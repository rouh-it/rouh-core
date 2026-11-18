/* A chat's two controls (rouh/reading.py), each with one job (Petar, 16 November 2026: "I hate duplicate
 * stuff ... the bar on the top we can use to control the contents ... while bottom includes rules,
 * tools, memory, this should control the other content"):
 *
 * - **Chat Options**, the button beside the model: how Rouh works here. Below.
 * - **The strip under the chat's title**: "Included content" and what this chat is about, in a few words
 *   ("Task 130 · 2 pages · subtasks left out", "Forked from 💬 General · parent chat included"), and pressed,
 *   its own panel, "What this chat reads" (`contentPaint`): This task, Other files in the folder, Subtasks
 *   (all or chosen; everything, notes only or pages only), Subtasks' chat histories, and for a subtask's chat
 *   Parent task and its chat history, each a switch with its size in tokens ("46k Tokens", `tokensSaid`),
 *   counted on what the model is sent (rouh/tokencount.py), and what is read now with what is read as an
 *   outline. A fork's panel draws the whole tree of chats it comes from (`treePaint`; Petar, 18 November
 *   2026): the chat it all started in at the top, each forked from the one above and set in further, each
 *   with a switch of its own, and "This chat - 🧵 Chat fork history" at the foot in the accent colour. "Subtasks" since
 *   17 November 2026 (Petar: "rename steps to subtasks"); the keys the server keeps still say steps.
 *   Only the choices a chat has are drawn; a chat with none (General, a chat of its own) has no strip,
 *   and an incognito chat's is a quiet line. On a phone the panel is a sheet from the bottom.
 *
 * Chat Options, until 17 November 2026 the one control for both:
 *
 * Petar, 15 November 2026 (Chat Change Planning): "context controls should be unified everywehre.
 * same icon, same location, same interface ... a button next to the smart". So a button beside the
 * model on the composer's line, in every chat (sliders since 16 November 2026: "this is book
 * doesn't make sense to me"); pressing it opens one panel above the box, headed "Chat Options":
 *
 * - while the chat is incognito, that it is and what is kept (Incognito is a button of its own,
 *   `incogBtn`, beside this one);
 * - the mode, three rows like the model's (Petar, 16 November 2026: "it can be a selector like the
 *   smart/cheap"): Simple chat, Full capabilities and Custom (`modes`), each with one line of what it
 *   means, and the one sentence that permission, privacy and safety cannot be turned off;
 * - on Custom only, memory, the person's rules and tools; a switch pressed anywhere puts the chat on
 *   Custom. What the chat is about is never here, and a mode never changes it;
 * - a link to everything this chat is told, full screen (`fullOpen`).
 *
 * Reset to defaults is a button at the right of the panel's title bar (Petar, 16 November 2026: "reset
 * to defaults should to top-right on the title bar"). On a desk, Custom's choices and the link stand
 * in a column of their own to the right of the modes ("when I press custom, the choices should appear
 * on the right side for desktop"); a phone keeps one column, the choices under the modes. The mode is
 * the chat's own, like the model beside it ("behavior should be like smart/cheap selection"): nothing
 * here saves it for new chats, and the button says which it is, Simple, Full or Custom (`paintBtn`).
 *
 * The full list (Petar, 16 November 2026): the same switches, kept in step with the panel; every
 * rule and piece of live context with its whole text and the switch it follows; filters by switch
 * and a search; a switch for each item but the locked ones; Reset to defaults in its title bar; and
 * one line for Synapse, which follows Memory.
 *
 * Every switch is a real button with role="switch", the whole row its target. A press is drawn at
 * once and saved after (Petar, 16 November 2026: "visuals should be immediate, request ajax should go
 * afterwards"): `guess` puts the change into a copy of what the server last said and that is painted
 * in the same task as the click; the save goes in the background, and its answer is drawn when it
 * comes, with the counts ("61 of 93") it alone can work out. Until then the counts are drawn faded,
 * as the old ones (`READ.pending`), never guessed. A save that fails puts back what the server last
 * said, with a quiet line in the panel. Outside the chain, like app/composer_extras.js, and imported
 * by app.js after it.
 */
import { CHATS, openChat } from 'app/chats.js';
import { composerPopsClose } from 'app/composer_extras.js';
import { $, el } from 'app/helpers.js';
import { ASK } from 'app/runs.js';
import { notify } from 'app/notices.js';
import { shared } from 'app/shared.js';

/** @typedef {{ id: string, kind: string, label: string, owner: string, path: string, size: string,
 *              tokens: number, on: boolean, how: string, group?: string }} ReadItem */
/** @typedef {{ id: string, title: string, text: string, source: string, locked: boolean, own?: boolean,
 *              on: boolean, off: boolean, with?: string, when?: string, live?: boolean, fills?: string }} ReadRule */
/** @typedef {{ key: string, title: string, sub: string, on: boolean, tokens: number, size: string,
 *              count: number, outlined: number }} ContentGroup */
/** One chat of a fork's tree: a parent chat with its switch, or the chat itself (`self`), with no switch.
    @typedef {{ id: string, label: string, tokens: number, on: boolean, depth: number, self?: boolean }} TreeChat */
/** @typedef {{ chat: string, kind: string, incognito: boolean, settings: Record<string, any>,
 *              mode?: string, content?: ContentGroup[], tree?: TreeChat[],
 *              items: ReadItem[], subtasks?: {id: string, label: string, on: boolean, size?: string, tokens?: number}[],
 *              task?: {id: string, label: string}, rules: ReadRule[], context?: ReadRule[], strip: string,
 *              outlined: number, reads: number, budget: number, kept?: string,
 *              synapse?: {text: string, on: boolean}, sources?: Record<string, string>,
 *              tools?: Record<string, {name: string, words: string}[]>,
 *              last?: {tokens: number, cached: number, requests: number, ts: number} | null }} ReadView */

var btn = /** @type {HTMLButtonElement | null} */ ($('readingBtn'));
var pop = $('readingPop');
var strip = /** @type {HTMLButtonElement | null} */ ($('readingStrip'));
/** The strip's own panel: what this chat is about. On the page itself, like the full list. */
var cpop = $('contentPop');
var cback = $('contentBack');
if (cpop && cpop.parentElement !== document.body) document.body.appendChild(cpop);
if (cback && cback.parentElement !== document.body) document.body.appendChild(cback);
var LAYERS = 'M4 7l8-4 8 4-8 4-8-4zM4 12l8 4 8-4M4 17l8 4 8-4';
var CHEV = 'M6 9l6 6 6-6';
var incogBtn = /** @type {HTMLButtonElement | null} */ ($('incogBtn'));
var full = $('toldFull');
// On the page itself, so no box around the composer can hold it inside its own bounds.
if (full && full.parentElement !== document.body) document.body.appendChild(full);
/** The full list: which switch's items are shown, the search, and what had the focus before it opened. */
var FULL = { filter: 'all', q: '', opener: /** @type {HTMLElement | null} */ (null) };
var SLIDERS = 'M4 7h9M17 7h3M4 17h3M11 17h9M17 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM11 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0z';
var HAT = 'M3 11h18M6.5 11l1.6-5.5h7.8L17.5 11M10.1 16a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0zM19.1 16a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0zM10.1 16h3.8';
var READ = { chat: '', data: /** @type {ReadView | null} */ (null), more: false, busy: false, asked: 0, focus: '', painted: '', openAfter: false, doc: '', after: '', from: '',
             /** What the server last said, which a failed save goes back to. */
             confirmed: /** @type {ReadView | null} */ (null),
             /** A press is drawn and its save not answered yet: the counts are the old ones, faded. */
             pending: false,
             /** The quiet line a failed save leaves in the panel, until the next press. */
             oops: '' };
var incogClose = /** @type {HTMLButtonElement | null} */ ($('incogClose'));
var btnWord = $('readingWord');
var incogAsk = $('incogAsk');

var LOCK = 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z';

/** The three modes, as the selector says them (rouh/reading.py `MODES`), each with one line of what it means.
    Full first (Petar, 18 November 2026: "full rouh capabilities should be the first option"). */
var MODES = [
  ['full', 'Full Rouh Capabilities', 'Everything on: memory, your rules, Rouh Tools and LLM Tools.'],
  ['simple', 'Simple chat', 'Plain talk with the model: web search, no memory, rules or Rouh Tools.'],
  ['custom', 'Custom', 'Choose each of them yourself.']
];
var SAFETY = 'Permission, privacy and safety cannot be turned off.';
/** The mode in one word, on the button, as the model's button says Smart or Cheap. The long names are only
    the popup's own (Petar, 18 November 2026: "Button should be "Full""); everywhere else says this. */
