"""What a part of Synapse's page means, in plain words: the (i) beside every label.

Petar, 3 October 2026 (fr_bc51d0de9b2b): "Please put (I) everywhere so I can
click and understand what does that specific section or title or attribute
mean. Inside put a button 🤷‍♂️ which would mean I still don't get it, and the
explanation should be rewritten. It should be generic explanations that are
not related to the data stored for this item specifically."

So an explanation is about a label in a place on the page, never about what a
dataset holds: the page sends the label, where it sits ("Items tab, an item's
page, Permissions, tier and sensitivity") and, for a number, its own note, and
nothing of the data. The first explanation of a label in a place is written
once by the helper model and kept for the organisation (`synapse.explanation`,
migration 0064), so the same label says the same thing on every dataset and
opens at once after the first time. 🤷‍♂️ asks for a new one with the earlier
ones in front of the model, so each rewrite says it another way; rewrites are
not kept, which is the page's session and nothing more.

Petar, the same day (fr_8f9b0f6b0fa4): "When I have an explanation like that,
I would like input to ask my question so the explanation is changed more in
the direction that was clear for me". So the box also takes his own words
about the explanation in front of him, and the rewrite is built around them:
it keeps what he says made sense, reworks what did not and answers what he
asked. Each question goes with the explanations and questions before it, so
he can narrow it down several times. These are not kept either.

What the model reads to explain it is what the page is made of, so it can say
what a column really is rather than guess from its name: the design spec
(85-01), how the lab was built and where it differs (85-02), the page's own
code (`synapse.js`) and the numbers it works by (`numbers.py`). That is the
same long text on every call and comes first, so OpenAI's prompt cache reads
it after the first call.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading

from . import ai, db

log = logging.getLogger("rouh.synapse.explain")

HERE = os.path.dirname(os.path.abspath(__file__))
ROUH = os.path.dirname(HERE)
PAGE_CODE = os.path.join(ROUH, "static", "synapse.js")
NUMBERS_CODE = os.path.join(HERE, "numbers.py")

#: The two documents in the workspace, by the end of their names, which
#: survive a task being renumbered or moved.
SPEC_NAME = "one-memory-for-rouh-design-spec.md"
BUILT_NAME = "how-the-synapse-lab-is-built.md"

EM_DASH = chr(0x2014)
MAX_LABEL = 200
MAX_PLACE = 300
MAX_HINT = 600
MAX_QUESTION = 1000

INSTRUCTIONS = """\
You explain one part of a web page to the person who owns the system it shows, ‹owner›. \
The page is Synapse's lab inside Rouh: a debugger for a memory system, with a homepage of datasets and, \
for each dataset, tabs (Activity, Add, Items, Retrieve, Explore, Tune, Evaluate). \
‹He› is reading it to understand it in detail so ‹he› can start correcting it.

You are given a label from the page (a section heading, a title, a column, a field or an attribute) \
and where on the page it sits. Say what that part of the page is and what it is for, in general:
- what it shows or what it lets ‹him› do, and where its value comes from;
- why it matters for how Synapse stores, links or finds things, when it does.

Rules:
- Generic only. You are never shown the data, so never describe any particular value, item, person or \
number; explain the concept, so the explanation is true on every dataset.
- Plain words for an intelligent reader who did not write the system. Define any term you have to use.
- Two to five short sentences, at most 90 words. No headings, no lists, no markdown, no quotation of code.
- Never use an em dash; use a plain dash or a comma.
- Where the spec has a decision that governs it, you may end with it in brackets, like (spec D46).
- Base what you say on the documents below: the page's own code shows exactly what each label displays, \
the build notes say where the lab differs from the spec. If the documents do not say, say what the label \
most plausibly means and that it is your reading.

