---
name: setup-prerequisites
description: Install and verify everything remastr needs on the Windows processing PC — StaxRip (VapourSynth, QTGMC, NVEncC, mkvmerge), vs-mlrt with TensorRT, the akarin plugin, all AI models (vs-mlrt models, external SCUNet/SwinIR/waifu2x, converted Real-ESRGAN ONNX), ffmpeg, uv, Node.js and backend/.env. Use when the user sets up remastr on a new machine, asks what is missing, or a preset fails because a tool or model file is not found.
---

# remastr prerequisites

Goal: a Windows PC with an NVIDIA RTX GPU on which every preset in `backend/src/remastr/presets.py` runs.
Work through the steps in order, but **run the check script first** and only do the steps it reports as missing.
Talk to the user in German (UI language of the project).

```powershell
powershell -ExecutionPolicy Bypass -File .claude/skills/setup-prerequisites/check.ps1
```

The script reads `REMASTR_STAXRIP_DIR`, `REMASTR_VSMLRT_DIR` and `REMASTR_WORK_DIR` from `backend/.env` (falling
back to the defaults in `config.py`) and prints one line per requirement with `OK` / `FEHLT` and the step number
below. It never prints secrets. Re-run it after each step.

## Ground rules

- Ask the user for the install location before downloading (defaults: `F:\Tools\...`, work dir `F:\Remastr`).
  Several GB are downloaded; tell them the sizes up front.
