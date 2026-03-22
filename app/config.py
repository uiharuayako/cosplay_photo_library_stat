from __future__ import annotations

import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.project_dir = base_dir
        self.data_dir = Path(os.getenv("DATA_DIR", base_dir / "data")).expanduser().resolve()
        configured_library_root = os.getenv("LIBRARY_ROOT") or os.getenv("NAS_BASE_PATH")
        if configured_library_root:
            library_root = Path(configured_library_root).expanduser().resolve()
        else:
            candidate_roots = [
                Path("/Volumes/data/Otaku/cosplay_photo_library_v3"),
                Path("/mnt/share/user/Otaku/cosplay_photo_library_v3"),
                Path("/mnt/user/Otaku/cosplay_photo_library_v3"),
                base_dir / "cosplay_data",
            ]
            library_root = next((path.resolve() for path in candidate_roots if path.exists()), (base_dir / "cosplay_data").resolve())
        self.library_root = library_root
        self.cache_dir = self.data_dir / "cache"
        self.thumbnail_dir = self.cache_dir / "thumbnails"
        self.i18n_dir = self.data_dir / "i18n"
        self.ui_i18n_dir = self.i18n_dir / "ui"
        self.entity_i18n_dir = self.i18n_dir / "entities"
        self.default_ui_i18n_dir = base_dir / "app" / "default_data" / "ui"
        default_db_path = self.cache_dir / "library.sqlite3"
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{default_db_path}")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8080"))
        self.thumbnail_size = int(os.getenv("THUMBNAIL_SIZE", "360"))
        self.valid_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".bmp",
            ".avif",
            ".heic",
            ".heif",
        }
        self.default_locale = os.getenv("DEFAULT_LOCALE", "zh-CN")


settings = Settings()
