"""The design standard: one way to design everything a person sees, in two tiers (task 169).

‹Owner›, 7 November 2026: "can we setup our standard build process for anything, including gene
therapy, to be utilizing a design process that follows v2 full. Include corrected bb-local-design,
skill.md, craft, and always give the necessary journeys. One change I want to make though - only
need 1 single copy, not three." And, answering three questions: "1. Directly to production 2. Put
all instructions for small changes, just no need for loops 3. Yes ... Explainers should follow those
standards also."

Design test 3 (task 169, step 169-09) showed what closes the gap to Claude Design: the full brief
with the journeys, journeys before pages, the design guide, and looking at your own work. So:

- **Every agent is told it** (`for_runs`, after the agent instructions, from
  `agent_instructions.block`): the two tiers, chosen by the agent and never asked, one direction,
  journeys always derived and never asked for, the guide read at run time, and the record below.
- **Every build of Rouh's code is told it again in its brief** (`stage_section`, from
  `starting.start`, for gene therapy and every run that changes Rouh: the nightly feature run,
  growing a drafted gene, a case fix, the nightly refactoring, delegate_task).
- **Ask AI and the comment pass, which change a page in one model call**, are told the small tier
  (`FOR_PAGE_EDITS`): they have no browser to check with, and say so.
- **Landing checks it** (`check`: `land.sh`'s `design_guard`, and in the containers `bin/rouh-land`'s
  `design_check`, in the worker, before the work is handed to the protected core, since the record
  stays in the run's checkout): a change to the screen lands only
  with a clean design record (`tools/design/record.py`): every journey met, no fault at 1440 or
  390 px, and on the full tier a critic round with no blocker left.

**The guide is private and never in this code.** Anthropic's `craft.md` and the design rules of its
Design type's SKILL.md have no published licence: they are a private copy for the person's own
jobs, in the workspace's `.claude/skills/bb-local-design/reference/claude-design-type/`. Rouh is
going open source (task 130) and the Gene Pool shares genes, so neither file nor its text is in
this repository; agents read them where they are (`find_skill`), and without them fall back to
the Apache-licensed frontend-design skill and the rules written here, and say so.

This module is the standard library only, so `land.sh` can run its check from a bare copy.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: The two tiers. The agent picks one; ‹owner› is never asked which.
TIERS = ("full", "small")

#: Where the design skill lives in the person's workspace, the one home for it.
SKILL = ".claude/skills/bb-local-design"
#: Anthropic's design guide, private: read where it is, never copied.
PRIVATE_GUIDE = ("reference/claude-design-type/craft.md",
                 "reference/claude-design-type/design-rules-from-SKILL.md")
#: The fallback that may be shared (Apache License 2.0).
OPEN_GUIDE = "reference/frontend-design/frontend-design-SKILL.md"

#: What counts as the screen in Rouh's code: a change here is a change a person sees.
SCREEN_PATHS = ("rouh/static", "rouh/templates", "one/static", "one/templates")
#: Inside those, what a person never sees.
NOT_SCREEN = (".d.ts", ".md", ".map")

#: The record of a design, in a checkout (`tools/design/record.py`).
RECORD = ".design/record.json"

#: A commit line that says a change to the screen's files changes nothing a person sees.
NONE_LINE = "Design: none"

#: At most this many critic rounds on the full tier.
MOST_ROUNDS = 3

#: Measured aims for the full tier, per screen (task 169, test 3 and ‹owner›'s brief).
AIM = "about 45 to 60 minutes and about 15 dollars a screen"


# --- what agents are told ---------------------------------------------------------------------

FOR_AGENTS = f"""\
## Design: one standard for everything a person sees

Everything that you build or change that a person sees follows one design process. This includes a screen or page of Rouh, a gene's screen, a fix on a screen, and the pages of the workspace (visual explainers, task and step pages, research pages). It is "v2-full" from task 169 (design test 3, step 169-09), with one change from ‹owner›: make **one** design direction, never two or three. Make more only when ‹he› asks for more in ‹his› own words. A change that has no screen is not affected.

