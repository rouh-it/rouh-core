/* Listen to this page: the page told as a narration that walks the listener
 * through it, in Rouh's voice (rouh/page_listen.py, the gene page_listen).
 *
 * Petar, 27 October 2026 (mutation request 6): "listen shouldn't be in the
 * share button, instead it should be in the tooltip with comments, highlights
 * and so on ... there are no controls, when it starts, there is no stopping
 * ... a special narration is generated that kind of walks me through this
 * content ... I should be able in listen mode to click exactly the element /
 * paragraph and start from there."
 *
 * So:
 *
 * - The speaker is a button in the floating control, beside the highlighter,
 *   and L. Pressed, the page as it is drawn now is cut into its elements, each
 *   numbered on the page (data-listen-n), and Rouh has a narration written for
 *   it: parts of one to three sentences, each tied to the elements it is about.
 *   The same page as it was is never written twice (the server keeps it).
 * - Each part is said in Rouh's own voice, asked for a part at a time, with
 *   the next two asked for while one is being said. The sound is made here,
 *   in the page, by an AudioContext made inside the press, which is what lets
 *   a phone play it.
 * - While it plays, the elements of the part being said are lit, a closed
 *   toggle they are in is opened, and they are brought into view when they
 *   are not in it. A bar at the bottom has back a part, pause and play, on a
 *   part, and stop; Escape stops too.
 * - While listening, a press on any part of the page starts the narration at
 *   the part that speaks about it, and a mouse outlines what it is over.
 *
 * Petar, the same day (mutation request 7): "I press listen and it says
 * getting page ready to listen and nothing happens for a while. Also I did it
 * multiple times. Once text is generated and voice, I shouldn't be generating
 * it again ... maybe we should have this page but page not the entire visual
 * explainer at once." So, version 3:
 *
 * - Only what is drawn now is sent: an explainer's other pages, and a tab
 *   that is not showing, are left out, so each page has its own narration.
 *   What is in a closed toggle on the page showing is still sent.
 * - The narration is written on the server whatever this page does, and its
 *   parts come back as they are written: the first is said while the rest
 *   are still to come, and this page asks again for what is ready until it
 *   has them all.
 * - Pressing Listen again on the same page plays what was written and said
 *   before: the server keeps both, and this page keeps the sound it had.
 * - Moving to another page of the explainer while listening stops it, and
 *   Listen there tells that page.
 *
 * The page is sandboxed and cannot call out, so each request goes to
 * `/api/listen`, which the page around this one carries (askRelay in Rouh's
 * cards.js), for the page's owner only.
 *
 * Vanilla, no dependencies, no build step. */