The documents follow.
"""

REWRITE = """\
‹He› read the explanations below and still does not get it. Write a new one that says the same thing \
another way: simpler, from a different angle, and with a small everyday example or comparison. \
Do not repeat their sentences. The same rules apply.
"""

ASKED = """\
Above is how the explanation has gone so far: each explanation ‹he› read and, after it, what ‹he› said about it. \
Write a new explanation built around the last thing ‹he› said. Keep and build on the parts ‹he› says made sense, \
rework from a different angle the parts ‹he› says did not, and answer ‹his› question directly within it. \
Stay on this label and stay generic; if ‹he› asks about a particular value, explain what such values mean in general. \
The same rules apply, except that you may use up to 140 words.
"""

#: Labels whose explanation is written here rather than by the model, because
#: the model's reading of them misled. "What the model reads (D11)" read as a
#: card prepared and stored for search (Petar, 3 October 2026); it is neither.
#: The fixed text is what the (i) opens, in place of any kept one, and it is the
#: facts every rewrite has to keep, a 🤷‍♂️ one or one built around his question.
FIXED = {
    "What the model reads (D11)": (
        "This text is not stored anywhere and is not searched. "
        "Plain code, with no model involved, builds it fresh from the item's stored X-ray each time "
        "the item goes into a question's pack (compact() in rouh/synapse/text.py). "
        "It is a header line (kind, date, people, title), then GIST, then one labelled line per claim, "
        "such as FACT, ASK (open) or CAVEAT. "
        "If the item has no claims, it shows up to about 900 characters of the item's original text instead, which nothing is cut from. "
        "What is stored and searchable is the X-ray itself, kept as data on the item and also written "
        "as a passage of its own (D24). "
        "This card is only the plain-text way that X-ray is shown to the model, in place of JSON (D11)."
    ),
    # Petar, 4 October 2026: code cuts nothing from an item's text (spec D25, revised).
    "Nothing cut: the whole text is kept (D25)": (
        "Code cuts nothing from an item's text. "
        "Quoted earlier replies, signatures and everything else stay in, because they are real context "
        "that may be needed or searched for. "
        "The whole text is what becomes the passages, the words searched, the embeddings and what the X-ray reads, "
        "and its word count is the one the X-ray settings are measured against. "
        "Every kind of item is treated the same way, emails included."
    ),
    "Quoted replies and signatures cut (D25)": (
        "This step is from a trace written before 4 October 2026, when code still cut quoted earlier replies "
        "and signatures from an item before it became passages. "
        "Nothing is cut any more: an item stored or edited since keeps its whole text, and a trace of it says "
        "\"Nothing cut: the whole text is kept\" here instead."
    ),
    # Petar, 4 October 2026, renamed "shown in answers" and "cited by answers" on an item's page
    # because the names were unclear, and said what each counts. The same day he had both count only
    # questions a person asked, the rows learning uses, with the rest on a smaller line under them.
    "read for questions": (
        "Each question Synapse is asked hands the model a pack of items to read. "
        "This counts how many of those packs included this item. "
        "Learning (D57) strengthens the links on the path to items an answer used, and weakens the links "
        "that lead only to items read 10 or more times and never used, so use in an answer is the only signal. "
        "It counts only questions a person actually asked, the same ones learning counts. "
        "Evaluation runs and background or other questions nobody asked are on the smaller line below, "
        "shown only when there are any."
    ),
    "used in answers": (
        "Of the packs this item was read in, this counts how many answers relied on it and gave it a footnote, "
        "so it can never be more than the read for questions number. "
        "Learning (D57) strengthens the links on the path to items used like this, and weakens the links "
        "that lead only to items read 10 or more times and never used, so this is the only signal. "
        "It counts only questions a person actually asked, the same ones learning counts. "
        "Evaluation runs and background or other questions nobody asked are on the smaller line below, "
        "shown only when there are any."
    ),
    # Petar, 3 October 2026, said what this one is, so it is his words and not the model's reading;
    # revised with D34 on 4 October 2026, when he found one email's topics far too narrow.
    "Topics, on an item's page": (
        "Topics are the lasting subjects things are filed under, which many items will be about over months, "
        "such as onboarding, fundraising, hiring, legal or a named project. "
        "They are never an event, a date, a single meeting, a person or an organisation (those are contacts), "
        "or two subjects in one name. "
        "When the model reads an item it names at most 2 topics, and none when nothing lasting applies, "
        "choosing from the topics and proposals already there whenever one fits. "
        "A name that is a topic already, spelt the same or meaning the same, links the item to it, and these are "
        "listed first. "
        "A new name is only a proposal, listed below with how many items back it; a later name that means the "
        "same counts towards it. "
        "It becomes a topic once enough items propose it within a set number of days. "
        "How close in meaning counts as the same, and both of those numbers, are under Tune, Links (spec D34)."
    ),
    # Every "Sensitivity" on the page: the Items table's column, the Add form's field, the item
    # page's value and the X-ray step's answer. Petar asked on 3 October 2026 for the levels to be
    # listed, each with what it really changes (search.readable_sql, walk.py, ai.decide's D67 check)
    # and how it is set (ingest.code_sensitivity, model_sensitivity, _raise_for_area, D75).
    "sensitivity": (
        "How sensitive an item is. It decides which models may handle it, and for the strictest levels who "
        "besides its owner can find it.\n\n"
        "normal: nothing sensitive. Found by all its readers, and the only level that may go to the hosted "
        "decision model (D67).\n"
        "private: personal, but not special. Found by all its readers, kept off the hosted decision model.\n"
        "special: health, money, legal matters, private contact details or another person's personal life. "
        "Kept off the hosted decision model, and found only by its owner's questions, even when others are "
        "readers. A layer built from it is special too.\n"
        "unlabelled: no model has read it yet. Treated like special until a level is set: kept off the hosted "
        "decision model and found only by its owner.\n\n"
        "How it is set: a level given with the item is a person's word and stands. Otherwise the model sets it "
        "when it reads the item for its X-ray. An area of health, money, legal or finance raises it to special, "
        "and these only raise it, never lower it. Since 4 October 2026 no decision call is asked about it: the X-ray "
        "call's reading is the one model's word on it (spec D82). Code never "
        "guesses it from words. Every item but a person or a topic gets an X-ray; a person or a topic "
        "keeps the level it came with, or stays unlabelled.\n\n"
        "What it does not do: readers decide who may see an item, and sensitivity only adds limits on top. It "
        "does not stop the helper model reading the item for its X-ray, or its passages being embedded."
    ),
}

# Petar, 3 October 2026 (D80): code decides no tier; a model makes every item's tier call. Kept
# explanations of these labels were written when code decided tiers, so these say it as it is now.
TIER = (
    "An item's tier decides how much work Synapse spends on it: tier 0, junk, is found only by its exact words "
    "and is never embedded, read or linked; tier 1, normal, is embedded and X-rayed (above the X-ray word count on Tune); "
    "tier 2, important, gets everything and weighs most when Synapse walks its links. "
    "Code decides no tier. It gathers signals about the item, such as the sender, the recipients, bulk headers, "
    "how often the owner wrote back, a star or a task, and a model reads them with the item's text and decides "
    "the tier, with a one-line reason, for every item (spec D80). "
    "For an item that gets an X-ray, that decision is made inside the X-ray call itself, which reads the same signals "
    "with the whole item, so no separate tier call is made (spec D82). "
    "Until the model answers, the tier is pending and the item counts as normal."
)
SIGNALS = (
    "The facts code collected about an item for its tier call: kind and source, the sender and whether they are "
    "the owner or a known contact, how many items came from them and how often the owner wrote to them, the "
    "recipients, bulk or list headers and the Gmail category, an automatic-looking address, bulk words near the "
    "top, a star, a task or project, whether the owner replied in the thread, its length, attachments and area. "
    "They are evidence, never verdicts: no signal puts an item in a tier by itself. "
    "The model weighs them with the text and decides (spec D80)."
)
TIER_CALL = (
    "The tier call's answer: the tier, the one-line reason the model wrote, which model and backend answered, "
    "what the call cost and how long it took. "
    "The helper model makes the call, because it can say why. If it cannot answer, the item is tier 1 and the "
    "reason says so; only when Tune has decision models on is a decision model asked first, and then its pick "
    "and how sure it was stand in for a reason. A tier of 0 only ever comes from a model (spec D80)."
)
FIXED.update({
    "Tier": TIER,
    "tier": TIER,
    "why this tier": (
        "The reason for the item's tier, in one line, as the model that decided it wrote it (spec D80). "
        "Code only gathers the signals; the helper model reads them with the text and makes the call. "
        "If the helper model could not answer, a decision model's pick and how sure it was stand in for a reason; "
        "if no model answered, it says so and the item is tier 1. "
        "For an item with an X-ray, the X-ray call wrote it, in the same answer as the X-ray (spec D82). "
        "If the X-ray later moved the item between tiers 1 and 2, both readings are kept here."
    ),
    "tier set by": (
        "Who set the item's tier. Normally a model: for an item with an X-ray, the helper model in its X-ray call "
        "(spec D82); for any other item, the helper model's tier call (spec D80). "
        "Otherwise: a decision model, when the helper model could not answer; nobody, when no model could, so the "
        "item is tier 1 until it is asked again; pending, while the call has not answered; the helper model again, "
        "when its X-ray moved the item between tiers 1 and 2; code, for items stored before 4 October 2026 under "
        "the old rules; or set when Synapse made it, for people, layers and topics it made itself."
    ),
    "Signals gathered by code": SIGNALS,
    "Signals the tier call read": SIGNALS,
    "Tier decided by a model": TIER_CALL,
    "Tier: signals gathered by code, decided by a model (D80)": (
        "The step that sets an item's tier. First code gathers the signals, facts about the item such as its "
        "sender, recipients, headers, history with the owner, a star or a task, and decides nothing. "
        "Then a model reads those signals with the item's text and decides tier 0, 1 or 2 with a one-line reason. "
        + TIER_CALL.split(". ", 1)[1]
    ),
    "Tier: signals gathered by code, decided in the X-ray call (D82)": (
        "The step that records an item's tier when it gets an X-ray. Code gathered the signals, facts about the item "
        "such as its sender, recipients, headers, history with the owner, a star or a task, and decided nothing. "
        "The X-ray call read them with the whole item and decided tier 0, 1 or 2 with a one-line reason, in the same "
        "answer as the X-ray, so no separate tier call was made. Its cost and time are the X-ray step's (spec D82)."
    ),
    "Sensitivity: read in the X-ray call, which only raises what came with the item (D60, D82)": (
        "The step that records an item's sensitivity when it gets an X-ray. The X-ray call read the item and said "
        "normal, private or special. A level given with the item, or an area of health, money, legal or finance the "
        "owner set, can only raise that, never lower it. No separate sensitivity suggestion is asked for an item "
        "with an X-ray (spec D82). Readers stay the permission check."
    ),
    "One call for an item with an X-ray (D82)": (
        "Since 4 October 2026 an item that gets an X-ray has its tier, sensitivity and area decided in that one "
        "helper call, beside its gist and claims. The separate tier call (D80) and the sensitivity suggestions (D75) "
        "cost more than the X-ray itself and protected nothing, since every such item is X-rayed and embedded "
        "anyway. Every item but a person or a topic gets an X-ray (D8), and no decision call is made unless Tune "
        "turns decision models on, to compare."
    ),
    "Tier call: every item's tier, with a one-line reason (D80)": (
        "Which model decides every item's tier. Code gathers signals about each item and decides nothing; this "
        "model reads them with the item's text and returns tier 0, 1 or 2 with a one-line reason, for every item, "
        "junk included, every time it is stored or edited. "
        "If it cannot answer, the item is tier 1 and says why; a decision model is asked first only when Tune "
        "has decision models on (spec D80)."
    ),
    "tier, as the X-ray read it": (
        "The X-ray call's own reading of the item's tier, important, normal or junk, with its reason. Since 4 "
        "October 2026 this is what decides the tier of an item with an X-ray, junk included (spec D82). Only when "
        "Tune switches the separate tier call back on does that call decide first, and then this reading may only "
        "move an item between tiers 1 and 2 (spec D58). Older X-rays said keep, normal or important."
    ),
    # Petar, 4 October 2026, renamed "Its history" on an item's page and said what it holds.
    "Related activities": (
        "The runs from the Activity tab that stored, edited or reprocessed this item, newest first, each with "
        "when it ran, how long it took, whether it finished, what it came to and what it cost. "
        "Each one opens its step-by-step record in Activity. "
        "Questions that only found the item are not listed here; they are under "
        "\"Every model and decision call that held it\"."
    ),
})

# Petar, 4 October 2026: people named in an item's text, read in the X-ray call and kept as raw
# material for a later feature; Q21 stays open, so nothing is linked or made from them.
PEOPLE_MENTIONED = (
    "The people this item's text names, as the X-ray call read them, in the same one call as the X-ray (spec D82). "
    "For each: the name as written, a Latin spelling when it is in Cyrillic, the emails, phones and handles the text "
    "plainly gives as theirs, organisation, role, how they stand to the sender, whether they wrote or receive it, how "
    "sure the model is, and a short quote that code checks is really in the text; a person whose quote fails is kept "
    "and flagged. Nothing is linked, matched or created from this yet: no person item, no identity and no link. It is "
    "kept on the item as data, not searched, as raw material for a later feature that turns them into people (spec Q21)."
)
FIXED.update({
    "People mentioned, on an item's page": PEOPLE_MENTIONED,
    "People mentioned, in the X-ray step": PEOPLE_MENTIONED,
    "Unattributed identifiers, under People mentioned": (
        "Emails, phones and handles in the item's text that are not plainly one person's, such as an address "
        "several people read or a general mailbox, each with the quote it came from and why. They are kept apart "
        "so that none is ever guessed onto someone. Like the people above, nothing is linked or created from them "
        "yet (spec Q21)."
    ),
    "Gold people for Evaluate": (
        "What a right reading of this item's people should find: each person's name with their emails, phones and "
        "handles, and the identifiers that belong to nobody for sure. It is never shown to the X-ray call. Evaluate "
        "compares it with what the X-ray stored, by name and by identifier."
    ),
    "People mentioned: extraction against gold people, in Evaluate": (
        "How well the X-ray call reads the people an item's text names, over every item given gold people. "
        "Precision is the share of what it found that is right; recall is the share of what was expected that it "
        "found. By name, a person counts when the first name matches, and the last name too when both have one. "
        "By identifier, an email, phone or handle counts when it is on the right person, or left unattributed when "
        "the gold leaves it so. No model call is made here; it only compares what is stored."
    ),
})


# Silos (`rouh/silos.py`): the label on every item, in the Items table and on an item's page.
FIXED["silos"] = (
    "Which of the owner's silos the item is in: one, several, or none yet. The silos are the owner's own, set "
    "in Rouh's Settings, Silos (Work and Personal to start with), and it is set per item, never per person.\n\n"
    "Where it comes from, strongest first: the owner's own word (a press here, a contact's card, or telling Rouh "
    "\"that's family\"), which nothing changes after; then where the item comes from, worked out by code from the "
    "source rules in Settings, Silos: a task takes its project's silo and everything inside a task takes the "
    "task's, an event takes its calendar's, a meeting its event's, an email its sender's, domain's, contact's or "
    "inbox's, a contact the rules on their addresses and the owner's own words on them; then the X-ray call, "
    "which reads the rest in the call it already makes, choosing from the owner's silos. In none hands it back "
    "to those.\n\n"
    "What it changes: questions can search one silo first (silo on synapse_query and synapse_find). Somebody "
    "using Rouh on the owner's behalf sees only some silos, Work unless they were given more: for them an item "
    "in none of their silos, and anything in no silo, special or unlabelled, is never found, by search, by a "
    "link, by its id or through an explanation."
)


# The recalibration a night makes before its idea when Synapse's code changed (`rouh/synapse/recalibrate.py`), on an
# attempt's page in the Improvements lab. Written here: a model reading these headings cold guesses wrong.
RECALIBRATED = (
    "Synapse's code had changed since the last night whose answers were graded, so before trying its idea the night "
    "first set a fresh starting point to judge the idea against. It ran the new code and the last graded code side by "
    "side on the 103 test questions, without grading (free, about a minute). When both found exactly the same memory "
    "for every question, the change is off the test's path and the last graded figures still hold, so they are carried "
    "over and nothing extra is spent. When the memory differs, the current code is graded once afresh (about $3.50) "
    "and that is the starting point. Either way the night then goes on to try its idea."
)
FIXED.update({
    "Recalibrated first": RECALIBRATED,
    "The recalibration did not hold up": (
        "The night set out to recalibrate because Synapse's code had changed, and what it measured looked wrong: a "
        "question failed, something leaked to someone who may not read it, the same code found different memory from "
        "one run to the next, or the share of the right memory found fell far below the last graded night. Nothing is "
        "judged against figures like that, so no idea was tried; the row says what was wrong. " + RECALIBRATED
    ),
    "Memory found": (
        "Whether the new code and the last graded code found the same memory for each of the 103 test questions: the "
        "same items the right answer needs, packs of the same size, and the same leaks. A question whose memory changes "
        "between two runs of the very same code (a tie between two items) is left out and counted. The same memory means "
        "the code change cannot have moved the graded figures, so they are carried over."
    ),
})

def fixed_text(label: str) -> str:
    """The fixed explanation of a label, if it has one, whatever the label's case."""
    return FIXED.get(label) or FIXED.get(label.lower()) or ""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text"],
          "properties": {"text": {"type": "string"}}}

