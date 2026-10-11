"""Command line. All behavior routes through the registry (forge.catalog.REGISTRY).

  python -m forge sword --seed N [--generator-version V] [--out PATH] [--json]     (Step 1 contract)
        [--obj-format {1,2}] [--save RECORD.json] [--preview IMAGE.png]
        [--view VIEW] [--width W] [--height H] [--ssaa S]                          (Step 2 contract)
  python -m forge generate ASSET_TYPE --seed N --generator-version V                (Step 2.5, generic)
        [--presentation-version P] [--export FORMAT:VERSION] [--out PATH]
        [--save RECORD.json] [--preview IMAGE.png] [preview options] [--json]
  python -m forge load RECORD.json [--out PATH [--obj-format {1,2}]] [--json]
  python -m forge preview RECORD.json [--out IMAGE.png] [--view VIEW] [--width W] [--height H] [--ssaa S]
  python -m forge export RECORD.json --format FORMAT:VERSION [--out PATH] [--json]    (Step 3)
  python -m forge validate-package PACKAGE.forgepkg [--reproduce] [--json]          (Step 3)

Step 3: `--export glb:1` (generate) and `export --format glb:1` write a Forge -> Engine
contract v1 package directory (asset.glb + manifest.json). `validate-package` checks
a package with the independent validator, without the generator; `--reproduce` also
regenerates it through the registry and requires byte-identical files.

`sword` is a pinned alias of `generate short_sword`: generator_version defaults to
1, presentation_version is 1, and the export is obj at --obj-format (default 1).
It never tracks newer registrations. `generate` has no version defaults.

Exit codes: 0 success; 2 invalid input (bad seed, unknown asset type/format,
unsupported version, malformed record, bad arguments); 3 a record failed
verification, or a package failed validation or reproduction. Unexpected errors are
not caught: they surface with a traceback. Nothing is written when input is invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from forge.catalog import REGISTRY
from forge.errors import ForgeError, RecordIntegrityError, RenderError
from forge.registry import (
    Registry,
    export_asset,
    exporter_for,
    generate_asset,
    present_asset,
    preview_for,
    render_asset_preview,
)
from forge.seed import parse_seed

EXIT_INVALID = 2
EXIT_INTEGRITY = 3

# The Step 1 / Step 2 `sword` command, pinned. Explicit values, not "newest registered".
SWORD_COMMAND = MappingProxyType({
    "asset_type": "short_sword",
    "generator_version": 1,
    "presentation_version": 1,
    "export_format": "obj",
    "export_version": 1,
})
_EXPORT_SPEC = re.compile(r"([a-z][a-z0-9_]*):([0-9]{1,6})")


def _add_preview_options(p: argparse.ArgumentParser) -> None:
    from forge.render.settings import PREVIEW_VIEWS
    p.add_argument("--view", choices=PREVIEW_VIEWS, help="camera preset (default three_quarter)")
    p.add_argument("--width", type=int, help="preview width in pixels (default 480)")
    p.add_argument("--height", type=int, help="preview height in pixels (default 960)")
    p.add_argument("--ssaa", type=int, help="supersampling factor per axis, 1-4 (default 2)")


def _build_parser(registry: Registry) -> argparse.ArgumentParser:
    fmt = SWORD_COMMAND["export_format"]
    fmt_versions = registry.export_versions(fmt)
    sword_generator = registry.asset(SWORD_COMMAND["asset_type"]).descriptor.generator_id
    parser = argparse.ArgumentParser(prog="python -m forge", description="Black Lantern Forge")
    sub = parser.add_subparsers(dest="command", required=True)

    sword = sub.add_parser("sword", help="generate a procedural short sword and export OBJ (pinned alias)")
    sword.add_argument("--seed", required=True, help="decimal integer in [0, 2**64-1]")
    sword.add_argument(
        "--generator-version", type=int, default=SWORD_COMMAND["generator_version"],
        help=f"generator version (registered: {list(registry.generator_versions(sword_generator))}; "
             f"pinned default {SWORD_COMMAND['generator_version']}, always recorded in the output)",
    )
    sword.add_argument("--out", help="output .obj path (default: output/short_sword_seed<SEED>_v<VERSION>.obj)")
    sword.add_argument("--json", action="store_true", help="print the full parameter record as JSON")
    sword.add_argument("--obj-format", type=int, choices=fmt_versions, default=SWORD_COMMAND["export_version"],
                       help="1 = Step 1 geometry-only OBJ (default); 2 = enriched OBJ + MTL with UVs, normals, materials")
    sword.add_argument("--save", metavar="RECORD.json", help="also write an asset record (Step 2)")
    sword.add_argument("--preview", metavar="IMAGE.png", help="also render a PNG preview (Step 2)")
    _add_preview_options(sword)

    gen = sub.add_parser("generate", help="generate any registered asset type (explicit versions)")
    gen.add_argument("asset_type", help=f"registered asset type: {', '.join(registry.asset_types())}")
    gen.add_argument("--seed", required=True, help="decimal integer in [0, 2**64-1]")
    gen.add_argument("--generator-version", type=int, required=True, help="explicit generator version")
    gen.add_argument("--presentation-version", type=int,
                     help="explicit presentation version (required for --save, --preview, presentation exports)")
    gen.add_argument("--export", metavar="FORMAT:VERSION", help="exporter, e.g. obj:1 or obj:2")
    gen.add_argument("--out", help="export path (default: output/<asset_type>_seed<SEED>_v<VERSION><ext>)")
    gen.add_argument("--save", metavar="RECORD.json", help="also write an asset record")
    gen.add_argument("--preview", metavar="IMAGE.png", help="also render a PNG preview")
    gen.add_argument("--json", action="store_true", help="print the full record of what was generated as JSON")
    _add_preview_options(gen)

    load = sub.add_parser("load", help="reload an asset record: validate, regenerate, verify")
    load.add_argument("record", help="asset record .json")
    load.add_argument("--out", help="re-export the reproduced asset to this .obj path")
    load.add_argument("--obj-format", type=int, choices=fmt_versions, default=SWORD_COMMAND["export_version"],
                      help="format for --out (default 1)")
    load.add_argument("--json", action="store_true", help="print the verification report as JSON")

    preview = sub.add_parser("preview", help="render a PNG preview from an asset record")
    preview.add_argument("record", help="asset record .json")
    preview.add_argument("--out", help="output .png (default: <record dir>/<record stem>_<view>.png)")
    _add_preview_options(preview)

    export = sub.add_parser("export", help="verify an asset record, then export it in an explicit format")
    export.add_argument("record", help="asset record .json")
    export.add_argument("--format", required=True, metavar="FORMAT:VERSION",
                        help="explicit exporter, e.g. glb:1 (engine package) or obj:2")
    export.add_argument("--out", help="output path (default: output/<asset_type>_seed<SEED>_v<VERSION><ext>)")
    export.add_argument("--json", action="store_true", help="print the export report as JSON")

    check = sub.add_parser("validate-package", help="validate an engine package without the generator (fail closed)")
    check.add_argument("package", help="package directory holding asset.glb + manifest.json")
    check.add_argument("--reproduce", action="store_true",
                       help="also regenerate it through the registry and require byte-identical files")
    check.add_argument("--json", action="store_true", help="print the validation report as JSON")
    return parser


def _fail(message: str, code: int = EXIT_INVALID) -> int:
    print(f"forge: error: {message}", file=sys.stderr)
    return code


def _preview_settings(args, base=None):
    from forge.render.settings import DEFAULT_PREVIEW, PreviewSettings
    base = base or DEFAULT_PREVIEW
    return PreviewSettings(
        preview_version=base.preview_version,
        view=args.view if args.view is not None else base.view,
        width=args.width if args.width is not None else base.width,
        height=args.height if args.height is not None else base.height,
        ssaa=args.ssaa if args.ssaa is not None else base.ssaa,
    )


def _check_suffix(path: str | None, suffix: str, flag: str) -> None:
    if path is not None and Path(path).suffix.lower() != suffix:
        raise RenderError(f"{flag} must end in {suffix}; got {path!r}")


# ------------------------------------------------------------------ generate (and the sword alias)

@dataclass(frozen=True)
class _Plan:
    asset_type: str
    seed_text: str
    generator_version: int
    presentation_version: int | None
    export: tuple[str, int] | None
    out: str | None
    save: str | None
    preview: str | None
    json: bool


def _run_generate(plan: _Plan, args, registry: Registry) -> int:
    from forge.record import build_record, save_record
    from forge.render import write_preview_png

    try:
        entry = registry.asset(plan.asset_type)
        d = entry.descriptor
        seed = parse_seed(plan.seed_text)
        registry.generator(d.generator_id, plan.generator_version)
        exporter = path = None
        if plan.export is not None:
            exporter = exporter_for(registry, d.asset_type, *plan.export)
            path = (Path(plan.out) if plan.out else
                    Path("output") / f"{d.asset_type}_seed{seed}_v{plan.generator_version}{exporter.extension}")
            if path.suffix.lower() != exporter.extension:
                return _fail(f"--out must end in {exporter.extension}; got {str(path)!r}")
        elif plan.out is not None:
            return _fail("--out requires --export FORMAT:VERSION")
        needs_presentation = bool(plan.save or plan.preview or (exporter is not None and exporter.needs_presentation))
        family = settings = None
        if needs_presentation:
            if plan.presentation_version is None:
                return _fail("--presentation-version is required for --save, --preview, or a presentation export")
            family = registry.presentation(d.presentation_id, plan.presentation_version)
            _check_suffix(plan.save, ".json", "--save")
            _check_suffix(plan.preview, ".png", "--preview")
            settings = _preview_settings(args)
            if plan.preview:
                preview_for(registry, d.asset_type, family.presentation_version, settings.preview_version)
        asset = generate_asset(registry, d.asset_type, seed, plan.generator_version)
    except ForgeError as exc:
        return _fail(str(exc))

    presented = present_asset(registry, asset, family.versions) if needs_presentation else None
    written, data, digest = (), b"", ""
    if exporter is not None:
        try:
            written = export_asset(registry, asset, presented, exporter.format_id, exporter.format_version, path)
        except ForgeError as exc:
            return _fail(str(exc))
        data = written[0].read_bytes()
        digest = hashlib.sha256(data).hexdigest()

    image = render_asset_preview(registry, presented, settings) if plan.preview else None
    record = None
    extra = [f"  {label:<18} {extra_path} ({exporter.format_id}_format {exporter.format_version})"
             for label, extra_path in zip(exporter.extra_file_labels, written[1:])] if exporter else []
    if exporter is not None and exporter.contract is not None:
        extra.append(f"  {'contract':<18} {exporter.contract[0]} v{exporter.contract[1]} (validated before writing)")
    if plan.save:
        record = build_record(presented, image, registry=registry)
        save_record(record, plan.save, registry=registry)
        extra += [f"  asset record       {plan.save}",
                  f"  record_content     {record['integrity']['record_content_sha256']}"]
    if image is not None:
        content = record["integrity"]["record_content_sha256"] if record else None
        write_preview_png(image, plan.preview, presented, content)
        extra += [f"  preview            {plan.preview} ({image.settings.view}, "
                  f"{image.width}x{image.height}, ssaa {image.settings.ssaa})",
                  f"  pixels_sha256      {image.pixels_sha256}"]

    if plan.json:
        out = asset.to_dict()
        if exporter is not None:
            out[exporter.format_id] = {"path": str(written[0]), "sha256": digest, "bytes": len(data)}
            if needs_presentation:
                out[exporter.format_id][f"{exporter.format_id}_format"] = exporter.format_version
            if exporter.contract is not None:
                out[exporter.format_id]["contract"] = {"id": exporter.contract[0], "version": exporter.contract[1]}
                out[exporter.format_id]["files"] = [str(p) for p in written]
        if needs_presentation:
            out["presentation"] = {**presented.versions.to_dict(), "materials": presented.materials}
        if record is not None:
            out["asset_record"] = {"path": plan.save,
                                   "record_content_sha256": record["integrity"]["record_content_sha256"]}
        if image is not None:
            out["preview"] = {"path": plan.preview, **image.settings.to_dict(), "pixels_sha256": image.pixels_sha256}
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        lines = [f"Black Lantern Forge - {d.display_name}",
                 f"  seed               {asset.seed}",
                 f"  generator_version  {asset.generator_version}",
                 *entry.summary_lines(asset)]
        if exporter is not None:
            lines += [f"  wrote              {written[0]}", f"  sha256             {digest}"]
        print("\n".join(lines + extra))
    return 0


def _cmd_sword(args, registry: Registry) -> int:
    return _run_generate(_Plan(
        asset_type=SWORD_COMMAND["asset_type"], seed_text=args.seed, generator_version=args.generator_version,
        presentation_version=SWORD_COMMAND["presentation_version"],
        export=(SWORD_COMMAND["export_format"], args.obj_format), out=args.out,
        save=args.save, preview=args.preview, json=args.json), args, registry)


def _cmd_generate(args, registry: Registry) -> int:
    export = None
    if args.export is not None:
        m = _EXPORT_SPEC.fullmatch(args.export)
        if m is None:
            return _fail(f"--export must look like FORMAT:VERSION (e.g. obj:1); got {args.export!r}")
        export = (m.group(1), int(m.group(2)))
    return _run_generate(_Plan(
        asset_type=args.asset_type, seed_text=args.seed, generator_version=args.generator_version,
        presentation_version=args.presentation_version, export=export, out=args.out,
        save=args.save, preview=args.preview, json=args.json), args, registry)


# ------------------------------------------------------------------ load / preview

def _cmd_load(args, registry: Registry) -> int:
    from forge.record import load_record
    fmt = (SWORD_COMMAND["export_format"], args.obj_format)
    try:
        if args.out:
            _check_suffix(args.out, registry.exporter(*fmt).extension, "--out")
        loaded = load_record(args.record, registry=registry)
        if args.out:
            exporter_for(registry, loaded.asset.asset_type, *fmt)
    except RecordIntegrityError as exc:
        return _fail(f"verification failed: {exc}", EXIT_INTEGRITY)
    except ForgeError as exc:
        return _fail(str(exc))
    a, p = loaded.asset, loaded.presented
    report = {
        "record": args.record,
        "status": "verified",
        "asset_type": a.asset_type,
        "seed": str(a.seed),
        "generator_version": a.generator_version,
        **p.versions.to_dict(),
        "materials": {c.name: c.material.preset for c in p.components},
        "checks_passed": list(loaded.verified),
        "record_content_sha256": loaded.record_content_sha256,
    }
    if loaded.spec.preview is not None:
        report["preview"] = loaded.spec.preview.to_dict()
    if args.out:
        written = export_asset(registry, a, p, fmt[0], fmt[1], args.out)
        report["export"] = {"path": args.out, "obj_format": args.obj_format,
                            "sha256": hashlib.sha256(written[0].read_bytes()).hexdigest()}
        if len(written) > 1:
            report["export"]["mtl"] = str(written[1])
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        lines = [
            "Black Lantern Forge - asset record verified",
            f"  record             {args.record}",
            f"  seed               {a.seed}",
            f"  generator_version  {a.generator_version}",
            f"  presentation       v{p.versions.presentation_version} (normals v{p.versions.normals_version}, "
            f"uv v{p.versions.uv_version}, material v{p.versions.material_version})",
            "  materials          " + ", ".join(f"{c.name}={c.material.preset}" for c in p.components),
            f"  checks passed      {', '.join(loaded.verified) or '(record carries no expectations)'}",
            f"  record_content     {loaded.record_content_sha256}",
        ]
        if args.out:
            lines.append(f"  exported           {args.out} (obj_format {args.obj_format}, "
                         f"sha256 {report['export']['sha256']})")
        print("\n".join(lines))
    return 0


def _cmd_preview(args, registry: Registry) -> int:
    from forge.record import load_record
    from forge.render import write_preview_png
    try:
        _check_suffix(args.out, ".png", "--out")
        loaded = load_record(args.record, registry=registry)
        overrides = any(v is not None for v in (args.view, args.width, args.height, args.ssaa))
        settings = _preview_settings(args, loaded.spec.preview)
        preview_for(registry, loaded.asset.asset_type, loaded.presented.versions.presentation_version,
                    settings.preview_version)
    except RecordIntegrityError as exc:
        return _fail(f"verification failed: {exc}", EXIT_INTEGRITY)
    except ForgeError as exc:
        return _fail(str(exc))

    image = render_asset_preview(registry, loaded.presented, settings)
    expected = loaded.spec.expected_pixels_sha256
    verify = expected is not None and settings == loaded.spec.preview
    if verify and image.pixels_sha256 != expected:
        return _fail(f"verification failed: preview pixels_sha256 is {image.pixels_sha256}, record expects "
                     f"{expected}", EXIT_INTEGRITY)
    record_path = Path(args.record)
    out = Path(args.out) if args.out else record_path.with_name(f"{record_path.stem}_{settings.view}.png")
    write_preview_png(image, out, loaded.presented, loaded.record_content_sha256)
    status = "verified against record" if verify else (
        "settings overridden; not compared" if overrides and expected else "no expected hash in record")
    print("\n".join([
        "Black Lantern Forge - preview",
        f"  record             {args.record}",
        f"  seed               {loaded.asset.seed}",
        f"  view               {settings.view} ({settings.width}x{settings.height}, ssaa {settings.ssaa})",
        f"  wrote              {out}",
        f"  pixels_sha256      {image.pixels_sha256} ({status})",
    ]))
    return 0


# ------------------------------------------------------------------ export / validate-package (Step 3)

class UnknownFormatSpec(ForgeError):
    """A FORMAT:VERSION argument that doesn't parse."""


