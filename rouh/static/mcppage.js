/* Anatomy, Connections, MCP servers, at /anatomy/connections/mcp (`rouh/mcp_servers.py`, `rouh/web/mcp.py`).

   Petar, 15 November 2026: "we need interface to describe the fact that we have MCP capabilities
   so people know. somewhere in anatomy we should have mcps and ability to easily connect one."

   Top to bottom: one sentence that says what MCP is, one line that a server's tools can act in
   its account, a verdict (how many servers are connected and how many tools they give) with the
   view's one primary button, Connect a server. Then one card per server: its name, Connected,
   Failing or Off, "from settings" for the installation's own (read-only), how many tools, its
   address or command, why it is failing in plain words without opening anything, the last four of
   each secret, Ask first, and Tools, Test, Turn off and Remove.

   Connect a server opens in place: start from a well-known server (which fills the form in and
   says which token it needs and where to get one) or Your own; an address with an optional header,
   or a command with arguments and environment values (administrators only). Test opens it and
   lists its tools; once a test passes, Save is the primary button, and saving opens it in the
   running Rouh with no restart. What is typed is held in this page only while the section is open
   and never comes back from the server; a token leaves the page only in the request that tests or
   saves it.

   The cards and controls are Anatomy's own (`heartbeatpage.css`: hb-card, hb-pill, hb-field,
   hb-say). A section of Anatomy, drawn into `#mcpBody`; Anatomy tells it when it shows and when
   it is left (`settingsPages` in app/runs.js). The design: .design/ of the run that built it
   (task 169's standard, full tier). */
