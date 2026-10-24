import json

from fastapi.testclient import TestClient

from remastr.main import create_app
from remastr.mcp_server import build_mcp

TOKEN = "secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client(settings, svc):
    settings.api_token = TOKEN
    return TestClient(create_app(settings, svc), base_url="http://127.0.0.1:8765")


def test_api_requires_token(settings, svc):
    with client(settings, svc) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/presets").status_code == 401
        assert c.get("/api/presets", headers={"Authorization": "Bearer wrong"}).status_code == 401
        presets = c.get("/api/presets", headers=AUTH).json()
        assert presets[0]["id"] == "dpir_vsr"
        assert c.get(f"/api/presets?token={TOKEN}").status_code == 200


def test_search_and_item(settings, svc):
    with client(settings, svc) as c:
        assert c.get("/api/search?q=micky", headers=AUTH).json()[0]["rating_key"] == "42"
        detail = c.get("/api/items/42", headers=AUTH).json()
        assert detail["item"]["show"] == "Mickys Clubhaus"
        assert detail["local"]["source"] is None


def test_replace_without_confirm_is_400(settings, svc):
    with client(settings, svc) as c:
        r = c.post("/api/items/42/upload", json={"mode": "replace"}, headers=AUTH)
        assert r.status_code == 400


async def test_mcp_tools_registered(svc):
    tools = {t.name for t in await build_mcp(svc).list_tools()}
    assert {"search_media", "create_previews", "process_item", "upload_result", "batch_process"} <= tools


def test_mcp_over_http(settings, svc):
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    headers = {**AUTH, "Accept": "application/json, text/event-stream"}
    with client(settings, svc) as c:
        assert c.post("/mcp", json=init, headers={"Accept": headers["Accept"]}).status_code == 401
        r = c.post("/mcp", json=init, headers=headers)
        assert r.status_code == 200, r.text
        body = r.text
        payload = json.loads(body.split("data:", 1)[1].strip().splitlines()[0]) if "data:" in body else r.json()
        assert payload["result"]["serverInfo"]["name"] == "remastr"
