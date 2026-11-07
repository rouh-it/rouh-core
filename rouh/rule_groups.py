"""The groups the Rules page sorts every rule into, by what it is about, and the three sections they are in.

Petar, 29 October 2026, of the Rules page: "way too many things for me to generally understand. they need to
be in groups, either toggles or navigation or maybe both." Until then the page was four cards by where a
rule was kept - his rules, rules for someone, his words, built-in rules - about a hundred rows long. So every
rule is in one of the groups below, by its subject and never by where it is kept;
where it came from is its own flag (`rouh/rules.py`, `origin`).

And 30 October 2026: "one section about owner, one section about Rouh that includes those three things and
then one section with everything else, tools and specifics." So the groups are in three sections, in this
order (`SECTIONS`): About Rouh, in purple - About Rouh, Writing and voice, How Rouh works; About the owner, in
orange - About you, and About other people (who was "Who's who"); and everything else.

A rule's group is worked out here when it is kept (`sort`) and kept with it, so it never moves by itself
afterwards; the person can move it by hand on the page, and that is kept too.

The sorting is words, not a model: a rule is short and says plainly what it is about, a wrong guess is one
press to fix, and this way a rule is grouped the moment it is kept, the same way every time, for nothing.
"""
from __future__ import annotations

import re

#: The three sections, in the order the page lists them: its key (the page's colour for it), its name.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("rouh", "About Rouh"),
    ("owner", "About the owner"),
    ("other", "Everything else"),
)

#: Every group, in the order the page lists them: its key (in the page's address, `/rules/<key>`), its name, its
#: section, and the words that put a rule in it, each with its weight. A word is matched at the start of a word,
#: so "calendar" finds "calendars" and "mail" finds "mailbox" but not "gmail".
GROUPS: tuple[tuple[str, str, str, dict[str, int]], ...] = (
    ("about", "About Rouh", "rouh", {
        "you are rouh": 6, "your name": 4, "born": 3, "renamed": 4, "your own code": 4, "which model": 4,
        "model you are": 4, "setting up": 2, "assistant": 1}),
    ("voice", "Writing and voice", "rouh", {
        "character": 4, "tone": 3, "voice": 2, "spoken": 3, "speak": 3, "said aloud": 3, "written": 2,
        "write": 1, "prose": 3, "em dash": 3, "markdown": 2, "words": 1, "plain language": 3, "concise": 2,
        "fun": 2, "warm": 2, "cheeky": 3, "flirt": 3, "humour": 3, "humor": 3, "joke": 2, "sentence": 1,
        "numbers": 1, "jargon": 2}),
    ("rouh", "How Rouh works", "rouh", {
        "rouh": 1, "orb": 3, "model": 2, "memory": 2, "remember": 2, "rules": 1, "thoughts": 2, "boxes": 2,
        "turn": 1, "build": 1, "code": 1, "name": 1, "you are": 4}),
    ("you", "About you", "owner", {
        "the person is": 6, "the owner is": 6, "i prefer": 4, "prefers": 3, "his primary": 4,
        "her primary": 4, "birthday": 3, "allergic": 4, "lives in": 3, "home address": 4}),
    ("people", "About other people", "owner", {
        "girlfriend": 5, "boyfriend": 5, "wife": 5, "husband": 5, "father": 5, "mother": 5, "brother": 5,
        "sister": 5, "son": 5, "daughter": 5, "child": 3, "family": 3, "partner": 3, "executive assistant": 5,
        "contact": 2, "contacts": 2, "who people are": 3, "nickname": 3, "relationship": 2, "colleague": 2,
        "friend": 2, "called": 2, "meeting guests": 2, "person": 1, "people": 1, "icloud": 1,
        "linkedin profile": 1, "phone number": 2, "mobile": 1}),
    ("mail", "Mail and messages", "other", {
        "email": 2, "emails": 2, "mail": 3, "inbox": 3, "reply": 1, "replies": 1, "draft": 2, "sign": 1,
        "signing": 2, "send": 1, "sent": 1, "telegram": 3, "slack": 3, "message": 1, "messages": 1,
        "forward": 2, "thread": 1, "address": 1, "addressed": 2, "archive": 2, "gmail": 2}),
    ("calendar", "Calendar and time", "other", {
        "calendar": 4, "calendars": 4, "event": 2, "events": 2, "meeting": 1, "flight": 3, "flights": 3,
        "trip": 2, "travel": 2, "dinner": 2, "weekend": 2, "invite": 2, "date": 1, "time": 1, "clock": 2,
        "today": 1, "goals": 1, "reminder": 2, "schedule": 2}),
    ("asking", "Asking and permissions", "other", {
        "confirm": 3, "confirmation": 3, "approval": 3, "approve": 3, "approved": 3, "permission": 3,
        "permissions": 3, "ask": 1, "asking": 2, "without asking": 3, "decision": 2, "decisions": 3,
        "yes": 1, "risk": 2, "irreversible": 3, "trusted": 2, "trust": 2, "allowed": 2, "may use": 2,
        "share": 2, "sharing": 3, "access": 2, "edit access": 3, "read access": 3, "public": 2,
        "untrusted": 3, "safety": 2, "order": 1}),
    ("work", "Tasks and jobs", "other", {
        "task": 2, "tasks": 2, "step": 1, "steps": 1, "job": 2, "jobs": 2, "run": 1, "runs": 2,
        "nightly": 2, "research": 2, "quest": 2, "goal": 1, "commit": 2, "deploy": 3, "main": 1,
        "workspace": 2, "sales": 2, "deal": 2, "client": 2, "clients": 2, "worker": 2, "workers": 2,
        "background": 1, "sign up": 2, "fix": 1}),
    ("web", "Web and tools", "other", {
        "browser": 3, "chrome": 3, "headless": 3, "playwright": 3, "web": 2, "website": 2, "page": 1,
        "api": 3, "integration": 3, "integrations": 3, "token": 2, "cli": 2, "linkedin": 2, "youtube": 3,
        "picture": 2, "pictures": 2, "search": 1, "checkout": 3, "shipping": 3, "booking": 2, "login": 2}),
    ("machines", "Machines and servers", "other", {
        "machine": 3, "machines": 3, "server": 3, "servers": 3, "root": 2, "ssh": 3, "office pc": 3,
        "computer": 2, "mac": 2, "linux": 3, "printer": 3, "network": 2,
        "disk": 2, "service": 1, "nginx": 3, "systemd": 3}),
    ("product", "Product and design", "other", {
        "principle": 3, "principles": 3, "design": 3, "page": 1, "pages": 1, "screen": 1, "menu": 3,
        "hamburger": 3, "explainer": 3, "visual": 2, "artifact": 3, "artifacts": 3, "card": 1, "cards": 1,
        "canvas": 1, "button": 2, "layout": 3, "ui": 3, "html": 2, "naming": 2, "product": 2,
        "open source": 2, "installer": 2, "instance": 2}),
)

