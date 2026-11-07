"""The X-ray of a long report: its argument as a numbered outline, over the page.

The reports the person's assistant writes are long. The task-informed
brainstorm of 29 September 2026 counted them: 38,245 words on task 61's site,
26,865 on the launch playbook, 11,250 with 87 sources on 66-02. A summary
throws most of that away, and what it throws away first is what matters most
when a decision rests on the report: the caveats, the places the sources
disagree, and how sure anybody is. So a report gets an X-ray instead, and the
report stays exactly as it is under it.

    1       one sentence: a claim the report makes
    1.1     one sentence: a reason for it
    1.1.1   one sentence: the evidence under that

Every point is one plain sentence. Opened, it says why (the reasoning, in the
X-ray author's words), shows its evidence as the report's own words, with the
report's own sources beside them, and takes the reader to the passage in the
full report it stands for, lit where it is. The report's answer in one
sentence heads it, and a picture of how the argument stands - which branches
rest on strong evidence, and where the caveats and disagreements are - is
drawn from the outline itself rather than from anything new.

What keeps it honest
--------------------

**Nothing in an X-ray is evidence unless the report says it.** Evidence is a
quote, and a quote is only shown if it is really in the page: the reader's
browser finds it in the page's own text before it is drawn, and a quote it
cannot find is left out and counted, never shown as if it were there. The
sources beside a quote are read out of the page too, from the citation links
around the passage (``<sup class="cite"><a href="#source-3">``, which is the
workspace's own rule for research), so an X-ray cannot name a source the report
does not. ``check`` below does the same search on the server, so the job that
writes an X-ray is told which of its quotes are not in the page before anybody
reads it.

**The report is never changed.** The X-ray is a file of its own beside the
page, named after it: ``index.html`` has ``index.xray.json``. It is put into the
page as the page is sent, the way the Ask AI drawer is (``askai.drawer_head``),
and the page on disk is not touched. The file itself is never served: ``.json``
is not a kind of file ``pages.py`` sends.

**Doubt stays visible.** A point can be a caveat, a disagreement between
sources, or something the report does not know, and each is marked as one and
listed together under Doubts, so the uncertainty the report kept is one press
away rather than compressed out of the summary.

Who writes one
--------------

A job in the workspace, under its ``bb-report-xray`` skill, whenever it builds a
long report, and whenever the person asks for one on a report that has none.
It runs ``python -m rouh.xray check <page>`` and fixes what that says before it
commits. Nothing here asks a model for one: the job has the whole report, its
notes and its sources in front of it, and can check its own work.

The format
----------

::

    {
      "xray": 1,
      "answer": {"claim": "The report's answer, in one sentence.",
                 "quote": "words from the report where it says so"},
      "points": [
        {"claim": "One sentence.",
         "label": "Two to five words",           # optional, for the picture
         "kind": "finding",                       # or caveat, disagreement, open
         "strength": "strong",                    # or moderate, weak, mixed
         "why": "Why the report concludes it.",   # optional
         "quote": "words from the report's passage for this point",
         "evidence": ["exact words from the report", "..."],
         "points": [ ...the same, one level down ]}
      ],
      "figure": {"quote": "words of the heading or caption of the report's own
                           picture that explains it best",
                 "why": "What that picture shows."}   # optional
    }

The numbers are where a point is, 1, 1.2, 1.2.3, and are never written in the
file.
"""
from __future__ import annotations

import html
import json
import logging
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

log = logging.getLogger("rouh.xray")

#: What an X-ray is kept as, beside its page: ``index.html`` -> ``index.xray.json``.
SUFFIX = ".xray.json"

#: The one version of the format there is.
VERSION = 1

#: The kinds of point, and what each is called on the screen.
KINDS = {
    "finding": "",
    "caveat": "Caveat",
    "disagreement": "Sources disagree",
    "open": "Not known yet",
}

#: How strongly the report's evidence backs a point, as the X-ray's author
#: judged it, and what each is called on the screen.
STRENGTHS = {
    "strong": "Strong evidence",
    "moderate": "Moderate evidence",
    "mixed": "Mixed evidence",
    "weak": "Weak evidence",
}

#: The deepest a point may be: 1, 1.1, 1.1.1, 1.1.1.1. The brainstorm asked for
#: three levels; the fourth is room, and ``check`` says when it is used.
DEPTH_MAX = 4

