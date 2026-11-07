"""What needs the person in Slack, for the morning brief (`rouh/morning_brief.py`).

Petar, 16 October 2026, the first of five Slack ideas ("do all of those"): the brief has a
section of what waits on him in Slack - questions put to him he has not answered, @mentions of
him he has not replied to, and threads whose last message is to him - since the last brief. Only
what he must act on, never a summary of a channel (his principle N1). Each line is who, where, a
few words of what they asked, how long it has waited, and a link to the message in Slack.

**Where it comes from.** Only the messages Rouh keeps (`rouh/slack.py`, kept as they arrive and
read back over 90 days); nothing is searched for in Slack. A message is a candidate when it is in
one of these places and nobody but the person can be meant to answer it:

- one of his own direct messages or group direct messages (read with his own token): what the
  others wrote there since he last wrote there;
- a channel Rouh is in: a message that mentions him, and in a thread he started or wrote in,
  what the others wrote since his last word in it.

Each place is one line, however many messages wait in it. One he has answered since in the same
direct message or thread, or reacted to, is dropped: his words are in what Rouh keeps, and his
reactions are read from Slack itself, the one message history call per line, which also drops a
message deleted since. A model (the brief's own, `morning_brief._ask`, through the LLM service)
reads each place with what was said before it and says whether it really waits on him, and in a
few words what is asked; "thanks" and "see you" do not. Each verdict is kept with the brief and
reused while the place has nothing new, so Update does not ask about it again. With no model to
ask, a place waits when what waits in it asks a question.

**When there is nothing.** No connection, a connection that is not this person's, no Slack
account known for him, or nothing waiting: the brief has no Slack part at all, and the page draws
no section (W5).

**Put away.** Each line has an x on the page (Petar, 19 October 2026, fr_6d5b2ccbf194: "I want to
discard what is past and not needed anymore"). The line's place and the time of its newest message
are kept in his own setting (`DISMISSED`), and the line is left out of every brief after, made or
opened, until somebody writes in that place again, which is a new line. Undo takes it out again.

**Whose.** The organisation's Slack app is read for the one person who connected it, whose user
token it holds (`SlackConnection.user_id`), and for nobody else. His own direct messages are his
alone and are only ever in his own brief; the part marks each of them `private`.
"""
from __future__ import annotations

import logging
import re
import time

from . import slack

log = logging.getLogger("rouh.slack_brief")

#: The first words of what the model is told, which is also how its stand-in knows it
#: (`rouh/testing/fake_model.py`).
ASK = "You read Slack for a morning brief."

SYSTEM = ASK + """

The person is ‹owner›. You are given places in ‹his› Slack, numbered: each is one of ‹his› direct
messages, one thread, or one message in a channel that mentions ‹him›. Each has what was said there
before, then what others wrote that ‹he› has not answered.

For each place, decide whether it waits on ‹owner›: somebody asked ‹him› something, wants a decision,
an answer, a review, a time, a file or anything else only ‹he› can give, and ‹he› has not given it.
It does not wait on ‹him› when it is a thank you, a greeting, news for everybody, a message ‹he› was
only copied on, something addressed to somebody else, or something already settled in what was said
after it.

Answer with one JSON object and nothing else:
{"waiting": [{"n": <the place's number>, "what": "<what they ask of ‹him›>"}]}
listing only the places that wait on ‹him›. "what" is a few plain words, at most twelve, of what
they ask, written as a short phrase in English whatever language they wrote in, with no name and no
quotation marks: "whether to sign the Plovdiv lease on Friday", "a call tomorrow".
"""

#: How far back a first brief, or one after a long gap, looks.
SINCE_MOST = 7 * 86400
SINCE_FIRST = 86400
#: How long a line still waiting is carried from one brief to the next.
CARRY_MOST = 14 * 86400
#: The most lines a brief has, newest first, and the most messages of a place read to the model.
MOST_LINES = 12
MOST_WAITING = 6
MOST_BEFORE = 6
#: The longest one message is when it reaches the model.
MESSAGE_CHARS = 1200
#: The longest the page waits for Slack when it reads the reactions again as it opens.
AGAIN_SECONDS = 6.0
#: The person's own setting (`models.UserSetting`) holding the lines put away: {place key: newest at}.
DISMISSED = "slack_brief_dismissed"
#: How long a line put away is remembered: past this it could not be carried into a brief anyway.
DISMISSED_KEEP = CARRY_MOST + SINCE_MOST


