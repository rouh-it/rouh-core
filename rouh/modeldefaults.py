"""Which model each use of a model asks: three modes, two tiers, and a tier for every use.

Petar, 24 October 2026, the design agreed in chat that day, and what it decided here:

- **Four providers**: Anthropic, OpenAI, Google (Gemini) and xAI (Grok). Google's and
  xAI's keys are typed into Anatomy, Rouh Land Account, Models (`rouh/providerkeys.py`); every call still
  goes through the LLM service with its cost written down (`rouh/llm.py`, principle D3).
- **Each tier is an ordered list of models across the providers**, not one OpenAI and
  one Anthropic model with a main one, and so is a use on a model of its own (Custom).
  An install asks the first model on the list whose provider it has a key for
  (`Now.model_for`), so an install with only one provider's key works end to end.
- **Each use asks its tier's list in an order of its own** (`modelstandard.use_order`),
  set for every use and every tier in the standard rather than one order for all, so
  rouh.land can move a model up for one use from that use's blind votes without moving it
  for another. Until there is data the order is Anthropic, OpenAI, Google, xAI, except
  that Cheaper keeps OpenAI's GPT-6 Luna first: every use ran on Luna there the day the
  lists came, and nothing anybody runs on changed (the old two-company tiers are read as
  their main model, then the other, then the standard's Google and xAI models: `_tier_held`).
- **A use tied to one provider says so and has a fallback** (`Use.only`, `Use.fallback`):
  Claude Code runs ask only Anthropic's models and Codex runs only OpenAI's, both signed
  in on their own subscription, so neither needs a key here; the router of Balanced is
  OpenAI's Decisions API, and without it Balanced asks the cheapest model this install
  can ask a plain question, easy or hard (`router_question`, `rouh/modelrouter.py`); Ask
  AI, its comment pass and look_into are loops written for Anthropic's API, and without
  an Anthropic key they answer as one plain question to the first model the install has
  (`Pair.fallback`), saying so.
- **Sharing is two separate choices, neither of them Auto**: the anonymous daily totals
  (`share_totals`, `shares`), and the blind comparisons (`compare`, `compares`), off until
  turned on, because they send the person's own request to a second provider
  (`rouh/modelvotes.py`). The double calls of 18 October, judged by a model, run only
  with the comparisons on, for the same reason (`double_rate`).

Petar, 23 October 2026 (card 1842): **two tiers**, Smart (Opus 5.5, and GPT-6.1 Sol
for what can only ask OpenAI) and Cheaper (GPT-6 Luna), and **three modes**, the one
choice most people see at the top of the Models page (`mode`):

- **Best**: the chats are always answered on Smart.
- **Balanced**, the default: the router reads each chat message and drops to
  Cheaper only when it is surer than the bar that the message is easy
  (`rouh/modelrouter.py`, OpenAI's Decisions API).
- **Saver**: the chats are always answered on Cheaper, and no use paid per token
  asks anything above Cheaper. A use that runs on a subscription the person
  already has (`Use.subscription`: Claude Code and Codex runs) keeps its tier.

The mode moves only what nobody changed by hand: a locked use keeps its own, and a
use on a model of its own (Custom) or off stays as it is. Best, the third tier
(GPT-6 Astra), went the same day: a row or a standard that names Best or Daily
means Smart (`modelstandard.tier_id`). What follows is how the tiers and uses
worked from 18 October 2026, and still work behind Customise.

Petar, 18 October 2026: "most Rouh users will not know which model to pick. They
end up with a weaker model and worse results, or pay more than they need to."

So nobody has to pick a model, and nobody picks how deeply it thinks:

- **Three tiers**: **Cheaper**, **Daily**, the daily driver, and **Best**, the
  most capable and the dearest. Each holds one of OpenAI's models and one of
  Anthropic's, and one of the two is its main one. Each starts on the model
  standard's (`rouh/modelstandard.py`), and an organisation may put other
  models in any of them on the Models page. Daily was called Recommended until
  the evening of 18 October 2026; "recommended" is now only the dot on the
  standard's own choice.
- **Every use of a model is on a tier** (`USES`): the chats, Rouh itself, a
  chat's title, a run, Ask AI and every other place Rouh asks a model. Each
  starts on the tier the standard recommends for it, with its reason, and may
  be moved to another in one press, or put on a model of its own (**Custom**).
  The heartbeat's wake-up check may also be off.
- **How deeply a model thinks comes with the model** (`modelstandard.effort`),
  from its benchmarks and score cards. Opus 5.5 thinks at medium wherever it
  answers.

A use that can only ask one company - Claude Code is Anthropic's, Codex is
OpenAI's - asks its tier's pick of that company; every other use asks the
tier's main one. Petar, the evening of 18 October 2026: a use that could only
ask Anthropic quietly answered with Haiku 4.5 while every tier on the page said
an OpenAI model, which is hidden behaviour, so both picks are on the page, each
can be changed, and every use's row says the exact model it asks. A use that
could ask OpenAI, on an install with no OpenAI key, asks its tier's Anthropic
pick rather than nobody.

Until 18 October 2026 there were two pairs, a model and a level for every chat
but General and another for General, a model picked per use, and before that a
model picked per chat in the box beside the composer. All three are gone, and
nothing of them still decides anything (principle A3).

**Auto, Sync and locks** (Petar, the evening of 18 October 2026: "Auto is a
toggle. Sync is a one time button press."). Each box on the Models page has its
own **Auto**: one for the three tiers (`auto_tiers`) and one for every use
(`auto_uses`), each independent of the other. On, the default, everything in
that box follows the Rouh model service on rouh.land, the standard Rouh fetches
from it each day, except what is **locked** (`locked`), which keeps its manual
value. Off, the organisation's own **manual** settings apply (`manual`), which
no standard moves; they are kept while Auto is on, so turning it off again
brings them back exactly. While either box is on Auto, the day's anonymous
counts go to rouh.land (`rouh/modeloutcomes.py`) and a small share of read-only
answers is asked of a second model too and judged (`rouh/llm.py`, double
calls). This replaced "Join the Rouh pool", which did all three for the whole
page.

**Sync** is a one-time press in a box with Auto off: its manual settings are made
what the service says now, except what is locked. The values it replaced are
kept (`undo`) until the next change, so the page can offer Undo for that one
press. **Reset to defaults** is the same for the standard built into this Rouh.

**Where it is kept.** One row of `model_defaults` per organisation
(`rouh.models.ModelDefaults`), keyed and read by `org_id` as `tenancy.py`
requires. It is changed three ways, and every one is a function
below: the Models page (`rouh/web/defaults.py`), Rouh itself when asked (the
`model_defaults` tool), and `manage.py model_defaults`. Only an organisation's
administrator may change it from a screen or by voice.

**Which organisation.** Chats carry no organisation, so a turn asks `org_now`:
whoever is speaking, else the one person this install has, else the default
organisation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from . import modelstandard as standard
from .config import (CHOICES_OF, DECISIONS_MODELS, EFFORT_NAMES, MODEL_CHOICES, PROVIDER_NAMES,
                     PROVIDERS, config as _config, current_model, is_decisions_model, model_name,
                     provider_of)
from .modelstandard import (ANTHROPIC, AUTO, BALANCED, BEST, CHEAPER, GOOGLE, MODE_NAMES, MODES, OFF,
                            OPENAI, SAVER, SMART, TIER_NAMES, TIERS, XAI)

log = logging.getLogger("rouh.modeldefaults")

__all__ = ["AUTO", "BALANCED", "BEST", "BOXES", "CHEAPER", "CUSTOM", "MODES", "MODE_NAMES", "NONE",
           "OFF", "SAVER", "SMART", "TIERS", "TIER_NAMES"]

#: A use on a model of its own rather than a tier's, as the page and a call's record
#: name it. The choice itself is kept as the model's id.
CUSTOM = "custom"

_MODELS = {m for m, _ in MODEL_CHOICES}

#: The model a use asks when no model on its list can be asked here: none. `llm.ask` says so
#: in words (`Cannot`), and the Models page beside the use (`Now.blocked`).
NONE = ""


def _is_model_id(value: str) -> bool:
    return str(value or "").startswith(("claude-", "gpt-", "gemini-", "grok-"))

#: What a chat answers on when the router cannot say: Smart (Petar, 23 October 2026: "If it
#: is unsure, slower than its time limit, or fails, the message stays on Smart").
AUTO_FALLBACK = SMART

#: Every choice a use may be on, by name, as the page and the model say it.
CHOICE_NAMES = {**TIER_NAMES, OFF: "Off", AUTO: "Routed", CUSTOM: "Custom"}

#: The two boxes of the Models page, each with its own Auto and Sync: the three tiers,
#: and every use.
BOXES = ("tiers", "uses")
BOX_NAMES = {"tiers": "Models", "uses": "Each use"}


class Refused(ValueError):
    """A change that was not made, with the reason in words a person can read."""


@dataclass(frozen=True)
class Pair:
    """A model, and how deeply it is asked to think. `fallback` is a use that can only ask
    one provider answering with another's model as one plain question, since that provider
    has no key here (`Use.fallback`)."""

    model: str
    effort: str
    fallback: bool = False

    def as_dict(self) -> dict:
        return {"model": self.model, "model_name": model_name(self.model),
                "effort": self.effort, "effort_name": EFFORT_NAMES.get(self.effort, self.effort)}


@dataclass(frozen=True)
class Use:
    """One place Rouh asks a model, as the Models page lists it."""

    id: str
    group: str
    name: str
    said: str
    #: The one company it can ask, or "" for either. Only where the code that asks
    #: truly needs that company, never because of which client it was handed: since
    #: the evening of 18 October 2026 a single question goes through `rouh/llm.py`,
    #: which asks either company (Petar: "Whatever we select here should be the one
    #: called. No exceptions.").
    only: str = ""
    #: Why it can only ask that company, as the page says it beside the use.
    needs: str = ""
    #: Whether it may be off.
    can_be_off: bool = False
    #: A level of its own, whatever its model's usual one: the router, which
    #: thinks as little as its model allows ("none" on OpenAI's, the lowest level on
    #: Anthropic's), because it has to be quick (`rouh/modelrouter.py`), and the two
    #: uses of the Decisions API, which takes no level at all.
    effort: str = ""
    #: What off is called.
    off_said: str = ""
    #: The `llm_requests.purpose` its requests are written down under.
    purposes: tuple = ()
    #: Whether it asks OpenAI's Decisions API (`llm.decide`), which takes only
    #: `config.DECISIONS_MODELS`: any other model is said not to run on the page.
    decisions: bool = False
    #: Whether an OpenAI model needs Rouh's own OpenAI key here. Codex signs in
    #: by itself, so a Codex run can be any of them whether or not Rouh has one.
    needs_key: bool = True
    #: Whether it runs on a subscription the person already pays for - Claude Code on a
    #: Claude subscription, Codex on a ChatGPT one - rather than per token. Saver leaves
    #: such a use on its tier (Petar, 23 October 2026: "Subscriptions are already paid
    #: for, so Saver may run Opus or Codex through them for code").
    subscription: bool = False
    #: The providers it can ask when it is not tied to one (`only`), or () for all four:
    #: the nightly runs are Claude Code or Codex, so Anthropic's or OpenAI's.
    can_ask: tuple = ()
    #: What happens when the provider it needs has no key here, in words for the page, and
    #: whether it then answers as one plain question to the first model the install can ask
    #: (`Pair.fallback`), or asks another use instead (`fallback_use`).
    fallback: str = ""
    fallback_any: bool = False
    fallback_use: str = ""

    @property
    def providers(self) -> tuple:
        """The providers whose models it may ask."""
        return (self.only,) if self.only else (self.can_ask or PROVIDERS)


#: The groups, in the order the page reads them.
GROUPS = ("Chats", "Heartbeat", "Runs and helpers", "Pages", "Genes", "Mail", "Slack",
          "Goals and the brief", "Control Room", "Synapse", "Setting up", "Auto")

#: Every use of a model. Synapse's models are its lab's, per dataset
#: (`rouh/synapse/numbers.py`), and are only listed on the page; a picture's model
#: is picked in the picture editor. The tier each starts on, and why, is the
#: standard's (`model_standard.json`, `uses`).
USES: tuple[Use, ...] = (
    # The chats themselves, which had a pair of their own each, a model and a level, until
    # 18 October 2026 (`default` and `general`), and before that a box beside the composer.
    Use("general", "Chats", "Rouh",
        "Rouh, the conversation that is always there, and every fork of it.", purposes=("turn",)),
    Use("chats", "Chats", "Every other chat",
        "A topic, a task's chat, an email's own chat, and a fork of any of them. A turn about "
        "somebody else's email or message is Reading an email or message from somebody else.",
        purposes=("turn",)),
    # Petar, 23 October 2026 (card 1842): Balanced's router is OpenAI's Decisions API, the
    # third kind of call (`llm.decide`): how sure it is that a message is easy, and Cheaper
    # only above the bar. The router of 18 October, a model asked in words (use "router"),
    # went the same day: on a model the Decisions API does not take, off, or when the call
    # fails, the message is answered on Smart (`modelrouter.decide`).
    Use("router_decisions", "Chats", "Choosing the model in Balanced",
        "In Balanced, asks OpenAI's Decisions API how sure it is that each message is easy, "
        "reading the last few turns and the chat's title. Cheaper answers only above the bar; "
        "otherwise, and whenever it is off, slow or fails, Smart answers.",
        only=OPENAI, needs="It is OpenAI's own Decisions API, which takes only GPT-6 Luna.",
        can_be_off=True, off_said="Off: Balanced answers every message on Smart.",
        purposes=("router_decisions",), decisions=True, effort="none",
        fallback="Without an OpenAI key, Balanced asks the cheapest model you have whether the "
                 "message is easy or hard (Choosing the model without OpenAI).",
        fallback_use="router_question"),
    # Petar, 24 October 2026: "Without OpenAI, the Balanced router becomes a plain 'easy or
    # hard?' question to the cheapest available model" (`modelrouter.decide`).
    Use("router_question", "Chats", "Choosing the model without OpenAI",
        "In Balanced, on an install without an OpenAI key, asks the cheapest model you have "
        "whether each message is easy or hard. Cheaper answers only when it says easy; "
        "otherwise, and whenever it is off, slow or fails, Smart answers.",
        can_be_off=True, off_said="Off: without OpenAI, Balanced answers every message on Smart.",
        purposes=("router_question",), effort="none"),
    Use("chat_title", "Chats", "Chat titles",
        "Names a chat from its first exchange, in an emoji and a few words.",
        purposes=("chat_title",)),
    Use("task_icon", "Chats", "Task icons",
        "Picks the emoji in front of each new task's title, from its title, many tasks to a "
        "question.", purposes=("task_icon",)),
    Use("filing", "Chats", "Filing new tasks",
        "Picks the project a new task belongs in.",
        purposes=("filing",)),
    Use("reminder_title", "Chats", "Clockwork titles",
        "Gives a reminder or scheduled work in Clockwork that has none a one-line title that says "
        "on its own what it is about.",
        purposes=("reminder_title",)),
    Use("reminder_words", "Chats", "Reading Clockwork's words",
        "Turns words typed into Clockwork, like \u201cnext Tuesday after lunch\u201d, into a day "
        "and a time.", purposes=("reminder_words",)),
    Use("heartbeat_check", "Heartbeat", "Wake-up check",
        "The first step of a beat: reads what woke it and decides whether anything needs "
        "attention. Only when something does is the decision asked. Off sends every beat "
        "straight to the decision.", can_be_off=True, off_said="Off: every beat goes to the decision",
        purposes=("heartbeat_check",)),
    Use("heartbeat_decide", "Heartbeat", "Decision",
        "The second step: the beat's own turn, in the Heartbeat chat or a long-running "
        "work's chat, which decides what to do and does it.", purposes=("turn",)),
    # 24 October 2026: a beat told Petar Anthropic had cut Rouh off, a day after he had
    # raised the cap. Before a beat says a company fails, it asks that company once
    # (`rouh/provider_check.py`), so each company has its own check.
    Use("provider_check_anthropic", "Heartbeat", "Checking Anthropic still fails",
        "Before the heartbeat tells you Anthropic is refusing Rouh's requests, one tiny "
        "question to Anthropic, a few tokens, proves it still is. If it answers, you are "
        "not told.", only=ANTHROPIC, needs="It checks whether Anthropic itself answers.",
        purposes=("provider_check_anthropic",)),
    Use("provider_check_openai", "Heartbeat", "Checking OpenAI still fails",
        "Before the heartbeat tells you OpenAI is refusing Rouh's requests, one tiny "
        "question to OpenAI, a few tokens, proves it still is. If it answers, you are not "
        "told.", only=OPENAI, needs="It checks whether OpenAI itself answers.",
        purposes=("provider_check_openai",)),
    # The first run's brain screen proves a pasted key has credit with one word from that
    # company's model (`rouh/web/firstrun.py`, `check_key`).
    Use("key_check_anthropic", "Setting up", "Checking a new Anthropic key",
        "When a key is pasted on the first run's brain screen, one tiny question to Anthropic, a "
        "few tokens, proves the account has credit, before the chats are given the key.",
        only=ANTHROPIC, needs="It checks the Anthropic key that was just pasted.",
        purposes=("key_check_anthropic",)),
    Use("key_check_openai", "Setting up", "Checking a new OpenAI key",
        "When a key is pasted on the first run's brain screen, one tiny question to OpenAI, a few "
        "tokens, proves the account has credit, before the chats are given the key.",
        only=OPENAI, needs="It checks the OpenAI key that was just pasted.",
        purposes=("key_check_openai",)),
    Use("code_runs", "Runs and helpers", "Code runs",
        "Every Claude Code run of the one program that Rouh starts, the runs that build "
        "Gene therapy's mutations among them.",
        only=ANTHROPIC, needs="Every Claude Code run of the one program is a Claude Code run, and Claude Code asks only Anthropic's models.",
        subscription=True, needs_key=False,
        fallback="It runs on your own Claude Code sign-in, so it needs no Anthropic key here."),
    # Card 1684, 18 October 2026: Rouh merges a clash itself rather than asking Petar.
    # A Claude Code pass run by land.sh, as whichever user lands the work, so the pick
    # reaches it as a file in the landing directory (`publish_merge_pick`).
    Use("merge_pass", "Runs and helpers", "Merging a clash",
        "When a job's work collides with main and its own run could not reconcile the two, "
        "the Claude Code pass that merges them keeping both sides' intent, before anybody "
        "is asked.",
        only=ANTHROPIC, needs="A Claude Code pass, and Claude Code asks only Anthropic's models.",
        subscription=True, needs_key=False,
        fallback="It runs on your own Claude Code sign-in, so it needs no Anthropic key here."),
    Use("codex_runs", "Runs and helpers", "Codex runs",
        "A run of OpenAI's Codex, when one is asked for by name.", needs_key=False,
        only=OPENAI, needs="A Codex run, and Codex asks only OpenAI's models.", subscription=True,
        fallback="It runs on Codex's own ChatGPT sign-in, so it needs no OpenAI key here."),
    # Petar, 6 October 2026: the nightly feature run has a pick of its own, which moves no
    # other run's (`nightly_feature.py`). It was Codex on GPT-6.1 Sol, which the Codex
    # subscription refused on the first night. Either company's model may be its tier's: a
    # Claude model is a Claude Code run and an OpenAI one a Codex run on the subscription, so
    # no key is needed for either.
    Use("nightly_feature_run", "Runs and helpers", "Nightly feature run",
        "The run that researches, picks and builds one new Rouh feature each night: "
        "Claude Code on a Claude model, Codex on an OpenAI one.", needs_key=False, subscription=True,
        can_ask=(ANTHROPIC, OPENAI)),
    # Petar, 15 October 2026: a refactoring run every night at 03:00, on the subscription as
    # the feature run is (`nightly_refactor.py`), and never the pick for every other run.
    # Its level on Codex, as everywhere, is its model's (`modelstandard.effort`).
    Use("nightly_refactor_run", "Runs and helpers", "Nightly refactoring run",
        "The run that looks over Rouh's code each night and does up to ten refactors side by "
        "side, or fewer and bigger ones, without changing what Rouh does: Claude Code on a Claude "
        "model, Codex on an OpenAI one, and each of its workers on the same.", needs_key=False,
        subscription=True,
        can_ask=(ANTHROPIC, OPENAI)),
    Use("workers", "Runs and helpers", "Background workers",
        "Assistant jobs and improve_myself workers, which run in Rouh's own terminals.",
        only=ANTHROPIC, needs="They run Claude Code in Rouh's own terminals, and Claude Code asks only Anthropic's models.",
        subscription=True, needs_key=False,
        fallback="It runs on your own Claude Code sign-in, so it needs no Anthropic key here."),
    # Named for Gene therapy, Feedback until 12 October 2026; the id, which the
    # picks are kept under, is unchanged.
    Use("triage", "Runs and helpers", "Reading Gene therapy",
        "Reads what was asked for in Gene therapy (feedback) the moment it lands and "
        "writes the brief a run builds from.", purposes=("triage",)),
    Use("run_summary", "Runs and helpers", "Run summaries",
        "The one line on a finished run's card.",
        purposes=("run_summary",)),
    # Petar, 25 October 2026: a job asks Rouh for what none of its tools gives, and carries on
    # (`rouh/job_gateway.py`). Its plain tool calls ask no model at all.
    Use("job_request", "Runs and helpers", "What a job asks Rouh for",
        "Reads a background job's request_from_rouh: whether a tool it has does it, whether only "
        "you can give it, or neither. A job's own calls of Rouh's tools ask no model.",
        purposes=("job_request",)),
    # Petar, 2 November 2026: "tomorrow I don't get a decision but whatever the new thing gets
    # done". A job's call that would wait on his yes is first read against his own words for
    # the job and his standing rules (`rouh/his_word.py`); covered, it runs.
    Use("his_word", "Runs and helpers", "Whether you already asked for this",
        "Reads a background job's call that would otherwise wait on your yes against your own "
        "words for that job and your standing rules: when they already ask for it, it runs and is "
        "listed under Done on your word on the Metabolism page.", purposes=("his_word",)),
    Use("subagent", "Runs and helpers", "Helpers",
        "look_into and the other helpers a turn sends to look something up.", purposes=("subagent",),
        only=ANTHROPIC, needs="Its loop reads the web with Anthropic's own web search and fetch tools, which run on Anthropic's side.",
        fallback="Without an Anthropic key, the first model you have answers it from what it "
                 "knows, without reading the web.", fallback_any=True),
    Use("askai", "Pages", "Ask AI",
        "The Ask AI drawer beside a page, and its edits to the page.", purposes=("askai",),
        only=ANTHROPIC, needs="Its loop of tools, page edits and web search is written for Anthropic's Messages API; it has no OpenAI side yet.",
        fallback="Without an Anthropic key, the first model you have answers questions about the "
                 "page, without editing it or reading the web.", fallback_any=True),
    Use("comment_pass", "Pages", "Answering page comments",
        "Ask AI's pass over a page's comments.",
        purposes=("comment_pass",),
        only=ANTHROPIC, needs="It is Ask AI's loop, written for Anthropic's Messages API; it has no OpenAI side yet.",
        fallback="Without an Anthropic key, the first model you have answers each comment, "
                 "without editing the page.", fallback_any=True),
    # Petar, 20 October 2026 (fr_a06689f582ba): Define beside Ask over a selected passage
    # (`rouh/definitions.py`).
    Use("page_define", "Pages", "Defining a passage",
        "Define, beside Ask over a passage selected on a page: a few sentences on what it "
        "means there, in a tooltip.", purposes=("page_define",)),
    # Petar, 27 October 2026 (mutation request 6 of Listen to this page): a narration that walks
    # the listener through a page, read out in Rouh's voice (`rouh/page_listen.py`).
    Use("page_listen", "Pages", "Narrating a page",
        "Listen, in a page's floating control: the page told as a narration that walks you "
        "through it, part by part, each part tied to the parts of the page it is about.",
        purposes=("page_listen",)),
    # Night 10 of the nightly feature run, 13 October 2026 (`rouh/source_check.py`).
    Use("source_check", "Pages", "Checking a page's sources",
        "Reads each footnoted source of a research page against what the page says it says, and "
        "marks the ones that say less, otherwise or nothing about it.", purposes=("source_check",)),
    # Petar, 13 October 2026, task 94 step 94-08: Ask a question on a gene's card in Mutations
    # (the Gene library until 14 October 2026), answered there from the gene's record, with follow-ups (`rouh/gene_questions.py`).
    Use("gene_question", "Pages", "Questions about a gene",
        "Ask a question on a gene's card in Mutations: answered from that gene's own "
        "record, with follow-ups.", purposes=("gene_question",)),
    # Task 98, step 98-16 (Petar, 13 October 2026): the gene log, filled by itself from every change
    # that lands (`rouh/genelog.py`), what each gene is worth to the person (`rouh/geneuse.py`), and
    # the Gene Pool's genes matched to how they use Rouh (`rouh/genepool.py`).
    Use("gene_writer", "Genes", "Writing the gene log",
        "Puts a change that landed in Rouh's code to the gene it built on, a new gene or a sub-gene, "
        "when its commit does not say.",
        purposes=("gene_writer",)),
    Use("gene_eval", "Genes", "How useful a gene is",
        "Once a month, and when asked: a score, what a gene replaced and the minutes it saves, from "
        "its contract and your relative use of it.",
        purposes=("gene_eval",)),
    # Petar, 4 November 2026: every idea of the Incubator scored from parts he can read and change
    # (`rouh/incubator_score.py`), in batches, and each new idea as it comes.
    Use("incubator_score", "Genes", "Scoring the Incubator's ideas",
        "Writes each Incubator idea's score parts, impact, confidence, frequency, pain, clarity and "
        "risk, each with a one-line reason, and suggests its stars; never a part or stars you set.",
        purposes=("incubator_score",)),
    # Petar, 4 November 2026: Trials (`rouh/trials/`). A made-up person tries each change a person will
    # see, one step at a time, on the Smart tier, and the problems they name are matched against the list.
    Use("trial_tester", "Genes", "Trials tester",
        "Plays a made-up person trying a change on a phone, one screen at a time: says what it sees, "
        "thinks and does, and every moment that confuses it.",
        purposes=("trial_tester",)),
    Use("trial_matcher", "Genes", "Trials: the same problem again",
        "Says whether a problem a trial found is one already on the list of problems, so it is "
        "counted again instead of written twice.",
        purposes=("trial_matcher",)),
    Use("trial_writer", "Genes", "Trials: writing a new tester",
        "Writes the whole profile of a new made-up tester from one sentence describing them, for you to "
        "read and change before it is kept.",
        purposes=("trial_writer",)),
    Use("trial_discuss", "Genes", "Trials: talking a problem over",
        "Answers you in a problem's discussion on the Trials page, with the problem, its screenshot and "
        "the try it came from in front of it.",
        purposes=("trial_discuss",)),
    Use("gene_match", "Genes", "Genes for you from the Gene Pool",
        "Picks the Gene Pool's genes and branches that fit how you use Rouh, says why, and may "
        "propose how one should be different for you.",
        purposes=("gene_match",)),
    # Petar, 23 October 2026 (task 141): about a hundred days after its birth a Rouh reads its
    # own history and gives itself a second name, with a short line on why (`rouh/birth.py`).
    Use("second_name", "Genes", "A Rouh's second name",
        "Once in its life, about a hundred days after its birth, reads its own history (counts and "
        "the names of its genes, never a chat) and gives itself a second name with a line on why.",
        purposes=("second_name",)),
    # Petar, 8 October 2026: a step of a case marked a false alarm starts a run that fixes
    # the check behind it (`case_fixes.py`), a Claude Code run of the one program.
    Use("case_fix_run", "Mail", "Fixing a false alarm",
        "The run a false alarm on a mail or Telegram case starts: it fixes the check that "
        "stopped it, proves it on the cases you marked, and lands it.",
        only=ANTHROPIC, needs="A Claude Code run of the one program, and Claude Code asks only Anthropic's models.",
        subscription=True, needs_key=False,
        fallback="It runs on your own Claude Code sign-in, so it needs no Anthropic key here."),
    # Petar, 21 October 2026, after a contact's email was started on Cheaper, a
    # routed GPT-6 Luna, which read her ask for edit rights as a hard limit on his accounts: the
    # turns of a case are a use of their own, never routed per message (`chatkinds.use_for`).
    Use("case_read", "Mail", "Reading an email or message from somebody else",
        "The turns of an email, Telegram or Slack message from somebody else: reading what they ask "
        "and mapping each ask to what Rouh would do, then starting what is let through. Never "
        "routed per message.", purposes=("turn",)),
    Use("case_ask", "Mail", "Questions about a mail case",
        "The question box on a mail case's trace page.",
        purposes=("case_ask",)),
    # Petar, 16 October 2026: promises made in Slack, by him or to him, wait in Decisions
    # (`rouh/slack_promises.py`). Every message Rouh keeps is read, a conversation a call.
    Use("slack_promises", "Slack", "Promises in Slack",
        "Reads new Slack messages for promises made by you or to you, with a deadline, says which "
        "open ones a later message shows kept, and drafts the nudge for one that is late.", purposes=("slack_promises",)),
    # Petar, 16 October 2026: a Slack channel linked to a task has its decisions written into the
    # task's notes (`rouh/slack_tasks.py`), a linked channel a call when Slack goes quiet.
    Use("slack_decisions", "Slack", "Decisions in a linked channel",
        "Reads new messages in a Slack channel linked to a task for clear decisions, and writes each "
        "into that task's notes with a link to the message.", purposes=("slack_decisions",)),
    Use("goal_split", "Goals and the brief", "Splitting a goal into steps",
        "Writes a goal's plan as its steps.",
        purposes=("goal_split",)),
    Use("goal_revise", "Goals and the brief", "Rewriting a goal's step",
        "Rewrites one step of a goal's plan the way it was asked, before it starts.",
        purposes=("goal_step_revise",)),
    Use("morning_brief", "Goals and the brief", "Morning brief",
        "Picks the world stories, the AI news and the day in history for the brief, and reads "
        "which Slack messages wait on you.", purposes=("brief_world", "brief_ai", "brief_history", "brief_slack")),
    Use("meeting_brief", "Goals and the brief", "What to raise before a meeting",
        "Reads the mail with a meeting's guests from outside and says where things stand, "
        "what is open and what to raise, and where you and each guest left things in Slack.", purposes=("meeting_brief", "meeting_slack")),
    # Petar, 9 October 2026: an answer in his own words to which LinkedIn profile is a meeting
    # guest's is read against the candidates, not failed (`meeting_people.read_with_model`).
    Use("meeting_pick_words", "Goals and the brief", "Reading which profile a meeting guest is",
        "Reads an answer in your own words to which LinkedIn profile is a meeting guest's, when "
        "it is not simply a name and a number, and asks back when the words fit more than one.", purposes=("meeting_pick_words",)),
    Use("meeting_next", "Goals and the brief", "Work to start after a meeting",
        "Reads a meeting's notes from the meeting library and says which work it calls for that "
        "Rouh can start, waiting in Decisions.", purposes=("meeting_next",)),
    # Night 9 of the nightly feature run, 12 October 2026 (`rouh/answered_in_chat.py`).
    Use("answered_in_chat", "Goals and the brief", "Questions you already answered in a chat",
        "Reads a question waiting in Decisions against what you said in your chats since it was "
        "asked, and says when one of your messages already answers it.", purposes=("answered_in_chat",)),
    # Petar, 18 October 2026: a question reaches him only when work he asked for has truly
    # stopped without him and the answer is his to give (`rouh/decision_gate.py`).
    Use("decision_gate", "Goals and the brief", "Whether a question needs you",
        "Reads a task's or a goal step's question before it reaches Decisions, and keeps it from "
        "you unless the work truly stopped on it and the answer is yours to give.", purposes=("decision_gate",)),
    # Petar, 9 October 2026: the Control Room's clusters are named, and their headlines
    # written, by a model of their own (`rouh/clusters.py`). Never at the moment the room opens: a pass
    # after it, and each night, so the room always opens on what was written last.
    Use("control_room", "Control Room", "Cluster names and headlines",
        "Names each cluster on the Control Room's map, decides which groups are one piece of "
        "work, and writes each card's headline and key numbers.", purposes=("control_room",)),
    # Petar, the evening of 18 October 2026: "No exceptions", Synapse included. Its lab picked
    # its own models per dataset until then (`rouh/synapse/numbers.py`); now each model job is a
    # use here. Its embeddings are not: a dataset's vectors are all one embedding model's, and a
    # question is embedded with that same model, so that stays with the dataset.
    Use("synapse_helper", "Synapse", "Synapse's helper",
        "Writes Synapse's X-rays, finds links and layers, and names the areas of its map.",
        purposes=("synapse_xray", "synapse_xray_section", "synapse_tier", "synapse_map_areas",
                  "synapse_layer_thread", "synapse_layer_topic", "synapse_layer_person",
                  "synapse_explain", "synapse_test_data")),
    Use("synapse_answer", "Synapse", "Synapse's answers",
        "Picks what Synapse recalls for a question and answers it from that.",
        purposes=("synapse_understand", "synapse_answer")),
    Use("synapse_decision", "Synapse", "Synapse's decision backend",
        "Synapse's experimental way of deciding by a model's log probabilities.",
        only=OPENAI, needs="It reads log probabilities, which only OpenAI's GPT-4.1 models give.",
        fallback="Without an OpenAI key, Synapse decides with its other backends, which ask "
                 "its helper's model.",
        purposes=("synapse_decide_tier", "synapse_decide_sensitivity", "synapse_decide_seed_rerank",
                  "synapse_decide_checkpoint_shadow")),
    Use("synapse_decisions_api", "Synapse", "OpenAI's Decisions API",
        "The other decision backend Synapse can try: OpenAI's own Decisions API, when this key may use it.",
        only=OPENAI, needs="It is OpenAI's own Decisions API, which takes only GPT-6 Luna.",
        purposes=("synapse_decisions_probe",), decisions=True, effort="none",
        fallback="Without an OpenAI key it does not run, and Synapse uses its other backends."),
    Use("synapse_recall_first", "Synapse", "Automatic recall's first reader",
        "The first of the two models that read a message at once for what Synapse should recall.",
        purposes=("synapse_recall_pick",)),
    Use("synapse_recall_second", "Synapse", "Automatic recall's second reader",
        "The second of the two models that read a message at once for what Synapse should "
        "recall, raced against the first."),
    Use("synapse_judge", "Synapse", "Judging Synapse's answers",
        "Scores Synapse's answers and citations in its benchmarks, so a change can be measured.",
        purposes=("synapse_judge",)),
    Use("synapse_dream", "Synapse", "Dreaming",
        "Proposes what Synapse should change about itself from what it saw, for the gate to test.",
        purposes=("synapse_dream",)),
    # Petar, the evening of 18 October 2026: double calls are part of Auto.
    Use("double_judge", "Auto", "Judging double calls",
        "With blind comparisons on, a small share of answers nobody is there to judge, that "
        "only say something, is asked of a second model too, and this compares the two and "
        "says which was better. Only that conclusion is counted.", purposes=("double_call",)),
)


BY_ID = {u.id: u for u in USES}

#: Everything that can be locked, changed and reset: the two tiers and every use.
ITEMS = TIERS + tuple(BY_ID)


def box_of(item: str) -> str:
    """The box of the Models page an item is in: a tier's or a use's."""
    return "tiers" if item in TIERS else "uses"


def _boxes(box: str | None) -> tuple:
    """One box by name, or both for none. Refused for anything else."""
    if box in (None, "", "both", "all"):
        return BOXES
    box = str(box).strip().lower()
    box = {"models": "tiers", "tier": "tiers", "use": "uses", "each use": "uses"}.get(box, box)
    if box not in BOXES:
        raise Refused(f"There is no box called {box!r}: it is tiers (Models) or uses (Each use).")
    return (box,)


def company(model: str) -> str:
    """Whose a model is: anthropic, openai, google or xai."""
    return provider_of(model)


def org_now(who=None) -> str:
    """The organisation whose models apply here and now.

    Whoever is asking, when that is known: the person on a request or a socket,
    or the speaker of the turn being answered (`tenancy.speaker`). With nobody
    - a feedback swept up in the background, a reminder that came due, a
    message from Telegram - the one person this install has, and failing that
    the default organisation. A guest is never whose models they are.
    """
    from .tenancy import DEFAULT_ORG_ID, GUEST_ORG, Tenancy, speaker

    for someone in (who, speaker()):
        org = getattr(someone, "org_id", "") or ""
        if org and org != GUEST_ORG:
            return org
    try:
        only = Tenancy().only_person()
    except Exception:              # no database to ask: the standard still answers
        only = None
    return getattr(only, "org_id", "") or DEFAULT_ORG_ID


def _row(org_id: str | None):
    org = org_id or org_now()
    try:
        from .models import ModelDefaults

        return ModelDefaults.objects.filter(org_id=org).first()
    except Exception:
        log.exception("the model choices for %s could not be read; using the standard", org)
        return None


def _tier_held(value, std: list) -> list | None:
    """A tier as a row holds it, as its ordered list of models, or None for one that is not
    usable any more. Since 24 October 2026 a tier is a list (`{"models": [...]}`); before,
    it was one OpenAI and one Anthropic model with a main one, which is read as the main
    model, then the other, then the standard's models of the providers it did not name,
    so nothing anybody ran on changes. Before the evening of 18 October 2026 a row held a
    tier as one model: that model first, then the standard's."""
    if isinstance(value, dict) and isinstance(value.get("models"), list):
        # Today's shape: the list as the organisation left it, with nothing added to it.
        return standard.ordered(current_model(str(m)) for m in value["models"]) or None
    if isinstance(value, list):
        return standard.ordered(current_model(str(m)) for m in value) or None
    if isinstance(value, str):
        model = current_model(value)
        got = [model] if model in _MODELS else []
    elif isinstance(value, dict):
        main = value.get("main") if value.get("main") in (OPENAI, ANTHROPIC) else ""
        picks = {k: current_model(str(value.get(k) or "")) for k in (OPENAI, ANTHROPIC)}
        if any(m and (m not in _MODELS or company(m) != k) for k, m in picks.items()):
            return None
        first = main or next((k for k in (ANTHROPIC, OPENAI) if picks[k]), "")
        got = [picks[k] for k in (first, OPENAI if first == ANTHROPIC else ANTHROPIC) if k and picks.get(k)]
    else:
        return None
    if not got:
        return None
    named = {company(m) for m in got}
    return got + [m for m in std if company(m) not in named and m not in got]


