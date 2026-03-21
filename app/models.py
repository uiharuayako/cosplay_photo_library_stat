from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class SetRecord(Base):
    __tablename__ = "set_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    coser_key: Mapped[str] = mapped_column(String(255), index=True)
    coser_name: Mapped[str] = mapped_column(String(255))
    set_name: Mapped[str] = mapped_column(String(512))
    relative_path: Mapped[str] = mapped_column(String(1024), unique=True)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    cover_relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    characters: Mapped[list[SetCharacter]] = relationship(
        "SetCharacter",
        back_populates="set_record",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SetCharacter(Base):
    __tablename__ = "set_characters"
    __table_args__ = (UniqueConstraint("set_id", "character_key", name="uq_set_character"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("set_records.id", ondelete="CASCADE"), index=True)
    character_key: Mapped[str] = mapped_column(String(255), index=True)
    character_name: Mapped[str] = mapped_column(String(255))

    set_record: Mapped[SetRecord] = relationship("SetRecord", back_populates="characters")


class ScanState(Base):
    __tablename__ = "scan_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_cosers: Mapped[int] = mapped_column(Integer, default=0)
    processed_cosers: Mapped[int] = mapped_column(Integer, default=0)
    current_coser: Mapped[str] = mapped_column(String(255), default="")
    current_set: Mapped[str] = mapped_column(String(512), default="")
    current_path: Mapped[str] = mapped_column(String(1024), default="")
    discovered_sets: Mapped[int] = mapped_column(Integer, default=0)
    discovered_images: Mapped[int] = mapped_column(BigInteger, default=0)
    discovered_size: Mapped[int] = mapped_column(BigInteger, default=0)
