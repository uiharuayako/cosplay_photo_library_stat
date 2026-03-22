from __future__ import annotations

import csv
import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .dashboard import SORT_FIELDS, build_dashboard_payload, calculate_average_image_size, format_entity_name
from .db import Base, SessionLocal, engine
from .i18n import (
    ensure_data_layout,
    get_ui_translations,
    list_available_locales,
    load_entity_translations,
    save_entity_translations,
)
from .models import ScanState, SetCharacter, SetRecord
from .scanner import library_has_data, normalize_key, read_scan_state, scan_is_running, start_scan


app = FastAPI(title="Cosplay Photo Library Stat")
app.mount("/static", StaticFiles(directory=settings.project_dir / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(settings.project_dir / "app" / "templates"))


ENTITY_TYPES = {"cosers", "characters"}
FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

BOLD_FONT_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


@app.on_event("startup")
def on_startup() -> None:
    ensure_data_layout()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        state = session.get(ScanState, 1)
        if state is None:
            session.add(ScanState(id=1))
        elif state.status == "running":
            state.status = "failed"
            state.message = "The previous scan was interrupted by an application restart."
        session.commit()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "default_locale": settings.default_locale,
            "default_sort": "images",
            "library_root": str(settings.library_root),
        },
    )


@app.get("/api/config")
def get_config() -> dict:
    locales = list_available_locales()
    locale_meta = []
    for locale in locales:
        ui = get_ui_translations(locale)
        locale_meta.append({"code": locale, "label": ui.get("locale_name", locale)})
    return {
        "defaultLocale": settings.default_locale,
        "defaultSort": "images",
        "supportedLocales": locale_meta,
        "libraryRoot": str(settings.library_root),
        "hasData": library_has_data(),
        "scanRunning": scan_is_running(),
    }


@app.get("/api/ui-translations/{locale}")
def ui_translations(locale: str) -> dict:
    return get_ui_translations(locale)


