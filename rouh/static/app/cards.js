/* Rouh's page, cards (section 9 of what was one app.js).
 *
 * Imports app/transcript.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { actBtn, cardInAnswer, cardInLiveAnswer, copyFrom, dropEmpty, scrollDown, stopTheTurn, T,
  turnIsRunning } from 'app/transcript.js';
import { shared } from 'app/shared.js';
import { $, clamp, el, esc, linkTo, siloChip, siloChips } from 'app/helpers.js';
import { load, store } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { demoFrame } from 'app/demo.js';
import { S, send } from 'app/socket.js';
import { ORBX } from 'app/orb.js';
import { jobClose, jobViewing, webClose, webViewing } from 'app/tasks.js';
import { ASK, askDelete, askFromPage, briefClose, briefViewing, BROWSE_ROOT, browseGo,
  workClose, workViewing, decisionsClose, decisionsViewing, actionsClose, actionsViewing, receiptsClose, receiptsViewing, homeClose, homeViewing,
  approvalsClose, approvalsViewing,
  sourcesClose, sourcesViewing, evolutionClose, evolutionViewing,
  thoughtsClose, thoughtsViewing,
  boxClose, boxViewing,
  browserZone, CANVAS, canvasLoad, canvasStep, clockPost, controlClose, controlViewing,
  drawCrumb, goalsClose, goalsTake, goalsViewing, locFind, locPermission, memoryClose, memoryViewing,
  moveOpen, moveSend, askTaskName, oneClose, oneViewing, pageUrl, projectsClose, projectsViewing, remindersClose,
  remindersViewing, runsClose, runsViewing, settingsClose, settingsViewing, sharePanelOpen,
  SHARES, sharesClose, synapseClose, synapseViewing, TASK_PREFIX, TASKS, TASKS_VIEW, tasksClose,
  tasksFrame, tasksUp, tasksViewing } from 'app/runs.js';
import { chatById, chatIsTask, CHATS, openChat } from 'app/chats.js';
import { findShow } from 'app/search.js';
import { ADDR, ADDR_BROWSER, addrAsk, addrOnCanvas, addrRead, addrTouch } from 'app/address.js';
import { canvasIsWanted, canvasShown, chatIsWanted, growInput, input, narrow, paintPaneButton, pane, sendTyped,
  setPane } from 'app/controls.js';
import { attSize, editorOpen } from 'app/attachments.js';
import { gtBoardClose, gtFromPage, gtOver } from 'app/gene_therapy.js';
import { offlineClose, offlineViewing } from 'app/offlineview.js';

/* ------------------------------------------------------------------ 9 */

function mdInline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\(((?:https?:|mailto:)[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

//: One cell of the row of dashes under a table's headings. The colons are
//: the alignment, which this draws all one way, and are taken rather than
//: refused so a table written with them is still a table.
var MD_RULE = /^:?-+:?$/;

function mdCells(row) {
  return String(row).trim().replace(/^\|/, '').replace(/\|$/, '')
    .split('|').map(function (c) { return c.trim(); });
}

/* Whether the line under a row of pipes is what makes it a table.

   Every cell is dashes, and there are as many of them as there are
   headings. The count is the half that matters: without it a paragraph
   reading "yes | no" with a "---" under it becomes a one-column table, and
   that is a line of text and a rule, which is what it looks like. */
function mdIsRule(under, wide) {
  if (under.indexOf('-') < 0) return false;
  var cells = mdCells(under);
  if (cells.length !== wide) return false;
  for (var i = 0; i < cells.length; i++) {
    if (!MD_RULE.test(cells[i])) return false;
  }
  return true;
}

//: A list item: its indent, its bullet or its number, and its words.
var MD_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;

function mdLead(line) { return line.length - line.replace(/^\s+/, '').length; }

/* One list from lines[i], pushed onto `out`, and the line after it.

   A list is every item at the first one's indent and of its kind, numbered
   or not, and a blank line between two of them leaves them one list. A
   model leaves one between every item of a long numbered list, and until 5
   October 2026 each blank line closed the list and the next item opened a
   new one, so a list of seven read 1, 1, 1, 1, 1, 1, 1 (Petar: "the list is
   only 1's"). The first item's own number is where the list starts, so the
   second of two lists written 1-3 and 11-17 still counts from 11. Whatever
   is indented under an item - another paragraph, a list inside it, code -
   is drawn inside that item. */
function mdList(lines, i, out) {
  var first = MD_ITEM.exec(lines[i]);
  var indent = first[1].length, ordered = /\d/.test(first[2]);
  var start = ordered ? parseInt(first[2], 10) : 1;
  var items = [], loose = false;
  while (i < lines.length) {
    var line = lines[i].replace(/\s+$/, ''), m = MD_ITEM.exec(line);
    if (m && m[1].length === indent) {
      if (/\d/.test(m[2]) !== ordered) break;
      items.push({ head: m[3], rest: [] });
      i++;
      continue;
    }
    if (!line) {
      // A blank line ends the list unless what follows it is still in it.
      var next = lines[i + 1] || '';
      if (next.trim() && (mdLead(next) > indent || (MD_ITEM.test(next) && mdLead(next) === indent))) {
        loose = true;
        if (!(MD_ITEM.test(next) && mdLead(next) === indent)) items[items.length - 1].rest.push('');
        i++;
        continue;
      }
      break;
    }
    if (mdLead(line) > indent) { items[items.length - 1].rest.push(line); i++; continue; }
    break;
  }
  var tag = ordered ? 'ol' : 'ul';
  out.push('<' + tag + ' class="md-list' + (loose ? ' md-loose' : '') + '"' +
    (ordered && start !== 1 ? ' start="' + start + '"' : '') + '>' +
    items.map(function (it) {
      var cut = Infinity;
      it.rest.forEach(function (l) { if (l.trim()) cut = Math.min(cut, mdLead(l)); });
      var inner = cut === Infinity ? ''
        : renderMarkdown(it.rest.map(function (l) { return l.slice(cut); }).join('\n'));
      return '<li>' + mdInline(it.head) + inner + '</li>';
    }).join('') + '</' + tag + '>');
  return i;
}

/* A copy button on every block of code. Petar, 28 October 2026
   (fr_034bef30be85): "when you give me commands like that, can you give me a
   copy button? look at claude how they have an icon for copy and when you
   press it it gets a √". So each block carries the message row's own copy
   icon in its top right corner, and a press copies that block's code and
   nothing else, ticks for a moment (`copied` in app/transcript.js) and goes
   back. It is markup here because renderMarkdown hands back markup, and one
   listener on the document answers every block, wherever it was drawn. */
var CODE_COPY = '<button type="button" class="act act-copy code-copy" title="Copy" aria-label="Copy">' +
  '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"' +
  ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<rect class="ico-copy" x="9" y="9" width="11" height="11" rx="2"></rect>' +
  '<path class="ico-copy" d="M5 15V5a2 2 0 0 1 2-2h10"></path>' +
  '<path class="ico-copied" d="M5 13l4.5 4.5L19 7"></path></svg></button>';

document.addEventListener('click', function (e) {
  var t = /** @type {Element|null} */ (e.target);
  var b = t && t.closest ? /** @type {HTMLElement|null} */ (t.closest('.code-copy')) : null;
  if (!b) return;
  e.preventDefault();
  e.stopPropagation();
  var code = b.parentElement && b.parentElement.querySelector('code');
  // The code as it was written: only the newlines a fence leaves at its end go.
  var text = code ? (code.textContent || '').replace(/\n+$/, '') : '';
  copyFrom(b, text, 'Copied');
});

function renderMarkdown(src) {
  var lines = String(src == null ? '' : src).replace(/\r/g, '').split('\n');
  var out = [], para = [];
  // Somebody who typed three lines meant three lines, so every newline
  // inside a paragraph is written out as the break it was. It has to be a
  // <br>: a newline left in the markup is whitespace, and whitespace is
  // collapsed wherever a bubble or a card sets `white-space: normal`, which
  // is what turned a typed message into one run-on line. A blank line is
  // still what starts a new paragraph.
  function flushPara() {
    if (para.length) { out.push('<p>' + mdInline(para.join('\n')).replace(/\n/g, '<br>') + '</p>'); para = []; }
  }
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].replace(/\s+$/, '');
    if (!line.trim()) { flushPara(); continue; }
    /* Code in a fence, kept exactly as it was written. Until 27 September
       2026 there was no case for one, so a fence came out as two stray
       backticks either side of its code drawn as a line of inline code. */
    var fence = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence) {
      flushPara();
      var code = [];
      for (i++; i < lines.length && lines[i].trim().indexOf(fence[1]) !== 0; i++) code.push(lines[i]);
      out.push('<div class="code-box"><pre class="md-code"><code>' + esc(code.join('\n')) +
        '</code></pre>' + CODE_COPY + '</div>');
      continue;
    }
    var h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { flushPara(); var lvl = Math.min(6, h[1].length + 2); out.push('<h' + lvl + '>' + mdInline(h[2]) + '</h' + lvl + '>'); continue; }
    /* A table, as a model writes one: a header row, a row of dashes under
       it, and the body. There was nowhere for one to go until 23 September
       2026, so a table arrived on screen as four lines of pipes - which is
       what Ask AI's own prompt asks for whenever a table helps, and what it
       got back every time. */
    var head = line.indexOf('|') >= 0 ? mdCells(line) : null;
    if (head && mdIsRule(lines[i + 1] || '', head.length)) {
      flushPara();
      var body = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].indexOf('|') >= 0; i++) {
        body.push(mdCells(lines[i]));
      }
      i--;
      out.push('<table class="md-table"><thead><tr>' +
        head.map(function (c) { return '<th>' + mdInline(c) + '</th>'; }).join('') +
        '</tr></thead><tbody>' +
        body.map(function (r) {
          return '<tr>' + r.map(function (c) { return '<td>' + mdInline(c) + '</td>'; }).join('') + '</tr>';
        }).join('') +
        '</tbody></table>');
      continue;
    }
    // A bullet, or a number followed by a dot or a bracket. Both are lists
    // on the page rather than a line of text that happens to start with a
    // digit, which is what "1. " used to leave behind.
    if (MD_ITEM.test(line)) { flushPara(); i = mdList(lines, i, out) - 1; continue; }
    para.push(line.trim());
  }
  flushPara();
  return out.join('');
}

/* ---------- where it came from ------------------------------------------

   Petar, 24 September 2026: "After web search and research as a whole,
   every source needs to be listed in a sources section. Ideally different
   items should have footnote numbers so we know specifically which thing
   was found at which url."

   A footnote is written as plain text, "[2]" or "[1, 3]", and the list it
   points at is a "Sources" line over a numbered list of links. Rouh's own
   answers are given both by the server, out of the citations the API hangs
   on what the model wrote (rouh/citing.py), and so is an answer in Ask AI;
   a card has a sources block the model fills in (`sourcesBlock`). This
   finds the list, puts each page's address under its title, and turns every
   number the list has into a small button that brings its entry into view
   and lights it. So a number next to a sentence leads, in one press, to the
   page the sentence came from, and a press on the page's name opens it.

   A number points at the first list after it: an answer's words come before
   its list, including words written above a tool the answer then used. One
   with no list after it is left as it is, and so is a number the list does
   not have - "[2026]" is a year in brackets. Never the list before it: while
   an answer is still being written its own list has not arrived, and the
   one above it belongs to the answer before. */

//: A run of footnotes, "[2]", "[1][3]" or "[1, 3]", and the space before
//: it, which the numbers take the place of: "the launch [2]" and "the
//: launch[2]" both end up "the launch²".
var CITE_MARK = / ?((?:\[\d{1,3}(?:\s*,\s*\d{1,3})*\])+)/g;

//: What a footnote is never looked for inside: somebody's link, code, the
//: list itself, the controls round a message, and a tool's own line, whose
//: search results are titles somebody else wrote.
var CITE_SKIP = 'a, code, pre, button, sup.cites, .sources-list, .turn-acts, .card-head, .tool';

// The site and the path, short, which is what an entry says under its name.
function sourceWhere(href) {
  var u;
  try { u = new URL(href, location.href); } catch (err) { return ''; }
  if (!/^https?:$/.test(u.protocol)) return '';
  var said = u.host.replace(/^www\./, '') + u.pathname.replace(/\/+$/, '');
  return said.length > 80 ? said.slice(0, 79) + '…' : said;
}

// One entry: its number, its name as the link, and where it is. The name is
// wrapped so the three sit in a grid whatever the entry was written as.
function dressSource(li, n) {
  if (li.getAttribute('data-n')) return;
  li.setAttribute('data-n', String(n));
  var name = el('span', 'src-name');
  while (li.firstChild) name.appendChild(li.firstChild);
  li.appendChild(name);
  var link = name.querySelector('a[href]');
  var at = link ? sourceWhere(link.getAttribute('href')) : '';
  if (at) {
    li.setAttribute('data-where', at);
    li.appendChild(el('span', 'src-where', at));
  }
}

// A card's sources block: every page it was made from, in the order of the
// numbers its items carry. A page with no address keeps its place, so the
// numbers after it still point where the model meant them to.
/** @param {import('./protocol').BlockOf<'sources'>} b */
function sourcesBlock(b) {
  var pages = Array.isArray(b.sources) ? b.sources : [];
  if (!pages.length) return null;
  var node = el('div', 'b-sources');
  node.appendChild(el('p', 'sources-head', 'Sources'));
  var list = el('ol', 'sources-list');
  for (var i = 0; i < pages.length; i++) {
    var page = pages[i] && typeof pages[i] === 'object' ? pages[i] : { url: String(pages[i] || '') };
    var url = String(page.url || page.href || '').trim();
    var li = el('li');
    if (/^https?:\/\//i.test(url)) {
      var a = el('a', null, String(page.title || '').trim() || sourceWhere(url) || url);
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      li.appendChild(a);
    } else {
      li.appendChild(document.createTextNode(String(page.title || url || 'A source with no address')));
    }
    list.appendChild(li);
    dressSource(li, i + 1);
  }
  node.appendChild(list);
  return node;
}

// Every Sources list inside `root`, the ones a card drew and the ones
// written in Markdown: a line saying "Sources" with a numbered list under it.
function sourceLists(root) {
  var heads = root.querySelectorAll('p, h3, h4, h5, h6');
  for (var i = 0; i < heads.length; i++) {
    var list = heads[i].nextElementSibling;
    if (!list || list.tagName !== 'OL' || list.classList.contains('sources-list')) continue;
    if (!/^sources:?$/i.test((heads[i].textContent || '').trim())) continue;
    heads[i].classList.add('sources-head');
    list.classList.add('sources-list');
    var first = Number(list.getAttribute('start')) || 1;
    for (var j = 0, n = 0; j < list.children.length; j++) {
      if (list.children[j].tagName === 'LI') dressSource(list.children[j], first + n++);
    }
  }
  return [].slice.call(root.querySelectorAll('ol.sources-list'));
}

function sourceEntry(list, n) {
  var items = list.children;
  for (var i = 0; i < items.length; i++) {
    if (items[i].getAttribute('data-n') === String(n)) return items[i];
  }
  return null;
}

// Bring one entry into view and light it, and put the keyboard on its link
// so Enter opens the page.
function showSource(li) {
  if (!li) return;
  try { li.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  catch (err) { li.scrollIntoView(false); }
  li.classList.remove('is-lit');
  void li.offsetWidth;
  li.classList.add('is-lit');
  clearTimeout(li.__lit);
  li.__lit = setTimeout(function () { li.classList.remove('is-lit'); }, 2400);
  var a = li.querySelector('a[href]');
  if (a) { try { a.focus({ preventScroll: true }); } catch (err) {} }
}

function citeButton(n, li) {
  var b = el('button', 'cite', String(n));
  b.type = 'button';
  var link = li.querySelector('a[href]');
  var name = ((link || li.querySelector('.src-name') || li).textContent || '').trim();
  var at = li.getAttribute('data-where') || '';
  var said = 'Source ' + n + (name ? ': ' + name : '') + (at && at !== name ? ' (' + at + ')' : '');
  b.title = said;
  b.setAttribute('aria-label', said);
  b.addEventListener('click', function (e) {
    e.preventDefault();
    e.stopPropagation();
    showSource(li);
  });
  return b;
}

function citeText(node, list) {
  var text = node.nodeValue, count = list.querySelectorAll(':scope > li[data-n]').length;
  var parts = document.createDocumentFragment(), last = 0, any = false, m;
  CITE_MARK.lastIndex = 0;
  while ((m = CITE_MARK.exec(text))) {
    var numbers = (m[1].match(/\d+/g) || []).map(Number);
    var entries = numbers.map(function (x) { return x >= 1 && x <= count ? sourceEntry(list, x) : null; });
    if (entries.some(function (li) { return !li; })) continue;
    // The numbers go with the word they follow, so a line never breaks
    // between the two and never starts with a number on its own.
    var before = text.slice(last, m.index), word = before.search(/\S+$/);
    if (word < 0) word = before.length;
    parts.appendChild(document.createTextNode(before.slice(0, word)));
    var glue = el('span', 'cite-glue', before.slice(word) || null);
    var sup = el('sup', 'cites');
    for (var i = 0; i < numbers.length; i++) sup.appendChild(citeButton(numbers[i], entries[i]));
    glue.appendChild(sup);
    parts.appendChild(glue);
    last = m.index + m[0].length;
    any = true;
  }
  if (!any) return;
  parts.appendChild(document.createTextNode(text.slice(last)));
  node.parentNode.replaceChild(parts, node);
}

function footnotes(root) {
  if (!root || !root.querySelectorAll) return;
  var lists = sourceLists(root);
  if (!lists.length) return;
  var walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  var found = [], node;
  while ((node = walk.nextNode())) {
    if (node.nodeValue.indexOf('[') < 0) continue;
    if (node.parentElement && node.parentElement.closest(CITE_SKIP)) continue;
    found.push(node);
  }
  for (var i = 0; i < found.length; i++) {
    var list = null;
    for (var j = 0; j < lists.length && !list; j++) {
      if (found[i].compareDocumentPosition(lists[j]) & Node.DOCUMENT_POSITION_FOLLOWING) list = lists[j];
    }
    if (list) citeText(found[i], list);
  }
}

// A card's blocks in the order they are drawn: its sources at the end,
// wherever they were written, and as one list, because every number on the
// card counts through one list.
function sourcesLast(blocks) {
  var rest = [], pages = [];
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i];
    if (b && b.block === 'sources') pages = pages.concat(Array.isArray(b.sources) ? b.sources : []);
    else rest.push(b);
  }
  if (pages.length) rest.push({ block: 'sources', sources: pages });
  return rest;
}

function svgEl(name, attrs) {
  var n = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (var k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}

function niceMax(v) {
  // A round number at or just above the largest value. The ladder is fine on
  // purpose: with only 1, 2, 5 and 10 to choose from, a maximum of 51,000
  // rounds up to 100,000 and every bar is drawn in the bottom half of the
  // chart. 6 gives 60,000 and the picture is readable.
  if (!(v > 0)) return 1;
  var exp = Math.pow(10, Math.floor(Math.log10(v)));
  var f = v / exp;
  var ladder = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  for (var i = 0; i < ladder.length; i++) {
    if (f <= ladder[i] + 1e-9) return ladder[i] * exp;
  }
  return 10 * exp;
}

/** @param {import('./protocol').BlockOf<'chart'>} b */
function chartBlock(b) {
  var labels = Array.isArray(b.labels) ? b.labels.map(String) : [];
  var values = (Array.isArray(b.values) ? b.values : []).map(function (v) { return Number(v) || 0; });
  var n = Math.max(labels.length, values.length);
  if (!n) return null;
  while (labels.length < n) labels.push('');
  while (values.length < n) values.push(0);

  var kind = b.kind === 'line' ? 'line' : 'bar';
  var W = 640, H = 230, padL = 46, padR = 14, padT = 16, padB = 34;
  var pw = W - padL - padR, ph = H - padT - padB;
  var lo = Math.min(0, Math.min.apply(null, values));
  var hi = niceMax(Math.max.apply(null, values));
  if (hi === lo) hi = lo + 1;
  var y = function (v) { return padT + ph - ((v - lo) / (hi - lo)) * ph; };

  var wrap = el('div', 'b-chart');
  if (b.title) wrap.appendChild(el('div', 'card-title', b.title));
  var scroll = el('div', 'chart-scroll');
  var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': (b.title || 'chart') + ', ' + kind });
  svg.style.minWidth = Math.max(300, Math.min(640, n * 46)) + 'px';

  // gridlines
  for (var g = 0; g <= 4; g++) {
    var gv = lo + ((hi - lo) * g) / 4;
    var gy = y(gv);
    svg.appendChild(svgEl('line', { x1: padL, y1: gy, x2: W - padR, y2: gy, class: 'ch-grid' }));
    var lt = svgEl('text', { x: padL - 8, y: gy + 4, class: 'ch-lbl', 'text-anchor': 'end' });
    lt.textContent = String(Math.round(gv * 100) / 100);
    svg.appendChild(lt);
  }
  svg.appendChild(svgEl('line', { x1: padL, y1: padT, x2: padL, y2: padT + ph, class: 'ch-axis' }));
  svg.appendChild(svgEl('line', { x1: padL, y1: y(Math.max(lo, 0)), x2: W - padR, y2: y(Math.max(lo, 0)), class: 'ch-axis' }));

  var slot = pw / n;
  var i, cx, txt;

  if (kind === 'bar') {
    var bw = Math.min(52, slot * 0.6);
    for (i = 0; i < n; i++) {
      cx = padL + slot * (i + 0.5);
      var zero = y(Math.max(lo, 0));
      var yTop = Math.min(y(values[i]), zero);
      var hgt = Math.abs(y(values[i]) - zero);
      svg.appendChild(svgEl('rect', {
        x: cx - bw / 2, y: yTop, width: bw, height: Math.max(1, hgt), rx: 3, class: 'ch-bar'
      }));
      if (n <= 14) {
        txt = svgEl('text', { x: cx, y: yTop - 6, class: 'ch-val', 'text-anchor': 'middle' });
        txt.textContent = String(values[i]);
        svg.appendChild(txt);
      }
    }
  } else {
    var pts = [];
    for (i = 0; i < n; i++) pts.push((padL + slot * (i + 0.5)) + ',' + y(values[i]));
    var zeroY = y(Math.max(lo, 0));
    svg.appendChild(svgEl('path', {
      d: 'M' + (padL + slot * 0.5) + ',' + zeroY + ' L' + pts.join(' L') + ' L' + (padL + slot * (n - 0.5)) + ',' + zeroY + ' Z',
      class: 'ch-area'
    }));
    svg.appendChild(svgEl('polyline', { points: pts.join(' '), class: 'ch-line' }));
    for (i = 0; i < n; i++) {
      svg.appendChild(svgEl('circle', { cx: padL + slot * (i + 0.5), cy: y(values[i]), r: 3.2, class: 'ch-dot' }));
    }
  }

  var every = n > 12 ? Math.ceil(n / 12) : 1;
  for (i = 0; i < n; i++) {
    if (i % every) continue;
    txt = svgEl('text', { x: padL + slot * (i + 0.5), y: H - 12, class: 'ch-lbl', 'text-anchor': 'middle' });
    txt.textContent = labels[i];
    svg.appendChild(txt);
  }

  scroll.appendChild(svg);
  wrap.appendChild(scroll);
  return wrap;
}

/* ---------- a picture on a card ----------

   Asked for a picture of a whale, Rouh used to offer a link to one,
   because a link was the nearest thing on the list of blocks it had. Now
   there is a picture block and the picture is drawn.

   It is loaded straight from wherever it is, which is what a browser is
   for: one round trip, cached where caches are, nothing through this
   machine. `referrerpolicy="no-referrer"` is what makes that work most of
   the time - a host that refuses to be hotlinked is reading the referrer,
   and there is not one to read. For the rest, a picture that fails to load
   is asked for a second time through Rouh, which fetches it on its own
   connection and hands the bytes over (picture.py). Only then, and only if
   that fails too, does the card say so in words. */

var IMAGE_PROXY = '/api/canvas/image?src=';

// Where a picture may come from: the open web, this Rouh, or the bytes
// themselves. Anything else - javascript:, file:, a data: URL that is not a
// picture - is not drawn at all.
function pictureSrc(raw) {
  if (typeof raw !== 'string') return null;
  var said = raw.trim();
  if (!said) return null;
  if (/^data:image\/[a-z0-9.+-]+[;,]/i.test(said)) return said;
  var u;
  try { u = new URL(said, location.href); } catch (err) { return null; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
  return u.href;
}

// Whether Rouh fetching this instead would be any different. It would not
// for this machine's own addresses, and there is nothing to fetch for bytes
// that are already here.
function worthProxying(src) {
  if (src.indexOf('data:') === 0) return false;
  try { return new URL(src, location.href).origin !== location.origin; }
  catch (err) { return false; }
}

/** @param {import('./protocol').BlockOf<'image'>} b */
function imageBlock(b) {
  var src = pictureSrc(b.src);
  if (!src) return null;
  var fig = el('figure', 'b-image');
  var img = document.createElement('img');
  img.alt = b.alt == null ? '' : String(b.alt);
  img.setAttribute('referrerpolicy', 'no-referrer');
  img.setAttribute('decoding', 'async');
  // The size the model already knows, so the card is the right height before
  // the bytes arrive and nothing under it jumps. The stylesheet still scales
  // the picture to the card's width; these are only the proportions.
  if (b.width > 0) img.setAttribute('width', String(Math.round(b.width)));
  if (b.height > 0) img.setAttribute('height', String(Math.round(b.height)));
  var tried = '';
  img.addEventListener('error', function () {
    if (tried === '' && worthProxying(src)) {
      tried = 'rouh';
      img.src = IMAGE_PROXY + encodeURIComponent(src);
      return;
    }
    if (tried === 'gone') return;
    tried = 'gone';
    img.remove();
    var gone = el('div', 'img-gone', 'That picture could not be loaded. ');
    var a = el('a', null, src.slice(0, 120));
    a.href = src;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    gone.appendChild(a);
    fig.insertBefore(gone, fig.firstChild);
  });
  img.src = src;
  fig.appendChild(img);
  if (b.caption) fig.appendChild(el('figcaption', null, b.caption));
  return fig;
}

/* ---------- markup the model wrote, in a frame of its own ----------

   The blocks above are a fixed list, and a fixed list is a menu: asked for a
   timeline, a diagram, two things side by side or a gallery, the best that
   could be done was the nearest item on it. So the model can write the
   markup itself and it is drawn as it is.

   It is not drawn on this page. It goes in a frame whose sandbox is
   `allow-scripts` and nothing besides - the same one word a workspace page
   gets, and for the same reason. Without the flag that would hand it this
   page's own origin, the browser gives it one that matches nothing: it
   cannot read this page, this page's cookies or this page's storage, cannot
   navigate this page, cannot open a window and cannot submit a form. Inside
   the markup there is a second lock, a Content-Security-Policy that leaves
   it its own style, its own script and pictures, and takes away fetch,
   sockets, forms and frames of its own.

   Every one of those flags is a single word away, so `test_workspace_pages.py`
   refuses to let any of them appear anywhere in this file, in code or in a
   sentence about it. That is why this paragraph names none of them.

   Two things the frame needs that a frame does not have. Colours: it cannot
   see this page's stylesheet, so Rouh's own variables go in with it. And a
   height: a frame has none of its own,
   so the page inside measures itself and says how tall it is, which is
   `rouh-html-size` below. Without that every one of these would be a fixed
   box with a scrollbar in it, which is not a card. */

//: Taller than this and the frame stops growing and scrolls what is in it
//: instead, rather than becoming a card nobody can get past.
var HTML_FRAME_MAX = 4000;

//: What a snippet is drawn in. Rouh's own colours, so
//: `var(--accent)` in something the model wrote is the same blue as the rest
//: of the screen; Rouh's fonts and its type sizes; and the card's own look
//: for the few elements a snippet is most likely to reach for. No background:
//: the card behind it is the background.
var HTML_FRAME_CSS = [
  ':root{color-scheme:dark;--bg:#0a0c10;--bg-2:#0e1116;--panel:#12161c;',
  '--panel-2:#171c24;--line:#232a34;--line-soft:#1b2129;--text:#e7ecf3;',
  '--dim:#8d9aac;--dimmer:#64707f;--accent:#5ec2ff;--accent-ink:#04121c;',
  '--accent-soft:rgba(94,194,255,.14);--good:#57d9a3;--warn:#f2b45e;--bad:#ff7a70;',
  '--radius:14px;--radius-s:9px;',
  '--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;',
  '--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,',
  '"Apple Color Emoji",sans-serif}',
  '*{box-sizing:border-box}',
  'html,body{margin:0;padding:0;background:transparent}',
  /* The one box everything the model wrote is inside, and the box the page
     measures. `flow-root` is the whole of why it is here: without it the
     last child's bottom margin collapses out through the body and out
     through the document element, so the body measures ten pixels shorter
     than the document it is in and the two disagree for ever. See
     HTML_FRAME_SCRIPT. */
  '#rouh-fit{display:flow-root}',
  'body{font-family:var(--sans);font-size:13.5px;line-height:1.55;color:var(--text)}',
  'h1,h2,h3,h4{margin:0 0 8px;font-weight:600;line-height:1.3}',
  'h1{font-size:18px}h2{font-size:16px}h3{font-size:14px}h4{font-size:13px}',
  'p{margin:0 0 8px}p:last-child{margin-bottom:0}',
  'a{color:var(--accent)}',
  'img,svg,canvas,video{max-width:100%}img,video{height:auto}',
  'table{border-collapse:collapse;font-size:13px}',
  'th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line-soft);',
  'vertical-align:top}',
  'th{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);',
  'font-weight:600}',
  'code,kbd,pre{font-family:var(--mono);font-size:12px}',
  'pre{background:var(--bg);border:1px solid var(--line-soft);border-radius:9px;',
  'padding:11px 12px;overflow-x:auto}',
  'hr{border:0;border-top:1px solid var(--line-soft);margin:12px 0}'
].join('');

//: Scripts and style of its own, and pictures. No connect-src, so nothing in
//: here can call anything; no form-action, so nothing can post anywhere; no
//: frame-src, so it cannot open a frame to get around either. The frame's own
//: sandbox attribute is the lock that matters and this is the second one.
var HTML_FRAME_CSP = "default-src 'none'; img-src https: http: data: blob:; "
  + "media-src https: http: data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
  + "font-src data:; base-uri 'none'; form-action 'none'";

//: The page inside measuring itself and saying so. Written as one string
//: because it goes into `srcdoc` rather than being fetched: there is no file
//: for a frame with no origin to ask for.
//: It measures on load, whenever anything inside it changes shape or content,
//: as each picture arrives, and a few times shortly after opening, which is
//: when a web font or a late picture moves everything down.
//:
//: **What it measures may never depend on how tall the frame already is.**
//: That is the whole rule, and breaking it is the jumping card Petar
//: reported on 22 September 2026: card 532 grew and shrank by ten pixels,
//: several times a second, for as long as it was on the screen.
//:
//: How that happened is worth keeping. It measured the body, and the
//: document element as well but only when the document element had really
//: overflowed - `past > innerHeight` - because a document element's
//: `scrollHeight` is never less than the window it is in and taking the
//: larger of the two unguarded would have meant a card could only ever grow.
//: The guard was sound. What was not is that the two heights disagreed at
//: rest: the last thing in card 532 carries a ten pixel bottom margin, that
//: margin collapses out through the body and out through the document
//: element, so the body measured 1135 and the document element 1145 with
//: nothing moving. At 1135 the guard was true and the page said 1145; the
//: frame became 1145, the guard was false, and the page said 1135. For ever.
//:
//: So the content goes in a box of its own that makes a block formatting
//: context (`#rouh-fit`, `display:flow-root` in HTML_FRAME_CSS). No margin
//: can escape it, its height is the whole of what the model drew, and that
//: height is a function of the frame's **width** alone. `innerHeight` is not
//: asked about at all any more, which is what makes the measurement settle.
//:
//: The one term that is still read off the window is the height a horizontal
//: scrollbar takes when the layout is wider than the frame - `innerHeight`
//: less the document element's `clientHeight` - and it is safe for the same
//: reason the rest is: it answers a question about width, not about height.
var HTML_FRAME_SCRIPT = [
  '(function(){var last=-1;',
  'function tall(){var d=document,b=d.body,e=d.documentElement;',
  'var box=d.getElementById("rouh-fit");',
  'var h=box?box.getBoundingClientRect().height:0;',
  'h=Math.max(h,b?b.scrollHeight:0);',
  'var bar=innerHeight-e.clientHeight;',
  'if(bar>0)h+=bar;',
  'return Math.ceil(h);}',
  'function say(){var h=tall();if(h===last)return;last=h;',
  'try{parent.postMessage({type:"rouh-html-size",height:h},"*");}catch(err){}}',
  'addEventListener("load",say);addEventListener("resize",say);',
  'if(window.ResizeObserver){var o=new ResizeObserver(say);',
  'o.observe(document.documentElement);if(document.body)o.observe(document.body);',
  'var fit=document.getElementById("rouh-fit");if(fit)o.observe(fit);}',
  'if(window.MutationObserver){new MutationObserver(say).observe(document.documentElement,',
  '{subtree:true,childList:true,attributes:true,characterData:true});}',
  'var pics=document.images;for(var i=0;i<pics.length;i++){',
  'pics[i].addEventListener("load",say);pics[i].addEventListener("error",say);}',
  'var when=[0,60,250,800,2000,5000];',
  'for(var j=0;j<when.length;j++)setTimeout(say,when[j]);',
  '})();'
].join('');

/* Giving a frame the height the page inside it asked for, and the latch that
   stops a card jumping for ever.

   Sizing a box from what is inside it, when what is inside it is laid out
   against that box, is a loop looking for somewhere to happen. The
   measurement above no longer gives it one, and it is not the only way in:
   a vertical scrollbar appearing takes fifteen pixels of width from markup
   nobody here wrote, which can reflow a line away and make the content
   shorter, which takes the scrollbar off again. That one is between the
   browser and a card's own CSS, and no measuring is careful enough to talk
   it out of it.

   So a frame remembers the last two heights it was given. A third that is
   the same as the one before it, and within a line's height of the one after
   it, is not a card that changed: it is a card flapping between two layouts.
   The taller of the two is kept - a card with ten pixels of room to spare
   reads exactly like a card, and one ten pixels short has a line cut off -
   and nothing that frame says afterwards moves it, until it says something
   outside that pair, which is a real change and starts the watch again.

   A real change is never an exact A-B-A inside a line's height, so nothing
   that ought to move is held still by this. */
var HTML_FRAME_JITTER = 24;

/* A file read on the canvas runs down the page: its frame is as tall as
   the file, and the canvas scrolls it, the way it scrolls every column of
   Rouh's own (`objectindex.FLOW_SCRIPT`, fr_0ce726bbcc5b). Every page
   opened on the canvas gets a new frame (`canvasLoad`), so only a page that
   said its height is ever sized. The same page loaded again into the same
   frame keeps the height until it says it again, so the reader stays at
   the place they had scrolled to. */
function tasksFlow(frame, height) {
  var body = $('tasksBody');
  if (!body || frame.parentNode !== body || !(height > 0)) return;
  body.classList.add('flows');
  frame.style.height = Math.ceil(height) + 'px';
}

function htmlFrameHeight(frame, want) {
  var seen = frame.__rouhSeen || (frame.__rouhSeen = []);
  var stuck = frame.__rouhStuck || 0;
  // Latched, and this is the flapping it was latched against: ignored.
  if (stuck && Math.abs(want - stuck) < HTML_FRAME_JITTER) return;
  if (stuck) { frame.__rouhStuck = 0; seen.length = 0; }
  seen.push(want);
  if (seen.length > 3) seen.shift();
  if (seen.length === 3 && seen[0] === seen[2] && seen[0] !== seen[1]
      && Math.abs(seen[1] - seen[0]) < HTML_FRAME_JITTER) {
    frame.__rouhStuck = Math.max(seen[0], seen[1]);
    frame.style.height = frame.__rouhStuck + 'px';
    seen.length = 0;
    return;
  }
  frame.style.height = want + 'px';
}

// The whole document a snippet is put into. `srcdoc` rather than an address,
// so there is nothing for anybody to fetch and nothing of this to reach
// except through the frame's edge.
function htmlFrameDoc(markup) {
  return demoFrame('<!doctype html><html>'
    + '<head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<meta http-equiv="Content-Security-Policy" content="' + HTML_FRAME_CSP + '">'
    + '<style>' + HTML_FRAME_CSS + '</style></head><body>'
    // Everything the model wrote, in the one box the page measures. It is a
    // block formatting context, so the height it reports is the height it
    // really is and no margin can collapse out of it into the document
    // around it (HTML_FRAME_SCRIPT says what that cost).
    + '<div id="rouh-fit">' + markup + '</div>'
    + '<script>' + HTML_FRAME_SCRIPT + '<\/script>'
    + '</body></html>');
}

/* Markup the model wrote, in a frame of its own.

   Every other block reflows: a table scrolls sideways inside its own box, a
   chart shrinks with the column, a list wraps. This one cannot, because its
   widths are whatever the model wrote them as. At a desk that is no matter,
   because every card is read on the canvas there (`openOnCanvas`). On a
   phone there is no second column, so it is drawn as what it is - an
   ordinary page - and allowed to scroll sideways inside the stream rather
   than being squashed or cut off.

   It carried the button that opens its card on the canvas until 24
   September 2026, when it was the only card that went there. Every card
   does now, so the button is on every card's head (`renderCard`). */
/** @param {import('./protocol').BlockOf<'html'>} b */
function htmlBlock(b) {
  var markup = typeof b.html === 'string' ? b.html
    : (typeof b.text === 'string' ? b.text : '');
  if (!markup.trim()) return null;
  var wrap = el('div', 'b-html');
  if (b.title) {
    var head = el('div', 'b-html-head');
    head.appendChild(el('div', 'card-title', b.title));
    wrap.appendChild(head);
  }
  // The page keeps its own width and is allowed to run past the column it is
  // read in, which is what a phone needs: squashed to 360 pixels a layout
  // written for 700 is not the thing the model drew.
  var scroll = el('div', 'html-scroll');
  var frame = document.createElement('iframe');
  frame.className = 'html-frame';
  frame.setAttribute('sandbox', 'allow-scripts');
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.title = b.title || 'Something Rouh drew';
  // A height to open at, so a card does not start as a sliver and jump. The
  // page inside says what it really is as soon as it has loaded.
  frame.style.height = clamp(b.height > 0 ? Number(b.height) : 180, 40, HTML_FRAME_MAX) + 'px';
  frameWrite(frame, htmlFrameDoc(markup));
  scroll.appendChild(frame);
  wrap.appendChild(scroll);
  return wrap;
}

/* ---------- a contact, before it is saved and after ---------------------

   What save_contact puts on the screen (apple_contacts.contact_card). The
   person is asked out loud before anything goes to their iCloud contacts,
   and Petar wanted to see the contact as well as hear it, 24 September
   2026: "I would like to see the new contact, though." So the same card
   is drawn twice: once while the details are read back, marked not saved
   yet, and again, in place, as iCloud kept it once they have said yes.

   On a change every field says what the change did to it. A number or an
   address taken off stays in the list, struck through, because something
   that has quietly gone missing is the one change nobody notices. A new
   contact marks nothing: everything on it is new.

   Every word on it is somebody's contact card, which anybody who ever sent
   a vCard could have written, so all of it goes in as text. */

var CONTACT_CHANGE = { added: 'added', changed: 'changed', removed: 'removed' };

// The first letter of the first word and of the last, as the phone draws
// them: a double-barrelled surname is one word, so it gives its first.
function contactInitials(name) {
  var words = String(name || '').trim().split(/\s+/).map(function (word) {
    var found = word.match(/[\p{L}\p{N}]/u);
    return found ? found[0] : '';
  }).filter(Boolean);
  var said = words.length > 1 ? words[0] + words[words.length - 1] : (words[0] || '');
  return said.toUpperCase() || '?';
}

function contactWas(text) {
  var was = el('span', 'ct-was');
  was.appendChild(document.createTextNode('was '));
  was.appendChild(el('s', null, text));
  return was;
}

/* ---------- Call from their contact card (night 42, rouh/card_call.py) ----------

   A card marked `call` draws each number as a tel: link with Call and Text
   beside it, so the phone rings or opens a text in one press. The press is
   only counted (POST /api/card-call, no number sent); the link does the rest. */

/** The number as a phone dials it: digits, with a leading +; "" when there are too few. */
function contactTel(number) {
  var text = String(number == null ? '' : number).trim();
  var digits = text.replace(/[^0-9]/g, '');
  if (digits.length < 3) return '';
  return (text.charAt(0) === '+' ? '+' : '') + digits;
}

function contactCall(b, r) {
  var tel = contactTel(r.value);
  var who = b.name || 'them';
  var line = el('span', 'ct-call');
  var number = el('a', 'ct-val ct-tel', String(r.value));
  number.href = 'tel:' + tel;
  number.title = 'Rings ' + who + ' on ' + r.value;
  line.appendChild(number);
  var acts = el('span', 'ct-acts');
  [['Call', 'tel:', 'call', 'Call '], ['Text', 'sms:', 'text', 'Text ']].forEach(function (one) {
    var a = el('a', 'ct-act', one[0]);
    a.href = one[1] + tel;
    a.setAttribute('aria-label', one[3] + who + ' on ' + r.value);
    a.addEventListener('click', function () { contactCalled(one[2]); });
    acts.appendChild(a);
  });
  number.addEventListener('click', function () { contactCalled('call'); });
  line.appendChild(acts);
  return line;
}

function contactCalled(how) {
  try {
    fetch('/api/card-call', {
      method: 'POST', keepalive: true, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ how: how })
    }).catch(function () {});
  } catch (e) { /* counting a use is never worth an error */ }
}

