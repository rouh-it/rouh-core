/* Settings, Cloudflare, at /settings/cloudflare (`rouh/cloudflare.py`, `rouh/web/cloudflare.py`).

   Petar, 12 October 2026: "create an input field where I can save the token in
   settings, so it doesn't pass through the LLM. Remember I have one cloudflare
   token for [the first Rouh's domain] and now we are doing another one
   for Rouh.it".

   One row per zone. A zone with no token has a password field and Save; the
   token leaves the page in that one request, and the field is emptied at once,
   whatever the answer. The server checks it with Cloudflare before keeping it,
   and a refused one is shown with each check it failed. A kept token is drawn
   only as set, its last four, when it was saved and when it was last checked,
   with Replace, Check again and Remove. Under the zones, another can be added
   by its domain name.

   A token that lacks only a permission is kept, marked as failing, with what
   it is missing in its checks (Petar, 28 October 2026): the permission is
   added at Cloudflare and Check again pressed, with nothing pasted again.

   Nobody looks up a zone ID: the server finds it, and the account's, with the
   token, and shows both read only once it has. The Account ID can be given,
   when the zone is added or with its token, because Cloudflare's page for an
   account token shows it and checks that token with it (27 October 2026,
   Petar's rouh.page token; "zone id seems not required").

   A group of Settings, drawn into `#cloudflareBody` from `/api/settings/cloudflare`.
   Settings tells it when it shows and when it is left (`settingsPages` in
   app/runs.js). */
