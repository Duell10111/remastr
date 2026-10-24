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
    assert svc.ftp.files[result["remote"]] == b"upscaled"
    assert svc.ftp.files[ORIGINAL] == b"original"
    assert not any(k.endswith(".remastr-upload") for k in svc.ftp.files)
    assert svc.plex.refreshed == [ITEM.file]


def test_version_upload_never_writes_partial_under_final_name(svc):
    """A cancelled upload must only leave a temporary file that Plex ignores."""
    from remastr.ftp import TransferCancelled

    def cancelled_upload(local, remote, on_progress=None, cancel=None):
        svc.ftp.files[remote] = local.read_bytes()[:3]
        raise TransferCancelled()

    make_output(svc)
    svc.ftp.upload = cancelled_upload
    with pytest.raises(TransferCancelled):
        run_upload(svc, UploadMode.version)
    leftovers = [k for k in svc.ftp.files if "Remastr" in k]
    assert len(leftovers) == 1 and leftovers[0].endswith(".remastr-upload")


def test_version_upload_does_not_overwrite_existing(svc):
    make_output(svc)
    svc.ftp.files["/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01 - Remastr 1080p.mkv"] = b"older"
    with pytest.raises(RuntimeError, match="already exists"):
        run_upload(svc, UploadMode.version)


def test_tmp_name_differs_per_local_file(tmp_path):
    import os

    from remastr.service import upload_tmp_name

    f = tmp_path / "a.mkv"
    f.write_bytes(b"first encode")
    first = upload_tmp_name("/tv/a.mkv", f)
    f.write_bytes(b"second encode!")
    os.utime(f, ns=(1, 1))
    assert upload_tmp_name("/tv/a.mkv", f) != first


def test_output_info_is_shown_and_reported_on_upload(svc):
    from remastr.models import OutputInfo

    out = make_output(svc)
    svc.workspace.save_output_info(
        out,
        OutputInfo(
            file="", size=0, preset="dpir_vsr", preset_name="DPIR deblock + NVIDIA VSR", codec="hevc", quality=26
        ),
    )
    [info] = svc.workspace.local_state(ITEM.rating_key).outputs
    assert (info.preset, info.quality, info.size) == ("dpir_vsr", 26, len(b"upscaled"))
    assert info.file == "output/Mickys Clubhaus - s01e01 - Remastr 1080p.mkv"
    result = run_upload(svc, UploadMode.version)
    assert result["preset"] == "dpir_vsr"
    assert "DPIR deblock + NVIDIA VSR, HEVC q26" in result["message"]


def test_output_without_info_still_listed(svc):
    make_output(svc)
    [info] = svc.workspace.local_state(ITEM.rating_key).outputs
    assert info.preset is None and info.size > 0


def test_upload_waits_for_running_process(svc):
    from remastr.models import ProcessRequest

    make_output(svc)  # a stale output exists
    proc = svc.process(ITEM.rating_key, ProcessRequest())
    upload = svc.upload(ITEM.rating_key, UploadRequest(mode=UploadMode.version))
    assert upload.depends_on == proc.id


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
