"""What a trusted contact's Clockwork item may do, decided by code each time it runs.

Petar, 12 October 2026, after a trusted contact's "so we can be reminded by you?" failed
although he had given them Clockwork: "Keep in mind, clockwork is about scheduling tasks not
just reminders. It should follow everything [they] can do in general without time scheduling."

So Clockwork is a time modifier, not a list of its own (`grants.CLOCKWORK_PROMPT`):

- **What an item may do comes from the contact's other grants.** A message or a reminder to
  them is Communication; a note in the owner's memory is Memory; work for them is Rouh for
  themselves; an addition to a task shared with them is Shared task. An item records the
  grants its work uses (`Reminder.uses`) and who it goes to (`Reminder.goes_to`).
- **Telling the owner at a time about what they told them is Clockwork alone.**
- **It is checked when it runs**, against the grants they hold then (`refusal`): a grant
  taken away stops their items that need it, and each says why on Clockwork.
- **What goes to them goes through the one outbox** (`mail_outbox.send_item`), and a "do"
  item's work runs with their grants' tools only (`turn_for`), so no hard limit is ever
  reachable from Clockwork.
"""
from __future__ import annotations

CLOCKWORK = "clockwork"
COMMUNICATE = "communicate"

#: Who an item goes to: the owner, told about what they told them; the contact; or both.
OWNER, CONTACT, BOTH = "owner", "contact", "both"
GOES_TO = (OWNER, CONTACT, BOTH)
#: The tool's words for them (`tools.ToolRegistry._clockwork_for_contact`). "petar" is the
#: word the tool took before 20 October 2026, still read as the owner.
TO_WORDS = {"owner": OWNER, "petar": OWNER, "them": CONTACT, "contact": CONTACT, "both": BOTH}

#: Where the contact gets an item: their email, or the Telegram account linked to them.
CHANNELS = ("email", "telegram")


def goes_to(row) -> str:
    """Who a row goes to: "owner", "contact" or "both". A row written before 20 October 2026
    may still say "petar", which is the owner, as anything else unknown is."""
    value = str(getattr(row, "goes_to", "") or "")
    return value if value in GOES_TO else OWNER


def to_them(row) -> bool:
    return goes_to(row) in (CONTACT, BOTH)


def to_owner(row) -> bool:
    return goes_to(row) in (OWNER, BOTH)


def needs_of(goes: str, uses) -> list[str]:
    """Every grant an item needs held: Clockwork, what its work uses, and Communication when
    it goes to them."""
    out = [CLOCKWORK]
    for key in uses or ():
        if key and key not in out:
            out.append(str(key))
    if goes in (CONTACT, BOTH) and COMMUNICATE not in out:
        out.append(COMMUNICATE)
    return out


def needs(row) -> list[str]:
    return needs_of(goes_to(row), getattr(row, "uses", None) or [])


def clean_uses(raw, tree) -> list[str]:
    """The grants an item's work uses, as the tool names them, checked to be real grants.
    ValueError says what is wrong."""
    from . import grants

    out: list[str] = []
    for one in raw or ():
        key = tree.resolve(str(one or "").strip().lower())
        if not key:
            raise ValueError(f"{one} is not a grant. Name grants by their ids, such as memory, "
                             "use or shared_task.")
        node = tree.nodes[key]
        if node.holding == grants.INBOX:
            raise ValueError("‹owner›'s inbox is never read or changed at a time for a contact.")
        if key != CLOCKWORK and key not in out:
            out.append(key)
    return out


def refusal(contact, tree, keys, *, now: bool = False, owner: str = "") -> str:
    """Why the contact may not have this done, or "" when they may: each grant in `keys` must
    be held. `now` words it for when an item comes due ("no longer holds")."""
    name = getattr(contact, "name", "") or owner or "They"
    first = name.split()[0] if name.split() else name
    if contact is None:
        return f"{owner or 'Its contact'} is no longer on your Trusted contacts."
    if getattr(contact, "implicit", False):
        return f"{name} is not on your Trusted contacts."
    if not contact.trusted:
        return f"{name} is switched off on your Trusted contacts."
    from . import capability_grants

    for key in keys:
        found = tree.resolve(key)
        if not found:
            return f"It needs a grant, {key}, that is not there any more."
        # Held on their page, as a capability in code names it, or as a grant of their own in
        # force - not taken back, not ended, not suspended (CAPABILITIES.md).
        if not capability_grants.holds_key(contact, found, tree):
            return (f"{first} {'no longer holds' if now else 'does not hold'} "
                    f"{tree.path_said(found)}, which it needs.")
    return ""


def to_said(row, owner: str, you: str = "you") -> str:
    """Who it goes to, for the Clockwork list: "Goes to Sam and you"."""
    first = (owner.split() or ["them"])[0]
    return {OWNER: f"Goes to {you}", CONTACT: f"Goes to {first}",
            BOTH: f"Goes to {first} and {you}"}[goes_to(row)]


def turn_for(row, contact, tree, who):
    """The work of a "do" item, held like a case's work (`mail_turn.MailTurn`): the tools of
    the grants it uses and nothing else, no hard limit, and nothing sent by the model."""
    from . import mail_turn

    from . import capability_grants

    tools = tuple(t for t in tree.tools_for(getattr(row, "uses", None) or [])
                  if t != "clockwork_for_contact")
    # What its work may do, checked on every call as a case's work is (CAPABILITIES.md): the
    # capabilities of the grants it uses, held now.
    authorized = capability_grants.clockwork_authorized(contact, tree,
                                                        getattr(row, "uses", None) or [])
    return mail_turn.MailTurn(
        user_id=str(who.user_id), org_id=str(who.org_id), message_id=f"clockwork:{row.id}",
        sender=(contact.addresses or [""])[0] if contact.addresses else "",
        relationship_known=True, mode=mail_turn.CARRY_OUT, case_id=0, trusted_id=contact.id,
        extra_tools=tools, granted=True, limits=frozenset(), sees=getattr(contact, "sees", None),
        authorized=authorized)


__all__ = ["BOTH", "CHANNELS", "CLOCKWORK", "COMMUNICATE", "CONTACT", "GOES_TO", "OWNER",
           "TO_WORDS", "clean_uses", "goes_to", "needs", "needs_of", "refusal", "to_owner",
           "to_said", "to_them", "turn_for"]
