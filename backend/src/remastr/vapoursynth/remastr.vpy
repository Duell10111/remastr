# VapourSynth pipeline used by remastr.pipeline (run through vspipe).
# Args (vspipe -a): src, cache, plugins (StaxRip Apps/Plugins), mlrt (vs-mlrt dir),
#                   deint (none|tff|bff), mode (esrgan|cugan|swinir|waifu2x|onnx|dpir|scunet|passthrough),
#                   outw, outh, matrix_in, fp16 (1|0), streams (TensorRT streams),
#                   onnx, multiple (model path and required size multiple, mode "onnx" only)
import sys

import vapoursynth as vs

core = vs.core

PLUGINS = globals()["plugins"]
MLRT = globals()["mlrt"]


def load(path):
    try:
        core.std.LoadPlugin(path)
    except vs.Error as e:
        if "already loaded" not in str(e):
            raise


load(PLUGINS + r"\Dual\L-Smash-Works\LSMASHSource.dll")

src = globals()["src"]
cache = globals().get("cache")
deint = globals().get("deint", "none")
mode = globals().get("mode", "esrgan")
outw = int(globals()["outw"])
outh = int(globals()["outh"])
matrix_in = globals().get("matrix_in", "170m")

clip = core.lsmas.LWLibavSource(src, cachefile=cache)

if deint in ("tff", "bff"):
    # QTGMC double-rate deinterlacing (25i -> 50p) with StaxRip's plugin set
    for dll in (r"\VS\mvtools\libmvtools.dll", r"\VS\nnedi3\libnnedi3.dll", r"\VS\nnedi3\vsznedi3.dll",
                r"\VS\RemoveGrainVS\RemoveGrainVS.dll", r"\Dual\fmtconv\fmtconv.dll",
                r"\VS\MiscFilters\MiscFilters.dll", r"\VS\EEDI3m\EEDI3.dll", r"\VS\EEDI3m\EEDI3m.dll"):
        load(PLUGINS + dll)
    sys.path[0:0] = [PLUGINS + r"\VS\Scripts", PLUGINS + r"\VS\mvsfunc"]
    import havsfunc

    clip = havsfunc.QTGMC(clip, Preset="Slower", TFF=(deint == "tff"), FPSDivisor=1)

if mode != "passthrough":
    load(MLRT + r"\vstrt.dll")
    load(MLRT + r"\akarin\akarin.dll")
    sys.path.insert(0, MLRT)
    import vsmlrt

    # Presets switch fp16 off for models that overflow in half precision (e.g. SwinIR: all-zero output)
    backend = vsmlrt.Backend.TRT(
        fp16=globals().get("fp16", "1") == "1", num_streams=int(globals().get("streams", "2"))
    )
    rgb = core.resize.Bicubic(clip, format=vs.RGBH, matrix_in_s=matrix_in)

if mode == "esrgan":
    rgb = vsmlrt.RealESRGAN(rgb, model=vsmlrt.RealESRGANv2Model.animevideov3, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "cugan":
    scale = 2 if clip.height * 2 >= outh else 3
    rgb = vsmlrt.CUGAN(rgb, noise=-1, scale=scale, version=2, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "swinir":
    # Real-world SR trained on realistic degradations (BSRGAN), GAN variant: most texture, slowest
    rgb = vsmlrt.SwinIR(rgb, model=vsmlrt.SwinIRModel.realSR_BSRGAN_DFO_s64w8_SwinIR_M_x2_GAN, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "waifu2x":
    # The photo models are 4x only (vsmlrt would downscale other factors), so resize once to the target below
    rgb = vsmlrt.Waifu2x(rgb, noise=1, scale=4, model=vsmlrt.Waifu2xModel.swin_unet_photo_v2, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "onnx":
    # Any upscaling ONNX model (e.g. converted Real-ESRGAN); output is resized to the target.
    # Models with a size multiple (window attention, e.g. HAT) get mirror padding, cropped again afterwards.
    m = int(globals().get("multiple", "1"))
    w, h = rgb.width, rgb.height
    pad_w, pad_h = -w % m, -h % m
    if pad_w:
        rgb = core.std.StackHorizontal([rgb, core.std.FlipHorizontal(rgb.std.Crop(left=w - pad_w))])
    if pad_h:
        rgb = core.std.StackVertical([rgb, core.std.FlipVertical(rgb.std.Crop(top=h - pad_h))])
    rgb = vsmlrt.inference(rgb, network_path=globals()["onnx"], backend=backend)
    scale = rgb.width // (w + pad_w)
    rgb = rgb.std.Crop(right=pad_w * scale, bottom=pad_h * scale)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "dpir":
    # Deblocking only; NVEncC scales afterwards. Keep the source matrix.
    rgb = vsmlrt.DPIR(rgb, strength=25, model=vsmlrt.DPIRModel.drunet_deblocking_color, backend=backend)
    out = core.resize.Bicubic(rgb, format=vs.YUV420P10, matrix_s=matrix_in)
elif mode == "scunet":
    # Blind real-world restoration (noise + compression) at source resolution; NVEncC scales afterwards
    rgb = vsmlrt.SCUNet(rgb, model=vsmlrt.SCUNetModel.scunet_color_real_psnr, backend=backend)
    out = core.resize.Bicubic(rgb, format=vs.YUV420P10, matrix_s=matrix_in)
elif mode == "passthrough":
    out = core.resize.Bicubic(clip, format=vs.YUV420P10)
else:
    raise ValueError(f"unknown mode {mode}")

out.set_output()
