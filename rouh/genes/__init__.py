"""Rouh's genes: each ability of Rouh declared once, in one gene manifest (GENES.md).

Petar, 12 October 2026: "build that grouping and architecture change with
contracts." Every page and destination of Rouh - Decisions, the task browser,
Clockwork, Synapse, Settings, Payments - has one file in `manifests/`, named
by its id, that says what it is, the words people use for it, which of the
six groups of the navigation it belongs to, where it lives, what it may be
attached to, whether it is still a lab, and what it touches: permissions,
outside accounts, tables, scheduled jobs, and how to take it out again.

Everything that lists Rouh's genes reads them from here and nowhere else:

* the navigation's links, beside its rail of six group boxes, which the page draws
  from `nav_groups` and has no link of its own written into it any more;
* Search, which finds a gene by its name and its words (`find`, from
  `rouh/searching.py`);
* the count of presses in Settings, Stats (`rouh/navtaps.py`, `nav_keys`).

A manifest that breaks the contract stops the import, with every problem
named, so a broken one cannot reach a screen: `python3 -m rouh.genes`
checks the lot, and `land.sh` runs it before it pushes work that touches
any of it. Standard library only, so that check needs nothing installed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Iterable

#: The six groups, in the order their boxes stand in the navigation's rail,
#: top to bottom. Fixed: nothing reorders them, by use or otherwise.
GROUPS: tuple[tuple[str, str], ...] = (
    ("now", "Now"),
    ("work", "Work"),
    ("time", "Time"),
    ("memory", "Memory"),
    # What the nightly run grows for the person: Parameters and Mutations. Petar, 13 October
    # 2026 (task 94, step 94-08): "an extra tab box in the navigation that is called evolution
    # right before anatomy ... Evolution will have an icon of forking." Metabolism, the runs
    # that do the work, joined it on 14 October 2026 (fr_d9e20791f108): "Metabolism should go
    # in evolution I think".
    ("evolution", "Evolution"),
    # Rouh itself. Shown as Anatomy since 13 October 2026 (fr_d3dbbd554a2a): "we're
    # not a robot. We're a living thing". The id stays `machine`, because it is in
    # every manifest, in shared genes signed elsewhere, in the counts of presses and
    # in the group each device remembers (`rouh.navGroup`).
    ("machine", "Anatomy"),
)
GROUP_IDS: tuple[str, ...] = tuple(g for g, _ in GROUPS)
#: Each group's own glyph, over its name in the rail: the inside of a 24 by 24
#: line drawing, held to the same contract as a gene's icon. Now a dot in a
#: circle, Work a stack, Time a clock, Memory a few nodes joined into a network,
#: which is how Rouh's memory is kept, Evolution a fork, one line branching in two as a gene
#: branches into the version for us (Petar, 13 October 2026, task 94 step 94-08), and Anatomy a
#: pair of lungs, something alive rather than a cog (Petar, 13 October 2026, fr_d3dbbd554a2a).
GROUP_ICONS: dict[str, str] = {
    "now": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
    "work": '<path d="M12 3.8 20.5 8 12 12.2 3.5 8z"/><path d="M3.5 12 12 16.2 20.5 12"/>'
            '<path d="M3.5 16 12 20.2 20.5 16"/>',
    "time": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.4 2.1"/>',
    "memory": '<path d="M7.1 7.6 10.4 11M13.6 11l3.3-3.9M13.9 13.5l3.7 1.4M10.6 14l-2.7 3.6'
              'M7.6 5.9l9.3-.6M19.1 13.2l-.4-5.7"/><circle cx="12" cy="12.5" r="2.2"/>'
              '<circle cx="5.8" cy="6.2" r="1.9"/><circle cx="18.3" cy="5.4" r="1.9"/>'
              '<circle cx="19.3" cy="15.4" r="1.9"/><circle cx="6.6" cy="19.2" r="1.9"/>',
    "evolution": '<circle cx="6.5" cy="5" r="2.2"/><circle cx="17.5" cy="5" r="2.2"/>'
                 '<circle cx="12" cy="19" r="2.2"/><path d="M6.5 7.2v1.3a3.2 3.2 0 0 0 3.2 3.2h4.6a3.2 '
                 '3.2 0 0 0 3.2-3.2V7.2M12 11.7v5.1"/>',
    "machine": '<path d="M12 4v5.5M12 9.5c0 1.7-1.3 2.9-3 3.1M12 9.5c0 1.7 1.3 2.9 3 3.1"/>'
               '<path d="M9 7.3c0-1-1-1.6-1.9-1C4.7 7.9 3.3 12 3.3 16.7c0 1.9 1.4 3.3 3.2 3.3 1.4 0 '
               '2.5-1.1 2.5-2.5z"/><path d="M15 7.3c0-1 1-1.6 1.9-1 2.4 1.6 3.8 5.7 3.8 10.4 0 1.9-1.4 '
               '3.3-3.2 3.3-1.4 0-2.5-1.1-2.5-2.5z"/>',
}
#: The one group whose box may carry a count: what is waiting on the person.
COUNTED_GROUP = "now"

#: Anatomy's own groups, each a page at `/anatomy/<group>` that stacks its sections one after
#: another, in this order. Petar, 14 October 2026 (card 1554): Anatomy is one link that replaces
#: Settings and the links beside it that repeated Settings' pages, "keep 5 groups please", and
#: "lets rename machinery to meta". The sixth, Rouh Land Account, since 4 November 2026: "in the
#: settings it needs to be clear what is relevant to rouh.land. so maybe we should have one
#: separate section Rouh Land Account": the rouh.land account, the Rouh's own profile there (its
#: birth), Models and the Gene Pool. `/anatomy` itself is the status board.
ANATOMY_ROOT = "/anatomy"
ANATOMY: tuple[tuple[str, str], ...] = (
    ("you", "You"),
    ("rouh-land", "Rouh Land Account"),
    ("connections", "Connections"),
    ("behaviour", "Behaviour"),
    ("money", "Money"),
    ("meta", "Meta"),
)
ANATOMY_IDS: tuple[str, ...] = tuple(g for g, _ in ANATOMY)
#: Each of Anatomy's groups' own glyph, on its link in the navigation, its line on the status
#: board and its row in the side list, held to the same contract as a gene's icon (Petar, 15
#: October 2026: "put some icons around"). You a person in a circle, Connections two links of a
#: chain, Behaviour a dial, Money a banknote, Meta an i for what is about Rouh itself, and Rouh
#: Land Account a globe, the place every Rouh is known by.
ANATOMY_ICONS: dict[str, str] = {
    "you": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="10" r="2.9"/>'
           '<path d="M6.8 18.2a6 6 0 0 1 10.4 0"/>',
    "rouh-land": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>'
                 '<path d="M12 3.5c2.4 2.3 3.6 5.1 3.6 8.5s-1.2 6.2-3.6 8.5c-2.4-2.3-3.6-5.1-3.6-8.5s1.2-6.2 3.6-8.5z"/>',
    "connections": '<path d="M10.2 13.8a3.8 3.8 0 0 0 5.4 0l3-3a3.8 3.8 0 0 0-5.4-5.4l-1.1 1.1"/>'
                   '<path d="M13.8 10.2a3.8 3.8 0 0 0-5.4 0l-3 3a3.8 3.8 0 0 0 5.4 5.4l1.1-1.1"/>',
    "behaviour": '<path d="M4.6 17a8.2 8.2 0 1 1 14.8 0"/><path d="M12 14l3.6-4.2"/>'
                 '<circle cx="12" cy="14" r="1.4"/>',
    "money": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.7"/>'
             '<path d="M6 12h.01M18 12h.01"/>',
    "meta": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.4"/><circle cx="12" cy="7.9" r="1" '
            'fill="currentColor"/>',
}
#: A section's route says both where it is and what it is called there:
#: `/anatomy/<group>/<section>`, its place on the group's page from `anatomy.order`.
SECTION_ROUTE = re.compile(r"^/anatomy/([a-z][a-z-]{0,30})/([a-z][a-z0-9-]{0,40})$")
#: The old names of the sections moved on 4 November 2026, when Rouh Land Account was made and
#: Trusted contacts and Offline went to Behaviour. Petar: "when I say move, don't leave backup
#: forwarding links". So an old address naming one of them, `/settings/<name>` or the old
#: `/anatomy/<group>/<name>`, is sent on nowhere: it is not found, as any address Rouh does not
#: have. The page is told them too (`for_page`), so a link to one inside it is not opened as
#: somewhere else. Birthday is Rouh profile now, and Genes the Gene Pool.
#: You, Profile is About You since the same day (`/anatomy/you/about-you`), and its old name
#: goes nowhere too.
MOVED: frozenset[str] = frozenset({"models", "birthday", "genes", "trusted-contacts", "offline", "profile"})

#: What a gene may later be shown as a tab on. Declared now, drawn later.
ATTACHES: tuple[str, ...] = ("task", "step", "person", "meeting", "email")
MATURITY: tuple[str, ...] = ("lab", "accepted")

#: Where a gene is reached from.
#:   list       a link in the navigation, shown while its group's box is picked
#:   dedicated  the area under the links that never changes: Rouh, Gene therapy,
#:              the profile row, the notifications and Search
#:   account    the menu behind the person's own name
#:   none       somewhere else (a Settings group, a server page), found by Search
PLACES: tuple[str, ...] = ("list", "dedicated", "account", "none")
#: How pressing it opens it.
#:   own      the page's own code wires the row by its `row` id (or `class`)
#:   address  Rouh goes to its `route`, as a link inside Rouh does
#:   press    presses the control whose id is `press`
#:   page     a page of its own, outside the app, at its `route`
OPENS: tuple[str, ...] = ("own", "address", "press", "page")
#: What may follow the name on a row, by class.
MARKS: tuple[str, ...] = ("sb-row-hint", "sb-row-dot", "sb-web-who")
#: When a row is drawn hidden and shown by the page's own code.
WHILE: tuple[str, ...] = ("browser-open",)
TOUCHES: tuple[str, ...] = ("permissions", "accounts", "tables", "jobs", "remove")
#: What counts as using a gene, so its use is counted as its own (task 98, step 98-16, the gene
#: log): the tools Rouh's model calls for it, the places and Settings groups it opens at, its
#: scheduled work as `schedule.ran` names it, and the purposes of its model calls in
#: `llm_requests`. Its link's presses and its route are its own without saying so. Each may be
#: claimed by one gene only; whatever no gene claims is counted as Rouh's own (`CORE`).
USES: dict[str, str] = {"tools": r"^[a-z][a-z0-9_]{1,62}$", "places": r"^[a-z][a-z0-9-]{0,40}$",
                        "settings": r"^[a-z][a-z0-9-]{0,40}$", "jobs": r"^[A-Za-z][A-Za-z0-9 _-]{0,60}$",
                        "purposes": r"^[a-z][a-z0-9_.:-]{0,60}$"}
#: The gene everything nobody else claims is counted under: Rouh itself.
CORE = "rouh"

#: How a gene says it was used (`rouh/genes/signals.py`): `events`, the named points in its code
#: where the person used it, which are what its trial counts, and `runs`, where it acted by itself,
#: which count for nothing and only say its moment came.
SIGNAL_KINDS: dict[str, re.Pattern] = {
    "events": re.compile(r"^[a-z][a-z0-9_]{1,40}$"),
    "runs": re.compile(r"^[a-z][a-z0-9_]{1,40}$"),
}
#: Reported from the gene's own code, through `evolution.used`.
SIGNALS_IN_CODE = ("events", "runs")
SAID_MOST = 140


def signal_problems(sig) -> list[str]:
    """What is wrong with one gene's `signals` (`rouh/genes/signals.py`), in words."""
    if not isinstance(sig, dict):
        return ["signals is not an object"]
    out = [f"signals has a kind it does not know: {k!r}" for k in sorted(set(sig) - set(SIGNAL_KINDS))]
    seen: dict[str, str] = {}
    for kind, pattern in SIGNAL_KINDS.items():
        if kind not in sig:
            continue
        got = sig[kind]
        if not isinstance(got, dict) or not got:
            out.append(f"signals.{kind} is not an object of name: what happened")
            continue
        for name, said in got.items():
            if not pattern.match(str(name)):
                out.append(f"signals.{kind} has {name!r}, which is not a {kind[:-1]}'s name")
            if not (isinstance(said, str) and said.strip() and len(said) <= SAID_MOST):
                out.append(f"signals.{kind}.{name} needs one plain line of what happened, "
                           f"{SAID_MOST} characters at most")
            if kind in SIGNALS_IN_CODE:
                if name in seen:
                    out.append(f"signals has {name!r} as both one of its {seen[name]} and one of its {kind}")
                seen[name] = kind
    if not isinstance(sig.get("events"), dict) or not sig.get("events"):
        out.append("signals has no events: a use counts only when its own code reports one")
    return out


