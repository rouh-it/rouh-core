"""What a contact deciding for the owner would commit them to, by the words of their decision.

Petar, 9 October 2026 (`DELEGATION.md`): a contact he gives authority over a goal, a quest or a
task decides it by email, checked at every action; money, deleting, publishing, sending and
committing him stay his. `rouh/delegation.py` reads the words of what they decided with these
(`commitments`, `moves_money`) and holds for the owner what would commit them.

Until 11 October 2026 these lived in `rouh/trusted.py`, beside the word lists that also decided
which emails waited for the owner. Those lists are gone (`MAIL.md`, D2): a mail case is judged from
grants, never from words. What stays here is the delegate's own guard, which is a separate thing:
it checks words that a contact wrote as a decision on the owner's behalf.
"""
from __future__ import annotations

import functools
import re

from . import owner

#: Words that make the word after them a prohibition: "make no promise", "do not
#: delete", "without paying".
_NOT = re.compile(r"(?<![\w'])(?:no|not|never|without|nor|don't|dont|do\s+not|doesn't|"
                  r"does\s+not|avoid|avoiding|neither)(?![\w'])", re.IGNORECASE)
#: Words that turn a prohibition back into the thing: "do not forget to pay",
#: "not only sign", "never stop paying". Any of these in the window and the
#: word counts as it always did.
_UNDO = re.compile(r"(?<![\w'])(?:forget|forgetting|fail|failing|neglect|hesitate|wait|"
                   r"delay|stop|cease|only|just|before|after|until|unless|later|but)(?![\w'])",
                   re.IGNORECASE)


def _forbidden(text: str, start: int) -> bool:
    """Whether the risky word at `start` is forbidden rather than asked for.

    Only the three words right before it, inside its own clause (no comma,
    stop or line between), and only a plain prohibition: "Make no attachment
    promise" is one, "Do not forget to sign the contract" and "Do not cancel
    it, delete it" are not. Narrow on purpose: a miss here is a step handed
    to a server job without the owner.
    """
    before = re.split(r"[,.;:!?\n()\[\]\"“”]", text[:start])[-1]
    window = " ".join(before.split()[-3:])
    return bool(_NOT.search(window)) and not _UNDO.search(window)


def negated_list(text: str, start: int) -> bool:
    """Whether the word at `start` is an item of a list a sentence forbids: "Do not change
    task grants, share another page, make the page public or contact anyone", "Make no
    bookings, purchases, operator enquiries, reservations or commitments".

    The sentence has to begin with the prohibition and be a list - "or" or
    "nor" in it - with no turn in it ("but", "instead", "then"), so "Do not
    cancel it, delete it" still asks for the deleting (`_forbidden`).
    """
    head = re.split(r"[.;:!?\n]", text[:start])[-1]
    tail = re.split(r"[.;:!?\n]", text[start:])[0]
    whole = head + tail
    return bool(re.match(r"\s*(?:\w+\s+)?(?:do\s+not|don'?t|never|avoid|without|no)\b", head,
                         re.IGNORECASE)) \
        and bool(re.search(r"\b(?:or|nor)\b", whole, re.IGNORECASE)) \
        and not re.search(r"\b(?:but|instead|then|unless|except|rather|only)\b", whole,
                          re.IGNORECASE)


#: Doing something that moves the owner's money, in what a case would do: paying,
#: buying, booking, reserving, transferring, invoicing, refunding, ordering or
#: subscribing, or his bank or card details (`moves_money`).
_MOVES_MONEY = re.compile(
    r"(?<![\w])(?:pay|pays|paying|paid|payment\w*|purchas\w*|buy|buys|buying|bought|"
    r"book|books|booked|booking\w*|reserv\w*|(?:bank|wire|money)\s+transfer\w*|"
    r"transfer\w*\s+(?:the\s+)?(?:money|funds?|payment|deposit)|invoic\w*|refund\w*|"
    r"bank\s+(?:details|account\w*)|iban|swift|card\s+(?:number|details)|deposit\w*|"
    r"checkout|order\s+(?:it|them|the|a|an)|subscri\w*|sign\s+up|плат\w*|"
    r"резерв\w*|купи\w*)(?![\w])", re.IGNORECASE)


def moves_money(text: str) -> bool:
    """Whether doing what `text` says would move money: one of `_MOVES_MONEY`'s words that
    the text does not forbid ("Make no bookings, purchases or reservations")."""
    text = str(text or "")
    return any(not _forbidden(text, m.start()) and not negated_list(text, m.start())
               for m in _MOVES_MONEY.finditer(text))


