"""Processing variants, based on comparison tests on an RTX 5070.

Findings: the anime models (esrgan, cugan) look great on cartoons but give live action a painted/waxy look.
On live action, Real-ESRGAN general x4v3 gave the most visible HD look at high speed; SCUNet + RTX VSR is the
cleanest but softest, DPIR + VSR a slightly more textured alternative.
The default preset comes first (the UI preselects it).
"""

from pathlib import Path

from pydantic import TypeAdapter

from remastr.models import DEFAULT_PRESET, Preset

PRESETS: list[Preset] = [
    # Real-ESRGAN real-world GANs, converted from the official weights (see tools/convert_realesrgan.py)
    Preset(
        id="realesr_general",
        name="Real-ESRGAN general x4v3",
        description="Live action (default), GAN, fast: most visible HD look, sharp edges and texture, "
        "skin stays natural. No extra denoising.",
        vpy_mode="onnx",
        onnx_model="remastr/realesr-general-x4v3.onnx",
    ),
    Preset(
        id="scunet_vsr",
        name="SCUNet + NVIDIA VSR",
        description="Live action: blind real-world restoration (noise, compression) at source "
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
        id="realesr_general_dn",
        name="Real-ESRGAN general x4v3 (denoise 50%)",
        description="Live action GAN, fast: like general x4v3 but smoother, for noisy or blocky sources.",
        vpy_mode="onnx",
        onnx_model="remastr/realesr-general-x4v3-dn50.onnx",
    ),
    Preset(
        id="realesrgan_x4plus",
        name="Real-ESRGAN x4plus",
        description="Live action GAN classic: strongest sharpening and texture; skin can look plastic. Slow.",
        vpy_mode="onnx",
        onnx_model="remastr/RealESRGAN_x4plus.onnx",
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


def load_extra_presets(path: Path) -> list[Preset]:
    """Add user presets from a JSON list (e.g. own ONNX models). Ids must not collide with built-in ones."""
    if not path.is_file():
        return []
    extra = TypeAdapter(list[Preset]).validate_json(path.read_bytes())
    for preset in extra:
        if preset.id in _BY_ID:
            raise ValueError(f"{path}: preset id '{preset.id}' already exists")
        PRESETS.append(preset)
        _BY_ID[preset.id] = preset
    return extra


def get_preset(preset_id: str) -> Preset:
    try:
        return _BY_ID[preset_id]
    except KeyError:
        raise ValueError(f"Unknown preset '{preset_id}'. Available: {', '.join(_BY_ID)}") from None