def _export_spec(text: str, flag: str) -> tuple[str, int]:
    m = _EXPORT_SPEC.fullmatch(text)
    if m is None:
        raise UnknownFormatSpec(f"{flag} must look like FORMAT:VERSION (e.g. glb:1); got {text!r}")
    return m.group(1), int(m.group(2))


def _cmd_export(args, registry: Registry) -> int:
    from forge.record import load_record
    try:
        fmt = _export_spec(args.format, "--format")
        registry.exporter(*fmt)
        loaded = load_record(args.record, registry=registry)
        a = loaded.asset
        exporter = exporter_for(registry, a.asset_type, *fmt)
        path = (Path(args.out) if args.out else
                Path("output") / f"{a.asset_type}_seed{a.seed}_v{a.generator_version}{exporter.extension}")
        if path.suffix.lower() != exporter.extension:
            return _fail(f"--out must end in {exporter.extension}; got {str(path)!r}")
        written = export_asset(registry, a, loaded.presented, *fmt, path)
    except RecordIntegrityError as exc:
        return _fail(f"verification failed: {exc}", EXIT_INTEGRITY)
    except ForgeError as exc:
        return _fail(str(exc))
    files = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in written}
    report = {"record": args.record, "status": "exported", "asset_type": a.asset_type, "seed": str(a.seed),
              "generator_version": a.generator_version, "format": f"{fmt[0]}:{fmt[1]}",
              "record_content_sha256": loaded.record_content_sha256, "files": files}
    if exporter.contract is not None:
        report["contract"] = {"id": exporter.contract[0], "version": exporter.contract[1]}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    lines = ["Black Lantern Forge - export from verified record",
             f"  record             {args.record}",
             f"  seed               {a.seed}",
             f"  generator_version  {a.generator_version}",
             f"  checks passed      {', '.join(loaded.verified) or '(record carries no expectations)'}",
             f"  format             {fmt[0]}:{fmt[1]}"]
    labels = ("wrote", *exporter.extra_file_labels)
    for label, (name, digest) in zip(labels, files.items()):
        lines += [f"  {label:<18} {name}", f"  {'sha256':<18} {digest}"]
    if exporter.contract is not None:
        lines.append(f"  {'contract':<18} {exporter.contract[0]} v{exporter.contract[1]} (validated before writing)")
    print("\n".join(lines))
    return 0


