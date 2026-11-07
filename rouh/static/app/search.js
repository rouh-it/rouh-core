/* Rouh's page, search, over all five: the box over everything, the pills, the rows and what each row's menu does (section 10d of what was one app.js).
 *
 * Imports app/chats.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { chatById, CHATS, chatShow } from 'app/chats.js';
import { $, el, linkTo } from 'app/helpers.js';
import { notify } from 'app/notices.js';
import { send } from 'app/socket.js';
import { transcriptEl } from 'app/transcript.js';
import { openCardView, svgEl } from 'app/cards.js';
import { jobOpens, openTask, taskRecs } from 'app/tasks.js';
import { askDelete, canvasLoad, canvasStepPage, canvasTask, movedTell, OBJ, projectsOpen,
  railChats, railName, runKind, runsOpen, threadName } from 'app/runs.js';
import { ADDR, addrOf, addrTouch } from 'app/address.js';
import { chatIsWanted, sidebarDone } from 'app/controls.js';
import { geneGo, geneIcon } from 'app/navgroups.js';
import { openImage } from 'app/attachments.js';

/* ---------------------------------------------------------------- 10d */

/* Search, over everything there is.
 *
 * One box over the whole window, asked for on 22 September 2026. Under the
 * field the pills - All, Chats, Tasks, Projects, Artifacts, Runs, since
 * 24 September Files, and since 12 October Pages right after Tasks, the HTML
 * pages among the artifacts alone (`searching.PAGE`) - and under those one line per result: the type as a
 * glyph, the name, a little of what matched, and at the far end the date it
 * was last worked on.
 *
 * A file is the one row that is not an object. It is a file the person
 * uploaded, found by the words in it (`rouh/uploads.py`), and it opens as
 * the file itself: its row menu is Open and Open in new tab, and nothing
 * else, because that is all its `actions` say.
 *
 * **Nothing about a result is decided here.** What matched, what to show of
 * it and what pressing it does all come from `rouh/searching.py` in the
 * answer: a row carries an `open` instruction and this file carries it out.
 * That is deliberate - the five objects each open a different way, and a
 * copy of those rules in the browser is a copy that falls behind.
 *
 * The pills narrow what is already on the screen rather than asking again,
 * so pressing one is instant. The counts beside them are for the whole
 * answer and not for what is drawn, which is why All can say 68 while eight
 * rows are showing.
 *
 * The keys: the arrows move the highlight, Enter opens, Escape closes - and
 * closes a row's menu first where one is open. The right arrow opens the
 * highlighted row's menu, and while a menu is open its five numbers are live,
 * which is what the little squares beside its items mean. They are live only
 * then on purpose: a digit typed into the field belongs to the field, and
 * "45-12" and "task 30" are things people really search for.
 */

var FIND = {
  open: false, q: '', kind: 'all', rows: [], counts: null,
  at: -1, menu: -1, gen: 0, back: 0, timer: 0, wanted: null,
  // The question still waiting for its answer, by its `gen`, and the timer
  // that says so on the screen when the answer is slow (`findWaiting`).
  asked: 0, slow: 0,
  // The task number of each chat in the list shown before anything is
  // typed, by chat id, as the server last said (`search_labels`).
  labels: {}
};

// How long the box waits before asking. Long enough that a word typed at
// speed is one question rather than six, short enough that it feels like
// none: the answer itself comes back in about twenty milliseconds.
var FIND_WAIT = 110;

// How long an answer may take before the box says it is still searching,
// and before it says Rouh has not answered at all. The answer takes well
// under a second on the live data; past these something is wrong with the
// connection, and the person is told rather than left looking at a list
// that has nothing to do with what they typed (fr_7356fafcdd76).
var FIND_SLOW = 700;
var FIND_LOST = 8000;

var FIND_PILLS = ['all', 'chat', 'task', 'page', 'project', 'artifact', 'run', 'file'];

// What each of the five looks like on a row. Drawn rather than written,
// because a column of glyphs is scanned and a column of the words "chat",
// "task", "project" is read.
var FIND_ICON = {
  chat: ['M21 12a8 8 0 0 1-8 8H7l-4 3 1-5a8 8 0 1 1 17-6z'],
  task: ['M9 11l2.5 2.5L16 9', 'M4 5h16v14H4z'],
  project: ['M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
  artifact: ['M14 3v5h5', 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z',
             'M9 13h6M9 17h4'],
  // A page is a browser window, not a sheet: a page and an .md beside it
  // were the same sheet until 1 October 2026, when Petar asked for the pages
  // to look different and be the ones the eye lands on (fr_c72cbb0c4149).
  page: ['M3 6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
         'M3 9h18', 'M6 6.5h.01M8.5 6.5h.01', 'M7 13h10M7 16h6'],
  run: ['M4 6l5 5-5 5', 'M12 18h8'],
  // The same branch the Fork button and a fork's mark wear (`forkIcon`).
  fork: ['M6 20V4', 'M6 15c0-4.5 3.5-7 12-7', 'M15 5l3 3-3 3'],
  file: ['M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9']
};

// What the pill says, for the sentence under an empty list.
var FIND_WORD = {
  chat: 'chat', task: 'task', page: 'page', project: 'project',
  artifact: 'artifact', run: 'run', file: 'file'
};

// What a row's menu offers, unless the row says otherwise. A file says
// otherwise (`searching.FILE_ACTIONS`): it has nothing to pin, rename or
// delete from here.
var FIND_ACTIONS = ['open', 'tab', 'pin', 'rename', 'delete'];

function findCan(row, what) {
  var can = (row && Array.isArray(row.actions)) ? row.actions : FIND_ACTIONS;
  return can.indexOf(what) >= 0;
}

function findIcon(type) {
  var svg = svgEl('svg', {
    viewBox: '0 0 24 24', width: '16', height: '16', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.7',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true'
  });
  var paths = FIND_ICON[type] || FIND_ICON.artifact;
  for (var i = 0; i < paths.length; i++) svg.appendChild(svgEl('path', { d: paths[i] }));
  return svg;
}

/* The date at the end of a row: the time if it happened today, the day and
   the month this year, and the year as well before that. Short on purpose -
   it is the last column of a line that has to stay one line. */
function findWhen(at) {
  if (!at) return '';
  var d = new Date(at * 1000), now = new Date();
  var sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
  }
  /** @type {Intl.DateTimeFormatOptions} */
  var opts = { day: 'numeric', month: 'short' };
  if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString(undefined, opts);
}

