/* Comments pinned to the page, the way Figma has them.
 *
 * Petar, 24 September 2026 (fr_5879c0745f99): "The person would press C or a
 * comment button somewhere, probably next to the Ask AI icon, which should
 * also be floating. When you click the comment button, you can click on the
 * screen at one of the HTML elements and write a comment ... make the
 * interactions with comments the same as in Figma. Whatever hover does, do
 * the same thing. Whatever click does, do the same thing."
 *
 * So, as in Figma:
 *
 * - C, or the comment button, is comment mode: the pointer becomes a comment
 *   pointer, the element under it is outlined, and a click drops a pin there
 *   and opens a box for the first message. Escape leaves. Shift+C shows or
 *   hides every comment.
 * - A pin is its author's avatar. Hovering it opens it out into the first
 *   message, who wrote it and how many replies; clicking it opens the whole
 *   thread beside it, with a box to reply at the bottom.
 * - Typing @ in any box offers the people who can open the page; the one
 *   picked is tagged, and Rouh emails them the comment with a link that opens
 *   the page with that thread open (rouh/comments.py).
 * - A thread is resolved with the tick at its top, and its pin goes. The
 *   chevron beside the comment button shows resolved ones again, faded, where
 *   they were, and lists every comment.
 * - A pin is a point on its element, not a place on the page, and is drawn
 *   again whenever the page moves under it ("following the page").
 * - A comment whose element has been taken off the page keeps its place, is
 *   drawn with a dashed amber edge, and shows what the element looked like,
 *   from the snapshot kept when the comment was made.
 * - Any comment can be moved onto another element: Move in its ⋯ menu, or
 *   its pin held and dragged ("moving a comment").
 * - The chevron also has Ask AI answer every open thread, for somebody who
 *   may change the page (rouh/commentpass.py, fr_662a64715b9f). The pass runs
 *   on the server; this page says it is running, draws the replies as they
 *   land, and opens its report in the page's chat when it is done ("the
 *   pass", below). What Ask AI writes is drawn with the sparkle, not initials.
 *
 * It lives beside the Ask AI drawer (askai.js), which built #askai-root, and
 * draws everything inside a shadow root in it: a page's own styles cannot
 * reach it, askai.js already treats anything inside #askai-root as its own
 * rather than the page's, and the text Ask AI reads off the page leaves it
 * out. The page is sandboxed and cannot call out, so every request goes to
 * `/api/comments`, which the page around this one carries (askRelay in app.js
 * for the owner, reader.js for a person the page is shared with).
 *
 * Vanilla, no dependencies, no build step. */
(function () {
"use strict";

var CFG = window.ASKAI_COMMENTS;
if (!CFG || window.ASKAI_BAR_ONLY || window.__askaiComments) return;
var ROOT = document.getElementById("askai-root");
if (!ROOT) return;
window.__askaiComments = true;

var ME = CFG.me || {};
var API = "/api/comments";
var POLL = 15000;
var SVGNS = "http://www.w3.org/2000/svg";

/* ------------------------------------------------------------------ state */

var S = {
  threads: [], byId: {}, people: [],
  loc: {},            /* thread id -> { el, orphan } */
  pins: {},           /* thread id -> pin element */
  shots: {},          /* thread id -> snapshot markup, once fetched */
  mode: false,        /* comment mode */
  hidden: false,      /* Shift+C: every pin put away */
  resolved: false,    /* resolved comments drawn, faded */
  reveal: 0,          /* one resolved thread shown because it was asked for */
  open: 0,            /* the thread open beside its pin */
  draft: null,        /* the comment being written, before it is sent */
  editing: 0,         /* the message being changed */
  moving: 0,          /* the thread waiting for the element it is to be moved onto */
  list: false,        /* every comment, as a list */
  pass: null,         /* Ask AI's pass over the threads, as the server last told it */
  watching: 0,        /* the pass this page saw running, so it hears it finish */
  sig: "", loaded: false, busy: false
};

var KEY = "askai-cm:" + (window.ASKAI_DOC || location.pathname);
function recall(name) { try { return localStorage.getItem(KEY + ":" + name); } catch (e) { return null; } }
function store(name, on) {
  try { if (on) localStorage.setItem(KEY + ":" + name, "1"); else localStorage.removeItem(KEY + ":" + name); }
  catch (e) {}
}
S.resolved = recall("resolved") === "1";
S.hidden = recall("hidden") === "1";

/* ------------------------------------------------------------------ small */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }
function words(s) { return String(s || "").replace(/\s+/g, " ").trim(); }
/* Enter is a new line in a comment, and Ctrl+Enter, or Cmd+Enter on a Mac,
   sends it: the rule every message box in Rouh keeps (`isSendKey` in Rouh's
   app.js, and why). An empty box says so where there is a keyboard. */
function isSendKey(e) {
  return e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey &&
    !e.isComposing;
}
function withSendKeys(said) {
  if (!(window.matchMedia && window.matchMedia("(pointer: fine)").matches)) return said;
  var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  return said + " (" + (mac ? "\u2318\u21a9" : "Ctrl+Enter") + " to send)";
}
function hashOf(s) {
  var h = 5381, i;
  s = String(s || "");
  for (i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

var COLOURS = ["#6d5cf0", "#0ea5e9", "#16a34a", "#d97706", "#e11d48", "#db2777", "#0d9488",
               "#9333ea", "#2563eb", "#ca8a04"];
function colourOf(key) { return COLOURS[parseInt(hashOf(key), 36) % COLOURS.length]; }
function initials(name) {
  var n = words(name);
  if (n.indexOf("@") > 0) n = n.split("@")[0];
  var parts = n.split(/[\s._-]+/).filter(Boolean);
  if (!parts.length) return "?";
  var a = parts[0].charAt(0), b = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
  return (a + b).toUpperCase();
}
function avatar(who) {
  who = who || {};
  /* Ask AI is the sparkle it is everywhere else, never a pair of initials. */
  if (who.ai) return '<span class="av ai" aria-hidden="true">' + ICON.spark + "</span>";
  return '<span class="av" style="background:' + colourOf(who.key || who.name || "") + '" ' +
         'aria-hidden="true">' + esc(initials(who.name || who.key)) + "</span>";
}

function ago(t) {
  var s = Date.now() / 1000 - Number(t || 0);
  if (s < 45) return "just now";
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  if (s < 86400 * 7) { var d = Math.round(s / 86400); return d + (d === 1 ? " day ago" : " days ago"); }
  try {
    return new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch (e) { return ""; }
}

/* A message's words, with the people it tagged drawn as tags. Escaped first;
   the only markup added is the tag's own span. */
function said(body, mentions) {
  var out = esc(body);
  (mentions || []).slice().sort(function (a, b) {
    return String(b.name || "").length - String(a.name || "").length;
  }).forEach(function (m) {
    if (!m || !m.name) return;
    var at = esc("@" + m.name);
    out = out.split(at).join('<span class="mention">' + at + "</span>");
  });
  return out;
}

var ICON = {
  comment: '<svg viewBox="0 0 24 24"><path d="M4 18.5V6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H8.5z"/></svg>',
  chev: '<svg viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3"/></svg>',
  grip: '<svg viewBox="0 0 8 14"><circle cx="2" cy="2" r="1.3"/><circle cx="6" cy="2" r="1.3"/><circle cx="2" cy="7" r="1.3"/><circle cx="6" cy="7" r="1.3"/><circle cx="2" cy="12" r="1.3"/><circle cx="6" cy="12" r="1.3"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M12 3l1.9 5.3L19 10l-5.1 1.7L12 17l-1.9-5.3L5 10l5.1-1.7z"/><path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/></svg>',
  tick: '<svg viewBox="0 0 12 12"><path d="M2.5 6.4l2.3 2.3 4.7-5"/></svg>',
  resolve: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.5 2.5 4.9-5.2"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M12 19V5M6 11l6-6 6 6"/></svg>'
};

/* ------------------------------------------------------------------ DOM */

/* The host covers the window and takes no pointer itself; what is drawn in it
   takes the pointer where it is. Its own rules are the few that have to be on
   the page rather than in the shadow root: keeping the page's inherited styles
   out, making room for the drawer when it is open, the comment pointer, and
   the Ask AI sparkle moving into the one floating control. */
var host = document.createElement("div");
host.id = "askai-cm";
var sheet = document.createElement("style");
sheet.textContent =
  "#askai-root #askai-cm{all:initial!important;position:fixed!important;top:0!important;" +
  "left:0!important;right:0!important;bottom:0!important;z-index:2147483002!important;" +
  "pointer-events:none!important;display:block!important}" +
  "body.askai-open #askai-root #askai-cm{right:var(--askai-w)!important}" +
  "html.askai-cm-on #askai-root #askai-launch{display:none!important}" +
  "html.askai-cm-on #askai-dd-toggle{right:calc(var(--askai-dock-w,112px) + 22px)}" +
  "html.askai-cm-on body.askai-open #askai-dd-toggle{right:calc(var(--askai-w) + " +
    "var(--askai-dock-w,112px) + 22px)}" +
  "html.askai-commenting,html.askai-commenting *{cursor:url(\"data:image/svg+xml," +
  encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">' +
    '<path d="M3 25V9a6 6 0 0 1 6-6h10a6 6 0 0 1 6 6v6a6 6 0 0 1-6 6H7z" fill="#6d5cf0" stroke="#fff" stroke-width="2"/>' +
    '<path d="M14 8v8M10 12h8" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>') +
  "\") 3 25,crosshair!important}";
document.head.appendChild(sheet);
document.documentElement.classList.add("askai-cm-on");

var sh = host.attachShadow({ mode: "open" });
sh.innerHTML =
  '<link rel="stylesheet" href="' + esc(CFG.css || "") + '">' +
  '<div class="cm" id="cm">' +
    '<div class="layer" id="layer"></div>' +
    '<div class="hover" id="hover"><span class="tag" id="hoverTag"></span></div>' +
    '<div class="dock" id="dock" role="toolbar" aria-label="Comments and Ask AI">' +
      '<span class="grip" id="grip" title="Drag to move \u00b7 double-click to put it back" ' +
        'aria-hidden="true">' + ICON.grip + "</span>" +
      '<button type="button" class="cmt" id="cmtBtn" aria-pressed="false" ' +
        'title="Comment (C)" aria-label="Comment">' + ICON.comment + '<span class="n" id="count"></span></button>' +
      '<button type="button" class="chev" id="chevBtn" aria-haspopup="menu" aria-expanded="false" ' +
        'title="Comment options" aria-label="Comment options">' + ICON.chev + "</button>" +
      '<button type="button" class="mark" id="markBtn" hidden></button>' +
      '<button type="button" class="listen" id="listenBtn" hidden></button>' +
      '<span class="sep" aria-hidden="true"></span>' +
      '<button type="button" class="opts" id="optsBtn" hidden></button>' +
      '<button type="button" class="hist" id="histBtn" hidden></button>' +
      '<button type="button" class="edit" id="editBtn" hidden></button>' +
      '<button type="button" class="ask" id="askBtn">' + ICON.spark + "</button>" +
    "</div>" +
    '<div class="passbar" id="passBar" role="status" hidden><span class="spin" aria-hidden="true">' +
      ICON.spark + '</span><span id="passWords"></span></div>' +
    '<div class="menu" id="menu" role="menu" hidden>' +
      '<button type="button" class="mi ai" role="menuitem" id="miAi" hidden>' +
        '<span class="ck">' + ICON.spark + '</span><span class="lb">Answer comments with Ask AI</span></button>' +
      '<div class="hr" id="miAiHr" hidden></div>' +
      '<button type="button" class="mi" role="menuitemcheckbox" id="miResolved">' +
        '<span class="ck">' + ICON.tick + "</span>Show resolved comments</button>" +
      '<button type="button" class="mi" role="menuitemcheckbox" id="miHide">' +
        '<span class="ck">' + ICON.tick + '</span>Hide comments<span class="k">Shift+C</span></button>' +
      '<div class="hr"></div>' +
      '<button type="button" class="mi" role="menuitem" id="miList">' +
        '<span class="ck"></span>All comments</button>' +
    "</div>" +
    '<div class="hint" id="hint" role="status"><span><span id="hintWords">Click anything on the page to comment on it</span>' +
      '<span class="long"> &middot; <kbd>Esc</kbd> to <span id="hintEsc">stop</span></span></span>' +
      '<button type="button" id="hintStop">Done</button></div>' +
    '<aside class="list" id="list" hidden aria-label="All comments">' +
      '<div class="head"><span class="t">Comments</span>' +
        '<label class="filt"><input type="checkbox" id="listResolved"> Show resolved</label>' +
        '<button type="button" class="ic" id="listClose" title="Close" aria-label="Close">' + ICON.close + "</button>" +
      "</div><div class=\"items\" id=\"items\"></div>" +
    "</aside>" +
    '<div class="toast" id="toast" role="status"></div>' +
  "</div>";
ROOT.appendChild(host);

function $(id) { return sh.getElementById(id); }
var cm = $("cm"), layer = $("layer"), hover = $("hover"), hoverTag = $("hoverTag");
var cmtBtn = $("cmtBtn"), chevBtn = $("chevBtn"), askBtn = $("askBtn"), menu = $("menu");
var hint = $("hint"), list = $("list"), items = $("items"), toast = $("toast");

/* The sparkle is the drawer's own launcher, pressed: what it opens is still
   askai.js's to decide (the drawer here, or Rouh's column on the canvas). */
var launch = document.getElementById("askai-launch");
askBtn.title = (launch && launch.title) || "Ask AI";
askBtn.setAttribute("aria-label", askBtn.title);
askBtn.addEventListener("click", function () { if (launch) launch.click(); });

/* History and Options are in this same control. Petar, 24 September 2026
   (fr_b91369ea7ba2): "History would be another icon on the floating bar, next
   to the Ask AI button and later the Comments button." askai.js builds both in
   its own bar ("history and options"), which this control takes the place of,
   so each is pressed through here the way the sparkle is, and shows whatever
   its own button shows: whether its panel is open, and how many options the
   page has. A reader Rouh gives no History to has none here either. */
function mirror(mine, id) {
  var own = document.getElementById(id);
  if (!own) return;
  function sync() {
    mine.hidden = own.hidden;
    mine.innerHTML = own.innerHTML;
    mine.title = own.title;
    mine.setAttribute("aria-label", own.getAttribute("aria-label") || own.title);
    if (own.hasAttribute("aria-pressed")) mine.setAttribute("aria-pressed", own.getAttribute("aria-pressed"));
    mine.classList.toggle("on", own.classList.contains("on"));
    dockWidth();
  }
  sync();
  new MutationObserver(sync).observe(own, { attributes: true, childList: true, subtree: true,
                                            characterData: true });
  mine.addEventListener("click", function () { own.click(); });
}
/* How wide the control is, for the drill-down switch that sits beside it. */
function dockWidth() {
  var dock = $("dock");
  if (dock && dock.offsetWidth)
    document.documentElement.style.setProperty("--askai-dock-w", dock.offsetWidth + "px");
}
mirror($("histBtn"), "askai-hist-btn");
mirror($("optsBtn"), "askai-opts-btn");
/* Edit, the pencil: point at part of the page to change it (askai.js,
   "pointing"), with E, for a reader who may change the page. */
mirror($("editBtn"), "askai-edit-btn");
/* The highlighter, with H (highlights.js), beside the comment button. */
mirror($("markBtn"), "askai-mark-btn");
/* Listen to this page, with L (listen.js), beside the highlighter. */
mirror($("listenBtn"), "askai-listen-btn");
dockWidth();

/* The control can be dragged out of the way by its six dots. Petar, 1 October
   2026 (fr_efe6c2c3014f): "sometimes it covers navigation parts and important
   titles ... just having the ability to drag around temporary is helpful to
   uncover what is underneath." Temporary is the word: nothing is kept, so a
   reload or the next page puts it back in the corner, and so does a
   double-click on the dots. It is held inside the window while it moves and
   whenever the window (or the drawer beside it) changes its size. */
var grip = $("grip"), dragged = null, dragEnd = null;
function dockAt(x, y) {
  var dock = $("dock"), W = cm.clientWidth || window.innerWidth, H = cm.clientHeight || window.innerHeight;
  x = clamp(x, 0, Math.max(0, W - dock.offsetWidth));
  y = clamp(y, 0, Math.max(0, H - dock.offsetHeight));
  dragged = { x: x, y: y };
  dock.style.left = x + "px"; dock.style.top = y + "px"; dock.style.right = "auto";
  /* Ask AI's progress through the threads stays just under the control. */
  var pass = $("passBar");
  pass.style.top = (y + dock.offsetHeight + 7) + "px";
  pass.style.right = Math.max(0, W - x - dock.offsetWidth) + "px";
}
function dockHome() {
  dragged = null;
  ["dock", "passBar"].forEach(function (id) {
    var el = $(id); el.style.left = el.style.top = el.style.right = "";
  });
}
grip.addEventListener("pointerdown", function (e) {
  if (e.button) return;
  e.preventDefault();
  if (dragEnd) dragEnd();
  closeMenus();
  var r = $("dock").getBoundingClientRect(), c = cm.getBoundingClientRect();
  var dx = e.clientX - r.left, dy = e.clientY - r.top;
  grip.setPointerCapture(e.pointerId);
  grip.classList.add("on");
  function move(ev) { dockAt(ev.clientX - c.left - dx, ev.clientY - c.top - dy); }
  function done() {
    dragEnd = null;
    grip.classList.remove("on");
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", done);
    grip.removeEventListener("pointercancel", done);
    grip.removeEventListener("lostpointercapture", done);
  }
  dragEnd = done;
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", done);
  grip.addEventListener("pointercancel", done);
  grip.addEventListener("lostpointercapture", done);
});
grip.addEventListener("dblclick", dockHome);
function dockKeep() { if (dragged) dockAt(dragged.x, dragged.y); }
window.addEventListener("resize", dockKeep);
if (window.ResizeObserver) new ResizeObserver(dockKeep).observe(cm);

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
          : "Rouh could not do that: it said " + r.status + "."));
      }
      return j;
    });
  }, function () {
    throw new Error("Rouh could not be reached. Check the connection and try again.");
  });
}

