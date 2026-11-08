/* Your Rouh, the card "Your Rouh's URL" (`rouh/relay.py`, `rouh/web/relay.py`): Connections, Phone
   until 7 November 2026, when step 141-17 moved it to Your Rouh and Petar's Correction 1 renamed the
   phone address its URL, with an (i) beside the title that says what kind of URL it is.

   The one place a Rouh's URL is: the address the relay gave it at birth, Turn on URL (where the
   chat's setup step "Reach me from my phone" sends the owner), the real state of the line to the
   relay (Connected, Reconnecting, Connecting, Off), this month's traffic beside the fair limit when
   the relay says it, the QR code that signs the owner in on the phone once, and Turn off.

   Drawn into `#phoneBody` from `/api/settings/phone`, read again every few seconds while it shows
   and the URL is on; Your Rouh (`birthpage.js`) tells it how the Rouh stands with rouh.land
   (`land`), and it tells Your Rouh's headline and tiles what it found. Anatomy tells it when it
   shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var P = { open: false, data: null, busy: false, error: '', link: null, timer: 0, seq: 0, seen: '', info: false,
            land: /** @type {{kind: string, admin: boolean, owner: string} | null} */ (null) };
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

  /* What Your Rouh says of its connection (`birthpage.js`), which changes what this card offers:
     a free or disconnected Rouh has no URL, a stopped one has it off, a member presses nothing. */
  function land() { return P.land || { kind: '', admin: true, owner: '' }; }
  function say(text, undo) { if (window.RouhBirth && window.RouhBirth.toast) window.RouhBirth.toast(text, undo); }
  function help(text) { return el('p', 'settings-help', text); }

  function draw() {
    var body = $('phoneBody');
    if (!body || !P.open) return;
    var d = P.data;
    var L = land();
    var page = el('div', 'hb-page yr-url');
    if (P.error) page.appendChild(el('p', 'hb-say bad', P.error));
    if (!d) {
      if (!P.error) page.appendChild(el('p', 'hb-empty', 'Reading…'));
      body.replaceChildren(page);
      tell();
      return;
    }
    var admin = d.admin && L.admin !== false;
    if (!d.relay) {
      page.appendChild(el('p', 'hb-empty', 'This installation has no relay, so it has no URL.'));
    } else if (L.kind === 'free' || L.kind === 'code' || L.kind === 'disconnected' || d.connected_choice === false && !d.hostname) {
      var none = el('div', 'yr-empty');
      none.appendChild(el('p', '', L.kind === 'disconnected'
        ? 'No URL while disconnected. It waits for this Rouh, and comes back when it connects again.'
        : 'No URL yet. It comes with connecting to rouh.land, above.'));
      none.appendChild(help(L.kind === 'disconnected' ? 'Nothing is open to the internet while it is disconnected.'
        : 'This ' + (d.independent || 'Independent Rouh') + ' opens nothing to the internet.'));
      page.appendChild(none);
    } else if (!d.hostname) {
      page.appendChild(el('p', 'hb-empty', d.pending || 'Its URL has not come from ' + d.service + ' yet.'));
      if (d.claim_error) page.appendChild(el('p', 'hb-say bad', d.claim_error));
      if (admin) {
        var again = el('div', 'hb-actions');
        again.appendChild(button(d.connected_choice ? 'Ask for it again' : 'Get its URL',
          d.connected_choice ? '' : 'primary', function () { call('POST', '/api/settings/phone/claim'); }));
        page.appendChild(again);
        page.appendChild(help('Nothing is open to the internet until you then turn it on.'));
      }
    } else {
      var addr = el('p', 'ph-address');
      var a = el('a', '', d.address.replace(/^https:\/\//, ''));
      a.href = d.address;
      a.target = '_blank';
      a.rel = 'noopener';
      addr.appendChild(a);
      page.appendChild(addr);
      if (L.kind === 'stopped') {
        var off = el('p', 'hb-state ph-state off');
        off.appendChild(el('span', 'hb-pulse'));
        off.appendChild(el('b', '', 'Off'));
        off.appendChild(el('span', 'ph-said', 'while rouh.land has stopped this Rouh.'));
        page.appendChild(off);
        body.replaceChildren(page);
        tell();
        return;
      }
      page.appendChild(stateLine(d));
      if (d.on && d.checked && !d.checked.ok && d.checked.error) {
        page.appendChild(el('p', 'hb-say bad', 'Checked from outside at ' + clock(d.checked.at) + ': ' + d.checked.error + '.'));
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
        page.appendChild(used);
      }
      if (!admin) {
        page.appendChild(el('p', 'yr-member', 'Only ' + (L.owner || 'its owner') + ', who owns this Rouh, can change this.'));
      } else {
        var acts = el('div', 'hb-actions');
        if (!d.on) {
          acts.appendChild(button('Turn on URL', 'primary', function () {
            P.link = null;
            call('POST', '/api/settings/phone/on').then(function (j) {
              if (j && !j.error) say('URL on.');
              tick();
            });
          }));
        } else {
          if (d.state === 'connected') {
            acts.appendChild(button(P.link ? 'New sign-in code' : 'Show sign-in code', 'primary', function () {
              call('POST', '/api/settings/phone/signin');
            }));
          }
          acts.appendChild(button('Turn off', 'yr-quiet', function () {
            P.link = null;
            call('POST', '/api/settings/phone/off').then(function (j) {
              if (j && !j.error) say('URL off. Phones signed in stop reaching it.');
            });
          }));
        }
        page.appendChild(acts);
        if (!d.on) page.appendChild(help('Turning it on lets your phone open this Rouh from anywhere. Only people who sign in can use it. Nothing is open to the internet until then.'));
      }
      if (d.on && P.link && d.state === 'connected') page.appendChild(qrCard(P.link));
      if (d.certificate && d.certificate.until) {
        var info = el('details', 'info ph-info');
        info.open = P.info;
        info.addEventListener('toggle', function () { P.info = info.open; });
        info.appendChild(el('summary', '', 'Locked end to end'));
        info.appendChild(el('p', 'hb-note', 'Locked with its own certificate, good until ' + day(d.certificate.until)
          + '. rouh.land’s relay passes it on by its name and never sees what is in it.'
          + (d.on && d.checked && d.checked.ok ? ' Checked from outside at ' + clock(d.checked.at) + '.' : '')));
        page.appendChild(info);
      } else if (d.on && d.certificate && d.certificate.error) {
        page.appendChild(el('p', 'hb-say bad', 'No certificate yet: ' + d.certificate.error));
      }
    }
    body.replaceChildren(page);
    tell();
  }

  /* Your Rouh's headline and URL tile follow this card. */
  function tell() { if (window.RouhBirth && window.RouhBirth.phone) window.RouhBirth.phone(P.data); }

  /* The (i) beside "Your Rouh's URL" (Correction 1 of 141-17): a small popover that says what kind
     of URL this is and what the relay is. It closes on Escape (focus back on the (i)), a click or
     tap outside it, or the (i) again. */
  (function info() {
    var ib = $('yrUrlInfoBtn'), pop = $('yrUrlInfo');
    if (!ib || !pop) return;
    function setOpen(o) {
      pop.hidden = !o;
      ib.setAttribute('aria-expanded', o ? 'true' : 'false');
      // Opened low on a phone's screen, it is brought up whole rather than left under the fold.
      if (o && pop.scrollIntoView) pop.scrollIntoView({ block: 'nearest' });
    }
    ib.addEventListener('click', function (e) { e.stopPropagation(); setOpen(pop.hidden); });
    document.addEventListener('click', function (e) {
      var t = /** @type {Node} */ (e.target);
      if (!pop.hidden && !pop.contains(t) && !ib.contains(t)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !pop.hidden) { e.stopPropagation(); setOpen(false); ib.focus(); }
    }, true);
  }());

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
    var pop = $('yrUrlInfo'), ib = $('yrUrlInfoBtn');
    if (pop) pop.hidden = true;
    if (ib) ib.setAttribute('aria-expanded', 'false');
  }

  /** Your Rouh's connection, as birthpage.js reads it. @param {{kind: string, admin: boolean, owner: string}} L */
  function landNow(L) {
    var before = JSON.stringify(P.land);
    P.land = L;
    if (before !== JSON.stringify(L)) draw();
  }

  window.RouhPhone = { shown: shownNow, hidden: hiddenNow, reload: load, land: landNow };
}());
