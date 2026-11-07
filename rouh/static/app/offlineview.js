/* Rouh's page, the Offline page, at /offline (`rouh/offline.py`, app/offline.js).
 *
 * It stands outside the chain of modules, like app/stars.js, and app.js
 * imports it last: its top level only wires its own buttons, and every
 * module it calls has run by then.
 *
 * What it shows, top to bottom: whether there is a connection, and what this
 * device keeps for when there is not - the same on the laptop and the phone,
 * kind by kind in Petar's order, how many, over which days, how much and when
 * each was last made, and what a device short of room left out - with
 * Refresh, how it is kept private, and how it is kept up to date (only while
 * Rouh is open: an iPhone gives a web app no time in the background, and this
 * says so rather than pretending). Then one search over all of it, and the
 * copy itself in tabs: tasks and their notes, mail, the calendar, decisions,
 * people, chats with their forks, notes for Rouh, and the outbox. Clockwork,
 * the goals, the quests and the task browser are their own pages, which open
 * from the copy as they are.
 *
 * Everything that can be done here goes through the outbox (`offlineQueue`):
 * with no connection it waits on this device, and with one it goes at once,
 * the same way. So answering a decision, replying, editing a task's notes,
 * making a reminder or a task, and recording a note all work the same online
 * and off, and are carried out once.
 */
import { $, el } from 'app/helpers.js';
import { notify } from 'app/notices.js';
import { KINDS, OFF, offlineQueue, offlineRepaint, outboxFlush, packAll, packRefresh, size, waiting, whenSaid,
  answerDecision, isOnline } from 'app/offline.js';
import { goToAddress, renderBlock, showLayer } from 'app/cards.js';
import { narrow, sidebarDone } from 'app/controls.js';
import { ORBX, orbExpand } from 'app/orb.js';
import { A, acquireMic, releaseMic } from 'app/voice.js';

var TABS = [['tasks', 'Tasks'], ['mail', 'Mail'], ['calendar', 'Calendar'], ['decisions', 'Decisions'],
  ['people', 'People'], ['chats', 'Chats'], ['notes', 'Notes'], ['outbox', 'Outbox']];
//: What each kind is called on the panel, and where its own page is, for the ones that have one.
var KIND_WORDS = { calendar: 'Calendar, a month either side', decisions: 'Decisions waiting on you',
  clockwork: 'Clockwork', goals: 'Goals, with their plans', quests: 'Quests, with ledgers and budgets',
  tasks: 'Tasks, whole', chats: 'Chats of two weeks, with forks', mail: 'Email, both inboxes',
  contacts: 'People' };
var KIND_PAGES = { clockwork: '/clockwork', goals: '/goals', quests: '/quests', tasks: '/tasks',
  decisions: '/decisions' };
var KIND_TABS = { calendar: 'calendar', decisions: 'decisions', tasks: 'tasks', chats: 'chats', mail: 'mail',
  contacts: 'people' };
//: How many rows a long list draws at once, and how many more each press of Show more adds.
var LIST_STEP = 120;
var STATUS_WORDS = { waiting: 'Waiting to send', sending: 'Sending', received: 'Received', running: 'Carrying out',
  done: 'Done', clash: 'Needs you, in Decisions', held: 'Needs your confirmation, in Decisions',
  failed: 'Could not be done', dropped: 'Set aside' };

var OFFV = {
  open: false,
  tab: 'tasks',
  //: What is opened inside a tab: a task's rel, a message's id, a chat's id.
  item: '',
  editing: '',
  replying: '',
  composing: false,
  find: '',
  rec: /** @type {any} */ (null),
  //: The part saying how the copy is kept is open, and stays so when the card is drawn again.
  how: false,
  //: The calendar's week, as how many weeks from this one: 0 is this week, -4 a month ago.
  week: 0,
  //: The day the mail list starts at, 'YYYY-MM-DD', or '' for the newest; and how many it draws.
  mailDay: '',
  shown: LIST_STEP,
  //: The event opened on the calendar, by its key.
  event: '',
  cards: /** @type {Record<string, any>} */ ({})
};

//: Whether Offline's section of Anatomy's Meta page is showing (`RouhOfflinePanel`, below).
var PANEL = { shown: false };

function offlineViewing() { return !!(OFFV && OFFV.open); }

function offlineOpen(tab, item) {
  if (ORBX.open) orbExpand(false);
  if (tab) { OFFV.tab = tab; OFFV.item = item || ''; OFFV.event = ''; }
  var was = OFFV.open;
  OFFV.open = true;
  if (!was) showLayer('offlineView');
  sidebarDone();
  offlineRepaint();
  packAll().then(draw);
  draw();
  if (!narrow()) { var v = $('offlineView'); if (v) v.focus({ preventScroll: true }); }
}

function offlineClose() {
  if (!OFFV || !OFFV.open) return;
  OFFV.open = false;
  stopRecording(false);
  showLayer(null);
  offlineRepaint();
}

/* Called by app/offline.js whenever something it says changed. Redraws only what
   cannot be in the middle of being typed into. */
var paintSoon = 0;
function offlinePaint() {
  if (PANEL.shown) panelDraw();
  if (window.RouhAnatomy) window.RouhAnatomy.repaint();
  if (!OFFV || !OFFV.open) return;
  clearTimeout(paintSoon);
  paintSoon = window.setTimeout(function () {
    drawMeta();
    var status = $('offStatus');
    if (status) status.replaceWith(statusCard());
    var held = $('offHeld');
    if (held) held.replaceWith(heldCard());
    if (OFFV.tab === 'outbox' && !typing()) drawTab();
    drawTabs();
  }, 60);
}

function typing() {
  var a = document.activeElement;
  return !!(a && $('offlineBody') && $('offlineBody').contains(a) && /^(TEXTAREA|INPUT|SELECT)$/.test(a.tagName));
}

/* ---------------------------------------------------------------- drawing */

function draw() {
  if (!OFFV.open) return;
  var body = $('offlineBody');
  if (!body) return;
  drawMeta();
  body.textContent = '';
  var page = el('div', 'off-page');
  page.appendChild(statusCard());
  page.appendChild(heldCard());
  page.appendChild(findBox());
  var results = el('div', 'off-found');
  results.id = 'offFound';
  page.appendChild(results);
  var tabs = el('div', 'off-tabs');
  tabs.id = 'offTabs';
  tabs.setAttribute('role', 'tablist');
  page.appendChild(tabs);
  var pane = el('div', 'off-pane');
  pane.id = 'offPane';
  pane.setAttribute('role', 'tabpanel');
  page.appendChild(pane);
  body.appendChild(page);
  drawTabs();
  drawTab();
  if (OFFV.find) drawFound();
}

function drawMeta() {
  var m = $('offlineMeta');
  if (!m) return;
  var n = waiting().length;
  m.textContent = (isOnline() ? 'Online' : 'Offline') + ' · ' + OFF.device.name
    + (n ? ' · ' + n + ' waiting to send' : '');
}