(function () {
  'use strict';

  /** @type {{open: boolean, data: any, busy: string, error: string, said: string, bad: boolean,
   *          connect: boolean, form: any, tested: any, expanded: Object<string, boolean>, seq: number}} */
  var S = { open: false, data: null, busy: '', error: '', said: '', bad: false, connect: false,
            form: null, tested: null, expanded: {}, seq: 0 };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function button(text, cls, act, label) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (label) b.setAttribute('aria-label', label);
    b.disabled = !!S.busy;
    b.addEventListener('click', act);
    return b;
  }
  function plural(n, one) { return n + ' ' + one + (n === 1 ? '' : 's'); }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }

  /* ---- talking to the server ---- */

  function call(method, url, body, busy) {
    var seq = ++S.seq;
    if (method === 'POST') { S.busy = busy || 'Working…'; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') S.busy = '';
          if (method === 'GET' && seq !== S.seq) return j;
          if (j && j.servers) S.data = j;
          if (r.ok) {
            S.error = '';
            if (j && j.said) { S.said = j.said; S.bad = !!j.bad; }
          } else {
            S.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return { ok: r.ok, body: j };
        });
      })
      .catch(function () {
        if (method === 'POST') S.busy = '';
        S.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
        return { ok: false, body: {} };
      });
  }
  function load() { return call('GET', '/api/settings/mcp'); }
  function post(url, body, busy) { S.said = ''; S.error = ''; S.bad = false; return call('POST', url, body, busy); }

  /* ---- the form's state, kept here so a redraw never loses what was typed ---- */

  function presets() { return (S.data && S.data.presets) || []; }
  function presetOf(id) { return presets().filter(function (p) { return p.id === id; })[0] || null; }

  function blankForm(id) {
    var p = presetOf(id || '');
    return { preset: p ? p.id : '', name: p ? p.name : '', kind: p ? p.kind : 'http',
             url: p && p.url ? p.url : '', command: p && p.command ? p.command.join(' ') : '', args: '',
             secret: '', header: '', headerValue: '', env: [{ name: '', value: '' }] };
  }

  function bodyOf(f) {
    var p = presetOf(f.preset);
    var body = { name: f.name, kind: f.kind, preset: f.preset };
    var secret = p && p.secret && f.secret ? [{ name: p.secret.key, value: (p.secret.prefix || '') + f.secret }] : [];
    if (f.kind === 'http') {
      body.url = f.url;
      body.headers = secret.length && p.secret.where === 'header' ? secret
        : (f.header ? [{ name: f.header, value: f.headerValue }] : []);
    } else {
      body.command = f.command;
      body.args = f.args;
      body.env = secret.length && p.secret.where === 'env' ? secret
        : f.env.filter(function (e) { return e.name; });
    }
    return body;
  }

  /* What is missing before a test is worth sending, in a sentence, or nothing. */
  function missing(f) {
    var p = presetOf(f.preset);
    if (!f.name) return 'Give it a short name first, such as github.';
    if (f.kind === 'http' && !/^https?:\/\/\S+/i.test(f.url || '')) return 'Type its address first. It starts with https://.';
    if (f.kind === 'stdio' && !(f.command || '').trim()) return 'Type the command that starts it first.';
    if (p && p.secret && !f.secret) return 'Paste your ' + p.secret.label + ' first: it needs one to say what it can do.';
    return '';
  }

  function test() {
    if (S.busy) return;
    var f = S.form;
    var lacking = missing(f);
    if (lacking) { S.tested = { ok: false, tools: [], error: lacking }; draw(); return; }
    S.tested = null;
    post('/api/settings/mcp/test', bodyOf(f), 'Testing ' + (f.name || 'the server') + '…').then(function (got) {
      if (!got || S.form !== f) return;
      var j = got.body || {};
      if (got.ok) S.tested = { ok: !!j.ok, tools: j.tools || [], error: j.error || '', said: j.said || '' };
      else S.tested = { ok: false, tools: [], error: (j && j.error) || S.error };
      // The result under the buttons says it; the line above the cards would only say it twice.
      S.said = '';
      S.error = '';
      draw();
      var res = document.querySelector('#mcpBody .mcp-result');
      if (res) res.focus();
    });
  }

  function save() {
    if (S.busy) return;
    var f = S.form;
    post('/api/settings/mcp/save', bodyOf(f), 'Saving and connecting ' + (f.name || 'the server') + '…').then(function (got) {
      if (got && got.ok) { S.connect = false; S.form = null; S.tested = null; draw(); focusOpen(); }
    });
  }

  function focusOpen() {
    var b = $('mcpConnectOpen');
    if (b) b.focus();
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('mcpBody');
    if (!body || !S.open) return;
    var active = document.activeElement && body.contains(document.activeElement) ? document.activeElement.id : '';
    body.setAttribute('aria-busy', S.busy ? 'true' : 'false');
    body.textContent = '';
    var page = el('div', 'hb-page mcp-page');
    body.appendChild(page);
    page.appendChild(head());
    var said = S.busy || S.error || S.said;
    var say = el('p', 'hb-say' + (S.error || S.bad ? ' bad' : ''), said);
    say.setAttribute('role', 'status');
    say.hidden = !said;
    page.appendChild(say);
    if (!S.data) {
      if (!S.error) page.appendChild(el('p', 'hb-empty', 'Reading the servers…'));
      return;
    }
    if (S.connect) page.appendChild(connectCard());
    var servers = S.data.servers || [];
    if (!servers.length && !S.connect) page.appendChild(emptyCard());
    // A failing server first: it is what a person comes from the status board to read.
    servers.slice().sort(function (a, b) { return (b.state === 'failing' ? 1 : 0) - (a.state === 'failing' ? 1 : 0); })
      .forEach(function (s) { page.appendChild(serverCard(s)); });
    if (active) {
      var again = $(active);
      if (again) again.focus();
    }
  }

  function verdict(d) {
    var servers = (d && d.servers) || [];
    if (!servers.length) return 'Nothing is connected yet.';
    var failing = servers.filter(function (s) { return s.state === 'failing'; }).length;
    return plural(d.connected, 'server') + ' connected, giving Rouh ' + plural(d.tools, 'tool') + '.' +
      (failing ? ' ' + failing + ' failing.' : '');
  }

  function head() {
    var h = el('div', 'mcp-head');
    h.appendChild(el('p', 'mcp-lede', 'MCP (Model Context Protocol) is a standard way to plug another program’s ' +
      'tools into Rouh, such as GitHub, Notion or Linear. Once a server is connected, its tools become Rouh’s tools.'));
    h.appendChild(el('p', 'mcp-acts', 'A connected server’s tools can act in that account, with the token you give it.'));
    var v = el('div', 'mcp-verdict');
    v.appendChild(el('strong', '', S.data ? verdict(S.data) : ''));
    if (!S.connect) {
      var go = button('Connect a server', 'primary', function () {
        S.connect = true; S.form = blankForm(''); S.tested = null; S.said = ''; S.error = '';
        draw();
        var first = document.querySelector('#mcpBody .mcp-chip');
        if (first) /** @type {HTMLElement} */ (first).focus();
      });
      go.id = 'mcpConnectOpen';
      v.appendChild(go);
    }
    h.appendChild(v);
    return h;
  }

  function emptyCard() {
    var c = el('section', 'setting-card hb-card mcp-empty');
    c.appendChild(el('p', 'hb-empty', 'No server is connected. Start from a well-known one, or from your own address ' +
      'or command with Connect a server above.'));
    var tiles = el('div', 'mcp-chips');
    tiles.setAttribute('role', 'group');
    tiles.setAttribute('aria-label', 'Start from a well-known server');
    presets().forEach(function (p) {
      var b = el('button', 'mcp-chip', p.title);
      b.type = 'button';
      b.addEventListener('click', function () {
        S.connect = true; S.form = blankForm(p.id); S.tested = null; S.said = ''; S.error = '';
        draw();
        var name = $('mcpSecret') || $('mcpName');
        if (name) name.focus();
      });
      tiles.appendChild(b);
    });
    c.appendChild(tiles);
    return c;
  }

  var STATES = { connected: ['Connected', 'yes'], failing: ['Failing', 'failed'], off: ['Off', 'no'],
                 waiting: ['Not opened yet', 'no'] };

  function serverCard(s) {
    var c = el('section', 'setting-card hb-card mcp-card');
    c.setAttribute('aria-label', s.name);
    var top = el('div', 'mcp-top');
    top.appendChild(el('h4', 'mcp-name', s.name));
    var st = STATES[s.state] || [s.state, 'no'];
    top.appendChild(el('span', 'hb-pill mcp-state ' + st[1], st[0]));
    if (s.source === 'settings') top.appendChild(el('span', 'hb-pill mcp-ro', 'from settings'));
    top.appendChild(el('span', 'mcp-count', plural((s.tools || []).length, 'tool')));
    c.appendChild(top);
    if (s.where) c.appendChild(el('p', 'mcp-where', s.where));
    if (s.error) {
      var why = el('p', 'mcp-why');
      why.appendChild(el('b', '', 'Why: '));
      why.appendChild(document.createTextNode(s.error));
      c.appendChild(why);
    }
    if (s.secrets && s.secrets.length) {
      c.appendChild(el('p', 'mcp-secrets', s.secrets.map(function (x) { return x.name + ' ' + x.hint; }).join(', ')));
    }
    if (s.source === 'saved') c.appendChild(askFirst(s));
    else c.appendChild(el('p', 'hb-note', (s.ask_first ? 'Ask first: on. ' : 'Ask first: off. Its tools run without asking you. ') +
      'Set in this Rouh’s settings (ROUH_MCP_SERVERS), so it is changed there, not here.'));
    var acts = el('div', 'hb-actions mcp-acts-row');
    var key = s.source + ':' + s.name;
    var open = !!S.expanded[key];
    if ((s.tools || []).length) {
      var t = button(open ? 'Hide tools' : 'Tools', '', function () { S.expanded[key] = !open; draw(); },
                     (open ? 'Hide the tools of ' : 'Show the tools of ') + s.name);
      t.id = 'mcpTools' + (s.id || s.name);
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
      acts.appendChild(t);
    }
    if (s.source === 'saved') {
      if (s.enabled) {
        var tb = button('Test', '', function () { post('/api/settings/mcp/check', { id: s.id }, 'Testing ' + s.name + '…'); },
                        'Test ' + s.name + ' now');
        tb.id = 'mcpTest' + s.id;
        acts.appendChild(tb);
      }
      var onoff = button(s.enabled ? 'Turn off' : 'Turn on', '', function () {
        post('/api/settings/mcp/enabled', { id: s.id, on: !s.enabled }, (s.enabled ? 'Turning ' + s.name + ' off…' : 'Turning ' + s.name + ' on…'));
      }, (s.enabled ? 'Turn off ' : 'Turn on ') + s.name);
      onoff.id = 'mcpOnOff' + s.id;
      acts.appendChild(onoff);
      acts.appendChild(button('Remove', 'danger', function () {
        if (!window.confirm('Remove ' + s.name + '? Its tools leave Rouh and its token is forgotten.')) return;
        post('/api/settings/mcp/remove', { id: s.id }, 'Removing ' + s.name + '…').then(focusOpen);
      }, 'Remove ' + s.name));
    }
    if (acts.childNodes.length) c.appendChild(acts);
    if (open) c.appendChild(toolList(s.tools || []));
    return c;
  }

  /* Ask first, as Rouh's own switch (`.gt-switch` in app.css): the words say the state as well as the knob. */
  function askFirst(s) {
    var sw = el('button', 'gt-switch mcp-ask');
    sw.type = 'button';
    sw.id = 'mcpAsk' + s.id;
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', s.ask_first ? 'true' : 'false');
    sw.disabled = !!S.busy;
    var track = el('span', 'gt-switch-track');
    track.setAttribute('aria-hidden', 'true');
    track.appendChild(el('span', 'gt-switch-knob'));
    sw.appendChild(track);
    sw.appendChild(el('span', 'gt-switch-label', s.ask_first ? 'Ask first: on. Each of its tools asks you before it runs'
                                                             : 'Ask first: off. Its tools run without asking you'));
    sw.addEventListener('click', function () { post('/api/settings/mcp/ask-first', { id: s.id, on: !s.ask_first }); });
    return sw;
  }

  function toolList(tools) {
    var wrap = el('div', 'mcp-tools-wrap');
    if (tools.length > 6) wrap.appendChild(el('p', 'mcp-tools-note', 'All ' + tools.length + ' tools; the list scrolls.'));
    var ul = el('ul', 'mcp-tools');
    ul.setAttribute('tabindex', '0');
    ul.setAttribute('aria-label', 'Tools');
    tools.forEach(function (t) {
      var li = el('li');
      li.appendChild(el('code', '', t.name));
      if (t.description) li.appendChild(el('span', '', t.description));
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }

  /* ---- Connect a server ---- */

  function connectCard() {
    var f = S.form || (S.form = blankForm(''));
    var c = el('section', 'setting-card hb-card mcp-connect');
    c.setAttribute('aria-labelledby', 'mcpConnectH');
    var h = el('h4', 'hb-h', 'Connect a server');
    h.id = 'mcpConnectH';
    c.appendChild(h);
    var chips = el('div', 'mcp-chips');
    chips.setAttribute('role', 'group');
    chips.setAttribute('aria-label', 'Start from');
    presets().concat([{ id: '', title: 'Your own' }]).forEach(function (p) {
      var b = el('button', 'mcp-chip', p.title);
      b.type = 'button';
      b.id = 'mcpPreset' + (p.id || 'own');
      b.setAttribute('aria-pressed', f.preset === p.id ? 'true' : 'false');
      b.addEventListener('click', function () { S.form = blankForm(p.id); S.tested = null; draw(); });
      chips.appendChild(b);
    });
    c.appendChild(chips);
    var p = presetOf(f.preset);
    var form = el('form', 'hb-form mcp-form');
    form.setAttribute('aria-label', 'The server');
    form.noValidate = true;
    if (p) form.appendChild(el('p', 'mcp-about', p.about));
    form.appendChild(field('Name', 'mcpName', 'text', 'name', 'github'));
    var canRun = !!(S.data && S.data.can_run_commands);
    var seg = el('div', 'mcp-seg');
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'How Rouh reaches it');
    [['http', 'An address'], ['stdio', 'A command']].forEach(function (k) {
      var b = el('button', '', k[1]);
      b.type = 'button';
      b.id = 'mcpKind' + k[0];
      b.setAttribute('aria-pressed', f.kind === k[0] ? 'true' : 'false');
      b.addEventListener('click', function () { f.kind = k[0]; S.tested = null; draw(); });
      seg.appendChild(b);
    });
    form.appendChild(seg);
    if (f.kind === 'stdio' && !canRun) {
      form.appendChild(el('p', 'hb-note', 'A command runs a program on this machine, so only an administrator can connect one.'));
    }
    if (f.kind === 'http') {
      form.appendChild(field('Address', 'mcpUrl', 'url', 'url', 'https://…'));
      if (p && p.secret) form.appendChild(secretField(p.secret));
      else {
        var pair = el('div', 'mcp-pair');
        pair.appendChild(field('Header (optional)', 'mcpHeader', 'text', 'header', 'Authorization'));
        pair.appendChild(field('Its value', 'mcpHeaderValue', 'password', 'headerValue', 'Bearer …'));
        form.appendChild(pair);
      }
    } else {
      form.appendChild(field('Command', 'mcpCommand', 'text', 'command', 'npx -y some-mcp-server'));
      form.appendChild(field('Arguments (optional)', 'mcpArgs', 'text', 'args', ''));
      if (p && p.secret) form.appendChild(secretField(p.secret));
      else {
        f.env.forEach(function (e, i) {
          var pair2 = el('div', 'mcp-pair');
          pair2.appendChild(field(i ? 'Environment value' : 'Environment value (optional)', 'mcpEnv' + i, 'text', null, 'API_KEY', e, 'name'));
          pair2.appendChild(field('Its value', 'mcpEnvValue' + i, 'password', null, '', e, 'value'));
          form.appendChild(pair2);
        });
        var add = el('button', 'mcp-add', 'Add another value');
        add.type = 'button';
        add.id = 'mcpEnvAdd';
        add.addEventListener('click', function () { f.env.push({ name: '', value: '' }); draw(); var n = $('mcpEnv' + (f.env.length - 1)); if (n) n.focus(); });
        form.appendChild(add);
      }
    }
    var passed = !!(S.tested && S.tested.ok);
    var acts = el('div', 'hb-actions');
    var tb = el('button', 'ctl small' + (passed ? '' : ' primary'), passed ? 'Test again' : 'Test');
    tb.type = 'submit';
    tb.id = 'mcpTestNew';
    tb.disabled = !!S.busy || (f.kind === 'stdio' && !canRun);
    acts.appendChild(tb);
    var sv = button('Save', passed ? 'primary' : '', save, 'Save and connect it');
    sv.id = 'mcpSave';
    sv.disabled = !!S.busy || !passed;
    acts.appendChild(sv);
    var cancel = button('Cancel', '', function () { S.connect = false; S.form = null; S.tested = null; draw(); focusOpen(); });
    acts.appendChild(cancel);
    form.appendChild(acts);
    if (S.tested) form.appendChild(result(S.tested, f));
    // Anything typed after a test makes it stale: the result goes and Test is the next press again,
    // without a redraw, so the caret stays where it is.
    form.addEventListener('input', function () {
      if (!S.tested) return;
      S.tested = null;
      var res = form.querySelector('.mcp-result');
      if (res) res.remove();
      sv.disabled = true; sv.classList.remove('primary');
      tb.classList.add('primary'); tb.textContent = 'Test';
    });
    form.addEventListener('submit', function (e) { e.preventDefault(); test(); });
    c.appendChild(form);
    return c;
  }

  function result(t, f) {
    var r = el('div', 'mcp-result ' + (t.ok ? 'ok' : 'bad'));
    r.setAttribute('tabindex', '-1');
    if (t.ok) {
      r.appendChild(el('strong', '', 'It works: ' + (f.name || 'it') + ' gives ' + plural(t.tools.length, 'tool') + '. Save to connect it.'));
      if (t.tools.length) r.appendChild(toolList(t.tools));
    } else {
      r.appendChild(el('strong', '', 'It did not work.'));
      r.appendChild(el('p', '', t.error || 'It did not say why.'));
    }
    return r;
  }

  function secretField(secret) {
    var l = field(secret.label, 'mcpSecret', 'password', 'secret', '');
    var help = el('small', 'mcp-help', secret.help + ' ');
    if (secret.link) {
      var a = el('a', '', 'Where to get one');
      a.href = secret.link;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      help.appendChild(a);
    }
    l.appendChild(help);
    return l;
  }

  /* One labelled input, bound to the form's state (or to one row of its environment values). */
  function field(text, id, type, key, placeholder, holder, holderKey) {
    var f = S.form;
    var label = el('label', 'hb-field wide');
    label.appendChild(el('span', '', text));
    var input = el('input');
    input.type = type;
    input.id = id;
    input.setAttribute('autocomplete', type === 'password' ? 'new-password' : 'off');
    input.spellcheck = false;
    input.maxLength = type === 'password' ? 4000 : 500;
    if (placeholder) input.placeholder = placeholder;
    var obj = holder || f;
    var k = holderKey || key;
    input.value = obj[k] || '';
    input.addEventListener('input', function () { obj[k] = input.value; });
    label.appendChild(input);
    return label;
  }

  /* ---- shown and left ---- */

  function shownNow() {
    if (S.open) return;
    S.open = true;
    S.said = ''; S.error = ''; S.bad = false;
    draw();
    load();
  }

  function hiddenNow() {
    S.open = false;
    // Nothing typed into the form, a token least of all, stays in the page once it is left.
    S.connect = false; S.form = null; S.tested = null;
    var body = $('mcpBody');
    if (body) body.querySelectorAll('input').forEach(function (i) { /** @type {HTMLInputElement} */ (i).value = ''; });
  }

  window.RouhMcp = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
