"""One answer to "what is going on with job X", for the chat tool `job_status`.

Petar, 20 November 2026 (task 182): "you can make a tool for status - that's fine." Checking
one job had taken about eight round trips that week - `check_tasks`, `look_at_task`,
`read_task_log`, `what_task_changed`, a tool search or two and a read of the wrong folder - and
still missed the one thing that mattered: a run Rouh had been told was "called over" had in
fact finished and was live.

So this puts together, for one job or one run of the one program, in a few plain lines:

- its state, with when it started, last moved and ended;
- a question it waits on, word for word, with its choices;
- the last lines of its screen, or of its history when the screen is gone;
- what it changed: each commit with its message, whether it is on main and whether the build
  Rouh is running has it, and the files it touched;
- its final report;
- and, when Rouh was told its turn was called over (or that it died or failed) while it in fact
  carried on and finished, that mismatch, said plainly.

The tool handler in `rouh/tools.py` (`_job_status`) fetches what only it can reach - the
register's rows, the one program's answer, a worker's screen - and hands it here. Everything
here is plain functions of what it is given, plus git and the landing record, so it is the
same answer whoever asks.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import clock, gitutil

#: How many lines of a screen or a history are given back.
SCREEN_LINES = 12
#: How many commits and files are named before the rest are counted.
MOST_COMMITS = 8
MOST_FILES = 10
#: How much of a final report is given back.
REPORT_CHARS = 900

#: The states of a job that is over.
OVER = ("done", "failed", "killed", "lost", "stopped", "unfinished", "refused", "reaped")
#: Open and busy, so the newest of these is "the job" when none is named.
BUSY = ("running", "starting", "waiting", "saving", "queued")

_HEX = re.compile(r"^[0-9a-f]{4,40}$")


# --- which job ---------------------------------------------------------------------------------


def _newest_first(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
                  reverse=True)


def pick(rows: list[Mapping[str, Any]], wanted: str, chat: str = "",
         me: str = "") -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]:
    """The job asked about, and the others that matched as well (newest first).

    By id or its first characters first, then by title (every word asked appearing in it, any
    case). With nothing asked: the newest busy job started from this chat, else the newest job
    from this chat, else the newest busy job anywhere, else the newest job. `me` is the job
    asking, when a job asks, and is never its own answer unless named.
    """
    rows = [r for r in _newest_first(rows) if str(r.get("id") or "")]
    wanted = " ".join(str(wanted or "").split())
    if wanted:
        low = wanted.lower()
        by_id = [r for r in rows if str(r["id"]).lower().startswith(low)] if _HEX.match(low) or \
            len(low) >= 4 and " " not in low else []
        if by_id:
            return by_id[0], by_id[1:]
        words = [w for w in re.split(r"\W+", low) if w]
        by_title = [r for r in rows if words and all(w in str(r.get("title") or "").lower()
                                                     for w in words)]
        if by_title:
            busy = [r for r in by_title if r.get("status") in BUSY]
            first = (busy or by_title)[0]
            return first, [r for r in by_title if r is not first]
        return None, []
    rows = [r for r in rows if str(r["id"]) != me] or rows
    here = [r for r in rows if chat and r.get("chat") == chat]
    for pool in (here, rows):
        busy = [r for r in pool if r.get("status") in BUSY]
        if busy:
            return busy[0], []
        if pool:
            return pool[0], []
    return None, []


# --- what it changed ---------------------------------------------------------------------------


def _git(where: str, *args: str) -> tuple[int, str]:
    if not where or not Path(where).exists():
        return 1, ""
    try:
        done = gitutil.run(where, *args, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout


def landings_of(run_id: str, land_dir: str) -> list[tuple[float, list[str]]]:
    """Each landing of this run's code, as `land.sh` and the core write it down (`landed.tsv`):
    when, and the commits it put on main, oldest first."""
    out: list[tuple[float, list[str]]] = []
    path = Path(land_dir or "/srv/rouh-land") / "landed.tsv"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        bits = line.split("\t")
        if len(bits) == 3 and bits[1] == run_id:
            try:
                at = float(bits[0])
            except ValueError:
                at = 0.0
            out.append((at, bits[2].split()))
    return out


def _on_main(where: str, sha: str) -> bool | None:
    """Whether the commit is on main: on either `main` or `origin/main`, because in Rouh's own
    code (`/code`) `main` is the live line and `origin/main` an old leftover, and in a clone of
    the workspace it can be the other way round. None when neither ref is there."""
    found = False
    for ref in ("main", "origin/main"):
        rc, _ = _git(where, "rev-parse", "--verify", "--quiet", ref)
        if rc != 0:
            continue
        found = True
        rc, _ = _git(where, "merge-base", "--is-ancestor", sha, ref)
        if rc == 0:
            return True
    return False if found else None


def shas_in(text: str) -> list[str]:
    """Commit ids a job named in its own words, such as its final report. Only a guess until
    `commit_facts` finds them, so they are passed to it as `maybe` and dropped when not found."""
    return list(dict.fromkeys(re.findall(r"(?<![0-9a-zA-Z])[0-9a-f]{7,40}(?![0-9a-zA-Z])",
                                         str(text or ""))))[:12]


def commit_facts(shas: Iterable[str], repos: list[str], running_sha: str = "",
                 code_repo: str = "", maybe: Iterable[str] = ()) -> list[dict]:
    """Each commit as it is in whichever of `repos` has it: its message, its files, whether it
    is on main, and - in Rouh's own code, `code_repo` - whether the build running has it.

    `maybe` are ids read out of a job's own words: kept only when a repository has them.
    """
    out, seen = [], set()
    recorded = [str(s or "").strip() for s in shas]
    guessed = [s for s in maybe if not any(r.startswith(s) or s.startswith(r)
                                           for r in recorded if r)]
    shas = recorded + guessed
    guessed_set = set(guessed)
    for sha in shas:
        sha = str(sha or "").strip()
        if not sha or sha in seen:
            continue
        seen.add(sha)
        fact: dict[str, Any] = {"sha": sha[:7]}
        for where in repos:
            rc, said = _git(where, "show", "-s", "--format=%h%x09%s%x09%cI", sha)
            if rc != 0 or not said.strip():
                continue
            short, subject, when = (said.strip().split("\t") + ["", ""])[:3]
            fact.update(sha=short, subject=subject, at=when, repo=where)
            _, names = _git(where, "show", "--name-only", "--format=", sha)
            fact["files"] = [n for n in names.splitlines() if n.strip()]
            fact["on_main"] = _on_main(where, sha)
            if where == code_repo and running_sha:
                rc, _ = _git(where, "merge-base", "--is-ancestor", sha, running_sha)
                fact["live"] = rc == 0
            break
        if sha in guessed_set and not fact.get("subject"):
            continue
        out.append(fact)
    return out


# --- a notice that said it was over when it was not ---------------------------------------------


def _hm(value: Any) -> str:
    """'13:21' today, '15 November 13:21' on another day, on the person's clock."""
    moment = clock.moment(value)
    if moment is None:
        return "?"
    if moment.date() == clock.now().date():
        return moment.strftime("%H:%M")
    return f"{moment.day} {moment.strftime('%B %H:%M')}"