function statusCard() {
  var card = el('section', 'off-card off-status');
  card.id = 'offStatus';
  var on = isOnline();
  var head = el('div', 'off-status-head');
  var dot = el('span', 'off-dot ' + (on ? 'on' : 'away'));
  dot.setAttribute('aria-hidden', 'true');
  head.appendChild(dot);
  var n = waiting().length;
  head.appendChild(el('strong', 'off-big', on
    ? (n ? 'Online, sending what you did offline' : 'Online')
    : 'Offline. Everything below works from this device’s copy.'));
  card.appendChild(head);
  var left = KINDS.filter(function (k) { return (OFF.meta.parts[k.id] || {}).left; });
  card.appendChild(el('p', 'off-line', 'This ' + OFF.device.name + ' keeps the same copy as your other '
    + 'devices: the calendar a month either side of today, thirty days of email, two weeks of chats with all '
    + 'their forks, every task the Control Room ranks above quiet, the decisions, and all of Clockwork, the '
    + 'goals and the quests.'));
  card.appendChild(el('p', 'off-line', 'Last made ' + whenSaid(OFF.meta.refreshedAt) + '.'
    + (n ? ' ' + n + (n === 1 ? ' action waits' : ' actions wait') + ' to be sent.' : '')));
  if (left.length) {
    card.appendChild(el('p', 'off-line off-warn', 'Short of room, so left out: '
      + left.map(function (k) { return k.name.toLowerCase(); }).join(', ') + '. What comes first is kept '
      + 'first: calendar, decisions, Clockwork, goals, quests, tasks, chats, email.'));
  }
  if (OFF.meta.why) card.appendChild(el('p', 'off-line', OFF.meta.why));
  var acts = el('div', 'off-acts');
  var again = el('button', 'ctl small off-primary', OFF.refreshing ? 'Making the copy…' : 'Refresh now');
  again.type = 'button';
  again.disabled = OFF.refreshing || !on;
  again.addEventListener('click', function () { packRefresh(true).then(draw); });
  acts.appendChild(again);
  if (n && on) {
    var send = el('button', 'ctl small', 'Send the outbox now');
    send.type = 'button';
    send.addEventListener('click', function () { outboxFlush(); });
    acts.appendChild(send);
  }
  card.appendChild(acts);
  var how = /** @type {HTMLDetailsElement} */ (el('details', 'off-how'));
  how.open = OFFV.how;
  how.addEventListener('toggle', function () { OFFV.how = how.open; });
  how.appendChild(el('summary', null, 'How it is kept up to date, and private'));
  var phone = OFF.device.kind === 'phone' || /iPhone|iPad/.test(navigator.userAgent);
  [
    'It is made again while Rouh is open: when you open it, when you come back to it, and every 15 minutes. '
      + 'Nothing is fetched by itself on a mobile connection when the browser can tell; Refresh now does it anyway.',
    phone ? 'On an iPhone, Safari gives a web app no time in the background, so the copy is never made while Rouh is '
      + 'closed. Open Rouh before you lose the connection and the copy is as fresh as that moment.'
      : 'Nothing is made in the background while Rouh is closed.',
    'A device short of room keeps the kinds in the order above and leaves out the last ones first, and this '
      + 'page says which.',
    OFF.sealed ? 'It is encrypted on this device (AES-GCM) with a key the browser made for you and will not hand '
      + 'out, even to Rouh’s own page. It belongs to your sign-in: signing out deletes it and the key, and a '
      + 'page for anybody else clears it before it keeps anything.'
      : 'This browser cannot encrypt it, so nothing private is kept on this device.',
    'Your device’s own encryption (FileVault on a Mac, the passcode on an iPhone) is what protects it when '
      + 'the device itself is lost: a browser cannot ask for a second password every time without getting in the way.'
  ].forEach(function (t) { how.appendChild(el('p', 'off-line', t)); });
  var e = OFF.storage;
  if (e && e.quota) {
    how.appendChild(el('p', 'off-line', 'This browser lets Rouh keep up to ' + size(e.quota) + ' here; it uses '
      + size(e.usage || 0) + '.' + (OFF.persisted ? ' It is kept even when the device is short of space.' : '')));
  }
  card.appendChild(how);
  return card;
}

/* What the device holds, kind by kind, in the order it is kept: how many, over which days,
   when it was made and how much room it takes, and what was left out and why. Each kind's
   name opens it: its tab here, or its own page. */
function heldCard() {
  var card = el('section', 'off-card off-held');
  card.id = 'offHeld';
  card.appendChild(el('h4', 'off-h', 'What this device holds'));
  var table = el('table', 'off-table');
  var thead = el('thead');
  var hr = el('tr');
  [['', ''], ['How many', 'off-n'], ['Which days', 'off-range'], ['Made', 'off-when'], ['Room', 'off-size']]
    .forEach(function (h) {
      var th = el('th', h[1] || null, h[0]);
      th.setAttribute('scope', 'col');
      hr.appendChild(th);
    });
  thead.appendChild(hr);
  table.appendChild(thead);
  var tbody = el('tbody');
  KINDS.forEach(function (kind) {
    var m = OFF.meta.parts[kind.id] || {};
    var tr = el('tr', m.left ? 'off-left' : null);
    tr.dataset.kind = kind.id;
    var th = el('th');
    th.setAttribute('scope', 'row');
    var words = KIND_WORDS[kind.id] || kind.name;
    if (KIND_TABS[kind.id] || KIND_PAGES[kind.id]) {
      var b = el('button', 'off-kind-go', words);
      b.type = 'button';
      b.addEventListener('click', function () {
        // From Anatomy's Meta page, the copy itself is this page's, at that kind's tab.
        if (!OFFV.open && KIND_TABS[kind.id]) { offlineOpen(KIND_TABS[kind.id], ''); return; }
        if (KIND_TABS[kind.id]) {
          OFFV.tab = KIND_TABS[kind.id];
          OFFV.item = '';
          drawTabs();
          drawTab();
          var tabs = $('offTabs');
          if (tabs) tabs.scrollIntoView({ block: 'start', behavior: 'smooth' });
        } else {
          offlineClose();
          goToAddress(KIND_PAGES[kind.id]);
        }
      });
      th.appendChild(b);
    } else {
      th.textContent = words;
    }
    tr.appendChild(th);
    tr.appendChild(el('td', 'off-n', m.left || !m.at ? '-' : m.of ? m.count + ' of ' + m.of : String(m.count)));
    var range = el('td', 'off-range');
    if (m.left) range.textContent = 'Left out: ' + m.left;
    else if (m.making) range.textContent = 'Being made now…';
    else if (!m.at) range.textContent = m.error ? 'Not yet: ' + m.error : 'Not yet';
    else range.textContent = [rangeWords(m), m.range, m.error].filter(Boolean).join(' · ') || 'All of it';
    // On a phone the column for when it was made is folded under the days, as a line of its own.
    if (m.at) range.appendChild(el('span', 'off-made', 'Made ' + whenSaid(m.at)));
    tr.appendChild(range);
    tr.appendChild(el('td', 'off-when', m.at ? whenSaid(m.at) : m.tried ? 'Tried ' + whenSaid(m.tried) : ''));
    tr.appendChild(el('td', 'off-size', m.bytes ? size(m.bytes) : ''));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  card.appendChild(table);
  return card;
}

/* The days one kind covers, as a person says them: "12 Sep – 12 Nov". */
function rangeWords(m) {
  if (!m.from && !m.to) return '';
  var f = function (t) {
    return t ? new Date(t * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' }) : '';
  };
  if (m.from && m.to) return f(m.from) + ' – ' + f(m.to);
  return m.from ? 'from ' + f(m.from) : 'until ' + f(m.to);
}

function drawTabs() {
  var tabs = $('offTabs');
  if (!tabs) return;
  tabs.textContent = '';
  TABS.forEach(function (t) {
    var b = el('button', 'off-tab' + (OFFV.tab === t[0] ? ' on' : ''), t[1]);
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', OFFV.tab === t[0] ? 'true' : 'false');
    var n = tabCount(t[0]);
    if (n) b.appendChild(el('span', 'off-count', String(n)));
    b.addEventListener('click', function () {
      OFFV.tab = t[0];
      OFFV.item = OFFV.event = '';
      OFFV.editing = OFFV.replying = '';
      OFFV.composing = false;
      OFFV.shown = LIST_STEP;
      drawTabs();
      drawTab();
    });
    tabs.appendChild(b);
  });
}

function tabCount(tab) {
  var p = OFF.parts;
  if (tab === 'outbox') return waiting().length;
  if (tab === 'decisions') return ((p.decisions && p.decisions.open) || []).filter(function (d) {
    return d.status === 'open' || d.status === 'failed';
  }).length;
  return 0;
}

function drawTab() {
  var pane = $('offPane');
  if (!pane) return;
  pane.textContent = '';
  var fn = { tasks: tasksTab, mail: mailTab, calendar: calendarTab, decisions: decisionsTab, people: peopleTab,
             chats: chatsTab, notes: notesTab, outbox: outboxTab }[OFFV.tab] || tasksTab;
  pane.appendChild(fn());
}

function empty(text) { return el('p', 'off-empty', text); }

function missing(part) {
  var m = OFF.meta.parts[part] || {};
  if (m.error) return empty('This device has no copy of this yet: ' + m.error);
  return empty(isOnline() ? 'This device has no copy of this yet. Refresh now makes one.'
    : 'This device has no copy of this: it was not made before the connection went.');
}

function back(text) {
  var b = el('button', 'off-back', '← ' + text);
  b.type = 'button';
  b.addEventListener('click', function () {
    OFFV.item = OFFV.event = '';
    OFFV.editing = OFFV.replying = '';
    OFFV.composing = false;
    drawTab();
  });
  return b;
}

function said(entry) {
  return entry ? 'Kept in the outbox: ' + (isOnline() ? 'sending now.' : 'it goes when this device is back online.')
    : '';
}

/* ---------------------------------------------------------------- tasks */

function tasksTab() {
  var wrap = el('div', 'off-sec');
  var part = OFF.parts.tasks;
  if (!part) return missing('tasks');
  var tasks = part.tasks || [];
  if (OFFV.item) {
    var t = tasks.filter(function (x) { return x.rel === OFFV.item || x.rel.split('/').pop() === OFFV.item.split('/').pop(); })[0];
    if (t) return taskOne(t);
  }
  var acts = el('div', 'off-acts');
  var add = el('button', 'ctl small', 'New task');
  add.type = 'button';
  add.addEventListener('click', function () { OFFV.composing = !OFFV.composing; drawTab(); });
  acts.appendChild(add);
  var browse = el('button', 'ctl small', 'Open the task browser');
  browse.type = 'button';
  browse.addEventListener('click', function () { offlineClose(); goToAddress('/tasks'); });
  acts.appendChild(browse);
  var whole = tasks.filter(function (x) { return x.whole; }).length;
  acts.appendChild(el('span', 'off-hint', whole + ' of ' + tasks.length + ' tasks whole on this device: every one the '
    + 'Control Room ranks above quiet, and every pinned one.'));
  wrap.appendChild(acts);
  if (part.why) wrap.appendChild(el('p', 'off-hint', part.why));
  if (OFFV.composing) wrap.appendChild(newTaskForm());
  // The ones kept whole first, pinned first among them, then the rest by when they moved.
  var sorted = tasks.slice().sort(function (a, b) {
    return (b.whole ? 1 : 0) - (a.whole ? 1 : 0) || (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0)
      || (b.changed || 0) - (a.changed || 0);
  });
  var list = el('ul', 'off-list');
  sorted.forEach(function (t) {
    var li = el('li', 'off-row' + (t.whole ? '' : ' off-thin'));
    var b = el('button', 'off-open');
    b.type = 'button';
    b.appendChild(el('span', 'off-num', t.number != null ? String(t.number) : ''));
    var main = el('span', 'off-main');
    main.appendChild(el('span', 'off-title', (t.pinned ? '★ ' : '') + t.name));
    main.appendChild(el('span', 'off-sub', [t.project, t.status, t.whole ? t.cluster : ''].filter(Boolean).join(' · ')));
    b.appendChild(main);
    if (!t.whole) b.appendChild(el('span', 'off-badge off-not', 'Not available offline'));
    b.addEventListener('click', function () { OFFV.item = t.rel; OFFV.editing = ''; drawTab(); });
    li.appendChild(b);
    list.appendChild(li);
  });
  wrap.appendChild(list);
  return wrap;
}

function newTaskForm() {
  var f = el('form', 'off-form');
  var title = field(f, 'Name of the task', 'input', '');
  var note = field(f, 'What it is about (optional)', 'textarea', '');
  var go = el('button', 'ctl small off-primary', 'Make it');
  go.type = 'submit';
  f.appendChild(go);
  f.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!title.value.trim()) { title.focus(); return; }
    offlineQueue('task', { title: title.value.trim(), note: note.value.trim() }, {}).then(function (entry) {
      notify('New task “' + title.value.trim() + '”. ' + said(entry), { tone: 'success' });
      OFFV.composing = false;
      drawTab();
    });
  });
  return f;
}