#: How many points one level may hold before the outline stops being one.
SIBLINGS_MAX = 12

#: How many evidence quotes one point may carry.
EVIDENCE_MAX = 8

#: The longest claim, why, label and quote kept, in characters. A claim longer
#: than this is not one sentence any more.
CLAIM_MAX = 400
WHY_MAX = 1200
LABEL_MAX = 60
QUOTE_MAX = 1200

#: The shortest quote, counted in letters and digits: anything shorter is found
#: in too many places to say where a point came from.
QUOTE_MIN = 12

#: The largest X-ray read. The largest report in the workspace would need a
#: small fraction of it.
FILE_MAX = 2_000_000


class Invalid(ValueError):
    """An X-ray file that cannot be used, saying why."""


# --------------------------------------------------------------------------
# The page's own words, the way a quote is looked for in them
# --------------------------------------------------------------------------

#: Elements whose content is never read as the page's words.
_SKIP = {"script", "style", "template", "noscript", "head", "title"}
#: Elements with no end tag, which never open a skipped region.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        if tag == "body":
            # A head that was never closed ends where the body begins.
            self._skip = [one for one in self._skip if one != "head"]
            return
        if tag in _SKIP:
            self._skip.append(tag)

    def handle_endtag(self, tag):
        if self._skip and self._skip[-1] == tag:
            self._skip.pop()

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def page_text(source: str) -> str:
    """The words of a page, as a reader sees them, from its HTML.

    Everything in ``<body>`` that is text, whether or not the part of the page
    it is on is showing at the moment: a report that switches between pages
    of its own keeps all of them in the one file.
    """
    parser = _Text()
    parser.feed(source)
    parser.close()
    return " ".join(parts.strip() for parts in parser.parts if parts.strip())


def key(text: str) -> str:
    """The letters and digits of ``text``, lower case, and nothing else.

    It is what a quote and a page are compared by, here and in the browser
    (``xkey`` in xray.js does the same). A quote copied out of a report differs
    from the page in all the ways that do not matter - curly or straight
    quotes, a dash or a hyphen, two spaces or a line break, a footnote number
    that ran into the word before it, words split across two elements - and in
    none that do.
    """
    return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())


# --------------------------------------------------------------------------
# Reading an X-ray file
# --------------------------------------------------------------------------


def path_for(page: Path) -> Path:
    """Where the X-ray of ``page`` is kept."""
    return page.with_name(page.stem + SUFFIX)


def _string(value, most: int, where: str, what: str, needed: bool = False) -> str:
    if value is None or value == "":
        if needed:
            raise Invalid(f"{where} has no {what}.")
        return ""
    if not isinstance(value, str):
        raise Invalid(f"{where}: {what} is not text.")
    said = " ".join(value.split())
    if len(said) > most:
        raise Invalid(f"{where}: {what} is {len(said)} characters, and the most is {most}.")
    return said


def _node(raw, number: str, depth: int) -> dict:
    where = f"Point {number}"
    if not isinstance(raw, dict):
        raise Invalid(f"{where} is not an object.")
    kind = raw.get("kind") or "finding"
    if kind not in KINDS:
        raise Invalid(f"{where}: kind is {kind!r}, and it is one of {', '.join(KINDS)}.")
    strength = raw.get("strength") or ""
    if strength and strength not in STRENGTHS:
        raise Invalid(f"{where}: strength is {strength!r}, and it is one of "
                      f"{', '.join(STRENGTHS)}.")
    evidence = raw.get("evidence") or []
    if not isinstance(evidence, list):
        raise Invalid(f"{where}: evidence is not a list of quotes.")
    if len(evidence) > EVIDENCE_MAX:
        raise Invalid(f"{where} has {len(evidence)} pieces of evidence, and the most is "
                      f"{EVIDENCE_MAX}.")
    node = {
        "claim": _string(raw.get("claim"), CLAIM_MAX, where, "claim", needed=True),
        "label": _string(raw.get("label"), LABEL_MAX, where, "label"),
        "kind": kind,
        "strength": strength,
        "why": _string(raw.get("why"), WHY_MAX, where, "why"),
        "quote": _string(raw.get("quote"), QUOTE_MAX, where, "quote", needed=True),
        "evidence": [_string(one, QUOTE_MAX, where, "a piece of evidence", needed=True)
                     for one in evidence],
        "points": _level(raw.get("points"), number, depth + 1),
    }
    return node