function refresh() {
  if (S.busy) return Promise.resolve();
  return api("GET").then(apply, function () { /* the page is still fine without them */ });
}

function apply(data) {
  passSeen(data.pass || null);
  var sig = JSON.stringify([data.threads, data.people]);
  S.people = data.people || [];
  if (data.me) ME = data.me;
  if (sig === S.sig && S.loaded) return;
  S.sig = sig;
  S.loaded = true;
  S.threads = data.threads || [];
  S.byId = {};
  S.threads.forEach(function (t) { S.byId[t.id] = t; });
  relocate();
  if (S.open && !S.byId[S.open]) closeThread();
  if (S.open) drawThread(S.byId[S.open], true);
  if (S.list) drawList();
}

setInterval(function () {
  if (document.visibilityState === "visible" && !S.draft && !S.editing) refresh();
}, POLL);
document.addEventListener("visibilitychange", function () {
  if (document.visibilityState === "visible") refresh();
});

/* ------------------------------------------------------------------ elements of the page */

/* What is never commented on: Ask AI's own things, which are not the page. */
function ours(el) {
  if (!el || el.nodeType !== 1) return false;
  if (el.id && el.id.indexOf("askai-") === 0) return true;
  return !!el.classList && (el.classList.contains("askai-hl") || el.classList.contains("askai-mk"));
}
function inOurs(el) { return !!(el && ROOT.contains(el)); }

/* The element a press lands on, as a comment would be pinned to it. */
function target(el) {
  while (el && el.nodeType !== 1) el = el.parentNode;
  if (!el || inOurs(el)) return null;
  if (el.closest && el.closest("mark.askai-hl")) el = el.closest("mark.askai-hl").parentElement;
  /* A highlighted passage is the element it is in (highlights.js). */
  if (el && el.closest && el.closest("mark.askai-mk")) el = el.closest("mark.askai-mk").parentElement;
  if (!el || el === document.documentElement) return document.body;
  return el;
}

function tagOf(el) { return String(el.tagName || "").toLowerCase(); }
function textOf(el) { return words(el.textContent || ""); }
function clsOf(el) {
  var c = el.getAttribute && el.getAttribute("class");
  return words(c || "").split(" ").filter(function (x) { return x && x.indexOf("askai-") !== 0; }).join(" ");
}
/* What an element looks like apart from its words: its classes, and for a
   picture or a link, what it shows or where it goes. */
function sigOf(el) {
  return hashOf(tagOf(el) + "|" + clsOf(el) + "|" + String(el.getAttribute("src") || "").slice(0, 4000) +
                "|" + (el.getAttribute("alt") || "") + "|" + (el.getAttribute("href") || ""));
}
/* The words a reader sees on an element, as it is drawn - not its source,
   where two words in neighbouring tags run together. */
function wordsOn(el, most) {
  var w = words(el.innerText || el.textContent || "") || el.getAttribute("alt") ||
          el.getAttribute("aria-label") || el.getAttribute("title") || "";
  return w.length > most ? w.slice(0, most - 1) + "…" : w;
}
/* What the outline says while commenting: which element, and what it says. */
function labelOf(el) {
  var n = tagOf(el), c = clsOf(el).split(" ")[0];
  var name = el.id ? n + "#" + el.id : (c ? n + "." + c : n);
  var w = wordsOn(el, 60);
  return name + (w ? " “" + w + "”" : "");
}

/* Where an element is: its place among its kind, from <body> down. */
function indexIn(el) {
  var n = 0, tag = el.tagName, sib = el.parentElement ? el.parentElement.firstElementChild : null;
  for (; sib; sib = sib.nextElementSibling) {
    if (ours(sib)) continue;
    if (sib.tagName === tag) { n++; if (sib === el) return n; }
  }
  return n || 1;
}
function pathOf(el) {
  var parts = [];
  while (el && el !== document.body && el !== document.documentElement && el.parentElement) {
    parts.unshift(tagOf(el) + ":" + indexIn(el));
    el = el.parentElement;
    if (parts.length > 80) return "";
  }
  return parts.join("/");
}
function atPath(path) {
  var el = document.body;
  if (!path) return el;
  var segs = path.split("/");
  for (var i = 0; i < segs.length; i++) {
    var cut = segs[i].lastIndexOf(":"), tag = segs[i].slice(0, cut), want = Number(segs[i].slice(cut + 1));
    var k = 0, found = null, c;
    for (c = el.firstElementChild; c; c = c.nextElementSibling) {
      if (ours(c)) continue;
      if (tagOf(c) === tag && ++k === want) { found = c; break; }
    }
    if (!found) return null;
    el = found;
  }
  return el;
}

function scrollX() { return window.scrollX || document.documentElement.scrollLeft || 0; }
function scrollY() { return window.scrollY || document.documentElement.scrollTop || 0; }
function pageWidth() { return document.documentElement.clientWidth || window.innerWidth; }

/* Everything a comment keeps about where it is (rouh/comments.py, clean_anchor). */
function describe(el, x, y) {
  var r = el.getBoundingClientRect(), text = textOf(el);
  var up = el.parentElement && el !== document.body ? el.parentElement : null;
  var pr = up ? up.getBoundingClientRect() : null;
  return {
    path: pathOf(el), tag: tagOf(el), id: el.id || "", cls: clsOf(el).slice(0, 200),
    text: text.slice(0, 300), hash: hashOf(text), sig: sigOf(el), label: wordsOn(el, 120),
    fx: r.width ? clamp((x - r.left) / r.width, 0, 1) : 0,
    fy: r.height ? clamp((y - r.top) / r.height, 0, 1) : 0,
    x: x + scrollX(), y: y + scrollY(), w: pageWidth(),
    /* The point as a share of the element around it, for when the element
       goes: the part of the page it was in is a better "where it was" than
       a place on a page that may be read at another width. */
    pfx: pr && pr.width ? clamp((x - pr.left) / pr.width, 0, 1) : -1,
    pfy: pr && pr.height ? clamp((y - pr.top) / pr.height, 0, 1) : -1
  };
}

