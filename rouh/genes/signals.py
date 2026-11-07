"""How a gene says it was used: its use signals, declared in one place, and the check that holds them
(GENES.md, "How a gene says it was used").

Petar, 19 October 2026: a gene's trial counted uses from a mix of places, and the box "Its own code
saying you used it" was offered, ticked, on genes whose code never said anything, so it could never
count. And the same evening: opening a page, pressing a link or Rouh calling a tool is not using a
gene. So the only use that counts is the gene's own report of one. Every gene with a switch
declares, under `"signals"` in its manifest, or in its entry in `owners.json` when it has no
manifest, the named points in its code where the person used it, each with one plain line of what
the person did:

    "signals": {
      "events": {"page_pdf": "You pressed PDF in a page's Share menu"},
      "runs":   {"read": "Rouh read the mail with a meeting's guests and said what to raise"}
    }

`events` are what its trial counts, and it needs at least one. `runs` are points where it acted by
itself: they count for nothing and only say its moment came. A gene that is about visiting a page
reports that visit from its page's code, as one of its events. Its code reports both through one
function, `evolution.used("<switch>", "<event>", who=..., detail=...)`, with the switch and the
event written out (the switch may be the module's `SWITCH`), so this check can read them.

`python -m rouh.genes.signals` fails, naming each problem, when a gene with a switch declares no
event, a declaration is not this shape, a declared event or run is never reported anywhere in
Rouh's code, or the code reports an event its gene does not declare. `land.sh` runs it before it
pushes Rouh's Python or the gene registry (`signals_guard`). At run time an undeclared event is
logged as a fault and not counted (`evolution.used`).

Standard library only, so a landing can run it from a bare copy of the commit it is about to push.
"""
from __future__ import annotations

import ast
import json
import sys
from functools import lru_cache
from pathlib import Path

# The shape of a declaration is the registry's, so a manifest is refused by `python -m rouh.genes` too.
from . import SIGNAL_KINDS as KINDS, SIGNALS_IN_CODE as CODE, signal_problems as shape_problems

HERE = Path(__file__).resolve().parent


