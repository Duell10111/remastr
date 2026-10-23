"""Data models shared by the REST API, the MCP tools and the services."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Library(BaseModel):
    key: str
    title: str
    type: str


class PlexItem(BaseModel):
    rating_key: str
    title: str
    type: str
    library: str
    show: str | None = None
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    file: str
    """Path of the (first) media file as Plex sees it."""
    size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    container: str | None = None
    video_codec: str | None = None

    @property
    def display_title(self) -> str:
        if self.show is not None and self.season is not None and self.episode is not None:
            return f"{self.show} - S{self.season:02d}E{self.episode:02d} - {self.title}"
        return f"{self.title} ({self.year})" if self.year else self.title


class Preset(BaseModel):
    id: str
    name: str
    description: str
    vpy_mode: Literal["esrgan", "cugan", "dpir", "passthrough"]
    """VapourSynth stage: esrgan/cugan upscale there; dpir/passthrough leave scaling to NVEncC."""
    nvenc_filters: list[str] = []
    """Extra NVEncC filter arguments (before scaling)."""
    nvenc_resize: str | None = None
    """NVEncC --vpp-resize value, only used when VapourSynth does not scale."""


class PreviewClip(BaseModel):
    preset: str
    file: str
    """Path relative to the item workspace."""


class PreviewRun(BaseModel):
    id: str
    start_s: float
    duration_s: float
    created_at: datetime
    clips: list[PreviewClip]


class LocalState(BaseModel):
    """What exists in the local workspace for an item."""

    source: str | None = None
    previews: list[PreviewRun] = []
    outputs: list[str] = []


class ItemDetail(BaseModel):
    item: PlexItem
    local: LocalState


class JobType(StrEnum):
    download = "download"
    preview = "preview"
    process = "process"
    upload = "upload"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Job(BaseModel):
    id: int
    type: JobType
    status: JobStatus
    rating_key: str
    title: str = ""
    params: dict[str, Any] = {}
    depends_on: int | None = None
    progress: float = 0.0
    """0..1"""
    message: str = ""
    result: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class UploadMode(StrEnum):
    version = "version"
    """Upload next to the original; Plex shows both as versions of the same item."""
    replace = "replace"
    """Upload, then move the original to the FTP archive folder."""


class PreviewRequest(BaseModel):
    presets: list[str] = Field(min_length=1)
    start_s: float = Field(default=120, ge=0)
    duration_s: float = Field(default=30, gt=0, le=600)


class ProcessRequest(BaseModel):
    preset: str
    codec: Literal["hevc", "av1"] = "hevc"
    quality: int = Field(default=20, ge=1, le=51)
    """NVEncC QVBR target; lower = better quality, larger file."""


class UploadRequest(BaseModel):
    mode: UploadMode = UploadMode.version
    confirm: bool = False
    """Must be true for mode=replace."""


class BatchRequest(BaseModel):
    rating_keys: list[str] = Field(min_length=1)
    process: ProcessRequest
    upload: UploadRequest | None = None