# --- preparing, as against committing ------------------------------------------------------
#
# Petar, 8 October 2026, after a trusted contact's email with trademark research
# and two law firms' offers, asking Rouh for an independent comparison, was
# held as "Legal ... does not count here: Something has to be done or
# decided, not only answered": preparing work for somebody he trusts is not
# committing him to anything. So what a request would have done is two kinds.
# Preparatory work is research, analysis, comparisons, drafts, summaries,
# documents and pages in the workspace, and the reply to the person who asked;
# it is theirs in any area the owner allowed them (`topic_grant_blocker`).
# A commitment (`COMMITMENTS`) still waits for his yes, and the hold says
# which one it is (`commitments`).

#: What commits the owner, as against preparing it, each as the hold says it.
COMMITMENTS: dict[str, str] = {
    "engage": "engaging or instructing a provider",
    "file": "filing or registering something",
    "sign": "signing something",
    "choose": "choosing a provider or an offer",
    "terms": "agreeing terms",
    "time": "committing ‹owner›'s time",
    "money": "paying or spending money",
    "outside": "sending something to somebody other than {name}",
    "publish": "publishing or sharing it beyond {name}",
    "irreversible": "something that cannot be undone",
}

#: What preparatory work is, as the page and the reading are told it.
PREPARATORY = ("research, analysis, comparisons, drafts, summaries, documents and pages in "
               "the workspace, and the reply to {name}")

#: Somebody a request would reach who is not the person it answers.
_OTHERS = (r"(?:(?:law\s+)?firms?|providers?|counsel|lawyers?|attorneys?|solicitors?|notar(?:y|ies)|"
           r"agents?|agenc(?:y|ies)|representatives?|vendors?|suppliers?|contractors?|"
           r"consultants?|accountants?|registr(?:ar|y)|operators?|hotels?|airlines?|banks?|"
           r"compan(?:y|ies)|landlords?|clients?|customers?|investors?|partners?|press|"
           r"journalists?|the\s+team|the\s+other\s+side|third[-\s]part(?:y|ies)|"
           r"anyone|anybody|everyone|everybody|someone|somebody|others|the\s+public|"
           r"uspto|euipo|wipo|ukipo|court)")
#: Words that may stand between a verb and the person it reaches: "contact the English
#: law firm", "email both providers". Never "to", "for", "in" or "about": "Instruct the
#: worker to compare provider offers" reaches nobody.
_GAP = r"(?:(?!(?:to|for|in|into|on|about|under|as|with|from|of)\b)[\w'-]+\s+){0,3}?"
#: What may follow a verb of buying or booking for it to be the act and not a noun:
#: "book the riad", "order two", never "the booking page" or "reserve provider
#: comparison until both arrive".
_OBJECT = r"\s+(?:a|an|the|it|them|this|that|these|those|his|her|their|our|one|two|both|\d+)\b"