(function () {
"use strict";

var CFG = window.ASKAI_LISTEN;
if (!CFG || window.ASKAI_BAR_ONLY || window.__askaiListen) return;
var ROOT = document.getElementById("askai-root");
if (!ROOT || !document.body) return;
window.__askaiListen = true;

var API = "/api/listen";
var MOST = 700, MOST_CHARS = 60000;
var NUM = "data-listen-n";

var S = {
  on: false,
  state: "idle",       /* idle, preparing, loading, playing, paused */
  key: "", parts: [], i: 0,
  done: false,         /* whether every part of the narration is in */
  poll: 0,             /* the timer that asks for the parts still to come */
  ctx: null, src: null,
  audio: {},           /* part -> promise of its AudioBuffer */
  token: 0,            /* the one play that may still start a sound */
  from: null,          /* an element pressed before the narration came */
  lit: []
};

/* ------------------------------------------------------------------ small */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function svg(d) { return '<svg viewBox="0 0 24 24" aria-hidden="true">' + d + "</svg>"; }
var ICON = {
  speaker: svg('<path d="M4.5 9.5h3l4.5-4v13l-4.5-4h-3z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
  back: svg('<path d="M6 5.5v13"/><path d="M18 5.5v13l-9-6.5z"/>'),
  next: svg('<path d="M18 5.5v13"/><path d="M6 5.5v13l9-6.5z"/>'),
  play: svg('<path d="M8 5.5v13l10.5-6.5z"/>'),
  pause: svg('<rect x="6.5" y="5" width="3.6" height="14" rx="1"/><rect x="13.9" y="5" width="3.6" height="14" rx="1"/>'),
  stop: svg('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>')
};

/* ------------------------------------------------------------------ the page's own styles */

var sheet = document.createElement("style");
sheet.textContent =
  "[data-listen-n].askai-ls-now{background:rgba(94,194,255,.16)!important;" +
  "box-shadow:0 0 0 3px rgba(94,194,255,.16),inset 3px 0 0 rgba(94,194,255,.9)!important;" +
  "border-radius:4px;transition:background .25s,box-shadow .25s}" +
  "html.askai-listening [data-listen-n]{cursor:pointer}" +
  "html.askai-listening [data-listen-n].askai-ls-hover{outline:1.5px dashed rgba(94,194,255,.85);" +
  "outline-offset:3px;border-radius:3px}" +
  "#askai-root #askai-ls{all:initial!important;position:fixed!important;top:0!important;" +
  "left:0!important;right:0!important;bottom:0!important;z-index:2147483003!important;" +
  "pointer-events:none!important;display:block!important}";
document.head.appendChild(sheet);

/* ------------------------------------------------------------------ what is drawn over the page */

var host = document.createElement("div");
host.id = "askai-ls";
var sh = host.attachShadow({ mode: "open" });
sh.innerHTML =
  '<link rel="stylesheet" href="' + esc(CFG.css || "") + '">' +
  '<div class="ls" id="ls">' +
    '<div class="bar" id="bar" role="toolbar" aria-label="Listening" ' +
        'title="Press any part of the page to listen from there">' +
      '<button type="button" id="back" title="Back a part" aria-label="Back a part">' + ICON.back + "</button>" +
      '<button type="button" class="play" id="play" title="Pause" aria-label="Pause">' + ICON.pause + "</button>" +
      '<button type="button" id="next" title="On a part" aria-label="On a part">' + ICON.next + "</button>" +
      '<span class="words" id="words" hidden></span>' +
      '<button type="button" class="stop" id="stop" title="Stop listening (Esc)" ' +
        'aria-label="Stop listening">' + ICON.stop + "</button>" +
    "</div>" +
    '<div class="toast" id="toast" role="status"></div>' +
  "</div>";
ROOT.appendChild(host);

function $(id) { return sh.getElementById(id); }
var bar = $("bar"), playBtn = $("play"), words = $("words"), toast = $("toast");

/* The button, in the drawer's own floating bar. Where comments are on, their
   control takes that bar's place and presses this one through (comments.js,
   "mirror"), and shows what it shows. */
var float = document.getElementById("askai-float");
var btn = document.createElement("button");
btn.id = "askai-listen-btn";
btn.type = "button";
btn.className = "askai-fb";
btn.innerHTML = ICON.speaker;
btn.setAttribute("aria-pressed", "false");
if (float) {
  var after = document.getElementById("askai-mark-btn") || document.getElementById("askai-launch");
  if (after && after.nextSibling) float.insertBefore(btn, after.nextSibling);
  else float.appendChild(btn);
}

var toastTimer = 0;
function say(text) {
  toast.textContent = text;
  toast.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toast.classList.remove("on"); }, 6000);
}

function draw() {
  btn.title = S.on ? "Stop listening (L)" : "Listen to this page (L)";
  btn.setAttribute("aria-label", S.on ? "Stop listening" : "Listen to this page");
  btn.setAttribute("aria-pressed", S.on ? "true" : "false");
  btn.classList.toggle("on", S.on);
  bar.classList.toggle("on", S.on);
  document.documentElement.classList.toggle("askai-listening", S.on);
  var waiting = S.state === "preparing" || S.state === "loading";
  var playing = S.state === "playing" || waiting;
  playBtn.innerHTML = playing ? ICON.pause : ICON.play;
  playBtn.title = playing ? "Pause" : "Play";
  playBtn.setAttribute("aria-label", playBtn.title);
  playBtn.classList.toggle("wait", waiting);
  words.hidden = S.state !== "preparing";
  words.textContent = S.state === "preparing" ? "Getting the page ready…" : "";
  $("back").disabled = !S.parts.length || S.i <= 0;
  $("next").disabled = !S.parts.length || S.i >= S.parts.length - 1;
}

/* ------------------------------------------------------------------ the server */

function api(body) {
  return fetch(API, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok || !j || j.error) {
        throw new Error((j && j.error) || (r.status === 401 || r.status === 403
          ? "Your sign-in has run out. Reload the page and try again."
          : "Rouh could not read the page: it said " + r.status + "."));
      }
      return j;
    });
  }, function () {
    throw new Error("Rouh could not be reached, so the page cannot be read.");
  });
}

