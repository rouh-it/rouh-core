/* The task browser at /workspace/. The server puts every project and every
   task, with its steps and their pages, in window.ROUH_TASKS; this draws them,
   and hands every change to Rouh, which writes it to the object database and
   moves the folder with it.

   This is the workspace's own index page brought back. It was written against
   `_categories.json`, which named a side and a category for every task in one
   file; here a task's category is the project that owns it in the object
   database, a category is a project inside Work or Personal, and a move is
   `objecttree.move` - the link table first, then `git mv`. Nothing is read
   from or written to `_categories.json` any more.

   Two things the old page had are gone because the model has no place for
   them: a category's colour, which is worked out from its place in its column
   unless the person picks one in Manage projects, and Claude's "guess" mark,
   which was a field in that file. Everything else is here.

   Nothing is kept in the browser except whether steps start open. */
(function () {
  'use strict';
  var DATA = window.ROUH_TASKS || { sides: [], categories: [], tasks: [] };
  /* Each column shows this many tasks before folding the older ones; below
     that the page simply scrolls. */
  var FOLD_AT = 50;
  var REDUCE = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  /* The handle a task or a subtask is dragged by, as Notion has it: six dots,
     in the margin at the start of the line the pointer is on. Petar, 22
     October 2026: "there seems to be a tiny sliver of space that gives me the
     hand/drag cursor ... nothing visual gives me the idea of dragging. both
     tasks and subtasks should have dragging area obvious." */
  var GRIP = '<span class="grip" aria-hidden="true" title="Drag to move"><svg viewBox="0 0 8 14">' +
    '<circle cx="2" cy="2" r="1.25"/><circle cx="6" cy="2" r="1.25"/><circle cx="2" cy="7" r="1.25"/>' +
    '<circle cx="6" cy="7" r="1.25"/><circle cx="2" cy="12" r="1.25"/><circle cx="6" cy="12" r="1.25"/></svg></span>';
  var CHEVRON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5l4.5 4.5L6 12.5"/></svg>';
  /* A box with its lid on, and the same box with an arrow coming up out of
     it: Archive, and bringing a task back (the menu's own two, `menu.js`). */
  var BOX = '<rect x="3.5" y="4.5" width="17" height="4" rx="1"/><path d="M5 8.5v10a1.5 1.5 0 0 0 1.5 1.5h11' +
    'a1.5 1.5 0 0 0 1.5-1.5v-10"/>';
  function boxIcon(out) {
    return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + BOX +
      (out ? '<path d="M12 17.5v-5.5M9.5 14.5L12 12l2.5 2.5"/>' : '<path d="M10 12.5h4"/>') + '</svg>';
  }
  /* The pin, as a task's own page draws it (`objectindex.PIN_SVG`): its head
     is filled on one that is pinned. */
  var PIN_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path class="pin-head" ' +
    'd="M10 3.5V9l-3 3v1.5h10V12l-3-3V3.5z"/><path d="M9 3.5h6"/><path d="M12 13.5v7"/></svg>';
  /* What the page sends Rouh, and what comes back. A sandboxed frame cannot
     fetch at all, so every change is handed to the page around it, which is
     signed in. It names an action and two ids, never an address. */
  var ASK = 'rouh-page-file', TOLD = 'rouh-frame-filed';
  /* Which list is showing, handed up to Rouh and back down again. The frame
     is thrown away every time a task or a page is opened out of it, so the
     page itself cannot remember what it was showing; Rouh keeps it for the
     tab and hands it back when the browser is opened again, which is what
     makes Back come back to the list the person left (pages.VIEW_MESSAGE). */
  var VIEW = 'rouh-page-view', VIEWED = 'rouh-frame-view';

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function plural(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }

  var sides = DATA.sides || [], cats = DATA.categories || [];
  /* A page opened at its own address rather than framed by Rouh has no way to
     hand a change up: it is read, and says so. */
  var readonly = !DATA.framed;
  if (readonly) { document.body.classList.add('readonly'); }
  var tasks = (DATA.tasks || []).slice();
  var byId = {};

  function reindex() {
    byId = {};
    tasks.forEach(function (t) { byId[t.id] = t; });
  }
  reindex();

  /* Which tasks show their steps: the ones whose arrow was pressed. There was
     an Expand all button for every task at once, and Petar had it taken off
     on 1 October 2026 (fr_0bfea6b4153f), with the rest of what sat over the
     search box, so the list starts higher on a phone. */
  var flipped = {};
  /* The Archive (`rouh/archiving.py`): true while the page shows the archived
     tasks instead of the live ones. Petar, 29 September 2026
     (fr_08e097dbe815): "After we have some archived tasks, we can click
     archive and see and search those instead of the live ones." So it is one
     more thing the list is narrowed by, like a project, and everything else
     on the page - the projects, the columns, the search, the keyboard - works
     the same on either side of it. */
  var shelf = false;
  /* Others' tasks (`rouh/task_origin.py`): true while the page shows the
     tasks made for somebody else - a trusted contact's email or Telegram
     message, a case - instead of his own, each marked with who it was for.
     Petar, 15 October 2026: "I don't want those to pollute my workspace.
     Maybe like a toggle similar to Archive?" It was first a switch that added
     them to his own list, and Petar, the same day (fr_e06a8342488e): "Others
     tasks in task browser should act like archives when it is clicked I only
     see other people's task." So it is the Archive's kind of thing: one more
     side the list is on, in the address with it, and the two together are
     the archived tasks made for other people.

     Made by Rouh is the same kind of side again, for the tasks Rouh's own
     processes made on their own - a thought's research, a night of the
     nightly run, a quest's beat. Petar, 16 October 2026: "Whatever any
     process is doing should be created without me being the gate. I just
     don't want to see it by default in the task browser." So `whose` is
     which of the three the list is on - his own (""), "others" or "rouh" -
     and `proc` narrows Made by Rouh to one process. Anything pinned, or
     waiting on him, is on his own side whoever made it. */
  var whose = '', proc = '';
  /* The labels whose eye is crossed: their tasks are left out of the list,
     wherever it is, until the eye is pressed again or the label itself is
     the filter pressed. Petar, 22 October 2026 (fr_d2222b1e45af): "I would
     like each tag/label to be able to be hidden by default. |eye| section in
     front can be clicked on that label and it can become crossed. in which
     case the view removes the items from that view." `others`, `rouh`,
     `goals`, and `cat:<id>` for a project. Others' tasks and Made by Rouh
     start crossed, which is what kept them out of his own list before there
     were eyes; anything pinned or waiting on him still shows. */
  var hide = {};
  var BUILTIN_HOME = 'hide=others,rouh';
  /* Where a task taken out of a project with the cross goes: the project a
     task nobody filed goes to (`filing.fallback`). */
  var FALLBACK = DATA.fallback || '';
  var sel = readView(decodeURIComponent(location.hash.slice(1)));
  var query = '';
  /* Whether the reader has changed the list here yet: Rouh's answer about
     the one they left is only put back over a page nobody has touched. */
  var touched = false;
  var unfolded = {};
  var stops = [];
  var cursorKey = null;
  var dragId = null;
  /* A subtask being dragged onto another task (`dragStep`), by its id. */
  var dragStepId = null;
  var toastTimer = null;
  var menuFor = null;
  var peekTest = null;

  var bar = $('#bar'), board = $('#board'), q = $('#q'),
    emptyEl = $('#empty'), menu = $('#menu'), toastEl = $('#toast'),
    noticeEl = $('#notice');
  var holding = document.createDocumentFragment();

  function catById(id) {
    for (var i = 0; i < cats.length; i++) { if (cats[i].id === id) { return cats[i]; } }
    return null;
  }
  function catOf(t) { return t.category ? catById(t.category) : null; }
  function sideName(id) {
    for (var i = 0; i < sides.length; i++) { if (sides[i].id === id) { return sides[i].name; } }
    return id;
  }
  /* A project's colour is one of the page's own names or `#rrggbb` picked by
     hand; the server lets nothing else through (`objectindex._coloured`). */
  function colorVal(name) { return /^#[0-9a-f]{6}$/i.test(name || '') ? name : 'var(--cat-' + name + ')'; }
  function colorVar(c) { return c ? colorVal(c.color) : 'var(--cat-none)'; }
  /* How light a colour is, 0 to 1, as WCAG reckons it; null for a name. */
  function lightness(hex) {
    if (!/^#[0-9a-f]{6}$/i.test(hex || '')) { return null; }
    var ch = [1, 3, 5].map(function (i) {
      var v = parseInt(hex.substr(i, 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.04) / 1.055, 2.4);
    });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  }
  /* The colour, and the colour of words written on it. The page's own seven
     are all light enough for its dark ink; a colour picked by hand may not
     be, and a button filled with a dark one is given white words instead. */
  function ccStyle(c) {
    var l = c ? lightness(c.color) : null;
    return '--cc:' + colorVar(c) + (l !== null && l < 0.18 ? ';--cc-on:#fff' : '');
  }
  function paintCc(el, c) {
    el.style.setProperty('--cc', colorVar(c));
    var l = c ? lightness(c.color) : null;
    if (l !== null && l < 0.18) { el.style.setProperty('--cc-on', '#fff'); } else { el.style.removeProperty('--cc-on'); }
  }
  function usedSides() { return sides.filter(function (s) { return cats.some(function (c) { return c.side === s.id; }); }); }
  function label(t) { return (t.n !== null && t.n !== undefined ? t.n + ' · ' : '') + t.name; }

  /* ---------------------------------------------------------------- the URL */
  /* The view is written as a fragment - `waiting`, `side=work`, `cat=a,b` -
     which is what a page opened at its own address reads out of its address.
     It is never a step in the tab's history. This used to push one for every
     button pressed, so that Back would return to the previous view, but this
     page lives in a frame Rouh throws away every time something is opened out
     of it, and a step a frame leaves behind is one Back lands on after the
     frame is gone: nothing at all in Chromium, which refuses the push from a
     sandboxed frame anyway, and a blank white page in Safari, which does not
     (fr_08e89370f7c7). So the address is only ever replaced, and the view is
     kept by Rouh instead (`VIEW` above). */
  /* The Archive and whose tasks go in front of the rest, and the crossed
     eyes last: `archived`, `others`, `rouh=thoughts`, `cat=a&hide=rouh`,
     `archived&others&cat=a&hide=`. A view says every eye, so it is never
     empty; the one Save view kept (`home`) is written as nothing at all,
     which keeps Rouh's address bare on the list he opens on. A view with no
     `hide` in it, written before there were eyes, has the home's. */
  function home() { return DATA.saved_view || BUILTIN_HOME; }
  function hideOf(list) {
    var out = {};
    list.split(',').forEach(function (k) {
      if (k === 'others' || k === 'rouh' || k === 'goals' ||
        (k.indexOf('cat:') === 0 && catById(k.slice(4)))) { out[k] = true; }
    });
    return out;
  }
  function hidePart(h) {
    var at = ('&' + h).lastIndexOf('&hide=');
    return at === -1 ? null : ('&' + h).slice(at + 6).split('&')[0];
  }
  function readView(h) {
    h = h || home();
    var said = hidePart(h);
    if (said === null) { said = hidePart(home()); }
    if (said === null) { said = hidePart(BUILTIN_HOME); }
    hide = hideOf(said);
    var rest = h.split('&').filter(function (x) { return x.indexOf('hide=') !== 0; });
    shelf = rest.indexOf('archived') !== -1;
    whose = rest.indexOf('others') !== -1 ? 'others' : '';
    proc = '';
    rest.forEach(function (x) {
      if (x === 'rouh' || x.indexOf('rouh=') === 0) { whose = 'rouh'; proc = x.slice(5); }
    });
    return fromHash(rest.filter(function (x) {
      return x !== 'archived' && x !== 'others' && x !== 'rouh' && x.indexOf('rouh=') !== 0;
    }).join('&'));
  }
  function fromHash(h) {
    if (h === 'waiting') { return { kind: 'waiting' }; }
    if (h === 'demo') { return { kind: 'demo' }; }
    if (h === 'goals') { return { kind: 'goals' }; }
    if (h.indexOf('side=') === 0) {
      var s = h.slice(5);
      if (sides.some(function (x) { return x.id === s; })) { return { kind: 'side', id: s }; }
    }
    if (h.indexOf('cat=') === 0) {
      var ids = h.slice(4).split(',').filter(function (id) { return catById(id); });
      if (ids.length) { return { kind: 'cats', ids: ids }; }
    }
    return { kind: 'all' };
  }
  function inner(s) {
    if (s.kind === 'waiting') { return 'waiting'; }
    if (s.kind === 'demo') { return 'demo'; }
    if (s.kind === 'goals') { return 'goals'; }
    if (s.kind === 'side') { return 'side=' + s.id; }
    if (s.kind === 'cats') { return 'cat=' + s.ids.join(','); }
    return '';
  }
  /* The whole view, eyes and all: what Save view keeps. */
  function fullView(s) {
    return [shelf ? 'archived' : '', whose === 'rouh' ? 'rouh' + (proc ? '=' + proc : '') : whose, inner(s),
      'hide=' + Object.keys(hide).filter(function (k) { return hide[k]; }).sort().join(',')]
      .filter(Boolean).join('&');
  }
  function hashFor(s) {
    var h = fullView(s);
    return h !== home() ? '#' + h : location.pathname + location.search;
  }
  function setSel(s) {
    sel = s;
    try { history.replaceState(null, '', hashFor(s)); } catch (e) { /* sandboxed */ }
    cursorKey = null;
    render(true);
    tell();
  }

  function viewOf(s) { var h = hashFor(s); return h.charAt(0) === '#' ? h.slice(1) : ''; }
  function toRouh(m) {
    if (readonly) { return; }
    var parent;
    try { parent = window.parent; } catch (e) { return; }
    if (!parent || parent === window) { return; }
    try { parent.postMessage(m, '*'); } catch (e) { /* Rouh is gone */ }
  }
  /* The list as it is now, for Rouh to keep. */
  function tell() {
    touched = true;
    toRouh({ type: VIEW, view: viewOf(sel), q: q.value });
  }
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== 'rouh-frame-offline' || e.source !== window.parent) { return; }
    offlineHave = null;
    if (m.offline && Array.isArray(m.have)) {
      offlineHave = {};
      m.have.forEach(function (rel) { offlineHave[String(rel)] = true; });
    }
    document.body.classList.toggle('offline', !!offlineHave);
    buildRows();
    render(false);
  });
  /* The list the reader left, put back when Rouh says what it was. */
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== VIEWED || e.source !== window.parent || touched) { return; }
    var was = viewOf(sel);
    var back = readView(typeof m.view === 'string' ? m.view : '');
    var words = typeof m.q === 'string' ? m.q : '';
    if (viewOf(back) === was && words === q.value) { return; }
    sel = back;
    q.value = words;
    query = words.trim().toLowerCase();
    cursorKey = null;
    /* Which side it is on decides what each line names (`setWhose`). */
    buildRows();
    render(false);
  });

  /* The tasks on this side of the Archive: the live ones, or the archived. */
  function onShelf(t) { return !!t.archived === shelf; }
  /* Whose side a task or a step is on: his own (""), "others" for one made
     for somebody else, "rouh" for one a process of Rouh's made
     (`rouh/task_origin.py`). */
  function kindOf(o) { return !o || !o.made ? '' : o.made.kind === 'other' ? 'others' : 'rouh'; }
  /* On side `w` (the list's, left out), and of process `p` there, if one is picked. */
  function ofSide(o, w, p) {
    if (w === undefined) { w = whose; p = proc; }
    return kindOf(o) === w && (w !== 'rouh' || !p || o.made.process === p);
  }
  /* Whether his own list shows what that side's maker made: his own always,
     Others' tasks and Made by Rouh while their eye is open. */
  function shownKind(k) { return !k || !hide[k]; }
  /* Pinned, or waiting on him: in his own list whoever made it, so nothing
     that needs him is out of sight. */
  function needsYou(t) { return !!t.pinned || isWaiting(t); }
  /* Whether a step, or one under it however deep, is on the side the list is on. */
  function holds(s, w, p) {
    return ofSide(s, w, p) || (s.kids || []).some(function (k) { return holds(k, w, p); });
  }
  /* Whether a task is on this side: his own, made for somebody else, or made
     by Rouh. One of his own tasks with steps a process made in it - a night
     of the nightly run in its task - is on Made by Rouh too, with those
     steps alone. */
  function seen(t, w, p) {
    if (w === undefined) { w = whose; p = proc; }
    if (!w) { return shownKind(kindOf(t)) || needsYou(t); }
    return ofSide(t, w, p) || t.steps.some(function (s) { return holds(s, w, p); });
  }
  /* The processes a task on Made by Rouh is there for: its own maker, or the
     makers of the steps that put it there. */
  function processesOf(t) {
    var out = {};
    (function walk(o) {
      if (kindOf(o) === 'rouh') { out[o.made.process] = o.made.name || o.made.process; }
      if (o !== t || kindOf(t) !== 'rouh') { (o.kids || o.steps || []).forEach(walk); }
    })(t);
    return out;
  }
  /* Which of a task's steps are drawn: every one of a task of the side the
     list is on (and of one somebody else made that is on his own side because
     it needs him); of one of his own, only his own steps and the pinned; and
     of any other, only those of this side, with whatever holds one. */
  function wholeHere(t) { return whose ? ofSide(t) : !!kindOf(t); }
  function keeper(t) {
    if (wholeHere(t)) { return function (s) { return !s.gone; }; }
    return function (s) { return !s.gone && (whose ? holds(s) : shownKind(kindOf(s)) || !!s.pinned); };
  }
  /* Left out by a crossed eye: a goal while Goals' is crossed, a task in a
     project whose eye is crossed. The label pressed as the filter shows its
     own tasks whatever its eye says, since that is what was asked for. */
  function eyeHidden(t) {
    if (hide.goals && isGoal(t) && sel.kind !== 'goals') { return true; }
    var c = catOf(t);
    return !!c && !!hide['cat:' + c.id] && !(sel.kind === 'cats' && sel.ids.indexOf(c.id) !== -1);
  }
  function pool() { return tasks.filter(function (t) { return onShelf(t) && seen(t); }); }
  function inSel(t) {
    if (sel.kind === 'waiting') { return isWaiting(t); }
    if (sel.kind === 'demo') { return inDemo(t); }
    if (sel.kind === 'goals') { return isGoal(t); }
    var c = catOf(t);
    if (sel.kind === 'side') { return !!c && c.side === sel.id; }
    if (sel.kind === 'cats') { return !!c && sel.ids.indexOf(c.id) !== -1; }
    return true;
  }
  function headHay(t) {
    var c = catOf(t);
    return ((t.n !== null && t.n !== undefined ? t.n : '') + ' ' + t.name + ' ' + t.dir + ' ' +
      (c ? c.name : '') + ' ' + (t.status_label || '') + ' ' + (t.tags || []).join(' ') + ' ' +
      (t.was || []).join(' ')).toLowerCase();
  }
  /* One step's own words, and whether it or any step under it, however
     deep, has the words searched for. The numbers it had before a move are
     among them (`rouh/moving.py`): Petar, 22 October 2026 (fr_676c7ad596fd),
     "when I search for 92-08, if that's what I remember, it would still
     appear, but it would be with the new name, 103-01." */
  function stepHay(s) { return (s.num + ' ' + s.title + ' ' + (s.was || []).join(' ')).toLowerCase(); }
  /* The number it had before, beside the one it has, when that is what the
     search found it by. */
  function wasMark(o) {
    if (!query) { return ''; }
    var hit = (o.was || []).filter(function (n) { return n.toLowerCase().indexOf(query) !== -1; });
    return hit.length ? '<span class="was" title="Its number before it was moved">was ' + esc(hit.join(', ')) + '</span>' : '';
  }
  function stepFinds(s) {
    return stepHay(s).indexOf(query) !== -1 || (s.kids || []).some(stepFinds);
  }
  function matchesQuery(t) {
    return !query || headHay(t).indexOf(query) !== -1 || t.steps.some(stepFinds);
  }
  /* What the list is, on whichever side of the Archive and whose tasks. */
  function sideWords() {
    var who = whose === 'others' ? 'Others\u2019' : whose === 'rouh' ? 'Made by Rouh,' : '';
    return shelf && who ? who + ' archived' + (whose === 'others' ? ' tasks' : '') : shelf ? 'Archive' :
      whose === 'others' ? 'Others\u2019 tasks' : whose === 'rouh' ? 'Made by Rouh' : 'All';
  }
  function selLabel() {
    if (sel.kind === 'all' && (shelf || whose)) { return sideWords(); }
    if (sel.kind === 'waiting') { return 'Waiting on you'; }
    if (sel.kind === 'demo') { return 'Shown in demo'; }
    if (sel.kind === 'goals') { return 'Goals'; }
    if (sel.kind === 'side') { return sideName(sel.id); }
    if (sel.kind === 'cats') {
      return sel.ids.map(function (id) { var c = catById(id); return c ? c.name : id; }).join(' + ');
    }
    return 'All';
  }

  /* ----------------------------------------------------------------- steps */
  /* A task opens when it has steps, and onto its steps and nothing else. One
     with none is a plain line with no arrow, whatever else it holds: its
     pages, chats, runs and cards are on its own page, which is where a press
     on its name goes. Petar, 24 September 2026: "a task in the task browser
     should have a chevron and subitems only if they are tasks. don't display
     artifacts, chats or any of that." The server sends nothing else to hang
     under it (`index_data`). One step is enough: an open row hides the newest
     step it shows beside its name, and a phone never shows that at all. */
  function openable(t) { return t.steps.some(keeper(t)); }
  function countOf(t) { return t.steps.filter(keeper(t)).length; }
  /* How many steps hang under a task or a step, as a bare number between its
     own number and its name, with the words on a pointer resting on it.
     Petar, 22 October 2026 (fr_092ef8f8682b): "move those forward right
     after the number of the task. make them without the label steps, just
     the number ... if I hover the 6, it says 6 sub steps". The words are
     the page's own tip (`data-tip`), there the moment the pointer is. One with none
     keeps the place empty, so every name in a list starts at the same x. A
     press on it opens and closes the steps, as the "6 steps" button did. */
  function countMark(n) {
    return n ? '<span class="scount" data-n="' + n + '" data-tip="' + plural(n, 'sub step') + '">' + n + '</span>' :
      '<span class="scount" aria-hidden="true"></span>';
  }
  /* The widths a list's number and count slots take, in characters: its
     widest number and its biggest count, so short numbers and long ones take
     the same room and the names after them line up. */
  function slotWidths(steps) {
    var w = 1, c = 1;
    steps.forEach(function (s) {
      w = Math.max(w, String(s.num || '').length);
      c = Math.max(c, String(s.n || '').length);
    });
    return '--snw:' + w + ';--scw:' + c;
  }
  function isOpen(t) { return openable(t) && !!flipped[t.id]; }
  /* A search narrows which tasks are listed and changes nothing about how
     each one is drawn: a task that was closed stays closed, one that was
     open stays open with all its steps, and a branch folded away stays
     folded, however the search found it. Until 15 October 2026 a task found
     only through one of its steps opened onto the steps that matched, with
     every branch on the way forced open, and Petar, that day
     (fr_449b45afdff4): "When I filter in the tasks, the result is that the
     tasks expand and I see all their sub tasks. Please don't do that. Don't
     unfold them automatically, they should stay as they are". */
  function stepsShown(t) { return { open: isOpen(t), steps: t.steps }; }
  /* A task whose next move is the person's (the agent instructions, Waiting tasks). Once they
     have answered it from the task's page it is waiting on the job that took
     the answer in rather than on them (`rouh/answering.py`), so it is not in
     Waiting on you; nor is one whose question they dismissed there
     (`dismissed`), which asks nothing now. Here it says so with its pill and
     nothing else: what it asks is at the top of its own page. Until 24
     September 2026 a line under its name said that too, and Petar, the same
     day: "remove the entire block Waiting on you including the specifics of
     what it is awaiting. keep only the waiting label." */
  function isWaiting(t) { return t.status === 'waiting' && !t.answered && !t.dismissed; }
  /* Demo mode (`rouh/demo.py`): what the person approved for an audience, a task with all
     its steps or one step, as the server says it (`DEMO.shown`, the numbers). Shown in demo
     lists them; a purple dot marks each one while demo mode, or its preview, is on. */
  var DEMO = DATA.demo || { on: false, shown: [] };
  var DEMO_SHOWN = {};
  (DEMO.shown || []).forEach(function (n) { DEMO_SHOWN[String(n)] = true; });
  function shownNum(n) {
    if (n === null || n === undefined || n === '') { return false; }
    n = String(n);
    return !!DEMO_SHOWN[n] || !!DEMO_SHOWN[n.split('-')[0] + '*'];
  }
  function stepInDemo(s) { return !!s.demo_shown || shownNum(s.num) || (s.kids || []).some(stepInDemo); }
  function inDemo(t) { return !!t.demo_shown || shownNum(t.n) || t.steps.some(stepInDemo); }
  function demoDot(on) {
    return on && DEMO.on ? '<i class="demo-dot" title="Shown in demo mode" aria-label="Shown in demo mode"></i>' : '';
  }
  /* One of the person's goals: a task tagged Goal, whose steps are its plan
     (`rouh/goals.py`). Petar, 27 September 2026: "one task with a label/Tag
     Goal (not folder)". So it is a pill on its row wherever it is filed, and
     a button over the columns that shows only them. */
  function isGoal(t) { return (t.tags || []).indexOf('goal') !== -1; }
  /* A goal says so with the sidebar's Goals target, in colour, and a waiting
     task with an hourglass, each named for a pointer and a screen reader.
     Until 1 October 2026 they were the words Goal and Waiting in pills, and
     Petar, that day (fr_a669ec406006): "Label goal should be replaced with
     colorful icon, same as in sidebar Goals. Label waiting on you, should be
     replaced with icon". The same two are on the bar's two buttons, which is
     where a person learns what each one means. */
  var GOAL_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke-width="2.2">' +
    '<circle cx="12" cy="12" r="8.6" stroke="var(--cat-rose)"/><circle cx="12" cy="12" r="4.6" ' +
    'stroke="var(--cat-amber)"/><circle cx="12" cy="12" r="1.5" fill="var(--cat-teal)" stroke="none"/></svg>';
  var WAIT_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 3.5h11M6.5 20.5h11"/>' +
    '<path d="M7.5 3.5c0 4.2 4.5 5.6 4.5 8.5s-4.5 4.3-4.5 8.5M16.5 3.5c0 4.2-4.5 5.6-4.5 8.5s4.5 4.3 4.5 8.5"/>' +
    '<path class="sand" d="M9.6 19.2c.6-1.6 1.6-2.4 2.4-2.4s1.8.8 2.4 2.4z"/></svg>';
  function markIcon(kind, words, svg) {
    return '<span class="tmark" data-mark="' + kind + '" role="img" title="' + words + '" aria-label="' +
      words + '">' + svg + '</span>';
  }
  /* A quest (`rouh/quests.py`) is a task tagged Quest, marked with the
     sidebar's Quests sword, the way a goal wears its target. */
  function isQuest(t) { return (t.tags || []).indexOf('quest') !== -1; }
  var QUEST_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke-width="2.1" ' +
    'stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M20.5 3.5l-.7 4.6L10 17.9 6.1 14l9.8-9.8z" stroke="var(--cat-teal)"/>' +
    '<path d="M3.8 12.2l8 8M7.4 16.6l-3.6 3.6" stroke="var(--cat-amber)"/></svg>';
  function tagChip(t) {
    return (isGoal(t) ? markIcon('goal', 'Goal', GOAL_SVG) : '') +
      (isQuest(t) ? markIcon('quest', 'Quest', QUEST_SVG) : '') + offChip(t);
  }
  /* Who made it, on a line of its own under the name: "By Thoughts", "By
     Nightly refactoring run", "For Sam Rivera". Beside the name it took the
     name's room, and a narrow column spelt the name out over five lines.
     Petar, 22 October 2026 (fr_d2222b1e45af): "I would like to see the tags
     "by thoughts" "by nightly refactoring run" to be on a new line, because
     otherwise the space becomes crunched and the task becomes in many
     lines." */
  function sourceLine(t) {
    var chip = madeChip(t);
    return chip ? '<span class="tsrc">' + chip + '</span>' : '';
  }
  /* Two people: Others' tasks, on its button and as the mark on a task made
     for somebody else. */
  var PEOPLE_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.2"/>' +
    '<path d="M3.5 19.5c.6-3.3 2.8-5.2 5.5-5.2s4.9 1.9 5.5 5.2"/><path d="M15.5 5.2a3 3 0 0 1 0 5.6"/>' +
    '<path d="M17.2 14.6c1.8.6 3 2.3 3.3 4.9"/></svg>';
  /* Rouh's own mark, for Made by Rouh: the orb's ring with its spark. */
  var ROUH_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/>' +
    '<path d="M12 7.5l1.3 3.2 3.2 1.3-3.2 1.3-1.3 3.2-1.3-3.2-3.2-1.3 3.2-1.3z"/></svg>';
  /* Who made a task or a step, on its line, when it was not him: "For Sam
     Rivera", with the channel in its title, or "By Thoughts", the
     process that made it. */
  function madeChip(o) {
    var f = o && o.made;
    if (!f) { return ''; }
    if (f.kind === 'other') {
      return '<span class="forchip" title="' + esc(f.words || ('Made for ' + f['for'])) + '">' + PEOPLE_SVG +
        '<span>For ' + esc(f['for']) + '</span></span>';
    }
    return '<span class="forchip bychip" title="' + esc(f.words || 'Made by Rouh') + '">' + ROUH_SVG +
      '<span>By ' + esc(f.name || 'Rouh') + '</span></span>';
  }
  /* With no connection Rouh says which tasks its device keeps whole (`rouh-frame-offline`,
     app/offline.js): every other task is still listed, by name, status and project, and says
     it is not available offline, so opening it is not a surprise. Null while online. */
  var offlineHave = null;
  function offChip(t) {
    if (!offlineHave || !t.href) { return ''; }
    var rel = '';
    try { rel = decodeURIComponent(String(t.href).replace(/^\/workspace\/_task\//, '').replace(/\/+$/, '')); }
    catch (e) { return ''; }
    return offlineHave[rel] ? '' :
      '<span class="offchip" title="This task is not in this device&rsquo;s offline copy">Not available offline</span>';
  }
  /* How far along the task is, from its row. A task nobody has said anything
     about is open, which is every task, so only the other two are worth a
     pill: a line with a chip on all 229 of them says nothing. Done says
     nothing either: Petar, 1 October 2026 (fr_a669ec406006), "I am not sure
     what label DONE is. Remove this altogether". Waiting is the hourglass. */
  function statusChip(t) {
    if (isWaiting(t)) { return markIcon('waiting', 'Waiting on you', WAIT_SVG); }
    if (t.status === 'done') { return ''; }
    // Answered from its page, it is on the job that took the answer in; its
    // question dismissed there, it asks nothing and wears no pill.
    if (t.status === 'waiting' && t.answered) {
      return '<span class="task-status" data-status="answered">Answered</span>';
    }
    if (t.status === 'waiting' && t.dismissed) { return ''; }
    return t.status && t.status !== 'open'
      ? '<span class="task-status" data-status="' + esc(t.status) + '">' + esc(t.status_label) + '</span>' : '';
  }
  /* Everything an open task shows: its steps, and under each its own steps,
     all the way down, each level hanging from its step's arrow with the rule
     a chat's forks hang from it by on a task's page (`.orow[data-kind=fork]`).
     Petar, 10 October 2026: "sub-sub tasks are not visible on the task list.
     Can you make them like chats? I like how I can see the branching of
     chats." Until then a step of a step was one more flat line under its
     task's steps, and one two levels down had no row to be drawn from at all.

     Every line keeps the arrow's width whether it has an arrow or not, so the
     numbers and names line up at every depth. A step with steps of its own
     opens and closes with its arrow; all start open, so nothing is hidden
     until the person folds it away. The step worked on last, however deep,
     is marked, so the newest work is found at a glance (`latest`). */
  var folded = {};
  function lines(steps, cls, latest, keep) {
    return steps.filter(keep).map(function (s) {
      return { s: s, kids: (s.kids || []).filter(keep) };
    }).map(function (x) {
      var s = x.s, kids = x.kids, shut = !!folded[s.id];
      var arrow = kids.length ?
        '<button type="button" class="stw" data-fold="' + esc(s.id) + '" aria-expanded="' + !shut + '" title="' +
        (shut ? 'Show' : 'Hide') + ' its ' + plural(kids.length, 'step') + '">' + CHEVRON + '</button>' :
        '<span class="stw" aria-hidden="true"></span>';
      var mark = s.id && s.id === latest ?
        '<span class="snew" role="img" title="Worked on last" aria-label="Worked on last"></span>' : '';
      return '<li class="br' + (kids.length ? ' has' : '') + (shut ? ' shut' : '') + '" data-step-id="' + esc(s.id) + '">' +
        '<div class="sline"' + (readonly || shelf || !s.id ? '>' : ' draggable="true">' + GRIP) + arrow +
        one(s, cls + (mark ? ' newest' : ''), mark, kids.length) +
        pinButton(s, stepName(s)) + stepArch(s) + stepDots(s) + '</div>' +
        (kids.length ? '<ol class="kids" style="' + listWidths(kids, keep) + '"' + (shut ? ' hidden' : '') + '>' +
          lines(kids, cls, latest, keep) + '</ol>' : '') +
        '</li>';
    }).join('');
  }
  /* Fold or open one step's branch in place. */
  function foldStep(b) {
    var id = b.dataset.fold, li = b.closest('li.br'), kids = li && li.querySelector(':scope > ol.kids');
    if (!kids) { return; }
    var shut = !kids.hidden;
    folded[id] = shut;
    kids.hidden = shut;
    li.classList.toggle('shut', shut);
    b.setAttribute('aria-expanded', !shut);
    var n = kids.children.length;
    b.title = (shut ? 'Show' : 'Hide') + ' its ' + plural(n, 'step');
    buildStops();
  }
  /* A step, however deep, by its id, in a task's tree. */
  function stepIn(steps, id) {
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].id === id) { return steps[i]; }
      var deeper = stepIn(steps[i].kids || [], id);
      if (deeper) { return deeper; }
    }
    return null;
  }
  /* A step archived a moment ago, before Rouh has answered, is not drawn,
     and nor is one on another side than the list's (`keeper`). */
  /* The archive box on a subtask's line, as its task has on its row: Petar,
     1 October 2026 (fr_a669ec406006), "Sub tasks should also have archive
     button". Rouh archives it and everything under it (`rouh/archiving.py`);
     it is then kept under Archived on its task's own page. In the Archive the
     whole task is archived already, so its subtasks have none. */
  function stepArch(s) {
    if (readonly || shelf || !s || !s.id) { return ''; }
    return '<button type="button" class="arch" data-step="' + esc(s.id) + '" data-out="false" ' +
      'title="Archive, with its subtasks" aria-label="' + esc('Archive ' + stepName(s)) + '">' +
      boxIcon(false) + '</button>';
  }
  function stepName(s) { return (s.num ? s.num + ' · ' : '') + s.title; }
  /* A subtask's own three dots, after its archive box: its two ways out of
     its task, "Move to new task" and "Promote to task" (`stepMenu`). Petar,
     22 October 2026 (fr_676c7ad596fd): "that can be done from the ". . ."
     context menu, which doesn't exist as of now and should." Moving it to a
     task that is there already is a drag onto that task's line. */
  function stepDots(s) {
    if (readonly || shelf || !s || !s.id) { return ''; }
    return '<button type="button" class="dots" data-step="' + esc(s.id) + '" aria-haspopup="menu" ' +
      'title="Move it out of its task" aria-label="' + esc('More for ' + stepName(s)) + '">' + DOTS_SVG + '</button>';
  }
  /* The pin, on every task's line and every step's (`rouh/pinning.py`): one
     press pins exactly that one to the Control Room, and one more unpins it.
     Amber and always there on one that is pinned; on the others, there on
     the line the pointer is on, as the archive box is. It pins that one only:
     never the task above a step, never the steps under a task. */
  function pinButton(o, name) {
    if (readonly || !o || !o.id) { return ''; }
    var on = !!o.pinned;
    return '<button type="button" class="pin" data-pin="' + esc(o.id) + '" aria-pressed="' + on +
      '" title="' + pinTitle(on) +
      '" aria-label="' + esc((on ? 'Unpin ' : 'Pin ') + name) + '">' + PIN_SVG + '</button>';
  }
  function pinTitle(on) { return on ? 'Pinned to the Control Room. Press to unpin' : 'Pin to the Control Room'; }
  /* The slot widths of one list of steps, the ones drawn in it. */
  function listWidths(steps, keep) {
    return slotWidths(steps.filter(keep).map(function (s) {
      return { num: s.num, n: (s.kids || []).filter(keep).length };
    }));
  }
  function one(s, cls, mark, n) {
    /* Approved for demo mode: drawn as it is there (`rouh/demo_style.py`). */
    var ok = shownNum(s.num) ? ' data-demo-ok' : '';
    var open = s.href ? '<a class="' + cls + '" draggable="false" href="' + esc(s.href) + '"' + ok + '>'
      : '<span class="' + cls + '"' + ok + '>';
    /* The icon and the name are one cell of the line's grid, so a step with
       an icon and one without keep the same columns. */
    return open + '<span class="snum">' + esc(s.num || '') + '</span>' + countMark(n) +
      '<span class="sname">' + iconMark(s, s.title) + '<span class="stitle">' +
      esc(s.title) + '</span>' + demoDot(!!s.demo_shown || shownNum(s.num)) + wasMark(s) + '</span>' + (madeKey(s) === stepsOf || (whose && kindOf(s) === whose) ? '' : madeChip(s)) +
      (mark || '') + (s.href ? '</a>' : '</span>');
  }
  /* A task's or a step's icon in front of its title, which a press changes
     (`taskicon.js`, `rouh/taskicons.py`): its emoji, or its picture. Given no
     id, as on the newest step beside a task's name, it is the icon alone. */
  function iconMark(o, title) {
    var ti = window.RouhTaskIcon;
    if (!ti) { return ''; }
    return ti.mark({ icon: o.icon, img: o.img, id: readonly ? '' : o.id, title: title }, '');
  }
  /* An icon Rouh kept, put into what the rows are drawn from, so the next
     drawing of them draws it too. The marks on the page have it already. */
  if (window.RouhTaskIcon) {
    window.RouhTaskIcon.onKept(function (id, shown) {
      var o = byId[id];
      if (!o) {
        for (var i = 0; i < tasks.length && !o; i++) { o = stepIn(tasks[i].steps || [], id); }
      }
      if (o) { o.icon = shown.icon; o.img = shown.img; }
    });
  }
  /* Who made the task whose steps are being drawn: a step made by the same
     wears no mark of its own, which would say again what its task says; nor
     does one on Others' tasks or Made by Rouh made the way the whole list
     was, which the line over the list says already. */
  var stepsOf = '';
  function madeKey(o) { return !o || !o.made ? '' : o.made.kind + ':' + (o.made.process || o.made['for'] || ''); }
  function paintSteps(t) {
    hideTip();
    var a = rows[t.id], list = $('.subs', a), shown = stepsShown(t), keep = keeper(t);
    if (!shown.steps.some(keep)) { shown.open = false; }
    a.classList.toggle('open', shown.open);
    var tw = $('button.tw', a);
    if (tw) {
      tw.setAttribute('aria-expanded', shown.open);
      tw.title = (shown.open ? 'Hide its steps (space)' : 'Show its steps (space)');
    }
    if (!shown.open) { list.hidden = true; list.innerHTML = ''; return; }
    stepsOf = madeKey(t);
    list.setAttribute('style', listWidths(shown.steps, keep));
    list.innerHTML = lines(shown.steps, 'sub', t.latest, keep);
    list.hidden = false;
  }
  /* Open or close one task in place. The steps grow out of the line and the
     tasks below slide down with them. */
  function toggleSteps(id, want) {
    var t = byId[id];
    if (!t || !openable(t) || !rows[id].isConnected) { return; }
    var now = stepsShown(t).open;
    if (want === undefined) { want = !now; }
    if (want === now) { return; }
    flipped[id] = !flipped[id];
    var a = rows[id], list = $('.subs', a);
    if (want) {
      paintSteps(t);
      if (!REDUCE) {
        /* Cut to its height only while it grows: the rest of the time the
           grips of its lines stand in the margin to their left. */
        list.style.overflow = 'hidden';
        list.animate([{ height: '0px', opacity: 0 }, { height: list.scrollHeight + 'px', opacity: 1 }],
          { duration: 200, easing: 'cubic-bezier(.2,.7,.2,1)' }).onfinish = function () { list.style.overflow = ''; };
      }
      buildStops();
      return;
    }
    if (REDUCE) { paintSteps(t); buildStops(); return; }
    var h = list.offsetHeight;
    a.classList.remove('open');
    list.style.overflow = 'hidden';
    list.animate([{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }],
      { duration: 160, easing: 'ease-in' }).onfinish = function () {
      list.style.overflow = '';
      paintSteps(t);
      buildStops();
    };
  }

  /* ------------------------------------------------------------------ rows */
  /* One element per task for the columns. They are moved, never rebuilt, so a
     task can be seen sliding to its new place, and a change that arrives from
     the server fills the same element again rather than making a new one. */
  var rows = {};
  function fillRow(t) {
    var keep = keeper(t), many = openable(t), s = t.steps.filter(keep)[0];
    var a = rows[t.id];
    a.draggable = !readonly;
    /* Approved for demo mode, with its steps: drawn as it is there (`rouh/demo_style.py`). */
    if (shownNum(t.n)) { a.setAttribute('data-demo-ok', ''); } else { a.removeAttribute('data-demo-ok'); }
    a.innerHTML = (readonly ? '' : GRIP) +
      (many ? '<button type="button" class="tw" aria-expanded="false">' + CHEVRON + '</button>' :
        '<span class="tw" aria-hidden="true"></span>') +
      (t.href ? '<a class="tl" draggable="false" href="' + esc(t.href) + '">' : '<span class="tl">') +
      '<span class="nslot">' + (t.n !== null && t.n !== undefined ? '<span class="num">' + esc(t.n) + '</span>' : '') +
      '</span>' + countMark(many ? countOf(t) : 0) +
      '<span class="tmain"><span class="tline">' + iconMark(t, t.name) + '<span class="tname">' + esc(t.name) +
      '</span>' + demoDot(!!t.demo_shown || shownNum(t.n)) + tagChip(t) +
      statusChip(t) + '</span>' + sourceLine(t) + '</span>' +
      (t.href ? '</a>' : '</span>') +
      /* The rest of the line is the task's own. Until 22 October 2026 it named
         the step worked on last, and Petar, that day (fr_b237d680f820): "do
         NOT show the "Worked on last" sub task on the main row of the task.
         it gets too busy." That step is still marked among its steps when the
         task is opened. A task with nothing to open says "No page yet" only
         when that is true: a task that built its pages in its own folder has
         them on its own page, which its name opens. */
      (!s ? '<span class="latest' + (t.pages ? '' : ' none') + '">' + (t.pages ? '' : 'No page yet') + '</span>' :
        !(s.href || t.href) ? '<span class="latest none">No page yet</span>' : '<span class="latest"></span>') +
      (readonly ? '<span class="cat"><span class="cn"></span></span>' :
        '<button type="button" class="cat" aria-haspopup="menu"><span class="cn"></span></button>') +
      '<span class="racts">' + demoButton(t) + pinButton(t, label(t)) + dotsButton(t) + '</span>' +
      '<ol class="subs" hidden></ol>';
  }
  /* Three dots at the end of every task's line, opening its menu: Rename,
     Move, whose it is, Archive and Delete (`rowMenu`). Until 22 October 2026
     the Archive box sat there on its own, and Petar, that day
     (fr_d2222b1e45af): "I would like to have dot dot dot menu at the end of
     every task. with some options like rename, delete archive, (in the menu
     rather than such icon always displayed)." Shown on the line the pointer
     is on, as the pin is; a phone, with no pointer to rest, always has it. */
  var DOTS_SVG = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">' +
    '<circle cx="5.5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="18.5" cy="12" r="1.7"/></svg>';
  /* In demo mode, an eye at the end of every task's line: one press shows the task with its
     steps to the audience, as it is now; another hides it again (`rouh/demo.py`). Petar, 28
     October 2026: "I don't understand how I can make something visible if I wanted to." */
  var EYE_ON = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 ' +
    '21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/></svg>';
  var EYE_OFF = EYE_ON.replace('</svg>', '<path d="M4 20L20 4"/></svg>');
  function demoButton(t) {
    if (readonly || !DEMO.demo || t.n === null || t.n === undefined) { return ''; }
    var on = shownNum(t.n);
    return '<button type="button" class="demo-eye' + (on ? ' on' : '') + '" data-demo-task="' + esc(t.n) +
      '" aria-pressed="' + on + '" title="' + (on ? 'Shown in demo mode. Press to hide it again' :
      'Hidden in demo mode. Press to show it, with its steps, as it is now') + '" aria-label="' +
      esc((on ? 'Hide in demo: ' : 'Show in demo: ') + 'task ' + t.n) + '">' + (on ? EYE_ON : EYE_OFF) + '</button>';
  }
  function dotsButton(t) {
    if (readonly) { return ''; }
    return '<button type="button" class="dots" aria-haspopup="menu" title="Rename, move, archive, delete" ' +
      'aria-label="' + esc('More for ' + label(t)) + '">' + DOTS_SVG + '</button>';
  }
  /* Make an element for every task there is now, fill the ones that are still
     here, and drop the ones that are gone. */
  function buildRows() {
    var seen = {};
    tasks.forEach(function (t) {
      seen[t.id] = true;
      if (!rows[t.id]) {
        var a = document.createElement('article');
        a.className = 'row';
        a.dataset.id = t.id;
        rows[t.id] = a;
        holding.appendChild(a);
      }
      fillRow(t);
    });
    Object.keys(rows).forEach(function (id) {
      if (seen[id]) { return; }
      if (rows[id].parentNode) { rows[id].parentNode.removeChild(rows[id]); }
      delete rows[id];
    });
  }
  function paintRow(t) {
    var a = rows[t.id], c = catOf(t);
    paintCc(a, c);
    var tn = $('.tname', a), was = tn && tn.nextElementSibling;
    if (was && was.classList.contains('was')) { was.remove(); }
    if (tn && wasMark(t)) { tn.insertAdjacentHTML('afterend', wasMark(t)); }
    var btn = $('.cat', a);
    if (btn) {
      $('.cn', btn).textContent = c ? c.name : 'No project';
      btn.title = readonly ? '' : 'Move to another project';
    }
    paintSteps(t);
  }

  /* ------------------------------------------------------ category buttons */
  function renderBar() {
    /* One line of filters, then one line for each column with its projects
       in it. A line that is too long for the screen is swiped sideways
       rather than wrapped, so the columns and their projects take a line
       each however many projects there are: Petar, 1 October 2026, "only
       three lines will be dedicated to categories and their projects"
       (fr_0bfea6b4153f).

       The Archive is first, because it changes what every other button
       counts: a press shows the archived tasks instead of the live ones and
       a second press comes back; a task dragged onto it is archived. Waiting
       on you is drawn only while something is waiting (`paintBar`). */
    var html = '<div class="line">' +
      lab('archive', '<button type="button" class="chip rl-chip archive" data-archive="1">' + boxIcon(false) +
        '<span class="lbl">Archive</span> <span class="c"></span></button>') +
      /* Others' tasks, next to the Archive and like it: a press shows the
         tasks made for other people instead of his own, and a second press
         comes back. Drawn only when some task was made for somebody else. */
      lab('others', '<button type="button" class="chip rl-chip others" data-others="1">' + PEOPLE_SVG +
        '<span class="lbl">Others&rsquo; tasks</span> <span class="c"></span></button>', true) +
      /* And Made by Rouh beside it, the same kind of button: the tasks Rouh's
         own processes made, instead of his. Drawn only when there are some. */
      lab('rouh', '<button type="button" class="chip rl-chip others byrouh" data-rouh="1">' + ROUH_SVG +
        '<span class="lbl">Made by Rouh</span> <span class="c"></span></button>', true) +
      '<button type="button" class="chip rl-chip wait" data-waiting="1" hidden title="' +
      'Only the tasks waiting on you">' +
      WAIT_SVG + 'Waiting on you <span class="c"></span></button>' +
      lab('goals', '<button type="button" class="chip rl-chip goals" data-goals="1" title="Only your goals">' +
        GOAL_SVG + 'Goals <span class="c"></span></button>', true) +
      '<button type="button" class="chip rl-chip demo" data-demo="1" hidden title="' +
      'Only what you approved for demo mode">' + '<i class="demo-dot"></i>Shown in demo <span class="c"></span></button>' +
      '<button type="button" class="chip rl-chip all" data-all="1" title="Every task">All <span class="c"></span></button>';
    /* Manage projects is on the search's line since 22 October 2026, so this
       line is filters and nothing else (fr_d2222b1e45af). */
    html += '</div>';
    /* Every column, a new one with no projects in it yet as well: Work,
       Personal and Rouh are the same kind of thing, and a column left off
       the bar until it holds a project was Rouh missing from this page. */
    sides.forEach(function (s) {
      html += '<div class="line grp">' +
        '<button type="button" class="side" data-side="' + esc(s.id) + '" title="Only ' + esc(s.name) +
        ', across the full width">' + esc(s.name) + ' <span class="c"></span></button>';
      cats.forEach(function (c) {
        if (c.side !== s.id) { return; }
        html += lab('cat:' + c.id, '<button type="button" class="chip rl-chip" data-cat="' + esc(c.id) + '" style="' + ccStyle(c) +
          '" title="' + esc(readonly ? c.name :
            'Only ' + c.name + '. Double-click to rename, right-click for more') +
          '"><i class="dot"></i><span class="lbl">' + esc(c.name) + '</span> <span class="c"></span></button>', true, c);
      });
      html += '</div>';
    });
    bar.innerHTML = html;
  }
  /* One label: its eye in front where it can be hidden, the button, and the
     cross at its end, there while it is the filter pressed and a task can be
     taken off it. Petar, 22 October 2026 (fr_d2222b1e45af): "the label that
     is active should have a |x| at the end and if I drag it on the X a hover
     appears that says "Remove that label" and if I release a task from it, it
     gets removed." So every label a task can be dragged onto, a task can be
     dragged off: a project (to the project a task nobody filed goes to), the
     Archive, Others' tasks and Made by Rouh. A press on the cross, with no
     task, stops filtering by it. */
  /* Drawn by the one label every list with labels uses (`labels.js`, `labels.css`), the Incubator's
     as well, since Petar asked on 3 November 2026 that both be "the same kind of setup". */
  function lab(key, button, eye, c) {
    return window.RouhLabels.html(key, button, { eye: !!eye, style: c ? ccStyle(c) : '',
      tail: readonly ? '' : '<button type="button" class="unlab" data-unlab="' + esc(key) + '" hidden>' +
        '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
        'stroke-width="2.2" stroke-linecap="round"><path d="M7 7l10 10M17 7L7 17"/></svg></button>' });
  }
  function labName(key) {
    if (key === 'archive') { return 'Archive'; }
    if (key === 'others') { return 'Others\u2019 tasks'; }
    if (key === 'rouh') { return 'Made by Rouh'; }
    if (key === 'goals') { return 'Goals'; }
    var c = catById(key.slice(4));
    return c ? c.name : key;
  }
  /* Whether the label is the filter pressed now, and a task can be dragged
     off it: the cross is drawn then and only then. A project's needs
     somewhere for the task to go, and the fallback project has none. */
  function removable(key) {
    if (readonly) { return false; }
    if (key === 'archive') { return shelf; }
    if (key === 'others' || key === 'rouh') { return whose === key; }
    if (key.indexOf('cat:') === 0) {
      var id = key.slice(4);
      return sel.kind === 'cats' && sel.ids.indexOf(id) !== -1 && !!FALLBACK && id !== FALLBACK && !!catById(FALLBACK);
    }
    return false;
  }
  function filtering(key) {
    if (key === 'others' || key === 'rouh') { return whose === key; }
    if (key === 'goals') { return sel.kind === 'goals'; }
    return key.indexOf('cat:') === 0 && sel.kind === 'cats' && sel.ids.indexOf(key.slice(4)) !== -1;
  }
  function unlabTitle(key) {
    var name = labName(key);
    var what = key === 'archive' ? 'bring it back to the live tasks' :
      key === 'others' || key === 'rouh' ? 'take it off ' + name + ': it is yours then' :
      'take it out of ' + name + ': it goes to ' + labName('cat:' + FALLBACK);
    return 'Drop a task here to ' + what + '. Press to stop filtering by ' + name;
  }
  function paintLabs() {
    $$('.lab', bar).forEach(function (l) {
      var key = l.dataset.lab, eye = $('.eye', l), x = $('.unlab', l), name = labName(key);
      /* Not dimmed while it is the filter pressed, which shows its tasks. */
      if (eye) { window.RouhLabels.paint(l, { off: !!hide[key], name: name, bright: filtering(key) }); }
      if (x) {
        x.hidden = !removable(key);
        x.title = unlabTitle(key);
        x.setAttribute('aria-label', 'Remove a task from ' + name);
      }
      l.classList.toggle('xed', !!x && !x.hidden);
    });
  }
  function counts() {
    var byCat = {}, bySide = {}, total = 0, waiting = 0, goals = 0, archived = 0, others = 0, rouh = 0, demo = 0;
    cats.forEach(function (c) { byCat[c.id] = 0; });
    sides.forEach(function (s) { bySide[s.id] = 0; });
    tasks.forEach(function (t) {
      if (!matchesQuery(t)) { return; }
      /* Others' tasks and Made by Rouh count those on this side of the
         Archive, drawn or not, so on his own side each says how many there are
         over there. */
      if (onShelf(t) && seen(t, 'others')) { others++; }
      if (onShelf(t) && seen(t, 'rouh')) { rouh++; }
      if (!seen(t)) { return; }
      /* The Archive's own count is of every archived task the search finds,
         from either side, so a search on the live side says how many more
         are in the Archive. */
      if (t.archived) { archived++; }
      if (!onShelf(t)) { return; }
      var c = catOf(t);
      if (c) { byCat[c.id]++; }
      if (isGoal(t)) { goals++; }
      if (inDemo(t)) { demo++; }
      if (eyeHidden(t)) { return; }
      total++;
      if (isWaiting(t)) { waiting++; }
      if (c) { bySide[c.side]++; }
    });
    return { byCat: byCat, bySide: bySide, total: total, waiting: waiting, goals: goals, archived: archived, demo: demo,
      others: others, rouh: rouh };
  }
  function paintBar(k) {
    $$('.chip[data-cat]', bar).forEach(function (b) {
      var id = b.dataset.cat, n = k.byCat[id] || 0, on = sel.kind === 'cats' && sel.ids.indexOf(id) !== -1;
      $('.c', b).textContent = n;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on);
      b.classList.toggle('zero', !!query && n === 0);
    });
    $$('.side', bar).forEach(function (b) {
      var on = sel.kind === 'side' && sel.id === b.dataset.side;
      $('.c', b).textContent = k.bySide[b.dataset.side] || 0;
      b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on);
    });
    var wait = $('.chip.wait', bar), waitOn = sel.kind === 'waiting';
    var anyWaiting = pool().some(isWaiting);
    wait.hidden = !anyWaiting && !waitOn;
    var goal = $('.chip.goals', bar), goalOn = sel.kind === 'goals';
    goal.parentNode.hidden = !pool().some(isGoal) && !goalOn;
    $('.c', goal).textContent = k.goals;
    goal.classList.toggle('on', goalOn);
    goal.setAttribute('aria-pressed', goalOn);
    goal.classList.toggle('zero', !!query && k.goals === 0);
    var dchip = $('.chip.demo', bar), demoOn = sel.kind === 'demo';
    dchip.hidden = !pool().some(inDemo) && !demoOn;
    $('.c', dchip).textContent = k.demo;
    dchip.classList.toggle('on', demoOn);
    dchip.setAttribute('aria-pressed', demoOn);
    $('.c', wait).textContent = k.waiting;
    wait.classList.toggle('on', waitOn);
    wait.setAttribute('aria-pressed', waitOn);
    wait.classList.toggle('zero', !!query && k.waiting === 0);
    var all = $('.chip.all', bar);
    $('.c', all).textContent = k.total;
    all.classList.toggle('on', sel.kind === 'all');
    all.setAttribute('aria-pressed', sel.kind === 'all');
    all.title = shelf ? 'Every archived task' : 'Every task';
    var arch = $('.chip.archive', bar);
    $('.c', arch).textContent = k.archived;
    arch.classList.toggle('on', shelf);
    arch.setAttribute('aria-pressed', shelf);
    arch.classList.toggle('zero', !!query && k.archived === 0);
    [['others', '.chip[data-others]', 'The tasks made for other people, by email or Telegram, instead of your own'],
      ['rouh', '.chip[data-rouh]', 'The tasks Rouh\u2019s own processes made, instead of your own']]
      .forEach(function (one) {
        var w = one[0], b = $(one[1], bar), on = whose === w;
        b.parentNode.hidden = !on && !tasks.some(function (t) { return seen(t, w); });
        $('.c', b).textContent = k[w];
        b.classList.toggle('on', on);
        b.setAttribute('aria-pressed', on);
        b.classList.toggle('zero', !!query && k[w] === 0);
        b.title = on ? 'Back to your own tasks' : one[2] + (readonly ? '' : '. Drag a task here to put it there');
      });
    arch.title = shelf ? 'Back to the live tasks' :
      readonly ? 'The archived tasks, instead of the live ones' :
      'The archived tasks, instead of the live ones. Drag a task here to archive it';
    paintLabs();
  }

  /* ------------------------------------------------------------------- tip */
  /* A few words about whatever the pointer is on, the moment it is on it and
     over everything else on the page: any element with `data-tip="..."`.
     The browser's own title waits a second or two and is drawn in its own
     plain box, and Petar, 22 October 2026, of the step count: "make the
     hover appear immediately and on top ... make it nice because this hover
     we will reuse for other things on that page". One element for the whole
     page, above what it is about and centred on it, below it when there is
     no room above, and never past the edge of the screen. A mouse shows it,
     and the keyboard does on whatever has the focus; a finger has no hover,
     so a phone never leaves one standing. */
  var tipEl = null, tipFor = null;
  function showTip(t) {
    var words = t.getAttribute('data-tip');
    if (!words) { hideTip(); return; }
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.id = 'tip';
      tipEl.className = 'tip';
      tipEl.setAttribute('role', 'tooltip');
      document.body.appendChild(tipEl);
    }
    if (tipFor && tipFor !== t) { tipFor.removeAttribute('aria-describedby'); }
    tipFor = t;
    t.setAttribute('aria-describedby', 'tip');
    tipEl.textContent = words;
    tipEl.classList.remove('on');
    var r = t.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight, gap = 8,
      vw = document.documentElement.clientWidth, mid = r.left + r.width / 2,
      below = r.top - h - gap < 6, x = Math.max(6, Math.min(vw - w - 6, mid - w / 2));
    tipEl.style.left = Math.round(x) + 'px';
    tipEl.style.top = Math.round(below ? r.bottom + gap : r.top - h - gap) + 'px';
    tipEl.style.setProperty('--arrow', Math.round(Math.max(10, Math.min(w - 10, mid - x))) + 'px');
    tipEl.classList.toggle('below', below);
    tipEl.classList.add('on');
  }
  function hideTip() {
    if (tipFor) { tipFor.removeAttribute('aria-describedby'); tipFor = null; }
    if (tipEl) { tipEl.classList.remove('on'); }
  }
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') { return; }
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (t === tipFor) { return; }
    if (t) { showTip(t); } else { hideTip(); }
  });
  document.documentElement.addEventListener('pointerleave', hideTip);
  document.addEventListener('focusin', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (t && t.matches(':focus-visible')) { showTip(t); }
  });
  document.addEventListener('focusout', function (e) { if (tipFor && tipFor.contains(e.target)) { hideTip(); } });
  document.addEventListener('pointerdown', hideTip, true);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { hideTip(); } }, true);
  window.addEventListener('scroll', hideTip, true);

  /* ---------------------------------------------------------------- render */
  function render(animate) {
    closeMenu(false);
    hideTip();
    /* The board is emptied and filled again below, and while it is empty the
       page is a screen high: anything that measures in between (the folds,
       the steps) lets the browser pull the scroll up to fit it. Pressing a
       pin or an archive box halfway down the list threw the page back
       towards the top, and Petar, 1 October 2026: "any time I press pin on
       anything I get scrolled to the top" (fr_0bfea6b4153f). So the page
       keeps its height until the board is whole again, and stays put.
       Safari still dropped the scroll to the top while the board was being
       refilled, height or no height ("When I press pin the page still jumps
       to the top", fr_0d42d0359c2d), so where the page was is taken first and
       put back before anything is painted. */
    var tall = document.body.style.minHeight, y = window.scrollY;
    document.body.style.minHeight = document.documentElement.scrollHeight + 'px';
    var before = null;
    if (animate && !REDUCE) {
      before = new Map();
      tasks.forEach(function (t) {
        var r = rows[t.id];
        if (r && r.isConnected && !r.hidden) { before.set(r, r.getBoundingClientRect()); }
      });
    }
    tasks.forEach(paintRow);
    var k = counts();
    paintBar(k);
    var here = pool();
    var asked = here.filter(function (t) { return inSel(t) && matchesQuery(t); });
    var shown = asked.filter(function (t) { return !eyeHidden(t); });
    /* The Archive is in the order things went into it, the newest first. */
    if (shelf) { shown.sort(function (x, y) { return (y.archived_at || 0) - (x.archived_at || 0); }); }
    document.body.classList.toggle('shelf', shelf);
    document.body.classList.toggle('othersside', !!whose);
    paintShelf(here.length);
    q.placeholder = shelf && whose === 'others' ? 'Search others\u2019 archived tasks' :
      shelf && whose === 'rouh' ? 'Search the archived tasks Rouh made' :
      shelf ? 'Search the archived tasks' : whose === 'others' ? 'Search others\u2019 tasks' :
      whose === 'rouh' ? 'Search the tasks Rouh made' :
      'Filter by task, step, title or project';
    var focusView = sel.kind !== 'all';
    board.innerHTML = '';
    tasks.forEach(function (t) { holding.appendChild(rows[t.id]); });
    board.hidden = false;
    if (focusView) { renderFocus(shown); } else { renderOverview(shown); }
    alignColumns();
    emptyEl.textContent = whose === 'others' && !here.length ? (shelf ? 'Nothing made for other people is archived.' :
      'No task here was made for somebody else.') :
      whose === 'rouh' && !here.length ? (shelf ? 'Nothing Rouh made is archived.' : 'Rouh has made no task here.') :
      shelf && !here.length ? 'Nothing is archived yet. ' +
      (readonly ? '' : 'Archive a task with the box at the end of its line, or drag it onto Archive.') :
      !query && !here.length ? 'Nothing has been filed into this workspace yet.' :
      asked.length ? plural(asked.length, 'task') + ' here ' + (asked.length === 1 ? 'is' : 'are') +
      ' hidden by a crossed eye. Press the eye in front of its label to show ' +
      (asked.length === 1 ? 'it.' : 'them.') :
      'Nothing matches. Clear the search, or press Esc to see every project.';
    emptyEl.hidden = shown.length !== 0 || (!query && here.length !== 0 && !asked.length);
    if ((shelf || whose) && !here.length && !query) { board.hidden = true; }
    document.body.style.minHeight = tall;
    if (window.scrollY !== y) { window.scrollTo(window.scrollX, y); }
    if (before) { flip(before); }
    buildStops();
    paintTools();
    /* A pointer resting on a category button keeps showing that category,
       including on anything this render has just drawn. */
    if (peekTest) { peek(peekTest); }
  }

  /* The line over the list while the Archive, Others' tasks or Made by Rouh
     is showing, so none is ever mistaken for his own live tasks, with the way
     back from each on it. On Made by Rouh it has a button for each process
     that made some, with how many, which narrows the list to that one. */
  var shelfEl = null;
  function paintShelf(n) {
    if (!shelfEl) {
      shelfEl = document.createElement('div');
      shelfEl.className = 'shelfhead';
      shelfEl.id = 'shelf';
      board.parentNode.insertBefore(shelfEl, board);
    }
    shelfEl.hidden = !shelf && !whose;
    if (shelfEl.hidden) { return; }
    var note = shelf ? 'Kept whole, with their subtasks.' +
      (readonly ? '' : ' Open one, search them, or bring one back with the box on its line.') : '';
    if (whose === 'others') {
      note = 'Made for other people, by email or Telegram, each marked with who it was for.' +
        (note ? ' ' + note : '');
    }
    var procs = '';
    if (whose === 'rouh') {
      var by = {}, names = {};
      tasks.forEach(function (t) {
        if (!onShelf(t) || !seen(t, 'rouh', '') || !matchesQuery(t)) { return; }
        var of = processesOf(t);
        Object.keys(of).forEach(function (k) { by[k] = (by[k] || 0) + 1; names[k] = of[k]; });
      });
      var keys = Object.keys(by).sort(function (x, y) { return by[y] - by[x] || (names[x] < names[y] ? -1 : 1); });
      if (proc && keys.indexOf(proc) === -1) { keys.push(proc); names[proc] = proc; by[proc] = 0; }
      procs = keys.length > 1 || proc ? '<span class="procs" role="group" aria-label="Which process made them">' +
        keys.map(function (k) {
          var on = proc === k;
          return '<button type="button" class="chip rl-chip proc' + (on ? ' on' : '') + '" data-proc="' + esc(k) +
            '" aria-pressed="' + on + '" title="' + esc(on ? 'Every process again' : 'Only what ' + names[k] + ' made') +
            '">' + esc(names[k]) + ' <span class="c">' + by[k] + '</span></button>';
        }).join('') + '</span>' : '';
    }
    var icon = (shelf ? boxIcon(false) : '') + (whose === 'others' ? PEOPLE_SVG : whose === 'rouh' ? ROUH_SVG : '');
    shelfEl.innerHTML = icon +
      '<b>' + esc(sideWords()) + '</b><span class="c">' +
      plural(n, shelf ? 'archived task' : 'task') + '</span>' +
      (note ? '<span class="note">' + esc(note) + '</span>' : '') + procs +
      (whose ? '<button type="button" class="back mine">Back to your tasks' +
        (shelf ? '' : ' <kbd>esc</kbd>') + '</button>' : '') +
      (shelf ? '<button type="button" class="back live">Back to live tasks' +
        (whose ? '' : ' <kbd>esc</kbd>') + '</button>' : '');
  }
  function setShelf(on) {
    if (shelf === on) { return; }
    shelf = on;
    setSel(sel);
  }
  /* His own tasks (""), Others' tasks or Made by Rouh. The rows are filled
     again, because which step a task's line names depends on the side. */
  function setWhose(w) {
    if (whose === w) { return; }
    whose = w;
    proc = '';
    buildRows();
    setSel(sel);
  }
  function setProc(p) {
    if (proc === p) { return; }
    proc = p;
    buildRows();
    setSel(sel);
  }

  /* One panel: a heading, its rows, and the line that folds what is past 50. */
  function panel(key, head, list, emptyText) {
    var col = document.createElement('section');
    col.className = 'col';
    col.innerHTML = '<header class="colhead">' + head + '</header><div class="rows"></div>';
    var box = $('.rows', col);
    list.forEach(function (t) { var r = rows[t.id]; r.hidden = false; box.appendChild(r); });
    if (!list.length && emptyText) {
      var none = document.createElement('p');
      none.className = 'none';
      none.textContent = emptyText;
      col.appendChild(none);
    }
    var fold = document.createElement('button');
    fold.type = 'button';
    fold.className = 'fold';
    fold.hidden = true;
    fold.dataset.key = key;
    col.appendChild(fold);
    return col;
  }

  /* Every task is in a project, so there is no heading for the ones that are
     not: a task nobody filed is filed by the model, and one it cannot place
     goes to Miscellaneous (`rouh/filing.py`). Petar asked for the "Not sorted"
     section gone on 23 September 2026 - "The AI should be sorting whether a
     task is in one project or another" - and it is gone from the data as well
     as from here, which is the only way it stays gone. */
  function renderOverview(shown) {
    var used = usedSides();
    var mineOf = function (s) { return shown.filter(function (t) { var c = catOf(t); return c && c.side === s.id; }); };
    /* A column with projects but nothing to show - nothing in it matches the
       search, nothing in it is archived - is one line, the same as a column
       with no projects, and goes after the columns that have tasks to show.
       Drawn as a full panel in its place it pushed the one task that did
       match off a phone's screen, where the columns stand one under another:
       searching for "email" put Work and Personal saying "Nothing here
       matches" above Rouh, and task 74 under the keyboard, and Petar, 1
       October 2026: "It is not displaying 74- how Rouh handles email"
       (fr_76280d8ad25c). */
    var full = used.filter(function (s) { return mineOf(s).length > 0; });
    var empty = used.filter(function (s) { return full.indexOf(s) < 0; });
    board.style.setProperty('--cols', Math.max(1, full.length));
    /* A column with no projects in it yet - a new one, as Rouh was on 29
       September 2026 - is drawn first, the whole width across and one line
       high, so it is on the page with the others without taking their width;
       under the others it was two screens down. It holds no task, since a
       task is always in a project. Then the columns with tasks to show, side
       by side, and last the ones with none. */
    sides.filter(function (s) { return used.indexOf(s) < 0; }).concat(full, empty).forEach(function (s) {
      var bare = used.indexOf(s) < 0;
      var mine = mineOf(s);
      var col = panel('s:' + s.id, '<button type="button" class="sidebtn" data-side="' + esc(s.id) + '" title="Only ' +
        esc(s.name) + ', across the full width">' + esc(s.name) + '</button><span class="c">' + mine.length +
        '</span>', mine, bare ? (readonly ? 'No projects in it yet.' : 'No projects in it yet. Add one with Manage projects.')
          : query ? 'Nothing here matches.' : shelf ? 'Nothing archived here.' :
          whose === 'others' ? 'None made for others here.' : whose === 'rouh' ? 'None made by Rouh here.' :
          'No tasks yet.');
      col.dataset.side = s.id;
      if (bare || !mine.length) { col.classList.add('bare'); }
      board.appendChild(col);
    });
    /* A workspace with no projects in it has no column for a task to be in,
       and that is the one time a task is not under a heading. It is said
       rather than left off the page, because a task that is simply not drawn
       is the bug this page keeps being asked to stop having. */
    if (!used.length && shown.length) {
      var none = document.createElement('p');
      none.className = 'none';
      none.textContent = shown.length + (shown.length === 1 ? ' task is' : ' tasks are') +
        ' in no project yet. Add one with Manage projects.';
      board.appendChild(none);
    }
    board.hidden = !sides.length && !shown.length;
    foldColumns();
  }

  /* Every list's task numbers, counts and names in three columns: the number
     slot as wide as the widest number in the list and the count slot as the
     biggest count, so the name after task 1 starts where the name after task
     10003 does (Petar, 22 October 2026, fr_092ef8f8682b). */
  function alignColumns() {
    $$('main .col').forEach(function (col) {
      var w = 1, c = 1;
      $$('.row', col).forEach(function (r) {
        var t = byId[r.dataset.id];
        if (!t) { return; }
        if (t.n !== null && t.n !== undefined) { w = Math.max(w, String(t.n).length); }
        if (openable(t)) { c = Math.max(c, String(countOf(t)).length); }
      });
      col.style.setProperty('--numw', w);
      col.style.setProperty('--cntw', c);
    });
  }

  function foldColumns() {
    $$('main .col').forEach(function (col) {
      var fold = $('.fold', col);
      if (!fold) { return; }
      var key = fold.dataset.key, rs = $$('.row', $('.rows', col)), extra = rs.length - FOLD_AT;
      rs.forEach(function (r, i) { r.hidden = extra > 0 && !unfolded[key] && i >= FOLD_AT; });
      fold.hidden = extra <= 0;
      if (extra > 0) {
        fold.textContent = unfolded[key] ? 'Fold the ' + extra + ' older task' + (extra === 1 ? '' : 's') + ' ▴' :
          extra + ' earlier task' + (extra === 1 ? '' : 's') + ' ▾';
      }
    });
  }

  /* One project, one column, Goals or Waiting on you: one panel the full
     width, of the very lines the columns are made of, so every task is open
     or closed exactly as it was in the columns, and its arrow opens it here
     as it does there. Until 15 October 2026 this was a card for each task
     with every one of its steps listed, and Petar, that day
     (fr_449b45afdff4): "When I filter in the tasks, the result is that the
     tasks expand and I see all their sub tasks. Please don't do that. Don't
     unfold them automatically, they should stay as they are". */
  function renderFocus(shown) {
    var dots = sel.kind === 'cats' ? sel.ids.map(function (id) {
      return '<i class="dot" style="' + ccStyle(catById(id)) + '"></i>';
    }).join('') : sel.kind === 'waiting' ? '<span class="tmark" data-mark="waiting" aria-hidden="true">' + WAIT_SVG + '</span>'
      : sel.kind === 'goals' ? '<span class="tmark" data-mark="goal" aria-hidden="true">' + GOAL_SVG + '</span>' : '';
    /* A project's name is the person's own, and demo mode blurs it; the rest are Rouh's words. */
    var head = dots + '<b' + (sel.kind === 'cats' ? '' : ' data-ui') + '>' + esc(selLabel()) + '</b><span class="c">' +
      plural(shown.length, 'task') +
      '</span><button type="button" class="back">Both columns <kbd>esc</kbd></button>';
    var none = query ? '' : sel.kind === 'waiting' ? 'Nothing is waiting on you.' :
      sel.kind === 'demo' ? 'Nothing is approved for demo mode yet. A task\u2019s menu has Show in demo.' :
      sel.kind === 'goals' ? 'No goals yet. Rouh\u2019s Goals page makes one.' :
      shelf ? 'Nothing in ' + selLabel() + ' is archived.' :
      whose === 'others' ? 'Nothing in ' + selLabel() + ' was made for somebody else.' :
      whose === 'rouh' ? 'Nothing in ' + selLabel() + ' was made by Rouh.' :
      'No tasks in ' + selLabel() + ' yet.' + (readonly ? '' : ' Drag one onto its button.');
    var col = panel('f:' + viewOf(sel), head, shown, none);
    col.classList.add('focus');
    board.style.setProperty('--cols', 1);
    board.appendChild(col);
    foldColumns();
  }

  /* Moved rows slide from where they were to where they are now. */
  function flip(before) {
    tasks.forEach(function (t) {
      var r = rows[t.id];
      if (!r || !r.isConnected || r.hidden) { return; }
      var b = before.get(r), a = r.getBoundingClientRect();
      if (!b) {
        r.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: 'ease-out' });
        return;
      }
      var dx = b.left - a.left, dy = b.top - a.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) { return; }
      r.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }],
        { duration: 260, easing: 'cubic-bezier(.2,.7,.2,1)' });
    });
  }

  /* ---------------------------------------------------------- the keyboard */
  /* The cursor remembers which task, and which of its pages, it is on - not a
     position in a list - so opening a task never makes it jump. */
  function holderOf(el) { return el.closest('[data-id]'); }
  function keyOf(el) {
    return { id: holderOf(el).dataset.id, href: el.classList.contains('tl') ? null : el.getAttribute('href') };
  }
  function elOf(k) {
    if (!k) { return null; }
    for (var i = 0; i < stops.length; i++) {
      var e = stops[i];
      if (holderOf(e).dataset.id !== k.id) { continue; }
      if (k.href === null ? e.classList.contains('tl') : (!e.classList.contains('tl') && e.getAttribute('href') === k.href)) {
        return e;
      }
    }
    return null;
  }
  function buildStops() {
    stops = $$('main .col .row:not([hidden]) .tl, main .col .row:not([hidden]) .subs:not([hidden]) a.sub');
    // Not the steps inside a branch that is folded away.
    stops = stops.filter(function (e) { return !e.closest('ol.kids[hidden]'); });
    if (cursorKey && !elOf(cursorKey) && cursorKey.href !== null) { cursorKey = { id: cursorKey.id, href: null }; }
    if (cursorKey && !elOf(cursorKey)) { cursorKey = null; }
    if (!cursorKey && query && stops.length) { cursorKey = keyOf(stops[0]); }
    paintCursor(false);
  }
  function paintCursor(scroll) {
    $$('.row.on, .sub.on').forEach(function (e) { e.classList.remove('on'); });
    var el = elOf(cursorKey);
    if (!el) { return; }
    var target = el.classList.contains('tl') ? holderOf(el) : el;
    target.classList.add('on');
    if (scroll) { target.scrollIntoView({ block: 'nearest' }); }
  }
  function moveCursor(step) {
    if (!stops.length) { return; }
    var i = stops.indexOf(elOf(cursorKey));
    i = i < 0 ? (step > 0 ? 0 : stops.length - 1) : (i + step + stops.length) % stops.length;
    cursorKey = keyOf(stops[i]);
    paintCursor(true);
  }
  /* The keyboard follows the highlight: a button clicked earlier lets go of
     it, so Enter and Space act on what is highlighted. */
  function letGo() {
    var a = document.activeElement;
    if (a && a !== q && a !== document.body && a.blur) { a.blur(); }
  }
  /* <- and -> go to the same place in the column beside, as the eye moves
     between Work and Personal. From anywhere else they go to the top of one. */
  function switchColumn(dir) {
    var cols = $$('.col', board);
    if (!cols.length) { return; }
    var el = elOf(cursorKey), row = el && holderOf(el), col = row && row.closest('.col');
    var at = col ? cols.indexOf(col) : -1, index = 0, target;
    if (at === -1) {
      target = cols[dir > 0 ? cols.length - 1 : 0];
    } else {
      target = cols[at + dir];
      index = $$('.row:not([hidden])', col).indexOf(row);
    }
    var list = target ? $$('.row:not([hidden])', target) : [];
    if (!list.length) { return; }
    cursorKey = { id: list[Math.min(Math.max(index, 0), list.length - 1)].dataset.id, href: null };
    paintCursor(true);
  }
  /* Space opens or closes the highlighted task; on one of its steps, it
     closes the task and goes back to its line. */
  function space() {
    var el = elOf(cursorKey);
    if (!el) { return; }
    var holder = holderOf(el);
    if (!el.classList.contains('tl')) {
      cursorKey = { id: holder.dataset.id, href: null };
      toggleSteps(holder.dataset.id, false);
      paintCursor(true);
      return;
    }
    toggleSteps(holder.dataset.id);
  }
  /* What Enter opens. A click rather than location.href: the page is sandboxed
     when Rouh frames it, so the link is handed up to the page around the frame,
     which is signed in and loads it (pages.follow_script). */
  function open(el) {
    if (!el) { return; }
    el.click();
  }

  /* -------------------------------------------------------------- the menu */
  /* The one menu every three dots in Rouh open (`menu.js`, put into this page
     ahead of this script), filled from a list: a heading, a rule, or an item
     with an icon by name - or a project's colour where a menu of projects has
     one - its words, and a short note at the end. `danger` is what cannot be
     undone, which goes last, under a rule, in red. */
  function openMenu(anchor, items) {
    menu.innerHTML = items.map(function (it, i) {
      if (it.heading) { return '<div class="menu-head">' + esc(it.heading) + '</div>'; }
      if (it.rule) { return '<hr class="menu-rule">'; }
      return '<button type="button" class="menu-item' + (it.danger ? ' danger' : '') + '" role="menuitem" data-i="' + i + '"' +
        (it.disabled ? ' disabled' : '') + (it.icon ? ' data-icon="' + esc(it.icon) + '"' : '') +
        (it.color ? ' style="--cc:' + colorVal(it.color) + '"' : '') + '>' +
        (it.color ? '<i class="dot"></i>' : '') +
        '<span class="menu-name">' + esc(it.label) + '</span>' +
        (it.note ? '<span class="menu-note">' + esc(it.note) + '</span>' : '') + '</button>';
    }).join('');
    window.RouhMenu.dress(menu);
    menu.hidden = false;
    menuFor = { anchor: anchor, items: items };
    window.RouhMenu.place(menu, anchor, 'start');
    window.RouhMenu.first(menu);
  }
  function closeMenu(restore) {
    if (menu.hidden) { return; }
    menu.hidden = true;
    var a = menuFor && menuFor.anchor;
    menuFor = null;
    if (restore && a && a.isConnected) { a.focus(); }
  }
  menu.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-i]');
    if (!b || !menuFor) { return; }
    var it = menuFor.items[+b.dataset.i];
    closeMenu(false);
    it.action();
  });
  menu.addEventListener('keydown', function (e) {
    if (window.RouhMenu.keys(menu, e)) { return; }
    if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); closeMenu(true); }
  });
  document.addEventListener('mousedown', function (e) {
    if (!menu.hidden && !menu.contains(e.target)) { closeMenu(false); }
  });

  function moveMenu(id, anchor) {
    var t = byId[id], cur = catOf(t), items = [];
    usedSides().forEach(function (s) {
      items.push({ heading: 'Move to · ' + s.name });
      cats.forEach(function (c) {
        if (c.side !== s.id) { return; }
        var here = !!cur && c.id === cur.id;
        items.push({ label: c.name, color: c.color, disabled: here, note: here ? 'here now' : '',
          action: function () { moveTask(id, c.id); } });
      });
    });
    if (!cats.length) { items.push({ label: 'No projects yet: add one with Manage projects', disabled: true }); }
    openMenu(anchor, items);
  }

  /* A task's own menu, from the three dots at the end of its line. Delete is
     Rouh's own: it asks what else goes with the task, stops what is running
     under it and says so before anything goes (`askDelete` in app.js), and
     this page is loaded again once it has. */
  function rowMenu(id, anchor) {
    var t = byId[id];
    if (!t) { return; }
    var k = kindOf(t), items = [
      { label: 'Rename', icon: 'rename', action: function () { renameTask(id); } },
      { label: 'Move to another project', icon: 'move', action: function () { moveMenu(id, anchor); } }];
    if (!k) {
      items.push({ label: 'Put in Made by Rouh', icon: 'rouh', action: function () { setWhoseTask(id, 'process'); } });
    } else {
      items.push({ label: k === 'rouh' ? 'Take off Made by Rouh' : 'Take off Others\u2019 tasks',
        icon: k === 'rouh' ? 'rouh' : 'people', note: 'it is yours then',
        action: function () { setWhoseTask(id, 'person'); } });
    }
    items.push(t.archived ?
      { label: 'Bring back from the Archive', icon: 'unarchive', action: function () { archiveTask(id, false); } } :
      { label: 'Archive', icon: 'archive', note: 'with its subtasks', action: function () { archiveTask(id, true); } });
    /* Demo mode (`rouh/demo.py`): let an audience see it, as it is now, with its steps; take
       that back; or make a copy of it to make safe by hand, shown only in demo mode. */
    var ref = t.n !== null && t.n !== undefined ? String(t.n) : (t.href || '');
    items.push({ rule: true });
    items.push({ label: shownNum(t.n) ? 'Show in demo as it is now' : 'Show in demo', icon: 'demo',
      note: 'with its steps', action: function () { toRouh({ type: 'rouh-page-demo', act: 'approve', kind: 'task', ref: ref }); } });
    if (shownNum(t.n)) {
      items.push({ label: 'Hide in demo', icon: 'demo', action: function () {
        toRouh({ type: 'rouh-page-demo', act: 'unapprove', kind: 'task', ref: ref });
      } });
    }
    items.push({ label: 'Make a demo copy', icon: 'demo', note: 'shown only in demo mode', action: function () {
      toRouh({ type: 'rouh-page-demo', act: 'copy', kind: 'task', ref: ref });
    } });
    items.push({ rule: true });
    items.push({ label: 'Delete', icon: 'delete', danger: true, action: function () {
      toRouh({ type: 'rouh-page-task', act: 'delete', task: id, name: label(t) });
    } });
    openMenu(anchor, items);
  }
  /* What is approved now, said back by Rouh after a press above or a change elsewhere. */
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== 'rouh-frame-demo' || e.source !== window.parent) { return; }
    DEMO = { on: !!m.on, demo: DEMO.demo, shown: m.shown || [] };
    DEMO_SHOWN = {};
    DEMO.shown.forEach(function (n) { DEMO_SHOWN[String(n)] = true; });
    buildRows();
    render(false);
  });
  /* Rename, from the menu: the name becomes a text field in its place. Enter
     or leaving it keeps what was typed; Escape puts the name back. Only the
     title changes: the folder keeps its name (`owning.rename`). */
  function renameTask(id) {
    var t = byId[id], a = rows[id], tl = a && $('.tl', a);
    if (!t || !tl) { return; }
    var box = document.createElement('span');
    box.className = 'tl renaming';
    box.innerHTML = (t.n !== null && t.n !== undefined ? '<span class="num">' + esc(t.n) + '</span>' : '') +
      '<input class="tren" maxlength="200" aria-label="Name of the task">';
    var input = $('input', box);
    input.value = t.name;
    tl.replaceWith(box);
    a.draggable = false;
    input.focus();
    input.select();
    var done = false;
    function finish(keep) {
      if (done) { return; }
      done = true;
      var v = input.value.replace(/\s+/g, ' ').trim(), old = t.name;
      if (!keep || !v || v === old) { fillRow(t); paintRow(t); return; }
      t.name = v;
      var held = hold(id, { name: v });
      fillRow(t);
      paintRow(t);
      post({ action: 'rename_task', task: id, name: v }, held).then(function () {
        render(false);
      }).catch(function (err) {
        var now = byId[id];
        if (!held.settled && now) { now.name = old; }
        settle(held);
        buildRows();
        render(false);
        fail(err.message);
      });
    }
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', function () { finish(true); });
  }

  function chipMenu(b) {
    var c = catById(b.dataset.cat);
    var n = tasks.filter(function (t) { var x = catOf(t); return x && x.id === c.id; }).length;
    var items = [{ heading: c.name }, { label: 'Rename', icon: 'rename', action: function () { startRename(c.id); } }];
    /* Every other column, not the first of them: there are three since Rouh
       became one, and "the other one" stopped being a single place. */
    sides.forEach(function (other) {
      if (other.id === c.side) { return; }
      items.push({ label: 'Put under ' + other.name, icon: 'swap', action: function () {
        change({ action: 'side', id: c.id, side: other.id });
      } });
    });
    items.push({ label: 'Manage projects', icon: 'settings', action: function () { openManager(b); } });
    // Last and under a rule, as on every menu in Rouh.
    items.push({ rule: true });
    items.push({ label: 'Delete', icon: 'delete', danger: true, disabled: n > 0, note: n > 0 ? 'only when empty' : '',
      action: function () { deleteCat(c.id); } });
    openMenu(b, items);
  }

  /* ------------------------------------------------------- saving to disk */
  /* Every change goes to Rouh, which writes the `owns` link and moves the
     folder with `git mv`, and hands back the whole index as it is afterwards -
     so two tabs, or an agent moving a folder, cannot leave the page showing
     something that is not saved.

     A sandboxed frame cannot fetch, so the request is handed to the page
     around it, which is signed in (pages.FILE_MESSAGE, and fileRelay in
     app.js). It names an action and ids, never an address. */
  function adopt(doc) {
    if (!doc || !doc.categories) { return; }
    sides = doc.sides || [];
    cats = doc.categories || [];
    tasks = (doc.tasks || []).slice();
    reindex();
    /* What was sent and is not answered yet is still drawn as sent. The
       changes go one at a time, so the answer to one is the index from before
       the next was written: drawn as it came, it put back a task archived a
       moment later, which then left again when its own answer came - three
       tasks archived in a row flickered in and out, and a press landing on
       one that had come back did nothing (29 September 2026). */
    pending.forEach(function (p) {
      if (p.apply) { p.apply(); return; }
      var t = pinTarget(p.id);
      if (t) { Object.keys(p.set).forEach(function (k) { t[k] = p.set[k]; }); }
    });
    buildRows();
  }
  /* The changes drawn ahead of their answer: `{id, set}`, the fields as the
     page drew them. Each goes when its own answer arrives, just before the
     index that answer carries is drawn, so the index is then the truth about
     it (`settle`). */
  var pending = [];
  function hold(id, set) {
    var p = { id: id, set: set, settled: false };
    pending.push(p);
    return p;
  }
  function settle(p) {
    p.settled = true;
    pending = pending.filter(function (x) { return x !== p; });
  }
  var waiting = {}, seq = 0;
  /* Changes go one at a time, in order, so an answer that arrives late can
     never draw an older state over a newer one. */
  var queue = Promise.resolve();
  function post(body, held) {
    var sent = queue.then(function () {
      return new Promise(function (ok, no) {
        if (readonly) { no(new Error('This page is read-only at its own address. Open the task browser in Rouh to change anything.')); return; }
        var id = 'f' + (++seq), parent;
        try { parent = window.parent; } catch (e) { parent = null; }
        if (!parent || parent === window) { no(new Error('Rouh could not be reached.')); return; }
        var slot = { ok: ok, no: no, held: held };
        slot.timer = setTimeout(function () {
          if (waiting[id]) { delete waiting[id]; no(new Error('Rouh did not answer.')); }
        }, 120000);
        waiting[id] = slot;
        try { parent.postMessage({ type: ASK, id: id, body: body }, '*'); }
        catch (e) { delete waiting[id]; clearTimeout(slot.timer); no(new Error('Rouh could not be reached.')); }
      });
    });
    queue = sent.catch(function () { /* the caller reports it */ });
    return sent;
  }
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || m.type !== TOLD) { return; }
    var slot = waiting[m.id];
    if (!slot) { return; }
    delete waiting[m.id];
    clearTimeout(slot.timer);
    /* Settled here only when the answer says what is saved. A refusal with
       no index, which is every change while Rouh cannot be reached, leaves
       it to the caller, which puts back what the page had drawn ahead of
       the answer: settled here, a task archived while Rouh was away stayed
       gone from the list although it never was archived. */
    if (slot.held && (m.ok || m.index)) { settle(slot.held); }
    if (m.index) { adopt(m.index); }
    if (m.ok) { slot.ok(m); return; }
    /* Cancelled by the person in a box Rouh asked in (Move to new task's
       name): nothing was changed, and nothing is said. */
    var no = new Error(m.error || 'The change was not saved.');
    no.cancelled = !!m.cancelled;
    slot.no(no);
  });

  /* Save it, and when the server has said what is on disk, draw that; if it
     refuses, draw what it has instead and say why.

     A change that worked says nothing: what it changed on the screen is the
     answer. Every one of them used to say so at the foot of the page, with
     an Undo, and since the changes go one at a time a few quick ones said so
     one after another for half a minute, each long after the press (Petar,
     22 October 2026, fr_1b64390a0545: "I think those notifications should be
     removed. Only if error happens"). `news` is the one exception, a function
     of what the server answered for when it knows something the page does
     not: deleting a project says where its kept notes went, and only the
     server knows there were any (`objectindex._delete_project`). */
  function change(body, afterRender, news) {
    return post(body).then(function (out) {
      renderBar();
      render(true);
      refreshManager();
      if (afterRender) { afterRender(); }
      var words = news ? news(out || {}) : '';
      if (words) { toast(words); }
    }).catch(function (err) {
      renderBar();
      render(true);
      refreshManager();
      fail(err.message);
    });
  }
  /* A task taken off a label, by dropping it on the label's cross. */
  function unlabel(id, key) {
    if (key === 'archive') { archiveTask(id, false); return; }
    if (key === 'others' || key === 'rouh') { setWhoseTask(id, 'person'); return; }
    if (key.indexOf('cat:') === 0 && FALLBACK) { moveTask(id, FALLBACK); }
  }
  /* Whose a task is, said by the person: "person", his own; "process", made
     by Rouh; "other", made for somebody else (`task_origin.set_by_person`).
     Nothing marks it again afterwards, so a task he takes off Made by Rouh
     stays his. */
  function whoseOf(t) { var k = kindOf(t); return k === 'rouh' ? 'process' : k === 'others' ? 'other' : 'person'; }
  function setWhoseTask(id, to) {
    var t = byId[id];
    if (!t) { return; }
    if (whoseOf(t) === to) {
      toast(label(t) + (to === 'process' ? ' is with Made by Rouh already' : to === 'other' ?
        ' is with Others\u2019 tasks already' : ' is yours already'));
      return;
    }
    /* Said by the task leaving the list it was on, as every change here is
       (`change`). */
    change({ action: 'mine', task: id, to: to });
  }
  function moveTask(id, catId) {
    var t = byId[id], old = t.category || null;
    if (old === catId) { return; }
    /* Drawn at once, so the task is seen landing; the answer replaces it with
       what is really on disk, folder and all. */
    t.category = catId;
    var held = hold(id, { category: catId });
    land(id, true);
    /* The task was shown landing, and scrolled to, at the press. The answer
       comes seconds later when other changes are ahead of it, and only
       draws what is saved, where the person now is: scrolling to the task
       again then took the page away from whatever they had moved on to. */
    post({ action: 'move', task: id, owner: catId }, held).then(function () {
      renderBar();
      render(true);
    }).catch(function (err) {
      // With no answer at all nothing said what it is, so it goes back.
      var now = byId[id];
      if (!held.settled && now) { now.category = old; }
      settle(held);
      render(true);
      fail(err.message);
    });
  }
  /* Archive a task, or bring it back. It leaves the list it was on at once;
     Rouh archives it and every subtask under it (`rouh/archiving.py`) and
     answers with the index as it is afterwards, which is then drawn. */
  function archiveTask(id, on) {
    var t = byId[id];
    if (!t || !!t.archived === on) { return; }
    var was = { archived: t.archived, at: t.archived_at, on: t.archived_on };
    var set = { archived: on, archived_at: on ? Date.now() / 1000 : 0, archived_on: on ? 'now' : '' };
    Object.keys(set).forEach(function (k) { t[k] = set[k]; });
    var held = hold(id, set);
    if (cursorKey && cursorKey.id === id) { cursorKey = null; }
    render(true);
    post({ action: 'archive', task: id, on: on }, held).then(function () {
      renderBar();
      render(true);
    }).catch(function (err) {
      var now = byId[id];
      if (!held.settled && now) {
        now.archived = was.archived;
        now.archived_at = was.at;
        now.archived_on = was.on;
      }
      settle(held);
      render(true);
      fail(err.message);
    });
  }
  /* Archive one subtask from its line. It leaves the list at once; Rouh
     answers with the index as it is afterwards, which no longer has it or
     anything under it. */
  function archiveStep(id, on) {
    var s = pinTarget(id);
    if (on && (!s || s.gone)) { return; }
    var held = on ? hold(id, { gone: true }) : null;
    if (on) { s.gone = true; render(false); }
    post({ action: 'archive', task: id, on: on }, held).then(function () {
      render(false);
    }).catch(function (err) {
      var now = pinTarget(id);
      if (held && !held.settled && now) { now.gone = false; }
      if (held) { settle(held); }
      render(false);
      fail(err.message);
    });
  }
  /* A subtask's menu, from the three dots on its line. */
  function stepMenu(id, anchor) {
    if (!pinTarget(id)) { return; }
    openMenu(anchor, [
      { label: 'Move to new task', icon: 'newtask', action: function () { moveStep(id, '+new'); } },
      { label: 'Promote to task', icon: 'promote', action: function () { moveStep(id, '+task'); } }]);
  }
  /* The task a step is directly in, or null for one deeper down. */
  function taskOfStep(id) {
    for (var i = 0; i < tasks.length; i++) {
      if ((tasks[i].steps || []).some(function (s) { return s.id === id; })) { return tasks[i]; }
    }
    return null;
  }
  /* The task that holds a step however deep, or the step's own row once it
     is a task. */
  function holderOfStep(id) {
    if (byId[id]) { return byId[id]; }
    for (var i = 0; i < tasks.length; i++) {
      if (stepIn(tasks[i].steps || [], id)) { return tasks[i]; }
    }
    return null;
  }
  /* A subtask moved: onto the task `where` names, or out of its task as the
     first subtask of a new one (`+new`) or as a task of its own (`+task`,
     `rouh/moving.py`). Rouh renumbers it and answers with the index, and the
     place it landed is opened and marked, under its new number. */
  /* A subtask put under another task on the screen, before Rouh has answered:
     taken off the list it was in, given the number it will have there - the
     task's number and one past its highest subtask, with the subtasks inside
     it wearing the new number in front of theirs - and put first among that
     task's subtasks. Rouh's answer then draws what it really did. Petar, 22
     October 2026: "it disappears from the old one, but doesn't appear
     immediately in the new one ... should immediately be moved, and then
     whatever other things need to be going on, can go in the background."
     Done again on every index drawn while the answer is on its way (`adopt`),
     and nothing when it is there already. */
  function placeStep(id, toId) {
    var to = byId[toId];
    if (!to) { return false; }
    if ((to.steps || []).some(function (x) { return x.id === id; })) { return true; }
    var found = null;
    function walk(list) {
      for (var i = 0; i < list.length && !found; i++) {
        if (list[i].id === id) { found = list.splice(i, 1)[0]; return; }
        walk(list[i].kids || []);
      }
    }
    tasks.forEach(function (t) { if (!found) { walk(t.steps || []); } });
    if (!found) { return false; }
    var was = String(found.num || ''), front = was.split('-')[0], high = 0;
    (to.steps || []).forEach(function (x) {
      var m = /^\d+-(\d+)$/.exec(String(x.num || ''));
      if (m) { high = Math.max(high, parseInt(m[1], 10)); }
    });
    var now = to.n !== null && to.n !== undefined ? to.n + '-' + (high < 9 ? '0' : '') + (high + 1) : '';
    found.num = now;
    if (was && now && (found.was || []).indexOf(was) === -1) { found.was = (found.was || []).concat([was]); }
    if (front && now) {
      (function renum(list) {
        list.forEach(function (k) {
          if (String(k.num || '').indexOf(front + '-') === 0) { k.num = String(to.n) + k.num.slice(front.length); }
          renum(k.kids || []);
        });
      })(found.kids || []);
    }
    found.gone = false;
    to.steps = [found].concat(to.steps || []);
    return true;
  }
  function moveStep(id, where) {
    var s = pinTarget(id);
    if (!s) { return; }
    if (byId[where]) { moveStepTo(id, where); return; }
    /* A new task is named first, in Rouh's box over the page (`askTaskName`
       in app.js), so the line stays where it is until it has been. */
    var naming = where === '+new';
    var held = naming ? null : hold(id, { gone: true });
    if (!naming) { s.gone = true; render(false); }
    post({ action: 'move_step', task: id, where: where, label: stepName(s), title: s.title }, held).then(function () {
      var t = holderOfStep(id);
      if (!t) { render(true); return; }
      if (t.id !== id && openable(t)) { flipped[t.id] = true; }
      land(t.id, true);
      var li = rows[t.id] && rows[t.id].querySelector('li.br[data-step-id="' + id + '"] > .sline');
      if (li) { li.classList.remove('flash'); void li.offsetWidth; li.classList.add('flash'); }
    }).catch(function (err) {
      var now = pinTarget(id);
      if (held && !held.settled && now) { now.gone = false; }
      if (held) { settle(held); }
      render(false);
      if (!err.cancelled) { fail(err.message); }
    });
  }
  /* Onto a task: drawn there at once and marked (`placeStep`), and the move
     made in the background. If Rouh says no, the index it answers with puts
     it back where it was, and why is said. */
  function moveStepTo(id, toId) {
    var before = JSON.stringify(tasks);
    var held = hold(id, {});
    held.apply = function () { placeStep(id, toId); };
    if (!placeStep(id, toId)) { settle(held); return; }
    buildRows();
    var t = byId[toId];
    if (openable(t)) { flipped[toId] = true; }
    land(toId, true);
    var li = rows[toId] && rows[toId].querySelector('li.br[data-step-id="' + id + '"] > .sline');
    if (li) { li.classList.remove('flash'); void li.offsetWidth; li.classList.add('flash'); }
    post({ action: 'move_step', task: id, where: toId }, held).then(function () {
      render(false);
    }).catch(function (err) {
      // With no answer at all nothing said what is saved: as it was, then.
      if (!held.settled) { settle(held); tasks = JSON.parse(before); reindex(); buildRows(); }
      render(false);
      fail(err.message);
    });
  }
  /* A task, or a step of one however deep, by its id. */
  function pinTarget(id) {
    if (byId[id]) { return byId[id]; }
    for (var i = 0; i < tasks.length; i++) {
      var found = stepIn(tasks[i].steps || [], id);
      if (found) { return found; }
    }
    return null;
  }
  /* Pin one task or step to the Control Room, or unpin it. Only the pin
     itself changes, so only the pin is drawn again, in place: nothing else on
     the page moves, and the amber pin is all the answer there is. It used to
     rebuild every line at the press, and Safari threw the list back to its
     top (`render`), and then say "Pinned ... to the Control Room" at the foot
     of the screen (Petar, 1 October 2026, fr_0d42d0359c2d: "When I press pin
     the page still jumps to the top ... Also, we don't need notification for
     that"). The answer carries the index, which fills every line again
     (`adopt`), so the page is drawn once more then, where it stands. If Rouh
     says no, the pin goes back and the reason is the one thing said. */
  function pinObj(id, on) {
    var o = pinTarget(id);
    if (!o || !!o.pinned === on) { return; }
    o.pinned = on;
    paintPin(id);
    var held = hold(id, { pinned: on });
    post({ action: 'pin', task: id, on: on }, held).then(function () {
      render(false);
    }).catch(function (err) {
      var now = pinTarget(id);
      if (!held.settled && now) { now.pinned = !on; }
      settle(held);
      render(false);
      paintPin(id);
      fail(err.message);
    });
  }
  /* Every pin on the page for that one task or step, drawn as it now is. */
  function paintPin(id) {
    var o = pinTarget(id);
    if (!o) { return; }
    var on = !!o.pinned, name = o.name !== undefined ? label(o) : stepName(o);
    Array.prototype.forEach.call(document.querySelectorAll('button.pin[data-pin]'), function (b) {
      if (b.dataset.pin !== id) { return; }
      b.setAttribute('aria-pressed', on);
      b.title = pinTitle(on);
      b.setAttribute('aria-label', (on ? 'Unpin ' : 'Pin ') + name);
    });
  }
  /* Re-draw, then make sure the task is visible where it landed and flash it. */
  function land(id, animate) {
    render(animate);
    var r = rows[id];
    if (r && r.isConnected && r.hidden) {
      var col = r.closest('.col'), fold = col && $('.fold', col);
      if (fold) { unfolded[fold.dataset.key] = true; render(false); }
    }
    if (r && r.isConnected && !r.hidden) {
      r.classList.remove('flash');
      void r.offsetWidth;
      r.classList.add('flash');
      r.scrollIntoView({ block: 'nearest' });
    }
  }
  function deleteCat(id) {
    var gone = catById(id);
    if (!gone) { return; }
    if (sel.kind === 'cats' && sel.ids.indexOf(id) !== -1) {
      var ids = sel.ids.filter(function (x) { return x !== id; });
      sel = ids.length ? { kind: 'cats', ids: ids } : { kind: 'all' };
    }
    /* What the server did, when it has more to say than that the project
       went: a project's kept notes are not deleted with it and go back to
       the general memory, and the person is told so rather than finding out.
       The project leaving the list is the whole answer otherwise. */
    change({ action: 'delete', id: id }, null, function (out) {
      var said = out && out.did;
      return said ? said.charAt(0).toUpperCase() + said.slice(1) : '';
    });
  }

  /* One line at the foot of the page, said at once and over whatever it said
     before. It is fixed to the window, so it never moves the list under it.
     A change that fails says so here (`fail`); one that works says nothing. */
  var failed = 0;
  function toast(text, bad, times) {
    clearTimeout(toastTimer);
    toastEl.innerHTML = (times > 1 ? '<b class="times">' + times + '\u00d7</b>' : '') + '<span>' + esc(text) + '</span>';
    toastEl.classList.toggle('bad', !!bad);
    var fresh = toastEl.hidden;
    toastEl.hidden = false;
    if (fresh && !REDUCE) {
      toastEl.animate([{ opacity: 0, transform: 'translate(-50%,8px)' }, { opacity: 1, transform: 'translate(-50%,0)' }],
        { duration: 160, easing: 'ease-out' });
    }
    toastTimer = setTimeout(function () { toastEl.hidden = true; failed = 0; }, bad ? 9000 : 6000);
  }
  /* A change that was not made. Several failing together, as every change
     does while Rouh cannot be reached, are one line with how many, rather
     than a line for each in turn. */
  function fail(why) {
    failed = toastEl.hidden || !toastEl.classList.contains('bad') ? 1 : failed + 1;
    toast(why, true, failed);
  }

  /* ------------------------------------------------- managing the projects */
  /* One list to rename, describe, move between the columns, add and delete the
     projects inside Work and Personal. Every change is saved as it is made.
     Nothing is picked for the person: a new project has no column until they
     choose one.

     What belongs in a project is a field again, and it is the same field when
     the project is made and when it is edited: the description. It is written
     for two readers. A person reading this list sees what each project is
     actually for, and the model that files a new task reads the same words to
     decide where the task goes (`rouh/filing.py`). A project nobody has
     described still works - its name is often enough - and the field is why
     "Buy" and "Misc" stop being a coin toss.

     The colour is worked out from the project's place in its column until the
     person picks one, which they do by pressing its dot: the page's seven as
     quick choices, and any colour at all, from the system's colour picker or
     typed as a hex value (Petar, fr_0e0dcb5b0c7b). A pick is kept on the
     project and wins; Default gives it back to its place. */
  var manageEl = null, manageFrom = null, addSide = null, pickFor = null;
  var PRESETS = [['blue', 'Blue'], ['amber', 'Amber'], ['teal', 'Teal'], ['rose', 'Rose'],
    ['violet', 'Violet'], ['green', 'Green'], ['slate', 'Slate']];
  /* The page's own colours as hex, for the colour picker to start from. */
  function hexOf(name) {
    if (/^#[0-9a-f]{6}$/i.test(name || '')) { return name.toLowerCase(); }
    var v = getComputedStyle(document.documentElement).getPropertyValue('--cat-' + name).trim().toLowerCase();
    return /^#[0-9a-f]{6}$/.test(v) ? v : '#72a6f7';
  }
  /* A hex value as typed, `#abc` or `3a7bd5` or `#3A7BD5`, as `#rrggbb`; or
     null when it is not one. */
  function typedHex(v) {
    v = String(v || '').trim().toLowerCase().replace(/^#/, '');
    if (/^[0-9a-f]{3}$/.test(v)) { v = v.replace(/./g, '$&$&'); }
    return /^[0-9a-f]{6}$/.test(v) ? '#' + v : null;
  }
  /* A colour that sits too close to the page's own near-black: said, never
     refused, because it is the person's to choose. Under 3:1 against the
     background is WCAG's line for anything that is not body text. */
  function tooDark(hex) {
    var l = lightness(hex);
    return l !== null && (l + 0.05) / (lightness('#0a0c10') + 0.05) < 3;
  }
  function colourPick(c) {
    var picked = c.picked || '', custom = /^#/.test(picked);
    var hex = hexOf(c.color);
    return '<div class="cpick" role="group" aria-label="Colour of ' + esc(c.name) + '">' +
      '<button type="button" class="cp-def" data-color="" aria-pressed="' + !picked + '" ' +
        'title="The colour its place in its column gives it">Default</button>' +
      PRESETS.map(function (p) {
        return '<button type="button" class="cp-sw" data-color="' + p[0] + '" aria-pressed="' + (picked === p[0]) +
          '" aria-label="' + p[1] + '" title="' + p[1] + '" style="--cc:var(--cat-' + p[0] + ')"></button>';
      }).join('') +
      '<label class="cp-custom" title="Any colour"><span class="cp-sw cp-any" aria-pressed="' + custom + '"' +
        (custom ? ' style="--cc:' + hex + '"' : '') + '>' +
        '<input type="color" class="cp-wheel" aria-label="Custom colour" value="' + hex + '"></span>' +
        '<span class="cp-lbl">Custom</span></label>' +
      '<input class="cp-hex" maxlength="7" spellcheck="false" autocomplete="off" aria-label="Hex colour" ' +
        'placeholder="#rrggbb" value="' + (custom ? esc(picked) : '') + '">' +
      '<button type="button" class="cp-save" disabled title="Save the custom colour">Save</button>' +
      '<p class="cp-why"' + (custom && tooDark(picked) ? '' : ' hidden') + '>Dark colours are hard to see on this page.</p>' +
      '</div>';
  }
  function saveColour(c, color) {
    var old = c.picked || '';
    if (color === old) { renderBar(); render(true); refreshManager(); return; }
    change({ action: 'color', id: c.id, color: color }, function () { flashRow(c.id); });
  }
  /* A colour picked or typed, not saved yet: the dot and the Custom swatch
     show it, the hex field says it, and Save is lit. Nothing is written until
     Save, or Enter in the hex field. Petar, 22 October 2026
     (fr_d2222b1e45af): "the custom color picker needs a save. currently I
     have to click on the circle that triggers custom color which is on the
     bottom under the actual custom picker palette." Until then a colour from
     the picker was saved when the picker said `change`, which Safari says only
     once its palette is closed, by a click somewhere else. */
  function previewColour(row, hex) {
    paintCc(row, { color: hex });
    var any = $('.cp-any', row);
    any.style.setProperty('--cc', hex);
    $('.cp-why', row).hidden = !tooDark(hex);
    var save = $('.cp-save', row), c = catById(row.dataset.id);
    if (save) { save.disabled = !c || hex === c.picked; }
  }
  function saveCustom(row) {
    var c = catById(row.dataset.id), hexEl = $('.cp-hex', row);
    if (!c || !hexEl) { return; }
    var hex = typedHex(hexEl.value) || ($('.cp-wheel', row) || {}).value;
    if (!typedHex(hex)) { fail('That is not a colour. Type one like #3a7bd5.'); return; }
    hexEl.value = typedHex(hex);
    saveColour(c, typedHex(hex));
  }
  function togglePick(id) {
    pickFor = pickFor === id ? null : id;
    renderManager();
    var row = $('.mgr-row[data-id="' + id + '"]', manageEl);
    if (!row) { return; }
    (pickFor ? $('.cpick [aria-pressed="true"]', row) || $('.cp-def', row) : $('.sw', row)).focus();
  }
  /* The same limit the server keeps (`objectindex.DESCRIPTION_MAX`), so the
     field stops where the write stops rather than silently losing the end of
     a sentence somebody typed. */
  var DESC_MAX = 1000;
  var DESC_HINT = 'What goes in here, in your own words. A new task is filed by what this says.';
  function sidePick(current) {
    return '<span class="sidepick" role="group" aria-label="Column">' + sides.map(function (s) {
      return '<button type="button" data-side="' + esc(s.id) + '" aria-pressed="' + (s.id === current) + '">' +
        esc(s.name) + '</button>';
    }).join('') + '</span>';
  }
  function openManager(from) {
    closeMenu(false);
    manageFrom = from || document.activeElement;
    if (!manageEl) {
      manageEl = document.createElement('div');
      manageEl.className = 'mgr-overlay';
      manageEl.id = 'manage';
      document.body.appendChild(manageEl);
      manageEl.addEventListener('mousedown', function (e) { if (e.target === manageEl) { closeManager(); } });
      manageEl.addEventListener('click', onManageClick);
      manageEl.addEventListener('keydown', onManageKey);
      manageEl.addEventListener('focusout', function (e) {
        if (e.target.matches('.mgr-row input.nm, .mgr-row textarea')) { saveField(e.target); }
      });
      manageEl.addEventListener('input', function (e) {
        if (e.target.closest('.mgr-add')) { paintAdd(); }
        var row = e.target.closest('.mgr-row');
        if (e.target.matches('.cp-wheel')) { previewColour(row, e.target.value); $('.cp-hex', row).value = e.target.value; }
        if (e.target.matches('.cp-hex')) {
          var hex = typedHex(e.target.value);
          if (hex) { previewColour(row, hex); $('.cp-wheel', row).value = hex; }
        }
      });
      /* The colour picker let go of: shown, waiting for Save. */
      manageEl.addEventListener('change', function (e) {
        var row = e.target.closest('.mgr-row');
        if (row && e.target.matches('.cp-wheel')) {
          previewColour(row, e.target.value.toLowerCase());
          $('.cp-hex', row).value = e.target.value.toLowerCase();
        }
      });
      /* A press anywhere else in the list puts the colours away, and only
         them: the list is not drawn again under the press, which would take
         the button being pressed away before its click. */
      manageEl.addEventListener('mousedown', function (e) {
        if (!pickFor || e.target.closest('.cpick, .sw')) { return; }
        pickFor = null;
        $$('.cpick', manageEl).forEach(function (p) {
          var r = p.closest('.mgr-row');
          paintCc(r, catById(r.dataset.id));
          p.remove();
        });
        $$('.sw[aria-expanded="true"]', manageEl).forEach(function (b) { b.setAttribute('aria-expanded', 'false'); });
      });
    }
    addSide = null;
    pickFor = null;
    manageEl.hidden = false;
    renderManager();
    $('.mgr', manageEl).focus();
  }
  function closeManager() {
    if (!manageEl || manageEl.hidden) { return; }
    var active = document.activeElement;
    if (active && active.matches && active.matches('.mgr-row input.nm, .mgr-row textarea')) {
      saveField(active);
    }
    pickFor = null;
    manageEl.hidden = true;
    var back = manageFrom && manageFrom.isConnected ? manageFrom : $('#manageBtn');
    if (back) { back.focus(); }
  }
  function refreshManager() { if (manageEl && !manageEl.hidden) { renderManager(); } }
  function renderManager() {
    var active = manageEl.contains(document.activeElement) ? document.activeElement : null;
    var keep = active && active.dataset.field ? { id: active.closest('[data-id]') ? active.closest('[data-id]').dataset.id : null,
      field: active.dataset.field, start: active.selectionStart, end: active.selectionEnd } : null;
    var old = $('.mgr-add', manageEl);
    var pending = old ? { name: $('.nm', old).value, description: $('.ds', old).value }
      : { name: '', description: '' };
    var held = {};
    tasks.forEach(function (t) { var c = catOf(t); if (c) { held[c.id] = (held[c.id] || 0) + 1; } });
    var names = sides.map(function (s) { return esc(s.name); });
    var either = names.length > 1 ? names.slice(0, -1).join(', ') + ' or ' + names[names.length - 1] : names.join('');
    var html = '<div class="mgr" role="dialog" aria-modal="true" aria-labelledby="mgr-title" tabindex="-1">' +
      '<header class="mgr-head"><h2 id="mgr-title">Projects</h2><p>Each project sits in one column, ' + either +
      '. A task filed into one is a folder inside it, and moving it here moves the folder.' +
      '</p><p class="mgr-why">The description says what belongs in the project. ' +
      'It is read by the small model (Haiku) that files each new task, so the plainer it is, ' +
      'the more often a new task lands here by itself.' +
      '</p><button type="button" class="mgr-x" aria-label="Close">×</button></header>' +
      '<div class="mgr-cols" aria-hidden="true"><span></span><span>Name</span><span>Column</span>' +
      '<span>Tasks</span><span></span></div>';
    sides.forEach(function (s) {
      var mine = cats.filter(function (c) { return c.side === s.id; });
      if (!mine.length) { return; }
      html += '<div class="mgr-group">' + esc(s.name) + '</div>';
      mine.forEach(function (c) {
        var n = held[c.id] || 0;
        html += '<div class="mgr-row" data-id="' + esc(c.id) + '" style="' + ccStyle(c) + '">' +
          '<button type="button" class="sw" aria-expanded="' + (pickFor === c.id) + '" aria-label="Colour of ' +
            esc(c.name) + '" title="Pick a colour"><i class="dot"></i></button>' +
          '<input class="nm" data-field="name" maxlength="60" aria-label="Name" value="' + esc(c.name) + '">' +
          sidePick(c.side) +
          '<span class="n">' + plural(n, 'task') + '</span>' +
          '<button type="button" class="del"' + (n ? ' disabled title="Move its ' + plural(n, 'task') +
            ' to another project first"' : ' title="Delete ' + esc(c.name) + '"') + '>Delete</button>' +
          (pickFor === c.id ? colourPick(c) : '') +
          '<label class="ds-wrap"><span>What belongs in ' + esc(c.name) + '</span>' +
          '<textarea class="ds" data-field="description" rows="2" maxlength="' + DESC_MAX + '" ' +
          'placeholder="' + esc(DESC_HINT) + '">' + esc(c.description || '') + '</textarea></label></div>';
      });
    });
    if (!cats.length) { html += '<p class="none">No projects yet. Add the first one below.</p>'; }
    /* A div rather than a form, and a button rather than a submit. The page
       is sandboxed with `allow-scripts` and nothing else, so the browser
       refuses a form submission before the submit event is fired: a form here
       would be an Add button that did nothing and said nothing. */
    html += '<div class="mgr-add"><span class="sw" aria-hidden="true"></span>' +
      '<input class="nm" data-field="new-name" maxlength="60" aria-label="Name of the new project" placeholder="New project">' +
      sidePick(addSide) +
      '<span class="n"></span><button type="button" class="go">Add</button>' +
      '<label class="ds-wrap"><span>What belongs in it</span>' +
      '<textarea class="ds" data-field="new-description" rows="2" maxlength="' + DESC_MAX + '" ' +
      'placeholder="' + esc(DESC_HINT) + '"></textarea></label>' +
      '<p class="why" hidden>Pick ' + either + ' for it first.</p></div>' +
      '<footer class="mgr-foot"><span>Every change is saved as you make it, to the object database and the folders. ' +
      'A description is saved when you click away from it.</span>' +
      '<button type="button" class="done">Done</button></footer></div>';
    manageEl.innerHTML = html;
    /* The Column cell is as wide as the widest picker, measured, because each
       row is a grid of its own and the header above them has to line up: two
       columns fitted 150px, and the third, Rouh, ran over the task count. */
    var pickW = 0;
    $$('.sidepick', manageEl).forEach(function (p) { pickW = Math.max(pickW, p.scrollWidth); });
    $('.mgr', manageEl).style.setProperty('--pickw', Math.max(150, Math.ceil(pickW)) + 'px');
    $('.mgr-add .nm', manageEl).value = pending.name;
    $('.mgr-add .ds', manageEl).value = pending.description;
    paintAdd();
    if (keep) {
      var back = keep.id ? $('.mgr-row[data-id="' + keep.id + '"] [data-field="' + keep.field + '"]', manageEl) :
        $('.mgr-add [data-field="' + keep.field + '"]', manageEl);
      if (back) {
        back.focus();
        try { back.setSelectionRange(keep.start, keep.end); } catch (e) { /* not a text field */ }
      }
    }
  }
  function paintAdd() {
    var row = $('.mgr-add', manageEl), name = $('.nm', row).value.trim();
    $('.go', row).disabled = !name || !addSide;
    $('.why', row).hidden = !(name && !addSide);
  }
  function flashRow(id) {
    var r = manageEl && $('.mgr-row[data-id="' + id + '"]', manageEl);
    if (!r) { return; }
    r.classList.remove('saved');
    void r.offsetWidth;
    r.classList.add('saved');
  }
  /* A name is saved when the field is left, or on Enter; a description when it
     is left, because Enter inside it is a new line and belongs to the person. */
  function saveField(input) {
    var row = input.closest('.mgr-row'), c = row && catById(row.dataset.id);
    if (!c) { return; }
    if (input.dataset.field === 'description') { saveDescription(input, c); return; }
    var value = input.value.trim(), old = c.name;
    if (value === old || value === input.dataset.sent) { return; }
    if (!value) { input.value = c.name; fail('A project needs a name.'); return; }
    input.dataset.sent = value;
    change({ action: 'rename', id: c.id, name: value }, function () { flashRow(c.id); });
  }
  /* An empty description is a real answer - it is what every project has until
     somebody writes one - so it is saved like any other. */
  function saveDescription(box, c) {
    var value = box.value.trim(), old = c.description || '';
    if (value === old || value === box.dataset.sent) { return; }
    box.dataset.sent = value;
    change({ action: 'describe', id: c.id, description: value }, function () { flashRow(c.id); });
  }
  function onManageClick(e) {
    var t = e.target;
    if (t.closest('.mgr-x') || t.closest('.done')) { closeManager(); return; }
    if (t.closest('.mgr-add .go')) { addProject(); return; }
    var pickBtn = t.closest('.sidepick button');
    if (pickBtn && t.closest('.mgr-add')) {
      addSide = pickBtn.dataset.side;
      $$('.mgr-add .sidepick button', manageEl).forEach(function (b) { b.setAttribute('aria-pressed', b === pickBtn); });
      paintAdd();
      $('.mgr-add .nm', manageEl).focus();
      return;
    }
    var row = t.closest('.mgr-row'), c = row && catById(row.dataset.id);
    if (!c) { return; }
    if (t.closest('.sw')) { togglePick(c.id); return; }
    if (t.closest('.cp-save')) { saveCustom(row); return; }
    var sw = t.closest('.cpick button[data-color]');
    if (sw) { saveColour(c, sw.dataset.color); return; }
    if (pickBtn) {
      if (pickBtn.dataset.side !== c.side) {
        change({ action: 'side', id: c.id, side: pickBtn.dataset.side }, function () { flashRow(c.id); });
      }
      return;
    }
    var del = t.closest('.del');
    if (del && !del.disabled) { deleteCat(c.id); }
  }
  function onManageKey(e) {
    e.stopPropagation();
    var t = e.target;
    if (e.key === 'Escape') {
      e.preventDefault();
      if (pickFor && t.closest && t.closest('.cpick, .sw')) { togglePick(pickFor); return; }
      if (t.matches && t.matches('.mgr-row input.nm, .mgr-row textarea')) {
        var was = catById(t.closest('.mgr-row').dataset.id);
        t.value = t.dataset.field === 'description' ? (was.description || '') : was.name;
        $('.mgr', manageEl).focus();
        return;
      }
      closeManager();
      return;
    }
    if (e.key === 'Enter' && t.matches && t.matches('.cp-hex')) {
      e.preventDefault();
      saveCustom(t.closest('.mgr-row'));
      return;
    }
    if (e.key === 'Enter' && t.matches && t.matches('.mgr-row input.nm')) {
      e.preventDefault();
      saveField(t);
      return;
    }
    if (e.key === 'Enter' && t.matches && t.matches('.mgr-add input')) {
      e.preventDefault();
      addProject();
    }
  }
  function addProject() {
    var form = $('.mgr-add', manageEl), name = $('.nm', form).value.trim(), side = addSide;
    var said = $('.ds', form).value.trim();
    if (!name || !side) { paintAdd(); (side ? $('.nm', form) : $('.sidepick button', form)).focus(); return; }
    var had = cats.map(function (c) { return c.id; });
    post({ action: 'add', name: name, side: side, description: said }).then(function () {
      var added = cats.filter(function (c) { return had.indexOf(c.id) === -1; })[0];
      addSide = null;
      /* Emptied before the list is drawn again, because the list carries the
         box's contents over a redraw so that typing survives a change saved
         somewhere else. What was just added is not still being typed, and a
         name left sitting there is how the same project gets added twice. */
      $('.nm', form).value = '';
      $('.ds', form).value = '';
      renderBar();
      render(true);
      renderManager();
      if (added) { flashRow(added.id); }
      $('.mgr-add .nm', manageEl).focus();
    }).catch(function (err) { renderManager(); fail(err.message); });
  }
  /* The button becomes a small text field in place: Enter keeps, Esc drops. */
  function startRename(id) {
    var b = $('.chip[data-cat="' + id + '"]', bar), c = catById(id);
    if (!b || !c) { return; }
    var box = document.createElement('span');
    box.className = 'chip rl-chip editing';
    paintCc(box, c);
    box.innerHTML = '<i class="dot"></i><input aria-label="Project name" maxlength="60">';
    var input = $('input', box);
    input.value = c.name;
    input.style.width = Math.max(6, c.name.length + 1) + 'ch';
    b.replaceWith(box);
    input.focus();
    input.select();
    var done = false;
    function finish(keep) {
      if (done) { return; }
      done = true;
      var v = input.value.trim(), old = c.name;
      if (keep && v && v !== old) {
        change({ action: 'rename', id: id, name: v });
        return;
      }
      renderBar();
      render(false);
    }
    input.addEventListener('input', function () { input.style.width = Math.max(6, input.value.length + 1) + 'ch'; });
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', function () { finish(true); });
  }

  /* ---------------------------------------------------------------- hover */
  /* Hovering a project shows where its tasks are without moving anything.
     Pressing it ends the preview: the list then shows what was chosen, and
     turning a filter off puts every task back at full strength even though
     the pointer is still resting on the button (fr_4cd37bc2a578). The preview
     comes back only once the pointer is on another button. */
  var peekHeld = null;
  function peek(test) {
    peekTest = test;
    document.body.classList.add('peeking');
    tasks.forEach(function (t) { rows[t.id].classList.toggle('lit', test(t)); });
  }
  function unpeek() {
    peekTest = null;
    document.body.classList.remove('peeking');
    $$('.lit').forEach(function (x) { x.classList.remove('lit'); });
  }
  function peekFrom(el) {
    if (el && el === peekHeld) { return; }
    peekHeld = null;
    if (dragId !== null || !el) { unpeek(); return; }
    if (el.dataset.waiting) { peek(isWaiting); return; }
    if (el.dataset.goals) { peek(isGoal); return; }
    if (el.dataset.cat) { var id = el.dataset.cat; peek(function (t) { var c = catOf(t); return !!c && c.id === id; }); return; }
    if (el.dataset.side) { var s = el.dataset.side; peek(function (t) { var c = catOf(t); return !!c && c.side === s; }); return; }
    unpeek();
  }
  bar.addEventListener('mouseover', function (e) { peekFrom(e.target.closest('.chip[data-cat], .chip[data-waiting], .chip[data-goals], .side')); });
  function leaveBar() { peekHeld = null; unpeek(); }
  bar.addEventListener('mouseleave', leaveBar);
  /* A pointer that jumps straight out of the page, onto the conversation
     beside it, never leaves the bar as far as the bar can tell. */
  document.documentElement.addEventListener('mouseleave', leaveBar);
  document.addEventListener('mouseover', function (e) { if (!bar.contains(e.target)) { leaveBar(); } });
  window.addEventListener('blur', leaveBar);

  /* --------------------------------------------------------------- clicks */
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b || e.detail > 1) { return; }
    if (b.matches('.chip[data-cat], .chip[data-waiting], .chip[data-goals], .side')) { peekHeld = b; unpeek(); }
    if (b.dataset.eye) { toggleEye(b.dataset.eye); return; }
    if (b.dataset.unlab) { stopFiltering(b.dataset.unlab); return; }
    if (b.dataset.archive) { setShelf(!shelf); return; }
    if (b.dataset.others) { setWhose(whose === 'others' ? '' : 'others'); return; }
    if (b.dataset.rouh) { setWhose(whose === 'rouh' ? '' : 'rouh'); return; }
    if (b.dataset.waiting) { setSel(sel.kind === 'waiting' ? { kind: 'all' } : { kind: 'waiting' }); return; }
    if (b.dataset.demo) { setSel(sel.kind === 'demo' ? { kind: 'all' } : { kind: 'demo' }); return; }
    if (b.dataset.goals) { setSel(sel.kind === 'goals' ? { kind: 'all' } : { kind: 'goals' }); return; }
    if (b.dataset.all) { setSel({ kind: 'all' }); return; }
    if (b.classList.contains('side')) {
      var s = b.dataset.side;
      setSel(sel.kind === 'side' && sel.id === s ? { kind: 'all' } : { kind: 'side', id: s });
      return;
    }
    if (b.dataset.cat) {
      var id = b.dataset.cat;
      if (e.metaKey || e.shiftKey || e.ctrlKey) {
        var ids = sel.kind === 'cats' ? sel.ids.slice() : [];
        var at = ids.indexOf(id);
        if (at === -1) { ids.push(id); } else { ids.splice(at, 1); }
        setSel(ids.length ? { kind: 'cats', ids: ids } : { kind: 'all' });
      } else {
        setSel(sel.kind === 'cats' && sel.ids.length === 1 && sel.ids[0] === id ? { kind: 'all' } : { kind: 'cats', ids: [id] });
      }
    }
  });
  /* An eye pressed: that label's tasks out of the list, or back in. Which
     steps a task's line names depends on Others' and Rouh's, so the rows are
     filled again for those. */
  function toggleEye(key) {
    hide[key] = !hide[key];
    if (!hide[key]) { delete hide[key]; }
    if (key === 'others' || key === 'rouh') { buildRows(); }
    setSel(sel);
  }
  /* The cross pressed with no task dropped on it: that label is no longer
     the filter. */
  function stopFiltering(key) {
    if (key === 'archive') { setShelf(false); return; }
    if (key === 'others' || key === 'rouh') { setWhose(''); return; }
    var id = key.slice(4), ids = sel.kind === 'cats' ? sel.ids.filter(function (x) { return x !== id; }) : [];
    setSel(ids.length ? { kind: 'cats', ids: ids } : { kind: 'all' });
  }
  bar.addEventListener('dblclick', function (e) {
    var b = e.target.closest('.chip[data-cat]');
    if (b && !readonly) { e.preventDefault(); startRename(b.dataset.cat); }
  });
  bar.addEventListener('contextmenu', function (e) {
    var b = e.target.closest('.chip[data-cat]');
    if (b && !readonly) { e.preventDefault(); chipMenu(b); }
  });
  /* A press on a step count opens or closes the steps it counts, never the
     link it sits in. Caught on the way down, because the frame's own handler
     for links (`pages.frame_script`) opens the task on the way up before this
     page's would see the press. */
  document.addEventListener('click', function (e) {
    var sc = e.target.closest && e.target.closest('.scount[data-n]');
    if (!sc || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    e.preventDefault();
    e.stopPropagation();
    var sub = sc.closest('.sub'), fb = sub && $(':scope > .stw[data-fold]', sub.parentNode);
    if (fb) { foldStep(fb); } else if (!sub) { toggleSteps(holderOf(sc).dataset.id); }
  }, true);
  document.addEventListener('click', function (e) {
    var pb = e.target.closest('button.pin[data-pin]');
    if (pb) {
      e.preventDefault();
      if (!readonly) { pinObj(pb.dataset.pin, pb.getAttribute('aria-pressed') !== 'true'); }
      return;
    }
    var sf = e.target.closest('button.stw[data-fold]');
    if (sf) { e.preventDefault(); foldStep(sf); return; }
    var tw = e.target.closest('.row button.tw');
    if (tw) { toggleSteps(holderOf(tw).dataset.id); return; }
    var sa = e.target.closest('.arch[data-step]');
    if (sa) { e.preventDefault(); if (!readonly) { archiveStep(sa.dataset.step, true); } return; }
    var sd = e.target.closest('.dots[data-step]');
    if (sd) { e.preventDefault(); if (!readonly) { stepMenu(sd.dataset.step, sd); } return; }
    var eye = e.target.closest('.row .demo-eye');
    if (eye) {
      e.preventDefault();
      toRouh({ type: 'rouh-page-demo', act: eye.classList.contains('on') ? 'unapprove' : 'approve', kind: 'task',
        ref: eye.dataset.demoTask });
      return;
    }
    var dots = e.target.closest('.row .dots');
    if (dots && !readonly) { e.preventDefault(); rowMenu(holderOf(dots).dataset.id, dots); return; }
    if (e.target.closest('.shelfhead .live')) { setShelf(false); return; }
    if (e.target.closest('.shelfhead .mine')) { setWhose(''); return; }
    var pr = e.target.closest('.shelfhead [data-proc]');
    if (pr) { setProc(proc === pr.dataset.proc ? '' : pr.dataset.proc); return; }
    var cat = e.target.closest('.row .cat');
    if (cat && !readonly) { e.preventDefault(); moveMenu(holderOf(cat).dataset.id, cat); return; }
    var sb = e.target.closest('.sidebtn');
    if (sb) {
      setSel(sel.kind === 'side' && sel.id === sb.dataset.side ? { kind: 'all' } : { kind: 'side', id: sb.dataset.side });
      return;
    }
    var fold = e.target.closest('.fold');
    if (fold) { unfolded[fold.dataset.key] = !unfolded[fold.dataset.key]; render(true); return; }
    if (e.target.closest('.col.focus .back')) { setSel({ kind: 'all' }); }
  });

  /* ------------------------------------------------------- drag and drop */
  function clearDrag() {
    document.body.classList.remove('dragging', 'dragstep');
    $$('.ghost, .over, .from, .can').forEach(function (x) { x.classList.remove('ghost', 'over', 'from', 'can'); });
    dragId = null;
    dragStepId = null;
    tip(null);
  }
  /* A subtask dragged onto another task's line becomes that task's next
     subtask (`moveStep`). Petar, 22 October 2026 (fr_676c7ad596fd): "If we
     move a subtask to another task, dragging it would be awesome." Every
     task it can go into is marked while it is held, and the one under it
     lights up; the task it is in now is not one of them. */
  function stepTarget(e) {
    var r = e.target.closest && e.target.closest('.row.can');
    return r || null;
  }
  /* A project's button moves the task there; Archive, on the live side,
     archives it; Others' tasks and Made by Rouh, when the list is not on
     them already, say it is somebody else's or Rouh's; and the cross at the
     end of the label pressed takes the task off it. */
  function dropTarget(e) {
    if (!e.target.closest) { return null; }
    return e.target.closest('.chip[data-cat], .unlab:not([hidden])' + (shelf ? '' : ', .chip.archive') +
      (whose === 'others' ? '' : ', .chip[data-others]') + (whose === 'rouh' ? '' : ', .chip[data-rouh]'));
  }
  /* The words over the cross while a task is held over it. A title is not
     shown in the middle of a drag, and the bar's lines scroll sideways, which
     would cut off anything drawn above them, so it is one element of the
     page's own, placed over the cross. */
  var tipEl = null;
  function tip(over) {
    if (!over) { if (tipEl) { tipEl.hidden = true; } return; }
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'droptip';
      tipEl.setAttribute('role', 'status');
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = 'Remove that label';
    tipEl.hidden = false;
    var r = over.getBoundingClientRect(), w = tipEl.offsetWidth;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
    tipEl.style.top = Math.max(4, r.top - tipEl.offsetHeight - 8) + 'px';
  }
  document.addEventListener('dragstart', function (e) {
    var sl = e.target.closest && e.target.closest('.sline[draggable="true"]');
    if (sl && !readonly) {
      var br = sl.closest('li.br');
      dragStepId = br.dataset.stepId;
      e.stopPropagation();
      try { e.dataTransfer.setData('text/plain', dragStepId); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* old browsers */ }
      closeMenu(false);
      unpeek();
      document.body.classList.add('dragstep');
      sl.classList.add('ghost');
      var home = taskOfStep(dragStepId);
      Object.keys(rows).forEach(function (rid) {
        if ((!home || rid !== home.id) && byId[rid] && !byId[rid].archived) { rows[rid].classList.add('can'); }
      });
      return;
    }
    var h = e.target.closest && e.target.closest('.row');
    if (!h || readonly) { return; }
    dragId = h.dataset.id;
    try { e.dataTransfer.setData('text/plain', dragId); e.dataTransfer.effectAllowed = 'move'; } catch (x) { /* old browsers */ }
    closeMenu(false);
    unpeek();
    document.body.classList.add('dragging');
    h.classList.add('ghost');
    var c = catOf(byId[dragId]), from = c && $('.chip[data-cat="' + c.id + '"]', bar);
    if (from) { from.classList.add('from'); }
  });
  document.addEventListener('dragover', function (e) {
    if (dragStepId !== null) {
      var to = stepTarget(e);
      $$('.row.over').forEach(function (o) { if (o !== to) { o.classList.remove('over'); } });
      if (!to) { return; }
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      to.classList.add('over');
      return;
    }
    if (dragId === null) { return; }
    var t = dropTarget(e);
    $$('.over').forEach(function (o) { if (o !== t) { o.classList.remove('over'); } });
    tip(t && t.dataset.unlab ? t : null);
    if (!t) { return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    t.classList.add('over');
  });
  document.addEventListener('drop', function (e) {
    if (dragStepId !== null) {
      var to = stepTarget(e), sid = dragStepId;
      clearDrag();
      if (!to) { return; }
      e.preventDefault();
      moveStep(sid, to.dataset.id);
      return;
    }
    var t = dropTarget(e);
    if (dragId === null || !t) { return; }
    e.preventDefault();
    var id = dragId, catId = t.dataset.cat;
    clearDrag();
    if (t.dataset.unlab) { unlabel(id, t.dataset.unlab); return; }
    if (t.dataset.archive) { archiveTask(id, true); return; }
    if (t.dataset.rouh) { setWhoseTask(id, 'process'); return; }
    if (t.dataset.others) { setWhoseTask(id, 'other'); return; }
    moveTask(id, catId);
  });
  document.addEventListener('dragend', clearDrag);

  /* ---------------------------------------------- the tools by the search */
  /* Save view: the list as it is now - which labels are hidden with their
     eye, the filter pressed, the Archive or whose tasks - is what the browser
     opens on from now on, on every device, until it is saved again
     (`objectindex.save_view`). Quiet while the list is the saved one, which
     is all it says once it has saved. */
  var saveBtn = $('#saveView'), keysBtn = $('#keysBtn'), keysLine = $('#keysLine');
  function paintTools() {
    if (!saveBtn) { return; }
    var same = fullView(sel) === home();
    saveBtn.disabled = same;
    saveBtn.title = same ? 'This is the view the task browser opens on' :
      'Open the task browser on this view from now on: the labels hidden with their eye and the filters pressed';
  }
  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      var view = fullView(sel);
      saveBtn.disabled = true;
      post({ action: 'save_view', view: view }).then(function () {
        DATA.saved_view = view;
        tell();
        paintTools();
      }).catch(function (err) { paintTools(); fail(err.message); });
    });
  }
  var manageBtn = $('#manageBtn');
  if (manageBtn) { manageBtn.addEventListener('click', function () { openManager(manageBtn); }); }
  /* [?]: the keyboard's line, hidden until it is asked for. */
  function toggleKeys() {
    if (!keysLine) { return; }
    keysLine.hidden = !keysLine.hidden;
    keysBtn.setAttribute('aria-expanded', String(!keysLine.hidden));
  }
  if (keysBtn) { keysBtn.addEventListener('click', toggleKeys); }

  /* ------------------------------------------------------ everything else */
  q.addEventListener('input', function () {
    query = q.value.trim().toLowerCase();
    cursorKey = null;
    render(false);
    tell();
  });
  /* One handler, for a key pressed here and for one Rouh hands down. A reader
     who has not clicked into the frame yet has the keyboard on Rouh's own
     page, and the arrows, Enter, Space and "/" are sent down and dispatched
     here as real presses (pages.keys_script), so there is nothing else to
     listen for: they arrive at this handler having been pressed. */
  function onKey(e) {
    if (manageEl && !manageEl.hidden) {
      if (e.key === 'Escape') { e.preventDefault(); closeManager(); }
      return;
    }
    if (!menu.hidden) {
      if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); }
      return;
    }
    var active = document.activeElement, typing = active === q;
    if (active && active.tagName === 'INPUT' && !typing) { return; }
    if (e.metaKey || e.ctrlKey || e.altKey) { return; }
    if (e.key === '/' && !typing) { e.preventDefault(); q.focus(); q.select(); return; }
    if (e.key === '?' && !typing) { e.preventDefault(); toggleKeys(); return; }
    /* Escape belongs to Rouh, which backs out one level of the canvas with
       it, and Rouh takes it whatever the page does - unless the page stops it
       (pages.keys_script). So the page stops it exactly when it has something
       of its own to undo, which is what the hint line under the search box
       promises, and lets it go when it has not, which is when a reader
       pressing Escape means "take me out of here". */
    if (e.key === 'Escape') {
      if (q.value) { e.preventDefault(); q.value = ''; query = ''; cursorKey = null; render(false); tell(); return; }
      if (sel.kind !== 'all') { e.preventDefault(); setSel({ kind: 'all' }); return; }
      if (proc) { e.preventDefault(); setProc(''); return; }
      if (whose) { e.preventDefault(); setWhose(''); return; }
      if (shelf) { e.preventDefault(); setShelf(false); return; }
      q.blur();
      return;
    }
    var free = !typing || !q.value;
    if (e.key === 'ArrowDown') { e.preventDefault(); letGo(); moveCursor(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); letGo(); moveCursor(-1); return; }
    if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && free) {
      e.preventDefault();
      letGo();
      switchColumn(e.key === 'ArrowRight' ? 1 : -1);
      return;
    }
    if (e.key === ' ' && free && cursorKey && !(active && active !== q && /^(BUTTON|A|SUMMARY)$/.test(active.tagName))) {
      e.preventDefault();
      space();
      return;
    }
    /* Enter opens what is highlighted, whatever button was clicked last; with
       nothing highlighted, a focused button keeps its usual Enter. */
    if (e.key === 'Enter') {
      var el = elOf(cursorKey) || (stops.length === 1 ? stops[0] : null);
      if (el) { e.preventDefault(); open(el); }
    }
  }
  document.addEventListener('keydown', onKey);
  window.addEventListener('resize', function () { closeMenu(false); });

  if (DATA.error) {
    noticeEl.textContent = DATA.error;
    noticeEl.hidden = false;
  }
  buildRows();
  renderBar();
  render(false);
  q.focus({ preventScroll: true });
  toRouh({ type: VIEW, ask: true });
})();
