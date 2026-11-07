"""A real Rouh, a stand-in where the model would be, and a real browser.

Two test files need the same three things: a Rouh on a free port with a
throwaway database, `fake_model.py` in front of Anthropic so every request body
lands on disk, and Chromium signed in with the voice awake. They were
written out twice, so a fix to one of them was a fix to one of them. They live
here now.

The account is real and there is no way round it (`rouh/accounts.py`):
every address is behind one, and a test gets past it by making an account and
typing the username and the password into the form. Past that the page is the
page - three columns, live on the socket, no splash screen. The one thing
still waiting is the voice, because a browser will not open a microphone or a
speaker outside a real press, and that press is given here the way a person
gives it.

Nothing in here asserts anything. It starts things and hands them over.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

from . import accounts, postgres

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Who owns every world: an invented person, never anybody real (SETUP.md). The
#: prompts name the owner from their account (`rouh/owner.py`), so the stand-in
#: for the model reads "Alex" wherever the live server's prompts read its own
#: owner's name (`fake_model.OWNER`). The username is the harness's to choose
#: (`accounts.USERNAME` here, `tests/e2e/conftest.py` for its worlds).
OWNER = {"first_name": "Alex", "last_name": "Morgan", "email": "alex@example.com",
         "organisation": "Example Co"}

#: The installation's own settings every world starts Rouh with, which are blank
#: in `rouh/config.py` until an installer sets them: Rouh's own mailbox and its
#: other name (`inbox.own`), the address its letters come from, and the clock a
#: person starts on. Europe/Athens keeps the hours every stand-in's mail and
#: calendar were written for.
INSTALLATION = {
    "ROUH_OWN_MAILBOXES": "rouh@example.com,rou@example.com",
    "ROUH_MAIL_FROM": "noreply@example.com",
    "ROUH_DEFAULT_ZONE": "Europe/Athens",
}

_NAME_THE_OWNER = r"""
import json, sys
from rouh.project import setup
setup()
from rouh.models import Organisation, User
said = json.loads(sys.argv[2])
user = User.objects.get(username=sys.argv[1])
User.objects.filter(pk=user.pk).update(first_name=said["first_name"], last_name=said["last_name"],
                                       email=said["email"])
