/* The Heartbeat page, at /anatomy/behaviour/heartbeat (`rouh/heartbeat.py`, `rouh/web/heartbeat.py`).

   Petar, 5 October 2026: "Heartbeat is the functionality you have to have in general. It has
   nothing to do with the money project/experiment." And 7 November 2026, of this page and the
   beats': "a page I don't understand well and I don't use for that reason ... redo the entire
   section related to heartbeats." So it was redesigned from his journeys (task 169, step
   169-13), one section with three views under one header:

   - Today (this address): one sentence on whether it is working and whether anything is
     stuck, the day's four numbers, the day as a picture (a lane for its own duties and one
     per quest, every beat a mark shaped by how it ended, a press on a lane opening the
     nearest beat), the last seven days by spend, what waits on him (each going where it is
     answered, as on Decisions; never answered a second way here), the quests it carries,
     and the notes it left.
   - Beats (`/anatomy/behaviour/beats`, `beatspage.js`), the table, under this header
     (`mountHeader`).
   - Settings (`/anatomy/behaviour/heartbeat/settings`): its duties, rhythm, hours, what
     wakes it, the skips and the messages.

   Drawn into `#heartbeatBody` from `/api/heartbeat`; every answer is the whole page again.
   It looks again every fifteen seconds while it shows, but never redraws a card being
   edited. Anatomy tells it when it shows, which view, and when it is left (`settingsPages`
   in app/runs.js). */
