"""Screenshot comparisons: the one committed browser suite in this repository.

Petar asked for it on 5 October 2026, before app.js was split into modules and
its files given content-hashed names, so that a refactor which is meant to
change nothing can be shown to have changed nothing. Every other proof here is
still a live drive over Playwright MCP (AGENTS.md); this suite is the exception
because what it guards is "the screens look exactly as they did", and that is a
question only a stored picture can answer.

    ./e2e.sh visual                   compare every screen with its baseline
    ./e2e.sh visual -k brief          one screen, both widths
    ./e2e.sh visual --update          take new baselines, on purpose

Each screen is taken at two widths, a phone (390 x 844) and a desk
(1440 x 900), in one world built for the suite (`world` below): a fixed small
workspace, the stand-in model, and nothing that reaches the network, so the
same code draws the same pixels. What moves or depends on the moment - the
orb's animation, the machine's load, clocks, the commit on the version chip -
is hidden or painted over with a flat mask before the comparison, CSS
animations are stopped by Playwright itself, and the browser's clock is held
at one moment.

A screen passes when no more than `MAX_DIFF_RATIO` of its pixels differ by more
than `PIXEL_THRESHOLD` in any channel, which absorbs anti-aliasing and nothing
a person would notice. A failure writes three pictures under
tests/e2e/.artifacts/visual/: what was expected, what was drawn, and the
difference in red.

The baselines are this machine's Chromium (the one ./e2e.sh installs) on
this server's fonts. Taken anywhere else, text renders a pixel differently and every
screen fails; run the suite where the baselines were taken, or take new ones
there with --update and commit them.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e import conftest as harness

HERE = Path(__file__).resolve().parent
BASELINES = HERE / "baselines"
ARTIFACTS = HERE.parent / ".artifacts" / "visual"
ROOT = HERE.parents[2]

#: `./e2e.sh visual --update` sets this: write what is drawn as the new
#: baseline instead of comparing with the old one.
UPDATING = os.environ.get("ROUH_VISUAL_UPDATE") == "1"

#: How far a channel may move before a pixel counts as different (0-255).
PIXEL_THRESHOLD = 32
#: How much of a screen may differ before it fails: 0.2%, which is about 2,600
#: pixels at a desk and 640 on a phone - a few glyphs' anti-aliasing, never a
#: moved panel, a changed colour or a missing button.
MAX_DIFF_RATIO = 0.002

WIDTHS = {
    "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True,
              "has_touch": True, "device_scale_factor": 1},
    "desk": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
}

#: Painted over on every screen, wherever they are: things that are right to
#: differ from one run to the next.
ALWAYS_MASKED = (
    "#orbStats .orb-stat-v",   # cpu, ram and spend read off the live machine
    ".card-when",              # the time a card was drawn
    ".msg-time", ".msg-when",  # the time a message was said
    ".turn-usage",             # prompt length and caching change as code grows
    ".tline",                  # how a reply was made: its milliseconds and costs are each run's own
    ".ver-chip", "#verRev", "#verWhen", "#verNum",  # the commit this checkout is on
)

#: Taken out of the picture rather than painted over, because they are drawn
#: under things that are worth comparing: the orb is a canvas animated every
#: frame, and its rings are this machine's load, and opened full screen it is
#: the whole window, with its controls and numbers on top of it. The sky
#: over the sidebar is where a falling star crosses it: in a fresh browser
#: not for an hour at least, but one that came due is shown a few seconds
#: after the page is up, so it is hidden rather than trusted to be empty.
HIDDEN = "#orb, #orb3d, .orb3d-labels, #orbRing, .sb-sky { visibility: hidden !important; }"

#: The moment the suite pretends it is, for the browser's own clock. Server
#: times are masked; this keeps a page's "today" and its relative times still.
FROZEN_AT = "2026-10-05T09:00:00+00:00"


def _workspace(folder: Path) -> Path:
    """The small fixed workspace conftest.py builds, as a git checkout.

    Never this checkout's own workspace/: that changes every day, and a task
    browser drawn from it would fail on every new task.
    """
    ws = folder / "workspace"
    harness.build_workspace(ws, work_only=True)
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.email=world@example.invalid", "-c",
                  "user.name=The harness", "commit", "-qm", "the visual suite's workspace"]):
        subprocess.run(argv, cwd=ws, check=True, capture_output=True)
    return ws


#: A closed email case, so /mail/case has something fixed to draw.
SEED_CASE = r'''
import django
django.setup()
from rouh.models import UserSetting
# Scheduled work is exercised separately: a visual world must draw the same
# screen whether started before or after the person's morning-brief time.
UserSetting.objects.update_or_create(
    user_id="1", org_id="org-default", name="morning_brief",
    defaults={"value": '{"on": false}', "updated_at": 1791190800.0})
from rouh.models.trust import MailCase
MailCase.objects.filter(key="visual-case").delete()
MailCase.objects.create(
    user_id="1", org_id="org-default", message_id="m-visual-1", key="visual-case",
    thread_id="t-visual-1", sender="sam@example.org", sender_name="Sam Rivera",
    subject="Can we move Thursday's call?",
    email={"from": "Sam Rivera <sam@example.org>",
           "subject": "Can we move Thursday's call?",
           "body": "Hi,\n\nSomething came up on Thursday. Could we move our call "
                   "to Friday at 10?\n\nThanks,\nSam"},
    identity_ok=True, identity_said="Gmail confirmed the sender (DKIM, SPF)",
    stage="done", route="nothing", outcome="Nothing to do: Alex answers this one.",
    created_at=1791190800.0, updated_at=1791190800.0)
# Synapse makes its two example datasets the first time it is opened, in the
# background, and a screen taken while they fill in is a different screen
# every time. Said to have been done already, it shows Synapse Master alone,
# which is made here rather than whenever the contacts sync gets to it.
from django.db import connection
with connection.cursor() as c:
    c.execute("INSERT INTO synapse.backend_status (org_id, name, status, said) "
              "VALUES ('org-default', 'seeded:1', 'done', 'examples made') ON CONFLICT DO NOTHING")
from rouh.synapse import master
master.make("org-default", "1")
'''


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    """Rouh with the stand-in model, a fixed workspace and a fixed email case."""
    from rouh.testing import browser

    folder = tmp_path_factory.mktemp("visual")
    nowhere = "http://127.0.0.1:1/no-network"
    generator = browser.start(
        folder,
        ROUH_ASSISTANT_REPO=str(_workspace(folder)),
        # The morning brief reads public feeds; here they answer nothing, so
        # the brief draws the same "could not be read" sections every time.
        ROUH_BRIEF_WEATHER_URL=nowhere, ROUH_BRIEF_WORLD_FEED=nowhere,
        ROUH_BRIEF_CHANNEL_FEED=nowhere, ROUH_BRIEF_CHANNEL_PAGE=nowhere,
        ROUH_BRIEF_HISTORY_FEED=nowhere, ROUH_BRIEF_JOKE_FEED=nowhere,
        TMUX=None,
    )
    live = next(generator)
    env = {**os.environ, **live.database, "ROUH_DATA_DIR": live.data_dir,
           "PYTHONPATH": str(ROOT), "DJANGO_SETTINGS_MODULE": "rouh.project.settings"}
    try:
        # Seed with the server stopped so no scheduled work races the fixtures.
        live.stop_the_server()
        seeded = subprocess.run([sys.executable, "-c", SEED_CASE], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        if seeded.returncode:
            raise RuntimeError(f"The visual fixtures could not be seeded:\n{seeded.stderr}")
        # Each task's status and summary, which are the database's.
        work_tasks = {k: v for k, v in harness.TASKS_SAY.items() if k.startswith("work/")}
        harness.seed_tasks(env, Path(live.data_dir), folder / "workspace", said=work_tasks)
        live.start_the_server()
        yield live
    finally:
        generator.close()


@pytest.fixture(params=list(WIDTHS))
def width(request) -> str:
    return request.param


@pytest.fixture
def screen(browser, world, width):
    """A signed-in page at one width, on a conversation nobody has had yet."""
    from rouh.testing.accounts import PASSWORD, USERNAME

    world.forget_the_conversation()
    context = browser.new_context(
        **WIDTHS[width], permissions=["microphone"], timezone_id="Europe/Athens",
        locale="en-GB", color_scheme="dark", reduced_motion="reduce")
    # Nothing leaves this machine: a page that reaches for a font or a feed on
    # the internet would draw whatever the network said that minute.
    context.route("**/*", lambda route: route.continue_()
                  if route.request.url.startswith(("http://127.0.0.1", "ws://127.0.0.1",
                                                   "data:", "blob:", "about:"))
                  else route.abort())
    page = context.new_page()
    page.clock.install(time=FROZEN_AT)
    page.goto(world.base_url + "/login")
    # One box first (since 4 November 2026, `rouh/web/auth.py`): a username, not an email, goes
    # straight on to the password.
    page.fill("#email", USERNAME)
    page.click("#continueBtn")
    page.wait_for_selector("input[name=password]")
    page.fill("input[name=password]", PASSWORD)
    page.click("button:has-text('Sign in')")
    page.wait_for_selector("#input")
    harness.wait_until_live(page)
    page.screen_width = width
    yield page
    context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A picture of the page a screen failed on before it was photographed - a
    wait that timed out - beside the comparisons' own pictures."""
    outcome = yield
    report = outcome.get_result()
    page = item.funcargs.get("screen") if hasattr(item, "funcargs") else None
    if report.when == "call" and report.failed and page is not None:
        try:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ARTIFACTS / f"{item.name}.failed.png"))
        except Exception:
            pass


