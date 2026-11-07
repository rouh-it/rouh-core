/* The Heartbeat page, at /settings/heartbeat (`rouh/heartbeat.py`, `rouh/web/heartbeat.py`).

   Petar, 5 October 2026: "Heartbeat is the functionality you have to have in
   general. It has nothing to do with the money project/experiment. ... Split
   those two." So this page is the heartbeat and nothing else: whether it is
   on and how often it beats, its working and quiet hours, what wakes it, the
   skips checked before any model is called, its daily cap, its messaging
   limits, what it is to do (its duties, each on or off, and his own words),
   what waits for his yes, and the notes its beats left him. Every beat is on a page of
   its own, the Beats page (`beatspage.js`), since 20 October 2026. The quests it carries
   (`questspage.js`) are listed by number and name only, each with a link to its own page and
   whether the heartbeat works on it; nothing of any one's goal or money is
   here.

   A group of Settings, drawn into `#heartbeatBody` from `/api/heartbeat`;
   every answer is the whole page again. It looks again every fifteen seconds
   while it shows, but never redraws a card being edited. Settings tells it
   when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var H = { open: false, data: null, busy: false, error: '', said: '', seq: 0, tick: 0,
            // A card being typed into, kept out of the timer's redraws.
            editing: '', showAnswered: false, carried: '',
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
          if (r.ok) {
            H.error = '';
            if (j && j.said) H.said = j.said;
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
      if (!H.error) page.appendChild(el('p', 'hb-empty', 'Reading the heartbeat…'));
      return;
    }
    page.appendChild(nowCard(d));
    page.appendChild(dutiesCard(d));
    page.appendChild(worksCard(d));
    page.appendChild(queueCard(d));
    page.appendChild(hoursCard(d));
    page.appendChild(wakesCard(d));
    page.appendChild(skipsCard(d));
    page.appendChild(messagesCard(d));
    if (d.state.notes && d.state.notes.length) page.appendChild(notesCard(d));
    body.scrollTop = keep;
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

  function nowCard(d) {
    var s = card('Heartbeat', '', 'hb-now', 'now');
    s.appendChild(el('p', 'settings-help', 'Rouh’s own turn that nobody asked for. It does its duties in its own chat, ' +
      'and works on each quest it carries in that quest’s own chat.'));
    // At the daily cap it is on but beats no more today, and says so rather than a next look.
    var capped = !d.state.paused && d.state.capped;
    var st = el('p', 'hb-state ' + (d.state.paused || capped ? 'paused' : 'on'));
    st.appendChild(el('span', 'hb-pulse'));
    var c = d.config;
    st.appendChild(document.createTextNode(d.state.paused ? 'Paused. Nothing beats until you resume it.' :
      capped ? d.state.capped :
      'On: every ' + d.state.interval_minutes + ' minutes between ' + c.hours.work_from + ' and ' +
      c.hours.work_to + ', and when something wakes it' + (d.state.next ? '. Next look ' + d.state.next + '.' : '.')));
    s.appendChild(st);
    if (capped) s.appendChild(el('p', 'hb-note', 'The cap limits what the AI behind the heartbeat may cost in ' +
      'a day, billed to the AI account on the Models page. Nothing more is spent on beats today, and you need ' +
      'do nothing: it starts again by itself. The cap is set below.'));
    var facts = [];
    if (d.state.last_full) facts.push('Last full beat ' + d.state.last_full + '.');
    facts.push('Spent today ' + d.state.spent_today + ' of its ' + d.state.daily_cap + ' daily cap, across every beat.');
    if (d.state.pending) facts.push(d.state.pending + ' event' + (d.state.pending === 1 ? '' : 's') + ' waiting for the next beat.');
    if (d.state.held) facts.push(d.state.held + ' message' + (d.state.held === 1 ? '' : 's') + ' kept for after your quiet hours.');
    if (!d.telegram) facts.push('Your phone is not set up, so it leaves notes rather than messages.');
    s.appendChild(el('p', 'hb-note', facts.join(' ')));
    var acts = el('div', 'hb-actions');
    acts.appendChild(button(d.state.paused ? 'Resume' : 'Pause', d.state.paused ? 'primary' : '', function () {
      act(d.state.paused ? 'resume' : 'pause');
    }, d.state.paused ? 'Start beating again' : 'Stop every beat until you resume it'));
    var now = button('Beat now', '', function () {
      act('now').then(function () { setTimeout(load, 2500); });
    }, 'A beat on its duties now, whatever the timer says');
    now.id = 'heartbeatNow';
    acts.appendChild(now);
    if (d.state.chat) {
      var open = el('a', 'hb-link', 'Open the Heartbeat chat');
      open.href = '/chat/' + encodeURIComponent(d.state.chat);
      open.addEventListener('click', function (e) {
        e.preventDefault();
        if (host().go) host().go('/chat/' + encodeURIComponent(d.state.chat));
      });
      acts.appendChild(open);
    }
    // The beats are a page of their own (`beatspage.js`), not a list here.
    var beats = el('a', 'hb-link', 'Every beat');
    beats.id = 'heartbeatBeats';
    beats.href = '/anatomy/behaviour/beats';
    beats.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (host().go) host().go('/anatomy/behaviour/beats');
    });
    acts.appendChild(beats);
    s.appendChild(acts);
    var f = form('now', 'How often and how much', function () {
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
    f.save();
    s.appendChild(f);
    return s;
  }

  function dutiesCard(d) {
    var s = card('What to do', 'its duties, each on or off', 'hb-duties', 'duties');
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

  function worksCard(d) {
    var s = card('Quests it carries', d.works.length ? String(d.works.length) : '', 'hb-works', 'works');
    if (!d.works.length) {
      s.appendChild(el('p', 'hb-empty', 'None yet. Make one on the Quests page, or ask Rouh, such as \u201cstart a quest: \u2026\u201d.'));
      var all = el('a', 'hb-link', 'The Quests page');
      all.href = '/quests';
      all.addEventListener('click', function (e) { e.preventDefault(); if (host().go) host().go('/quests'); });
      s.appendChild(all);
      return s;
    }
    s.appendChild(el('p', 'settings-help', 'Each is a task of its own with its own page and its own chat. With its box ticked, the heartbeat works on it.'));
    var ul = el('ul', 'hb-work-list');
    d.works.forEach(function (w) {
      var li = el('li', 'hb-work');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = !!w.carried;
      box.setAttribute('aria-label', 'The heartbeat carries quest ' + w.number + ' ' + w.title);
      box.addEventListener('change', function () {
        H.said = '';
        call('POST', '/api/heartbeat/work', { id: w.id, act: box.checked ? 'carry' : 'drop' });
      });
      li.appendChild(box);
      var name = el('a', 'hb-work-name', w.number + ' \u00b7 ' + w.title);
      name.href = w.href;
      name.addEventListener('click', function (e) {
        e.preventDefault();
        if (host().go) host().go(w.href);
      });
      li.appendChild(name);
      li.appendChild(el('span', 'hb-work-state', w.why_not || (w.period ? w.period : 'being worked on')));
      var acts = el('div', 'hb-work-acts');
      var beats = el('a', 'hb-link', 'Its beats');
      beats.href = '/settings/beats/' + w.number;
      beats.addEventListener('click', function (e) {
        e.preventDefault();
        if (host().go) host().go('/settings/beats/' + w.number);
      });
      acts.appendChild(beats);
      acts.appendChild(button('Reset', '', function () { clearWork(w, 'reset'); },
        'Start it again from beat 1, keeping its goal and rules'));
      var ask = el('div', 'hb-work-ask');
      acts.appendChild(button('Delete', 'danger', function () { clearWork(w, 'delete', ask); },
        'Delete it, and say what becomes of its task'));
      li.appendChild(acts);
      li.appendChild(ask);
      ul.appendChild(li);
    });
    s.appendChild(ul);
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

  function raisedBy(by) {
    if (!by) return null;
    if (by.href) {
      var a = el('a', 'hb-raised work', by.label);
      a.href = by.href;
      a.addEventListener('click', function (e) { e.preventDefault(); if (host().go) host().go(by.href); });
      return a;
    }
    return el('span', 'hb-raised', by.label);
  }

  function queueCard(d) {
    var waiting = d.approvals.filter(function (a) { return a.state === 'waiting'; });
    var answered = d.approvals.filter(function (a) { return a.state !== 'waiting'; });
    var s = card('Waiting for your yes', waiting.length ? String(waiting.length) : '', 'hb-queue', 'queue');
    if (!waiting.length) {
      s.appendChild(el('p', 'hb-empty', 'Nothing. Whatever a beat may not do by itself - mail to anyone but you, posting, publishing, ' +
        'sharing, a refund, signing up - waits here, saying which duty or which quest raised it.'));
    }
    // Only what is still waiting stays ticked: one answered or deleted elsewhere drops out.
    var still = {};
    waiting.forEach(function (a) { if (H.picked[a.id]) still[a.id] = true; });
    H.picked = still;
    if (waiting.length) s.appendChild(queuePick(waiting));
    waiting.forEach(function (a) { s.appendChild(approval(a, true)); });
    if (answered.length) {
      var more = button(H.showAnswered ? 'Hide answered' : 'Answered (' + answered.length + ')', 'hb-more',
        function () { H.showAnswered = !H.showAnswered; draw(); });
      more.setAttribute('aria-expanded', H.showAnswered ? 'true' : 'false');
      s.appendChild(more);
      if (H.showAnswered) answered.forEach(function (a) { s.appendChild(approval(a, false)); });
    }
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

  /* A waiting approval is a decision (`rouh/decisions.py`), drawn the one way every
     question is (`decision.js`) and answered the one way, with the tick for Delete
     selected above it. Without its decision - the decisions not read yet - it is drawn
     as it always was. */
  var cardHost = null, cardsKept = {};
  function decisionHost() {
    if (!cardHost && window.RouhDecision) {
      cardHost = window.RouhDecision.fetchHost({
        go: function (href) { if (host().go) { host().go(href); } },
        changed: function (d, what) { if (what !== 'get') { setTimeout(load, 1200); } }
      });
    }
    return cardHost;
  }

  function approval(a, open) {
    var d = open && H.data && H.data.decisions ? H.data.decisions[a.id] : null;
    if (d && window.RouhDecision && decisionHost()) {
      var wrap = el('div', 'hb-ask-card');
      var top = el('label', 'hb-check hb-ask-tick');
      var tick = el('input', 'hb-ask-box');
      tick.type = 'checkbox';
      tick.checked = !!H.picked[a.id];
      tick.setAttribute('aria-label', 'Select ' + (askNumber(a) || 'this approval'));
      tick.addEventListener('change', function () {
        if (tick.checked) H.picked[a.id] = true; else delete H.picked[a.id];
        draw();
      });
      top.appendChild(tick);
      top.appendChild(el('span', 'hb-num', 'Select'));
      wrap.appendChild(top);
      wrap.appendChild(window.RouhDecision.kept(cardsKept, d, decisionHost(), { place: 'page', here: '/settings/heartbeat' }));
      return wrap;
    }
    var box = el('div', 'hb-ask' + (open ? '' : ' answered'));
    var head = el('div', 'hb-ask-head');
    if (open) {
      var tick = el('input', 'hb-ask-box');
      tick.type = 'checkbox';
      tick.checked = !!H.picked[a.id];
      tick.setAttribute('aria-label', 'Select ' + (askNumber(a) || 'this approval'));
      tick.addEventListener('change', function () {
        if (tick.checked) H.picked[a.id] = true; else delete H.picked[a.id];
        draw();
      });
      head.appendChild(tick);
    }
    if (askNumber(a)) head.appendChild(el('span', 'hb-num', askNumber(a)));
    head.appendChild(el('span', 'hb-ask-what', a.what));
    if (!open) head.appendChild(el('span', 'hb-pill ' + a.state, a.state === 'failed' ? 'yes, failed' :
      a.state === 'rule' ? 'needed nobody\'s yes' : a.state));
    else if (a.blocking) head.appendChild(el('span', 'hb-pill blocking', 'blocking'));
    box.appendChild(head);
    var dl = el('dl', 'hb-ask-dl');
    var from = raisedBy(a.by);
    if (from) {
      dl.appendChild(el('dt', '', 'For'));
      var dd = el('dd', '');
      dd.appendChild(from);
      dl.appendChild(dd);
    }
    [['To', a.to_whom], ['Why', a.why], ['Cost', a.cost],
     ['Runs', a.tool ? a.tool : 'Nothing: a decision'], ['Asked', a.asked],
     ['Answered', a.answered ? a.answered + (a.on ? ' on ' + a.on : '') : ''],
     ['Result', a.result]].forEach(function (pair) {
      if (!pair[1]) return;
      dl.appendChild(el('dt', '', pair[0]));
      dl.appendChild(el('dd', '', pair[1]));
    });
    box.appendChild(dl);
    if (open) {
      var r = el('div', 'hb-ask-do');
      r.appendChild(button('Yes', 'primary', function () { answer(a, 'yes'); }, 'Run exactly this, and nothing else'));
      r.appendChild(button('No', '', function () { answer(a, 'no'); }, 'Do not do it'));
      r.appendChild(button('Delete', 'danger hb-ask-del', function () { deleteAsks(a); },
        'Take it off the list for good: neither a yes nor a no'));
      box.appendChild(r);
    }
    return box;
  }

  function answer(a, word) {
    H.said = '';
    call('POST', '/api/heartbeat/answer', { id: a.id, answer: word });
  }

  /* The silent notes beats left for Rouh's next conversation with Petar. Every beat itself is
     on the beats' own page (`beatspage.js`). */
  function notesCard(d) {
    var s = card('Notes it left you', String(d.state.notes.length), 'hb-notes', 'notes');
    var ul = el('ul', 'hb-events');
    d.state.notes.slice().reverse().forEach(function (n) {
      ul.appendChild(el('li', n.seen ? 'seen' : '', n.at + ' · ' + n.text + (n.seen ? '' : ' (not yet said)')));
    });
    s.appendChild(ul);
    return s;
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

  function shownNow() {
    if (H.open) return;
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
                          tell: function (text) { H.carried = String(text || ''); } };
})();
