"""How often each row of the navigation is pressed, for Settings, Stats.

Petar, 10 October 2026 (fr_e82bf294e064): "Please make a new feature where I see
navigation tap counts. Settings should have stats and for now, stats will have just
each navigation item and the count of taps in a bar chart for total for 30 days
rolling back."

* **The navigation is the rows of the sidebar's `#sbNav`** and the dedicated area under
  it: the links beside the rail of five group boxes, and Rouh, Search and Gene therapy, each marked
  `data-nav="<key>"` in the page with one of the keys in `ITEMS`. The group boxes, the
  account menu, the statuses at the foot and the buttons in the head are not
  navigation, and are not counted.
* **A tap is a press.** Every press of a row is one row of `nav_taps`, with when it
  happened, including a press of the row for the place the person is already on: the
  question is how often each is pressed, and a press is a press. A keyboard shortcut is
  not a press of the row and is not counted.
* **Counts are the person's own**, across every device they are signed in on, keyed by
  their user and their organisation like everything else of theirs.
* **The window rolls.** `counts` adds up the last `DAYS` days back from this moment, so
  a press older than that stops counting on its own. Nothing was counted before this
  shipped, so every row starts at zero, and every item is listed even at zero.

Rows are kept rather than thrown away after the window, so a later stat can look
further back; one row is a few dozen bytes and a person presses a few hundred a month.

Petar, 12 October 2026 (fr_0ef0ca151b48): "can you update stats for the navigation to
take the new double level. we need to have stats for the tabs on the left too. and
maybe make a chart that shows which flows where."

* **Both levels are counted.** The navigation has two levels since that day: the rail
  of five group boxes on the left (Now, Work, Time, Memory, Anatomy, `genes.GROUPS`)
  and the links beside the box that is picked. A press of a box is a row too, under
  `group:<id>`, which no gene's id can be. The boxes were not counted before
  `BOXES_SINCE`, and the page says so rather than showing their zeros as real.
* **Counts come grouped** (`levels`): each box with its own presses and the presses
  of its links, and under it each link; then the dedicated area, which belongs to
  no box.
* **The flow** (`flow`) is where the person went next. Each page load sends an id of
  its own with every press (`visit`), and a journey is that load's presses with no
  pause longer than `PAUSE` between them, so two devices or two tabs at once never
  braid into one. Presses from before the id was sent are one visit per person,
  split the same way. A journey is drawn step by step, the way Google Analytics
  draws its behaviour flow, at either level: by section, where a box and the links
  beside it are the one place, and by link, where only the links are places and a
  box press is the way to one. Pressing the place you are already in again is not a
  move, so a repeat folds into the step before it.
"""
from __future__ import annotations

import time

from . import genes

#: Every row of the navigation, by the key the page sends, in the order the sidebar
#: has them, with the name it shows. Read from the gene registry (`rouh/genes`,
#: GENES.md) since 12 October 2026, so a gene's link is counted the moment its
#: gene puts it in the navigation, and a key no manifest declares is refused.
ITEMS: tuple[tuple[str, str], ...] = genes.nav_keys()
NAMES = dict(ITEMS)
#: Keys a row was counted under before it was renamed, and the key it has now, so its
#: presses from before still count for it: Gene therapy was Feedback until 12 October 2026.
FORMERLY = {"feedback": "gene-therapy"}

#: How far back the chart counts, in days.
DAYS = 30

#: A press of a group box is kept under this before the group's id.
BOX = "group:"
#: The group boxes, by the key a press of one is kept under, with the name each shows.
BOXES: tuple[tuple[str, str], ...] = tuple((BOX + gid, name) for gid, name in genes.GROUPS)
BOX_NAMES = dict(BOXES)
#: The day presses of the links started to be counted, as a time.
LINKS_SINCE = 1791590400.0  # 10 October 2026, 00:00 UTC
#: The day presses of the group boxes started to be counted, and each press carried
#: its page load, as a time.
BOXES_SINCE = 1791763200.0  # 12 October 2026, 00:00 UTC

#: The longest pause inside one journey through the navigation, in seconds.
PAUSE = 30 * 60
#: How many steps of a journey the flow draws, and how many places a step names
#: before the rest are folded into one.
STEPS = 4
PLACES = 5
#: How many of the commonest moves are listed under the flow.
MOVES = 8


