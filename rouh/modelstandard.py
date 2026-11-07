"""The model standard: which models each tier holds, in order, how deeply each model
thinks, which tier each use of a model starts on and in which order it asks the
providers, what each of the three modes means, and the router's confidence bar.

Petar, 24 October 2026: four providers, not two - Anthropic, OpenAI, Google (Gemini)
and xAI (Grok) - and **each tier an ordered list of models across them** (schema 4,
`tiers.<tier>.models`), so an install takes the first model on the list whose
provider it has a key for (`rouh/modeldefaults.py`). A use may carry an order of its
own for each tier (`uses.<use>.order.<tier>`: providers or model ids, first asked
first), which is how
rouh.land reorders one use without touching another once its blind votes show a model
does better there (rouh.land's `rouhit/rankings.py`); the built-in standard gives every
use one, in the default order until there is data: Anthropic, OpenAI, Google, xAI,
except that Cheaper keeps GPT-6 Luna first, the model every Cheaper use ran on the day
the lists came, so nothing anybody runs on changed. A standard of schema 3 or older
(one OpenAI and one Anthropic model a tier, with a main one) is still read: its main
model first, the other second, and this install's Google and xAI models after them.

Petar, 23 October 2026 (card 1842): two tiers, not three - **Smart** (Opus 5.5,
and GPT-6.1 Sol for what can only ask OpenAI) and **Cheaper** (GPT-6 Luna) - and
three modes on top of them, one choice at the top of the Models page: **Best**
(always Smart), **Balanced** (the router decides each message, the default) and
**Saver** (always Cheaper, never paying per token for anything above it). Best,
the third tier, is gone: a standard of schema 2 or 1 is still read, its Daily
tier being Smart and its Best tier dropped, and a use it puts on Best or Daily
is on Smart (`tier_id`). Schema 3 adds `modes` and `router` (`bar`).

Petar, 18 October 2026: "most Rouh users will not know which model to pick. They
end up with a weaker model and worse results, or pay more than they need to." So
nobody has to pick a model for a use. Each tier holds one of OpenAI's models and
one of Anthropic's, one of the two its main one, and every use of a model is on
one of them (`rouh/modeldefaults.py`). A model always thinks at the level that
comes with it, from its benchmarks and score cards, and nobody picks that either.

**The standard is data, one table** (`model_standard.json`, beside this file):
the two tiers, the effort for every model on the list with a reason and a
source, the tier each use starts on, with a reason, what each mode means and the
router's bar. Its shape is `model_standard.schema.json`, version 4; `check` below
is the same rules in code, so a standard that breaks them is never used. Version
2 (three tiers) and version 1 (a tier was one model with a stand-in of each
company, whose company is the tier's main one) are still read (`READS`).

**One person sets it, and every Rouh follows.** The standard Petar publishes is
at `config.model_standard_url` on rouh.land. Once a day every Rouh fetches it
(`fetch`), saying the version of the shape it reads (`?schema=4`), so rouh.land
answers a Rouh that reads only schema 2 in that shape and this one in its own;
a good one is kept (`app_state`, `STATE`) and used for everything the
person has not changed themselves - a person's own picks are theirs and are
never written over. A fetch that fails keeps the last good standard, and the
failure is written down quietly (`FETCHED`), never shown as a notice: a
standard a day old is still a standard. Before the first good fetch, and on an
install that fetches nothing, the one built in is the standard.

What a fetched standard may say is narrow on purpose: only models on this
install's list (`config.MODEL_CHOICES`), only the five levels, only uses this
install has. Anything else in it is left out, and what it leaves out is the
built-in standard's, so a published standard can be small.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import time

from .config import EFFORTS, MODEL_CHOICES, PROVIDERS, config as _config, is_openai, provider_of

log = logging.getLogger("rouh.modelstandard")

HERE = os.path.dirname(os.path.abspath(__file__))
BUILT_IN_FILE = os.path.join(HERE, "model_standard.json")
SCHEMA_FILE = os.path.join(HERE, "model_standard.schema.json")

#: The version of the standard's shape this Rouh reads. A standard of another
#: version is refused, and the last good one kept, so a change of shape on
#: rouh.land can never break a Rouh that does not know it yet.
SCHEMA = 4
#: The versions this Rouh reads: 1 is the shape of the first day, 2 the three tiers of
#: 18 October 2026, which rouh.land gives a Rouh that does not say it reads 3, 3 the
#: two tiers and three modes of 23 October 2026, and 4 the ordered lists of 24 October.
READS = (1, 2, 3, 4)

CHEAPER, SMART = "cheaper", "smart"
#: The two tiers, cheapest first: the order every screen shows them in.
TIERS = (CHEAPER, SMART)
TIER_NAMES = {CHEAPER: "Cheaper", SMART: "Smart"}
#: What a tier was called before: the middle tier was Recommended until the evening of
#: 18 October 2026 and Daily until 23 October 2026, when it became Smart and Best, the
#: third, went (Petar, card 1842). A row, a standard or a retry that names any of them
#: means Smart.
OLD_NAMES = {"recommended": SMART, "daily": SMART, "best": SMART}
#: The old names a schema 2 or 1 standard's tiers may come under, best first: its Daily
#: tier is Smart, and its Best tier is no tier any more.
TIER_SOURCES = {CHEAPER: (CHEAPER,), SMART: (SMART, "daily", "recommended")}

#: The three modes (Petar, 23 October 2026): Best always answers on Smart, Balanced
#: has the router decide each message, Saver always answers on Cheaper and pays per
#: token for nothing above it.
BEST, BALANCED, SAVER = "best", "balanced", "saver"
MODES = (BEST, BALANCED, SAVER)
MODE_NAMES = {BEST: "Best", BALANCED: "Balanced", SAVER: "Saver"}
DEFAULT_MODE = BALANCED
#: The router's bar when no standard says one: Cheaper only when it is at least this sure
#: the message is easy.
DEFAULT_BAR = 0.9

ANTHROPIC, OPENAI, GOOGLE, XAI = "anthropic", "openai", "google", "xai"
COMPANIES = PROVIDERS


def tier_id(tier) -> str:
    """A tier's id as it is now, from anything that may name it the old way."""
    tier = str(tier or "").strip().lower()
    return OLD_NAMES.get(tier, tier)