(function () {
  'use strict';

  var H = { open: false, data: null, busy: false, error: '', said: '', seq: 0, tick: 0,
            // Which view shows: 'today' or 'settings' (the beats are their own section,
            // `beatspage.js`, under the same header); the day the day picture shows, by its
            // place in `days.list`, -1 for today; the beat pressed on it; the old queue opened.
            view: 'today', day: -1, beat: 0, oldQueue: false, wholeDay: false,
            // A card being typed into, kept out of the timer's redraws.
            editing: '', carried: '',
            // The waiting approvals ticked for a mass delete, by number.
            picked: {} };

  function host() { return window.RouhHeartbeatHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, title) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) b.title = title;
    b.addEventListener('click', act);
    return b;
  }
  /* Django's CSRF token, on every write this page makes. csrf.js puts it on all of
     them as well; this page holds a form that matters too much to rest on that alone. */
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }

  function call(method, url, body) {
    var seq = ++H.seq;
    if (method === 'POST') H.busy = true;
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') H.busy = false;
          if (seq !== H.seq && method === 'GET') return j;
          if (j && j.state) H.data = j;
          heads();
          if (r.ok) {
            H.error = '';
            if (j && j.said && !H.quiet) H.said = j.said;
            H.quiet = false;
          } else {
            H.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') H.busy = false;
        H.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }

  function load() { return call('GET', '/api/heartbeat'); }
  function act(what, more) {
    H.said = '';
    H.quiet = what === 'pause' || what === 'resume';
    H.editing = '';
    var body = { act: what };
    for (var k in (more || {})) body[k] = more[k];
    return call('POST', '/api/heartbeat/act', body);
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('heartbeatBody');
    if (!body || !H.open) return;
    var d = H.data;
    if (H.editing && d) {
      // Only the line that says what happened changes while something is typed.
      var say = body.querySelector('.hb-say');
      if (say) { say.textContent = H.error || H.said; say.className = 'hb-say' + (H.error ? ' bad' : ''); }
      return;
    }
    var keep = body.scrollTop;
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (H.error ? ' bad' : ''), H.error || H.said);
    say2.setAttribute('role', 'status');
    if (!H.error && !H.said) say2.hidden = true;
    page.appendChild(say2);
    if (!d) {
      page.insertBefore(header(H.view || 'today', null), say2);
      if (!H.error) page.appendChild(el('p', 'hb-empty', 'Reading the heartbeat…'));
      return;
    }
    page.insertBefore(header(H.view === 'settings' ? 'settings' : 'today', d), say2);
    if (H.view === 'settings') {
      page.appendChild(settingsHead(d));
      page.appendChild(jumps());
      var grid = el('div', 'hb2-settings');
      var duties = dutiesCard(d);
      duties.classList.add('wide');
      grid.appendChild(duties);
      [rhythmCard(d), hoursCard(d), wakesCard(d), skipsCard(d), messagesCard(d)]
        .forEach(function (c) { grid.appendChild(c); });
      page.appendChild(grid);
    } else {
      today(page, d);
    }
    body.scrollTop = keep;
    heads();
  }

  function card(title, sub, cls, name) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    if (name) s.dataset.card = name;
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  /* A form in a card: typing into it holds the timer's redraws off that card,
     and its Save sends only its own part of the settings. */
  function form(name, label, onSave, saveWords) {
    var f = el('form', 'hb-form');
    f.setAttribute('aria-label', label);
    f.addEventListener('input', function () { H.editing = name; });
    f.addEventListener('change', function () { H.editing = name; });
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      onSave();
    });
    f.save = function (words) {
      var row = el('div', 'hb-actions');
      var b = el('button', 'ctl small primary', words || saveWords || 'Save');
      b.type = 'submit';
      row.appendChild(b);
      f.appendChild(row);
      return b;
    };
    return f;
  }

  function field(text, type, value, id, cls) {
    var label = el('label', 'hb-field' + (cls ? ' ' + cls : ''));
    label.appendChild(el('span', '', text));
    var input = el('input');
    input.type = type;
    input.id = id;
    input.value = value == null ? '' : String(value);
    label.appendChild(input);
    return { label: label, input: input };
  }

  function check(text, on, id, help) {
    var label = el('label', 'hb-check');
    var input = el('input');
    input.type = 'checkbox';
    input.id = id;
    input.checked = !!on;
    label.appendChild(input);
    var words = el('span', '', text);
    if (help) words.appendChild(el('span', 'hb-check-help', help));
    label.appendChild(words);
    return { label: label, input: input };
  }

  function row(cls) { return el('div', 'hb-row' + (cls ? ' ' + cls : '')); }

  /** A box of words grown to show all of them. */
  function fit(area) {
    area.style.height = 'auto';
    area.style.height = (area.scrollHeight + 2) + 'px';
  }

  function dutiesCard(d) {
    var s = card('Duties', 'what it looks after on every beat, each on or off', 'hb-duties', 'duties');
    var list = d.config.duties.map(function (x) { return { id: x.id, text: x.text, on: !!x.on }; });
    var f = form('duties', 'Its duties', function () {
      var out = [];
      ul.querySelectorAll('li').forEach(function (li) {
        out.push({ id: li.dataset.id || '', on: li.querySelector('input[type=checkbox]').checked,
                   text: li.querySelector('textarea').value });
      });
      act('set', { duties: out, extra: extra.value });
    });
    var ul = el('ul', 'hb-duty-list');
    function add(x) {
      var li = el('li', 'hb-duty' + (x.id === 'work' ? ' work' : ''));
      li.dataset.id = x.id || '';
      var box = el('input');
      box.type = 'checkbox';
      box.checked = x.on;
      box.setAttribute('aria-label', 'On: ' + (x.text || 'new duty'));
      li.appendChild(box);
      var text = el('textarea');
      text.rows = 2;
      text.maxLength = 600;
      text.value = x.text || '';
      text.setAttribute('aria-label', 'Duty');
      text.placeholder = 'What it should look after on every beat';
      text.addEventListener('input', function () { fit(text); });
      li.appendChild(text);
      if (x.id !== 'work') {
        li.appendChild(button('Remove', 'hb-remove', function () {
          H.editing = 'duties';
          li.remove();
        }, 'Take this duty off the list'));
      } else {
        li.appendChild(el('span', 'hb-pill', 'quests'));
      }
      ul.appendChild(li);
    }
    list.forEach(add);
    f.appendChild(ul);
    // Each as tall as its words, once it is on the page and has a width.
    requestAnimationFrame(function () { ul.querySelectorAll('textarea').forEach(fit); });
    var addRow = el('div', 'hb-actions');
    addRow.appendChild(button('Add a duty', '', function () {
      H.editing = 'duties';
      add({ id: '', text: '', on: true });
      var last = /** @type {HTMLTextAreaElement} */ (ul.querySelector('li:last-child textarea'));
      if (last) last.focus();
    }));
    f.appendChild(addRow);
    var lab = el('label', 'hb-field wide hb-extra');
    lab.appendChild(el('span', '', 'Anything else, in your words'));
    var extra = el('textarea');
    extra.id = 'hbExtra';
    extra.rows = 3;
    extra.maxLength = 4000;
    extra.value = d.config.extra || '';
    extra.placeholder = 'Such as: keep an eye on the price of flights to Lisbon in March';
    lab.appendChild(extra);
    f.appendChild(lab);
    f.save('Save the duties');
    s.appendChild(f);
    return s;
  }

  /* Reset or delete one quest, once Petar has read what goes with it. A delete asks in
     place, with the Quests page's own box, what becomes of its task (`questspage.js`). */
  function clearWork(w, what, place) {
    function told() {
      // The sidebar's count goes with it (`questspage.js`).
      if (window.RouhQuests && window.RouhQuests.reload) window.RouhQuests.reload();
    }
    if (what === 'delete' && place && window.RouhQuests && window.RouhQuests.askDelete) {
      H.editing = 'delete';
      window.RouhQuests.askDelete(w, place, function (j) {
        H.editing = '';
        H.said = (j && (j.said || j.error)) || '';
        load();
        told();
      }, function () { H.editing = ''; place.textContent = ''; });
      return;
    }
    if (!window.confirm(clearWords('quest ' + w.number + ' \u201c' + w.title + '\u201d', w.tally, what))) return;
    H.said = '';
    call('POST', '/api/heartbeat/work', { id: w.id, act: what }).then(told);
  }

  /* Working hours, outside them, and quiet hours, each with its own words under its own
     heading, read by a screen reader with its fields. Petar, 6 October 2026: one line
     about all three was opaque; each sentence belongs to its own section. The words
     are what `Heartbeat._tick` does: the timer only inside working hours, events at
     any hour, and in quiet hours nothing by itself, the events kept for after them. */
  function hoursCard(d) {
    var h = d.config.hours;
    var s = card('Hours', 'on your clock', 'hb-hours', 'hours');
    var f = form('hours', 'Working and quiet hours', function () {
      act('set', { hours: { work_from: wf.input.value, work_to: wt.input.value, quiet_on: qon.input.checked,
                            quiet_from: qf.input.value, quiet_to: qt.input.value } });
    });
    var work = group(f, 'hbWorkHours', 'Working hours', d.config.wakes.timer ?
      'During these hours, the heartbeat runs by itself at regular intervals, every ' +
        d.state.interval_minutes + ' minutes, and also whenever an event wakes it.' :
      'The timer is turned off under What wakes it, so even in these hours the heartbeat ' +
        'runs only when an event wakes it.');
    var r = row();
    var wf = field('From', 'time', h.work_from, 'hbWorkFrom');
    var wt = field('to', 'time', h.work_to, 'hbWorkTo');
    r.appendChild(wf.label); r.appendChild(wt.label);
    work.appendChild(r);
    described(work, [wf, wt]);
    group(f, 'hbOffHours', 'Outside working hours', 'Outside working hours, the heartbeat runs ' +
      'only when an event wakes it, such as a job finishing or new mail in Rouh\u2019s own inbox.');
    var quiet = group(f, 'hbQuietHours', 'Quiet hours', 'During quiet hours, the heartbeat does not ' +
      'run, even inside working hours. Events that arrive then, such as a job finishing, wait ' +
      'until quiet hours end, and the next beat handles them together. Jobs and runs already going ' +
      'carry on; only the heartbeat waits. Beat now still runs a beat.');
    var qon = check('Keep quiet hours', h.quiet_on, 'hbQuietOn');
    quiet.appendChild(qon.label);
    var r2 = row();
    var qf = field('From', 'time', h.quiet_from, 'hbQuietFrom');
    var qt = field('to', 'time', h.quiet_to, 'hbQuietTo');
    r2.appendChild(qf.label); r2.appendChild(qt.label);
    quiet.appendChild(r2);
    described(quiet, [qon, qf, qt]);
    var pic = dayBar(function () {
      return { work_from: wf.input.value, work_to: wt.input.value, quiet_on: qon.input.checked,
               quiet_from: qf.input.value, quiet_to: qt.input.value };
    });
    f.insertBefore(pic, f.firstChild);
    f.addEventListener('input', function () { pic.paint(); });
    f.addEventListener('change', function () { pic.paint(); });
    f.save();
    s.appendChild(f);
    return s;
  }

  /* A titled part of a form with its own help: the heading names the group and the help
     describes it. Fields put in it are given to `described` to be read with that help. */
  function group(f, id, title, help) {
    var g = el('div', 'hb-group');
    g.setAttribute('role', 'group');
    var h = el('h5', 'hb-h5', title);
    h.id = id + 'Title';
    var p = el('p', 'settings-help', help);
    p.id = id + 'Help';
    g.setAttribute('aria-labelledby', h.id);
    g.setAttribute('aria-describedby', p.id);
    g.appendChild(h);
    g.appendChild(p);
    f.appendChild(g);
    return g;
  }

  function described(g, fields) {
    var help = g.getAttribute('aria-describedby');
    fields.forEach(function (x) { x.input.setAttribute('aria-describedby', help); });
  }

  function wakesCard(d) {
    var w = d.config.wakes, fl = d.config.flood;
    var s = card('What wakes it', '', 'hb-wakes', 'wakes');
    var f = form('wakes', 'What wakes it', function () {
      act('set', { wakes: { timer: t.input.checked, runs: r.input.checked, mail: m.input.checked },
                   flood: { gap_seconds: gap.input.value, most: most.input.value, window_minutes: win.input.value } });
    });
    var t = check('The timer', w.timer, 'hbWakeTimer', 'every interval, in working hours');
    var r = check('Finished jobs and runs', w.runs, 'hbWakeRuns', 'assistant jobs, delegated tasks and runs of the one program');
    var m = check('New mail in Rouh’s own inbox', w.mail, 'hbWakeMail', 'never your own inbox');
    [t, r, m].forEach(function (x) { f.appendChild(x.label); });
    f.appendChild(el('h5', 'hb-h5', 'Flood guard'));
    var row1 = row();
    var gap = field('At least (seconds apart)', 'number', fl.gap_seconds, 'hbGap');
    gap.input.min = '0'; gap.input.max = '3600';
    var most = field('At most (wakes)', 'number', fl.most, 'hbMost');
    most.input.min = '1'; most.input.max = '100';
    var win = field('in (minutes)', 'number', fl.window_minutes, 'hbWindow');
    win.input.min = '1'; win.input.max = '1440';
    row1.appendChild(gap.label); row1.appendChild(most.label); row1.appendChild(win.label);
    f.appendChild(row1);
    f.appendChild(el('p', 'settings-help', 'Whatever arrives faster waits, and the next beat hears it all together.'));
    f.save();
    s.appendChild(f);
    return s;
  }

  function skipsCard(d) {
    var k = d.config.skip;
    var s = card('Skips', 'checked in code, before any model is called', 'hb-skips', 'skips');
    var f = form('skips', 'Skips', function () {
      act('set', { skip: { busy: busy.input.checked, nothing_new: nn.input.checked,
                           nothing_new_hours: hours.input.value, nothing_on: off.input.checked } });
    });
    var busy = check('Rouh is already in a turn', k.busy, 'hbSkipBusy', 'it looks again in a few minutes');
    var nn = check('Nothing new since the last beat', k.nothing_new, 'hbSkipNew', 'no finished work, no mail, nothing due, no answer');
    var hours = field('…and a full beat within (hours)', 'number', k.nothing_new_hours, 'hbSkipHours', 'wide');
    hours.input.min = '1'; hours.input.max = '72';
    var off = check('No duty is on', k.nothing_on, 'hbSkipOff');
    [busy, nn].forEach(function (x) { f.appendChild(x.label); });
    f.appendChild(hours.label);
    f.appendChild(off.label);
    f.appendChild(el('p', 'settings-help', 'Always skipped: while paused, in quiet hours, and once today’s spend reaches the daily cap. A quest is also skipped while it is paused, before its start, after its end or with its budget spent.'));
    f.save();
    s.appendChild(f);
    return s;
  }

  function messagesCard(d) {
    var m = d.config.messages;
    var s = card('Messages', 'what reaches your phone', 'hb-messages', 'messages');
    var f = form('messages', 'Messaging limits', function () {
      var worth = {};
      boxes.forEach(function (b) { worth[b.key] = b.c.input.checked; });
      act('set', { messages: { per_hour: ph.input.value, per_day: pd.input.value, quiet_on: qon.input.checked,
                               quiet_from: qf.input.value, quiet_to: qt.input.value, summary_at: sum.input.value,
                               worth: worth } });
    });
    var r = row();
    var ph = field('At most an hour', 'number', m.per_hour, 'hbPerHour');
    ph.input.min = '0'; ph.input.max = '20';
    var pd = field('At most a day', 'number', m.per_day, 'hbPerDay');
    pd.input.min = '0'; pd.input.max = '100';
    r.appendChild(ph.label); r.appendChild(pd.label);
    f.appendChild(r);
    f.appendChild(el('p', 'settings-help', 'A yes that is blocking work may go past the hourly limit, never the daily one. What is held back is kept as a note for your next conversation.'));
    var qon = check('Quiet hours for messages', m.quiet_on, 'hbMsgQuietOn', 'kept and sent together when they end');
    f.appendChild(qon.label);
    var r2 = row();
    var qf = field('From', 'time', m.quiet_from, 'hbMsgQuietFrom');
    var qt = field('to', 'time', m.quiet_to, 'hbMsgQuietTo');
    r2.appendChild(qf.label); r2.appendChild(qt.label);
    f.appendChild(r2);
    f.appendChild(el('h5', 'hb-h5', 'Worth a message'));
    var names = { needs_yes: 'It needs your yes', needs_human: 'It needs a human step', earned: 'Money came in',
                  broken: 'Something broke', summary: 'A daily summary' };
    var boxes = Object.keys(names).map(function (key) {
      var c = check(names[key], m.worth[key], 'hbWorth_' + key);
      f.appendChild(c.label);
      return { key: key, c: c };
    });
    var sum = field('The summary at', 'time', m.summary_at, 'hbSummaryAt');
    f.appendChild(sum.label);
    f.save();
    s.appendChild(f);
    return s;
  }

  function pickedAsks() {
    return Object.keys(H.picked).filter(function (k) { return H.picked[k]; }).map(Number);
  }

  /* Select all, how many are ticked, and Delete selected, as on the Beats page. */
  function queuePick(waiting) {
    var ids = pickedAsks();
    var r = el('div', 'hb-actions hb-ask-pick');
    var label = el('label', 'hb-check hb-ask-all');
    var all = el('input');
    all.type = 'checkbox';
    all.id = 'asksAll';
    all.checked = ids.length > 0 && ids.length === waiting.length;
    all.indeterminate = ids.length > 0 && ids.length < waiting.length;
    all.addEventListener('change', function () {
      H.picked = {};
      if (all.checked) waiting.forEach(function (a) { H.picked[a.id] = true; });
      draw();
    });
    label.appendChild(all);
    label.appendChild(el('span', '', 'Select all'));
    r.appendChild(label);
    r.appendChild(el('span', 'bt-picked', ids.length ? count(ids.length, 'approval') + ' selected' : 'None selected'));
    var del = button('Delete selected', 'danger', function () { deleteAsks(null); }, 'Delete the selected approvals: neither a yes nor a no');
    del.id = 'asksDelete';
    del.disabled = !ids.length || H.busy;
    r.appendChild(del);
    return r;
  }

  function count(n, one) { return n + ' ' + (n === 1 ? one : one + 's'); }

  /* An approval's one name: its decision's number, "Decision 351", or '' before it is one.
     Never the queue's own id, which read as a second number for the same thing. */
  function askNumber(a) { return a.decision ? 'Decision ' + a.decision : ''; }
  /* An approval as a confirmation names it: its number and its first line, cut short. */
  function askName(a) {
    var first = String(a.what || '').split('\n')[0].trim();
    if (first.length > 90) first = first.slice(0, 89).trim() + '\u2026';
    return [askNumber(a), first ? '\u201c' + first + '\u201d' : ''].filter(Boolean).join(' ');
  }

  var DELETE_MEANS = 'It is not a yes and not a no: nothing it describes will ever run, and the heartbeat ' +
    'is not told it was answered. A yes sent to it later on Telegram does nothing.';

  /** @param {?{id: number, what: string}} one the approval its own Delete was pressed on, or null for the ticked ones */
  function deleteAsks(one) {
    var ids = one ? [one.id] : pickedAsks();
    if (!ids.length) return;
    var words = one ? 'Delete ' + askName(one) + '?\n\n' + DELETE_MEANS :
      'Delete ' + count(ids.length, 'approval') + '?\n\n' + (ids.length === 1 ? DELETE_MEANS :
        'They are not a yes and not a no: nothing they describe will ever run, and the heartbeat ' +
        'is not told they were answered. A yes sent to any of them later on Telegram does nothing.');
    if (!window.confirm(words)) return;
    H.said = '';
    call('POST', '/api/heartbeat/approvals', { act: 'delete', ids: ids }).then(function (j) {
      if (j && j.ok) ids.forEach(function (i) { delete H.picked[i]; });
      draw();
    });
  }

  /* The silent notes beats left for Rouh's next conversation with Petar. Every beat itself is
     on the beats' own page (`beatspage.js`). */
  function notesCard(d) {
    var s = card('Notes it left you', 'the newest ' + d.state.notes.length + ', kept for your next conversation', 'hb-notes', 'notes');
    var ul = el('ul', 'hb-events');
    d.state.notes.slice().reverse().forEach(function (n) {
      ul.appendChild(el('li', n.seen ? 'seen' : '', n.at + ' · ' + n.text + (n.seen ? '' : ' (not yet said)')));
    });
    s.appendChild(ul);
    return s;
  }

  /* ---- the header, on all three views ---- */

  var VIEWS = [['today', 'Today', '/anatomy/behaviour/heartbeat'],
               ['beats', 'Beats', '/anatomy/behaviour/beats'],
               ['settings', 'Settings', '/anatomy/behaviour/heartbeat/settings']];
  // The headers drawn on the beats' page (`beatspage.js`), redrawn whenever the heartbeat is read.
  var mounted = [];

  function go(href, e) {
    if (e && (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1)) return;
    if (e) e.preventDefault();
    var view = href === VIEWS[2][2] ? 'settings' : href === VIEWS[0][2] ? 'today' : '';
    if (view && H.open && host().viewed) {
      if (view === 'today') { H.day = -1; H.beat = 0; }
      H.said = '';
      H.error = '';
      H.view = view;
      H.editing = '';
      draw();
      toTop();
      host().viewed(view === 'settings' ? 'settings' : '');
      return;
    }
    if (host().go) host().go(href);
  }

  /** A view changed: its top shown, in whatever scrolls it (Anatomy's body, or this one). */
  function toTop() {
    var b = $('heartbeatBody');
    if (!b) return;
    b.scrollTop = 0;
    var outer = b.closest('.settings-body');
    if (outer) outer.scrollTop = 0;
  }

  function goLink(text, href, cls) {
    var a = el('a', cls || 'hb-link', text);
    a.href = href;
    a.addEventListener('click', function (e) { go(href, e); });
    return a;
  }

  function waitingOf(d) {
    return ((d && d.approvals) || []).filter(function (a) { return a.state === 'waiting'; });
  }

  /** How it stands, in a word and a tone: on, paused, or paused for today at the cap. */
  function standing(d) {
    if (!d) return { word: 'Reading…', tone: 'idle' };
    if (d.state.paused) return { word: 'Paused', tone: 'off' };
    if (d.state.capped) return { word: 'Paused for today', tone: 'warn' };
    return { word: 'On', tone: 'on' };
  }

  /** The header every view of the heartbeat has: how it stands, Pause or Resume, Beat now,
      and the three views. @param {string} view @param {?Object} d */
  function header(view, d) {
    var head = el('header', 'hb2-head');
    var top = el('div', 'hb2-head-top');
    var st = standing(d);
    var pill = el('p', 'hb2-pill ' + st.tone);
    pill.appendChild(el('span', 'hb2-pill-dot'));
    pill.appendChild(el('span', '', st.word));
    pill.setAttribute('role', 'status');
    top.appendChild(pill);
    if (d && !d.state.paused && d.state.next && !d.state.capped) {
      top.appendChild(el('span', 'hb2-next', 'Next look ' + d.state.next));
    }
    var acts = el('div', 'hb2-head-acts');
    if (d) {
      var paused = d.state.paused;
      var pb = button(paused ? 'Resume' : 'Pause', paused ? 'primary' : '', function () {
        act(paused ? 'resume' : 'pause');
      }, paused ? 'Start beating again' : 'Stop every beat until you resume it');
      pb.id = 'heartbeatPause';
      acts.appendChild(pb);
      var now = button('Beat now', '', function () {
        act('now').then(function () { setTimeout(load, 2500); });
      }, 'A beat on its duties now, whatever the timer says');
      now.id = 'heartbeatNow';
      acts.appendChild(now);
    }
    top.appendChild(acts);
    head.appendChild(top);
    var tabs = el('nav', 'hb2-tabs');
    tabs.setAttribute('aria-label', 'The heartbeat');
    VIEWS.forEach(function (v) {
      var a = goLink(v[1], v[2], 'hb2-tab');
      if (v[0] === view) a.setAttribute('aria-current', 'page');
      if (v[0] === 'today') {
        var n = waitingOf(d).length;
        if (n) {
          var c = el('span', 'hb2-count', String(n));
          c.title = n + ' waiting on you';
          a.appendChild(c);
        }
      }
      tabs.appendChild(a);
    });
    head.appendChild(tabs);
    return head;
  }

  /** The header drawn into the beats' page; it reads the heartbeat itself when nothing has. */
  function mountHeader(node) {
    if (!node) return;
    if (mounted.indexOf(node) < 0) mounted.push(node);
    mounted = mounted.filter(function (n) { return document.body.contains(n); });
    node.textContent = '';
    node.appendChild(header('beats', H.data));
    if (!H.data && !H.busy) load();
  }

  function heads() {
    mounted = mounted.filter(function (n) { return document.body.contains(n); });
    mounted.forEach(function (n) { n.textContent = ''; n.appendChild(header('beats', H.data)); });
  }

  /* ---- Today ---- */

  var END_WORDS = { skipped: 'Skipped in code', slept: 'Check: nothing to do', nothing: 'Did nothing',
                    note: 'Left a note', message: 'Messaged you', asked: 'Asked for your yes',
                    failed: 'Failed', running: 'Running' };
  var LEGEND = ['note', 'message', 'asked', 'nothing', 'slept', 'skipped', 'failed', 'running'];
  var WOKE_WORDS = { timer: 'the timer', event: 'an event', due: 'its own set time', now: 'Beat now',
                     answer: 'your answer', summary: 'the daily summary' };

  function dayList(d) { return (d.days && d.days.list) || []; }
  function shownDay(d) {
    var list = dayList(d);
    if (!list.length) return null;
    var i = H.day < 0 || H.day >= list.length ? list.length - 1 : H.day;
    return list[i];
  }
  function isToday(d, day) { var l = dayList(d); return !!day && l.length && l[l.length - 1] === day; }
  function decidedOf(c) { return c.nothing + c.note + c.message + c.asked; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }
  function cents(v) { return '$' + Number(v || 0).toFixed(2); }

  function today(page, d) {
    var day = shownDay(d);
    page.appendChild(verdict(d));
    page.appendChild(tiles(d, day));
    page.appendChild(dayCard(d, day));
    var two = el('div', 'hb2-two');
    two.appendChild(needsCard(d));
    two.appendChild(carriesCard(d));
    page.appendChild(two);
    if (d.state.notes && d.state.notes.length) page.appendChild(notesCard(d));
  }

  /* One sentence that answers "is it working on my things, and is anything stuck?", then the
     few facts that back it, then the one thing to press. */
  function verdict(d) {
    var s = el('section', 'hb2-verdict');
    s.setAttribute('aria-label', 'How the heartbeat stands');
    var waiting = waitingOf(d).length;
    var todayDay = dayList(d).length ? dayList(d)[dayList(d).length - 1] : null;
    var failed = todayDay ? todayDay.counts.failed : 0;
    var carried = (d.carried || []).filter(function (w) { return w.carried && !w.why_not; }).length;
    var line;
    if (d.state.paused) line = 'Paused. Nothing beats until you resume it.';
    else if (d.state.capped) line = 'Paused for today: the daily cap is reached.';
    else if (waiting) line = 'Working, and ' + plural(waiting, 'thing waits', 'things wait') + ' for your answer.';
    else if (failed) line = 'Working, but ' + plural(failed, 'beat') + ' failed today.';
    else line = 'Working on your things. Nothing is stuck.';
    s.appendChild(el('h3', 'hb2-say', line));
    var facts = el('ul', 'hb2-facts');
    function fact(text, cls) { var li = el('li', cls || '', text); facts.appendChild(li); return li; }
    if (d.state.capped && !d.state.paused) {
      var why = String(d.state.capped).replace(/^Paused for today:\s*/, '');
      fact(why.charAt(0).toUpperCase() + why.slice(1), 'wide');
    }
    if (!d.state.paused && d.state.next && !d.state.capped) fact('Next look ' + d.state.next);
    if (d.state.last_full) fact('Last full beat ' + d.state.last_full);
    fact(carried ? 'Working on ' + plural(carried, 'quest') : 'Working on no quests');
    if (failed && (waiting || d.state.paused || d.state.capped)) fact(plural(failed, 'beat') + ' failed today', 'bad');
    if (waiting && (d.state.paused || d.state.capped)) fact(plural(waiting, 'thing waits', 'things wait') + ' on you', 'waits');
    if (d.state.pending) fact(plural(d.state.pending, 'event') + ' waiting for the next beat');
    s.appendChild(facts);
    var acts = el('div', 'hb2-verdict-acts');
    if (waiting) {
      var first = waitingOf(d)[0];
      var b = goLink(waiting === 1 ? 'Answer it in Decisions' : 'Answer them in Decisions',
                     waiting === 1 && first.href ? first.href : '/decisions',
                     // Paused, Resume in the header is the one main button.
                     'ctl hb2-cta' + (d.state.paused ? ' quiet' : ' primary'));
      b.id = 'heartbeatAnswer';
      acts.appendChild(b);
    }
    if (d.state.chat) acts.appendChild(goLink('Open the Heartbeat chat', '/chat/' + encodeURIComponent(d.state.chat)));
    if (acts.childNodes.length) s.appendChild(acts);
    return s;
  }

  function bar(part, whole, cls, label) {
    var b = el('span', 'hb2-bar ' + (cls || ''));
    var f = el('span', 'hb2-bar-fill');
    f.style.width = Math.max(0, Math.min(100, whole ? 100 * part / whole : 0)) + '%';
    b.appendChild(f);
    b.setAttribute('role', 'img');
    b.setAttribute('aria-label', label);
    return b;
  }

  /** One of the day's numbers: its value, what it is, the same in a few words for a phone, and
      what more there is to say. */
  function tile(cls, value, words, extra, short) {
    var t = el('div', 'hb2-tile ' + (cls || ''));
    t.appendChild(el('p', 'hb2-tile-v', value));
    t.appendChild(el('p', 'hb2-tile-l', words));
    if (short) {
      t.lastChild.classList.add('long');
      t.appendChild(el('p', 'hb2-tile-l short', short));
    }
    if (extra) t.appendChild(extra);
    return t;
  }

  /* The day's four numbers, for the day the picture shows: what it cost, how many beats and how
     they went, the messages, and what waits on him now. */
  function tiles(d, day) {
    var row = el('section', 'hb2-tiles');
    row.setAttribute('aria-label', 'The numbers for ' + (day ? day.label.toLowerCase() : 'today'));
    var cap = (d.days && d.days.cap_value) || 0;
    var spent = day ? day.spent_value : 0;
    var over = cap && spent > cap;
    var reached = (isToday(d, day) && !!d.state.capped) || over;
    row.appendChild(tile(reached ? 'warn' : '', day ? day.spent : '$0.00',
      (day && !isToday(d, day) ? 'spent ' + day.label : 'spent today') + ' of the ' + cents(cap) + ' daily cap' +
      (over ? ', over it' : reached ? ', cap reached' : ''),
      bar(reached ? Math.max(spent, cap) : spent, cap, reached ? 'warn' : '', 'Spent ' + (day ? day.spent : '$0.00') + ' of ' + cents(cap) +
        (reached ? ', the cap reached' : '')), reached ? 'of ' + cents(cap) + ', cap reached' : 'spent, of ' + cents(cap)));
    var c = day ? day.counts : { nothing: 0, note: 0, message: 0, asked: 0, slept: 0, skipped: 0, failed: 0, running: 0 };
    var total = day ? day.beats.length : 0;
    var stack = el('span', 'hb2-stack');
    stack.setAttribute('role', 'img');
    stack.setAttribute('aria-label', decidedOf(c) + ' decided, ' + c.slept + ' let sleep, ' + c.skipped +
      ' skipped in code, ' + c.failed + ' failed');
    [['decided', decidedOf(c)], ['slept', c.slept], ['skipped', c.skipped], ['failed', c.failed], ['running', c.running]].forEach(function (p) {
      if (!p[1]) return;
      var seg = el('span', 'hb2-seg ' + p[0]);
      seg.style.flexGrow = String(p[1]);
      stack.appendChild(seg);
    });
    var key = el('p', 'hb2-tile-k', decidedOf(c) + ' decided · ' + c.slept + ' slept · ' + c.skipped + ' skipped' +
      (c.failed ? ' · ' + c.failed + ' failed' : '') + (c.running ? ' · ' + c.running + ' running' : ''));
    var wrap = el('div', '');
    wrap.appendChild(stack);
    wrap.appendChild(key);
    key.classList.add('more');
    row.appendChild(tile(c.failed ? 'bad' : '', String(total), plural(total, 'beat').replace(/^\d+ /, '') +
      (day && !isToday(d, day) ? ' ' + day.label : ' today'), wrap, total === 1 ? 'beat' : 'beats'));
    var per = (d.days && d.days.per_day) || 0;
    var msgWords = (c.message === 1 ? 'message' : 'messages') + ' to your phone' +
      (day && !isToday(d, day) ? ' ' + day.label : ' today') + ' (at most ' + per + ')';
    var msgMore = [];
    if (isToday(d, day) && d.state.held) msgMore.push(plural(d.state.held, 'message') + ' held for after quiet hours');
    if (!d.telegram && isToday(d, day)) msgMore.push('Your phone is not set up now, so new messages become notes');
    row.appendChild(tile('', String(c.message), msgWords, msgMore.length ? el('p', 'hb2-tile-k more', msgMore.join('. ') + '.') : null,
      c.message === 1 ? 'message' : 'messages'));
    var waiting = waitingOf(d).length;
    var wt = tile(waiting ? 'ask' : '', String(waiting), waiting ? 'waiting on you now' : 'nothing waits on you',
      null, waiting ? 'wait on you' : 'wait on you');
    wt.appendChild(goLink(waiting ? 'Open Decisions' : 'Decisions', '/decisions', 'hb-link hb2-tile-a more'));
    row.appendChild(wt);
    return row;
  }

  /* The week, a day a bar by what it cost against the cap; pressing one shows that day. */
  function week(d) {
    var list = dayList(d);
    var cap = (d.days && d.days.cap_value) || 0;
    var most = Math.max(cap, Math.max.apply(null, list.map(function (x) { return x.spent_value; }).concat([0.01])));
    var w = el('div', 'hb2-week');
    w.setAttribute('role', 'group');
    w.setAttribute('aria-label', 'Pick a day');
    var shown = shownDay(d);
    list.forEach(function (x, i) {
      var b = el('button', 'hb2-wday' + (x === shown ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('aria-pressed', x === shown ? 'true' : 'false');
      b.setAttribute('aria-label', x.label + ': ' + plural(x.beats.length, 'beat') + ', ' + x.spent + ' spent');
      var col = el('span', 'hb2-wbar');
      var fill = el('span', 'hb2-wfill' + (cap && x.spent_value > cap ? ' over' : ''));
      fill.style.height = Math.max(2, 100 * x.spent_value / most) + '%';
      col.appendChild(fill);
      b.appendChild(col);
      b.appendChild(el('span', 'hb2-wname', i === list.length - 1 ? 'Today' : x.short));
      var overCap = cap && x.spent_value > cap;
      b.appendChild(el('span', 'hb2-wsum' + (overCap ? ' over' : ''), x.spent));
      if (overCap) b.appendChild(el('span', 'hb2-wover', 'over cap'));
      if (overCap) b.setAttribute('aria-label', b.getAttribute('aria-label') + ', over the daily cap');
      b.addEventListener('click', function () {
        H.day = i === list.length - 1 ? -1 : i;
        H.beat = 0;
        draw();
        var again = document.querySelector('.hb2-wday.on');
        if (again) /** @type {HTMLElement} */ (again).focus();
      });
      w.appendChild(b);
    });
    return w;
  }

  function hhmm(t) { var m = /^(\d\d):(\d\d)$/.exec(String(t || '')); return m ? (+m[1]) * 60 + (+m[2]) : 0; }
  /** The minutes of a day a range from one time to another covers, as one or two pieces. */
  function spans(from, to) {
    var a = hhmm(from), b = hhmm(to);
    if (a === b) return [];
    return a < b ? [[a, b]] : [[a, 1440], [0, b]];
  }
  /* The part of the day the picture shows, in minutes: the whole day, or on a narrow screen
     the hours that hold its beats, so a busy day's marks have room. */
  var WIN = [0, 1440];
  function pctOf(min) { return (100 * (min - WIN[0]) / (WIN[1] - WIN[0])) + '%'; }
  function span(a, b) { return (100 * (Math.min(b, WIN[1]) - Math.max(a, WIN[0])) / (WIN[1] - WIN[0])) + '%'; }
  function windowFor(day, now, narrow) {
    if (!narrow || H.wholeDay || !day.beats.length) return [0, 1440];
    var first = day.beats[0].min, last = day.beats[day.beats.length - 1].min;
    if (now != null) last = Math.max(last, now);
    var a = Math.max(0, Math.floor(first / 60) * 60), b = Math.min(1440, Math.ceil((last + 1) / 60) * 60);
    if (b - a < 8 * 60) { a = Math.max(0, b - 8 * 60); b = Math.min(1440, a + 8 * 60); }
    return [a, b];
  }

  /** The bands behind a day: working hours lighter, quiet hours hatched. */
  function bands(cfg, into) {
    spans(cfg.hours.work_from, cfg.hours.work_to).forEach(function (p) {
      if (p[1] <= WIN[0] || p[0] >= WIN[1]) return;
      var b = el('span', 'hb2-band work');
      b.style.left = pctOf(Math.max(p[0], WIN[0])); b.style.width = span(p[0], p[1]);
      into.appendChild(b);
    });
    if (cfg.hours.quiet_on) {
      spans(cfg.hours.quiet_from, cfg.hours.quiet_to).forEach(function (p) {
        if (p[1] <= WIN[0] || p[0] >= WIN[1]) return;
        var b = el('span', 'hb2-band quiet');
        b.style.left = pctOf(Math.max(p[0], WIN[0])); b.style.width = span(p[0], p[1]);
        into.appendChild(b);
      });
    }
  }

  function glyph(end) {
    var g = el('span', 'hb2-glyph ' + end);
    g.setAttribute('aria-hidden', 'true');
    return g;
  }

  /** The lane a beat is drawn in: its quest, its own duties (null), or 'gone' for every quest
      since deleted, drawn together. */
  function laneOf(d, b) {
    if (b.lane == null) return null;
    return (d.carried || []).some(function (w) { return w.id === b.lane; }) ? b.lane : 'gone';
  }

  function laneName(d, id) {
    if (id == null) return 'Its own duties';
    if (id === 'gone') return 'Quests since deleted';
    var w = (d.carried || []).filter(function (x) { return x.id === id; })[0];
    return w ? w.number + ' ' + w.title : 'A deleted quest';
  }

  /* The day as a picture: a lane for its own duties and one for each quest, every beat a mark
     where it happened, shaped by how it ended; quiet hours hatched, now and the next look
     marked. A mark pressed says what that beat did, with the way to open it. */
  function dayCard(d, day) {
    var s = el('section', 'setting-card hb-card hb2-daycard');
    s.setAttribute('aria-labelledby', 'hbDayTitle');
    var top = el('div', 'hb2-day-top');
    var h = el('h4', 'hb-h', day ? (isToday(d, day) ? 'Today, beat by beat' : day.label + ', beat by beat') : 'The day');
    h.id = 'hbDayTitle';
    top.appendChild(h);
    top.appendChild(week(d));
    s.appendChild(top);
    if (!day) { s.appendChild(el('p', 'hb-empty', 'No beats yet.')); return s; }
    var lanes = [null];
    (d.carried || []).forEach(function (w) { if (w.carried && !w.why_not) lanes.push(w.id); });
    day.beats.forEach(function (b) { var l = laneOf(d, b); if (lanes.indexOf(l) < 0) lanes.push(l); });
    var pic = el('div', 'hb2-day');
    var now = isToday(d, day) && d.days ? d.days.now_min : null;
    var host_ = $('heartbeatBody');
    var wide = host_ ? host_.clientWidth : 1000;
    var narrow = wide < 600;
    WIN = windowFor(day, now, narrow);
    var axis = el('div', 'hb2-axis');
    axis.setAttribute('aria-hidden', 'true');
    var hours = (WIN[1] - WIN[0]) / 60, stepH = hours > 12 ? 3 : 2;
    for (var hr = WIN[0] / 60; hr <= WIN[1] / 60; hr += stepH) {
      var t = el('span', 'hb2-tick', (hr < 10 ? '0' : '') + hr + ':00');
      t.style.left = pctOf(hr * 60);
      if (hr === WIN[0] / 60) t.classList.add('start');
      if (hr + stepH > WIN[1] / 60) t.classList.add('end');
      axis.appendChild(t);
    }
    // Marks closer than a mark's width step into a second or third row, so none hides another.
    var trackPx = Math.max(200, wide - 60), gap = 13 * (WIN[1] - WIN[0]) / trackPx;
    lanes.forEach(function (id) {
      var mine = day.beats.filter(function (b) { return laneOf(d, b) === id; });
      var lane = el('div', 'hb2-lane');
      var name = el('p', 'hb2-lane-name');
      name.appendChild(el('span', 'hb2-lane-title', laneName(d, id)));
      name.appendChild(el('span', 'hb2-lane-n', mine.length ? plural(mine.length, 'beat') : 'no beats'));
      lane.appendChild(name);
      var track = el('div', 'hb2-track');
      bands(d.config, track);
      if (now != null) {
        var nl = el('span', 'hb2-now');
        nl.style.left = pctOf(now);
        nl.setAttribute('aria-hidden', 'true');
        track.appendChild(nl);
        if (d.days.next_min != null && id === null) {
          var nx = el('span', 'hb2-nextmark');
          nx.style.left = pctOf(d.days.next_min);
          nx.title = 'Next look ' + d.state.next;
          nx.setAttribute('aria-hidden', 'true');
          track.appendChild(nx);
        }
      } else if (!isToday(d, day)) {
        // a past day is all past
      }
      if (now != null) {
        var future = el('span', 'hb2-future');
        future.style.left = pctOf(now);
        future.style.width = span(now, WIN[1]);
        future.setAttribute('aria-hidden', 'true');
        track.appendChild(future);
      }
      // The marks are drawn, not pressed one by one: on a busy day they are closer together
      // than a finger, so a press anywhere on the lane picks the beat nearest to it, and the
      // panel it opens steps to the beat before or after.
      var lastIn = [-1e9, -1e9, -1e9];
      mine.forEach(function (b) {
        var r = 0;
        while (r < 2 && b.min - lastIn[r] < gap) r++;
        lastIn[r] = b.min;
        var m = el('span', 'hb2-mark row' + r + (H.beat === b.id ? ' on' : ''));
        m.style.left = pctOf(b.min);
        m.setAttribute('aria-hidden', 'true');
        m.appendChild(glyph(b.end));
        track.appendChild(m);
      });
      if (mine.length) {
        var pick = el('button', 'hb2-pick');
        pick.type = 'button';
        pick.setAttribute('aria-label', laneName(d, id) + ': ' + plural(mine.length, 'beat') +
          '. Press to open the latest; on the picture, the one nearest where you press');
        pick.addEventListener('click', function (e) {
          var box = track.getBoundingClientRect();
          var at = e.detail && box.width ? 1440 * (e.clientX - box.left) / box.width : null;
          var best = mine[mine.length - 1];
          if (at != null) {
            mine.forEach(function (b) { if (Math.abs(b.min - at) < Math.abs(best.min - at)) best = b; });
          }
          H.beat = best.id;
          draw();
          var panel = document.querySelector('.hb2-beat .hb2-step');
          if (panel) /** @type {HTMLElement} */ (panel).focus();
        });
        track.appendChild(pick);
      }
      lane.appendChild(track);
      pic.appendChild(lane);
    });
    pic.appendChild(axis);
    s.appendChild(pic);
    var picked = day.beats.filter(function (b) { return b.id === H.beat; })[0];
    if (picked) s.appendChild(beatPanel(d, picked));
    var legend = el('ul', 'hb2-legend');
    legend.setAttribute('aria-label', 'What the marks mean');
    LEGEND.forEach(function (k) {
      if (k === 'running' && !day.counts.running) return;
      var li = el('li', '');
      li.appendChild(glyph(k));
      li.appendChild(el('span', '', END_WORDS[k] + ' ' + (day.counts[k] || 0)));
      legend.appendChild(li);
    });
    var q = el('li', '');
    q.appendChild(el('span', 'hb2-glyph quietkey'));
    q.appendChild(el('span', '', 'Quiet hours'));
    legend.appendChild(q);
    s.appendChild(legend);
    var foot = el('div', 'hb2-day-foot');
    if (narrow && day.beats.length) {
      var whole = button(H.wholeDay ? 'Show the busy hours' : 'Show the whole day', 'hb2-whole', function () {
        H.wholeDay = !H.wholeDay; draw();
      }, H.wholeDay ? 'Widen the hours that hold beats' : 'All 24 hours, from 00:00');
      foot.appendChild(whole);
    }
    foot.appendChild(goLink('Every beat ' + (isToday(d, day) ? 'today' : day.label) + ', as a table',
      '/anatomy/behaviour/beats?from=' + day.day + '&to=' + day.day));
    s.appendChild(foot);
    return s;
  }

  function beatPanel(d, b) {
    var p = el('div', 'hb2-beat');
    p.setAttribute('role', 'region');
    p.setAttribute('aria-label', 'The beat at ' + b.at);
    var head = el('p', 'hb2-beat-head');
    head.appendChild(glyph(b.end));
    head.appendChild(el('strong', '', b.at + ' · ' + (END_WORDS[b.end] || b.end)));
    head.appendChild(el('span', 'hb2-beat-meta', laneName(d, laneOf(d, b)) + ' · woken by ' +
      (WOKE_WORDS[b.woke] || b.woke) + (b.cost ? ' · ' + b.cost : ' · cost nothing')));
    p.appendChild(head);
    var words = b.said || b.why;
    if (words) p.appendChild(el('p', 'hb2-beat-words', words));
    var acts = el('div', 'hb-actions hb2-beat-acts');
    var day = shownDay(d);
    var all = day ? day.beats : [b];
    var at = all.indexOf(b);
    [['Earlier', at - 1], ['Later', at + 1]].forEach(function (p) {
      var step = button(p[0], 'hb2-step', function () {
        H.beat = all[p[1]].id;
        draw();
        var again = document.querySelector('.hb2-beat .hb2-step[data-dir="' + p[0] + '"]');
        if (again && !(/** @type {HTMLButtonElement} */ (again)).disabled) /** @type {HTMLElement} */ (again).focus();
      }, p[0] === 'Earlier' ? 'The beat before this one, on any lane' : 'The beat after this one, on any lane');
      step.dataset.dir = p[0];
      step.disabled = p[1] < 0 || p[1] >= all.length;
      acts.appendChild(step);
    });
    acts.appendChild(goLink('Open this beat', '/anatomy/behaviour/beats?beat=' + b.id, 'ctl small hb2-open'));
    var close = button('Close', '', function () { H.beat = 0; draw(); });
    acts.appendChild(close);
    p.appendChild(acts);
    return p;
  }

  /* What waits on him: never answered twice, so each goes to its decision on the one list. */
  function needsCard(d) {
    var waiting = waitingOf(d);
    var s = card('Needs you', waiting.length ? String(waiting.length) : '', 'hb2-needs', 'needs');
    if (!waiting.length) {
      s.appendChild(el('p', 'hb-empty', 'Nothing waits on you. Whatever a beat may not do by itself, such as paying or ' +
        'sending for you, is put on Decisions and runs only on your yes.'));
    } else {
      var ul = el('ul', 'hb2-asks');
      waiting.slice(0, 5).forEach(function (a) {
        var li = el('li', '');
        var link = goLink('', a.href || '/decisions', 'hb2-ask');
        link.appendChild(el('span', 'hb2-ask-n', a.decision ? 'Decision ' + a.decision : 'Waiting'));
        link.appendChild(el('span', 'hb2-ask-what', String(a.what || '').split('\n')[0]));
        var meta = [a.by && a.by.label, a.cost, a.blocking ? 'blocking' : '', a.asked ? 'asked ' + a.asked : '']
          .filter(Boolean).join(' · ');
        link.appendChild(el('span', 'hb2-ask-meta', meta));
        li.appendChild(link);
        ul.appendChild(li);
      });
      s.appendChild(ul);
      var all = goLink(waiting.length > 5 ? 'All ' + waiting.length + ' in Decisions' : 'Answer them in Decisions', '/decisions');
      s.appendChild(all);
    }
    // Deleting some for good, neither a yes nor a no, as the old queue here could; answering
    // is only ever where Decisions sends each one. Kept closed, in case.
    if (waiting.length) {
      var keep = el('details', 'brown-toggle hb2-oldqueue');
      if (H.oldQueue) keep.open = true;
      keep.addEventListener('toggle', function () { H.oldQueue = keep.open; });
      keep.appendChild(el('summary', '', 'Delete some of them, neither a yes nor a no'));
      var body = el('div', 'brown-toggle-body');
      body.appendChild(queuePick(waiting));
      var list = el('ul', 'hb2-dellist');
      waiting.forEach(function (a) {
        var li = el('li', '');
        var lab = el('label', 'hb-check');
        var tick = el('input', 'hb-ask-box');
        tick.type = 'checkbox';
        tick.checked = !!H.picked[a.id];
        tick.addEventListener('change', function () {
          if (tick.checked) H.picked[a.id] = true; else delete H.picked[a.id];
          draw();
        });
        lab.appendChild(tick);
        lab.appendChild(el('span', '', (a.decision ? 'Decision ' + a.decision + ': ' : '') + String(a.what || '').split('\n')[0]));
        li.appendChild(lab);
        list.appendChild(li);
      });
      body.appendChild(list);
      keep.appendChild(body);
            s.appendChild(keep);
    }
    return s;
  }

  var QUEST_STATE = { on: 'Working on it', paused: 'Paused', ended: 'Ended', 'not carried': 'Not carried',
                      'not started': 'Not started' };

  /* The quests it carries, each with where it stands, what it cost and what waits on him. */
  function carriesCard(d) {
    var list = d.carried || [];
    var working = list.filter(function (w) { return w.carried && !w.why_not; }).length;
    var s = card('Quests it carries', list.length ? working + ' working, of ' + list.length : '', 'hb2-carries', 'works');
    if (!list.length) {
      s.appendChild(el('p', 'hb-empty', 'None yet. A quest is long-running work it carries for you. Make one on the Quests ' +
        'page, or ask Rouh: “start a quest: …”.'));
      s.appendChild(goLink('The Quests page', '/quests'));
      return s;
    }
    var ul = el('ul', 'hb2-quests');
    list.forEach(function (w) {
      var li = el('li', 'hb2-quest' + (w.carried ? '' : ' dropped'));
      var line = el('div', 'hb2-q-top');
      var sw = el('label', 'hb2-switch');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = !!w.carried;
      box.setAttribute('aria-label', 'The heartbeat carries quest ' + w.number + ' ' + w.title);
      box.addEventListener('change', function () {
        H.said = '';
        call('POST', '/api/heartbeat/work', { id: w.id, act: box.checked ? 'carry' : 'drop' });
      });
      sw.appendChild(box);
      sw.appendChild(el('span', 'hb2-switch-ui'));
      line.appendChild(sw);
      line.appendChild(goLink(w.number + ' ' + w.title, w.href, 'hb2-q-name'));
      var state = w.state || (w.carried ? 'on' : 'not carried');
      // Its own state, but said as the heartbeat's when the heartbeat holds every quest back.
      var held = state === 'on' && (d.state.paused || d.state.capped);
      line.appendChild(el('span', 'hb2-chip ' + (held ? 'held' : state.replace(' ', '-')),
        held ? (d.state.paused ? 'Waits: heartbeat paused' : 'Waits: cap reached') : (QUEST_STATE[state] || state)));
      li.appendChild(line);
      var meta = [];
      if (w.last_beat) meta.push('last beat ' + w.last_beat);
      if (w.next_beat && w.carried && state === 'on') {
        meta.push(d.state.paused ? 'no beat until you resume the heartbeat' :
          d.state.capped ? 'next beat tomorrow, once the cap resets' : 'next ' + w.next_beat);
      }
      if (w.approvals) meta.push(plural(w.approvals, 'waits', 'wait') + ' on you');
      if (state === 'not carried') meta.push('Turn its switch on and the heartbeat works on it');
      else if (w.why_not && state !== 'paused') meta.push(w.why_not);
      else if (state === 'paused') meta.push('Carried, but paused on its own page');
      if (meta.length) li.appendChild(el('p', 'hb2-q-meta', meta.join(' · ')));
      if (w.budget) {
        var spent = parseFloat(String(w.spent || '0').replace(/[^0-9.]/g, '')) || 0;
        var budget = parseFloat(String(w.budget).replace(/[^0-9.]/g, '')) || 0;
        var money = el('div', 'hb2-q-money');
        money.appendChild(bar(spent, budget, w.over ? 'warn' : '', 'Spent ' + w.spent + ' of a ' + w.budget + ' budget'));
        money.appendChild(el('span', '', w.spent + ' of ' + w.budget + (w.over ? ', over' : '')));
        li.appendChild(money);
      } else if (w.spent) {
        li.appendChild(el('p', 'hb2-q-meta', w.spent + ' spent, no budget set'));
      }
      var acts = el('div', 'hb2-q-acts');
      acts.appendChild(goLink('Its beats', '/anatomy/behaviour/beats/' + w.number));
      var more = el('details', 'hb2-more');
      more.appendChild(el('summary', '', 'More'));
      var mb = el('div', 'hb2-more-body');
      var ask = el('div', 'hb-work-ask');
      mb.appendChild(button('Reset', '', function () { clearWork(w, 'reset'); },
        'Start it again from beat 1, keeping its goal and rules'));
      mb.appendChild(button('Delete', 'danger', function () { clearWork(w, 'delete', ask); },
        'Delete it, and say what becomes of its task'));
      more.appendChild(mb);
      acts.appendChild(more);
      li.appendChild(acts);
      li.appendChild(ask);
      ul.appendChild(li);
    });
    s.appendChild(ul);
    return s;
  }

  /* ---- Settings ---- */

  var PARTS = [['duties', 'Duties'], ['rhythm', 'Rhythm'], ['hours', 'Hours'], ['wakes', 'What wakes it'],
               ['skips', 'Skips'], ['messages', 'Messages']];

  /* The headline of Settings: what it looks after and how often, in one sentence. */
  function settingsHead(d) {
    var c = d.config, on = c.duties.filter(function (x) { return x.on; }).length;
    var words = 'It looks after ' + plural(on, 'duty', 'duties') + ', every ' + d.state.interval_minutes +
      ' minutes from ' + c.hours.work_from + ' to ' + c.hours.work_to +
      (c.hours.quiet_on ? ', silent ' + c.hours.quiet_from + ' to ' + c.hours.quiet_to : '') +
      ', and spends up to ' + d.state.daily_cap + ' a day.';
    return el('p', 'hb2-sethead', words);
  }

  function jumps() {
    var nav = el('nav', 'hb2-jumps');
    nav.setAttribute('aria-label', 'Jump to');
    PARTS.forEach(function (p) {
      var b = button(p[1], 'hb2-jump', function () {
        var c = document.querySelector('#heartbeatBody [data-card="' + p[0] + '"]');
        if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'start' }); var f = c.querySelector('input, textarea'); if (f) /** @type {HTMLElement} */ (f).focus({ preventScroll: true }); }
      });
      nav.appendChild(b);
    });
    return nav;
  }

  /* How often and how much: the interval and the daily cap, with what today has cost. */
  function rhythmCard(d) {
    var s = card('Rhythm', 'how often it looks, and what it may spend a day', 'hb-rhythm', 'rhythm');
    var f = form('rhythm', 'How often and how much', function () {
      act('set', { interval_minutes: iv.input.value, daily_cap: cap.input.value });
    });
    var r = row();
    var iv = field('Every (minutes)', 'number', d.state.interval_minutes, 'hbInterval');
    iv.input.min = '5'; iv.input.max = '1440'; iv.input.step = '1';
    var cap = field('Daily cap on its model spend ($)', 'number', d.state.daily_cap_value, 'hbCap', 'wide');
    cap.input.min = '0'; cap.input.max = '100'; cap.input.step = '0.5';
    r.appendChild(iv.label);
    r.appendChild(cap.label);
    f.appendChild(r);
    f.appendChild(el('p', 'settings-help', 'Spent today ' + d.state.spent_today + ' of ' + d.state.daily_cap +
      ', across every beat, quests included. At the cap it rests until midnight by itself.'));
    f.save();
    s.appendChild(f);
    return s;
  }

  /** The 24 hours as a bar, working hours lighter and quiet hours hatched, redrawn as typed. */
  function dayBar(get) {
    var wrap = el('div', 'hb2-hoursbar');
    var track = el('div', 'hb2-track small');
    var axis = el('div', 'hb2-axis');
    axis.setAttribute('aria-hidden', 'true');
    [0, 6, 12, 18, 24].forEach(function (hr) {
      var t = el('span', 'hb2-tick' + (hr === 24 ? ' end' : ''), (hr < 10 ? '0' : '') + hr + ':00');
      t.style.left = pctOf(hr * 60);
      axis.appendChild(t);
    });
    function paint() {
      track.textContent = '';
      var c = get();
      bands({ hours: c }, track);
      track.setAttribute('aria-label', 'Working ' + c.work_from + ' to ' + c.work_to +
        (c.quiet_on ? ', quiet ' + c.quiet_from + ' to ' + c.quiet_to : ', no quiet hours'));
    }
    track.setAttribute('role', 'img');
    wrap.appendChild(track);
    wrap.appendChild(axis);
    var key = el('ul', 'hb2-legend');
    var a = el('li', ''); a.appendChild(el('span', 'hb2-glyph workkey')); a.appendChild(el('span', '', 'Working hours: the timer beats'));
    var b = el('li', ''); b.appendChild(el('span', 'hb2-glyph quietkey')); b.appendChild(el('span', '', 'Quiet hours: nothing beats'));
    key.appendChild(a); key.appendChild(b);
    wrap.appendChild(key);
    paint();
    wrap.paint = paint;
    return wrap;
  }

  /* ---- shown and left ---- */

  /* What a reset or a delete asks first: the quest by number and name, and how much goes with it. */
  function clearWords(title, t, what) {
    function n(k, one, many) { return t[k] + ' ' + (t[k] === 1 ? one : many); }
    var went = n('beats', 'beat', 'beats') + ', ' + n('notebook', 'notebook entry', 'notebook entries') + ', ' +
      n('ledger', 'ledger line', 'ledger lines') + ' and ' +
      (t.approvals ? n('approvals', 'pending approval', 'pending approvals') : 'no pending approvals');
    if (what === 'reset') {
      return 'Reset ' + title + ' and start it again from beat 1?\n\n' +
        'This clears its ' + went + ', its plan, its notebook and its next beat, and its money starts again from nothing. ' +
        'Its goal, rules, dates and budget are kept. What its beats already cost today still counts ' +
        'toward the heartbeat\u2019s daily cap.';
    }
    return 'Delete ' + title + '?\n\n' +
      'This takes away its ' + went + ', its next beat and its money totals. ' +
      'Runs it started are kept, and so is its chat. What its beats already cost today ' +
      'still counts toward the heartbeat\u2019s daily cap. This cannot be undone.';
  }

  /** @param {string} [view] 'settings', or '' for Today */
  function shownNow(view) {
    var want = view === 'settings' ? 'settings' : 'today';
    if (H.open && want === H.view) return;
    if (H.open) {
      H.view = want;
      H.editing = '';
      draw();
      toTop();
      return;
    }
    H.view = want;
    H.open = true;
    // What was said on the way here, such as a quest deleted on its own page.
    H.said = H.carried || '';
    H.carried = '';
    H.editing = '';
    draw();
    load();
    clearInterval(H.tick);
    H.tick = setInterval(function () { if (H.open && !H.busy && !H.editing) load(); }, 15000);
  }

  function hiddenNow() {
    H.open = false;
    H.editing = '';
    clearInterval(H.tick);
  }

  window.RouhHeartbeat = { shown: shownNow, hidden: hiddenNow, reload: load, clearWords: clearWords,
                          mountHeader: mountHeader,
                          tell: function (text) { H.carried = String(text || ''); } };
})();
