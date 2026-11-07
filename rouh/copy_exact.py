"""Copy kept word for word: copy given to Ask AI for a page is checked on the page, word for word.

Built by the nightly feature run, night 21, 24 October 2026 (task 94, idea I-125). The copy of
‹his› company's site is written on Rouh's pages, and the person writing it pastes each version
into Ask AI section by section: "[Section: Hero]", then "Eyebrow: ...", "Headline: ...",
"Body: ...". On 23 October 2026 five such pastes went into one task's page in an evening, with
"make no other text changes than what is provided", "Only change copy if it has changed in what I
provided" and, for a change of layout, "Keep all copy exactly as written". Ask AI answers that it
has done it, and whether every line really is on the page as given, letter for letter, was left
to the reader to find out by proofreading the page against the paste.

So, while its switch is on, every Ask AI answer that changed the page is checked by code, with no
model call:

- **Copy given.** Each line of copy in the question (`given`): a line labelled as copy
  ("Headline:", "Body:", "Eyebrow:", "CTA:" and the like, `COPY_LABELS`), and every line of a
  "[Section: ...]" block, which runs to the next blank line. A label that is not copy ("Design
  notes:", "Problem:") and the section markers themselves are left out; "[ Book a call ]" is the
  words on the button.
- **Copy kept.** A change asked for with the copy to stay as it is ("keep all copy exactly as
  written", "don't change the text") and no copy given: the words a reader sees on the page are
  the same before and after (`kept_words`).

When a line given is not on the page word for word, or words changed that were to stay, Ask AI is
told so in the same answer, with the lines, and puts them right with the same edit tool. Whatever
is still not right when it has finished is named under its answer, so the reader knows without
proofreading. Quotes, dashes and spaces are compared as a reader sees them: a curly apostrophe is
the same as a straight one, and so is a line broken differently.

**Whose.** The page being changed and the words of the question, nothing else; for an invited
guest it counts for the page's owner.

**Its switch** is `copy_exact` (`rouh/switches.py`): off, Ask AI answers as it did before.
"""
from __future__ import annotations

import difflib
import html
import logging
import re

log = logging.getLogger("rouh.copy_exact")

SWITCH = "copy_exact"

#: Labels that put copy on a page, by their lowercase words.
COPY_LABELS = frozenset({
    "eyebrow", "kicker", "overline", "headline", "heading", "header", "title", "h1", "h2", "h3",
    "subheadline", "sub-headline", "subheading", "subhead", "sub-head", "subtitle", "deck",
    "body", "body copy", "copy", "text", "lead", "intro", "paragraph", "tagline", "caption",
    "label", "quote", "pull quote", "cta", "primary cta", "secondary cta", "button", "link",
    "button text", "cta text", "question", "answer", "q", "a", "bullet", "note line"})
#: The most lines checked, and the longest named back in full.
MOST_LINES = 120
SHOWN = 160

_SECTION = re.compile(r"\[\s*section\s*:[^\]]*\]\s*(?:\([^)]*\))?\s*", re.I)
_LABEL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&-]{0,28}?)\s*:\s*(.+?)\s*$")
_TAGGED = re.compile(r"^\[[A-Za-z][\w -]{0,20}\]\s")
_BUTTON = re.compile(r"\[\s*([^\[\]]{1,80}?)\s*\]")
_KEEP = re.compile(
    r"\b(?:keep|leave|preserve)\b[^.\n]{0,30}\b(?:copy|text|wording|words)\b[^.\n]{0,30}"
    r"\b(?:exactly|as (?:it is|is|written|they are)|unchanged|the same|word for word|intact)\b"
    r"|\b(?:do not|don'?t|dont|never|without)\s+(?:change|touch|edit|alter|rewrite)\s+"
    r"(?:the |any |any of the )?(?:copy|text|wording|words)\b", re.I)
_TAGS = re.compile(r"<(script|style|template|noscript)\b.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SAME = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
                       "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
                       "\u2013": "-", "\u2014": "-", "\u2011": "-", "\u2212": "-",
                       "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u00ad": "", "\u200b": ""})


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def same(text: str) -> str:
    """Text as compared: quotes, dashes and spaces as a reader sees them."""
    return " ".join(html.unescape(str(text or "")).translate(_SAME).split())


def shown(markup: str) -> str:
    """The words a reader sees on a page, as one line."""
    body = _TAGS.sub(" ", markup or "")
    return same(_TAG.sub(" ", body))


def _copy_of(value: str) -> list[str]:
    """A value as it goes on the page: "[ Book a call ]" is the words on its button, and two
    buttons are two; a note in brackets ("[Design: three cards]") is not copy at all."""
    value = value.strip()
    buttons = _BUTTON.findall(value)
    if buttons and not _BUTTON.sub("", value).strip(" ,;|/"):
        return [b.strip() for b in buttons if ":" not in b and b.strip()]
    return [value] if value else []