def mode_id(mode) -> str:
    """A mode's id, or the default for anything that is not one."""
    mode = str(mode or "").strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def company_of(model: str) -> str:
    return provider_of(model)


def ordered(models) -> list[str]:
    """A list of models as a tier may hold it: models on this install's list, each once."""
    out = []
    for m in models or []:
        m = str(m or "").strip()
        if m in _MODELS and m not in out:
            out.append(m)
    return out


def order_by(models: list[str], order) -> list[str]:
    """`models` with those that `order` names first, in its order: `order` holds providers
    or model ids, and a model is placed by its own id when named, else by its provider. What
    it does not name keeps its place after them."""
    order = [str(o) for o in order or []]
    if not order:
        return list(models)

    def rank(i_m):
        i, m = i_m
        if m in order:
            return (order.index(m), i)
        p = provider_of(m)
        return (order.index(p) + 0.5, i) if p in order else (len(order) + 1, i)

    return [m for _, m in sorted(enumerate(models), key=rank)]

#: The use's choice that is no model at all: the heartbeat's wake-up check, off.
OFF = "off"

#: A use whose tier a model picks for each message (`rouh/modelrouter.py`), as a call is
#: written down; in the standard it is `routed` on a use, and in revision 2026-10-18.2 it
#: was a use's tier, "auto", which is read as routed on Daily.
AUTO = "auto"

#: Where the standard last fetched is kept, and what the last fetch said.
STATE = "model_standard"
FETCHED = "model_standard_fetch"

#: How often the standard is fetched.
EVERY = 24 * 3600
#: The most a published standard may weigh: it is a few kilobytes.
MOST_BYTES = 256 * 1024

_MODELS = {m for m, _ in MODEL_CHOICES}


class Bad(ValueError):
    """A standard that breaks the schema, with what is wrong in words."""


