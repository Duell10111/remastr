"""Application service: the single API used by both the REST routes and the MCP tools."""

import hashlib
import logging
import posixpath
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from remastr import pipeline
from remastr.config import Settings
from remastr.ftp import FtpService, PathMapper
from remastr.jobs import JobContext, JobRunner, JobStore
from remastr.models import (
    BatchRequest,
    ItemDetail,
    Job,
    JobType,
    Library,
    OutputInfo,
    PlexItem,
    Preset,
    PreviewRequest,
    PreviewRun,
    ProcessRequest,
    UploadMode,
    UploadRequest,
    VersionRequest,
)
from remastr.plex import PlexService
from remastr.presets import PRESETS, get_preset, load_extra_presets
from remastr.quality import QualityResult
from remastr.workspace import Workspace, plex_basename

log = logging.getLogger(__name__)

UPLOAD_TMP_SUFFIX = ".remastr-upload"


class Remastr:
    def __init__(self, settings: Settings, plex: PlexService | None = None, ftp: FtpService | None = None):
        self.settings = settings
        self.plex = plex or PlexService(settings)
        self.ftp = ftp or FtpService(settings)
        self.paths = PathMapper(settings.path_mappings)
        self.workspace = Workspace(settings)
        if extra := load_extra_presets(settings.work_dir / "presets.json"):
            log.info("Loaded %d extra presets: %s", len(extra), ", ".join(p.id for p in extra))
        self.store = JobStore(settings.work_dir / "remastr.db")
        self.runner = JobRunner(
            self.store,
            {
                JobType.download: self._run_download,
                JobType.preview: self._run_preview,
                JobType.process: self._run_process,
                JobType.upload: self._run_upload,
            },
        )

    def start(self) -> None:
        self.runner.start()

    def stop(self) -> None:
        self.runner.stop()

    # ------------------------------------------------------------------ queries

    def libraries(self) -> list[Library]:
        return self.plex.libraries()

    def search(self, query: str, library: str | None = None, limit: int = 50) -> list[PlexItem]:
        return [self._with_selected_version(i) for i in self.plex.search(query, library, limit)]

    def presets(self) -> list[Preset]:
        return PRESETS

    def item(self, rating_key: str) -> ItemDetail:
        try:
            item = self._fetch(rating_key)
        except Exception:
            item = self.workspace.load_item(rating_key)
            if item is None:
                raise
            log.warning("Plex unreachable, using cached metadata for %s", rating_key)
        return ItemDetail(item=item, local=self.workspace.local_state(rating_key))

    def jobs(self, limit: int = 100, rating_key: str | None = None, active_only: bool = False) -> list[Job]:
        return self.store.list(limit, rating_key, active_only)

    def job(self, job_id: int) -> Job:
        return self.store.get(job_id)

    def media_file(self, rating_key: str, rel_path: str) -> Path:
        return self.workspace.resolve(rating_key, rel_path)

    # ----------------------------------------------------------------- commands

    def select_version(self, rating_key: str, req: VersionRequest) -> ItemDetail:
        """Choose which original version downloads, previews, processing and uploads use. A downloaded source of
        a different version is discarded; previews and outputs stay."""
        if self.store.list(rating_key=rating_key, active_only=True):
            raise ValueError("Jobs for this item are still queued or running; wait or cancel them first")
        current = self._fetch(rating_key)
        if req.file is None:
            new = current.with_version(current.versions[0].file, pinned=False)
        else:
            new = current.with_version(req.file, pinned=True)  # raises for unknown paths
        self.workspace.select_version(rating_key, req.file)
        if new.file != current.file:
            self.workspace.discard_source(rating_key)
        self.workspace.save_item(new)
        return ItemDetail(item=new, local=self.workspace.local_state(rating_key))

    def cancel_job(self, job_id: int) -> Job:
        return self.runner.cancel(job_id)

    def download(self, rating_key: str) -> Job:
        item = self._fetch(rating_key)
        return self.runner.submit(JobType.download, rating_key, item.display_title)

    def preview(self, rating_key: str, req: PreviewRequest) -> Job:
        for p in req.presets:
            get_preset(p)
        item = self._fetch(rating_key)
        dep = self._source_dependency(item)
        return self.runner.submit(JobType.preview, rating_key, item.display_title, req.model_dump(), dep)

    def process(self, rating_key: str, req: ProcessRequest, depends_on: int | None = None) -> Job:
        if get_preset(req.preset).preview_only:
            raise ValueError(f"Preset '{req.preset}' is too slow for whole files; use it for previews only")
        item = self._fetch(rating_key)
        dep = depends_on or self._source_dependency(item)
        return self.runner.submit(JobType.process, rating_key, item.display_title, req.model_dump(), dep)

    def upload(self, rating_key: str, req: UploadRequest, depends_on: int | None = None) -> Job:
        if req.mode == UploadMode.replace:
            if not req.confirm:
                raise ValueError("Replacing the original requires confirm=true")
            if not self.settings.ftp_archive_root:
                raise ValueError("Replace mode needs REMASTR_FTP_ARCHIVE_ROOT (folder outside the Plex libraries)")
        item = self._fetch(rating_key)
        self.paths.to_ftp(item.file)  # fail early on missing mapping
        if depends_on is None:
            # Never upload a stale output while a newer one is still being produced
            depends_on = self._active_job(rating_key, JobType.process)
        if depends_on is None and not self.workspace.outputs(rating_key):
            raise ValueError("No processed output for this item yet; run process first")
        return self.runner.submit(JobType.upload, rating_key, item.display_title, req.model_dump(), depends_on)

    def batch(self, req: BatchRequest) -> list[Job]:
        """download (if needed) -> process -> upload (optional), chained per item."""
        jobs: list[Job] = []
        for rk in req.rating_keys:
            proc = self.process(rk, req.process)
            jobs.append(proc)
            if req.upload is not None:
                jobs.append(self.upload(rk, req.upload, depends_on=proc.id))
        return jobs

    # ---------------------------------------------------------------- internals

    def _fetch(self, rating_key: str) -> PlexItem:
        item = self._with_selected_version(self.plex.item(rating_key))
        self.workspace.save_item(item)
        return item

    def _with_selected_version(self, item: PlexItem) -> PlexItem:
        """Apply the manually chosen original version. If Plex no longer has that file, fall back to the default."""
        selected = self.workspace.selected_version(item.rating_key)
        if selected is None:
            return item
        if not any(v.file == selected for v in item.versions):
            log.warning("Selected version %s of item %s is gone, using %s", selected, item.rating_key, item.file)
            return item
        return item.with_version(selected, pinned=True)

    def _source_dependency(self, item: PlexItem) -> int | None:
        """None if the source is local; otherwise the id of an active or newly queued download job."""
        if self.workspace.find_source(item.rating_key):
            return None
        if (active := self._active_job(item.rating_key, JobType.download)) is not None:
            return active
        return self.runner.submit(JobType.download, item.rating_key, item.display_title).id

    def _active_job(self, rating_key: str, type: JobType) -> int | None:
        """Newest queued/running job of the given type for the item."""
        for job in self.store.list(rating_key=rating_key, active_only=True):  # newest first
            if job.type == type:
                return job.id
        return None

    def _item(self, ctx: JobContext) -> PlexItem:
        item = self.workspace.load_item(ctx.job.rating_key)
        if item is None:
            raise RuntimeError("Item metadata missing from workspace")
        return item

    def _source(self, ctx: JobContext) -> Path:
        src = self.workspace.find_source(ctx.job.rating_key)
        if src is None:
            raise RuntimeError("Source file not downloaded")
        return src

    def _run_download(self, ctx: JobContext) -> dict[str, Any]:
        item = self._item(ctx)
        if existing := self.workspace.find_source(item.rating_key):
            return {"message": "Already downloaded", "file": existing.name}
        target = self.workspace.source_target(item)
        self.ftp.download(self.paths.to_ftp(item.file), target, _bytes_progress(ctx), ctx.cancel)
        return {"message": "Downloaded", "file": target.name, "size": target.stat().st_size}

    def _run_preview(self, ctx: JobContext) -> dict[str, Any]:
        req = PreviewRequest.model_validate(ctx.job.params)
        src = self._source(ctx)
        run_dir = self.workspace.new_preview_dir(ctx.job.rating_key)
        clips = pipeline.create_previews(
            self.settings,
            src,
            run_dir,
            [get_preset(p) for p in req.presets],
            req.start_s,
            req.duration_s,
            ctx.progress,
            ctx.cancel,
        )
        run = PreviewRun(
            id=run_dir.name,
            start_s=req.start_s,
            duration_s=req.duration_s,
            created_at=datetime.now(UTC),
            clips=[self.workspace.preview_clip(run_dir, p.id, f) for p, f in clips],
        )
        self.workspace.save_preview(run_dir, run)
        return {"message": f"{len(clips)} preview clips", "preview": run.id}

    def _run_process(self, ctx: JobContext) -> dict[str, Any]:
        req = ProcessRequest.model_validate(ctx.job.params)
        item = self._item(ctx)
        preset = get_preset(req.preset)
        info = OutputInfo(
            file="",
            size=0,
            preset=preset.id,
            preset_name=preset.name,
            codec=req.codec,
            quality=req.quality,
            quality_auto=req.quality is None,
        )

        def title(quality: int, search: QualityResult | None) -> str:
            info.quality = quality
            info.vmaf = search.vmaf if search else None
            return f"Remastr: {info.label}"

        result = pipeline.process(
            self.settings,
            self._source(ctx),
            self.workspace.output_dir(item.rating_key),
            lambda h: self.workspace.output_name(item, h),
            preset,
            req.codec,
            req.quality,
            ctx.progress,
            ctx.cancel,
            video_title=title,
            target_vmaf=req.target_vmaf,
        )
        output = Path(result["file"])
        info.description = result.pop("plan")
        info.created_at = datetime.now(UTC)
        self.workspace.save_output_info(output, info)
        result["file"] = output.name
        result["preset"] = preset.id
        result["message"] = f"{info.label} · {info.description}"
        return result

    def _run_upload(self, ctx: JobContext) -> dict[str, Any]:
        req = UploadRequest.model_validate(ctx.job.params)
        item = self._item(ctx)
        outputs = self.workspace.outputs(item.rating_key)
        if not outputs:
            raise RuntimeError("No processed output to upload")
        local = max(outputs, key=lambda p: p.stat().st_mtime)
        made_with = self.workspace.output_info(item.rating_key, local)
        provenance = {
            "preset": made_with.preset,
            "preset_name": made_with.preset_name,
            "codec": made_with.codec,
            "quality": made_with.quality,
            "vmaf": made_with.vmaf,
        }
        original = self.paths.to_ftp(item.file)
        remote_dir = posixpath.dirname(original)
        progress = _bytes_progress(ctx)

        # Both modes upload under a temporary name Plex ignores and rename at the end, so Plex never indexes a
        # partial file.
        if req.mode == UploadMode.version:
            final = posixpath.join(remote_dir, local.name)
            if self.ftp.exists(final):
                raise RuntimeError(f"Target {final} already exists; not overwriting")
            self.ftp.upload(local, upload_tmp_name(final, local), progress, ctx.cancel)
            self.ftp.rename(upload_tmp_name(final, local), final)
            self.plex.refresh_folder(item.file)
            return {
                "message": f"Uploaded as additional version ({made_with.label}): {local.name}",
                "remote": final,
                **provenance,
            }

        # replace: upload, archive the original, then move the new file into place
        final = posixpath.join(remote_dir, Path(plex_basename(item.file)).stem + ".mkv")
        tmp = upload_tmp_name(final, local)
        archive = posixpath.join(self.settings.ftp_archive_root, original.lstrip("/"))
        if final != original and self.ftp.exists(final):
            raise RuntimeError(f"Target {final} already exists; not overwriting")
        self.ftp.upload(local, tmp, progress, ctx.cancel)
        ctx.progress(1.0, "archiving original")
        self.ftp.rename(original, archive)
        self.ftp.rename(tmp, final)
        self.plex.refresh_folder(item.file)
        return {
            "message": f"Original replaced ({made_with.label})",
            "remote": final,
            "archived_original": archive,
            **provenance,
        }


def upload_tmp_name(final: str, local: Path) -> str:
    """Temporary remote name, unique per local file content version, so a resumed upload only ever continues
    the same file. The suffix is not a video extension, so Plex ignores it."""
    st = local.stat()
    fingerprint = hashlib.sha1(f"{local.name}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:10]
    return f"{final}.{fingerprint}{UPLOAD_TMP_SUFFIX}"


def _bytes_progress(ctx: JobContext) -> Callable[[int, int], None]:
    def progress(done: int, total: int) -> None:
        ctx.progress(done / total if total else 0, f"{done / 1e6:,.0f} / {total / 1e6:,.0f} MB")

    return progress