/** @param {import('./protocol').BlockOf<'contact'>} b */
function contactBlock(b) {
  var saved = b.state === 'saved';
  var state = saved || b.state === 'declined' || b.state === 'shown' ? b.state : 'unsaved';
  var node = el('div', 'b-contact is-' + state);

  var head = el('div', 'ct-head');
  // Their own picture from iCloud, else the LinkedIn photo Rouh kept for them
  // (rouh/meeting_people.py), behind the sign-in; the initials otherwise.
  var face = b.photo ? personFace(b.photo, b.name, 'ct-face')
    : el('span', 'ct-face', contactInitials(b.name));
  face.setAttribute('aria-hidden', 'true');
  head.appendChild(face);
  var who = el('div', 'ct-who');
  var name = el('div', 'ct-name');
  name.appendChild(el('span', null, b.name || 'No name'));
  if (b.was_name) name.appendChild(el('span', 'ct-tag is-changed', CONTACT_CHANGE.changed));
  who.appendChild(name);
  if (b.was_name) who.appendChild(contactWas(b.was_name));
  head.appendChild(who);
  head.appendChild(el('span', 'ct-state', b.status || (saved ? 'Saved' : 'Not saved yet')));
  node.appendChild(head);

  // Rouh's own two fields are rows like any other, so a card filed as a
  // step keeps them (rouh/steps.py); here they are sections of their own.
  var all = Array.isArray(b.rows) ? b.rows : [];
  var rows = [], own = {}, silos = null;
  // Every address is one list of its own (personaddresses.js, rouh/person_addresses.py), in place of
  // the card's email rows, which stay in the block for a card filed as a step.
  var listed = !!(b.addresses && window.RouhAddresses && b.state !== 'unsaved' && b.state !== 'declined');
  for (var k = 0; k < all.length; k++) {
    var row = all[k] || {};
    if (CONTACT_OWN[row.kind]) own[row.kind] = row.value == null ? '' : String(row.value);
    // On your own card the company is changed here too, like the two fields below (About You, Contact card).
    else if (row.kind === 'organisation' && b.me && b.contact) own.organisation = row.value == null ? '' : String(row.value);
    else if (row.kind === 'silos') silos = row;
    else if (row.kind === 'email' && listed) continue;
    // An address that is Rouh's own is drawn under Also known as, with its Unlink.
    else if (row.in_aka && b.aka && window.RouhPersonLinks) continue;
    else rows.push(row);
  }
  if (rows.length) {
    var list = el('dl', 'ct-rows');
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i] || {};
      var change = CONTACT_CHANGE[r.change] ? r.change : '';
      var line = el('div', 'ct-row' + (change ? ' is-' + change : '')
        + (r.kind === 'note' ? ' is-note' : ''));
      line.appendChild(el('dt', null, r.label || r.kind || ''));
      var value = el('dd');
      if (b.call && r.kind === 'phone' && change !== 'removed' && contactTel(r.value)) {
        value.appendChild(contactCall(b, r));
      } else {
        value.appendChild(el(change === 'removed' ? 's' : 'span', 'ct-val', r.value == null ? '' : r.value));
      }
      if (r.was) value.appendChild(contactWas(r.was));
      line.appendChild(value);
      if (change) line.appendChild(el('span', 'ct-tag is-' + change, CONTACT_CHANGE[change]));
      list.appendChild(line);
    }
    node.appendChild(list);
  }
  if (listed) {
    var addresses = window.RouhAddresses.list({ data: b.addresses, ds: b.people_ds, editable: !!b.contact });
    addresses.classList.add('ct-own', 'is-addresses');
    node.appendChild(addresses);
  }
  var aka = contactAka(b);
  if (aka) node.appendChild(aka);
  // A guest of this Rouh's: the owner's two ways to get them back in (signinpage.js).
  if (b.contact && window.RouhGuestSignIn && b.state !== 'unsaved' && b.state !== 'declined') {
    var mails = (b.rows || []).filter(function (r) { return r.kind === 'email' && r.value; })
      .map(function (r) { return String(r.value); });
    if (mails.length) node.appendChild(window.RouhGuestSignIn.section(mails));
  }
  // Shown whenever there is something in them, and always on a card that
  // says which contact it is, because that is a card they can be written on.
  if (b.me && b.contact) node.appendChild(contactOwn(b, 'organisation', own.organisation || ''));
  ['relationship', 'research'].forEach(function (kind) {
    if (own[kind] || b.contact) node.appendChild(contactOwn(b, kind, own[kind] || ''));
  });
  if (silos !== null && b.contact) node.appendChild(contactSilos(b, silos));
  if (b.remark) node.appendChild(el('p', 'ct-remark', b.remark));
  if (b.foot) node.appendChild(el('p', 'ct-foot', b.foot));
  return node;
}

/* ---------- Rouh's own two fields on a contact --------------------------

   Petar, 25 September 2026: contacts gain "Online research (MD content)"
   and "My relationship to them", visible and editable wherever contacts are
   shown. Both are Rouh's own and never go to iCloud (rouh/people.py), so a
   change is kept at once, with no Save to iCloud in between: Save sends
   `contact_note` and the card comes back as `ui`, drawn again as it now
   reads, as a new version of itself. Something that could not be kept comes
   back as `contact_note_said`, and what was typed stays in the box.

   A card that says which contact it is (`contact`) can be written on; one
   that is only a look at a contact about to be saved cannot. The research
   is markdown written by Rouh from other people's pages, drawn by
   renderMarkdown, which escapes everything before it draws anything. */

var CONTACT_OWN = { relationship: 'My relationship', research: 'Online research' };

/* What each field is called: on the person's own card the relationship is who they are, and the
   company theirs (Petar, 4 November 2026: About You's own about text and organisation moved here). */
function contactOwnLabel(b, kind) {
  if (kind === 'organisation') return 'Company';
  if (kind === 'relationship' && b.me) return 'Who you are';
  return CONTACT_OWN[kind];
}

function contactOwn(b, kind, value) {
  var label = contactOwnLabel(b, kind);
  var box = el('section', 'ct-own is-' + kind);
  var head = el('div', 'ct-own-head');
  head.appendChild(el('h5', 'ct-own-title', label));
  box.appendChild(head);
  var body = el('div', 'ct-own-body');
  box.appendChild(body);
  var editable = !!b.contact && b.state !== 'unsaved' && b.state !== 'declined';
  var edit = null;
  function show() {
    body.textContent = '';
    if (!value) {
      body.appendChild(el('p', 'ct-own-empty', kind === 'research'
        ? 'Nothing researched yet.' : (b.me && kind === 'relationship' ? 'This is you.' : 'Not said yet.')));
      return;
    }
    if (kind === 'research') {
      var md = el('div', 'ct-md');
      md.innerHTML = renderMarkdown(value);
      body.appendChild(md);
      if (b.research_said) body.appendChild(el('p', 'ct-own-said', b.research_said));
    } else {
      body.appendChild(el('p', 'ct-rel', value));
    }
  }
  function write() {
    if (edit) edit.hidden = true;
    body.textContent = '';
    var area = el('textarea', 'ct-input');
    area.rows = kind === 'research' ? 10 : kind === 'organisation' ? 1 : 3;
    area.value = value;
    area.setAttribute('aria-label', label);
    area.placeholder = kind === 'research'
      ? 'Markdown: who they are, and the pages that say so.'
      : kind === 'organisation' ? 'Your company, or whatever says who you are.'
      : b.me ? 'A line or two about yourself.' : 'Who they are to you, in your own words.';
    var row = el('div', 'ct-edit-row');
    var save = el('button', 'ct-save', 'Save');
    save.type = 'button';
    var cancel = el('button', 'ct-cancel', 'Cancel');
    cancel.type = 'button';
    row.appendChild(save);
    row.appendChild(cancel);
    var said = el('p', 'ct-said');
    said.hidden = true;
    said.setAttribute('role', 'alert');
    body.appendChild(area);
    body.appendChild(row);
    body.appendChild(said);
    area.focus();
    function stop() {
      if (edit) edit.hidden = false;
      box.__said = null;
      show();
    }
    function keep() {
      var card = box.closest('.card');
      var number = card ? card.getAttribute('data-card') : null;
      if (!number) {
        said.textContent = 'This card cannot be written on here.';
        said.hidden = false;
        return;
      }
      save.disabled = cancel.disabled = true;
      save.textContent = 'Saving\u2026';
      said.hidden = true;
      send({ type: 'contact_note', card: Number(number), contact: b.contact,
             field: kind, value: area.value });
    }
    cancel.addEventListener('click', stop);
    save.addEventListener('click', keep);
    area.addEventListener('keydown', function (e) {
      // Escape leaves the box and nothing else: not a turn, not a panel.
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); stop(); return; }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); keep(); }
    });
    box.__said = function (why) {
      save.disabled = cancel.disabled = false;
      save.textContent = 'Save';
      said.textContent = why || 'That was not kept.';
      said.hidden = false;
    };
  }
  if (editable) {
    edit = el('button', 'ct-edit', value ? 'Edit' : 'Add');
    edit.type = 'button';
    edit.setAttribute('aria-label', (value ? 'Edit ' : 'Add ') + label.toLowerCase());
    edit.addEventListener('click', write);
    head.appendChild(edit);
  }
  show();
  return box;
}

/* ---------- silos, on a contact ------------------------------------------

   A contact is in one or more of the person's silos, or none (rouh/silos.py,
   Settings, Silos), which Rouh keeps beside their two own fields
   (rouh/people.py) and never sends to iCloud. Each silo is a chip that is
   pressed in or out; a press is kept at once, the same way a Save of the
   fields above is (`contact_note`, field `silos`, the whole set as keys), and
   the card comes back drawn as it now reads. A card that is only a look at a
   contact about to be saved shows the chips and no choices. */

function contactSilos(b, row) {
  var box = el('section', 'ct-own is-silos');
  var head = el('div', 'ct-own-head');
  var title = el('h5', 'ct-own-title', 'Silos');
  title.id = 'ctSilos' + Math.random().toString(36).slice(2, 9);
  head.appendChild(title);
  box.appendChild(head);
  var keys = Array.isArray(row.keys) ? row.keys.slice() : [];
  var editable = !!b.contact && b.state !== 'unsaved' && b.state !== 'declined';
  var said = el('p', 'ct-said');
  said.hidden = true;
  said.setAttribute('role', 'alert');
  if (!editable) {
    box.appendChild(siloChips(row.chips || []) || el('p', 'ct-rel', 'In no silo yet'));
    return box;
  }
  var group = el('div', 'silo-toggles');
  group.setAttribute('role', 'group');
  group.setAttribute('aria-labelledby', title.id);
  (row.choices || []).forEach(function (c) {
    var on = keys.indexOf(c.key) >= 0;
    var press = el('button', 'silo-toggle');
    press.type = 'button';
    press.setAttribute('aria-pressed', on ? 'true' : 'false');
    press.appendChild(siloChip(c));
    press.addEventListener('click', function () {
      var card = box.closest('.card');
      var number = card ? card.getAttribute('data-card') : null;
      if (!number) {
        said.textContent = 'This card cannot be written on here.';
        said.hidden = false;
        return;
      }
      var next = on ? keys.filter(function (k) { return k !== c.key; }) : keys.concat([c.key]);
      Array.prototype.forEach.call(group.children, function (x) { x.disabled = true; });
      said.hidden = true;
      send({ type: 'contact_note', card: Number(number), contact: b.contact, field: 'silos', value: next });
    });
    group.appendChild(press);
  });
  box.appendChild(group);
  if (row.said) box.appendChild(el('p', 'ct-own-said', row.said));
  box.appendChild(said);
  box.__said = function (why) {
    Array.prototype.forEach.call(group.children, function (x) { x.disabled = false; });
    said.textContent = why || 'That was not kept.';
    said.hidden = false;
  };
  return box;
}

/* ---------- Also known as, on a contact ---------------------------------

   Petar, 22 October 2026: which Slack member, address and name is this
   contact, set from the contact card (rouh/synapse/aka.py). The section is
   personlinks.js's, the same one the person's card in Synapse draws; after a
   link, an unlink or an Undo the card is drawn again as it now reads, in
   place (`contact_note`, field `refresh`), so every tab on this thread and a
   card filed as a step say the same. A card only looked at before it is
   saved has none. */

/** @param {import('./protocol').BlockOf<'contact'>} b */
function contactAka(b) {
  if (!b.aka || !b.people_ds || !b.contact || !window.RouhPersonLinks) return null;
  if (b.state === 'unsaved' || b.state === 'declined') return null;
  var box = window.RouhPersonLinks.section({
    ds: b.people_ds, person: b.contact, data: b.aka, by: 'contact card', hideCard: true,
    hideEmails: !!(b.addresses && window.RouhAddresses),
    className: 'ct-own is-aka',
    changed: function () {
      var card = box.closest('.card');
      var number = card ? card.getAttribute('data-card') : null;
      if (!number) { box.__said('Kept. Ask Rouh to show the contact again to see it.'); return; }
      send({ type: 'contact_note', card: Number(number), contact: b.contact, field: 'refresh', value: '' });
    }
  });
  return box;
}

// Why a change on a contact card was not kept, under the box it was typed in.
function contactNoteSaid(card, why) {
  var found = document.querySelectorAll('.card[data-card="' + card + '"] .ct-own');
  for (var i = 0; i < found.length; i++) if (found[i].__said) found[i].__said(why);
}

/* ---------- an email, as it arrived -------------------------------------

   The head of the conversation Rouh handles a new email in
   (rouh/mail_alerts.py): who it is from and to, when, what about, and what
   it says. Every word of it is the sender's, so it is all text, the body
   kept as it was written, line for line. */

/** @param {import('./protocol').BlockOf<'email'>} b */
function emailBlock(b) {
  var node = el('div', 'b-email');
  var head = el('dl', 'em-head');
  [['From', b.from], ['To', b.to], ['Cc', b.cc], ['Date', b.date]].forEach(function (pair) {
    if (!pair[1]) return;
    var line = el('div', 'em-line');
    line.appendChild(el('dt', null, pair[0]));
    var said = el('dd', null, pair[0] === 'From' && b.from_photo ? null : pair[1]);
    // The sender's face when they are a contact with one, as their contact card draws it.
    if (pair[0] === 'From' && b.from_photo) {
      said.classList.add('em-from');
      said.appendChild(personFace(b.from_photo, String(b.from).replace(/<[^>]*>/, '').trim(), 'em-face'));
      said.appendChild(el('span', null, pair[1]));
    }
    line.appendChild(said);
    head.appendChild(line);
  });
  node.appendChild(head);
  node.appendChild(el('div', 'em-subject', b.subject || '(no subject)'));
  node.appendChild(el('div', 'em-body', b.body || '(nothing written in it)'));
  // Its files, named: Rouh opens one when it needs what is in it
  // (rouh/mail_attachments.py), so the card only says they are there.
  if (b.files && b.files.length) {
    var files = el('ul', 'em-files');
    files.setAttribute('aria-label', 'Attached files');
    b.files.forEach(function (f) {
      var item = el('li', 'em-file');
      item.appendChild(el('span', 'em-fname', f.name || 'attachment'));
      if (f.about) item.appendChild(el('span', 'em-fabout', f.about));
      files.appendChild(item);
    });
    node.appendChild(files);
  }
  var foot = [b.filed ? 'Gmail filed it: ' + b.filed + '.' : '', b.checked || '']
    .filter(Boolean).join(' ');
  if (foot) node.appendChild(el('p', 'em-foot', foot));
  return node;
}

function emailWords(b) {
  var lines = [];
  [['From', b.from], ['To', b.to], ['Cc', b.cc], ['Date', b.date],
   ['Subject', b.subject]].forEach(function (pair) {
    if (pair[1]) lines.push(pair[0] + ': ' + pair[1]);
  });
  lines.push('', String(b.body || ''));
  (b.files || []).forEach(function (f, i) {
    if (!i) lines.push('');
    lines.push('Attached: ' + (f.name || 'attachment') + (f.about ? ' (' + f.about + ')' : ''));
  });
  return lines.join('\n');
}

/* ---------- a card that asks before something leaves Rouh -------------

   The buttons at the foot of a card whose tool is about to do something
   outside Rouh (rouh/asking.py): Save to iCloud on a contact today. Petar,
   24 September 2026: "give me a button to save. maybe that should be a
   template card too." So it is a block of its own that any such card ends
   with, and not something the contact card draws for itself.

   A press names the card and the answer and nothing else. What is done is
   read out of the card as the server stored it, so what the buttons do is
   exactly what the card above them shows. When it worked the card comes
   back as `ui`, saved or not saved, without these buttons; when it did not,
   `card_ask_said` says why under them, and they can be pressed again if it
   is worth pressing again. Saying yes out loud answers it the same way. */

function askBlock(b) {
  var node = el('div', 'b-ask');
  var row = el('div', 'ab-row');
  var yes = el('button', 'ab-yes', b.yes || 'Yes');
  yes.type = 'button';
  var no = el('button', 'ab-no', b.no || 'No');
  no.type = 'button';
  row.appendChild(yes);
  row.appendChild(no);
  if (b.hint) row.appendChild(el('span', 'ab-hint', b.hint));
  node.appendChild(row);
  var said = el('p', 'ab-said');
  said.hidden = true;
  said.setAttribute('role', 'status');
  node.appendChild(said);
  function press(choice, button, busy) {
    var card = node.closest('.card');
    var number = card ? card.getAttribute('data-card') : null;
    if (!number) return;
    yes.disabled = no.disabled = true;
    button.classList.add('is-busy');
    button.textContent = busy;
    said.hidden = true;
    if (choice === 'yes' && b.locate) {
      askedLocation(function (given) {
        send({ type: 'card_ask', card: Number(number), choice: choice, given: given });
      });
      return;
    }
    send({ type: 'card_ask', card: Number(number), choice: choice });
  }
  yes.addEventListener('click', function () {
    press('yes', yes, b.locate ? 'Finding you\u2026' : 'Saving\u2026');
  });
  no.addEventListener('click', function () { press('no', no, 'Not saving\u2026'); });
  node.__reset = function (open) {
    yes.disabled = no.disabled = !open;
    yes.classList.remove('is-busy');
    no.classList.remove('is-busy');
    yes.textContent = b.yes || 'Yes';
    no.textContent = b.no || 'No';
  };
  node.__say = function (text) {
    said.textContent = text;
    said.hidden = !text;
  };
  return node;
}

// Share my location, pressed on the card Rouh draws when where the person is
// matters (fr_a3ff524b15c8, `tools._ask_for_location`): the browser's own
// question, then what it answered, handed to `done` to go up with the press.
// A permission already refused is not asked again: the browser would only
// say no once more, so the no is reported without calling it.
function askedLocation(done) {
  var zone = browserZone();
  if (!navigator.geolocation) { done({ failed: 'unsupported', zone: zone }); return; }
  locPermission().then(function (state) {
    if (state === 'denied') { done({ failed: 'denied', zone: zone }); return; }
    // Watched for a while, not asked once: a device that does not know
    // where it is yet says so at once and goes on trying (`locFind`).
    locFind(function (pos, err) {
      if (pos) {
        done({ lat: pos.coords.latitude, lon: pos.coords.longitude,
               accuracy: pos.coords.accuracy, zone: zone });
        return;
      }
      var code = err && err.code;
      done({ failed: code === 1 ? 'denied' : code === 3 ? 'timeout' : 'unavailable',
             zone: zone });
    });
  });
}

// Why a press was not honoured, under the buttons of every copy of that
// card on this page. `again` puts the buttons back, for a press worth making
// again; otherwise they stay pressed, because the question has gone.
function askSaid(card, why, again) {
  var asks = document.querySelectorAll('.card[data-card="' + card + '"] .b-ask');
  for (var i = 0; i < asks.length; i++) {
    if (asks[i].__reset) asks[i].__reset(!!again);
    if (asks[i].__say) asks[i].__say(why || 'That could not be done.');
  }
}

/* ---------- people found on LinkedIn, to pick the one to research -------

   Petar, 26 September 2026 (rouh/linkedin.py): "shows me on screen
   available data to pick which person is the correct one that we should
   research and harvest. Basically image of the face, name, and whatever
   quick information for job is accessible".

   So each person is a row: their face, their name, which opens their
   profile on LinkedIn, the headline under it (nearly always their role and
   company), where they are, and a Research button. The numbers are the
   ones Rouh knows them by, so "the third one" said out loud is the third
   row. A press names the card and the number and nothing else
   (`card_pick`): the server harvests that person, draws their profile as a
   card of its own, and draws this list again with the row saying which card
   that is. What could not be done comes back as `card_pick_said`, said
   under the list. */

// An address a person may be sent to from a card: the open web and nothing
// else.
function webHref(raw) {
  var u;
  try { u = new URL(String(raw || ''), location.href); } catch (err) { return null; }
  return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
}

// A face, or a company's logo, with the initials standing in when there is
// no picture or it will not load. LinkedIn's pictures are signed addresses
// that stop working after a few weeks, so an old card says who it was even
// then.
function personFace(src, name, cls) {
  var face = el('span', cls);
  face.setAttribute('aria-hidden', 'true');
  function initials() {
    face.textContent = contactInitials(name);
    face.classList.add('is-initials');
  }
  var said = pictureSrc(src);
  if (!said) { initials(); return face; }
  var img = document.createElement('img');
  img.alt = '';
  img.setAttribute('referrerpolicy', 'no-referrer');
  img.setAttribute('decoding', 'async');
  var tried = false;
  img.addEventListener('error', function () {
    if (!tried && worthProxying(said)) {
      tried = true;
      img.src = IMAGE_PROXY + encodeURIComponent(said);
      return;
    }
    img.remove();
    initials();
  });
  img.src = said;
  face.appendChild(img);
  return face;
}

