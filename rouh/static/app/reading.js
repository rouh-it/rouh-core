/* Chat Options: the one control for what Rouh uses in the chat on screen (rouh/reading.py).
 *
 * Petar, 15 November 2026 (Chat Change Planning): "context controls should be unified everywehre.
 * same icon, same location, same interface ... a button next to the smart". So a button beside the
 * model on the composer's line, in every chat (sliders since 16 November 2026: "this is book
 * doesn't make sense to me"), and a thin strip under the chat's head that says in plain words what
 * is read ("Reading Memory · Your rules · Tools · Task 62 · 1 note"); pressing either opens one
 * panel above the box, headed "Chat Options" and nothing more:
 *
 * - while the chat is incognito, that it is and what is kept (Incognito is a button of its own,
 *   `incogBtn`, beside this one);
 * - in a task's chat, what is read now, each item with its size (short, long, very long) and
 *   "outline" when it is too much to read whole;
 * - memory, the person's rules and tools, with permission, privacy and safety shown always on;
 * - in a task's chat, notes, pages, chat histories and the subtasks (none, all, some);
 * - a link to everything this chat is told, full screen (`fullOpen`), and Reset to defaults.
 *
 * The full list (Petar, 16 November 2026): the same switches, kept in step with the panel; every
 * rule and piece of live context with its whole text and the switch it follows; filters by switch
 * and a search; a switch for each item but the locked ones; whether the choices are this chat's
 * only or kept for new chats; Reset to defaults; and one line for Synapse, which follows Memory.
 *
 * Every switch is a real button with role="switch", the whole row its target. What the server says
 * after each change is what is drawn: the panel never guesses a count. Outside the chain, like
 * app/composer_extras.js, and imported by app.js after it.
 */
import { CHATS, openChat } from 'app/chats.js';
import { composerPopsClose } from 'app/composer_extras.js';
import { $, el } from 'app/helpers.js';
import { ASK } from 'app/runs.js';
import { notify } from 'app/notices.js';

/** @typedef {{ id: string, kind: string, label: string, owner: string, path: string, size: string,
 *              tokens: number, on: boolean, how: string }} ReadItem */
/** @typedef {{ id: string, title: string, text: string, source: string, locked: boolean, own?: boolean,
 *              on: boolean, off: boolean, with?: string, when?: string, live?: boolean, fills?: string }} ReadRule */
/** @typedef {{ chat: string, kind: string, incognito: boolean, settings: Record<string, any>,
 *              items: ReadItem[], subtasks?: {id: string, label: string, on: boolean}[],
 *              task?: {id: string, label: string}, rules: ReadRule[], context?: ReadRule[], strip: string,
 *              outlined: number, reads: number, budget: number, kept?: string,
 *              synapse?: {text: string, on: boolean}, sources?: Record<string, string>,
 *              saved?: Record<string, any> }} ReadView */

var btn = /** @type {HTMLButtonElement | null} */ ($('readingBtn'));
var pop = $('readingPop');
var strip = /** @type {HTMLButtonElement | null} */ ($('readingStrip'));
var incogBtn = /** @type {HTMLButtonElement | null} */ ($('incogBtn'));
var full = $('toldFull');
// On the page itself, so no box around the composer can hold it inside its own bounds.
if (full && full.parentElement !== document.body) document.body.appendChild(full);
/** The full list: which switch's items are shown, the search, and what had the focus before it opened. */
var FULL = { filter: 'all', q: '', opener: /** @type {HTMLElement | null} */ (null) };
var SLIDERS = 'M4 7h9M17 7h3M4 17h3M11 17h9M17 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM11 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0z';
var HAT = 'M3 11h18M6.5 11l1.6-5.5h7.8L17.5 11M10.1 16a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0zM19.1 16a2.6 2.6 0 1 1-5.2 0 2.6 2.6 0 0 1 5.2 0zM10.1 16h3.8';
var READ = { chat: '', data: /** @type {ReadView | null} */ (null), more: false, busy: false, asked: 0, focus: '', painted: '', openAfter: false, doc: '', after: '' };

var LOCK = 'M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z';

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

