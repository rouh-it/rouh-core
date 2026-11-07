"""Google Sheets read tab by tab: the part two genes of night 29 share, and the first of them,
**Sheets read tab by tab**.

Built by the nightly feature run, night 29, 1 November 2026 (task 94, idea I-170). Until tonight
Rouh read a Google Sheet only through Drive's export, which is comma-separated text of the
sheet's **first tab** and nothing else, with no word that there are others: a price list, a
budget or a plan kept over several tabs was read as its first tab, and a question about the
second had an answer made up from the first, or none.

The Sheets API names every tab and sends each one's cells (`google_api/sheets.py`). This module:

- `sheet`: one spreadsheet read tab by tab, kept a few minutes, so the second gene of the night,
  **Written into a sheet** (`rouh/sheet_write.py`), can check a tab's name and rows against what
  was just read without asking Google again.
- **Sheets read tab by tab** (switch `sheet_tabs`, invisible): while it is on, `read_doc` on a
  Google Sheet gives every tab by its name, in the sheet's order, each with its rows numbered
  and its columns lettered, as the sheet shows them (formatted values: "€1,200", "12%"), and
  which tabs are hidden, to a chat, a job and Ask AI alike. One Sheets call for the tabs and
  one for their values, made only for a sheet; no model.

**Whose.** The sheets the connected Google account can open (`org_id` and `user_id`); nothing
is written by this gene.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("rouh.sheet_tabs")

SWITCH = "sheet_tabs"
TITLE = ("Sheets read tab by tab: a Google Sheet is read with every tab by its name, rows "
         "numbered and columns lettered, not only its first tab")
SPREADSHEET = "application/vnd.google-apps.spreadsheet"
#: How long a sheet read is kept for the next read of it.
FRESH = 300.0
#: The most of a sheet said to the model, and the most rows of one tab.
MOST_CHARS = 200_000
MOST_ROWS = 2_000
_held: dict[tuple, tuple[float, dict]] = {}


def on(who, switch: str = SWITCH) -> bool:
    from . import switches

    return switches.on(switch, getattr(who, "org_id", None) or None)


def forget() -> None:
    _held.clear()


async def sheet(services, who, sheet_id: str, *, fresh: bool = False) -> dict:
    """{id, title, tabs: [{id, title, index, hidden, rows: [[str]]}]}, kept for `FRESH` seconds."""
    from .google_api.sheets import quoted_tab

    key = (getattr(who, "org_id", ""), getattr(who, "user_id", ""), sheet_id)
    held = _held.get(key)
    if held and not fresh and time.time() - held[0] < FRESH:
        return held[1]
    about = await services.sheets.about(sheet_id)
    values = await services.sheets.values(sheet_id, [quoted_tab(t["title"]) for t in about["tabs"]])
    tabs = [dict(t, rows=rows) for t, rows in zip(about["tabs"], values)]
    got = {"id": about["id"], "title": about["title"], "tabs": tabs}
    _held[key] = (time.time(), got)
    return got


def _clip(text: str, most: int = 300) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def said(read: dict, changed: str = "") -> str:
    """A sheet as `read_doc` gives it: every tab by its name, rows numbered, columns lettered."""
    from .google_api.sheets import column_name, sheet_link

    tabs = read.get("tabs") or []
    names = ", ".join(
        f"{t['title']!r}" + (" (hidden)" if t.get("hidden") else "")
        + f" {len(t.get('rows') or [])} rows" for t in tabs)
    lines = [f"{read.get('title') or 'A sheet'} - Google Sheet, id {read.get('id')}, "
             f"{len(tabs)} tab{'s' if len(tabs) != 1 else ''}: {names}"]
    if changed:
        lines.append(changed)
    lines.append(
        "Read tab by tab, every tab, as the sheet shows its values. Each row starts with its "
        "number and each cell is in its column's letter's place, so a cell is named "
        "'Tab'!B7. A tab opens at " + sheet_link(read.get("id") or "", None) + "#gid=<its gid>.")
    for n, t in enumerate(tabs, start=1):
        rows = t.get("rows") or []
        width = max((len(r) for r in rows), default=0)
        lines.append("")
        lines.append(f"=== Tab {n} of {len(tabs)}: {t['title']} (gid {t['id']})"
                     + (", hidden" if t.get("hidden") else "")
                     + f", {len(rows)} rows, columns A to {column_name(width) if width else 'A'} ===")
        if not rows:
            lines.append("(empty)")
            continue
        lines.append("    " + " | ".join(column_name(c) for c in range(1, width + 1)))
        for i, row in enumerate(rows[:MOST_ROWS], start=1):
            if not any(str(c).strip() for c in row):
                continue
            lines.append(f"{i}: " + " | ".join(_clip(c) for c in row))
        if len(rows) > MOST_ROWS:
            lines.append(f"… {len(rows) - MOST_ROWS} more rows in this tab are cut here.")
    text = "\n".join(lines)
    if len(text) > MOST_CHARS:
        text = text[:MOST_CHARS].rstrip() + "\n… the rest of the sheet is cut here."
    return text


async def read_doc_text(google, sheet_id: str, changed: str = "") -> str:
    """What read_doc says of a sheet while the switch is on, or "" to read it as before."""
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return ""
    services = google.services()
    if getattr(services, "sheets", None) is None:
        return ""
    try:
        read = await sheet(services, who, sheet_id, fresh=True)
    except Exception as exc:  # noqa: BLE001 - Drive's export is read instead
        log.info("the sheet %s could not be read tab by tab: %r", sheet_id, exc)
        return ""
    from . import evolution

    tabs = read.get("tabs") or []
    await asyncio.to_thread(
        evolution.used, SWITCH, "read", who=who,
        detail=f"a Google Sheet of {len(tabs)} tab{'s' if len(tabs) != 1 else ''} read tab by tab")
    return said(read, changed)


__all__ = ["SPREADSHEET", "SWITCH", "TITLE", "forget", "on", "read_doc_text", "said", "sheet"]
