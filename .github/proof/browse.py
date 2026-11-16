"""Sign in through the real form and read Anatomy, Meta, Changes over Playwright MCP.

    browse.py URL PASSWORD OUT PHASE WORD...   every WORD must be on the page (a leading ! must not)
"""
import asyncio, os, sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.sync_api import sync_playwright

url, password, out, phase, *words = sys.argv[1:]
with sync_playwright() as p:
    exe = p.chromium.executable_path
log = []

async def drive():
    params = StdioServerParameters(command=os.environ["STACK_PLAYWRIGHT_MCP"],
                                   args=["--headless", "--isolated", "--browser=chromium", "--executable-path=" + exe])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            async def call(name, **a):
                res = await s.call_tool(name, a)
                text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
                log.append(f"## {name} {a}\n{text}")
                if res.is_error or "### Error" in text:
                    raise SystemExit(f"{name}: {text[-800:]}")
                return text
            await call("browser_navigate", url=url + "/login")
            await call("browser_type", target="#email", text="alex@example.com")
            await call("browser_click", target="#continueBtn")
            page = await call("browser_snapshot")
            mail = "Check your email" in page
            if mail:
                await call("browser_click", target="text=Can't get the email?")
            await call("browser_type", target="#password", text=password)
            await call("browser_click", target="button:text-is('Sign in with password')" if mail else "button:text-is('Sign in')")
            await call("browser_wait_for", time=3)
            await call("browser_navigate", url=url + "/anatomy/meta/changes")
            await call("browser_wait_for", time=6)
            page = await call("browser_snapshot")
            shot = Path.cwd() / ".playwright-mcp" / f"changes-{phase}.png"
            await call("browser_take_screenshot", filename=str(shot), fullPage=True)
            Path(out, shot.name).write_bytes(shot.read_bytes())
            missing = [x for x in words if (x[1:] in page) if x.startswith("!")] + \
                      [x for x in words if not x.startswith("!") and x not in page]
            if missing:
                raise SystemExit(f"{phase}: Meta, Changes did not match {missing}")
            print(f"browse {phase}: Meta, Changes shows " + ", ".join(words))

try:
    asyncio.run(drive())
finally:
    Path(out, f"browse-{phase}.txt").write_text("\n\n".join(log))