/* The words that matched, picked out of a line. Built as text nodes and
   never as markup: what is in here is a person's own chat title. */
function findMark(host, text, words) {
  text = String(text == null ? '' : text);
  if (!text) return;
  var low = text.toLowerCase(), at = 0;
  while (at < text.length) {
    var best = -1, len = 0;
    for (var i = 0; i < words.length; i++) {
      var w = String(words[i] || '').toLowerCase();
      if (!w) continue;
      var found = low.indexOf(w, at);
      if (found >= 0 && (best < 0 || found < best)) { best = found; len = w.length; }
    }
    if (best < 0) { host.appendChild(document.createTextNode(text.slice(at))); return; }
    if (best > at) host.appendChild(document.createTextNode(text.slice(at, best)));
    host.appendChild(el('span', 'hit', text.slice(best, best + len)));
    at = best + len;
  }
}

function findWords() {
  return String(FIND.q || '').split(/\s+/).filter(function (w) { return !!w; });
}

/* ---------- opening and closing the box ---------- */

function findShow(on) {
  var dlg = $('searchDialog'), box = $('findInput');
  if (!dlg || !box) return;
  on = !!on;
  if (on === FIND.open) { if (on) box.focus(); return; }
  FIND.open = on;
  var btn = $('searchBtn');
  if (btn) btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  if (!on) {
    findMenuShow(false);
    try { dlg.close(); } catch (err) { dlg.removeAttribute('open'); }
    return;
  }
  try { dlg.showModal(); } catch (err) { dlg.setAttribute('open', ''); }
  // Every opening starts at All. A pill is a way of narrowing the answer in
  // front of you, not a setting: coming back a day later and being told
  // "nothing here is a task" because that is what you pressed last time is a
  // papercut every single time.
  FIND.kind = 'all';
  box.value = FIND.q;
  box.focus();
  box.select();
  // The sidebar is navigation and this is the way past it: on a screen it
  // was lying over, it has nothing left to do.
  sidebarDone();
  findAsk(true);
}

/* ---------- asking ---------- */

function findAsk(now) {
  if (FIND.timer) { clearTimeout(FIND.timer); FIND.timer = 0; }
  if (!FIND.q) {
    findWaiting(0);
    FIND.rows = findRecent(); FIND.counts = null; FIND.at = -1; findDraw();
    findAskLabels();
    return;
  }
  // The list on the screen stops being the answer the moment the words
  // change, so it says so at once: the latest chats' heading goes, and the
  // rows fade until the answer to these words replaces them.
  findStale(true);
  if (!now) { FIND.timer = setTimeout(function () { FIND.timer = 0; findAsk(true); }, FIND_WAIT); return; }
  FIND.gen++;
  // A question that could not leave this page is not one to wait for. Until
  // 22 October 2026 it went nowhere and said nothing, and the box went on
  // showing the latest chats under whatever was typed (fr_7356fafcdd76). It
  // is asked again the moment the connection is back (`findReconnected`).
  if (!send({ type: 'search', q: FIND.q, kind: FIND.kind, gen: FIND.gen })) {
    findWaiting(0);
    FIND.asked = FIND.gen;
    findSaid('Not connected to Rouh. It searches as soon as it is back.', true);
    return;
  }
  findWaiting(FIND.gen);
}

/* The answer to `gen` is on its way, or nothing is (0). Slow, the box says it
   is searching; lost, it says Rouh has not answered, and typing again or the
   connection coming back asks again. */
function findWaiting(gen) {
  if (FIND.slow) { clearTimeout(FIND.slow); FIND.slow = 0; }
  FIND.asked = gen;
  if (!gen) return;
  FIND.slow = setTimeout(function () {
    if (FIND.asked !== gen || !FIND.open) return;
    findSaid('Searching…', false);
    FIND.slow = setTimeout(function () {
      FIND.slow = 0;
      if (FIND.asked !== gen || !FIND.open) return;
      findSaid('Rouh has not answered. Type again to search again.', true);
    }, FIND_LOST - FIND_SLOW);
  }, FIND_SLOW);
}

/* The rows on the screen are not the answer to the words in the field. */
function findStale(on) {
  var host = $('findList'), head = $('findHead');
  if (host) host.classList.toggle('is-stale', !!on);
  if (on && head) head.hidden = true;
}

/* The socket is open again. A question asked while it was down, or lost
   with it, is asked again rather than left unanswered. */
function findReconnected() {
  if (FIND.open && FIND.q && FIND.asked) findAsk(true);
}

/* The numbers for the list before anything is typed. It is drawn from the
   chats this page already holds, which do not carry the number of the task
   each is about, so it is drawn at once with whatever numbers were known
   and drawn again when the server has said (`searching.labels`). Until 4
   October 2026 it never asked, and not one row had a number
   (fr_a898cf088d57). */
