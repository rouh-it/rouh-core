"""Where decisions come from, and where their answers go back to (`rouh/decisions.py`).

One adapter per part of Rouh that asks the person something. Each one says three things and
does one:

- `collect(who)`: what it asks now, each as a `decisions.Ask`, or None when it cannot be read
  this time (the one program not connected, no workspace), which leaves its questions alone.
- `settled(who, row)`: what became of a question it no longer asks: answered at the source
  (its own page, Telegram, the terminal), dismissed there, or simply not asked any more.
- `apply(who, row, channel)`: carry the answer out, through the source's own way of being
  answered, which is the only thing that knows what an answer does there. Awaited by the
  desk once the answer's window to be undone has passed.
- and, where the source has the idea, `dismiss(who, row)`: close it without an answer.

The adapters keep no state of their own and never decide anything: the source decides what
an answer means, and `decisions.answer` has already checked that it is an answer at all and
that its risk was confirmed. What runs inside Rouh's process - a turn in a task's chat, the
heartbeat, the one program's socket, the timekeeper, the conflict desk - is handed to them by
the runtime through `hooks`, so this file can be read and checked without any of it running.

The sources, in the order the Decisions page groups them:

- **task** - a task waiting on the person, or a finished one that still asks something: the
  question in its meta, else the passage in its notes (`waiting.py`); an answer goes
  into the task's chat as his own words, and Rouh hands it to a job (`brain.WAITING`), the
  same as from the task's own page, which records it (`answering.record`).
- **goal** - a goal step whose part for him is a decision (`goals.KINDS`): the choice is
  written into the step and the step is marked complete by him, which starts what follows.
- **approval** - the heartbeat's and the quests' approval queue (`heartbeat.py`): yes runs
  exactly what was queued, no runs nothing; his own words are a no with his words passed on.
- **run** - a run of the one program asking leave, or posing a choice (`one/questions.py`).
- **job** - a background job stopped at its prompt, or on a step it handed to the live
  browser (LIVE BROWSER NEEDED, `browser_handoff.py`): his words go to its prompt
  (`reply_to_task`).
- **conflict** - a landing that collided, with its four fixed choices (`conflicts.py`).
- **dream** - a night of Synapse's dreaming's changes of one kind, left for his Approve or
  Reject, as one decision holding them (`synapse/dreaming.py`): all at once or one by one,
  each decided as on the Dreams page, where it can be undone.
- **meeting** - the guests of a meeting within a day whom Rouh could not be sure of on
  LinkedIn, one question for the meeting (`meeting_people.py`): the profile he names is
  harvested and kept on that guest's contact.
- **after_meeting** - the work a meeting he just had calls for, read from its notes in the
  meeting library (`meeting_next.py`): Start begins a run briefed with the meeting, filed in
  the task named; Not needed drops it.
- **mail** - an email or a Telegram message from somebody else waiting for his yes
  (`mail_cases.py`), with what the yes does as A, the reply that goes at once, B, the
  action, and C, the reply with the result: approve and decline go through the case's own
  decision (`CaseDesk.decide`), bound to exactly what he was shown.
- **genes** - every gene the nightly run built that waits on his answer, each a decision of
  its own that opens the gene's page in Mutations, where it is answered (`rouh/evolution.py`).
- **promise** - a promise made to him in Slack that is late, with nothing since to show it kept
  (`slack_promises.py`): Chase, which posts a nudge as Rouh's bot on his yes, Wait, or Drop. One a
  later message showed kept closes by itself, with Undo in the history. His own promises are
  never here: they are Clockwork reminders, because a promise is a deadline until it is late.
- **casefix** - a run fixing the check behind a step he marked a false alarm that failed,
  or that would have had to loosen a safety rule (`case_fixes.py`): Try again starts a new
  fix run with his words, Leave it closes it.

And each says whether its questions may reach the person at all (`gate`, `rouh/decision_gate.py`,
Petar, 18 October 2026): only when work he asked for truly stopped without him and the answer
is his to give. What can be told by code is told here; a task's question and a goal step's
decision are read by the gate's judge.

Each also counts what it asks at the source itself (`census`) and says why something it
counts has no open decision (`why_not`), which is what `manage.py decisions_migrate`
reports before and after.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from . import decisions, owner
from .decisions import Applied, Ask, Settled


def _status(ask: dict) -> str:
    """A mail ask's status as it is now: rows written before 20 October 2026 said
    "waiting_for_petar" where they now say "waiting_for_owner"."""
    return str(ask.get("status") or "").replace("_petar", "_owner")

log = logging.getLogger("rouh.decision_sources")


class Hooks:
    """What the runtime lends the adapters. None until the runtime sets it."""

    #: async (folder, text) -> (chat id, chat title): his answer said in the task's chat.
    deliver_task = None
    #: The live heartbeat (`heartbeat.LIVE`).
    heartbeat = None
    #: async (question id, "yes"|"no") -> (answer, why not)
    one_answer = None
    #: () -> the one program's open questions, or None when it is not connected.
    one_questions = None
    #: The timekeeper, for a goal step marked complete.
    keeper = None
    #: async (conflict id, n) -> {"ok", "why", ...}
    conflict_answer = None
    #: The runtime's config, for the conflict records' place.
    cfg = None
    #: async (run id, words) -> what the job said: his words typed into a job's prompt
    #: (`tools.reply_to_task`).
    reply_to_task = None
    #: () -> the mail cases' desk (`mail_cases.CaseDesk`), or None when new mail is not
    #: handled on this server.
    mail_desk = None


hooks = Hooks()


class Source:
    kind = ""
    label = ""
    #: Its chip on a decision's line: where it came from, in a word or two.
    tag = ""
    #: Whether its `link` is the item's own page, where the decision is answered in full: a
    #: line opens it. One without such a page opens the decision's own, `/decisions/<number>`.
    own_page = False
    #: Whether it can be closed without an answer.
    can_dismiss = False
    #: Whether his own words are acted on (handed to a job that may carry the risk out),
    #: so a gated question answered in words needs that risk confirmed too.
    text_acts = False
    #: Whether the source tells his phone itself, so the desk does not tell it twice.
    notifies = False
    #: Whether its questions are about a date - a promise that is late - so a date in them that
    #: has passed never makes one probably stale (`decisions.stale_reasons`).
    dated = False

    def collect(self, who) -> list[Ask] | None:
        raise NotImplementedError

    def census(self, who) -> dict[str, str] | None:
        """What this source asks now, counted at the source itself and not through the
        decisions: {its own id for it: one line}, or None when it cannot be read. What the
        migration counts before and after (`manage.py decisions_migrate`)."""
        asks = self.collect(who)
        return None if asks is None else {a.source_id: a.title for a in asks}

    def why_not(self, who, source_id: str) -> str:
        """Why something the census counts has no open decision."""
        return "it no longer waits on you"

    def settled(self, who, row) -> Settled | None:
        return None

    async def apply(self, who, row, channel: str) -> Applied:
        raise NotImplementedError

    def dismiss(self, who, row) -> str:
        raise decisions.Refused("This one cannot be dismissed.")

    def can_reopen(self, row) -> bool:
        """Whether a question it closed by itself can be opened again (`decisions.reopen`)."""
        return False

    def reopen(self, who, row) -> str:
        raise decisions.Refused("That cannot be undone now.")

    # --- the gate (`rouh/decision_gate.py`) ---------------------------------------------------

    def gate(self, who, ask):
        """Whether this question may reach the person at all, where code can tell: a
        `decision_gate.Verdict`, or None to have the gate's judge read it. A source that says
        nothing is read by the judge, so nothing new floods him by default."""
        return None

    def background(self, who, ask) -> str:
        """What the judge is told about the work a question came from, beyond its own words."""
        return ""

    def on_cleared(self, who, ask, verdict) -> None:
        """The gate kept this question from him: let go of it at the source, where the source
        holds it in a way the person sees (a task left waiting). Called again whenever the source
        asks it again, so it must be safe to repeat."""

    def on_reopened(self, who, row) -> str:
        """He opened again what the gate cleared: ask it again at the source. What to say."""
        return "Open again, and waiting on you."


def _owner(who) -> bool:
    """Whether `who` is the person the workspace is for: tasks, goals, runs and landings
    are the install's, and asked of its owner (`telegram.phone_owner`), never of a guest
    or a second account."""
    from . import telegram
    from .tenancy import Tenancy

    try:
        owner = telegram.phone_owner(Tenancy())
    except Exception:
        log.exception("decisions: whose workspace this is could not be read")
        return False
    return owner is not None and str(owner.user_id) == str(who.user_id) \
        and str(owner.org_id) == str(who.org_id)


def _delegate_said(row) -> str:
    """A delegate's answer, said as theirs and never as the owner's (`rouh/delegation.py`): their
    name, the answer, and their own words as they wrote them. "" for his own answer."""
    if not str(row.answered_by or "").startswith("delegate:"):
        return ""
    got = row.answer or {}
    name = got.get("by_name") or "The person ‹owner› gave authority over this"
    words = got.get("words") or ""
    return (f"{name}, who decides for this by ‹owner›'s grant, answered: {got.get('said') or ''}"
            + (f"\nTheir words: \u201c{words}\u201d" if words else ""))


def _silo_of(folder: str) -> str:
    """The project inside the top-level one a task's folder sits in ("clients" in
    work/clients/90-...), for a decision's line, or "" for a task right under the top."""
    parts = [p for p in str(folder or "").strip("/").split("/") if p]
    if len(parts) < 3:
        return ""
    return re.sub(r"^\d+[-.]\s*", "", parts[1]).replace("-", " ").strip().capitalize()


def _yes_from(options, recommended: str, then: str = "", note: str = "") -> str:
    """What a yes does, from what the source already says: the recommended answer and what it
    means, else what an answer does (`then`); and the risk in plain words when there is one.
    "" when none of them says it, which the gate refuses (`decisions.missing_line`)."""
    rec = next((o for o in options or [] if o.get("id") == recommended), None)
    said = ""
    if rec is not None and rec.get("detail"):
        said = f"{rec['label']}: {str(rec['detail']).rstrip('.')}."
    elif then:
        said = str(then).strip()
    if said and note and note.rstrip(".").lower() not in said.lower():
        said = said.rstrip(".") + ". " + note.rstrip(".") + "."
    return said


def _project_of(folder: str) -> str:
    top = str(folder or "").strip("/").split("/", 1)[0]
    return {"work": "Work", "personal": "Personal", "rouh": "Rouh",
            "private": "Personal"}.get(top.lower(), top.replace("-", " ").title() if top else "")


# --- tasks -------------------------------------------------------------------------------