def _custom_of(value) -> list | None:
    """A use's model of its own (Custom), as its ordered list, from a list or one model id
    (as it was kept before 24 October 2026), or None for neither."""
    if isinstance(value, (list, tuple)):
        got = standard.ordered(current_model(str(m)) for m in value)
        return got or None
    if isinstance(value, str) and _is_model_id(value.strip()):
        model = current_model(value.strip())
        return [model] if model in _MODELS else None
    return None


def _choice_ok(use: Use, choice) -> bool:
    """Whether a use may be on this choice: a tier, off, or a list of models of its own
    (Custom), each of a provider it can ask."""
    if isinstance(choice, (list, tuple)):
        return bool(choice) and all(m in _MODELS and company(m) in use.providers for m in choice)
    if choice in TIERS:
        return True
    if choice == OFF:
        return use.can_be_off
    return False


def _read_choice(value):
    """A use's choice as a row or the standard keeps it: a tier, off, or a Custom list."""
    custom = _custom_of(value)
    if custom is not None:
        return custom
    choice = standard.tier_id(str(value or "").strip())
    if choice == standard.AUTO:      # a use on Auto before it was the page's one toggle
        choice = AUTO_FALLBACK
    return choice


def _layer(tiers, uses, doc) -> tuple[dict, dict]:
    """One set of choices as a row keeps it, only what is still something the
    organisation may have: tiers by their id, uses by theirs."""
    out_t, out_u = {}, {}
    tiers = dict(tiers or {})
    for t, v in tiers.items():
        # A row from before 23 October 2026 holds Best and Daily: Daily is Smart, and Best,
        # which no tier is any more, is left out (unless the row has no Daily to be Smart).
        if str(t).strip().lower() == "best" and any(k in tiers for k in ("daily", "smart", "recommended")):
            continue
        t = standard.tier_id(t)
        if t in TIERS:
            got = _tier_held(v, standard.tier_pick(t, doc))
            if got is not None:
                out_t[t] = got
    for u, v in dict(uses or {}).items():
        choice = _read_choice(v)
        if u in BY_ID and _choice_ok(BY_ID[u], choice):
            out_u[u] = choice
    return out_t, out_u


