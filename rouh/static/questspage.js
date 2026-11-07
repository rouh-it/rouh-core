/* Quests: every one at /quests, and each at /quests/<its task's number>
   (`rouh/quests.py`, `rouh/web/quests.py`).

   Petar, 5 October 2026: long-running work becomes Quests, each a numbered
   task tagged Quest with its own chat, "and add a Quests page where he can
   manage them: add new ones, edit existing ones". So this draws two things in
   one layer.

   The list: every quest with its number, title, where it stands, its dates,
   its spend against its budget, income and net, what waits for his yes and
   its last and next beat, with Pause or Resume, Reset and Delete on each, and
   New quest, a form for a title, goal, rules, starting plan, dates, budget and
   card cap that makes the task and the record together.

   One quest: whether it is being worked on, its money against its budget, its
   task with its files and steps, its title, goal, rules, plan and notebook to
   read and change in place, its dates, budget, cap and carried switch, its
   ledger with a line to add what he paid or earned himself, the beats on it
   and what they asked him, and Reset and Delete.

   A delete asks what becomes of its task: archived with its files (the
   default), kept as a task, or deleted with its files and steps.

   The layer, its address and opening and closing it are app/runs.js's
   (`workOpen`), handed over through `window.RouhWorkHost`; `W.id` is the
   quest's number, or '' for the list. */
