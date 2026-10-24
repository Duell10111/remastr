"""Convert a PyTorch super-resolution checkpoint (.pth/.safetensors) to ONNX for vs-mlrt.

The architecture is detected by spandrel (https://github.com/chaiNNer-org/spandrel), which knows most models on
OpenModelDB: HAT, SwinIR, RealPLKSR, SPAN, Compact, ESRGAN, DAT, ... Output: input "input", NCHW float RGB 0..1,
dynamic height/width. Weights are loaded with weights_only (no pickle code). The export is verified against PyTorch
with onnxruntime on a size different from the export size.

Usage:
    uv run --no-project --with spandrel --with torch --with onnx --with onnxruntime --with numpy \
        python tools/convert_model.py <model.pth> <out.onnx>

Window-attention models (HAT, SwinIR, DAT) pad to their window size inside forward(), and tracing bakes that padding
away (TracerWarning "if pad_h or pad_w"). Their ONNX model then only accepts multiples of the window size (HAT: 16):
set "onnx_multiple" in the preset accordingly and remastr mirror-pads the frame.
"""

import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import spandrel
import torch

src, out = Path(sys.argv[1]), Path(sys.argv[2])
desc = spandrel.ModelLoader().load_from_file(src)
assert isinstance(desc, spandrel.ImageModelDescriptor), "not an image-to-image model"
assert desc.input_channels == 3 and desc.output_channels == 3, "only RGB models are supported"
req = desc.size_requirements
print(f"{desc.architecture.name}, {desc.scale}x, {sum(p.numel() for p in desc.model.parameters()) / 1e6:.1f}M params")

model = desc.model.eval().float()
out.parent.mkdir(parents=True, exist_ok=True)
with torch.no_grad():
    torch.onnx.export(
        model,
        torch.rand(1, 3, 64, 64),
        str(out),
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        dynamic_axes={"input": {2: "h", 3: "w"}, "output": {2: "oh", 3: "ow"}},
        dynamo=False,
    )

# 48x80: non-square, different from the export size, and a multiple of common window sizes (8, 16)
x = torch.rand(1, 3, max(48, req.minimum), max(80, req.minimum))
with torch.no_grad():
    ref = model(x).numpy()
got = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"]).run(None, {"input": x.numpy()})[0]
diff = np.abs(ref - got).max()
print(
    f"{out.name}: {x.shape[2]}x{x.shape[3]} -> {got.shape[2]}x{got.shape[3]}, max abs diff vs torch {diff:.2e}, "
    f"{out.stat().st_size / 1e6:.1f} MB"
)
if diff > 1e-3:
    raise SystemExit("export does not match PyTorch")