# --- who he is in Slack ---------------------------------------------------------------------


def _connection_of(who):
    """The organisation's Slack app when it is this person's, with tokens to read with; or None."""
    try:
        conn = slack.connection(who.org_id)
    except Exception:  # noqa: BLE001 - no table yet, nothing to read
        return None
    if conn is None or not conn.bot_sealed or not conn.team_id or str(conn.user_id) != str(who.user_id):
        return None
    return conn


def _me(conn, who) -> str:
    """His own Slack id: the user token's, or the member whose confirmed address is his own."""
    if conn.slack_user_id:
        return conn.slack_user_id
    from . import my_card
    from .models import SlackPerson

    try:
        own = {a.lower() for a in my_card.own_addresses(str(who.user_id), str(who.org_id))}
    except Exception:  # noqa: BLE001 - no card: only the token can say
        return ""
    if not own:
        return ""
    found = (SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id, email__in=own,
                                        is_bot=False, deleted=False).values_list("slack_id", flat=True))
    return found[0] if len(found) == 1 else ""


def _my_names(conn, me: str) -> list[str]:
    """How a kept message writes a mention of him: "@" and the name `slack.plain` wrote out."""
    from .models import SlackPerson

    row = SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id, slack_id=me).first()
    names = {me}
    if row is not None:
        names |= {n for n in (row.real_name, row.name) if n}
    return sorted(names, key=len, reverse=True)


def _mentions(text: str, names: list[str]) -> bool:
    low = str(text or "").lower()
    return any(re.search("@" + re.escape(n.lower()) + r"(?![\w])", low) for n in names)


# --- the places that may wait on him --------------------------------------------------------


def _own(conv) -> bool:
    """One of his own direct messages or group direct messages, read with his own token."""
    return bool(conv.private) and conv.kind in slack.USER_KINDS


def _place_of(conv, m) -> str:
    """Which place a message is in: the direct message, its thread, or the channel message's own."""
    reply = bool(m.thread_ts) and m.thread_ts != m.ts
    if _own(conv):
        return f"{conv.channel_id}:{m.thread_ts if reply else ''}"
    return f"{conv.channel_id}:{m.thread_ts if reply else m.ts}"


def _answers(conv, key: str, m) -> bool:
    """Whether his message `m` is an answer in the place `key`: anything he wrote in one of his own
    direct messages, or a word in the same thread."""
    if _own(conv) and not key.partition(":")[2]:
        return m.channel_id == conv.channel_id
    return _in_place(conv, key, m)


def _in_place(conv, key: str, m) -> bool:
    """Whether a message belongs to the place `key`."""
    cid, _, root = key.partition(":")
    if m.channel_id != cid:
        return False
    reply = bool(m.thread_ts) and m.thread_ts != m.ts
    if _own(conv) and not root:
        return not reply
    return m.ts == root or m.thread_ts == root


def where_words(conv) -> str:
    """Where it was said, as the brief writes it: "#general", "Direct message", "Group message"."""
    if conv.kind in ("channel", "group"):
        return f"#{conv.name}"
    # Who wrote is the line's first words, so a direct message is not named again by its people.
    return "Direct message" if conv.kind == "im" else "Group message"


def permalink(conn, channel_id: str, ts: str, thread_ts: str = "") -> str:
    """The message's own address in Slack, as `chat.getPermalink` gives it, opening the app on a phone."""
    base = str(conn.team_url or "").rstrip("/")
    if not base:
        return ""
    url = f"{base}/archives/{channel_id}/p{str(ts).replace('.', '')}"
    if thread_ts and thread_ts != ts:
        url += f"?thread_ts={thread_ts}&cid={channel_id}"
    return url


