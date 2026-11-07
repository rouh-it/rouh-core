"""Genes on the fly: a gene's contract drafted from a conversation, shaped, grown into Rouh, and kept or
taken out (GENES.md, "Genes on the fly"; task 98, step 98-17).

Petar, 13 October 2026, in the chat "On-the-fly gene formulation": "Let's discuss how we can start
formulating genes on the fly". Rouh's proposal that day (card 1504): when he says "that should be a
gene", Rouh writes its contract on a card at once - what it does, where it shows up, what it changes,
how it is removed - he revises it by voice, every version kept, and "grow it" makes the contract the
brief of a build that lands it as a gene behind its switch, off until he tries it; drafts never grown
sit in task 94's ideas list. One thing was left to him: "should I offer a gene on my own when I see
you doing something by hand, or only when you ask?" He has not answered, so it is a setting, per
person, in Evolution's Parameters (`evolution_settings.propose`), and it starts at "only when I ask".

* **A draft** is a node of the gene log (`rouh/genelog.py`), origin "draft", status "draft", with every
  version of its contract kept in order (`draft["versions"]`). It is drafted by Rouh's model with the
  tool `gene_draft`, from what the person said, never from a gene someone else wrote.
* **Growing** it starts a run briefed with the contract the person shaped: it builds the gene behind a
  switch of its own, registered off, and ends its commit with `Gene: <key>`, so the log shows it Being
  built, then Off once it lands; Turn it on is accepting it, and Take it out removes it as its contract
  says (both the log's own).
* **Leaving it for the night** puts it in the nightly run's brief, which adds it to task 94's
  `ideas.md` as an entry of its own and may pick it like any other idea. Rouh does not write the
  workspace itself: a deploy resets the live workspace to main, and the night's run lands its own.
* **Dropping** a draft deletes it; a grown gene is taken out instead.

Its switch `gene_drafts` turns the tool off. The contract is informational, never a permission: a
gene may change Rouh in any way except the protected core (GENES.md, "What a gene may change"),
and the contract says truthfully how.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("rouh.genedraft")

SWITCH = "gene_drafts"
#: Whether Rouh may offer to draft a gene unprompted: Petar's question, still open (card 1504).
PROPOSE = {"asked": "Only when I ask for one", "offer": "Rouh may offer one when it sees something worth it"}
VERSIONS_MOST = 40


class Refused(ValueError):
    """Something a draft will not do, with the reason in words."""


def _m():
    from . import models

    return models


def _now() -> float:
    return time.time()


def on(org: str) -> bool:
    from . import switches

    return switches.on(SWITCH, org)


def propose(who) -> str:
    row = _m().EvolutionSetting.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id)).first()
    value = getattr(row, "propose", "") or "asked"
    return value if value in PROPOSE else "asked"


def set_propose(who, value: str, *, by: str = "") -> dict:
    from . import evolution

    if value not in PROPOSE:
        raise Refused("It is asked or offer.")
    M = _m().EvolutionSetting
    row = M.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id)).first()
    if row is None:
        # No Parameters yet: the proposal's numbers, as Parameters reads them, and this setting.
        d = evolution.DEFAULTS
        row = M.objects.create(org_id=str(who.org_id), user_id=str(who.user_id), total=d["total"],
                               invisible=d["invisible"], shows_up=d["shows_up"], ask_for=d["ask_for"],
                               changes_work=d["changes_work"], updated_at=_now(), by="", history=[])
    M.objects.filter(id=row.id).update(propose=value, updated_at=_now())
    said = {"asked": "Rouh drafts a gene only when you ask for one.",
            "offer": "Rouh may offer to draft a gene when it sees something worth one."}[value]
    return {"ok": True, "propose": value, "said": said}


def prompt_line(who) -> str:
    """For a turn the person started: Rouh may offer to draft a gene, when their setting says so."""
    if who is None or not on(str(who.org_id)) or propose(who) != "offer":
        return ""
    return ("Genes on the fly: the person has said you may offer to draft a gene when you see them do "
            "something by hand that Rouh could do for them every time, or when an idea of theirs is an "
            "ability Rouh lacks. Offer in one short sentence at the end of your answer, at most once a "
            "conversation, and draft it with gene_draft only when they say yes.")


# --- drafts ----------------------------------------------------------------------------------------


def _contract_from(args: dict, before: dict | None = None) -> dict:
    from . import genelog

    before = before or {}
    t = dict(before.get("touches") or {})
    for k in ("permissions", "accounts", "tables", "jobs"):
        if k in args:
            t[k] = args.get(k) or []
    raw = {"what": args.get("what") if "what" in args else before.get("what"),
           "where": args.get("where") if "where" in args else before.get("where"),
           "touches": t, "remove": args.get("remove") if "remove" in args else before.get("remove")}
    return genelog.clean_contract(raw)


def _view(n) -> str:
    c = n.contract or {}
    t = c.get("touches") or {}
    parts = [f"Gene {n.id} “{n.name}” ({n.status}): {c.get('what')}"]
    if c.get("where"):
        parts.append(f"Where: {c['where']}.")
    for k, label in (("permissions", "May do"), ("accounts", "Outside accounts"), ("tables", "Tables"),
                     ("jobs", "Scheduled work")):
        if t.get(k):
            parts.append(f"{label}: {', '.join(t[k])}.")
    parts.append(f"To remove: {(c.get('remove') or 'not said yet').rstrip('.')}.")
    parts.append(f"Version {len((n.draft or {}).get('versions') or [])}. Its page: /evolution/mutations/log/{n.id}")
    return " ".join(parts)


def _draft_node(who, gene_id):
    from . import genelog

    n = genelog._node(who, gene_id)
    if n.origin != "draft":
        raise Refused(f"{n.name} is not a gene drafted on the fly.")
    return n


def draft(who, args: dict, *, chat: str = "") -> dict:
    """A new draft from what the person said: its contract, its first version."""
    from . import genelog

    org = str(who.org_id)
    if not on(org):
        raise Refused("Genes on the fly are switched off here (gene_drafts, under Other switches in Evolution, Mutations).")
    name = genelog._cut(args.get("name"), 80)
    if not name:
        raise Refused("A gene needs a name, in two to five words.")
    contract = _contract_from(args)
    if not contract["what"]:
        raise Refused("Say in one sentence what the gene does.")
    if not contract["remove"]:
        contract["remove"] = "Not written yet: say how it is taken out before it is grown."
    now = _now()
    n = genelog.make(org, genelog.free_key(org, "draft-" + genelog._slug(name)[:34]), name, contract=contract,
                     origin="draft", status="draft", at=now, sentence=contract["what"],
                     requested_by=str(who.user_id), by="person", made_by="drafted in a conversation",
                     draft={"versions": [{"at": now, "contract": contract, "said": "First draft."}],
                            "chat": str(chat or "")[:80], "idea": genelog._cut(args.get("idea"), 600)},
                     said="Drafted in a conversation, from the person's own words.")
    return {"ok": True, "gene": n.id, "said": "Drafted. " + _view(n)}


def revise(who, gene_id, args: dict) -> dict:
    from . import genelog

    n = _draft_node(who, gene_id)
    if n.status not in ("draft",):
        raise Refused(f"{n.name} is {genelog.STATUSES.get(n.status, n.status).lower()}: change it by building on it.")
    contract = _contract_from(args, n.contract)
    name = genelog._cut(args.get("name"), 80) or n.name
    d = dict(n.draft or {})
    versions = list(d.get("versions") or []) + [{"at": _now(), "contract": contract,
                                                  "said": genelog._cut(args.get("why") or "Revised.", 300)}]
    d["versions"] = versions[-VERSIONS_MOST:]
    _m().GeneLogGene.objects.filter(id=n.id).update(
        name=name, contract=contract, contract_sha=genelog.contract_sha(contract), sentence=contract["what"],
        draft=d, changed_at=_now(), updated_at=_now())
    genelog._event(n, "revised", by="person", detail=f"Version {len(d['versions'])}: {contract['what']}")
    n.refresh_from_db()
    return {"ok": True, "gene": n.id, "said": "Revised. " + _view(n)}


def leave_for_night(who, gene_id, yes: bool = True) -> dict:
    from . import genelog

    n = _draft_node(who, gene_id)
    if n.status != "draft":
        raise Refused(f"{n.name} is already {genelog.STATUSES.get(n.status, n.status).lower()}.")
    d = dict(n.draft or {})
    d["night"] = bool(yes)
    _m().GeneLogGene.objects.filter(id=n.id).update(draft=d, updated_at=_now())
    genelog._event(n, "drafted", by="person", detail="Left for the nightly run: it goes into task 94's ideas list."
                   if yes else "Taken back from the nightly run.")
    return {"ok": True, "said": (f"{n.name} is left for the nightly run: the next night adds it to its ideas "
                                 "list, and may build it." if yes else f"{n.name} stays a draft here.")}


def drop(who, gene_id) -> dict:
    from . import genelog

    n = _draft_node(who, gene_id)
    if n.status != "draft":
        raise Refused(f"{n.name} is {genelog.STATUSES.get(n.status, n.status).lower()}: take it out instead.")
    M = _m()
    M.GeneLogEvent.objects.filter(org_id=n.org_id, root_id=n.id).delete()
    M.GeneLogGene.objects.filter(id=n.id, org_id=n.org_id).delete()
    return {"ok": True, "said": f"The draft “{n.name}” is gone."}


def grow_brief(key: str, n) -> str:
    switch = key.replace("-", "_")[:60]
    return "\n".join([
        f"‹Owner› asked Rouh to grow the gene “{n.name}”, which ‹he› drafted in a conversation, into Rouh. Its key "
        f"in the gene log is {key}.",
        "",
        "Its contract, as ‹he› shaped it (‹his› own words, and the brief): " + json.dumps(n.contract, ensure_ascii=False),
        "Why ‹he› wanted it: " + ((n.draft or {}).get("idea") or "the contract says it"),
        "",
        f"1. Build it as a new gene: a gene manifest `rouh/genes/manifests/{key}.json` with \"maturity\": \"lab\" "
        f"and \"switch\": \"{switch}\", registered off, whose contract says truthfully what it does and how to "
        "remove it, and code that does what the contract says. "
        f"Give every file it adds to the gene `{key}` in rouh/genes/owners.json: land.sh refuses a file no "
        "gene owns.",
        "2. Prove it in a test world the way AGENTS.md says, with its switch on there.",
        f"3. Commit with a message whose last line is exactly `Gene: {key}`, and land it with ./land.sh, which "
        "deploys it. Read its last sentence and say it.",
        "Do nothing else: no sign-ups, no payments, nothing sent.",
    ])


async def grow(who, gene_id) -> dict:
    """The draft becomes the brief of a run that builds it in, behind its own switch, off."""
    import asyncio

    from . import genelog, nightly_feature, owner

    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this Rouh grows a gene into it.")
    n = await asyncio.to_thread(_draft_node, who, gene_id)
    if n.status != "draft":
        raise Refused(f"{n.name} is already {genelog.STATUSES.get(n.status, n.status).lower()}.")
    org = str(who.org_id)
    if not (n.contract or {}).get("remove") or (n.contract or {}).get("remove", "").startswith("Not written yet"):
        raise Refused("Its contract does not say how to take it out yet: say that first.")
    key = await asyncio.to_thread(genelog.free_key, org, genelog._slug(n.name)[:40])
    try:
        if nightly_feature.hooks.start is None:
            raise RuntimeError("Rouh's runs are not ready")
        agent = await asyncio.to_thread(nightly_feature.engine, who)
        got = await nightly_feature.hooks.start(
            brief=owner.say(grow_brief(key, n), who), title=f"Grow the gene {n.name}", preset="improve_myself", agent=agent,
            use=nightly_feature.USE, org_id=org, one_fields={"browser_port": nightly_feature._free_port()})
    except Exception as exc:  # noqa: BLE001 - said, not hidden; the draft stays a draft
        log.exception("growing %s could not start", n.id)
        raise Refused(f"{n.name} stays a draft: the run that builds it could not be started "
                      f"({str(exc).strip().rstrip('.') or type(exc).__name__}).") from None
    run = str(got.get("id") or "")

    def mark():
        d = dict(n.draft or {})
        d["run"] = run
        _m().GeneLogGene.objects.filter(id=n.id).update(key=key, status="growing", draft=d, changed_at=_now(),
                                                        updated_at=_now())
        genelog._event(n, "grow_started", by="person", detail=f"Run {run} is building it in, behind its own "
                                                              "switch, off until you turn it on.")
    await asyncio.to_thread(mark)
    return {"ok": True, "run": run, "said": f"Run {run} is growing {n.name} into Rouh, behind its own switch, "
                                            "off until you turn it on."}


def for_night(who) -> str:
    """The drafts left for the nightly run, as its brief carries them: each to be added to task 94's
    ideas list as an entry of its own, and picked like any other idea."""
    rows = _m().GeneLogGene.objects.filter(org_id=str(who.org_id), origin="draft", status="draft")
    left = [n for n in rows if (n.draft or {}).get("night")]
    if not left:
        return ""
    lines = ["Genes ‹owner› drafted in a conversation and left for you (the gene log, Drafts). Add each to "
             "ideas.md as an entry of its own if it is not there yet (Source: the gene log, its key), and pick "
             "it like any other idea. Its contract is ‹his› own words:"]
    for n in left:
        lines.append(f"- {n.key}: “{n.name}”. {json.dumps(n.contract, ensure_ascii=False)}")
    return "\n".join(lines)


def list_text(who) -> str:
    rows = list(_m().GeneLogGene.objects.filter(org_id=str(who.org_id), origin="draft").order_by("-changed_at")[:20])
    if not rows:
        return "No gene has been drafted on the fly."
    return "\n".join(_view(n) for n in rows)