function wordSet(s) {
  var out = {};
  String(s || "").toLowerCase().split(/[^\p{L}\p{N}]+/u).forEach(function (w) { if (w) out[w] = 1; });
  return out;
}
function alike(a, b) {
  var A = wordSet(a), B = wordSet(b), both = 0, all = 0, k;
  for (k in A) { all++; if (B[k]) both++; }
  for (k in B) if (!A[k]) all++;
  return all ? both / all : 1;
}

/* The element a comment is pinned to, found again on the page as it is now,
   or null when it has gone.

   The page may have been changed since - by Ask AI, by whoever owns it - so
   the element is looked for in the order that is surest first: its own id;
   its place in the page, holding the same words; the same words anywhere,
   nearest to where it was; and its place, with words that are still mostly
   the same, which is an element edited where it stands. Anything else is an
   element that was taken off the page. */
function locate(a) {
  a = a || {};
  var tag = a.tag || "body";
  if (tag === "body" && !a.path) return document.body;
  if (a.id) {
    var byId = document.getElementById(a.id);
    if (byId && tagOf(byId) === tag && !inOurs(byId)) return byId;
  }
  var there = atPath(a.path);
  if (there && tagOf(there) !== tag) there = null;
  if (there && same(there, a)) return there;
  var found = a.hash ? byWords(a) : null;
  if (found) return found;
  if (there) {
    var now = textOf(there);
    if (!now && !a.text) { if (sigOf(there) === a.sig) return there; }
    else if (now && a.text && alike(now.slice(0, 300), a.text) >= 0.5) return there;
  }
  return a.quote ? byQuote(a) : null;
}
/* A comment Rouh pinned by a passage it quoted (rouh/page_comments.py): the
   smallest element of its kind, or of any kind, that still holds those words,
   for a page whose scripts draw it otherwise than its file says. */
function byQuote(a) {
  var want = words(a.quote).toLowerCase(), tags = [a.tag, "*"], i, j, all, el, best, bestN;
  for (j = 0; j < tags.length; j++) {
    all = document.getElementsByTagName(tags[j]);
    if (all.length > 4000) continue;
    best = null; bestN = Infinity;
    for (i = 0; i < all.length; i++) {
      el = all[i];
      if (inOurs(el) || /^(script|style|head|html|title|template|noscript)$/.test(tagOf(el))) continue;
      var t = textOf(el);
      if (t.length < bestN && t.toLowerCase().indexOf(want) >= 0) { best = el; bestN = t.length; }
    }
    if (best) return best;
  }
  return null;
}
function same(el, a) {
  var t = textOf(el);
  if (!a.hash) return true;
  if (hashOf(t) !== a.hash) return false;
  return t ? true : sigOf(el) === a.sig;
}
function byWords(a) {
  var all = document.getElementsByTagName(a.tag);
  if (all.length > 4000) return null;
  var best = null, bestD = Infinity, i, el;
  for (i = 0; i < all.length; i++) {
    el = all[i];
    if (inOurs(el) || !same(el, a)) continue;
    var r = el.getBoundingClientRect();
    var d = Math.abs(r.top + scrollY() - a.y) + Math.abs(r.left + scrollX() - a.x) / 4;
    if (d < bestD) { best = el; bestD = d; }
  }
  return best;
}

function relocate() {
  S.loc = {};
  S.threads.forEach(function (t) {
    var el = locate(t.anchor);
    S.loc[t.id] = { el: el, orphan: !el };
  });
  if (S.draft && !S.draft.el.isConnected) S.draft.el = document.body;
  watchSizes();
  draw();
}

/* Where a pin's point is on the screen now, or null when it is out of sight
   inside something scrolled away. */
function sized(el) {
  while (el && el !== document.body) {
    var r = el.getBoundingClientRect();
    if (r.width || r.height) return el;
    el = el.parentElement;
  }
  return el || document.body;
}
function hiddenIn(el, x, y) {
  for (var p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
    var cs = getComputedStyle(p);
    if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
    var r = p.getBoundingClientRect();
    if (x < r.left - 2 || x > r.right + 2 || y < r.top - 2 || y > r.bottom + 2) return true;
  }
  return false;
}
function pointOf(anchor, el) {
  var a = anchor || {};
  if (el) {
    var box = sized(el), r = box.getBoundingClientRect();
    var fx = box === el ? a.fx : 0, fy = box === el ? a.fy : 0;
    var x = r.left + (fx || 0) * r.width, y = r.top + (fy || 0) * r.height;
    if (box !== document.body && hiddenIn(box, x, y)) return null;
    return { x: x, y: y };
  }
  /* Gone: roughly where it was. In the part of the page it was in, when that
     is still there; otherwise at the place on the page, across as a share of
     its width, since it may be read at another width than it was made at. */
  var W = cm.clientWidth || window.innerWidth;
  var cut = String(a.path || "").lastIndexOf("/");
  var around = a.pfx >= 0 && a.path ? atPath(cut > 0 ? a.path.slice(0, cut) : "") : null;
  if (around) {
    var ar = around.getBoundingClientRect();
    if (ar.width || ar.height) {
      return { x: clamp(ar.left + a.pfx * ar.width, 8, W - 44), y: ar.top + a.pfy * ar.height };
    }
  }
  var px = a.w ? a.x / a.w * pageWidth() : a.x;
  return { x: clamp(px - scrollX(), 8, W - 44), y: a.y - scrollY() };
}

/* ------------------------------------------------------------------ pins */

function shown(t) {
  if (S.open === t.id || S.reveal === t.id) return true;
  if (S.hidden && !S.mode) return false;
  return !t.resolved || S.resolved;
}

function pinFor(t) {
  var pin = S.pins[t.id];
  if (!pin) {
    pin = document.createElement("div");
    pin.className = "pin";
    pin.tabIndex = 0;
    pin.setAttribute("role", "button");
    pin.dataset.id = t.id;
    pin.addEventListener("mouseenter", function () { peek(pin, true); });
    pin.addEventListener("mouseleave", function () { peek(pin, false); });
    pin.addEventListener("focus", function () { peek(pin, true); });
    pin.addEventListener("blur", function () { peek(pin, false); });
    pin.addEventListener("pointerdown", function (e) { grab(pin, e); });
    pin.addEventListener("click", function (e) {
      e.stopPropagation();
      if (dropped) { dropped = false; return; }   /* the end of a drag, not a press */
      var id = Number(pin.dataset.id);
      if (S.open === id) closeThread(); else openThread(id);
    });
    pin.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pin.click(); }
    });
    layer.appendChild(pin);
    S.pins[t.id] = pin;
  }
  var first = t.messages[0] || {}, replies = t.messages.length - 1;
  var orphan = S.loc[t.id] && S.loc[t.id].orphan;
  var drawnAs = [first.id, first.body, replies, t.resolved, orphan, first.author && first.author.name].join("|");
  if (pin.dataset.drawn !== drawnAs) {
    pin.dataset.drawn = drawnAs;
    pin.innerHTML =
      '<div class="bubble">' + avatar(t.author) +
        '<div class="peek">' +
          '<div class="ph"><b>' + esc(t.author.name) + "</b><span>" + esc(ago(t.created_at)) + "</span></div>" +
          '<div class="pt">' + said(first.body, first.mentions) + "</div>" +
          (replies > 0 ? '<div class="pr">' + replies + (replies === 1 ? " reply" : " replies") + "</div>" : "") +
          (t.resolved ? '<div class="pr">Resolved' + (t.resolved_by ? " by " + esc(t.resolved_by) : "") + "</div>" : "") +
          (orphan ? '<div class="gone"><b>Its part of the page was removed.</b>' +
                    '<div class="shot empty" data-shot="' + t.id + '">What it was on is being fetched…</div></div>' : "") +
        "</div>" +
      "</div>" +
      /* Outside the bubble, so they stay at full strength on a faded pin. */
      '<span class="tick" aria-hidden="true">' + ICON.tick + "</span>" +
      '<span class="lost" aria-hidden="true">!</span>';
    pin.setAttribute("aria-label", "Comment by " + t.author.name + ": " + (first.body || "").slice(0, 80) +
      (t.resolved ? " (resolved)" : "") + (orphan ? " (its element was removed)" : ""));
  }
  pin.classList.toggle("resolved", !!t.resolved);
  pin.classList.toggle("orphan", !!orphan);
  pin.classList.toggle("on", S.open === t.id);
  return pin;
}

function peek(pin, on) {
  if (on && S.open === Number(pin.dataset.id)) on = false;   /* its thread is already open */
  pin.classList.toggle("peeking", !!on);
  var bubble = pin.querySelector(".bubble");
  if (bubble) bubble.style.transform = "";
  if (!on) return;
  var box = pin.querySelector("[data-shot]");
  if (box) showShot(Number(pin.dataset.id), box, 220);
  /* Opened out near an edge, it moves over just enough to stay on the page,
     and never so far that it leaves the pointer that opened it. */
  if (bubble) {
    var r = bubble.getBoundingClientRect();
    var W = cm.clientWidth || window.innerWidth;
    var dx = Math.min(0, W - 8 - r.right), dy = Math.max(0, 8 - r.top);
    dx = Math.max(dx, 34 - r.width);
    if (dx || dy) bubble.style.transform = "translate(" + Math.round(dx) + "px," + Math.round(dy) + "px)";
  }
}

var drawing = 0;
function draw() {
  if (drawing) return;
  drawing = requestAnimationFrame(function () { drawing = 0; drawNow(); });
}
function drawNow() {
  var alive = {};
  S.threads.forEach(function (t) {
    if (!t.messages || !t.messages.length) return;
    var pin = pinFor(t);
    alive[t.id] = 1;
    if (dragging && dragging.id === t.id) return;   /* it is under the pointer */
    var p = shown(t) ? pointOf(t.anchor, S.loc[t.id] && S.loc[t.id].el) : null;
    if (!p) { pin.hidden = true; return; }
    pin.hidden = false;
    pin.style.left = Math.round(p.x) + "px";
    pin.style.top = Math.round(p.y) + "px";
  });
  Object.keys(S.pins).forEach(function (id) {
    if (!alive[id]) { S.pins[id].remove(); delete S.pins[id]; }
  });
  if (S.draft) placeDraft();
  if (S.open) placePop(openPop, S.pins[S.open]);
  if (S.mode && hovered) showHover(hovered.isConnected && !S.draft && !S.open ? hovered : null);
  if ((S.moving || dragging) && hovered) showHover(hovered.isConnected ? hovered : null);
  var open = S.threads.filter(function (t) { return !t.resolved; }).length;
  $("count").textContent = open ? String(open) : "";
  cmtBtn.title = "Comment (C)" + (open ? " · " + open + " open" : "");
}

window.addEventListener("scroll", draw, true);
window.addEventListener("resize", draw);

/* The page changes under the pins - it draws itself, Ask AI changes it, a
   passage asked about becomes a mark - so they are found again, a moment
   after it settles. Ask AI's own things changing is not the page changing. */
var settling = 0;
new MutationObserver(function (records) {
  var moved = false;
  for (var i = 0; i < records.length; i++) {
    if (inOurs(records[i].target)) continue;
    if (records[i].type === "attributes") { moved = true; continue; }
    clearTimeout(settling);
    settling = setTimeout(relocate, 250);
    return;
  }
  if (moved) draw();
}).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });

/* Following the page. A pin is kept as a point on its element, never as a
   place on the page, so it has to be drawn again whenever the page moves
   under it, and a page can move without anything being added or taken away: an accordion opened by a
   class, a picture or a font arriving, a transition running, a column that
   wraps. Petar, 29 September 2026 (fr_a383dc8329c0): "Once the page is
   shifted, the comments are not aligned. They should be bound to the element
   specifically and remember the element x y locally, not page absolute x y."
   So every change of size the browser can report, of the page and of each
   element a pin is on, draws them again; and a slow look every second
   catches what moves without changing size. */
var sizes = window.ResizeObserver ? new ResizeObserver(function () { draw(); }) : null;
var watched = [];
function watchSizes() {
  if (!sizes) return;
  sizes.disconnect();
  watched = [document.documentElement, document.body];
  Object.keys(S.loc).forEach(function (id) { if (S.loc[id].el) watched.push(S.loc[id].el); });
  watched.forEach(function (el) { sizes.observe(el); });
}
["load", "transitionend", "animationend", "toggle"].forEach(function (kind) {
  window.addEventListener(kind, function (e) { if (!inOurs(e.target)) draw(); }, true);
});
if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
setInterval(function () {
  if (document.visibilityState === "visible" && S.threads.length) draw();
}, 1000);

