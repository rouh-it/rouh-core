#!/usr/bin/env python3
"""The record of a design, kept in a checkout of Rouh's code while a screen is built.

Every change that a person sees follows one design standard (`rouh/design_standard.py`, task 169):
journeys first, one direction, the guide read at run time, a self-check at 1440 and 390 px, and on
the full tier critic rounds until no blocker is left. This tool writes what was done into
`.design/record.json` in the checkout (never committed: `/.design/` is in .gitignore), and
`land.sh` reads it (`design_guard`) before it pushes a change to the screen.

    python3 tools/design/record.py skill                        where the design skill is, and the guide
    python3 tools/design/record.py start --tier full|small --what "what is built"
    python3 tools/design/record.py journey "Decide a problem" --target "1 click, 5 s" --met --how "..."
    python3 tools/design/record.py designs <step>/designs       shoot.mjs on the prototype (full tier)
    python3 tools/design/record.py critic --round 1 --blockers 3 [--report path]
    python3 tools/design/record.py screens --url http://127.0.0.1:PORT --user U --password P / /evolution/trials
    python3 tools/design/record.py cost --usd 12.40              what the run cost, when it is known
    python3 tools/design/record.py show

`screens` needs Playwright (`.venv-e2e/bin/python tools/design/record.py screens ...`); the rest is
the standard library. It checks the real screens, signed in, with the same faults as the skill's
`shoot.mjs`, which checks only files: sideways scrolling, text cut off at its box's edge, a fixed
panel covering the page, a page that draws almost nothing, script errors, broken images, and
requests to other sites. Each fault blocks the landing until it is fixed and the check is run again.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from rouh import design_standard as ds  # noqa: E402 - the standard library only

RECORD = ROOT / ".design" / "record.json"
SHOTS = ROOT / ".design" / "shots"

#: The two widths and the two themes every screen is looked at in.
SIZES = (("desk", 1440, 900), ("phone", 390, 844))
SCHEMES = ("dark", "light")

#: The same checks as the skill's shoot.mjs, run inside the page. Rouh's own words and code
#: (task 169, steps 169-04 and 169-05), so they can live in Rouh's public code.
CHECK_JS = r"""() => {
  const W = window.innerWidth, H = window.innerHeight;
  const shown = e => { const cs = getComputedStyle(e); return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity > 0.05; };
  const label = e => (e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/)[0] : '')) + ' "' + (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 30) + '"';
  const scrolls = a => { for (; a && a !== document.body; a = a.parentElement) { if (/^(auto|scroll)$/.test(getComputedStyle(a).overflowX)) return true; } return false; };
  const cut = [];
  for (const e of document.body.querySelectorAll('*')) {
    if (cut.length >= 6) break;
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own || !shown(e)) continue;
    const r = e.getBoundingClientRect(); if (r.width <= 2 || r.height <= 2) continue;
    const cs = getComputedStyle(e);
    if (cs.clip !== 'auto' || /inset\(50%\)/.test(cs.clipPath)) continue;
    if (cs.textOverflow === 'ellipsis' || /^(auto|scroll)$/.test(cs.overflowX) || /^(auto|scroll)$/.test(cs.overflowY)) continue;
    if (['INPUT', 'TEXTAREA', 'SELECT', 'OPTION'].includes(e.tagName)) continue;
    // Where the element's own text really is, so a larger touch area drawn by a pseudo-element
    // (::after with a negative inset, as the guide's 44 px targets ask) is not taken for cut text.
    const rg = document.createRange(); let tl = 1e9, tr = -1e9, tb = -1e9;
    for (const n of e.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { rg.selectNodeContents(n); for (const q of rg.getClientRects()) { tl = Math.min(tl, q.left); tr = Math.max(tr, q.right); tb = Math.max(tb, q.bottom); } }
    const wide = e.scrollWidth > e.clientWidth + 2 && e.clientWidth > 0 && (tr > r.right + 2 || tl < r.left - 2);
    const tall = /hidden|clip/.test(cs.overflowY) && e.scrollHeight > e.clientHeight + 2 && e.clientHeight > 0 && !(+cs.webkitLineClamp > 0) && tb > r.bottom + 2;
    if (wide || tall) cut.push(label(e) + (wide ? ` ${e.scrollWidth - e.clientWidth}px wider` : '') + (tall ? ` ${e.scrollHeight - e.clientHeight}px taller` : '') + ' than its box');
    else if (r.right > W + 1 && r.left < W && !scrolls(e.parentElement)) cut.push(label(e) + ' runs past the right edge of the screen');
  }
  let ink = 0, chars = 0;
  for (const e of document.body.querySelectorAll('*')) {
    if (!shown(e)) continue;
    const r = e.getBoundingClientRect(); if (r.bottom < 0 || r.top > H || !r.width || !r.height) continue;
    if (['IMG', 'SVG', 'CANVAS', 'VIDEO', 'svg'].includes(e.tagName)) ink += Math.min(r.width, W) * Math.min(r.height, H);
    for (const n of e.childNodes) if (n.nodeType === 3) chars += n.textContent.trim().length;
  }
  const covers = [];
  for (const e of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(e); if (cs.position !== 'fixed' || !shown(e) || cs.pointerEvents === 'none') continue;
    const r = e.getBoundingClientRect();
    const area = Math.max(0, Math.min(r.right, W) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, H) - Math.max(r.top, 0));
    if (area > W * H * 0.25) covers.push(label(e) + ` covers ${Math.round(100 * area / (W * H))}% of the screen`);
  }
  return {
    sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
    broken: [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.getAttribute('src')).map(i => i.getAttribute('src')),
    cut, empty: chars < 40 && ink < W * H * 0.05, chars, covers,
  };
}"""


def load() -> dict:
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(rec: dict) -> None:
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    (RECORD.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    RECORD.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def need(rec: dict) -> dict:
    if not rec.get("tier"):
        sys.exit("No design is started here: run `record.py start --tier full|small --what ...` first.")
    return rec


def cmd_skill(_a) -> int:
    found = ds.find_skill()
    print(ds.skill_report(found))
    return 0


def cmd_start(a) -> int:
    rec = {"tier": a.tier, "what": a.what, "started": time.time(), "journeys": [], "designs": [],
           "critic": [], "screens": {}, "files": {}, "cost_usd": None}
    found = ds.find_skill()
    rec["skill"] = str(found["path"]) if found["path"] else ""
    rec["guide"] = "private" if found["guide"] else "fallback"
    save(rec)
    print(f"Started a {a.tier} design: {a.what}")
    print(ds.skill_report(found))
    return 0


def cmd_journey(a) -> int:
    rec = need(load())
    rec["journeys"] = [j for j in rec["journeys"] if j["name"] != a.name]
    rec["journeys"].append({"name": a.name, "target": a.target, "met": bool(a.met), "how": a.how})
    save(rec)
    print(f"Journey \"{a.name}\": {'met' if a.met else 'MISSED'} ({a.target}).")
    return 0


def cmd_designs(a) -> int:
    rec = need(load())
    found = ds.find_skill()
    if not found["path"] or not (found["path"] / "shoot.mjs").is_file():
        sys.exit("shoot.mjs was not found (record.py skill says where it looked).")
    env = dict(os.environ)
    nm = _node_modules()
    if nm:
        env["NODE_PATH"] = nm
    shoot = found["path"] / "shoot.mjs"
    # Node finds an ES module's packages from the module's own folder, not NODE_PATH, so the check
    # runs from a copy beside a node_modules that holds playwright.
    run_from = shoot
    if nm:
        stage = ROOT / ".design" / "shoot"
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "shoot.mjs").write_bytes(shoot.read_bytes())
        if (found["path"] / "fonts.conf").is_file():
            (stage / "fonts.conf").write_bytes((found["path"] / "fonts.conf").read_bytes())
        link = stage / "node_modules"
        if not link.exists():
            link.symlink_to(nm)
        run_from = stage / "shoot.mjs"
    out = ROOT / ".design" / "shots" / "designs"
    got = subprocess.run(["node", str(run_from), str(Path(a.folder).resolve()), str(out)],
                         capture_output=True, text=True, env=env)
    said = (got.stdout + got.stderr).strip()
    print(said)
    fails = [ln.strip() for ln in said.splitlines() if ln.startswith("FAIL") or ln.startswith("     ")]
    rec["designs"].append({"folder": str(a.folder), "at": time.time(), "ok": got.returncode == 0,
                           "faults": fails[:40], "widths": [1440, 390]})
    save(rec)
    return got.returncode


def _node_modules() -> str:
    """A node_modules that holds playwright: the one npx keeps for Playwright MCP, or one beside us."""
    for p in [ROOT / "node_modules", *sorted(Path.home().glob(".npm/_npx/*/node_modules"))]:
        if (p / "playwright").is_dir():
            return str(p)
    return ""


def cmd_critic(a) -> int:
    rec = need(load())
    rec["critic"] = [c for c in rec["critic"] if c["round"] != a.round]
    rec["critic"].append({"round": a.round, "blockers": a.blockers, "report": a.report or "", "at": time.time()})
    rec["critic"].sort(key=lambda c: c["round"])
    save(rec)
    print(f"Critic round {a.round}: {a.blockers} blocker(s).")
    return 0


def cmd_cost(a) -> int:
    rec = need(load())
    rec["cost_usd"] = a.usd
    save(rec)
    print(f"Cost: ${a.usd:.2f}")
    return 0


def cmd_screens(a) -> int:
    rec = need(load())
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("screens needs Playwright: run it with .venv-e2e/bin/python (./e2e.sh makes it).")
    base = a.url.rstrip("/")
    SHOTS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    found = ds.find_skill()
    conf = (found["path"] / "fonts.conf") if found["path"] else None
    if conf and conf.is_file() and sys.platform.startswith("linux"):
        env.setdefault("FONTCONFIG_FILE", str(conf))
    results, total = {}, 0
    with sync_playwright() as p:
        browser = p.chromium.launch(env=env)
        for scheme in SCHEMES:
            for size, w, h in SIZES:
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme,
                                          device_scale_factor=2 if size == "phone" else 1)
                page = ctx.new_page()
                if a.user:
                    _sign_in(page, base, a.user, a.password)
                for path in a.paths:
                    errors, outside = [], []
                    on_console = (lambda m: errors.append(m.text) if m.type == "error" else None)
                    on_error = (lambda e: errors.append(str(e)))
                    on_request = (lambda r: outside.append(r.url) if _outside(r.url, base) else None)
                    page.on("console", on_console)
                    page.on("pageerror", on_error)
                    page.on("request", on_request)
                    page.goto(base + path, wait_until="load")
                    page.wait_for_timeout(a.settle)
                    got = page.evaluate(CHECK_JS)
                    page.remove_listener("console", on_console)
                    page.remove_listener("pageerror", on_error)
                    page.remove_listener("request", on_request)
                    tag = f"{_slug(path)}-{scheme}-{size}"
                    shot = SHOTS / f"{tag}.png"
                    page.screenshot(path=str(shot), full_page=False)
                    faults = []
                    if got["sideways"]:
                        faults.append("scrolls sideways")
                    if got["broken"]:
                        faults.append("broken images: " + ", ".join(got["broken"][:5]))
                    errors = [e for e in errors if not _ignorable(e)]
                    if errors:
                        faults.append("script errors: " + " | ".join(errors[:3])[:400])
                    if outside:
                        faults.append("requests to other sites: " + ", ".join(sorted(set(outside))[:5]))
                    if got["cut"]:
                        faults.append("text cut off: " + " | ".join(got["cut"]))
                    if got["empty"]:
                        faults.append(f"draws almost nothing on its first screen ({got['chars']} characters)")
                    if got["covers"]:
                        faults.append("fixed panel over the page: " + " | ".join(got["covers"]))
                    total += len(faults)
                    results.setdefault(path, {})[f"{scheme}-{size}"] = {"faults": faults, "shot": str(shot.relative_to(ROOT))}
                    print(f"{'FAIL' if faults else 'ok  '} {path} {scheme} {size} ({w} px) -> {shot.relative_to(ROOT)}"
                          + ("".join("\n     " + f for f in faults)))
                ctx.close()
        browser.close()
    rec["screens"] = {"at": time.time(), "url": base, "pages": results, "faults": total}
    rec["files"] = ds.blobs_now(ROOT, ds.screen_files(ROOT, a.since))
    save(rec)
    print(f"{total} fault(s) on {len(a.paths)} screen(s) at 1440 and 390 px, dark and light."
          + ("" if total else " Now look at every screenshot yourself."))
    return 1 if total else 0


def _sign_in(page, base: str, user: str, password: str) -> None:
    """Sign in as a person would: the address first, then the password, whichever form it is."""
    page.goto(base + "/login", wait_until="load")
    who = page.locator("input#email, input[name=username], input[name=email]").first
    who.fill(user)
    pw = page.locator("input[type=password]")
    if not pw.count() or not pw.first.is_visible():
        page.locator("button[type=submit]").first.click()
        pw.first.wait_for(state="visible", timeout=15000)
    pw.first.fill(password)
    page.locator("button[type=submit]:visible").first.click()
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)


def _outside(url: str, base: str) -> bool:
    return not (url.startswith(base) or url.startswith("data:") or url.startswith("blob:")
                or url.startswith("about:") or url.startswith("ws://127.0.0.1") or url.startswith("http://127.0.0.1"))


def _ignorable(text: str) -> bool:
    """A test world has no model and no network: what it says about that is not the screen's fault."""
    return any(s in text for s in ("net::ERR_", "Failed to load resource", "WebSocket"))