def settle(page, ms: int = 600) -> None:
    """Fonts loaded, and a moment for the last frame of layout to land."""
    page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
    page.wait_for_timeout(ms)


def _compare(expected, drawn):
    """How many pixels differ by more than the threshold, and a picture of where."""
    from PIL import Image, ImageChops

    if expected.size != drawn.size:
        return expected.size[0] * expected.size[1], None
    delta = ImageChops.difference(expected.convert("RGB"), drawn.convert("RGB"))
    # The biggest of the three channels' differences, pixel by pixel.
    r, g, b = delta.split()
    biggest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    over = biggest.point(lambda v: 255 if v > PIXEL_THRESHOLD else 0)
    count = over.histogram()[255]
    picture = drawn.convert("RGB").copy()
    picture = Image.blend(picture, Image.new("RGB", picture.size, (0, 0, 0)), 0.6)
    picture.paste((255, 0, 0), mask=over)
    return count, picture


def shoot(page, name: str, mask=()) -> None:
    """Photograph the page and compare it with its baseline, or replace it."""
    from io import BytesIO

    from PIL import Image

    full = f"{name}-{page.screen_width}"
    locators = [page.locator(s) for s in (*ALWAYS_MASKED, *mask)]
    png = page.screenshot(animations="disabled", caret="hide", mask=locators,
                          mask_color="#ff00ff", scale="css", style=HIDDEN)
    BASELINES.mkdir(parents=True, exist_ok=True)
    baseline = BASELINES / f"{full}.png"
    if UPDATING or not baseline.exists():
        baseline.write_bytes(png)
        if not UPDATING:
            pytest.fail(f"{full}: there was no baseline, so this one was written. "
                        "Look at it, and commit it if it is right.")
        return
    drawn = Image.open(BytesIO(png))
    expected = Image.open(baseline)
    count, picture = _compare(expected, drawn)
    total = drawn.size[0] * drawn.size[1]
    if count > total * MAX_DIFF_RATIO:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        expected.save(ARTIFACTS / f"{full}.expected.png")
        drawn.save(ARTIFACTS / f"{full}.actual.png")
        if picture is not None:
            picture.save(ARTIFACTS / f"{full}.diff.png")
        pytest.fail(f"{full}: {count} of {total} pixels differ "
                    f"({count / total:.3%}, allowed {MAX_DIFF_RATIO:.1%}). "
                    f"Pictures in {ARTIFACTS}.")