function findAskLabels() {
  var ids = [], i;
  for (i = 0; i < FIND.rows.length; i++) {
    if (FIND.rows[i].type === 'chat') ids.push(FIND.rows[i].id);
  }
  if (ids.length) send({ type: 'search_labels', kind: 'chat', ids: ids });
}

/** @param {import('./protocol').FromServer<'search_labels'>} m */
function findLabels(m) {
  if (!m || m.kind !== 'chat') return;
  FIND.labels = m.labels || {};
  if (!FIND.open || FIND.q) return;
  var at = FIND.at;
  FIND.rows = findRecent();
  FIND.at = at < FIND.rows.length ? at : -1;
  findDraw();
}

/* An answer. Thrown away unless it is the answer to the word in the field
   now: a box is typed into faster than a query comes back, and an older
   answer landing last is a list that does not match what is on the screen. */
/** @param {import('./protocol').FromServer<'search_results'>} m */
function findAnswer(m) {
  if (!m || Number(m.gen || 0) !== FIND.gen) return;
  findWaiting(0);
  FIND.rows = findFolded(Array.isArray(m.results) ? m.results : []);
  FIND.counts = m.counts || null;
  FIND.at = FIND.rows.length ? 0 : -1;
  findDraw();
}

/* Each fork found, as a line of its own under the chat it hangs off. The
   server folds them there (`searching._fold_forks`): a fork is a side
   question of one chat and not a chat of its own, so it is never a row
   among the others. Each is still a row of the list to the keys and to a
   screen reader, so Up and Down step onto it and Enter opens it - the fork
   itself, at the message that matched. Opening is all it offers: pinning,
   renaming and deleting are the chat's. */
function findFolded(rows) {
  var out = [], i, k, row, f;
  for (i = 0; i < rows.length; i++) {
    row = rows[i];
    out.push(row);
    if (!Array.isArray(row.forks)) continue;
    for (k = 0; k < row.forks.length; k++) {
      f = row.forks[k];
      out.push({
        type: 'chat', branch: true, id: f.id, title: f.title, label: '',
        snippet: f.snippet || '', at: f.at, why: f.why, open: f.open, url: f.url,
        under: findName(row), actions: ['open', 'tab']
      });
    }
  }
  return out;
}

/* ---------- drawing ---------- */

function findDraw() {
  var host = $('findList');
  if (!host) return;
  findMenuShow(false);
  var words = findWords(), i;

  for (i = 0; i < FIND_PILLS.length; i++) {
    var pill = $('findPills').children[i];
    if (!pill) continue;
    var mine = FIND_PILLS[i] === FIND.kind;
    pill.classList.toggle('on', mine);
    pill.setAttribute('aria-selected', mine ? 'true' : 'false');
    var count = pill.querySelector('.find-count');
    var n = FIND.counts ? Number(FIND.counts[FIND_PILLS[i]] || 0) : -1;
    count.hidden = n < 0;
    count.textContent = n < 0 ? '' : String(n);
  }
  findPillInView();

  host.textContent = '';
  host.classList.remove('is-stale');
  for (i = 0; i < FIND.rows.length; i++) host.appendChild(findRow(FIND.rows[i], i, words));
  var head = $('findHead');
  if (head) head.hidden = !!FIND.q || !FIND.rows.length;
  findSaid(findEmptyWords(), false);
  findKeepOnScreen();
}

/* The pill that is on is always one you can see. On a phone the pills are a
   row that scrolls sideways, and it kept wherever it was last left: every
   opening starts at All again, so the next opening showed Tasks and Runs
   with All, the one that was on, scrolled off the left edge. */
function findPillInView() {
  var row = $('findPills'), pill = row && row.querySelector('.find-pill.on');
  if (!pill || row.scrollWidth <= row.clientWidth) return;
  var box = row.getBoundingClientRect(), at = pill.getBoundingClientRect();
  var pad = 12;
  if (at.left < box.left + pad) row.scrollLeft -= box.left + pad - at.left;
  else if (at.right > box.right - pad) row.scrollLeft += at.right - (box.right - pad);
}

/* The chats, latest first, before anything is typed.

   The sidebar listed every chat until 30 September 2026, when Petar asked
   for that list to go: he gets to the work through the task browser. A
   chat that is not a task's has no page in the task browser, though, so
   this is where it is found now, on the one press that is already the way
   past navigation. General first, then what is pinned, then the rest by
   when each was last used (`railChats`). A task's own chats are here too,
   each with its task's number in front: they were left to the words typed
   until 4 October 2026, which left only the chats in no task, and so not one
   number on the list Petar opened (fr_a898cf088d57, then fr_73496cfea391).
   On the Chats pill and on All; the other pills are about something else. */
function findRecent() {
  if (FIND.kind !== 'all' && FIND.kind !== 'chat') return [];
  var all = railChats(), out = [], i, c, general;
  for (i = 0; i < all.length; i++) {
    c = all[i];
    general = c.id === CHATS.general;
    out.push({
      type: 'chat', id: c.id, title: railName(c),
      label: general ? '' : FIND.labels[c.id] || findFolderNumber(c.task),
      pinned: !general && !!c.pinned,
      snippet: general ? 'The main chat'
        : c.messages ? c.messages + (c.messages === 1 ? ' message' : ' messages')
          : 'Nothing said yet',
      at: Number(c.updated_at) || 0,
      url: addrOf('chat', c.id),
      open: { how: 'chat', id: c.id },
      // General is the one chat that cannot be pinned, renamed or deleted.
      actions: general ? ['open', 'tab'] : null
    });
  }
  return out;
}