function taskOne(t) {
  var wrap = el('div', 'off-sec');
  wrap.appendChild(back('Every task'));
  wrap.appendChild(el('h4', 'off-h2', (t.number != null ? t.number + '. ' : '') + t.name));
  wrap.appendChild(el('p', 'off-line', [t.project, t.status, t.said].filter(Boolean).join(' · ')));
  if (!t.whole) {
    wrap.appendChild(empty('Not available offline. Only its name, status and project are on this device: it is '
      + 'not in a Control Room cluster above quiet, and it is not pinned.'));
    return wrap;
  }
  var acts = el('div', 'off-acts');
  var open = el('button', 'ctl small', 'Open its page');
  open.type = 'button';
  open.addEventListener('click', function () { offlineClose(); goToAddress('/task/' + t.rel); });
  acts.appendChild(open);
  if (t.cluster) acts.appendChild(el('span', 'off-hint', 'In the Control Room’s ' + t.cluster + ' (' + t.size + ')'));
  wrap.appendChild(acts);
  var where = (t.number != null ? t.number + '. ' : '') + t.name;
  (t.notes || []).forEach(function (n) { wrap.appendChild(noteBlock(n, where)); });
  var steps = t.step_list || [];
  if (steps.length) {
    wrap.appendChild(el('h5', 'off-h3', 'Steps'));
    steps.forEach(function (s) {
      var d = el('details', 'off-step');
      var sum = el('summary', null, (s.number ? s.number + ' ' : '') + (s.title || s.rel) + (s.state ? ' · ' + s.state : ''));
      d.appendChild(sum);
      var at = where + ', ' + (s.number || s.title || '');
      var go = el('button', 'ctl small', 'Open the step');
      go.type = 'button';
      go.addEventListener('click', function () { offlineClose(); goToAddress('/task/' + s.rel); });
      d.appendChild(go);
      if (s.note) d.appendChild(noteBlock(s.note, at));
      (s.notes || []).forEach(function (n) { d.appendChild(noteBlock(n, at)); });
      if (s.words) {
        d.appendChild(el('p', 'off-hint', 'The page’s words, to read. Open the step for the page itself.'));
        d.appendChild(el('div', 'off-text', s.words));
      }
      if (!s.note && !s.words && !(s.notes || []).length) d.appendChild(el('p', 'off-hint', 'It has no notes of its own.'));
      wrap.appendChild(d);
    });
  }
  return wrap;
}

/* One note of a task: read, or edited into the outbox with the version it started from. */
function noteBlock(n, where) {
  var box = el('section', 'off-note');
  var head = el('div', 'off-note-head');
  head.appendChild(el('span', 'off-note-name', n.name));
  var queued = OFF.box.filter(function (e) { return e.kind === 'page' && e.payload.path === n.path && (e.status === 'waiting' || e.status === 'sending'); });
  var text = queued.length ? queued[queued.length - 1].payload.text : n.text;
  if (queued.length) head.appendChild(el('span', 'off-badge', 'Edited offline, waiting to send'));
  if (n.editable && OFFV.editing !== n.path) {
    var edit = el('button', 'ctl small', 'Edit');
    edit.type = 'button';
    edit.addEventListener('click', function () { OFFV.editing = n.path; drawTab(); });
    head.appendChild(edit);
  }
  box.appendChild(head);
  if (OFFV.editing === n.path) {
    var f = el('form', 'off-form');
    var ta = el('textarea', 'off-input off-editor');
    ta.value = text;
    ta.setAttribute('aria-label', 'Edit ' + n.name);
    ta.rows = Math.min(28, Math.max(8, text.split('\n').length + 2));
    f.appendChild(ta);
    var acts = el('div', 'off-acts');
    var save = el('button', 'ctl small off-primary', 'Save');
    save.type = 'submit';
    var cancel = el('button', 'ctl small', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', function () { OFFV.editing = ''; drawTab(); });
    acts.appendChild(save);
    acts.appendChild(cancel);
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (ta.value === text) { OFFV.editing = ''; drawTab(); return; }
      // The base is what the device read from Rouh, even under an earlier edit still
      // waiting: the server merges from there, and two edits of mine never clash.
      offlineQueue('page', { path: n.path, text: ta.value, where: n.name + ', ' + (where || '') }, { version: n.version, text: n.text }).then(function (entry) {
        notify(n.name + ' saved. ' + said(entry), { tone: 'success' });
        OFFV.editing = '';
        drawTab();
      });
    });
    box.appendChild(f);
    setTimeout(function () { ta.focus(); }, 0);
  } else {
    box.appendChild(el('div', 'off-text', text || '(empty)'));
    if (n.cut) box.appendChild(el('p', 'off-hint', 'Cut short on this device; it is too long to edit offline.'));
  }
  return box;
}