// A card by its number, brought into view: out on the canvas at a desk,
// scrolled to on a phone.
function showCardNumbered(no) {
  var card = document.querySelector('.card[data-card="' + no + '"]');
  if (!card) return false;
  var slot = slotOf(card);
  if (card.classList.contains('on-canvas') || (slot && slot.classList.contains('is-folded'))) {
    showOnCanvas(card);
  }
  if (narrow() || !card.classList.contains('on-canvas')) {
    card.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  return true;
}

function peopleBlock(b) {
  var people = Array.isArray(b.people) ? b.people : [];
  if (!people.length) return null;
  var picked = b.picked && typeof b.picked === 'object' ? b.picked : {};
  var node = el('div', 'b-people');
  var list = el('ol', 'pp-list');
  var buttons = [];
  people.forEach(function (p, i) {
    p = p || {};
    var done = picked[String(i)];
    var row = el('li', 'pp-row' + (done ? ' is-picked' : ''));
    row.appendChild(el('span', 'pp-no', String(i + 1)));
    row.appendChild(personFace(p.photo, p.name, 'pp-face'));
    var who = el('div', 'pp-who');
    var href = webHref(p.url);
    /** @type {any} */
    var name = el(href ? 'a' : 'span', 'pp-name', p.name || 'No name');
    if (href) {
      name.href = href;
      name.target = '_blank';
      name.rel = 'noopener noreferrer';
      name.title = 'Their profile on LinkedIn';
    }
    who.appendChild(name);
    if (p.headline) who.appendChild(el('div', 'pp-headline', p.headline));
    if (p.location) who.appendChild(el('div', 'pp-where', p.location));
    // A meeting's guests (rouh/meeting_people.py): a line of background, and
    // where Rouh stands with them when it is not simply found.
    if (p.about) who.appendChild(el('div', 'pp-about', p.about));
    if (p.note) who.appendChild(el('div', 'pp-note', p.note));
    row.appendChild(who);
    var act = el('div', 'pp-act');
    if (done) {
      var shown = el('button', 'pp-done', 'Researched · #' + done);
      shown.type = 'button';
      shown.title = 'Their profile is card ' + done;
      shown.addEventListener('click', function () { showCardNumbered(done); });
      act.appendChild(shown);
    } else if (b.token) {
      var go = el('button', 'pp-go', 'Research');
      go.type = 'button';
      go.setAttribute('aria-label', 'Research number ' + (i + 1) + ', ' + (p.name || ''));
      go.addEventListener('click', function () { press(i, go); });
      buttons.push(go);
      act.appendChild(go);
    }
    row.appendChild(act);
    list.appendChild(row);
  });
  node.appendChild(list);
  var said = el('p', 'pp-said');
  said.hidden = true;
  said.setAttribute('role', 'status');
  node.appendChild(said);
  if (buttons.length) node.appendChild(el('p', 'pp-hint', 'Or say which one.'));
  function press(i, button) {
    var card = node.closest('.card');
    var number = card ? card.getAttribute('data-card') : null;
    if (!number) return;
    buttons.forEach(function (x) { x.disabled = true; });
    button.classList.add('is-busy');
    button.textContent = 'Researching…';
    said.hidden = true;
    send({ type: 'card_pick', card: Number(number), pick: i });
  }
  // Why a press was not done. `again` puts every button back; without it
  // the list is spent - too old, or not this person's - and says so.
  node.__said = function (why, again) {
    buttons.forEach(function (x) {
      x.disabled = !again;
      x.classList.remove('is-busy');
      x.textContent = 'Research';
    });
    said.textContent = why || 'That could not be done.';
    said.hidden = false;
  };
  return node;
}

function pickSaid(card, why, again) {
  var lists = document.querySelectorAll('.card[data-card="' + card + '"] .b-people');
  for (var i = 0; i < lists.length; i++) if (lists[i].__said) lists[i].__said(why, again);
}

/* ---------- one person's LinkedIn profile, harvested -------------------

   Laid out the way the HR project's Lookup page lays out the person it was
   first written for: who they are at the top, then About, Experience,
   Education and Skills, and their latest posts, with the few things that
   page leaves out and a researcher wants - certifications, languages, what
   others wrote about them. Long passages open on a press rather than
   filling the canvas; everything was harvested and is all here. */

var PROFILE_POSTS_SHOWN = 3;

/* One post on a profile card, saying first how it stands to the person whose
   profile it is: their own post, a repost with or without their own comment,
   a comment or a reaction on somebody else's, or authorship unknown
   (`linkedin.label`). Their own words are drawn plain and the original
   author's in a quote under that author's name, so the two never read as
   one. A card harvested before 5 October 2026 has no relation on its posts:
   only a repost with words of its own was told apart then, so the rest are
   drawn as of unknown authorship rather than as theirs. */
var PF_RELATIONS = {
  own: 'Own post', repost: 'Reposted, no comment of their own',
  quote: 'Reposted with own comment', commented: 'Commented on', liked: 'Liked',
  reacted: 'Reacted to', other: "Somebody else's post, listed without saying why",
  unknown: 'Authorship unknown'
};

function pfPost(p) {
  p = p || {};
  var rel = p.relation;
  var mine = p.text || '';
  var theirs = p.original_text || '';
  var by = p.original_author || '';
  if (!PF_RELATIONS[rel]) {
    rel = p.repost_of ? (mine ? 'quote' : 'repost') : 'unknown';
    if (p.repost_of) { by = p.repost_of; theirs = p.repost_text || ''; }
    else { theirs = mine; mine = ''; }
  }
  var post = el('article', 'pf-post');
  post.dataset.relation = rel;
  var tag = el('div', 'pf-rel');
  var said = PF_RELATIONS[rel];
  if (rel === 'reacted' && p.reaction) said += ' (' + p.reaction + ')';
  tag.appendChild(el('span', 'pf-rel-kind', said));
  if (rel !== 'own' && rel !== 'unknown') {
    tag.appendChild(el('span', null, ' · ' + (p.original_is_owner ? 'their own post'
      : (rel === 'commented' || rel === 'liked' || rel === 'reacted' ? 'a post by '
        : 'original by '))));
    if (!p.original_is_owner) {
      tag.appendChild(pfLink(by || 'an author LinkedIn did not name',
        p.original_author_url, 'pf-co pf-rel-by'));
    }
  }
  post.appendChild(tag);
  if (mine) post.appendChild(pfLong(mine, '', 360));
  if (theirs) {
    var quote = el('div', 'pf-orig');
    if (rel !== 'own') {
      quote.appendChild(el('div', 'pf-orig-by', (rel === 'unknown' || !by)
        ? 'Author not given by LinkedIn' : by + ' wrote'));
    }
    quote.appendChild(pfLong(theirs, 'pf-quote', 240));
    post.appendChild(quote);
  }
  var pics = Array.isArray(p.images) ? p.images : [];
  if (pics.length) {
    var row = el('div', 'pf-pics');
    pics.forEach(function (src) {
      var at = pictureSrc(src);
      if (!at) return;
      var img = document.createElement('img');
      img.alt = '';
      img.setAttribute('referrerpolicy', 'no-referrer');
      img.setAttribute('decoding', 'async');
      img.loading = 'lazy';
      img.addEventListener('error', function () { img.remove(); });
      img.src = at;
      row.appendChild(img);
    });
    post.appendChild(row);
  }
  var meta = el('div', 'pf-post-meta');
  var when = p.date || p.ago;
  if (when) meta.appendChild(el('span', null, when));
  if (rel !== 'liked' && rel !== 'reacted') {
    meta.appendChild(el('span', null, (p.likes || 0) + ' likes · ' + (p.comments || 0)
      + ' comments'));
  }
  if (webHref(p.url)) meta.appendChild(pfLink('View on LinkedIn ↗', p.url, 'pf-view'));
  post.appendChild(meta);
  return post;
}

// A list of posts in a section, the first few shown and the rest a press away.
function pfPosts(sec, posts, noun) {
  var hidden = [];
  posts.forEach(function (p, i) {
    var post = pfPost(p);
    if (i >= PROFILE_POSTS_SHOWN) {
      post.hidden = true;
      hidden.push(post);
    }
    sec.appendChild(post);
  });
  if (hidden.length) {
    var all = el('button', 'pf-more', 'Show all ' + posts.length + ' ' + noun);
    all.type = 'button';
    all.addEventListener('click', function () {
      hidden.forEach(function (x) { x.hidden = false; });
      all.remove();
    });
    sec.appendChild(all);
  }
}

function pfSection(title, count) {
  var box = el('section', 'pf-sec');
  box.appendChild(el('h5', 'pf-title', title + (count ? ' (' + count + ')' : '')));
  return box;
}

// Somebody's own words, their lines kept, folded past `most` characters.
function pfLong(text, cls, most) {
  var wrap = el('div', 'pf-longwrap');
  var body = el('div', 'pf-long' + (cls ? ' ' + cls : ''), text);
  wrap.appendChild(body);
  if (String(text || '').length > most) {
    body.classList.add('is-clamped');
    var more = el('button', 'pf-more', 'Show more');
    more.type = 'button';
    more.addEventListener('click', function () {
      var open = body.classList.toggle('is-clamped') === false;
      more.textContent = open ? 'Show less' : 'Show more';
    });
    wrap.appendChild(more);
  }
  return wrap;
}

function pfLink(text, raw, cls) {
  // No address is no link: an empty one would resolve to this very page.
  var href = String(raw || '').trim() ? webHref(raw) : null;
  /** @type {any} */
  var a = el(href ? 'a' : 'span', cls, text);
  if (href) {
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
  }
  return a;
}

function pfItem(logo, logoName) {
  var item = el('div', 'pf-item');
  item.appendChild(personFace(logo, logoName, 'pf-logo'));
  var body = el('div', 'pf-item-body');
  item.appendChild(body);
  return { item: item, body: body };
}

function profileBlock(b) {
  var node = el('div', 'b-profile');
  var head = el('div', 'pf-head');
  head.appendChild(personFace(b.photo, b.name, 'pf-face'));
  var who = el('div', 'pf-who');
  who.appendChild(el('div', 'pf-name', b.name || 'No name'));
  if (b.headline) who.appendChild(el('div', 'pf-headline', b.headline));
  if (b.location) who.appendChild(el('div', 'pf-where', b.location));
  var facts = Array.isArray(b.facts) ? b.facts : [];
  if (facts.length) {
    var factRow = el('div', 'pf-facts');
    facts.forEach(function (f) { factRow.appendChild(el('span', 'pf-fact', f)); });
    who.appendChild(factRow);
  }
  head.appendChild(who);
  if (webHref(b.url)) head.appendChild(pfLink('LinkedIn ↗', b.url, 'pf-open'));
  node.appendChild(head);

  var sec;
  if (b.about) {
    sec = pfSection('About');
    sec.appendChild(pfLong(b.about, '', 420));
    node.appendChild(sec);
  }

  var jobs = Array.isArray(b.experience) ? b.experience : [];
  if (jobs.length) {
    sec = pfSection('Experience', jobs.length);
    jobs.forEach(function (job) {
      job = job || {};
      var one = pfItem(job.logo, job.company || job.title);
      one.body.appendChild(el('div', 'pf-item-title', job.title || job.company || ''));
      var sub = el('div', 'pf-item-sub');
      if (job.company) sub.appendChild(pfLink(job.company, job.company_url, 'pf-co'));
      if (job.location) sub.appendChild(el('span', null, (job.company ? ' · ' : '') + job.location));
      if (sub.childNodes.length) one.body.appendChild(sub);
      var when = [job.dates, job.duration, job.kind].filter(Boolean).join(' · ');
      if (when) one.body.appendChild(el('div', 'pf-item-when', when));
      if (job.description) one.body.appendChild(pfLong(job.description, 'pf-desc', 240));
      sec.appendChild(one.item);
    });
    node.appendChild(sec);
  }

  var schools = Array.isArray(b.education) ? b.education : [];
  if (schools.length) {
    sec = pfSection('Education', schools.length);
    schools.forEach(function (s) {
      s = s || {};
      var one = pfItem(s.logo, s.school);
      one.body.appendChild(el('div', 'pf-item-title', s.school || ''));
      if (s.degree) one.body.appendChild(el('div', 'pf-item-sub', s.degree));
      if (s.dates) one.body.appendChild(el('div', 'pf-item-when', s.dates));
      sec.appendChild(one.item);
    });
    node.appendChild(sec);
  }

  var skills = Array.isArray(b.skills) ? b.skills : [];
  if (skills.length) {
    sec = pfSection('Skills', skills.length);
    var chips = el('div', 'pf-chips');
    skills.forEach(function (s) { chips.appendChild(el('span', 'pf-chip', s)); });
    sec.appendChild(chips);
    node.appendChild(sec);
  }

  var certs = Array.isArray(b.certifications) ? b.certifications : [];
  if (certs.length) {
    sec = pfSection('Certifications', certs.length);
    var certList = el('ul', 'pf-plain');
    certs.forEach(function (c) {
      c = c || {};
      var li = el('li');
      li.appendChild(el('span', 'pf-item-title', c.title || ''));
      var by = [c.by, c.when].filter(Boolean).join(' · ');
      if (by) li.appendChild(el('span', 'pf-item-when', ' ' + by));
      certList.appendChild(li);
    });
    sec.appendChild(certList);
    node.appendChild(sec);
  }

  var langs = Array.isArray(b.languages) ? b.languages : [];
  if (langs.length) {
    sec = pfSection('Languages');
    sec.appendChild(el('div', 'pf-item-sub', langs.join(' · ')));
    node.appendChild(sec);
  }

  var recs = Array.isArray(b.recommendations) ? b.recommendations : [];
  if (recs.length) {
    sec = pfSection('Recommendations', recs.length);
    recs.forEach(function (r) {
      r = r || {};
      var box = el('div', 'pf-rec');
      box.appendChild(pfLong(r.text || '', 'pf-quote', 280));
      var by = el('div', 'pf-item-when');
      by.appendChild(pfLink(r.by || 'Somebody', r.by_url, 'pf-co'));
      var more = [r.headline, r.when].filter(Boolean).join(' · ');
      if (more) by.appendChild(el('span', null, ' · ' + more));
      box.appendChild(by);
      sec.appendChild(box);
    });
    node.appendChild(sec);
  }

  var posts = Array.isArray(b.posts) ? b.posts : [];
  if (posts.length) {
    sec = pfSection('Latest posts and reposts', posts.length);
    pfPosts(sec, posts, 'posts');
    node.appendChild(sec);
  } else if (b.posts_said || b.posts_read) {
    sec = pfSection('Latest posts and reposts');
    sec.appendChild(el('p', 'pf-note',
      b.posts_said || 'No posts or reposts of theirs were found.'));
    node.appendChild(sec);
  }

  // Their comments and likes on other people's posts, which LinkedIn's
  // posts listing never holds (rouh/linkedin.py, `_activity`).
  var acts = Array.isArray(b.activity) ? b.activity : [];
  if (acts.length) {
    sec = pfSection('Comments and reactions', acts.length);
    pfPosts(sec, acts, 'comments and reactions');
    node.appendChild(sec);
  } else if (b.activity_said) {
    sec = pfSection('Comments and reactions');
    sec.appendChild(el('p', 'pf-note', b.activity_said));
    node.appendChild(sec);
  }

  if (b.harvested) {
    node.appendChild(el('p', 'pf-foot', 'Harvested from LinkedIn through HarvestAPI on '
      + new Date(b.harvested * 1000).toLocaleDateString(undefined,
        { day: 'numeric', month: 'long', year: 'numeric' }) + '.'));
  }
  return node;
}

/* ---------- a card the person writes in, with the button that sends it ----

   The second template card (rouh/composing.py), beside the one that asks.
   Petar, 24 September 2026, after Rouh drafted a reply and showed it in a
   card: "when you draft an email and show it in a card, it needs to be a
   card that is dynamic. It should be editable, so I can change the text,
   have a send button. Once I send it, it should say sent and not be editable
   anymore."

   So it is a small compose window that happens to live in the conversation.
   The lines at the top are ordinary inputs, the body is contenteditable with
   the handful of formatting buttons a person actually uses, the files going
   with it are chips, and the one button sends it.

   What they type is saved as they type it, a second or so after they stop,
   so a reload or the phone in the other room finds the card as they left it
   and nothing written is ever lost to a closed tab. A save redraws nothing:
   the card must not move under the cursor of the person writing in it.

   Once it has gone the whole block comes back from the server in its sent
   state - the same words, as text rather than as fields, with no button and
   no way to press one - so what the card says always follows what actually
   happened, which is the thing that was wrong before. */

// How long after the last keystroke the card is saved.
var COMPOSE_SAVE_MS = 1200;

// `own` is a compose form that belongs to another card rather than to a
// stored compose block: the inbox card's Reply, Reply all and Forward. It
// carries `label` for the chip at the top, `send(edits, node)` for the
// button, and `cancel()` for the Cancel beside it. Such a form is never
// saved as it is typed, because nothing is stored until it is sent.
function composeBlock(b, cardId, own) {
  var node = el('div', 'b-compose');
  // Done with, and nothing left to press: sent, or not sent because another
  // draft of the same email went instead and this one left Gmail's Drafts.
  var notSent = b.state === 'not_sent';
  var sent = b.state === 'sent' || notSent;
  if (sent) node.classList.add('is-sent');
  if (notSent) node.classList.add('is-not-sent');

  var head = el('div', 'cp-head');
  head.appendChild(el('span', 'cp-state' + (notSent ? ' is-not-sent' : sent ? ' is-sent' : ' is-draft'),
                      notSent ? 'Not sent' : sent ? 'Sent' : (own && own.label) || 'Draft'));
  // The time it went is drawn here rather than written into the words on the
  // server, so it is on the same clock as the time in the card's own head.
  if (b.said) {
    head.appendChild(el('span', 'cp-when',
                        b.said + (b.at ? ' at ' + clockOf(b.at) : '')));
  }
  node.appendChild(head);
  // What became of the rest once it went, so the card says what Gmail now
  // shows: the conversation archived, another draft of it out of Drafts.
  if (sent && b.after) node.appendChild(el('p', 'cp-after', b.after));

  var fields = Array.isArray(b.fields) ? b.fields : [];
  var boxes = {};
  var rows = el('div', 'cp-fields');
  var hidden = [], names = [];
  for (var i = 0; i < fields.length; i++) {
    (function (f) {
      var name = String(f.name || '');
      var row = el('label', 'cp-field');
      row.appendChild(el('span', 'cp-label', f.label || name));
      if (sent) {
        if (!String(f.value || '').trim()) return;
        row.appendChild(el('span', 'cp-value', f.value));
      } else {
        var box = el('input', 'cp-input');
        box.type = 'text';
        box.value = f.value == null ? '' : String(f.value);
        box.setAttribute('aria-label', f.label || name);
        box.addEventListener('input', touched);
        box.addEventListener('blur', saveNow);
        boxes[name] = box;
        row.appendChild(box);
        // Cc and Bcc are out of the way until there is something in them or
        // the person asks for them, which is what every compose window does.
        if ((name === 'cc' || name === 'bcc') && !box.value.trim()) {
          row.hidden = true;
          hidden.push(row);
          names.push(f.label || name);
        }
      }
      rows.appendChild(row);
    }(fields[i] || {}));
  }
  node.appendChild(rows);
  if (hidden.length) {
    // Named for what is actually behind it: with a Cc already filled in, a
    // button saying "Cc, Bcc" offers something that is on the screen.
    var more = el('button', 'cp-more', names.join(', '));
    more.type = 'button';
    more.addEventListener('click', function () {
      for (var h = 0; h < hidden.length; h++) hidden[h].hidden = false;
      more.remove();
      var first = hidden[0] && hidden[0].querySelector('input');
      if (first) first.focus();
    });
    node.appendChild(more);
  }

  // --- the body, and the formatting a person actually uses -----------------

  var body = el('div', 'cp-body');
  body.innerHTML = b.body || '';
  if (sent) {
    body.setAttribute('aria-label', 'What was sent');
  } else {
    body.contentEditable = 'true';
    body.setAttribute('role', 'textbox');
    body.setAttribute('aria-multiline', 'true');
    body.setAttribute('aria-label', 'The message');
    body.addEventListener('input', touched);
    body.addEventListener('blur', saveNow);
    node.appendChild(formatting());
  }
  node.appendChild(body);

  function formatting() {
    var bar = el('div', 'cp-tools');
    var keep = null;
    [['Bold', 'bold', 'B'], ['Italic', 'italic', 'I'],
     ['Bulleted list', 'insertUnorderedList', '•'],
     ['Numbered list', 'insertOrderedList', '1.']].forEach(function (one) {
      var btn = el('button', 'cp-tool cp-' + one[1], one[2]);
      btn.type = 'button';
      btn.title = one[0];
      btn.setAttribute('aria-label', one[0]);
      // The selection has to survive the press, and a button that takes
      // focus takes it with it.
      btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
      btn.addEventListener('click', function () {
        body.focus();
        try { document.execCommand('styleWithCSS', false, 'false'); } catch (e) {}
        try { document.execCommand(one[1], false, null); } catch (e) {}
        touched();
      });
      bar.appendChild(btn);
    });
    var link = el('button', 'cp-tool cp-link', 'Link');
    link.type = 'button';
    link.title = 'Make the selected words a link';
    link.addEventListener('mousedown', function (e) { e.preventDefault(); });
    var where = el('div', 'cp-where');
    where.hidden = true;
    var url = el('input', 'cp-url');
    url.type = 'url';
    url.placeholder = 'https://';
    url.setAttribute('aria-label', 'Where the link goes');
    var add = el('button', 'cp-add', 'Add link');
    add.type = 'button';
    where.appendChild(url);
    where.appendChild(add);
    link.addEventListener('click', function () {
      // The words that were selected, kept while the cursor is in the box.
      var sel = window.getSelection && window.getSelection();
      keep = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
      where.hidden = !where.hidden;
      if (!where.hidden) url.focus();
    });
    add.addEventListener('click', function () {
      var href = url.value.trim();
      if (!href) return;
      if (!/^(https?:|mailto:|tel:)/i.test(href)) href = 'https://' + href;
      body.focus();
      if (keep && window.getSelection) {
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(keep);
      }
      try { document.execCommand('createLink', false, href); } catch (e) {}
      url.value = '';
      where.hidden = true;
      touched();
    });
    url.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); add.click(); }
    });
    bar.appendChild(link);
    bar.appendChild(where);
    return bar;
  }

  // --- what is going with it ----------------------------------------------

  var files = (b.attachments || []).map(function (f) {
    return { id: String(f.id || ''), name: String(f.name || ''), size: f.size || 0 };
  });
  var chips = el('div', 'cp-files');
  node.appendChild(chips);
  drawFiles();

  function drawFiles() {
    chips.textContent = '';
    chips.hidden = !files.length;
    files.forEach(function (f, n) {
      var chip = el('span', 'cp-file');
      chip.appendChild(el('span', 'cp-file-name', f.name));
      if (f.size) chip.appendChild(el('span', 'cp-file-size', attSize(f.size)));
      if (!sent) {
        var off = el('button', 'cp-file-x', '×');
        off.type = 'button';
        off.title = 'Take ' + f.name + ' off this message';
        off.setAttribute('aria-label', 'Take ' + f.name + ' off this message');
        off.addEventListener('click', function () {
          files.splice(n, 1);
          drawFiles();
          node.__dirty = true;
          saveNow();
        });
        chip.appendChild(off);
      }
      chips.appendChild(chip);
    });
  }

  // --- the button ----------------------------------------------------------

  var said = el('p', 'cp-said');
  said.hidden = true;
  said.setAttribute('role', 'status');

  if (!sent) {
    var row = el('div', 'cp-row');
    var go = el('button', 'cp-send', b.send || 'Send');
    go.type = 'button';
    row.appendChild(go);
    if (own && own.cancel) {
      var cancel = el('button', 'cp-cancel', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', function () { own.cancel(); });
      row.appendChild(cancel);
    }
    var picker = null;
    if (b.can_attach) {
      var clip = el('button', 'cp-attach', 'Attach a file');
      clip.type = 'button';
      row.appendChild(clip);
      picker = el('input', 'cp-picker');
      picker.type = 'file';
      picker.multiple = true;
      picker.hidden = true;
      row.appendChild(picker);
      clip.addEventListener('click', function () { picker.click(); });
      picker.addEventListener('change', function () {
        var list = picker.files ? Array.prototype.slice.call(picker.files) : [];
        picker.value = '';
        list.forEach(attach);
      });
    }
    if (b.hint) row.appendChild(el('span', 'cp-hint', b.hint));
    var kept = el('span', 'cp-kept', 'Saved');
    kept.hidden = true;
    row.appendChild(kept);
    node.appendChild(row);
    node.appendChild(said);

    go.addEventListener('click', function () {
      if (!own && !number()) return;
      go.disabled = true;
      go.classList.add('is-busy');
      go.textContent = 'Sending…';
      said.hidden = true;
      clearTimeout(node.__timer);
      if (own) own.send(edits(), node);
      else send({ type: 'card_compose', card: number(), do: 'send', edits: edits() });
    });

    node.__reset = function (open) {
      go.disabled = !open;
      go.classList.remove('is-busy');
      go.textContent = b.send || 'Send';
    };
    node.__say = function (text) {
      said.textContent = text;
      said.hidden = !text;
    };
    node.__kept = function () {
      kept.hidden = false;
      clearTimeout(node.__keptTimer);
      node.__keptTimer = setTimeout(function () { kept.hidden = true; }, 2000);
    };
  } else {
    node.appendChild(said);
  }

  function attach(file) {
    if (!S.sessionId) return;
    var chip = { id: '', name: file.name, size: file.size, going: true };
    files.push(chip);
    drawFiles();
    var form = new FormData();
    form.append('file', file, file.name);
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/attachments/' + encodeURIComponent(S.sessionId));
    xhr.onload = function () {
      var answer = {};
      try { answer = JSON.parse(xhr.responseText) || {}; } catch (e) {}
      if (xhr.status >= 200 && xhr.status < 300 && answer.id) {
        chip.id = answer.id;
        chip.size = answer.size || chip.size;
        chip.going = false;
        drawFiles();
        // A file put on the card is a change to the card, exactly as typing
        // in it is: without this the chip was on the screen and gone again
        // after a reload, because nothing had been saved.
        node.__dirty = true;
        saveNow();
      } else {
        files.splice(files.indexOf(chip), 1);
        drawFiles();
        if (node.__say) node.__say(answer.error || 'That file could not be attached.');
      }
    };
    xhr.onerror = function () {
      files.splice(files.indexOf(chip), 1);
      drawFiles();
      if (node.__say) node.__say('That file did not reach the server.');
    };
    xhr.send(form);
  }

  function number() {
    var card = node.closest('.card');
    var n = card ? card.getAttribute('data-card') : null;
    return n ? Number(n) : (cardId ? Number(cardId) : 0);
  }

  function edits() {
    var out = { fields: {}, body: body.innerHTML, attachments: [] };
    for (var name in boxes) {
      if (Object.prototype.hasOwnProperty.call(boxes, name)) out.fields[name] = boxes[name].value;
    }
    files.forEach(function (f) { if (f.id) out.attachments.push({ id: f.id, name: f.name }); });
    return out;
  }

  function touched() {
    node.__dirty = true;
    if (own) return;
    clearTimeout(node.__timer);
    node.__timer = setTimeout(saveNow, COMPOSE_SAVE_MS);
  }

  function saveNow() {
    clearTimeout(node.__timer);
    if (own || sent || !node.__dirty || !number()) return;
    node.__dirty = false;
    send({ type: 'card_compose', card: number(), do: 'save', edits: edits() });
  }

  // What is on the form, for whoever holds it: the inbox card puts the
  // caret where the person writes.
  node.__body = body;
  node.__boxes = boxes;
  return node;
}

// Why a press on a compose card was not honoured, under the button of every
// copy of that card on this page. `again` puts the button back, which is
// almost always: a send that failed leaves the card exactly as the person
// wrote it, and the whole point is that they can press it again.
function composeSaid(card, why, again) {
  var found = document.querySelectorAll('.card[data-card="' + card + '"] .b-compose');
  for (var i = 0; i < found.length; i++) {
    if (found[i].__reset) found[i].__reset(!!again);
    if (found[i].__say) found[i].__say(why || 'That could not be sent.');
  }
}

// Their words, kept. Said quietly and briefly: it is a reassurance, not news.
function composeKept(card) {
  var found = document.querySelectorAll('.card[data-card="' + card + '"] .b-compose');
  for (var i = 0; i < found.length; i++) if (found[i].__kept) found[i].__kept();
}

/* ---------- the inbox, as a card the person works through --------------

   The third template card (rouh/inbox.py), asked for on 25 September 2026:
   "a real inbox widget on the screen with working mail actions: Archive,
   Reply, Reply all and Forward." An html block could draw an inbox, and
   nothing on it could reach the mailbox, because an html block is drawn in
   a sandbox.

   The card holds no mail. It asks the server for the inbox when it first
   comes into view and whenever Refresh is pressed (`card_inbox`, answered
   by `card_inbox_said` with the page's own `rid`), so it is never a picture
   of the inbox as it was. It has three faces and shows one at a time: the
   list; one message as a page of its own, with Back at the top and the
   bottom and Newer and Older to step through; and the form a Reply, Reply
   all or Forward opens, which is the draft card's compose form with Cancel
   beside Send. What the person does from it is done in their mailbox by the
   server and told to the conversation, the way the draft card's Send is.

   Opening a message here marks it read in Gmail, as opening it in Gmail
   does; Mark unread puts it back. A reply or a forward sent from here
   archives the conversation, so the card goes back to its list without it
   (Petar, 26 September 2026). */

// The asks waiting on an answer, by the id the page gave each one.
var INBOX_ASKED = {};
var inboxSeq = 0;
// A list older than this is read again when its card comes back into view.
var INBOX_STALE_MS = 120000;
// How long an ask may wait before the card says it got no answer.
var INBOX_WAIT_MS = 60000;

function inboxAsk(token, what, extra, done) {
  var rid = 'inbox-' + (++inboxSeq);
  /** @type {import('./protocol').ToServer<'card_inbox'>} */
  var msg = { type: 'card_inbox', token: token, do: what, rid: rid };
  for (var k in extra) if (Object.prototype.hasOwnProperty.call(extra, k)) msg[k] = extra[k];
  INBOX_ASKED[rid] = done;
  if (!send(msg)) {
    delete INBOX_ASKED[rid];
    done({ ok: false, why: 'Rouh is not connected right now. Try again in a moment.' });
    return;
  }
  setTimeout(function () {
    if (!INBOX_ASKED[rid]) return;
    delete INBOX_ASKED[rid];
    done({ ok: false, why: 'The mailbox did not answer. Try again.' });
  }, INBOX_WAIT_MS);
}

// The answer to one ask, to the card that asked it.
/** @param {import('./protocol').FromServer<'card_inbox_said'>} m */
function inboxSaid(m) {
  var done = INBOX_ASKED[m.rid];
  if (!done) return;
  delete INBOX_ASKED[m.rid];
  done(m);
}

// A message changed on another card or another screen of this person's:
// every inbox card on this page follows.
/** @param {import('./protocol').FromServer<'card_inbox_changed'>} m */
function inboxChanged(m) {
  var found = document.querySelectorAll('.b-inbox');
  for (var i = 0; i < found.length; i++) if (found[i].__changed) found[i].__changed(m);
}

// The socket went, and every ask on it with it: say so now rather than a
// minute later.
function inboxLost() {
  var waiting = INBOX_ASKED;
  INBOX_ASKED = {};
  for (var rid in waiting) {
    if (Object.prototype.hasOwnProperty.call(waiting, rid)) {
      waiting[rid]({ ok: false, why: 'The connection to Rouh dropped. Try again.' });
    }
  }
}

// The same line the server writes (`inbox.counted`), for after a message has
// been archived or marked here and the numbers have moved.
function inboxCounted(total, unread, query, shown, more) {
  var of = query ? shown : total;
  var u = !unread ? 'none unread' : unread === of ? 'all unread' : unread + ' unread';
  if (query) {
    if (!shown) return 'Nothing in the inbox matches ' + query;
    return (more ? 'the newest ' + shown : String(shown)) + ' in the inbox matching ' +
      query + ', ' + u;
  }
  if (!total) return 'Nothing in the inbox';
  return total + ' in the inbox, ' + u;
}

// Words with their web addresses made into links that open a new tab.
function inboxWords(node, text) {
  var re = /https?:\/\/[^\s<>"')\]]+/g;
  var at = 0, m;
  text = String(text || '');
  while ((m = re.exec(text))) {
    var href = m[0].replace(/[.,;:!?]+$/, '');
    if (m.index > at) node.appendChild(document.createTextNode(text.slice(at, m.index)));
    var a = el('a', null, href);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    node.appendChild(a);
    at = m.index + href.length;
    re.lastIndex = at;
  }
  if (at < text.length) node.appendChild(document.createTextNode(text.slice(at)));
}

// The card's top, brought into view in whatever it scrolls in, when it has
// changed face and the top is where the person reads from.
function inboxToTop(node) {
  var p = node.parentElement;
  while (p && p !== document.body) {
    var over = getComputedStyle(p).overflowY;
    if ((over === 'auto' || over === 'scroll') && p.scrollHeight > p.clientHeight) {
      var top = node.getBoundingClientRect().top - p.getBoundingClientRect().top;
      if (top < 0 || top > p.clientHeight * 0.6) p.scrollTop += top - 8;
      return;
    }
    p = p.parentElement;
  }
}

function inboxButton(cls, text, title) {
  var b = el('button', 'ib-btn ' + cls, text);
  b.type = 'button';
  if (title) b.title = title;
  return b;
}

function inboxBlock(b) {
  var node = el('div', 'b-inbox');
  var token = String(b.token || '');
  // One of the person's own inboxes, connected read-only (`rouh/inboxes.py`):
  // it lists and opens mail, and has nothing on it that would change any.
  var readOnly = !!b.read_only;
  if (readOnly) node.classList.add('is-read-only');
  var st = { rows: [], total: 0, unread: 0, query: String(b.query || ''), more: false,
             loaded: 0, loading: false, pos: -1, open: null, face: 'list' };

  // --- the list ------------------------------------------------------------

  var list = el('div', 'ib-list');
  var head = el('div', 'ib-head');
  var count = el('span', 'ib-count', 'Reading the inbox…');
  count.setAttribute('role', 'status');
  var refresh = inboxButton('ib-refresh', 'Refresh', 'Read the inbox again');
  head.appendChild(count);
  head.appendChild(refresh);
  list.appendChild(head);
  if (readOnly) {
    list.appendChild(el('p', 'ib-whose', (b.address ? b.address + ' is ' : 'This inbox is ') +
      'connected read-only: Rouh reads it, and nothing here changes it in Gmail.'));
  }
  var listSaid = el('p', 'ib-said');
  listSaid.hidden = true;
  listSaid.setAttribute('role', 'status');
  list.appendChild(listSaid);
  var rows = el('ul', 'ib-rows');
  rows.setAttribute('aria-label', 'The inbox, newest first');
  list.appendChild(rows);
  var foot = el('p', 'ib-foot');
  foot.hidden = true;
  list.appendChild(foot);
  node.appendChild(list);

  // --- one message, as a page of its own ----------------------------------

  var mail = el('div', 'ib-mail');
  mail.hidden = true;
  function navRow(where) {
    var nav = el('div', 'ib-nav ib-nav-' + where);
    var back = inboxButton('ib-back', '← Back to the inbox');
    var newer = inboxButton('ib-newer', 'Newer', 'The message that came after this one');
    var older = inboxButton('ib-older', 'Older', 'The message that came before this one');
    back.addEventListener('click', showList);
    newer.addEventListener('click', function () { step(-1); });
    older.addEventListener('click', function () { step(1); });
    nav.appendChild(back);
    var turn = el('span', 'ib-turn');
    turn.appendChild(newer);
    turn.appendChild(older);
    nav.appendChild(turn);
    nav.__newer = newer;
    nav.__older = older;
    return nav;
  }
  var navTop = navRow('top');
  var navBottom = navRow('bottom');
  var subject = el('h3', 'ib-subject');
  var heads = el('dl', 'ib-heads');
  var acts = el('div', 'ib-acts');
  var archive = inboxButton('ib-archive', 'Archive', 'Take it out of the inbox, keeping it in the mailbox');
  var reply = inboxButton('ib-reply', 'Reply');
  var replyAll = inboxButton('ib-replyall', 'Reply all');
  var forward = inboxButton('ib-forward', 'Forward');
  var marker = inboxButton('ib-mark', 'Mark read');
  [archive, reply, replyAll, forward, marker].forEach(function (x) { acts.appendChild(x); });
  // Unsubscribe in the inbox card (night 34, rouh/inbox_unsubscribe.py): only on mail from a
  // list, and on a read-only inbox too, as it asks the sender and changes nothing in the mailbox.
  var unsubRow = el('div', 'ib-unsub');
  unsubRow.hidden = true;
  // Remind me about this email (night 34, rouh/inbox_remind.py): a reminder on Clockwork at a
  // time, on a read-only inbox too, as nothing in the mailbox changes.
  var remindRow = el('div', 'ib-remind');
  remindRow.hidden = true;
  // You meet them soon (night 36, rouh/meeting_soon.py): a meeting in the next days with the sender
  // or somebody else on the email, said under its headers, with Open the meeting.
  var soonRow = el('div', 'ib-soon');
  soonRow.hidden = true;
  // Also waiting on you (night 36, rouh/waiting_too.py): the sender's other conversations whose last
  // word is still theirs, said under the headers, each with Open.
  var tooRow = el('div', 'ib-soon ib-too');
  tooRow.hidden = true;
  // How you know them (night 38, rouh/know_them.py): a sender back after months, with when you last
  // and first wrote and who introduced you, said under the headers with Open the last and Open the first.
  var knowRow = el('div', 'ib-soon ib-know');
  knowRow.hidden = true;
  // If it does not come (night 36, rouh/promise_watch.py): on an email promising something by a day,
  // one press has Rouh look for it the morning after and say only if nothing came.
  var watchRow = el('div', 'ib-remind ib-watch');
  watchRow.hidden = true;
  // If I have not answered it, remind me (night 37, rouh/answer_watch.py): on an email asking him
  // something, one press has Rouh look the next working morning and remind him only if he has not answered.
  var answerRow = el('div', 'ib-remind ib-answer-watch');
  answerRow.hidden = true;
  // Save them as a contact (night 39, rouh/save_sender.py): a sender not in the contacts, with what
  // saving them would add, and one press that saves them to iCloud.
  var saveRow = el('div', 'ib-remind ib-save-sender');
  saveRow.hidden = true;
  // A contact card in an email (night 40, rouh/card_in_mail.py): whose card the email carries, what it
  // holds, and one press that saves it to iCloud, onto the contact already there when there is one.
  var cardRow = el('div', 'ib-remind ib-card-in-mail');
  cardRow.hidden = true;
  // Call them from their email (night 41, rouh/call_sender.py): the sender's numbers, mobile first,
  // each a tel: link the phone rings in one press.
  var callRow = el('div', 'ib-remind ib-call');
  callRow.hidden = true;
  var mailSaid = el('p', 'ib-said');
  mailSaid.hidden = true;
  mailSaid.setAttribute('role', 'status');
  var body = el('div', 'ib-body');
  var files = el('div', 'ib-files');
  files.hidden = true;
  mail.appendChild(navTop);
  mail.appendChild(subject);
  mail.appendChild(heads);
  mail.appendChild(soonRow);
  mail.appendChild(tooRow);
  mail.appendChild(knowRow);
  mail.appendChild(callRow);
  mail.appendChild(acts);
  mail.appendChild(unsubRow);
  mail.appendChild(remindRow);
  mail.appendChild(watchRow);
  mail.appendChild(answerRow);
  mail.appendChild(saveRow);
  mail.appendChild(cardRow);
  mail.appendChild(mailSaid);
  mail.appendChild(body);
  mail.appendChild(files);
  mail.appendChild(navBottom);
  node.appendChild(mail);

  // --- the form a reply or a forward is written in -------------------------

  var write = el('div', 'ib-write');
  write.hidden = true;
  node.appendChild(write);

  // --- what the faces say --------------------------------------------------

  function say(where, text, undo) {
    where.textContent = '';
    where.hidden = !text;
    where.classList.remove('is-bad');
    if (!text) return;
    where.appendChild(document.createTextNode(text));
    if (undo) {
      where.appendChild(document.createTextNode(' '));
      var u = inboxButton('ib-undo', 'Undo');
      u.addEventListener('click', undo);
      where.appendChild(u);
    }
  }
  function sayBad(where, text) {
    say(where, text);
    where.classList.add('is-bad');
  }

  function face(which) {
    st.face = which;
    list.hidden = which !== 'list';
    mail.hidden = which !== 'mail';
    write.hidden = which !== 'write';
  }

  function drawCount() {
    count.textContent = inboxCounted(st.total, st.unread, st.query, st.rows.length, st.more);
    foot.hidden = !(st.rows.length && st.total > st.rows.length && !st.query);
    foot.textContent = 'Showing the newest ' + st.rows.length + '.';
  }

  function drawRows() {
    rows.textContent = '';
    if (!st.rows.length) {
      rows.appendChild(el('li', 'ib-empty', st.query ? 'Nothing here matches.' : 'Nothing in the inbox.'));
    }
    // A column of faces once any sender here is a contact with one; the others show their initials.
    var faced = st.rows.some(function (r) { return !!r.photo; });
    st.rows.forEach(function (r, n) {
      var li = el('li');
      var btn = el('button', 'ib-row' + (r.unread ? ' is-unread' : '') + (faced ? ' has-face' : ''));
      btn.type = 'button';
      btn.setAttribute('aria-label', (r.unread ? 'Unread. ' : '') + r.from + ', ' +
                       r.subject + ', ' + r.when);
      var dot = el('span', 'ib-dot');
      dot.setAttribute('aria-hidden', 'true');
      btn.appendChild(dot);
      // The sender's face when they are a contact with one (rouh/inbox.py, faces).
      if (faced) btn.appendChild(personFace(r.photo || '', r.from, 'ib-face'));
      var line = el('span', 'ib-line');
      var top = el('span', 'ib-top');
      top.appendChild(el('span', 'ib-from', r.from));
      // Its silos (rouh/silos.py), small, beside who sent it.
      var silos = siloChips(r.silos || [], 'ib-silos');
      if (silos) top.appendChild(silos);
      top.appendChild(el('span', 'ib-when', r.when));
      line.appendChild(top);
      line.appendChild(el('span', 'ib-subj', r.subject));
      if (r.snippet) line.appendChild(el('span', 'ib-snip', r.snippet));
      btn.appendChild(line);
      btn.addEventListener('click', function () { openAt(n); });
      li.appendChild(btn);
      rows.appendChild(li);
    });
    drawCount();
  }

  function load(quiet) {
    if (st.loading) return;
    if (!token) {
      count.textContent = 'This card cannot reach the mailbox. Ask Rouh to show the inbox again.';
      return;
    }
    st.loading = true;
    refresh.disabled = true;
    refresh.textContent = 'Refreshing…';
    if (!quiet) say(listSaid, '');
    inboxAsk(token, 'list', {}, function (m) {
      st.loading = false;
      refresh.disabled = false;
      refresh.textContent = 'Refresh';
      if (!m.ok) {
        if (!st.loaded) count.textContent = 'The inbox could not be read.';
        sayBad(listSaid, m.why);
        return;
      }
      st.loaded = Date.now();
      st.rows = Array.isArray(m.rows) ? m.rows : [];
      st.total = m.total || 0;
      st.unread = m.unread || 0;
      st.more = !!m.more;
      drawRows();
      count.textContent = m.count || count.textContent;
    });
  }
  refresh.addEventListener('click', function () { load(false); });

  // --- one message ---------------------------------------------------------

  function addHead(label, value) {
    if (!String(value || '').trim()) return;
    heads.appendChild(el('dt', null, label));
    heads.appendChild(el('dd', null, value));
  }

  function drawNav() {
    [navTop, navBottom].forEach(function (nav) {
      nav.__newer.disabled = st.pos <= 0;
      nav.__older.disabled = st.pos < 0 || st.pos >= st.rows.length - 1;
    });
  }

  function drawMark() {
    var unread = st.open ? st.open.unread : (st.rows[st.pos] || {}).unread;
    marker.textContent = unread ? 'Mark read' : 'Mark unread';
    marker.title = unread ? 'Tell Gmail this has been read' : 'Make it unread again in Gmail';
  }

  function drawMessage(msg) {
    heads.textContent = '';
    addHead('From', msg.from);
    addHead('To', msg.to);
    addHead('Cc', msg.cc);
    addHead('Date', msg.date);
    subject.textContent = msg.subject || '(no subject)';
    body.textContent = '';
    var stack = [body];
    (Array.isArray(msg.parts) ? msg.parts : []).forEach(function (p) {
      var depth = Math.max(0, Math.min(8, Number(p.q) || 0));
      while (stack.length - 1 > depth) stack.pop();
      while (stack.length - 1 < depth) {
        var q = el('div', 'ib-quote');
        stack[stack.length - 1].appendChild(q);
        stack.push(q);
      }
      // A paragraph to a block, so the space between two of them is the
      // card's own gap rather than a whole empty line of text.
      String(p.text || '').split(/\n[ \t]*\n+/).forEach(function (words) {
        if (!words.trim()) return;
        var para = el('div', 'ib-text' + (p.head ? ' ib-attr' : ''));
        inboxWords(para, words);
        stack[depth].appendChild(para);
      });
    });
    if (!body.childNodes.length) body.appendChild(el('p', 'ib-none', 'This message has no text.'));
    files.textContent = '';
    var att = Array.isArray(msg.attachments) ? msg.attachments : [];
    files.hidden = !att.length;
    if (att.length) {
      files.appendChild(el('span', 'ib-files-label', att.length === 1 ? 'Attached' : att.length + ' attached'));
      att.forEach(function (a) {
        var chip = el('span', 'cp-file');
        chip.appendChild(el('span', 'cp-file-name', a.name));
        if (a.size) chip.appendChild(el('span', 'cp-file-size', attSize(a.size)));
        files.appendChild(chip);
      });
    }
    drawMark();
    drawUnsub(msg);
    drawRemind(msg);
    drawSoon(msg);
    drawToo(msg);
    drawKnow(msg);
    drawWatch(msg);
    drawAnswerWatch(msg);
    drawSaveSender(msg);
    drawCardInMail(msg);
    drawCallSender(msg);
  }

  /** @param {any} msg */
  function drawToo(msg) {
    tooRow.textContent = '';
    var t = msg && msg.waiting_too;
    var others = (t && t.others) || [];
    tooRow.hidden = !others.length;
    others.forEach(function (/** @type {any} */ o) {
      var line = el('p', 'ib-soon-line');
      line.appendChild(el('span', 'ib-soon-note', o.said + '.'));
      if (o.link) {
        var open = el('a', 'ib-soon-link', 'Open');
        open.href = o.link;
        open.target = '_blank';
        open.rel = 'noopener';
        open.title = 'Opens that conversation in Gmail';
        open.setAttribute('aria-label', 'Open: ' + o.said);
        open.addEventListener('click', function () {
          inboxAsk(token, 'waiting_too', { id: msg.id }, function () {});
        });
        line.appendChild(open);
      }
      tooRow.appendChild(line);
    });
  }

  /** @param {any} msg */
  function drawKnow(msg) {
    knowRow.textContent = '';
    var k = msg && msg.know_them;
    knowRow.hidden = !(k && k.said);
    if (!k || !k.said) return;
    var line = el('p', 'ib-soon-line');
    line.appendChild(el('span', 'ib-soon-note', k.said));
    [['last', 'Open the last', 'Opens your last conversation with them in Gmail'],
      ['first', 'Open the first', 'Opens your first conversation with them in Gmail']].forEach(function (w) {
      var href = k[w[0]];
      if (!href) return;
      var open = el('a', 'ib-soon-link', w[1]);
      open.href = href;
      open.target = '_blank';
      open.rel = 'noopener';
      open.title = w[2];
      open.addEventListener('click', function () {
        inboxAsk(token, 'know_them', { id: msg.id, when: w[0] }, function () {});
      });
      line.appendChild(open);
    });
    knowRow.appendChild(line);
  }

  /** @param {any} msg */
  function drawSoon(msg) {
    soonRow.textContent = '';
    var s = msg && msg.meeting_soon;
    var meetings = (s && s.meetings) || [];
    soonRow.hidden = !meetings.length;
    meetings.forEach(function (m) {
      var line = el('p', 'ib-soon-line');
      line.appendChild(el('span', 'ib-soon-note', m.said + '.'));
      if (m.link) {
        var open = el('a', 'ib-soon-link', 'Open the meeting');
        open.href = m.link;
        open.target = '_blank';
        open.rel = 'noopener';
        open.title = 'Opens it in Google Calendar';
        open.addEventListener('click', function () {
          inboxAsk(token, 'meeting_soon', { id: msg.id }, function () {});
        });
        line.appendChild(open);
      }
      soonRow.appendChild(line);
    });
  }

  /** @param {any} msg */
  function drawWatch(msg) {
    watchRow.textContent = '';
    var w = msg && msg.watch;
    watchRow.hidden = !w;
    if (!w) return;
    watchRow.appendChild(el('span', 'ib-remind-note', 'They wrote: \u201c' + w.sentence + '\u201d'));
    var b = inboxButton('ib-watch-at', w.label, 'Rouh looks for it ' + w.at + ' and tells you only if nothing has come');
    watchRow.appendChild(b);
    b.addEventListener('click', function () {
      busy(b, 'Setting\u2026');
      inboxAsk(token, 'watch', { id: msg.id }, function (m) {
        done(b);
        if (!m.ok) {
          sayBad(mailSaid, m.why || 'It could not be set.');
          return;
        }
        watchRow.textContent = '';
        watchRow.appendChild(el('span', 'ib-remind-note', m.said || 'Rouh will look for it.'));
        var see = el('a', 'ib-remind-link', 'See it on Clockwork');
        see.href = '/clockwork';
        watchRow.appendChild(see);
      });
    });
  }

  /** @param {any} msg */
  function drawAnswerWatch(msg) {
    answerRow.textContent = '';
    var w = msg && msg.answer_watch;
    answerRow.hidden = !w;
    if (!w) return;
    answerRow.appendChild(el('span', 'ib-remind-note', 'They asked: \u201c' + w.ask + '\u201d'));
    var b = inboxButton('ib-answer-watch-at', w.label, 'Rouh looks ' + w.at + ' and reminds you only if you have not answered by then');
    answerRow.appendChild(b);
    b.addEventListener('click', function () {
      busy(b, 'Setting\u2026');
      inboxAsk(token, 'answer_watch', { id: msg.id }, function (m) {
        done(b);
        if (!m.ok) {
          sayBad(mailSaid, m.why || 'It could not be set.');
          return;
        }
        answerRow.textContent = '';
        answerRow.appendChild(el('span', 'ib-remind-note', m.said || 'Rouh will look tomorrow.'));
        var see = el('a', 'ib-remind-link', 'See it on Clockwork');
        see.href = '/clockwork';
        answerRow.appendChild(see);
      });
    });
  }

  /** @param {any} msg */
  function drawCallSender(msg) {
    callRow.textContent = '';
    var c = msg && msg.call_sender;
    var numbers = (c && c.numbers) || [];
    callRow.hidden = !numbers.length;
    if (!numbers.length) return;
    callRow.appendChild(el('span', 'ib-remind-note', c.said || 'Call them:'));
    numbers.forEach(function (/** @type {any} */ n) {
      var a = el('a', 'ib-btn ib-call-at', (n.label ? n.label + ' ' : '') + n.number);
      a.href = String(n.tel || '');
      a.title = 'Rings ' + (c.name || 'them') + ' on ' + n.number;
      a.addEventListener('click', function () {
        // Counted only; the link itself has the phone ring the number.
        inboxAsk(token, 'call_sender', { id: msg.id, when: n.label || '' }, function () {});
      });
      callRow.appendChild(a);
    });
  }

  /** @param {any} msg */
  function drawCardInMail(msg) {
    cardRow.textContent = '';
    var c = msg && msg.card_in_mail;
    cardRow.hidden = !(c && c.said);
    if (!c || !c.said) return;
    cardRow.appendChild(el('span', 'ib-remind-note', c.said));
    if (!c.button) return;
    var b = inboxButton('ib-card-in-mail-at', c.button,
      c.kind === 'new' ? 'Saves ' + (c.name || 'them') + ' to your iCloud contacts'
        : 'Adds what the card has to ' + (c.name || 'their') + '\'s contact in iCloud');
    cardRow.appendChild(b);
    b.addEventListener('click', function () {
      busy(b, 'Saving\u2026');
      inboxAsk(token, 'card_in_mail', { id: msg.id }, function (m) {
        done(b);
        if (!m.ok) {
          sayBad(mailSaid, m.why || 'The card could not be saved.');
          return;
        }
        cardRow.textContent = '';
        cardRow.appendChild(el('span', 'ib-remind-note', m.said || 'Saved to your contacts.'));
      });
    });
  }

  /** @param {any} msg */
  function drawSaveSender(msg) {
    saveRow.textContent = '';
    var w = msg && msg.save_sender;
    saveRow.hidden = !(w && w.said);
    if (!w || !w.said) return;
    saveRow.appendChild(el('span', 'ib-remind-note', w.said));
    var b = inboxButton('ib-save-sender-at', 'Save to contacts', 'Adds ' + (w.name || 'them') + ' to your iCloud contacts, as said');
    saveRow.appendChild(b);
    b.addEventListener('click', function () {
      busy(b, 'Saving\u2026');
      inboxAsk(token, 'save_sender', { id: msg.id }, function (m) {
        done(b);
        if (!m.ok) {
          sayBad(mailSaid, m.why || 'They could not be saved.');
          return;
        }
        saveRow.textContent = '';
        saveRow.appendChild(el('span', 'ib-remind-note', m.said || 'Saved to your contacts.'));
      });
    });
  }

  /** @param {any} msg */
  function drawRemind(msg) {
    remindRow.textContent = '';
    var r = msg && msg.remind;
    var choices = (r && r.choices) || [];
    remindRow.hidden = !choices.length;
    if (!choices.length) return;
    remindRow.appendChild(el('span', 'ib-remind-note', 'Remind me:'));
    var buttons = [];
    choices.forEach(function (c) {
      var b = inboxButton('ib-remind-at', c.label, 'Rouh brings this email back ' + c.at + ', on your phone too');
      buttons.push(b);
      remindRow.appendChild(b);
      b.addEventListener('click', function () {
        busy(b, 'Setting…');
        buttons.forEach(function (x) { if (x !== b) x.disabled = true; });
        inboxAsk(token, 'remind', { id: msg.id, when: c.when }, function (m) {
          done(b);
          if (!m.ok) {
            buttons.forEach(function (x) { x.disabled = false; });
            sayBad(mailSaid, m.why || 'The reminder could not be set.');
            return;
          }
          remindRow.textContent = '';
          remindRow.appendChild(el('span', 'ib-remind-note', m.said || 'Rouh will bring it back.'));
          var see = el('a', 'ib-remind-link', 'See it on Clockwork');
          see.href = '/clockwork';
          remindRow.appendChild(see);
        });
      });
    });
  }

  /** @param {any} msg */
  function drawUnsub(msg) {
    unsubRow.textContent = '';
    var u = msg && msg.unsubscribe;
    unsubRow.hidden = !u;
    if (!u) return;
    var note = el('span', 'ib-unsub-note', 'From a list: ' + (u.list || 'this sender') +
      (u.before ? '. You unsubscribed on ' + u.before + '.' : ''));
    unsubRow.appendChild(note);
    if (u.how === 'mail') {
      unsubRow.appendChild(el('span', 'ib-unsub-note', 'It unsubscribes only by an email from your own address.'));
      return;
    }
    var b = inboxButton('ib-unsubscribe', u.how === 'link' ? 'Unsubscribe…' : 'Unsubscribe',
      u.how === 'link' ? "Open the sender's own page to unsubscribe" : 'Stop mail from this list, in one press');
    unsubRow.appendChild(b);
    b.addEventListener('click', function () {
      var asked = msg.id;
      // A tab opened inside the press itself, so no browser blocks it; filled once the server says where.
      var tab = u.how === 'link' ? window.open('', '_blank') : null;
      busy(b, 'Unsubscribing…');
      inboxAsk(token, 'unsubscribe', { id: asked }, function (m) {
        done(b);
        if (!m.ok) {
          if (tab) tab.close();
          sayBad(mailSaid, m.why || 'It could not be done.');
          return;
        }
        if (m.open && tab) { tab.opener = null; tab.location.href = m.open; }
        else if (m.open) window.open(m.open, '_blank', 'noopener');
        b.disabled = true;
        b.textContent = 'Unsubscribed';
        say(mailSaid, m.said || 'Unsubscribed.');
      });
    });
  }

  function openAt(n, said) {
    var r = st.rows[n];
    if (!r) return;
    st.pos = n;
    st.open = null;
    face('mail');
    say(mailSaid, said || '');
    heads.textContent = '';
    addHead('From', r.from + (r.address && r.address !== r.from ? ' <' + r.address + '>' : ''));
    addHead('Date', r.when);
    subject.textContent = r.subject;
    body.textContent = '';
    body.appendChild(el('p', 'ib-none', 'Opening the message…'));
    files.hidden = true;
    unsubRow.hidden = true;
    remindRow.hidden = true;
    watchRow.hidden = true;
    answerRow.hidden = true;
    acts.hidden = readOnly;
    drawNav();
    drawMark();
    inboxToTop(node);
    var asked = r.id;
    inboxAsk(token, 'open', { id: r.id }, function (m) {
      // Read in Gmail now, whichever face the card has moved on to.
      if (m.ok && m.marked_read) { markRow(asked, false); drawCount(); }
      if (st.face !== 'mail' || (st.rows[st.pos] || {}).id !== asked) {
        if (m.ok && m.marked_read && st.face === 'list') drawRows();
        return;
      }
      if (!m.ok || !m.message) {
        body.textContent = '';
        sayBad(mailSaid, m.why || 'That message could not be opened.');
        return;
      }
      st.open = m.message;
      drawMessage(m.message);
    });
  }

  function step(by) {
    var n = st.pos + by;
    if (n >= 0 && n < st.rows.length) openAt(n);
  }

  function showList(said, undo) {
    face('list');
    st.pos = -1;
    st.open = null;
    drawRows();
    if (typeof said === 'string') say(listSaid, said, undo);
    else say(listSaid, '');
    inboxToTop(node);
  }

  function busy(button, text) {
    button.disabled = true;
    button.classList.add('is-busy');
    button.__was = button.textContent;
    button.textContent = text;
  }
  function done(button) {
    button.disabled = false;
    button.classList.remove('is-busy');
    if (button.__was) button.textContent = button.__was;
  }

  // Out of the inbox, off the list at once, and back to the list with a way
  // to put it back.
  archive.addEventListener('click', function () {
    var r = st.rows[st.pos];
    if (!r) return;
    busy(archive, 'Archiving…');
    inboxAsk(token, 'archive', { id: r.id }, function (m) {
      done(archive);
      if (!m.ok) { sayBad(mailSaid, m.why); return; }
      forget(r.id);
      showList('Archived "' + r.subject + '".', function () { unarchive(r); });
    });
  });

  function unarchive(r) {
    say(listSaid, 'Putting it back…');
    inboxAsk(token, 'unarchive', { id: r.id }, function (m) {
      if (!m.ok) { sayBad(listSaid, m.why); return; }
      say(listSaid, 'Back in the inbox: "' + r.subject + '".');
      load(true);
    });
  }

  // Every message of one conversation the card lists.
  function inThread(thread) {
    return st.rows.filter(function (r) { return thread && r.thread === thread; })
      .map(function (r) { return r.id; });
  }

  // A message gone from the inbox, wherever it went from.
  function forget(id) {
    var at = -1;
    st.rows.forEach(function (r, n) { if (r.id === id) at = n; });
    if (at < 0) return false;
    var gone = st.rows.splice(at, 1)[0];
    st.total = Math.max(0, st.total - 1);
    if (gone.unread) st.unread = Math.max(0, st.unread - 1);
    if (st.pos > at) st.pos -= 1;
    return true;
  }

  function markRow(id, unread) {
    st.rows.forEach(function (r) {
      if (r.id !== id || r.unread === unread) return;
      r.unread = unread;
      st.unread = Math.max(0, st.unread + (unread ? 1 : -1));
    });
    if (st.open && st.open.id === id) st.open.unread = unread;
  }

  marker.addEventListener('click', function () {
    var r = st.rows[st.pos];
    if (!r) return;
    var unread = st.open ? st.open.unread : r.unread;
    busy(marker, unread ? 'Marking read…' : 'Marking unread…');
    inboxAsk(token, unread ? 'read' : 'unread', { id: r.id }, function (m) {
      done(marker);
      if (!m.ok) { sayBad(mailSaid, m.why); return; }
      markRow(r.id, !!m.unread);
      drawMark();
      say(mailSaid, m.unread ? 'Marked unread.' : 'Marked read.');
    });
  });

  // --- writing back --------------------------------------------------------

  var LABELS = { reply: 'Reply', replyall: 'Reply all', forward: 'Forward' };

  function writeBack(mode, button) {
    var r = st.rows[st.pos];
    if (!r) return;
    busy(button, 'Opening…');
    inboxAsk(token, 'compose', { id: r.id, mode: mode }, function (m) {
      done(button);
      if (!m.ok || !m.form) { sayBad(mailSaid, m.why || 'That could not be opened.'); return; }
      var f = m.form;
      write.textContent = '';
      var top = el('div', 'ib-nav ib-nav-top');
      var back = inboxButton('ib-back', '← Back to the message');
      back.addEventListener('click', function () { face('mail'); inboxToTop(node); });
      top.appendChild(back);
      write.appendChild(top);
      write.appendChild(el('h3', 'ib-subject', (mode === 'forward' ? 'Forwarding: ' : 'Replying to: ') + r.subject));
      var form = composeBlock({
        fields: f.fields, body: f.body, send: f.send || 'Send',
        attachments: (f.attachments || []).map(function (a) {
          return { id: a.part, name: a.name, size: a.size };
        }),
        hint: 'Sent from Rouh’s own mailbox, signed as Rouh.'
      }, 0, {
        label: LABELS[mode],
        cancel: function () { face('mail'); inboxToTop(node); },
        send: function (edits, formNode) {
          var keep = (edits.attachments || []).map(function (a) { return a.id; });
          inboxAsk(token, 'send', {
            id: r.id, mode: mode, keep: keep,
            edits: { fields: edits.fields, body: edits.body }
          }, function (a) {
            if (!a.ok) {
              formNode.__reset(true);
              formNode.__say(a.why || 'That did not go, and nothing was sent.');
              return;
            }
            var went = (mode === 'forward' ? 'Forwarded to ' : 'Reply sent to ') +
                (a.to || 'them') + '.';
            if (a.archived) {
              // Out of the inbox with its whole conversation, as Gmail's
              // Send & Archive leaves it, and Undo puts this message back.
              var gone = inThread(a.thread);
              if (gone.indexOf(r.id) < 0) gone.push(r.id);
              gone.forEach(forget);
              showList(went + ' The conversation is archived.', function () { unarchive(r); });
              return;
            }
            face('mail');
            say(mailSaid, went + (a.after ? ' ' + a.after : ''));
            inboxToTop(node);
          });
        }
      });
      write.appendChild(form);
      if (mode === 'forward' && f.forwarded) write.appendChild(forwardedPreview(f.forwarded));
      face('write');
      inboxToTop(node);
      // The caret where the person writes: the first line of the body for a
      // reply, the To line for a forward, which goes to nobody yet.
      var to = form.__boxes && form.__boxes.to;
      if (mode === 'forward' && to) {
        to.focus();
      } else if (form.__body) {
        form.__body.focus();
        try {
          var range = document.createRange();
          range.setStart(form.__body.firstChild || form.__body, 0);
          range.collapse(true);
          var sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        } catch (e) {}
      }
    });
  }
  /* The original under a forward's note, as it will go: Gmail's header, and
     the message's own HTML in a frame that runs nothing, or its text. It is
     shown and not edited, because it goes out exactly as it came
     (`rouh/forwarding.py`). */
  function forwardedPreview(fw) {
    var box = el('div', 'ib-fwd');
    box.appendChild(el('p', 'ib-fwd-rule', fw.rule || '---------- Forwarded message ---------'));
    var dl = el('dl', 'ib-heads ib-fwd-heads');
    (fw.head || []).forEach(function (h) {
      if (!h || !h[1]) return;
      dl.appendChild(el('dt', '', h[0]));
      dl.appendChild(el('dd', '', h[1]));
    });
    box.appendChild(dl);
    if (fw.html) {
      var frame = document.createElement('iframe');
      frame.className = 'ib-fwd-frame';
      // Nothing allowed at all: no scripts, no forms, no reaching this page.
      frame.setAttribute('sandbox', '');
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.title = 'The forwarded email, as it will go';
      frame.srcdoc = demoFrame('<!doctype html><html><head><meta charset="utf-8">'
        + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        + 'img-src https: http: data:; style-src \'unsafe-inline\'; font-src data: https:">'
        + '<base target="_blank"></head><body>' + fw.html + '</body></html>');
      box.appendChild(frame);
    } else {
      box.appendChild(el('div', 'ib-fwd-text', fw.text || ''));
    }
    box.appendChild(el('p', 'ib-fwd-hint', 'It goes as it came, unchanged, under what you write above.'));
    return box;
  }
  reply.addEventListener('click', function () { writeBack('reply', reply); });
  replyAll.addEventListener('click', function () { writeBack('replyall', replyAll); });
  forward.addEventListener('click', function () { writeBack('forward', forward); });

  // --- another screen's change, and being looked at -----------------------

  if (!readOnly) node.__changed = function (m) {
    if (!m || !(m.id || m.thread)) return;
    if (m.archived) {
      // One message, or a whole conversation archived once a reply went.
      var ids = m.id ? [m.id] : inThread(m.thread);
      var here = st.face !== 'list' ? (st.rows[st.pos] || {}).id : null;
      var open = here != null && ids.indexOf(here) >= 0;
      var any = false;
      ids.forEach(function (id) { if (forget(id)) any = true; });
      if (any && st.face === 'list') drawRows();
      if (open) showList(m.id ? 'That message was archived.' : 'That conversation was archived.');
      else if (st.face !== 'list') drawNav();
    } else if (m.unarchived) {
      if (st.face === 'list') load(true);
    } else if (typeof m.unread === 'boolean') {
      markRow(m.id, m.unread);
      if (st.face === 'list') drawRows();
      else { drawMark(); drawCount(); }
    }
  };

  // Read when it is first seen, not when it is drawn: a conversation with
  // five inbox cards in its past would otherwise read the mailbox five times
  // on every load. Read again when it comes back into view with an old list.
  function seen() {
    if (!st.loaded) load(false);
    else if (st.face === 'list' && Date.now() - st.loaded > INBOX_STALE_MS) load(true);
  }
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) if (entries[i].isIntersecting) seen();
    }).observe(node);
  } else {
    setTimeout(seen, 0);
  }
  return node;
}

