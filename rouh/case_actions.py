"""What a case's reading may make of an ask: one capability Rouh's code declares, the resources it
names and the values it asks, and a hard limit only when the sender's own words ask for that effect.

Petar, 21 October 2026, on a contact's case: her "(ii) I need to have the right
to make changes in the tasks and be able to talk to you in the interface" was read three times and
labelled three ways - permission to edit task 128, covered but failed, and a hard limit on his
accounts and passwords - while what she asked for was the edit permission she held through her
Decide on quest 128, which lets her change those tasks and use Ask AI on their pages. "Talk to you
in the workspace" is Ask AI on a task's page: nothing in it reaches his accounts. So (MAIL.md D34,
and since the same evening D35 and CAPABILITIES.md):

- **An ask is one capability** (`rouh/capabilities.py`), named by its id or its action word: read a
  task, change one, Ask AI on one, be let in to one, decide for one, share a page, a new shared task,
  research, other work, a Clockwork item, a note kept, the inbox, the calendar, or an answer alone -
  whatever the deployed genes declare, and nothing listed here. The reading names it with the
  resources it acts on (`resource`: task numbers, calendar ids) and the values it asks within its
  limits (`values`); `apply` fills in what that needs - a level on the owner's tasks, a grant on the
  contact's page, a hard limit - so the same capability always needs the same thing. The reading
  never writes a grant (`new_grant` is refused): Rouh's code proposes one from these fields.
  `unsupported` is an ask no capability does, which only the owner sees to.
- **A hard limit only from their words** (`asks_for`, `effect_ok`). The reading quotes, in
  `effect_words`, the words of theirs that ask for the effect - "pay the deposit", "book the
  flight", "my password" - and they must be in the message and say that effect. General words never
  are one: "talk to you", "the workspace", "the interface", "access", "the right to make changes".
  The same rule holds for what a run says it needs (`CaseDesk._block`) and when a case is judged
  again (`mail_ledger.settle`): a hard limit nobody's words asked for is never put to the owner.

Pure and standard library only, so `rouh/mail_replay.py` runs the very same code.
"""
from __future__ import annotations

import re

from . import capabilities

#: What an ask is when its words ask for an effect only the owner decides, and when nothing Rouh
#: has does it. Neither is a capability.
HARD_LIMIT, UNSUPPORTED = "hard_limit", "unsupported"
#: What the reading named before capabilities, read as the ones above.
OLD_WORDS = {"other": "", "none_fits": UNSUPPORTED}

#: What each level on one of the owner's tasks lets a person do (`rouh/task_access.py`), as the
#: reading and the start are told it.
LEVELS_SAID = ("read: open it, its notes, pages and steps; edit: change it too, and use Ask AI and "
               "talk to Rouh on its pages; decide: decide for ‹owner› there too. Each includes the "
               "ones before it, and a level on a quest or a task reaches the goals and steps under it.")

