"""Video processing: analysis, VapourSynth -> NVEncC encoding, muxing audio/subtitles back in.

Mirrors the upscale.ps1 workflow that was validated on an RTX 5070:
  ffprobe + idet  ->  vspipe (QTGMC, AI model)  |  NVEncC (filters, scaling, HW encode)  ->  mkvmerge
"""

import json
import math
import re
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from remastr.config import Settings
from remastr.models import Preset

ProgressFn = Callable[[float, str], None]
"""(fraction 0..1, message)"""

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_STANDARD_DARS = (4 / 3, 16 / 9)


class Cancelled(Exception):
    pass


class PipelineError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    dar: float
    field_order: str
    color_space: str
    fps: float
    duration: float
    video_start: float
    min_start: float


@dataclass(frozen=True)
class Plan:
    deint: str
    """none | tff | bff"""
    upscale: bool
    out_w: int
    out_h: int
    out_fps: float
    matrix_in: str
    """VapourSynth matrix name of the source: 709 | 170m"""


def _ratio(value: str | None) -> float | None:
    m = re.fullmatch(r"(\d+)[:/](\d+)", value or "")
    if not m or int(m[1]) == 0 or int(m[2]) == 0:
        return None
    return int(m[1]) / int(m[2])


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def probe(settings: Settings, path: Path) -> MediaInfo:
    res = _run([settings.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", "--", str(path)])
    if res.returncode != 0:
        raise PipelineError(f"ffprobe failed: {res.stderr.strip()}")
    data = json.loads(res.stdout)
    video = next(
        (
            s
            for s in data.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise PipelineError("No video stream found")

    sar = _ratio(video.get("sample_aspect_ratio")) or 1.0
    dar = video["width"] * sar / video["height"]
    # PAL/NTSC widths include overscan, so snap to the standard ratios
    for std in _STANDARD_DARS:
        if abs(dar / std - 1) < 0.03:
            dar = std

    starts = [float(s["start_time"]) for s in data["streams"] if s.get("start_time") not in (None, "N/A")]
    return MediaInfo(
        width=int(video["width"]),
        height=int(video["height"]),
        dar=dar,
        field_order=video.get("field_order", ""),
        color_space=video.get("color_space", ""),
        fps=_ratio(video.get("r_frame_rate")) or 25.0,
        duration=float(data["format"].get("duration") or 0),
        video_start=float(video.get("start_time") or 0),
        min_start=min(starts) if starts else 0.0,
    )


def detect_scan(settings: Settings, path: Path, info: MediaInfo) -> str:
    """Detect interlacing from the picture content (DVB flags are often wrong)."""
    seek = min(300.0, max(0.0, info.duration / 3))
    res = _run(
        [
            settings.ffmpeg,
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{seek:.1f}",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-frames:v",
            "600",
            "-vf",
            "idet",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=600,
    )
    found = re.findall(r"Multi frame detection: TFF:\s*(\d+)\s+BFF:\s*(\d+)\s+Progressive:\s*(\d+)", res.stderr)
    if found:
        tff, bff, prog = map(int, found[-1])
        if tff + bff > prog:
            return "tff" if tff >= bff else "bff"
        if tff + bff + prog > 0:
            return "none"
    return {"tt": "tff", "tb": "tff", "bb": "bff", "bt": "bff"}.get(info.field_order, "none")


def make_plan(info: MediaInfo, scan: str, target_height: int) -> Plan:
    upscale = info.height < 720
    out_h = target_height if upscale else info.height
    out_w = int(round(out_h * info.dar / 2) * 2)
    if "709" in info.color_space:
        matrix_in = "709"
    elif info.color_space in ("smpte170m", "bt470bg"):
        matrix_in = "170m"
    else:
        matrix_in = "709" if info.height >= 720 else "170m"
    return Plan(
        deint=scan,
        upscale=upscale,
        out_w=out_w,
        out_h=out_h,
        out_fps=info.fps * (2 if scan != "none" else 1),
        matrix_in=matrix_in,
    )


def effective_preset(plan: Plan, preset: Preset) -> Preset:
    """HD sources are only deinterlaced; AI models and VSR are meant for SD."""
    if plan.upscale:
        return preset
    return Preset(id=preset.id, name=preset.name, description=preset.description, vpy_mode="passthrough")


def _output_matrix(plan: Plan, preset: Preset) -> str:
    if preset.scales_in_vapoursynth:
        return "709"
    return plan.matrix_in


def build_vspipe_cmd(
    settings: Settings, src: Path, plan: Plan, preset: Preset, cache: Path, frames: tuple[int, int] | None = None
) -> list[str]:
    script = resources.files("remastr") / "vapoursynth" / "remastr.vpy"
    args = {
        "src": str(src),
        "cache": str(cache),
        "plugins": str(settings.vs_plugins),
        "mlrt": str(settings.vsmlrt_dir),
        "deint": plan.deint,
        "mode": preset.vpy_mode,
        "outw": str(plan.out_w),
        "outh": str(plan.out_h),
        "matrix_in": plan.matrix_in,
        "fp16": "1" if preset.fp16 else "0",
        "streams": str(preset.num_streams),
    }
    if preset.vpy_mode == "onnx":
        if not preset.onnx_model:
            raise PipelineError(f"Preset {preset.id} has no onnx_model")
        args["onnx"] = str(settings.vsmlrt_dir / "models" / preset.onnx_model)  # absolute paths stay absolute
        args["multiple"] = str(preset.onnx_multiple)
    cmd = [str(settings.vspipe), "-c", "y4m"]
    for k, v in args.items():
        cmd += ["-a", f"{k}={v}"]
    if frames:
        cmd += ["-s", str(frames[0]), "-e", str(frames[1])]
    return cmd + [str(script), "-"]


def build_nvencc_cmd(settings: Settings, plan: Plan, preset: Preset, out: Path, codec: str, quality: int) -> list[str]:
    matrix = _output_matrix(plan, preset)
    vui = "bt709" if matrix == "709" else "smpte170m"
    cmd = [
        str(settings.nvencc),
        "--y4m",
        "-i",
        "-",
        "-c",
        codec,
        "--preset",
        "p7",
        "--qvbr",
        str(quality),
        "--output-depth",
        "8" if codec == "h264" else "10",
    ]
    cmd += preset.nvenc_filters
    if not preset.scales_in_vapoursynth and preset.nvenc_resize and plan.upscale:
        cmd += ["--vpp-resize", preset.nvenc_resize, "--output-res", f"{plan.out_w}x{plan.out_h}"]
    cmd += ["--sar", "1:1", "--colormatrix", vui, "--colorprim", vui, "--transfer", vui, "-o", str(out)]
    return cmd


def run_encode(
    vs_cmd: list[str],
    enc_cmd: list[str],
    total_frames: int,
    log_path: Path,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Run vspipe | NVEncC, report progress from NVEncC's frame counter."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as vs_log:
        vs = subprocess.Popen(vs_cmd, stdout=subprocess.PIPE, stderr=vs_log, creationflags=_NO_WINDOW)
        enc = subprocess.Popen(
            enc_cmd, stdin=vs.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NO_WINDOW
        )
        assert vs.stdout is not None and enc.stderr is not None
        vs.stdout.close()  # NVEncC owns the read end now
        tail: deque[str] = deque(maxlen=15)
        buf = b""
        try:
            while chunk := enc.stderr.read1(4096):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                buf += chunk
                *lines, buf = re.split(rb"[\r\n]", buf)
                for raw in lines:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    tail.append(line)
                    m = re.match(r"(?:\[[\d.]+%\]\s*)?(\d+) frames: ([\d.]+) fps", line)
                    if m and on_progress and total_frames > 0:
                        done = int(m[1])
                        on_progress(min(done / total_frames, 1.0), f"{done}/{total_frames} frames, {m[2]} fps")
        except BaseException:
            enc.kill()
            vs.kill()
            raise
        finally:
            enc_rc = enc.wait()
            vs_rc = vs.wait()
    if enc_rc != 0 or vs_rc != 0:
        vs_tail = log_path.read_text("utf-8", "replace").strip().splitlines()[-6:]
        raise PipelineError(
            f"Encoding failed (vspipe {vs_rc}, NVEncC {enc_rc}).\nvspipe: {' / '.join(vs_tail)}\n"
            f"NVEncC: {' / '.join(list(tail)[-6:])}"
        )


def mux(
    settings: Settings, video: Path, source: Path, dest: Path, sync_ms: int, video_title: str | None = None
) -> None:
    """Combine the new video with audio + subtitles of the source, compensating the A/V start offset.
    video_title becomes the video track name (shown by Plex in the media info)."""
    cmd = [str(settings.mkvmerge), "-q", "-o", str(dest), "--no-global-tags"]
    if video_title:
        cmd += ["--track-name", f"0:{video_title}"]
    cmd += [
        str(video),
        "--no-video",
        "--no-attachments",
    ]
    if sync_ms:
        cmd += ["--sync", f"-1:{sync_ms}"]
    cmd.append(str(source))
    res = _run(cmd)
    if res.returncode > 1:  # 1 = warnings only
        raise PipelineError(f"mkvmerge failed: {(res.stdout + res.stderr).strip()[-800:]}")


def duration_of(settings: Settings, path: Path) -> float:
    res = _run([settings.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def analyze(settings: Settings, src: Path) -> tuple[MediaInfo, Plan]:
    info = probe(settings, src)
    scan = detect_scan(settings, src, info)
    return info, make_plan(info, scan, settings.target_height)


def describe(info: MediaInfo, plan: Plan) -> str:
    scan = "progressive" if plan.deint == "none" else f"interlaced ({plan.deint}) -> QTGMC"
    mode = "AI upscale" if plan.upscale else "HD, deinterlace only"
    return f"{info.width}x{info.height} -> {plan.out_w}x{plan.out_h}, {scan}, {mode}"


def create_previews(
    settings: Settings,
    src: Path,
    out_dir: Path,
    presets: list[Preset],
    start_s: float,
    duration_s: float,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> list[tuple[Preset, Path]]:
    """Encode the same frame range with each preset as browser-friendly H.264 MP4 (no audio)."""
    info, plan = analyze(settings, src)
    total = max(1, math.floor(info.duration * plan.out_fps))
    first = min(int(start_s * plan.out_fps), total - 1)
    last = min(first + max(1, int(duration_s * plan.out_fps)) - 1, total - 1)
    count = last - first + 1
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, preset in enumerate(presets):
        eff = effective_preset(plan, preset)
        out = out_dir / f"{preset.id}.mp4"

        def step(frac: float, msg: str, i: int = i, name: str = preset.name) -> None:
            if on_progress:
                on_progress((i + frac) / len(presets), f"{name}: {msg}")

        step(0, "starting")
        run_encode(
            build_vspipe_cmd(settings, src, plan, eff, out_dir / "source.lwi", (first, last)),
            build_nvencc_cmd(settings, plan, eff, out, "h264", 20),
            count,
            out_dir / f"{preset.id}.vspipe.log",
            step,
            cancel,
        )
        results.append((preset, out))
    return results


def process(
    settings: Settings,
    src: Path,
    dest_dir: Path,
    name_for_height: Callable[[int], str],
    preset: Preset,
    codec: str,
    quality: int,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    video_title: str | None = None,
) -> dict:
    """Full-length processing with audio and subtitles. Writes the result atomically."""
    info, plan = analyze(settings, src)
    eff = effective_preset(plan, preset)
    dest = dest_dir / name_for_height(plan.out_h)
    if on_progress:
        on_progress(0, describe(info, plan))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_video = dest.with_name(dest.stem + ".video.mkv")
    tmp_mux = dest.with_name(dest.stem + ".partial.mkv")
    try:
        run_encode(
            build_vspipe_cmd(settings, src, plan, eff, dest.with_name(dest.stem + ".lwi")),
            build_nvencc_cmd(settings, plan, eff, tmp_video, codec, quality),
            max(1, math.floor(info.duration * plan.out_fps)),
            dest.with_name(dest.stem + ".vspipe.log"),
            on_progress,
            cancel,
        )
        if on_progress:
            on_progress(1.0, "muxing audio/subtitles")
        mux(settings, tmp_video, src, tmp_mux, round((info.min_start - info.video_start) * 1000), video_title)
        out_dur = duration_of(settings, tmp_mux)
        if abs(out_dur - info.duration) > 2:
            raise PipelineError(f"Output duration {out_dur:.1f}s differs from source {info.duration:.1f}s")
        tmp_mux.replace(dest)
    finally:
        for p in (tmp_video, tmp_mux, dest.with_name(dest.stem + ".lwi")):
            p.unlink(missing_ok=True)
    return {
        "file": str(dest),
        "size": dest.stat().st_size,
        "duration_s": info.duration,
        "width": plan.out_w,
        "height": plan.out_h,
        "plan": describe(info, plan),
    }