def _level(raw, above: str, depth: int) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise Invalid(f"The points under {above or 'the answer'} are not a list.")
    if not raw:
        return []
    if depth > DEPTH_MAX:
        raise Invalid(f"Point {above} has points under it, and {DEPTH_MAX} levels is the most.")
    if len(raw) > SIBLINGS_MAX:
        raise Invalid(f"There are {len(raw)} points under {above or 'the answer'}, and "
                      f"{SIBLINGS_MAX} is the most.")
    return [_node(one, f"{above}.{i}" if above else str(i), depth)
            for i, one in enumerate(raw, start=1)]


def parse(data) -> dict:
    """An X-ray as it is drawn, from the file's JSON, or Invalid saying why.

    Only the fields the format has are kept, every string has its spaces
    folded, and nothing is invented: a field left out stays empty.
    """
    if not isinstance(data, dict):
        raise Invalid("An X-ray is a JSON object.")
    if data.get("xray") != VERSION:
        raise Invalid(f'An X-ray says "xray": {VERSION} at its top.')
    answer = data.get("answer")
    if not isinstance(answer, dict):
        raise Invalid('There is no "answer": the report\'s answer in one sentence.')
    points = _level(data.get("points"), "", 1)
    if not points:
        raise Invalid("There are no points.")
    figure = data.get("figure")
    shown = {
        "answer": {
            "claim": _string(answer.get("claim"), CLAIM_MAX, "The answer", "claim", True),
            "quote": _string(answer.get("quote"), QUOTE_MAX, "The answer", "quote"),
        },
        "points": points,
        "figure": None,
    }
    if figure:
        if not isinstance(figure, dict):
            raise Invalid("figure is not an object.")
        shown["figure"] = {
            "quote": _string(figure.get("quote"), QUOTE_MAX, "The figure", "quote", True),
            "why": _string(figure.get("why"), WHY_MAX, "The figure", "why"),
        }
    return shown


def read(page: Path) -> dict | None:
    """The X-ray beside ``page``, parsed, or None when it has none.

    A file that is there and cannot be used is None too, with a line in the
    log: the page is still the page, and a broken X-ray over it would be worse
    than none. ``check`` is what says why.
    """
    where = path_for(page)
    try:
        if not where.is_file() or where.is_symlink():
            return None
        if where.stat().st_size > FILE_MAX:
            log.warning("xray: %s is larger than %d bytes and is not drawn", where, FILE_MAX)
            return None
        return parse(json.loads(where.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, Invalid) as err:
        log.warning("xray: %s is not drawn: %s", where, err)
        return None


# --------------------------------------------------------------------------
# Checking one against its page
# --------------------------------------------------------------------------


def _walk(points: list[dict], above: str = ""):
    for i, node in enumerate(points, start=1):
        number = f"{above}.{i}" if above else str(i)
        yield number, node
        yield from _walk(node["points"], number)


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?:\s+|$)(?=[A-Z0-9\"'(]|$)", text.strip())) or 1