class TaskSource(Source):
    kind = "task"
    label = "Task"
    tag = "Task"
    own_page = True
    can_dismiss = True
    text_acts = True

    def _rows(self):
        from . import owning

        st = owning.store()
        root = owning._workspace()
        if st is None or not root:
            return None, None, ()
        return st, root, [t for t in st.list_tasks(limit=None)
                          if t.state in ("waiting", "done") and t.folder
                          and not str(t.folder).startswith("_")]

    def collect(self, who) -> list[Ask] | None:
        from . import addressing, answering, goals, waiting
        from .models import User

        if not _owner(who):
            return None
        st, root, rows = self._rows()
        if st is None:
            return None
        names = waiting.names_of(User.objects.filter(pk=int(who.user_id)).first())
        out = []
        asked = {}
        found = []
        metas = goals.metas_at(t.folder for t in rows)
        for t in rows:
            folder = str(t.folder)
            meta = metas.get(folder.strip("/"))
            if meta is None:
                meta = goals._meta(Path(root) / folder)
            if isinstance(meta.get("goal_step"), dict):
                continue              # a goal step's part is the goal source's
            if t.state == "done" and not isinstance(meta.get("question"), dict):
                continue              # finished, and asking nothing: the common case, read once
            question, notes, line = answering.asked_of(root, folder, names)
            if t.state == "done" and question is None:
                continue
            asked[t.id] = line
            found.append((t, folder, question, notes, line, meta))
        said = answering.answers_to(asked)
        for t, folder, question, notes, line, meta in found:
            if t.id in said:
                continue              # answered or dismissed on its page; the job has it
            shape = (meta.get("question") if isinstance(meta.get("question"), dict) else {})
            opts = [{"id": f"o{i + 1}", "label": o.label, "detail": o.detail}
                    for i, o in enumerate(question.options)] if question else []
            ask = (question.ask if question and question.ask else
                   notes.line if notes else
                   "It is marked as waiting on you, and its notes do not say what for.")
            if not question and not notes:
                opts = [{"id": "find", "label": "Find out what it needs",
                         "detail": "A job reads its notes and asks you properly."}]
            rec = str(shape.get("recommended") or "").strip().lower()
            rec_id = next((o["id"] for o in opts if o["label"].lower() == rec), "")
            risk = str(shape.get("risk") or "reversible")
            number = f"Task {t.number}" if t.number else "A task"
            prepared = [{"label": "Its notes", "href": _doc(folder, waiting.NOTES)}]
            if notes and notes.markdown:
                prepared.append({"label": "What its notes say", "text": notes.markdown[:1500]})
            then_said = question.then if question and question.then else ""
            stopped = t.state == "waiting"
            out.append(Ask(
                source_id=t.id, key=decisions.key_of(t.id, line),
                # What it is: the task, and what it asks, in its own words.
                title=(f"{number}, {t.title}" if t.title and t.number else t.title or number)
                + (f": {question.ask}" if question and question.ask else ""),
                question=ask,
                why=str(shape.get("why") or "")[:1200],
                then=(question.then if question and question.then else
                      "Your answer goes into the task's chat, and Rouh hands it to a job that "
                      "writes it into the task and carries it on."),
                link=addressing.url_for("task", t.id, folder),
                context=f"{number} · {t.title}" if t.title else number,
                project=_project_of(folder), batch=f"task:{t.id}",
                options=opts, recommended=rec_id,
                recommended_why=str(shape.get("recommended_why") or shape.get("because") or ""),
                allow_other=True,
                answer_type="multi" if question and question.several else "choice",
                urgency=("whenever" if t.state == "done" else
                         str(shape.get("urgency") or "soon")),
                risk=risk, risk_note=str(shape.get("risk_note") or ""),
                prepared=prepared + _prepared(shape), asked_at=_touched(t),
                history=_task_history(t.id),
                yes_does=_yes_from(opts, rec_id, then_said, str(shape.get("risk_note") or "")),
                wait_cost=(f"{number} is stopped until you answer." if stopped else
                           f"Nothing waits on it: {number.lower()} is finished."),
                blocks=stopped, tags=[_silo_of(folder)],
                advice=str(shape.get("recommended") or "") if not rec_id else "",
                # A question its job marked a hands-on step only he can do (`rouh/actions.py`,
                # the agent instructions' "Waiting tasks and their questions"): an action, with
                # whatever its job said of it; else read once.
                kind=("action" if str(shape.get("kind") or "").lower() == "action" else
                      "decision" if str(shape.get("kind") or "").lower() == "decision" else ""),
                action=({"do": shape.get("ask") or ask, "steps": shape.get("steps") or [],
                         "minutes": shape.get("minutes") or 0,
                         "check": shape.get("check") or "", "after": shape.get("then") or ""}
                        if str(shape.get("kind") or "").lower() == "action" else {})))
        return out

    def census(self, who) -> dict[str, str] | None:
        """Every task marked waiting, and every finished one whose meta still asks."""
        from . import goals

        if not _owner(who):
            return None
        st, root, rows = self._rows()
        if st is None:
            return None
        out = {}
        metas = goals.metas_at(t.folder for t in rows)
        for t in rows:
            meta = metas.get(str(t.folder).strip("/"))
            if meta is None:
                meta = goals._meta(Path(root) / str(t.folder))
            if isinstance(meta.get("goal_step"), dict):
                continue              # counted with the goal steps
            if t.state == "waiting":
                out[t.id] = f"Task {t.number}: {t.title}" if t.number else t.title
            elif isinstance(meta.get("question"), dict):
                out[t.id] = f"Task {t.number} (done, asks): {t.title}" if t.number else t.title
        return out

    def why_not(self, who, source_id: str) -> str:
        from . import answering, goals, owning
        from .models import Task

        task = Task.objects.filter(id=source_id).first()
        if task is None or not task.folder:
            return "the task is gone"
        meta = goals._meta(Path(owning._workspace() or "/-") / task.folder)
        if isinstance(meta.get("goal_step"), dict):
            return "it is a step of a goal: it is taken in as a Goal step decision"
        got = answering.answers_to({task.id: _asked_line(_Q("", str(who.user_id)), task)}).get(task.id)
        if got is not None and got.answer:
            return ("answered on its page; it waits on the job carrying the answer, not on you, "
                    "until that job takes the task off waiting")
        if got is not None and got.dismissed:
            return "dismissed on its page"
        return "it no longer waits on you"

    def settled(self, who, row) -> Settled | None:
        from . import answering
        from .models import Task

        task = Task.objects.filter(id=row.source_id).first()
        if task is None:
            return Settled(decisions.WITHDRAWN, result="The task is gone.")
        rows = (answering.answers_to({row.source_id: _asked_line(row, task)}) if task else {})
        got = rows.get(row.source_id)
        if got is not None and got.answer and not got.dismissed:
            return Settled(decisions.APPLIED, said=got.answer, channel="task page",
                           result="Answered on the task's page.")
        if got is not None and got.dismissed:
            return Settled(decisions.DISMISSED, channel="task page",
                           result="Dismissed on the task's page.")
        return Settled(decisions.WITHDRAWN, result="The task does not ask this any more.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import answering
        from .models import Task

        if hooks.deliver_task is None:
            return Applied(False, "Nothing here can take a task's answer right now.")
        task = await asyncio.to_thread(lambda: Task.objects.filter(id=row.source_id).first())
        if task is None or not task.folder:
            return Applied(False, "The task is not there any more.")
        line = _asked_line(row, task)
        said = (row.answer or {}).get("said") or ""
        number = f"Task {task.number}" if task.number else "This task"
        if (row.answer or {}).get("choice") == ["find"]:
            text = (f"{number} is marked as waiting on me, and its notes do not say what for. "
                    "What does it need from me?")
        else:
            head = (" is done, and it asked me this: " if task.state == "done"
                    else " is waiting on me for this: ")
            text = f"{number}{head}{row.question}\nMy answer: {said}"
            if channel == "telegram":
                text += "\n(Answered on Telegram.)"
            by = _delegate_said(row)
            if by:
                # Not his words: the answer of somebody he gave authority over this task.
                text = f"{number}{head}{row.question}\n{by}"
        chat, title = await hooks.deliver_task(task.folder, text)
        if not chat:
            return Applied(False, "Its chat could not be opened.")
        if (row.answer or {}).get("choice") != ["find"]:
            await asyncio.to_thread(answering.record, task.folder, line, said, chat)
        return Applied(True, f"Sent into the task's chat{', ' + chr(8220) + title + chr(8221) if title else ''}"
                             ", where Rouh hands it to a job that carries the task on.")

    def dismiss(self, who, row) -> str:
        from . import answering
        from .models import Task

        task = Task.objects.filter(id=row.source_id).first()
        if task is None or not task.folder:
            raise decisions.Refused("The task is not there any more.")
        answering.record(task.folder, _asked_line(row, task), "", "", dismissed=True)
        return "Dismissed. Nothing was sent, and the task is left as it is."

    # --- the gate -----------------------------------------------------------------------------

    def gate(self, who, ask):
        from . import decision_gate as gate
        from .models import Task

        task = Task.objects.filter(id=ask.source_id).first()
        if task is None:
            return None
        rec = next((o["label"] for o in ask.options if o.get("id") == ask.recommended), "")
        if task.status == "done":
            # Petar, 18 October 2026: research ends with Rouh's recommendation, never with a
            # follow-up question. A finished task has nothing stopped on him.
            return gate.keep_back("The task is done, so the work it was for is finished and "
                                  "nothing waits on ‹his› answer.",
                                  rec and f"Rouh's recommendation, {rec}.")
        if [o.get("id") for o in ask.options] == ["find"]:
            return gate.keep_back("It is marked waiting and does not say for what.")
        return None

    def background(self, who, ask) -> str:
        from . import instructions, owning
        from .models import Task

        task = Task.objects.filter(id=ask.source_id).first()
        root = owning._workspace()
        if task is None:
            return ""
        lines = [f"Task {task.number}: {task.title}" if task.number else task.title,
                 f"Its status: {task.status}"]
        if task.summary:
            lines.append(f"Its summary: {task.summary}")
        if root and task.folder:
            try:
                notes = instructions.in_folder(Path(root) / task.folder).read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                notes = ""
            if notes:
                lines += ["Its notes (AGENTS.md), from the top:", notes[:4500]]
        return "\n".join(lines)

    def _place(self, task_id: str):
        from . import owning
        from .models import Task

        task = Task.objects.filter(id=task_id).first()
        root = owning._workspace()
        if task is None or not task.folder or not root:
            return None, None
        return task, Path(root) / task.folder

    def on_cleared(self, who, ask, verdict) -> None:
        """Take the question out of the task, where he would still see it: out of its
        meta (kept beside it as `question_cleared`, which Open again puts back), the
        mark in its notes labelled as cleared, and the task out of waiting."""
        from . import goals, instructions, taskmeta, taskrecord

        task, folder = self._place(ask.source_id)
        if task is None or taskmeta.of(task.id) is None:
            return
        meta = goals._meta(folder)
        kept = meta.get("question_cleared") if isinstance(meta.get("question_cleared"), dict) else {}
        changed = False
        if isinstance(meta.get("question"), dict):
            kept = {"question": meta.pop("question")}
            changed = True
        notes_path = instructions.in_folder(folder)
        swaps = _clear_marks(notes_path, _names(who))
        if swaps:
            kept["notes_was"] = (kept.get("notes_was") or []) + swaps
            changed = True
        if meta.get("status") == "waiting":
            kept["status_was"] = "waiting"
            meta["status"] = "done" if verdict.work == "finished" else "in-progress"
            changed = True
        if not changed:
            return
        kept.update(cleared_at=time.strftime("%Y-%m-%d %H:%M"), why=verdict.reason,
                    recommended=verdict.recommendation)
        meta["question_cleared"] = kept
        with taskrecord.acting("Rouh, the decision gate"):
            goals._write_meta(folder, meta)
        log.info("decision gate: task %s let go of its question (%s)", task.number or task.id,
                 meta.get("status"))

    def on_reopened(self, who, row) -> str:
        from . import goals, instructions, taskrecord

        task, folder = self._place(row.source_id)
        if task is None:
            raise decisions.Refused("The task is not there any more.")
        meta = goals._meta(folder)
        kept = meta.pop("question_cleared", None)
        if isinstance(kept, dict):
            if isinstance(kept.get("question"), dict):
                meta["question"] = kept["question"]
            _put_marks_back(instructions.in_folder(folder), kept.get("notes_was") or [])
        if task.status != "done" or (isinstance(kept, dict) and kept.get("status_was")):
            meta["status"] = "waiting"
        with taskrecord.acting(owner.say("‹Owner›, opening a cleared question again", who)):
            goals._write_meta(folder, meta)
        number = f"Task {task.number}" if task.number else "The task"
        return f"Open again: {number} is waiting on you for it."


def _names(who) -> tuple:
    from . import waiting
    from .models import User

    try:
        return waiting.names_of(User.objects.filter(pk=int(who.user_id)).first())
    except Exception:
        return ()


def _clear_marks(path: Path, names) -> list[list[str]]:
    """Every "Waiting on Petar" in a task's notes, labelled as cleared, so nothing reads the
    task as waiting on him any more (`waiting.ask_in` finds that phrase anywhere): the notes'
    own words are kept, and each change is returned as [now, was] so it can be put back."""
    from . import waiting

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    who = "|".join(r"\s+".join(re.escape(p) for p in n.split())
                   for n in (*waiting._called(names), *waiting._ANYONE))
    mark = re.compile(r"\b(waiting on)\b([^.\n]{0,60}?)(?<!\w)(" + who + r")(?!\w)", re.I)
    day = time.strftime("%-d %B %Y")
    swaps: list[list[str]] = []

    def swap(m) -> str:
        lead = "Cleared" if m.group(1)[0].isupper() else "cleared"
        said = f"{lead} by Rouh on {day}, as it did not need {m.group(3)}"
        swaps.append([said, m.group(0)])
        return said

    out = mark.sub(swap, text)
    if swaps:
        path.write_text(out, encoding="utf-8")
    return swaps


def _put_marks_back(path: Path, swaps) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    out = text
    for now, was in swaps:
        if isinstance(now, str) and isinstance(was, str):
            out = out.replace(now, was, 1)
    if out != text:
        path.write_text(out, encoding="utf-8")


def _doc(folder: str, name: str) -> str:
    from . import objectindex

    try:
        return objectindex.doc_url(folder, name)
    except Exception:
        return ""


def _prepared(shape: dict) -> list[dict]:
    """What the asker says it prepared, from `question.prepared` in its meta."""
    out = []
    for p in shape.get("prepared") or []:
        if isinstance(p, str):
            p = {"label": p}
        if isinstance(p, dict) and str(p.get("label") or "").strip():
            out.append({"label": str(p["label"])[:200],
                        **({"href": str(p["href"])[:600]} if p.get("href") else {}),
                        **({"text": str(p["text"])[:1500]} if p.get("text") else {})})
    return out[:8]


def _task_history(task_id: str) -> list[dict]:
    """What was answered or dismissed on this task's page before, to earlier questions."""
    from .models import TaskAnswer

    out = []
    for a in TaskAnswer.objects.filter(task_id=task_id).order_by("created_at")[:20]:
        said = ("Dismissed on the task's page: " if a.dismissed else "Answered on the task's page: ")
        out.append({"at": a.created_at, "kind": "earlier",
                    "detail": said + (a.answer or a.asked)[:400]
                    + (f" (to: {a.asked[:200]})" if a.answer and a.asked else "")})
    return out


def _touched(task) -> float | None:
    return float(getattr(task, "updated_at", 0) or getattr(task, "created_at", 0) or 0) or None


def _asked_line(row, task) -> str:
    """The line an answer is recorded against (`answering.asked_of`), read again now."""
    from . import answering, owning, waiting
    from .models import User

    try:
        names = waiting.names_of(User.objects.filter(pk=int(row.user_id)).first())
    except Exception:
        names = ()
    root = owning._workspace()
    if not root or not task.folder:
        return row.question
    _q, _n, line = answering.asked_of(root, task.folder, names)
    return line or row.question


# --- goal steps --------------------------------------------------------------------------


class GoalSource(Source):
    kind = "goal"
    label = "Goal step"
    tag = "Goal step"
    own_page = True
    text_acts = True

    @staticmethod
    def _waiting(goals, every):
        """Every step of every goal that waits on the person: one marked waiting with
        something asked of him (Rouh did its part, or got stuck), and one whose part for him
        is a decision not yet made."""
        for g in every:
            for s in goals._flat(g["steps"]):
                needs = s.get("needs") or {}
                if s.get("status") == "done":
                    continue
                if (s.get("status") == "waiting" and needs) or (
                        s.get("kind") == "decision" and s.get("your_state") == "todo"):
                    yield g, s, needs

    def _every(self, who):
        from . import goals

        try:
            return goals.listing(who)
        except Exception:
            log.exception("decisions: the goals could not be read")
            return None

    def census(self, who):
        from . import goals

        if not _owner(who):
            return None
        every = self._every(who)
        if every is None:
            return None
        return {(s["folder"] or s["id"]): f"Goal {g.get('number')} step {s['n']}: {s['title']}"
                for g, s, _n in self._waiting(goals, every)}

    def collect(self, who) -> list[Ask] | None:
        from . import goals

        if not _owner(who):
            return None
        every = self._every(who)
        if every is None:
            return None
        out = []
        for g, s, needs in self._waiting(goals, every):
            stuck = needs.get("label") == "Rouh is stuck"
            kind = "decision" if (needs.get("kind") or s.get("kind")) == "decision" else "action"
            ask = (needs.get("words") or s.get("your_words") or s.get("ask") or s.get("left")
                   or s["title"])
            if stuck:
                opts = [{"id": "again", "label": "Try it again",
                         "detail": "Rouh starts the step again, with your words if you give any."}]
                then = "Rouh starts the step again in the background, told what you said."
            elif kind == "decision":
                opts = [{"id": f"o{i + 1}", "label": label} for i, label in
                        enumerate(s.get("options") or [])]
                then = ("Your choice is written into the step, the step is complete, and "
                        "whatever waits on it starts.")
            else:
                opts = [{"id": "done", "label": "Done, mark it complete",
                         "detail": "The step is complete, and whatever waits on it starts."}]
                then = ("The step is complete, and whatever waits on it starts. Your words, if "
                        "you give any, are kept on the step as your note.")
            # Rouh's own addresses for the step and what is in it (`addressing`), which a
            # press opens in Rouh and Cmd opens in a new tab; never a framed page's own.
            here = "/task/" + s["folder"] if s.get("folder") else ""
            prepared = [{"label": f["name"], "href": f"{here}/{f['name']}"}
                        for f in (s.get("prepared") or {}).get("files", [])[:6] if here]
            if here and s.get("explainer"):
                prepared.insert(0, {"label": "What Rouh did, and what is yours",
                                    "href": f"{here}/{goals.EXPLAINER_DOC}"})
            if here and s.get("yours_page"):
                prepared.insert(0, {"label": "How to do it",
                                    "href": f"{here}/{goals.YOURS_DOC}"})
            # What waits on it: the steps set to start once it is done.
            after = [x for x in goals._flat(g["steps"])
                     if (x.get("run") or {}).get("mode") == "after"
                     and (x.get("run") or {}).get("after") == s["id"]
                     and x.get("status") != "done"]
            named = (f"goal {g['number']} step {s['n']}" if g.get("number") else f"step {s['n']}")
            out.append(Ask(
                source_id=s["folder"] or s["id"],
                key=decisions.key_of(s["id"], ask, "stuck" if stuck else kind),
                title=f"{s['title']}, {named}", question=ask,
                why=(s.get("outcome") or "")[:800],
                then=then,
                link=here or ("/task/" + g["folder"] if g.get("folder") else ""),
                context=f"Goal {g['number']} · step {s['n']}" if g.get("number")
                else f"Step {s['n']}",
                project=_project_of(g.get("folder") or ""), batch=f"goal:{g['id']}",
                options=opts, allow_other=True,
                answer_type="choice", urgency="soon", risk="reversible", prepared=prepared,
                history=([{"at": 0, "kind": "raised",
                           "detail": "Rouh did its part and left this for you."}]
                         if s.get("rouh_done") else
                         [{"at": 0, "kind": "raised", "detail": "Rouh stopped on it: "
                           + (s.get("stuck") or "it needs you to unblock it.")}]
                         if stuck else []),
                yes_does=(f"Rouh starts {named} again in the background." if stuck else
                          f"Writes your choice into {named} and marks it complete"
                          + (f", which starts {_steps_words(after)}." if after else ".")
                          if kind == "decision" else
                          f"Marks {named} complete"
                          + (f", which starts {_steps_words(after)}." if after else ".")),
                wait_cost=(f"{_steps_words(after).capitalize()} wait{'s' if len(after) == 1 else ''} "
                           "on it." if after else
                           f"{named.capitalize()} is stopped until you answer." if stuck else
                           "Nothing waits on it."),
                blocks=bool(after) or stuck, tags=[g.get("title") or ""],
                # A step only he can do is an action (`rouh/actions.py`); a choice, or Rouh
                # stuck and asking whether to try again, is a decision.
                kind="decision" if stuck or kind == "decision" else "action",
                action=({} if stuck or kind == "decision" else {
                    "do": ask, "after": ("Marks " + named + " complete"
                                         + (f", which starts {_steps_words(after)}." if after
                                            else ".")),
                    "steps": ([{"text": "Read how to do it, on the step's own page.",
                                "href": f"{here}/{goals.YOURS_DOC}", "link": "How to do it"}]
                              if here and s.get("yours_page") else [])})))
        return out

    def why_not(self, who, source_id: str) -> str:
        return "it no longer waits on you"

    def gate(self, who, ask):
        from . import decision_gate as gate

        if [o.get("id") for o in ask.options] == ["done"]:
            # Petar, 18 October 2026: an action only he can do - a sign-in, a payment, a call -
            # is his by what it is, and the plan stops on it.
            return gate.let_through("A step of the goal only ‹he› can do, and the plan waits on it.")
        return None

    def background(self, who, ask) -> str:
        import json

        from . import goals, owning
        from .models import Task

        root = owning._workspace()
        step = Task.objects.filter(folder=ask.source_id).first() if ask.source_id else None
        if not root or step is None:
            return ""
        lines = [f"The step's status: {step.status}"]
        meta = goals._meta(Path(root) / step.folder)
        if isinstance(meta.get("goal_step"), dict):
            lines.append("The step as the plan has it: "
                         + json.dumps(meta["goal_step"], ensure_ascii=False)[:2000])
        goal = Path(root) / str(Path(step.folder).parent)
        try:
            known = (goal / "goal.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            known = ""
        top = Task.objects.filter(folder=str(Path(step.folder).parent)).first()
        if top is not None:
            lines.append(f"The goal: {top.title}" + (f". {top.summary}" if top.summary else ""))
        if known:
            lines += ["What the person said about the goal (goal.md):", known[:2000]]
        others = [f"- {t.title}: {t.status}" for t in Task.objects.filter(
            folder__startswith=str(Path(step.folder).parent) + "/").order_by("folder")[:20]]
        if others:
            lines += ["The goal's steps and where each stands:", *others]
        return "\n".join(lines)

    def settled(self, who, row) -> Settled | None:
        from . import goals
        from .models import Task

        task = Task.objects.filter(folder=row.source_id).first() if row.source_id else None
        if task is None:
            return Settled(decisions.WITHDRAWN, result="The step is gone.")
        meta = goals._meta(goals._folder(task) or Path("/-"))
        block = meta.get("goal_step") if isinstance(meta.get("goal_step"), dict) else {}
        chose = block.get(goals.CHOICE) or block.get(goals.NOTE) or ""
        if meta.get("status") == "done":
            return Settled(decisions.APPLIED, said=chose or "Marked complete",
                           channel="goal page", result="Completed on the step's page.")
        return Settled(decisions.WITHDRAWN, result="The step does not ask this any more.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import goals
        from .models import Task

        task = await asyncio.to_thread(lambda: Task.objects.filter(folder=row.source_id).first())
        if task is None:
            return Applied(False, "The step is not there any more.")
        goal = await asyncio.to_thread(goals.goal_above, task)
        if goal is None or hooks.keeper is None:
            return Applied(False, "Its goal could not be found.")
        got = row.answer or {}
        picked = got.get("choice") or []
        words = got.get("text") or ""
        if _delegate_said(row):
            # Kept on the step as theirs, with their own words, never as his note.
            words = (f"Decided by {got.get('by_name') or 'their delegate'}"
                     + (f": \u201c{got.get('words')}\u201d" if got.get("words") else "")
                     + (f" {words}" if words else ""))
        if "again" in picked:
            await hooks.keeper.do_step(who, goal, task.id, unattended=False,
                                       why=("The person asked for this step to be tried "
                                            "again." + (f" They said: {words}" if words else "")))
            return Applied(True, "Rouh started the step again.")
        verb = got.get("verb")
        if verb in ("not_doing", "another"):
            # An action he will not do, or wants done another way (`rouh/actions.py`): the step
            # is started again with his words, to find another route or stop, never marked done.
            await asyncio.to_thread(goals.change_step, task, note=words)
            await hooks.keeper.do_step(who, goal, task.id, unattended=False, why=(
                "The person will not do this step's action themselves. " if verb == "not_doing"
                else "The person wants this step's action done another way. ")
                + f"Their own words: {words} Find another way to finish the step without them, "
                "or stop it and say why.")
            return Applied(True, "Rouh started the step again with your words, to find another "
                                 "way or stop it.")
        labels = [o["label"] for o in row.options or [] if o["id"] in picked and o["id"] != "done"]
        if labels:
            await asyncio.to_thread(goals.change_step, task, choice=labels[0],
                                    note=words or None)
        elif words and "done" not in picked and any(o["id"].startswith("o")
                                                    for o in row.options or []):
            await asyncio.to_thread(goals.change_step, task, choice=got.get("text") or words,
                                    note=words if _delegate_said(row) else None)
        elif words:
            await asyncio.to_thread(goals.change_step, task, note=words)
        started = await hooks.keeper.step_status(who, goal, task.id, "done", by_person=True)
        more = f" {len(started)} step(s) waiting on it started." if started else ""
        whose = (f"{got.get('by_name') or 'their'}'s" if _delegate_said(row) else "your")
        return Applied(True, (f"Written into the step as {whose} choice, and the step is "
                              "complete." if labels else "The step is complete.") + more)


# --- the heartbeat's and the quests' approvals ------------------------------------------------


_SENDING = ("send", "mail", "forward", "reply", "telegram", "message", "invite", "email")
#: Named for mail, and sending none: marking, labelling or binning, and what new mail did.
#: Both were labelled "sending" until 2 November 2026.
_NOT_SENDING = frozenset({"modify_mail", "mail_alerts", "draft_mail"})
_PUBLISHING = ("publish", "post", "share", "tweet", "linkedin", "comment")
_MONEY = ("stripe", "pay", "card", "buy", "purchase", "refund", "charge", "order", "shipping")
#: Calendar changes that tell the guests, which is sending.
_TELLS_GUESTS = ("guests", "add_guests", "attendees", "notify", "send_updates")


_FOR_GOOD_ACTION = re.compile(r"(^|_)(delete|purge|erase|destroy|wipe|empty_trash|expunge)(_|$)")


def risk_of_tool(tool: str, args: dict | None = None) -> str:
    """How risky running a queued tool is, worked out from what the call does.

    Until 2 November 2026 anything not plainly money, publishing or sending was "irreversible",
    so a DNS record and a certificate request for the rouh.land move ‹Owner› had asked for were
    each labelled "Cannot be undone", and that label alone carried them through the gate to
    ‹him› (Decisions 385 and 386). ‹His› words that day: "I want ot undrstand what caused it and
    to change so tomorrow I don't get a decision but whatever the new thing gets done". So an
    unknown call is not "irreversible" any more: a DNS record, a setting, a certificate that can
    be withdrawn, a file in a repository or a deploy with an undo point can all be undone, and
    "irreversible" is kept for what deletes for good (`protected`'s own list of it). Nothing to
    run is a decision only."""
    from . import his_word, protected

    name = str(tool or "").lower()
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").lower()
    if not name:
        return "reversible"
    said = f"{name} {action}"
    if any(w in said for w in _MONEY):
        return "money"
    if any(w in said for w in _PUBLISHING):
        return "publishing"
    if name not in _NOT_SENDING and any(w in said for w in _SENDING):
        return "sending"
    if "calendar_event" in name and any(args.get(k) for k in _TELLS_GUESTS):
        return "sending"
    if name in protected.REFUSED or protected._deletes(name) or \
            any(args.get(k) for k in protected._FOR_GOOD) or _FOR_GOOD_ACTION.search(action):
        return "irreversible"
    # What cannot be worked out at all and could do a great deal - a tool nobody has said what it
    # does, a command on the server - is not taken as undoable: it fails closed.
    if name in his_word.OPEN_ENDED or his_word.unknown(name, args):
        return "irreversible"
    return "reversible"


def _steps_words(steps) -> str:
    """"step 4" or "steps 4 and 5", for what waits on a goal step."""
    ns = [str(x.get("n")) for x in steps]
    if len(ns) == 1:
        return f"step {ns[0]}"
    return "steps " + ", ".join(ns[:-1]) + " and " + ns[-1]


class ApprovalSource(Source):
    kind = "approval"
    label = "Approval"
    tag = "Approval"
    own_page = True

    def gate(self, who, ask):
        """Petar, 2 November 2026: "tomorrow I don't get a decision but whatever the new thing
        gets done". A job's call that ‹his› own words for the job already asked for never gets
        here: it ran (`his_word`, `job_gateway._on_his_word`). What a job did queue is judged
        like any other question: what spends, sends, publishes or truly cannot be undone is
        ‹his› by what it is; the rest goes to the judge, told why Rouh did not find ‹his› words
        covered it (`background`). A beat's queue is as it was."""
        from . import decision_gate as gate

        calls = [p for p in ask.prepared or [] if isinstance(p, dict) and p.get("approval")]
        if ask.batch.startswith("job:") and not calls:
            # What a job asked with request_from_rouh, which only ‹he› can give: Rouh's gateway
            # asks it once whoever asks again (`job_gateway.request`).
            return gate.let_through("A job needs something only ‹he› can give, and Rouh's own "
                                    "tools could not give it.")
        if ask.batch.startswith("job:"):
            if ask.risk in gate.GATED:
                return gate.let_through("A job's call that ‹his› own words for it did not cover, "
                                        "and that spends, sends, publishes or cannot be undone.")
            return None
        if ask.risk in gate.GATED:
            return gate.let_through("The beat queued something it may never do by itself, and "
                                    "it waits for ‹his› yes.")
        return gate.keep_back("Nothing it would run spends, sends, publishes or cannot be "
                              "undone, so the beat goes on without ‹him›.")

    def background(self, who, ask) -> str:
        """For a job's calls: what the job is, the owner's own words behind it, and why Rouh's
        check of those words did not find they already ask for each call."""
        from .models import JobRequest

        ids = [int(p["approval"]) for p in ask.prepared or []
               if isinstance(p, dict) and str(p.get("approval") or "").isdigit()]
        if not ids:
            return ""
        rows = list(JobRequest.objects.filter(user_id=str(who.user_id),
                                              org_id=str(who.org_id or ""),
                                              approval_id__in=ids).order_by("id"))
        if not rows:
            return ""
        lines = [f"A background job, {rows[0].job_title or rows[0].job_id}, asked for these "
                 "calls through Rouh's gateway."]
        words = next((r.words for r in rows if r.words), "")
        lines.append("‹Owner›'s own words for the job:\n" + (words[:3000] if words else
                                                               "(none: nothing ‹he› said is behind it)"))
        for r in rows:
            lines.append(f"- {r.tool}: Rouh's check of ‹his› words said: "
                         f"{r.judged or '(not checked)'}")
        return "\n".join(lines)

    def on_cleared(self, who, ask, verdict) -> None:
        """A job's calls the gate kept from ‹him›: let go of at the source, so they do not wait
        in the queue for an answer nobody is asked for, and the job told by request_status."""
        from .models import HeartbeatApproval, JobRequest

        ids = [int(p["approval"]) for p in ask.prepared or []
               if isinstance(p, dict) and str(p.get("approval") or "").isdigit()]
        if not ids or not ask.batch.startswith("job:"):
            return
        said = owner.say(f"Not put to ‹owner›, and nothing ran: {verdict.reason}", who)
        now = time.time()
        HeartbeatApproval.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""),
                                         id__in=ids, state="waiting").update(
            state="no", answered_on="gate", answered_at=now, result=said[:4000])
        JobRequest.objects.filter(approval_id__in=ids, outcome="pending").update(
            outcome="cleared", answer=said[:4000], settled_at=now)

    can_dismiss = True
    notifies = True

    def collect(self, who) -> list[Ask] | None:
        from . import heartbeat, job_gateway, quests

        rows = heartbeat.waiting(who)
        works = {w.id: w for w in quests.all_of(who)} if rows else {}
        out = []
        # One decision per job: a job's calls waiting together are one question, named by its
        # first call, which lists them all (`_job_calls`). Its asks for what only ‹he› can give
        # (no tool) stay one each, shared by every job that asks the same.
        jobs_calls: dict[str, list] = {}
        roots: dict[str, str] = {}
        for a in rows:
            if job_gateway.is_jobs(a) and a.tool:
                # Grouped by the work they serve: the run at the top of the runs that started
                # the job, so a job and the jobs it started ask one question, across tools.
                job = str(a.duty)[len(job_gateway.DUTY):]
                if job not in roots:
                    roots[job] = job_gateway.root_of(job)
                jobs_calls.setdefault(roots[job], []).append(a)
        for calls in jobs_calls.values():
            out.append(self._job_calls(sorted(calls, key=lambda x: x.id)))
        for a in rows:
            if job_gateway.is_jobs(a) and a.tool:
                continue
            work = works.get(a.work_id) if a.work_id is not None else None
            job = str(a.duty or "")[len(job_gateway.DUTY):] if job_gateway.is_jobs(a) else ""
            if work is not None:
                context = (f"Quest {work.task_number} · {work.title}" if work.task_number
                           else work.title)
                link = quests.address(work)
                project = "Quests"
            elif job:
                # Queued by a background job through Rouh's gateway (`rouh/job_gateway.py`).
                # No page of its own answers it, so its line opens the decision's own page.
                context = f"Job {job}"
                link = ""
                project = "Metabolism"
            else:
                context = "Heartbeat" + (f" · {a.duty}" if a.duty else "")
                # The beat that asked, opened on the beats' page, else the heartbeat's Today.
                link = heartbeat.beat_address(a.beat_id) if a.beat_id else heartbeat.HOME
                project = "Heartbeat"
            risk = risk_of_tool(a.tool, a.args)
            runs = (f"Runs {a.tool} once, with exactly what was queued, and nothing else."
                    if a.tool else "Nothing runs now: the heartbeat hears your yes and carries on.")
            note = " ".join(x for x in (a.what, f"To: {a.to_whom}." if a.to_whom else "",
                                        f"Cost: {a.cost}." if a.cost else "") if x)
            prepared = []
            if a.tool:
                prepared.append({"label": f"What runs: {a.tool}",
                                 "text": _args_text(a.args)})
            what = " ".join(str(a.what or "").split()).rstrip(".") or "Something the heartbeat queued"
            whose = (f"quest {work.task_number}" if work is not None and work.task_number else
                     "a quest" if work is not None else f"job {job}" if job else "the heartbeat")
            if job and not a.tool:
                runs = "Nothing runs: your answer goes to the jobs that asked."
            out.append(Ask(
                source_id=str(a.id), key=decisions.key_of(a.id),
                title=what if job else f"{what}, for {whose}", question=a.what,
                why=" ".join(x for x in (a.why, f"To: {a.to_whom}." if a.to_whom else "",
                                         f"Cost: {a.cost}." if a.cost else "") if x),
                then=("The job that asked is told your answer either way; a no runs nothing."
                      if job else "The heartbeat hears your answer either way; a no runs nothing."),
                link=link, context=context, project=project,
                batch=(f"quest:{a.work_id}" if a.work_id is not None else f"job:{job}" if job
                       else "heartbeat"),
                options=([{"id": "yes", "label": "Give it", "detail": "Write it in your own "
                           "words; they go to the jobs that asked.", "go": True},
                          {"id": "no", "label": "No", "detail": "The jobs finish without it."}]
                         if job and not a.tool else
                         [{"id": "yes", "label": "Yes, do it", "detail": runs, "go": True},
                          {"id": "no", "label": "No", "detail": "Nothing runs."}]),
                # A job's reason is the job's words, which may carry what it read: never said as
                # Rouh's recommendation.
                recommended="" if job else "yes", recommended_why="" if job else a.why[:300],
                allow_other=True, answer_type="approval",
                urgency="now" if a.blocking else "today",
                risk=risk, risk_note=note[:600], prepared=prepared, asked_at=a.asked_at,
                history=[{"at": a.asked_at, "kind": "raised",
                          "detail": (f"Queued by heartbeat beat #{a.beat_id}" if a.beat_id
                                     else f"Asked by job {job} through Rouh's gateway" if job
                                     else "Queued") + (f" for {context}" if context and not job
                                                       else "") + "."}],
                # A job's ask the gateway read as hands-on is an action; one it read as a
                # question is a decision; one asked before it read either is read once
                # (`rouh/actions.py`).
                kind=("" if a.tool or not job else
                      "action" if (a.args or {}).get("hands_on") is True else
                      "decision" if (a.args or {}).get("hands_on") is False else ""),
                action=({"after": "The job that asked is told your answer, in your words, and "
                                  "carries on from it.",
                         "wait": (f"Job {job} is held until you do it." if a.blocking else
                                  f"Job {job} goes on without it meanwhile.")}
                        if job and not a.tool and (a.args or {}).get("hands_on") is not False
                        else {}),
                yes_does=" ".join(x for x in (
                    f"Runs {a.tool} once, exactly as queued." if a.tool else
                    "Nothing runs: your answer goes to the jobs that asked." if job else
                    "Nothing runs: the heartbeat hears your yes and carries on.",
                    f"To {str(a.to_whom).rstrip('.')}." if a.to_whom else "",
                    f"Costs {str(a.cost).rstrip('.')}." if a.cost else "") if x),
                wait_cost=(f"{whose[0].upper() + whose[1:]} is held until you answer."
                           if a.blocking else "Nothing waits on it."),
                blocks=bool(a.blocking)))
        return out

    def _job_calls(self, calls: list) -> Ask:
        """One job's calls that wait on ‹his› yes, as one decision (Petar, 2 November 2026):
        each listed with what runs, the riskiest of them its risk, and a yes runs each of them
        once, exactly as queued (`apply`)."""
        from . import job_gateway

        from .models import Run

        head = calls[0]
        job = str(head.duty or "")[len(job_gateway.DUTY):]
        root = job_gateway.root_of(job)
        work = (Run.objects.filter(id=root).values_list("title", flat=True).first() or "").strip()
        risks = [risk_of_tool(a.tool, a.args) for a in calls]
        order = ["money", "irreversible", "publishing", "sending"]
        risk = next((r for r in order if r in risks), "reversible")
        whats = [" ".join(str(a.what or "").split()).rstrip(".") or f"Run {a.tool}" for a in calls]
        if len(calls) == 1:
            title = whats[0]
        else:
            title = (f"{len(calls)} calls for {work or f'job {job}'}: " + "; ".join(
                w.split(", for job ")[0] for w in whats))
        # The reason is the issue they serve, then each call's own, said as the job's.
        reason = " ".join(str(head.why or "").split()) if len(calls) == 1 else (
            (f"All for one piece of work, {work}. " if work else "All for one piece of work. ")
            + " ".join(f"{i}. {a.tool}: {' '.join(str(a.why or '').split()) or 'no reason given.'}"
                       for i, a in enumerate(calls, 1)))
        to_whom = ", ".join(dict.fromkeys(a.to_whom for a in calls if a.to_whom))
        prepared = [{"label": f"What runs: {a.tool}", "text": _args_text(a.args),
                     "approval": a.id} for a in calls]
        note = " ".join(x for x in ("; ".join(whats) + ".", f"To: {to_whom}." if to_whom else "")
                        if x)
        each = "each of these once, exactly as queued" if len(calls) > 1 else \
            f"{head.tool} once, with exactly what was queued"
        return Ask(
            # A call joining is a new question, judged afresh: a verdict on the calls before it
            # is never stretched over it.
            source_id=str(head.id), key=decisions.key_of("job-calls", *[a.id for a in calls]),
            title=title[:300], question=title[:1200],
            why=" ".join(x for x in (reason, f"To: {to_whom}." if to_whom else "") if x),
            then="The jobs that asked are told your answer either way; a no runs nothing.",
            link="", context=f"Job {root}", project="Metabolism", batch=f"job:{root}",
            options=[{"id": "yes", "label": "Yes, do it" if len(calls) == 1 else "Yes, do all",
                      "detail": f"Runs {each}, and nothing else.", "go": True},
                     {"id": "no", "label": "No", "detail": "Nothing runs."}],
            recommended="", recommended_why="", allow_other=True, answer_type="approval",
            urgency="now" if any(a.blocking for a in calls) else "today",
            risk=risk,
            risk_note=note[:600], prepared=prepared, asked_at=head.asked_at,
            history=[{"at": a.asked_at, "kind": "raised",
                      "detail": f"Asked by job {str(a.duty)[len(job_gateway.DUTY):]} through Rouh's gateway: {a.tool}."}
                     for a in calls],
            yes_does=f"Runs {each}." + (f" To {to_whom.rstrip('.')}." if to_whom else ""),
            wait_cost=f"Job {root} is held until you answer." if any(a.blocking for a in calls)
            else "Nothing waits on it.",
            blocks=any(a.blocking for a in calls))

    def settled(self, who, row) -> Settled | None:
        from . import heartbeat
        from .models import HeartbeatApproval

        try:
            ident = int(row.source_id)
        except ValueError:
            return None
        a = HeartbeatApproval.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                             id=ident).first()
        if a is None:
            if heartbeat.was_deleted(_Who(row.user_id, row.org_id), ident):
                return Settled(decisions.DISMISSED, result="Deleted from the queue.")
            return Settled(decisions.WITHDRAWN, result="It is not in the queue any more.")
        if a.state == heartbeat.RULE_STATE:
            # Ran because a beat may now do it by itself: nobody's yes, and never ‹his›.
            return Settled(decisions.APPLIED, said="Needed nobody's yes", channel="rule",
                           by="rouh", result=(" ".join(x for x in (
                               "Mail from Rouh's own inbox to the person who decides for this "
                               "work, about it, needs nobody's yes, so it went as queued.",
                               a.result or "") if x))[:600])
        if a.state in ("yes", "no", "failed"):
            said = {"yes": "Yes", "no": "No", "failed": "Yes"}[a.state]
            return Settled(decisions.APPLIED, said=said, channel=a.answered_on or "heartbeat",
                           result=(a.result or "")[:600])
        return None

    async def apply(self, who, row, channel: str) -> Applied:
        live = hooks.heartbeat
        if live is None:
            return Applied(False, "The heartbeat is not running, so nothing could take it.")
        got = row.answer or {}
        yes = "yes" in (got.get("choice") or [])
        # A job's own entry: the jobs that asked are told, words and all (`job_gateway.answered`),
        # and no beat hears of it.
        jobs = str(getattr(row, "batch", "") or "").startswith("job:")
        if jobs and not yes and got.get("text") and "no" not in (got.get("choice") or []):
            # A job's question answered in ‹his› own words is answered, not refused.
            yes = True
        listed = [int(p["approval"]) for p in row.prepared or []
                  if isinstance(p, dict) and str(p.get("approval") or "").isdigit()]
        if jobs and len(listed) > 1:
            # One decision for a job's calls: the answer is each one's, run one by one.
            parts = [await live.answer(who, ident, yes, on=channel,
                                       words=str(got.get("text") or ""))
                     for ident in listed]
            ok = not any("could not run" in p for p in parts)
            return Applied(ok, " ".join(parts)[:3000])
        said = await live.answer(who, row.source_id, yes, on=channel,
                                 words=str(got.get("text") or ""))
        by = "" if jobs else _delegate_said(row)
        if by:
            await live.event("answer", owner.say(f"On {decisions.name_of(row)}: {by}", who)[:900],
                             approval=int(row.source_id))
        elif got.get("text") and not jobs:
            await live.event("answer", owner.say(f"‹owner›'s own words on {decisions.name_of(row)}: ",
                                                 who) + f"{got['text'][:600]}",
                             approval=int(row.source_id))
        ok = not said.startswith(("There is no", "Which one", "Approval #")) and \
            "already answered" not in said and "could not run" not in said
        return Applied(ok, said)

    def dismiss(self, who, row) -> str:
        from . import heartbeat

        listed = [str(p["approval"]) for p in row.prepared or []
                  if isinstance(p, dict) and str(p.get("approval") or "").isdigit()]
        return heartbeat.delete_approvals(who, listed or [row.source_id])


