/* Ask AI - injected into every page by _askai/server.py.
 *
 * Select a passage, ask about it, and the passage stays highlighted permanently
 * with its thread attached. A highlight IS a thread that was started from a
 * passage, so there is no separate highlight store to drift.
 *
 * Vanilla, no dependencies, no build step. Builds all of its own DOM so a host
 * page needs zero markup. */
(function () {
"use strict";

if (window.__askaiLoaded) return;
window.__askaiLoaded = true;

var DOC = window.ASKAI_DOC || "";
var Q = "doc=" + encodeURIComponent(DOC);

/* ------------------------------------------------------------------ hosted */
/* Whether the page around this one is drawing the conversation itself.
 *
 * Rouh frames this page on its canvas and has a conversation column beside the
 * frame. Until 23 September 2026 this file opened a chat of its own over the
 * page while that column stood there holding another one, which is the two
 * chats on one screen that Petar asked to be made into one.
 *
 * So when Rouh says it is hosting (askai.drawer_head), the drawer here is
 * built and never opened - it is hidden by a rule Rouh puts in the page - and
 * the three things that can only happen in the page happen here and are handed
 * up: a passage being selected, a mark being pressed, and the words on the
 * page being read.
 *
 * Built and hidden rather than left out, because this same file, unhosted, is
 * the whole Ask AI a reader who is not the owner gets on a page that has been
 * shared with them. One branch, one file, and the two cannot drift.
 *
 * CAN_EDIT is a second and separate question: whether this reader may have
 * the page changed. Since 24 September 2026 Ask AI makes the change itself
 * (askai.py, "Changing the page"), so it is answered for readers who are not
 * the owner too - a person the page was shared with to change, and a visitor
 * to a link that says so - and it is Rouh that decides, never this page. Where
 * it is true there is a way to point at part of the page, and Change on the
 * bar over a selection. VERSION is which version of the page this is, handed
 * back with anything pointed at (askai.page_version). */
var UP = null;
try { UP = (window.parent && window.parent !== window) ? window.parent : null; }
catch (e) { UP = null; }
var HOSTED = !!window.ASKAI_HOSTED && !!UP;
var CAN_EDIT = !!window.ASKAI_CAN_EDIT && !!UP;
var VERSION = String(window.ASKAI_VERSION || "");

/* Enter is a new line in the box, and Ctrl+Enter, or Cmd+Enter on a Mac,
 * asks: the rule every message box in Rouh keeps (`isSendKey` in Rouh's
 * app.js, and why). The line under the box says so where there is a keyboard
 * to press it on. */
function isSendKey(e) {
  return e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey &&
    !e.isComposing;
}
var KEYS_SAID = window.matchMedia && window.matchMedia("(pointer: fine)").matches
  ? (/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "")
    ? "\u2318\u21a9" : "Ctrl+Enter") + " to send"
  : "";

/* One thing the page has to say to Rouh. Nothing in here is an address and
 * nothing in here writes: a passage, a topic number, and the page's own
 * words. Which page all of it is about is Rouh's answer, read off the frame it
 * loaded, never this page's. */
function tellRouh(said) {
  if (!UP) return;
  said.type = "rouh-askai";
  try { UP.postMessage(said, "*"); } catch (err) {}
}

/* Content root: where highlights may live. Never the Ask AI UI itself. */
var MAIN = document.querySelector("main") || document.querySelector("article") || document.body;

var threadId = null, selectedText = "", busy = false, threadMeta = {}, lastThreadId = null;

/* ------------------------------------------------------------------ markdown */
/* Escape first, then build only known tags. Model output can never inject HTML. */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, function (m, a) { return "<code>" + a + "</code>"; })
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  var lines = esc(src).split("\n"), out = [], buf = [], fence = null, i = 0;
  function flush() {
    if (buf.length) { out.push("<p>" + inline(buf.join(" ")) + "</p>"); buf = []; }
  }
  function cells(row) {
    return row.trim().replace(/^\||\|$/g, "").split("|")
      .map(function (c) { return inline(c.trim()); });
  }
  while (i < lines.length) {
    var ln = lines[i];
    if (fence !== null) {
      if (/^\s*```/.test(ln)) { out.push("<pre><code>" + fence.join("\n") + "</code></pre>"); fence = null; }
      else fence.push(ln);
      i++; continue;
    }
    if (/^\s*```/.test(ln)) { flush(); fence = []; i++; continue; }
    if (/^\s*$/.test(ln)) { flush(); i++; continue; }

    if (/^\s*\|.*\|\s*$/.test(ln) && i + 1 < lines.length &&
        /^\s*\|[\s:\-|]+\|\s*$/.test(lines[i + 1])) {
      flush();
      var html = "<table><thead><tr>" +
        cells(ln).map(function (c) { return "<th>" + c + "</th>"; }).join("") +
        "</tr></thead><tbody>";
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        html += "<tr>" + cells(lines[i]).map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>";
        i++;
      }
      out.push(html + "</tbody></table>");
      continue;
    }
    var h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) { flush(); out.push("<h" + h[1].length + ">" + inline(h[2]) + "</h" + h[1].length + ">"); i++; continue; }
    if (/^\s*&gt;\s?/.test(ln)) {
      flush();
      var quote = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*&gt;\s?/, "")); i++;
      }
      out.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
      continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(ln)) {
      flush();
      var ordered = /^\s*\d+\./.test(ln), items = [];
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push("<li>" + inline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "")) + "</li>");
        i++;
      }
      out.push((ordered ? "<ol>" : "<ul>") + items.join("") + (ordered ? "</ol>" : "</ul>"));
      continue;
    }
    buf.push(ln.trim()); i++;
  }
  if (fence !== null) out.push("<pre><code>" + fence.join("\n") + "</code></pre>");
  flush();
  return out.join("");
}

/* ------------------------------------------------------------------- DOM ---- */

var root = document.createElement("div");
root.id = "askai-root";
var CRUMB = window.ASKAI_CRUMB || {};

function attr(s) { return esc(s).replace(/"/g, "&quot;"); }

/* One element per level, every level in the same design: the task, then the
 * step, each reading "number \u00b7 name". A level is a link only when it leads
 * somewhere other than the page already open. */
function pill(p, kind) {
  var inner =
    (p.num ? '<span class="askai-pn">' + esc(p.num) + '</span>' : '') +
    (p.num && p.name ? '<span class="askai-pd">\u00b7</span>' : '') +
    (p.name ? '<span class="askai-pt">' + esc(p.name) + '</span>' : '');
  var cls = "askai-pill askai-" + kind;
  return p.href
    ? '<a class="' + cls + '" href="' + attr(p.href) + '"' +
        (p.hint ? ' title="' + attr(p.hint) + '"' : '') + '>' + inner + '</a>'
    : '<span class="' + cls + '">' + inner + '</span>';
}

/* The bar is whatever the server says it is, so this file carries no
 * assumptions about how a workspace names its folders. */
function crumbHtml() {
  var sep = '<span class="sep">/</span>';
  var home = CRUMB.home_label || "All pages";
  var out = '<a class="home" href="/" title="' + attr(home) + '">' +
              '<svg viewBox="0 0 24 24">' +
                '<rect x="3" y="3" width="7" height="7" rx="1"/>' +
                '<rect x="14" y="3" width="7" height="7" rx="1"/>' +
                '<rect x="3" y="14" width="7" height="7" rx="1"/>' +
                '<rect x="14" y="14" width="7" height="7" rx="1"/>' +
              '</svg><span>' + esc(home) + '</span>' +
            '</a>';
  if (CRUMB.task) out += sep + pill(CRUMB.task, "task");
  if (CRUMB.step) out += sep + pill(CRUMB.step, "step");
  if (CRUMB.sub) out += sep + '<span class="sub">' + esc(CRUMB.sub) + '</span>';
  /* The task page is its own last level, so it sends no title. */
  if (CRUMB.title !== null) {
    out += sep + '<span class="title">' + esc(CRUMB.title || document.title) + '</span>';
  }
  return out;
}

/* The two drawings the floating bar's own buttons are made of: a clock with
   its hand running back, for History, and two sliders, for Options. */
var CLOCK = '<svg viewBox="0 0 24 24" class="askai-line"><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/>' +
  '<path d="M3.5 3.5v5h5"/><path d="M12 7.5V12l3 2"/></svg>';
var SLIDERS = '<svg viewBox="0 0 24 24" class="askai-line"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/>' +
  '<circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/></svg>';
var DECIDED = '<svg viewBox="0 0 24 24" class="askai-line"><circle cx="12" cy="12" r="8.5"/>' +
  '<path d="M8.3 12.3l2.5 2.5 4.9-5.2"/></svg>';
var PENCIL = '<svg viewBox="0 0 24 24" class="askai-line"><path d="M4 20h4.2L19.4 8.8a2.1 2.1 0 0 0 0-3' +
  'l-1.2-1.2a2.1 2.1 0 0 0-3 0L4 15.8z"/><path d="M13.5 6.5l4 4"/></svg>';

/* The task page draws its own content and borrows only the bar. */
if (window.ASKAI_BAR_ONLY) {
  root.innerHTML = '<div id="askai-crumb">' + crumbHtml() + '</div>';
  document.body.appendChild(root);
  return;
}

root.innerHTML =
  '<div id="askai-crumb">' + crumbHtml() + '</div>' +
  /* The bar that appears over a passage the moment it is selected.
     Two things can be wanted at that moment and they are different jobs:
     understanding what it says, and deciding it should say something else.
     Petar: "I just know I have two use cases: reading and understanding, and
     then separately updating... It can be different buttons, I don't know."
     So it is two buttons, and Change is only here where Rouh said this reader
     may have it. */
  '<div id="askai-acts">' +
    '<button id="askai-btn">\u2726 ' + (HOSTED ? 'Ask' : 'Ask AI') + '</button>' +
    (CAN_EDIT ? '<button id="askai-change">\u2726 Change with AI</button>' +
      '<button id="askai-typeit" title="Type over it yourself">\u270e Edit text</button>' : '') +
  '</div>' +
  /* The floating bar in the corner. The sparkle has always been here, and
     stays exactly where it was; History is next to it, under it, for the
     reader Rouh gives one to (the owner), and Options under that where the
     page has any. Petar, 24 September 2026: "History would be another icon on
     the floating bar, next to the Ask AI button and later the Comments
     button." Comments goes after History. It runs down the edge rather than
     along the top because a page's own menu runs along the top: side by
     side, the three of them covered the last tab of task 61's site. Where
     the page has comments (comments.js) their floating control takes this
     bar's place, and History and Options are pressed through it. */
  '<div id="askai-float">' +
    '<button id="askai-launch" title="Ask AI" aria-label="Ask AI">' +
      '<svg viewBox="0 0 24 24">' +
        '<path d="M12 3l1.9 5.3L19 10l-5.1 1.7L12 17l-1.9-5.3L5 10l5.1-1.7z"/>' +
        '<path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>' +
      '</svg>' +
    '</button>' +
    /* Edit: point at the part of the page to change, the way Point in the
       page's chat does, from the page itself and with E (below, "pointing"). */
    (CAN_EDIT
      ? '<button id="askai-edit-btn" class="askai-fb" type="button" aria-pressed="false" ' +
          'title="Edit (E): click any text to type over it" ' +
          'aria-label="Edit: click any text to type over it">' + PENCIL + '</button>'
      : '') +
    (window.ASKAI_HISTORY && UP
      ? '<button id="askai-hist-btn" class="askai-fb" type="button" ' +
          'title="History of this page" aria-label="History of this page">' + CLOCK + '</button>'
      : '') +
    '<button id="askai-opts-btn" class="askai-fb" type="button" hidden ' +
        'title="Options on this page" aria-label="Options on this page">' +
      SLIDERS + '<span class="askai-fbn"></span>' +
    '</button>' +
  '</div>' +
  '<div id="askai-tip"></div>' +
  (CAN_EDIT ? '<div id="askai-pick-box"><span id="askai-pick-tag"></span></div>' +
    '<div id="askai-pick-hint" role="status"><span>Click the part of the page to change</span>' +
    '<button type="button">Stop</button></div>' +
    '<div id="askai-type-bar" role="toolbar" aria-label="Typing">' +
      '<span class="k">Enter to save \u00b7 Esc to cancel</span>' +
      '<button type="button" class="save">Save</button>' +
      '<button type="button" class="ai" title="Tell Ask AI what to change here instead">\u2726 Ask AI</button>' +
    '</div>' +
    '<div id="askai-type-said" role="status"><span class="w"></span>' +
      '<button type="button" class="undo">Undo</button></div>' : '') +
  '<aside id="askai-drawer">' +
    '<div id="askai-grip" title="Drag to resize"></div>' +
    '<div class="head">' +
      '<span class="t">Ask AI</span>' +
      /* The topics asked about this page, as Rouh's own column calls them:
         History is the page's changes (below, "history and options"). */
      '<button data-act="history">Topics</button>' +
      '<button data-act="new">New</button>' +
      '<button data-act="close">\u2715</button>' +
    '</div>' +
    '<div class="quote" id="askai-quote"></div>' +
    (CAN_EDIT ? '<div class="picked" id="askai-picked"><span class="w"></span>' +
      '<button type="button" title="Stop pointing at it" aria-label="Stop pointing at it">\u2715</button></div>' : '') +
    '<div id="askai-msgs"></div>' +
    '<button id="askai-jump" title="Jump to latest">\u2193 Latest</button>' +
    '<div id="askai-composer">' +
      '<textarea id="askai-input" rows="1" placeholder="' + (CAN_EDIT
        ? 'Ask about this page, or say what to change...'
        : 'Ask about the selected text...') + '"></textarea>' +
      '<div id="askai-bar">' +
        '<button disabled title="Attach files (not enabled)">' +
          '<svg viewBox="0 0 24 24"><path d="M21.4 11.05 12.25 20.2a5.5 5.5 0 1 1-7.78-7.78l9.2-9.2a3.67 3.67 0 1 1 5.18 5.18l-9.2 9.2a1.83 1.83 0 1 1-2.6-2.6l8.5-8.48"/></svg>' +
        '</button>' +
        (CAN_EDIT
          ? '<button id="askai-point" title="Point at the part of the page to change" ' +
              'aria-label="Point at part of the page" aria-pressed="false">' +
              '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/>' +
              '<path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="1.5"/></svg>' +
            '</button>'
          : '<button disabled title="Add context (not enabled)">' +
              '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
            '</button>') +
        '<button disabled title="Voice (not enabled)">' +
          '<svg viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/></svg>' +
        '</button>' +
        /* The model Rouh asks, as Rouh says it (`drawer_head` in askai.py), so
           it cannot go on naming one the drawer has moved off. */
        (window.ASKAI_MODEL ? '<select id="askai-model" title="Model"><option>' +
          esc(window.ASKAI_MODEL) + '</option></select>' : '') +
        '<span class="sp"></span>' +
        '<button class="send" id="askai-send" title="Send">' +
          '<svg viewBox="0 0 24 24"><path d="M12 20V5M6 11l6-6 6 6"/></svg>' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div id="askai-note">' + KEYS_SAID + '</div>' +
  '</aside>';
document.body.appendChild(root);

var acts   = root.querySelector("#askai-acts");
var btn    = root.querySelector("#askai-btn");
var change = root.querySelector("#askai-change");
var launch = root.querySelector("#askai-launch");
var tip    = root.querySelector("#askai-tip");
var msgs   = root.querySelector("#askai-msgs");
var quote  = root.querySelector("#askai-quote");
var input  = root.querySelector("#askai-input");
var send   = root.querySelector("#askai-send");
var note   = root.querySelector("#askai-note");
/* What the line under the box says before an answer has sources to name, and
   says again when a question fails before anything was answered. */
var NOTE_SAID = note ? note.textContent : "";
var jump   = root.querySelector("#askai-jump");

function open()  {
  /* Hosted, the conversation is the column beside this frame, so opening it
     is asking Rouh to show it. Nothing is opened over the page: that is the
     second chat this whole arrangement exists to be rid of. */
  if (HOSTED) { tellRouh({ what: "open" }); return; }
  document.body.classList.add("askai-open"); placeJump(); setTimeout(function(){ input.focus(); }, 300);
}
function close() { document.body.classList.remove("askai-open"); }

root.querySelector('[data-act="close"]').addEventListener("click", close);
root.querySelector('[data-act="new"]').addEventListener("click", function () {
  threadId = null; selectedText = "";
  quote.classList.remove("on"); quote.textContent = "";
  msgs.innerHTML = ""; pinned = true; syncJump(); input.value = ""; size();
  open();
});
root.querySelector('[data-act="history"]').addEventListener("click", showHistory);

/* --------------------------------------------------- highlight anchoring ---- */
/* Anchor on the passage TEXT, not offsets or XPaths: text survives edits above
 * it and fails gracefully. The index below is whitespace-normalised, because
 * String(selection) collapses whitespace while node.nodeValue does not. */

function skipsAskaiUi(node) {
  return node.parentElement && node.parentElement.closest("#askai-root");
}
function walker(rootEl) {
  return document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      return skipsAskaiUi(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    }
  });
}
function buildIndex(rootEl) {
  var w = walker(rootEl), out = "", map = [], node, i, ch, lastWasSpace = true;
  while ((node = w.nextNode())) {
    var v = node.nodeValue;
    for (i = 0; i < v.length; i++) {
      ch = v.charAt(i);
      if (ch === " " || ch === "\n" || ch === "\t" || ch === "\r") {
        if (lastWasSpace) continue;
        out += " "; map.push({ node: node, off: i }); lastWasSpace = true;
      } else {
        out += ch; map.push({ node: node, off: i }); lastWasSpace = false;
      }
    }
  }
  return { text: out, map: map };
}
function findRange(needle, rootEl) {
  var n = String(needle).replace(/\s+/g, " ").trim();
  if (n.length < 4) return null;
  var idx = buildIndex(rootEl), at = idx.text.indexOf(n);
  if (at < 0) {
    n = n.slice(0, 60);
    at = idx.text.indexOf(n);
    if (at < 0) return null;
  }
  var s = idx.map[at], e = idx.map[at + n.length - 1];
  if (!s || !e) return null;
  var r = document.createRange();
  try { r.setStart(s.node, s.off); r.setEnd(e.node, e.off + 1); }
  catch (err) { return null; }
  return r;
}
function wrapRange(range, id, rootEl) {
  var nodes = [], w = walker(rootEl), nd;
  while ((nd = w.nextNode())) if (range.intersectsNode(nd)) nodes.push(nd);

  /* Capture every offset BEFORE mutating: surroundContents splits text nodes,
     which invalidates the range's references to later ones. */
  var plan = [];
  nodes.forEach(function (node) {
    if (node.parentElement && node.parentElement.closest("mark.askai-hl")) return;
    var s = (node === range.startContainer) ? range.startOffset : 0;
    var e = (node === range.endContainer) ? range.endOffset : node.nodeValue.length;
    if (e > s) plan.push({ node: node, s: s, e: e });
  });

  var made = 0;
  plan.forEach(function (p) {
    try {
      var r = document.createRange();
      r.setStart(p.node, p.s); r.setEnd(p.node, p.e);
      var m = document.createElement("mark");
      m.className = "askai-hl"; m.dataset.thread = id;
      r.surroundContents(m);
      made++;
    } catch (err) { /* fragment straddles an element edge - skip just that piece */ }
  });
  return made > 0;
}
function applyHighlight(text, id, rootEl) {
  if (!text || !id) return false;
  if (rootEl.querySelector('mark.askai-hl[data-thread="' + id + '"]')) return true;
  var r = findRange(text, rootEl);
  return r ? wrapRange(r, id, rootEl) : false;
}
function group(id) { return MAIN.querySelectorAll('mark.askai-hl[data-thread="' + id + '"]'); }

