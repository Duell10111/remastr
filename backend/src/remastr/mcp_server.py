"""MCP server: the same operations as the web UI, for AI assistants (Streamable HTTP at /mcp)."""

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from remastr.models import (
    DEFAULT_PRESET,
    DEFAULT_QUALITY,
    BatchRequest,
    ItemDetail,
    Job,
    Library,
    PlexItem,
    Preset,
    PreviewRequest,
    ProcessRequest,
    UploadMode,
    UploadRequest,
)
from remastr.service import Remastr

INSTRUCTIONS = """\
Remastr improves video files from a Plex server with AI upscaling (SD -> 1080p, deinterlacing for TV recordings).

Typical workflow:
1. search_media to find movies/episodes (rating_key identifies an item).
2. create_previews with several presets on a short section; compare the clips (get_item lists them) and let the
   user choose. Downloading happens automatically when needed.
   Live action: realesr_general (default), scunet_vsr (cleaner, softer) or dpir_vsr.
   Cartoons/anime: esrgan or cugan (these make live action look painted).
3. process_item (or batch_process for many items) with the chosen preset.
4. upload_result: mode "version" adds the file next to the original (safe, default). Mode "replace" moves the
   original to an archive folder and requires confirm=true - only use it when the user explicitly asked for it.
All long-running operations are jobs: poll list_jobs / get_job for progress.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
QUEUES_WORK = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)


def build_mcp(svc: Remastr) -> MCPServer:
    mcp = MCPServer(name="remastr", instructions=INSTRUCTIONS)

    @mcp.tool(annotations=READ_ONLY)
    def list_libraries() -> list[Library]:
        """List the Plex movie and TV libraries."""
        return svc.libraries()

    @mcp.tool(annotations=READ_ONLY)
    def search_media(query: str, library: str | None = None, limit: int = 50) -> list[PlexItem]:
        """Search movies and episodes by title. A matching show title returns its episodes.
        library: optional library title or key."""
        return svc.search(query, library, limit)

    @mcp.tool(annotations=READ_ONLY)
    def get_item(rating_key: str) -> ItemDetail:
        """Plex metadata of an item plus local state: downloaded source, preview runs with clip files, outputs."""
        return svc.item(rating_key)

    @mcp.tool(annotations=READ_ONLY)
    def list_presets() -> list[Preset]:
        """Available processing presets (AI models / filter chains)."""
        return svc.presets()

    @mcp.tool(annotations=QUEUES_WORK)
    def download_item(rating_key: str) -> Job:
        """Queue a download of the original file via FTP."""
        return svc.download(rating_key)

    @mcp.tool(annotations=QUEUES_WORK)
    def create_previews(rating_key: str, presets: list[str], start_s: float = 120, duration_s: float = 30) -> Job:
        """Queue preview clips of the same section, one per preset, for side-by-side comparison."""
        return svc.preview(rating_key, PreviewRequest(presets=presets, start_s=start_s, duration_s=duration_s))

    @mcp.tool(annotations=QUEUES_WORK)
    def process_item(
        rating_key: str,
        preset: str = DEFAULT_PRESET,
        codec: Literal["hevc", "av1"] = "hevc",
        quality: int = DEFAULT_QUALITY,
    ) -> Job:
        """Queue full-length processing (with audio and subtitles). quality: lower = better/larger (QVBR)."""
        return svc.process(rating_key, ProcessRequest(preset=preset, codec=codec, quality=quality))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    def upload_result(rating_key: str, mode: Literal["version", "replace"] = "version", confirm: bool = False) -> Job:
        """Upload the processed file to Plex. "version": next to the original (Plex shows both versions).
        "replace": the original is moved to the archive folder - requires confirm=true and explicit user consent."""
        return svc.upload(rating_key, UploadRequest(mode=UploadMode(mode), confirm=confirm))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    def batch_process(
        rating_keys: list[str],
        preset: str = DEFAULT_PRESET,
        codec: Literal["hevc", "av1"] = "hevc",
        quality: int = DEFAULT_QUALITY,
        upload_mode: Literal["none", "version", "replace"] = "none",
        confirm_replace: bool = False,
    ) -> list[Job]:
        """Queue download -> process -> optional upload for many items. upload_mode "replace" needs
        confirm_replace=true and explicit user consent."""
        upload = None if upload_mode == "none" else UploadRequest(mode=UploadMode(upload_mode), confirm=confirm_replace)
        return svc.batch(
            BatchRequest(
                rating_keys=rating_keys,
                process=ProcessRequest(preset=preset, codec=codec, quality=quality),
                upload=upload,
            )
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_jobs(active_only: bool = False, rating_key: str | None = None, limit: int = 50) -> list[Job]:
        """Jobs, newest first, with status and progress (0..1)."""
        return svc.jobs(limit, rating_key, active_only)

    @mcp.tool(annotations=READ_ONLY)
    def get_job(job_id: int) -> Job:
        """A single job with status, progress, message and result."""
        return svc.job(job_id)

    @mcp.tool(annotations=QUEUES_WORK)
    def cancel_job(job_id: int) -> Job:
        """Cancel a queued or running job."""
        return svc.cancel_job(job_id)

    return mcp
