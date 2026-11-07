"""`python3 -m rouh.genes`: the gene contract, checked (GENES.md).

Petar, 12 October 2026: "A test that fails if a navigation link is added
outside the registry, or a manifest lacks a valid group." Not a suite: one
check of one contract, a second or so, standard library only, run by
`land.sh` (`genes_guard`) before it pushes work that touches the registry,
the page's markup or its script, the way the mail replay is run for the mail.

It fails, naming each problem, when

* a group has no glyph for its box in the rail, or one that is more than a
  drawing (`rouh.genes.GROUP_ICONS`);
* a manifest breaks the contract: no valid group, an unknown key, a route
  that is not one, an icon that is more than a drawing, two genes with one
  id, one order or one element id (`rouh.genes.read`);
* a navigation link is written into the page by hand: inside the navigation
  (`#sbNav`) there is nothing but the rail of group boxes and the loop over the
  registry, and anywhere else in the page a `data-nav` is one of the genes
  the registry places in the dedicated area (Rouh, Search, Gene therapy) or a
  link's plus;
* the page's script makes a navigation link of its own (`data-nav` set from
  a script);
* the orb's script (`app/orb.js`) reads the genes: the orb draws execution,
  and a gene is never one of its lines;
* the gene ownership map (`owners.json`) names something that is not a gene,
  or gives a core gene a switch (`rouh.genes.owners`).

And it checks itself: each of those is tried on a broken copy, and the check
has to fail on every one, so it cannot quietly pass by finding nothing.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from . import GROUP_ICONS, MANIFESTS, ManifestError, group_problems, read

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "rouh" / "templates" / "rouh" / "index.html"
ROW = ROOT / "rouh" / "templates" / "rouh" / "_nav_row.html"
SCRIPTS = ROOT / "rouh" / "static"

NAV_OPEN = '<div class="sb-nav" id="sbNav">'
#: What may stand inside the navigation, once the template's own tags and
#: comments are taken out: the rail's boxes with their glyphs (drawn from the
#: registry's `GROUP_ICONS`), Now's count, the groups and the loop.
NAV_TAGS = {"div", "button", "span", "svg", "script"}
#: The orb's own script, and what in it would mean it had read the genes.
ORB = "app/orb.js"
ORB_MUST_NOT = re.compile(r"rouhGenes|app/navgroups\.js|rouh/genes|\bgene(Go|Icon|ById|Open)\b")
DATA_NAV = re.compile(r"""data-nav\s*=\s*["']([^"'{}]*)["']""")


def _nav_block(page: str) -> str:
    """The navigation's own markup, from its opening tag to the one that closes it."""
    at = page.find(NAV_OPEN)
    if at < 0:
        return ""
    depth, i = 0, at
    tag = re.compile(r"<(/?)div\b[^>]*>")
    for m in tag.finditer(page, at):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[at:m.end()]
        i = m.end()
    return page[at:i]


def _without_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", "", text, flags=re.S)
    return re.sub(r"<script>.*?</script>", "<script></script>", text, flags=re.S)


def page_problems(page: str, row: str, genes: list[dict], scripts: dict[str, str]) -> list[str]:
    out: list[str] = []
    dedicated = {m["id"] for m in genes if m["nav"]["place"] == "dedicated"}
    pluses = {m["nav"]["plus"]["nav"] for m in genes if m["nav"].get("plus")}
    nav = _without_comments(_nav_block(page))
    if not nav:
        out.append(f"index.html: the navigation ({NAV_OPEN}) is not there")
    else:
        if '{% include "rouh/_nav_row.html" %}' not in nav or "NAV_GROUPS" not in nav:
            out.append("index.html: the navigation is not drawn from the registry (NAV_GROUPS, _nav_row.html)")
        for m in re.finditer(r"<\s*([a-zA-Z]+)", nav):
            if m.group(1).lower() not in NAV_TAGS:
                out.append(f"index.html: a <{m.group(1)}> is written into the navigation by hand; "
                           "a link comes from a gene manifest (GENES.md)")
        for m in DATA_NAV.finditer(nav):
            out.append(f"index.html: data-nav={m.group(1)!r} is written into the navigation by hand")
        if re.search(r"""href\s*=\s*["']/""", nav):
            out.append("index.html: an address is written into the navigation by hand")
    for m in DATA_NAV.finditer(_without_comments(page)):
        key = m.group(1)
        if key not in dedicated and key not in pluses:
            out.append(f"index.html: data-nav={key!r} is a navigation link outside the registry; "
                       "give it a gene manifest in rouh/genes/manifests/ instead")
    row = _without_comments(row)
    if re.search(r"""href\s*=\s*["']/""", row) or DATA_NAV.search(row):
        out.append("_nav_row.html: a link is written into the row template by hand")
    for name, text in scripts.items():
        if re.search(r"""(setAttribute\(\s*['"]data-nav['"]|dataset\.nav\s*=|data-nav=)""", text):
            out.append(f"{name}: makes a navigation link in script; it comes from a manifest instead")
        # The orb draws execution - jobs, sub-agents, tool calls - and a gene is
        # never one of its lines (GENES.md, What a gene is).
        if name.endswith(ORB) and ORB_MUST_NOT.search(text):
            out.append(f"{name}: the orb reads the gene registry; a gene is never drawn as a line on the orb")
    return out


