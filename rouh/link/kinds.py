"""Kinds of live shared space, and what each starts with.

Every kind is the same room and the same data (`doc.py`): fields, long texts and lists. A kind only
says what a new one starts with and what its page calls its parts. Phase 1 is the task page; phase 2
opens every kind of work a Rouh does (Petar's list: pages and explainers, documents and drafts,
trips, research, calendar proposals, lists).
"""
from __future__ import annotations

KINDS = {
    "task": {"word": "Task page", "fields": {"status": "in progress"}, "texts": ["notes"],
             "lists": ["steps"], "names": {"notes": "Notes", "steps": "Steps"}},
    "page": {"word": "Page or explainer", "fields": {}, "texts": ["body"], "lists": ["sections"],
             "names": {"body": "Page", "sections": "Sections"}},
    "doc": {"word": "Document or draft", "fields": {"status": "draft"}, "texts": ["body"], "lists": ["sections"],
            "names": {"body": "Opening", "sections": "Sections"}},
    "trip": {"word": "Trip", "fields": {"dates": ""}, "texts": ["notes"], "lists": ["flights", "stays", "places"],
             "names": {"notes": "Notes", "flights": "Flights", "stays": "Places to stay", "places": "Things to do"}},
    "research": {"word": "Research", "fields": {"question": ""}, "texts": ["summary"], "lists": ["sources", "findings"],
                 "names": {"summary": "Summary", "sources": "Sources", "findings": "Findings"}},
    "calendar": {"word": "Calendar proposal", "fields": {}, "texts": ["notes"], "lists": [],
                 "names": {"notes": "Notes"}},
    "list": {"word": "List", "fields": {}, "texts": [], "lists": ["items"], "names": {"items": "Items"}},
}


def of(kind: str) -> dict:
    return KINDS.get(kind) or KINDS["task"]


def word(kind: str) -> str:
    return of(kind)["word"]
