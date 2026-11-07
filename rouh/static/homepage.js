/* Home, at /home (`rouh/web/home.py`, `rouh/hue.py`): the house itself.

   Petar, 17 October 2026: "chat is not going to cut it. Very cumbersome. I need interface and
   quick access... It should be part of a bigger push towards home automation in general."

   A hub of sections, one for each kind of device, each drawn by its own script into an element
   of its own, in the order each asks for. Lights are the first, and are here. A section is
   added with

     (window.RouhHomeSections = window.RouhHomeSections || []).push({
       id: 'vacuum', order: 20, mount: function (el) {}, shown: function () {}, hidden: function () {} });

   at any time, before or after this script: `mount` is called once, the first time Home is
   shown, with the section's own empty `<section id="homeSection-<id>">`; `shown` and `hidden`
   each time Home is shown and left. A section with nothing to show draws nothing, and its
   empty element takes no room.

   The lights, laid out as the Hue app lays them out: a card for each room, then each zone, then
   any light in no room, with its name, whether it is on and how bright, a switch and a slider.
   Pressing its name opens it in place: its scenes, its colours and warm whites where its lights
   have them, and each of its lights with a switch and a slider of its own. What is pressed shows
   at once, and the bridge's own state, read again a moment later, is what stays. Nothing is
   drawn again that did not change, and nothing moves.

   The state is read every 12 seconds while the page is on screen, and not at all while it is
   hidden or another page is up. A 429 from the Hue cloud keeps what is shown and reads again
   after 45 seconds. A slider sends one change at a time for each thing it changes, the latest
   value once the one before has been answered, so a drag is a few calls rather than dozens. */
