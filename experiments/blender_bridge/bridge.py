"""Forge side of an optional, isolated Blender job bridge (experiment; standard library only).

Forge never imports bpy (Blender is GPL-3.0): every job runs Blender in a separate process with explicit files.

    python3 bridge.py run <job.json> --launcher bpy --exe <python-with-bpy>
    python3 bridge.py run <job.json> --launcher blender --exe <blender binary>
    python3 bridge.py version --launcher ... --exe ...

A job (see README.md) names one input file with its sha256, one operation with parameters, and an output name. The
runner:
  1. checks the launcher reports the pinned Blender version (fail closed);
  2. verifies the input checksum, creates a fresh job directory under --jobs-root, copies the input in read-only;
  3. runs job_blender.py in Blender with only that directory (input, output/, job.json), a timeout and a log;
  4. checks that Blender wrote only inside output/, hashes the outputs, and writes result.json with timings, peak
     memory (Linux/macOS), exit code and the Blender-side report.
Nothing is overwritten: each run gets a new directory. Forge-side validation of output GLBs is done by the caller
(see verify.py), not trusted from Blender.
"""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOB_SCRIPT = HERE / "job_blender.py"
PINNED_VERSION = "5.2.2"   # the version proposed for approval (bpy 5.2.2 / Blender 5.2.2); fail closed on anything else
OPERATIONS = ("inspect", "roundtrip", "simplify", "extract_region")
SCHEMA = "forge.blender-job"
SCHEMA_VERSION = 1


class BridgeError(RuntimeError):
    pass


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def command(launcher: str, exe: str, *args: str) -> list:
    if launcher == "blender":   # the Blender application: background mode, no user preferences or add-ons
        return [exe, "--background", "--factory-startup", "--python-exit-code", "3", "--python", *args[:1], "--", *args[1:]]
    if launcher == "bpy":       # Blender as a Python module (pip bpy) in its own interpreter / venv
        return [exe, "-I", *args]
    raise BridgeError(f"unknown launcher {launcher!r}")


def blender_version(launcher: str, exe: str) -> str:
    probe = "import bpy; print('BLENDER_VERSION', bpy.app.version_string)"
    cmd = [exe, "-I", "-c", probe] if launcher == "bpy" else [exe, "--background", "--factory-startup", "--python-expr", probe]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BridgeError(f"Blender not runnable: {e}") from e
    for line in r.stdout.splitlines():
        if line.startswith("BLENDER_VERSION "):
            return line.split()[1]
    raise BridgeError(f"no Blender version reported (exit {r.returncode}): {r.stderr[-500:]}")


def load_job(path) -> dict:
    job = json.loads(Path(path).read_text())
    if job.get("schema") != SCHEMA or job.get("schema_version") != SCHEMA_VERSION:
        raise BridgeError("not a forge.blender-job v1 document")
    if job.get("operation") not in OPERATIONS:
        raise BridgeError(f"operation must be one of {OPERATIONS}")
    out = job.get("output")
    if out is not None and (Path(out).name != out or not out.endswith(".glb")):
        raise BridgeError("output must be a bare .glb file name (written inside the job's output/ directory)")
    for k in ("input", "input_sha256"):
        if not job.get(k):
            raise BridgeError(f"missing {k}")
    return job


def _peak_rss_mb():
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return round(r / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except Exception:
        return None


def run(job_path, launcher, exe, jobs_root, timeout=1800, check_version=True, expect_version=PINNED_VERSION) -> dict:
    job = load_job(job_path)
    if Path(exe).exists():  # jobs run with the job directory as working directory: never pass a relative path on
        exe = str(Path(exe).absolute())  # not resolve(): a venv python is a symlink, and resolving it leaves the venv
    version = blender_version(launcher, exe) if check_version else None
    if check_version and version != expect_version:
        raise BridgeError(f"Blender {version} is not the expected {expect_version}")
    src = (Path(job_path).parent / job["input"]).resolve()
    if not src.is_file():
        raise BridgeError(f"input not found: {src}")
    if sha256(src) != job["input_sha256"]:
        raise BridgeError("input checksum does not match the job (source changed or wrong file)")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    Path(jobs_root).mkdir(parents=True, exist_ok=True)  # a fresh, uniquely named directory per run: nothing is overwritten
    jd = Path(tempfile.mkdtemp(prefix=f"{stamp}_{job['operation']}_{job['input_sha256'][:8]}_", dir=Path(jobs_root).resolve()))
    (jd / "output").mkdir()
    inp = jd / ("input" + src.suffix)
    shutil.copyfile(src, inp)
    os.chmod(inp, stat.S_IREAD)
    (jd / "job.json").write_text(json.dumps({**job, "input": inp.name}, indent=1))
    before = {p.name for p in jd.iterdir()}
    t0 = time.time()
    with open(jd / "blender.log", "w") as log:
        try:
            r = subprocess.run(command(launcher, exe, str(JOB_SCRIPT), str(jd / "job.json")), cwd=jd, stdout=log,
                               stderr=subprocess.STDOUT, timeout=timeout, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            code = r.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        except OSError as e:  # launcher vanished or not executable: a recorded failure, not a crash
            code = f"not runnable: {e}"
    res = {"schema": "forge.blender-job-result", "schema_version": 1, "job": job, "job_dir": str(jd), "launcher": launcher,
           "blender_version": version, "expected_version": expect_version, "exit_code": code, "seconds": round(time.time() - t0, 2), "peak_rss_mb": _peak_rss_mb()}
    stray = sorted({p.name for p in jd.iterdir()} - before - {"blender.log", "report.json"})
    res["unexpected_files"] = stray
    rep = jd / "output" / "report.json"
    res["report"] = json.loads(rep.read_text()) if rep.is_file() else None
    res["outputs"] = {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in sorted((jd / "output").iterdir()) if p.is_file()}
    res["input_unchanged"] = sha256(inp) == job["input_sha256"]
    res["ok"] = code == 0 and res["report"] is not None and res["report"].get("ok") is True and not stray and res["input_unchanged"]
    (jd / "result.json").write_text(json.dumps(res, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("run", "version"))
    ap.add_argument("job", nargs="?")
    ap.add_argument("--launcher", choices=("bpy", "blender"), required=True)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--jobs-root", default=str(HERE / "jobs"))
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--expect-version", default=PINNED_VERSION, help="exact Blender version required (recorded in result.json)")
    a = ap.parse_args()
    try:
        if a.cmd == "version":
            print(blender_version(a.launcher, a.exe))
            return 0
        res = run(a.job, a.launcher, a.exe, a.jobs_root, a.timeout, expect_version=a.expect_version)
    except BridgeError as e:
        print("BRIDGE ERROR:", e, file=sys.stderr)
        return 2
    print(json.dumps({k: res[k] for k in ("ok", "exit_code", "seconds", "peak_rss_mb", "outputs", "job_dir")}, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
