"""Every setting Rouh reads, in one place, with the reasoning attached.

Nothing here reads a secret at import time except through the environment, so
this file is safe to read and safe to commit. The secrets live in
/var/www/rouh/.env on the server and are loaded into the process by systemd.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


#: The name every setting here used to start with. The server's own `.env` and
#: five systemd drop-ins still say `JARVIS_...`, and neither is written by a
#: deploy, so a rename that only moved the code would have taken the API keys,
#: the data directory and the public address with it. Both prefixes are read,
#: `ROUH_` first, so the two can be changed over whenever somebody is at the
#: machine rather than in the same instant as this file. RENAME.md has the rest.
OLD_PREFIX = "JARVIS_"
PREFIX = "ROUH_"


def _site(path: str) -> str:
    """An address on Rouh's public site, from the one setting ROUH_SITE_URL (`rouh/site.py`)."""
    from .site import url

    return url(path)


def _env(name: str, default: str = "") -> str:
    """A setting, by its own name, then by the name it had before the rename."""
    said = os.environ.get(name)
    if said is None and name.startswith(PREFIX):
        said = os.environ.get(OLD_PREFIX + name[len(PREFIX):])
    return (said if said is not None else default).strip()


def _read_secret(path: str) -> str:
    """A secret kept in a file of its own, or "" when there is none to read."""
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


#: Linux users that were renamed on the machines Rouh runs on, old name to new
#: (RENAME.md, "On the machine"). The uid did not change, so a setting that
#: still names the old user means the new one.
RENAMED_USERS = {"jarvis": "rouh"}


def _user_exists(name: str) -> bool:
    try:
        import pwd

        pwd.getpwnam(name)
        return True
    except (KeyError, ImportError):
        return False


def _machine_user(name: str) -> str:
    """A user named by a setting, as it is called on this machine now.

    The `jarvis` user became `rouh` on 22 September 2026 and the setting that
    names the workers' user did not follow it, so from then on every worker
    was started with `runuser -u jarvis`, which does not exist, and died in the
    second it was started (b0e4656f and d05698d4 on 24 September). A name this
    machine does not have is read as the name it was renamed to, when that one
    exists. Anything else is left as it was said: `crew.py` refuses to start a
    worker as a user that is not there, in words, before anything is made.
    """
    name = (name or "").strip()
    if not name or _user_exists(name):
        return name
    renamed = RENAMED_USERS.get(name)
    return renamed if renamed and _user_exists(renamed) else name