def _reproduce(package: Path, report, registry: Registry) -> tuple[str, ...]:
    """Regenerate the package through the registry; every file must match byte for byte."""
    import tempfile
    entry = registry.asset(report.asset_type)
    d = entry.descriptor
    pres = dict(report.presentation)
    if (report.generator_id, pres["presentation_id"]) != (d.generator_id, d.presentation_id):
        raise RecordIntegrityError("the package names a generator or presentation the asset type doesn't use")
    family = registry.presentation(d.presentation_id, pres["presentation_version"])
    pinned = family.versions.to_dict()
    if {k: pres[k] for k in pinned} != pinned:
        raise RecordIntegrityError(f"package presentation versions {pres} differ from the registered {pinned}")
    exporter = exporter_for(registry, d.asset_type, *report.exporter)
    asset = generate_asset(registry, d.asset_type, int(report.seed), report.generator_version)
    presented = present_asset(registry, asset, family.versions)
    with tempfile.TemporaryDirectory() as tmp:
        written = export_asset(registry, asset, presented, *report.exporter, Path(tmp) / f"r{exporter.extension}")
        names = sorted(p.name for p in written)
        if names != sorted(p.name for p in package.iterdir()):
            raise RecordIntegrityError(f"regenerated files {names} differ from the package's")
        for p in written:
            if p.read_bytes() != (package / p.name).read_bytes():
                raise RecordIntegrityError(f"{p.name} is not reproduced byte for byte")
    return tuple(names)


