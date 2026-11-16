"""Your files open to anyone: which of ‹his› own Drive files anyone with the link can open, and which
are shared with people outside ‹his› company, with whom, asked in words.

Built by the nightly feature run, night 45 of the ledger (16 November 2026, task 94).
Before a client leaves, a partner asks what was shared with them, or a link turns up where it should
not, the question is "what of mine is open?". Rouh could not answer it: search_drive finds files by
name, list_drive_permissions reads one file at a time, and Drive's own screen shows a file's sharing
only inside its Share box. So the answer was an afternoon of opening Share on file after file.

So, while its switch is on, the tool `open_files` reads ‹his› own files in Drive with their sharing
(`Drive.owned_and_shared`, one listing, read only, newest change first, up to `MOST`), and says, in
order of how wide:

- **Anyone with the link** can open it (and whether it can be found by a search), and what they may do;
- **Shared outside**: every person, group or company outside ‹his› own domains it is shared with,
  each with what they may do;
- how many more are shared only inside ‹his› company, which are not listed.

Each file comes with its id and link, so closing the link is one more step with Rouh's own
manage_drive_file or share_drive_file, on ‹his› word. `who` narrows it to one outside address or
company ("what have we shared with northwind.test").

Nothing is changed or kept, and no model is asked.

**Whose.** The person's own Google connection, by `org_id` and `user_id`; ‹his› own domains are those
of ‹his› account and contact card (`my_card.own_addresses`).

**Its switch** is `open_files` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

SWITCH = "open_files"
TITLE = "Your files open to anyone: Drive files open with the link or shared outside"

#: The most files read in one answer, and listed under each heading.
MOST = 1000
SHOWN = 25

DESCRIPTION = (
    "Which of the person's own files in Google Drive are open beyond their company: those anyone "
    "with the link can open, and those shared with people, groups or companies outside the person's "
    "own domains, each with who and what they may do, newest change first, with the file id and link. "
    "Use it for 'what of mine is public', 'which files are open to anyone', 'what have we shared with "
    "<company or person>' (give who). It reads and changes nothing: closing a link is manage_drive_file "
    "or share_drive_file after the person says so.")

SCHEMA = {
    "type": "object",
    "properties": {
        "who": {"type": "string",
                "description": "Only what is shared with this outside address or domain, such as "
                               "dana@northwind.test or northwind.test. Left out, everything open."},
    },
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def own_domains(who, account: str = "") -> set[str]:
    from . import my_card

    addresses = list(my_card.own_addresses(str(getattr(who, "user_id", "") or ""),
                                           str(getattr(who, "org_id", "") or "")))
    addresses += [str(getattr(who, "email", "") or ""), account]
    return {a.rsplit("@", 1)[1].lower() for a in addresses if a and "@" in a}


_GENERIC = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
            "me.com", "proton.me", "protonmail.com"}


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[1].lower() if "@" in email else ""


def outside(permission: dict, mine: set[str]) -> bool:
    """Whether one permission reaches past the person's own company."""
    kind = permission.get("kind")
    if kind == "anyone":
        return True
    if kind == "domain":
        return str(permission.get("who") or "").replace("everybody at ", "").lower() not in mine
    domain = _domain(str(permission.get("email") or ""))
    if not domain:
        return False
    # A personal address at a mail provider is outside even when the person's own is there too.
    return domain not in (mine - _GENERIC)


def _role(role: str) -> str:
    from .google_api import can

    return can(role)


def _day(stamp: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).strftime("%-d %B %Y")
    except ValueError:
        return ""


def answer(files: list[dict], mine: set[str], *, only: str = "") -> str:
    """The answer, from the person's shared files and their own domains."""
    only = (only or "").strip().lower().lstrip("@")
    public, shared, inside = [], [], 0
    for one in files:
        held = one.get("permissions") or []
        anyone = [p for p in held if p.get("kind") == "anyone"]
        out = [p for p in held if p.get("kind") != "anyone" and outside(p, mine)]
        if only:
            out = [p for p in out if only in str(p.get("email") or "").lower()
                   or only in str(p.get("who") or "").lower()]
            anyone = []
        if anyone:
            public.append((one, anyone[0], out))
        elif out:
            shared.append((one, out))
        elif not only:
            inside += 1
    if not public and not shared:
        if only:
            return f"None of your own files in Drive is shared with {only}."
        return ("None of your own files in Drive is open to anyone with the link or shared outside "
                + (", ".join(sorted(mine)) or "your company") + "."
                + (f" {inside} are shared only inside it." if inside else ""))
    lines: list[str] = []
    if public:
        lines.append(f"Open to anyone with the link: {len(public)} of your files.")
        for one, link, out in public[:SHOWN]:
            found = " and anyone can find it in a search" if link.get("discoverable") else ""
            more = ("; also shared with " + ", ".join(_person(p) for p in out[:5])) if out else ""
            lines.append(f"- {one['name']} ({one['type']}, changed {_day(one['modified'])}): anyone with the link "
                         f"can {_role(link.get('role') or 'reader')} it{found}{more} - file id {one['id']} - {one['link']}")
        if len(public) > SHOWN:
            lines.append(f"- and {len(public) - SHOWN} more.")
    if shared:
        lines.append(("Shared with " + only if only else "Shared outside your company") + f": {len(shared)} of your files.")
        for one, out in shared[:SHOWN]:
            lines.append(f"- {one['name']} ({one['type']}, changed {_day(one['modified'])}): "
                         + ", ".join(_person(p) for p in out[:8])
                         + (f" and {len(out) - 8} more" if len(out) > 8 else "")
                         + f" - file id {one['id']} - {one['link']}")
        if len(shared) > SHOWN:
            lines.append(f"- and {len(shared) - SHOWN} more.")
    if inside and not only:
        lines.append(f"{inside} more are shared only inside your company, and are not listed.")
    lines.append("Nothing was changed. Closing a link or taking somebody off is one more step, on the person's word.")
    return "\n".join(lines)


def _person(p: dict) -> str:
    said = str(p.get("who") or "somebody")
    email = str(p.get("email") or "")
    if email and email not in said:
        said += f" ({email})"
    return f"{said} can {_role(p.get('role') or 'reader')}"


__all__ = ["DESCRIPTION", "MOST", "SCHEMA", "SHOWN", "SWITCH", "TITLE", "answer", "on", "outside", "own_domains"]