def _flag(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


#: The file that says a workspace has been reshaped into a tree of projects and
#: tasks. `objecttree.MAP_FILE` is this same name and reads it from here; it is
#: written down in this file because `_workspace_root` below has to answer
#: before anything else in Rouh is imported.
WORKSPACE_MAP = "_migration-map.json"


def _workspace_root() -> str:
    """The person's workspace: wherever the installation's setting says.

    `ROUH_WORKSPACE` names it, and `ROUH_ASSISTANT_REPO`, its name before 21
    October 2026, is read when that is not said. On the server it is
    `/var/www/rouh/workspace`, a checkout of the person's own private
    repository, beside Rouh's code and never inside it: Rouh's code is
    software anybody may one day read, and the workspace is a life.

    It was `workspace/` inside Rouh's own checkout from 21 September 2026 to 21
    October 2026, and before that a repository of its own at `/srv/assistant`.
    Nothing here knows either path any more. Nothing configured is no
    workspace: assistant jobs and `read_workspace` are off, and nothing is
    guessed, so a copy of the code can never be pointed at somebody's tasks by
    where it happens to be checked out.

    A reshaped workspace is the only one Rouh can draw - the index comes out
    of the object rows, and a flat `tasks/NN.name` has no rows - so a
    configured folder without `_migration-map.json` is still answered, and the
    pages that need the tree say it is not there.
    """
    return _env("ROUH_WORKSPACE") or _env("ROUH_ASSISTANT_REPO")


def _content_paths() -> str:
    """What counts as content rather than code in Rouh's own checkout.

    Said by `ROUH_CONTENT_PATHS` when it is said. Otherwise the workspace's
    folder, when the workspace still lives inside Rouh's checkout - which it
    did until 21 October 2026 - and nothing at all when it is a repository of
    its own, which is how it is now: every commit to the code is code.
    """
    said = _env("ROUH_CONTENT_PATHS")
    if said:
        return said
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = _workspace_root()
    if root:
        rel = os.path.relpath(os.path.realpath(root), os.path.realpath(here))
        if rel != "." and not rel.startswith(".."):
            return rel.replace(os.sep, "/").rstrip("/") + "/"
    return ""


def _said(name: str, default: str) -> str:
    """A setting where an empty value is nobody's intention, so it is the default.

    Most settings here mean something by being blank: no log directory of its
    own, no tmux socket of its own, no effort flag on the worker's command
    line. A model name and an effort level are not among them. There is no such
    thing as a request with no model, and `output_config: {"effort": ""}` is a
    400 on every turn - the voice would simply stop answering, with nothing on
    screen to say why, because a line in an environment file had been emptied
    rather than removed.
    """
    return _env(name, default) or default


#: The generation of a model id, by family: "claude-sonnet-5" is 5. Searched
#: rather than anchored, because a Bedrock or Vertex id puts the vendor in
#: front of the same name.
_GENERATION = re.compile(r"(?:sonnet|opus|fable|haiku)-(\d{1,2})(?!\d)")


def takes_effort(model: str) -> bool:
    """Whether this model is asked how deeply to think, and thinks adaptively.

    The 5 generation does both and only both: `output_config.effort` says how
    deeply, thinking is adaptive and is never configured by hand, and a
    temperature, a top_p or a top_k is refused outright.

    Haiku 4.5 sits in the same picker beside them (`templates/rouh/index.html`) and
    takes neither. An effort is a 400 there and so is adaptive thinking, which
    means the request has to be built for the model that was picked rather than
    for the one that answers most of the time. Asking for the picker's third
    option and getting silence is exactly the sort of thing nobody reports.

    Unknown names are treated as the older shape, which is the safe way round:
    the worst of a missing effort is a shallower answer, and the worst of an
    effort that is not taken is no answer at all.
    """
    name = (model or "").lower()
    if any(older in name for older in _EFFORT_4):
        return True
    found = _GENERATION.search(name)
    return bool(found) and int(found.group(1)) >= 5


#: The two of the 4 generation on the list (`MODEL_CHOICES`) that are asked
#: the same way as the 5: every level, adaptive thinking, no temperature.
#: Sonnet 4.6 is not among them: it has no "xhigh", so it is sent no level.
_EFFORT_4 = ("claude-opus-4-7", "claude-opus-4-8")


def thinking_for(model: str, display: str = "summarized") -> dict | None:
    """The thinking to ask this model for, or nothing to send.

    The 5 generation thinks whether or not it is asked to - Opus 5.5 and Fable
    cannot be told not to, and Opus 5 and Sonnet 5 think when nothing is said -
    and returns what it thought as an empty block unless asked for a summary.
    Asking for one changes what is returned and nothing else: the thinking is
    the same and is billed the same. It is asked for so that the log of
    requests (`rouh/llmlog.py`) has the reasoning in it, which is the
    reasoning Petar asked that log for, and which Anthropic's own guidance
    says a log needs `display: "summarized"` for. Nothing else reads it: it is
    never spoken and never written to a transcript.

    Nothing for an older model, which does not think unless it is told to and
    refuses to be told this way (`takes_effort`).
    """
    if not takes_effort(model):
        return None
    return {"type": "adaptive", "display": display or "summarized"}


#: Models that have been replaced, by the one that replaced them. A name on the
#: left is read as the name on the right wherever Rouh is told a model: from
#: the environment, from a fallback list, and from a page still showing the
#: list it was loaded with before a deploy.
#:
#: Opus 5 became Opus 5.5 on 24 September 2026, when Petar asked "change
#: everywhere that uses opus 5 to use opus 5.5". This table is what makes that
#: everywhere rather than everywhere in this repository: the server's own
#: environment file names `claude-opus-5` for the conversation (every start on
#: 23 September logged `model=claude-opus-5`, against a default of Sonnet 5),
#: and that file is not one a change here may touch. Opus 5.5 was checked on
#: Rouh's own account before this went in: the Ask AI drawer has asked for it
#: through the same API key since 23 September, and been answered.
REPLACED = {"claude-opus-5": "claude-opus-5-5"}


def current_model(name: str) -> str:
    """The model to ask for, given the name somebody wrote down."""
    name = (name or "").strip()
    return REPLACED.get(name, name)


#: How deeply a model may be asked to think, shallowest first: Anthropic's
#: `output_config.effort` and OpenAI's `reasoning.effort` both take every one
#: of these. The list the Settings page offers for the two defaults
#: (`rouh/modeldefaults.py`), and the only words either default may hold.
EFFORTS = ("low", "medium", "high", "xhigh", "max")

#: Each level as the Settings page names it.
EFFORT_NAMES = {"low": "Low", "medium": "Medium", "high": "High",
                "xhigh": "Extra high", "max": "Max"}


def effort_for(model: str, said: str = "") -> str:
    """How deeply to ask this model to think, or "" to send no level at all.

    `said` is the level that was chosen (`rouh/modeldefaults.py`), sent to any
    model that is asked; nothing to one that is not (`takes_effort`), where a
    level is a 400, and nothing when nothing was chosen, which leaves it to
    the API.
    """
    if not takes_effort(model):
        return ""
    return (said or "").strip()


#: OpenAI's GPT-6 Luna, the first of OpenAI's models on the list. Petar, 26
#: September 2026: "Give me the option to use Luna from OpenAI instead of the
#: listed three models of Anthropic." It answers Rouh's own spoken turn through
#: OpenAI's Responses API (`rouh/luna.py`), and only when `OPENAI_API_KEY` is in
#: the service's environment (`luna_ready`). The Cheaper tier's model since 18
#: October 2026 (`model_standard.json`).
LUNA = "gpt-6-luna"

#: The models there are to choose from, in the order a person reads them: the
#: two columns of a tier's chooser on the Models page (`rouh/modeldefaults.py`).
#: A model added here needs its level in the model standard too
#: (`model_standard.json`, `efforts`), which the standard's check insists on.
#:
#: Petar, 5 October 2026 (fr_74d5e6383c34): "add all the latest openai and
#: anthropic models most popular 5-10 of each company in the selection." So
#: eight of each, every one a model id the provider's API serves today:
#: Anthropic's from its models table, OpenAI's from developers.openai.com's
#: list of models and its prices page, both read that day. Claude Opus 5 is
#: not here because it is read as Opus 5.5 (`REPLACED`). A use that can only
#: ask one company is offered only that company's (`modeldefaults.USES`).
ANTHROPIC_CHOICES = (
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5", "Sonnet 5"),
    ("claude-haiku-4-5", "Haiku 4.5"),
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-fable-5", "Fable 5"),
    ("claude-opus-4-8", "Opus 4.8"),
    ("claude-opus-4-7", "Opus 4.7"),
    ("claude-sonnet-4-6", "Sonnet 4.6"),
)
OPENAI_CHOICES = (
    (LUNA, "Luna"),
    ("gpt-6-astra", "GPT-6 Astra"),
    ("gpt-6.1-sol", "GPT-6.1 Sol"),
    ("gpt-6-sol", "GPT-6 Sol"),
    ("gpt-5.6-terra", "GPT-5.6 Terra"),
    ("gpt-5.5", "GPT-5.5"),
    ("gpt-5.4", "GPT-5.4"),
    ("gpt-5.4-mini", "GPT-5.4 Mini"),
    # The two that give log probabilities, which Synapse's decision backend reads
    # (`modeldefaults.USES`, synapse_decision); on the list since 18 October 2026, so
    # that use is on the Models page like every other.
    ("gpt-4.1-mini", "GPT-4.1 Mini"),
    ("gpt-4.1-nano", "GPT-4.1 Nano"),
)
#: Google's Gemini models and xAI's Grok models, since 24 October 2026 (Petar: "Google
#: and xAI (Grok) as providers, alongside OpenAI and Anthropic"). Each is a model id its
#: provider's own pages listed that day, at the price they gave (`costs.PRICES`): Google's
#: Gemini API models and pricing pages (ai.google.dev/gemini-api/docs/models and /pricing,
#: last updated 22 October 2026) and xAI's models page (docs.x.ai/docs/models). Both are
#: asked through their OpenAI-compatible Chat Completions endpoints (`rouh/llm.py`,
#: `rouh/compat.py`), with a key the organisation types into Anatomy, Behaviour, Models
#: (`rouh/providerkeys.py`).
GOOGLE_CHOICES = (
    ("gemini-4-argon", "Gemini 4 Argon"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite"),
)
XAI_CHOICES = (
    ("grok-4.7", "Grok 4.7"),
    ("grok-4.6", "Grok 4.6"),
    ("grok-4.3", "Grok 4.3"),
)
MODEL_CHOICES = ANTHROPIC_CHOICES + OPENAI_CHOICES + GOOGLE_CHOICES + XAI_CHOICES
#: The only reasoning levels a model takes, where it takes fewer than its provider's others:
#: Grok 4.3 takes none and low (docs.x.ai, "Reasoning", read 24 October 2026). `llm.compat_effort`.
LEVELS_TAKEN = {"grok-4.3": ("none", "low")}

#: The four providers, in the order a use asks them when nothing else says
#: (`model_standard.json`): Anthropic, OpenAI, Google, xAI (Petar, 24 October 2026:
#: "Default order until there is data: Anthropic 1, OpenAI 2, Google 3, xAI 4").
ANTHROPIC, OPENAI, GOOGLE, XAI = "anthropic", "openai", "google", "xai"
PROVIDERS = (ANTHROPIC, OPENAI, GOOGLE, XAI)
PROVIDER_NAMES = {ANTHROPIC: "Anthropic", OPENAI: "OpenAI", GOOGLE: "Google", XAI: "xAI"}
#: Each provider's models, in the order the Models page lists them.
CHOICES_OF = {ANTHROPIC: ANTHROPIC_CHOICES, OPENAI: OPENAI_CHOICES, GOOGLE: GOOGLE_CHOICES,
              XAI: XAI_CHOICES}

#: The models OpenAI's Decisions API takes (`POST /v1/decisions`, `rouh/llm.py` `decide`).
#: Only GPT-6 Luna, by OpenAI's own guide and reference, read on 23 October 2026
#: (developers.openai.com/api/docs/guides/decisions): "Send requests to POST /v1/decisions
#: using gpt-6-luna, the only currently supported model." A use that asks the Decisions API
#: on any other model is said to be unable to on the Models page (`modeldefaults.Now.blocked`).
DECISIONS_MODELS = (LUNA,)


def is_decisions_model(model: str) -> bool:
    """Whether OpenAI's Decisions API takes this model."""
    return (model or "").strip() in DECISIONS_MODELS


def is_openai(model: str) -> bool:
    """Whether a model id is OpenAI's rather than Anthropic's.

    By the name alone, because that is all a setting or a page ever says:
    OpenAI's models are called gpt-something and o-something, Anthropic's
    claude-something.
    """
    name = (model or "").strip().lower()
    return name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))


def provider_of(model: str) -> str:
    """Whose a model is, by its id alone: gpt- and o- are OpenAI's, gemini- Google's,
    grok- xAI's, and everything else Anthropic's (claude-)."""
    name = (model or "").strip().lower()
    if is_openai(name):
        return OPENAI
    if name.startswith("gemini-"):
        return GOOGLE
    if name.startswith("grok-"):
        return XAI
    return ANTHROPIC


def luna_ready(cfg) -> bool:
    """Whether Luna can be asked at all: there is an OpenAI key to ask with."""
    return bool(getattr(cfg, "openai_api_key", ""))


_SPOKEN_MODEL = re.compile(r"^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$")
#: And OpenAI's: "gpt-6-luna" is "GPT-6 Luna".
_SPOKEN_GPT = re.compile(r"^gpt-(\d+(?:\.\d+)?)(?:-([a-z]+))?$")

#: Every model on the list, as the list names it: Luna is "Luna".
_NAMED = dict(MODEL_CHOICES)


def model_name(model: str) -> str:
    """A model as a person says it: "claude-opus-5-5" is "Opus 5.5".

    The same reading as `modelName` in app.js, which names the models in the
    box beside Rouh's own composer. Anything not shaped like a Claude or an
    OpenAI model id is given back as it is.
    """
    model = (model or "").strip()
    if model in _NAMED:
        return _NAMED[model]
    gpt = _SPOKEN_GPT.match(model)
    if gpt:
        return f"GPT-{gpt.group(1)}" + (f" {gpt.group(2).capitalize()}" if gpt.group(2) else "")
    found = _SPOKEN_MODEL.match(model)
    if not found:
        return model
    family, major, minor = found.groups()
    return f"{family.capitalize()} {major}" + (f".{minor}" if minor else "")