def _at(value: Any) -> float | None:
    moment = clock.moment(value) if value not in (None, "") else None
    return moment.timestamp() if moment else None


def one_mismatch(entries: list[Mapping[str, Any]], run: Mapping[str, Any],
                 landed_at: Iterable[float] = ()) -> str:
    """A run of the one program whose turn was called over while it went on, or had finished.

    The program calls a turn over when what it paused on never reported (`agent.pause-ended`),
    and Rouh is then told "its turn was called over ... it did not finish". Two ways that is
    wrong, both seen this week: the run carried on afterwards and finished (a later turn, a
    landing, a good end), or its work had already landed before the notice came.
    """
    calls = [e for e in entries if e.get("kind") == "agent.pause-ended"]
    if not calls:
        return ""
    last = calls[-1]
    t = _at(last.get("at")) or 0.0
    why = " ".join(str((last.get("body") or {}).get("why") or "nothing woke it").split())
    # "nothing came back from <a shell command> in 75 minutes": the command says nothing to a person.
    why = re.sub(r"^nothing came back from .+ in (\d+ \w+)$",
                 r"nothing it was waiting on came back in \1", why)[:120]
    later_turn = next((e for e in entries if (_at(e.get("at")) or 0) > t
                       and e.get("kind") == "agent.stopped"
                       and not (e.get("body") or {}).get("paused")), None)
    later_land = next((e for e in entries if (_at(e.get("at")) or 0) > t
                       and e.get("kind") == "work.landed"), None)
    ended_ok = next((e for e in entries if e.get("kind") == "run.ended"
                     and (e.get("body") or {}).get("ok")), None)
    landed = sorted(a for a in landed_at if a)
    landed_before = [a for a in landed if a <= t]
    head = (f"Rouh was told at {_hm(last.get('at'))} that this run's turn was called over "
            f"({why})")
    if later_turn or later_land:
        what = later_land or later_turn
        return (f"{head}, but the run carried on and finished afterwards: "
                f"{'its work landed' if later_land else 'it ended its turn'} at "
                f"{_hm(what.get('at'))}. The notice was wrong; it did not stop there.")
    if landed_before or (ended_ok and run.get("succeeded_at")):
        bits = []
        if landed_before:
            bits.append(f"its work had already landed at {_hm(landed_before[-1])}")
        if ended_ok:
            bits.append(f"it ended well at {_hm(ended_ok.get('at'))}")
        return (f"{head}, but " + " and ".join(bits) + ". The notice was about a background "
                "wait it left behind, not about its work: the work was finished.")
    return ""