// What a contact card says, for the copy button: the lines a person would
// paste into a message, with what the change did in brackets.
function contactWords(b) {
  var lines = [String(b.name || '') + (b.status ? ' (' + b.status + ')' : '')];
  if (b.was_name) lines.push('was ' + b.was_name);
  var rows = Array.isArray(b.rows) ? b.rows : [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i] || {};
    var said = (r.label || r.kind || '') + '\t' + (r.value == null ? '' : r.value);
    if (r.change) said += ' (' + r.change + (r.was ? ', was ' + r.was : '') + ')';
    lines.push(said);
  }
  if (b.remark) lines.push(String(b.remark));
  return lines.join('\n');
}

/* ---------- a job whose work will not go onto main --------------------

   land.sh climbs its own ladder and only writes a conflict record when it
   runs out of rungs: twice failed, or both sides rewrote the same thing. Then
   this is what the person sees, and it is the whole of their part. The one
   line of the question, the two sides beside each other, and four buttons,
   each of them a command land.sh already knows how to run. Nothing here is
   free text, and nothing here needs the conversation it came from.

   It is a block of its own rather than an `html` one because those are drawn
   in a sandboxed frame that can reach neither this page nor the socket, so
   buttons inside one would be a picture of buttons.

   The number on each button is the key that presses it. While a live card is
   on the screen, 1 to 4 answer it from the keyboard, unless the person is
   typing, because a digit typed into the composer is a digit, not an answer. */

var conflictCards = {};

/** @param {import('./protocol').BlockOf<'conflict'>} b */
function conflictBlock(b, older) {
  var id = String(b.id || '');
  var node = el('div', 'b-conflict');
  node.setAttribute('data-conflict', id);

  var head = el('div', 'cf-head');
  head.appendChild(el('span', 'cf-dot'));
  head.appendChild(el('b', null, 'Conflict needs you'));
  head.appendChild(el('span', 'cf-where', b.heading || ''));
  node.appendChild(head);

  var q = el('div', 'cf-q', b.question || 'Which side of this should win?');
  node.appendChild(q);

  var sides = el('div', 'cf-sides');
  (b.sides || []).forEach(function (s) {
    var side = el('div', 'cf-side');
    side.appendChild(el('h5', null, s.heading || ''));
    side.appendChild(el('p', null, s.text || ''));
    side.appendChild(el('code', null, s.files || ''));
    sides.appendChild(side);
  });
  node.appendChild(sides);

  var row = el('div', 'cf-btns');
  var buttons = [];
  (b.options || []).forEach(function (o) {
    var button = el('button', 'cf-b' + (o.tone && o.tone !== 'plain' ? ' ' + o.tone : ''));
    button.type = 'button';
    button.appendChild(el('span', 'k', String(o.n)));
    button.appendChild(el('span', null, o.label || ''));
    button.title = o.means || '';
    button.setAttribute('aria-label', o.n + '. ' + (o.label || '') +
      (o.means ? '. ' + o.means : ''));
    button.addEventListener('click', function () { answerConflict(id, o.n); });
    row.appendChild(button);
    buttons.push(button);
  });
  node.appendChild(row);

  var said = el('div', 'cf-said');
  said.hidden = true;
  node.appendChild(said);

  var rec = { node: node, buttons: buttons, said: said };
  (conflictCards[id] = conflictCards[id] || []).push(rec);
  var open = b.state === 'waiting' || !b.state;
  if (open && !older) {
    // Drawn as it arrived, so it is open by definition: the server only
    // sends one while it is waiting. It goes on the live list, which is
    // otherwise only what `ready` said at the moment this tab connected -
    // and a card that arrived after that was drawn dead on arrival.
    S.liveConflicts = S.liveConflicts || {};
    S.liveConflicts[id] = true;
  }
  // A card read back off the canvas may be one that was answered while this
  // tab was shut. `ready` says which are still live, so anything not on that
  // list is drawn as over rather than offering four buttons that do nothing.
  if (!open) {
    settleConflict(rec, b.choice, labelOf(b, b.choice));
  } else if (older && S.liveConflicts && !S.liveConflicts[id]) {
    settleConflict(rec, null, '');
  }
  return node;
}

function labelOf(b, n) {
  var found = null;
  (b.options || []).forEach(function (o) { if (o.n === n) found = o.label; });
  return found || '';
}

function answerConflict(id, n) {
  var list = conflictCards[id] || [];
  list.forEach(function (rec) {
    rec.buttons.forEach(function (button) { button.disabled = true; });
  });
  send({ type: 'conflict_answer', id: id, choice: n });
}

function settleConflict(rec, n, label, why) {
  rec.buttons.forEach(function (button) {
    button.disabled = true;
    if (n && button.firstChild && button.firstChild.textContent === String(n)) {
      button.classList.add('picked');
    }
  });
  rec.node.classList.add('cf-done');
  rec.said.hidden = false;
  rec.said.textContent = why || (n
    ? 'You chose ' + n + (label ? ', ' + label : '') + '. It has gone back to the job.'
    : 'Already answered.');
}

// Bring a conflict card into view and put the keyboard on it, from the orb or
// from the job's row on the task list.
function showConflictCard(id) {
  var found = document.querySelector('.b-conflict[data-conflict="' + String(id) + '"]');
  if (!found) return false;
  // At a desk a card is read on the canvas: one folded to its line in the
  // conversation is opened there, and one already there is brought out
  // from under whatever page is loaded over it.
  var card = found.closest('.card');
  var slot = card ? slotOf(card) : null;
  if (card && (card.classList.contains('on-canvas') ||
               (slot && slot.classList.contains('is-folded')))) {
    showOnCanvas(card);
  }
  var panel = $('canvasPanel');
  if (panel && window.matchMedia && window.matchMedia('(max-width: 899px)').matches) {
    panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  found.scrollIntoView({ block: 'center', behavior: 'smooth' });
  found.classList.add('cf-lit');
  window.setTimeout(function () { found.classList.remove('cf-lit'); }, 1400);
  var first = /** @type {HTMLElement} */ (found.querySelector('.cf-b:not([disabled])'));
  if (first) first.focus();
  return true;
}

/** @param {Partial<import('./protocol').FromServer<'conflict_done'>> & {why?: string}} m a conflict_done, or a conflict_gone's id and why */
function onConflictDone(m) {
  var id = String(m.id || '');
  if (S.liveConflicts) delete S.liveConflicts[id];
  (conflictCards[id] || []).forEach(function (rec) {
    // The server says what happened rather than the page guessing at it: a
    // pick that went back to the worker and a pick Rouh carried out itself
    // because the worker had stopped are not the same news, and the second
    // one is the one worth saying out loud.
    settleConflict(rec, m.choice, m.label, m.said || m.why);
  });
}

// Which conflicts are still waiting, off `ready`. A card is drawn from the
// canvas, which is history, and history does not know it was answered.
function notedConflicts(list) {
  S.liveConflicts = {};
  (list || []).forEach(function (b) {
    if (b && b.id) S.liveConflicts[String(b.id)] = true;
  });
  var id;
  for (id in conflictCards) {
    if (!S.liveConflicts[id]) {
      conflictCards[id].forEach(function (rec) {
        if (!rec.node.classList.contains('cf-done')) settleConflict(rec, null, '');
      });
    }
  }
}

// The digits, while a live card is on the screen and nobody is typing.
function conflictKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  if (!/^[1-4]$/.test(e.key)) return false;
  var on = /** @type {HTMLElement} */ (document.activeElement);
  if (on && (on.tagName === 'INPUT' || on.tagName === 'TEXTAREA' || on.isContentEditable)) {
    return false;
  }
  var id, list, i;
  for (id in conflictCards) {
    if (!S.liveConflicts || !S.liveConflicts[id]) continue;
    list = conflictCards[id];
    for (i = list.length - 1; i >= 0; i--) {
      if (!list[i].node.classList.contains('cf-done') && list[i].node.isConnected) {
        answerConflict(id, Number(e.key));
        return true;
      }
    }
  }
  return false;
}

/* A table or a list under the heading the model gave it.

   `label` is one field of the schema shared by every block, and the model
   writes one on a list as often as not: "Also worth knowing", "The other
   findings that matter". Only a stat drew it until 24 September 2026, so
   every such list read as though it carried on from the table above it,
   and a link given a label and no text showed its bare address instead. */
function labelled(b, node) {
  if (b.label == null || String(b.label).trim() === '') return node;
  var wrap = el('div', 'b-labelled');
  wrap.appendChild(el('div', 'b-label', String(b.label)));
  wrap.appendChild(node);
  return wrap;
}

/* One block, drawn. The same function serves a message and a card, because
   they are the same thing: a message is a block list with one text block in
   it. `older` is a card read back from the history rather than drawn now. */
/** @param {import('./protocol').Block} b */
function renderBlock(b, cardId, older) {
  if (!b || typeof b !== 'object') return null;
  var node, i;
  switch (b.block) {
    case 'stat':
      node = el('div', 'b-stat');
      if (b.label != null) node.appendChild(el('span', 'lbl', b.label));
      node.appendChild(el('span', 'num', b.value == null ? '-' : b.value));
      if (b.hint) node.appendChild(el('span', 'hint', b.hint));
      return node;

    case 'table':
      node = el('div', 'b-table');
      var table = el('table');
      var cols = Array.isArray(b.columns) ? b.columns : [];
      if (cols.length) {
        var thead = el('thead'), htr = el('tr');
        for (i = 0; i < cols.length; i++) htr.appendChild(el('th', null, cols[i]));
        thead.appendChild(htr);
        table.appendChild(thead);
      }
      var tbody = el('tbody');
      var rows = Array.isArray(b.rows) ? b.rows : [];
      for (i = 0; i < rows.length; i++) {
        var tr = el('tr');
        var cells = Array.isArray(rows[i]) ? rows[i] : [rows[i]];
        for (var c = 0; c < cells.length; c++) tr.appendChild(el('td', null, cells[c]));
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      node.appendChild(table);
      return labelled(b, node);

    case 'list':
      var items = Array.isArray(b.items) ? b.items : [];
      if (!items.length) return null;
      node = el('ul', 'b-list');
      for (i = 0; i < items.length; i++) node.appendChild(el('li', null, items[i]));
      return labelled(b, node);

    case 'text':
      node = el('div', 'b-text');
      node.innerHTML = renderMarkdown(b.text);
      return labelled(b, node);

    case 'code':
      node = el('div', 'b-code');
      if (b.language) node.appendChild(el('span', 'lang', b.language));
      var pre = el('pre');
      pre.appendChild(el('code', null, b.text == null ? '' : b.text));
      node.appendChild(pre);
      node.insertAdjacentHTML('beforeend', CODE_COPY);
      return node;

    case 'chart':
      return chartBlock(b);

    case 'image':
      return imageBlock(b);

    case 'html':
      return htmlBlock(b);

    case 'conflict':
      return conflictBlock(b, older);

    case 'contact':
      return contactBlock(b);

    case 'email':
      return emailBlock(b);

    case 'ask':
      return askBlock(b);

    case 'people':
      return peopleBlock(b);

    case 'profile':
      return profileBlock(b);

    case 'compose':
      return composeBlock(b, cardId);

    case 'inbox':
      return inboxBlock(b);

    case 'sources':
      return sourcesBlock(b);

    case 'link':
      if (!b.href) return null;
      node = el('div', 'b-link');
      var a = el('a');
      var href = String(b.href);
      // An address in Rouh itself - a run's own page at the foot of its report
      // (`rouh/run_report.py`), a task's page - is opened here, in this tab,
      // the way every other link into Rouh is (`linkTo`); Cmd and the middle
      // button still take it to a tab of its own. Anywhere else opens beside.
      // A file of a task's, by the signed link Rouh drew for it (`rouh/filelinks.py`), such as a
      // page made into a PDF (`rouh/page_pdf.py`), is saved, never opened as a place in Rouh.
      var file = href.indexOf('/files/') === 0;
      var inapp = !file && href.charAt(0) === '/' && href.charAt(1) !== '/';
      var named = file ? decodeURIComponent(href.split('/').pop() || '') : '';
      if (inapp) {
        linkTo(a, href);
      } else if (file) {
        a.href = href;
        a.setAttribute('download', named);
      } else {
        a.href = href;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
      }
      a.appendChild(el('span', null, b.text || b.label || href));
      a.appendChild(el('span', 'href', file ? named : inapp ? location.host + href : href));
      // A press on a link out is told to the model, which answers it; going
      // somewhere in Rouh is only going there, and starts no turn. A file is only saved.
      a.addEventListener('click', function () {
        if (file) return;
        if (inapp) goToAddress(href);
        else send({ type: 'ui_event', id: b.id || cardId, value: href });
      });
      node.appendChild(a);
      return node;

    case 'frame':
      // A page from the person's workspace, as a tile that opens it: its
      // name, where it lives, and one button. The page itself is opened on
      // the canvas, at full width, as the page it is.
      //
      // This block drew the whole page inside the card until 23 September
      // 2026, working, in a sandboxed frame. Petar found that confusing:
      // the same page was then a card with a page loaded inside it, and a
      // page of its own on the task, and it was not clear those were one
      // thing. A page is only ever seen as itself now, and a card that
      // points at one says so and takes you there.
      //
      // Only Rouh's own address for workspace pages is opened, judged after
      // the browser has resolved it.
      var pageSrc;
      try { pageSrc = new URL(b.href, location.href); } catch (err) { return null; }
      if (pageSrc.origin !== location.origin || pageSrc.pathname.indexOf(WORKSPACE_ROUTE) !== 0) return null;
      var pageAt = pageSrc.pathname + (pageSrc.search || '');
      var pageRel = pageSrc.pathname.slice(WORKSPACE_ROUTE.length);
      try { pageRel = decodeURIComponent(pageRel); } catch (err) {}
      node = el('div', 'b-page');
      var pageOpen = el('button', 'b-page-open');
      pageOpen.type = 'button';
      // The globe every page is drawn with (`objectindex.KIND_MARKS`).
      pageOpen.appendChild(el('span', 'b-page-mark', '\ud83c\udf10'));
      var pageWords = el('span', 'b-page-words');
      pageWords.appendChild(el('span', 'b-page-name', b.title || 'A page from the workspace'));
      pageWords.appendChild(el('span', 'b-page-where', pageRel));
      pageOpen.appendChild(pageWords);
      pageOpen.appendChild(el('span', 'b-page-go', 'Open the page'));
      pageOpen.title = 'Opens this page on the canvas, at full width.';
      pageOpen.addEventListener('click', function () { canvasLoad(pageAt); });
      node.appendChild(pageOpen);
      return node;

    default:
      return null; // unknown kinds are skipped, never thrown
  }
}

/* ---------- a workspace page in a frame ----------

   A frame is sandboxed, so the browser gives the page inside it an origin of
   its own. What that costs is the sign-in: the browser sends Rouh's cookie
   with a request this page starts for the frame, and does not send it with a
   request the frame starts for itself. The first load is this page's, so it
   worked; every link clicked inside the frame was the frame's, and Rouh
   answered it "Sign in to Rouh first." That is what a reader saw when they
   pressed Task browser and when they clicked a task.

   So the frame never fetches anything. This page fetches the markup, with
   its own sign-in, and hands it over as text. The page in the frame is the
   same page, sandboxed the same way, with two lines more in its head saying
   where it is and that it still may not call out (pages.frame_head); it is
   only who asked for it that has changed. A link clicked inside comes back
   here as a message, and this page fetches that address too. */

var WORKSPACE_ROUTE = '/workspace/';

/* A comment thread to open on the page this address names, from the link
   in a letter that tagged the person: `/task/<the page>?comment=<id>`
   (`rouh/comments.py`). Read once, as Rouh starts, because the address is
   tidied as soon as the page is on the screen, and handed to the canvas's
   frame the first time it loads that page. */
var COMMENT_WANTED = (function () {
  var found = /[?&]comment=(\d{1,12})(?:&|$)/.exec(location.search || '');
  var parts = location.pathname.split('/').filter(Boolean);
  if (!found || parts.length < 2) return null;
  try {
    return { rel: parts.slice(1).map(decodeURIComponent).join('/'), id: Number(found[1]) };
  } catch (err) { return null; }
})();

// The address Rouh asks for, for a page it is going to frame: the same
// address with the mark that says this is a page for a frame.
function frameAddress(href, hosted) {
  var u = new URL(href, location.href);
  if (u.origin !== location.origin || u.pathname.indexOf(WORKSPACE_ROUTE) !== 0) return null;
  u.searchParams.set('framed', '1');
  if (hosted && COMMENT_WANTED) {
    var here = '';
    try { here = decodeURIComponent(u.pathname.slice(WORKSPACE_ROUTE.length)); } catch (err) {}
    if (here === COMMENT_WANTED.rel) {
      u.searchParams.set('comment', String(COMMENT_WANTED.id));
      COMMENT_WANTED = null;
    }
  }
  /* And that this page is drawing the conversation about it, in the column
     beside the frame, so the page comes back without a chat of its own in
     it (askai.drawer_head). Only the canvas's frame asks for that: a page
     framed inside a card has no column beside it and keeps the drawer it
     always had. */
  if (hosted) u.searchParams.set('hosted', '1');
  return u;
}

// The frame one of these messages came from, or nothing. A sandboxed page
// has no origin to check, so the window it was sent from is the whole check.
function frameOf(source) {
  if (!source) return null;
  var frames = document.querySelectorAll('iframe');
  for (var i = 0; i < frames.length; i++) {
    try { if (frames[i].contentWindow === source) return frames[i]; } catch (err) {}
  }
  return null;
}

var FRAME_TITLE = /<title[^>]*>([\s\S]*?)<\/title\s*>/i;
var FRAME_ENTITY = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

// The page's own title, out of the markup. Read here rather than out of the
// frame: nothing can read a title through a sandboxed frame's edge. The few
// entities a page can have in a title are undone by hand rather than by
// handing the string to the browser to parse, which is how a title becomes
// markup on this page.
function frameTitle(text) {
  var found = FRAME_TITLE.exec(text || '');
  if (!found) return '';
  return found[1]
    .replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, function (whole, name) {
      if (name.charAt(0) === '#') {
        var code = name.charAt(1) === 'x' || name.charAt(1) === 'X'
          ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
        return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : whole;
      }
      var said = FRAME_ENTITY[name.toLowerCase()];
      return said === undefined ? whole : said;
    })
    .replace(/\s+/g, ' ').trim();
}

// A sentence in place of a page that would not load. The background is
// Rouh's own and not `transparent`: a frame paints white where its page
// paints nothing, so a transparent sheet in a dark app is a white one, and
// that is exactly what the person sent in on 23 September 2026. The tasks
// canvas does not come here at all any more - it says so in Rouh's own
// chrome, with the way back on it (`canvasLost`) - and this is what is left
// for every other frame.
function frameSays(words) {
  return '<!doctype html><meta charset="utf-8"><body style="margin:0;padding:24px;'
       + 'font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;'
       + 'color:#8b95a3;background:#0a0c10">' + esc(words) + '</body>';
}

/* A page put into a frame without leaving anything in the tab's history.

   Setting `srcdoc` on a frame that already holds a page is a navigation of
   that frame, and a browser may write it into the tab's history as a step
   of its own. So may anything a page does to its own address inside the
   frame: the task browser pushed one for every project button pressed,
   which Chromium refuses from a sandboxed frame and Safari allows. Rouh
   throws a frame away every time the canvas moves (`canvasLoad`), and a
   step left behind by a frame that is gone is one Back lands on with
   nothing to show: Chromium does nothing for that press, and Safari loads
   the old `about:srcdoc` again, empty, a white rectangle where the task
   browser should be. Petar, 27 September 2026, from an iPhone
   (fr_08e89370f7c7): "When I am on task browser and click a page to view
   and then go back I don't get back to the task browser but I get a white
   blank page."

   Two things stop it, and this is both of them. The frame is taken out of
   the page while its page is changed and put back, so the page arrives in a
   browsing context of its own, and the first page of a context replaces the
   empty one it started with instead of adding a step. And every one of
   those contexts has a name nothing else has had: a step some page inside
   it did manage to leave behind names a frame that no longer exists, and
   a browser going Back finds nothing there to load into. */
var frameSerial = 0;

function frameWrite(frame, html) {
  var parent = frame.parentNode, next = frame.nextSibling;
  frameSerial += 1;
  frame.name = 'rouh-frame-' + frameSerial;
  if (parent) parent.removeChild(frame);
  // In demo mode the page starts in demo mode too, kept copies with no connection among them.
  frame.srcdoc = demoFrame(html);
  if (parent) parent.insertBefore(frame, next);
}

/* With no connection, which tasks this device keeps whole, said to the task
   browser so the rest say so. Asked by the browser as it loads, and said
   again when the page goes on from this device's copy (`offlineReplay`),
   because a browser an address opened is there before the socket has had
   its chance to fail (`addrEarly`). Not while the socket is still on its
   way: that is not being offline. */
function browserOfflineSay() {
  var frame = tasksFrame(), off = window.RouhOffline;
  if (!frame || CANVAS.at !== BROWSE_ROOT || !off || !off.away()) return;
  off.wholeTasks().then(function (/** @type {string[]} */ have) {
    try { frame.contentWindow.postMessage({ type: 'rouh-frame-offline', offline: true, have: have }, '*'); }
    catch (err) {}
  });
}

/* One page into one frame. Answers with what became of it - whether it
   arrived, its own title, and the address that actually answered.

   That last one matters because `fetch` follows a redirect without saying
   so, and both the breadcrumb and the Ask AI relay have to know where they
   really are rather than where they asked to be. */
/**
 * @param {HTMLIFrameElement} frame
 * @param {string} href
 * @returns {Promise<{ok: boolean, status?: number, text?: string, title?: string,
 *                    landed?: string, why?: string}>}
 */
function frameLoad(frame, href) {
  var u = frameAddress(href, frame === tasksFrame());
  if (!u) return Promise.resolve({ ok: false, title: '' });
  // Only the newest load of this frame is ever shown: a reader who clicks
  // twice sees the second page, not whichever answered last.
  var mine = frame.rouhLoad = (frame.rouhLoad || 0) + 1;
  return fetch(u.href, { credentials: 'same-origin' })
    .then(function (r) {
      var landed = '';
      // Where the fetch ended up, which is not where it was sent when Rouh
      // redirected on the way.
      try {
        var end = new URL(r.url, location.href);
        if (end.origin === location.origin) {
          end.searchParams.delete('framed');
          end.searchParams.delete('hosted');
          end.searchParams.delete('y');
          end.searchParams.delete('comment');
          // An old version of the page is still that page (`askVersion`).
          end.searchParams.delete('version');
          landed = end.pathname + (end.search || '');
        }
      } catch (err) {}
      return r.text().then(function (text) {
        return { ok: r.ok, status: r.status, text: text, landed: landed };
      });
    })
    .catch(function (err) {
      return { ok: false, status: 0, text: '', why: String(err && err.message || err) };
    })
    .then(function (/** @type {{ok: boolean, status: number, text: string, landed?: string, why?: string}} */ got) {
      if (frame.rouhLoad !== mine) return { ok: got.ok, title: '' };
      if (got.ok) {
        frameWrite(frame, got.text);
        // A link that named a place in the page (`other.html#part`): the
        // fetch carried no fragment, so the page is asked to go there once
        // it has loaded (`pages.HASH_MESSAGE`).
        if (u.hash && u.hash !== '#') {
          frame.addEventListener('load', function () {
            try { frame.contentWindow.postMessage({ type: 'rouh-frame-hash', hash: u.hash }, '*'); }
            catch (err) {}
          }, { once: true });
        }
        // Which workspace page this frame is showing. The Ask AI relay below
        // reads it from here rather than from anything the page inside says:
        // the page runs its own scripts, and what it may ask about is the
        // page it already is.
        frame.rouhAt = got.landed || u.pathname;
      }
      else if (got.status === 401 || got.status === 403)
        frameWrite(frame, frameSays('Your sign-in has run out. Reload Rouh to read this page.'));
      else if (got.status)
        frameWrite(frame, frameSays('That page could not be read: the server said ' + got.status + '.'));
      else frameWrite(frame, frameSays('That page could not be read: ' + (got.why || 'no answer')));
      return { ok: got.ok, status: got.status, landed: got.landed || '',
               title: got.ok ? frameTitle(got.text) : '' };
    });
}

