"""Double-click launcher for Forge Desktop.

On Windows, .pyw files run with pythonw (no console window). Elsewhere:
    python launch_forge_desktop.pyw
Equivalent to `python -m forge_desktop` from this folder.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forge_desktop.app import main  # noqa: E402

sys.exit(main())
