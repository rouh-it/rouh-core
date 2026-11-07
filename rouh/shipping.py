"""Shipping: where a parcel should go, in the person's favourite order, for any checkout.

Petar, 14 October 2026: "I want to be able to define shipping options and addresses with
priority depending on what the vendor allows ... sometimes it is a box, sometimes a speedy
office, sometimes I have to provide address. I have preferences for each situation ... I
need to be able to line up options in favorite order." And: "I need to be able to define
logistics company, type of place, and specific address."

**An option** (`ShippingOption`) is three things, kept apart on the page and here:

- the courier, free text with suggestions (`COMPANIES`), or Any courier (`ANY`);
- the kind of place (`KINDS`): a locker or box, an office, or a door address;
- the place itself: the courier's own code and name for its locker or office, and the
  street, city, postcode, country, floor, apartment, entrance and door code.

With them go a label ("Speedy locker near home"), the recipient's name and phone, which are
blank when they are the person's own defaults (`recipient`), notes for the courier, its place
in the main order and an on/off switch. Every option and situation is labelled with the
Personal silo (`home_silo`), as private contact detail: a turn limited to other silos, such
as a trusted contact's, sees none of it (`silos.limit_now`).

**Situations** (`ShippingSituation`) are named, such as "Big or heavy" or "Abroad", each with
its own ordered list of the saved options. "Default" always exists, has no row, and is the
main order. Every list ends with an implicit "ask me": when nothing in it fits, Rouh asks.

**Choosing** (`decide`, pure, and `choose`, which reads the person's own lists): given what a
checkout offers - the couriers and the kinds of place, or pairs of them, and optionally a
situation and the country the delivery goes to - the first option in the list that fits is
chosen. It fits when it is switched on, its country (if it has one) is the delivery's, its
kind is offered, and its courier is offered (or it says Any courier), with that kind when the
offer pairs them. The answer names the option and why, every option skipped before it and why
("Speedy locker skipped, the seller offers no lockers"), or that nothing fits and the owner is to
be asked.

**Changing** them is the Shipping page's (Settings, Shipping, `/settings/shipping`), and the
`shipping` tool's only in a turn the person started, in their own words (`signups.PERSON_TURN`):
never because an email, a page or a job said to. Filling a checkout with the option chosen is
`browser fill_shipping` (`browsing.Desk.fill_shipping`), which never presses anything: the
button that buys is pressed only with `place_order`, for a purchase the owner asked for themselves
(`rouh/purchases.py`), which checks that the address on the page is one of these options.

Everything is keyed and queried by `org_id` and `user_id`.
"""
from __future__ import annotations

import json
import re
import time

#: The kinds of place, in the order the page offers them, and how each is named.
KINDS = ("locker", "office", "address")
KIND_NAMES = {"locker": "Locker or box", "office": "Office", "address": "Door address"}
#: A kind in a sentence: "a Speedy locker", "to an office".
KIND_SAID = {"locker": "locker", "office": "office", "address": "door address"}
#: What a seller does not offer, in "the seller offers no ...".
KIND_NONE = {"locker": "lockers", "office": "office pick-up", "address": "delivery to a door address"}
#: Words a checkout or the model may use for each kind, checked as whole words, lockers first.
KIND_WORDS = {
    "locker": ("locker", "lockers", "box", "boxes", "parcel locker", "parcel machine", "automat",
               "apm", "paczkomat", "pickup box", "pick up box", "автомат", "автомати", "бокс"),
    "office": ("office", "offices", "branch", "post office", "pickup point", "pick up point",
               "pick-up point", "pudo", "store", "shop", "collection point", "офис", "офиси", "поща"),
    "address": ("address", "door", "home", "door address", "to door", "to address", "home delivery",
                "courier to address", "адрес", "до адрес", "до врата"),
}

