from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import settings


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def ensure_data_layout() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.thumbnail_dir.mkdir(parents=True, exist_ok=True)
    settings.ui_i18n_dir.mkdir(parents=True, exist_ok=True)
    settings.entity_i18n_dir.mkdir(parents=True, exist_ok=True)

    for source_file in settings.default_ui_i18n_dir.glob("*.json"):
        target_file = settings.ui_i18n_dir / source_file.name
        if not target_file.exists():
            target_file.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")

    for locale in list_available_locales():
        for prefix in ("cosers", "characters"):
            file_path = entity_translation_path(prefix, locale)
            if not file_path.exists():
                _write_json(file_path, {})


def list_available_locales() -> list[str]:
    locales = sorted(path.stem for path in settings.ui_i18n_dir.glob("*.json"))
    if settings.default_locale not in locales:
        locales.insert(0, settings.default_locale)
    return list(dict.fromkeys(locales))


def get_ui_translations(locale: str) -> dict[str, Any]:
    payload = _load_json(settings.default_ui_i18n_dir / f"{settings.default_locale}.json", {}).copy()
    payload.update(_load_json(settings.ui_i18n_dir / f"{settings.default_locale}.json", {}))
    if locale != settings.default_locale:
        payload.update(_load_json(settings.default_ui_i18n_dir / f"{locale}.json", {}))
        payload.update(_load_json(settings.ui_i18n_dir / f"{locale}.json", {}))
    return payload


def entity_translation_path(entity_type: str, locale: str) -> Path:
    if entity_type not in {"cosers", "characters"}:
        raise ValueError(f"Unsupported entity type: {entity_type}")
    return settings.entity_i18n_dir / f"{entity_type}.{locale}.json"


def load_entity_translations(entity_type: str, locale: str) -> dict[str, str]:
    path = entity_translation_path(entity_type, locale)
    return _load_json(path, {})


def save_entity_translations(entity_type: str, locale: str, translations: dict[str, str]) -> None:
    path = entity_translation_path(entity_type, locale)
    _write_json(path, translations)
