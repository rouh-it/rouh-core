"""Claude says whether the person has finished, before it answers.

Deciding the end of a turn from the sound of the voice alone does not work for
somebody who dictates slowly. A sentence that sounds finished ends the turn
even when the person is in the middle of a thought, and a pause for thought is
three to five seconds long. Live on 13 September 2026, "Start a new task." was
called finished a second into such a pause, and so were "... Garden." and
"... the back garden.": one request, six fragments, and every answer started too
early.

So the model reads the words and says. Every reply starts with exactly one of
three characters, and only a finished question is answered. After either of the
other two nothing is said, nothing is shown, nothing is stored, and what the
person says next joins the same question.

The mark is the first token of the answer the model was going to write anyway,
so a finished question costs no extra request and no time anyone would notice.
An unfinished one costs one request that is thrown away.

The three characters are the ones Pipecat used, kept on purpose: they are
single codepoints no model writes by accident, and the conversations already
stored are full of them.
"""
from __future__ import annotations

#: Finished. The reply follows the mark.
FINISHED = "\N{BLACK CIRCLE}"                       # U+25CF
#: Cut off in the middle of a sentence, a list or a phrase.
CUT_OFF_MID_THOUGHT = "\N{CIRCLE WITH LEFT HALF BLACK}"   # U+25D0
#: Announced but not yet said, or thinking out loud.
STILL_THINKING = "\N{WHITE CIRCLE}"                 # U+25CB

#: Every mark the model may write. None of them is ever shown, spoken or stored.
MARKS = (FINISHED, CUT_OFF_MID_THOUGHT, STILL_THINKING)

#: Seconds to wait after "cut off mid-thought" before answering what there is.
#: Pipecat's own default was 5, and a person who pauses three to five seconds to
#: think would be answered in the middle of the next thought. Twenty leaves room
#: for two long pauses, and for the transcript of the last words to land.
CUT_OFF_WAIT = 20.0

#: Seconds to wait after "still thinking". Longer, because the person has only
#: said what they are about to say ("Start a new task.") or is deliberating out
#: loud, and the thing itself has not started yet.
THINKING_WAIT = 30.0

#: How a message from Rouh's own software starts, so that it can never be
#: mistaken for the person's words, by the model or by the code that joins what
#: the person says into one question.
NOTE = "[A note from Rouh's own software, not the person:"

#: What the model is told when the wait runs out, or when the person has pressed
#: send or Finish: answer what there is. No "go ahead", no "take your time" - a
#: person who has stopped talking is not asked to start again.
ANSWER_NOW = (
    f"{NOTE} the person has finished for now.] "
    f"Answer what they have said so far, as a finished request, as well as you can. "
    f"Start your reply with {FINISHED} and a space. "
    "Do not mention the pause, do not say you were waiting, and do not ask them to go on."
)

# What the model is told about the marks is the rule "turn-marks" on the Rules page, a rule of the person's
# that a new Rouh starts with (`rouh/rule_defaults_fallback.json`), filled in with the three marks above, so the
# words and the parser can never name different characters. Until 21 October 2026 it was `INSTRUCTIONS`, here.
# Turned off, the parser still reads a reply as finished when it starts with no mark.


class Unfinished(Exception):
    """The person had not finished asking, so the turn was abandoned.

    Raised out of a turn that read `\N{CIRCLE WITH LEFT HALF BLACK}` or
    `\N{WHITE CIRCLE}` off the front of the reply. Nothing was said, nothing
    was shown and nothing was stored: the question the turn was started with is
    still the question, and whatever the person says next joins it.
    """

    def __init__(self, mark: str):
        super().__init__(f"the person had not finished ({mark})")
        self.mark = mark

    @property
    def wait(self) -> float:
        """How long to leave them before answering what there is anyway.

        Read here rather than kept on the exception so that the two numbers
        above are the only place either of them is written down.
        """
        return THINKING_WAIT if self.mark == STILL_THINKING else CUT_OFF_WAIT


class Reading:
    """The front of a reply, held back until its mark can be read.

    Every piece of the stream goes in and what comes out is what may be shown
    and spoken. Nothing comes out until the first character that is not a space
    has arrived, because that character is the mark - or is the proof that
    there is no mark at all, which is answered exactly like a finished one. One
    character is enough, so the holding back is over within the first token and
    costs nothing anybody could hear.

    A reply that is nothing but whitespace never decides and never releases it,
    which is right: there is nothing there to say.
    """

    def __init__(self) -> None:
        #: Which mark the reply started with, once it is known. None means
        #: either "not yet" or "there was not one"; `decided` tells them apart.
        self.mark: str | None = None
        self.decided = False
        self._held = ""
        self._owed_space = False

    def take(self, piece: str) -> str:
        """Add a piece of the stream, and give back what may be released."""
        if self.decided:
            if self._owed_space:
                self._owed_space = False
                if piece[:1] == " ":
                    return piece[1:]
            return piece
        self._held += piece
        front = self._held.lstrip()
        if not front:
            return ""                      # nothing but space: still no mark
        self.decided = True
        self._held = ""
        if front[0] not in MARKS:
            return front                   # no mark at all: answered as finished
        self.mark = front[0]
        rest = front[1:]
        # "Write the mark, a space, then your full reply": that space belongs
        # to the mark and not to the answer. It almost never arrives in the
        # same piece as the mark, so the reader remembers that it is owed one.
        if rest[:1] == " ":
            return rest[1:]
        if not rest:
            self._owed_space = True
        return rest

    @property
    def unfinished(self) -> bool:
        """Did the model say the person had not finished asking?"""
        return self.mark in (CUT_OFF_MID_THOUGHT, STILL_THINKING)


def strip_marks(text: str) -> str:
    """The text with every turn mark taken out."""
    for mark in MARKS:
        text = text.replace(mark, "")
    return text


def is_note(message) -> bool:
    """A message Rouh's own software put in the conversation, not the person."""
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text") or "" for b in content if isinstance(b, dict))
    return isinstance(content, str) and content.lstrip().startswith(NOTE)
