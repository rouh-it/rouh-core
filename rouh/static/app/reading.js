/* What I'm reading: the one control for what Rouh reads in the chat on screen (rouh/reading.py).
 *
 * Petar, 15 November 2026 (Chat Change Planning): "context controls should be unified everywehre.
 * same icon, same location, same interface ... a button next to the smart". So an open book beside
 * the model on the composer's line, in every chat, and a thin strip under the chat's head that says
 * in plain words what is read ("Reading Memory · Your rules · Tools · Task 62 · 1 note"); pressing
 * either opens one panel above the box:
 *
 * - Incognito, first, because it changes everything below it (app/reading.js `incognitoTo`);
 * - in a task's chat, what is read now, each item with its size (short, long, very long) and
 *   "outline" when it is too much to read whole;
 * - memory, the person's rules and tools, in every chat, with permission, privacy and safety
 *   shown always on;
 * - in a task's chat, notes, pages, chat histories and the subtasks (none, all, some);
 * - the rules told in this chat, each readable, open in an incognito chat.
 *
 * Every switch is a real button with role="switch", the whole row its target. What the server says
 * after each change is what is drawn: the panel never guesses a count. Outside the chain, like
 * app/composer_extras.js, and imported by app.js after it.
 */
import { CHATS, openChat } from 'app/chats.js';
import { composerPopsClose } from 'app/composer_extras.js';
import { $, el } from 'app/helpers.js';
import { notify } from 'app/notices.js';

/** @typedef {{ id: string, kind: string, label: string, owner: string, path: string, size: string,
 *              tokens: number, on: boolean, how: string }} ReadItem */
/** @typedef {{ title: string, text: string, locked: boolean, own: boolean, on: boolean, with: string }} ReadRule */
/** @typedef {{ chat: string, kind: string, incognito: boolean, settings: Record<string, any>,
 *              items: ReadItem[], subtasks?: {id: string, label: string, on: boolean}[],
 *              task?: {id: string, label: string}, rules: ReadRule[], strip: string,
 *              outlined: number, reads: number, budget: number, kept?: string }} ReadView */

var btn = /** @type {HTMLButtonElement | null} */ ($('readingBtn'));
var pop = $('readingPop');
var strip = /** @type {HTMLButtonElement | null} */ ($('readingStrip'));
var READ = { chat: '', data: /** @type {ReadView | null} */ (null), more: false, busy: false, asked: 0, focus: '', painted: '', openAfter: false };

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

/** @param {ReadView} d @param {boolean} open */
function rulesBlock(d, open) {
  var s = sec('');
  var det = el('details', 'reading-rules');
  if (open) det.open = true;
  var locked = d.rules.filter(function (r) { return r.locked; }).length;
  var withTools = d.rules.filter(function (r) { return !!r.with; }).length;
  det.appendChild(el('summary', '', 'Rules told in this chat: ' + d.rules.length + ' (' + locked + ' always on'
    + (withTools ? ', ' + withTools + ' only with their tools' : '') + ')'));
  var ul = el('ul', '');
  d.rules.forEach(function (r) {
    var li = el('li', r.on ? '' : 'off');
    var head = el('b', '');
    head.appendChild(el('span', '', r.title));
    var tag = el('span', 'reading-lock');
    if (r.locked) { tag.appendChild(icon(LOCK, 12)); tag.appendChild(document.createTextNode('always on')); }
    else if (!r.on) tag.textContent = 'off here';
    else if (r.with) tag.textContent = 'with ' + r.with.replace(/^the /, '');
    if (tag.textContent) head.appendChild(tag);
    li.appendChild(head);
    li.appendChild(el('p', '', r.text.length > 320 ? r.text.slice(0, 320) + '…' : r.text));
    ul.appendChild(li);
  });
  det.appendChild(ul);
  s.appendChild(det);
  return s;
}