def get_db() -> Iterable[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def clamp_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    current = text
    while current and draw.textlength(f"{current}{suffix}", font=font) > max_width:
        current = current[:-1]
    return f"{current.rstrip()}{suffix}" if current else suffix


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    preferred_paths = BOLD_FONT_PATHS if bold else FONT_PATHS
    for path in preferred_paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def format_bytes_compact(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(value, 0))
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    precision = 0 if unit_index <= 1 else 2 if size < 10 else 1
    return f"{size:.{precision}f} {units[unit_index]}"


def get_cover_image_path(record: SetRecord) -> Path:
    if not record.cover_relative_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    image_path = resolve_library_relative_path(record.cover_relative_path, "cover")
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Cover source not found")
    return image_path


def resolve_library_relative_path(relative_path: str, path_label: str = "image") -> Path:
    image_path = (settings.library_root / relative_path).resolve()
    try:
        image_path.relative_to(settings.library_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {path_label} path") from exc
    return image_path


def get_image_thumbnail_path(image_relative_path: str, target_size: int, cache_key: str | None = None) -> Path:
    image_path = resolve_library_relative_path(image_relative_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image source not found")
    unique_key = cache_key or hashlib.sha1(image_relative_path.encode("utf-8")).hexdigest()
    thumb_name = f"{unique_key}-{target_size}.jpg"
    thumb_path = settings.thumbnail_dir / thumb_name
    if not thumb_path.exists() or thumb_path.stat().st_mtime < image_path.stat().st_mtime:
        try:
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                image.thumbnail((target_size, target_size))
                image.save(thumb_path, format="JPEG", quality=82, optimize=True)
        except (OSError, UnidentifiedImageError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to build thumbnail: {exc}") from exc
    return thumb_path


def get_thumbnail_path(record: SetRecord, target_size: int) -> Path:
    if not record.cover_relative_path:
        raise HTTPException(status_code=404, detail="Cover not found")
    return get_image_thumbnail_path(record.cover_relative_path, target_size, cache_key=f"set-{record.id}")


def pick_poster_image_relative_path(record: SetRecord) -> str | None:
    candidate_paths: list[str] = []
    set_images = sorted(record.images, key=lambda item: item.image_index)
    if set_images:
        candidate_paths.extend(image.relative_path for image in set_images[:12])
    if record.cover_relative_path:
        candidate_paths.append(record.cover_relative_path)

    seen: set[str] = set()
    unique_candidates = []
    for relative_path in candidate_paths:
        if relative_path and relative_path not in seen:
            seen.add(relative_path)
            unique_candidates.append(relative_path)

    fallback_path: str | None = unique_candidates[0] if unique_candidates else None
    for relative_path in unique_candidates:
        image_path = resolve_library_relative_path(relative_path)
        if not image_path.exists():
            continue
        try:
            with Image.open(image_path) as candidate:
                width, height = candidate.size
        except (OSError, UnidentifiedImageError):
            continue
        if height >= width:
            return relative_path
    return fallback_path


def list_set_image_relative_paths_from_disk(set_relative_path: str) -> list[str]:
    set_path = resolve_library_relative_path(set_relative_path, "set")
    if not set_path.exists() or not set_path.is_dir():
        raise HTTPException(status_code=404, detail="Set folder not found")

    with os.scandir(set_path) as iterator:
        image_paths = [
            str(Path(entry.path).resolve().relative_to(settings.library_root))
            for entry in iterator
            if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.casefold() in settings.valid_extensions
        ]
    image_paths.sort(key=lambda value: Path(value).name.casefold())
    return image_paths


def serialize_set_images(record: SetRecord) -> list[dict]:
    images = []
    set_images = sorted(record.images, key=lambda item: item.image_index)
    if set_images:
        image_rows = [
            {
                "index": image.image_index,
                "fileName": image.file_name,
                "relativePath": image.relative_path,
            }
            for image in set_images
        ]
    else:
        image_rows = [
            {
                "index": index,
                "fileName": Path(relative_path).name,
                "relativePath": relative_path,
            }
            for index, relative_path in enumerate(list_set_image_relative_paths_from_disk(record.relative_path))
        ]

    for image in image_rows:
        images.append(
            {
                "index": image["index"],
                "fileName": image["fileName"],
                "relativePath": image["relativePath"],
                "thumbnailUrl": f"/api/sets/{record.id}/images/{image['index']}?size=420",
                "imageUrl": f"/api/sets/{record.id}/images/{image['index']}",
            }
        )
    return images


def build_ranking_poster(locale: str, sort: str, entity: str, session: Session) -> bytes:
    if entity not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported entity type")
    if sort not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Unsupported sort field")

    ui = get_ui_translations(locale)
    dashboard_payload = build_dashboard_payload(locale, sort, session)
    items = dashboard_payload[entity][:12]
    if not items:
        raise HTTPException(status_code=404, detail="No ranking data available")

    canvas_width = 2048
    padding = 56
    grid_gap = 24
    columns = 3
    card_width = (canvas_width - (padding * 2) - (grid_gap * (columns - 1))) // columns
    media_height = 520
    card_body_height = 176
    card_height = media_height + card_body_height
    rows = 4
    header_height = 208
    footer_height = 88
    canvas_height = header_height + (rows * card_height) + ((rows - 1) * grid_gap) + footer_height + padding

    image = Image.new("RGB", (canvas_width, canvas_height), "#f4ede5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, canvas_width, canvas_height), fill="#f4ede5")
    draw.ellipse((-120, -160, 760, 520), fill="#ead6c8")
    draw.ellipse((canvas_width - 720, -180, canvas_width + 160, 420), fill="#d8ebe3")
    draw.rounded_rectangle((26, 26, canvas_width - 26, canvas_height - 26), radius=38, fill="#fbf7f2", outline="#dfd0c1", width=2)

    title_font = load_font(68, bold=True)
    subtitle_font = load_font(26)
    badge_font = load_font(28, bold=True)
    stat_font = load_font(28, bold=True)
    name_font = load_font(38, bold=True)
    meta_font = load_font(24)
    footer_font = load_font(24)

    entity_title = ui.get("coser_cover_title", "Coser cover ranking") if entity == "cosers" else ui.get("character_cover_title", "Character cover ranking")
    sort_label = ui.get(f"sort_{sort}", sort.title())
    summary = dashboard_payload["summary"]

    title_badge = ui.get("sort_current_label", "Current ranking metric")
    badge_text = f"{title_badge}: {sort_label}"
    badge_width = draw.textlength(badge_text, font=subtitle_font) + 34
    badge_box = (padding, 36, padding + badge_width, 84)
    draw.rounded_rectangle(badge_box, radius=18, fill="#fff5ea", outline="#edcfbb")
    draw.text((badge_box[0] + 17, badge_box[1] + 10), badge_text, fill="#9d5435", font=subtitle_font)

    title_y = 92
    draw.text((padding, title_y), entity_title, fill="#1f1a16", font=title_font, stroke_width=2, stroke_fill="#1f1a16")

    summary_cards = [
        (ui.get("summary_total_sets", "Sets"), f"{summary['totalSets']:,}"),
        (ui.get("summary_total_images", "Images"), f"{summary['totalImages']:,}"),
        (ui.get("summary_total_size", "Total size"), format_bytes_compact(summary["totalSize"])),
    ]
    title_right = padding + draw.textlength(entity_title, font=title_font) + 48
    summary_gap = 14
    summary_row_height = 34
    summary_width = 372
    summary_x = max(title_right, canvas_width - padding - summary_width)
    summary_y = 34
    for label, value in summary_cards:
        card_box = (summary_x, summary_y, summary_x + summary_width, summary_y + summary_row_height)
        draw.text((card_box[0], card_box[1]), label, fill="#7a6b5f", font=meta_font)
        value_width = draw.textlength(value, font=badge_font)
        value_x = max(card_box[0] + 170, card_box[2] - value_width)
        draw.text((value_x, card_box[1] - 1), value, fill="#1f1a16", font=badge_font)
        summary_y += summary_row_height + summary_gap

    generated_text = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    generated_width = draw.textlength(generated_text, font=footer_font)
    generated_x = canvas_width - padding - generated_width
    generated_y = max(title_y + 70, summary_y + 4)
    draw.text((generated_x, generated_y), generated_text, fill="#7a6b5f", font=footer_font)

    for index, item in enumerate(items):
        row = index // columns
        column = index % columns
        x = padding + column * (card_width + grid_gap)
        y = header_height + row * (card_height + grid_gap)
        card_box = (x, y, x + card_width, y + card_height)
        media_box = (x, y, x + card_width, y + media_height)
        body_box = (x, y + media_height, x + card_width, y + card_height)

        shadow_box = (x + 6, y + 10, x + card_width + 6, y + card_height + 10)
        draw.rounded_rectangle(shadow_box, radius=24, fill="#e7d8ca")
        draw.rounded_rectangle(card_box, radius=24, fill="#fffdf9", outline="#eadacb", width=2)

        record = session.get(SetRecord, item["cover_set_id"]) if item.get("cover_set_id") else None
        chosen_relative_path = pick_poster_image_relative_path(record) if record is not None else None
        if chosen_relative_path:
            image_path = resolve_library_relative_path(chosen_relative_path)
            with Image.open(image_path) as source_image:
                source_rgb = source_image.convert("RGB")
                background = ImageOps.fit(source_rgb, (card_width, media_height), method=Image.Resampling.LANCZOS)
                background = background.filter(ImageFilter.GaussianBlur(radius=18))
                background = Image.blend(background, Image.new("RGB", background.size, "#2a211a"), 0.24)
                cover = ImageOps.contain(source_rgb, (card_width, media_height), method=Image.Resampling.LANCZOS)
            composed = background.copy()
            paste_x = (card_width - cover.width) // 2
            paste_y = (media_height - cover.height) // 2
            composed.paste(cover, (paste_x, paste_y))
            mask = Image.new("L", (card_width, media_height), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_width, media_height + 24), radius=24, fill=255)
            image.paste(composed, media_box[:2], mask)
        else:
            draw.rounded_rectangle(media_box, radius=24, fill="#ddd2c7")
            placeholder = ui.get("not_available", "Not available")
            placeholder_width = draw.textlength(placeholder, font=name_font)
            draw.text((x + (card_width - placeholder_width) / 2, y + (media_height - 26) / 2), placeholder, fill="#6d6258", font=name_font)

        overlay_top = y + media_height - 90
        draw.rectangle((x, overlay_top, x + card_width, y + media_height), fill="#17120e")
        badge_text = f"#{index + 1}"
        badge_box = (x + 18, y + 18, x + 104, y + 62)
        draw.rounded_rectangle(badge_box, radius=20, fill="#fff8ef", outline="#edd8c5")
        draw.text((badge_box[0] + 15, badge_box[1] + 8), badge_text, fill="#1f1a16", font=badge_font)

        stat_text = (
            str(item["image_count"])
            if sort == "images"
            else str(item["set_count"])
            if sort == "sets"
            else format_bytes_compact(item["total_size"])
            if sort == "size"
            else format_bytes_compact(item["average_image_size"])
        )
        stat_width = draw.textlength(stat_text, font=stat_font)
        stat_box = (x + card_width - stat_width - 42, y + media_height - 62, x + card_width - 18, y + media_height - 16)
        draw.rounded_rectangle(stat_box, radius=18, fill="#fff8ee")
        draw.text((stat_box[0] + 12, stat_box[1] + 8), stat_text, fill="#8f3f29", font=stat_font)

        text_left = x + 20
        text_top = body_box[1] + 16
        max_text_width = card_width - 40
        name_text = clamp_text(draw, item["display_name"], name_font, max_text_width)
        metric_text = clamp_text(draw, f"{sort_label} · {stat_text}", stat_font, max_text_width)
        meta_text = clamp_text(
            draw,
            f"{ui.get('sets', 'Sets')} {item['set_count']:,} · {ui.get('images', 'Images')} {item['image_count']:,}",
            meta_font,
            max_text_width,
        )
        size_text = clamp_text(draw, f"{ui.get('size', 'Size')} {format_bytes_compact(item['total_size'])}", meta_font, max_text_width)
        draw.text((text_left, text_top), name_text, fill="#1f1a16", font=name_font, stroke_width=1, stroke_fill="#1f1a16")
        draw.text((text_left, text_top + 48), metric_text, fill="#8f3f29", font=stat_font)
        draw.text((text_left, text_top + 86), meta_text, fill="#6d6258", font=meta_font)
        draw.text((text_left, text_top + 118), size_text, fill="#6d6258", font=meta_font)

    footer_text = "Cosplay Photo Library Stat"
    draw.text((padding, canvas_height - 56), footer_text, fill="#7a6b5f", font=footer_font)

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


@app.get("/api/dashboard")
def dashboard(
    locale: str = Query(default=settings.default_locale),
    sort: str = Query(default="images"),
    session: Session = Depends(get_db),
) -> dict:
    payload = build_dashboard_payload(locale, sort, session)
    payload["summary"]["lastCompletedScan"] = read_scan_state().get("finished_at")
    return payload


@app.get("/api/library/options")
def library_options(
    locale: str = Query(default=settings.default_locale),
    session: Session = Depends(get_db),
) -> dict:
    dashboard_payload = build_dashboard_payload(locale, "images", session)
    return {
        "cosers": [
            {"key": item["key"], "label": item["display_name"], "raw_name": item["raw_name"]}
            for item in dashboard_payload["cosers"]
        ],
        "characters": [
            {"key": item["key"], "label": item["display_name"], "raw_name": item["raw_name"]}
            for item in dashboard_payload["characters"]
        ],
    }


def serialize_set(
    record: SetRecord,
    coser_translations: dict[str, str],
    character_translations: dict[str, str],
) -> dict:
    return {
        "id": record.id,
        "setName": record.set_name,
        "relativePath": record.relative_path,
        "imageCount": record.image_count,
        "totalSize": record.total_size,
        "averageImageSize": calculate_average_image_size(record.total_size, record.image_count),
        "coser": {
            "key": record.coser_key,
            "rawName": record.coser_name,
            "displayName": format_entity_name(record.coser_name, record.coser_key, coser_translations),
        },
        "characters": [
            {
                "key": relation.character_key,
                "rawName": relation.character_name,
                "displayName": format_entity_name(
                    relation.character_name,
                    relation.character_key,
                    character_translations,
                ),
            }
            for relation in sorted(record.characters, key=lambda item: item.character_name.casefold())
        ],
        "coverUrl": f"/api/sets/{record.id}/cover",
    }


@app.get("/api/cosers/{coser_key}")
def coser_detail(
    coser_key: str,
    locale: str = Query(default=settings.default_locale),
    sort: str = Query(default="images"),
    session: Session = Depends(get_db),
) -> dict:
    if sort not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Unsupported sort field")
    rows = session.execute(
        select(SetRecord)
        .where(SetRecord.coser_key == coser_key)
        .options(selectinload(SetRecord.characters))
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Coser not found")

    coser_translations = load_entity_translations("cosers", locale)
    character_translations = load_entity_translations("characters", locale)
    raw_name = rows[0].coser_name
    sets_payload = [serialize_set(record, coser_translations, character_translations) for record in rows]
    field = {"images": "imageCount", "sets": None, "size": "totalSize", "avg_size": "averageImageSize"}[sort]
    if field is None:
        sets_payload.sort(key=lambda item: (item["setName"].casefold(),))
    else:
        sets_payload.sort(key=lambda item: (-item[field], item["setName"].casefold()))
    return {
        "entity": {
            "key": coser_key,
            "rawName": raw_name,
            "displayName": format_entity_name(raw_name, coser_key, coser_translations),
            "setCount": len(rows),
            "imageCount": sum(row.image_count for row in rows),
            "totalSize": sum(row.total_size for row in rows),
            "averageImageSize": calculate_average_image_size(sum(row.total_size for row in rows), sum(row.image_count for row in rows)),
        },
        "sets": sets_payload,
    }


@app.get("/api/characters/{character_key}")
def character_detail(
    character_key: str,
    locale: str = Query(default=settings.default_locale),
    sort: str = Query(default="images"),
    session: Session = Depends(get_db),
) -> dict:
    if sort not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Unsupported sort field")
    rows = session.execute(
        select(SetRecord)
        .join(SetCharacter, SetCharacter.set_id == SetRecord.id)
        .where(SetCharacter.character_key == character_key)
        .options(selectinload(SetRecord.characters))
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Character not found")

    coser_translations = load_entity_translations("cosers", locale)
    character_translations = load_entity_translations("characters", locale)
    raw_name = next(
        (
            relation.character_name
            for record in rows
            for relation in record.characters
            if relation.character_key == character_key
        ),
        character_key,
    )
    sets_payload = [serialize_set(record, coser_translations, character_translations) for record in rows]
    field = {"images": "imageCount", "sets": None, "size": "totalSize", "avg_size": "averageImageSize"}[sort]
    if field is None:
        sets_payload.sort(key=lambda item: (item["setName"].casefold(),))
    else:
        sets_payload.sort(key=lambda item: (-item[field], item["setName"].casefold()))
    return {
        "entity": {
            "key": character_key,
            "rawName": raw_name,
            "displayName": format_entity_name(raw_name, character_key, character_translations),
            "setCount": len(rows),
            "imageCount": sum(row.image_count for row in rows),
            "totalSize": sum(row.total_size for row in rows),
            "averageImageSize": calculate_average_image_size(sum(row.total_size for row in rows), sum(row.image_count for row in rows)),
        },
        "sets": sets_payload,
    }


@app.get("/api/scan/status")
def scan_status() -> dict:
    state = read_scan_state()
    state["hasData"] = library_has_data()
    state["scanRunning"] = scan_is_running()
    return state


@app.post("/api/scan/start")
def begin_scan() -> dict:
    if not start_scan():
        raise HTTPException(status_code=409, detail="A scan is already running")
    return {"started": True}


@app.get("/api/sets/{set_id}/cover")
def set_cover(set_id: int, size: int | None = Query(default=None), session: Session = Depends(get_db)):
    record = session.get(SetRecord, set_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Cover not found")

    target_size = max(64, min(size or settings.thumbnail_size, 1024))
    thumb_path = get_thumbnail_path(record, target_size)
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/api/sets/{set_id}")
def set_detail(set_id: int, locale: str = Query(default=settings.default_locale), session: Session = Depends(get_db)) -> dict:
    record = session.execute(
        select(SetRecord)
        .where(SetRecord.id == set_id)
        .options(selectinload(SetRecord.characters), selectinload(SetRecord.images))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Set not found")

    coser_translations = load_entity_translations("cosers", locale)
    character_translations = load_entity_translations("characters", locale)
    payload = serialize_set(record, coser_translations, character_translations)
    payload["images"] = serialize_set_images(record)
    return payload


@app.get("/api/sets/{set_id}/images/{image_index}")
def set_image(
    set_id: int,
    image_index: int,
    size: int | None = Query(default=None),
    session: Session = Depends(get_db),
):
    record = session.execute(
        select(SetRecord)
        .where(SetRecord.id == set_id)
        .options(selectinload(SetRecord.images))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Set not found")

    image_payload = next((item for item in serialize_set_images(record) if item["index"] == image_index), None)
    if image_payload is None:
        raise HTTPException(status_code=404, detail="Image not found")

    image_relative_path = image_payload["relativePath"]
    image_path = resolve_library_relative_path(image_relative_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image source not found")

    if size is not None:
        target_size = max(64, min(size, 1600))
        thumb_path = get_image_thumbnail_path(image_relative_path, target_size)
        return FileResponse(thumb_path, media_type="image/jpeg")

    media_type = f"image/{image_path.suffix.lstrip('.').lower()}"
    if media_type == "image/jpg":
        media_type = "image/jpeg"
    return FileResponse(image_path, media_type=media_type)


@app.get("/api/rankings/{entity}/poster")
def export_ranking_poster(
    entity: str,
    locale: str = Query(default=settings.default_locale),
    sort: str = Query(default="images"),
    session: Session = Depends(get_db),
):
    poster = build_ranking_poster(locale, sort, entity, session)
    filename = f"{entity}-{sort}-{locale}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.png"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(poster), media_type="image/png", headers=headers)


@app.get("/api/i18n/export")
def export_translations(
    entity: str = Query(...),
    locale: str = Query(...),
    session: Session = Depends(get_db),
):
    if entity not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported entity type")

    translations = load_entity_translations(entity, locale)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["key", "raw_name", "translation"],
    )
    writer.writeheader()

    dashboard_payload = build_dashboard_payload(locale, "images", session)
    rows = dashboard_payload[entity]
    for row in rows:
        writer.writerow(
            {
                "key": row["key"],
                "raw_name": row["raw_name"],
                "translation": translations.get(row["key"], ""),
            }
        )

    filename = f"{entity}-{locale}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv", headers=headers)


@app.post("/api/i18n/import")
async def import_translations(
    entity: str = Query(...),
    locale: str = Query(...),
    file: UploadFile = File(...),
) -> dict:
    if entity not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported entity type")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"translation"}.issubset({field.casefold() for field in reader.fieldnames}):
        raise HTTPException(status_code=400, detail="CSV must contain a translation column")

    translations = load_entity_translations(entity, locale)
    updated = 0
    for row in reader:
        lowered_row = {key.casefold(): value for key, value in row.items()}
        translation = (lowered_row.get("translation") or "").strip()
        key = (lowered_row.get("key") or "").strip()
        raw_name = (lowered_row.get("raw_name") or "").strip()
        if not key and raw_name:
            key = normalize_key(raw_name)
        if not key or not translation:
            continue
        translations[key] = translation
        updated += 1
    save_entity_translations(entity, locale, translations)
    return {"updated": updated}