#: The couriers the page suggests, in its order. Free text is just as good.
COMPANIES = ("Speedy", "Econt", "BOX NOW", "DHL", "Bulgarian Posts", "UPS", "FedEx")
ANY = "Any courier"
#: Other spellings of each suggested courier, so "Еконт" or "Box Now locker" finds Econt or BOX NOW.
ALIASES = {
    "speedy": ("speedy", "спиди"),
    "econt": ("econt", "econt express", "еконт", "еконт експрес"),
    "boxnow": ("box now", "boxnow", "бокс нау"),
    "dhl": ("dhl", "dhl express", "dhl parcel"),
    "bgpost": ("bulgarian posts", "bulgarian post", "bg post", "bgpost", "български пощи"),
    "ups": ("ups",),
    "fedex": ("fedex", "fed ex", "federal express"),
}
_ANY_WORDS = {"any", "any courier", "any company", "anyone", "anybody", "*"}

#: Where the person's own default recipient is kept, in `user_settings`.
RECIPIENT = "shipping_recipient"
PAGE = "/settings/shipping"
DEFAULT = "default"
DEFAULT_NAME = "Default"

#: How long each field may be.
LONGEST = {"label": 80, "company": 60, "place_code": 40, "place_name": 120, "line1": 160, "city": 80,
           "postal_code": 20, "country": 40, "floor": 10, "apartment": 10, "entrance": 10,
           "door_code": 20, "recipient_name": 120, "recipient_phone": 40, "notes": 400}
ADDRESS = ("line1", "city", "postal_code", "country", "floor", "apartment", "entrance", "door_code")


class Refused(ValueError):
    """A change refused, with the reason; `fields` maps each wrong field to what is wrong with it,
    so the page says each under its own field, as the Payments page does."""

    def __init__(self, message: str = "", fields: dict | None = None):
        self.fields = dict(fields or {})
        super().__init__(message or " ".join(self.fields.values()))


# --- words -----------------------------------------------------------------------------------

def _words(text) -> str:
    """Lower case, every run of what is not a letter or digit one space."""
    return " ".join(re.sub(r"[^\w*]+", " ", str(text or "").lower()).replace("_", " ").split())


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _line(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def kind_of(text) -> str:
    """The kind of place some words name ("Parcel locker", "до офис", "address"), or ""."""
    t = _words(text)
    if not t:
        return ""
    if t in KINDS:
        return t
    for kind in KINDS:
        if any(_has(t, w) for w in KIND_WORDS[kind]):
            return kind
    return ""


def _without_kinds(t: str) -> str:
    for kind in KINDS:
        for w in sorted(KIND_WORDS[kind], key=len, reverse=True):
            t = f" {t} ".replace(f" {w} ", " ").strip()
    return " ".join(t.split())


def _kind_words_out(text) -> str:
    """Some words with every kind's words taken out, as written: "Speedy office" is "Speedy"."""
    out = str(text or "")
    for kind in KINDS:
        for w in sorted(KIND_WORDS[kind], key=len, reverse=True):
            out = re.sub(rf"(?i)(?<!\w){re.escape(w)}(?!\w)", " ", out)
    return " ".join(out.replace(" - ", " ").split()).strip(" -,:;")


def company_key(text) -> str:
    """What a courier's name is compared by: "*" for Any courier, a known courier's own key
    whichever way it is spelt, else its words run together. "" for nothing."""
    t = _words(text)
    if not t:
        return ""
    if t in _ANY_WORDS:
        return "*"
    for key, spellings in ALIASES.items():
        for s in spellings:
            if _has(t, s) or t.replace(" ", "") == s.replace(" ", ""):
                return key
    rest = _without_kinds(t)
    return (rest or t).replace(" ", "")


def is_any(company) -> bool:
    return company_key(company) == "*"


def offers_from(args: dict) -> list[tuple[str, str, str]]:
    """What a checkout offers, as (courier key or "", courier as written, kind or "") each.

    From `offers`, a list of {company, kind} or {company, kinds} or plain words such as
    "Speedy office"; or from `companies` and `kinds`, two lists, every courier with every kind."""
    out: list[tuple[str, str, str]] = []

    def add(company, kind):
        c, k = company_key(company), kind_of(kind) if kind else ""
        if c == "*":
            c = ""
        if (c or k) and (c, k) not in [(a, b) for a, _, b in out]:
            # A courier the page suggests is said the way the page spells it.
            said = next((n for n in COMPANIES if company_key(n) == c), "") or _line(company, 60)
            out.append((c, said if c else "", k))

    for one in args.get("offers") or []:
        if isinstance(one, dict):
            kinds = one.get("kinds") if isinstance(one.get("kinds"), list) else [one.get("kind") or one.get("type")]
            for k in kinds or [""]:
                add(one.get("company") or one.get("courier") or "", k or "")
        elif isinstance(one, str):
            # "Speedy office": the courier is what is left once the kind's words are out.
            add(one if company_key(one) in ALIASES else _kind_words_out(one), one)
    companies = [c for c in _listed(args.get("companies") or args.get("couriers")) if c]
    kinds = [k for k in _listed(args.get("kinds") or args.get("types")) if kind_of(k)]
    if companies and kinds:
        for c in companies:
            for k in kinds:
                add(c, k)
    else:
        for c in companies:
            add(c, "")
        for k in kinds:
            add("", k)
    return out


def _listed(value) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;\n]", value) if v.strip()]
    return [str(v) for v in value or [] if str(v or "").strip()]


