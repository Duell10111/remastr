"""Application service: the single API used by both the REST routes and the MCP tools."""

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
    PlexItem,
    Preset,
    PreviewRequest,
    PreviewRun,
    ProcessRequest,
    UploadMode,
    UploadRequest,
)
from remastr.plex import PlexService
from remastr.presets import PRESETS, get_preset
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
        return self.plex.search(query, library, limit)

    def presets(self) -> list[Preset]:
        return PRESETS

    def item(self, rating_key: str) -> ItemDetail:
        try:
            item = self.plex.item(rating_key)
            self.workspace.save_item(item)
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
        get_preset(req.preset)
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
        item = self.plex.item(rating_key)
        self.workspace.save_item(item)
        return item

    def _source_dependency(self, item: PlexItem) -> int | None:
        """None if the source is local; otherwise the id of an active or newly queued download job."""
        if self.workspace.find_source(item.rating_key):
            return None
        for job in self.store.list(rating_key=item.rating_key, active_only=True):
            if job.type == JobType.download:
                return job.id
        return self.runner.submit(JobType.download, item.rating_key, item.display_title).id

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
        result = pipeline.process(
            self.settings,
            self._source(ctx),
            self.workspace.output_dir(item.rating_key),
            lambda h: self.workspace.output_name(item, h),
            get_preset(req.preset),
            req.codec,
            req.quality,
            ctx.progress,
            ctx.cancel,
        )
        result["message"] = result.pop("plan")
        result["file"] = Path(result["file"]).name
        return result

    def _run_upload(self, ctx: JobContext) -> dict[str, Any]:
        req = UploadRequest.model_validate(ctx.job.params)
        item = self._item(ctx)
        outputs = self.workspace.outputs(item.rating_key)
        if not outputs:
            raise RuntimeError("No processed output to upload")
        local = max(outputs, key=lambda p: p.stat().st_mtime)
        original = self.paths.to_ftp(item.file)
        remote_dir = posixpath.dirname(original)
        progress = _bytes_progress(ctx)

        if req.mode == UploadMode.version:
            remote = posixpath.join(remote_dir, local.name)
            self.ftp.upload(local, remote, progress, ctx.cancel)
            self.plex.refresh_folder(item.file)
            return {"message": f"Uploaded as additional version: {local.name}", "remote": remote}

        # replace: upload under a temporary name, archive the original, then move the new file into place
        final = posixpath.join(remote_dir, Path(plex_basename(item.file)).stem + ".mkv")
        tmp = final + UPLOAD_TMP_SUFFIX
        archive = posixpath.join(self.settings.ftp_archive_root, original.lstrip("/"))
        self.ftp.upload(local, tmp, progress, ctx.cancel)
        if final != original and self.ftp.exists(final):
            raise RuntimeError(f"Target {final} already exists; not overwriting")
        ctx.progress(1.0, "archiving original")
        self.ftp.rename(original, archive)
        self.ftp.rename(tmp, final)
        self.plex.refresh_folder(item.file)
        return {"message": "Original replaced", "remote": final, "archived_original": archive}


def _bytes_progress(ctx: JobContext) -> Callable[[int, int], None]:
    def progress(done: int, total: int) -> None:
        ctx.progress(done / total if total else 0, f"{done / 1e6:,.0f} / {total / 1e6:,.0f} MB")

    return progress
