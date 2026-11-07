"""Whose Rouh this is: the owner a request, a turn or a job is for, and how text names them.

Petar, 20 October 2026: Rouh is to be ready for fresh installations by other
people, so nobody's name, pronouns or company are written into the code, the
prompts or the defaults (SETUP.md has the whole of it).

**The owner is an account, never a word in the code.** What text calls them
comes from the stores Rouh already had, read here and nowhere else:

- the name is the account's first name (`users.first_name`), or the nickname
  on their profile when there is no first name (`rouh/profile.py`);
- the full name is the account's first and last name;
- the pronouns are on their profile (`pronouns`: "he", "she", or nothing,
  which says the name again instead);
- the company is the one on their own contact card (`people.People.me`, About
  You, Contact card, since 4 November 2026), else their organisation's name
  (`organisations.name`), unless it is still the name an organisation starts
  with.

**Whose it is** is answered the way `rouh/tenancy.py` answers who is asking:
the identity handed in (`who`), else the person whose socket this turn is on
(`tenancy.speaker`), else the person `llmlog.about` says the requests in this
context are for, else the one account an installation with exactly one
account has (`Tenancy.only_person`). A guest is never the owner: text in a
guest's context names the installation's owner. With nobody found it is "the
owner", and never anybody's name.

**Text names the owner with marks**, and the marks are filled in where the
text leaves Rouh (`say`): every request made of a model (`rouh/llmlog.py`),
every message on the page's socket and every page answered, every Telegram
message and letter, and every brief a worker is started with. A prompt that
said "Ask Petar before you send it" says "Ask ‹owner› before you send it", and
reaches the model as it was, with the owner's name in it.

The marks:

    ‹owner›  ‹Owner›            the name; "the owner" / "The owner" with none
    ‹owner_full›                the first and last name
    ‹company›                   the organisation's name
    ‹he› ‹He› ‹him› ‹his› ‹His› ‹himself›   their pronouns

With no pronouns on the profile a pronoun mark is the name again ("Alex
decides", "Alex's phone"), because the prompts' verbs were written for one
person and "they decides" is not English.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass

from . import dbwork

log = logging.getLogger("rouh.owner")

#: The first character of every mark, so text without one is passed through
#: without a second look.
OPEN = "‹"

#: Every mark there is.
MARKS = ("‹owner›", "‹Owner›", "‹owner_full›", "‹company›",
         "‹he›", "‹He›", "‹him›", "‹his›", "‹His›", "‹himself›")

_MARK = re.compile("|".join(re.escape(m) for m in MARKS))

#: What the text calls the owner when nobody is known.
NOBODY = "the owner"

#: The pronouns a profile may hold, and their forms.
PRONOUNS = {
    "he": {"‹he›": "he", "‹He›": "He", "‹him›": "him", "‹his›": "his", "‹His›": "His",
           "‹himself›": "himself"},
    "she": {"‹he›": "she", "‹He›": "She", "‹him›": "her", "‹his›": "her", "‹His›": "Her",
            "‹himself›": "herself"},
}

#: How long one owner's details are kept before they are read again. A
#: profile saved through Rouh forgets them at once (`forget`); this is only for
#: a change made some other way.
FRESH_FOR = 60.0


@dataclass(frozen=True)
class Owner:
    """The owner, as text names them."""

    user_id: str
    org_id: str
    name: str
    full_name: str = ""
    pronouns: str = ""
    company: str = ""

    def words(self) -> dict[str, str]:
        """Every mark, filled in for this owner."""
        return words(self)


def words(owner: Owner | None) -> dict[str, str]:
    """What each mark says, for this owner or for nobody."""
    name = (owner.name if owner else "") or NOBODY
    named = name[:1].upper() + name[1:]
    out = {
        "‹owner›": name,
        "‹Owner›": named,
        "‹owner_full›": (owner.full_name if owner else "") or name,
        "‹company›": (owner.company if owner else "") or f"{name}'s company",
    }
    forms = PRONOUNS.get((owner.pronouns if owner else "") or "")
    if forms:
        out.update(forms)
    else:
        out.update({"‹he›": name, "‹He›": named, "‹him›": name, "‹his›": f"{name}'s",
                    "‹His›": f"{named}'s", "‹himself›": "themself"})
    return out


# --- reading an owner ---------------------------------------------------------------------

_CACHE: dict[str, tuple[float, Owner | None]] = {}
_LOCK = threading.Lock()
_POOL = dbwork.Executor(max_workers=2, thread_name_prefix="rouh-owner")


def forget(user_id=None) -> None:
    """Read this person (or everybody) again next time, after their profile changed."""
    with _LOCK:
        if user_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(str(user_id), None)


def _in_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _sync(fn, *args):
    """Run a database read from wherever this is: a thread of its own inside an event loop."""
    if _in_loop():
        return _POOL.submit(fn, *args).result(timeout=10)
    return fn(*args)


def _card_company(user_id: str, org_id: str) -> str:
    """The company on the person's own contact card (`people.People.me`), or "". Never raises."""
    try:
        from . import people

        me = people.People().me(user_id, org_id)
        return (me.organisation if me is not None else "").strip()
    except Exception:  # noqa: BLE001 - the organisation's name is still there
        log.info("the company on the owner's contact could not be read")
        return ""