#: The words of each commitment, as an instruction says them: the plain verb, so
#: "distinguishing preparation from filing, hiring a provider or spending" and "He
#: is the one who sends it to the bank" describe and commit nobody.
#:
#: The owner is never a name written here: `_OWNER` is their name and full name and "the
#: owner", and `_COMPANY` their organisation's name and "the company", both filled in at
#: call time for the owner the text is for (`_commits`).
_OWNER = "@OWNER@"
_COMPANY = "@COMPANY@"
_PATTERNS: dict[str, str] = {
    "engage": "|".join([
        r"\b(?:engage|appoint|hire|retain|instruct|mandate|commission)\s+" + _GAP + _OTHERS
        + r"\b",
        r"\b(?:engage|appoint|hire|instruct)\s+(?:them|either(?:\s+one)?|one\s+of\s+them|"
        r"both)\b",
        r"\baccept\s+(?:the|their|an?|this|that|either|one|both)\s+(?:[\w'-]+\s+){0,2}?"
        r"(?:offers?|quotes?|quotations?|proposals?)\b",
        r"\bgo\s+ahead\s+with\s+(?:the|their|either|one|both)\s+(?:[\w'-]+\s+){0,2}?"
        r"(?:offers?|quotes?|providers?|firms?|filings?)\b",
    ]),
    "file": "|".join([
        r"\b(?:file|lodge|submit)\s+(?:(?:the|an?|our|their|his|her|its|both|all)\s+)?"
        r"(?:(?!(?:under|in|into|to|with|as|at|on|for)\b)[\w'-]+\s+){0,2}"
        r"(?:applications?|trade\s?marks?|marks?|patents?|claims?|lawsuits?|suits?|"
        r"complaints?|appeals?|oppositions?|registrations?|petitions?|tax\s+returns?)\b",
        r"\b(?:file|lodge|apply)\s+(?:[\w'-]+\s+){0,2}?(?:with|at|before)\s+(?:the\s+)?"
        r"(?:uspto|euipo|wipo|ukipo|bpo|court|registry|patent\s+office|"
        r"trade\s?mark\s+office)\b",
        r"\bapply\s+for\s+(?:an?\s+|the\s+)?(?:[\w'-]+\s+){0,2}?(?:trade\s?marks?|marks?|"
        r"patents?|registrations?|licen[cs]es?)\b",
        r"\bregister\s+(?:the|an?|our|his|her|their)\s+(?:[\w'-]+\s+){0,2}?(?:trade\s?marks?|"
        r"marks?|company|companies|domains?|business|patents?)\b",
    ]),
    "choose": r"\b(?:choose|select|pick|go\s+with|decide\s+on|settle\s+on|award)\s+"
              r"(?:the|either|one|their|a|an|this|that)\s+(?:[\w'-]+\s+){0,2}?"
              r"(?:firms?|providers?|offers?|quotes?|quotations?|bids?|vendors?|suppliers?|"
              r"agenc(?:y|ies)|lawyers?|counsel|attorneys?|contractors?|consultants?)\b",
    "time": "|".join([
        r"\b(?:schedule|arrange|set\s+up|book|confirm|accept|fix)\s+(?:a|an|the|this|that|"
        r"their|his|her|" + _OWNER + r"'?s)\s+(?:[\w'-]+\s+){0,2}?(?:meetings?|calls?|slots?|"
        r"appointments?|"
        r"interviews?|demos?|visits?|sessions?|invit(?:e|ation)s?)\b",
        r"\b(?:block|reserve|put|add)\s+(?:[\w'-]+\s+){0,3}?(?:in|into|on|to)\s+"
        r"(?:" + _OWNER + r"'?s|his|her|their|the)\s+calendar\b",
        r"\bcommit\s+(?:" + _OWNER + r"|him|her|them)\s+to\s+(?:a\s+|the\s+)?"
        r"(?:meeting|call|date|day)\b",
    ]),
    "sign": r"\b(?:sign|countersign|e-?sign)\s+(?:the|this|that|it|an?|our|their|his|her|any|"
            r"both)\b|\bsign\s+off\s+on\b",
    "terms": "|".join([
        r"\bagree\s+(?:to|on)\s+(?:the\s+|their\s+|its\s+|an?\s+)?(?:[\w'-]+\s+)?"
        r"(?:terms|price|fees?|offer|quote|contract|agreement|engagement|deal|proposal|"
        r"conditions|deadline|date)\b",
        r"\baccept\s+(?:the|their|these|those|any)\s+(?:[\w'-]+\s+){0,2}?"
        r"(?:terms|conditions|contract|agreement|engagement)\b",
        r"\bconfirm\s+(?:the|our|his|her|their)\s+(?:[\w'-]+\s+)?(?:engagement|instructions?|"
        r"order|booking|terms|deal|agreement)\b",
        r"\bcommit\s+(?:" + _OWNER + r"|him|her|them|us|" + _COMPANY + r")\s+to\b",
        r"\bnegotiate\s+(?:the\s+|their\s+)?(?:terms|price|fees?|contract)\b",
    ]),
    "money": "|".join([
        r"\bpay\b(?!\s+(?:attention|heed))", r"\b(?:buy|purchase)\b",
        r"\b(?:book|reserve|order)" + _OBJECT + r"(?:\s+[\w'-]+)?",
        r"\bmake\s+(?:a|the|any)\s+(?:[\w'-]+\s+)?payments?\b",
        r"\b(?:wire|transfer|send)\s+(?:the\s+)?(?:money|funds?|payment|deposit|amount|sum|"
        r"€\s?\d+|\$\s?\d+|\d+\s?(?:eur|euros?|usd|bgn|leva))\b",
        r"\b(?:subscribe|check\s?out|sign\s+up|top\s+up)\b",
        r"\b(?:invoice|refund|deposit)" + _OBJECT,
        r"\bspend\s+(?:€|\$|\d|money|the\s+budget)",
        r"\b(?:плати|платете|купи|купете|резервирай\w*)\b",
    ]),
    "publish": "|".join([
        r"\bpublish\b(?!\s+(?:date|sources?))",
        r"\bmake\s+(?:it|this|them|the\s+[\w'-]+)\s+public\b",
        r"\bpost\s+(?:it|this|them|the\s+[\w'-]+)\s+(?:on|to)\b",
        r"\bpublic\s+link\b",
    ]),
    "irreversible": r"\b(?:delete|cancel|terminate|wipe|destroy|revoke)\b"
                    r"|\bwithdraw\s+(?:the|our|his|her|their)\s+(?:[\w'-]+\s+){0,2}?"
                    r"(?:application|offer|registration|mark|trade\s?mark)\b",
}