(function () {
  'use strict';

  var C = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: '',
            replacing: '', tried: null, autoChecked: {}, ids: {}, addAccount: '', addZone: '' };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, title) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) b.title = title;
    b.addEventListener('click', act);
    return b;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function slug(zone) { return String(zone).replace(/[^a-z0-9]+/gi, '-'); }

  function call(method, url, body) {
    var seq = ++C.seq;
    if (method === 'POST') C.busy = true;
    if (method === 'POST') draw();
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') C.busy = false;
          if (seq !== C.seq && method === 'GET') return j;
          if (j && j.zones) C.data = j;
          C.tried = (j && j.tried) || null;
          if (r.ok) {
            if (method === 'POST' && body && body.zone) delete C.ids[body.zone];
            if (method === 'POST' && body && body.zone && url.indexOf('/zone') > 0) { C.addAccount = ''; C.addZone = ''; }
            C.error = '';
            if (j && j.said) C.said = j.said;
            C.editing = '';
            C.replacing = '';
          } else {
            C.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') C.busy = false;
        C.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() {
    return call('GET', '/api/settings/cloudflare').then(function () { autoCheck(); });
  }
  function post(url, body) { C.said = ''; C.error = ''; return call('POST', url, body); }

  /* A token carried over from the server's settings has never been checked
     here: check it once, as the page first shows it. */
  function autoCheck() {
    var d = C.data;
    if (!d || !d.admin || !C.open || C.busy) return;
    d.zones.forEach(function (z) {
      if (z.token && z.token.from && !z.token.checked && !C.autoChecked[z.zone]) {
        C.autoChecked[z.zone] = true;
        post('/api/settings/cloudflare/check', { zone: z.zone });
      }
    });
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('cloudflareBody');
    if (!body || !C.open) return;
    body.setAttribute('aria-busy', C.busy ? 'true' : 'false');
    if (C.editing && C.data && !C.busy) {
      // Something is being typed: only the line that says how it went changes.
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = C.error || C.said;
        say.className = 'hb-say' + (C.error ? ' bad' : '');
        say.hidden = !(C.error || C.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (C.error ? ' bad' : ''), C.busy ? 'Asking Cloudflare…' : (C.error || C.said));
    say2.setAttribute('role', 'status');
    say2.hidden = !(C.busy || C.error || C.said);
    page.appendChild(say2);
    if (!C.data) {
      if (!C.error) page.appendChild(el('p', 'hb-empty', 'Reading the zones…'));
      return;
    }
    page.appendChild(aboutCard(C.data));
    page.appendChild(zonesCard(C.data));
    if (C.data.admin) page.appendChild(addCard());
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }

  function aboutCard(d) {
    var s = card('Cloudflare', '', 'cf-about');
    s.appendChild(el('p', 'settings-help', 'One API token for each zone, for Rouh’s own work on its DNS, ' +
      'certificates and settings. A token typed here goes straight to Rouh’s server, is checked with ' +
      'Cloudflare and kept sealed. No chat, model or log ever sees it, and this page shows only its last four.'));
    var perms = el('div', 'pay-perms cf-perms');
    perms.appendChild(el('h5', 'hb-h5', 'Make each token with'));
    var need = el('div', 'pay-perm write');
    need.appendChild(el('span', 'pay-perm-name', 'Needed'));
    need.appendChild(el('span', 'pay-perm-what', d.needed.join('; ')));
    perms.appendChild(need);
    var opt = el('div', 'pay-perm read');
    opt.appendChild(el('span', 'pay-perm-name', 'Optional'));
    opt.appendChild(el('span', 'pay-perm-what', d.optional.join('; ')));
    perms.appendChild(opt);
    perms.appendChild(el('p', 'settings-help', 'Zone Resources: Include, Specific zone, and that one zone only. ' +
      'In Cloudflare: My Profile, API Tokens, or Manage Account, API Tokens; then Create Token, Custom token. ' +
      'Rouh finds the zone ID with the token. For a token made under Manage Account, also paste the ' +
      'Account ID that page shows.'));
    s.appendChild(perms);
    return s;
  }

  function zonesCard(d) {
    var s = card('Zones', String(d.zones.length), 'cf-zones');
    if (!d.admin) {
      s.appendChild(el('p', 'settings-help', 'Only an administrator of this organisation adds, replaces or removes a token.'));
    }
    var list = el('ol', 'hb-list cf-list');
    d.zones.forEach(function (z) { list.appendChild(zoneRow(d, z)); });
    s.appendChild(list);
    return s;
  }

  function zoneRow(d, z) {
    var t = z.token;
    var li = el('li', 'hb-beat cf-zone');
    li.id = 'cf-' + slug(z.zone);
    li.setAttribute('aria-label', z.zone);
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what cf-name', z.zone));
    var pill = !t ? ['No token', ''] : t.ok === false ? ['Token set · check failed', 'failed'] : ['Token set', 'yes'];
    top.appendChild(el('span', 'hb-pill' + (pill[1] ? ' ' + pill[1] : ''), pill[0]));
    if (z.status && z.status !== 'active') top.appendChild(el('span', 'hb-beat-nums', 'zone ' + z.status));
    li.appendChild(top);

    var dl = el('dl', 'hb-ask-dl cf-fields');
    // An account not yet confirmed by Cloudflare is in the token form, where it can be changed.
    var rows = [['Zone ID', z.zone_id, 'cf-mono'], ['Account ID', z.zone_id || !d.admin ? z.account_id : '', 'cf-mono']];
    if (t) {
      rows.push(['Token', 'set, ending …' + t.last4, 'cf-mono']);
      rows.push(['Saved', t.saved + (t.from ? ', carried over from ' + t.from : ''), '']);
      rows.push(['Last checked', t.checked ? t.checked + (t.ok ? ', passed' : ', failed') : 'not checked here yet', '']);
    }
    rows.forEach(function (row) {
      if (!row[1]) return;
      dl.appendChild(el('dt', '', row[0]));
      dl.appendChild(el('dd', row[2], row[1]));
    });
    li.appendChild(dl);

    // What the last check found: the one just tried for this zone, or the kept token's.
    var checks = C.tried && C.tried.zone === z.zone ? C.tried.checks : (t && t.checks) || [];
    if (checks.length && (C.tried && C.tried.zone === z.zone || (t && t.ok === false))) li.appendChild(checkList(checks));

    if (!d.admin) return li;
    if (!t || C.replacing === z.zone) {
      li.appendChild(tokenForm(z, !!t));
    } else {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Replace', '', function () {
        C.replacing = z.zone;
        C.tried = null;
        C.said = ''; C.error = '';
        draw();
        var f = $('cfToken-' + slug(z.zone));
        if (f) f.focus();
      }, 'Save a new token for ' + z.zone + ' in place of this one'));
      // A token kept for want of a permission: once it is added at Cloudflare, this is the next press.
      acts.appendChild(button('Check again', t.ok === false ? 'primary' : '', function () {
        post('/api/settings/cloudflare/check', { zone: z.zone });
      }, 'Ask Cloudflare again whether this token still passes every check'));
      acts.appendChild(button('Remove', 'danger', function () {
        if (!window.confirm('Remove the ' + z.zone + ' token? Rouh forgets it; it still works at Cloudflare until you delete it there.')) return;
        post('/api/settings/cloudflare/remove', { zone: z.zone });
      }, 'Forget this token'));
      li.appendChild(acts);
    }
    if (!t && !z.starting) {
      var off = el('div', 'hb-actions');
      off.appendChild(button('Take off the list', '', function () {
        post('/api/settings/cloudflare/zone/forget', { zone: z.zone });
      }));
      li.appendChild(off);
    }
    return li;
  }

  function checkList(checks) {
    var ul = el('ul', 'cf-checks');
    ul.setAttribute('aria-label', 'What the check found');
    checks.forEach(function (c) {
      var li = el('li', 'cf-check ' + (c.ok ? 'ok' : c.optional ? 'opt' : 'bad'));
      li.appendChild(el('span', 'cf-mark', c.ok ? '✓' : c.optional ? '–' : '✗'));
      li.appendChild(el('span', 'cf-check-name', c.name));
      li.appendChild(el('span', 'cf-check-said', c.said));
      ul.appendChild(li);
    });
    return ul;
  }

  function tokenForm(z, replacing) {
    var f = el('form', 'hb-form cf-form');
    f.setAttribute('aria-label', 'Token for ' + z.zone);
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { C.editing = z.zone; });
    var label = el('label', 'hb-field wide');
    label.appendChild(el('span', '', replacing ? 'New API token for ' + z.zone : 'API token for ' + z.zone));
    var input = el('input');
    input.type = 'password';
    input.id = 'cfToken-' + slug(z.zone);
    input.setAttribute('autocomplete', 'off');
    input.spellcheck = false;
    input.maxLength = 300;
    input.placeholder = 'Paste the token';
    label.appendChild(input);
    f.appendChild(label);
    var account = accountField('cfAccountId-' + slug(z.zone),
                                 (C.ids[z.zone] || {}).account_id || z.account_id || '');
    if (!z.zone_id) f.appendChild(account.label);  // until Cloudflare has confirmed the account
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save');
    save.type = 'submit';
    save.disabled = C.busy;
    acts.appendChild(save);
    if (replacing) {
      acts.appendChild(button('Cancel', '', function () {
        input.value = '';
        C.replacing = ''; C.editing = ''; C.tried = null;
        draw();
      }));
    }
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (C.busy) return;
      var value = input.value;
      // The token leaves the page with this one request and is not kept in it.
      input.value = '';
      C.editing = '';
      if (!value.trim()) {
        C.error = 'Paste the token first.';
        draw();
        return;
      }
      var typed = C.ids[z.zone] = { account_id: account.input.value.trim() };
      post('/api/settings/cloudflare/token', { zone: z.zone, token: value, account_id: typed.account_id });
      value = '';
    });
    return f;
  }

  /* The Cloudflare account's ID, as its token page shows it: optional. */
  function accountField(id, value) {
    var l = el('label', 'hb-field wide');
    l.appendChild(el('span', '', 'Account ID (optional)'));
    var i = el('input', 'cf-mono');
    i.type = 'text';
    i.id = id;
    i.value = value;
    i.maxLength = 64;
    i.spellcheck = false;
    i.setAttribute('autocomplete', 'off');
    i.setAttribute('autocapitalize', 'off');
    i.placeholder = '32 letters and digits';
    l.appendChild(i);
    return { label: l, input: i };
  }

  function addCard() {
    var s = card('Add a zone', '', 'cf-add');
    var f = el('form', 'hb-form');
    f.setAttribute('aria-label', 'Add a zone');
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { C.editing = 'add'; });
    var label = el('label', 'hb-field wide');
    label.appendChild(el('span', '', 'Domain name'));
    var input = el('input');
    input.type = 'text';
    input.id = 'cfAddZone';
    input.maxLength = 253;
    input.placeholder = 'example.com';
    input.value = C.addZone || '';
    input.spellcheck = false;
    input.setAttribute('autocomplete', 'off');
    label.appendChild(input);
    f.appendChild(label);
    var account = accountField('cfAddAccount', C.addAccount || '');
    f.appendChild(account.label);
    var acts = el('div', 'hb-actions');
    var add = el('button', 'ctl small', 'Add zone');
    add.type = 'submit';
    acts.appendChild(add);
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var name = C.addZone = input.value;
      C.addAccount = account.input.value.trim();
      C.editing = '';
      post('/api/settings/cloudflare/zone', { zone: name, account_id: C.addAccount }).then(function (j) {
        if (j && j.ok) input.value = '';
      });
    });
    s.appendChild(f);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (C.open) return;
    C.open = true;
    C.said = '';
    C.error = '';
    C.editing = '';
    C.replacing = '';
    C.tried = null;
    C.autoChecked = {};
    draw();
    load();
  }

  function hiddenNow() {
    C.open = false;
    C.editing = '';
    C.replacing = '';
    // Nothing typed into a token field stays in the page once it is left.
    var body = $('cloudflareBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { i.value = ''; });
  }

  window.RouhCloudflare = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
