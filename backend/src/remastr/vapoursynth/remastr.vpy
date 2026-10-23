# VapourSynth pipeline used by remastr.pipeline (run through vspipe).
# Args (vspipe -a): src, cache, plugins (StaxRip Apps/Plugins), mlrt (vs-mlrt dir),
#                   deint (none|tff|bff), mode (esrgan|cugan|dpir|passthrough), outw, outh, matrix_in
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

if mode in ("esrgan", "cugan", "dpir"):
    load(MLRT + r"\vstrt.dll")
    load(MLRT + r"\akarin\akarin.dll")
    sys.path.insert(0, MLRT)
    import vsmlrt

    backend = vsmlrt.Backend.TRT(fp16=True, num_streams=2)
    rgb = core.resize.Bicubic(clip, format=vs.RGBH, matrix_in_s=matrix_in)

if mode == "esrgan":
    rgb = vsmlrt.RealESRGAN(rgb, model=vsmlrt.RealESRGANv2Model.animevideov3, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "cugan":
    scale = 2 if clip.height * 2 >= outh else 3
    rgb = vsmlrt.CUGAN(rgb, noise=-1, scale=scale, version=2, backend=backend)
    out = core.resize.Spline36(rgb, outw, outh, format=vs.YUV420P10, matrix_s="709")
elif mode == "dpir":
    # Deblocking only; NVEncC scales afterwards. Keep the source matrix.
    rgb = vsmlrt.DPIR(rgb, strength=25, model=vsmlrt.DPIRModel.drunet_deblocking_color, backend=backend)
    out = core.resize.Bicubic(rgb, format=vs.YUV420P10, matrix_s=matrix_in)
elif mode == "passthrough":
    out = core.resize.Bicubic(clip, format=vs.YUV420P10)
else:
    raise ValueError(f"unknown mode {mode}")

out.set_output()