/* Where a frame is to be taken next, and by whom: this page.

   Two kinds of address come up out of a frame and only one of them is a
   page. A link into `/workspace/` is a file, and it is loaded into the frame
   it was clicked in. A link to an **object** - `/chat/<id>`, `/run/<id>`,
   `/artifact/<id>`, and a task or a project by its folder - is not a page at
   all: a chat is a conversation in the column beside the frame and a run is
   a terminal, and loading either one into a frame would be a picture of it.
   So an object address is opened the way a pasted link is, which is the one
   path everything else in this file already takes (`addrAsk`, `findGo`).

   That is what makes the project page's rows work. It lists what is under a
   project - its chats, its runs, what it has drawn - and each row is a plain
   link to that object's own address, written by `objectindex.py`. Nothing
   new is invented on either side: the page writes the address the object
   already has, and this opens it. */
// A link to another site, pressed in a sandboxed frame, which cannot open
// one itself (`pages.follow_script`): a tab of its own, with no opener and no
// referrer, and only ever an http or https address.
function frameOut(href) {
  var went;
  try { went = new URL(href); } catch (err) { return; }
  if (!/^https?:$/.test(went.protocol) || went.origin === location.origin) return;
  window.open(went.href, '_blank', 'noopener,noreferrer');
}

function frameGo(frame, href) {
  var went;
  try { went = new URL(href, location.href); } catch (err) { return; }
  if (went.origin !== location.origin) return;
  var where = went.pathname + went.search + went.hash;
  if (went.pathname.indexOf(WORKSPACE_ROUTE) === 0) {
    // A note beside the page (`91-01.booklet-text.md`) is not a page for the
    // frame: the workspace serves no `.md` as a file, so the frame said "That
    // page is not here any more". It is read in Rouh instead, at the address
    // a tab opened onto it is sent to (`_rouh_address` in views.py). Task 91's
    // booklet links its text that way, 6 October 2026.
    if (/\.md$/i.test(went.pathname)) {
      goToAddress('/task/' + went.pathname.slice(WORKSPACE_ROUTE.length));
      return;
    }
    if (frame === tasksFrame()) browseGo(where);
    else frameLoad(frame, where);
    return;
  }
  goToAddress(went.pathname);
}

/* One object, opened by its own address, from wherever the address came
   from. The server turns the address into the same open instruction a
   search result carries, so there are no rules here either. */
function goToAddress(path, query) {
  // A place in the page (`#step-<id>` on a goal's map, from a quest's page) is
  // carried to the frame once it has loaded, as it is for an address opened
  // from outside (`ADDR.hash`), rather than read as part of the path.
  var raw = String(path || ''), cut = raw.indexOf('#');
  var bare = cut >= 0 ? raw.slice(0, cut) : raw, ask = bare.indexOf('?');
  // A query in the link itself counts when none is given beside it (a notice's button).
  if (query === undefined && ask >= 0) query = bare.slice(ask);
  // A workspace page's own file address, as the Control Room's Pages and a
  // notice's link write it (`pages.url_for`), is read as the address the bar
  // says for it, the way the server sends a tab opened on it there
  // (`_rouh_address` in web/views.py). Until 9 November 2026 it was no
  // address at all here, so a press on one did nothing (fr_126f4ce72bd1).
  bare = workspaceAddress(bare.split('?')[0], query);
  var want = addrRead(bare, query);
  if (!want) return false;
  if (cut >= 0 && raw.length > cut + 1) want.hash = raw.slice(cut);
  ADDR.wanted = want;
  ADDR.asked = false;
  addrAsk();
  return true;
}

/* Rouh's address for a path under `/workspace/`, and any other path as it
   is: the workspace's top is the task browser, an object's own page
   (`/workspace/_task/<folder>/`, with `?doc=` one of its notes) is that
   object, and a page or a note is `/task/<its path>`, which finds it inside a
   project as well as a task (`addressing.inside`). */
function workspaceAddress(path, query) {
  if (path.indexOf(WORKSPACE_ROUTE) !== 0) return path;
  var rel = path.slice(WORKSPACE_ROUTE.length);
  if (!rel || rel === 'index.html') return ADDR_BROWSER;
  var obj = WORKSPACE_ROUTE + '_task/';
  if (path.indexOf(obj) === 0) {
    rel = path.slice(obj.length).replace(/\/+$/, '');
    if (!rel) return path;
    var doc = new URLSearchParams(String(query || '')).get('doc') || '';
    if (doc && doc.indexOf('/') < 0 && doc.charAt(0) !== '.') rel += '/' + encodeURIComponent(doc);
  }
  return '/task/' + rel.replace(/^\/+/, '');
}

/* ---------- what a framed workspace page asks Rouh ----------

   One thing on these pages reaches out: the Ask AI drawer, which asks for
   the addresses the workspace's own proxy used to answer on. It cannot, from
   here: the page is sandboxed, so connect-src 'none' refuses the request
   before it leaves the page, and the origin the browser gives the page means
   no sign-in would go with it anyway. That sandbox is not in the way of the
   feature, it is the feature's safety: a page runs its own scripts and must
   not be able to talk to Rouh as the person.

   So the page hands the request up (pages.ask_script) and this page makes
   it, signed in, and passes the answer back a piece at a time. Two rules
   keep that from being a way round the sandbox:

   - only these three addresses are ever carried, and they are mapped here
     rather than taken from the page;
   - which page a question is about is this page's answer, read off the frame
     it loaded, never the page's own, so the worst a page can do is ask a
     question about itself.

   There was a fourth address until 21 September 2026, and it was the only
   one that wrote: the retired index page's own drag, which filed a task into
   another category through the workspace's `_categories.json`. That page and
   that route went with the rest of the separate workspace in stage three,
   and the drag came back on 22 September with the task browser. It does not
   come back through here: nothing this relay carries writes anything, and
   the three addresses above are still the whole of what it will carry.

   A change the task browser makes goes through `fileRelay` below instead,
   and the shape is the difference. This relay is handed an address and
   checks it against a list; that one is handed an action name and object
   ids, and no address at all, so there is nothing in it to point somewhere
   it was not meant to go. */

var ASK_ROUTE = '/api/askai/';
var ASK_THREAD = /^\/api\/threads\/(\d+)$/;

// The Rouh address for one of the page's own, or nothing.
function askRoute(path) {
  if (path === '/api/ask') return ASK_ROUTE + 'ask';
  if (path === '/api/threads') return ASK_ROUTE + 'threads';
  // Text typed straight into the page, and put back from the page itself
  // (`askai.type_text`): the only change the page makes without a question.
  if (path === '/api/type') return ASK_ROUTE + 'type';
  if (path === '/api/undo') return ASK_ROUTE + 'undo';
  // Comments pinned to the page (`rouh/web/comments.py`), which are the
  // owner's own and so answered at an address of Rouh's own.
  if (path === '/api/comments') return '/api/comments';
  // The highlights on it, everybody's (`rouh/web/highlights.py`).
  if (path === '/api/highlights') return '/api/highlights';
  // The passages explained in place on it (`rouh/web/definitions.py`).
  if (path === '/api/definitions') return '/api/definitions';
  // Listen to this page: its narration, and each part of it in Rouh's voice
  // (`rouh/web/page_listen.py`), for the owner only.
  if (path === '/api/listen') return '/api/page-listen';
  // The page's history, and the options kept over it (`rouh/pagehistory.py`).
  if (path === '/api/history') return ASK_ROUTE + 'history';
  if (path === '/api/keep') return ASK_ROUTE + 'keep';
  if (path === '/api/option') return ASK_ROUTE + 'option';
  var one = ASK_THREAD.exec(path);
  return one ? ASK_ROUTE + 'threads/' + one[1] : null;
}

// One part of one answer, back to the page that asked.
function askSay(frame, id, part) {
  part.type = 'rouh-page-answer';
  part.id = id;
  try { frame.contentWindow.postMessage(part, '*'); } catch (err) {}
}

// What the drawer sent, with the page it is about replaced by the one this
// page knows the frame is showing.
function askBody(raw, doc) {
  var said;
  try { said = JSON.parse(raw || '{}'); } catch (err) { said = {}; }
  if (!said || typeof said !== 'object' || said instanceof Array) said = {};
  said.doc = doc;
  return JSON.stringify(said);
}

// A refusal, in the drawer's own event shape rather than as a status.
//
// What the drawer says when a request comes back with a bad status is "Proxy
// not reachable. Start it with python3 _askai/server.py", which was true on
// the laptop and is nonsense here. It draws an `error` event as a message in
// the conversation, so a reason handed over that way is a sentence the reader
// can act on, and askai.js stays as it was written.
function askTrouble(frame, id, words) {
  askSay(frame, id, { part: 'open', status: 200 });
  askSay(frame, id, {
    part: 'chunk',
    text: 'data: ' + JSON.stringify({ type: 'error', message: words }) + '\n\n'
        + 'data: ' + JSON.stringify({ type: 'done' }) + '\n\n'
  });
  askSay(frame, id, { part: 'end' });
}

function askRelay(frame, m) {
  var path = String(m.path || '');
  var to = askRoute(path);
  var at = frame.rouhAt || '';
  var asking = path === '/api/ask';
  if (!to || at.indexOf(WORKSPACE_ROUTE) !== 0) {
    if (asking) askTrouble(frame, m.id, 'Rouh does not know which page this is.');
    else { askSay(frame, m.id, { part: 'open', status: 404 }); askSay(frame, m.id, { part: 'end' }); }
    return;
  }
  var doc;
  try { doc = decodeURIComponent(at.slice(WORKSPACE_ROUTE.length)); }
  catch (err) { askTrouble(frame, m.id, 'Rouh does not know which page this is.'); return; }
  /** @type {RequestInit} */
  var init = { credentials: 'same-origin', method: m.method === 'POST' ? 'POST' : 'GET' };
  if (init.method === 'POST') {
    // Which document it is about is this page's answer, never the page's.
    init.headers = { 'Content-Type': 'application/json' };
    init.body = askBody(m.body, doc);
  }
  var where = to + '?doc=' + encodeURIComponent(doc);
  fetch(where, init).then(function (r) {
    if (asking && !r.ok) {
      askTrouble(frame, m.id, r.status === 401 || r.status === 403
        ? 'Your sign-in has run out. Reload Rouh and ask again.'
        : 'Rouh could not answer that: the server said ' + r.status + '.');
      return;
    }
    askSay(frame, m.id, { part: 'open', status: r.status });
    var done = function () { askSay(frame, m.id, { part: 'end' }); };
    if (!r.body) {
      return r.text().then(function (t) {
        askSay(frame, m.id, { part: 'chunk', text: t });
        done();
      });
    }
    var reader = r.body.getReader(), dec = new TextDecoder();
    return (function pump() {
      return reader.read().then(function (got) {
        if (got.done) { done(); return; }
        askSay(frame, m.id, { part: 'chunk', text: dec.decode(got.value, { stream: true }) });
        return pump();
      });
    })();
  }).catch(function () {
    if (asking) askTrouble(frame, m.id, 'Rouh could not be reached. Is it still running?');
    else { askSay(frame, m.id, { part: 'open', status: 502 }); askSay(frame, m.id, { part: 'end' }); }
  });
}

/* ---------- a page's own settings ----------

   A workspace page is sandboxed: what it keeps in the browser is forgotten
   when it closes, and it cannot reach Rouh. A page that wants to remember
   what its reader chose on it - a part hidden, a tab picked - hands it up
   here, and this page keeps it in Rouh, signed in, for this person, on any
   device (`rouh/pagestate.py`):

     page -> {type: 'rouh-page-state', op: 'get', key}
     page <- {type: 'rouh-page-state', op: 'value', key, value}   (null: none kept)
     page -> {type: 'rouh-page-state', op: 'set', key, value}     (null removes it)

   Like the Ask AI relay above, which page the settings belong to is read off
   the frame this page loaded, never taken from the page, so the worst a page
   can do is change its own settings. The requests of one frame go one after
   another, so a save never overtakes the read before it. */

var STATE_ROUTE = '/api/page-state';

function stateRelay(frame, m) {
  var at = frame.rouhAt || '';
  var key = m.key;
  if (at.indexOf(WORKSPACE_ROUTE) !== 0 || typeof key !== 'string' || !key || key.length > 200
      || (m.op !== 'get' && m.op !== 'set')) return;
  var doc;
  try { doc = decodeURIComponent(at.slice(WORKSPACE_ROUTE.length).split('?')[0]); }
  catch (err) { return; }
  var where = STATE_ROUTE + '?doc=' + encodeURIComponent(doc);
  var value = m.value === undefined ? null : m.value;
  /** @type {Promise<unknown>} */
  var before = frame.rouhState || Promise.resolve();
  frame.rouhState = before.then(/** @returns {Promise<unknown>} */ function () {
    if (m.op === 'set') {
      return fetch(where, {
        credentials: 'same-origin', method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, value: value })
      });
    }
    return fetch(where, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (got) {
        // Nothing answered, when the read failed: the page keeps what it has.
        if (!got || !got.settings || frame.rouhAt !== at) return;
        var kept = Object.prototype.hasOwnProperty.call(got.settings, key) ? got.settings[key] : null;
        try {
          frame.contentWindow.postMessage(
            { type: 'rouh-page-state', op: 'value', key: key, value: kept }, '*');
        } catch (err) {}
      });
  }).catch(function () {});
}

/* ---------- what the task browser saves ----------

   The task browser is a workspace page like any other: sandboxed, with an
   origin of its own and connect-src 'none', so it can no more write than it
   can read. It hands the change up and this page makes the request, signed
   in (pages.FILE_MESSAGE).

   Three things keep that from being a way round the sandbox:

   - it carries an action name and object ids, never an address, so there is
     nothing in it to aim somewhere else. One route answers it and the server
     decides what each action may do (objectindex.change);
   - only the task browser's own frame is listened to. A card on the canvas
     frames pages too, and a page in one of those asking to move a task is
     ignored rather than answered;
   - the answer carries the index as it is afterwards, refusal and all, so
     the page draws what is on disk rather than what it asked for. */

var FILING = '/api/workspace/filing';

function fileSay(frame, id, said) {
  said.type = 'rouh-frame-filed';
  said.id = id;
  try { frame.contentWindow.postMessage(said, '*'); } catch (err) {}
}

function fileRelay(frame, m) {
  var id = m.id;
  if (frame !== tasksFrame() || !m.body || typeof m.body !== 'object'
      || m.body instanceof Array) {
    fileSay(frame, id, { ok: false, error: 'Rouh will not save that from here.' });
    return;
  }
  // Move to new task, from a subtask's line in the task browser: what the new
  // task is called is asked here first (`askTaskName`), and nothing is sent
  // when the box is cancelled.
  if (m.body.action === 'move_step' && m.body.where === '+new' && !m.body.name) {
    askTaskName(String(m.body.label || ''), String(m.body.title || '')).then(function (name) {
      if (name === null) { fileSay(frame, id, { ok: false, cancelled: true, error: '' }); return; }
      fileRelay(frame, { id: id, body: Object.assign({}, m.body, { name: name }) });
    });
    return;
  }
  fetch(FILING, {
    credentials: 'same-origin', method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(m.body)
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      fileSay(frame, id, {
        // The index for the task browser, and, when the change was made on
        // a project's own page, that project as it now stands: both pages
        // draw what the server says is saved rather than what they typed.
        ok: !!j.ok && r.ok, index: j.index || null, project: j.project || null,
        // What the server did, when it has more to say than the page knows.
        did: j.did || '',
        error: j.error || (r.ok ? '' : (r.status === 401 || r.status === 403
          ? 'Your sign-in has run out. Reload Rouh and try again.'
          : 'Rouh could not save that: the server said ' + r.status + '.'))
      });
    });
  }).catch(function () {
    // In the words Petar gave it (fr_1b64390a0545): the one thing the page
    // says after a change is that it was not made, and why.
    fileSay(frame, id, { ok: false, error: 'Couldn’t make that change: Rouh is not connected right now.' });
  });
}

/* ---------- what a project's own page asks for ----------

   Two things on that page are not a filing action and could not be one: the
   box at the top that starts a chat, and the Add files button.

   A chat is the socket's, not a route's. Making one and moving into it is
   `new_chat`, which this tab follows, so what comes up out of the frame is
   handed to the socket exactly as the New chat button in the rail is - with
   the project's id on it, so the conversation is made inside the project
   whose page it was started from.

   A file is bytes, and the frame cannot send them anywhere: it reads the
   file itself and hands the bytes up, and this page makes the upload signed
   in. The same two rules as everything else hold: only the canvas's own
   frame is listened to, and what is carried is an object id and never a path
   - the server works out where a project's files live from that id
   (`objectindex.files_key`). */

var PROJECT_FILE = '/api/workspace/file';

//: What was typed into a project's box before the chat to say it in exists.
//: One at a time: a second press before the first chat opens replaces it,
//: which is what pressing twice means.
var PENDING_SAY = '';

function projectSay(frame, id, said) {
  said.type = 'rouh-frame-project';
  said.id = id;
  try { frame.contentWindow.postMessage(said, '*'); } catch (err) {}
}

function projectChat(frame, m) {
  if (frame !== tasksFrame() || typeof m.project !== 'string' || !m.project) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not start a chat from here.' });
    return;
  }
  if (typeof m.said === 'string' && m.said.trim() && !ownPage(frame)) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not send words from this page.' });
    return;
  }
  PENDING_SAY = typeof m.said === 'string' ? m.said.slice(0, 20000).trim() : '';
  chatIsWanted();
  if (!send({ type: 'new_chat', folder: m.project })) {
    PENDING_SAY = '';
    projectSay(frame, m.id, { ok: false, error: 'Rouh is not connected, so that chat was not started.' });
    return;
  }
  projectSay(frame, m.id, { ok: true });
}

/* Start chat, the one chat button on a task's or a step's own page
   (`taskpage.js`), floating in its bottom right corner.

   It starts a chat and never continues one. Petar, 23 September 2026: "i
   don't need a button to continue chat, I need a button to start a chat".
   So it asks for a new conversation about the task (`new_chat` with the
   task on it, `conversations.start_for_task`): the task's own while nothing
   has been said about it, and a new one beside it once something has. The
   task's own conversation is still what opening the task brings back, and
   the page lists every chat the task holds.

   And it puts that conversation **on the screen**, with the cursor in it,
   which it was not when the page came from the task browser: that takes
   the whole window and folds the conversation away.

   Which task is Rouh's own answer, read off the page it framed
   (`CANVAS.step`, else `CANVAS.task`), and never the frame's: the frame
   says only that its button was pressed. **A subtask's page starts a chat
   of the subtask's own**, never its task's. Until 29 September 2026 a step
   answered with its task, and Petar, pressing it on a subtask he had
   reached from the Control Room: "I press the new chat [button] and I go
   to the parents chat" (fr_3113364c29fa). The subtask's chat has its task
   as background, names both at its head, and can send a decision up to the
   task (`rouh/subtasknotes.py`). Pressed again while its empty chat is the
   one open, it is the same chat: two presses are not two chats.

   **An answer**, from the box at the top of a task that is waiting on the
   person, is the same press with the words to say on it (`say`): which
   task, what it asked, and what they picked or wrote in that box. It does
   not start a chat. Petar, 24 September 2026 (fr_d262eeec7d44): "that
   should go to the main chat, not opne a new chat. only open a new chat If
   there was no such chat before that." So it asks for the chat the task
   already has (`answer_chat`, `conversations.answer_for_task`), and a new
   one only when it has none; the server moves this tab there, or says it
   is the one open already. The words are sent in it as soon as it is
   open, exactly as if typed, and with them what was asked and what was
   answered (`answers`), so the server writes the answer down against the
   task (`rouh/answering.py`). Which task that is, is this page's answer
   again, never the frame's. The task's page is loaded again once Rouh has
   answered, and then says which job has it (`taskAnswerSettled`). */
function taskChat(frame, m) {
  var task = CANVAS.task;
  if (frame !== tasksFrame() || !task) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not start a chat from here.' });
    return;
  }
  if (typeof m.say === 'string' && m.say.trim() && !ownPage(frame)) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not send words from this page.' });
    return;
  }
  TASK_SAY = null;
  if (typeof m.say === 'string' && m.say.trim()) {
    var answers = m.answers && typeof m.answers === 'object' ? m.answers : null;
    TASK_SAY = {
      text: m.say.trim().slice(0, 6000),
      task: task,
      answers: answers ? {
        task: task,
        asked: String(answers.asked || '').slice(0, 1000),
        answer: String(answers.answer || '').slice(0, 4000)
      } : null,
      at: CANVAS.at
    };
  }
  var chat = CHATS ? chatById(CHATS.active) : null;
  if (TASK_SAY) {
    // An answer: into the chat the task already has, which the server
    // picks, and moves this tab to unless it is the one open already.
    shared.TASK_CHAT_ASKED = task;
    if (!send({ type: 'answer_chat', task: task })) {
      shared.TASK_CHAT_ASKED = '';
      TASK_SAY = null;
      projectSay(frame, m.id, { ok: false, error: 'Rouh is not connected, so the answer was not sent.' });
      return;
    }
  } else if (!(chat && chat.draft && chat.task === (CANVAS.step || task))) {
    // Start chat, on the subtask when the page is a subtask's. Its empty
    // chat already the one open, there is nothing to ask for.
    task = CANVAS.step || task;
    shared.TASK_CHAT_ASKED = task;
    if (!send({ type: 'new_chat', task: task })) {
      shared.TASK_CHAT_ASKED = '';
      projectSay(frame, m.id, { ok: false, error: 'Rouh is not connected, so the chat was not started.' });
      return;
    }
  }
  chatIsWanted();
  // A phone shows one pane at a time and the press was for the other one.
  // At a desk the cursor goes into the box, ready for the first words; on a
  // phone that would put the keyboard over the conversation they have only
  // just been taken to, so there it waits for a tap like every other box.
  if (narrow()) setPane('chat');
  else if (input) input.focus();
  projectSay(frame, m.id, { ok: true });
}

/* Whether the frame holds one of Rouh's own pages of an object - a task's,
   a step's or a project's, drawn by `objectindex.py` with only Rouh's own
   script in it - rather than a page a job built, which is loaded into the
   same frame and runs whatever scripts it was written with. Only Rouh's own
   pages may have words sent in the person's name: the question box's
   answer, the project page's box. A built page can open a chat, and never
   speak in it. Read off what this page loaded into the frame
   (`frame.rouhAt`), never off anything the page says. */
function ownPage(frame) {
  return String(frame && frame.rouhAt || '').indexOf(TASK_PREFIX) === 0;
}

// What a waiting task's page asked to have said in the chat it goes to:
// the words, which task, what was asked and answered, and which page it
// was pressed on.
var TASK_SAY = null;
// The words that carry an answer, until the one send that takes them.
shared.TYPED_ANSWER = null;
// The task's page an answer was sent from, until Rouh has answered it.
var ANSWERED_ON = '';
// An answer in the box, waiting for the turn already running in its chat
// to end: that chat, and the words (`taskSaidIt`).
var ANSWER_HELD = null;

// The chat the answer asked for is open: the words go in the box and are
// sent, through the composer, so they are drawn, stored and answered
// exactly as anything typed is. The answer rides on that one message and
// on no other (`sendTyped`). Only in a chat of the task it answers: a
// switch to anything else is somebody else's, and the one asked for is
// still coming.
//
// The chat is the task's own, not a new one, so Rouh may be in the middle
// of answering something else in it, and a message typed then is not sent
// (`S.busy`). The words wait in the box, where they can be seen, and go the
// moment that turn is over (`answerHeldGo`).
function taskSaidIt() {
  if (!TASK_SAY || !input) return;
  var here = CHATS ? chatById(CHATS.active) : null;
  if (!here || here.task !== TASK_SAY.task) return;
  var said = TASK_SAY;
  TASK_SAY = null;
  input.value = said.text;
  growInput();
  shared.TYPED_ANSWER = said.answers ? { text: said.text, answers: said.answers } : null;
  ANSWERED_ON = said.at || '';
  if (S.busy) { ANSWER_HELD = { chat: here.id, text: said.text }; return; }
  sendTyped();
}

// The turn the answer waited for is over. Sent, if the person is still in
// that chat and the words in the box are still the answer's; otherwise
// they are theirs to send or not.
function answerHeldGo() {
  var held = ANSWER_HELD;
  ANSWER_HELD = null;
  if (!held || held.chat !== CHATS.active || S.busy || !input
      || input.value.trim() !== held.text) return;
  sendTyped();
}

// The server's word on an answer's chat when nothing was switched: it is
// the chat open already, so the answer goes now; or there is no such
// task, and it goes nowhere rather than into whatever opens next.
function taskAnswerHere(chat) {
  shared.TASK_CHAT_ASKED = '';
  if (!TASK_SAY) return;
  if (!chat) {
    TASK_SAY = null;
    notify('That task is not there any more, so the answer was not sent.', { tone: 'warning' });
    return;
  }
  taskSaidIt();
}

/* Dismiss, on the question box of a task's page: the question closed
   without an answer. Petar, 24 September 2026: "i also need the option to
   dismiss it". Nothing is said in any chat and no job is started; the
   server writes it down against the task and the question as the box
   showed it (`rouh/answering.py`), and the lists stop marking the task as
   waiting on the person. Which task is this page's answer, as for an
   answer, and only Rouh's own page of it may ask (`ownPage`). */
function taskDismiss(frame, m) {
  var task = CANVAS.task;
  if (frame !== tasksFrame() || !task || !ownPage(frame)) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not dismiss that from here.' });
    return;
  }
  var ok = send({ type: 'dismiss_question', task: task,
                  asked: String(m.asked || '').slice(0, 1000) });
  projectSay(frame, m.id, ok ? { ok: true }
    : { ok: false, error: 'Rouh is not connected, so it was not dismissed.' });
}

/* Rename and Delete, from the three dots on a task's or a subtask's own
   page (`taskpage.js`). Petar, 27 September 2026 (fr_3273da8d3be9): "just
   like a chat, I should have ... and then a menu that allows me to rename
   and delete this task."

   Which task is this page's answer: the folder the frame is at, as for a
   step of a goal, and never anything the frame says. Only Rouh's own page
   of it may ask (`ownPage`). The server finds the task at that folder
   (`owning.task_at`).

   Delete opens the one delete dialog every Delete here opens (`askDelete`),
   named after the task, and nothing goes until its button is pressed. The
   page it was pressed on is then left for the level above it
   (`canvasLeftBehind`). Rename is written by the server and said back as
   `object_changed`; the page has already put the new name up, and puts the
   old one back if the answer is no. */
var PAGE_RENAME = null;

function taskPageFolder() {
  var at = String(CANVAS.at || '');
  if (at.indexOf(TASK_PREFIX) !== 0) return '';
  var folder = at.slice(TASK_PREFIX.length).split('?')[0].split('#')[0].replace(/\/+$/, '');
  try { folder = decodeURIComponent(folder); } catch (err) {}
  return folder;
}

/* A press on the decision drawn on a task's or a goal step's own page
   (`decision.js`, `objectindex._decision_mount`). The page cannot reach Rouh,
   so it hands the press up, and it is sent only from Rouh's own page in the
   canvas, and only for that page's own question: which page it is comes from
   the canvas, never from the frame, and the server refuses a decision that is
   not this folder's (`from_page`, `decisions.of_page`). What the server said
   goes back down as it is, a 409 asking for the risk to be confirmed with it. */
var DECISION_ACTS = ['get', 'answer', 'delegate', 'snooze', 'wake', 'undo', 'dismiss'];

/** @param {HTMLIFrameElement} frame @param {any} m */
function taskDecision(frame, m) {
  var folder = taskPageFolder();
  var id = Number(m.decision);
  if (frame !== tasksFrame() || !ownPage(frame) || !folder || DECISION_ACTS.indexOf(m.act) < 0
      || !(id > 0)) {
    projectSay(frame, m.id, { ok: false, status: 403,
                              out: { error: 'Rouh will not answer that from here.' } });
    return;
  }
  var got = m.body && typeof m.body === 'object' ? m.body : {};
  var body = { act: m.act, from_page: folder };
  if (Array.isArray(got.choice)) body.choice = got.choice.slice(0, 8).map(String);
  if (typeof got.text === 'string') body.text = got.text.slice(0, 4000);
  if (typeof got.confirm === 'string') body.confirm = got.confirm.slice(0, 40);
  if (typeof got.until === 'number') body.until = got.until;
  var get = m.act === 'get';
  fetch('/api/decisions/' + id + (get ? '?from_page=' + encodeURIComponent(folder) : '/act'), {
    method: get ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-Time-Zone': browserZone() },
    body: get ? undefined : JSON.stringify(body)
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (out) {
      projectSay(frame, m.id, { ok: r.ok, status: r.status, out: out });
    });
  }).catch(function () {
    projectSay(frame, m.id, { ok: false, status: 0,
                              out: { error: 'Rouh could not be reached. Is it still running?' } });
  });
}

/* PDF, from one item's own menu on a task's page (`taskpage.js`,
   `objectindex._item_line`): a PDF of that item alone, a page or a .md, in
   the folder framed here, which is the task's and never the frame's word for
   it. The item is a path inside that folder and nothing that climbs out of
   it. It is made on the server while he does anything else, and the
   notification that it is ready has its download (`rouh/page_pdf.py`). */
/** @param {HTMLIFrameElement} frame @param {any} m @param {string} folder */
function taskItemPdf(frame, m, folder) {
  var item = String(m.item || '').replace(/^\/+/, '');
  var paper = m.paper === 'a4' ? 'a4' : 'letter';
  if (!item || item.split('/').some(function (p) { return !p || p === '.' || p === '..'; })) {
    projectSay(frame, m.id, { ok: false, error: 'That is not an item of this task.' });
    return;
  }
  var name = item.split('/').pop();
  fetch('/api/page-pdf', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ at: folder + '/' + item, paper: paper })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'The PDF could not be started.' }; });
  }).catch(function () {
    return { error: 'The PDF could not be started: Rouh did not answer.' };
  }).then(function (got) {
    if (!got || got.error) {
      var why = (got && got.error) || 'The PDF could not be started.';
      notify(why, { tone: 'error', kind: 'page_pdf' });
      projectSay(frame, m.id, { ok: false, error: why });
      return;
    }
    notify(got.already ? 'A PDF of ' + name + ' is already being made.'
                       : 'Making a PDF of ' + name + ' for ' + got.paper + ' paper.',
           { tone: 'info', kind: 'page_pdf',
             body: 'Only this item. You will be told here when it is ready, with its download.' });
    projectSay(frame, m.id, { ok: true });
  });
}

/* Check sources on a page's line under its task's Sources
   (`objectindex._sources_section`): that one page's sources read against
   what it says, started here, and its Sources opened, where it is seen being
   read and what was found appears (`sourcespage.js`). Nothing is checked
   without this press (fr_563bcb1bdb26). */
/** @param {HTMLIFrameElement} frame @param {any} m @param {string} folder */
function taskCheckSources(frame, m, folder) {
  var item = String(m.item || '').replace(/^\/+/, '');
  if (!item || item.split('/').some(function (p) { return !p || p === '.' || p === '..'; })) {
    projectSay(frame, m.id, { ok: false, error: 'That is not a page of this task.' });
    return;
  }
  var doc = folder + '/' + item;
  fetch('/api/sources', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc: doc, check: true })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'The check could not be started.' }; });
  }).catch(function () {
    return { error: 'The check could not be started: Rouh did not answer.' };
  }).then(function (got) {
    if (!got || got.error) {
      projectSay(frame, m.id, { ok: false, error: (got && got.error) || 'The check could not be started.' });
      return;
    }
    projectSay(frame, m.id, { ok: true });
    goToAddress('/sources/' + doc.split('/').slice(0, -1).join('/'));
  });
}

/* What a chat's or a fork's own three dots on a task's page ask for
   (`objectindex._chat_line`): its PDF, its cards, a pin, or Delete, each
   what the same item in its dots in Rouh's own lists does (`rowMenuAct`).
   The PDF is kept in the task framed here, which the server checks the chat
   is one of (`page_pdf.chat_place`). */
/** @param {HTMLIFrameElement} frame @param {any} m @param {string} folder */
function taskChatAct(frame, m, folder) {
  var id = String(m.chat || '');
  var name = String(m.name || '').slice(0, 200) || 'this chat';
  if (m.act === 'cards') {
    drawnOpen(id, name);
    projectSay(frame, m.id, { ok: true });
    return;
  }
  if (m.act === 'pin' || m.act === 'unpin') {
    var sent = send({ type: 'pin_object', kind: 'chat', id: id, on: m.act === 'pin' });
    projectSay(frame, m.id, sent ? { ok: true }
      : { ok: false, error: 'Rouh is not connected, so the pin was not changed.' });
    return;
  }
  if (m.act === 'delete') {
    askDelete('chat', id, name, '', CANVAS.at);
    projectSay(frame, m.id, { ok: true });
    return;
  }
  var paper = m.paper === 'a4' ? 'a4' : 'letter';
  fetch('/api/page-pdf', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat: id, at: folder, paper: paper })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'The PDF could not be started.' }; });
  }).catch(function () {
    return { error: 'The PDF could not be started: Rouh did not answer.' };
  }).then(function (got) {
    if (!got || got.error) {
      var why = (got && got.error) || 'The PDF could not be started.';
      notify(why, { tone: 'error', kind: 'page_pdf' });
      projectSay(frame, m.id, { ok: false, error: why });
      return;
    }
    notify(got.already ? 'A PDF of the chat ' + name + ' is already being made.'
                       : 'Making a PDF of the chat ' + name + ' for ' + got.paper + ' paper.',
           { tone: 'info', kind: 'page_pdf',
             body: 'The whole conversation, with its cards. You will be told here when it is ready, with its download.' });
    projectSay(frame, m.id, { ok: true });
  });
}