var SHORT = /** @type {Record<string, string>} */ ({ simple: 'Simple', full: 'Full', custom: 'Custom' });

function currentChat() { return String((CHATS && CHATS.active) || ''); }

/** @param {string} d @param {number} size */
function icon(d, size) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d);
  svg.appendChild(p);
  return svg;
}

/** One row with a switch: the whole row is the button. @param {string} key @param {boolean} on
    @param {string} title @param {string} sub @param {string} [cls] @param {boolean} [locked] */
function row(key, on, title, sub, cls, locked) {
  var b = el('button', 'reading-row' + (cls ? ' ' + cls : ''));
  b.type = 'button';
  b.setAttribute('role', 'switch');
  b.setAttribute('aria-checked', on ? 'true' : 'false');
  b.dataset.key = key;
  if (locked) b.setAttribute('aria-disabled', 'true');
  var t = el('span', 'reading-row-t');
  var name = el('b', '');
  if (locked) { var lk = el('span', 'reading-lock'); lk.appendChild(icon(LOCK, 12)); name.appendChild(lk); name.appendChild(document.createTextNode(' ')); }
  name.appendChild(document.createTextNode(title));
  t.appendChild(name);
  if (sub) t.appendChild(el('span', '', sub));
  b.appendChild(t);
  b.appendChild(el('span', 'reading-sw'));
  b.title = title + (locked ? ': always on' : on ? ': on' : ': off');
  return b;
}

/** @param {string} label */
function sec(label) {
  var s = el('div', 'reading-sec');
  if (label) s.appendChild(el('p', '', label));
  return s;
}

/** Every item a chat can be told: the rules, then the live context. @param {ReadView} d @returns {ReadRule[]} */
function allItems(d) { return (d.rules || []).concat(d.context || []); }

/** "61 of 93": what is told now, of everything that can be. @param {ReadView} d */
function toldCount(d) {
  var every = allItems(d);
  return { told: every.filter(function (r) { return r.on; }).length, all: every.length };
}

/** The button on the composer's line: its one word is the chat's mode. @param {ReadView | null} d */
function paintBtn(d) {
  if (!btn || !btnWord) return;
  var mode = d && d.settings ? String(d.settings.mode || '') : '';
  btnWord.textContent = SHORT[mode] || 'Options';
  btn.dataset.mode = mode;
  var says = 'Chat Options: ' + (SHORT[mode] || 'what this chat uses') + '. Memory, your rules, Rouh Tools and LLM Tools';
  btn.dataset.tip = says;
  btn.setAttribute('aria-label', 'Chat Options, ' + (SHORT[mode] || 'loading'));
}

/** The strip, from the server's words. @param {ReadView | null} d */
function paintStrip(d) {
  paintBtn(d);
  document.body.classList.toggle('chat-incognito', !!(d && d.incognito));
  var mark = $('incogMark');
  if (mark) mark.hidden = !(d && d.incognito);
  if (incogClose) incogClose.hidden = !(d && d.incognito);
  if (incogAsk && !(d && d.incognito)) incogAsk.hidden = true;
  if (incogBtn) {
    incogBtn.setAttribute('aria-pressed', d && d.incognito ? 'true' : 'false');
    incogBtn.dataset.tip = d && d.incognito ? 'Leave incognito: this chat is deleted, and you go back to General'
      : 'Incognito: a new chat where nothing is kept, deleted when you leave it';
  }
  if (!strip) return;
  var words = $('readingStripWords'), stripMark = $('readingStripMark');
  if (!words || !stripMark) return;
  var groups = ((d && d.content) || []).concat(/** @type {any[]} */ ((d && d.tree) || []));
  // The page open on the canvas beside the chat, which every message is told (`rouh/page_in_chat.py`).
  var bits = d && d.strip ? d.strip.split(' · ') : [];
  if (d && ASK.doc) bits.push('This page');
  READ.doc = ASK.doc;
  // Nothing to choose and nothing to say (General, a chat of its own): no strip at all.
  strip.hidden = !d || (!d.incognito && !bits.length);
  if (strip.hidden) { if (cpop && !cpop.hidden) openContent(false); return; }
  // Incognito, or nothing to choose: a quiet line, never a press that opens an empty panel.
  var quiet = !groups.length;
  strip.disabled = quiet;
  strip.classList.toggle('quiet', quiet);
  words.textContent = '';
  stripMark.textContent = '';
  stripMark.appendChild(icon(d && d.incognito ? HAT : LAYERS, 15));
  if (d && d.incognito) {
    words.appendChild(el('b', '', 'Incognito:'));
    words.appendChild(document.createTextNode('nothing here is kept'));
    if (bits.length) words.appendChild(document.createTextNode(' · '));
  } else {
    words.appendChild(el('b', '', 'Included content'));
  }
  bits.forEach(function (bit, i) {
    if (i) words.appendChild(document.createTextNode(' · '));
    words.appendChild(el('span', 'reading-strip-bit', bit));
  });
  // Faded while a choice made here is being saved: the summary is the server's.
  words.classList.toggle('pending', READ.pending && !!(cpop && !cpop.hidden));
  var chev = $('readingStripChev');
  if (chev) { chev.textContent = ''; chev.hidden = quiet; if (!quiet) chev.appendChild(icon(CHEV, 12)); }
  var says = (d && d.incognito ? 'Incognito chat, nothing is kept' + (bits.length ? ': ' + bits.join(', ') : '') + '.'
    : 'Included content: ' + bits.join(', ') + '.') + (quiet ? '' : ' Press to choose what this chat reads.');
  strip.title = says;
  strip.setAttribute('aria-label', says);
  if (quiet && cpop && !cpop.hidden) openContent(false);
}

