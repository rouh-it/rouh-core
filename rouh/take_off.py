"""Taken off your files: a person, or everybody at a company, taken off one file or off every file of
‹his› shared with them, asked in words.

Built by the nightly feature run, night 46 of the ledger (17 November 2026, task 94).
When a client relationship ends, a contractor leaves or a partner should no longer see the drafts,
the job is "take them off everything". Rouh could not do it: `share_drive_file` adds people and turns
a link off, but never takes a named person off, and Your files open to anyone (night 45,
`rouh/open_files.py`) only lists who is on what. So it was Drive's Share box, file after file.

So, while its switch is on, the tool `take_off_files` takes `who`, an address (dana@northwind.test) or
a company's domain (northwind.test), and:

- with `file_id`, takes every permission of theirs off that one file;
- without it, reads ‹his› own files that are shared (`Drive.owned_and_shared`, one listing) and takes
  their permissions off every one of them;

and says, file by file, what each of them could do before. A company's domain takes off its people
one by one and a permission for the whole domain. The owner is never taken off, the link anyone can
open is left as it is (`share_drive_file` with anyone_with_link off is that), and nobody is emailed:
Drive tells nobody when access is taken away. A file that would not let go is named with why.

The tool's own words say to tell the person what will be taken off, and let them agree, before it
is called, as share_drive_file's do.

No model is asked; nothing is kept.

**Whose.** The person's Google connection, by `org_id` and `user_id`.

**Its switch** is `take_off` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

SWITCH = "take_off"
TITLE = "Taken off your files: a person or a company taken off one file or every file shared with them"

#: The most of ‹his› files read, and taken off, in one call.
MOST = 1000
SHOWN = 30

DESCRIPTION = (
    "Takes a person, or everybody at a company, off the person's own files in Google Drive: off one "
    "file (file_id), or off every file of theirs shared with them (no file_id). who is an email address "
    "(dana@northwind.test) or a company's domain (northwind.test). It takes away their access straight "
    "away; Google tells nobody. The owner is never taken off and a link anyone can open is left as it "
    "is (share_drive_file with anyone_with_link off takes that away). Before you call it, say out loud "
    "who you are about to take off and from what, and let the person agree; open_files with who lists "
    "what they are on first. Use it for 'take Dana off the contract draft', 'take Northwind off all my "
    "files', 'remove the contractor from everything'.")

SCHEMA = {
    "type": "object",
    "properties": {
        "who": {"type": "string",
                "description": "The email address to take off, or a company's domain such as "
                               "northwind.test for everybody there."},
        "file_id": {"type": "string",
                    "description": "Only this file, by its id. Left out, every file of the person's "
                                   "shared with them."},
    },
    "required": ["who"],
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def target(text: str) -> tuple[str, str]:
    """(address, domain) from what was said: one of the two is filled, or both empty."""
    said = (text or "").strip().lower().strip("<>").lstrip("@")
    if not said or " " in said:
        return "", ""
    if "@" in said:
        return said, ""
    if "." in said:
        return "", said
    return "", ""


def theirs(permission: dict, address: str, domain: str) -> bool:
    """Whether one permission is the person or company to take off. Never the owner's or the link's."""
    if permission.get("role") == "owner" or permission.get("kind") == "anyone":
        return False
    email = str(permission.get("email") or "").lower()
    if address:
        return email == address
    if permission.get("kind") == "domain":
        named = str(permission.get("domain") or "") or str(permission.get("who") or "").replace("everybody at ", "")
        return named.lower() == domain
    return bool(email) and email.rsplit("@", 1)[-1] == domain


def answer(whom: str, done: list[tuple[dict, list[dict]]], failed: list[tuple[dict, str]], *,
           one_file: bool) -> str:
    """What was taken off, file by file, in the words the person hears."""
    from .google_api import can

    if not done and not failed:
        if one_file:
            return f"{whom} is not on that file, so nothing was taken off."
        return f"{whom} is not on any of your own files in Drive, so nothing was taken off."
    lines: list[str] = []
    if done:
        lines.append(f"Taken {whom} off {len(done)} file{'s' if len(done) != 1 else ''}:")
        for one, gone in done[:SHOWN]:
            lines.append(f"- {one.get('name') or one.get('id')}: "
                         + ", ".join(f"{p.get('who') or p.get('email')} could {can(p.get('role') or 'reader')} it"
                                     for p in gone[:6])
                         + (f" and {len(gone) - 6} more" if len(gone) > 6 else "")
                         + f" - file id {one.get('id')}")
        if len(done) > SHOWN:
            lines.append(f"- and {len(done) - SHOWN} more.")
    for one, why in failed[:10]:
        lines.append(f"Not taken off {one.get('name') or one.get('id')}: {why}")
    lines.append("Google emailed nobody. The owner and any link anyone can open were left as they were.")
    return "\n".join(lines)


__all__ = ["DESCRIPTION", "MOST", "SCHEMA", "SHOWN", "SWITCH", "TITLE", "answer", "on", "target", "theirs"]
