"""What demo mode looks like: the style and the first script every page of Rouh carries in its head
(`rouh/demo.py`, app/demo.js).

Petar, 28 October 2026, on how it is done: "just make sure css loads first, and I can freely open
new tabs and the loading won't mess up, also if I do refresh. also if internet stops midway". So
the blurring is the browser's, and it is in the page itself, before anything else:

- **The style is inline in the head**, never a file of its own, so nothing is drawn before it is
  there: the shell's (`index.html`, through `head`) and every workspace page's in a frame
  (`frame_head`). The service worker keeps the shell whole, so a page opened with no connection
  carries it too.
- **The first script decides before the first paint.** It reads this browser's last word
  (localStorage) and the server's cookie (`rouh_demo`, or `rouh_demo_preview` for the preview)
  and puts `demo` on `<html>` when either says so. The page asks the server after that, and only
  the server takes it off (app/demo.js).
- **Everything is redacted unless it is the interface or approved.** Under `html.demo` every
  element is drawn in Rouh Redact (`rouh/static/demo-redact.woff2`, made by
  tools/demo-font/make.py), where every character is the same rounded bar of the same width,
  so all that is left of a word is its length; and the bars are softened into a smudge with a
  shadow in the text's own colour at low contrast, the letters themselves transparent. A blur
  alone keeps enough to be read back by a model trained on it; bars have nothing in them to
  read. What stays sharp is a short list of the interface's own parts (`INTERFACE`) and
  whatever carries `data-demo-ok`, which the page puts on what was approved. Anything new is
  redacted until somebody says otherwise.
- **Until the font has loaded, nothing redacted is drawn at all** (no `demo-font` on `<html>`
  yet): no fallback font can show a real letter for one frame. It is a data URI, so it is there
  as soon as the style is.
- **Pictures, videos, canvases and embedded documents** become a plain grey box of their own
  size: a blur of a picture can be undone as well as a blur of letters can.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

FONT = Path(__file__).resolve().parent / "static" / "demo-redact.woff2"

#: The interface: what stays sharp in demo mode. Rouh's own page, and the pages it draws in
#: frames (the task browser, a task's page). Never a list that holds the person's words: a
#: button that is a task's name, a chip that is a project's name, a row of a list.
INTERFACE = ", ".join("""
[data-ui]
nav.sidebar .sb-head
.sb-tool
.sb-nav-tab
.sb-row
.sb-tabs
.navgroup
#composer .composer-tools
#composer button
#input
.chat-head button
.chat-tabs
.panel-head
.panel-rail
.canvas-bar button
.crumb-act
.menu
.demo-menu
.demo-said
.orb-layer
.role
.msg-role
.who
.turnline
.turn-line
.msg-tools
.msg-acts
.setting-card > h2
.setting-card > h3
.setting-card label
.setting-card .hint
.settings-nav
.anatomy-nav
kbd
button:not(.row):not(.tw):not(.cat):not(.chip):not(.side)
[role="tab"]
[role="menuitem"]
[role="toolbar"] > button
svg
label
legend
th
dt
summary
.searchline
.status
.chip.all
.chip.archive
.chip.others
.chip.wait
.chip.goals
.chip.demo
.side
.num
.snum
.nslot
.scount
.tw
.racts
.dots
.pin
.tmark
.c
.lab .eye
.lab .unlab
.back
.brand
.sb-row-name
.turn-who
.turn-note
.tl-tiers
.tcrumb-chip.home
.settings-help
.settings-note
.setting-part > h5
.setting-card > h4
.field > label
.anatomy-name
.anatomy-about
.share-help
.web-keep
.hint
#projectsEmpty
h2.divider
.sgo
.okind
.owhen
.ometa-cell
.sholds
.opin-w
.menu-head
.schev
.bf-h
.bf-joke-setup
.bf-joke-punch
.bf-joke-src
.bf-sec.bf-world
.bf-sec.bf-ai
.bf-sec.bf-history
""".split("\n")[1:-1])

#: The person's own words inside a part of the interface, redacted all the same: their name on
#: the account button, a task's name in the breadcrumb, a chat's name over its conversation.
CONTENT = ", ".join("""
.sb-account-name
.sb-avatar
.crumb-project-name
.tcrumb-chip:not(.home)
#streamTitle
.chat-title
.tname
.stitle
.oname
.settings-help code
.settings-help b
.settings-help strong
#briefView button:not(.bf-btn):not(.bf-settings):not(.bf-gear):not(.bf-gene-pick):not(.layer-x):not(.bf-slack-x):not(.bf-topic-x):not(.bf-bd-change):not(:is(.bf-world, .bf-ai, .bf-history) *)
button [class*="title"]:not(.menu-name)
button [class*="subject"]
""".split("\n")[1:-1])

#: Media of the person's own: a grey box of the same size. The orb is Rouh's.
MEDIA = "img, video, canvas:not(#orb), picture, object, embed, iframe[src$='.pdf']"


@lru_cache(maxsize=1)
def font_uri() -> str:
    try:
        return "data:font/woff2;base64," + base64.b64encode(FONT.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _not_shown() -> str:
    """Everything that is neither the interface nor approved."""
    return (f":not({INTERFACE}):not(:is({INTERFACE}) *)"
            ":not([data-demo-ok]):not([data-demo-ok] *)")


@lru_cache(maxsize=1)
def style() -> str:
    hidden = _not_shown()
    return (
        "<style id=\"demoStyle\">/* Demo mode (rouh/demo_style.py). */"
        f"@font-face{{font-family:\"Rouh Redact\";src:url({font_uri()}) format(\"woff2\");"
        "font-display:block}"
        # Every word that is not the interface's: the same bar for every character, its own
        # colour at low contrast, softened into a smudge, never selectable.
        f"html.demo body {hidden}, html.demo body{hidden}{{"
        "font-family:\"Rouh Redact\"!important;letter-spacing:0!important;word-spacing:0!important;"
        "font-variant-ligatures:none!important;font-feature-settings:normal!important;"
        "-webkit-text-fill-color:transparent!important;caret-color:transparent!important;"
        "text-shadow:0 0 .42em color-mix(in srgb,currentColor 42%,transparent)!important;"
        "-webkit-user-select:none!important;user-select:none!important}"
        # The person's own words inside a part of the interface.
        f"html.demo body :is({CONTENT}):not([data-demo-ok]):not([data-demo-ok] *),"
        f"html.demo body :is({CONTENT}) *:not([data-demo-ok] *){{"
        "font-family:\"Rouh Redact\"!important;letter-spacing:0!important;"
        "-webkit-text-fill-color:transparent!important;"
        "text-shadow:0 0 .42em color-mix(in srgb,currentColor 42%,transparent)!important;"
        "-webkit-user-select:none!important;user-select:none!important}"
        f"html.demo:not(.demo-font) body :is({CONTENT}){{text-shadow:none!important}}"
        # Until the font is in, nothing redacted is drawn at all.
        f"html.demo:not(.demo-font) body {hidden}{{text-shadow:none!important}}"
        f"html.demo body {hidden}::placeholder{{color:transparent!important;"
        "-webkit-text-fill-color:transparent!important;text-shadow:none!important}"
        # Words drawn inside a picture of Rouh's own kind (a chart's labels): not shown.
        "html.demo body svg :is(text,tspan):not([data-demo-ok] *){visibility:hidden!important}"
        # The interface keeps its own face, wherever it sits.
        f"html.demo :where({INTERFACE}, [data-demo-ok]){{"
        "font-family:var(--demo-ui-font,var(--sans,-apple-system,BlinkMacSystemFont,\"Segoe UI\","
        "Roboto,sans-serif));-webkit-text-fill-color:currentColor;text-shadow:none;"
        "-webkit-user-select:auto;user-select:auto}"
        # Pictures, video, canvases and documents: a grey box of their own size.
        f"html.demo body :is({MEDIA}){hidden}{{filter:contrast(0) brightness(.9)!important;"
        "background:#7c838f!important;opacity:.32!important;-webkit-user-drag:none}"
        # A background picture in the person's content goes too.
        f"html.demo body [style*=\"background-image\"]{hidden}{{background-image:none!important}}"
        "</style>")


#: The first script: demo mode on `<html>` before anything is drawn, from this browser's last
#: word or the server's cookie; and the font's arrival, which lets the bars be drawn.
HEAD_SCRIPT = (
    "<script>/* Demo mode (rouh/demo_style.py): before the first paint. */(function(){"
    "var d=document.documentElement,on=false;"
    "try{on=localStorage.getItem('rouh.demo')==='1'}catch(e){}"
    "try{if(/(?:^|;\\s*)rouh_demo(?:_preview)?=1/.test(document.cookie||''))on=true}catch(e){}"
    "if(on){d.classList.add('demo');if(document.title.indexOf('Rouh')!==0)document.title='Rouh'}"
    "function ready(){d.classList.add('demo-font')}"
    "try{document.fonts.load('16px \"Rouh Redact\"','x').then(ready,ready)}catch(e){ready()}"
    "})();</script>")


def head() -> str:
    """What the shell's head carries, first."""
    return style() + HEAD_SCRIPT


