"""Every case put on its ledger, and each case's one decision made from its ledger
(Petar, 11 October 2026, `MAIL.md`: D1, D7, D8, D10).

Nothing is sent to anybody, and nothing is run: a case that rests stays at rest until the
owner's own Redo or Approve and run (D6).

- **The ledger.** A case read since 11 October 2026 has its asks in its reading: each becomes a
  `MailAsk`, judged from the grants the contact holds now (`mail_ledger.judge`), with the owner's
  choices kept (a grant they gave, once, declined). What went now and was checked is done, with
  what the check saw; an answer whose reply never went is allowed, for their run to answer. A case
  read before then has no asks: it is one ask, the whole message - done when it ended answered,
  declined when the owner blocked it, failed when Rouh stopped, and waiting for them when it
  waited; one whose work was done and checked and whose reply waited for their yes is the work,
  done, and the answer, allowed. Its stage is the ledger's (`mail_ledger.rest_stage`).
- **One decision per case.** Every decision still open is closed as superseded, and a case whose
  ledger has something only the owner moves gets one new decision listing it. They were told of
  all of them already, so no note goes to their phone for these.

On the installation it was written for, it also attached a few named contacts' later messages to
the cases they belonged to, named one case's asks in plain words, and set three named contacts'
time zones. Those cases and contacts live only in that installation's database, so those steps
are not here any more.
"""
import json
import re
import time

from django.db import migrations

SUPERSEDED = ("Rouh keeps one ledger per case since 11 October 2026: this was asked before it, "
              "and the case has one decision now, made from its ledger.")
OLD_READING = ("It was read before messages were split into their asks. Approve and run reads it "
               "again, ask by ask, with the grants they hold now.")

IN_FLIGHT = ("new", "assessing", "working", "waiting_on_job", "following_up", "verifying",
             "replying", "notifying")


def _tree(apps, org_id):
    from rouh import grants

    Grant = apps.get_model("rouh", "Grant")
    rows = list(Grant.objects.filter(org_id=org_id))
    by_id = {r.id: r.key for r in rows}
    if not rows:
        return grants.seed_tree()
    return grants.Tree.of([{"key": r.key, "name": r.name, "description": r.description,
                            "title": r.title, "prompt": r.prompt,
                            "parent": by_id.get(r.parent_id, ""), "holding": r.holding,
                            "tools": r.tools or [], "merged_into": by_id.get(r.merged_into_id, ""),
                            "revision": r.revision, "position": r.position, "id": r.id}
                           for r in rows])


def _contact(apps, case, tree):
    from rouh import trusted as trust

    if not case.contact_id:
        return trust.implicit(case.sender, case.sender_name)
    TrustedContact = apps.get_model("rouh", "TrustedContact")
    TrustedAddress = apps.get_model("rouh", "TrustedAddress")
    ContactGrant = apps.get_model("rouh", "ContactGrant")
    TelegramLink = apps.get_model("rouh", "TelegramLink")
    Grant = apps.get_model("rouh", "Grant")
    row = TrustedContact.objects.filter(id=case.contact_id).first()
    if row is None:
        return None
    keys = {g.id: g.key for g in Grant.objects.filter(org_id=row.org_id)}
    return trust.Trusted(
        id=row.id, name=row.name, contact_id=row.contact_id, trusted=row.trusted,
        levels=trust.with_lower(row.levels or []),
        addresses=list(TrustedAddress.objects.filter(contact_id=row.id)
                       .values_list("address", flat=True)),
        grants=list(row.grants or []),
        inbox_scope=row.inbox_scope or "none", inbox_from=list(row.inbox_from or []),
        beyond=row.beyond or "ask", zone=row.zone or "",
        telegram=[f"telegram:{t.tg_user_id}" for t in
                  TelegramLink.objects.filter(contact_id=row.id, state="linked")
                  if t.tg_user_id],
        extra_grants=[keys[g] for g in ContactGrant.objects.filter(contact_id=row.id)
                      .values_list("grant_id", flat=True) if g in keys])


