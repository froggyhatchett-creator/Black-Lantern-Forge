"""Command line for the Forge Engine Viewer.

  python -m forge_engine_viewer PACKAGE.forgepkg                    open the viewer window (validates first)
  python -m forge_engine_viewer PACKAGE.forgepkg --validate-only    validate only; no GUI needed
  python -m forge_engine_viewer PACKAGE.forgepkg --dump-summary     validate, then print the package summary
  python -m forge_engine_viewer                                     open an empty window (File: Open package…)
Add --json to --validate-only or --dump-summary for machine-readable output.

Exit codes: 0 valid; 1 GUI unavailable (Tkinter or display missing); 2 bad arguments; 3 package refused.
The package is only read; nothing is written anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys

from forge_engine_viewer.errors import IngestionError
from forge_engine_viewer.ingest import ingest
from forge_engine_viewer.summary import summary_dict, summary_lines

EXIT_GUI_UNAVAILABLE = 1
EXIT_REFUSED = 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m forge_engine_viewer",
                                description="Independent consumer of Forge -> Engine Asset Contract v1 packages")
    p.add_argument("package", nargs="?", help="package directory (.forgepkg) holding asset.glb + manifest.json")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="validate and report; no GUI")
    mode.add_argument("--dump-summary", action="store_true", help="validate, then print the package summary; no GUI")
    p.add_argument("--json", action="store_true", help="JSON output (with --validate-only or --dump-summary)")
    return p


def _refused(exc: IngestionError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"status": "refused", "code": exc.code, "message": exc.message}, indent=2, sort_keys=True))
    print(f"forge-engine-viewer: refused [{exc.code}]: {exc.message}", file=sys.stderr)
    return EXIT_REFUSED


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    headless = args.validate_only or args.dump_summary
    if headless and args.package is None:
        parser.error("--validate-only and --dump-summary need a package path")
    if args.json and not headless:
        parser.error("--json needs --validate-only or --dump-summary")

    if headless:
        try:
            pkg = ingest(args.package)
        except IngestionError as exc:
            return _refused(exc, args.json)
        if args.validate_only:
            if args.json:
                print(json.dumps({"status": "valid", "package": pkg.path,
                                  "contract": {"id": pkg.contract_id, "version": pkg.contract_version},
                                  "checks": list(pkg.checks), "hashes_verified": list(pkg.hashes_verified),
                                  "glb_sha256": pkg.glb_sha256, "manifest_file_sha256": pkg.manifest_sha256},
                                 indent=2, sort_keys=True))
            else:
                print("\n".join([
                    f"VALID  {pkg.path}",
                    f"  contract           {pkg.contract_id} v{pkg.contract_version}",
                    f"  checks passed      {len(pkg.checks)}: {', '.join(pkg.checks)}",
                    f"  hashes verified    {len(pkg.hashes_verified)}: {', '.join(pkg.hashes_verified)}",
                    f"  glb_sha256         {pkg.glb_sha256}",
                    f"  manifest_sha256    {pkg.manifest_sha256}",
                ]))
        elif args.json:
            print(json.dumps(summary_dict(pkg), indent=2, sort_keys=True))
        else:
            print("\n".join(summary_lines(pkg)))
        return 0

    if args.package is not None:                 # validate before any window exists
        try:
            ingest(args.package)
        except IngestionError as exc:
            return _refused(exc, False)
    try:
        from forge_engine_viewer import window
    except ImportError as exc:
        print(f"forge-engine-viewer: the viewer window needs Tkinter ({exc}). "
              "Use --validate-only or --dump-summary without a GUI.", file=sys.stderr)
        return EXIT_GUI_UNAVAILABLE
    return window.run(args.package)            # the window's session validates again before drawing