def built_in() -> dict:
    """The standard this install ships with. A fresh copy each time."""
    with open(BUILT_IN_FILE, encoding="utf-8") as f:
        return check(json.load(f), whole=True)


def check(doc, *, whole: bool = False) -> dict:
    """The standard as it may be used, or `Bad`.

    `whole` is the built-in standard, which must say everything: every tier,
    an effort for every model on the list and a tier for every use. A fetched
    one need only be well formed: whatever it leaves out is the built-in's
    (`merged`), and a model, a use or a level this install does not have is
    dropped rather than refusing the rest.
    """
    if not isinstance(doc, dict):
        raise Bad("a standard is a JSON object")
    if doc.get("schema") not in READS:
        raise Bad(f"schema {doc.get('schema')!r} is not one of {READS}")
    revision = str(doc.get("revision") or "").strip()
    if not revision or len(revision) > 64:
        raise Bad("revision is missing")
    out = {"schema": SCHEMA, "revision": revision,
           "published": str(doc.get("published") or "")[:40], "tiers": {}, "efforts": {},
           "uses": {}}
    tiers = doc.get("tiers")
    if not isinstance(tiers, dict):
        raise Bad("tiers is missing")
    tiers = {str(k).strip().lower(): v for k, v in tiers.items()}
    for tier in TIERS:
        # A schema 2 standard's Daily is Smart; its Best is no tier any more and is left out.
        t = next((tiers[k] for k in TIER_SOURCES[tier] if k in tiers), None)
        if t is None and not whole:
            continue
        if not isinstance(t, dict):
            raise Bad(f"tier {tier} is missing")
        if isinstance(t.get("models"), list):
            # Version 4: the tier's models in order, across the providers. One this install
            # does not have is left out; a tier left with none is not used.
            models = ordered(t["models"])
            if not models:
                raise Bad(f"tier {tier}: none of its models is one this Rouh has")
        else:
            anth, oai = (str(t.get(k) or "") for k in ("anthropic", "openai"))
            if anth not in _MODELS or is_openai(anth):
                raise Bad(f"tier {tier}: anthropic {anth!r} is not one of Anthropic's models")
            if oai not in _MODELS or not is_openai(oai):
                raise Bad(f"tier {tier}: openai {oai!r} is not one of OpenAI's models")
            main = str(t.get("main") or "")
            if not main:
                # Version 1: the tier's one model, which was its own company's stand-in too.
                model = str(t.get("model") or "")
                if model not in (anth, oai):
                    raise Bad(f"tier {tier}: its model must be its own company's stand-in too")
                main = company_of(model)
            if main not in (OPENAI, ANTHROPIC):
                raise Bad(f"tier {tier}: main {main!r} is not openai or anthropic")
            # Version 3 and older: the main model first, then the other company's.
            models = [oai, anth] if main == OPENAI else [anth, oai]
        out["tiers"][tier] = {"models": models, "why": str(t.get("why") or "")[:400]}
    efforts = doc.get("efforts")
    if not isinstance(efforts, dict):
        raise Bad("efforts is missing")
    for model, e in efforts.items():
        if model not in _MODELS or not isinstance(e, dict):
            continue
        level = str(e.get("effort") or "")
        if level not in EFFORTS and level != "":
            raise Bad(f"effort for {model}: {level!r} is not one of {', '.join(EFFORTS)}")
        out["efforts"][model] = {"effort": level, "why": str(e.get("why") or "")[:600],
                                 "source": str(e.get("source") or "")[:400],
                                 "source_title": str(e.get("source_title") or "")[:200]}
    uses = doc.get("uses")
    if not isinstance(uses, dict):
        raise Bad("uses is missing")
    from .modeldefaults import BY_ID

    for use_id, u in uses.items():
        use = BY_ID.get(use_id)
        if use is None or not isinstance(u, dict):
            continue
        if isinstance(u.get("tier"), list):
            # Schema 4: models of its own, in order across providers (Custom), each one it may
            # ask; a model this Rouh does not have is left out.
            mine = [m for m in ordered(u["tier"]) if use.providers and company_of(m) in use.providers]
            if not mine:
                if whole:
                    raise Bad(f"use {use_id}: none of its models is one it can ask")
                continue
            out["uses"][use_id] = {"tier": mine, "why": str(u.get("why") or "")[:400]}
            continue
        raw = str(u.get("tier") or "").strip()
        tier = raw if raw in _MODELS else tier_id(raw)
        routed = bool(u.get("routed"))
        if tier == AUTO:
            # Revision 2026-10-18.2 put the chats on "auto", a choice of their own; since
            # the evening of 18 October 2026 Auto is a toggle per box, and a routed
            # use is on its tier (Daily) with `routed` (`routed` below).
            tier, routed = SMART, True
        own = tier in _MODELS and (not use.only or company_of(tier) == use.only)
        if tier not in TIERS and not own and not (tier == OFF and use.can_be_off):
            if whole:
                raise Bad(f"use {use_id}: {tier!r} is not a tier it can be on")
            # A choice this Rouh does not have (a newer standard's): the use keeps the
            # built-in standard's, and the rest of the standard is still used.
            log.info("the model standard puts %s on %r, which it cannot be on here", use_id, tier)
            continue
        out["uses"][use_id] = {"tier": tier, "why": str(u.get("why") or "")[:400]}
        if routed and tier in TIERS:
            out["uses"][use_id]["routed"] = True
        order = u.get("order")
        if isinstance(order, dict):
            # For each tier, providers or model ids, first asked first (schema 4); what this
            # Rouh does not know is left out.
            got = {}
            for t, said in order.items():
                t = tier_id(t)
                kept = [str(o) for o in said if str(o) in PROVIDERS or str(o) in _MODELS] \
                    if t in TIERS and isinstance(said, list) else []
                if kept:
                    got[t] = list(dict.fromkeys(kept))
            if got:
                out["uses"][use_id]["order"] = got
    modes = doc.get("modes")
    if isinstance(modes, dict):
        out["modes"] = {m: {"why": str((modes.get(m) or {}).get("why") or "")[:600]}
                        for m in MODES if isinstance(modes.get(m), dict)}
        default = str(modes.get("default") or "")
        if default in MODES:
            out["modes"]["default"] = default
    router = doc.get("router")
    if isinstance(router, dict):
        try:
            bar = float(router.get("bar"))
        except (TypeError, ValueError):
            raise Bad("router.bar is not a number")
        if not 0.5 <= bar <= 1.0:
            raise Bad(f"router.bar {bar} is not between 0.5 and 1")
        out["router"] = {"bar": bar, "why": str(router.get("why") or "")[:400]}
    doubles = doc.get("double_calls")
    if isinstance(doubles, dict):
        try:
            rate = float(doubles.get("rate") or 0)
        except (TypeError, ValueError):
            raise Bad("double_calls.rate is not a number")
        out["double_calls"] = {"rate": max(0.0, min(rate, 0.2)), "why": str(doubles.get("why") or "")[:400]}
    if whole:
        if not out.get("router") or not out.get("modes"):
            raise Bad("the built-in standard says what the modes mean and the router's bar")
        missing = sorted(_MODELS - set(out["efforts"]))
        if missing:
            raise Bad("no effort for " + ", ".join(missing))
        missing = sorted(set(BY_ID) - set(out["uses"]))
        if missing:
            raise Bad("no tier for " + ", ".join(missing))
    return out