class Refused(ValueError):
    """A press that cannot be counted, with what to say about it."""


def _model():
    from .models import NavTap

    return NavTap


def _ids(who) -> tuple[str, str]:
    return str(who.user_id), str(who.org_id)


def record(who, item: str, *, visit: str = "", now: float | None = None) -> None:
    """Count one press of one row of the navigation, or of one of its group boxes.
    `visit` is the page load it was pressed in, for the flow."""
    from .tenancy import GUEST_ORG

    item = str(item or "").strip()
    if item not in NAMES and item not in BOX_NAMES:
        raise Refused(f"There is no navigation item called {item[:40]!r}.")
    user_id, org_id = _ids(who)
    if org_id == GUEST_ORG:
        raise Refused("A guest has no navigation to count.")
    visit = str(visit or "").strip()[:64]
    _model().objects.create(user_id=user_id, org_id=org_id, item=item, visit=visit,
                            at=time.time() if now is None else now)


def _presses(who, since: float, now: float) -> list[tuple[str, str, float]]:
    """This person's presses in the window, (visit, item, at), oldest first, with an
    old key read as the one it has now."""
    user_id, org_id = _ids(who)
    rows = (_model().objects.filter(user_id=user_id, org_id=org_id, at__gte=since, at__lte=now)
            .order_by("at", "id").values_list("visit", "item", "at"))
    return [(visit or "", FORMERLY.get(item, item), at) for visit, item, at in rows]


def _layout() -> tuple[list[tuple[str, str, list[str]]], list[str]]:
    """Each group box, (id, name, the keys of its links in the order they stand), and
    the keys of the dedicated area, which no box holds."""
    boxes = []
    for gid, gname in genes.GROUPS:
        keys = [key for m in genes.in_list(gid) for key, _ in genes.links(m)]
        boxes.append((gid, gname, keys))
    placed = {key for _, _, keys in boxes for key in keys}
    return boxes, [key for key, _ in ITEMS if key not in placed]


def counts(who, *, days: int = DAYS, now: float | None = None, shown: set[str] | None = None,
           presses: list | None = None) -> dict:
    """Both levels and how often this person pressed each in the last `days` days.

    Every group box, in the rail's order, with its own presses (`box`) and the presses
    of its links (`links`), and under it every link, most pressed first and the
    sidebar's order between equals, at zero when it was not pressed; then the
    dedicated area the same way. `shown` holds back a link the person's sidebar does
    not have (Receipts, behind its switch) unless it was pressed.
    """
    now = time.time() if now is None else now
    since = now - days * 86400
    if presses is None:
        presses = _presses(who, since, now)
    got: dict[str, int] = {}
    for _, item, _ in presses:
        got[item] = got.get(item, 0) + 1
    order = {key: i for i, (key, _) in enumerate(ITEMS)}

    def rows(keys):
        out = [{"key": key, "name": NAMES[key], "taps": int(got.get(key, 0))}
               for key in keys if shown is None or key in shown or got.get(key)]
        out.sort(key=lambda it: (-it["taps"], order[it["key"]]))
        return out

    boxes, dedicated = _layout()
    groups = []
    for gid, gname, keys in boxes:
        items = rows(keys)
        groups.append({"id": gid, "name": gname, "box": int(got.get(BOX + gid, 0)),
                       "links": sum(it["taps"] for it in items), "items": items})
    rest = rows(dedicated)
    box_taps = sum(g["box"] for g in groups)
    link_taps = sum(g["links"] for g in groups) + sum(it["taps"] for it in rest)
    return {"days": days, "since": since, "until": now, "boxes_since": BOXES_SINCE, "links_since": LINKS_SINCE,
            "total": box_taps + link_taps, "box_total": box_taps, "link_total": link_taps,
            "groups": groups, "dedicated": rest}


def journeys(presses: list[tuple[str, str, float]], pause: float = PAUSE) -> list[list[str]]:
    """The presses as journeys: each page load's own, split wherever it paused for
    longer than `pause`, in the order they started."""
    started: list[tuple[float, list[str]]] = []
    open_: dict[str, tuple[float, list[str]]] = {}
    for visit, item, at in presses:
        last = open_.get(visit)
        if last is None or at - last[0] > pause:
            path: list[str] = []
            started.append((at, path))
        else:
            path = last[1]
        path.append(item)
        open_[visit] = (at, path)
    return [path for _, path in started]


