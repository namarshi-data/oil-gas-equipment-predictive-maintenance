"""Loopback-only portfolio assistant. Trusted identity is fixed at startup."""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .assistant import EvidenceAssistant, QueryError


def make_server(root, principal, port=8790, mode="rules", model=None):
    engine = EvidenceAssistant(root, principal, mode, model)
    assets = {"/": ("assistant.html", "text/html"), "/assistant.js": ("assistant.js", "text/javascript"), "/assistant.css": ("assistant.css", "text/css")}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log questions, credentials or evidence rows.

        def allowed_host(self):
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in allowed and (origin is None or origin in {"http://" + h for h in allowed})

        def send(self, status, value, mime="application/json"):
            content = json.dumps(value, allow_nan=False).encode() if mime == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Only same-origin loopback requests are accepted."})
            parsed = urlparse(self.path)
            if parsed.path in assets:
                name, mime = assets[parsed.path]
                return self.send(200, (Path(root) / "web" / name).read_bytes(), mime)
            if parsed.path == "/api/context":
                return self.send(200, {"principal": engine.principal, "assigned_sites": sorted(engine.sites), "mode": "Rules-based · no LLM" if mode == "rules" else "OpenAI planner · deterministic evidence", "local_demo": True, "evaluation_start": engine.settings["evaluation_start"], "evaluation_end": engine.settings["evaluation_end"]})
            if parsed.path == "/api/evidence":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"source", "site", "asset_id"} or any(len(v) != 1 for v in query.values()):
                    return self.send(400, {"error": "Unsupported evidence arguments."})
                try:
                    result = engine.evidence(query.get("source", [""])[0], query.get("site", [None])[0], query.get("asset_id", [None])[0])
                    return self.send(200, result)
                except QueryError as exc:
                    return self.send(403, {"error": str(exc)})
            return self.send(404, {"error": "Not found."})

        def do_POST(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Only same-origin loopback requests are accepted."})
            if self.path != "/api/ask":
                return self.send(404, {"error": "Not found."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "Use application/json."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 8000:
                    return self.send(400, {"error": "Request body is too large or empty."})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or set(payload) != {"question"}:
                    return self.send(400, {"error": "Only a question is accepted. Identity and roles are server configuration."})
            except (ValueError, UnicodeDecodeError):
                return self.send(400, {"error": "Invalid JSON request."})
            return self.send(200, engine.ask(payload["question"]))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.engine = engine
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--principal", required=True, help="Trusted local-demo identity from dim_user_site.csv")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--mode", choices=["rules", "openai"], default="rules")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    args = parser.parse_args()
    if args.mode == "openai" and (not args.model or not os.environ.get("OPENAI_API_KEY")):
        parser.error("OpenAI mode needs OPENAI_API_KEY and an explicit OPENAI_MODEL (or --model).")
    server = make_server(args.root.resolve(), args.principal, args.port, args.mode, args.model)
    print(f"Local demo: http://127.0.0.1:{server.server_address[1]} · {args.mode} · fixed principal {args.principal}", flush=True)
    print("No production authentication. Do not expose this server beyond loopback. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