def _json(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def genes(folder: Path = HERE) -> dict[str, dict]:
    """Every gene that has a switch: {key: {switch, signals, core, where}}, from the manifests and
    from the genes in `owners.json` that have none."""
    out: dict[str, dict] = {}
    for path in sorted((folder / "manifests").glob("*.json")):
        m = _json(path)
        if m.get("id") and m.get("switch"):
            out[m["id"]] = {"switch": m["switch"], "signals": m.get("signals"),
                            "where": f"rouh/genes/manifests/{path.name}"}
    for key, g in ((_json(folder / "owners.json").get("genes") or {}).items()):
        if not isinstance(g, dict) or key in out:
            continue
        if g.get("switch") and not (folder / "manifests" / f"{key}.json").exists():
            out[key] = {"switch": g["switch"], "signals": g.get("signals"),
                        "where": f"rouh/genes/owners.json, {key}"}
    return out


@lru_cache(maxsize=1)
def by_switch() -> dict[str, dict]:
    """{switch: its signals}, as this checkout declares them."""
    return {g["switch"]: (g["signals"] if isinstance(g["signals"], dict) else {})
            for g in genes().values()}


def of_switch(switch: str) -> dict:
    """One switch's declared events and runs, each {name: what happened}; {} when it declares none."""
    sig = by_switch().get(str(switch or "")) or {}
    return {k: dict(sig[k]) for k in KINDS if isinstance(sig.get(k), dict)}


def code_kind(switch: str, event: str) -> str:
    """"used" for one of the gene's events, "ran" for one of its runs, "" for neither."""
    sig = of_switch(switch)
    return "used" if event in sig.get("events", {}) else "ran" if event in sig.get("runs", {}) else ""


# --- reading the code ------------------------------------------------------------------------------


def _is_used(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr in ("used", "ran", "note")
            and isinstance(node.value, ast.Name) and node.value.id == "evolution")


def _constants(tree) -> dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def calls(root: Path) -> list[dict]:
    """Every `evolution.used(...)` in Rouh's Python, with its switch and event where they can be
    read, and why where they cannot."""
    top = root / "rouh"
    files = [p for p in sorted(top.rglob("*.py")) if "migrations" not in p.parts and p.name != "evolution.py"]
    trees, consts = {}, {}
    for p in files:
        try:
            trees[p] = ast.parse(p.read_text(encoding="utf-8"), str(p))
        except (OSError, SyntaxError, ValueError):
            continue
        consts[p] = _constants(trees[p])
    by_name: dict[str, Path] = {}
    # A module named in `name.SWITCH` is the one nearest the top: rouh/meeting_people.py, not the
    # management command of the same name.
    for p in sorted(trees, key=lambda x: (len(x.parts), str(x))):
        by_name.setdefault(p.stem, p)
    out = []
    for p, tree in trees.items():
        rel = str(p.relative_to(root))
        wrapped = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in wrapped:
                continue
            if _is_used(node.func):
                fn, args = node.func, list(node.args)
            elif isinstance(node.func, ast.Call) and node.func.args and _is_used(node.func.args[0]):
                # sync_to_async(evolution.used)(switch, event, ...)
                wrapped.add(id(node.func))
                fn, args = node.func.args[0], list(node.args)
            elif node.args and _is_used(node.args[0]):
                # asyncio.to_thread(evolution.used, switch, event, ...)
                fn, args = node.args[0], list(node.args[1:])
            else:
                continue
            at = f"{rel}:{node.lineno}"
            if fn.attr != "used":
                out.append({"at": at, "why": f"evolution.{fn.attr} is gone: report through "
                                              "evolution.used(switch, event)"})
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            sw = args[0] if args else kw.get("switch")
            ev = args[1] if len(args) > 1 else kw.get("event")
            switch = ""
            if isinstance(sw, ast.Constant) and isinstance(sw.value, str):
                switch = sw.value
            elif isinstance(sw, ast.Name):
                switch = consts[p].get(sw.id, "")
            elif isinstance(sw, ast.Attribute) and isinstance(sw.value, ast.Name):
                other = by_name.get(sw.value.id)
                switch = consts.get(other, {}).get(sw.attr, "") if other else ""
            if not switch:
                out.append({"at": at, "why": "its switch is not a name this check can read: write it "
                                             "out, or use the module's SWITCH"})
                continue
            if not (isinstance(ev, ast.Constant) and isinstance(ev.value, str)):
                out.append({"at": at, "switch": switch,
                            "why": "its event is not written out: name it, as the gene declares it"})
                continue
            out.append({"at": at, "switch": switch, "event": ev.value})
    return out


def check(root: Path) -> list[str]:
    """Everything wrong with how the genes say they were used."""
    out: list[str] = []
    found = genes(root / "rouh" / "genes")
    reported = calls(root)
    said: dict[str, set[str]] = {}
    for c in reported:
        if c.get("why"):
            out.append(f"{c['at']}: {c['why']}")
            continue
        said.setdefault(c["switch"], set()).add(c["event"])
    switches = {g["switch"]: key for key, g in found.items()}
    for c in reported:
        if c.get("why"):
            continue
        if c["switch"] not in switches:
            out.append(f"{c['at']}: reports a use of {c['switch']!r}, which no gene with that switch declares")
        elif not code_kind_in(found[switches[c["switch"]]].get("signals"), c["event"]):
            out.append(f"{c['at']}: reports {c['event']!r} for {c['switch']}, which "
                       f"{found[switches[c['switch']]]['where']} does not declare under signals.events or signals.runs")
    for key, g in found.items():
        sig = g.get("signals")
        if sig is None or sig == {}:
            out.append(f"{key} ({g['where']}): has the switch {g['switch']} and declares no signals: "
                       "name the points in its code where the person uses it, under signals.events")
            continue
        out += [f"{key} ({g['where']}): {p}" for p in shape_problems(sig)]
        if not isinstance(sig, dict):
            continue
        for kind in CODE:
            for name in (sig.get(kind) or {}) if isinstance(sig.get(kind), dict) else {}:
                if name not in said.get(g["switch"], set()):
                    out.append(f"{key} ({g['where']}): declares the {kind[:-1]} {name!r}, and nothing "
                               f"reports it: call evolution.used({g['switch']!r}, {name!r}) where it happens")
    return out


def code_kind_in(sig, event: str) -> bool:
    sig = sig if isinstance(sig, dict) else {}
    return any(isinstance(sig.get(k), dict) and event in sig[k] for k in CODE)


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else HERE.parents[1]
    said = check(root)
    for line in said:
        print(f"FAIL {line}")
    if said:
        print(f"How the genes say they were used does not hold: {len(said)} "
              f"problem{'s' if len(said) != 1 else ''}.")
        return 1
    n = len(genes(root / "rouh" / "genes"))
    print(f"Every gene with a switch says how it was used: {n} genes, every event declared and reported.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
