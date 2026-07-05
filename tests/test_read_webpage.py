"""Smoke check for the T2-3 read_webpage tool."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.core.tools  # noqa: F401  triggers discovery
from backend.core.tools.registry import REGISTRY


def _build_fixture():
    parts = [
       "<html><head>",
       "<title>SG Demo</title>",
      "</head>",
       "<body>",
       "<h1>Hi</h1>",
       "<script>evilscript</" + "script>",   # split</script> so this file's lexer is happy
        "<p>Hello sg_cube page</p>",
        "<footer>ignore me</footer>",
     "</body>",
     "</html>",
    ]
    return "".join(parts)


def _checks():
    assert "read_webpage" in REGISTRY, "read_webpage missing from REGISTRY"
    t = REGISTRY["read_webpage"]
    assert t.security.value == "safe", f"expected SAFE, got {t.security}"

    import http.server, threading, socketserver

    FIXTURE_HTML = _build_fixture()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_): pass  # silence
        def do_GET(self):
            body = FIXTURE_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), H) as srv:
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            r = t.func(url=f"http://127.0.0.1:{port}/")
            assert r.status.value == "success", r.message
            assert r.data["title"] == "SG Demo"
            assert "Hello sg_cube page" in r.message
            assert "evilscript" not in r.message, "script tag must be stripped"
            assert "ignore me" not in r.message, "footer must be stripped"
            print("  PASS: read_webpage fetches + strips HTML")

            r2 = t.func(url="")
            assert r2.status.value == "blocked"
            print("  PASS: blocks empty URL")

            r3 = t.func(url=f"127.0.0.1:{port}")
            assert r3.status.value == "success", r3.message
            assert r3.data["url"].startswith("http://")
            print("  PASS: auto-prefixes http:// when scheme missing")

            r4 = t.func(url="http://127.0.0.1:1/no-server-here")
            assert r4.status.value == "error", r4.reason
            print("  PASS: connection failure surfaces as error")
        finally:
            srv.shutdown()
            srv.server_close()


_checks()
print("=== T2-3 verification: ALL PASSED ===")