def _sections() -> dict[str, str]:
    """Where each key is at the level of sections: a box and its links are their
    group, a row of the dedicated area is itself."""
    boxes, dedicated = _layout()
    out = {BOX + gid: gid for gid, _, _ in boxes}
    for gid, _, keys in boxes:
        out.update({key: gid for key in keys})
    out.update({key: key for key in dedicated})
    return out


def flow(presses: list[tuple[str, str, float]], level: str = "sections") -> dict:
    """Where the person went next, step by step, at one level: "sections" or "links".

    `steps` holds a column per step of a journey, up to `STEPS`: the places it was at
    by then, the commonest `PLACES` by name and the rest folded into one, each with
    how many journeys were there (`n`) and how many ended there (`ended`). `links`
    are how many went from a place in one step to a place in the next, and `moves`
    the commonest moves over whole journeys, whatever their step.
    """
    sections = _sections()
    names = {**NAMES, **{gid: name for gid, name in genes.GROUPS}}
    order = {key: i for i, key in enumerate([g for g, _ in genes.GROUPS] + [k for k, _ in ITEMS])}
    paths = []
    for journey in journeys(presses):
        path: list[str] = []
        for item in journey:
            if level == "sections":
                place = sections.get(item)
            else:
                place = None if item.startswith(BOX) else (item if item in NAMES else None)
            if place and (not path or path[-1] != place):
                path.append(place)
        if path:
            paths.append(path)

    kept: list[set[str]] = []
    steps = []
    for i in range(STEPS):
        here: dict[str, list[int]] = {}
        for path in paths:
            if len(path) > i:
                n = here.setdefault(path[i], [0, 0])
                n[0] += 1
                n[1] += len(path) == i + 1
        if not here:
            break
        ranked = sorted(here, key=lambda key: (-here[key][0], order.get(key, 999)))
        top = ranked[:PLACES] if len(ranked) > PLACES + 1 else ranked
        kept.append(set(top))
        nodes = [{"key": key, "name": names.get(key, key), "n": here[key][0], "ended": here[key][1]}
                 for key in top]
        folded = ranked[len(top):]
        if folded:
            nodes.append({"key": "*", "name": f"{len(folded)} more", "more": len(folded),
                          "n": sum(here[k][0] for k in folded), "ended": sum(here[k][1] for k in folded)})
        steps.append({"n": sum(v[0] for v in here.values()), "ended": sum(v[1] for v in here.values()),
                      "nodes": nodes})

    def node(i, key):
        return key if key in kept[i] else "*"

    between: dict[tuple[int, str, str], int] = {}
    moved: dict[tuple[str, str], int] = {}
    for path in paths:
        for i in range(len(path) - 1):
            moved[(path[i], path[i + 1])] = moved.get((path[i], path[i + 1]), 0) + 1
            if i + 1 < len(steps):
                key = (i, node(i, path[i]), node(i + 1, path[i + 1]))
                between[key] = between.get(key, 0) + 1
    links = [{"step": i, "from": a, "to": b, "n": n} for (i, a, b), n in sorted(between.items())]
    moves = sorted(moved.items(), key=lambda kv: (-kv[1], order.get(kv[0][0], 999), order.get(kv[0][1], 999)))
    return {"level": level, "journeys": len(paths), "steps": steps, "links": links,
            "moves": [{"from": a, "to": b, "from_name": names.get(a, a), "to_name": names.get(b, b), "n": n}
                      for (a, b), n in moves[:MOVES]]}


def page(who, *, now: float | None = None) -> dict:
    """Everything Settings, Stats shows on its Navigation tab: the counts at both
    levels, and the flow at each."""
    from . import receipts

    shown = {key for key, _ in ITEMS}
    if not receipts.on(who):
        shown.discard("receipts")
    now = time.time() if now is None else now
    presses = _presses(who, now - DAYS * 86400, now)
    return {"navigation": counts(who, now=now, shown=shown, presses=presses),
            "flow": {"pause_minutes": PAUSE // 60,
                     "sections": flow(presses, "sections"), "links": flow(presses, "links")}}
