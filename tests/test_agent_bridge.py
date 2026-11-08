"""H2: PETIT Tools over MCP keep the same catalog, risk, approval and receipt boundary."""
import io
import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import agent_bridge, conversation_store as store, db, petit_mcp


def running_turn(request_id="r-bridge", *, is_admin=True):
    store.create_thread("t-" + request_id)
    store.accept("t-" + request_id, request_id, {"message": "m", "is_admin": is_admin})
    assert store.claim(request_id)
    return request_id


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(agent_bridge.router)
    return TestClient(app)


def bridge_for(api, token):
    def forward(request):
        response = api.request(request.method, request.url.path, content=request.content,
                               headers={"Authorization": request.headers.get("authorization", ""),
                                        "Content-Type": "application/json"})
        return httpx.Response(response.status_code, content=response.content, headers={"Content-Type": "application/json"})
    return petit_mcp.Bridge("http://core", token, transport=httpx.MockTransport(forward))


def rpc(bridge, *messages):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    petit_mcp.serve(stdin, stdout, bridge)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_mcp_initialize_list_and_read_call(api):
    bridge = bridge_for(api, agent_bridge.issue(running_turn()))
    init, listed, called = rpc(bridge,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["capabilities"]["tools"] is not None
    names = {t["name"]: t for t in listed["result"]["tools"]}
    assert "get_current_time" in names and names["get_current_time"]["annotations"]["readOnlyHint"] is True
    assert "update_persona_file" in names and names["update_persona_file"]["annotations"]["readOnlyHint"] is False
    assert called["result"]["isError"] is False and called["result"]["content"][0]["type"] == "text"


def test_confirm_write_becomes_pending_approval_not_execution(api):
    request_id = running_turn()
    bridge = bridge_for(api, agent_bridge.issue(request_id))
    from backend import petit_home
    before = (petit_home.ensure() / "SOUL.md").read_text(encoding="utf-8")
    (reply,) = rpc(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "update_persona_file", "arguments": {"file": "SOUL.md", "content": "# SOUL\n静か", "reason": "r"}}})
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert payload["status"] == "awaiting_user_approval"
    pending = store.approvals(request_id)
    assert [p["approval_id"] for p in pending] == [payload["approval_id"]] and "+静か" in pending[0]["preview"]
    assert (petit_home.root() / "SOUL.md").read_text(encoding="utf-8") == before


def test_low_risk_write_records_effect_receipt(api):
    request_id = running_turn()
    bridge = bridge_for(api, agent_bridge.issue(request_id))
    (reply,) = rpc(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "save_memory", "arguments": {"content": "架空の合言葉はORBIT"}}})
    assert reply["result"]["isError"] is False, reply
    with db.get_connection() as connection:
        rows = connection.execute("SELECT tool,status FROM effect_receipts WHERE request_id=?", (request_id,)).fetchall()
    assert [(r["tool"], r["status"]) for r in rows] == [("save_memory", "applied")]


def test_unknown_and_invalid_calls_are_tool_errors(api):
    bridge = bridge_for(api, agent_bridge.issue(running_turn()))
    unknown, invalid, bad_args = rpc(bridge,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "dispatch_shell", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "save_memory", "arguments": {"nope": 1}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "save_memory", "arguments": "x"}})
    assert unknown["result"]["isError"] and "tool_not_public_or_unavailable" in unknown["result"]["content"][0]["text"]
    assert invalid["result"]["isError"]
    assert bad_args["error"]["code"] == -32602


def test_token_scope(api):
    bad = bridge_for(api, "not-a-token")
    (reply,) = rpc(bad, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert reply["error"]["code"] == -32603
    guest = bridge_for(api, agent_bridge.issue(running_turn("r-guest", is_admin=False)))
    (reply,) = rpc(guest, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "Tool" in reply["error"]["message"]
    token = agent_bridge.issue(running_turn("r-done"))
    with db.get_connection() as connection:
        connection.execute("UPDATE turns SET status='completed' WHERE request_id='r-done'")
    assert api.post("/api/agent-bridge/tools/list", headers={"Authorization": "Bearer " + token}).status_code == 409
    agent_bridge.revoke(token)
    assert api.post("/api/agent-bridge/tools/list", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_call_budget(api, monkeypatch):
    monkeypatch.setattr(agent_bridge, "MAX_CALLS", 1)
    token = agent_bridge.issue(running_turn())
    headers = {"Authorization": "Bearer " + token}
    body = {"name": "get_current_time", "arguments": {}}
    assert api.post("/api/agent-bridge/tools/call", json=body, headers=headers).status_code == 200
    assert api.post("/api/agent-bridge/tools/call", json=body, headers=headers).status_code == 429


def test_protocol_errors():
    bridge = petit_mcp.Bridge("http://unused", "t", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    stdin = io.StringIO("not json\n[]\n" + json.dumps({"jsonrpc": "2.0", "id": 5, "method": "nope"}) + "\n")
    stdout = io.StringIO()
    petit_mcp.serve(stdin, stdout, bridge)
    codes = [json.loads(line)["error"]["code"] for line in stdout.getvalue().splitlines()]
    assert codes == [-32700, -32600, -32601]


def test_full_app_lets_token_endpoints_through_admin_middleware_only_with_token(monkeypatch):
    # Regression: the admin-cookie middleware used to reject the bridge and the Discord relay.
    from backend import app as app_module, setup_store
    monkeypatch.setattr(setup_store, "initialized", lambda: True)
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", "d" * 40)
    client = TestClient(app_module.create_app())
    token = agent_bridge.issue(running_turn())
    ok = client.post("/api/agent-bridge/tools/list", headers={"Authorization": "Bearer " + token})
    assert ok.status_code == 200 and ok.json()["tools"]
    assert client.post("/api/agent-bridge/tools/list").status_code == 401
    assert client.get("/api/channels/discord/notifications", headers={"Authorization": "Bearer " + "d" * 40}).status_code == 200
    assert client.get("/api/channels/discord/notifications").status_code == 401
    # Everything else still needs the admin cookie.
    assert client.get("/api/threads").status_code == 401
    assert client.get("/api/agent-bridgeX").status_code == 401