function refreshHighlights() {
  return fetch("/api/threads?" + Q)
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      if (!rows || !rows.length) return;
      lastThreadId = String(rows[0].id);     /* ordered most recent first */
      rows.forEach(function (t) {
        threadMeta[t.id] = {
          question: t.first_question, answer: t.first_answer,
          count: t.msg_count, text: t.selected_text
        };
        if (t.selected_text) applyHighlight(t.selected_text, t.id, MAIN);
      });
    })
    .catch(function () { /* proxy down - page still fine, just unhighlighted */ });
}

/* ------------------------------------------------------------- selection ---- */

document.addEventListener("mouseup", function (e) {
  if (root.contains(e.target) || window.ASKAI_VIEWING) return;
  setTimeout(function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) { acts.classList.remove("on"); return; }
    var txt = String(sel).trim();
    if (txt.length < 4 || !MAIN.contains(sel.anchorNode)) { acts.classList.remove("on"); return; }
    var r = sel.getRangeAt(0).getBoundingClientRect();
    /* The bar is measured rather than guessed at, because it is one button or
       two depending on what this reader may do with the page. */
    acts.classList.add("on");
    acts.style.top  = Math.max(8, r.top - 40) + "px";
    acts.style.left = Math.min(Math.max(8, r.left),
                               Math.max(8, window.innerWidth - acts.offsetWidth - 8)) + "px";
    acts.dataset.text = txt;
  }, 10);
});
acts.addEventListener("mousedown", function (e) { e.preventDefault(); });

/* The mark this selection is inside, if it is inside one. Pressing Ask over a
   passage already asked about reopens that topic rather than starting a second
   one on the same words. */
function markUnder() {
  var sel = window.getSelection();
  return sel && sel.anchorNode && sel.anchorNode.parentElement
    ? sel.anchorNode.parentElement.closest("mark.askai-hl") : null;
}

btn.addEventListener("click", function () {
  var txt = acts.dataset.text || "";
  acts.classList.remove("on");
  var inside = markUnder();
  if (inside) { loadThread(inside.dataset.thread); return; }  /* reopen, never duplicate */

  /* Hosted, the passage goes up and becomes the quote over Rouh's own box.
     It is the same move - a selection becomes a citation - drawn in the one
     place there is a conversation. */
  if (HOSTED) { tellRouh({ what: "ask", text: txt }); return; }

  /* A new selection MUST reset the thread, or the new passage silently never
     gets a highlight (a thread stores exactly one anchor). */
  threadId = null;
  selectedText = txt;
  quote.textContent = txt;
  quote.classList.add("on");
  msgs.innerHTML = ""; pinned = true; syncJump(); input.value = ""; size();
  open();
});

/* Change, over the passage, at the moment the reader decides the page is
   wrong. The passage becomes the quote and the box asks what should change;
   Ask AI makes the change (askai.py). Hosted, that box is Rouh's column, so
   the passage goes up to it; otherwise it is the drawer here. There is no
   such button at all for a reader who may not change the page. */
if (change) {
  change.addEventListener("click", function () {
    var txt = acts.dataset.text || "";
    acts.classList.remove("on");
    if (HOSTED) { tellRouh({ what: "change", text: txt }); return; }
    threadId = null;
    selectedText = txt;
    quote.textContent = txt;
    quote.classList.add("on");
    msgs.innerHTML = ""; pinned = true; syncJump(); input.value = ""; size();
    input.placeholder = "What should change here?";
    open();
  });
}

/* ------------------------------------------------------------- pointing ---- */
/* Petar, 24 September 2026: "for editing, pointing to a section might be a
 * better approach. If I point to a headline or a div, it knows exactly which
 * HTML element to edit."
 *
 * Rouh marks every element of a page it serves to somebody who may change it
 * with where that element starts in the file (MARK, `pages.with_marks`). Point
 * starts a mode in which a box follows the pointer round the marked element
 * under it and says what it is; a click picks it, Escape or Stop leaves. What
 * is handed on is that number, the tag, the words on it and the page's
 * version, so the element's own source can be read out of the file exactly
 * (`askai.picked_element`). Nothing about the page has to have an id.
 *
 * While pointing, the page's own clicks are held back: a press is a pick, not
 * a press on a button of the page. Ask AI's own controls - the drawer, the
 * floating bar, the comments - still take theirs.
 *
 * Edit is the same pointing, kept on. Petar, 24 September 2026
 * (fr_662a64715b9f): "add an icon for edit so that when it's activated, maybe
 * with the letter E, you can point at elements on the website just like the
 * feature we have already called POINT with the aim icon in the 'This Page'
 * chat." Point is pressed in the chat and ends with the one part it picks.
 * Edit is the pencil in the floating bar, or E, as C is comments: the pointer
 * becomes a pencil, and every part clicked is handed to the chat as the thing
 * to change, one after another, until E, Escape, Done or the pencil again.
 * On a narrow page shared with somebody the drawer covers the page, so there
 * it ends with the pick, as Point does. */
var MARK = "data-rouh-at";
var pickBox = root.querySelector("#askai-pick-box");
var pickTag = root.querySelector("#askai-pick-tag");
var pickHint = root.querySelector("#askai-pick-hint");
var pointBtn = root.querySelector("#askai-point");
var editBtn = root.querySelector("#askai-edit-btn");
var pickedBar = root.querySelector("#askai-picked");
var PLACEHOLDER = input.placeholder;
var picking = false, pickStay = false, pickOver = null, picked = null, pickedEl = null;

function markedFrom(node) {
  var el = node && node.nodeType === 1 ? node : (node && node.parentElement);
  while (el && el !== document.documentElement) {
    if (root.contains(el)) return null;
    if (el.hasAttribute && el.hasAttribute(MARK)) return el;
    el = el.parentElement;
  }
  return null;
}
function tagOf(el) { return String(el.tagName || "").toLowerCase(); }
function wordsOn(el) {
  var t = String(el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  if (!t) t = el.getAttribute("alt") || el.getAttribute("aria-label") || el.getAttribute("title") || "";
  return String(t).slice(0, 300);
}
function nameOf(el) {
  var n = tagOf(el);
  if (el.id) return n + "#" + el.id;
  var c = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
  return c && c.indexOf("askai-") !== 0 ? n + "." + c : n;
}
function pickDraw(el, text) {
  pickOver = el;
  if (!el) { pickBox.classList.remove("on"); return; }
  var r = el.getBoundingClientRect();
  pickBox.style.left = (r.left - 2) + "px";
  pickBox.style.top = (r.top - 2) + "px";
  pickBox.style.width = (r.width + 4) + "px";
  pickBox.style.height = (r.height + 4) + "px";
  pickBox.classList.toggle("below", r.top < 30);
  var w = wordsOn(el);
  pickTag.textContent = text ? "\u270e Click to type" : nameOf(el) + (w ? "  " + w.slice(0, 48) : "");
  pickBox.classList.toggle("text", !!text);
  pickBox.classList.add("on");
}
/* Whether the drawer was put away so the page could be pointed at: on a
   narrow screen it covers the page (askai.css), so it goes while pointing and
   comes back with the pick, or when pointing is given up. */
var pickHid = false;
/* Whether a pick keeps Edit on: not where the drawer covers the page. */
function staysOn() { return HOSTED || window.innerWidth > 900; }
function pickMode(stay) {
  pickStay = !!stay;
  document.documentElement.classList.toggle("askai-editing", pickStay);
  pickHint.querySelector("span").textContent = pickStay
    ? "Click any text to type over it, or anything else to ask AI to change it. E or Esc to stop"
    : "Click the part of the page to change";
  pickHint.querySelector("button").textContent = pickStay ? "Done" : "Stop";
  if (editBtn) { editBtn.classList.toggle("on", pickStay); editBtn.setAttribute("aria-pressed", pickStay ? "true" : "false"); }
}
function pickStart(stay) {
  if (!CAN_EDIT) return;
  if (picking) { if (stay) pickMode(true); return; }
  picking = true;
  pickMode(stay);
  pickHid = !HOSTED && window.innerWidth <= 900 && document.body.classList.contains("askai-open");
  if (pickHid) close();
  acts.classList.remove("on");
  document.documentElement.classList.add("askai-picking");
  pickHint.classList.add("on");
  if (pointBtn) { pointBtn.classList.add("on"); pointBtn.setAttribute("aria-pressed", "true"); }
  /* Rouh's Point says the page is waiting to be pointed at, whichever way it
     was asked to. */
  if (stay && HOSTED) tellRouh({ what: "pointing", on: true });
}
function pickStop(tell) {
  if (!picking) return;
  picking = false;
  pickMode(false);
  document.documentElement.classList.remove("askai-picking");
  pickHint.classList.remove("on");
  pickDraw(null);
  if (pointBtn) { pointBtn.classList.remove("on"); pointBtn.setAttribute("aria-pressed", "false"); }
  if (tell && HOSTED) tellRouh({ what: "pointing", on: false });
  if (pickHid) { pickHid = false; open(); }
}
function pickShow(el) {
  if (pickedEl) pickedEl.classList.remove("askai-picked");
  pickedEl = el || null;
  if (pickedEl) pickedEl.classList.add("askai-picked");
}
function pickClear() {
  picked = null;
  pickShow(null);
  if (pickedBar) pickedBar.classList.remove("on");
  input.placeholder = PLACEHOLDER;
}
function pickChoose(el) {
  var still = pickStay && staysOn();
  if (still) pickDraw(null); else pickStop(false);
  var said = { at: Number(el.getAttribute(MARK)) || 0, tag: tagOf(el), text: wordsOn(el),
               label: nameOf(el), version: VERSION };
  pickShow(el);
  if (HOSTED) { tellRouh({ what: "picked", picked: said, still: still }); return; }
  picked = said;
  pickedBar.querySelector(".w").innerHTML = "<b>" + esc(said.label) + "</b>" +
    esc(said.text.slice(0, 140));
  pickedBar.classList.add("on");
  input.placeholder = "What should change here?";
  open();
}
if (CAN_EDIT) {
  /* With Edit on, text that can be typed over says so under the pointer, and
     a click on it is a caret in it (below, "typing"); anything else is
     pointed at for Ask AI, as before. */
  document.addEventListener("mousemove", function (e) {
    if (!picking) return;
    var inTyping = !!typing && typing.el.contains(e.target);
    var text = pickStay && !inTyping ? typeTarget(e.target) : null;
    document.documentElement.classList.toggle("askai-over-text", !!text || inTyping);
    if (inTyping) { pickDraw(null); return; }
    pickDraw(text || markedFrom(e.target), !!text);
  }, true);
  ["mousedown", "mouseup", "pointerdown", "pointerup", "touchstart"].forEach(function (kind) {
    document.addEventListener(kind, function (e) {
      if (picking && !root.contains(e.target)) e.stopPropagation();
    }, true);
  });
  document.addEventListener("click", function (e) {
    if (!picking || root.contains(e.target)) return;
    /* Inside the text being typed, a click moves the caret and does nothing
       else: not a link followed, not the page's own button pressed. */
    if (typing && typing.el.contains(e.target)) {
      if (e.target.closest && e.target.closest("a")) e.preventDefault();
      e.stopPropagation();
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    var text = pickStay ? typeTarget(e.target) : null;
    if (text) { pickDraw(null); typeStart(text, e.clientX, e.clientY); return; }
    var el = markedFrom(e.target);
    if (el) pickChoose(el);
  }, true);
  /* Escape leaves, and goes no further: handed up, it would close the page. */
  document.addEventListener("keydown", function (e) {
    if (!picking || e.key !== "Escape" || typing) return;
    e.preventDefault();
    e.stopPropagation();
    pickStop(true);
  }, true);
  window.addEventListener("scroll", function () {
    if (picking && pickOver) pickDraw(pickOver, pickBox.classList.contains("text"));
  }, true);
  pickHint.querySelector("button").addEventListener("click", function () { pickStop(true); });
  if (pointBtn) {
    pointBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (picking) pickStop(true); else pickStart();
    });
  }
  /* Edit, and E. After the page's own keys, so a page with an E of its own
     keeps it, and never while something is being typed. */
  function editToggle() {
    if (picking && pickStay) pickStop(true); else pickStart(true);
  }
  if (editBtn) {
    editBtn.addEventListener("click", function (e) { e.stopPropagation(); editToggle(); });
  }
  /* Comments asked for while pointing (C, comments.js): pointing stops. */
  document.addEventListener("askai-stop-pointing", function () { pickStop(true); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "e" && e.key !== "E") return;
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
    var t = e.composedPath ? e.composedPath()[0] : e.target;
    if (t && t.nodeType === 1 && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
    e.preventDefault();
    editToggle();
  }, false);
  if (pickedBar) {
    pickedBar.querySelector("button").addEventListener("click", function () {
      pickClear();
      input.focus();
    });
  }
}

/* ------------------------------------------------------------- typing ---- */
/* fr_65039fdac5a2, 27 September 2026, from a person editing the copy of a
 * shared page: "I couldn't figure out how to just type my change into the
 * text, I had to ask AI to make the text change... Changing text directly by
 * typing would have saved me hours."
 *
 * So text can be typed over where it stands. With Edit on (the pencil, or E)
 * the pointer says "Click to type" over any piece of text, and a click puts
 * the caret in it; over a selected passage, Edit text does the same with the
 * passage still selected, so typing replaces it. Enter or a click elsewhere
 * saves, Escape puts it back, and Ask AI on the little bar hands the same
 * piece to the conversation instead.
 *
 * What is typed is never sent as markup. The piece is cut into runs of text
 * at every element of the page's own (the ones marked with where they are in
 * the file), and the runs go to Rouh as they were and as they are, which
 * writes only the runs that changed into the file (`askai.type_text`). So a
 * bold word or a link inside the text stays exactly as it was. The page is
 * not sent again: it already shows what was typed, and only the places the
 * rest of the page is marked with move on by what was added. */
var VOID = /^(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)$/;
/* What is never typed into: controls, pictures, and anything bigger than a
   piece of text. */
var UNTYPED = /^(html|body|input|textarea|select|option|button|img|svg|video|audio|canvas|iframe|object|embed|script|style|template|table|thead|tbody|tfoot|tr|ul|ol|dl|form|picture|math)$/;
var typeBar = root.querySelector("#askai-type-bar");
var typeSaid = root.querySelector("#askai-type-said");
var typing = null, typeQueue = Promise.resolve(), saidTimer = null;

function displayOf(el) {
  try { return getComputedStyle(el).display; } catch (err) { return "inline"; }
}
/* Whether ``el`` is a piece of text: some words, and nothing inside it that
   is laid out as a block of its own or is not text at all. */
function typeable(el) {
  if (!el || !el.hasAttribute || !el.hasAttribute(MARK) || root.contains(el)) return false;
  if (UNTYPED.test(tagOf(el)) || el.isContentEditable) return false;
  if (!/\S/.test(el.textContent || "")) return false;
  var all = el.getElementsByTagName("*");
  if (all.length > 400) return false;
  for (var i = 0; i < all.length; i++) {
    var t = tagOf(all[i]);
    if (t === "br" || t === "wbr" || root.contains(all[i])) continue;
    if (UNTYPED.test(t)) return false;
    var d = displayOf(all[i]);
    if (d !== "inline" && d !== "none" && d !== "contents") return false;
  }
  return true;
}
/* The piece of text a pointer is over: a bold word is its sentence, so the
   element is widened past anything that is only inline in its line. */
function typeTarget(node) {
  var el = markedFrom(node);
  if (!el) return null;
  while (el.parentElement && el.parentElement.hasAttribute(MARK) && displayOf(el) === "inline" &&
         !UNTYPED.test(tagOf(el.parentElement)) && el.parentElement !== document.body) {
    el = el.parentElement;
  }
  return typeable(el) ? el : null;
}
/* The runs of text in ``el``, cut at every element of the page's own - and at
   every comment - as the file is cut (`askai._runs`). Anything the page's own
   script or Ask AI's marks put in is only text. */