/* ---------------------------------------------------------------- mail */

function mailTab() {
  var part = OFF.parts.mail;
  if (!part) return missing('mail');
  var msgs = part.messages || [];
  if (OFFV.item) {
    var m = msgs.filter(function (x) { return x.id === OFFV.item; })[0];
    if (m) return mailOne(m);
  }
  var wrap = el('div', 'off-sec');
  var acts = el('div', 'off-acts');
  var write = el('button', 'ctl small', 'New email');
  write.type = 'button';
  write.addEventListener('click', function () { OFFV.composing = !OFFV.composing; drawTab(); });
  acts.appendChild(write);
  // A day to start the list at, within the days this device keeps.
  var pick = /** @type {HTMLInputElement} */ (el('input', 'off-input off-date'));
  pick.type = 'date';
  pick.setAttribute('aria-label', 'Show email from this day back');
  pick.title = 'Show email from this day back';
  if (part.from) pick.min = isoDay(new Date(part.from * 1000));
  pick.max = isoDay(new Date());
  pick.value = OFFV.mailDay;
  pick.addEventListener('change', function () { OFFV.mailDay = pick.value; OFFV.shown = LIST_STEP; drawTab(); });
  acts.appendChild(pick);
  if (OFFV.mailDay) {
    var newest = el('button', 'ctl small', 'Newest');
    newest.type = 'button';
    newest.addEventListener('click', function () { OFFV.mailDay = ''; OFFV.shown = LIST_STEP; drawTab(); });
    acts.appendChild(newest);
  }
  wrap.appendChild(acts);
  wrap.appendChild(el('p', 'off-hint', msgs.length + ' emails from the last ' + (part.days || 30) + ' days, '
    + ((part.inboxes || []).length) + (part.inboxes && part.inboxes.length === 1 ? ' inbox' : ' inboxes')
    + ((part.inboxes || []).length ? ': ' + part.inboxes.join(', ') : '') + '.'));
  if (OFFV.composing) wrap.appendChild(composeForm(null));
  var from = OFFV.mailDay ? new Date(OFFV.mailDay + 'T23:59:59').getTime() / 1000 : Infinity;
  var shown = msgs.filter(function (m) { return (m.at || 0) <= from; });
  if (!shown.length) {
    wrap.appendChild(empty(part.why || (OFFV.mailDay ? 'No email from that day or before it is on this device.'
      : 'No email from those days is on this device.')));
    return wrap;
  }
  var list = el('ul', 'off-list');
  var lastDay = '';
  shown.slice(0, OFFV.shown).forEach(function (m) {
    var d = new Date((m.at || 0) * 1000).toDateString();
    if (d !== lastDay) {
      lastDay = d;
      list.appendChild(el('li', 'off-row off-dayhead', new Date((m.at || 0) * 1000)
        .toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })));
    }
    var li = el('li', 'off-row' + (m.unread ? ' unread' : ''));
    var b = el('button', 'off-open');
    b.type = 'button';
    var main = el('span', 'off-main');
    var top = el('span', 'off-title', (m.sent ? 'To ' + shortName(m.to) : shortName(m.from)));
    main.appendChild(top);
    main.appendChild(el('span', 'off-subject', m.subject || '(no subject)'));
    main.appendChild(el('span', 'off-sub', (m.snippet || '').slice(0, 140)));
    b.appendChild(main);
    b.appendChild(el('span', 'off-day', day(m.at)));
    b.addEventListener('click', function () { OFFV.item = m.id; OFFV.replying = ''; drawTab(); });
    li.appendChild(b);
    list.appendChild(li);
  });
  wrap.appendChild(list);
  if (shown.length > OFFV.shown) {
    var more = el('button', 'ctl small', 'Show ' + Math.min(LIST_STEP, shown.length - OFFV.shown) + ' older of '
      + (shown.length - OFFV.shown));
    more.type = 'button';
    more.addEventListener('click', function () { OFFV.shown += LIST_STEP; drawTab(); });
    wrap.appendChild(more);
  }
  return wrap;
}

function isoDay(d) {
  return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}

function shortName(addr) {
  var s = String(addr || '');
  var named = /^\s*"?([^"<]+?)"?\s*</.exec(s);
  return named ? named[1] : s.replace(/[<>]/g, '');
}

function addressOf(addr) {
  var got = /<([^>]+)>/.exec(String(addr || ''));
  return got ? got[1] : String(addr || '').trim();
}

function day(at) {
  if (!at) return '';
  var d = new Date(at * 1000);
  var now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
}

function mailOne(m) {
  var wrap = el('div', 'off-sec');
  wrap.appendChild(back('Every email'));
  var head = el('div', 'off-mail-head');
  head.appendChild(el('h4', 'off-h2', m.subject || '(no subject)'));
  head.appendChild(el('p', 'off-line', 'From ' + (m.from || '') + (m.to ? ' · to ' + m.to : '')));
  head.appendChild(el('p', 'off-hint', (m.date || '') + ' · in ' + (m.inbox || '')
    + (m.files && m.files.length ? ' · ' + m.files.length + ' attached: ' + m.files.join(', ') : '')));
  wrap.appendChild(head);
  wrap.appendChild(el('div', 'off-text off-mail-body', m.body || m.snippet || ''));
  if (m.cut) wrap.appendChild(el('p', 'off-hint', 'Cut short on this device.'));
  var acts = el('div', 'off-acts');
  var reply = el('button', 'ctl small off-primary', 'Reply');
  reply.type = 'button';
  reply.addEventListener('click', function () { OFFV.replying = m.id; drawTab(); });
  acts.appendChild(reply);
  wrap.appendChild(acts);
  if (OFFV.replying === m.id) wrap.appendChild(composeForm(m));
  return wrap;
}

/* A reply to `m`, or a new email with none. It is a draft in Rouh's mailbox unless Send
   is ticked and confirmed, the same press and confirmation the compose card asks for. */
function composeForm(m) {
  var f = el('form', 'off-form');
  var mine = m && m.whose === 'person';
  if (mine) {
    f.appendChild(el('p', 'off-hint', 'This came to your own mailbox, which Rouh reads and never writes, so your '
      + 'reply goes as a new email from Rouh’s mailbox.'));
  }
  var replyTo = m ? addressOf(m.sent ? m.to : (m.reply_to || m.from)) : '';
  var to = field(f, 'To', 'input', replyTo);
  var cc = field(f, 'Cc', 'input', m && !m.sent ? '' : '');
  var subject = field(f, 'Subject', 'input', m ? (/^re:/i.test(m.subject || '') ? m.subject : 'Re: ' + (m.subject || '')) : '');
  var body = field(f, 'Message', 'textarea', '');
  body.rows = 8;
  var sendLine = el('label', 'off-check');
  var send = el('input');
  send.type = 'checkbox';
  sendLine.appendChild(send);
  sendLine.appendChild(el('span', null, 'Send it when this device is back online, not just a draft'));
  f.appendChild(sendLine);
  var acts = el('div', 'off-acts');
  var go = el('button', 'ctl small off-primary', 'Save');
  go.type = 'submit';
  send.addEventListener('change', function () { go.textContent = send.checked ? 'Send when back online' : 'Save as a draft'; });
  go.textContent = 'Save as a draft';
  acts.appendChild(go);
  f.appendChild(acts);
  f.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!to.value.trim()) { to.focus(); return; }
    if (!body.value.trim()) { body.focus(); return; }
    var confirmed = false;
    if (send.checked) {
      // Sending cannot be undone, so it is confirmed now, by name, as it is online.
      confirmed = window.confirm('Send this to ' + to.value.trim() + ' as soon as this device is back online? '
        + 'It cannot be undone. Rouh still keeps it as a draft if anything newer has come in.');
      if (!confirmed) return;
    }
    var payload = { to: to.value.trim(), cc: cc.value.trim(), subject: subject.value.trim(), body: body.value,
                    send: send.checked, confirmed: confirmed };
    var kind = 'draft', base = {};
    if (m) {
      kind = 'reply';
      Object.assign(payload, { message_id: m.id, thread_id: m.thread_id, inbox: m.inbox, whose: m.whose });
      base = { last_id: lastInThread(m), last_at: m.at };
    }
    offlineQueue(kind, payload, base).then(function (entry) {
      notify((send.checked ? 'To be sent to ' : 'Draft to ') + payload.to + '. ' + said(entry), { tone: 'success' });
      OFFV.replying = '';
      OFFV.composing = false;
      drawTab();
    });
  });
  return f;
}