def _alternation(words) -> str:
    """Escaped words as one group, longest first, any run of spaces in them matching any."""
    said = sorted({w.strip().lower() for w in words if w and w.strip()}, key=len, reverse=True)
    return "(?:" + "|".join(r"\s+".join(re.escape(p) for p in w.split()) for w in said) + ")"


@functools.lru_cache(maxsize=32)
def _compiled(names: str, company: str) -> dict[str, re.Pattern]:
    return {key: re.compile(pattern.replace(_OWNER, names).replace(_COMPANY, company),
                            re.IGNORECASE) for key, pattern in _PATTERNS.items()}


def _the_owner(who=None):
    try:
        return owner.resolve(who)
    except Exception:                               # noqa: BLE001 - the generic words still hold
        return None


def _commits(found) -> dict[str, re.Pattern]:
    """The commitments' patterns for this owner: their names, and their company's."""
    names = [found.name, found.full_name] if found is not None else []
    company = [found.company] if found is not None else []
    return _compiled(_alternation(names + ["the owner"]),
                     _alternation(company + ["the company"]))


#: Reaching somebody directly: "contact the firm", "email both providers".
_REACH = re.compile(
    r"\b(?:contact|e-?mail|message|call|phone|ring|write\s+to|reach\s+out\s+to|"
    r"get\s+in\s+touch\s+with|cc|copy\s+in|invite|notify|inform|tell|ask|introduce|forward)"
    r"\s+(?:the\s+|an?\s+|both\s+|either\s+|each\s+|any\s+|all\s+|their\s+|our\s+)?" + _GAP
    + _OTHERS + r"\b", re.IGNORECASE)
#: Sending something on to somebody: "send the report to the firm", "share it with Sam".
_SEND = re.compile(
    r"\b(?:send|deliver|share|forward|pass|give|hand|show|present|post|e-?mail|return|"
    r"introduce|copy)\b[^.;:!?\n]{0,160}?\b(?:to|with)\s+([^.;:!?\n,()]{1,80})",
    re.IGNORECASE)
#: Where the recipient of a send stops: "to Jordan in this thread once verified".
_RECIPIENT_END = re.compile(r"\b(?:for|in|by|once|when|after|before|so|as|within|via|on|from|"
                            r"if|unless|until|because|without|rather|then|who|which|that)\b",
                            re.IGNORECASE)
#: Somebody else doing it: "for Jordan to present to the owner and Sam", "so the firm can file
#: the application", "the provider will file": theirs to do, not Rouh's.
_THEIRS = re.compile(r"(?:\bfor\s+[\w'-]+(?:\s+[\w'-]+)?\s+to"
                     r"|\b(?:help|helps|helping|let|lets|letting)(?:\s+[\w'-]+){1,2}?(?:\s+to)?"
                     r"|(?<!\bi)(?<!\bwe)(?<!\brouh)\s+(?:can|could|will|would|may|might|"
                     r"should|must|shall))\s+$", re.IGNORECASE)
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: Names that are never somebody outside: Rouh, and words a sentence starts with. The
#: owner's own names are added at call time (`_outside`).
_OWN_NAMES = {"owner", "rouh", "i", "we", "you", "me", "us", "her", "him",
              "them", "the", "a", "an", "and", "or", "both", "each", "it", "this", "that"}
#: A prohibition anywhere in a sentence, and a list of what it forbids after it: "Include
#: the next steps, but do not file, buy, sign up, contact providers or commit anybody".
_NO = re.compile(r"\b(?:do\s+not|don'?t|never|must\s+not|mustn'?t|should\s+not|shouldn'?t|"
                 r"no|nor|without|avoid|neither|not)\b", re.IGNORECASE)
_TURN = re.compile(r"\b(?:but|instead|then|unless|except|rather|only|so|until|once|after|"
                   r"before|when|if)\b", re.IGNORECASE)