/* ------------------------------------------------------------------ the snapshot */
/* The element as it looks now, kept with the comment so that if it is taken
 * off the page, the comment can still show what it was about. It is the
 * element's own markup rebuilt with the styles the browser worked out for it
 * written onto each part, because the page's style sheet will not reach it
 * where it is shown. Pictures travel inside it when they are small; scripts,
 * frames, forms and anything that could call out never do. */

var LAYOUT = ["display", "position", "top", "right", "bottom", "left", "float", "box-sizing",
  "margin-top", "margin-right", "margin-bottom", "margin-left",
  "padding-top", "padding-right", "padding-bottom", "padding-left",
  "border-top", "border-right", "border-bottom", "border-left",
  "border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius",
  "border-bottom-left-radius", "background-color", "background-image", "opacity", "box-shadow",
  "overflow", "flex-direction", "flex-wrap", "justify-content", "align-items", "align-content",
  "row-gap", "column-gap", "flex-grow", "flex-shrink", "flex-basis", "align-self", "order",
  "grid-template-columns", "grid-template-rows", "grid-column", "grid-row",
  "text-decoration-line", "vertical-align", "max-width"];
var INHERITED = ["color", "font-family", "font-size", "font-weight", "font-style", "line-height",
  "letter-spacing", "text-align", "text-transform", "white-space", "list-style-type",
  "fill", "stroke", "stroke-width"];
var PLAIN = { "position": "static", "top": "auto", "right": "auto", "bottom": "auto", "left": "auto",
  "float": "none", "box-sizing": "content-box", "background-color": "rgba(0, 0, 0, 0)",
  "background-image": "none", "opacity": "1", "box-shadow": "none", "overflow": "visible",
  "flex-direction": "row", "flex-wrap": "nowrap", "justify-content": "normal", "align-items": "normal",
  "align-content": "normal", "row-gap": "normal", "column-gap": "normal", "flex-grow": "0",
  "flex-shrink": "1", "flex-basis": "auto", "align-self": "auto", "order": "0",
  "grid-template-columns": "none", "grid-template-rows": "none", "grid-column": "auto",
  "grid-row": "auto", "text-decoration-line": "none", "vertical-align": "baseline",
  "max-width": "none", "border-top-left-radius": "0px", "border-top-right-radius": "0px",
  "border-bottom-right-radius": "0px", "border-bottom-left-radius": "0px" };
var SKIP = { script: 1, style: 1, link: 1, meta: 1, noscript: 1, template: 1, iframe: 1,
  object: 1, embed: 1, audio: 1, source: 1, track: 1, base: 1, title: 1, head: 1, dialog: 1 };
var AS_SPAN = { button: 1, input: 1, select: 1, textarea: 1, a: 1, label: 1, output: 1 };
var SVG_TAGS = { svg: 1, g: 1, path: 1, rect: 1, circle: 1, ellipse: 1, line: 1, polyline: 1,
  polygon: 1, text: 1, tspan: 1, defs: 1, lineargradient: 1, radialgradient: 1, stop: 1,
  clippath: 1, title: 1 };
var SVG_ATTRS = ["viewBox", "d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2",
  "width", "height", "points", "fill", "stroke", "stroke-width", "stroke-linecap",
  "stroke-linejoin", "stroke-dasharray", "opacity", "fill-opacity", "stroke-opacity",
  "transform", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
  "font-size", "font-weight", "text-anchor", "dominant-baseline", "fill-rule", "clip-rule",
  "clip-path", "id", "preserveAspectRatio"];
var SHOT_MAX = 180000;