/** The strip, from the server's words. @param {ReadView | null} d */
function paintStrip(d) {
  document.body.classList.toggle('chat-incognito', !!(d && d.incognito));
  var mark = $('incogMark');
  if (mark) mark.hidden = !(d && d.incognito);
  if (!strip) return;
  strip.hidden = !d;
  if (!d) return;
  var words = $('readingStripWords'), stripMark = $('readingStripMark');
  if (!words || !stripMark) return;
  words.textContent = '';
  stripMark.textContent = '';
  stripMark.appendChild(icon(d.incognito
    ? 'M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c5 0 9 4.5 10 7a13 13 0 0 1-3 4.1M6.6 6.6A13 13 0 0 0 2 12c1 2.5 5 7 10 7a10 10 0 0 0 4.4-1M9.9 9.9a3 3 0 0 0 4.2 4.2'
    : 'M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5C17 4.5 14 5 12 6.5zM12 6.5v13', 15));
  if (d.incognito) {
    words.appendChild(el('b', '', 'Incognito:'));
    words.appendChild(document.createTextNode('nothing here is kept, and the chat is deleted when you leave it'));
  } else {
    words.appendChild(el('b', '', 'Reading'));
    d.strip.split(' · ').forEach(function (bit, i) {
      if (i) words.appendChild(document.createTextNode(' · '));
      words.appendChild(el('span', 'reading-strip-bit', bit));
    });
  }
  var says = (d.incognito ? 'Incognito chat. ' : 'Reading: ' + d.strip + '. ') + 'Press to change what I read.';
  strip.title = says;
  strip.setAttribute('aria-label', says);
}

/** The panel. @param {ReadView} d */
function paintPop(d) {
  if (!pop) return;
  var s = d.settings;
  var task = d.kind === 'task';
  pop.textContent = '';
  var h = el('h2', '', 'What I’m reading');
  h.id = 'readingHead';
  h.tabIndex = -1;
  pop.appendChild(h);
  var verdict = d.kind === 'task'
    ? (d.outlined ? 'Too much to read whole: ' + d.outlined + ' of ' + d.items.length
        + ' items are read as outlines, their headings and first lines.'
        : 'All ' + d.items.length + ' item' + (d.items.length === 1 ? ' is' : 's are') + ' read whole.')
    : d.kind === 'general' ? 'You, your rules and your tools. A task’s chat also reads its task.'
    : 'You, your rules and your tools.';
  pop.appendChild(el('p', 'reading-verdict', verdict));

  if (task && d.items.length) {
    var list = sec('What is read now');
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

  var top = sec('');
  if (incognitoTo || d.incognito) top.appendChild(row('incognito', d.incognito, 'Incognito',
    d.incognito ? 'On: nothing here is kept, and the chat is deleted when you leave it'
                : 'A new chat where nothing is kept, deleted when you leave it', 'incog'));
  if (d.incognito && d.kept) top.appendChild(el('p', 'reading-verdict', d.kept));
  if (top.childNodes.length) pop.appendChild(top);

  var every = sec('In every chat');
  every.appendChild(row('memory', !!s.memory, 'Memory', 'What Rouh has learned about you and your people'));
  every.appendChild(row('rules', !!s.rules, 'Your rules', 'Off keeps the rules about permission, privacy and safety'));
  every.appendChild(row('tools', !!s.tools, 'Tools', 'Mail, calendar, the browser, jobs and the rest'));
  every.appendChild(row('safety', true, 'Permission, privacy and safety', 'Always on', 'locked', true));
  pop.appendChild(every);
  if (d.incognito) pop.appendChild(rulesBlock(d, true));

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
  if (!d.incognito) pop.appendChild(rulesBlock(d, false));
}

/** @param {ReadView | null} d */
function paint(d) {
  READ.data = d;
  paintStrip(d);
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
      : t.dataset.more ? '[data-more]' : '';
    if (t.dataset.more) { READ.more = !READ.more; paint(READ.data); return; }
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
  });
  document.addEventListener('pointerdown', function (e) {
    if (pop.hidden) return;
    var t = /** @type {Node} */ (e.target);
    if (pop.contains(t) || btn.contains(t) || (strip && strip.contains(t))) return;
    openPop(false);
  }, true);
  window.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || pop.hidden) return;
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
  }, 400);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) READ.chat = ''; });
  window.addEventListener('rouh:reading-again', function () { READ.chat = ''; });
  window.addEventListener('resize', place);
}

export { onIncognito, openPop as readingOpen, READ };