def _ordinal(n: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
            8: "eighth", 9: "ninth", 10: "tenth"}.get(n, f"number {n}")


def _offered_said(offers) -> str:
    """What the seller offers, in words: "Speedy and Econt to a locker or an office"."""
    if not offers:
        return "nothing said"
    parts = []
    for c, text, k in offers:
        parts.append(" ".join(x for x in (text or ("any courier" if k else ""), "to a " + KIND_SAID[k] if k else "")
                              if x))
    return "; ".join(parts)


def _why_not(o: dict, okey: str, offers) -> str:
    kinds = {k for _, _, k in offers if k}
    couriers = {c for c, _, _ in offers if c}
    if kinds and o["kind"] not in kinds:
        return f"the seller offers no {KIND_NONE[o['kind']]}"
    if okey != "*" and couriers and okey not in couriers:
        return f"the seller does not ship with {o['company']}"
    theirs = sorted({k for c, _, k in offers if c == okey and k}, key=KINDS.index)
    if theirs:
        return (f"the seller offers {o['company']} only to "
                + " or ".join(("an " if KIND_SAID[k][0] in "aeiou" else "a ") + KIND_SAID[k] for k in theirs))
    return "it does not fit what the seller offers"


def decide(options: list[dict], offers: list[tuple[str, str, str]], *, country: str = "",
           situation: str = DEFAULT_NAME) -> dict:
    """The first option in `options` (in order) that fits what the seller `offers`.

    Each option is a dict with at least label, company, kind, country and active. Answers
    {"option", "rank", "courier", "skipped", "ask", "reason"}: the option and its place in the
    list, the courier to pick for it (the seller's own for Any courier), every option passed
    over with why, whether the owner is to be asked, and all of it in one sentence."""
    country = _line(country, 2).upper()
    skipped: list[str] = []
    for rank, o in enumerate(options, 1):
        name = o["label"]
        if not o.get("active", True):
            skipped.append(f"{name} skipped, it is switched off")
            continue
        here = str(o.get("country") or "").upper()
        if country and here and here != country:
            skipped.append(f"{name} skipped, it is in {here} and this delivery goes to {country}")
            continue
        okey = company_key(o["company"]) or "*"
        fits = [(c, text, k) for c, text, k in offers
                if (not k or k == o["kind"]) and (not c or okey == "*" or c == okey)]
        if not fits:
            skipped.append(f"{name} skipped, {_why_not(o, okey, offers)}")
            continue
        courier = o["company"] if okey != "*" else next((t for _, t, _ in fits if t), "")
        how = f"{KIND_SAID[o['kind']]} with {courier}" if courier else f"{KIND_SAID[o['kind']]}, any courier"
        reason = (f"Picked {name} ({how}), the {_ordinal(rank)} choice in {situation}"
                  + (": " + "; ".join(skipped) + "." if skipped else ", first in the list."))
        return {"option": o, "rank": rank, "courier": courier, "skipped": skipped, "ask": False,
                "reason": reason}
    if not options:
        reason = (f"No shipping option is saved in {situation}, so ask ‹owner› where it should go "
                  f"(‹he› can line them up in Settings, Shipping).")
    else:
        reason = (f"Nothing in {situation} fits what the seller offers ({_offered_said(offers)}): "
                  + "; ".join(skipped) + ". Ask ‹owner› which to use.")
    return {"option": None, "rank": 0, "courier": "", "skipped": skipped, "ask": True, "reason": reason}