def _args_text(args) -> str:
    import json

    try:
        return json.dumps(args or {}, ensure_ascii=False, indent=1)[:1500]
    except (TypeError, ValueError):
        return str(args)[:1500]


class _Q:
    """A stand-in decision, for reading a task's line with no decision at hand."""

    def __init__(self, question: str, user_id: str = ""):
        self.question, self.user_id = question, user_id


class _Who:
    def __init__(self, user_id, org_id):
        self.user_id, self.org_id = user_id, org_id


# --- runs of the one program --------------------------------------------------------------


class RunSource(Source):
    kind = "run"
    label = "Run"
    tag = "Run"
    own_page = True

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("A run of the one program is held until ‹he› answers.")
    notifies = True

    def collect(self, who) -> list[Ask] | None:
        from . import addressing, runs

        if not _owner(who) or hooks.one_questions is None:
            return None
        got = hooks.one_questions()
        if got is None:
            return None
        out = []
        for q in got:
            if not q.get("id") or not q.get("open", True):
                continue
            choices = q.get("choices") or {}
            posed = bool(q.get("kind")) and choices.get("yes") and choices.get("no")
            run_id = str(q.get("run") or "")
            title = ""
            try:
                row = runs.row_for(run_id) if run_id else None
                title = (row or {}).get("title") or ""
            except Exception:
                title = ""
            text = str(q.get("text") or "A run is asking.")
            detail = str(q.get("detail") or q.get("what") or "")
            risk = "money" if posed and q.get("kind") == "billing" else (
                "reversible" if posed else "irreversible")
            yes_label = choices.get("yes") or "Allow"
            no_label = choices.get("no") or "Deny"
            out.append(Ask(
                source_id=str(q["id"]), key=decisions.key_of(q["id"]),
                title=(f"{title}: {text}" if title else f"A run of the one program: {text}"),
                question=text,
                why=str(q.get("why") or ""),
                then=("The run is held until you answer." if not posed else
                      "The run waits on this choice."),
                link=f"/run/{run_id}" if run_id else addressing.METABOLISM,
                context=f"Run · {title}" if title else "Run", project="Metabolism",
                batch=f"run:{run_id}",
                options=[{"id": "yes", "label": yes_label,
                          "detail": detail[:400] if not posed else "", "go": True},
                         {"id": "no", "label": no_label,
                          "detail": "The run is told no." if not posed else ""}],
                allow_other=False, answer_type="yes_no", urgency="now",
                due_at=_epoch(q.get("expires_at")) if not q.get("lasting") else None,
                risk=risk, risk_note=(f"Lets the run do this: {detail or text}"[:600]
                                      if not posed else text[:600]),
                prepared=[{"label": "What it wants to run", "text": detail[:1500]}] if detail
                else [], asked_at=_epoch(q.get("asked_at")),
                yes_does=(f"{yes_label}: the run goes on that way." if posed else
                          f"Lets the run do this: {(detail or text).rstrip('.')}."),
                wait_cost=("The run is held until you answer." if q.get("lasting") or posed else
                           "The run is held, and is told no when its time runs out."),
                blocks=True))
        return out

    def settled(self, who, row) -> Settled | None:
        if row.due_at and row.due_at < time.time():
            return Settled(decisions.EXPIRED, result="It ran out of time, and the run was told no.")
        return Settled(decisions.WITHDRAWN, result="Closed in the one program: answered there, "
                                                   "or the run moved on.")

    async def apply(self, who, row, channel: str) -> Applied:
        if hooks.one_answer is None:
            return Applied(False, "The one program is not connected.")
        yes = "yes" in ((row.answer or {}).get("choice") or [])
        got, why = await hooks.one_answer(row.source_id, "yes" if yes else "no")
        if why:
            return Applied(False, why)
        if (got or {}).get("said"):
            return Applied(True, f"Done: {got['said']}.")
        return Applied(True, "Allowed; the run carries on." if yes else "Refused; the run was told no.")


