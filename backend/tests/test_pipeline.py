from pathlib import Path

from remastr.pipeline import MediaInfo, build_nvencc_cmd, build_vspipe_cmd, effective_preset, make_plan
from remastr.presets import get_preset


def info(w, h, dar, color_space="", fps=25.0):
    return MediaInfo(
        width=w,
        height=h,
        dar=dar,
        field_order="",
        color_space=color_space,
        fps=fps,
        duration=60,
        video_start=0,
        min_start=0,
    )


def test_pal_anamorphic_interlaced():
    plan = make_plan(info(720, 576, 16 / 9), "tff", 1080)
    assert (plan.out_w, plan.out_h, plan.upscale, plan.deint) == (1920, 1080, True, "tff")
    assert plan.out_fps == 50
    assert plan.matrix_in == "170m"


def test_small_4_3_progressive():
    plan = make_plan(info(480, 360, 4 / 3, fps=24000 / 1001), "none", 1080)
    assert (plan.out_w, plan.out_h, plan.upscale) == (1440, 1080, True)


def test_hd_is_only_deinterlaced():
    plan = make_plan(info(1920, 1080, 16 / 9, "bt709"), "tff", 1080)
    assert (plan.out_w, plan.out_h, plan.upscale, plan.matrix_in) == (1920, 1080, False, "709")
    assert effective_preset(plan, get_preset("esrgan")).vpy_mode == "passthrough"


def test_nvencc_scales_only_for_non_vapoursynth_presets(settings):
    plan = make_plan(info(720, 576, 4 / 3), "none", 1080)
    esrgan = build_nvencc_cmd(settings, plan, get_preset("esrgan"), Path("o.mkv"), "hevc", 20)
    vsr = build_nvencc_cmd(settings, plan, get_preset("mild_vsr"), Path("o.mkv"), "hevc", 20)
    assert "--vpp-resize" not in esrgan and "bt709" in esrgan
    assert vsr[vsr.index("--output-res") + 1] == "1440x1080"
    assert "smpte170m" in vsr  # NVEncC-scaled output keeps the source matrix
    assert vsr.index("--vpp-smooth") < vsr.index("--vpp-resize")


def test_scaling_stage_per_preset(settings):
    plan = make_plan(info(640, 360, 16 / 9), "none", 1080)
    scunet = build_nvencc_cmd(settings, plan, get_preset("scunet_vsr"), Path("o.mkv"), "hevc", 26)
    swinir = build_nvencc_cmd(settings, plan, get_preset("swinir_real"), Path("o.mkv"), "hevc", 26)
    assert scunet[scunet.index("--output-res") + 1] == "1920x1080"
    assert "--vpp-resize" not in swinir and "bt709" in swinir


def test_onnx_preset_passes_model_path(settings):
    plan = make_plan(info(640, 360, 16 / 9), "none", 1080)
    cmd = build_vspipe_cmd(settings, Path("in.mp4"), plan, get_preset("realesr_general"), Path("c.lwi"))
    onnx = next(a for a in cmd if a.startswith("onnx="))
    assert onnx.endswith(str(Path("models/remastr/realesr-general-x4v3.onnx")))
    nvenc = build_nvencc_cmd(settings, plan, get_preset("realesr_general"), Path("o.mkv"), "hevc", 26)
    assert "--vpp-resize" not in nvenc  # VapourSynth scales


def test_extra_presets_from_json(tmp_path):
    import json

    import pytest

    from remastr.presets import load_extra_presets

    path = tmp_path / "presets.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "my_model",
                    "name": "Mine",
                    "description": "test",
                    "vpy_mode": "onnx",
                    "onnx_model": "C:/models/mine.onnx",
                }
            ]
        )
    )
    from remastr import presets

    try:
        assert [p.id for p in load_extra_presets(path)] == ["my_model"]
        assert get_preset("my_model").onnx_model == "C:/models/mine.onnx"
        with pytest.raises(ValueError, match="already exists"):
            load_extra_presets(path)
    finally:  # presets are module-global; don't leak into other tests
        presets.PRESETS[:] = [p for p in presets.PRESETS if p.id != "my_model"]
        presets._BY_ID.pop("my_model", None)


def test_preview_uses_h264_8bit(settings):
    plan = make_plan(info(720, 576, 4 / 3), "none", 1080)
    cmd = build_nvencc_cmd(settings, plan, get_preset("esrgan"), Path("p.mp4"), "h264", 20)
    assert cmd[cmd.index("--output-depth") + 1] == "8"


def test_vspipe_frame_range_and_args(settings):
    plan = make_plan(info(720, 576, 16 / 9), "bff", 1080)
    cmd = build_vspipe_cmd(settings, Path("in.ts"), plan, get_preset("cugan"), Path("c.lwi"), (100, 199))
    assert "deint=bff" in cmd and "mode=cugan" in cmd and "outw=1920" in cmd
    assert cmd[cmd.index("-s") + 1] == "100" and cmd[cmd.index("-e") + 1] == "199"
    assert cmd[-2].endswith("remastr.vpy") and cmd[-1] == "-"


def test_onnx_padding_and_precision_args(settings):
    plan = make_plan(info(640, 360, 16 / 9), "none", 1080)
    hat = build_vspipe_cmd(settings, Path("in.mp4"), plan, get_preset("real_hat"), Path("c.lwi"))
    general = build_vspipe_cmd(settings, Path("in.mp4"), plan, get_preset("realesr_general"), Path("c.lwi"))
    assert "multiple=16" in hat and "fp16=0" in hat and "streams=1" in hat
    assert "multiple=1" in general and "fp16=1" in general and "streams=2" in general
