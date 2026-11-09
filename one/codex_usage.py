"""The Codex sessions a run started inside itself, counted for the run's page.

Petar, 9 November 2026 (task 178): two runs of Claude Code called `codex exec -m
gpt-6-astra` inside themselves. Eight Codex sessions spent the ChatGPT plan's five-hour
window and ended "Your workspace is out of credits", and none of it showed anywhere.
A request for an OpenAI model now starts Codex itself (`rouh/codex_route.py`); this is
for the run that still calls Codex inside, and for a run of Codex itself.

Codex keeps every session as a rollout file under ``~/.codex/sessions/YYYY/MM/DD/``.
Its first line, ``session_meta``, says the folder it worked in (``cwd``). A session whose
folder is the run's own folder, or inside it, is that run's. From each one this reads:

* the turns (``task_started``), the model (``turn_context``),
* the tokens, from the last ``token_count``'s running total,
* the plan (``rate_limits.plan_type``) and the two windows, five hours (``primary``)
  and a week (``secondary``), each with how much is used and when it resets,
* and whether it stopped on the plan's limit ("out of credits", ``usage_limit_exceeded``).

Nothing here writes anything, and a file that cannot be read is left out, never guessed.
Each file is read once for each size it has, so a page asked for again costs a ``stat``.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: A file read, by its path, with the size and time it had: (size, mtime, what it said).
_READ: dict[str, tuple[int, float, dict[str, Any] | None]] = {}

#: How many day folders before the run started are looked in, for a clock on another zone.
_DAYS_BEFORE = 1

#: The words Codex ends a turn with when the plan has nothing left.
OUT_OF_CREDITS = "usage_limit_exceeded"


def sessions_root(home: str) -> Path:
    return Path(home or str(Path.home())) / ".codex" / "sessions"


def _inside(cwd: str, folder: str) -> bool:
    cwd, folder = cwd.rstrip("/"), folder.rstrip("/")
    return bool(folder) and (cwd == folder or cwd.startswith(folder + "/"))


def _day_folders(root: Path, since: float | None) -> list[Path]:
    """The day folders worth reading: from the day before the run began, or all of them."""
    if since is None:
        return sorted(p for p in root.glob("*/*/*") if p.is_dir())
    first = datetime.fromtimestamp(since, timezone.utc).date() - timedelta(days=_DAYS_BEFORE)
    today = datetime.now(timezone.utc).date() + timedelta(days=1)
    out, day = [], first
    while day <= today:
        folder = root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if folder.is_dir():
            out.append(folder)
        day += timedelta(days=1)
    return out


def _cwd_of(path: Path) -> str:
    """The folder a session worked in, from its first line, or ""."""
    try:
        with path.open("rb") as f:
            first = f.readline(1 << 20)
        meta = json.loads(first)
    except (OSError, ValueError):
        return ""
    if not isinstance(meta, dict) or meta.get("type") != "session_meta":
        return ""
    return str((meta.get("payload") or {}).get("cwd") or "")


def _window(said: Any) -> dict[str, Any] | None:
    if not isinstance(said, dict):
        return None
    return {"used_percent": said.get("used_percent"),
            "window_minutes": said.get("window_minutes"),
            "resets_at": said.get("resets_at")}


def read_session(path: Path) -> dict[str, Any] | None:
    """One rollout file, counted, or None when it is not a session that can be read."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    kept = _READ.get(key)
    if kept is not None and kept[0] == st.st_size and kept[1] == st.st_mtime:
        return kept[2]
    out: dict[str, Any] | None = {
        "file": path.name, "session": "", "cwd": "", "originator": "", "model": "",
        "turns": 0, "tokens": {}, "plan_type": "", "limits": None, "limits_at": "",
        "started_at": "", "last_at": "", "out_of_credits": False, "error": "",
    }
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                at = str(item.get("timestamp") or "")
                if at:
                    out["started_at"] = out["started_at"] or at
                    out["last_at"] = at
                kind, body = item.get("type"), item.get("payload")
                if not isinstance(body, dict):
                    continue
                if kind == "session_meta":
                    out["session"] = str(body.get("id") or body.get("session_id") or "")
                    out["cwd"] = str(body.get("cwd") or "")
                    out["originator"] = str(body.get("originator") or "")
                elif kind == "turn_context":
                    out["model"] = str(body.get("model") or out["model"])
                elif kind == "event_msg":
                    what = body.get("type")
                    if what == "task_started":
                        out["turns"] += 1
                    elif what == "token_count":
                        info = body.get("info")
                        if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                            out["tokens"] = dict(info["total_token_usage"])
                        limits = body.get("rate_limits")
                        if isinstance(limits, dict):
                            out["plan_type"] = str(limits.get("plan_type") or out["plan_type"])
                            # A window Codex stopped saying (as it does once the plan is
                            # spent) keeps what it last said, rather than turning to nothing.
                            was = out["limits"] or {}
                            out["limits"] = {
                                "primary": _window(limits.get("primary")) or was.get("primary"),
                                "secondary": (_window(limits.get("secondary"))
                                              or was.get("secondary")),
                                "reached": limits.get("rate_limit_reached_type") or None}
                            out["limits_at"] = at
                    elif what in ("task_complete", "error", "stream_error"):
                        err = body.get("error") if what == "task_complete" else body
                        if isinstance(err, dict) and (err.get("message") or err.get("codex_error_info")):
                            out["error"] = str(err.get("message") or "")[:300]
                            info = err.get("codex_error_info")
                            if info == OUT_OF_CREDITS or "out of credits" in out["error"].lower():
                                out["out_of_credits"] = True
    except OSError:
        out = None
    if out is not None and not out["cwd"]:
        out = None
    _READ[key] = (st.st_size, st.st_mtime, out)
    return out