KEYS = {"id", "name", "title", "aliases", "group", "route", "icon", "attaches_to", "maturity",
        "switch", "signals", "nav", "touches", "uses", "anatomy", "capabilities", "needs_guard"}
#: needs_guard: the oldest protected core (rouh-guard, guard/VERSION) a gene works with, such as
#: ">=1.0". The guard's change step reads it, and a change whose gene needs a newer core waits for
#: one (GENES.md, "What a gene may change").
NEEDS_GUARD = re.compile(r"^(>=|==)?\s*\d{1,3}(\.\d{1,3}){0,2}$")
#: A section of one of Anatomy's group pages: its place there, and, where the gene's own name
#: is not what the section is called, the name its heading has.
ANATOMY_KEYS = {"order", "name"}
NAV_KEYS = {"place", "order", "opens", "row", "press", "controls", "class", "marks", "plus", "while",
            "counts", "as"}
#: What a link may be drawn as, in its own place and instead of one link of its own: `anatomy`
#: is Anatomy's groups (`ANATOMY`), each with its glyph and opening its page. Petar, 14
#: October 2026 (fr_d9e20791f108): "all the 5 groups under anatomy should be in the navigation
#: under the anatomy square tab", and the next day: "remove the anatomy link that is at the top,
#: within the anatomy section. No need for that, each subsection goes to the subpage".
AS: tuple[str, ...] = ("anatomy",)

ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
ELEMENT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,60}$")
SWITCH = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
ROUTE = re.compile(r"^/[a-z0-9][a-z0-9/_-]*$")
CLASS = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
#: An icon is the inside of a 24 by 24 line drawing, and nothing that can run.
ICON_TAG = re.compile(r"<\s*/?\s*([a-zA-Z]+)")
ICON_TAGS = {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}