def _epoch(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --- landings that collided --------------------------------------------------------------


class ConflictSource(Source):
    """A landing that collided, and only one Rouh may not settle itself.

    Petar, 18 October 2026: a landing's conflict is technical, and Rouh settles it: `land.sh`
    merges both sides, or takes the side its merge pass recommends and says why in the job's
    report. The one kind that reaches him is a clash that would lose his own written words - an
    edit he made in place, which Rouh's saver carried to main - with no safe merge
    (`conflicts.his_words`). Then it is one decision per file, however many jobs collided in it,
    titled by the file, saying what each side changed and what Rouh recommends."""

    kind = "conflict"
    label = "Conflict"
    tag = "Landing"
    notifies = True

    @staticmethod
    def _file_of(record) -> str:
        files = [str(f) for f in (record.get("files") or []) if str(f).strip()]
        return files[0] if files else str(record.get("id") or "")

    def _groups(self):
        from . import conflicts

        waiting = conflicts.waiting_now(cfg=hooks.cfg)
        parked = conflicts.parked_now(cfg=hooks.cfg)
        groups: dict[str, list] = {}
        for record, was_parked in [(r, False) for r in waiting] + [(r, True) for r in parked]:
            if record.get("id"):
                groups.setdefault(self._file_of(record), []).append((record, was_parked))
        return groups

    def gate(self, who, ask):
        from . import conflicts, decision_gate as gate

        try:
            group = self._groups().get(ask.source_id.removeprefix("file:"), [])
        except Exception:
            return None
        if any(conflicts.his_words(r) for r, _p in group):
            return gate.let_through("Settling it would lose words ‹owner› wrote ‹himself›, and "
                                    "no merge keeps both.")
        return gate.keep_back("A landing's collision is Rouh's to settle: it merges both sides, "
                              "or takes the side it recommends and says why in the job's report.")

    def collect(self, who) -> list[Ask] | None:
        from . import addressing, conflicts

        if not _owner(who):
            return None
        try:
            groups = self._groups()
        except Exception:
            log.exception("decisions: the conflict records could not be read")
            return None
        out = []
        for path, group in groups.items():
            record, was_parked = group[0]
            ids = sorted(str(r.get("id")) for r, _p in group)
            name = path.rsplit("/", 1)[-1]
            mine = conflicts.side_summary(record.get("mine") or {})
            theirs = conflicts.side_summary(record.get("theirs") or {})
            jobs = len(group)
            question = (f"Two pieces of work changed {path} in ways that cannot both hold. "
                        f"The job's side: {mine.rstrip('.')}. Main's side: {theirs.rstrip('.')}."
                        + (f" {jobs - 1} other job(s) collided in the same file and follow "
                           "your answer." if jobs > 1 else ""))
            opts = [{"id": str(c["n"]), "label": c["label"], "detail": c["means"]}
                    for c in conflicts.CHOICES]
            pick = str((conflicts.choice(record.get("recommend")) or {}).get("n") or "3")
            out.append(Ask(
                source_id=f"file:{path}",
                key=decisions.key_of("file", path, ",".join(ids),
                                     "parked" if was_parked else "waiting"),
                title=f"Which version of {name} to keep", question=question,
                why=(str(record.get("his_words_why") or "")
                     or "One side holds words you wrote yourself, and no merge keeps both."),
                then="Your pick goes to the job that wrote the code for every job that collided "
                     "here, which carries it out and proves it again before it lands.",
                link=f"/run/{record.get('run')}" if record.get("run") else addressing.METABOLISM,
                context=f"Landing · {name}", project="Metabolism", batch=f"conflict:{path}",
                options=opts,
                recommended=pick,
                recommended_why=(str(record.get("recommend_why") or "")
                                 or "It keeps what both sides meant, and the job proves it again."),
                allow_other=False, answer_type="choice",
                urgency="whenever" if was_parked else "today", risk="reversible",
                prepared=[{"label": "What each side changed",
                           "text": f"The job's side: {mine}\nMain's side: {theirs}\n"
                                   + "\n".join(f"Collided in it: {i}" for i in ids)}],
                asked_at=float(record.get("at") or 0) or None,
                yes_does=_yes_from(opts, pick),
                wait_cost=("Nothing waits on it: you parked it, and the work stays on its own "
                           "branch." if was_parked else
                           f"The work that changed {name} stays off main until you pick."),
                blocks=not was_parked))
        return out

    def _records_of(self, row) -> list:
        from . import conflicts

        path = row.source_id.removeprefix("file:")
        return [r for r in conflicts.read_all(cfg=hooks.cfg)
                if self._file_of(r) == path or str(r.get("id")) == row.source_id]

    def settled(self, who, row) -> Settled | None:
        for r in self._records_of(row):
            if r.get("choice"):
                return Settled(decisions.APPLIED, said=str(r.get("choice_label") or r["choice"]),
                               channel="conflict card", result="Picked on its card.")
        return Settled(decisions.WITHDRAWN, result="It does not need you any more.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import conflicts

        if hooks.conflict_answer is None:
            return Applied(False, "Nothing here can take a conflict's answer right now.")
        pick = ((row.answer or {}).get("choice") or [""])[0]
        records = await asyncio.to_thread(self._records_of, row)
        ids = [str(r.get("id")) for r in records if conflicts.needs_a_person(r)
               or r.get("state") == conflicts.PARKED] or [row.source_id]
        said = []
        for rid in ids:
            got = await hooks.conflict_answer(rid, pick)
            if not got.get("ok"):
                return Applied(False, str(got.get("why") or "It could not be carried out."))
            said.append(got)
        got = said[-1]
        how = ("It went back to the job." if got.get("sent_to_the_worker") else
               "Carried out here: the job had stopped." if got.get("carried_out_here") else
               "Recorded.")
        each = f" For all {len(ids)} jobs." if len(ids) > 1 else ""
        return Applied(True, f"You chose {got.get('choice')}, {got.get('label')}. {how}{each}")


# --- background jobs stopped on the person: a prompt, or a step for the live browser -----------


class JobSource(Source):
    kind = "job"
    label = "Job"
    tag = "Job"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("A job is stopped at its prompt, or on a step only ‹he› can do in "
                                "the live browser.")
    text_acts = True

    def _rows(self):
        from .models import Run

        return list(Run.objects.filter(state="waiting", archived=False, parent_run_id__isnull=True)
                    .order_by("-started_at")[:100])

    def _theirs(self):
        """The runs whose question is the one program's own, which the run source has."""
        got = hooks.one_questions() if hooks.one_questions is not None else None
        return {str(q.get("run") or "") for q in (got or [])}, got is not None

    def census(self, who):
        if not _owner(who):
            return None
        return {r.id: f"{r.title}: {r.question or r.detail or 'waiting on you'}"[:200]
                for r in self._rows()}

    def why_not(self, who, source_id: str) -> str:
        from . import runs as register
        from .models import Run

        theirs, known = self._theirs()
        if source_id in theirs:
            return "its question is the one program's own: it is a Run decision"
        row = Run.objects.filter(id=source_id).first()
        if not known and row is not None and row.policy == register.ONE_POLICY \
                and row.phase == "asking":
            return ("it is a run of the one program asking on its screen, and the program "
                    "could not be reached to tell its own questions from it")
        return "it no longer waits on you"

    def collect(self, who) -> list[Ask] | None:
        from . import browser_handoff, runs as register

        if not _owner(who):
            return None
        theirs, known = self._theirs()
        out = []
        for r in self._rows():
            if r.id in theirs:
                continue
            asked = str(r.question or r.detail or "").strip()
            is_one = r.policy == register.ONE_POLICY
            if is_one and r.phase == "asking" and not known:
                continue          # cannot tell a permission ask from a screen one: the run source's
            handoff = browser_handoff.is_line(asked) or browser_handoff.is_line(r.detail)
            details = _handoff_of(r.id) if handoff else None
            if handoff:
                step = details.step if details else asked[len(browser_handoff.LINE):]
                prepared = []
                if details is not None:
                    prepared = [{"label": "Where", "text": details.address},
                                {"label": "Ready", "text": details.ready},
                                {"label": "What it needs back", "text": details.send_back}]
                    prepared = [p for p in prepared if p["text"]]
                out.append(Ask(
                    source_id=r.id, key=decisions.key_of(r.id, asked, "handoff"),
                    title=f"{r.title or 'A job'}: {step.rstrip('.')}, in the live browser",
                    question=f"Do this in the live browser: {step}",
                    why="The job stopped at a step only you may take: a sign-in, a code, a "
                        "payment or a button that cannot be undone. Rouh opens it in its live "
                        "browser and hands it to you there.",
                    then="What you write is sent to the job, which carries on from it.",
                    link=f"/run/{r.id}", context=f"Job · {r.title}" if r.title else "Job",
                    project="Metabolism", batch=f"run:{r.id}", options=[], allow_other=True,
                    answer_type="text", urgency="today", risk="reversible",
                    risk_note="", prepared=prepared, asked_at=r.updated_at or r.started_at,
                    yes_does=("Rouh opens " + (details.address if details and details.address
                                               else "the page") + " in its live browser for you "
                              f"to {step[:1].lower() + step[1:].rstrip('.')}; what you send back "
                              "goes to the job, which carries on."),
                    wait_cost="The job is stopped until then.", blocks=True,
                    kind="action", action={
                        "do": f"{step.rstrip('.')}, in Rouh's live browser",
                        "steps": ([{"text": f"Open {details.address} in Rouh's live browser.",
                                    "href": details.address, "link": "The page"}]
                                  if details is not None and details.address.startswith("http")
                                  else []) + [{"text": step}],
                        "after": "What you send back goes to the job, which carries on from it.",
                        "wait": "The job is stopped until then."}))
                continue
            out.append(Ask(
                source_id=r.id, key=decisions.key_of(r.id, asked, "prompt"),
                title=(f"{r.title or 'A job'} asks: {asked}" if asked else
                       f"{r.title or 'A job'} is stopped at its prompt"),
                question=asked or "It stopped at a prompt and is waiting for you.",
                why="The job is held at its prompt until it is answered.",
                then="What you write is typed into the job's prompt, as reply_to_task does.",
                link=f"/run/{r.id}", context=f"Job · {r.title}" if r.title else "Job",
                project="Metabolism", batch=f"run:{r.id}", options=[], allow_other=True,
                answer_type="text", urgency="now", risk="irreversible",
                risk_note=("What you write goes straight to the job's prompt, which may allow "
                           "what it asked to do."),
                asked_at=r.updated_at or r.started_at,
                yes_does=("What you write is typed into the job's prompt, which may let it do "
                          "what it asked."),
                wait_cost="The job is held at its prompt until you answer.", blocks=True))
        return out

    def settled(self, who, row) -> Settled | None:
        return Settled(decisions.WITHDRAWN, result="The job moved on: answered at its prompt, "
                                                   "or it finished.")

    async def apply(self, who, row, channel: str) -> Applied:
        if hooks.reply_to_task is None:
            return Applied(False, "Nothing here can reach the job right now.")
        words = (row.answer or {}).get("text") or (row.answer or {}).get("said") or ""
        said = await hooks.reply_to_task(row.source_id, words)
        bad = str(said or "").lower()
        return Applied(not any(w in bad for w in ("refused", "no such", "not found", "could not")),
                       str(said or "Sent to the job.")[:2000])


def _handoff_of(run_id: str):
    """A crew job's hand-off kept on its record, with its address and what it needs."""
    from . import browser_handoff
    from .models import Crewmate

    mate = Crewmate.objects.filter(id=run_id).first()
    meta = getattr(mate, "meta", None) if mate is not None else None
    if isinstance(meta, str):
        import json

        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    return browser_handoff.from_dict((meta or {}).get("handoff")) if isinstance(meta, dict) else None


# --- Synapse: what a night of dreaming proposed, waiting for his Approve or Reject ------------


_DREAM_ASK = {
    "superseded": "Is the older one replaced by the newer?",
    "ask_closed": "Is this ask closed?",
    "promise_kept": "Was this promise kept?",
    "duplicate": "Are these the same, to be merged into one?",
    "misfiled_rule": "Is this a fact rather than a standing rule of yours?",
    "contradiction": "These two say different things. Which stands?",
    "sensitivity_mismatch": "Should this be kept as private as what it came from?",
    "link_strength": "Should these be linked more strongly, as they are used together?",
}
#: What one night's changes of a kind are called, one and many.
_DREAM_NOUN = {
    "superseded": ("replacement", "replacements"),
    "ask_closed": ("ask to close", "asks to close"),
    "promise_kept": ("promise kept", "promises kept"),
    "duplicate": ("merge", "merges"),
    "misfiled_rule": ("rule to refile as a fact", "rules to refile as facts"),
    "contradiction": ("contradiction", "contradictions"),
    "sensitivity_mismatch": ("sensitivity change", "sensitivity changes"),
    "link_strength": ("link change", "link changes"),
}


def _dream_noun(kind: str, n: int) -> str:
    one, many = _DREAM_NOUN.get(kind, ("change", "changes"))
    return f"{n} {one if n == 1 else many}"


class DreamSource(Source):
    """What a night of Synapse's dreaming left for his Approve or Reject (`synapse/dreaming.py`).

    Until 8 October 2026 every change was a decision of its own, and one night's 142 small,
    reversible changes buried everything else on the Decisions page ("Decisions is
    overflowing, needs a fix"). Since then a night's changes of one kind are ONE decision,
    "Synapse, night 1: 32 link changes", whose `items` are the changes: Approve all, Reject
    all, or open it and decide them one by one. Each change answered goes through
    `dreaming.decide`, exactly as on the Dreams page and as its own decision did before, and
    is undone on the Dreams page the same way. A group answered in part stays open for the
    rest (`Applied.reopen`). The per-change decisions still waiting the day this shipped were
    folded into their group by the first sync (`settled`), which says so on each.
    """

    kind = "dream"
    label = "Synapse"
    tag = "Memory"
    own_page = True

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.keep_back("Synapse's own housekeeping of its memory: nothing ‹he› asked for "
                              "waits on it, and each change stays on the Dreams page.",
                              "The changes wait on the Dreams page in the Synapse lab.")

    def _master(self, who):
        from .synapse import db, dreaming

        try:
            if not db.ready() or not dreaming.ready():
                return None
            return db.row("SELECT * FROM synapse.dataset WHERE master AND org_id = %s "
                          "AND user_id = %s ORDER BY created_at LIMIT 1",
                          (str(who.org_id), str(who.user_id)))
        except Exception:
            log.exception("decisions: Synapse could not be read")
            return None

    def _waiting(self, who):
        from .synapse import datasets, dreaming, search

        ds = self._master(who)
        if ds is None:
            return None, None, None
        viewer = search.readers_for(datasets.me(ds))
        return ds, viewer, dreaming.waiting(ds, viewer)["changes"]

    @staticmethod
    def group_of(night, kind) -> str:
        """A group's own id: its night and its kind."""
        return f"{night}:{kind}"

    def census(self, who):
        from .synapse import db

        ds = self._master(who)
        if ds is None:
            return None
        rows = db.rows("SELECT d.number AS night, c.kind, count(*) AS n FROM synapse.dream_change c "
                       "JOIN synapse.dream d ON d.id = c.dream_id WHERE c.dataset_id = %s "
                       "AND c.state = 'waiting' GROUP BY 1, 2", (ds["id"],))
        return {self.group_of(r["night"], r["kind"]): f"night {r['night']}: "
                + _dream_noun(r["kind"], int(r["n"])) for r in rows}

    def why_not(self, who, source_id: str) -> str:
        return "it is not readable in full by you (a reader you are not), so it is left on the Dreams page"

    @staticmethod
    def _item(ds, c) -> dict:
        sides = []
        for name in ("old", "new"):
            side = c.get(name) or {}
            if side:
                words = side.get("text") or ""
                if words.strip() == (side.get("title") or "").strip():
                    words = ""  # only its title again
                sides.append({"label": ("Older: " if name == "old" else "Newer: ")
                              + (side.get("title") or "")[:120],
                              "text": words[:600],
                              "href": f"/synapse/{ds['id']}/item/{side['id']}"})
        titles = [(c.get(n) or {}).get("title") or "" for n in ("old", "new")]
        label = " ↔ ".join(t for t in titles if t) or f"Change {c['id']}"
        effect = c.get("effect") or {}
        return {"id": str(c["id"]), "label": label[:300],
                "detail": str(effect.get("said") or "Make the change.")[:400],
                "why": c.get("reason") or "",
                "href": f"/synapse/{ds['id']}/dreams/waiting",
                "sides": [{k: v for k, v in x.items() if v} for x in sides]}

    def collect(self, who) -> list[Ask] | None:
        from .synapse import dreaming

        try:
            ds, _viewer, changes = self._waiting(who)
        except Exception:
            log.exception("decisions: the dream changes could not be read")
            return None
        if ds is None:
            return None
        groups: dict[tuple, list] = {}
        for c in changes:
            groups.setdefault((c.get("night"), c["kind"]), []).append(c)
        out = []
        for (night, kind), these in groups.items():
            n = len(these)
            noun = _dream_noun(kind, n)
            made = [t for t in (_epoch(c.get("made_at")) for c in these) if t]
            ask = _DREAM_ASK.get(kind, "Should this change be made?")
            out.append(Ask(
                source_id=self.group_of(night, kind),
                key=decisions.key_of("dream-group", night, kind),
                title=f"Synapse, night {night}: {noun}",
                question=f"Synapse's night {night} proposes {noun}. For each: {ask[0].lower()}{ask[1:]}",
                why=("Small changes to your memory, each reversible. Approve all or Reject all "
                     "answers every one the same way; open the list to decide them one by one."),
                then="Approve makes a change in your memory, and it can be undone on the "
                     "Dreams page; Reject leaves it as it is and it is never proposed again. "
                     "What you leave unanswered stays here.",
                link=f"/synapse/{ds['id']}/dreams/waiting",
                context=f"Synapse · night {night} · {dreaming.KIND_WORDS.get(kind, kind)}",
                project="Synapse", batch=f"dream:{night}:{kind}",
                options=[{"id": "approve", "label": f"Approve all {n}" if n > 1 else "Approve",
                          "each": "Approve",
                          "detail": "Make every change; each can be undone on the Dreams page."
                          if n > 1 else str((these[0].get("effect") or {}).get("said")
                                            or "Make the change.")[:400]},
                         {"id": "reject", "label": f"Reject all {n}" if n > 1 else "Reject",
                          "each": "Reject",
                          "detail": "Leave them as they are; none is proposed again." if n > 1
                          else "Leave it as it is; never proposed again."}],
                allow_other=False, answer_type="choice", urgency="whenever", risk="reversible",
                items=[self._item(ds, c) for c in these],
                asked_at=min(made) if made else None,
                history=[{"at": min(made) if made else 0, "kind": "raised",
                          "detail": f"Proposed by Synapse's night {night}."}],
                yes_does=(f"Makes the {noun} in your memory; each can be undone on the Dreams "
                          "page."),
                wait_cost="Nothing waits on it: your memory stays as it is."))
        return out

    def _group_left(self, who, row) -> int | None:
        """How many of a group's changes still wait at the source, or None if unreadable."""
        from .synapse import db

        night, _, kind = str(row.source_id).partition(":")
        ds = self._master(who)
        if ds is None:
            return None
        try:
            return int(db.value(
                "SELECT count(*) FROM synapse.dream_change c JOIN synapse.dream d ON d.id = c.dream_id "
                "WHERE c.dataset_id = %s AND d.number = %s AND c.kind = %s AND c.state = 'waiting'",
                (ds["id"], int(night), kind)) or 0)
        except Exception:
            return None

    def settled(self, who, row) -> Settled | None:
        from .synapse import db

        if ":" in str(row.source_id):
            # A group nothing waits in any more: decided on the Dreams page.
            left = self._group_left(who, row)
            if left == 0:
                return Settled(decisions.APPLIED, said="Every change decided",
                               channel="Dreams page",
                               result="Every change in it has been decided, here or on the "
                                      "Dreams page.")
            return Settled(decisions.WITHDRAWN, result="It no longer asks this.")
        try:
            got = db.row("SELECT c.state, c.kind, d.number AS night FROM synapse.dream_change c "
                         "JOIN synapse.dream d ON d.id = c.dream_id WHERE c.id = %s",
                         (int(row.source_id),))
        except Exception:
            return None
        if got is None:
            return Settled(decisions.WITHDRAWN, result="The change is gone.")
        if got["state"] in ("applied", "rejected"):
            return Settled(decisions.APPLIED,
                           said="Approve" if got["state"] == "applied" else "Reject",
                           channel="Dreams page", result=f"{got['state'].title()} on the Dreams page.")
        if got["state"] == "waiting":
            # One change a decision of its own, from before a night's changes were grouped:
            # its question goes on in its group.
            group = (_models_decision().objects.filter(
                user_id=row.user_id, org_id=row.org_id, source=self.kind,
                source_id=self.group_of(got["night"], got["kind"]))
                .exclude(status__in=decisions.DONE).order_by("-id").first())
            where = (f"{group.number or group.id}, {group.title}" if group is not None
                     else f"?, night {got['night']}'s {got['kind']}")
            return Settled(decisions.WITHDRAWN,
                           result=f"{decisions.FOLDED}{where}: one decision for the night's changes "
                                  "of this kind, where it still waits.")
        return Settled(decisions.WITHDRAWN, result=f"It is {got['state']} now.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from .synapse import dreaming

        answer = row.answer or {}
        each = answer.get("items") or {}
        if not each:
            # A change that was a decision of its own (before grouping), answered in its window.
            verdict = (answer.get("choice") or [""])[0]
            each = {str(row.source_id): verdict} if ":" not in str(row.source_id) else {}
        if not each or any(v not in ("approve", "reject") for v in each.values()):
            return Applied(False, "Approve or reject.")
        ds, viewer, _c = await asyncio.to_thread(self._waiting, who)
        if ds is None:
            return Applied(False, "Synapse could not be reached.")
        done = {"approve": 0, "reject": 0}
        gone, failed = 0, []
        for change, verdict in each.items():
            try:
                got = await asyncio.to_thread(dreaming.decide, ds, int(change), verdict, viewer,
                                              by="decisions")
            except Exception as exc:  # noqa: BLE001 - said on the decision
                log.exception("decisions: dream change %s could not be decided", change)
                failed.append(f"{change}: {type(exc).__name__}")
                continue
            if got.get("ok"):
                done[verdict] += 1
            elif "not waiting" in str(got.get("why") or "") or "no such" in str(got.get("why") or "").lower():
                gone += 1
            else:
                failed.append(f"{change}: {got.get('why') or 'it could not be done'}")
        said = []
        if done["approve"]:
            said.append(f"Approved {done['approve']}: made, and each can be undone on the Dreams page")
        if done["reject"]:
            said.append(f"Rejected {done['reject']}: left as they were")
        if gone:
            said.append(f"{gone} already decided elsewhere")
        if failed:
            said.append(f"{len(failed)} could not be done ({'; '.join(failed[:3])})")
        result = ("; ".join(said) or "Nothing was done") + "."
        if ":" not in str(row.source_id):
            ok = not failed
            return Applied(ok, ("Approved: the change is made, and can be undone on the Dreams page."
                                if done["approve"] else "Rejected: left as it was.") if ok
                           and (done["approve"] or done["reject"]) else result)
        left = await asyncio.to_thread(self._group_left, who, row)
        if left is None and (failed or len(each) < len(row.items or [])):
            return Applied(not failed, result, reopen=True)
        if left:
            return Applied(not failed or bool(done["approve"] or done["reject"]),
                           f"{result} {_dream_noun(row.batch.rsplit(':', 1)[-1], left)} still wait.",
                           reopen=True)
        return Applied(not failed, result)


def _models_decision():
    from .models import Decision

    return Decision


class NightlySource(Source):
    """The nightly feature run's one question a night (`rouh/nightly_feature.py`).

    Petar, 6 October 2026: three answers. Accept marks it accepted. Reject and undo turns
    the feature's switch off at once, then starts a run that reverts the code, deploys, and
    cancels every trial, subscription and account the night made, from services.md. Other
    is his own words, which the next night's run is given first.
    """

    kind = "nightly"
    label = "Nightly feature"
    tag = "Gene"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.keep_back("The night's feature is already live and stays on unless ‹he› "
                              "turns it off; nothing waits on ‹his› answer.",
                              "The feature stays on, as Rouh recommends.")
    text_acts = True

    def collect(self, who) -> list[Ask] | None:
        from . import nightly_feature

        if not _owner(who):
            return []
        try:
            asked = nightly_feature.unanswered(who)
        except Exception:
            log.exception("decisions: the nightly feature run's nights could not be read")
            return None
        folder = nightly_feature.task_folder()
        out = []
        for r in asked:
            # A night whose genes Mutations keeps is asked there, in Mutations' one
            # line (`GeneSource`), not here as well (Petar, 13 October 2026, task 94 step 94-08).
            if _in_mutations(who, r.number):
                continue
            prepared = [{"label": f"Screenshot {i + 1}", "href": f"/workspace/{p}"}
                        for i, p in enumerate(r.screenshots or [])]
            if r.report:
                prepared.insert(0, {"label": "What was built, with screenshots",
                                    "href": f"/workspace/{r.report}"})
            if r.try_it:
                prepared.insert(0, {"label": "Try this", "text": r.try_it})
            if r.run_id:
                prepared.append({"label": f"The night's run, {r.run_id}", "href": f"/run/{r.run_id}"})
            out.append(Ask(
                source_id=str(r.number), key=decisions.key_of("nightly", r.number),
                title=f"Nightly feature, night {r.number}: {r.feature}",
                question=(r.built or r.feature)[:1600],
                why=(f"What it saves you: {r.saves}" if r.saves else ""),
                then=("Accept keeps it. Reject and undo turns it off at once"
                      + (f" (switch {r.switch})" if r.switch else "")
                      + ", reverts the code, deploys, and cancels everything it signed up for. "
                      "Something else is your own words, which tonight's run reads first."),
                link=f"/task/{folder}" if folder else "",
                context="Nightly Rouh feature run", project="Rouh", batch="nightly",
                options=[{"id": "accept", "label": "Accept",
                          "detail": "Keep the feature, and mark it accepted."},
                         {"id": "reject", "label": "Reject and undo", "go": True,
                          "detail": "Switch it off now, revert the code, redeploy, and cancel "
                                    "every trial, subscription and account it made."}],
                allow_other=True, answer_type="choice", urgency="soon",
                risk="reversible", prepared=prepared, asked_at=r.asked_at,
                history=[{"at": r.started_at, "kind": "raised",
                          "detail": f"Built by night {r.number}'s run {r.run_id}."}],
                yes_does=f"Accept keeps {r.feature.rstrip('.')} in your Rouh, as it is now.",
                wait_cost="Nothing waits on it: the feature stays on as it is."))
        return out

    def settled(self, who, row) -> Settled | None:
        from . import nightly_feature

        r = nightly_feature.night(who, row.source_id)
        if r is None:
            return Settled(decisions.WITHDRAWN, result="The night is gone.")
        if r.verdict:
            return Settled(decisions.APPLIED, said=r.verdict, result=f"Answered: {r.verdict}.")
        if _in_mutations(who, r.number):
            return Settled(decisions.WITHDRAWN,
                           result="Moved to Mutations (Evolution): its gene waits in To review, "
                                  "with Keep, Reject (which takes its code out, as Reject and undo "
                                  "did), Decide later and Mutate. Answering it there answers the night.")
        return None

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import nightly_feature

        answer = row.answer or {}
        choice = (answer.get("choice") or [""])[0]
        words = str(answer.get("text") or "").strip()
        r = await asyncio.to_thread(nightly_feature.night, who, row.source_id)
        if r is None:
            return Applied(False, "That night is gone.")
        if choice == "accept":
            await asyncio.to_thread(nightly_feature.decide, who, r, "accepted", words)
            return Applied(True, f"Accepted: “{r.feature}” stays.")
        if choice == "reject":
            try:
                said = await nightly_feature.undo(who, r)
            except Exception as exc:  # noqa: BLE001 - answered again once it can start
                log.exception("the nightly feature run's undo could not be started")
                return Applied(False, ("Its switch is off, but " if r.switch else "")
                               + f"the run that undoes it could not be started: {exc}")
            await asyncio.to_thread(nightly_feature.decide, who, r, "rejected", words)
            return Applied(True, said)
        if words:
            await asyncio.to_thread(nightly_feature.decide, who, r, "other", words)
            return Applied(True, "Kept for tonight's run, which reads your words first.")
        return Applied(False, "Accept, Reject and undo, or your own words.")


def _in_mutations(who, number) -> bool:
    from . import evolution

    try:
        return evolution.night_in_mutations(who, number)
    except Exception:
        log.exception("decisions: whether night %s is in Mutations could not be read", number)
        return False


class GeneSource(Source):
    """Mutations (`rouh/evolution.py`): every gene the nightly run built that waits on the
    person's answer, each a decision of its own that opens that gene's own page in Mutations.

    Petar, 13 October 2026, task 94 step 94-08, had them as one line for the night, "10 genes
    to review", and on 15 October (fr_fa2525969751) that line answered them too, all at once or
    one by one. Petar, 18 October 2026: "Every gene from the nightly run that waits on Petar is
    its own decision line, never one batch line", each linking to the gene's own page, where
    Keep, Reject, Decide later and Mutate are answered with everything there is to know. So the
    line is the gene: its name, one sentence on what it does for him, what Keep would do, and
    its number to say. Answering it on its page closes the line at once (`evolution._poke`), as
    answered there (`settled`).

    Since 18 October 2026 no gene waits on him (`evolution.waiting`): it is on, on trial, the
    moment it is built, so this makes no line, and only closes the ones left from before. Rouh's
    tool can still answer Keep on one (`apply`), as the gene's page would."""

    kind = "genes"
    label = "Mutations"
    tag = "Gene"
    own_page = True

    @staticmethod
    def source_of(g) -> str:
        return f"g{g.id}"

    def gate(self, who, ask):
        """A gene waiting on him is his to keep or reject: it changes his Rouh, and stays off
        (or as it is) until he answers. Petar asked the same day the gate shipped that each be
        a line of its own in Decisions (18 October 2026, "Every gene from the nightly run that
        waits on Petar is its own decision line"), so it is let through."""
        from . import decision_gate as gate

        return gate.let_through("A gene the nightly run built changes ‹his› Rouh only if ‹he› "
                                "keeps it, and ‹owner› asked for each to be a line in Decisions.")

    def collect(self, who) -> list[Ask] | None:
        """None waits on him since 18 October 2026: every gene is on, on trial, the moment it is
        built, and its trial decides by itself (Petar: "run automatically without my inputs").
        An open line from before is closed by `settled`."""
        return []

    def settled(self, who, row) -> Settled | None:
        """Answered on the gene's page: what became of it, said as his answer there."""
        from . import evolution

        if not row.source_id.startswith("g"):
            return Settled(decisions.WITHDRAWN, result="Each gene is its own decision now.")
        g = evolution._gene(who, row.source_id[1:])
        if g is None:
            return Settled(decisions.WITHDRAWN, result="The gene is not in Mutations any more.")
        said = evolution.STATE_NAMES.get(g.state, g.state)
        if g.state == "trial":
            # Since 18 October 2026 nothing about a gene waits on him: it is on, on trial.
            return Settled(decisions.WITHDRAWN, result=f"{g.name} is on, on trial; its trial "
                                                       "decides by itself.")
        if g.state in evolution.REVIEW and g.state != "later":
            return Settled(decisions.WITHDRAWN, result=f"{g.name}: {said}.")
        return Settled(decisions.APPLIED, said=said, channel="Mutations",
                       result=f"Answered on its page in Mutations: {said}.")

    async def apply(self, who, row, channel: str) -> Applied:
        """Keep or Decide later, as the gene's page would answer it. Reject, which asks why,
        and Mutate are answered on its page."""
        import asyncio

        from . import evolution

        picked = ((row.answer or {}).get("choice") or [""])[0]
        if picked != "keep":
            return Applied(False, "Keep; the rest is answered on the gene's page.")
        try:
            got = await asyncio.to_thread(evolution.answer, who, row.source_id.lstrip("g"), picked,
                                          channel="decisions")
        except evolution.Refused as exc:
            return Applied(False, str(exc))
        return Applied(True, str((got or {}).get("said") or
                                 "Passed: you kept it."))


class MeetingSource(Source):
    """Guests of a meeting within a day whom Rouh could not be sure of on LinkedIn
    (`rouh/meeting_people.py`).

    Petar, 7 October 2026: every guest of a meeting is looked up ahead of time, and a guest who
    is not surely one person is never harvested. Each such guest waits on their own contact card
    for his pick; only once the meeting is within `meeting_people.ASK_WITHIN` is he asked here,
    and then once for the whole meeting, never once a guest. The profile he picks is harvested
    and kept on that contact.

    Petar, 9 October 2026: "I should have the buttons to pick which of the two. Second I should
    be able to expand them and see the rest of the information you have on them." So every
    candidate is an answer of its own ("Dirk 1"), its short line under it and the rest of what
    is kept on it folded below (`decisions.more_of`); a press keeps that one, and the question
    stays open for any other guest still waiting. An answer in his own words is read for a name
    and a number first, and whatever that cannot read is read by a model against the candidates
    (`meeting_people.read_with_model`); words that fit more than one are asked about again,
    never failed.
    """

    kind = "meeting"
    label = "Meeting guests"
    tag = "Meeting"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.keep_back("Which LinkedIn profile is a guest's is Rouh's own preparation "
                              "for a meeting; nothing ‹he› asked for stops without it.",
                              "The guest stays unresolved on their contact card.")
    can_dismiss = True
    #: An option that picks a candidate: "<number>@<person id>".
    PICK = re.compile(r"^(\d{1,2})@(.+)$")

    @staticmethod
    def _summary(c: dict) -> str:
        return " - ".join(v for v in (c.get("name"), c.get("headline"), c.get("location")) if v)

    @classmethod
    def _choices(cls, waiting: list[dict]) -> tuple[list[dict], list[dict]]:
        """The answers for the guests whose candidates all fit on the card, nearest first, with
        None of them last; and the guests left for after (asked once these are answered)."""
        from . import meeting_people

        room = decisions.OPTIONS_MOST - 1
        firsts = [(w["name"] or "").split()[0] if (w["name"] or "").split() else "" for w in waiting]
        options, later = [], []
        for w, first in zip(waiting, firsts):
            found = w["linkedin"].get("candidates") or []
            if later or (options and len(found) > room - len(options)):
                later.append(w)
                continue
            # A first name two guests share would make two answers called the same.
            called = first if first and firsts.count(first) == 1 else (w["name"] or w["email"])
            for n, c in enumerate(found[:room - len(options)], 1):
                facts = [[k, c[f]] for k, f in (("Name on LinkedIn", "name"), ("Headline", "headline"),
                                                 ("Where", "location"), ("Profile", "url"))
                         if c.get(f)]
                facts.append(["Listed", f"Number {n} of the {len(found)} profiles LinkedIn found for {w['name']}"
                              if len(found) > 1 else f"The only profile LinkedIn found for {w['name']}"])
                options.append({"id": f"{n}@{w['pid']}"[:40], "label": f"{called} {n}",
                                "detail": cls._summary(c),
                                "more": {"facts": facts, "photo": c.get("photo") or "",
                                         "href": c.get("url") or "",
                                         "href_label": "Open the profile on LinkedIn"}})
        options.append({"id": "none", "label": "None of them",
                        "detail": "Leave them unresearched; Rouh will not ask about them again "
                                  f"for {meeting_people.AGAIN_DAYS} days."})
        return options, later

    def collect(self, who) -> list[Ask] | None:
        from . import clock, meeting_people

        if not _owner(who):
            return []
        try:
            waiting = meeting_people.meetings_waiting(who)
        except Exception:
            log.exception("decisions: the meetings' guests could not be read")
            return None
        out = []
        for m in waiting:
            options, later = self._choices(m["waiting"])
            now = [w for w in m["waiting"] if w not in later]
            reasons = [f"{w['name']}: {w['linkedin'].get('why') or 'not sure which'}." for w in now]
            prepared = [{"label": f"{w['name']} ({w['email']}), to pick after this", "text": "\n".join(
                f"{n}. {self._summary(c)}" for n, c in enumerate(w["linkedin"].get("candidates") or [], 1))}
                for w in later]
            names = [w["name"] for w in now]
            whose = (names[0] + "'s" if len(names) == 1 else
                     ", ".join(n + "'s" for n in names[:-1]) + " and " + names[-1] + "'s")
            when = clock.moment(m["start"])
            said_when = f"{when:%A} {when:%H:%M}" if when else ""
            after = (f" {len(later)} more at this meeting after these: "
                     + ", ".join(w["name"] for w in later) + "." if later else "")
            out.append(Ask(
                source_id=m["key"], key=decisions.key_of("meeting", m["key"]),
                title=f"Who is who at “{m['title']}”",
                question=(f"Which LinkedIn profile is {whose}? Pick it below, or say which in "
                          "your own words." if len(now) == 1 else
                          f"Which LinkedIn profiles are {whose}? Pick each one below, or say which "
                          "in your own words."),
                why=("Rouh could not tell, so nothing was kept for them yet. "
                     + " ".join(reasons) + after)[:1500],
                then=("The profile you pick is read from LinkedIn and kept on their contact as "
                      "their online research, with their photo if they have none. Nothing is "
                      "sent to anybody. Each one is also on their contact card, with a Research "
                      "button a candidate."),
                context=f"Meeting · {said_when}".strip(" ·"), project="", batch="meeting",
                options=options, allow_other=True, answer_type="choice", urgency="today",
                due_at=m["start"], prepared=prepared, risk="reversible",
                yes_does=("Reads the profile you pick from LinkedIn and keeps it on "
                          + (f"{names[0]}'s contact" if len(names) == 1 else "their contacts")
                          + ". Nothing is sent to anybody."),
                wait_cost=("Rouh's preparation for the meeting has nothing on "
                           + ("them" if len(names) > 1 else names[0] if names else "them")
                           + " until you pick; the question goes when the meeting begins.")))
        return out

    def settled(self, who, row) -> Settled | None:
        return Settled(decisions.WITHDRAWN,
                       result="Nobody at the meeting waits for a pick any more, or it has begun.")

    def _meeting(self, who, row) -> dict | None:
        from . import meeting_people

        return next((m for m in meeting_people.meetings_waiting(who) if m["key"] == row.source_id),
                    None)

    def _pressed(self, meeting: dict, choice: str) -> list:
        """The guest and the number an answer's button picks, or [] when it is not one."""
        hit = self.PICK.match(choice or "")
        if not hit:
            return []
        n = int(hit.group(1))
        for w in meeting["waiting"]:
            if (f"{n}@{w['pid']}"[:40] == choice
                    and 1 <= n <= len(w["linkedin"].get("candidates") or [])):
                return [(w, n)]
        return []

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import linkedin, meeting_people

        answer = row.answer or {}
        choice = (answer.get("choice") or [""])[0]
        words = str(answer.get("text") or "").strip()
        meeting = await asyncio.to_thread(self._meeting, who, row)
        if meeting is None:
            return Applied(True, "Nobody at that meeting waits for a pick any more.")
        asks = ""
        if choice == "none" and not words:
            picks, nones = [], list(meeting["waiting"])
        elif self._pressed(meeting, choice):
            picks, nones = self._pressed(meeting, choice), []
        elif choice and not words:
            # A button from before the candidates changed: nothing it named is waiting now.
            return Applied(False, "That profile is not one of the candidates any more.", reopen=True)
        else:
            picks, nones, unread = meeting_people.answer_words(who, meeting, words)
            if unread or not (picks or nones):
                read = await meeting_people.read_with_model(who, meeting, words)
                if read is not None:
                    picks, nones, asks = read.picks, read.nones, read.ask
                elif not (picks or nones):
                    return Applied(False, f"Rouh could not tell which profile “{words}” means: "
                                          "press the one you mean.", reopen=True)
        cfg = hooks.cfg
        apify = linkedin.Apify(getattr(cfg, "apify_api_token", "") or "",
                               getattr(cfg, "apify_url", "") or linkedin.APIFY_URL)
        said, failed = [], False
        for w, n in picks:
            url = (w["linkedin"].get("candidates") or [])[n - 1].get("url") or ""
            if not apify.ready():
                said.append(f"{w['name']}: LinkedIn research is not set up on this machine")
                failed = True
                continue
            got = await meeting_people.harvest_pick(who, apify, w["pid"], url,
                                                    meeting=meeting.get("title") or "")
            if got.get("ok"):
                said.append(f"{w['name']}: kept profile {n}")
            else:
                said.append(f"{w['name']}: {got.get('why')}")
                failed = True
        for w in nones:
            await asyncio.to_thread(meeting_people.none_of_them, who, w["pid"])
            said.append(f"{w['name']}: none of them")
        done = "; ".join(said) + "." if said else ""
        if asks:
            # Words that fit more than one: asked back, and the question stays open.
            return Applied(not failed, f"{done} {asks}".strip(), reopen=True)
        if failed:
            return Applied(False, done)
        left = await asyncio.to_thread(self._meeting, who, row)
        if left is not None:
            names = ", ".join(w["name"] for w in left["waiting"])
            return Applied(True, f"{done} Still to pick: {names}.".strip(), reopen=True)
        return Applied(True, done)

    def dismiss(self, who, row) -> str:
        return "Dismissed. They stay waiting on their contact cards."


class ContactPicksSource(MeetingSource):
    """The contacts added from his meetings whom Rouh could not be sure of on LinkedIn, asked
    about once for them all (`rouh/meeting_contacts.py`).

    Petar, 22 October 2026, of the guests added to his contacts and looked up on LinkedIn: "Only
    if many contacts end up waiting for a pick, put one single decision for Petar listing them,
    not one per person." So each such contact waits on their own card for his pick, as a
    meeting's guest does, and once `meeting_contacts.MANY_WAITING` of them wait, one question
    lists them all, with their candidates as the meeting's question has them; it stays open
    while any of them still waits. Somebody a meeting within a day already asks about is left to
    that meeting's question. There is no None of them for everybody at once: his words say who
    is none of them ("Elena none").
    """

    kind = "contact_picks"
    label = "Contacts to pick on LinkedIn"
    tag = "Contacts"
    KEY = "contacts"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("‹Owner› asked on 22 October 2026 for one question listing the "
                                "contacts that wait for ‹his› pick of their LinkedIn profile, once "
                                "many of them do.")

    def _waiting(self, who) -> list[dict]:
        from . import meeting_contacts, meeting_people

        asked = {w["pid"] for m in meeting_people.meetings_waiting(who) for w in m["waiting"]}
        return [w for w in meeting_contacts.waiting_for_pick(who) if w["pid"] not in asked]

    def _meeting(self, who, row) -> dict | None:
        waiting = self._waiting(who)
        return {"key": self.KEY, "title": "", "start": 0, "waiting": waiting} if waiting else None

    def collect(self, who) -> list[Ask] | None:
        from . import meeting_contacts

        if not _owner(who):
            return []
        try:
            waiting = self._waiting(who)
        except Exception:
            log.exception("decisions: the contacts waiting for a LinkedIn pick could not be read")
            return None
        if not waiting:
            return []
        from .models import Decision

        # Once asked, it is asked until nobody waits, however few are left.
        open_now = Decision.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""),
                                           source=self.kind, source_id=self.KEY,
                                           status__in=decisions.WAITING).exists()
        if len(waiting) < meeting_contacts.MANY_WAITING and not open_now:
            return []
        options, later = self._choices(waiting)
        options = [o for o in options if o["id"] != "none"]
        now = [w for w in waiting if w not in later]
        prepared = [{"label": f"{w['name']} ({w['email']}), to pick after these", "text": "\n".join(
            f"{n}. {self._summary(c)}" for n, c in enumerate(w["linkedin"].get("candidates") or [], 1))}
            for w in later]
        names = ", ".join(w["name"] for w in waiting)
        n = len(waiting)
        return [Ask(
            source_id=self.KEY, key=decisions.key_of(self.kind, self.KEY),
            title=f"Which LinkedIn profile is theirs: {n} contact{'s' if n != 1 else ''} from your meetings",
            question=("Which LinkedIn profile is each of them? Pick below, or say which in your own "
                      "words, such as “Sam 2, Elena none”."),
            why=(f"Rouh could not be sure of {n} of the people it added from your meetings: {names}. "
                 + " ".join(f"{w['name']}: {w['linkedin'].get('why') or 'not sure which'}." for w in now))[:1500],
            then=("The profile you pick is read from LinkedIn and kept on their contact as their "
                  "online research, with their photo if they have none. Nothing is sent to anybody "
                  "and nothing is written to iCloud."),
            context="Contacts from your meetings", project="", batch="contacts",
            options=options, allow_other=True, answer_type="choice", urgency="whenever",
            prepared=prepared, risk="reversible",
            yes_does="Reads the profile you pick from LinkedIn and keeps it on their contact in Rouh. "
                     "Nothing is sent to anybody.",
            wait_cost="Nothing waits on it: they stay unresearched, each with the candidates on their "
                      "contact card.")]

    def settled(self, who, row) -> Settled | None:
        return Settled(decisions.WITHDRAWN, result="No contact waits for a pick any more.")


class AfterMeetingSource(Source):
    """The work a meeting he just had calls for, which Rouh can start (`rouh/meeting_next.py`).

    Night 6 of the nightly feature run, 9 October 2026 (task 94, I-073): once a meeting's notes
    reach his memory from the meeting library, one model call says which work it calls for
    that Rouh can do by itself, at most three pieces, each with why. One question for the
    meeting holds them as its items: Start all, Not needed, or each on its own. Start begins a
    run of his assistant briefed with the meeting's notes, filed in the task named; nothing is
    sent to anybody. Behind the switch `meeting_next`: off, nothing is asked.
    """

    kind = "after_meeting"
    label = "After meetings"
    tag = "After a meeting"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.keep_back("Work Rouh could start after a meeting is a suggestion, not work "
                              "‹he› asked for that stopped.",
                              "Nothing is started.")
    can_dismiss = True

    def _waiting(self, who) -> list[tuple[str, dict, list[dict]]] | None:
        from . import meeting_next

        if not _owner(who):
            return []
        try:
            if not meeting_next.on(who):
                return []
            said = meeting_next.answered(who)
            out = []
            for mid, one in meeting_next.made(who).items():
                waiting = [w for w in one.get("work") or [] if w.get("id") not in (said.get(mid) or {})]
                if waiting:
                    out.append((mid, one, waiting))
            return out
        except Exception:
            log.exception("decisions: the work after meetings could not be read")
            return None

    @staticmethod
    def _item(work: dict) -> dict:
        task = (f"In task {work['task']}, {work['task_title']}." if work.get("task")
                else "In a new task of its own.")
        day = datetime_at(work["by"]) if work.get("by") else None
        by = f" Needed by {_day_words(day)}." if day else ""
        return {"id": work["id"], "label": work["do"],
                "detail": f"{task}{by} What the run is told: {work['brief']}"[:1200],
                "why": work.get("why") or ""}

    def collect(self, who) -> list[Ask] | None:
        from . import clock

        waiting = self._waiting(who)
        if waiting is None:
            return None
        out = []
        for mid, one, work in waiting:
            n = len(work)
            title = one.get("title") or "the meeting"
            when = clock.moment(one.get("end") or 0)
            said_when = f"{when:%A %-d %B, %H:%M}" if when else ""
            soonest = min((w["by"] for w in work if w.get("by")), default="")
            out.append(Ask(
                source_id=mid, key=decisions.key_of("after_meeting", mid, one.get("version"),
                                                    *[w["id"] + w["do"] for w in one.get("work") or []]),
                title=f"After “{title}”: {n} piece{'s' if n != 1 else ''} of work Rouh can start",
                question=(f"Rouh read the notes of “{title}”. Should it start "
                          + ("this?" if n == 1 else "these? Start all, or decide each one.")),
                why=(work[0].get("why") or "" if n == 1 else
                     "Read from the meeting's notes, which Mutations already shows you; each piece "
                     "of work below says why the meeting calls for it.")[:1500],
                then=("Start begins a run of your assistant, already briefed with the meeting's notes, "
                      "that writes what it makes into the task named; it comes back to that task's chat. "
                      "Nothing is sent to anybody: anything for somebody else is a draft for you. "
                      "Not needed drops it."),
                link=(f"/synapse/{one['dataset']}/item/{mid}" if one.get("dataset") else ""),
                context=f"Meeting · {said_when}".strip(" ·"), project="", batch="after_meeting",
                options=[{"id": "start", "label": f"Start all {n}" if n > 1 else "Start it",
                          "each": "Start",
                          "detail": "Start a run for each, briefed with the meeting's notes."
                          if n > 1 else "Start a run for it, briefed with the meeting's notes."},
                         {"id": "skip", "label": "Not needed", "each": "Not needed",
                          "detail": "Drop it; nothing is started." if n == 1
                          else "Drop them all; nothing is started."}],
                allow_other=False, answer_type="choice", urgency="today", risk="reversible",
                due_at=(datetime_at(soonest) if soonest else None),
                items=[self._item(w) for w in work] if n > 1 else [],
                prepared=([{"label": work[0]["do"], "text": self._item(work[0])["detail"]}]
                          if n == 1 else []),
                asked_at=one.get("at"),
                history=[{"at": one.get("at") or 0, "kind": "raised",
                          "detail": f"Read from the meeting's notes by {one.get('model') or 'the model'}."}],
                yes_does=(f"Starts {'a run' if n == 1 else f'{n} runs'} of your assistant, briefed "
                          "with the meeting's notes: "
                          + "; ".join(str(w.get("do") or "").rstrip(".") for w in work[:3])
                          + ". Nothing is sent to anybody."),
                wait_cost="Nothing starts until you answer."))
        return out

    def settled(self, who, row) -> Settled | None:
        from . import meeting_next

        try:
            if not meeting_next.on(who):
                return Settled(decisions.WITHDRAWN, result="Its switch, meeting_next, is off.")
            one = meeting_next.made(who).get(str(row.source_id))
            said = meeting_next.answered(who).get(str(row.source_id)) or {}
        except Exception:
            return None
        if one is None:
            return Settled(decisions.WITHDRAWN, result="The meeting is no longer read.")
        if all(w.get("id") in said for w in one.get("work") or []):
            started = sum(1 for v in said.values() if v.get("said") == "start")
            return Settled(decisions.APPLIED, said="Every piece decided",
                           result=f"Every piece of work decided: {started} started.")
        return Settled(decisions.WITHDRAWN, result="It asks this again with what is left.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import meeting_next

        answer = row.answer or {}
        each = dict(answer.get("items") or {})
        work = await asyncio.to_thread(meeting_next.left, who, row.source_id)
        if not each:
            choice = (answer.get("choice") or [""])[0]
            each = {w["id"]: choice for w in work}
        if not each or any(v not in ("start", "skip") for v in each.values()):
            return Applied(False, "Start, or Not needed.")
        by_id = {w["id"]: w for w in work}
        started, skipped, failed, gone = [], 0, [], 0
        for item, verdict in each.items():
            w = by_id.get(item)
            if w is None:
                gone += 1
                continue
            if verdict == "skip":
                await asyncio.to_thread(meeting_next.mark, who, row.source_id, item, "skip")
                skipped += 1
                continue
            got = await meeting_next.start(who, row.source_id, w)
            if got.get("ok"):
                await asyncio.to_thread(meeting_next.mark, who, row.source_id, item, "start",
                                        run=got.get("run") or "")
                started.append(f"“{w['do']}”" + (f" (run {got['run']})" if got.get("run") else ""))
            else:
                failed.append(f"“{w['do']}”: {got.get('why')}")
        said = []
        if started:
            said.append("Started " + ", ".join(started))
        if skipped:
            said.append(f"{skipped} not needed")
        if gone:
            said.append(f"{gone} already decided")
        if failed:
            said.append("could not start " + "; ".join(failed))
        result = ("; ".join(said) or "Nothing was done") + "."
        rest = await asyncio.to_thread(meeting_next.left, who, row.source_id)
        return Applied(not failed, result, reopen=bool(rest))

    def dismiss(self, who, row) -> str:
        from . import meeting_next

        for w in meeting_next.left(who, row.source_id):
            meeting_next.mark(who, row.source_id, w["id"], "skip", why="dismissed")
        return "Dismissed: nothing from that meeting is started."


def _day_words(at: float) -> str:
    from . import clock

    when = clock.moment(at)
    return f"{when:%A} {when.day} {when:%B}" if when else ""


def datetime_at(day: str) -> float | None:
    """The end of a day (YYYY-MM-DD) on the person's clock, as a moment."""
    from datetime import datetime

    from . import clock

    try:
        got = datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59)
    except ValueError:
        return None
    return got.replace(tzinfo=clock.zone()).timestamp()


# --- mail and Telegram cases --------------------------------------------------------------


class MailSource(Source):
    """A case's one decision: what of an email or a Telegram message waits for Petar (D8).

    Petar, 11 October 2026: "A mail case gets one decision listing its waiting asks. It is
    regenerated whenever the ledger changes, and the old one is superseded automatically, so a
    stale plan can never be carried out." Each case holds at most one pending `MailApproval`,
    made from its ledger (`mail_cases.CaseDesk.sync_decision`), and keyed here on its
    fingerprint, which moves whenever what it lists moves; the old row is then withdrawn, never
    answered.

    Each ask that only he moves is an item: waiting for his decision, failed (his run tries it
    again), or approved and not yet run. "Approve and run" gives each waiting ask what it needs
    for good where a grant can be given (a new one set up as Rouh's reading proposed it), lets
    a hard limit or one for somebody not on his Trusted contacts go once, and then starts it
    - the same code as the case page's saved choices and its Redo. "Allow once and run" lets each
    go this once. "Decline" declines them, the only refusal there is. "Open the case" is a link.
    Every answer is one batch (D18): what he approved starts, and one message tells the contact
    all of it, with his own words beside a decline when he wrote some. His words alone run the
    case again, reading the message first, with them.
    """

    kind = "mail"
    label = "Message"
    tag = "Message"
    own_page = True

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("Somebody's message waits for ‹his› permission for Rouh to act or "
                                "reply in ‹his› name.")
    notifies = True

    @staticmethod
    def _step(approval) -> str:
        """The case page's step for this decision, `#approval-N`: the Nth decision its case
        asked for (`case_trace`), which a line opens at."""
        from .models import MailApproval

        n = MailApproval.objects.filter(user_id=approval.user_id, org_id=approval.org_id,
                                        case_id=approval.case_id, id__lte=approval.id).count()
        return f"#approval-{max(n, 1)}"

    @staticmethod
    def _key(approval) -> str:
        return decisions.key_of("mail", approval.id, approval.fingerprint)

    def _waiting(self, who) -> list[tuple]:
        """(case, decision) for every case's pending decision, oldest first."""
        from .models import MailApproval, MailCase

        whose = {"user_id": str(who.user_id), "org_id": str(who.org_id)}
        asked = list(MailApproval.objects.filter(**whose, status="pending", kind="asks")
                     .order_by("id"))
        if not asked:
            return []
        cases = {c.id: c for c in MailCase.objects.filter(
            **whose, id__in=[a.case_id for a in asked])}
        return [(cases[a.case_id], a) for a in asked if a.case_id in cases and a.asks]

    def collect(self, who) -> list[Ask] | None:
        from . import case_state, mail_cases, mail_outbox
        from .models import TrustedContact

        out = []
        waiting_cases = self._waiting(who)
        # Whether each sender is on his Trusted contacts, and switched on, as that page has
        # them now: what a trusted contact's grants cover runs without him, so a decision from
        # one is only ever what goes beyond them, and the card says so first (fr_93833fb07db1).
        listed = dict(TrustedContact.objects.filter(
            user_id=str(who.user_id), org_id=str(who.org_id),
            id__in=[c.contact_id for c, _ in waiting_cases if c.contact_id])
            .values_list("id", "trusted")) if waiting_cases else {}
        for case, approval in waiting_cases:
            name = case.sender_name or case.sender
            first = mail_cases.first_name(name) or name
            trusted = listed.get(case.contact_id) if case.contact_id else None
            standing_why = (f"{first} is a trusted contact: what their grants cover runs without "
                            "you, and only what goes beyond them waits here. "
                            if trusted else
                            f"{first} is on your Trusted contacts and switched off, so everything "
                            "from them waits for you. "
                            if trusted is False else
                            f"{first} is not on your Trusted contacts, so Rouh may only answer "
                            "them without you. ")
            noun = mail_cases._noun(case)
            kind_said = mail_cases.CHANNELS.get(mail_cases.channel_of(case), ("Message",))[0]
            waiting = [i for i in approval.asks if _status(i) == "waiting_for_owner"]
            failed = [i for i in approval.asks if i.get("status") == "failed"
                      and not i.get("possible")]
            # Failed, and a run would do it now (`mail_ledger.rejudge`, D15): run it, nothing
            # to choose.
            ready = [i for i in approval.asks if i.get("status") == "failed"
                     and i.get("possible")]
            approved = [i for i in approval.asks if i.get("status") in ("approved", "allowed")]
            items = []
            for i in approval.asks:
                words = i.get("label") or i.get("ask") or ""
                proposed = i.get("proposal") or {}
                items.append({
                    "id": i["id"], "label": f"\u201c{i.get('ask') or words}\u201d",
                    "detail": (i.get("why") or f"Needs {i.get('need')}."
                               if _status(i) == "waiting_for_owner" else
                               "Failed" + (f": {i['why'].rstrip('.')}" if i.get("why") else "")
                               + f". A run does it: {i['possible']}"
                               if i.get("possible") else
                               {"failed": "Failed",
                                "approved": "Approved by you, not run yet",
                                "allowed": "Allowed, not run yet"}.get(
                                    i.get("status"), i.get("status") or "") + (
                                   f". {i['why']}" if i.get("why") else "")),
                    "options": [o for o in ("grant", "once", "decline", "mine")
                                if o in (i.get("options") or [])],
                    # Letting them edit a task is no grant, and is not called one (D28).
                    **({"names": {"grant": f"Let {first} edit task {i['task']}"}}
                       if i.get("task") else {}),
                    # A grant Rouh's code proposes: the one sentence it gives, made from its
                    # fields, is what Give says (CAPABILITIES.md).
                    **({"names": {"grant": "Give: " + proposed.get("wording", "")},
                        "grant_wording": proposed.get("wording", "")}
                       if proposed.get("wording") and not i.get("task") else {})})
            parts = []
            if waiting:
                parts.append(f"{len(waiting)} wait{'s' if len(waiting) == 1 else ''} for you")
            if failed:
                parts.append(f"{len(failed)} failed")
            if ready:
                parts.append(f"{len(ready)} ready to run")
            if approved:
                parts.append(f"{len(approved)} allowed or approved, not run yet")
            question = (f"What of {first}'s {noun} may Rouh do?"
                        if case_state.choosing(approval.asks) else
                        f"Run {first}'s {noun} again?")
            sent = [{"part": "sent", "label": "What they had from Rouh already",
                     "text": m["text"], "when": f"{m['kind_said']} by {m['channel']}"
                     + (" (did not go)" if m["state"] not in ("sent", "unknown") else ""),
                     "hint": ""}
                    for m in mail_outbox.views(case.user_id, case.org_id, case.id)][-3:]
            later = [x for x in case.later or [] if isinstance(x, dict)]
            def line(i: dict, said: str) -> str:
                words = str(i.get("label") or i.get("ask") or "")
                words = words if len(words) <= 90 else words[:89].rsplit(" ", 1)[0] + "\u2026"
                return f"\u201c{words}\u201d: " + str(said or "").strip().rstrip(".")
            why = "; ".join(line(i, f"needs {i.get('need')}" if i in waiting else
                                 f"failed, and a run does it: {i['possible']}"
                                 if i in ready else i.get("why") or i.get("status"))
                            for i in (waiting + failed + ready or approval.asks)[:6]) + "."
            if (waiting or failed) and (approved or ready):
                why += (f" {len(approved) + len(ready)} more ready to run: they run with "
                        "these.")
            if not (waiting or failed):
                gone = len(approved) + len(ready)
                why = (f"Nothing waits for a choice: {gone} "
                       f"ask{'s' if gone != 1 else ''} ready to run. " + why)
            if later:
                why += (f" {first} wrote again since: \u201c"
                        + str(later[-1].get("summary") or later[-1].get("words") or "")[:200]
                        + "\u201d")
            gives = [str((i.get("proposal") or {}).get("wording") or "") for i in waiting
                     if (i.get("proposal") or {}).get("wording") and "grant" in (i.get("options") or [])]
            choosing = case_state.choosing(approval.asks)
            options = case_state.decision_options(
                approval.asks, link=mail_cases.case_path(case.key))
            # What it is, in plain words: whose message, about what, and the task it is
            # about when one ask names one.
            about = (case.subject if case.subject and mail_cases.channel_of(case) == "email"
                     else "")
            tasks = sorted({str(i["task"]) for i in approval.asks if i.get("task")})
            asked = [str(i.get("ask") or i.get("label") or "").strip().rstrip(".")
                     for i in (waiting + failed + ready + approved)][:3]
            asked = [a if len(a) <= 90 else a[:89].rsplit(" ", 1)[0] + "\u2026" for a in asked if a]
            then = (("Approve and run gives each what it needs - the grant, or the edit "
                     "permission of the task, for good where one can be given, once where not - "
                     "and starts it: one message tells "
                     f"{first} what you approved and has started, and each started one sends its "
                     "own result when it is done. Allow once and run lets each go this once. "
                     f"Decline declines them, and the same one message tells {first} they will "
                     "not be done. ")
                    if choosing else
                    (f"Run it now starts what is allowed and approved, and one message tells "
                     f"{first} it has started. ")) + (
                f"Your own words run the {noun} again, read with them. To set a new grant up "
                "another way first, open the case.")
            out.append(Ask(
                source_id=str(approval.id), key=self._key(approval),
                title=(f"{kind_said} from {name}" + (f" about {about}" if about else "")
                       + (f", task {', '.join(tasks)}" if tasks else "")),
                question=question,
                why=(standing_why + why.strip())[:1500],
                then=then,
                link=mail_cases.case_path(case.key) + self._step(approval),
                context=f"{kind_said} from {name}" + (f" \u00b7 {case.subject}"
                                                      if case.subject and
                                                      mail_cases.channel_of(case) == "email"
                                                      else ""),
                project="", batch=f"mail:{case.key}",
                options=options,
                allow_other=True, answer_type="choice", urgency="today", risk="reversible",
                risk_note="A grant can be changed or taken back in Settings, and every change to "
                          "one is kept as a version.",
                items=items if choosing and len(items) > 1 else [], prepared=sent,
                asked_at=approval.asked_at,
                history=[{"at": approval.asked_at, "kind": "raised",
                          "detail": f"{name}'s {noun}: " + ", ".join(parts) + "."}],
                yes_does=((f"Approve and run does what {first} asked"
                           + (": " + "; ".join(f"\u201c{a}\u201d" for a in asked) if asked else "")
                           + f", and one message tells {first} it has started."
                           # The grant it gives, in the one sentence code made from exactly
                           # what is given, which the answer is bound to (CAPABILITIES.md).
                           + "".join(f" It gives: {g}" for g in gives))
                          if choosing else
                          ("Runs what is allowed and approved"
                           + (": " + "; ".join(f"\u201c{a}\u201d" for a in asked) if asked else "")
                           + f", and one message tells {first} it has started.")),
                wait_cost=f"{first} waits: nothing of their {noun} is done until you answer.",
                blocks=True,
                tags=[kind_said if mail_cases.channel_of(case) != "email" else ""]))
        return out

    def settled(self, who, row) -> Settled | None:
        from .models import MailApproval

        try:
            ident = int(row.source_id)
        except ValueError:
            return None
        a = MailApproval.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                        id=ident).first()
        if a is None:
            return Settled(decisions.WITHDRAWN, result="It is not there any more.")
        if a.status == "approved":
            return Settled(decisions.APPLIED, channel="case page",
                           said=a.instruction or "Decided on its asks")
        if a.status == "pending":
            return Settled(decisions.WITHDRAWN, result="What waits changed since, so it is "
                                                      "asked again as a new decision.")
        return Settled(decisions.WITHDRAWN, result=a.why_invalid or "It is not asked any more.")

    def _current(self, who, row):
        from .models import MailApproval, MailCase

        try:
            ident = int(row.source_id)
        except ValueError:
            return None
        a = MailApproval.objects.filter(user_id=row.user_id, org_id=row.org_id, id=ident,
                                        status="pending").first()
        if a is None:
            return None
        case = MailCase.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                       id=a.case_id).first()
        return (case, a) if case is not None else None

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from .tenancy import Identity

        desk = hooks.mail_desk() if hooks.mail_desk is not None else None
        if desk is None:
            return Applied(False, "New mail is not handled on this server, so nothing could "
                                  "take your answer.")
        got = row.answer or {}
        choice = (got.get("choice") or [""])[0]
        words = str(got.get("text") or "").strip()
        found = await asyncio.to_thread(self._current, who, row)
        if found is None:
            return Applied(False, "That decision is no longer open: what waits changed since, "
                                  "and it is asked again as it is now.")
        case, approval = found
        if self._key(approval) != row.key:
            return Applied(False, "What it asks changed after you saw it, so nothing was done. "
                                  "Look at it again.")
        me = Identity(user_id=str(row.user_id), org_id=str(row.org_id))
        try:
            if words and not choice and not got.get("items"):
                said = await desk.redo(me, case.key, attempt=case.attempt_no,
                                       instruction=words, by_decision=True)
                return Applied(True, f"Run again with your words. {said}")
            each = dict(got.get("items") or {})
            if choice and not each:
                each = {str(i.get("id")): choice for i in approval.asks}
            # What an item cannot take, it takes the nearest it can: a hard limit is allowed
            # once when "for good" was picked for all of them.
            choices = {}
            for item in approval.asks:
                pick = each.get(str(item.get("id")))
                if not pick:
                    continue
                if pick not in (item.get("options") or []):
                    pick = "once" if pick == "grant" and "once" in (item.get("options") or []) \
                        else pick
                if pick in (item.get("options") or []):
                    # A grant Rouh proposed is given exactly as this decision showed it: its
                    # digest goes with the answer, and nothing else is given (CAPABILITIES.md).
                    choices[str(item["id"])] = {"choice": pick, "digest": item.get("digest") or ""}
            if not choices and (choice in ("grant", "once", "run") or
                                any(v in ("grant", "once") for v in each.values())):
                # Nothing left to decide - only what he approved and was not run yet, or what
                # failed: run it.
                said = await desk.redo(me, case.key, attempt=case.attempt_no, by_decision=True)
                return Applied(True, said)
            # Every answer here is one batch of his decisions: it runs, so what he approved
            # starts and one message tells them the whole of it, declines too (D18).
            said = await desk.decide_asks(me, case.key, approval_id=approval.id,
                                          choices=choices, run=True,
                                          reason=words if any(
                                              c["choice"] in ("decline", "mine")
                                              for c in choices.values()) else "")
        except (ValueError, LookupError) as exc:
            return Applied(False, str(exc))
        return Applied(True, said)


