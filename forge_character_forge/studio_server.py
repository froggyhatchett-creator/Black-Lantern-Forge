"""Local Character Studio server: serves the studio and runs exact builds/exports with the Python engine.

    python3 -m forge_character_forge studio [--port 8765] [--out studio_exports]

GET  /                  the studio page
GET  /api/health        {"ok": true}
POST /api/export        body = Character DNA JSON -> exact public GLB (validated) written to --out
GET  /api/file/<name>   download a GLB written by /api/export
Binds to 127.0.0.1 only.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO_DIR = ROOT / "studio"
DEFAULT_PACK = ROOT / "examples" / "character_forge_aaa" / "studio" / "studio_pack.bin"
SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}[hidden]{display:none!important}</style>'
            '</head><body>')
TYPES = {".js": "text/javascript", ".json": "application/json", ".bin": "application/octet-stream", ".glb": "model/gltf-binary",
         ".html": "text/html; charset=utf-8"}
_lock = threading.Lock()


def make_handler(pack: Path, out_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = (STUDIO_DIR / "index.html").read_text(encoding="utf-8")
                return self._send(200, (SKELETON + html + "</body></html>").encode(), TYPES[".html"])
            if path == "/api/health":
                return self._json(200, {"ok": True, "engine": "forge_character_forge"})
            m = re.fullmatch(r"/api/file/([\w.-]+\.glb)", path)
            if m:
                f = out_dir / m.group(1)
                if not f.is_file():
                    return self._json(404, {"error": "no such export"})
                return self._send(200, f.read_bytes(), TYPES[".glb"])
            if path == "/studio_pack.bin":
                return self._send(200, pack.read_bytes(), TYPES[".bin"])
            m = re.fullmatch(r"/([\w.-]+\.(?:js|json))", path)
            if m and (STUDIO_DIR / m.group(1)).is_file():
                f = STUDIO_DIR / m.group(1)
                return self._send(200, f.read_bytes(), TYPES[f.suffix])
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/export":
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n <= 0 or n > 2_000_000:
                    return self._json(400, {"error": "missing or oversized DNA body"})
                dna = json.loads(self.rfile.read(n))
                from forge_character_forge import dna as D
                from forge_character_forge.pipeline import export_character
                D.validate_dna(dna)
                name = re.sub(r"[^\w.-]+", "_", dna["identity"].get("name") or "character")[:40] or "character"
                out_dir.mkdir(parents=True, exist_ok=True)
                target = out_dir / f"{name}.glb"
                with _lock:  # one exact build at a time
                    res = export_character(dna, target, profile="public", physics=True)
                (out_dir / f"{name}.dna.json").write_text(json.dumps(dna, indent=1))
                res["download"] = f"api/file/{target.name}"
                res["path"] = str(target)
                return self._json(200, {k: res[k] for k in ("path", "bytes", "sha256", "validation", "download", "clips")})
            except Exception as exc:  # report every failure to the page
                return self._json(400, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def serve(port: int = 8765, pack: Path = DEFAULT_PACK, out_dir: Path = Path("studio_exports")) -> ThreadingHTTPServer:
    if not Path(pack).is_file():
        raise FileNotFoundError(f"studio pack not found: {pack} (run python3 tools/build_studio.py)")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Path(pack), Path(out_dir)))
    return httpd