/** The strip, from the server's words. @param {ReadView | null} d */
function paintStrip(d) {
  document.body.classList.toggle('chat-incognito', !!(d && d.incognito));
  var mark = $('incogMark');
  if (mark) mark.hidden = !(d && d.incognito);
  if (incogBtn) {
    incogBtn.setAttribute('aria-pressed', d && d.incognito ? 'true' : 'false');
    incogBtn.dataset.tip = d && d.incognito ? 'Leave incognito: this chat is deleted, and you go back to General'
      : 'Incognito: a new chat where nothing is kept, deleted when you leave it';
  }
  if (!strip) return;
  strip.hidden = !d;
  if (!d) return;
  var words = $('readingStripWords'), stripMark = $('readingStripMark');
  if (!words || !stripMark) return;
  words.textContent = '';
  stripMark.textContent = '';
  stripMark.appendChild(icon(d.incognito ? HAT : SLIDERS, 15));
  if (d.incognito) {
    words.appendChild(el('b', '', 'Incognito:'));
    words.appendChild(document.createTextNode('nothing here is kept, and the chat is deleted when you leave it'));
  } else {
    words.appendChild(el('b', '', 'Reading'));
    // The page open on the canvas beside the chat, which every message is told (`rouh/page_in_chat.py`).
    var bits = d.strip.split(' · ');
    if (ASK.doc) bits.push('This page');
    READ.doc = ASK.doc;
    bits.forEach(function (bit, i) {
      if (i) words.appendChild(document.createTextNode(' · '));
      words.appendChild(el('span', 'reading-strip-bit', bit));
    });
  }
  var says = (d.incognito ? 'Incognito chat. ' : 'Reading: ' + d.strip + '. ') + 'Press for Chat Options.';
  strip.title = says;
  strip.setAttribute('aria-label', says);
}

/** The panel. @param {ReadView} d */
function paintPop(d) {
  if (!pop) return;
  var s = d.settings;
  var task = d.kind === 'task';
  pop.textContent = '';
  // Just the name of the panel: a second line under it read as one more option (Petar, 16 November 2026).
  var h = el('h2', '', 'Chat Options');
  h.id = 'readingHead';
  h.tabIndex = -1;
  pop.appendChild(h);

  if (task && d.items.length) {
    var list = sec(d.outlined ? 'What is read now · ' + d.outlined + ' of ' + d.items.length + ' as outlines'
      : 'What is read now · all ' + d.items.length + ' read whole');
    var ul = el('ul', 'reading-items');
    // What is cut to an outline first, then the largest: the short list shows what matters.
    var order = d.items.slice().sort(function (a, b) {
      return (a.how === 'outline' ? 0 : 1) - (b.how === 'outline' ? 0 : 1) || b.tokens - a.tokens;
    });
    (READ.more ? order : order.slice(0, 3)).forEach(function (it) {
      var li = el('li', '');
      var n = el('span', 'n', it.label);
      n.title = it.path || it.label;
      li.appendChild(n);
      li.appendChild(el('span', 'z', it.size));
      if (it.how === 'outline') li.appendChild(el('span', 'o', 'outline'));
      ul.appendChild(li);
    });
    list.appendChild(ul);
    if (d.items.length > 3) {
      var more = el('button', 'reading-more', READ.more ? 'Show fewer' : 'Show all ' + d.items.length);
      more.type = 'button';
      more.dataset.more = '1';
      list.appendChild(more);
    }
    pop.appendChild(list);
  }

  // Incognito is a button of its own (`incogBtn`); here, while it is on, what it means and a way out.
  if (d.incognito) {
    var top = sec('');
    top.appendChild(row('incognito', true, 'Incognito', 'On: nothing here is kept, and the chat is deleted when you leave it', 'incog'));
    if (d.kept) top.appendChild(el('p', 'reading-verdict', d.kept));
    pop.appendChild(top);
  }

  var every = sec('What this chat uses');
  switches(every, s);
  pop.appendChild(every);

  if (task && d.task) {
    var t = sec('Task ' + d.task.label.split(' · ')[0]);
    t.appendChild(row('md', !!s.md, 'Notes', 'The task’s .md files'));
    t.appendChild(row('html', !!s.html, 'Pages', 'The task’s pages, as their words'));
    t.appendChild(row('histories', !!s.histories, 'Chat histories', 'What was said in the task’s other chats'));
    var subs = d.subtasks || [];
    if (subs.length) {
      var r = el('div', 'reading-row locked');
      var rt = el('span', 'reading-row-t');
      rt.appendChild(el('b', '', 'Subtasks'));
      rt.appendChild(el('span', '', subs.length + ' in this task'));
      r.appendChild(rt);
      var seg = el('span', 'reading-seg');
      seg.setAttribute('role', 'group');
      seg.setAttribute('aria-label', 'Which subtasks are read');
      [['none', 'None'], ['all', 'All'], ['some', 'Some']].forEach(function (p) {
        var b = el('button', '', p[1]);
        b.type = 'button';
        b.dataset.seg = p[0];
        b.setAttribute('aria-pressed', s.subtasks === p[0] ? 'true' : 'false');
        seg.appendChild(b);
      });
      r.appendChild(seg);
      t.appendChild(r);
      if (s.subtasks === 'some') {
        subs.forEach(function (sub) { t.appendChild(row('sub:' + sub.id, sub.on, sub.label, '', 'sub')); });
      }
    }
    pop.appendChild(t);
  }
  // Everything this chat is told is a link to the full list, never a list of its own here.
  var foot = sec('');
  var n = toldCount(d);
  var link = el('button', 'reading-link');
  link.type = 'button';
  link.dataset.full = '1';
  link.appendChild(el('span', '', 'See everything this chat is told (' + n.told + ' of ' + n.all + ')'));
  link.appendChild(icon('M9 6l6 6-6 6', 14));
  foot.appendChild(link);
  var reset = el('button', 'reading-link quiet', 'Reset to defaults');
  reset.type = 'button';
  reset.dataset.reset = '1';
  foot.appendChild(reset);
  if (d.saved && Object.keys(d.saved).length) foot.appendChild(el('p', 'reading-verdict', 'New chats start with your saved choices.'));
  pop.appendChild(foot);
}