#: The words that ask for each hard limit's effect, English and Bulgarian, as stems: only these
#: make an ask one. A limit with none here (acting while it is unsure who wrote) is the code's
#: own and never read from words.
LIMIT_WORDS: dict[str, str] = {
    "money": (r"\bpa(?:y|id|ying|yment)s?\b|\bbuy|\bbought\b|\bpurchas|\bcheck ?out\b|"
              r"\border(?:ed|ing)?\s+(?:it|them|the|a|an|one|some|me|us|for)\b|\bbook(?:ed|ing|s)?\b|"
              r"\breserv|\btransfer|\bwire\b|\binvoice|\bdeposit|\bfees?\b|\bcard\b|\bbank|\biban\b|"
              r"\brefund|\bspend|\bsubscri|\btickets?\b|\bdonat|\bmoney\b|\bcharge|"
              r"плат|плащ|купи|купу|поръча|резерв|превод|превед|фактур|депозит|карт[аи]|банк|"
              r"такс|билет|дари|пари"),
    "accounts": (r"\bpass(?:word|code|phrase)s?\b|\blog ?-?in|\blogin|\bsign ?-?in\b|\bsign(?:ing)? in(?:to)?\b|"
                 r"\bcredential|\baccounts?\b|\busername|\b2fa\b|\btwo[- ]factor|\botp\b|"
                 r"\bone[- ]time code|\bverification code|\bpin\b|\brecovery|\bapi key|"
                 r"парол|акаунт|потребителск|вход в|код за"),
    "as_owner": (r"\bon (?:his|her|their|your) behalf\b|\bin (?:his|her|their|your) name\b|"
                 r"\bas (?:him|her|them)\b|\bfrom (?:his|her|their|your) (?:e-?mail|address|account|inbox)\b|"
                 r"\bsign(?:ed|ing)? (?:it|this|that|for)\b|\bpretend|"
                 r"от (?:негово|нейно|тяхно) име|от името на|вместо (?:него|нея)"),
    "delete_mail": (r"\bdelet|\bremov|\btrash|\berase|\bwipe|\bpurge|изтри|премахн"),
    "forward_outside": (r"\bforward|\bfwd\b|\bpass (?:it|them|this) on\b|\bsend (?:it|them|this) on\b|"
                        r"препрат"),
    "third_party": (r"\bsend|\bsent\b|\bshar(?:e|es|ed|ing)\b|\bforward|\bintroduc|\bcc\b|\bcopy (?:in|him|her|them)\b|"
                    r"\be-?mail (?!me\b|us\b)\w|\binvit|\breach out|\bcontact (?!me\b|us\b)\w|"
                    r"\btell (?!me\b|us\b)\w|\blet (?:him|her|them|\w+) (?:know|see|have)\b|"
                    r"\bgive (?:him|her|them|\w+) access|\bmessage (?!me\b|us\b)\w|\bpost (?:it|this|them) to\b|"
                    r"изпрат|прати|сподел|препрат|запознай|покани|свържи|кажи на|пиши на|обади"),
    "time": (r"\bcalendar|\bmeet(?:ing)?s?\b|\bappointment|\bschedul|\bslots?\b|\bbook(?:ed|ing|s)?\b|"
             r"\bblock\b|\breserv|\bavailab|\binvit|\b(?:a|the) call\b|\bcall (?:with|me|us|him|her)\b|"
             r"\bdiar(?:y|ies)\b|\bhold (?:the|a|that|those)? ?(?:date|day|time|week)|"
             r"календар|срещ|час(?:а|ове)?\b|запази|насрочи|обаждане|разговор|резерв"),
    "publish": (r"\bpublish|\bpublic|\bpost(?:ed|ing)? (?:it|this|them|on|to)\b|\bannounc|\btweet|\bblog\b|"
                r"\brelease|\bpress release|\bgo live\b|\blinkedin|\bsocial media|"
                r"публику|публичн|обяв|пусни"),
    "irreversible": (r"\bdelet|\bremov|\bcancel|\bterminat|\bclose (?:the|my|his|her|their|an?) |"
                     r"\bsign(?:ed|ing)? (?:the|it|this|that|a|an)\b|\bsubmit|\bfil(?:e|ing) (?:the|it|this|a|an)\b|"
                     r"\bregister|\bapply|\bwipe|\bdestroy|\birrevers|\bpermanent|\bfor good\b|"
                     r"изтри|отмен|прекрат|закри|подпиш|подпис|подад|регистр|кандидат"),
}

#: Limits that are never read from words: the code's own.
NOT_FROM_WORDS = frozenset({"identity_doubt"})


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("’", "'").lower().split())


def asks_for(limit: str, words: str) -> bool:
    """Whether these words ask for the effect of this hard limit. A limit read from no words -
    acting while it is unsure who wrote - is the code's, and always true here."""
    if limit in NOT_FROM_WORDS:
        return True
    pattern = LIMIT_WORDS.get(limit)
    return bool(pattern) and re.search(pattern, _norm(words)) is not None