def crew_mismatch(meta: Mapping[str, Any], status: str) -> str:
    """A worker Rouh reported as died or failed that is done after all."""
    reported = str((meta or {}).get("reported") or "")
    if status == "done" and (reported == "lost" or reported.startswith("failed:")):
        word = "died" if reported == "lost" else "failed"
        return (f"Rouh was told this job {word}, but it is done now: it carried on and finished "
                "afterwards. The earlier notice was wrong.")
    return ""


# --- the answer --------------------------------------------------------------------------------


def _when(value: Any) -> str:
    if not value:
        return ""
    return f"{_hm(value)} ({clock.ago(value)})"


def _tail(text: str, n: int = SCREEN_LINES) -> list[str]:
    lines = [ln.rstrip() for ln in str(text or "").splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return [ln[:200] for ln in lines if ln.strip()][-n:]


def render(row: Mapping[str, Any], *, others: list[Mapping[str, Any]] = (),
           question: str = "", choices: list[str] = (), screen: str = "",
           screen_kind: str = "screen", report: str = "", commits: list[dict] = (),
           files: list[str] = (), landing_notes: list[str] = (), uncommitted: list[str] = (),
           mismatch: str = "", running_sha: str = "", extra: list[str] = ()) -> str:
    """The answer, in short plain lines. Sections with nothing in them are left out."""
    where = "one-program run" if row.get("owner") == "one" or row.get("mode") == "one" else "job"
    status = str(row.get("status") or "unknown")
    lines = [f"{where.capitalize()} {row.get('id')}, \"{row.get('title') or 'Untitled'}\": "
             f"{status.upper()}" + (f", exit code {row['exit_code']}"
                                    if row.get("exit_code") not in (None, 0) else "") + "."]
    times = [(w, row.get(k)) for w, k in (("started", "created_at"), ("last moved", "updated_at"),
                                          ("ended", "finished_at"))]
    lines += [f"- {w}: {_when(v)}" for w, v in times if v]
    if status == "idle":
        lines.append("- Its turn is over and it waits at its prompt; reply_to_task carries it on.")
    if mismatch:
        lines.append(f"NOTE: {mismatch}")
    if question:
        lines.append(f"Waiting on: {question}")
        if choices:
            lines.append("Choices: " + " | ".join(choices))
    for line in extra:
        lines.append(line)
    if commits or files or landing_notes or uncommitted:
        lines.append("What it changed:")
        for c in list(commits)[:MOST_COMMITS]:
            state = []
            if c.get("on_main") is True:
                state.append("on main")
            elif c.get("on_main") is False:
                state.append("NOT on main")
            if "live" in c:
                state.append("in the build running" if c["live"]
                             else f"NOT yet in the build running ({running_sha[:7] or '?'})")
            subject = c.get("subject") or "(commit not found here)"
            lines.append(f"- {c['sha']} {subject}" + (f" [{', '.join(state)}]" if state else ""))
        if len(commits) > MOST_COMMITS:
            lines.append(f"- and {len(commits) - MOST_COMMITS} more commits")
        lines += [f"- {n}" for n in landing_notes]
        named = list(dict.fromkeys(files))
        if named:
            shown = ", ".join(named[:MOST_FILES])
            more = f", and {len(named) - MOST_FILES} more" if len(named) > MOST_FILES else ""
            lines.append(f"- Files ({len(named)}): {shown}{more}")
        if uncommitted:
            lines.append(f"- Left uncommitted ({len(uncommitted)}): "
                         + ", ".join(u.strip() for u in uncommitted[:6]))
    elif status in OVER:
        lines.append("What it changed: no commit or landing of it is on record here.")
    if report:
        lines.append("Final report: " + report.strip()[:REPORT_CHARS])
    tail = _tail(screen)
    if tail:
        lines.append(f"Last lines of its {screen_kind}:")
        lines += [f"  {ln}" for ln in tail]
    if others:
        lines.append("Also matched: " + "; ".join(
            f"{o.get('id')} \"{o.get('title')}\" ({o.get('status')})" for o in list(others)[:4]))
    return "\n".join(lines)