/* The newest email this device has of the thread, which is what the reply answers. */
function lastInThread(m) {
  var msgs = (OFF.parts.mail && OFF.parts.mail.messages) || [];
  var same = msgs.filter(function (x) { return x.thread_id && x.thread_id === m.thread_id && x.inbox === m.inbox; });
  same.sort(function (a, b) { return (b.at || 0) - (a.at || 0); });
  return (same[0] || m).id;
}

function field(form, label, tag, value) {
  var l = el('label', 'off-field');
  l.appendChild(el('span', 'off-label', label));
  var input = el(tag, 'off-input');
  if (tag === 'input') input.type = 'text';
  input.value = value || '';
  l.appendChild(input);
  form.appendChild(l);
  return input;
}

/* ---------------------------------------------------------------- calendar */

/* The calendar a week at a time, this week first: Earlier and Later move a week, a day picked
   goes to its week, and Today comes back. Pressing an event opens all of it. The device keeps
   thirty days either side of today, and the arrows stop where the copy does. */
function calendarTab() {
  var part = OFF.parts.calendar;
  if (!part) return missing('calendar');
  var events = part.events || [];
  if (OFFV.event) {
    var ev = events.filter(function (x) { return eventKey(x) === OFFV.event; })[0];
    if (ev) return eventOne(ev);
  }
  var wrap = el('div', 'off-sec');
  var first = weekStart(new Date());
  first.setDate(first.getDate() + 7 * OFFV.week);
  var last = new Date(first);
  last.setDate(last.getDate() + 7);
  var copyFrom = part.from ? part.from * 1000 : -Infinity;
  var copyTo = part.to ? part.to * 1000 : Infinity;
  var nav = el('div', 'off-acts off-weeknav');
  var earlier = el('button', 'ctl small', '‹ Earlier');
  earlier.type = 'button';
  earlier.setAttribute('aria-label', 'The week before');
  earlier.disabled = first.getTime() <= copyFrom;
  earlier.addEventListener('click', function () { OFFV.week -= 1; drawTab(); });
  var today = el('button', 'ctl small', 'Today');
  today.type = 'button';
  today.disabled = OFFV.week === 0;
  today.addEventListener('click', function () { OFFV.week = 0; drawTab(); });
  var later = el('button', 'ctl small', 'Later ›');
  later.type = 'button';
  later.setAttribute('aria-label', 'The week after');
  later.disabled = last.getTime() >= copyTo;
  later.addEventListener('click', function () { OFFV.week += 1; drawTab(); });
  var pick = /** @type {HTMLInputElement} */ (el('input', 'off-input off-date'));
  pick.type = 'date';
  pick.setAttribute('aria-label', 'Go to a day');
  pick.title = 'Go to a day';
  if (part.from) pick.min = isoDay(new Date(copyFrom));
  if (part.to) pick.max = isoDay(new Date(copyTo - 1));
  pick.value = OFFV.week ? isoDay(first) : '';
  pick.addEventListener('change', function () {
    if (!pick.value) return;
    var want = weekStart(new Date(pick.value + 'T12:00:00'));
    OFFV.week = Math.round((want.getTime() - weekStart(new Date()).getTime()) / (7 * 86400000));
    drawTab();
  });
  [earlier, today, later, pick].forEach(function (n) { nav.appendChild(n); });
  wrap.appendChild(nav);
  var lastDay = new Date(last);
  lastDay.setDate(lastDay.getDate() - 1);
  wrap.appendChild(el('h4', 'off-h2', first.toLocaleDateString([], { day: 'numeric', month: 'long' }) + ' – '
    + lastDay.toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' })));
  var inWeek = events.filter(function (e) {
    return evTo(e) >= first.getTime() && evAt(e) < last.getTime();
  });
  if (!events.length) {
    wrap.appendChild(empty(part.why || 'Nothing on the calendar in the days this device keeps.'));
    return wrap;
  }
  for (var i = 0; i < 7; i++) {
    var d = new Date(first);
    d.setDate(d.getDate() + i);
    var next = new Date(d);
    next.setDate(next.getDate() + 1);
    var on = inWeek.filter(function (e) {
      var at = evAt(e), to = evTo(e);
      return at < next.getTime() && (to > d.getTime() || at >= d.getTime());
    });
    var isToday = d.toDateString() === new Date().toDateString();
    var head = el('h5', 'off-h3' + (isToday ? ' off-today' : ''),
      d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }) + (isToday ? ' · Today' : ''));
    wrap.appendChild(head);
    if (!on.length) { wrap.appendChild(el('p', 'off-hint off-free', 'Nothing on.')); continue; }
    var list = el('ul', 'off-list');
    on.forEach(function (ev) {
      var li = el('li', 'off-row off-event' + (ev.declined ? ' declined' : ''));
      var b = el('button', 'off-open');
      b.type = 'button';
      b.appendChild(el('span', 'off-day', eventWhen(ev)));
      var main = el('span', 'off-main');
      main.appendChild(el('span', 'off-title', ev.title + (ev.declined ? ' (declined)' : '')));
      var bits = [ev.where, (ev.guests || []).map(function (g) { return g.name || g.email; }).slice(0, 6).join(', '), ev.calendar];
      main.appendChild(el('span', 'off-sub', bits.filter(Boolean).join(' · ')));
      b.appendChild(main);
      b.addEventListener('click', function () { OFFV.event = eventKey(ev); drawTab(); });
      li.appendChild(b);
      list.appendChild(li);
    });
    wrap.appendChild(list);
  }
  return wrap;
}

/* When an event starts and ends on this device's clock. An all-day one is its days, wherever
   the device is, not midnight where the server is. */
function evAt(e) {
  return e.all_day && /^\d{4}-\d\d-\d\d$/.test(e.start || '') ? new Date(e.start + 'T00:00:00').getTime()
    : (e.starts_at || 0) * 1000;
}
function evTo(e) {
  if (e.all_day && /^\d{4}-\d\d-\d\d$/.test(e.end || e.start || '')) {
    return new Date((e.end || e.start) + 'T23:59:59').getTime();
  }
  return (e.ends_at || e.starts_at || 0) * 1000;
}

function weekStart(d) {
  var out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  out.setDate(out.getDate() - ((out.getDay() + 6) % 7));
  return out;
}

function eventKey(ev) { return (ev.calendar_id || ev.calendar || '') + '|' + ev.id + '|' + ev.start; }