#: In a frame: a page Rouh hands over in demo mode is always in demo mode (it has no storage
#: or cookie of its own to read), and is approved whole when its task was.
_FRAME_SCRIPT = (
    "<script>/* Demo mode (rouh/demo_style.py), put in by Rouh. */(function(){"
    "var d=document.documentElement;d.classList.add('demo');%s"
    "function ready(){d.classList.add('demo-font')}"
    "try{document.fonts.load('16px \"Rouh Redact\"','x').then(ready,ready)}catch(e){ready()}"
    "function plain(){if(document.title!=='Rouh')document.title='Rouh';"
    "if(!d.hasAttribute('data-demo-ok')){var t=document.querySelectorAll('[title]');"
    "for(var i=0;i<t.length;i++){t[i].setAttribute('data-demo-title','');t[i].removeAttribute('title')}"
    "var f=document.querySelectorAll('input,textarea,form');"
    "for(var j=0;j<f.length;j++)f[j].setAttribute('autocomplete','off')}}"
    # A task's or a step's own page: Show in demo beside its pin, one press to show it to the
    # audience as it is now, another to hide it again (`rouh/demo.py`).
    "function eye(){var pin=document.getElementById('tkPin'),n=%s;"
    "if(!pin||!n||document.getElementById('tkDemo'))return;var on=d.hasAttribute('data-demo-ok');"
    "var b=document.createElement('button');b.type='button';b.id='tkDemo';b.className='opin';"
    "b.setAttribute('data-ui','');b.setAttribute('aria-pressed',on?'true':'false');"
    "b.innerHTML='<svg viewBox=\"0 0 24 24\" width=\"16\" height=\"16\" aria-hidden=\"true\" fill=\"none\" "
    "stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">"
    "<path d=\"M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z\"/>"
    "<circle cx=\"12\" cy=\"12\" r=\"2.8\"/>'+(on?'':'<path d=\"M4 20L20 4\"/>')+'</svg>"
    "<span class=\"opin-w\">'+(on?'Shown in demo':'Show in demo')+'</span>';"
    "if(on)b.style.color='#b57bff';"
    "b.addEventListener('click',function(){b.disabled=true;try{parent.postMessage({type:'rouh-page-demo',"
    "act:on?'unapprove':'approve',kind:n.indexOf('-')>0?'step':'task',ref:n},'*')}catch(e){}});"
    "pin.parentNode.insertBefore(b,pin)}"
    "document.addEventListener('DOMContentLoaded',function(){plain();eye();"
    "new MutationObserver(plain).observe(document.documentElement,{subtree:true,childList:true,"
    "attributes:true,attributeFilter:['title']})});"
    "})();</script>")


def frame_head(approved: bool, number: str = "") -> str:
    """`number` is the task's or step's own when the page is one: its Show in demo button."""
    safe = number if number.replace("-", "").isdigit() else ""
    return style() + (_FRAME_SCRIPT % ("d.setAttribute('data-demo-ok','');" if approved else "",
                                       f"'{safe}'" if safe else "''"))