def is_custom(choice) -> bool:
    return isinstance(choice, (list, tuple))


class Now:
    """Everything one organisation's models are, read once: the standard, its own
    manual set, whether each box is on Auto, the locks, and which providers it has a
    key for. Never raises.

    A box on Auto (the default): every item in it is what the standard says, except
    a locked one, which keeps its manual value. Auto off: the manual set (`manual`),
    which no standard moves; anything it does not name (a use added since) is the
    standard's.
    """

    def __init__(self, org_id: str | None = None, cfg=None) -> None:
        self.cfg = cfg or _config
        self.org = org_id or org_now()
        self.row = _row(self.org)
        self.doc = standard.current()
        row = self.row
        self.auto_tiers = True if row is None else bool(getattr(row, "auto_tiers", True))
        self.auto_uses = True if row is None else bool(getattr(row, "auto_uses", True))
        undo = (getattr(row, "undo", None) or {}) if row is not None else {}
        self.undo = undo if isinstance(undo, dict) else {}
        self.locked = {str(x) for x in ((getattr(row, "locked", None) or []) if row is not None else [])
                       if x in TIERS or x in BY_ID}
        manual = (getattr(row, "manual", None) or {}) if row is not None else {}
        manual = manual if isinstance(manual, dict) else {}
        self.manual_tiers, self.manual_uses = _layer(manual.get("tiers"), manual.get("uses"), self.doc)
        #: The mode (Best, Balanced or Saver): the organisation's own once it picked one,
        #: else the service's default.
        picked = str(getattr(row, "mode", "") or "") if row is not None else ""
        self.mode = picked if picked in MODES else standard.default_mode(self.doc)
        #: The router's bar set by hand, or None to follow the service's (`bar`).
        try:
            held = manual.get("bar")
            self.manual_bar = None if held is None else min(1.0, max(0.5, float(held)))
        except (TypeError, ValueError):
            self.manual_bar = None
        #: The two sharing choices (Petar, 24 October 2026), each apart from Auto.
        self.share_totals = True if row is None else bool(getattr(row, "share_totals", True))
        self.compare = False if row is None else bool(getattr(row, "compare", False))
        try:
            self.compare_per_day = max(0, int(getattr(row, "compare_per_day", 1) if row is not None else 1))
        except (TypeError, ValueError):
            self.compare_per_day = 1
        #: Which providers can be asked here, read once (`providerkeys.has`).
        from . import providerkeys

        self.keys = {p: providerkeys.has(p, self.org, self.cfg) for p in PROVIDERS}

    @property
    def bar(self) -> float:
        """How sure Balanced's router must be that a message is easy for Cheaper to answer
        it: set by hand under Customise, or the service's."""
        return self.manual_bar if self.manual_bar is not None else standard.bar(self.doc)

    @property
    def auto(self) -> bool:
        """Whether either box is on Auto."""
        return self.auto_tiers or self.auto_uses

    def auto_in(self, box: str) -> bool:
        return self.auto_tiers if box == "tiers" else self.auto_uses

    def _manual(self, item: str) -> bool:
        """Whether this item is answered from the manual set: its box's Auto off, or
        locked."""
        return not self.auto_in(box_of(item)) or item in self.locked

    def can_ask(self, model: str) -> bool:
        """Whether this model's provider has a key here."""
        return bool(self.keys.get(company(model)))

    def tier(self, tier: str) -> list:
        """A tier's models, in order."""
        if self._manual(tier) and tier in self.manual_tiers:
            return list(self.manual_tiers[tier])
        return standard.tier_pick(tier, self.doc)

    def tier_model(self, tier: str) -> str:
        """The first model on a tier's list that can be asked here, else its first."""
        models = self.tier(tier)
        return next((m for m in models if self.can_ask(m)), models[0] if models else NONE)

    def base_choice(self, use_id: str):
        """What a use is on before the mode moves it: a tier, `OFF`, or a Custom list."""
        if self._manual(use_id) and use_id in self.manual_uses:
            return self.manual_uses[use_id]
        return _read_choice(standard.tier_of_use(use_id, self.doc))

    def choice(self, use_id: str):
        """What a use is on: a tier, `OFF`, or a Custom list, with the mode applied. Best
        and Saver put the chats the mode decides on Smart and Cheaper, and Saver puts every
        other use paid per token that is on Smart on Cheaper. A locked use, one on a model
        of its own and one that is off are left as they are."""
        choice = self.base_choice(use_id)
        if use_id in self.locked or is_custom(choice) or choice not in TIERS:
            return choice
        if standard.routed(use_id, self.doc):
            return {BEST: SMART, SAVER: CHEAPER}.get(self.mode, choice)
        if self.mode == SAVER and choice == SMART and not BY_ID[use_id].subscription:
            return CHEAPER
        return choice

    def routed(self, use_id: str) -> bool:
        """Whether each message this use answers has its tier picked by the router
        (`rouh/modelrouter.py`): only in Balanced, only for the chats the service's
        standard routes, and never for a locked use, which keeps its own tier."""
        return (self.mode == BALANCED and use_id not in self.locked
                and standard.routed(use_id, self.doc)
                and not is_custom(self.base_choice(use_id))
                and self.base_choice(use_id) in TIERS)

    def moved(self, use_id: str) -> bool:
        """Whether the mode moved this use off the tier it is set to (Best or Saver)."""
        return self.choice(use_id) != self.base_choice(use_id)

    def kind(self, use_id: str) -> str:
        """The choice with a model of its own named `CUSTOM`, and a routed use `AUTO`:
        what is written down of a call."""
        if self.routed(use_id):
            return AUTO
        choice = self.choice(use_id)
        return CUSTOM if is_custom(choice) else choice

    def candidates(self, use: Use, choice) -> list:
        """The models a use would ask on this choice, first asked first: a tier's list in the
        use's own order for that tier (`modelstandard.use_order`), or its Custom list; only
        those of a provider it can ask."""
        if is_custom(choice):
            models = list(choice)
        elif choice in TIERS and self._manual(choice) and choice in self.manual_tiers:
            # A tier the organisation set by hand is asked in its own order by every use:
            # the standard's order for a use is for the standard's list.
            models = self.tier(choice)
        elif choice in TIERS:
            models = standard.order_by(self.tier(choice), standard.use_order(use.id, choice, self.doc))
        else:
            return []
        return [m for m in models if company(m) in use.providers]

    def first(self, use: Use, models: list) -> str:
        """The model a use asks of these: the first whose provider has a key here, or, for a
        use that signs in by itself (Claude Code, Codex), simply the first."""
        if not use.needs_key:
            return models[0] if models else NONE
        return next((m for m in models if self.can_ask(m)), NONE)

    def _fallback(self, use: Use, choice) -> str:
        """For a use tied to a provider with no key here that answers as one plain question
        instead (`Use.fallback_any`): the first model on its tier's list, any provider's,
        that can be asked."""
        if not use.fallback_any:
            return NONE
        tier = choice if choice in TIERS else SMART
        models = standard.order_by(self.tier(tier), standard.use_order(use.id, tier, self.doc))
        if is_custom(choice):
            models = list(choice) + models
        return next((m for m in models if self.can_ask(m)), NONE)

    def model_for(self, use: Use, tier) -> str:
        """The model a use asks on this tier (or Custom list): the first on its list it can
        ask here. Never another provider's in secret: a use tied to one provider asks only
        that provider's (`Use.needs` says why), and its fallback is said on the page."""
        return self.first(use, self.candidates(use, tier))

    def tier_pair(self, use_id: str, tier: str) -> Pair:
        """The model and level a use asks on this tier, whatever tier it is set to:
        what the router's pick becomes (`rouh/modelrouter.py`)."""
        use = BY_ID[use_id]
        model = self.model_for(use, tier)
        fallback = False
        if not model:
            model, fallback = self._fallback(use, tier), True
        level = standard.effort(model, self.doc) if model else ""
        return Pair(model, (use.effort if level and use.effort else level), fallback=fallback and bool(model))

    def pair(self, use_id: str) -> Pair:
        """The model and level a use asks: `OFF` for a use that is off, `NONE` for one with
        nothing on its list it can ask here. A routed use with no message to read asks its
        own tier's: a turn is routed before it asks (`modelrouter`)."""
        choice = self.choice(use_id)
        if choice == OFF:
            return Pair(OFF, "")
        return self.tier_pair(use_id, choice)

    def standard_value(self, item: str, doc: dict | None = None):
        """What the standard (or `doc`) says an item is."""
        doc = doc or self.doc
        if item in TIERS:
            return standard.tier_pick(item, doc)
        return _read_choice(standard.tier_of_use(item, doc))

    def value(self, item: str):
        return self.tier(item) if item in TIERS else self.base_choice(item)

    def manual_value(self, item: str):
        """An item's value in the manual set, or the standard's where it names none."""
        held = self.manual_tiers.get(item) if item in TIERS else self.manual_uses.get(item)
        return held if held is not None else self.standard_value(item)

    def blocked(self, use_id: str) -> str:
        """Why a use cannot ask a model here, or what it does instead, in words for the
        page, or ""."""
        use = BY_ID[use_id]
        choice = self.choice(use_id)
        if choice == OFF:
            return ""
        pair = self.pair(use_id)
        if pair.fallback:
            return use.fallback or f"Its provider has no key here, so {model_name(pair.model)} answers instead."
        if not pair.model:
            if use.fallback_use and self.choice(use.fallback_use) != OFF and self.pair(use.fallback_use).model:
                return use.fallback
            asked = sorted({company(m) for m in self.candidates(use, choice)}, key=PROVIDERS.index)
            who = " or ".join(PROVIDER_NAMES[p] for p in asked) or "any provider"
            return (f"No model on its list can be asked here: there is no {who} key, so this does "
                    "not run." + (f" {use.fallback}" if use.fallback else " Add a key in Models, above."))
        if use.decisions and not is_decisions_model(pair.model):
            return (f"{model_name(pair.model)} cannot be asked: OpenAI's Decisions API takes only "
                    + ", ".join(model_name(m) for m in DECISIONS_MODELS) + ", so this does not run.")
        return ""

    def differs(self, box: str | None = None) -> bool:
        """Whether Reset to defaults would change anything in a box (or either): with
        its Auto off, an item not locked that is not what the standard built into this
        Rouh says. With Auto on there is nothing of the person's to reset."""
        base = standard.merged(None)
        return any(not self.auto_in(b) and any(
            _same(self.value(i), self.standard_value(i, base)) is False
            for i in ITEMS if box_of(i) == b and i not in self.locked) for b in _boxes(box))