function runsOf(el) {
  var runs = [""], marks = [];
  (function walk(parent) {
    for (var c = parent.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) runs[runs.length - 1] += c.nodeValue;
      else if (c.nodeType === 8) runs.push("");
      else if (c.nodeType === 1 && !root.contains(c)) {
        if (!c.hasAttribute(MARK)) { walk(c); continue; }
        marks.push(c);
        runs.push("");
        if (!VOID.test(tagOf(c))) { walk(c); runs.push(""); }
      }
    }
  })(el);
  return { runs: runs, marks: marks };
}
function sameMarks(a, b) {
  if (a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
function caretAt(x, y) {
  var r = null;
  if (document.caretRangeFromPoint) r = document.caretRangeFromPoint(x, y);
  else if (document.caretPositionFromPoint) {
    var p = document.caretPositionFromPoint(x, y);
    if (p) { r = document.createRange(); r.setStart(p.offsetNode, p.offset); r.collapse(true); }
  }
  return r;
}
function typePlace() {
  if (!typing) return;
  var r = typing.el.getBoundingClientRect(), h = typeBar.offsetHeight || 34;
  var top = r.bottom + 8;
  if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
  typeBar.style.top = top + "px";
  typeBar.style.left = Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - typeBar.offsetWidth - 8)) + "px";
}
function typeStart(el, x, y, range) {
  if (typing && typing.el === el) return;
  typeEnd(true);
  acts.classList.remove("on");
  var was = runsOf(el);
  typing = { el: el, tag: tagOf(el), was: was.runs, marks: was.marks, html: el.innerHTML };
  el.setAttribute("contenteditable", "true");
  el.setAttribute("spellcheck", "true");
  el.classList.add("askai-typing");
  el.focus({ preventScroll: true });
  var r = range || (x != null ? caretAt(x, y) : null);
  var sel = window.getSelection();
  if (sel) {
    if (!r || !el.contains(r.startContainer)) {
      r = document.createRange();
      r.selectNodeContents(el);
      r.collapse(false);
    }
    sel.removeAllRanges();
    sel.addRange(r);
  }
  typeBar.classList.add("on");
  typePlace();
}
/* Done typing: saved, or put back as it was. */
function typeEnd(save) {
  var t = typing;
  if (!t) return;
  typing = null;
  var el = t.el;
  el.removeAttribute("contenteditable");
  el.removeAttribute("spellcheck");
  el.classList.remove("askai-typing");
  typeBar.classList.remove("on");
  if (!save) { el.innerHTML = t.html; return; }
  var now = runsOf(el);
  var body = { tag: t.tag, was: t.was };
  if (sameMarks(now.marks, t.marks)) {
    if (now.runs.join("\u0000") === t.was.join("\u0000")) return;
    body.now = now.runs;
  } else {
    /* The typing went across a bold word or the like and took it out: what
       is there now is plain text. */
    body.plain = now.runs.join("");
  }
  /* One at a time and in order, each with where the piece is after the ones
     before it moved the page on. */
  typeQueue = typeQueue.then(function () {
    body.at = Number(el.getAttribute(MARK));
    return post("/api/type", body).then(function (got) {
      if (!got.ok) {
        el.innerHTML = t.html;
        typeTell(got.j.error || "That could not be saved.", 0, true);
        return;
      }
      marksMove(got.j.moved || []);
      if (got.j.version) VERSION = String(got.j.version);
      typeTell("Saved", Number(got.j.edit) || 0, false);
    });
  });
}
/* Every place the page is marked with, after the file moved on by so much
   after each of ``moved``'s places. */
function marksMove(moved) {
  if (!moved.length) return;
  var all = document.querySelectorAll("[" + MARK + "]");
  for (var i = 0; i < all.length; i++) {
    if (root.contains(all[i])) continue;
    var at = Number(all[i].getAttribute(MARK)), by = 0;
    for (var j = 0; j < moved.length; j++) if (at >= moved[j][0]) by += moved[j][1];
    if (by) all[i].setAttribute(MARK, String(at + by));
  }
}
function typeTell(words, edit, bad) {
  typeSaid.querySelector(".w").textContent = words;
  var undo = typeSaid.querySelector(".undo");
  undo.hidden = !edit;
  undo.disabled = false;
  typeSaid.dataset.edit = edit ? String(edit) : "";
  typeSaid.classList.toggle("bad", !!bad);
  typeSaid.classList.add("on");
  clearTimeout(saidTimer);
  saidTimer = setTimeout(function () { typeSaid.classList.remove("on"); }, bad ? 9000 : 5000);
}
if (CAN_EDIT) {
  /* Before anything of the page's own, or Edit's: the keys typed are the
     text's, and Enter and Escape are Save and Cancel. */
  window.addEventListener("keydown", function (e) {
    if (!typing || !typing.el.contains(e.target)) return;
    e.stopPropagation();
    if (e.isComposing) return;
    if (e.key === "Enter") { e.preventDefault(); typeEnd(true); return; }
    if (e.key === "Escape") { e.preventDefault(); typeEnd(false); }
  }, true);
  ["keyup", "keypress"].forEach(function (kind) {
    window.addEventListener(kind, function (e) {
      if (typing && typing.el.contains(e.target)) e.stopPropagation();
    }, true);
  });
  /* Text only: a paste is its words, and nothing is dropped in. */
  document.addEventListener("paste", function (e) {
    if (!typing || !typing.el.contains(e.target)) return;
    e.preventDefault();
    var words = (e.clipboardData && e.clipboardData.getData("text/plain")) || "";
    document.execCommand("insertText", false, words.replace(/\s*\n\s*/g, " "));
  }, true);
  document.addEventListener("drop", function (e) {
    if (typing && typing.el.contains(e.target)) e.preventDefault();
  }, true);
  /* Clicking away saves, unless it was onto the bar that goes with it. */
  document.addEventListener("focusout", function (e) {
    var t = typing;
    if (!t || e.target !== t.el) return;
    setTimeout(function () {
      if (typing !== t) return;
      var a = document.activeElement;
      if (a && (t.el.contains(a) || typeBar.contains(a))) return;
      typeEnd(true);
    }, 0);
  }, true);
  window.addEventListener("scroll", typePlace, true);
  window.addEventListener("resize", typePlace);
  typeBar.addEventListener("mousedown", function (e) { e.preventDefault(); });
  typeBar.querySelector(".save").addEventListener("click", function () { typeEnd(true); });
  typeBar.querySelector(".ai").addEventListener("click", function () {
    var el = typing && typing.el;
    typeEnd(false);
    if (el) pickChoose(el);
  });
  typeSaid.querySelector(".undo").addEventListener("click", function () {
    var id = Number(typeSaid.dataset.edit) || 0, b = this;
    if (!id) return;
    b.disabled = true;
    post("/api/undo", { edit: id }).then(function (got) {
      if (!got.ok) { typeTell(got.j.error || "That could not be put back.", 0, true); return; }
      typeSaid.classList.remove("on");
      if (!patchPage(got.j.patch)) pageAgain();
    });
  });
  /* Edit text, over a selected passage: the caret in its text, with the
     passage still selected, so what is typed replaces it. */
  var typeIt = root.querySelector("#askai-typeit");
  if (typeIt) {
    typeIt.addEventListener("click", function () {
      var sel = window.getSelection();
      var range = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
      var el = range ? typeTarget(range.startContainer) : null;
      acts.classList.remove("on");
      if (!el) {
        typeTell("That cannot be typed over here, because it is not one piece of text. " +
                 "Use Change with AI instead.", 0, true);
        return;
      }
      if (!el.contains(range.endContainer)) range.collapse(true);
      typeStart(el, null, null, range);
    });
  }
}

/* ------------------------------------------------------ a change, in place -- */
/* A change Ask AI made, or one put back, onto the page that is open rather
 * than by sending the page again (`askai.patch_of`, and why). Each element it
 * touched is found by where it was in the file, and made what it is now: its
 * attributes that changed in the file, and its insides where they changed -
 * down through every element the two versions have alike, so what the page's
 * own script did to the rest of it (which of its pages is showing, what is
 * open) stays. True when it was all done; false, and the page is sent again,
 * when any of it could not be. */
function parseMarked(markup) {
  var t = document.createElement("template");
  t.innerHTML = String(markup || "");
  return t.content.firstElementChild;
}
function attrsMorph(live, from, to) {
  var names = {};
  [].forEach.call(from.attributes, function (a) { names[a.name] = 1; });
  [].forEach.call(to.attributes, function (a) { names[a.name] = 1; });
  Object.keys(names).forEach(function (n) {
    if (n === MARK) { live.setAttribute(MARK, to.getAttribute(MARK)); return; }
    var a = from.getAttribute(n), b = to.getAttribute(n);
    if (a === b) return;
    if (b === null) live.removeAttribute(n); else live.setAttribute(n, b);
  });
}
/* The live element's own children, cut the way `runsOf` cuts: each child of
   the file's, and the stretches of text between them. */
function childShape(el, liveSide) {
  var out = [{ text: true, nodes: [] }];
  for (var c = el.firstChild; c; c = c.nextSibling) {
    var own = c.nodeType === 1 && c.hasAttribute(MARK) && !(liveSide && root.contains(c));
    if (own || c.nodeType === 8) {
      out.push({ el: c });
      out.push({ text: true, nodes: [] });
    } else if (c.nodeType === 3 || (c.nodeType === 1 && liveSide)) {
      out[out.length - 1].nodes.push(c);
    }
  }
  return out;
}
function textOf(nodes) {
  return nodes.map(function (n) { return n.textContent; }).join("");
}
function morph(live, from, to) {
  if (tagOf(live) !== tagOf(to) || tagOf(from) !== tagOf(to)) {
    live.replaceWith(document.importNode(to, true));
    return;
  }
  attrsMorph(live, from, to);
  if (/^(style|script|textarea|title)$/.test(tagOf(to))) {
    if (from.textContent !== to.textContent) live.textContent = to.textContent;
    return;
  }
  var a = childShape(from, false), b = childShape(to, false), l = childShape(live, true);
  var alike = a.length === b.length && a.length === l.length;
  for (var i = 0; alike && i < a.length; i++) {
    if (a[i].el) {
      alike = !!b[i].el && !!l[i].el && a[i].el.nodeType === b[i].el.nodeType &&
        l[i].el.nodeType === a[i].el.nodeType &&
        (a[i].el.nodeType === 8 || (tagOf(a[i].el) === tagOf(b[i].el) &&
         l[i].el.getAttribute(MARK) === a[i].el.getAttribute(MARK)));
    }
  }
  if (!alike) {
    /* Its insides are not the same shape any more: they are the new ones. */
    while (live.firstChild) live.removeChild(live.firstChild);
    [].forEach.call(to.childNodes, function (c) { live.appendChild(document.importNode(c, true)); });
    return;
  }
  for (var j = 0; j < a.length; j++) {
    if (a[j].el) {
      if (a[j].el.nodeType === 1) morph(l[j].el, a[j].el, b[j].el);
      continue;
    }
    var was = textOf(a[j].nodes), now = textOf(b[j].nodes);
    if (was === now) continue;
    var put = document.createTextNode(now);
    var first = l[j].nodes[0];
    if (first) first.parentNode.insertBefore(put, first);
    else if (l[j + 1] && l[j + 1].el) live.insertBefore(put, l[j + 1].el);
    else live.appendChild(put);
    l[j].nodes.forEach(function (n) { n.remove(); });
  }
}
function patchPage(patch) {
  if (!patch || !Array.isArray(patch.parts) || !patch.parts.length) return false;
  var found = [];
  for (var i = 0; i < patch.parts.length; i++) {
    var p = patch.parts[i];
    var live = document.querySelector("[" + MARK + '="' + Number(p.was) + '"]');
    var from = parseMarked(p.before), to = parseMarked(p.after);
    if (!live || root.contains(live) || !from || !to || tagOf(live) !== String(p.tag)) return false;
    found.push([live, from, to]);
  }
  /* Everything else moves on first, and the parts are then marked as they
     are in the file now. */
  var inside = found.map(function (f) { return f[0]; });
  var all = document.querySelectorAll("[" + MARK + "]");
  for (var k = 0; k < all.length; k++) {
    var el = all[k];
    if (root.contains(el) || inside.some(function (x) { return x === el || x.contains(el); })) continue;
    var at = Number(el.getAttribute(MARK)), by = 0;
    patch.moved.forEach(function (m) { if (at >= m[0]) by += m[1]; });
    if (by) el.setAttribute(MARK, String(at + by));
  }
  found.forEach(function (f) { morph(f[0], f[1], f[2]); });
  if (patch.version) VERSION = String(patch.version);
  refreshHighlights();
  return true;
}
/* The page sent again, where the reader was, for a change that could not be
   made on it. Hosted, Rouh loads it; shared, the page around this one. */
function pageAgain() {
  tellRouh({ what: "reload", thread: Number(threadId) || 0, y: window.scrollY || 0 });
}

/* The persistent launcher resumes the LAST conversation rather than starting a
 * new one - "New" is the only control that clears the thread.
 *
 * Hosted, it is the way in rather than a second chat: a page loaded from the
 * task browser takes the conversation column with it, so this is the one thing
 * on the screen to press when nothing has been selected. Every path out of it
 * below ends in `loadThread` or `open`, and both of those go up. */
if (HOSTED) {
  launch.title = "Ask about this page";
  launch.setAttribute("aria-label", "Ask about this page");
}
launch.addEventListener("click", function () {
  /* Hosted, the conversation is Rouh's column, and only Rouh knows whether it
     is on the screen: it opens it, or puts it away if it is already there,
     with whatever was said in it kept. */
  if (HOSTED) { tellRouh({ what: "toggle" }); return; }
  if (document.body.classList.contains("askai-open")) { close(); return; }
  if (lastThreadId && threadMeta[lastThreadId]) { loadThread(lastThreadId); return; }
  threadId = null; selectedText = "";
  quote.classList.remove("on"); quote.textContent = "";
  msgs.innerHTML = "";
  open();
});

/* --------------------------------------------------------------- messages --- */

function bubble(cls, text) {
  var d = document.createElement("div");
  d.className = "msg " + cls;
  if (text != null) d.textContent = text;
  msgs.appendChild(d); down();
  return d;
}
function dots() {
  var d = document.createElement("div");
  d.className = "dots"; d.innerHTML = "<i></i><i></i><i></i>";
  msgs.appendChild(d); down();
  return d;
}
function tool(name, detail) {
  var d = document.createElement("details");
  d.className = "tool";
  var s = document.createElement("summary"); s.textContent = name;
  var b = document.createElement("div"); b.className = "body"; b.textContent = detail || "";
  d.appendChild(s); d.appendChild(b);
  msgs.appendChild(d); down();
}
/* Sticky-bottom autoscroll: follow the stream only while the reader is already
 * at the bottom. The moment they scroll up to re-read something, stop yanking
 * them back, and offer one click to re-anchor. */
var pinned = true;
function atBottom() { return msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 40; }
function syncJump() {
  var scrollable = msgs.scrollHeight > msgs.clientHeight + 8;
  placeJump();                       /* the note and composer both change height */
  jump.classList.toggle("on", !pinned && scrollable);
}
function down(force) {
  if (force || pinned) { msgs.scrollTop = msgs.scrollHeight; pinned = true; }
  syncJump();
}
msgs.addEventListener("scroll", function () { pinned = atBottom(); syncJump(); });
/* The composer grows with the text, so measure rather than guess the offset. */
function placeJump() {
  var composer = root.querySelector("#askai-composer");
  jump.style.bottom = (composer.offsetHeight + note.offsetHeight + 14) + "px";
}
window.addEventListener("resize", function () { placeJump(); pinned = atBottom(); syncJump(); });
jump.addEventListener("click", function () { down(true); input.focus(); });

/* --------------------------------------------------------------- composer --- */

root.querySelector("#askai-composer").addEventListener("click", function (e) {
  if (!e.target.closest("button") && !e.target.closest("select")) input.focus();
});
function size() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 15 * 20 + 15) + "px";  /* 15 lines, then scroll */
  placeJump();
}
input.addEventListener("input", size);
input.addEventListener("keydown", function (e) {
  if (isSendKey(e)) { e.preventDefault(); ask(); }
});
send.addEventListener("click", ask);

/* ----------------------------------------------------------------- server --- */

function loadThread(id) {
  /* Hosted, a topic is read in Rouh's own column, which is where every other
     topic on this page is read. Pressing a mark on the page is the same thing
     as pressing its row in the list there, seen from the other end. */
  if (HOSTED) { tellRouh({ what: "thread", id: Number(id) || 0 }); return; }
  threadId = String(id);
  msgs.innerHTML = "";
  var meta = threadMeta[threadId];
  selectedText = (meta && meta.text) ? meta.text : "";
  quote.textContent = selectedText;
  quote.classList.toggle("on", !!selectedText);
  open();
  fetch("/api/threads/" + threadId + "?" + Q)
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      rows.forEach(function (m) {
        if (m.role === "user") bubble("user", m.content);
        else if (m.role === "edit") editLine(m.edit, m.content, !!m.undone);
        else bubble("ai").innerHTML = md(m.content);
      });
    })
    .catch(function () {
      bubble("ai err", "This topic could not be read. Rouh could not be reached.");
    });
}

/* The report of Ask AI's pass over the comments, opened where every other
   topic on this page is read (comments.js, "the pass"). */
document.addEventListener("askai-open-thread", function (e) {
  var id = Number(e && e.detail) || 0;
  if (id) loadThread(String(id));
});

function showHistory() {
  fetch("/api/threads?" + Q).then(function (r) { return r.json(); }).then(function (rows) {
    msgs.innerHTML = "";
    quote.classList.remove("on");
    threadId = null;
    open();
    if (!rows.length) { bubble("ai").innerHTML = md("_No topics on this page yet._"); return; }
    var wrap = bubble("ai");
    wrap.innerHTML = "<h3>Topics</h3>";
    rows.forEach(function (t) {
      var b = document.createElement("button");
      b.className = "histbtn";
      b.textContent = (t.first_question || t.title || "Thread " + t.id) + "  (" + t.msg_count + ")";
      b.addEventListener("click", function () { loadThread(t.id); });
      wrap.appendChild(b);
    });
  }).catch(function () {
    bubble("ai err", "Rouh could not be reached.");
  });
}

function pageText() {
  var clone = MAIN.cloneNode(true);
  var ui = clone.querySelector("#askai-root");
  if (ui) ui.remove();
  return clone.innerText || "";
}