/** Tokens said short: 840, 3.1k, 74k, 1.2M. @param {number} n */
function kTokens(n) {
  n = Math.max(0, Math.round(n || 0));
  if (n < 1000) return String(n);
  if (n < 10000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  if (n < 1e6) return Math.round(n / 1000) + 'k';
  return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
}

/** A size as the panel says it, the count alone (Petar, 18 November 2026: "Do not evaluate very long or
    not. Just say 46k Tokens"): "46k Tokens", "3.1k Tokens", "840 Tokens". @param {number} n */
function tokensSaid(n) { return kTokens(n) + ' Tokens'; }

/** A size beside a choice, with the whole number on hover. @param {number | undefined} n */
function sizeTag(n) {
  var z = el('span', 'reading-size', tokensSaid(n || 0));
  z.title = 'About ' + Math.round(n || 0).toLocaleString() + ' tokens, as the model is sent it';
  return z;
}

/** One choice of the strip's panel: a switch with its size beside it. @param {ContentGroup} g */
function contentRow(g) {
  var b = row('c:' + g.key, g.on, g.title, g.sub, 'content');
  if (g.size) b.insertBefore(sizeTag(g.tokens), b.lastChild);
  return b;
}

/** A fork's tree of chats (rouh/reading.py `tree`): each parent chat a row set in by how far down the chain
    it is, its name a link to it and its switch its own; the chat itself at the foot, in the accent colour,
    with its size and no switch, because its own words are always sent. @param {TreeChat[]} chats */
function treePaint(chats) {
  var box = el('div', 'reading-sec content-tree');
  box.setAttribute('role', 'list');
  box.setAttribute('aria-label', 'The chats this chat comes from');
  chats.forEach(function (c) {
    var r = el('div', 'tree-row' + (c.self ? ' self' : '') + (c.depth ? ' kid' : ''));
    r.setAttribute('role', 'listitem');
    r.style.setProperty('--depth', String(c.depth));
    if (c.self) {
      r.appendChild(el('span', 'tree-name', c.label));
    } else {
      var go = el('button', 'tree-name', c.label);
      go.type = 'button';
      go.dataset.open = c.id;
      go.title = 'Open ' + c.label;
      r.appendChild(go);
    }
    r.appendChild(sizeTag(c.tokens));
    if (!c.self) {
      var sw = el('button', 'tree-sw');
      sw.type = 'button';
      sw.setAttribute('role', 'switch');
      sw.setAttribute('aria-checked', c.on ? 'true' : 'false');
      sw.setAttribute('aria-label', 'Send ' + c.label + ' with each message');
      sw.title = c.label + (c.on ? ': sent with each message' : ': left out');
      sw.dataset.key = 'par:' + c.id;
      sw.appendChild(el('span', 'reading-sw'));
      r.appendChild(sw);
    }
    box.appendChild(r);
  });
  return box;
}

/** A row of buttons, one pressed. @param {string} key @param {string} now @param {string} label
    @param {string[][]} opts */
function seg(key, now, label, opts) {
  var g = el('span', 'reading-seg');
  g.setAttribute('role', 'group');
  g.setAttribute('aria-label', label);
  opts.forEach(function (o) {
    var b = el('button', '', o[1]);
    b.type = 'button';
    b.dataset.cseg = key + ':' + o[0];
    b.setAttribute('aria-pressed', now === o[0] ? 'true' : 'false');
    g.appendChild(b);
  });
  return g;
}

/** The strip's panel: what this chat is about. @param {ReadView} d */
function contentPaint(d) {
  if (!cpop) return;
  var s = d.settings;
  cpop.textContent = '';
  var bar = el('div', 'reading-top');
  var h = el('h2', '', 'What this chat reads');
  h.id = 'contentHead';
  h.tabIndex = -1;
  bar.appendChild(h);
  var x = el('button', 'content-x');
  x.type = 'button';
  x.dataset.close = '1';
  x.setAttribute('aria-label', 'Close');
  x.appendChild(icon('M6 6l12 12M18 6L6 18', 18));
  bar.appendChild(x);
  cpop.appendChild(bar);
  cpop.appendChild(el('p', 'reading-verdict content-hint',
    'Select the contextual information that supports each message of this conversation'));
  // A save that failed is said where the switches are, not under the list.
  if (READ.oops) {
    var oops = el('p', 'reading-oops', READ.oops);
    oops.setAttribute('role', 'status');
    cpop.appendChild(oops);
  }
  var list = el('div', 'reading-sec content-groups');
  (d.content || []).forEach(function (g) {
    list.appendChild(contentRow(g));
    if (g.key !== 'steps' || !g.on) return;
    var subs = d.subtasks || [];
    var more = el('div', 'content-more');
    more.appendChild(el('p', '', 'Which subtasks'));
    more.appendChild(seg('subtasks', s.subtasks === 'some' ? 'some' : 'all', 'Which subtasks',
      [['all', 'All ' + subs.length], ['some', 'Chosen']]));
    more.appendChild(el('p', '', 'Of each subtask'));
    more.appendChild(seg('steps_what', s.steps_what || 'all', 'What of each subtask',
      [['all', 'Everything'], ['md', 'Notes only'], ['html', 'Pages only']]));
    list.appendChild(more);
    if (s.subtasks === 'some') {
      subs.forEach(function (sub) {
        var r = row('sub:' + sub.id, sub.on, sub.label, '', 'sub');
        if (sub.size) r.insertBefore(sizeTag(sub.tokens), r.lastChild);
        list.appendChild(r);
      });
    }
  });
  if (list.childNodes.length) cpop.appendChild(list);
  if (d.tree && d.tree.length) cpop.appendChild(treePaint(d.tree));

  // What is read now: what the choices bring in, each with its size, and what is too much to read whole.
  var read = (d.items || []).filter(function (it) { return it.kind !== 'fork' && it.kind !== 'parent' && it.kind !== 'self'; });
  if (read.length) {
    var sec2 = sec(d.outlined ? 'What is read now · ' + d.outlined + ' of ' + read.length + ' as outlines'
      : 'What is read now · all ' + read.length + ' read whole');
    if (d.outlined) sec2.appendChild(el('p', 'reading-verdict', 'Too much to read whole together, so the longest are read as outlines: their headings and first lines.'));
    var ul = el('ul', 'reading-items' + (READ.pending ? ' pending' : ''));
    var order = read.slice().sort(function (a, b) {
      return (a.how === 'outline' ? 0 : 1) - (b.how === 'outline' ? 0 : 1) || b.tokens - a.tokens;
    });
    (READ.more ? order : order.slice(0, 4)).forEach(function (it) {
      var li = el('li', '');
      var n = el('span', 'n', it.owner && it.group !== 'task' && it.group !== 'others' ? it.owner + ' · ' + it.label : it.label);
      n.title = it.path || it.label;
      li.appendChild(n);
      li.appendChild(el('span', 'z', tokensSaid(it.tokens)));
      if (it.how === 'outline') li.appendChild(el('span', 'o', 'outline'));
      ul.appendChild(li);
    });
    sec2.appendChild(ul);
    if (read.length > 4) {
      var more2 = el('button', 'reading-more', READ.more ? 'Show fewer' : 'Show all ' + read.length);
      more2.type = 'button';
      more2.dataset.more = '1';
      sec2.appendChild(more2);
    }
    cpop.appendChild(sec2);
  }
}

/** Under the strip on a desk; a sheet from the bottom on a phone. */
function contentPlace() {
  if (!cpop || cpop.hidden || !strip) return;
  var sheet = window.innerWidth < 600;
  cpop.classList.toggle('sheet', sheet);
  if (cback) cback.hidden = !sheet;
  if (sheet) { cpop.style.left = cpop.style.top = cpop.style.width = cpop.style.maxHeight = ''; return; }
  var r = strip.getBoundingClientRect();
  var w = Math.min(460, Math.max(300, r.width - 16));
  cpop.style.left = Math.round(Math.min(r.left + 8, window.innerWidth - w - 8)) + 'px';
  cpop.style.top = Math.round(r.bottom + 2) + 'px';
  cpop.style.width = w + 'px';
  // Down to the composer and no further: the box stays in sight under it.
  var box = $('composerBox');
  var floor = box ? box.getBoundingClientRect().top - 8 : window.innerHeight - 24;
  cpop.style.maxHeight = Math.max(200, Math.round(floor - r.bottom - 2)) + 'px';
}

/** Open or close the strip's panel. @param {boolean} on */
function openContent(on) {
  if (!cpop || !strip) return;
  if (on && pop && !pop.hidden) openPop(false);
  if (on) composerPopsClose();
  var was = !cpop.hidden;
  cpop.hidden = !on;
  strip.setAttribute('aria-expanded', on ? 'true' : 'false');
  document.body.classList.toggle('content-open', on);
  if (!on) {
    if (cback) cback.hidden = true;
    if (was && cpop.contains(document.activeElement)) strip.focus();
    return;
  }
  if (READ.data) contentPaint(READ.data);
  contentPlace();
  var head = $('contentHead');
  if (head) head.focus();
  // Drawn at once from what was last fetched; the sizes are asked again behind it, because what was said
  // since the chat was opened changes them (the chat itself, from 0 Tokens at its first message).
  if (READ.chat && !READ.busy && !READ.pending) load(READ.chat);
}

/** The panel. @param {ReadView} d */
function paintPop(d) {
  if (!pop) return;
  tipHide();
  var s = d.settings;
  var custom = s.mode === 'custom';
  pop.textContent = '';
  pop.classList.toggle('custom', custom);
  // The title bar: just the name of the panel (a second line under it read as one more option), and
  // Reset to defaults at its right (Petar, 16 November 2026).
  var bar = el('div', 'reading-top');
  var h = el('h2', '', 'Chat Options');
  h.id = 'readingHead';
  h.tabIndex = -1;
  bar.appendChild(h);
  var reset = el('button', 'reading-reset', 'Reset to defaults');
  reset.type = 'button';
  reset.dataset.reset = '1';
  reset.title = d.incognito ? 'Back to Simple chat, nothing left out' : 'Back to Full, nothing left out';
  bar.appendChild(reset);
  pop.appendChild(bar);

  // Two columns whenever there is the room (a desk): the modes on the left, Custom's choices on the right.
  // Simple and Full keep the same columns with the right one empty, so nothing moves when the mode does
  // (Petar, 18 November 2026: "keep their column the same size as custom. just the right side will be empty").
  var body = el('div', 'reading-body cols');
  var main = el('div', 'reading-main');
  var side = el('div', 'reading-side');
  body.appendChild(main);
  body.appendChild(side);
  pop.appendChild(body);

  // The mode first, in every chat: it is the one choice most people make here.
  var mode = sec('How this chat works');
  mode.appendChild(modes(s.mode, 'readingModes'));
  mode.appendChild(el('p', 'reading-safety', SAFETY));
  main.appendChild(mode);

  // Incognito is a button of its own (`incogBtn`); here, while it is on, what it means and a way out.
  if (d.incognito) {
    var top = sec('');
    top.appendChild(row('incognito', true, 'Incognito', 'On: nothing here is kept, and the chat is deleted when you leave it', 'incog'));
    if (d.kept) top.appendChild(el('p', 'reading-verdict', d.kept));
    main.appendChild(top);
  }

  // What the last message really came to, from the provider's own count: rules, tools, memory, the history
  // and the message together (`reading.last_turn`). Under the modes, in every mode.
  if (d.last && d.last.tokens) {
    var last = el('p', 'reading-last', 'Last message: ' + kTokens(d.last.tokens) + ' tokens in'
      + (d.last.cached ? ' · ' + kTokens(d.last.cached) + ' from the cache' : ''));
    last.title = d.last.tokens.toLocaleString() + ' tokens went to the model with the first request of the last turn'
      + (d.last.requests > 1 ? ', which took ' + d.last.requests + ' requests' : '') + '.';
    main.appendChild(last);
  }
  if (READ.oops) {
    var oops = el('p', 'reading-oops', READ.oops);
    oops.setAttribute('role', 'status');
    main.appendChild(oops);
  }

  // The switches one by one, and everything this chat is told, on Custom only: Simple and Full set them all
  // (Petar, 18 November 2026: "see everything this chat is told should only appear in the right column of
  // customized").
  if (!custom) return;
  var every = sec('What this chat uses');
  switches(every, s, d);
  side.appendChild(every);
  // Everything this chat is told is a link to the full list, never a list of its own here.
  var foot = sec('');
  var n = toldCount(d);
  var link = el('button', 'reading-link');
  link.type = 'button';
  link.dataset.full = '1';
  var words = el('span', '', 'See everything this chat is told ');
  // The count is the server's: while a press is being saved it is the old one, faded, never a guess.
  var count = el('span', 'reading-count' + (READ.pending ? ' pending' : ''), '(' + n.told + ' of ' + n.all + ')');
  if (READ.pending) count.setAttribute('aria-busy', 'true');
  words.appendChild(count);
  link.appendChild(words);
  link.appendChild(icon('M9 6l6 6-6 6', 14));
  foot.appendChild(link);
  side.appendChild(foot);
}

/** The mode selector: three radio rows drawn like the model's (`.model-opt`, app/composer_extras.js).
    @param {string} now @param {string} id */
function modes(now, id) {
  var g = el('div', 'model-opts reading-modes');
  g.setAttribute('role', 'radiogroup');
  g.setAttribute('aria-label', 'How this chat works');
  g.id = id;
  MODES.forEach(function (m) {
    var b = el('button', 'model-opt');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', m[0] === now ? 'true' : 'false');
    b.tabIndex = m[0] === now ? 0 : -1;
    b.dataset.mode = m[0];
    b.appendChild(el('span', 'model-opt-mark'));
    b.appendChild(el('span', 'model-opt-name', m[1]));
    b.appendChild(el('span', 'model-opt-hint', m[2]));
    g.appendChild(b);
  });
  return g;
}

/** The four switches, the same in the panel and the full list. Permission, privacy and safety is not one of
    them: what cannot be turned off is said in a sentence, never drawn as a switch (Petar, 16 November 2026).
    Tools are two since 18 November 2026 (rouh/toolsides.py): each with a line naming a few of its tools and
    a (?) that lists them all (`toolsRow`).
    @param {HTMLElement} into @param {Record<string, any>} s @param {ReadView} d */
function switches(into, s, d) {
  into.appendChild(row('memory', !!s.memory, 'Memory', 'What Rouh has learned about you and your people'));
  into.appendChild(row('rules', !!s.rules, 'Your rules', 'Off keeps the rules about permission, privacy and safety'));
  into.appendChild(toolsRow('rouh', !!s.rouh_tools, d));
  into.appendChild(toolsRow('llm', !!s.llm_tools, d));
}

/** The tools each side's line names first, when this Rouh has them; the rest are in its (?). */
var FIRST_TOOLS = /** @type {Record<string, string[]>} */ ({
  rouh: ['send_mail', 'list_calendar_events', 'search_drive', 'make_a_task', 'show_on_screen'],
  llm: ['web_search', 'web_fetch', 'code_execution', 'make_picture']
});
var SIDE_NAMES = /** @type {Record<string, string>} */ ({ rouh: 'Rouh Tools', llm: 'LLM Tools' });
var SIDE_SUBS = /** @type {Record<string, string>} */ ({
  rouh: 'Rouh’s own: mail, calendar, Drive, tasks, the screen and the rest',
  llm: 'The model’s own: the web, code and pictures'
});

/** One side of tools: its switch, and under it a line of a few of its tools and a (?) for all of them.
    @param {string} side @param {boolean} on @param {ReadView} d */
function toolsRow(side, on, d) {
  var box = el('div', 'reading-tools');
  box.appendChild(row(side + '_tools', on, SIDE_NAMES[side], SIDE_SUBS[side]));
  var all = (d.tools && d.tools[side]) || [];
  if (!all.length) return box;
  var names = all.map(function (t) { return t.name; });
  var first = FIRST_TOOLS[side].filter(function (n) { return names.indexOf(n) >= 0; });
  names.forEach(function (n) { if (first.length < 3 && first.indexOf(n) < 0) first.push(n); });
  first = first.slice(0, 3);
  var line = el('p', 'reading-tools-line');
  line.appendChild(el('span', 'reading-tools-names', first.join(', ') + (all.length > first.length ? ', …' : '')));
  var q = el('button', 'reading-tools-q', '?');
  q.type = 'button';
  q.dataset.tools = side;
  q.setAttribute('aria-label', 'All ' + all.length + ' ' + SIDE_NAMES[side]);
  q.setAttribute('aria-expanded', 'false');
  q.setAttribute('aria-controls', 'toolsTip');
  line.appendChild(q);
  box.appendChild(line);
  return box;
}

/** The (?)'s list: every tool of one side with a few words each, over the page, beside the (?) pressed or
    hovered. Hover shows it on a desk; a press (a tap on a phone) keeps it open until Escape, a press
    elsewhere or the (?) again. */
var TIP = { el: /** @type {HTMLElement | null} */ (null), side: '', pinned: false, from: /** @type {HTMLElement | null} */ (null),
            hide: 0 };

/** @param {HTMLElement} q @param {boolean} pin */
function tipShow(q, pin) {
  var side = q.dataset.tools || '';
  var all = (READ.data && READ.data.tools && READ.data.tools[side]) || [];
  if (!all.length) return;
  clearTimeout(TIP.hide);
  if (!TIP.el) {
    TIP.el = el('div', 'tools-tip');
    TIP.el.id = 'toolsTip';
    TIP.el.setAttribute('role', 'tooltip');
    TIP.el.addEventListener('mouseenter', function () { clearTimeout(TIP.hide); });
    TIP.el.addEventListener('mouseleave', function () { if (!TIP.pinned) tipLater(); });
    document.body.appendChild(TIP.el);
  }
  var t = TIP.el;
  if (TIP.side !== side || t.hidden || !t.firstChild) {
    t.textContent = '';
    t.appendChild(el('p', 'tools-tip-h', SIDE_NAMES[side] + ' · ' + all.length));
    var ul = el('ul', '');
    all.forEach(function (x) {
      var li = el('li', '');
      li.appendChild(el('code', '', x.name));
      li.appendChild(document.createTextNode(' - ' + x.words));
      ul.appendChild(li);
    });
    t.appendChild(ul);
    t.scrollTop = 0;
  }
  if (TIP.from && TIP.from !== q) TIP.from.setAttribute('aria-expanded', 'false');
  TIP.side = side;
  TIP.from = q;
  TIP.pinned = pin || TIP.pinned;
  q.setAttribute('aria-expanded', 'true');
  t.hidden = false;
  // Never over the switches it is about. On a desk, to the left of their column, beside the (?) (a list
  // above it covered Memory and Your rules, and took the press meant for them); on a phone, where there is
  // one column, under the (?) or above it, and a tap anywhere else closes it.
  var r = q.getBoundingClientRect();
  var w = Math.min(320, window.innerWidth - 32);
  t.style.width = w + 'px';
  var col = /** @type {HTMLElement | null} */ (q.closest('.reading-side, .cot-switches'));
  var c = col ? col.getBoundingClientRect() : r;
  if (c.left - w - 12 >= 8) {
    var h0 = Math.min(360, window.innerHeight - 32);
    t.style.maxHeight = h0 + 'px';
    var hh = Math.min(h0, t.scrollHeight);
    t.style.left = (c.left - w - 12) + 'px';
    t.style.top = Math.max(16, Math.min(window.innerHeight - hh - 16, r.top + r.height / 2 - hh / 2)) + 'px';
    t.style.bottom = '';
    return;
  }
  t.style.left = Math.max(16, Math.min(window.innerWidth - w - 16, r.left + r.width / 2 - w / 2)) + 'px';
  var below = window.innerHeight - r.bottom - 16, above = r.top - 16;
  var h = Math.min(320, Math.max(below, above) - 8);
  t.style.maxHeight = Math.max(120, h) + 'px';
  if (below >= Math.min(320, t.scrollHeight) || below >= above) { t.style.top = (r.bottom + 6) + 'px'; t.style.bottom = ''; }
  else { t.style.top = ''; t.style.bottom = (window.innerHeight - r.top + 6) + 'px'; }
}

function tipHide() {
  clearTimeout(TIP.hide);
  if (TIP.el) TIP.el.hidden = true;
  if (TIP.from) TIP.from.setAttribute('aria-expanded', 'false');
  TIP.pinned = false;
}

/** Hidden a moment after the pointer leaves, so it can move from the (?) onto the list to scroll it. */
function tipLater() {
  clearTimeout(TIP.hide);
  TIP.hide = window.setTimeout(tipHide, 250);
}

[pop, full].forEach(function (box) {
  if (!box) return;
  box.addEventListener('mouseover', function (e) {
    var q = /** @type {HTMLElement} */ (e.target).closest && /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('.reading-tools-q'));
    if (q && !TIP.pinned) tipShow(q, false);
  });
  box.addEventListener('mouseout', function (e) {
    var q = /** @type {HTMLElement} */ (e.target).closest && /** @type {HTMLElement} */ (e.target).closest('.reading-tools-q');
    if (q && !TIP.pinned) tipLater();
  });
  box.addEventListener('focusin', function (e) {
    var q = /** @type {HTMLElement} */ (e.target);
    if (q.classList && q.classList.contains('reading-tools-q') && !TIP.pinned) tipShow(q, false);
  });
  box.addEventListener('focusout', function (e) {
    var q = /** @type {HTMLElement} */ (e.target);
    if (q.classList && q.classList.contains('reading-tools-q') && !TIP.pinned) tipLater();
  });
  box.addEventListener('scroll', function () { if (TIP.el && !TIP.el.hidden) tipHide(); }, true);
});
document.addEventListener('pointerdown', function (e) {
  if (!TIP.el || TIP.el.hidden) return;
  var t = /** @type {HTMLElement} */ (e.target);
  if (TIP.el.contains(t) || (t.closest && t.closest('.reading-tools-q'))) return;
  tipHide();
}, true);
window.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || !TIP.el || TIP.el.hidden) return;
  e.preventDefault();
  e.stopPropagation();
  var back = TIP.from;
  tipHide();
  if (back) back.focus();
}, true);

