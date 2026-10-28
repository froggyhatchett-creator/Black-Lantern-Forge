"""Read-only Mercy profile report. Standard library only; never writes to the profile.

  python tools/profile_report.py                     # default profile, summary + fingerprints
  python tools/profile_report.py --diagnose          # explain non-complete turns (timed_out, failed, ...)
  python tools/profile_report.py --json before.json  # save for a before/after upgrade comparison

Close Mercy first for a perfectly consistent snapshot. The database is opened with mode=ro.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def default_profile():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "BlackLantern/Mercy-v02"
    return Path.home() / ".local/share/black-lantern-mercy-v02"


def digest(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(list(row), ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:16]


def classify(turn, audits):
    """Plain-language cause for a turn that did not complete."""
    kinds = [(a.get("error"), a.get("authorization"), a.get("execution"), a.get("capability")) for a in audits]
    if any(e == "DeadlineExceeded" for e, *_ in kinds):
        return "DEADLINE reached while a tool step / permission prompt was pending (shown to the model as 'Capability rejected or failed')"
    rejected = [k for k in kinds if k[0] == "ValueError" and k[1] == "not_requested"]
    if rejected:
        return ("TOOL REQUEST REJECTED by Mercy's validation before any permission prompt (malformed or argument-bearing call from the model/backend); "
                "the model then saw 'Capability rejected or failed'")
    if any(k[1] == "denied" for k in kinds):
        return "USER (or harness) DENIED the permission prompt"
    if any(k[2] == "failed" for k in kinds):
        return "A capability FAILED during execution: " + ", ".join(str(k[0]) for k in kinds if k[2] == "failed")
    if turn["state"] == "timed_out":
        return "INFERENCE/GENERATION deadline reached with no tool activity (backend too slow for generation_timeout)"
    if turn["state"] == "cancelled":
        return "Cancelled by the user"
    if turn["state"] == "interrupted":
        return "Application stopped mid-turn"
    return "PROVIDER error: " + str(turn["error"])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles are cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, default=default_profile())
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    db_path = a.profile / "mercy.sqlite3"
    if not db_path.exists():
        print("No database at", db_path)
        return 2
    db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    report = {"profile": str(a.profile), "schema": db.execute("PRAGMA user_version").fetchone()[0]}
    for table in ("conversations", "messages", "turns", "memories", "audit"):
        report[table] = db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
    report["messages_fingerprint"] = digest(db.execute("SELECT id, role, content, state FROM messages ORDER BY id"))
    report["memories_fingerprint"] = digest(db.execute("SELECT id, content FROM memories ORDER BY id"))
    for name in ("identity.json", "config.json"):
        p = a.profile / name
        report[name + "_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
    cfg = a.profile / "config.json"
    report["config"] = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else None
    report["turn_states"] = {r[0]: r[1] for r in db.execute("SELECT state, COUNT(*) FROM turns GROUP BY state")}
    print(json.dumps(report, indent=2))
    if a.diagnose:
        print("\n--- turns that did not complete, or whose tool request failed (most recent first) ---")
        failed_ids = {r[0] for r in db.execute("SELECT turn_id, data FROM audit WHERE turn_id IS NOT NULL")
                      if json.loads(r[1]).get("execution") == "failed"}
        bad = [t for t in db.execute("SELECT * FROM turns ORDER BY started DESC")
               if t["state"] != "complete" or t["id"] in failed_ids][:a.limit]
        if not bad:
            print("none")
        for t in bad:
            audits = [json.loads(r["data"]) for r in db.execute("SELECT data FROM audit WHERE turn_id=? ORDER BY id", (t["id"],))]
            reply = db.execute("SELECT content FROM messages WHERE turn_id=? AND role='assistant'", (t["id"],)).fetchone()
            print("\nturn %s  state=%s  provider=%s  started=%s  ended=%s" % (t["id"][:8], t["state"], t["provider"], t["started"], t["ended"]))
            print("  cause:", classify(t, audits))
            print("  assistant text:", (reply[0] if reply else "")[:160].replace("\n", " "))
            for au in audits:
                print("  audit:", {k: au[k] for k in ("event", "capability", "authorization", "execution", "error") if k in au})
    if a.json:
        a.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("\nSaved", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