(function () {
  'use strict';

  var EVERY = 12000;
  var SLOWER = 45000;
  // How long after a press the bridge's answer is waited for before a read may overwrite it.
  var SETTLE = 2500;

  function $(id) { return document.getElementById(id); }
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
  function svg(paths, size) {
    var s = '<svg viewBox="0 0 24 24" width="' + (size || 20) + '" height="' + (size || 20) + '" aria-hidden="true" ' +
      'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + paths + '</svg>';
    var w = document.createElement('span');
    w.innerHTML = s;
    return w.firstChild;
  }
  var BULB = '<path d="M9 17.5h6"/><path d="M10 20.5h4"/><path d="M12 3.5a5.5 5.5 0 0 0-3.2 10c.7.5 1.2 1.3 1.2 2.2V17.5h4v-1.8c0-.9.5-1.7 1.2-2.2A5.5 5.5 0 0 0 12 3.5z"/>';
  var CHEVRON = '<path d="M6 9l6 6 6-6"/>';

  /* ================================================================ the hub */

  var H = { open: false, sections: [], wrapped: false };

  function sectionsBox() {
    var body = $('homeBody');
    if (!body) return null;
    var box = body.querySelector('.hm-page');
    if (!box) { box = el('div', 'hm-page'); body.appendChild(box); }
    return box;
  }

  function place(sec) {
    var box = sectionsBox();
    if (!box || sec.node) return;
    var node = el('section', 'hm-section');
    node.id = 'homeSection-' + sec.id;
    sec.node = node;
    // In order: before the first section that comes after it.
    var after = null;
    for (var i = 0; i < H.sections.length; i++) {
      var o = H.sections[i];
      if (o !== sec && o.node && o.node.parentNode === box && (o.order > sec.order)) {
        if (!after || o.order < after.order) after = o;
      }
    }
    box.insertBefore(node, after ? after.node : null);
    try { sec.mount(node); } catch (err) { if (window.console) console.error('home: section ' + sec.id, err); }
    sec.mounted = true;
  }

  function add(sec) {
    if (!sec || !sec.id || typeof sec.mount !== 'function') return;
    if (H.sections.some(function (o) { return o.id === sec.id; })) return;
    var s = { id: String(sec.id), order: Number(sec.order) || 100, mount: sec.mount, shown: sec.shown,
              hidden: sec.hidden, node: null, mounted: false };
    H.sections.push(s);
    if (H.wrapped) {
      place(s);
      if (H.open && typeof s.shown === 'function') s.shown();
    }
  }

  // Sections pushed before this script ran, and every one pushed after it.
  var queue = window.RouhHomeSections = window.RouhHomeSections || [];
  queue.forEach(add);
  queue.push = function () {
    for (var i = 0; i < arguments.length; i++) add(arguments[i]);
    return Array.prototype.push.apply(queue, arguments);
  };

  function shown() {
    if (H.open) return;
    H.open = true;
    if (!H.wrapped) {
      H.wrapped = true;
      H.sections.slice().sort(function (a, b) { return a.order - b.order; }).forEach(place);
    }
    H.sections.forEach(function (s) { if (typeof s.shown === 'function') s.shown(); });
  }

  function hidden() {
    if (!H.open) return;
    H.open = false;
    H.sections.forEach(function (s) { if (typeof s.hidden === 'function') s.hidden(); });
  }

  window.RouhHome = { shown: shown, hidden: hidden };

  var x = $('homeClose');
  if (x) x.addEventListener('click', function () { if (host().close) host().close(); });

  /* ================================================================ the lights */

  var L = {
    root: null, data: null, error: '', on: false, timer: 0, wait: EVERY, reading: false,
    // Open cards, by their key ("room:<id>"), kept while the page is.
    open: {},
    // A key pressed recently: its controls keep what was pressed until the bridge has answered.
    held: {},
    // One change in flight for each key, and the latest one waiting behind it.
    flying: {}, next: {}, last: {}, sentAt: {},
    cards: {}
  };

  function call(method, body) {
    return fetch('/api/home/lights', {
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

  function schedule(ms) {
    clearTimeout(L.timer);
    L.timer = 0;
    if (!L.on || !visible()) return;
    L.timer = setTimeout(read, ms == null ? L.wait : ms);
  }

  function read() {
    clearTimeout(L.timer);
    L.timer = 0;
    if (!L.on || !visible()) return;
    // A read asked for while one is on its way is made once that one is back.
    if (L.reading) { L.again = true; return; }
    L.reading = true;
    L.again = false;
    call('GET').then(function (got) {
      L.reading = false;
      if (got.status === 429) {
        L.wait = SLOWER;
        L.again = false;
      } else if (got.status >= 400) {
        L.error = got.json.error || 'Hue did not answer.';
        L.wait = EVERY;
      } else {
        L.error = '';
        L.wait = EVERY;
        take(got.json);
      }
      draw();
      schedule(L.again ? 1200 : null);
    }, function () {
      L.reading = false;
      L.error = 'Rouh could not be reached.';
      draw();
      schedule(L.again ? 1200 : null);
    });
  }

  /* A read of the home, merged into what is shown: what was pressed and is still held keeps the
     pressed values, and only those, until the bridge has had time to say them back. */
  function take(fresh) {
    var now = Date.now();
    if (L.data && fresh.connected) {
      eachThing(fresh, function (key, t) {
        var held = L.held[key];
        if (!held || held.until < now) { delete L.held[key]; return; }
        var mine = find(L.data, key);
        if (!mine) return;
        Object.keys(held.fields).forEach(function (f) { if (f in mine) t[f] = mine[f]; });
      });
    }
    L.data = fresh;
  }

  function eachThing(d, fn) {
    ['rooms', 'zones'].forEach(function (k) {
      (d[k] || []).forEach(function (g) {
        fn(g.kind + ':' + g.id, g);
        (g.lights || []).forEach(function (l) { fn('light:' + l.id, l); });
      });
    });
    (d.loose || []).forEach(function (l) { fn('light:' + l.id, l); });
  }

  function find(d, key) {
    var hit = null;
    if (d) eachThing(d, function (k, t) { if (!hit && k === key) hit = t; });
    return hit;
  }

  // Every copy of a light: it is in its room and in every zone it is in.
  function eachCopy(key, fn) {
    if (L.data) eachThing(L.data, function (k, t) { if (k === key) fn(t); });
  }

  /* ---- pressing ---- */

  /* Hold what a press changed on `key` (its `fields`) for `ms`, or until its change is answered. */
  function hold(key, fields, ms) {
    var h = L.held[key] || (L.held[key] = { until: 0, fields: {} });
    fields.forEach(function (f) { h.fields[f] = true; });
    h.until = ms === Infinity ? Infinity : Math.max(h.until === Infinity ? 0 : h.until, Date.now() + ms);
  }

  function release(keys, ms) {
    keys.forEach(function (k) {
      var h = L.held[k];
      if (!h) return;
      if (ms) h.until = Date.now() + ms; else delete L.held[k];
    });
  }

  /* Send a change for one key: one at a time, the latest waiting behind the one in flight, and
     never sooner than `GAP` after the one before for a room or a zone (`GAP_LIGHT` for a light),
     which is inside what Hue asks of an app. `holds` is each key it changes, with the fields it
     changes there. The same change twice running is sent once. */
  var GAP = 600, GAP_LIGHT = 300;

  function send(key, body, holds) {
    holds.forEach(function (h) { hold(h[0], h[1], Infinity); });
    var keys = holds.map(function (h) { return h[0]; });
    var said = JSON.stringify(body);
    if (L.flying[key]) {
      var queued = L.next[key];
      L.next[key] = { body: body, said: said, keys: (queued ? queued.keys : []).concat(keys) };
      return;
    }
    // A slider let go where its last step already was.
    if (said === L.last[key] && (body.brightness != null || body.kelvin != null) &&
        Date.now() - (L.sentAt[key] || 0) < 3000) { release(keys, SETTLE); schedule(1200); return; }
    fire(key, body, said, keys);
  }

  function fire(key, body, said, keys) {
    L.flying[key] = keys;
    L.last[key] = said;
    L.sentAt[key] = Date.now();
    call('POST', body).then(function (got) { landed(key, got); }, function () {
      landed(key, { status: 0, json: { error: 'Rouh could not be reached.' } });
    });
  }

  function landed(key, got) {
    var keys = L.flying[key] || [];
    var bad = got.status >= 400 || got.status === 0;
    if (bad) {
      L.error = got.json.error || 'That did not reach the lights.';
      L.last[key] = '';
    } else {
      L.error = '';
    }
    var waiting = L.next[key];
    delete L.next[key];
    if (waiting && !(got.json && got.json.connected === false)) {
      // The latest value goes next; what this one held stays held for it.
      var gap = (key.indexOf('light:') === 0 ? GAP_LIGHT : GAP) - (Date.now() - (L.sentAt[key] || 0));
      var all = keys.concat(waiting.keys);
      L.flying[key] = all;
      if (bad) draw();
      setTimeout(function () {
        if (waiting.said === L.last[key]) { L.flying[key] = false; release(all, SETTLE); schedule(1200); return; }
        fire(key, waiting.body, waiting.said, all);
      }, Math.max(0, gap));
      return;
    }
    L.flying[key] = false;
    if (bad) {
      release(keys, 0);
      if (got.json && got.json.connected === false) { L.data = got.json; draw(); return; }
      draw();
      schedule(300);
      return;
    }
    release(keys, SETTLE);
    // The bridge's own word on it, a moment from now.
    schedule(1200);
  }

  function lightKeys(t, fields, only) {
    return (t.lights || []).filter(function (l) { return !only || l[only]; })
      .map(function (l) { return ['light:' + l.id, fields]; });
  }

  function setOn(key, on) {
    var t = find(L.data, key);
    if (!t) return;
    var kind = key.split(':')[0];
    eachCopy(key, function (c) { c.on = on; });
    var holds = [[key, ['on']]];
    if (kind !== 'light') {
      (t.lights || []).forEach(function (l) { eachCopy('light:' + l.id, function (c) { c.on = on; }); });
      if (!on) (t.scenes || []).forEach(function (s) { s.active = false; });
      holds = [[key, on ? ['on'] : ['on', 'scenes']]].concat(lightKeys(t, ['on']));
    }
    draw();
    send(key, { kind: kind, id: t.id, on: on }, holds);
  }

  function setBrightness(key, pct) {
    var t = find(L.data, key);
    if (!t) return;
    var kind = key.split(':')[0];
    eachCopy(key, function (c) { c.on = true; c.brightness = pct; });
    if (kind !== 'light') {
      (t.lights || []).forEach(function (l) {
        eachCopy('light:' + l.id, function (c) { c.on = true; if (c.dims) c.brightness = pct; });
      });
    }
    draw();
    send(key, { kind: kind, id: t.id, brightness: pct },
      [[key, ['on', 'brightness']]].concat(kind !== 'light' ? lightKeys(t, ['on', 'brightness']) : []));
  }

  function setColour(key, hex) {
    var t = find(L.data, key);
    if (!t) return;
    var kind = key.split(':')[0];
    t.on = true;
    t.tints = [hex];
    (t.lights || []).forEach(function (l) {
      if (!l.colour) return;
      eachCopy('light:' + l.id, function (c) { c.on = true; c.tint = hex; c.mode = 'colour'; });
    });
    draw();
    send(key, { kind: kind, id: t.id, colour: hex },
      [[key, ['on', 'tints']]].concat(lightKeys(t, ['on', 'tint', 'mode'], 'colour')));
  }

  function setKelvin(key, kelvin) {
    var t = find(L.data, key);
    if (!t) return;
    var kind = key.split(':')[0];
    var hex = whiteHex(kelvin), mirek = Math.round(1e6 / kelvin);
    t.on = true;
    t.tints = [hex];
    (t.lights || []).forEach(function (l) {
      if (!l.white) return;
      eachCopy('light:' + l.id, function (c) { c.on = true; c.tint = hex; c.mode = 'white'; c.mirek = mirek; });
    });
    draw();
    send(key, { kind: kind, id: t.id, kelvin: kelvin },
      [[key, ['on', 'tints']]].concat(lightKeys(t, ['on', 'tint', 'mode', 'mirek'], 'white')));
  }

  function scene(key, s) {
    var g = find(L.data, key);
    if (!g) return;
    g.scenes.forEach(function (o) { o.active = o.id === s.id; });
    g.on = true;
    // How bright the scene is, the bridge says next.
    g.brightness = null;
    draw();
    send(key, { scene: s.id }, [[key, ['on', 'scenes']]]);
  }

  function allOff() {
    if (!L.data) return;
    var holds = [];
    eachThing(L.data, function (k, t) {
      t.on = false;
      (t.scenes || []).forEach(function (s) { s.active = false; });
      holds.push([k, ['on', 'scenes']]);
    });
    draw();
    send('*', { all_off: true }, holds);
  }

  /* ---- colours as a screen shows them ---- */

  // A white of `kelvin` as a colour (Tanner Helland's fit, as `rouh/hue.py` has it).
  function whiteHex(kelvin) {
    var t = Math.max(1000, Math.min(40000, kelvin)) / 100, r, g, b;
    r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
    g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
    b = t >= 66 ? 255 : (t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307);
    return '#' + [r, g, b].map(function (c) {
      var v = Math.round(Math.max(0, Math.min(255, c)));
      return (v < 16 ? '0' : '') + v.toString(16);
    }).join('');
  }

  var SWATCHES = [['Red', '#ff2a1f'], ['Orange', '#ff8a1f'], ['Yellow', '#ffd21f'], ['Green', '#38d86b'],
                  ['Cyan', '#2ad4e8'], ['Blue', '#2f5bff'], ['Purple', '#9a3cff'], ['Pink', '#ff4fb0']];
  var WARMEST = 2000, COOLEST = 6500;

  /* ---- drawing, in place ---- */

  function draw() {
    var root = L.root;
    if (!root) return;
    if (!L.data) {
      root.textContent = '';
      root.appendChild(head(false));
      var wait = el('p', 'hm-line hm-quiet', L.error || 'Reading the lights…');
      root.appendChild(wait);
      return;
    }
    if (L.data.connected === false) {
      root.textContent = '';
      L.cards = {};
      root.appendChild(head(false));
      var line = el('p', 'hm-line');
      line.appendChild(el('span', '', L.data.said || 'Philips Hue is not connected.'));
      var go = el('a', 'ctl small primary hm-connect', 'Connect');
      go.href = L.data.connect || '/anatomy/connections/hue';
      go.setAttribute('data-inapp', '');
      go.addEventListener('click', function (e) {
        if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        if (host().go) host().go(go.getAttribute('href')); else location.href = go.href;
      });
      line.appendChild(go);
      root.appendChild(line);
      return;
    }
    var shell = root.querySelector('.hm-lights');
    if (!shell) {
      root.textContent = '';
      L.cards = {};
      shell = el('div', 'hm-lights');
      shell.appendChild(head(true));
      var say = el('p', 'hm-line hm-say');
      say.setAttribute('role', 'status');
      shell.appendChild(say);
      [['rooms', 'Rooms'], ['zones', 'Zones'], ['loose', 'Not in a room']].forEach(function (p) {
        var part = el('div', 'hm-part');
        part.setAttribute('data-part', p[0]);
        part.appendChild(el('h5', 'hm-sub', p[1]));
        var grid = el('div', 'hm-grid');
        grid.setAttribute('role', 'list');
        part.appendChild(grid);
        shell.appendChild(part);
      });
      root.appendChild(shell);
    }
    var sayNode = shell.querySelector('.hm-say');
    sayNode.textContent = L.error;
    sayNode.hidden = !L.error;
    var off = shell.querySelector('.hm-alloff');
    if (off) off.disabled = !anyOn(L.data);
    var seen = {};
    ['rooms', 'zones', 'loose'].forEach(function (k) {
      var part = shell.querySelector('[data-part="' + k + '"]');
      var grid = part.querySelector('.hm-grid');
      var list = L.data[k] || [];
      part.hidden = !list.length;
      var nodes = list.map(function (t) {
        var key = (k === 'loose' ? 'light' : t.kind) + ':' + t.id;
        seen[key] = true;
        var card = L.cards[key];
        if (!card) { card = L.cards[key] = makeCard(key); }
        fillCard(card, key, t);
        return card.node;
      });
      // Only moved when the bridge's own order changed; never otherwise.
      var same = grid.children.length === nodes.length && nodes.every(function (n, i) { return grid.children[i] === n; });
      if (!same) nodes.forEach(function (n) { grid.appendChild(n); });
      Array.prototype.slice.call(grid.children).forEach(function (n) { if (nodes.indexOf(n) < 0) n.remove(); });
    });
    Object.keys(L.cards).forEach(function (k) { if (!seen[k]) delete L.cards[k]; });
  }

  function anyOn(d) {
    var on = false;
    eachThing(d, function (k, t) { if (t.on) on = true; });
    return on;
  }

  function head(withOff) {
    var h = el('div', 'hm-head');
    h.appendChild(el('h4', 'hm-h', 'Lights'));
    if (withOff) {
      var b = el('button', 'ctl small hm-alloff', 'All off');
      b.type = 'button';
      b.title = 'Turn every light off';
      b.addEventListener('click', allOff);
      h.appendChild(b);
    }
    return h;
  }

  var seq = 0;

  function sw(label) {
    var b = el('button', 'hm-switch');
    b.type = 'button';
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-label', label);
    b.appendChild(el('span', 'hm-knob'));
    return b;
  }

  function slider(label) {
    var r = el('input', 'hm-dim');
    r.type = 'range';
    r.min = '1';
    r.max = '100';
    r.step = '1';
    r.setAttribute('aria-label', label);
    return r;
  }

  /* A slider that sends while it is dragged, at most once in flight for its key, and once more
     where it is let go; while a finger is on it nothing read from the bridge moves it. */
  function wireSlider(r, act) {
    r.addEventListener('pointerdown', function () { r.dataset.held = '1'; });
    ['pointerup', 'pointercancel', 'blur'].forEach(function (ev) {
      r.addEventListener(ev, function () { delete r.dataset.held; });
    });
    r.addEventListener('input', function () {
      paintFill(r);
      act(Number(r.value), false);
    });
    r.addEventListener('change', function () { act(Number(r.value), true); });
  }

  function paintFill(r) {
    var lo = Number(r.min), hi = Number(r.max);
    r.style.setProperty('--pct', (((Number(r.value) - lo) / ((hi - lo) || 1)) * 100).toFixed(1) + '%');
  }

  function setSlider(r, v) {
    if (r.dataset.held || document.activeElement === r && r.matches(':active')) return;
    if (String(r.value) !== String(v)) r.value = String(v);
    paintFill(r);
  }

  function setSwitch(b, on) {
    var v = on ? 'true' : 'false';
    if (b.getAttribute('aria-checked') !== v) b.setAttribute('aria-checked', v);
  }

  function stateWords(t) {
    if (!t.on) return 'Off';
    return t.brightness != null && t.dims !== false ? 'On · ' + Math.max(1, Math.round(t.brightness)) + '%' : 'On';
  }

  function tintsOf(t) {
    if (t.tints) return t.tints;
    return t.tint ? [t.tint] : [];
  }

  function makeCard(key) {
    var id = 'hm' + (++seq);
    var kind = key.split(':')[0];
    var card = { key: key, node: el('div', 'hm-card'), sign: '' };
    card.node.setAttribute('role', 'listitem');
    card.node.setAttribute('data-key', key);
    var top = el('div', 'hm-top');
    var name = el('button', 'hm-name');
    name.type = 'button';
    var bulb = el('span', 'hm-bulb');
    bulb.appendChild(svg(BULB, 20));
    name.appendChild(bulb);
    var words = el('span', 'hm-words');
    card.title = el('span', 'hm-title');
    card.state = el('span', 'hm-state');
    words.appendChild(card.title);
    words.appendChild(card.state);
    name.appendChild(words);
    card.chev = svg(CHEVRON, 18);
    card.chev.setAttribute('class', 'hm-chev');
    name.appendChild(card.chev);
    card.name = name;
    top.appendChild(name);
    card.sw = sw('');
    card.sw.addEventListener('click', function () {
      var t = find(L.data, key);
      if (t) setOn(key, !t.on);
    });
    top.appendChild(card.sw);
    card.node.appendChild(top);
    card.dim = slider('');
    wireSlider(card.dim, function (v) { setBrightness(key, v); });
    card.node.appendChild(card.dim);
    var more = el('div', 'hm-more');
    more.id = id + 'more';
    var inner = el('div', 'hm-more-in');
    more.appendChild(inner);
    card.more = more;
    card.inner = inner;
    card.node.appendChild(more);
    name.setAttribute('aria-controls', more.id);
    name.addEventListener('click', function () {
      if (!card.expandable) return;
      L.open[key] = !L.open[key];
      paintOpen(card);
    });
    if (kind === 'light') card.node.classList.add('hm-single');
    return card;
  }

  function paintOpen(card) {
    var open = !!(L.open[card.key] && card.expandable);
    card.node.classList.toggle('open', open);
    card.name.setAttribute('aria-expanded', card.expandable ? (open ? 'true' : 'false') : 'false');
    if (!card.expandable) card.name.removeAttribute('aria-expanded');
    card.more.toggleAttribute('inert', !open);
  }

  function fillCard(card, key, t) {
    var node = card.node;
    if (card.title.textContent !== t.name) card.title.textContent = t.name;
    var words = stateWords(t);
    if (card.state.textContent !== words) card.state.textContent = words;
    card.sw.setAttribute('aria-label', t.name);
    setSwitch(card.sw, t.on);
    node.toggleAttribute('data-on', !!t.on);
    var tints = tintsOf(t);
    node.style.setProperty('--t1', tints[0] || '#ffcf8a');
    node.style.setProperty('--t2', tints[1] || tints[0] || '#ffcf8a');
    var dims = t.dims !== false;
    card.dim.hidden = !dims;
    card.dim.setAttribute('aria-label', 'Brightness of ' + t.name);
    if (t.brightness != null) setSlider(card.dim, Math.max(1, Math.round(t.brightness)));
    else paintFill(card.dim);
    card.dim.classList.toggle('off', !t.on);
    var isGroup = key.split(':')[0] !== 'light';
    // A room of one plug has nothing more to show than its card does.
    card.expandable = isGroup && !!((t.scenes && t.scenes.length) || (t.lights && t.lights.length > 1) ||
      t.colour || t.white);
    node.classList.toggle('hm-expandable', card.expandable);
    if (isGroup) fillMore(card, key, t);
    paintOpen(card);
  }

  /* What is inside a card: built again only when its scenes or lights changed, and otherwise
     only its values are put in. */
  function fillMore(card, key, t) {
    var sign = JSON.stringify([(t.scenes || []).map(function (s) { return [s.id, s.name]; }),
      (t.lights || []).map(function (l) { return [l.id, l.name, l.dims, l.colour, l.white]; }), t.colour, t.white]);
    if (sign !== card.sign) {
      card.sign = sign;
      buildMore(card, key, t);
    }
    (card.chips || []).forEach(function (c) {
      var s = (t.scenes || []).filter(function (o) { return o.id === c.id; })[0];
      var on = !!(s && s.active);
      c.node.classList.toggle('on', on);
      c.node.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (card.warm) {
      var ws = (t.lights || []).filter(function (l) { return l.on && l.mode === 'white' && l.mirek; });
      var mirek = (ws.length ? ws.reduce(function (a, l) { return a + l.mirek; }, 0) / ws.length : 0);
      if (mirek) setSlider(card.warm, Math.round(1e6 / mirek));
      else paintFill(card.warm);
    }
    (card.rows || []).forEach(function (row) {
      var l = (t.lights || []).filter(function (o) { return o.id === row.id; })[0];
      if (!l) return;
      setSwitch(row.sw, l.on);
      var w = stateWords(l);
      if (row.state.textContent !== w) row.state.textContent = w;
      row.node.toggleAttribute('data-on', !!l.on);
      row.node.style.setProperty('--t1', l.tint || '#ffcf8a');
      if (row.dim) {
        setSlider(row.dim, Math.max(1, Math.round(l.brightness || 1)));
        row.dim.classList.toggle('off', !l.on);
      }
    });
  }

  function buildMore(card, key, t) {
    var inner = card.inner;
    inner.textContent = '';
    card.chips = [];
    card.rows = [];
    card.warm = null;
    if (t.scenes && t.scenes.length) {
      var chips = el('div', 'hm-scenes');
      chips.setAttribute('role', 'group');
      chips.setAttribute('aria-label', 'Scenes in ' + t.name);
      t.scenes.forEach(function (s) {
        var b = el('button', 'hm-chip', s.name);
        b.type = 'button';
        b.addEventListener('click', function () { scene(key, s); });
        chips.appendChild(b);
        card.chips.push({ id: s.id, node: b });
      });
      inner.appendChild(chips);
    }
    if (t.colour || t.white) {
      var tones = el('div', 'hm-tones');
      if (t.colour) {
        var row = el('div', 'hm-swatches');
        row.setAttribute('role', 'group');
        row.setAttribute('aria-label', 'Colours for ' + t.name);
        SWATCHES.forEach(function (c) {
          var b = el('button', 'hm-swatch');
          b.type = 'button';
          b.style.setProperty('--c', c[1]);
          b.setAttribute('aria-label', c[0]);
          b.title = c[0];
          b.addEventListener('click', function () { setColour(key, c[1]); });
          row.appendChild(b);
        });
        // Any other colour, from the device's own picker.
        var other = el('label', 'hm-swatch hm-other');
        other.title = 'Another colour';
        var pick = el('input');
        pick.type = 'color';
        pick.value = '#ff8800';
        pick.setAttribute('aria-label', 'Another colour for ' + t.name);
        pick.addEventListener('change', function () { setColour(key, pick.value); });
        other.appendChild(pick);
        row.appendChild(other);
        tones.appendChild(row);
      }
      if (t.white) {
        var lo = t.mirek_max ? Math.max(WARMEST, Math.round(1e6 / t.mirek_max)) : WARMEST;
        var hi = t.mirek_min ? Math.min(COOLEST, Math.round(1e6 / t.mirek_min)) : COOLEST;
        var warm = el('input', 'hm-dim hm-warm');
        warm.type = 'range';
        warm.min = String(lo);
        warm.max = String(hi);
        warm.step = '50';
        warm.value = String(Math.round((lo + hi) / 2));
        warm.setAttribute('aria-label', 'Warm to cool white for ' + t.name);
        warm.style.setProperty('--w1', whiteHex(lo));
        warm.style.setProperty('--w2', whiteHex((lo + hi) / 2));
        warm.style.setProperty('--w3', whiteHex(hi));
        wireSlider(warm, function (v) { setKelvin(key, v); });
        paintFill(warm);
        card.warm = warm;
        tones.appendChild(warm);
      }
      inner.appendChild(tones);
    }
    if (t.lights && t.lights.length) {
      var list = el('ul', 'hm-each');
      list.setAttribute('aria-label', 'Lights in ' + t.name);
      t.lights.forEach(function (l) {
        var lkey = 'light:' + l.id;
        var li = el('li', 'hm-one');
        var top = el('div', 'hm-one-top');
        var dot = el('span', 'hm-dot');
        dot.setAttribute('aria-hidden', 'true');
        top.appendChild(dot);
        var words = el('span', 'hm-words');
        words.appendChild(el('span', 'hm-title', l.name));
        var state = el('span', 'hm-state');
        words.appendChild(state);
        top.appendChild(words);
        var s = sw(l.name);
        s.addEventListener('click', function () {
          var me = find(L.data, lkey);
          if (me) setOn(lkey, !me.on);
        });
        top.appendChild(s);
        li.appendChild(top);
        var dim = null;
        if (l.dims) {
          dim = slider('Brightness of ' + l.name);
          wireSlider(dim, function (v) { setBrightness(lkey, v); });
          li.appendChild(dim);
        }
        list.appendChild(li);
        card.rows.push({ id: l.id, node: li, sw: s, state: state, dim: dim });
      });
      inner.appendChild(list);
    }
  }

  /* ---- the section's life ---- */

  function lightsShown() {
    L.on = true;
    draw();
    read();
  }

  function lightsHidden() {
    L.on = false;
    clearTimeout(L.timer);
    L.timer = 0;
  }

  document.addEventListener('visibilitychange', function () {
    if (!L.on) return;
    if (visible()) read(); else { clearTimeout(L.timer); L.timer = 0; }
  });

  queue.push({
    id: 'lights', order: 10,
    mount: function (node) { L.root = node; node.classList.add('hm-lights-section'); },
    shown: lightsShown, hidden: lightsHidden
  });
})();