function eventWhen(ev) {
  if (ev.all_day) return 'All day';
  var t = function (s) { return new Date(s * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
  return t(ev.starts_at) + (ev.ends_at ? '–' + t(ev.ends_at) : '');
}

/* One event, whole. */
function eventOne(ev) {
  var wrap = el('div', 'off-sec');
  var b = el('button', 'off-back', '← The week');
  b.type = 'button';
  b.addEventListener('click', function () { OFFV.event = ''; drawTab(); });
  wrap.appendChild(b);
  wrap.appendChild(el('h4', 'off-h2', ev.title));
  var when = new Date(evAt(ev)).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  wrap.appendChild(el('p', 'off-line', when + ', ' + eventWhen(ev) + (ev.zone ? ' (' + ev.zone + ')' : '')));
  var facts = el('dl', 'off-facts');
  var put = function (k, v) {
    if (!v) return;
    facts.appendChild(el('dt', null, k));
    facts.appendChild(el('dd', null, v));
  };
  put('Where', ev.where);
  put('Calendar', ev.calendar);
  put('Organiser', ev.organiser_name ? ev.organiser_name + ' <' + ev.organiser + '>' : ev.organiser);
  put('Your answer', ev.my_response ? { accepted: 'Going', declined: 'Not going', tentative: 'Maybe',
    needsAction: 'Not answered yet' }[ev.my_response] || ev.my_response : '');
  put('Call', ev.video);
  wrap.appendChild(facts);
  if ((ev.guests || []).length) {
    wrap.appendChild(el('h5', 'off-h3', (ev.guests.length === 1 ? '1 guest' : ev.guests.length + ' guests')
      + (ev.guests_omitted ? ', and more Google left out' : '')));
    var list = el('ul', 'off-list');
    ev.guests.forEach(function (g) {
      var li = el('li', 'off-row');
      var main = el('span', 'off-main');
      main.appendChild(el('span', 'off-title', (g.name || g.email) + (g.organiser ? ' · organiser' : '')));
      main.appendChild(el('span', 'off-sub', [g.name ? g.email : '', { accepted: 'going', declined: 'not going',
        tentative: 'maybe', needsAction: 'not answered' }[g.response] || g.response, g.optional ? 'optional' : '']
        .filter(Boolean).join(' · ')));
      li.appendChild(main);
      list.appendChild(li);
    });
    wrap.appendChild(list);
  }
  if (ev.description) wrap.appendChild(el('div', 'off-text', ev.description));
  return wrap;
}

/* ---------------------------------------------------------------- decisions */

function decisionsTab() {
  var part = OFF.parts.decisions;
  if (!part) return missing('decisions');
  var wrap = el('div', 'off-sec');
  var open = (part.open || []).concat(part.snoozed || []);
  if (!open.length) return empty('Nothing is waiting on you.');
  if (!window.RouhDecision) return empty('The decisions could not be drawn.');
  var host = {
    act: function (id, what, body) {
      if (what === 'get') return Promise.resolve({ ok: true, status: 200, out: {} });
      return answerDecision(id, what, body).then(function (r) {
        if (r && r.ok) notify('Answered. ' + said(true), { tone: 'success' });
        return r;
      });
    },
    go: function (href) { offlineClose(); goToAddress(href); }
  };
  open.forEach(function (d, i) {
    wrap.appendChild(window.RouhDecision.card(d, host, { place: 'page', index: i + 1 }));
  });
  return wrap;
}

/* ---------------------------------------------------------------- people */

function peopleTab() {
  var part = OFF.parts.contacts;
  if (!part) return missing('contacts');
  var people = part.contacts || [];
  if (!people.length) return empty('No contacts are on this device.');
  var wrap = el('div', 'off-sec');
  var list = el('ul', 'off-list');
  people.slice().sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); }).forEach(function (p) {
    var li = el('li', 'off-row off-person');
    var main = el('span', 'off-main');
    main.appendChild(el('span', 'off-title', p.name || (p.emails || [])[0] || ''));
    if (p.organisation) main.appendChild(el('span', 'off-sub', p.organisation));
    var links = el('span', 'off-links');
    (p.emails || []).slice(0, 3).forEach(function (e) {
      var a = el('a', 'off-link', e);
      a.href = 'mailto:' + e;
      links.appendChild(a);
    });
    (p.phones || []).slice(0, 3).forEach(function (n) {
      var a = el('a', 'off-link', n);
      a.href = 'tel:' + n.replace(/[^+\d]/g, '');
      links.appendChild(a);
    });
    main.appendChild(links);
    li.appendChild(main);
    list.appendChild(li);
  });
  wrap.appendChild(list);
  return wrap;
}

/* ---------------------------------------------------------------- chats */

/* Every chat of the last two weeks, newest first, each with its forks under it, however deep,
   in the order they were made: a fork is an attachment to the chat it came off, never a chat
   in a list of its own (`rouh/forks.py`). */
function chatsTab() {
  var part = OFF.parts.chats;
  if (!part) return missing('chats');
  var chats = part.chats || [];
  if (OFFV.item) {
    var c = chats.filter(function (x) { return x.id === OFFV.item; })[0];
    if (c) return chatOne(c, chats);
  }
  var wrap = el('div', 'off-sec');
  var forks = chats.filter(function (x) { return x.fork_of; }).length;
  wrap.appendChild(el('p', 'off-hint', (chats.length - forks) + ' chats from the last ' + (part.days || 14)
    + ' days, whole, with ' + forks + (forks === 1 ? ' fork' : ' forks') + ' of them.'));
  var list = el('ul', 'off-list');
  chats.slice(0, OFFV.shown).forEach(function (c) {
    var li = el('li', 'off-row' + (c.fork_of ? ' off-fork' : ''));
    if (c.depth) li.style.paddingLeft = (12 + 18 * Math.min(c.depth, 4)) + 'px';
    var b = el('button', 'off-open');
    b.type = 'button';
    var main = el('span', 'off-main');
    main.appendChild(el('span', 'off-title', (c.fork_of ? '↳ ' : '') + (c.title || 'Untitled chat')));
    var last = (c.messages || [])[(c.messages || []).length - 1];
    main.appendChild(el('span', 'off-sub', (c.fork_of ? 'Fork · ' : '') + (c.messages || []).length + ' messages'
      + (c.cards && c.cards.length ? ' · ' + c.cards.length + ' cards' : '')
      + (last ? ' · ' + String(last.text || '').slice(0, 120) : '')));
    b.appendChild(main);
    b.appendChild(el('span', 'off-day', day(c.updated || (last && last.ts) || 0)));
    b.addEventListener('click', function () { OFFV.item = c.id; drawTab(); });
    li.appendChild(b);
    list.appendChild(li);
  });
  wrap.appendChild(list);
  if (chats.length > OFFV.shown) {
    var more = el('button', 'ctl small', 'Show ' + Math.min(LIST_STEP, chats.length - OFFV.shown) + ' more');
    more.type = 'button';
    more.addEventListener('click', function () { OFFV.shown += LIST_STEP; drawTab(); });
    wrap.appendChild(more);
  }
  return wrap;
}

/* One chat, whole, with its cards where they were drawn. A fork says which chat it came off,
   with what it carried of that chat folded above its own words, and every chat lists its forks
   at the end, each opening the same way. */