# --- the rows --------------------------------------------------------------------------------

def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def home_silo(who) -> str:
    """The silo shipping is labelled with: Personal, by its key or its name, or "" if the account
    has no such silo."""
    from . import silos

    have = silos.by_key(who.user_id, who.org_id)
    if "personal" in have:
        return "personal"
    found = silos.find(who.user_id, who.org_id, "Personal")
    return found.key if found else ""


def _visible(rows: list, limit) -> list:
    from . import silos

    return [r for r in rows if silos.fits([r.silo] if r.silo else [], limit)] if limit is not None else rows


def option_rows(who, limit=None) -> list:
    """This person's options, in the main order: by position, then as they were added."""
    rows = list(_models().ShippingOption.objects.filter(**_whose(who)).order_by("position", "id"))
    return _visible(rows, limit)


def option_row(who, option_id):
    try:
        option_id = int(option_id)
    except (TypeError, ValueError):
        return None
    return _models().ShippingOption.objects.filter(**_whose(who), id=option_id).first()


def situation_rows(who, limit=None) -> list:
    rows = list(_models().ShippingSituation.objects.filter(**_whose(who)).order_by("position", "id"))
    return _visible(rows, limit)


def situation_row(who, situation_id):
    try:
        situation_id = int(situation_id)
    except (TypeError, ValueError):
        return None
    return _models().ShippingSituation.objects.filter(**_whose(who), id=situation_id).first()


def view(row) -> dict:
    """An option as the page and `decide` read it."""
    return {"id": row.id, "label": row.label, "company": row.company, "any": is_any(row.company),
            "kind": row.kind, "kind_name": KIND_NAMES.get(row.kind, row.kind),
            "place_code": row.place_code, "place_name": row.place_name,
            "address": {k: getattr(row, k) for k in ADDRESS}, "country": row.country,
            "recipient_name": row.recipient_name, "recipient_phone": row.recipient_phone,
            "notes": row.notes, "active": bool(row.active), "position": row.position, "silo": row.silo}


def option_from(form: dict) -> dict:
    """An option as the owner typed it, checked; a Refused names each field that is wrong."""
    wrong = {}
    out = {k: _line(form.get(k), LONGEST[k]) for k in ("label", "company", "place_code", "place_name",
                                                       "recipient_name", "recipient_phone")}
    out["notes"] = str(form.get("notes") or "").strip()[:LONGEST["notes"]]
    address = form.get("address") if isinstance(form.get("address"), dict) else form
    out.update({k: _line(address.get(k), LONGEST[k]) for k in ADDRESS})
    out["country"] = out["country"].upper()
    kind = str(form.get("kind") or "").strip().lower()
    out["kind"] = kind if kind in KINDS else kind_of(kind)
    if is_any(out["company"]):
        out["company"] = ANY
    else:
        # A suggested courier keeps its own spelling, whichever way it was typed.
        known = {company_key(c): c for c in COMPANIES}
        out["company"] = known.get(company_key(out["company"]), out["company"])
    if not out["label"]:
        wrong["label"] = "Give it a name you will know it by, such as Speedy locker near home."
    if not out["company"]:
        wrong["company"] = "Name the courier, or pick Any courier."
    if not out["kind"]:
        wrong["kind"] = "Pick the kind of place: a locker, an office or a door address."
    elif out["kind"] in ("locker", "office"):
        if not (out["place_code"] or out["place_name"]):
            wrong["place_code"] = (f"Give the {KIND_SAID[out['kind']]}'s code or its name, as the courier "
                                   "lists it.")
    else:
        if not out["line1"]:
            wrong["line1"] = "Give the street and number."
        if not out["city"]:
            wrong["city"] = "Give the city."
    if out["country"] and not re.fullmatch(r"[A-Z]{2}", out["country"]):
        wrong["country"] = "The country is its two letters, such as BG or GB."
    if out["recipient_phone"] and not re.fullmatch(r"\+?[\d\s()./-]{5,}", out["recipient_phone"]):
        wrong["recipient_phone"] = "That is not a phone number. Leave it empty to use your own."
    if wrong:
        raise Refused(fields=wrong)
    return out