**Pick the tier yourself. Never ask ‹owner› which tier.**
1. **Full tier**, for a new screen or page, or one you rework (its structure, its navigation or one of its journeys changes):
   1. Journeys first. Before you build anything, write `journeys.md` in the person's words: where each journey starts, the question in the person's head, the data that answers it, the action, and a target such as "1 click, 5 s". Get the journeys from the request and the existing screens (5 to 8 for a screen). Never ask ‹owner› for them. If ‹he› named journeys, they are the spine, in ‹his› order and ‹his› words.
   2. Then the page structure (`ia.md`), the full brief (`brief.md`: what it is, who comes and how often, the journeys, the freedom to rethink the pages, the must-keep list, the style, the real counts and the settled words), and the awkward real states (`states.md`, MUST and SHOULD). Navigation, tab names and the page list are not fixed unless ‹owner› says so; data, data names, decision names and the must-keep items are.
   3. Build ONE direction as one self-contained HTML file, after you read the guide (below). Check it with the skill's `shoot.mjs` at 1440 and 390 px, dark and light, and fix what it finds.
   4. Critic rounds: one new helper (not a fork) per round, given the skill's `critic-prompt.md` word for word, with only the brief, journeys, states, the guide's paths and the screenshots. It judges journeys first and must-keep items second. Fix and repeat until a round finds no blocker, at most {MOST_ROUNDS} rounds.
   5. Write the handoff with tokens for both themes (`HANDOFF.md`). Then build it into the real code, prove it in the browser, and land it.
   Aim: {AIM}. Write down the time and the cost that you really used.
2. **Small tier**, for a change on an existing screen or page: a label, a button, a field, a fix. The same instructions in full, with NO critic loop: read the guide; write in `journeys.md` the journeys that the change touches, with their targets, and the must-keep items it touches; follow the existing look and tokens of the screen and do not restyle the rest; then check the changed screen at 1440 and 390 px, dark and light, and fix what the check finds.
3. Workspace pages (explainers, task and step pages, research pages) use the skill's own tiers for them, all with no critic loop.

**The guide, which you read at run time.** The design skill `bb-local-design` is in ‹owner›'s workspace, at `{SKILL}/`: its `SKILL.md`, `critic-prompt.md`, `brief-template.md`, scorecard, `shoot.mjs`, `fonts.conf` and `reference/`. In a checkout of Rouh's code, `python3 tools/design/record.py skill` finds it and says where it is. Read these each time, before you design: the skill's `SKILL.md`; Anthropic's design guide, `{PRIVATE_GUIDE[0]}` and `{PRIVATE_GUIDE[1]}`; `{OPEN_GUIDE}`; and `reference/extra-checks.md`.
- Anthropic's two guide files have no published licence. They are a private copy for our own jobs. Read them where they are. Never copy them or their text into Rouh's code, a commit, a gene, a page, a step's files, anything that the Gene Pool sends, or anything that is published or shared.
- If they are not there, use frontend-design and the rules in this section, and write in your report: "Design guide: not found, used frontend-design and Rouh's own rules."
- Use no leaked prompts. Make no Anthropic artifacts: the output is plain HTML in our own code and pages.

**Rules for every build.** One self-contained page that makes no network requests (no CDN, no Google Fonts). All data in one object, so every count agrees on every view. Tokens as CSS custom properties, for both themes. One accent colour. Semantic colours differ in lightness and come with a shape or a label, and are never the colour of a button or the brand. One primary button for each view. Each view starts with a headline sentence, then summary visuals, then detail. Real buttons, links and labelled inputs, touch targets of at least 44 px, and a visible focus. A designed empty state, never a blank box. It works at 390 px with no sideways scroll. No left-border cards, gradient washes or emoji.