def _same(a, b) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    return a == b


def use_pair(use_id: str, org_id: str | None = None, cfg=None) -> Pair:
    """The model a use asks, and the level it thinks at: its tier's pick of the
    company it can ask, or its main model, or the model of its own on Custom, at
    the level that comes with the model. `OFF` comes back as the model `OFF`, for
    the one use that may be off. Never raises for a use that exists."""
    return Now(org_id, cfg).pair(use_id)


def use_model(use_id: str, org_id: str | None = None, cfg=None) -> str:
    """Only the model a use asks (`use_pair`)."""
    return use_pair(use_id, org_id, cfg).model


def use_tier(use_id: str, org_id: str | None = None, cfg=None) -> str:
    """What a use is on: a tier, `OFF`, `AUTO`, or `CUSTOM`."""
    return Now(org_id, cfg).kind(use_id)


def use_of(purpose: str, session_id: str = "") -> str:
    """The use a request written down under this purpose was made for, or "".
    A turn is a chat's: Rouh's, a heartbeat's, or every other chat's."""
    if purpose == "turn":
        from . import chatkinds

        return chatkinds.use_for(session_id)
    for use in USES:
        if purpose in use.purposes and purpose != "turn":
            return use.id
    return ""


# --- changing them ---------------------------------------------------------------------------
#
# Every change to a tier or a use is to the manual set, which once written names
# everything, so no later standard moves it.