/* ------------------------------------------------------------------ the page, cut into its elements */

var INLINE = /^(A|ABBR|B|BDI|BDO|CITE|CODE|DATA|DFN|EM|I|KBD|MARK|Q|S|SAMP|SMALL|SPAN|STRONG|SUB|TIME|U|VAR|LABEL|FONT|DEL|INS)$/;
var SKIP_TAG = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TEXTAREA|SELECT|OPTION|BUTTON|NAV|SVG|HEAD|INPUT|SUP)$/;
/* What holds the sources, the footnote marks, a menu or the X-ray: never said. */
var SKIP_MARK = /(^|[\s_-])(sources?|footnotes?|cite|menu|hamburger|navbar|sidebar|toc|xray)($|[\s_-])/i;
var skipMemo = new WeakMap();
function skipped(el) {
  if (!el || el === document.body || el === document.documentElement) return false;
  if (skipMemo.has(el)) return skipMemo.get(el);
  var marks = (el.id || "") + " " + (typeof el.className === "string" ? el.className : "");
  var no = el === ROOT || SKIP_TAG.test(el.tagName.toUpperCase()) ||
    el.getAttribute("aria-hidden") === "true" || el.getAttribute("role") === "navigation" ||
    SKIP_MARK.test(marks) || skipped(el.parentElement);
  skipMemo.set(el, no);
  return no;
}
/* The element a run of words belongs to: the nearest that is not inline,
   and for a table's cell, its row. */
function unitOf(el) {
  while (el && el !== document.body && INLINE.test(el.tagName.toUpperCase())) el = el.parentElement;
  if (!el || el === document.body) return null;
  if (/^(TD|TH)$/.test(el.tagName)) return el.closest("tr") || el;
  return el;
}
function kindOf(el) {
  var t = el.tagName.toLowerCase();
  if (/^h[1-6]$/.test(t) || t === "p" || t === "blockquote" || t === "pre") return t;
  if (t === "li" || t === "dt" || t === "dd") return "item";
  if (t === "tr") return "row";
  if (t === "summary") return "toggle";
  if (t === "caption" || t === "figcaption") return "caption";
  return "box";
}

