"""The screens, each at a phone's width and a desk's (conftest.py says how)."""
from __future__ import annotations

import json
import re

from .conftest import settle, shoot

#: A card with one of each block people meet most: a number, words, a table
#: and a page drawn in a frame.
CARD = {
    "title": "Quarter at a glance",
    "blocks": [
        {"block": "stat", "label": "Revenue", "value": "€41,200",
         "hint": "up 12% on last quarter"},
        {"block": "text", "text": "The **second quarter** closed ahead of plan. "
                                  "Three things moved it:\n\n- the Lisbon offsite\n"
                                  "- two new clients\n- a lower hosting bill"},
        {"block": "table", "label": "By month", "columns": ["Month", "Revenue", "Costs"],
         "rows": [["April", "€12,900", "€8,100"], ["May", "€13,600", "€8,400"],
                  ["June", "€14,700", "€8,250"]]},
        {"block": "html", "title": "A drawn box", "height": 90,
         "html": '<div style="font:16px sans-serif;color:#fff;background:#234;'
                 'padding:20px;border-radius:8px">Drawn in a frame</div>'},
    ],
}


def _turn_over(page) -> None:
    """Wait until the answer has finished: the Send button is back."""
    page.wait_for_function(
        "() => { const s = document.getElementById('stopBtn');"
        " return !s || s.hidden || getComputedStyle(s).display === 'none'; }",
        timeout=20_000)


def test_idle(screen):
    settle(screen)
    shoot(screen, "idle")


def test_cards(screen):
    _conversation(screen)
    screen.get_by_role("textbox", name="Message").fill(
        "Show it. TOOL show_on_screen " + json.dumps(CARD))
    screen.get_by_role("button", name="Send message").click()
    screen.get_by_text("Quarter at a glance").first.wait_for()
    _turn_over(screen)
    screen.frame_locator("iframe.html-frame").first.get_by_text("Drawn in a frame").wait_for()
    settle(screen, 1200)
    shoot(screen, "cards")


def test_task_browser(screen):
    screen.goto(_base(screen) + "/tasks")
    # The browser is drawn into a frame over the canvas.
    screen.frame_locator("iframe[srcdoc]").first.get_by_text("The rail", exact=True) \
        .first.wait_for()
    settle(screen)
    shoot(screen, "task-browser")


def test_task_list_toggled(screen):
    """The navigation the other way from how the page opens: open, at both
    widths, since the orb's circle is the menu button at a desk too
    (12 October 2026) and grows into the row at its foot."""
    screen.get_by_role("button", name="Open menu").click()
    settle(screen, 900)
    shoot(screen, "task-list-toggled")


def test_transcript_with_canvas(screen):
    """A conversation in the transcript, and the canvas beside it at a desk or
    switched to on a phone: the transcript open and closed. At a desk a chat
    with no cards of its own opens with the chat alone: the Canvas rail at
    the right opens the canvas, and the chat's own Hide puts it away."""
    _conversation(screen)
    screen.get_by_role("textbox", name="Message").fill("Hello there")
    screen.get_by_role("button", name="Send message").click()
    screen.locator("#transcript").get_by_text("Hello there").first.wait_for()
    _turn_over(screen)
    settle(screen, 900)
    shoot(screen, "transcript")
    if screen.screen_width == "phone":
        screen.locator("#canvasToggle").click()
        settle(screen, 900)
        shoot(screen, "transcript-closed")
    else:
        screen.get_by_role("button", name="Show the canvas", exact=True).click()
        settle(screen, 900)
        shoot(screen, "transcript-canvas")
        screen.get_by_role("button", name="Hide the chat", exact=True).click()
        settle(screen, 900)
        shoot(screen, "transcript-closed")


def test_orb_full_screen(screen):
    # The circle is the menu button at both widths, and held it is the orb.
    circle = screen.get_by_role("button", name="Open menu").bounding_box()
    screen.mouse.move(circle["x"] + circle["width"] / 2, circle["y"] + circle["height"] / 2)
    screen.mouse.down()
    screen.wait_for_timeout(700)
    screen.mouse.up()
    screen.get_by_role("button", name="Put the orb back in its corner").wait_for()
    settle(screen, 900)
    shoot(screen, "orb-open")