function taskPageAct(frame, m) {
  // A task's or a step's icon, from the icon picker in the task browser or on
  // a task's page (`taskicon.js`), named by the task's id as every change the
  // task browser makes names it (`taskIconAct`).
  if (m.act === 'icon') {
    taskIconAct(frame, m);
    return;
  }
  // The icon picker's list of every emoji and the words each is found by,
  // which the page cannot fetch itself (`emojiList`).
  if (m.act === 'emoji') {
    emojiList(frame, m);
    return;
  }
  // Delete, from the three dots at the end of a task's line in the task
  // browser (`rowMenu` in taskbrowser.js): Rouh's own dialog, which says what
  // goes with it before anything goes, and the browser loaded again after.
  if (frame === tasksFrame() && CANVAS.at === BROWSE_ROOT && m.act === 'delete') {
    if (typeof m.task !== 'string' || !m.task) {
      projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that task from here.' });
      return;
    }
    askDelete('task', m.task, String(m.name || ''), '', BROWSE_ROOT);
    return;
  }
  var folder = taskPageFolder();
  if (frame !== tasksFrame() || !ownPage(frame) || !folder
      || ['rename', 'delete', 'archive', 'unarchive', 'move', 'new_task', 'promote', 'pin', 'unpin',
          'drop_file', 'mine', 'not_mine', 'rouhs', 'pdf', 'cards', 'slack_unlink',
          'slack_remove', 'check_sources', 'doc_changes', 'doc_names', 'doc_on_page', 'doc_add',
          'doc_comments', 'doc_comments_apply', 'deck_rehearse', 'deck_picture', 'deck_rehearsed', 'doc_attach',
          'retitle', 'to_send', 'open_item', 'task_time'].indexOf(m.act) === -1) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that task from here.' });
    return;
  }
  // A chat's own dots on this page (`objectindex._chat_line`).
  if (m.chat) {
    if (['pdf', 'cards', 'pin', 'unpin', 'delete'].indexOf(m.act) === -1) {
      projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that chat from here.' });
      return;
    }
    taskChatAct(frame, m, folder);
    return;
  }
  // A subtask's own dots on its task's page (`objectindex._subtask_dots`):
  // the same as its own page's, for the folder under the one framed here,
  // and never anything that climbs out of it.
  var sub = '';
  if (m.sub) {
    sub = String(m.sub).replace(/^\/+|\/+$/g, '');
    if (!sub || sub.split('/').some(function (p) { return !p || p === '.' || p === '..'; })
        || ['pdf', 'pin', 'unpin', 'move', 'new_task', 'promote', 'archive', 'unarchive', 'delete'].indexOf(m.act) === -1) {
      projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that subtask from here.' });
      return;
    }
    folder = folder + '/' + sub;
  }
  if (m.act === 'cards') {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that task from here.' });
    return;
  }
  if (m.act === 'pdf') {
    taskItemPdf(frame, m, folder);
    return;
  }
  if (m.act === 'check_sources') {
    taskCheckSources(frame, m, folder);
    return;
  }
  if (m.act === 'retitle') {
    // Rename, from a page's own dots on this page: the page's own name, the file
    // left where it is (`pagehistory.retitle`). The page drew it already, so only
    // a refusal has anything to say.
    var item = String(m.item || '').replace(/^\/+/, '');
    var called = String(m.title || '').replace(/\s+/g, ' ').trim().slice(0, 200);
    if (!item || !called || item.split('/').some(function (p) { return !p || p === '.' || p === '..'; })) {
      projectSay(frame, m.id, { ok: false, error: called ? 'That page cannot be renamed from here.'
                                                         : 'A name cannot be empty.' });
      return;
    }
    clockPost(FILING, { action: 'retitle_page', folder: folder, item: item, title: called })
      .then(function (answer) {
        var out = answer.out || {};
        projectSay(frame, m.id, answer.ok && out.ok ? { ok: true }
          : { ok: false, error: out.error || 'It could not be renamed.' });
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'doc_names') {
    // The names Drive gives the documents the task's notes link to, which the page drew with
    // the notes' own words until now (`rouh/task_docs.py`).
    fetch('/api/task-docs/names', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder })
    }).then(function (r) {
      return r.json().catch(function () { return {}; });
    }).catch(function () { return {}; }).then(function (got) {
      projectSay(frame, m.id, got && got.ok ? { ok: true, names: got.names || {} }
                                            : { ok: false, error: (got && got.error) || '' });
    });
    return;
  }
  if (m.act === 'doc_add') {
    // Add a document (night 23, `rouh/task_docs.py`): a Google Doc, Sheet or Slides link
    // pasted under the task's Documents, kept in the task's notes.
    fetch('/api/task-docs/add', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, link: String(m.link || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be added.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, doc: got.doc || {}, readable: !!got.readable }
        : { ok: false, error: (got && got.error) || 'It could not be added.' });
    });
    return;
  }
  if (m.act === 'to_send') {
    // To send from your mail (night 24, `rouh/to_send.py`): Write it in Gmail pressed, Not
    // sending, or its Undo, on a reply the task drafted for the person to send themselves.
    fetch('/api/to-send', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, n: Number(m.n), do: String(m.do || ''),
                             subject: String(m.subject || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'That did not go through.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok ? { ok: true }
        : { ok: false, error: (got && got.error) || 'That did not go through.' });
    });
    return;
  }
  if (m.act === 'open_item') {
    // Open on this task (night 28, `rouh/open_items.py`): Done on an open item of the task's
    // Where this stands, or its Undo, kept in the task's notes.
    fetch('/api/open-items', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, key: String(m.key || ''), do: String(m.do || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'That did not go through.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok ? { ok: true }
        : { ok: false, error: (got && got.error) || 'That did not go through.' });
    });
    return;
  }
  if (m.act === 'task_time') {
    // Time before its date (night 32, `rouh/task_time.py`): the free time left before the date the
    // task's notes say it is due, or focus time put in one of its gaps.
    fetch('/api/task-time', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, act: String(m.do || ''), start: String(m.start || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be done.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, hours: got.hours, until: String(got.until || ''), gaps: got.gaps || [],
            said: String(got.said || ''), link: String(got.link || '') }
        : { ok: false, error: (got && got.error) || 'It could not be done.' });
    });
    return;
  }
  if (m.act === 'doc_attach') {
    // Attach to a meeting (night 31, `rouh/meeting_attach.py`): the meetings a document under the
    // task's Documents could go on, or, with a key, the document attached to that one.
    fetch('/api/task-docs/attach', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: String(m.doc || ''), key: String(m.key || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be done.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, meetings: got.meetings || [], doc: String(got.doc || ''), said: String(got.said || ''),
            already: !!got.already }
        : { ok: false, error: (got && got.error) || 'It could not be done.' });
    });
    return;
  }
  if (m.act === 'deck_rehearse' || m.act === 'deck_picture' || m.act === 'deck_rehearsed') {
    // Rehearse (night 27, `rouh/rehearse.py`): a deck under the task's Documents read slide by
    // slide, a picture of one slide, and a rehearsal that reached its end.
    var deckPath = { deck_rehearse: 'rehearse', deck_picture: 'slide-picture', deck_rehearsed: 'rehearsed' }[m.act];
    fetch('/api/task-docs/' + deckPath, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: String(m.doc || ''), slide: String(m.slide || ''),
                             seconds: Number(m.seconds) || 0, seen: Number(m.seen) || 0,
                             count: Number(m.count) || 0 })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be read.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, deck: got.deck || null, url: String(got.url || '') }
        : { ok: false, error: (got && got.error) || 'It could not be read.' });
    });
    return;
  }
  if (m.act === 'doc_comments' || m.act === 'doc_comments_apply') {
    // Comments on the task's documents (night 26, `rouh/task_comments.py`): the open comments
    // on its Google documents, or on one, and Have a job apply them.
    var applying = m.act === 'doc_comments_apply';
    fetch(applying ? '/api/task-docs/apply-comments' : '/api/task-docs/comments', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: String(m.doc || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be read.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? (applying ? { ok: true, said: String(got.said || ''), again: !!got.again }
                    : { ok: true, docs: got.docs || {} })
        : { ok: false, error: (got && got.error) || 'It could not be read.' });
    });
    return;
  }
  if (m.act === 'doc_on_page') {
    // Which paragraphs of a Google Doc the task's notes link to are on the task's pages word
    // for word, read in place on its page (`rouh/doc_on_page.py`).
    fetch('/api/task-docs/on-page', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: String(m.doc || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be read.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, text: String(got.text || '') }
        : { ok: false, error: (got && got.error) || 'It could not be read.' });
    });
    return;
  }
  if (m.act === 'doc_changes') {
    // What changed in a Google document the task's notes link to, read in place on its
    // page (`rouh/task_docs.py`).
    fetch('/api/task-docs/changes', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: String(m.doc || '') })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'It could not be read.' }; });
    }).catch(function () {
      return { error: 'Rouh could not be reached. Try again in a moment.' };
    }).then(function (got) {
      projectSay(frame, m.id, got && got.ok
        ? { ok: true, text: String(got.text || '') }
        : { ok: false, error: (got && got.error) || 'It could not be read.' });
    });
    return;
  }
  if (m.act === 'pin' || m.act === 'unpin') {
    // The pin in the page's header: this task or step alone, pinned to the
    // Control Room or taken off it (`rouh/pinning.py`). The page drew it
    // already, so only a refusal has anything to say.
    clockPost(FILING, { action: 'pin', folder: folder, on: m.act === 'pin' })
      .then(function (answer) {
        var out = answer.out || {};
        if (!answer.ok || !out.ok) {
          projectSay(frame, m.id, { ok: false, error: out.error || 'The pin could not be changed.' });
          return;
        }
        projectSay(frame, m.id, { ok: true });
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'slack_unlink' || m.act === 'slack_remove') {
    // A Slack channel linked to this task unlinked, or a decision written from
    // it taken out of the task's notes, and the channels as they are
    // afterwards (`rouh/slack_tasks.py`).
    clockPost(FILING, { action: m.act, folder: folder, slack: String(m.slack || '') })
      .then(function (answer) {
        var out = answer.out || {};
        projectSay(frame, m.id, answer.ok && out.ok
          ? { ok: true, slack: out.slack || [] }
          : { ok: false, error: out.error || 'That could not be changed.', slack: out.slack });
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'drop_file') {
    // The cross on a file uploaded to it: that file off this task, and the
    // task's files as they are afterwards (`objectindex._drop_task_file`).
    clockPost(FILING, { action: 'drop_task_file', folder: folder, file: String(m.file || '') })
      .then(function (answer) {
        var out = answer.out || {};
        projectSay(frame, m.id, answer.ok && out.ok
          ? { ok: true, files: out.files || [] }
          : { ok: false, error: out.error || 'That file could not be taken off.' });
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'archive' || m.act === 'unarchive') {
    // The task browser's own change, named by the folder framed here, and
    // the page loaded again to say what it is now (`rouh/archiving.py`).
    var at = CANVAS.at;
    clockPost(FILING, { action: 'archive', folder: folder, on: m.act === 'archive' })
      .then(function (answer) {
        var out = answer.out || {};
        if (!answer.ok || !out.ok) {
          projectSay(frame, m.id, { ok: false, error: out.error || 'It could not be archived.' });
          return;
        }
        projectSay(frame, m.id, { ok: true });
        // The bar's menus of steps and of tasks leave the archived out, and
        // were read once and kept: read again, so it goes or comes back now.
        CANVAS.taskData = null;
        TASKS.asked = false;
        if (tasksViewing()) drawCrumb();
        if (tasksViewing() && CANVAS.at === at) frameLoad(frame, at);
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'mine' || m.act === 'not_mine' || m.act === 'rouhs') {
    // Whose task it is: his own, made for somebody else, or made by one of
    // Rouh's processes, each of the last two out of his own task list until
    // Others' tasks or Made by Rouh shows it (`rouh/task_origin.py`). The page
    // is loaded again, which says who made it now, and that is all that is
    // said: a change that worked is not announced.
    var was = CANVAS.at;
    clockPost(FILING, { action: 'mine', folder: folder,
      to: m.act === 'mine' ? 'person' : m.act === 'rouhs' ? 'process' : 'other' })
      .then(function (answer) {
        var out = answer.out || {};
        if (!answer.ok || !out.ok) {
          projectSay(frame, m.id, { ok: false, error: out.error || 'Whose task it is could not be changed.' });
          return;
        }
        projectSay(frame, m.id, { ok: true });
        if (tasksViewing() && CANVAS.at === was) frameLoad(frame, was);
      }).catch(function () {
        projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
      });
    return;
  }
  if (m.act === 'move') {
    // Rouh's own picker, over the page (`moveOpen`), for the folder framed
    // here. The page is loaded at its new address once it has moved.
    moveOpen(folder, sub ? String(m.name || '') : '');
    projectSay(frame, m.id, { ok: true });
    return;
  }
  if (m.act === 'new_task' || m.act === 'promote') {
    // Out of its task, with no picker: the first subtask of a new task, or a
    // task of its own, in the project its task is in (`rouh/moving.py`).
    // Named as its line names it: its number, then what it is called.
    var title = sub ? String(m.title || '') : CANVAS.title;
    var num = (folder.split('/').pop().match(/^\d+(?:-\d+)?(?=[.-])/) || [''])[0];
    var named = m.act === 'promote' ? Promise.resolve('')
      : askTaskName((num ? num + ' \u00b7 ' : '') + title, title);
    named.then(function (name) {
      if (name === null) { projectSay(frame, m.id, { ok: true }); return null; }
      return moveSend(folder, m.act === 'promote' ? '+task' : '+new', true, name).then(function (out) {
        projectSay(frame, m.id, out.ok ? { ok: true } : { ok: false, error: out.error });
      });
    });
    return;
  }
  if (m.act === 'delete') {
    // A subtask deleted from its task's page leaves that page where it is,
    // loaded again without it (`canvasLeftBehind`).
    var name = (sub ? String(m.name || '') : CANVAS.title) || folder.split('/').pop();
    askDelete('task', '', name, folder, sub ? CANVAS.at : '');
    projectSay(frame, m.id, { ok: true });
    return;
  }
  var title = String(m.title || '').replace(/\s+/g, ' ').trim().slice(0, 200);
  if (!title) {
    projectSay(frame, m.id, { ok: false, error: 'A name cannot be empty.' });
    return;
  }
  if (!send({ type: 'rename_object', kind: 'task', folder: folder, title: title })) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh is not connected, so it was not renamed.' });
    return;
  }
  PAGE_RENAME = { frame: frame, id: m.id, folder: folder, title: title, at: CANVAS.at };
}

// The server's answer to a rename a task's page asked for. True when it was
// that one, which is then said back to the page and nowhere else.
/** @param {import('./protocol').FromServer<'object_changed'>} m */
function taskPageRenamed(m) {
  var asked = PAGE_RENAME;
  if (!asked || !m || m.kind !== 'task' || m.act !== 'rename') return false;
  PAGE_RENAME = null;
  projectSay(asked.frame, asked.id, m.ok ? { ok: true }
    : { ok: false, error: m.why || 'It could not be renamed.' });
  // The window's own title is the page's, read as it arrived.
  if (m.ok && CANVAS.at === asked.at) {
    CANVAS.title = asked.title;
    addrTouch();
  }
  if (m.ok && CANVAS.task && asked.folder.indexOf(CANVAS.task) === 0) {
    // The bar over the canvas says the task's name and its steps' names,
    // read off the folder once and kept: read again.
    CANVAS.taskData = null;
    TASKS.asked = false;
    if (tasksViewing()) drawCrumb();
  }
  return true;
}

/* A step of a goal, acted on from its own page (`taskpage.js`): Start
   with Rouh or Do it now, Mark done, Reopen, and on its How to do it page
   Save and a tick on one of the person's steps. Until 27 September 2026 the
   Goals page's Open brought the person to a page that said nothing about
   the step and had nothing on it to press (fr_89eebb50bd23).

   Which step is this page's answer, read off the page it framed - where
   the frame is, which is the step's folder - and never the frame's: the
   frame says only which button was pressed. The server finds the goal
   above that folder, and refuses one that is not a step of a goal. Started,
   the goal's chat opens beside the page, where Rouh is working on it; the
   page is loaded again either way, so it says what the step is now. */
function taskGoalStep(frame, m) {
  var at = CANVAS.at;
  var body = { now: { act: 'now' },
               done: { act: 'status', status: 'done' },
               undone: { act: 'status', status: 'not-started' },
               note: { act: 'note' },
               tick: { act: 'tick' } }[m.act];
  if (frame !== tasksFrame() || !ownPage(frame) || !body || at.indexOf(TASK_PREFIX) !== 0) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that step from here.' });
    return;
  }
  // A step's own page, or its How to do it page at `?doc=your-part`.
  var folder = at.split('?')[0].slice(TASK_PREFIX.length).replace(/\/+$/, '');
  try { folder = decodeURIComponent(folder); } catch (err) {}
  body.folder = folder;
  // What he wrote and picked on the How to do it page (`goals.NOTE`).
  if (typeof m.note === 'string') body.note = m.note.slice(0, 4000);
  if (typeof m.choice === 'string') body.choice = m.choice.slice(0, 400);
  // One of his steps ticked there (`goals.YOUR_STEPS`): which, as drawn.
  if (m.act === 'tick') {
    body.index = Number(m.index) || 0;
    body.text = String(m.text || '').slice(0, 600);
    body.done = !!m.done;
  }
  clockPost('/api/goals/step', body).then(function (answer) {
    var out = answer.out || {};
    if (out.goals) goalsTake(out);
    if (!answer.ok) {
      projectSay(frame, m.id, { ok: false, error: out.error || 'That did not work.' });
      return;
    }
    projectSay(frame, m.id, { ok: true });
    if (answer.queued) {
      // Kept for when the device is back online: the page keeps what it drew, since loading it
      // again would bring back this device's copy from before the press.
      notify('Kept on this device: it goes to Rouh when you are back online.', { tone: 'success' });
      return;
    }
    var goal = (out.goals || []).filter(function (g) { return g.id === out.goal; })[0];
    if (m.act === 'now' && goal && goal.chat) {
      openChat(goal.chat);
      chatIsWanted();
      if (narrow()) setPane('chat');
    }
    // A tick is already drawn on the page, which is left where it was
    // scrolled rather than loaded again under the person's finger.
    if (m.act !== 'tick' && tasksViewing() && CANVAS.at === at) frameLoad(frame, at);
  }).catch(function () {
    projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
  });
}

/* A goal's own page (`goalpage.js`): every press the Goals page's card
   used to take - Do it now, At a time, After a step, Cancel, Change and
   Save, Mark done, Reopen - the deadline, and since fr_b083c37a634d its
   streams moved and Rouh let go on by itself. Petar, 27 September 2026
   (fr_b7586f638301): the goal lives on its task; later that day it got a
   page of its own inside the task, at the task's goal.md.

   Which goal is this page's answer, never the frame's: the folder the
   canvas framed, and the server refuses a folder that is not a goal. The
   frame says which step and what was pressed. The goal comes back to the
   frame as it now is, and it is drawn again in place, so nothing jumps. */
function goalMapFolder(frame) {
  var at = CANVAS.at;
  if (frame !== tasksFrame() || !ownPage(frame) || at.indexOf(TASK_PREFIX) !== 0) return '';
  // The goal's own page is its task's `?doc=goal.md` (`goalpage.js`): the
  // folder is the address without it.
  var folder = at.split('?')[0].slice(TASK_PREFIX.length).replace(/\/+$/, '');
  try { folder = decodeURIComponent(folder); } catch (err) {}
  return folder;
}

// `arrange` is the streams moved and reordered by hand, and `go` Rouh
// let carry on by itself, with one stream or every one it can
// (fr_b083c37a634d).
// `check` is Check now on a step that is the goal's quest's: one beat on the quest
// (`questcheck.ask`).
var GOAL_MAP_ACTS = ['now', 'at', 'after', 'clear', 'status', 'reword', 'deadline',
                     'arrange', 'go', 'again', 'pause', 'resume', 'redirect', 'check'];

// The streams as the page arranged them, in the one shape the server takes.
function goalStreams(said) {
  if (!Array.isArray(said)) return null;
  return said.slice(0, 12).map(function (one) {
    one = one || {};
    return { id: String(one.id || '').slice(0, 20), name: String(one.name || '').slice(0, 60),
             steps: (Array.isArray(one.steps) ? one.steps : []).slice(0, 40).map(function (x) {
               return String(x || '').slice(0, 80);
             }) };
  });
}

function taskGoalMap(frame, m) {
  var folder = goalMapFolder(frame);
  if (!folder || GOAL_MAP_ACTS.indexOf(m.act) < 0) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that goal from here.' });
    return;
  }
  var body = { folder: folder, act: m.act };
  ['step', 'date', 'time', 'after', 'status', 'deadline', 'stream'].forEach(function (k) {
    if (typeof m[k] === 'string') body[k] = m[k].slice(0, 200);
  });
  if (m.wording && typeof m.wording === 'object') body.wording = m.wording;
  // Do it again: what he did not like about what Rouh made.
  if (typeof m.feedback === 'string') body.feedback = m.feedback.slice(0, 2000);
  // Redirect: what the person wants done differently from now on.
  if (typeof m.direction === 'string') body.direction = m.direction.slice(0, 1200);
  if (m.act === 'arrange') body.streams = goalStreams(m.streams);
  // Check it once even though the quest or the heartbeat is paused, said in the control.
  if (m.act === 'check') body.while_paused = m.while_paused === true;
  clockPost('/api/goals/step', body).then(function (answer) {
    var out = answer.out || {};
    if (out.goals) goalsTake(out);
    if (!answer.ok) {
      projectSay(frame, m.id, { ok: false, error: out.error || 'That did not work.' });
      return;
    }
    var goal = (out.goals || []).filter(function (g) { return g.id === out.goal; })[0];
    projectSay(frame, m.id, { ok: true, goal: goal || null, said: out.said || '' });
    if (answer.queued) notify('Kept on this device: it goes to Rouh when you are back online.', { tone: 'success' });
    if ((m.act === 'now' || m.act === 'go' || m.act === 'again') && goal && goal.chat) {
      openChat(goal.chat);
      chatIsWanted();
      if (narrow()) setPane('chat');
    }
  }).catch(function () {
    projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
  });
}

// Change first's Rewrite: the step written again the way the person asked,
// kept nowhere until they save it or have it done (`goals.revise`).
function taskGoalRevise(frame, m) {
  var folder = goalMapFolder(frame);
  if (!folder || typeof m.step !== 'string' || !m.wording || typeof m.wording !== 'object') {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not rewrite that from here.' });
    return;
  }
  clockPost('/api/goals/revise', { folder: folder, step: m.step, wording: m.wording,
                                   ask: String(m.ask || '').slice(0, 2000) })
    .then(function (answer) {
      var out = answer.out || {};
      if (!answer.ok || !out.wording) {
        projectSay(frame, m.id, { ok: false, error: out.error || 'Rouh could not rewrite it. Try again.' });
        return;
      }
      projectSay(frame, m.id, { ok: true, wording: out.wording });
    }).catch(function () {
      projectSay(frame, m.id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
    });
}

// The goals as they now are, to a goal's page on the canvas, which draws
// itself again if its goal is among them (`goalpage.js`).
function goalMapTell(goals) {
  var frame = tasksFrame();
  if (!frame || !tasksViewing() || !goals || CANVAS.at.indexOf(TASK_PREFIX) !== 0) return;
  try { frame.contentWindow.postMessage({ type: 'rouh-goal-view', goals: goals }, '*'); }
  catch (err) {}
}

// Rouh has answered the answer: the task's page, if it is still the one on
// the canvas, is loaded again, and says now which job has it. In the same
// frame, so nothing around it moves.
function taskAnswerSettled() {
  if (!ANSWERED_ON) return;
  var at = ANSWERED_ON;
  ANSWERED_ON = '';
  var frame = tasksFrame();
  if (!frame || !tasksViewing() || CANVAS.at !== at) return;
  frameLoad(frame, at);
}

// The chat asked for above is open. Whatever was typed into the project's
// box goes into it now, through the composer, so it is sent, drawn and
// answered exactly as anything typed by hand is.
function projectSaidIt() {
  if (!PENDING_SAY) return;
  var words = PENDING_SAY;
  PENDING_SAY = '';
  if (!input) return;
  input.value = words;
  growInput();
  sendTyped();
}

/* A file chosen on a project's page.

   What comes up is the bytes, not the `File`: the page is sandboxed and has
   an origin of its own, so a file the browser handed it belongs to that
   origin and an upload started from here with it is refused by the browser
   before it leaves - `net::ERR_ALPN_NEGOTIATION_FAILED`, and nothing in the
   server log to say why. An ArrayBuffer has no origin and crosses, and it is
   transferred rather than cloned, so a big file is moved and not copied.
   The name is made safe again on the server (`attachments.safe_name`), and
   what the file really is, is decided there from its bytes. */
function projectUpload(frame, m) {
  var id = m.id;
  var bytes = m.bytes;
  if (frame !== tasksFrame() || typeof m.project !== 'string' || !m.project
      || !(bytes instanceof ArrayBuffer) || typeof m.name !== 'string' || !m.name) {
    projectSay(frame, id, { ok: false, error: 'Rouh will not attach that from here.' });
    return;
  }
  var form = new FormData();
  form.append('id', m.project);
  form.append('file', new Blob([bytes], { type: m.media_type || '' }), m.name);
  fetch(PROJECT_FILE, { credentials: 'same-origin', method: 'POST', body: form })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        projectSay(frame, id, {
          ok: !!j.ok && r.ok, project: j.project || null,
          error: j.error || (r.ok ? '' : (r.status === 401 || r.status === 403
            ? 'Your sign-in has run out. Reload Rouh and try again.'
            : 'Rouh could not attach that: the server said ' + r.status + '.'))
        });
      });
    })
    .catch(function () {
      projectSay(frame, id, { ok: false, error: 'Rouh could not be reached. Is it still running?' });
    });
}

/* A task's icon (`rouh/taskicons.py`): an emoji, written through the filing
   route, or a picture's bytes, made small on the page and uploaded here signed
   in, as a task's files are. Only the canvas's own frame may ask, while it
   holds the task browser or a task's page. The answer is the icon as the
   pages draw it, which the picker puts in place of the old one. */
/* Every emoji the icon picker offers, and the words each is found by
   (`rouh/static/emoji.json`, tools/emoji/build.py), fetched once for every
   frame that asks: a sandboxed page has no fetch of its own. */
/** @type {Promise<any> | null} */
var emojiAsked = null;

function emojiList(/** @type {HTMLIFrameElement} */ frame, /** @type {any} */ m) {
  if (!emojiAsked) {
    emojiAsked = fetch('../emoji.json').then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    });
  }
  emojiAsked.then(function (data) {
    projectSay(frame, m.id, { ok: true, emoji: data });
  }, function () {
    emojiAsked = null;
    projectSay(frame, m.id, { ok: false, error: 'The emoji could not be loaded. Close this and try again.' });
  });
}

function taskIconAct(frame, m) {
  var id = m.id;
  if (frame !== tasksFrame() || !(ownPage(frame) || CANVAS.at === BROWSE_ROOT)
      || typeof m.task !== 'string' || !m.task) {
    projectSay(frame, id, { ok: false, error: 'Rouh will not change that icon from here.' });
    return;
  }
  var told = function (/** @type {any} */ j, /** @type {boolean} */ ok, /** @type {number} */ status) {
    projectSay(frame, id, {
      ok: !!j.ok && ok, shown: j.shown || null,
      error: j.error || (ok ? '' : (status === 401 || status === 403
        ? 'Your sign-in has run out. Reload Rouh and try again.'
        : status === 413 ? 'That picture is too big for an icon.'
        : 'Rouh could not keep that icon: the server said ' + status + '.'))
    });
  };
  if (m.bytes instanceof ArrayBuffer) {
    var form = new FormData();
    form.append('icon', m.task);
    form.append('file', new Blob([m.bytes], { type: 'image/png' }), 'icon.png');
    fetch(PROJECT_FILE, { credentials: 'same-origin', method: 'POST', body: form })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) { told(j, r.ok, r.status); });
      })
      .catch(function () {
        projectSay(frame, id, { ok: false, error: 'Rouh could not be reached. Is it still running?' });
      });
    return;
  }
  clockPost(FILING, { action: 'icon', task: m.task, icon: String(m.icon || '').slice(0, 32) })
    .then(function (answer) { told(answer.out || {}, answer.ok, answer.ok ? 200 : 500); })
    .catch(function () {
      projectSay(frame, id, { ok: false, error: 'Rouh could not be reached. Try again in a moment.' });
    });
}

/* Upload, on a task's or a subtask's own page (`taskpage.js`): one file's
   bytes, which this page uploads signed in, as it does a project's. Which
   task is this page's answer, the folder framed on the canvas
   (`taskPageFolder`), never the frame's; and only Rouh's own page of it may
   ask (`ownPage`). The answer carries the task's files as they now are. */
function taskUpload(frame, m) {
  var id = m.id;
  var bytes = m.bytes;
  var folder = taskPageFolder();
  if (frame !== tasksFrame() || !ownPage(frame) || !folder
      || !(bytes instanceof ArrayBuffer) || typeof m.name !== 'string' || !m.name) {
    projectSay(frame, id, { ok: false, error: 'Rouh will not upload that from here.' });
    return;
  }
  var form = new FormData();
  form.append('folder', folder);
  form.append('file', new Blob([bytes], { type: m.media_type || '' }), m.name);
  fetch(PROJECT_FILE, { credentials: 'same-origin', method: 'POST', body: form })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        projectSay(frame, id, {
          ok: !!j.ok && r.ok, files: j.files || null,
          error: j.error || (r.ok ? '' : (r.status === 401 || r.status === 403
            ? 'Your sign-in has run out. Reload Rouh and try again.'
            : r.status === 413 ? m.name + ' is too big to upload.'
            : 'Rouh could not upload that: the server said ' + r.status + '.'))
        });
      });
    })
    .catch(function () {
      projectSay(frame, id, { ok: false, error: 'Rouh could not be reached. Is it still running?' });
    });
}

/* A press in the three dots of a working folder inside a task, or of a line of its listing
   (`folderpage.js`, `rouh/folder_acts.py`): New folder, Upload files, Rename or Delete. The task
   is the one framed here, read off the canvas and never off the page; the page names only the
   folder or file inside it, which the server holds to that task's folder. When the folder the
   page is showing was itself renamed or deleted (`here`), the frame is sent where it is now: the
   new name, or the folder above it, or the task's own page. */
var FOLDER_ACTS = ['new_folder', 'rename', 'delete', 'upload', 'again'];

/** @param {HTMLIFrameElement} frame @param {any} m */
function taskFolderAct(frame, m) {
  var folder = taskPageFolder();
  var doc = String(m.doc || '').replace(/^\/+|\/+$/g, '');
  if (frame !== tasksFrame() || !ownPage(frame) || !folder || !doc
      || doc.split('/').some(function (p) { return !p || p === '.' || p === '..'; })
      || FOLDER_ACTS.indexOf(m.act) === -1) {
    projectSay(frame, m.id, { ok: false, error: 'Rouh will not change that folder from here.' });
    return;
  }
  if (m.act === 'again') {
    // Done: the folder drawn again, with what is in it now.
    projectSay(frame, m.id, { ok: true });
    frameGo(frame, String(CANVAS.at || ''));
    return;
  }
  var asked;
  if (m.act === 'upload') {
    if (!(m.bytes instanceof ArrayBuffer) || typeof m.name !== 'string' || !m.name) {
      projectSay(frame, m.id, { ok: false, error: 'Rouh will not upload that from here.' });
      return;
    }
    var form = new FormData();
    form.append('folder', folder);
    form.append('doc', doc);
    form.append('file', new Blob([m.bytes], { type: m.media_type || '' }), m.name);
    asked = fetch(PROJECT_FILE, { credentials: 'same-origin', method: 'POST', body: form });
  } else {
    asked = fetch('/api/workspace/folder', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: folder, doc: doc, act: m.act,
                             name: String(m.name || '').slice(0, 200) })
    });
  }
  asked.then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (got) {
      if (!r.ok || !got.ok) {
        return { error: got.error || (r.status === 401 || r.status === 403
          ? 'Your sign-in has run out. Reload Rouh and try again.'
          : r.status === 413 ? String(m.name || 'That file') + ' is too big to upload.'
          : 'That could not be done: the server said ' + r.status + '.') };
      }
      return got;
    });
  }).catch(function () {
    return { error: 'Rouh could not be reached. Try again in a moment.' };
  }).then(function (got) {
    if (got.error) {
      projectSay(frame, m.id, { ok: false, error: got.error });
      return;
    }
    projectSay(frame, m.id, { ok: true, doc: String(got.doc || ''), name: String(got.name || '') });
    if (m.here && (m.act === 'rename' || m.act === 'delete')) {
      var base = String(CANVAS.at || '').split('?')[0].split('#')[0];
      if (base.slice(-1) !== '/') base += '/';
      frameGo(frame, got.doc ? base + '?doc=' + encodeURIComponent(String(got.doc)) : base);
    }
  });
}

// A page in a frame, telling this page what the reader did in it. Every one
// of these is acted on only for a frame that is really on this page.
window.addEventListener('message', function (e) {
  var m = e.data;
  if (!m || (m.type !== 'rouh-page-follow' && m.type !== 'rouh-page-key'
             && m.type !== 'rouh-page-address' && m.type !== 'rouh-page-ask'
             && m.type !== 'rouh-page-file' && m.type !== 'rouh-html-size'
             && m.type !== 'rouh-page-chat' && m.type !== 'rouh-page-upload'
             && m.type !== 'rouh-page-dismiss' && m.type !== 'rouh-page-goal'
             && m.type !== 'rouh-page-goalmap' && m.type !== 'rouh-page-goalrevise'
             && m.type !== 'rouh-page-view' && m.type !== 'rouh-askai'
             && m.type !== 'rouh-page-task' && m.type !== 'rouh-page-feedback'
             && m.type !== 'rouh-page-decision' && m.type !== 'rouh-page-height'
             && m.type !== 'rouh-page-state' && m.type !== 'rouh-page-folder')) return;
  var frame = frameOf(e.source);
  if (!frame) return;
  if (m.type === 'rouh-page-height') {
    if (frame === tasksFrame()) tasksFlow(frame, m.height);
    return;
  }
  if (m.type === 'rouh-html-size') {
    // A frame has no height of its own, so the page inside it measured
    // itself. Only a frame this page drew for a snippet is sized this way:
    // a workspace page has a height in the stylesheet and says nothing.
    if (frame.classList.contains('html-frame') && m.height > 0)
      htmlFrameHeight(frame, clamp(Math.ceil(m.height), 24, HTML_FRAME_MAX));
    return;
  }
  if (m.type === 'rouh-page-ask') {
    askRelay(frame, m);
    return;
  }
  if (m.type === 'rouh-page-state') {
    stateRelay(frame, m);
    return;
  }
  // The task browser saying which list it is showing, or asking which one
  // it was showing before it was thrown away. Only the canvas's own frame,
  // and only while it holds the browser.
  if (m.type === 'rouh-page-view') {
    if (frame !== tasksFrame() || CANVAS.at !== BROWSE_ROOT) return;
    if (m.ask) {
      try {
        frame.contentWindow.postMessage(
          { type: 'rouh-frame-view', view: TASKS_VIEW.view, q: TASKS_VIEW.q }, '*');
      } catch (err) {}
      browserOfflineSay();
      return;
    }
    if (typeof m.view === 'string' && m.view.length <= 2000 && m.view !== TASKS_VIEW.view) {
      TASKS_VIEW.view = m.view;
      // And into the address, in place of the one there: a reload, a new tab
      // or Back from a task opens the same list (`addrWithView`).
      ADDR.replace = true;
      addrTouch();
    }
    if (typeof m.q === 'string' && m.q.length <= 500) TASKS_VIEW.q = m.q;
    return;
  }
  // A passage selected on the canvas's page, a mark on it pressed, or the
  // page handing back its own words. The one conversation is drawn here,
  // not in the page (`askHost` below).
  if (m.type === 'rouh-askai') {
    askFromPage(frame, m);
    return;
  }
  if (m.type === 'rouh-page-file') {
    fileRelay(frame, m);
    return;
  }
  if (m.type === 'rouh-page-chat') {
    // A task's page starts a chat about the task; a project's starts one
    // in the project.
    if (typeof m.task === 'string') taskChat(frame, m);
    else projectChat(frame, m);
    return;
  }
  if (m.type === 'rouh-page-upload') {
    // A task's page uploads to the task it is; a project's, to the project.
    if (m.task === true) taskUpload(frame, m);
    else projectUpload(frame, m);
    return;
  }
  if (m.type === 'rouh-page-dismiss') {
    taskDismiss(frame, m);
    return;
  }
  if (m.type === 'rouh-page-goal') {
    taskGoalStep(frame, m);
    return;
  }
  if (m.type === 'rouh-page-task') {
    taskPageAct(frame, m);
    return;
  }
  if (m.type === 'rouh-page-folder') {
    taskFolderAct(frame, m);
    return;
  }
  if (m.type === 'rouh-page-decision') {
    taskDecision(frame, m);
    return;
  }
  if (m.type === 'rouh-page-feedback') {
    gtFromPage(frame, m);
    return;
  }
  if (m.type === 'rouh-page-goalmap') {
    taskGoalMap(frame, m);
    return;
  }
  if (m.type === 'rouh-page-goalrevise') {
    taskGoalRevise(frame, m);
    return;
  }
  if (m.type === 'rouh-page-follow') {
    if (typeof m.href !== 'string') return;
    if (m.out) frameOut(m.href);
    else frameGo(frame, m.href);
    return;
  }
  if (m.type === 'rouh-page-address') {
    // A frame that has taken itself somewhere. The workspace's own index
    // does it every time Enter is pressed on a task, and no script can catch
    // a page doing that. The frame is at a real address, which means it
    // asked for the page without Rouh's sign-in, so it is loaded again
    // from here, where the sign-in is. A page this page handed over says it
    // is at "about:srcdoc" and is not a frame that has gone anywhere.
    if (typeof m.href === 'string') frameGo(frame, m.href);
    return;
  }
  // Cmd+K, or Ctrl+K, handed up out of the page: search, which is supposed
  // to work from anywhere and would otherwise be the one shortcut that stops
  // working the moment a task page takes the whole window (pages.FRAME_KEYS).
  // It belongs to Rouh wherever the frame is, so it is answered before the
  // check below for which frame this was.
  if ((m.key === 'k' || m.key === 'K') && (m.meta || m.ctrl)) {
    findShow(true);
    return;
  }
  // Escape and Back belong to the tasks in the canvas, and to nothing else
  // that frames a page: a card on the canvas has neither. Both climb one
  // level of the breadcrumb, which is what one press means here.
  if (frame !== tasksFrame()) return;
  tasksUp();
});

var cardSeq = 0;

/* ---------- one stream: messages and cards, in the order they happened ----

   A message and a card are the same thing. A message is a list of blocks
   with one text block in it; a card is a list of blocks with several. There
   is one renderer for both (`renderBlock`), and one place they are read:
   the transcript, oldest at the top, newest at the bottom, exactly as a
   conversation reads.

   Cards used to be drawn on the canvas and nowhere else, which meant the
   answer to a question was in one column and the words about it were in
   another, and on a phone they were on two different screens. So every card
   has its place in the conversation, where it was drawn. On a phone it is
   read there. At a desk it is read on the canvas beside it, and its place
   holds a line naming it (`openOnCanvas`, and why, under "every card on the
   canvas, at a desk").

   There is exactly one of each card. Opening one on the canvas moves that
   same element there and leaves the line in its place in the stream;
   bringing it back puts it back. Nothing is ever built twice, so nothing can
   drift. */

// What the page holds of the canvas's history, which lives on the server.
//
// The canvas used to exist only in this tab: a reload, or Rouh restarting,
// and everything it had ever drawn was gone. Now every card is kept on the
// server (memory.py) and read back through /api/canvas/cards. The page holds
// the newest CARD_PAGE of them and asks for the next lot when the reader
// scrolls up past the oldest it has, so opening the page costs the same
// whether there are ten cards behind it or ten thousand.
var CARD_PAGE = 10;
// `gen` is which chat's stream is being filled. A page of history is a
// request that takes a moment to come back, and the chat can be switched
// while it is out: the answer then belongs to a conversation that is no
// longer on the screen, and placing it would put the old chat's cards among
// the new chat's words. Every reset bumps this, and an answer whose number no
// longer matches is dropped rather than drawn.
// `keepCanvas`: the chat being read back is along a strip of forks from the
// one before it, and the canvas stays as it is (`resetStreamCards`).
// `bare`: the chat has just been opened and nothing has been put on the
// canvas since. Its cards are read back as their lines in the conversation,
// and the bare canvas does not pick the newest of them up by itself
// (`cardsSettle`) until a card is drawn now or one is opened on it by hand.
// Petar, 26 October 2026 (fr_9feadc24353b): "unless that canvas was
// generated now, or I clicked show in canvas, the canvas should be blank and
// also closed."
var CARDS = { oldest: null, more: true, loading: false, restoring: 0, gen: 0,
              keepCanvas: false, bare: false };

function streamEl() { return $('transcript'); }

// The note at the very top of the stream saying there is more behind it, and
// the mark everything older is placed after. A card drawn before the oldest
// message the page holds has no message to sit under, so it sits here, and
// each page of older cards goes straight after the note - which, since the
// server answers newest first, leaves them in order.
function olderNote() {
  return $('streamOlder');
}

/* Where one item of history belongs in the stream.

   Every message drawn from the history carries its own row number
   (`data-msg`), and every card says which message it came after
   (`after_message_id` in memory.py). That is the whole of the ordering: a
   card goes immediately under the message whose turn drew it.

   A card whose message is not on screen falls back to the clock - which is
   every card drawn before that column existed, and every card whose message
   had no words to draw. It goes after the last message older than it.

   A card drawn by a call inside an answer goes inside that answer, under the
   line of the call (`after_call`), with the words written after it below it,
   which is where it was while the answer was being written
   (`cardInAnswer`, fr_6b1852e8f32e). `inAnswer` is one drawn in an answer
   with no call to go by, placed after what its message drew. */