def _places(conn, me: str, since: float, carried: set[str], start: float) -> list[dict]:
    """Every place with something in it from others since `since` (or a carried place's since
    `start`) that he has not answered there: its conversation, the messages waiting, and what came before."""
    from .models import SlackConversation, SlackMessage

    convs = {c.channel_id: c for c in SlackConversation.objects.filter(org_id=conn.org_id, team_id=conn.team_id)
             if (c.is_member or c.private) and not (c.kind == "im" and not c.private)}
    if not convs:
        return []
    names = _my_names(conn, me)
    rows = list(SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, at__gte=start,
                                            channel_id__in=list(convs)).order_by("at", "ts"))
    # The threads he is in: one he wrote in, or started, whenever that was. A message he started
    # one with is kept before anybody answers it, with no thread_ts of its own.
    threads = set(SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, author_id=me)
                  .exclude(thread_ts="").values_list("channel_id", "thread_ts"))
    roots = {(m.channel_id, m.thread_ts) for m in rows if m.thread_ts and m.thread_ts != m.ts}
    if roots:
        threads |= set(SlackMessage.objects.filter(
            org_id=conn.org_id, team_id=conn.team_id, author_id=me, channel_id__in={c for c, _ in roots},
            ts__in={t for _, t in roots}).values_list("channel_id", "ts"))
    keys: dict[str, float] = {}
    for m in rows:
        conv = convs[m.channel_id]
        if m.author_id == me or m.by_rouh or not (m.text or m.files):
            continue
        key = _place_of(conv, m)
        reply = bool(m.thread_ts) and m.thread_ts != m.ts
        if not _own(conv) and not _mentions(m.text, names) and not (
                reply and (m.channel_id, m.thread_ts) in threads):
            continue
        if m.at < since and key not in carried:
            continue
        keys.setdefault(key, m.at)
    out = []
    for key, first in keys.items():
        cid = key.partition(":")[0]
        conv = convs[cid]
        root = key.partition(":")[2]
        q = SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=cid)
        if root:
            q = q.filter(slack.models_q_thread(root))
        there = [m for m in q.order_by("at", "ts") if _in_place(conv, key, m)]
        mine = [m for m in (SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id,
                                                        channel_id=cid, author_id=me).order_by("at")
                            if _own(conv) and not root else there)
                if m.author_id == me and _answers(conv, key, m)]
        last_mine = mine[-1].at if mine else 0.0
        waiting = [m for m in there if m.at > last_mine and m.author_id != me and not m.by_rouh
                   and (m.text or m.files)]
        if not waiting:
            continue
        if not _own(conv):
            # In a channel only what is to him waits: the mention itself, or a reply in his thread.
            waiting = [m for m in waiting if _mentions(m.text, names) or (
                m.thread_ts and (m.channel_id, m.thread_ts) in threads)]
            if not waiting:
                continue
        before = [m for m in there if m.at <= waiting[0].at and m not in waiting][-MOST_BEFORE:]
        later = []
        if not _own(conv) and root and not any(m.thread_ts == root for m in there if m.ts != root):
            # A channel message with no thread under it: what he said in the channel afterwards
            # is shown to the model, which says whether it answered.
            later = list(SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=cid,
                                                     author_id=me, at__gt=waiting[0].at, thread_ts="")
                         .order_by("at")[:3])
        out.append({"key": key, "conv": conv, "waiting": waiting[-MOST_WAITING:], "first_at": waiting[0].at,
                    "before": before, "later": later})
    out.sort(key=lambda p: -p["waiting"][-1].at)
    return out[:MOST_LINES * 2]


def _verdict_key(place: dict) -> str:
    """A place as it stands: the same until something new is said in it, or edited."""
    last = place["waiting"][-1]
    edited = max((m.edited_at or 0) for m in place["waiting"])
    return f"{place['key']}|{last.ts}|{len(place['waiting'])}|{edited:.0f}"


# --- Slack itself: his reactions, and what was deleted --------------------------------------


def _reacted_or_gone(conn, me: str, channel_id: str, private: bool, root: str, tss: list[str],
                     first_at: float) -> str:
    """"answered" when he reacted to one of these messages, or replied where Rouh did not keep it;
    "gone" when they were all deleted; "" when they still wait, or Slack could not say."""
    client = slack.user_client(conn) if private else slack.bot(conn)
    if client is None:
        return ""
    try:
        if root:
            got = client.call("conversations.replies", channel=channel_id, ts=root, limit=200)
        else:
            got = client.call("conversations.history", channel=channel_id, oldest=f"{first_at - 1:.6f}",
                              inclusive="true", limit=200)
    except (slack.SlackError, slack.NotSetUp) as exc:
        log.info("slack: the brief could not read %s again: %s", channel_id, exc)
        return ""
    messages = got.get("messages") or []
    found = {str(m.get("ts")): m for m in messages}
    for ts in tss:
        for r in (found.get(ts) or {}).get("reactions") or []:
            if me in (r.get("users") or []):
                return "answered"
    if any(str(m.get("user") or "") == me and slack.ts_float(m.get("ts")) > first_at for m in messages
           if not root or str(m.get("thread_ts") or m.get("ts")) == root):
        return "answered"
    if tss and not any(ts in found for ts in tss):
        return "gone"
    return ""