function ask() {
  var q = input.value.trim();
  if (!q || busy) return;
  busy = true; send.disabled = true;
  bubble("user", q); down(true);
  input.value = ""; size();

  var spinner = dots(), target = null, acc = "", wrote = false;

  var changedNow = 0, patches = [];
  fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      doc: DOC, threadId: threadId, selectedText: selectedText,
      context: pageText(), question: q, picked: picked
    })
  }).then(function (res) {
    if (!res.ok || !res.body) throw new Error("bad response");
    var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) return;
        buf += dec.decode(r.value, { stream: true });
        var parts = buf.split("\n\n");
        buf = parts.pop();
        parts.forEach(function (chunk) {
          var line = chunk.split("\n").filter(function (l) { return l.indexOf("data:") === 0; })[0];
          if (!line) return;
          var ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { return; }

          if (ev.type === "thread") { threadId = String(ev.threadId); }
          else if (ev.type === "sources") {
            if (ev.files && ev.files.length)
              note.textContent = "Grounded in " + ev.files.length + " source file(s): " + ev.files.join(", ");
          }
          else if (ev.type === "tool") {
            if (spinner) { spinner.remove(); spinner = null; }
            tool(ev.name || "Tool", ev.detail || "");
            target = null;
          }
          else if (ev.type === "text") {
            if (spinner) { spinner.remove(); spinner = null; }
            if (!target) { target = bubble("ai"); acc = ""; }
            wrote = true;
            acc += ev.text;
            target.innerHTML = md(acc);
            down();
          }
          else if (ev.type === "edited") {
            if (spinner) { spinner.remove(); spinner = null; }
            editLine(ev.edit, ev.summary, false);
            changedNow++;
            patches.push(ev.patch || null);
            target = null;
          }
          else if (ev.type === "error") {
            if (spinner) { spinner.remove(); spinner = null; }
            bubble("ai err").innerHTML = md("**Error:** " + ev.message);
            /* Nothing was answered, so nothing was grounded in those files. */
            if (!wrote && !changedNow && note) note.textContent = NOTE_SAID;
          }
        });
        return pump();
      });
    }
    return pump();
  }).catch(function () {
    if (spinner) { spinner.remove(); spinner = null; }
    bubble("ai err").innerHTML = md(
      "**Rouh could not be reached.** Check the connection and ask again.");
  }).then(function () {
    busy = false; send.disabled = false;
    if (spinner) { spinner.remove(); spinner = null; }
    /* The page on disk is not the page on the screen any more, so it is sent
       again - with this topic open and the page where it was - and what was
       pointed at is let go, because its place in the file has moved. */
    if (changedNow) {
      pickClear();
      /* Onto the page that is open, where the reader is, and sent again only
         when it cannot be (below, "a change, in place"). */
      if (!patches.every(patchPage)) reloadPage();
      return;
    }
    refreshHighlights();
  });
}

/* A change Ask AI made to the page, as a line of its own, with Undo on it. */
function editLine(id, summary, undone) {
  var d = document.createElement("div");
  d.className = "msg edit" + (undone ? " undone" : "");
  var w = document.createElement("span");
  w.className = "w";
  w.textContent = "Changed the page: " + (summary || "done");
  d.appendChild(w);
  if (!undone && Number(id) > 0) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = "Undo";
    b.title = "Put the page back as it was before this change";
    b.addEventListener("click", function () { undoEdit(Number(id), d, b); });
    d.appendChild(b);
  }
  msgs.appendChild(d); down();
  return d;
}

function undoEdit(id, line, btn) {
  btn.disabled = true;
  fetch("/api/undo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc: DOC, edit: id })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; });
  }).catch(function () {
    return { ok: false, j: { error: "Rouh could not be reached." } };
  }).then(function (got) {
    if (!got.ok || !got.j || got.j.error) {
      btn.disabled = false;
      bubble("ai err", (got.j && got.j.error) || "That change could not be put back.");
      return;
    }
    line.classList.add("undone");
    btn.remove();
    if (!patchPage(got.j && got.j.patch)) reloadPage();
  });
}

/* The page again, from Rouh. Not hosted, the page around this one loads it
   (reader.js); hosted, Rouh's column does that itself when it sees the change. */
function reloadPage() {
  if (HOSTED || !UP) return;
  tellRouh({ what: "reload", thread: Number(threadId) || 0, y: window.scrollY || 0 });
}

/* ------------------------------------------------------------------ tooltip - */
/* A tooltip that dismisses on mouseout is unreachable. The grace period plus the
 * mouseenter cancel is what makes it usable. */

var tipTimer = null, tipFor = null;

function showTip(mark) {
  var id = mark.dataset.thread, meta = threadMeta[id];
  if (!meta) return;
  tipFor = id;
  [].forEach.call(group(id), function (n) { n.classList.add("active"); });

  tip.innerHTML = "";
  var m = document.createElement("div"); m.className = "meta";
  m.textContent = "Asked about this \u00B7 " + (meta.count || 0) + " messages";
  var q = document.createElement("div"); q.className = "q"; q.textContent = meta.question || "";
  var a = document.createElement("div"); a.className = "a"; a.textContent = meta.answer || "";
  var acts = document.createElement("div"); acts.className = "acts";
  var openBtn = document.createElement("button");
  openBtn.className = "p"; openBtn.textContent = "Open thread";
  openBtn.addEventListener("click", function () { hideTip(); loadThread(id); });
  var copy = document.createElement("button");
  copy.textContent = "Copy link";
  copy.addEventListener("click", function () { copyLink(meta.text, copy); });
  acts.appendChild(openBtn); acts.appendChild(copy);
  tip.appendChild(m); tip.appendChild(q); tip.appendChild(a); tip.appendChild(acts);
  tip.classList.add("on");

  var r = mark.getBoundingClientRect(), t = tip.getBoundingClientRect();
  var left = Math.min(Math.max(r.left, 12), window.innerWidth - t.width - 12);
  var top = r.bottom + 10;
  if (top + t.height > window.innerHeight - 12) top = r.top - t.height - 10;   /* flip above */
  /* Clamp regardless: a mark can sit off-screen and the tooltip must not follow. */
  top = Math.min(Math.max(top, 12), Math.max(12, window.innerHeight - t.height - 12));
  tip.style.left = Math.max(left, 12) + "px";
  tip.style.top = top + "px";
}
function hideTip() {
  tip.classList.remove("on");
  if (tipFor) [].forEach.call(group(tipFor), function (n) { n.classList.remove("active"); });
  tipFor = null;
}
MAIN.addEventListener("mouseover", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (!m) return;
  clearTimeout(tipTimer);
  showTip(m);
});
MAIN.addEventListener("mouseout", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (!m) return;
  tipTimer = setTimeout(hideTip, 280);
});
tip.addEventListener("mouseenter", function () { clearTimeout(tipTimer); });
tip.addEventListener("mouseleave", function () { tipTimer = setTimeout(hideTip, 200); });
MAIN.addEventListener("click", function (e) {
  var m = e.target.closest && e.target.closest("mark.askai-hl");
  if (m) loadThread(m.dataset.thread);
});

/* Sharing only. The browser's own fragment highlight is not hoverable or
 * scriptable, so it complements the marks rather than replacing them. */
function copyLink(text, button) {
  var t = String(text || "").replace(/\s+/g, " ").trim().slice(0, 140);
  var url = location.origin + location.pathname + "#:~:text=" +
            encodeURIComponent(t).replace(/-/g, "%2D");
  var done = function () {
    var old = button.textContent;
    button.textContent = "Copied \u2713";
    setTimeout(function () { button.textContent = old; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText)
    navigator.clipboard.writeText(url).then(done, done);
  else done();
}

/* ---------------------------------------------------------------- resizer --- */
/* One variable drives both halves of the push layout: `#askai-drawer` reads
 * --askai-w for its width and `body.askai-open` reads it for its margin. Writing
 * it once on <html> moves them together, so there is no way for the drawer and
 * the gap it leaves to disagree mid-drag. */

var MIN_W = 320;
function maxW() { return Math.max(MIN_W, Math.round(window.innerWidth * 0.6)); }
function setW(px) {
  var w = Math.min(Math.max(Math.round(px), MIN_W), maxW());
  document.documentElement.style.setProperty("--askai-w", w + "px");
  return w;
}

try {
  var savedW = parseInt(localStorage.getItem("askai-w"), 10);
  if (savedW) setW(savedW);
} catch (e) {}

var grip = root.querySelector("#askai-grip");
grip.addEventListener("pointerdown", function (e) {
  e.preventDefault();
  grip.setPointerCapture(e.pointerId);
  /* Transitions are for the open/close slide. During a drag they lag the pointer. */
  document.body.classList.add("askai-resizing");

  function move(ev) { setW(window.innerWidth - ev.clientX); }
  function up(ev) {
    grip.removeEventListener("pointermove", move);
    grip.removeEventListener("pointerup", up);
    grip.releasePointerCapture(ev.pointerId);
    document.body.classList.remove("askai-resizing");
    try {
      var cur = getComputedStyle(document.documentElement)
        .getPropertyValue("--askai-w").trim();
      localStorage.setItem("askai-w", parseInt(cur, 10) || 420);
    } catch (err) {}
  }
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", up);
});

/* A width that was fine on a wide monitor must not swallow a narrow window. */
window.addEventListener("resize", function () {
  var cur = parseInt(getComputedStyle(document.documentElement)
    .getPropertyValue("--askai-w"), 10);
  if (cur) setW(cur);
});

/* ------------------------------------------------- history and options --- */
/* Petar, 24 September 2026 (fr_b91369ea7ba2): "whenever someone makes a change
 * on the website, I want a history of every change, including who made it and
 * when. I want to be able to click on each entry and see how the page looked
 * at that moment." And: "for every change, I have to decide whether I want to
 * keep it in the options... an options pop-up so other people can switch
 * between red and orange... I'd rather have it as a layer on top so it doesn't
 * distort the original HTML."
 *
 * Both are drawn here, inside #askai-root and never in the page's own markup.
 * Everything about them on the server is `rouh/pagehistory.py`.
 *
 * - **History** (the clock in the floating bar, for the owner): every change,
 *   newest first, with who made it and when. Pressing one asks Rouh to load
 *   the page as it was then into this same frame, read only; that page comes
 *   with ASKAI_VIEWING, which draws the bar across its top saying which moment
 *   it is, with the way back to the page as it is now. A change nobody has
 *   decided about asks, on its line, whether to keep it as an option.
 * - **Options**: a small tab in 61-01's purple on each part of the page that
 *   has more than one version, and a pop-up from it to switch between them.
 *   Switching is this viewer's alone and swaps the element on the screen;
 *   Make default is everybody's - anybody who can read the page may press it,
 *   and the last press stands - and writes the page, which is then sent again.
 *   The sliders in the floating bar list every option on the page, which is
 *   the way to the ones with nothing on the screen to hang a tab on, a change
 *   to the page's styles among them. */

var VIEWING = window.ASKAI_VIEWING || null;
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function node(tag, cls, words) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (words != null) n.textContent = words;
  return n;
}
function pad2(n) { return (n < 10 ? "0" : "") + n; }
/* "Today, 19:02", "Yesterday, 19:02", "24 Sep, 19:02", "24 Sep 2025, 19:02". */
function when(ts) {
  if (!ts) return "";
  var d = new Date(ts * 1000), now = new Date();
  var at = pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  var y = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "Today, " + at;
  if (d.toDateString() === y.toDateString()) return "Yesterday, " + at;
  return d.getDate() + " " + MONTHS[d.getMonth()] +
    (d.getFullYear() === now.getFullYear() ? "" : " " + d.getFullYear()) + ", " + at;
}
function post(path, body) {
  return fetch(path + "?" + Q, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      return { ok: r.ok && !(j && j.error), j: j || {} };
    });
  }).catch(function () {
    return { ok: false, j: { error: "Rouh could not be reached." } };
  });
}
/* The page again, from Rouh, where the reader was: hosted, Rouh's column loads
   it; for a reader it is shared with, the page around this one (reader.js). */
function reloadAfter() {
  tellRouh({ what: "reload", thread: Number(threadId) || 0, y: window.scrollY || 0 });
}

var float = root.querySelector("#askai-float");
var histBtn = root.querySelector("#askai-hist-btn");
var optsBtn = root.querySelector("#askai-opts-btn");

/* One panel under the floating bar, holding History or Options, never both. */
var panel = node("section");
panel.id = "askai-panel";
panel.setAttribute("role", "dialog");
panel.hidden = true;
panel.innerHTML = '<div class="askai-ph"><span class="askai-pt"></span>' +
  '<span class="askai-ps"></span><button type="button" class="askai-px" ' +
  'title="Close" aria-label="Close">✕</button></div><div class="askai-pl"></div>';
root.appendChild(panel);
var panelKind = "";
var panelList = panel.querySelector(".askai-pl");

function panelOpen(kind, title, sub) {
  panelKind = kind;
  panel.setAttribute("aria-label", title);
  panel.querySelector(".askai-pt").textContent = title;
  panel.querySelector(".askai-ps").textContent = sub || "";
  panel.hidden = false;
  if (histBtn) histBtn.classList.toggle("on", kind === "history");
  if (optsBtn) optsBtn.classList.toggle("on", kind === "options");
}
function panelClose() {
  panelKind = "";
  panel.hidden = true;
  if (histBtn) histBtn.classList.remove("on");
  if (optsBtn) optsBtn.classList.remove("on");
}
panel.querySelector(".askai-px").addEventListener("click", panelClose);
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  if (popFor) { popClose(); e.stopPropagation(); return; }
  if (panelKind && !VIEWING) { panelClose(); e.stopPropagation(); }
}, true);

/* ---- History ---- */

function historyOpen() {
  panelOpen("history", "History", "Every change to this page, newest first");
  panelList.textContent = "";
  panelList.appendChild(node("p", "askai-pn", "Reading the history…"));
  fetch("/api/history?" + Q).then(function (r) {
    return r.json().then(function (j) { return { ok: r.ok, j: j }; });
  }).then(function (got) {
    if (panelKind !== "history") return;
    if (!got.ok || !got.j || !Array.isArray(got.j.entries)) throw new Error("no history");
    historyDraw(got.j.entries);
  }).catch(function () {
    if (panelKind !== "history") return;
    panelList.textContent = "";
    panelList.appendChild(node("p", "askai-pn bad", "The history could not be read."));
  });
}
function historyAgain() { if (panelKind === "history") historyOpen(); }

function historyDraw(entries) {
  panelList.textContent = "";
  var here = VIEWING ? VIEWING.id : "";
  panelList.appendChild(historyRow({ id: "", kind: "now", summary: "The page as it is now" }, here));
  entries.forEach(function (e) { panelList.appendChild(historyRow(e, here)); });
  if (!entries.length) {
    panelList.appendChild(node("p", "askai-pn",
      "No changes yet. Every change made with Ask AI, and every new version saved, is listed here."));
  }
  var on = panelList.querySelector(".askai-he.on");
  if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest" });
}

function tag(words, cls, title) {
  var t = node("span", "askai-tag" + (cls ? " " + cls : ""), words);
  if (title) t.title = title;
  return t;
}

function historyRow(e, here) {
  var row = node("div", "askai-he k-" + e.kind + (e.id === here ? " on" : "") +
                 (e.undone ? " undone" : ""));
  var open = node("button", "askai-hb");
  open.type = "button";
  open.appendChild(node("span", "askai-hw", e.summary || "Changed the page"));
  var said = [e.who, when(e.at)].filter(Boolean).join(" · ");
  if (e.kind === "now") said = here ? "Leave the old version and go back to it" : "You are looking at it";
  if (said) open.appendChild(node("span", "askai-hm", said));
  open.title = e.kind === "now" ? "The page as it is now" : "See the page as it was then";
  open.addEventListener("click", function () {
    if (e.id === here) return;
    showVersion(e.id);
  });
  row.appendChild(open);

  var tags = node("div", "askai-ht");
  if (e.kind === "saved") tags.appendChild(tag("Saved", "", "A new version saved in the workspace's history"));
  if (e.kind === "undo") tags.appendChild(tag("Put back"));
  if (e.kind === "default") tags.appendChild(tag("Default picked", "opt-line"));
  if (e.kind === "change") {
    if (e.undone) {
      tags.appendChild(tag("Put back"));
    } else if (e.keep === "option") {
      tags.appendChild(tag("Option", "opt"));
      if (e.option === "gone") tags.appendChild(tag("No longer on the page", "", "The page changed there since"));
      if (e.option === "stopped") tags.appendChild(tag("Not offered any more"));
    } else if (e.keep === "final") {
      tags.appendChild(tag("Final", "", "Not kept as an option"));
    } else if (e.keepable && !VIEWING) {
      tags.appendChild(keepAsk(e, row));
    }
  }
  if (tags.childNodes.length) row.appendChild(tags);
  return row;
}

/* The question under a change nobody has decided about. Most of the time the
   answer is no, so no is one press and the same size as yes. */
function keepAsk(e, row) {
  var ask = node("span", "askai-kq");
  ask.appendChild(node("span", "askai-kw", "Keep as an option?"));
  var yes = node("button", "askai-ky", "Keep both");
  yes.type = "button";
  yes.title = "Keep this change and the version before it, so people can switch between them";
  var no = node("button", "askai-kn", "No, final");
  no.type = "button";
  no.title = "Keep this change as it is, with no switch";
  function decide(choice) {
    yes.disabled = no.disabled = true;
    post("/api/keep", { edit: e.edit, keep: choice }).then(function (got) {
      if (!got.ok) {
        yes.disabled = no.disabled = false;
        var bad = row.querySelector(".askai-kerr") || row.appendChild(node("p", "askai-kerr"));
        bad.textContent = got.j.error || "That could not be saved.";
        return;
      }
      if (got.j.options) optionsSet(got.j.options);
      e.keep = got.j.keep;
      if (e.keep === "option") e.option = "on";
      row.replaceWith(historyRow(e, VIEWING ? VIEWING.id : ""));
      tellRouh({ what: "kept", edit: e.edit, keep: e.keep });
    });
  }
  yes.addEventListener("click", function () { decide("option"); });
  no.addEventListener("click", function () { decide("final"); });
  ask.appendChild(yes);
  ask.appendChild(no);
  return ask;
}

