"""An OpenAI-compatible model for development and the end-to-end tests: no network, no key, scripted answers.

It answers ``POST /v1/chat/completions`` (with and without ``stream``) and ``GET /v1/models``. The system prompt
steers it:

- ``SLOW <seconds>``: wait that long before answering (a long run, for stopping a worker in the middle of it);
- ``CALL <tool> <json arguments>``: call that tool once, then answer with what it returned;
- anything else: answer ``stub: <the last user message>``.

Requests are counted per system prompt at ``GET /stats`` (for the tests). Only for development and tests.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from typing import Any

COUNTS: dict[str, int] = {}
LOCK = threading.Lock()


def _answer(messages: list[dict[str, Any]]) -> dict[str, Any]:
    system = next((str(item.get("content") or "") for item in messages if item.get("role") == "system"), "")
    with LOCK:
        COUNTS[system] = COUNTS.get(system, 0) + 1
    words = system.split(maxsplit=2)
    if len(words) >= 2 and words[0] == "SLOW":
        time.sleep(float(words[1]))
    if len(words) >= 2 and words[0] == "CALL":
        results = [item for item in messages if item.get("role") == "tool"]
        if not results:
            arguments = words[2] if len(words) > 2 else "{}"
            return {
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": words[1], "arguments": arguments}}
                ]
            }
        return {"content": f"tool said: {results[-1].get('content')}"}
    users = [item for item in messages if item.get("role") == "user"]
    last = users[-1].get("content") if users else ""
    if isinstance(last, list):
        last = " ".join(str(part.get("text", "")) for part in last if isinstance(part, dict))
    return {"content": f"stub: {last}"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(format % args, flush=True)

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": "stub-model", "object": "model", "owned_by": "stub"}]})
        elif self.path == "/stats":
            with LOCK:
                self._json(200, dict(COUNTS))
        elif self.path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        message = _answer(list(body.get("messages") or []))
        finish = "tool_calls" if "tool_calls" in message else "stop"
        model = str(body.get("model") or "stub-model")
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        base = {"id": "chatcmpl-stub", "created": int(time.time()), "model": model}
        if not body.get("stream"):
            choice = {"index": 0, "message": {"role": "assistant", "content": None, **message}, "finish_reason": finish}
            self._json(200, {**base, "object": "chat.completion", "choices": [choice], "usage": usage})
            return
        delta: dict[str, Any] = {"role": "assistant"}
        if "tool_calls" in message:
            delta["tool_calls"] = [{"index": 0, **call} for call in message["tool_calls"]]
        else:
            delta["content"] = message["content"]
        chunks = [
            {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
            {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9100"))
    print(f"model stub on port {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