Organisation.objects.filter(id=user.org_id).update(name=said["organisation"])
"""


def name_the_owner(data_dir: str, env: dict[str, str], username: str = "") -> None:
    """Give a world's one account the invented owner's name, address and organisation.

    The admin command makes the account with a username and a password and
    nothing else, and the prompts name the owner from their account, so a world
    whose owner had no name would read "the owner" everywhere the live server
    reads a name.
    """
    done = subprocess.run(
        [sys.executable, "-c", _NAME_THE_OWNER, username or accounts.USERNAME, json.dumps(OWNER)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
        env={**env, "ROUH_DATA_DIR": str(data_dir), "PYTHONPATH": REPO},
    )
    if done.returncode != 0:
        raise RuntimeError(f"the owner could not be named:\n{done.stdout}\n{done.stderr}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, proc: subprocess.Popen, log: str, limit: float = 60.0) -> None:
    """Wait until the port answers, and say what the process printed if it never does."""
    import urllib.error
    import urllib.request

    until = time.time() + limit
    while time.time() < until:
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return                       # answering at all is what is being waited for
        except OSError:
            time.sleep(0.2)
    with open(log, encoding="utf-8", errors="replace") as fh:
        raise RuntimeError(f"{url} never came up. It said:\n{fh.read()[-4000:]}")


#: The name every request to the stand-in for OpenAI is written under
#: (`fake_openai.py`).
LUNA_FILE = "luna-"


class Live:
    """Where the running Rouh is, and where to read what it sent the model."""

    def __init__(self, base_url: str, requests_dir: str, data_dir: str,
                 spoken_dir: str | None = None, restart=None, stop=None,
                 start=None, database: dict | None = None, icloud: dict | None = None,
                 mail: dict | None = None, linkedin: dict | None = None,
                 stripe: dict | None = None, slack: dict | None = None, hue: dict | None = None,
                 dreame: dict | None = None, setup_url: str = ""):
        self.base_url = base_url
        #: A first run's address with its setup code in it, as Rouh for Mac opens it ("" otherwise).
        self.setup_url = setup_url
        #: The stand-in for the Dreamehome cloud this Rouh is pointed at (`rouh/testing/fake_dreame.py`):
        #: its address and the account it knows.
        self.dreame = dreame or {}
        #: The stand-in for the Philips Hue cloud this Rouh is pointed at (`rouh/testing/fake_hue.py`):
        #: its address, the app it knows, every call and each light's state.
        self.hue = hue or {}
        #: The stand-in for Slack this Rouh is pointed at (`rouh/testing/fake_slack.py`): its
        #: address, where people's messages are said and every call is listed.
        self.slack = slack or {}
        #: The stand-in for Stripe this Rouh is pointed at (`rouh/testing/fake_stripe.py`):
        #: its address, and the page listing every call and endpoint.
        self.stripe = stripe or {}
        #: The stand-in for Apify's LinkedIn scrapers this Rouh is pointed at
        #: (`rouh/testing/fake_apify.py`): its address, and the page listing
        #: every run it was asked for.
        self.linkedin = linkedin or {}
        #: The stand-in for Brevo this Rouh sends its letters through
        #: (`rouh/testing/fake_brevo.py`): its address, and its inbox page.
        self.mail = mail or {}
        #: The stand-in for iCloud's CardDAV this Rouh is pointed at
        #: (`rouh/testing/fake_carddav.py`): its address, and the Apple ID and
        #: app-specific password it accepts.
        self.icloud = icloud or {}
        self.requests_dir = requests_dir
        self.data_dir = data_dir
        #: Where this world's PostgreSQL is: the ROUH_DB_* settings the server
        #: was started with (`rouh/testing/postgres.py`).
        self.database = database or {}
        self.spoken_dir = spoken_dir
        self._restart = restart
        self._stop = stop
        self._start = start

    def restart_the_server(self) -> None:
        """Stop Rouh and start it again on the same port, as a deploy does.

        A page that is open when this happens loses its websocket and puts it
        back by itself, which is the only way a test can make a real reconnect
        happen: taking the browser offline does not close a socket that is
        already open, and reaching into the page to close one proves nothing
        about the page.
        """
        if self._restart is None:
            raise RuntimeError("this Live was not started with a way to restart it")
        self._restart()

    def stop_the_server(self) -> None:
        """Stop Rouh and leave it stopped.

        The same thing as the first half of a restart, held there: a page that
        is open loses its socket and stays without one, so a test can look at
        what the page says about being offline instead of racing a server that
        is already coming back. `start_the_server` puts it back.
        """
        if self._stop is None:
            raise RuntimeError("this Live was not started with a way to stop it")
        self._stop()

    def start_the_server(self) -> None:
        """Start Rouh again on the same port after `stop_the_server`."""
        if self._start is None:
            raise RuntimeError("this Live was not started with a way to start it")
        self._start()

    def spoken(self) -> list[str]:
        """Every sentence the stand-in voice was asked to say, oldest first."""
        if not self.spoken_dir or not os.path.isdir(self.spoken_dir):
            return []
        out = []
        for name in sorted(os.listdir(self.spoken_dir)):
            with open(os.path.join(self.spoken_dir, name), encoding="utf-8") as fh:
                out.append(json.load(fh).get("text") or "")
        return out

    def _recorded(self, lead: str) -> list[bytes]:
        """Every request body the stand-in wrote down under one name, oldest first.

        The turns and the side errands are kept apart. A naming, and now a
        filing, is an errand that follows a turn and lands whenever the model
        gets round to it, so a test reading "what went out with my screenshot"
        must not be handed one; the prefix each is written under is how they
        are told apart on disk (`fake_model.TITLE_FILE`, `FILING_FILE`).
        """
        from .fake_model import FILING_FILE, PASS_FILE, REVISE_FILE, TITLE_FILE, TRIAGE_FILE

        # Luna's requests are not Anthropic's turns either: they are read
        # with `luna_requests`, and a test asking for "the last request" to
        # Claude is never handed one of them.
        errands = (TITLE_FILE, FILING_FILE, TRIAGE_FILE, PASS_FILE, REVISE_FILE, LUNA_FILE)
        out = []
        for name in sorted(os.listdir(self.requests_dir)):
            if lead:
                if not name.startswith(lead):
                    continue
            elif name.startswith(errands):
                continue
            with open(os.path.join(self.requests_dir, name), "rb") as fh:
                out.append(fh.read())
        return out

    def model_requests(self) -> list[dict]:
        return [json.loads(raw) for raw in self._recorded("")]

    def raw_model_requests(self) -> list[bytes]:
        return self._recorded("")

    def model_usage(self) -> list[dict]:
        """What the stand-in billed each request as, oldest first: the file it
        was written under, its model, its breakpoints, and the usage it sent
        back, cache reads and writes included (`fake_model.cache_usage`)."""
        from .fake_model import usage_file

        try:
            with open(usage_file(self.requests_dir), encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            return []

    def title_requests(self) -> list[dict]:
        """What was sent to have a chat named. See `rouh/chats.py`."""
        from .fake_model import TITLE_FILE

        return [json.loads(raw) for raw in self._recorded(TITLE_FILE)]

    def luna_requests(self) -> list[dict]:
        """What was sent to OpenAI for a turn Luna answered (`rouh/luna.py`)."""
        return [json.loads(raw) for raw in self._recorded(LUNA_FILE)]

    def filing_requests(self) -> list[dict]:
        """What was sent to have a new task filed. See `rouh/filing.py`."""
        from .fake_model import FILING_FILE

        return [json.loads(raw) for raw in self._recorded(FILING_FILE)]

    def forget_the_conversation(self) -> None:
        """Empty the transcript in this throwaway Rouh, between tests.

        Every browser is in the same chat, which is the whole point of it
        (`memory.CONVERSATION`), so a new browser context is not a new
        conversation. Without this each test in a file starts with what the
        test before it said still on the screen, and a test that waits for a
        word to appear is satisfied by the previous test's answer before the
        model has been asked anything at all.

        Straight into the database because there is nothing on the page that
        clears a conversation; this is a test's own setup, not a thing the
        person does. The running server holds its own connection to the same
        file in WAL mode, which is what makes a second writer safe here.
        """
        import psycopg

        db = psycopg.connect(host=self.database["ROUH_DB_HOST"],
                             port=self.database["ROUH_DB_PORT"],
                             dbname=self.database["ROUH_DB_NAME"],
                             user=self.database["ROUH_DB_USER"], autocommit=False)
        try:
            db.execute("DELETE FROM messages")
            # And the chats, which are the same thing seen from further out:
            # the conversation is now several of them, each with its own
            # history, its own title and its own cards, and a test that starts
            # with the chats the test before it made is a test that starts
            # halfway through somebody else's work. The first chat stays,
            # untitled and unfiled, because that is what a Rouh nobody has
            # talked to yet has.
            #
            # A chat is a row of `objects.chat` since 21 September 2026, with
            # its turns in `message` and whatever owns it in `link`, so all
            # three go.
            db.execute("DELETE FROM message")
            db.execute("DELETE FROM chat WHERE id <> 'conversation'")
            db.execute("DELETE FROM link WHERE dst_type='chat' OR src_type='chat'"
                       " OR src_type='project' OR dst_type='project'")
            db.execute("DELETE FROM project")
            db.execute("UPDATE chat SET title=NULL, unread=false, state='live'")
            db.execute("DELETE FROM app_state WHERE key='active_chat'")
            db.commit()
        finally:
            db.close()


def _workspace_copy(root) -> str:
    """A real workspace (`workspace_source.source`), copied into the world and
    made a git checkout of its own, the way `rouh_with_tree` in
    tests/e2e/conftest.py does it and for the same reasons: Rouh writes into a
    workspace, and moves folders in it with `git mv`."""
    import shutil

    from .workspace_source import source

    target = os.path.join(str(root), "workspace")
    if os.path.isdir(target):
        return target
    shutil.copytree(source(), target, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "temp", "*.sqlite3*"))
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.email=world@example.invalid", "-c", "user.name=The harness",
                  "commit", "-qm", "the workspace, as this checkout has it"]):
        subprocess.run(argv, cwd=target, check=True, capture_output=True)
    return target


def start(root, with_voice: bool = False, luna: bool = False, anthropic: bool = True,
          google: bool = False, xai: bool = False, first_run: bool = False, **extra_env):
    """Start the stand-in model and a Rouh in front of it. A generator fixture.

    `root` is a directory to put everything in, `extra_env` anything a test
    wants set on top. `luna` gives Rouh the key the stand-in for OpenAI takes,
    so Luna can be picked and General answers with it, as the server does once
    it has a real key (`rouh/luna.py`); without it this world is the server as
    it is without one. Yields a :class:`Live`, and takes the processes down
    again afterwards whatever happened.

    `with_voice` starts a stand-in for ElevenLabs as well
    (`rouh/testing/fake_voice.py`) and points Rouh at it, so replies really
    are spoken and real audio really does arrive at the page. Off by default:
    every other browser test wants a Rouh that says nothing out loud, which
    is what `ROUH_VOICE_REPLIES=0` below gives it.

    `first_run` is a fresh install of the containers, as Rouh for Mac starts it: no owner, no
    model key, a setup code in ``data/first-run-code`` (`Live.setup_url` opens with it), a keys
    folder of the world's own and Claude Code's sign-in page on (`rouh/web/firstrun.py`).

    `anthropic` False takes Anthropic's key away, for a world with only another
    provider's; `google` and `xai` give this installation the key the stand-in for
    Google's and xAI's Chat Completions takes (`rouh/testing/fake_compat.py`). That
    stand-in is always started and both providers are always pointed at it, so a key
    typed into Anatomy, Rouh Land Account, Models reaches the stand-in and never Google or xAI.

    An `extra_env` value of None takes that variable out of the environment
    rather than setting it to anything. `TMUX` is the one that matters: a tmux
    client reads it before it reads `TMUX_TMPDIR`, so a Rouh started from
    inside a pane - which is where this suite runs on the server - would open
    its workers on that pane's tmux server whatever else it was told
    (`rouh/testing/tmux_sandbox.py` is the long version).
    """
    data_dir = str(root / "data")
    requests_dir = str(root / "model-requests")
    spoken_dir = str(root / "spoken")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(requests_dir, exist_ok=True)
    os.makedirs(spoken_dir, exist_ok=True)
    # An explicit workspace must not first copy the real checkout's workspace.
    workspace = extra_env.get("ROUH_ASSISTANT_REPO") or _workspace_copy(root)

    model_port, app_port = free_port(), free_port()
    model_log, app_log = str(root / "model.log"), str(root / "app.log")

    env = dict(os.environ)
    env.update(
        PYTHONPATH=REPO,
        ROUH_DATA_DIR=data_dir,
        # A copy of this checkout's workspace, never the checkout itself: Rouh
        # files an unfiled task into a project the moment it starts, with
        # `git mv`, and a world pointed at the checkout moved folders in this
        # repository (found on 23 September 2026).
        ROUH_ASSISTANT_REPO=workspace,
        ROUH_PORT=str(app_port),
        # The key a worker in another container shows Rouh (`rouh/workerkey.py`), in this
        # world's own folder. Inherited, it is the container's shared /run/one/rouh-worker.json,
        # and a world started there (2 November 2026) wrote its own address and key into it, so
        # every other run's rouh tools and rouh-task talked to the world instead of to Rouh.
        ROUH_WORKER_KEY_FILE=str(root / "rouh-worker.json"),
        # The address this world is reached at, so a link Rouh makes to
        # itself for somebody else to open - a public page's, from
        # `publish_task` - is a link to this world. Left unsaid it is the live
        # server's, and a link from here would open a page there.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{app_port}",
        **INSTALLATION,
        ANTHROPIC_API_KEY="test-key-not-a-real-one" if anthropic else "",
        GEMINI_API_KEY="test-gemini-key-not-a-real-one" if google else "",
        XAI_API_KEY="test-xai-key-not-a-real-one" if xai else "",
        ROUH_GOOGLE_BASE_URL="http://127.0.0.1:1/no-google/v1beta/openai/",
        ROUH_XAI_BASE_URL="http://127.0.0.1:1/no-xai/v1",
        ANTHROPIC_BASE_URL=f"http://127.0.0.1:{model_port}",
        # Luna, OpenAI's model, has a stand-in of its own, started below, and
        # a key that is only ever the stand-in's, given only with `luna`.
        # Without it there is no key at all, whatever this machine exports,
        # which is the server as it is today: Luna greyed out in the box and
        # General answering with Claude. Nothing here ever reaches OpenAI.
        OPENAI_API_KEY="sk-test-key-not-a-real-one" if luna else "",
        OPENAI_BASE_URL="http://127.0.0.1:1/no-openai/v1",
        ELEVENLABS_API_KEY="",                      # nothing is spoken here
        ROUH_VOICE_REPLIES="0",
        ROUH_REALTIME_STT="0",
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_ONE_SOCKET=str(root / "no-one.sock"),
        ROUH_ONE_TOKEN=str(root / "no-one-token.json"),
        # The landing lock and the conflict records (`land.sh`,
        # `rouh/conflicts.py`), in a folder of this world's own. Every fixture
        # in tests/e2e/conftest.py already does this and this did not, so a
        # Rouh started here read the real ones: a live job's question turned
        # this world's orb red, and a pick made in this world would have
        # decided a live job's conflict.
        ROUH_LAND_DIR=str(root / "land"),
        # Nowhere, and at an address that answers nothing. The real file is on
        # this server and holds the real bot: a browser test that found it
        # would text the owner every time the suite ran. A test that wants to watch
        # a message go out writes its own file and starts
        # `rouh/testing/fake_telegram.py` in front of it.
        ROUH_TELEGRAM_FILE=str(root / "no-telegram.json"),
        ROUH_TELEGRAM_API_BASE="http://127.0.0.1:1/no-telegram",
        # A person's own Telegram account, which makes a group for each fork
        # (`rouh/telegram_account.py`): the stand-in's side of it, at an
        # address that answers nothing unless a test starts the stand-in and
        # says where it is. Never Telegram itself, with anybody's account.
        ROUH_TELEGRAM_ACCOUNT_URL="http://127.0.0.1:1/no-telegram-account",
        # iCloud's CardDAV is a stand-in of this world's own, started below. A
        # world left pointed at contacts.icloud.com would send whatever Apple
        # ID was typed into Settings to Apple.
        ROUH_CARDDAV_URL="http://127.0.0.1:1/no-icloud",
        # Brevo is a stand-in of this world's own too, started below, with a
        # key file that holds the stand-in's key. Left pointed at the real
        # service, a world would find no key and send nothing, which is
        # right, and a world given the real key would mail real people.
        ROUH_BREVO_FILE=str(root / "no-brevo.json"),
        ROUH_BREVO_URL="http://127.0.0.1:1/no-brevo",
        # LinkedIn research goes to a stand-in for Apify of this world's own,
        # started below, with the stand-in's key. A world given the real key
        # would spend money and read real people's profiles.
        APIFY_API_TOKEN="",
        ROUH_APIFY_URL="http://127.0.0.1:1/no-apify",
        # Voyage AI, which makes Synapse's vectors, is a stand-in of this
        # world's own too, started below with the stand-in's key. Never the
        # real one: it would spend the real key's three requests a minute.
        VOYAGE_API_KEY="",
        VOYAGE_ENDPOINT="http://127.0.0.1:1/no-voyage",
        # Stripe is a stand-in of this world's own, started below. A world left
        # pointed at api.stripe.com would send whatever key was typed into
        # Payments to Stripe, and make real products and links with it.
        ROUH_STRIPE_API_BASE="http://127.0.0.1:1/no-stripe",
        # Cloudflare is a stand-in of this world's own, started below, and the first zone's
        # token the server's settings hold is the stand-in's, so Settings, Cloudflare
        # carries it over as live Rouh does (`rouh/cloudflare.py`) with nothing real.
        ROUH_CLOUDFLARE_API="http://127.0.0.1:1/no-cloudflare",
        CLOUDFLARE_ROUH_IS_TOKEN="",
        # rouh.land, for the model standard and the counts of how each model did: never
        # reached from a world (`rouh/modelstandard.py`, `rouh/modeloutcomes.py`).
        ROUH_MODEL_STANDARD_URL="http://127.0.0.1:1/no-rouh-it/standard.json",
        ROUH_MODEL_OUTCOMES_URL="http://127.0.0.1:1/no-rouh-it/outcomes",
        ROUH_MODEL_OUTCOMES_SEND="0",
        # And the rule defaults (`rouh/ruledefaults.py`): the two a Rouh starts with offline, unless
        # ROUH_TEST_RULE_DEFAULTS_URL points the world at a stand-in of its own.
        ROUH_RULE_DEFAULTS_URL=os.environ.get("ROUH_TEST_RULE_DEFAULTS_URL",
                                              "http://127.0.0.1:1/no-rouh-it/rules.json"),
        # Slack is a stand-in of this world's own, started below (`rouh/testing/fake_slack.py`).
        # Left pointed at slack.com, a world would send whatever token was pasted into Settings
        # to Slack, and post in a real workspace with it.
        ROUH_SLACK_API="http://127.0.0.1:1/no-slack",
        # The Philips Hue cloud is a stand-in of this world's own, started below
        # (`rouh/testing/fake_hue.py`): Connect goes to its sign-in page, never Hue's.
        ROUH_HUE_API="http://127.0.0.1:1/no-hue",
        # The Dreamehome cloud is a stand-in of this world's own, started below
        # (`rouh/testing/fake_dreame.py`): an email and password typed into Settings never reach Dreame.
        ROUH_DREAME_API="http://127.0.0.1:1/no-dreame",
    )
    setup_url = ""
    if first_run:
        import secrets

        keys = root / "keys"
        os.makedirs(keys, exist_ok=True)
        code_file = os.path.join(data_dir, "first-run-code")
        with open(code_file, "w") as fh:
            fh.write(secrets.token_urlsafe(18) + "\n")
        env.update(ANTHROPIC_API_KEY="", OPENAI_API_KEY="", ROUH_FIRST_RUN_CODE_FILE=code_file,
                   ROUH_KEYS_DIR=str(keys), ROUH_CLAUDE_SIGNIN="1", ROUH_PUBLISHED_PORT=str(app_port))
    env.update({k: str(v) for k, v in extra_env.items() if v is not None})
    for name, value in extra_env.items():
        if value is None:
            env.pop(name, None)

    procs: list[subprocess.Popen] = []
    try:
        with open(model_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_model",
                 "--port", str(model_port), "--record", requests_dir],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{model_port}/openapi.json", procs[-1], model_log)

        # The same for OpenAI's Responses API, which is what Luna answers
        # through (`rouh/luna.py`). Its requests land beside Anthropic's, each
        # named `luna-...json`, so a test reads what was sent to either.
        luna_port = free_port()
        luna_log = str(root / "luna.log")
        with open(luna_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_openai",
                 "--port", str(luna_port), "--record", requests_dir],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{luna_port}/openapi.json", procs[-1], luna_log)
        if "OPENAI_BASE_URL" not in extra_env:
            env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{luna_port}/v1"

        # Google's and xAI's Chat Completions, one stand-in for both (`fake_compat.py`):
        # requests land beside the others as `compat-<provider>-...json`.
        compat_port = free_port()
        compat_log = str(root / "compat.log")
        with open(compat_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_compat",
                 "--port", str(compat_port), "--record", requests_dir],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{compat_port}/openapi.json", procs[-1], compat_log)
        if "ROUH_GOOGLE_BASE_URL" not in extra_env:
            env["ROUH_GOOGLE_BASE_URL"] = f"http://127.0.0.1:{compat_port}/v1beta/openai/"
        if "ROUH_XAI_BASE_URL" not in extra_env:
            env["ROUH_XAI_BASE_URL"] = f"http://127.0.0.1:{compat_port}/v1"

        # A stand-in for iCloud's contacts, with an address book in it, so
        # Settings can be connected for real and the contacts tools answer.
        from .fake_carddav import APP_PASSWORD, APPLE_ID

        icloud_port = free_port()
        icloud_log = str(root / "icloud.log")
        with open(icloud_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_carddav", "--port", str(icloud_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{icloud_port}/_state", procs[-1], icloud_log)
        icloud = {"url": f"http://127.0.0.1:{icloud_port}/", "apple_id": APPLE_ID,
                  "app_password": APP_PASSWORD}
        if "ROUH_CARDDAV_URL" not in extra_env:
            env["ROUH_CARDDAV_URL"] = icloud["url"]

        # A stand-in for Brevo, with an inbox a browser can open, so a page
        # shared by email sends a real letter and its link can be pressed.
        from .fake_brevo import KEY as BREVO_KEY

        mail_port = free_port()
        mail_log = str(root / "mail.log")
        with open(mail_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_brevo", "--port", str(mail_port),
                 "--record", str(root / "mail")],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{mail_port}/letters", procs[-1], mail_log)
        mail = {"url": f"http://127.0.0.1:{mail_port}",
                "inbox": f"http://127.0.0.1:{mail_port}/inbox"}
        if "ROUH_BREVO_URL" not in extra_env:
            key_file = root / "brevo.json"
            key_file.write_text(json.dumps({"api_key": BREVO_KEY}), encoding="utf-8")
            env["ROUH_BREVO_URL"] = mail["url"]
            env["ROUH_BREVO_FILE"] = str(key_file)

        # A stand-in for Apify's HarvestAPI scrapers, full of made-up people
        # with drawn faces, so a LinkedIn search and a harvest really run.
        from .fake_apify import KEY as APIFY_KEY

        apify_port = free_port()
        apify_log = str(root / "apify.log")
        with open(apify_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_apify", "--port", str(apify_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{apify_port}/_calls", procs[-1], apify_log)
        linkedin = {"url": f"http://127.0.0.1:{apify_port}",
                    "calls": f"http://127.0.0.1:{apify_port}/_calls"}
        if "ROUH_APIFY_URL" not in extra_env:
            env["ROUH_APIFY_URL"] = linkedin["url"]
            env["APIFY_API_TOKEN"] = APIFY_KEY

        # Voyage AI's embeddings (`rouh/testing/fake_voyage.py`), recorded
        # beside the model's requests as `voyage-...json`.
        from .fake_voyage import KEY as VOYAGE_KEY

        voyage_port = free_port()
        voyage_log = str(root / "voyage.log")
        with open(voyage_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_voyage", "--port", str(voyage_port),
                 "--record", requests_dir],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{voyage_port}/_state", procs[-1], voyage_log)
        if "VOYAGE_ENDPOINT" not in extra_env:
            env["VOYAGE_ENDPOINT"] = f"http://127.0.0.1:{voyage_port}"
            env["VOYAGE_API_KEY"] = VOYAGE_KEY

        # Stripe's API (`rouh/testing/fake_stripe.py`), which takes any rk_test_
        # key and signs its events the way Stripe does.
        stripe_port = free_port()
        stripe_log = str(root / "stripe.log")
        with open(stripe_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_stripe", "--port", str(stripe_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{stripe_port}/_calls", procs[-1], stripe_log)
        stripe = {"url": f"http://127.0.0.1:{stripe_port}",
                  "calls": f"http://127.0.0.1:{stripe_port}/_calls"}
        if "ROUH_STRIPE_API_BASE" not in extra_env:
            env["ROUH_STRIPE_API_BASE"] = stripe["url"]

        # Cloudflare's API (`rouh/testing/fake_cloudflare.py`), which knows a few
        # tokens and refuses every other one as Cloudflare does.
        from .fake_cloudflare import FIRST as CF_FIRST, TOKENS as CF_TOKENS

        cf_port = free_port()
        cf_log = str(root / "cloudflare.log")
        with open(cf_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_cloudflare", "--port", str(cf_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{cf_port}/_calls", procs[-1], cf_log)
        if "ROUH_CLOUDFLARE_API" not in extra_env:
            env["ROUH_CLOUDFLARE_API"] = f"http://127.0.0.1:{cf_port}"
            env["CLOUDFLARE_ROUH_IS_TOKEN"] = next(t for t, g in CF_TOKENS.items() if g["zones"] == [CF_FIRST])

        # Slack (`rouh/testing/fake_slack.py`): its Web API and its Socket Mode, with a workspace
        # of four people and the tokens it knows (`TOKENS`).
        slack_port = free_port()
        slack_log = str(root / "slack.log")
        with open(slack_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_slack", "--port", str(slack_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{slack_port}/_sockets", procs[-1], slack_log)
        slack = {"url": f"http://127.0.0.1:{slack_port}", "calls": f"http://127.0.0.1:{slack_port}/_calls"}
        if "ROUH_SLACK_API" not in extra_env:
            env["ROUH_SLACK_API"] = f"http://127.0.0.1:{slack_port}/api"

        # The Philips Hue cloud (`rouh/testing/fake_hue.py`): its sign-in page, its token endpoint,
        # the bridge's link button and a small home of rooms, a zone, lights and scenes.
        hue_port = free_port()
        hue_log = str(root / "hue.log")
        with open(hue_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_hue", "--port", str(hue_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{hue_port}/_calls", procs[-1], hue_log)
        from . import fake_hue
        hue = {"url": f"http://127.0.0.1:{hue_port}", "client_id": fake_hue.CLIENT_ID,
               "client_secret": fake_hue.CLIENT_SECRET, "app_id": fake_hue.APP_ID}
        if "ROUH_HUE_API" not in extra_env:
            env["ROUH_HUE_API"] = hue["url"]

        # The Dreamehome cloud and one robot on it (`rouh/testing/fake_dreame.py`): the sign-in, the
        # robot's properties and actions, and a map that names five rooms; and the same robot
        # through a Mi Home account, with Xiaomi's two-step code and picture.
        dreame_port = free_port()
        dreame_log = str(root / "dreame.log")
        with open(dreame_log, "w") as fh:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "rouh.testing.fake_dreame", "--port", str(dreame_port)],
                cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{dreame_port}/_calls", procs[-1], dreame_log)
        from . import fake_dreame
        dreame = {"url": f"http://127.0.0.1:{dreame_port}", "email": fake_dreame.EMAIL,
                  "password": fake_dreame.PASSWORD, "mi_user": fake_dreame.MI_USER,
                  "mi_password": fake_dreame.MI_PASSWORD, "mi_code": fake_dreame.MI_CODE,
                  "mi_captcha": fake_dreame.MI_CAPTCHA}
        if "ROUH_DREAME_API" not in extra_env:
            env["ROUH_DREAME_API"] = dreame["url"]

        if with_voice:
            voice_port = free_port()
            voice_log = str(root / "voice.log")
            with open(voice_log, "w") as fh:
                procs.append(subprocess.Popen(
                    [sys.executable, "-m", "rouh.testing.fake_voice",
                     "--port", str(voice_port), "--record", spoken_dir],
                    cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT))
            wait_for(f"http://127.0.0.1:{voice_port}/openapi.json", procs[-1], voice_log)
            env.update(
                ELEVENLABS_BASE_URL=f"http://127.0.0.1:{voice_port}/v1",
                ELEVENLABS_API_KEY="test-key-not-a-real-one",
                ROUH_VOICE_REPLIES="1",
            )
            env.update({k: str(v) for k, v in extra_env.items() if v is not None})

        app = {"proc": None}

        def start_the_app() -> None:
            with open(app_log, "a") as fh:
                app["proc"] = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "rouh.server:app",
                     "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "warning"],
                    cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT)
            procs.append(app["proc"])
            wait_for(f"http://127.0.0.1:{app_port}/", app["proc"], app_log)

        def stop_the_app() -> None:
            """Stop Rouh and leave the port empty.

            Only ever the process id this function started, which is the whole
            of the rule about killing things on a machine where other people's
            jobs are running under the same user.
            """
            was = app["proc"]
            if was is not None and was.poll() is None:
                was.terminate()
                try:
                    was.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    was.kill()
                    was.wait(timeout=10)
            if was in procs:
                procs.remove(was)
            app["proc"] = None

        def restart_the_app() -> None:
            stop_the_app()
            start_the_app()

        # A PostgreSQL of this world's own, with the schema in it, before Rouh
        # starts: Rouh will not start on a database without one.
        cluster = postgres.for_world(root, env)
        start_the_app()

        # Somebody to be. Made through the same admin command a person runs on
        # the server, so every run of the suite exercises it. A first run has nobody yet:
        # the owner is made on its page.
        if not first_run:
            accounts.make_account_in(data_dir, env)
            name_the_owner(data_dir, env)
        else:
            with open(env["ROUH_FIRST_RUN_CODE_FILE"]) as fh:
                setup_url = f"http://127.0.0.1:{app_port}/setup?code={fh.read().strip()}"
        yield Live(f"http://127.0.0.1:{app_port}", requests_dir, data_dir, spoken_dir,
                   restart_the_app, stop_the_app, start_the_app, database=cluster.env(),
                   icloud=icloud, mail=mail, linkedin=linkedin, stripe=stripe, slack=slack, hue=hue,
                   dreame=dreame, setup_url=setup_url)
    finally:
        for proc in reversed(procs):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        postgres.stop_world(root)


def chromium(microphone: str | None = None):
    """A Chromium with a microphone in it. A generator fixture.

    A fake microphone rather than none: a test that presses the microphone
    button gets a real stream, and a browser with no audio device at all sends
    the page down the "no microphone" path, which is not the path the owner is on.
    Skips, loudly, when there is no browser to drive here.

    `microphone` is a WAV file Chromium plays into that device, on a loop,
    which is how a test has somebody actually speak: see
    `rouh/testing/fake_microphone.py`, which writes one. Without it the
    device is Chromium's own steady tone, which the page's speech detection
    rightly refuses to call speech.
    """
    import pytest
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    if microphone:
        args.append(f"--use-file-for-fake-audio-capture={microphone}")
    try:
        with sync_playwright() as pw:
            try:
                b = pw.chromium.launch(args=args)
            except PlaywrightError as exc:
                pytest.skip(f"Chromium is not installed for Playwright here: {exc}")
            yield b
            b.close()
    except PlaywrightError as exc:                  # the driver itself is missing
        pytest.skip(f"Playwright could not start: {exc}")


class Engine:
    """A launched browser, and the phone to open it on.

    `devices` is Playwright's own description of a real handset - its screen,
    its density, its touchscreen and its user agent - and it has to be read off
    the Playwright object that launched the browser, which is why the two
    travel together rather than the test fetching one of them itself.
    """

    def __init__(self, name, browser, phone):
        self.name = name
        self.browser = browser
        self.phone = phone

    def new_context(self, **extra):
        return self.browser.new_context(**dict(self.phone, **extra))


def an_engine(name: str, phone: str = "iPhone 13"):
    """A browser of the named engine, on a phone. A generator fixture.

    Skips, loudly and with the command that fixes it, where the machine has no
    build of that engine. WebKit is what Safari and every browser on an iPhone
    are built on, so it is the honest engine for anything about iOS, and
    Playwright has no WebKit build for every distribution - Ubuntu 26.04, which
    is this server, is one of the ones it refuses. Chromium driving the
    phone's own screen and touchscreen still proves anything that is in the
    page's own script rather than in the engine.
    """
    import pytest
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    try:
        with sync_playwright() as pw:
            kind = getattr(pw, name, None)
            if kind is None:
                pytest.skip(f"Playwright here has no {name}")
            try:
                browser = kind.launch()
            except PlaywrightError as exc:
                pytest.skip(f"no {name} on this machine - "
                            f"`playwright install {name}` ({str(exc)[:120]})")
            yield Engine(name, browser, dict(pw.devices[phone]))
            browser.close()
    except PlaywrightError as exc:                  # the driver itself is missing
        pytest.skip(f"Playwright could not start: {exc}")


def show_the_runs(page):
    """Press the `</>` in the sidebar's header, the way the person does.

    The sidebar shows one list at a time, the chats and tasks or the work
    running now, and it comes up on the chats. So a test about a run presses
    that half of the switch first, exactly as its reader would, rather than
    reaching past the page.
    """
    page.click("#railTabRuns")
    page.wait_for_selector("#tasksList:visible")
    return page


def open_the_page(browser, live, wake: bool = True, **context_args):
    """A fresh conversation, signed in, started, connected. A generator fixture.

    Fresh because the chats are emptied first: the conversation lives on the
    server and is shared by every browser, so a new context on its own is not a
    new conversation.

    The socket opens with the page and nothing has to be pressed first. The
    speaker does need a press - a browser will not play a sound on a page
    nobody has touched - so `wake` gives one, on the name in the top bar where
    nothing happens. The session id arrives on the socket's `ready`, and
    nothing can be sent before it does, so waiting for it here is what every
    test needs.

    `wake=False` leaves that press ungiven, which is where most people actually
    are: they open the page and type. A test of what Rouh says out loud has
    to start there, because the bug was that a page which had never been
    pressed threw every spoken reply away.

    No microphone is opened either way. This page opens one only when somebody
    presses the microphone button, holds hold-to-talk or starts dictating; a
    test that wants a live one does that itself. `acquireMic` and
    `releaseMic` in `rouh/static/app.js` are the only two functions anywhere
    that may touch a `MediaStream`, and that is the whole of the rule.
    """
    live.forget_the_conversation()
    context = browser.new_context(permissions=["microphone"], **context_args)
    page = context.new_page()
    accounts.sign_in_in_the_browser(page, live.base_url)
    if wake:
        page.locator(".brand-name").click()
    page.wait_for_function(
        "() => document.getElementById('sessId')"
        " && document.getElementById('sessId').textContent.trim().length > 1",
        timeout=30_000)
    yield page
    context.close()