#: The tools every request carries whole, never deferred (`rouh/toolsearch.py`).
#:
#: Empty, on purpose, since 26 September 2026: Petar asked for nothing to be
#: loaded by default, so the difference in speed shows, and he will fill this
#: with the tools he actually uses. Every tool is still declared on every
#: request and found through the search, so leaving one out of here costs a
#: search the first time it is needed in a conversation, never the tool.
#: `ROUH_TOOLS_ALWAYS_LOADED` overrides this list on one machine.
#:
#: The first two, by voice on 6 October 2026: Synapse Master's find and query,
#: loaded at the start of every turn beside the search tool, so remembering
#: never waits on a search first. Automatic recall puts item ids into a turn
#: (`rouh/synapse/autorecall.py`), and these are what read them further. Where
#: a chat has no Master they are not declared, and so not loaded either.
TOOLS_ALWAYS_LOADED: tuple[str, ...] = ("synapse_find", "synapse_query")


def _num(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass
class Config:
    # --- Identity -----------------------------------------------------------
    host: str = field(default_factory=lambda: _env("ROUH_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_num("ROUH_PORT", 8021)))
    #: The address this installation is opened at, which every link Rouh
    #: writes starts with. An installation's own: blank until its installer
    #: sets it (SETUP.md), never another installation's address.
    public_url: str = field(default_factory=lambda: _env("ROUH_PUBLIC_URL"))
    #: Where this Rouh's birth service is (`rouh/birth.py`): rouh.land's own unless these say
    #: otherwise, which only a test world or a registry of its own does. The key is a file with
    #: the service's public key in PEM.
    birth_url: str = field(default_factory=lambda: _env("ROUH_BIRTH_URL"))
    birth_key_file: str = field(default_factory=lambda: _env("ROUH_BIRTH_KEY_FILE"))
    #: Every name Rouh answers to from outside, comma separated. The public
    #: URL above is the one name links are written with; these are all the
    #: names a person may open it under, side by side, each with its own
    #: sign-in (no cookie domain is set). Allowed hosts, CSRF origins, the
    #: socket's origin check and Google's way back all read this one list.
    #: Blank is the public URL's own name alone.
    public_hosts: str = field(default_factory=lambda: _env("ROUH_PUBLIC_HOSTS"))
    data_dir: str = field(default_factory=lambda: _env("ROUH_DATA_DIR", "/var/www/rouh/data"))
    #: Where this process writes files a person reads afterwards rather than
    #: data it works from. The audit trail of every Google write is the first
    #: of them: see rouh/google_audit.py. Defaults to `logs` beside the data,
    #: so one backup still covers both.
    log_dir: str = field(default_factory=lambda: _env("ROUH_LOG_DIR"))

    # --- The database -------------------------------------------------------
    # PostgreSQL, since 23 September 2026, through Django (`rouh/models/`).
    # Until then every store kept its own tables in one SQLite file in the data
    # directory; that file is read once, by `manage.py import_sqlite`, and is
    # never written again (`legacy_sqlite_path` below).
    #
    # On the server Rouh reaches its database over TCP on this machine as the
    # role `rouh`, with a password the deploy made once and keeps in a file
    # only root can read (`db_password_file`). The browser environment points
    # all of these at a throwaway cluster of its own (`rouh/testing/postgres.py`)
    # and the laptop at whatever it has.
    db_name: str = field(default_factory=lambda: _env("ROUH_DB_NAME", "rouh"))
    db_user: str = field(default_factory=lambda: _env("ROUH_DB_USER", "rouh"))
    #: An address, or the directory of a unix socket (anything starting "/").
    db_host: str = field(default_factory=lambda: _env("ROUH_DB_HOST", "127.0.0.1"))
    db_port: str = field(default_factory=lambda: _env("ROUH_DB_PORT", "5432"))
    #: Said outright, which is for a laptop. The server uses the file.
    db_password: str = field(default_factory=lambda: _env("ROUH_DB_PASSWORD"))
    #: JSON, {"password": "..."}, mode 0600, outside the repository.
    db_password_file: str = field(default_factory=lambda: _env(
        "ROUH_DB_PASSWORD_FILE", "/var/www/rouh/.secrets/postgres.json"))

    # --- Access -------------------------------------------------------------
    # There is no setting here, and that is the point. Until 16 September 2026
    # access was one shared word in this file's environment, and an empty one
    # meant "open to anyone", which is a switch nobody should be able to flick
    # by mistake on a machine that is on the internet. Who may sign in now lives
    # in the database, as Django accounts with hashed passwords, and the only
    # ways to make one are the admin command, the Django admin, or signing in
    # with Google from the organisation's own domain:
    #
    #     python manage.py account add <username> --generate

    # Credentials Rouh holds for somebody else - an organisation's Google
    # client secret, a person's refresh token - are encrypted in the database
    # with this key. It never appears in this repository. If it is not set,
    # encryption.py makes a key once and keeps it beside the database with mode
    # 0600, which keeps a single-machine install working; moving it into the
    # environment is better, because a key beside the file it protects is only
    # as safe as the permissions around it.
    # In the containers the core's start reads the key out of the keys volume into the
    # environment; ROUH_ENCRYPTION_KEY_FILE names that file, so a command run in the core
    # beside Rouh (`docker compose exec core python manage.py ...`) opens what Rouh sealed
    # rather than making a key of its own and finding every credential unreadable.
    encryption_key: str = field(default_factory=lambda: _env("ROUH_ENCRYPTION_KEY")
                                or _read_secret(_env("ROUH_ENCRYPTION_KEY_FILE")))

    # --- Google ---------------------------------------------------------------
    # There is deliberately no client id and no client secret here. Google will
    # not approve one public Rouh app for mail and Drive, so every
    # organisation registers its own OAuth client in its own Google Cloud
    # project and its administrator enters the pair in Settings. It is then
    # tenant-owned data in the database, encrypted, and there is no fallback to
    # anything server-wide. See rouh/google_store.py and GOOGLE.md.
    #
    # The four addresses below are Google's own. They are settings only so that
    # a test can stand in for Google without touching the network; nothing on
    # the server ever sets them.
    google_auth_url: str = field(
        default_factory=lambda: _env("ROUH_GOOGLE_AUTH_URL",
                                     "https://accounts.google.com/o/oauth2/v2/auth")
    )
    google_token_url: str = field(
        default_factory=lambda: _env("ROUH_GOOGLE_TOKEN_URL",
                                     "https://oauth2.googleapis.com/token")
    )
    google_revoke_url: str = field(
        default_factory=lambda: _env("ROUH_GOOGLE_REVOKE_URL",
                                     "https://oauth2.googleapis.com/revoke")
    )
    google_userinfo_url: str = field(
        default_factory=lambda: _env("ROUH_GOOGLE_USERINFO_URL",
                                     "https://openidconnect.googleapis.com/v1/userinfo")
    )
    #: Replaces the Gmail, Drive and Docs hosts all at once. Tests only.
    google_api_base: str = field(default_factory=lambda: _env("ROUH_GOOGLE_API_BASE"))
    #: How often one signed-in person may ask for a consent URL, finish one, or
    #: change their organisation's OAuth client. Generous for somebody pressing
    #: a button, useless to anything trying combinations. A setting only so a
    #: browser suite, which presses that button far faster than a person can,
    #: is not testing the rate limit every time it tests something else;
    #: nothing on the server sets it.
    google_rate_limit: int = field(
        default_factory=lambda: int(_num("ROUH_GOOGLE_RATE_LIMIT", 12)))

    # --- Apple Contacts ------------------------------------------------------
    # There is no Apple ID and no password here either. Each person enters
    # their own in Settings, and it is theirs, sealed in the database
    # (`rouh/apple_contacts.py`, APPLE.md).
    #
    #: iCloud's CardDAV address. A setting only so a test can stand in for
    #: iCloud (`rouh/testing/fake_carddav.py`); nothing on the server sets it.
    carddav_url: str = field(
        default_factory=lambda: _env("ROUH_CARDDAV_URL", "https://contacts.icloud.com/"))
    #: How often every connected address book is synced by itself, in minutes.
    #: Only what changed is fetched, so a sync with nothing new is two short
    #: requests.
    apple_sync_minutes: float = field(
        default_factory=lambda: _num("ROUH_APPLE_SYNC_MINUTES", 15))

    # --- The brain ----------------------------------------------------------
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    max_tokens: int = field(default_factory=lambda: int(_num("ROUH_MAX_TOKENS", 8000)))

    # --- The model standard (rouh/modelstandard.py, rouh/modeloutcomes.py) --
    # Petar, 18 October 2026: three tiers, a tier for every use of a model, and
    # how deeply a model thinks coming with the model, all from one standard he
    # publishes on rouh.land, which every Rouh fetches once a day. What an
    # organisation changed is in its database (`rouh/modeldefaults.py`); nothing
    # here picks a model.
    #
    #: Where the published standard is fetched from. Empty fetches nothing, and
    #: the standard built in (`rouh/model_standard.json`) is the standard.
    model_standard_url: str = field(default_factory=lambda: _env(
        "ROUH_MODEL_STANDARD_URL", _site("/models/standard.json")))
    #: Where the defaults every Rouh starts with are fetched from, once a day: the rules tagged "defaults" in
    #: the Rouh that publishes them (`rouh/ruledefaults.py`). Empty fetches nothing, and a Rouh keeps the rules
    #: it has, with the ones it starts with when it never fetched any (`rule_defaults_fallback.json`, the same set).
    rule_defaults_url: str = field(default_factory=lambda: _env(
        "ROUH_RULE_DEFAULTS_URL", _site("/rules/defaults.json")))
    #: Where the day's counts of how each model did are sent, when they are
    #: (`rouh/modeloutcomes.py`): counts and rates per use, model and level,
    #: nothing anybody said and nothing that says whose.
    model_outcomes_url: str = field(default_factory=lambda: _env(
        "ROUH_MODEL_OUTCOMES_URL", _site("/models/outcomes")))
    #: Whether they are really sent, for an organisation that shares them. Off, a
    #: dry run: the day's totals are made and kept as what would have been sent,
    #: and nothing leaves. On from the evening of 18 October 2026; off again since 24
    #: October 2026, when the totals were made private enough to leave (installs under
    #: twenty dropped on rouh.land, no address kept) and Petar said sending stays a dry
    #: run until he switches it on.
    model_outcomes_send: bool = field(
        default_factory=lambda: _flag("ROUH_MODEL_OUTCOMES_SEND", False))
    #: The share of a chat's plain answers offered as a blind comparison, within each
    #: organisation's daily limit a person and only with its opt-in on (`rouh/modelvotes.py`).
    compare_chance: float = field(default_factory=lambda: _num("ROUH_COMPARE_CHANCE", 0.25))
    #: How long a chat in Balanced waits for the router (OpenAI's Decisions API) before
    #: it answers on Smart instead (`rouh/modelrouter.py`), in seconds.
    router_seconds: float = field(default_factory=lambda: _num("ROUH_ROUTER_SECONDS", 8.0))

    # --- Luna, OpenAI's model (rouh/luna.py) -------------------------------
    #: The key Luna is asked with. Read from the service's own environment and
    #: from nowhere else, like ANTHROPIC_API_KEY above: on the server that is
    #: `/var/www/rouh/.env`, which only root reads and no deploy writes. Empty
    #: means Luna is offered in the box and cannot be picked, and nothing else
    #: anywhere changes.
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    #: Google's Gemini API key and xAI's, as this installation's own, from its environment.
    #: An organisation types its own into Anatomy, Behaviour, Models, which is used first and kept
    #: sealed (`rouh/providerkeys.py`). Empty: only what Settings holds.
    google_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    xai_api_key: str = field(default_factory=lambda: _env("XAI_API_KEY"))
    #: Where each is asked, when not at their own OpenAI-compatible endpoints
    #: (`llmlog.COMPAT_URLS`): only so a test can put a stand-in in front of them
    #: (`rouh/testing/fake_compat.py`). Empty is the provider's own.
    google_base_url: str = field(default_factory=lambda: _env("ROUH_GOOGLE_BASE_URL"))
    xai_base_url: str = field(default_factory=lambda: _env("ROUH_XAI_BASE_URL"))
    #: Whether Rouh hands the OpenAI key to the one program, for runs of Codex
    #: billed to the API (`one/billing.py`). On this server it does. In the
    #: containers (`deploy/container/`) it does not: the program runs in the
    #: workers' container, which never holds a key, and its Codex runs reach
    #: OpenAI through the key proxy, which adds the key on the way out.
    one_gets_keys: bool = field(default_factory=lambda: _flag("ROUH_ONE_GETS_KEYS", True))
    #: Voyage AI's key, for the vectors Synapse searches by meaning with
    #: (`rouh/synapse/ai.py`, spec D37), and where to ask: a key made in
    #: MongoDB Atlas answers only at its own address (`ai.mongodb.com`), a key
    #: made at voyageai.com only at Voyage's. Both from the service's own
    #: environment like every key here, never shown. OpenAI still answers
    #: everything else Synapse asks.
    voyage_api_key: str = field(default_factory=lambda: _env("VOYAGE_API_KEY"))
    voyage_endpoint: str = field(default_factory=lambda: _env("VOYAGE_ENDPOINT"))
    #: The most one Luna request may write. Larger than `max_tokens` on
    #: purpose: OpenAI counts the reasoning a model does before it answers as
    #: output, and a ceiling the reasoning can use up is an answer that stops
    #: before its first word ("incomplete: max_output_tokens"). OpenAI's own
    #: advice is to leave at least 25,000 for it.
    luna_max_tokens: int = field(
        default_factory=lambda: int(_num("ROUH_LUNA_MAX_TOKENS", 32000)))
    # --- Thinking between tool calls (rouh/brain.py) ----------------------
    #: Extended thinking, on across tool calls inside one turn. Off by
    #: default: it costs tokens and it costs the first spoken word, and a
    #: spoken turn is the most latency-sensitive thing this process does.
    #: Worth turning on for a Rouh that is asked hard multi-step questions
    #: rather than quick ones.
    #:
    #: There is deliberately no budget here. Thinking on these models is
    #: adaptive: the model decides how much to do and `effort` above is the
    #: dial. A fixed `budget_tokens` is refused outright by Opus 5 and the
    #: rest of its family.
    thinking: bool = field(default_factory=lambda: _flag("ROUH_THINKING", False))
    #: What comes back in the thinking blocks: "summarized" returns a readable
    #: summary, and "omitted", the API's own default on these models, returns
    #: them empty. Either way the thinking happens, is billed, and is never
    #: spoken and never written to the transcript. Summarized since 26
    #: September 2026, so that the log of requests has the reasoning in it
    #: (`thinking_for`, `rouh/llmlog.py`).
    thinking_display: str = field(
        default_factory=lambda: _env("ROUH_THINKING_DISPLAY", "summarized"))

    # --- Which tools each request carries (rouh/toolsearch.py) -------------
    #: How the model finds a tool it has not loaded yet. Every tool is
    #: declared on every request and every one is deferred, so a turn starts
    #: with a search tool and a catalogue of one line per tool, and loads the
    #: definitions it needs: "regex" is Anthropic's own search by pattern, and
    #: the default; "bm25" is Anthropic's search by words; "client" is the
    #: search `toolsearch.find` runs in this process, the same for every
    #: provider; "off" sends every tool whole on every request, as it was until
    #: 26 September 2026.
    tool_search: str = field(default_factory=lambda: _env("ROUH_TOOL_SEARCH", "regex"))
    #: Tools sent whole on every request, never deferred, by name. Empty by
    #: default: see `TOOLS_ALWAYS_LOADED` above for why, and put names there
    #: to change it for every machine, or in `ROUH_TOOLS_ALWAYS_LOADED`,
    #: comma-separated, to change it for one.
    tools_always_loaded: tuple = field(default_factory=lambda: tuple(
        n for n in (x.strip() for x in _env("ROUH_TOOLS_ALWAYS_LOADED").split(",")) if n)
        or TOOLS_ALWAYS_LOADED)

    # --- General's window (rouh/chatkinds.py, rouh/context_editing.py) -----
    # Everything in this section is General's, and General's only. General runs
    # to thousands of messages going back months and cannot be sent whole, so
    # it is sent a window of its newest messages with the old tool results in
    # it trimmed. Every other chat is sent whole, every message and every tool
    # result as it came back: nothing here reaches one, and there is no setting
    # that would cut one.
    #
    #: How many of General's newest messages are sent with each turn.
    history_turns: int = field(default_factory=lambda: int(_num("ROUH_HISTORY_TURNS", 40)))
    #: Turning this off sends General's window with every tool result whole.
    context_editing: bool = field(
        default_factory=lambda: _flag("ROUH_CONTEXT_EDITING", True))
    #: How many messages at the end of the window keep their tool results
    #: whole. The answer being written right now depends on them, so this is
    #: the one number that must never be tuned to zero.
    context_keep_messages: int = field(
        default_factory=lambda: int(_num("ROUH_CONTEXT_KEEP", 6)))
    #: The size of window worth acting on, in tokens, counted from the API's
    #: own usage numbers. Past it the recent results are trimmed too, a few at
    #: a time. Well under the model's real limit on purpose: the point is to
    #: keep the conversation cheap, not to rescue it at the edge.
    context_budget_tokens: int = field(
        default_factory=lambda: int(_num("ROUH_CONTEXT_BUDGET", 120_000)))
    #: The smallest tool result worth trimming, in characters.
    context_min_body: int = field(
        default_factory=lambda: int(_num("ROUH_CONTEXT_MIN_BODY", 400)))

    # --- Subagents (rouh/subagent.py) -------------------------------------
    # A lookup with a window of its own, run inside a spoken turn, whose window
    # is thrown away and whose answer is all that comes back.
    subagents: bool = field(default_factory=lambda: _flag("ROUH_SUBAGENTS", True))
    #: The looking is done by the default model, at the default level
    #: (`rouh/modeldefaults.py`), whichever chat it is looking for.
    #: How many rounds of tool calls before it has to answer with what it has.
    #: Somebody is waiting with their mouth open, so this is small on purpose.
    subagent_rounds: int = field(
        default_factory=lambda: int(_num("ROUH_SUBAGENT_ROUNDS", 8)))
    subagent_max_tokens: int = field(
        default_factory=lambda: int(_num("ROUH_SUBAGENT_MAX_TOKENS", 2000)))

    # --- Tools that have to be asked about (rouh/permissions.py) ----------
    #: Named tools stop before they run and the person is asked. Empty by
    #: default, and empty means nothing anywhere behaves differently: this is
    #: the whole of the compatibility promise, so it is not a flag to turn the
    #: gate on, it is the list of what the gate is for.
    confirm_tools: str = field(default_factory=lambda: _env("ROUH_CONFIRM_TOOLS"))
    #: How long a question waits for an answer before it is refused. Nobody may
    #: be at the screen, and a spoken turn that hangs is worse than one that
    #: says it is waiting on somebody.
    confirm_timeout: float = field(
        default_factory=lambda: _num("ROUH_CONFIRM_TIMEOUT", 120))

    # --- The box run_command runs in (rouh/sandbox.py) --------------------
    #: "auto" uses bubblewrap, or the kernel's Landlock where bubblewrap cannot
    #: run (a container), and says so when neither holds; "required" refuses to
    #: run anything without one (the worker of every Rouh instance); "off" leaves the
    #: read-only command rules as the whole of the check, which is what it was
    #: before the sandbox existed.
    sandbox: str = field(default_factory=lambda: _env("ROUH_SANDBOX", "auto"))
    #: Whether a sandboxed command may reach the network. Off, which is the
    #: point of it. `curl` is the one allowed command that needs it, so this is
    #: the switch for anybody who uses it and would rather keep it working.
    sandbox_network: bool = field(
        default_factory=lambda: _flag("ROUH_SANDBOX_NETWORK", False))

    # --- MCP servers (rouh/mcp.py) ----------------------------------------
    #: External Model Context Protocol servers, whose tools join the tool list
    #: namespaced. Either the JSON itself, or a path to a file holding it, in
    #: the same shape every other client in this world uses. Empty by default.
    mcp_servers: str = field(default_factory=lambda: _env("ROUH_MCP_SERVERS"))
    mcp_config: str = field(default_factory=lambda: _env("ROUH_MCP_CONFIG"))
    #: Whether the model is asked at all. On: a task nobody filed is read by
    #: the filing model (`modeldefaults.USES`, filing) and lands under the project it belongs in. Off skips the
    #: model, which is what a machine with no model configured gets anyway -
    #: and the task still lands, in `filing_fallback` below.
    filing_auto: bool = field(default_factory=lambda: _flag("ROUH_FILING_AUTO", True))
    #: Where a task goes when nothing else decides: the model answered `none`,
    #: or was not asked, or could not be reached. The folder name of one of the
    #: person's own projects, matched against its folder and then against its
    #: name, so renaming Misc to Miscellaneous does not break it.
    #:
    #: There is a fallback at all because there is no longer a **Not sorted**
    #: heading for a task to wait under. Petar, 23 September 2026: "We should
    #: not have a section called Not sorted. The AI should be sorting whether a
    #: task is in one project or another." What he did not say is where a task
    #: the model cannot place should go, so it goes to Miscellaneous, which is
    #: what that project is for, and one drag puts it right.
    filing_fallback: str = field(
        default_factory=lambda: _env("ROUH_FILING_FALLBACK", "misc"))

    # --- The Gene therapy board, carried the rest of the way (rouh/triage.py) ---
    # A feedback is read the moment it lands, a feature request is written from
    # it, and a run is started to build it, with nobody pressing anything.
    # Petar, 22 September 2026: "the feedbacks should be automatically
    # converted to feature requests and should automatically be put in RUNS to
    # be completed." The two settings are named for Gene therapy, which was
    # called Feedback until 12 October 2026; the environment keeps the old
    # names, so a machine set up before then is read the same.
    gene_therapy_auto: bool = field(default_factory=lambda: _flag("ROUH_FEEDBACK_AUTO", True))
    #: A feedback is read, and its brief written, by the default model at the
    #: default level (`rouh/modeldefaults.py`): it is writing what a coding run
    #: works from, which is the one thing here worth spending tokens on.
    #: And the beat behind the immediate path, in minutes: what picks up a
    #: feedback written while this process was restarting, and tries again for
    #: a run that nothing on the machine would take.
    gene_therapy_sweep_minutes: float = field(
        default_factory=lambda: _num("ROUH_FEEDBACK_SWEEP_MINUTES", 5))

    # --- Speech -------------------------------------------------------------
    elevenlabs_api_key: str = field(default_factory=lambda: _env("ELEVENLABS_API_KEY"))
    # George: British, male, and confirmed to read Bulgarian correctly as well as
    # English. Overridable, but a default means the thing talks out of the box.
    voice_id: str = field(
        default_factory=lambda: _env("ROUH_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    )
    tts_model: str = field(default_factory=lambda: _env("ROUH_TTS_MODEL", "eleven_flash_v2_5"))
    # Batch is the fallback; realtime is the normal path.
    stt_model: str = field(default_factory=lambda: _env("ROUH_STT_MODEL", "scribe_v1"))
    stt_realtime_model: str = field(
        default_factory=lambda: _env("ROUH_STT_REALTIME_MODEL", "scribe_v2_realtime")
    )
    use_realtime_stt: bool = field(default_factory=lambda: _flag("ROUH_REALTIME_STT", True))
    # Which languages this assistant is actually spoken to. Naming them stops
    # one language being read as a neighbour of it (Bulgarian as Russian was
    # what open detection did on a short clip). An installation names its
    # owner's own; blank falls back to detecting anything.
    stt_language: str = field(default_factory=lambda: _env("ROUH_STT_LANGUAGE", "eng"))
    stt_secondary_languages: str = field(
        default_factory=lambda: _env("ROUH_STT_SECONDARY")
    )
    # Words this assistant hears constantly and a general transcriber has never
    # met. Without them a domain came back misspelt, and a worker then went
    # looking for a domain that does not exist. Up to 50 terms, 20 characters
    # each, comma separated in the environment. The default is the product's
    # own words; an installation adds its owner's (their name, their company,
    # their domains, their city) in its own environment (SETUP.md).
    stt_keyterms: str = field(
        default_factory=lambda: _env(
            "ROUH_STT_KEYTERMS",
            "Rouh,nginx,subdomain,Cloudflare,Anthropic,ElevenLabs,Claude Code,worktree,tmux,"
            "systemd,DNS,SSL,repo,deploy,staging,Postgres,SQLite,API key,webhook",
        )
    )
    def public_host_list(self) -> list[str]:
        """The names in `public_hosts`, and the public URL's own, lower case."""
        from urllib.parse import urlsplit

        names = [h.strip().lower() for h in self.public_hosts.split(",")]
        names.append((urlsplit(self.public_url).hostname or "").lower())
        return sorted({h for h in names if h})

    def keyterm_list(self) -> list[str]:
        """The vocabulary hints as a list.

        The setting is one comma-separated string because it comes from an
        environment variable. Handing that string to something expecting a list
        gives 235 one-character hints, which is not an error anywhere - it is
        just quietly useless.
        """
        return [t.strip()[:20] for t in (self.stt_keyterms or "").split(",") if t.strip()]

    # 16k up for speech-to-text, 24k down because that is what the voice returns.
    mic_sample_rate: int = 16000
    tts_sample_rate: int = field(default_factory=lambda: int(_num("ROUH_TTS_RATE", 24000)))
    voice_replies: bool = field(default_factory=lambda: _flag("ROUH_VOICE_REPLIES", True))

    # --- Telegram (rouh/telegram.py, rouh/telegram_chat.py) ---------------
    # The one way to reach the person when he is not at the screen, and since
    # 26 September 2026 a way for him to write to Rouh from his phone. There is
    # no token here, the same as everywhere else in this file: the bot's key
    # and the chat it talks to are in their own file on the server, outside the
    # repository, owned by the user this service runs as and readable by
    # nobody else. It is read each time it is needed and never held in memory.
    #
    # This is Rouh's own bot, @rouh_telegram_bot, and not the "Clauder" bot
    # the laptop's tg-ask and the one program's phone share. That one keeps its
    # own file under /etc/one, named by ONE_TELEGRAM, and nothing here goes
    # near it. Only one process may read a bot's messages, so pointing this at
    # the real file anywhere but the service - a test, a copy on the laptop -
    # would take the owner's messages away from the server.
    telegram_file: str = field(
        default_factory=lambda: _env("ROUH_TELEGRAM_FILE",
                                     "/var/www/rouh/.secrets/rouh_telegram.json")
    )
    #: Telegram's own address. A setting only so a test can stand in for it;
    #: nothing on the server sets it.
    telegram_api_base: str = field(
        default_factory=lambda: _env("ROUH_TELEGRAM_API_BASE", "https://api.telegram.org")
    )
    #: Whether a background job that simply finished - a page, files, an
    #: answer, a live change - sends Petar a "Done" message on Telegram
    #: (`rouh/job_phone.py`). Off since 6 October 2026, when he asked to stop
    #: being told on Telegram that a run was done; a job that needs him is
    #: sent whatever this says.
    phone_done_jobs: bool = field(default_factory=lambda: _flag("ROUH_PHONE_DONE_JOBS", False))

    # --- Rouh's own mail (rouh/mailer.py) -------------------------------------
    # The invitations and notes a person gets when a page is shared with them,
    # sent through Brevo from this install's own address. Like Telegram's, the
    # key is not here: it is in its own file on the server, outside the
    # repository, owned by the user this service runs as and readable by nobody
    # else, and it is read when a letter goes out.
    brevo_file: str = field(
        default_factory=lambda: _env("ROUH_BREVO_FILE", "/var/www/rouh/.secrets/brevo.json")
    )
    #: Brevo's own address. A setting only so a world can stand in for it
    #: (`rouh/testing/fake_brevo.py`); nothing on the server sets it.
    brevo_url: str = field(
        default_factory=lambda: _env("ROUH_BREVO_URL", "https://api.brevo.com")
    )
    #: Who the letters are from: an address of the installation's own domain,
    #: set by its installer (SETUP.md). Blank sends nothing (`mailer.ready`).
    mail_from: str = field(default_factory=lambda: _env("ROUH_MAIL_FROM"))
    mail_from_name: str = field(default_factory=lambda: _env("ROUH_MAIL_FROM_NAME", "Rouh"))

    #: Rouh's own mailbox on this installation, and any other name of it, comma
    #: separated, the first the one it writes from: the Google account Rouh
    #: itself is connected as, never the owner's. Blank means this installation
    #: gave Rouh no mailbox of its own (`inbox.own`). The owner's own addresses
    #: are never here: they are their account's and their card's (`my_card`).
    own_mailboxes: str = field(default_factory=lambda: _env("ROUH_OWN_MAILBOXES"))

    #: The time zone a person is on until one of their pages or their shared
    #: location says otherwise (`rouh/clock.py`). UTC unless the installation
    #: says where its people are.
    default_zone: str = field(default_factory=lambda: _env("ROUH_DEFAULT_ZONE", "UTC"))

    # --- New mail (rouh/mail_alerts.py) -------------------------------------
    # There was a setting here for the small model that judged whether each
    # new email was worth a note. Petar had it removed on 25 September 2026
    # (fr_b657bd8f6100): Rouh itself handles every message now, with the
    # model it talks with.
    #: How long Rouh is given to handle one new email before the plain note
    #: goes to the phone instead. It carries on afterwards; only the note
    #: stops waiting for it.
    mail_turn_minutes: float = field(
        default_factory=lambda: _num("ROUH_MAIL_TURN_MINUTES", 8))
    #: How often the watches are checked for renewal, and the inboxes looked
    #: at in case a note from Google never arrived. Gmail asks for a watch to
    #: be made again daily; this only decides how soon after it is due.
    mail_alerts_minutes: float = field(
        default_factory=lambda: _num("ROUH_MAIL_ALERTS_MINUTES", 60))

    # --- Tools --------------------------------------------------------------
    enable_web_search: bool = field(default_factory=lambda: _flag("ROUH_WEB_SEARCH", True))
    enable_web_fetch: bool = field(default_factory=lambda: _flag("ROUH_WEB_FETCH", True))
    # Off on purpose. Web search and web fetch already run code on Anthropic's
    # side to sift a page before it reaches the answer, and a second execution
    # sandbox declared beside them is what made every search fail: the model
    # called web_search from inside that sandbox, which has no network. See the
    # comment beside the tool definitions in tools.py.
    enable_code_exec: bool = field(default_factory=lambda: _flag("ROUH_CODE_EXEC", False))
    enable_delegate: bool = field(default_factory=lambda: _flag("ROUH_DELEGATE", True))

    # --- YouTube ------------------------------------------------------------
    # Two tools that read, and nothing else: what was said in a video, and
    # which videos exist. On by default for the same reason web search is -
    # they only read - and off in one line for a machine that should not reach
    # YouTube at all.
    enable_youtube: bool = field(default_factory=lambda: _flag("ROUH_YOUTUBE", True))
    # The Data API v3 key, for search. It is the one secret here read straight
    # out of the environment under Google's own name rather than Rouh's,
    # because that is what the person will be handed when they make it and
    # what every piece of documentation about it calls it. It goes in
    # /var/www/rouh/.env beside the others and systemd puts it in the
    # process. Without it the search tool says so plainly, and falls back to
    # scraping the results page, which it then says as well.
    youtube_api_key: str = field(default_factory=lambda: _env("YOUTUBE_API_KEY"))
    # Whether the transcript tool may start a real headless Chromium when a
    # plain HTTP fetch is turned away by YouTube's bot check. It is slower and
    # it is a browser on a server, so there is a switch; it is on because
    # without it about half the videos asked for come back with nothing.
    youtube_browser: bool = field(
        default_factory=lambda: _flag("ROUH_YOUTUBE_BROWSER", True))
    # Where Playwright's browser builds are, when they are not in the running
    # user's own ~/.cache/ms-playwright. Blank means Playwright's default,
    # which is right on a machine where the browser was installed by the same
    # user the service runs as.
    playwright_browsers: str = field(
        default_factory=lambda: _env("PLAYWRIGHT_BROWSERS_PATH"))

    # --- LinkedIn research (`rouh/linkedin.py`) -------------------------------
    # Find a person on LinkedIn, let them be picked, then harvest the profile,
    # through HarvestAPI's scrapers on Apify. The token is Apify's own name for
    # it, read straight out of the environment like YOUTUBE_API_KEY: it was
    # the HR project's, copied into /var/www/rouh/.env on 26 September 2026.
    # Without it the two tools are not offered at all.
    enable_linkedin: bool = field(default_factory=lambda: _flag("ROUH_LINKEDIN", True))
    apify_api_token: str = field(default_factory=lambda: _env("APIFY_API_TOKEN"))
    # Where Apify is. A test world points this at its stand-in
    # (`rouh/testing/fake_apify.py`), so nothing it does reaches LinkedIn.
    apify_url: str = field(
        default_factory=lambda: _env("ROUH_APIFY_URL", "https://api.apify.com"))

    # --- The Live browser (`rouh/browsing.py`) ------------------------------
    # A real browser Rouh drives for errands, which the person watches and can
    # take over. On by default: it only ever reaches the public internet, it
    # never runs as root, and nothing it does is out of the person's sight.
    enable_browser: bool = field(default_factory=lambda: _flag("ROUH_BROWSER", True))
    # Who the browser runs as when Rouh is root. Never root: a browser that
    # cannot be started as this user is not started.
    browser_user: str = field(
        default_factory=lambda: _env("ROUH_BROWSER_USER", "nobody"))
    # Where the browser's build is linked to when its own user cannot reach
    # the one Playwright installed (in /root, on a server where Rouh is root).
    browser_builds: str = field(
        default_factory=lambda: _env("ROUH_BROWSER_BUILDS", "/var/lib/rouh-browser"))
    # host:port pairs the browser may reach although they are not on the
    # public internet. Empty on a real machine; a test world names its own
    # stand-in website here, which is on 127.0.0.1 like everything in it.
    browser_allow: str = field(default_factory=lambda: _env("ROUH_BROWSER_ALLOW"))
    # Where a browser of its own is, when Rouh does not start one beside itself: in the
    # containers the core holds the keys and runs no browser, so every browser it uses (the
    # Live browser, a page read once, a PDF, a transcript) is a Playwright connection to the
    # stack's browser container (deploy/stack/compose.yml), ws://browser:9230/browser. Its
    # way out is the key proxy, which refuses private addresses, so the gatekeeper and the
    # jail above are not used then. Blank: a browser is started here, as on the server.
    browser_remote: str = field(default_factory=lambda: _env("ROUH_BROWSER_REMOTE"))
    # Rouh's own shell, used inside a spoken turn to answer "how much disk is
    # left" without starting a worker. It is read-only on purpose, and that is a
    # routing decision rather than a limit on what Rouh can do: a delegated
    # worker already runs anything as root. Reads happen inline because they are
    # instant and harmless; anything that writes goes through a worker, where it
    # gets a worktree, a log and a screen someone can read.
    enable_shell: bool = field(default_factory=lambda: _flag("ROUH_SHELL", True) or _env("ROUH_SHELL") == "worker")
    #: In the containers the core holds every key, so the shell's commands run in the worker,
    #: which holds none, through the one program (`one/shell.py`): ROUH_SHELL=worker.
    shell_in_worker: bool = field(default_factory=lambda: _env("ROUH_SHELL") == "worker")

    # --- Delegation ---------------------------------------------------------
    crew_workspace: str = field(
        default_factory=lambda: _env("ROUH_CREW_WORKSPACE", "/var/www/rouh/crew")
    )
    crew_session: str = field(default_factory=lambda: _env("ROUH_CREW_SESSION", "jarvis"))
    # Which tmux server the jobs live on. Blank means tmux's default socket,
    # which is what a person wants on a real machine: they can `tmux attach -t
    # jarvis` without knowing anything. A test that starts a whole Rouh sets
    # this, so its jobs cannot land on - or be killed with - the server the
    # deployment is using. `TMUX_TMPDIR` alone is not enough for that: tmux
    # reads `TMUX` first, and `TMUX` is set in every pane, including the pane a
    # test suite is being run in.
    crew_tmux_socket: str = field(default_factory=lambda: _env("ROUH_CREW_TMUX_SOCKET"))
    # Workers run as this user, not as the app.
    #
    # Two reasons, and the second is the one that decided it. Claude Code
    # refuses --dangerously-skip-permissions when it is running as root, so as
    # root every job stops on a prompt nobody will ever answer. And a worker is
    # a program writing files and running commands on a box that also serves
    # other sites and the databases; it has no business being
    # root. Blank runs workers as whoever runs the app.
    #
    # `rouh`, which was `jarvis` until the machine's user was renamed on
    # 22 September 2026. A setting that still says `jarvis` is read as `rouh`
    # wherever there is no `jarvis` any more (`_machine_user`).
    crew_user: str = field(
        default_factory=lambda: _machine_user(_env("ROUH_CREW_USER", "rouh")))
    # The group every chat attachment belongs to, and the one thing on this
    # machine that group opens. Its members are the users anything handed a
    # person's file runs as: `rouh`, which runs the crew's workers, and
    # `assistant`, which runs the one program's runs. Both are told a picture
    # by its path, and until 1 October 2026 only the first could open one:
    # the tree was group `rouh`, and putting `assistant` in that group would
    # have opened the crew's worktrees and Rouh's own home to it as well.
    # `python manage.py attachments_access` makes the group and puts the tree
    # in it. A machine without the group falls back to the crew user's own
    # group, which is how it was before (`attachments._gid_of`).
    attachments_group: str = field(
        default_factory=lambda: _env("ROUH_ATTACHMENTS_GROUP", "rouh-attachments"))
    # One home for every file (`rouh/filestore.py`): the folder every file Rouh is handed is kept
    # in, which Rouh, its jobs, the one program's runs and helpers all see read and write at the
    # same path. Blank means: in the containers, `files` in the volume Rouh and the worker already
    # share (/run/one/files); anywhere else, `files` in the data directory.
    files_dir: str = field(default_factory=lambda: _env("ROUH_FILES_DIR", ""))
    # The size above which a file is never committed to git and is kept on disk with a copy in
    # R2 instead, in megabytes (Petar: "about 10 MB, kept in config").
    # How many days a file put in the bin is kept before the bin is emptied of it.
    files_bin_days: float = field(
        default_factory=lambda: float(_env("ROUH_FILES_BIN_DAYS", "30") or 30))
    files_git_max_mb: float = field(
        default_factory=lambda: float(_env("ROUH_FILES_GIT_MAX_MB", "10") or 10))
    crew_home: str = field(
        default_factory=lambda: _env("ROUH_CREW_HOME", "/var/www/rouh/home")
    )
    allow_yolo: bool = field(default_factory=lambda: _flag("ROUH_ALLOW_YOLO", True))
    # Where Rouh's own code lives on this machine, as a git checkout. Being a
    # checkout rather than a copy is what lets it change and redeploy itself.
    app_dir: str = field(default_factory=lambda: _env("ROUH_APP_DIR", "/var/www/rouh/app"))
    # Which checkout of this repository the top bar compares the running one
    # program against. Blank means the one program's own, `one_app_dir`
    # (/srv/one/app), which is the right answer on every real machine: it is the
    # clone that program's service is started from and the clone its deploy
    # fetches into, so both halves of that chip come from one repository. This
    # points it somewhere else, for a machine that keeps the program's code
    # somewhere unusual.
    one_repo: str = field(default_factory=lambda: _env("ROUH_ONE_REPO"))
    # The one program's own checkout, the one its service is started from.
    # Three things read it: the commit its chip says is waiting, the commit shown
    # for the running program when the program is too old to report its own, and
    # the deploy that chip offers, which is this checkout being fast-forwarded
    # onto main and the service restarted (`one_deploy.py`).
    one_app_dir: str = field(default_factory=lambda: _env("ROUH_ONE_APP_DIR", "/srv/one/app"))
    # What in this repository is content rather than code, space separated:
    # the person's tasks, notes and pages under `workspace/`, which neither
    # service imports or runs. The same setting `land.sh` and `update-all.sh`
    # read to move a checkout across such a commit without restarting anything,
    # and the reason the two version marks do not call a service behind when
    # only content is newer than what it is running (`versions.py`).
    content_paths: str = field(default_factory=_content_paths)
    # The script the button under that chip runs: the one program on its own,
    # and nothing else. Blank means the copy in Rouh's own checkout,
    # `one/deploy/update.sh`, which is the right one: the program's checkout is
    # the thing being moved, so its copy of the script could change under the
    # script while it runs.
    one_deploy_script: str = field(default_factory=lambda: _env("ROUH_ONE_DEPLOY_SCRIPT"))
    # The script that puts Rouh itself on the newest code and restarts it,
    # which is the second half of a deploy. Blank means `deploy/rouh.sh` in
    # Rouh's own checkout.
    update_script: str = field(default_factory=lambda: _env("ROUH_UPDATE_SCRIPT"))
    # **What a deploy runs**: `update-all.sh`, which puts the one program and
    # Rouh on the same commit, in that order, out of the two scripts above.
    # Both services come out of this one repository and used to be updated by
    # two paths that never called each other, so every automatic deploy moved
    # Rouh and left the one program where it was. Blank means the copy in
    # Rouh's own checkout, which is the right one everywhere but a test,
    # where it has to be a stand-in: a browser test of the deploy that follows
    # a landed change must really start a script and must not really restart
    # the server it is driving.
    deploy_script: str = field(default_factory=lambda: _env("ROUH_DEPLOY_SCRIPT"))
    # Where the landing lock and the conflict records live (`land.sh`,
    # `rouh/conflicts.py`). One directory, shared by both users that land
    # work: the `jarvis` user, which runs Rouh's own crew, and `assistant`,
    # which runs every run of the one program. It is made sticky and
    # world-writable, the way /tmp is, because neither user is in the other's
    # group and a lock only one of them can open is not a lock.
    land_dir: str = field(default_factory=lambda: _env("ROUH_LAND_DIR", "/srv/rouh-land"))
    # The script that is the only thing allowed to push to main. Blank means
    # `land.sh` beside Rouh's own checkout, which is the right one everywhere:
    # both services come out of this one repository, so the program's landing
    # and the crew's landing climb the same ladder.
    land_script: str = field(default_factory=lambda: _env("ROUH_LAND_SCRIPT"))
    # Whether what Rouh makes in the workspace - a task, a step, a move - is
    # landed on main by Rouh itself (`rouh/saving.py`). Off unless it is said,
    # and it is said only in the server's own settings: every test world, the
    # laptop and every job's checkout has the real repository as its remote, so
    # finding one is no sign of being the server.
    save_workspace: bool = field(default_factory=lambda: _flag("ROUH_SAVE_WORKSPACE", False))
    # Held (task 161): a copy of a Rouh that must not act in anyone's name - the Creator Rouh's
    # rehearsal beside the real one, and the new one on switch day until the old one is stopped
    # and checked. Its page, its turns and its protected core work; nothing reaches out by itself:
    # no reminders or night jobs, no Telegram, mail, Slack, phone address, morning brief, meeting
    # work, crew or weekly copy (`runtime.startup`). Off unless the settings file says so.
    hold: bool = field(default_factory=lambda: _flag("ROUH_HOLD", False))
    # Rouh's own checkout of main, that it lands those saves from. Blank means
    # `workspace-saves` in the data directory.
    save_dir: str = field(default_factory=lambda: _env("ROUH_SAVE_DIR"))
    enable_self_update: bool = field(default_factory=lambda: _flag("ROUH_SELF_UPDATE", True))
    # How a worker calls home when it stops. "http" is neater - Claude Code posts
    # the JSON itself, with no shell and no quoting - but it only exists in newer
    # builds. 2.1.2, which is what the server runs, rejects the whole settings
    # file as invalid and then BLOCKS on a prompt asking whether to continue
    # without it. "command" is a curl line and works on every version.
    crew_hook_transport: str = field(
        default_factory=lambda: _env("ROUH_CREW_HOOK_TRANSPORT", "command")
    )

    # --- The person's workspace ----------------------------------------------
    # Where every task, note and built page lives: a repository of its own,
    # named by `ROUH_WORKSPACE` (`_workspace_root` above is the whole of how it
    # is found). Blank turns assistant jobs and read_workspace off.
    assistant_repo: str = field(default_factory=_workspace_root)
    # The checkout of the workspace's repository that runs' own checkouts are
    # made from (the one program's `assistant` space), for a run in a checkout
    # of Rouh's code that has to write into a task (`workspace_repo.code_run_note`).
    workspace_space: str = field(
        default_factory=lambda: _env("ROUH_WORKSPACE_SPACE", "/srv/spaces/workspace"))
    #: Where the one program makes each run's own checkout (its `ONE_RUNS_DIR`), one of the
    #: places a job's `rouh objecttree` may name as its workspace (`rouh/web/objecttreeapi.py`).
    one_runs: str = field(default_factory=lambda: _env("ROUH_ONE_RUNS", "/srv/one-runs"))
    assistant_user: str = field(
        default_factory=lambda: _env("ROUH_ASSISTANT_USER", "assistant")
    )
    assistant_home: str = field(
        default_factory=lambda: _env("ROUH_ASSISTANT_HOME", "/home/assistant")
    )
    assistant_jobs: str = field(
        default_factory=lambda: _env("ROUH_ASSISTANT_JOBS", "/srv/assistant-jobs")
    )
    # Which model an assistant job and the Ask AI drawer are, and how deeply
    # they think, is the default pair (`rouh/modeldefaults.py`), which a run of
    # the one program is told too: what answers about a page and what writes
    # one are the same model, the same as they were when this was a setting of
    # its own.
    # A second address a finished page can be opened at, put on the card under
    # the page itself. It used to be the workspace's own Ask AI proxy on
    # 127.0.0.1:1111, which stage three stopped and disabled on 21 September
    # 2026; a card carrying a link to a service nobody is running is worse than
    # a card with no second link, and the page is on the card already. Blank
    # unless a machine really has somewhere else to send a reader.
    assistant_review_url: str = field(
        default_factory=lambda: _env("ROUH_ASSISTANT_REVIEW_URL")
    )

    # --- The object model ----------------------------------------------------
    # The five objects in `rouh/objects.py` - project, task, chat, run,
    # artifact - with their two children and the one link table that joins
    # them.
    #
    # On since step two, which made every kind of running work one type: a
    # background worker, a run of the one program and a sub-agent inside either
    # are all rows of `run`, and the task list, `check_tasks`, `one_runs`,
    # `what_is_running` and the orb are all answered from that one register
    # (`rouh/runs.py`).
    #
    # Step four made every output one type: a card on the screen, a numbered
    # step in the workspace and a built page are all `artifact` rows with their
    # versions, each owned by the task or the thread it was made in or by
    # nothing at all (`rouh/artifacts.py`). The screen history that was in
    # `screen_cards` was migrated into those rows, keeping every number.
    #
    # Step five turned the last of them on: who owns what is
    # `rouh/owning.py`, and starting anything at all is `rouh/starting.py`.
    #
    # **There is no second implementation behind this flag any more.** It used
    # to name a fork in the road - the register on one side, the two lists the
    # task list was stitched together from on the other - and step five deleted
    # the second road, because two ways of answering "what is running" is the
    # exact thing this model exists to be rid of. Off now means these tables
    # are not read or written at all, which is a way of standing a machine up
    # with the storage untouched and nothing else.
    #
    # **The conversations are the one thing it does not cover.** Step three
    # moved those onto `objects.chat`, with the task that owns one as a row in
    # the link table (`rouh/conversations.py`), and there is nowhere else for
    # a conversation to live: a flag that hid a person's chats would not be a
    # safety valve, so that module opens the store whatever this says.
    object_model_enabled: bool = field(
        default_factory=lambda: _flag("ROUH_OBJECT_MODEL_ENABLED", True))

    def db_password_now(self) -> str:
        """The database password: said outright, or read from its file.

        Read when Django opens its settings, never logged. A file that is not
        there, or not readable by this user, is an empty password, which is
        right for a cluster that trusts its own socket.
        """
        if self.db_password:
            return self.db_password
        try:
            with open(self.db_password_file, encoding="utf-8") as fh:
                return str((json.load(fh) or {}).get("password") or "")
        except (OSError, ValueError, AttributeError):
            return ""

    @property
    def legacy_sqlite_path(self) -> str:
        """The SQLite file Rouh kept everything in until 23 September 2026.

        Read once, by `manage.py import_sqlite`, when the data moved into
        PostgreSQL; nothing opens it after that. It was ``jarvis.sqlite3``
        until 22 September 2026, so a data directory that still holds that
        file and not this one is read from the old name.
        """
        mine = os.path.join(self.data_dir, "rouh.sqlite3")
        if not os.path.exists(mine):
            was = os.path.join(self.data_dir, "jarvis.sqlite3")
            if os.path.exists(was):
                return was
        return mine

    @property
    def logs_path(self) -> str:
        """The directory the audit trail is written into."""
        return self.log_dir or os.path.join(self.data_dir, "logs")

    def missing(self) -> list[str]:
        """What is not configured, so /healthz can say so instead of failing later."""
        gaps = []
        if not self.anthropic_api_key:
            gaps.append("ANTHROPIC_API_KEY")
        if not self.elevenlabs_api_key:
            gaps.append("ELEVENLABS_API_KEY")
        if not self.voice_id:
            gaps.append("ROUH_VOICE_ID")
        return gaps


config = Config()