/* Rouh loads the page as it was into this same frame, or the page as it is
   now for an empty one. */
function showVersion(id) {
  popClose();
  tellRouh({ what: "version", version: String(id || "") });
}

if (histBtn) {
  histBtn.addEventListener("click", function () {
    if (panelKind === "history") panelClose(); else historyOpen();
  });
}

/* ---- An old version, read only ---- */

if (VIEWING) {
  document.documentElement.classList.add("askai-viewing");
  document.documentElement.style.setProperty("--askai-crumb-h", "44px");
  var said = VIEWING.kind === "start"
    ? "before the first change here"
    : VIEWING.kind === "saved" ? "when this version was saved: " + (VIEWING.summary || "")
    : VIEWING.kind === "undo" ? "after " + (VIEWING.summary || "a change was put back")
    : "after " + (VIEWING.who ? VIEWING.who + "'s change: " : "the change: ") + (VIEWING.summary || "");
  var bar = node("div");
  bar.id = "askai-viewing";
  bar.setAttribute("role", "status");
  bar.innerHTML = '<span class="askai-vi">' + CLOCK + '</span>';
  var words = node("span", "askai-vw");
  words.appendChild(document.createTextNode("The page as it was "));
  words.appendChild(node("b", null, when(VIEWING.at)));
  words.appendChild(document.createTextNode(", " + said));
  words.title = words.textContent;
  bar.appendChild(words);
  bar.appendChild(node("span", "askai-vr", "Read only"));
  var back = node("button", "askai-vb", "Back to the current page");
  back.type = "button";
  back.addEventListener("click", function () { showVersion(""); });
  bar.appendChild(back);
  root.appendChild(bar);
  launch.hidden = true;
  if (histBtn) historyOpen();
}

/* ---- The options ---- */

var OPTS = [];
var chips = node("div");
chips.id = "askai-chips";
root.appendChild(chips);
var optBox = node("div");
optBox.id = "askai-optbox";
root.appendChild(optBox);
var pop = node("div");
pop.id = "askai-optpop";
pop.setAttribute("role", "dialog");
pop.setAttribute("aria-label", "Options");
pop.hidden = true;
root.appendChild(pop);
var popFor = null;

function parse(markup) {
  var t = document.createElement("template");
  t.innerHTML = String(markup || "");
  return t.content.firstElementChild;
}

/* Where a part is on the screen: by the number the page marked it with as it
   was sent, which is where the default starts in the file, and for the few
   elements that are never marked - a <style> - by its words. */
function locate(part, chosen) {
  if (part.at >= 0) {
    var marked = document.querySelector("[" + MARK + '="' + part.at + '"]');
    if (marked && !root.contains(marked)) return marked;
  }
  var want = parse(part.alts[chosen]);
  if (!want) return null;
  var same = document.getElementsByTagName(want.tagName);
  for (var i = 0; i < same.length; i++) {
    if (!root.contains(same[i]) && same[i].textContent === want.textContent) return same[i];
  }
  return null;
}

function optionsSet(list) {
  /* Every part back as the page has it, before the new list is drawn. */
  OPTS.forEach(function (o) { if (o.shown !== o.data.chosen) swap(o, o.data.chosen); });
  popClose();
  OPTS = (Array.isArray(list) ? list : []).map(function (d) {
    return {
      data: d, shown: d.chosen, chip: null,
      parts: (d.parts || []).map(function (p) {
        return { tag: p.tag, alts: p.alts || [], node: locate(p, d.chosen) };
      })
    };
  });
  chipsDraw();
  if (optsBtn) {
    optsBtn.hidden = !OPTS.length;
    optsBtn.querySelector(".askai-fbn").textContent = OPTS.length ? String(OPTS.length) : "";
  }
  if (panelKind === "options") optionsOpen();
}

/* One version of an option onto the screen. An element whose insides are the
   same in both versions keeps itself and has its attributes changed, so a
   button that changed colour keeps whatever the page's own script hung on it;
   a style sheet has its words changed; anything else is swapped whole. */
function swap(o, i) {
  if (o.shown === i) return;
  o.parts.forEach(function (p) {
    var at = p.node;
    if (!at || !at.isConnected) return;
    var from = parse(p.alts[o.shown]), to = parse(p.alts[i]);
    if (!to) return;
    if (/^style$/i.test(to.tagName)) { at.textContent = to.textContent; return; }
    if (from && from.tagName === to.tagName && from.innerHTML === to.innerHTML) {
      [].slice.call(at.attributes).forEach(function (a) {
        if (a.name !== MARK && !to.hasAttribute(a.name)) at.removeAttribute(a.name);
      });
      [].slice.call(to.attributes).forEach(function (a) { at.setAttribute(a.name, a.value); });
      return;
    }
    if (at.hasAttribute(MARK)) to.setAttribute(MARK, at.getAttribute(MARK));
    at.replaceWith(to);
    p.node = to;
  });
  o.shown = i;
}

function visibleEl(el) {
  if (!el || !el.isConnected || /^(style|script|link|meta|title|head)$/i.test(el.tagName)) return false;
  var r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
/* What a change to the page's styles is about: the rule the two versions
   first differ in, by its selector - ".cta" for a button made orange - and
   the first thing on the screen it styles. So the red and orange button has
   its tab on the button, where Petar would look for it. */
function styledBy(p) {
  var a = String(p.alts[0] || ""), b = String(p.alts[1] || "");
  var at = 0;
  while (at < a.length && at < b.length && a.charAt(at) === b.charAt(at)) at++;
  var upto = a.slice(0, at), open = upto.lastIndexOf("{");
  if (open < 0) return null;
  /* The rule starts after the one before it, or after the <style> tag's own
     ">" - not after a ">" in the selector, which is a child combinator. */
  var close = Math.max(upto.lastIndexOf("}", open), a.indexOf(">"));
  var selector = upto.slice(close + 1, open).replace(/\/\*[\s\S]*?\*\//g, "").trim();
  if (!selector || selector.charAt(0) === "@") return null;
  try {
    var all = document.querySelectorAll(selector);
    for (var i = 0; i < all.length; i++) if (!root.contains(all[i]) && visibleEl(all[i])) return all[i];
  } catch (err) {}
  return null;
}
function anchorOf(o) {
  for (var i = 0; i < o.parts.length; i++) if (visibleEl(o.parts[i].node)) return o.parts[i].node;
  for (var j = 0; j < o.parts.length; j++) {
    if (/^style$/i.test(o.parts[j].tag)) { var styled = styledBy(o.parts[j]); if (styled) return styled; }
  }
  return null;
}

function chipsDraw() {
  chips.textContent = "";
  OPTS.forEach(function (o) {
    var final = !!o.data.final;
    var b = node("button", "askai-chip" + (final ? " final" : ""));
    b.type = "button";
    b.innerHTML = final ? DECIDED : SLIDERS;
    b.appendChild(node("span", null, final ? "Decided" : o.data.alts.length + " options"));
    b.title = final ? "Decided: “" + o.data.alts[o.data.chosen].label + "” was made final"
      : "This part of the page has " + o.data.alts.length + " versions";
    b.setAttribute("aria-label", (final ? "Decided: " : "Options: ") + o.data.title);
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      if (popFor === o) popClose(); else popOpen(o, b);
    });
    b.addEventListener("mouseenter", function () { outline(anchorOf(o)); });
    b.addEventListener("mouseleave", function () { if (popFor !== o) outline(null); });
    o.chip = b;
    chips.appendChild(b);
  });
  chipsPlace();
}

var outlined = null;
function outline(el) {
  outlined = el;
  if (!el) { optBox.classList.remove("on"); return; }
  var r = el.getBoundingClientRect();
  optBox.style.left = (r.left - 3) + "px";
  optBox.style.top = (r.top - 3) + "px";
  optBox.style.width = (r.width + 6) + "px";
  optBox.style.height = (r.height + 6) + "px";
  optBox.classList.add("on");
}

function chipsPlace() {
  var top = VIEWING ? 44 : 0;
  OPTS.forEach(function (o) {
    var b = o.chip;
    if (!b) return;
    var a = VIEWING ? null : anchorOf(o);
    var r = a && a.getBoundingClientRect();
    if (!r || r.bottom < top + 8 || r.top > window.innerHeight - 8) { b.hidden = true; return; }
    b.hidden = false;
    var w = b.offsetWidth || 90;
    b.style.left = Math.min(Math.max(4, r.right - w), window.innerWidth - w - 4) + "px";
    b.style.top = Math.max(top + 4, r.top - 12) + "px";
  });
  if (popFor) popPlace();
  if (outlined) outline(outlined.isConnected ? outlined : null);
}
window.addEventListener("scroll", chipsPlace, true);
window.addEventListener("resize", chipsPlace);
window.addEventListener("hashchange", function () { setTimeout(chipsPlace, 60); });
document.addEventListener("click", function () { setTimeout(chipsPlace, 60); }, true);
/* A page that draws itself moves its parts about without saying so. */
setInterval(function () { if (OPTS.length) chipsPlace(); }, 800);

/* One option, as a block: its versions to switch between, which is the
   default, and the press that makes another one the default. The same block
   in the pop-up over the page and in the list under the floating bar. */
function optionBlock(o) {
  var final = !!o.data.final;
  var box = node("div", "askai-ob" + (final ? " final" : ""));
  var head = node("div", "askai-ot");
  head.appendChild(node("span", "askai-otl", final ? "Decided" : "Options"));
  head.appendChild(node("span", "askai-ots", o.data.title));
  box.appendChild(head);
  o.data.alts.forEach(function (a, i) {
    var line = node("div", "askai-oa" + (i === o.shown ? " shown" : ""));
    var pick = node("button", "askai-os");
    pick.type = "button";
    pick.setAttribute("aria-pressed", i === o.shown ? "true" : "false");
    pick.title = i === o.shown ? "On the screen now" : "Show this version";
    pick.appendChild(node("span", "askai-ol", a.label));
    /* Why it exists, beside it, every version. Petar, 24 September 2026
       (fr_662a64715b9f): "each option for how something should look or what
       we should choose needs to have reasoning somewhere around it so that we
       know why somebody picked that specific option to exist." */
    pick.appendChild(node("span", "askai-orsn" + (a.reason ? "" : " none"),
                          a.reason || "No reason given yet"));
    pick.appendChild(node("span", "askai-om" + (a.ai ? " ai" : ""), !a.who && i === 0
      ? "Until " + when(a.at) : [(a.ai ? "\u2726 " : "") + a.who, when(a.at)].filter(Boolean).join(" · ")));
    pick.addEventListener("click", function () {
      swap(o, i);
      optionRedraw(o);
      var at = anchorOf(o);
      if (at) outline(at);
    });
    line.appendChild(pick);
    var acts = node("div", "askai-oacts");
    if (i === o.data.chosen) {
      acts.appendChild(final ? tag("Final", "opt-line final", "This is what was decided")
        : tag("Default", "opt-line", "Everybody sees this version when the page opens"));
    } else if (!final) {
      var make = node("button", "askai-omk", "Make default");
      make.type = "button";
      make.title = "Everybody sees this version when the page opens";
      make.addEventListener("click", function () { makeDefault(o, i, make, box); });
      acts.appendChild(make);
    }
    /* Closing the choice: this version, and no more choosing. Petar, 29
       September 2026 (fr_a383dc8329c0): "coding an option as final between
       all those other options". */
    if (CAN_EDIT && !final) {
      var fin = node("button", "askai-omk askai-ofn", "Make final");
      fin.type = "button";
      fin.title = "Decide on this version: it becomes the default, and the page shows the choice as made";
      fin.addEventListener("click", function () { makeFinal(o, i, fin, box); });
      acts.appendChild(fin);
    }
    line.appendChild(acts);
    box.appendChild(line);
    if (CAN_EDIT) box.appendChild(reasonEditor(o, i, box));
  });
  var foot = "Everybody sees the default when the page opens.";
  if (o.data.chosen_by) foot += " " + o.data.chosen_by + " made it the default, " + when(o.data.chosen_at) + ".";
  if (final) {
    foot = "“" + o.data.alts[o.data.chosen].label + "” was made final" +
      (o.data.final_by ? " by " + o.data.final_by : "") + ", " + when(o.data.final_at) +
      ". The other versions can still be looked at.";
  }
  box.appendChild(node("p", "askai-of", foot));
  if (CAN_EDIT && final) {
    var again = node("button", "askai-orm", "Open the choice again");
    again.type = "button";
    again.title = "Undo the decision, so a different version can be made the default";
    again.addEventListener("click", function () { reopenOption(o, again, box); });
    box.appendChild(again);
  }
  if (CAN_EDIT) {
    var stop = node("button", "askai-orm", "Stop offering these options");
    stop.type = "button";
    stop.title = "Keep the default on the page and let the other versions go";
    stop.addEventListener("click", function () { removeOption(o, stop, box); });
    box.appendChild(stop);
  }
  return box;
}

/* Writing why a version exists, for a reader who may change the page: a
   line under it that opens into a box, saved with Enter. */
function reasonEditor(o, i, box) {
  var a = o.data.alts[i];
  var wrap = node("div", "askai-orw");
  var ask = node("button", "askai-orb", a.reason ? "Change the reason" : "Add a reason");
  ask.type = "button";
  ask.title = "Say why this version exists";
  wrap.appendChild(ask);
  ask.addEventListener("click", function (e) {
    e.stopPropagation();
    wrap.textContent = "";
    var field = node("input", "askai-ori");
    field.type = "text";
    field.maxLength = 400;
    field.value = a.reason || "";
    field.placeholder = "Why this version exists";
    field.setAttribute("aria-label", "Why “" + a.label + "” exists");
    var save = node("button", "askai-omk", "Save");
    save.type = "button";
    var cancel = node("button", "askai-orb", "Cancel");
    cancel.type = "button";
    wrap.appendChild(field);
    wrap.appendChild(save);
    wrap.appendChild(cancel);
    function done() {
      save.disabled = true;
      post("/api/option", { option: o.data.id, action: "reason", choice: i, reason: field.value })
        .then(function (got) {
          if (!got.ok) {
            save.disabled = false;
            optionSay(box, got.j.error || "That could not be saved.");
            return;
          }
          a.reason = got.j.reason || "";
          optionRedraw(o);
        });
    }
    save.addEventListener("click", function (ev) { ev.stopPropagation(); done(); });
    cancel.addEventListener("click", function (ev) { ev.stopPropagation(); optionRedraw(o); });
    field.addEventListener("keydown", function (ev) {
      ev.stopPropagation();
      if (ev.key === "Enter") { ev.preventDefault(); done(); }
      if (ev.key === "Escape") { ev.preventDefault(); optionRedraw(o); }
    });
    ["keyup", "keypress"].forEach(function (k) {
      field.addEventListener(k, function (ev) { ev.stopPropagation(); });
    });
    setTimeout(function () { field.focus(); }, 0);
  });
  return wrap;
}

function optionSay(box, words) {
  var bad = box.querySelector(".askai-oe") || box.appendChild(node("p", "askai-oe"));
  bad.textContent = words;
}

function optionRedraw(o) {
  if (popFor === o) {
    pop.textContent = "";
    pop.appendChild(optionBlock(o));
    popPlace();
  }
  if (panelKind === "options") optionsOpen();
}

function makeDefault(o, i, button, box) {
  button.disabled = true;
  button.textContent = "Saving…";
  post("/api/option", { option: o.data.id, action: "default", choice: i }).then(function (got) {
    if (!got.ok) {
      button.disabled = false;
      button.textContent = "Make default";
      optionSay(box, got.j.error || "That could not be saved.");
      return;
    }
    button.textContent = "Default";
    reloadAfter();
  });
}

function makeFinal(o, i, button, box) {
  button.disabled = true;
  button.textContent = "Saving…";
  post("/api/option", { option: o.data.id, action: "final", choice: i }).then(function (got) {
    if (!got.ok) {
      button.disabled = false;
      button.textContent = "Make final";
      optionSay(box, got.j.error || "That could not be saved.");
      return;
    }
    /* A new default is a new page, so it is loaded again, as Make default
       does; the same one is only the choice closing, drawn in place. */
    if (got.j.changed) { reloadAfter(); return; }
    optionsSet(got.j.options || []);
    historyAgain();
  });
}

function reopenOption(o, button, box) {
  button.disabled = true;
  post("/api/option", { option: o.data.id, action: "reopen" }).then(function (got) {
    if (!got.ok) {
      button.disabled = false;
      optionSay(box, got.j.error || "That could not be saved.");
      return;
    }
    optionsSet(got.j.options || []);
  });
}

function removeOption(o, button, box) {
  button.disabled = true;
  post("/api/option", { option: o.data.id, action: "remove" }).then(function (got) {
    if (!got.ok) {
      button.disabled = false;
      optionSay(box, got.j.error || "That could not be saved.");
      return;
    }
    optionsSet(got.j.options || []);
    historyAgain();
  });
}

function popOpen(o, chip) {
  popFor = o;
  pop.textContent = "";
  pop.appendChild(optionBlock(o));
  pop.hidden = false;
  popPlace(chip);
  outline(anchorOf(o));
}
function popClose() {
  if (!popFor) return;
  popFor = null;
  pop.hidden = true;
  outline(null);
}
/* Under the part it switches rather than over it, so the reader watches the
   part change as they press; above it when there is no room below; beside
   it when there is room there and none above or below, which is what a part
   with several versions, each with its reason, comes to; and beside the tab
   when there is room nowhere. */