/** The three switches and the locked one, the same in the panel and the full list. @param {HTMLElement} into
    @param {Record<string, any>} s */
function switches(into, s) {
  into.appendChild(row('memory', !!s.memory, 'Memory', 'What Rouh has learned about you and your people'));
  into.appendChild(row('rules', !!s.rules, 'Your rules', 'Off keeps the rules about permission, privacy and safety'));
  into.appendChild(row('tools', !!s.tools, 'Tools', 'Mail, calendar, the browser, jobs and the rest'));
  into.appendChild(row('safety', true, 'Permission, privacy and safety', 'Always on', 'locked', true));
}

/** The full list, from the server's words. @param {ReadView} d */
function fullPaint(d) {
  var inner = $('toldIn'), foot = $('toldFoot');
  if (!full || !inner || !foot) return;
  var s = d.settings, names = d.sources || {}, every = allItems(d), n = toldCount(d);
  var keepFocus = document.activeElement && document.activeElement.id === 'toldQ';
  inner.textContent = '';
  var head = el('p', 'cot-verdict', n.told + ' of ' + n.all + ' items reach this chat with these choices.');
  head.appendChild(el('small', '', (s.memory ? 'Memory is on, so all of Synapse is read for each message too. '
    : 'Memory is off: Synapse is not read, and your name is taken out of what is told. ')
    + 'An item marked “only when” is told only in the turns it names.'));
  inner.appendChild(head);
  var sw = el('div', 'cot-switches');
  switches(sw, s);
  inner.appendChild(sw);
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
      lk.appendChild(document.createTextNode(r.source === 'chat' ? 'set above' : 'always on'));
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
        : 'Left out: ' + (r.with && !s.tools ? 'Tools' : names[r.source] || r.source) + ' is off.';
      li.appendChild(el('p', 'cot-why', why));
    }
    // Lines the source wrapped by hand run on; blank lines and list items stay where they are.
    li.appendChild(el('p', 'cot-text', r.text.replace(/\n {2,}(?=\S)/g, ' ').replace(/([^\n])\n(?![\n\-*•]|\d+[.)] )/g, '$1 ')));
    ul.appendChild(li);
  });
  inner.appendChild(ul);

  foot.textContent = '';
  if (!d.incognito) {
    var apply = el('div', 'cot-apply');
    apply.setAttribute('role', 'radiogroup');
    apply.setAttribute('aria-label', 'Apply these choices to');
    [['0', 'This chat only'], ['1', 'This chat and new chats']].forEach(function (o) {
      var lab = el('label', '');
      var r = /** @type {HTMLInputElement} */ (el('input', ''));
      r.type = 'radio';
      r.name = 'toldKeep';
      r.value = o[0];
      r.checked = (s.keep ? '1' : '0') === o[0];
      lab.appendChild(r);
      lab.appendChild(document.createTextNode(o[1]));
      apply.appendChild(lab);
    });
    foot.appendChild(apply);
  }
  var reset = el('button', 'cot-btn', 'Reset to defaults');
  reset.type = 'button';
  reset.dataset.reset = '1';
  reset.title = 'Everything on, nothing left out' + (d.incognito ? '' : ', here and for new chats');
  foot.appendChild(reset);
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

