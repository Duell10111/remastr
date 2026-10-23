# Remastr

KI-Upscaling für Plex-Aufnahmen: Originale per FTP holen, Varianten an Testabschnitten vergleichen,
im Batch verbessern und als zusätzliche Version zurück nach Plex hochladen (oder das Original ersetzen).
Steuerbar über eine Weboberfläche und per **MCP** (z. B. aus Claude).

```
Mac / Browser / Claude (MCP)  ──HTTP──▶  Windows-PC: remastr (FastAPI + MCP + Job-Queue + GPU-Pipeline)
                                               │ FTP(S)            │ Plex-API
                                               ▼                   ▼
                                           Plex-Server: Dateien + Metadaten
```

## Pipeline

Pro Datei: Analyse (ffprobe + Interlacing-Erkennung am Bildinhalt) → VapourSynth (QTGMC-Deinterlacing,
KI-Modell via vs-mlrt/TensorRT) → NVEncC (Filter, Skalierung, HEVC/AV1 in Hardware) → mkvmerge (Ton und
Untertitel aus dem Original, A/V-Versatz ausgeglichen). SD wird auf 1080p hochskaliert, HD nur deinterlaced.

| Preset | Beschreibung |
|---|---|
| `esrgan` | Real-ESRGAN animevideov3: sauber, nah am Original (Standard) |
| `cugan` | Real-CUGAN pro: am schärfsten, kräftige Konturen |
| `dpir_vsr` | DPIR-Deblocking + NVIDIA RTX Video Super Resolution |
| `mild_vsr` | Deblock/Deband + RTX VSR, sehr schnell |
| `lanczos` | ohne KI, Referenz zum Vergleichen |

## Voraussetzungen (Verarbeitungs-PC)

- Windows, NVIDIA RTX-GPU mit aktuellem Treiber
- [StaxRip](https://github.com/staxrip/staxrip) (portable; bringt VapourSynth, QTGMC, NVEncC, mkvmerge mit)
- [vs-mlrt](https://github.com/AmusementClub/vs-mlrt) (TensorRT-Paket) + `akarin`-Plugin in `<vs-mlrt>/akarin/`
- ffmpeg/ffprobe im `PATH`
- [uv](https://docs.astral.sh/uv/) und Node.js (LTS)

## Einrichten

```sh
cd backend
cp .env.example .env      # Plex, FTP, Pfad-Zuordnung, Tool-Pfade eintragen
uv sync
cd ../frontend
npm install
npm run build             # das Backend liefert frontend/dist unter / aus
cd ../backend
uv run remastr            # http://127.0.0.1:8765
```

### Zugriff vom Mac / aus dem Netzwerk

In `backend/.env`: `REMASTR_HOST=0.0.0.0`, einen langen zufälligen `REMASTR_API_TOKEN` setzen und den
Rechnernamen in `REMASTR_ALLOWED_HOSTS` ergänzen (z. B. `["my-pc:*","192.168.1.20:*"]`). Ggf. Port 8765 in
der Windows-Firewall freigeben.

### Entwickeln auf dem Mac

Backend läuft auf dem PC, die Oberfläche lokal mit Hot Reload:

```sh
cd frontend
echo "REMASTR_BACKEND=http://my-pc:8765" > .env.local
npm run dev
```

Python-Code ohne GPU entwickeln/testen: `uv run pytest` läuft auch auf macOS (Plex/FTP/GPU sind in den
Tests ersetzt).

## MCP

Endpoint: `http://<pc>:8765/mcp` (Streamable HTTP, Bearer-Token). Beispiel Claude Code:

```sh
claude mcp add --transport http remastr http://my-pc:8765/mcp --header "Authorization: Bearer <token>"
```

Tools: `search_media`, `get_item`, `list_presets`, `download_item`, `create_previews`, `process_item`,
`upload_result`, `batch_process`, `list_jobs`, `get_job`, `cancel_job`. Ersetzen von Originalen
(`mode="replace"`) erfordert `confirm=true`.

## Upload-Modi

- **version** (Standard): Datei landet neben dem Original als `<Name> - Remastr 1080p.mkv`; Plex fasst beide
  als Versionen desselben Titels zusammen.
- **replace**: Upload unter temporärem Namen → Original wird nach `REMASTR_FTP_ARCHIVE_ROOT` verschoben →
  neue Datei wird an Ort und Stelle umbenannt → Plex-Teilscan.

## Projektstruktur

```
backend/src/remastr/
  config.py       Einstellungen (.env)
  service.py      zentrale Service-Schicht (von REST und MCP genutzt)
  api.py          REST-API für die Oberfläche
  mcp_server.py   MCP-Tools
  jobs.py         SQLite-Job-Queue, Lanes "transfer" und "gpu"
  pipeline.py     Analyse, vspipe | NVEncC, mkvmerge
  presets.py      Varianten
  plex.py, ftp.py, workspace.py
  vapoursynth/remastr.vpy
frontend/src/     React + Vite + TypeScript (Vergleichsansicht: components/Compare.tsx)
```
