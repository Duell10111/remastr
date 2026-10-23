# Remastr – notes for AI assistants

- Backend: Python 3.13, uv, FastAPI, MCP Python SDK **2.x** (`mcp.server.mcpserver.MCPServer`, not v1 `FastMCP`).
  Run from `backend/`: `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format src tests`.
- Frontend: React 19 + Vite + TypeScript (`erasableSyntaxOnly`: no enums/parameter properties). `npm run build`,
  `npm run lint` (oxlint).
- `service.Remastr` is the single application API. REST (`api.py`) and MCP (`mcp_server.py`) must stay thin
  wrappers around it; add features there first so UI and MCP stay in sync.
- Long-running work is a job (`jobs.py`). Handlers must honour `ctx.cancel` and report `ctx.progress`.
- The GPU pipeline only runs on the Windows PC (StaxRip tools, vs-mlrt/TensorRT, NVEncC). Tests replace Plex/FTP
  with fakes (`tests/conftest.py`) and only check command construction for the pipeline.
- Never let anything delete originals on the Plex server: "replace" moves them to `ftp_archive_root` and needs
  explicit confirmation (API `confirm=true`).
- UI text is German; code, comments and identifiers are English.
