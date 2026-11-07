/* Passages of the page highlighted in colour, the way Apple Books and Kindle
 * have them.
 *
 * Petar, 1 October 2026 (fr_69625bf0c1a8): "on my html pages, I would love to
 * get one more feature besides comments and ask ai - highlighter. I would
 * love to turn on maker and be able to highlight in colors like apple books
 * or kindle."
 *
 * So:
 *
 * - The marker is a button in the floating control, beside comments and Ask
 *   AI, and H. While it is on, text selected on the page is painted in the
 *   colour chosen, the moment the selection is made, and the bar at the
 *   bottom offers the five colours and Done. Escape, Done or the button again
 *   puts it down, and selecting text is selecting text again: the bar that
 *   asks Ask AI about it comes back, and comments are as they were.
 * - Painting over part of a passage already painted makes one passage of
 *   both, in the colour just used; painting inside one gives it that colour.
 * - Pressing a painted passage, with the marker on or off, opens a small bar
 *   over it with the five colours and a bin: another colour, or no highlight.
 * - Every passage is kept (rouh/highlights.py), as its words and the words
 *   either side of them, and drawn again where it was when the page is opened
 *   again.
 *
 * Petar, 2 October 2026 (fr_0f05e13f03a8): "I feel like highlighting should
 * be visible by all users seeing that html document. also the name of the
 * person that highlighted it should not appear unless you hover on desktop
 * (or tap on mobile/tablet)."
 *
 * - So everybody who can open the page sees everybody's highlights on it,
 *   each in the colour its maker chose. Only the maker's own open the little
 *   bar; the others are theirs to change, not ours.
 * - Who made a passage is a small label, "Highlighted by Sam", out of
 *   sight until a mouse rests on the passage, or a finger taps it. A tap or
 *   a click anywhere else puts it away again. Where two people's passages
 *   overlap, it names both.
 * - The list is asked for again whenever the page comes back into view, so
 *   what somebody else marked meanwhile appears without a reload.
 *
 * The marks are <mark class="askai-mk"> around the page's own text, so they
 * are in the page and move with it; everything else - the bar, the colours,
 * the little bar over a passage - is drawn in a shadow root in #askai-root,
 * which askai.js and comments.js already treat as their own and not the
 * page's. Ask AI's marks over passages asked about are askai-hl, and the two
 * sit inside one another happily.
 *
 * The page is sandboxed and cannot call out, so each request goes to
 * `/api/highlights`, which the page around this one carries (askRelay in
 * app.js for the owner, reader.js for a person the page is shared with).
 *
 * Vanilla, no dependencies, no build step. */