/** @param {ReadView | null} d */
function paint(d) {
  READ.data = d;
  paintStrip(d);
  if (d && full && !full.hidden) fullPaint(d);
  if (d && pop && !pop.hidden) {
    var moved = READ.painted !== d.chat;
    paintPop(d);
    place();
    // Another chat in the same open panel starts at its top: what it is, before its rules.
    if (moved) pop.scrollTop = 0;
    READ.painted = d.chat;
    var again = READ.focus ? /** @type {HTMLElement | null} */ (pop.querySelector(READ.focus)) : null;
    if (again) again.focus();
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
  btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (strip) strip.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (on) place();
  if (on && !READ.data) {
    pop.textContent = '';
    pop.appendChild(el('p', 'reading-verdict', 'Finding what this chat reads…'));
  }
  if (on && READ.data) {
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
      paint(d);
      // Just turned incognito: the panel shows the rules that will apply in it.
      if (READ.openAfter && d && d.incognito) { READ.openAfter = false; openPop(true); }
    })
    .catch(function () { /* the next look asks again */ READ.chat = ''; });
}

/** @param {Record<string, any>} change */
function change(change) {
  var chat = READ.chat || currentChat();
  if (!chat || READ.busy) return;
  READ.busy = true;
  // Whatever an earlier read answers after this, the answer to this change is what is drawn.
  READ.asked++;
  fetch('/api/reading', { method: 'POST', credentials: 'same-origin',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ chat: chat, change: change }) })
    .then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d && d.error ? d.error : 'That could not be changed.');
        return d;
      });
    })
    .then(function (d) {
      READ.busy = false;
      if (READ.chat === chat) paint(d);
      if (READ.after) { refocus(READ.after); READ.after = ''; }
    })
    .catch(function (err) {
      READ.busy = false;
      notify(String(err && err.message || 'That could not be changed: Rouh is not connected.'), { tone: 'error' });
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
  if (!on) { openChat(CHATS.general); return; }
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

/** A switch pressed in the panel or the full list: what it changes on the server.
    @param {HTMLElement} t */
function pressed(t) {
  if (!READ.data) return;
  if (t.dataset.reset) { change({ reset: true }); return; }
  if (t.dataset.seg) { change({ subtasks: t.dataset.seg }); return; }
  var key = t.dataset.key;
  if (!key || t.getAttribute('aria-disabled') === 'true') return;
  var on = t.getAttribute('aria-checked') !== 'true';
  if (key === 'incognito') {
    if (incognitoTo) incognitoTo(on);
    else notify('Incognito is not ready on this page yet.', { tone: 'error' });
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
  if (strip) strip.addEventListener('click', function (e) {
    e.stopPropagation();
    openPop(pop.hidden);
  });
  pop.addEventListener('click', function (e) {
    var t = /** @type {HTMLElement} */ (e.target).closest('button');
    if (!t || !READ.data) return;
    READ.focus = t.dataset.key ? '[data-key="' + t.dataset.key + '"]' : t.dataset.seg ? '[data-seg="' + t.dataset.seg + '"]'
      : t.dataset.more ? '[data-more]' : t.dataset.reset ? '[data-reset]' : '';
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
      READ.after = t.dataset.key ? '#toldFull [data-key="' + t.dataset.key + '"]' : t.dataset.reset ? '#toldFull [data-reset]' : '';
      pressed(t);
    });
    full.addEventListener('input', function (e) {
      var t = /** @type {HTMLInputElement} */ (e.target);
      if (t.id !== 'toldQ' || !READ.data) return;
      FULL.q = t.value;
      fullPaint(READ.data);
    });
    full.addEventListener('change', function (e) {
      var t = /** @type {HTMLInputElement} */ (e.target);
      if (t.name === 'toldKeep') { READ.after = '#toldFull input[name="toldKeep"][value="' + t.value + '"]'; change({ keep: t.value === '1' }); }
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
    if (pop.hidden || (full && !full.hidden)) return;
    var t = /** @type {Node} */ (e.target);
    if (pop.contains(t) || btn.contains(t) || (strip && strip.contains(t)) || (incogBtn && incogBtn.contains(t))) return;
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
}

export { onIncognito, openPop as readingOpen, READ };