def check(folder: Path = MANIFESTS, page: str | None = None, row: str | None = None,
          scripts: dict[str, str] | None = None) -> list[str]:
    try:
        genes = read(folder)
    except ManifestError as err:
        return str(err).splitlines()[1:] or [str(err)]
    if page is None:
        page = PAGE.read_text(encoding="utf-8")
    if row is None:
        row = ROW.read_text(encoding="utf-8")
    if scripts is None:
        scripts = {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8", errors="replace")
                   for p in SCRIPTS.rglob("*.js") if "ort" not in p.name and "xterm" not in p.name}
    return page_problems(page, row, genes, scripts)


def bites() -> list[str]:
    """The check fails on each thing it is there to stop. Anything it misses is a problem."""
    out = []
    page, row = PAGE.read_text(encoding="utf-8"), ROW.read_text(encoding="utf-8")
    nav_at = page.find(NAV_OPEN) + len(NAV_OPEN)
    tries = {
        "a link written into the navigation":
            dict(page=page[:nav_at] + '\n<a class="sb-row" href="/somewhere" data-nav="somewhere">X</a>'
                 + page[nav_at:]),
        "a data-nav link outside the navigation":
            dict(page=page.replace("<body>", '<body>\n<button data-nav="elsewhere">Y</button>', 1)),
        "a link made in script":
            dict(scripts={"x.js": "a.setAttribute('data-nav', 'made');"}),
        "the orb drawing genes":
            dict(scripts={"rouh/static/app/orb.js": "var g = JSON.parse($('rouhGenes').textContent);"}),
    }
    for what, kw in tries.items():
        if not check(**kw):
            out.append(f"the check does not catch {what}")
    with tempfile.TemporaryDirectory() as tmp:
        for path in MANIFESTS.glob("*.json"):
            (Path(tmp) / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        one = Path(tmp) / "decisions.json"
        for what, change in (("a manifest with no group", lambda m: m.pop("group")),
                             ("a manifest with a group that is not one", lambda m: m.update(group="misc"))):
            good = one.read_text(encoding="utf-8")
            m = json.loads(good)
            change(m)
            one.write_text(json.dumps(m), encoding="utf-8")
            if not any("group" in p for p in check(Path(tmp))):
                out.append(f"the check does not catch {what}")
            one.write_text(good, encoding="utf-8")
    for what, icons in (("a group with no glyph", {k: v for k, v in GROUP_ICONS.items() if k != "time"}),
                        ("a group glyph that is more than a drawing",
                         {**GROUP_ICONS, "now": '<image href="x.png"/>'})):
        if not group_problems(icons):
            out.append(f"the check does not catch {what}")
    return out


def map_problems() -> list[str]:
    """The gene ownership map holds together: every gene it names is one, a core gene has no switch
    (`rouh/genes/owners.py`; which files it owns is asked by `python -m rouh.genes.owners`)."""
    from . import owners

    try:
        return [f"owners.json: {p}" for p in owners.Owners(owners.read()).problems()]
    except owners.MapError as err:
        return [str(err)]


def main() -> int:
    said = check() + bites() + map_problems()
    if said:
        for line in said:
            print(f"FAIL {line.strip()}")
        print(f"The gene contract does not hold: {len(said)} problem{'s' if len(said) != 1 else ''}.")
        return 1
    n = len(list(MANIFESTS.glob("*.json")))
    print(f"The gene contract holds: {n} gene manifests, every link in the navigation from the registry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
