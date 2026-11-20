/* Anatomy, Behaviour, Permissions, at /anatomy/behaviour/permissions (`rouh/unrestricted.py`,
   `rouh/web/permissions.py`), and the mode chip in the conversation's top row.

   Petar, 20 November 2026 (task 191): "I want to see toggle for unrestricted mode." One switch,
   Restricted or Unrestricted, for what his own chats and runs may do without asking; for some hours,
   until he switches it back, or permanently. Under it, what still asks him in every mode, What Rouh
   did while it was on (each with Undo where the service allows), what rouh-open has open, and every
   flip. Only his own press here changes it: the server refuses anything else.

   The chip: "Restricted" quietly, or Unrestricted in the warning colour with its end ("Unrestricted
   until 18:30"); pressing it opens this page. It reads the mode on load, every minute, when the page comes back
   into view, and after every flip. Drawn into `#permissionsBody` from `/api/permissions`; Anatomy
   says when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var ROUTE = '/anatomy/behaviour/permissions';
  /* data: the last answer. hours: the hours picked. how: the length picked. busy: a press waiting.
     said: what the last press did. fail: the page could not be read. undoing: the row being undone. */
  var S = { open: false, data: null, seq: 0, hours: 4, how: 'hours', busy: false, said: '', bad: '',
            fail: '', undoing: 0, undoSaid: {}, most: 100 };
  /* The length last picked, kept on this device so the next switch is the chip and one press. */
  var KEEP = 'rouh.permissions.length';
  try {
    var kept = JSON.parse(localStorage.getItem(KEEP) || 'null');
    if (kept && ['hours', 'until_back', 'permanent'].indexOf(kept.how) >= 0) {
      S.how = kept.how;
      if (kept.hours > 0 && kept.hours <= 72) S.hours = kept.hours;
    }
  } catch (err) {}
  function keepLength() {
    try { localStorage.setItem(KEEP, JSON.stringify({ how: S.how, hours: S.hours })); } catch (err) {}
  }

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
        if (j && j.mode) { S.data = j; S.fail = ''; chip(j.mode); }
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

  /* ---- the chip in the conversation's top row ---- */

  /* The end, short enough for the chip, with its day whenever it is not today. */
  function chipWhen(at) {
    var d = new Date(at * 1000), now = new Date();
    var hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    if (d.toDateString() === now.toDateString()) return hm;
    if (d.toDateString() === new Date(now.getTime() + 86400000).toDateString()) return 'tomorrow ' + hm;
    return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + hm;
  }

  function chip(m) {
    var c = $('modeChip');
    if (!c) return;
    var on = !!(m && m.mode === 'unrestricted');
    c.hidden = false;
    c.classList.toggle('on', on);
    c.classList.toggle('for-good', on && m.how === 'permanent');
    var shackle = $('modeChipShackle');
    if (shackle) shackle.setAttribute('d', on ? OPEN[1] : SHUT[1]);
    var words = $('modeChipWords');
    var short = !on ? 'Restricted' : m.how === 'permanent' ? 'Unrestricted permanently'
      : (m.how === 'until_back' || !m.until) ? 'Unrestricted, no end set'
      : 'Unrestricted until ' + chipWhen(m.until);
    if (words) words.textContent = short;
    c.title = modeWords(m) + '. Press to see or change it.';
    c.setAttribute('aria-label', modeWords(m) + '. Open Permissions.');
  }
  function chipLoad() {
    var fetcher = window.RouhPermissionsFetch || fetch;
    fetcher('/api/permissions?only=mode', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.mode) chip(j.mode); })
      .catch(function () {});
  }

  /* ---- pressing ---- */

  function press(mode) {
    if (S.busy || !(S.data && S.data.can_change)) return;
    var body = { mode: mode };
    if (mode === 'unrestricted') { body.how = S.how; if (S.how === 'hours') body.hours = S.hours; }
    S.busy = true; S.said = ''; S.bad = '';
    draw();
    call('POST', '/api/permissions', body).then(function (got) {
      S.busy = false;
      if (got && got.ok) {
        S.said = mode === 'unrestricted' ? 'Switched. ' + modeWords(got.body.mode) + '.'
          : 'Switched back. Rouh asks you again where it used to.';
      } else {
        S.bad = (got && got.body && got.body.error) || 'That could not be saved.';
      }
      draw();
      var back = document.querySelector('#permissionsBody .pm-main');
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

  function switchCard(d) {
    var on = d.mode.mode === 'unrestricted';
    var sec = el('section', 'hb-sec pm-switch' + (on ? ' on' : ''));
    sec.setAttribute('aria-labelledby', 'pmSwitchH');
    var h = el('h3', 'hb-h', on ? 'Switch back' : 'Switch to Unrestricted');
    h.id = 'pmSwitchH';
    sec.appendChild(h);
    if (!d.can_change) {
      sec.appendChild(el('p', 'pm-note', 'Only the owner of this Rouh can switch its mode, so this cannot be pressed here.'));
    }
    if (!on) {
      var how = el('fieldset', 'pm-how');
      how.appendChild(el('legend', 'pm-legend', 'For how long'));
      [['hours', 'For some hours'], ['until_back', 'Until I switch it back'], ['permanent', 'Permanently']].forEach(function (o) {
        var row = el('div', 'pm-opt' + (S.how === o[0] ? ' picked' : ''));
        var lab = el('label', 'pm-opt-label');
        var r = el('input');
        r.type = 'radio'; r.name = 'pmHow'; r.value = o[0]; r.checked = S.how === o[0];
        r.disabled = !d.can_change || S.busy;
        r.addEventListener('change', function () { S.how = o[0]; keepLength(); draw(); focusSoon('input[name="pmHow"][value="' + o[0] + '"]'); });
        lab.appendChild(r);
        lab.appendChild(el('span', '', o[1]));
        row.appendChild(lab);
        if (o[0] === 'hours') {
          var hl = el('label', 'pm-hide', 'Hours');
          hl.setAttribute('for', 'pmHours');
          var n = el('select', 'pm-hours');
          n.id = 'pmHours';
          [1, 2, 4, 8, 12, 24, 48, 72].filter(function (x) { return x <= (d.most_hours || 72); }).forEach(function (x) {
            var opt = el('option', '', x + (x === 1 ? ' hour' : ' hours'));
            opt.value = String(x);
            if (x === S.hours) opt.selected = true;
            n.appendChild(opt);
          });
          n.disabled = !d.can_change || S.busy || S.how !== 'hours';
          n.addEventListener('change', function () { S.hours = parseInt(n.value, 10) || 4; keepLength(); draw(); focusSoon('#pmHours'); });
          row.appendChild(hl);
          row.appendChild(n);
        }
        how.appendChild(row);
      });
      sec.appendChild(how);
    }
    var row = el('div', 'pm-acts');
    var b = el('button', 'ctl pm-main' + (on ? '' : ' primary'), S.busy ? 'Saving…'
      : on ? 'Switch back to Restricted' : 'Switch to Unrestricted');
    b.type = 'button';
    b.disabled = !d.can_change || S.busy;
    b.addEventListener('click', function () { press(on ? 'restricted' : 'unrestricted'); });
    row.appendChild(b);
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
      empty.appendChild(el('p', '', 'Nothing yet. Whatever runs because the mode is Unrestricted is listed here, with Undo wherever the service keeps what was there before, as Cloudflare does.'));
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
    return m.mode !== 'unrestricted' && S.how === 'hours' ? S.hours : 8;
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

  function flips(d) {
    var det = el('details', 'pm-flips');
    var sum = el('summary', '', 'Every switch (' + (d.flips || []).length + ')');
    det.appendChild(sum);
    var body = el('div', 'pm-flips-body');
    if (!(d.flips || []).length) body.appendChild(el('p', 'pm-note', 'It has never been switched: Rouh has been Restricted all along.'));
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

  function focusSoon(sel) {
    var n = document.querySelector('#permissionsBody ' + sel);
    if (n) n.focus({ preventScroll: true });
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
    page.appendChild(grants(d));
    page.appendChild(flips(d));
    body.appendChild(page);
  }

  window.RouhPermissions = {
    // A message is about the press that made it: never carried to the next visit.
    shown: function () { S.open = true; S.said = ''; S.bad = ''; S.undoSaid = {}; draw(); load(); },
    hidden: function () { S.open = false; },
    route: ROUTE
  };

  function start() {
    var c = $('modeChip');
    if (c) c.addEventListener('click', function (e) {
      // Cmd, Ctrl, Shift or the middle button: the browser's new tab, as every link here.
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || !window.RouhAnatomy || !window.RouhAnatomy.open) return;
      e.preventDefault();
      window.RouhAnatomy.open('permissions');
    });
    chipLoad();
    setInterval(chipLoad, 60000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) chipLoad(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