/** The full list, from the server's words. @param {ReadView} d */
function fullPaint(d) {
  var inner = $('toldIn'), foot = $('toldFoot');
  if (!full || !inner || !foot) return;
  tipHide();
  var s = d.settings, names = d.sources || {}, every = allItems(d), n = toldCount(d);
  var keepFocus = document.activeElement && document.activeElement.id === 'toldQ';
  inner.textContent = '';
  var head = el('p', 'cot-verdict' + (READ.pending ? ' pending' : ''), n.told + ' of ' + n.all + ' items reach this chat with these choices.');
  full.classList.toggle('pending', READ.pending);
  head.appendChild(el('small', '', (s.memory ? 'Memory is on, so all of Synapse is read for each message too. '
    : 'Memory is off: Synapse is not read, and your name is taken out of what is told. ')
    + 'An item marked “only when” is told only in the turns it names.'));
  inner.appendChild(head);
  inner.appendChild(modes(s.mode, 'toldModes'));
  if (s.mode === 'custom') {
    var sw = el('div', 'cot-switches');
    switches(sw, s, d);
    inner.appendChild(sw);
  }
  inner.appendChild(el('p', 'reading-safety', SAFETY));
  var syn = el('p', 'cot-synapse' + (s.memory ? '' : ' off'));
  syn.appendChild(el('b', '', 'Synapse: ' + (s.memory ? 'included. ' : 'not included. ')));
  syn.appendChild(document.createTextNode((d.synapse && d.synapse.text || 'All of Synapse, Rouh’s memory.')
    + ' It follows Memory, and is too big to list here.'));
  inner.appendChild(syn);

  var bar = el('div', 'cot-bar');
  var filters = el('div', 'cot-filters');
  filters.setAttribute('role', 'group');
  filters.setAttribute('aria-label', 'Show the items of');
  ['all', 'memory', 'rules', 'tools', 'safety', 'builtin', 'chat'].forEach(function (k) {
    var of = k === 'all' ? every : every.filter(function (r) { return r.source === k; });
    if (!of.length && k !== 'all') return;
    var on = of.filter(function (r) { return r.on; }).length;
    // How many of them reach the chat, when not all of them do.
    var b = el('button', '', (k === 'all' ? 'All' : names[k] || k) + ' ' + (on < of.length ? on + ' of ' + of.length : of.length));
    b.type = 'button';
    b.dataset.filter = k;
    b.setAttribute('aria-pressed', FULL.filter === k ? 'true' : 'false');
    filters.appendChild(b);
  });
  bar.appendChild(filters);
  var search = el('input', 'cot-q');
  var q = /** @type {HTMLInputElement} */ (search);
  q.type = 'search';
  q.id = 'toldQ';
  q.placeholder = 'Search the words';
  q.setAttribute('aria-label', 'Search the words of every item');
  q.value = FULL.q;
  bar.appendChild(q);
  inner.appendChild(bar);
  // On a phone the chips scroll on their own: the one chosen is kept in sight.
  var cur = /** @type {HTMLElement | null} */ (filters.querySelector('[aria-pressed="true"]'));
  if (cur && filters.scrollWidth > filters.clientWidth) {
    var fr = filters.getBoundingClientRect(), cr = cur.getBoundingClientRect();
    if (cr.right > fr.right - 24 || cr.left < fr.left) filters.scrollLeft += cr.left - fr.left - 16;
  }

  var words = FULL.q.trim().toLowerCase();
  var shown = every.filter(function (r) {
    return (FULL.filter === 'all' || r.source === FULL.filter)
      && (!words || (r.title + ' ' + r.text + ' ' + (r.with || '')).toLowerCase().indexOf(words) >= 0);
  });
  if (!shown.length) {
    var none = el('div', 'cot-none');
    none.appendChild(el('p', '', words ? 'Nothing matches “' + FULL.q.trim() + '”.' : 'Nothing here.'));
    var clear = el('button', 'cot-btn', 'Show everything');
    clear.type = 'button';
    clear.dataset.clear = '1';
    none.appendChild(clear);
    inner.appendChild(none);
  }
  var ul = el('ul', 'cot-items');
  shown.forEach(function (r) {
    var li = el('li', 'cot-item' + (r.on ? '' : ' out'));
    var top = el('div', 'cot-item-h');
    top.appendChild(el('b', '', r.title));
    if (r.locked) {
      var lk = el('span', 'reading-lock');
      lk.appendChild(icon(LOCK, 12));
      lk.appendChild(document.createTextNode(r.source === 'chat' ? 'set by what the chat is' : 'cannot be turned off'));
      top.appendChild(lk);
    } else {
      var b = el('button', 'cot-sw' + (!r.on && !r.off ? ' follows' : ''));
      b.type = 'button';
      b.setAttribute('role', 'switch');
      b.setAttribute('aria-checked', r.off ? 'false' : 'true');
      b.setAttribute('aria-label', (r.off ? 'Put back: ' : 'Leave out: ') + r.title);
      b.dataset.item = r.id;
      b.appendChild(el('span', 'reading-sw'));
      top.appendChild(b);
    }
    li.appendChild(top);
    var tags = el('div', 'cot-tags');
    tags.appendChild(el('span', 'cot-tag', (names[r.source] || r.source) + (r.with ? ' · with ' + r.with : '')));
    if (r.when) tags.appendChild(el('span', 'cot-tag', r.when));
    if (r.live) tags.appendChild(el('span', 'cot-tag', 'live: what it says now'));
    if (r.fills) tags.appendChild(el('span', 'cot-tag', 'the {…} are filled in as it is told: ' + r.fills));
    li.appendChild(tags);
    if (!r.on) {
      var why = r.off ? 'Left out: you turned it off here.'
        : 'Left out: ' + (r.with && !s.rouh_tools && !s.llm_tools ? 'Rouh Tools and LLM Tools are' : (names[r.source] || r.source) + ' is') + ' off.';
      li.appendChild(el('p', 'cot-why', why));
    }
    // Lines the source wrapped by hand run on; blank lines and list items stay where they are.
    li.appendChild(el('p', 'cot-text', r.text.replace(/\n {2,}(?=\S)/g, ' ').replace(/([^\n])\n(?![\n\-*•]|\d+[.)] )/g, '$1 ')));
    ul.appendChild(li);
  });
  inner.appendChild(ul);

  foot.textContent = '';
  // Reset to defaults is in the title bar, beside Close (`toldReset`).
  var top = $('toldReset');
  if (top) top.title = d.incognito ? 'Back to Simple chat, nothing left out'
    : 'Back to Full, nothing left out';
  var done = el('button', 'cot-btn done', 'Done');
  done.type = 'button';
  done.dataset.done = '1';
  foot.appendChild(done);
  if (keepFocus) {
    var again = /** @type {HTMLInputElement | null} */ ($('toldQ'));
    if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
  }
}