def check(page: Path) -> tuple[list[str], list[str], dict]:
    """What is wrong with the X-ray beside ``page``, and what could be better.

    Errors are what stop it being drawn, or would draw something the report
    does not say: a file that is not the format, and a quote that is not in the
    page. Warnings are the shape the brainstorm asked for and the page has
    not quite got: a claim of more than one sentence, a first level of fewer
    than three or more than seven points, a quote found in several places, so
    that "read it in the report" could land on the wrong one.

    The third value counts what is there, for the line the command prints.
    """
    errors: list[str] = []
    warnings: list[str] = []
    counts = {"points": 0, "quotes": 0, "levels": 0}
    where = path_for(page)
    if not where.is_file():
        return [f"There is no X-ray beside {page.name}: it would be {where.name}."], [], counts
    try:
        xray = parse(json.loads(where.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, Invalid) as err:
        return [f"{where.name}: {err}"], [], counts
    try:
        words = key(page_text(page.read_text(encoding="utf-8", errors="replace")))
    except OSError as err:
        return [f"{page.name} cannot be read: {err}"], [], counts

    def look(quote: str, whose: str, what: str) -> None:
        counts["quotes"] += 1
        wanted = key(quote)
        shown = quote if len(quote) <= 80 else quote[:77] + "..."
        if len(wanted) < QUOTE_MIN:
            errors.append(f"{whose}: {what} \"{shown}\" is too short to say where it is; "
                          f"quote at least {QUOTE_MIN} letters.")
            return
        found = words.find(wanted)
        if found < 0:
            errors.append(f"{whose}: {what} \"{shown}\" is not in the page. Copy it from the "
                          "report word for word.")
        elif words.find(wanted, found + 1) >= 0:
            warnings.append(f"{whose}: {what} \"{shown}\" is in the page more than once; the "
                            "first is the one shown. Quote a little more to make it one.")

    answer = xray["answer"]
    if _sentences(answer["claim"]) > 1:
        warnings.append("The answer is more than one sentence.")
    if answer["quote"]:
        look(answer["quote"], "The answer", "its quote")
    else:
        warnings.append("The answer has no quote, so it cannot be read in the report.")
    first = len(xray["points"])
    if not 3 <= first <= 7:
        warnings.append(f"The first level has {first} points; three to seven reads best.")
    for number, node in _walk(xray["points"]):
        counts["points"] += 1
        counts["levels"] = max(counts["levels"], number.count(".") + 1)
        whose = f"Point {number}"
        if _sentences(node["claim"]) > 1:
            warnings.append(f"{whose}'s claim is more than one sentence.")
        look(node["quote"], whose, "its quote")
        for one in node["evidence"]:
            look(one, whose, "evidence")
    if xray["figure"]:
        look(xray["figure"]["quote"], "The figure", "its quote")
    if counts["levels"] > 3:
        warnings.append(f"The outline is {counts['levels']} levels deep; three reads best.")
    return errors, warnings, counts


# --------------------------------------------------------------------------
# Into the page
# --------------------------------------------------------------------------

#: The X-ray's own two files, in the folder the drawer's are in.
FILES = ("xray.css", "xray.js")


def head(root, rel: str) -> bytes:
    """The X-ray of the page at ``rel``, ready to go into its head, or nothing.

    ``rel`` is the page's path in the workspace, already checked by whoever
    asked for the drawer. What goes in is the parsed X-ray, the layer's style
    sheet as text (it draws in a shadow root of its own, so no report's styles
    reach it and none of its reach the report) and its script as a ``data:``
    address, because a framed page cannot fetch anything.
    """
    from . import askai

    if not root or not rel.lower().endswith(".html"):
        return b""
    try:
        base = Path(root).resolve()
        page = (base / rel).resolve()
        page.relative_to(base)
    except (OSError, ValueError):
        return b""
    xray = read(page)
    if xray is None:
        return b""
    css_name, js_name = FILES
    script = askai.asset_url(js_name)
    try:
        css = (askai.DRAWER_DIR / css_name).read_text(encoding="utf-8")
    except OSError:
        css = ""
    if not script or not css:
        log.warning("xray: %s is served without its X-ray: %s or %s could not be read",
                    rel, css_name, js_name)
        return b""
    said = (f"<script>window.ROUH_XRAY = "
            f"{askai.script_json({'xray': xray, 'css': css, 'kinds': KINDS, 'strengths': STRENGTHS})};"
            f"</script>\n"
            f'<script src="{html.escape(script, quote=True)}" defer></script>\n')
    return said.encode("utf-8", "surrogateescape")


# --------------------------------------------------------------------------
# The command a job runs before it commits one
# --------------------------------------------------------------------------

USAGE = """\
python -m rouh.xray check <page.html>   what is wrong with the X-ray beside a page
python -m rouh.xray text <page.html>    the page's words, as quotes are looked for in them
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("check", "text"):
        sys.stderr.write(USAGE)
        return 2
    page = Path(argv[1])
    if not page.is_file():
        sys.stderr.write(f"There is no page at {page}.\n")
        return 2
    if argv[0] == "text":
        sys.stdout.write(page_text(page.read_text(encoding="utf-8", errors="replace")) + "\n")
        return 0
    errors, warnings, counts = check(page)
    for line in errors:
        print(f"error: {line}")
    for line in warnings:
        print(f"warning: {line}")
    if errors:
        print(f"{path_for(page).name}: {len(errors)} error(s). It is not drawn until they "
              "are fixed." if not counts["points"] else
              f"{path_for(page).name}: {len(errors)} error(s). A quote that is not in the page "
              "is left out when the X-ray is drawn; fix them.")
        return 1
    print(f"{path_for(page).name}: {counts['points']} points, {counts['levels']} levels, "
          f"{counts['quotes']} quotes, every one of them in the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