/* The number a task's folder says it is, the way `searching.number_of_folder`
   reads it: 85 out of `rouh/assistant/85.rouh-memory`, 62-16 out of
   `.../62.rouh/62-16.sharing...`, and 11-01 for a step that says only its
   own place under 11. So a task's chat wears its number the moment the list
   is drawn, before the server has said (`findLabels`). */
function findFolderNumber(folder) {
  var parts = String(folder || '').replace(/^\/+|\/+$/g, '').split('/');
  var said = [], i, m, name;
  for (i = 0; i < parts.length; i++) {
    m = /^(\d+(?:-\d+)*)(?=[.-]|$)/.exec(parts[i]);
    if (m) said.push(m[1]);
  }
  if (!said.length) return '';
  name = said[said.length - 1];
  for (i = said.length - 2; i >= 0; i--) {
    if (name.indexOf(said[i] + '-') === 0) break;
    name = said[i] + '-' + name;
  }
  return name;
}

function findEmptyWords() {
  if (!FIND.q) return FIND.rows.length ? '' : 'Type to search everything you have.';
  if (FIND.rows.length) return '';
  if (FIND.kind !== 'all' && FIND.counts && FIND.counts.all) {
    return 'Nothing here is a ' + (FIND_WORD[FIND.kind] || FIND.kind)
      + ', but All has ' + FIND.counts.all + '.';
  }
  return 'Nothing matches “' + FIND.q + '”.';
}

function findSaid(words, bad) {
  var said = $('findSaid');
  if (!said) return;
  said.textContent = words || '';
  said.classList.toggle('bad', !!bad);
  said.hidden = !words;
}

function findRow(row, i, words) {
  // A link to what it opens, the same address Open in new tab in its menu
  // opens, so Cmd-click and the browser's own menu take it to a tab too
  // (`linkTo`). Still an option of the list to the keys and a screen reader.
  var node = el('a', 'find-row' + (i === FIND.at ? ' on' : ''));
  node.setAttribute('role', 'option');
  linkTo(node, findCan(row, 'tab') && row.url ? row.url : '');
  node.setAttribute('aria-selected', i === FIND.at ? 'true' : 'false');
  node.setAttribute('data-i', String(i));

  // A page wears its own icon and stands out from the other artifacts
  // (`searching.is_page`, `.find-row.is-page`).
  if (row.page) node.classList.add('is-page');
  // A fork, under the chat it hangs off (`findFolded`).
  if (row.branch) node.classList.add('is-branch');
  var icon = el('span', 'find-icon');
  // One of Rouh's own pages wears the glyph its link in the navigation wears
  // (`searching.gene_lines`, the gene registry).
  icon.appendChild((row.type === 'gene' && geneIcon(row.id)) ||
    findIcon(row.page ? 'page' : row.branch ? 'fork' : row.type));
  icon.title = row.type === 'gene' ? 'page in Rouh' : row.page ? 'page' : row.branch ? 'fork' : row.type;
  node.appendChild(icon);

  // The number of the task this is, or is in, in a column of its own in
  // front of the name: every row wears one, because everything here is
  // somewhere in the task browser (`searching._label`). A row in no task
  // keeps the column empty, so the names still start in one line.
  var num = el('span', 'find-num');
  findMark(num, findLabel(row), words);
  node.appendChild(num);

  var name = el('span', 'find-name');
  findMark(name, findTitle(row), words);
  node.appendChild(name);

  // Found and still archived: opening it is fine, and the person should
  // know it is not on the live list before they do.
  if (row.archived) node.appendChild(el('span', 'find-tag', 'Archived'));
  if (row.branch) node.appendChild(el('span', 'find-tag', 'Fork'));

  // Kept, and it says the same thing on all five now. A task used to be born
  // pinned, so the mark was left off a task row to save a column of identical
  // marks saying nothing; since 22 September 2026 the pin is the person's own
  // on every type, and a task wears it like anything else.
  if (row.pinned) {
    var pin = el('span', 'find-pin', '📌');
    pin.title = 'Pinned';
    node.appendChild(pin);
  }

  var snip = el('span', 'find-snip');
  findMark(snip, row.snippet || '', words);
  node.appendChild(snip);

  node.appendChild(el('span', 'find-when', findWhen(row.at)));

  var acts = el('span', 'find-acts');
  var dots = el('button', 'find-dots', '⋯');
  dots.type = 'button';
  dots.setAttribute('data-act', 'menu');
  dots.setAttribute('aria-haspopup', 'menu');
  dots.setAttribute('aria-expanded', 'false');
  dots.setAttribute('aria-label', 'What to do with ' + findName(row));
  acts.appendChild(dots);
  var go = el('button', 'find-enter', '↵');
  go.type = 'button';
  go.setAttribute('data-act', 'open');
  go.setAttribute('aria-label', 'Open ' + findName(row));
  acts.appendChild(go);
  node.appendChild(acts);

  node.title = findName(row) + (row.snippet && row.snippet !== row.where
    ? '\n' + row.snippet : '') + (row.where ? '\n' + row.where : '');
  return node;
}

// The number a row is drawn with: the task's it is, or is in
// (`searching._label`), and the row's own number from before there was one.
function findLabel(row) {
  if (!row) return '';
  if (row.label) return String(row.label);
  return row.number != null ? String(row.number) : '';
}

// The name on a row, without that number - unless the name is nothing but
// the number, or starts with it. A task taken in from a folder is named
// from the folder, so `30.jarvis` is the task "30 Jarvis", and the column
// in front already says 30.
function findTitle(row) {
  var title = String((row && row.title) || '');
  var n = findLabel(row);
  if (!n || title === n) return title;
  if (title.indexOf(n + ' ') === 0 || title.indexOf(n + '.') === 0) {
    return title.slice(n.length + 1).replace(/^\s+/, '') || title;
  }
  return title;
}

