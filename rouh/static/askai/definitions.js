/* Define: a selected passage explained in place, in the light of the page.
 *
 * Petar, 20 October 2026 (fr_a06689f582ba): "when I select text, I get ASK
 * option to start chatting with that text. However next to ASK option add a
 * Define option that exlains inline in a tooltip this term/text with relation
 * to the context. also keep it underlined for future hovers that will display
 * tooltip".
 *
 * So:
 *
 * - Define sits beside Ask on the bar over a selection (askai.js builds the
 *   bar; this adds the button to it).
 * - Pressing it underlines the passage at once and opens a tooltip under it,
 *   which says it is explaining until the explanation comes back, a few
 *   sentences on what the passage means on this page (rouh/definitions.py).
 * - The passage stays underlined, dotted and in teal, which is neither a
 *   highlight's colour wash nor Ask AI's purple. A mouse resting on it, or a
 *   finger tapping it, opens the same tooltip with the explanation as kept,
 *   and nothing is asked again.
 * - Whoever pressed Define can have it explained again, or take it off,
 *   from the tooltip.
 * - Everybody who can open the page sees every passage defined on it, as
 *   with highlights, and the list is asked for again when the page comes back
 *   into view.
 *
 * A passage is found again by its words, the words around them and where it
 * was, with highlights.js's own code (window.__askaiText), so the two can
 * never find the same passage in two different places. The underline is
 * <mark class="askai-df"> on the page; the tooltip is drawn in a shadow root
 * in #askai-root, which the drawer and comments treat as theirs and not the
 * page's.
 *
 * Vanilla, no dependencies, no build step. */
(function () {
"use strict";

var CFG = window.ASKAI_DEFINITIONS;
var T = window.__askaiText;
if (!CFG || !T || window.ASKAI_BAR_ONLY || window.__askaiDefinitions) return;
var ROOT = document.getElementById("askai-root");
var ACTS = document.getElementById("askai-acts");
if (!ROOT || !ACTS || !document.body) return;
window.__askaiDefinitions = true;

var API = "/api/definitions";

/* As rouh/definitions.py has them: how much of the page goes with a passage.
   How long a passage may be is the server's to say, and it says why. */
var CONTEXT_MAX = 60000, PARAGRAPH_MAX = 4000;

var S = {
  list: [],
  byId: {},
  tip: null,        /* the definition the tooltip is about, or a temporary id */
  pinned: false,    /* opened by a press, so it stays until a press elsewhere */
  busy: {}          /* ids being explained right now */
};

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ------------------------------------------------------------------ the page's own styles */

/* The underline, on the page itself: dotted and teal, a colour neither the
   highlighter's five nor Ask AI's purple. A <mark> is drawn black on yellow
   unless told otherwise, so both are put back to the page's own. */
var sheet = document.createElement("style");
sheet.textContent =
  "mark.askai-df{background:transparent!important;color:inherit!important;padding:0!important;" +
  "margin:0!important;text-decoration:underline dotted rgba(45,212,191,.95)!important;" +
  "text-decoration-thickness:2px!important;text-underline-offset:3px!important;" +
  "text-decoration-skip-ink:none!important;cursor:help}" +
  "mark.askai-df.askai-df-on{background:rgba(45,212,191,.16)!important;border-radius:2px}" +
  "mark.askai-df.askai-df-wait{animation:askai-df-wait 1.1s ease-in-out infinite}" +
  "@keyframes askai-df-wait{50%{background:rgba(45,212,191,.22)}}" +
  "#askai-root #askai-df{all:initial!important;position:fixed!important;top:0!important;" +
  "left:0!important;right:0!important;bottom:0!important;z-index:2147483002!important;" +
  "pointer-events:none!important;display:block!important}";
document.head.appendChild(sheet);

/* ------------------------------------------------------------------ the tooltip */

var host = document.createElement("div");
host.id = "askai-df";
var sh = host.attachShadow({ mode: "open" });
sh.innerHTML =
  '<link rel="stylesheet" href="' + esc(CFG.css || "") + '">' +
  '<div class="df" id="tip" role="tooltip" hidden>' +
    '<div class="term" id="term"></div>' +
    '<div class="said" id="said" aria-live="polite"></div>' +
    '<div class="acts" id="acts"></div>' +
  '</div>';
ROOT.appendChild(host);
var tip = sh.getElementById("tip"), term = sh.getElementById("term"),
    said = sh.getElementById("said"), tipActs = sh.getElementById("acts");

/* The button, beside Ask. */
var btn = document.createElement("button");
btn.id = "askai-define";
btn.type = "button";
btn.textContent = "Define";
btn.title = "Explain this here, in the light of the page";
var ask = document.getElementById("askai-btn");
if (ask && ask.nextSibling) ACTS.insertBefore(btn, ask.nextSibling);
else ACTS.appendChild(btn);

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
        var bad = new Error((j && j.error) || (r.status === 401 || r.status === 403
          ? "Your sign-in has run out. Reload the page and try again."
          : "Rouh could not explain it: it said " + r.status + "."));
        bad.status = r.status;
        throw bad;
      }
      return j;
    });
  }, function () {
    throw new Error("Rouh could not be reached, so it could not explain it.");
  });
}

