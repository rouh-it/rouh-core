/* Anatomy, Behaviour, Permissions, at /anatomy/behaviour/permissions (`rouh/unrestricted.py`,
   `rouh/web/permissions.py`): the one place the mode is seen and switched.

   Petar, 20 November 2026 (task 191): "I want to see toggle for unrestricted mode." And on
   21 November 2026: "the restricted button should be removed from the top of the chat. it should
   remain in anatomy > behavior > permissions ... by default it should be unrestricted. I can pick
   restricted. or while restricted I can pick unrestricted options: time x, time z, time y or
   permanently." So while Unrestricted the card says so plainly, with what is left when it is timed,
   and has one press, Switch to Restricted; while Restricted it has a short row of presses, one per
   length (`offered_hours`) and Permanently, each switching at once. Under it, what still asks him
   in every mode, What Rouh did while it was on (each with Undo where the service allows), what the
   switch opens for his runs (the five rouh-open items, `rouh/run_access.py`), and every flip. Only
   his own press here changes it: the server refuses anything else. Nothing in the conversation's
   header shows or changes the mode. Drawn into `#permissionsBody` from `/api/permissions`;
   Anatomy says when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var ROUTE = '/anatomy/behaviour/permissions';
  /* data: the last answer. busy: a press waiting, pressing: which ("restricted", "permanent" or
     the hours). said: what the last press did. fail: the page could not be read. undoing: the row
     being undone. tick: the timer that keeps "left" true while the page is open. */
  var S = { open: false, data: null, seq: 0, busy: false, pressing: '', said: '',
            bad: '', fail: '', undoing: 0, undoSaid: {}, most: 100, tick: 0 };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  var SVG = 'http://www.w3.org/2000/svg';
  function icon(paths) {
    var s = document.createElementNS(SVG, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
    });
    return s;
  }
  var OPEN = ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 6.8-1.2'];
  var SHUT = ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'];
  var HAND = ['M12 3l8 4v5c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V7z', 'M12 8v5', 'M12 16h.01'];
  var BACK = ['M9 14 4 9l5-5', 'M4 9h10.5a5.5 5.5 0 0 1 0 11H11'];
  var KEY = ['M14 10a4 4 0 1 0-4 4', 'M13 13l7 7', 'M17 17l2-2'];
  var CHECK = ['M5 12.5l4.5 4.5L19 7.5'];
  var WAIT = ['M12 3a9 9 0 1 0 0.01 0', 'M12 7.5V12l3 2'];

  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  function call(method, path, body) {
    var seq = ++S.seq;
    var fetcher = window.RouhPermissionsFetch || fetch;
    return fetcher(path, {
      method: method, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: method === 'POST' ? JSON.stringify(body || {}) : undefined
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (method === 'GET' && seq !== S.seq) return null;
        if (j && j.mode) { S.data = j; S.fail = ''; }
        if (!r.ok && method === 'GET') S.fail = (j && j.error) || 'The server said ' + r.status + '.';
        return { ok: r.ok, body: j || {} };
      });
    }).catch(function () {
      if (method === 'GET') S.fail = 'Rouh could not be reached. Check the connection and try again.';
      return { ok: false, body: { error: 'Rouh could not be reached. Check the connection and try again.' } };
    });
  }

  function load() { return call('GET', '/api/permissions?most=' + S.most).then(function () { draw(); }); }

  /* ---- words ---- */

  function clockOf(at) {
    var d = new Date(at * 1000), now = new Date();
    var hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    if (d.toDateString() === now.toDateString()) return hm;
    var tomorrow = new Date(now.getTime() + 86400000);
    if (d.toDateString() === tomorrow.toDateString()) return 'tomorrow ' + hm;
    return hm + ' on ' + d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  }
  function when(at) {
    var d = new Date(at * 1000), now = new Date();
    var hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    if (d.toDateString() === now.toDateString()) return 'Today ' + hm;
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ', ' + hm;
  }
  function modeWords(m) {
    if (!m || m.mode !== 'unrestricted') return 'Restricted';
    if (m.how === 'permanent') return 'Unrestricted, permanently';
    if (m.how === 'until_back' || !m.until) return 'Unrestricted until you switch it back';
    return 'Unrestricted until ' + clockOf(m.until);
  }

  /* What is left of an Unrestricted of some hours: "3 h 59 min left", "12 min left". */
  function leftOf(at) {
    var mins = Math.max(0, Math.ceil((at - Date.now() / 1000) / 60));
    if (mins < 60) return (mins <= 1 ? 'Less than a minute' : mins + ' min') + ' left';
    var h = Math.floor(mins / 60), m = mins % 60;
    return h + ' h' + (m ? ' ' + m + ' min' : '') + ' left';
  }
  function timed(m) { return !!(m && m.mode === 'unrestricted' && m.how === 'hours' && m.until); }

  /* ---- pressing ---- */

  /* to: "restricted", "permanent", or a number of hours of Unrestricted. One press, no second step. */
  function press(to) {
    if (S.busy || !(S.data && S.data.can_change)) return;
    var body = to === 'restricted' ? { mode: 'restricted' }
      : to === 'permanent' ? { mode: 'unrestricted', how: 'permanent' }
      : { mode: 'unrestricted', how: 'hours', hours: to };
    S.busy = true; S.said = ''; S.bad = ''; S.pressing = String(to);
    draw();
    call('POST', '/api/permissions', body).then(function (got) {
      S.busy = false;
      if (got && got.ok) {
        S.said = to === 'restricted' ? 'Switched to Restricted. Rouh asks you again where it used to.'
          : 'Switched. ' + modeWords(got.body.mode) + '.';
      } else {
        S.bad = (got && got.body && got.body.error) || 'That could not be saved.';
      }
      draw();
      // The press is gone with the state it belonged to: focus goes to the card's heading, so the
      // next state is read out and no choice looks picked.
      var back = document.querySelector('#pmSwitchH');
      if (back) back.focus({ preventScroll: true });
    });
  }

  function undo(row) {
    if (S.undoing) return;
    S.undoing = row.id;
    draw();
    call('POST', '/api/permissions/undo', { id: row.id }).then(function (got) {
      S.undoing = 0;
      S.undoSaid[row.id] = got && got.ok ? { ok: true, text: 'Undone: ' + got.body.said }
        : { ok: false, text: (got && got.body && got.body.error) || 'It could not be undone.' };
      if (got && got.body && got.body.mode) S.data = got.body;
      draw();
    });
  }

  /* ---- drawing ---- */

  function headline(d) {
    var on = d.mode.mode === 'unrestricted';
    var p = el('p', 'pm-headline');
    var state = el('span', 'pm-state' + (on ? ' on' : ''));
    state.appendChild(icon(on ? OPEN : SHUT));
    state.appendChild(document.createTextNode(on ? 'Unrestricted' : 'Restricted'));
    p.appendChild(state);
    if (on && d.mode.how === 'permanent') {
      p.appendChild(el('strong', 'pm-for-good', 'Permanently, it never ends by itself. '));
    }
    var does = 'own chats and runs do what you ask without asking you first, except the three things below.';
    p.appendChild(document.createTextNode(on
      ? (d.mode.how === 'permanent' ? 'Your ' + does : (d.mode.how === 'until_back' || !d.mode.until
         ? 'Until you switch it back: ' : 'Until ' + clockOf(d.mode.until) + ': ') + 'your ' + does)
      : 'Your runs ask you before they send, change Cloudflare, deploy or run what nobody has classified.'));
    return p;
  }

  function hoursWords(x) { return x + (x === 1 ? ' hour' : ' hours'); }

  /* The card that switches: Unrestricted says what it is and offers Restricted; Restricted offers
     each length of Unrestricted as its own press. */
  function switchCard(d) {
    var m = d.mode, on = m.mode === 'unrestricted';
    var sec = el('section', 'hb-sec pm-switch' + (on ? ' on' : ''));
    sec.setAttribute('aria-labelledby', 'pmSwitchH');
    var h = el('h3', 'hb-h', on ? 'Change the mode' : 'Switch to Unrestricted');
    h.id = 'pmSwitchH';
    h.tabIndex = -1;
    sec.appendChild(h);
    if (on) {
      var now = el('p', 'pm-now');
      now.appendChild(el('strong', '', m.how === 'permanent' ? 'Unrestricted, permanently.'
        : timed(m) ? 'Unrestricted until ' + clockOf(m.until) + '.' : 'Unrestricted until you switch it back.'));
      if (timed(m)) {
        now.appendChild(document.createTextNode(' '));
        now.appendChild(el('span', 'pm-left', leftOf(m.until)));
        now.appendChild(document.createTextNode(', then it goes back to Restricted by itself.'));
      } else if (m.set_by === 'the default') {
        now.appendChild(document.createTextNode(' This is the default: nobody has switched it yet.'));
      } else {
        now.appendChild(document.createTextNode(' It stays this way until you switch to Restricted.'));
      }
      sec.appendChild(now);
    } else {
      sec.appendChild(el('p', 'pm-now', 'Pick how long. It switches as soon as you press.'));
    }
    if (!d.can_change) {
      sec.appendChild(el('p', 'pm-note', 'Only the owner of this Rouh can switch its mode, so this cannot be pressed here.'));
    }
    var row = el('div', 'pm-acts' + (on ? '' : ' pm-picks'));
    if (on) {
      var b = el('button', 'ctl pm-main primary', S.busy ? 'Saving…' : 'Switch to Restricted');
      b.type = 'button';
      b.disabled = !d.can_change || S.busy;
      b.addEventListener('click', function () { press('restricted'); });
      row.appendChild(b);
    } else {
      row.setAttribute('role', 'group');
      row.setAttribute('aria-label', 'Unrestricted for how long');
      var most = d.most_hours || 72;
      (d.offered_hours || [1, 4, 24]).filter(function (x) { return x <= most; }).forEach(function (x) {
        var hb = el('button', 'ctl pm-pick', S.busy && S.pressing === String(x) ? 'Saving…' : hoursWords(x));
        hb.type = 'button';
        hb.disabled = !d.can_change || S.busy;
        hb.setAttribute('aria-label', 'Unrestricted for ' + hoursWords(x));
        hb.addEventListener('click', function () { press(x); });
        row.appendChild(hb);
      });
      var pb = el('button', 'ctl pm-pick pm-for-ever', S.busy && S.pressing === 'permanent' ? 'Saving…' : 'Permanently');
      pb.type = 'button';
      pb.disabled = !d.can_change || S.busy;
      pb.setAttribute('aria-label', 'Unrestricted permanently');
      pb.addEventListener('click', function () { press('permanent'); });
      row.appendChild(pb);
    }
    sec.appendChild(row);
    if (S.said) sec.appendChild(el('p', 'pm-say good', S.said));
    if (S.bad) sec.appendChild(el('p', 'pm-say bad', S.bad));
    return sec;
  }

  function stillAsks(d) {
    var sec = el('section', 'hb-sec');
    sec.setAttribute('aria-labelledby', 'pmAsksH');
    var h = el('h3', 'hb-h', 'Still asks you, in every mode');
    h.id = 'pmAsksH';
    sec.appendChild(h);
    var ul = el('ul', 'pm-list');
    (d.still_asks || []).forEach(function (t) {
      var li = el('li');
      li.appendChild(icon(HAND));
      li.appendChild(el('span', '', t.charAt(0).toUpperCase() + t.slice(1) + '.'));
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    sec.appendChild(el('p', 'pm-note', 'Kept in both modes too: what an email or a page says is never taken as your word, secrets are masked, and runs a contact, a stranger’s mail or one of Rouh’s own processes started never get Unrestricted.'));
    return sec;
  }

  function didRow(r) {
    var li = el('li', 'pm-did');
    var top = el('div', 'pm-did-top');
    top.appendChild(el('span', 'pm-did-what', r.what || r.tool));
    top.appendChild(el('span', 'pm-did-when', when(r.at)));
    li.appendChild(top);
    var meta = (r.via === 'job' ? 'Run ' + (r.title ? r.title : r.where) : 'In your chat') + ', with ' + r.tool;
    li.appendChild(el('p', 'pm-did-meta', meta));
    if (r.why) li.appendChild(el('p', 'pm-did-why', r.why));
    var foot = el('div', 'pm-did-foot');
    var said = S.undoSaid[r.id];
    if (r.undone_at) {
      foot.appendChild(el('span', 'pm-did-undone', 'Undone ' + when(r.undone_at) + (r.undone_said ? ': ' + r.undone_said : '')));
    } else if (r.can_undo) {
      var b = el('button', 'ctl small pm-undo');
      b.type = 'button';
      b.appendChild(icon(BACK));
      b.appendChild(document.createTextNode(S.undoing === r.id ? 'Undoing…' : 'Undo'));
      b.disabled = !!S.undoing || !(S.data && S.data.can_change);
      b.setAttribute('aria-label', 'Undo: ' + (r.what || r.tool));
      b.addEventListener('click', function () { undo(r); });
      foot.appendChild(b);
    } else {
      foot.appendChild(el('span', 'pm-did-no', r.undo_said || 'No undo for this one.'));
    }
    // A failure is said beside the row; a success is the row's own "Undone ..." line.
    if (said && !said.ok) foot.appendChild(el('span', 'pm-say bad', said.text));
    li.appendChild(foot);
    return li;
  }

  function did(d) {
    var sec = el('section', 'hb-sec');
    sec.setAttribute('aria-labelledby', 'pmDidH');
    var rows = d.did || [];
    var total = Math.max(d.did_total || 0, rows.length);
    var h = el('h3', 'hb-h', 'What Rouh did');
    h.id = 'pmDidH';
    h.appendChild(el('span', 'hb-h-sub', !rows.length ? 'What ran without asking, newest first'
      : total > rows.length ? 'The latest ' + rows.length + ' of ' + total + ' actions that ran without asking, newest first'
      : total + (total === 1 ? ' action' : ' actions') + ' that ran without asking, newest first'));
    sec.appendChild(h);
    if (!rows.length) {
      var empty = el('div', 'pm-empty');
      empty.appendChild(icon(BACK));
      empty.appendChild(el('p', '', 'Nothing yet. Whatever runs because the mode is Unrestricted is listed here, with Undo wherever the service keeps what was there before: Cloudflare, Drive, your calendar, Gmail’s labels and bin, iCloud contacts and what Rouh posted in Slack.'));
      sec.appendChild(empty);
      return sec;
    }
    var ul = el('ul', 'pm-dids');
    rows.forEach(function (r) { ul.appendChild(didRow(r)); });
    sec.appendChild(ul);
    if (total > rows.length) {
      var more = el('button', 'ctl small pm-more', 'Show ' + Math.min(100, total - rows.length) + ' older');
      more.type = 'button';
      more.addEventListener('click', function () { S.most += 100; load(); });
      sec.appendChild(more);
    }
    return sec;
  }

  /* The hours to give rouh-open: what is left of an Unrestricted of some hours, else the hours
     picked, rounded up to whole hours from 1 to 72. */
  function hoursForOpen(d) {
    var m = d.mode || {};
    if (m.mode === 'unrestricted' && m.how === 'hours' && m.until) {
      return Math.min(72, Math.max(1, Math.ceil((m.until - Date.now() / 1000) / 3600)));
    }
    return 8;
  }

  function grants(d) {
    var sec = el('section', 'hb-sec');
    sec.setAttribute('aria-labelledby', 'pmGrantsH');
    var h = el('h3', 'hb-h', 'rouh-open: GitHub, the internet and your servers');
    h.id = 'pmGrantsH';
    sec.appendChild(h);
    var g = d.grants || [];
    if (g.length) {
      var ul = el('ul', 'pm-list');
      g.forEach(function (x) {
        var li = el('li');
        li.appendChild(icon(KEY));
        li.appendChild(el('span', '', x.what + ', open until ' + clockOf(x.until) + '.'));
        ul.appendChild(li);
      });
      sec.appendChild(ul);
    } else {
      sec.appendChild(el('p', 'pm-note', 'Nothing is open from your Mac right now.'));
    }
    var p = el('p', 'pm-note');
    var m = d.mode || {};
    var timed = !(m.mode === 'unrestricted' && m.how !== 'hours');
    p.appendChild(document.createTextNode('This switch does not open or close these. They are opened from your Mac with your own keys, which are never on this server, and each runs to its own end. '
      + (timed ? 'For the same hours, run ' : 'rouh-open lasts at most 72 hours at a time: run ')));
    p.appendChild(el('code', 'pm-code', 'rouh-open ' + (timed ? hoursForOpen(d) : 72)));
    p.appendChild(document.createTextNode(timed ? ' on your Mac.' : ' on your Mac, and again when it ends.'));
    sec.appendChild(p);
    return sec;
  }

  /* What the switch opens for the owner's runs: the five rouh-open items (`rouh/run_access.py`),
     each with what it does in Restricted and in Unrestricted, the mode in force marked "now",
     and whether its standing access is ready, said in words beside its sign. */
  function opens(d) {
    var on = (d.mode || {}).mode === 'unrestricted';
    var items = d.access || [];
    var sec = el('section', 'hb-sec');
    sec.setAttribute('aria-labelledby', 'pmOpensH');
    var h = el('h3', 'hb-h', 'What the switch opens for your runs');
    h.id = 'pmOpensH';
    var here = items.filter(function (x) { return x.applies !== false; });
    var ready = here.filter(function (x) { return x.ready; }).length;
    h.appendChild(el('span', 'hb-h-sub', ready === here.length ? 'All ' + here.length + ' ready'
      : ready + ' of ' + here.length + ' ready'));
    sec.appendChild(h);
    var ul = el('ul', 'pm-opens');
    items.forEach(function (x) {
      var li = el('li', 'pm-open');
      var top = el('div', 'pm-open-top');
      top.appendChild(el('span', 'pm-open-name', x.name || x.key));
      var na = x.applies === false;
      if (na) li.className += ' na';
      var tag = el('span', 'pm-ready' + (x.ready ? ' yes' : ''));
      if (!na) tag.appendChild(icon(x.ready ? CHECK : WAIT));
      tag.appendChild(document.createTextNode(na ? 'Not here' : x.ready
        ? (x.until ? 'Ready, until ' + clockOf(x.until) : 'Ready') : 'Not ready'));
      top.appendChild(tag);
      li.appendChild(top);
      var both = el('div', 'pm-open-modes');
      [['Restricted', x.restricted, !on], ['Unrestricted', x.unrestricted, on]].forEach(function (m) {
        var cell = el('p', 'pm-open-mode' + (m[2] ? ' now' : ''));
        cell.appendChild(el('span', 'pm-open-label', m[0] + (m[2] ? ', now' : '')));
        cell.appendChild(el('span', '', m[1] || ''));
        both.appendChild(cell);
      });
      li.appendChild(both);
      if (!x.ready && x.why) li.appendChild(el('p', 'pm-open-why', x.why));
      if (!x.ready && x.fix && x.fix.href) {
        var a = el('a', 'pm-open-fix', x.fix.label || 'Set it up');
        a.href = x.fix.href;
        li.appendChild(a);
      }
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    return sec;
  }

  function flips(d) {
    var det = el('details', 'pm-flips');
    var sum = el('summary', '', 'Every switch (' + (d.flips || []).length + ')');
    det.appendChild(sum);
    var body = el('div', 'pm-flips-body');
    if (!(d.flips || []).length) body.appendChild(el('p', 'pm-note', 'It has never been switched: Rouh has been Unrestricted, the default, all along.'));
    var ul = el('ul', 'pm-flip-list');
    (d.flips || []).forEach(function (f) {
      ul.appendChild(el('li', '', when(f.at) + ': ' + (f.now === 'unrestricted'
        ? 'Unrestricted' + (f.how === 'permanent' ? ', permanently' : f.how === 'until_back' ? ', until switched back' : f.until ? ' until ' + clockOf(f.until) : '')
        : 'Restricted') + ', by ' + (f.by || 'the owner')));
    });
    body.appendChild(ul);
    det.appendChild(body);
    return det;
  }

  function draw() {
    var body = $('permissionsBody');
    if (!body || !S.open) return;
    body.textContent = '';
    var page = el('div', 'hb-page pm-page');
    var d = S.data;
    if (!d) {
      if (S.fail) {
        var f = el('p', 'pm-fail', S.fail);
        var again = el('button', 'ctl small', 'Try again');
        again.type = 'button';
        again.addEventListener('click', function () { S.fail = ''; draw(); load(); });
        f.appendChild(again);
        page.appendChild(f);
      } else {
        page.appendChild(el('p', 'hb-empty', 'Reading the mode…'));
      }
      body.appendChild(page);
      body.setAttribute('aria-busy', S.fail ? 'false' : 'true');
      return;
    }
    body.setAttribute('aria-busy', 'false');
    if (S.fail) {
      // A later read that failed: what is shown may be old, and it says so.
      var stale = el('p', 'pm-fail', 'This may be out of date: ' + S.fail);
      var retry = el('button', 'ctl small', 'Try again');
      retry.type = 'button';
      retry.addEventListener('click', function () { S.fail = ''; load(); });
      stale.appendChild(retry);
      page.appendChild(stale);
    }
    page.appendChild(headline(d));
    var top = el('div', 'pm-top');
    top.appendChild(switchCard(d));
    top.appendChild(stillAsks(d));
    page.appendChild(top);
    page.appendChild(did(d));
    // What the switch opens; what rouh-open has open is shown only when that cannot be read.
    page.appendChild((d.access || []).length ? opens(d) : grants(d));
    page.appendChild(flips(d));
    body.appendChild(page);
  }

  window.RouhPermissions = {
    // A message is about the press that made it: never carried to the next visit.
    shown: function () {
      S.open = true; S.said = ''; S.bad = ''; S.undoSaid = {}; draw(); load();
      clearInterval(S.tick);
      S.tick = setInterval(tick, 20000);
    },
    hidden: function () { S.open = false; clearInterval(S.tick); S.tick = 0; },
    route: ROUTE
  };

  /* While the page is open: what is left is kept true, and when the hours end the mode is read
     again, so the card shows Restricted without anybody pressing anything. */
  function tick() {
    if (!S.open || document.hidden || !S.data) return;
    var m = S.data.mode;
    if (!timed(m)) return;
    if (m.until <= Date.now() / 1000) { load(); return; }
    Array.prototype.forEach.call(document.querySelectorAll('#permissionsBody .pm-left'), function (n) {
      n.textContent = leftOf(m.until);
    });
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden && S.open && S.data) { if (timed(S.data.mode) && S.data.mode.until <= Date.now() / 1000) load(); else tick(); } });
})();