def _forbidden_list(text: str, start: int) -> bool:
    """Whether the word at `start` is an item of a list a prohibition earlier in its own
    sentence forbids, with nothing between them that turns it back into a thing to do."""
    head = re.split(r"[.;:!?\n]", text[:start])[-1]
    tail = re.split(r"[.;:!?\n]", text[start:])[0]
    nos = list(_NO.finditer(head))
    if not nos:
        return False
    between = head[nos[-1].end():]
    items = [i for i in re.split(r",|\bor\b|\bnor\b|\band\b", between)]
    if _TURN.search(between) or any(len(i.split()) > 5 for i in items):
        return False
    return bool(re.search(r"\b(?:or|nor)\b", between + tail, re.IGNORECASE)) or \
        len(between.split()) <= 3


def _allowed(text: str, start: int) -> bool:
    """Whether the word at `start` is asked for, not a guardrail the text sets, and Rouh's
    to do, not somebody else's."""
    return not _forbidden(text, start) and not negated_list(text, start) and \
        not _forbidden_list(text, start) and not _THEIRS.search(text[:start])


def _outside(text: str, contact, found=None) -> list[str]:
    """Where `text` would send or reach somebody other than the contact it answers."""
    mine = {a.lower() for a in getattr(contact, "addresses", None) or ()}
    own_names = _OWN_NAMES | {w.lower() for w in str(getattr(contact, "name", "") or "")
                              .split()}
    if found is not None:
        own_names |= {w.lower() for n in (found.name, found.full_name) for w in (n or "").split()}
    found: list[str] = [m.group(0) for m in _REACH.finditer(text) if _allowed(text, m.start())]
    for m in _SEND.finditer(text):
        if not _allowed(text, m.start()):
            continue
        whom = _RECIPIENT_END.split(m.group(1), 1)[0]
        strangers = {a.lower().rstrip(".") for a in _ADDRESS.findall(whom)} - mine
        names = [w for w in re.findall(r"\b[A-ZА-Я][\w'-]+", _ADDRESS.sub("", whom))
                 if w.lower().removesuffix("'s") not in own_names]
        if strangers or names or re.search(r"\b" + _OTHERS + r"\b", whom, re.IGNORECASE):
            found.append(" ".join(m.group(0).split()))
    for sentence in re.split(r"(?<=[.;!?\n])\s+", text):
        verb = re.search(r"\b(?:send|e-?mail|forward|share|cc|copy|contact|write)\b", sentence,
                         re.IGNORECASE)
        if not verb or not _allowed(sentence, verb.start()):
            continue
        for a in _ADDRESS.finditer(sentence):
            address = a.group(0).lower().rstrip(".")
            if address not in mine and not re.search(r"\bfrom\s+$", sentence[:a.start()],
                                                     re.IGNORECASE):
                found.append(address)
    return list(dict.fromkeys(found))


def commitments(text: str, contact=None, who=None) -> list[dict]:
    """What doing `text` - the reading's proposed action - would commit the owner to, each
    `{"kind", "said", "words"}`, leaving out what the text forbids and what it says
    somebody else does. `who` is the owner it is for (`owner.resolve`).

    Everything else a request does is preparatory (`PREPARATORY`). "Do not
    file, appoint counsel, contact providers, pay, book or change any
    accounts" commits nobody; "Instruct the law firm to file" does.
    """
    text = " ".join(str(text or "").replace("’", "'").split())
    name = str(getattr(contact, "name", "") or "") or "them"
    the_owner = _the_owner(who)
    patterns = _commits(the_owner)
    out: list[dict] = []

    quoted: list[tuple[int, int]] = []

    def add(kind: str, words: list[str]) -> None:
        if words:
            out.append({"kind": kind, "said": COMMITMENTS[kind].format(name=name),
                        "words": words[0]})

    def found(kind: str) -> list[str]:
        """Its words, the ones another kind already quoted last: "Book an appointment ...
        and pay the deposit" is the owner's time for the booking, and money for "pay"."""
        hits = [m for m in patterns[kind].finditer(text) if _allowed(text, m.start())]
        fresh = [m for m in hits if not any(a <= m.start() < b for a, b in quoted)]
        if fresh or hits:
            quoted.append((fresh or hits)[0].span())
        return [m.group(0) for m in fresh + [m for m in hits if m not in fresh]]

    for kind in ("engage", "choose", "file", "sign", "terms", "time", "money"):
        add(kind, found(kind))
    add("outside", _outside(text, contact, the_owner))
    for kind in ("publish", "irreversible"):
        add(kind, found(kind))
    return out


def commitments_said(found: list[dict]) -> str:
    """Commitments as one plain clause: engaging or instructing a provider ("instruct the
    law firm") and paying or spending money ("pay")."""
    parts = [f"{c['said']} (\"{c['words']}\")" for c in found]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
