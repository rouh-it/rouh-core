/* Settings, Connections, Slack, at /anatomy/connections/slack (`rouh/slack.py`, `rouh/web/slack.py`).

   Petar, 16 October 2026: "I need you to evesdrop on my slack. Full integration. You should be
   able to talk to people and be added to channels."

   Not connected: the steps in Slack, the first of them one press that opens Slack's "Create an
   app" with Rouh's manifest filled in, and the three tokens to paste. Connected: which workspace,
   as which bot, whose own direct messages are read, how listening and reading back go, and what is
   kept; each token as set and its last four, with Replace, and Check again and Disconnect. A token
   leaves the page in the one request that saves it, and its field is emptied at once, whatever the
   answer.

   A section of Anatomy, drawn into `#slackBody` from `/api/settings/slack`. Anatomy tells it when it
   shows and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var S = { open: false, data: null, busy: false, error: '', said: '', seq: 0, editing: false,
            replacing: {}, timer: 0 };
  var KINDS = [
    ['bot', 'Bot token', 'xoxb-', 'OAuth & Permissions: Bot User OAuth Token'],
    ['user', 'Your user token', 'xoxp-', 'OAuth & Permissions: User OAuth Token. It reads only your own direct messages.'],
    ['app', 'App-level token', 'xapp-', 'Basic Information: App-Level Tokens, with the connections:write scope']
  ];

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
          if (j && j.tokens) S.data = j;
          if (same) return j;
          if (r.ok) {
            S.error = '';
            if (j && j.said) S.said = j.said;
            if (method === 'POST') { S.replacing = {}; S.editing = false; }
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
  function load() { return call('GET', '/api/settings/slack'); }
  function post(url, body) { S.said = ''; S.error = ''; return call('POST', url, body); }

  /* While it connects or reads back, the page reads again every few seconds, and stops once it
     is listening and done, or is left. */
  function follow() {
    clearTimeout(S.timer);
    var d = S.data;
    if (!S.open || !d || !d.connected) return;
    var moving = d.listening !== 'listening' || (d.backfill && d.backfill.started_at && !d.backfill.finished_at);
    if (!moving) return;
    S.timer = window.setTimeout(function () { if (!S.editing && !S.busy) load().then(follow); else follow(); }, 4000);
  }

  /* ---- the (i): what a step means, opened in place ---- */

  var INFO_SVG = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.4" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="6.2" r="1.15" fill="currentColor"/>' +
    '<path d="M10 9v5.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  var infoSeq = 0;
  function info(label, lines) {
    var id = 'skInfo' + (++infoSeq);
    var b = el('button', 'sk-i');
    b.type = 'button';
    b.innerHTML = INFO_SVG;
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', id);
    var note = el('div', 'sk-guide');
    note.id = id;
    note.hidden = true;
    lines.forEach(function (t) { note.appendChild(el('p', '', t)); });
    b.addEventListener('click', function () {
      note.hidden = !note.hidden;
      b.setAttribute('aria-expanded', note.hidden ? 'false' : 'true');
    });
    return { button: b, note: note };
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('slackBody');
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
    var say2 = el('p', 'hb-say' + (S.error ? ' bad' : ''), S.busy ? 'Asking Slack…' : (S.error || S.said));
    say2.setAttribute('role', 'status');
    say2.hidden = !(S.busy || S.error || S.said);
    page.appendChild(say2);
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the connection…'));
      return;
    }
    page.appendChild(statusCard(S.data));
    if (!S.data.connected) page.appendChild(stepsCard(S.data));
    page.appendChild(tokensCard(S.data));
  }

  function card(title, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    s.appendChild(el('h4', 'hb-h', title));
    return s;
  }

  function stateOf(d) {
    if (!d.connected) return ['Not connected', ''];
    if (d.listening === 'listening') return ['Listening', 'yes'];
    if (d.listening === 'connecting' || !d.listening) return ['Connecting', ''];
    return ['Not listening', 'failed'];
  }

  function statusCard(d) {
    var s = el('section', 'setting-card hb-card sk-status');
    var top = el('div', 'hb-beat-top');
    top.appendChild(el('span', 'hb-beat-what', d.team || 'Rouh’s Slack app'));
    var st = stateOf(d);
    top.appendChild(el('span', 'hb-pill' + (st[1] ? ' ' + st[1] : ''), st[0]));
    s.appendChild(top);
    if (!d.tokens.bot && !d.tokens.app && !d.tokens.user) return s;
    var dl = el('dl', 'hb-ask-dl sk-fields');
    var rows = [];
    if (d.bot) rows.push(['Bot', '@' + d.bot]);
    rows.push(['Your messages', d.for ? 'Read as ' + d.for + ', for you alone'
      : 'Not read: add your user token below']);
    if (d.connected) {
      rows.push(['Listening', d.listening === 'listening' ? 'Since ' + d.since
        : (d.listening_said || 'Starting.')]);
      var b = d.backfill || {};
      // While the last b.days days are being read back; once done, Kept says what they came to.
      if (b.started_at && !b.finished) rows.push(['Last ' + (b.days || 90) + ' days', 'Reading back… ' + (b.messages || 0) + ' so far']);
      rows.push(['Kept', d.messages + ' message' + (d.messages === 1 ? '' : 's') + ' from ' +
        d.conversations + ' conversation' + (d.conversations === 1 ? '' : 's')]);
    }
    rows.forEach(function (r) {
      dl.appendChild(el('dt', '', r[0]));
      dl.appendChild(el('dd', '', r[1]));
    });
    s.appendChild(dl);
    if (d.connected && d.admin) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Check again', '', function () { post('/api/settings/slack/check', {}); },
        'Ask Slack again whether every kept token still works'));
      acts.appendChild(button('Disconnect', 'danger', function () {
        if (!window.confirm('Disconnect Slack? Rouh forgets the tokens and stops listening. The app stays in your workspace until you remove it in Slack.')) return;
        post('/api/settings/slack/remove', {});
      }, 'Forget every token and stop listening'));
      s.appendChild(acts);
    }
    return s;
  }

  function step(n, title, more, help) {
    var li = el('li', 'sk-step');
    var head = el('div', 'sk-step-head');
    head.appendChild(el('span', 'sk-step-n', String(n)));
    head.appendChild(el('span', 'sk-step-what', title));
    var tip = help ? info('About step ' + n, help) : null;
    if (tip) head.appendChild(tip.button);
    li.appendChild(head);
    if (more) li.appendChild(more);
    if (tip) li.appendChild(tip.note);
    return li;
  }

  function stepsCard(d) {
    var s = card('Connect Slack', 'sk-steps');
    var ol = el('ol', 'sk-step-list');
    var make = el('a', 'ctl small primary sk-make', 'Create the app in Slack');
    make.href = d.create_url;
    make.target = '_blank';
    make.rel = 'noopener noreferrer';
    var both = el('div', 'hb-actions sk-make-row');
    both.appendChild(make);
    both.appendChild(button('Copy the manifest', '', function () { copyManifest(d); },
      'For Slack’s From an app manifest, if the page it opens is empty'));
    ol.appendChild(step(1, 'Create Rouh’s app', both, [
      'Slack opens with Rouh’s app already described: a bot called Rouh and Socket Mode, so nothing on this server has to be reachable from outside. Pick your workspace, press Next, then Create.',
      'The bot may read the channels it is in and the messages people send it, see who people are, and post as Rouh: ' + d.bot_scopes.join(', ') + '.',
      'Your own token may only read your own direct messages: ' + d.user_scopes.join(', ') + '. It can never post as you.',
      'If Slack opens with an empty manifest, press Copy the manifest, then in Slack choose Create New App, From an app manifest, and paste it.']));
    ol.appendChild(step(2, 'In Install App, press Install to Workspace, then Allow', null, [
      'Allow covers both the bot and your own read-only access to your direct messages.']));
    ol.appendChild(step(3, 'In Basic Information, App-Level Tokens, press Generate Token and Scopes, and add connections:write', null, [
      'Any name will do. This token opens the connection Slack sends its events down.']));
    ol.appendChild(step(4, 'Paste the three tokens below and press Save', null, null));
    ol.appendChild(step(5, 'Invite @Rouh to each channel it should read', null, [
      'In the channel, type /invite @Rouh. A private channel can only be joined this way; Rouh can join a public one itself when you ask it to.']));
    s.appendChild(ol);
    return s;
  }

  function copyManifest(d) {
    var text = '';
    try {
      text = JSON.stringify(JSON.parse(new URL(d.create_url).searchParams.get('manifest_json') || '{}'), null, 2);
    } catch (err) { text = ''; }
    if (!text || !navigator.clipboard) { S.error = 'This browser would not copy it.'; draw(); return; }
    navigator.clipboard.writeText(text).then(function () {
      S.error = ''; S.said = 'Rouh’s manifest is copied: paste it in Slack’s From an app manifest.'; draw();
    }, function () { S.error = 'This browser would not copy it.'; draw(); });
  }

  function tokensCard(d) {
    var s = card('Tokens', 'sk-tokens');
    if (!d.admin) {
      s.appendChild(el('p', 'settings-help', 'Only an administrator of this organisation connects Slack.'));
      return s;
    }
    var f = el('form', 'hb-form sk-form');
    f.setAttribute('aria-label', 'Slack tokens');
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { S.editing = true; });
    var inputs = {};
    KINDS.forEach(function (k) {
      var kept = d.tokens[k[0]];
      var row = el('div', 'sk-token');
      if (kept && !S.replacing[k[0]]) {
        row.appendChild(el('span', 'sk-token-name', k[1]));
        row.appendChild(el('span', 'sk-token-set', 'set, ending …' + kept.last4));
        row.appendChild(button('Replace', '', function () {
          S.replacing[k[0]] = true;
          S.said = ''; S.error = '';
          draw();
          var again = $('skToken-' + k[0]);
          if (again) again.focus();
        }, 'Paste a new ' + k[1].toLowerCase().replace(/^your /, '') + ' in place of this one'));
        f.appendChild(row);
        return;
      }
      var label = el('label', 'hb-field wide');
      var head = el('span', 'sk-label');
      head.appendChild(document.createTextNode(k[1]));
      var tip = info('Where to find ' + (/^your /i.test(k[1]) ? '' : 'the ') + k[1].toLowerCase(), [k[3]]);
      head.appendChild(tip.button);
      label.appendChild(head);
      var input = el('input');
      input.type = 'password';
      input.id = 'skToken-' + k[0];
      input.name = k[0];
      input.setAttribute('autocomplete', 'off');
      input.spellcheck = false;
      input.maxLength = 300;
      input.placeholder = k[2] + '…';
      label.appendChild(input);
      label.appendChild(tip.note);
      f.appendChild(label);
      inputs[k[0]] = input;
    });
    if (Object.keys(inputs).length) {
      var acts = el('div', 'hb-actions');
      var save = el('button', 'ctl small primary', 'Save');
      save.type = 'submit';
      save.disabled = S.busy;
      acts.appendChild(save);
      if (Object.keys(S.replacing).length) {
        acts.appendChild(button('Cancel', '', function () {
          Object.keys(inputs).forEach(function (n) { inputs[n].value = ''; });
          S.replacing = {}; S.editing = false;
          draw();
        }));
      }
      f.appendChild(acts);
    }
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (S.busy) return;
      var body = {};
      var any = false;
      Object.keys(inputs).forEach(function (n) {
        body[n] = inputs[n].value;
        if (inputs[n].value.trim()) any = true;
        // Each token leaves the page with this one request and is not kept in it.
        inputs[n].value = '';
      });
      S.editing = false;
      if (!any) { S.error = 'Paste a token first.'; draw(); return; }
      post('/api/settings/slack/tokens', body).then(follow);
      body = {};
    });
    s.appendChild(f);
    return s;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = ''; S.error = ''; S.editing = false; S.replacing = {};
    draw();
    load().then(follow);
  }

  function hiddenNow() {
    S.open = false;
    S.editing = false;
    S.replacing = {};
    clearTimeout(S.timer);
    // Nothing typed into a token field stays in the page once it is left.
    var body = $('slackBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { i.value = ''; });
  }

  window.RouhSlack = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