_docs_lock = threading.Lock()
_docs: dict = {"key": None}


def _find(root: str, ending: str) -> str:
    """The first file under the workspace whose name ends so, or ''."""
    if not root or not os.path.isdir(root):
        return ""
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "source-code"))
        for name in sorted(files):
            if name.endswith(ending):
                return os.path.join(folder, name)
    return ""


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _workspace() -> str:
    from ..config import config
    return getattr(config, "assistant_repo", "") or ""


def documents() -> str:
    """The long, fixed part every explanation reads, the same on every call."""
    root = _workspace()
    with _docs_lock:
        if _docs["key"] != root:
            _docs["spec"] = _find(root, SPEC_NAME)
            _docs["built"] = _find(root, BUILT_NAME)
            _docs["key"] = root
        parts = []
        for title, path in (("THE PAGE'S OWN CODE (rouh/static/synapse.js)", PAGE_CODE),
                            ("THE NUMBERS IT WORKS BY (rouh/synapse/numbers.py)", NUMBERS_CODE),
                            ("HOW THE LAB WAS BUILT, AND WHERE IT DIFFERS FROM THE SPEC (85-02)", _docs["built"]),
                            ("THE DESIGN SPEC (85-01)", _docs["spec"])):
            text = _read(path) if path else ""
            if text:
                parts.append(f"===== {title} =====\n{text}")
        return "\n\n".join(parts)


