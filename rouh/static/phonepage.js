/* Settings, Connections, Phone, at /anatomy/connections/phone (`rouh/relay.py`, `rouh/web/relay.py`).

   The one place a Rouh's phone address is: the address the relay gave it at birth, the
   switch that opens it ("Reach me from my phone", where the chat's setup step sends the
   owner), the real state of the line to the relay (Connected, Reconnecting, Connecting,
   Off), this month's traffic beside the fair limit when the relay says it, and the QR code
   that signs the owner in on the phone once.

   Drawn into `#phoneBody` from `/api/settings/phone`, read again every few seconds while
   it shows and the address is on. Settings tells it when it shows and when it is left
   (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var P = { open: false, data: null, busy: false, error: '', link: null, timer: 0, seq: 0, seen: '', info: false };
  var EVERY = 3000;

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
    b.disabled = P.busy;
    b.addEventListener('click', act);
    return b;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function gb(bytes) {
    var n = bytes / 1e9;
    return (n >= 10 ? Math.round(n) : Math.round(n * 10) / 10) + ' GB';
  }
  function day(at) {
    try {
      return new Date(at * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' });
    } catch (err) { return ''; }
  }
  function clock(at) {
    try {
      return new Date(at * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch (err) { return ''; }
  }

  function call(method, url) {
    var seq = ++P.seq;
    if (method === 'POST') { P.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? '{}' : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') P.busy = false;
          if (seq !== P.seq && method === 'GET') return j;
          var error = r.ok ? '' : ((j && j.error) || 'The server said ' + r.status + '.');
          // A look that found nothing new leaves the page as it is (B1).
          var seen = JSON.stringify([j, error]);
          if (method === 'GET' && seen === P.seen) return j;
          P.seen = seen;
          if (j && j.link) P.link = j;
          else if (j && 'state' in j) P.data = j;
          P.error = error;
          draw();
          return j;
        });
      })
      .catch(function () {
        P.busy = false;
        P.error = 'Rouh could not be reached.';
        draw();
        return null;
      });
  }

  function load() { return call('GET', '/api/settings/phone'); }

  var WORDS = {
    connected: ['Connected', 'yes'],
    reconnecting: ['Reconnecting', 'wait'],
    connecting: ['Connecting', 'wait'],
    off: ['Off', 'no']
  };

  function stateLine(d) {
    var w = WORDS[d.state] || WORDS.off;
    var line = el('p', 'hb-state ph-state ' + d.state);
    line.appendChild(el('span', 'hb-pulse'));
    line.appendChild(el('b', '', w[0]));
    if (d.said) line.appendChild(el('span', 'ph-said', d.said));
    return line;
  }

  function draw() {
    var body = $('phoneBody');
    if (!body || !P.open) return;
    var d = P.data;
    var page = el('div', 'hb-page');
    if (P.error) page.appendChild(el('p', 'hb-say bad', P.error));
    if (!d) {
      if (!P.error) page.appendChild(el('p', 'hb-empty', 'Reading…'));
      body.replaceChildren(page);
      return;
    }
    var s = el('section', 'setting-card hb-card ph-card');
    s.appendChild(el('h4', 'hb-h', 'Reach me from my phone'));
    if (!d.relay) {
      s.appendChild(el('p', 'hb-empty', 'This installation has no relay, so it has no phone address.'));
    } else if (d.connected_choice === false) {
      s.appendChild(el('p', 'hb-empty', 'This Rouh is on its own, so it opens no address to the internet.'));
    } else if (!d.hostname) {
      s.appendChild(el('p', 'hb-empty', d.pending || (d.connected_choice
        ? 'Its address has not come from ' + d.service + ' yet.'
        : 'This Rouh was set up before it could choose to be Connected, so it has no phone address yet.')));
      if (d.claim_error) s.appendChild(el('p', 'hb-say bad', d.claim_error));
      if (d.admin && (d.connected_choice || d.account)) {
        // Connected, or already linked to its owner's account on the service: the address is asked for.
        if (!d.connected_choice) {
          s.appendChild(el('p', 'hb-note', 'It is linked to your account on ' + d.service + ', so it can have its own '
            + 'address. Nothing is open to the internet until you then press Reach me from my phone.'));
        }
        var again = el('div', 'hb-actions');
        again.appendChild(button(d.connected_choice ? 'Ask for it again' : 'Get its phone address',
          d.connected_choice ? '' : 'primary', function () { call('POST', '/api/settings/phone/claim'); }));
        s.appendChild(again);
      } else if (d.admin && d.account_url) {
        // A Rouh born before its first run asked: linked to its owner's rouh.land account the way the
        // Rouh profile links it, keeping its name; the link gives it its address (relay.linked_later).
        s.appendChild(el('p', 'hb-note', 'Sign in to your account on ' + d.service + ' and link this Rouh to it. '
          + 'It keeps its name, and gets its own address. Nothing is open to the internet until you then '
          + 'press Reach me from my phone.'));
        var go = el('a', 'ctl small primary', 'Sign in to ' + d.service + ' to link it');
        go.href = d.account_url + (d.account_url.indexOf('?') < 0 ? '?' : '&') + 'rouh=' + encodeURIComponent(location.origin);
        var link = el('div', 'hb-actions');
        link.appendChild(go);
        s.appendChild(link);
      }
    } else {
      var addr = el('p', 'ph-address');
      var a = el('a', '', d.address.replace(/^https:\/\//, ''));
      a.href = d.address;
      a.target = '_blank';
      a.rel = 'noopener';
      addr.appendChild(a);
      s.appendChild(addr);
      s.appendChild(stateLine(d));
      if (d.on && d.checked && !d.checked.ok && d.checked.error) {
        s.appendChild(el('p', 'hb-say bad', 'Checked from outside at ' + clock(d.checked.at) + ': ' + d.checked.error + '.'));
      }
      if (d.on && d.limit_bytes && d.usage) {
        var used = el('div', 'ph-usage');
        used.appendChild(el('span', '', 'This month ' + gb(d.usage.bytes) + ' of ' + gb(d.limit_bytes)
          + (d.usage.slowed ? ', slowed until the month ends' : '')));
        var bar = el('span', 'ph-bar');
        var fill = el('span', 'ph-fill' + (d.usage.slowed ? ' slowed' : ''));
        fill.style.width = Math.min(100, Math.round(100 * d.usage.bytes / d.limit_bytes)) + '%';
        bar.appendChild(fill);
        used.appendChild(bar);
        s.appendChild(used);
      }
      if (!d.on) {
        s.appendChild(el('p', 'hb-note', 'Nothing is open to the internet until you turn it on.'));
      }
      if (d.admin) {
        var acts = el('div', 'hb-actions');
        if (!d.on) {
          acts.appendChild(button('Reach me from my phone', 'primary', function () {
            P.link = null;
            call('POST', '/api/settings/phone/on').then(tick);
          }));
        } else {
          if (d.state === 'connected') {
            acts.appendChild(button(P.link ? 'New sign-in code' : 'Sign in on my phone', 'primary', function () {
              call('POST', '/api/settings/phone/signin');
            }));
          }
          acts.appendChild(button('Turn off', '', function () {
            P.link = null;
            call('POST', '/api/settings/phone/off');
          }));
        }
        s.appendChild(acts);
      }
      if (d.on && P.link && d.state === 'connected') s.appendChild(qrCard(P.link));
      if (d.certificate && d.certificate.until) {
        var info = el('details', 'info ph-info');
        info.open = P.info;
        info.addEventListener('toggle', function () { P.info = info.open; });
        info.appendChild(el('summary', '', 'Locked end to end'));
        info.appendChild(el('p', 'hb-note', 'Locked with its own certificate, good until ' + day(d.certificate.until)
          + '. The relay passes it on by its name and never sees what is in it.'
          + (d.on && d.checked && d.checked.ok ? ' Checked from outside at ' + clock(d.checked.at) + '.' : '')));
        s.appendChild(info);
      } else if (d.on && d.certificate && d.certificate.error) {
        s.appendChild(el('p', 'hb-say bad', 'No certificate yet: ' + d.certificate.error));
      }
    }
    page.appendChild(s);
    body.replaceChildren(page);
  }

  function qrCard(link) {
    var box = el('div', 'ph-qr');
    var pic = el('div', 'ph-qr-pic');
    pic.setAttribute('role', 'img');
    pic.setAttribute('aria-label', 'QR code that signs you in on your phone');
    pic.innerHTML = link.qr;
    box.appendChild(pic);
    var words = el('div', 'ph-qr-words');
    words.appendChild(el('p', '', 'Scan it with your phone\'s camera. It signs you in once, for ten minutes, until '
      + clock(link.until) + '.'));
    words.appendChild(el('p', 'hb-note', 'Then use Share, Add to Home Screen, to keep it like an app.'));
    box.appendChild(words);
    return box;
  }

  function tick() {
    clearTimeout(P.timer);
    if (!P.open) return;
    P.timer = setTimeout(function () {
      if (!P.open) return;
      var on = P.data && P.data.on;
      (on ? load() : Promise.resolve()).then(tick);
    }, EVERY);
  }

  function shownNow() {
    if (P.open) return;
    P.open = true;
    P.error = '';
    P.seen = '';
    draw();
    load().then(tick);
  }

  function hiddenNow() {
    P.open = false;
    P.link = null;
    clearTimeout(P.timer);
  }

  window.RouhPhone = { shown: shownNow, hidden: hiddenNow, reload: load };
}());