(function () {
"use strict";

var CFG = window.ASKAI_HIGHLIGHTS;
if (!CFG || window.ASKAI_BAR_ONLY || window.__askaiHighlights) return;
var ROOT = document.getElementById("askai-root");
if (!ROOT || !document.body) return;
window.__askaiHighlights = true;

var API = "/api/highlights";

/* The five colours, as the page paints them and as the swatches show them.
   Translucent, so a page's own text colour and background still read through,
   on a light page or a dark one. */
var COLOURS = [
  { name: "yellow", label: "Yellow", swatch: "#ffd60a", paint: "rgba(255,214,10,.42)" },
  { name: "green", label: "Green", swatch: "#6fd65a", paint: "rgba(111,214,90,.38)" },
  { name: "blue", label: "Blue", swatch: "#5ab8ff", paint: "rgba(90,184,255,.36)" },
  { name: "pink", label: "Pink", swatch: "#ff6fae", paint: "rgba(255,111,174,.34)" },
  { name: "purple", label: "Purple", swatch: "#b08cff", paint: "rgba(176,140,255,.40)" }
];
var BY_NAME = {};
COLOURS.forEach(function (c) { BY_NAME[c.name] = c; });

var KEY = "askai-mk:colour";
function recall() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
function store(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }

var S = {
  list: [],            /* everybody's highlights, as the server last said */
  byId: {},
  on: false,           /* the marker */
  colour: BY_NAME[recall()] ? recall() : "yellow",
  open: 0,             /* the highlight whose little bar is open */
  busy: false
};

/* ------------------------------------------------------------------ small */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function html() { return document.documentElement; }

/* A marker over the colour it paints in: the line under it is that colour. */
function markerIcon(colour) {
  return '<svg viewBox="0 0 24 24" class="askai-line" aria-hidden="true">' +
    '<path d="M14.6 4.2l5.2 5.2-7.7 7.7H7v-5.2z"/><path d="M7 11.9l5.1 5.2"/>' +
    '<path d="M7 17.1L5 19.2h4.2"/>' +
    '<path d="M3.5 21.6h17" stroke="' + esc((BY_NAME[colour] || COLOURS[0]).swatch) +
    '" stroke-width="2.6"/></svg>';
}
var BIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 7h15M9.5 7V4.8h5V7"/>' +
  '<path d="M6.5 7l.9 12.2h9.2L17.5 7"/><path d="M10.2 10.5v5.5M13.8 10.5v5.5"/></svg>';
var TICK = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.4l2.3 2.3 4.7-5"/></svg>';

/* ------------------------------------------------------------------ the page's own styles */

/* What the marks look like, on the page itself rather than in the shadow root
   below, because they are on the page. Their own colour is the text's: a
   browser draws <mark> in black on yellow unless told otherwise. */
var sheet = document.createElement("style");
sheet.textContent =
  "mark.askai-mk{color:inherit!important;border-radius:2px;padding:0!important;margin:0!important;" +
  "-webkit-box-decoration-break:clone;box-decoration-break:clone;cursor:pointer}" +
  COLOURS.map(function (c) {
    return "mark.askai-mk[data-c=\"" + c.name + "\"]{background:" + c.paint + "!important}";
  }).join("") +
  "mark.askai-mk.askai-mk-on{box-shadow:inset 0 -2px 0 rgba(109,92,240,.95)}" +
  "html.askai-marking body,html.askai-marking body *{cursor:text}" +
  "html.askai-marking mark.askai-mk,html.askai-marking a[href]{cursor:pointer}" +
  "#askai-root #askai-mk{all:initial!important;position:fixed!important;top:0!important;" +
  "left:0!important;right:0!important;bottom:0!important;z-index:2147483003!important;" +
  "pointer-events:none!important;display:block!important}";
document.head.appendChild(sheet);

/* ------------------------------------------------------------------ what is drawn over the page */

var host = document.createElement("div");
host.id = "askai-mk";
var sh = host.attachShadow({ mode: "open" });
function swatches(cls) {
  return COLOURS.map(function (c) {
    return '<button type="button" class="sw ' + cls + '" data-c="' + c.name + '" title="' + c.label +
      '" aria-label="' + c.label + '" style="--c:' + c.swatch + '"><span>' + TICK + "</span></button>";
  }).join("");
}
sh.innerHTML =
  '<link rel="stylesheet" href="' + esc(CFG.css || "") + '">' +
  '<div class="mk" id="mk">' +
    '<div class="bar" id="bar" role="toolbar" aria-label="Highlighter">' +
      '<div class="sws" role="radiogroup" aria-label="Colour">' + swatches("pick") + "</div>" +
      '<span class="words">Select text to highlight it<span class="long"> &middot; ' +
        "<kbd>Esc</kbd> to stop</span></span>" +
      '<button type="button" class="done" id="done">Done</button>' +
    "</div>" +
    '<div class="pop" id="pop" role="toolbar" aria-label="Highlight" hidden>' +
      swatches("re") +
      '<span class="sep" aria-hidden="true"></span>' +
      '<button type="button" class="bin" id="bin" title="Remove highlight" ' +
        'aria-label="Remove highlight">' + BIN + "</button>" +
    "</div>" +
    '<div class="who" id="who" role="tooltip" hidden></div>' +
    '<div class="toast" id="toast" role="status"></div>' +
  "</div>";
ROOT.appendChild(host);

function $(id) { return sh.getElementById(id); }
var bar = $("bar"), pop = $("pop"), toast = $("toast"), who = $("who");

/* The button, in the drawer's own floating bar beside History and Edit.
   Where comments are on, their control takes that bar's place and presses
   this one through (comments.js, "mirror"), and shows what it shows. */
var float = document.getElementById("askai-float");
var btn = document.createElement("button");
btn.id = "askai-mark-btn";
btn.type = "button";
btn.className = "askai-fb";
btn.setAttribute("aria-pressed", "false");
if (float) {
  var after = document.getElementById("askai-launch");
  if (after && after.nextSibling) float.insertBefore(btn, after.nextSibling);
  else float.appendChild(btn);
}
function drawButton() {
  var c = BY_NAME[S.colour] || COLOURS[0];
  btn.innerHTML = markerIcon(S.colour);
  btn.title = S.on ? "Highlighting in " + c.label.toLowerCase() + " (H to stop)" : "Highlighter (H)";
  btn.setAttribute("aria-label", S.on ? "Stop highlighting" : "Highlighter");
  btn.setAttribute("aria-pressed", S.on ? "true" : "false");
  btn.classList.toggle("on", S.on);
  [].forEach.call(sh.querySelectorAll(".sw.pick"), function (b) {
    var mine = b.getAttribute("data-c") === S.colour;
    b.classList.toggle("on", mine);
    b.setAttribute("aria-pressed", mine ? "true" : "false");
  });
}

var toastTimer = 0;
function say(words, bad) {
  toast.textContent = words;
  toast.classList.toggle("bad", !!bad);
  toast.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toast.classList.remove("on"); }, 6000);
}