def given(question: str) -> dict:
    """{lines, keep}: the copy lines the question gives, and whether it asks the copy to stay."""
    lines: list[str] = []
    in_section = False
    for raw in str(question or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            in_section = False
            continue
        # A marker ends what was before it on its line ("Here is the copy. [Section: Hero]").
        marker = _SECTION.search(line)
        if marker:
            in_section = True
            line = line[marker.end():].strip()
            if not line:
                continue
        label = _LABEL.match(line)
        if label:
            name = " ".join(label.group(1).lower().split())
            if name in COPY_LABELS:
                lines.extend(_copy_of(label.group(2)))
            else:
                # Any other label is an instruction ("Design: two cards"), never copy, and so is
                # what follows it until the next section.
                in_section = False
            continue
        if line.startswith("[") and (line.endswith("]") and ":" in line or _TAGGED.match(line)):
            # "[Image: a screenshot of ...]" or "[Flow] ...": a note for the designer.
            continue
        if line.endswith(":"):
            # "Design notes:" heads instructions, not copy.
            in_section = False
            continue
        if in_section:
            for words in _copy_of(line):
                if len(words.split()) >= 2 or _BUTTON.search(line):
                    lines.append(words)
    seen, out = set(), []
    for one in lines:
        key = same(one)
        if key and key not in seen:
            seen.add(key)
            out.append(one)
    return {"lines": out[:MOST_LINES], "keep": not out and bool(_KEEP.search(str(question or "")))}


def wants(question: str) -> bool:
    found = given(question)
    return bool(found["lines"] or found["keep"])


def missing(lines: list[str], markup: str) -> list[str]:
    """The lines given that are not on the page word for word."""
    page = shown(markup)
    return [one for one in lines if same(one) not in page]


def kept_words(before: str, after: str) -> list[str]:
    """Where the words a reader sees changed, as "was -> now" pairs; [] when they are the same."""
    was, now = shown(before).split(), shown(after).split()
    if was == now:
        return []
    out = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=was, b=now, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        old, new = " ".join(was[a1:a2]), " ".join(now[b1:b2])
        out.append(f'"{_cut(old)}" became "{_cut(new)}"' if old and new
                   else f'"{_cut(old)}" was taken out' if old else f'"{_cut(new)}" was added')
        if len(out) >= 12:
            break
    return out


def _cut(text: str, most: int = SHOWN) -> str:
    return text if len(text) <= most else text[:most - 3].rstrip() + "..."


def problems(question: str, before: str, after: str) -> dict:
    """{missing, changed}: what is not right on the page against what the question asked."""
    found = given(question)
    if found["lines"]:
        return {"missing": missing(found["lines"], after), "changed": [],
                "lines": len(found["lines"])}
    if found["keep"]:
        return {"missing": [], "changed": kept_words(before, after), "lines": 0}
    return {"missing": [], "changed": [], "lines": 0}


def tell_model(found: dict) -> str:
    """What Ask AI is told after its edit when something is not right, or ""."""
    if found["missing"]:
        listed = "\n".join(f"- {one}" for one in found["missing"])
        return ("\n\nChecked against the question: these lines of copy you were given are not on "
                "the page word for word. Put each on the page exactly as given (the same words, "
                "spelling and punctuation; the section labels stay off the page), with edit_page, "
                "then say what you changed:\n" + listed)
    if found["changed"]:
        listed = "\n".join(f"- {one}" for one in found["changed"])
        return ("\n\nChecked against the question: the copy was to stay exactly as written, and "
                "these words a reader sees changed. Put the words back as they were, keeping the "
                "change of layout, with edit_page:\n" + listed)
    return ""


def tell_reader(found: dict) -> str:
    """The line under the answer when something is still not right after Ask AI finished, or ""."""
    if found["missing"]:
        many = len(found["missing"])
        head = ("One line you gave is" if many == 1 else f"{many} lines you gave are")
        return (f"\n\n{head} not on the page word for word yet:\n"
                + "\n".join(f"- {_cut(one)}" for one in found["missing"][:12]))
    if found["changed"]:
        return ("\n\nThe copy was to stay as written, and these words changed:\n"
                + "\n".join(f"- {one}" for one in found["changed"][:12]))
    return ""


def counted_for(who, page_org: str = ""):
    """Whose use it is: the reader, or the page's owner when a guest asked."""
    if not page_org:
        return who
    from . import evolution

    return evolution._owner()


def checked(who, page_org: str, detail: str) -> None:
    """What landed on the page was checked against the question, after Ask AI changed it."""
    from . import evolution

    evolution.used("copy_exact", "checked", who=counted_for(who, page_org), detail=detail)


def corrected(who, page_org: str, detail: str) -> None:
    """Ask AI was told what was not on the page as given, to put it right."""
    from . import evolution

    evolution.used("copy_exact", "corrected", who=counted_for(who, page_org), detail=detail)


__all__ = ["SWITCH", "given", "kept_words", "checked", "corrected", "missing", "on", "problems", "same", "shown",
           "tell_model", "tell_reader", "wants"]
