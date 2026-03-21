from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import settings
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


SORT_FIELDS = {"images": "image_count", "sets": "set_count", "size": "total_size"}
ENTITY_TYPES = {"cosers", "characters"}


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


def sort_items(items: list[dict], sort_by: str) -> list[dict]:
    field = SORT_FIELDS[sort_by]
    return sorted(
        items,
        key=lambda item: (-item[field], item["display_name"].casefold(), item["raw_name"].casefold()),
    )


def format_entity_name(raw_name: str, key: str, translations: dict[str, str]) -> str:
    translated = translations.get(key, "").strip()
    return translated or raw_name


def build_dashboard_payload(locale: str, sort_by: str, session: Session) -> dict:
    if sort_by not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail="Unsupported sort field")

    coser_translations = load_entity_translations("cosers", locale)
    character_translations = load_entity_translations("characters", locale)
    set_rows = session.execute(
        select(SetRecord).options(selectinload(SetRecord.characters)).order_by(SetRecord.coser_name, SetRecord.set_name)
    ).scalars().all()

    total_images = sum(item.image_count for item in set_rows)
    total_size = sum(item.total_size for item in set_rows)

    coser_map: dict[str, dict] = {}
    character_map: dict[str, dict] = {}

    for row in set_rows:
        coser_entry = coser_map.setdefault(
            row.coser_key,
            {
                "key": row.coser_key,
                "raw_name": row.coser_name,
                "display_name": format_entity_name(row.coser_name, row.coser_key, coser_translations),
                "set_count": 0,
                "image_count": 0,
                "total_size": 0,
                "cover_set_id": row.id,
            },
        )
        coser_entry["set_count"] += 1
        coser_entry["image_count"] += row.image_count
        coser_entry["total_size"] += row.total_size

        for relation in row.characters:
            character_entry = character_map.setdefault(
                relation.character_key,
                {
                    "key": relation.character_key,
                    "raw_name": relation.character_name,
                    "display_name": format_entity_name(
                        relation.character_name,
                        relation.character_key,
                        character_translations,
                    ),
                    "set_count": 0,
                    "image_count": 0,
                    "total_size": 0,
                    "cover_set_id": row.id,
                },
            )
            character_entry["set_count"] += 1
            character_entry["image_count"] += row.image_count
            character_entry["total_size"] += row.total_size

    scan_state = read_scan_state()
    return {
        "summary": {
            "totalCosers": len(coser_map),
            "totalSets": len(set_rows),
            "totalCharacters": len(character_map),
            "totalImages": total_images,
            "totalSize": total_size,
            "lastCompletedScan": scan_state.get("finished_at"),
        },
        "cosers": sort_items(list(coser_map.values()), sort_by),
        "characters": sort_items(list(character_map.values()), sort_by),
    }


@app.get("/api/dashboard")
def dashboard(
    locale: str = Query(default=settings.default_locale),
    sort: str = Query(default="images"),
    session: Session = Depends(get_db),
) -> dict:
    return build_dashboard_payload(locale, sort, session)


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
    field = {"images": "imageCount", "sets": None, "size": "totalSize"}[sort]
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
    field = {"images": "imageCount", "sets": None, "size": "totalSize"}[sort]
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
    if record is None or not record.cover_relative_path:
        raise HTTPException(status_code=404, detail="Cover not found")

    image_path = (settings.library_root / record.cover_relative_path).resolve()
    try:
        image_path.relative_to(settings.library_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cover path") from exc

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Cover source not found")

    target_size = max(64, min(size or settings.thumbnail_size, 1024))
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

    return FileResponse(thumb_path, media_type="image/jpeg")


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
        fieldnames=["key", "raw_name", "translation", "set_count", "image_count", "total_size"],
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
                "set_count": row["set_count"],
                "image_count": row["image_count"],
                "total_size": row["total_size"],
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