def may_change(who) -> bool:
    """Whether this person may move their organisation's models: its
    administrators may, the way they manage its Google app. The model decides
    what everybody in it is answered with, and what it costs."""
    return bool(who is not None and getattr(who, "is_admin", False))


def _write(org_id: str, by: str, **fields) -> None:
    from .models import ModelDefaults

    # What Sync replaced is kept only until the next change: Undo is for that one press.
    fields.setdefault("undo", {})
    ModelDefaults.objects.update_or_create(
        org_id=str(org_id),
        defaults={**fields, "changed_by": str(by or "")[:120], "changed_at": time.time()})


def _kept(value):
    """A value as the row keeps it: a tier as its ordered list (`{"models": [...]}`), a
    Custom use as its list."""
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _manual_set(now: Now) -> tuple[dict, dict]:
    """The whole manual set as it stands: what it names, and the standard's value for
    anything it does not, so that once written no later standard moves it."""
    return ({t: now.manual_value(t) for t in TIERS}, {u: now.manual_value(u) for u in BY_ID})


#: Not given: the bar set by hand stays as it is (`_write_manual`).
_KEEP = object()


def _write_manual(org_id: str, by: str, tiers: dict, uses: dict, *, bar=_KEEP, **more) -> None:
    if bar is _KEEP:
        bar = Now(org_id).manual_bar
    manual = {"tiers": {t: {"models": _kept(v)} for t, v in tiers.items()},
              "uses": {u: _kept(v) for u, v in uses.items()}}
    if bar is not None:
        manual["bar"] = bar
    _write(org_id, by, manual=manual, **more)