def _clip(text, n: int) -> str:
    return " ".join(str(text or "").split())[:n]


def key_of(label: str, place: str) -> str:
    return hashlib.sha256(f"{place}\n{label}".encode()).hexdigest()[:32]


def _history(before: list[str], asks: list[str]) -> str:
    """The explanations read so far, each followed by what he said about it, if anything."""
    lines = []
    for i, b in enumerate(before):
        lines.append(f"Explanation {i + 1}: {b}")
        # asks[i + 1] is what he said about explanation i + 1, which brought the next one.
        if i + 1 < len(asks) and asks[i + 1]:
            lines.append(f"He said about it: {asks[i + 1]}")
    return "\n\n".join(lines)


def _ask(label: str, place: str, hint: str, before: list[str], owner: dict,
         asks: list[str] | None = None, question: str = "") -> tuple[str, str]:
    from .. import modeldefaults

    # The Models page's model for Synapse's helper, now (`numbers.MODEL_USES`).
    model = modeldefaults.use_model("synapse_helper", (owner or {}).get("org_id") or None)
    lines = [f"Label: {label}", f"Where it is: {place or 'the Synapse page'}"]
    if hint:
        lines.append(f"What the page says beside it: {hint}")
    text = "\n".join(lines)
    if question:
        text += "\n\n" + _history(before, asks or []) + f"\n\nWhat he says now: {question}\n\n" + ASKED
    elif before:
        text += "\n\n" + REWRITE + "\n" + _history(before, asks or [])
    got = ai.generate(model=model, instructions=INSTRUCTIONS + "\n" + documents(), text=text, schema=SCHEMA,
                      name="synapse_explanation", purpose="explain", max_tokens=2000,
                      owner=owner, timeout=120.0)
    words = " ".join(str(got.get("text") or "").replace(EM_DASH, " - ").split())
    if not words:
        raise RuntimeError("the model wrote nothing")
    return words, str(got.get("_model") or model)


