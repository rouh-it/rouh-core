"""The words of an item: cut into passages, checked and rendered.

Nothing is ever cut from an item's text (D25, revised 4 October 2026): quoted
replies and signatures are kept, and the whole text is what becomes passages.

- `passages` cuts the text into pieces of about 400 tokens with 50 of overlap,
  at paragraph boundaries where it can (D24).
- `quote_found` is task 75's check: a claim's quote must be in the raw text
  after spacing, punctuation, quotes and case are normalised (D10).
- `compact` renders an item as the short block of plain lines the model reads,
  kinds in capitals and a handle in brackets, never JSON and never an id (D11, D23).
- `other_alphabet` writes a Latin name in Cyrillic and back, so a search for
  Ivaylo finds Ивайло (D36).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime


def words(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def tokens(text: str) -> int:
    """An estimate: about 1.3 tokens a word, the spec's own rule of thumb."""
    return max(1, int(round(words(text) * 1.3))) if text else 0


#: Characters a token, in what Synapse hands a model: the jump in Claude's input tokens after two synapse_query
#: results in a chat on 24 October 2026 (5,613 for 14,047 characters, 6,201 for 15,784), where `tokens` said
#: half of that. Ids, dates, addresses and titles are many tokens and one word.
HANDED_CHARS = 2.5


def handed(text: str) -> int:
    """The tokens a model is handed in this text, as near as its own count goes (`HANDED_CHARS`)."""
    return max(tokens(text), int(len(text or "") / HANDED_CHARS + 0.999)) if text else 0


def passages(body: str, size: int = 400, overlap: int = 50) -> list[str]:
    """About `size` tokens each, `overlap` shared, cut at paragraphs where possible."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]
    if not paras:
        return []
    out, now = [], []
    for para in paras:
        if now and tokens("\n\n".join(now + [para])) > size:
            out.append("\n\n".join(now))
            tail = " ".join(" ".join(now).split()[-max(0, int(overlap / 1.3)):]) if overlap else ""
            now = [tail] if tail else []
        if tokens(para) > size:
            # A paragraph longer than a passage is cut at sentences.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for s in sentences:
                if now and tokens(" ".join(now + [s])) > size:
                    out.append(" ".join(now))
                    tail = " ".join(" ".join(now).split()[-max(0, int(overlap / 1.3)):]) if overlap else ""
                    now = [tail] if tail else []
                now.append(s)
        else:
            now.append(para)
    if now and " ".join(now).strip():
        out.append("\n\n".join(now))
    return out


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_found(quote: str, raw: str) -> bool:
    q = norm(quote)
    return bool(q) and q in norm(raw)


def first_sentence(text: str, most: int = 30) -> str:
    one = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)[0]
    w = one.split()
    return " ".join(w[:most]) + ("..." if len(w) > most else "")


def short_date(value) -> str:
    """A moment's day on the person's clock (`clock.zone`), never the database's UTC: an email sent at 01:00
    in a zone east of UTC was written down as the day before."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:10]
    if value.tzinfo is not None:
        from ..clock import zone

        value = value.astimezone(zone())
    return value.strftime("%-d %b %Y")


def item_date(item: dict) -> str:
    """The day an item is from, as `short_date` writes it. An all-day calendar event (`calsync`) is its own
    calendar date, whatever clock reads it: its `said_at` is midnight on a clock east of UTC, which in UTC is the day before,
    and Christmas Day read 24 December and New Year's Day 31 December (6 October 2026)."""
    meta = item.get("meta") or {}
    start = str(meta.get("start") or "")
    if (meta.get("gcal") or {}).get("all_day") and re.match(r"^\d{4}-\d{2}-\d{2}$", start):
        return datetime.strptime(start, "%Y-%m-%d").strftime("%-d %b %Y")
    return short_date(item.get("said_at"))