/* ------------------------------------------------------------------ the server */

function api(method, body) {
  var init = { method: method };
  if (body) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  return fetch(API, init).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok || !j || j.error) {
        throw new Error((j && j.error) || (r.status === 401 || r.status === 403
          ? "Your sign-in has run out. Reload the page and try again."
          : "Rouh could not keep that: it said " + r.status + "."));
      }
      return j;
    });
  }, function () {
    throw new Error("Rouh could not be reached, so that highlight was not kept.");
  });
}

/* ------------------------------------------------------------------ the page's text */

/* The page's words as one string, with every run of white space one space,
   and where each of its letters is: the same text a selection reads, so a
   passage is found by what it says, not by where it sits in the markup.
   Ask AI's and comments' own things are not the page, and neither is what
   a page keeps in a script or a style. */
var SKIP = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TEXTAREA|SELECT|OPTION)$/;
function skipped(node) {
  for (var el = node.parentElement; el && el !== document.body; el = el.parentElement) {
    if (el === ROOT || SKIP.test(el.tagName)) return true;
  }
  return false;
}
function textIndex() {
  var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: function (n) { return skipped(n) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; }
  });
  var out = [], map = [], nodes = [], at = new Map(), node, i, ch, space = true;
  while ((node = w.nextNode())) {
    var v = node.nodeValue, from = map.length;
    for (i = 0; i < v.length; i++) {
      ch = v.charAt(i);
      if (/\s/.test(ch)) {
        if (space) continue;
        out.push(" "); map.push({ node: node, off: i }); space = true;
      } else {
        out.push(ch); map.push({ node: node, off: i }); space = false;
      }
    }
    nodes.push({ node: node, from: from, to: map.length });
    at.set(node, nodes[nodes.length - 1]);
  }
  return { text: out.join(""), map: map, nodes: nodes, at: at };
}

