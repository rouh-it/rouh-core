"""Written into a sheet: asked in words, Rouh writes cells or adds rows in a Google Sheet, and says
what each cell held before.

Built by the nightly feature run, night 29, 1 November 2026 (task 94, idea I-171). Rouh could
write a Google Doc (`edit_doc`) and replace a whole Drive file, but not one cell of a Google
Sheet: "put 1,200 in the March column of the budget", "add Dana's quote as a row in the vendors
sheet" or "change the seat price on the Pricing tab to 49" had no tool, and replacing the file
from Drive would have turned a sheet of several tabs into one tab of text. So asking for it was
a manual step left to ‹him›.

So, while its switch is on, the tool **edit_sheet** writes into a Google Sheet the connected
Google account can edit, through the Sheets API (`google_api/sheets.py`): single cells by their
address ("B7"), a block of rows from a cell, or rows added under the last row of a tab. Values
go in as if typed, so "=SUM(B2:B9)" stays a formula and "12%" a percentage. Before it writes it
reads the tab (`sheet_tabs.sheet`), refuses a tab the sheet does not have (naming those it has),
and its answer says, for every cell it changed, what was there before, so a wrong cell can be
put back in words. Nothing is ever deleted: a cell is only overwritten, and rows only added.

**Whose.** The sheets the connected Google account can edit (`org_id` and `user_id`). It writes
only what ‹he› asked for in words, in a chat or a job of ‹his›; a sheet's own words never ask
for a write.

**Its switch** is `sheet_write` (`rouh/switches.py`): off, the tool says so and writes nothing.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.sheet_write")

SWITCH = "sheet_write"
TITLE = ("Written into a sheet: asked in words, Rouh writes cells or adds rows in a Google Sheet "
         "and says what each cell held before")
TOOL_NAME = "edit_sheet"
#: The most cells one call may write.
MOST_CELLS = 500
DESCRIPTION = (
    "Write into a Google Sheet: set cells by their address, write a block of rows from a cell, "
    "or add rows under the last row of a tab. Use it when the person asks for something to be "
    "put, changed or added in a spreadsheet ('put 1,200 in B7 of the budget', 'add a row for "
    "Dana's quote to the vendors sheet', 'change the seat price on the Pricing tab to 49'). "
    "Read the sheet with read_doc first, so you know its tabs, its rows' numbers and its columns' "
    "letters. Values go in as if typed: a formula like =SUM(B2:B9) stays a formula. `tab` is the "
    "tab's name (the first tab when left out). Give `cells` for single cells, `rows` with `at` "
    "for a block whose top-left cell is `at`, or `append` for new rows at the end. It never "
    "deletes anything. Say back what was written, and what the changed cells held before.")
SCHEMA = {
    "type": "object",
    "properties": {
        "sheet": {"type": "string", "description": "The Google Sheet: its link, its id or its name."},
        "tab": {"type": "string", "description": "The tab's name. The first tab when left out."},
        "cells": {"type": "array", "description": "Single cells to set.",
                  "items": {"type": "object",
                            "properties": {"at": {"type": "string", "description": "Like B7."},
                                           "value": {"type": "string"}},
                            "required": ["at", "value"]}},
        "rows": {"type": "array", "description": "A block of rows, each a list of values, "
                                                  "written from the cell `at`.",
                 "items": {"type": "array", "items": {"type": "string"}}},
        "at": {"type": "string", "description": "The top-left cell for `rows`, like A12."},
        "append": {"type": "array", "description": "Rows to add under the tab's last row.",
                   "items": {"type": "array", "items": {"type": "string"}}},
    },
    "required": ["sheet"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _rows(raw) -> list[list[str]]:
    out = []
    for row in raw or []:
        if isinstance(row, (list, tuple)):
            out.append([_value(c) for c in row])
        elif row is not None:
            out.append([_value(row)])
    return out


def _was(rows: list[list[str]], r: int, c: int) -> str:
    if r - 1 < len(rows):
        line = rows[r - 1]
        if c - 1 < len(line):
            return str(line[c - 1])
    return ""


def plan(read: dict, args: dict) -> tuple[dict | None, list[dict], str]:
    """(the tab, [{kind: cell|block|append, ...}], why not) for what was asked."""
    from .google_api.sheets import cell

    tabs = read.get("tabs") or []
    if not tabs:
        return None, [], "That sheet has no tabs to write in."
    wanted = str(args.get("tab") or "").strip()
    if wanted:
        tab = next((t for t in tabs if t["title"] == wanted), None) or next(
            (t for t in tabs if t["title"].casefold() == wanted.casefold()), None)
        if tab is None:
            names = ", ".join(repr(t["title"]) for t in tabs)
            return None, [], f"The sheet has no tab called {wanted!r}. Its tabs are {names}."
    else:
        tab = tabs[0]
    todo: list[dict] = []
    count = 0
    for one in args.get("cells") or []:
        if not isinstance(one, dict):
            continue
        where = cell(str(one.get("at") or ""))
        if where is None:
            return tab, [], f"{one.get('at')!r} is not a cell's address. A cell is named like B7."
        todo.append({"kind": "cell", "row": where[0], "col": where[1], "rows": [[_value(one.get("value"))]]})
        count += 1
    block = _rows(args.get("rows"))
    if block:
        where = cell(str(args.get("at") or "A1"))
        if where is None:
            return tab, [], f"{args.get('at')!r} is not a cell's address. A block starts at a cell like A12."
        todo.append({"kind": "block", "row": where[0], "col": where[1], "rows": block})
        count += sum(len(r) for r in block)
    added = _rows(args.get("append"))
    if added:
        todo.append({"kind": "append", "rows": added})
        count += sum(len(r) for r in added)
    if not todo:
        return tab, [], "Say what to write: cells, rows with the cell they start at, or rows to add."
    if count > MOST_CELLS:
        return tab, [], f"That is {count} cells; at most {MOST_CELLS} are written in one go."
    return tab, todo, ""


def _changes(tab: dict, todo: list[dict]) -> list[str]:
    """For each overwritten cell, "B7: «1,000» → «1,200»"; a cell that was empty is said as such."""
    from .google_api.sheets import column_name

    rows = tab.get("rows") or []
    out = []
    for one in todo:
        if one["kind"] == "append":
            continue
        for i, line in enumerate(one["rows"]):
            for j, value in enumerate(line):
                r, c = one["row"] + i, one["col"] + j
                before = _was(rows, r, c)
                if before == value:
                    continue
                out.append(f"{column_name(c)}{r}: " + (f"«{before}»" if before else "(empty)")
                           + f" → «{value}»")
    return out


async def answer(google, args: dict) -> str:
    """What edit_sheet says, having written what was asked for."""
    from . import evolution, sheet_tabs
    from .google_api import GoogleSaidNo
    from .google_api.sheets import column_name, quoted_tab

    blocked = google.not_ready_because()
    if blocked:
        return blocked
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return "Writing into a Google Sheet is switched off (Evolution, Mutations: Written into a sheet)."
    named = str(args.get("sheet") or "").strip()
    if not named:
        return "Say which sheet, by its link, its id or its name."
    services = google.services()
    from .tools import _find_doc, _google_trouble

    try:
        sheet_id, kind = await _find_doc(services.drive, named)
        if kind and kind != sheet_tabs.SPREADSHEET:
            return f"{named!r} is not a Google Sheet, so it has no cells to write in."
        read = await sheet_tabs.sheet(services, who, sheet_id, fresh=True)
    except GoogleSaidNo as exc:
        return _google_trouble(exc)
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        return _google_trouble(exc)
    tab, todo, why_not = plan(read, args)
    if why_not:
        return why_not
    changed = _changes(tab, todo)
    done = []
    try:
        for one in todo:
            if one["kind"] == "append":
                got = await services.sheets.append(sheet_id, tab["title"], one["rows"])
                done.append(f"added {len(one['rows'])} row{'s' if len(one['rows']) != 1 else ''} "
                            f"at {got['range']}")
            else:
                at = f"{quoted_tab(tab['title'])}!{column_name(one['col'])}{one['row']}"
                got = await services.sheets.write(sheet_id, at, one["rows"])
                done.append(f"wrote {got['cells'] or sum(len(r) for r in one['rows'])} "
                            f"cell{'s' if (got['cells'] or 2) != 1 else ''} at {got['range']}")
    except Exception as exc:  # noqa: BLE001 - said in Google's words, with what was done before it
        said = _google_trouble(exc)
        return (said + (" Before that: " + "; ".join(done) + "." if done else ""))
    sheet_tabs.forget()
    from .google_api.sheets import sheet_link

    said = (f"In {read.get('title') or 'the sheet'!r}, tab {tab['title']!r}: " + "; ".join(done) + "."
            + (" Changed: " + "; ".join(changed[:40])
               + (f"; and {len(changed) - 40} more." if len(changed) > 40 else ".") if changed else "")
            + f" It opens at {sheet_link(sheet_id, tab['id'])}.")
    wrote = getattr(google, "wrote", None)
    if callable(wrote):
        wrote(TOOL_NAME, sheet_id, said)
    cells = sum(sum(len(r) for r in one["rows"]) for one in todo)
    await asyncio.to_thread(evolution.used, SWITCH, "written", who=who,
                            detail=f"{cells} cell{'s' if cells != 1 else ''} written into a Google Sheet")
    return said


__all__ = ["DESCRIPTION", "MOST_CELLS", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "on", "plan"]