class DelegateSource(Source):
    """What a trusted contact who decides for a piece of work wanted that stays Petar's
    (`rouh/delegation.py`, `hold_for_owner`): spending, sending, publishing, committing him,
    or something they asked for that would. Their recommendation and their exact words are
    on it, attributed to them.

    Yes or no, with his words, is said in the work's own chat as his answer to what they
    asked, so Rouh carries it on there; nothing is done before he answers. A decision of
    theirs on a decision that already exists is not one of these: it is drawn on that
    decision's own card (`decisions.with_delegates`)."""

    kind = "delegate"
    label = "From a delegate"
    tag = "Delegate"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("A delegate asked for something that stays ‹his›: money, "
                                "deleting, publishing, sending or committing ‹him›.")
    can_dismiss = True
    text_acts = True

    #: The risk of what was held, from the action it is - never from words in what was asked
    #: (Petar, 21 October 2026: a request for a timeline that mentioned his steps of paying was
    #: held as moving money). What spends, charges or moves money is an action of its own.
    _RISK = {"money": "money", "send": "sending", "publish": "publishing",
             "delete": "irreversible", "commit": "irreversible", "rouh": "irreversible"}

    @classmethod
    def risk_of(cls, a) -> str:
        from . import delegation

        part = delegation.NEVER_ACTS.get(str(a.act or "").lower()) or \
            delegation.NEVER_ACTS.get(str((a.asked or {}).get("do") or "").lower())
        return cls._RISK.get(part or "", "irreversible")

    @staticmethod
    def done_since(a):
        """The later action that did what this held one asked for, in the same message: the
        same act on the same work with the same words, done (delegate act 18 after 17). None
        when there is none."""
        from . import delegation
        from .models import DelegateAct

        if not a.case_id:
            return None
        for d in DelegateAct.objects.filter(user_id=a.user_id, org_id=a.org_id,
                                            case_id=a.case_id, act=a.act, target=a.target,
                                            outcome="done", id__gt=a.id).order_by("id"):
            if delegation._norm(d.words) == delegation._norm(a.words):
                return d
        return None

    @staticmethod
    def case_decision(a):
        """The decision of the mail case this was held in, while it is open: the one decision
        the same request already has (Petar, 21 October 2026: one ask, one decision)."""
        from .models import Decision, MailCase

        if not a.case_id:
            return None
        key = MailCase.objects.filter(user_id=a.user_id, org_id=a.org_id, id=a.case_id) \
            .values_list("key", flat=True).first()
        if not key:
            return None
        return Decision.objects.filter(user_id=a.user_id, org_id=a.org_id, source="mail",
                                       batch=f"mail:{key}",
                                       status__in=decisions.ANSWERABLE).first()

    def _rows(self, who):
        from .models import DelegateAct

        out = []
        for a in DelegateAct.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id),
                                            outcome__in=("for_owner", "for_petar"),
                                            decision_id__isnull=True).order_by("at"):
            if self.done_since(a) is not None:
                continue
            found = self.case_decision(a)
            if found is not None:
                # Drawn on the case's own decision as their recommendation, and not asked
                # again as a decision of its own.
                DelegateAct.objects.filter(id=a.id, decision_id__isnull=True).update(
                    decision_id=found.id, handle=str(found.number or ""))
                continue
            out.append(a)
        return out

    def _work(self, who, a) -> tuple[str, str]:
        """(its chat's folder, its address) for the goal or quest it was about."""
        from . import quests
        from .models import Task

        if a.target_kind == "quest":
            q = quests.get(who, a.target)
            task = quests.task_of(q) if q is not None else None
            return (getattr(task, "folder", "") or "", quests.address(q) if q else "")
        task = Task.objects.filter(id=a.target).first() if a.target else None
        folder = getattr(task, "folder", "") or ""
        return folder, ("/task/" + folder if folder else "")

    def collect(self, who) -> list[Ask] | None:
        if not _owner(who):
            return None
        try:
            rows = self._rows(who)
        except Exception:
            log.exception("decisions: what delegates held for him could not be read")
            return None
        out = []
        for a in rows:
            risk = self.risk_of(a)
            _folder, link = self._work(who, a)
            kind = (a.target_kind or "work").title()
            what = " ".join(str(a.said or a.words or "").split()).rstrip(".")
            where = f"{kind.lower()} {a.number}" if a.number else (a.title or "the work")
            out.append(Ask(
                source_id=str(a.id), key=decisions.key_of("delegate", a.id),
                title=f"{a.contact_name} asks for your yes on {where}",
                question=(a.said or a.words)[:1200],
                why=(f"It stays yours: {a.why}." if a.why else "")
                + (f" Their words: \u201c{a.words}\u201d" if a.words else ""),
                then=("Your answer is said in the work's own chat as yours, and Rouh carries it "
                      "on from there. Nothing is done before you answer."),
                link=link, context=(f"{kind} {a.number} · {a.title}" if a.number else a.title),
                project="Delegated", batch=f"delegate:{a.contact_id}",
                options=[{"id": "yes", "label": "Yes, go ahead", "go": True,
                          "detail": f"As {a.contact_name} recommends."},
                         {"id": "no", "label": "No", "detail": "Nothing is done."}],
                allow_other=True, answer_type="approval", urgency="today", risk=risk,
                risk_note=a.why[:600], asked_at=a.at,
                history=[{"at": a.at, "kind": "raised",
                          "detail": f"{a.contact_name} asked for it by {a.channel or 'email'}; "
                                    "held for you."}],
                yes_does=(f"It goes ahead as {a.contact_name} asked: {what}." if what else ""),
                wait_cost=f"Nothing of it is done on {where} until you answer.", blocks=True))
        return out

    def settled(self, who, row) -> Settled | None:
        from .models import DelegateAct

        a = DelegateAct.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                       id=int(row.source_id)).first() \
            if str(row.source_id).isdigit() else None
        if a is None:
            return Settled(decisions.WITHDRAWN, result="It is not there any more.")
        if a.outcome == "answered":
            return Settled(decisions.APPLIED, said=a.undone_said or "Answered",
                           result="Answered.")
        done = self.done_since(a)
        if done is not None:
            said = " ".join(str(done.said or "").split()).rstrip(".")
            return Settled(decisions.APPLIED, by="itself",
                           said=f"Done already: {said}." if said else "Done already.",
                           result=(f"Closed by itself: {a.contact_name} had it done within "
                                   f"their own authority right after it was held ({said})."))
        if a.decision_id and a.decision_id != row.id:
            return Settled(decisions.WITHDRAWN,
                           result="It is one ask with the decision of the email it came in, "
                                  "where their recommendation is drawn.")
        return Settled(decisions.WITHDRAWN, result="It is not held for you any more.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from .models import DelegateAct

        a = await asyncio.to_thread(lambda: DelegateAct.objects.filter(
            user_id=row.user_id, org_id=row.org_id, id=int(row.source_id)).first())
        if a is None:
            return Applied(False, "It is not there any more.")
        got = row.answer or {}
        said = got.get("said") or ""
        folder, _link = await asyncio.to_thread(self._work, who, a)
        text = (f"{a.contact_name}, who decides for this by my grant, asked for something that "
                f"is mine to decide: {a.said}"
                + (f"\nTheir words: \u201c{a.words}\u201d" if a.words else "")
                + f"\nMy answer: {said}")
        where = ""
        if folder and hooks.deliver_task is not None:
            chat, title = await hooks.deliver_task(folder, text)
            where = f" Said in the work's chat{', ' + title if title else ''}." if chat else ""
        await asyncio.to_thread(lambda: DelegateAct.objects.filter(id=a.id).update(
            outcome="answered", undone_said=said[:300]))
        return Applied(True, f"Answered: {said}.{where}")

    def dismiss(self, who, row) -> str:
        from .models import DelegateAct

        DelegateAct.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                   id=int(row.source_id)).update(outcome="answered",
                                                                 undone_said="Dismissed")
        return "Dismissed: nothing was done."