function chatOne(c, chats) {
  var wrap = el('div', 'off-sec');
  var parent = c.fork_of ? chats.filter(function (x) { return x.id === c.fork_of; })[0] : null;
  if (parent) {
    var up = el('button', 'off-back', '← ' + (parent.title || 'The chat it came off'));
    up.type = 'button';
    up.addEventListener('click', function () { OFFV.item = parent.id; drawTab(); });
    wrap.appendChild(up);
  } else {
    wrap.appendChild(back('Every chat'));
  }
  wrap.appendChild(el('h4', 'off-h2', c.title || 'Untitled chat'));
  if (c.fork_of) {
    wrap.appendChild(el('p', 'off-line', 'A fork of “' + (parent ? parent.title : 'another chat') + '”.'));
    if (parent) {
      var carried = (parent.messages || []).filter(function (m) { return !c.fork_at || (m.id || 0) <= c.fork_at; });
      if (carried.length) {
        var d = el('details', 'off-step off-carried');
        d.appendChild(el('summary', null, 'What it carried from “' + (parent.title || 'the chat') + '”: '
          + carried.length + (carried.length === 1 ? ' message' : ' messages')));
        carried.slice(-12).forEach(function (m) { d.appendChild(saidRow(m)); });
        wrap.appendChild(d);
      }
    }
  }
  var items = (c.messages || []).map(function (m) { return { at: m.ts || 0, id: m.id, m: m }; });
  (c.cards || []).forEach(function (card) {
    var after = items.filter(function (x) { return x.id === card.after_message_id; })[0];
    items.push({ at: after ? after.at + 0.5 : (card.at || 0), card: card });
  });
  items.sort(function (a, b) { return a.at - b.at; });
  if (!items.length) wrap.appendChild(empty('Nothing was said in it yet.'));
  items.forEach(function (x) {
    if (x.m) {
      wrap.appendChild(saidRow(x.m));
    } else if (x.card) {
      var card = el('div', 'off-card-copy');
      card.appendChild(el('div', 'off-card-title', (x.card.card_id ? '#' + x.card.card_id + ' ' : '') + (x.card.title || 'Card')));
      if (x.card.description) card.appendChild(el('p', 'off-hint', x.card.description));
      (x.card.blocks || []).forEach(function (b) {
        try {
          var node = renderBlock(b, x.card.card_id, true);
          if (node) card.appendChild(node);
        } catch (e) { /* a block this copy cannot draw is left out */ }
      });
      wrap.appendChild(card);
    }
  });
  var kids = chats.filter(function (x) { return x.fork_of === c.id; });
  if (kids.length) {
    wrap.appendChild(el('h5', 'off-h3', kids.length === 1 ? 'Its fork' : 'Its ' + kids.length + ' forks'));
    var list = el('ul', 'off-list');
    kids.forEach(function (k) {
      var li = el('li', 'off-row off-fork');
      var b = el('button', 'off-open');
      b.type = 'button';
      var main = el('span', 'off-main');
      main.appendChild(el('span', 'off-title', '↳ ' + (k.title || 'Untitled fork')));
      var asked = (k.messages || []).filter(function (m) { return m.role === 'user'; })[0];
      main.appendChild(el('span', 'off-sub', asked ? String(asked.text || '').slice(0, 160) : (k.messages || []).length + ' messages'));
      b.appendChild(main);
      b.addEventListener('click', function () { OFFV.item = k.id; drawTab(); });
      li.appendChild(b);
      list.appendChild(li);
    });
    wrap.appendChild(list);
  }
  return wrap;
}

function saidRow(m) {
  var p = el('div', 'off-said ' + (m.role === 'user' ? 'me' : 'rouh'));
  p.appendChild(el('span', 'off-who', (m.role === 'user' ? 'You' : 'Rouh') + (m.ts ? ' · ' + whenSaid(m.ts * 1000) : '')));
  var words = m.text || ((m.tools || []).length ? 'Used ' + m.tools.join(', ') + '.' : '');
  if (words) p.appendChild(el('div', 'off-text', words));
  if ((m.files || []).length) p.appendChild(el('p', 'off-hint', 'Attached: ' + m.files.join(', ')));
  return p;
}

/* ---------------------------------------------------------------- notes for Rouh */

function notesTab() {
  var wrap = el('div', 'off-sec');
  wrap.appendChild(el('p', 'off-hint', 'A note or a voice note becomes a message to Rouh in General when this device '
    + 'is back online, and Rouh answers it then.'));
  var f = el('form', 'off-form');
  var text = field(f, 'A note for Rouh', 'textarea', '');
  text.rows = 4;
  var acts = el('div', 'off-acts');
  var go = el('button', 'ctl small off-primary', 'Give it to Rouh');
  go.type = 'submit';
  acts.appendChild(go);
  f.appendChild(acts);
  f.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!text.value.trim()) { text.focus(); return; }
    offlineQueue('note', { text: text.value.trim() }, {}).then(function (entry) {
      notify('Note kept. ' + said(entry), { tone: 'success' });
      text.value = '';
      drawTab();
    });
  });
  wrap.appendChild(f);

  var voice = el('section', 'off-card off-voice');
  voice.appendChild(el('h4', 'off-h', 'Voice note'));
  var rec = OFFV.rec;
  var line = el('p', 'off-line', rec ? 'Recording… ' + secs(rec) : 'Record what you want to tell Rouh.');
  line.id = 'offRecLine';
  voice.appendChild(line);
  var vacts = el('div', 'off-acts');
  var start = el('button', 'ctl small' + (rec ? '' : ' off-primary'), rec ? 'Stop and keep it' : 'Record');
  start.type = 'button';
  start.addEventListener('click', function () { if (OFFV.rec) stopRecording(true); else startRecording(); });
  vacts.appendChild(start);
  if (rec) {
    var cancel = el('button', 'ctl small', 'Throw it away');
    cancel.type = 'button';
    cancel.addEventListener('click', function () { stopRecording(false); });
    vacts.appendChild(cancel);
  }
  voice.appendChild(vacts);
  wrap.appendChild(voice);

  var r = el('section', 'off-card off-reminder');
  r.appendChild(el('h4', 'off-h', 'Reminder'));
  var rf = el('form', 'off-form');
  var title = field(rf, 'Remind me to', 'input', '');
  var row2 = el('div', 'off-pair');
  rf.appendChild(row2);
  var date = field(row2, 'Day', 'input', '');
  date.type = 'date';
  var tomorrow = new Date(Date.now() + 86400000);
  date.value = tomorrow.toISOString().slice(0, 10);
  var time = field(row2, 'Time', 'input', '09:00');
  time.type = 'time';
  var racts = el('div', 'off-acts');
  var rgo = el('button', 'ctl small off-primary', 'Make the reminder');
  rgo.type = 'submit';
  racts.appendChild(rgo);
  rf.appendChild(racts);
  rf.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!title.value.trim()) { title.focus(); return; }
    var zone = '';
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { zone = ''; }
    offlineQueue('reminder', { title: title.value.trim(), what: title.value.trim(), date: date.value, time: time.value,
                               repeat: 'once', zone: zone }, {}).then(function (entry) {
      notify('Reminder kept. ' + said(entry), { tone: 'success' });
      title.value = '';
    });
  });
  r.appendChild(rf);
  wrap.appendChild(r);
  return wrap;
}

function secs(rec) {
  var s = Math.round((Date.now() - rec.at) / 1000);
  return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
}

/* The microphone is opened and closed only by the two functions that may (app/voice.js);
   while a note is recorded every frame is kept for it and none is heard as speech. */
function startRecording() {
  A.note = [];
  OFFV.rec = { at: Date.now(), timer: 0 };
  acquireMic().then(function () {
    if (!OFFV.rec) return;
    OFFV.rec.timer = window.setInterval(function () {
      var line = $('offRecLine');
      if (line && OFFV.rec) line.textContent = 'Recording… ' + secs(OFFV.rec);
      if (OFFV.rec && Date.now() - OFFV.rec.at > 180000) stopRecording(true);
    }, 500);
    drawTab();
  }, function (e) {
    A.note = null;
    OFFV.rec = null;
    notify('The microphone could not be opened: ' + (e && e.message ? e.message : e), { tone: 'warning' });
    drawTab();
  });
  drawTab();
}

function stopRecording(keepIt) {
  var rec = OFFV.rec;
  if (!rec) return;
  clearInterval(rec.timer);
  var frames = A.note || [];
  A.note = null;
  OFFV.rec = null;
  releaseMic();
  if (keepIt && frames.length) {
    var wav = wavOf(frames);
    var seconds = Math.round(frames.length * 320 / 16000);
    offlineQueue('note', { audio: wav, seconds: seconds }, {}).then(function (entry) {
      notify('Voice note of ' + seconds + ' s kept. ' + said(entry), { tone: 'success' });
      drawTab();
    });
  }
  if (OFFV.open && OFFV.tab === 'notes') drawTab();
}

/* 16 kHz mono 16-bit PCM, as a WAV, as base64: what the server's ears take. */
function wavOf(frames) {
  var n = 0;
  frames.forEach(function (f) { n += f.length; });
  var buf = new ArrayBuffer(44 + n * 2);
  var v = new DataView(buf);
  var put = function (at, s) { for (var i = 0; i < s.length; i++) v.setUint8(at + i, s.charCodeAt(i)); };
  put(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); put(8, 'WAVE'); put(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  put(36, 'data'); v.setUint32(40, n * 2, true);
  var at = 44;
  frames.forEach(function (f) { for (var i = 0; i < f.length; i++) { v.setInt16(at, f[i], true); at += 2; } });
  var bytes = new Uint8Array(buf);
  var s = '';
  for (var i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)));
  return btoa(s);
}