function popPlace() {
  if (!popFor || !popFor.chip || popFor.chip.hidden) { popClose(); return; }
  var c = popFor.chip.getBoundingClientRect();
  var at = anchorOf(popFor);
  var r = at ? at.getBoundingClientRect() : c;
  var w = pop.offsetWidth, h = pop.offsetHeight, room = window.innerHeight - 8;
  var W = window.innerWidth;
  var left = Math.min(Math.max(8, r.left), W - w - 8);
  var top = r.bottom + 8;
  if (top + h > room) {
    if (r.top - h - 8 >= 8) top = r.top - h - 8;
    else if (r.right + 10 + w <= W - 8 || r.left - 10 - w >= 8) {
      left = r.right + 10 + w <= W - 8 ? r.right + 10 : r.left - 10 - w;
      top = Math.min(r.top, room - h);
    } else top = c.bottom + 6;
  }
  pop.style.left = Math.max(8, left) + "px";
  pop.style.top = Math.max(8, Math.min(top, room - h)) + "px";
}
document.addEventListener("mousedown", function (e) {
  if (popFor && !pop.contains(e.target) && !(popFor.chip && popFor.chip.contains(e.target))) popClose();
}, true);

/* Every option on the page, under the floating bar: the way to the ones with
   nothing on the screen to hang a tab on. */
function optionsOpen() {
  panelOpen("options", "Options", OPTS.length === 1 ? "1 part of this page has versions"
    : OPTS.length + " parts of this page have versions");
  panelList.textContent = "";
  OPTS.forEach(function (o) {
    var box = optionBlock(o);
    var at = anchorOf(o);
    if (at) {
      var go = node("button", "askai-ogo", "Show where");
      go.type = "button";
      go.addEventListener("click", function () {
        var where = anchorOf(o);
        if (!where) return;
        where.scrollIntoView({ block: "center", behavior: "smooth" });
        setTimeout(function () { outline(where); }, 350);
        setTimeout(function () { if (outlined === where && popFor !== o) outline(null); }, 2200);
      });
      box.querySelector(".askai-ot").appendChild(go);
    } else {
      box.querySelector(".askai-ot").appendChild(node("span", "askai-onote", "Not a part you can point at, such as the page's styles"));
    }
    panelList.appendChild(box);
  });
  if (!OPTS.length) panelList.appendChild(node("p", "askai-pn", "No options on this page."));
}
if (optsBtn) {
  optsBtn.addEventListener("click", function () {
    if (panelKind === "options") panelClose(); else optionsOpen();
  });
}

if (!VIEWING) optionsSet(window.ASKAI_OPTIONS || []);

/* Ask AI's pass over the comments offered another version of something on
   the page (comments.js, "the pass"): the options as they are now. */
document.addEventListener("askai-options-stale", function () {
  if (VIEWING) return;
  post("/api/option", { action: "list" }).then(function (got) {
    if (got.ok && got.j.options) optionsSet(got.j.options);
  });
});

/* --------------------------------------------------------------------- boot - */

/* Explainers pin their own sidebars and TOCs with `position:sticky; top:0`, which
 * would slide under the fixed bar. Offsetting them by computed style rather than
 * by class name covers every layout - and any explainer written later. */
function clearTheBar() {
  /* A frame says the bar is 0px high, and 0 is a height: "|| 44" read it as
     unset and pushed every sticky sidebar 44px down, over a gap. */
  var h = parseFloat(getComputedStyle(document.documentElement)
            .getPropertyValue("--askai-crumb-h"));
  if (isNaN(h)) h = 44;
  if (h === 0) return;
  var all = document.body.querySelectorAll("*");
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (root.contains(el)) continue;
    var cs = getComputedStyle(el);
    if (cs.position !== "sticky" || parseFloat(cs.top) !== 0) continue;
    el.style.top = h + "px";
    /* A full-height sticky rail would now overflow by exactly the bar height. */
    if (Math.abs(el.getBoundingClientRect().height - window.innerHeight) < 2) {
      el.style.height = "calc(100vh - " + h + "px)";
    }
  }
}

/* What Rouh asks of the page while it is hosting the conversation. Two things,
 * and neither is an instruction to run: hand back the words a reader can
 * actually see - these pages draw themselves, so the markup Rouh holds is not
 * what is on the screen - and draw the marks again, because a passage just
 * asked about has become one. */
if (HOSTED) {
  window.addEventListener("message", function (e) {
    if (e.source !== UP) return;
    var m = e.data;
    if (!m || m.type !== "rouh-askai-do") return;
    if (m.what === "context") {
      tellRouh({ what: "context", id: m.id, text: pageText(), y: window.scrollY || 0 });
      return;
    }
    if (m.what === "marks") { refreshHighlights(); return; }
    /* The changes Ask AI just made in Rouh's column, onto this page where it
       is; the page is asked for again only if one of them cannot be. */
    if (m.what === "patch") {
      pickShow(null);
      if (!(Array.isArray(m.patches) && m.patches.length && m.patches.every(patchPage))) pageAgain();
      return;
    }
    /* A change kept as an option, or not, in Rouh's column: the options are
       drawn again, and the history with them if it is open. */
    if (m.what === "options") { optionsSet(m.options); historyAgain(); return; }
    /* Point, pressed in Rouh's column; pressed again, or the pick let go. An
       old version of the page is read only, so there is nothing to point at
       and the button in the column is told so. */
    if (m.what === "point") {
      if (!CAN_EDIT) { tellRouh({ what: "pointing", on: false }); return; }
      pickStart();
      return;
    }
    if (m.what === "unpoint") { pickStop(false); return; }
    if (m.what === "unpick") { pickShow(null); return; }
    /* Show me, pressed beside a change in Rouh's column (`rouh/askai_show.py`): the part it
       made, found by its words, brought into view and lit for a moment. */
    if (m.what === "show") { showPart(m); return; }
  }, false);
}

/* Show me where (night 24, switch `askai_show`): the element of `tag` whose words are `text`,
   the `nth` such from the top, or failing that the heading the change is under. Rouh is told
   whether it was found and whether it is showing, so its column can say where it is when not. */
function squash(t) { return String(t || "").replace(/\s+/g, " ").trim(); }
function showPart(m) {
  var tag = String(m.tag || "").toLowerCase().replace(/[^a-z0-9-]/g, "");
  var text = squash(m.text), heading = squash(m.heading), el = null;
  function mine(x) { return !root.contains(x); }
  if (tag && text) {
    var same = Array.prototype.filter.call(document.querySelectorAll(tag), function (x) {
      return mine(x) && squash(x.textContent).slice(0, text.length) === text;
    });
    el = same[Math.min(Number(m.nth) || 0, same.length - 1)] || null;
    if (!el) {
      var head = text.slice(0, 60);
      var holds = Array.prototype.filter.call(document.querySelectorAll(tag), function (x) {
        return mine(x) && squash(x.textContent).indexOf(head) !== -1;
      });
      holds.sort(function (a, b) { return a.textContent.length - b.textContent.length; });
      el = holds[0] || null;
    }
  }
  if (!el && heading) {
    el = Array.prototype.filter.call(document.querySelectorAll("h1,h2,h3,h4,h5,h6"), function (x) {
      return mine(x) && squash(x.textContent) === heading;
    })[0] || null;
  }
  if (!el) { tellRouh({ what: "shown", found: false }); return; }
  var style = window.getComputedStyle(el);
  var hidden = !el.getClientRects().length || style.visibility === "hidden";
  tellRouh({ what: "shown", found: true, hidden: hidden });
  if (hidden) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  if (typeof el.animate === "function") {
    el.animate([
      { outline: "3px solid rgba(245, 166, 35, 0)", outlineOffset: "6px" },
      { outline: "3px solid rgba(245, 166, 35, 1)", outlineOffset: "3px", offset: 0.15 },
      { outline: "3px solid rgba(245, 166, 35, 1)", outlineOffset: "3px", offset: 0.8 },
      { outline: "3px solid rgba(245, 166, 35, 0)", outlineOffset: "3px" }
    ], { duration: 2200, easing: "ease-out" });
  }
}

/* Sent again after a change: back where the reader was on the page, and -
   in the drawer - with the topic they were in open again. A page that draws
   itself may not be its full height at once, so the scroll is set twice. */
var BACK_TO = Number(window.ASKAI_SCROLL) || 0;
if (BACK_TO > 0) {
  window.scrollTo(0, BACK_TO);
  setTimeout(function () { window.scrollTo(0, BACK_TO); }, 300);
}
var REOPEN = HOSTED ? 0 : Number(window.ASKAI_OPEN) || 0;

size();
clearTheBar();
refreshHighlights().then(function () {      /* never blocks first render */
  if (REOPEN) loadThread(String(REOPEN));
});
})();

/* =============================================================== drill-down -
 * A second way to read a page: one sentence stating a finding, one picture that
 * lets it be checked, and the three to five findings that matter next, each of
 * which can be added below or opened as a new branch to the side. Typed
 * questions go to /api/ask and come back as one sentence and one picture.
 *
 * It appears only where the page has a findings file beside it, named after the
 * page (index.html -> index.findings.json); the format is in _askai/README.md.
 * It lives in this file because askai.js is the one script every copy of the
 * workspace injects, briefings.page included, and it draws inside a shadow root
 * so no explainer's styles can reach it and none of its styles reach the page. */
