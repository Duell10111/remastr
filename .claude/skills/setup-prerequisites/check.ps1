# Checks remastr's processing prerequisites. Prints OK/FEHLT per item with the SKILL.md step number.
# Reads only non-secret path settings from backend/.env.
$ErrorActionPreference = 'Continue'
# Tools installed by winget/fnm in this session are only on the user PATH, not yet in this shell's
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + $env:Path
if ((Get-Command fnm -ErrorAction SilentlyContinue) -and -not (Get-Command node -ErrorAction SilentlyContinue)) {
    fnm env --shell powershell | Out-String | Invoke-Expression
    fnm use lts-latest 2>$null | Out-Null
}
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$envFile = Join-Path $repo 'backend\.env'

function Get-Setting($key, $default) {
    if (Test-Path $envFile) {
        $m = Select-String -Path $envFile -Pattern "^\s*REMASTR_$key\s*=\s*(.*)$" | Select-Object -First 1
        if ($m) {
            $v = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
            if ($v) { return $v }
        }
    }
    return $default
}

$staxrip = Get-Setting 'STAXRIP_DIR' 'F:\Tools\StaxRip\StaxRip-v2.52.6-x64'
$vsmlrt = Get-Setting 'VSMLRT_DIR' 'F:\Tools\vs-mlrt'
$work = Get-Setting 'WORK_DIR' 'F:\Remastr'
$ffprobe = Get-Setting 'FFPROBE' 'ffprobe'
$missing = 0

function Check($step, $label, [bool]$ok, $hint = '') {
    if ($ok) { Write-Host ("OK     [{0}] {1}" -f $step, $label) -ForegroundColor Green }
    else {
        $script:missing++
        Write-Host ("FEHLT  [{0}] {1}{2}" -f $step, $label, $(if ($hint) { "  -> $hint" } else { '' })) -ForegroundColor Red
    }
}
function Has-Command($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "StaxRip: $staxrip`nvs-mlrt: $vsmlrt`nWork dir: $work`n"

$gpu = if (Has-Command 'nvidia-smi') { (& nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>$null) -join ', ' } else { '' }
Check 1 "NVIDIA GPU/Treiber $gpu" ([bool]$gpu)

Check 2 'StaxRip vspipe.exe' (Test-Path "$staxrip\Apps\FrameServer\VapourSynth\Lib\site-packages\vapoursynth\vspipe.exe")
Check 2 'StaxRip NVEncC64.exe' (Test-Path "$staxrip\Apps\Encoders\NVEncC\NVEncC64.exe")
Check 2 'StaxRip mkvmerge.exe' (Test-Path "$staxrip\Apps\Support\MKVToolNix\mkvmerge.exe")
Check 2 'StaxRip 7za.exe (zum Entpacken)' (Test-Path "$staxrip\Apps\Support\7zip\7za.exe")

Check 3 'vs-mlrt vsmlrt.py' (Test-Path "$vsmlrt\vsmlrt.py")
Check 3 'vs-mlrt vstrt.dll (TensorRT)' (Test-Path "$vsmlrt\vstrt.dll")
Check 3 'akarin.dll' (Test-Path "$vsmlrt\akarin\akarin.dll")
foreach ($d in 'RealESRGANv2', 'cugan', 'dpir') {
    Check 3 "Modelle models\$d" ([bool](Get-ChildItem "$vsmlrt\models\$d" -Filter *.onnx -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1))
}

Check 4 'SCUNet (scunet_vsr)' (Test-Path "$vsmlrt\models\scunet\scunet_color_real_psnr.onnx")
Check 4 'SwinIR (swinir_real)' ([bool](Get-ChildItem "$vsmlrt\models\swinir" -Filter '*realSR_BSRGAN_DFO*x2_GAN*.onnx' -ErrorAction SilentlyContinue | Select-Object -First 1))
Check 4 'waifu2x swin_unet photo (waifu2x_photo)' (Test-Path "$vsmlrt\models\waifu2x\swin_unet_photo_v2")

foreach ($f in 'realesr-general-x4v3.onnx', 'realesr-general-x4v3-dn50.onnx', 'RealESRGAN_x4plus.onnx') {
    Check 5 "Real-ESRGAN $f" (Test-Path "$vsmlrt\models\remastr\$f") 'tools/convert_realesrgan.py'
}

Check 6 "ffprobe ($ffprobe)" ((Has-Command $ffprobe) -or (Test-Path $ffprobe))
Check 6 'uv' (Has-Command 'uv') 'PATH neu laden oder winget install astral-sh.uv'
Check 6 'Node.js' (Has-Command 'node') 'fnm use lts-latest'
Check 6 'Backend-Abhängigkeiten (backend\.venv)' (Test-Path "$repo\backend\.venv")
Check 6 'Frontend gebaut (frontend\dist)' (Test-Path "$repo\frontend\dist\index.html")

Check 7 'backend\.env vorhanden' (Test-Path $envFile) 'Copy-Item backend/.env.example backend/.env'
foreach ($k in 'PLEX_URL', 'PLEX_TOKEN', 'FTP_HOST', 'FTP_USER', 'FTP_PASSWORD', 'PATH_MAPPINGS') {
    Check 7 "REMASTR_$k gesetzt" ([bool](Get-Setting $k ''))  # value itself is never printed
}
Check 7 "Arbeitsordner $work" (Test-Path $work)

Write-Host ''
if ($missing) { Write-Host "$missing Punkt(e) fehlen." -ForegroundColor Yellow; exit 1 }
Write-Host 'Alles vorhanden.' -ForegroundColor Green