**The record, which landing checks (Rouh's code).** In a checkout of Rouh's code, keep the record of the design with `tools/design/record.py`, in `.design/` (never committed; the design files of the full tier go there too, and in the task's step folder when the run has a task): `start --tier full|small --what "..."`, then `journey "<name>" --target "..." --met` (or `--missed`) for each journey, `designs <folder>` for the prototype of the full tier, `critic --round N --blockers K` after each critic round, `screens --url <test world> --user <login> --password <password> <each changed address>` after the real code is built (it checks the real screens at 1440 and 390 px, dark and light), and `cost --usd <amount>`. Landing (`./land.sh`, or `rouh-land` in the containers) does not push a change to the screen (`rouh/static/`, `rouh/templates/`, `one/static/`) when the record is missing, when a journey is missed, when the screen check found a fault (sideways scroll, cut text, a panel that covers the page, a page that draws almost nothing, a script error, a broken image, a request to another site), when a full-tier design has no critic round or still has blockers, or when the screen files changed after the check. A commit that changes those files but truly changes nothing that a person sees (types, comments, a refactor that the screenshot comparisons prove) says so with a line `{NONE_LINE} - <why>` in its own commit message; the line covers only that commit's files.

In your last message, say the tier, the journeys and whether each was met, the result of the check at both widths, the critic rounds (full tier), and the time and the cost."""

#: What a build of Rouh's code is told in its brief, after the standing text above.
BUILD_STAGE = f"""\
## Design

If this work changes anything a person sees, follow "Design: one standard for everything a person sees" in your instructions. Pick the tier yourself and do not ask: the full tier for a new or reworked screen (journeys first, one direction, critic rounds until no blocker is left, at most {MOST_ROUNDS}, then the handoff), and the small tier for a change on an existing screen (the same instructions, no critic loop). Keep the record with `tools/design/record.py` (`python3 tools/design/record.py skill` first): Landing reads it before it pushes a change to the screen. Then build it into the real code, prove it in the browser, and land it. Nobody approves it on the way. If nothing a person sees changes, this section does not apply."""

#: What Ask AI and the comment pass are told when they may change a page: the small tier.
FOR_PAGE_EDITS = (
    "\n\nA change to the page follows the design standard's small tier (task 169):\n"
    "- Work out the journey the reader's request serves: who comes to this part of the page and "
    "what they want to find or do there. Keep that journey quick and keep every journey the page "
    "already served working.\n"
    "- Keep what the page must keep: its recommendation, its numbers, its sources, any decision it asks for.\n"
    "- Follow the page's own look and tokens: its colours (its CSS custom properties), type, "
    "spacing, components and words. Do not restyle the rest. Make one version, not several.\n"
    "- It must still work at 390 px wide with no sideways scrolling and nothing cut off, and at "
    "1440 px, in dark and light. Semantic colours come with a label or a shape. Real buttons and "
    "links. No left-border cards, gradient washes or emoji.\n"
    "- You cannot look at the page in a browser here, so say in your reply which widths and "
    "themes your change may affect.")


def for_runs(org: str = "") -> str:
    """The section every agent is told after its agent instructions. Always on: it is how Rouh
    builds, not a gene with a switch."""
    return FOR_AGENTS


def stage_section(brief: str) -> str:
    """What a build of Rouh's code is told in its brief, or "" for a run that changes no code (a
    trial the person asked for, which is a report to read)."""
    try:
        from . import trials

        if trials.BY_HAND in brief:
            return ""
    except Exception:  # noqa: BLE001 - the design stage is never worth a build
        log.exception("design: could not read whether this is a trial by hand")
    return BUILD_STAGE


# --- where the skill is -----------------------------------------------------------------------


def _git(args: list[str], cwd: Path | str | None = None) -> tuple[int, str]:
    try:
        got = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return got.returncode, got.stdout


def _candidates(root: Path) -> list[Path]:
    out = []
    for env in ("ROUH_DESIGN_SKILL",):
        if os.environ.get(env):
            out.append(Path(os.environ[env]))
    out.append(root / SKILL)                     # a run in the workspace itself
    for env in ("ROUH_WORKSPACE", "ROUH_ASSISTANT_REPO"):
        if os.environ.get(env):
            out.append(Path(os.environ[env]) / SKILL)
    out.append(Path.home() / "workspace" / SKILL)  # the worker's checkout of the workspace
    return out


def find_skill(root: Path | str | None = None) -> dict:
    """Where the design skill is, whether Anthropic's private guide is beside it, and where it was
    looked for. When no checkout of the workspace holds it, it is read out of the workspace's own
    repository (`ONE_WORKSPACE_ORIGIN`, the worker's read-only copy) into `.design/skill/` of this
    checkout, which is never committed."""
    root = Path(root or os.getcwd())
    looked = []
    for p in _candidates(root):
        looked.append(str(p))
        if (p / "SKILL.md").is_file():
            return {"path": p, "guide": all((p / g).is_file() for g in PRIVATE_GUIDE),
                    "open": (p / OPEN_GUIDE).is_file(), "looked": looked}
    origin = os.environ.get("ONE_WORKSPACE_ORIGIN") or os.environ.get("ROUH_WORKSPACE_ORIGIN") \
        or "/workspace-origin/workspace.git"
    looked.append(f"{origin} (main)")
    if Path(origin).exists():
        into = root / ".design" / "skill"
        rc, listing = _git(["--git-dir", origin, "ls-tree", "-r", "--name-only", "main", "--", SKILL])
        if rc == 0 and listing.strip():
            for name in listing.split():
                rel = name[len(SKILL) + 1:]
                rc2, body = 0, b""
                try:
                    body = subprocess.run(["git", "--git-dir", origin, "show", f"main:{name}"],
                                          capture_output=True, timeout=60).stdout
                except (OSError, subprocess.SubprocessError):
                    rc2 = 1
                if rc2 == 0:
                    dest = into / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(body)
            (root / ".design").mkdir(exist_ok=True)
            (root / ".design" / ".gitignore").write_text("*\n", encoding="utf-8")
            if (into / "SKILL.md").is_file():
                return {"path": into, "guide": all((into / g).is_file() for g in PRIVATE_GUIDE),
                        "open": (into / OPEN_GUIDE).is_file(), "looked": looked}
    return {"path": None, "guide": False, "open": False, "looked": looked}


def skill_report(found: dict) -> str:
    if not found["path"]:
        return ("The design skill was not found (looked in: " + "; ".join(found["looked"]) + "). "
                "Design guide: not found, used frontend-design and Rouh's own rules (the Design section of "
                "your instructions). Say so in your report.")
    p = found["path"]
    lines = [f"The design skill: {p}",
             f"  read: {p / 'SKILL.md'}",
             f"  critic prompt: {p / 'critic-prompt.md'}",
             f"  screenshot check: {p / 'shoot.mjs'} (fonts: {p / 'fonts.conf'})"]
    if found["guide"]:
        lines.append("  Anthropic's design guide (private: read it here, never copy it or its text anywhere): "
                     + ", ".join(str(p / g) for g in PRIVATE_GUIDE))
    else:
        lines.append("  Design guide: not found, used frontend-design and Rouh's own rules. Say so in your report.")
    if found["open"]:
        lines.append(f"  frontend-design (Apache 2.0): {p / OPEN_GUIDE}")
    if (p / "reference" / "extra-checks.md").is_file():
        lines.append(f"  extra checks: {p / 'reference' / 'extra-checks.md'}")
    return "\n".join(lines)


# --- the screen's files -----------------------------------------------------------------------


def is_screen(path: str) -> bool:
    return any(path == s or path.startswith(s + "/") for s in SCREEN_PATHS) \
        and not path.endswith(NOT_SCREEN) and "/vendor/" not in path


def screen_files(root: Path | str, since: str = "origin/main") -> list[str]:
    """The screen's files this checkout changes from where it branched off `since`, committed or not."""
    root = Path(root)
    rc, base = _git(["merge-base", since, "HEAD"], root)
    base = base.strip() if rc == 0 else since
    _, changed = _git(["diff", "--name-only", base, "--", *SCREEN_PATHS], root)
    _, new = _git(["ls-files", "--others", "--exclude-standard", "--", *SCREEN_PATHS], root)
    return sorted({p for p in (changed.split() + new.split()) if is_screen(p)})


def blobs_now(root: Path | str, files: list[str]) -> dict:
    """Each file's git blob as it is on disk now: what the commit about to be pushed must hold."""
    root = Path(root)
    out = {}
    for f in files:
        if not (root / f).exists():
            out[f] = "deleted"
            continue
        _, sha = _git(["hash-object", f], root)
        out[f] = sha.strip()
    return out


# --- the check before landing -----------------------------------------------------------------


def summary(rec: dict) -> str:
    j = rec.get("journeys") or []
    met = sum(1 for x in j if x.get("met"))
    s = rec.get("screens") or {}
    rounds = rec.get("critic") or []
    took = ""
    if rec.get("started"):
        took = f", {round((time.time() - rec['started']) / 60)} min so far"
    cost = f", ${rec['cost_usd']:.2f}" if rec.get("cost_usd") is not None else ""
    lines = [f"Design ({rec.get('tier')} tier): {rec.get('what', '')}{took}{cost}",
             f"  guide: {rec.get('guide', '?')} ({rec.get('skill') or 'no skill found'})",
             f"  journeys: {met} of {len(j)} met" + "".join(
                 f"\n    {'met   ' if x.get('met') else 'MISSED'} {x['name']} ({x.get('target', '')})" for x in j)]
    for d in rec.get("designs") or []:
        lines.append(f"  prototype check ({d['folder']}): {'clean' if d.get('ok') else 'FAULTS: ' + '; '.join(d.get('faults', [])[:4])}")
    for c in rounds:
        lines.append(f"  critic round {c['round']}: {c['blockers']} blocker(s)")
    if s:
        lines.append(f"  screens: {s.get('faults', 0)} fault(s), {len(s.get('pages') or {})} page(s) at 1440 and 390 px, dark and light")
    else:
        lines.append("  screens: not checked yet")
    return "\n".join(lines)


def check(repo: Path | str, before: str, after: str, record: Path | str | None = None) -> tuple[bool, str]:
    """Whether a change may land as far as its design goes, and the sentence that says why."""
    repo = Path(repo)
    rc, out = _git(["diff", "--name-only", before, after, "--", *SCREEN_PATHS], repo)
    if rc != 0:
        return True, "the design check could not read what changed, so it did not stop the landing"
    changed = [p for p in out.split() if is_screen(p)]
    if not changed:
        return True, "the design check: no screen changed"
    # A "Design: none" line covers only the screen files of its own commit (test run t-full, 7 November
    # 2026: one such line in any commit had let every screen change in the landing through).
    _, shas = _git(["rev-list", f"{before}..{after}"], repo)
    needs, said = set(), ""
    for sha in shas.split():
        _, body = _git(["log", "-1", "--format=%B", sha], repo)
        _, files = _git(["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha], repo)
        line = next((ln.strip() for ln in body.splitlines() if ln.strip().startswith(NONE_LINE)), "")
        if line:
            said = said or line
        else:
            needs |= {f for f in files.split() if f in changed}
    if not needs:
        return True, f"the design check: {len(changed)} screen file(s) changed, each in a commit that says \"{said[:160]}\""
    changed = sorted(needs)
    path = Path(record) if record else repo / RECORD
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    first = changed[0]
    how = ("Follow the Design section of your instructions and keep the record with tools/design/record.py "
           "(start, journey, screens, and critic on the full tier), or, if nothing a person sees changes, say so in a "
           f"commit message line \"{NONE_LINE} - <why>\".")
    if not rec.get("tier"):
        return False, f"this changes the screen ({first}) and there is no design record in {RECORD}. {how}"
    wrong = []
    journeys = rec.get("journeys") or []
    if not journeys:
        wrong.append("no journey is written down")
    missed = [x["name"] for x in journeys if not x.get("met")]
    if missed:
        wrong.append("journeys missed: " + ", ".join(missed))
    screens = rec.get("screens") or {}
    if not screens:
        wrong.append("the screens were not checked at 1440 and 390 px (record.py screens)")
    elif screens.get("faults"):
        bad = []
        for page, views in (screens.get("pages") or {}).items():
            for view, got in views.items():
                for f in got.get("faults") or []:
                    bad.append(f"{page} {view}: {f}")
        wrong.append(f"the screen check found {screens['faults']} fault(s), the first: " + (bad[0][:240] if bad else "?"))
    if rec.get("tier") == "full":
        rounds = rec.get("critic") or []
        if not rounds:
            wrong.append("the full tier has no critic round")
        elif rounds[-1].get("blockers", 1):
            wrong.append(f"critic round {rounds[-1]['round']} left {rounds[-1]['blockers']} blocker(s)")
        designs = rec.get("designs") or []
        if not designs:
            wrong.append("the full tier's prototype was never checked with shoot.mjs (record.py designs)")
        elif not designs[-1].get("ok"):
            wrong.append("the prototype's last shoot.mjs check had faults")
    if screens:
        files = rec.get("files") or {}
        stale = []
        for f in changed:
            rc, sha = _git(["rev-parse", f"{after}:{f}"], repo)
            now = sha.strip() if rc == 0 else "deleted"
            if files.get(f) != now:
                stale.append(f)
        if stale:
            wrong.append(f"{len(stale)} screen file(s) changed after the screen check, the first {stale[0]}: run record.py screens again")
    if wrong:
        return False, f"this changes the screen ({first}) and its design record does not pass: " + "; ".join(wrong) + ". " + how
    j = len(journeys)
    tail = f", {len(rec.get('critic') or [])} critic round(s), no blocker left" if rec.get("tier") == "full" else ""
    return True, (f"the design check ({rec['tier']} tier): {j} journey(s) met, no fault at 1440 or 390 px{tail}")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="The design check before a landing (land.sh, design_guard).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--repo", required=True)
    c.add_argument("--before", required=True)
    c.add_argument("--after", default="HEAD")
    c.add_argument("--record", default="")
    sub.add_parser("text")
    a = ap.parse_args(argv)
    if a.cmd == "text":
        print(FOR_AGENTS)
        return 0
    ok, said = check(a.repo, a.before, a.after, a.record or None)
    print(said)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BUILD_STAGE", "FOR_AGENTS", "FOR_PAGE_EDITS", "SCREEN_PATHS", "TIERS", "blobs_now", "check",
           "find_skill", "for_runs", "is_screen", "screen_files", "skill_report", "stage_section", "summary"]