(function () {
"use strict";

if (window.ASKAI_BAR_ONLY || window.__askaiDrill) return;
window.__askaiDrill = true;

var DOC = window.ASKAI_DOC || "";
/* The top bar's data says whether this page has a findings file, and its name,
 * so a page without one never asks for it. Fetched beside the page. */
var FINDINGS = (window.ASKAI_CRUMB || {}).findings || "";
var KEY = "askai-dd:" + (DOC || location.pathname);

var D = null;        /* the findings file */
var S = null;        /* where the reader is: branches, what is open, what is seen */
var host = null, sh = null, toggle = null, busy = false;

function store(k, v) { try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (e) {} }
function recall(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }

var CSS = `
:host {
  --bg: #eeede8; --surface: #fbfbf9; --panel: #f3f2ee; --line: #dedbd2; --line-strong: #c7c2b5;
  --ink: #1b1c1e; --ink-soft: #45454a; --ink-mute: #76736b; --accent: #0b7a8a; --accent-ink: #ffffff;
  --accent-soft: color-mix(in srgb, var(--accent) 12%, transparent);
  --risk: #b8402c; --decide: #1f5fbf; --disagree: #a86a00; --assume: #6b4bb3;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  --col-w: clamp(640px, 44vw, 780px);
  color-scheme: light;
}
:host([data-theme="dark"]) {
  --bg: #0c0e10; --surface: #15181b; --panel: #1b1f23; --line: #262b31; --line-strong: #373e46;
  --ink: #ebe9e3; --ink-soft: #bdbab1; --ink-mute: #8c8980; --accent: #3fc3d3; --accent-ink: #062226;
  --risk: #f08069; --decide: #74a8ff; --disagree: #e3ab3c; --assume: #b59eff;
  color-scheme: dark;
}
* { box-sizing: border-box; }
button, input { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.app { height: 100%; display: flex; flex-direction: column; background: var(--bg); color: var(--ink); font: 15px/1.5 var(--sans); -webkit-font-smoothing: antialiased; position: relative; }

.topbar { flex: none; display: flex; align-items: center; gap: 10px; padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--line); }
.tabs { flex: 1; min-width: 0; display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; padding: 2px; }
.tabs::-webkit-scrollbar { display: none; }
.tab { flex: none; display: flex; align-items: center; gap: 7px; max-width: 250px; padding: 5px 10px 5px 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); cursor: pointer; font-size: 13px; }
.tab .n { flex: none; width: 20px; height: 20px; border-radius: 5px; display: grid; place-items: center; font: 700 11px/1 var(--mono); background: var(--line); color: var(--ink-soft); }
.tab .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tab .c { color: var(--ink-mute); font-size: 12px; }
.tab.on { border-color: var(--accent); background: var(--accent-soft); }
.tab.on .n { background: var(--accent); color: var(--accent-ink); }
.tools { flex: none; display: flex; align-items: center; gap: 6px; }
.btn { padding: 6px 10px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--surface); cursor: pointer; font-size: 12.5px; color: var(--ink-soft); white-space: nowrap; }
.btn:hover { color: var(--ink); border-color: var(--ink-mute); }
.btn b { color: var(--ink); }
.btn .need { color: var(--risk); font-weight: 600; }

.ws { flex: 1; min-height: 0; display: flex; gap: 12px; padding: 12px 16px; overflow-x: auto; overflow-y: hidden; position: relative; scroll-behavior: smooth; }
.col { flex: 0 0 var(--col-w); min-height: 0; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.col.on { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 30%, transparent); }
.col-head { flex: none; padding: 9px 16px; border-bottom: 1px solid var(--line); }
.col-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; font: 600 10.5px/1.3 var(--mono); letter-spacing: .07em; text-transform: uppercase; color: var(--ink-mute); }
.col-title .x { border: 0; background: none; cursor: pointer; font: 400 18px/1 var(--sans); color: var(--ink-mute); padding: 0 4px; }
.crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 3px; margin-top: 4px; font-size: 13px; }
.crumb { border: 0; background: none; padding: 2px 4px; border-radius: 5px; cursor: pointer; color: var(--accent); text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
.crumb:hover { background: var(--accent-soft); }
.crumb.other { color: var(--ink-mute); }
.ln { font: 700 10px/1 var(--mono); padding: 2px 4px; margin-right: 4px; border-radius: 4px; background: var(--line); color: var(--ink-soft); display: inline-block; text-decoration: none; }
.crumbs .sep { color: var(--ink-mute); }
.crumbs .here { font-weight: 650; padding: 2px 4px; }
.col-body { flex: 1; min-height: 0; overflow-y: auto; position: relative; padding: 0 18px 28px; overscroll-behavior: contain; }
.ghost { flex: 0 0 260px; display: grid; place-items: center; padding: 20px; border: 1px dashed var(--line-strong); border-radius: 12px; color: var(--ink-mute); font-size: 13.5px; text-align: center; }

.block { padding: 18px 0 16px; border-top: 1px solid var(--line); }
.block:first-child { border-top: 0; }
.block.flash { animation: flash 1.4s ease-out; }
@keyframes flash { from { background: var(--accent-soft); } to { background: transparent; } }
@media (prefers-reduced-motion: reduce) { .block.flash { animation: none; } .ws { scroll-behavior: auto; } }
.kicker { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; margin: 0 0 6px; font: 600 10.5px/1.3 var(--mono); letter-spacing: .07em; text-transform: uppercase; color: var(--ink-mute); }
.question { margin: 0 0 14px; padding: 10px 12px; border-left: 3px solid var(--line-strong); border-radius: 0 8px 8px 0; background: var(--panel); font-size: 14.5px; line-height: 1.45; color: var(--ink-soft); }
.question b { display: block; margin-bottom: 2px; font: 600 10.5px/1.3 var(--mono); letter-spacing: .07em; text-transform: uppercase; color: var(--ink-mute); }
.sentence { margin: 0 0 14px; font-size: 1.25rem; line-height: 1.36; font-weight: 650; letter-spacing: -.005em; text-wrap: pretty; }
.wait { display: flex; align-items: center; gap: 10px; color: var(--ink-mute); font-size: 14px; }
.wait i { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1s infinite ease-in-out; }
@keyframes pulse { 50% { opacity: .25; } }
.err { color: var(--risk); font-size: 14px; }
.meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 14px; margin: 8px 0 0; font-size: 12.5px; color: var(--ink-mute); }
.meta button { border: 0; background: none; padding: 0; cursor: pointer; color: var(--accent); font-size: 12.5px; white-space: nowrap; }
.meta button:hover { text-decoration: underline; }
.opened { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px; border: 1px solid var(--line); border-radius: 999px; background: var(--panel); cursor: pointer; font-size: 12.5px; color: var(--ink-soft); }
.chip:hover { border-color: var(--line-strong); color: var(--ink); }
.chip .ln { margin: 0; background: var(--accent); color: var(--accent-ink); }
.more { margin-top: 10px; border: 0; background: none; padding: 2px 0; cursor: pointer; font-size: 12.5px; color: var(--accent); }

.fork { margin-top: 18px; }
.fork-h { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 12px; margin: 0 0 8px; }
.fork-h b { font: 600 10.5px/1.3 var(--mono); letter-spacing: .07em; text-transform: uppercase; color: var(--ink-mute); }
.fork-h span { font-size: 12px; color: var(--ink-mute); }
.cards { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 8px; }
.card { display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); min-width: 0; }
.card:hover { border-color: var(--line-strong); }
.card .txt { border: 0; background: none; padding: 0; text-align: left; cursor: pointer; font-size: 13.5px; font-weight: 600; line-height: 1.36; color: var(--ink); }
.card .acts { margin-top: auto; display: flex; gap: 6px; }
.act { flex: 1; padding: 6px 0; border: 1px solid var(--line-strong); border-radius: 7px; background: var(--surface); cursor: pointer; font-size: 12px; font-weight: 600; color: var(--ink-soft); white-space: nowrap; }
.act:hover { color: var(--ink); border-color: var(--ink-mute); }
.act.side { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--line-strong)); }
.tag { display: inline-flex; align-items: center; gap: 6px; font: 600 10px/1.3 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--ink-soft); }
.tag::before { content: ""; flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--c, var(--line-strong)); }
.tag.risk { --c: var(--risk); } .tag.decide { --c: var(--decide); } .tag.disagree { --c: var(--disagree); } .tag.assume { --c: var(--assume); }
.done { margin: 14px 0 0; font-size: 13.5px; color: var(--ink-soft); }

.dock { flex: none; display: flex; align-items: center; gap: 8px; padding: 9px 16px calc(9px + env(safe-area-inset-bottom)); background: var(--surface); border-top: 1px solid var(--line); }
.asking { flex: none; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--ink-mute); }
.asking b { color: var(--ink-soft); }
.ask { flex: 1; min-width: 0; padding: 9px 12px; border: 1px solid var(--line-strong); border-radius: 10px; background: var(--panel); color: var(--ink); font-size: 16px; }
.ask::placeholder { color: var(--ink-mute); }
.send { flex: none; padding: 9px 14px; border: 0; border-radius: 10px; background: var(--accent); color: var(--accent-ink); cursor: pointer; font-size: 14px; font-weight: 600; }
.send.side { background: var(--surface); color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line-strong)); }
.send:disabled { opacity: .5; cursor: default; }

.pop { position: absolute; z-index: 20; top: 52px; right: 12px; width: min(440px, calc(100% - 24px)); max-height: min(70%, 560px); overflow-y: auto; padding: 14px; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 12px; box-shadow: 0 12px 40px rgb(0 0 0 / .22); }
.pop[hidden] { display: none; }
.pop h3 { margin: 0 0 4px; font-size: 14px; }
.pop p { margin: 0 0 10px; font-size: 12.5px; color: var(--ink-mute); }
.pop .card { margin-top: 8px; }

.pic { padding: 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; overflow-x: auto; }
.cap { margin: 12px 0 0; font-size: 12.5px; line-height: 1.45; color: var(--ink-mute); }
.t { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; line-height: 1.38; }
.t.wide { min-width: 460px; }
.t th, .t td { padding: 7px 9px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); }
.t thead th { font-weight: 650; border-bottom-color: var(--line-strong); }
.t tbody th { font-weight: 600; color: var(--ink-soft); }
.t tr:last-child > * { border-bottom: 0; }
.t .mk { background: var(--accent-soft); }
.t thead .mk { box-shadow: inset 0 3px 0 var(--accent); }
.mk-label { display: block; margin-top: 3px; font: 600 10px/1.2 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--accent); }
.t tr.mkrow > * { background: var(--accent-soft); font-weight: 600; }
.t tr.mkrow > th:first-child { box-shadow: inset 3px 0 0 var(--accent); }
.t tr.desc > * { font-size: 12.5px; font-weight: 400; color: var(--ink-soft); }
.tl { position: relative; height: 100px; min-width: 300px; margin: 0 6px; }
.tl .axis { position: absolute; left: 0; right: 0; top: 43px; height: 2px; background: var(--line-strong); }
.tl .band { position: absolute; top: 33px; height: 22px; border-radius: 4px; background: color-mix(in srgb, var(--disagree) 26%, transparent); }
.tl .dot { position: absolute; top: 37px; width: 14px; height: 14px; border-radius: 50%; transform: translateX(-50%); background: var(--surface); border: 2px solid var(--ink-mute); }
.tl .dot.loud { background: var(--accent); border-color: var(--accent); }
.tl .lab { position: absolute; white-space: nowrap; font-size: 12.5px; line-height: 1.3; color: var(--ink-soft); }
.tl .up { top: 8px; } .tl .down { top: 60px; } .tl .down2 { top: 78px; }
.tl .l { transform: translateX(-7px); } .tl .r { transform: translateX(calc(-100% + 7px)); } .tl .c { transform: translateX(-50%); }
.tl .lab.loud { color: var(--ink); font-weight: 650; }
.tl .lab.tick { font-size: 11.5px; color: var(--ink-mute); }
.bars { display: grid; gap: 12px; }
.brow .bl { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 4px; font-size: 13px; color: var(--ink-soft); }
.brow .bl b { color: var(--ink); white-space: nowrap; font-variant-numeric: tabular-nums; }
.brow.loud .bl { color: var(--ink); font-weight: 600; }
.track { height: 12px; border-radius: 6px; background: var(--line); overflow: hidden; }
.fill { height: 100%; border-radius: 6px; background: var(--ink-mute); }
.brow.loud .fill { background: var(--accent); }
.fact { display: grid; grid-template-columns: 6.4em 1fr auto; gap: 4px 12px; align-items: baseline; padding: 8px 0; border-top: 1px solid var(--line); font-size: 13.5px; }
.fact:first-child { border-top: 0; padding-top: 0; }
.fact .v { font-size: 1.05rem; font-weight: 700; white-space: nowrap; font-variant-numeric: tabular-nums; }
.fact.loud .v { color: var(--accent); }
.grade { font: 600 10px/1.2 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--ink-soft); border: 1px solid var(--line-strong); border-radius: 999px; padding: 3px 8px; white-space: nowrap; }
.plist { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; counter-reset: p; }
.plist li { counter-increment: p; display: grid; grid-template-columns: 24px 1fr; gap: 10px; font-size: 13.5px; line-height: 1.42; }
.plist li::before { content: counter(p); height: 22px; display: grid; place-items: center; font: 600 11px/1 var(--mono); color: var(--ink-mute); border: 1px solid var(--line-strong); border-radius: 6px; }
.plist li.loud { font-weight: 650; }
.plist li.loud::before { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
.stc { margin: 0 0 8px; font-size: 13px; color: var(--ink-soft); }
.stc b { font-size: 1.35rem; color: var(--ink); margin-right: 4px; }
.srow { display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; padding: 8px 0; border-top: 1px solid var(--line); font-size: 13.5px; }
.srow .st { font: 600 10px/1.9 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--decide); }
.srow .rec { grid-column: 2; font-size: 12.5px; color: var(--ink-mute); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.side-box { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); font-size: 13px; line-height: 1.45; }
.side-box.mk { border-color: var(--accent); box-shadow: inset 0 3px 0 var(--accent); }
.side-box h4 { margin: 0 0 6px; font-size: 13.5px; }
.side-box p { margin: 0 0 6px; color: var(--ink-soft); }
.side-box p:last-child { margin: 0; }
.score { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
.score div { padding: 10px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); text-align: center; }
.score b { display: block; font-size: 1.05rem; }
.score span { font-size: 11.5px; color: var(--ink-mute); }
.score .good b { color: var(--accent); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
.stat { padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.stat b { display: block; font-size: 1.3rem; line-height: 1.2; font-variant-numeric: tabular-nums; }
.stat span { font-size: 12px; line-height: 1.35; color: var(--ink-soft); }
.stat.loud { border-color: var(--accent); }
.stat.loud b { color: var(--accent); }
.flow { list-style: none; margin: 0; padding: 0; display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 22px; }
.flow li { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); font-size: 12.5px; line-height: 1.4; color: var(--ink-soft); }
.flow li b { font-size: 13.5px; line-height: 1.3; color: var(--ink); }
.flow li.loud { border-color: var(--accent); box-shadow: inset 0 3px 0 var(--accent); }
.flow li + li::before { content: "\\2192"; position: absolute; left: -17px; top: 50%; transform: translateY(-50%); color: var(--ink-mute); font-size: 15px; }

@media (max-width: 760px) {
  .topbar { flex-wrap: wrap; gap: 8px; }
  .tabs { order: 3; flex-basis: 100%; }
  .tools { margin-left: auto; }
  .ws { padding: 0; gap: 0; overflow: hidden; }
  .col { display: none; flex: 1 1 auto; border: 0; border-radius: 0; box-shadow: none !important; }
  .col.on { display: flex; }
  .ghost, .asking { display: none; }
  .col-body { padding: 0 16px 24px; }
  .sentence { font-size: 1.15rem; }
  .cards { grid-auto-columns: 76%; overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 6px; margin-right: -16px; padding-right: 16px; }
  .card { scroll-snap-align: start; }
  .pair { grid-template-columns: 1fr; }
  .score { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .fact { grid-template-columns: 1fr auto; } .fact .v { grid-column: 1 / -1; }
  .flow { grid-auto-flow: row; gap: 18px; }
  .flow li + li::before { content: "\\2193"; left: 50%; top: -17px; transform: translateX(-50%); }
  .pop { top: 96px; }
}
`;

/* How a typed question is asked, so the answer comes back as one sentence and
 * one picture through the same /api/ask every copy of the workspace answers. */
var FORMAT = "\n\n---\nAnswer for a reader who has read none of this page. Reply with one JSON object and nothing else, in this shape:\n" +
  '{"sentence": "the answer in one plain sentence of at most 25 words; define any term the page coined; numbers and detail go in the picture", "label": "two to five words naming this answer", ' +
  '"picture": PICTURE, "caption": "one sentence under the picture", "sure": "how sure, in plain words: strong, fair or weak source, the page\'s own judgement, or not in the page", ' +
  '"page": "the number of the page of this document that says it, like 05, or empty"}\n' +
  'PICTURE is null or one of: {"type":"stats","items":[["value","what it is"]]} with 2 to 5 items; ' +
  '{"type":"bars","rows":[["label","value as text",0.4]]} where the number is a share from 0 to 1; ' +
  '{"type":"pair","items":[{"h":"title","p":["sentence"]},{"h":"title","p":["sentence"]}]}; ' +
  '{"type":"list","items":[["point"]]}; {"type":"rows","head":["","column","column"],"rows":[["row","cell","cell"]]}; ' +
  '{"type":"flow","steps":[{"h":"title","p":"sentence"}]} with 2 to 4 steps.\n' +
  "Use only what the page and its notes say. If they do not answer it, say so in the sentence and set picture to null.";
var ASKED = { stats: 1, bars: 1, pair: 1, list: 1, rows: 1, flow: 1 };
var DRAWN = { choice: 1, rows: 1, timeline: 1, bars: 1, facts: 1, list: 1, status: 1, pair: 1, score: 1, stats: 1, flow: 1 };

var ROOT = null, PARENT = {};
function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function node(k) { return (S && S.extra[k]) || D.findings[k]; }
function weight(k) { var n = node(k), T = D.tags || {}; return n && n.tag && T[n.tag] ? T[n.tag][1] : 5; }
function seenCount() { return D.order.filter(function (k) { return S.seen[k]; }).length; }

/* ------------------------------------------------------------------ state - */
function fresh() {
  var s = { lines: [{ id: 1, origin: null, blocks: [ROOT], scroll: 0 }], focus: 1, seen: {}, where: {},
            from: {}, next: 2, open: {}, extra: {}, thread: null, qn: 0 };
  s.seen[ROOT] = true; s.where[ROOT] = 1;
  return s;
}
function restore() {
  try {
    var s = JSON.parse(recall(KEY + ":state") || "null");
    if (s && s.lines && s.lines.length && s.lines[0].blocks[0] === ROOT && s.extra) {
      s.lines.forEach(function (L) { L.blocks = L.blocks.filter(function (k) { return s.extra[k] || D.findings[k]; }); });
      Object.keys(s.extra).forEach(function (k) { if (s.extra[k].pending) { s.extra[k].pending = false; s.extra[k].error = "The page was closed before the answer arrived. Ask again."; } });
      return s;
    }
  } catch (e) {}
  return fresh();
}
var saveTimer = null;
function save() { clearTimeout(saveTimer); saveTimer = setTimeout(function () { store(KEY + ":state", JSON.stringify(S)); }, 150); }
function line(id) { for (var i = 0; i < S.lines.length; i++) if (S.lines[i].id === id) return S.lines[i]; return null; }
function idx(id) { for (var i = 0; i < S.lines.length; i++) if (S.lines[i].id === id) return i; return -1; }
function descends(L, anc) { while (L && L.origin) { if (L.origin.line === anc) return true; L = line(L.origin.line); } return false; }
function lineName(L) { return L.origin ? "branch " + L.id : "the main line"; }
function chain(L) {
  var own = L.blocks.map(function (n) { return { line: L.id, node: n }; });
  if (!L.origin) return own;
  var P = line(L.origin.line);
  if (!P) return own;
  var pc = chain(P), cut = -1;
  for (var i = 0; i < pc.length; i++) if (pc[i].line === P.id && pc[i].node === L.origin.node) cut = i;
  return pc.slice(0, cut + 1).concat(own);
}

/* ---------------------------------------------------------------- actions - */
function openBelow(lineId, src, k) {
  if (S.where[k]) return jump(S.where[k], k, true);
  line(lineId).blocks.push(k);
  S.where[k] = lineId; S.seen[k] = true;
  S.from[k] = { line: lineId, node: src, how: "below" };
  S.focus = lineId; S.open = {};
  render({ line: lineId, node: k });
}
function openSide(lineId, src, k) {
  if (S.where[k]) return jump(S.where[k], k, true);
  var id = S.next++, i = idx(lineId) + 1;
  while (i < S.lines.length && descends(S.lines[i], lineId)) i++;
  S.lines.splice(i, 0, { id: id, origin: { line: lineId, node: src }, blocks: [k], scroll: 0 });
  S.where[k] = id; S.seen[k] = true;
  S.from[k] = { line: lineId, node: src, how: "side", to: id };
  S.focus = id; S.open = {};
  render({ line: id, node: k });
}
function jump(lineId, k, flash) { S.focus = lineId; render({ line: lineId, node: k, flash: flash }); }
function closeLine(id) {
  var L = line(id);
  if (!L || !L.origin || S.lines.some(function (x) { return x.origin && x.origin.line === id; })) return;
  L.blocks.forEach(function (n) { delete S.where[n]; delete S.from[n]; });
  S.lines.splice(idx(id), 1);
  if (S.focus === id) S.focus = L.origin.line;
  render({ line: S.focus, node: L.origin.node });
}

/* --------------------------------------------------------------- pictures - */
function tl(points, extra) {
  var h = '<div class="tl">' + (extra || "") + '<div class="axis"></div>';
  points.forEach(function (p) {
    var at = ' style="left:' + (Number(p.pos) * 100) + '%"';
    if (p.dot !== false) h += '<div class="dot' + (p.loud ? " loud" : "") + '"' + at + '></div>';
    h += '<div class="lab ' + (p.side || "down") + " " + (p.anchor || "c") + (p.loud ? " loud" : "") + (p.tick ? " tick" : "") + '"' + at + '>' + esc(p.lab) + '</div>';
  });
  return h + '</div>';
}
function cells(r, mark, from) {
  return r.slice(from).map(function (c, i) { return '<td' + (i === mark ? ' class="mk"' : '') + '>' + esc(c) + '</td>'; }).join("");
}
function picture(p) {
  var h = "";
  if (p.type === "choice") {
    h = '<table class="t"><thead><tr><th></th>' + p.cols.map(function (c, i) {
      return '<th' + (i === p.mark ? ' class="mk"' : '') + '>' + esc(c) + (i === p.mark ? '<span class="mk-label">Recommended</span>' : '') + '</th>';
    }).join("") + '</tr></thead><tbody>' +
      (p.desc ? '<tr class="desc"><th scope="row">What it is</th>' + cells(p.desc, p.mark, 0) + '</tr>' : '') +
      p.rows.map(function (r) { return '<tr><th scope="row">' + esc(r[0]) + '</th>' + cells(r, p.mark, 1) + '</tr>'; }).join("") + '</tbody></table>';
  } else if (p.type === "rows") {
    h = '<table class="t wide"><thead><tr>' + p.head.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join("") + '</tr></thead><tbody>' +
      p.rows.map(function (r, i) { return '<tr' + (i === p.mark ? ' class="mkrow"' : '') + '><th scope="row">' + esc(r[0]) + '</th>' + cells(r, -1, 1) + '</tr>'; }).join("") + '</tbody></table>';
  } else if (p.type === "timeline") {
    h = tl(p.points, (p.bands || []).map(function (b) { return '<div class="band" style="left:' + (b[0] * 100) + '%;width:' + (b[1] * 100) + '%"></div>'; }).join(""));
  } else if (p.type === "bars") {
    h = '<div class="bars">' + p.rows.map(function (r) {
      var f = Math.max(0, Math.min(1, Number(r[2]) || 0));
      return '<div class="brow' + (r[3] ? " loud" : "") + '"><div class="bl"><span>' + esc(r[0]) + '</span><b>' + esc(r[1]) + '</b></div><div class="track"><div class="fill" style="width:' + Math.max(f * 100, 1.5) + '%"></div></div></div>';
    }).join("") + '</div>';
  } else if (p.type === "facts") {
    h = '<div>' + p.rows.map(function (r) {
      return '<div class="fact' + (r[3] ? " loud" : "") + '"><span class="v">' + esc(r[0]) + '</span><span>' + esc(r[1]) + '</span><span class="grade">' + esc(r[2]) + '</span></div>';
    }).join("") + '</div>';
  } else if (p.type === "list") {
    h = '<ol class="plist">' + p.items.map(function (it) { it = [].concat(it); return '<li' + (it[1] ? ' class="loud"' : '') + '>' + esc(it[0]) + '</li>'; }).join("") + '</ol>';
  } else if (p.type === "status") {
    h = '<p class="stc"><b>' + esc(p.count[0]) + '</b>' + esc(p.count[1]) + '</p>' + p.rows.map(function (r) {
      return '<div class="srow"><span class="st">Open</span><span>' + esc(r[0]) + '</span><span class="rec">' + esc(r[1]) + '</span></div>';
    }).join("");
  } else if (p.type === "pair") {
    h = '<div class="pair">' + p.items.map(function (it, i) {
      return '<div class="side-box' + (i === p.mark ? " mk" : "") + '"><h4>' + esc(it.h) + '</h4>' + [].concat(it.p).map(function (x) { return '<p>' + esc(x) + '</p>'; }).join("") + '</div>';
    }).join("") + '</div>';
  } else if (p.type === "score") {
    h = '<div class="score">' + p.cells.map(function (c) { return '<div' + (c[2] ? ' class="good"' : '') + '><b>' + esc(c[0]) + '</b><span>' + esc(c[1]) + '</span></div>'; }).join("") + '</div>';
  } else if (p.type === "stats") {
    h = '<div class="stats">' + p.items.map(function (it) { return '<div class="stat' + (it[2] ? " loud" : "") + '"><b>' + esc(it[0]) + '</b><span>' + esc(it[1]) + '</span></div>'; }).join("") + '</div>';
  } else if (p.type === "flow") {
    h = '<ol class="flow">' + p.steps.map(function (s, i) { return '<li' + (i === p.mark ? ' class="loud"' : '') + '><b>' + esc(s.h) + '</b><span>' + esc(s.p) + '</span></li>'; }).join("") + '</ol>';
  }
  return '<div class="pic">' + h + (p.cap ? '<p class="cap">' + esc(p.cap) + '</p>' : '') + '</div>';
}
/* A picture the model got wrong is left out rather than breaking the answer. */
function safePicture(p) { if (!p || !DRAWN[p.type]) return ""; try { return picture(p); } catch (e) { return ""; } }

/* ----------------------------------------------------------------- pieces - */
function tagHtml(t) { var T = D.tags || {}; return t && T[t] ? '<span class="tag ' + esc(t) + '">' + esc(T[t][0]) + '</span>' : ''; }
function pageRef(p) {
  var P = D.pages || {};
  if (!p) return null;
  if (P[p]) return { id: p, num: P[p] };
  var want = String(p).replace(/\D/g, "");
  for (var id in P) if (P[id] === want || P[id] === ("0" + want).slice(-2)) return { id: id, num: P[id] };
  return null;
}
function card(k, lineId, src) {
  var n = node(k), d = ' data-node="' + esc(k) + '" data-line="' + lineId + '" data-src="' + esc(src) + '"';
  return '<div class="card">' + (tagHtml(n.tag) || '<span class="tag">Deeper</span>') +
    '<button type="button" class="txt" data-act="below"' + d + '>' + esc(n.short || n.s) + '</button>' +
    '<div class="acts"><button type="button" class="act" data-act="below"' + d + '>↓ Below</button>' +
    '<button type="button" class="act side" data-act="side"' + d + '>→ Side</button></div></div>';
}
function options(id) {
  var kids = ((node(id) || {}).kids || []).filter(function (k) { return D.findings[k] && !S.where[k]; });
  var extra = [];
  if (kids.length < 3) {
    extra = D.order.filter(function (k) { return k !== ROOT && k !== id && !S.where[k] && kids.indexOf(k) < 0 && !S.seen[k] && S.seen[PARENT[k]]; })
      .sort(function (a, b) { return weight(a) - weight(b) || D.order.indexOf(a) - D.order.indexOf(b); })
      .slice(0, 3 - kids.length);
  }
  return { kids: kids, extra: extra };
}
function fork(id, L) {
  var o = options(id);
  if (!o.kids.length && !o.extra.length) {
    return seenCount() === D.order.length ? '<p class="done">✓ You have seen all ' + D.order.length + ' findings on this page.</p>' : '';
  }
  return '<div class="fork"><div class="fork-h"><b>' + (o.kids.length ? 'What matters most next' : 'Not seen yet, and worth it') + '</b>' +
    '<span>↓ Below adds it under this answer · → Side opens a new branch</span></div><div class="cards">' +
    o.kids.concat(o.extra).map(function (k) { return card(k, L.id, id); }).join("") + '</div></div>';
}
function opened(id, L) {
  var h = "";
  Object.keys(S.from).forEach(function (k) {
    var f = S.from[k];
    if (f.line !== L.id || f.node !== id || !S.where[k]) return;
    h += '<button type="button" class="chip" data-jump="' + esc(k) + '">' +
      (f.how === "side" ? '<span class="ln">' + f.to + '</span>→ ' : '↓ ') + esc(node(k).label) + '</button>';
  });
  return h ? '<div class="opened">' + h + '</div>' : '';
}
function block(id, L, isLast) {
  var n = node(id), h = '<article class="block" data-node="' + esc(id) + '">';
  if (n.q) h += '<p class="question"><b>The question</b>' + esc(n.q) + '</p>';
  if (n.ask) h += '<p class="question"><b>You asked</b>' + esc(n.ask) + '</p>';
  h += '<p class="kicker"><span>' + esc(n.label) + '</span>' + tagHtml(n.tag) + '</p>';
  if (n.pending) return h + '<p class="wait"><i></i>Reading the page and its notes…</p></article>';
  if (n.error) return h + '<p class="err">' + esc(n.error) + '</p></article>';
  h += '<p class="sentence">' + esc(n.s) + '</p>' + safePicture(n.pic);
  var ref = pageRef(n.page);
  h += '<p class="meta"><span>' + (n.sure ? 'How sure: ' + esc(n.sure) : '') + '</span>' +
    (ref ? '<button type="button" data-goto="' + esc(ref.id) + '">Where it says this: page ' + esc(ref.num) + ' ↗</button>' : '') + '</p>';
  h += opened(id, L);
  if (isLast || S.open[id]) h += fork(id, L);
  else {
    var left = options(id).kids.length;
    if (left) h += '<button type="button" class="more" data-more="' + esc(id) + '">+ ' + left + ' more from here</button>';
  }
  return h + '</article>';
}
function crumbs(L) {
  var c = chain(L);
  return c.map(function (x, i) {
    if (i === c.length - 1) return '<span class="here">' + esc(node(x.node).label) + '</span>';
    var other = x.line !== L.id;
    return '<button type="button" class="crumb' + (other ? " other" : "") + '" data-jump="' + esc(x.node) + '">' +
      (other ? '<span class="ln">' + x.line + '</span>' : '') + esc(node(x.node).label) + '</button><span class="sep">›</span>';
  }).join("");
}
function column(L) {
  var hasKids = S.lines.some(function (x) { return x.origin && x.origin.line === L.id; });
  var title = L.origin ? 'Branch ' + L.id + ' · from ' + esc(node(L.origin.node).label) : 'Main line';
  return '<section class="col' + (L.id === S.focus ? " on" : "") + '" data-line="' + L.id + '">' +
    '<div class="col-head"><div class="col-title"><span>' + title + '</span>' +
    (L.origin && !hasKids ? '<button type="button" class="x" data-close="' + L.id + '" aria-label="Close branch ' + L.id + '">×</button>' : '') +
    '</div><nav class="crumbs" aria-label="The way back">' + crumbs(L) + '</nav></div>' +
    '<div class="col-body">' + L.blocks.map(function (k, i) { return block(k, L, i === L.blocks.length - 1); }).join("") + '</div></section>';
}

/* ----------------------------------------------------------------- render - */
var el = {};
function render(target) {
  el.tabs.innerHTML = S.lines.map(function (L) {
    return '<button type="button" class="tab' + (L.id === S.focus ? " on" : "") + '" data-tab="' + L.id + '"><span class="n">' + L.id + '</span>' +
      '<span class="t">' + esc(node(L.blocks[0]).label) + '</span><span class="c">' + L.blocks.length + '</span></button>';
  }).join("");
  var flagged = D.order.filter(function (k) { return !S.seen[k] && D.findings[k].tag; }).length;
  el.seen.innerHTML = 'Seen <b>' + seenCount() + '</b> of ' + D.order.length + (flagged ? ' · <span class="need">' + flagged + ' flagged</span>' : '');
  el.ws.innerHTML = S.lines.map(column).join("") + '<div class="ghost">→ Side on any finding opens it here, as a new branch beside this one.</div>';
  S.lines.forEach(function (L) { var b = el.ws.querySelector('.col[data-line="' + L.id + '"] .col-body'); if (b) b.scrollTop = L.scroll || 0; });
  var F = line(S.focus);
  el.asking.innerHTML = 'Asking in <b>' + esc(lineName(F)) + '</b> · ' + esc(node(F.blocks[F.blocks.length - 1]).label);
  if (!el.pop.hidden) drawPop();
  save();
  if (target) reveal(target);
}
function reveal(t) {
  var col = el.ws.querySelector('.col[data-line="' + t.line + '"]');
  if (!col) return;
  var left = col.offsetLeft - 16, right = col.offsetLeft + col.offsetWidth + 16 - el.ws.clientWidth;
  if (el.ws.scrollLeft > left) el.ws.scrollLeft = Math.max(0, left);
  else if (el.ws.scrollLeft < right) el.ws.scrollLeft = right;
  var tab = el.tabs.querySelector(".tab.on");
  if (tab) tab.scrollIntoView({ block: "nearest", inline: "nearest" });
  if (!t.node) return;
  var body = col.querySelector(".col-body"), b = col.querySelector('.block[data-node="' + t.node + '"]');
  if (!b) return;
  requestAnimationFrame(function () { body.scrollTo({ top: Math.max(0, b.offsetTop - 6), behavior: "smooth" }); });
  if (t.flash) b.classList.add("flash");
}
function drawPop() {
  var F = line(S.focus), src = F.blocks[F.blocks.length - 1];
  var rest = D.order.filter(function (k) { return !S.seen[k]; })
    .sort(function (a, b) { return weight(a) - weight(b) || D.order.indexOf(a) - D.order.indexOf(b); });
  el.pop.innerHTML = '<h3>Not seen yet: ' + rest.length + ' of ' + D.order.length + '</h3>' +
    '<p>Flagged ones first: your decisions, risks, and places where sources differ. ↓ Below adds to ' + esc(lineName(F)) + '; → Side opens a new branch.</p>' +
    (rest.length ? rest.map(function (k) { return card(k, F.id, src); }).join("") : '<p>Nothing left. You have seen every finding on this page.</p>');
}
function togglePop(show) {
  el.pop.hidden = !show;
  el.seen.setAttribute("aria-expanded", show ? "true" : "false");
  if (show) drawPop();
}

/* ------------------------------------------------------------ questions - */
function pageText() {
  var M = document.querySelector("main") || document.querySelector("article") || document.body;
  var c = M.cloneNode(true);
  ["#askai-root", "#askai-dd"].forEach(function (s) { var x = c.querySelector(s); if (x) x.remove(); });
  return c.innerText || c.textContent || "";
}
function parseAnswer(t) {
  var a = t.indexOf("{"), b = t.lastIndexOf("}");
  if (a >= 0 && b > a) {
    try { var o = JSON.parse(t.slice(a, b + 1)); if (o && o.sentence) return o; } catch (e) {}
  }
  return { sentence: t.replace(/\s+/g, " ").trim().slice(0, 700) || "No answer came back.", picture: null };
}
function setBusy() {
  el.sends.forEach(function (b) { b.disabled = busy; });
}
function askNow(side) {
  var q = el.input.value.trim();
  if (!q || busy) return;
  busy = true; setBusy();
  el.input.value = "";
  var F = line(S.focus), src = F.blocks[F.blocks.length - 1], id = "q" + (++S.qn), acc = "", err = null;
  S.extra[id] = { label: "Your question", ask: q, pending: true };
  (side ? openSide : openBelow)(F.id, src, id);
  fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc: DOC, threadId: S.thread, selectedText: "Drill-down: " + q, context: pageText(), question: q + FORMAT })
  }).then(function (res) {
    if (!res.ok || !res.body) throw new Error("The AI answered with an error (" + res.status + "). Ask again.");
    var reader = res.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) return;
        buf += dec.decode(r.value, { stream: true });
        var parts = buf.split("\n\n");
        buf = parts.pop();
        parts.forEach(function (chunk) {
          var l = chunk.split("\n").filter(function (x) { return x.indexOf("data:") === 0; })[0];
          if (!l) return;
          var ev; try { ev = JSON.parse(l.slice(5).trim()); } catch (e) { return; }
          if (ev.type === "thread") S.thread = String(ev.threadId);
          else if (ev.type === "text") acc += ev.text;
          else if (ev.type === "error") err = ev.message || "The AI returned an error.";
        });
        return pump();
      });
    }
    return pump();
  }).then(function () { finish(id, err ? null : acc, err); },
          function (e) { finish(id, null, (e && e.message && e.message.indexOf("The AI") === 0) ? e.message : "The AI could not be reached. Check the connection and ask again."); });
}
function finish(id, text, err) {
  var n = S.extra[id];
  busy = false; setBusy();
  if (!n) return;
  n.pending = false;
  if (err) n.error = err;
  else {
    var a = parseAnswer(text || "");
    n.s = String(a.sentence);
    if (a.label) n.label = String(a.label).slice(0, 60);
    n.pic = a.picture && ASKED[a.picture.type] ? a.picture : null;
    if (n.pic && a.caption) n.pic.cap = String(a.caption);
    n.sure = a.sure ? String(a.sure) : "";
    n.page = a.page ? String(a.page) : "";
  }
  if (S.where[id]) render({ line: S.where[id], node: id });
}