def _not_while_auto(now: Now, item: str, what: str) -> None:
    box = box_of(item)
    if now.auto_in(box):
        raise Refused(f"Auto is on in {BOX_NAMES[box]}, so {what} follows the Rouh model service "
                      f"and cannot be changed. Turn Auto off in {BOX_NAMES[box]} first, and your "
                      "own settings apply.")


def _models_given(models, what: str) -> list:
    """A list of models as somebody gave it, every one checked: refused with the first that
    is not a model to choose."""
    if isinstance(models, str):
        models = [m for m in models.replace(",", " ").split() if m]
    got = []
    for m in models or []:
        wanted = current_model(str(m).strip())
        if wanted not in _MODELS:
            raise Refused(f"{model_name(wanted) or 'That'} is not a model to choose. It can be "
                          + ", ".join(n for _, n in MODEL_CHOICES) + ".")
        if wanted not in got:
            got.append(wanted)
    if not got:
        raise Refused(f"Name at least one model for {what}.")
    return got


def put_tier(org_id: str, tier: str, model: str | None = None, *, main: str | None = None,
             models=None, by: str = "", cfg=None) -> None:
    """A tier's ordered list of models (`models`), or one model moved to the front of it,
    added if it was not on it ("put Sonnet in Cheaper"), or a provider's first model on it
    moved to the front (`main`, "make Google's model Smart's first"). Only with the tiers'
    Auto off: with it on, every tier is the service's."""
    tier = standard.tier_id(tier)
    if tier not in TIERS:
        raise Refused(f"There is no tier called {tier!r}: it is {', '.join(TIERS)}.")
    now = Now(org_id, cfg)
    _not_while_auto(now, tier, TIER_NAMES[tier])
    got = list(now.tier(tier))
    if models is not None:
        got = _models_given(models, TIER_NAMES[tier])
    elif model:
        wanted = _models_given([model], TIER_NAMES[tier])[0]
        got = [wanted] + [m for m in got if m != wanted]
    elif main is not None:
        main = str(main).strip().lower()
        if main not in PROVIDERS:
            raise Refused("A provider is " + ", ".join(PROVIDER_NAMES.values()) + ".")
        first = next((m for m in got if company(m) == main), None)
        if first is None:
            raise Refused(f"{TIER_NAMES[tier]} has no {PROVIDER_NAMES[main]} model: add one first.")
        got = [first] + [m for m in got if m != first]
    else:
        raise Refused(f"Name the model to put in {TIER_NAMES[tier]}.")
    tiers, uses = _manual_set(now)
    tiers[tier] = got
    _write_manual(org_id, by, tiers, uses)
    log.info("models for %s changed by %s: %s is now %s", org_id, by or "somebody", tier, ", ".join(got))


def put_use(org_id: str, use_id: str, tier, *, models=None, by: str = "", cfg=None) -> None:
    """Put a use on a tier, off, or models of its own (Custom: `models` an ordered list, or
    `tier` one model's id). Only with Each use's Auto off: with it on, every use is the
    service's."""
    use = BY_ID.get(str(use_id or "").strip())
    if use is None:
        raise Refused(f"There is no use called {use_id!r}.")
    raw = str(tier or "").strip()
    if models is not None:
        choice = _models_given(models, use.name)
    elif _is_model_id(raw):
        choice = _models_given([raw], use.name)
    else:
        choice = standard.tier_id(raw)
    if choice == CUSTOM:
        raise Refused(f"Name the model for {use.name}.")
    if not _choice_ok(use, choice):
        if is_custom(choice):
            bad = next(m for m in choice if company(m) not in use.providers)
            raise Refused(f"{use.name} can only ask "
                          + " or ".join(PROVIDER_NAMES[p] for p in use.providers)
                          + f", so it cannot be {model_name(bad)}.")
        can = list(TIERS) + ([OFF] if use.can_be_off else [])
        raise Refused(f"{use.name} can be {', '.join(can)} or a model of its own, not {raw!r}.")
    now = Now(org_id, cfg)
    _not_while_auto(now, use.id, use.name)
    tiers, uses = _manual_set(now)
    uses[use.id] = choice
    _write_manual(org_id, by, tiers, uses)
    log.info("models for %s changed by %s: %s is now on %s", org_id, by or "somebody", use.id,
             ", ".join(choice) if is_custom(choice) else choice)


def put_lock(org_id: str, item: str, on: bool, *, by: str = "", cfg=None) -> None:
    """Lock an item, a tier or a use, or unlock it. A locked item keeps its own value:
    Auto, Sync, Reset to defaults and a new standard leave it as it is. Locked while
    Auto is on, it keeps what it is now."""
    item = standard.tier_id(item) if standard.tier_id(item) in TIERS else str(item or "").strip()
    if item not in TIERS and item not in BY_ID:
        raise Refused(f"There is no tier or use called {item!r}.")
    now = Now(org_id, cfg)
    locked = set(now.locked)
    tiers, uses = _manual_set(now)
    if on:
        locked.add(item)
        # What it shows now is what it keeps, the mode's move included.
        (tiers if item in TIERS else uses)[item] = now.value(item) if item in TIERS else now.choice(item)
    else:
        locked.discard(item)
    _write_manual(org_id, by, tiers, uses, locked=sorted(locked))
    log.info("models for %s changed by %s: %s %s", org_id, by or "somebody", item,
             "locked" if on else "unlocked")


def put_mode(org_id: str, mode: str, *, by: str = "", cfg=None) -> None:
    """The mode: Best, Balanced or Saver (Petar, 23 October 2026). It is the one choice
    most people make, and it changes nothing anybody set by hand."""
    mode = str(mode or "").strip().lower()
    if mode not in MODES:
        raise Refused(f"There is no mode called {mode!r}: it is " + ", ".join(MODES) + ".")
    now = Now(org_id, cfg)
    tiers, uses = _manual_set(now)
    _write_manual(org_id, by, tiers, uses, mode=mode, bar=now.manual_bar)
    log.info("models for %s changed by %s: the mode is now %s", org_id, by or "somebody", mode)


def put_bar(org_id: str, bar, *, by: str = "", cfg=None) -> None:
    """The router's bar, set by hand (a number from 0.5 to 1, or a percentage), or None to
    follow the service's again. Set by hand, no standard moves it, the way a lock holds."""
    now = Now(org_id, cfg)
    value = None
    if bar not in (None, "", "service", "standard"):
        try:
            value = float(str(bar).strip().rstrip("%"))
        except ValueError:
            raise Refused(f"{bar!r} is not a number: the bar is how sure the router must be, "
                          "from 50% to 100%.")
        if value > 1:
            value /= 100
        if not 0.5 <= value <= 1.0:
            raise Refused("The bar is from 50% to 100%: below 50% Cheaper would answer messages "
                          "the router thinks are hard.")
        value = round(value, 3)
    tiers, uses = _manual_set(now)
    _write_manual(org_id, by, tiers, uses, bar=value)
    log.info("models for %s changed by %s: the router's bar is now %s", org_id, by or "somebody",
             "the service's" if value is None else value)


def put_auto(org_id: str, on: bool, box: str | None = None, *, by: str = "", cfg=None) -> None:
    """Auto on in a box (or both): it follows the Rouh model service. Off: its manual
    settings apply. While either box is on, the day's counts are sent and double calls
    run. The manual set is kept as it is either way, so turning Auto on and off again
    brings it back exactly; turned off the first time it is what everything showed."""
    boxes = _boxes(box)
    now = Now(org_id, cfg)
    tiers, uses = _manual_set(now)
    _write_manual(org_id, by, tiers, uses, **{f"auto_{b}": bool(on) for b in boxes})
    log.info("models for %s changed by %s: Auto %s for %s", org_id, by or "somebody",
             "on" if on else "off", ", ".join(boxes))


def _set_from(org_id: str, box: str | None, doc: dict, by: str, cfg, what: str) -> int:
    """The manual settings not locked, in a box with Auto off (or every such box),
    made what `doc` says. What it replaced is kept for Undo. The number changed."""
    now = Now(org_id, cfg)
    boxes = [b for b in _boxes(box) if not now.auto_in(b)]
    if not boxes:
        raise Refused((f"Auto is on in {BOX_NAMES[box]}" if box else "Auto is on in both boxes")
                      + f", so it already follows the Rouh model service: {what} is for your own "
                      "settings, with Auto off.")
    tiers, uses = _manual_set(now)
    before: dict = {"tiers": {}, "uses": {}}
    for item in ITEMS:
        if box_of(item) not in boxes or item in now.locked:
            continue
        held = tiers if item in TIERS else uses
        new = now.standard_value(item, doc)
        if _same(held[item], new) is False:
            before[box_of(item)][item] = _kept(held[item])
            held[item] = new
    changed = len(before["tiers"]) + len(before["uses"])
    _write_manual(org_id, by, tiers, uses, undo=before if changed else {})
    return changed