var WORD = /[\p{L}\p{N}'’_-]/u;

/* A range on the page as where it starts and ends in that text, trimmed of
   space at either end, or null when it holds no words. */
function spanOf(range, idx) {
  var s = -1, e = -1;
  idx.nodes.forEach(function (n) {
    if (n.to <= n.from || !range.intersectsNode(n.node)) return;
    var lo = n.node === range.startContainer ? range.startOffset : 0;
    var hi = n.node === range.endContainer ? range.endOffset : n.node.nodeValue.length;
    for (var k = n.from; k < n.to; k++) {
      var off = idx.map[k].off;
      if (off >= lo && off < hi) {
        if (s < 0) s = k;
        e = k + 1;
      }
    }
  });
  if (s < 0) return null;
  /* Whole words, as Apple Books and Kindle paint them: a selection that
     stops part of the way into a word takes the rest of it. */
  while (s > 0 && WORD.test(idx.text.charAt(s - 1)) && WORD.test(idx.text.charAt(s))) s--;
  while (e < idx.text.length && WORD.test(idx.text.charAt(e - 1)) && WORD.test(idx.text.charAt(e))) e++;
  while (s < e && idx.text.charAt(s) === " ") s++;
  while (e > s && idx.text.charAt(e - 1) === " ") e--;
  return e > s ? { s: s, e: e } : null;
}

/* Where one highlight is drawn now, in that text. */
function spanOfMarks(id, idx) {
  var marks = marksOf(id);
  if (!marks.length) return null;
  var s = -1, e = -1;
  [].forEach.call(marks, function (m) {
    var w = document.createTreeWalker(m, NodeFilter.SHOW_TEXT), t;
    while ((t = w.nextNode())) {
      var n = idx.at.get(t);
      if (!n || n.to <= n.from) continue;
      if (s < 0 || n.from < s) s = n.from;
      if (n.to > e) e = n.to;
    }
  });
  return s < 0 ? null : { s: s, e: e };
}

/* Where a kept passage is on the page as it is now: by its words, and where
   they are there more than once, by the words around them and then by where
   it was. */
function find(anchor, idx) {
  var text = String(anchor.text || "");
  if (!text) return null;
  var best = null, bestScore = -Infinity, at = idx.text.indexOf(text), seen = 0;
  var pre = String(anchor.prefix || ""), suf = String(anchor.suffix || "");
  while (at >= 0 && seen++ < 500) {
    var score = 0, k;
    for (k = 1; k <= pre.length && at - k >= 0 && idx.text.charAt(at - k) === pre.charAt(pre.length - k); k++) score++;
    for (k = 0; k < suf.length && idx.text.charAt(at + text.length + k) === suf.charAt(k); k++) score++;
    score -= Math.abs(at - (Number(anchor.start) || 0)) / 100000;
    if (score > bestScore) { bestScore = score; best = at; }
    at = idx.text.indexOf(text, at + 1);
  }
  return best == null ? null : { s: best, e: best + text.length };
}

function anchorOf(span, idx) {
  return {
    text: idx.text.slice(span.s, span.e),
    prefix: idx.text.slice(Math.max(0, span.s - 48), span.s),
    suffix: idx.text.slice(span.e, span.e + 48),
    start: span.s
  };
}

/* ------------------------------------------------------------------ the marks */

function marksOf(id) {
  return document.querySelectorAll('mark.askai-mk[data-hl="' + String(id).replace(/"/g, "") + '"]');
}

/* Where a mark may not go: between the rows of a table or the items of a
   list, where only those may be. Only the words themselves are painted. */
var NO_INLINE = /^(TABLE|THEAD|TBODY|TFOOT|TR|COLGROUP|UL|OL|DL|SELECT|HTML|HEAD)$/;

/* The span painted, one mark around each piece of text in it. */
function paint(span, id, colour, idx) {
  var plan = [];
  idx.nodes.forEach(function (n) {
    var lo = Math.max(n.from, span.s), hi = Math.min(n.to, span.e);
    if (hi <= lo) return;
    var s = idx.map[lo].off, e = idx.map[hi - 1].off + 1;
    if (!/\S/.test(n.node.nodeValue.slice(s, e))) return;
    if (!n.node.parentElement || NO_INLINE.test(n.node.parentElement.tagName)) return;
    plan.push({ node: n.node, s: s, e: e });
  });
  /* Last first: wrapping a piece splits its text node, and the earlier
     pieces' places are in the part that stays. */
  for (var i = plan.length - 1; i >= 0; i--) {
    var p = plan[i];
    try {
      var r = document.createRange();
      r.setStart(p.node, p.s);
      r.setEnd(p.node, p.e);
      var m = document.createElement("mark");
      m.className = "askai-mk";
      m.setAttribute("data-hl", String(id));
      m.setAttribute("data-c", colour);
      r.surroundContents(m);
    } catch (err) { /* a piece that cannot be wrapped is left as it is */ }
  }
  return plan.length > 0;
}

/* A highlight's marks taken off, its text put back as it was. */
function unpaint(id) {
  var parents = [];
  [].forEach.call(marksOf(id), function (m) {
    var p = m.parentNode;
    if (!p) return;
    while (m.firstChild) p.insertBefore(m.firstChild, m);
    p.removeChild(m);
    if (parents.indexOf(p) < 0) parents.push(p);
  });
  parents.forEach(function (p) { try { p.normalize(); } catch (e) {} });
}

function recolourMarks(id, colour) {
  [].forEach.call(marksOf(id), function (m) { m.setAttribute("data-c", colour); });
}

/* Every kept highlight not yet on the page, drawn where it is. One that is
   not there - its words have gone - is skipped and kept, and comes back if
   they do. Last on the page first, for the same reason as in paint. */
function placeAll() {
  var missing = S.list.filter(function (h) { return !marksOf(h.id).length; });
  if (!missing.length) return;
  var idx = textIndex(), spans = [];
  missing.forEach(function (h) {
    var span = find(h.anchor || {}, idx);
    if (span) spans.push({ h: h, span: span });
  });
  spans.sort(function (a, b) { return b.span.s - a.span.s; });
  quietly(function () {
    spans.forEach(function (x) { paint(x.span, x.h.id, x.h.colour, idx); });
  });
}

/* The page's own changes - a page drawing more of itself, Ask AI changing a
   paragraph - can take marks with them. Whatever is missing afterwards is
   drawn again. The marks' own changes are not the page's. */
var settle = 0;
var watcher = new MutationObserver(function (records) {
  for (var i = 0; i < records.length; i++) {
    if (!ROOT.contains(records[i].target)) {
      clearTimeout(settle);
      settle = setTimeout(placeAll, 250);
      return;
    }
  }
});
function quietly(fn) {
  try { fn(); } finally { watcher.takeRecords(); }
}

/* ------------------------------------------------------------------ the server's list */

/* The list as the server has it now. A highlight its maker took off since
   goes from the page, one they gave another colour changes, and one that is
   new is drawn. */
function apply(data) {
  var list = (data && data.highlights) || [], now = {};
  list.forEach(function (h) { now[h.id] = h; });
  quietly(function () {
    S.list.forEach(function (h) {
      if (!now[h.id]) unpaint(h.id);
      else if (now[h.id].colour !== h.colour) recolourMarks(h.id, now[h.id].colour);
    });
  });
  if (S.open && !now[S.open]) closePop();
  hideWho();
  S.list = list;
  S.byId = now;
  placeAll();
}

function load() {
  return api("GET").then(apply, function () { /* the page is still the page without them */ });
}

/* Back on the page after a while away: what the others marked meanwhile. */
document.addEventListener("visibilitychange", function () {
  if (document.visibilityState === "visible" && !S.busy) load();
});

/* ------------------------------------------------------------------ painting a selection */

function inPage(node) {
  var el = node && (node.nodeType === 1 ? node : node.parentElement);
  return !!el && document.body.contains(el) && !ROOT.contains(el);
}

/* The selection painted in the colour chosen. A passage it falls inside
   takes that colour; passages it runs over become one with it. */
function paintSelection() {
  var sel = window.getSelection();
  if (!S.on || S.busy || !sel || sel.isCollapsed || !sel.rangeCount) return false;
  var range = sel.getRangeAt(0);
  if (!inPage(range.startContainer) || !inPage(range.endContainer)) return false;
  var idx = textIndex(), span = spanOf(range, idx);
  if (!span) return false;
  sel.removeAllRanges();
  painted = Date.now();
  var colour = S.colour, over = [];
  S.list.forEach(function (h) {
    if (!h.mine) return;
    var at = spanOfMarks(h.id, idx);
    if (at && at.s < span.e && span.s < at.e) over.push({ h: h, at: at });
  });
  if (over.length === 1 && over[0].at.s <= span.s && span.e <= over[0].at.e) {
    if (over[0].h.colour !== colour) recolour(over[0].h.id, colour);
    return true;
  }
  var whole = { s: span.s, e: span.e };
  over.forEach(function (o) { whole.s = Math.min(whole.s, o.at.s); whole.e = Math.max(whole.e, o.at.e); });
  var anchor = anchorOf(whole, idx);
  var gone = over.map(function (o) { return o.h.id; });
  var temp = "new-" + Date.now();
  quietly(function () {
    gone.forEach(unpaint);
    var now = textIndex();
    var again = find(anchor, now) || whole;
    paint(again, temp, colour, now);
  });
  S.list = S.list.filter(function (h) { return gone.indexOf(h.id) < 0; });
  gone.forEach(function (id) { delete S.byId[id]; });
  S.busy = true;
  api("POST", { do: "add", colour: colour, anchor: anchor, replaces: gone }).then(function (j) {
    S.busy = false;
    var h = j.highlight;
    [].forEach.call(marksOf(temp), function (m) { m.setAttribute("data-hl", String(h.id)); });
    S.list.push(h);
    S.byId[h.id] = h;
  }, function (err) {
    S.busy = false;
    quietly(function () { unpaint(temp); });
    say(err.message, true);
    load();
  });
  return true;
}

/* ------------------------------------------------------------------ one passage's little bar */

function recolour(id, colour) {
  var h = S.byId[id];
  if (!h || h.colour === colour) return;
  var was = h.colour;
  h.colour = colour;
  recolourMarks(id, colour);
  drawPop();
  api("POST", { do: "colour", id: id, colour: colour }).then(null, function (err) {
    h.colour = was;
    recolourMarks(id, was);
    drawPop();
    say(err.message, true);
  });
}

function removeHighlight(id) {
  var h = S.byId[id];
  if (!h) return;
  closePop();
  hideWho();
  quietly(function () { unpaint(id); });
  S.list = S.list.filter(function (x) { return x.id !== id; });
  delete S.byId[id];
  api("POST", { do: "remove", id: id }).then(null, function (err) {
    say(err.message, true);
    load();
  });
}

function openPop(id) {
  if (!S.byId[id] || !S.byId[id].mine) return;
  closePop();
  S.open = id;
  [].forEach.call(marksOf(id), function (m) { m.classList.add("askai-mk-on"); });
  pop.hidden = false;
  drawPop();
  placePop();
  var first = pop.querySelector(".sw.on") || pop.querySelector(".sw");
  if (first) first.focus({ preventScroll: true });
}
function closePop() {
  if (!S.open) return;
  [].forEach.call(marksOf(S.open), function (m) { m.classList.remove("askai-mk-on"); });
  S.open = 0;
  pop.hidden = true;
}
function drawPop() {
  var h = S.byId[S.open];
  if (!h) return;
  [].forEach.call(pop.querySelectorAll(".sw"), function (b) {
    var mine = b.getAttribute("data-c") === h.colour;
    b.classList.toggle("on", mine);
    b.setAttribute("aria-pressed", mine ? "true" : "false");
  });
}
/* Over the passage's first line, or under it where there is no room above. */
function placePop() {
  var marks = marksOf(S.open);
  if (!marks.length) { closePop(); hideWho(); return; }
  var rects = marks[0].getClientRects(), r = rects.length ? rects[0] : marks[0].getBoundingClientRect();
  var w = pop.offsetWidth || 220, h = pop.offsetHeight || 40;
  var top = r.top - h - 8;
  if (top < 8) {
    var last = marks[marks.length - 1].getBoundingClientRect();
    top = Math.min(last.bottom + 8, window.innerHeight - h - 8);
  }
  var left = Math.min(Math.max(8, r.left + Math.min(r.width, 160) / 2 - w / 2), window.innerWidth - w - 8);
  pop.style.top = Math.max(8, top) + "px";
  pop.style.left = Math.max(8, left) + "px";
}

[].forEach.call(pop.querySelectorAll(".sw"), function (b) {
  b.addEventListener("click", function (e) {
    e.stopPropagation();
    if (S.open) recolour(S.open, b.getAttribute("data-c"));
  });
});
$("bin").addEventListener("click", function (e) { e.stopPropagation(); if (S.open) removeHighlight(S.open); });
pop.addEventListener("mousedown", function (e) { e.preventDefault(); });

/* ------------------------------------------------------------------ the marker */

function busyElsewhere() {
  var c = html().classList;
  return c.contains("askai-commenting") || c.contains("askai-picking") ||
    !!document.querySelector(".askai-typing");
}

function setOn(on) {
  on = !!on;
  if (on === S.on) return;
  if (on) {
    /* The marker, comments (C) and Edit (E) all take what the page is
       pressed for, so picking up one puts the others down. */
    try { document.dispatchEvent(new CustomEvent("askai-stop-pointing")); } catch (e) {}
    try { document.dispatchEvent(new CustomEvent("askai-stop-commenting")); } catch (e) {}
  }
  S.on = on;
  html().classList.toggle("askai-marking", on);
  bar.classList.toggle("on", on);
  drawButton();
  if (on) {
    /* A passage already selected when the marker is picked up is painted. */
    setTimeout(paintSelection, 0);
  }
}

function setColour(name) {
  if (!BY_NAME[name]) return;
  S.colour = name;
  store(name);
  drawButton();
}

btn.addEventListener("click", function (e) { e.stopPropagation(); setOn(!S.on); });
$("done").addEventListener("click", function () { setOn(false); });
[].forEach.call(sh.querySelectorAll(".sw.pick"), function (b) {
  b.addEventListener("click", function (e) { e.stopPropagation(); setColour(b.getAttribute("data-c")); });
});
bar.addEventListener("mousedown", function (e) {
  /* Pressing a colour keeps whatever is selected on the page selected. */
  if (e.target !== $("done")) e.preventDefault();
});
document.addEventListener("askai-stop-marking", function () { setOn(false); });

/* Comments or Edit picked up some other way: the marker goes down. */
new MutationObserver(function () {
  var c = html().classList;
  if (S.on && (c.contains("askai-commenting") || c.contains("askai-picking"))) setOn(false);
}).observe(html(), { attributes: true, attributeFilter: ["class"] });

/* A selection is painted as it is made: with a mouse, as the button comes
   up. A finger's selection has no such moment - it is made by a long press
   and its handles are dragged after - so it is painted once it has stood
   still for a moment with nothing pressed. */
var pressed = false, still = 0, painted = 0;
document.addEventListener("pointerdown", function (e) {
  if (!ROOT.contains(e.target)) pressed = true;
}, true);
document.addEventListener("pointerup", function () { pressed = false; }, true);
document.addEventListener("pointercancel", function () { pressed = false; }, true);
document.addEventListener("mouseup", function (e) {
  if (!S.on || ROOT.contains(e.target)) return;
  paintSelection();
});
document.addEventListener("selectionchange", function () {
  if (!S.on) return;
  clearTimeout(still);
  still = setTimeout(function () { if (!pressed) paintSelection(); }, 900);
});

/* ------------------------------------------------------------------ who made it */

/* The highlights under one point of the page, innermost first: two people's
   passages over the same words are one mark inside the other. */
function covering(node) {
  var out = [];
  for (var el = node && (node.nodeType === 1 ? node : node.parentElement); el && el !== document.body;
       el = el.parentElement) {
    if (el.tagName !== "MARK" || !el.classList.contains("askai-mk")) continue;
    var h = S.byId[el.getAttribute("data-hl")];
    if (h && out.indexOf(h) < 0) out.push(h);
  }
  return out;
}

function whoSaid(list) {
  var names = [], me = false;
  list.forEach(function (h) {
    if (h.mine) me = true;
    else if (names.indexOf(h.by || "Somebody") < 0) names.push(h.by || "Somebody");
  });
  if (me) names.push("you");
  if (names.length < 2) return names[0] || "";
  return names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
}

/* The label, over the line of the passage the pointer or the finger is on,
   or over the little bar when that is open. Kept in the page's view while
   it is pinned by a press; a mouse's goes when the mouse moves off. */
var W = { mark: null, x: 0, y: 0, pinned: false, key: "" };
function showWho(list, mark, x, y, pinned) {
  var said = whoSaid(list);
  if (!said) { hideWho(); return; }
  who.innerHTML = "Highlighted by <b>" + esc(said) + "</b>";
  who.hidden = false;
  W.mark = mark; W.x = x; W.y = y; W.pinned = !!pinned;
  W.key = list.map(function (h) { return h.id; }).join(",");
  placeWho();
}
function hideWho() {
  if (who.hidden) return;
  who.hidden = true;
  W.mark = null; W.pinned = false; W.key = "";
}
function placeWho() {
  if (!W.mark || !W.mark.isConnected) { hideWho(); return; }
  var w = who.offsetWidth, h = who.offsetHeight, top, left;
  if (!pop.hidden) {
    var p = pop.getBoundingClientRect(), line0 = marksOf(S.open)[0];
    var under = line0 && p.top > line0.getBoundingClientRect().top;
    top = under ? p.bottom + 6 : p.top - h - 6;
    left = p.left;
  } else {
    var rects = W.mark.getClientRects(), r = rects[0] || W.mark.getBoundingClientRect();
    for (var i = 0; i < rects.length; i++) {
      if (W.y >= rects[i].top - 2 && W.y <= rects[i].bottom + 2) { r = rects[i]; break; }
    }
    top = r.top - h - 6;
    if (top < 8) top = r.bottom + 6;
    var x = Math.min(Math.max(W.x, r.left), r.right);
    left = x - w / 2;
  }
  who.style.top = Math.max(8, Math.min(top, window.innerHeight - h - 8)) + "px";
  who.style.left = Math.max(8, Math.min(left, window.innerWidth - w - 8)) + "px";
}

/* A mouse resting on a passage: who made it, for as long as it rests there.
   A finger has no such thing; a tap is its way of asking (below). */
var hoverTimer = 0;
document.addEventListener("pointerover", function (e) {
  if (e.pointerType !== "mouse" || ROOT.contains(e.target)) return;
  clearTimeout(hoverTimer);
  var list = covering(e.target);
  if (!list.length) {
    if (!W.pinned) hoverTimer = setTimeout(hideWho, 120);
    return;
  }
  if (pressed) return;
  var key = list.map(function (h) { return h.id; }).join(",");
  if (W.pinned && W.key === key) return;
  var mark = e.target.closest("mark.askai-mk"), x = e.clientX, y = e.clientY;
  hoverTimer = setTimeout(function () { showWho(list, mark, x, y, false); }, 150);
}, true);
document.documentElement.addEventListener("mouseleave", function () {
  clearTimeout(hoverTimer);
  if (!W.pinned) hideWho();
});

/* Pressing a painted passage says who made it, and opens its little bar
   when it is the reader's own: with the marker on, always; with it off,
   unless the press was meant for a link or a control in it, for Ask AI's
   mark over the same words, or for comments or Edit. Pressing anywhere
   else puts both away. */
document.addEventListener("click", function (e) {
  if (ROOT.contains(e.target)) return;
  var m = e.target && e.target.closest ? e.target.closest("mark.askai-mk") : null;
  if (!m) { closePop(); hideWho(); return; }
  /* The press that ended a selection the marker has just painted. */
  if (Date.now() - painted < 400) return;
  var sel = window.getSelection();
  if (sel && !sel.isCollapsed) return;
  if (busyElsewhere()) return;
  if (!S.on) {
    if (e.defaultPrevented) return;
    if (e.target.closest("a[href], button, input, select, textarea, label, mark.askai-hl, [contenteditable]")) return;
  } else {
    e.preventDefault();
    e.stopPropagation();
  }
  var list = covering(e.target);
  var own = list.filter(function (h) { return h.mine; })[0];
  var key = list.map(function (h) { return h.id; }).join(",");
  if (own ? S.open === own.id : W.pinned && W.key === key) {
    closePop();
    hideWho();
    return;
  }
  clearTimeout(hoverTimer);
  if (own) openPop(own.id); else closePop();
  showWho(list, m, e.clientX, e.clientY, true);
}, true);
window.addEventListener("scroll", function () {
  if (S.open) placePop();
  if (W.pinned) placeWho(); else hideWho();
}, true);
window.addEventListener("resize", function () {
  if (S.open) placePop();
  if (!who.hidden) placeWho();
});

/* ------------------------------------------------------------------ keys */

function typing(e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  return !!(t && t.nodeType === 1 && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable));
}

/* Escape puts away the little bar first, then the marker, and goes no
   further: handed up, it would close the page. */
window.addEventListener("keydown", function (e) {
  if (e.key !== "Escape" || e.defaultPrevented) return;
  if (S.open) { closePop(); hideWho(); }
  else if (!who.hidden) hideWho();
  else if (S.on) setOn(false);
  else return;
  e.preventDefault();
  e.stopPropagation();
}, true);

/* H: the marker. After the page's own keys, so a page with an H of its own
   keeps it, and never while something is being typed. */
window.addEventListener("keydown", function (e) {
  if (e.key !== "h" && e.key !== "H") return;
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || typing(e)) return;
  e.preventDefault();
  setOn(!S.on);
}, false);

/* How a passage is found again, for definitions.js, which underlines the
   passages explained in place and must find them the same way. */
window.__askaiText = { index: textIndex, spanOf: spanOf, find: find, anchorOf: anchorOf,
                       inPage: inPage };

/* ------------------------------------------------------------------ boot */

drawButton();
load().then(function () {
  watcher.observe(document.body, { childList: true, subtree: true, characterData: true });
});
})();
