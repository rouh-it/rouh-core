"""Sheets: reading a Google Sheet tab by tab, and writing into one.

Drive's own export of a Google Sheet is comma-separated text of its **first tab only**, with no
word that the sheet has others, which is all Rouh could read of a sheet until night 29
(1 November 2026, task 94): a price list, a budget or a plan kept over several tabs was read as
its first one, and nothing could be written into a sheet at all. The Sheets API sends every tab
by its name and writes cells by their address; the connection's Drive grant covers both, so no
new access is asked for.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import TYPE_CHECKING

from ..tenancy import Identity

if TYPE_CHECKING:
    from .clients import GoogleClients

log = logging.getLogger("rouh.google")

SPREADSHEET_TYPE = "application/vnd.google-apps.spreadsheet"
#: Only what reading a sheet needs: its title and each tab's name, id, place and size.
FIELDS = "spreadsheetId,properties(title),sheets(properties(sheetId,title,index,hidden,gridProperties))"


def quoted_tab(tab: str) -> str:
    """A tab's name as a range names it: 'Price list' with its own quotes doubled."""
    return "'" + str(tab or "").replace("'", "''") + "'"


class Sheets:
    """Google Sheets: a spreadsheet read tab by tab, and cells written by their address."""

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who

    def _url(self, path: str) -> str:
        return self._clients.base("sheets") + "/v4/spreadsheets" + path

    async def about(self, sheet_id: str) -> dict:
        """{id, title, tabs: [{id, title, index, hidden, rows, columns}]}, in the sheet's order."""
        body = await self._clients.call(
            self._who, "GET", self._url("/" + urllib.parse.quote(sheet_id)),
            params={"fields": FIELDS})
        tabs = []
        for one in body.get("sheets") or []:
            p = one.get("properties") or {}
            grid = p.get("gridProperties") or {}
            tabs.append({"id": p.get("sheetId", 0), "title": str(p.get("title") or ""),
                         "index": int(p.get("index") or 0), "hidden": bool(p.get("hidden")),
                         "rows": int(grid.get("rowCount") or 0),
                         "columns": int(grid.get("columnCount") or 0)})
        tabs.sort(key=lambda t: t["index"])
        return {"id": body.get("spreadsheetId") or sheet_id,
                "title": str((body.get("properties") or {}).get("title") or ""), "tabs": tabs}

    async def values(self, sheet_id: str, ranges: list[str]) -> list[list[list[str]]]:
        """The values of each range, as they are shown in the sheet (formatted), in the same order."""
        if not ranges:
            return []
        body = await self._clients.call(
            self._who, "GET", self._url("/" + urllib.parse.quote(sheet_id) + "/values:batchGet"),
            params=[("ranges", r) for r in ranges] + [("valueRenderOption", "FORMATTED_VALUE"),
                                                      ("majorDimension", "ROWS")])
        out = []
        for one in body.get("valueRanges") or []:
            out.append([[str(c) for c in row] for row in one.get("values") or []])
        while len(out) < len(ranges):
            out.append([])
        return out

    async def write(self, sheet_id: str, at: str, rows: list[list]) -> dict:
        """Write `rows` from the cell range `at`, as if typed (a formula stays a formula)."""
        body = await self._clients.call(
            self._who, "PUT",
            self._url("/" + urllib.parse.quote(sheet_id) + "/values/" + urllib.parse.quote(at, safe="")),
            params={"valueInputOption": "USER_ENTERED", "includeValuesInResponse": "false"},
            json_body={"range": at, "majorDimension": "ROWS", "values": rows})
        return {"range": str(body.get("updatedRange") or at),
                "cells": int(body.get("updatedCells") or 0)}

    async def append(self, sheet_id: str, tab: str, rows: list[list]) -> dict:
        """Add `rows` under the last row of the table in `tab`, as if typed."""
        at = quoted_tab(tab)
        body = await self._clients.call(
            self._who, "POST",
            self._url("/" + urllib.parse.quote(sheet_id) + "/values/"
                      + urllib.parse.quote(at, safe="") + ":append"),
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json_body={"range": at, "majorDimension": "ROWS", "values": rows})
        updates = body.get("updates") or {}
        return {"range": str(updates.get("updatedRange") or at),
                "cells": int(updates.get("updatedCells") or 0)}


_A1 = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d{1,7})$")


def column_name(n: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while n > 0:
        n, rest = divmod(n - 1, 26)
        out = chr(65 + rest) + out
    return out


def column_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def cell(address: str) -> tuple[int, int] | None:
    """'B7' -> (7, 2): row and column, both from 1, or None when it is not one cell's address."""
    found = _A1.match((address or "").strip())
    if not found:
        return None
    return int(found.group(2)), column_number(found.group(1))


def sheet_link(sheet_id: str, tab_id: int | None = None) -> str:
    """The address that opens the sheet in Google Sheets, on one tab when its id is given."""
    link = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    return link + (f"#gid={tab_id}" if tab_id is not None else "")


__all__ = ["FIELDS", "SPREADSHEET_TYPE", "Sheets", "cell", "column_name", "column_number",
           "quoted_tab", "sheet_link"]
