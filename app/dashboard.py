from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .i18n import load_entity_translations
from .models import SetRecord


SORT_FIELDS = {"images": "image_count", "sets": "set_count", "size": "total_size", "avg_size": "average_image_size"}


def sort_items(items: list[dict], sort_by: str) -> list[dict]:
    field = SORT_FIELDS[sort_by]
    return sorted(
        items,
        key=lambda item: (-item[field], item["display_name"].casefold(), item["raw_name"].casefold()),
    )


def format_entity_name(raw_name: str, key: str, translations: dict[str, str]) -> str:
    translated = translations.get(key, "").strip()
    return translated or raw_name


def calculate_average_image_size(total_size: int, image_count: int) -> float:
    if image_count <= 0:
        return 0
    return total_size / image_count


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
    average_image_size = calculate_average_image_size(total_size, total_images)

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
                "average_image_size": 0,
            },
        )
        coser_entry["set_count"] += 1
        coser_entry["image_count"] += row.image_count
        coser_entry["total_size"] += row.total_size
        coser_entry["average_image_size"] = calculate_average_image_size(coser_entry["total_size"], coser_entry["image_count"])

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
                    "average_image_size": 0,
                },
            )
            character_entry["set_count"] += 1
            character_entry["image_count"] += row.image_count
            character_entry["total_size"] += row.total_size
            character_entry["average_image_size"] = calculate_average_image_size(character_entry["total_size"], character_entry["image_count"])

    return {
        "summary": {
            "totalCosers": len(coser_map),
            "totalSets": len(set_rows),
            "totalCharacters": len(character_map),
            "totalImages": total_images,
            "totalSize": total_size,
            "averageImageSize": average_image_size,
        },
        "cosers": sort_items(list(coser_map.values()), sort_by),
        "characters": sort_items(list(character_map.values()), sort_by),
    }
