from pathlib import Path

import pytest
from pydantic import ValidationError

from remastr.models import OutputInfo, ProcessRequest
from remastr.pipeline import MediaInfo, build_nvencc_cmd, make_plan
from remastr.presets import get_preset
from remastr.quality import QualityProbe, sample_ranges, search


def vmaf_curve(q: int) -> QualityProbe:
    """Monotonic fake: VMAF drops by 1 per QVBR step, 97 at q24."""
    vmaf = 97 - (q - 24)
    return QualityProbe(quality=q, vmaf=vmaf, worst=vmaf - 1, kbps=10000 / q)


def test_search_finds_highest_passing_quality():
    measured = []

    def measure(q):
        measured.append(q)
        return vmaf_curve(q)

    best, probes = search(measure, 18, 32, 95.0)
    assert best.quality == 26  # VMAF 95; q27 gives 94
    assert len(measured) <= 4
    assert [p.quality for p in probes] == sorted(measured)


def test_search_respects_worst_sample_margin():
    def measure(q):
        p = vmaf_curve(q)
        return p.model_copy(update={"worst": p.vmaf - 5 if q >= 22 else p.vmaf})  # one bad scene from q22 on

    best, _ = search(measure, 18, 32, 95.0)
    assert best.quality == 24  # q25/q26 reach the mean, but their worst sample is more than 3 below the target


def test_search_falls_back_to_lowest_quality():
    best, probes = search(lambda q: QualityProbe(quality=q, vmaf=80, worst=79, kbps=1), 18, 32, 95.0)
    assert best.quality == 18
    assert probes[0].quality == 18


def test_sample_ranges_spread_over_the_file():
    ranges = sample_ranges(total_frames=33000, fps=25)
    assert len(ranges) == 5
    assert all(b - a + 1 == 200 for a, b in ranges)
    assert ranges[0][0] >= 33000 * 0.05 and ranges[-1][1] < 33000 * 0.95
    assert all(ranges[i][1] < ranges[i + 1][0] for i in range(4))


def test_sample_ranges_short_file_uses_middle():
    assert sample_ranges(total_frames=1000, fps=25) == [(0, 999)]
    assert sample_ranges(total_frames=1500, fps=25) == [(250, 1249)]


def test_lossless_reference_encode(settings):
    info = MediaInfo(640, 360, 16 / 9, "", "", 25.0, 60, 0, 0)
    plan = make_plan(info, "none", 1080)
    cmd = build_nvencc_cmd(settings, plan, get_preset("scunet_vsr"), Path("ref.mkv"), "hevc", None)
    assert "--lossless" in cmd and "--qvbr" not in cmd
    assert "--vpp-resize" in cmd  # the reference contains the preset's NVEncC stage


def test_process_request_quality():
    assert ProcessRequest().quality is None  # automatic by default
    assert ProcessRequest(codec="av1", quality=40).quality == 40
    with pytest.raises(ValidationError):
        ProcessRequest(codec="hevc", quality=55)


def test_output_label_names_automatic_quality():
    info = OutputInfo(file="x", size=1, preset_name="P", codec="hevc", quality=28, quality_auto=True, vmaf=95.43)
    assert info.label == "P, HEVC q28 (auto, VMAF 95.4)"
    assert OutputInfo(file="x", size=1, preset_name="P", codec="hevc", quality=26).label == "P, HEVC q26"
