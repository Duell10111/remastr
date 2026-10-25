"""Automatic quality ("target VMAF"): the highest QVBR value, i.e. the smallest file, that still looks the same.

1. A few short samples spread over the file run through the full pipeline (AI model, NVEncC filters) and are
   encoded losslessly: that is the reference, the picture before compression.
2. Binary search over QVBR: re-encode the samples, measure VMAF against the reference, keep the highest QVBR whose
   mean VMAF reaches the target and whose worst sample stays close to it.
Monotonic in practice (higher QVBR -> lower VMAF), so 4 probes cover the search range.
"""

import json
import math
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from remastr.config import Settings
from remastr.models import Preset
from remastr.pipeline import (
    _NO_WINDOW,
    Cancelled,
    MediaInfo,
    PipelineError,
    Plan,
    ProgressFn,
    build_nvencc_cmd,
    build_vspipe_cmd,
    run_encode,
)

SEARCH_RANGE = {"hevc": (18, 32), "av1": (20, 50)}
"""QVBR range per codec (NVEncC scale: HEVC 0-51, AV1 0-63). The upper bound caps the search: beyond it GAN texture
starts to disappear even when VMAF still looks fine."""
SAMPLES = 5
SAMPLE_S = 8.0
WORST_MARGIN = 3.0
"""The worst sample may be this much below the target (e.g. dark or very busy scenes)."""


class QualityProbe(BaseModel):
    quality: int
    vmaf: float
    """Mean VMAF over all sample frames."""
    worst: float
    """Mean VMAF of the worst sample."""
    kbps: float


class QualityResult(BaseModel):
    quality: int
    vmaf: float
    worst: float
    target: float
    reached: bool
    """False if even the lowest QVBR in the search range misses the target (then that one is used)."""
    est_size: int
    """Estimated size of the full video stream in bytes (without audio)."""
    probes: list[QualityProbe]


@dataclass
class _Samples:
    ranges: list[tuple[int, int]]
    fps: float
    files: list[Path] = field(default_factory=list)

    @property
    def lengths(self) -> list[int]:
        return [b - a + 1 for a, b in self.ranges]


def sample_ranges(
    total_frames: int, fps: float, samples: int = SAMPLES, sample_s: float = SAMPLE_S
) -> list[tuple[int, int]]:
    """Inclusive frame ranges, spread over 5%..95% of the file (skips intros/credits)."""
    length = max(1, round(sample_s * fps))
    if total_frames <= samples * length * 2:
        n = min(total_frames, samples * length)
        start = (total_frames - n) // 2
        return [(start, start + n - 1)]
    lo, hi = int(total_frames * 0.05), int(total_frames * 0.95) - length
    step = (hi - lo) / max(1, samples - 1)
    return [(round(lo + i * step), round(lo + i * step) + length - 1) for i in range(samples)]


def passes(probe: QualityProbe, target: float) -> bool:
    return probe.vmaf >= target and probe.worst >= target - WORST_MARGIN


def search(measure, lo: int, hi: int, target: float) -> tuple[QualityProbe, list[QualityProbe]]:
    """Largest quality value in [lo, hi] that passes; the lowest one if none does."""
    probes: dict[int, QualityProbe] = {}
    best: QualityProbe | None = None
    a, b = lo, hi
    while a <= b:
        q = (a + b + 1) // 2
        probes[q] = measure(q)
        if passes(probes[q], target):
            best, a = probes[q], q + 1
        else:
            b = q - 1
    if best is None:
        best = probes.get(lo) or measure(lo)
        probes[lo] = best
    return best, [probes[q] for q in sorted(probes)]


