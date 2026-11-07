"""Which gene every file of Rouh belongs to: the gene ownership map (GENES.md, "Every file belongs to a gene").

Petar, 19 October 2026, in conversation: "there is no plumbing that is not gene". Every part of Rouh is
a gene, the shared parts underneath included - the turn loop, memory, mail, the screen, model calls,
the one program, landing - and every change Rouh gets, by whatever route, is written into the history
of the genes whose files it touched. This module is the half of that a landing can ask without a
database: `owners.json` beside it maps every file of the repository, by its path or a pattern, to one
or more genes, and

* `owners_of(path)` says which genes own a file (`None` for a file outside Rouh, the workspace);
* `python -m rouh.genes.owners check` holds the whole map: every tracked file has an owner, every gene
  it names is a gene, a core gene has no switch;
* `python -m rouh.genes.owners changed --repo R --before A --after B` is what `land.sh` asks before it
  pushes (`owners_guard`): a change that touches a file no gene owns is refused, naming the file.

**A pattern.** A path relative to the repository's top, where `*` is any part of one name, `**` any
number of folders and `?` one letter. When several patterns match a file, the most exact wins: a
whole path beats a pattern, and between patterns the one with the longer fixed start. Genes tied at
that rank all own it, so a file two genes share is listed under both (`rouh/meeting_brief.py` is
What to raise and What to raise remembers). A gene's manifest is its own without being listed.

**A gene in the map.** Its key is a gene manifest's id (`rouh/genes/manifests/<id>.json`) or a key of
the gene log; one with no manifest says its `name` and `what` here, which is its record until the
gene log makes it. `core: true` marks a gene Rouh breaks without, which therefore has no off switch;
`switch` names the feature switch of a gene that has one and no manifest to say so; `needed_by` names
the genes that cannot work without a shared one (written by `needs`, from what imports what).

Standard library only, so a landing can run it from a bare copy of the commit it is about to push.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAP = HERE / "owners.json"
MANIFESTS = HERE / "manifests"
MAP_PATH = "rouh/genes/owners.json"
MANIFEST_DIR = "rouh/genes/manifests/"

KEY = re.compile(r"^[a-z][a-z0-9.-]{1,80}$")
SWITCH = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
GENE_KEYS = {"name", "what", "core", "switch", "signals", "files", "needed_by"}
WILD = re.compile(r"[*?\[]")


class MapError(ValueError):
    """The map cannot be read at all."""


def read(path: Path | str = MAP) -> dict:
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except OSError as err:
        raise MapError(f"{MAP_PATH} cannot be read: {err}") from None


def parse(text: str) -> dict:
    try:
        raw = json.loads(text)
    except ValueError as err:
        raise MapError(f"{MAP_PATH} is not JSON: {err}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("genes"), dict):
        raise MapError(f"{MAP_PATH} has no genes")
    return raw


@lru_cache(maxsize=4096)
def _regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches(pattern: str, path: str) -> bool:
    return bool(_regex(pattern).match(path))


def rank(pattern: str) -> tuple[int, int]:
    """How exact a pattern is: a whole path first, then the longer fixed start."""
    wild = WILD.search(pattern)
    return (1, len(pattern)) if wild is None else (0, wild.start())


class Owners:
    """The map, ready to be asked."""

    def __init__(self, raw: dict, manifests: set[str] | None = None):
        self.raw = raw
        self.genes: dict[str, dict] = {k: v for k, v in raw["genes"].items() if isinstance(v, dict)}
        self.outside = list((raw.get("outside") or {}).keys())
        self.manifests = set(manifests) if manifests is not None else {p.stem for p in MANIFESTS.glob("*.json")}
        self.rules: list[tuple[str, str]] = [(pat, key) for key, g in self.genes.items()
                                             for pat in (g.get("files") or []) if isinstance(pat, str)]

    def is_outside(self, path: str) -> bool:
        return any(matches(p, path) for p in self.outside)

    def owners_of(self, path: str) -> list[str] | None:
        """The genes that own a file, most exact patterns first; [] for none; None outside Rouh."""
        if self.is_outside(path):
            return None
        if path.startswith(MANIFEST_DIR) and path.endswith(".json"):
            return [Path(path).stem]
        best, keys = None, []
        for pat, key in self.rules:
            if not matches(pat, path):
                continue
            r = rank(pat)
            if best is None or r > best:
                best, keys = r, [key]
            elif r == best and key not in keys:
                keys.append(key)
        return keys

    def known(self, key: str) -> bool:
        return key in self.genes or key in self.manifests

    def core(self) -> set[str]:
        return {k for k, g in self.genes.items() if g.get("core") is True}

    def name_of(self, key: str) -> str:
        g = self.genes.get(key) or {}
        if g.get("name"):
            return str(g["name"])
        if key in self.manifests:
            try:
                return json.loads((MANIFESTS / f"{key}.json").read_text(encoding="utf-8")).get("name") or key
            except (OSError, ValueError):
                return key
        return key

    def problems(self, files: list[str] | None = None) -> list[str]:
        """Everything wrong with the map, and every file of `files` no gene owns."""
        out: list[str] = []
        for key, g in self.raw["genes"].items():
            if not isinstance(g, dict):
                out.append(f"{key}: is not an object")
                continue
            if not KEY.match(key):
                out.append(f"{key!r} is not a gene's key: lowercase letters, digits, dots and dashes")
            for k in sorted(set(g) - GENE_KEYS):
                out.append(f"{key}: has a key the map does not know: {k!r}")
            if key not in self.manifests:
                for k in ("name", "what"):
                    if not (isinstance(g.get(k), str) and g[k].strip()):
                        out.append(f"{key}: has no gene manifest, so it says its own {k} here")
            if "core" in g and not isinstance(g["core"], bool):
                out.append(f"{key}: core is not true or false")
            if "switch" in g and not (isinstance(g["switch"], str) and SWITCH.match(g["switch"])):
                out.append(f"{key}: switch {g['switch']!r} is not a switch's name")
            switch = g.get("switch") or self._manifest_switch(key)
            if g.get("core") is True and switch:
                out.append(f"{key}: is core, so it has no off switch, and it has the switch {switch}")
            if "signals" in g:
                from . import signal_problems

                out += [f"{key}: {p}" for p in signal_problems(g["signals"])]
            pats = g.get("files", [])
            if not (isinstance(pats, list) and all(isinstance(p, str) and p.strip() and not p.startswith("/")
                                                    for p in pats)):
                out.append(f"{key}: files is not a list of paths in the repository")
            need = g.get("needed_by", [])
            if not isinstance(need, list) or any(not isinstance(n, str) for n in need):
                out.append(f"{key}: needed_by is not a list of genes")
            else:
                out += [f"{key}: needed_by names {n!r}, which is not a gene" for n in need if not self.known(n)]
        for path in files or []:
            got = self.owners_of(path)
            if got == []:
                out.append(f"{path}: belongs to no gene")
            elif got:
                out += [f"{path}: belongs to {k!r}, which is not a gene" for k in got if not self.known(k)]
        return out

    def _manifest_switch(self, key: str) -> str:
        if key not in self.manifests:
            return ""
        try:
            return json.loads((MANIFESTS / f"{key}.json").read_text(encoding="utf-8")).get("switch") or ""
        except (OSError, ValueError):
            return ""

    def unused(self, files: list[str]) -> list[str]:
        """Patterns that match no file any more: worth taking out, never a reason to refuse."""
        return [f"{key}: {pat}" for pat, key in self.rules if not any(matches(pat, f) for f in files)]


@lru_cache(maxsize=1)
def here() -> Owners:
    return Owners(read())


def owners_of(path: str) -> list[str] | None:
    return here().owners_of(path)


# --- git ----------------------------------------------------------------------------------------


def _git(repo: str, *args: str) -> str:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise MapError(f"git {' '.join(args[:2])} failed: {done.stderr.strip()[:200]}")
    return done.stdout


def tracked(repo: str) -> list[str]:
    return [p for p in _git(repo, "ls-files", "-z").split("\0") if p]


def changed(repo: str, before: str, after: str) -> list[str]:
    """The files a range of commits adds, changes or renames to: what has to belong to a gene. A file
    it deletes belongs to nobody any more."""
    out = _git(repo, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=ACMRT", f"{before}...{after}")
    return [p for p in out.split("\0") if p]


def at(repo: str, sha: str) -> Owners | None:
    """The map as a commit has it, with the manifests it has: None before there was a map."""
    try:
        text = _git(repo, "show", f"{sha}:{MAP_PATH}")
    except MapError:
        return None
    names = _git(repo, "ls-tree", "--name-only", f"{sha}:{MANIFEST_DIR.rstrip('/')}")
    return Owners(parse(text), {Path(n).stem for n in names.split() if n.endswith(".json")})


# --- what needs a shared gene --------------------------------------------------------------------

IMPORT = re.compile(r"^\s*(?:from\s+(?:rouh)?\.?([a-z_][a-z0-9_.]*)?\s+import\s+([a-z_][a-z0-9_, ]*)|import\s+rouh\.([a-z_][a-z0-9_.]*))",
                    re.M)


def needs(root: Path, owners: Owners, shared: list[str]) -> dict[str, list[str]]:
    """For each shared gene, the other genes whose Python imports one of its modules."""
    module_gene: dict[str, list[str]] = {}
    for path in root.joinpath("rouh").rglob("*.py"):
        rel = str(path.relative_to(root))
        mod = rel[:-3].replace("/", ".").removesuffix(".__init__")
        module_gene[mod] = owners.owners_of(rel) or []
    out: dict[str, set[str]] = {k: set() for k in shared}
    for path in root.joinpath("rouh").rglob("*.py"):
        rel = str(path.relative_to(root))
        mine = set(owners.owners_of(rel) or [])
        pkg = rel[:-3].replace("/", ".").rsplit(".", 1)[0]
        for m in IMPORT.finditer(path.read_text(encoding="utf-8", errors="replace")):
            targets = []
            if m.group(3):
                targets.append("rouh." + m.group(3))
            else:
                base = m.group(1) or ""
                stem = "rouh" if base in ("", "rouh") else ("rouh." + base if not base.startswith("rouh") else base)
                if base == "" or m.group(0).lstrip().startswith("from ."):
                    stem = pkg if not base else f"{pkg}.{base}"
                targets += [stem] + [f"{stem}.{n.strip()}" for n in m.group(2).split(",") if n.strip()]
            for t in targets:
                for g in module_gene.get(t, []):
                    if g in out:
                        out[g] |= mine - {g}
    return {k: sorted(v) for k, v in out.items()}


# --- the command ---------------------------------------------------------------------------------


def _top() -> str:
    return str(HERE.parents[1])


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    args = dict(zip(argv[1::2], argv[2::2]))
    repo = args.get("--repo") or _top()
    if cmd == "who":
        for path in argv[1:]:
            got = owners_of(path)
            print(f"{path}: " + ("outside Rouh" if got is None else ", ".join(got) or "no gene"))
        return 0
    if cmd == "check":
        o = here()
        files = tracked(repo)
        said = o.problems(files)
        for line in said:
            print(f"FAIL {line}")
        for line in o.unused(files):
            print(f"note: a pattern that matches nothing now, {line}")
        if said:
            print(f"The gene ownership map does not hold: {len(said)} problem{'s' if len(said) != 1 else ''}.")
            return 1
        owned = sum(1 for f in files if owners_of(f))
        print(f"Every file belongs to a gene: {owned} files, {len(o.genes)} genes, {len(o.core())} of them core.")
        return 0
    if cmd == "changed":
        before, after = args.get("--before", ""), args.get("--after", "HEAD")
        o = at(repo, after)
        files = changed(repo, before, after)
        if o is None:
            print("There is no gene ownership map in this commit yet, so nothing is asked.")
            return 0
        said = o.problems(files)
        if said:
            first = said[0]
            unowned = [f for f in files if o.owners_of(f) == []]
            if unowned:
                print(f"{unowned[0]} belongs to no gene" + (f" (and {len(unowned) - 1} more files)" if len(unowned) > 1 else "")
                      + f". Add it to {MAP_PATH} under the gene it is part of - a new gene only for a new ability"
                      + " - and land again.")
            else:
                print(f"The gene ownership map does not hold: {first}. Mend {MAP_PATH} and land again.")
            for line in said:
                print(f"FAIL {line}", file=sys.stderr)
            return 1
        keys = sorted({k for f in files for k in (o.owners_of(f) or [])})
        print(f"Every changed file belongs to a gene: {', '.join(keys) or 'none of Rouh'}.")
        return 0
    if cmd == "needs":
        o = here()
        shared = [k for k in argv[1:] if not k.startswith("--")] or sorted(o.core())
        for k, v in needs(Path(repo), o, shared).items():
            print(f"{k}: {', '.join(v)}")
        return 0
    print("usage: python -m rouh.genes.owners [check | changed --repo R --before A --after B | who PATH... | needs GENE...]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
