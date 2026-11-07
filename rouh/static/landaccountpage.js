/* Rouh Land Account, Your profile, at /anatomy/rouh-land/your-profile (`rouh/landaccount.py`,
   `rouh/web/landaccount.py`), and the first card of its Gene Pool section.

   Petar, 4 November 2026, of the first version: "in the page for my profile I see ROUH information
   that should not be the case", and "these buttons are weird. each one of them needs to be really
   well thought out with great interface ... what they do, why do them, in what situations, how do
   we make sure people understand what happens when you click them". So Your profile is the person
   and their rouh.land account, nothing of the Rouh's own (its name, id, address, since, last check
   are Rouh profile's), and it says two things: whether you have a rouh.land account this Rouh
   knows of, and whether this Rouh is connected to it; the account's email and role only when
   rouh.land tells this Rouh, which today it does not.

   The controls, each shown only where it makes sense (and every other one there was is gone):

   - "Sign up or sign in on rouh.land to connect this Rouh" - the one main action while this Rouh is
     in no rouh.land account (not born yet, born on its own, or registered with no account), for an
     administrator. It goes to rouh.land's door in this tab; there you sign up or sign in, and
     rouh.land sends you back with a code that Rouh profile uses to connect it (and, before its
     birth, to give it its name at the same moment). Beside it, one line on what connecting gives:
     the Gene Pool and the model list. A member who is not an administrator is told who connects it,
     with no button, because the press would be refused.
   - "Manage your account on rouh.land" - a quiet link, only once this Rouh is in your account, to
     your account page there, in a new tab, which it says. No sign-up call to action then: you have
     an account.
   - "Try again" - only beside an error that a new ask might clear (rouh.land could not be reached,
     or did not accept the last check), for an administrator. It asks rouh.land at once.
   - When rouh.land no longer recognises this Rouh, one plain sentence and nothing to press: the
     keys are opaque (Petar, 4 November 2026).
   - No "Check with rouh.land now": the page asks rouh.land by itself as it opens, at most once in
     five minutes, and the gene log's beat asks every six hours; the result is said only when
     something is wrong. No "Its Rouh profile": Rouh profile is the next row of this group's
     navigation. No "Signing in, out and connecting again" card: the states and the one action in
     each say it.

   The Gene Pool's first card says where this Rouh stands in the Pool on rouh.land, from
   /api/birth, with the Pool's own page a press away; the registry and the lab under it are
   genespage.js's.

   Anatomy tells each when it shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var A = { open: false, data: null, busy: false, error: '', checked: false };
  var P = { open: false, data: null, error: '' };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function get(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Time-Zone': deviceZone() } })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (!r.ok) throw new Error((j && j.error) || 'The server said ' + r.status + '.');
          return j;
        });
      });
  }
  function card(title, sub) {
    var s = el('section', 'setting-card hb-card la-card');
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }
  function help(text) { return el('p', 'settings-help', text); }
  function readout(rows) {
    var dl = el('dl', 'readout la-readout');
    rows.forEach(function (r) {
      var d = el('div');
      d.appendChild(el('dt', null, r[0]));
      var dd = el('dd', r[2] ? 'mono' : '', r[1]);
      d.appendChild(dd);
      dl.appendChild(d);
    });
    return dl;
  }
  /* An address inside Rouh: a plain press goes there in the page (`goToAddress`, handed to
     genespage.js as RouhGenesHost), Cmd-click opens a tab. */
  function inapp(text, href, cls) {
    var a = el('a', cls || 'ctl small', text);
    a.href = href;
    a.setAttribute('data-inapp', '');
    a.addEventListener('click', function (e) {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (window.RouhGenesHost) window.RouhGenesHost.go(href);
      else location.href = href;
    });
    return a;
  }
  function out(text, href, cls) {
    var a = el('a', cls || 'ctl small', text);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    return a;
  }
  function route(id, fallback) {
    return (window.RouhNav && window.RouhNav.route(id)) || fallback;
  }

  /* ---- Your profile ---- */

  /** @param {boolean} [keep] keep what a press just said, its refusal too */
  function load(keep) {
    return get('/api/rouh-land/account').then(function (j) {
      if (j) { A.data = j; if (!keep) A.error = ''; }
      draw();
      // The page's own ask of rouh.land, once as it opens; said only if something is wrong.
      if (j && j.check_due && !A.checked) { A.checked = true; check(false); }
    }).catch(function (e) { A.error = e.message || 'Rouh could not be reached.'; draw(); });
  }

  /** @param {boolean} retry pressed beside an error, so asked whatever the last ask was */
  function check(retry) {
    A.busy = true;
    if (retry) draw();
    fetch('/api/rouh-land/account/check', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                                            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(),
                                                       'X-Time-Zone': deviceZone() },
                                            body: JSON.stringify({ retry: !!retry }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (got) {
        A.busy = false;
        if (got.ok && got.j && 'connected' in got.j) { A.data = got.j; A.error = ''; }
        else if (retry) A.error = (got.j && got.j.error) || 'rouh.land could not be asked.';
        draw();
      })
      .catch(function () { A.busy = false; if (retry) A.error = 'Rouh could not be reached.'; draw(); });
  }

  function doorHref(d) {
    var base = d.door || '';
    if (!base) return '';
    return base + (base.indexOf('?') < 0 ? '?' : '&') + 'rouh=' + encodeURIComponent(location.origin) +
      (d.sign_in_email ? '&email=' + encodeURIComponent(d.sign_in_email) : '');
  }

  /* Stop being connected: the owner keeps signing in here with the email they have, Gene Pool
     sharing stops, and the rouh.land account stays until it is deleted there (`birth.disconnect`). */
  function disconnect() {
    if (!window.confirm('Disconnect this Rouh from rouh.land? You keep signing in here with your email. ' +
      'Gene Pool sharing stops. Your rouh.land account stays until you delete it there.')) return;
    A.busy = true;
    draw();
    fetch('/api/birth/disconnect', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                                     headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(),
                                                'X-Time-Zone': deviceZone() }, body: '{}' })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (got) {
        A.busy = false;
        A.error = got.ok ? '' : ((got.j && got.j.error) || 'It could not be disconnected.');
        load(true);
      })
      .catch(function () { A.busy = false; A.error = 'Rouh could not be reached.'; draw(); });
  }

  function problemBox(d) {
    var p = d.problem;
    var box = el('div', 'la-problem');
    box.setAttribute('role', 'alert');
    box.appendChild(el('p', 'hb-say bad', p.said));
    if (!d.admin) {
      box.appendChild(help('An administrator of this Rouh can put it right.'));
      return box;
    }
    if (p['do'] !== 'retry') return box;
    var acts = el('div', 'hb-actions');
    var b = el('button', 'ctl small', A.busy ? 'Asking rouh.land…' : 'Try again');
    b.type = 'button';
    b.disabled = A.busy;
    b.addEventListener('click', function () { check(true); });
    acts.appendChild(b);
    box.appendChild(acts);
    return box;
  }

  function draw() {
    var body = $('landAccountBody');
    if (!body || !A.open) return;
    body.textContent = '';
    var page = el('div', 'hb-page la-page');
    body.appendChild(page);
    if (A.error) page.appendChild(el('p', 'hb-say bad', A.error));
    var d = A.data;
    if (!d) { if (!A.error) page.appendChild(help('Reading…')); return; }

    var s = card('Your rouh.land account', d.connected ? 'connected' : 'not connected');
    page.appendChild(s);
    if (d.problem) s.appendChild(problemBox(d));
    var rows = [
      ['rouh.land account', d.has_account ? 'Yes' : 'None connected to this Rouh', false],
      ['This Rouh', d.connected ? 'Connected to your account' : 'Not connected', false],
    ];
    if (d.sign_in_email) rows.push(['Email', d.sign_in_email, true]);
    if (d.role) rows.push(['Your role there', d.role, false]);
    s.appendChild(readout(rows));
    if (d.sign_in_email) s.appendChild(help(d.sign_in_label + '.' + (d.connected
      ? ' To change it, change it on rouh.land: this Rouh follows.'
      : ' Connect with it, and the same email runs both.')));

    var acts = el('div', 'hb-actions');
    if (d.connected) {
      var manage = out('Manage your account on rouh.land', d.account_url, 'la-quiet');
      manage.setAttribute('aria-label', 'Manage your account on rouh.land (opens in a new tab)');
      acts.appendChild(manage);
      acts.appendChild(el('span', 'la-note', 'Opens in a new tab.'));
      s.appendChild(acts);
      // Disconnect, on Rouh profile until 4 November 2026: Rouh profile is the Rouh's name, nickname,
      // birthday and one line about rouh.land, and being in an account is this page's.
      if (d.admin) {
        var off = el('div', 'hb-actions');
        var b = el('button', 'ctl small danger', A.busy ? 'Working…' : 'Disconnect from rouh.land');
        b.type = 'button';
        b.disabled = A.busy;
        b.addEventListener('click', disconnect);
        off.appendChild(b);
        s.appendChild(off);
      }
      return;
    }
    if (!d.admin) {
      s.appendChild(help('Only an administrator of this Rouh connects it to a rouh.land account.'));
      return;
    }
    s.appendChild(help('Connecting gives this Rouh the Gene Pool, where Rouhs share what they learn, and the ' +
      'list of models every Rouh follows.'));
    var href = doorHref(d);
    if (href) {
      var go = el('a', 'ctl small primary la-go', 'Sign up or sign in on rouh.land to connect this Rouh');
      go.href = href;
      acts.appendChild(go);
      s.appendChild(acts);
      s.appendChild(help(d.born ? 'rouh.land opens here, and brings you back with a code that connects it.'
        : 'rouh.land opens here, and brings you back with a code. Connecting is this Rouh\u2019s birth: rouh.land ' +
          'gives it its own name.'));
    }
  }

  /* Told again while it is already showing (Anatomy reloads its sections), it reads again and
     keeps what a press just said. */
  function shownNow() {
    var again = A.open;
    A.open = true;
    if (!again) A.checked = false;
    draw();
    load(again);
  }
  function hiddenNow() { A.open = false; A.error = ''; }

  /* ---- The Gene Pool's standing card ---- */

  function poolLoad() {
    return get('/api/birth').then(function (j) {
      if (j) { P.data = j; P.error = ''; }
      poolDraw();
    }).catch(function (e) { P.error = e.message || 'Rouh could not be reached.'; poolDraw(); });
  }

  function poolDraw() {
    var body = $('poolStandBody');
    if (!body || !P.open) return;
    body.textContent = '';
    var page = el('div', 'hb-page la-page');
    body.appendChild(page);
    var s = card('This Rouh in the Gene Pool');
    page.appendChild(s);
    if (P.error) { s.appendChild(el('p', 'hb-say bad', P.error)); return; }
    var d = P.data;
    if (!d) { s.appendChild(help('Reading…')); return; }
    var pool = d.pool || {};
    var r = d.rouh || null;
    s.appendChild(help(!r ? 'A free Rouh is not in the Gene Pool: it joins by itself when it is connected to rouh.land, which is its birth.'
      : !r.connected ? r.name + ' is not registered on rouh.land, so it is not in the Gene Pool.'
      : pool.on ? r.name + ' is in the Gene Pool on rouh.land.' : 'The Gene Pool is switched off for this Rouh.'));
    s.appendChild(readout([
      ['Outgoing genes', pool.outgoing || '-', false],
      ['Incoming genes', pool.incoming || '-', false],
    ]));
    var acts = el('div', 'hb-actions');
    acts.appendChild(inapp('Open the Gene Pool', pool.route || route('gene-pool', '/evolution/pool')));
    s.appendChild(acts);
    s.appendChild(help('The genes this Rouh gives and takes are chosen on the Gene Pool’s own page. Below: a gene registry ' +
      'of your own, and the lab its genes arrive in.'));
  }

  window.RouhLandAccount = { shown: shownNow, hidden: hiddenNow, reload: function () { return load(); } };
  window.RouhPoolStand = {
    shown: function () { P.open = true; poolDraw(); poolLoad(); },
    hidden: function () { P.open = false; },
  };
})();