function outline() {
  [].forEach.call(document.querySelectorAll("[" + NUM + "]"), function (el) { el.removeAttribute(NUM); });
  var units = [], byEl = new Map(), chars = 0;
  var walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  var node;
  while ((node = walk.nextNode())) {
    if (!/\S/.test(node.data)) continue;
    var p = node.parentElement;
    if (!p || skipped(p)) continue;
    var u = unitOf(p);
    if (!u) continue;
    var one = byEl.get(u);
    if (!one) {
      if (units.length >= MOST) break;
      one = { el: u, bits: [], cell: null };
      byEl.set(u, one);
      units.push(one);
    }
    var cell = p.closest("td,th");
    if (cell && one.cell && cell !== one.cell) one.bits.push(" | ");
    if (cell) one.cell = cell;
    one.bits.push(node.data);
  }
  var out = [];
  units.forEach(function (one) {
    var text = one.bits.join("").replace(/\s+/g, " ").trim();
    if (!/\w/.test(text) || chars > MOST_CHARS) return;
    /* In a closed toggle on what is showing: told, and said to be there.
       Not drawn otherwise: on another page or tab, which is not this page. */
    var el = one.el, shown = "", shut = outerShut(el);
    if (shut) {
      if (!shut.getClientRects().length) return;
      shown = "toggle";
    } else if (!el.getClientRects().length) return;
    var n = out.length;
    chars += text.length;
    el.setAttribute(NUM, String(n));
    out.push({ n: n, kind: kindOf(el), text: text.slice(0, 1500), shown: shown });
  });
  return out;
}

/* The outermost closed toggle an element is in, or nothing. */
function outerShut(el) {
  var top = null;
  for (var d = el.parentElement && el.parentElement.closest("details:not([open])"); d;
       d = d.parentElement && d.parentElement.closest("details:not([open])")) {
    var sum = el.closest("summary");
    if (!(sum && sum.parentElement === d)) top = d;
  }
  return top;
}

/* Whether any of what is being told is still on the screen, or in a toggle
   on it: when none is, the reader has moved to another page. */
function showing() {
  var els = document.querySelectorAll("[" + NUM + "]");
  for (var k = 0; k < els.length; k++) {
    if (els[k].getClientRects().length) return true;
    var shut = outerShut(els[k]);
    if (shut && shut.getClientRects().length) return true;
  }
  return !els.length;
}

function elOf(n) { return document.querySelector("[" + NUM + '="' + n + '"]'); }

/* ------------------------------------------------------------------ the part being said, on the page */