def save_option(who, form: dict):
    """An option added at the end of the main order, or the one named by `form["id"]` changed."""
    fields = option_from(form)
    now = time.time()
    if "active" in form:
        fields["active"] = bool(form.get("active"))
    M = _models().ShippingOption
    if form.get("id") not in (None, ""):
        row = option_row(who, form.get("id"))
        if row is None:
            raise Refused("That shipping option is not one of yours.")
        M.objects.filter(**_whose(who), id=row.id).update(**fields, updated_at=now)
        return option_row(who, row.id)
    last = M.objects.filter(**_whose(who)).order_by("-position").values_list("position", flat=True).first()
    return M.objects.create(**_whose(who), **fields, position=(last + 1) if last is not None else 0,
                            silo=home_silo(who), created_at=now, updated_at=now)


def delete_option(who, option_id):
    """An option taken out of the main order and every situation's list; the row it was, or None."""
    from django.db import transaction

    row = option_row(who, option_id)
    if row is None:
        return None
    with transaction.atomic():
        for s in situation_rows(who):
            if row.id in (s.options or []):
                s.options = [i for i in s.options if i != row.id]
                s.updated_at = time.time()
                s.save(update_fields=["options", "updated_at"])
        _models().ShippingOption.objects.filter(**_whose(who), id=row.id).delete()
    return row


def set_active(who, option_id, active: bool):
    row = option_row(who, option_id)
    if row is None:
        return None
    _models().ShippingOption.objects.filter(**_whose(who), id=row.id).update(
        active=bool(active), updated_at=time.time())
    return option_row(who, row.id)


def _ids(order) -> list[int]:
    out: list[int] = []
    for v in order or []:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i not in out:
            out.append(i)
    return out


def reorder(who, situation, order) -> str:
    """The main order (situation "default"), or a situation's list, set to `order`, a list of
    option ids. The main order keeps every option: one not named stays, after those named. A
    situation's list is exactly the options named, so adding and taking out are this too.
    Answers the situation's name."""
    from django.db import transaction

    mine = {r.id: r for r in option_rows(who)}
    wanted = [i for i in _ids(order) if i in mine]
    if str(situation or DEFAULT).strip().lower() in (DEFAULT, ""):
        rest = [i for i in mine if i not in wanted]
        with transaction.atomic():
            for position, i in enumerate(wanted + rest):
                if mine[i].position != position:
                    _models().ShippingOption.objects.filter(**_whose(who), id=i).update(position=position)
        return DEFAULT_NAME
    row = situation_row(who, situation)
    if row is None:
        raise Refused("That situation is not one of yours.")
    row.options = wanted
    row.updated_at = time.time()
    row.save(update_fields=["options", "updated_at"])
    return row.name


def move(who, situation, option_id, by: int) -> str:
    """One option moved up (by -1) or down (by 1) in a list; what the page's buttons and the tool
    call. Answers the situation's name."""
    ids = order_of(who, situation)
    try:
        option_id = int(option_id)
    except (TypeError, ValueError):
        raise Refused("That shipping option is not in this list.") from None
    if option_id not in ids:
        raise Refused("That shipping option is not in this list.")
    at = ids.index(option_id)
    to = max(0, min(len(ids) - 1, at + (1 if int(by) > 0 else -1)))
    ids.insert(to, ids.pop(at))
    return reorder(who, situation, ids)


def order_of(who, situation) -> list[int]:
    if str(situation or DEFAULT).strip().lower() in (DEFAULT, ""):
        return [r.id for r in option_rows(who)]
    row = situation_row(who, situation)
    if row is None:
        raise Refused("That situation is not one of yours.")
    mine = {r.id for r in option_rows(who)}
    return [i for i in _ids(row.options) if i in mine]


def _clean_name(who, name, but=None) -> str:
    name = _line(name, 60)
    if not name:
        raise Refused(fields={"name": "Give the situation a name, such as Big or heavy."})
    if _words(name) == DEFAULT:
        raise Refused(fields={"name": "Default is the main order, and is always there. Pick another name."})
    for s in situation_rows(who):
        if s.id != but and _words(s.name) == _words(name):
            raise Refused(fields={"name": f"There is a situation called {s.name} already."})
    return name


