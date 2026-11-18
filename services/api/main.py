import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from packages.protocol.python.lifeline_protocol import SyncBundle, verify_event
from services.api.auth import router as auth_router
from services.api.dashboard import router as dashboard_router
from services.api.db import Base, SessionLocal, engine
from services.api.models import EventRecord
from services.api.risk import router as risk_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Lifeline API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4173", "http://127.0.0.1:4173"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["authorization", "content-type"],
)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(risk_router)
API_PREFIX = "/api/v1"
logger = logging.getLogger("lifeline.api")


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 413: "too_large", 429: "rate_limited"}.get(exc.status_code, "request_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": str(exc.detail), "details": {}}},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "message": "Request validation failed", "details": exc.errors()}},
    )


class MediaAck(BaseModel):
    media_id: str
    status: str = "received"


class SyncResponse(BaseModel):
    accepted_ids: list[str]
    rejected: list[dict[str, str]]
    missing_events: list[dict[str, Any]]


def media_id_from_bytes(content: bytes) -> str:
    import hashlib
    return hashlib.sha256(content).hexdigest()[:26].upper()


def enqueue_triage(event_ids: list[str]) -> None:
    if not os.getenv("REDIS_URL"):
        return
    try:
        from services.triage.tasks import process_event

        for event_id in event_ids:
            process_event.delay(event_id)
    except Exception:
        # Intake remains available; the immutable event log still holds the work for replay.
        logger.exception("Triage queue unavailable; accepted events remain in the event log")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{API_PREFIX}/sync", response_model=SyncResponse)
def sync(bundle: SyncBundle) -> SyncResponse:
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    stored: list[str] = []
    with SessionLocal() as session:
        for event in bundle.events:
            try:
                verify_event(event)
            except ValueError as exc:
                rejected.append({"event_id": event.event_id, "reason": str(exc)})
                continue
            if session.get(EventRecord, event.event_id) is None:
                session.add(EventRecord(
                    event_id=event.event_id, device_id=event.device_id, hlc=event.hlc,
                    event_type=event.type, request_id=event.request_id,
                    payload=json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
                    hops=event.hops, signature=event.signature,
                ))
                stored.append(event.event_id)
            accepted.append(event.event_id)
        session.commit()
        known = set(bundle.known_event_ids) | {event.event_id for event in bundle.events if event.event_id in accepted}
        missing_query = select(EventRecord)
        if known:
            missing_query = missing_query.where(~EventRecord.event_id.in_(known))
        for device_id, highest_hlc in bundle.highest_hlc_by_device.items():
            if len(device_id) <= 128 and len(highest_hlc) <= 80:
                missing_query = missing_query.where(
                    (EventRecord.device_id != device_id) | (EventRecord.hlc > highest_hlc)
                )
        missing = session.scalars(missing_query).all()
        missing_events = [
            {"protocol_version": 1, "event_id": row.event_id, "device_id": row.device_id,
             "hlc": row.hlc, "type": row.event_type, "request_id": row.request_id,
             "payload": json.loads(row.payload), "hops": row.hops, "signature": row.signature}
            for row in missing
        ]
    enqueue_triage(stored)
    return SyncResponse(accepted_ids=accepted, rejected=rejected, missing_events=missing_events)


@app.get(f"{API_PREFIX}/sync/summary")
def sync_summary() -> dict[str, Any]:
    with SessionLocal() as session:
        rows = session.scalars(select(EventRecord.hlc)).all()
    return {"event_count": len(rows), "highest_hlc": max(rows, default=None)}


@app.post(f"{API_PREFIX}/media", response_model=MediaAck)
async def upload_media(file: UploadFile = File(...)) -> MediaAck:  # noqa: B008
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Media exceeds 10 MiB limit")
    if not content:
        raise HTTPException(status_code=400, detail="Empty media is not accepted")
    return MediaAck(media_id=media_id_from_bytes(content))


@app.get(f"{API_PREFIX}/requests/{{request_id}}/status")
def request_status(request_id: str) -> dict[str, str]:
    with SessionLocal() as session:
        event = session.scalar(select(EventRecord).where(EventRecord.request_id == request_id).order_by(EventRecord.hlc.desc()))
    if event is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"request_id": request_id, "status": "received", "updated_hlc": event.hlc}


@app.get(f"{API_PREFIX}/config")
def config() -> dict[str, Any]:
    return {"language_bundles_version": "1", "map_tile_urls": [], "feature_flags": {"offline_sos": True}, "server_time": datetime.now(UTC)}
