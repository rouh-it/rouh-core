/* The X-ray of a long report (rouh/xray.py).
 *
 * The report's argument as a numbered outline, over the report: one sentence
 * a point, opened for why, for its evidence and for where it is in the full
 * report, which the page scrolls to and lights. Put into the page by Rouh as it
 * is sent, with the X-ray itself in window.ROUH_XRAY; the page on disk is never
 * changed and nothing here changes the report either, beyond showing the part
 * of it a point is about.
 *
 * What keeps it honest is in this file as much as on the server: a quote is
 * found in the page's own words before it is drawn, and what is drawn is the
 * page's text at that place, not the X-ray's copy of it. A quote that is not
 * there is left out and counted. The sources beside a quote are the report's
 * own citation links around it, read out of the page.
 */
(function () {
'use strict';

if (window.__rouhXray) return;
window.__rouhXray = true;

var CFG = window.ROUH_XRAY;
if (!CFG || !CFG.xray || !CFG.xray.points || !CFG.xray.points.length) return;
var X = CFG.xray, KINDS = CFG.kinds || {}, STRENGTHS = CFG.strengths || {};

/* The name the lit passage is kept under (the CSS Custom Highlight API). */
var HL = 'rouh-xray';
/* Wider than this, the page moves over and stays beside the panel; narrower,
   the panel is closed to show the passage and a button brings it back. */
var SIDE_BY_SIDE = 980;
/* The fewest letters and digits a quote may have, as in xray.py. */
var QUOTE_MIN = 12;

var DOUBT = { caveat: 1, disagreement: 1, open: 1 };
var METER = { strong: 4, moderate: 3, mixed: 2, weak: 1 };

function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* --------------------------------------------------------------- numbers - */
var ALL = [];       /* every point, in reading order: {n, node, parent} */
var BY = {};        /* number -> that */
(function number(points, above, parent) {
  points.forEach(function (node, i) {
    var n = above ? above + '.' + (i + 1) : String(i + 1);
    var e = { n: n, node: node, parent: parent };
    ALL.push(e); BY[n] = e;
    number(node.points || [], n, e);
  });
})(X.points, '', null);

function isDoubt(node) { return !!DOUBT[node.kind] || node.strength === 'weak' || node.strength === 'mixed'; }

/* ---------------------------------------------------- the page's own words - */
/* Letters and digits, lower case, and nothing else: `key` in xray.py. Each is
   kept with the text node and offset it came from, so a place in the key is a
   place in the page. Everything in the body is read, whether or not the part
   of the report it is on is showing at the moment. */
var LETTER;
try { LETTER = new RegExp('[\\p{L}\\p{N}]', 'u'); } catch (e) { LETTER = /[A-Za-z0-9\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF]/; }
var IDX = null;
var host = null;

function readPage() {
  var keyParts = [], nodes = [], offs = [];
  var skip = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, TITLE: 1 };
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: function (n) {
      if (n.nodeType === 1) {
        if (skip[n.tagName] || n === host || n.id === 'askai-root' || n.id === 'askai-dd') return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_SKIP;
      }
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  var t;
  while ((t = walker.nextNode())) {
    var s = t.data;
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      if (!LETTER.test(ch)) continue;
      var low = ch.toLowerCase();
      for (var j = 0; j < low.length; j++) { keyParts.push(low.charAt(j)); nodes.push(t); offs.push(i); }
    }
  }
  IDX = { key: keyParts.join(''), nodes: nodes, offs: offs };
}

function xkey(text) {
  var out = '';
  var s = String(text || '');
  for (var i = 0; i < s.length; i++) { var ch = s.charAt(i); if (LETTER.test(ch)) out += ch.toLowerCase(); }
  return out;
}

var FOUND = {};
/* The place in the page a quote is at, as a Range, or null when it is not in
   the page. The first place, as `check` in xray.py says. */
function locate(quote) {
  if (!quote) return null;
  var was = FOUND[quote];
  if (was !== undefined) {
    if (!was || (document.contains(was.startContainer) && document.contains(was.endContainer))) return was;
    IDX = null;   /* the page drew itself again since: read it afresh */
  }
  if (!IDX) readPage();
  var k = xkey(quote), at = k.length >= QUOTE_MIN ? IDX.key.indexOf(k) : -1, range = null;
  if (at >= 0) {
    var end = at + k.length - 1;
    try {
      range = document.createRange();
      range.setStart(IDX.nodes[at], IDX.offs[at]);
      range.setEnd(IDX.nodes[end], IDX.offs[end] + 1);
    } catch (e) { range = null; }
  }
  FOUND[quote] = range;
  return range;
}

/* What the page says at a place, in its own words. */
function wordsAt(range) { return range.toString().replace(/\s+/g, ' ').trim(); }

/* ------------------------------------------------- the report's own sources - */
var BLOCKS = 'p,li,td,th,dd,dt,blockquote,figcaption,caption,h1,h2,h3,h4,h5,h6,summary,pre';
var NOTE_ID = /^(source|src|ref|cite|fn|note)/i;

function elementOf(n) { return n.nodeType === 1 ? n : n.parentElement; }

/* The sources the report cites around a passage: its footnote links into its
   own Sources list, and plain links to other sites, in the paragraph, item or
   cell the passage is in. Never anything the X-ray says. */
function citesAt(range) {
  var out = [], seen = {};
  var here = [], a = elementOf(range.startContainer), b = elementOf(range.endContainer);
  [a, b].forEach(function (el) {
    var block = el && el.closest(BLOCKS);
    if (block && here.indexOf(block) < 0) here.push(block);
  });
  var links = [];
  here.forEach(function (block) { links = links.concat([].slice.call(block.querySelectorAll('a[href]'))); });
  if (!here.length) {
    var box = elementOf(range.commonAncestorContainer);
    links = [].slice.call(box.querySelectorAll('a[href]')).filter(function (l) { return range.intersectsNode(l); });
  }
  links.forEach(function (l) {
    var raw = l.getAttribute('href') || '';
    if (raw.charAt(0) === '#') {
      var id = raw.slice(1), entry = null;
      try { id = decodeURIComponent(id); } catch (e) {}
      if (!NOTE_ID.test(id)) return;
      entry = document.getElementById(id);
      if (!entry || seen['#' + id]) return;
      seen['#' + id] = 1;
      var out1 = entry.querySelector('a[href^="http"]');
      var title = ((out1 && out1.textContent) || entry.textContent || '').replace(/\s+/g, ' ').trim();
      out.push({ k: (l.textContent || '').replace(/\s+/g, '').slice(0, 6), title: title.slice(0, 150),
                 href: out1 ? out1.href : '', entry: entry, id: '#' + id });
    } else if (/^https?:/i.test(raw)) {
      /* Written out whole, to another site: a link to another page of the
         workspace is not a source. */
      try { if (new URL(l.href).origin === new URL(document.baseURI).origin) return; } catch (e) { return; }
      if (seen[l.href]) return;
      seen[l.href] = 1;
      out.push({ k: '', title: (l.textContent || l.href).replace(/\s+/g, ' ').trim().slice(0, 150), href: l.href, id: l.href });
    }
  });
  return out;
}

/* ------------------------------------------- showing a passage in the report - */
function showing(el) {
  if (!el || !el.getClientRects().length) return false;
  try { return getComputedStyle(el).visibility !== 'hidden'; } catch (e) { return true; }
}

/* A control is pressed the way the reader would press it, with two things
   held back: a step in the frame's history, which Back would later land on
   once the frame is gone (`frameWrite` in app.js), and a link's own default,
   which inside Rouh's frame would load the page again rather than switch it. */
function press(ctl) {
  var push = history.pushState;
  function stop(e) { var t = e.target; if (t && t.closest && t.closest('a[href]')) e.preventDefault(); }
  try { history.pushState = function (s, t, u) { try { return history.replaceState(s, t, u); } catch (e) {} }; } catch (e) {}
  window.addEventListener('click', stop, false);
  try { ctl.click(); } catch (e) {}
  window.removeEventListener('click', stop, false);
  try { history.pushState = push; } catch (e) {}
}

function quoted(v) { return '"' + String(v).replace(/["\\]/g, '\\$&') + '"'; }

/* A report built with the workspace's explainer skill shows one of its pages at
   a time, and a passage may be on one that is not showing. Each report does
   its switching its own way, so the control that opens the part holding the
   passage is looked for the ways they do it: a nav link to its id, or a
   button naming it in data-page, data-p, data-go, data-tab or aria-controls. */
function openTo(el) {
  for (var p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS' && !p.open) p.open = true;
  if (showing(el)) return true;
  var owners = [];
  for (p = el; p && p !== document.body; p = p.parentElement) if (p.id) owners.push(p);
  for (var i = 0; i < owners.length && !showing(el); i++) {
    var A = owners[i];
    var names = [A.id], bare = A.id.replace(/^(page|p|tab|sec|section|panel|view)[-_]/i, '');
    if (bare && bare !== A.id) names.push(bare);
    var ctl = null;
    for (var j = 0; j < names.length && !ctl; j++) {
      var n = quoted(names[j]);
      var sels = ['a[href=' + quoted('#' + names[j]) + ']', '[data-page=' + n + ']', '[data-p=' + n + ']',
                  '[data-go=' + n + ']', '[data-tab=' + n + ']', '[data-target=' + n + ']',
                  '[data-target=' + quoted('#' + names[j]) + ']', '[data-section=' + n + ']',
                  '[aria-controls=' + quoted(A.id) + ']'];
      for (var s = 0; s < sels.length && !ctl; s++) {
        var found = [].slice.call(document.querySelectorAll(sels[s])).filter(function (c) {
          return !A.contains(c) && !(host && host.contains(c));
        });
        ctl = found[0] || null;
      }
    }
    if (ctl) press(ctl);
  }
  return showing(el);
}

var litTimer = null, litEl = null;
function light(range, el) {
  try {
    if (window.CSS && CSS.highlights && window.Highlight) CSS.highlights.set(HL, new Highlight(range));
  } catch (e) {}
  if (litEl) litEl.classList.remove('rouh-xray-lit');
  litEl = el;
  el.classList.add('rouh-xray-lit');
  clearTimeout(litTimer);
  litTimer = setTimeout(function () { if (litEl) litEl.classList.remove('rouh-xray-lit'); }, 2600);
}

/* The passage for a quote, opened, scrolled to, lit and given the keyboard.
   False when the page could not show it. */
function goTo(range) {
  var el = elementOf(range.startContainer);
  var block = el.closest(BLOCKS) || el;
  if (!openTo(block)) return false;
  requestAnimationFrame(function () {
    var tall = block.getBoundingClientRect().height > window.innerHeight * 0.6;
    try { block.scrollIntoView({ block: tall ? 'start' : 'center' }); } catch (e) { block.scrollIntoView(); }
    if (tall) {
      var r = range.getBoundingClientRect();
      if (r.top > window.innerHeight * 0.7) window.scrollBy(0, r.top - window.innerHeight * 0.3);
    }
    light(range, block);
    if (!block.hasAttribute('tabindex') && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(block.tagName)) {
      block.setAttribute('tabindex', '-1');
    }
    try { block.focus({ preventScroll: true }); } catch (e) {}
  });
  return true;
}

/* ------------------------------------------------------------ drawing it - */
var ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round"><path d="M4 5h2M9 5h11M6 10h2M11 10h9M6 15h2M11 15h9M4 20h2M9 20h11"/></svg>';
var CHEV = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';

var sh = null, el = {}, open = false, backTo = '', missing = 0, drawn = false;
var SRC = {};   /* number -> the sources around its passage and evidence */

function doubtsUnder(e) {
  var c = { caveat: 0, disagreement: 0, open: 0 };
  (function walk(node) {
    if (DOUBT[node.kind]) c[node.kind] += 1;
    (node.points || []).forEach(walk);
  })(e.node);
  return c;
}

function meter(strength) {
  var on = METER[strength] || 0;
  if (!on) return '<span>Not rated</span>';
  var cells = '';
  for (var i = 1; i <= 4; i++) cells += '<i' + (i <= on ? ' class="on"' : '') + '></i>';
  return '<span class="meter ' + esc(strength) + '" aria-hidden="true">' + cells + '</span>' +
    '<span>' + esc(STRENGTHS[strength] || strength) + '</span>';
}

function sourcesOf(n) {
  if (SRC[n]) return SRC[n];
  var e = BY[n], seen = {}, list = [];
  [e.node.quote].concat(e.node.evidence || []).forEach(function (q) {
    var r = locate(q);
    if (!r) return;
    citesAt(r).forEach(function (c) { if (!seen[c.id]) { seen[c.id] = 1; list.push(c); } });
  });
  SRC[n] = list;
  return list;
}

function tagsFor(e) {
  var node = e.node, h = '';
  if (DOUBT[node.kind]) h += '<span class="tag ' + esc(node.kind) + '">' + esc(KINDS[node.kind]) + '</span>';
  if (node.strength) h += '<span class="tag">' + esc(STRENGTHS[node.strength] || node.strength) + '</span>';
  var s = sourcesOf(e.n).length;
  if (s) h += '<span class="tag src">' + s + (s === 1 ? ' source' : ' sources') + '</span>';
  return h ? '<div class="tags">' + h + '</div>' : '';
}

function citesHtml(list) {
  if (!list.length) return '';
  return '<div class="cites">' + list.map(function (c, i) {
    var label = (c.k ? '<span class="k">[' + esc(c.k) + ']</span>' : '') + esc(c.title || 'Source');
    if (c.href) return '<a class="cite" href="' + esc(c.href) + '" data-out="1" target="_blank" rel="noopener noreferrer">' + label + '</a>';
    return '<button type="button" class="cite" data-entry="' + esc(c.id) + '">' + label + '</button>';
  }).join('') + '</div>';
}

/* One point: its claim as the button that opens it, then what it holds. */
function nodeHtml(e) {
  var node = e.node, id = 'xr-' + e.n.replace(/\./g, '-');
  var h = '<li class="node" id="' + id + '" data-n="' + esc(e.n) + '">' +
    '<button type="button" class="row" aria-expanded="false" aria-controls="' + id + '-d">' +
    '<span class="num">' + esc(e.n) + '</span><span class="txt">' + esc(node.claim) + '</span>' + CHEV + '</button>' +
    tagsFor(e) +
    '<div class="detail" id="' + id + '-d" hidden>';
  if (node.why) h += '<p class="why"><b>Why</b>' + esc(node.why) + '</p>';
  var ev = [];
  (node.evidence || []).forEach(function (q, i) {
    var r = locate(q);
    if (!r) { missing += 1; return; }
    ev.push('<li><blockquote>' + esc(wordsAt(r)) + '</blockquote>' + citesHtml(citesAt(r)) +
      '<button type="button" class="go" data-go="ev" data-n="' + esc(e.n) + '" data-i="' + i + '">Show it in the report →</button></li>');
  });
  if (ev.length) h += '<div class="ev"><h4>Evidence, in the report\'s words</h4><ul>' + ev.join('') + '</ul></div>';
  if (locate(node.quote)) {
    h += '<button type="button" class="jump" data-go="node" data-n="' + esc(e.n) + '">Read ' + esc(e.n) + ' in the full report →</button>';
  } else {
    missing += 1;
    h += '<p class="none">The passage this point stands for could not be found in the report.</p>';
  }
  h += '<p class="said" role="status" hidden></p>';
  if (node.points && node.points.length) {
    h += '<ol class="kids">' + node.points.map(function (c, i) { return nodeHtml(BY[e.n + '.' + (i + 1)]); }).join('') + '</ol>';
  }
  return h + '</div></li>';
}

function mapHtml() {
  var tops = ALL.filter(function (e) { return !e.parent; });
  return '<section class="map" aria-labelledby="xr-map-h"><h3 id="xr-map-h">How the argument stands</h3>' +
    '<p class="legend">Each branch of the answer, with how strongly the report\'s evidence backs it and the doubts under it. Press one to open it.</p>' +
    '<ol>' + tops.map(function (e) {
      var node = e.node, d = doubtsUnder(e), s = sourcesOf(e.n).length, facts = meter(node.strength);
      if (s) facts += '<span>' + s + (s === 1 ? ' source' : ' sources') + '</span>';
      if (d.caveat) facts += '<span class="doubt caveat"><span aria-hidden="true">⚠ </span>' + d.caveat + (d.caveat === 1 ? ' caveat' : ' caveats') + '</span>';
      if (d.disagreement) facts += '<span class="doubt disagreement"><span aria-hidden="true">⇄ </span>' + d.disagreement + (d.disagreement === 1 ? ' disagreement' : ' disagreements') + '</span>';
      if (d.open) facts += '<span class="doubt open"><span aria-hidden="true">? </span>' + d.open + ' not known</span>';
      return '<li><button type="button" class="branch" data-to="' + esc(e.n) + '">' +
        '<span class="num">' + esc(e.n) + '</span><span class="lbl">' + esc(node.label || node.claim) + '</span>' +
        '<span class="facts">' + facts + '</span></button></li>';
    }).join('') + '</ol></section>';
}

function doubtsHtml(list) {
  return '<p class="intro">What the report is not sure of: its caveats, where its sources disagree, what it does not know, and the points its evidence backs only weakly or in part.</p>' +
    '<ol class="doubts">' + list.map(function (e) {
      return '<li><button type="button" class="row" data-to="' + esc(e.n) + '"><span class="num">' + esc(e.n) + '</span>' +
        '<span class="txt">' + esc(e.node.claim) + '</span>' + CHEV + '</button>' + tagsFor(e) + '</li>';
    }).join('') + '</ol>';
}

function draw() {
  if (drawn) return;
  drawn = true;
  missing = 0;
  var tops = X.points.length, doubts = ALL.filter(function (e) { return isDoubt(e.node); });
  var a = X.answer || {}, h = '';
  h += '<section class="answer" aria-labelledby="xr-ans-h"><span class="eyebrow" id="xr-ans-h">The answer, in one sentence</span>' +
    '<p class="claim">' + esc(a.claim) + '</p>';
  if (a.quote && locate(a.quote)) h += '<button type="button" class="go" data-go="answer">Read it in the report →</button>';
  h += '<p class="said" role="status" hidden></p></section>';
  h += mapHtml();
  if (X.figure && locate(X.figure.quote)) {
    h += '<section class="figure" aria-labelledby="xr-fig-h"><span class="eyebrow" id="xr-fig-h">The report\'s own picture of it</span>' +
      (X.figure.why ? '<p>' + esc(X.figure.why) + '</p>' : '') +
      '<button type="button" class="go" data-go="figure">Show it in the report →</button><p class="said" role="status" hidden></p></section>';
  }
  h += '<div class="tools"><h3 id="xr-tree-h">The argument, point by point</h3>' +
    '<button type="button" class="small" data-all="open">Open all</button>' +
    '<button type="button" class="small" data-all="close">Close all</button></div>' +
    '<ol class="tree" aria-labelledby="xr-tree-h">' + X.points.map(function (p, i) { return nodeHtml(BY[String(i + 1)]); }).join('') + '</ol>';
  var foot = '<p>Written from the report under it. Every quote shown is the report\'s own words, found on this page, with the sources the report gives beside them. How strong the evidence is was judged by whoever wrote the X-ray.</p>';
  if (missing) foot += '<p>' + missing + (missing === 1 ? ' quote in this X-ray is' : ' quotes in this X-ray are') + ' not in the report, so ' + (missing === 1 ? 'it is' : 'they are') + ' left out.</p>';
  el.outline.innerHTML = h + '<div class="foot">' + foot + '</div>';
  el.doubts.innerHTML = doubtsHtml(doubts);
  el.doubtCount.textContent = String(doubts.length);
  el.doubtTab.hidden = !doubts.length;
}

/* ------------------------------------------------------- opening, closing - */
function wide() { return window.innerWidth >= SIDE_BY_SIDE; }

function setOpen(on, keepFocus) {
  open = on;
  if (on) draw();
  el.panel.hidden = !on;
  el.launch.setAttribute('aria-expanded', on ? 'true' : 'false');
  el.launch.hidden = on;
  el.panel.setAttribute('aria-modal', wide() ? 'false' : 'true');
  document.documentElement.classList.toggle('rouh-xray-push', on && wide());
  if (on) {
    setBack('');
    if (!keepFocus) try { el.title.focus(); } catch (e) {}
  } else if (!keepFocus) {
    try { el.launch.focus(); } catch (e) {}
  }
}

/* After a jump on a narrow screen the panel is out of the way, and the button
   that opens it says where it will take the reader back to. */
function setBack(n) {
  backTo = n;
  el.launch.classList.toggle('back', !!n);
  el.launchText.textContent = n ? 'Back to ' + n : 'X-ray';
  el.launchCount.textContent = n ? '' : '· ' + X.points.length + ' points';
  el.launch.setAttribute('aria-label', n ? (BY[n] ? 'Back to point ' + n + ' in the X-ray' : 'Back to the X-ray')
    : 'X-ray: this report\'s argument in ' + X.points.length + ' numbered points');
}

function tab(which) {
  var doubts = which === 'doubts';
  el.outlineTab.setAttribute('aria-selected', doubts ? 'false' : 'true');
  el.doubtTab.setAttribute('aria-selected', doubts ? 'true' : 'false');
  el.outlineTab.tabIndex = doubts ? -1 : 0;
  el.doubtTab.tabIndex = doubts ? 0 : -1;
  el.outline.hidden = doubts;
  el.doubts.hidden = !doubts;
  el.body.scrollTop = 0;
}

function expand(li, on) {
  var row = li.querySelector(':scope > .row'), d = li.querySelector(':scope > .detail');
  if (!row || !d) return;
  row.setAttribute('aria-expanded', on ? 'true' : 'false');
  d.hidden = !on;
}

/* A point in the outline, opened with everything above it, scrolled to, and
   given the keyboard. */
function reveal(n) {
  tab('outline');
  var li = sh.getElementById('xr-' + n.replace(/\./g, '-'));
  if (!li) return;
  var parts = n.split('.');
  for (var i = 1; i <= parts.length; i++) {
    var up = sh.getElementById('xr-' + parts.slice(0, i).join('-'));
    if (up) expand(up, true);
  }
  var row = li.querySelector(':scope > .row');
  sh.querySelectorAll('.node.lit').forEach(function (x) { x.classList.remove('lit'); });
  li.classList.add('lit');
  setTimeout(function () { li.classList.remove('lit'); }, 2200);
  try { row.scrollIntoView({ block: 'center' }); } catch (e) {}
  try { row.focus({ preventScroll: true }); } catch (e) {}
}

function say(from, words) {
  var box = from.closest('.node, section');
  var said = box && box.querySelector('.said');
  if (!said) return;
  said.innerHTML = words;
  said.hidden = !words;
}

/* Into the report, from a point, a piece of evidence, the answer or the
   figure. */
function jump(btn) {
  var what = btn.getAttribute('data-go'), n = btn.getAttribute('data-n') || '', quote = '';
  if (what === 'answer') quote = X.answer.quote;
  else if (what === 'figure') quote = X.figure.quote;
  else if (what === 'node') quote = BY[n].node.quote;
  else if (what === 'ev') quote = BY[n].node.evidence[+btn.getAttribute('data-i')];
  var r = locate(quote);
  if (!r) return;
  var back = n || '';
  if (!goTo(r)) {
    say(btn, 'That part of the report could not be opened from here. It reads: <q>' + esc(wordsAt(r)) + '</q>');
    return;
  }
  say(btn, '');
  if (!wide()) {
    setOpen(false, true);
    setBack(back || 'the X-ray');
  }
}

function entry(btn) {
  var id = btn.getAttribute('data-entry') || '', target = null;
  try { target = document.getElementById(id.slice(1)); } catch (e) {}
  if (!target) return;
  var r = document.createRange();
  r.selectNodeContents(target);
  if (goTo(r) && !wide()) { setOpen(false, true); setBack('the X-ray'); }
}

/* ------------------------------------------------------------- the layer - */
function build() {
  host = document.createElement('div');
  host.id = 'rouh-xray';
  sh = host.attachShadow({ mode: 'open' });
  sh.innerHTML = '<style>' + (CFG.css || '') + '</style>' +
    '<button type="button" class="launch" aria-haspopup="dialog" aria-expanded="false" aria-controls="xr-panel">' +
    ICON + '<span class="lt">X-ray</span><span class="n"></span></button>' +
    '<div class="panel" id="xr-panel" role="dialog" aria-labelledby="xr-title" hidden>' +
    '<div class="head"><div class="t"><h2 id="xr-title" tabindex="-1"><span class="eb">X-ray</span>This report\'s argument, numbered</h2>' +
    '<p>Open a point for why, its evidence and where it is in the full report. The report itself is unchanged.</p></div>' +
    '<button type="button" class="close" aria-label="Close the X-ray">×</button></div>' +
    '<div class="tabs" role="tablist" aria-label="Ways to read it">' +
    '<button type="button" class="tab" role="tab" id="xr-tab-o" aria-controls="xr-o" aria-selected="true">Outline</button>' +
    '<button type="button" class="tab" role="tab" id="xr-tab-d" aria-controls="xr-d" aria-selected="false" tabindex="-1" hidden>' +
    'Doubts <span class="c"></span></button></div>' +
    '<div class="body">' +
    '<div id="xr-o" role="tabpanel" aria-labelledby="xr-tab-o"></div>' +
    '<div id="xr-d" role="tabpanel" aria-labelledby="xr-tab-d" hidden></div>' +
    '</div></div>';
  document.body.appendChild(host);
  el = {
    launch: sh.querySelector('.launch'), launchText: sh.querySelector('.launch .lt'),
    launchCount: sh.querySelector('.launch .n'), panel: sh.querySelector('.panel'),
    title: sh.getElementById('xr-title'), body: sh.querySelector('.body'),
    outline: sh.getElementById('xr-o'), doubts: sh.getElementById('xr-d'),
    outlineTab: sh.getElementById('xr-tab-o'), doubtTab: sh.getElementById('xr-tab-d'),
    doubtCount: sh.querySelector('#xr-tab-d .c')
  };
  setBack('');

  /* The page's half: the lit passage and the room the panel takes. */
  var style = document.createElement('style');
  style.textContent =
    '::highlight(' + HL + '){background-color:rgba(250,204,21,.42)}' +
    '.rouh-xray-lit{outline:2px solid rgba(250,204,21,.85)!important;outline-offset:4px!important}' +
    'html.rouh-xray-push body{margin-right:min(460px,100vw)!important}' +
    '@media print{#rouh-xray{display:none!important}}';
  (document.head || document.documentElement).appendChild(style);

  el.launch.addEventListener('click', function () {
    var n = backTo;
    setOpen(true);
    if (n && BY[n]) reveal(n);
  });
  sh.querySelector('.close').addEventListener('click', function () { setOpen(false); });
  el.outlineTab.addEventListener('click', function () { tab('outline'); });
  el.doubtTab.addEventListener('click', function () { tab('doubts'); });
  sh.querySelector('.tabs').addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    if (el.doubtTab.hidden) return;
    e.preventDefault();
    var to = el.outlineTab.getAttribute('aria-selected') === 'true' ? 'doubts' : 'outline';
    tab(to);
    (to === 'doubts' ? el.doubtTab : el.outlineTab).focus();
  });

  sh.addEventListener('click', function (e) {
    var t = e.target;
    var row = t.closest('.tree .row');
    if (row) { var li = row.parentNode; expand(li, row.getAttribute('aria-expanded') !== 'true'); return; }
    var to = t.closest('[data-to]');
    if (to) { reveal(to.getAttribute('data-to')); return; }
    var go = t.closest('[data-go]');
    if (go) { jump(go); return; }
    var en = t.closest('[data-entry]');
    if (en) { entry(en); return; }
    var all = t.closest('[data-all]');
    if (all) {
      var on = all.getAttribute('data-all') === 'open';
      sh.querySelectorAll('.tree .node').forEach(function (li) { expand(li, on); });
      return;
    }
    /* A source on another site: a sandboxed page cannot open a tab, so the
       page around it is asked to, as `follow_script` in pages.py does for a
       link in the report itself. On a page with nobody around it, the link
       is left to the browser. */
    var out = t.closest('a[data-out]');
    if (out) {
      var p = null;
      try { p = window.parent; } catch (err) {}
      if (p && p !== window) {
        e.preventDefault();
        try { p.postMessage({ type: 'rouh-page-follow', out: true, href: out.href }, '*'); } catch (err) {}
      }
    }
  });

  /* Escape closes the X-ray, and goes no further: in Rouh's frame it would
     otherwise also take the reader back a level (`keys_script` in pages.py). */
  sh.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); return; }
    /* On a phone the panel is the whole screen, so Tab goes round inside it
       rather than into the page hidden under it. */
    if (e.key !== 'Tab' || !open || wide()) return;
    var can = [].slice.call(el.panel.querySelectorAll('button, a[href], [tabindex="0"]')).filter(function (x) {
      return x.getClientRects().length && x.tabIndex >= 0;
    });
    if (!can.length) return;
    var first = can[0], last = can[can.length - 1], at = sh.activeElement;
    if (e.shiftKey && (at === first || at === el.title)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
  });

  function theme() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    host.setAttribute('data-theme', t);
  }
  theme();
  new MutationObserver(theme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
  window.addEventListener('resize', function () {
    if (!open) return;
    el.panel.setAttribute('aria-modal', wide() ? 'false' : 'true');
    document.documentElement.classList.toggle('rouh-xray-push', wide());
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
else build();
})();