// The whole name, number and all, for what a row is called out loud: its
// tooltip, the menu's label for a screen reader, and the delete dialog.
function findName(row) {
  if (row && row.branch) return 'the fork ' + findTitle(row) + ' of ' + row.under;
  var n = findLabel(row), title = findTitle(row);
  return n && title !== n ? n + ' ' + title : title;
}

function findMove(step) {
  if (!FIND.rows.length) return;
  var was = FIND.at;
  FIND.at = (FIND.at + step + FIND.rows.length) % FIND.rows.length;
  findPaint(was);
  findKeepOnScreen();
}

function findPaint(was) {
  var host = $('findList');
  if (!host) return;
  var nodes = host.children;
  if (was >= 0 && nodes[was]) {
    nodes[was].classList.remove('on');
    nodes[was].setAttribute('aria-selected', 'false');
  }
  if (FIND.at >= 0 && nodes[FIND.at]) {
    nodes[FIND.at].classList.add('on');
    nodes[FIND.at].setAttribute('aria-selected', 'true');
  }
}

function findKeepOnScreen() {
  var host = $('findList');
  if (!host || FIND.at < 0) return;
  var node = host.children[FIND.at];
  if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
}

/* ---------- the row menu ---------- */

function findMenuShow(on, i) {
  var menu = $('findMenu'), host = $('findList');
  if (!menu) return;
  var dots = host ? host.querySelectorAll('.find-dots') : [];
  for (var k = 0; k < dots.length; k++) dots[k].setAttribute('aria-expanded', 'false');
  if (!on) { menu.hidden = true; FIND.menu = -1; return; }
  var row = FIND.rows[i];
  if (!row) return;
  FIND.menu = i;
  RouhMenu.label($('findPin'), row.pinned ? 'Un-pin' : 'Pin');
  RouhMenu.icon($('findPin'), row.pinned ? 'unpin' : 'pin');
  // Only what this row can do. The rule over Delete goes with Delete.
  var items = menu.querySelectorAll('.menu-item');
  for (var n = 0; n < items.length; n++) {
    items[n].hidden = !findCan(row, items[n].getAttribute('data-do'));
  }
  var rule = menu.querySelector('.menu-rule');
  if (rule) rule.hidden = !findCan(row, 'delete');
  menu.hidden = false;
  var anchor = host.children[i];
  var button = anchor ? anchor.querySelector('.find-dots') : null;
  if (button) button.setAttribute('aria-expanded', 'true');
  // Its right edge under the dots, which are at the right end of the row.
  RouhMenu.place(menu, button || anchor, 'end');
}

/* ---------- what a row does ---------- */

var FIND_KEYS = { '1': 'open', '2': 'tab', '3': 'pin', '4': 'rename', '5': 'delete' };

function findAct(what, i) {
  var row = FIND.rows[i];
  if (!row || !findCan(row, what)) return;
  if (what === 'open') { findMenuShow(false); findGo(row); return; }
  if (what === 'tab') {
    findMenuShow(false);
    window.open(row.url, '_blank', 'noopener');
    return;
  }
  if (what === 'pin') {
    findMenuShow(false);
    send({ type: 'pin_object', kind: row.type, id: row.id, on: !row.pinned });
    return;
  }
  if (what === 'rename') {
    findMenuShow(false);
    var said = window.prompt('What should this be called?', row.title || '');
    if (said == null) return;
    send({ type: 'rename_object', kind: row.type, id: row.id, title: said });
    return;
  }
  if (what === 'delete') {
    findMenuShow(false);
    // The one delete dialog every cross on this page opens: it names the
    // thing, says what else goes with it counted by the server off the very
    // links the delete walks, and leaves its button disabled until that
    // sentence has arrived. A search result deletes exactly the way
    // everything else does, cascade and all (`askDelete`).
    askDelete(row.type, row.id, findName(row));
  }
}

/* Opening one, whatever it is. The instruction came with the row
   (`searching._open`), so this is four short cases and no rules of its own. */
function findGo(row) {
  if (!row) return;
  var how = (row.open && row.open.how) || 'none';
  findShow(false);
  // What the server just said this folder is. A task and a project are both
  // a page on the canvas and both are addressed by their folder, so the
  // address bar has to know which word to put in front of it. It works that
  // out from the projects the rail already holds (`addrIsProject`), and
  // that list can still be on its way on the load that opened this very
  // address - so what the server said is kept, and believed first.
  if (how === 'task' && row.open.task) ADDR.kinds[row.open.task] = row.type;
  if (how === 'chat') { findMsgWant(row.open); chatShow(row.open.id); return; }
  /* The page first and the conversation after it, which is the order
     `openTaskThread` keeps when the same task is pressed in the rail.
     Loading a page takes the conversation by itself (`tasksHold`), so a
     conversation asked for before the load is folded away again by it, and
     a task opened from a link landed in a different layout from the same
     task opened from a row. They are one layout now.

     A project is the one that really does take the window: it is a page to
     browse and has no conversation of its own, and pressing it in the rail
     has always opened it that way (`pinnedProjectRow`). */
  if (how === 'task') {
    canvasTask(row.open.task);
    if (row.type !== 'project') chatIsWanted();
    return;
  }
  // A step opens to its own page, the same as a press on it anywhere else
  // (`openStepItem`), and a reload of that page's address lands back on it.
  if (how === 'step') { canvasStepPage(row.open.step); chatIsWanted(); return; }
  // Something inside a task or a project - a note, a folder, a page - which
  // only an address asks for (`searching._inside_line`). Exactly what the
  // press on its line loaded, laid out as the object it is in is laid out.
  if (how === 'page') {
    // What the folder is, which for a task's own page or document is the
    // task, whatever the row is drawn as (`searching._doc_line`).
    var over = row.open.kind || row.type;
    ADDR.kinds[row.open.task] = over;
    canvasLoad(row.open.page);
    if (over !== 'project') chatIsWanted();
    return;
  }
  // A card, a page, a document: the artifact itself, on its own layer over
  // the canvas. It used to be whatever owned it, which for every card on a
  // task's page was that page again (`searching._open`).
  if (how === 'card') { openCardView(row.open.id); return; }
  if (how === 'run') { findGoRun(row.open.id); return; }
  if (how === 'projects') { projectsOpen(); return; }
  if (how === 'file') { findGoFile(row.open, row.title); return; }
  if (how === 'gene') { geneGo(row.open.id); return; }
  notify('There is nothing built to open for “' + findName(row)
    + '” yet.', { tone: 'info' });
}