class CaseFixSource(Source):
    """A run fixing a false alarm's check that failed, or stopped because only loosening a
    safety rule would fix it (`rouh/case_fixes.py`).

    Petar, 8 October 2026: marking a step of a case a false alarm starts a run that fixes the
    check; when it fails, or would have to loosen a rule about money, sending outside,
    publishing, private data, anything irreversible or taking a message as instructions, it
    says so plainly with what is needed from him, and that is a decision here. Try again
    starts a new fix run on the same step, with his words as its reason; Leave it closes it,
    and the check goes on stopping messages like that one.
    """

    kind = "casefix"
    label = "Check fix"
    tag = "Check fix"
    own_page = True

    def gate(self, who, ask):
        from . import decision_gate as gate

        if ask.title.endswith("needs your decision"):
            return gate.let_through("The only fix would loosen a safety rule, which is ‹his› to "
                                    "decide.")
        return gate.keep_back("A fix that did not work is Rouh's to look at again; meanwhile the "
                              "check goes on stopping such messages, which is safe.",
                              "The check is left as it is.")
    text_acts = True
    notifies = True

    def collect(self, who) -> list[Ask] | None:
        from . import case_fixes, mail_cases

        try:
            rows = case_fixes.waiting(who)
        except Exception:
            log.exception("decisions: the check fixes could not be read")
            return None
        out = []
        for r in rows:
            case = r.case
            s = r.summary or {}
            name = case.sender_name or case.sender
            needs = r.outcome in ("needs_owner", "needs_petar")
            said = (s.get("needs") if needs else (r.why or s.get("why"))) or ""
            out.append(Ask(
                source_id=str(r.id), key=decisions.key_of("casefix", r.id, r.outcome, said),
                title=(f"Check fix for {name}'s {mail_cases._noun(case)}, {r.step}: "
                       + ("needs your decision" if needs else "did not work")),
                question=(said or "The run ended without saying what it did.")[:1600],
                why=(f"Found: {s['cause']}" if s.get("cause") else ""),
                then=("Try again starts a new run on the same step, with your words as its "
                      "reason. Leave it keeps the check as it is: messages like this one go on "
                      "being stopped for you."),
                link=mail_cases.case_path(case.key) + f"#fix-{r.id}",
                context=f"{name}" + (f" · {case.subject}" if case.subject else ""),
                project="Rouh", batch="casefix",
                options=[{"id": "again", "label": "Try again", "go": True,
                          "detail": "A new run fixes the check, with your words if you give any."},
                         {"id": "leave", "label": "Leave it",
                          "detail": "Nothing changes; the check keeps stopping this kind of message."}],
                allow_other=True, answer_type="choice", urgency="soon", risk="reversible",
                prepared=([{"label": f"The run, {r.run_id}", "href": f"/run/{r.run_id}"}]
                          if r.run_id else []),
                asked_at=r.ended_at or r.created_at,
                history=[{"at": r.created_at, "kind": "raised",
                          "detail": f"You marked {r.step} a false alarm."}],
                yes_does=(f"Try again starts a new run to fix the check behind {r.step}, with "
                          "your words as its reason."),
                wait_cost=("Nothing waits on it: the check keeps stopping messages like this one "
                           "for you.")))
        return out

    def settled(self, who, row) -> Settled | None:
        from . import case_fixes

        r = case_fixes.get(who, row.source_id)
        if r is None:
            return Settled(decisions.WITHDRAWN, result="The fix is gone.")
        if r.verdict:
            return Settled(decisions.APPLIED, said=r.verdict, result=f"Answered: {r.verdict}.")
        return None

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import case_fixes

        desk = hooks.mail_desk() if hooks.mail_desk is not None else None
        if desk is None:
            return Applied(False, "New mail is not handled on this server, so nothing could "
                                  "take your answer.")
        answer = row.answer or {}
        choice = (answer.get("choice") or [""])[0]
        words = str(answer.get("text") or "").strip()
        r = await asyncio.to_thread(case_fixes.get, who, row.source_id)
        if r is None:
            return Applied(False, "That fix is gone.")
        if r.verdict:
            return Applied(True, f"Already answered: {r.verdict}.")
        if choice == "leave" and not words:
            return Applied(True, await case_fixes.answer(desk, who, r, "leave", ""))
        if choice in ("again", "") and (choice or words):
            return Applied(True, await case_fixes.answer(desk, who, r, "again", words))
        return Applied(False, "Try again, Leave it, or your own words.")