def test_synapse(screen):
    _nav(screen, "Memory", "Synapse")
    # Synapse Master is made in the background on the first visit; the card
    # with its name is the screen finished.
    screen.locator(".syn-ds-name", has_text="Synapse Master").filter(visible=True) \
        .first.wait_for()
    # Its tasks are synced into it in the background: wait for the queue to
    # empty, and mask the counts, which say how far that has got.
    for _ in range(2):
        screen.wait_for_function("() => !document.querySelector('.syn-ds-filling')",
                                 timeout=60_000)
        settle(screen, 2500)
    shoot(screen, "synapse", mask=(".syn-ds-counts",))


def test_brief(screen):
    _nav(screen, "Now", "Morning brief")
    # Opening it never makes one (fr_e7c51081dc50): the first of the two widths
    # finds none in the world, and makes it with Update, as the person would.
    none = screen.get_by_text("No morning brief has been made yet").filter(visible=True).first
    made = screen.get_by_text("No location is set").filter(visible=True).first
    none.or_(made).wait_for(timeout=20_000)
    if none.is_visible():
        screen.get_by_role("button", name="Update", exact=True).click()
        # Not drawn pressed or under the pointer, so both widths look alike.
        screen.mouse.move(5, 500)
        screen.evaluate("() => document.activeElement && document.activeElement.blur()")
    made.wait_for(timeout=60_000)
    settle(screen, 900)
    # The date and the minute it was made are the server's own today, so both
    # are masked. The date is also given the day the baselines were taken: at
    # a phone's width "Mon, 5 Oct" wraps to two lines beside Print and "Thu, 8
    # Oct" does not, and a mask hides the words but not the page moving down.
    screen.evaluate("""() => { document.getElementById('briefTitle').innerHTML =
        '<span class="bf-day-long">Monday</span><span class="bf-day-short">Mon</span>, 5 Oct'; }""")
    shoot(screen, "brief", mask=("#briefTitle", "#briefMeta"))


def test_mail_case(screen):
    screen.goto(_base(screen) + "/mail/case/visual-case")
    # Inside Rouh, in the Approvals layer, since 15 October 2026: the case's
    # one page, the server's, in a frame, with its asks at the top drawn by
    # `mailcasepage.js` (MAIL.md D26).
    case = screen.frame_locator("#caseFrame")
    case.locator("h1").get_by_text("Sam Rivera").first.wait_for()
    # Drawn, and with no asks on this case, put away (MAIL.md D26).
    case.locator("#caseAsks .mc-page").wait_for(state="attached")
    settle(screen)
    shoot(screen, "mail-case")


def _nav(page, group: str, name: str) -> None:
    """A link of the navigation, pressed as the person would: its group's box
    in the rail first (GENES.md), then the link. The navigation is behind the
    orb's circle at both widths, and on a phone what it opens is on the
    canvas, which is the other pane."""
    phone = page.viewport_size["width"] < 900
    page.get_by_role("button", name="Open menu").click()
    page.get_by_role("tab", name=re.compile("^" + group)).click()
    # The sidebar's places are links, so Cmd-click opens them in a new tab.
    # A lab's name goes on with its tag, "Synapse Lab".
    page.get_by_role("tabpanel").get_by_role("link", name=re.compile("^" + re.escape(name) + r"\b")).click()
    if not phone:
        return
    toggle = page.get_by_role("button", name="Open the canvas, which has something on it")
    try:
        toggle.wait_for(timeout=3000)
    except Exception:
        return          # it opened over the conversation by itself
    toggle.click()


def _conversation(page) -> None:
    """The fixed General chat, rather than a draft named in the background."""
    from tests.e2e import conftest as harness

    page.goto(_base(page) + "/chat/conversation")
    page.wait_for_selector("#input")
    harness.wait_until_live(page)


def _base(page) -> str:
    return "/".join(page.url.split("/")[:3])