KEYS = tuple(g[0] for g in GROUPS)
NAMES = {g[0]: g[1] for g in GROUPS}
SECTION_OF = {g[0]: g[2] for g in GROUPS}
#: Where a rule nothing else claims goes: how Rouh works with the person.
FALLBACK = "asking"

_SPLIT = re.compile(r"[^a-z0-9]+")


def _hits(low: str, padded: str, word: str) -> int:
    """How often `word` (one word or a few) starts a word in the text."""
    if " " in word:
        return low.count(word)
    return padded.count(" " + word)


def sort(text: str, for_: list[dict] | None = None) -> str:
    """The group a rule is about, by its words, a rule for a person leaning to About other people, since it is
    about that person."""
    low = " ".join(str(text or "").lower().replace("’", "'").split())
    padded = " " + " ".join(w for w in _SPLIT.split(low) if w)
    score = {k: 0 for k in KEYS}
    for key, _name, _section, words in GROUPS:
        for w, weight in words.items():
            score[key] += weight * _hits(low, padded, w)
    for f in for_ or []:
        if isinstance(f, dict) and f.get("type") == "person":
            score["people"] += 6
        elif isinstance(f, dict) and f.get("type") in ("task", "project"):
            score["work"] += 2
    best = max(KEYS, key=lambda k: (score[k], -KEYS.index(k)))
    return best if score[best] > 0 else FALLBACK


def known(key: str) -> bool:
    return str(key or "") in NAMES


def listing() -> list[dict]:
    """The groups, in order, each with its section, for the page."""
    return [{"key": k, "name": n, "section": sec} for k, n, sec, _ in GROUPS]


def sections() -> list[dict]:
    return [{"key": k, "name": n} for k, n in SECTIONS]


__all__ = ["FALLBACK", "GROUPS", "KEYS", "NAMES", "SECTIONS", "SECTION_OF", "known", "listing", "sections", "sort"]
