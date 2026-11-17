from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class EventRecord(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    hlc: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column("type", String(64))
    request_id: Mapped[str] = mapped_column(String(26), index=True)
    payload: Mapped[str] = mapped_column(Text)
    hops: Mapped[int] = mapped_column(Integer, default=0)
    signature: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    source: Mapped[str] = mapped_column(String(16), default="https")