def _read(user_id: str) -> Owner | None:
    from .models import Organisation, User, UserSetting
    from .models.accounts import DEFAULT_ORG_ID, DEFAULT_ORG_NAME
    from . import profile

    try:
        user = User.objects.filter(pk=int(str(user_id))).first()
    except (TypeError, ValueError):
        return None
    if user is None or getattr(user, "is_guest", False):
        return None
    org_id = user.org_id or DEFAULT_ORG_ID
    held: dict = {}
    value = (UserSetting.objects.filter(user_id=str(user.pk), name=profile.NAME)
             .values_list("value", flat=True).first())
    if value:
        try:
            import json

            held = json.loads(value) or {}
        except (TypeError, ValueError):
            held = {}
    held = held if isinstance(held, dict) else {}
    first = (user.first_name or "").strip()
    nickname = str(held.get("nickname") or "").strip()
    name = first or nickname
    full = " ".join(p for p in ((user.first_name or "").strip(), (user.last_name or "").strip()) if p)
    company = _card_company(str(user.pk), str(org_id))
    if not company:
        # Not on their contact yet (it is carried there once, `profile.carry_to_card`): the
        # organisation's name, unless it is still the name an organisation starts with.
        company = (Organisation.objects.filter(id=org_id).values_list("name", flat=True).first() or "")
        if company.strip() == DEFAULT_ORG_NAME:
            company = ""
    pronouns = str(held.get("pronouns") or "").strip().lower()
    return Owner(user_id=str(user.pk), org_id=org_id, name=name, full_name=full or name,
                 pronouns=pronouns if pronouns in PRONOUNS else "", company=company.strip())


def of(user_id) -> Owner | None:
    """The owner with this account id, or None: no such account, or a guest's."""
    key = str(getattr(user_id, "user_id", user_id) or "").strip()
    if not key:
        return None
    now = time.monotonic()
    with _LOCK:
        held = _CACHE.get(key)
    if held is not None and now - held[0] < FRESH_FOR:
        return held[1]
    try:
        found = _sync(_read, key)
    except Exception:                               # noqa: BLE001 - text must still go out
        log.exception("the owner %s could not be read", key)
        return held[1] if held else None
    with _LOCK:
        _CACHE[key] = (now, found)
    return found


def _installation_owner() -> Owner | None:
    def only():
        from .tenancy import Tenancy

        who = Tenancy().only_person()
        return str(who.user_id) if who is not None else ""

    try:
        found = _sync(only)
    except Exception:                               # noqa: BLE001
        log.exception("the installation's one account could not be read")
        return None
    return of(found) if found else None


def resolve(who=None) -> Owner | None:
    """Whose Rouh this text is for: `who`, else the context's person, else the only account."""
    for candidate in _candidates(who):
        found = of(candidate)
        if found is not None:
            return found
    return _installation_owner()


def _candidates(who):
    if who is not None:
        yield getattr(who, "user_id", who)
    try:
        from .tenancy import speaker

        talking = speaker()
    except Exception:                               # noqa: BLE001
        talking = None
    if talking is not None:
        yield talking.user_id
    try:
        from . import llmlog

        said = llmlog.current().get("user_id")
    except Exception:                               # noqa: BLE001
        said = None
    if said:
        yield said


# --- saying text ------------------------------------------------------------------------


def has_marks(text) -> bool:
    return isinstance(text, str) and OPEN in text and bool(_MARK.search(text))


def say(text, who=None, *, owner: Owner | None = None, said: dict | None = None):
    """Text with every mark filled in for the owner it is for. Anything not text comes back as it was."""
    if not isinstance(text, str) or OPEN not in text:
        return text
    table = said if said is not None else words(owner if owner is not None else resolve(who))
    return _MARK.sub(lambda m: table[m.group(0)], text)


def say_all(value, who=None, *, owner: Owner | None = None):
    """Every string inside a structure of dicts and lists, filled in. The structure is copied only where it changes."""
    table: dict | None = None

    def walk(v):
        nonlocal table
        if isinstance(v, str):
            if OPEN not in v or not _MARK.search(v):
                return v
            if table is None:
                table = words(owner if owner is not None else resolve(who))
            return _MARK.sub(lambda m: table[m.group(0)], v)
        if isinstance(v, dict):
            out = None
            for k, item in v.items():
                new = walk(item)
                if new is not item:
                    if out is None:
                        out = dict(v)
                    out[k] = new
            return v if out is None else out
        if isinstance(v, list):
            out = None
            for i, item in enumerate(v):
                new = walk(item)
                if new is not item:
                    if out is None:
                        out = list(v)
                    out[i] = new
            return v if out is None else out
        if isinstance(v, tuple):
            items = [walk(item) for item in v]
            return v if all(a is b for a, b in zip(items, v)) else tuple(items)
        return v

    return walk(value)


def say_bytes(body: bytes, who=None) -> bytes:
    """A JSON or text body with its marks filled in, or the same bytes when it has none."""
    if not body or OPEN.encode() not in body and b"\\u2039" not in body:
        return body
    import json

    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        try:
            return say(body.decode("utf-8"), who).encode("utf-8")
        except UnicodeDecodeError:
            return body
    new = say_all(data, who)
    if new is data:
        return body
    return json.dumps(new, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def name_pattern(owner: Owner | None = None, who=None) -> str:
    """A regular expression for how a model's answer names the owner: their name, or "the owner"."""
    found = owner if owner is not None else resolve(who)
    names = [NOBODY, "the person", "owner"]
    if found is not None:
        names[:0] = [n for n in (found.name, found.full_name) if n]
    return "(?:" + "|".join(re.escape(n) for n in dict.fromkeys(names)) + ")"


#: Words of the protocol that used to be the owner's name, read as the word they are now.
LEGACY = {"petar": "owner"}


def word(value, default: str = "") -> str:
    """A protocol word as it is now: "petar", which rows and models may still say, is "owner"."""
    said = str(value or "").strip().lower()
    return LEGACY.get(said, said) or default