/* ------------------------------------------------------------------ the underlines */

function marksOf(id) {
  return document.querySelectorAll('mark.askai-df[data-df="' + String(id).replace(/"/g, "") + '"]');
}

var NO_INLINE = /^(TABLE|THEAD|TBODY|TFOOT|TR|COLGROUP|UL|OL|DL|SELECT|HTML|HEAD)$/;

/* The span underlined, one mark around each piece of text in it, last first
   because wrapping a piece splits its text node. */
function paint(span, id, idx) {
  var plan = [];
  idx.nodes.forEach(function (n) {
    var lo = Math.max(n.from, span.s), hi = Math.min(n.to, span.e);
    if (hi <= lo) return;
    var s = idx.map[lo].off, e = idx.map[hi - 1].off + 1;
    if (!/\S/.test(n.node.nodeValue.slice(s, e))) return;
    if (!n.node.parentElement || NO_INLINE.test(n.node.parentElement.tagName)) return;
    plan.push({ node: n.node, s: s, e: e });
  });
  for (var i = plan.length - 1; i >= 0; i--) {
    var p = plan[i];
    try {
      var r = document.createRange();
      r.setStart(p.node, p.s);
      r.setEnd(p.node, p.e);
      var m = document.createElement("mark");
      m.className = "askai-df";
      m.setAttribute("data-df", String(id));
      r.surroundContents(m);
    } catch (err) { /* a piece that cannot be wrapped is left as it is */ }
  }
  return plan.length > 0;
}

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

function placeAll() {
  var missing = S.list.filter(function (d) { return !marksOf(d.id).length; });
  if (!missing.length) return;
  var idx = T.index(), spans = [];
  missing.forEach(function (d) {
    var span = T.find(d.anchor || {}, idx);
    if (span) spans.push({ d: d, span: span });
  });
  spans.sort(function (a, b) { return b.span.s - a.span.s; });
  quietly(function () {
    spans.forEach(function (x) { paint(x.span, x.d.id, idx); });
  });
}

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

/* Every id is a string on the page, as the underline's own data-df is, so the
   one the tooltip holds and the one the server sent are the same. */
function own(d) { d.id = String(d.id); return d; }

function apply(data) {
  var list = ((data && data.definitions) || []).map(own), now = {};
  list.forEach(function (d) { now[d.id] = d; });
  quietly(function () {
    S.list.forEach(function (d) { if (!now[d.id] && !S.busy[d.id]) unpaint(d.id); });
  });
  if (S.tip && !now[S.tip] && !S.busy[S.tip]) hide();
  S.list = list;
  S.byId = now;
  placeAll();
  if (S.tip && now[S.tip]) draw(S.tip);
}

function load() {
  return api("GET").then(apply, function () { /* the page is still the page without them */ });
}

document.addEventListener("visibilitychange", function () {
  if (document.visibilityState === "visible" && !Object.keys(S.busy).length) load();
});

/* ------------------------------------------------------------------ the tooltip, drawn */

function draw(id) {
  var d = S.byId[id];
  if (!d) return;
  /* The words themselves as its heading, as a dictionary's popup has them,
     where they are a term; a longer passage is already there under it. */
  var words = (d.anchor && d.anchor.text) || "";
  term.textContent = words.length <= 80 ? words : "";
  term.hidden = !term.textContent;
  tipActs.innerHTML = "";
  tip.classList.remove("bad");
  if (S.busy[id]) {
    said.innerHTML = '<span class="wait">Explaining<i>.</i><i>.</i><i>.</i></span>';
  } else if (d.error) {
    tip.classList.add("bad");
    said.textContent = d.error;
    if (d.retry) tipActs.appendChild(action("Try again", d.retry));
  } else {
    said.textContent = d.text || "";
    if (d.mine) {
      tipActs.appendChild(action("Explain again", function () { again(d.id); }));
      tipActs.appendChild(action("Remove", function () { remove(d.id); }));
    } else if (d.by) {
      var by = document.createElement("span");
      by.className = "by";
      by.textContent = "Defined by " + d.by;
      tipActs.appendChild(by);
    }
  }
  tipActs.hidden = !tipActs.childNodes.length;
}

function action(words, fn) {
  var b = document.createElement("button");
  b.type = "button";
  b.textContent = words;
  b.addEventListener("click", function (e) { e.stopPropagation(); fn(); });
  return b;
}

function show(id, pinned, x, y) {
  if (S.tip && S.tip !== id) lit(S.tip, false);
  S.tip = id;
  S.pinned = !!pinned;
  draw(id);
  lit(id, true);
  tip.hidden = false;
  place(x, y);
}

function hide() {
  if (S.tip) lit(S.tip, false);
  S.tip = null;
  S.pinned = false;
  tip.hidden = true;
}

function lit(id, on) {
  [].forEach.call(marksOf(id), function (m) { m.classList.toggle("askai-df-on", on); });
}

/* Under the line of the passage nearest the pointer, or under its last line;
   above it where there is no room below. Kept inside the window. */
var at = { x: null, y: null };
function place(x, y) {
  if (x != null) { at.x = x; at.y = y; }
  var marks = marksOf(S.tip);
  if (!marks.length) { hide(); return; }
  var rects = [];
  [].forEach.call(marks, function (m) { [].push.apply(rects, m.getClientRects()); });
  if (!rects.length) return;
  var r = rects[rects.length - 1];
  if (at.y != null) {
    for (var i = 0; i < rects.length; i++) {
      if (at.y >= rects[i].top - 2 && at.y <= rects[i].bottom + 2) { r = rects[i]; break; }
    }
  }
  var w = tip.offsetWidth, h = tip.offsetHeight;
  var top = r.bottom + 8;
  if (top + h > window.innerHeight - 8) top = r.top - h - 8;
  top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
  var left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
  tip.style.top = top + "px";
  tip.style.left = left + "px";
}

/* ------------------------------------------------------------------ Define, pressed */

/* The block the passage is in: the paragraph, the item, the cell. */
var BLOCK = "p,li,td,th,dd,dt,blockquote,figcaption,h1,h2,h3,h4,h5,h6,pre,summary,caption,label";
function paragraphOf(node) {
  var el = node && (node.nodeType === 1 ? node : node.parentElement);
  var b = el && el.closest ? el.closest(BLOCK) : null;
  if (!b) {
    for (b = el; b && b !== document.body; b = b.parentElement) {
      var d = getComputedStyle(b).display;
      if (d !== "inline" && d !== "contents") break;
    }
  }
  return b && b !== document.body ? String(b.innerText || b.textContent || "").slice(0, PARAGRAPH_MAX) : "";
}

/* The page's words to go with it: all of them, or on a long page the part
   around the passage. */
function contextOf(idx, span) {
  var text = idx.text;
  if (text.length <= CONTEXT_MAX) return text;
  var from = Math.max(0, Math.min(span.s - CONTEXT_MAX / 2, text.length - CONTEXT_MAX));
  return text.slice(from, from + CONTEXT_MAX);
}

/* The definition already on exactly these words, if there is one. */
function sameAs(span, idx) {
  for (var i = 0; i < S.list.length; i++) {
    var d = S.list[i];
    var marks = marksOf(d.id);
    if (!marks.length) continue;
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
    if (s === span.s && e === span.e) return d;
  }
  return null;
}

btn.addEventListener("click", function (e) {
  e.stopPropagation();
  var sel = window.getSelection();
  ACTS.classList.remove("on");
  if (!sel || sel.isCollapsed || !sel.rangeCount) return;
  var range = sel.getRangeAt(0);
  if (!T.inPage(range.startContainer) || !T.inPage(range.endContainer)) return;
  var idx = T.index(), span = T.spanOf(range, idx);
  if (!span) return;
  var rr = range.getBoundingClientRect();
  var paragraph = paragraphOf(range.startContainer);
  sel.removeAllRanges();
  var same = sameAs(span, idx);
  if (same) { show(same.id, true, rr.left, rr.bottom - 1); return; }
  var anchor = T.anchorOf(span, idx);
  var temp = "new-" + Date.now();
  var d = { id: temp, anchor: anchor, text: "", mine: true };
  quietly(function () { paint(span, temp, idx); });
  S.list.push(d);
  S.byId[temp] = d;
  define(d, { do: "define", anchor: anchor, paragraph: paragraph, context: contextOf(idx, span) },
         rr.left, rr.bottom - 1);
});
ACTS.addEventListener("mousedown", function (e) { e.preventDefault(); });

function waiting(id, on) {
  if (on) S.busy[id] = true; else delete S.busy[id];
  [].forEach.call(marksOf(id), function (m) { m.classList.toggle("askai-df-wait", !!on); });
}

/* Asked for, and the tooltip kept open on it while it is explained. */
function define(d, body, x, y) {
  var temp = d.id;
  d.error = "";
  waiting(temp, true);
  show(temp, true, x, y);
  api("POST", body).then(function (j) {
    waiting(temp, false);
    var got = own(j.definition);
    var known = S.byId[got.id];
    if (known && known !== d) {
      /* Somebody had already explained these words: theirs is the one. */
      quietly(function () { unpaint(temp); });
      drop(temp);
      placeAll();
      if (S.tip === temp) show(got.id, true);
      return;
    }
    [].forEach.call(marksOf(temp), function (m) { m.setAttribute("data-df", String(got.id)); });
    drop(temp);
    S.list.push(got);
    S.byId[got.id] = got;
    if (S.tip === temp) S.tip = got.id;
    if (S.tip === got.id) { draw(got.id); place(); }
  }, function (err) {
    waiting(temp, false);
    d.error = err.message;
    /* A refusal (too long, not shared) says what to do instead; anything
       else may work a moment later. */
    d.retry = err.status === 400 || err.status === 404 ? null : function () { define(d, body); };
    d.abandon = true;
    if (S.tip === temp) { draw(temp); place(); }
    else { quietly(function () { unpaint(temp); }); drop(temp); }
  });
}

function drop(id) {
  S.list = S.list.filter(function (x) { return x.id !== id; });
  delete S.byId[id];
}

function again(id) {
  var d = S.byId[id];
  if (!d || S.busy[id]) return;
  var was = d.text;
  waiting(id, true);
  draw(id);
  place();
  api("POST", { do: "again", id: id, paragraph: paragraphOf(marksOf(id)[0]),
                context: contextOf(T.index(), { s: Number((d.anchor || {}).start) || 0 }) })
    .then(function (j) {
      waiting(id, false);
      var got = own(j.definition);
      S.byId[id] = got;
      S.list = S.list.map(function (x) { return x.id === id ? got : x; });
      if (S.tip === id) { draw(id); place(); }
    }, function (err) {
      waiting(id, false);
      d.text = was;
      d.error = err.message;
      d.retry = function () { d.error = ""; again(id); };
      if (S.tip === id) { draw(id); place(); }
      d.error = "";
    });
}

function remove(id) {
  var d = S.byId[id];
  if (!d) return;
  hide();
  quietly(function () { unpaint(id); });
  drop(id);
  api("POST", { do: "remove", id: id }).then(null, function () { load(); });
}

/* ------------------------------------------------------------------ hover and press */

function defOf(node) {
  var el = node && (node.nodeType === 1 ? node : node.parentElement);
  var m = el && el.closest ? el.closest("mark.askai-df") : null;
  return m ? m.getAttribute("data-df") : null;
}

/* A mouse resting on an underlined passage opens its tooltip; moving off it,
   and not onto the tooltip, closes it again unless a press opened it. */
var hoverTimer = 0;
document.addEventListener("pointerover", function (e) {
  if (e.pointerType !== "mouse" || ROOT.contains(e.target)) return;
  var id = defOf(e.target);
  clearTimeout(hoverTimer);
  if (!id) {
    if (S.tip && !S.pinned) hoverTimer = setTimeout(hide, 250);
    return;
  }
  if (S.pinned && S.tip === id) return;
  var x = e.clientX, y = e.clientY;
  hoverTimer = setTimeout(function () { if (S.byId[id]) show(id, false, x, y); }, 160);
}, true);
host.addEventListener("pointerover", function () { clearTimeout(hoverTimer); });
document.documentElement.addEventListener("mouseleave", function () {
  clearTimeout(hoverTimer);
  if (S.tip && !S.pinned) hide();
});

/* A press on an underlined passage, which is how a finger asks: the tooltip,
   kept open. A press anywhere else puts it away, and lets go of an
   explanation that failed. Links and controls in the passage keep their
   press. */
document.addEventListener("click", function (e) {
  if (ROOT.contains(e.target)) return;
  var id = defOf(e.target);
  if (!id) {
    if (S.tip) {
      var d = S.byId[S.tip];
      if (d && d.abandon && !S.busy[d.id]) { quietly(function () { unpaint(d.id); }); drop(d.id); }
      hide();
    }
    return;
  }
  var sel = window.getSelection();
  if (sel && !sel.isCollapsed) return;
  if (e.target.closest("a[href], button, input, select, textarea, [contenteditable]")) return;
  if (S.pinned && S.tip === id) { hide(); return; }
  clearTimeout(hoverTimer);
  show(id, true, e.clientX, e.clientY);
}, true);

window.addEventListener("keydown", function (e) {
  if (e.key !== "Escape" || e.defaultPrevented || !S.tip) return;
  hide();
  e.preventDefault();
  e.stopPropagation();
}, true);
window.addEventListener("scroll", function () { if (S.tip) place(); }, true);
window.addEventListener("resize", function () { if (S.tip) place(); });

/* ------------------------------------------------------------------ boot */

load().then(function () {
  watcher.observe(document.body, { childList: true, subtree: true, characterData: true });
});
})();
