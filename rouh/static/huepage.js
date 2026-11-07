/* Settings, Connections, Philips Hue, at /anatomy/connections/hue (`rouh/hue.py`, `rouh/web/hue.py`).

   Petar, 16 October 2026: "can you build the cloud integration", for Hue lights through
   the Hue cloud.

   The connection first: not connected, connected to which bridge and when it was last reached, or
   lapsed and needing a sign-in again; with Connect, which goes to Hue's own sign-in in this
   browser and comes back here, or Check now and Disconnect. Signed in while the bridge's link
   button could not be pressed through the cloud (17 October 2026, HTTP 521), it asks for the
   bridge's own button, with Try again, which waits up to 30 seconds for it. Under it the organisation's Hue app:
   until it is set, three fields for its client id, client secret and app id, with an (i) saying
   where they come from and which callback address to register; once set, what is kept, with
   Change and Remove. The secret leaves the page in the one request that saves it.

   A section of Anatomy, drawn into `#hueBody` from `/api/settings/hue`. Anatomy tells it when it
   shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var S = { open: false, data: null, busy: false, busyText: '', error: '', said: '', seq: 0, editing: false,
            changing: false, fromHue: false, typed: null };
  var BUTTON_LINE = 'Press the round button on top of your Hue bridge, then press Try again within 30 seconds.';

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
    b.disabled = S.busy;
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

  function call(method, url, body) {
    var seq = ++S.seq;
    if (method === 'POST') { S.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = false;
          if (seq !== S.seq && method === 'GET') return j;
          // Read again and nothing changed: the page is left exactly as it is.
          var same = method === 'GET' && r.ok && S.data && !S.error && JSON.stringify(S.data) === JSON.stringify(j);
          if (j && 'connected' in j) S.data = j;
          if (same) return j;
          if (r.ok) {
            // What the way back from Hue said stays until something is pressed here.
            if (method === 'POST' || !S.fromHue) S.error = '';
            if (j && j.said) S.said = j.said;
            if (method === 'POST') { S.editing = false; S.changing = false; S.typed = null; }
          } else {
            S.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return j;
        });
      })
      .catch(function () {
        if (method === 'POST') S.busy = false;
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
      });
  }
  function load() { return call('GET', '/api/settings/hue'); }
  function post(url, body, busyText) {
    S.said = ''; S.error = ''; S.fromHue = false; S.busyText = busyText || '';
    return call('POST', url, body);
  }

  /* What the way back from Hue's sign-in said (`?hue=said|error&say=...`), shown once and taken
     out of the address, so a reload does not say it again. */
  function takeReturn() {
    var q;
    try { q = new URLSearchParams(location.search); } catch (err) { return; }
    var kind = q.get('hue');
    if (!kind) return;
    var say = q.get('say') || '';
    if (kind === 'error') { S.error = say; S.said = ''; } else { S.said = say; S.error = ''; }
    S.fromHue = true;
    q.delete('hue'); q.delete('say');
    var rest = q.toString();
    try { history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash); }
    catch (err) { /* the address keeps it; nothing else depends on it */ }
  }

  /* ---- the (i): what a field means, opened in place ---- */

  var INFO_SVG = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.4" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="6.2" r="1.15" fill="currentColor"/>' +
    '<path d="M10 9v5.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var infoSeq = 0;
  function info(label, fill) {
    var id = 'hueInfo' + (++infoSeq);
    var b = el('button', 'sk-i');
    b.type = 'button';
    b.innerHTML = INFO_SVG;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', id);
    var note = el('div', 'sk-guide');
    note.id = id;
    note.hidden = true;
    fill(note);
    b.addEventListener('click', function () {
      note.hidden = !note.hidden;
      b.setAttribute('aria-expanded', note.hidden ? 'false' : 'true');
    });
    return { button: b, note: note };
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('hueBody');
    if (!body || !S.open) return;
    body.setAttribute('aria-busy', S.busy ? 'true' : 'false');
    if (S.editing && S.data && !S.busy) {
      // Something is being typed: only the line that says how it went changes.
      var say = body.querySelector('.hb-say');
      if (say) {
        say.textContent = S.error || S.said;
        say.className = 'hb-say' + (S.error ? ' bad' : '');
        say.hidden = !(S.error || S.said);
      }
      return;
    }
    body.textContent = '';
    var page = el('div', 'hb-page');
    body.appendChild(page);
    var say2 = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.busy ? (S.busyText || 'Asking Hue…') : (S.error || S.said));
    say2.setAttribute('role', 'status');
    say2.hidden = !(S.busy || S.error || S.said);
    page.appendChild(say2);
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the connection…'));
      return;
    }
    page.appendChild(statusCard(S.data));
    page.appendChild(appCard(S.data));
  }

  function stateOf(d) {
    if (d.lapsed) return ['Sign in again', 'failed'];
    if (d.connected) return ['Connected', 'yes'];
    if (d.needs_button) return ['Not linked', 'blocking'];
    return ['Not connected', ''];
  }

  function statusCard(d) {
    var s = el('section', 'setting-card hb-card hue-status');
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what', d.bridge || 'Philips Hue'));
    var st = stateOf(d);
    top.appendChild(el('span', 'hb-pill' + (st[1] ? ' ' + st[1] : ''), st[0]));
    s.appendChild(top);
    var rows = [];
    if (d.lapsed) rows.push(['Why', d.lapsed_said || 'The sign-in with Hue can no longer be renewed.']);
    if (d.connected || d.lapsed) {
      if (d.since) rows.push(['Connected', d.since]);
      if (d.reached) rows.push(['Last reached', d.reached]);
    }
    if (d.needs_button) s.appendChild(el('p', 'hue-button-line', BUTTON_LINE));
    if (rows.length) {
      var dl = el('dl', 'hb-ask-dl sk-fields');
      rows.forEach(function (r) {
        dl.appendChild(el('dt', '', r[0]));
        dl.appendChild(el('dd', '', r[1]));
      });
      s.appendChild(dl);
    }
    var acts = el('div', 'hb-actions');
    var ready = d.app && d.app.ready;
    if (d.needs_button) {
      acts.appendChild(button('Try again', 'primary hue-try', function () {
        post('/api/settings/hue/link', {}, 'Waiting for the bridge…');
      }, 'Ask the bridge for its key, for up to 30 seconds'));
    } else if (!d.connected) {
      // Until the Hue app below is set there is nothing to sign in with, so no Connect.
      if (ready) {
        var go = el('a', 'ctl small primary hue-connect', d.lapsed ? 'Connect again' : 'Connect');
        go.href = '/auth/hue/start';
        go.title = 'Sign in to your Hue account, on Hue’s own page';
        if (S.busy) {
          go.setAttribute('aria-disabled', 'true');
          go.classList.add('off');
          go.addEventListener('click', function (e) { e.preventDefault(); });
        }
        acts.appendChild(go);
      }
    } else {
      acts.appendChild(button('Check now', '', function () { post('/api/settings/hue/check', {}); },
        'Reach the bridge through the Hue cloud now'));
    }
    if (d.connected || d.lapsed || d.needs_button) {
      acts.appendChild(button('Disconnect', 'danger', function () {
        if (!window.confirm('Disconnect Philips Hue? Rouh forgets your Hue sign-in and its key to the bridge.')) return;
        post('/api/settings/hue/disconnect', {});
      }, 'Forget your Hue sign-in and the bridge’s key'));
    }
    if (acts.childNodes.length) s.appendChild(acts);
    return s;
  }

  function appInfo(d) {
    return info('Where the Hue app comes from', function (note) {
      note.appendChild(el('p', '', 'Register a Remote Hue API app at developers.meethue.com, under My Apps. Hue shows its client id, client secret and app id there.'));
      var p = el('p', 'hue-cb');
      p.appendChild(document.createTextNode('Its callback URL must be exactly '));
      var code = el('code', 'hue-cb-url', d.callback || '');
      p.appendChild(code);
      note.appendChild(p);
      var copy = button('Copy the callback URL', '', function () {
        if (!navigator.clipboard) { S.error = 'This browser would not copy it.'; draw(); return; }
        navigator.clipboard.writeText(d.callback || '').then(function () {
          copy.textContent = 'Copied';
        }, function () { S.error = 'This browser would not copy it.'; draw(); });
      });
      copy.disabled = false;
      note.appendChild(copy);
    });
  }

  function appCard(d) {
    var s = el('section', 'setting-card hb-card hue-app');
    var head = el('h4', 'hb-h sk-label', 'Hue app');
    var tip = appInfo(d);
    head.appendChild(tip.button);
    s.appendChild(head);
    s.appendChild(tip.note);
    if (!d.admin) {
      s.appendChild(el('p', 'settings-help', d.app && d.app.ready ? 'Set up by an administrator of this organisation.'
        : 'An administrator of this organisation sets up the Hue app first.'));
      return s;
    }
    if (d.app && d.app.ready && !S.changing) {
      var dl = el('dl', 'hb-ask-dl sk-fields');
      [['Client id', d.app.client_id], ['Client secret', 'set, ending …' + d.app.secret_last4],
       ['App id', d.app.app_id || 'Not set']].forEach(function (r) {
        dl.appendChild(el('dt', '', r[0]));
        dl.appendChild(el('dd', r[0] === 'App id' && !d.app.app_id ? 'hue-none' : '', r[1]));
      });
      s.appendChild(dl);
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Change', '', function () {
        S.changing = true; S.said = ''; S.error = '';
        draw();
        var first = $('hueClientId');
        if (first) first.focus();
      }, 'Type a new client id, secret or app id'));
      acts.appendChild(button('Remove', 'danger', function () {
        if (!window.confirm('Remove the Hue app? Nobody here can connect Hue until it is set again.')) return;
        post('/api/settings/hue/app/remove', {});
      }, 'Forget the Hue app'));
      s.appendChild(acts);
      return s;
    }
    var f = el('form', 'hb-form sk-form');
    f.setAttribute('aria-label', 'Hue app');
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { S.editing = true; });
    var kept = d.app || {};
    // What was typed and refused stays in the fields, but never the secret.
    var typed = S.typed || {};
    var fields = [
      ['client_id', 'hueClientId', 'Client id', 'text', typed.client_id != null ? typed.client_id : (kept.client_id || '')],
      ['client_secret', 'hueSecret', 'Client secret', 'password', ''],
      ['app_id', 'hueAppId', 'App id', 'text', typed.app_id != null ? typed.app_id : (kept.app_id || '')]
    ];
    var inputs = {};
    fields.forEach(function (k) {
      var label = el('label', 'hb-field wide');
      label.appendChild(el('span', '', k[2]));
      var input = el('input');
      input.type = k[3];
      input.id = k[1];
      input.name = k[0];
      input.setAttribute('autocomplete', 'off');
      input.spellcheck = false;
      input.maxLength = 300;
      input.value = k[4];
      if (k[0] === 'client_secret' && kept.secret_last4) input.placeholder = 'Kept, ending …' + kept.secret_last4;
      label.appendChild(input);
      f.appendChild(label);
      inputs[k[0]] = input;
    });
    var acts2 = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save');
    save.type = 'submit';
    save.disabled = S.busy;
    acts2.appendChild(save);
    if (S.changing) {
      acts2.appendChild(button('Cancel', '', function () {
        inputs.client_secret.value = '';
        S.changing = false; S.editing = false; S.typed = null;
        draw();
      }));
    }
    f.appendChild(acts2);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (S.busy) return;
      var body = { client_id: inputs.client_id.value, client_secret: inputs.client_secret.value,
                   app_id: inputs.app_id.value };
      // The secret leaves the page with this one request and is not kept in it.
      inputs.client_secret.value = '';
      S.editing = false;
      S.typed = { client_id: body.client_id, app_id: body.app_id };
      post('/api/settings/hue/app', body);
      body = {};
    });
    s.appendChild(f);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = ''; S.error = ''; S.editing = false; S.changing = false; S.fromHue = false;
    takeReturn();
    draw();
    load();
  }

  function hiddenNow() {
    S.open = false;
    S.editing = false;
    S.changing = false;
    // Nothing typed into the secret's field stays in the page once it is left.
    var body = $('hueBody');
    if (body) body.querySelectorAll('input[type="password"]').forEach(function (i) { i.value = ''; });
  }

  window.RouhHue = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
