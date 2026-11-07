"""Which model providers this Rouh can ask, and with which key.

Petar, 24 October 2026: "Add Google (Gemini API) and xAI (Grok API) keys in Settings."
So there are four providers (`config.PROVIDERS`), and each install asks only the ones it
has a key for (`rouh/modeldefaults.py`: a use takes the first model on its list whose
provider has one).

- **Anthropic and OpenAI** are this installation's own keys, from its environment
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), as they always were.
- **Google and xAI** are typed into Anatomy, Rouh Land Account, Models, by an administrator of the
  organisation, and kept sealed with this instance's key (`rouh/encryption.py`), one row
  per organisation and provider (`ModelProviderKey`). The page is only ever told whether
  one is set, its last four characters, who saved it and when: nothing gives a key back.
  An installation may also set its own in its environment (`GEMINI_API_KEY`,
  `XAI_API_KEY`), the way it sets Anthropic's and OpenAI's; the organisation's own wins.

A key is read through here and nowhere else (`key`), and `has` is the one answer to
"can this provider be asked here", which the Models page, the picks and the LLM service
(`rouh/llm.py`) all use.
"""
from __future__ import annotations

import logging
import threading
import time

from .config import ANTHROPIC, GOOGLE, OPENAI, PROVIDER_NAMES, PROVIDERS, XAI, config as _config

log = logging.getLogger("rouh.providerkeys")

#: The providers whose key is typed into Settings.
TYPED = (GOOGLE, XAI)
#: The setting each provider's own key is in, for this installation.
ENV_FIELD = {ANTHROPIC: "anthropic_api_key", OPENAI: "openai_api_key",
             GOOGLE: "google_api_key", XAI: "xai_api_key"}
ENV_NAME = {ANTHROPIC: "ANTHROPIC_API_KEY", OPENAI: "OPENAI_API_KEY",
            GOOGLE: "GEMINI_API_KEY", XAI: "XAI_API_KEY"}
#: Where each provider's keys are made, for the page.
WHERE = {GOOGLE: "https://aistudio.google.com/apikey", XAI: "https://console.x.ai/"}

#: The organisations' sealed keys, read once and held a little while: a pick reads them on
#: every call. Emptied by every save.
_HELD: dict = {}
_LOCK = threading.Lock()
HOLD_SECONDS = 30


class Refused(ValueError):
    """A key that was not saved, with why in words a person can read."""


def _org(org_id: str | None) -> str:
    if org_id:
        return str(org_id)
    from .modeldefaults import org_now

    return org_now()


def _rows(org: str) -> dict:
    """{provider: (sealed, last4, saved_by, saved_at)} for this organisation, held briefly."""
    now = time.monotonic()
    with _LOCK:
        held = _HELD.get(org)
        if held and now - held[0] < HOLD_SECONDS:
            return held[1]
    got: dict = {}
    try:
        from .models import ModelProviderKey

        for r in ModelProviderKey.objects.filter(org_id=org).values(
                "provider", "key_sealed", "last4", "saved_by", "saved_at"):
            got[r["provider"]] = (r["key_sealed"], r["last4"], r["saved_by"], r["saved_at"])
    except Exception:                       # no database: only the environment's keys
        log.debug("the provider keys of %s could not be read", org, exc_info=True)
    with _LOCK:
        _HELD[org] = (now, got)
    return got


def forget() -> None:
    with _LOCK:
        _HELD.clear()


def key(provider: str, org_id: str | None = None, cfg=None) -> str:
    """The key to ask this provider with, for this organisation, or "" for none."""
    cfg = cfg or _config
    if provider in TYPED:
        sealed = (_rows(_org(org_id)).get(provider) or ("",))[0]
        if sealed:
            try:
                from .encryption import box

                return box().open_(sealed)
            except Exception:
                log.warning("the %s key of %s could not be opened", provider, org_id or "this Rouh")
    return str(getattr(cfg, ENV_FIELD.get(provider, ""), "") or "")


def has(provider: str, org_id: str | None = None, cfg=None) -> bool:
    """Whether this provider can be asked here."""
    return bool(key(provider, org_id, cfg))


def available(org_id: str | None = None, cfg=None) -> tuple:
    """The providers that can be asked here, in the default order."""
    return tuple(p for p in PROVIDERS if has(p, org_id, cfg))


def chats_can_answer(org_id: str | None = None, cfg=None) -> bool:
    """Whether Rouh's own chats have a model to answer with: any provider's key here.

    Claude Code signed in with a Claude subscription does not count: that sign-in is the
    worker's, for its runs, and Rouh's chats call a provider's API with a key of their own.
    """
    return bool(available(org_id, cfg))


def where_to_add_a_key() -> str:
    """One sentence: where the owner adds a key for the chats, on this installation."""
    from .web import claude_signin

    if claude_signin.enabled():
        return ("Rouh's chats have no model key. Add an Anthropic or OpenAI API key at "
                "/setup/claude, under Rouh's own chats: Claude Code's sign-in does not cover them.")
    return ("Rouh's chats have no model key. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in Rouh's "
            "settings, or add a Google or xAI key on the Models page.")


def shown(org_id: str | None = None, cfg=None) -> list[dict]:
    """What the Models page says of each provider: whether it can be asked and where its key
    comes from. Never the key."""
    cfg = cfg or _config
    org = _org(org_id)
    rows = _rows(org)
    out = []
    for p in PROVIDERS:
        own = rows.get(p)
        env = bool(getattr(cfg, ENV_FIELD[p], ""))
        out.append({"id": p, "name": PROVIDER_NAMES[p], "typed": p in TYPED,
                    "has": bool((own and own[0]) or env),
                    "source": "settings" if own and own[0] else "server" if env else "",
                    "last4": own[1] if own else "", "saved_by": own[2] if own else "",
                    "saved_at": own[3] if own else None, "env": ENV_NAME[p],
                    "where": WHERE.get(p, "")})
    return out


def save(org_id: str, provider: str, value: str, *, by: str = "") -> None:
    """Keep an organisation's key for Google or xAI, sealed, or remove it with an empty one."""
    provider = str(provider or "").strip().lower()
    if provider not in TYPED:
        raise Refused(f"Only Google's and xAI's keys are typed in here; {PROVIDER_NAMES.get(provider, provider)}'s "
                      "is this server's own.")
    value = "".join(str(value or "").split())
    from .models import ModelProviderKey

    if not value:
        ModelProviderKey.objects.filter(org_id=str(org_id), provider=provider).delete()
        forget()
        log.info("the %s key of %s was removed by %s", provider, org_id, by or "somebody")
        return
    if len(value) < 16 or len(value) > 400:
        raise Refused(f"That does not look like a {PROVIDER_NAMES[provider]} API key.")
    from .encryption import box

    ModelProviderKey.objects.update_or_create(
        org_id=str(org_id), provider=provider,
        defaults={"key_sealed": box().seal(value), "last4": value[-4:], "saved_by": str(by or "")[:120],
                  "saved_at": time.time()})
    forget()
    log.info("a %s key for %s was saved by %s", provider, org_id, by or "somebody")
