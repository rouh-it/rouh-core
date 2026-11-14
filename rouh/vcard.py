"""vCards: reading the ones iCloud holds, and changing only what was asked.

iCloud keeps every contact as a vCard 3.0 file (RFC 2426). A card carries far
more than Rouh reads - a photo as a page of base64, postal addresses, related
people, Apple's own `X-AB...` lines and its `item1.` groups that tie a phone
number to the label it was given. None of that may be lost because the
assistant changed somebody's organisation.

So a card is never rebuilt from the fields Rouh understands. `Card` keeps
every line exactly as it arrived, and an edit touches the lines it has to and
no others: changing a birthday rewrites the `BDAY` line, adding a number adds
one `TEL` line, and the photo is still the same bytes afterwards. Only a new
contact is written from scratch.

What Rouh reads out of a card is `Person`: the name, every phone number and
email address with the label the phone shows beside it, the organisation, the
birthday, the note, where the photo is (`photo_of`), and whether it is a person at all - iCloud keeps contact
groups as vCards too (`X-ADDRESSBOOKSERVER-KIND:group`), and a group is never
a person anybody meant.

The labels are Apple's. A number is labelled either by its TYPE parameters
(``TEL;type=CELL;type=VOICE``) or, for anything Apple has no TYPE for, by an
``X-ABLabel`` line in the same group (``item1.TEL`` and ``item1.X-ABLabel``),
written ``_$!<Mobile>!$_`` for Apple's own labels and as plain text for one the
person made up. Both are read, and both are written the way the phone writes
them, so a number Rouh adds looks on the phone like one typed into it.

Folding follows the RFC: a line is at most 75 octets, continuation lines start
with one space, and a fold never splits a UTF-8 character, which is the mistake
that turns a Cyrillic name into two replacement characters on the phone.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: The longest line, in octets, before it is folded (RFC 2425 5.8.1).
FOLD = 75

#: What goes in PRODID on a card Rouh writes from nothing.
PRODID = "-//Rouh//Contacts//EN"

#: Apple's own label names, as they appear between `_$!<` and `>!$_`, said the
#: way the phone says them.
APPLE_LABELS = {
    "mobile": "mobile", "iphone": "iPhone", "home": "home", "work": "work",
    "main": "main", "homefax": "home fax", "workfax": "work fax",
    "otherfax": "other fax", "pager": "pager", "other": "other",
    "icloud": "iCloud", "school": "school", "homepage": "homepage",
}

#: The other way: a label as a person says it, to how Apple writes its own.
APPLE_RAW = {"other": "Other", "mobile": "Mobile", "home": "Home", "work": "Work",
             "main": "Main", "pager": "Pager", "home fax": "HomeFAX",
             "work fax": "WorkFAX", "iphone": "iPhone"}

#: A phone label, as a person says it, to the TYPE parameters the phone writes
#: for it. A label that is not here is a custom one and goes in X-ABLabel.
PHONE_TYPES = {
    "mobile": ("CELL", "VOICE"), "cell": ("CELL", "VOICE"),
    "iphone": ("IPHONE", "CELL", "VOICE"), "home": ("HOME", "VOICE"),
    "work": ("WORK", "VOICE"), "main": ("MAIN",), "home fax": ("HOME", "FAX"),
    "work fax": ("WORK", "FAX"), "pager": ("PAGER",), "other": ("OTHER", "VOICE"),
}

#: The same for email. "other" has no TYPE of its own on Apple's side.
EMAIL_TYPES = {"home": ("INTERNET", "HOME"), "work": ("INTERNET", "WORK")}

#: The same for a postal address (ADR), read and written by night 43's gene `postal_address`.
ADDRESS_TYPES = {"home": ("HOME",), "work": ("WORK",)}

#: The parts of a postal address after the post office box and the extended address, in ADR's order.
ADDRESS_PARTS = ("street", "city", "region", "postal_code", "country")

#: TYPE values that say nothing a person would call a label.
_NOT_LABELS = {"voice", "pref", "internet", "x400", "msg", "text"}

_ESCAPED = re.compile(r"\\(.)", re.DOTALL)
_ITEM = re.compile(r"^item(\d+)$", re.IGNORECASE)
_DATE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")
_NO_YEAR = re.compile(r"^--(\d{2})-?(\d{2})")

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


class BadField(ValueError):
    """A value that cannot go into a card, with the sentence that says why."""


# --- escaping ----------------------------------------------------------------


def escape(text: str) -> str:
    """A text value, escaped for a vCard line."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return (text.replace("\\", "\\\\").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def unescape(value: str) -> str:
    return _ESCAPED.sub(lambda m: "\n" if m.group(1) in "nN" else m.group(1), value or "")


