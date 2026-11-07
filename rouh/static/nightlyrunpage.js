/* The nightly feature run's own page in Evolution, at `/evolution/nightly` (`rouh/web/nightly_run.py`).

   Petar, 3 November 2026: the nightly run was a row on Clockwork; it is a feature of its own now, beside
   the Incubator, which its ideas are read from and written to: its schedule and its switch, its nights
   and what each did, and its settings, its caps and the lessons in its task's feedback.md.
   `window.RouhNightlyRun` is what `evolutionpage.js` mounts. */
(function () {
  'use strict';

  var API = '/api/evolution/nightly';
  var S = { root: null, data: null, error: '', said: '', host: null, busy: false };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text, title) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) { b.title = title; }
    return b;
  }
  function call(body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    if (body) { init.method = 'POST'; init.headers = { 'Content-Type': 'application/json' }; init.body = JSON.stringify(body); }
    return fetch(API, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that just now.'); }
        return j;
      });
    });
  }
  function go(href) { if (S.host && S.host.go) { S.host.go(href); } else { location.href = href; } }
  function when(t) { return t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''; }

  function load() {
    return call(null).then(function (j) { S.data = j; S.error = ''; draw(); },
                           function (e) { S.error = String((e && e.message) || e); draw(); });
  }
  function change(body) {
    S.busy = true; draw();
    call(body).then(function (j) { S.data = j; S.busy = false; S.said = j.said || 'Saved.'; draw(); },
                    function (e) { S.busy = false; S.error = String((e && e.message) || e); draw(); });
  }

  function section(title) {
    var s = el('section', 'evo-part nr-part');
    s.appendChild(el('h4', 'evo-part-h', title));
    return s;
  }

  function draw() {
    var root = S.root;
    if (!root || !root.isConnected) { return; }
    root.textContent = '';
    root.appendChild(el('p', 'evo-lede', 'Each night Rouh researches, picks and builds the genes Parameters asks for, from the ideas in the Incubator, and puts each on trial in Mutations.'));
    if (S.error) { root.appendChild(el('p', 'evo-error', S.error)); }
    if (S.said) { root.appendChild(el('p', 'evo-said', S.said)); }
    var d = S.data;
    if (!d) { root.appendChild(el('p', 'evo-loading', 'Reading the nightly run…')); return; }
    // Its schedule and its switch.
    var sch = section('When it runs');
    var row = d.schedule;
    if (!row) {
      sch.appendChild(el('p', 'evo-lede', 'It has no task in this workspace yet, so it is not scheduled.'));
    } else {
      var line = el('div', 'nr-row');
      var sw = el('label', 'nr-switch');
      var box = el('input');
      box.type = 'checkbox';
      box.checked = row.state === 'on';
      box.disabled = S.busy;
      box.setAttribute('role', 'switch');
      box.addEventListener('change', function () { change({ on: box.checked }); });
      sw.appendChild(box);
      sw.appendChild(el('span', '', row.state === 'on' ? 'On' : 'Paused'));
      line.appendChild(sw);
      var at = el('input', 'nr-time');
      at.type = 'time';
      at.value = row.at_time || d.caps.at;
      at.setAttribute('aria-label', 'Its time each night');
      at.disabled = S.busy;
      at.addEventListener('change', function () { if (at.value) { change({ at: at.value }); } });
      line.appendChild(el('span', 'nr-dim', 'every night at'));
      line.appendChild(at);
      sch.appendChild(line);
      sch.appendChild(el('p', 'nr-dim', row.state === 'on' ? ('Next: ' + (row.when || row.day + ' ' + row.time) + '.') : 'Paused: no night starts until it is on again.'));
      if (row.last_said) { sch.appendChild(el('p', 'nr-dim', 'Last night: ' + row.last_said)); }
      var now = button('ctl small', 'Start a night now', 'Start tonight’s night at once');
      now.disabled = S.busy;
      now.addEventListener('click', function () {
        if (window.confirm('Start a night of the nightly run now? It builds and lands genes, within its caps.')) { change({ start: true }); }
      });
      sch.appendChild(now);
    }
    root.appendChild(sch);
    // Its settings.
    var set = section('Its rules');
    var ul = el('ul', 'nr-list');
    ul.appendChild(el('li', '', 'Pays at most ' + d.caps.dollars + ' dollars a night with the card, in all.'));
    ul.appendChild(el('li', '', 'Signs up for at most ' + d.caps.services + ' services a night, with Rouh’s own address.'));
    ul.appendChild(el('li', '', 'May sign up and pay only in the first ' + d.caps.hours + ' hours after it starts.'));
    ul.appendChild(el('li', '', 'Picks its ideas from the Incubator only, and writes the ideas its research finds there, marked as from the nightly run.'));
    if (d.ideas.rule) {
      ul.appendChild(el('li', '', d.ideas.rule + ' ' + (d.ideas.pickable === 1 ? '1 idea can be picked now.' : d.ideas.pickable + ' ideas can be picked now.')));
    }
    set.appendChild(ul);
    var links = el('p', 'nr-row');
    var params = el('a', 'evo-link', 'How many genes a night: Parameters');
    params.href = '/evolution/parameters';
    params.addEventListener('click', function (e) { e.preventDefault(); go('/evolution/parameters'); });
    links.appendChild(params);
    var inc = el('a', 'evo-link', 'Its ideas in the Incubator (' + d.ideas.all + ', ' + d.ideas['new'] + ' new)');
    inc.href = '/evolution/incubator';
    inc.addEventListener('click', function (e) { e.preventDefault(); go('/evolution/incubator'); });
    links.appendChild(inc);
    if (d.task) {
      var t = el('a', 'evo-link', 'Its task');
      t.href = '/task/' + d.task;
      t.addEventListener('click', function (e) { e.preventDefault(); go('/task/' + d.task); });
      links.appendChild(t);
    }
    set.appendChild(links);
    if (d.lessons) {
      var ls = el('details', 'inc-sec');
      ls.appendChild(el('summary', '', 'What it has learned (feedback.md)'));
      var body = el('div', 'inc-text');
      var md = S.host && S.host.markdown;
      var html = md ? md(d.lessons) : null;
      if (typeof html === 'string') { body.innerHTML = html; } else { body.textContent = d.lessons; }
      ls.appendChild(body);
      set.appendChild(ls);
    }
    root.appendChild(set);
    // Its nights.
    var ns = section('Its nights · ' + d.nights.length);
    if (!d.nights.length) { ns.appendChild(el('p', 'evo-lede', 'No night has run yet.')); }
    else {
      var scroll = el('div', 'inc-scroll nr-scroll');
      var table = el('table', 'inc-table nr-table');
      var hr = el('tr');
      ['Night', 'Started', 'State', 'What it built', 'Your answer'].forEach(function (h) { var th = el('th', 'inc-th', h); th.setAttribute('scope', 'col'); hr.appendChild(th); });
      var th = el('thead'); th.appendChild(hr); table.appendChild(th);
      var tb = el('tbody');
      d.nights.forEach(function (n) {
        var tr = el('tr', 'inc-tr');
        tr.appendChild(el('td', 'inc-td', n.number));
        tr.appendChild(el('td', 'inc-td', when(n.started_at)));
        var st = el('td', 'inc-td');
        st.appendChild(el('span', 'inc-chip inc-tone-' + ({ running: 'amber', done: 'green', failed: 'rose', short: 'slate' }[n.state] || 'none'), n.state + (n.run_state ? ' (' + n.run_state + ')' : '')));
        if (n.why) { st.title = n.why; }
        tr.appendChild(st);
        var what = el('td', 'inc-td nr-what', n.feature || n.built || n.why || '–');
        what.title = n.report || n.built || '';
        if (n.run_id) {
          var a = el('a', 'evo-link', 'run');
          a.href = '/run/' + n.run_id;
          a.addEventListener('click', function (e) { e.preventDefault(); go('/run/' + n.run_id); });
          what.appendChild(document.createTextNode(' '));
          what.appendChild(a);
        }
        tr.appendChild(what);
        tr.appendChild(el('td', 'inc-td', n.verdict ? n.verdict + (n.words ? ': ' + n.words : '') : '–'));
        tb.appendChild(tr);
      });
      table.appendChild(tb);
      scroll.appendChild(table);
      ns.appendChild(scroll);
    }
    root.appendChild(ns);
  }

  window.RouhNightlyRun = {
    mount: function (wrap, host) {
      S.host = host || null;
      S.root = el('div', 'nr');
      wrap.appendChild(S.root);
      draw();
      load();
    }
  };
}());