def merged(fetched: dict | None) -> dict:
    """The fetched standard over the built-in one: what it says wins, and what
    it leaves out is the built-in's."""
    base = built_in()
    # A standard older than the one this Rouh was built with is stale: a deploy brought a
    # newer one before rouh.land published it, so the built-in one stands until it does.
    if not fetched or str(fetched.get("revision") or "") < str(base.get("revision") or ""):
        base["source"] = "built-in"
        return base
    out = copy.deepcopy(base)
    out["revision"], out["published"] = fetched["revision"], fetched.get("published", "")
    for part in ("tiers", "efforts", "uses", "modes"):
        out[part].update(copy.deepcopy(fetched.get(part) or {}))
    for tier, t in (fetched.get("tiers") or {}).items():
        # A tier that names none of a provider's models (a schema 3 standard names only
        # OpenAI's and Anthropic's) keeps this Rouh's own for it, after the ones it names.
        mine = [m for m in base["tiers"].get(tier, {}).get("models", [])
                if provider_of(m) not in {provider_of(x) for x in t.get("models", [])}]
        out["tiers"][tier] = {**out["tiers"][tier], "models": list(t.get("models", [])) + mine}
    if fetched.get("router"):
        out["router"] = copy.deepcopy(fetched["router"])
    if fetched.get("double_calls"):
        out["double_calls"] = copy.deepcopy(fetched["double_calls"])
    # The mark of a fetched standard, a word and not an address: kept as it was before the move
    # to rouh.land (task 165), as the page and the rule defaults' stamps read it.
    out["source"] = "rouh.it"
    return out


