"""Feature switches: one on/off switch per feature, the organisation's.

Petar, 6 October 2026, setting up the nightly feature run (`rouh/nightly_feature.py`):
every feature it builds is built behind an on/off switch of its own, and his Reject and
undo turns that switch off at once, before anything is reverted, so the feature stops the
moment he says so rather than when a run has finished undoing it.

**Using one.** A feature asks whether it is on where it starts doing anything, by its
name, and does nothing when it is off::

    from rouh import switches

    if not switches.on("calendar_digest"):
        return

A name is lowercase letters, digits and underscores. A switch nobody has written is on,
so a feature works the moment it is deployed; it registers itself with a title for the
Settings page by `register`. The nightly run registers its genes' switches off (its
`nightly_switch` and `nightly_gene` tools): since 13 October 2026 a gene it builds is a
candidate until Petar keeps it in Mutations (`rouh/evolution.py`, EVOLUTION.md).

**Where it is seen.** A gene's switch is its row's in Evolution, Mutations (`rouh/evolution.py`),
where Keep, Turn off and Turn on again turn it. Every other switch, Rouh's own and a shared
gene's, is listed with its state under Other switches, in Mutations' In your Rouh
(`evolution.other_switches`), and turned there. Until 14 October 2026 they were all on
Settings, Services; Services is now what is paid for (`rouh/services.py`) and has no switches.
Any switch is also turned with
``python manage.py feature_switch <name> on|off``.

**Whose.** A feature is the install's, so a switch is keyed by `org_id`, and every query
here names it (`AGENTS.md`, "Whose data is it"). A call that names no organisation means
the one the speaker belongs to, else the install's own (`tenancy.org_now`).

Reading one is a database read, kept for a few seconds so a feature asked about in a loop
does not ask the database every time; turning one off clears that at once in this process.
"""
from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger("rouh.switches")

#: What a switch may be called.
NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
#: How long a switch's state is kept before it is read again, in seconds.
FRESH = 5.0

_seen: dict[tuple[str, str], tuple[float, bool]] = {}
_lock = threading.Lock()


class Refused(ValueError):
    """A switch that cannot be named or changed, with the reason."""


def _org(org_id) -> str:
    if org_id:
        return str(org_id)
    from .modeldefaults import org_now

    return str(org_now())


def clean(name) -> str:
    """The switch's name as it is kept, or Refused."""
    text = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not NAME.match(text):
        raise Refused(f"{name!r} is not a switch's name: lowercase letters, digits and "
                      "underscores, starting with a letter, such as calendar_digest.")
    return text


def _model():
    from .models import FeatureSwitch

    return FeatureSwitch


def on(name: str, org_id: str | None = None) -> bool:
    """Whether the feature is on. Never raises: a switch that cannot be read is on, the
    way it was before it had a switch, and the reason is logged."""
    try:
        key = (_org(org_id), clean(name))
    except Exception:
        log.exception("the switch %r could not be named; treating it as on", name)
        return True
    now = time.monotonic()
    with _lock:
        got = _seen.get(key)
        if got is not None and now - got[0] < FRESH:
            return got[1]
    try:
        state = _model().objects.filter(org_id=key[0], name=key[1]).values_list(
            "on", flat=True).first()
    except Exception:
        log.exception("the switch %s could not be read; treating it as on", key[1])
        return True
    value = True if state is None else bool(state)
    with _lock:
        _seen[key] = (now, value)
    return value


def register(name: str, title: str = "", *, org_id: str | None = None,
             night_id: int | None = None, on: bool = True) -> dict:
    """Make the switch if it is not there, on unless `on` is False; give it a title. Never turns
    an existing one on or off. The nightly run makes its genes' switches off: a gene it builds
    is a candidate until Petar keeps it in Mutations (`rouh/evolution.py`)."""
    org, key = _org(org_id), clean(name)
    title = " ".join(str(title or "").split())[:160]
    row, made = _model().objects.get_or_create(
        org_id=org, name=key, defaults={"title": title, "on": bool(on), "night_id": night_id,
                                        "changed_by": "registered" if on else "registered off, a candidate",
                                        "updated_at": time.time()})
    if made:
        with _lock:
            _seen.pop((org, key), None)
    if not made and title and row.title != title:
        _model().objects.filter(id=row.id).update(title=title)
        row.title = title
    return view(row)


def set_on(name: str, value: bool, *, by: str, org_id: str | None = None,
           title: str = "") -> dict:
    """Turn the switch on or off, making it if it is not there."""
    org, key = _org(org_id), clean(name)
    fields = {"on": bool(value), "changed_by": str(by or "")[:80], "updated_at": time.time()}
    row, made = _model().objects.get_or_create(
        org_id=org, name=key, defaults={**fields, "title": " ".join(str(title or "").split())[:160]})
    if not made:
        _model().objects.filter(id=row.id).update(**fields)
        for k, v in fields.items():
            setattr(row, k, v)
    with _lock:
        _seen.pop((org, key), None)
    log.info("feature switch %s is %s now (%s)", key, "on" if value else "off", by)
    return view(row)


def listing(org_id: str | None = None) -> list[dict]:
    return [view(r) for r in _model().objects.filter(org_id=_org(org_id)).order_by("name")]


def view(row) -> dict:
    return {"name": row.name, "title": row.title or "", "on": bool(row.on),
            "night": row.night_id, "changed_by": row.changed_by or "",
            "updated_at": row.updated_at}
