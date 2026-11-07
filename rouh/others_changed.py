"""Changed by others: the pages of ‹his› that somebody else changed since ‹he› last opened them, in the brief.

Built by the nightly feature run, night 21, 24 October 2026 (task 94, idea I-126). ‹His› pages are
shared to be worked on: the copy of ‹his› company's site is written on one of ‹his› task pages by
the person ‹he› shared it with, who changed it nineteen times with Ask AI on the evening of
23 October 2026. Nothing tells ‹him› when that happens. On 22 October 2026 ‹he› had to ask a chat
"can you tell me if task 61 has been updated by him ... I want to know where we are, what he did,
and what I need to know", and a job went looking.

Every change somebody makes to a page through Ask AI, or by typing into it, is already kept whole
with a one-line summary of what it changed (`askai_edits`, `rouh/askai.py`), and every time ‹he›
opens a page is in the event log (`since_read.opens`). So, while its switch is on, the morning
brief has a section **Changed by others**, read afresh every time the page opens, with no model:
each page of ‹his› organisation that somebody other than ‹him› changed in the last
`LOOK_BACK_DAYS`, after ‹he› last opened it; who changed it, how many changes and when the last
was, and the summaries of the newest changes. **Open the page** opens it, which also takes it off
the list, since ‹he› has now seen it; **Seen** puts it away until somebody changes it again, with
Undo.

**Whose.** Changes to pages of ‹his› own organisation (`askai_edits.page_org_id`) and ‹his› own
opens, by `org_id` and `user_id`; what ‹he› put away is ‹his› own setting (`user_settings`,
`others_changed`). Nothing is sent and nothing is changed anywhere but that setting.

**Its switch** is `others_changed` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("rouh.others_changed")

SWITCH = "others_changed"
#: How far back changes are read, in days.
LOOK_BACK_DAYS = 7
#: The person's own setting: {page: the newest change id it was put away at}.
KEPT = "others_changed"
#: The most pages listed, and the most change summaries shown for one page.
MOST = 10
SUMMARIES = 4


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def kept(who) -> dict[str, int]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): int(v) for k, v in held.items() if isinstance(v, int)} \
        if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _names(user_ids: set[str]) -> dict[str, str]:
    """What each person who changed a page is called, by their account."""
    from django.contrib.auth import get_user_model

    from .comments import name_of

    ids = [int(u) for u in user_ids if u.isdigit()]
    out = {str(u.pk): name_of(u) for u in get_user_model().objects.filter(pk__in=ids)}
    for one in user_ids:
        if one.startswith("link:"):
            out[one] = "A visitor to a public link"
    return out


def _title(root, doc: str) -> str:
    from . import pages

    try:
        path = pages.check(root, doc)
    except Exception:  # noqa: BLE001 - a page that is gone is named by its address
        return ""
    return pages.title_of(path)


def changed(who, root, *, now: float | None = None) -> dict | None:
    """{items, count} for the brief, or None when nobody else changed a page of ‹his›."""
    from . import since_read
    from .models import AskEdit

    now = now or time.time()
    rows = list(AskEdit.objects.filter(page_org_id=str(who.org_id),
                                       created_at__gt=now - LOOK_BACK_DAYS * 86400,
                                       undone_at__isnull=True)
                .exclude(user_id=str(who.user_id))
                .values("id", "user_id", "doc", "summary", "created_at")
                .order_by("-created_at")[:2000])
    if not rows:
        return None
    by_doc: dict[str, list[dict]] = {}
    for r in rows:
        by_doc.setdefault(r["doc"], []).append(r)
    put_away = kept(who)
    names = _names({r["user_id"] for r in rows})
    out = []
    for doc, edits in by_doc.items():
        opened = since_read.opens(who, doc, now=now)
        last_open = opened[0] if opened else 0.0
        fresh = [e for e in edits if e["created_at"] > last_open]
        if not fresh:
            continue
        newest = fresh[0]
        if put_away.get(doc, 0) >= newest["id"]:
            continue
        summaries, seen = [], set()
        for e in fresh:
            words = " ".join(str(e["summary"] or "").split())
            if words and words not in seen:
                seen.add(words)
                summaries.append(words)
            if len(summaries) >= SUMMARIES:
                break
        people = []
        for e in fresh:
            name = names.get(e["user_id"], "Somebody")
            if name not in people:
                people.append(name)
        out.append({"key": doc, "doc": doc, "title": _title(root, doc) or doc.rsplit("/", 2)[-2],
                    "task": doc.split("/")[2] if doc.count("/") >= 3 else "",
                    "link": "/task/" + doc, "people": people, "changes": len(fresh),
                    "last": newest["created_at"], "newest": newest["id"],
                    "opened": last_open or None, "summaries": summaries,
                    "more": max(0, len(fresh) - len(summaries))})
    if not out:
        return None
    out.sort(key=lambda i: i["last"], reverse=True)
    return {"items": out[:MOST], "count": len(out)}


async def again(who, brief: dict, root) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("others_changed", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        found = await sync_to_async(changed)(who, root)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the pages changed by others could not be read")
        return
    if found:
        from . import evolution

        brief["others_changed"] = {"ok": True, "source": "Your pages", **found}
        await sync_to_async(evolution.used)(
            SWITCH, "shown", who=who, detail=f"{found['count']} pages changed by others")


def act(who, key: str, what: str, newest: int = 0) -> None:
    """Seen (put away until a newer change), Undo (taken back), or Open the page (put away too)."""
    from . import evolution

    held = kept(who)
    if what == "open":
        # Opened from here is seen: the line goes now, not once the open reaches the event log.
        if newest:
            held[key] = max(int(newest), held.get(key, 0))
            _keep(who, held)
        evolution.used(SWITCH, "opened", who=who, detail=f"opened {key} from the brief")
        return
    if what == "seen":
        held[key] = int(newest)
    else:
        held.pop(key, None)
    _keep(who, held)
    if what == "seen":
        evolution.used(SWITCH, "seen", who=who, detail=f"put away the changes to {key}")


__all__ = ["KEPT", "SWITCH", "act", "again", "changed", "on"]