def _grant_of(raw: dict) -> str:
    named = [str(g) for g in raw.get("approved_grants") or raw.get("grants") or [] if str(g)]
    work = [g for g in named if g != "communicate"]
    if work:
        return work[0]
    return "none" if named else ""


def _choice_of(decided: list, quote: str) -> tuple[str, str]:
    from rouh import mail_ledger as ledger

    for d in decided or []:
        if isinstance(d, dict) and ledger.same(d.get("ask"), quote):
            return ({"grant": "grant", "pass": "once", "wrong": "once", "reject": "decline",
                     "mine": "mine"}.get(str(d.get("choice") or ""), ""),
                    str(d.get("grant") or ""))
    return "", ""


def _asks_of(case) -> list:
    """The ledger a case's own records give, before it is judged."""
    from rouh import mail_ledger as ledger

    report = (case.assessment or {}).get("assess") or {}
    asks_state = case.asks or {}
    verified = bool(case.verified_at) or ((case.assessment or {}).get("verify") or {}) \
        .get("verified") is True
    evidence = " ".join(str(case.verified_said or "").split())[:1200]
    now_ids = {str(a.get("id")) for a in asks_state.get("now") or [] if isinstance(a, dict)}
    out = []
    raw_asks = [a for a in report.get("asks") or [] if isinstance(a, dict) and a.get("ask")]
    if raw_asks:
        for n, raw in enumerate(raw_asks, start=1):
            quote = " ".join(str(raw["ask"]).split())
            grant = _grant_of(raw)
            new = raw.get("new_grant") if isinstance(raw.get("new_grant"), dict) else {}
            choice, given = _choice_of(asks_state.get("decided") or [], quote)
            a = ledger.Ask(ident=str(raw.get("id") or ledger.ident_of(quote)), quote=quote, n=n,
                           label="", do=str(raw.get("do") or ""),
                           grant=grant if grant else "", new_grant=new or {},
                           hard_limit=str(raw.get("hard_limit") or ""), choice=choice,
                           choice_grant=given, source="migrated")
            answer = a.grant == "none" and not a.hard_limit
            went_now = a.ident in now_ids
            if answer and case.replied_at:
                a.status, a.why = ledger.DONE, "Answered."
                a.evidence = [ledger.evidence_line("Answered in the reply",
                                                   ids=[case.reply_message_id])]
            elif went_now and not answer and verified:
                a.status, a.why = ledger.DONE, "Done, and the check saw it."
                a.evidence = [ledger.evidence_line(evidence or "The check saw it done.",
                                                   ids=re.findall(r"\btask \d+\b", evidence))]
            out.append(a)
        return out
    if case.route in ("junk", "nothing") or case.stage in ("junk_spam", "junk_not_moved"):
        return []
    quote = str(case.subject or "").strip() or " ".join(str((case.email or {}).get("body")
                                                             or "").split())[:200]
    label = " ".join(str(report.get("summary") or "").split())[:200]
    follow = case.follow_up or {}
    if case.stage == "done":
        return [ledger.whole(quote, label=label, status=ledger.DONE,
                             why="It was carried to its end before the ledger was kept.",
                             evidence=[ledger.evidence_line(case.outcome or "Done.",
                                                            ids=[case.reply_message_id])])]
    if case.stage == "blocked":
        if follow.get("blocked_by"):
            one = ledger.whole(quote, label=label, status=ledger.DECLINED, why="You declined it.")
            one.choice = "decline"
            return [one]
        return [ledger.whole(quote, label=label, status=ledger.FAILED,
                             why=(case.blocker or "Rouh could not go on.")[:600])]
    if verified and not case.replied_at:
        work = ledger.whole(quote, label=label or "the work you asked for",
                            status=ledger.DONE, why="Done, and the check saw it.",
                            evidence=[ledger.evidence_line(evidence or "The check saw it done.")])
        work.ident, work.source = "work", "migrated"
        answer = ledger.Ask(ident="answer", quote="(the answer to it)", n=2,
                            label="the answer, with what was made", grant="none",
                            status=ledger.ALLOWED, why="Its answer never went: your run sends it.",
                            source="migrated")
        return [work, answer]
    return [ledger.whole(quote, label=label, status=ledger.WAITING, why=OLD_READING)]