def _cmd_validate_package(args, registry: Registry) -> int:
    from forge.engine.validate import validate_package
    from forge.errors import EngineContractError
    package = Path(args.package)
    if not package.is_dir():
        return _fail(f"{args.package!r} is not a package directory")
    try:
        report = validate_package(package)
    except EngineContractError as exc:
        return _fail(f"package invalid: {exc}", EXIT_INTEGRITY)
    reproduced = None
    if args.reproduce:
        try:
            reproduced = _reproduce(package, report, registry)
        except RecordIntegrityError as exc:
            return _fail(f"package not reproduced: {exc}", EXIT_INTEGRITY)
        except ForgeError as exc:
            return _fail(f"package not reproduced: {exc}")
    if args.json:
        out = {"package": args.package, **report.to_dict()}
        if reproduced is not None:
            out["reproduced"] = list(reproduced)
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    lines = [
        "Black Lantern Forge - engine package valid",
        f"  package            {args.package}",
        f"  contract           {report.contract_id} v{report.contract_version}",
        f"  asset              {report.asset_type} seed {report.seed} ({report.generator_id} v{report.generator_version})",
        f"  exporter           {report.exporter[0]}:{report.exporter[1]}",
        f"  lod0               {len(report.render_nodes)} nodes, {report.vertices} vertices, {report.triangles} triangles",
        f"  collision_hull     convex hull, {report.collision_vertices} vertices, {report.collision_triangles} triangles",
        *(f"  {name:<18} {list(t)}" for name, t in report.sockets),
        f"  checks passed      {len(report.checks)}: {', '.join(report.checks)}",
        f"  hashes verified    {len(report.hashes_verified)}: {', '.join(report.hashes_verified)}",
        f"  glb_sha256         {report.glb_sha256}",
        f"  manifest_sha256    {report.manifest_sha256}",
    ]
    if reproduced is not None:
        lines.append(f"  reproduced         byte-identical: {', '.join(reproduced)}")
    print("\n".join(lines))
    return 0


_COMMANDS = MappingProxyType({
    "sword": _cmd_sword,
    "generate": _cmd_generate,
    "load": _cmd_load,
    "preview": _cmd_preview,
    "export": _cmd_export,
    "validate-package": _cmd_validate_package,
})


def main(argv: list[str] | None = None, *, registry: Registry = REGISTRY) -> int:
    args = _build_parser(registry).parse_args(argv)
    return _COMMANDS[args.command](args, registry)


if __name__ == "__main__":
    sys.exit(main())
