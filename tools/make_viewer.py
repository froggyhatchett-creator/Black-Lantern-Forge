"""Embed an exported GLB into tools/viewer_template.html -> a self-contained three.js viewer page."""
import base64
import sys
from pathlib import Path

glb, out = Path(sys.argv[1]), Path(sys.argv[2])
html = Path(__file__).with_name("viewer_template.html").read_text()
data = base64.b64encode(glb.read_bytes()).decode("ascii")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html.replace("__GLB_BASE64__", data))
print(out, f"{out.stat().st_size / 1e6:.1f} MB")
