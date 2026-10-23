# remastr backend

FastAPI + MCP server, job queue and the video pipeline. See the [project README](../README.md).

```sh
uv sync
uv run remastr          # start server (reads .env)
uv run pytest           # tests
uv run ruff check src tests && uv run ruff format src tests
```