# --- the part ------------------------------------------------------------------------------


def _line(conn, place: dict, what: str) -> dict:
    conv, last = place["conv"], place["waiting"][-1]
    first = place["waiting"][0]
    authors = []
    for m in place["waiting"]:
        name = m.contact_name or m.author_name
        if name and name not in authors:
            authors.append(name)
    return {"key": place["key"], "channel": conv.channel_id, "ts": last.ts, "thread_ts": last.thread_ts,
            "tss": [m.ts for m in place["waiting"]], "who": slack._and(authors[:3]) or "Somebody",
            "where": where_words(conv), "kind": conv.kind, "what": what, "at": first.at, "last_at": last.at,
            "link": permalink(conn, conv.channel_id, last.ts, last.thread_ts), "private": bool(conv.private)}


def _for_model(conn, places: list[dict], me: str) -> str:
    from . import clock

    def said(m) -> str:
        moment = clock.moment(m.at)
        who = "‹owner›" if m.author_id == me else (m.contact_name or m.author_name or "somebody")
        text = (m.text or "")[:MESSAGE_CHARS]
        if m.files:
            text += (" " if text else "") + "[files: " + ", ".join(m.files) + "]"
        return f"  {moment.strftime('%-d %b %H:%M') if moment else ''} {who}: {text}"

    parts = []
    for n, p in enumerate(places, 1):
        conv = p["conv"]
        where = {"im": f"‹his› direct message with {conv.name}", "mpim": f"‹his› {conv.name}",
                 "channel": f"#{conv.name}", "group": f"the private channel #{conv.name}"}.get(conv.kind, conv.name)
        what = "a thread in " if p["key"].partition(":")[2] and conv.kind not in slack.USER_KINDS and \
            any(m.thread_ts and m.thread_ts != m.ts for m in p["waiting"]) else ""
        lines = [f"=== {n}: {what}{where}"]
        if p["before"]:
            lines.append("Before:")
            lines += [said(m) for m in p["before"]]
        lines.append("Not answered:")
        lines += [said(m) for m in p["waiting"]]
        if p["later"]:
            lines.append("‹owner› said later in the channel:")
            lines += [said(m) for m in p["later"]]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _plain_verdict(place: dict) -> dict:
    """With no model: a place waits when what waits in it asks a question."""
    asks = [m for m in place["waiting"] if "?" in (m.text or "")]
    if not asks:
        return {"waits": False, "what": ""}
    words = (asks[-1].text or "").split()
    return {"waits": True, "what": " ".join(words[:12]) + ("…" if len(words) > 12 else "")}


async def make(who, since: float, before: dict | None) -> dict | None:
    """The brief's Slack part: {"ok", "items", "judged", "workspace"}, or None when there is no Slack
    of this person's to read. `before` is the brief this one is made on, whose verdicts are reused
    and whose lines still waiting are carried."""
    from asgiref.sync import sync_to_async

    from . import morning_brief

    conn = await sync_to_async(_connection_of)(who)
    if conn is None:
        return None
    me = await sync_to_async(_me)(conn, who)
    if not me:
        return None
    now = time.time()
    since = max(min(since, now - SINCE_FIRST), now - SINCE_MOST)
    old = ((before or {}).get("slack") or {})
    carried = {one["key"]: one["at"] for one in old.get("items") or [] if one.get("at", 0) > now - CARRY_MOST}
    start = min([since, *carried.values()])
    places = await sync_to_async(_places)(conn, me, since, set(carried), start)
    judged_before = old.get("judged") or {}
    judged: dict[str, dict] = {}
    ask = []
    for p in places:
        key = _verdict_key(p)
        if key in judged_before:
            judged[key] = judged_before[key]
        else:
            ask.append(p)
    if ask:
        got = None
        try:
            got = await morning_brief._ask(who, "brief_slack", SYSTEM, await sync_to_async(_for_model)(conn, ask, me),
                                           1500)
        except Exception:  # noqa: BLE001 - written down; the plain rule stands in
            log.exception("the morning brief's Slack reading could not ask a model")
        if got is not None:
            said = {}
            for one in got.get("waiting") or []:
                try:
                    said[int(one.get("n"))] = str(one.get("what") or "").strip()[:200]
                except (TypeError, ValueError, AttributeError):
                    continue
            for n, p in enumerate(ask, 1):
                judged[_verdict_key(p)] = {"waits": n in said, "what": said.get(n, "")}
        else:
            for p in ask:
                # Not kept: the next brief asks a model again, when there is one.
                p["plain"] = _plain_verdict(p)
    lines = []
    for p in places:
        verdict = judged.get(_verdict_key(p)) or p.get("plain") or {}
        if not verdict.get("waits"):
            continue
        lines.append((p, verdict.get("what") or ""))
    items = []
    for p, what in lines[:MOST_LINES]:
        root = p["key"].partition(":")[2]
        state = await sync_to_async(_reacted_or_gone)(
            conn, me, p["conv"].channel_id, bool(p["conv"].private), root,
            [m.ts for m in p["waiting"]], p["first_at"])
        if not state:
            items.append(_line(conn, p, what))
    gone = await sync_to_async(dismissed_of)(who)
    return {"ok": True, "items": _not_dismissed(items, gone), "judged": judged,
            "workspace": conn.team_name or "Slack"}