function placeByAnchor(node, afterMessageId, at, afterCall, inAnswer) {
  var host = streamEl();
  if (!host) return;
  if ((afterCall || inAnswer) &&
      cardInAnswer(node, afterCall, afterMessageId, at)) return;
  var anchor = null;
  if (afterMessageId != null) {
    anchor = host.querySelector('.turn[data-msg="' + Number(afterMessageId) + '"], ' +
                                '.turn[data-msgs~="' + Number(afterMessageId) + '"]');
  }
  if (!anchor && at != null) {
    var turns = host.querySelectorAll('.turn[data-at]');
    for (var i = 0; i < turns.length; i++) {
      if (Number(turns[i].getAttribute('data-at')) <= Number(at)) anchor = turns[i];
    }
  }
  if (!anchor) {
    // Older than anything on screen: under the "what came before" note, so
    // the next page read back goes above it. Marked, so that it goes under its
    // message once older messages are read back (`cardsUnpark`).
    node.__parked = { after: afterMessageId, at: at };
    var note = olderNote();
    if (note && note.parentNode === host) host.insertBefore(node, note.nextSibling);
    else host.insertBefore(node, host.firstChild);
    return;
  }
  // After the message, and after any card already sitting under it that was
  // drawn before this one, but above one drawn after it. The history is read
  // newest first, so without the clock two cards under one message - two
  // drawn in one turn, or a card drawn before a note of Rouh's own that the
  // page never shows - came back the wrong way up.
  var at_ = anchor.nextSibling;
  while (at_ && at_.nodeType === 1 && at_.classList &&
         at_.classList.contains('card-slot') &&
         !(at != null && at_.__at != null && Number(at_.__at) > Number(at))) {
    at_ = at_.nextSibling;
  }
  node.__at = at;
  node.__parked = null;
  host.insertBefore(node, at_);
}

// Every card waiting at the top for a message older than any on the screen is
// placed again, now that older messages have been drawn (`olderLoad`).
function cardsUnpark() {
  var host = streamEl();
  if (!host) return;
  var parked = [];
  for (var n = host.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 1 && /** @type {Element} */ (n).classList.contains('turn')) break;
    if (/** @type {any} */ (n).__parked) parked.push(n);
  }
  parked.forEach(function (node) {
    var was = node.__parked;
    node.remove();
    placeByAnchor(node, was.after, was.at);
  });
}

// The slot a card lives in. It stays in the stream whether the card is in it
// or out on the canvas, which is what keeps the card's place in the
// conversation while it is being read at full width. Held on the card
// itself, because while the card is out on the canvas the slot is not its
// parent and a card drawn by hand may have no number to look one up by.
function slotOf(card) {
  return (card && card.__slot) || null;
}

/* What a card says, in words, for the clipboard.

   A card is markup as often as it is a sentence, and a copy of it has to be
   something a person can paste into a message: the rows of a table, the
   words of a page, the number a stat is. Read off the blocks it was built
   from rather than off the screen, because an `html` block is drawn inside a
   sandboxed frame and nothing out here can read a word of it. */
var HTML_LINES = 'p,div,li,tr,h1,h2,h3,h4,h5,h6,section,article,header,footer,'
  + 'blockquote,pre,figcaption,caption,dt,dd';

function htmlWords(markup) {
  if (!markup) return '';
  var doc = null, i;
  try { doc = new DOMParser().parseFromString(String(markup), 'text/html'); }
  catch (err) { doc = null; }
  if (!doc || !doc.body) return '';
  // A line where the markup has one. Read off raw, a heading runs straight
  // into the paragraph under it and a table comes out as one long word.
  var breaks = doc.body.querySelectorAll('br');
  for (i = 0; i < breaks.length; i++) {
    breaks[i].parentNode.insertBefore(doc.createTextNode('\n'), breaks[i]);
  }
  var cells = doc.body.querySelectorAll('td,th');
  for (i = 0; i < cells.length; i++) cells[i].appendChild(doc.createTextNode('\t'));
  var lines = doc.body.querySelectorAll(HTML_LINES);
  for (i = 0; i < lines.length; i++) lines[i].appendChild(doc.createTextNode('\n'));
  return doc.body.textContent
    .replace(/[ \t]*\n[ \t]*/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/ {2,}/g, ' ')
    .trim();
}

function blockWords(b) {
  if (!b || typeof b !== 'object') return '';
  var i, lines;
  switch (b.block) {
    case 'text':
    case 'code':
      return String(b.text == null ? '' : b.text);
    case 'stat':
      return [b.label, b.value == null ? '' : String(b.value), b.hint]
        .filter(Boolean).join(': ');
    case 'list':
      lines = (Array.isArray(b.items) ? b.items : [])
        .map(function (one) { return '- ' + one; });
      if (b.label) lines.unshift(String(b.label));
      return lines.join('\n');
    case 'table':
      lines = [];
      if (b.label) lines.push(String(b.label));
      if (Array.isArray(b.columns) && b.columns.length) lines.push(b.columns.join('\t'));
      var rows = Array.isArray(b.rows) ? b.rows : [];
      for (i = 0; i < rows.length; i++) {
        lines.push((Array.isArray(rows[i]) ? rows[i] : [rows[i]]).join('\t'));
      }
      return lines.join('\n');
    case 'chart':
      var labels = Array.isArray(b.labels) ? b.labels : [];
      var values = Array.isArray(b.values) ? b.values : [];
      lines = [];
      for (i = 0; i < labels.length; i++) {
        lines.push(labels[i] + '\t' + (values[i] == null ? '' : values[i]));
      }
      return lines.join('\n');
    case 'image':
      return String(b.caption || b.alt || b.src || b.url || '');
    case 'link':
      return [b.text || b.label, b.href].filter(Boolean).join('\n');
    case 'sources':
      lines = (Array.isArray(b.sources) ? b.sources : []).map(function (page, n) {
        page = page || {};
        return (n + 1) + '. ' + [page.title, page.url].filter(Boolean).join(' - ');
      });
      return lines.length ? 'Sources\n' + lines.join('\n') : '';
    case 'html':
      return htmlWords(typeof b.html === 'string' ? b.html : (b.text || ''));
    case 'contact':
      return contactWords(b);
    case 'email':
      return emailWords(b);
    case 'ask':
    case 'inbox':
      // Nothing to copy that is not already the card's title: the inbox is
      // read live and the card itself holds none of it.
      return '';
    case 'compose':
      // What a compose card copies is the message as a person would paste
      // it: the lines at the top, then the words, without the markup.
      lines = (Array.isArray(b.fields) ? b.fields : []).filter(function (f) {
        return String(f.value || '').trim();
      }).map(function (f) { return (f.label || f.name) + ': ' + f.value; });
      lines.push('');
      lines.push(htmlWords(b.body || ''));
      return lines.join('\n').trim();
    default:
      return String(b.text || b.title || '');
  }
}

/* The line under a card's title, or nothing when it only says the title
   again. A job's report used to be drawn with one ("the answer to Debug
   Balanced model router" under "Answer: Debug Balanced model router"), and
   Petar asked on 26 October 2026 for that line to go (fr_4241e4d596a4). No
   report is drawn with one now; this keeps the ones already kept quiet too.
   @param {{title?: string, description?: string}} spec */
function cardDesc(spec) {
  var desc = String(spec.description || '').trim();
  if (!desc) return '';
  var title = String(spec.title || '').trim();
  var colon = title.indexOf(': ');
  var named = (colon >= 0 ? title.slice(colon + 2) : title).trim().toLowerCase();
  return named && desc.toLowerCase().indexOf(named) >= 0 ? '' : desc;
}

function cardWords(spec) {
  var parts = [];
  if (spec.title) parts.push(String(spec.title));
  var desc = cardDesc(spec);
  if (desc) parts.push(desc);
  var blocks = sourcesLast(Array.isArray(spec.blocks) ? spec.blocks : []);
  for (var i = 0; i < blocks.length; i++) {
    var said = blockWords(blocks[i]).trim();
    if (said) parts.push(said);
  }
  return parts.join('\n\n');
}

/* The chip a card wears about the workspace: where it went, or the way to
   put it there.

   A card is a card. Nothing writes one into the workspace by itself any more
   - that is what the person asked to have taken out on 22 September 2026 -
   so a card drawn in a thread that is a task offers the press instead, and a
   card that has been filed says which step it is and opens it.

   One builder for both, because `cardFiled` swaps one for the other where
   the card already stands. */
function filingChip(spec) {
  if (spec.filed) {
    var filed = el('button', 'card-filed', 'Filed as ' + spec.filed);
    filed.type = 'button';
    filed.title = 'Open this step on the canvas';
    filed.addEventListener('click', function () {
      if (spec.filed_rel) canvasStep(spec.filed_rel);
    });
    return filed;
  }
  if (!spec.card_id || !chatIsTask()) return null;
  var file = el('button', 'card-filed card-file', 'File as a step');
  file.type = 'button';
  file.title = 'Write this card into the task this thread is, as its next'
    + ' numbered step. Nothing is filed until you ask for it.';
  file.addEventListener('click', function () {
    file.disabled = true;
    send({ type: 'file_card', id: spec.card_id });
  });
  return file;
}

/* A card that has just been put on the record, changed where it stands.

   Not drawn again: a card is drawn again when it is asked for again or
   revised, and that moves it to the end of the conversation, which is right
   for both of those and wrong for this one. Filing does not change a word of
   what the card says - it says where the same words now also live - so the
   card stays exactly where the person was looking at it and only its chip
   changes. A card that is not on this screen needs nothing: the stream is
   read back from the rows, which carry the filing. */
function cardFiled(spec) {
  var host = streamEl();
  var pick = '[data-card="' + spec.card_id + '"]';
  var card = host ? host.querySelector('.card-slot' + pick + ' .card') : null;
  if (!card && $('cards')) card = $('cards').querySelector('.card' + pick);
  var meta = card ? card.querySelector('.card-meta') : null;
  if (!meta) return;
  var chip = filingChip(spec);
  var was = meta.querySelector('.card-filed');
  if (!chip) { if (was) was.remove(); return; }
  if (was) meta.replaceChild(chip, was);
  else meta.insertBefore(chip, meta.querySelector('.card-desc'));
}

// `stay` is a card changed in place by the person, on the card itself (a
// contact's relationship or research): its new version takes the old one's
// place in the conversation rather than moving to the end of it.
/** @param {import('./protocol').CardSpec} spec */
/* Which version of a card this is, with the way to the others either side of it:
   "‹ v2 of 3 ›". Petar, 4 November 2026: "now I see v2 of 2 ... and it doesn't
   have controls for me to switch between canvas versions." A press draws the card
   again in place as that version read (`card_version`), on this screen only, and
   writes nothing: the newer versions stay, and the arrows go back to them. */
function cardVersions(spec) {
  var at = Number(spec.version || spec.versions), of = Number(spec.versions);
  var box = el('span', 'card-ver');
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Versions of this card');
  box.title = 'This card has been revised. Every version it has had is kept.';
  function step(cls, label, to) {
    var b = el('button', 'card-ver-step ' + cls, cls === 'prev' ? '\u2039' : '\u203a');
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.title = label;
    b.disabled = to < 1 || to > of || !spec.card_id;
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      if (b.disabled) return;
      if (!send({ type: 'card_version', card: Number(spec.card_id), version: to })) {
        notify('Not connected, so the card could not be turned to that version.', { tone: 'error' });
      }
    });
    return b;
  }
  box.appendChild(step('prev', 'Show version ' + (at - 1) + ' of this card', at - 1));
  var said = el('span', 'card-ver-at', 'v' + at + ' of ' + of);
  said.setAttribute('aria-live', 'polite');
  if (at === of) said.classList.add('is-newest');
  box.appendChild(said);
  box.appendChild(step('next', 'Show version ' + (at + 1) + ' of this card', at + 1));
  return box;
}

function renderCard(spec, older, stay) {
  var host = streamEl();
  if (!host) return;
  var already = spec.card_id
    ? host.querySelector('.card-slot[data-card="' + spec.card_id + '"]') : null;
  // Reading the history back must never move a card somebody is looking at:
  // a card asked for again sits at the end of the stream, and the page later
  // reads back the stretch of history it used to be in. So an older card
  // that is already on screen is left exactly where it is.
  if (already && older) return;
  dropEmpty();
  var id = 'card-' + (++cardSeq);
  var card = el('div', 'card');
  card.id = id;
  // What the line it leaves in the conversation calls it while it is out on
  // the canvas (`cardLine`): its number and its title, as its head says.
  card.__no = spec.card_id || null;
  card.__title = spec.title || 'Rouh';

  // The server's number for this card, which is what the person says out
  // loud to get it back. It survives a reload; the local counter does not.
  if (spec.card_id) card.setAttribute('data-card', String(spec.card_id));
  if (spec.again) card.classList.add('again');

  var head = el('div', 'card-head');
  var titles = el('div');
  titles.appendChild(el('div', 'card-title', spec.title || 'Rouh'));
  // What it is and when it was, so a card that has scrolled a long way up
  // still says what it is without anyone having to ask for it again.
  if (spec.card_id || cardDesc(spec) || spec.at || spec.filed) {
    var meta = el('div', 'card-meta');
    if (spec.card_id) meta.appendChild(el('span', 'card-no', '#' + spec.card_id));
    // A card that has been revised says which of its versions this is.
    // Revising never overwrites: every one it has had is kept, and the older
    // ones come back by number, so the card has to say which one is on it.
    if (spec.versions > 1) meta.appendChild(cardVersions(spec));
    if (spec.at) meta.appendChild(el('span', 'card-when', clockOf(spec.at)));
    var chip = filingChip(spec);
    if (chip) meta.appendChild(chip);
    var desc = cardDesc(spec);
    if (desc) meta.appendChild(el('span', 'card-desc', desc));
    titles.appendChild(meta);
  }
  head.appendChild(titles);
  var tools = el('div', 'card-tools');
  // One button, both ways, on every card. It used to be on the head of an
  // `html` block and nowhere else, because that was the only card that went
  // out on the canvas; every card does now, so every card carries the way
  // back and forth. A card already on the canvas used to carry a button
  // offering to open it on the canvas, which moved it home and straight back
  // out: a press that flickered and did nothing. It says which way it goes,
  // and `sayWhichWay` keeps the words honest.
  //
  // On a phone as well, since 26 September 2026, where it is the glyph for
  // full screen rather than the words: the canvas slides in with this card
  // on it, and the cross in the corner puts it back in the conversation
  // where it was being read. Petar: "the cards displayed in chat, can those
  // have a button that puts them full screen on the canvas? If I press it,
  // canvas slides sideways to fill screen I can close it."
  //
  // There was a cross beside it until 26 October 2026, which took the card
  // off the conversation until the next reload. Petar did not know what it
  // did, and the canvas's own Hide is what he wants instead
  // (fr_4241e4d596a4).
  var way = el('button', 'ctl small to-canvas');
  way.type = 'button';
  way.appendChild(el('span', 'to-canvas-say', 'Open on the canvas'));
  way.appendChild(fullScreenGlyph());
  way.appendChild(bringBackGlyph());
  sayWhichWay(card, way);
  way.addEventListener('click', function () {
    if (card.classList.contains('on-canvas')) bringCardHome(card, true);
    else openOnCanvas(card, true);
  });
  tools.appendChild(way);
  head.appendChild(tools);
  card.appendChild(head);

  var body = el('div', 'card-body');
  var blocks = sourcesLast(Array.isArray(spec.blocks) ? spec.blocks : []);
  for (var i = 0; i < blocks.length; i++) {
    var node = null;
    try { node = renderBlock(blocks[i], id, older); } catch (err) { node = null; }
    if (node) body.appendChild(node);
  }
  if (!body.childNodes.length) body.appendChild(el('p', 'empty', 'Nothing renderable in this one.'));
  footnotes(body);
  card.appendChild(body);

  // The same quiet row every message in the stream has. A card cannot be
  // asked again - it was drawn by a tool inside an answer, and that answer's
  // own row is what asks for it again - so the one thing it offers is copy,
  // and what it copies is what the card says rather than the markup it says
  // it in.
  var acts = el('div', 'turn-acts card-acts');
  var copyCard = actBtn('copy', 'Copy what this card says');
  copyCard.addEventListener('click', function () {
    copyFrom(copyCard, cardWords(spec), 'Copied the card');
  });
  acts.appendChild(copyCard);
  card.appendChild(acts);

  // The place in the conversation this card has, whether or not the card is
  // sitting in it this second.
  var slot = el('div', 'card-slot');
  if (spec.card_id) slot.setAttribute('data-card', String(spec.card_id));
  slot.appendChild(card);
  card.__slot = slot;

  // Asking for a card again moves it, rather than leaving two of the same
  // thing on screen at different heights. One that was out on the canvas is
  // brought home first, so nothing of it is left behind there.
  var placed = false, wasOut = false;
  if (already) {
    var oldCard = already.querySelector('.card');
    if (!oldCard) {
      var out = $('cards');
      oldCard = out && spec.card_id
        ? out.querySelector('.card[data-card="' + spec.card_id + '"]') : null;
      wasOut = !!oldCard;
      if (oldCard) bringCardHome(oldCard);
    }
    if (stay && !older && already.parentNode) {
      slot.__place = already.__place;
      slot.__at = already.__at;
      already.parentNode.insertBefore(slot, already);
      placed = true;
    }
    already.remove();
  }
  if (older) {
    placeByAnchor(slot, spec.after_message_id, spec.placed_at || spec.at, spec.after_call,
                  spec.in_answer);
    // Read back from the history, so nobody asked for it this minute. At a
    // desk it is the line that opens it on the canvas, and the newest of
    // the chat's is put out there once the page of them is in
    // (`loadOlderCards`, through `cardsSettle`). A phone that reads cards
    // on the canvas does the same (`cardsGoOut`).
    if (cardsGoOut()) foldCard(card);
    return;
  }
  // Drawn now, so it goes at the end of the conversation: under everything
  // said so far, and above the sign that Rouh is still working.
  if (placed) {
    // Where it was, and out on the canvas again if that is where it was
    // being read when it was changed - on a phone as well, where it was
    // being read full screen.
    if (wasOut) openOnCanvas(card, false, 'again');
    return;
  }
  // In the answer being written, when one is: under the call that drew it,
  // and the words written after it below it.
  if (cardInLiveAnswer(slot, spec.after_call)) { /* placed */ }
  else if (T.typing && T.typing.parentNode === host) host.insertBefore(slot, T.typing);
  else host.appendChild(slot);
  // At a desk every card goes out on the canvas as it is drawn, which is
  // the whole of this split: the canvas beside the conversation at a desk,
  // the conversation it was drawn in on a phone. `openOnCanvas` is the one
  // that knows where a phone reads a card (`cardsGoOut`) and that a page
  // loaded over the canvas is not to be covered, so neither is asked twice.
  // A card asked for again while a phone was reading it full screen stays
  // there, the same as one revised in place.
  openOnCanvas(card, false, wasOut && !cardsGoOut() ? 'again' : 'arriving');
  scrollDown();
}

/* ---------- every card on the canvas, at a desk ----------

   Petar, 24 September 2026: "The card is squeezed into the chat while the
   big black half of the screen stays empty. I expected that cards should go
   on canvas by default on desktop experience. They should only be squeezed
   in chat on mobile."

   Until then only a card carrying an `html` block went out, because that is
   the one block that cannot reflow. Every other card - a table, a list, a
   job's report - was read in a third of the window, beside a canvas with
   nothing on it. So where a card is read is decided by the width of the
   screen, for every card, and by nothing else:

   - **At a desk it goes out on the canvas, by itself, as it is drawn.** The
     same card is moved across, never copied, and the conversation keeps a
     line in its place saying which card it is and that it is on the canvas,
     so the words either side of it still read in order.
   - **One at a time.** The canvas holds the newest card. The one it held
     folds to its line in the conversation, and pressing that line puts it
     back on the canvas. So at a desk no card is squeezed into the chat at
     all, and scrolling back through a conversation is scrolling through
     what was shown, each of it one press from the canvas.
   - **On a phone it stays in the conversation**, because there is no second
     column to move it to. Below 900px there are no lines and every card is
     in the stream in full. Its button is the full screen glyph, which
     slides the canvas in with the card on it, and the cross in the corner
     puts it back (since 26 September 2026). A phone can be switched to the
     desk's way as well, from the bare canvas (`cardsGoOut`).

   A page loaded over the canvas - a task, a run, Settings - is never covered
   by a card. It is what the person put there, and a card sent out under it
   would be an answer nobody can see. So a card drawn while one is open is
   read in the conversation, and goes out when the canvas is bare again
   (`cardsSettle`, from `showLayer`).

   A press overrules all of it for that card. Bringing one home by hand
   marks it `__kept`, and nothing afterwards folds it or sends it out on its
   own: the person has said where they want to read it, and a later resize
   changing its mind under them would be the page arguing. Opening it on the
   canvas by hand takes that back. */

// The button on a card's head, which is one button going both ways. What it
// says has to be where the card actually is, not where it was when it was
// drawn, or it offers to do the thing it has already done. `only` is the
// one button of a card still being built, before it has a head to look in.
//
// On a phone the words are not drawn - the glyph is - and a card on the
// canvas there has no buttons on its head at all: the cross in the corner
// is the way back (see `.card.on-canvas .card-tools` in the stylesheet).
function sayWhichWay(card, only) {
  if (!card) return;
  var away = card.classList.contains('on-canvas');
  var buttons = only ? [only] : card.querySelectorAll('.card-head .to-canvas');
  var said = away ? 'Bring it back here' : 'Open on the canvas';
  for (var i = 0; i < buttons.length; i++) {
    var words = buttons[i].querySelector('.to-canvas-say');
    if (words) words.textContent = said;
    buttons[i].setAttribute('aria-label', said);
    buttons[i].title = away
      ? 'Read it in the conversation instead, in among the words about it'
      : narrow() ? 'Open this card full screen, on the canvas'
        : 'Open this card on the canvas, beside the conversation';
  }
}

