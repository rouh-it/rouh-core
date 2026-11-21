"""Say it more simply: one press under an answer asks for it again in plain words.

Built by the nightly feature run, night 50 of the ledger (21 November 2026, task 94), for the
person's guidance that half of what is built makes Rouh easier for somebody using it for the
first time, technical or not.

An answer that uses words somebody new does not know - a term, an abbreviation, a name of one of
Rouh's own parts - is put right only by asking, and somebody new to Rouh, or not technical, does
not know they may, or how to say it. The person this Rouh belongs to asks for plain words often
enough to have a rule about it.

So, while its switch is on, every answer in a conversation has one more button beside Read this
aloud: Say it more simply. Pressed, it puts one message in the box, in the person's name, naming
the answer by its first words (`ASK`), and sends it the way Send does: the answer comes back
shorter and in plain words, through the conversation's own model, like any message. Nothing else
is asked of a model and nothing is kept; the press is counted (`POST /api/say-plainer`).

**Its switch** is `say_plainer` (`rouh/switches.py`): off, there is no such button.
"""
from __future__ import annotations

SWITCH = "say_plainer"
TITLE = "Say it more simply: one press under an answer asks for it again in plain words"

#: The message the button sends; `{start}` is the answer's first words.
ASK = ("Say your answer that starts \"{start}\" again more simply: shorter, in plain words, and "
       "explain in a few words any term somebody new to this would not know.")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def for_page(who) -> dict:
    """What the page needs: whether it is on, and the words the button sends."""
    return {"on": on(who), "ask": ASK}


def pressed(who) -> None:
    """Say it more simply pressed under an answer: its use."""
    from . import evolution

    evolution.used("say_plainer", "pressed", who=who, detail="")
