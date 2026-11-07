"""Every point accounted for: a job asked to apply several comments or changes goes through them
one by one, and its report ends with what became of each.

Built by the nightly feature run, night 26, 29 October 2026 (task 94). On 28 October 2026 a job
updated the explainer in task 148 with a reviewer's comments and reported "every comment
applied". When ‹he› asked again, the next job went through them one by one against the page as
it was: two of fourteen had been done. The same afternoon a job's report left out the third of
three changes ‹he› had asked for ("everything is too dark"), and Rouh had to ask the job again.
A list of points is where a report says "done" for the whole and means most of it.

So, while its switch is on, a job started for the person (`tools._started`) whose request, or
the person's own words in that turn, asks for comments, feedback or a review to be applied, or
gives three or more numbered or bulleted changes, has a short section put after its brief
(`RULE`): go through the points one at a time, check each against the result as it is now, and
end the report with one line per point, in the order given, saying Done, Partly or Not done and
why. Nothing is drawn on any screen.

**No model call.** The request is read by code (`asks_for_points`).

**Whose.** The run's own brief, for the organisation of whoever is speaking.

**Its switch** is `each_point` (`rouh/switches.py`): off, no run is told.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("rouh.each_point")

SWITCH = "each_point"
TITLE = ("Every point accounted for: a job asked to apply several comments or changes goes "
         "through them one by one and ends with each one, done or not")
HEADING = "## Every point accounted for"
RULE = (
    "This asks for several things to be applied: comments, feedback, a review, or a list of "
    "changes. Find every one of them first, and say how many there are and where they came "
    "from. Then go through them one at a time. Before you finish, check each one again against "
    "the result as it is now, not as you remember changing it. End your report with one line "
    "per point, in the order they were given: the point in a few words (and whose it is, when "
    "it is somebody's comment), what was there before, what is there now, and Done, Partly or "
    "Not done, with why for anything not done. Never write \"all done\" or \"every comment "
    "applied\" without those lines. If a point cannot be found where you were told to look, say "
    "where you looked.")

#: The words that say the points are somebody's comments or feedback.
_POINTS = re.compile(
    r"\b(comments?|feedback|review(?:er)?'?s?|remarks|notes from|corrections|suggestions|"
    r"коментар\w*|забележк\w*|обратна\s+връзка|корекци\w*)\b", re.I)
#: The words that ask for them to be applied.
_APPLY = re.compile(
    r"\b(apply|applied|update|fix|address|implement|incorporate|go through|as per|according to|"
    r"take (?:in|into account)|work in|make the changes|change|приложи|отрази|оправи|направи|"
    r"съобрази)\w*", re.I)
#: A line of a list: "1.", "2)", "-", "*", "•".
_ITEM = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+\S", re.M)


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def asks_for_points(words: str) -> str:
    """Why these words ask for several points to be applied ("comments", "list"), or ""."""
    text = str(words or "")
    if not text.strip():
        return ""
    for got in _POINTS.finditer(text):
        near = text[max(0, got.start() - 160): got.end() + 160]
        if _APPLY.search(near):
            return "comments"
    if len(_ITEM.findall(text)) >= 3:
        return "list"
    return ""


def with_rule(brief: str, who=None) -> str:
    """The brief, with `RULE` after it when it, or the person's own words in this turn, ask
    for several points to be applied and the switch is on; else the brief as it was."""
    try:
        if HEADING in brief:
            return brief
        if who is None:
            from .tenancy import speaker

            who = speaker()
        if who is None or not on(getattr(who, "org_id", None)):
            return brief
        asked = ""
        try:
            from . import turntrace

            trace = turntrace.current()
            asked = str(getattr(trace, "asked", "") or "") if trace is not None else ""
        except Exception:  # noqa: BLE001 - the brief alone is read
            asked = ""
        # A list in the brief alone is how a model writes any brief; only the person's own list
        # counts, while comments to apply count wherever they are asked for.
        why = asks_for_points(asked) or ("comments" if asks_for_points(brief) == "comments" else "")
        if not why:
            return brief
        from . import evolution

        evolution.used(SWITCH, "told", who=who,
                       detail=f"a job asked to apply several points ({why}) was told to account for each")
        return f"{brief.rstrip()}\n\n{HEADING}\n\n{RULE}"
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("every point accounted for could not be put in a run's brief")
        return brief


__all__ = ["HEADING", "RULE", "SWITCH", "TITLE", "asks_for_points", "on", "with_rule"]
