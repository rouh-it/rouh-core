/* Home, Vacuum: the Dreame robot vacuum on the Home page (`homepage.js`, `rouh/dreame.py`).

   Petar, 17 October 2026: "I have robot for cleaning, can we connect that too?" The robot is
   connected in Settings, Connections, Dreame, through Dreamehome or Mi Home; this is where it is
   used. One card: its name, what it is doing in plain words (an error in the robot's own words),
   its battery, and how long and how much it has cleaned while it cleans. Start (Resume when it is
   paused), Pause, Return to dock and Locate. Where its map names rooms, the rooms to press and
   Clean them; where it says its suction, mode and mop wetness, those to press, which the robot
   keeps for its next clean. The base: what it is doing, its clean and used water tanks and its
   dust bag, and Wash mop pads, Dry mop pads (Stop drying) and Empty dust bin where it has them;
   the brushes, filter and pads and how much of each is left, in a section closed until pressed.

   A section of Home (`window.RouhHomeSections`): with no Dreame connection, or one that has
   lapsed, it says so in a line with Connect, as Lights does for Hue. Nothing is drawn before the
   first answer, so there is never a placeholder. A press shows at
   once on the button pressed, and the robot's own state, read again, is what stays. Each part of
   the card is drawn again only when what it shows changed. The robot is read every 5 seconds
   while it cleans or heads home, every 20 otherwise, and not at all while the page is hidden or
   another page is up. GET and POST /api/home/vacuum (`rouh/web/dreame.py`). */