HERE = Path(__file__).resolve().parent
MANIFESTS = HERE / "manifests"


class ManifestError(ValueError):
    """One or more manifests break the contract; the message names every problem."""


def _strs(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def icon_problems(icon) -> list[str]:
    """What is wrong with an icon, a gene's or a group's: empty, or more than a drawing."""
    if not (isinstance(icon, str) and icon.strip()):
        return ["icon is empty"]
    out = []
    tags = {t.lower() for t in ICON_TAG.findall(icon)}
    if not tags or tags - ICON_TAGS:
        out.append(f"icon may only draw with {', '.join(sorted(ICON_TAGS))}")
    if re.search(r"\bon[a-z]+\s*=|javascript:|href", icon, re.I):
        out.append("icon has something in it that is not a drawing")
    return out


def group_problems(icons: dict | None = None) -> list[str]:
    """Every group has its own glyph for the rail, and nothing else has one."""
    icons = GROUP_ICONS if icons is None else icons
    out = [f"group {g}: has no icon" for g in GROUP_IDS if g not in icons]
    if icons is GROUP_ICONS:
        out += [f"Anatomy's group {g}: has no icon" for g in ANATOMY_IDS if g not in ANATOMY_ICONS]
        out += [f"Anatomy's group {g}: {said}" for g in ANATOMY_IDS if g in ANATOMY_ICONS
                for said in icon_problems(ANATOMY_ICONS[g])]
    out += [f"group {g!r}: has an icon and is not a group" for g in icons if g not in GROUP_IDS]
    for g in GROUP_IDS:
        if g in icons:
            out += [f"group {g}: {said}" for said in icon_problems(icons[g])]
    return out


def problems(m, name: str = "") -> list[str]:
    """Everything wrong with one manifest, as sentences. Empty when it keeps the contract."""
    where = name or (m.get("id") if isinstance(m, dict) else "") or "a manifest"
    if not isinstance(m, dict):
        return [f"{where}: is not an object"]
    out: list[str] = []

    def bad(text: str) -> None:
        out.append(f"{where}: {text}")

    for key in sorted(set(m) - KEYS):
        bad(f"has a key the contract does not know: {key!r}")
    for key in ("id", "name", "title", "aliases", "group", "route", "icon", "attaches_to", "maturity",
                "nav", "touches"):
        if key not in m:
            bad(f"lacks {key!r}")
    fid = m.get("id")
    if "id" in m and not (isinstance(fid, str) and ID.match(fid)):
        bad(f"id {fid!r} is not lowercase letters, digits and dashes")
    if name and isinstance(fid, str) and fid != name:
        bad(f"id {fid!r} is not its file's name")
    for key in ("name", "title"):
        if key in m and not (isinstance(m[key], str) and m[key].strip()):
            bad(f"{key} is empty")
    if "aliases" in m and not _strs(m["aliases"]):
        bad("aliases is not a list of words")
    if "group" in m and m["group"] not in GROUP_IDS:
        bad(f"group {m['group']!r} is not one of {', '.join(GROUP_IDS)}")
    route = m.get("route")
    if route is not None and not (isinstance(route, str) and ROUTE.match(route)):
        bad(f"route {route!r} is not an address in Rouh")
    if "icon" in m:
        out.extend(f"{where}: {said}" for said in icon_problems(m.get("icon")))
    att = m.get("attaches_to")
    if "attaches_to" in m:
        if not isinstance(att, list) or any(a not in ATTACHES for a in att) or len(set(att)) != len(att):
            bad(f"attaches_to must be a list of {', '.join(ATTACHES)} (empty for none)")
    if "maturity" in m and m["maturity"] not in MATURITY:
        bad(f"maturity {m['maturity']!r} is not lab or accepted")
    if "needs_guard" in m and not (isinstance(m["needs_guard"], str) and NEEDS_GUARD.match(m["needs_guard"].strip())):
        bad(f"needs_guard {m['needs_guard']!r} is not a protected core's version, such as \">=1.0\"")
    if "switch" in m and not (isinstance(m["switch"], str) and SWITCH.match(m["switch"])):
        bad(f"switch {m['switch']!r} is not a switch's name")

    t = m.get("touches")
    if "touches" in m:
        if not isinstance(t, dict):
            bad("touches is not an object")
        else:
            for key in sorted(set(t) - set(TOUCHES)):
                bad(f"touches has a key the contract does not know: {key!r}")
            for key in TOUCHES[:-1]:
                if key not in t or not (isinstance(t[key], list) and all(isinstance(v, str) and v.strip()
                                                                          for v in t[key])):
                    bad(f"touches.{key} is not a list (empty when there is nothing)")
            if not (isinstance(t.get("remove"), str) and t["remove"].strip()):
                bad("touches.remove does not say how to remove or undo it")

    sec = m.get("anatomy")
    placed = SECTION_ROUTE.match(route) if isinstance(route, str) else None
    if "anatomy" in m:
        if not isinstance(sec, dict):
            bad("anatomy is not an object")
        else:
            for key in sorted(set(sec) - ANATOMY_KEYS):
                bad(f"anatomy has a key the contract does not know: {key!r}")
            if not isinstance(sec.get("order"), int) or isinstance(sec.get("order"), bool):
                bad("a section of Anatomy needs a whole-number anatomy.order")
            if "name" in sec and not (isinstance(sec["name"], str) and sec["name"].strip()):
                bad("anatomy.name is empty")
        if not placed:
            bad(f"is a section of Anatomy and its route {route!r} is not /anatomy/<group>/<section>")
    elif placed:
        bad("its route is a section of Anatomy and it has no anatomy.order")
    if placed:
        if placed.group(1) not in ANATOMY_IDS:
            bad(f"route {route!r} names {placed.group(1)!r}, which is not one of {', '.join(ANATOMY_IDS)}")
        if placed.group(2) in ANATOMY_IDS:
            bad(f"route {route!r} names a section with a group's name")

    if "signals" in m:
        # How it says it was used (`rouh/genes/signals.py`): checked with its code by `python -m rouh.genes.signals`.
        for p in signal_problems(m["signals"]):
            bad(p)
        if not m.get("switch"):
            bad("declares signals and has no switch: signals are for a gene that can be on trial")

    uses = m.get("uses")
    if "uses" in m:
        if not isinstance(uses, dict):
            bad("uses is not an object")
        else:
            for key in sorted(set(uses) - set(USES)):
                bad(f"uses has a key the contract does not know: {key!r}")
            for key, pattern in USES.items():
                if key in uses and not (isinstance(uses[key], list)
                                        and all(isinstance(v, str) and re.match(pattern, v) for v in uses[key])):
                    bad(f"uses.{key} is not a list of {key}' names")

    if "capabilities" in m:
        # What it lets Rouh do for somebody other than the owner (`rouh/capabilities.py`,
        # CAPABILITIES.md): checked with their locked contracts by `python -m rouh.capabilities`
        # and the mail replay. A bare copy of this folder alone, as some of land.sh's checks
        # read it, has no capabilities module beside it to check them with.
        try:
            from ..capabilities import declaration_problems
        except ImportError:
            declaration_problems = None
        if declaration_problems is not None:
            out.extend(declaration_problems(m["capabilities"], where))

    nav = m.get("nav")
    if "nav" in m:
        if not isinstance(nav, dict):
            bad("nav is not an object")
            return out
        for key in sorted(set(nav) - NAV_KEYS):
            bad(f"nav has a key the contract does not know: {key!r}")
        place = nav.get("place")
        if place not in PLACES:
            bad(f"nav.place {place!r} is not one of {', '.join(PLACES)}")
        opens = nav.get("opens")
        if place == "list" and opens is None:
            bad("a link in the navigation must say how it opens (nav.opens)")
        if opens is not None and opens not in OPENS:
            bad(f"nav.opens {opens!r} is not one of {', '.join(OPENS)}")
        if opens in ("address", "page") and not route:
            bad(f"opens by {opens} and has no route")
        if opens == "press" and not (isinstance(nav.get("press"), str) and ELEMENT.match(nav["press"])):
            bad("opens by press and does not name what to press (nav.press)")
        if opens == "own" and not (nav.get("row") or nav.get("class")):
            bad("opens with the page's own code and has no row id or class for it to find")
        if place == "list":
            if not isinstance(nav.get("order"), int) or isinstance(nav.get("order"), bool):
                bad("a link in the navigation needs a whole-number nav.order")
        for key in ("row", "controls"):
            if key in nav and not (isinstance(nav[key], str) and ELEMENT.match(nav[key])):
                bad(f"nav.{key} {nav[key]!r} is not an element id")
        if "class" in nav and not (isinstance(nav["class"], str) and CLASS.match(nav["class"])):
            bad(f"nav.class {nav['class']!r} is not a class name")
        if "while" in nav and nav["while"] not in WHILE:
            bad(f"nav.while {nav['while']!r} is not one of {', '.join(WHILE)}")
        if "as" in nav and nav["as"] not in AS:
            bad(f"nav.as {nav['as']!r} is not one of {', '.join(AS)}")
        if "as" in nav and (place != "list" or nav.get("plus") or nav.get("marks")):
            bad("only a plain link in the navigation is drawn as other links (nav.as)")
        if "counts" in nav and not isinstance(nav["counts"], bool):
            bad("nav.counts is not true or false")
        for mark in nav.get("marks", []) if isinstance(nav.get("marks", []), list) else [None]:
            if not (isinstance(mark, dict) and set(mark) == {"id", "class"}
                    and isinstance(mark["id"], str) and ELEMENT.match(mark["id"]) and mark["class"] in MARKS):
                bad(f"nav.marks has {mark!r}, which is not an id and one of {', '.join(MARKS)}")
        plus = nav.get("plus")
        if plus is not None:
            if not (isinstance(plus, dict) and set(plus) == {"id", "nav", "name", "title", "icon"}
                    and ELEMENT.match(str(plus.get("id"))) and ID.match(str(plus.get("nav")))
                    and all(isinstance(plus[k], str) and plus[k].strip() for k in ("name", "title", "icon"))):
                bad("nav.plus must be {id, nav, name, title, icon}")
    return out


def read(folder: Path = MANIFESTS) -> list[dict]:
    """Every manifest in the folder, checked one by one and against each other.
    Raises ManifestError naming every problem at once."""
    found: list[dict] = []
    out: list[str] = group_problems()
    files = sorted(folder.glob("*.json"))
    if not files:
        raise ManifestError(f"there are no manifests in {folder}")
    for path in files:
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            out.append(f"{path.name}: is not JSON ({err})")
            continue
        said = problems(m, path.stem)
        out.extend(said)
        if not said:
            found.append(m)
    seen_ids: dict[str, str] = {}
    seen_orders: dict[tuple[str, int], str] = {}
    seen_navs: dict[str, str] = {}
    for m in found:
        nav = m["nav"]
        ids = [nav.get("row") or (f"nav-{m['id']}" if nav["place"] == "list" else ""),
               *[mk["id"] for mk in nav.get("marks", [])],
               (nav.get("plus") or {}).get("id", ""),
               *[u["row_id"] for u in as_links(m)]]
        for el in filter(None, ids):
            if el in seen_ids:
                out.append(f"{m['id']}: element id {el!r} is already {seen_ids[el]}'s")
            seen_ids[el] = m["id"]
        if nav["place"] == "list":
            key = (m["group"], nav["order"])
            if key in seen_orders:
                out.append(f"{m['id']}: order {nav['order']} in {m['group']} is already {seen_orders[key]}'s")
            seen_orders[key] = m["id"]
        for key in filter(None, [m["id"], (nav.get("plus") or {}).get("nav"), *[u["id"] for u in as_links(m)]]):
            if key in seen_navs:
                out.append(f"{m['id']}: the key {key!r} is already {seen_navs[key]}'s")
            seen_navs[key] = m["id"]
    seen_sections: dict[str, str] = {}
    seen_places: dict[tuple[str, int], str] = {}
    for m in found:
        where = section_of(m)
        if not where:
            continue
        if where[1] in seen_sections:
            out.append(f"{m['id']}: the section {where[1]!r} is already {seen_sections[where[1]]}'s")
        seen_sections[where[1]] = m["id"]
        key = (where[0], m["anatomy"]["order"])
        if key in seen_places:
            out.append(f"{m['id']}: anatomy.order {key[1]} in {key[0]} is already {seen_places[key]}'s")
        seen_places[key] = m["id"]
    out += claim_problems(found)
    if out:
        raise ManifestError("the gene manifests break the contract (GENES.md):\n  "
                            + "\n  ".join(out))
    return found


def claims(m: dict) -> dict[str, list[str]]:
    """What counts as using a gene: what its manifest's `uses` says, with its own link's key and
    the place its route opens at, which are its own without saying so."""
    out = {k: list((m.get("uses") or {}).get(k) or []) for k in USES}
    out["nav"] = [m["id"]] if m.get("nav", {}).get("place") in ("list", "dedicated", "account") else []
    plus = (m.get("nav") or {}).get("plus")
    if plus:
        out["nav"].append(plus["nav"])
    out["nav"] += [u["id"] for u in as_links(m)]
    route = m.get("route") or ""
    where = section_of(m)
    if where:
        # A section of Anatomy is opened at its own name, as each group of Settings was.
        out["settings"] = sorted(set(out["settings"]) | {where[1]})
        return out
    # A gene reached only from elsewhere (`none`) lives inside another's place: its openings are
    # that gene's, not its own.
    if route and route != "/" and m.get("nav", {}).get("place") != "none":
        parts = route.strip("/").split("/")
        if parts[0] == "settings" and len(parts) > 1:
            out["settings"] = sorted(set(out["settings"]) | {"/".join(parts[1:])})
        elif parts[0] not in ("settings", "anatomy"):
            out["places"] = sorted(set(out["places"]) | {parts[0]})
    return out


def section_of(m: dict) -> tuple[str, str] | None:
    """(group, section) of a gene that is a section of one of Anatomy's pages, or None."""
    placed = SECTION_ROUTE.match(m.get("route") or "") if "anatomy" in m else None
    return (placed.group(1), placed.group(2)) if placed else None


def as_links(m: dict) -> list[dict]:
    """The links a gene's link is drawn as, in its place (`nav.as`), in the order they stand:
    each with the key its presses are counted under, its name, its glyph, its address and its
    row's id. Empty for a gene drawn as its own one link."""
    if (m.get("nav") or {}).get("as") != "anatomy":
        return []
    return [{"id": f"anatomy-{gid}", "name": gname, "title": f"{m['name']}, {gname}",
             "icon": ANATOMY_ICONS[gid], "route": f"{ANATOMY_ROOT}/{gid}",
             "row_id": f"nav-anatomy-{gid}"} for gid, gname in ANATOMY]


def links(m: dict) -> list[tuple[str, str]]:
    """Every pressable key a gene's link brings to the navigation, with the name it shows, in
    the order they stand: the link and its plus, or the links it is drawn as."""
    drawn_as = as_links(m)
    if drawn_as:
        return [(u["id"], u["name"]) for u in drawn_as]
    out = [(m["id"], m["name"])]
    plus = m["nav"].get("plus")
    if plus:
        out.append((plus["nav"], plus["name"]))
    return out


def claim_problems(found: Iterable[dict]) -> list[str]:
    """A tool, a place, a job or a purpose counted for two genes would be counted twice."""
    out, seen = [], {}
    for m in found:
        for key, names in claims(m).items():
            if key in ("nav", "places"):
                # Two genes may open at the same place (a page and its group); presses are each one's.
                continue
            for name in names:
                if (key, name) in seen and seen[(key, name)] != m["id"]:
                    out.append(f"{m['id']}: uses.{key} {name!r} is already {seen[(key, name)]}'s")
                seen[(key, name)] = m["id"]
    return out


GENES: tuple[dict, ...] = tuple(read())
BY_ID: dict[str, dict] = {m["id"]: m for m in GENES}
#: Every section of Anatomy, by its name in an address, and the group whose page it is on.
#: Switches do not come into it: an old address of a section that is off still lands somewhere.
SECTIONS: dict[str, str] = {where[1]: where[0] for where in map(section_of, GENES) if where}


def _always(_name: str) -> bool:
    return True


def shown(m: dict, switch_on: Callable[[str], bool] = _always) -> bool:
    """Whether a gene is there for this person: always, unless its switch is off."""
    return not m.get("switch") or bool(switch_on(m["switch"]))


def row_id(m: dict) -> str:
    """The id of a gene's link in the navigation."""
    return m["nav"].get("row") or f"nav-{m['id']}"


def in_list(group: str, genes: Iterable[dict] = GENES) -> list[dict]:
    """A group's links in the order they stand: accepted ones by their order, then
    the lab ones by theirs, last. Never by use."""
    rows = [m for m in genes if m["group"] == group and m["nav"]["place"] == "list"]
    return sorted(rows, key=lambda m: (m["maturity"] == "lab", m["nav"]["order"], m["id"]))


def nav_groups(switch_on: Callable[[str], bool] = _always, extra: Iterable[dict] = ()) -> list[dict]:
    """The six groups with the links under each, ready for the template. `extra` is the
    shared genes in the organisation's lab (`rouh/genelab.py`), drawn after Rouh's own."""
    out = []
    here = [m for m in (*GENES, *extra) if shown(m, switch_on)]
    for gid, gname in GROUPS:
        rows = []
        for m in in_list(gid, here):
            nav = m["nav"]
            rows.append({**m, "row_id": row_id(m), "lab": m["maturity"] == "lab",
                         "opens": nav["opens"], "press": nav.get("press", ""),
                         "controls": nav.get("controls", ""), "css": nav.get("class", ""),
                         "marks": nav.get("marks", []), "plus": nav.get("plus"), "as_links": as_links(m),
                         "hidden": bool(nav.get("while")), "shared": bool(m.get("shared")),
                         "publisher_name": m.get("publisher_name", "")})
        out.append({"id": gid, "name": gname, "icon": GROUP_ICONS[gid], "counted": gid == COUNTED_GROUP,
                    "genes": rows})
    return out


def about(m: dict) -> str:
    """What a gene is, in a line, without its name said first: its title after "Name: ", or
    the whole title where it has no such start. The line under a section in its group's menu."""
    what = m["title"].split(": ", 1)[1] if ": " in m["title"] else m["title"]
    return what[:1].upper() + what[1:]


def anatomy(switch_on: Callable[[str], bool] = _always) -> list[dict]:
    """Anatomy's groups, each with its sections in the order its menu lists them: the one
    list the side list, the menus, the pages, their addresses and the status board are all
    drawn from."""
    out = []
    for gid, gname in ANATOMY:
        rows = []
        for m in GENES:
            where = section_of(m)
            if where and where[0] == gid and shown(m, switch_on):
                rows.append((m["anatomy"]["order"], {"id": where[1], "gene": m["id"], "route": m["route"],
                                                     "name": m["anatomy"].get("name") or m["name"],
                                                     "about": about(m), "icon": m["icon"]}))
        out.append({"id": gid, "name": gname, "route": f"{ANATOMY_ROOT}/{gid}", "icon": ANATOMY_ICONS[gid],
                    "sections": [row for _, row in sorted(rows, key=lambda r: r[0])]})
    return out


def for_page(switch_on: Callable[[str], bool] = _always, extra: Iterable[dict] = ()) -> dict:
    """What the page is handed as JSON: the groups, and every gene it can open, the shared
    genes of the organisation's lab (`extra`) among them."""
    return {
        "groups": [{"id": g, "name": n} for g, n in GROUPS],
        "anatomy": anatomy(switch_on),
        "moved": sorted(MOVED),
        "genes": [{
            "id": m["id"], "name": m["name"], "group": m["group"], "route": m["route"],
            "aliases": m["aliases"], "icon": m["icon"], "maturity": m["maturity"],
            "place": m["nav"]["place"], "opens": m["nav"].get("opens", ""),
            "press": m["nav"].get("press", ""),
            "row": row_id(m) if m["nav"]["place"] == "list" else "",
            "shared": bool(m.get("shared")),
        } for m in (*GENES, *extra) if shown(m, switch_on)],
    }


def nav_keys() -> tuple[tuple[str, str], ...]:
    """Every pressable key of the navigation, `data-nav`, with the name it shows, in
    the order the navigation has them: each group's links (a link's plus right after
    it, and a link drawn as others as those), then the counted rows of the dedicated area."""
    out: list[tuple[str, str]] = []
    for gid in GROUP_IDS:
        for m in in_list(gid):
            out += links(m)
    out += [(m["id"], m["name"]) for m in GENES
            if m["nav"]["place"] == "dedicated" and m["nav"].get("counts")]
    return tuple(out)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def find(words: Iterable[str], switch_on: Callable[[str], bool] = _always, limit: int = 4,
         extra: Iterable[dict] = ()) -> list[dict]:
    """The genes a search's words name, best first: every word must begin a word of
    the gene's name or of one of its aliases. Its name matching beats an alias. `extra`
    is the shared genes of the organisation's lab, found the same way."""
    asked = [w for w in (str(x).lower().strip() for x in words) if w]
    # A letter or two is the start of a word on its way, not a place asked for.
    if len("".join(asked)) < 3:
        return []
    found = []
    for m in (*GENES, *extra):
        if not shown(m, switch_on):
            continue
        name = _words(m["name"])
        best = None
        for rank, said in [(0, name)] + [(1, _words(a)) for a in m["aliases"]]:
            if all(any(w.startswith(a) for w in said) for a in asked):
                best = rank
                break
        if best is not None:
            exact = " ".join(asked) == " ".join(name)
            found.append((0 if exact else 1, best, m["nav"]["place"] != "list", m["name"], m))
    found.sort(key=lambda row: row[:4])
    return [row[-1] for row in found[:limit]]