- Downloads go to a separate folder (e.g. `F:\Tools\_downloads\<name>\`), never into the repo. Download with
  `curl.exe -L --fail -o <file> <url>`.
- Pin exactly the versions below. They are the ones remastr was tested with (`vsmlrt.py` must match the model
  folder layout and the TensorRT DLLs).
- Archives are 7z. StaxRip ships 7-Zip: `<staxrip>\Apps\Support\7zip\7za.exe` (install StaxRip first).
- `backend/.env` holds secrets (Plex token, FTP password). Never print it; edit single keys only and mask values
  in any output.
- Only remastr's own processing PC needs steps 1–5. A Mac used for development only needs step 6.

## 1. NVIDIA driver

`nvidia-smi` must work and show an RTX GPU. RTX Video Super Resolution (presets `*_vsr`) needs a current
Game Ready/Studio driver (≥ 550). If missing: user installs it from nvidia.com — don't automate this.

## 2. StaxRip (VapourSynth R7x, QTGMC/havsfunc, NVEncC, mkvmerge, 7-Zip)

- https://github.com/staxrip/staxrip/releases/download/v2.52.6/StaxRip-v2.52.6-x64.7z (portable, ~1 GB)
- Extract so that `<dir>\StaxRip-v2.52.6-x64\StaxRip.exe` exists (7-Zip needed once for this — use an installed
  7-Zip, or `tar -xf` does **not** work for 7z; ask the user to extract it with Explorer/7-Zip if none exists).
- remastr uses from it: `Apps\FrameServer\VapourSynth\...\vspipe.exe`, `Apps\Encoders\NVEncC\NVEncC64.exe`,
  `Apps\Support\MKVToolNix\mkvmerge.exe`, `Apps\Plugins\` (QTGMC dependencies, LSMASH).
- Set `REMASTR_STAXRIP_DIR` in `backend/.env` to the `StaxRip-v2.52.6-x64` folder.

## 3. vs-mlrt v15.16 (TensorRT) + akarin

Into one folder `<vs-mlrt>` (default `F:\Tools\vs-mlrt`), `$z = '<staxrip>\Apps\Support\7zip\7za.exe'`:

| Download (all `https://github.com/...`) | Size | Extract |
|---|---|---|
| `AmusementClub/vs-mlrt/releases/download/v15.16/vsmlrt-windows-x64-tensorrt.v15.16.7z.001` and `.002` | ~3 GB | `& $z x <...7z.001> -o<vs-mlrt>` (both parts in the same folder) → `vsmlrt.py`, `vstrt.dll`, `vsmlrt-cuda\` |
| `AmusementClub/vs-mlrt/releases/download/v15.16/models.v15.16.7z` | ~0.9 GB | `& $z x <file> -o<vs-mlrt>` → `models\RealESRGANv2`, `cugan`, `dpir`, ... |
| `AkarinVS/vapoursynth-plugin/releases/download/v0.95/akarin-release-lexpr-amd64-v0.95.7z` | small | `& $z e <file> -o<vs-mlrt>\akarin -r '*.dll'` → `akarin\akarin.dll` |

Set `REMASTR_VSMLRT_DIR` in `backend/.env`.

## 4. External models (SCUNet, SwinIR, waifu2x photo)

From `https://github.com/AmusementClub/vs-mlrt/releases/download/external-models/`:
`scunet_v2.7z` (~0.5 GB, default-preset alternative `scunet_vsr`), `swinir_v1.7z` (~1.2 GB, `swinir_real`),
`waifu2x_swin_unet_v5.7z` (~0.45 GB, `waifu2x_photo`).

Extract each **into `<vs-mlrt>\models`** (the archives contain `scunet\`, `swinir\`, `waifu2x\` at top level):
`& $z x <file> -o<vs-mlrt>\models -y`. If the user wants to save space, these are optional — only the matching
preset fails without them.

## 5. Real-ESRGAN ONNX (default preset `realesr_general`, plus `realesr_general_dn`, `realesrgan_x4plus`)

1. Download the official weights to e.g. `F:\Tools\_downloads\realesrgan\`:
   - `https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth`
   - `https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-wdn-x4v3.pth`
   - `https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth`
2. Convert (CPU is enough; uv fetches a throwaway torch env, ~1 GB, nothing is added to the project). From
   `backend/`:
   ```powershell
   uv run --no-project --with torch --with onnx --with onnxruntime --with numpy `
       python tools/convert_realesrgan.py F:\Tools\_downloads\realesrgan <vs-mlrt>\models\remastr
   ```
3. Expect three lines with `max abs diff vs torch` around `1e-6`; anything above `1e-3` means a broken export —
   stop and investigate instead of continuing. Result: `realesr-general-x4v3.onnx`,
   `realesr-general-x4v3-dn50.onnx`, `RealESRGAN_x4plus.onnx` in `<vs-mlrt>\models\remastr\`.

### 5b. Real-HAT GAN (optional, preview-only presets `real_hat`, `real_hat_sharper`)

The weights are only on the official HAT Google Drive folder (`1HpmReFfoUqUbnAOQ7rvOeNU3uf_m69w0`, linked from
https://github.com/XPixelGroup/HAT). Download the two files with gdown (~170 MB each):

```powershell
uv run --no-project --with gdown gdown 1Ma12vCWT27P9M99-s2RXnynKN-OQsBrv -O F:\Tools\_downloads\hat\Real_HAT_GAN_SRx4.pth
uv run --no-project --with gdown gdown 1EioFq5-mKmv1uqta_Byd9cgXp9SU3zjj -O F:\Tools\_downloads\hat\Real_HAT_GAN_sharper.pth
```

SHA-256 of `Real_HAT_GAN_SRx4.pth`: `F5B1E3BBBB05147CA2BEEFCC715279CB647D7976CBDA67D62EA7E6E20D5FFCC7`, of
`Real_HAT_GAN_sharper.pth`: `5800B67136006EB8CAB3B4ED7C8D73B6A195BB18E6CC709B674F9AA069C00271`. Then, from
`backend/`, for each file:

```powershell
uv run --no-project --with spandrel --with torch --with onnx --with onnxruntime --with numpy `
    python tools/convert_model.py F:\Tools\_downloads\hat\<name>.pth <vs-mlrt>\models\remastr\<name>.onnx
```

Own models (e.g. from OpenModelDB) are converted the same way and added via `<work_dir>\presets.json`, see README
"Eigene Modelle". Window-attention models (HAT, SwinIR, DAT) need `"onnx_multiple"` = their window size there.

## 6. ffmpeg, uv, Node.js

- `ffmpeg`/`ffprobe` on `PATH` (e.g. `winget install Gyan.FFmpeg`), or set `REMASTR_FFMPEG`/`REMASTR_FFPROBE`
  to full paths.
- uv: `winget install astral-sh.uv` (macOS: `brew install uv`). Afterwards in an open PowerShell:
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:Path`.
- Node.js LTS (e.g. `winget install Schniz.fnm`, then `fnm install --lts`; macOS: `brew install node`).
- Then `cd backend; uv sync` and `cd frontend; npm install; npm run build`.

## 7. backend/.env

`Copy-Item backend/.env.example backend/.env` if it does not exist, then let the **user** fill in Plex URL/token,
FTP host/user/password and `REMASTR_PATH_MAPPINGS` (don't ask them to paste secrets into the chat). Notes:
SFTPGo's FTP usually listens on 2121; a mkcert/private CA goes into `REMASTR_CA_BUNDLE` (find it with
`mkcert -CAROOT`). Create `REMASTR_WORK_DIR` on a disk with plenty of free space (~2–5 GB per SD episode during
processing).

## 8. Smoke test

1. `cd backend; uv run pytest -q` — must pass (no GPU needed).
2. Start `uv run remastr`, open http://127.0.0.1:8765, search a short SD item, create previews with
   `lanczos,realesr_general,scunet_vsr`.
3. The **first** run per model and resolution builds a TensorRT engine (1–5 min each, cached as `*.engine` next to
   the ONNX file). Tell the user this is expected, not a hang. Later runs start in seconds.
4. Failures and their usual cause: `No such file ... .onnx` → step 4/5; `akarin` / `Expr` errors → step 3;
   all-green or black output → driver/TensorRT mismatch (re-check step 1 and the vs-mlrt version).