# --- what is kept --------------------------------------------------------------------------

def _state(key: str) -> dict:
    try:
        from .models.memory import AppState

        raw = AppState.objects.filter(key=key).values_list("value", flat=True).first()
        got = json.loads(raw) if raw else {}
        return got if isinstance(got, dict) else {}
    except Exception:
        log.exception("%s could not be read", key)
        return {}


def _keep(key: str, value: dict) -> None:
    from .models.memory import AppState

    AppState.objects.update_or_create(key=key, defaults={"value": json.dumps(value)})


#: The standard in use, read once and then again whenever a fetch keeps a new one.
_CACHE: dict = {}


def current() -> dict:
    """The standard in use now: the last good one fetched over the built-in one.
    Never raises: a kept copy that cannot be read is the built-in standard."""
    if _CACHE.get("doc") is not None and time.time() - _CACHE.get("at", 0) < 60:
        return _CACHE["doc"]
    kept = _state(STATE).get("doc")
    try:
        doc = merged(check(kept) if kept else None)
    except Bad as exc:
        log.warning("the kept model standard is not usable (%s): using the built-in one", exc)
        doc = merged(None)
    _CACHE.update(doc=doc, at=time.time())
    return doc


def forget_cache() -> None:
    _CACHE.clear()


def fetched_said() -> dict:
    """What the last fetch said, for the Models page: when, and whether it worked."""
    return _state(FETCHED)


# --- the daily fetch -----------------------------------------------------------------------

#: How soon a fetch that failed is tried again.
RETRY = 60 * 60


def due(now: float | None = None) -> bool:
    """Whether to fetch now: a day since the last good fetch, and an hour since the
    last try of any kind."""
    now = time.time() if now is None else now
    said = fetched_said()
    return (now - float(said.get("ok_at") or 0) >= EVERY
            and now - float(said.get("at") or 0) >= RETRY)


def fetch(cfg=None, *, url: str | None = None) -> dict:
    """Fetch the published standard and keep it if it is good. Never raises.

    Gives back what is written down about this fetch: `{at, ok, revision?,
    error?}`. A failure keeps the last good standard and is in the log once.
    """
    import httpx

    cfg = cfg or _config
    url = (cfg.model_standard_url if url is None else url) or ""
    said: dict = {"at": time.time(), "url": url}
    if not url:
        said.update(ok=False, error="no address to fetch the standard from")
        _say(said)
        return said
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True,
                          headers={"Accept": "application/json",
                                   "User-Agent": "Rouh model standard/1"}) as client:
            # Which shape this Rouh reads, so rouh.land can answer an older Rouh in the shape it
            # knows (three tiers, schema 2) and this one in its own: kept with any query of its own.
            r = client.get(httpx.URL(url).copy_merge_params({"schema": SCHEMA}))
        if r.status_code != 200:
            raise Bad(f"HTTP {r.status_code}")
        if len(r.content) > MOST_BYTES:
            raise Bad(f"{len(r.content)} bytes is too big for a standard")
        doc = check(r.json())
    except (Bad, ValueError, httpx.HTTPError) as exc:
        said.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        log.info("the model standard could not be fetched from %s: %s; the last good one is "
                 "kept", url, said["error"])
        _say(said)
        return said
    try:
        _keep(STATE, {"doc": doc, "fetched_at": said["at"], "url": url})
    except Exception as exc:
        said.update(ok=False, error=f"could not be kept: {exc}"[:300])
        log.exception("the model standard fetched from %s could not be kept", url)
        _say(said)
        return said
    said.update(ok=True, ok_at=said["at"], revision=doc["revision"])
    _say(said)
    forget_cache()
    log.info("model standard %s fetched from %s", doc["revision"], url)
    return said