/* The message a search matched, in the chat it opens: the row carries it
   (`searching._message_of`) and the chat, once it is on the screen, is
   scrolled to it and lights it for a moment, so a fork or a chat found by
   something said halfway up is opened there and not at its end. Kept until
   that chat's `chat_switched` arrives, and only for a little while: a
   switch that never comes must not throw some later chat about. */
var FIND_MSG_WAIT = 15000;

function findMsgWant(open) {
  FIND.msg = open && open.msg ? { chat: open.id, msg: Number(open.msg),
    ex: Number(open.ex) || 0, words: findWords(),
    until: Date.now() + FIND_MSG_WAIT } : null;
}

function findMsgReveal(chatId) {
  var want = FIND.msg;
  if (!want) return;
  if (want.chat !== chatId) {
    if (Date.now() > want.until) FIND.msg = null;
    return;
  }
  FIND.msg = null;
  var sel = '.turn[data-msg="' + want.msg + '"], .turn[data-msgs~="' + want.msg + '"]';
  // A turn drawn live, and kept as it was along a strip (`forkPark`), has
  // only its exchange: then it is the one of that exchange that says the
  // words, or the exchange's question.
  function turn() {
    var t = transcriptEl();
    if (!t) return null;
    var at = t.querySelector(sel);
    if (at || !want.ex) return at;
    var of = t.querySelectorAll('.turn[data-root="' + want.ex + '"]'), i, k, said;
    for (i = of.length - 1; i >= 0; i--) {
      said = String(of[i].textContent || '').toLowerCase();
      for (k = 0; k < want.words.length; k++) {
        if (said.indexOf(String(want.words[k]).toLowerCase()) < 0) break;
      }
      if (k === want.words.length) return of[i];
    }
    return of[0] || null;
  }
  function there() {
    var at = turn();
    if (at && at.scrollIntoView) at.scrollIntoView({ block: 'center' });
    return at;
  }
  // After the frame the transcript is drawn in, and once more after what
  // is read back with it - its cards - has had its moment to push the
  // conversation to its end.
  requestAnimationFrame(function () {
    var at = there();
    if (!at) return;
    at.classList.add('found-turn');
    setTimeout(there, 400);
    setTimeout(function () { at.classList.remove('found-turn'); }, 2600);
  });
}

/* A file the person uploaded, opened as the file itself and never as the
   words read out of it: a picture in the same viewer a press on it in the
   conversation opens, a PDF or plain text in a tab of its own, and anything
   a browser would not show on this address handed over as the download it
   is, without a blank tab left behind. Which of the three is the server's
   answer (`uploads._shown_as`), not this file's. */
function findGoFile(open, name) {
  if (!open || !open.url) return;
  if (open.as === 'picture') { openImage(open.url, name); return; }
  if (open.as === 'tab') { window.open(open.url, '_blank', 'noopener'); return; }
  var a = document.createElement('a');
  a.href = open.url;
  a.download = name || '';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

//: A run asked for by its own address before the rail's list of runs had
//: arrived. A page opened at `/run/<id>` asks for it the moment the socket
//: is up, which is before the first snapshot of the runs has landed, so the
//: ask is held here and tried again when it does (`runsArrived`).
var RUN_WANTED = '';

/* A run opens where a run lives: on the task list, and for a run of the one
   program that means its terminal on the canvas, which is what pressing its
   row does (`openTask`). A run the list has forgotten says so rather than
   opening nothing. */
function findGoRun(id) {
  var rec = taskRecs[id];
  if (!rec) { RUN_WANTED = id; return; }
  RUN_WANTED = '';
  // Opened, and never closed. Pressing the deploy card toggles it, which is
  // right for a press and wrong for an address: a run reached by its own
  // link has to end up open whether or not its card already was. A run and
  // one of Rouh's own jobs both open on the canvas, which never closes on a
  // second press.
  if (rec.mode === 'one' || jobOpens(rec) || !rec.open) openTask(rec);
  // Any other run opens on its card, on the runs page.
  if (rec.mode !== 'one' && !jobOpens(rec)) {
    runsOpen(runKind(rec));
    var host = $('tasksList'), nodes = host ? host.children : [];
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute('data-id') === String(id) && nodes[i].scrollIntoView) {
        nodes[i].scrollIntoView({ block: 'nearest' });
        break;
      }
    }
  }
}

/* The rail's runs have arrived, which is where a run asked for by its own
   address before there was a list lands. Only a whole snapshot is allowed
   to give up on one: a single run's own message says nothing about whether
   another exists. */