/** Open or close the full list. @param {boolean} on */
function fullOpen(on) {
  if (!full) return;
  if (on) {
    FULL.opener = /** @type {HTMLElement | null} */ (document.activeElement);
    full.hidden = false;
    document.body.classList.add('cot-open');
    if (READ.data) fullPaint(READ.data);
    var h = $('toldHead');
    if (h) h.focus();
  } else {
    full.hidden = true;
    document.body.classList.remove('cot-open');
    var back = FULL.opener && document.contains(FULL.opener) ? FULL.opener : btn;
    if (back) back.focus();
  }
}

/** A selector that finds this control again once its panel is drawn anew, or "". @param {Element | null} t */
function selectorOf(t) {
  var b = /** @type {HTMLElement | null} */ (t);
  if (!b || !b.dataset) return '';
  var d = b.dataset;
  if (b.id) return '#' + b.id;
  return d.key ? '[data-key="' + d.key + '"]' : d.seg ? '[data-seg="' + d.seg + '"]' : d.mode ? '[data-mode="' + d.mode + '"]'
    : d.item ? '[data-item="' + d.item + '"]' : d.filter ? '[data-filter="' + d.filter + '"]' : d.more ? '[data-more]'
    : d.reset ? '[data-reset]' : d.full ? '[data-full]' : d.cseg ? '[data-cseg="' + d.cseg + '"]'
    : d.tools ? '[data-tools="' + d.tools + '"]' : '';
}

