import pytest

from remastr.jobs import JobContext
from remastr.models import JobType, UploadMode, UploadRequest

from .conftest import ITEM

ORIGINAL = "/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01.ts"


def make_output(svc, name="Mickys Clubhaus - s01e01 - Remastr 1080p.mkv"):
    svc.workspace.save_item(ITEM)
    out = svc.workspace.output_dir(ITEM.rating_key) / name
    out.parent.mkdir(parents=True)
    out.write_bytes(b"upscaled")
    return out


def run_upload(svc, mode, confirm=False):
    job = svc.store.create(
        JobType.upload, ITEM.rating_key, params=UploadRequest(mode=mode, confirm=confirm).model_dump()
    )
    return svc._run_upload(JobContext(job=job, store=svc.store))


def test_output_name_uses_version_suffix(svc):
    assert svc.workspace.output_name(ITEM, 1080) == "Mickys Clubhaus - s01e01 - Remastr 1080p.mkv"


def test_upload_as_version_keeps_original(svc):
    make_output(svc)
    result = run_upload(svc, UploadMode.version)
    assert result["remote"] == "/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01 - Remastr 1080p.mkv"
    assert svc.ftp.files[ORIGINAL] == b"original"
    assert svc.plex.refreshed == [ITEM.file]


def test_replace_archives_original(svc):
    make_output(svc)
    result = run_upload(svc, UploadMode.replace, confirm=True)
    assert result["remote"] == "/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01.mkv"
    assert ORIGINAL not in svc.ftp.files
    assert svc.ftp.files["/archive" + ORIGINAL] == b"original"
    assert svc.ftp.files[result["remote"]] == b"upscaled"
    assert not any(k.endswith(".remastr-upload") for k in svc.ftp.files)


def test_replace_requires_confirmation(svc):
    make_output(svc)
    with pytest.raises(ValueError, match="confirm"):
        svc.upload(ITEM.rating_key, UploadRequest(mode=UploadMode.replace))


def test_process_queues_download_first(svc):
    from remastr.models import ProcessRequest

    job = svc.process(ITEM.rating_key, ProcessRequest(preset="esrgan"))
    download = svc.store.get(job.depends_on)
    assert download.type == JobType.download
    # A second request reuses the pending download
    again = svc.process(ITEM.rating_key, ProcessRequest(preset="cugan"))
    assert again.depends_on == download.id


def test_unknown_preset_rejected(svc):
    from remastr.models import PreviewRequest

    with pytest.raises(ValueError, match="Unknown preset"):
        svc.preview(ITEM.rating_key, PreviewRequest(presets=["nope"]))


def test_workspace_resolve_blocks_traversal(svc):
    make_output(svc)
    with pytest.raises(FileNotFoundError):
        svc.media_file(ITEM.rating_key, "../../remastr.db")
