"""Data models shared by the REST API, the MCP tools and the services."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

DEFAULT_PRESET = "realesr_general"
DEFAULT_QUALITY = 26
"""Suggested fixed QVBR when the automatic quality is switched off: visually identical to 20 on upscaled SD at
roughly 40% of the size (tested on 640x360 -> 1080p)."""
DEFAULT_TARGET_VMAF = 95.0
"""Automatic quality target: VMAF 95 is generally considered visually indistinguishable from the reference."""


class Library(BaseModel):
    key: str
    title: str
    type: str


class MediaVersion(BaseModel):
    """One original file of an item. Plex groups several files of the same title as versions."""

    file: str
    size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    container: str | None = None
    video_codec: str | None = None
    bitrate: int | None = None
    """Overall bitrate in kbit/s."""


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
    versions: list[MediaVersion] = []
    """All original versions (remastr uploads excluded). file/size/width/... above describe the selected one."""
    version_pinned: bool = False
    """The version was chosen manually; otherwise it is the first original Plex lists."""

    def with_version(self, file: str, pinned: bool) -> "PlexItem":
        v = next((v for v in self.versions if v.file == file), None)
        if v is None:
            raise ValueError(f"{file} is not an original version of item {self.rating_key}")
        return self.model_copy(update={**v.model_dump(exclude={"bitrate"}), "version_pinned": pinned})

    @property
    def display_title(self) -> str:
        if self.show is not None and self.season is not None and self.episode is not None:
            return f"{self.show} - S{self.season:02d}E{self.episode:02d} - {self.title}"
        return f"{self.title} ({self.year})" if self.year else self.title


class Preset(BaseModel):
    id: str
    name: str
    description: str
    vpy_mode: Literal["esrgan", "cugan", "swinir", "waifu2x", "onnx", "dpir", "scunet", "passthrough"]
    """VapourSynth stage (see remastr.vpy). Upscaling modes scale there; the others leave scaling to NVEncC."""
    onnx_model: str | None = None
    """vpy_mode "onnx": upscaling model (NCHW RGB, input named "input"), relative to <vs-mlrt>/models or absolute."""
    onnx_multiple: int = 1
    """vpy_mode "onnx": the model needs width/height to be a multiple of this (e.g. 16 for HAT); the frame is
    mirror-padded before and cropped after inference."""
    fp16: bool = True
    """TensorRT in half precision. Some transformer models overflow in fp16 (black/green output)."""
    num_streams: int = 2
    """Parallel TensorRT streams. Large models need 1: two contexts overflow 12 GB VRAM and get ~15x slower."""
    preview_only: bool = False
    """Too slow for whole files; only offered for preview clips."""
    nvenc_filters: list[str] = []
    """Extra NVEncC filter arguments (before scaling)."""
    nvenc_resize: str | None = None
    """NVEncC --vpp-resize value, only used when VapourSynth does not scale."""

    @property
    def scales_in_vapoursynth(self) -> bool:
        return self.vpy_mode in ("esrgan", "cugan", "swinir", "waifu2x", "onnx")


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


class OutputInfo(BaseModel):
    """A processed file plus how it was made (stored next to it as <name>.remastr.json)."""

    file: str
    """Path relative to the item workspace."""
    size: int
    preset: str | None = None
    preset_name: str | None = None
    codec: str | None = None
    quality: int | None = None
    quality_auto: bool = False
    """quality was chosen by the automatic search."""
    vmaf: float | None = None
    """Measured VMAF of the chosen quality on the search samples (automatic quality only)."""
    description: str | None = None
    created_at: datetime | None = None

    @property
    def label(self) -> str:
        if not self.preset_name:
            return "unknown preset"
        label = f"{self.preset_name}, {(self.codec or '').upper()} q{self.quality}"
        if self.quality_auto:
            label += f" (auto, VMAF {self.vmaf:.1f})" if self.vmaf is not None else " (auto)"
        return label


class LocalState(BaseModel):
    """What exists in the local workspace for an item."""

    source: str | None = None
    previews: list[PreviewRun] = []
    outputs: list[OutputInfo] = []


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
    preset: str = DEFAULT_PRESET
    codec: Literal["hevc", "av1"] = "hevc"
    quality: int | None = Field(default=None, ge=1, le=63)
    """NVEncC QVBR (lower = better quality, larger file; HEVC 1-51, AV1 1-63). None = automatic: the highest value
    whose VMAF reaches target_vmaf."""
    target_vmaf: float = Field(default=DEFAULT_TARGET_VMAF, ge=80, le=99)

    @model_validator(mode="after")
    def _quality_in_codec_range(self) -> "ProcessRequest":
        if self.quality is not None and self.codec == "hevc" and self.quality > 51:
            raise ValueError("HEVC quality must be 1-51")
        return self


class VersionRequest(BaseModel):
    file: str | None = None
    """Plex path of the original version to work with. None = automatic (the first original Plex lists)."""


class UploadRequest(BaseModel):
    mode: UploadMode = UploadMode.version
    confirm: bool = False
    """Must be true for mode=replace."""


class BatchRequest(BaseModel):
    rating_keys: list[str] = Field(min_length=1)
    process: ProcessRequest
    upload: UploadRequest | None = None
