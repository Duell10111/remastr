"""Convert official Real-ESRGAN weights to ONNX for vs-mlrt (input "input", NCHW float RGB 0..1, dynamic H/W).

Architectures follow xinntao/Real-ESRGAN (SRVGGNetCompact) and BasicSR (RRDBNet); load_state_dict(strict=True)
verifies that they match the checkpoints exactly. Weights are loaded with weights_only=True (no pickle code).

Usage (needs the three .pth files from https://github.com/xinntao/Real-ESRGAN/releases:
v0.2.5.0/realesr-general-x4v3.pth, v0.2.5.0/realesr-general-wdn-x4v3.pth, v0.1.0/RealESRGAN_x4plus.pth):

    uv run --no-project --with torch --with onnx --with onnxruntime --with numpy \
        python tools/convert_realesrgan.py <dir with .pth files> <vs-mlrt>/models/remastr
"""

import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from torch import nn


class SRVGGNetCompact(nn.Module):
    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4):
        super().__init__()
        self.upscale = upscale
        self.body = nn.ModuleList([nn.Conv2d(num_in_ch, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)])
        for _ in range(num_conv):
            self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            self.body.append(nn.PReLU(num_parameters=num_feat))
        self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        return self.upsampler(out) + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


class ResidualDenseBlock(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(nf, gc)
        self.rdb2 = ResidualDenseBlock(nf, gc)
        self.rdb3 = ResidualDenseBlock(nf, gc)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, nf=64, nb=23, gc=32):
        super().__init__()
        self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
        self.conv_body = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_hr = nn.Conv2d(nf, nf, 3, 1, 1)
        self.conv_last = nn.Conv2d(nf, 3, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        feat = self.conv_first(x)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def load(path: Path) -> dict:
    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    for key in ("params_ema", "params"):
        if key in ckpt:
            return ckpt[key]
    return ckpt


def export(model: nn.Module, out: Path) -> None:
    model.eval()
    dummy = torch.rand(1, 3, 64, 80)
    kwargs = dict(
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        dynamic_axes={"input": {2: "h", 3: "w"}, "output": {2: "h4", 3: "w4"}},
    )
    try:
        torch.onnx.export(model, dummy, str(out), dynamo=False, **kwargs)
    except TypeError:  # older torch without the dynamo flag
        torch.onnx.export(model, dummy, str(out), **kwargs)
    # verify against PyTorch on a different (non-square) size, which also proves the dynamic shape
    x = torch.rand(1, 3, 48, 72)
    with torch.no_grad():
        ref = model(x).numpy()
    got = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"]).run(None, {"input": x.numpy()})[0]
    print(
        f"  {out.name}: output {got.shape}, max abs diff vs torch {np.abs(ref - got).max():.2e}, "
        f"{out.stat().st_size / 1e6:.1f} MB"
    )


src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
print("torch", torch.__version__, "| onnxruntime", ort.__version__)

general = load(src / "realesr-general-x4v3.pth")
wdn = load(src / "realesr-general-wdn-x4v3.pth")
for strength, name in ((1.0, "realesr-general-x4v3.onnx"), (0.5, "realesr-general-x4v3-dn50.onnx")):
    # Real-ESRGAN's "denoise strength": weight interpolation between the plain and the denoising model
    blended = {k: strength * general[k] + (1 - strength) * wdn[k] for k in general}
    net = SRVGGNetCompact()
    net.load_state_dict(blended, strict=True)
    export(net, dst / name)

net = RRDBNet()
net.load_state_dict(load(src / "RealESRGAN_x4plus.pth"), strict=True)
export(net, dst / "RealESRGAN_x4plus.onnx")