def _say(said: dict) -> None:
    """Write down what this fetch said, keeping when the last good one was."""
    if not said.get("ok_at"):
        said = {**said, "ok_at": fetched_said().get("ok_at") or 0}
    try:
        _keep(FETCHED, said)
    except Exception:
        log.exception("what the model standard's fetch said could not be written down")


# --- reading it ----------------------------------------------------------------------------

def effort(model: str, doc: dict | None = None) -> str:
    """The level this model thinks at, by the standard: "" for one that takes
    none (Haiku 4.5), and "medium" for a model the standard does not know."""
    doc = doc or current()
    got = (doc.get("efforts") or {}).get(model)
    if got is None:
        return "medium"
    return str(got.get("effort") or "")




def tier_of_use(use_id: str, doc: dict | None = None):
    """The choice a use starts on: a tier, off, a model's id, or a list of models of its own."""
    doc = doc or current()
    held = ((doc.get("uses") or {}).get(use_id) or {}).get("tier")
    if isinstance(held, list):
        return list(held)
    raw = str(held or "")
    return raw if raw in _MODELS else (tier_id(raw) or SMART)


def routed(use_id: str, doc: dict | None = None) -> bool:
    """Whether this use is one of the chats the mode decides (`modeldefaults.Now.routed`):
    Best puts it on Smart, Saver on Cheaper, and Balanced has the router decide each of
    its messages (`rouh/modelrouter.py`). Nobody picks it for a use: it is the service's."""
    doc = doc or current()
    return bool(((doc.get("uses") or {}).get(use_id) or {}).get("routed"))


def bar(doc: dict | None = None) -> float:
    """How sure the router must be that a message is easy before Cheaper answers it."""
    doc = doc or current()
    try:
        return float((doc.get("router") or {}).get("bar") or DEFAULT_BAR)
    except (TypeError, ValueError):
        return DEFAULT_BAR


def default_mode(doc: dict | None = None) -> str:
    """The mode an organisation that has not picked one is on: the service's."""
    doc = doc or current()
    return mode_id((doc.get("modes") or {}).get("default"))


def mode_why(mode: str, doc: dict | None = None) -> str:
    doc = doc or current()
    return str(((doc.get("modes") or {}).get(mode) or {}).get("why") or "")


def double_rate(doc: dict | None = None) -> float:
    """The share of read-only answers asked of a second model too, while Auto is on."""
    doc = doc or current()
    return float((doc.get("double_calls") or {}).get("rate") or 0.0)


def tier_pick(tier: str, doc: dict | None = None) -> list[str]:
    """A tier's models, in order, by the standard."""
    doc = doc or current()
    return list(doc["tiers"][tier]["models"])


def tier_model(tier: str, doc: dict | None = None) -> str:
    """A tier's first model, by the standard."""
    return tier_pick(tier, doc)[0]


def use_order(use_id: str, tier: str, doc: dict | None = None) -> list[str]:
    """The order a use asks a tier's models in, by the standard: providers or model ids, or
    nothing for the tier's own order. Set for each use and each tier on its own, so rouh.land
    can move a model up for one use without moving it for any other."""
    doc = doc or current()
    return list((((doc.get("uses") or {}).get(use_id) or {}).get("order") or {}).get(tier) or [])


def published() -> dict:
    """The built-in standard as rouh.land publishes it: without the parts that are
    only this install's reading (`source`)."""
    doc = built_in()
    doc.pop("source", None)
    return doc