(function () {
  'use strict';

  var W = { open: false, id: '', data: null, list: null, busy: false, error: '', said: '', seq: 0,
            tick: 0, soon: 0, editing: '', making: false, asking: null };

  function host() { return window.RouhWorkHost || {}; }
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
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  /* What a quest's page may change with no connection: kept in this device's outbox and carried
     out through the same address once there is one (app/offline.js, `offline._clock`). Check now
     starts work now, and waits for a connection. */
  var OFFLINE_ACTS = ['pause', 'resume', 'set', 'brief'];
  function offline() { return !!(window.RouhOffline && !window.RouhOffline.online()); }
  function keepOffline(url, body, d) {
    var act = String((body || {}).act || '');
    var ledger = /\/ledger$/.test(url);
    if (!ledger && OFFLINE_ACTS.indexOf(act) < 0) {
      W.error = 'That needs a connection to Rouh: it starts work now. It is not kept for later.';
      draw();
      return Promise.resolve(null);
    }
    var name = d ? 'quest ' + d.work.number + ' “' + d.work.title + '”' : 'a quest';
    var label = ledger ? 'Add ' + (body.direction === 'in' ? 'money in' : 'money out') + ' to the ledger of ' + name
      + ': ' + (body.amount || '') + ' ' + (body.currency || '') + ' ' + (body.what || '')
      : { pause: 'Pause ' + name, resume: 'Resume ' + name, set: 'Change the budget and dates of ' + name,
          brief: 'Change the ' + (body.part || 'brief') + ' of ' + name }[act];
    var base = d ? { paused: !!d.work.paused } : {};
    return window.RouhOffline.queue('clock', { path: url, body: body || {}, label: label, zone: deviceZone() }, base)
      .then(function () {
        if (d && (act === 'pause' || act === 'resume')) {
          d.work.paused = act === 'pause';
          d.work.state = act === 'pause' ? 'paused' : 'on';
          d.work.why_not = act === 'pause' ? 'It is paused.' : '';
          (W.list || []).forEach(function (q) {
            if (String(q.number) !== String(d.work.number)) return;
            q.paused = d.work.paused;
            q.state = d.work.state;
          });
          // The device's copy says so too, so the page read again from it (every 20 seconds,
          // or opened again) shows what was done rather than what was.
          if (window.RouhOffline.prime) {
            if (W.data === d) window.RouhOffline.prime('/api/quests/' + encodeURIComponent(d.work.number), d);
            if (W.list) window.RouhOffline.prime('/api/quests', { quests: W.list });
          }
        }
        W.error = '';
        W.said = 'Kept on this device: it goes to Rouh when you are back online.';
        draw();
        return { ok: true, queued: true };
      });
  }

  function call(method, url, body) {
    if (method === 'POST' && offline() && /^\/api\/quests\/\d+\/(act|ledger)$/.test(url)) {
      return keepOffline(url, body, W.data && W.data.work ? W.data : null);
    }
    var seq = ++W.seq;
    var forId = W.id;
    if (method === 'POST') W.busy = true;
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') W.busy = false;
          if (forId !== W.id || (seq !== W.seq && method === 'GET')) return j;
          if (j && j.work) W.data = j;
          if (j && j.quests) W.list = j.quests;
          if (r.ok) {
            W.error = '';
            if (j && j.said) W.said = j.said;
          } else {
            W.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') W.busy = false;
        W.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
        return null;
      });
  }

  var cardHost = null, cardsKept = {};
  function decisionHost() {
    if (!cardHost && window.RouhDecision) {
      cardHost = window.RouhDecision.fetchHost({
        go: function (href) { if (host().go) { host().go(href); } },
        changed: function (one, what) { if (what !== 'get') { setTimeout(load, 1200); } }
      });
    }
    return cardHost;
  }

  function base() { return '/api/quests/' + encodeURIComponent(W.id); }
  function load() { return call('GET', W.id ? base() : '/api/quests'); }
  function act(what, more) {
    W.said = '';
    W.editing = '';
    var body = { act: what };
    for (var k in (more || {})) body[k] = more[k];
    return call('POST', base() + '/act', body);
  }
  /* The same, for a quest on the list rather than the one open. */
  function actOn(number, what, more) {
    var body = { act: what };
    for (var k in (more || {})) body[k] = more[k];
    if (offline()) {
      var q = (W.list || []).filter(function (x) { return String(x.number) === String(number); })[0];
      // Named and kept as the quest on the list, not the one open.
      var one = q ? { work: { number: q.number, title: q.title, paused: !!q.paused } } : null;
      return keepOffline('/api/quests/' + encodeURIComponent(number) + '/act', body, one).then(function (got) {
        if (got && q && (what === 'pause' || what === 'resume')) {
          q.paused = what === 'pause';
          q.state = what === 'pause' ? 'paused' : 'on';
        }
        draw();
      });
    }
    W.said = '';
    W.busy = true;
    return fetch('/api/quests/' + encodeURIComponent(number) + '/act', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(), 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        W.busy = false;
        if (r.ok) { W.error = ''; W.said = (j && j.said) || ''; } else {
          W.error = (j && j.error) || 'The server said ' + r.status + '.';
        }
        return load();
      });
    }).catch(function () {
      W.busy = false;
      W.error = 'Rouh could not be reached. Check the connection and try again.';
      draw();
    });
  }

  /* ---- the sidebar's row: how many are being worked on now ---- */

  function hint() {
    var h = $('questsHint');
    if (!h) return;
    var on = (W.list || []).filter(function (q) { return q.state === 'on'; }).length;
    h.textContent = on ? String(on) : '';
  }
  function listLoad() {
    // Only a count in the navigation hangs on it until the page is opened, so it is asked in the
    // lane kept for work nobody is waiting on (`rouh.dbwork.later`).
    return fetch('/api/quests', { credentials: 'same-origin', cache: 'no-store',
                                  headers: W.open ? {} : { 'X-Rouh-Later': '1' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.quests) return;
        W.list = j.quests;
        hint();
        if (W.open && !W.id && !W.editing && !W.making && !W.asking) draw();
      })
      .catch(function () {});
  }

  /* ---- drawing ---- */

  /** @param {boolean} [whole] drawn again even under a form being filled in */
  function draw(whole) {
    var body = $('workBody');
    if (!body) return;
    var d = W.id && W.data && String(W.data.work.number) === W.id ? W.data : null;
    paintHead(d);
    hint();
    if (!whole && (W.editing || W.making) && (d || !W.id)) {
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = W.error || W.said;
        say.className = 'hb-say' + (W.error ? ' bad' : '');
        say.hidden = !(W.error || W.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (W.error ? ' bad' : ''), W.error || W.said);
    say2.setAttribute('role', 'status');
    say2.hidden = !(W.error || W.said);
    page.appendChild(say2);
    if (!W.id) { drawList(page); return; }
    if (!d) {
      if (!W.error) page.appendChild(el('p', 'hb-empty', 'Reading it…'));
      return;
    }
    // A check queued or running is followed closely, so its end shows without a reload.
    clearTimeout(W.soon);
    if (d.next && d.next.live) W.soon = setTimeout(function () { if (W.open && !W.busy) load(); }, 3000);
    page.appendChild(nextCard(d));
    page.appendChild(nowCard(d));
    page.appendChild(taskCard(d));
    if (d.delegates && (d.delegates.deciders.length || d.delegates.acts.length)) {
      page.appendChild(delegatesCard(d.delegates));
    }
    page.appendChild(briefCard(d));
    page.appendChild(setCard(d));
    page.appendChild(ledgerCard(d));
    page.appendChild(beatsCard(d));
    page.appendChild(manageCard(d));
  }

  function paintHead(d) {
    var title = $('workTitle'), meta = $('workMeta'), pause = $('workPause');
    var back = $('questsBack'), add = $('questsNew');
    var one = !!W.id;
    if (title) title.textContent = one ? (d ? d.work.number + ' · ' + d.work.title : 'Quest ' + W.id) : 'Quests';
    if (one && d && host().titled) host().titled(d.work.title);
    if (meta) {
      meta.textContent = one ? (!d ? '' : [d.work.why_not ? d.work.why_not.replace(/\.$/, '') : 'Being worked on',
                                           d.work.period].filter(Boolean).join(' · '))
        : 'The long-running work the heartbeat carries, each a task of its own';
    }
    if (back) back.hidden = !one;
    if (add) { add.hidden = one; add.disabled = W.making; }
    if (pause) {
      pause.hidden = !one;
      pause.textContent = d && d.work.paused ? 'Resume' : 'Pause';
      pause.disabled = !d || W.busy;
      pause.title = d && d.work.paused ? 'Let the heartbeat work on it again' :
        'No beat works on it until you resume it';
    }
  }

  function card(title, sub, cls) {
    var s = el('section', 'hb-sec' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  function stat(label, value, cls) {
    var box = el('div', 'hb-stat' + (cls ? ' ' + cls : ''));
    box.appendChild(el('div', 'hb-stat-v', value));
    box.appendChild(el('div', 'hb-stat-l', label));
    return box;
  }

  function link(text, href, cls) {
    var a = el('a', cls || 'hb-link', text);
    a.href = href;
    a.addEventListener('click', function (e) {
      e.preventDefault();
      if (host().go) host().go(href);
    });
    return a;
  }

  var STATE_WORDS = { on: 'On', paused: 'Paused', ended: 'Ended', 'not carried': 'Not carried',
                      'not started': 'Not started' };

  /* ---- the list ---- */

  function drawList(page) {
    if (W.making) { page.appendChild(newCard()); }
    if (W.asking) { page.appendChild(deleteCard(W.asking)); }
    if (!W.list) {
      if (!W.error) page.appendChild(el('p', 'hb-empty', 'Reading them…'));
      return;
    }
    if (!W.list.length && !W.making) {
      var none = card('No quests yet', '', 'q-none');
      none.appendChild(el('p', 'hb-empty', 'A quest is long-running work the heartbeat carries by itself: a goal, ' +
        'rules, a budget and dates, worked on in beats of its own. Press New quest, or ask Rouh to start one.'));
      page.appendChild(none);
      return;
    }
    W.list.forEach(function (q) { page.appendChild(questRow(q)); });
  }

  function questRow(q) {
    var s = el('section', 'hb-sec q-row q-' + q.state.replace(/\s+/g, '-'));
    s.dataset.quest = String(q.number);
    var h = el('h4', 'hb-h q-head');
    h.appendChild(el('span', 'q-num', String(q.number)));
    h.appendChild(link(q.title, q.href, 'q-title'));
    h.appendChild(el('span', 'hb-pill q-state ' + q.state.replace(/\s+/g, '-'), STATE_WORDS[q.state] || q.state));
    s.appendChild(h);
    var dates = q.end ? q.start + ' to ' + q.end : (q.start ? 'Since ' + q.start + ', no end' : 'No dates');
    s.appendChild(el('p', 'hb-note q-dates', dates + (q.why_not && q.state !== 'on' ? ' · ' + q.why_not.replace(/\.$/, '') : '')));
    var stats = el('div', 'hb-stats q-stats');
    stats.appendChild(stat(q.budget ? 'Spent of ' + q.budget : 'Spent, no budget', q.spent, q.over ? 'out over' : 'out'));
    stats.appendChild(stat('Income', q.income, 'in'));
    stats.appendChild(stat('Net', q.net, q.net_down ? 'out' : 'in'));
    stats.appendChild(stat('Waiting for your yes', String(q.approvals), q.approvals ? 'ask' : ''));
    s.appendChild(stats);
    var beats = el('p', 'hb-note q-beats');
    beats.textContent = 'Last beat ' + (q.last_beat || 'not yet') + ' · Next beat ' +
      (q.next_beat || (q.state !== 'on' ? 'none while ' + (STATE_WORDS[q.state] || q.state).toLowerCase() :
        q.heartbeat_paused ? 'none while the heartbeat is paused' : 'when the heartbeat next looks'));
    s.appendChild(beats);
    var acts = el('div', 'hb-actions q-acts');
    var open = button('Open', 'primary', function () { if (host().open) host().open(String(q.number)); }, 'Its own page');
    acts.appendChild(open);
    acts.appendChild(button(q.paused ? 'Resume' : 'Pause', '', function () {
      actOn(q.number, q.paused ? 'resume' : 'pause');
    }, q.paused ? 'Let the heartbeat work on it again' : 'No beat works on it until you resume it'));
    acts.appendChild(button('Reset', '', function () { resetQuest(q, q.tally, function () { load(); }); },
      'Start it again from beat 1, keeping its goal and rules'));
    acts.appendChild(button('Delete', 'danger', function () {
      W.asking = { number: q.number, title: q.title, tally: q.tally, from: 'list' };
      draw();
      var b = document.querySelector('.q-confirm');
      if (b) b.scrollIntoView({ block: 'nearest' });
    }, 'Delete it, and say what becomes of its task'));
    s.appendChild(acts);
    return s;
  }

  /* ---- New quest ---- */

  function textField(text, id, value, rows, hintText) {
    var label = el('label', 'hb-field wide q-area');
    label.appendChild(el('span', '', text));
    var area = el('textarea');
    area.id = id;
    area.rows = rows;
    area.maxLength = 8000;
    area.value = value || '';
    if (hintText) area.placeholder = hintText;
    label.appendChild(area);
    return { label: label, input: area };
  }

  function newCard() {
    var s = card('New quest', 'a numbered task of its own, with its chat and its money', 'q-new');
    var f = el('form', 'hb-form q-form');
    f.setAttribute('aria-label', 'New quest');
    var title = field('Title', 'text', '', 'questTitle', 'wide');
    title.input.required = true;
    title.input.maxLength = 200;
    title.input.placeholder = 'Such as: Can Rouh earn more than it spends?';
    f.appendChild(title.label);
    var goal = textField('Goal', 'questGoal', '', 3, 'What it is for, and what counts as done');
    var rules = textField('Rules', 'questRules', '', 3, 'What every beat must keep to');
    var plan = textField('Starting plan', 'questPlan', '', 3, 'The first steps; the beats keep it current');
    [goal, rules, plan].forEach(function (x) { f.appendChild(x.label); });
    var r = el('div', 'hb-row');
    var start = field('Starts', 'date', today(), 'questStart');
    var end = field('Last day', 'date', '', 'questEnd');
    r.appendChild(start.label); r.appendChild(end.label);
    f.appendChild(r);
    var r2 = el('div', 'hb-row');
    var budget = field('Budget ($)', 'number', '', 'questBudget');
    budget.input.min = '0'; budget.input.step = '1'; budget.input.placeholder = 'None';
    var cap = field('Most a card purchase ($)', 'number', '50', 'questCap');
    cap.input.min = '0'; cap.input.step = '1';
    r2.appendChild(budget.label); r2.appendChild(cap.label);
    f.appendChild(r2);
    var carry = el('label', 'hb-check');
    var box = el('input');
    box.type = 'checkbox';
    box.id = 'questCarried';
    box.checked = true;
    carry.appendChild(box);
    carry.appendChild(el('span', '', 'The heartbeat carries it, starting now'));
    f.appendChild(carry);
    f.appendChild(el('p', 'settings-help', 'No end date means it goes on until you end it. The budget counts its model and ' +
      'tool spend and its card charges; with none, nothing stops it but the heartbeat’s daily cap.'));
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Make the quest');
    save.type = 'submit';
    acts.appendChild(save);
    acts.appendChild(button('Cancel', '', function () { W.making = false; W.error = ''; draw(); }));
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      save.disabled = true;
      W.said = '';
      call('POST', '/api/quests', {
        title: title.input.value, goal: goal.input.value, rules: rules.input.value, plan: plan.input.value,
        start: start.input.value, end: end.input.value, budget: budget.input.value, spend_cap: cap.input.value,
        carried: box.checked
      }).then(function (j) {
        save.disabled = false;
        if (!j || !j.quest) return;
        W.making = false;
        listLoad();
        var said = j.said || '';
        if (host().open) host().open(String(j.quest));
        W.said = said;
        draw();
      });
    });
    s.appendChild(f);
    setTimeout(function () { title.input.focus(); }, 0);
    return s;
  }

  /* ---- one quest ---- */

  function nowCard(d) {
    var w = d.work;
    var s = card('Where it stands', w.period, 'hb-now');
    var st = el('p', 'hb-state ' + (w.why_not || w.heartbeat_paused ? 'paused' : 'on'));
    st.appendChild(el('span', 'hb-pulse'));
    st.appendChild(document.createTextNode(w.why_not ? w.why_not : w.heartbeat_paused ?
      'The heartbeat itself is paused, so no beat works on it until the heartbeat is resumed.' :
      'The heartbeat works on it, in its own chat. What happens next is above.'));
    s.appendChild(st);
    s.appendChild(el('p', 'hb-note', 'Last full beat on it ' + (w.last_beat || 'not yet') + '.' +
      (w.due ? ' It set its own next beat for ' + w.due.replace(/\.$/, '') + '.' : '')));
    var money = el('div', 'hb-stats');
    money.appendChild(stat('In', d.money['in'], 'in'));
    money.appendChild(stat('Out', d.money.out, 'out'));
    money.appendChild(stat('Net', d.money.net, d.money.net.charAt(0) === '-' ? 'out' : 'in'));
    money.appendChild(stat(Number(w.budget) ? 'Left of ' + d.money.budget : 'No budget', Number(w.budget) ? d.money.left : '-'));
    s.appendChild(money);
    s.appendChild(el('p', 'hb-note', 'Out counts ' + d.money.models + ' of model and tool spend on it and ' +
      d.money.paid + ' from its ledger, ' + d.money.cards + ' of that by card. At most $' + w.spend_cap +
      ' a card purchase, under the Payments caps.'));
    var links = el('div', 'hb-links');
    if (w.chat) links.appendChild(link('Open its chat', '/chat/' + encodeURIComponent(w.chat)));
    else links.appendChild(el('span', 'hb-link q-nochat', 'Its chat is made at its first beat.'));
    if (w.earlier_chat) links.appendChild(link('Its earlier beats, in the Heartbeat chat', '/chat/' + encodeURIComponent(w.earlier_chat)));
    links.appendChild(link('Its beats, as a table', '/anatomy/behaviour/beats/' + w.number));
    links.appendChild(link('The heartbeat, today', '/anatomy/behaviour/heartbeat'));
    s.appendChild(links);
    return s;
  }

  /* What happens next, and Check now (`rouh/questcheck.py`): the same state the goal map
     draws on the quest's steps, never the notebook's words. Petar, 6 October 2026: "has
     to be on hte goals map. but also on the quest I guess. and I have to have an option to
     'heartbeat' once, no?" */
  function factRow(dl, label, value) {
    dl.appendChild(el('dt', '', label));
    var dd = el('dd');
    if (typeof value === 'string') dd.textContent = value; else if (value) dd.appendChild(value);
    dl.appendChild(dd);
    return dd;
  }

  function nextCard(d) {
    var q = d.next || {};
    var s = card('What happens next', q.label || '', 'q-next x-' + (q.state || 'waiting'));
    s.id = 'questNext';
    var dl = el('dl', 'q-facts');
    factRow(dl, 'Who does it', q.executor);
    if (q.live) factRow(dl, 'Now', q.live.words);
    if (q.last_full) {
      var lw = el('span');
      lw.appendChild(document.createTextNode(q.last_full.full_when + ': ' + q.last_full.words));
      if (q.last_full.outdated) lw.appendChild(el('strong', 'q-outdated', q.last_full.outdated));
      factRow(dl, 'Last check', lw);
    } else {
      factRow(dl, 'Last check', 'None yet.');
    }
    if (q.last && (!q.last_full || q.last.id !== q.last_full.id)) {
      factRow(dl, 'Last look', q.last.full_when + ': ' + q.last.words);
    }
    if ((q.steps || []).length) {
      var ul = el('ul', 'q-gsteps');
      q.steps.forEach(function (one) {
        var li = el('li', one.blocked_by ? 'blocked' : one.news ? 'news' : 'ready');
        var words = 'Step ' + one.n + ' “' + one.title + '”: ';
        if (one.blocked_by) {
          words += 'blocked on step ' + one.blocked_by.n + ' “' + one.blocked_by.title + '”'
            + (one.blocked_by.label ? ' (' + one.blocked_by.label.toLowerCase() + ')' : '') + '.';
        } else if (one.after) {
          words += 'ready since step ' + one.after.n + ' “' + one.after.title + '” was completed'
            + (one.after.when ? ' ' + one.after.when : '') + ' by ' + one.after.by + '.'
            + (one.news ? ' That came after its last check.' : '');
        } else {
          words += 'ready.';
        }
        li.appendChild(el('span', '', words + ' '));
        var go = link('Open it on the goal map', one.href, 'hb-link q-goal-link');
        li.appendChild(go);
        ul.appendChild(li);
      });
      factRow(dl, 'Its goal steps', ul);
    }
    var reasons = (q.held || []).concat(q.waits || []);
    if (reasons.length) {
      var why = el('ul', 'q-why');
      reasons.forEach(function (r) { why.appendChild(el('li', 'k-' + r.key, r.words)); });
      factRow(dl, 'Why it waits', why);
    }
    if (q.next && q.next.when) {
      var nx = el('span');
      nx.appendChild(el('strong', '', q.next.soon ? 'Any moment now' : q.next.when));
      if (!q.next.soon) nx.appendChild(document.createTextNode(' ' + q.zone + ' time, in ' + q.next.in + ', at the earliest.'));
      nx.appendChild(el('span', 'q-small', q.next.words));
      factRow(dl, 'Next automatic check', nx);
    } else {
      factRow(dl, 'Next automatic check', 'None: ' + (((q.held || [])[0] || {}).words || 'nothing would wake it.'));
    }
    s.appendChild(dl);
    s.appendChild(checkBox(q));
    return s;
  }

  function checkBox(q) {
    var c = q.check || {};
    var wrap = el('div', 'q-check');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Check the quest now');
    var once = null;
    if (c.needs_yes) {
      var lab = el('label', 'hb-check q-once');
      once = el('input');
      once.type = 'checkbox';
      once.id = 'questCheckOnce';
      lab.appendChild(once);
      lab.appendChild(el('span', '', c.yes_words));
      wrap.appendChild(lab);
    }
    var row = el('div', 'q-check-row');
    var go = button(q.live ? (q.live.status === 'running' ? 'Checking…' : 'Check queued') : 'Check now',
      'primary', function () {
        go.disabled = true;
        act('now', { while_paused: !!(once && once.checked), where: 'quest' });
      });
    go.id = 'questCheckNow';
    go.disabled = W.busy || !c.can || !!(once && !once.checked);
    if (once) once.addEventListener('change', function () { go.disabled = W.busy || !once.checked; });
    row.appendChild(go);
    row.appendChild(el('span', 'q-check-help', c.help || ''));
    wrap.appendChild(row);
    if (c.refused) wrap.appendChild(el('p', 'hb-note q-check-no', 'Check now is not available: ' + c.refused));
    return wrap;
  }

  var STEP_WORDS = { done: 'Done', waiting: 'Waiting', 'in-progress': 'Under way', 'not-started': 'Not started' };

  function taskCard(d) {
    var w = d.work;
    var s = card('Its task', w.task_folder ? 'task ' + w.number : 'not found', 'q-task');
    if (!w.task_folder) {
      s.appendChild(el('p', 'hb-empty', 'Its task is not in the workspace on this machine, so its goal, rules, plan and ' +
        'notebook are read from its record.'));
      return s;
    }
    s.appendChild(el('p', 'hb-note q-folder', 'Its goal, rules, plan and notebook are files in it: ' +
      Object.keys(w.task_files).map(function (k) { return w.task_files[k]; }).join(', ') + '.'));
    var open = link('Open task ' + w.number, '/task/' + w.task_folder.split('/').map(encodeURIComponent).join('/'));
    open.id = 'questTaskLink';
    s.appendChild(open);
    if (w.steps && w.steps.length) {
      s.appendChild(el('h5', 'hb-h5', 'Its steps'));
      var ul = el('ul', 'q-steps');
      w.steps.forEach(function (st) {
        var li = el('li', 'q-step ' + st.status);
        li.appendChild(el('span', 'q-step-num', st.number));
        li.appendChild(el('span', 'q-step-title', st.title));
        li.appendChild(el('span', 'hb-pill', STEP_WORDS[st.status] || st.status));
        ul.appendChild(li);
      });
      s.appendChild(ul);
    }
    return s;
  }

  /* Who decides for this quest by Petar's grant, and what they did on it, with their
     own words (`rouh/delegation.py`). Undo and revoke are on their Trusted contacts page. */
  function delegatesCard(g) {
    var s = card('Who decides', g.deciders.length ? g.deciders.join(', ') : '', 'q-delegates');
    if (g.deciders.length) {
      s.appendChild(el('p', 'hb-note', g.deciders.join(' and ') + ' decides for this quest by your grant: its ' +
        'decisions, its brief, pausing it and asking for a beat. Money, deleting, publishing, sending and ' +
        'commitments stay yours.'));
    }
    var ul = el('ul', 'hb-events q-delegate-acts');
    g.acts.forEach(function (a) {
      var li = el('li', a.outcome === 'done' ? 'seen' : 'waiting');
      li.appendChild(document.createTextNode((a.outcome === 'for_owner' || a.outcome === 'for_petar' ? 'Held for you: ' : a.outcome === 'undone' ? 'Undone: ' :
        'Decided by ' + a.name + ': ') + (a.said || a.why)));
      if (a.words) { li.appendChild(el('span', 'q-delegate-words', ' \u201c' + a.words + '\u201d')); }
      ul.appendChild(li);
    });
    if (ul.childNodes.length) { s.appendChild(ul); }
    return s;
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

  function holds(f, name) {
    f.addEventListener('input', function () { W.editing = name; });
    f.addEventListener('change', function () { W.editing = name; });
  }

  function setCard(d) {
    var w = d.work;
    var s = card('Budget and dates', '', 'hb-set-card');
    var f = el('form', 'hb-form');
    f.setAttribute('aria-label', 'Budget and dates');
    holds(f, 'set');
    var r = el('div', 'hb-row');
    var budget = field('Budget ($)', 'number', w.budget, 'workBudget');
    budget.input.min = '0'; budget.input.step = '1';
    var cap = field('Most a card purchase ($)', 'number', w.spend_cap, 'workCap');
    cap.input.min = '0'; cap.input.step = '1';
    r.appendChild(budget.label); r.appendChild(cap.label);
    var r2 = el('div', 'hb-row');
    var start = field('Starts', 'date', w.start, 'workStart');
    var end = field('Last day', 'date', w.end, 'workEnd');
    r2.appendChild(start.label); r2.appendChild(end.label);
    f.appendChild(r);
    f.appendChild(r2);
    var carry = el('label', 'hb-check');
    var box = el('input');
    box.type = 'checkbox';
    box.id = 'workCarried';
    box.checked = !!w.carried;
    carry.appendChild(box);
    carry.appendChild(el('span', '', 'The heartbeat carries it'));
    f.appendChild(carry);
    f.appendChild(el('p', 'settings-help', 'The budget counts its model and tool spend and its card charges. A beat is skipped ' +
      'once it is spent, or outside its dates. An empty last day means no end.'));
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save');
    save.type = 'submit';
    acts.appendChild(save);
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      act('set', { budget: budget.input.value, spend_cap: cap.input.value, start: start.input.value,
                   end: end.input.value || 'none', carried: box.checked });
    });
    s.appendChild(f);
    return s;
  }

  var BY = { owner: 'You', petar: 'You', heartbeat: 'Heartbeat', card: 'Card', stripe: 'Stripe' };

  function ledgerCard(d) {
    var s = card('Ledger', d.money.net + ' net', 'hb-ledger');
    if (!d.ledger.length) {
      s.appendChild(el('p', 'hb-empty', 'No money in or out yet, besides its model and tool spend (' + d.money.models + ').'));
    } else {
      var table = el('table', 'hb-table');
      var head = el('tr');
      ['When', 'What', 'By', 'Amount'].forEach(function (h) { head.appendChild(el('th', '', h)); });
      var thead = el('thead');
      thead.appendChild(head);
      table.appendChild(thead);
      var tbody = el('tbody');
      d.ledger.forEach(function (e) {
        var tr = el('tr', e.direction);
        tr.appendChild(el('td', 'hb-when', e.when));
        tr.appendChild(el('td', '', e.what));
        tr.appendChild(el('td', 'hb-by', BY[e.by] || e.by));
        tr.appendChild(el('td', 'hb-amt', (e.direction === 'in' ? '+' : '−') + e.amount + ' ' + e.currency));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      s.appendChild(table);
    }
    var form = el('form', 'hb-set hb-add');
    form.setAttribute('aria-label', 'Add to the ledger');
    holds(form, 'ledger');
    var dir = el('select');
    dir.id = 'workDir';
    [['out', 'Paid out'], ['in', 'Came in']].forEach(function (p) {
      var o = el('option', '', p[1]); o.value = p[0]; dir.appendChild(o);
    });
    var dl = el('label', 'hb-field');
    dl.appendChild(el('span', '', 'Money'));
    dl.appendChild(dir);
    var amt = field('Amount', 'number', '', 'workAmount');
    amt.input.step = '0.01'; amt.input.min = '0.01'; amt.input.required = true;
    var cur = field('Currency', 'text', 'USD', 'workCurrency');
    cur.input.maxLength = 8;
    var what = field('What for', 'text', '', 'workWhat', 'wide');
    what.input.required = true; what.input.maxLength = 300;
    [dl, amt.label, cur.label, what.label].forEach(function (n) { form.appendChild(n); });
    var add = el('button', 'ctl small', 'Add');
    add.type = 'submit';
    form.appendChild(add);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      W.editing = '';
      W.said = '';
      call('POST', base() + '/ledger',
           { direction: dir.value, amount: amt.input.value, currency: cur.input.value, what: what.input.value });
    });
    s.appendChild(form);
    return s;
  }

  function briefCard(d) {
    var s = card('The standing brief', 'what every beat on it works from', 'hb-brief');
    [['title', 'Title', 'Its task’s name too'], ['goal', 'Goal', 'Yours'], ['rules', 'Rules', 'Yours'],
     ['plan', 'Plan', 'The heartbeat keeps it'], ['notebook', 'Notebook', 'The heartbeat keeps it']]
      .forEach(function (part) {
        var det = el('details', 'hb-part');
        det.dataset.part = part[0];
        det.open = true;
        var sum = el('summary', '', part[1]);
        sum.appendChild(el('span', 'hb-h-sub', part[2]));
        det.appendChild(sum);
        var text = el('div', 'hb-text', d.work[part[0]] || '(empty)');
        det.appendChild(text);
        var edit = button('Edit', 'hb-edit', function () {
          W.editing = 'brief-' + part[0];
          var f = el('form', 'hb-form hb-brief-form');
          f.setAttribute('aria-label', 'Edit the ' + part[1].toLowerCase());
          var area;
          if (part[0] === 'title') {
            area = el('input');
            area.type = 'text';
            area.maxLength = 200;
            area.className = 'q-title-input';
            area.value = d.work.title || '';
          } else {
            area = el('textarea');
            area.value = d.work[part[0]] || '';
            area.rows = Math.min(18, Math.max(4, (area.value.match(/\n/g) || []).length + 2));
            area.maxLength = 8000;
          }
          area.setAttribute('aria-label', part[1]);
          f.appendChild(area);
          var acts = el('div', 'hb-actions');
          var save = el('button', 'ctl small primary', 'Save');
          save.type = 'submit';
          acts.appendChild(save);
          acts.appendChild(button('Cancel', '', function () { W.editing = ''; draw(); }));
          f.appendChild(acts);
          f.addEventListener('submit', function (e) {
            e.preventDefault();
            act('brief', { part: part[0], text: area.value }).then(function () { listLoad(); });
          });
          text.replaceWith(f);
          edit.remove();
          area.focus();
        }, 'Change the ' + part[1].toLowerCase());
        det.appendChild(edit);
        s.appendChild(det);
      });
    return s;
  }

  var TRIGGER = { timer: 'Timer', event: 'Event', due: 'Its own time', now: 'Asked now', answer: 'Your answer' };

  function beatsCard(d) {
    var done = d.beats.filter(function (b) { return b.status !== 'skipped'; });
    var s = card('Beats on it', String(done.length), 'hb-beats');
    if (!done.length) s.appendChild(el('p', 'hb-empty', 'None yet.'));
    var list = el('ol', 'hb-list');
    done.slice(0, 15).forEach(function (b) {
      var li = el('li', 'hb-beat ' + b.status);
      var top = el('div', 'hb-beat-top');
      top.appendChild(el('span', 'hb-when', b.when));
      top.appendChild(el('span', 'hb-pill', TRIGGER[b.trigger] || b.trigger));
      top.appendChild(el('span', 'hb-beat-what', b.status === 'running' ? 'Running…' : b.status === 'failed' ? 'Failed' :
        ({ nothing: 'Ended with nothing', note: 'Left a note', telegram: 'Sent you a Telegram' }[b.outcome] || 'Done')));
      if (b.cost) top.appendChild(el('span', 'hb-beat-nums', b.cost));
      li.appendChild(top);
      if (b.reason) li.appendChild(el('p', 'hb-beat-reason', b.reason));
      if (b.said) li.appendChild(el('p', 'hb-beat-said', b.said));
      list.appendChild(li);
    });
    s.appendChild(list);
    s.appendChild(link('Every beat on it, as a table', '/anatomy/behaviour/beats/' + d.work.number));
    if (d.approvals.length) {
      s.appendChild(el('h5', 'hb-h5', 'What it asked you'));
      // What waits is a decision, drawn and answered the one way every question is
      // (`decision.js`); what was answered is a line each.
      var drawn = 0;
      d.approvals.forEach(function (a) {
        var one = a.state === 'waiting' && d.decisions ? d.decisions[a.id] : null;
        if (!one || !window.RouhDecision) { return; }
        s.appendChild(window.RouhDecision.kept(cardsKept, one, decisionHost(), { place: 'context' }));
        drawn += 1;
      });
      var ul = el('ul', 'hb-events q-asks');
      d.approvals.forEach(function (a) {
        if (a.state === 'waiting' && d.decisions && d.decisions[a.id] && window.RouhDecision) { return; }
        ul.appendChild(el('li', a.state === 'waiting' ? 'waiting' : 'seen',
          (a.decision ? 'Decision ' + a.decision + ' ' : '') + a.what + ' · ' + (a.state === 'rule' ? 'needed nobody\'s yes' : a.state) +
          ' · ' + a.when));
      });
      if (ul.childNodes.length) { s.appendChild(ul); }
      if (!drawn && d.approvals.some(function (a) { return a.state === 'waiting'; })) {
        s.appendChild(link('Answer on the Decisions page', '/decisions'));
      }
    }
    return s;
  }

  /* Start it again from beat 1, or delete it, once Petar has read what goes with it
     (`quests.reset`, `quests.remove`). The words are the Heartbeat page's own. */
  function manageCard(d) {
    var s = card('Start again or delete', '', 'hb-manage');
    if (W.asking) {
      s.appendChild(deleteCard(W.asking));
      return s;
    }
    s.appendChild(el('p', 'hb-note', 'A reset keeps its goal, rules, dates and budget and clears everything its beats ' +
      'did, so it starts again from beat 1. Deleting it takes it away with everything that is only its, and asks ' +
      'what becomes of its task. Neither touches runs it started.'));
    var acts = el('div', 'hb-actions');
    var reset = button('Reset', '', function () {
      resetQuest({ number: d.work.number, title: d.work.title }, d.tally, function () { load(); });
    }, 'Start it again from beat 1, keeping its goal and rules');
    reset.id = 'workReset';
    acts.appendChild(reset);
    var del = button('Delete', 'danger', function () {
      W.asking = { number: d.work.number, title: d.work.title, tally: d.tally, from: 'page' };
      draw();
      var b = document.querySelector('.q-confirm');
      if (b) b.scrollIntoView({ block: 'nearest' });
    }, 'Delete it, and say what becomes of its task');
    del.id = 'workDelete';
    acts.appendChild(del);
    s.appendChild(acts);
    return s;
  }

  function words(q, t, what) {
    var fn = window.RouhHeartbeat && window.RouhHeartbeat.clearWords;
    var name = 'quest ' + q.number + ' “' + q.title + '”';
    return fn ? fn(name, t, what) : (what === 'reset' ? 'Reset ' + name + '?' : 'Delete ' + name + '?');
  }

  function resetQuest(q, t, done) {
    if (!window.confirm(words(q, t, 'reset'))) return;
    actOn(q.number, 'reset').then(function () { listLoad(); if (done) done(); });
  }

  /* The delete, asked in place: what goes, and what becomes of its task. Archived with
     its files is the default, because it can be brought back from the task browser. */
  function deleteCard(q) {
    var box = el('div', 'q-confirm');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-label', 'Delete quest ' + q.number);
    var text = words(q, q.tally || { beats: 0, notebook: 0, ledger: 0, approvals: 0 }, 'delete').split('\n\n');
    box.appendChild(el('p', 'q-confirm-q', text[0]));
    if (text[1]) box.appendChild(el('p', 'hb-note', text[1]));
    var fs = el('fieldset', 'q-fate');
    fs.appendChild(el('legend', '', 'And its task ' + q.number + ', with its files and steps:'));
    [['archive', 'Archive it, keeping its files', 'Out of the lists; it can be brought back from the task browser’s Archive.'],
     ['keep', 'Keep it as a task, with its files', 'It stays where it is, no longer a quest.'],
     ['delete', 'Delete it with its files and steps', 'Gone from the workspace. This cannot be undone.']]
      .forEach(function (o, i) {
        var lab = el('label', 'q-fate-opt');
        var r = el('input');
        r.type = 'radio';
        r.name = 'questFate';
        r.value = o[0];
        r.checked = i === 0;
        lab.appendChild(r);
        var t = el('span', '');
        t.appendChild(el('strong', '', o[1]));
        t.appendChild(el('span', 'hb-note', o[2]));
        lab.appendChild(t);
        fs.appendChild(lab);
      });
    box.appendChild(fs);
    var acts = el('div', 'hb-actions');
    var go = button('Delete quest ' + q.number, 'danger', function () {
      var picked = box.querySelector('input[name="questFate"]:checked');
      var fate = picked ? picked.value : 'archive';
      go.disabled = true;
      var number = q.number;
      W.asking = null;
      var body = { act: 'delete', task: fate };
      fetch('/api/quests/' + encodeURIComponent(number) + '/act', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(), 'X-CSRFToken': csrfToken() },
        body: JSON.stringify(body)
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (r.ok) { W.error = ''; W.said = j.said || ''; } else { W.error = j.error || 'The server said ' + r.status + '.'; }
          if (q.done) { q.done(j); return; }
          if (r.ok && W.id) { W.data = null; if (host().open) host().open(''); }
          listLoad();
          load();
        });
      }).catch(function () {
        W.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
    }, 'Delete it, as chosen above');
    go.id = 'questDeleteGo';
    acts.appendChild(go);
    acts.appendChild(button('Cancel', '', function () {
      W.asking = null;
      if (q.cancel) q.cancel(); else draw();
    }));
    box.appendChild(acts);
    return box;
  }

  /* ---- the layer ---- */

  function shownNow(id) {
    var moved = W.id !== String(id || '');
    W.id = String(id || '');
    W.open = true;
    if (moved) { W.data = null; W.editing = ''; W.asking = null; W.making = false; W.error = ''; }
    if (moved && W.id) W.said = W.said || '';
    draw();
    load();
    clearInterval(W.tick);
    W.tick = setInterval(function () { if (W.open && !W.busy && !W.editing && !W.making && !W.asking) load(); }, 20000);
  }

  function hiddenNow() {
    W.open = false;
    W.editing = '';
    W.making = false;
    W.asking = null;
    W.said = '';
    clearInterval(W.tick);
  }

  (function wire() {
    var close = $('workClose'), pause = $('workPause');
    var back = $('questsBack'), add = $('questsNew');
    if (close) close.addEventListener('click', function () { if (host().close) host().close(); });
    if (back) back.addEventListener('click', function () { W.said = ''; if (host().open) host().open(''); });
    // The form is drawn once, then held: nothing read meanwhile redraws under it.
    if (add) add.addEventListener('click', function () {
      W.making = true;
      W.said = '';
      W.error = '';
      W.asking = null;
      W.editing = '';
      draw(true);
    });
    if (pause) pause.addEventListener('click', function () {
      act(W.data && W.data.work.paused ? 'resume' : 'pause').then(function () { listLoad(); });
    });
    // The count, once the conversation the page is opening is on the screen (index.html).
    window.rouhLater(listLoad);
  })();

  /* What the Heartbeat page uses to ask a delete the same way: the same box, put where
     it asks, and `done` when it has been answered. */
  function askDelete(q, place, done, cancel) {
    place.textContent = '';
    place.appendChild(deleteCard({ number: q.number, title: q.title, tally: q.tally, done: done, cancel: cancel }));
  }

  window.RouhWork = { shown: shownNow, hidden: hiddenNow, reload: load, rows: listLoad };
  window.RouhQuests = { askDelete: askDelete, reload: listLoad };
})();
