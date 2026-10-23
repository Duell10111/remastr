"""Settings, loaded from environment variables (prefix REMASTR_) or backend/.env."""

from functools import cached_property
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PathMapping(BaseModel):
    """The same folder as Plex sees it and as it appears on the FTP server."""

    plex: str
    ftp: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REMASTR_", env_file=".env", extra="ignore")

    # --- HTTP server (web UI, REST API, MCP) ---
    host: str = "127.0.0.1"
    port: int = 8765
    api_token: str = ""
    """Bearer token for /api and /mcp. Required when host is not a loopback address."""
    allowed_hosts: list[str] = ["127.0.0.1:*", "localhost:*"]
    """Host headers accepted by the MCP endpoint (DNS rebinding protection), e.g. "my-pc:*"."""

    # --- Plex ---
    plex_url: str = "http://localhost:32400"
    plex_token: str = ""

    # --- FTP ---
    ftp_host: str = ""
    ftp_port: int = 21
    ftp_user: str = ""
    ftp_password: str = ""
    ftp_tls: bool = True
    """Use explicit FTPS (AUTH TLS). Strongly recommended."""
    path_mappings: list[PathMapping] = []
    """JSON list, e.g. [{"plex": "/data/tv", "ftp": "/tv"}]."""
    ftp_archive_root: str = ""
    """FTP folder for originals replaced by "replace" uploads. Must be outside every Plex library."""
    version_suffix: str = " - Remastr {height}p"
    """Appended to the original file name for "version" uploads; Plex groups them as versions of one item."""

    # --- Local workspace ---
    work_dir: Path = Path("F:/Remastr")

    # --- Processing tools (Windows + NVIDIA) ---
    staxrip_dir: Path = Path(r"F:\Tools\StaxRip\StaxRip-v2.52.6-x64")
    vsmlrt_dir: Path = Path(r"F:\Tools\vs-mlrt")
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    target_height: int = 1080
    """Output height for SD sources. HD sources are only deinterlaced."""

    @cached_property
    def vspipe(self) -> Path:
        return self.staxrip_dir / "Apps/FrameServer/VapourSynth/Lib/site-packages/vapoursynth/vspipe.exe"

    @cached_property
    def nvencc(self) -> Path:
        return self.staxrip_dir / "Apps/Encoders/NVEncC/NVEncC64.exe"

    @cached_property
    def mkvmerge(self) -> Path:
        return self.staxrip_dir / "Apps/Support/MKVToolNix/mkvmerge.exe"

    @cached_property
    def vs_plugins(self) -> Path:
        return self.staxrip_dir / "Apps/Plugins"

    @property
    def is_loopback(self) -> bool:
        return self.host in ("127.0.0.1", "localhost", "::1")
