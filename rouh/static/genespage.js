/* Meta, Gene registry (Rouh Land Account, Gene Pool until 7 November 2026), at /anatomy/meta/gene-pool (`rouh/genelab.py`, `rouh/web/genes.py`;
   Meta, Genes until 4 November 2026).

   Shared genes from a gene registry, and the lab they arrive in. Petar, 12
   October 2026: a gene is an idea written in a contract - what it is, where
   it appears, what it touches and how to remove it - and may change Rouh in
   any way, so what it touches is shown before it is installed, as
   information and never as a gate.

   The list, at the section's own address: the registry Rouh is pointed at and the key
   it pins (off until both are set), the lab with each gene's own switch, the
   genes in the registry's signed index with their ratings and publishers,
   and what was done. One gene, at <the section>/<publisher>/<name>: its
   whole contract as the registry signed it, then Install, which asks once
   more and installs it in the lab switched off; once installed its switch,
   its files to read, an update with what changed in its contract, and
   Remove, which says what the check afterwards found.

   Every word a gene says about itself is drawn as text (`textContent`),
   never as markup, and nothing here acts on it.

   A group of Settings, drawn into `#genesBody`. Settings tells it when it
   shows, which gene, and when it is left (`settingsPages` in app/runs.js). */
(function () {
  'use strict';

  var G = { open: false, gene: '', data: null, busy: false, error: '', said: '', seq: 0, asking: '',
            removed: null, file: null, editing: false, changing: false };

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
    b.disabled = G.busy;
    b.addEventListener('click', act);
    return b;
  }
  /* A link inside Rouh: a plain press goes there in the page, Cmd-click opens a tab. */
  function link(text, href, cls) {
    var a = el('a', cls || 'gn-link', text);
    a.href = href;
    a.setAttribute('data-inapp', '');
    a.addEventListener('click', function (e) {
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (window.RouhGenesHost) window.RouhGenesHost.go(href);
    });
    return a;
  }
  function csrfToken() {
    var found = /(?:^|;\s*)rouh_csrftoken=([^;]+)/.exec(document.cookie || '');
    return found ? decodeURIComponent(found[1]) : '';
  }
  function deviceZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
  }
  function when(seconds) {
    if (!seconds) return '';
    var d = new Date(seconds * 1000);
    try {
      return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (err) { return d.toISOString(); }
  }
  function whenIso(text) {
    var t = Date.parse(String(text || ''));
    return isNaN(t) ? String(text || '') : when(t / 1000);
  }
  function rating(r) {
    if (!r || r.average == null) return '';
    return r.average + ' of 5' + (r.count != null ? ' from ' + r.count : '');
  }

  function call(method, url, body) {
    var seq = ++G.seq;
    if (method === 'POST') { G.busy = true; draw(); }
    return fetch(url, { method: method, credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json', 'X-Time-Zone': deviceZone(),
                                   'X-CSRFToken': csrfToken() },
                        body: method === 'POST' ? JSON.stringify(body || {}) : undefined })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (method === 'POST') G.busy = false;
          if (seq !== G.seq && method === 'GET') return j;
          if (j && j.registry) G.data = j;
          if (r.ok) {
            G.error = '';
            if (j && j.said) G.said = j.said;
          } else {
            G.error = (j && j.error) || 'The server said ' + r.status + '.';
          }
          draw();
          return r.ok ? j : null;
        });
      })
      .catch(function () {
        if (method === 'POST') G.busy = false;
        G.error = 'Rouh could not be reached. Check the connection and try again.';
        draw();
        return null;
      });
  }
  function load() { return call('GET', '/api/settings/genes'); }
  /* The section's own address, as the server says it (`genelab.public`, from its manifest). */
  function here() { return (G.data && G.data.route) || '/anatomy/meta/gene-pool'; }
  function post(url, body) {
    G.said = ''; G.error = ''; G.asking = '';
    return call('POST', url, body);
  }
  /* A gene switched on or off, installed or removed: the navigation's links again. */
  function navAgain(j) {
    if (j && window.RouhNav) window.RouhNav.refresh();
    return j;
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('genesBody');
    if (!body || !G.open) return;
    if (G.editing && G.data && !G.busy) {
      var say0 = body.querySelector('.hb-say');
      if (say0) {
        say0.textContent = G.error || G.said;
        say0.className = 'hb-say' + (G.error ? ' bad' : '');
        say0.hidden = !(G.error || G.said);
      }
      return;
    }
    body.setAttribute('aria-busy', G.busy ? 'true' : 'false');
    body.textContent = '';
    var page = el('div', 'hb-page gn-page');
    body.appendChild(page);
    var say = el('p', 'hb-say' + (G.error ? ' bad' : ''), G.busy ? 'Working…' : (G.error || G.said));
    say.setAttribute('role', 'status');
    say.hidden = !(G.busy || G.error || G.said);
    page.appendChild(say);
    if (!G.data) {
      if (!G.error) page.appendChild(el('p', 'hb-empty', 'Reading the lab…'));
      return;
    }
    if (G.gene) drawGene(page, G.data, G.gene);
    else drawList(page, G.data);
  }

  function card(title, sub, cls) {
    var s = el('section', 'setting-card hb-card' + (cls ? ' ' + cls : ''));
    var h = el('h4', 'hb-h', title);
    if (sub) h.appendChild(el('span', 'hb-h-sub', sub));
    s.appendChild(h);
    return s;
  }
  function dl(rows, cls) {
    var d = el('dl', 'hb-ask-dl gn-dl' + (cls ? ' ' + cls : ''));
    rows.forEach(function (row) {
      if (!row[1]) return;
      d.appendChild(el('dt', '', row[0]));
      d.appendChild(el('dd', row[2] || '', row[1]));
    });
    return d;
  }
  function pill(text, cls) { return el('span', 'hb-pill' + (cls ? ' ' + cls : ''), text); }
  function toggle(label, on, act, disabled) {
    var b = el('button', 'gn-toggle');
    b.type = 'button';
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-checked', on ? 'true' : 'false');
    b.setAttribute('aria-label', label);
    b.appendChild(el('span', 'gn-knob'));
    b.appendChild(el('span', 'gn-toggle-word', on ? 'On' : 'Off'));
    b.disabled = G.busy || !!disabled;
    b.addEventListener('click', act);
    return b;
  }

  /* -- the list -- */

  function drawList(page, d) {
    page.appendChild(registryCard(d));
    page.appendChild(labCard(d));
    if (d.registry.url) page.appendChild(availableCard(d));
    if (d.history.length) page.appendChild(historyCard(d));
  }

  function registryCard(d) {
    var r = d.registry;
    var s = card('Gene registry', r.url ? '' : 'off', 'gn-registry');
    s.appendChild(el('p', 'settings-help', 'Shared genes come from a gene registry. Every list Rouh fetches from it ' +
      'is checked against the registry’s public key pinned here, a gene’s whole contract is shown before it is ' +
      'installed, and a gene is installed only when you say so, into the lab below, switched off.'));
    if (!r.url || G.changing) {
      if (!r.url) s.appendChild(el('p', 'hb-empty', 'Off: Rouh asks no registry anything until one is set here.'));
      if (d.admin) s.appendChild(registryForm(r));
      else s.appendChild(el('p', 'settings-help', 'Only an administrator of this organisation sets the registry.'));
      return s;
    }
    s.appendChild(dl([
      ['Registry', r.url, 'gn-mono'],
      ['Pinned key', r.key_id, 'gn-mono'],
      ['Index', r.index_made_at ? 'signed ' + whenIso(r.index_made_at) : 'not fetched yet'],
      ['Blocklist', r.blocklist_made_at ? 'signed ' + whenIso(r.blocklist_made_at) + ', ' +
        r.blocked_count + (r.blocked_count === 1 ? ' entry' : ' entries') : 'not fetched yet'],
      ['Checked', r.fetched_at ? when(r.fetched_at) + ', and every ' + everyText(d.every_minutes) : ''],
      ['Set by', r.set_by ? r.set_by + ', ' + when(r.set_at) : '']
    ]));
    if (r.error) s.appendChild(el('p', 'gn-warn', r.error));
    if (d.admin) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Check now', '', function () { post('/api/settings/genes/check', {}).then(navAgain); },
        'Fetch the registry’s blocklist and index now'));
      acts.appendChild(button('Change', '', function () { G.changing = true; G.said = ''; G.error = ''; draw(); },
        'Point Rouh at another registry, or pin another key'));
      acts.appendChild(button('Turn off', 'danger', function () {
        if (!window.confirm('Stop asking this registry anything? Genes already in the lab stay there.')) return;
        post('/api/settings/genes/registry/forget', {});
      }, 'Ask no registry anything'));
      s.appendChild(acts);
    }
    return s;
  }
  function everyText(minutes) {
    if (!minutes) return 'hour';
    if (minutes >= 60 && minutes % 60 === 0) return minutes === 60 ? 'hour' : (minutes / 60) + ' hours';
    if (minutes >= 1) return Math.round(minutes) + ' minutes';
    return Math.round(minutes * 60) + ' seconds';
  }

  function registryForm(r) {
    var f = el('form', 'hb-form gn-form');
    f.setAttribute('aria-label', 'Gene registry');
    f.setAttribute('autocomplete', 'off');
    f.addEventListener('input', function () { G.editing = true; });
    var a = el('label', 'hb-field wide');
    a.appendChild(el('span', '', 'Registry address'));
    var url = el('input');
    url.type = 'url';
    url.id = 'gnUrl';
    url.placeholder = 'https://rouh.land/registry/';
    url.value = r.url || '';
    url.spellcheck = false;
    url.maxLength = 500;
    a.appendChild(url);
    f.appendChild(a);
    var k = el('label', 'hb-field wide');
    k.appendChild(el('span', '', 'The registry’s public key (Ed25519, PEM)'));
    var key = el('textarea', 'gn-key');
    key.id = 'gnKey';
    key.rows = 4;
    key.spellcheck = false;
    key.placeholder = '-----BEGIN PUBLIC KEY-----\n…\n-----END PUBLIC KEY-----';
    key.value = r.public_key || '';
    k.appendChild(key);
    f.appendChild(k);
    var acts = el('div', 'hb-actions');
    var save = el('button', 'ctl small primary', 'Save and check');
    save.type = 'submit';
    save.disabled = G.busy;
    acts.appendChild(save);
    if (r.url) {
      acts.appendChild(button('Cancel', '', function () { G.changing = false; G.editing = false; draw(); }));
    }
    f.appendChild(acts);
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      G.editing = false;
      post('/api/settings/genes/registry', { url: url.value, public_key: key.value }).then(function (j) {
        if (j) { G.changing = false; draw(); }
      });
    });
    return f;
  }

  function labCard(d) {
    var s = card('The lab', d.installed.length ? String(d.installed.length) : '', 'gn-lab');
    var top = el('div', 'gn-lab-top');
    top.appendChild(el('p', 'settings-help', 'Shared genes arrive here, each behind its own switch, off. Their files ' +
      'are kept and never run. Switched on, a gene is in the navigation where its contract says, marked Shared. ' +
      'The lab’s own switch turns every shared gene off at once.'));
    if (d.admin) {
      top.appendChild(toggle('The lab is ' + (d.lab_on ? 'on' : 'off'), d.lab_on, function () {
        post('/api/settings/genes/lab', { on: !d.lab_on }).then(navAgain);
      }));
    }
    s.appendChild(top);
    if (!d.installed.length) {
      s.appendChild(el('p', 'hb-empty', 'Nothing in the lab yet.'));
      return s;
    }
    var list = el('ul', 'hb-list gn-list');
    d.installed.forEach(function (g) {
      var li = el('li', 'hb-beat gn-row gn-installed' + (g.on ? ' on' : ' off'));
      li.setAttribute('aria-label', g.name + ', in the lab');
      var words = el('div', 'gn-words');
      var line = el('div', 'hb-beat-top');
      line.appendChild(link(g.name, g.route, 'gn-name'));
      line.appendChild(pill(g.version, 'gn-ver'));
      if (g.state === 'blocked') line.appendChild(pill(g.blocked && g.blocked.severity === 'hard' ? 'Blocklisted' : 'Blocklisted for quality', 'failed'));
      if (g.update) line.appendChild(pill('Update: ' + g.update.version, 'blocking'));
      words.appendChild(line);
      words.appendChild(el('span', 'gn-sub', g.gene + (g.listing && g.listing.publisher_name ? ' · ' + g.listing.publisher_name : '')));
      li.appendChild(words);
      if (d.admin) {
        var hard = g.state === 'blocked' && g.blocked && g.blocked.severity === 'hard';
        li.appendChild(toggle(g.name + ' is ' + (g.switch_on ? 'on' : 'off'), g.switch_on, function () {
          post('/api/settings/genes/switch', { gene: g.gene, on: !g.switch_on }).then(navAgain);
        }, hard && !g.switch_on));
      }
      list.appendChild(li);
    });
    s.appendChild(list);
    return s;
  }

  function availableCard(d) {
    var s = card('In the registry', d.available.length ? String(d.available.length) : '', 'gn-available');
    if (!d.available.length) {
      s.appendChild(el('p', 'hb-empty', d.registry.index_made_at ? 'The registry lists no genes.' :
        'The index has not been fetched yet.'));
      return s;
    }
    s.appendChild(el('p', 'settings-help', 'Ratings are what people who reviewed a gene said at the registry. ' +
      'The registry cannot see who installed what, and a rating says how satisfied someone was, not that a gene is safe.'));
    var list = el('ul', 'hb-list gn-list');
    d.available.forEach(function (g) {
      var li = el('li', 'hb-beat gn-row');
      li.setAttribute('aria-label', g.sections.name + ', from ' + g.publisher_name);
      var words = el('div', 'gn-words');
      var line = el('div', 'hb-beat-top');
      line.appendChild(link(g.sections.name, here() + '/' + g.gene, 'gn-name'));
      line.appendChild(pill(g.version, 'gn-ver'));
      if (g.installed) line.appendChild(pill('In the lab' + (g.installed_version !== g.version ? ', ' + g.installed_version : ''), 'yes'));
      if (g.blocked) line.appendChild(pill('Blocklisted', 'failed'));
      words.appendChild(line);
      var what = g.sections.what || g.sections.title;
      if (what) words.appendChild(el('span', 'gn-what', what));
      var meta = [publisherText(g), rating(g.rating) ? 'rated ' + rating(g.rating) : 'not rated yet'];
      words.appendChild(el('span', 'gn-sub', meta.join(' · ')));
      li.appendChild(words);
      li.appendChild(link('Read its contract', here() + '/' + g.gene, 'ctl small gn-open'));
      list.appendChild(li);
    });
    s.appendChild(list);
    return s;
  }
  function publisherText(g) {
    var who = (g.listing ? g.listing.publisher_name : g.publisher_name) || g.publisher;
    var official = g.listing ? g.listing.official : g.official;
    var verified = g.listing ? g.listing.verified_publisher : g.verified_publisher;
    return 'by ' + who + (official ? ', the project’s own' : verified ? ' (verified publisher)' : '');
  }

  var WHAT = { installed: 'Installed', switched_on: 'Switched on', switched_off: 'Switched off', removed: 'Removed',
               blocked: 'Blocklisted', unblocked: 'Block lifted', update: 'Update seen', updated: 'Updated',
               registry: 'Registry', lab_on: 'Lab on', lab_off: 'Lab off' };
  function historyCard(d) {
    var s = card('What was done', '', 'gn-history');
    var list = el('ol', 'hb-list gn-hist');
    d.history.forEach(function (h) {
      var li = el('li', 'hb-beat gn-hist-row');
      var line = el('div', 'hb-beat-top');
      line.appendChild(el('span', 'hb-beat-what', (WHAT[h.what] || h.what) + (h.gene ? ': ' + h.gene + (h.version ? ' ' + h.version : '') : '')));
      line.appendChild(el('span', 'hb-beat-nums', when(h.at) + (h.by ? ' · ' + h.by : '')));
      li.appendChild(line);
      if (h.said) li.appendChild(el('p', 'gn-said', h.said));
      list.appendChild(li);
    });
    s.appendChild(list);
    return s;
  }

  /* -- one gene -- */

  function find(d, gene) {
    var inLab = null, listed = null;
    d.installed.forEach(function (g) { if (g.gene === gene) inLab = g; });
    d.available.forEach(function (g) { if (g.gene === gene) listed = g; });
    return { lab: inLab, listed: listed };
  }

  function drawGene(page, d, gene) {
    var back = el('p', 'gn-back');
    back.appendChild(link('‹ All genes', here()));
    page.appendChild(back);
    var f = find(d, gene);
    if (G.removed && G.removed.gene === gene) page.appendChild(removedCard(G.removed));
    var pulled = null;
    (d.blocked || []).forEach(function (b) { if (b.target.split(/[@ ]/)[0] === gene) pulled = pulled || b; });
    if (!f.lab && !f.listed && pulled) {
      page.appendChild(blockCard(pulled, false));
      return;
    }
    if (!f.lab && !f.listed) {
      var none = card(gene, '', 'gn-head');
      none.appendChild(el('p', 'hb-empty', d.registry.url ? 'The registry’s signed index has no gene ' + gene +
        ', and it is not in the lab.' : 'Rouh is not pointed at a gene registry, and ' + gene + ' is not in the lab.'));
      page.appendChild(none);
      return;
    }
    var shown = f.lab ? f.lab.contract : f.listed.sections;
    var version = f.lab ? f.lab.version : f.listed.version;
    page.appendChild(headCard(gene, shown, f));
    if (f.lab && f.lab.state === 'blocked') page.appendChild(blockCard(f.lab.blocked, true));
    else if (!f.lab && f.listed.blocked) page.appendChild(blockCard(f.listed.blocked, false));
    page.appendChild(contractCard(shown, version, f.lab ? 'Its contract, as installed' : 'Its contract, before you install it'));
    if (f.lab) {
      if (f.lab.update) page.appendChild(updateCard(d, f.lab));
      page.appendChild(labGeneCard(d, f.lab));
    } else if (d.admin && !f.listed.blocked) {
      page.appendChild(installCard(f.listed));
    }
  }

  function headCard(gene, s, f) {
    var g = f.lab || f.listed;
    var c = card(s.name, '', 'gn-head');
    c.querySelector('.hb-h').appendChild(pill('Shared', 'gn-shared'));
    if (s.title) c.appendChild(el('p', 'gn-title', s.title));
    var listing = f.lab ? f.lab.listing : f.listed;
    var r = rating(listing.rating), vr = rating(listing.version_rating);
    c.appendChild(dl([
      ['Gene', gene, 'gn-mono'],
      ['Publisher', publisherText(f.lab ? f.lab : f.listed).replace(/^by /, '')],
      ['Rating', r ? r + (vr && vr !== r ? '; this version ' + vr : '') : 'Not rated yet'],
      ['Version', (f.lab ? f.lab.version + ' installed' : f.listed.version) + (f.lab && f.listed && f.listed.version !== f.lab.version ? ', ' + f.listed.version + ' in the registry' : '')],
      ['Kind', g.kind === 'code' ? 'Reviewed code, from the Rouh project' : g.kind === 'brief' ? 'A brief and its tests' : g.kind],
      ['Fits', listing.core_range ? 'Rouh ' + listing.core_range : ''],
      ['Published', listing.published_at ? whenIso(listing.published_at) : '']
    ]));
    return c;
  }

  function blockCard(b, installed) {
    var c = card(b.severity === 'hard' ? 'Blocklisted by the registry' : 'Blocklisted for quality', '', 'gn-blocked');
    c.appendChild(el('p', 'gn-warn', b.reason));
    if (b.what_to_do) c.appendChild(dl([['What to do', b.what_to_do]]));
    c.appendChild(el('p', 'settings-help', installed
      ? (b.severity === 'hard' ? 'Rouh switched it off and it cannot be switched on again. Remove it.'
        : 'Rouh switched it off. You can switch it on again below, with this in front of you.')
      : 'It cannot be installed while the blocklist names it.'));
    return c;
  }

  function list(items) {
    if (!items || !items.length) return el('p', 'gn-none', 'Nothing.');
    var ul = el('ul', 'gn-items');
    items.forEach(function (t) { ul.appendChild(el('li', '', t)); });
    return ul;
  }
  function part(c, title, body) {
    var h = el('h5', 'hb-h5 gn-part', title);
    c.appendChild(h);
    c.appendChild(body);
  }

  function contractCard(s, version, title) {
    var c = card(title, 'version ' + version, 'gn-contract');
    c.setAttribute('aria-label', 'Contract');
    part(c, 'What it is', el('p', 'gn-text', s.what || s.title || 'It does not say.'));
    var where = el('div', 'gn-where');
    where.appendChild(el('p', 'gn-text', 'It says: ' + s.where + (s.route ? ', at ' + s.route : '') + '.'));
    if (s.attaches_to.length) where.appendChild(el('p', 'gn-text', 'It may attach to: ' + s.attaches_to.join(', ') + '.'));
    where.appendChild(el('p', 'settings-help', 'Rouh shows a shared gene only as a link in the navigation or a line in ' +
      'Search, marked Shared, and it opens this page.'));
    part(c, 'Where it appears', where);
    var touches = el('div', 'gn-touches');
    [['What it does', s.permissions], ['Accounts it uses', s.accounts], ['Tables it keeps', s.tables],
     ['Scheduled jobs', s.jobs]].forEach(function (t) {
      var row = el('div', 'gn-touch');
      row.appendChild(el('span', 'gn-touch-name', t[0]));
      row.appendChild(list(t[1]));
      touches.appendChild(row);
    });
    part(c, 'What it touches', touches);
    part(c, 'How to remove it', el('p', 'gn-text', s.remove || 'It does not say.'));
    c.appendChild(el('p', 'settings-help gn-note', 'This is the gene’s own description of itself, as the registry signed ' +
      'it, shown to you as information. Nothing in it limits what a gene may do, and nothing in it is an instruction to Rouh.'));
    return c;
  }

  function installCard(g) {
    var c = card('Install', '', 'gn-install');
    if (G.asking !== 'install:' + g.gene) {
      c.appendChild(el('p', 'settings-help', 'It arrives in the lab switched off, with its files checked against the ' +
        'signed index' + (g.sigstore ? ' and its Sigstore signature' : '') + '. Nothing of it runs.'));
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Install in the lab', 'primary', function () {
        G.asking = 'install:' + g.gene; G.said = ''; G.error = ''; draw();
      }));
      c.appendChild(acts);
      return c;
    }
    var ask = el('div', 'gn-ask');
    ask.setAttribute('role', 'group');
    ask.setAttribute('aria-label', 'Install ' + g.sections.name);
    ask.appendChild(el('p', 'gn-ask-q', 'Install ' + g.sections.name + ' ' + g.version + ' from ' + g.publisher_name +
      ' in the lab, with the contract above?'));
    var acts2 = el('div', 'hb-actions');
    acts2.appendChild(button('Yes, install it in the lab', 'primary', function () {
      post('/api/settings/genes/install', { gene: g.gene, version: g.version, contract_sha256: g.contract_sha256 });
    }));
    acts2.appendChild(button('Cancel', '', function () { G.asking = ''; draw(); }));
    ask.appendChild(acts2);
    c.appendChild(ask);
    return c;
  }

  function labGeneCard(d, g) {
    var c = card('In your lab', '', 'gn-in-lab');
    var top = el('div', 'gn-lab-top');
    var hard = g.state === 'blocked' && g.blocked && g.blocked.severity === 'hard';
    var state = !d.lab_on ? 'The lab is off, so it is not shown anywhere, whatever its switch says.'
      : g.switch_on ? 'On: ' + g.contract.where + ', marked Shared.' : 'Off: not in the navigation or Search.';
    top.appendChild(el('p', 'gn-text', state));
    if (d.admin) {
      top.appendChild(toggle(g.name + ' is ' + (g.switch_on ? 'on' : 'off'), g.switch_on, function () {
        post('/api/settings/genes/switch', { gene: g.gene, on: !g.switch_on }).then(navAgain);
      }, hard && !g.switch_on));
    }
    c.appendChild(top);
    var checks = el('ul', 'cf-checks gn-checks');
    checks.setAttribute('aria-label', 'How its files were checked');
    [[true, 'Signed index', 'The index naming it was signed by the pinned key.'],
     [true, 'Its files', 'Their SHA-256 is the one the signed index names: ' + g.sha256.slice(0, 16) + '…'],
     [g.sigstore && g.sigstore.state === 'verified' ? true : null, 'Sigstore', g.sigstore ? g.sigstore.said : '']
    ].forEach(function (row) {
      var li = el('li', 'cf-check ' + (row[0] ? 'ok' : 'opt'));
      li.appendChild(el('span', 'cf-mark', row[0] ? '✓' : '–'));
      li.appendChild(el('span', 'cf-check-name', row[1]));
      li.appendChild(el('span', 'cf-check-said', row[2]));
      checks.appendChild(li);
    });
    c.appendChild(checks);
    c.appendChild(dl([['Installed', (g.installed_by ? g.installed_by + ', ' : '') + when(g.installed_at)],
                      ['Its switch', g.switch, 'gn-mono']]));
    c.appendChild(filesPart(g));
    if (d.admin) c.appendChild(removePart(g));
    return c;
  }

  function filesPart(g) {
    var wrap = el('div', 'gn-files');
    wrap.appendChild(el('h5', 'hb-h5', 'Its files (' + g.files.length + '), kept here and never run'));
    var ul = el('ul', 'gn-file-list');
    g.files.forEach(function (f) {
      var li = el('li', 'gn-file');
      var b = el('button', 'gn-file-name', f.path);
      b.type = 'button';
      b.setAttribute('aria-expanded', G.file && G.file.gene === g.gene && G.file.path === f.path ? 'true' : 'false');
      b.addEventListener('click', function () {
        if (G.file && G.file.gene === g.gene && G.file.path === f.path) { G.file = null; draw(); return; }
        G.file = { gene: g.gene, path: f.path, text: null, said: 'Reading…' };
        draw();
        fetch('/api/settings/genes/file?gene=' + encodeURIComponent(g.gene) + '&path=' + encodeURIComponent(f.path),
              { credentials: 'same-origin', cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (!G.file || G.file.path !== f.path) return;
            G.file = { gene: g.gene, path: f.path, text: j.text, said: j.error || j.said || '' };
            draw();
          })
          .catch(function () { G.file = { gene: g.gene, path: f.path, text: null, said: 'It could not be read.' }; draw(); });
      });
      li.appendChild(b);
      li.appendChild(el('span', 'gn-file-size', size(f.size)));
      if (G.file && G.file.gene === g.gene && G.file.path === f.path) {
        if (G.file.text != null) {
          var pre = el('pre', 'gn-file-text', G.file.text);
          pre.setAttribute('aria-label', f.path);
          li.appendChild(pre);
        } else {
          li.appendChild(el('p', 'hb-empty', G.file.said));
        }
      }
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }
  function size(n) {
    if (n < 1024) return n + ' bytes';
    if (n < 1024 * 1024) return Math.round(n / 102.4) / 10 + ' KB';
    return Math.round(n / 104857.6) / 10 + ' MB';
  }

  function removePart(g) {
    var wrap = el('div', 'gn-remove');
    if (G.asking !== 'remove:' + g.gene) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Remove', 'danger', function () { G.asking = 'remove:' + g.gene; G.said = ''; G.error = ''; draw(); },
        'Take it out of Rouh, and check nothing is left'));
      wrap.appendChild(acts);
      return wrap;
    }
    var ask = el('div', 'gn-ask');
    ask.setAttribute('role', 'group');
    ask.setAttribute('aria-label', 'Remove ' + g.name);
    ask.appendChild(el('p', 'gn-ask-q', 'Remove ' + g.name + '? Its files and its switch are deleted, and Rouh then ' +
      'checks that nothing named for it is left.'));
    var acts2 = el('div', 'hb-actions');
    acts2.appendChild(button('Yes, remove it', 'danger', function () {
      post('/api/settings/genes/remove', { gene: g.gene }).then(function (j) {
        if (j && j.check) { G.removed = { gene: g.gene, check: j.check, said: j.said }; G.file = null; draw(); }
        navAgain(j);
      });
    }));
    acts2.appendChild(button('Cancel', '', function () { G.asking = ''; draw(); }));
    ask.appendChild(acts2);
    wrap.appendChild(ask);
    return wrap;
  }

  function removedCard(r) {
    var c = card(r.check.ok ? 'Removed, and Rouh is as it was' : 'Removed, and something is left', '', 'gn-removed');
    var ul = el('ul', 'cf-checks');
    ul.setAttribute('aria-label', 'The check after it was removed');
    r.check.checks.forEach(function (t) {
      var li = el('li', 'cf-check ' + (t.gone ? 'ok' : 'bad'));
      li.appendChild(el('span', 'cf-mark', t.gone ? '✓' : '✗'));
      li.appendChild(el('span', 'cf-check-name', t.what));
      li.appendChild(el('span', 'cf-check-said', t.gone ? 'gone' : 'still there'));
      ul.appendChild(li);
    });
    var same = el('li', 'cf-check ' + (r.check.differences.length ? 'bad' : 'ok'));
    same.appendChild(el('span', 'cf-mark', r.check.differences.length ? '✗' : '✓'));
    same.appendChild(el('span', 'cf-check-name', 'The lab, against just before it came'));
    same.appendChild(el('span', 'cf-check-said', r.check.differences.length ? r.check.differences.join('; ') : 'the same'));
    ul.appendChild(same);
    c.appendChild(ul);
    return c;
  }

  function updateCard(d, g) {
    var u = g.update;
    var c = card('An update is waiting: ' + u.version, 'from ' + g.version, 'gn-update');
    if (!u.changes.length) {
      c.appendChild(el('p', 'gn-text', 'Nothing in its contract changed.'));
    } else {
      c.appendChild(el('h5', 'hb-h5', 'What changed in its contract'));
      var ul = el('ul', 'gn-changes');
      u.changes.forEach(function (ch) {
        var li = el('li', 'gn-change');
        li.appendChild(el('span', 'gn-change-name', ch.label));
        var what = el('div', 'gn-change-what');
        (ch.added || []).forEach(function (t) { what.appendChild(el('p', 'gn-added', '+ ' + t)); });
        (ch.gone || []).forEach(function (t) { what.appendChild(el('p', 'gn-gone', '− ' + t)); });
        if (ch.now != null || ch.was != null) {
          if (ch.was) what.appendChild(el('p', 'gn-gone', 'Was: ' + ch.was));
          what.appendChild(el('p', 'gn-added', 'Now: ' + (ch.now || 'nothing')));
        }
        li.appendChild(what);
        ul.appendChild(li);
      });
      c.appendChild(ul);
    }
    c.appendChild(el('p', 'settings-help', 'Rouh never installs an update by itself. Its switch stays as it is now.'));
    if (d.admin && !(g.state === 'blocked' && g.blocked && g.blocked.severity === 'hard')) {
      var acts = el('div', 'hb-actions');
      acts.appendChild(button('Yes, update to ' + u.version, 'primary', function () {
        post('/api/settings/genes/update', { gene: g.gene, version: u.version, contract_sha256: u.contract_sha256 });
      }));
      c.appendChild(acts);
    }
    return c;
  }

  /* ---- shown and left ---- */

  function shownNow(gene) {
    var g = String(gene || '');
    var was = G.open;
    G.open = true;
    if (g !== G.gene) {
      G.gene = g;
      G.asking = '';
      G.file = null;
      G.editing = false;
      if (G.removed && G.removed.gene !== g) G.removed = null;
      if (was) { G.said = ''; G.error = ''; }
    }
    if (!was) { G.said = ''; G.error = ''; G.changing = false; G.editing = false; }
    draw();
    load();
    var body = $('genesBody');
    var scroller = body && body.closest ? body.closest('.settings-body') : null;
    if (scroller) scroller.scrollTop = 0;
  }

  function hiddenNow() {
    G.open = false;
    G.asking = '';
    G.editing = false;
    G.changing = false;
    G.file = null;
    G.removed = null;
  }

  window.RouhGenes = { shown: shownNow, hidden: hiddenNow, reload: load };
})();
