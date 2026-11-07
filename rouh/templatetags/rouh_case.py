"""Filters for a case's Step by step table (`templates/rouh/_case_timeline.html`).

``{{ value|case_json }}`` draws a raw value as it was kept, never rebuilt: a dict or a
list, or a string that is JSON, pretty printed with its quote marks in the accent
colour, its colons in amber and its string values in green (Petar, 11 October 2026);
any other string as plain text. Everything is escaped first and only Rouh's own spans
are added, so nothing an email or a model said can reach the page as markup.

``{{ at|case_clock }}`` is a step's time, as the rest of the case page says it.
"""
from __future__ import annotations

import html
import json
import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

#: A JSON string, then whether a colon follows it (a key) or not (a value).
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"(\s*:)?')


def _parsed(value):
    """A string that is a JSON object or list, parsed; anything else as it is."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "[") and text[-1:] in ("}", "]"):
            try:
                return json.loads(text), True
            except ValueError:
                return value, False
        return value, False
    return value, True


def styled_json(value) -> str:
    """Pretty JSON as escaped HTML, with its quotes, colons and strings in spans."""
    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    out, last = [], 0
    for m in _TOKEN.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        body = html.escape(m.group(0)[1:len(m.group(0)) - len(m.group(1) or "") - 1])
        quote = '<span class="j-q">"</span>'
        if m.group(1):
            out.append(f'<span class="j-key">{quote}{body}{quote}</span>'
                       f'{html.escape(m.group(1)[:-1])}<span class="j-colon">:</span>')
        else:
            out.append(f'<span class="j-str">{quote}{body}{quote}</span>')
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


@register.filter
def case_json(value) -> str:
    got, is_json = _parsed(value)
    if is_json and isinstance(got, (dict, list)):
        return mark_safe(f'<pre class="tl-json">{styled_json(got)}</pre>')
    if got in (None, ""):
        return mark_safe('<span class="tl-none">-</span>')
    if is_json and not isinstance(got, str):
        return mark_safe(f'<pre class="tl-json">{styled_json(got)}</pre>')
    return mark_safe(f'<pre class="tl-text">{html.escape(str(got))}</pre>')


@register.filter
def case_size(value) -> int:
    """How long a cell is drawn, to fold the long ones."""
    got, is_json = _parsed(value)
    if is_json and not isinstance(got, str):
        return len(json.dumps(got, indent=2, ensure_ascii=False, default=str))
    return len(str(got or ""))


@register.filter
def case_head(value, most: int = 110) -> str:
    """The first words of a cell, for its folded line."""
    got, is_json = _parsed(value)
    if is_json and isinstance(got, dict):
        text = ", ".join(str(k) for k in list(got)[:6]) + (" ..." if len(got) > 6 else "")
        return "{" + text + "}"
    if is_json and isinstance(got, list):
        return f"{len(got)} item{'s' if len(got) != 1 else ''}"
    text = " ".join(str(got or "").split())
    return text if len(text) <= most else text[:most].rstrip() + "..."


@register.filter
def case_clock(at) -> str:
    from rouh import mail_cases

    try:
        return mail_cases._stamp(float(at)) if at else ""
    except (TypeError, ValueError):
        return str(at or "")
