# Cosplay Photo Library Stat

A rebuilt web application for large-scale cosplay photo libraries.

This version replaces the old Streamlit prototype with a FastAPI + server-rendered frontend architecture focused on:

- persistent scan cache stored in SQLite by default, with optional MySQL support
- live full-scan progress updates showing the current folder and cumulative counts
- full rankings for all cosers and all characters
- sortable statistics by image count, set count, or total size
- on-demand cover thumbnails with thumbnail cache persistence
- export / import flows for entity translation CSV files
- multilingual UI text driven by JSON locale files mounted from the host

## Expected library structure

The scanner expects a strict directory layout:

```text
LIBRARY_ROOT/
├── arty huang/
│   ├── arty huang - alicization administrator/
│   │   ├── artyhuang_alicizationadministrator_001.jpg
│   │   └── ...
│   └── arty huang - asuna/
└── alexis lust/
    └── alexis lust - triss merigold, jennefer/
```

Rules:

- level 1 directory name = coser name
- level 2 directory name must contain ` - `
- the part after ` - ` is parsed as the character segment
- multiple characters are split by English commas `,`
- trailing numeric suffixes in characters such as `nyotengu 2` are normalized to `nyotengu`

## Architecture

### Backend

- FastAPI application under `app/`
- SQLAlchemy models for cached set metadata and scan state
- background scan worker for full library traversal
- JSON translation files stored under the mapped data directory
- thumbnail cache stored under the mapped data directory

### Persistence layout

When `DATA_DIR=/data`, the app writes:

```text
/data/
├── cache/
│   ├── library.sqlite3
│   └── thumbnails/
└── i18n/
    ├── entities/
    │   ├── characters.en.json
    │   ├── characters.ja.json
    │   ├── characters.zh-CN.json
    │   ├── cosers.en.json
    │   ├── cosers.ja.json
    │   └── cosers.zh-CN.json
    └── ui/
        ├── en.json
        ├── ja.json
        └── zh-CN.json
```

The whole `/data` directory should be mounted to the host so scan cache, thumbnails, and i18n files survive container recreation.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export LIBRARY_ROOT=/absolute/path/to/cosplay_photo_library_v3
export DATA_DIR=$(pwd)/data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Open [http://localhost:8080](http://localhost:8080).

## Docker deployment

### SQLite mode (recommended default)

1. Copy `docker-compose.yml.example` to `docker-compose.yml`
2. Adjust the host paths
3. Start the container

```bash
docker compose up -d --build
```

Example mapping:

- host `./app_data` -> container `/data`
- host `/path/to/cosplay_photo_library_v3` -> container `/library:ro`

### Optional MySQL mode

If you want metadata in MySQL instead of SQLite, replace `DATABASE_URL` with:

```text
mysql+pymysql://<username>:<password>@<mysql-host>:3306/<database>?charset=utf8mb4
```

Notes:

- the image library mount is still required because covers and scans read the files directly
- the `/data` volume is still required because thumbnails and i18n JSON files remain file-based
- SQLite is simpler to operate for a single-instance deployment and is the default

## Features

### Live scan progress

During a full scan, the UI shows:

- current coser folder
- current set folder
- processed coser count vs total coser count
- cumulative set count, image count, and total storage size

Scan results are committed after the traversal finishes successfully, so a failed scan will not wipe the last successful cache.

### Rankings and sorting

All ranking views default to descending image count.

Users can switch sorting to:

- image count
- set count
- total file size

Both coser and character dashboards respect the active sort metric.

### Cover thumbnails

The app stores one cover path per set and generates JPEG thumbnails on demand into `/data/cache/thumbnails`.

### i18n workflow

The application supports multilingual UI and multilingual entity names.

- UI strings are JSON files in `/data/i18n/ui`
- coser translations are JSON files in `/data/i18n/entities/cosers.<locale>.json`
- character translations are JSON files in `/data/i18n/entities/characters.<locale>.json`
- export CSV files from the UI for AI localization
- import translated CSV files back into the app

CSV exports include:

- `key`
- `raw_name`
- `translation`
- `set_count`
- `image_count`
- `total_size`

## API overview

- `GET /api/config`
- `GET /api/dashboard?locale=zh-CN&sort=images`
- `GET /api/cosers/{key}?locale=zh-CN&sort=images`
- `GET /api/characters/{key}?locale=zh-CN&sort=images`
- `GET /api/scan/status`
- `POST /api/scan/start`
- `GET /api/sets/{id}/cover`
- `GET /api/i18n/export?entity=cosers&locale=zh-CN`
- `POST /api/i18n/import?entity=cosers&locale=zh-CN`

## Important operational notes

- The scanner reads only direct image files inside each level-2 set folder.
- Image files are never modified.
- The recommended library mount is read-only.
- This repository does not include your NAS data; you must mount it into the container.
- If your deployment environment cannot reach the NAS path or MySQL host, the app will start, but scans will fail until connectivity is fixed.