// Four corners pulled out to the edges: full screen, which is what the
// button is on a phone, where the words would take the card's title's room.
function fullScreenGlyph() {
  var svg = svgEl('svg', {
    class: 'to-canvas-glyph', viewBox: '0 0 24 24', width: '16', height: '16',
    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
  svg.appendChild(svgEl('path', { d: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5' }));
  return svg;
}

// An arrow back to the edge the conversation is on: Bring it back here, as
// the glyph a desk's card on the canvas has in its head instead of the words
// (Petar's mockup of 26 October 2026, fr_341089f4b07a).
function bringBackGlyph() {
  var svg = svgEl('svg', {
    class: 'to-canvas-back', viewBox: '0 0 24 24', width: '18', height: '18',
    fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
  svg.appendChild(svgEl('path', { d: 'M4 5v14M14 7l-5 5 5 5M9 12h11' }));
  return svg;
}

/* ---------- where a phone reads a card ----------

   At a desk every card goes out on the canvas as it is drawn. On a phone it
   is read in the conversation, and its full screen glyph puts it on the
   canvas by hand. That is "chat", and it is what a phone did before this.

   "canvas" is the desk's way on a phone: every card goes out on the canvas
   as it is drawn, and the canvas slides in to show it; the conversation
   keeps the line in its place that it keeps at a desk, and the corner glyph
   is orange for as long as the canvas holds one. Petar, 26 September 2026:
   "Maybe the canvas should have a button that toggles between chat and
   canvas display for mobile to be the default. So I can try the two
   experiences." Read as where a card is displayed on a phone, since the
   way between the two panes is the corner glyph and a phone already comes
   back to the pane it was left on. The switch is on the bare canvas
   (`#cardsWhere` in index.html), and the choice is kept in this browser.

   Below 900px only. At a desk the answer is always the canvas, and the
   switch is not drawn. */
var KEY_PHONE_CARDS = 'rouh.phonecards.v1';
var PHONE_CARDS = load(KEY_PHONE_CARDS) === 'canvas' ? 'canvas' : 'chat';

// Whether a card drawn now goes out on the canvas by itself.
// At a desk, while the canvas is on the screen: put away, a card is read in
// the conversation it was drawn in, as on a phone (`canvasShown`).
function cardsGoOut() { return narrow() ? PHONE_CARDS === 'canvas' : canvasShown(); }

function paintCardsWhere() {
  var app = $('app');
  if (app) app.setAttribute('data-phone-cards', PHONE_CARDS);
  var box = $('cardsWhere');
  if (!box) return;
  var buttons = box.querySelectorAll('[data-where]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].setAttribute('aria-pressed',
      buttons[i].getAttribute('data-where') === PHONE_CARDS ? 'true' : 'false');
  }
}

// A press on one side of the switch: remembered, and shown straight away,
// so the two can be tried one after the other. "Chat" puts every card back
// in the conversation and goes there to read them; "Canvas" puts the newest
// out on the canvas this switch is on.
function cardsWhere(want) {
  var next = want === 'canvas' ? 'canvas' : 'chat';
  PHONE_CARDS = next;
  store(KEY_PHONE_CARDS, next);
  paintCardsWhere();
  // A card kept in the conversation by hand was kept under the other way of
  // doing it. Changing the way is asking to see this one.
  var every = document.querySelectorAll('.card');
  for (var i = 0; i < every.length; i++) every[i].__kept = false;
  if (next === 'chat' && narrow() && !layerOpen()) setPane('chat');
  cardsSettle();
}

(function () {
  paintCardsWhere();
  var box = $('cardsWhere');
  if (!box) return;
  box.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('[data-where]') : null;
    if (b) cardsWhere(b.getAttribute('data-where'));
  });
})();

/* The line a card leaves in its place in the conversation while it is not
   drawn there: which card it is, where it is, and the way to it.

   Two ways of saying it. `away` is the card that is on the canvas this
   minute: the line says so and offers to bring it back. `folded` is one the
   canvas has moved on from, and the line is the way back to it. In both,
   the card's number and title are a press that shows it on the canvas, so
   the conversation reads "#4 Grok as the voice: two routes" where the card
   was, and that is where it is found again. */
function cardLine(card, how) {
  var slot = slotOf(card);
  if (!slot) return;
  var was = slot.querySelector('.card-away');
  if (was) was.remove();
  var out = how === 'away';
  var line = el('div', 'card-away' + (out ? ' is-out' : ''));
  var go = el('button', 'card-away-go');
  go.type = 'button';
  if (card.__no) go.appendChild(el('span', 'card-no', '#' + card.__no));
  go.appendChild(el('span', 'card-away-title', card.__title || 'Rouh'));
  if (out) go.appendChild(el('span', 'card-away-say', 'On the canvas'));
  go.title = out ? 'Show it on the canvas' : 'Open this card on the canvas';
  go.addEventListener('click', function () { showOnCanvas(card); });
  line.appendChild(go);
  var act = el('button', 'ctl small', out ? 'Bring it back here' : 'Open on the canvas');
  act.type = 'button';
  act.title = out ? 'Read it in the conversation instead, in among the words about it'
    : 'Open this card on the canvas, beside the conversation';
  act.addEventListener('click', function () {
    if (out) bringCardHome(card, true);
    else openOnCanvas(card, true);
  });
  line.appendChild(act);
  slot.appendChild(line);
}

// The line on a bare canvas, which is said by the canvas having no card on
// it and nothing else: every way a card leaves ends here. Two sentences and
// the stylesheet picks one, because what is true of this column is not the
// same at a desk and on a phone, where a card is put out here only to be
// read full screen and the pane is where pages, tasks and runs open - unless
// the phone reads cards here (`cardsGoOut`), when it says what a desk says.
// The same markup is in the page (index.html) for the moment before any of
// this has run.
function canvasEmptyLine() {
  var out = $('cards');
  if (!out || out.querySelector('.card') || out.querySelector('#cardsEmpty')) return;
  var p = el('p', 'empty');
  p.id = 'cardsEmpty';
  p.appendChild(el('span', 'at-desk', 'Anything Rouh shows you appears here.'));
  p.appendChild(el('span', 'on-phone',
    'What Rouh shows you is in the conversation. Pages, tasks and runs open here.'));
  out.insertBefore(p, out.firstChild);
}

// `byHand` is a person pressing one of the buttons that say this. A press
// takes back a card kept in the conversation, and it stands down whatever is
// loaded over the canvas, because the person is asking to see this card.
// Without one - a card arriving, the window changing - neither happens, and
// a page on the canvas keeps the canvas.
//
// `how` is why it is going out without a press: 'arriving' is a card drawn
// this minute, and 'again' a card revised, or asked for again, while it was
// out here. On a phone
// the canvas is a pane of its own, so a press, or a card arriving on a
// phone that reads cards here, slides it in; and a phone that reads cards
// in the conversation puts one out here by a press and by nothing else,
// except to keep the card it is showing when that card is revised.
function openOnCanvas(card, byHand, how) {
  var host = $('cards');
  var slot = slotOf(card);
  if (!host || !slot) return false;
  // A card drawn in this chat this minute, one shown again, or one a person
  // asked to read here opens the canvas at a desk if it was away.
  // Not for a card arriving under a page that is open there: that one is
  // read in the conversation, as it is with the canvas on the screen.
  if (!narrow() && (byHand || how === 'arriving' || how === 'again') && !canvasShown()
      && (byHand || !layerOpen() || CARDS_UP)) canvasIsWanted(true);
  if (!cardsGoOut() && !byHand && how !== 'again') return false;
  if (layerOpen() && !CARDS_UP) {
    if (!byHand) return false;
    // Over the content, not in place of it: only what is already over the
    // content stands down.
    standDownLayersExcept(null, true);
    if (contentOpen()) CARDS_UP = true;
  }
  if (byHand) card.__kept = false;
  CARDS.bare = false;
  // Where the conversation was being read, if this is being taken out of
  // it on a phone, so the way back lands there (`cardsBackInPlace`).
  if (byHand && narrow() && pane !== 'canvas') {
    var box = streamEl();
    CARD_BACK = box && slot.isConnected ? { card: card,
      at: slot.getBoundingClientRect().top - box.getBoundingClientRect().top } : null;
  }
  // One at a time: the canvas is the wide surface, not a second stream. The
  // one it held folds to its line in the conversation - or, on a phone that
  // reads cards in the conversation, goes back into it whole.
  var was = host.querySelectorAll('.card');
  for (var i = 0; i < was.length; i++) {
    if (was[i] === card) continue;
    if (cardsGoOut()) foldCard(was[i]);
    else bringCardHome(was[i]);
  }
  // After the others have gone, not before. Taking the last one off leaves
  // an empty canvas, and an empty canvas puts the line saying so back - so a
  // line taken away first came straight back, and sat above the card that
  // replaced it saying a card appears here.
  var e = $('cardsEmpty');
  if (e) e.remove();
  slot.classList.remove('is-folded');
  slot.classList.add('is-away');
  cardLine(card, 'away');
  host.appendChild(card);
  card.classList.add('on-canvas');
  sayWhichWay(card);
  host.scrollTop = 0;
  paintCovered();
  if (narrow() && (byHand || how === 'arriving')) setPane('canvas');
  return true;
}

// The card taken out of the conversation on a phone, and how far down the
// conversation's box its place was at that moment. Coming back, the place
// is put at the same height, so the person lands where they were rather
// than where the conversation's box happened to scroll to without it.
var CARD_BACK = null;

// The conversation, on a phone, as it comes back on screen: a card that was
// only out on the canvas to be read full screen goes back into it
// (`cardsSettle`), and the place it was read from is where it was.
function cardsBackInPlace() {
  cardsSettle();
  var back = CARD_BACK;
  CARD_BACK = null;
  var box = streamEl();
  var slot = back ? slotOf(back.card) : null;
  if (!box || !slot || !slot.isConnected) return;
  box.scrollTop += slot.getBoundingClientRect().top - box.getBoundingClientRect().top - back.at;
}

// The press on a card's line: that card, on the canvas, in front of
// whatever was loaded over it. One already there is lit for a moment, so a
// press on the line of the card in plain view still visibly answers - and
// on a phone, where the canvas is the other pane, is slid in to be seen.
function showOnCanvas(card) {
  if (!card.classList.contains('on-canvas')) { openOnCanvas(card, true); return; }
  if (layerOpen() && !CARDS_UP) {
    standDownLayersExcept(null, true);
    if (contentOpen()) cardsCover(true);
  }
  if (narrow()) setPane('canvas');
  var host = $('cards');
  if (host) host.scrollTop = 0;
  card.classList.add('lit');
  window.setTimeout(function () { card.classList.remove('lit'); }, 1400);
}

// Back into its place in the conversation as the line that opens it, and
// not as the card: at a desk a card is read on the canvas, and the canvas
// has moved on from this one.
function foldCard(card) {
  var slot = slotOf(card);
  if (!slot) { card.remove(); return; }
  slot.classList.remove('is-away');
  slot.classList.add('is-folded');
  card.classList.remove('on-canvas');
  slot.appendChild(card);
  cardLine(card, 'folded');
  sayWhichWay(card);
  canvasEmptyLine();
}

// Back into the conversation in full. `byHand` is a person pressing one of
// the buttons that say this, rather than the window having become too
// narrow for a canvas. Only a press is a decision, and only a decision is
// remembered.
function bringCardHome(card, byHand) {
  if (!card) return;
  if (byHand) card.__kept = true;
  var slot = slotOf(card);
  if (!slot) { card.remove(); return; }
  slot.classList.remove('is-away', 'is-folded');
  var line = slot.querySelector('.card-away');
  if (line) line.remove();
  card.classList.remove('on-canvas');
  slot.appendChild(card);
  sayWhichWay(card);
  canvasEmptyLine();
}

// Each card's own way between the conversation and the canvas, offered
// wherever the card has a place in the conversation on screen to go back to.
function cardWaysSay() {
  var ways = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('.card-head .to-canvas'));
  for (var i = 0; i < ways.length; i++) {
    var card = ways[i].closest('.card');
    ways[i].hidden = cardAdrift(card);
    sayWhichWay(card, ways[i]);
  }
}

/* Every card where the screen says it belongs, from wherever they are.

   Called when something other than a card arriving has changed the answer:
   a chat read back off the server, the window crossing 900px, a page taken
   off the canvas, a card on it taken off the conversation. Safe to call as
   often as a resize fires - a second call finds nothing to move.

   - Below 900px every card is in the conversation in full, unless the
     phone reads cards on the canvas (`cardsGoOut`), when it is the same as
     a desk. The one exception is a card opened full screen by hand, which
     stays on the canvas for as long as the canvas is the pane on screen.
   - With a page loaded over the canvas nothing moves under it.
   - Otherwise the canvas holds the newest card: a card read in the
     conversation because it arrived while a page was up (or while the
     window was narrow) goes out, the newest of them, and a bare canvas takes
     the conversation's newest. Every other card folds to its line. A card
     kept by hand is left exactly where it is, and a bare canvas stays bare
     when the newest card is one of those: the person is reading it here.

   It never takes the canvas off a card nobody has asked about since: one
   already out is newer, or is the one opened by hand to be read. */
function cardsSettle() {
  var out = $('cards');
  var host = streamEl();
  if (!out || !host) return;
  var i;
  cardWaysSay();
  if (!cardsGoOut()) {
    var away = pane === 'canvas' ? [] : out.querySelectorAll('.card');
    for (i = 0; i < away.length; i++) bringCardHome(away[i]);
    var folded = host.querySelectorAll('.card-slot.is-folded > .card');
    for (i = 0; i < folded.length; i++) bringCardHome(folded[i]);
    return;
  }
  if (layerOpen()) return;
  var loose = [];
  var inStream = host.querySelectorAll('.card-slot:not(.is-folded):not(.is-away) > .card');
  for (i = 0; i < inStream.length; i++) if (!inStream[i].__kept) loose.push(inStream[i]);
  // Nothing has been put on the canvas since the chat was opened: the cards
  // it was read back with are older than this visit, and the canvas coming
  // back (its rail, a phone switched to Canvas) folds them to their lines
  // rather than putting the newest of them out (`CARDS.bare`).
  if (loose.length && !CARDS.bare) {
    openOnCanvas(loose[loose.length - 1]);
  } else if (!out.querySelector('.card') && !CARDS.bare) {
    var slots = host.querySelectorAll('.card-slot');
    var newest = slots.length ? slots[slots.length - 1].querySelector('.card') : null;
    if (newest && !newest.__kept) openOnCanvas(newest);
  }
  for (i = 0; i < loose.length; i++) {
    if (!loose[i].classList.contains('on-canvas')) foldCard(loose[i]);
  }
}

/* ---------- one card, opened by itself ----------

   Petar, 22 September 2026: "when I click on any of the artifacts. nothing
   happens. just blinks and nothing happens. it is possible that it loads
   undeneath, but ultimately I have no way to see it if it closes when I
   close the task browser."

   Both halves of that were right. Every card on a task's page is owned by
   that task, and what a click on one asked the server for was "open whatever
   owns this" - so the answer was the very page he was looking at, fetched
   and framed a second time. That was the blink. Nothing was ever drawn for
   the card itself, anywhere, so there was no way to read one at all.

   Now a card opens as itself, on a layer of its own over the canvas: its
   name at the top, its blocks under it drawn by the renderer the
   conversation already uses, and a cross that puts the reader back where
   they came from. Two things follow from it being a layer rather than
   something drawn inside the browser, and they are the two the person asked
   for:

   - it stands the task browser down as it opens, so it is in front because
     there is nothing left in front of it, rather than because of a z-index
     somebody has to keep true;
   - closing the browser cannot take it with it, because by the time the card
     is up the browser is already closed.

   `/artifact/<id>` has been this thing's address since the addressing went
   in (`rouh/addressing.py`). This is the first thing to answer it. */

var CARDVIEW = { id: '', title: '', back: '', asked: 0 };

function cardViewing() { return !!(CARDVIEW && CARDVIEW.id); }

/* Open one, by its id or by the number the person says out loud.

   Where the reader is now is read off the screen first, before anything
   moves: opening this stands the other layers down, and afterwards there is
   nothing left to read it off. It is kept as an address rather than as a
   note about a panel, so the way back is the one path a link, a search
   result and the Back button all take. */
function openCardView(id) {
  var want = String(id || '');
  if (!want) return;
  if (!cardViewing()) CARDVIEW.back = addrOnCanvas();
  CARDVIEW.id = want;
  CARDVIEW.title = '';
  var mine = ++CARDVIEW.asked;
  showLayer('cardView');
  cardViewHead('', null, null);
  cardViewSays('Reading it…');
  fetch('/api/canvas/card?id=' + encodeURIComponent(want),
        { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (got) {
        return { ok: r.ok, status: r.status, got: got };
      });
    })
    .catch(function (err) {
      return { ok: false, status: 0, got: { error: 'Rouh could not be reached: '
        + ((err && err.message) || 'no answer') + '.' } };
    })
    .then(function (answer) {
      // Only the newest press counts: two artifacts clicked quickly is two
      // requests in flight, and the one being read is the second.
      if (CARDVIEW.asked !== mine || !cardViewing()) return;
      if (!answer.ok) {
        // Said on the screen rather than nowhere, which is the whole
        // complaint: a click that cannot be answered has to say so.
        CARDVIEW.title = 'That card could not be opened';
        cardViewHead(CARDVIEW.title, null, null);
        cardViewSays((answer.got && answer.got.error)
          || ('Rouh answered ' + answer.status + '.'));
        addrTouch();
        return;
      }
      drawCardView(answer.got);
    });
}

//: What each kind of artifact is called in a sentence. The words the rows
//: carry are the database's - card, page, doc, diff, file, image - and two
//: of them are not what a person would say out loud.
var ARTIFACT_WORDS = { card: 'card', page: 'page', doc: 'document',
                       diff: 'diff', file: 'file', image: 'picture' };

// The head of the layer: what the thing is called, and the same facts a card
// wears in the conversation, so it is recognisably the same card.
function cardViewHead(title, spec, got) {
  var name = $('cardViewTitle'), meta = $('cardViewMeta');
  if (name) name.textContent = title || 'Card';
  if (!meta) return;
  meta.textContent = '';
  if (!spec) return;
  // The number, and only where there is one. A card carries the number the
  // person says out loud; a page or a document taken in off the disk has
  // none, and its row id is not a number anybody would ever say.
  if (typeof spec.card_id === 'number') {
    meta.appendChild(el('span', 'card-no', '#' + spec.card_id));
  }
  if (spec.versions > 1) {
    meta.appendChild(el('span', 'card-ver', 'v' + (spec.version || spec.versions)
      + ' of ' + spec.versions));
  }
  if (spec.at) meta.appendChild(el('span', 'card-when', clockOf(spec.at)));
  /* Where it went, and never the offer to file it: that offer is about the
     conversation the person is standing in, and this card may have been
     opened from anywhere at all.

     Only while the step is really there, too. The chip opens the step it
     names, and a row whose folder has been moved or deleted still names
     where it used to be - offering to open that is offering a second press
     that does nothing, which is the whole of what was being fixed here. */
  if (spec.filed && got && got.on_disk) {
    var chip = filingChip(spec);
    if (chip) meta.appendChild(chip);
  }
  var desc = cardDesc(spec);
  if (desc) meta.appendChild(el('span', 'card-desc', desc));
}

// One line in the body where the card would be: reading it, or why it cannot
// be drawn.
function cardViewSays(words) {
  var body = $('cardViewBody');
  if (!body) return;
  body.textContent = '';
  body.appendChild(el('p', 'card-view-none', words));
}

function drawCardView(got) {
  var spec = (got && got.card) || {};
  var blocks = sourcesLast(Array.isArray(spec.blocks) ? spec.blocks : []);
  CARDVIEW.title = spec.title || (got && got.title) || 'Card';
  cardViewHead(CARDVIEW.title, spec, got);
  var body = $('cardViewBody');
  body.textContent = '';
  var drew = 0, node, i;
  for (i = 0; i < blocks.length; i++) {
    // No card element is handed down, which is what leaves an `html` block
    // without its "Open on the canvas" button: this is the canvas, at the
    // width it was written for, so the button would offer to do what has
    // already been done.
    try { node = renderBlock(blocks[i], 0); } catch (err) { node = null; }
    if (node) { body.appendChild(node); drew++; }
  }
  // A run's "What it changed" is words and not blocks: its commits and the
  // files it touched, drawn as the Under dialog draws them.
  if (!drew && got && got.text) {
    body.appendChild(el('pre', 'under-diff', got.text));
    drew++;
  }
  if (!drew) body.appendChild(cardViewNothing(got || {}));
  footnotes(body);
  addrTouch();
}

/* Nothing to draw, and **why**, which is the half that was missing.

   A card is blocks; a page, a document, a file or a picture is bytes on disk
   that the row only names. Neither is an error, and an empty box is not an
   answer to either, so this says which it is, where the bytes are, and
   whether they are still there. */
function cardViewNothing(got) {
  var kind = ARTIFACT_WORDS[String(got.kind || '')] || 'artifact';
  var path = String(got.path || '');
  var p = el('p', 'card-view-none');
  if (!path) {
    p.appendChild(document.createTextNode('There is nothing drawn in this '
      + kind + ' to put on the screen.'));
    return p;
  }
  p.appendChild(document.createTextNode(got.on_disk
    ? 'Rouh keeps this ' + kind + ' as a file rather than as blocks it draws: '
    : 'This ' + kind + ' names a file that is not in the workspace any more: '));
  p.appendChild(el('code', null, path));
  p.appendChild(document.createTextNode(got.on_disk
    ? '.' : '. There is nothing left of it to draw.'));
  // A built page really can be shown, so it is offered rather than described:
  // it is the one kind of file on this list the canvas already knows how to
  // frame.
  if (got.on_disk && /\.html?$/i.test(path)) {
    var open = el('button', 'ctl small', 'Open the page');
    open.type = 'button';
    open.addEventListener('click', function () { canvasLoad(pageUrl(path)); });
    p.appendChild(document.createElement('br'));
    p.appendChild(open);
  }
  return p;
}

function cardViewClose() {
  if (!cardViewing()) return;
  var back = CARDVIEW.back;
  CARDVIEW.id = '';
  CARDVIEW.title = '';
  CARDVIEW.back = '';
  // Anything still in flight is for a card nobody is looking at now.
  CARDVIEW.asked++;
  var body = $('cardViewBody');
  if (body) body.textContent = '';
  showLayer(null);
  /* And back to what the card was opened from - the task's page, the
     browser, a run - down the one path a link takes. Not the bare canvas: a
     card is read out of something, and the way back has to be to that thing.

     Never while this closer is one of the layers being stood down for
     another that is opening. That is a move to somewhere else, not a card
     being closed, and the address is about to follow it - the same rule
     `addrBack` keeps. */
  if (back && !standingDown && !contentOpen()) goToAddress(back);
  else addrTouch();
}

/* ---------- every card one chat drew, side by side ----------

   Petar, 24 September 2026, about the cards listed on task 61's page:
   "those cards - do they belong to a chat? if so, remove them from the
   directly in this task. they will be found in the chat. the chat three
   dots can have an extra option "Artifacts" or "Cards" and when I click
   it, I see the rendering of all the artifacts in that chat ever lined up
   in the canvas."

   They do: every card's version says which message it came after, and that
   message is one chat's. So Cards, on a chat's three dots, opens this: a
   layer over the canvas, like one card read by itself, holding every card
   that chat drew (`/api/canvas/drawn`, `artifacts.drawn_in`), oldest first
   and each drawn whole by the renderer the conversation uses, side by side
   in as many columns as the canvas has room for. "Cards" and not
   "Artifacts" because that is what every other place calls them: the
   number on each, the line in the conversation, the task's page.

   The chat does not have to be the one open. Closing it gives the canvas
   back as it was, and goes back to a task's page it was opened over. */

var DRAWN = { chat: '', back: '', asked: 0 };

function drawnViewing() { return !!(DRAWN && DRAWN.chat); }

function drawnOpen(chatId, name) {
  var want = String(chatId || '');
  if (!want) return;
  // Read before anything is stood down: opening this closes the tasks, and
  // closing the tasks forgets which page was loaded.
  if (!drawnViewing()) DRAWN.back = tasksViewing() ? (CANVAS.at || '') : '';
  DRAWN.chat = want;
  var mine = ++DRAWN.asked;
  showLayer('drawnView');
  $('drawnTitle').textContent = 'Cards in ' + (name || 'this chat');
  $('drawnMeta').textContent = '';
  drawnSays('Reading its cards…');
  fetch('/api/canvas/drawn?chat=' + encodeURIComponent(want), { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (got) {
        return { ok: r.ok, status: r.status, got: got };
      });
    })
    .catch(function (err) {
      return { ok: false, status: 0, got: { error: 'Rouh could not be reached: '
        + ((err && err.message) || 'no answer') + '.' } };
    })
    .then(function (answer) {
      if (DRAWN.asked !== mine || DRAWN.chat !== want) return;
      if (!answer.ok) {
        drawnSays((answer.got && answer.got.error) || ('Rouh answered ' + answer.status + '.'));
        return;
      }
      drawnDraw(answer.got || {});
    });
  var layer = $('drawnView');
  if (layer) layer.focus();
}

function drawnSays(words) {
  var body = $('drawnBody');
  if (!body) return;
  body.textContent = '';
  body.appendChild(el('p', 'card-view-none', words));
}

function drawnDraw(got) {
  var cards = Array.isArray(got.cards) ? got.cards : [];
  var total = Number(got.total) || cards.length;
  var meta = $('drawnMeta'), body = $('drawnBody');
  if (!body) return;
  if (meta) {
    meta.textContent = '';
    meta.appendChild(el('span', null, !total ? 'No cards yet'
      : total > cards.length ? 'The newest ' + cards.length + ' of ' + total + ' cards'
      : total === 1 ? '1 card' : total + ' cards'));
    if (total > 1) meta.appendChild(el('span', null, 'in the order they were drawn'));
  }
  if (!cards.length) {
    drawnSays('Nothing has been drawn in this chat yet. A card Rouh shows you while '
      + 'you talk in it appears here.');
    return;
  }
  body.textContent = '';
  var strip = el('div', 'drawn-strip');
  for (var i = 0; i < cards.length; i++) strip.appendChild(drawnCard(cards[i]));
  body.appendChild(strip);
  body.scrollTop = 0;
}

// One card, whole, as its head and body are in the conversation, without
// the buttons that move it there and back: here it is read, not moved.
function drawnCard(spec) {
  var card = el('article', 'card drawn-card');
  if (spec.card_id) card.setAttribute('data-card', String(spec.card_id));
  var head = el('div', 'card-head');
  var titles = el('div');
  titles.appendChild(el('div', 'card-title', spec.title || 'Rouh'));
  var meta = el('div', 'card-meta');
  if (typeof spec.card_id === 'number') meta.appendChild(el('span', 'card-no', '#' + spec.card_id));
  if (spec.versions > 1) {
    meta.appendChild(el('span', 'card-ver', 'v' + (spec.version || spec.versions)
      + ' of ' + spec.versions));
  }
  if (spec.at) meta.appendChild(el('span', 'card-when', drawnWhen(spec.at)));
  var desc = cardDesc(spec);
  if (desc) meta.appendChild(el('span', 'card-desc', desc));
  titles.appendChild(meta);
  head.appendChild(titles);
  card.appendChild(head);
  var body = el('div', 'card-body');
  var blocks = sourcesLast(Array.isArray(spec.blocks) ? spec.blocks : []);
  for (var i = 0; i < blocks.length; i++) {
    var node = null;
    try { node = renderBlock(blocks[i], 0); } catch (err) { node = null; }
    if (node) body.appendChild(node);
  }
  if (!body.childNodes.length) body.appendChild(el('p', 'empty', 'Nothing renderable in this one.'));
  footnotes(body);
  card.appendChild(body);
  return card;
}

// "18:04" today, and "23 Sep, 18:04" on any other day: the cards of one chat
// can be days apart.
function drawnWhen(at) {
  var d = new Date(at * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return clockOf(at);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ', '
    + clockOf(at);
}

function drawnClose() {
  if (!drawnViewing()) return;
  var back = DRAWN.back;
  DRAWN.chat = '';
  DRAWN.back = '';
  DRAWN.asked++;
  var body = $('drawnBody');
  if (body) body.textContent = '';
  showLayer(null);
  // Back to the page it was opened over, the way the public pages go back.
  // Never while this closer is one of the layers being stood down for
  // another that is opening: that is a move somewhere else. And not when
  // the page is still there underneath, which it is unless it was left.
  if (back && !standingDown && !contentOpen()) canvasLoad(back);
}

/* The first page of a chat's cards, asked for as the socket says hello.

   The cards are placed among the messages, so they are drawn once the
   conversation is, but nothing about asking for them has to wait for it: the
   page knows which chat it is opening from its address. Until 23 October
   2026 the request went out when the handshake came back, and on the first Rouh the
   canvas then took two seconds more than the conversation, for an answer the
   server makes in ten milliseconds. So it goes out beside `hello`, and
   `loadOlderCards` takes its answer if the chat it opens is that chat and the
   answer is fresh. It is used once, or not at all. */
var CARDS_EARLY = { url: '', at: 0, answer: /** @type {Promise<any> | null} */ (null) };
var CARDS_EARLY_FRESH = 20000;

/** @param {string} chat */
function cardsEarly(chat) {
  if (!chat) return;
  var url = '/api/canvas/cards?limit=' + CARD_PAGE + '&chat=' + encodeURIComponent(chat);
  var answer = fetch(url, { credentials: 'same-origin' }).then(function (r) {
    if (!r.ok) throw new Error('the canvas history answered ' + r.status);
    return r.json();
  });
  // Nobody may be waiting on it yet: a failure here is told by the request it stands in for.
  answer.catch(function () {});
  CARDS_EARLY = { url: url, at: Date.now(), answer: answer };
}

/** @param {string} url */
function cardsAsk(url) {
  var early = CARDS_EARLY;
  CARDS_EARLY = { url: '', at: 0, answer: null };
  if (early.answer && early.url === url && Date.now() - early.at < CARDS_EARLY_FRESH) return early.answer;
  return fetch(url, { credentials: 'same-origin' }).then(function (r) {
    if (!r.ok) throw new Error('the canvas history answered ' + r.status);
    return r.json();
  });
}

// One page of the history, older than what the page already holds. Called
// once when the conversation is drawn, and again each time the reader gets
// near the oldest thing on it.
function loadOlderCards() {
  if (CARDS.loading || !CARDS.more) return Promise.resolve(0);
  // No chat is open at the front door, and a request naming no chat is
  // answered with the active chat's cards: they were drawn into a
  // conversation that has no words in it, every one of them, ten at a time
  // (`boxLaidOut`). Petar, 17 October 2026 (fr_5fcd2acebed7): "the entire
  // history loads ... I literally see all the canvas widgets".
  if (!S.sessionId) return Promise.resolve(0);
  CARDS.loading = true;
  var gen = CARDS.gen;
  // The first page of a chat is the chat being opened. Its cards are read
  // back as their lines in the conversation and none of them goes out on
  // the canvas: what was drawn an hour ago is not what the person opened the
  // chat to look at (`CARDS.bare`). A card goes out when it is drawn now, or
  // when its line's Open on the canvas is pressed.
  var opening = CARDS.oldest == null;
  var note = olderNote();
  // Not for the first page of a chat slid into place along a strip of forks
  // (`resetStreamCards`): put up and taken down again a moment later, it
  // pushed the whole conversation down a line and back up just after the
  // snap. Petar, 15 October 2026 (fr_60918f90d0bb): "There is a snap and
  // after the snap some refresh happens. Can we not have it?"
  if (note && !(opening && CARDS.keepCanvas)) noteShown(note, true);
  // Which chat's cards. Said rather than left to the server, so a switch
  // that crosses with a request already in flight cannot fill this chat's
  // conversation with the other one's cards.
  var url = '/api/canvas/cards?limit=' + CARD_PAGE +
    (CARDS.oldest == null ? '' : '&before=' + CARDS.oldest) +
    (S.sessionId ? '&chat=' + encodeURIComponent(S.sessionId) : '');
  return cardsAsk(url).then(function (data) {
    if (gen !== CARDS.gen) return 0;      // another chat's conversation is on screen now
    var list = (data && data.cards) || [];
    // Newest first, and each one placed where its own message is. Anything
    // older than the oldest message on screen ends up under the note at the
    // top, in the order it was drawn.
    CARDS.restoring++;
    var keep = keepTheScroll();
    try {
      for (var i = 0; i < list.length; i++) {
        renderCard(list[i], true);
        if (list[i].card_id) CARDS.oldest = list[i].card_id;
      }
    } finally { CARDS.restoring--; keep(); }
    CARDS.more = !!(data && data.more) && list.length > 0;
    if (opening) {
      var stays = CARDS.keepCanvas;
      CARDS.keepCanvas = false;
      var out = $('cards');
      if (stays && out && out.querySelector('.card')) cardsFoldLoose();
      else cardsSettle();
    }
    return list.length;
  }).catch(function (err) {
    // Nothing in the conversation is lost by this failing - it is all still
    // on the server - so it says so quietly and lets the next scroll try
    // again.
    console.warn('canvas history:', err.message);
    if (gen === CARDS.gen) CARDS.more = true;
    return -1;
  }).then(function (n) {
    if (gen !== CARDS.gen) return n;      // a later load owns the stream now
    CARDS.loading = false;
    if (note) noteShown(note, CARDS.more);
    // A page of cards that did not fill the box leaves nothing to scroll, so
    // the next lot has to be asked for here: no scroll is coming. Never after
    // a failure, though - that would be a page asking a server that is not
    // answering, as fast as it can, for as long as it is down.
    if (n >= 0 && CARDS.more && boxLaidOut() && !boxScrolls()) return loadOlderCards();
    return n;
  });
}

// The note going up or coming down is a line above the reader too, and is
// measured from the bottom the same way (`keepTheScroll`).
function noteShown(note, on) {
  if (note.hidden === !on) return;
  var keep = keepTheScroll();
  note.hidden = !on;
  keep();
}

// Putting something in above the reader moves everything they are looking at
// down by its height. Measured from the bottom rather than from the top, the
// reader stays exactly where they were - which is also what stops one page of
// older cards from scrolling the top into view and asking for the next.
function keepTheScroll() {
  var host = streamEl();
  if (!host) return function () {};
  var fromTheBottom = host.scrollHeight - host.scrollTop;
  return function () { host.scrollTop = host.scrollHeight - fromTheBottom; };
}

// Take every card off the screen: the ones placed among the words, and the
// one opened at full width. What goes back in their place is the caller's
// business - the active chat's, read back from the start, or nothing at all
// at the front door (`frontDoorGo`).
function clearTheCards() {
  var host = streamEl();
  if (!host) return false;
  var out = $('cards');
  if (out) {
    var away = out.querySelectorAll('.card');
    for (var k = 0; k < away.length; k++) away[k].remove();
    canvasEmptyLine();
  }
  var on = host.querySelectorAll('.card-slot');
  for (var i = 0; i < on.length; i++) on[i].remove();
  CARDS.gen++;
  CARDS.oldest = null;
  CARDS.more = true;
  CARDS.loading = false;
  CARDS.keepCanvas = false;
  CARDS.bare = true;
  return true;
}

// Take every card out of the conversation and read the active chat's back
// from the start. Cards belong to the chat they were drawn in, so switching
// chats changes what is in the stream as surely as it changes the words.
function resetCanvas() {
  if (!clearTheCards()) return;
  return loadOlderCards();
}

/* The same, for a move along a strip of forks, where the canvas is the
   strip's and not the chat's (`rouh/forks.py`): this chat's cards are read
   back into its conversation, and whatever is out on the canvas stays out.
   They arrive as their lines, as a card the canvas has moved on from does,
   unless the canvas is bare, when the newest goes out as it always would. */
function resetStreamCards() {
  var host = streamEl();
  if (!host) return;
  var on = host.querySelectorAll('.card-slot');
  for (var i = 0; i < on.length; i++) on[i].remove();
  CARDS.gen++;
  CARDS.oldest = null;
  CARDS.more = true;
  CARDS.loading = false;
  CARDS.keepCanvas = true;
  return loadOlderCards();
}

// Every card read back into the conversation folded to its line, leaving
// the canvas as it was - except the card the canvas is holding, when it is
// one of this chat's: the copy just read back goes out in its place, so its
// line says it is on the canvas and "Bring it back here" has somewhere to
// bring it.
function cardsFoldLoose() {
  var host = streamEl();
  if (!host || !cardsGoOut()) { cardsSettle(); return; }
  var out = $('cards');
  var shown = out ? out.querySelector('.card') : null;
  var same = shown && cardAdrift(shown) ? shown.getAttribute('data-card') : '';
  // Read back from history, a card is already its line (`renderCard`); one
  // drawn at the moment the chat opened is not yet.
  var read = host.querySelectorAll('.card-slot > .card');
  for (var i = 0; i < read.length; i++) {
    var card = read[i], slot = slotOf(card);
    if (card.__kept) continue;
    if (same && card.getAttribute('data-card') === same) openOnCanvas(card);
    else if (slot && !slot.classList.contains('is-folded')) foldCard(card);
  }
  cardsAdriftSay();
}

// A card on the canvas whose place in a conversation is not on the screen:
// it was drawn in another chat of the strip of forks the person is moving
// along (`resetStreamCards`). It is read where it is, and its button to go
// back into the conversation is not offered, because that conversation is
// not the one beside it.
function cardAdrift(card) {
  var slot = slotOf(card);
  return !!slot && !slot.isConnected;
}

function cardsAdriftSay() {
  var out = $('cards');
  if (!out) return;
  var cards = out.querySelectorAll('.card');
  for (var i = 0; i < cards.length; i++) {
    if (!cardAdrift(cards[i])) continue;
    var ways = cards[i].querySelectorAll('.card-head .to-canvas');
    for (var k = 0; k < ways.length; k++) ways[k].hidden = true;
  }
}

// The stream scrolls inside its own box at every width - on a phone it is
// given a height of its own for exactly this (app.css). That is what bounds
// the reading back: a conversation that grew with its cards instead, in a
// page that scrolls, has no end to reach, and a reader who scrolled to the
// head of the page quietly pulled the whole history in behind them, ten
// cards a request.
function boxScrolls() {
  var host = streamEl();
  return !!host && host.scrollHeight > host.clientHeight + 4;
}

/* Whether the conversation is on the screen at all. Behind the canvas on a
   phone, folded away at a desk, or at the front door it has no layout, so it
   measures as a box that does not scroll and whose oldest item is in view,
   however much is in it. Read like that, every page of cards asked for the
   next one and every resize asked again, until the whole history of the
   chat was in it, and the reader came back to a conversation that was
   nothing but cards. Nothing older is read while it is away; it is read
   when the conversation is back and the reader goes up to it. */
function boxLaidOut() {
  var host = streamEl();
  return !!host && host.clientHeight > 0;
}

// Whether the reader is within about a screenful of the oldest thing the page
// holds, which is at the top of the stream.
function nearTheOldest() {
  var host = streamEl();
  if (!host) return false;
  // The whole conversation fits in its box, so its oldest item is already in
  // view.
  if (!boxScrolls()) return true;
  return host.scrollTop <= host.clientHeight;
}

(function () {
  var host = streamEl();
  if (!host || typeof fetch !== 'function') return;
  var maybe = function () { if (boxLaidOut() && nearTheOldest()) loadOlderCards(); };
  host.addEventListener('scroll', maybe);
  // And when the conversation comes back on the screen, which is not always
  // a resize of the window: a column unfolding at a desk.
  if (window.ResizeObserver) new ResizeObserver(maybe).observe(host);
  // A taller window shows more of the conversation at once, which can put the
  // oldest thing on it in view without anybody scrolling.
  window.addEventListener('resize', maybe);
  window.addEventListener('resize', cardsSettle);
  // The first read is not started here. A card is placed among the words of
  // the conversation, so the words have to be on the screen first:
  // `openTheStream` asks for them once `ready` has brought the transcript.
})();

function clockOf(unixSeconds) {
  var d = new Date(unixSeconds * 1000);
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
}

/* ---------- a layer over the canvas ----------
   A run, the tasks, Settings and the list of chats and tasks each open over
   the canvas, not in place of it: the cards stay where they are underneath,
   at the scroll position they were at, and closing the layer gives the
   canvas back untouched. One layer at a time, and `showLayer` below is what
   enforces it.

   The tasks are one of these now. They were a modal over the whole window
   until 21 September 2026, which put a sheet over the drag that moves a page
   under your hand and over the Ask AI drawer on it, and took all three
   columns to show one. */

var LAYERS = ['runView', 'jobView', 'webView', 'tasksView', 'settingsView', 'memoryView',
              'remindersView', 'goalsView',
              'cardView', 'drawnView', 'sharesView',
              'controlView', 'briefView', 'workView', 'decisionsView', 'actionsView', 'receiptsView', 'homeView', 'approvalsView', 'sourcesView', 'evolutionView', 'thoughtsView', 'boxView', 'runsView',
              'synapseView', 'offlineView'];
var LAYER_CLOSE = { runView: function () { oneClose(); },
                    jobView: function () { jobClose(); },
                    webView: function () { webClose(); },
                    tasksView: function () { tasksClose(); },
                    settingsView: function () { settingsClose(); },
                    memoryView: function () { memoryClose(); },
                    remindersView: function () { remindersClose(); },
                    goalsView: function () { goalsClose(); },
                    cardView: function () { cardViewClose(); },
                    drawnView: function () { drawnClose(); },
                    sharesView: function () { sharesClose(); },
                    controlView: function () { controlClose(); },
                    briefView: function () { briefClose(); },
                    workView: function () { workClose(); },
                    decisionsView: function () { decisionsClose(); },
                    actionsView: function () { actionsClose(); },
                    receiptsView: function () { receiptsClose(); },
                    homeView: function () { homeClose(); },
                    approvalsView: function () { approvalsClose(); },
                    sourcesView: function () { sourcesClose(); },
                    evolutionView: function () { evolutionClose(); },
                    thoughtsView: function () { thoughtsClose(); },
                    boxView: function () { boxClose(); },
                    runsView: function () { runsClose(); },
                    synapseView: function () { synapseClose(); },
                    offlineView: function () { offlineClose(); } };

/* Two levels on the canvas, and every layer is on one of them.

   Content is the bottom level: a task, a page, the task browser, a run,
   Synapse, the Control Room, the brief, goals, reminders, Memory, the live
   browser. It is somewhere the person went, and it stays until they go
   somewhere else.

   The top level is for something looked at for a moment over that content:
   one card read by itself, every card a chat drew, Settings, the list of
   public pages - and a card put out on the canvas by hand
   (`cardsCover`). It lies over the content and never closes it, so
   dismissing it shows the content again exactly as it was: the frame not
   loaded again, the page at the place it was scrolled to.

   Petar, 4 October 2026 (fr_30f188faa389), after a task page had been lost
   on a phone to a press of the corner and then to a card read full screen:
   "Canvas is temporary and can be closed. Content lives and just switches
   between chat and content." Until then every layer stood every other one
   down as it opened, and Settings, a card and the public pages each put the
   page back afterwards by loading its address again. */
var COVERS = ['cardView', 'drawnView', 'settingsView', 'sharesView'];
// Each layer's own word for whether it is open, read after a closer has
// cleared it to tell which layers are still up.
var LAYER_ON = { runView: function () { return oneViewing(); },
                 jobView: function () { return jobViewing(); },
                 webView: function () { return webViewing(); },
                 tasksView: function () { return tasksViewing(); },
                 settingsView: function () { return settingsViewing(); },
                 memoryView: function () { return memoryViewing(); },
                 remindersView: function () { return remindersViewing(); },
                 goalsView: function () { return goalsViewing(); },
                 cardView: function () { return cardViewing(); },
                 drawnView: function () { return drawnViewing(); },
                 sharesView: function () { return !!(SHARES && SHARES.open); },
                 controlView: function () { return controlViewing(); },
                 briefView: function () { return briefViewing(); },
                 workView: function () { return workViewing(); },
                 decisionsView: function () { return decisionsViewing(); },
                 actionsView: function () { return actionsViewing(); },
                 receiptsView: function () { return receiptsViewing(); },
                 homeView: function () { return homeViewing(); },
                 approvalsView: function () { return approvalsViewing(); },
                 sourcesView: function () { return sourcesViewing(); },
                 evolutionView: function () { return evolutionViewing(); },
                 thoughtsView: function () { return thoughtsViewing(); },
                 boxView: function () { return boxViewing(); },
                 runsView: function () { return runsViewing(); },
                 synapseView: function () { return synapseViewing(); },
                 offlineView: function () { return offlineViewing(); } };

function isCover(id) { return COVERS.indexOf(id) >= 0; }

/* Standing every other layer down is part of showing one, and not something
   each opener is trusted to remember.

   Each layer keeps a flag of its own saying whether it is open - `ONE.viewing`,
   `TASKVIEW.rel`, `SETTINGS.open`, `PROJ.open` - and the rest of the page
   asks those flags rather than the screen. So a flag left true for a layer
   that has just been hidden is a lie the whole page believes, and the button
   that opens that layer closes it instead: the press does nothing visible,
   and it takes the person out of whatever they were looking at on the way.

   That is what happened to the chats. It was the fourth layer, and the three
   openers written before it each named the other three closers by hand and
   none of them was ever taught the new one. Opening a run, a task or Settings
   over the list left the page sure the list was still up, so the next press
   of "All chats and tasks" closed a list nobody could see and showed the
   bare canvas, and only the press after that opened it. A project is made
   from that list and from nowhere else, so for anybody who was not starting
   from an empty canvas the projects were simply out of reach.

   One table, `LAYER_CLOSE`, already says how each layer is closed. Using it
   here is what makes a layer added next impossible to forget: it has to go in
   that table to be closed at all.

   Re-entrant on purpose - every closer ends in `showLayer(null)` - so the
   guard lets the outermost call be the one that decides what is on the
   screen. Each closer clears its own flag before it calls back in, so
   nothing here can loop. */
var standingDown = false;

// `coversOnly` stands down the top level and leaves the content under it,
// which is what opening something on the top level does.
function standDownLayersExcept(keep, coversOnly) {
  if (standingDown) return;
  standingDown = true;
  try {
    for (var i = 0; i < LAYERS.length; i++) {
      if (coversOnly && !isCover(LAYERS[i])) continue;
      if (LAYERS[i] !== keep && LAYER_CLOSE[LAYERS[i]]) LAYER_CLOSE[LAYERS[i]]();
    }
  } finally {
    standingDown = false;
  }
}

// `id` is the layer opening. With none, a closer has just cleared its own
// flag, and what stays up is whatever was up and still says it is open:
// the content under a card or Settings that has gone.
function showLayer(id) {
  var cover = !!id && isCover(id);
  if (id) standDownLayersExcept(id, cover);
  // Anything opened takes the place of a card that was over the content.
  if (id) CARDS_UP = false;
  var up = [];
  for (var i = 0; i < LAYERS.length; i++) {
    var name = LAYERS[i], node = $(name);
    if (!node) continue;
    var stays = name === id ||
      ((!id || (cover && !isCover(name))) && !node.hidden && LAYER_ON[name]());
    node.hidden = !stays;
    if (stays) up.push(name);
  }
  paintCovered();
  var panel = $('canvasPanel');
  if (panel) panel.classList.toggle('layered', up.length > 0);
  // The projects and the Gene therapy board lie over the conversation and the
  // canvas together, so a layer opened while either is up would open onto a
  // canvas nobody can see. They stand down like everything else, and for
  // the same reason.
  if (id) projectsClose();
  if (id) gtBoardClose();
  // A run, a task and Settings all open on the canvas. On a phone the canvas
  // may not be the pane on screen, and a layer opened onto a pane nobody is
  // looking at is a button that did nothing. Closing one leaves the person
  // where they are: they are already looking at the canvas.
  if (id && narrow() && !CANVAS.redraw) setPane('canvas');
  // At a desk the same is the canvas opened, if it was put away.
  if (id && !narrow() && !CANVAS.redraw) canvasIsWanted();
  // And the corner cross says what it will close, which is this.
  paintPaneButton();
  // A page taken off the canvas leaves it bare, and the bare canvas at a
  // desk holds the newest card: one that arrived while the page was up was
  // read in the conversation, since it was not to cover the page, and goes
  // out now. Only the outermost call - the closers called on the way to
  // showing another layer come back through here too, and nothing moves
  // under a layer that is about to open.
  if (!id && !standingDown) cardsSettle();
  // What is on the canvas has changed, so the address bar has. Every way of
  // opening a run, a task, a project or a step ends here, which is what
  // makes this the one place the address has to be told (see 10f).
  addrTouch();
}

// What is in front on the canvas: something over the content first, then
// the content.
function layerOpen() {
  var base = null;
  for (var i = 0; i < LAYERS.length; i++) {
    var node = $(LAYERS[i]);
    if (!node || node.hidden) continue;
    if (isCover(LAYERS[i])) return LAYERS[i];
    if (!base) base = LAYERS[i];
  }
  return base;
}

// The content on the canvas, whether or not something is over it.
function contentOpen() {
  for (var i = 0; i < LAYERS.length; i++) {
    var node = $(LAYERS[i]);
    if (node && !node.hidden && !isCover(LAYERS[i])) return LAYERS[i];
  }
  return null;
}

/* A card put out on the canvas by hand while content is open lies over the
   content the way Settings does, rather than closing it. It is the top
   level for as long as the canvas holds a card: putting it back in the
   conversation, Escape, leaving the canvas on a phone or opening anything
   else ends it, and the content is there again underneath. */
var CARDS_UP = false;

function cardsCover(on) {
  CARDS_UP = !!on;
  paintCovered();
  paintPaneButton();
}

// Which content is under something, so it is kept but not drawn: hidden
// rather than taken off the page, so a task's frame is not loaded again and
// stays scrolled where it was.
function paintCovered() {
  var out = $('cards');
  if (CARDS_UP && !(out && out.querySelector('.card') && contentOpen())) CARDS_UP = false;
  var top = layerOpen();
  var over = CARDS_UP || (!!top && isCover(top));
  for (var i = 0; i < LAYERS.length; i++) {
    var node = $(LAYERS[i]);
    if (!node) continue;
    var under = over && !node.hidden && !isCover(LAYERS[i]);
    node.classList.toggle('under', under);
    if (under) node.setAttribute('inert', '');
    else node.removeAttribute('inert');
  }
  var panel = $('canvasPanel');
  if (panel) {
    panel.classList.toggle('covered', over && !!contentOpen());
    panel.classList.toggle('cards-up', CARDS_UP);
  }
}

// Back from a card over the content: it goes back to the conversation the
// way the canvas moves on from a card - to its line at a desk, or whole into
// the conversation on a phone - and the content shows again.
function cardsUncover() {
  if (!CARDS_UP) return false;
  var out = $('cards');
  var on = out ? out.querySelectorAll('.card') : [];
  for (var i = 0; i < on.length; i++) {
    if (cardsGoOut()) foldCard(on[i]);
    else bringCardHome(on[i]);
  }
  cardsCover(false);
  return true;
}

// Whatever else Escape already closes and is open right now: the orb over the
// whole screen, a picture opened full size. One press
// closes one thing, so a layer under any of those keeps its place. The node
// card marks the key used instead, which is the same rule seen from the
// other side - its handler is registered before this one.
function somethingElseIsOver() {
  // The sharing panel is one of these: while it is up it is the thing in
  // front, so Escape closes it rather than the page it is about.
  if (ORBX.open || gtOver() || sharePanelOpen()) return true;
  // Pointing at part of the page: Escape stops that and nothing else.
  if (ASK.pointing) return true;
  // The picture editor is over everything while it is up.
  if (editorOpen()) return true;
  var box = $('lightbox');
  return !!(box && !box.hidden);
}

// Escape closes whatever is over the canvas - unless the person is typing,
// and the run's terminal counts as typing: Escape there belongs to the
// program running in it.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || e.defaultPrevented || somethingElseIsOver()) return;
  var where = document.activeElement;
  if (where && where.closest &&
      where.closest('.one-term-wrap, .web-screen.mine, input, textarea, select, dialog')) return;
  // The projects are over both columns rather than over the canvas, so they
  // are not one of the layers and are the thing on top while they are up.
  if (projectsViewing()) { e.preventDefault(); projectsClose(); return; }
  if (cardsUncover()) { e.preventDefault(); return; }
  var open = layerOpen();
  if (!open) return;
  e.preventDefault();
  // Escape climbs the breadcrumb rather than going straight to the bare
  // canvas: from a page to its task, from a task to the index, and only then
  // out. So one press is always one step back out, never all the way.
  if (open === 'tasksView') { tasksUp(); return; }
  LAYER_CLOSE[open]();
});

/* 1 to 4 answer a conflict card.

   The number on each button is the key that presses it, which is what card
   489 asked for: the whole of the person's part is one digit, so it should
   take one key. Only while a live card is on the screen, and never while
   somebody is typing, because a digit typed into the composer is a digit. */
document.addEventListener('keydown', function (e) {
  if (e.defaultPrevented || somethingElseIsOver() || tasksViewing()) return;
  if (conflictKey(e)) e.preventDefault();
});

/* Escape stops the turn, the way it does in a terminal.

   Registered after the handler above on purpose, so one press closes one
   thing: whatever Escape already closed still closes first, and the turn is
   stopped by the press after it. The one exception is the composer. A person
   typing has their hands on the keyboard and their eyes on the answer, and
   Escape there is about the answer, never about a panel somewhere else on
   the screen - which is why the handler above steps out of the way inside a
   text box and this one does not. */
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || e.defaultPrevented || !turnIsRunning()) return;
  var where = document.activeElement;
  var composing = !!(where && where.closest && where.closest('#composer'));
  if (!composing && (somethingElseIsOver() || layerOpen())) return;
  // A run's terminal keeps its own Escape: it belongs to the program in it.
  if (where && where.closest && where.closest('.one-term-wrap')) return;
  e.preventDefault();
  stopTheTurn();
});

export { ANSWER_HELD, answerHeldGo, ASK_ROUTE, askSaid, browserOfflineSay, cardFiled, CARDS, cardsEarly, cardsUnpark, CARDS_UP,
  cardsAdriftSay, cardsBackInPlace, cardsGoOut, cardsSettle, cardsUncover, CARDVIEW, cardViewClose,
  cardViewing, cardWaysSay, clearTheCards, clockOf, composeKept, composeSaid, contactNoteSaid,
  contentOpen, drawnClose, drawnOpen, FILING, footnotes, frameLoad, goalMapTell, goToAddress,
  inboxChanged, inboxLost, inboxSaid, layerOpen, LAYERS, loadOlderCards, mdCells, mdIsRule,
  notedConflicts, onConflictDone, openCardView, paintCovered, pickSaid, projectSaidIt,
  renderBlock, renderCard, renderMarkdown, resetCanvas, resetStreamCards, showConflictCard,
  showLayer, sourcesLast, standingDown, streamEl, svgEl, taskAnswerHere, taskAnswerSettled,
  taskPageFolder, taskPageRenamed, taskSaidIt, WORKSPACE_ROUTE };