def find_quality(
    settings: Settings,
    src: Path,
    info: MediaInfo,
    plan: Plan,
    preset: Preset,
    codec: str,
    target: float,
    work_dir: Path,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> QualityResult:
    lo, hi = SEARCH_RANGE[codec]
    total = max(1, math.floor(info.duration * plan.out_fps))
    samples = _Samples(sample_ranges(total, plan.out_fps), plan.out_fps)
    work_dir.mkdir(parents=True, exist_ok=True)
    steps = len(samples.ranges) + math.ceil(math.log2(hi - lo + 2))

    def report(done: int, msg: str) -> None:
        if on_progress:
            on_progress(min(done / steps, 1.0), msg)

    try:
        for i, frames in enumerate(samples.ranges):
            report(i, f"quality search: reference sample {i + 1}/{len(samples.ranges)}")
            out = work_dir / f"ref{i}.mkv"
            run_encode(
                build_vspipe_cmd(settings, src, plan, preset, work_dir / "source.lwi", frames),
                build_nvencc_cmd(settings, plan, preset, out, "hevc", None),
                frames[1] - frames[0] + 1,
                work_dir / f"ref{i}.vspipe.log",
                None,
                cancel,
            )
            samples.files.append(out)
        reference = _concat(settings, samples.files, work_dir / "reference.mkv")
        seconds = sum(samples.lengths) / samples.fps
        done = len(samples.ranges)

        def measure(q: int) -> QualityProbe:
            nonlocal done
            report(done, f"quality search: testing q{q}")
            out = work_dir / f"q{q}.mkv"
            run_encode(
                [settings.ffmpeg, "-v", "error", "-i", str(reference), "-f", "yuv4mpegpipe", "-strict", "-1", "-"],
                _probe_encode_cmd(settings, codec, q, out),
                sum(samples.lengths),
                work_dir / f"q{q}.decode.log",
                None,
                cancel,
            )
            scores = _vmaf(settings, out, reference, work_dir, cancel)
            per_sample, pos = [], 0
            for n in samples.lengths:
                chunk = scores[pos : pos + n]
                per_sample.append(sum(chunk) / max(1, len(chunk)))
                pos += n
            probe = QualityProbe(
                quality=q,
                vmaf=round(sum(scores) / max(1, len(scores)), 2),
                worst=round(min(per_sample), 2),
                kbps=round(out.stat().st_size * 8 / 1000 / seconds, 1),
            )
            done += 1
            report(done, f"quality search: q{q} -> VMAF {probe.vmaf} (worst sample {probe.worst})")
            return probe

        best, probes = search(measure, lo, hi, target)
    finally:
        for p in work_dir.glob("*"):
            p.unlink(missing_ok=True)
        work_dir.rmdir()
    return QualityResult(
        quality=best.quality,
        vmaf=best.vmaf,
        worst=best.worst,
        target=target,
        reached=passes(best, target),
        est_size=round(best.kbps * 1000 / 8 * info.duration),
        probes=probes,
    )


def _probe_encode_cmd(settings: Settings, codec: str, quality: int, out: Path) -> list[str]:
    """Same encoder settings as the real encode (build_nvencc_cmd), without filters: the reference already has them."""
    return [
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
        "10",
        "-o",
        str(out),
    ]


def _concat(settings: Settings, parts: list[Path], dest: Path) -> Path:
    if len(parts) == 1:
        return parts[0]
    cmd = [str(settings.mkvmerge), "-q", "-o", str(dest), str(parts[0])]
    for p in parts[1:]:
        cmd += ["+", str(p)]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if res.returncode > 1:
        raise PipelineError(f"mkvmerge (reference samples) failed: {(res.stdout + res.stderr).strip()[-500:]}")
    return dest


def _vmaf(
    settings: Settings, distorted: Path, reference: Path, cwd: Path, cancel: threading.Event | None
) -> list[float]:
    """Per-frame VMAF scores. Runs in cwd with a relative log path (Windows drive colons break filter args)."""
    log = "vmaf.json"
    cmd = [
        settings.ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(distorted),
        "-i",
        str(reference),
        "-lavfi",
        f"[0:v][1:v]libvmaf=log_path={log}:log_fmt=json:n_threads=8",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    while True:
        try:
            _, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                raise Cancelled() from None
    if proc.returncode != 0:
        raise PipelineError(f"VMAF failed: {err.decode('utf-8', 'replace').strip()[-500:]}")
    data = json.loads((cwd / log).read_text("utf-8"))
    return [f["metrics"]["vmaf"] for f in data["frames"]]
