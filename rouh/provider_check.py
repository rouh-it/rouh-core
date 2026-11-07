"""Whether a model company still fails, asked live before the heartbeat says it does.

On 24 October 2026 at 10:23 Sofia time the heartbeat told Petar, on his screen and on
Telegram, that Anthropic had cut Rouh off until 1 November. It had, for an hour on 23
October (10:56 to 11:58 UTC), until he raised the spending cap; every Anthropic request
after 12:08 UTC worked, the beat's own among them. The beat had read the report of a
run that diagnosed the cap the day before and passed it on as news, without asking
Anthropic again (run 2f64b48b of the one program).

So an ending of a beat that says a model company is failing is held here first
(`heartbeat.Heartbeat.end`): this asks that company one tiny question, through the LLM
service and the Models page's use for it, and only a failure lets the message go. When
every company it names answers, the message is not sent, and what the heartbeat kept as already
told about that company failing is forgotten, so a real failure later is told again
(`forget_over`).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: The words that name each company in what the heartbeat says. Only its name: a model's
#: name is said of chats and runs that fail for their own reasons too.
COMPANIES = {
    "anthropic": re.compile(r"\banthropic\b", re.I),
    "openai": re.compile(r"\bopenai\b", re.I),
}
#: The words that say a company is failing.
FAILING = re.compile(
    r"\b(cap|caps|capped|limit|limits|quota|credit|credits|block\w*|refus\w*|reject\w*|"
    r"cut\w* (\w+ )?off|outage|fail\w*|error\w*|not working|stopped working|unavailable|"
    r"overloaded|denied)\b", re.I)
#: How each company is called to the owner.
NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
#: The Models page's use each company's check asks (`modeldefaults.USES`).
USE = {"anthropic": "provider_check_anthropic", "openai": "provider_check_openai"}
#: How long the check waits for the answer before it counts as not answering.
WAIT = 30.0


@dataclass(frozen=True)
class Checked:
    company: str
    working: bool
    at: float
    said: str


def named(text: str) -> list[str]:
    """The companies `text` says are failing: each one it names, if it also says something
    fails. [] when it says nothing of the kind."""
    text = str(text or "")
    if not FAILING.search(text):
        return []
    return [c for c, words in COMPANIES.items() if words.search(text)]


async def check(company: str, *, user_id: str = "", org_id: str = "", session_id: str = "") -> Checked:
    """Ask `company` one tiny question now. Working when it answers; not working, with what
    it said, when it raises or does not answer in time."""
    import asyncio

    from . import llm, llmlog

    said = {"purpose": USE[company], "subject": company}
    if user_id:
        said["user_id"] = user_id
    if org_id:
        said["org_id"] = org_id
    if session_id:
        said["session_id"] = session_id
    try:
        with llmlog.about(**said):
            got = await llm.ask(USE[company], messages="Reply with the word OK.", max_tokens=16,
                                org_id=org_id or None, purpose=USE[company],
                                subject=company, timeout=WAIT)
        return Checked(company, True, time.time(), f"{got.model} answered")
    except asyncio.TimeoutError:
        return Checked(company, False, time.time(), f"no answer in {int(WAIT)} seconds")
    except Exception as exc:                     # what it said is the evidence either way
        return Checked(company, False, time.time(), " ".join(str(exc).split())[:300])


def forget_over(user_id: str, org_id: str, companies=None) -> list[str]:
    """Drop what the heartbeat kept as already told about a company failing, for each company
    whose latest request in the LLM service's log worked (or each of `companies`, already
    checked live). Gives back what it dropped."""
    from django.db import transaction

    from . import models

    with transaction.atomic():
        row = (models.HeartbeatState.objects.select_for_update()
               .filter(user_id=str(user_id), org_id=str(org_id)).first())
        if row is None:
            return []
        own = dict(row.own or {})
        told = list(own.get("told") or [])
        about = {c for item in told for c in named(item)}
        if not about:
            return []
        over = set(companies) & about if companies is not None else {c for c in about if latest_worked(c)}
        # Only when every company it says fails is over: "Anthropic refuses; OpenAI is fine"
        # stays while Anthropic still refuses.
        dropped = [t for t in told if named(t) and set(named(t)) <= over]
        if not dropped:
            return []
        own["told"] = [t for t in told if t not in dropped]
        models.HeartbeatState.objects.filter(id=row.id).update(own=own, updated_at=time.time())
    log.info("the heartbeat forgot, as over: %s", dropped)
    return dropped


def latest_worked(company: str) -> bool:
    """Whether the newest request to `company` in the LLM service's log worked."""
    from .models import LLMRequest

    last = (LLMRequest.objects.filter(provider=company, status__in=("ok", "error"))
            .order_by("-id").values_list("status", flat=True).first())
    return last == "ok"