function runsArrived(whole) {
  if (!RUN_WANTED) return;
  if (taskRecs[RUN_WANTED]) { findGoRun(RUN_WANTED); return; }
  if (!whole) return;
  RUN_WANTED = '';
  notify('That run is not on the task list any more.', { tone: 'warning' });
  addrTouch();
}

/* A pin or a rename came back. The list is asked again rather than patched:
   what changed may have changed what matches, and a row renamed out of the
   query has to leave the list it was renamed in. */
/** @param {import('./protocol').FromServer<'object_changed'>} m */
function findChanged(m) {
  if (!m) return;
  if (!m.ok) {
    var why = m.why || 'That could not be done.';
    if (FIND.open) findSaid(why, true); else notify(why, { tone: 'error' });
    return;
  }
  if (FIND.open) findAsk(true);
}

/* ---------- detaching a fork, into a task ----------

   Petar, 6 October 2026 (fr_efa418fa7e82): "when I detach a chat I have to
   pick which task I move it to, or else I am not detaching. this is done to
   prevent loose chats. so I click the detach, I end up in a modal that has
   search (the same mechanics as the normal search with CMD+K) and then it
   gets detached and moved at the same time."

   So the unlinked chain on a fork's card (`forkDetach`) opens this and does
   nothing else. It is the box above, narrowed to tasks: what is typed is
   asked of the server exactly as the box's Tasks pill asks it
   (`searching.search`), so a task is found by the same words and its number
   puts it first; before anything is typed it lists the tasks last worked
   on, the way the box lists the latest chats. The arrows move, Enter or a
   press picks, and picking is the whole move: one `detach_fork` naming the
   task, which the server carries out as one step or refuses
   (`owning.detach_fork_into`). Escape, the cross and a press outside it
   close it, and the fork is still a fork, beside the chat it came off.

   The answer is `attached`, the answer every move has, so the bar that says
   where it went is the one every move puts up (`movedTell`). The person
   stays where they are; the bar's button opens the task. */

var DETACH = { chat: '', not: '', q: '', rows: [], at: -1, gen: 0, timer: 0, busy: false };

function detachAsk(chat) {
  var dlg = $('detachDialog'), box = $('detachInput');
  if (!dlg || !box || !chat || !chat.id) return;
  var row = chatById(chat.id) || chat;
  // A fork is in no task, so there is no "where it is now" to leave off the
  // list. Were it in one, moving it there would do nothing.
  var owned = row.owned_by;
  DETACH = { chat: chat.id, not: owned && owned.type === 'task' ? owned.id : '',
             q: '', rows: [], at: -1, gen: DETACH.gen, timer: 0, busy: false };
  $('detachWhat').textContent = '“' + threadName(row) + '” leaves the chat it came'
    + ' off and becomes a chat of the task you pick, with every message it has.'
    + ' Nothing changes until you pick one.';
  dlg.classList.remove('is-busy');
  box.value = '';
  detachSaid('', false);
  try { dlg.showModal(); } catch (err) { dlg.setAttribute('open', ''); }
  box.focus();
  detachSearch(true);
}

function detachClose() {
  var dlg = $('detachDialog');
  if (!dlg) return;
  try { dlg.close(); } catch (err) { dlg.removeAttribute('open'); }
}

function detachOpen() {
  var dlg = $('detachDialog');
  return !!dlg && dlg.open;
}

function detachSearch(now) {
  if (DETACH.timer) { clearTimeout(DETACH.timer); DETACH.timer = 0; }
  if (!DETACH.q) {
    DETACH.rows = detachLatest();
    DETACH.at = DETACH.rows.length ? 0 : -1;
    detachDraw();
    return;
  }
  if (!now) {
    DETACH.timer = setTimeout(function () { DETACH.timer = 0; detachSearch(true); }, FIND_WAIT);
    return;
  }
  DETACH.gen++;
  send({ type: 'search', q: DETACH.q, kind: 'task', gen: DETACH.gen, box: 'detach' });
}

/* The tasks, the one last worked on first, before anything is typed. The
   same list the owner dialog and the Start box are drawn from, which has no
   archived task in it (`owning.snapshot`). */
function detachLatest() {
  return (OBJ.tasks || []).filter(function (t) {
    return t.id !== DETACH.not;
  }).sort(function (a, b) {
    return (Number(b.changed_at) || 0) - (Number(a.changed_at) || 0);
  }).map(function (t) {
    return { type: 'task', id: t.id, title: t.title || t.id,
             number: t.number, label: t.number != null ? String(t.number) : '',
             snippet: detachState(t.state), at: Number(t.changed_at) || 0 };
  });
}

function detachState(state) {
  return { waiting: 'Waiting on you', done: 'Done' }[String(state || '')] || '';
}

/* An answer, kept only when it is the answer to the words in the field now.
   Only tasks, and never an archived one or the one it is in already. */
/** @param {import('./protocol').FromServer<'search_results'>} m */
function detachAnswer(m) {
  if (!m || Number(m.gen || 0) !== DETACH.gen || !detachOpen()) return;
  DETACH.rows = (Array.isArray(m.results) ? m.results : []).filter(function (row) {
    return row.type === 'task' && !row.archived && row.id !== DETACH.not;
  });
  DETACH.at = DETACH.rows.length ? 0 : -1;
  detachDraw();
}