/** @param {ReadView | null} d */
function paint(d) {
  READ.data = d;
  // What has the focus in the panel or the full list keeps it, however often they are drawn again.
  var at = document.activeElement;
  var inPop = !!(pop && at && pop.contains(at)), inFull = !!(full && at && full.contains(at));
  var inContent = !!(cpop && at && cpop.contains(at));
  var keep = READ.focus || ((inPop || inFull || inContent) ? selectorOf(at) : '');
  paintStrip(d);
  if (d && full && !full.hidden) {
    var scrolled = full.querySelector('.cot-body');
    var y = scrolled ? scrolled.scrollTop : 0;
    fullPaint(d);
    if (scrolled) scrolled.scrollTop = y;
    if (inFull && keep) refocus('#toldFull ' + keep);
  }
  if (d && pop && !pop.hidden) {
    var moved = READ.painted !== d.chat;
    var top = pop.scrollTop;
    paintPop(d);
    place();
    // Another chat in the same open panel starts at its top: what it is, before its rules.
    pop.scrollTop = moved ? 0 : top;
    READ.painted = d.chat;
    var again = keep && (inPop || READ.focus) ? /** @type {HTMLElement | null} */ (pop.querySelector(keep)) : null;
    if (again) again.focus();
  }
  if (d && cpop && !cpop.hidden) {
    var ctop = cpop.scrollTop;
    contentPaint(d);
    contentPlace();
    cpop.scrollTop = READ.painted === d.chat ? ctop : 0;
    var back = keep && inContent ? /** @type {HTMLElement | null} */ (cpop.querySelector(keep)) : null;
    if (back) back.focus();
  }
  READ.focus = '';
}

/** Over the box, sized to the room there is: the box moves (the welcome holds it in the middle of an
    empty chat, a phone's keyboard comes up), so this is done every time the panel is drawn. */
function place() {
  if (!pop || pop.hidden) return;
  // Over the box itself, whatever the composer around it is: the welcome holds the box in the
  // middle of a wide column.
  var box = $('composerBox'), comp = $('composer');
  if (box && comp) {
    var b = box.getBoundingClientRect(), c = comp.getBoundingClientRect();
    pop.style.left = Math.max(0, Math.round(b.left - c.left)) + 'px';
    pop.style.right = Math.max(0, Math.round(c.right - b.right)) + 'px';
    // Above the box when there is room there, as on a conversation; below it when the box is high
    // up, as on an empty chat on a phone, where the panel would otherwise run off the top.
    var above = Math.round(b.top - 16), below = Math.round(window.innerHeight - b.bottom - 16);
    var up = above >= 280 || above >= below;
    pop.style.top = up ? '' : 'calc(100% + 8px)';
    pop.style.bottom = up ? '' : 'auto';
    pop.style.maxHeight = Math.max(160, Math.min(580, up ? above : below)) + 'px';
  }
}

/** @param {boolean} on */
function openPop(on) {
  if (!btn || !pop) return;
  if (on) composerPopsClose();
  pop.hidden = !on;
  if (!on) tipHide();
  btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (strip) strip.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (on) place();
  // Only this chat's own choices are drawn: another chat's, still held while this one's are fetched, would
  // show the wrong mode and switches (a fork just opened showed its parent's, 18 November 2026).
  var mine = !!(READ.data && READ.data.chat === currentChat());
  if (on && !mine) {
    pop.textContent = '';
    pop.appendChild(el('p', 'reading-verdict', 'Finding what this chat reads…'));
    if (currentChat() && READ.chat !== currentChat()) load(currentChat());
  }
  if (on && mine && READ.data) {
    paintPop(READ.data);
    var head = $('readingHead');
    if (head) head.focus();
  }
}

/** @param {string} chat */
function load(chat) {
  READ.chat = chat;
  if (!chat) { paint(null); return; }
  var asked = ++READ.asked;
  fetch('/api/reading?chat=' + encodeURIComponent(chat), { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (asked !== READ.asked || READ.chat !== chat) return;
      READ.confirmed = d;
      READ.pending = false;
      READ.oops = '';
      paint(d);
      // Just turned incognito: the panel shows the rules that will apply in it.
      if (READ.openAfter && d && d.incognito) { READ.openAfter = false; openPop(true); }
    })
    .catch(function () { /* the next look asks again */ READ.chat = ''; });
}

/** The changes pressed while another was on its way, in order, each with the chat it was pressed in: sent
    one by one as each is answered, never dropped, even once the page has moved to another chat (a fork made
    the moment after a press, 18 November 2026). Switches pressed one after another in a chat go as one change.
    @type {{chat: string, wanted: Record<string, any>}[]} */
var NEXT = [];

/** The switches a mode sets (rouh/reading.py `SIMPLE` and `FULL`); Custom sets none. */
var MODE_SETS = /** @type {Record<string, Record<string, any>>} */ ({
  simple: { memory: false, rules: false, rouh_tools: false, llm_tools: true, off: [] },
  full: { memory: true, rules: true, rouh_tools: true, llm_tools: true, off: [] }
});
/** What the chat is about (rouh/reading.py `CONTENT_KEYS`): set in the strip's panel, never by a mode. */
var CONTENT_KEYS = ['task', 'others', 'subtasks', 'picked', 'steps_what', 'step_histories', 'parent_task',
                    'parent_task_history', 'fork_history', 'parents'];

/** What the panel will say once this change is saved, as far as it can be told without the server: the
    settings, the mode, and each subtask's switch. Counts are left as they were (`READ.pending`).
    @param {ReadView} d @param {Record<string, any>} wanted @returns {ReadView} */
