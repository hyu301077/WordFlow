import sys
import time

import pytest

from wordflow import page_transport
from wordflow.page_transport import PageTransport, PageTransportError


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    """用真正的 stdio 子进程覆盖分包、通知和关闭路径。"""
    script = tmp_path / "stub_server.py"
    script.write_text("""
import json
import sys
import time

for line in sys.stdin:
    req = json.loads(line)
    method = req.get("method")
    if method == "initialized":
        continue
    assert method in {"initialize", "thread/start", "mcpServer/tool/call"}
    if method == "initialize":
        value = {}
    elif method == "thread/start":
        assert req["params"]["sandbox"] == "read-only"
        assert req["params"]["ephemeral"]
        value = {"thread": {"id": "test-thread"}}
    else:
        p = req["params"]
        assert p["threadId"] == "test-thread" and p["server"] == "codex_apps"
        op = p["arguments"]["test"]
        if op == "hang":
            time.sleep(15)
        if op == "approval":
            print(json.dumps({"id": 42, "method": "tool/requestUserInput", "params": {}}), flush=True)
            denial = json.loads(sys.stdin.readline())
            assert denial["id"] == 42 and "error" in denial
            break
        if op == "end":
            break
        value = {"structuredContent": {"tool": p["tool"]}}
        if op == "error":
            value = {"isError": True, "content": [{"type": "text", "text": "sensitive detail"}]}
        if op == "conflict":
            value = {"isError": True, "structuredContent": {"error": {"code": "edit_conflict"}}}
    print(json.dumps({"method": "irrelevant/notification"}))
    print(json.dumps({"id": req["id"], "result": value}), flush=True)
""", encoding="utf-8")
    monkeypatch.setattr(page_transport, "_codex_command", lambda: [sys.executable, "-B", "-u", str(script)])


def test_page_rpc_auth_scope_and_errors(app_server):
    with PageTransport() as service:
        for tool in ("chatgpt_space.read_page", "chatgpt_space.edit_page"):
            assert service.call(tool, {"test": "ok"}) == {"tool": tool}
        with pytest.raises(PageTransportError, match="仅支持"):
            service.call("chatgpt_space.trash_page", {})
        assert service.call("chatgpt_space.edit_page", {"test": "conflict"}) == {"error": {"code": "edit_conflict"}}
        with pytest.raises(PageTransportError, match="访问权限") as caught:
            service.call("chatgpt_space.read_page", {"test": "error"})
        assert "sensitive detail" not in str(caught.value)


@pytest.mark.parametrize(("op", "message"), [("approval", "额外授权"), ("end", "断开"), ("hang", "超时")])
def test_rpc_interruption_closes_process(app_server, op, message):
    with pytest.raises(PageTransportError, match=message):
        with PageTransport() as service:
            proc = service._proc
            service.timeout = 0.15
            service.call("chatgpt_space.read_page", {"test": op})
    assert proc.poll() is not None


def test_cancel_pending_rpc(app_server):
    with pytest.raises(PageTransportError, match="已取消"):
        with PageTransport() as service:
            proc = service._proc
            stop = time.monotonic() + 0.1
            service.cancelled = lambda: time.monotonic() >= stop
            service.call("chatgpt_space.read_page", {"test": "hang"})
    assert proc.poll() is not None
