"""REST API for the web UI."""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from remastr.models import (
    BatchRequest,
    ItemDetail,
    Job,
    Library,
    PlexItem,
    Preset,
    PreviewRequest,
    ProcessRequest,
    UploadRequest,
)
from remastr.service import Remastr

router = APIRouter(prefix="/api")


def _svc(request: Request) -> Remastr:
    return request.app.state.remastr


def _bad_request(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/libraries")
def libraries(request: Request) -> list[Library]:
    return _svc(request).libraries()


@router.get("/search")
def search(request: Request, q: str, library: str | None = None, limit: int = Query(50, le=500)) -> list[PlexItem]:
    return _svc(request).search(q, library, limit)


@router.get("/presets")
def presets(request: Request) -> list[Preset]:
    return _svc(request).presets()


@router.get("/items/{rating_key}")
def item(request: Request, rating_key: str) -> ItemDetail:
    try:
        return _svc(request).item(rating_key)
    except ValueError as e:
        raise _bad_request(e) from e


@router.post("/items/{rating_key}/download")
def download(request: Request, rating_key: str) -> Job:
    return _svc(request).download(rating_key)


@router.post("/items/{rating_key}/previews")
def preview(request: Request, rating_key: str, body: PreviewRequest) -> Job:
    try:
        return _svc(request).preview(rating_key, body)
    except ValueError as e:
        raise _bad_request(e) from e


@router.post("/items/{rating_key}/process")
def process(request: Request, rating_key: str, body: ProcessRequest) -> Job:
    try:
        return _svc(request).process(rating_key, body)
    except ValueError as e:
        raise _bad_request(e) from e


@router.post("/items/{rating_key}/upload")
def upload(request: Request, rating_key: str, body: UploadRequest) -> Job:
    try:
        return _svc(request).upload(rating_key, body)
    except ValueError as e:
        raise _bad_request(e) from e


@router.get("/items/{rating_key}/files/{path:path}")
def media_file(request: Request, rating_key: str, path: str) -> FileResponse:
    """Serves preview clips and outputs (supports HTTP range requests for video seeking)."""
    try:
        return FileResponse(_svc(request).media_file(rating_key, path))
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail="File not found") from e


@router.post("/batch")
def batch(request: Request, body: BatchRequest) -> list[Job]:
    try:
        return _svc(request).batch(body)
    except ValueError as e:
        raise _bad_request(e) from e


@router.get("/jobs")
def jobs(
    request: Request, limit: int = Query(100, le=1000), rating_key: str | None = None, active_only: bool = False
) -> list[Job]:
    return _svc(request).jobs(limit, rating_key, active_only)


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: int) -> Job:
    try:
        return _svc(request).job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/jobs/{job_id}/cancel")
def cancel(request: Request, job_id: int) -> Job:
    try:
        return _svc(request).cancel_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
