"""HTTP contract: /v1/check and /v1/execute only (never /v1/datapilot)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from datapilot.guard.write_gate_client import WriteGateSQLGuardClient

pytestmark = [pytest.mark.suite_p0, pytest.mark.suite_gate]

class _Handler(BaseHTTPRequestHandler):
    paths: list[str] = []

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        _Handler.paths.append(self.path)
        if self.path == "/v1/datapilot":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"gone"}')
            return
        if self.path not in ("/v1/check", "/v1/execute"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        execute = self.path == "/v1/execute" or bool(payload.get("execute"))
        resp = {
            "datapilot": "EXECUTE",
            "action": "ALLOW",
            "allowed": True,
            "reason": "ok",
            "rule_id": "select_allow",
            "risk_score": 0.1,
            "executed": execute,
            "rows": [{"ok": 1}] if execute else None,
            "rowcount": 1 if execute else None,
            "columns": ["ok"] if execute else None,
        }
        data = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def http_guard_server():
    _Handler.paths = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


def test_execute_hits_v1_execute_not_datapilot(http_guard_server: str) -> None:
    client = WriteGateSQLGuardClient(
        guard_url=http_guard_server,
        prefer_http=True,
        mode="http",
    )
    # Only HTTP: disable module + CLI
    client._block_or_execute = None

    result = client.execute("SELECT 1 AS ok")
    assert result.allowed is True
    assert result.datapilot == "EXECUTE"
    assert "/v1/execute" in _Handler.paths
    assert "/v1/datapilot" not in _Handler.paths

    # Old path would 404 — server records it
    import urllib.request

    req = urllib.request.Request(
        f"{http_guard_server}/v1/datapilot",
        data=b'{"sql":"SELECT 1"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(Exception):
        urllib.request.urlopen(req, timeout=5)
    assert "/v1/datapilot" in _Handler.paths


def test_check_hits_v1_check(http_guard_server: str) -> None:
    client = WriteGateSQLGuardClient(
        guard_url=http_guard_server,
        prefer_http=True,
        mode="http",
    )
    client._block_or_execute = None
    before = list(_Handler.paths)
    r = client.check("SELECT 1")
    assert r.allowed is True
    new_paths = _Handler.paths[len(before) :]
    assert "/v1/check" in new_paths
    assert "/v1/datapilot" not in new_paths