def _people(meta: dict) -> str:
    def name(x):
        return str(x).split("<")[0].strip().strip('"') or str(x)
    sender = meta.get("from")
    to = meta.get("to") or []
    if isinstance(to, str):
        to = [to]
    if sender and to:
        return f"{name(sender)} → {', '.join(name(t) for t in to[:3])}"
    return name(sender) if sender else ""


KIND_WORD = {"fact": "FACT", "ask": "ASK", "promise": "PROMISE", "decision": "DECISION",
             "caveat": "CAVEAT", "disagreement": "DISAGREEMENT", "open": "OPEN", "rule": "RULE"}


def _note_day(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return f"{value.day} {value.strftime('%b')}"


def claim_line(c: dict, note: dict | None = None, refs: dict | None = None) -> str:
    """One claim as the model reads it. `note` is a night of dreaming's note on it (`dreaming.annotate`):
    an ask or promise closed by a later item reads closed, a rule that is a fact reads as its kind, and a
    replaced claim says so, with the number of the item that replaced it when that item is in `refs`."""
    k = str(c.get("k") or "fact")
    if note and note.get("note") == "kind" and note.get("kind_now"):
        k = note["kind_now"]
    kind = KIND_WORD.get(k, "FACT")
    bits = []
    by = (refs or {}).get(str(note.get("by_item"))) if note else None
    if k in ("ask", "promise"):
        if note and note.get("note") == "closed":
            bits.append("closed" + (f" {_note_day(note.get('changed_on'))}" if note.get("changed_on") else "")
                        + (f" by [{by}]" if by else f' by "{note["by_title"][:60]}"' if note.get("by_title") else ""))
        else:
            bits.append("open" if c.get("open") else "closed")
    if c.get("due"):
        bits.append(f"due {c['due']}")
    if note and note.get("note") == "replaced":
        day = _note_day(note.get("changed_on"))
        bits.append("replaced" + (f" {day}" if day else "") + (f" by [{by}]" if by else ""))
        if by:
            # The newer claim is in the pack: the old value is left out, so it can never win (D86).
            return f"{kind} ({', '.join(bits)})"
    head = f"{kind} ({', '.join(bits)})" if bits else kind
    return f"{head}: {c.get('c', '')}"


def is_open(c: dict, note: dict | None = None) -> bool:
    """An ask or promise still open: the X-ray says so and no night has closed or replaced it."""
    return (c.get("k") in ("ask", "promise") and bool(c.get("open"))
            and not (note and note.get("note") in ("closed", "replaced")))


def question_stems(text: str) -> set:
    """The words of a text that say something, cut to their first five letters so a plural or a tense still
    matches, in both alphabets: what `compact` matches an item's claims with (attempt 40)."""
    words = re.findall(r"[^\W_]{4,}|\d+", f"{text} {other_alphabet(text)}".lower())
    return {w[:5] for w in words if w not in _COMMON}


#: Words too common to tell one claim from another.
_COMMON = {"that", "this", "with", "from", "have", "what", "which", "when", "where", "about", "does", "were",
           "been", "will", "they", "them", "their", "there", "into", "than", "then", "also", "only", "petar",
           "rouh"}


def compact(handle: int | str, item: dict, *, raw_chars: int = 900, with_quotes: bool = False,
            refs: dict | None = None, claims_at_most: int = 0, claims_for: set | None = None) -> str:
    """One item as the model reads it (D11). `refs` numbers the other items of the same pack, by id, so a
    note can point at the one that replaced or closed a claim. `claims_at_most`, when given, keeps only that
    many claims, in their order, and says how many more it has (a pack fitted to a budget, attempt 40): those
    that share most words with `claims_for` (`question_stems`), the first ones when none does."""
    meta = item.get("meta") or {}
    if item.get("kind") == "vocabulary":
        # An entry of the person's vocabulary is a meaning, never an instruction (`rouh/vocabulary.py`), and says so.
        from .. import vocabulary

        return (f"[{handle}] vocabulary, {vocabulary.DEFINITION}: "
                + vocabulary.line({"term": meta.get("term") or item.get("title") or "",
                                   "meaning": meta.get("meaning") or "", "aliases": meta.get("aliases") or []})[2:])
    head = [str(item.get("kind") or "item"), item_date(item)]
    who = _people(meta)
    if who:
        head.append(who)
    if item.get("title"):
        head.append(f'"{item["title"]}"')
    if meta.get("layer"):
        head.append(f"{meta['layer']} layer")
    if item.get("alias_of") and (refs or {}).get(str(item["alias_of"])):
        head.append(f"the same as [{refs[str(item['alias_of'])]}]")
    lines = [f"[{handle}] " + " · ".join(h for h in head if h)]
    x = item.get("xray") or {}
    claims = x.get("claims") or []
    notes = item.get("_notes") or {}
    newer = sorted({refs[str(n["by_item"])] for n in notes.values() if n.get("note") == "replaced"
                    and (refs or {}).get(str(n.get("by_item")))})
    if x.get("gist") and claims:
        lines.append("    GIST" + (f" (written before {', '.join(f'[{r}]' for r in newer)} replaced part of it)"
                                   if newer else "") + f": {x['gist']}")
    shown = range(len(claims))
    if claims_at_most and len(claims) > claims_at_most:
        hits = [len(question_stems(str(c.get("c") or "")) & (claims_for or set())) for c in claims]
        shown = sorted(sorted(range(len(claims)), key=lambda i: (-hits[i], i))[:claims_at_most])
    more = len(claims) - len(shown)
    for i in shown:
        c = claims[i]
        note = notes.get(i)
        line = "    " + claim_line(c, note, refs)
        left_out = bool(note and note.get("note") == "replaced" and (refs or {}).get(str(note.get("by_item"))))
        if with_quotes and c.get("q") and not left_out:
            line += f' "{c["q"]}"'
        lines.append(line)
    if more:
        lines.append(f"    ... and {more} more claim{'s' if more > 1 else ''}")
    if not claims:
        body = (item.get("body") or item.get("raw") or "").strip()
        if body:
            text = " ".join(body.split())
            lines.append("    " + (text[:raw_chars] + ("..." if len(text) > raw_chars else "")))
    return "\n".join(lines)


_LAT = {"a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е", "z": "з", "i": "и", "y": "й",
        "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
        "u": "у", "f": "ф", "h": "х", "c": "ц", "w": "в", "q": "к", "x": "кс", "j": "дж"}
_LAT2 = {"zh": "ж", "ch": "ч", "sh": "ш", "sht": "щ", "yu": "ю", "ya": "я", "ts": "ц", "iy": "ий"}
_CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
        "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht",
        "ъ": "a", "ь": "y", "ю": "yu", "я": "ya"}


def other_alphabet(text: str) -> str:
    """The same words in the other alphabet, Bulgarian's way (Ivaylo and Ивайло)."""
    if not text:
        return ""
    if re.search(r"[а-яА-Я]", text):
        return "".join(_CYR.get(ch.lower(), ch) for ch in text)
    out, i, low = [], 0, text.lower()
    while i < len(low):
        for size in (3, 2):
            part = low[i:i + size]
            if part in _LAT2:
                out.append(_LAT2[part])
                i += size
                break
        else:
            out.append(_LAT.get(low[i], low[i]))
            i += 1
    return "".join(out)


def address_of(who: str) -> tuple[str, str]:
    """`Maria Ivanova <maria@x.com>` as (name, address); an address alone names itself."""
    who = (who or "").strip()
    found = re.match(r'^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$', who)
    if found:
        name, addr = found.group(1).strip(), found.group(2).strip().lower()
        return name or addr.split("@")[0], addr
    if "@" in who:
        return who.split("@")[0].replace(".", " ").title(), who.lower()
    return who, ""
