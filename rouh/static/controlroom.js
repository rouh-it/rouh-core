/* The Control Room, at /control (`rouh/controlroom.py`).

   A map of what is on Petar's mind. Petar, 9 October 2026, turning down the
   room of pins: his work moves too fast to pin, and he wants "a map of
   what's going on in my brain, with big cards that contain lots of data,
   while very useful at a glance". Step 62-21 drew three layouts; he took two
   of them, with these decisions the same day:

   - Two ways to look at the same clusters, switched at the top: the Mosaic,
     which is where the room opens, and the Front page. The choice is
     remembered in this browser.
   - A cluster's size comes from him, never from Rouh's own work: his
     messages, what waits on his answer, how often he comes back, how soon its
     next date is, and his tone. What Rouh is running in a cluster is in the
     Runs section of the opened card and never makes it bigger.
   - A pin is a small lift, not a seat: a cluster with something pinned in it
     is a little bigger, and can still be outgrown or go quiet.
   - A cluster he has not touched for seven days leaves the map, quiet edge
     and all.
   - No calendar strip at the top. A cluster's next date is on its own card.

   The server works out every cluster, its size and every line on it
   (`controlroom.room`); the names and headlines are Opus 5.5's, written after
   the room opens and each night, never while it opens. This file only lays
   them out and draws them. It reads once per opening, like the room always
   has (Petar, 1 October 2026), and lays the map out once per read, so
   nothing moves while he looks.

   Pressing a card opens that cluster in place, with the rest of the map
   beside it; Escape, or the back button, goes back to the map.

   The layer, its address and its row in the sidebar are app.js's
   (`controlOpen`); this file is handed what it needs through
   `window.RouhControlHost` and answers through `window.RouhControl`. */