def save_situation(who, form: dict):
    """A situation added, starting with the main order's options switched on, or renamed."""
    M = _models().ShippingSituation
    now = time.time()
    if form.get("id") not in (None, ""):
        row = situation_row(who, form.get("id"))
        if row is None:
            raise Refused("That situation is not one of yours.")
        row.name = _clean_name(who, form.get("name"), but=row.id)
        row.updated_at = now
        row.save(update_fields=["name", "updated_at"])
        return row
    name = _clean_name(who, form.get("name"))
    start = _ids(form.get("options")) if isinstance(form.get("options"), list) else []
    last = M.objects.filter(**_whose(who)).order_by("-position").values_list("position", flat=True).first()
    return M.objects.create(**_whose(who), name=name, options=start,
                            position=(last + 1) if last is not None else 0, silo=home_silo(who),
                            created_at=now, updated_at=now)


def delete_situation(who, situation_id):
    row = situation_row(who, situation_id)
    if row is None:
        return None
    _models().ShippingSituation.objects.filter(**_whose(who), id=row.id).delete()
    return row


def find_situation(who, name, limit=None):
    """A situation by its id or its name, ignoring case; None for Default or none such."""
    t = _words(name)
    if t in ("", DEFAULT):
        return None
    for s in situation_rows(who, limit):
        if str(s.id) == t or _words(s.name) == t:
            return s
    return False


# --- the recipient ---------------------------------------------------------------------------