(function () {
  'use strict';

  var BUSY_EVERY = 5000;
  var IDLE_EVERY = 20000;
  var SUCTION = [['quiet', 'Quiet'], ['standard', 'Standard'], ['strong', 'Strong'], ['turbo', 'Turbo']];
  var MODES = [['vacuum', 'Vacuum'], ['mop', 'Mop'], ['both', 'Both']];
  var WETNESS = [[1, 'Slightly dry'], [2, 'Moist'], [3, 'Wet']];
  var TINTS = { cleaning: '#4fb3ff', returning: '#4fb3ff', paused: '#ffcf8a', error: '#ff6b5f' };

  var V = { root: null, on: false, data: null, error: '', timer: 0, reading: false, again: false,
            pressing: '', picked: {}, parts: {}, sig: {} };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function host() { return window.RouhHomeHost || {}; }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function icon(paths) {
    var w = document.createElement('span');
    w.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg>';
    return w.firstChild;
  }
  var ROBOT = '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="8.6" r="1.8"/><path d="M7.6 15.2h8.8"/>';

  function call(method, body) {
    return fetch('/api/home/vacuum', {
      method: method, credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(), 'X-CSRFToken': csrfToken() },
      body: method === 'POST' ? JSON.stringify(body || {}) : undefined
    }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return { status: 401, json: {} }; }
      return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, json: j || {} }; });
    });
  }

  /* ---- reading, on a gentle clock ---- */

  function visible() { return document.visibilityState !== 'hidden'; }

  function busy(d) {
    var k = d && d.robot && d.robot.kind;
    return k === 'cleaning' || k === 'returning' || k === 'paused';
  }

  function schedule(ms) {
    clearTimeout(V.timer);
    V.timer = 0;
    if (!V.on || !visible()) return;
    V.timer = setTimeout(read, ms != null ? ms : (busy(V.data) ? BUSY_EVERY : IDLE_EVERY));
  }

  function read() {
    clearTimeout(V.timer);
    V.timer = 0;
    if (!V.on || !visible()) return;
    if (V.reading) { V.again = true; return; }
    V.reading = true;
    V.again = false;
    call('GET').then(function (got) {
      V.reading = false;
      if (got.status >= 400) {
        // What is shown stays; the line under the name says why it is not new.
        if (V.data) V.error = got.json.error || 'The robot did not answer.';
      } else {
        V.error = '';
        V.data = got.json;
      }
      draw();
      schedule(V.again ? 1200 : null);
    }, function () {
      V.reading = false;
      if (V.data) V.error = 'Rouh could not be reached.';
      draw();
      schedule(V.again ? 1200 : null);
    });
  }

  /* ---- pressing ---- */

  function press(key, body) {
    if (V.pressing) return;
    V.pressing = key;
    V.error = '';
    draw();
    call('POST', body).then(function (got) {
      V.pressing = '';
      if (got.json && 'connected' in got.json) V.data = got.json;
      V.error = got.status >= 400 ? (got.json.error || 'The robot did not do that.') : '';
      draw();
      // The robot's own word on it, a moment from now.
      schedule(2500);
    }, function () {
      V.pressing = '';
      V.error = 'Rouh could not be reached.';
      draw();
    });
  }

  function cleanRooms() {
    var ids = (V.data.rooms || []).filter(function (r) { return V.picked[r.id]; }).map(function (r) { return r.id; });
    if (!ids.length) return;
    V.picked = {};
    press('rooms', { action: 'start', rooms: ids });
  }

  /* ---- drawing, in place ---- */

  function draw() {
    var root = V.root;
    if (!root) return;
    var d = V.data;
    if (!d) {
      // Nothing is drawn before the first answer, and the empty section takes no room.
      if (root.firstChild) { root.textContent = ''; V.parts = {}; V.sig = {}; }
      return;
    }
    if (!V.parts.head) {
      root.textContent = '';
      V.parts = {};
      V.sig = {};
      var h = el('div', 'hm-head');
      h.appendChild(el('h4', 'hm-h', 'Vacuum'));
      root.appendChild(h);
      V.parts.head = h;
      ['line', 'card'].forEach(function (k) {
        var n = el('div', 'hv-' + k);
        root.appendChild(n);
        V.parts[k] = n;
      });
    }
    // A robot the cloud could not reach comes with why, beside it.
    var robot = d.connected && d.robot ? Object.assign({}, d.robot, d.unreachable ? { unreachable: d.unreachable } : {}) : null;
    part('line', [d.connected, d.lapsed, d.said, !!robot], function (n) {
      if (robot) return;
      var line = el('p', 'hm-line');
      // The same line and button as Lights when Hue is not connected.
      line.appendChild(el('span', '', d.lapsed
        ? 'The robot needs signing in again' + (d.said ? ': ' + d.said : '.')
        : !d.connected ? 'The robot vacuum is not connected.'
        : (d.said || 'There is no robot vacuum on this account.')));
      line.appendChild(settingsLink(d.lapsed ? 'Connect again' : d.connected ? 'Settings' : 'Connect', d.page));
      n.appendChild(line);
    });
    if (!robot) {
      if (V.parts.top) {
        V.parts.card.textContent = '';
        ['cardNode', 'top', 'alert', 'acts', 'rooms', 'settings', 'base', 'parts'].forEach(function (k) { delete V.parts[k]; delete V.sig[k]; });
      }
      return;
    }
    drawCard(V.parts.card, d, robot);
  }

  /* Draw one part again only when what it shows changed; the focus stays where it was. */
  function part(key, sig, fill, into) {
    var s = JSON.stringify(sig);
    if (V.sig[key] === s) return;
    V.sig[key] = s;
    var n = into || V.parts[key];
    var focused = document.activeElement && n.contains(document.activeElement)
      ? document.activeElement.getAttribute('data-key') : '';
    n.textContent = '';
    fill(n);
    if (focused) {
      var again = n.querySelector('[data-key="' + focused + '"]');
      if (again) again.focus();
    }
  }

  function settingsLink(text, href) {
    var go = el('a', 'ctl small primary hm-connect', text);
    go.href = href || '/anatomy/connections/dreame';
    go.setAttribute('data-inapp', '');
    go.addEventListener('click', function (e) {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (host().go) host().go(go.getAttribute('href')); else location.href = go.href;
    });
    return go;
  }

  function drawCard(card, d, robot) {
    if (!V.parts.top) {
      card.textContent = '';
      var c = el('div', 'hm-card hv-card');
      card.appendChild(c);
      V.parts.cardNode = c;
      ['top', 'alert', 'acts', 'rooms', 'settings', 'base', 'parts'].forEach(function (k) {
        var n = el('div', 'hv-' + k);
        c.appendChild(n);
        V.parts[k] = n;
      });
    }
    var c2 = V.parts.cardNode;
    var tint = robot.unreachable ? '' : TINTS[robot.kind] || '';
    if (tint) { c2.setAttribute('data-on', ''); c2.style.setProperty('--t1', tint); c2.style.setProperty('--t2', tint); }
    else c2.removeAttribute('data-on');
    c2.setAttribute('data-kind', robot.unreachable ? 'unreachable' : robot.kind || '');

    part('top', [robot.name, robot.words, robot.battery, robot.charging, robot.clean, !!robot.unreachable], function (n) {
      var top = el('div', 'hm-top');
      var dot = el('span', 'hm-bulb hv-icon');
      dot.appendChild(icon(ROBOT));
      top.appendChild(dot);
      var words = el('div', 'hm-words');
      words.appendChild(el('span', 'hm-title', robot.name || 'Robot vacuum'));
      var state = robot.unreachable ? 'Not answering' : robot.words || '';
      if (robot.clean && (robot.clean.minutes || robot.clean.area) &&
          (robot.kind === 'cleaning' || robot.kind === 'paused' || robot.kind === 'returning')) {
        state += ' · ' + robot.clean.minutes + ' min · ' + robot.clean.area + ' m²';
      }
      words.appendChild(el('span', 'hm-state hv-state', state));
      top.appendChild(words);
      if (robot.battery != null && !robot.unreachable) {
        var b = el('span', 'hv-battery' + (robot.battery <= 20 ? ' low' : ''), robot.battery + '%');
        b.title = robot.charging ? 'Battery, charging' : 'Battery';
        b.setAttribute('aria-label', 'Battery ' + robot.battery + '%' + (robot.charging ? ', charging' : ''));
        b.insertBefore(battery(robot.battery, robot.charging), b.firstChild);
        top.appendChild(b);
      }
      n.appendChild(top);
    });

    part('alert', [robot.error, robot.notice, robot.unreachable, V.error], function (n) {
      var said = robot.unreachable || robot.error || '';
      if (said) n.appendChild(el('p', 'hv-error', said));
      else if (robot.notice) n.appendChild(el('p', 'hv-notice', robot.notice));
      if (V.error) {
        var e = el('p', 'hm-line hm-say', V.error);
        e.setAttribute('role', 'status');
        n.appendChild(e);
      }
    });

    var k = robot.kind;
    part('acts', [k, V.pressing, !!robot.unreachable], function (n) {
      if (robot.unreachable) return;
      var row = el('div', 'hv-row');
      row.appendChild(act('start', k === 'paused' ? 'Resume' : 'Start', { action: 'start' },
        k === 'cleaning' || k === 'error', 'Clean everywhere'));
      row.appendChild(act('pause', 'Pause', { action: 'pause' }, k !== 'cleaning' && k !== 'returning',
        'Pause cleaning'));
      row.appendChild(act('dock', 'Return to dock', { action: 'dock' },
        k === 'docked' || k === 'charging', 'Send it back to its dock'));
      row.appendChild(act('locate', 'Locate', { action: 'locate' }, false, 'It says where it is'));
      n.appendChild(row);
    });

    var rooms = d.rooms || [];
    part('rooms', [rooms, V.picked, V.pressing, k, !!robot.unreachable], function (n) {
      if (!rooms.length || robot.unreachable) return;
      n.appendChild(el('h5', 'hm-sub', 'Rooms'));
      var chips = el('div', 'hv-chips');
      chips.setAttribute('role', 'group');
      chips.setAttribute('aria-label', 'Rooms to clean');
      rooms.forEach(function (r) {
        var on = !!V.picked[r.id];
        var b = el('button', 'hm-chip' + (on ? ' on' : ''), r.name);
        b.type = 'button';
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.setAttribute('data-key', 'room-' + r.id);
        b.addEventListener('click', function () {
          if (V.picked[r.id]) delete V.picked[r.id]; else V.picked[r.id] = true;
          draw();
        });
        chips.appendChild(b);
      });
      n.appendChild(chips);
      var count = Object.keys(V.picked).length;
      if (count) {
        var go = act('rooms', count === 1 ? 'Clean 1 room' : 'Clean ' + count + ' rooms', null,
          k === 'cleaning', 'Clean the rooms picked', cleanRooms);
        go.classList.add('primary');
        var row = el('div', 'hv-row');
        row.appendChild(go);
        n.appendChild(row);
      }
    });

    var can = robot.can || {};
    part('settings', [can, robot.suction, robot.mode, robot.wetness, V.pressing, !!robot.unreachable], function (n) {
      var rows = [];
      if (robot.unreachable) return;
      if (can.suction) rows.push(['Suction', 'suction', SUCTION, robot.suction]);
      if (can.mode) rows.push(['Mode', 'mode', MODES, robot.mode]);
      if (can.wetness) rows.push(['Mop', 'wetness', WETNESS, robot.wetness]);
      if (!rows.length) return;
      n.appendChild(el('h5', 'hm-sub', 'For the next clean'));
      rows.forEach(function (r) {
        var line = el('div', 'hv-setting');
        line.appendChild(el('span', 'hv-label', r[0]));
        var chips = el('div', 'hv-chips');
        chips.setAttribute('role', 'radiogroup');
        chips.setAttribute('aria-label', r[0]);
        r[2].forEach(function (o) {
          var on = String(r[3]) === String(o[0]);
          var key = r[1] + '-' + o[0];
          var b = el('button', 'hm-chip' + (on ? ' on' : ''), o[1]);
          b.type = 'button';
          b.setAttribute('role', 'radio');
          b.setAttribute('aria-checked', on ? 'true' : 'false');
          b.setAttribute('data-key', key);
          b.disabled = !!V.pressing;
          if (V.pressing === key) b.setAttribute('aria-busy', 'true');
          b.addEventListener('click', function () {
            if (on) return;
            press(key, { action: r[1], level: String(o[0]) });
          });
          chips.appendChild(b);
        });
        line.appendChild(chips);
        n.appendChild(line);
      });
    });

    drawBase(robot, can);
  }

  function drawBase(robot, can) {
    var base = robot.base || {};
    part('base', [base, can.wash, can.dry, can.empty, V.pressing, !!robot.unreachable], function (n) {
      if (robot.unreachable || !(can.wash || can.dry || can.empty || base.clean_tank || base.dirty_tank || base.dust_bag)) return;
      n.appendChild(el('h5', 'hm-sub', 'Base'));
      // What the base is doing, then each of its tanks and its bag, as the robot says them.
      var facts = [];
      if (base.work) facts.push([base.work, false]);
      if (base.emptying) facts.push(['Emptying the dust bin', false]);
      [['clean_tank', 'Clean water'], ['dirty_tank', 'Used water'], ['dust_bag', 'Dust bag']].forEach(function (t) {
        if (base[t[0]]) facts.push([t[1] + ': ' + base[t[0]].toLowerCase(), base[t[0]] !== 'Fine']);
      });
      if (facts.length) {
        var line = el('p', 'hv-facts');
        facts.forEach(function (f, i) {
          if (i) line.appendChild(document.createTextNode(' · '));
          line.appendChild(el('span', f[1] ? 'hv-warn' : '', f[0]));
        });
        n.appendChild(line);
      }
      var row = el('div', 'hv-row');
      if (can.wash) row.appendChild(act('wash', 'Wash mop pads', { action: 'wash' }, !!base.washing, 'The base washes the mop pads'));
      if (can.dry) row.appendChild(act('dry', base.drying ? 'Stop drying' : 'Dry mop pads', { action: 'dry' }, false,
        base.drying ? 'Stop the hot-air drying' : 'The base dries the mop pads with hot air'));
      if (can.empty) row.appendChild(act('empty', 'Empty dust bin', { action: 'empty' }, !!base.emptying, 'The base empties the robot’s dust bin'));
      if (row.firstChild) n.appendChild(row);
    });
    var cons = robot.consumables || [];
    part('parts', [cons, !!robot.unreachable], function (n) {
      if (robot.unreachable || !cons.length) return;
      // Closed until pressed, and kept open or closed across reads.
      var d = el('details', 'hv-more');
      if (V.partsOpen) d.open = true;
      d.addEventListener('toggle', function () { V.partsOpen = d.open; });
      var sum = el('summary', 'hm-sub', 'Brushes, filter and pads');
      sum.setAttribute('data-key', 'parts');
      d.appendChild(sum);
      var list = el('ul', 'hv-partlist');
      cons.forEach(function (c) {
        var li = el('li', c.left <= 10 ? 'hv-warn' : '');
        li.appendChild(el('span', '', c.name));
        li.appendChild(el('span', 'hv-left', c.left + '% left'));
        list.appendChild(li);
      });
      d.appendChild(list);
      n.appendChild(d);
    });
  }

  function act(key, text, body, off, title, fn) {
    var b = el('button', 'ctl small hv-act', text);
    b.type = 'button';
    b.title = title;
    b.setAttribute('data-key', 'act-' + key);
    b.disabled = !!off || !!V.pressing;
    if (V.pressing === key) b.setAttribute('aria-busy', 'true');
    b.addEventListener('click', fn || function () { press(key, body); });
    return b;
  }

  function battery(pct, charging) {
    var w = Math.max(1, Math.round(13 * Math.min(100, Math.max(0, pct)) / 100));
    return icon('<rect x="3" y="7.5" width="16" height="9" rx="2"/><path d="M21 10.5v3"/>' +
      '<rect x="4.5" y="9" width="' + w + '" height="6" rx="1" fill="currentColor" stroke="none"/>' +
      (charging ? '<path d="M11.5 8.5l-2 3.5h3l-2 3.5" stroke="var(--bg)" stroke-width="1.4"/>' : ''));
  }

  /* ---- the section's life ---- */

  function vacuumShown() {
    V.on = true;
    read();
  }

  function vacuumHidden() {
    V.on = false;
    clearTimeout(V.timer);
    V.timer = 0;
  }

  document.addEventListener('visibilitychange', function () {
    if (!V.on) return;
    if (visible()) read(); else { clearTimeout(V.timer); V.timer = 0; }
  });

  (window.RouhHomeSections = window.RouhHomeSections || []).push({
    id: 'vacuum', order: 20,
    mount: function (node) { V.root = node; V.parts = {}; V.sig = {}; node.classList.add('hv-section'); },
    shown: vacuumShown, hidden: vacuumHidden
  });
})();
