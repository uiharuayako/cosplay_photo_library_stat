from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Iterable

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
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
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
    preferred_paths = []
    if bold:
        preferred_paths.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    preferred_paths.extend(FONT_PATHS)
    for path in preferred_paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def get_cover_image_path(record: SetRecord) -> Path:
    if not record.cover_relative_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    image_path = (settings.library_root / record.cover_relative_path).resolve()
    try:
        image_path.relative_to(settings.library_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cover path") from exc

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Cover source not found")
    return image_path


def get_thumbnail_path(record: SetRecord, target_size: int) -> Path:
    image_path = get_cover_image_path(record)
    thumb_name = f"set-{record.id}-{target_size}.jpg"
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

    canvas_width = 1660
    padding = 48
    grid_gap = 24
    columns = 4
    card_width = (canvas_width - (padding * 2) - (grid_gap * (columns - 1))) // columns
    media_height = 390
    card_body_height = 164
    card_height = media_height + card_body_height
    rows = 3
    header_height = 170
    footer_height = 48
    canvas_height = header_height + (rows * card_height) + ((rows - 1) * grid_gap) + footer_height + padding

    image = Image.new("RGB", (canvas_width, canvas_height), "#f6f0e7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, canvas_width, canvas_height), fill="#f6f0e7")
    draw.rounded_rectangle((24, 24, canvas_width - 24, canvas_height - 24), radius=34, fill="#fbf8f2", outline="#e0d4c6", width=2)

    title_font = load_font(46, bold=True)
    subtitle_font = load_font(22)
    badge_font = load_font(22, bold=True)
    stat_font = load_font(20, bold=True)
    name_font = load_font(26, bold=True)
    meta_font = load_font(18)

    entity_title = ui.get("coser_cover_title", "Coser cover ranking") if entity == "cosers" else ui.get("character_cover_title", "Character cover ranking")
    sort_label = ui.get(f"sort_{sort}", sort.title())
    summary = dashboard_payload["summary"]

    draw.text((padding, 42), entity_title, fill="#1f1a16", font=title_font)
    draw.text(
        (padding, 98),
        f"{ui.get('sort_current_label', 'Current ranking metric')}: {sort_label}   {ui.get('summary_total_sets', 'Sets')}: {summary['totalSets']}   {ui.get('summary_total_images', 'Images')}: {summary['totalImages']}",
        fill="#6d6258",
        font=subtitle_font,
    )

    for index, item in enumerate(items):
        row = index // columns
        column = index % columns
        x = padding + column * (card_width + grid_gap)
        y = header_height + row * (card_height + grid_gap)
        card_box = (x, y, x + card_width, y + card_height)
        media_box = (x, y, x + card_width, y + media_height)
        body_box = (x, y + media_height, x + card_width, y + card_height)

        draw.rounded_rectangle(card_box, radius=26, fill="#fffdf8", outline="#e6d9cc", width=2)

        record = session.get(SetRecord, item["cover_set_id"]) if item.get("cover_set_id") else None
        if record is not None and record.cover_relative_path:
            thumb_path = get_thumbnail_path(record, 720)
            with Image.open(thumb_path) as thumb:
                cover = ImageOps.fit(thumb.convert("RGB"), (card_width, media_height), method=Image.Resampling.LANCZOS)
            mask = Image.new("L", (card_width, media_height), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_width, media_height + 36), radius=26, fill=255)
            image.paste(cover, media_box[:2], mask)
        else:
            draw.rounded_rectangle(media_box, radius=26, fill="#ddd2c7")
            placeholder = ui.get("not_available", "Not available")
            placeholder_width = draw.textlength(placeholder, font=name_font)
            draw.text((x + (card_width - placeholder_width) / 2, y + (media_height - 26) / 2), placeholder, fill="#6d6258", font=name_font)

        overlay_top = y + media_height - 96
        draw.rectangle((x, overlay_top, x + card_width, y + media_height), fill="#15110d")
        badge_text = f"#{index + 1}"
        badge_box = (x + 18, y + 18, x + 88, y + 54)
        draw.rounded_rectangle(badge_box, radius=18, fill="#fff8ee", outline="#eadacc")
        draw.text((badge_box[0] + 16, badge_box[1] + 8), badge_text, fill="#1f1a16", font=badge_font)

        stat_text = (
            str(item["image_count"])
            if sort == "images"
            else str(item["set_count"])
            if sort == "sets"
            else f"{round(item['total_size'] / (1024 * 1024 * 1024), 2)} GB"
            if sort == "size"
            else f"{round(item['average_image_size'] / (1024 * 1024), 2)} MB"
        )
        stat_width = draw.textlength(stat_text, font=stat_font)
        stat_box = (x + card_width - stat_width - 38, y + media_height - 58, x + card_width - 18, y + media_height - 18)
        draw.rounded_rectangle(stat_box, radius=16, fill="#fff8ee")
        draw.text((stat_box[0] + 12, stat_box[1] + 8), stat_text, fill="#8f3f29", font=stat_font)

        text_left = x + 18
        text_top = body_box[1] + 16
        max_text_width = card_width - 36
        name_text = clamp_text(draw, item["display_name"], name_font, max_text_width)
        metric_text = clamp_text(draw, f"{sort_label} · {stat_text}", stat_font, max_text_width)
        meta_text = clamp_text(
            draw,
            f"{ui.get('sets', 'Sets')} {item['set_count']} · {ui.get('images', 'Images')} {item['image_count']}",
            meta_font,
            max_text_width,
        )
        size_text = clamp_text(draw, f"{ui.get('size', 'Size')} {round(item['total_size'] / (1024 * 1024), 2)} MB", meta_font, max_text_width)
        avg_size_text = clamp_text(
            draw,
            f"{ui.get('avg_size', 'Avg image size')} {round(item['average_image_size'] / (1024 * 1024), 2)} MB",
            meta_font,
            max_text_width,
        )
        draw.text((text_left, text_top), name_text, fill="#1f1a16", font=name_font)
        draw.text((text_left, text_top + 38), metric_text, fill="#8f3f29", font=stat_font)
        draw.text((text_left, text_top + 74), meta_text, fill="#6d6258", font=meta_font)
        draw.text((text_left, text_top + 100), size_text, fill="#6d6258", font=meta_font)
        draw.text((text_left, text_top + 126), avg_size_text, fill="#6d6258", font=meta_font)

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