/* ---------------------------------------------------------------- the outbox */

function outboxTab() {
  var wrap = el('div', 'off-sec');
  var mine = OFF.box.slice().sort(function (a, b) { return b.made_at - a.made_at; });
  wrap.appendChild(el('h5', 'off-h3', 'From this ' + OFF.device.name));
  if (!mine.length) wrap.appendChild(empty('Nothing done offline on this device.'));
  var list = el('ul', 'off-list');
  mine.forEach(function (e) { list.appendChild(boxRow(e.label, e.status, e.result, e.made_at, '', e.kind)); });
  wrap.appendChild(list);
  var others = Object.keys(OFF.results).map(function (id) { return OFF.results[id]; })
    .filter(function (r) { return !OFF.box.some(function (e) { return e.id === r.id; }); })
    .sort(function (a, b) { return (b.updated_at || 0) - (a.updated_at || 0); });
  if (others.length) {
    wrap.appendChild(el('h5', 'off-h3', 'From your other devices'));
    var olist = el('ul', 'off-list');
    others.slice(0, 30).forEach(function (r) {
      olist.appendChild(boxRow(r.label || r.kind, r.status, r.result, (r.made_at || 0) * 1000, r.device || '', r.kind));
    });
    wrap.appendChild(olist);
  }
  return wrap;
}

function boxRow(label, status, result, at, device, kind) {
  var li = el('li', 'off-row off-box off-s-' + status);
  var main = el('span', 'off-main');
  main.appendChild(el('span', 'off-title', label || kind));
  main.appendChild(el('span', 'off-sub', [STATUS_WORDS[status] || status, result].filter(Boolean).join(': ')));
  li.appendChild(main);
  li.appendChild(el('span', 'off-day', (device ? device + ' · ' : '') + whenSaid(at)));
  if (status === 'clash' || status === 'held') {
    var go = el('button', 'ctl small', 'Open in Decisions');
    go.type = 'button';
    go.addEventListener('click', function () { offlineClose(); goToAddress('/decisions'); });
    li.appendChild(go);
  }
  return li;
}

/* ---------------------------------------------------------------- search */

function findBox() {
  var wrap = el('div', 'off-find');
  var input = el('input', 'off-input off-search');
  input.type = 'search';
  input.placeholder = 'Search everything on this device';
  input.setAttribute('aria-label', 'Search everything on this device');
  input.value = OFFV.find;
  input.addEventListener('input', function () {
    OFFV.find = input.value;
    drawFound();
  });
  wrap.appendChild(input);
  return wrap;
}

function drawFound() {
  var box = $('offFound');
  if (!box) return;
  box.textContent = '';
  var q = OFFV.find.trim().toLowerCase();
  if (q.length < 2) return;
  var words = q.split(/\s+/);
  var hit = function (text) {
    var t = String(text || '').toLowerCase();
    return words.every(function (w) { return t.indexOf(w) >= 0; });
  };
  var found = [];
  var p = OFF.parts;
  ((p.tasks && p.tasks.tasks) || []).forEach(function (t) {
    var notes = (t.notes || []).map(function (n) { return n.text; }).join(' ')
      + (t.step_list || []).map(function (s) { return [s.title, s.note && s.note.text, s.words].join(' '); }).join(' ');
    if (hit([t.number, t.name, t.said, t.status, notes].join(' '))) {
      found.push({ tab: 'tasks', item: t.rel, title: (t.number != null ? t.number + '. ' : '') + t.name, sub: 'Task', text: notes });
    }
  });
  ((p.mail && p.mail.messages) || []).forEach(function (m) {
    if (hit([m.from, m.to, m.subject, m.body].join(' '))) {
      found.push({ tab: 'mail', item: m.id, title: m.subject || '(no subject)', sub: 'Email from ' + shortName(m.from), text: m.body });
    }
  });
  ((p.calendar && p.calendar.events) || []).forEach(function (ev) {
    var guests = (ev.guests || []).map(function (g) { return g.name + ' ' + g.email; }).join(' ');
    if (hit([ev.title, ev.where, ev.description, guests].join(' '))) {
      found.push({ tab: 'calendar', item: '', event: eventKey(ev), title: ev.title, sub: 'Calendar, ' + new Date(ev.starts_at * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }), text: ev.where });
    }
  });
  ((p.decisions && p.decisions.open) || []).forEach(function (d) {
    if (hit([d.number ? 'decision ' + d.number + ' #' + d.number : '', d.title, d.question, d.context].join(' '))) {
      found.push({ tab: 'decisions', item: '', title: d.question || d.title, sub: d.number ? 'Decision ' + d.number : 'Decision', text: d.context });
    }
  });
  ((p.contacts && p.contacts.contacts) || []).forEach(function (c) {
    if (hit([c.name, c.organisation, (c.emails || []).join(' '), (c.phones || []).join(' ')].join(' '))) {
      found.push({ tab: 'people', item: '', title: c.name, sub: 'Person', text: (c.emails || []).join(', ') });
    }
  });
  ((p.chats && p.chats.chats) || []).forEach(function (c) {
    var all = (c.messages || []).map(function (m) { return m.text; }).join(' ')
      + (c.cards || []).map(function (k) { return k.title + ' ' + (k.description || ''); }).join(' ');
    if (hit([c.title, all].join(' '))) found.push({ tab: 'chats', item: c.id, title: c.title || 'Chat', sub: 'Chat', text: all });
  });
  box.appendChild(el('p', 'off-hint', found.length ? found.length + ' found on this device' : 'Nothing on this device matches.'));
  var list = el('ul', 'off-list');
  found.slice(0, 40).forEach(function (f) {
    var li = el('li', 'off-row');
    var b = el('button', 'off-open');
    b.type = 'button';
    var main = el('span', 'off-main');
    main.appendChild(el('span', 'off-title', f.title));
    main.appendChild(el('span', 'off-sub', f.sub + (f.text ? ' · ' + around(f.text, words[0]) : '')));
    b.appendChild(main);
    b.addEventListener('click', function () {
      OFFV.tab = f.tab;
      OFFV.item = f.item;
      OFFV.event = f.event || '';
      OFFV.find = '';
      draw();
    });
    li.appendChild(b);
    list.appendChild(li);
  });
  box.appendChild(list);
}

function around(text, word) {
  var t = String(text || '').replace(/\s+/g, ' ');
  var at = t.toLowerCase().indexOf(word);
  if (at < 0) return t.slice(0, 100);
  var from = Math.max(0, at - 40);
  return (from ? '…' : '') + t.slice(from, at + 80);
}

/* ---------------------------------------------------------------- wiring */

var closeBtn = $('offlineClose');
if (closeBtn) closeBtn.addEventListener('click', offlineClose);
var view = $('offlineView');
if (view) {
  view.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !e.defaultPrevented && !typing()) { e.preventDefault(); offlineClose(); }
  });
}

/* Offline as a section of Anatomy's Behaviour page (`/anatomy/behaviour/offline`, Meta's until
   4 November 2026): this page's first two
   cards as they are - whether there is a connection, what this device keeps and how, with
   Refresh, and what it holds kind by kind - drawn again whenever they change. The copy itself,
   to read and act on with no connection, stays here at /offline, where each kind's name goes. */

function panelDraw() {
  var box = $('offlinePanel');
  if (!box) return;
  box.textContent = '';
  [statusCard(), heldCard()].forEach(function (card) {
    card.removeAttribute('id');
    box.appendChild(card);
  });
}

window.RouhOfflinePanel = {
  shown: function () { PANEL.shown = true; panelDraw(); },
  hidden: function () { PANEL.shown = false; }
};

export { offlineClose, offlineOpen, offlinePaint, offlineViewing, OFFV };