def sync(org_id: str, box: str | None = None, *, by: str = "", cfg=None) -> int:
    """Sync, a one-time press: a box's manual settings (or those of every box with
    Auto off) made what the Rouh model service says now, except the locked items.
    The number of settings it changed; Undo puts them back (`undo_sync`)."""
    changed = _set_from(org_id, box, standard.current(), by, cfg, "Sync")
    log.info("models for %s: %s synced with the service by %s, %d changed", org_id,
             box or "the manual settings", by or "somebody", changed)
    return changed


def undo_sync(org_id: str, *, by: str = "", cfg=None) -> int:
    """What the last Sync or Reset changed, put back, except what was locked since.
    Only until the next change. The number put back."""
    now = Now(org_id, cfg)
    if not now.undo:
        raise Refused("There is nothing to undo: the last change was not a Sync or a Reset.")
    tiers, uses = _manual_set(now)
    kept_t, kept_u = _layer(now.undo.get("tiers"), now.undo.get("uses"), now.doc)
    back = 0
    for held, kept in ((tiers, kept_t), (uses, kept_u)):
        for item, value in kept.items():
            if item not in now.locked:
                held[item] = value
                back += 1
    _write_manual(org_id, by, tiers, uses)
    log.info("models for %s: the last Sync undone by %s, %d put back", org_id, by or "somebody", back)
    return back


def reset(org_id: str, box: str | None = None, *, by: str = "", cfg=None) -> int:
    """A box's manual settings (or those of every box with Auto off) back to the
    standard built into this Rouh, except the locked items. With Auto on there is
    nothing of the person's to reset. Undo puts them back, like Sync's."""
    now = Now(org_id, cfg)
    if not any(not now.auto_in(b) for b in _boxes(box)):
        return 0
    changed = _set_from(org_id, box, standard.merged(None), by, cfg, "Reset to defaults")
    log.info("models for %s reset to the defaults by %s", org_id, by or "somebody")
    return changed


def shares(org_id: str | None = None) -> bool:
    """Whether this organisation sends its anonymous daily totals to rouh.land: its own
    toggle, "Share anonymous totals with rouh.land" (Petar, 24 October 2026), on unless
    turned off, and no longer Auto's. Whether they really leave is `config.model_outcomes_send`
    (`rouh/modeloutcomes.py`)."""
    row = _row(org_id)
    return True if row is None else bool(getattr(row, "share_totals", True))


def compares(org_id: str | None = None) -> bool:
    """Whether this organisation takes part in blind comparisons: its own toggle, off until
    somebody turns it on, because a comparison sends the person's own request to a second
    provider (`rouh/modelvotes.py`). Double calls, which do the same, run only then too."""
    row = _row(org_id)
    return False if row is None else bool(getattr(row, "compare", False))


def compare_per_day(org_id: str | None = None) -> int:
    """At most this many comparisons a person a day: 1 to start (Petar: "start with at most 1
    comparison per person per day, adjustable")."""
    row = _row(org_id)
    try:
        return 1 if row is None else max(0, int(getattr(row, "compare_per_day", 1)))
    except (TypeError, ValueError):
        return 1


def double_rate(org_id: str | None = None) -> float:
    """The share of read-only answers nobody is there to judge that is asked of a second
    model too: the standard's with blind comparisons on, and none otherwise."""
    return standard.double_rate() if compares(org_id) else 0.0


def second_opinion(use_id: str, first: str, org_id: str | None = None, cfg=None) -> Pair | None:
    """The model a double call or a blind comparison asks beside `first`: the first model on
    the same list from another provider that can be asked here, so the two answers come from
    two providers; else, with only one provider, nothing. Only a use that can ask more than
    one provider."""
    now = Now(org_id, cfg)
    use = BY_ID.get(use_id)
    if use is None or use.only:
        return None
    choice = now.choice(use_id)
    if choice == OFF:
        return None
    tier = choice if (choice in TIERS or is_custom(choice)) else SMART
    models = now.candidates(use, tier)
    if is_custom(tier):
        models += now.candidates(use, SMART)
    for model in models:
        if model != first and company(model) != company(first) and now.can_ask(model):
            return Pair(model, standard.effort(model, now.doc))
    return None


def put_share(org_id: str, which: str, on: bool, *, per_day=None, by: str = "", cfg=None) -> None:
    """The totals toggle (`which` "share") or the blind comparisons' (`which` "compare"), and
    how many comparisons a person a day (`per_day`, 0 to 10)."""
    from .models import ModelDefaults

    now = Now(org_id, cfg)
    tiers, uses = _manual_set(now)
    more = {}
    if which == "share":
        more["share_totals"] = bool(on)
    else:
        if on is not None:
            more["compare"] = bool(on)
        if per_day is not None:
            try:
                n = int(per_day)
            except (TypeError, ValueError):
                raise Refused("How many comparisons a day is a whole number, 0 to 10.")
            if not 0 <= n <= 10:
                raise Refused("How many comparisons a day is a whole number, 0 to 10.")
            more["compare_per_day"] = n
    if not ModelDefaults.objects.filter(org_id=str(org_id)).exists():
        _write_manual(org_id, by, tiers, uses, **more)
    else:
        ModelDefaults.objects.filter(org_id=str(org_id)).update(
            **more, changed_by=str(by or "")[:120], changed_at=time.time())
    log.info("models for %s changed by %s: %s", org_id, by or "somebody", more)


def put(org_id: str, which: str, *, model: str | None = None, tier: str | None = None,
        main: str | None = None, lock: bool | None = None, on: bool | None = None,
        box: str | None = None, mode: str | None = None, bar=_KEEP, models=None,
        per_day=None, by: str = "", cfg=None) -> int | None:
    """One change, by name:

    - `which` "mode" with `mode`: Best, Balanced or Saver;
    - `which` "bar" with `bar`: the router's bar set by hand, or None for the service's;
    - a tier (`which` a tier): `models`, its whole ordered list; or `model` moved to the
      front of it; or `main`, a provider, whose first model on it is moved to the front;
    - a use (`which` a use): `tier` a tier or "off", or `models` (or `model`) models of its
      own (Custom), first asked first;
    - either, with `lock` true or false: locked or not;
    - `which` "auto" with `on`, and `box` "tiers" or "uses" or neither for both:
      Auto on or off in that box;
    - `which` "share" with `on`: the anonymous daily totals shared with rouh.land or not;
    - `which` "compare" with `on` and/or `per_day`: the blind comparisons on or off, and how
      many a person a day;
    - `which` "sync", with `box` or not: the manual settings of that box (or of every
      box with Auto off) made what the service says now, except what is locked (a
      one-time press), giving back how many changed;
    - `which` "undo_sync": what the last Sync or Reset changed, put back;
    - `which` "reset", with `box` or not: the manual settings not locked back to the
      defaults.

    And the merge pass's model written again for `land.sh` (`publish_merge_pick`)."""
    which = str(which or "").strip()
    low = standard.tier_id(which)
    got = None
    if low == "mode":
        put_mode(org_id, mode or "", by=by, cfg=cfg)
    elif low == "bar":
        put_bar(org_id, None if bar is _KEEP else bar, by=by, cfg=cfg)
    elif low == "reset":
        got = reset(org_id, box, by=by, cfg=cfg)
    elif low == "auto":
        if on is None:
            raise Refused("Say whether Auto is on or off.")
        put_auto(org_id, bool(on), box, by=by, cfg=cfg)
    elif low in ("share", "compare"):
        if on is None and (low == "share" or per_day is None):
            raise Refused("Say whether it is on or off.")
        put_share(org_id, low, on, per_day=per_day, by=by, cfg=cfg)
    elif low == "sync":
        got = sync(org_id, box, by=by, cfg=cfg)
    elif low in ("undo_sync", "undo"):
        got = undo_sync(org_id, by=by, cfg=cfg)
    elif lock is not None and (low in TIERS or which in BY_ID):
        put_lock(org_id, low if low in TIERS else which, bool(lock), by=by, cfg=cfg)
    elif low in TIERS:
        put_tier(org_id, low, model, main=main, models=models, by=by, cfg=cfg)
    elif which in BY_ID:
        if not tier and not model and models is None:
            u = BY_ID[which]
            raise Refused(f"Name the tier for {u.name}: " + ", ".join(TIERS)
                          + (", off" if u.can_be_off else "") + ", or a model of its own.")
        if models is not None or (model and (not tier or tier == CUSTOM)):
            put_use(org_id, which, None, models=models if models is not None else [model], by=by, cfg=cfg)
        else:
            put_use(org_id, which, tier, by=by, cfg=cfg)
    else:
        raise Refused(f"There is no tier or use called {which!r}: a tier is "
                      f"{', '.join(TIERS)}, and a use is one of {', '.join(BY_ID)}.")
    publish_merge_pick(org_id, cfg)
    return got


def publish_merge_pick(org_id: str | None = None, cfg=None) -> bool:
    """Write the merge pass's model and level where `land.sh` reads them. Never raises.

    `land.sh` runs in a job's own checkout as whichever user lands the work, and
    cannot read this database, so the model for "Merging a clash" is written into
    the landing directory when Rouh starts, whenever anything here changes, and
    whenever a new standard is fetched.
    """
    try:
        from . import merge_pass, owner

        got = use_pair("merge_pass", org_id, cfg)
        # What the merge pass's prompt calls the owner: it runs where the
        # database cannot be read (`rouh/merge_pass.py`).
        try:
            words = owner.words(owner.resolve())
        except Exception:                           # noqa: BLE001 - "the owner" then
            log.exception("the owner could not be read for the merge pass")
            words = None
        publish_mode(org_id, cfg)
        return merge_pass.write_merge_pick(got.model, got.effort, cfg=cfg or _config, words=words)
    except Exception:
        log.exception("the merge pass's model could not be written for land.sh")
        return False


#: The file in the landing directory that says the mode, for the one program, which cannot
#: read this database: a run of Codex whose ChatGPT subscription runs out in Saver is never
#: offered the API key (`one/billing.py`, `saver`).
MODE_FILE = "model-mode.json"


def publish_mode(org_id: str | None = None, cfg=None) -> bool:
    """Write the mode where the one program reads it. Never raises."""
    import json as _json
    import os as _os

    try:
        from .conflicts import land_dir, write_bytes

        base = land_dir(cfg or _config)
        if not base.is_dir():
            return False
        place = base / MODE_FILE
        ok = write_bytes(place, _json.dumps({"mode": Now(org_id, cfg).mode, "at": time.time()}) + "\n")
        if ok:
            try:
                _os.chmod(place, 0o664)
            except OSError:
                pass
        return bool(ok)
    except Exception:
        log.exception("the mode could not be written for the one program")
        return False


