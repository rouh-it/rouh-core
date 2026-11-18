"""A mistyped address caught when sharing: a file is not shared, and a meeting not booked, with an
address a letter or two off one ‹he› already knows.

Built by the nightly feature run, night 47 of the ledger (18 November 2026, task 94).
Night 33's gene (`rouh/address_check.py`) holds an email whose address is a letter or two off a known
one. Sharing a file and inviting a guest were left out, and they are worse: "share the deck with
dana@northwnd.com" gives a stranger's Google account the deck for good, and Google emails them the
link from ‹his› account; a guest mistyped on a meeting gets the invitation, the agenda and the call
link. Nothing bounces, so nobody notices until Dana asks where the deck is.

So, while its switch is on, before Rouh shares a file with people by name (`share_drive_file`,
`create_doc` and every tool that shares through `ToolRegistry._share`) and before it books a meeting
with guests (`create_calendar_event`), each address is compared with the ones ‹he› already has, by
night 33's own rules (`address_check.known` and `address_check.meant`): ‹his› Synapse Master's
people, Rouh's mailbox and ‹his› own address.

- An address already known, or a new one that looks like nobody known, goes as before.
- One that is not known and is a letter or two off a known one is not shared, or the meeting is not
  booked: nothing changes in Drive or the calendar, nobody is emailed, and Rouh is told which address
  and which known one it is probably meant to be, to ask in a few words.
- When ‹he› says the new address is right, `address_checked` shares or books it as written.

No model is asked; nothing is kept.

**Whose.** The Synapse Master of the person sharing (`org_id` and `user_id`).

**Its switch** is `share_address` (`rouh/switches.py`): off, files are shared and guests invited at
whatever address is given, as before.
"""
from __future__ import annotations

SWITCH = "share_address"
TITLE = "A mistyped address caught when sharing a file or inviting a guest"

#: Said to the model beside share_drive_file's and create_calendar_event's other fields.
FIELD = {"type": "boolean",
         "description": ("Share or invite at the addresses exactly as written even though one is a "
                         "letter or two off an address the person already has. Only when the person "
                         "says the address is right, after being asked.")}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def near_misses(addresses: list[str], have: set[str]) -> list[tuple[str, str]]:
    """[(address as given, the known one it is probably meant to be)], for the ones held."""
    from . import address_check

    out: list[tuple[str, str]] = []
    for one in addresses:
        one = str(one or "").strip().lower()
        if not one or "@" not in one or one in have:
            continue
        meant = address_check.meant(one, have)
        if meant and (one, meant) not in out:
            out.append((one, meant))
    return out


def check(who, addresses: list[str]) -> list[tuple[str, str]]:
    """The near misses among `addresses`, against what the person has; [] when there are none."""
    from . import address_check

    wanted = [str(a or "").strip().lower() for a in addresses if a]
    if not wanted:
        return []
    return near_misses(wanted, address_check.known(who))


def said(found: list[tuple[str, str]], *, booking: bool) -> str:
    """Why nothing was done, in the words Rouh is handed."""
    done = ("Not booked, and no guest was invited: " if booking
            else "Not shared, nobody was given the file and Google emailed nobody: ")
    lines = [done + "; ".join(f"{one} is not an address the person has, and is a letter or two off {m}"
                              for one, m in found) + "."]
    lines.append("Ask the person in a few words whether they meant "
                 + (found[0][1] if len(found) == 1 else "those")
                 + ("; book it with the right address, or, if they say the new address is right, "
                    "book it again with address_checked." if booking else
                    "; share it with the right address, or, if they say the new address is right, "
                    "share it again with share_drive_file and address_checked."))
    return "\n".join(lines)


__all__ = ["FIELD", "SWITCH", "TITLE", "check", "near_misses", "on", "said"]