def split_structured(value: str) -> list[str]:
    """The parts of a structured value (N, ORG), each unescaped."""
    parts, current, i = [], [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            current.append(value[i:i + 2])
            i += 2
            continue
        if ch == ";":
            parts.append(unescape("".join(current)))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append(unescape("".join(current)))
    return parts


def _split_outside_quotes(text: str, sep: str) -> list[str]:
    out, current, quoted = [], [], False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        if ch == sep and not quoted:
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
    out.append("".join(current))
    return out


def fold(line: str) -> str:
    """One logical line as the lines the file holds, never splitting a character."""
    chunks, current, size = [], [], 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        limit = FOLD if not chunks else FOLD - 1   # a continuation starts with a space
        if size + width > limit and current:
            chunks.append("".join(current))
            current, size = [ch], width
        else:
            current.append(ch)
            size += width
    chunks.append("".join(current))
    return "\r\n ".join(chunks)


def unfold(text: str) -> list[str]:
    """The logical lines of a file, continuation lines joined back on."""
    out: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        elif raw.strip():
            out.append(raw)
    return out


# --- one line ---------------------------------------------------------------


@dataclass
class Prop:
    """One property line. `raw` is the line as it arrived, kept to write back."""

    name: str
    value: str = ""
    params: list[tuple[str, str]] = field(default_factory=list)
    group: str = ""
    raw: str | None = None

    @classmethod
    def parse(cls, line: str) -> Prop | None:
        quoted = False
        for i, ch in enumerate(line):
            if ch == '"':
                quoted = not quoted
            elif ch == ":" and not quoted:
                break
        else:
            return None
        head, value = line[:i], line[i + 1:]
        parts = _split_outside_quotes(head, ";")
        name, group = parts[0].strip(), ""
        if "." in name:
            group, name = name.split(".", 1)
        params: list[tuple[str, str]] = []
        for part in parts[1:]:
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                key, val = part.split("=", 1)
                params.append((key.strip().upper(), val.strip().strip('"')))
            else:
                params.append(("TYPE", part))      # vCard 2.1's bare TEL;CELL
        return cls(name=name.upper(), value=value, params=params, group=group, raw=line)

    def types(self) -> set[str]:
        out: set[str] = set()
        for key, val in self.params:
            if key == "TYPE":
                out.update(v.strip().lower() for v in val.split(",") if v.strip())
        return out

    def param(self, key: str) -> str | None:
        for name, val in self.params:
            if name == key.upper():
                return val
        return None

    def text(self) -> str:
        return unescape(self.value)

    def line(self) -> str:
        if self.raw is not None:
            return self.raw
        head = (self.group + "." if self.group else "") + self.name
        for key, val in self.params:
            needs_quotes = any(c in val for c in ",;:")
            head += f";{key.lower() if key == 'TYPE' else key}=" + (f'"{val}"' if needs_quotes else val)
        return head + ":" + self.value


# --- one card ---------------------------------------------------------------


class Card:
    """Every line of one vCard, in order, between BEGIN and END."""

    def __init__(self, props: list[Prop]) -> None:
        self.props = props

    @classmethod
    def parse(cls, text: str) -> Card:
        props: list[Prop] = []
        inside = False
        for line in unfold(text):
            upper = line.strip().upper()
            if upper == "BEGIN:VCARD":
                if inside:
                    break                       # a second card: only the first is read
                inside = True
                continue
            if upper == "END:VCARD":
                break
            if not inside:
                continue
            prop = Prop.parse(line)
            if prop is not None:
                props.append(prop)
        if not inside:
            raise BadField("That is not a vCard: it has no BEGIN:VCARD.")
        return cls(props)

    def text(self) -> str:
        lines = ["BEGIN:VCARD", *(p.line() for p in self.props), "END:VCARD"]
        return "".join(fold(line) + "\r\n" for line in lines)

    def all(self, name: str) -> list[Prop]:
        return [p for p in self.props if p.name == name.upper()]

    def first(self, name: str) -> Prop | None:
        found = self.all(name)
        return found[0] if found else None

    def value(self, name: str) -> str:
        prop = self.first(name)
        return prop.text() if prop else ""

    def label_of(self, prop: Prop) -> str:
        """The label the phone shows beside a number or an address."""
        if prop.group:
            for other in self.props:
                if other.group.lower() == prop.group.lower() and other.name == "X-ABLABEL":
                    return _apple_label(other.text())
        kinds = prop.types() - _NOT_LABELS
        if "iphone" in kinds:
            return "iPhone"
        if "cell" in kinds:
            return "mobile"
        if "fax" in kinds:
            return "home fax" if "home" in kinds else "work fax" if "work" in kinds else "fax"
        for word in ("main", "pager", "home", "work", "other"):
            if word in kinds:
                return word
        return ""

    def set(self, name: str, value: str, params: list[tuple[str, str]] | None = None) -> None:
        """One line of this name, in place of any there were, or none for ''."""
        existing = self.all(name)
        if not value:
            self.props = [p for p in self.props if p.name != name.upper()]
            return
        fresh = Prop(name=name.upper(), value=value, params=list(params or []))
        if existing:
            where = self.props.index(existing[0])
            self.props = [p for p in self.props if p.name != name.upper()]
            self.props.insert(where, fresh)
        else:
            self.props.append(fresh)

    def remove(self, prop: Prop) -> None:
        """One line, and its group's label with it when nothing else is left in it."""
        self.props = [p for p in self.props if p is not prop]
        if not prop.group:
            return
        rest = [p for p in self.props if p.group.lower() == prop.group.lower()]
        if all(p.name.startswith("X-AB") for p in rest):
            self.props = [p for p in self.props if p.group.lower() != prop.group.lower()]

    def next_item(self) -> str:
        used = [int(m.group(1)) for p in self.props if (m := _ITEM.match(p.group or ""))]
        return f"item{max(used, default=0) + 1}"


def _apple_label(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("_$!<") and text.endswith(">!$_"):
        inner = text[4:-4]
        return APPLE_LABELS.get(inner.lower().replace(" ", ""), inner.lower())
    return text


# --- what Rouh reads out of a card -----------------------------------------------


@dataclass
class Person:
    uid: str = ""
    name: str = ""
    phones: list[dict] = field(default_factory=list)
    emails: list[dict] = field(default_factory=list)
    organisation: str = ""
    birthday: str = ""
    note: str = ""
    #: The card's Job title (TITLE), read and written by night 42's gene `job_title`.
    title: str = ""
    #: The card's postal addresses (ADR), each {"address": one line, "label", "parts"}; read and written by
    #: night 43's gene `postal_address`.
    addresses: list[dict] = field(default_factory=list)
    #: "individual", or "group" for one of iCloud's contact groups.
    kind: str = "individual"
    #: Where the card's picture is, without its bytes (`photo_of`), or {} for none.
    photo: dict = field(default_factory=dict)


def read(text: str) -> Person:
    card = Card.parse(text)
    kind = (card.value("X-ADDRESSBOOKSERVER-KIND") or card.value("KIND") or "").strip().lower()
    org_parts = [p.strip() for p in split_structured(card.first("ORG").value)] \
        if card.first("ORG") else []
    organisation = ", ".join(p for p in org_parts if p)
    name = card.value("FN").strip()
    if not name and card.first("N"):
        family, given, middle, prefix, suffix = (split_structured(card.first("N").value)
                                                 + [""] * 5)[:5]
        name = " ".join(p.strip() for p in (prefix, given, middle, family, suffix) if p.strip())
    if not name:
        name = organisation
    phones = []
    for prop in card.all("TEL"):
        number = prop.text().strip()
        if number:
            phones.append({"number": number, "label": card.label_of(prop)})
    emails = []
    for prop in card.all("EMAIL"):
        address = prop.text().strip()
        if address:
            emails.append({"address": address, "label": card.label_of(prop)})
    return Person(
        uid=card.value("UID").strip(),
        name=name,
        phones=phones,
        emails=emails,
        organisation=organisation,
        birthday=_birthday_of(card.first("BDAY")),
        note=card.value("NOTE").strip(),
        title=card.value("TITLE").strip(),
        addresses=addresses_of(card),
        kind="group" if kind == "group" else "individual",
        photo=photo_of(card),
    )


_CROP = re.compile(r"^ABClipRect_1&(-?\d+)&(-?\d+)&(\d+)&(\d+)(?:&|$)")


def photo_of(card: Card) -> dict:
    """Where the card's picture is: {"kind": "inline", "type", "digest"} for one carried in the card as
    base64, {"kind": "uri", "uri"} for one at an address (iCloud's own photo server, or another host, as
    an iPhone writes `PHOTO;VALUE=uri:https://...`), each with "crop" [x, y, width, height] when Apple
    kept the part of the picture the phone shows (`X-ABCROP-RECTANGLE`, measured from the bottom left).
    {} when the card has no picture. The bytes are never read here: `contact_photos` fetches and keeps
    them."""
    import hashlib

    prop = card.first("PHOTO")
    if prop is None or not prop.value.strip():
        return {}
    value = prop.value.strip()
    out: dict = {}
    crop = _CROP.match(prop.param("X-ABCROP-RECTANGLE") or "")
    if crop:
        x, y, w, h = (int(v) for v in crop.groups())
        if w > 0 and h > 0:
            out["crop"] = [x, y, w, h]
    kinds = prop.types() | {(prop.param("VALUE") or "").lower(), (prop.param("ENCODING") or "").lower()}
    if value.lower().startswith("data:"):
        head = value[5:].split(",", 1)[0]
        out.update(kind="inline", type=head.split(";")[0] or "image/jpeg")
    elif "uri" in kinds or re.match(r"^https?://", value, re.IGNORECASE):
        if not re.match(r"^https?://", value, re.IGNORECASE):
            return {}
        out.update(kind="uri", uri=value)
    elif "b" in kinds or "base64" in kinds:
        found = next((t for t in prop.types() if t in ("jpeg", "jpg", "png", "gif", "heic", "webp")), "jpeg")
        out.update(kind="inline", type="image/" + ("jpeg" if found == "jpg" else found))
    else:
        return {}
    # Of the whole line, so a new crop of the same picture is a new face too.
    out["digest"] = hashlib.sha256((prop.raw or value).encode()).hexdigest()[:16]
    return out


def _birthday_of(prop: Prop | None) -> str:
    """"1985-03-12", or "--03-12" when the year is not known, or ""."""
    if prop is None:
        return ""
    value = prop.value.strip()
    found = _NO_YEAR.match(value)
    if found:
        return f"--{found.group(1)}-{found.group(2)}"
    found = _DATE.match(value)
    if not found:
        return ""
    year, month, day = found.groups()
    # Apple writes a birthday with no year as year 1604 and says so in a
    # parameter, because vCard 3.0 cannot leave the year out.
    omitted = prop.param("X-APPLE-OMIT-YEAR")
    if (omitted and omitted.strip() == year) or year == "1604":
        return f"--{month}-{day}"
    return f"{year}-{month}-{day}"


def birthday_words(birthday: str) -> str:
    """"12 March 1985", or "12 March" when the year is not known."""
    found = _NO_YEAR.match(birthday or "")
    if found:
        month, day = int(found.group(1)), int(found.group(2))
        return f"{day} {MONTHS[month - 1]}" if 1 <= month <= 12 else birthday
    found = _DATE.match(birthday or "")
    if not found:
        return birthday or ""
    year, month, day = (int(g) for g in found.groups())
    return f"{day} {MONTHS[month - 1]} {year}" if 1 <= month <= 12 else birthday


def check_birthday(text: str) -> str:
    """A birthday as a person or the model gave it, tidied, or BadField."""
    text = (text or "").strip()
    if not text:
        return ""
    found = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if found:
        year, month, day = int(found.group(1)), int(found.group(2)), int(found.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    found = re.fullmatch(r"-{0,2}(\d{1,2})-(\d{1,2})", text)
    if found:
        month, day = int(found.group(1)), int(found.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"--{month:02d}-{day:02d}"
    raise BadField(f"\"{text}\" is not a birthday I can save. Give it as YYYY-MM-DD, "
                   "or --MM-DD when the year is not known.")


# --- writing ------------------------------------------------------------------


def _name_parts(name: str) -> str:
    """N for a name: the last word is the family name, the rest the given."""
    words = name.split()
    if len(words) <= 1:
        return ";" + escape(name) + ";;;"
    return escape(words[-1]) + ";" + escape(" ".join(words[:-1])) + ";;;"


def _bday_params(birthday: str) -> tuple[str, list[tuple[str, str]]]:
    found = _NO_YEAR.match(birthday)
    if found:
        return f"1604-{found.group(1)}-{found.group(2)}", [
            ("X-APPLE-OMIT-YEAR", "1604"), ("VALUE", "date")]
    return birthday, [("VALUE", "date")]


def digits_of(number: str) -> str:
    return re.sub(r"\D", "", number or "")


def same_number(a: str, b: str) -> bool:
    """Whether two ways of writing a number are the same number.

    "+359 888 123 456", "00359888123456" and "0888 123 456" are one phone, so
    the last nine digits decide it whenever both have that many.
    """
    da, db = digits_of(a), digits_of(b)
    if not da or not db:
        return False
    if len(da) >= 9 and len(db) >= 9:
        return da[-9:] == db[-9:]
    return da.lstrip("0") == db.lstrip("0")


def _add_labelled(card: Card, name: str, value: str, label: str,
                  types: dict[str, tuple[str, ...]], always: tuple[str, ...]) -> None:
    label = (label or "").strip()
    known = types.get(label.lower())
    if known:
        card.props.append(Prop(name=name, value=escape(value),
                               params=[("TYPE", t) for t in known]))
        return
    group = card.next_item()
    card.props.append(Prop(name=name, value=escape(value), group=group,
                           params=[("TYPE", t) for t in always]))
    apple = APPLE_RAW.get(label.lower())
    said = f"_$!<{apple}>!$_" if apple else label
    card.props.append(Prop(name="X-ABLABEL", value=escape(said), group=group))


def add_phone(card: Card, number: str, label: str = "mobile") -> bool:
    number = (number or "").strip()
    if not digits_of(number):
        raise BadField(f"\"{number}\" is not a phone number.")
    if any(same_number(p.text(), number) for p in card.all("TEL")):
        return False
    _add_labelled(card, "TEL", number, label or "mobile", PHONE_TYPES, ("VOICE",))
    return True


def add_email(card: Card, address: str, label: str = "") -> bool:
    address = (address or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
        raise BadField(f"\"{address}\" is not an email address.")
    if any(p.text().strip().lower() == address.lower() for p in card.all("EMAIL")):
        return False
    _add_labelled(card, "EMAIL", address, label or "other", EMAIL_TYPES, ("INTERNET",))
    return True


def remove_phone(card: Card, number: str) -> bool:
    gone = [p for p in card.all("TEL") if same_number(p.text(), number)]
    for prop in gone:
        card.remove(prop)
    return bool(gone)


def remove_email(card: Card, address: str) -> bool:
    wanted = (address or "").strip().lower()
    gone = [p for p in card.all("EMAIL") if p.text().strip().lower() == wanted]
    for prop in gone:
        card.remove(prop)
    return bool(gone)


def address_parts(prop: Prop) -> dict:
    """An ADR line's parts by name: street, city, region, postal_code, country (the post office box and
    the extended address go in front of the street)."""
    got = [" ".join(p.split()) for p in split_structured(prop.value)] + [""] * 7
    box, extended, street = got[0], got[1], got[2]
    street = ", ".join(p for p in (box, extended, street) if p)
    return dict(zip(ADDRESS_PARTS, (street, got[3], got[4], got[5], got[6])))


def address_line(parts: dict) -> str:
    """A postal address as one line, the way a letter is addressed: street, postal code and city,
    region, country."""
    town = " ".join(p for p in (str(parts.get("postal_code") or "").strip(), str(parts.get("city") or "").strip())
                    if p)
    bits = [str(parts.get("street") or "").strip(), town, str(parts.get("region") or "").strip(),
            str(parts.get("country") or "").strip()]
    return ", ".join(" ".join(b.split()) for b in bits if b)


def addresses_of(card: Card) -> list[dict]:
    out = []
    for prop in card.all("ADR"):
        parts = address_parts(prop)
        line = address_line(parts)
        if line:
            out.append({"address": line, "label": card.label_of(prop), "parts": parts})
    return out


def same_address(a: str, b: str) -> bool:
    """Whether a line someone said names this address: equal, or one inside the other, case, accents
    and punctuation aside."""
    pa = " ".join(re.findall(r"\w+", _plain(a or "")))
    pb = " ".join(re.findall(r"\w+", _plain(b or "")))
    if not pa or not pb:
        return False
    return pa == pb or f" {pa} " in f" {pb} " or f" {pb} " in f" {pa} "


def add_address(card: Card, parts: dict, label: str = "") -> bool:
    clean = {k: " ".join(str(parts.get(k) or "").split()) for k in ADDRESS_PARTS}
    line = address_line(clean)
    if not line:
        raise BadField("An address needs at least a street, a city or a country.")
    if any(same_address(address_line(address_parts(p)), line) for p in card.all("ADR")):
        return False
    value = ";".join(["", ""] + [escape(clean[k]) for k in ADDRESS_PARTS])
    label = (label or "home").strip()
    known = ADDRESS_TYPES.get(label.lower())
    if known:
        card.props.append(Prop(name="ADR", value=value, params=[("TYPE", t) for t in known]))
        return True
    group = card.next_item()
    card.props.append(Prop(name="ADR", value=value, group=group))
    apple = APPLE_RAW.get(label.lower())
    card.props.append(Prop(name="X-ABLABEL", value=escape(f"_$!<{apple}>!$_" if apple else label), group=group))
    return True


def remove_address(card: Card, said: str) -> list[str]:
    """The addresses taken off for a line someone said, each as one line."""
    gone = [p for p in card.all("ADR") if same_address(address_line(address_parts(p)), said)]
    for prop in gone:
        card.remove(prop)
    return [address_line(address_parts(p)) for p in gone]


@dataclass
class Changes:
    """What one write asks for. None is "leave it as it is"; "" is "clear it"."""

    name: str | None = None
    organisation: str | None = None
    birthday: str | None = None
    note: str | None = None
    title: str | None = None
    add_phones: list[dict] = field(default_factory=list)
    remove_phones: list[str] = field(default_factory=list)
    add_emails: list[dict] = field(default_factory=list)
    remove_emails: list[str] = field(default_factory=list)
    #: Postal addresses (night 43, `postal_address`): each {"parts": {street, city, ...}, "label"}.
    add_addresses: list[dict] = field(default_factory=list)
    remove_addresses: list[str] = field(default_factory=list)

    def scalars(self) -> dict[str, str]:
        """The single-valued fields this sets, by `Person`'s own names."""
        return {k: v for k, v in (("name", self.name), ("organisation", self.organisation),
                                  ("birthday", self.birthday), ("note", self.note),
                                  ("title", self.title))
                if v is not None}

    def empty(self) -> bool:
        return not (self.scalars() or self.add_phones or self.remove_phones
                    or self.add_emails or self.remove_emails or self.add_addresses
                    or self.remove_addresses)


def apply(card: Card, changes: Changes) -> list[str]:
    """Make the changes on the card, and say each one that really happened."""
    said: list[str] = []
    if changes.name is not None:
        name = changes.name.strip()
        if not name:
            raise BadField("A contact needs a name.")
        if name != card.value("FN").strip():
            card.set("FN", escape(name))
            card.set("N", _name_parts(name))
            said.append(f"the name is now {name}")
    if changes.organisation is not None:
        org = changes.organisation.strip()
        was = ", ".join(p.strip() for p in split_structured(card.first("ORG").value)
                        if p.strip()) if card.first("ORG") else ""
        if org != was:
            card.set("ORG", escape(org) + ";" if org else "")
            said.append(f"the organisation is now {org}" if org
                        else "the organisation is cleared")
    if changes.birthday is not None:
        birthday = check_birthday(changes.birthday)
        if birthday != _birthday_of(card.first("BDAY")):
            if birthday:
                value, params = _bday_params(birthday)
                card.set("BDAY", value, params)
                said.append(f"the birthday is now {birthday_words(birthday)}")
            else:
                card.set("BDAY", "")
                said.append("the birthday is cleared")
    if changes.title is not None:
        title = " ".join(changes.title.split())
        if title != card.value("TITLE").strip():
            card.set("TITLE", escape(title))
            said.append(f"the job title is now {title}" if title else "the job title is cleared")
    if changes.note is not None:
        note = changes.note.strip()
        if note != card.value("NOTE").strip():
            card.set("NOTE", escape(note))
            said.append("the note is changed" if note else "the note is cleared")
    for number in changes.remove_phones:
        if remove_phone(card, number):
            said.append(f"removed the number {number}")
    for email in changes.remove_emails:
        if remove_email(card, email):
            said.append(f"removed {email}")
    for phone in changes.add_phones:
        number, label = str(phone.get("number") or ""), str(phone.get("label") or "")
        if add_phone(card, number, label):
            said.append(f"added {label or 'mobile'} {number.strip()}")
    for email in changes.add_emails:
        address, label = str(email.get("address") or ""), str(email.get("label") or "")
        if add_email(card, address, label):
            said.append(f"added {address.strip()}" + (f" ({label})" if label else ""))
    for said_line in changes.remove_addresses:
        for line in remove_address(card, said_line):
            said.append(f"removed the address {line}")
    for one in changes.add_addresses:
        parts, label = dict(one.get("parts") or {}), str(one.get("label") or "")
        if add_address(card, parts, label):
            said.append(f"added the address {address_line(parts)}" + (f" ({label})" if label else ""))
    return said


def new_card(uid: str, changes: Changes) -> tuple[Card, list[str]]:
    """A card written from nothing, the way the phone writes one."""
    card = Card([Prop(name="VERSION", value="3.0"), Prop(name="PRODID", value=PRODID)])
    name = (changes.name or "").strip()
    if not name:
        raise BadField("A new contact needs a name.")
    card.props.append(Prop(name="N", value=_name_parts(name)))
    card.props.append(Prop(name="FN", value=escape(name)))
    said = apply(card, Changes(organisation=changes.organisation or None,
                               birthday=changes.birthday or None, note=changes.note or None,
                               title=changes.title or None,
                               add_phones=changes.add_phones, add_emails=changes.add_emails,
                               add_addresses=changes.add_addresses))
    card.props.append(Prop(name="UID", value=uid))
    return card, said


def with_uid(card: Card, uid: str) -> Card:
    """The same card under a new UID: the second of two, when both are kept."""
    card.set("UID", uid)
    return card


# --- what a search is matched against -----------------------------------------------

#: Cyrillic to Latin, Bulgarian's own streamlined system with the few Russian
#: letters it lacks, so "Ivan" finds "Иван" and "Georgi" finds "Георги".
_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sht", "ъ": "a", "ь": "y", "ю": "yu", "я": "ya", "ё": "yo",
    "э": "e", "ы": "y", "є": "ye", "і": "i", "ї": "yi", "ґ": "g",
}


def _plain(text: str) -> str:
    """Lower case, with accents taken off: "José" is "jose"."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def latin(text: str) -> str:
    lowered = (text or "").lower()
    return _plain("".join(_LATIN.get(ch, ch) for ch in lowered))


def normalise(text: str) -> str:
    """What a search word and a searched text are both turned into."""
    return " ".join(_plain(text).split())


def searchable(person: Person) -> tuple[str, str]:
    """The words a contact is found by, and the digits of every number it has."""
    parts = [person.name, person.organisation, person.note,
             *(e["address"] for e in person.emails)]
    words = normalise(" ".join(p for p in parts if p))
    written = latin(" ".join(p for p in parts if p))
    if " ".join(written.split()) != words:
        words += " " + " ".join(written.split())
    digits = " ".join(d for d in (digits_of(p["number"]) for p in person.phones) if d)
    return words, digits