function styleOf(el, cs, parentCs, root) {
  var out = [], i, p, v;
  for (i = 0; i < LAYOUT.length; i++) {
    p = LAYOUT[i]; v = cs.getPropertyValue(p);
    if (!v) continue;
    if (p.indexOf("border-") === 0 && !/radius/.test(p)) {
      if (/^0px|none/.test(v) || / none /.test(v)) continue;
    } else if (/^(margin|padding)-/.test(p)) {
      if (v === "0px") continue;
    } else if (PLAIN[p] === v) continue;
    if (p === "background-image" && /url\(/i.test(v)) continue;
    if (root && (p === "position" || p === "top" || p === "right" || p === "bottom" ||
                 p === "left" || p === "float" || /^margin-/.test(p))) continue;
    if (!root && p === "position" && v !== "relative" && v !== "absolute") continue;
    out.push(p + ":" + v);
  }
  for (i = 0; i < INHERITED.length; i++) {
    p = INHERITED[i]; v = cs.getPropertyValue(p);
    if (!v || (!root && parentCs && parentCs.getPropertyValue(p) === v)) continue;
    if ((p === "fill" || p === "stroke") && /url\(/i.test(v)) continue;
    out.push(p + ":" + v);
  }
  if (root && cs.display === "inline") out.push("display:inline-block");
  var t = tagOf(el), r;
  if (root || t === "img" || t === "svg" || t === "canvas" || t === "video" || t === "input" ||
      t === "select" || t === "textarea") {
    r = el.getBoundingClientRect();
    out.push("width:" + Math.round(r.width) + "px");
    if (!root || t === "img" || t === "svg") out.push("height:" + Math.round(r.height) + "px");
  }
  return out.join(";").replace(/"/g, "'");
}

/* The colour a part of the page is drawn on: its own, or the nearest one
   behind it, so dark words on a light page are not shown on the dark card. */
function backdrop(el) {
  for (var p = el; p && p.nodeType === 1; p = p.parentElement) {
    var c = getComputedStyle(p).backgroundColor;
    if (c && c !== "transparent" && !/rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(c)) return c;
  }
  return "#ffffff";
}

function shoot(el) {
  var tries = [{ nodes: 500, pictures: 150000 }, { nodes: 160, pictures: 0 }];
  for (var i = 0; i < tries.length; i++) {
    var out = shootWith(el, tries[i]);
    if (out && out.length <= SHOT_MAX) return out;
  }
  var d = document.createElement("div");
  d.setAttribute("style", "padding:10px;font:14px/1.45 sans-serif;color:#1b1c1e;background:" + backdrop(el));
  d.textContent = textOf(el).slice(0, 2000) || labelOf(el);
  return d.outerHTML;
}

function shootWith(el, limits) {
  var count = 0, budget = limits.pictures;
  function copy(node, parentCs, root, inSvg) {
    if (node.nodeType === 3) return document.createTextNode(node.nodeValue);
    if (node.nodeType !== 1 || ours(node) || ++count > limits.nodes) return null;
    var t = tagOf(node);
    if (SKIP[t]) return null;
    var cs = getComputedStyle(node);
    if (cs.display === "none") return null;
    var out, i;
    if (inSvg || t === "svg") {
      if (!SVG_TAGS[t]) return null;
      out = document.createElementNS(SVGNS, node.tagName);
      for (i = 0; i < SVG_ATTRS.length; i++) {
        var v = node.getAttribute(SVG_ATTRS[i]);
        if (v != null && !/url\((?!\s*#)/i.test(v)) out.setAttribute(SVG_ATTRS[i], v);
      }
      if (t === "svg") out.setAttribute("style", styleOf(node, cs, parentCs, root));
      else out.setAttribute("style", ["fill", "stroke", "stroke-width", "opacity"].map(function (p) {
        var v = cs.getPropertyValue(p);
        return v && !/url\(/i.test(v) ? p + ":" + v : "";
      }).filter(Boolean).join(";").replace(/"/g, "'"));
      for (var c = node.firstChild; c; c = c.nextSibling) {
        var got = copy(c, cs, false, true);
        if (got) out.appendChild(got);
      }
      return out;
    }
    if (t === "img" || t === "canvas" || t === "video" || t === "picture") {
      out = document.createElement(t === "img" ? "img" : "div");
      var src = t === "img" ? String(node.currentSrc || node.getAttribute("src") || "") : "";
      if (t === "canvas") {
        try { src = node.toDataURL("image/png"); out = document.createElement("img"); } catch (e) { src = ""; }
      }
      if (/^data:image\//i.test(src) && src.length <= budget) {
        budget -= src.length;
        out.setAttribute("src", src);
        if (node.getAttribute("alt")) out.setAttribute("alt", node.getAttribute("alt"));
      } else if (out.tagName === "IMG") {
        out = document.createElement("div");
      }
      var st = styleOf(node, cs, parentCs, root);
      if (out.tagName !== "IMG") st += ";background:repeating-linear-gradient(45deg,#8883 0 6px,#8881 6px 12px)";
      out.setAttribute("style", st);
      return out;
    }
    out = document.createElement(AS_SPAN[t] ? "span" : (t === "body" || t === "html" ? "div" : t));
    out.setAttribute("style", styleOf(node, cs, parentCs, root));
    if (t === "td" || t === "th") {
      if (node.colSpan > 1) out.setAttribute("colspan", node.colSpan);
      if (node.rowSpan > 1) out.setAttribute("rowspan", node.rowSpan);
    }
    if (t === "input" || t === "textarea") {
      out.textContent = node.value || node.getAttribute("placeholder") || "";
      return out;
    }
    if (t === "select") {
      out.textContent = node.selectedOptions && node.selectedOptions[0] ? node.selectedOptions[0].text : "";
      return out;
    }
    for (var k = node.firstChild; k; k = k.nextSibling) {
      var part = copy(k, cs, false, false);
      if (part) out.appendChild(part);
      if (count > limits.nodes) break;
    }
    return out;
  }
  var made = copy(el, el.parentElement ? getComputedStyle(el.parentElement) : null, true, false);
  if (!made) return "";
  var wrap = document.createElement("div");
  wrap.setAttribute("style", "background:" + backdrop(el) + ";padding:8px;display:inline-block");
  wrap.appendChild(made);
  return wrap.outerHTML;
}

/* A snapshot, drawn. It is somebody else's markup, so it is never put in as
   markup: it is read into a document that runs nothing and loads nothing, and
   built again here out of a short list of elements and attributes. Its styles
   lose anything that would fetch, and it is drawn in a shadow root of its own,
   scaled to fit, clipped to its box. */
var HTML_OK = { div: 1, span: 1, p: 1, h1: 1, h2: 1, h3: 1, h4: 1, h5: 1, h6: 1, ul: 1, ol: 1,
  li: 1, dl: 1, dt: 1, dd: 1, table: 1, thead: 1, tbody: 1, tfoot: 1, tr: 1, td: 1, th: 1,
  caption: 1, colgroup: 1, col: 1, strong: 1, b: 1, em: 1, i: 1, u: 1, s: 1, del: 1, ins: 1,
  small: 1, sub: 1, sup: 1, code: 1, pre: 1, kbd: 1, samp: 1, blockquote: 1, q: 1, cite: 1,
  abbr: 1, mark: 1, time: 1, section: 1, article: 1, header: 1, footer: 1, nav: 1, aside: 1,
  main: 1, figure: 1, figcaption: 1, details: 1, summary: 1, img: 1, br: 1, hr: 1, wbr: 1 };
/* What goes with everything inside it, words and all: nothing a reader of the
   snapshot should see, and nothing that could run or load. */
var DROP = { script: 1, style: 1, noscript: 1, template: 1, iframe: 1, frame: 1, frameset: 1,
  object: 1, embed: 1, applet: 1, link: 1, meta: 1, base: 1, head: 1, title: 1, textarea: 1,
  select: 1, option: 1, button: 1, input: 1, form: 1, math: 1, foreignobject: 1 };
var SVG_OK = {};
SVG_ATTRS.forEach(function (a) { SVG_OK[a.toLowerCase()] = a; });

function safeStyle(v) {
  return String(v || "")
    .replace(/url\s*\(\s*(['"]?)(?!data:image\/)[^)]*\)/gi, "none")
    .replace(/expression\s*\(|javascript:|@import|behavior\s*:|-moz-binding/gi, "")
    .replace(/position\s*:\s*(fixed|sticky)/gi, "position:relative");
}

function safeSnapshot(markup) {
  var doc;
  try { doc = new DOMParser().parseFromString("<div>" + markup + "</div>", "text/html"); }
  catch (e) { return null; }
  function build(node, inSvg) {
    if (node.nodeType === 3) return document.createTextNode(node.nodeValue);
    if (node.nodeType !== 1) return null;
    var t = tagOf(node), out, i, a;
    if (DROP[t]) return null;
    if (inSvg || t === "svg") {
      if (!SVG_TAGS[t]) return null;
      out = document.createElementNS(SVGNS, t === "lineargradient" ? "linearGradient"
        : t === "radialgradient" ? "radialGradient" : t === "clippath" ? "clipPath" : t);
      for (i = 0; i < node.attributes.length; i++) {
        a = node.attributes[i];
        var name = SVG_OK[a.name.toLowerCase()];
        if (name && !/url\((?!\s*#)/i.test(a.value) && !/javascript:/i.test(a.value)) out.setAttribute(name, a.value);
        else if (a.name === "style") out.setAttribute("style", safeStyle(a.value));
      }
    } else if (HTML_OK[t]) {
      out = document.createElement(t);
      var st = node.getAttribute("style");
      if (st) out.setAttribute("style", safeStyle(st));
      if (t === "img") {
        var src = node.getAttribute("src") || "";
        if (/^data:image\/(png|jpe?g|gif|webp|avif|svg\+xml)[;,]/i.test(src)) out.setAttribute("src", src);
        if (node.getAttribute("alt")) out.setAttribute("alt", node.getAttribute("alt"));
      }
      if (t === "td" || t === "th") {
        ["colspan", "rowspan"].forEach(function (n) {
          var v = parseInt(node.getAttribute(n), 10);
          if (v > 1 && v < 100) out.setAttribute(n, String(v));
        });
      }
    } else {
      /* Something not on the list: its words stay, it does not. */
      out = document.createDocumentFragment();
    }
    for (var c = node.firstChild; c; c = c.nextSibling) {
      var got = build(c, inSvg || t === "svg");
      if (got) out.appendChild(got);
    }
    return out;
  }
  return build(doc.body.firstChild, false);
}

function showShot(id, box, width) {
  if (!box || box.dataset.drawn === "1") return;
  var draw = function (markup) {
    /* Asked for twice before the first answer came - a hover and a focus -
       it is drawn once: a box has room for one shadow root. */
    if (!box.isConnected || box.dataset.drawn === "1") return;
    box.dataset.drawn = "1";
    var built = markup ? safeSnapshot(markup) : null;
    if (!built) {
      box.classList.add("empty");
      box.textContent = "No picture of it was kept.";
      return;
    }
    box.classList.remove("empty");
    box.textContent = "";
    var inner = box.attachShadow ? box.attachShadow({ mode: "open" }) : box;
    var style = document.createElement("style");
    style.textContent = ":host{all:initial;display:block;position:relative;overflow:hidden;" +
      "contain:paint}.s{position:absolute;left:0;top:0;transform-origin:0 0}";
    var stage = document.createElement("div");
    stage.className = "s";
    stage.appendChild(built);
    inner.appendChild(style);
    inner.appendChild(stage);
    var w = Math.max(stage.scrollWidth, 1), h = Math.max(stage.scrollHeight, 1);
    var room = box.clientWidth || width || 260;
    var scale = Math.min(1, room / w);
    stage.style.transform = "scale(" + scale + ")";
    box.style.height = Math.min(Math.ceil(h * scale), 190) + "px";
  };
  if (S.shots[id] != null) { draw(S.shots[id]); return; }
  api("POST", { do: "snapshot", thread: id }).then(function (j) {
    S.shots[id] = j.snapshot || "";
    draw(S.shots[id]);
  }, function () { draw(""); });
}

/* ------------------------------------------------------------------ writing */

/* One box to write in - a new comment, a reply, an edit - with @ offering the
   people who can open the page, and who was picked kept with it. */
function composer(opts) {
  var wrap = document.createElement("div");
  wrap.className = "composer";
  wrap.innerHTML =
    '<div class="box">' +
      '<textarea rows="1" placeholder="' + esc(withSendKeys(opts.placeholder)) + '" aria-label="' + esc(opts.placeholder) + '"></textarea>' +
      '<div class="bar">' +
        '<button type="button" class="at" title="Mention somebody" aria-label="Mention somebody">@</button>' +
        '<span class="sp"></span>' +
        (opts.edit
          ? '<button type="button" class="plain cancel">Cancel</button><button type="button" class="plain go save">Save</button>'
          : '<button type="button" class="send" title="Send" aria-label="Send" disabled>' + ICON.send + "</button>") +
      "</div>" +
    "</div>" +
    '<div class="ments" hidden role="listbox"></div>' +
    '<div class="err" role="alert"></div>';
  var ta = wrap.querySelector("textarea"), ments = wrap.querySelector(".ments");
  var sendBtn = wrap.querySelector(".send, .save"), err = wrap.querySelector(".err");
  var tagged = {}, choices = [], at = 0, asking = null;
  (opts.mentions || []).forEach(function (m) { tagged[m.key] = m.name; });
  ta.value = opts.text || "";

  function size() {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
    if (!opts.edit) sendBtn.disabled = !ta.value.trim();
  }
  function query() {
    var before = ta.value.slice(0, ta.selectionStart);
    var m = /(^|\s)@([^\s@]{0,40})$/.exec(before);
    return m ? { from: before.length - m[2].length - 1, q: m[2].toLowerCase() } : null;
  }
  function close() { ments.hidden = true; asking = null; }
  function listPeople() {
    asking = query();
    if (!asking) { close(); return; }
    choices = S.people.filter(function (p) {
      if (p.key === ME.key) return false;
      if (!asking.q) return true;
      var hay = (p.name + " " + p.email).toLowerCase();
      return hay.indexOf(asking.q) === 0 || hay.indexOf(" " + asking.q) >= 0 ||
             p.email.toLowerCase().indexOf(asking.q) === 0;
    }).slice(0, 8);
    at = 0;
    ments.innerHTML = choices.length ? choices.map(function (p, i) {
      return '<button type="button" class="who' + (i === 0 ? " on" : "") + '" role="option" data-i="' + i + '">' +
        avatar(p) + '<span class="nm"><b>' + esc(p.name) + '</b><span class="em">' +
        esc(p.owner ? "Owns this page" : (p.joined ? p.email : p.email + " · invited, no account yet")) +
        "</span></span></button>";
    }).join("") : '<div class="none">' + (S.people.length > 1
      ? "Nobody on this page is called that."
      : "Nobody else can open this page yet. Share it with somebody, and they can be tagged here.") + "</div>";
    ments.hidden = false;
    var r = wrap.getBoundingClientRect();
    ments.classList.toggle("up", r.bottom + 230 > (cm.clientHeight || window.innerHeight));
  }
  function pick(i) {
    var p = choices[i];
    if (!p || !asking) return;
    var name = "@" + p.name + " ";
    ta.value = ta.value.slice(0, asking.from) + name + ta.value.slice(ta.selectionStart);
    var caret = asking.from + name.length;
    ta.setSelectionRange(caret, caret);
    tagged[p.key] = p.name;
    close();
    size();
    ta.focus();
  }
  function mark(i) {
    var all = ments.querySelectorAll(".who");
    if (!all.length) return;
    at = (i + all.length) % all.length;
    for (var k = 0; k < all.length; k++) all[k].classList.toggle("on", k === at);
    all[at].scrollIntoView({ block: "nearest" });
  }

  ta.addEventListener("input", function () { size(); listPeople(); err.textContent = ""; });
  ta.addEventListener("click", listPeople);
  ta.addEventListener("keydown", function (e) {
    /* Keys typed here are this box's: never Rouh's Backspace or Escape, and
       never a page's own shortcut. Search (Cmd+K) is the one that goes on. */
    if (!((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey))) e.stopPropagation();
    if (!ments.hidden && choices.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); mark(at + 1); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); mark(at - 1); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pick(at); return; }
    }
    if (isSendKey(e)) { e.preventDefault(); submit(); }
  });
  ta.addEventListener("keyup", function (e) {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End") listPeople();
  });
  ["keypress", "keyup"].forEach(function (k) { ta.addEventListener(k, function (e) { e.stopPropagation(); }); });
  ments.addEventListener("mousedown", function (e) { e.preventDefault(); });
  ments.addEventListener("click", function (e) {
    var b = e.target.closest(".who");
    if (b) pick(Number(b.dataset.i));
  });
  wrap.querySelector(".at").addEventListener("click", function () {
    var s = ta.selectionStart, before = ta.value.slice(0, s);
    var add = (before && !/\s$/.test(before) ? " " : "") + "@";
    ta.value = before + add + ta.value.slice(s);
    ta.setSelectionRange(s + add.length, s + add.length);
    ta.focus();
    size();
    listPeople();
  });
  function submit() {
    var text = ta.value.trim();
    if (!text || wrap.classList.contains("busy")) return;
    var keys = Object.keys(tagged).filter(function (k) { return text.indexOf("@" + tagged[k]) >= 0; });
    opts.send(text, keys);
  }
  if (sendBtn) sendBtn.addEventListener("click", submit);
  var cancel = wrap.querySelector(".cancel");
  if (cancel && opts.cancel) cancel.addEventListener("click", opts.cancel);

  size();
  return {
    el: wrap, ta: ta,
    text: function () { return ta.value; },
    focus: function () { setTimeout(function () { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); size(); }, 0); },
    busy: function (on) { wrap.classList.toggle("busy", !!on); ta.disabled = !!on; if (sendBtn) sendBtn.disabled = !!on || !ta.value.trim(); },
    error: function (words) { err.textContent = words || ""; },
    listing: function () { return !ments.hidden; },
    stopListing: close,
    clear: function () { ta.value = ""; tagged = {}; size(); }
  };
}

var toastTimer = 0;
function say(words, bad) {
  toast.textContent = words;
  toast.classList.toggle("bad", !!bad);
  toast.classList.add("on");
  toast.style.bottom = S.mode ? "70px" : "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toast.classList.remove("on"); }, 6000);
}

/* What became of the letters to the people a message tagged. */
function sayLetters(letters) {
  if (!letters || !letters.length) return;
  var went = letters.filter(function (l) { return l.sent; }).map(function (l) { return l.name; });
  var not = letters.filter(function (l) { return !l.sent; });
  var out = [];
  if (went.length) out.push("Emailed " + went.join(", ") + ".");
  not.forEach(function (l) { out.push(l.name + " was tagged, but no letter went: " + l.why + "."); });
  say(out.join(" "), !!not.length);
}

/* ------------------------------------------------------------------ popovers */

function placePop(pop, pin) {
  if (!pop || pop.hidden) return;
  /* Beside the pin, and clear of the list of comments when it is open. */
  var W = (cm.clientWidth || window.innerWidth) - (S.list ? list.offsetWidth : 0);
  var H = cm.clientHeight || window.innerHeight;
  var x, y;
  if (pin && !pin.hidden) {
    var r = pin.getBoundingClientRect();
    x = r.right + 10; y = r.top;
    if (x + pop.offsetWidth > W - 8) x = r.left - pop.offsetWidth - 10;
  } else {
    x = (W - pop.offsetWidth) / 2; y = 80;
  }
  pop.style.left = Math.round(clamp(x, 8, Math.max(8, W - pop.offsetWidth - 8))) + "px";
  pop.style.top = Math.round(clamp(y, 8, Math.max(8, H - pop.offsetHeight - 8))) + "px";
}

/* ---- a new comment ---- */

function startDraft(el, x, y) {
  var anchor = describe(el, x, y);
  var pin = document.createElement("div");
  pin.className = "pin draft";
  pin.innerHTML = '<div class="bubble">' + avatar(ME) + "</div>";
  layer.appendChild(pin);
  var pop = document.createElement("div");
  pop.className = "pop new";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", "New comment");
  var box = composer({ placeholder: "Add a comment", send: sendDraft });
  pop.appendChild(box.el);
  cm.appendChild(pop);
  S.draft = { el: el, anchor: anchor, pin: pin, pop: pop, box: box };
  placeDraft();
  box.focus();
}
function placeDraft() {
  var d = S.draft;
  if (!d) return;
  var p = pointOf(d.anchor, d.el.isConnected ? d.el : null);
  if (!p) { d.pin.hidden = true; d.pop.hidden = true; return; }
  d.pin.hidden = false; d.pop.hidden = false;
  d.pin.style.left = Math.round(p.x) + "px";
  d.pin.style.top = Math.round(p.y) + "px";
  placePop(d.pop, d.pin);
}
function dropDraft() {
  if (!S.draft) return;
  S.draft.pin.remove();
  S.draft.pop.remove();
  S.draft = null;
}
function sendDraft(text, keys) {
  var d = S.draft;
  if (!d) return;
  d.box.busy(true);
  var shot = "";
  try { shot = shoot(d.el.isConnected ? d.el : document.body); } catch (e) { shot = ""; }
  S.busy = true;
  api("POST", { do: "start", anchor: d.anchor, snapshot: shot, body: text, mentions: keys })
    .then(function (j) {
      S.busy = false;
      var t = j.thread;
      S.shots[t.id] = shot;
      S.threads.push(t);
      S.byId[t.id] = t;
      S.loc[t.id] = { el: d.el.isConnected ? d.el : null, orphan: !d.el.isConnected };
      watchSizes();
      dropDraft();
      drawNow();
      openThread(t.id);
      sayLetters(j.letters);
    }, function (err) {
      S.busy = false;
      if (S.draft !== d) return;
      d.box.busy(false);
      d.box.error(err.message);
    });
}

/* ---- an open thread ---- */

var openPop = null, openBox = null;

function openThread(id, scrolled) {
  var t = S.byId[id];
  if (!t) return;
  closeMenus();
  if (S.draft) {
    if (S.draft.box.text().trim()) { shake(S.draft.pop); return; }
    dropDraft();
  }
  if (S.open && S.open !== id) closeThread();
  S.open = id;
  if (t.resolved && !S.resolved) S.reveal = id;
  drawNow();
  var pin = S.pins[id];
  if (!scrolled && pin && (pin.hidden || !onScreen(pin))) { bringIntoView(t, function () { openThread(id, true); }); return; }
  Object.keys(S.pins).forEach(function (k) { S.pins[k].classList.remove("peeking"); });
  drawThread(t, false);
  if (S.list) drawList();
}

function onScreen(pin) {
  var r = pin.getBoundingClientRect(), W = cm.clientWidth || window.innerWidth, H = cm.clientHeight || window.innerHeight;
  return r.bottom > 0 && r.top < H && r.right > 0 && r.left < W;
}

function bringIntoView(t, then) {
  var l = S.loc[t.id];
  if (l && l.el) l.el.scrollIntoView({ block: "center", inline: "nearest" });
  else window.scrollTo(0, Math.max(0, (t.anchor.y || 0) - window.innerHeight / 2));
  setTimeout(function () { drawNow(); then(); }, 60);
}

function closeThread() {
  if (openPop) { openPop.remove(); openPop = null; openBox = null; }
  var was = S.open;
  S.open = 0;
  S.editing = 0;
  if (S.reveal === was) S.reveal = 0;
  draw();
  if (S.list) drawList();
}

function shake(pop) {
  pop.classList.remove("shake");
  void pop.offsetWidth;
  pop.classList.add("shake");
  var ta = pop.querySelector("textarea");
  if (ta) ta.focus();
}

function drawThread(t, again) {
  if (!t) return;
  if (again && S.editing) return;      /* never pull an edit out from under the person */
  var orphan = S.loc[t.id] && S.loc[t.id].orphan;
  var fresh = !openPop || openPop.dataset.id !== String(t.id);
  if (fresh) {
    if (openPop) openPop.remove();
    openPop = document.createElement("div");
    openPop.className = "pop";
    openPop.dataset.id = String(t.id);
    openPop.setAttribute("role", "dialog");
    openPop.innerHTML = '<div class="top"></div>';
    /* The reply box is made once per open thread and kept when the thread
       is drawn again - a reply arriving, a refresh - so what is being typed,
       and who in it is tagged, stays. */
    openBox = composer({ placeholder: "Reply", send: function (text, keys) { sendReply(t.id, text, keys); } });
    openPop.appendChild(openBox.el);
    cm.appendChild(openPop);
  }
  var msgsWas = openPop.querySelector(".msgs");
  var atEnd = !msgsWas || msgsWas.scrollHeight - msgsWas.scrollTop - msgsWas.clientHeight < 30;
  openPop.setAttribute("aria-label", "Comment by " + t.author.name);
  var top = openPop.querySelector(".top");
  top.innerHTML =
    '<div class="head"><span class="t">' + (t.resolved ? "Resolved" : "Comment") + "</span>" +
      /* Resolve says so in words: it is how an open item is closed, and a
         tick alone was not found (fr_a383dc8329c0, "How do you close open
         items?"). */
      '<button type="button" class="ic res" aria-pressed="' + (t.resolved ? "true" : "false") + '" title="' +
        (t.resolved ? "Open this comment again" : "Close this comment: it is dealt with") + '">' + ICON.resolve +
        '<span class="lb">' + (t.resolved ? "Re-open" : "Resolve") + "</span></button>" +
      '<button type="button" class="ic more tmore" title="More" aria-label="More" aria-haspopup="menu" aria-expanded="false">' + ICON.more + "</button>" +
      '<button type="button" class="ic x" title="Close" aria-label="Close">' + ICON.close + "</button>" +
    "</div>" +
    (orphan ? '<div class="gone"><b>The part of the page this was on has been removed.</b>' +
      '<div class="was">' + (t.anchor.label ? "It read “" + esc(t.anchor.label) + "”, and looked like this:"
        : "It looked like this:") + "</div>" +
      '<div class="shot empty" data-shot="' + t.id + '">Fetching what it looked like…</div>' +
      '<button type="button" class="fix">Move it onto another part of the page</button></div>' : "") +
    (t.resolved ? '<div class="state">' + ICON.tick + "Resolved" + (t.resolved_by ? " by " + esc(t.resolved_by) : "") +
      (t.resolved_at ? " · " + esc(ago(t.resolved_at)) : "") + "</div>" : "") +
    '<div class="msgs" role="list">' + t.messages.map(function (m, i) {
      return '<div class="msg" role="listitem" data-m="' + m.id + '" data-first="' + (i === 0 ? 1 : 0) + '">' + avatar(m.author) +
        '<div class="body"><div class="mh"><b>' + esc(m.author.name) + '</b><span class="when" title="' +
        esc(new Date(m.created_at * 1000).toLocaleString()) + '">' + esc(ago(m.created_at)) +
        (m.edited ? " · edited" : "") + "</span></div>" +
        '<div class="text">' + said(m.body, m.mentions) + "</div></div>" +
        (m.mine || m.can_delete ? '<button type="button" class="ic more mmore" title="More" aria-label="More" aria-haspopup="menu" aria-expanded="false">' + ICON.more + "</button>" : "") +
      "</div>";
    }).join("") + "</div>";
  top.querySelector(".x").addEventListener("click", closeThread);
  top.querySelector(".res").addEventListener("click", function () { resolve(t.id, !t.resolved); });
  var tm = top.querySelector(".tmore");
  if (tm) tm.addEventListener("click", function (e) {
    e.stopPropagation();
    var acts = [{ label: "Move", act: function () { startMove(t.id); } }];
    if (t.can_delete) acts.push({ label: "Delete thread", bad: true, sure: "Press again to delete the whole thread",
                                  act: function () { removeThread(t.id); } });
    openMenuAt(tm, acts);
  });
  var fix = top.querySelector(".fix");
  if (fix) fix.addEventListener("click", function (e) { e.stopPropagation(); startMove(t.id); });
  [].forEach.call(top.querySelectorAll(".mmore"), function (b) {
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      var row = b.closest(".msg"), id = Number(row.dataset.m), first = row.dataset.first === "1";
      var m = t.messages.filter(function (x) { return x.id === id; })[0];
      var acts = [];
      if (m && m.mine) acts.push({ label: "Edit", act: function () { editMessage(t, m, row); } });
      if (m && (m.mine || m.can_delete)) acts.push({ label: first ? "Delete thread" : "Delete", bad: true,
        sure: first ? "Press again to delete the whole thread" : "Press again to delete",
        act: function () { removeMessage(t.id, id); } });
      openMenuAt(b, acts);
    });
  });
  if (orphan) showShot(t.id, top.querySelector("[data-shot]"), 300);
  var msgs = top.querySelector(".msgs");
  if (atEnd) msgs.scrollTop = msgs.scrollHeight;
  placePop(openPop, S.pins[t.id]);
  if (fresh) openBox.focus();
  var pin = S.pins[t.id];
  if (pin) pin.classList.add("on");
}

function sendReply(id, text, keys) {
  var box = openBox;
  box.busy(true);
  S.busy = true;
  api("POST", { do: "reply", thread: id, body: text, mentions: keys }).then(function (j) {
    S.busy = false;
    var t = S.byId[id];
    if (t) t.messages.push(j.message);
    box.busy(false);
    if (box === openBox) box.clear();
    if (S.open === id) drawThread(t, true);
    draw();
    sayLetters(j.letters);
  }, function (err) {
    S.busy = false;
    box.busy(false);
    box.error(err.message);
  });
}

function resolve(id, done) {
  api("POST", { do: done ? "resolve" : "reopen", thread: id }).then(function (j) {
    var t = S.byId[id];
    if (!t) return;
    t.resolved = j.resolved;
    t.resolved_by = j.resolved_by;
    t.resolved_at = j.resolved_at;
    if (done) {
      /* Resolved is gone from the page, as it is in Figma, unless resolved
         comments are being shown. */
      closeThread();
      say("Resolved. It is still in All comments, and Show resolved comments puts it back on the page.");
    } else {
      drawThread(t, true);
    }
    if (S.list) drawList();
    drawNow();
  }, function (err) { say(err.message, true); });
}

function removeThread(id) {
  api("POST", { do: "delete", thread: id }).then(function () { forget(id); }, function (err) { say(err.message, true); });
}
function removeMessage(threadId, messageId) {
  api("POST", { do: "delete", message: messageId }).then(function (j) {
    if (j.removed === "thread") { forget(threadId); return; }
    var t = S.byId[threadId];
    if (!t) return;
    t.messages = t.messages.filter(function (m) { return m.id !== messageId; });
    if (S.open === threadId) drawThread(t, true);
    draw();
  }, function (err) { say(err.message, true); });
}
function forget(id) {
  if (S.open === id) closeThread();
  S.threads = S.threads.filter(function (t) { return t.id !== id; });
  delete S.byId[id];
  delete S.loc[id];
  drawNow();
  if (S.list) drawList();
}

function editMessage(t, m, row) {
  S.editing = m.id;
  var text = row.querySelector(".text");
  var box = composer({
    placeholder: "Edit your comment", text: m.body, mentions: m.mentions, edit: true,
    cancel: function () { S.editing = 0; drawThread(t, true); },
    send: function (body, keys) {
      box.busy(true);
      api("POST", { do: "edit", message: m.id, body: body, mentions: keys }).then(function (j) {
        S.editing = 0;
        t.messages = t.messages.map(function (x) { return x.id === m.id ? j.message : x; });
        drawThread(t, true);
        draw();
        sayLetters(j.letters);
      }, function (err) { box.busy(false); box.error(err.message); });
    }
  });
  box.el.classList.add("inline");
  text.replaceWith(box.el);
  box.focus();
}

/* ---- menus ---- */

var floating = null;
function openMenuAt(button, acts) {
  closeMenus();
  if (!acts.length) return;
  var m = document.createElement("div");
  m.className = "menu";
  m.setAttribute("role", "menu");
  acts.forEach(function (a) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "mi" + (a.bad ? " bad" : "");
    b.setAttribute("role", "menuitem");
    b.textContent = a.label;
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      /* Nothing on a sandboxed page can ask "are you sure?" in a window of
         its own, so a deletion asks by being pressed a second time. */
      if (a.sure && !b.classList.contains("sure")) {
        b.classList.add("sure");
        b.textContent = a.sure;
        return;
      }
      closeMenus();
      a.act();
    });
    m.appendChild(b);
  });
  cm.appendChild(m);
  var r = button.getBoundingClientRect(), W = cm.clientWidth || window.innerWidth;
  m.style.top = Math.round(r.bottom + 4) + "px";
  m.style.left = Math.round(clamp(r.right - m.offsetWidth, 8, W - m.offsetWidth - 8)) + "px";
  button.setAttribute("aria-expanded", "true");
  floating = { menu: m, button: button };
  var first = m.querySelector(".mi");
  if (first) first.focus();
}

function closeMenus() {
  if (floating) {
    floating.menu.remove();
    floating.button.setAttribute("aria-expanded", "false");
    floating = null;
  }
  if (!menu.hidden) {
    menu.hidden = true;
    chevBtn.setAttribute("aria-expanded", "false");
  }
}

function drawMenu() {
  $("miResolved").setAttribute("aria-checked", S.resolved ? "true" : "false");
  $("miHide").setAttribute("aria-checked", S.hidden ? "true" : "false");
  var ai = $("miAi"), running = passRunning();
  ai.hidden = $("miAiHr").hidden = !CFG.ai_pass;
  ai.setAttribute("aria-disabled", running ? "true" : "false");
  ai.querySelector(".lb").textContent = running ? "Ask AI is answering the comments…"
    : "Answer comments with Ask AI";
  ai.title = running ? "It is going through the open threads now"
    : "Ask AI reads every open thread, with the page and its notes, and adds to the ones " +
      "where it has something useful to say";
}

chevBtn.addEventListener("click", function (e) {
  e.stopPropagation();
  if (!menu.hidden) { closeMenus(); return; }
  closeMenus();
  drawMenu();
  menu.hidden = false;
  chevBtn.setAttribute("aria-expanded", "true");
  var r = $("dock").getBoundingClientRect(), W = cm.clientWidth || window.innerWidth;
  menu.style.top = Math.round(r.bottom + 6) + "px";
  menu.style.left = Math.round(clamp(r.right - menu.offsetWidth, 8, W - menu.offsetWidth - 8)) + "px";
  (CFG.ai_pass ? $("miAi") : $("miResolved")).focus();
});
$("miAi").addEventListener("click", function () { closeMenus(); startPass(); });
$("miResolved").addEventListener("click", function () { setResolved(!S.resolved); closeMenus(); });
$("miHide").addEventListener("click", function () { setHidden(!S.hidden); closeMenus(); });
$("miList").addEventListener("click", function () { closeMenus(); openList(); });
menu.addEventListener("keydown", menuKeys);
cm.addEventListener("keydown", function (e) {
  if (floating && floating.menu.contains(e.target)) menuKeys(e);
});
function menuKeys(e) {
  var box = floating ? floating.menu : menu;
  var all = [].slice.call(box.querySelectorAll(".mi")).filter(function (b) { return !b.hidden; });
  var at = all.indexOf(sh.activeElement);
  if (e.key === "ArrowDown") { e.preventDefault(); e.stopPropagation(); all[(at + 1) % all.length].focus(); }
  if (e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); all[(at - 1 + all.length) % all.length].focus(); }
}

function setResolved(on) {
  S.resolved = !!on;
  store("resolved", S.resolved);
  $("listResolved").checked = S.resolved;
  if (!S.resolved && S.open && S.byId[S.open] && S.byId[S.open].resolved) S.reveal = S.open;
  drawNow();
  if (S.list) drawList();
}
function setHidden(on) {
  S.hidden = !!on;
  store("hidden", S.hidden);
  if (S.hidden && S.open) closeThread();
  drawNow();
  say(S.hidden ? "Comments are hidden. Shift+C, or the comment options, show them again." : "Comments are shown.");
}

/* ---- every comment, as a list ---- */

function openList() {
  S.list = true;
  $("listResolved").checked = S.resolved;
  list.hidden = false;
  drawList();
  $("listClose").focus();
}
function closeList() { S.list = false; list.hidden = true; }
$("listClose").addEventListener("click", closeList);
$("listResolved").addEventListener("change", function () { setResolved($("listResolved").checked); });

function drawList() {
  var open = S.threads.filter(function (t) { return !t.resolved; });
  var done = S.threads.filter(function (t) { return t.resolved; });
  function row(t) {
    var first = t.messages[0] || {}, replies = t.messages.length - 1;
    var orphan = S.loc[t.id] && S.loc[t.id].orphan;
    return '<button type="button" class="item' + (t.resolved ? " resolved" : "") + (S.open === t.id ? " on" : "") +
      '" data-id="' + t.id + '">' + avatar(t.author) + '<span class="body"><span class="mh"><b>' +
      esc(t.author.name) + '</b><span class="when">' + esc(ago(t.created_at)) + "</span></span>" +
      '<span class="text">' + said(first.body, first.mentions) + "</span>" +
      '<span class="tags">' + (replies > 0 ? "<span>" + replies + (replies === 1 ? " reply" : " replies") + "</span>" : "") +
      (t.resolved ? '<span class="tg ok">Resolved</span>' : "") +
      (orphan ? '<span class="tg lost">Its element was removed</span>' : "") + "</span></span></button>";
  }
  var html = "";
  if (!S.threads.length) html = '<div class="empty">No comments on this page yet. Press C, or the comment button, and click anything on the page.</div>';
  else {
    html += open.length ? open.map(row).join("") : '<div class="empty">Every comment here is resolved.</div>';
    if (done.length) {
      html += '<div class="sec">Resolved · ' + done.length + "</div>";
      html += S.resolved ? done.map(row).join("") :
        '<div class="empty">Tick Show resolved to list them, and to see them faded on the page.</div>';
    }
  }
  items.innerHTML = html;
  [].forEach.call(items.querySelectorAll(".item"), function (b) {
    b.addEventListener("click", function () { focusThread(Number(b.dataset.id)); });
  });
}

/* Open a thread from anywhere - the list, a letter's link - wherever it is on
   the page: scrolled to, revealed if it was resolved, and opened. */
function focusThread(id) {
  var t = S.byId[id];
  if (!t) { say("That comment is not on this page any more.", true); return; }
  if (t.resolved) S.reveal = id;
  if (S.hidden) setHidden(false);
  bringIntoView(t, function () { openThread(id, true); });
}

/* ------------------------------------------------------------------ the pass */
/* Ask AI answering every open thread (rouh/commentpass.py). Petar, 24
 * September 2026 (fr_662a64715b9f): "This option should be clickable from the
 * chevron of the comments and it should answer everything that makes sense as
 * a thread... I also want a quick report on the whole run displayed somewhere
 * and it could be in the chat, the same chat that edits the page."
 *
 * Pressing it sends what only this page knows: the words on the page as the
 * reader sees them, and for each thread the element it is pinned to - what it
 * is, which heading it is under, how far down the page, its markup, and the
 * marks that say which of the page's options it is part of. The server does
 * the rest and says how it is going with the comments this page already
 * fetches, more often while it runs. When it finishes the replies are drawn,
 * a sentence says what happened, and its report opens in the page's chat:
 * Rouh's column on the canvas, the drawer on a page shared with somebody. */

var PASS_POLL = 3000;
var passTimer = 0;

function passRunning() { return !!(S.pass && S.pass.state === "running"); }

function passSeen(p) {
  S.pass = p;
  if (p && p.state === "running") S.watching = p.id;
  else if (S.watching && (!p || p.id === S.watching)) {
    S.watching = 0;
    if (p && p.said) say(p.said, p.state === "failed");
    if (p && p.report) openReport(p.report);
    if (p && p.offered) {
      try { document.dispatchEvent(new CustomEvent("askai-options-stale")); } catch (e) {}
    }
  }
  drawPass();
  if (passRunning() && !passTimer) passPoll();
}

/* Asked after more often while it runs, whatever else the page is doing: a
   comment being written holds the usual refresh back, and this is not that. */
function passPoll() {
  clearTimeout(passTimer);
  passTimer = setTimeout(function () {
    passTimer = 0;
    if (!passRunning()) return;
    (S.busy ? Promise.resolve() : api("GET").then(apply, function () {})).then(function () {
      if (passRunning() && !passTimer) passPoll();
    });
  }, PASS_POLL);
}

function drawPass() {
  var bar = $("passBar"), p = S.pass;
  var on = !!(p && p.state === "running");
  bar.hidden = !on;
  if (on) {
    $("passWords").textContent = !p.threads ? "Ask AI is reading the comments…"
      : "Ask AI is answering " + p.threads + (p.threads === 1 ? " thread" : " threads") +
        (p.mine ? "…" : ", for " + p.by + "…");
  }
  if (!menu.hidden) drawMenu();
}

/* The report, in the page's chat. On the canvas that is Rouh's column, which
   opens the topic the way a mark pressed on the page does; for a reader it is
   the drawer in this page (askai.js). */
function openReport(id) {
  if (window.ASKAI_HOSTED && window.parent && window.parent !== window) {
    try { window.parent.postMessage({ type: "rouh-askai", what: "thread", id: Number(id) }, "*"); } catch (e) {}
    return;
  }
  try { document.dispatchEvent(new CustomEvent("askai-open-thread", { detail: Number(id) })); } catch (e) {}
}

/* The words a reader sees on the page, as it draws them, and none of Ask
   AI's own: its drawer, its tabs over the options, the drill-down. Read off
   the live page rather than a copy of it, because a copy is not drawn and
   would hand over the words of the page's scripts and styles too. All of
   them: they were cut at 120,000 characters, which left the bottom of a long
   page out of every pass; the server keeps them to the page's own size
   (`askai.page_text`), and the model's context window is the only limit. */
function pageWords() {
  var out = [];
  for (var n = document.body.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 3) { if (words(n.nodeValue)) out.push(words(n.nodeValue)); continue; }
    if (n.nodeType !== 1 || n.id === "askai-root" || n.id === "askai-dd" ||
        /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(n.tagName)) continue;
    var t = "";
    try { t = n.innerText || ""; } catch (e) { t = ""; }
    if (t.trim()) out.push(t);
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

var MARK = "data-rouh-at";
function markOf(el) {
  var v = el && el.getAttribute ? el.getAttribute(MARK) : null;
  return v == null ? null : Number(v);
}
/* The heading an element is under: the last one before it in the page. */
function headingOver(el) {
  var all = document.querySelectorAll("h1,h2,h3,h4"), found = "";
  for (var i = 0; i < all.length && i < 3000; i++) {
    var h = all[i];
    if (inOurs(h) || h === el || h.contains(el)) continue;
    if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) found = wordsOn(h, 150);
    else break;
  }
  return found;
}
function insideOf(el) {
  var chain = [], p = el.parentElement;
  while (p && p !== document.body && p !== document.documentElement && chain.length < 4) {
    var c = clsOf(p).split(" ")[0];
    chain.unshift(tagOf(p) + (p.id ? "#" + p.id : (c ? "." + c : "")));
    p = p.parentElement;
  }
  return chain.join(" > ");
}
/* An element's markup as the model is shown it: without Rouh's own marks and
   classes, and without pictures written into it, which are a long run of
   letters that say nothing. */
function markupOf(el) {
  if (!el || el === document.body || el === document.documentElement) return "";
  var html = "";
  try { html = el.outerHTML || ""; } catch (e) { return ""; }
  return html.replace(/\sdata-rouh-at="\d+"/g, "")
             .replace(/\s?askai-[a-z-]+/g, "")
             .replace(/data:[^"')\s]{120,}/g, "data:…")
             .slice(0, 4000);
}
function elementsFor() {
  var out = {}, H = Math.max(document.documentElement.scrollHeight, 1);
  S.threads.forEach(function (t) {
    if (t.resolved) return;
    var l = S.loc[t.id], el = l && l.el;
    if (!el) { out[t.id] = { found: false, tag: t.anchor.tag, label: t.anchor.label || t.anchor.text }; return; }
    var r = el.getBoundingClientRect(), marks = [], holds = [];
    for (var p = el; p && p.nodeType === 1; p = p.parentElement) {
      var m = markOf(p);
      if (m != null) marks.push(m);
    }
    var inner = el.querySelectorAll ? el.querySelectorAll("[" + MARK + "]") : [];
    for (var i = 0; i < inner.length && i < 120; i++) holds.push(Number(inner[i].getAttribute(MARK)));
    out[t.id] = {
      found: true, tag: tagOf(el), label: wordsOn(el, 200), section: headingOver(el),
      inside: insideOf(el), down: clamp((r.top + scrollY()) / H, 0, 1), html: markupOf(el),
      marks: marks, holds: holds
    };
  });
  return out;
}

function startPass() {
  if (!CFG.ai_pass) return;
  if (passRunning()) { say("Ask AI is already answering the comments. Its replies will appear here."); return; }
  /* Running from the press, before the server has said how many threads it
     is taking, so the bar does not guess. */
  S.pass = { state: "running", threads: 0, mine: true, id: -1 };
  drawPass();
  api("POST", { do: "ai_pass", context: pageWords(), elements: elementsFor() }).then(function (j) {
    var p = j.pass || {};
    if (p.state === "nothing") { S.pass = null; drawPass(); say(p.said); return; }
    passSeen(p);
    say("Ask AI is reading the " + p.threads + (p.threads === 1 ? " open thread" : " open threads") +
        " with the page and its notes. Its replies, and a report in the page's chat, come when it is done.");
  }, function (err) {
    S.pass = null;
    drawPass();
    say(err.message, true);
  });
}

/* ------------------------------------------------------------------ comment mode */

function picking() { return document.documentElement.classList.contains("askai-picking"); }
function marking() { return document.documentElement.classList.contains("askai-marking"); }

function setMode(on) {
  on = !!on;
  /* Edit (E, askai.js) is the other tool that takes the page's clicks:
     asking for comments puts it down, as picking a tool does in Figma. */
  if (on && picking()) {
    try { document.dispatchEvent(new CustomEvent("askai-stop-pointing")); } catch (e) {}
    if (picking()) return;
  }
  /* And so does the highlighter (highlights.js). */
  if (on && marking()) {
    try { document.dispatchEvent(new CustomEvent("askai-stop-marking")); } catch (e) {}
    if (marking()) return;
  }
  if (on && S.moving) stopMove(false);
  S.mode = on;
  hintSays();
  cmtBtn.classList.toggle("on", on);
  cmtBtn.setAttribute("aria-pressed", on ? "true" : "false");
  document.documentElement.classList.toggle("askai-commenting", on);
  hint.classList.toggle("on", on);
  if (!on) {
    showHover(null);
    if (S.draft && !S.draft.box.text().trim()) dropDraft();
  }
  closeMenus();
  drawNow();
}

cmtBtn.addEventListener("click", function (e) { e.stopPropagation(); setMode(!S.mode); });
$("hintStop").addEventListener("click", function () { if (S.moving) stopMove(true); else setMode(false); });

var hovered = null;
function showHover(el) {
  var same = el && el === hovered && hover.classList.contains("on");
  hovered = el;
  if (!el) { hover.classList.remove("on"); return; }
  var r = el.getBoundingClientRect();
  hover.style.left = Math.round(r.left - 2) + "px";
  hover.style.top = Math.round(r.top - 2) + "px";
  hover.style.width = Math.round(r.width + 4) + "px";
  hover.style.height = Math.round(r.height + 4) + "px";
  hover.classList.toggle("below", r.top < 28);
  if (!same) hoverTag.textContent = labelOf(el);
  hover.classList.add("on");
}

/* The outline says what a press would comment on, so it is only there while a
   press would: not over a comment being written or read, which a press on the
   page puts away first. */
window.addEventListener("mousemove", function (e) {
  if (dragging || picking()) return;
  if (S.moving) { showHover(inOurs(e.target) ? null : target(e.target)); return; }
  if (!S.mode) return;
  showHover(inOurs(e.target) || S.draft || S.open ? null : target(e.target));
}, true);

/* While commenting, a press on the page is a place to comment, never a press
   on the page's own buttons and links, and never the start of a selection. */
["mousedown", "mouseup", "pointerdown", "pointerup", "dblclick", "auxclick", "contextmenu"].forEach(function (kind) {
  window.addEventListener(kind, function (e) {
    if ((!S.mode && !S.moving) || picking() || inOurs(e.target)) return;
    e.stopPropagation();
    if (kind === "mousedown" || kind === "dblclick") e.preventDefault();
  }, true);
});

window.addEventListener("click", function (e) {
  /* The click a dragged pin's release makes lands wherever it was let go:
     it is the end of the drag, never a press on the page. */
  if (dropped) { e.preventDefault(); e.stopPropagation(); return; }
  if (inOurs(e.target)) {
    /* A press inside this layer that is not on a menu closes a menu. */
    if (e.composedPath && (floating || !menu.hidden)) {
      var path = e.composedPath();
      if (path.indexOf(menu) < 0 && (!floating || path.indexOf(floating.menu) < 0) && path.indexOf(chevBtn) < 0) closeMenus();
    }
    return;
  }
  closeMenus();
  if (S.moving && !picking()) {
    e.preventDefault();
    e.stopPropagation();
    var onto = target(e.target);
    if (onto) moveTo(S.moving, onto, e.clientX, e.clientY);
    return;
  }
  if (!S.mode || picking()) {
    /* Outside commenting, a press on the page puts an open thread away, as a
       press on the canvas does in Figma, and goes on to the page. */
    if (S.open) closeThread();
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  if (S.open) { closeThread(); return; }
  if (S.draft) {
    if (S.draft.box.text().trim()) { shake(S.draft.pop); return; }
    dropDraft();
  }
  var el = target(e.target);
  if (el) startDraft(el, e.clientX, e.clientY);
}, true);

/* ------------------------------------------------------------------ moving a comment */
/* A comment put onto another part of the page. Petar, 29 September 2026
 * (fr_a383dc8329c0): "if the elements get deleted, the comments have
 * exclamation marks ... But we don't have a means of fixing them. Maybe we
 * can hold and drag on top of their new html element? Or have a move option
 * in the dot dot dot menu, that afterwards allow you to select an html
 * element." Both are here, for any comment, not only one whose element went:
 *
 * - Move, in a thread's ⋯ menu (and the button in the notice that its part of
 *   the page was removed), is a pick like comment mode's: the element under
 *   the pointer is outlined, a press puts the comment on it, Escape leaves it
 *   where it was.
 * - A pin held and dragged goes where it is dropped, onto the element under
 *   it. A press that does not move is still a press, and opens the thread.
 *
 * Either way the comment is described again from the element it lands on,
 * with the point as a share of that element, and a new picture of it is kept,
 * so it is found and drawn there after a reload, and if that element goes
 * too, it shows what it was on last. Anybody who can comment may move a
 * comment, as anybody may resolve one: it changes where it points, not what
 * anybody said. */

function hintSays() {
  var moving = !!S.moving;
  $("hintWords").textContent = moving ? "Click the part of the page this comment is about"
    : "Click anything on the page to comment on it";
  $("hintEsc").textContent = moving ? "leave it where it is" : "stop";
  $("hintStop").textContent = moving ? "Cancel" : "Done";
  hint.classList.toggle("on", S.mode || moving);
}

function startMove(id) {
  if (!S.byId[id]) return;
  closeMenus();
  if (S.mode) setMode(false);
  if (picking()) {
    try { document.dispatchEvent(new CustomEvent("askai-stop-pointing")); } catch (e) {}
    if (picking()) return;
  }
  if (S.open) closeThread();
  if (S.draft) dropDraft();
  S.moving = id;
  S.reveal = id;
  document.documentElement.classList.add("askai-commenting");
  hintSays();
  drawNow();
  var pin = S.pins[id];
  if (pin) pin.classList.add("moving");
}

function stopMove(reopen) {
  var id = S.moving;
  if (!id) return;
  S.moving = 0;
  if (S.pins[id]) S.pins[id].classList.remove("moving");
  if (!S.mode) document.documentElement.classList.remove("askai-commenting");
  showHover(null);
  hintSays();
  if (S.reveal === id) S.reveal = 0;
  drawNow();
  if (reopen) openThread(id);
}

function moveTo(id, el, x, y) {
  var t = S.byId[id];
  if (!t) { stopMove(false); return; }
  var anchor = describe(el, x, y), shot = "";
  try { shot = shoot(el); } catch (e) { shot = ""; }
  api("POST", { do: "move", thread: id, anchor: anchor, snapshot: shot }).then(function (j) {
    t.anchor = (j.thread && j.thread.anchor) || anchor;
    S.shots[id] = shot;
    S.loc[id] = { el: el, orphan: false };
    watchSizes();
    stopMove(false);
    var w = wordsOn(el, 60);
    say(w ? "Moved onto “" + w + "”." : "Moved onto the " + tagOf(el) + " there.");
  }, function (err) {
    stopMove(false);
    say(err.message, true);
  });
}

/* Holding a pin and dragging it. The point of a pin is its lower left
   corner, so the pin is carried by where it was taken hold of, and the
   comment goes where that point is let go. */
var dragging = null, dropped = false;
function grab(pin, e) {
  if (e.button !== 0 || S.moving || picking() || e.pointerType === "touch") return;
  var id = Number(pin.dataset.id), r = pin.getBoundingClientRect();
  var held = { id: id, pin: pin, x0: e.clientX, y0: e.clientY,
               dx: e.clientX - r.left, dy: e.clientY - r.bottom, on: false };
  function under(ev) {
    var x = ev.clientX - held.dx, y = ev.clientY - held.dy;
    return { x: x, y: y, el: target(document.elementFromPoint(x + 1, y - 1)) };
  }
  function move(ev) {
    if (!held.on) {
      if (Math.abs(ev.clientX - held.x0) + Math.abs(ev.clientY - held.y0) < 6) return;
      held.on = true;
      dragging = held;
      if (S.open === id) closeThread();
      pin.classList.remove("peeking");
      pin.classList.add("dragging");
    }
    var at = under(ev);
    pin.style.left = Math.round(at.x) + "px";
    pin.style.top = Math.round(at.y) + "px";
    showHover(at.el);
  }
  function up(ev) {
    window.removeEventListener("pointermove", move, true);
    window.removeEventListener("pointerup", up, true);
    if (!held.on) return;
    var at = under(ev);
    dragging = null;
    dropped = true;
    setTimeout(function () { dropped = false; }, 0);
    pin.classList.remove("dragging");
    showHover(null);
    if (at.el) moveTo(id, at.el, at.x, at.y); else drawNow();
  }
  window.addEventListener("pointermove", move, true);
  window.addEventListener("pointerup", up, true);
}

/* ------------------------------------------------------------------ keys */

function typing(e) {
  var t = e.composedPath ? e.composedPath()[0] : e.target;
  return !!(t && t.nodeType === 1 && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable));
}

/* Escape puts away the nearest thing first, and when it has put something
   away it goes no further: handed up, it would close the page. */
window.addEventListener("keydown", function (e) {
  if (e.key !== "Escape" || picking()) return;
  var done = true;
  if (floating || !menu.hidden) closeMenus();
  else if (S.moving) stopMove(true);
  else if (openBox && openBox.listing()) openBox.stopListing();
  else if (S.draft && S.draft.box.listing()) S.draft.box.stopListing();
  else if (S.editing && S.byId[S.open]) { S.editing = 0; drawThread(S.byId[S.open], true); }
  else if (S.draft) dropDraft();
  else if (S.open) closeThread();
  else if (S.list) closeList();
  else if (S.mode) setMode(false);
  else done = false;
  if (done) { e.preventDefault(); e.stopPropagation(); }
}, true);

/* C, as in Figma: comment mode. Shift+C: every comment shown or put away.
   After the page's own keys, so a page with a C of its own keeps it. */
window.addEventListener("keydown", function (e) {
  if (e.key !== "c" && e.key !== "C") return;
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e)) return;
  e.preventDefault();
  if (e.shiftKey) setHidden(!S.hidden);
  else setMode(!S.mode);
}, false);

/* The highlighter asked for while commenting: comment mode ends. */
document.addEventListener("askai-stop-commenting", function () {
  if (S.moving) stopMove(false);
  if (S.mode) setMode(false);
});

/* Point, in Ask AI, and comment mode both take the page's clicks, so starting
   one ends the other. */
new MutationObserver(function () {
  if (picking() && S.mode) setMode(false);
  if (picking() && S.moving) stopMove(false);
}).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

/* ------------------------------------------------------------------ boot */

refresh().then(function () {
  var wanted = Number(CFG.open) || 0;
  if (wanted) setTimeout(function () { focusThread(wanted); }, 150);
});
drawNow();
})();
