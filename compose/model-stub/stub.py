"""An OpenAI-compatible model for development and the end-to-end tests: no network, no key, scripted answers.

It answers ``POST /v1/chat/completions`` (with and without ``stream``) and ``GET /v1/models``. The system prompt
steers it:

- ``SLOW <seconds>``: wait that long before answering (a long run, for stopping a worker in the middle of it);
- ``CALL <tool> <json arguments>``: call that tool once, then answer with what it returned;
- anything else: answer ``stub: <the last user message>``.

It also answers the part of Ollama's API that the semantic knowledge index uses, with one embedding model
(``EMBEDDING_MODEL``): ``GET /api/version``, ``/api/tags``, ``/api/ps``, ``POST /api/show`` and ``/api/embed``. Its
vectors are bags of hashed words (``DIMENSIONS`` values, normalized): texts that share words are close, so a semantic
search finds the passage whose words a query names. ``/api/embed`` calls and texts are counted at ``GET /stats``
(``embed_calls``, ``embed_texts``).

Requests are counted per system prompt at ``GET /stats`` (for the tests). Only for development and tests.
"""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import re
import threading
import time
from typing import Any

COUNTS: dict[str, int] = {}
LOCK = threading.Lock()

EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DIMENSIONS = 64
DIGEST = hashlib.sha256(b"nodestro model stub embedding").hexdigest()
EMBEDDING_DETAILS = {"format": "gguf", "family": "qwen3", "parameter_size": "596M", "quantization_level": "Q8_0"}


def _vector(text: str) -> list[float]:
    """A bag of hashed words: equal words land on equal dimensions, so shared words make texts similar."""
    values = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        values[int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values] if any(values) else [1.0 / math.sqrt(DIMENSIONS)] * DIMENSIONS


def _ollama_get(path: str) -> Any:
    if path == "/api/version":
        return {"version": "0.0.0-stub"}
    if path == "/api/tags":
        model = {"name": EMBEDDING_MODEL, "model": EMBEDDING_MODEL, "digest": DIGEST, "size": 639_000_000,
                 "modified_at": "2026-01-01T00:00:00Z", "details": EMBEDDING_DETAILS}  # fmt: skip
        return {"models": [model]}
    if path == "/api/ps":
        return {"models": []}
    return None


def _ollama_post(path: str, body: dict[str, Any]) -> tuple[int, Any] | None:
    if path not in ("/api/show", "/api/embed"):
        return None
    if str(body.get("model") or "") != EMBEDDING_MODEL:
        return 404, {"error": f"model '{body.get('model')}' not found"}
    if path == "/api/show":
        info = {"general.architecture": "qwen3", "qwen3.context_length": 32768, "qwen3.embedding_length": DIMENSIONS}
        return 200, {"capabilities": ["embedding"], "details": EMBEDDING_DETAILS, "model_info": info, "license": "stub",
                     "parameters": "", "modified_at": "2026-01-01T00:00:00Z"}  # fmt: skip
    texts = body.get("input")
    texts = [texts] if isinstance(texts, str) else [str(item) for item in texts or []]
    with LOCK:
        COUNTS["embed_calls"] = COUNTS.get("embed_calls", 0) + 1
        COUNTS["embed_texts"] = COUNTS.get("embed_texts", 0) + len(texts)
    words = sum(len(text.split()) for text in texts)
    return 200, {"model": EMBEDDING_MODEL, "embeddings": [_vector(text) for text in texts],
                 "prompt_eval_count": words, "total_duration": 1_000_000, "load_duration": 0}  # fmt: skip


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
            # Only the JSON object after the tool name: the runtime may add its own sections to the system prompt.
            arguments = "{}"
            if len(words) > 2:
                try:
                    _, end = json.JSONDecoder().raw_decode(words[2])
                    arguments = words[2][:end]
                except ValueError:
                    arguments = words[2]
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
        elif (answer := _ollama_get(self.path.rstrip("/"))) is not None:
            self._json(200, answer)
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        ollama = _ollama_post(self.path.rstrip("/"), body)
        if ollama is not None:
            self._json(*ollama)
            return
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
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
