/* Anatomy, Behaviour, Permission gates, at /anatomy/behaviour/gates (`rouh/gates.py`, `rouh/web/gates.py`).

   Petar, 15 November 2026: "setup an interface in anatomy to know there are permission gates and
   adjust them but I don't want to deal with them myself as of now."

   A headline that says whether any tool is gated, what a gate is in three lines, then every tool by
   its area, the candidates first, each with an "Ask me first" switch. A candidate is a tool where a
   mistake costs money or cannot be taken back, marked with the words of that mistake; nothing is
   switched on by default. A tool the server gates (ROUH_CONFIRM_TOOLS) is on and locked. Drawn into
   `#gatesBody` from `/api/anatomy/gates`; Anatomy says when it shows and when it is left
   (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  /* data: the last answer. only: just the candidates. q: the search. busy: the tool being saved.
     said / error: what the last change of each tool did. fail: the page could not be read.
     shownAll: the areas opened in full; the rest show their candidates and gated tools only. */
  var S = { open: false, data: null, seq: 0, only: false, q: '', busy: '', said: {}, error: {}, fail: '', shownAll: {} };

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
  var LOCK = ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'];
  var HAND = ['M12 3l8 4v5c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V7z', 'M9 12l2 2 4-4'];
  var CODE = ['M8 8l-4 4 4 4', 'M16 8l4 4-4 4', 'M13.5 6l-3 12'];
  var BELL = ['M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z', 'M10 20a2 2 0 0 0 4 0'];
  var WARN = ['M12 4l9 16H3z', 'M12 10v4', 'M12 17h.01'];

  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }

  function call(method, body, tool) {
    var seq = ++S.seq;
    var fetcher = window.RouhGatesFetch || fetch;
    return fetcher('/api/anatomy/gates', {
      method: method, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: method === 'POST' ? JSON.stringify(body || {}) : undefined
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (method === 'GET' && seq !== S.seq) return null;
        if (j && j.groups) { S.data = j; S.fail = ''; }
        if (!r.ok) {
          var why = (j && j.error) || 'The server said ' + r.status + '.';
          if (tool) S.error[tool] = why; else S.fail = why;
        }
        return { ok: r.ok, body: j || {} };
      });
    }).catch(function () {
      var why = 'Rouh could not be reached. Check the connection and try again.';
      if (tool) S.error[tool] = why; else S.fail = why;
      return { ok: false, body: {} };
    });
  }

  function load() {
    return call('GET').then(function () { draw(); });
  }

  function flip(t) {
    if (S.busy || t.locked || !(S.data && S.data.can_change)) return;
    var want = !t.on;
    S.busy = t.name;
    delete S.error[t.name];
    delete S.said[t.name];
    draw();
    call('POST', { tool: t.name, on: want }, t.name).then(function (got) {
      S.busy = '';
      if (got && got.ok) {
        S.said[t.name] = want ? 'Saved. It asks you first from its next call.' : 'Saved. It runs without asking.';
        setTimeout(function () { if (S.said[t.name]) { delete S.said[t.name]; draw(); } }, 5000);
      }
      draw();
      var back = document.querySelector('#gatesBody [data-tool="' + t.name + '"] .gp-sw');
      if (back) back.focus({ preventScroll: true });
    });
  }

  /* ---- drawing ---- */

  function names(list) {
    var shown = list.slice(0, 3).join(', ');
    return list.length > 3 ? shown + ' and ' + (list.length - 3) + ' more' : shown;
  }

  function headline(d) {
    var p = el('p', 'gp-headline');
    var on = [], locked = 0;
    d.groups.forEach(function (g) { g.tools.forEach(function (t) { if (t.on) on.push(t.name); if (t.locked) locked++; }); });
    var state = el('span', 'gp-state' + (on.length ? ' on' : ''), on.length ? 'On' : 'Off');
    p.appendChild(state);
    if (!on.length) {
      p.appendChild(document.createTextNode('No tool is gated: all ' + d.total + ' of Rouh’s tools run without asking you first.'));
    } else {
      p.appendChild(document.createTextNode(
        on.length + (on.length === 1 ? ' tool asks' : ' tools ask') + ' you first: ' + names(on) + '. ' +
        (locked ? (locked === on.length ? (locked === 1 ? 'It is' : 'They are') : locked + ' of them ' + (locked === 1 ? 'is' : 'are')) +
                  ' locked on by the server. ' : '') +
        (d.total - on.length) + ' run without asking.'));
    }
    return p;
  }

  function about(d) {
    var sec = el('section', 'hb-sec');
    sec.setAttribute('aria-labelledby', 'gpAboutH');
    var h = el('h3', 'hb-h', 'What a gate is');
    h.id = 'gpAboutH';
    sec.appendChild(h);
    var ul = el('ul', 'gp-about');
    function line(paths, parts) {
      var li = el('li');
      li.appendChild(icon(paths));
      var span = el('span');
      parts.forEach(function (p) { span.appendChild(typeof p === 'string' ? document.createTextNode(p) : p); });
      li.appendChild(span);
      ul.appendChild(li);
    }
    line(HAND, ['A tool you switch to Ask me first stops before it runs and waits for your yes, for every use of that tool. A yes is for that one call only.']);
    line(CODE, ['It is enforced by Rouh’s code, not by its rules: Rouh cannot talk its way past it.']);
    var link = el('a', '', 'Decisions');
    link.href = '/decisions';
    var secs = Math.round(d.timeout || 120);
    var wait = secs % 60 === 0 ? (secs / 60) + (secs === 60 ? ' minute' : ' minutes') : secs + ' seconds';
    line(BELL, ['It asks you under the conversation and on ', link,
                ', with a notice. With no answer in ' + wait + ' it is not done, and Rouh says it is waiting on you.']);
    sec.appendChild(ul);
    return sec;
  }

  function matches(t) {
    if (S.only && !t.candidate && !t.on) return false;
    if (!S.q) return true;
    var q = S.q.toLowerCase();
    return t.name.toLowerCase().indexOf(q) >= 0 || (t.brief || '').toLowerCase().indexOf(q) >= 0;
  }

  function finder(d) {
    var row = el('div', 'gp-find');
    var only = el('button', 'gp-only');
    only.type = 'button';
    only.setAttribute('aria-pressed', S.only ? 'true' : 'false');
    only.appendChild(icon(WARN));
    only.appendChild(document.createTextNode('Only candidates '));
    only.appendChild(el('span', 'gp-count', String(d.candidates)));
    only.addEventListener('click', function () { S.only = !S.only; draw(); focusSoon('.gp-only'); });
    row.appendChild(only);
    var wrap = el('div', 'gp-search-wrap');
    var label = el('label', 'gp-hide', 'Find a tool');
    label.setAttribute('for', 'gpSearch');
    var input = el('input', 'gp-search');
    input.type = 'search';
    input.id = 'gpSearch';
    input.placeholder = 'Find a tool, such as send_mail';
    input.value = S.q;
    input.autocomplete = 'off';
    input.addEventListener('input', function () {
      S.q = input.value.trim();
      drawTools();
    });
    wrap.appendChild(label);
    wrap.appendChild(input);
    row.appendChild(wrap);
    return row;
  }

  function focusSoon(sel) {
    var n = document.querySelector('#gatesBody ' + sel);
    if (n) n.focus({ preventScroll: true });
  }

  function toolRow(t, can) {
    var li = el('li', 'gp-row');
    li.setAttribute('data-tool', t.name);
    var who = el('div', 'gp-who');
    var top = el('div', 'gp-name-line');
    top.appendChild(el('span', 'gp-name', t.name));
    if (t.candidate) {
      var chip = el('span', 'gp-chip');
      chip.appendChild(icon(WARN));
      chip.appendChild(document.createTextNode(t.kind_words || 'Candidate'));
      chip.title = 'A candidate: a mistake with this tool is expensive or cannot be undone';
      top.appendChild(chip);
    }
    if (t.missing) {
      var gone = el('span', 'gp-chip lock', 'No longer a tool');
      gone.title = 'A gate is set for a tool this Rouh does not have now: switch it off to clear it';
      top.appendChild(gone);
    }
    if (t.locked) {
      var lock = el('span', 'gp-chip lock');
      lock.appendChild(icon(LOCK));
      lock.appendChild(document.createTextNode('Locked on by the server'));
      lock.title = 'Gated by ROUH_CONFIRM_TOOLS in the server’s settings';
      top.appendChild(lock);
    }
    who.appendChild(top);
    if (t.brief) who.appendChild(el('p', 'gp-brief', t.brief));
    li.appendChild(who);

    var sw = el('button', 'gp-sw' + (S.busy === t.name ? ' busy' : ''));
    sw.type = 'button';
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', t.on ? 'true' : 'false');
    sw.setAttribute('aria-label', 'Ask me first before ' + t.name + ' runs');
    sw.disabled = t.locked || !can || (!!S.busy && S.busy !== t.name);
    if (t.locked) sw.title = 'Locked on: ROUH_CONFIRM_TOOLS in the server’s settings gates it';
    sw.appendChild(el('span', 'gp-knob'));
    sw.appendChild(el('span', 'gp-sw-word', S.busy === t.name ? 'Saving' : t.on ? 'On' : 'Off'));
    sw.addEventListener('click', function () { flip(t); });
    li.appendChild(sw);

    if (S.error[t.name]) li.appendChild(el('p', 'gp-row-say bad', S.error[t.name]));
    else if (S.said[t.name]) li.appendChild(el('p', 'gp-row-say good', S.said[t.name]));
    return li;
  }

  function drawTools() {
    var box = $('gpTools');
    if (!box || !S.data) return;
    box.textContent = '';
    var d = S.data;
    var groups = d.groups.slice().sort(function (a, b) { return (b.candidates > 0) - (a.candidates > 0); });
    var any = false;
    var quiet = [];
    groups.forEach(function (g) {
      // An area with no candidate and nothing gated is one press in a compact row at the end,
      // until it is opened or a search reaches into it.
      if (!S.q && !S.only && !S.shownAll[g.id] && !g.candidates && !g.gated &&
          !g.tools.some(function (t) { return S.busy === t.name || S.said[t.name] || S.error[t.name]; })) {
        quiet.push(g);
        return;
      }
      var found = g.tools.filter(matches);
      if (!found.length) return;
      any = true;
      // An area shows its candidates and anything gated; the rest wait behind one press, unless a
      // search is asking for them or the area was opened.
      var whole = !!S.q || S.shownAll[g.id];
      var shown = whole ? found : found.filter(function (t) { return t.candidate || t.on || S.busy === t.name || S.said[t.name] || S.error[t.name]; });
      var rest = found.length - shown.length;
      var sec = el('div', 'gp-group');
      sec.setAttribute('data-group', g.id);
      var h = el('h4', 'gp-group-h', g.name);
      var bits = [g.tools.length + (g.tools.length === 1 ? ' tool' : ' tools')];
      if (g.candidates) bits.push(g.candidates + (g.candidates === 1 ? ' candidate' : ' candidates'));
      bits.push(g.gated ? g.gated + ' gated' : 'none gated');
      h.appendChild(el('span', 'gp-group-n', bits.join(' · ')));
      sec.appendChild(h);
      var ul = el('ul', 'gp-rows');
      shown.forEach(function (t) { ul.appendChild(toolRow(t, !!d.can_change)); });
      sec.appendChild(ul);
      if (rest > 0 || (S.shownAll[g.id] && !S.q && found.length > shown.filter(function (t) { return t.candidate || t.on; }).length)) {
        var more = el('button', 'gp-more');
        more.type = 'button';
        var open = !!S.shownAll[g.id];
        more.textContent = open ? 'Show fewer' : (shown.length ? 'Show the other ' + rest + (rest === 1 ? ' tool' : ' tools')
                                                                 : 'Show its ' + rest + (rest === 1 ? ' tool' : ' tools'));
        more.setAttribute('aria-expanded', open ? 'true' : 'false');
        more.addEventListener('click', function () {
          if (open) delete S.shownAll[g.id]; else S.shownAll[g.id] = true;
          drawTools();
          var again = document.querySelector('#gatesBody [data-group="' + g.id + '"] .gp-more');
          if (again) again.focus({ preventScroll: true });
        });
        sec.appendChild(more);
      }
      box.appendChild(sec);
    });
    if (quiet.length) {
      any = true;
      var rest = el('div', 'gp-group gp-quiet');
      var n = 0;
      quiet.forEach(function (g) { n += g.tools.length; });
      var qh = el('h4', 'gp-group-h', 'Areas with no candidates');
      qh.appendChild(el('span', 'gp-group-n', quiet.length + ' areas · ' + n + ' tools · none gated'));
      rest.appendChild(qh);
      var wrap = el('div', 'gp-quiet-list');
      quiet.forEach(function (g) {
        var b = el('button', 'gp-area');
        b.type = 'button';
        b.setAttribute('data-area', g.id);
        b.appendChild(document.createTextNode(g.name + ' '));
        b.appendChild(el('span', 'gp-count', String(g.tools.length)));
        b.setAttribute('aria-label', 'Show ' + g.name + ', ' + g.tools.length + (g.tools.length === 1 ? ' tool' : ' tools'));
        b.addEventListener('click', function () {
          S.shownAll[g.id] = true;
          drawTools();
          var opened = document.querySelector('#gatesBody [data-group="' + g.id + '"] .gp-sw');
          if (opened) opened.focus();
        });
        wrap.appendChild(b);
      });
      rest.appendChild(wrap);
      box.appendChild(rest);
    }
    if (!any) box.appendChild(el('p', 'gp-empty', S.q ? 'No tool matches “' + S.q + '”.' : 'No tool matches.'));
  }

  function draw() {
    var body = $('gatesBody');
    if (!body || !S.open) return;
    var keepSearch = document.activeElement && document.activeElement.id === 'gpSearch';
    body.textContent = '';
    var page = el('div', 'hb-page gp-page');
    var d = S.data;
    if (!d) {
      if (S.fail) {
        var f = el('p', 'gp-fail', S.fail);
        var again = el('button', 'ctl small', 'Try again');
        again.type = 'button';
        again.addEventListener('click', function () { S.fail = ''; draw(); load(); });
        f.appendChild(again);
        page.appendChild(f);
      } else {
        page.appendChild(el('p', 'hb-empty', 'Reading Rouh’s tools…'));
      }
      body.appendChild(page);
      body.setAttribute('aria-busy', S.fail ? 'false' : 'true');
      return;
    }
    body.setAttribute('aria-busy', 'false');
    page.appendChild(headline(d));
    if (!d.can_change) page.appendChild(el('p', 'gp-only-admin', 'Only this Rouh’s administrator can change its gates, so the switches here cannot be pressed.'));
    page.appendChild(about(d));
    var tools = el('section', 'hb-sec');
    tools.setAttribute('aria-labelledby', 'gpToolsH');
    var h = el('h3', 'hb-h', 'Tools');
    h.id = 'gpToolsH';
    h.appendChild(el('span', 'hb-h-sub', 'Candidates first: where a mistake costs money or cannot be undone'));
    tools.appendChild(h);
    if (S.fail) tools.appendChild(el('p', 'gp-fail', S.fail));
    tools.appendChild(finder(d));
    var list = el('div');
    list.id = 'gpTools';
    tools.appendChild(list);
    page.appendChild(tools);
    body.appendChild(page);
    drawTools();
    if (keepSearch) {
      var s = $('gpSearch');
      if (s) { s.focus({ preventScroll: true }); s.setSelectionRange(s.value.length, s.value.length); }
    }
  }

  window.RouhGates = {
    shown: function () {
      S.open = true;
      draw();
      load();
    },
    hidden: function () { S.open = false; }
  };
})();