function unlight() {
  S.lit.forEach(function (el) { el.classList.remove("askai-ls-now"); });
  S.lit = [];
}
function light(i) {
  unlight();
  var part = S.parts[i];
  if (!part) return;
  var first = null;
  (part.at || []).forEach(function (n) {
    var el = elOf(n);
    if (!el) return;
    for (var d = el.closest("details:not([open])"); d; d = d.parentElement && d.parentElement.closest("details:not([open])")) {
      d.open = true;
    }
    el.classList.add("askai-ls-now");
    S.lit.push(el);
    if (!first && el.getClientRects().length) first = el;
  });
  if (first) {
    var r = first.getBoundingClientRect(), h = window.innerHeight;
    if (r.top < 40 || r.top > h - 120) first.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

/* ------------------------------------------------------------------ the sound */

function ensureCtx() {
  if (!S.ctx) {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try { S.ctx = new AC(); } catch (e) { return null; }
  }
  if (S.ctx.state === "suspended") S.ctx.resume().catch(function () {});
  return S.ctx;
}

function bufferOf(said) {
  var raw = atob(said.pcm || ""), n = raw.length >> 1;
  var buf = S.ctx.createBuffer(1, Math.max(1, n), said.rate || 24000), out = buf.getChannelData(0);
  for (var i = 0; i < n; i++) {
    var v = raw.charCodeAt(2 * i) | (raw.charCodeAt(2 * i + 1) << 8);
    out[i] = (v >= 32768 ? v - 65536 : v) / 32768;
  }
  return buf;
}

function audioOf(i, jump) {
  if (i < 0 || i >= S.parts.length) return null;
  if (!S.audio[i]) {
    var key = S.key;
    S.audio[i] = api({ do: "say", key: key, i: i, jump: !!jump }).then(function (said) {
      return bufferOf(said);
    }, function (err) {
      if (S.key === key) delete S.audio[i];
      throw err;
    });
  }
  return S.audio[i];
}

function quiet() {
  var src = S.src;
  S.src = null;
  if (src) { try { src.onended = null; src.stop(); } catch (e) {} }
}

function play(i, jump) {
  var token = ++S.token;
  quiet();
  S.i = i;
  S.state = "loading";
  ensureCtx();
  light(i);
  draw();
  /* Not written yet: it is played when it comes (more). */
  if (i >= S.parts.length) return;
  audioOf(i, jump).then(function (buf) {
    if (token !== S.token || !S.on) return;
    var src = S.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(S.ctx.destination);
    src.onended = function () {
      if (S.src !== src) return;
      S.src = null;
      if (S.i + 1 < S.parts.length || !S.done) play(S.i + 1);
      else finish();
    };
    S.src = src;
    src.start();
    if (S.state !== "paused") S.state = "playing";
    else S.ctx.suspend().catch(function () {});
    draw();
    [1, 2].forEach(function (k) { var p = audioOf(i + k); if (p) p.catch(function () {}); });
  }, function (err) {
    if (token !== S.token) return;
    S.state = "paused";
    draw();
    say(err.message);
  });
}

function finish() {
  S.state = "paused";
  S.i = 0;
  unlight();
  setOn(false);
}

function pause() {
  if (S.state === "paused") return;
  S.state = "paused";
  if (S.ctx) S.ctx.suspend().catch(function () {});
  draw();
}

function resume() {
  ensureCtx();
  if (!S.parts.length) { start(null); return; }
  if (S.src) { S.state = "playing"; draw(); return; }
  play(S.i);
}

/* The part that speaks about element n: the one that names it, or else the
   last one before it on the page. */
function partFor(n) {
  var best = -1, bestAt = -1;
  for (var i = 0; i < S.parts.length; i++) {
    var at = S.parts[i].at || [];
    for (var k = 0; k < at.length; k++) {
      if (at[k] === n) return i;
      if (at[k] < n && at[k] > bestAt) { bestAt = at[k]; best = i; }
    }
  }
  return best < 0 ? 0 : best;
}

function start(fromN) {
  ensureCtx();
  if (!S.ctx) { say("This browser cannot play sound."); setOn(false); return; }
  S.state = "preparing";
  S.from = fromN;
  draw();
  var items = outline();
  if (!items.length) { say("There are no words on this page to read."); setOn(false); return; }
  var token = ++S.token, run = S.run = (S.run || 0) + 1;
  api({ do: "narrate", title: document.title || "", outline: items }).then(function (said) {
    if (token !== S.token || !S.on) return;
    if (said.key !== S.key) S.audio = {};
    S.key = said.key;
    S.parts = [];
    S.done = false;
    S.i = 0;
    more(said, run, true);
  }, function (err) {
    if (token !== S.token) return;
    say(err.message);
    setOn(false);
  });
}

/* What came of the narration so far: start once there is something to say,
   go on with a part that was waited for, and ask again until all is in. */
function more(said, run, first) {
  if (run !== S.run || !S.on || said.key !== S.key) return;
  var had = S.parts.length;
  S.parts = said.parts || [];
  S.done = !!said.done;
  if (S.done && !S.parts.length) { say("No narration came back for this page. Try again."); setOn(false); return; }
  var waited = S.state === "loading" && !S.src && S.i >= had && S.i < S.parts.length;
  if (S.state === "preparing") {
    var at = S.from != null ? fromPart(S.from) : (S.parts.length ? 0 : -1);
    if (at >= 0) { var jumped = S.from != null; S.from = null; play(at, jumped); }
  } else if (waited) {
    play(S.i);
  } else if (S.done && S.state === "loading" && !S.src && S.i >= S.parts.length) {
    finish();
    return;
  }
  draw();
  if (S.done) return;
  clearTimeout(S.poll);
  S.poll = setTimeout(function () {
    if (run !== S.run || !S.on) return;
    api({ do: "ready", key: S.key }).then(function (got) { more(got, run, false); }, function (err) {
      if (run !== S.run || !S.on) return;
      say(err.message);
      setOn(false);
    });
  }, first ? 400 : 800);
}

/* The part to start at for element n pressed before the narration was all
   in, once it is known: -1 while the part that tells it may be still to come. */
function fromPart(n) {
  for (var i = 0; i < S.parts.length; i++) {
    var at = S.parts[i].at || [];
    for (var k = 0; k < at.length; k++) if (at[k] >= n) return partFor(n);
  }
  return S.done ? partFor(n) : -1;
}

function setOn(on) {
  if (on === S.on) return;
  S.on = on;
  if (on) {
    start(null);
  } else {
    S.token++;
    S.run = (S.run || 0) + 1;
    clearTimeout(S.poll);
    quiet();
    unlight();
    hoverOff();
    S.state = "idle";
    if (S.ctx) S.ctx.suspend().catch(function () {});
  }
  draw();
}

/* ------------------------------------------------------------------ presses */

btn.addEventListener("click", function (e) { e.stopPropagation(); setOn(!S.on); });
playBtn.addEventListener("click", function () {
  if (S.state === "playing" || S.state === "loading") pause();
  else if (S.state === "paused") resume();
});
$("back").addEventListener("click", function () { if (S.parts.length) play(Math.max(0, S.i - 1)); });
$("next").addEventListener("click", function () {
  if (S.parts.length) play(Math.min(S.parts.length - 1, S.i + 1));
});

/* Another page of the explainer, or another tab, put in place of the one
   being told: that one's narration is over. */
function moved() {
  setTimeout(function () { if (S.on && !showing()) setOn(false); }, 80);
}
window.addEventListener("hashchange", moved);
window.addEventListener("popstate", moved);
window.addEventListener("click", function (e) { if (!inOurs(e)) moved(); }, false);
$("stop").addEventListener("click", function () { setOn(false); });

function inOurs(e) {
  var path = e.composedPath ? e.composedPath() : [];
  return path.indexOf(ROOT) >= 0;
}
function unitAt(t) {
  if (!t || t.nodeType !== 1) return null;
  var u = t.closest("[" + NUM + "]");
  return u || t.querySelector("[" + NUM + "]");
}

/* While listening, a press on the page is "from here". Before the page's own
   handlers and the other layers', so a link or a toggle pressed means only that. */
window.addEventListener("click", function (e) {
  if (!S.on || inOurs(e) || e.button) return;
  var u = unitAt(e.target);
  if (!u) return;
  e.preventDefault();
  e.stopPropagation();
  var n = parseInt(u.getAttribute(NUM), 10);
  if (S.state === "preparing") { S.from = n; return; }
  var at = fromPart(n);
  if (at < 0) { S.from = n; S.state = "preparing"; quiet(); unlight(); draw(); return; }
  play(at, true);
}, true);

var hovered = null;
function hoverOff() {
  if (hovered) hovered.classList.remove("askai-ls-hover");
  hovered = null;
}
window.addEventListener("mouseover", function (e) {
  if (!S.on || inOurs(e)) { hoverOff(); return; }
  var u = e.target && e.target.closest ? e.target.closest("[" + NUM + "]") : null;
  if (u === hovered) return;
  hoverOff();
  if (u) { hovered = u; u.classList.add("askai-ls-hover"); }
}, true);

/* ------------------------------------------------------------------ keys */

function typing(e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  return !!(t && t.nodeType === 1 && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable));
}
window.addEventListener("keydown", function (e) {
  if (e.key !== "Escape" || e.defaultPrevented || !S.on) return;
  setOn(false);
  e.preventDefault();
  e.stopPropagation();
}, true);
/* L: Listen. After the page's own keys, so a page with an L of its own keeps it. */
window.addEventListener("keydown", function (e) {
  if (e.key !== "l" && e.key !== "L") return;
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || typing(e)) return;
  e.preventDefault();
  setOn(!S.on);
}, false);

draw();
})();
