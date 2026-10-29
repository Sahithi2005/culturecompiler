"""Tiny HTTP server (standard library only).  Run:  python -m app.server

Env: QLOO_API_KEY (live mode), QLOO_BASE_URL, CC_MOCK=1 (force synthetic), ANTHROPIC_API_KEY (optional
wording polish), PORT (default 8000).
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import AnalysisError, analyze
from .llm import AnthropicLLM
from .mock import MockQloo
from .models import Brief, BriefError, example_brief
from .qloo import LIVE_BASE, QlooClient, QlooError

STATIC = Path(__file__).parent / "static"


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader (KEY=value lines). Real environment variables win."""
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

MAX_BODY = 100_000
_slots = threading.BoundedSemaphore(2)  # protect the API quota on a public demo
RATE = (10, 600)  # max analyses per client IP per window (count, seconds)
_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


def rate_limited(ip: str, now: float | None = None) -> bool:
    import time
    now = time.time() if now is None else now
    with _hits_lock:
        recent = [t for t in _hits.get(ip, []) if now - t < RATE[1]]
        if len(recent) >= RATE[0]:
            _hits[ip] = recent
            return True
        recent.append(now)
        _hits[ip] = recent
        if len(_hits) > 5000:
            _hits.clear()
        return False


def make_client():
    key = os.environ.get("QLOO_API_KEY", "").strip()
    if os.environ.get("CC_MOCK") == "1" or not key:
        return MockQloo()
    return QlooClient(key, os.environ.get("QLOO_BASE_URL", LIVE_BASE))


def make_llm():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return AnthropicLLM(key) if key else None


class Handler(BaseHTTPRequestHandler):
    client = None
    llm = None

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/health":
            self._json(200, {"ok": True, "mode": self.client.mode, "llm": self.llm is not None})
        elif path == "/api/example":
            self._json(200, example_brief())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/analyze":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if not 0 < n <= MAX_BODY:
            return self._json(413, {"error": "Body missing or too large."})
        try:
            brief = Brief.from_dict(json.loads(self.rfile.read(n)))
        except json.JSONDecodeError:
            return self._json(400, {"error": "Body is not valid JSON."})
        except BriefError as e:
            return self._json(400, {"error": str(e)})
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if rate_limited(ip):
            return self._json(429, {"error": "Rate limit reached for this demo; please wait a few minutes."})
        if not _slots.acquire(blocking=False):
            return self._json(429, {"error": "Server busy; try again in a few seconds."})
        try:
            self._json(200, analyze(brief, self.client, self.llm))
        except AnalysisError as e:
            self._json(422, {"error": str(e)})
        except QlooError as e:
            self._json(502, {"error": f"Qloo error: {e}"})
        except Exception:  # never leak internals or keys
            self._json(500, {"error": "Internal error while analysing."})
        finally:
            _slots.release()

    def log_message(self, fmt, *args):  # keep logs free of query strings
        pass


def make_server(port: int = 0, client=None, llm=None) -> ThreadingHTTPServer:
    h = type("BoundHandler", (Handler,), {"client": client or make_client(), "llm": llm})
    return ThreadingHTTPServer(("0.0.0.0", port), h)


if __name__ == "__main__":
    load_dotenv()
    port = int(os.environ.get("PORT", "8000"))
    srv = make_server(port, llm=make_llm())
    print(f"CultureCompiler on :{port}  data mode = {srv.RequestHandlerClass.client.mode}")
    srv.serve_forever()