function guess(d, wanted) {
  var s = Object.assign({}, d.settings);
  if (wanted.reset) {
    Object.assign(s, MODE_SETS[d.incognito ? 'simple' : 'full'], { mode: d.incognito ? 'simple' : 'full' });
  } else if (wanted.mode) {
    s.mode = wanted.mode;
    if (MODE_SETS[wanted.mode]) Object.assign(s, MODE_SETS[wanted.mode]);
  } else {
    Object.keys(wanted).forEach(function (k) {
      s[k] = k === 'parents' ? Object.assign({}, s.parents || {}, wanted[k]) : wanted[k];
    });
    if (Object.keys(wanted).some(function (k) { return CONTENT_KEYS.indexOf(k) < 0; })) s.mode = 'custom';
  }
  var g = /** @type {ReadView} */ (Object.assign({}, d, { settings: s, mode: s.mode }));
  if (d.content) {
    g.content = d.content.map(function (c) {
      var on = c.key === 'steps' ? s.subtasks !== 'none' : !!s[c.key];
      return on === c.on ? c : Object.assign({}, c, { on: on });
    });
  }
  if (d.tree && wanted.parents) {
    g.tree = d.tree.map(function (c) {
      return c.self || !(c.id in wanted.parents) ? c : Object.assign({}, c, { on: !!wanted.parents[c.id] });
    });
  }
  if (d.subtasks) {
    var picked = s.picked || [];
    g.subtasks = d.subtasks.map(function (x) {
      return Object.assign({}, x, { on: s.subtasks === 'all' || (s.subtasks === 'some' && picked.indexOf(x.id) >= 0) });
    });
  }
  // An item left out by itself in the full list moves its own switch at once.
  if (wanted.off || wanted.reset || MODE_SETS[wanted.mode || '']) {
    var off = s.off || [];
    /** @param {ReadRule} r */
    var flip = function (r) { return r.locked ? r : Object.assign({}, r, { off: off.indexOf(r.id) >= 0 }); };
    g.rules = (d.rules || []).map(flip);
    g.context = (d.context || []).map(flip);
  }
  return g;
}

/** @param {Record<string, any>} wanted */
function change(wanted) {
  var chat = READ.chat || currentChat();
  if (!chat) return;
  // Drawn now, in the same task as the press; the server's answer is drawn when it comes.
  if (READ.data && READ.data.chat === chat) {
    READ.pending = true;
    READ.oops = '';
    paint(guess(READ.data, wanted));
  }
  send(chat, wanted);
}

/** The save, in the background: one at a time, and a press made meanwhile sent as soon as it is answered.
    @param {string} chat @param {Record<string, any>} wanted */
function send(chat, wanted) {
  if (READ.busy) {
    // Kept, with later switches merged into it; a mode or a reset pressed after replaces what was kept of
    // the same chat.
    var held = NEXT.length && NEXT[NEXT.length - 1].chat === chat ? NEXT[NEXT.length - 1].wanted : null;
    if (wanted.mode || wanted.reset) {
      NEXT = NEXT.filter(function (x) { return x.chat !== chat; });   // what came before it no longer matters
      NEXT.push({ chat: chat, wanted: Object.assign({}, wanted) });
    } else if (held && !held.mode && !held.reset) {
      // Parent chats pressed one after another are all kept: each is its own choice.
      var parents = held.parents && wanted.parents ? Object.assign({}, held.parents, wanted.parents) : null;
      Object.assign(held, wanted);
      if (parents) held.parents = parents;
    }
    else NEXT.push({ chat: chat, wanted: Object.assign({}, wanted) });
    return;
  }
  READ.busy = true;
  // Whatever an earlier read answers after this, the answer to this change is what is drawn: in this chat
  // only, so a press still being saved for a chat the page has left never drops the read of the one it is in.
  if (READ.chat === chat) READ.asked++;
  fetch('/api/reading', { method: 'POST', credentials: 'same-origin',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ chat: chat, change: wanted }) })
    .then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d && d.error ? d.error : 'That could not be changed.');
        return d;
      });
    })
    .then(function (d) {
      READ.busy = false;
      var next = NEXT.shift();
      // The next press goes whichever chat the page is in now: it is saved to the chat it was made in.
      if (next) {
        if (READ.chat === chat) READ.confirmed = d;
        send(next.chat, next.wanted);
        return;
      }
      if (READ.chat !== chat) return;
      READ.confirmed = d;
      // Nothing more on its way: what the server says is drawn, counts and all.
      READ.pending = false;
      paint(d);
      if (READ.after) { refocus(READ.after); READ.after = ''; }
    })
    .catch(function (err) {
      READ.busy = false;
      // What was pressed after it in this chat goes with it; another chat's presses are still sent.
      NEXT = NEXT.filter(function (x) { return x.chat !== chat; });
      var other = NEXT.shift();
      if (other) send(other.chat, other.wanted);
      READ.pending = false;
      if (READ.chat !== chat) return;
      // Back to what the server last said, with a quiet line where the press was.
      var why = String(err && err.message || '');
      READ.oops = 'Not saved, so it is back as it was' + (why && why !== 'Failed to fetch' ? ': ' + why : '. Rouh is not connected.');
      if (why && why.slice(-1) !== '.' && READ.oops.slice(-1) !== '.') READ.oops += '.';
      paint(READ.confirmed);
      if (!(pop && !pop.hidden) && !(full && !full.hidden)) notify(READ.oops, { tone: 'error' });
    });
}

/** Incognito on: a new incognito chat is opened (rouh/incognito.py); off: back out of it. Set by
    app/incognito.js when it is loaded. @type {((on: boolean) => void) | null} */
var incognitoTo = null;

/** @param {(on: boolean) => void} fn */
function onIncognito(fn) { incognitoTo = fn; }

/* Incognito on opens a new incognito chat and keeps the panel open on it, so the rules that will apply
   are in front of the person; off goes back to the main chat, and leaving the incognito chat ends it
   (rouh/incognito.py). */
onIncognito(function (on) {
  if (full && !full.hidden) fullOpen(false);
  if (!on) { leaveIncognito(); return; }
  // Where the person was, to go back to when they close it.
  if (!(READ.data && READ.data.incognito)) READ.from = currentChat();
  // The look changes at once; the chat follows a moment later.
  document.body.classList.add('chat-incognito');
  fetch('/api/incognito', { method: 'POST', credentials: 'same-origin',
                            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ start: true }) })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('refused')); })
    .then(function (d) { if (d && d.chat) { READ.chat = ''; READ.openAfter = true; openChat(d.chat); } })
    .catch(function () {
      document.body.classList.remove('chat-incognito');
      notify('An incognito chat could not be started. Try again in a moment.', { tone: 'error' });
    });
});

/** Out of the incognito chat, back to the chat the person was in before it, else General. Opening another
    chat ends the incognito one, which deletes it (rouh/runtime.py `incognito_left`). */
function leaveIncognito() {
  if (incogAsk) incogAsk.hidden = true;
  if (pop && !pop.hidden) openPop(false);
  var back = READ.from && READ.from !== currentChat() ? READ.from : String(CHATS.general || '');
  READ.from = '';
  openChat(back);
}

/** The X at the top right of an incognito chat: at once when nothing was said in it, else after one line. */
function closeIncognito() {
  var said = !!document.querySelector('#transcript .turn');
  if (!said || !incogAsk) { leaveIncognito(); return; }
  incogAsk.hidden = false;
  var keep = $('incogAskGo');
  if (keep) keep.focus();
}
if (incogClose) incogClose.addEventListener('click', function (e) {
  e.stopPropagation();
  if (incogAsk && !incogAsk.hidden) { incogAsk.hidden = true; return; }
  closeIncognito();
});
if (incogAsk) {
  incogAsk.addEventListener('click', function (e) {
    var t = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!t) return;
    if (t.id === 'incogAskGo') leaveIncognito();
    else if (t.id === 'incogAskKeep') { incogAsk.hidden = true; if (incogClose) incogClose.focus(); }
  });
  document.addEventListener('pointerdown', function (e) {
    if (!incogAsk || incogAsk.hidden) return;
    var t = /** @type {Node} */ (e.target);
    if (incogAsk.contains(t) || (incogClose && incogClose.contains(t))) return;
    incogAsk.hidden = true;
  }, true);
  window.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !incogAsk || incogAsk.hidden) return;
    e.preventDefault();
    e.stopPropagation();
    incogAsk.hidden = true;
    if (incogClose) incogClose.focus();
  }, true);
}