/* ------------------------------------------------------------ the mode - */
function pageTheme() {
  var t = document.documentElement.getAttribute("data-theme");
  if (t === "dark" || t === "light") return t;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
/* In place, not as a new step in the tab's history: this page is in Rouh's
   frame, and a step a frame leaves behind is one Back lands on after the frame
   is gone - nothing at all in Chromium, a blank white page in Safari
   (`frameWrite` in app.js, fr_08e89370f7c7). */
function goTo(id) {
  closeMode();
  location.replace("#" + id);
  try { window.dispatchEvent(new PopStateEvent("popstate", { state: { p: id } })); } catch (e) {}
  try { window.dispatchEvent(new HashChangeEvent("hashchange")); } catch (e) {}
}
function build() {
  host = document.createElement("div");
  host.id = "askai-dd";
  host.hidden = true;
  host.setAttribute("role", "region");
  host.setAttribute("aria-label", "Drill-down view of this page");
  sh = host.attachShadow({ mode: "open" });
  sh.innerHTML = '<style>' + CSS + '</style><div class="app">' +
    '<header class="topbar"><nav class="tabs" aria-label="Branches"></nav><div class="tools">' +
    '<button type="button" class="btn seen" aria-expanded="false"></button><button type="button" class="btn reset">Start over</button></div></header>' +
    '<div class="ws"></div>' +
    '<div class="dock"><span class="asking"></span>' +
    '<input class="ask" id="askai-dd-q" type="text" enterkeyhint="send" autocomplete="off" placeholder="Ask about this page" aria-label="Ask a question about this page">' +
    '<button type="button" class="send" data-send="below">Ask</button>' +
    '<button type="button" class="send side" data-send="side" title="Answer it as a new branch">→ Side</button></div>' +
    '<div class="pop" hidden></div></div>';
  document.body.appendChild(host);
  el = { tabs: sh.querySelector(".tabs"), ws: sh.querySelector(".ws"), seen: sh.querySelector(".seen"),
         pop: sh.querySelector(".pop"), asking: sh.querySelector(".asking"), input: sh.querySelector(".ask"),
         sends: Array.prototype.slice.call(sh.querySelectorAll(".send")) };

  sh.addEventListener("click", function (e) {
    var t = e.target;
    var a = t.closest("[data-act]");
    if (a) {
      var side = a.getAttribute("data-act") === "side" || (a.classList.contains("txt") && (e.metaKey || e.ctrlKey || e.shiftKey));
      if (el.pop.contains(a)) togglePop(false);
      (side ? openSide : openBelow)(+a.getAttribute("data-line"), a.getAttribute("data-src"), a.getAttribute("data-node"));
      return;
    }
    var j = t.closest("[data-jump]");
    if (j) { var k = j.getAttribute("data-jump"); if (S.where[k]) jump(S.where[k], k, true); return; }
    var tab = t.closest("[data-tab]");
    if (tab) { jump(+tab.getAttribute("data-tab"), null, false); return; }
    var m = t.closest("[data-more]");
    if (m) { S.open[m.getAttribute("data-more")] = true; S.focus = +m.closest(".col").getAttribute("data-line"); render(); return; }
    var c = t.closest("[data-close]");
    if (c) { closeLine(+c.getAttribute("data-close")); return; }
    var g = t.closest("[data-goto]");
    if (g) { goTo(g.getAttribute("data-goto")); return; }
    var s = t.closest("[data-send]");
    if (s) { askNow(s.getAttribute("data-send") === "side"); return; }
    if (t.closest(".seen")) { togglePop(el.pop.hidden); return; }
    if (t.closest(".reset")) { S = fresh(); togglePop(false); el.ws.scrollLeft = 0; render({ line: 1, node: ROOT }); return; }
    if (!el.pop.hidden && !el.pop.contains(t)) togglePop(false);
    var col = t.closest(".col");
    if (col && +col.getAttribute("data-line") !== S.focus) { S.focus = +col.getAttribute("data-line"); render(); }
  });
  el.ws.addEventListener("scroll", function (e) {
    var b = e.target;
    if (!b.classList || !b.classList.contains("col-body")) return;
    var L = line(+b.parentNode.getAttribute("data-line"));
    if (L) { L.scroll = b.scrollTop; save(); }
  }, true);
  el.input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); askNow(false); } });
  sh.addEventListener("keydown", function (e) { if (e.key === "Escape" && !el.pop.hidden) togglePop(false); });

  host.setAttribute("data-theme", pageTheme());
  new MutationObserver(function () { host.setAttribute("data-theme", pageTheme()); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", function () { host.setAttribute("data-theme", pageTheme()); });
  }
}
function setToggle(on) {
  toggle.classList.toggle("on", on);
  toggle.setAttribute("aria-pressed", on ? "true" : "false");
  toggle.innerHTML = on ? '<span aria-hidden="true">▤</span> Page view' : '<span aria-hidden="true">⇶</span> Drill down';
  toggle.title = on ? "Back to the page as written" : "Read this page by drilling down";
}
function mainEl() { var M = document.querySelector("main") || document.querySelector("article"); return M && M !== document.body ? M : null; }
function openMode() {
  if (!host) build();
  if (!S) S = restore();
  host.hidden = false;
  document.documentElement.classList.add("askai-dd-on");
  var M = mainEl(); if (M) M.setAttribute("inert", "");
  setToggle(true);
  store(KEY + ":open", "1");
  render(S.lines.length ? { line: S.focus } : null);
}
function closeMode() {
  if (host) host.hidden = true;
  document.documentElement.classList.remove("askai-dd-on");
  var M = mainEl(); if (M) M.removeAttribute("inert");
  setToggle(false);
  store(KEY + ":open", null);
}
function ready(d) {
  if (!d || !d.findings || !d.order || !d.order.length || !d.findings[d.order[0]]) return;
  D = d; ROOT = d.order[0]; PARENT = {};
  d.order.forEach(function (k) { (d.findings[k].kids || []).forEach(function (c) { PARENT[c] = k; }); });
  toggle = document.createElement("button");
  toggle.type = "button";
  toggle.id = "askai-dd-toggle";
  toggle.addEventListener("click", function () { if (host && !host.hidden) closeMode(); else openMode(); });
  (document.getElementById("askai-root") || document.body).appendChild(toggle);
  document.body.classList.add("askai-has-dd");
  setToggle(false);
  if (recall(KEY + ":open")) openMode();
}
if (FINDINGS) {
  fetch(FINDINGS, { cache: "no-cache", credentials: "same-origin" })
    .then(function (r) { if (!r.ok) throw new Error("no findings"); return r.json(); })
    .then(ready, function () {});
}
})();