def forwards(apps, schema_editor):
    from rouh import mail_ledger as ledger
    from rouh import trusted as trust

    MailCase = apps.get_model("rouh", "MailCase")
    MailAsk = apps.get_model("rouh", "MailAsk")
    MailApproval = apps.get_model("rouh", "MailApproval")
    MailCaseEvent = apps.get_model("rouh", "MailCaseEvent")
    now = time.time()

    def event(case, stage, said):
        MailCaseEvent.objects.create(user_id=case.user_id, org_id=case.org_id, case_id=case.id,
                                     at=time.time(), stage=stage, said=said[:4000])

    # Every decision still open is superseded: each case has one, made from its ledger, below.
    MailApproval.objects.filter(status="pending").update(status="superseded",
                                                         why_invalid=SUPERSEDED)

    trees = {}
    for case in MailCase.objects.exclude(stage="merged").order_by("id"):
        if MailAsk.objects.filter(case_id=case.id).exists():
            continue
        asks = _asks_of(case)
        if not asks:
            continue
        tree = trees.setdefault(case.org_id, _tree(apps, case.org_id))
        contact = _contact(apps, case, tree)
        judged = ledger.judge(asks, contact, tree, identity_ok=case.identity_ok,
                              identity_said=case.identity_said)
        # What the records said stands: an old message's whole ask is as its case ended.
        judged = [j if a.source != "whole" else a for a, j in zip(asks, judged)]
        for a in judged:
            # Only the columns the ledger had at this migration: later ones are added after it.
            columns = {f.name for f in MailAsk._meta.get_fields()}
            fields = {k: v for k, v in a.as_dict().items() if k != "ident" and k in columns}
            MailAsk.objects.create(user_id=case.user_id, org_id=case.org_id, case_id=case.id,
                                   ident=a.ident, created_at=now, updated_at=now, **fields)
        if case.stage in IN_FLIGHT or case.stage in ("awaiting_approval", "done", "blocked"):
            stage = ledger.rest_stage(judged)
            line = ledger.why_line(judged, tree=tree,
                                   contact_name=contact.name if contact is not None else "")
            MailCase.objects.filter(id=case.id).update(stage=stage, outcome=line[:4000],
                                                       turn_started_at=0, updated_at=now)
            if stage != case.stage:
                event(case, stage, "Put on its ledger (11 October 2026): " + line)
        needs = ledger.needs_owner(judged)
        if not needs:
            continue
        listed = contact is not None and not contact.implicit and contact.trusted
        items = []
        for a in needs:
            if a.status == ledger.WAITING:
                options = (["grant"] if listed and not a.hard_limit and case.identity_ok
                           else []) + ["once", "decline", "mine"]
            elif a.status == ledger.FAILED:
                options = ["once", "decline", "mine"]
            else:
                options = ["decline", "mine"]
            items.append({"id": a.ident, "ask": a.quote, "label": a.label, "n": a.n,
                          "status": a.status, "why": a.why,
                          "need": (ledger.need_named(a, tree, "") if a.status == ledger.WAITING
                                   else "Not run yet" if a.status == ledger.ALLOWED
                                   else ledger.WORDS[a.status]),
                          "grant": a.grant if a.grant != "none" else "",
                          "grant_name": tree.name(a.grant) if a.grant and a.grant != "none"
                          else "", "hard_limit": a.hard_limit, "new_grant": a.new_grant,
                          "options": options,
                          "who": contact.name if contact is not None else case.sender_name})
        print_ = trust.fingerprint(case.key, 0, ledger.decision_signature(judged),
                                   [i["id"] for i in items])
        MailApproval.objects.create(
            user_id=case.user_id, org_id=case.org_id, case_id=case.id, fingerprint=print_,
            proposed_action=json.dumps([i["label"] or i["ask"] for i in items])[:4000],
            proposed_reply="", asked_at=now, attempt_no=case.attempt_no, kind="asks",
            asks=items, answers={}, notified_at=now, reminded_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0120_mail_ledger"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
