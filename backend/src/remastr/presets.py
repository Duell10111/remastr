"""Processing variants, based on comparison tests on an RTX 5070.

Findings: the anime models (esrgan, cugan) look great on cartoons but give live action a painted/waxy look.
On live action, SCUNet + RTX VSR gave the cleanest result, DPIR + VSR a close, slightly more textured second.
The default preset comes first (the UI preselects it).
"""

from remastr.models import DEFAULT_PRESET, Preset

PRESETS: list[Preset] = [
    Preset(
        id="scunet_vsr",
        name="SCUNet + NVIDIA VSR",
        description="Live action (default): blind real-world restoration (noise, compression) at source "
        "resolution, then RTX Video Super Resolution. Cleanest result.",
        vpy_mode="scunet",
        nvenc_resize="algo=ngx-vsr,vsr-quality=4",
    ),
    Preset(
        id="dpir_vsr",
        name="DPIR deblock + NVIDIA VSR",
        description="Live action: AI deblocking at source resolution, then RTX Video Super Resolution. "
        "Keeps a bit more texture than SCUNet.",
        vpy_mode="dpir",
        nvenc_resize="algo=ngx-vsr,vsr-quality=4",
    ),
    Preset(
        id="mild_vsr",
        name="Deblock/deband + NVIDIA VSR",
        description="Live action, fast: classic GPU filters plus RTX Video Super Resolution.",
        vpy_mode="passthrough",
        nvenc_filters=["--vpp-smooth", "quality=4,qp=10", "--vpp-deband", "range=15,thre=10,dither=8"],
        nvenc_resize="algo=ngx-vsr,vsr-quality=4",
    ),
    Preset(
        id="swinir_real",
        name="SwinIR real-world (GAN)",
        description="Live action: super-resolution trained on realistic degradations, can invent detail. "
        "Very slow (~1.5 fps on an RTX 5070, runs in fp32): previews and short clips only.",
        vpy_mode="swinir",
    ),
    Preset(
        id="waifu2x_photo",
        name="waifu2x swin_unet photo",
        description="Live action/photos: light denoise plus 4x upscale (scaled to target).",
        vpy_mode="waifu2x",
    ),
    Preset(
        id="esrgan",
        name="Real-ESRGAN animev3",
        description="Cartoons/anime: clean lines, close to the original. Makes live action look painted.",
        vpy_mode="esrgan",
    ),
    Preset(
        id="cugan",
        name="Real-CUGAN pro",
        description="Cartoons/anime: sharpest, crisp outlines; can thicken lines. Not for live action.",
        vpy_mode="cugan",
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
assert PRESETS[0].id == DEFAULT_PRESET


def get_preset(preset_id: str) -> Preset:
    try:
        return _BY_ID[preset_id]
    except KeyError:
        raise ValueError(f"Unknown preset '{preset_id}'. Available: {', '.join(_BY_ID)}") from None