def _held(who) -> dict:
    value = (_models().UserSetting.objects.filter(**_whose(who), name=RECIPIENT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def own_defaults(who) -> dict:
    """The person's own name and phone, as their profile and their contact card have them."""
    from . import my_card

    user = _models().User.objects.filter(pk=who.user_id).values("first_name", "last_name").first() or {}
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x).strip()
    phone = ""
    try:
        found = my_card.card(str(who.user_id), str(who.org_id))
        for p in (found or {}).get("phones") or []:
            phone = str(p.get("number") if isinstance(p, dict) else p or "").strip()
            if phone:
                break
    except Exception:  # noqa: BLE001 - no card is only no phone
        phone = ""
    return {"name": name, "phone": phone}


def recipient(who) -> dict:
    """Who a parcel is for unless an option says otherwise: what was set on the Shipping page,
    else the profile's name and the contact card's first phone."""
    held, own = _held(who), own_defaults(who)
    return {"name": str(held.get("name") or "") or own["name"],
            "phone": str(held.get("phone") or "") or own["phone"],
            "set": {"name": str(held.get("name") or ""), "phone": str(held.get("phone") or "")},
            "own": own}


def set_recipient(who, name, phone) -> dict:
    wrong = {}
    name, phone = _line(name, LONGEST["recipient_name"]), _line(phone, LONGEST["recipient_phone"])
    if phone and not re.fullmatch(r"\+?[\d\s()./-]{5,}", phone):
        wrong["phone"] = "That is not a phone number."
    if wrong:
        raise Refused(fields=wrong)
    M = _models().UserSetting
    M.objects.bulk_create(
        [M(**_whose(who), name=RECIPIENT, value=json.dumps({"name": name, "phone": phone}, ensure_ascii=False),
           updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])
    return recipient(who)


# --- what the page and the model are given -----------------------------------------------------

def public(who) -> dict:
    """Everything the Shipping page draws."""
    from . import silos

    opts = option_rows(who)
    ids = {r.id for r in opts}
    sits = [{"id": DEFAULT, "name": DEFAULT_NAME, "default": True, "options": [r.id for r in opts]}]
    for s in situation_rows(who):
        sits.append({"id": s.id, "name": s.name, "default": False,
                     "options": [i for i in _ids(s.options) if i in ids]})
    key = home_silo(who)
    info = silos.by_key(who.user_id, who.org_id).get(key) if key else None
    return {"options": [view(r) for r in opts], "situations": sits, "recipient": recipient(who),
            "companies": [*COMPANIES, ANY], "kinds": [{"key": k, "name": KIND_NAMES[k]} for k in KINDS],
            "silo": info.chip() if info else None}


def _place_said(o: dict) -> str:
    a = o["address"]
    if o["kind"] in ("locker", "office"):
        place = " ".join(x for x in (o["place_code"], f"“{o['place_name']}”" if o["place_name"] else "") if x)
        where = ", ".join(x for x in (a["line1"], a["city"], a["postal_code"], a["country"]) if x)
        return f"{KIND_SAID[o['kind']]} {place}" + (f" ({where})" if where else "")
    parts = [a["line1"]]
    parts += [f"entrance {a['entrance']}" if a["entrance"] else "", f"floor {a['floor']}" if a["floor"] else "",
              f"apartment {a['apartment']}" if a["apartment"] else ""]
    parts += [a["postal_code"] + " " + a["city"] if a["postal_code"] else a["city"], a["country"]]
    return "door address " + ", ".join(p.strip() for p in parts if p and p.strip()) + (
        f"; door code {a['door_code']}" if a["door_code"] else "")


def place_line(o: dict) -> str:
    """Where an option delivers, as a purchase keeps it and the Payments page shows it: its
    label and its place, never its door code."""
    return f"{o['label']}: " + _place_said(o).split("; door code")[0]


def line_for_model(o: dict, n: int, rec: dict) -> str:
    who = (o["recipient_name"] or rec["name"]) + (", " + (o["recipient_phone"] or rec["phone"])
                                                  if (o["recipient_phone"] or rec["phone"]) else "")
    return (f"{n}. {o['label']} [option {o['id']}]: {o['company']}, {_place_said(o)}"
            + (f"; for {who}" if who else "")
            + (f"; notes for the courier: {o['notes']}" if o["notes"] else "")
            + ("" if o["active"] else " (switched off)"))


NOT_SEEN = ("‹owner›'s shipping options are in ‹his› Personal silo, which this conversation may not see. "
            "Never say or guess ‹his› addresses here.")


def listing(who, limit=None) -> str:
    """The options in the main order and each situation's list, for the model."""
    opts = option_rows(who, limit)
    if limit is not None and not opts and option_rows(who):
        return NOT_SEEN
    if not opts:
        return ("No shipping options are saved. ‹owner› lines them up in Settings, Shipping "
                f"({PAGE}); at a checkout, ask ‹him› where it should go.")
    rec = recipient(who)
    views = {r.id: view(r) for r in opts}
    lines = [f"Default (the main order), tried top to bottom, then ask ‹owner›:"]
    lines += [line_for_model(v, n, rec) for n, v in enumerate(views.values(), 1)]
    for s in situation_rows(who, limit):
        ids = [i for i in _ids(s.options) if i in views]
        lines.append(f"Situation “{s.name}” [situation {s.id}]: "
                     + (", ".join(f"{n}. {views[i]['label']}" for n, i in enumerate(ids, 1)) if ids else "empty")
                     + ", then ask ‹owner›.")
    if rec["name"] or rec["phone"]:
        lines.append(f"Recipient unless an option says otherwise: {rec['name']}"
                     + (f", {rec['phone']}" if rec["phone"] else "") + ".")
    lines.append("Private contact detail: never put these in mail or pages for anybody else unless ‹owner› asks.")
    return "\n".join(lines)


def choose(who, args: dict, limit=None) -> dict:
    """`decide` on the person's own list for a situation: the Default's main order unless one is
    named. Adds "said", everything the model needs to fill the checkout and tell the owner."""
    opts = option_rows(who, limit)
    if limit is not None and not opts and option_rows(who):
        return {"option": None, "ask": True, "said": NOT_SEEN}
    offers = offers_from(args)
    if not offers:
        return {"option": None, "ask": True,
                "said": "Say what the checkout offers: companies (the couriers it lists) and kinds (locker, "
                        "office, address), or offers, pairs of them, as the page shows them."}
    note = ""
    name = DEFAULT_NAME
    views = {r.id: view(r) for r in opts}
    order = list(views.values())
    wanted = str(args.get("situation") or "").strip()
    if wanted:
        found = find_situation(who, wanted, limit)
        if found is False:
            names = ", ".join(s.name for s in situation_rows(who, limit)) or "none but Default"
            note = f"There is no situation called “{wanted}” (there are: {names}), so Default was used. "
        elif found is not None:
            name = f"“{found.name}”"
            order = [views[i] for i in _ids(found.options) if i in views]
    return _checkout_result(who, order, offers, country=str(args.get("country") or ""), name=name, note=note)


def _checkout_result(who, order, offers, *, country: str, name: str, note: str) -> dict:
    """Decide on the resolved list and assemble the checkout's result and recipient."""
    got = decide(order, offers, country=country, situation=name)
    got["situation"] = name
    if got["option"] is None:
        got["said"] = note + got["reason"]
        return got
    o, rec = got["option"], recipient(who)
    got["recipient"] = {"name": o["recipient_name"] or rec["name"], "phone": o["recipient_phone"] or rec["phone"]}
    got["said"] = _checkout_said(o, got, note)
    return got


def _checkout_said(o: dict, got: dict, note: str) -> str:
    """The chosen option's place, recipient and checkout instructions, in words."""
    a = o["address"]
    detail = [f"Courier: {got['courier'] or 'any the seller offers'}.",
              f"Place: {_place_said(o)}."]
    if o["kind"] in ("locker", "office"):
        detail.append(f"Pick it in the page's own list of {KIND_SAID[o['kind']]}s"
                      + (f" by its code {o['place_code']}" if o["place_code"] else "")
                      + (f" or name “{o['place_name']}”" if o["place_name"] else "")
                      + (f" in {a['city']}" if a["city"] else "") + ".")
    detail.append(f"Recipient: {got['recipient']['name'] or '(no name saved)'}"
                  + (f", {got['recipient']['phone']}" if got["recipient"]["phone"] else ", no phone saved") + ".")
    if o["notes"]:
        detail.append(f"Notes for the courier: {o['notes']}")
    return (note + got["reason"] + "\n" + "\n".join(detail)
                   + f"\nFill it in with browser fill_shipping {{\"option\": {o['id']}}}, then pick the "
                     "courier and the place where the page asks, and tell ‹owner› in one short line which one "
                     "you picked and why. Choosing shipping never means pressing the button that orders.")


def fill_values(who, option_id, limit=None) -> dict | None:
    """What `browsing.Desk.fill_shipping` puts into a checkout's fields for one option: the
    recipient, the address as far as it has one, and notes for the courier. None if it is not
    one of this person's options (or not one this turn may see)."""
    row = option_row(who, option_id)
    if row is None or (limit is not None and not _visible([row], limit)):
        return None
    o, rec = view(row), recipient(who)
    a = dict(o["address"])
    if o["kind"] != "address":
        # A locker or an office is picked in the page's own list; its street is not the recipient's.
        a.update(line1="", entrance="", floor="", apartment="", door_code="")
    name = o["recipient_name"] or rec["name"]
    first, _, last = name.partition(" ")
    extra = ", ".join(x for x in (f"entrance {a['entrance']}" if a["entrance"] else "",
                                  f"floor {a['floor']}" if a["floor"] else "",
                                  f"apartment {a['apartment']}" if a["apartment"] else "") if x)
    notes = " ".join(x for x in (o["notes"], f"Door code {a['door_code']}." if a["door_code"] else "") if x)
    return {"option": o, "name": name, "given_name": first, "family_name": last,
            "phone": o["recipient_phone"] or rec["phone"], "line1": a["line1"], "line2": extra,
            "entrance": a["entrance"], "floor": a["floor"], "apartment": a["apartment"],
            "city": a["city"], "postal_code": a["postal_code"], "country": a["country"],
            "notes": notes, "place_code": o["place_code"], "place_name": o["place_name"]}


__all__ = ["ANY", "COMPANIES", "DEFAULT", "KINDS", "PAGE", "Refused", "choose", "company_key", "decide",
           "delete_option", "delete_situation", "fill_values", "home_silo", "kind_of", "listing", "move",
           "offers_from", "option_from", "place_line", "public", "recipient", "reorder", "save_option", "save_situation",
           "set_active", "set_recipient"]
