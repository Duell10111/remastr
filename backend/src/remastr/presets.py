"""Processing variants. Based on the comparison tests with SD cartoon material on an RTX 5070."""

from remastr.models import Preset

PRESETS: list[Preset] = [
    Preset(
        id="esrgan",
        name="Real-ESRGAN animev3",
        description="Anime/cartoon video model (4x, then scaled to target). Clean and close to the original. Default.",
        vpy_mode="esrgan",
    ),
    Preset(
        id="cugan",
        name="Real-CUGAN pro",
        description="Sharpest result with crisp outlines; can thicken/darken lines. Slower.",
        vpy_mode="cugan",
    ),
    Preset(
        id="dpir_vsr",
        name="DPIR deblock + NVIDIA VSR",
        description="AI deblocking at source resolution, then RTX Video Super Resolution. Clean but softer.",
        vpy_mode="dpir",
        nvenc_resize="algo=ngx-vsr,vsr-quality=4",
    ),
    Preset(
        id="mild_vsr",
        name="Deblock/deband + NVIDIA VSR",
        description="Classic GPU filters plus RTX Video Super Resolution. Very fast.",
        vpy_mode="passthrough",
        nvenc_filters=["--vpp-smooth", "quality=4,qp=10", "--vpp-deband", "range=15,thre=10,dither=8"],
        nvenc_resize="algo=ngx-vsr,vsr-quality=4",
    ),
    Preset(
        id="lanczos",
        name="Lanczos (reference)",
        description="Plain resize without AI, for comparison.",
        vpy_mode="passthrough",
        nvenc_resize="lanczos",
    ),
]

_BY_ID = {p.id: p for p in PRESETS}
DEFAULT_PRESET = "esrgan"


def get_preset(preset_id: str) -> Preset:
    try:
        return _BY_ID[preset_id]
    except KeyError:
        raise ValueError(f"Unknown preset '{preset_id}'. Available: {', '.join(_BY_ID)}") from None