def effect_ok(limit: str, effect_words: str, *, quote: str = "", message: str = "") -> str:
    """Why a reading may not name this hard limit for an ask, or "": the words of theirs that ask
    for it must be quoted, be in the message (or the ask's own words), and say that effect."""
    if not limit or limit in NOT_FROM_WORDS:
        return ""
    said = _norm(effect_words)
    if not said:
        return (f"names hard limit {limit} with no effect_words: quote the words of theirs that ask "
                f"for that effect. If nothing they wrote asks for it, it is no hard limit: map it to "
                f"the action it is.")
    if said not in _norm(quote) and said not in _norm(message):
        return (f"gives effect_words \"{effect_words}\", which are not in their message: quote "
                "their own words exactly.")
    if not asks_for(limit, said):
        return (f"names hard limit {limit}, and \"{effect_words}\" do not ask for that effect. A hard "
                "limit is only what their words ask Rouh to do - pay, buy, book, sign, send or share "
                "with somebody else, publish, delete, reach ‹owner›'s accounts or passwords, commit "
                "‹his› time. General words never are one: talking to Rouh, the workspace, the "
                "interface, access to a task or the right to change it are actions on a task "
                "(page_chat, edit_task, access).")
    return ""


def _resources(raw) -> list[str]:
    if raw in (None, ""):
        return []
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw))
    return [str(x).strip().lstrip("#") for x in items if str(x).strip()]


def apply(one: dict, n: int, *, message: str = "", found=None) -> tuple[dict, str]:
    """A reading's ask with what its capability needs filled in, or what is wrong with it for the
    model to fix. `one` is the ask as the reading gave it; what comes back is the same dict with
    `capability`, `action`, `scope`, `values`, `grant`, `task`, `task_needs` and `hard_limit` as the
    capability says. A hard limit is checked against their words, whatever the capability."""
    found = found or capabilities.catalogue()
    one = dict(one)
    quote = str(one.get("ask") or "")
    said = str(one.get("capability") or one.get("action") or "").strip().lower()
    said = said.replace(" ", "_").replace("-", "_") if "." not in said else said
    said = OLD_WORDS.get(said, said)
    limit = str(one.get("hard_limit") or "").strip().lower()
    effect = str(one.get("effect_words") or "")
    if one.get("new_grant"):
        return one, (f"Ask {n} writes a new_grant. Grants are never written in words: name the "
                     "capability that does it, the resources it acts on and the values it asks, "
                     "and Rouh's code proposes the grant. If no capability does it, say "
                     "capability unsupported.")
    cap = None
    if said == UNSUPPORTED:
        one.update(capability=UNSUPPORTED, action=UNSUPPORTED, grant="", task="",
                   task_needs="", scope=[], values={})
    elif said == HARD_LIMIT:
        one["action"] = HARD_LIMIT
        if not limit:
            return one, f"Ask {n} is a hard_limit and names none: name the one its doing would need."
    elif said:
        cap = found.get(said)
        if cap is None:
            return one, (f"Ask {n} names capability \"{said}\", which Rouh does not have. The "
                         "capabilities are: " + ", ".join(sorted(found.caps)) + ", or hard_limit, "
                         "or unsupported.")
    elif one.get("grant") and str(one.get("grant")) not in ("none", "communicate"):
        named = found.by_legacy(str(one["grant"]))
        cap = named[0] if len(named) == 1 else None
        if cap is None and not named:
            return one, (f"Ask {n} names no capability: name the one that does it, from the "
                         "list, or unsupported.")
    elif one.get("grant") in ("none", "communicate") and not one.get("task") and not limit:
        cap = found.get("communication.reply")
    if cap is not None:
        one["capability"], one["action"] = cap.id, cap.action
        named = _resources(one.get("resource"))
        if one.get("task") and cap.resource == "task":
            named = [str(one["task"]).strip().lstrip("#")] + [x for x in named if x != str(
                one["task"]).strip().lstrip("#")]
        if cap.resource == "task":
            wrong = [x for x in named if not capabilities.TASK_RE.match(x.split("-")[0])]
            if wrong:
                return one, (f"Ask {n} names \"{wrong[0]}\" as a task: give each task's number, "
                             "such as 90.")
            if not named and cap.authority == "task_level":
                return one, (f"Ask {n} is {cap.id}, which is about one of ‹owner›'s tasks: give "
                             "each task's number in resource.")
            one["task"] = named[0] if named else ""
            one["scope"] = named
        elif cap.resource == "calendar":
            if any(capabilities.WILD.search(x) for x in named):
                return one, f"Ask {n} names every calendar: name each one, or none."
            one["scope"] = named
        else:
            one["scope"] = []
            if one.get("task") and cap.authority == "grant":
                # Work about one of the owner's tasks reads that task: research, a timeline, a
                # plan. It needs read on it, and the grant for the work.
                one["task_needs"] = "read"
        if cap.authority == "task_level":
            one["grant"] = "none"
            one["task_needs"] = {"view": "read", "edit": "", "decide": "decide"}[cap.level]
            if cap.action == "access":
                one["task_needs"] = "access"
        else:
            key = cap.legacy_grant if ":" not in cap.legacy_grant else ""
            one["grant"] = "none" if key == "communicate" else key
        values = one.get("values") if isinstance(one.get("values"), dict) else {}
        kept = {}
        for name, v in values.items():
            c = cap.constraint(str(name))
            if c is None:
                return one, f"Ask {n} gives {name}, which {cap.id} has no limit for."
            if c.type == "choice":
                vs = v if isinstance(v, list) else [v]
                if any(str(x) not in dict(c.values) for x in vs):
                    return one, (f"Ask {n} gives {name} {v}: it is one of "
                                 + ", ".join(x for x, _ in c.values) + ".")
                kept[name] = str(vs[0]) if len(vs) == 1 else [str(x) for x in vs]
        one["values"] = kept
        reserved = [r for r in cap.reserved]
        if reserved and not limit:
            limit = reserved[0]
    if limit:
        wrong = effect_ok(limit, effect, quote=quote, message=message)
        if wrong:
            return one, f"Ask {n} {wrong}"
        one["hard_limit"] = limit
        if cap is not None and limit not in cap.reserved:
            # Their words ask for the effect: it is that hard limit, whatever else it is.
            one["action"] = HARD_LIMIT
    return one, ""


