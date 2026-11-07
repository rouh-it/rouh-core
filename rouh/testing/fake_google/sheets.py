"""Sheets registration for the Google stand-in (`rouh/google_api/sheets.py`).

A spreadsheet is seeded by a test with ``POST /_sheet`` ``{"id", "name", "tabs": [{"title",
"rows": [[...]], "hidden"?}], "parents"?}``: it becomes a Google Sheet in Drive whose export, as
Drive's own does, is comma-separated text of its **first tab only**. ``GET /v4/spreadsheets/<id>``
names its tabs, ``.../values:batchGet`` reads ranges (a whole tab, or ``'Tab'!A1:C9``), ``PUT
.../values/<range>`` writes cells from a range's first cell and ``POST .../values/<tab>:append``
adds rows under the last one, the way the Sheets API does with ``USER_ENTERED`` (here a value is
kept as it was sent). ``GET /_sheet/<id>`` hands a test the tabs as they are now.
"""
from __future__ import annotations

import csv
import io
import re

from . import ACCOUNT_EMAIL, JSONResponse, Request, _owner_permission

SPREADSHEET = "application/vnd.google-apps.spreadsheet"


def _first_tab_csv(sheet: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in (sheet["tabs"][0]["rows"] if sheet["tabs"] else []):
        writer.writerow(row)
    return out.getvalue()


def _col(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_name(n: int) -> str:
    out = ""
    while n > 0:
        n, rest = divmod(n - 1, 26)
        out = chr(65 + rest) + out
    return out



def _parse(sheet: dict, address: str):
    """(tab, first row, first col, last row or None, last col or None) for a range address."""
    address = address.strip()
    if "!" in address:
        name, cells = address.split("!", 1)
    elif any(t["title"] == address.strip("'").replace("''", "'") for t in sheet["tabs"]):
        name, cells = address, ""
    else:
        name, cells = "", address
    name = name.strip()
    if name.startswith("'") and name.endswith("'"):
        name = name[1:-1].replace("''", "'")
    tab = next((t for t in sheet["tabs"] if t["title"] == name), None) if name else sheet["tabs"][0]
    if tab is None:
        return None
    if not cells:
        return tab, 1, 1, None, None
    m = re.match(r"^([A-Za-z]{1,3})(\d+)?(?::([A-Za-z]{1,3})(\d+)?)?$", cells.strip())
    if not m:
        return None
    r1 = int(m.group(2) or 1)
    c1 = _col(m.group(1))
    c2 = _col(m.group(3)) if m.group(3) else (c1 if m.group(2) and not m.group(3) else None)
    r2 = int(m.group(4)) if m.group(4) else (r1 if m.group(2) and not m.group(3) else None)
    return tab, r1, c1, r2, c2


def _sheets_routes(app, world, seen, note, file_named):
    world.setdefault("sheets", {})

    @app.post("/_sheet")
    async def seed_sheet(request: Request):
        got = await request.json()
        sheet_id = str(got.get("id") or "")
        tabs = [{"id": i * 1000 + 7 if i else 0, "title": str(t.get("title") or f"Sheet{i + 1}"),
                 "hidden": bool(t.get("hidden")),
                 "rows": [[str(c) for c in row] for row in t.get("rows") or []]}
                for i, t in enumerate(got.get("tabs") or [])]
        sheet = {"id": sheet_id, "name": str(got.get("name") or "Untitled spreadsheet"), "tabs": tabs}
        world["sheets"][sheet_id] = sheet
        found = file_named(sheet_id)
        if found is None:
            found = {"id": sheet_id, "mimeType": SPREADSHEET, "parents": got.get("parents") or ["root"],
                     "trashed": False, "owners": [{"displayName": "Alex Morgan",
                                                    "emailAddress": ACCOUNT_EMAIL}],
                     "permissions": [_owner_permission()]}
            world["files"].append(found)
        found.update({"name": sheet["name"], "content": _first_tab_csv(sheet),
                      "modifiedTime": got.get("modifiedTime") or "2026-10-30T12:00:00Z",
                      "webViewLink": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"})
        note("sheet seeded", {"id": sheet_id, "tabs": len(tabs)})
        return JSONResponse({"ok": True})

    @app.get("/_sheet/{sheet_id}")
    async def sheet_now(sheet_id: str):
        sheet = world["sheets"].get(sheet_id)
        if sheet is None:
            return JSONResponse({"error": "no such sheet"}, status_code=404)
        return JSONResponse(sheet)

    def _missing(sheet_id: str):
        return JSONResponse({"error": {"code": 404, "message": "Requested entity was not found."}},
                            status_code=404)

    @app.get("/v4/spreadsheets/{sheet_id}")
    async def read_sheet(sheet_id: str, request: Request):
        seen["api"].append(str(request.url))
        sheet = world["sheets"].get(sheet_id)
        if sheet is None:
            return _missing(sheet_id)
        return JSONResponse({
            "spreadsheetId": sheet_id, "properties": {"title": sheet["name"]},
            "sheets": [{"properties": {"sheetId": t["id"], "title": t["title"], "index": i,
                                       **({"hidden": True} if t["hidden"] else {}),
                                       "gridProperties": {
                                           "rowCount": max(1000, len(t["rows"])),
                                           "columnCount": max(26, max((len(r) for r in t["rows"]),
                                                                      default=0))}}}
                       for i, t in enumerate(sheet["tabs"])]})

    def _cut(tab, r1, c1, r2, c2):
        rows = tab["rows"]
        last_r = r2 or len(rows)
        out = []
        for r in range(r1, last_r + 1):
            row = rows[r - 1] if r - 1 < len(rows) else []
            last_c = c2 or len(row)
            out.append([row[c - 1] if c - 1 < len(row) else "" for c in range(c1, last_c + 1)])
        while out and not any(out[-1]):
            out.pop()
        return [_trim(r) for r in out]

    def _trim(row):
        row = list(row)
        while row and row[-1] == "":
            row.pop()
        return row

    @app.get("/v4/spreadsheets/{sheet_id}/values:batchGet")
    async def batch_get(sheet_id: str, request: Request):
        seen["api"].append(str(request.url))
        sheet = world["sheets"].get(sheet_id)
        if sheet is None:
            return _missing(sheet_id)
        out = []
        for address in request.query_params.getlist("ranges"):
            parsed = _parse(sheet, address)
            if parsed is None:
                return JSONResponse({"error": {"code": 400, "message": f"Unable to parse range: {address}"}},
                                    status_code=400)
            values = _cut(*parsed)
            out.append({"range": address, "majorDimension": "ROWS", **({"values": values} if values else {})})
        return JSONResponse({"spreadsheetId": sheet_id, "valueRanges": out})

    def _put(tab, r1, c1, values):
        rows = tab["rows"]
        for i, row in enumerate(values):
            r = r1 + i
            while len(rows) < r:
                rows.append([])
            line = rows[r - 1]
            for j, value in enumerate(row):
                c = c1 + j
                while len(line) < c:
                    line.append("")
                line[c - 1] = "" if value is None else str(value)

    def _refresh(sheet):
        found = file_named(sheet["id"])
        if found is not None:
            found["content"] = _first_tab_csv(sheet)

    @app.put("/v4/spreadsheets/{sheet_id}/values/{address:path}")
    async def write_values(sheet_id: str, address: str, request: Request):
        seen["api"].append(str(request.url))
        sheet = world["sheets"].get(sheet_id)
        if sheet is None:
            return _missing(sheet_id)
        parsed = _parse(sheet, address)
        if parsed is None:
            return JSONResponse({"error": {"code": 400, "message": f"Unable to parse range: {address}"}},
                                status_code=400)
        tab, r1, c1, _r2, _c2 = parsed
        values = (await request.json()).get("values") or []
        _put(tab, r1, c1, values)
        _refresh(sheet)
        cells = sum(len(r) for r in values)
        last = f"{_col_name(c1 + max((len(r) for r in values), default=1) - 1)}{r1 + len(values) - 1}"
        note("sheet written", {"id": sheet_id, "range": address, "values": values})
        return JSONResponse({"spreadsheetId": sheet_id,
                             "updatedRange": f"'{tab['title']}'!{_col_name(c1)}{r1}:{last}",
                             "updatedCells": cells})

    @app.post("/v4/spreadsheets/{sheet_id}/values/{address:path}")
    async def append_values(sheet_id: str, address: str, request: Request):
        seen["api"].append(str(request.url))
        if not address.endswith(":append"):
            return JSONResponse({"error": {"code": 404, "message": "Not found"}}, status_code=404)
        sheet = world["sheets"].get(sheet_id)
        if sheet is None:
            return _missing(sheet_id)
        parsed = _parse(sheet, address[: -len(":append")])
        if parsed is None:
            return JSONResponse({"error": {"code": 400, "message": "Unable to parse range"}},
                                status_code=400)
        tab = parsed[0]
        values = (await request.json()).get("values") or []
        while tab["rows"] and not any(tab["rows"][-1]):
            tab["rows"].pop()
        start = len(tab["rows"]) + 1
        _put(tab, start, 1, values)
        _refresh(sheet)
        last = f"{_col_name(max((len(r) for r in values), default=1))}{start + len(values) - 1}"
        note("sheet appended", {"id": sheet_id, "tab": tab["title"], "values": values})
        return JSONResponse({"spreadsheetId": sheet_id, "updates": {
            "updatedRange": f"'{tab['title']}'!A{start}:{last}",
            "updatedCells": sum(len(r) for r in values)}})