def explain(person, label: str, place: str = "", hint: str = "", before: list | None = None,
            asks: list | None = None, question: str = "") -> dict:
    """An explanation of a label in a place: the kept one, a fresh rewrite when `before` is given,
    or one built around `question`, what he said about the last of `before`.

    `asks[i]` is what he had said that brought `before[i]`, '' where it was the first or a 🤷‍♂️.
    """
    label, place, hint = _clip(label, MAX_LABEL), _clip(place, MAX_PLACE), _clip(hint, MAX_HINT)
    question = _clip(question, MAX_QUESTION)
    if not label:
        return {"ok": False, "why": "Nothing to explain."}
    fixed = fixed_text(label)
    if fixed and not before:
        return {"ok": True, "text": fixed, "kept": True}
    if fixed:
        hint = "What is true of it, which the rewrite must keep and must not contradict: " + fixed
    pairs = [(_clip(b, 1500), _clip(a, MAX_QUESTION)) for b, a in
             zip(before or [], list(asks or []) + [""] * len(before or [])) if str(b or "").strip()][-6:]
    before = [b for b, _ in pairs]
    asks = [a for _, a in pairs]
    if question and not before:
        return {"ok": False, "why": "There is no explanation yet to ask about."}
    org, user = str(person.org_id), str(person.user_id)
    key = key_of(label, place)
    if not before:
        kept = db.row("SELECT text FROM synapse.explanation WHERE org_id = %s AND key = %s", (org, key))
        if kept:
            return {"ok": True, "text": kept["text"], "kept": True}
    if not ai.have_key():
        return {"ok": False, "why": "This machine has no OpenAI key, so there is nobody to write an explanation."}
    try:
        text, model = _ask(label, place, hint, before, {"org_id": org, "user_id": user}, asks, question)
    except Exception as exc:  # noqa: BLE001
        log.warning("Synapse could not explain %r in %r: %s", label, place, exc)
        return {"ok": False, "why": f"The explanation could not be written: {type(exc).__name__}: {exc}"}
    if not before:
        db.run("INSERT INTO synapse.explanation (org_id, key, label, place, text, model) "
               "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (org_id, key) DO NOTHING",
               (org, key, label, place, text, model))
        kept = db.row("SELECT text FROM synapse.explanation WHERE org_id = %s AND key = %s", (org, key))
        text = kept["text"] if kept else text
    return {"ok": True, "text": text, "kept": not before}