# --- what the page and the model are told ----------------------------------------------------

def _model_shown(model: str, doc: dict, now: "Now") -> dict:
    e = (doc.get("efforts") or {}).get(model) or {}
    level = str(e.get("effort") or "")
    return {"id": model, "name": model_name(model), "effort": level,
            "effort_name": _effort_name(level),
            "why": e.get("why") or "", "source": e.get("source") or "",
            "source_title": e.get("source_title") or "", "company": company(model),
            "company_name": PROVIDER_NAMES[company(model)], "has_key": now.can_ask(model)}


def _effort_name(level: str) -> str:
    """A level as a row says it: a model that takes none (Haiku 4.5) says so too."""
    return "No reasoning" if level in ("none", "") else EFFORT_NAMES.get(level, level)


def _pair_shown(pair: Pair) -> dict:
    if pair.model in (OFF, NONE):
        return {"model": "", "model_name": "", "effort": "", "effort_name": "", "fallback": False}
    return {"model": pair.model, "model_name": model_name(pair.model), "effort": pair.effort,
            "effort_name": _effort_name(pair.effort), "fallback": pair.fallback}


def _list_shown(models: list, asked: str, doc: dict, now: "Now", use: Use | None = None) -> list:
    """An ordered list as a row draws it: each model with its provider, whether it can be
    asked here, and which one is the one asked."""
    out = []
    for m in models:
        shown = _model_shown(m, doc, now)
        shown["asked"] = m == asked
        if use is not None and not use.needs_key:
            shown["has_key"] = True        # signs in by itself
        out.append(shown)
    return out


def shown(org_id: str | None = None, cfg=None, *, who=None) -> dict:
    """What the Models page draws, and what the tool says."""
    from . import providerkeys

    now = Now(org_id, cfg)
    doc, cfg = now.doc, now.cfg
    out = {"can_change": may_change(who),
           "mode": now.mode,
           "modes": [{"id": m, "name": MODE_NAMES[m], "why": standard.mode_why(m, doc)} for m in MODES],
           "mode_default": standard.default_mode(doc),
           "bar": now.bar, "bar_standard": standard.bar(doc), "bar_set": now.manual_bar is not None,
           "bar_why": str((doc.get("router") or {}).get("why") or ""),
           "auto": {b: now.auto_in(b) for b in BOXES},
           "differs": {b: now.differs(b) for b in BOXES},
           "can_undo": bool(now.undo),
           "locked": sorted(now.locked),
           "changed_by": getattr(now.row, "changed_by", "") or "",
           "changed_at": getattr(now.row, "changed_at", None),
           "providers": providerkeys.shown(now.org, cfg),
           "provider_names": dict(PROVIDER_NAMES),
           "share_totals": now.share_totals, "compare": now.compare,
           "compare_per_day": now.compare_per_day,
           "models": {p: [_model_shown(m, doc, now) for m, _ in CHOICES_OF[p]] for p in PROVIDERS},
           "tiers": [], "groups": list(GROUPS), "uses": []}
    for tier in TIERS:
        models = now.tier(tier)
        std = standard.tier_pick(tier, doc)
        first = next((m for m in models if now.can_ask(m)), NONE)
        main = _model_shown(first, doc, now) if first else {"name": "", "effort_name": ""}
        out["tiers"].append({
            "id": tier, "name": TIER_NAMES[tier], "models": _list_shown(models, first, doc, now),
            "model": first, "model_name": main["name"], "effort": main.get("effort", ""),
            "effort_name": main["effort_name"], "none": not first,
            "standard": list(std), "changed": not _same(models, std), "locked": tier in now.locked,
            "tier_why": (doc["tiers"][tier].get("why") or "")})
    # What each use would ask with nothing changed, for the dot in its own chooser.
    plain = Now.__new__(Now)
    plain.__dict__.update(now.__dict__)
    plain.auto_tiers, plain.auto_uses, plain.locked, plain.mode = True, True, set(), BALANCED
    for group in GROUPS:
        for use in (u for u in USES if u.group == group):
            choice = now.choice(use.id)
            rec = doc["uses"].get(use.id) or {}
            rec_choice = _read_choice(standard.tier_of_use(use.id, doc))
            options = ([{"id": OFF, "name": CHOICE_NAMES[OFF]}] if use.can_be_off else []) + [
                {"id": t, "name": TIER_NAMES[t], **_pair_shown(now.tier_pair(use.id, t))}
                for t in TIERS] + [{"id": CUSTOM, "name": CHOICE_NAMES[CUSTOM]}]
            pair = now.pair(use.id)
            listed = now.candidates(use, choice) if choice != OFF else []
            out["uses"].append({
                "id": use.id, "group": use.group, "name": use.name, "said": use.said,
                "tier": CUSTOM if is_custom(choice) else choice,
                "custom": list(choice) if is_custom(choice) else [],
                "list": _list_shown(listed, pair.model, doc, now, use),
                "recommended": CUSTOM if is_custom(rec_choice) else rec_choice,
                "recommended_why": rec.get("why") or "",
                "recommended_model": plain.pair(use.id).model if rec_choice != OFF else "",
                "only": use.only, "providers": list(use.providers), "needs": use.needs,
                "fallback_said": use.fallback, "blocked": now.blocked(use.id),
                "off_said": use.off_said, "options": options,
                "changed": not _same(choice, rec_choice), "locked": use.id in now.locked,
                **_pair_shown(pair),
                # In Balanced, for the chats the service routes, the tier is picked per message;
                # Best and Saver move what nobody set by hand (`Now.choice`).
                "routed": now.routed(use.id), "moved": now.moved(use.id),
                "subscription": use.subscription})
    fetch = standard.fetched_said()
    out["standard"] = {"revision": doc.get("revision"), "published": doc.get("published"),
                       "source": doc.get("source"), "checked_at": fetch.get("at"),
                       "checked_ok": fetch.get("ok"), "url": cfg.model_standard_url}
    out["double_rate"] = standard.double_rate(doc)
    # What Ask AI answers with, which the This page side names.
    ask = now.pair("askai")
    out["work_model"], out["work_model_name"] = ask.model, model_name(ask.model)
    out["work_effort"] = ask.effort
    return out


def _names(models) -> str:
    return ", then ".join(f"{model_name(m)} ({m})" for m in models)


def said(org_id: str | None = None, cfg=None) -> str:
    """Everything in a few sentences, as the model says it back."""
    now = Now(org_id, cfg)

    def box_said(box: str) -> str:
        return (f"{BOX_NAMES[box]} ({box}) is on Auto: it follows the Rouh model service, "
                "except what is locked, and cannot be changed until its Auto is off."
                if now.auto_in(box) else
                f"{BOX_NAMES[box]} ({box}) has Auto off: its manual settings apply and no "
                "standard moves them; Sync makes them what the service says now.")

    mode_said = {BEST: "every chat message is answered on Smart",
                 BALANCED: (f"the router (OpenAI's Decisions API, or without an OpenAI key a plain "
                            f"easy-or-hard question to the cheapest model) reads each chat message and "
                            f"Cheaper answers only when it is at least {round(now.bar * 100)}% sure the "
                            "message is easy" + (" (a bar set by hand)" if now.manual_bar is not None else "")
                            + "; otherwise Smart"),
                 SAVER: ("every chat message is answered on Cheaper, and every use paid per token is on "
                         "Cheaper too; Claude Code and Codex runs keep their tier, on the subscription")}
    keys = [PROVIDER_NAMES[p] for p in PROVIDERS if now.keys.get(p)]
    lines = [f"The mode is {MODE_NAMES[now.mode]} [{now.mode}]: {mode_said[now.mode]}. The modes are "
             "best, balanced and saver.",
             "This Rouh can ask " + (", ".join(keys) if keys else "no provider at all")
             + " (a provider is asked only with a key; Google's and xAI's are typed into Anatomy, Rouh Land Account, Models). "
             "Each tier is an ordered list of models across providers, and a use asks the first one "
             "on its list it has a key for.",
             f"The service's standard is {now.doc.get('revision')}.", box_said("tiers"), box_said("uses"),
             ("Anonymous daily totals are shared with rouh.land" if now.share_totals else
              "Anonymous daily totals are not shared") + "; blind comparisons are "
             + (f"on (at most {now.compare_per_day} a person a day)" if now.compare else "off") + "."]
    for tier in TIERS:
        models = now.tier(tier)
        first = now.tier_model(tier)
        std = standard.tier_pick(tier, now.doc)
        mark = "" if _same(models, std) else " (the standard's: " + _names(std) + ")"
        lines.append(f"{TIER_NAMES[tier]} [{tier}]: {_names(models)}; asked here: "
                     f"{model_name(first) if now.can_ask(first) else 'none, no key for any of them'}"
                     f"{mark}" + (", locked" if tier in now.locked else "") + ".")
    uses = []
    for use in USES:
        choice = now.choice(use.id)
        rec = _read_choice(standard.tier_of_use(use.id, now.doc))
        pair = now.pair(use.id)
        if choice == OFF:
            what = "off"
        elif now.routed(use.id):
            what = ("picked per message by the router: Cheaper when it is sure the message is easy, "
                    f"else {TIER_NAMES.get(choice, choice)}")
        elif not pair.model:
            what = (f"{'Custom' if is_custom(choice) else TIER_NAMES[choice]}, but no model on its list "
                    "can be asked here, so it does not run")
        else:
            what = (f"Custom ({_names(choice)}), so {model_name(pair.model)}" if is_custom(choice)
                    else f"{TIER_NAMES[choice]}, so {model_name(pair.model)}")
            what += (f" at {pair.effort}" if pair.effort and pair.effort != "none"
                     else ", with no reasoning")
            if pair.fallback:
                what += ", as one plain question, since its own provider has no key here"
        if now.moved(use.id):
            what += f" (moved there by {MODE_NAMES[now.mode]})"
        elif not _same(choice, rec):
            what += f" (the standard's: {CHOICE_NAMES.get(rec, 'Custom') if not is_custom(rec) else 'Custom'})"
        if use.id in now.locked:
            what += ", locked"
        uses.append(f"{use.name} [{use.id}]: {what}")
    lines.append("Each use of a model: " + "; ".join(uses) + ".")
    lines.append("Nothing that Reset to defaults would change." if not now.differs() else
                 "Some of it differs from the defaults, so Reset to defaults would change it.")
    return " ".join(lines)