/** Arrow keys move between the three modes, as a group of radio buttons does. @param {KeyboardEvent} e */
function modeKeys(e) {
  if (['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].indexOf(e.key) < 0) return;
  var at = /** @type {HTMLElement | null} */ (document.activeElement);
  var group = at && at.closest('.reading-modes');
  if (!group || !at) return;
  var all = Array.prototype.slice.call(group.querySelectorAll('.model-opt'));
  var i = all.indexOf(at);
  if (i < 0) return;
  e.preventDefault();
  all[(i + (e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length].focus();
}

/** A switch pressed in the panel or the full list: what it changes on the server.
    @param {HTMLElement} t */
function pressed(t) {
  if (!READ.data) return;
  if (t.dataset.tools) {
    // The (?) of a side of tools: a press keeps its list open (a tap on a phone), a second press closes it.
    if (TIP.pinned && TIP.from === t && TIP.el && !TIP.el.hidden) tipHide();
    else { TIP.pinned = false; tipShow(t, true); }
    return;
  }
  if (t.dataset.reset) { change({ reset: true }); return; }
  if (t.dataset.seg) { change({ subtasks: t.dataset.seg }); return; }
  if (t.dataset.cseg) {
    var cs = t.dataset.cseg.split(':');
    if (t.getAttribute('aria-pressed') === 'true') return;
    var c0 = /** @type {Record<string, any>} */ ({});
    c0[cs[0]] = cs[1];
    // Chosen starts with the steps that are read now: none is dropped by the press itself.
    if (cs[0] === 'subtasks' && cs[1] === 'some') c0.picked = (READ.data.settings.picked || []).length
      ? READ.data.settings.picked : (READ.data.subtasks || []).map(function (x) { return x.id; });
    change(c0);
    return;
  }
  if (t.dataset.mode) {
    if (t.getAttribute('aria-checked') === 'true') return;
    change({ mode: t.dataset.mode });
    return;
  }
  var key = t.dataset.key;
  if (!key || t.getAttribute('aria-disabled') === 'true') return;
  var on = t.getAttribute('aria-checked') !== 'true';
  if (key === 'incognito') {
    if (incognitoTo) incognitoTo(on);
    else notify('Incognito is not ready on this page yet.', { tone: 'error' });
    return;
  }
  if (key.indexOf('c:') === 0) {
    var ck = key.slice(2);
    var cc = /** @type {Record<string, any>} */ ({});
    if (ck === 'steps') cc.subtasks = on ? 'all' : 'none';
    else cc[ck] = on;
    change(cc);
    return;
  }
  if (key.indexOf('par:') === 0) {
    var pc = /** @type {Record<string, boolean>} */ ({});
    pc[key.slice(4)] = on;
    change({ parents: pc });
    return;
  }
  if (key.indexOf('sub:') === 0) {
    var id = key.slice(4);
    var picked = (READ.data.subtasks || []).filter(function (x) { return x.on; }).map(function (x) { return x.id; });
    picked = on ? picked.concat([id]) : picked.filter(function (x) { return x !== id; });
    change({ subtasks: 'some', picked: picked });
    return;
  }
  var c = /** @type {Record<string, any>} */ ({});
  c[key] = on;
  change(c);
}

/** Put the focus back on what was pressed, once the list is drawn again. @param {string} sel */
function refocus(sel) {
  var again = sel ? /** @type {HTMLElement | null} */ (document.querySelector(sel)) : null;
  if (again) again.focus();
}

if (btn && pop) {
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    openPop(pop.hidden);
  });
  // The strip opens its own panel, what this chat is about; never Chat Options (Petar, 16 November 2026:
  // "I hate duplicate stuff").
  if (strip && cpop) {
    strip.addEventListener('click', function (e) {
      e.stopPropagation();
      if (strip && strip.disabled) return;
      openContent(cpop ? cpop.hidden : false);
    });
    cpop.addEventListener('click', function (e) {
      var t = /** @type {HTMLElement} */ (e.target).closest('button');
      if (!t || !READ.data) return;
      if (t.dataset.close) { openContent(false); return; }
      if (t.dataset.more) { READ.more = !READ.more; paint(READ.data); return; }
      // A parent chat's name goes to that chat, as the fork's mark above the chat does.
      if (t.dataset.open) { openContent(false); openChat(t.dataset.open); return; }
      pressed(t);
    });
    if (cback) cback.addEventListener('click', function () { openContent(false); });
  }
  pop.addEventListener('keydown', modeKeys);
  if (full) full.addEventListener('keydown', modeKeys);
  pop.addEventListener('click', function (e) {
    var t = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!t || !READ.data) return;
    READ.focus = t.dataset.key ? '[data-key="' + t.dataset.key + '"]' : t.dataset.seg ? '[data-seg="' + t.dataset.seg + '"]'
      : t.dataset.mode ? '[data-mode="' + t.dataset.mode + '"]' : t.dataset.more ? '[data-more]' : t.dataset.reset ? '[data-reset]' : '';
    if (t.dataset.more) { READ.more = !READ.more; paint(READ.data); return; }
    if (t.dataset.full) { fullOpen(true); return; }
    pressed(t);
  });
  if (full) {
    full.addEventListener('click', function (e) {
      var t = /** @type {HTMLElement} */ (e.target).closest('button');
      if (!t || !READ.data) return;
      if (t.id === 'toldClose' || t.dataset.done) { fullOpen(false); return; }
      if (t.dataset.filter) { FULL.filter = t.dataset.filter; fullPaint(READ.data); refocus('[data-filter="' + t.dataset.filter + '"]'); return; }
      if (t.dataset.clear) { FULL.q = ''; FULL.filter = 'all'; fullPaint(READ.data); refocus('#toldQ'); return; }
      if (t.dataset.item) {
        var id = t.dataset.item;
        var off = (READ.data.settings.off || []).filter(function (/** @type {string} */ x) { return x !== id; });
        if (t.getAttribute('aria-checked') === 'true') off.push(id);
        READ.after = '[data-item="' + id + '"]';
        change({ off: off });
        return;
      }
      READ.after = t.dataset.key ? '#toldFull [data-key="' + t.dataset.key + '"]' : t.dataset.reset ? '#toldReset'
        : t.dataset.mode ? '#toldFull [data-mode="' + t.dataset.mode + '"]' : '';
      pressed(t);
    });
    full.addEventListener('input', function (e) {
      var t = /** @type {HTMLInputElement} */ (e.target);
      if (t.id !== 'toldQ' || !READ.data) return;
      FULL.q = t.value;
      fullPaint(READ.data);
    });
    // Tab stays inside the full list while it is open.
    full.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab' || !full) return;
      var all = /** @type {HTMLElement[]} */ (Array.prototype.slice.call(full.querySelectorAll('button, input, [tabindex="-1"]#toldHead')))
        .filter(function (x) { return x.offsetParent !== null || x.id === 'toldHead'; });
      if (!all.length) return;
      var first = all[0], last = all[all.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }
  if (incogBtn) incogBtn.addEventListener('click', function () {
    var on = incogBtn.getAttribute('aria-pressed') !== 'true';
    if (incognitoTo) incognitoTo(on);
  });
  document.addEventListener('pointerdown', function (e) {
    var t = /** @type {Node} */ (e.target);
    if (cpop && !cpop.hidden && !cpop.contains(t) && !(strip && strip.contains(t)) && !(cback && cback.contains(t))) openContent(false);
    if (pop.hidden || (full && !full.hidden)) return;
    if (pop.contains(t) || btn.contains(t) || (incogBtn && incogBtn.contains(t))) return;
    openPop(false);
  }, true);
  window.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (full && !full.hidden) {
      e.preventDefault();
      e.stopPropagation();
      fullOpen(false);
      return;
    }
    if (cpop && !cpop.hidden) {
      e.preventDefault();
      e.stopPropagation();
      openContent(false);
      if (strip) strip.focus();
      return;
    }
    if (pop.hidden) return;
    e.preventDefault();
    e.stopPropagation();
    var inside = pop.contains(document.activeElement);
    openPop(false);
    if (inside && btn) btn.focus();
  }, true);
  // The chat on screen changes in many places; its id is looked at a few times a second, and the
  // server asked only when it changed, and again when the page comes back into view.
  setInterval(function () {
    var chat = currentChat();
    if (chat !== READ.chat) { READ.more = false; load(chat); }
    else if (READ.data && (ASK.doc || '') !== READ.doc) paintStrip(READ.data);
  }, 400);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) READ.chat = ''; });
  window.addEventListener('rouh:reading-again', function () { READ.chat = ''; });
  window.addEventListener('resize', place);
  window.addEventListener('resize', contentPlace);
}

/** This chat's Chat Options as the panel draws them, presses not yet saved included, for a fork of it to
    start with (`forks._with_options`, the `fork` message's `options`); null when they are not known here.
    @param {string} chat @returns {Record<string, any> | null} */
function forkOptions(chat) {
  var d = READ.data;
  if (!d || d.chat !== chat || !d.settings) return null;
  var s = d.settings;
  return { mode: s.mode, memory: !!s.memory, rules: !!s.rules, rouh_tools: !!s.rouh_tools,
           llm_tools: !!s.llm_tools, off: (s.off || []).slice() };
}

shared.forkOptions = forkOptions;

export { forkOptions, onIncognito, openPop as readingOpen, READ };