def actions_said(found=None) -> list[str]:
    """The capabilities, and the two things an ask may be besides, as the reading is told them."""
    found = found or capabilities.catalogue()
    return [*found.brief(),
            f"   - {HARD_LIMIT}: an effect only ‹owner› decides, which their words ask for: paying "
            "or buying, ‹his› accounts or passwords, sending or sharing with somebody else, "
            "publishing, deleting, committing ‹his› time, what cannot be undone.",
            f"   - {UNSUPPORTED}: nothing above does it. It waits for ‹owner›, and nothing is "
            "granted for it."]


def _number(n: str) -> int:
    return int(n) if str(n).isdigit() else 0


def tasks_said(tasks: dict | None, first: str, owner: str) -> list[str]:
    """What a turn of a case is told of what the sender may do with the owner's tasks, from the one
    permission record (`task_access.for_judge`): each task they decide for, may edit or may only
    read, by its number, with the task it comes through when it is inherited, and what each level
    lets them do. Tasks only: a step goes with its task."""
    rows = [(n, t) for n, t in (tasks or {}).items() if "-" not in n and t.get("level")]
    if not rows:
        return []
    rows.sort(key=lambda one: _number(one[0]))

    def said(n: str, t: dict) -> str:
        via = str(t.get("from") or "")
        return (f"{n} {t.get('title') or ''}".strip()
                + (f" (through {via})" if via and via != n else ""))

    out = []
    for level, head, most in (
            ("decide", f"Tasks of {owner}'s {first} decides for, and so may change and read", 60),
            ("edit", f"Tasks of {owner}'s {first} may change", 60),
            ("view", f"Tasks of {owner}'s {first} may only read", 40)):
        got = [said(n, t) for n, t in rows if t["level"] == level]
        if got:
            out.append(f"{head}: " + "; ".join(got[:most]) + ("; and more" if len(got) > most
                                                                else "") + ".")
    out.append("What each level lets them do: " + LEVELS_SAID.replace("‹owner›", owner))
    return out


__all__ = ["HARD_LIMIT", "LEVELS_SAID", "LIMIT_WORDS", "UNSUPPORTED", "actions_said", "apply",
           "asks_for", "effect_ok", "tasks_said"]
