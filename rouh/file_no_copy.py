"""Kept from being passed on: a Drive file viewers cannot download, print or copy, and editors cannot share.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
A deck for investors, a price list for one partner, a draft contract: they are shared to be read,
not to be downloaded and sent on. Drive has two settings for it, under Share, then the cog: "Viewers
and commenters can see the option to download, print and copy" and "Editors can change permissions
and share". Asked "let them read it but not download it", Rouh could share the file and nothing more.

So, while its switch is on, `manage_drive_file` takes two more settings for one file:
`viewers_can_copy` false keeps everybody who may only view or comment on it from downloading,
printing or copying it (Drive's copyRequiresWriterPermission), true gives it back; and
`editors_can_share` false keeps its editors from sharing it on or changing who may open it (Drive's
writersCanShare, which only the file's owner may change, and which a shared drive's own rules
decide instead), true gives it back. What the file is set to already is said, and nothing is
changed twice. Nobody is emailed. No model is asked.

**Whose.** The person's own Google connection (`org_id` and `user_id`), one file at a time.

**Its switch** is `file_no_copy` (`rouh/switches.py`): off, the two settings are refused and nothing
changes.
"""
from __future__ import annotations

SWITCH = "file_no_copy"
TITLE = "Kept from being passed on: a Drive file viewers cannot download, print or copy, and editors cannot share"

VIEWERS = {"type": "boolean",
           "description": "false: people who may only view or comment on the file cannot download, print or copy "
                          "it (Drive's 'viewers can download, print and copy' off); true gives it back. For 'let "
                          "them read it but not download it'. One file, not a folder."}
EDITORS = {"type": "boolean",
           "description": "false: the file's editors cannot share it on or change who may open it; true gives it "
                          "back. Only the file's owner may change it, and not in a shared drive."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def wanted(args) -> dict:
    """The settings asked for: {"viewers_can_copy": bool, "editors_can_share": bool}, either left out."""
    out = {}
    for name in ("viewers_can_copy", "editors_can_share"):
        value = args.get(name)
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no", "on", "off"):
            out[name] = value.strip().lower() in ("true", "yes", "on")
    return out


def state_of(found: dict) -> dict:
    """What Drive's answer says the file is set to now."""
    return {"viewers_can_copy": not bool(found.get("copyRequiresWriterPermission")),
            "editors_can_share": found.get("writersCanShare") is not False}


def said(name: str, file_id: str, now: dict, changed: list[str]) -> str:
    """What Rouh is told back, as Drive says it now."""
    what = name or file_id
    viewers = ("people who may only view or comment can download, print and copy it" if now["viewers_can_copy"]
               else "people who may only view or comment cannot download, print or copy it")
    editors = ("its editors can share it and change who may open it" if now["editors_can_share"]
               else "its editors cannot share it on or change who may open it")
    head = f"Changed {what!r} in Drive: " if changed else f"{what!r} was already set that way, so nothing was changed: "
    return (head + f"{viewers}; {editors}. Nobody was emailed. The file is {file_id}."
            + (" Note that this does not stop somebody taking a photo or a screenshot of what they can see." if
               not now["viewers_can_copy"] and "viewers_can_copy" in changed else ""))


__all__ = ["EDITORS", "SWITCH", "TITLE", "VIEWERS", "on", "said", "state_of", "wanted"]
