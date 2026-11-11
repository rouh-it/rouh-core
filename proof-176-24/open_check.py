"""Opens the sign-in link a wizard transcript printed, in headless Chromium, as the owner would on
their phone or laptop; checks that General shows Rouh's greeting, answers a first message, and that
the link works once. Screenshots at phone and desk width. Task 176, step 176-24 (proof)."""
import re, sys
from playwright.sync_api import sync_playwright

transcript, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
text = re.sub(r"\x1b\[[0-9;]*m", "", open(transcript, encoding="utf-8", errors="replace").read())
links = re.findall(r"(https?://[^\s]+/(?:phone/in|setup)\?code=[A-Za-z0-9_-]+)", text)
assert links, "the wizard printed no sign-in link"
link = links[-1]
print("link:", re.sub(r"code=.*", "code=<hidden>", link))
with sync_playwright() as p:
    b = p.chromium.launch()
    for width, height, tag in ((390, 844, "phone"), (1440, 900, "desk")):
        ctx = b.new_context(viewport={"width": width, "height": height})
        pg = ctx.new_page()
        if tag == "phone":
            pg.goto(link, wait_until="networkidle", timeout=90000)
            print("landed on", pg.url)
            pg.get_by_text("I will be your Rouh").first.wait_for(timeout=60000)
            print("greeting:", pg.get_by_text("I will be your Rouh").first.inner_text()[:200])
            cookies = ctx.cookies()
            pg.screenshot(path=f"{out}/{name}-general-{tag}.png")
            box = pg.get_by_role("textbox", name="Message")
            box.fill("Gmail please. How do I start?")
            pg.get_by_role("button", name="Send message").click()
            pg.get_by_text("Gmail please. How do I start?").first.wait_for(timeout=30000)
            pg.wait_for_timeout(8000)
            pg.screenshot(path=f"{out}/{name}-answered-{tag}.png")
            again = b.new_context().new_page()
            again.goto(link, wait_until="networkidle", timeout=60000)
            print("the same link again lands on:", again.url, "| signed in:", "I will be your Rouh" in again.content())
        else:
            ctx.add_cookies(cookies)
            pg.goto(link.split("/setup")[0].split("/phone/in")[0] + "/", wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(3000)
            pg.screenshot(path=f"{out}/{name}-general-{tag}.png")
    b.close()