def for_run(folder: str, *, home: str = "", since: float | None = None,
            root: Path | None = None) -> dict[str, Any] | None:
    """Every Codex session that worked in `folder` or under it, and their sum, or None.

    `since` is when the run began (epoch seconds), so only the day folders from then are
    looked in. The plan's windows are the newest any of its sessions saw.
    """
    if not folder:
        return None
    root = root or sessions_root(home)
    if not root.is_dir():
        return None
    sessions: list[dict[str, Any]] = []
    for day in _day_folders(root, since):
        for path in sorted(day.glob("rollout-*.jsonl")):
            if not _inside(_cwd_of(path), folder):
                continue
            got = read_session(path)
            if got is not None:
                sessions.append(got)
    if not sessions:
        return None
    sessions.sort(key=lambda s: s["started_at"])
    total: dict[str, int] = {}
    for s in sessions:
        for name, value in (s["tokens"] or {}).items():
            if isinstance(value, int):
                total[name] = total.get(name, 0) + value
    newest = max((s for s in sessions if s["limits"]), key=lambda s: s["limits_at"], default=None)
    models = sorted({s["model"] for s in sessions if s["model"]})
    return {
        "sessions": [{k: v for k, v in s.items() if k != "limits_at"} for s in sessions],
        "count": len(sessions),
        "turns": sum(s["turns"] for s in sessions),
        "tokens": total,
        "models": models,
        "plan_type": newest["plan_type"] if newest else "",
        "limits": newest["limits"] if newest else None,
        "limits_at": newest["limits_at"] if newest else "",
        "out_of_credits": any(s["out_of_credits"] for s in sessions),
        "error": next((s["error"] for s in reversed(sessions) if s["error"]), ""),
        "read_at": time.time(),
    }


def requested_epoch(run: dict[str, Any]) -> float | None:
    """When a run began, as epoch seconds, from the program's ISO times."""
    for name in ("requested_at", "started_at"):
        said = run.get(name)
        if isinstance(said, (int, float)):
            return float(said)
        if isinstance(said, str) and said:
            try:
                return datetime.fromisoformat(said.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def run_folder(run: dict[str, Any]) -> str:
    """The folder a run's sessions work under: its checkout, as `/home/rouh/runs/<id>`."""
    cwd = str(run.get("cwd") or "")
    return os.path.normpath(cwd) if cwd else ""
