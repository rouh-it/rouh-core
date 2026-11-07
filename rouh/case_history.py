"""How mail cases were judged until 11 October 2026: kept only so their pages read as they ran.

Petar, 11 October 2026 (`MAIL.md`): a case is judged from its ledger and the grants the contact
holds, never by words, topics or model checks. Until then a route judged each email by risk word
lists, allowed topics, a reply check, a status check and a word review, and the case's trace kept
each rule's verdict in those terms. Those cases are still on their pages, so `rouh/case_trace.py`
reads their kept rows with these tables, word for word as they stood. Nothing here judges
anything: no code that decides what a case may do imports this module.
"""
from __future__ import annotations

RISKS = {'money': "It involves ‹owner›'s money: paying, buying, booking, transferring, invoicing or "
          'refunding, or ‹his› own prices, figures or bank details. Looking up public prices or '
          'costing a plan, with nothing paid, bought or booked, is not money.',
 'accounts': "It asks for a password, a code, a login or an account of ‹owner›'s, or a change to "
             'who may reach one.',
 'sharing': 'It asks for access to something, or for something to be shared with somebody.',
 'private_data': 'It asks for or would give out private or sensitive personal data.',
 'legal': 'It is a legal matter: a contract, a lawyer, a court, an obligation in law.',
 'health': 'It is a health matter: a doctor, a diagnosis, a hospital, treatment.',
 'commitment': 'It would commit ‹owner› to something: a meeting, a deadline, a promise or an '
               'agreement.',
 'irreversible': 'It asks for something that cannot be undone: deleting, cancelling, sending '
                 'on or publishing.',
 'identity_doubt': 'Rouh is not sure the message is really from this contact.',
 'unclear_intent': 'Rouh is not sure what they want.'}

RISK_ALIASES = {'legal_health': ('legal', 'health')}

GRANT_COVERS = {'sharing': ('tasks', 'use')}

REPLY_RISKS = {'money': "The reply states ‹owner›'s prices, amounts, figures or bank details.",
 'private_data': "The reply contains somebody's personal data.",
 'legal': "The reply takes a legal position or agrees terms on ‹owner›'s behalf.",
 'commitment': "The reply promises, in ‹owner›'s name, something still to come: a date, a "
               'meeting, a deadline, an agreement or an obligation. Saying what already '
               'happened or where something stands now - that ‹owner› approved it, that it waits '
               'for ‹him›, that it was held back - is not a commitment, and neither is Rouh '
               'saying it sends, emails or shares the answer or its result to them, or when.',
 'irreversible': 'The reply says Rouh has done, or will do, something that cannot be undone. '
                 'Describing contract terms, policies or what happens to data is not that, and '
                 'neither is Rouh sending, emailing or sharing the answer or its result to the '
                 'person it is replying to: that is the reply itself.',
 'accounts': 'The reply contains a login, a password or a code.'}

REPLY_COVERS = {'money': {'topics': ('money',), 'levels': ()},
 'private_data': {'topics': ('private_data',), 'levels': ()},
 'legal': {'topics': ('legal',), 'levels': ()},
 'commitment': {'topics': (), 'levels': ()},
 'irreversible': {'topics': (), 'levels': ()},
 'accounts': {'topics': (), 'levels': ()}}

TOPICS = {'legal': ('Legal', 'Contracts, lawyers, courts, obligations in law.'),
 'health': ('Health', 'Doctors, diagnoses, hospitals, treatment.'),
 'money': ('Money',
           'Payments, invoices, prices, refunds, bank details - talked about. Nothing is paid '
           'or transferred on it.'),
 'private_data': ('Private data',
                  'Personal details such as a phone number, an address, a date of birth or an '
                  'ID number.')}

NET = {'iban': 'a bank account number (IBAN)',
 'card': 'a payment card number',
 'password': 'a password',
 'code': 'a one-time or verification code',
 'phone': "somebody's phone number"}

NEEDS = {'inbox': ('Your inbox, read',
           "Reading ‹owner›'s own inbox: searching it, or reading a message or a file in it. "
           'Covered by Your inbox - how far.'),
 'inbox_write': ('Your inbox, changed',
                 "Labelling, archiving or drafting in ‹owner›'s own inbox. Covered only by Full "
                 'read and write.'),
 'as_owner': ('Acting as you',
              'Sending as ‹owner›, deleting ‹his› mail, or forwarding ‹his› mail to anybody outside. '
              'Never covered: it asks ‹him› every time.')}

COMMITMENTS = {'engage': 'engaging or instructing a provider',
 'file': 'filing or registering something',
 'sign': 'signing something',
 'choose': 'choosing a provider or an offer',
 'terms': 'agreeing terms',
 'time': "committing ‹owner›'s time",
 'money': 'paying or spending money',
 'outside': 'sending something to somebody other than {name}',
 'publish': 'publishing or sharing it beyond {name}',
 'irreversible': 'something that cannot be undone'}

PREPARATORY = ('research, analysis, comparisons, drafts, summaries, documents and pages in the workspace, '
 'and the reply to {name}')

STATUS_OPTION = ('May be told the approval status of their own requests',
 'When they ask whether something of theirs is waiting for you, stopped, approved or done, '
 'Rouh answers at once from its own records, in plain words. Only that: never what you are '
 "asked to approve, your reasons, or anybody else's requests. A reply that says more still "
 'waits for you as usual.')

WORD_CHECKED = ('money', 'accounts', 'sharing', 'private_data', 'legal', 'health', 'commitment', 'irreversible')

#: The catch-all the reading named until 11 October 2026.
OLD_CATCH_ALL = "outside_grant"
#: What acting as the owner was called on cases kept before 20 October 2026, as a need, a route's
#: rule and a hard limit: "as_owner" now.
AS_OWNER, AS_OWNER_BEFORE = "as_owner", "as_petar"
#: Need words kept under an older name.
NEED_ALIASES = {"other": OLD_CATCH_ALL, AS_OWNER_BEFORE: AS_OWNER}

#: What the history of an old case said at these steps (`rouh/mail_cases.py` until then).
STOP_SAID = "Rouh stopped here, and holds it for you:"
PREPARE_SAID = "Made first, then asked:"
REREAD_SAID = "Re-read after permissions changed"
REPREPARE_SAID = "Read again to make it first:"
STATUS_SAID = "They asked only where their own requests stand, and you let them be told:"
#: How long the reply check and the word review were given.
REPLY_CHECK_SECONDS = 180
REVIEW_PURPOSE = "word_review"
REVIEW_SECONDS = 120


def commitments_said(found: list[dict]) -> str:
    """Commitments as one plain clause, as an old route kept them."""
    parts = [f"{c['said']} (\"{c['words']}\")" for c in found]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def need_name(key: str) -> str:
    """A need of an old reading as the page says it."""
    from . import trusted as trust

    key = NEED_ALIASES.get(key, key)
    if key == OLD_CATCH_ALL:
        return "Old catch-all"
    return (trust.LEVELS.get(key) or NEEDS.get(key) or (key,))[0]


def stopped(case) -> bool:
    """Whether an old case waited because Rouh stopped where it could not go on."""
    return case.stage == "awaiting_approval" and (case.follow_up or {}).get("asked") == "stop"