function detachDraw() {
  var host = $('detachList');
  if (!host) return;
  var words = DETACH.q ? String(DETACH.q).split(/\s+/).filter(function (w) { return !!w; }) : [];
  host.textContent = '';
  for (var i = 0; i < DETACH.rows.length; i++) {
    host.appendChild(detachRow(DETACH.rows[i], i, words));
  }
  $('detachListHead').hidden = !!DETACH.q || !DETACH.rows.length;
  if (DETACH.busy) return;
  detachSaid(DETACH.rows.length ? ''
    : DETACH.q ? 'No task matches “' + DETACH.q + '”.'
      : 'There are no tasks yet to put it in.', false);
  detachKeepOnScreen();
}

/* One task, drawn the way the box draws one: its glyph, its number in a
   column of its own, its name, and when it was last worked on. */
function detachRow(row, i, words) {
  var node = el('div', 'find-row' + (i === DETACH.at ? ' on' : ''));
  node.setAttribute('role', 'option');
  node.setAttribute('aria-selected', i === DETACH.at ? 'true' : 'false');
  node.setAttribute('data-i', String(i));
  var icon = el('span', 'find-icon');
  icon.appendChild(findIcon('task'));
  node.appendChild(icon);
  var num = el('span', 'find-num');
  findMark(num, findLabel(row), words);
  node.appendChild(num);
  var name = el('span', 'find-name');
  findMark(name, findTitle(row), words);
  node.appendChild(name);
  var snip = el('span', 'find-snip');
  findMark(snip, row.snippet || '', words);
  node.appendChild(snip);
  node.appendChild(el('span', 'find-when', findWhen(row.at)));
  node.title = 'Detach into ' + findName(row);
  return node;
}

function detachMove(step) {
  if (!DETACH.rows.length) return;
  var host = $('detachList'), was = DETACH.at;
  DETACH.at = (DETACH.at + step + DETACH.rows.length) % DETACH.rows.length;
  detachPaint(host, was);
  detachKeepOnScreen();
}

function detachPaint(host, was) {
  var nodes = host ? host.children : [];
  if (was >= 0 && nodes[was]) {
    nodes[was].classList.remove('on');
    nodes[was].setAttribute('aria-selected', 'false');
  }
  if (DETACH.at >= 0 && nodes[DETACH.at]) {
    nodes[DETACH.at].classList.add('on');
    nodes[DETACH.at].setAttribute('aria-selected', 'true');
  }
}

function detachKeepOnScreen() {
  var host = $('detachList');
  var node = host && DETACH.at >= 0 ? host.children[DETACH.at] : null;
  if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
}

function detachSaid(words, bad) {
  var said = $('detachSaid');
  if (!said) return;
  said.textContent = words || '';
  said.classList.toggle('bad', !!bad);
  said.hidden = !words;
}

/* Picked: the one message that detaches it and files it, and the box waits
   for the answer, so a second press cannot send it twice. */
function detachPick(i) {
  var row = DETACH.rows[i];
  if (!row || DETACH.busy || !DETACH.chat) return;
  DETACH.busy = true;
  $('detachDialog').classList.add('is-busy');
  detachSaid('Detaching it into ' + findName(row) + '…', false);
  send({ type: 'detach_fork', id: DETACH.chat, task: row.id });
}

/* The answer to a pick, which is `attached` about the fork. True when it was
   this box's to take: it closes and the bar says where the chat went, or it
   stays open and says why not, so another task can be picked. */
/** @param {import('./protocol').FromServer<'attached'>} m */
function detachAnswered(m) {
  if (!m || !DETACH.busy || m.kind !== 'chat' || m.id !== DETACH.chat) return false;
  DETACH.busy = false;
  $('detachDialog').classList.remove('is-busy');
  if (!m.ok) {
    detachSaid(m.why || 'It could not be detached into that task.', true);
    return true;
  }
  DETACH.chat = '';
  detachClose();
  movedTell(m, 'detached');
  return true;
}

(function () {
  var dlg = $('detachDialog'), box = $('detachInput'), list = $('detachList');
  if (!dlg || !box || !list) return;
  $('detachClose').addEventListener('click', detachClose);
  // Closed however it was closed, nothing is detached: a pick still on its
  // way is answered, and the answer is put in the bar instead.
  dlg.addEventListener('close', function () {
    if (DETACH.timer) { clearTimeout(DETACH.timer); DETACH.timer = 0; }
    if (!DETACH.busy) DETACH.chat = '';
  });
  // A press on the backdrop, which is the dialog element itself.
  dlg.addEventListener('click', function (e) {
    if (e.target === dlg) detachClose();
  });
  box.addEventListener('input', function () {
    DETACH.q = box.value.trim();
    detachSearch(false);
  });
  list.addEventListener('click', function (e) {
    var node = e.target && e.target.closest ? e.target.closest('.find-row') : null;
    if (node) detachPick(Number(node.getAttribute('data-i')));
  });
  // Hovering a row moves the highlight with it, as it does in the box.
  list.addEventListener('mousemove', function (e) {
    var node = e.target && e.target.closest ? e.target.closest('.find-row') : null;
    if (!node) return;
    var i = Number(node.getAttribute('data-i'));
    if (i === DETACH.at) return;
    var was = DETACH.at;
    DETACH.at = i;
    detachPaint(list, was);
  });
  dlg.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); detachMove(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); detachMove(-1); return; }
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      // Words typed faster than the answer: Enter asks now and picks the
      // first of what comes back, rather than the first of the list before.
      if (DETACH.timer) { detachSearch(true); return; }
      if (DETACH.at >= 0) detachPick(DETACH.at);
    }
  });
}());

export { detachAnswer, detachAnswered, detachAsk, FIND, FIND_KEYS, findAct, findAnswer, findAsk, findReconnected,
  findChanged, findGo, findLabels, findMenuShow, findMove, findMsgReveal, findPaint, findShow,
  RUN_WANTED, runsArrived };