def _slug(path: str) -> str:
    s = "".join(c if c.isalnum() else "-" for c in path.strip("/")) or "home"
    return s.strip("-")[:60] or "home"


def cmd_show(_a) -> int:
    rec = load()
    if not rec:
        print("No design record here.")
        return 0
    print(ds.summary(rec))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("skill").set_defaults(fn=cmd_skill)
    s = sub.add_parser("start")
    s.add_argument("--tier", choices=ds.TIERS, required=True)
    s.add_argument("--what", required=True)
    s.set_defaults(fn=cmd_start)
    s = sub.add_parser("journey")
    s.add_argument("name")
    s.add_argument("--target", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--met", action="store_true")
    g.add_argument("--missed", action="store_true")
    s.add_argument("--how", default="")
    s.set_defaults(fn=cmd_journey)
    s = sub.add_parser("designs")
    s.add_argument("folder")
    s.set_defaults(fn=cmd_designs)
    s = sub.add_parser("critic")
    s.add_argument("--round", type=int, required=True)
    s.add_argument("--blockers", type=int, required=True)
    s.add_argument("--report", default="")
    s.set_defaults(fn=cmd_critic)
    s = sub.add_parser("cost")
    s.add_argument("--usd", type=float, required=True)
    s.set_defaults(fn=cmd_cost)
    s = sub.add_parser("screens")
    s.add_argument("--url", required=True)
    s.add_argument("--user", default="")
    s.add_argument("--password", default="")
    s.add_argument("--settle", type=int, default=1500, help="milliseconds to wait after a page loads")
    s.add_argument("--since", default="origin/main", help="what the screen files are compared with")
    s.add_argument("paths", nargs="+")
    s.set_defaults(fn=cmd_screens)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