# --- lines put away ---------------------------------------------------------------------------


def dismissed_of(who) -> dict[str, float]:
    """The lines this person put away: {place key: the newest message's time when they did}."""
    import json

    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=DISMISSED)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    if not isinstance(held, dict):
        return {}
    return {str(k): float(v) for k, v in held.items() if isinstance(v, (int, float))}


def _line_at(one: dict) -> float:
    return float(one.get("last_at") or one.get("at") or 0)


def _not_dismissed(items: list[dict], gone: dict[str, float]) -> list[dict]:
    """The lines not put away. A line whose place has a newer message than when it was put away stays."""
    return [one for one in items if _line_at(one) > gone.get(one.get("key") or "", -1)]


def dismiss(who, key: str, at: float, *, undo: bool = False) -> dict[str, float]:
    """Put a line away, or with `undo` bring it back. What is kept after."""
    import json

    from .models import UserSetting

    gone = dismissed_of(who)
    if undo:
        gone.pop(key, None)
    else:
        gone[key] = max(float(at), gone.get(key, 0.0))
    oldest = time.time() - DISMISSED_KEEP
    gone = {k: v for k, v in gone.items() if v > oldest}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=DISMISSED,
                     value=json.dumps(gone), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return gone


def _still_waiting(who, part: dict) -> dict:
    """The part as the page opens: each line he has answered or reacted to since is dropped."""
    conn = _connection_of(who)
    if conn is None:
        return {**part, "items": []}
    me = _me(conn, who)
    if not me:
        return part
    from .models import SlackConversation

    convs = {c.channel_id: c for c in SlackConversation.objects.filter(
        org_id=conn.org_id, team_id=conn.team_id, channel_id__in={i["channel"] for i in part.get("items") or []})}
    keep = []
    started = time.time()
    for one in part.get("items") or []:
        conv = convs.get(one["channel"])
        if conv is None:
            continue
        if _answered_since(conn, me, conv, one):
            continue
        if time.time() - started < AGAIN_SECONDS:
            root = one["key"].partition(":")[2]
            if _reacted_or_gone(conn, me, conv.channel_id, bool(conv.private), root, one.get("tss") or [one["ts"]],
                                one["at"]):
                continue
        keep.append(one)
    return {**part, "items": keep}


def _answered_since(conn, me: str, conv, one: dict) -> bool:
    """Whether he wrote in the line's place after what waits there."""
    from .models import SlackMessage

    q = SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=conv.channel_id,
                                    author_id=me, at__gt=one["at"])
    return any(_answers(conv, one["key"], m) for m in q)


async def again(who, brief: dict) -> None:
    """The kept part read again as the brief is handed to the page, never asking a model."""
    from asgiref.sync import sync_to_async

    part = brief.get("slack")
    if not part or not part.get("items"):
        return
    try:
        part = await sync_to_async(_still_waiting)(who, part)
    except Exception:  # noqa: BLE001 - the kept lines stand
        log.exception("the morning brief's Slack lines could not be read again")
    gone = await sync_to_async(dismissed_of)(who)
    brief["slack"] = {**part, "items": _not_dismissed(part.get("items") or [], gone)}