(function () {
  'use strict';

  var API = '/api/control';
  /* Others' tasks (`rouh/task_origin.py`): the tasks made for somebody else,
     by email or Telegram, left off the map until he switches them on. One
     switch for the map and the task browser, kept for him by Rouh. */
  var OTHERS = '/api/control/others';
  var PREF = 'rouh-control';
  var VIEWS = [['mosaic', 'Mosaic'], ['front', 'Front page']];

  var R = {
    open: false, data: null, at: 0, busy: false, error: '', seq: 0,
    side: 'all', view: 'mosaic', help: false, opened: ''
  };

  function host() { return window.RouhControlHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December'];
  var DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  function ago(t) {
    if (!t) return '';
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' minutes ago';
    if (s < 5400) return 'an hour ago';
    if (s < 86400) return Math.round(s / 3600) + ' hours ago';
    if (s < 172800) return 'yesterday';
    if (s < 7 * 86400) return Math.round(s / 86400) + ' days ago';
    var d = new Date(t * 1000);
    return 'on ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  function clock(t) {
    var d = new Date(t * 1000);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  /* When a date ahead is, as a person says it: "today 15:00", "tomorrow
     11:30", "Tuesday 09:00", "on 21 October". */
  function ahead(t) {
    var d = new Date(t * 1000), now = new Date();
    var day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var diff = Math.floor((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - day) / 86400000);
    if (diff <= 0) return 'today ' + clock(t);
    if (diff === 1) return 'tomorrow ' + clock(t);
    if (diff < 7) return DAYS[d.getDay()] + ' ' + clock(t);
    return 'on ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  /* When he last looked, said as a time: "11:02 today", "yesterday 18:40",
     "Monday 09:12", "3 October". */
  function before(t) {
    var d = new Date(t * 1000), now = new Date();
    var day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var diff = Math.floor((day - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);
    if (diff <= 0) return clock(t) + ' today';
    if (diff === 1) return 'yesterday ' + clock(t);
    if (diff < 7) return DAYS[d.getDay()] + ' ' + clock(t);
    return d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  function today() {
    var d = new Date();
    return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  }

  function readPrefs() {
    try {
      var p = JSON.parse(localStorage.getItem(PREF) || '{}');
      if (p.side) R.side = p.side;
      if (p.view === 'front' || p.view === 'mosaic') R.view = p.view;
    } catch (err) { /* private window */ }
  }
  function writePrefs() {
    try { localStorage.setItem(PREF, JSON.stringify({ side: R.side, view: R.view })); }
    catch (err) { /* private window */ }
  }

  /* A link to the thing itself. A plain press opens it here in Rouh; a press
     with a modifier is the browser's, which opens a tab of its own. */
  function link(href, cls, text, title) {
    var a = el('a', cls, text);
    a.href = href;
    if (title) a.title = title;
    a.addEventListener('click', function (e) {
      e.stopPropagation();
      if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (!host().go) return;
      e.preventDefault();
      host().go(href);
    });
    return a;
  }

  /* ------------------------------------------------------------ reading */

  function load() {
    var seq = ++R.seq;
    R.busy = true;
    busy();
    var done = function (data, error) {
      if (seq !== R.seq) return;
      R.busy = false;
      R.error = error || '';
      if (data) { R.data = data; R.at = data.at || Date.now() / 1000; }
      if (R.open) draw();
    };
    if (typeof fetch !== 'function') { done(null, 'This browser cannot read the map.'); return; }
    fetch(API, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.ok && j && j.ok && Array.isArray(j.clusters)) done(j, '');
        else done(null, (j && j.why) || 'Rouh could not read the map (the server said ' + r.status + ').');
      });
    }).catch(function () {
      done(null, 'Rouh could not be reached. Check the connection and try again.');
    });
  }

  function busy() {
    var body = $('crBody');
    if (body) body.setAttribute('aria-busy', R.busy ? 'true' : 'false');
  }

  /* ------------------------------------------------------------ narrowing */

  function clusters() { return (R.data && R.data.clusters) || []; }
  var SIDE_ORDER = ['Work', 'Personal', 'Rouh'];
  function sides() { return SIDE_ORDER.slice(); }
  function matches(c) {
    return R.side === 'all' || c.side === R.side.toLowerCase();
  }
  function shown() { return clusters().filter(matches); }
  function quiet(c) { return c.size === 'quiet'; }
  function byKey(k) {
    var all = clusters();
    for (var i = 0; i < all.length; i++) if (all[i].key === k) return all[i];
    return null;
  }

  /* ------------------------------------------------------------ drawing */

  function draw() {
    var body = $('crBody');
    if (!body) return;
    busy();
    meta();
    var keep = body.scrollTop;
    body.textContent = '';
    if (R.error) body.appendChild(trouble());
    var d = R.data;
    if (!d) {
      if (!R.error) body.appendChild(loading());
      return;
    }
    if (d.partial && d.partial.length) body.appendChild(partial(d.partial));
    var box = el('section', 'cr-map');
    box.setAttribute('aria-label', 'What is on your mind');
    box.appendChild(tools());
    box.appendChild(key());
    body.appendChild(box);
    var list = shown();
    if (R.opened && !byKey(R.opened)) R.opened = '';
    if (!clusters().length) box.appendChild(nothing());
    else if (!list.length) {
      box.appendChild(el('p', 'cr-note cr-none', 'Nothing from ' + R.side + ' has been on your mind '
        + 'in the last ' + (d.quiet_days || 7) + ' days.'));
    } else if (R.opened) box.appendChild(openView(byKey(R.opened), list));
    else if (R.view === 'front') box.appendChild(frontPage(list));
    else box.appendChild(mosaic(list));
    if (d.naming) box.appendChild(el('p', 'cr-note cr-naming', d.naming));
    body.scrollTop = keep;
    // Laid out once its board has a size: the mosaic is worked out from it.
    requestAnimationFrame(layout);
  }

  function meta() {
    var m = $('crMeta');
    if (!m) return;
    m.textContent = '';
    var d = R.data;
    if (!d) { m.appendChild(el('span', null, R.busy ? 'Reading the map…' : '')); return; }
    var all = clusters();
    var waiting = all.reduce(function (s, c) { return s + (c.waiting || []).length; }, 0);
    m.appendChild(el('span', null, plural(all.length, 'card')
      + (waiting ? ', ' + waiting + ' waiting on you' : '')));
    var read = el('span', 'cr-read', 'Read at ' + clock(R.at));
    read.title = new Date(R.at * 1000).toLocaleString();
    m.appendChild(read);
  }

  function loading() {
    var box = el('div', 'cr-loading');
    box.setAttribute('role', 'status');
    box.appendChild(el('p', 'cr-loading-say', 'Reading what is on your mind…'));
    var skel = el('div', 'cr-skel');
    for (var i = 0; i < 3; i++) skel.appendChild(el('span', 'cr-skel-bar'));
    box.appendChild(skel);
    return box;
  }

  function trouble() {
    var p = el('p', 'cr-say bad');
    p.setAttribute('role', 'alert');
    p.appendChild(document.createTextNode(R.error + (R.data
      ? ' What is below was read at ' + clock(R.at) + '.' : '') + ' '));
    var again = el('button', 'cr-link-btn', 'Try again');
    again.type = 'button';
    again.addEventListener('click', load);
    p.appendChild(again);
    return p;
  }

  function partial(list) {
    var box = el('details', 'cr-say warn');
    box.appendChild(el('summary', null, 'Part of this could not be read, so some of it may be missing.'));
    var ul = el('ul');
    list.forEach(function (w) { ul.appendChild(el('li', null, w)); });
    box.appendChild(ul);
    return box;
  }

  function nothing() {
    var box = el('section', 'cr-card cr-nothing');
    box.appendChild(el('h4', null, 'Nothing on the map yet'));
    box.appendChild(el('p', 'cr-note', 'Clusters form from what you talk to Rouh about, what waits on '
      + 'your answer and what you open. Nothing has in the last ' + ((R.data && R.data.quiet_days) || 7)
      + ' days.'));
    return box;
  }

  /* How the map is made, under the help button. */
  function key() {
    var box = el('div', 'cr-key');
    box.id = 'crHelp';
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', 'How the map is made');
    box.hidden = !R.help;
    var d = R.data || {};
    box.appendChild(el('p', 'cr-key-title', 'How the map is made'));
    var dl = el('dl', 'cr-key-list');
    var rows = [['A subject', 'A client such as Acme Bank, a person such as Sam, an '
      + 'organisation. Its rows are the tasks, Clockwork jobs, chats and meetings that are about it.'],
    ['One piece of work', 'One task, one Clockwork job or one meeting series, holding only what belongs to it '
      + 'directly: its own chats, files and runs, and what is linked to it. It is called what that task or job '
      + 'is called, a task with its number.'],
    ['Cards', 'Rouh decides each card\u2019s subject first and checks everything against it, never against its '
      + 'neighbours: a person or topic two things share never puts them together, and Work, Personal, Rouh and '
      + 'your health stay apart. Each row in an opened card says why it is there. '
      + (d.model_name || 'Opus 5.5') + ' names the subjects and writes each card\u2019s Where it stands, after '
      + 'the room opens and each night, never while you wait.'],
    ['Task changes', 'The tasks and steps on a card that were done, stopped or set waiting on you since you '
      + 'last opened the Control Room.'],
    ['Size', 'From you alone: your messages in it, what waits on your answer, how often you came back this '
      + 'week, how soon its next date is, and your tone. What Rouh is running never makes a card bigger.'],
    ['Pins', 'Something pinned in a cluster lifts it a little (' + Math.round((d.pin_boost || 0) * 100)
      + ' points of 100). It does not keep it on the map.'],
    ['Quiet', 'The smallest sit in the quiet edge under the map. A cluster you have not touched for '
      + (d.quiet_days || 7) + ' days leaves the map' + (d.gone ? ' (' + plural(d.gone, 'has', 'have') + ' left now)' : '') + '.']];
    rows.forEach(function (x) {
      dl.appendChild(el('dt', 'cr-key-k', x[0]));
      dl.appendChild(el('dd', null, x[1]));
    });
    box.appendChild(dl);
    box.appendChild(el('p', 'cr-note cr-key-foot', 'Press a card to open it, with the rest of the map beside '
      + 'it. Escape goes back. The map is laid out once each time the room opens, so nothing moves while you look.'));
    return box;
  }

  var HELP_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" '
    + 'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
    + '<path d="M9.6 9.3a2.5 2.5 0 0 1 4.8 1c0 1.7-2.4 2.2-2.4 3.7"/><path d="M12 17.2h.01"/></svg>';

  function tools() {
    var bar = el('div', 'cr-tools');
    bar.appendChild(seg('View', 'cr-view-seg', VIEWS, R.view, function (v) { R.view = v; R.opened = ''; }));
    bar.appendChild(seg('Show', 'cr-side-seg', [['all', 'All']].concat(sides().map(function (s) { return [s, s]; })),
      R.side, function (v) { R.side = v; }));
    var d = R.data || {};
    if (d.others || d.show_others) bar.appendChild(othersSwitch(!!d.show_others, d.others || 0));
    var help = el('button', 'cr-help');
    help.type = 'button';
    help.id = 'crHelpBtn';
    help.innerHTML = HELP_SVG;
    help.title = 'How the map is made';
    help.setAttribute('aria-label', 'How the map is made');
    help.setAttribute('aria-controls', 'crHelp');
    help.setAttribute('aria-expanded', R.help ? 'true' : 'false');
    help.addEventListener('click', function () { showHelp(!R.help); });
    bar.appendChild(help);
    return bar;
  }

  /* The switch beside Show: pressed, the map is read again with the tasks made
     for other people on it, each marked with who it was for, or without. */
  function othersSwitch(on, n) {
    var b = el('button', 'cr-seg-btn cr-others');
    b.type = 'button';
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.appendChild(document.createTextNode('Others\u2019 tasks'));
    b.appendChild(el('span', 'cr-others-n', ' ' + n));
    b.title = on ? 'Showing the tasks made for other people. Press to hide them'
      : plural(n, 'task') + ' made for other people, by email or Telegram, ' + (n === 1 ? 'is' : 'are') +
        ' left off the map. Press to show them';
    b.addEventListener('click', function () {
      b.disabled = true;
      fetch(OTHERS, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: !on })
      }).then(function (r) {
        if (r.status === 401) { location.href = '/login'; return; }
        if (!r.ok) throw new Error(String(r.status));
        R.opened = '';
        load();
      }).catch(function () {
        b.disabled = false;
        R.error = 'Rouh could not change that just now. Try again in a moment.';
        draw();
      });
    });
    return b;
  }
  /* Who a task or a card was made for, while others' tasks are on the map. */
  function forMark(f) {
    var x = el('span', 'cr-for', 'For ' + f['for']);
    x.title = f.words || ('Made for ' + f['for']);
    return x;
  }

  function showHelp(on) {
    R.help = on;
    var box = $('crHelp'), btn = $('crHelpBtn');
    if (box) box.hidden = !on;
    if (btn) btn.setAttribute('aria-expanded', on ? 'true' : 'false');
  }

  function seg(label, cls, options, now, set) {
    var g = el('div', 'cr-seg ' + cls);
    g.setAttribute('role', 'group');
    g.setAttribute('aria-label', label);
    g.appendChild(el('span', 'cr-seg-label', label));
    options.forEach(function (o) {
      var b = el('button', 'cr-seg-btn', o[1]);
      b.type = 'button';
      b.setAttribute('aria-pressed', o[0] === now ? 'true' : 'false');
      b.addEventListener('click', function () { set(o[0]); writePrefs(); draw(); });
      g.appendChild(b);
    });
    return g;
  }

  /* ---- the pieces of a card ---- */

  var SIZE_WORDS = { large: 'large', medium: 'medium', small: 'small', quiet: 'quiet' };
  /* The signals, in the colours of the meter under a card. */
  var SIG = [['activity', 'Your messages'], ['waiting', 'Waiting on you'], ['returns', 'Your returns'],
    ['date', 'Next date'], ['tone', 'Tone'], ['pin', 'Pinned']];

  /* Petar, 13 October 2026 (fr_691311644626): a card says nothing he has to
     decode. No Work or Topic tag, which read as the Work column; no "busier
     this week", which the card's place on the map already says; no count of
     what waits on him over the list of it; no key numbers, which change every
     time; and no "Rouh: 1 running", since an opened card has a Runs section.
     A topic card says what its subject is, in words, once opened. */
  var SUBJECT_WORDS = { project: 'A client', person: 'A person', org: 'An organisation' };

  /* Where a card stands, in one line Opus 5.5 wrote, said to be that. */
  function stands(c, cls) {
    if (!c.headline) return null;
    var x = el('div', cls);
    x.appendChild(el('span', 'cr-ld-lab', 'Where it stands '));
    x.appendChild(document.createTextNode(c.headline));
    x.title = 'Where it stands, in one line written by ' + ((R.data && R.data.model_name) || 'Opus 5.5')
      + ' from what is on this card.';
    return x;
  }
  function why(c) {
    var e = c.evidence || {}, bits = [];
    if (e.messages_14d) bits.push(plural(e.messages_14d, 'message') + ' from you in 14 days');
    if (e.opened_7d) bits.push(plural(e.opened_7d, 'page') + ' opened this week');
    if ((c.waiting || []).length) bits.push(c.waiting.length + ' waiting on you');
    if (c.pinned) bits.push(c.pinned === 1 ? 'pinned' : c.pinned + ' pinned');
    return bits.join(' · ') || 'Little from you in the last two weeks';
  }
  function meter(c) {
    var m = el('div', 'cr-meter');
    m.setAttribute('aria-hidden', 'true');
    var w = (R.data && R.data.weights) || {};
    var used = 0;
    SIG.forEach(function (s) {
      var v = s[0] === 'pin' ? (c.boost || 0) : ((c.parts || {})[s[0]] || 0) * (w[s[0]] || 0);
      if (v > 0.004) {
        var i = el('i', 'm-' + s[0]);
        i.style.flex = v.toFixed(3);
        i.title = s[1];
        m.appendChild(i);
        used += v;
      }
    });
    var rest = el('i', 'm-rest');
    rest.style.flex = Math.max(0, 1 - used).toFixed(3);
    m.appendChild(rest);
    return m;
  }
  /* `listed`: the card lists what waits on him, so it is not counted too. */
  function chips(c, most, listed) {
    var box = el('div', 'cr-chips');
    var out = [];
    if ((c.waiting || []).length && !listed) out.push(el('span', 'cr-chip wait', c.waiting.length + ' waiting on you'));
    if ((c.dates || []).length) out.push(el('span', 'cr-chip date', ahead(c.dates[0].at) + ' · ' + c.dates[0].what));
    if (c.pinned) out.push(el('span', 'cr-chip pin', c.pinned === 1 ? 'Pinned' : c.pinned + ' pinned'));
    out.slice(0, most || 4).forEach(function (x) { box.appendChild(x); });
    return box;
  }
  /* What the changes on a card are counted from, said: never "since you last
     looked", which did not say since when, or looked at what. */
  function changesTitle() {
    var t = R.data && R.data.looked;
    return t ? 'Task changes since ' + before(t) : 'Task changes';
  }
  function blk(title, items, most) {
    if (!items || !items.length) return null;
    var b = el('div', 'cr-blk');
    b.appendChild(el('div', 'cr-bt', title));
    var ul = el('ul');
    items.slice(0, most || items.length).forEach(function (x) { ul.appendChild(x); });
    b.appendChild(ul);
    return b;
  }
  function waitItems(c) {
    return (c.waiting || []).map(function (w) {
      var x = el('li', 'w');
      if (w.href) x.appendChild(link(w.href, 'cr-in', w.text, 'Open it'));
      else x.appendChild(document.createTextNode(w.text));
      if (w.when) x.appendChild(el('span', 'cr-u', ' ' + w.when));
      return x;
    });
  }
  function sinceItems(c) {
    return (c.since || []).map(function (s) {
      var x = el('li');
      if (s.href) x.appendChild(link(s.href, 'cr-in', s.text, 'Open it'));
      else x.appendChild(document.createTextNode(s.text));
      if (s.at) x.appendChild(el('span', 'cr-m', ' ' + ago(s.at)));
      return x;
    });
  }
  function dateItems(c) {
    return (c.dates || []).map(function (d) {
      var x = el('li');
      x.appendChild(el('strong', null, ahead(d.at)));
      x.appendChild(document.createTextNode(' ' + d.what));
      whyLine(x, d.why, false);
      return x;
    });
  }
  /* Why a task, chat or meeting is in its cluster: the one direct tie that
     holds it there, so a wrong one can be seen. */
  function whyLine(x, why, full) {
    if (!why) return;
    if (full) x.appendChild(el('span', 'cr-wy', why));
    else x.title = 'Here because: ' + why;
  }
  function taskItems(c, full) {
    return (c.tasks || []).map(function (t) {
      var x = el('li', 'cr-tk' + (t.pinned ? ' pinned' : ''));
      x.appendChild(link(t.href, 'cr-in', (t.n != null ? t.n + ' ' : '') + t.title, 'Open ' + t.title));
      if (t.made_for) x.appendChild(forMark(t.made_for));
      if (t.state) x.appendChild(el('span', 'cr-m', ' ' + t.state));
      whyLine(x, t.why, full);
      return x;
    });
  }
  function jobItems(c, full) {
    return (c.jobs || []).map(function (j) {
      var x = el('li', 'cr-tk');
      x.appendChild(link(j.href, 'cr-in', j.title, 'Open Clockwork'));
      if (j.state) x.appendChild(el('span', 'cr-m', ' ' + j.state));
      whyLine(x, j.why, full);
      return x;
    });
  }
  function meetingItems(c) {
    var now = Date.now() / 1000;
    return (c.meetings || []).map(function (m) {
      var x = el('li');
      x.appendChild(el('strong', null, m.at >= now - 7200 ? ahead(m.at) : ago(m.at)));
      x.appendChild(document.createTextNode(' ' + m.what));
      whyLine(x, m.why, true);
      return x;
    });
  }
  /* A chat's line, and its sub-chats set in under it: a chat that hangs off
     another listed here is drawn inside that one, and one whose chat is not
     listed names it. */
  function chatItems(c) {
    var list = c.chats || [], here = {}, kids = {};
    list.forEach(function (x) { here[x.id] = true; });
    list.forEach(function (x) {
      if (x.parent && here[x.parent]) (kids[x.parent] = kids[x.parent] || []).push(x);
    });
    function one(x, sub) {
      var i = el('li', sub ? 'cr-sub' : null);
      i.appendChild(link(x.href, 'cr-in', x.title, 'Open the chat'));
      var m = [];
      if (x.parent) m.push('sub-chat');
      if (x.at) m.push(ago(x.at));
      if (m.length) i.appendChild(el('span', 'cr-m', ' ' + m.join(' · ')));
      if (x.parent && !here[x.parent]) i.appendChild(el('span', 'cr-wy', 'a sub-chat of “' + (x.parent_title || 'another chat') + '”'));
      whyLine(i, x.why, true);
      if (kids[x.id]) {
        var ul = el('ul', 'cr-subs');
        ul.setAttribute('aria-label', 'Sub-chats of ' + x.title);
        kids[x.id].forEach(function (k) { ul.appendChild(one(k, true)); });
        i.appendChild(ul);
      }
      return i;
    }
    return list.filter(function (x) { return !(x.parent && here[x.parent]); })
      .map(function (x) { return one(x, false); });
  }
  /* Rouh's runs here: each called what it is called, how it stands and when,
     and what it was started for. */
  function runItems(c) {
    return (c.runs || []).map(function (r) {
      var x = el('li', r.running ? 'cr-run on' : 'cr-run');
      x.appendChild(link(r.href, 'cr-in', r.title, 'Open the run'));
      x.appendChild(el('span', 'cr-m', ' ' + (r.running ? 'running now' : r.state + (r.at ? ' ' + ago(r.at) : ''))));
      whyLine(x, r.why, true);
      return x;
    });
  }
  /* The pages he opened here, the latest first, with the task or step each is in. */
  function pageItems(c) {
    return (c.pages || []).map(function (p) {
      var x = el('li');
      x.appendChild(link(p.href, 'cr-in', p.title, 'Open the page'));
      if (p.at) x.appendChild(el('span', 'cr-m', ' opened ' + ago(p.at)));
      whyLine(x, p.why, true);
      return x;
    });
  }
  function people(c) {
    if (!(c.people || []).length) return null;
    var b = el('div', 'cr-blk');
    b.appendChild(el('div', 'cr-bt', 'People'));
    b.appendChild(el('div', 'cr-ppl', c.people.slice(0, 6).join(' · ')));
    return b;
  }
  function add(box, x) { if (x) box.appendChild(x); }

  /* What a card holds depends on the room it has: the bigger it is, the more
     it says, in this order - what waits on him, the task changes since he
     last opened the room, the next date, its tasks, its people. Its name
     comes first, whole, and is the last thing given up. */
  function tierOf(w, h) {
    var a = w * h;
    return a > 150000 ? 'xl' : a > 80000 ? 'l' : a > 42000 ? 'm' : a > 17000 ? 's' : 'xs';
  }
  function cardEl(c, w, h, force) {
    var t = force || tierOf(w, h);
    var card = el('div', 'cr-cc t-' + t + (c.provisional ? ' provisional' : ''));
    card.setAttribute('data-side', c.side || 'work');
    card.setAttribute('data-kind', c.kind || 'work');
    card.setAttribute('data-key', c.key);
    card.setAttribute('data-size', c.size);
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', c.name + ', ' + SIZE_WORDS[c.size] + '. Open it.');
    var hd = el('div', 'cr-hd');
    hd.appendChild(el('span', 'cr-nm', c.name));
    if (c.made_for) hd.appendChild(forMark(c.made_for));
    card.appendChild(hd);
    if (t !== 'xs') add(card, stands(c, 'cr-ld'));
    card.appendChild(chips(c, t === 'xs' ? 1 : 4, t !== 'xs' && (c.waiting || []).length > 0));
    var cols = el('div', 'cr-cols');
    var n = t === 'xl' ? 4 : t === 'l' ? 3 : 2;
    if (t === 'xl' || t === 'l') {
      add(cols, blk('Waiting on you', waitItems(c), n));
      add(cols, blk(changesTitle(), sinceItems(c), n - 1));
      add(cols, blk('Next', dateItems(c), 2));
      add(cols, blk('Tasks', taskItems(c), n));
      add(cols, blk('Clockwork', jobItems(c), 2));
      add(cols, people(c));
    } else if (t === 'm') {
      add(cols, blk('Waiting on you', waitItems(c), 2));
      add(cols, (c.since || []).length ? blk(changesTitle(), sinceItems(c), 1) : blk('Tasks', taskItems(c), 2));
    } else if (t === 's') {
      add(cols, (c.waiting || []).length ? blk('Waiting on you', waitItems(c), 1) : blk('Tasks', taskItems(c), 1));
    }
    if (cols.childNodes.length) card.appendChild(cols);
    if (t !== 'xs') {
      var y = el('div', 'cr-why', 'Why this size: ' + why(c));
      y.title = why(c);
      card.appendChild(y);
      card.appendChild(meter(c));
    }
    function go() { R.opened = c.key; draw(); var b = $('crBody'); if (b) b.scrollTop = 0; }
    card.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a')) return;
      go();
    });
    card.addEventListener('keydown', function (e) {
      if (e.target !== card) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
    return card;
  }

  /* Whatever does not fit in a card is left out whole, never cut in half:
     the last item of a block first, then whole blocks. */
  function fitCols(card) {
    var cols = card.querySelector('.cr-cols');
    if (!cols) return;
    for (var round = 0; round < 40; round++) {
      var bottom = cols.getBoundingClientRect().bottom, bad = null;
      [].forEach.call(cols.querySelectorAll('.cr-blk:not(.gone)'), function (b) {
        if (b.getBoundingClientRect().top > bottom - 30) { bad = b; return; }
        [].forEach.call(b.querySelectorAll('li:not(.gone)'), function (x) {
          if (x.getBoundingClientRect().bottom > bottom + 1) bad = x;
        });
      });
      if (!bad) break;
      bad.classList.add('gone');
      [].forEach.call(cols.querySelectorAll('.cr-blk:not(.gone)'), function (b) {
        if (!b.querySelector('li:not(.gone), .cr-ppl')) b.classList.add('gone');
      });
    }
  }
  /* Then the card as a whole: extra chips first, then Where it stands
     shorter, and the name only at the very last. */
  function fitCard(card) {
    if (!card.style.height) return;
    function over() {
      var last = card.lastElementChild;
      return card.scrollHeight > card.clientHeight + 1
        || (last && last.getBoundingClientRect().bottom > card.getBoundingClientRect().bottom - 6);
    }
    var ld = card.querySelector('.cr-ld'), y = card.querySelector('.cr-why'), m = card.querySelector('.cr-meter');
    var cs = [].slice.call(card.querySelectorAll('.cr-chips .cr-chip'));
    var steps = [
      function () { if (ld) ld.style.webkitLineClamp = '3'; },
      function () { if (cs.length > 2) cs[cs.length - 1].classList.add('gone'); },
      function () { if (ld) ld.style.webkitLineClamp = '2'; },
      function () { if (cs.length > 1) cs[1].classList.add('gone'); },
      function () { if (y) y.classList.add('gone'); },
      function () { if (ld) ld.style.webkitLineClamp = '1'; },
      function () { if (m) m.classList.add('gone'); },
      function () { var nm = card.querySelector('.cr-nm'); if (nm) nm.classList.add('two'); },
      function () { if (ld) ld.classList.add('gone'); },
      function () { if (cs.length) cs[0].classList.add('gone'); },
      function () { var nm = card.querySelector('.cr-nm'); if (nm) nm.classList.add('one'); }
    ];
    for (var i = 0; i < steps.length && over(); i++) steps[i]();
  }
  function fitAll(board) {
    [].forEach.call(board.querySelectorAll('.cr-cc'), function (c) { fitCols(c); fitCard(c); });
  }

  /* The quiet edge: one small pill each, under the map. */
  function edge(list) {
    if (!list.length) return null;
    var box = el('div', 'cr-edge');
    box.setAttribute('aria-label', 'Quiet');
    box.appendChild(el('span', 'cr-edge-lab', 'Quiet'));
    list.forEach(function (c) {
      var q = el('button', 'cr-q');
      q.type = 'button';
      q.setAttribute('data-side', c.side || 'work');
      q.setAttribute('data-key', c.key);
      q.appendChild(el('span', 'cr-q-nm', c.name));
      if (c.made_for) q.appendChild(forMark(c.made_for));
      var e = c.evidence || {};
      var note = (c.dates || []).length ? ahead(c.dates[0].at) : e.last_you ? 'you, ' + ago(e.last_you) : '';
      if (note) q.appendChild(el('small', null, note));
      q.title = c.headline || c.name;
      q.addEventListener('click', function () { R.opened = c.key; draw(); });
      box.appendChild(q);
    });
    return box;
  }

  function narrowRoom() {
    var b = $('crBody');
    return !b || b.clientWidth <= 640;
  }

  /* ---- the mosaic ---- */

  function mosaic(list) {
    var wrap = el('div', 'cr-mosaic');
    var board = el('div', 'cr-board');
    board.id = 'crBoard';
    board.setAttribute('data-view', 'mosaic');
    wrap.appendChild(board);
    add(wrap, edge(list.filter(quiet)));
    return wrap;
  }

  /* The screen divided between the clusters by score, squarified so each card
     is close to square and the big ones are clearly bigger (score^2.6, as in
     62-21). On a narrow room they stack, each as tall as its score allows. */
  function layMosaic(board, list) {
    var big = list.filter(function (c) { return !quiet(c); });
    if (!big.length) big = list.slice(0, 1);
    board.textContent = '';
    if (narrowRoom()) {
      board.classList.add('stack');
      big.forEach(function (c) {
        var h = Math.round(130 + 330 * Math.min(1, c.score));
        var card = cardEl(c, board.clientWidth || 340, h);
        board.appendChild(card);
      });
      return;
    }
    board.classList.remove('stack');
    // As tall as the cards need: one card is not stretched over the whole
    // screen, and many share at least the screen below the switch.
    var n = big.length;
    board.style.height = n <= 1 ? '320px' : n <= 3 ? '460px' : '';
    var W = board.clientWidth, H = board.clientHeight, gap = 8;
    squarify(big.map(function (c) { return { c: c, v: Math.pow(Math.max(c.score, 0.02), 2.6) }; }), 0, 0, W, H)
      .forEach(function (r) {
        var w = r.w - gap, h = r.h - gap;
        var card = cardEl(r.i.c, w, h);
        card.style.left = (r.x + gap / 2) + 'px';
        card.style.top = (r.y + gap / 2) + 'px';
        card.style.width = w + 'px';
        card.style.height = h + 'px';
        board.appendChild(card);
      });
    fitAll(board);
  }

  function squarify(items, x, y, w, h) {
    var out = [], rest = items.slice();
    var total = items.reduce(function (s, i) { return s + i.v; }, 0) || 1, scale = (w * h) / total;
    var row = [];
    function worst(r, len) {
      var s = 0, mx = 0, mn = 1e18;
      r.forEach(function (i) { var a = i.v * scale; s += a; mx = Math.max(mx, a); mn = Math.min(mn, a); });
      var l2 = len * len, s2 = s * s;
      return Math.max(l2 * mx / s2, s2 / (l2 * mn));
    }
    function layrow(r) {
      var s = r.reduce(function (a, i) { return a + i.v * scale; }, 0);
      if (w >= h) {
        var cw = s / h, cy = y;
        r.forEach(function (i) { var ch = i.v * scale / cw; out.push({ i: i, x: x, y: cy, w: cw, h: ch }); cy += ch; });
        x += cw; w -= cw;
      } else {
        var rh = s / w, cx = x;
        r.forEach(function (i) { var cw2 = i.v * scale / rh; out.push({ i: i, x: cx, y: y, w: cw2, h: rh }); cx += cw2; });
        y += rh; h -= rh;
      }
    }
    while (rest.length) {
      var len = Math.min(w, h), next = rest[0];
      if (!row.length || worst(row.concat([next]), len) <= worst(row, len)) { row.push(next); rest.shift(); }
      else { layrow(row); row = []; }
    }
    if (row.length) layrow(row);
    return out;
  }

  /* ---- the front page ---- */

  /* The same clusters as a newspaper: the biggest is the lead story, the next
     four the secondary stories, the rest briefs, and the quiet ones a line
     each at the bottom. Petar, 9 October 2026: no calendar strip across the
     top; each story carries its own next date. Petar, 13 October 2026: a
     story's headline is its name, whole, with a task's number; Opus 5.5's line
     is under it as Where it stands. */
  function frontPage(list) {
    var page = el('div', 'cr-front');
    var stories = list.filter(function (c) { return !quiet(c); });
    if (!stories.length) stories = list.slice(0, 1);
    var mast = el('div', 'cr-mast');
    mast.appendChild(el('b', null, 'The Control Room'));
    var waiting = stories.reduce(function (s, c) { return s + (c.waiting || []).length; }, 0);
    mast.appendChild(el('span', null, today() + ' · ' + plural(stories.length, 'card')
      + (waiting ? ', ' + waiting + ' waiting on you' : '')));
    page.appendChild(mast);
    var grid = el('div', 'cr-fp');
    stories.slice(0, 5).forEach(function (c, i) { grid.appendChild(story(c, i === 0 ? 'lead' : 'sec')); });
    page.appendChild(grid);
    if (stories.length > 5) {
      var briefs = el('div', 'cr-briefs');
      stories.slice(5).forEach(function (c) { briefs.appendChild(story(c, 'brief')); });
      page.appendChild(briefs);
    }
    add(page, edge(list.filter(quiet)));
    return page;
  }

  function story(c, kind) {
    var card = cardEl(c, kind === 'lead' ? 900 : 400, kind === 'lead' ? 430 : kind === 'sec' ? 210 : 150,
      kind === 'lead' ? 'xl' : kind === 'sec' ? 'm' : 's');
    card.classList.add('cr-story-' + kind);
    return card;
  }

  /* ---- one cluster, opened ---- */

  /* Everything the cluster has, with the rest of the map beside it, each as
     tall as its score allows. Escape or Back goes back to the map. */
  function openView(c, list) {
    var box = el('div', 'cr-open');
    var main = el('article', 'cr-big');
    main.setAttribute('data-side', c.side || 'work');
    main.setAttribute('data-kind', c.kind || 'work');
    main.setAttribute('data-key', c.key);
    var top = el('div', 'cr-big-top');
    var back = el('button', 'cr-back', '‹ The map');
    back.type = 'button';
    back.id = 'crBack';
    back.title = 'Back to the map (Esc)';
    back.addEventListener('click', closeOpened);
    top.appendChild(back);
    top.appendChild(el('span', 'cr-size', SIZE_WORDS[c.size]));
    main.appendChild(top);
    var hd = el('div', 'cr-hd');
    hd.appendChild(el('h4', 'cr-nm cr-big-nm', c.name));
    if (c.made_for) hd.appendChild(forMark(c.made_for));
    main.appendChild(hd);
    if (c.kind === 'topic' && SUBJECT_WORDS[c.type]) main.appendChild(el('p', 'cr-kind-line', SUBJECT_WORDS[c.type]));
    add(main, stands(c, 'cr-ld cr-big-ld'));
    if (c.provisional && c.kind === 'topic') {
      main.appendChild(el('p', 'cr-note', 'Not named yet: Rouh calls this subject by its own name until '
        + 'the next naming pass names it.'));
    }
    main.appendChild(chips(c, 4, true));
    var grid = el('div', 'cr-dgrid');
    var a = el('div'), b = el('div');
    // Petar, 13 October 2026: opened, what waits on him is called Decisions,
    // and the task changes are a column of their own on the right.
    add(a, blk('Decisions', waitItems(c)));
    add(a, blk('Meetings', meetingItems(c)));
    add(b, blk('Tasks', taskItems(c, true)));
    add(b, blk('Clockwork', jobItems(c, true)));
    add(b, people(c));
    [a, b].forEach(function (col) { if (col.childNodes.length) grid.appendChild(col); });
    // Chats, Runs and Pages, a section each and drawn alike (fr_691311644626).
    var lists = el('div', 'cr-dgrid cr-dlists');
    add(lists, blk('Chats', chatItems(c)));
    add(lists, blk('Runs', runItems(c)));
    add(lists, blk('Pages', pageItems(c)));
    var split = el('div', 'cr-dsplit');
    var left = el('div', 'cr-dleft');
    if (grid.childNodes.length) left.appendChild(grid);
    if (lists.childNodes.length) left.appendChild(lists);
    split.appendChild(left);
    var since = blk(changesTitle(), sinceItems(c));
    if (since) {
      since.title = 'Since you last opened the Control Room';
      var right = el('aside', 'cr-dsince');
      right.setAttribute('aria-label', 'Task changes');
      right.appendChild(since);
      split.appendChild(right);
      split.classList.add('two');
    }
    main.appendChild(split);
    var y = el('div', 'cr-why', 'Why this size: ' + why(c));
    main.appendChild(y);
    main.appendChild(meter(c));
    box.appendChild(main);
    var rest = el('div', 'cr-side');
    rest.setAttribute('aria-label', 'The rest of the map');
    list.filter(function (x) { return x.key !== c.key; }).forEach(function (x) {
      var card = cardEl(x, 230, 70, 'xs');
      card.style.minHeight = Math.round(40 + 90 * Math.min(1, x.score)) + 'px';
      rest.appendChild(card);
    });
    box.appendChild(rest);
    return box;
  }

  function closeOpened() {
    var was = R.opened;
    R.opened = '';
    draw();
    requestAnimationFrame(function () {
      var card = document.querySelector('#crBody .cr-cc[data-key="' + was + '"], #crBody .cr-q[data-key="' + was + '"]');
      if (card) card.focus({ preventScroll: false });
    });
  }

  /* Laid out once the board is on the screen, since its size decides it. */
  function layout() {
    var board = $('crBoard');
    if (board && R.data) layMosaic(board, shown());
    var front = document.querySelector('#crBody .cr-fp');
    if (front) fitAll(front);
  }

  /* ------------------------------------------------------------ the layer */

  /* The room reads the map once, when it is opened, and lays it out once per
     read. Petar, 1 October 2026: it is never read again by itself. */
  function shownNow() {
    if (R.open) return;
    R.open = true;
    R.opened = '';
    readPrefs();
    draw();
    load();
  }

  function hiddenNow() {
    R.open = false;
  }

  (function wire() {
    var view = $('controlView');
    if (!view) return;
    var close = $('crClose');
    if (close) close.addEventListener('click', function () { if (host().close) host().close(); });
    // Escape folds the help away first, then closes an opened cluster, and
    // only then is the page's own, which closes the room.
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !R.open || view.hidden) return;
      if (R.help) {
        e.stopPropagation();
        e.preventDefault();
        showHelp(false);
        var btn = $('crHelpBtn');
        if (btn) btn.focus();
      } else if (R.opened) {
        e.stopPropagation();
        e.preventDefault();
        closeOpened();
      }
    }, true);
  })();

  window.RouhControl = {
    shown: shownNow,
    hidden: hiddenNow
  };
})();
