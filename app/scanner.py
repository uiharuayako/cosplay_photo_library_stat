from __future__ import annotations

import os
import re
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import SessionLocal
from .models import ScanState, SetCharacter, SetImage, SetRecord


_trailing_suffix_re = re.compile(r"\s+\d+$")
_scan_lock = Lock()
_executor = ThreadPoolExecutor(max_workers=1)
_scan_future: Future[None] | None = None


@dataclass(slots=True)
class SetPayload:
    coser_key: str
    coser_name: str
    set_name: str
    relative_path: str
    image_count: int
    total_size: int
    cover_relative_path: str | None
    image_relative_paths: list[str]
    characters: list[tuple[str, str]]


def normalize_key(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def clean_character_name(value: str) -> str:
    return _trailing_suffix_re.sub("", " ".join(value.strip().split()))


def parse_character_names(set_name: str) -> list[tuple[str, str]]:
    if " - " not in set_name:
        return []
    _, character_part = set_name.split(" - ", 1)
    results: list[tuple[str, str]] = []
    for raw_character in character_part.split(","):
        cleaned = clean_character_name(raw_character)
        if not cleaned:
            continue
        results.append((normalize_key(cleaned), cleaned))
    return results or [("unknown", "Unknown")]


def scan_set(set_path: Path, library_root: Path) -> tuple[int, int, str | None, list[str]]:
    image_count = 0
    total_size = 0
    cover_name: str | None = None
    cover_relative_path: str | None = None
    image_relative_paths: list[str] = []

    with os.scandir(set_path) as iterator:
        for entry in iterator:
            if not entry.is_file(follow_symlinks=False):
                continue
            extension = Path(entry.name).suffix.casefold()
            if extension not in settings.valid_extensions:
                continue
            image_count += 1
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            total_size += stat_result.st_size
            image_relative_paths.append(str(Path(entry.path).resolve().relative_to(library_root)))
            lowered_name = entry.name.casefold()
            if cover_name is None or lowered_name < cover_name:
                cover_name = lowered_name
                cover_relative_path = str(Path(entry.path).resolve().relative_to(library_root))

    image_relative_paths.sort(key=lambda value: Path(value).name.casefold())
    return image_count, total_size, cover_relative_path, image_relative_paths


def _state_defaults() -> dict:
    return {
        "status": "idle",
        "message": "",
        "started_at": None,
        "finished_at": None,
        "total_cosers": 0,
        "processed_cosers": 0,
        "current_coser": "",
        "current_set": "",
        "current_path": "",
        "discovered_sets": 0,
        "discovered_images": 0,
        "discovered_size": 0,
    }


def update_scan_state(**changes: object) -> None:
    with SessionLocal() as session:
        state = session.get(ScanState, 1)
        if state is None:
            state = ScanState(id=1, **_state_defaults())
            session.add(state)
            session.flush()
        for key, value in changes.items():
            setattr(state, key, value)
        session.commit()


def read_scan_state() -> dict:
    with SessionLocal() as session:
        state = session.get(ScanState, 1)
        if state is None:
            state = ScanState(id=1, **_state_defaults())
            session.add(state)
            session.commit()
            session.refresh(state)
        progress = 0.0
        if state.total_cosers:
            progress = min(state.processed_cosers / state.total_cosers, 1.0)
        return {
            "status": state.status,
            "message": state.message,
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "finished_at": state.finished_at.isoformat() if state.finished_at else None,
            "total_cosers": state.total_cosers,
            "processed_cosers": state.processed_cosers,
            "current_coser": state.current_coser,
            "current_set": state.current_set,
            "current_path": state.current_path,
            "discovered_sets": state.discovered_sets,
            "discovered_images": state.discovered_images,
            "discovered_size": state.discovered_size,
            "progress": progress,
        }


def read_indexed_summary() -> tuple[int, int, int]:
    with SessionLocal() as session:
        total_sets = session.execute(select(func.count(SetRecord.id))).scalar_one() or 0
        total_images = session.execute(select(func.coalesce(func.sum(SetRecord.image_count), 0))).scalar_one() or 0
        total_size = session.execute(select(func.coalesce(func.sum(SetRecord.total_size), 0))).scalar_one() or 0
        return int(total_sets), int(total_images), int(total_size)


def persist_set_payload(session, item: SetPayload) -> tuple[int, int, int]:
    existing = session.execute(
        select(SetRecord).where(SetRecord.relative_path == item.relative_path)
    ).scalar_one_or_none()
    is_new = existing is None

    previous_images = 0
    previous_size = 0

    def assign_record_values(record: SetRecord) -> None:
        record.coser_key = item.coser_key
        record.coser_name = item.coser_name
        record.set_name = item.set_name
        record.relative_path = item.relative_path
        record.image_count = item.image_count
        record.total_size = item.total_size
        record.cover_relative_path = item.cover_relative_path

    if is_new:
        existing = SetRecord()
        assign_record_values(existing)
        session.add(existing)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            existing = session.execute(
                select(SetRecord).where(SetRecord.relative_path == item.relative_path)
            ).scalar_one()
            is_new = False
            previous_images = existing.image_count
            previous_size = existing.total_size
            session.execute(delete(SetCharacter).where(SetCharacter.set_id == existing.id))
            session.execute(delete(SetImage).where(SetImage.set_id == existing.id))
            assign_record_values(existing)
    else:
        previous_images = existing.image_count
        previous_size = existing.total_size
        session.execute(delete(SetCharacter).where(SetCharacter.set_id == existing.id))
        session.execute(delete(SetImage).where(SetImage.set_id == existing.id))
        assign_record_values(existing)

    for character_key, character_name in item.characters:
        session.add(
            SetCharacter(
                set_id=existing.id,
                character_key=character_key,
                character_name=character_name,
            )
        )

    for image_index, image_relative_path in enumerate(item.image_relative_paths):
        session.add(
            SetImage(
                set_id=existing.id,
                image_index=image_index,
                file_name=Path(image_relative_path).name,
                relative_path=image_relative_path,
            )
        )

    session.commit()
    return (1 if is_new else 0, item.image_count - previous_images, item.total_size - previous_size)


def remove_missing_sets(seen_relative_paths: set[str]) -> None:
    with SessionLocal() as session:
        existing_rows = session.execute(select(SetRecord.id, SetRecord.relative_path)).all()
        missing_ids = [row.id for row in existing_rows if row.relative_path not in seen_relative_paths]
        if not missing_ids:
            return
        session.execute(delete(SetImage).where(SetImage.set_id.in_(missing_ids)))
        session.execute(delete(SetCharacter).where(SetCharacter.set_id.in_(missing_ids)))
        session.execute(delete(SetRecord).where(SetRecord.id.in_(missing_ids)))
        session.commit()


def scan_library() -> None:
    library_root = settings.library_root
    if not library_root.exists():
        update_scan_state(
            status="failed",
            message=f"Library root not found: {library_root}",
            finished_at=datetime.utcnow(),
        )
        return

    try:
        with os.scandir(library_root) as iterator:
            coser_entries = sorted(
                [entry for entry in iterator if entry.is_dir(follow_symlinks=False)],
                key=lambda item: item.name.casefold(),
            )
    except OSError as exc:
        update_scan_state(status="failed", message=str(exc), finished_at=datetime.utcnow())
        return

    previous_state = read_scan_state()
    indexed_sets, indexed_images, indexed_size = read_indexed_summary()
    resume_mode = previous_state["status"] == "failed" and indexed_sets > 0
    existing_paths: set[str] = set()
    if resume_mode:
        with SessionLocal() as session:
            existing_paths = set(session.execute(select(SetRecord.relative_path)).scalars().all())
    indexed_paths = set(existing_paths)

    if resume_mode:
        discovered_sets, discovered_images, discovered_size = indexed_sets, indexed_images, indexed_size
    else:
        discovered_sets = 0
        discovered_images = 0
        discovered_size = 0

    update_scan_state(
        status="running",
        message="Resuming interrupted scan..." if resume_mode else "Scanning library...",
        started_at=datetime.utcnow(),
        finished_at=None,
        total_cosers=len(coser_entries),
        processed_cosers=0,
        current_coser="",
        current_set="",
        current_path=str(library_root),
        discovered_sets=discovered_sets,
        discovered_images=discovered_images,
        discovered_size=discovered_size,
    )

    seen_relative_paths: set[str] = set()

    try:
        with SessionLocal() as write_session:
            for coser_index, coser_entry in enumerate(coser_entries, start=1):
                update_scan_state(
                    current_coser=coser_entry.name,
                    current_set="",
                    current_path=str(Path(coser_entry.path).resolve()),
                    processed_cosers=coser_index - 1,
                )

                try:
                    with os.scandir(coser_entry.path) as set_iterator:
                        set_entries = sorted(
                            [entry for entry in set_iterator if entry.is_dir(follow_symlinks=False)],
                            key=lambda item: item.name.casefold(),
                        )
                except OSError:
                    continue

                for set_entry in set_entries:
                    relative_path = str(Path(set_entry.path).resolve().relative_to(library_root))
                    seen_relative_paths.add(relative_path)
                    if resume_mode and relative_path in indexed_paths:
                        continue

                    update_scan_state(
                        current_set=set_entry.name,
                        current_path=str(Path(set_entry.path).resolve()),
                        processed_cosers=coser_index - 1,
                        discovered_sets=discovered_sets,
                        discovered_images=discovered_images,
                        discovered_size=discovered_size,
                    )

                    characters = parse_character_names(set_entry.name)
                    if not characters:
                        continue
                    image_count, total_size, cover_relative_path, image_relative_paths = scan_set(Path(set_entry.path), library_root)
                    item = SetPayload(
                        coser_key=normalize_key(coser_entry.name),
                        coser_name=coser_entry.name,
                        set_name=set_entry.name,
                        relative_path=relative_path,
                        image_count=image_count,
                        total_size=total_size,
                        cover_relative_path=cover_relative_path,
                        image_relative_paths=image_relative_paths,
                        characters=characters,
                    )
                    set_delta, image_delta, size_delta = persist_set_payload(write_session, item)
                    indexed_paths.add(relative_path)
                    if resume_mode:
                        discovered_sets += set_delta
                        discovered_images += image_delta
                        discovered_size += size_delta
                    else:
                        discovered_sets += 1
                        discovered_images += image_count
                        discovered_size += total_size
                    update_scan_state(
                        current_set=set_entry.name,
                        current_path=str(Path(set_entry.path).resolve()),
                        processed_cosers=coser_index - 1,
                        discovered_sets=discovered_sets,
                        discovered_images=discovered_images,
                        discovered_size=discovered_size,
                    )

                update_scan_state(
                    processed_cosers=coser_index,
                    current_coser=coser_entry.name,
                    current_path=str(Path(coser_entry.path).resolve()),
                    discovered_sets=discovered_sets,
                    discovered_images=discovered_images,
                    discovered_size=discovered_size,
                )

        remove_missing_sets(seen_relative_paths)

        discovered_sets, discovered_images, discovered_size = read_indexed_summary()

        update_scan_state(
            status="completed",
            message=f"Scan complete. {discovered_sets} sets indexed.",
            finished_at=datetime.utcnow(),
            processed_cosers=len(coser_entries),
            current_set="",
            discovered_sets=discovered_sets,
            discovered_images=discovered_images,
            discovered_size=discovered_size,
        )
    except Exception as exc:
        update_scan_state(status="failed", message=str(exc), finished_at=datetime.utcnow())
        raise


def start_scan() -> bool:
    global _scan_future
    with _scan_lock:
        if _scan_future and not _scan_future.done():
            return False
        _scan_future = _executor.submit(scan_library)
        return True


def scan_is_running() -> bool:
    with _scan_lock:
        return bool(_scan_future and not _scan_future.done())


def library_has_data() -> bool:
    with SessionLocal() as session:
        return session.execute(select(SetRecord.id).limit(1)).first() is not None
