/* Meta, Changes, at /anatomy/meta/changes (`rouh/codechanges.py`, `rouh/web/changes.py`).

   Task 98, step 98-23: in a container a Rouh has a protected core beside it, which checks every
   change of the Rouh's own code before it goes live, keeps an undo point for each, and puts the
   code back by itself (the doctor) when Rouh stops answering right after a change. This page is
   where the person sees it: the code that runs, every undo point with Put back, what is waiting
   for a newer core, and what the doctor last did. Nothing here changes the person's data.

   Drawn into `#changesBody` from `/api/settings/changes`; Settings tells it when it shows and
   when it is left (`settingsPages` in app/runs.js).

   Its first card is Rouh's updates (task 140, step 140-18, `rouh/code_update.py`, from
   `/api/settings/updates`): how this Rouh takes new releases of Rouh (Ride along, Update when I
   press, My own path), the version it has and the newest, what is new, the button that updates it
   now, and how the last update went. */
(function () {
  'use strict';

  var C = { open: false, data: null, busy: false, error: '', said: '', confirm: 0, timer: 0 };
  /* Rouh's updates: their own answer, apart from the protected core's, so either can be slow. */
  var U = { data: null, busy: false, error: '', said: '', loaded: false };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    b.addEventListener('click', act);
    return b;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function when(at) {
    if (!at) return '';
    var d = new Date(at * 1000);
    return d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
  function short(c) { return String(c || '').slice(0, 12); }

  function call(method, url, body) {
    if (method === 'POST') { C.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') C.busy = false;
          if (j && (j.guard !== undefined)) C.data = j;
          if (!r.ok) C.error = (j && j.error) || 'That did not work. Try again.';
          else if (method === 'POST') { C.error = ''; C.said = (j && j.said) || ''; }
          draw();
          return j;
        });
      })
      .catch(function () { C.busy = false; C.error = 'Rouh could not be reached.'; draw(); });
  }
  function load() { loadUpdates(false); return call('GET', '/api/settings/changes'); }

  function updatesCall(method, url, body) {
    if (method === 'POST') { U.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          U.busy = false;
          U.loaded = true;
          if (j && j.mode) U.data = j;
          if (!r.ok) U.error = (j && j.error) || 'That did not work. Try again.';
          else if (method === 'POST') { U.error = ''; U.said = (j && j.said) || ''; }
          draw();
          return j;
        });
      })
      .catch(function () { U.busy = false; U.loaded = true; U.error = 'Rouh could not be reached.'; draw(); });
  }
  function loadUpdates(look) {
    if (look) { U.said = ''; U.error = ''; }
    return updatesCall('GET', '/api/settings/updates' + (look ? '?look=1' : '')).then(function (j) {
      if (look && j && j.mode && !U.error) { U.said = j.check_error ? '' : 'Asked rouh.land just now.'; draw(); }
      return j;
    });
  }

  function card(title, sub) {
    var s = el('section', 'setting-card hb-card');
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  function drawState(page, d) {
    var notes = [];
    if (d.busy) notes.push(['ch-busy', 'The protected core is ' + d.busy + '…']);
    if (d.code && d.code.clean === false) {
      notes.push(['ch-warn', 'There is work in the code that is not committed. It does not run; ' +
        'at the next start it is kept on a branch of its own.']);
    }
    notes.forEach(function (n) { page.appendChild(el('p', n[0], n[1])); });
  }

  function drawDoctor(page, d) {
    var n = d.notice;
    var cur = (d.code && d.code.point) || null;
    if (!n || !cur || cur.n !== n.point) return;
    var s = card('The doctor put the code back');
    s.classList.add('ch-doctor');
    s.appendChild(el('p', '', n.said || ''));
    if (n.from && d.admin) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Put the change back', '', function () { undo(n.from); }));
      s.appendChild(acts);
    }
    page.appendChild(s);
  }

  function drawWaiting(page, d) {
    if (!d.pending || !d.pending.length) return;
    var s = card('Waiting for a Rouh update');
    var ul = el('ul', 'hb-list ch-list');
    d.pending.forEach(function (p) {
      var li = el('li', 'hb-beat ch-row');
      li.appendChild(el('div', 'ch-why', p.why || short(p.commit)));
      var needs = Object.keys(p.needs || {}).map(function (g) { return g + ' needs ' + p.needs[g]; });
      li.appendChild(el('div', 'ch-sub', needs.join(' · ') + ' · this core is ' + (d.version || '?')));
      ul.appendChild(li);
    });
    s.appendChild(ul);
    page.appendChild(s);
  }

  var MODE_LINES = {
    ride: 'Takes each new release by itself, at a quiet moment, at most once a day.',
    press: 'Nothing comes in until you press Update to the newest Rouh.',
    own: 'Never looks for releases by itself. You can still press the button.'
  };

  function updatesHeadline(d) {
    if (d.makes_releases) return 'This Rouh makes Rouh’s releases.';
    if (d.busy) return 'Updating Rouh…';
    if (d.pending) return 'Checking the update before it goes live…';
    if (!d.newest) return d.on_its_own ? 'This Rouh is on its own, so it does not look for releases by itself.'
      : 'The newest release of Rouh is not known yet.';
    if (d.up_to_date) return 'This Rouh is up to date.';
    return 'A newer Rouh is ready.';
  }

  function drawUpdates(page) {
    var d = U.data;
    var s = card('Rouh’s updates');
    s.classList.add('cu-card');
    s.setAttribute('aria-busy', U.busy ? 'true' : 'false');
    if (!d) {
      s.appendChild(el('p', 'hb-empty', U.error || (U.loaded ? 'Not known yet.' : 'Looking…')));
      page.appendChild(s);
      return;
    }
    var lead = el('p', 'cu-lead' + (d.newest && !d.up_to_date && !d.makes_releases ? ' new' : ''), updatesHeadline(d));
    lead.setAttribute('role', 'status');
    s.appendChild(lead);

    var dl = el('dl', 'hb-ask-dl ch-dl cu-dl');
    var rows = [];
    if (d.current && d.current.label) {
      rows.push(['You have', d.current.label + (d.current.own_commits
        ? ', with ' + d.current.own_commits + ' change' + (d.current.own_commits === 1 ? '' : 's') + ' of its own' : '')]);
    }
    if (d.newest) rows.push(['Newest', d.newest.label]);
    if (d.makes_releases && d.publishing) rows.push(['Releases', d.publishing.said || 'None published from here yet.']);
    rows.forEach(function (row) { dl.appendChild(el('dt', '', row[0])); dl.appendChild(el('dd', '', row[1])); });
    if (rows.length) s.appendChild(dl);

    if (d.whats_new && d.whats_new.length && !d.up_to_date) {
      s.appendChild(el('p', 'cu-sub-h', 'What is new'));
      var ul = el('ul', 'cu-new');
      d.whats_new.forEach(function (line) { ul.appendChild(el('li', '', line)); });
      s.appendChild(ul);
    }

    var say = U.busy ? 'Working…' : (U.error || U.said);
    if (d.busy && d.busy.step) say = 'Updating: ' + d.busy.step + '…';
    if (say) s.appendChild(el('p', 'hb-say' + (U.error ? ' bad' : ''), say));

    var acts = el('div', 'hb-actions cu-actions');
    if (d.admin && !d.makes_releases) {
      var can = !d.why_not && !U.busy;
      var go = button('Update to the newest Rouh', 'primary', function () {
        updatesCall('POST', '/api/settings/updates/now', {}).then(function () {
          window.setTimeout(function () { loadUpdates(false); }, 5000);
        });
      });
      go.disabled = !can;
      if (!can && d.why_not && !(d.up_to_date)) go.setAttribute('aria-describedby', 'cuWhyNot');
      if (d.newest && !d.up_to_date) acts.appendChild(go);
    }
    var look = button(d.on_its_own ? 'Look for a newer Rouh' : 'Look again', '', function () {
      U.busy = true; draw();
      loadUpdates(true);
    });
    acts.appendChild(look);
    s.appendChild(acts);
    if (d.newest && d.why_not && !d.up_to_date && !d.makes_releases && !d.busy && !d.pending) {
      var why = el('p', 'cu-why', d.why_not);
      why.id = 'cuWhyNot';
      s.appendChild(why);
    }
    if (d.check_error && !d.newest) s.appendChild(el('p', 'cu-why', d.check_error));

    var box = el('fieldset', 'cu-modes');
    box.appendChild(el('legend', 'cu-sub-h', 'How new releases come'));
    Object.keys(d.modes || {}).forEach(function (k) {
      var lab = el('label', 'cu-mode' + (d.mode === k ? ' on' : ''));
      var r = el('input');
      r.type = 'radio'; r.name = 'cuMode'; r.value = k; r.checked = d.mode === k;
      r.disabled = !d.admin || U.busy;
      r.addEventListener('change', function () {
        if (r.checked) updatesCall('POST', '/api/settings/updates/mode', { mode: k });
      });
      var text = el('span', 'cu-mode-text');
      text.appendChild(el('span', 'cu-mode-name', d.modes[k] + (k === 'ride' ? ' (the default)' : '')));
      text.appendChild(el('span', 'cu-mode-line', MODE_LINES[k] || ''));
      lab.appendChild(r);
      lab.appendChild(text);
      box.appendChild(lab);
    });
    if (d.on_its_own && d.mode === 'ride') {
      box.appendChild(el('p', 'cu-why', 'This Rouh is on its own, so it never rides along: it asks rouh.land only when you press a button here.'));
    }
    if (!d.admin) box.appendChild(el('p', 'cu-why', 'Only an administrator of this Rouh changes how its code is updated.'));
    s.appendChild(box);

    var last = d.last;
    if (last) {
      var lp = el('p', 'cu-last' + (last.ok ? '' : ' bad'));
      lp.appendChild(el('span', 'cu-last-h', 'Last update, ' + when(last.at) + ': '));
      lp.appendChild(document.createTextNode(lastLine(last)));
      s.appendChild(lp);
    }
    s.appendChild(el('p', 'settings-help', 'Only Rouh’s code changes. Your rules, memory, mail, people and ' +
      'settings stay as they are, and your own changes are kept on top. Each update is checked first and ' +
      'becomes an undo point below.'));
    page.appendChild(s);
  }

  function lastLine(last) {
    if (!last.ok) return 'did not update to ' + (last.label || 'the newest release') + ': ' + (last.said || '');
    var t = 'updated to ' + (last.label || 'the newest release') + '.';
    (last.kept || []).forEach(function (k) {
      var who = (k.genes || ['a change of its own']).join(' and ');
      t += ' ' + who.charAt(0).toUpperCase() + who.slice(1) + ' stayed as it was in ' + k.file + '.';
    });
    return t;
  }

  function drawPoints(page, d) {
    var s = card('Undo points');
    if (!d.points || !d.points.length) {
      s.appendChild(el('p', 'hb-empty', 'None yet.'));
      page.appendChild(s);
      return;
    }
    var ol = el('ol', 'hb-list ch-list');
    d.points.forEach(function (p) {
      var li = el('li', 'hb-beat ch-row' + (p.current ? ' current' : ''));
      var top = el('div', 'ch-top');
      top.appendChild(el('span', 'ch-n', String(p.n)));
      top.appendChild(el('span', 'ch-why', p.why || 'no description'));
      if (p.current) top.appendChild(el('span', 'hb-pill ch-pill', 'Runs now'));
      li.appendChild(top);
      var sub = [short(p.commit), when(p.at), p.by || '',
                 p.checked ? p.checked.passed + ' checks passed' : ''];
      if (p.doctored) sub.push('put back by the doctor');
      li.appendChild(el('div', 'ch-sub', sub.filter(Boolean).join(' · ')));
      if (!p.current && d.admin) {
        var acts = el('div', 'hb-actions');
        if (C.confirm === p.n) {
          acts.appendChild(el('span', 'ch-ask', 'Put the code back to this point? Your data stays as it is.'));
          acts.appendChild(button('Put back', 'primary', function () { undo(p.n); }));
          acts.appendChild(button('Cancel', '', function () { C.confirm = 0; draw(); }));
        } else {
          acts.appendChild(button('Put back to this', '', function () { C.confirm = p.n; draw(); }));
        }
        li.appendChild(acts);
      }
      ol.appendChild(li);
    });
    s.appendChild(ol);
    page.appendChild(s);
  }

  function drawCore(page, d) {
    var s = card('The protected core', d.version ? 'rouh-guard ' + d.version : '');
    s.appendChild(el('p', 'settings-help', 'The parts of Rouh that its own changes cannot reach: the key ' +
      'proxy, the checks every change must pass, and the doctor. Only signed releases update them.'));
    var doc = d.doctor || {};
    var dl = el('dl', 'hb-ask-dl ch-dl');
    var health = doc.failing_since ? 'not answering since ' + when(doc.failing_since)
      : (doc.last_ok ? 'answering' : 'not looked at yet');
    [['Rouh', health],
     ['The doctor', 'goes back after ' + (doc.patience_minutes || 5) + ' minutes without an answer, within ' +
       (doc.window_minutes || 30) + ' minutes of a change'],
     ['Contracts', Object.keys(d.contracts || {}).map(function (k) { return k + ' ' + d.contracts[k].join(', '); }).join(' · ')]
    ].forEach(function (row) { dl.appendChild(el('dt', '', row[0])); dl.appendChild(el('dd', '', row[1])); });
    s.appendChild(dl);
    page.appendChild(s);
  }

  function draw() {
    var body = $('changesBody');
    if (!body || !C.open) return;
    body.setAttribute('aria-busy', C.busy ? 'true' : 'false');
    body.textContent = '';
    var page = el('div', 'hb-page ch-page');
    var say = C.busy ? 'Working…' : (C.error || C.said);
    if (say) page.appendChild(el('p', 'hb-say' + (C.error ? ' bad' : ''), say));
    var d = C.data;
    if (!d) {
      if (!C.error) page.appendChild(el('p', 'hb-empty', 'Asking the protected core…'));
    } else if (!d.guard || d.answering === false) {
      drawUpdates(page);
      var s = card('Changes');
      s.appendChild(el('p', 'settings-help', d.said || ''));
      page.appendChild(s);
    } else {
      drawDoctor(page, d);
      drawState(page, d);
      drawUpdates(page);
      drawWaiting(page, d);
      drawPoints(page, d);
      drawCore(page, d);
    }
    body.appendChild(page);
  }

  function undo(n) {
    C.confirm = 0;
    call('POST', '/api/settings/changes/undo', { point: n }).then(function () {
      // Rouh starts again on the code put back; read the page again once it answers.
      window.setTimeout(load, 8000);
    });
  }

  function shownNow() {
    if (C.open) return;
    C.open = true;
    C.error = '';
    C.said = '';
    C.confirm = 0;
    draw();
    load();
    window.clearInterval(C.timer);
    C.timer = window.setInterval(function () { if (C.open && !C.busy) load(); }, 15000);
  }

  function hiddenNow() {
    C.open = false;
    window.clearInterval(C.timer);
  }

  window.RouhChanges = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