class OfflineSource(Source):
    """Something done offline that could not simply be carried out when it came back (`rouh/offline.py`).

    Petar, 12 October 2026 (card 1457): "If what an action acted on has changed since (a newer
    email in the thread, a decision already answered, a page edited by a job), the action is not
    carried out but becomes a decision in the decisions list, showing both versions." So a page
    edited here and offline in the same lines, an answer to a question that was answered or asked
    differently meanwhile, a reply to a thread with a newer email in it, and a send or an answer
    that needs a confirmation it was not given, each wait here with both sides until he says.
    """

    kind = "offline"
    label = "Offline"
    tag = "Offline"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("Something ‹he› did ‹himself› offline could not be carried out as "
                                "it was, and both sides are ‹his›.")
    notifies = False

    def collect(self, who) -> list[Ask] | None:
        from . import offline

        try:
            rows = offline.asking(who)
        except Exception:
            log.exception("decisions: the offline outbox could not be read")
            return None
        out = []
        for r in rows:
            q = offline.question_of(r, who)
            out.append(Ask(
                source_id=r.action_id, key=decisions.key_of("offline", r.action_id, r.status),
                title=q["title"], question=q["question"], why=q.get("why", ""),
                then="Whatever you choose is carried out once, and both devices show it.",
                link="/offline", context=f"Offline · {r.device_name or r.device_kind or 'a device'}",
                project="Rouh", batch="offline", options=q["options"],
                recommended=q.get("recommended", ""), recommended_why=q.get("recommended_why", ""),
                allow_other=False, answer_type="choice", urgency=q.get("urgency", "today"),
                risk=q.get("risk", "reversible"), risk_note=q.get("risk_note", ""),
                prepared=q.get("prepared", []), asked_at=r.received_at,
                history=[{"at": r.made_at, "kind": "raised",
                          "detail": f"Done offline on {r.device_name or r.device_kind or 'a device'}."}],
                yes_does=_yes_from(q["options"], q.get("recommended", "") or
                                   next((o.get("id") for o in q["options"] if o.get("detail")), ""),
                                   note=q.get("risk_note", "")),
                wait_cost=("What you did offline on "
                           + (r.device_name or r.device_kind or "a device")
                           + " is held until you answer."),
                blocks=True))
        return out

    def settled(self, who, row) -> Settled | None:
        from . import offline

        r = offline.one(who, row.source_id)
        if r is None:
            return Settled(decisions.WITHDRAWN, result="It is not in the outbox any more.")
        if r.status in ("done", "dropped"):
            return Settled(decisions.APPLIED, said=r.result, channel="offline", result=r.result)
        return None

    async def apply(self, who, row, channel: str) -> Applied:
        from . import offline

        pick = ((row.answer or {}).get("choice") or [""])[0]
        ok, said = await offline.resolve(who, row.source_id, pick)
        return Applied(ok, said)


# --- Slack: promises made to him that are late -------------------------------------------------


class PromiseSource(Source):
    """Promises made to him in Slack that are late (`rouh/slack_promises.py`).

    Petar, 16 October 2026, asking why Slack promises went to the decisions list, and agreeing to
    this split ("Do it"): a promise is not a decision until it is overdue and he must choose what
    to do; before that it is a deadline, and deadlines belong on Clockwork. So his own promises are
    never here - each is a Clockwork reminder a day before it is due (`slack_promises.clockwork`) -
    and one made to him is shown nowhere until its time has passed with nothing in the
    conversation to show it kept. Only then is it one decision of its own, in full: who promised
    what, by when, how late it is, the link, and Chase (the nudge drafted for it, or his own words,
    posted as Rouh's bot on his yes to that sending), Wait (asked again in a few days) or Drop. One
    that a later message showed kept closes by itself, and its line in the history has Undo.

    Until 17 October every open promise was also an item of one line with a count here, "N open
    promises in Slack" (`GROUP`), and one of his own came up in full a day before it was due; the
    line is withdrawn by the first sync after that (`settled`) and never asked again.
    """

    kind = "promise"
    label = "Slack promise"
    tag = "Promise"

    def gate(self, who, ask):
        from . import decision_gate as gate

        return gate.let_through("A promise made to ‹him› is late, and chasing it sends a message "
                                "in ‹his› name.")
    text_acts = True
    dated = True

    #: The source id of the one line with a count, which is not asked any more.
    GROUP = "group"

    @staticmethod
    def context_of(p) -> str:
        from . import slack_promises

        return f"Slack · {slack_promises.where_said(p)}"

    def collect(self, who) -> list[Ask] | None:
        from . import clock, slack_promises

        try:
            rows = slack_promises.late(who)
        except Exception:
            log.exception("decisions: the promises in Slack could not be read")
            return None
        now, zone = time.time(), clock.zone_of(who)
        return [self._late(p, now, zone) for p in rows]

    def _late(self, p, now: float, zone) -> Ask:
        from . import slack_promises

        where = slack_promises.where_said(p)
        name = (p.by_name or "They").split()[0]
        due = slack_promises.due_words(p, now, zone)
        _c, _t, goes = slack_promises.nudge_where(p)
        nudge = slack_promises.nudge_text(p)
        back = slack_promises.wait_day(now + slack_promises.WAIT_DAYS * 86400.0, zone)
        options = [
            {"id": "chase", "label": "Chase", "go": True,
             "detail": f"Rouh's bot posts the nudge below to {name} in {goes}."},
            {"id": "wait", "label": "Wait",
             "detail": f"Ask again on {back}, unless {name} shows it done in Slack before then."},
            {"id": "drop", "label": "Drop", "detail": "Stop watching it. Nothing is sent."}]
        question = f"{slack_promises.said(p)}, {due}, and nothing in the conversation since shows it kept."
        said_where = f"{name} said it in {where}" + (f": \u201c{p.quote.rstrip('.')}.\u201d" if p.quote else ".")
        reminded = f" Rouh reminded {name} on {clock_day(p.reminded_at, zone)}." if p.reminded_at else ""
        waited = (f" You said Wait {p.waits} time{'s' if p.waits != 1 else ''}." if p.waits else "")
        return Ask(
            # Waiting adds to the key only once he has waited, so a question asked before Wait was
            # an answer keeps its row and number and takes the new options in place.
            source_id=f"p{p.id}", key=decisions.key_of("slack-promise", p.id, p.reopened, p.reminders,
                                                       *([p.waits] if p.waits else [])),
            title=f"{slack_promises.said(p)}, {due}", question=question,
            why=said_where + reminded + waited + " Something else posts your own words in place of the nudge.",
            link=slack_promises.link_of(p), context=self.context_of(p), project="Slack",
            options=options, recommended="chase",
            recommended_why="It is late, and nothing since shows it kept.",
            allow_other=True, answer_type="choice", urgency="today",
            due_at=p.due_at or None, risk="sending",
            risk_note=f"Posts a message to {p.by_name} in Slack, as Rouh.",
            prepared=[{"part": "A", "label": "The nudge, if you pick Chase", "text": nudge,
                       "when": f"Posted as Rouh in {goes}"}],
            asked_at=max(p.made_at, p.due_at),
            history=[{"at": slack_ts(p.ts) or p.made_at, "kind": "raised",
                      "detail": f"Said in {where}: \u201c{p.quote}\u201d"}],
            yes_does=f"Chase: Rouh's bot posts one nudge to {name} in {goes}.",
            wait_cost=f"It only gets later: nothing since shows {name} kept it.")

    def settled(self, who, row) -> Settled | None:
        from . import clock, slack_promises

        if row.source_id == self.GROUP:
            return Settled(decisions.WITHDRAWN,
                           result="Promises are not asked about before they are late any more: yours are "
                                  "reminders on Clockwork, and one made to you comes here once it is late.")
        p = slack_promises.one(who, row.source_id)
        if p is None:
            return Settled(decisions.WITHDRAWN, result="The promise is gone.")
        if p.status == slack_promises.KEPT and p.closed_by == "itself":
            return Settled(decisions.APPLIED, said="Kept", channel="Slack",
                           result=slack_promises.kept_words(p), by="itself")
        if p.status == slack_promises.KEPT:
            return Settled(decisions.APPLIED, said="Done", result="Closed as kept.")
        if p.status == slack_promises.DROPPED:
            return Settled(decisions.APPLIED, said="Drop", result="Dropped.")
        if p.by_petar:
            return Settled(decisions.WITHDRAWN, result="Your own promise is a reminder on Clockwork now.")
        if p.wait_until and p.wait_until > time.time():
            return Settled(decisions.WITHDRAWN, result="Asked again on "
                           f"{slack_promises.wait_day(p.wait_until, clock.zone_of(who))}.")
        return Settled(decisions.WITHDRAWN, result="It is not late yet, so it waits quietly until it is.")

    async def apply(self, who, row, channel: str) -> Applied:
        import asyncio

        from . import slack, slack_promises

        answer = row.answer or {}
        text = str(answer.get("text") or "").strip()
        if row.source_id == self.GROUP:
            return Applied(False, "Promises are not asked about before they are late any more.")
        verdict = ((answer.get("choice") or [""])[0]) or ("chase" if text else "")
        # The answers it had until 17 October: Remind them is Chase, and Done closes it as kept.
        verdict = {"remind": "chase"}.get(verdict, verdict)
        try:
            if verdict == "done":
                said = await asyncio.to_thread(slack_promises.close, who, row.source_id, slack_promises.KEPT,
                                               note=text)
            elif verdict == "drop":
                said = await asyncio.to_thread(slack_promises.close, who, row.source_id,
                                               slack_promises.DROPPED, note=text)
            elif verdict == "wait":
                said = await asyncio.to_thread(slack_promises.wait, who, row.source_id)
            elif verdict == "chase":
                said = await asyncio.to_thread(slack_promises.remind, who, row.source_id, text)
            else:
                return Applied(False, "Chase, Wait or Drop.")
        except (ValueError, slack.NotSetUp) as exc:
            return Applied(False, str(exc))
        except slack.SlackError as exc:
            return Applied(False, f"Slack would not post it ({exc.error}). Nothing went.")
        return Applied(True, said)

    def can_reopen(self, row) -> bool:
        from . import slack_promises

        if str(row.answered_by or "") != "itself" or not str(row.source_id).startswith("p"):
            return False
        p = slack_promises.one(_Who(row.user_id, row.org_id), row.source_id)
        return p is not None and p.status == slack_promises.KEPT and p.closed_by == "itself"

    def reopen(self, who, row) -> str:
        from . import slack_promises

        try:
            return slack_promises.reopen(who, row.source_id)
        except ValueError as exc:
            raise decisions.Refused(str(exc)) from None


def _slack():
    from . import slack

    return slack


def slack_ts(ts) -> float:
    return _slack().ts_float(ts)


def clock_day(at: float, zone) -> str:
    """A day as a person says it: "16 Oct"."""
    import datetime as dt

    return dt.datetime.fromtimestamp(at, zone).strftime("%-d %b") if at else ""


_SOURCES: dict[str, Source] = {s.kind: s for s in (
    TaskSource(), GoalSource(), ApprovalSource(), MailSource(), RunSource(), JobSource(),
    ConflictSource(), DreamSource(), NightlySource(), GeneSource(), MeetingSource(), ContactPicksSource(), AfterMeetingSource(),
    CaseFixSource(), DelegateSource(), OfflineSource(), PromiseSource())}


def sources() -> dict[str, Source]:
    return _SOURCES
