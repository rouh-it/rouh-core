/* Synapse's lab: the homepage and the debugger (`rouh/synapse/`, `rouh/web/synapse.py`).

   Petar asked to SEE how facts are stored, edited and retrieved. So every
   operation on a dataset is a trace with steps (`rouh/synapse/trace.py`), and
   this file draws them: storing an item step by step, an edit and what it
   changed, a deletion and its cascade, a question as a walk played one
   expansion at a time over a graph, the pack, the answer and what it used,
   and every model, decision and database call with its cost and time.

   At /synapse it draws the homepage: the datasets, its models and backends,
   the starting numbers, and what is not built yet. At
   /synapse/<dataset> it draws that dataset's debugger in tabs. Beside both is
   the Synapse chat, the one chat for the whole of Synapse rather than one per
   dataset (fr_df883b2daae8, `rouh/synapse/chat.py`), opened through
   `window.RouhSynapseHost`, which app.js hands over, as it does for the
   Control Room. It acts on the dataset on the screen, and a fork of it, made
   with Rouh's own Fork, stays on the dataset it was made over. Whatever it does
   shows up here as it happens, because the Activity list is read again every
   couple of seconds while a dataset is open.

   Every heading, column, field and attribute has an (i) beside it that opens
   what that part of the page means, in general, and a 🤷‍♂️ in it that says it
   again another way (fr_bc51d0de9b2b, `rouh/synapse/explain.py`).

   Dark only, like the rest of Rouh, and laid out for a desk and a phone. */
(function () {
  'use strict';

  var API = '/api/synapse';
  var S = {
    open: false, ds: '', home: null, data: null, tab: 'activity', follow: true,
    timer: null, busy: false, traceId: '', traceData: null, lastSeen: '', activity: null,
    item: '', itemData: null, items: null, itemFilter: { q: '', kind: '', origin: '' }, itemsTotal: 0,
    query: '', queryData: null, frame: 0, playing: null, speed: 900, queries: null,
    graph: null, graphFilter: { min: 0, types: {} }, mapData: null, mapViewer: '', search: null,
    tuneDraft: {}, compare: null, evalData: null, evalRun: '', evalRunData: null,
    addMode: 'note', explore: 'graph', editing: false, error: '', homeConfirm: '',
    // The Improvements page (`rouh/synapse/improvements.py`): its list, and the attempt open on it.
    page: '', attempt: '', imp: null, impOne: null, impError: '', impTick: 0,
    // The Dreams tab (`rouh/synapse/dreaming.py`): the nights, the one open ('' newest, a number, or
    // 'waiting'), and its filters.
    dreams: null, dreamView: '', dreamNight: null, dreamWaiting: null, dreamFilter: { kinds: {}, state: '', area: '', q: '' },
    dreamFocus: 0, dreamTick: 0, dreamConfirm: false,
    // The Vocabulary page (`rouh/vocabulary.py`): the entries, the words searched for, the entry open in its
    // form ('' none, 'new', or an id) and what is typed there, the one asked about before it is deleted, and
    // the server's refusal of a save.
    vocab: null, vocabQ: '', vocabEdit: '', vocabDraft: null, vocabConfirm: '', vocabError: '', vocabRefused: ''
  };
  var TABS = [['activity', 'Activity'], ['dreams', 'Dreams'], ['add', 'Add'], ['items', 'Items'], ['retrieve', 'Retrieve'],
    ['explore', 'Explore'], ['tune', 'Tune'], ['evaluate', 'Evaluate']];
  var KIND_COLOUR = { vocabulary: '#c9a2ff', mail: '#5ec2ff', note: '#57d9a3', doc: '#7ec86c', task: '#f2b45e', project: '#e2b04d',
    person: '#ab8ff3', place: '#9fb4ff', topic: '#f07ea2', layer: '#ffd166', rule: '#ff7a70', event: '#4cc4b0',
    file: '#a3adbb', chat_turn: '#a3adbb', rouh_said: '#64707f', card: '#a3adbb' };
  var TYPE_COLOUR = { from: '#8d9aac', to: '#8d9aac', cc: '#64707f', in_thread: '#5ec2ff', reply_to: '#5ec2ff',
    'in': '#f2b45e', same_as: '#ab8ff3', attached: '#a3adbb', about: '#57d9a3', follows_up: '#4cc4b0', continues: '#5ec2ff',
    contradicts: '#ff7a70', updates: '#ffd166', rule_for: '#ff7a70', built_from: '#ffd166' };

  function host() { return window.RouhSynapseHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      if (Array.isArray(c)) { c.forEach(function (x) { if (x) parent.appendChild(x); }); continue; }
      parent.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return parent;
  }
  function btn(text, cls, onClick, title) {
    var b = el('button', 'syn-btn' + (cls ? ' ' + cls : ''), text);
    b.type = 'button';
    if (title) b.title = title;
    if (onClick) b.addEventListener('click', onClick);
    return b;
  }
  // A control that takes the person somewhere: a link to that address, so
  // Cmd-click, the middle button and Open link in new tab open it in a tab of
  // its own. A plain press stays here and does what `onClick` does: the page
  // around this leaves it to the handler (`data-inapp`, app/helpers.js).
  function goBtn(text, cls, href, onClick, title) {
    var a = el('a', 'syn-btn' + (cls ? ' ' + cls : ''), text);
    a.href = href;
    a.setAttribute('data-inapp', '');
    if (title) a.title = title;
    if (onClick) a.addEventListener('click', onClick);
    return a;
  }
  function dsHref(id) { return '/synapse/' + encodeURIComponent(id); }
  function money(n) {
    n = Number(n || 0);
    if (!n) return '$0';
    if (n < 0.01) return '$' + n.toFixed(5);
    return '$' + n.toFixed(3);
  }
  function msText(n) {
    if (n == null) return '';
    n = Number(n);
    if (n < 1000) return Math.round(n) + ' ms';
    return (n / 1000).toFixed(n < 10000 ? 1 : 0) + ' s';
  }
  function num(n, d) { return n == null ? '' : Number(n).toFixed(d == null ? 3 : d); }
  function when(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return String(iso);
    var today = new Date();
    var t = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + ':' +
      String(d.getSeconds()).padStart(2, '0');
    if (d.toDateString() === today.toDateString()) return t;
    return d.getDate() + ' ' + d.toLocaleString('en-GB', { month: 'short' }) + ' ' + t;
  }
  function day(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.getDate() + ' ' + d.toLocaleString('en-GB', { month: 'short' }) + ' ' + d.getFullYear();
  }
  function chip(what, n, cls) {
    var c = el('span', 'syn-chip' + (cls ? ' ' + cls : ''), n + ' ' + what);
    c.dataset.explain = 'The count of ' + what + ' in a dataset';
    return c;
  }
  // A heading whose words carry this dataset's values, explained by its
  // generic name instead.
  function named(node, key) { node.dataset.explain = key; return node; }
  function rowLabel(text) { return el('span', 'syn-rowlabel', text); }
  function short(id) { return String(id || '').slice(0, 8); }
  // Readers, owners and askers are people since 3 October 2026: ids, said by name.
  function peopleNames() {
    var out = { everyone: 'everyone' };
    ((S.data && S.data.people) || []).forEach(function (p) { out[p.key] = p.name; });
    return out;
  }
  function nameOf(id) { return peopleNames()[id] || id; }
  // Readers are picked, never typed (4 October 2026): the box searches the owner's people set
  // (`/people`, `people.search`) and only a person chosen from its list, or everyone, is kept,
  // so what is saved is always a person's id. `chosen` is [{id, name}], as the server names them.
  var pickSeq = 0;
  function peoplePicker(label, chosen, opts) {
    opts = opts || {};
    var id = 'synPick' + (++pickSeq);
    var picked = (chosen || []).filter(function (p) { return p && p.id; }).map(function (p) { return { id: p.id, name: p.name || nameOf(p.id) }; });
    var wrap = el('div', 'syn-field syn-pick-field');
    var lab = el('span', null, label);
    var box = el('div', 'syn-pick');
    var chips = el('span', 'syn-pick-chips');
    var input = el('input', 'syn-pick-in');
    input.type = 'text'; input.autocomplete = 'off'; input.spellcheck = false;
    input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-controls', id + 'List');
    input.setAttribute('aria-label', label);
    var list = el('ul', 'syn-pick-list'); list.id = id + 'List'; list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', label + ' found'); list.hidden = true;
    var say = el('p', 'syn-pick-say'); say.hidden = true; say.setAttribute('aria-live', 'polite');
    var shown = [], active = -1, seq = 0, timer = 0, quiet = false;

    function has(pid) { return picked.some(function (p) { return p.id === pid; }); }
    function drawChips() {
      chips.replaceChildren();
      picked.forEach(function (p, n) {
        var c = el('span', 'syn-pchip');
        var x = el('button', 'syn-pchip-x', '×'); x.type = 'button';
        x.setAttribute('aria-label', 'Remove ' + p.name);
        x.addEventListener('click', function () { picked.splice(n, 1); drawChips(); input.focus(); });
        add(c, el('span', null, p.name), x);
        chips.appendChild(c);
      });
      input.placeholder = picked.length ? 'Add another' : (opts.empty || 'Search your people');
    }
    function close() { list.hidden = true; active = -1; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
    function mark(n) {
      active = n;
      Array.prototype.forEach.call(list.querySelectorAll('[role=option]'), function (li, k) {
        li.setAttribute('aria-selected', k === n ? 'true' : 'false');
        if (k === n) { input.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest' }); }
      });
    }
    function choose(p) {
      if (!has(p.id)) picked.push({ id: p.id, name: p.name });
      input.value = ''; say.hidden = true; drawChips(); close(); input.focus();
    }
    function draw(typed, people) {
      var t = typed.trim().toLowerCase();
      shown = [];
      if ('everyone'.indexOf(t) === 0 || (t.length > 2 && t.indexOf('every') === 0)) shown.push({ id: 'everyone', name: 'everyone', detail: 'anyone who can ask this dataset' });
      people.forEach(function (p) { shown.push({ id: p.id, name: p.name, detail: p.me ? 'you' + (p.detail ? ', ' + p.detail : '') : p.detail }); });
      shown = shown.filter(function (p) { return !has(p.id); });
      list.replaceChildren();
      shown.forEach(function (p, n) {
        var li = el('li', 'syn-pick-opt'); li.id = id + 'O' + n; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false');
        add(li, el('span', 'syn-pick-name', p.name), p.detail ? el('span', 'syn-pick-detail', p.detail) : null);
        li.addEventListener('mousedown', function (e) { e.preventDefault(); });
        li.addEventListener('click', function () { choose(p); });
        list.appendChild(li);
      });
      if (!shown.length) {
        var none = el('li', 'syn-pick-none', t ? 'Nobody in your people matches “' + typed.trim() + '”.' : 'Type a name, an address or a phone number.');
        none.setAttribute('role', 'presentation');
        list.appendChild(none);
      }
      list.hidden = false; input.setAttribute('aria-expanded', 'true');
      mark(shown.length && t ? 0 : -1);
    }
    function look() {
      var q = input.value, mine = ++seq;
      api(dsPath('/people?q=' + encodeURIComponent(q.trim()))).then(function (j) {
        if (mine !== seq || document.activeElement !== input) return;
        draw(q, (j && j.people) || []);
      }).catch(function (e) { if (mine === seq) { say.textContent = e.message; say.hidden = false; } });
    }
    input.addEventListener('input', function () { say.hidden = true; clearTimeout(timer); timer = setTimeout(look, 140); });
    input.addEventListener('focus', function () { if (quiet) { quiet = false; return; } look(); });
    input.addEventListener('blur', function () { seq++; clearTimeout(timer); close(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (list.hidden) { look(); return; }
        if (!shown.length) return;
        mark(e.key === 'ArrowDown' ? (active + 1) % shown.length : (active <= 0 ? shown.length - 1 : active - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (!list.hidden && active >= 0 && shown[active]) choose(shown[active]);
      } else if (e.key === 'Escape') {
        if (!list.hidden) { e.preventDefault(); e.stopPropagation(); close(); }
      } else if (e.key === 'Backspace' && !input.value && picked.length) {
        picked.pop(); drawChips();
      }
    });
    box.addEventListener('mousedown', function (e) { if (e.target === box || e.target === chips) { e.preventDefault(); input.focus(); } });
    add(box, chips, input, list);
    add(wrap, lab, box, say);
    drawChips();
    return {
      node: wrap,
      ids: function () { return picked.map(function (p) { return p.id; }); },
      // What stops a save: words typed and never picked, or nobody when somebody is needed.
      problem: function (needOne) {
        var left = input.value.trim(), why = '';
        if (left) why = '“' + left + '” is not a person yet: pick one from the list, or clear it.';
        else if (needOne && !picked.length) why = 'Pick at least one reader, or everyone.';
        say.textContent = why; say.hidden = !why;
        if (why) { quiet = document.activeElement !== input; input.focus(); }
        return why;
      }
    };
  }
  function originChip(origin) {
    if (!origin) return null;
    return el('span', 'syn-origin o-' + origin, origin === 'icloud' ? 'from contacts' : 'made by Synapse');
  }
  function plural(n, one, many) { return n + ' ' + (Number(n) === 1 ? one : (many || one + 's')); }

  function api(path, opts) { return call(API + path, opts); }
  function call(url, opts) {
    opts = opts || {};
    var init = { method: opts.method || (opts.body ? 'POST' : 'GET'), credentials: 'same-origin', headers: {} };
    if (opts.body && !(opts.body instanceof FormData)) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    } else if (opts.body) {
      init.body = opts.body;
    }
    return fetch(url, init).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
        if (!r.ok) throw new Error((j && (j.error || j.why)) || ('HTTP ' + r.status));
        return j;
      });
    });
  }
  function dsPath(p) { return '/ds/' + S.ds + (p || ''); }

  function say(text, kind) {
    var box = el('p', 'syn-say' + (kind ? ' ' + kind : ''), text);
    return box;
  }
  function flash(text, kind) {
    var meta = $('synMeta');
    if (!meta) return;
    meta.textContent = text;
    meta.className = 'run-meta syn-flash' + (kind ? ' ' + kind : '');
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { meta.textContent = ''; meta.className = 'run-meta'; renderMeta(); }, 4500);
  }

  /* ----------------------------------------------------------------- the layer */

  window.RouhSynapse = {
    shown: function (ds) {
      S.open = true;
      // `improvements` and `improvements/<n>` are the Improvements page and one attempt on it.
      var imp = /^improvements(?:\/(\d+))?$/.exec(ds || '');
      if (ds === 'vocabulary') {
        if (S.ds) resetDataset();
        S.ds = '';
        S.page = 'vocabulary';
        host().dataset && host().dataset('vocabulary', 'Vocabulary');
        watchForLabels();
        draw();
        stopPolling();
        synapseChat(false);
        return;
      }
      if (imp) {
        if (S.ds) resetDataset();
        S.ds = '';
        S.page = 'improvements';
        if (S.attempt !== (imp[1] || '')) S.impOne = null;
        S.attempt = imp[1] || '';
        host().dataset && host().dataset(ds, S.attempt ? 'Attempt ' + S.attempt : 'Improvements');
        watchForLabels();
        draw();
        startPolling();
        synapseChat(false);
        return;
      }
      S.page = '';
      // `<dataset>/dreams`, `<dataset>/dreams/<night>` and `<dataset>/dreams/waiting`: the Dreams tab.
      var dr = /^([0-9a-f-]{36})\/dreams(?:\/(\d+|waiting))?$/.exec(ds || '');
      if (dr) {
        if (dr[1] !== S.ds) { resetDataset(); S.ds = dr[1]; }
        S.tab = 'dreams';
        if (S.dreamView !== (dr[2] || '')) { S.dreamView = dr[2] || ''; S.dreamNight = null; }
      } else if (ds !== S.ds) { resetDataset(); S.ds = ds || ''; }
      watchForLabels();
      draw();
      startPolling();
      synapseChat(false);
    },
    hidden: function () {
      S.open = false;
      closeExplain(false);
      stopPlay();
      stopPolling();
    }
  };

  function resetDataset() {
    S.data = null; S.activity = null; S.traceId = ''; S.traceData = null; S.item = ''; S.itemData = null;
    S.items = null; S.query = ''; S.queryData = null; S.frame = 0; S.queries = null; S.graph = null;
    S.mapData = null; S.search = null; S.tuneDraft = {}; S.compare = null; S.evalData = null; S.evalRun = '';
    S.evalRunData = null; S.lastSeen = ''; S.tab = 'activity'; S.editing = false;
    S.dreams = null; S.dreamView = ''; S.dreamNight = null; S.dreamWaiting = null; S.dreamFocus = 0; S.dreamConfirm = false;
    S.dreamFilter = { kinds: {}, state: '', area: '', q: '' };
    stopPlay();
  }

  function openDataset(id, name, tab) {
    resetDataset();
    S.page = '';
    S.ds = id;
    if (tab) S.tab = tab;
    host().dataset && host().dataset(id, name || '');
    draw();
    synapseChat(false);
  }

  function goHome() {
    resetDataset();
    S.page = '';
    S.ds = '';
    host().dataset && host().dataset('', '');
    draw();
    synapseChat(false);
  }

  // The Synapse chat beside the lab, told which dataset is on the screen. A
  // chat already open that is it, or a fork of it, stays: opening another
  // dataset never changes the chat or its name. `show` is a press for the
  // chat itself, which always goes to the Synapse chat.
  function synapseChat(show) {
    var active = host().activeChat ? host().activeChat() : '';
    return api('/chat', { body: { dataset: S.ds || '', active: active } }).then(function (j) {
      if (!j || !j.chat || !host().chat) return;
      if (show || !j.keep) host().chat(j.chat, show);
    }).catch(function () {});
  }

  function startPolling() {
    stopPolling();
    S.timer = setInterval(tick, 2000);
  }
  function stopPolling() { if (S.timer) clearInterval(S.timer); S.timer = null; }

  function tick() {
    if (!S.open || document.hidden) return;
    if (S.page === 'improvements') {
      // An attempt still running is read again every ten seconds, until it has finished.
      var live = S.attempt ? (S.impOne && S.impOne.outcome === 'running')
        : (S.imp && (S.imp.attempts || []).some(function (a) { return a.outcome === 'running'; }));
      if (live && ++S.impTick % 5 === 0) loadImprovements(true);
      return;
    }
    if (!S.ds) {
      var filling = (S.home && S.home.datasets || []).some(function (d) { return Number(d.waiting) > 0; });
      if (filling && !S.busy) loadHome(true);
      return;
    }
    loadActivity(true);
    if (S.tab === 'dreams') dreamsTick();
    if (S.traceId && S.traceData && S.traceData.status !== 'done' && S.traceData.status !== 'failed') loadTrace(S.traceId, true);
    if (S.query && S.queryData && S.queryData.status === 'running') loadQuery(S.query, true);
    if (S.tab === 'evaluate' && S.evalRun && S.evalRunData && S.evalRunData.status === 'running') loadEvalRun(S.evalRun, true);
  }

  function draw() {
    var body = $('synBody');
    if (!body) return;
    if (S.page === 'improvements') {
      $('synTitle').textContent = 'Synapse';
      renderImprovements(body);
      renderMeta();
      return;
    }
    if (S.page === 'vocabulary') {
      $('synTitle').textContent = 'Synapse';
      renderVocabulary(body);
      renderMeta();
      return;
    }
    if (!S.ds) {
      $('synTitle').textContent = 'Synapse';
      if (!S.home) { body.replaceChildren(el('p', 'syn-loading', 'Reading Synapse...')); loadHome(); return; }
      renderHome(body);
    } else {
      if (!S.data) { body.replaceChildren(el('p', 'syn-loading', 'Opening the dataset...')); loadDataset(); return; }
      renderDataset(body);
    }
    renderMeta();
  }

  function renderMeta() {
    var meta = $('synMeta');
    if (!meta || meta.classList.contains('syn-flash')) return;
    if (S.page === 'improvements') {
      meta.textContent = S.imp ? plural((S.imp.attempts || []).length, 'attempt') + ' to make Synapse better' : '';
      return;
    }
    if (S.page === 'vocabulary') {
      meta.textContent = S.vocab ? plural((S.vocab.entries || []).length, 'entry', 'entries') + ' in ' + S.vocab.master : '';
      return;
    }
    if (!S.ds) {
      meta.textContent = S.home ? plural((S.home.datasets || []).length, 'dataset') + ', each kept apart from the others' : '';
      return;
    }
    var c = (S.data && S.data.counts) || {};
    if (S.data && S.data.dataset.role === 'people') {
      meta.textContent = plural(c.people || 0, 'person', 'people') + ', the people every real dataset resolves against';
      return;
    }
    meta.textContent = S.data ? (plural(c.items || 0, 'item') + ', ' + plural(c.links || 0, 'link') + ', ' +
      plural(c.layers || 0, 'layer') + ', ' + money(c.cost) + ' spent') : '';
  }


  /* ------------------------------------------------------------ the Vocabulary page

     The person's own words and nicknames, and what they mean by them (`rouh/vocabulary.py`,
     `rouh/web/vocabulary.py`), at /synapse/vocabulary, in the Memory group. Each entry is an item of kind
     vocabulary in Synapse Master: its word, what it means, its other names, what it is about (a person, a
     task or a project) and its silos. A message that uses the word or another name is given the entry in its
     background memory. Until 30 October 2026 these were "Your words" on the Rules page. */

  function vocabApi(path, body) {
    return call('/api/vocabulary' + (path || ''), body ? { body: body } : {});
  }

  function loadVocabulary() {
    return vocabApi('').then(function (j) {
      if (S.page !== 'vocabulary') return;
      S.vocab = j; S.vocabError = '';
      draw();
    }).catch(function (e) {
      if (S.page !== 'vocabulary') return;
      S.vocabError = e.message;
      draw();
    });
  }

  function vocabNames(e) { return [e.term].concat(e.aliases || []); }

  function vocabMatches(e, q) {
    q = String(q || '').toLowerCase().trim();
    if (!q) return true;
    var hay = vocabNames(e).concat([e.meaning]).concat((e.context || []).map(function (c) { return c.name; }))
      .join(' ').toLowerCase();
    return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function renderVocabulary(body) {
    keepScroll(function () {
      if (S.vocabError && !S.vocab) { body.replaceChildren(say('Vocabulary could not be read: ' + S.vocabError, 'bad')); return; }
      if (!S.vocab) { body.replaceChildren(el('p', 'syn-loading', 'Reading your vocabulary...')); loadVocabulary(); return; }
      body.replaceChildren(drawVocabulary(S.vocab));
    });
  }

  function drawVocabulary(d) {
    var wrap = el('div', 'syn-imp syn-vocab');
    var top = el('div', 'syn-top');
    add(top, goBtn('All datasets', 'quiet', '/synapse', goHome), el('h5', 'syn-imp-title', 'Vocabulary'));
    wrap.appendChild(top);
    wrap.appendChild(el('p', 'syn-note', 'Your own words and nicknames, and what you mean by them. When a message uses one, ' +
      'Rouh is given its meaning.'));
    var bar = el('div', 'syn-row');
    var q = el('input', 'syn-in syn-vocab-q');
    q.type = 'search';
    q.placeholder = 'Search your vocabulary';
    q.setAttribute('aria-label', 'Search your vocabulary');
    q.value = S.vocabQ;
    var list = el('ul', 'syn-vocab-list');
    list.setAttribute('aria-label', 'Your vocabulary');
    q.addEventListener('input', function () { S.vocabQ = q.value; drawVocabList(list, d); });
    add(bar, q);
    if (S.vocabEdit !== 'new') {
      bar.appendChild(btn('Add an entry', 'primary', function () {
        S.vocabEdit = 'new'; S.vocabRefused = ''; S.vocabDraft = vocabDraftOf(null); draw();
      }));
    }
    wrap.appendChild(bar);
    if (S.vocabEdit === 'new') wrap.appendChild(vocabForm(null));
    drawVocabList(list, d);
    wrap.appendChild(list);
    return wrap;
  }

  function drawVocabList(list, d) {
    list.replaceChildren();
    var shown = (d.entries || []).filter(function (e) { return vocabMatches(e, S.vocabQ); });
    shown.forEach(function (e) { list.appendChild(S.vocabEdit === e.id ? vocabForm(e) : vocabRow(e)); });
    if (!shown.length) {
      list.appendChild(el('li', 'syn-note', (d.entries || []).length ? 'Nothing matches “' + S.vocabQ.trim() + '”.'
        : 'Nothing here yet. Add a word, or tell Rouh what you mean by one.'));
    }
  }

  function vocabRow(e) {
    var li = el('li', 'syn-card syn-vocab-entry');
    li.setAttribute('data-id', e.id);
    var head = el('div', 'syn-vocab-head');
    head.appendChild(el('b', 'syn-vocab-term', '“' + e.term + '”'));
    if ((e.aliases || []).length) {
      head.appendChild(el('span', 'syn-vocab-also', 'also ' + e.aliases.map(function (a) { return '“' + a + '”'; }).join(', ')));
    }
    li.appendChild(head);
    li.appendChild(el('p', 'syn-vocab-meaning', e.meaning));
    var about = (e.context || []);
    var chips = siloChips(e.silo_chips);
    if (about.length || chips) {
      var row = el('div', 'syn-vocab-chips');
      about.forEach(function (c) {
        var tag = el('span', 'syn-chip', c.name + ' (' + c.type + ')');
        tag.dataset.noexplain = '1';
        row.appendChild(tag);
      });
      if (chips) row.appendChild(chips);
      li.appendChild(row);
    }
    var acts = el('div', 'syn-row syn-vocab-acts');
    if (S.vocabConfirm === e.id) {
      acts.appendChild(el('span', 'syn-vocab-ask', 'Delete “' + e.term + '”?'));
      acts.appendChild(btn('Delete', 'danger', function () {
        vocabSave('/delete', { id: e.id }, 'Deleted “' + e.term + '”.');
      }));
      acts.appendChild(btn('Keep it', 'quiet', function () { S.vocabConfirm = ''; draw(); }));
    } else {
      acts.appendChild(btn('Edit', 'quiet', function () {
        S.vocabEdit = e.id; S.vocabConfirm = ''; S.vocabRefused = ''; S.vocabDraft = vocabDraftOf(e); draw();
      }, 'Edit “' + e.term + '”'));
      acts.appendChild(btn('Delete', 'quiet', function () { S.vocabConfirm = e.id; draw(); }, 'Delete “' + e.term + '”'));
    }
    li.appendChild(acts);
    return li;
  }

  function vocabDraftOf(e) {
    return { term: e ? e.term : '', meaning: e ? e.meaning : '', aliases: e ? (e.aliases || []).join(', ') : '',
             context: e ? (e.context || []).slice() : [], silos: e ? (e.silos || []).slice() : [] };
  }

  function vocabField(label, control) {
    var lab = el('label', 'syn-vocab-field');
    lab.appendChild(el('span', 'syn-vocab-label', label));
    lab.appendChild(control);
    return lab;
  }

  // The form for a new entry (`e` null) or one being changed, its words kept in `S.vocabDraft` so a redraw, and
  // above all a refusal, never takes them away.
  function vocabForm(e) {
    var dr = S.vocabDraft || (S.vocabDraft = vocabDraftOf(e));
    var form = el(e ? 'li' : 'div', 'syn-card syn-form syn-vocab-form');
    var term = el('input', 'syn-in');
    term.type = 'text';
    term.value = dr.term; term.placeholder = 'Bo';
    term.addEventListener('input', function () { dr.term = term.value; });
    var meaning = el('textarea', 'syn-in');
    meaning.rows = 2; meaning.value = dr.meaning; meaning.placeholder = 'Robert Smith, my brother';
    meaning.addEventListener('input', function () { dr.meaning = meaning.value; });
    var aliases = el('input', 'syn-in');
    aliases.type = 'text';
    aliases.value = dr.aliases; aliases.placeholder = 'Bobby, Rob';
    aliases.addEventListener('input', function () { dr.aliases = aliases.value; });
    var head = el('h6', null, e ? 'Change “' + e.term + '”' : 'A new entry');
    head.dataset.noexplain = '1';
    add(form, head,
        vocabField('Word', term), vocabField('What it means', meaning), vocabField('Other names, with commas', aliases),
        vocabField('About', vocabAbout(dr)));
    var all = (S.vocab && S.vocab.silos) || [];
    if (all.length) {
      var group = el('div', 'silo-toggles');
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', 'Silos');
      all.forEach(function (c) {
        var b = el('button', 'silo-toggle');
        b.type = 'button';
        var on = function () { return dr.silos.indexOf(c.key) >= 0; };
        b.setAttribute('aria-pressed', on() ? 'true' : 'false');
        b.appendChild(siloChip(c));
        b.addEventListener('click', function () {
          dr.silos = on() ? dr.silos.filter(function (k) { return k !== c.key; }) : dr.silos.concat([c.key]);
          b.setAttribute('aria-pressed', on() ? 'true' : 'false');
        });
        group.appendChild(b);
      });
      form.appendChild(vocabField('Silos', group));
    }
    if (S.vocabRefused) form.appendChild(say(S.vocabRefused, 'bad'));
    var acts = el('div', 'syn-row');
    acts.appendChild(btn(e ? 'Save' : 'Add it', 'primary', function () {
      if (!dr.term.trim() || !dr.meaning.trim()) { (dr.term.trim() ? meaning : term).focus(); return; }
      var body = { term: dr.term, meaning: dr.meaning, aliases: dr.aliases, context: dr.context, silos: dr.silos };
      if (e) body.id = e.id;
      vocabSave(e ? '/edit' : '/add', body, (e ? 'Saved “' : 'Kept “') + dr.term.trim() + '”.');
    }));
    acts.appendChild(btn('Cancel', 'quiet', function () { S.vocabEdit = ''; S.vocabDraft = null; S.vocabRefused = ''; draw(); }));
    form.appendChild(acts);
    setTimeout(function () { if (!document.activeElement || document.activeElement === document.body) term.focus(); }, 0);
    return form;
  }

  // What an entry is about: the people, tasks and projects picked, each a chip that a press takes off, and a
  // box that finds more (`/api/rules/targets`, the same finder a rule for somebody uses).
  function vocabAbout(dr) {
    var wrap = el('div', 'syn-vocab-about');
    var chips = el('div', 'syn-vocab-chips');
    var found = el('div', 'syn-vocab-found');
    var drawChips = function () {
      chips.replaceChildren();
      dr.context.forEach(function (c, i) {
        var b = btn(c.name + ' (' + c.type + ') ×', 'quiet tiny', function () { dr.context.splice(i, 1); drawChips(); },
          'Take off ' + c.name);
        chips.appendChild(b);
      });
    };
    var box = el('input', 'syn-in');
    box.type = 'text';
    box.placeholder = 'Find a person, task or project';
    box.setAttribute('aria-label', 'Find what it is about');
    var timer = null;
    box.addEventListener('input', function () {
      clearTimeout(timer);
      var want = box.value.trim();
      if (!want) { found.replaceChildren(); return; }
      timer = setTimeout(function () {
        call('/api/rules/targets?q=' + encodeURIComponent(want)).then(function (j) {
          if (box.value.trim() !== want) return;
          found.replaceChildren();
          ((j && j.targets) || []).slice(0, 8).forEach(function (t) {
            found.appendChild(btn(t.name + ' (' + t.about + ')', 'quiet tiny', function () {
              if (!dr.context.some(function (c) { return c.type === t.type && c.id === t.id; })) {
                dr.context.push({ type: t.type, id: t.id, name: t.name });
              }
              box.value = ''; found.replaceChildren(); drawChips();
            }));
          });
          if (!found.children.length) found.appendChild(el('span', 'syn-dim', 'Nothing called that.'));
        }).catch(function () {});
      }, 250);
    });
    drawChips();
    return add(wrap, chips, box, found);
  }

  function vocabSave(path, body, done) {
    return vocabApi(path, body).then(function (j) {
      S.vocab = j; S.vocabEdit = ''; S.vocabDraft = null; S.vocabConfirm = ''; S.vocabRefused = '';
      draw();
      flash(done);
    }).catch(function (err) {
      S.vocabRefused = err.message;
      S.vocabConfirm = '';
      if (path === '/delete') flash(err.message, 'bad');
      draw();
    });
  }

  /* ------------------------------------------------------------ the Improvements page

     Every attempt to make Synapse better, newest first (`rouh/synapse/improvements.py`): the nightly
     run's (`rouh/synapse/nightly.py`, at 02:00 on Petar's clock) and the ones task 85 had already
     documented, backfilled from its notes. Each opens: the ideas considered, the one chosen and why,
     the hypothesis, what changed, every measure before and after, the spend and time, the conclusion,
     the outcome, any decision that is Petar's, and the paragraph the morning brief reads out. */

  var OUTCOME_CLS = { kept: 'good', kept_experience: 'good', discarded: 'quiet', failed: 'bad', needs_decision: 'warn', baseline: 'info',
                      running: 'busy' };

  function homeImprovements(m) {
    var card = el('section', 'syn-card syn-imp-home');
    add(card, el('h4', null, 'Improvements'));
    var sched = m.schedule;
    add(card, el('p', 'syn-note', 'Every attempt to make Synapse better, kept or not, with its numbers. ' +
      (sched ? (sched.state === 'paused' ? 'The nightly run is paused.' : 'The next nightly run is ' + sched.when + '.')
             : 'The nightly run is not scheduled on this server.')));
    if (m.latest) add(card, el('p', 'syn-imp-latest', 'Newest: ' + m.latest));
    card.appendChild(add(el('div', 'syn-row'), goBtn('Open Improvements' + (m.count ? ' (' + m.count + ')' : ''), 'primary',
      '/synapse/improvements', function () { openImprovements(''); })));
    return card;
  }

  function openImprovements(n) {
    resetDataset();
    S.page = 'improvements';
    S.attempt = n ? String(n) : '';
    S.impOne = null;
    host().dataset && host().dataset('improvements' + (S.attempt ? '/' + S.attempt : ''),
                                     S.attempt ? 'Attempt ' + S.attempt : 'Improvements');
    draw();
  }

  function loadImprovements(quiet) {
    var want = S.attempt;
    return api('/improvements' + (want ? '/' + want : '')).then(function (j) {
      if (S.page !== 'improvements' || S.attempt !== want) return;
      S.impError = '';
      var before = JSON.stringify(want ? S.impOne : S.imp);
      if (want) S.impOne = j.attempt; else S.imp = j;
      if (!quiet || before !== JSON.stringify(want ? S.impOne : S.imp)) draw();
    }).catch(function (e) {
      if (S.page !== 'improvements' || S.attempt !== want) return;
      S.impError = e.message;
      if (!quiet) draw();
    });
  }

  function outcomeChip(a) {
    return el('span', 'syn-imp-outcome ' + (OUTCOME_CLS[a.outcome] || ''), a.outcome_words || a.outcome);
  }

  function dateOf(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ', ' +
      d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }

  function minutes(s) {
    if (s == null) return '';
    s = Number(s);
    return s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1) + ' h';
  }

  function renderImprovements(body) {
    keepScroll(function () {
      if (S.impError) { body.replaceChildren(say('The attempts could not be read: ' + S.impError, 'bad')); return; }
      if (S.attempt) {
        if (!S.impOne) { body.replaceChildren(el('p', 'syn-loading', 'Opening attempt ' + S.attempt + '...')); loadImprovements(); return; }
        body.replaceChildren(drawAttempt(S.impOne));
        return;
      }
      if (!S.imp) { body.replaceChildren(el('p', 'syn-loading', 'Reading the attempts...')); loadImprovements(); return; }
      body.replaceChildren(drawAttempts(S.imp));
    });
  }

  function drawAttempts(d) {
    var wrap = el('div', 'syn-imp');
    var top = el('div', 'syn-top');
    add(top, goBtn('All datasets', 'quiet', '/synapse', goHome), el('h5', 'syn-imp-title', 'Improvements'));
    wrap.appendChild(top);
    var intro = el('section', 'syn-card');
    add(intro, el('p', null, 'Every attempt to make Synapse better, newest first. Each night one idea is tried and measured ' +
      'on 103 questions over a frozen copy of Synapse Master, 53 about Rouh\'s mail and 50 about the rest of the memory. ' +
      'It is kept when it helps beyond noise, or kept for the experience when it makes Rouh better to use with proof from ' +
      'real chat turns; either way with no regression on either set, no leaks, no more than 10% slower and no more than 20% dearer. ' +
      'When Synapse\'s code changed since the last judged night, the night recalibrates first and then still tries its idea.'));
    var sched = d.schedule;
    var line = el('div', 'syn-row');
    add(line, el('span', 'syn-note', sched ? (sched.state === 'paused' ? 'The nightly run is paused. '
      : 'Next run: ' + sched.when + ' (' + sched.repeats.toLowerCase() + '). ') +
      (sched.last_said ? 'Last time, ' + String(sched.last_day).toLowerCase() + ' at ' + sched.last_time + ': ' + sched.last_said + '.' : '')
      : 'The nightly run is not scheduled on this server.'));
    if (sched && host().go) line.appendChild(goBtn('Pause or move it in Clockwork', 'quiet', '/clockwork', function () { host().go('/clockwork'); }));
    intro.appendChild(line);
    wrap.appendChild(intro);

    var list = el('ol', 'syn-imp-list');
    (d.attempts || []).forEach(function (a) {
      var li = el('li');
      var row = el('a', 'syn-imp-row');
      row.href = '/synapse/improvements/' + a.number;
      row.setAttribute('data-inapp', '');
      row.setAttribute('aria-label', 'Attempt ' + a.number + ': ' + (a.chosen || 'no idea yet') + ', ' + a.outcome_words);
      var head = el('span', 'syn-imp-head');
      add(head, el('span', 'syn-imp-n', '#' + a.number), outcomeChip(a), el('span', 'syn-imp-when', dateOf(a.started_at)));
      if (a.source === 'backfilled') head.appendChild(el('span', 'syn-imp-tag', 'backfilled from notes'));
      if (a.mode === 'baseline' && a.source !== 'backfilled') head.appendChild(el('span', 'syn-imp-tag', 'baseline only'));
      if (a.recalibration) head.appendChild(el('span', 'syn-imp-tag', a.recalibration.trusted ? 'recalibrated first' : 'recalibration failed'));
      var what = el('span', 'syn-imp-what', a.chosen || (a.outcome === 'running' ? 'Choosing an idea...' : 'No idea chosen'));
      var moved = (a.headline || []).filter(function (m) { return m.before != null && m.after != null; }).slice(0, 4);
      var sub = el('span', 'syn-imp-sub');
      var only = (a.headline || []).filter(function (m) { return m.before == null && m.after != null; }).slice(0, 4);
      if (!moved.length && only.length) {
        only.forEach(function (m) { sub.appendChild(el('span', 'syn-imp-m', shortLabel(m.label) + ' ' + m.after_text)); });
      } else if (moved.length) {
        moved.forEach(function (m) {
          sub.appendChild(el('span', 'syn-imp-m ' + (m.moved || ''), shortLabel(m.label) + ' ' + m.before_text + ' → ' + m.after_text));
        });
      } else {
        sub.textContent = (a.conclusion || a.paragraph || '').slice(0, 220);
      }
      add(row, head, what, sub);
      row.addEventListener('click', function () { openImprovements(a.number); });
      li.appendChild(row);
      list.appendChild(li);
    });
    if (!(d.attempts || []).length) list.appendChild(el('li', 'syn-note', 'No attempt has been recorded yet.'));
    wrap.appendChild(list);
    return wrap;
  }

  function shortLabel(label) {
    return String(label || '').replace(/^Recall: .*$/, 'Recall').replace(/^Answer correctness.*$/, 'Answers')
      .replace(/^Citations that support.*$/, 'Citations').replace(/^Time to pack, slowest 5%$/, 'p95')
      .replace(/^Cost per question$/, 'Cost').replace(/^Tokens the pack adds.*$/, 'Tokens').replace(/^Permission leaks$/, 'Leaks');
  }

  function drawAttempt(a) {
    var wrap = el('div', 'syn-imp');
    var top = el('div', 'syn-top');
    add(top, btn('All attempts', 'quiet', function () { openImprovements(''); }),
      el('h5', 'syn-imp-title', 'Attempt ' + a.number), outcomeChip(a));
    wrap.appendChild(top);

    var head = el('section', 'syn-card');
    add(head, el('h4', null, a.chosen || (a.outcome === 'running' ? 'Still choosing an idea' : 'No idea chosen')));
    var facts = [['Started', dateOf(a.started_at) || '-'], ['Finished', dateOf(a.finished_at) || (a.outcome === 'running' ? 'still running' : '-')],
      ['Took', minutes(a.duration_s) || '-'], ['Model spend', a.spend_usd == null ? '-' : money(a.spend_usd)],
      ['Mode', a.mode === 'baseline' ? 'baseline only: measured, nothing changed' : 'a full night'],
      ['Where it came from', a.source === 'backfilled' ? 'backfilled from task 85\'s notes' : a.source === 'hand' ? 'recorded by hand' : 'the nightly run']];
    var dl = el('dl', 'syn-imp-facts');
    facts.forEach(function (f) { add(dl, el('dt', null, f[0]), el('dd', null, f[1])); });
    head.appendChild(dl);
    if (a.notes_ref) head.appendChild(el('p', 'syn-note', 'From ' + a.notes_ref));
    if (a.run_id && host().go) head.appendChild(add(el('div', 'syn-row'), goBtn('Open its run', 'quiet', '/run/' + encodeURIComponent(a.run_id), function () { host().go('/run/' + a.run_id); })));
    wrap.appendChild(head);

    var report = el('section', 'syn-card syn-imp-report');
    add(report, el('h4', null, 'The morning report'), el('p', null, a.paragraph || ''));
    wrap.appendChild(report);

    // A night whose Synapse code had changed since the last judged night recalibrates before its idea
    // (`rouh/synapse/recalibrate.py`): what changed, what the two codes found, and what it cost.
    var rc = a.recalibration;
    if (rc) {
      var recal = el('section', 'syn-card' + (rc.trusted ? '' : ' warn'));
      recal.appendChild(el('h4', null, rc.trusted ? 'Recalibrated first' : 'The recalibration did not hold up'));
      var how = { carried: 'the last judged figures carried over, nothing judged', judged: 'main measured and judged afresh',
        failed: 'stopped: no idea judged against it', none: '-' };
      var rrows = [[rowLabel('Judged last'), rc.from_attempt ? 'attempt ' + rc.from_attempt + ', code ' + (rc.from_code || '-') +
        (rc.from_commit ? ' (commit ' + String(rc.from_commit).slice(0, 8) + ')' : '') : 'nothing judged before'],
        [rowLabel('Code tonight'), rc.code || '-'], [rowLabel('How'), how[rc.how] || rc.how || '-']];
      if (rc.same_memory) rrows.push([rowLabel('Memory found'), rc.same_memory]);
      if (rc.problem) rrows.push([rowLabel('What was wrong'), rc.problem]);
      if (rc.spend_usd != null) rrows.push([rowLabel('Spent on it'), money(rc.spend_usd)]);
      recal.appendChild(table(null, rrows, 'small'));
      if ((rc.commits || []).length) {
        recal.appendChild(el('h6', null, 'What changed in Synapse since'));
        var cl = el('ul', 'syn-list');
        rc.commits.forEach(function (c) { cl.appendChild(el('li', null, c)); });
        recal.appendChild(cl);
      }
      wrap.appendChild(recal);
    }

    var d = a.decision || {};
    if (d.question) {
      var dec = el('section', 'syn-card warn');
      add(dec, el('h4', null, d.answer ? 'The decision, and your answer' : 'Waiting on your decision'),
        el('p', null, d.question));
      var ul = el('ul', 'syn-list');
      (d.options || []).forEach(function (o) {
        var li = el('li');
        add(li, el('strong', null, o.label), o.detail ? document.createTextNode(': ' + o.detail) : null);
        ul.appendChild(li);
      });
      dec.appendChild(ul);
      if (d.answer) dec.appendChild(el('p', 'syn-imp-answer', 'Answered: ' + d.answer));
      wrap.appendChild(dec);
    }

    var think = el('section', 'syn-card');
    add(think, el('h4', null, 'The thinking'));
    if ((a.ideas || []).length) {
      think.appendChild(el('h6', null, 'Ideas considered'));
      var ideas = el('ul', 'syn-list');
      a.ideas.forEach(function (i) {
        var text = typeof i === 'string' ? i : (i.idea || '');
        var note = typeof i === 'string' ? '' : (i.note || '');
        var li = el('li', /chosen/i.test(note) ? 'syn-imp-chosen' : '');
        add(li, document.createTextNode(text), note ? el('span', 'syn-note', ' (' + note + ')') : null);
        ideas.appendChild(li);
      });
      think.appendChild(ideas);
    }
    [['Why this one', a.why_chosen], ['What earlier attempts suggested', a.earlier], ['Hypothesis', a.hypothesis]]
      .forEach(function (p) { if (p[1]) add(think, el('h6', null, p[0]), el('p', null, p[1])); });
    if (think.childNodes.length > 1) wrap.appendChild(think);

    var ch = a.changes || {};
    if (ch.summary || (ch.commits || []).length || (ch.files || []).length) {
      var changed = el('section', 'syn-card');
      add(changed, el('h4', null, 'What was changed'), ch.summary ? el('p', null, ch.summary) : null);
      var rows = [];
      if ((ch.commits || []).length) rows.push([rowLabel('Commits'), ch.commits.join(', ')]);
      if ((ch.files || []).length) rows.push([rowLabel('Files'), ch.files.join(', ')]);
      if (ch.branch) rows.push([rowLabel('Branch'), ch.branch]);
      if (rows.length) changed.appendChild(table(null, rows, 'small'));
      wrap.appendChild(changed);
    }

    var nums = el('section', 'syn-card');
    add(nums, el('h4', null, 'The measures'), el('p', 'syn-note', (a.benchmark ? a.benchmark + (a.benchmark_version ? ', ' + a.benchmark_version : '') : 'No benchmark named') + '.'));
    if ((a.measures || []).length) {
      // The earlier inbox-only run, beside the first baseline: for reference, never the figure to beat.
      var ref = a.reference;
      var head = ['Measure', 'Before', 'After', ''];
      if (ref) head.push('Reference');
      nums.appendChild(table(head, a.measures.map(function (m) {
        var r = [m.label, m.before_text, el('span', 'syn-imp-m ' + (m.moved || ''), m.after_text),
          el('span', 'syn-imp-m ' + (m.moved || ''), m.moved === 'better' ? 'better' : m.moved === 'worse' ? 'worse' : '')];
        if (ref) r.push(el('span', 'syn-imp-ref', m.reference_text || ''));
        return r;
      }), 'syn-imp-measures'));
      if (ref) nums.appendChild(el('p', 'syn-note', 'Reference: ' + ref.label + ' (run ' + String(ref.run || '').slice(0, 8) +
        '), the same 53 mail questions when they searched Rouh\'s inbox alone. Shown for reference, not as the figure to beat: ' +
        'they now search all of Synapse Master, which is harder.'));
    } else {
      nums.appendChild(el('p', 'syn-note', a.outcome === 'running' ? 'Not measured yet.' : 'No numbers were recorded.'));
    }
    wrap.appendChild(nums);

    var x = a.experience || {};
    if (x.expected) {
      var exp = el('section', 'syn-card syn-imp-report');
      add(exp, el('h4', null, 'The experience it was kept for'), el('p', null, 'Expected, written before it was built: ' + x.expected));
      (x.evidence || []).forEach(function (e) {
        var box = el('div', 'syn-imp-ev');
        add(box, el('p', 'syn-imp-ev-msg', '\u201c' + (e.message || '') + '\u201d'),
          add(el('p'), el('strong', null, 'Before: '), document.createTextNode(e.before || '')),
          add(el('p'), el('strong', null, 'After: '), document.createTextNode(e.after || '')));
        exp.appendChild(box);
      });
      if (x.page && host().go) exp.appendChild(add(el('div', 'syn-row'), goBtn('Open the evidence, with screenshots', 'quiet',
        '/workspace/' + x.page, function () { host().go('/workspace/' + x.page); })));
      wrap.appendChild(exp);
    }

    if (a.conclusion) {
      var concl = el('section', 'syn-card');
      add(concl, el('h4', null, 'Conclusion'), el('p', null, a.conclusion));
      wrap.appendChild(concl);
    }
    return wrap;
  }

  /* ---------------------------------------------------------------- the homepage */

  function loadHome(quiet) {
    S.busy = true;
    return api('/home').then(function (j) {
      S.busy = false;
      // Read again every couple of seconds while a dataset is filling: drawn
      // again only when something on it changed.
      var same = quiet && S.home && JSON.stringify(S.home) === JSON.stringify(j);
      S.home = j;
      if (!S.ds && !same) draw();
    }).catch(function (e) {
      S.busy = false;
      if (!quiet) $('synBody').replaceChildren(say('Synapse could not be read: ' + e.message, 'bad'));
    });
  }

  function renderHome(body) {
    var h = S.home;
    var wrap = el('div', 'syn-home');
    var sets = el('section', 'syn-card');
    add(sets, el('h4', null, 'Datasets'));
    var grid = el('div', 'syn-ds-grid');
    (h.datasets || []).forEach(function (d) {
      var card = el('article', 'syn-ds');
      var title = el('a', 'syn-ds-name', d.name);
      title.href = dsHref(d.id);
      title.setAttribute('data-inapp', '');
      title.addEventListener('click', function () { openDataset(d.id, d.name); });
      var counts = el('p', 'syn-ds-counts', d.role === 'people' ? plural(d.people, 'person', 'people') + ' · the people every real dataset ' +
        'resolves against' : plural(d.items, 'item') + (Number(d.people) > 0 ? ' · ' + plural(d.people, 'person', 'people') : '')
        + ' · ' + plural(d.links, 'link') + ' · ' + plural(d.layers, 'layer') + ' · ' + money(d.cost));
      var filling = Number(d.waiting) > 0 ? el('p', 'syn-ds-filling', 'Working: ' + plural(d.waiting, 'job') + ' on the queue') : null;
      var actions = el('div', 'syn-row');
      actions.appendChild(goBtn('Open', 'primary', dsHref(d.id), function () { openDataset(d.id, d.name); }));
      if (d.master) {
        // Rouh's own memory (rouh/synapse/master.py): the server refuses to delete it, so nothing offers to.
        actions.appendChild(el('span', 'syn-note', 'Rouh\'s memory: the tools in every chat read and write it'));
      } else if (S.homeConfirm === d.id) {
        actions.appendChild(btn('Delete it and everything in it', 'danger', function () {
          api('/ds/' + d.id + '/delete', { body: {} }).then(function (j) {
            S.homeConfirm = '';
            flash('Deleted ' + d.name + ': ' + (j.deleted.items || 0) + ' items, ' + (j.deleted.links || 0) + ' links, ' +
              (j.deleted.logged_requests_redacted || 0) + ' logged requests redacted.');
            loadHome();
          }).catch(function (e) { flash(e.message, 'bad'); });
        }));
        actions.appendChild(btn('Keep it', '', function () { S.homeConfirm = ''; renderHome($('synBody')); }));
      } else {
        actions.appendChild(btn('Delete', 'quiet', function () { S.homeConfirm = d.id; renderHome($('synBody')); }));
      }
      add(card, title, d.about ? el('p', 'syn-ds-about', d.about) : null, counts, filling, actions);
      grid.appendChild(card);
    });
    if (!(h.datasets || []).length) grid.appendChild(el('p', 'syn-note', 'No datasets yet. Make one below, or add an example.'));
    sets.appendChild(grid);

    var form = el('div', 'syn-newds');
    var nameIn = el('input', 'syn-in'); nameIn.placeholder = 'Name of the new dataset'; nameIn.setAttribute('aria-label', 'Name of the new dataset');
    var aboutIn = el('input', 'syn-in'); aboutIn.placeholder = 'What it is for (optional)'; aboutIn.setAttribute('aria-label', 'What it is for');
    var make = btn('Create dataset', 'primary', function () {
      if (!nameIn.value.trim()) { nameIn.focus(); return; }
      make.disabled = true;
      api('/datasets', { body: { name: nameIn.value, about: aboutIn.value } }).then(function (j) {
        openDataset(j.dataset, nameIn.value);
      }).catch(function (e) { make.disabled = false; flash(e.message, 'bad'); });
    });
    add(form, nameIn, aboutIn, make);
    sets.appendChild(form);
    var ex = el('div', 'syn-examples');
    add(ex, el('span', 'syn-note', 'Add an example set (fictional):'));
    (h.examples || []).forEach(function (x) {
      ex.appendChild(btn(x.name, '', function () {
        api('/examples', { body: { key: x.key } }).then(function (j) {
          flash(x.name + ' is being filled; open it to watch every item go in.');
          loadHome();
        }).catch(function (e) { flash(e.message, 'bad'); });
      }, x.about));
    });
    sets.appendChild(ex);

    var peopleCard = homePeople(h.people || {});
    var mailCard = homeMail(h.mail || {});
    var calendarCard = homeCalendar(h.calendar || {});
    var meetingsCard = homeMeetings(h.meetings || {});
    var improveCard = homeImprovements(h.improvements || {});
    var kindsCard = kindsView(h.kinds || []);

    var models = el('section', 'syn-card');
    add(models, el('h4', null, 'Models and backends'));
    // Since 18 October 2026 every model Synapse asks is set on the Models page, under Synapse,
    // like every other model Rouh asks; only the embeddings stay with each dataset.
    var where = el('p', 'syn-note');
    where.appendChild(document.createTextNode('Which model does each job is set on the '));
    var link = el('a', null, 'Models page');
    link.setAttribute('href', (window.RouhNav && window.RouhNav.route('models')) || '/anatomy/behaviour/models');
    where.appendChild(link);
    where.appendChild(document.createTextNode(', under Synapse. Embeddings stay with each dataset, under Tune > Vectors.'));
    models.appendChild(where);
    var b = h.backends || {};
    var dec = b.decisions || {};
    var decState = dec.status === 'open' ? 'open to this key' : dec.status === 'refused' ? 'not open to this key' :
      dec.status === 'no_key' ? 'no OpenAI key on this machine' : 'not asked yet';
    var tbl = table(['Part', 'What answers it'], [
      [rowLabel('Store'), b.store],
      [rowLabel('Embeddings, for search by meaning'), b.embeddings + ', 1,024 dimensions, half precision, for new datasets. ' +
        'Each dataset searches the one model its vectors are; Tune > Vectors moves a dataset to another.'],
      [rowLabel('Helper model: X-rays, judgement links, layers, the map\'s words'), b.helper],
      [rowLabel('Tier call: every item\'s tier, with a one-line reason (D80)'), b.helper + ' reads the signals code gathered with the ' +
        'item\'s text and decides tier 0, 1 or 2 for every item, every time. Code decides no tier. If the helper model cannot answer, ' +
        'the item is tier 1 and says why.'],
      [rowLabel('One call for an item with an X-ray (D82)'), 'Every item but a person or a topic gets an X-ray, and the X-ray call itself ' +
        'writes its title and decides its tier, sensitivity and area, with code\'s signals in front of it, so no separate tier call or ' +
        'sensitivity suggestion is made. A person or a topic gets no X-ray; a topic typed in gets the tier call alone.'],
      [rowLabel('Answer model: the query, the checkpoint and the answer'), b.answer],
      [rowLabel('Decision models (Choice, Score, Noul)'), 'Off: no decision call is made, and whatever needs deciding is decided by ' +
        b.helper + '. Tune > Decision models turns them on for a dataset, to compare; then the OpenAI Decisions API (' + decState +
        ') or ' + b.decision_generative + ' with log probabilities answers, and every decision says which backend answered.'],
      [rowLabel('Judge for evaluations'), b.judge + '; a judge of the family that ranked or answered is said beside the result (D77)'],
      [rowLabel('OpenAI key'), b.openai_key ? 'present (read by the server, never shown)' : 'missing: nothing can be X-rayed'],
      [rowLabel('Voyage AI key'), b.voyage_key ? 'present (read by the server, never shown)' : 'missing: voyage-4 vectors cannot be made, so search is by words']
    ]);
    models.appendChild(tbl);
    var decRow = el('div', 'syn-row');
    add(decRow, el('span', 'syn-note', 'Decisions API: ' + (dec.said || '') + (dec.checked_at ? ' (checked ' + when(dec.checked_at) + ')' : '')),
      btn('Check again', 'quiet', function (ev) {
        ev.target.disabled = true;
        api('/decisions/probe', { body: {} }).then(function () { loadHome(); }).catch(function (e) { flash(e.message, 'bad'); });
      }));
    models.appendChild(decRow);

    var nums = el('section', 'syn-card');
    add(nums, el('h4', null, 'The numbers it works by'),
      el('p', 'syn-note', 'Every number is a value, never a constant (D5). These are the starting values; each dataset can change ' +
        'its own on its Tune tab. "Starting value" marks the spec\'s own; "lab choice" marks a choice made for this lab.'));
    nums.appendChild(settingsTable(h.settings || [], null));

    var notBuilt = el('section', 'syn-card');
    add(notBuilt, el('h4', null, 'Not built yet, or built differently'));
    var ul = el('ul', 'syn-list');
    (h.not_built || []).forEach(function (n) {
      var li = el('li');
      add(li, el('strong', null, n.what + '. '), n.why);
      ul.appendChild(li);
    });
    notBuilt.appendChild(ul);

    add(wrap, sets, improveCard, peopleCard, mailCard, calendarCard, meetingsCard, kindsCard, models, notBuilt, nums);
    keepScroll(function () { body.replaceChildren(wrap); });
  }

  // The owner's contacts: Synapse Master's people, kept two ways with iCloud (4 October 2026,
  // rouh/synapse/contacts.py). There is no import any more: the iCloud sync writes every card onto its
  // person, and an edit of a contact here is written back to iCloud and the phone.
  function homePeople(p) {
    var card = el('section', 'syn-card');
    add(card, el('h4', null, 'Contacts'), el('p', 'syn-note', 'Your contacts are the people of Synapse Master, matched ' +
      'by their addresses and phone numbers, never by name alone. The iCloud sync brings every card in; editing or ' +
      'deleting a person who has a card writes the change to iCloud, and so to your phone. People Synapse met in an ' +
      'item and nothing else never reach the phone.'));
    if (!p.id) { card.appendChild(say('There is no Synapse Master yet.', 'note')); return card; }
    var o = p.origins || {};
    var ids = p.identities || {};
    var rows = [[rowLabel('With a card in iCloud'), String(p.cards || 0)],
      [rowLabel('Met by Synapse, no card'), String(o.synapse || 0)],
      [rowLabel('Identifiers'), ['email', 'phone', 'name', 'handle'].map(function (k) { return plural(ids[k] || 0, k); }).join(', ')],
      [rowLabel('Flagged as likely the same'), String(p.likely_same || 0)],
      [rowLabel('On the way to iCloud'), String(p.to_icloud || 0) + (p.to_icloud_failed ? ', ' + p.to_icloud_failed + ' failed' : '') +
        (p.last_to_icloud ? ', last written ' + when(p.last_to_icloud) : '')]];
    card.appendChild(table(['', 'Now'], rows));
    var row = el('div', 'syn-row');
    row.appendChild(btn('Open the contacts', 'primary', function () { S.itemFilter = { q: '', kind: 'person', origin: '' }; openDataset(p.id, p.name, 'items'); }));
    card.appendChild(row);
    return card;
  }

  // Gmail kept in Synapse Master (card 1163, 5 October 2026, rouh/synapse/gmailsync.py): each inbox's
  // history read every minute and on Gmail's push, its backfill, its queue, failures and the nightly check.
  // Every calendar Rouh's Google account can read, kept in Synapse Master (rouh/synapse/calsync.py).
  function homeCalendar(c) {
    var card = el('section', 'syn-card syn-mail');
    add(card, el('h4', null, 'Calendar'), el('p', 'syn-note', 'Every event on every calendar Rouh’s Google account can ' +
      'read is kept in Synapse Master, past and future: its own calendars and each one shared with it, found again every ' +
      'hour. Changes are read every ' + Math.round(c.poll_seconds || 60) + ' seconds; an event deleted in the calendar is ' +
      'deleted here, and every night each calendar’s whole list is checked against Synapse’s. Nothing here writes to a ' +
      'calendar. You are the only reader.'));
    if (!c.id) { card.appendChild(say('There is no Synapse Master yet.', 'note')); return card; }
    if (!(c.calendars || []).length) {
      card.appendChild(say('No calendar is kept yet: Google is not connected, or the first read has not run.', 'note'));
      return card;
    }
    c.calendars.forEach(function (x, i) {
      var state = !x.enabled ? (x.state === 'busy only' ? 'not read: shared as free and busy only' : 'stopped' +
          (x.error ? ': ' + x.error : '')) :
        x.state === 'synced' ? (x.stale ? 'stale: no good read for ' + (c.stale_minutes || 15) + ' minutes' : 'in step') +
          (x.last_ok_at ? ', last read ' + when(x.last_ok_at) : '') :
        x.state === 'listing' ? 'first listing: ' + count(x.listed) + ' so far' : 'waiting for its first read';
      var badge = !x.enabled ? el('span', 'syn-badge', 'not read') : x.stale ? el('span', 'syn-badge badc', 'stale') :
        x.state === 'synced' ? el('span', 'syn-badge good', 'in step') : el('span', 'syn-badge', 'listing');
      var head = el('div', 'syn-row syn-mail-inbox' + (i ? ' later' : ''));
      add(head, el('strong', null, x.calendar), badge);
      card.appendChild(head);
      if (x.enabled && x.error) card.appendChild(say(x.error, 'bad'));
      var r = x.reconcile || {};
      var checked = r.at ? when(r.at) + ': calendar ' + count(r.calendar) + ', Synapse ' + count(r.synapse) +
        (r.missing || r.extra ? ', ' + count(r.missing) + ' stored, ' + count(r.extra) + ' deleted' : ', the same') : 'not yet';
      var rows = [[rowLabel('Now'), state]];
      if (x.enabled) {
        rows.push([rowLabel('Kept here'), plural(x.kept, 'event') + ', ' + count(x.read_by_model) + ' read by the model' +
          (x.deleted_in_synapse ? ', ' + count(x.deleted_in_synapse) + ' deleted in Synapse on purpose' : '')]);
        rows.push([rowLabel('Checked against the calendar'), checked]);
      }
      card.appendChild(table(['', 'Now'], rows));
    });
    return card;
  }

  // The meeting library, kept in Synapse Master (9 October 2026, rouh/synapse/meetings.py):
  // where the sync stands, what it holds, what waits, and what happened lately. Every update is in Activity.
  function homeMeetings(m) {
    var card = el('section', 'syn-card syn-mail');
    add(card, el('h4', null, 'Meetings'), el('p', 'syn-note', 'Every meeting in the meeting library is kept in Synapse ' +
      'Master: its summary, decisions and action items as the library wrote them, X-rayed once, and its transcript as ' +
      'passages found by meaning and by word. The library is the original; nothing here edits a meeting. A webhook says ' +
      'when one changes; a meeting already kept is read again after ' + Math.round((m.quiet_seconds || 600) / 60) +
      ' minutes with no further change, a new one at once. The library\'s changes are read every ' +
      Math.round((m.poll_seconds || 600) / 60) + ' minutes too, and every revision is checked each night at ' +
      (m.check_at || '03:30') + '. You read every meeting; anyone else only those listing their address as a reader.'));
    if (!m.id) { card.appendChild(say('There is no Synapse Master yet.', 'note')); return card; }
    var badge = !m.on ? el('span', 'syn-badge', 'waiting for its settings') :
      m.error ? el('span', 'syn-badge badc', 'trouble') :
      m.behind ? el('span', 'syn-badge', m.behind + ' behind') : el('span', 'syn-badge good', 'in step');
    var head = el('div', 'syn-row syn-mail-inbox');
    add(head, el('strong', null, m.library || 'The meeting library'), badge);
    card.appendChild(head);
    if (!m.on) card.appendChild(say(m.why_off, 'note'));
    else if (m.error) card.appendChild(say(m.error, 'bad'));
    var c = m.counts || {};
    var chk = m.check || {};
    var bf = m.backfill || {};
    var cost = m.cost || {};
    var rows = [
      [rowLabel('Kept here'), plural(m.meetings || 0, 'meeting') + ', ' + count(m.read_by_model) + ' X-rayed; ' +
        plural(m.passages || 0, 'transcript passage') + ', ' + count(m.passages_embedded) + ' embedded'],
      [rowLabel('In step'), count(m.in_sync) + ' of ' + count(m.meetings) + (m.behind ? '; ' + plural(m.behind, 'meeting') +
        ' changed in the library and waiting to be read' : '') + (m.new_waiting ? '; ' + plural(m.new_waiting, 'new meeting') +
        ' waiting' : '') + (m.next_due ? ', next at ' + when(m.next_due) : '')],
      [rowLabel('Last webhook'), (m.last_event_at ? when(m.last_event_at) : 'none yet') + ' · webhook ' + m.webhook +
        (c.webhooks_refused ? ' · ' + plural(c.webhooks_refused, 'refused message') : '')],
      [rowLabel('Last poll'), (m.last_poll_ok_at ? when(m.last_poll_ok_at) : 'never') + ', up to change ' + count(m.since_seq)],
      [rowLabel('First import'), m.backfill_state === 'done' ? 'done ' + when(m.backfill_done_at) + ': ' +
        count(bf.changes) + ' changes, ' + count(bf.listed) + ' meetings listed' : m.backfill_state],
      [rowLabel('Checked each night'), chk.at ? when(chk.at) + ': ' + count(chk.in_sync) + ' in step, ' + count(chk.behind) +
        ' behind, ' + count(chk.withdrawn_still_here) + ' withdrawn still here' + (chk.held_back ? '. ' + chk.held_back : '') : 'not yet'],
      [rowLabel('Cost'), cost.stores ? money(cost.per_meeting) + ' a meeting to bring in (' + plural(cost.stores, 'meeting') +
        ', ' + money(cost.stores_usd) + '); updates ' + money(cost.edits_usd) + ' for ' + plural(cost.edits || 0, 'update') : 'nothing yet'],
      [rowLabel('Revisions ignored as old'), count(c.old_ignored)]];
    card.appendChild(table(['', 'Now'], rows));
    (m.failing || []).forEach(function (f) { card.appendChild(say('Meeting ' + f.meeting + ': ' + f.error, 'bad')); });
    if ((m.recent || []).length) {
      add(card, el('h5', null, 'Lately'));
      var ul = el('ul', 'syn-list');
      m.recent.slice(0, 10).forEach(function (r) { ul.appendChild(el('li', null, when(r.at) + ' · ' + r.said)); });
      card.appendChild(ul);
    }
    var row = el('div', 'syn-row');
    row.appendChild(btn('Open the meetings', 'primary', function () { S.itemFilter = { q: '', kind: 'meeting', origin: '' }; openDataset(m.id, '', 'items'); }));
    row.appendChild(btn('Open its Activity', 'quiet', function () { openDataset(m.id, '', 'activity'); }));
    card.appendChild(row);
    return card;
  }

  function homeMail(m) {
    var card = el('section', 'syn-card syn-mail');
    add(card, el('h4', null, 'Gmail'), el('p', 'syn-note', 'Every email of each inbox below is kept in Synapse Master, ' +
      'spam and the Bin included, drafts once sent. Gmail\'s history is read every ' + Math.round((m.poll_seconds || 60)) +
      ' seconds and the moment Gmail\'s push arrives; a message deleted in Gmail is deleted here with everything made ' +
      'from it, and its labels and folder are kept on it. Every night the whole of Gmail\'s list is checked against ' +
      'Synapse\'s, and you hear on Telegram only if they still differ after the fix. You are the only reader. ' +
      'Another inbox is added with manage.py synapse_mail add <address>.'));
    if (!m.id) { card.appendChild(say('There is no Synapse Master yet.', 'note')); return card; }
    if (!(m.inboxes || []).length) { card.appendChild(say('No inbox is kept yet.', 'note')); return card; }
    m.inboxes.forEach(function (x, i) {
      var head = el('div', 'syn-row syn-mail-inbox' + (i ? ' later' : ''));
      add(head, el('strong', null, x.inbox),
        x.enabled ? (x.stale ? el('span', 'syn-badge badc', 'stale') : el('span', 'syn-badge good', 'in step')) :
          el('span', 'syn-badge', 'stopped'));
      card.appendChild(head);
      if (x.flag) card.appendChild(say(x.flag + (x.history_error ? ': ' + x.history_error : '.'), 'bad'));
      var c = x.last_history_counts || {};
      var counts = c.relisted !== undefined ? 'the whole mailbox listed (' + count(c.relisted) + '), ' + count(c.added) + ' missing queued'
        : count(c.added || 0) + ' new, ' + count(c.deleted || 0) + ' deleted, ' + count(c.labels || 0) + ' with changed labels';
      var b = x.backfill || {};
      var it = x.items || {};
      var folders = Object.keys(x.folders || {}).map(function (k) { return count(x.folders[k]) + ' ' + k; }).join(', ');
      var jobs = x.jobs || {};
      var waiting = Object.keys(jobs).map(function (k) { return count(jobs[k]) + ' ' + k.replace('mail_', '').replace(':', ', '); }).join('; ');
      var r = x.reconcile || {};
      var checked = !r.at ? 'not yet: the first runs the night after the backfill is listed' :
        r.error ? 'failed: ' + r.error :
        when(r.at) + ' (' + (r.by || '') + '): Gmail ' + count(r.gmail_after !== undefined ? r.gmail_after : r.gmail) + ', Synapse ' +
          count(r.synapse_after !== undefined ? r.synapse_after : r.synapse) +
          (r.clean ? (r.on_the_way ? ', in step once the ' + plural(r.on_the_way, 'change') + ' still on the queue ' +
              (Number(r.on_the_way) === 1 ? 'is' : 'are') + ' done' : ', the same') :
            ', still ' + count(r.missing_after) + ' missing and ' + count(r.extra_after) + ' extra' +
            (r.on_the_way ? ', besides ' + plural(r.on_the_way, 'change') + ' still on the queue' : '')) +
          (r.missing || r.extra ? '; before the fix ' + count(r.missing) + ' missing, ' + count(r.extra) + ' extra' : '') +
          (r.deleted_in_synapse ? '; ' + count(r.deleted_in_synapse) + ' deleted in Synapse on purpose' : '') +
          ((r.told_owner || r.told_petar) ? '; Telegram: ' + (r.told_owner || r.told_petar) : '');
      var w = x.watch || {};
      var rows = [
        [rowLabel('Last history read'), x.last_history_ok_at ? when(x.last_history_ok_at) + ': ' + counts : 'not yet'],
        [rowLabel('Last push from Gmail'), x.last_push_at ? when(x.last_push_at) : 'none yet'],
        [rowLabel('Read to history id'), x.history_id || 'not yet'],
        [rowLabel('Backfill'), b.state === 'listed' ? (b.done ? 'done: ' : 'listed, being stored: ') + count(b.listed) +
          ' listed' + (b.listed_at ? ' by ' + when(b.listed_at) : '') : b.state === 'listing' ? 'listing: ' + count(b.listed) +
          ' so far' : 'not started'],
        [rowLabel('Kept here'), plural(it.mail || 0, 'email') + (folders ? ' (' + folders + ')' : '') + ', ' +
          plural(it.files || 0, 'file') + (it.deleted ? ', ' + count(it.deleted) + ' deleted' : '') +
          (it.mail ? '; ' + count(it.read_by_model || 0) + ' read by the model' : '')],
        [rowLabel('Waiting'), (waiting || 'nothing') + (x.model_parts_waiting ? '; ' + count(x.model_parts_waiting) +
          ' model parts' : '')],
        [rowLabel('Failures'), (x.retrying ? count(x.retrying) + ' being tried again; ' : '') + count(x.failed_7d || 0) +
          ' failed in 7 days' + (x.last_failure ? ': ' + x.last_failure : '') +
          (x.history_failures ? '; history not read ' + plural(x.history_failures, 'time') + ' running' : '')],
        [rowLabel('Gmail\'s push'), w.by === 'mail alerts' ? 'the watch mail alerts keeps, until ' + when(w.expires_at) :
          w.by === 'sync' ? 'a watch of its own, until ' + when(w.expires_at) : (w.error || 'none: read every minute')],
        [rowLabel('Checked against Gmail'), checked],
        [rowLabel('Cost so far'), '$' + Number(x.cost_usd || 0).toFixed(4)]];
      card.appendChild(table(['', 'Now'], rows));
      var row = el('div', 'syn-row');
      row.appendChild(btn('Read Gmail now', '', function (ev) {
        ev.target.disabled = true;
        api('/mail/read', { body: { inbox: x.inbox } }).then(function (j) { flash(j.said); loadHome(); })
          .catch(function (e) { flash(e.message, 'bad'); ev.target.disabled = false; });
      }));
      row.appendChild(btn('Check against Gmail now', 'quiet', function (ev) {
        ev.target.disabled = true;
        api('/mail/reconcile', { body: { inbox: x.inbox } }).then(function (j) { flash(j.said); })
          .catch(function (e) { flash(e.message, 'bad'); ev.target.disabled = false; });
      }));
      card.appendChild(row);
    });
    return card;
  }

  // What each kind of item must carry, from rouh/synapse/kinds.py.
  function kindsView(list) {
    var card = el('section', 'syn-card');
    add(card, el('h4', null, 'Kinds and what each must carry'), el('p', 'syn-note', 'Everything Synapse knows is one item with a kind. ' +
      'Every item has ' + (((list[0] || {}).common) || []).join(', ') + '. A kind\'s own fields live on the item and are checked ' +
      'whenever it is stored or edited; an item missing a required one is refused.'));
    card.appendChild(table(['Kind', 'Must have', 'May have', 'Rules'], list.map(function (k) {
      return [add(el('span'), el('span', 'syn-kind k-' + k.kind, k.kind), el('span', 'syn-note', ' ' + k.about)),
        k.required.map(function (f) { return f.name; }).join(', '),
        k.optional.map(function (f) { return f.name; }).join(', '), (k.rules || []).join(' ')];
    })));
    return card;
  }

  /* --- A shortened cell, and the whole of it in a modal --------------------------------

     Petar read a cut cell as the content itself being cut (4 October 2026). So a cell
     that shows only the start of a value says so, with the whole length, and its
     "See the rest" opens all of it. `o.whole` is the value when the page has it;
     otherwise `o.load` fetches it and resolves to { meta, body }. */
  function count(n) { return Number(n || 0).toLocaleString('en-US'); }
  function cutCell(o) {
    var cell = el('div', 'syn-cut');
    cell.appendChild(el('span', 'syn-cut-text', o.preview + '...'));
    var foot = el('div', 'syn-cut-foot');
    var more = el('button', 'syn-cut-more', 'See the rest');
    more.type = 'button';
    more.addEventListener('click', function () {
      openWhole(o.title, more, o.load || function () { return Promise.resolve({ meta: o.meta, body: o.whole }); });
    });
    add(foot, el('span', null, count(o.shown) + ' of ' + count(o.total) + ' ' + o.unit), ' · ', more);
    cell.appendChild(foot);
    return cell;
  }
  // A plain string in a cell, shortened to `limit` characters only when it is longer.
  function shortText(text, limit, title) {
    text = text == null ? '' : String(text);
    if (text.length <= limit) return text;
    return cutCell({ preview: text.slice(0, limit), shown: limit, total: text.length, unit: 'characters',
      title: title, whole: text, meta: count(text.length) + ' characters' });
  }

  var WHOLE = { back: null, opener: null };
  function openWhole(title, opener, load) {
    closeWhole();
    var back = el('div', 'syn-modal-back');
    var box = el('div', 'syn-modal');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', title);
    var head = el('div', 'syn-modal-head');
    var close = el('button', 'syn-pop-x', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    close.addEventListener('click', closeWhole);
    var meta = el('p', 'syn-modal-meta', 'Reading it...');
    add(head, add(el('div', 'syn-modal-title'), el('strong', null, title), meta), close);
    var body = el('pre', 'syn-modal-body');
    add(box, head, body);
    back.appendChild(box);
    back.addEventListener('pointerdown', function (e) { if (e.target === back) closeWhole(); });
    document.body.appendChild(back);
    WHOLE.back = back; WHOLE.opener = opener;
    close.focus();
    load().then(function (got) {
      if (WHOLE.back !== back) return;
      meta.textContent = got.meta || '';
      body.textContent = got.body || '';
    }).catch(function (e) {
      if (WHOLE.back !== back) return;
      meta.textContent = 'Could not read it: ' + e.message;
      meta.classList.add('bad');
    });
  }
  function closeWhole() {
    if (!WHOLE.back) return;
    WHOLE.back.remove();
    var opener = WHOLE.opener;
    WHOLE.back = null; WHOLE.opener = null;
    if (opener && opener.isConnected) opener.focus();
  }
  document.addEventListener('keydown', function (e) {
    if (!WHOLE.back || e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    closeWhole();
  }, true);

  // The passages of an item (D24): the text is on the page whole, the words and the
  // vector are fetched whole only when asked for.
  function passageTable(itemId, passages) {
    var PREVIEW = { text: 400, words: 200, numbers: 6 };
    function fetchWhole(p) {
      p.whole = p.whole || api(dsPath('/item/' + itemId + '/passage/' + p.id)).catch(function (e) { p.whole = null; throw e; });
      return p.whole;
    }
    function dims(n) { return count(n) + ' dimensions'; }
    function vectorText(v) { return String(v || '').replace(/^\[|\]$/g, '').split(',').join(', '); }
    var t = table(['#', 'From the X-ray', 'Text', 'Words (tsvector)', 'Vector'], passages.map(function (p) {
      // A text piece is numbered 1, 2, 3 in its item; the X-ray passage has no number of its own.
      var name = p.from_xray ? 'The X-ray passage' : 'Passage ' + p.seq;
      var text = p.text || '';
      var textCell = text.length > PREVIEW.text ? cutCell({ preview: text.slice(0, PREVIEW.text), shown: PREVIEW.text,
        total: text.length, unit: 'characters', title: name + ': text', whole: text,
        meta: count(text.length) + ' characters' }) : text;
      var words = p.words || '';
      var wordsLen = p.words_len || words.length;
      var wordsCell = wordsLen > PREVIEW.words ? cutCell({ preview: words.slice(0, PREVIEW.words), shown: PREVIEW.words,
        total: wordsLen, unit: 'characters', title: name + ': words (tsvector)', load: function () {
          return fetchWhole(p).then(function (w) { return { meta: count(w.words.length) + ' characters', body: w.words }; });
        } }) : words;
      var vecCell = 'none';
      if (p.embedded) {
        var head = vectorText(p.vec_head).split(', ').slice(0, PREVIEW.numbers);
        vecCell = add(el('div'), el('div', 'syn-cut-model', p.embed_model + ', ' + dims(p.vec_dims)),
          cutCell({ preview: head.join(', '), shown: head.length, total: p.vec_dims, unit: 'numbers',
            title: name + ': vector', load: function () {
              return fetchWhole(p).then(function (w) {
                return { meta: (w.embed_model || 'no model') + ', ' + dims(w.vec_dims), body: vectorText(w.vector) };
              });
            } }));
      }
      return [p.from_xray ? 'X-ray' : p.seq, p.from_xray ? 'yes' : '', textCell, wordsCell, vecCell];
    }), 'small passages');
    return t;
  }

  function table(head, rows, cls) {
    var box = el('div', 'syn-scroll');
    var t = el('table', 'syn-table' + (cls ? ' ' + cls : ''));
    if (head) {
      var tr = el('tr');
      head.forEach(function (h) { tr.appendChild(el('th', null, h)); });
      add(t, add(el('thead'), tr));
    }
    var tb = el('tbody');
    rows.forEach(function (r) {
      var row = el('tr');
      r.forEach(function (c) {
        var td = el('td');
        if (c instanceof Node) td.appendChild(c); else td.textContent = c == null ? '' : String(c);
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    box.appendChild(t);
    return box;
  }

  function settingsTable(list, draft) {
    var groups = {};
    list.forEach(function (n) { (groups[n.group] = groups[n.group] || []).push(n); });
    var box = el('div', 'syn-settings');
    Object.keys(groups).forEach(function (g) {
      var det = el('details', 'syn-group');
      if (draft) det.open = g === 'Traversal' || g === 'Decision models';
      add(det, el('summary', null, g + ' (' + groups[g].length + ')'));
      var rows = groups[g].map(function (n) {
        var label = el('div', 'syn-set-label');
        add(label, el('span', null, n.label), el('span', 'syn-ref', n.ref));
        if (n.note) label.appendChild(el('span', 'syn-set-note', n.note));
        var badge = el('span', 'syn-badge ' + (n.starting ? 'start' : 'lab'), n.starting ? 'starting value' : 'lab choice');
        var startText = n.kind === 'table' ? 'all 1' : String(n.start);
        if (!draft) {
          return [label, n.kind === 'table' ? 'all 1' : String(n.value), add(el('span'), badge, ' ', el('span', 'syn-note', 'moves on: ' + (n.moves || '')))];
        }
        var input = settingInput(n, draft);
        var reset = btn('Back to ' + startText, 'quiet tiny', function () {
          draft[n.key] = null;
          renderTab();
        });
        var changed = (n.key in draft) ? draft[n.key] !== null : n.changed;
        var cell = add(el('div', 'syn-set-val'), input, changed ? reset : null);
        return [label, cell, add(el('span'), badge, changed ? el('span', 'syn-badge changed', 'changed') : null, ' ',
          el('span', 'syn-note', 'start ' + startText))];
      });
      det.appendChild(table(['Number', draft ? 'Value' : 'Starting value', ''], rows, 'syn-set-table'));
      box.appendChild(det);
    });
    return box;
  }

  function settingInput(n, draft) {
    var cur = (n.key in draft) ? (draft[n.key] === null ? n.start : draft[n.key]) : n.value;
    var input;
    if (n.kind === 'bool') {
      input = el('input'); input.type = 'checkbox'; input.checked = !!cur;
      input.addEventListener('change', function () { draft[n.key] = input.checked; });
    } else if (n.kind === 'choice') {
      input = el('select', 'syn-in');
      n.choices.forEach(function (c) { var o = el('option', null, c); o.value = c; if (c === cur) o.selected = true; input.appendChild(o); });
      input.addEventListener('change', function () { draft[n.key] = input.value; });
    } else if (n.kind === 'table') {
      input = el('div', 'syn-types');
      Object.keys(cur || {}).forEach(function (t) {
        var w = el('label', 'syn-type-in');
        var i = el('input', 'syn-in num'); i.type = 'number'; i.step = '0.05'; i.value = cur[t];
        i.addEventListener('change', function () {
          var next = Object.assign({}, (draft[n.key] && draft[n.key] !== null) ? draft[n.key] : cur);
          next[t] = Number(i.value);
          draft[n.key] = next;
        });
        add(w, el('span', null, t), i);
        input.appendChild(w);
      });
      return input;
    } else {
      input = el('input', 'syn-in num'); input.type = 'number';
      if (n.step != null) input.step = n.step;
      if (n.lo != null) input.min = n.lo;
      if (n.hi != null) input.max = n.hi;
      input.value = cur;
      input.addEventListener('change', function () { draft[n.key] = input.value === '' ? null : Number(input.value); });
    }
    input.setAttribute('aria-label', n.label);
    return input;
  }

  /* -------------------------------------------------------------- a dataset */

  function loadDataset() {
    return api(dsPath('')).then(function (j) {
      S.data = j;
      host().dataset && host().dataset(S.ds, j.dataset.name);
      if (!S.activity) loadActivity(true);
      draw();
    }).catch(function (e) {
      $('synBody').replaceChildren(say('That dataset could not be opened: ' + e.message, 'bad'),
        goBtn('All datasets', '', '/synapse', goHome));
    });
  }

  // Everything here is drawn again while it is read: the homepage while a
  // dataset fills, the Activity list, a running question or evaluation. Safari
  // throws its scroller back to the top when a redraw swaps its content, which
  // put Petar back at the top every two seconds (fr_296175b9a6ea), so every
  // redraw puts back where he was: on the body, while it still shows the same
  // homepage or dataset, and on a list that scrolls by itself. Even the row of
  // counts at the top of a dataset, swapped on its own, moved it.
  function keepScroll(fn, inner) {
    var body = $('synBody');
    var view = S.page === 'improvements' ? 'improvements/' + S.attempt : S.page === 'vocabulary' ? 'vocabulary' : (S.ds || '/');
    var y = body && body.dataset.view === view ? body.scrollTop : 0;
    var iy = inner ? inner.scrollTop : 0;
    fn();
    if (inner) inner.scrollTop = iy;
    if (body) { body.dataset.view = view; body.scrollTop = y; }
  }

  function renderDataset(body) {
    keepScroll(function () { drawDataset(body); });
  }

  function drawDataset(body) {
    var d = S.data;
    $('synTitle').textContent = d.dataset.name;
    // The Dreams tab has an address of its own (and each night, and what waits); every other tab is the dataset's.
    host().dataset && host().dataset(S.tab === 'dreams' ? S.ds + '/dreams' + (S.dreamView ? '/' + S.dreamView : '') : S.ds,
      d.dataset.name);
    var wrap = el('div', 'syn-dataset');
    var top = el('div', 'syn-top');
    var back = goBtn('All datasets', 'quiet', '/synapse', goHome);
    back.setAttribute('aria-label', 'All datasets');
    var c = d.counts || {};
    var chips = el('div', 'syn-chips');
    [['items', c.items], ['X-rayed', c.xrayed], ['people', c.people], ['topics', c.topics], ['layers', c.layers],
      ['rules', c.rules], ['links', c.links], ['passages', c.passages], ['vectors', c.vectors]].forEach(function (p) {
      chips.appendChild(chip(p[0], p[1]));
    });
    var jobs = (d.jobs && d.jobs.waiting) || {};
    var waiting = Object.keys(jobs).reduce(function (a, k) { return a + jobs[k]; }, 0);
    if (waiting) chips.appendChild(chip('on the queue', waiting, 'busy'));
    var chatBtn = btn('Synapse chat', 'quiet', function () { synapseChat(true); },
      'Open the Synapse chat beside it');
    var rename = btn('Rename', 'quiet', function () {
      var name = window.prompt('A new name for this dataset', d.dataset.name);
      if (!name) return;
      api(dsPath('/rename'), { body: { name: name } }).then(function () { loadDataset(); });
    });
    add(top, back, chips, add(el('div', 'syn-row'), chatBtn, rename));
    wrap.appendChild(top);
    if (d.dataset.about) wrap.appendChild(el('p', 'syn-about', d.dataset.about));
    wrap.appendChild(peopleLine(d));
    if (!d.openai_key) wrap.appendChild(say('This machine has no OpenAI key, so items are stored and found by their words only; nothing is X-rayed or embedded.', 'warn'));

    var tabs = el('div', 'syn-tabs');
    tabs.setAttribute('role', 'tablist');
    TABS.forEach(function (t) {
      var b = el('button', 'syn-tab' + (S.tab === t[0] ? ' on' : ''), t[1]);
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', S.tab === t[0] ? 'true' : 'false');
      b.addEventListener('click', function () { stopPlay(); setTab(t[0]); });
      tabs.appendChild(b);
    });
    wrap.appendChild(tabs);
    var pane = el('div', 'syn-pane');
    pane.id = 'synPane';
    wrap.appendChild(pane);
    body.replaceChildren(wrap);
    renderTab();
  }

  function peopleLine(d) {
    var ph = d.people_home || {};
    var o = ph.origins || {};
    var line = el('div', 'syn-row syn-peopleline');
    if (d.dataset.master) {
      add(line, el('span', 'syn-note', 'Its people are your contacts (' + plural(d.counts.people || 0, 'person', 'people') +
        '): kept two ways with iCloud, so an edit of one with a card reaches your phone.'));
      return line;
    }
    if (ph.own) {
      add(line, el('span', 'syn-note', 'Its people are its own (' + plural(d.counts.people || 0, 'person', 'people') +
        '), apart from your contacts in Synapse Master.'));
      return line;
    }
    add(line, el('span', 'syn-note', 'Its people come from ' + ph.name + ': ' + plural(d.counts.people || 0, 'person', 'people') +
      ' linked here, of ' + ((o.icloud || 0) + (o.synapse || 0)) + '.'),
      btn('Open ' + ph.name, 'quiet', function () { S.itemFilter = { q: '', kind: 'person', origin: '' }; openDataset(ph.id, ph.name, 'items'); }));
    return line;
  }

  function renderTab() {
    var pane = $('synPane');
    if (!pane) return;
    var fn = { activity: renderActivity, dreams: renderDreams, add: renderAdd, items: renderItems, retrieve: renderRetrieve,
      explore: renderExplore, tune: renderTune, evaluate: renderEvaluate }[S.tab];
    keepScroll(function () {
      pane.replaceChildren();
      fn(pane);
    });
  }

  function setTab(tab) {
    // Other tabs read the item list for their pickers and keep it; the Items tab reads it afresh,
    // so items stored since, and the areas the model has set since, are there.
    if (tab === 'items' && S.tab !== 'items' && !S.item) S.items = null;
    // The Dreams tab reads the nights again on the way in: a setting changed in Tune shows at once.
    if (tab === 'dreams' && S.tab !== 'dreams') loadDreams(true);
    S.tab = tab;
    renderDataset($('synBody'));
  }

  /* --- Dreams: what each night of dreaming did, and what waits ---------------------------------

     A night of dreaming compares what changed with what came before (`rouh/synapse/dreaming.py`):
     it marks claims a newer item replaced and asks a later item answered by itself, each with Undo,
     and keeps merges, kind changes and sensitivity waiting for Petar. Here: the nights as a strip of
     tiles with a stacked bar by kind, the memory's health across nights, one night opened with its
     summary, diary and changes, old beside new with their quotes, and everything that waits. */

  var DREAM_KINDS = [['superseded', 'Replaced', '#3987e5'], ['ask_closed', 'Asks closed', '#d95926'],
    ['promise_kept', 'Promises kept', '#199e70'], ['duplicate', 'Duplicates', '#c98500'],
    ['misfiled_rule', 'Rule fixes', '#d55181'], ['contradiction', 'Contradictions', '#008300'],
    ['sensitivity_mismatch', 'Sensitivity', '#9085e9'], ['link_strength', 'Links', '#e66767']];
  var DREAM_KIND = {};
  DREAM_KINDS.forEach(function (k, i) { DREAM_KIND[k[0]] = { name: k[1], colour: k[2], n: i }; });
  var DREAM_STATE = { applied: 'Applied', waiting: 'Waits for you', rejected: 'Rejected', undone: 'Undone', shown: 'For you to read' };
  var DREAM_SIDES = {
    superseded: ['Was', 'Now'], ask_closed: ['Asked', 'Answered by'], promise_kept: ['Promised', 'Kept in'],
    duplicate: ['Stored again', 'Kept as the one'], contradiction: ['One says', 'Another says'],
    misfiled_rule: ['Read as a rule', 'Is really'] };
  var DREAM_HEALTH = [['open_asks', 'Open asks still open'], ['duplicates', 'Duplicates'],
    ['contradictions', 'Contradictions flagged'], ['replaced', 'Claims replaced']];

  function dreamRunning() {
    return ((S.dreams && S.dreams.nights) || []).filter(function (n) { return n.status === 'running' || n.status === 'queued'; })[0] || null;
  }
  function dreamTotal(counts, state) {
    var t = 0;
    Object.keys(counts || {}).forEach(function (k) {
      Object.keys(counts[k] || {}).forEach(function (st) { if (!state || st === state) t += Number(counts[k][st] || 0); });
    });
    return t;
  }
  function dreamKindTotal(counts, kind) {
    var c = (counts || {})[kind] || {};
    return Object.keys(c).reduce(function (a, st) { return a + (st === 'rejected' ? 0 : Number(c[st] || 0)); }, 0);
  }
  function shortDay(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return { day: d.getDate() + ' ' + d.toLocaleString('en-GB', { month: 'short' }), week: d.toLocaleString('en-GB', { weekday: 'short' }) };
  }

  function loadDreams(quiet) {
    if (!S.ds) return;
    return api(dsPath('/dreams')).then(function (j) {
      var before = S.dreams;
      S.dreams = j;
      var nights = j.nights || [];
      var view = S.dreamView || (nights[0] ? String(nights[0].number) : '');
      var changed = !before || JSON.stringify(before.nights) !== JSON.stringify(j.nights) || before.waiting !== j.waiting;
      if (view === 'waiting') { if (!S.dreamWaiting || changed) loadDreamWaiting(); }
      else if (view) {
        var open = S.dreamNight;
        var live = nights.filter(function (n) { return String(n.number) === view; })[0];
        if (!open || String(open.number) !== view || (live && (live.status !== open.status || live.stage !== open.stage ||
            JSON.stringify(live.progress) !== JSON.stringify(open.progress) || live.waiting !== open.waiting_now))) loadDreamNight(view);
      }
      if (S.tab === 'dreams' && (changed || !quiet)) renderTab();
    }).catch(function (e) { if (!quiet) flash(e.message, 'bad'); });
  }
  function loadDreamNight(n) {
    return api(dsPath('/dreams/night/' + n)).then(function (j) {
      S.dreamNight = j;
      if (S.tab === 'dreams') renderTab();
    }).catch(function (e) { flash(e.message, 'bad'); });
  }
  function loadDreamWaiting() {
    return api(dsPath('/dreams/waiting')).then(function (j) {
      S.dreamWaiting = j;
      if (S.tab === 'dreams') renderTab();
    }).catch(function (e) { flash(e.message, 'bad'); });
  }
  // Read again every couple of seconds while a night runs, and every half minute otherwise.
  function dreamsTick() {
    S.dreamTick++;
    if (dreamRunning() || S.dreamTick % 15 === 0) loadDreams(true);
  }
  function dreamGo(view, focus) {
    S.dreamView = view == null ? '' : String(view);
    S.dreamNight = null; S.dreamConfirm = false; S.dreamFocus = focus || 0;
    if (S.tab !== 'dreams') { S.tab = 'dreams'; renderDataset($('synBody')); } else renderDataset($('synBody'));
    loadDreams(true);
  }

  function renderDreams(pane) {
    var d = S.dreams;
    if (!d) { pane.appendChild(el('p', 'syn-loading', 'Reading the nights...')); loadDreams(); return; }
    var nights = d.nights || [];
    var run = dreamRunning();
    var wrap = el('div', 'dr');
    var head = el('section', 'syn-card dr-head');
    var top = el('div', 'dr-top');
    var title = el('div', 'dr-title');
    add(title, el('h4', null, 'Dreams'), el('p', 'syn-note', 'Each night Synapse compares what changed with what came before. ' +
      'Replaced facts, closed asks and link moves apply by themselves, each with Undo; merges, rule fixes and sensitivity wait for you; ' +
      'contradictions are only shown.'));
    var acts = el('div', 'syn-row dr-acts');
    var now = btn(run ? (run.status === 'queued' ? 'Starting...' : 'Dreaming...') : 'Dream now', 'primary', function () {
      now.disabled = true;
      api(dsPath('/dreams/run'), { body: {} }).then(function (j) {
        flash('Night ' + j.number + ' is starting: it shows below as it runs.');
        dreamGo(j.number);
      }).catch(function (e) { flash(e.message, 'bad'); now.disabled = false; });
    }, 'Run a night over this dataset now, on the backfill lane');
    now.disabled = !!run;
    var wait = btn('Waiting for you' + (d.waiting ? ' (' + d.waiting + ')' : ''), 'dr-waitbtn' + (S.dreamView === 'waiting' ? ' on' : '') + (d.waiting ? ' has' : ''),
      function () { dreamGo(S.dreamView === 'waiting' ? '' : 'waiting'); }, 'Every change still waiting for you, across nights');
    wait.setAttribute('aria-pressed', S.dreamView === 'waiting' ? 'true' : 'false');
    add(acts, now, wait);
    add(top, title, acts);
    head.appendChild(top);
    var line = [];
    var st = d.settings || {};
    if (d.schedule) line.push('Nightly at 04:00: ' + (d.schedule.state === 'on' ? 'on' + (d.schedule.when ? ', next ' + d.schedule.when : '') : d.schedule.state + ', until it is turned on'));
    line.push('spend cap $' + Number(st.dream_cap_usd || 0).toFixed(2) + ' a night');
    line.push('at most ' + Math.round(Number(st.dream_guard_share || 0) * 100) + '% of an area changed in one night');
    var autoOn = [['dream_auto_replaced', 'replaced'], ['dream_auto_closed', 'closed asks'], ['dream_auto_links', 'links'],
      ['dream_auto_duplicates', 'duplicates'], ['dream_auto_kinds', 'rule fixes'], ['dream_auto_sensitivity', 'sensitivity']]
      .filter(function (k) { return st[k[0]]; }).map(function (k) { return k[1]; });
    line.push('applies by itself: ' + (autoOn.join(', ') || 'nothing'));
    add(head, el('p', 'syn-note dr-settings', line.join(' · ') + '. Change these in Tune, under Dreaming.'));
    wrap.appendChild(head);

    if (!nights.length) {
      var empty = el('section', 'syn-card dr-empty');
      add(empty, el('div', 'dr-moon', '☾'), el('h5', null, 'Synapse has not dreamed over this dataset yet'),
        el('p', 'syn-note', 'A night reads what changed since the last one, and the oldest items no night has read, with their neighbours: ' +
          'the same thread, person, task or topic, and the closest by words and meaning. Press Dream now to run the first.'));
      if (d.example && d.examples_missing) {
        empty.appendChild(add(el('div', 'syn-row'), btn('Add the dream examples (' + d.examples_missing + ' items)', '', function (e) {
          e.target.disabled = true;
          api(dsPath('/dreams/examples'), { body: {} }).then(function () {
            flash('Adding them: they show in Activity, and a night can find each kind once they are read.');
          }).catch(function (er) { flash(er.message, 'bad'); });
        }), el('span', 'syn-note', 'An old and a new code, a moved date, an answered ask, a receipt stored twice, a rule that is a fact, a contradiction.')));
      }
      wrap.appendChild(empty);
      pane.appendChild(wrap);
      return;
    }
    if (d.example && d.examples_missing) {
      wrap.appendChild(add(el('div', 'syn-row dr-examples'), el('span', 'syn-note', 'This example set was made before its dream examples.'),
        btn('Add the dream examples (' + d.examples_missing + ')', 'quiet', function (e) {
          e.target.disabled = true;
          api(dsPath('/dreams/examples'), { body: {} }).then(function () { flash('Adding them: they show in Activity.'); })
            .catch(function (er) { flash(er.message, 'bad'); });
        })));
    }
    wrap.appendChild(dreamStrip(nights));
    wrap.appendChild(dreamHealth(nights, d.health_now));
    var body = el('div', 'dr-body');
    body.id = 'drBody';
    if (S.dreamView === 'waiting') body.appendChild(dreamWaitingView());
    else body.appendChild(dreamNightView());
    wrap.appendChild(body);
    pane.appendChild(wrap);
    if (S.dreamFocus) {
      var card = pane.querySelector('[data-change="' + S.dreamFocus + '"]');
      if (card) {
        S.dreamFocus = 0;
        card.classList.add('focus');
        setTimeout(function () { card.scrollIntoView({ block: 'center' }); }, 30);
      }
    }
  }

  // The strip of nights, newest first, like a row of a calendar: a tile each, its stacked bar by kind
  // as long as the night was busy against the busiest, and a badge for what still waits.
  function dreamStrip(nights) {
    var box = el('section', 'dr-strip-wrap');
    box.setAttribute('aria-label', 'Nights, newest first');
    var strip = el('div', 'dr-strip');
    strip.setAttribute('role', 'list');
    var most = Math.max.apply(null, nights.map(function (n) { return dreamTotal(n.counts) - dreamTotal(n.counts, 'rejected'); }).concat([1]));
    var open = S.dreamView === 'waiting' ? '' : (S.dreamView || String(nights[0].number));
    nights.forEach(function (n) {
      var t = el('button', 'dr-tile st-' + n.status + (String(n.number) === open ? ' on' : '') + (n.undone_at ? ' undone' : ''));
      t.type = 'button';
      t.setAttribute('role', 'listitem');
      var dd = shortDay(n.started_at);
      var total = dreamTotal(n.counts) - dreamTotal(n.counts, 'rejected');
      var bar = el('span', 'dr-bar');
      bar.setAttribute('aria-hidden', 'true');
      var fill = el('span', 'dr-bar-fill');
      fill.style.width = (total ? Math.max(8, Math.round(total / most * 100)) : 0) + '%';
      DREAM_KINDS.forEach(function (k) {
        var c = dreamKindTotal(n.counts, k[0]);
        if (!c) return;
        var seg = el('span', 'dr-seg');
        seg.style.flexGrow = c;
        seg.style.background = k[2];
        seg.title = c + ' ' + k[1].toLowerCase();
        fill.appendChild(seg);
      });
      bar.appendChild(fill);
      var mark = n.status === 'running' || n.status === 'queued' ? el('span', 'dr-mark live', n.status === 'queued' ? 'starting' : 'dreaming') :
        n.status === 'failed' ? el('span', 'dr-mark bad', 'failed') : (n.guard && n.guard.tripped) ? el('span', 'dr-mark warn', 'guard') :
          n.status === 'stopped' ? el('span', 'dr-mark warn', 'cap') : n.undone_at ? el('span', 'dr-mark', 'undone') : null;
      add(t, add(el('span', 'dr-tile-day'), el('span', 'dr-tile-date', dd.day || ''), el('span', 'dr-tile-week', (dd.week || '') + ' · #' + n.number)),
        bar, add(el('span', 'dr-tile-sum'), el('span', null, total ? plural(total, 'change') :
          (n.status === 'running' || n.status === 'queued') ? 'comparing...' : n.status === 'failed' ? 'nothing applied' : 'nothing to change'), mark));
      if (n.waiting) {
        var badge = el('span', 'dr-badge', String(n.waiting));
        badge.title = plural(n.waiting, 'change') + ' waiting for you';
        t.appendChild(badge);
      }
      t.setAttribute('aria-label', 'Night ' + n.number + ', ' + (dd.day || '') + ', ' + (total ? plural(total, 'change') : 'nothing to change') +
        (n.waiting ? ', ' + n.waiting + ' waiting for you' : '') + (n.status !== 'done' ? ', ' + n.status : ''));
      t.setAttribute('aria-current', String(n.number) === open ? 'true' : 'false');
      t.addEventListener('click', function () { dreamGo(n.number); });
      strip.appendChild(t);
    });
    var legend = el('div', 'dr-legend');
    DREAM_KINDS.forEach(function (k) {
      if (!nights.some(function (n) { return dreamKindTotal(n.counts, k[0]); })) return;
      var sw = el('span', 'dr-sw');
      sw.style.background = k[2];
      legend.appendChild(add(el('span', 'dr-legend-i'), sw, k[1]));
    });
    add(box, strip, legend);
    return box;
  }

  // The memory's health after each night, one small chart a measure (oldest on the left), each with its
  // own scale: they are counts of different things.
  function dreamHealth(nights, now) {
    var box = el('section', 'dr-health');
    box.setAttribute('aria-label', 'Memory health across nights');
    var rows = nights.filter(function (n) { return n.health && Object.keys(n.health).length; }).slice().reverse();
    DREAM_HEALTH.forEach(function (m) {
      var vals = rows.map(function (n) { return Number(n.health[m[0]] || 0); });
      var cur = now && now[m[0]] != null ? Number(now[m[0]]) : (vals.length ? vals[vals.length - 1] : 0);
      var prev = vals.length > 1 ? vals[vals.length - 2] : null;
      var tile = el('div', 'dr-h');
      var delta = prev == null ? '' : (cur - prev === 0 ? 'no change' : (cur > prev ? '+' : '') + (cur - prev) + ' since the night before');
      add(tile, el('span', 'dr-h-label', m[1]), add(el('span', 'dr-h-now'), el('b', null, String(cur)), delta ? el('span', 'dr-h-delta', delta) : null));
      tile.appendChild(sparkline(vals, rows, m[1]));
      box.appendChild(tile);
    });
    var det = el('details', 'dr-h-table');
    add(det, el('summary', null, 'As a table'), table(['Night', 'Date'].concat(DREAM_HEALTH.map(function (m) { return m[1]; })),
      rows.slice().reverse().map(function (n) {
        return ['#' + n.number, day(n.started_at)].concat(DREAM_HEALTH.map(function (m) { return String(n.health[m[0]] || 0); }));
      }), 'small'));
    box.appendChild(det);
    return box;
  }

  function sparkline(vals, rows, label) {
    var W = 160, H = 38, P = 5;
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('class', 'dr-spark');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', label + ': ' + (vals.join(', ') || 'no nights yet'));
    if (!vals.length) return svg;
    var hi = Math.max.apply(null, vals.concat([1])), lo = Math.min.apply(null, vals.concat([0]));
    var x = function (i) { return vals.length === 1 ? W / 2 : P + i * (W - 2 * P) / (vals.length - 1); };
    var y = function (v) { return H - P - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (H - 2 * P); };
    var base = document.createElementNS(ns, 'line');
    base.setAttribute('x1', 0); base.setAttribute('x2', W); base.setAttribute('y1', H - P + 1); base.setAttribute('y2', H - P + 1);
    base.setAttribute('class', 'dr-spark-base');
    svg.appendChild(base);
    if (vals.length > 1) {
      var path = document.createElementNS(ns, 'polyline');
      path.setAttribute('points', vals.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join(' '));
      path.setAttribute('class', 'dr-spark-line');
      svg.appendChild(path);
    }
    vals.forEach(function (v, i) {
      // A wide, invisible hit target per night, with the night's value as its tooltip.
      var hit = document.createElementNS(ns, 'rect');
      var w = vals.length === 1 ? W : (W - 2 * P) / (vals.length - 1);
      hit.setAttribute('x', Math.max(0, x(i) - w / 2)); hit.setAttribute('y', 0); hit.setAttribute('width', w); hit.setAttribute('height', H);
      hit.setAttribute('class', 'dr-spark-hit');
      var tip = document.createElementNS(ns, 'title');
      tip.textContent = 'Night ' + rows[i].number + ', ' + day(rows[i].started_at) + ': ' + v;
      hit.appendChild(tip);
      svg.appendChild(hit);
      if (i === vals.length - 1 || vals.length < 12) {
        var dot = document.createElementNS(ns, 'circle');
        dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(v)); dot.setAttribute('r', i === vals.length - 1 ? 3.5 : 2.5);
        dot.setAttribute('class', 'dr-spark-dot' + (i === vals.length - 1 ? ' last' : ''));
        svg.appendChild(dot);
      }
    });
    return svg;
  }

  var DREAM_STAGES = [['gather', 'Gather'], ['judge', 'Judge'], ['learn', 'Learn'], ['apply', 'Apply'], ['done', 'Done']];

  function dreamNightView() {
    var box = el('div', 'dr-night');
    var n = S.dreamNight;
    if (!n) { box.appendChild(el('p', 'syn-loading', 'Reading the night...')); return box; }
    var card = el('section', 'syn-card dr-night-card');
    var dd = shortDay(n.started_at);
    add(card, add(el('div', 'dr-night-head'), el('span', 'dr-night-n', 'Night ' + n.number),
      el('span', 'syn-note', exactTime(n.started_at) + ' · by ' + ({ schedule: 'the 04:00 schedule', page: 'Dream now', chat: 'the chat', command: 'a command' }[n.by] || n.by))));
    if (n.status === 'running' || n.status === 'queued') {
      card.appendChild(dreamProgress(n));
    } else if (n.summary) {
      card.appendChild(el('p', 'dr-summary', n.summary));
    }
    if (n.status === 'failed') card.appendChild(say(n.stopped_why || 'It failed.', 'bad'));
    if (n.guard && n.guard.tripped) card.appendChild(add(say('', 'warn'), el('b', null, 'The 25 percent guard stopped it. '), n.guard.why));
    if (n.status === 'stopped' && n.stopped_why) card.appendChild(add(say('', 'warn'), el('b', null, 'The spend cap stopped it. '), n.stopped_why));
    if (n.undone_at) card.appendChild(say('You undid this night on ' + exactTime(n.undone_at) + '.', 'note'));
    var sc = n.scope || {};
    var facts = el('div', 'dr-facts');
    [['Read', (sc.changed || 0) + ' changed' + (sc.backfill ? ' + ' + sc.backfill + ' never read' : '')],
      ['Neighbours', String(sc.neighbours || 0)], ['Groups compared', String(sc.groups || 0)],
      ['Cost', money(n.cost_usd) + ' of $' + Number(n.cap_usd || 0).toFixed(2)], ['Took', n.ms != null ? msText(n.ms) : '...']]
      .forEach(function (f) { facts.appendChild(add(el('div', 'dr-fact'), el('span', null, f[0]), el('b', null, f[1]))); });
    card.appendChild(facts);
    var acts = el('div', 'syn-row');
    if (n.trace_id) {
      acts.appendChild(btn('Every step in Activity', 'quiet', function () {
        S.traceId = n.trace_id; S.traceData = null; setTab('activity'); loadTrace(n.trace_id);
      }, 'The night step by step, with each call, its cost and its time'));
    }
    var applied = n.applied_now || 0, waitingN = n.waiting_now || 0;
    if ((applied || waitingN) && n.status !== 'running') {
      if (!S.dreamConfirm) {
        acts.appendChild(btn('Undo this night', 'danger', function () { S.dreamConfirm = true; renderTab(); }));
      } else {
        var conf = el('div', 'dr-confirm');
        conf.setAttribute('role', 'alertdialog');
        conf.setAttribute('aria-label', 'Undo night ' + n.number);
        add(conf, el('p', null, 'Undo night ' + n.number + '? This reverses ' + plural(applied, 'applied change') +
          (waitingN ? ' and withdraws ' + plural(waitingN, 'change') + ' still waiting' : '') + ', putting back exactly what they touched.'),
          add(el('div', 'syn-row'), btn('Undo ' + plural(applied + waitingN, 'change'), 'danger', function (e) {
            e.target.disabled = true;
            api(dsPath('/dreams/night/' + n.number + '/undo'), { body: {} }).then(function (j) {
              S.dreamConfirm = false;
              flash('Night ' + n.number + ' undone: ' + plural(j.undone, 'change') + ' put back' + (j.withdrawn ? ', ' + j.withdrawn + ' withdrawn' : '') + '.');
              loadDreamNight(n.number); loadDreams(true);
            }).catch(function (er) { flash(er.message, 'bad'); });
          }), btn('Keep it', 'quiet', function () { S.dreamConfirm = false; renderTab(); })));
        acts.appendChild(conf);
      }
    }
    card.appendChild(acts);
    box.appendChild(card);
    if ((n.diary || []).length && n.status !== 'running') {
      var di = el('section', 'syn-card dr-diary');
      di.appendChild(el('h6', null, 'The night\'s diary'));
      var ol = el('ol', 'dr-diary-list');
      n.diary.forEach(function (x) {
        var li = el('li', 'dr-diary-' + x.kind);
        var k = DREAM_KIND[x.kind];
        var dot = el('span', 'dr-dot');
        if (k) dot.style.background = k.colour;
        add(li, dot, el('span', null, x.text));
        ol.appendChild(li);
      });
      di.appendChild(ol);
      box.appendChild(di);
    }
    if (n.hidden) box.appendChild(say(plural(n.hidden, 'change') + ' of this night name an item you cannot read, so ' + (n.hidden === 1 ? 'it is' : 'they are') + ' not shown.', 'note'));
    if (n.status === 'running' || n.status === 'queued') return box;
    if (!(n.changes || []).length) {
      box.appendChild(add(el('section', 'syn-card dr-empty small'), el('div', 'dr-moon', '☾'), el('h5', null, 'A quiet night'),
        el('p', 'syn-note', 'Nothing it read needed a change: no newer value, no answered ask, no copy, no misread rule, no contradiction.')));
      return box;
    }
    box.appendChild(dreamChanges(n.changes, n.number));
    return box;
  }

  function dreamProgress(n) {
    var pr = n.progress || {};
    var box = el('div', 'dr-progress');
    box.setAttribute('aria-live', 'polite');
    var stage = n.status === 'queued' ? 'queued' : (pr.stage || n.stage || 'gather');
    var steps = el('ol', 'dr-stages');
    var reached = true;
    DREAM_STAGES.forEach(function (s) {
      var li = el('li', s[0] === stage ? 'now' : reached ? 'done' : '', s[1]);
      if (s[0] === stage) reached = false;
      steps.appendChild(li);
    });
    if (stage === 'queued') steps.querySelectorAll('li').forEach(function (li) { li.className = ''; });
    var words = stage === 'queued' ? 'Waiting for a slot on the backfill lane...' :
      stage === 'gather' ? 'Gathering what changed and its neighbours' + (pr.seeds ? ' (' + plural(pr.seeds, 'item') + ')' : '') + '...' :
        stage === 'judge' ? 'Comparing ' + (pr.done || 0) + ' of ' + plural(pr.groups || 0, 'group') + (pr.found ? ', ' + plural(pr.found, 'change') + ' found so far' : '') + '...' :
          stage === 'apply' ? 'Applying ' + plural(pr.changes || 0, 'change') + '...' : 'Working...';
    var bar = el('div', 'dr-pbar');
    var fill = el('span');
    fill.style.width = (stage === 'judge' && pr.groups ? Math.round((pr.done || 0) / pr.groups * 100) : stage === 'apply' ? 95 : stage === 'gather' ? 5 : 0) + '%';
    bar.appendChild(fill);
    add(box, steps, el('p', 'dr-progress-words', words), bar, el('p', 'syn-note', 'Spent so far ' + money(n.cost_usd) + ' of the $' + Number(n.cap_usd || 0).toFixed(2) + ' cap.'));
    return box;
  }

  function dreamMatches(v) {
    var f = S.dreamFilter;
    var on = Object.keys(f.kinds).filter(function (k) { return f.kinds[k]; });
    if (on.length && !f.kinds[v.kind]) return false;
    if (f.state && v.state !== f.state) return false;
    if (f.area && (v.area || '(no area)') !== f.area) return false;
    if (f.q) {
      var hay = [v.reason, v.area, v.old && v.old.title, v.old && v.old.text, v.new && v.new.title, v.new && v.new.text,
        (v.old && v.old.quotes || []).join(' '), (v.new && v.new.quotes || []).join(' '), JSON.stringify(v.effect || {}),
        (v.payload && v.payload.link_words) || ''].join(' ').toLowerCase();
      if (hay.indexOf(f.q.toLowerCase()) < 0) return false;
    }
    return true;
  }

  function dreamFilters(changes) {
    var f = S.dreamFilter;
    var bar = el('div', 'dr-filters');
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter the changes');
    var kinds = el('div', 'dr-kchips');
    DREAM_KINDS.forEach(function (k) {
      var n = changes.filter(function (v) { return v.kind === k[0]; }).length;
      if (!n) return;
      var b = el('button', 'dr-kchip' + (f.kinds[k[0]] ? ' on' : ''));
      b.type = 'button';
      b.setAttribute('aria-pressed', f.kinds[k[0]] ? 'true' : 'false');
      var dot = el('span', 'dr-dot');
      dot.style.background = k[2];
      add(b, dot, k[1] + ' ' + n);
      b.addEventListener('click', function () { f.kinds[k[0]] = !f.kinds[k[0]]; renderTab(); });
      kinds.appendChild(b);
    });
    var stateSel = el('select', 'syn-in small');
    stateSel.setAttribute('aria-label', 'State');
    [['', 'Every state']].concat(Object.keys(DREAM_STATE).map(function (k) { return [k, DREAM_STATE[k]]; })).forEach(function (o) {
      var opt = el('option', null, o[1]); opt.value = o[0]; if (f.state === o[0]) opt.selected = true; stateSel.appendChild(opt);
    });
    stateSel.addEventListener('change', function () { f.state = stateSel.value; renderTab(); });
    var areas = {};
    changes.forEach(function (v) { areas[v.area || '(no area)'] = 1; });
    var areaSel = el('select', 'syn-in small');
    areaSel.setAttribute('aria-label', 'Area');
    [['', 'Every area']].concat(Object.keys(areas).sort().map(function (a) { return [a, a]; })).forEach(function (o) {
      var opt = el('option', null, o[1]); opt.value = o[0]; if (f.area === o[0]) opt.selected = true; areaSel.appendChild(opt);
    });
    areaSel.addEventListener('change', function () { f.area = areaSel.value; renderTab(); });
    var q = el('input', 'syn-in small dr-search');
    q.type = 'search'; q.placeholder = 'Search the changes'; q.value = f.q;
    q.setAttribute('aria-label', 'Search the changes');
    q.addEventListener('input', function () {
      f.q = q.value;
      clearTimeout(q.t);
      q.t = setTimeout(function () {
        var pos = q.selectionStart;
        renderTab();
        var again = document.querySelector('.dr-search');
        if (again) { again.focus(); try { again.setSelectionRange(pos, pos); } catch (e) { /* not a text box */ } }
      }, 220);
    });
    var any = Object.keys(f.kinds).some(function (k) { return f.kinds[k]; }) || f.state || f.area || f.q;
    add(bar, kinds, add(el('div', 'dr-fsel'), stateSel, areaSel, q,
      any ? btn('Clear', 'quiet tiny', function () { S.dreamFilter = { kinds: {}, state: '', area: '', q: '' }; renderTab(); }) : null));
    return bar;
  }

  function dreamChanges(changes, night) {
    var box = el('div', 'dr-changes');
    box.appendChild(dreamFilters(changes));
    var shown = changes.filter(dreamMatches);
    if (!shown.length) {
      box.appendChild(el('p', 'syn-note dr-none', 'No change matches these filters.'));
      return box;
    }
    DREAM_KINDS.forEach(function (k) {
      var group = shown.filter(function (v) { return v.kind === k[0]; });
      if (!group.length) return;
      var sec = el('section', 'dr-group');
      sec.style.setProperty('--k', k[2]);
      var waiting = group.filter(function (v) { return v.state === 'waiting'; });
      var h = add(el('div', 'dr-group-head'), add(el('h5', null), el('span', 'dr-dot'), k[1] + ' ', el('span', 'dr-group-n', String(group.length))));
      h.querySelector('.dr-dot').style.background = k[2];
      if (waiting.length > 1) {
        add(h, add(el('div', 'syn-row'),
          btn('Approve all ' + waiting.length, 'tiny', function (e) { dreamGroup(e.target, night, k[0], 'approve'); }),
          btn('Reject all', 'tiny quiet', function (e) { dreamGroup(e.target, night, k[0], 'reject'); })));
      }
      sec.appendChild(h);
      group.forEach(function (v) { sec.appendChild(dreamCard(v)); });
      box.appendChild(sec);
    });
    return box;
  }

  function dreamGroup(button, night, kind, verdict) {
    button.disabled = true;
    api(dsPath('/dreams/group'), { body: { night: night || null, kind: kind, verdict: verdict } }).then(function (j) {
      flash(plural(j.done, 'change') + (verdict === 'approve' ? ' approved and applied.' : ' rejected.'));
      dreamRefresh();
    }).catch(function (e) { flash(e.message, 'bad'); button.disabled = false; });
  }
  function dreamRefresh() {
    if (S.dreamView === 'waiting') loadDreamWaiting(); else if (S.dreamNight) loadDreamNight(S.dreamNight.number);
    loadDreams(true);
  }
  function dreamDecide(button, v, verdict) {
    button.disabled = true;
    api(dsPath('/dreams/change/' + v.id + '/' + verdict), { body: {} }).then(function (j) {
      flash({ approve: 'Approved and applied.', reject: 'Rejected: it will not be proposed again.', undo: 'Undone: put back exactly as it was.' }[verdict] +
        (j.left && j.left.length ? ' ' + plural(j.left.length, 'field') + ' had changed since, and were left as they are.' : ''));
      dreamRefresh();
    }).catch(function (e) { flash(e.message, 'bad'); button.disabled = false; });
  }

  // One quote, highlighted where it sits in the claim's words when it is there, on its own otherwise.
  function quoteBlock(q) {
    var b = el('blockquote', 'dr-quote');
    add(b, el('mark', null, q));
    return b;
  }

  function dreamSide(v, side, label) {
    var s = v[side];
    var box = el('div', 'dr-side dr-' + side);
    if (!s) return box;
    box.appendChild(el('span', 'dr-side-label', label));
    var title = itemLink(s.id, s.title);
    title.classList.add('dr-side-title');
    add(box, title, el('span', 'dr-side-meta', [s.kind, s.said_at ? day(s.said_at) : '', s.area].filter(Boolean).join(' · ')));
    var k = s.claim_kind;
    if (v.kind === 'misfiled_rule' && side === 'new') k = (v.payload && v.payload.to_kind) || 'fact';
    if (s.text || (v.kind === 'misfiled_rule' && v.old)) {
      var text = s.text || (v.old && v.old.text) || '';
      box.appendChild(add(el('p', 'dr-claim'), k ? el('span', 'dr-ck', k.toUpperCase()) : null, text));
    }
    (s.quotes || []).forEach(function (q) { box.appendChild(quoteBlock(q)); });
    return box;
  }

  function dreamCard(v) {
    var card = el('article', 'dr-card st-' + v.state);
    card.dataset.change = v.id;
    card.style.setProperty('--k', (DREAM_KIND[v.kind] || {}).colour || '#8d9aac');
    var head = el('div', 'dr-card-head');
    // Its decision's number, which is how the person names it to Rouh.
    if (v.decision_number) {
      var tag = el('span', 'dr-number', '#' + v.decision_number);
      tag.title = 'Say “decision ' + v.decision_number + '” to Rouh to name this one';
      tag.setAttribute('aria-label', 'Decision ' + v.decision_number);
      head.appendChild(tag);
    }
    add(head, el('span', 'dr-kind', (DREAM_KIND[v.kind] || {}).name || v.kind), el('span', 'dr-state s-' + v.state, DREAM_STATE[v.state] || v.state),
      v.area ? el('span', 'dr-area', v.area) : null, v.night ? btn('Night ' + v.night, 'link dr-nightlink', function () { dreamGo(v.night, v.id); }) : null);
    card.appendChild(head);
    card.appendChild(el('p', 'dr-reason', v.reason));
    var p = v.payload || {};
    if (v.kind === 'sensitivity_mismatch') {
      var list = el('ul', 'dr-sens');
      var raised = {};
      (p.raise || []).forEach(function (r) { raised[r.id] = 1; });
      (p.levels || []).forEach(function (r) {
        var li = el('li');
        add(li, itemLink(r.id, r.title || 'an item'), el('span', 'dr-lvl l-' + r.level, r.level),
          raised[r.id] ? add(el('span', 'dr-arrow'), '→') : null, raised[r.id] ? el('span', 'dr-lvl l-' + p.to, p.to) : null);
        list.appendChild(li);
      });
      card.appendChild(list);
    } else if (v.kind === 'link_strength') {
      var lk = el('div', 'dr-link');
      add(lk, el('span', 'dr-link-words', p.link_words || ''), add(el('span', 'dr-link-move'), strengthBar(p.from), el('span', 'dr-arrow', '→'), strengthBar(p.to)));
      card.appendChild(lk);
    } else {
      var sides = DREAM_SIDES[v.kind] || ['Old', 'New'];
      var pair = el('div', 'dr-pair' + (v.kind === 'misfiled_rule' ? ' one' : ''));
      var right = v.kind === 'misfiled_rule' ? { id: v.old.id, title: v.old.title, kind: v.old.kind, said_at: v.old.said_at, area: v.old.area, text: v.old.text, quotes: [] } : v.new;
      var fake = { kind: v.kind, payload: p, old: v.old, new: right };
      add(pair, dreamSide(fake, 'old', sides[0]), el('span', 'dr-pair-arrow' + (v.kind === 'contradiction' || v.kind === 'duplicate' ? '' : ' turn'),
        v.kind === 'contradiction' ? '≠' : v.kind === 'duplicate' ? '=' : '→'),
        dreamSide(fake, 'new', sides[1] + (v.kind === 'misfiled_rule' ? ' a ' + (p.to_kind || 'fact') : '')));
      if (v.kind === 'superseded' && p.changed_on) pair.appendChild(el('span', 'dr-when', 'changed ' + day(p.changed_on)));
      card.appendChild(pair);
    }
    var e = v.effect || {};
    if (e.question && (e.before || e.after)) {
      var ef = el('div', 'dr-effect');
      add(ef, el('span', 'dr-effect-label', 'What changes in answers'), el('p', 'dr-effect-q', '“' + e.question + '”'),
        add(el('p', 'dr-effect-a'), el('span', 'dr-before', e.before || 'nothing'), el('span', 'dr-arrow', '→'), el('span', 'dr-after', e.after || 'nothing')));
      card.appendChild(ef);
    }
    if ((v.left || []).length) card.appendChild(el('p', 'syn-note', 'When it was undone, ' + plural(v.left.length, 'field') + ' had changed since and ' + (v.left.length === 1 ? 'was' : 'were') + ' left as ' + (v.left.length === 1 ? 'it was' : 'they were') + '.'));
    var acts = el('div', 'syn-row dr-card-acts');
    if (v.state === 'applied') acts.appendChild(btn('Undo', '', function (ev) { dreamDecide(ev.target, v, 'undo'); }, 'Put back exactly what this change touched'));
    if (v.state === 'waiting') {
      acts.appendChild(btn('Approve', 'primary', function (ev) { dreamDecide(ev.target, v, 'approve'); }));
      acts.appendChild(btn('Reject', '', function (ev) { dreamDecide(ev.target, v, 'reject'); }, 'It will not be proposed again'));
    }
    if (v.state === 'shown') acts.appendChild(btn('Dismiss', 'quiet', function (ev) { dreamDecide(ev.target, v, 'reject'); }, 'Read it; it will not be shown again'));
    if (v.decided_at && v.state !== 'waiting' && v.state !== 'shown') acts.appendChild(el('span', 'syn-note', DREAM_STATE[v.state] + ' ' + when(v.decided_at) + (v.decided_by && v.decided_by !== 'dream' ? ' by ' + ({ page: 'you', deletion: 'a deletion' }[v.decided_by] || v.decided_by) : '')));
    if (acts.childNodes.length) card.appendChild(acts);
    return card;
  }

  function dreamWaitingView() {
    var box = el('div', 'dr-night');
    var w = S.dreamWaiting;
    if (!w) { box.appendChild(el('p', 'syn-loading', 'Reading what waits...')); return box; }
    var card = el('section', 'syn-card');
    add(card, el('h5', null, 'Waiting for you'), el('p', 'syn-note', 'Every change any night kept for your Approve or Reject, newest night first. ' +
      'Approve applies it now, saving what it touches so it can be undone; Reject keeps it from being proposed again.'));
    box.appendChild(card);
    if (!(w.changes || []).length) {
      box.appendChild(add(el('section', 'syn-card dr-empty small'), el('div', 'dr-moon', '✓'), el('h5', null, 'Nothing waits for you'),
        el('p', 'syn-note', 'Every change the nights proposed is applied, rejected or undone.')));
      return box;
    }
    box.appendChild(dreamChanges(w.changes, null));
    return box;
  }

  // The item page's Dreams card: every change a night made that touches this item, each opening its night.
  function itemDreamsCard(list) {
    var card = el('section', 'syn-card dr-itemcard');
    card.appendChild(el('h6', null, 'Dreams (' + list.length + ')'));
    var ul = el('ul', 'dr-itemlist');
    list.forEach(function (v) {
      var li = el('li');
      var dot = el('span', 'dr-dot');
      dot.style.background = (DREAM_KIND[v.kind] || {}).colour || '#8d9aac';
      add(li, dot, el('span', 'dr-kind', (DREAM_KIND[v.kind] || {}).name || v.kind), el('span', 'dr-state s-' + v.state, DREAM_STATE[v.state] || v.state),
        el('span', 'dr-itemreason', v.reason), btn('Night ' + v.night, 'link', function () { dreamGo(v.night, v.id); }, 'Open this change on its night'));
      ul.appendChild(li);
    });
    card.appendChild(ul);
    return card;
  }

  /* --- Activity: every trace, live --------------------------------------------- */

  function loadActivity(quiet) {
    if (!S.ds) return;
    return api(dsPath('/activity')).then(function (j) {
      var before = S.activity;
      S.activity = j;
      var newest = (j.traces || [])[0];
      var known = {};
      ((before && before.traces) || []).forEach(function (t) { known[t.id] = t; });
      // The chat did something: follow it, if following is on.
      if (before && S.follow) {
        var fresh = (j.traces || []).filter(function (t) { return !known[t.id] && t.by === 'chat'; });
        if (fresh.length) {
          var t = fresh[fresh.length - 1];
          if (t.kind === 'query' && t.query_id) { openQuery(t.query_id); setTab('retrieve'); flash('The chat asked a question: it is open below.'); }
          else { S.traceId = t.id; S.traceData = null; setTab('activity'); loadTrace(t.id); flash('The chat did something: it is open below.'); }
          refreshCounts();
          return;
        }
      }
      var changed = !before || JSON.stringify(before.traces.slice(0, 12).map(sig)) !== JSON.stringify(j.traces.slice(0, 12).map(sig)) ||
        JSON.stringify(before.jobs) !== JSON.stringify(j.jobs);
      if (changed) {
        refreshCounts();
        if (S.tab === 'activity') renderActivityList();
      }
    }).catch(function () {});
  }
  function sig(t) { return [t.id, t.status, t.steps, t.ms]; }

  function refreshCounts() {
    api(dsPath('')).then(function (j) {
      S.data = j;
      var top = document.querySelector('.syn-top .syn-chips');
      if (top) keepScroll(function () {
        var c = j.counts || {};
        top.replaceChildren();
        [['items', c.items], ['X-rayed', c.xrayed], ['people', c.people], ['topics', c.topics], ['layers', c.layers],
          ['rules', c.rules], ['links', c.links], ['passages', c.passages], ['vectors', c.vectors]].forEach(function (p) {
          top.appendChild(chip(p[0], p[1]));
        });
        var jobs = (j.jobs && j.jobs.waiting) || {};
        var waiting = Object.keys(jobs).reduce(function (a, k) { return a + jobs[k]; }, 0);
        if (waiting) top.appendChild(chip('on the queue', waiting, 'busy'));
      });
      var vc = $('synVectors');
      if (vc) keepScroll(function () { drawVectors(vc); });
      var pl = document.querySelector('.syn-peopleline');
      if (pl) keepScroll(function () { pl.replaceWith(peopleLine(j)); });
      renderMeta();
    }).catch(function () {});
  }

  function renderActivity(pane) {
    var bar = el('div', 'syn-row');
    var follow = el('label', 'syn-check');
    var cb = el('input'); cb.type = 'checkbox'; cb.checked = S.follow;
    cb.addEventListener('change', function () { S.follow = cb.checked; });
    add(follow, cb, ' Follow the chat: open whatever it does');
    add(bar, el('p', 'syn-note', 'Every store, edit, deletion, question, layer, map rebuild and evaluation, newest first. ' +
      'Press one to see its steps.'), follow);
    var split = el('div', 'syn-split');
    var list = el('div', 'syn-trace-list');
    list.id = 'synTraceList';
    var detail = el('div', 'syn-trace-detail');
    detail.id = 'synTraceDetail';
    add(split, list, detail);
    add(pane, bar, split);
    renderActivityList();
    renderTraceDetail();
  }

  function renderActivityList() {
    var list = $('synTraceList');
    if (list) keepScroll(drawActivityList, list);
  }

  function drawActivityList() {
    var list = $('synTraceList');
    if (!list) return;
    var a = S.activity;
    if (!a) { list.replaceChildren(el('p', 'syn-loading', 'Reading...')); return; }
    list.replaceChildren();
    var jobs = (a.jobs && a.jobs.waiting) || {};
    var keys = Object.keys(jobs);
    var back = (a.jobs && a.jobs.backfill) || {};
    if (keys.length) list.appendChild(el('p', 'syn-queue', 'On the queue: ' + keys.map(function (k) {
      return jobs[k] + ' ' + k + (back[k] ? ' (' + (back[k] === jobs[k] ? 'all' : back[k]) + ' on the backfill lane)' : '');
    }).join(', ')));
    if (a.jobs && a.jobs.held) list.appendChild(el('p', 'syn-queue bad', 'Backfill ' + a.jobs.held + '.'));
    if (a.jobs && a.jobs.failed) list.appendChild(el('p', 'syn-queue bad', a.jobs.failed + ' jobs failed after three tries'));
    if (!(a.traces || []).length) list.appendChild(el('p', 'syn-note', 'Nothing has happened in this dataset yet. Add an item, or ask the chat to.'));
    (a.traces || []).forEach(function (t) {
      var row = el('button', 'syn-trace' + (S.traceId === t.id ? ' on' : '') + ' st-' + t.status);
      row.type = 'button';
      add(row, el('span', 'syn-kind k-' + t.kind, t.kind), el('span', 'syn-trace-title', t.title || t.kind),
        el('span', 'syn-trace-meta', [t.by, when(t.started_at), t.ms != null ? msText(t.ms) : t.status, money(t.cost_usd)].join(' · ')));
      row.addEventListener('click', function () {
        if (t.kind === 'query' && t.query_id) { openQuery(t.query_id); setTab('retrieve'); return; }
        S.traceId = t.id; S.traceData = null; renderActivityList(); loadTrace(t.id);
        var d = $('synTraceDetail');
        if (d && host().narrow && host().narrow()) d.scrollIntoView({ block: 'start' });
      });
      list.appendChild(row);
    });
  }

  function loadTrace(id, quiet) {
    return api(dsPath('/trace/' + id)).then(function (j) {
      if (S.traceId !== id) return;
      var same = S.traceData && JSON.stringify(S.traceData) === JSON.stringify(j);
      S.traceData = j;
      if (!same) renderTraceDetail();
    }).catch(function (e) { if (!quiet) flash(e.message, 'bad'); });
  }

  function renderTraceDetail(target) {
    keepScroll(function () { drawTraceDetail(target); });
  }

  function drawTraceDetail(target) {
    var box = target || $('synTraceDetail');
    if (!box) return;
    var t = S.traceData;
    if (!S.traceId) { box.replaceChildren(el('p', 'syn-note', 'Pick something on the left to see each of its steps.')); return; }
    if (!t) { box.replaceChildren(el('p', 'syn-loading', 'Reading its steps...')); return; }
    box.replaceChildren(traceView(t));
  }

  function traceView(t) {
    var wrap = el('div', 'syn-trace-view');
    var head = el('div', 'syn-trace-head');
    add(head, el('span', 'syn-kind k-' + t.kind, t.kind), el('h5', null, t.title),
      el('p', 'syn-note', [t.status, 'by ' + t.by, t.ms != null ? msText(t.ms) : 'running', money(t.cost_usd)].join(' · ')));
    if (t.item_id && t.kind !== 'delete') head.appendChild(btn('Open the item', 'quiet', function () { openItem(t.item_id); }));
    wrap.appendChild(head);
    (t.steps || []).forEach(function (st) { wrap.appendChild(stepView(st, t)); });
    if (t.status === 'queued') wrap.appendChild(say('The model\'s part is waiting on the queue; its steps appear here as it runs.', 'note'));
    if (t.status === 'running') wrap.appendChild(el('p', 'syn-loading', 'Running...'));
    if ((t.calls || []).length) {
      var det = el('details', 'syn-step');
      add(det, el('summary', null, 'Every call in this operation (' + t.calls.length + ')'));
      det.appendChild(callsTable(t.calls));
      wrap.appendChild(det);
    }
    return wrap;
  }

  function callsTable(calls, byRun) {
    var sums = {};
    calls.forEach(function (c) {
      var k = c.kind;
      sums[k] = sums[k] || { n: 0, ms: 0, cost: 0 };
      sums[k].n++; sums[k].ms += Number(c.ms || 0); sums[k].cost += Number(c.cost_usd || c.cost || 0);
    });
    var names = { generate: 'Main and helper model calls', decide: 'Decision calls', embed: 'Embeddings', db: 'Database lookups' };
    var all = { n: 0, ms: 0, cost: 0 };
    Object.keys(sums).forEach(function (k) { all.n += sums[k].n; all.ms += sums[k].ms; all.cost += sums[k].cost; });
    var box = el('div');
    var byKind = table(['Kind', 'Calls', 'Time, summed', 'Cost'], Object.keys(sums).map(function (k) {
      return [names[k] || k, sums[k].n, msText(sums[k].ms), money(sums[k].cost)];
    }).concat([['Total', all.n, msText(all.ms), money(all.cost)]]));
    byKind.querySelector('tbody tr:last-child').className = 'syn-total';
    box.appendChild(byKind);
    var head = ['Kind', 'Purpose', 'Backend', 'Model and version', 'Time', 'Tokens in/out', 'Cost', 'OK'];
    var rows = calls.map(function (c) {
      return [c.kind, c.purpose, backendName(c.backend), (c.model || '') + (c.version && c.version !== c.model ? ' (' + c.version + ')' : ''),
        msText(c.ms), (c.tokens_in || c['in'] || 0) + ' / ' + (c.tokens_out || c.out || 0), money(c.cost_usd != null ? c.cost_usd : c.cost),
        c.ok === false ? 'failed: ' + (c.error || '') : 'yes'];
    });
    if (!byRun) { box.appendChild(table(head, rows, 'small')); return box; }
    // On an item's page the calls come from every run that held it, already grouped by run,
    // newest run first: one Run cell spans each group, with what that run's calls came to.
    var groups = [];
    calls.forEach(function (c, i) {
      var g = groups[groups.length - 1];
      if (!g || g.id !== (c.trace_id || null)) groups.push(g = { id: c.trace_id || null, first: i, calls: [] });
      g.calls.push(c);
    });
    var runs = table(['Run'].concat(head), rows.map(function (r) { return [''].concat(r); }), 'small by-run');
    var trs = runs.querySelectorAll('tbody tr');
    groups.forEach(function (g) {
      var cost = 0, ms = 0;
      g.calls.forEach(function (c) { ms += Number(c.ms || 0); cost += Number(c.cost_usd || 0); });
      var td = trs[g.first].firstChild;
      td.rowSpan = g.calls.length;
      td.className = 'syn-run';
      add(td, runLink(g.calls[0]), el('span', 'syn-run-sum', plural(g.calls.length, 'call') + ' · ' + msText(ms) + ' · ' + money(cost)));
      trs[g.first].classList.add('syn-run-first');
      for (var i = g.first + 1; i < g.first + g.calls.length; i++) trs[i].removeChild(trs[i].firstChild);
    });
    box.appendChild(runs);
    return box;
  }

  // A call's run in a few words, as Activity names it: its kind (a store the worker started
  // again is a rerun) and the minute it started. Pressed, it opens that run in Activity.
  function runLink(c) {
    if (!c.trace_id) return el('span', 'syn-run-none', 'no run');
    var kind = c.trace_kind === 'store' && c.trace_by === 'worker' ? 'rerun' : (c.trace_kind || 'run');
    var at = c.trace_at ? new Date(c.trace_at) : null;
    var hm = at && !isNaN(at) ? String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0') : '';
    if (hm && at.toDateString() !== new Date().toDateString()) hm = at.getDate() + ' ' + at.toLocaleString('en-GB', { month: 'short' }) + ' ' + hm;
    var b = el('button', 'syn-link', kind + (hm ? ' ' + hm : ''));
    b.type = 'button';
    b.title = 'Open this run, step by step, in Activity' + (c.trace_at ? ' (' + exactTime(c.trace_at) + ')' : '');
    b.addEventListener('click', function () {
      S.traceId = c.trace_id; S.traceData = null; setTab('activity'); loadTrace(c.trace_id);
    });
    return b;
  }

  // D80: code gathers the evidence and decides nothing; a model makes the tier call, with a reason.
  var TIER_NAMES = ['0, junk', '1, normal', '2, important'];
  var TIER_BY = { model: 'a model: the helper model\'s tier call (D80)', decision: 'a decision model, because the helper model could not answer (D80)',
    none: 'nobody: no model could answer, so tier 1 until it is asked again (D80)', pending: 'pending: the tier call has not answered yet (D80)',
    xray: 'the helper model, moving it when it read the item (D58)', xray_call: 'the helper model, in the X-ray call that read the whole item (D82)', code: 'code, by the rules used before 4 October 2026 (D58 as first written)' };

  // An item's sensitivity_why, said in words: who set it and what the model read, then what can only
  // raise it; code's own line only while nobody else has said anything.
  function sensWhy(w) {
    w = w || {};
    var bits = [];
    if (w.set_by) bits.push('set by ' + w.set_by);
    if (w.model) bits.push('the model read: ' + w.model);
    if (w.given) bits.push('given with the item: ' + w.given);
    if (w.area) bits.push('raised to special: ' + w.area);
    if (w.decision && (w.decision.flagged || []).length) bits.push('raised by the sensitivity suggestions: ' + w.decision.flagged.join(', '));
    if (!bits.length && w.code) bits.push(w.code);
    return bits.map(function (b) { return b.charAt(0).toUpperCase() + b.slice(1).replace(/\.$/, ''); }).join('. ') || null;
  }

  function tierName(t) { return TIER_NAMES[t] != null ? TIER_NAMES[t] : String(t); }
  function tierBy(by) { return TIER_BY[by] || 'set when Synapse made it'; }

  function signalsView(sg) {
    var list = function (v) { return (v || []).join(', ') || 'none'; };
    var yes = function (v) { return v ? 'yes' : 'no'; };
    var sent = sg.sender_address || sg.sender_name;
    return kv({ kind: sg.kind, source: sg.source,
      sender: sent ? (sg.sender_name || '') + (sg.sender_address ? ' <' + sg.sender_address + '>' : '') : 'none: added by the owner, not received',
      'sender is the owner': yes(sg.sender_is_owner), 'sender is a known contact': yes(sg.sender_known_contact) + (sg.sender_contact ? ' (' + sg.sender_contact + ')' : ''),
      'items from this sender before': sent ? String(sg.sender_items || 0) : '', 'times the owner wrote to them': sent ? String(sg.owner_replies_to_sender || 0) : '',
      'often unanswered': sent ? yes(sg.sender_often_unanswered) + ' (from ' + sg.often_unanswered_from + ' items with no reply)' : '',
      to: list(sg.to), cc: list(sg.cc), recipients: String(sg.recipients || 0),
      'List-Unsubscribe header': yes(sg.list_unsubscribe), precedence: sg.precedence || 'none', 'auto-submitted': sg.auto_submitted || 'none',
      'Gmail category': sg.gmail_category || 'none', 'automatic-looking address': sg.automatic_address || 'no',
      'bulk words near the top': list(sg.bulk_words_near_top), starred: yes(sg.starred), task: sg.task || 'none', project: sg.project || 'none',
      thread: sg.thread ? sg.thread + ' (' + plural(Number(sg.thread_items || 0) + 1, 'item') + ')' : 'none', 'the owner replied in the thread': sg.thread ? yes(sg.owner_replied_in_thread) : '',
      words: String(sg.words || 0), attachments: String(sg.attachments || 0), 'attached to': sg.attached_to || '', area: sg.area || 'none',
      'Rouh\'s junk check': sg.rouh_junk_check || '' });
  }

  function tierView(d) {
    var box = el('div');
    box.appendChild(el('h6', null, 'Signals gathered by code'));
    box.appendChild(el('p', 'syn-note', 'Facts about the item, never verdicts: code decides no tier (D80).'));
    box.appendChild(signalsView(d.signals));
    box.appendChild(el('h6', null, 'Tier decided by a model'));
    box.appendChild(kv({ tier: tierName(d.tier), 'why this tier': d.why, 'tier set by': tierBy(d.by), backend: backendName(d.backend), model: d.model,
      cost: d.cost != null ? money(d.cost) : '', time: d.ms ? msText(d.ms) : '', 'prior it gives': d.prior,
      before: d.before_by === 'pending' ? 'pending, counted as normal until the call answered' :
        d.before != null ? tierName(d.before) + (d.before_by ? ', set by ' + tierBy(d.before_by) : '') : '' }));
    var failed = (d.tried || []).filter(function (t) { return !t.ok; });
    if (failed.length) box.appendChild(table(['Asked', 'What went wrong'], (d.tried || []).map(function (t) {
      return [t.by + (t.model ? ' (' + t.model + ')' : t.backend ? ' (' + backendName(t.backend) + ')' : ''), t.ok ? 'answered' : t.error];
    })));
    if (d.decision) box.appendChild(decisionView(d.decision));
    if (d.read) {
      var det = el('details', 'syn-json');
      add(det, el('summary', null, 'What the model read'), pre(d.read));
      box.appendChild(det);
    }
    return box;
  }

  function backendName(b) {
    return { openai_decisions: 'OpenAI Decisions API', generative: 'generative (log probabilities)', openai: 'OpenAI',
      postgresql: 'PostgreSQL', off: 'off' }[b] || b || '';
  }

  // How the words list ranked (search.WORDS_BACKENDS, card 1125 change 1).
  var WORDS_RANKED = {
    capped: 'the rarest words\' passages, scored by how rare each question word is and ts_rank (as on 4 October)',
    bm25: 'BM25 in PostgreSQL: each word\'s rarity, how often the passage uses it, against how long the passage is',
    pg_search: 'BM25 in ParadeDB\'s pg_search index, top passages by block-max WAND' };
  var STEP_OPEN = { area: 1, xray: 1, judgement_links: 1, code_links: 1, counts: 1, match: 1, made: 1, tier: 1, sensitivity: 1, answer: 1, quote_check: 1, topics: 1,
    diff: 1, recheck: 1, xray_diff: 1, links: 1, check: 1, apply: 1, ops: 1, assemble: 1, short_links: 1, summary: 1 };

  // Steps whose titles carry the item or question they were about.
  var DATA_STEP = { item: 'Stored one example item', question: 'One evaluation question, answered by one configuration' };

  function stepView(st, t) {
    var det = el('details', 'syn-step st-' + st.status);
    if (STEP_OPEN[st.name] || st.status === 'failed') det.open = true;
    var sum = el('summary');
    var stepTitle = el('span', 'syn-step-title', st.title || st.name);
    if (DATA_STEP[st.name]) named(stepTitle, DATA_STEP[st.name]);
    else if (/^checkpoint_\d+$/.test(st.name || '')) named(stepTitle, 'Checkpoint again, another round (D50)');
    var job = st.name === 'queued' ? queuedJob(st, t) : null;
    add(sum, el('span', 'syn-step-n', st.seq), stepTitle,
      el('span', 'syn-step-meta', (job ? [jobLine(job)] : [st.status !== 'done' ? st.status : '', msText(st.ms),
        Number(st.cost_usd) ? money(st.cost_usd) : '']).filter(Boolean).join(' · ')));
    det.appendChild(sum);
    var body = stepBody(st.name, st.data || {});
    if (job) body.insertBefore(jobView(job), body.firstChild);
    det.appendChild(body);
    return det;
  }

  // The queue's own record of a queued step (migration 0071): which lane, and when it ran.
  function queuedJob(st, t) {
    var jobs = (t && t.jobs) || [];
    var id = (st.data || {}).job;
    for (var i = 0; i < jobs.length; i++) if (String(jobs[i].id) === String(id)) return jobs[i];
    return null;
  }

  function jobLine(j) {
    if (j.done_at) return 'ran at ' + when(j.started_at) + ', ' + msText(j.waited_ms) + ' after it was queued';
    if (j.started_at) return 'running since ' + when(j.started_at);
    return 'waiting on the ' + (j.lane || 'live') + ' lane since ' + when(j.made_at);
  }

  function jobView(j) {
    var rows = { lane: j.lane === 'backfill' ? 'backfill: an import\'s work, on slots of its own, never in front of live mail'
      : 'live', queued: exactTime(j.made_at),
      'not before': j.not_before && j.not_before !== j.made_at ? exactTime(j.not_before) : '',
      started: j.started_at ? exactTime(j.started_at) : 'not yet', waited: j.started_at ? msText(j.waited_ms) : '',
      finished: j.done_at ? exactTime(j.done_at) : '', took: j.ran_ms != null ? msText(j.ran_ms) : '',
      tries: j.tries, error: j.error || '' };
    Object.keys(rows).forEach(function (k) { if (rows[k] === '' || rows[k] == null) delete rows[k]; });
    var box = kv(rows);
    box.classList.add('syn-job');
    return box;
  }

  function stepBody(name, d) {
    var box = el('div', 'syn-step-body');
    var skip = { calls: 1 };
    if (d.error) box.appendChild(say(d.error, 'bad'));
    if (d.note) box.appendChild(el('p', 'syn-note', d.note));
    if (name === 'raw') {
      box.appendChild(kv({ kind: d.kind, title: d.title, 'title by': d.title_by ? d.title_by + ': ' + (d.title_why || '') : '',
        area: d.area ? d.area + ' (set by the owner)' : (d.area === '' ? 'none came with it, so the model may suggest one' : ''),
        source: d.source + ' / ' + d.source_key, 'said at': d.said_at, words: d.words }));
      if (d.meta && Object.keys(d.meta).length) box.appendChild(kv(d.meta));
      box.appendChild(pre(d.raw));
      return box;
    }
    if (name === 'clean' && d.cut) {
      // A trace from before 4 October 2026, when code still cut quoted replies and signatures.
      box.appendChild(kv({ 'quoted lines cut': d.cut.quoted_lines, 'quoted block cut': d.cut.quote_block ? (d.cut.quote_chars + ' characters') : 'no',
        'signature cut': d.cut.signature ? 'yes' : 'no', 'words kept': d.kept_words }));
      box.appendChild(pre(d.body));
      return box;
    }
    if (name === 'clean') {
      box.appendChild(kv({ 'cut': 'nothing', words: d.words, characters: d.chars }));
      return box;
    }
    if (name === 'tier' && d.signals) {
      box.appendChild(tierView(d));
      return box;
    }
    if (d.decision) box.appendChild(decisionView(d.decision));
    if (d.screen) box.appendChild(decisionView(d.screen));
    if (name === 'embedding' && d.sample) {
      box.appendChild(kv({ model: d.model, dimensions: d.dims, passages: d.passages, 'stored as': d.stored_as, length: d.norm }));
      box.appendChild(vecBars(d.sample));
      return box;
    }
    if ((name === 'code_links' || name === 'judgement_links') && (d.links || d.made)) {
      box.appendChild(linksTable(d.links || d.made));
      if (d.refused && d.refused.length) box.appendChild(kv({ 'refused by code': d.refused.map(function (r) { return '[' + r.target + '] ' + r.why; }).join('; ') }));
      if (d.recheck) {
        box.appendChild(el('h6', null, 'Existing judgement links, re-checked (D33)'));
        box.appendChild(table(['Link', 'Verdict', 'Strength', 'Why'], d.recheck.map(function (r) {
          return [r.link, r.verdict, r.from != null ? num(r.from, 2) + ' to ' + num(r.to, 2) : '', r.why || ''];
        })));
      }
      return box;
    }
    if (name === 'xray' && d.answer) {
      box.appendChild(kv({ model: d.model, 'claims asked for': d.asked_claims, 'candidates shown': d.candidates_shown,
        'older claims shown': d.older_claims_shown }));
      // Since 4 October 2026 the model's read sets the sensitivity; older traces only say whether it raised it.
      if (d.sensitivity) box.appendChild(kv({ 'sensitivity before': d.sensitivity.before, 'sensitivity after': d.sensitivity.after,
        'sensitivity set by': d.sensitivity.set_by || d.sensitivity.why }));
      else box.appendChild(kv({ 'sensitivity raised': d.sensitivity_raised || 'no' }));
      if (d.answer.title || d.answer.area) box.appendChild(kv({ title: d.answer.title, area: d.answer.area }));
      if ((d.areas_shown || []).length) box.appendChild(kv({ 'areas shown to the model': d.areas_shown.join('; ') }));
      box.appendChild(claimsView({ gist: d.answer.gist, claims: d.answer.claims }));
      if ((d.answer.links || []).length) {
        box.appendChild(el('h6', null, 'Judgement links the model proposed'));
        box.appendChild(table(['Candidate', 'Type', 'Strength', 'Claim', 'Why'], d.answer.links.map(function (l) {
          return ['[' + l.target + ']', l.type, l.strength, l.claim >= 0 ? l.claim : '', l.why];
        })));
      }
      box.appendChild(kv({ topics: (d.answer.topics || []).map(function (t) { return t.name + ' (' + t.strength + ')'; }).join(', ') || 'none',
        'topics it refused': (d.answer.topics_refused || []).map(function (t) { return t.name + ': ' + t.why; }).join('; '),
        'topics shown to the model': d.topics_shown ? d.topics_shown.join('; ') || 'none yet' : '',
        'proposals shown to the model': d.proposals_shown ? d.proposals_shown.join('; ') || 'none' : '' }));
      box.appendChild(kv({ sensitivity: d.answer.sensitivity + ': ' + (d.answer.sensitivity_why || ''), 'tier, as the X-ray read it': d.answer.tier ? d.answer.tier + (d.answer.tier_why ? ': ' + d.answer.tier_why : '') : '',
        rules: (d.answer.rules || []).join(', ') || 'none', terms: (d.answer.terms || []).map(function (t) { return t.term + ' = ' + t.meaning; }).join('; ') || 'none' }));
      // Since 4 October 2026 the same call reads the people the text names, kept as data only (Q21).
      if (d.people_mentioned) {
        var ph = el('h6', null, 'People mentioned');
        ph.dataset.explain = 'People mentioned, in the X-ray step';
        add(box, ph, mentionsView(d.people_mentioned, false));
      }
      return box;
    }
    if (name === 'xray' && d.gist) {
      box.appendChild(kv({ gist: d.gist, words: d.words, threshold: d.threshold, why: d.why, title: d.title }));
      return box;
    }
    // Since 4 October 2026 the topics step says, for every name the X-ray proposed, what became of it (D34).
    if (name === 'topics' && d.decisions) {
      box.appendChild(kv({ rule: d.rule, 'shown to the model': d.shown.topics + ' topics, ' + d.shown.proposals + ' open proposals',
        'matched by meaning with': d.meaning.model + ', cosine ' + num(d.meaning.threshold, 2) + ' or more', 'meaning not matched because': d.meaning.note }));
      box.appendChild(d.decisions.length ? table(['Proposed', 'What happened', 'Became', 'Similarity', 'Closest name'], d.decisions.map(function (x) {
        return [x.proposed, x.outcome, x.became, x.similarity == null ? '' : num(x.similarity, 3), x.closest || ''];
      })) : el('p', 'syn-note', 'The X-ray proposed no topic for this item.'));
      if (d.refused.length) {
        box.appendChild(el('h6', null, 'Refused: too narrow, a contact, or over the limit'));
        box.appendChild(table(['Name', 'Refused by', 'Why'], d.refused.map(function (r) { return [r.name, r.by, r.why]; })));
      }
      return box;
    }
    if (name === 'area') {
      box.appendChild(kv({ before: d.before, 'set by before': d.set_by_before, 'the model said': d.the_model_said,
        'medium or kind (D83)': d.guard ? d.guard.why : '',
        after: d.after, 'set by': d.set_by, 'items proposing it': d.items_proposing != null ? d.items_proposing + ' of the ' + d.bar + ' it needs' : '',
        'sensitivity raised': d.sensitivity ? d.sensitivity.before + ' to ' + d.sensitivity.after : '',
        'areas shown to the model': (d.areas_shown || []).join('; ') || 'none yet' }));
      if (d.map) box.appendChild(kv({ map: d.map.queued ? 'marked for a rebuild (D17)' : d.map.note }));
      return box;
    }
    if (name === 'area_move') {
      box.appendChild(add(el('dl', 'syn-kv'), el('dt', null, 'item'), add(el('dd'), itemLink(d.item, d.item_title || d.item))));
      box.appendChild(kv({ from: d.from, to: d.to, 'set by': d.set_by,
        'sensitivity raised': d.sensitivity ? d.sensitivity.before + ' to ' + d.sensitivity.after : 'no' }));
      return box;
    }
    if (name === 'area_map') {
      box.appendChild(kv({ queued: d.queued ? 'yes' : 'no', waits: d.waits_s != null ? d.waits_s + ' s' : '', rule: d.rule, note: d.note }));
      return box;
    }
    if (name === 'title') {
      box.appendChild(kv({ before: d.before, 'made by before': d.by_before, 'the model wrote': d.proposed || 'nothing', after: d.after, why: d.why }));
      return box;
    }
    if (name === 'quote_check') {
      box.appendChild(kv({ claims: d.claims, kept: d.kept, rejected: d.rejected ? 'yes, the item falls back to raw' : 'no', rule: d.rule }));
      if ((d.dropped || []).length) box.appendChild(table(['Dropped claim', 'Its quote, not found in the item'], d.dropped.map(function (x) { return [x.c, x.q]; })));
      return box;
    }
    if (name === 'candidates' && d.chosen) {
      box.appendChild(kv({ 'searched with': d.searched_with, pool: d.pool,
        'from structure': d.structure != null ? d.structure : '', 'words list': d.words_list, 'meaning list': d.meaning_list,
        screened: d.screened, 'time': d.ms != null ? msText(d.ms) : '', 'database time': msText(d.db_ms) }));
      if ((d.rare_terms || []).length) box.appendChild(table(['Rarest word searched', 'Other passages holding it'],
        d.rare_terms.map(function (r) { return [r.lexeme, r.df]; }), 'small'));
      var why = d.chosen.some(function (c) { return c.structure; });
      box.appendChild(table(['#', 'Candidate', 'Kind', 'Fused score', 'Ranks'].concat(why ? ['Structure'] : []).concat(['Decision p(yes)']),
        d.chosen.map(function (c) {
          return [c.n, c.title, c.kind, num(c.rrf, 4), ranksText(c.ranks)].concat(why ? [c.structure || ''] : [])
            .concat([c.p_screen == null ? '' : num(c.p_screen, 3)]);
        })));
      return box;
    }
    if (name === 'search' && d.top) {
      var tm = d.terms || {};
      var fb = tm.found_by || {};
      box.appendChild(kv({ 'search query': d.query,
        'tasks named by number, added to the query': (d.named_tasks || []).map(function (t) {
          return '\u201c' + t.words + '\u201d is task ' + t.number + ', ' + t.title;
        }).join('; '),
        'words searched': d.words_query,
        'words ranked by': WORDS_RANKED[tm.backend] || '', 'note': tm.backend_note || '',
        'rarest words, drawing the candidates': (tm.picked || []).length && tm.backend !== 'pg_search' ? tm.picked.join(', ') + ' (' + tm.picked_df + ' passages'
          + (tm.common ? (tm.backend === 'bm25' ? ', even the rarest is commoner than ' + tm.cap
            + ', so passages holding most of the words together were looked for first'
            : ', even the rarest is commoner than ' + tm.cap + ', so its most recent were taken') : '') + ')' : '',
        'words that had to meet': tm.together ? tm.together.need + ' of ' + tm.together.words.join(', ') : '',
        'candidates kept, by how they were found': tm.found_by ? Object.keys(fb).filter(function (k) { return fb[k]; })
          .map(function (k) { return fb[k] + ' ' + k; }).join(', ') || 'none' : '',
        'words list': d.words, 'meaning list': d.meaning,
        'vector index searched': d.ef_search ? d.ef_search + ' neighbours deep (hnsw_ef_search)' : '',
        fused: d.fused, 'fusion k': d.k, 'database time': msText(d.db_ms), 'readers checked': (d.asker_readers || []).join(', '),
        'results checked once each': d.checked != null ? d.checked + (d.dropped ? ', ' + d.dropped + ' dropped' : ', none dropped') : '',
        'recent first': d.recent ? 'the last ' + d.recent.days + ' days found ' + d.recent.found
          + (d.recent.older_searched ? ', too few, so older items were searched too' : '') : '' }));
      box.appendChild(table(['Item', 'Kind', 'Fused', 'Words rank', 'Meaning rank', 'Words score', 'Cosine'], d.top.map(function (t) {
        return [itemLink(t.id, t.title), t.kind, num(t.rrf, 4), t.ranks.words || '', t.ranks.meaning || '', t.scores.words || '', t.scores.meaning || ''];
      })));
      return box;
    }
    if (name === 'seeds' && d.mmr) {
      box.appendChild(kv({ seeds: d.seeds, 'weight on relevance': d.diversity }));
      if ((d.fixed_order || []).length) box.appendChild(table(['Fixed-order seed (D56)', 'Why'], d.fixed_order.map(function (f) { return [itemLink(f.id, short(f.id)), f.why]; })));
      box.appendChild(table(['Seed', 'Relevance', 'Redundancy', 'Marginal relevance'], d.mmr.map(function (m) {
        return [itemLink(m.id, short(m.id)), num(m.relevance), num(m.redundancy), num(m.mmr)];
      })));
      return box;
    }
    if (name === 'pack' && d.text) { box.appendChild(kv({ items: d.items, tokens: d.tokens })); box.appendChild(pre(d.text)); return box; }
    if (name === 'map_rules' && d.map) { box.appendChild(kv({ asker: d.asker_name || nameOf(d.asker), mode: d.mode, 'map tokens': d.map_tokens })); box.appendChild(pre(d.map)); return box; }
    if (name === 'rules' && d.rules) {
      box.appendChild(kv({ tokens: d.tokens, budget: d.budget, 'over budget': d.over_budget ? 'yes, ask the owner to merge some' : 'no' }));
      box.appendChild(d.rules.length ? table(['Rule', 'For'], d.rules.map(function (r) { return [r.text, r['for']]; })) : el('p', 'syn-note', 'No rules apply.'));
      return box;
    }
    if (name === 'answer' && d.answer != null) {
      box.appendChild(answerView(d.answer, d.used || [], d.not_in_pack));
      return box;
    }
    if (name === 'ops' && d.ops) {
      box.appendChild(kv({ model: d.model, gist: d.gist }));
      box.appendChild(table(['Operation', 'Claim', 'Text', 'Cites', 'Why'], d.ops.map(function (o) {
        return [o.op, o.claim >= 0 ? o.claim : '', o.c, (o.from || []).map(function (n) { return '[' + n + ']'; }).join(''), o.why];
      })));
      return box;
    }
    if (name === 'assemble' && d.text) { box.appendChild(kv({ words: d.words, tokens: d.tokens, cap: d.cap, 'dropped for the cap': (d.dropped_for_cap || []).length })); box.appendChild(pre(d.text)); return box; }
    if (name === 'diff' && d.diff) {
      box.appendChild(diffView(d.diff));
      if (d.title) box.appendChild(kv({ 'title before': d.title.before, 'title after': d.title.after }));
      if (d.meta && Object.keys(d.meta).length) box.appendChild(kv(Object.fromEntries(Object.keys(d.meta).map(function (k) {
        return [k, JSON.stringify(d.meta[k].before) + ' to ' + JSON.stringify(d.meta[k].after)];
      }))));
      return box;
    }
    if (name === 'xray_diff') {
      box.appendChild(kv({ 'gist before': d.gist_before || '', 'gist after': d.gist_after || '' }));
      box.appendChild(listBlock('Claims added', d.claims_added, 'add'));
      box.appendChild(listBlock('Claims removed', d.claims_removed, 'del'));
      box.appendChild(listBlock('Claims kept', d.claims_kept, ''));
      return box;
    }
    if (name === 'links' && d.deleted) {
      box.appendChild(table(['Type', 'From', 'To', 'Strength', 'Origin'], d.deleted.map(function (l) { return [l.type, l.from, l.to, num(l.strength, 2), l.origin]; })));
      return box;
    }
    if (name === 'check' && d.phrases) {
      box.appendChild(table(['Phrase (first words)', 'Still found in'], d.phrases.map(function (p) {
        var f = Object.keys(p.found_in || {});
        return [p.phrase, f.length ? f.map(function (k) { return k + ' (' + p.found_in[k] + ')'; }).join(', ') : 'nowhere'];
      })));
      box.appendChild(say(d.found_total ? d.found_total + ' places still hold it.' : 'Nothing left anywhere.', d.found_total ? 'bad' : 'good'));
      return box;
    }
    if (name === 'summary' && d.summary) { box.appendChild(evalSummary(d.summary, d.order)); return box; }
    if (name === 'counts' && d.cards != null) { box.appendChild(importCounts(d)); return box; }
    if (name === 'queued') skip.lane = 1;  // said in the queue's own table above it
    box.appendChild(genericView(d, skip));
    return box;
  }

  // The contacts import, in numbers (decision 11).
  function importCounts(d) {
    var box = el('div');
    var rows = [['Cards read', d.cards], ['Rouh profiles read', d.profiles], ['Profiles with no card', d.profiles_without_card],
      ['People made', d.created], ['People updated', d.updated], ['Unchanged', d.unchanged],
      ['Made by Synapse before, now from contacts', d.adopted_from_synapse], ['Your own card, on the dataset\'s own person', d.my_card],
      ['Cards merged into a person who already had another card', d.cards_merged],
      ['Likely the same, flagged (same full name)', d.likely_duplicates], ['Office lines, flagged and not merged', d.shared_phone_flagged],
      ['Identifier conflicts, flagged', d.conflicts], ['Skipped (no name, address or phone)', d.skipped],
      ['Vectors queued (people something links to)', d.embeds_queued]];
    box.appendChild(table(['What', 'How many'], rows.map(function (r) { return [rowLabel(r[0]), String(r[1] == null ? 0 : r[1])]; }), 'small'));
    var ids = d.identifiers || {};
    var addd = d.identifiers_added || {};
    box.appendChild(el('h6', null, 'Identifiers'));
    box.appendChild(table(['Type', 'Now', 'Added by this run'], Object.keys(ids).sort().map(function (k) {
      return [k, String(ids[k]), String(addd[k] || 0)];
    }), 'small'));
    var o = d.people_by_origin || {};
    box.appendChild(el('h6', null, 'People by origin'));
    box.appendChild(table(['Origin', 'People'], Object.keys(o).sort().map(function (k) { return [originChip(k) || k, String(o[k])]; }), 'small'));
    return box;
  }

  function ranksText(r) {
    r = r || {};
    return Object.keys(r).map(function (k) { return k + ' ' + r[k]; }).join(', ');
  }

  function listBlock(title, items, cls) {
    var b = el('div', 'syn-listblock ' + (cls || ''));
    b.appendChild(el('h6', null, title + ' (' + (items || []).length + ')'));
    var ul = el('ul', 'syn-list');
    (items || []).forEach(function (x) { ul.appendChild(el('li', null, x)); });
    b.appendChild(ul);
    return b;
  }

  function diffView(lines) {
    var box = el('pre', 'syn-pre syn-diff');
    lines.forEach(function (l) {
      var s = el('span', l[0] === '+' && l.indexOf('+++') !== 0 ? 'add' : l[0] === '-' && l.indexOf('---') !== 0 ? 'del' : '', l + '\n');
      box.appendChild(s);
    });
    return box;
  }

  function pre(text) { return el('pre', 'syn-pre', text || ''); }

  function kv(obj) {
    var dl = el('dl', 'syn-kv');
    Object.keys(obj || {}).forEach(function (k) {
      var v = obj[k];
      if (v == null || v === '') return;
      add(dl, el('dt', null, k), el('dd', null, typeof v === 'object' ? JSON.stringify(v) : String(v)));
    });
    return dl;
  }

  function genericView(d, skip) {
    var box = el('div');
    var simple = {};
    Object.keys(d || {}).forEach(function (k) {
      if (skip && skip[k]) return;
      if (k === 'note' || k === 'error' || k === 'decision' || k === 'screen') return;
      var v = d[k];
      if (Array.isArray(v) && v.length && typeof v[0] === 'object' && v[0] !== null) {
        var keys = Object.keys(v[0]).slice(0, 8);
        box.appendChild(el('h6', null, k.replace(/_/g, ' ')));
        box.appendChild(table(keys, v.slice(0, 60).map(function (r) {
          return keys.map(function (kk) { var x = r[kk]; return x != null && typeof x === 'object' ? JSON.stringify(x) : x; });
        }), 'small'));
      } else if (v && typeof v === 'object' && !Array.isArray(v)) {
        var det = el('details', 'syn-json');
        add(det, el('summary', null, k.replace(/_/g, ' ')), pre(JSON.stringify(v, null, 1)));
        box.appendChild(det);
      } else {
        simple[k.replace(/_/g, ' ')] = Array.isArray(v) ? v.join(', ') : v;
      }
    });
    if (Object.keys(simple).length) box.insertBefore(kv(simple), box.firstChild);
    return box;
  }

  function decisionView(dec) {
    var box = el('div', 'syn-decision');
    var backend = dec.backend === 'openai_decisions' ? 'OpenAI Decisions API (' + (dec.model || 'gpt-6-luna') + ')' :
      dec.backend === 'generative' ? 'Generative backend: ' + (dec.model || '') + ', answers forced to the labels, probabilities from log probabilities' :
        dec.backend === 'off' ? 'off' : dec.backend;
    var head = el('div', 'syn-row');
    add(head, el('span', 'syn-badge dm', 'decision: ' + (dec.purpose || '')), el('span', 'syn-note', backend +
      (dec.ms != null ? ' · ' + msText(dec.ms) : '') + (dec.cost ? ' · ' + money(dec.cost) : '') + (dec.calls ? ' · ' + dec.calls + ' calls' : '') +
      (dec.version ? ' · version ' + dec.version : '')));
    box.appendChild(head);
    if (dec.asked && dec.asked !== dec.backend) box.appendChild(el('p', 'syn-note', 'Asked for: ' + backendName(dec.asked) + '. ' + (dec.why || '')));
    else if (dec.why) box.appendChild(el('p', 'syn-note', dec.why));
    if (dec.fallback) box.appendChild(say(dec.fallback, 'warn'));
    var answers = dec.answers || {};
    var qs = dec.questions || [];
    var shown = 0;
    Object.keys(answers).forEach(function (qid) {
      if (shown > 12) return;
      shown++;
      var a = answers[qid];
      var q = qs.filter(function (x) { return x.id === qid; })[0] || {};
      var row = el('div', 'syn-dq');
      add(row, el('p', 'syn-dq-q', (q.type ? q.type.toUpperCase() + ': ' : '') + (q.prompt || qid)));
      var probs = a.probabilities || {};
      Object.keys(probs).forEach(function (label) {
        var p = Number(probs[label] || 0);
        var bar = el('div', 'syn-pbar');
        var fill = el('span', 'syn-pfill' + ((a.pick === label || (q.type === 'noul' && ((label === 'yes') === (a.p_yes >= 0.5)))) ? ' on' : ''));
        fill.style.width = Math.round(p * 100) + '%';
        add(bar, fill, el('span', 'syn-plabel', label + ' ' + (p * 100).toFixed(1) + '%'));
        row.appendChild(bar);
      });
      if (a.confidence != null) row.appendChild(el('p', 'syn-note', 'confidence ' + num(a.confidence, 3) + (a.score != null ? ', score ' + num(a.score, 3) : '')));
      box.appendChild(row);
    });
    if (Object.keys(answers).length > 13) box.appendChild(el('p', 'syn-note', (Object.keys(answers).length - 13) + ' more answers, in the table above.'));
    return box;
  }

  function vecBars(v) {
    var box = el('div', 'syn-vec');
    var max = Math.max.apply(null, v.map(function (x) { return Math.abs(x); })) || 1;
    v.forEach(function (x) {
      var b = el('span', 'syn-vbar' + (x < 0 ? ' neg' : ''));
      b.style.height = Math.max(2, Math.round(Math.abs(x) / max * 40)) + 'px';
      b.title = x.toFixed(4);
      box.appendChild(b);
    });
    box.appendChild(el('span', 'syn-note', 'the first ' + v.length + ' of the vector\'s numbers'));
    return box;
  }

  function strengthBar(s) {
    var w = el('span', 'syn-sbar');
    var f = el('span', 'syn-sfill');
    f.style.width = Math.round(Number(s || 0) * 100) + '%';
    w.appendChild(f);
    w.appendChild(el('span', 'syn-slabel', num(s, 2)));
    return w;
  }

  function linksTable(links) {
    return table(['Type', 'To', 'Strength', 'Why', 'New'], (links || []).map(function (l) {
      var t = el('span', 'syn-ltype', l.type);
      t.style.borderColor = TYPE_COLOUR[l.type] || '#8d9aac';
      var to = l.to_id ? itemLink(l.to_id, l.to) : l.to;
      if (l.person) to = add(el('span', 'syn-person'), to, originChip(l.person.origin));
      return [t, to, strengthBar(l.strength), (l.why || '') + (l.person && l.person.how ? '; ' + l.person.how : ''),
        l['new'] === false ? 'updated' : 'new'];
    }));
  }

  function itemLink(id, text) {
    var a = el('button', 'syn-link', text || short(id));
    a.type = 'button';
    a.addEventListener('click', function () { openItem(id); });
    return a;
  }

  function claimsView(x) {
    var box = el('div', 'syn-xray');
    if (x.gist) box.appendChild(el('p', 'syn-gist', x.gist));
    var ul = el('ul', 'syn-claims');
    (x.claims || []).forEach(function (c) {
      var li = el('li', 'k-' + (c.k || 'fact'));
      var tag = el('span', 'syn-ckind', (c.k || 'fact').toUpperCase() + (c.k === 'ask' || c.k === 'promise' ? (c.open ? ' open' : ' closed') : ''));
      add(li, tag, el('span', 'syn-ctext', c.c));
      var bits = [];
      if (c.s) bits.push(c.s);
      if (c.due) bits.push('due ' + c.due);
      if ((c.who || []).length) bits.push('who ' + c.who.join(', '));
      if ((c.to || []).length) bits.push('to ' + c.to.join(', '));
      if ((c.from_ids || []).length) bits.push('cites ' + c.from_ids.length + ' items');
      if (bits.length) li.appendChild(el('span', 'syn-cmeta', bits.join(' · ')));
      if (c.q) li.appendChild(el('q', 'syn-quote', c.q));
      if ((c.from_ids || []).length) {
        var src = el('span', 'syn-cmeta');
        c.from_ids.forEach(function (id, i) { src.appendChild(itemLink(id, '[' + (c.from && c.from[i] || i + 1) + ']')); });
        li.appendChild(src);
      }
      ul.appendChild(li);
    });
    if (!(x.claims || []).length) ul.appendChild(el('li', 'syn-note', x.rejected || 'No claims: the raw text is the X-ray.'));
    box.appendChild(ul);
    return box;
  }

  /* --- Add ---------------------------------------------------------------------- */

  var ADD_MODES = [['note', 'A fact or note'], ['rule', 'A rule'], ['task', 'A task'], ['event', 'An event'],
    ['topic', 'A topic'], ['person', 'A person'], ['place', 'A place'],
    ['email', 'Paste an email'], ['doc', 'Paste a document'], ['files', 'Upload files']];
  var ADD_KIND = { note: 'note', rule: 'rule', task: 'task', event: 'event', topic: 'topic', person: 'person',
    place: 'place', email: 'mail', doc: 'doc' };
  var ADD_TEXT = { note: 'The fact or note', rule: 'The rule', task: 'The task', event: 'The event',
    topic: 'The topic', person: 'About the person', place: 'The place', doc: 'Document text' };

  function renderAdd(pane) {
    // The pills are the one place the kind of a new item is picked (fr_c8cc5d672892, 4 October
    // 2026: Petar wanted no second Kind dropdown below them), so every kind that can be typed in
    // has a pill of its own, and `ADD_KIND` says which kind each pill stores.
    var modes = el('div', 'syn-seg');
    ADD_MODES.forEach(function (m) {
      var b = el('button', 'syn-segb' + (S.addMode === m[0] ? ' on' : ''), m[1]);
      b.type = 'button';
      b.addEventListener('click', function () { S.addMode = m[0]; renderTab(); });
      modes.appendChild(b);
    });
    pane.appendChild(modes);
    var f = el('div', 'syn-form');
    if (S.addMode === 'files') {
      var input = el('input'); input.type = 'file'; input.multiple = true; input.accept = '.txt,.md,.markdown,.pdf,.eml,text/plain,application/pdf,message/rfc822';
      input.setAttribute('aria-label', 'Files to upload');
      var go = btn('Upload and store', 'primary', function () {
        if (!input.files.length) return;
        var fd = new FormData();
        for (var i = 0; i < input.files.length; i++) fd.append('files', input.files[i]);
        go.disabled = true;
        api(dsPath('/upload'), { body: fd }).then(function (j) { afterStore(j); }).catch(function (e) { go.disabled = false; flash(e.message, 'bad'); });
      });
      add(f, el('p', 'syn-note', 'Text, Markdown, PDF and email (.eml) files. Each becomes an item with its words unchanged; an email keeps its sender, recipients, date and thread.'), input, go);
      pane.appendChild(f);
      return;
    }
    var fields = {};
    function field(label, key, type, ph) {
      var w = el('label', 'syn-field');
      var i = type === 'area' ? el('textarea', 'syn-in') : el('input', 'syn-in');
      if (type && type !== 'area') i.type = type;
      if (ph) i.placeholder = ph;
      if (type === 'area') i.rows = 10;
      fields[key] = i;
      add(w, el('span', null, label), i);
      return w;
    }
    if (S.addMode === 'email') {
      add(f, el('p', 'syn-note', 'Paste a whole email, headers and all: lines starting From:, To:, Cc:, Subject: and Date: are read off the top, and the rest is its text, quoted replies and signatures included. Nothing is cut: the whole text is searched.'),
        field('The email', 'text', 'area', 'From: Sam Rivera <sam@example.org>\nTo: Alex <alex@example.com>\nSubject: ...\n\nHi Alex, ...'));
    } else {
      add(f, field(ADD_TEXT[S.addMode] || 'The fact or note', 'text', 'area'),
        field('Title (optional)', 'title', 'text'));
    }
    var row = el('div', 'syn-grid2');
    var mine = (S.data.people || []).filter(function (p) { return p.me; })[0];
    var readers = peoplePicker('Readers', mine ? [{ id: mine.key, name: mine.name }] : [], { empty: 'Only you: search your people to add' });
    add(row, field('When it was said (optional)', 'said_at', 'datetime-local'), field('Area (optional)', 'area', 'text', 'Clients, Team, Health...'),
      readers.node);
    var sens = el('label', 'syn-field');
    var sel = el('select', 'syn-in');
    ['', 'normal', 'private', 'special'].forEach(function (v) { var o = el('option', null, v || 'let Synapse decide'); o.value = v; sel.appendChild(o); });
    add(sens, el('span', null, 'Sensitivity'), sel);
    row.appendChild(sens);
    if (S.addMode === 'rule') row.appendChild(field('Rule for (a task, person or address)', 'rule_for', 'text'));
    f.appendChild(row);
    var store = btn('Store it', 'primary', function () {
      var text = fields.text.value;
      if (!text.trim()) { fields.text.focus(); return; }
      if (readers.problem(false)) return;
      var payload = { text: text };
      if (S.addMode === 'email') Object.assign(payload, parseEmail(text));
      if (fields.title && fields.title.value) payload.title = fields.title.value;
      if (fields.said_at.value) payload.said_at = new Date(fields.said_at.value).toISOString();
      if (fields.area.value) payload.area = fields.area.value;
      if (readers.ids().length) payload.readers = readers.ids();
      if (sel.value) payload.sensitivity = sel.value;
      payload.kind = ADD_KIND[S.addMode] || 'note';
      if (fields.rule_for && fields.rule_for.value) payload.rule_for = fields.rule_for.value.split(',').map(function (x) { return x.trim(); });
      store.disabled = true;
      api(dsPath('/items'), { body: payload }).then(function (j) { afterStore(j); }).catch(function (e) { store.disabled = false; flash(e.message, 'bad'); });
    });
    f.appendChild(store);
    pane.appendChild(f);
  }

  function parseEmail(text) {
    var out = {}, lines = text.split(/\r?\n/), i = 0;
    for (; i < lines.length; i++) {
      var m = /^(From|To|Cc|Subject|Date):\s*(.*)$/i.exec(lines[i]);
      if (!m) { if (lines[i].trim() === '') { i++; } break; }
      var k = m[1].toLowerCase(), v = m[2].trim();
      if (k === 'from') out.from = v;
      else if (k === 'to') out.to = v.split(',').map(function (x) { return x.trim(); });
      else if (k === 'cc') out.cc = v.split(',').map(function (x) { return x.trim(); });
      else if (k === 'subject') out.title = v;
      else if (k === 'date') { var d = new Date(v); if (!isNaN(d)) out.said_at = d.toISOString(); }
    }
    if (out.from || out.title) out.text = lines.slice(i).join('\n');
    return out;
  }

  function afterStore(j) {
    var first = (j.stored || []).filter(function (x) { return x.ok; })[0];
    var bad = (j.stored || []).filter(function (x) { return !x.ok; });
    if (bad.length) flash(bad[0].why || 'Not stored.', 'bad');
    if (!first) return;
    var n = (j.stored || []).length - bad.length;
    flash(j.backfill ? 'Stored ' + n + ' items, ' + j.concurrency + ' at once. Each is found by its words already; their model parts are on the queue\'s backfill lane.'
      : 'Stored. Watch its steps: code\'s part is done, the model\'s part is on the queue.');
    S.traceId = first.trace; S.traceData = null;
    loadActivity(true);
    setTab('activity');
    loadTrace(first.trace);
  }

  /* --- Items and an item's page -------------------------------------------------- */

  function loadItems() {
    return api(dsPath('/items?q=' + encodeURIComponent(S.itemFilter.q) + '&kind=' + encodeURIComponent(S.itemFilter.kind) +
      '&origin=' + encodeURIComponent(S.itemFilter.origin || ''))).then(function (j) {
      S.items = j.items; S.itemsTotal = j.total || j.items.length;
      if (S.tab === 'items' && !S.item) renderTab();
    });
  }

  function openItem(id) {
    S.item = id; S.itemData = null; S.editing = false;
    if (S.tab !== 'items') { S.tab = 'items'; renderDataset($('synBody')); } else renderTab();
    api(dsPath('/item/' + id)).then(function (j) { S.itemData = j; if (S.tab === 'items' && S.item === id) renderTab(); })
      .catch(function (e) { flash(e.message, 'bad'); });
  }

  // Under the two counts learning uses: what evaluation runs and background or other questions
  // showed and cited, which learning never counts (D57). Nothing when both are zero.
  function useRest(u) {
    if (!u) return null;
    var parts = [];
    if (u.eval_shown || u.eval_cited) parts.push('Evaluation runs: read ' + u.eval_shown + ', used ' + u.eval_cited + '.');
    if (u.other_shown || u.other_cited) parts.push('Background or other questions nobody asked: read ' + u.other_shown + ', used ' + u.other_cited + '.');
    if (!parts.length) return null;
    var p = el('p', 'syn-note syn-use-rest', 'Not counted for learning. ' + parts.join(' '));
    p.dataset.noexplain = '1';
    return p;
  }

  function renderItems(pane) {
    if (S.item) { renderItem(pane); return; }
    var bar = el('div', 'syn-row');
    var q = el('input', 'syn-in'); q.placeholder = 'Words in the title or text'; q.value = S.itemFilter.q; q.setAttribute('aria-label', 'Filter items');
    var kind = el('select', 'syn-in'); kind.setAttribute('aria-label', 'Kind');
    ['', 'mail', 'note', 'doc', 'file', 'task', 'event', 'meeting', 'person', 'place', 'topic', 'layer', 'rule'].forEach(function (k) {
      var o = el('option', null, k || 'every kind'); o.value = k; if (k === S.itemFilter.kind) o.selected = true; kind.appendChild(o);
    });
    // People by where they came from (decision 11).
    var origin = el('select', 'syn-in'); origin.setAttribute('aria-label', 'Origin');
    [['', 'any origin'], ['icloud', 'from contacts (icloud)'], ['synapse', 'made by Synapse']].forEach(function (k) {
      var o = el('option', null, k[1]); o.value = k[0]; if (k[0] === (S.itemFilter.origin || '')) o.selected = true; origin.appendChild(o);
    });
    var go = btn('Show', '', function () {
      S.itemFilter = { q: q.value, kind: origin.value && !kind.value ? 'person' : kind.value, origin: origin.value };
      S.items = null; renderTab();
    });
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') go.click(); });
    add(bar, q, kind, origin, go);
    pane.appendChild(bar);
    if (!S.items) { pane.appendChild(el('p', 'syn-loading', 'Reading items...')); loadItems(); return; }
    if (S.itemsTotal > S.items.length) pane.appendChild(el('p', 'syn-note', 'The first ' + S.items.length + ' of ' + S.itemsTotal +
      ': narrow it with words, an address or a phone number.'));
    if (S.itemFilter.kind === 'person') {
      pane.appendChild(table(['Name', 'Origin', 'Value', 'Old contact', 'Likely the same', 'Links', 'Readers'], S.items.map(function (i) {
        return [titleCell(i), originChip(i.origin), i.value == null ? '' : num(i.value, 2), i.old_ids || '',
          i.likely_same ? plural(i.likely_same, 'other') : '', i.links, (i.reader_names || []).join(', ')];
      }), 'items'));
      return;
    }
    pane.appendChild(table(['Title', 'Kind', 'Area', 'Silos', 'Said', 'Tier', 'Sensitivity', 'Claims', 'Links', 'Readers', 'State'], S.items.map(function (i) {
      return [titleCell(i), i.layer ? 'layer: ' + i.layer : (i.kind === 'person' ? add(el('span'), 'person ', originChip(i.origin)) : i.kind),
        areaCell(i), siloChips(i.silo_chips) || el('span', 'syn-dim', 'none yet'),
        day(i.said_at), i.tier_by === 'pending' ? 'pending' : i.tier, i.sensitivity, i.claims, i.links, (i.reader_names || []).join(', '), i.status];
    }), 'items'));
  }

  /* Silos (rouh/silos.py): the person's own silos, set in Rouh's Settings, Silos. An item is in one,
     several or none, each a chip: its colour as a dot and its name. On an item's page every silo is a
     chip that is pressed in or out, one press each, and the line beside them says who set them and why.
     A press is the person's own word on it, which nothing changes after; pressing the last one out
     hands it back to its source and the X-ray. Somebody limited to some silos never sees what is in
     none of theirs. */
  function siloChip(c) {
    var chip = el('span', 'silo-chip');
    if (c && /^#[0-9a-f]{6}$/i.test(c.colour || '')) chip.style.setProperty('--silo', c.colour);
    return add(chip, el('span', 'silo-dot'), el('span', 'silo-name', (c && c.name) || ''));
  }
  function siloChips(list) {
    if (!list || !list.length) return null;
    var row = el('span', 'silo-chips');
    list.forEach(function (c) { row.appendChild(siloChip(c)); });
    return row;
  }
  function silosBy(it) {
    if (!(it.silos || []).length) return 'In no silo yet. Anybody limited to some silos does not see it.';
    if (it.silos_by === 'person') return 'Set by you' + (it.silos_why && !/^[^:,]{1,40} said so$/.test(it.silos_why) ? ': ' + it.silos_why : '') + '.';
    if (it.silos_by === 'source') return 'From ' + (it.silos_why || 'where it comes from') + '.';
    if (it.silos_by === 'model') return 'Read by the X-ray.';
    return '';
  }
  function silosRow(it) {
    var row = el('div', 'syn-silos');
    var label = el('span', 'syn-silos-label', 'Silos');
    label.id = 'synSilosLabel';
    var group = el('div', 'silo-toggles');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-labelledby', label.id);
    var now = (it.silos || []).slice();
    (it.silos_all || []).forEach(function (c) {
      var on = now.indexOf(c.key) >= 0;
      var b = el('button', 'silo-toggle');
      b.type = 'button';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.appendChild(siloChip(c));
      b.addEventListener('click', function () {
        var next = on ? now.filter(function (k) { return k !== c.key; }) : now.concat([c.key]);
        Array.prototype.forEach.call(group.children, function (x) { x.disabled = true; });
        api(dsPath('/item/' + it.id + '/silos'), { body: { silos: next } }).then(function (j) {
          flash(!next.length ? 'In no silo: its source and the X-ray decide again.'
            : 'In ' + (j && j.said ? j.said : c.name) + (j && j.carried ? ', with ' + plural(j.carried, 'item') + ' inside it.' : '.'));
          openItem(it.id);
        }).catch(function (e) {
          Array.prototype.forEach.call(group.children, function (x) { x.disabled = false; });
          flash(e.message, 'bad');
        });
      });
      group.appendChild(b);
    });
    return add(row, label, group, el('span', 'syn-silos-by', silosBy(it)));
  }

  // An item's area and who set it; with none, General and any area the model proposed for it.
  function areaCell(i) {
    if (i.kind === 'person' || i.kind === 'place' || i.kind === 'topic' || i.kind === 'layer' || i.kind === 'rule') return '';
    if (i.area) return add(el('span'), i.area, el('span', 'syn-titleby', 'by ' + (i.area_by || 'owner')));
    return add(el('span', 'syn-dim'), 'General', i.area_proposed ? el('span', 'syn-titleby', 'proposed: ' + i.area_proposed) : null);
  }

  function titleCell(i) {
    var link = itemLink(i.id, i.title || '(untitled)');
    if (i.title_by !== 'model') return link;
    return add(el('span'), link, el('span', 'syn-titleby', 'title by model'));
  }

  function renderItem(pane) {
    var back = btn('All items', 'quiet', function () { S.item = ''; S.itemData = null; S.items = null; renderTab(); });
    pane.appendChild(back);
    var d = S.itemData;
    if (!d) { pane.appendChild(el('p', 'syn-loading', 'Reading the item...')); return; }
    var it = d.item;
    var head = el('div', 'syn-item-head');
    add(head, el('span', 'syn-kind k-' + it.kind, it.meta && it.meta.layer ? it.meta.layer + ' layer' : it.kind), el('h5', null, it.title || '(untitled)'),
      el('p', 'syn-note', [it.meta && it.meta.title_by === 'model' ? 'title by model' : null, 'version ' + it.version, it.said_at ? 'said ' + day(it.said_at) : '', 'stored ' + when(it.stored_at), it.status].filter(Boolean).join(' · ')));
    var actions = el('div', 'syn-row');
    if (it.kind === 'person' && d.person && d.person.origin) head.children[1].appendChild(originChip(d.person.origin));
    if (it.lives_in) actions.appendChild(btn('Lives in ' + it.lives_in.name, 'quiet', function () {
      S.itemFilter = { q: '', kind: 'person', origin: '' }; var id = it.id; openDataset(it.lives_in.id, it.lives_in.name, 'items'); openItem(id);
    }, 'This person belongs to the owner, not to this dataset: open them where they live'));
    if (it.kind !== 'layer') actions.appendChild(btn(S.editing ? 'Stop editing' : 'Edit', '', function () { S.editing = !S.editing; renderTab(); }));
    if (it.kind !== 'person' && it.kind !== 'layer' && it.kind !== 'topic') actions.appendChild(rerunButton(it));
    var del = btn('Delete', 'danger', function () {
      if (del.dataset.armed !== '1') {
        del.dataset.armed = '1';
        del.textContent = d.person && d.person.card ? 'Delete them here, from iCloud and from your phone' : 'Delete it, and everything made from it';
        return;
      }
      del.disabled = true;
      api(dsPath('/item/' + it.id + '/delete'), { body: {} }).then(function (j) {
        flash('Deleted. The cascade is open below.');
        S.item = ''; S.itemData = null; S.items = null;
        S.traceId = j.trace; S.traceData = null; setTab('activity'); loadTrace(j.trace); loadActivity(true);
      }).catch(function (e) { flash(e.message, 'bad'); });
    });
    actions.appendChild(del);
    head.appendChild(actions);
    pane.appendChild(head);
    pane.appendChild(silosRow(it));
    if (S.editing) pane.appendChild(it.kind === 'person' ? personForm(it, d.person || {}) : editForm(it));
    if (d.person) pane.appendChild(personCard(it, d.person));
    var pending = (it.meta && it.meta.pending_rules) || [];
    if (pending.length) {
      var pr = el('div', 'syn-card warn');
      pr.appendChild(el('h6', null, 'Waiting for the owner: is this a standing rule? (D59)'));
      pending.forEach(function (p) {
        pr.appendChild(add(el('div', 'syn-row'), el('span', null, p.text), btn('Make it a rule', '', function () {
          api(dsPath('/item/' + it.id + '/rule'), { body: { claim: p.claim } }).then(function () { openItem(it.id); });
        })));
      });
      pane.appendChild(pr);
    }
    var grid = el('div', 'syn-item-grid');
    var xr = el('section', 'syn-card');
    add(xr, el('h6', null, 'X-ray'), claimsView(it.xray || {}),
      el('p', 'syn-note', it.xray_by ? 'Made by ' + (it.xray_by.model || it.xray_by.by) + ' at ' + when(it.xray_by.at) +
        (it.xray_dropped ? '; ' + it.xray_dropped + ' claims dropped by the quote check' : '') : 'No X-ray yet.'));
    add(xr, el('h6', null, 'What the model reads (D11)'), pre(it.compact));
    var raw = el('section', 'syn-card');
    add(raw, el('h6', null, 'Raw, unchanged'), pre(it.raw), it.meta && Object.keys(it.meta).length ? kv(it.meta) : null);
    var perm = el('section', 'syn-card');
    add(perm, el('h6', null, 'Permissions, tier and sensitivity'), kv({ readers: (it.reader_names || []).map(function (r) { return r.name; }).join(', '),
      owner: it.owner_name || it.owner,
      area: itemArea(it), 'area set by': itemAreaBy(it),
      thread: it.meta && it.meta.thread ? it.meta.thread : null, 'thread from': itemThreadFrom(it),
      sensitivity: it.sensitivity, 'why sensitive': sensWhy(it.sensitivity_why), tier: tierName(it.tier), 'why this tier': it.tier_why,
      'tier set by': tierBy(it.tier_by),
      'source key': it.source + ' / ' + it.source_key, 'read for questions': d.use && d.use.shown, 'used in answers': d.use && d.use.cited }),
      useRest(d.use));
    if (it.tier_signals) add(perm, el('h6', null, 'Signals the tier call read'), signalsView(it.tier_signals));
    add(grid, xr, raw, perm);
    pane.appendChild(grid);
    if (it.kind !== 'person' && it.kind !== 'layer') pane.appendChild(mentionsCard(it, d.mentions_score));
    if (it.kind !== 'topic' && it.kind !== 'layer' && d.topics) pane.appendChild(topicsCard(d.topics));
    if ((d.dreams || []).length) pane.appendChild(itemDreamsCard(d.dreams));
    var out = d.links.filter(function (l) { return l.src === it.id; });
    var inn = d.links.filter(function (l) { return l.dst === it.id; });
    var lk = el('section', 'syn-card');
    lk.appendChild(el('h6', null, 'Links out (' + out.length + ') and in (' + inn.length + ')'));
    lk.appendChild(table(['Direction', 'Type', 'Other item', 'Strength', 'Base strength', 'Origin', 'By', 'Why'], out.map(function (l) {
      // A person is shown by name, with where they came from (decision 11).
      var other = l.dst_kind === 'person' ? add(el('span', 'syn-person'), itemLink(l.dst, l.dst_title || 'person'), originChip(l.dst_origin)) :
        itemLink(l.dst, l.dst_title || l.dst_kind);
      return ['out', typeChip(l.type), other, strengthBar(l.strength), num(l.base_strength, 2), l.origin, l.made_by, l.why];
    }).concat(inn.map(function (l) {
      return ['in', typeChip(l.type), itemLink(l.src, l.src_title || l.src_kind), strengthBar(l.strength), num(l.base_strength, 2), l.origin, l.made_by, l.why];
    }))));
    pane.appendChild(lk);
    var ps = el('section', 'syn-card');
    ps.appendChild(el('h6', null, 'Passages: what search searches (D24)'));
    ps.appendChild(passageTable(it.id, d.passages));
    pane.appendChild(ps);
    if (d.versions.length) {
      var vs = el('section', 'syn-card');
      vs.appendChild(el('h6', null, 'Earlier versions (D27)'));
      d.versions.forEach(function (v) {
        var det = el('details', 'syn-step');
        det.dataset.noexplain = '1';
        add(det, el('summary', null, 'Version ' + v.version + ', ' + when(v.made_at) + ', ' + (v.why || '')),
          v.raw ? diffView(lineDiff(v.raw, it.raw)) : null, v.xray ? claimsView(v.xray) : null);
        vs.appendChild(det);
      });
      pane.appendChild(vs);
    }
    if (d.derived.length) {
      pane.appendChild(add(el('section', 'syn-card'), el('h6', null, 'Built from it (deleting it reaches these)'),
        table(['Table', 'Item', 'Kind'], d.derived.map(function (x) { return [x.child_table, x.title ? itemLink(x.child_id, x.title) : x.child_id, x.kind || '']; }))));
    }
    if (d.traces.length) {
      var tr = el('section', 'syn-card');
      tr.appendChild(el('h6', null, 'Related activities'));
      var acts = el('div', 'syn-acts');
      acts.dataset.noexplain = '1';
      d.traces.forEach(function (t) { acts.appendChild(activityCard(t)); });
      tr.appendChild(acts);
      pane.appendChild(tr);
    }
    if (d.calls.length) pane.appendChild(add(el('section', 'syn-card'), el('h6', null, 'Every model and decision call that held it'), callsTable(d.calls, true)));
  }

  /* People mentioned (4 October 2026, Q21 kept open): read in the one X-ray call and kept as
     data on the item. Nothing is linked, matched or made from them yet; this only shows them. */

  // An item's X-ray made again on the queue, as the worker reprocesses it, and the page read
  // again when it is done: how an item X-rayed before 4 October 2026 gets its people.
  function rerunButton(it) {
    var b = btn('Re-run X-ray', '', function () {
      b.disabled = true; b.textContent = 'Re-running the X-ray...';
      var before = (it.xray_by && it.xray_by.at) || '';
      api(dsPath('/item/' + it.id + '/rerun'), { body: {} }).then(function () {
        flash('The X-ray is running again. This page updates when it is done.');
        var tries = 0;
        (function poll() {
          if (S.item !== it.id || S.tab !== 'items') return;
          api(dsPath('/item/' + it.id)).then(function (j) {
            var at = (j.item.xray_by && j.item.xray_by.at) || '';
            var done = at !== before && j.item.status === 'ready';
            if (done || ++tries > 80) {
              if (S.item !== it.id) return;
              S.itemData = j; renderTab();
              flash(done ? 'The X-ray was made again.' : 'Still running; open the item again later.', done ? '' : 'bad');
              return;
            }
            setTimeout(poll, 3000);
          }).catch(function () { setTimeout(poll, 3000); });
        })();
      }).catch(function (e) { b.disabled = false; b.textContent = 'Re-run X-ray'; flash(e.message, 'bad'); });
    }, 'Make this item\'s X-ray again with today\'s X-ray call: one model call, which also reads the people its text names');
    return b;
  }

  function mentionsCard(it, score) {
    var card = el('section', 'syn-card syn-mentions');
    var h = el('h6', null, 'People mentioned');
    h.dataset.explain = 'People mentioned, on an item\'s page';
    card.appendChild(h);
    var by = it.xray_by || {};
    if (it.mentions) card.appendChild(mentionsView(it.mentions, true));
    else card.appendChild(el('p', 'syn-note syn-mempty', it.kind === 'topic' ? 'A topic has no X-ray, so nothing reads it for people.' :
      by.by === 'code' ? 'No model read this item, so nobody looked for people in it: its X-ray was made by code, not by the X-ray call.' :
        by.model ? 'Its X-ray was made before 4 October 2026, when the X-ray call did not yet read the people a text names. ' +
          'It is not read again by itself: Re-run X-ray at the top fills this in for this item.' : 'Not X-rayed yet.'));
    card.appendChild(goldView(it, score));
    return card;
  }

  function idList(values, missing) {
    if (!(values || []).length) return '';
    var box = el('span', 'syn-mids');
    (values || []).forEach(function (v) {
      var line = el('span', 'syn-mid', v);
      if ((missing || []).indexOf(v) >= 0) line.appendChild(el('span', 'syn-badge badc', 'not in the text'));
      box.appendChild(line);
    });
    return box;
  }

  function quoteCell(text, found) {
    var box = el('span', 'syn-mquote');
    if (text) box.appendChild(el('q', 'syn-quote', text));
    box.appendChild(el('span', 'syn-badge ' + (found ? 'good' : 'badc'), found ? 'quote found in the text' : 'quote not in the text: kept, flagged'));
    return box;
  }

  // A table that becomes one block per row on a phone, each cell under its column's name.
  function stackTable(head, rows, cls) {
    var box = table(head, rows, 'stack ' + (cls || ''));
    box.querySelectorAll('tbody tr').forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (td, i) { td.dataset.label = head[i]; });
    });
    return box;
  }

  function mentionsView(m, withRaw) {
    var box = el('div', 'syn-mview');
    var ps = m.people_mentioned || [], ids = m.unattributed_identifiers || [];
    if (!ps.length && !ids.length) box.appendChild(el('p', 'syn-note syn-mempty', 'The X-ray found nobody named in the text, and no email, phone or handle.'));
    if (ps.length) {
      box.appendChild(stackTable(['Name', 'Emails', 'Phones', 'Handles', 'Organisation', 'Role', 'Relationship', 'Sender or recipient', 'Confidence', 'Quote'],
        ps.map(function (p) {
          var name = add(el('span', 'syn-mname'), el('b', null, p.full_name_as_written || [p.first_name, p.last_name].filter(Boolean).join(' ') || '(no name)'));
          if (p.name_latin) name.appendChild(el('span', 'syn-mlatin', p.name_latin));
          var parts = [p.first_name ? 'first ' + p.first_name : '', p.last_name ? 'last ' + p.last_name : ''].filter(Boolean).join(', ');
          if (parts) name.appendChild(el('span', 'syn-mparts', parts));
          return [name, idList(p.emails, p.identifiers_not_in_text), idList(p.phones, p.identifiers_not_in_text), idList(p.handles, p.identifiers_not_in_text),
            p.organisation || '', p.role_or_title || '', p.relationship_hint || '',
            p.is_sender_or_recipient === true ? 'yes' : p.is_sender_or_recipient === false ? 'no, only mentioned' : 'unclear',
            el('span', 'syn-conf c-' + p.confidence, p.confidence), quoteCell(p.quote, p.quote_found)];
        }), 'mentions'));
    } else if (ids.length) box.appendChild(el('p', 'syn-note syn-mempty', 'The X-ray found nobody named in the text.'));
    var uh = el('h6', null, 'Unattributed identifiers');
    uh.dataset.explain = 'Unattributed identifiers, under People mentioned';
    if (ps.length || ids.length) box.appendChild(uh);
    if (ps.length || ids.length) box.appendChild(ids.length ? stackTable(['Kind', 'Value', 'Why nobody\'s for sure', 'Quote'], ids.map(function (u) {
      var v = add(el('span', 'syn-mid'), u.value);
      if (u.in_text === false) v.appendChild(el('span', 'syn-badge badc', 'not in the text'));
      return [u.kind, v, u.why || '', quoteCell(u.quote, u.quote_found)];
    }), 'unattributed') : el('p', 'syn-note syn-mempty', 'None: every email, phone or handle the text holds, if any, is on its person.'));
    var c = m.checks || {};
    var meta = [m.model ? 'Read by ' + m.model + (m.at ? ' at ' + when(m.at) : '') : '',
      ps.length ? (ps.length - (c.quotes_failed || 0)) + ' of ' + ps.length + ' quotes found in the text by code' : '',
      c.identifiers_not_in_text ? c.identifiers_not_in_text + ' identifiers not in the text' : ''].filter(Boolean).join(' · ');
    if (meta) box.appendChild(el('p', 'syn-note', meta));
    if (withRaw) {
      var det = el('details', 'syn-json');
      add(det, el('summary', null, 'The raw JSON, exactly as stored'), pre(JSON.stringify(m, null, 2)));
      box.appendChild(det);
    }
    return box;
  }

  // Gold people: what an evaluation expects the X-ray to find in this item (Evaluate scores it).
  function goldView(it, score) {
    var box = el('div', 'syn-mgold');
    var g = it.mentions_gold;
    var h = el('h6', null, 'Gold people for Evaluate');
    box.appendChild(h);
    if (g) {
      box.appendChild(el('p', 'syn-note', (g.people || []).map(function (p) {
        var ids = [].concat(p.emails || [], p.phones || [], p.handles || []);
        return p.name + (ids.length ? ' (' + ids.join(', ') + ')' : '');
      }).join('; ') + ((g.unattributed || []).length ? '. Unattributed: ' + g.unattributed.map(function (u) { return u.value; }).join(', ') : '')));
      if (score) box.appendChild(el('p', 'syn-note', 'Against it: names ' + score.names.matched + ' of ' + score.names.gold + ' found, ' +
        (score.names.found - score.names.matched) + ' extra; identifiers ' + score.identifiers.right + ' of ' + score.identifiers.gold + ' right, ' +
        (score.identifiers.found - score.identifiers.right) + ' wrong or extra.'));
    } else box.appendChild(el('p', 'syn-note', 'None set: Evaluate does not score this item.'));
    var edit = btn(g ? 'Edit gold people' : 'Set gold people', 'quiet', function () {
      edit.remove();
      var ta = el('textarea', 'syn-in syn-mgold-in');
      ta.setAttribute('aria-label', 'Gold people, as JSON');
      ta.rows = 8;
      ta.value = JSON.stringify(g || { people: [{ name: '', emails: [], phones: [], handles: [] }], unattributed: [] }, null, 2);
      var save = btn('Save gold people', 'primary', function () {
        var val;
        try { val = JSON.parse(ta.value); } catch (e) { flash('That is not valid JSON: ' + e.message, 'bad'); return; }
        api(dsPath('/item/' + it.id + '/gold'), { body: { gold: val } }).then(function () { flash('Gold people saved.'); openItem(it.id); })
          .catch(function (e) { flash(e.message, 'bad'); });
      });
      add(box, ta, add(el('div', 'syn-row'), save));
    });
    box.appendChild(edit);
    return box;
  }

  // What a run on an item did, in the words a person would use: a reprocess is a store the
  // worker started again on its own, with no page or source behind it.
  function activityKind(t) {
    if (t.kind === 'store') return t.by === 'worker' ? { label: 'Reprocessed', cls: 'reprocess' } : { label: 'Stored', cls: 'store' };
    if (t.kind === 'edit') return { label: 'Edited', cls: 'edit' };
    if (t.kind === 'delete') return { label: 'Deleted', cls: 'delete' };
    if (t.kind === 'layer') return { label: 'Layer', cls: 'layer' };
    return { label: 'Other run', cls: 'other' };
  }
  var ACT_STATUS = { done: 'Finished', failed: 'Failed', running: 'Running', queued: 'Queued' };

  function ago(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 86400) { var h = Math.floor(s / 3600); return h + (h === 1 ? ' hour ago' : ' hours ago'); }
    var days = Math.floor(s / 86400);
    if (days === 1) return 'yesterday';
    if (days < 14) return days + ' days ago';
    return day(iso);
  }
  function exactTime(iso) {
    var d = new Date(iso);
    return isNaN(d) ? '' : d.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  // One run on an item's page, opening its step-by-step record in Activity.
  function activityCard(t) {
    var k = activityKind(t);
    var status = t.status || 'done';
    var card = el('button', 'syn-act st-' + status);
    card.type = 'button';
    card.title = 'Open this run, step by step, in Activity';
    var at = el('time', 'syn-act-when', ago(t.started_at));
    at.dateTime = t.started_at;
    at.title = exactTime(t.started_at);
    var took = t.ms != null ? 'took ' + msText(t.ms) : '';
    add(card, add(el('span', 'syn-act-top'),
      el('span', 'syn-act-kind a-' + k.cls, k.label),
      add(el('span', 'syn-act-time'), at, took ? el('span', 'syn-act-took', took) : null),
      el('span', 'syn-act-status s-' + status, ACT_STATUS[status] || status)));
    if (t.error) card.appendChild(el('span', 'syn-act-error', t.error));
    var outs = (t.outcomes || []).slice(0, 3);
    if (outs.length) {
      var ul = el('span', 'syn-act-outs');
      outs.forEach(function (o) { ul.appendChild(el('span', 'syn-act-out', o)); });
      card.appendChild(ul);
    }
    card.appendChild(el('span', 'syn-act-foot', (t.steps === 1 ? '1 step' : (t.steps || 0) + ' steps') + ' · ' + money(t.cost_usd)));
    card.addEventListener('click', function () {
      S.traceId = t.id; S.traceData = null; setTab('activity'); loadTrace(t.id);
    });
    return card;
  }

  // The topics an item is linked to, then the ones its X-ray proposed that are not topics yet (D34).
  function topicsCard(t) {
    var card = el('section', 'syn-card');
    var h = el('h6', null, 'Topics');
    h.dataset.explain = 'Topics, on an item\'s page';
    card.appendChild(h);
    if (t.linked.length) {
      var ul = el('ul', 'syn-list');
      t.linked.forEach(function (x) {
        ul.appendChild(add(el('li'), itemLink(x.id, x.title || '(untitled)'), el('span', 'syn-titleby wrap', 'linked, strength ' + num(x.strength, 2))));
      });
      card.appendChild(ul);
    } else {
      card.appendChild(el('p', 'syn-note', 'Not linked to any topic yet.'));
    }
    if (t.proposed.length) {
      var pl = el('ul', 'syn-list');
      t.proposed.forEach(function (p) {
        pl.appendChild(add(el('li'), el('span', null, p.name), el('span', 'syn-titleby wrap', proposalNote(p, t) + ' · strength ' +
          num(p.strength, 2) + ', ' + day(p.at) + (p.current ? '' : ', by an earlier X-ray of it'))));
      });
      add(card, el('p', 'syn-note', 'Proposed by this item, not topics yet:'), pl);
    }
    return card;
  }

  function proposalNote(p, t) {
    if (!p.in_window) return 'proposed over ' + t.days + ' days ago, so no longer counted';
    var n = Math.min(Number(p.backers) || 0, t.bar);
    return 'proposed, ' + n + ' of ' + t.bar + ' items needed';
  }

  function itemThreadFrom(it) {
    var m = it.meta || {};
    if (!m.thread) return null;
    if (it.source === 'upload' && it.kind === 'mail') return 'the email file\'s own headers: References, else In-Reply-To, else its Message-ID';
    // 'lab' is the Add form, the chat and the example sets: before 3 October 2026 the Add form asked for a thread.
    if (it.source === 'lab') return 'given with the item, not read from a source: an example set\'s own thread, or one typed into the Add form before it stopped asking. Nothing fills one for a pasted item now';
    return 'the source it came from (' + it.source + '), its own thread id, set by code';
  }

  function itemArea(it) {
    var m = it.meta || {};
    if (m.area) return m.area;
    return 'General' + (m.area_proposed ? ', proposed: ' + m.area_proposed + ' (waiting for enough items)' : '');
  }

  function itemAreaBy(it) {
    var m = it.meta || {};
    var by = m.area_by === 'owner' || m.area_by === 'model' ? m.area_by : (m.area ? 'owner' : '');
    if (!by) return m.area_proposed ? 'nobody yet' : '';
    return by + (m.area_why ? ': ' + m.area_why : '');
  }

  function typeChip(t) {
    var c = el('span', 'syn-ltype', t);
    c.style.borderColor = TYPE_COLOUR[t] || '#8d9aac';
    return c;
  }

  function lineDiff(a, b) {
    var x = (a || '').split('\n'), y = (b || '').split('\n'), out = [];
    var setY = {}; y.forEach(function (l) { setY[l] = 1; });
    var setX = {}; x.forEach(function (l) { setX[l] = 1; });
    x.forEach(function (l) { if (!setY[l]) out.push('-' + l); else out.push(' ' + l); });
    y.forEach(function (l) { if (!setX[l]) out.push('+' + l); });
    return out;
  }

  // A person: where they came from, what identifies them, how much they matter, and every item linked to them.
  function personCard(it, p) {
    var card = el('section', 'syn-card syn-personcard');
    card.appendChild(el('h6', null, 'This person'));
    var old = (p.old || []).map(function (o) {
      return o.contact_id + (o.store ? ' (' + o.store + ')' : '') + (o.uid ? ', vCard UID ' + o.uid : '');
    });
    card.appendChild(kv(Object.assign({
      origin: p.origin === 'icloud' ? (p.card ? 'icloud: a card in iCloud, kept two ways: an edit or a delete here reaches iCloud and the phone'
        : 'icloud: had a card in iCloud, gone from it now') : p.origin === 'synapse' ?
        'synapse: met in an item, matching nobody; never synced to iCloud or the phone' : p.origin,
      'old contact id': old.join('; '),
      value: p.value == null ? 'not computed yet' : num(p.value, 3),
      'vector': p.embedded ? 'embedded (' + plural(p.embedded, 'passage') + ')' : 'none yet: words only until something links to them'
    }, p.fields || {})));
    var vp = p.value_parts || {};
    if (vp.rule) {
      card.appendChild(el('h6', null, 'How the value was worked out (decision 9)'));
      card.appendChild(kv({ 'items they are on': vp.items, 'written to them by the owner': vp.owner_wrote_to_them,
        'answered by the owner': vp.owner_answered_them, latest: vp.latest ? when(vp.latest) : 'none', recency: vp.recency,
        activity: vp.activity, 'relationship set': vp.relationship ? 'yes' : 'no', base: vp.base, rule: vp.rule }));
    }
    if (p.aka && window.RouhPersonLinks) {
      // Its identifiers, a search to link another one in, the people likely the same with Same person and
      // Not the same, and every change with Undo: the one section the contact card draws too (personlinks.js).
      card.appendChild(window.RouhPersonLinks.section({
        ds: S.ds, person: it.id, data: p.aka, by: 'Synapse', titleTag: 'h6', className: 'syn-aka',
        open: function (id, name) { return itemLink(id, name); },
        changed: function (j) {
          flash(j.said || 'Done.');
          openItem(j.person || it.id);
        }
      }));
    } else {
      card.appendChild(el('h6', null, 'Identifiers (' + (p.identities || []).length + ')'));
      card.appendChild(table(['Type', 'Value', 'As written', 'Where it came from'], (p.identities || []).map(function (x) {
        return [x.type, x.value, x.shown, x.source];
      }), 'small'));
    }
    card.appendChild(el('h6', null, 'Items linked to them (' + (p.linked || []).length + ')'));
    card.appendChild((p.linked || []).length ? table(['Item', 'Kind', 'Link', 'Dataset', 'Said'], p.linked.map(function (l) {
      var title = String(l.dataset_id) === String(S.ds) ? itemLink(l.id, l.title) : l.title;
      return [title, l.kind, typeChip(l.type), l.dataset, day(l.said_at)];
    }), 'small') : el('p', 'syn-note', 'Nothing yet.'));
    return card;
  }

  function personForm(it, p) {
    var f = el('div', 'syn-form');
    var meta = it.meta || {};
    var name = el('input', 'syn-in'); name.value = it.title || ''; name.setAttribute('aria-label', 'Name');
    var rel = el('textarea', 'syn-in'); rel.rows = 3; rel.value = meta.relationship || ''; rel.setAttribute('aria-label', 'Who they are to the owner');
    var org = el('input', 'syn-in'); org.value = meta.organisation || ''; org.setAttribute('aria-label', 'Organisation');
    var emails = el('input', 'syn-in'); emails.placeholder = 'another address, or several, comma separated'; emails.setAttribute('aria-label', 'Add addresses');
    var phones = el('input', 'syn-in'); phones.placeholder = 'another number, or several, comma separated'; phones.setAttribute('aria-label', 'Add phone numbers');
    var known = el('input'); known.type = 'checkbox'; known.checked = !!meta.known;
    var readers = peoplePicker('Readers', it.reader_names);
    var save = btn('Save', 'primary', function () {
      if (readers.problem(true)) return;
      save.disabled = true;
      api(dsPath('/item/' + it.id + '/edit'), { body: { title: name.value, relationship: rel.value, organisation: org.value,
        emails: emails.value, phones: phones.value, known: known.checked,
        readers: readers.ids() } }).then(function (j) {
        flash('Saved. Its identifiers and value are below.');
        S.editing = false; openItem(it.id);
      }).catch(function (e) { save.disabled = false; flash(e.message, 'bad'); });
    });
    add(f, el('p', 'syn-note', p.card ? 'A contact: the name, organisation, addresses and phone numbers are written to ' +
      'iCloud when you save, and so reach your phone. Who they are to you stays in Synapse.' :
      'This person has no card in iCloud, so a change stays in Synapse and never reaches the phone.'),
      add(el('label', 'syn-field'), el('span', null, 'Name'), name),
      add(el('label', 'syn-field'), el('span', null, 'Who they are to the owner'), rel),
      add(el('div', 'syn-grid2'), add(el('label', 'syn-field'), el('span', null, 'Organisation'), org),
        readers.node,
        add(el('label', 'syn-field'), el('span', null, 'Add addresses'), emails),
        add(el('label', 'syn-field'), el('span', null, 'Add phone numbers'), phones)),
      add(el('div', 'syn-row'), add(el('label', 'syn-check'), known, ' known to the owner: their mail counts as from a known contact')), save);
    return f;
  }

  function editForm(it) {
    var f = el('div', 'syn-form');
    var title = el('input', 'syn-in'); title.value = it.title || ''; title.setAttribute('aria-label', 'Title');
    var text = el('textarea', 'syn-in'); text.rows = 12; text.value = it.raw || ''; text.setAttribute('aria-label', 'Text');
    var readers = peoplePicker('Readers', it.reader_names);
    var area = el('input', 'syn-in'); area.value = (it.meta && it.meta.area) || ''; area.setAttribute('aria-label', 'Area');
    area.placeholder = 'none: General';
    var save = btn('Save, and show what changed', 'primary', function () {
      if (readers.problem(true)) return;
      save.disabled = true;
      api(dsPath('/item/' + it.id + '/edit'), { body: { title: title.value, text: text.value, area: area.value,
        readers: readers.ids() } }).then(function (j) {
        if (j.unchanged) { flash('Nothing changed.'); save.disabled = false; return; }
        flash('Edited. Watch what is re-checked and rebuilt.');
        S.editing = false; S.item = ''; S.itemData = null;
        S.traceId = j.trace; S.traceData = null; setTab('activity'); loadTrace(j.trace); loadActivity(true);
      }).catch(function (e) { save.disabled = false; flash(e.message, 'bad'); });
    });
    add(f, add(el('label', 'syn-field'), el('span', null, 'Title'), title), add(el('label', 'syn-field'), el('span', null, 'Text'), text),
      readers.node,
      add(el('label', 'syn-field'), el('span', null, 'Area (yours is never changed by the model)'), area), save);
    return f;
  }

  /* --- Retrieve: a question, its walk, its pack and its answer --------------------- */

  function loadQueries() {
    return api(dsPath('/queries')).then(function (j) { S.queries = j; if (S.tab === 'retrieve' && !S.query) renderTab(); });
  }

  function openQuery(id) {
    S.query = id; S.queryData = null; S.frame = 0; stopPlay();
    loadQuery(id);
  }

  function loadQuery(id, quiet) {
    return api(dsPath('/query/' + id)).then(function (j) {
      if (S.query !== id) return;
      var was = S.queryData;
      S.queryData = j;
      if (!was || was.status !== j.status || JSON.stringify((was.trace || {}).steps) !== JSON.stringify((j.trace || {}).steps)) {
        if (j.status !== 'running' && (!was || was.status === 'running')) S.frame = 0;
        if (S.tab === 'retrieve') renderTab();
      }
    }).catch(function (e) { if (!quiet) flash(e.message, 'bad'); });
  }

  function askForm(onAsk, label) {
    var f = el('div', 'syn-form');
    var q = el('input', 'syn-in'); q.placeholder = 'Ask the dataset something'; q.setAttribute('aria-label', 'Question');
    var row = el('div', 'syn-grid2');
    var asker = el('select', 'syn-in'); asker.setAttribute('aria-label', 'Ask as');
    (S.data.people || []).forEach(function (p) { var o = el('option', null, p.name + (p.me ? ' (the owner)' : '')); o.value = p.key; asker.appendChild(o); });
    var ctx = el('select', 'syn-in'); ctx.setAttribute('aria-label', 'About this item');
    var none = el('option', null, 'no context item'); none.value = ''; ctx.appendChild(none);
    var mode = el('select', 'syn-in'); mode.setAttribute('aria-label', 'Mode');
    [['live', 'live: 4,000 tokens, cosine relevance'], ['background', 'background pack: 20,000 tokens, waves and frontier scoring (D71)']].forEach(function (m) {
      var o = el('option', null, m[1]); o.value = m[0]; mode.appendChild(o);
    });
    add(row, add(el('label', 'syn-field'), el('span', null, 'Ask as'), asker), add(el('label', 'syn-field'), el('span', null, 'About this item (like a mail case)'), ctx),
      add(el('label', 'syn-field'), el('span', null, 'Mode'), mode));
    function fillCtx() {
      (S.items || []).filter(function (i) { return i.kind === 'mail' || i.kind === 'note' || i.kind === 'doc'; }).slice(0, 200).forEach(function (i) {
        var o = el('option', null, i.title + ' (' + day(i.said_at) + ')'); o.value = i.id; ctx.appendChild(o);
      });
    }
    if (S.items) fillCtx(); else loadItems().then(fillCtx);
    var go = btn(label || 'Ask', 'primary', function () {
      if (!q.value.trim()) { q.focus(); return; }
      go.disabled = true;
      onAsk({ question: q.value, asker: asker.value, context: ctx.value || null, mode: mode.value }, function () { go.disabled = false; });
    });
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') go.click(); });
    add(f, q, row, go);
    return f;
  }

  function renderRetrieve(pane) {
    if (S.query) { renderQuery(pane); return; }
    pane.appendChild(askForm(function (body, done) {
      api(dsPath('/query'), { body: body }).then(function (j) { done(); openQuery(j.query); renderTab(); })
        .catch(function (e) { done(); flash(e.message, 'bad'); });
    }));
    pane.appendChild(el('h6', null, 'Earlier questions'));
    if (!S.queries) { pane.appendChild(el('p', 'syn-loading', 'Reading...')); loadQueries(); return; }
    pane.appendChild(table(['Question', 'Asked as', 'Mode', 'By', 'Time to pack', 'Cost', 'When'], S.queries.map(function (q) {
      var b = btn(q.question, 'linkish', function () { openQuery(q.id); renderTab(); });
      return [b, q.asker_name || nameOf(q.asker), q.mode + (q.label ? ' · ' + q.label : ''), q.by, msText(q.ms_pack), money(q.cost_usd), when(q.created_at)];
    })));
  }

  function renderQuery(pane) {
    var bar = el('div', 'syn-row');
    add(bar, btn('Ask something else', 'quiet', function () { S.query = ''; S.queryData = null; S.queries = null; stopPlay(); renderTab(); }));
    pane.appendChild(bar);
    var q = S.queryData;
    if (!q) { pane.appendChild(el('p', 'syn-loading', 'Reading the question...')); return; }
    var head = el('div', 'syn-qhead');
    add(head, el('h5', null, q.question), el('p', 'syn-note', ['asked as ' + (q.asker_name || nameOf(q.asker)), q.mode, 'by ' + q.by, q.status,
      q.ms_pack != null ? 'pack in ' + msText(q.ms_pack) : '', q.ms_total != null ? 'answer in ' + msText(q.ms_total) : '', money(q.cost_usd)].filter(Boolean).join(' · ')));
    pane.appendChild(head);
    if (q.status === 'running') {
      pane.appendChild(el('p', 'syn-loading', 'Working: each step appears as it finishes.'));
      if (q.trace) pane.appendChild(traceView(q.trace));
      return;
    }
    if (q.status === 'failed') pane.appendChild(say('It failed: ' + ((q.answer || {}).error || ''), 'bad'));
    var walk = q.walk || {};
    var frames = walk.frames || [];
    if (frames.length) pane.appendChild(walkPlayer(q, frames));
    var cols = el('div', 'syn-qcols');
    var packBox = el('section', 'syn-card');
    var pack = q.pack || {};
    var ruleCount = (pack.items || []).filter(function (it) { return it.kind === 'rule'; }).length;
    packBox.appendChild(named(el('h6', null, 'The pack handed to the model: ' + plural((pack.items || []).length - ruleCount, 'item') +
      (ruleCount ? ' and ' + plural(ruleCount, 'rule') : '') + ', ' + (pack.tokens || 0) + ' tokens (D46)'),
      'The pack handed to the model: its items and tokens (D46)'));
    var used = {};
    ((q.answer || {}).cited_ids || []).forEach(function (id) { used[id] = 1; });
    (pack.items || []).concat(((pack.more || {}).items) || []).forEach(function (it) {
      var row = el('div', 'syn-packitem' + (used[it.id] ? ' used' : ''));
      var h = el('div', 'syn-row');
      add(h, el('span', 'syn-n', '[' + it.n + ']'), itemLink(it.id, it.title), el('span', 'syn-note', it.kind === 'rule' ? (it.route || 'a rule') : 'score ' + num(it.score, 4) + ' · ' + (it.route || it.group || '')),
        used[it.id] ? el('span', 'syn-badge good', 'used in the answer') : null);
      add(row, h, pre(it.lines));
      packBox.appendChild(row);
    });
    var ans = el('section', 'syn-card');
    ans.appendChild(el('h6', null, 'The answer'));
    var a = q.answer || {};
    ans.appendChild(answerView(a.text || '', a.used || [], a.not_in_pack));
    if ((a.rounds || []).length) ans.appendChild(table(['Checkpoint round', 'What the model did', 'Why'], a.rounds.map(function (r, i) { return [i + 1, r.action, r.why || '']; })));
    if (a.shadow) {
      ans.appendChild(el('h6', null, 'Checkpoint shadow (D72): logged, nothing acts on it'));
      ans.appendChild(kv({ 'p(enough)': num(a.shadow.p_enough, 3), backend: backendName(a.shadow.backend), 'the model did': a.shadow.main_model_did,
        'would have acted': a.shadow.would_act ? 'yes' : 'no', why: a.shadow.why || a.shadow.fallback }));
    }
    ans.appendChild(whyBox(q));
    add(cols, ans, packBox);
    pane.appendChild(cols);
    if (q.trace) {
      var det = el('details', 'syn-step');
      add(det, el('summary', null, 'Every step and call of this question (' + (q.trace.steps || []).length + ' steps)'), traceView(q.trace));
      pane.appendChild(det);
    }
  }

  function answerView(text, used, bad) {
    var box = el('div', 'syn-answer');
    var byN = {};
    (used || []).forEach(function (u) { byN[u.n] = u; });
    var p = el('p');
    String(text || '(no answer)').split(/(\[\d+\])/).forEach(function (part) {
      var m = /^\[(\d+)\]$/.exec(part);
      if (m && byN[m[1]]) {
        var c = itemLink(byN[m[1]].id, part);
        c.className = 'syn-cite';
        c.title = byN[m[1]].title;
        p.appendChild(c);
      } else p.appendChild(document.createTextNode(part));
    });
    box.appendChild(p);
    if ((used || []).length) {
      var u = el('p', 'syn-note', 'Used: ');
      used.forEach(function (x) { add(u, itemLink(x.id, '[' + x.n + '] ' + x.title), ' '); });
      box.appendChild(u);
    }
    if ((bad || []).length) box.appendChild(say('Cited numbers that were not in the pack, refused by code: ' + bad.join(', '), 'bad'));
    return box;
  }

  function whyBox(q) {
    var box = el('div', 'syn-why');
    box.appendChild(el('h6', null, 'Why was an item found, or not?'));
    var sel = el('select', 'syn-in'); sel.setAttribute('aria-label', 'Item to explain');
    var out = el('div');
    function fill() {
      (S.items || []).forEach(function (i) { var o = el('option', null, i.title + ' (' + i.kind + ')'); o.value = i.id; sel.appendChild(o); });
    }
    if (S.items) fill(); else loadItems().then(fill);
    var go = btn('Explain', '', function () {
      api(dsPath('/why'), { body: { query: q.id, item: sel.value } }).then(function (j) {
        out.replaceChildren(kv({ item: j.item, 'in the pack': j.in_pack ? 'yes, as [' + j.n + ']' : 'no', route: j.route, cited: j.cited == null ? '' : (j.cited ? 'yes' : 'no'),
          reason: j.reason }));
        if ((j.seen || []).length) out.appendChild(table(['Walk step', 'As', 'Score', 'Kept', 'Why not'], j.seen.map(function (s) {
          return [s.frame, s.as, num(s.score, 5), s.kept == null ? '' : (s.kept ? 'yes' : 'no'), s.why || ''];
        })));
      });
    });
    add(box, add(el('div', 'syn-row'), sel, go), out);
    return box;
  }

  /* The walk, played one expansion at a time over a graph of every item it touched. */

  function stopPlay() { if (S.playing) clearInterval(S.playing); S.playing = null; }

  function walkPlayer(q, frames) {
    var box = el('section', 'syn-card syn-walk');
    var walk = q.walk || {};
    box.appendChild(named(el('h6', null, 'The walk: ' + plural(frames.length - 1, 'step') + ', stopped because ' + (walk.stop || '')),
      'The walk: its steps, and why it stopped'));
    var model = walkModel(frames, walk.titles || {});
    var controls = el('div', 'syn-row syn-walk-controls');
    var counter = el('span', 'syn-note');
    var first = btn('Start again', 'quiet', function () { stopPlay(); S.frame = 0; paint(); });
    var prev = btn('Back', 'quiet', function () { stopPlay(); S.frame = Math.max(0, S.frame - 1); paint(); });
    var next = btn('Next step', 'primary', function () { stopPlay(); S.frame = Math.min(frames.length - 1, S.frame + 1); paint(); });
    var play = btn('Play', '', function () {
      if (S.playing) { stopPlay(); play.textContent = 'Play'; return; }
      if (S.frame >= frames.length - 1) S.frame = 0;
      play.textContent = 'Pause';
      S.playing = setInterval(function () {
        if (S.frame >= frames.length - 1) { stopPlay(); play.textContent = 'Play'; paint(); return; }
        S.frame++; paint();
      }, S.speed);
    });
    var end = btn('Run to the end', 'quiet', function () { stopPlay(); play.textContent = 'Play'; S.frame = frames.length - 1; paint(); });
    var speed = el('select', 'syn-in small'); speed.setAttribute('aria-label', 'Speed');
    [[1500, 'slow'], [900, 'normal'], [350, 'fast']].forEach(function (s) { var o = el('option', null, s[1]); o.value = s[0]; if (s[0] === S.speed) o.selected = true; speed.appendChild(o); });
    speed.addEventListener('change', function () { S.speed = Number(speed.value); if (S.playing) { stopPlay(); play.click(); } });
    add(controls, first, prev, next, play, end, speed, counter);
    box.appendChild(controls);
    var budget = el('div', 'syn-budget');
    var budgetFill = el('span', 'syn-budget-fill');
    var budgetText = el('span', 'syn-budget-text');
    add(budget, budgetFill, budgetText);
    box.appendChild(budget);
    var split = el('div', 'syn-walk-split');
    var graphBox = el('div', 'syn-walk-graph');
    var svg = svgEl('svg', { viewBox: '0 0 ' + model.w + ' ' + model.h, role: 'img', 'aria-label': 'The items the walk touched, and the links it followed' });
    graphBox.appendChild(svg);
    var legend = el('div', 'syn-legend');
    [['seed', 'a search seed'], ['current', 'being opened now'], ['gathered', 'gathered into the pack'], ['queued', 'in the queue'], ['dropped', 'looked at, not queued']].forEach(function (l) {
      add(legend, add(el('span', 'syn-leg'), el('i', 'lg-' + l[0]), l[1]));
    });
    graphBox.appendChild(legend);
    var panel = el('div', 'syn-walk-panel');
    add(split, graphBox, panel);
    box.appendChild(split);

    function paint() {
      var k = S.frame;
      var fr = frames[k];
      counter.textContent = 'Step ' + k + ' of ' + (frames.length - 1);
      next.disabled = k >= frames.length - 1;
      end.disabled = k >= frames.length - 1;
      prev.disabled = k === 0;
      var state = model.stateAt(k);
      var tokens = fr.tokens || 0, b = fr.budget || walk.budget || 1;
      budgetFill.style.width = Math.min(100, Math.round(tokens / b * 100)) + '%';
      budgetText.textContent = 'Budget: ' + tokens + ' of ' + b + ' tokens' + (fr.gathered != null ? ' · ' + fr.gathered + ' gathered' : '') +
        (fr.expansions != null ? ' · ' + fr.expansions + ' expansions' : '') + (fr.db_ms != null ? ' · ' + fr.db_ms + ' ms in the database' : '');
      drawWalkGraph(svg, model, state);
      keepScroll(function () { panel.replaceChildren(framePanel(fr)); });
    }
    paint();
    return box;
  }

  function walkModel(frames, titles) {
    var nodes = {}, edges = {}, order = [];
    function node(id, title) {
      if (!nodes[id]) { nodes[id] = { id: id, title: title || titles[id] || short(id) }; order.push(id); }
      return nodes[id];
    }
    frames.forEach(function (fr) {
      (fr.seeds || []).forEach(function (s) { node(s.id, s.title).seed = true; node(s.id).kind = s.kind; });
      (fr.opened || []).forEach(function (o) { node(o.id, o.title); });
      (fr.neighbours || []).forEach(function (n) {
        node(n.id, n.title);
        var key = n.parent + '>' + n.id;
        if (!edges[key]) edges[key] = { a: n.parent, b: n.id, type: n.link && n.link.type, strength: n.link && n.link.strength };
      });
      (fr.queue || []).forEach(function (q) { node(q.id, q.title); });
    });
    var list = order.map(function (id) { return nodes[id]; });
    var edgeList = Object.keys(edges).map(function (k) { return edges[k]; });
    var w = 900, h = 520;
    layout(list, edgeList, w, h, 'walk');
    function stateAt(k) {
      var gathered = {}, queued = {}, dropped = {}, current = {}, edgeOn = {}, kept = {};
      for (var i = 0; i <= k; i++) {
        var fr = frames[i];
        (fr.opened || []).forEach(function (o) { gathered[o.id] = 1; });
        (fr.neighbours || []).forEach(function (n) {
          if (n.kept) kept[n.id] = 1; else dropped[n.id] = 1;
          edgeOn[n.parent + '>' + n.id] = n.kept ? 'kept' : (edgeOn[n.parent + '>' + n.id] || 'seen');
        });
      }
      var fk = frames[k];
      // Everything queued and not yet taken out, not only the top of the queue
      // the frame lists.
      Object.keys(kept).forEach(function (id) { if (!gathered[id]) queued[id] = 1; });
      Object.keys(kept).forEach(function (id) { delete dropped[id]; });
      ((frames[0] || {}).seeds || []).forEach(function (sd) { if (!gathered[sd.id]) queued[sd.id] = 1; });
      (fk.queue || []).forEach(function (q) { queued[q.id] = 1; });
      (fk.opened || []).forEach(function (o) { current[o.id] = 1; });
      if (fk.kind === 'seeds') (fk.seeds || []).forEach(function (s) { queued[s.id] = 1; });
      return { gathered: gathered, queued: queued, dropped: dropped, current: current, edgeOn: edgeOn, frame: fk };
    }
    return { nodes: list, edges: edgeList, w: w, h: h, stateAt: stateAt };
  }

  function svgEl(tag, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  /* A small force layout, seeded so the same graph lays out the same way each time. */
  function layout(nodes, edges, w, h, seed) {
    var rnd = (function (s) { var x = 0; for (var i = 0; i < s.length; i++) x = (x * 31 + s.charCodeAt(i)) >>> 0; return function () { x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296; }; })(seed + nodes.length);
    var byId = {};
    nodes.forEach(function (n, i) {
      var a = i / Math.max(1, nodes.length) * Math.PI * 2;
      n.x = w / 2 + Math.cos(a) * w * 0.3 + (rnd() - 0.5) * 40;
      n.y = h / 2 + Math.sin(a) * h * 0.3 + (rnd() - 0.5) * 40;
      byId[n.id] = n;
    });
    var k = Math.sqrt(w * h / Math.max(1, nodes.length)) * (nodes.length > 40 ? 1.1 : 0.8);
    var iters = nodes.length > 300 ? 120 : 220;
    for (var it = 0; it < iters; it++) {
      var t = (1 - it / iters) * k * 0.6;
      nodes.forEach(function (n) { n.dx = 0; n.dy = 0; });
      for (var i = 0; i < nodes.length; i++) {
        for (var j = i + 1; j < nodes.length; j++) {
          var a = nodes[i], b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
          var f = k * k / d;
          a.dx += dx / d * f; a.dy += dy / d * f; b.dx -= dx / d * f; b.dy -= dy / d * f;
        }
      }
      edges.forEach(function (e) {
        var a = byId[e.a], b = byId[e.b];
        if (!a || !b) return;
        var dx = a.x - b.x, dy = a.y - b.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var f = d * d / k;
        a.dx -= dx / d * f; a.dy -= dy / d * f; b.dx += dx / d * f; b.dy += dy / d * f;
      });
      nodes.forEach(function (n) {
        n.dx += (w / 2 - n.x) * 0.006; n.dy += (h / 2 - n.y) * 0.006;
        var d = Math.sqrt(n.dx * n.dx + n.dy * n.dy) || 0.01;
        n.x += n.dx / d * Math.min(d, t); n.y += n.dy / d * Math.min(d, t);
        n.x = Math.max(30, Math.min(w - 30, n.x)); n.y = Math.max(24, Math.min(h - 24, n.y));
      });
    }
    return byId;
  }

  function drawWalkGraph(svg, model, st) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var byId = {};
    model.nodes.forEach(function (n) { byId[n.id] = n; });
    model.edges.forEach(function (e) {
      var a = byId[e.a], b = byId[e.b];
      if (!a || !b) return;
      var on = st.edgeOn[e.a + '>' + e.b];
      if (!on) return;
      var line = svgEl('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, 'class': 'syn-wedge ' + on });
      line.setAttribute('stroke', TYPE_COLOUR[e.type] || '#8d9aac');
      line.setAttribute('stroke-width', on === 'kept' ? 1 + 2.5 * Number(e.strength || 0.5) : 1);
      svg.appendChild(line);
    });
    model.nodes.forEach(function (n) {
      var cls = st.current[n.id] ? 'current' : st.gathered[n.id] ? 'gathered' : st.queued[n.id] ? 'queued' : st.dropped[n.id] ? 'dropped' : 'unseen';
      if (cls === 'unseen') return;
      var g = svgEl('g', { 'class': 'syn-wnode ' + cls + (n.seed ? ' seed' : ''), transform: 'translate(' + n.x + ',' + n.y + ')' });
      var c = svgEl('circle', { r: st.current[n.id] ? 13 : 9 });
      g.appendChild(c);
      var tt = svgEl('title'); tt.textContent = n.title; g.appendChild(tt);
      if (cls !== 'dropped') {
        var label = svgEl('text', { x: 14, y: 5 });
        label.textContent = n.title.length > 28 ? n.title.slice(0, 27) + '...' : n.title;
        g.appendChild(label);
      }
      g.addEventListener('click', function () { openItem(n.id); });
      svg.appendChild(g);
    });
  }

  function scoreLine(x) {
    return 'R ' + num(x.R, 3) + ' × P ' + num(x.P, 3) + ' × H ' + num(x.H, 3) + ' × path ' + num(x.pi, 4) + ' = ' + num(x.score, 5);
  }

  function framePanel(fr) {
    var box = el('div');
    if (fr.kind === 'seeds') {
      box.appendChild(el('p', 'syn-note', fr.note || ''));
      box.appendChild(table(['Seed', 'Score = R × P × H', 'Prior', 'Ranks', 'Boosted'], (fr.seeds || []).map(function (s) {
        return [itemLink(s.id, s.title), num(s.R, 3) + ' × ' + num(s.P, 3) + ' × ' + num(s.H, 3) + ' = ' + num(s.score, 4),
          s.prior ? 'tier ' + s.prior.tier + ' (' + s.prior.tier_prior + ') × recency ' + s.prior.recency + ' × ' + s.prior.superseded : '',
          ranksText(s.ranks) || s.why, s.boosted ? 'context × boost' : ''];
      }), 'small'));
      return box;
    }
    if (fr.kind === 'stop') {
      box.appendChild(say('Stopped: ' + fr.stop, 'note'));
      box.appendChild(kv({ gathered: fr.gathered, expansions: fr.expansions, tokens: fr.tokens + ' of ' + fr.budget, 'database time': fr.db_ms + ' ms' }));
      if ((fr.branches_stopped || []).length) box.appendChild(table(['Branch that stopped', 'Why'], fr.branches_stopped.map(function (b) { return [b.branch, b.why]; })));
      return box;
    }
    (fr.opened || []).forEach(function (o) {
      var c = el('div', 'syn-opened');
      add(c, el('p', null, 'Opened: '), itemLink(o.id, o.title), el('p', 'syn-score', scoreLine(o)),
        el('p', 'syn-note', (o.path || []).length ? 'Reached by: ' + o.path.map(function (p) { return p.type + ' (' + p.dir + ', strength ' + p.strength + ', T ' + p.T + ', d ' + p.d + ')'; }).join(' then ') : 'A seed from search.'),
        el('p', 'syn-note', (o.links || 0) + ' links, ' + (o.tokens || 0) + ' tokens to the pack' + (o.H < 1 ? '; a hub, marked down to H ' + num(o.H, 3) + ' (' + o.degree + ' links)' : '')));
      box.appendChild(c);
    });
    if (fr.decision) {
      box.appendChild(el('h6', null, 'Frontier scored by a decision model in one batch (D71)'));
      box.appendChild(decisionView(fr.decision));
    }
    if (fr.branch_stopped) box.appendChild(say('Branch through ' + fr.branch_stopped.branch + ' stopped: ' + fr.branch_stopped.why, 'note'));
    var ns = fr.neighbours || [];
    box.appendChild(el('h6', null, 'Its neighbours (' + ns.length + '), each score taken apart'));
    box.appendChild(table(['Neighbour', 'Link', 'R', 'P', 'H', 'strength × T × d', 'Path', 'Score', 'Kept'], ns.map(function (n) {
      var l = n.link || {};
      return [itemLink(n.id, n.title), (l.type || '') + ' ' + (l.dir || ''), num(n.R, 3) + (n.cos != null ? ' (cos ' + num(n.cos, 3) + ')' : '') + (n.p_yes != null ? ' (p ' + num(n.p_yes, 2) + ')' : ''),
        num(n.P, 3), num(n.H, 3), num(l.strength, 2) + ' × ' + l.T + ' × ' + l.d, num(n.pi, 4), num(n.score, 5),
        n.kept ? 'queued' : n.why];
    }), 'small'));
    if ((fr.queue || []).length) {
      box.appendChild(el('h6', null, 'The queue after this step, best first'));
      box.appendChild(table(['Item', 'Score'], fr.queue.map(function (q) { return [itemLink(q.id, q.title), num(q.score, 5)]; }), 'small'));
    }
    return box;
  }

  /* --- Explore -------------------------------------------------------------------- */

  function renderExplore(pane) {
    var seg = el('div', 'syn-seg');
    [['graph', 'Graph'], ['map', 'The tiny map'], ['search', 'Search'], ['layers', 'Layers and topics']].forEach(function (m) {
      var b = el('button', 'syn-segb' + (S.explore === m[0] ? ' on' : ''), m[1]);
      b.type = 'button';
      b.addEventListener('click', function () { S.explore = m[0]; renderTab(); });
      seg.appendChild(b);
    });
    pane.appendChild(seg);
    if (S.explore === 'graph') exploreGraph(pane);
    else if (S.explore === 'map') exploreMap(pane);
    else if (S.explore === 'search') exploreSearch(pane);
    else exploreLayers(pane);
  }

  function exploreGraph(pane) {
    if (!S.graph) {
      pane.appendChild(el('p', 'syn-loading', 'Laying out the graph...'));
      api(dsPath('/graph')).then(function (j) { S.graph = j; S.graph.laid = null; if (S.tab === 'explore') renderTab(); });
      return;
    }
    var g = S.graph;
    var types = {};
    g.links.forEach(function (l) { types[l.type] = (types[l.type] || 0) + 1; });
    var filters = el('div', 'syn-row syn-filters');
    Object.keys(types).sort().forEach(function (t) {
      var lab = el('label', 'syn-check');
      var cb = el('input'); cb.type = 'checkbox'; cb.checked = S.graphFilter.types[t] !== false;
      cb.addEventListener('change', function () { S.graphFilter.types[t] = cb.checked; renderTab(); });
      var chip = typeChip(t + ' ' + types[t]);
      add(lab, cb, chip);
      filters.appendChild(lab);
    });
    var minLab = el('label', 'syn-check');
    var min = el('input'); min.type = 'range'; min.min = 0; min.max = 1; min.step = 0.05; min.value = S.graphFilter.min;
    min.setAttribute('aria-label', 'Hide links weaker than');
    min.addEventListener('change', function () { S.graphFilter.min = Number(min.value); renderTab(); });
    add(minLab, ' Strength from ' + num(S.graphFilter.min, 2) + ' ', min);
    filters.appendChild(minLab);
    filters.appendChild(btn('Read it again', 'quiet', function () { S.graph = null; renderTab(); }));
    pane.appendChild(filters);
    var links = g.links.filter(function (l) { return S.graphFilter.types[l.type] !== false && Number(l.strength) >= S.graphFilter.min; });
    var w = 1000, h = 680;
    if (!g.laid) g.laid = layout(g.nodes, g.links.map(function (l) { return { a: l.src, b: l.dst }; }), w, h, 'explore');
    var box = el('div', 'syn-graph-box');
    var svg = svgEl('svg', { viewBox: '0 0 ' + w + ' ' + h, role: 'img', 'aria-label': 'Every item in the dataset and its links' });
    links.forEach(function (l) {
      var a = g.laid[l.src], b = g.laid[l.dst];
      if (!a || !b) return;
      var line = svgEl('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, 'class': 'syn-gedge' });
      line.setAttribute('stroke', TYPE_COLOUR[l.type] || '#8d9aac');
      line.setAttribute('stroke-width', 0.4 + 2.2 * Number(l.strength));
      line.setAttribute('stroke-opacity', 0.25 + 0.6 * Number(l.strength));
      var tt = svgEl('title'); tt.textContent = l.type + ' ' + num(l.strength, 2) + ' (' + l.origin + ')'; line.appendChild(tt);
      svg.appendChild(line);
    });
    g.nodes.forEach(function (n) {
      var p = g.laid[n.id];
      var r = 3 + Math.min(14, Math.sqrt(Number(n.degree) || 0) * 1.6);
      var gg = svgEl('g', { 'class': 'syn-gnode', transform: 'translate(' + p.x + ',' + p.y + ')' });
      var c = svgEl('circle', { r: r });
      c.setAttribute('fill', KIND_COLOUR[n.kind] || '#8d9aac');
      if (n.kind === 'layer') c.setAttribute('stroke', '#ffd166');
      gg.appendChild(c);
      var tt = svgEl('title'); tt.textContent = n.title + ' (' + (n.layer ? n.layer + ' layer' : n.kind) + ', ' + n.degree + ' links)'; gg.appendChild(tt);
      if (Number(n.degree) >= 14 || n.kind === 'layer' || n.kind === 'topic' || n.kind === 'person' || n.kind === 'task') {
        var t = svgEl('text', { x: r + 3, y: 4 });
        t.textContent = n.title.length > 22 ? n.title.slice(0, 21) + '...' : n.title;
        gg.appendChild(t);
      }
      gg.addEventListener('click', function () { openItem(n.id); });
      svg.appendChild(gg);
    });
    box.appendChild(svg);
    pane.appendChild(box);
    var legend = el('div', 'syn-legend');
    Object.keys(KIND_COLOUR).forEach(function (k) {
      if (!g.nodes.some(function (n) { return n.kind === k; })) return;
      var i = el('i'); i.style.background = KIND_COLOUR[k];
      add(legend, add(el('span', 'syn-leg'), i, k));
    });
    pane.appendChild(legend);
    pane.appendChild(el('p', 'syn-note', g.nodes.length + ' items, ' + links.length + ' of ' + g.links.length + ' links shown. A circle\'s size is how many links it has; a line\'s width is its strength. Press an item to open it.'));
  }

  function exploreMap(pane) {
    var viewer = S.mapViewer || (S.data && S.data.me) || '';
    if (!S.mapData || S.mapData.viewer !== viewer) {
      pane.appendChild(el('p', 'syn-loading', 'Reading the map...'));
      api(dsPath('/map?viewer=' + encodeURIComponent(viewer))).then(function (j) { S.mapData = j; if (S.tab === 'explore') renderTab(); });
      return;
    }
    var m = S.mapData;
    var row = el('div', 'syn-row');
    var sel = el('select', 'syn-in'); sel.setAttribute('aria-label', 'Whose map');
    (m.people || []).forEach(function (p) { var o = el('option', null, p.name + '\'s map'); o.value = p.key; if (p.key === m.viewer) o.selected = true; sel.appendChild(o); });
    sel.addEventListener('change', function () { S.mapViewer = sel.value; S.mapData = null; renderTab(); });
    add(row, sel, btn('Rebuild now', '', function () {
      api(dsPath('/map/rebuild'), { body: { viewer: m.viewer } }).then(function () { flash('Rebuilding the map; it shows in Activity.'); setTimeout(function () { S.mapData = null; if (S.tab === 'explore') renderTab(); }, 6000); });
    }));
    pane.appendChild(row);
    pane.appendChild(el('p', 'syn-note', 'One short text that loads into every turn: the areas, what is active now, and the owner\'s own words (D14). It is built per person from only what they may see (D18), about 600 words and never over 1,200 tokens (D15).'));
    var split = el('div', 'syn-map-split');
    var mapBox = el('div');
    if (m.current) {
      mapBox.appendChild(el('p', 'syn-note', 'Version ' + m.current.version + ', ' + m.current.tokens + ' tokens, ' + when(m.current.made_at) + ', ' + (m.current.why || '')));
      mapBox.appendChild(pre(m.current.text));
    } else mapBox.appendChild(el('p', 'syn-note', 'No map yet for ' + (m.viewer_name || nameOf(m.viewer)) + '. It is made after the first items are stored, or press Rebuild now.'));
    add(split, mapBox, mapAreas(m));
    pane.appendChild(split);
    var pin = el('div', 'syn-form');
    var term = el('input', 'syn-in'); term.placeholder = '"Module A" = the onboarding flow for Lumen'; term.setAttribute('aria-label', 'A line for the owner\'s words');
    add(pin, el('h6', null, 'Pin a line of the owner\'s words (never dropped by code, D16)'), term, btn('Pin it', '', function () {
      if (!term.value.trim()) return;
      api(dsPath('/map/pin'), { body: { section: 'words', key: term.value.split('=')[0].trim().slice(0, 40), text: term.value } }).then(function () { flash('Pinned; rebuild the map to see it.'); S.mapData = null; renderTab(); });
    }));
    pane.appendChild(pin);
    if ((m.lines || []).length) pane.appendChild(table(['Section', 'Key', 'Line', 'Pinned', 'By', ''], m.lines.map(function (l) {
      return [l.section, l.key, l.text.split('|')[0], l.pinned ? 'yes' : '', l.by, l.pinned ? btn('Unpin', 'quiet tiny', function () {
        api(dsPath('/map/unpin'), { body: { section: l.section, key: l.key } }).then(function () { S.mapData = null; renderTab(); });
      }) : ''];
    }), 'small'));
    if ((m.history || []).length > 1) {
      var det = el('details', 'syn-step');
      det.appendChild(el('summary', null, 'Earlier versions (' + (m.history.length - 1) + ')'));
      m.history.slice(1).forEach(function (v) { add(det, el('p', 'syn-note', 'Version ' + v.version + ', ' + when(v.made_at) + ', ' + v.tokens + ' tokens'), pre(v.text)); });
      pane.appendChild(det);
    }
  }

  // The areas beside the map: each real one with who set it, and the new ones the model proposed
  // that wait for enough items (D16).
  function mapAreas(m) {
    var box = el('section', 'syn-card syn-map-areas');
    box.appendChild(el('h6', null, 'Areas'));
    box.appendChild(table(['Area', 'Items', 'Set by the owner', 'Set by the model'], (m.areas || []).map(function (a) {
      return [a.area, a.items, a.area === 'General' ? '' : a.by_owner, a.area === 'General' ? '' : a.by_model];
    }), 'small'));
    box.appendChild(el('h6', null, 'Proposed areas, waiting'));
    var bar = m.area_min_items || 3;
    if ((m.proposed || []).length) {
      box.appendChild(table(['Proposed area', 'Items proposing it'], m.proposed.map(function (p) {
        return [p.name, p.items + ' of ' + bar];
      }), 'small'));
    } else box.appendChild(el('p', 'syn-note', 'None waiting.'));
    box.appendChild(el('p', 'syn-note', 'When no area comes with an item, the model suggests one in its X-ray call. A new name stays a proposal, with the item under General, until ' +
      bar + ' items propose it; then it becomes an area and they move into it. An area the owner set is never changed by the model.'));
    return box;
  }

  function exploreSearch(pane) {
    var row = el('div', 'syn-row');
    var q = el('input', 'syn-in'); q.placeholder = 'Search by words and by meaning'; q.setAttribute('aria-label', 'Search');
    if (S.search) q.value = S.search.q;
    var asker = el('select', 'syn-in'); asker.setAttribute('aria-label', 'Search as');
    (S.data.people || []).forEach(function (p) { var o = el('option', null, 'as ' + p.name); o.value = p.key; asker.appendChild(o); });
    if (S.search) asker.value = S.search.asker;
    var go = btn('Search', 'primary', function () {
      if (!q.value.trim()) return;
      api(dsPath('/search?q=' + encodeURIComponent(q.value) + '&asker=' + encodeURIComponent(asker.value))).then(function (j) {
        S.search = { q: q.value, asker: asker.value, result: j }; renderTab();
      }).catch(function (e) { flash(e.message, 'bad'); });
    });
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') go.click(); });
    add(row, q, asker, go);
    pane.appendChild(row);
    pane.appendChild(el('p', 'syn-note', 'One database round trip with two lists, words (English and Bulgarian word forms, the other alphabet, letter groups) and meaning (nearest vectors), fused by rank with k = 60 (D36), readers checked inside the query (D38). Rules are never searched (D59).'));
    if (!S.search) return;
    var r = S.search.result;
    pane.appendChild(kv({ 'words searched': r.query_words, 'words list': r.words,
      'meaning list': r.meaning_on ? r.meaning + ' (' + r.meaning_model + ')' : 'off: ' + (r.meaning_off_why || 'no embedding'),
      'database time': msText(r.ms) }));
    pane.appendChild(table(['Item', 'Kind', 'Fused', 'Words rank', 'Meaning rank', 'Words score', 'Cosine'], (r.items || []).map(function (i) {
      return [itemLink(i.item_id, i.title), i.kind, num(i.rrf, 4), i.ranks.words || '', i.ranks.meaning || '', i.scores.words || '', i.scores.meaning || ''];
    })));
  }

  function exploreLayers(pane) {
    pane.appendChild(add(el('div', 'syn-row'), el('p', 'syn-note', 'Layers are X-rays of many items: a thread at 4 items, a person and topic at 10, a profile at 30 (D53), updated by diff (D54). Topics are items too (D34).'),
      btn('Merge close topics now (D34)', 'quiet', function () {
        api(dsPath('/topics/merge'), { body: {} }).then(function (j) { flash(j.merged.length ? 'Merged ' + j.merged.length + ' topics.' : 'No topics were close enough to merge.'); });
      })));
    api(dsPath('/items?kind=layer')).then(function (j) {
      pane.appendChild(el('h6', null, 'Layers (' + j.items.length + ')'));
      pane.appendChild(table(['Layer', 'Kind', 'Claims', 'Built from (links)', 'Readers', 'Updated'], j.items.map(function (i) {
        return [itemLink(i.id, i.title), i.layer, i.claims, i.links, (i.reader_names || []).join(', '), day(i.said_at)];
      })));
      return api(dsPath('/items?kind=topic'));
    }).then(function (j) {
      pane.appendChild(el('h6', null, 'Topics (' + j.items.length + ')'));
      pane.appendChild(table(['Topic', 'Links', 'Readers'], j.items.map(function (i) { return [itemLink(i.id, i.title), i.links, (i.reader_names || []).join(', ')]; })));
      return api(dsPath('/items?kind=person'));
    }).then(function (j) {
      pane.appendChild(el('h6', null, 'People (' + (j.total || j.items.length) + ')'));
      pane.appendChild(table(['Person', 'Origin', 'Value', 'Links'], j.items.map(function (i) {
        return [itemLink(i.id, i.title), originChip(i.origin), i.value == null ? '' : num(i.value, 2), i.links];
      })));
    }).catch(function (e) { flash(e.message, 'bad'); });
  }

  /* --- Tune ------------------------------------------------------------------------ */

  function renderTune(pane) {
    var d = S.data;
    var draft = S.tuneDraft;
    pane.appendChild(el('p', 'syn-note', 'Every number this dataset works by. Change any, then either save them for this dataset, or keep them unsaved and compare one question with and without them, side by side.'));
    var bar = el('div', 'syn-row');
    add(bar, btn('Save for this dataset', 'primary', function () {
      if (!Object.keys(draft).length) { flash('Nothing changed yet.'); return; }
      api(dsPath('/settings'), { body: { changes: draft } }).then(function (j) {
        if (j.problems && j.problems.length) flash(j.problems.join('; '), 'bad'); else flash('Saved.');
        S.tuneDraft = {}; loadDataset();
      });
    }), btn('Forget unsaved changes', 'quiet', function () { S.tuneDraft = {}; renderTab(); }),
      el('span', 'syn-note', Object.keys(draft).length ? Object.keys(draft).length + ' unsaved' : ''));
    pane.appendChild(bar);
    var vc = el('section', 'syn-card syn-vectors');
    vc.id = 'synVectors';
    vc.setAttribute('aria-label', 'Vectors');
    drawVectors(vc);
    pane.appendChild(vc);
    var cmp = el('section', 'syn-card');
    cmp.appendChild(el('h6', null, 'Compare: the same question as saved (A) and with the unsaved changes (B)'));
    cmp.appendChild(askForm(function (body, done) {
      var over = {};
      Object.keys(draft).forEach(function (k) { if (draft[k] !== null) over[k] = draft[k]; });
      var a = api(dsPath('/query'), { body: Object.assign({}, body, { label: 'A: as saved' }) });
      var b = api(dsPath('/query'), { body: Object.assign({}, body, { label: 'B: with changes', override: over }) });
      Promise.all([a, b]).then(function (r) {
        done();
        S.compare = { a: r[0].query, b: r[1].query, over: over, A: null, B: null };
        pollCompare();
      }).catch(function (e) { done(); flash(e.message, 'bad'); });
    }, 'Run both'));
    var res = el('div', 'syn-compare');
    res.id = 'synCompare';
    cmp.appendChild(res);
    pane.appendChild(cmp);
    pane.appendChild(settingsTable(d.settings || [], draft));
    renderCompare();
  }

  /* The model this dataset's vectors are, and moving them to another (vectors.py). */
  var MOVE_SAYS = {
    moving: 'Moving', switched: 'Moved', failed: 'Stopped', put_back: 'Put back'
  };
  function drawVectors(card) {
    var v = (S.data && S.data.vectors) || {};
    var c = v.counts || {};
    var m = v.move || {};
    var target = 'voyage-4';
    var keys = v.keys || {};
    card.replaceChildren();
    card.appendChild(el('h6', null, 'Vectors'));
    card.appendChild(el('p', 'syn-note', 'Search by meaning reads ' + plural(c.on_model || 0, v.model + ' vector') +
      ' of ' + plural(c.passages || 0, 'passage') + '. A dataset\'s vectors are all one model\'s, and a question is ' +
      'embedded with that model, because two models\' numbers mean nothing to each other.' +
      (c.strays ? ' ' + plural(c.strays, 'passage') + ' still hold another model\'s vector and are found by words until swept.' : '')));
    if (!keys[v.model]) card.appendChild(say('This machine has no key for ' + v.model + ', so questions here are answered by words alone.', 'warn'));
    var facts = {};
    if (m.state) {
      facts['move'] = (MOVE_SAYS[m.state] || m.state) + ': ' + m.from + ' to ' + m.to;
      if (m.state === 'moving') facts['made so far'] = (c.staged || 0) + ' of ' + (c.vectors || 0) + ' passages, beside the old vectors';
      if (m.started_at) facts['started'] = when(m.started_at);
      if (m.switched_at) facts['switched'] = when(m.switched_at) + ', ' + plural(m.switched || 0, 'passage');
      if (m.put_back_at) facts['put back'] = when(m.put_back_at);
      var ck = m.verification;
      if (ck) facts['checked'] = (ck.ok ? 'passed' : 'failed') + ': ' + ck.live + ' passages, ' + ck.missing + ' missing, ' +
        ck.wrong_dims + ' of the wrong size, ' + ck.empty + ' empty; ' + ck.found_themselves + ' of ' + ck.sample +
        ' sampled passages found themselves in the top ' + ck.top;
      if (m.error) facts[m.state === 'moving' ? 'waiting on' : 'why'] = m.error;
      if (c.kept) facts['old vectors kept'] = plural(c.kept, 'passage');
    }
    card.appendChild(kv(facts));
    var row = el('div', 'syn-row');
    if (v.model !== target && m.state !== 'moving') {
      var go = btn(m.state === 'failed' && m.to === target ? 'Carry on moving to ' + target : 'Move to ' + target, 'primary', function () {
        go.disabled = true;
        api(dsPath('/vectors/move'), { body: { to: target } }).then(function () {
          flash('Moving to ' + target + ': search stays on ' + v.model + ' until every vector is made and checked.');
          refreshCounts();
        }).catch(function (e) { go.disabled = false; flash(e.message, 'bad'); });
      }, keys[target] ? '' : 'This machine has no key for ' + target);
      if (!keys[target]) go.disabled = true;
      row.appendChild(go);
    }
    if (m.state === 'moving' || m.state === 'switched') {
      row.appendChild(btn(m.state === 'moving' ? 'Stop the move' : 'Put back ' + m.from, 'quiet', function (ev) {
        ev.target.disabled = true;
        api(dsPath('/vectors/put_back'), { body: {} }).then(function () {
          flash(m.state === 'moving' ? 'Stopped: search never left ' + m.from + '.' : 'Search is on ' + m.from + ' again.');
          refreshCounts();
        }).catch(function (e) { ev.target.disabled = false; flash(e.message, 'bad'); });
      }));
    }
    if (row.childNodes.length) card.appendChild(row);
  }

  function pollCompare() {
    var c = S.compare;
    if (!c) return;
    Promise.all([api(dsPath('/query/' + c.a)), api(dsPath('/query/' + c.b))]).then(function (r) {
      c.A = r[0]; c.B = r[1];
      renderCompare();
      if ((c.A.status === 'running' || c.B.status === 'running') && S.compare === c) setTimeout(pollCompare, 1200);
    });
  }

  function renderCompare() {
    keepScroll(drawCompare);
  }

  function drawCompare() {
    var box = $('synCompare');
    var c = S.compare;
    if (!box || !c) return;
    box.replaceChildren();
    if (!c.A || !c.B) { box.appendChild(el('p', 'syn-loading', 'Running both...')); return; }
    box.appendChild(kv({ 'B changes': JSON.stringify(c.over) }));
    var ids = function (q) { return ((q.pack || {}).items || []).map(function (i) { return i.id; }); };
    var a = ids(c.A), b = ids(c.B);
    var both = a.filter(function (x) { return b.indexOf(x) >= 0; });
    var cols = el('div', 'syn-qcols');
    [['A: as saved', c.A, a], ['B: with the changes', c.B, b]].forEach(function (s) {
      var q = s[1];
      var card = el('section', 'syn-card');
      card.appendChild(el('h6', null, s[0]));
      if (q.status === 'running') { card.appendChild(el('p', 'syn-loading', 'Still working...')); cols.appendChild(card); return; }
      var w = q.walk || {};
      card.appendChild(kv({ 'stopped because': w.stop, expansions: w.expansions, 'tokens used': (w.tokens || 0) + ' of ' + w.budget,
        'items in the pack': s[2].length, 'time to pack': msText(q.ms_pack), 'whole question': msText(q.ms_total), cost: money(q.cost_usd) }));
      card.appendChild(answerView((q.answer || {}).text || '', (q.answer || {}).used || [], (q.answer || {}).not_in_pack));
      var ul = el('ul', 'syn-list');
      ((q.pack || {}).items || []).forEach(function (i) {
        var li = el('li', both.indexOf(i.id) >= 0 ? '' : 'only');
        add(li, '[' + i.n + '] ', itemLink(i.id, i.title), ' ' + num(i.score, 4) + (both.indexOf(i.id) >= 0 ? '' : ' (only here)'));
        ul.appendChild(li);
      });
      card.appendChild(ul);
      card.appendChild(btn('Open this walk', 'quiet', function () { openQuery(q.id); setTab('retrieve'); }));
      cols.appendChild(card);
    });
    box.appendChild(el('p', 'syn-note', both.length + ' items in both packs, ' + (a.length - both.length) + ' only in A, ' + (b.length - both.length) + ' only in B.'));
    box.appendChild(cols);
  }

  /* --- Evaluate --------------------------------------------------------------------- */

  function loadEval() {
    return api(dsPath('/eval')).then(function (j) {
      S.evalData = j;
      if (!S.evalRun && j.runs.length) { S.evalRun = j.runs[0].id; loadEvalRun(S.evalRun); }
      if (S.tab === 'evaluate') renderTab();
    });
  }
  function loadEvalRun(id, quiet) {
    return api(dsPath('/eval/run/' + id)).then(function (j) {
      var changed = JSON.stringify(S.evalRunData) !== JSON.stringify(j);
      S.evalRunData = j;
      if (changed && S.tab === 'evaluate') renderTab();
    }).catch(function () {});
  }

  function renderEvaluate(pane) {
    if (!S.evalData) { pane.appendChild(el('p', 'syn-loading', 'Reading the evaluation set...')); loadEval(); return; }
    var e = S.evalData;
    pane.appendChild(el('p', 'syn-note', 'Questions with the items a right answer needs (gold) and the facts it must hold. A question marked "must not answer" passes only when nothing it names reaches the pack. Runs never teach the links (D57); the judge is never of the family that ranked or answered (D77).'));
    var run = el('section', 'syn-card');
    run.appendChild(el('h6', null, 'Run the set'));
    var checks = el('div', 'syn-row');
    var chosen = { without: true, 'with': true };
    e.presets.forEach(function (p) {
      var lab = el('label', 'syn-check');
      var cb = el('input'); cb.type = 'checkbox'; cb.checked = !!chosen[p.key];
      cb.addEventListener('change', function () { chosen[p.key] = cb.checked; });
      add(lab, cb, ' ' + p.label);
      if (p.note) lab.title = p.note;
      checks.appendChild(lab);
    });
    var go = btn('Run it', 'primary', function () {
      var presets = Object.keys(chosen).filter(function (k) { return chosen[k]; });
      go.disabled = true;
      api(dsPath('/eval/run'), { body: { presets: presets } }).then(function (j) {
        S.evalRun = j.run; S.evalRunData = null; flash('Running ' + j.configs.join(' vs ') + '.'); loadEval(); loadEvalRun(j.run);
      }).catch(function (er) { go.disabled = false; flash(er.message, 'bad'); });
    });
    add(run, el('p', 'syn-note', 'Two configurations side by side are the with-and-without comparison of D79: a decision model may be switched on only when it lifts recall by 3 points with nothing else worse.'), checks, go);
    pane.appendChild(run);
    if (e.runs.length) {
      var sel = el('select', 'syn-in'); sel.setAttribute('aria-label', 'Run');
      e.runs.forEach(function (r) { var o = el('option', null, when(r.started_at) + ': ' + r.label + ' (' + r.status + ')'); o.value = r.id; if (r.id === S.evalRun) o.selected = true; sel.appendChild(o); });
      sel.addEventListener('change', function () { S.evalRun = sel.value; S.evalRunData = null; loadEvalRun(sel.value); });
      pane.appendChild(add(el('div', 'syn-row'), el('span', 'syn-note', 'Run:'), sel));
    }
    if (S.evalRun && S.evalRunData) pane.appendChild(evalRunView(S.evalRunData, e.questions));
    if (e.people) pane.appendChild(peopleEvalCard(e.people));
    var qs = el('section', 'syn-card');
    qs.appendChild(el('h6', null, 'The questions (' + e.questions.length + ')'));
    qs.appendChild(table(['Group', 'Question', 'Asked as', 'About', 'Gold items', 'Key facts', ''], e.questions.map(function (q) {
      return [q.grp, q.question + (q.forbidden ? ' (must not answer)' : ''), q.asker_name || nameOf(q.asker), q.context_title || '', (q.gold_titles || []).join('; '),
        (q.facts || []).join('; '), btn('Remove', 'quiet tiny', function () {
          api(dsPath('/eval/question'), { body: { 'delete': q.id } }).then(function () { S.evalData = null; renderTab(); });
        })];
    }), 'small'));
    qs.appendChild(questionForm());
    pane.appendChild(qs);
  }

  // 'email:a@b.example' as the person would write it; a phone is kept by its last nine digits.
  function idText(keys) { return (keys || []).map(function (k) { return k.replace(/^(email|handle):/, '').replace(/^phone:/, 'phone ending '); }).join(', '); }

  // Gold people against what the X-ray stored: no model call, only a comparison (Q21's groundwork).
  function peopleEvalCard(pe) {
    var card = el('section', 'syn-card');
    var h = el('h6', null, 'People mentioned: extraction against gold people');
    h.dataset.explain = 'People mentioned: extraction against gold people, in Evaluate';
    card.appendChild(h);
    if (!pe.items) {
      card.appendChild(el('p', 'syn-note', 'No item here has gold people. Set them on an item\'s page, under People mentioned.'));
      return card;
    }
    function pct(v) { return v == null ? '' : (v * 100).toFixed(0) + '%'; }
    card.appendChild(el('p', 'syn-note', pe.read + ' of ' + pe.items + ' items with gold people have people read by their X-ray. ' +
      'A name is right when the first name matches, and the last name too when both have one (Cyrillic compared through its Latin letters). ' +
      'An identifier is right on the right person, or left unattributed when the gold leaves it so.'));
    card.appendChild(table(['Measure', 'Precision', 'Recall', 'Counts'], [
      [rowLabel('By name'), pct(pe.names.precision), pct(pe.names.recall), pe.names.matched + ' matched, ' + pe.names.found + ' found, ' + pe.names.gold + ' expected'],
      [rowLabel('By identifier'), pct(pe.identifiers.precision), pct(pe.identifiers.recall), pe.identifiers.right + ' right, ' + pe.identifiers.found + ' found, ' + pe.identifiers.gold + ' expected']], 'small'));
    card.appendChild(stackTable(['Item', 'Names', 'Missed', 'Extra', 'Identifiers', 'Missed', 'Wrong or extra'], pe.per_item.map(function (r) {
      var link = itemLink(r.item, r.title || '(untitled)');
      if (!r.read) return [link, 'not read yet', '', '', '', '', ''];
      return [link, r.names.matched + ' of ' + r.names.gold, r.names.missed.join(', '), r.names.extra.join(', '),
        r.identifiers.right + ' of ' + r.identifiers.gold, idText(r.identifiers.missed), idText(r.identifiers.wrong)];
    }), 'small'));
    var unread = pe.per_item.filter(function (r) { return !r.read; });
    if (unread.length) {
      var go = btn('Re-run the X-ray of the ' + (unread.length === 1 ? 'one item' : unread.length + ' items') + ' not read yet', '', function () {
        go.disabled = true;
        Promise.all(unread.map(function (r) { return api(dsPath('/item/' + r.item + '/rerun'), { body: {} }); })).then(function () {
          flash('Queued. Open Evaluate again in a minute or two.');
        }).catch(function (er) { go.disabled = false; flash(er.message, 'bad'); });
      }, 'One X-ray call per item, the same call that makes its X-ray');
      card.appendChild(go);
    }
    return card;
  }

  function questionForm() {
    var f = el('div', 'syn-form');
    var q = el('input', 'syn-in'); q.placeholder = 'A question with a known answer'; q.setAttribute('aria-label', 'New question');
    var facts = el('input', 'syn-in'); facts.placeholder = 'Key facts, separated by ;'; facts.setAttribute('aria-label', 'Key facts');
    var asker = el('select', 'syn-in'); asker.setAttribute('aria-label', 'Asked as');
    (S.data.people || []).forEach(function (p) { var o = el('option', null, 'asked as ' + p.name); o.value = p.key; asker.appendChild(o); });
    var gold = el('select', 'syn-in'); gold.multiple = true; gold.size = 6; gold.setAttribute('aria-label', 'Gold items');
    var forbidden = el('input'); forbidden.type = 'checkbox';
    function fill() {
      (S.items || []).filter(function (i) { return i.kind !== 'person'; }).forEach(function (i) {
        var o = el('option', null, i.title + ' (' + i.kind + ')'); o.value = i.id; gold.appendChild(o);
      });
    }
    if (S.items) fill(); else loadItems().then(fill);
    var addb = btn('Add the question', 'primary', function () {
      if (!q.value.trim()) return;
      var g = Array.prototype.filter.call(gold.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
      api(dsPath('/eval/question'), { body: { question: q.value, gold: g, asker: asker.value, forbidden: forbidden.checked,
        facts: facts.value.split(';').map(function (x) { return x.trim(); }).filter(Boolean), group: 'Added' } }).then(function () {
        S.evalData = null; renderTab();
      });
    });
    add(f, el('h6', null, 'Add a question'), q, add(el('div', 'syn-grid2'), asker,
      add(el('label', 'syn-check'), forbidden, ' must not be answerable (its gold items are forbidden to this asker)')),
      add(el('label', 'syn-field'), el('span', null, 'Gold items: the items a right answer needs (hold Ctrl or Cmd for several)'), gold), facts, addb);
    return f;
  }

  function evalSummary(summary, order) {
    // The run's own order (its first configuration is the baseline); a jsonb object keeps its keys sorted, not as written.
    var labels = (order || []).filter(function (l) { return summary && summary[l]; });
    Object.keys(summary || {}).forEach(function (l) { if (labels.indexOf(l) < 0) labels.push(l); });
    var rows = [['Recall at budget', 'recall', 'pct'], ['Citation correctness', 'citation', 'pct'], ['Answer correctness', 'answer', 'pct'],
      ['Time to pack, median', 'median_ms', 'ms'], ['Time to pack, slowest 5%', 'p95_ms', 'ms'], ['Cost per question', 'cost', 'money'],
      ['Searches made', 'searches', 'n'], ['The map alone answered, said the model (D85)', 'map_said_enough', 'n'],
      ['Searches skipped for it (D85)', 'searches_skipped', 'n'],
      ['Leaks (forbidden items in a pack)', 'leaks', 'n'], ['Hosted decision calls above normal', 'privacy', 'n'], ['Errors', 'errors', 'n'],
      ['Recall vs the first, points', 'recall_points_vs_first', 'n'], ['Citation vs the first, points', 'citation_points_vs_first', 'n'],
      ['Answer vs the first, points', 'answer_points_vs_first', 'n']];
    var gateKey = { recall: 'recall', citation: 'citation', median_ms: 'median', p95_ms: 'p95', cost: 'cost', leaks: 'leaks', privacy: 'privacy' };
    var body = rows.map(function (r) {
      return [rowLabel(r[0])].concat(labels.map(function (l) {
        var s = summary[l] || {}, v = s[r[1]];
        var text = v == null ? '' : r[2] === 'pct' ? (v * 100).toFixed(1) + '%' : r[2] === 'ms' ? msText(v) : r[2] === 'money' ? money(v) : String(v);
        var g = gateKey[r[1]];
        var cell = el('span', null, text);
        if (g && s.gates && v != null) cell.appendChild(el('span', 'syn-badge ' + (s.gates[g] ? 'good' : 'badc'), s.gates[g] ? 'passes' : 'fails'));
        return cell;
      }));
    });
    body.push([rowLabel('Decision-model gate (D79)')].concat(labels.map(function (l) {
      var s = summary[l] || {};
      return s.decision_gate == null ? '' : (s.decision_gate ? 'passes: may be switched on' : 'fails: stays off');
    })));
    return table(['Measure'].concat(labels), body, 'eval');
  }

  function evalRunView(run, questions) {
    var box = el('section', 'syn-card');
    box.appendChild(named(el('h6', null, run.label + ' · ' + run.status + (run.status === 'running' ? ' (' + (run.results || []).length + ' answered so far)' : '')),
      'One run of the evaluation set, and its state'));
    if (run.summary && Object.keys(run.summary).length) {
      box.appendChild(evalSummary(run.summary, (run.configs || []).map(function (c) { return c.label; })));
    }
    var byQ = {};
    (questions || []).forEach(function (q) { byQ[q.id] = q; });
    box.appendChild(table(['Configuration', 'Question', 'Recall', 'Citations', 'Facts', 'Pack', 'Cost', 'Answer'], (run.results || []).map(function (r) {
      var q = byQ[r.question] || {};
      var open = btn(r.text || q.question || '', 'linkish', function () { openQuery(r.query); setTab('retrieve'); });
      return [r.config, open, r.forbidden ? (r.leaked && r.leaked.length ? 'LEAKED' : 'nothing leaked') : (r.recall == null ? '' : (r.recall * 100).toFixed(0) + '%'),
        r.citation_correctness == null ? '' : (r.citation_correctness * 100).toFixed(0) + '%', r.answer_correctness == null ? '' : (r.answer_correctness * 100).toFixed(0) + '%',
        msText(r.ms_pack), money(r.cost), shortText(r.answer || r.error || '', 220, 'Answer to: ' + (r.text || q.question || ''))];
    }), 'small'));
    return box;
  }

  /* --- (i): what each part of the page means ------------------------------------------

     Petar asked for an (i) beside every section, title and attribute, opening a
     generic explanation of it, with a 🤷‍♂️ that has it said again another way
     (fr_bc51d0de9b2b). The buttons are put in by one observer over the page,
     whatever drew it, so a redraw every two seconds keeps them, and a part of the
     page added later gets them without its own code knowing. An explanation is
     asked for by the label and where it sits, never by what the dataset holds
     (`rouh/synapse/explain.py`); the server keeps the first one, and the rewrites
     live in this page until it is closed. */

  var EXPLAINED = {};
  var POP = { box: null, anchor: null, key: '', show: null };
  var EXPLAIN_TARGETS = ['h4', 'h6', 'th', 'dt', '.syn-field > span:first-child', '.syn-set-label > span:first-child',
    '.syn-group > summary', 'details.syn-step > summary', '.syn-json > summary', '.syn-step-title', '.syn-chip',
    '.syn-rowlabel', '.syn-ckind', '.syn-badge.dm', '.syn-tab.on', '.syn-segb.on', '.syn-check'].join(',');
  // Buttons and labels around a control cannot hold another button: theirs goes beside them.
  var BESIDE = { 'syn-tab': 1, 'syn-segb': 1, 'syn-check': 1 };

  function explainLabel(node) {
    if (node.dataset.explain) return node.dataset.explain;
    if (node.classList.contains('syn-badge') && node.classList.contains('dm')) return 'A decision model\'s answer, and its purpose';
    var text = '';
    node.childNodes.forEach(function (c) {
      if (c.nodeType === 3) text += c.textContent;
      else if (c.nodeType === 1 && !c.classList.contains('syn-i') && c.tagName !== 'INPUT' && c.tagName !== 'SELECT' &&
        !c.classList.contains('syn-ref') && !c.classList.contains('syn-step-n') && !c.classList.contains('syn-step-meta')) text += c.textContent;
    });
    text = text.replace(/\s*\(\d[\d,]*\)/g, '').replace(/\s+/g, ' ').trim();
    if (node.classList.contains('syn-ckind')) text = 'Claim kind: ' + text.replace(/ (OPEN|CLOSED)$/, '');
    return text;
  }

  function explainWanted(node) {
    if (node.closest('[data-noexplain]')) return false;
    if (node.classList.contains('syn-step-title')) return true;
    if (node.tagName === 'SUMMARY' && node.querySelector('.syn-step-title')) return false;
    if (node.classList.contains('syn-ckind')) {
      // A list of claims says what a kind is once, at its first claim of that kind.
      var list = node.closest('.syn-claims');
      var mine = explainLabel(node);
      var first = list && Array.prototype.filter.call(list.querySelectorAll('.syn-ckind'), function (k) { return explainLabel(k) === mine; })[0];
      if (first && first !== node) return false;
    }
    if (node.tagName === 'TH' && !node.textContent.trim()) return false;
    return !!explainLabel(node);
  }

  function infoButton(node) {
    var b = el('button', 'syn-i');
    b.type = 'button';
    var label = explainLabel(node);
    b.setAttribute('aria-label', 'What this means: ' + label);
    b.title = 'What this means';
    b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (POP.box && POP.anchor === b) { closeExplain(true); return; }
      openExplain(b, node);
    });
    return b;
  }

  function decorate(root) {
    if (!root || root.nodeType !== 1) return;
    var found = root.matches && root.matches(EXPLAIN_TARGETS) ? [root] : [];
    root.querySelectorAll(EXPLAIN_TARGETS).forEach(function (n) { found.push(n); });
    found.forEach(function (n) {
      if (n.dataset.explained === '1' || !n.isConnected) return;
      if (!explainWanted(n)) return;
      n.dataset.explained = '1';
      var b = infoButton(n);
      var beside = Object.keys(BESIDE).some(function (c) { return n.classList.contains(c); });
      if (beside) n.after(b); else n.appendChild(b);
    });
  }

  var explainWatch = null;
  function watchForLabels() {
    var body = $('synBody');
    if (!body || explainWatch) return;
    explainWatch = new MutationObserver(function (records) {
      records.forEach(function (r) { r.addedNodes.forEach(function (n) { if (n.nodeType === 1 && !n.classList.contains('syn-i')) decorate(n); }); });
    });
    explainWatch.observe(body, { childList: true, subtree: true });
    decorate(body);
  }

  // Where a label sits, in words that hold nothing of the dataset: which page and
  // tab, which view of it, and the section around it.
  function explainPlace(node) {
    var bits = [];
    var kind = node.tagName === 'TH' ? 'a column of a table' : node.tagName === 'DT' ? 'a named value in a list of values' :
      node.closest('.syn-set-label') ? 'a number Synapse works by' : node.closest('.syn-field') ? 'a field of a form' :
        node.classList.contains('syn-chip') ? 'a count in the row at the top of a dataset' :
          node.classList.contains('syn-rowlabel') ? 'a row of a table' : node.classList.contains('syn-ckind') ? 'the kind of a claim in an X-ray' :
            node.classList.contains('syn-tab') ? 'a tab of a dataset' : node.classList.contains('syn-segb') ? 'a choice of view' :
              node.classList.contains('syn-step-title') ? 'one step of an operation\'s trace' :
                node.tagName === 'SUMMARY' ? 'a part that folds open' : node.classList.contains('syn-check') ? 'a switch' :
                  node.classList.contains('syn-badge') ? 'a decision shown inside a step' : 'a heading';
    bits.push(kind);
    var section = sectionOf(node);
    if (section) bits.push('in the section "' + section + '"');
    if (node.tagName === 'TH') {
      var table = node.closest('table');
      var cols = table ? Array.prototype.map.call(table.querySelectorAll('thead th'), function (th) { return explainLabel(th); }).filter(Boolean) : [];
      if (cols.length > 1) bits.push('(the table\'s columns are: ' + cols.join(', ') + ')');
    }
    if (!S.ds) bits.push('on the Synapse homepage');
    else if (!node.closest('#synPane')) bits.push('at the top of a dataset\'s page, the same on every tab');
    else {
      var tab = (TABS.filter(function (t) { return t[0] === S.tab; })[0] || [])[1] || S.tab;
      var view = S.tab === 'items' && S.item ? ', on one item\'s page' : S.tab === 'retrieve' && S.query ? ', on one question\'s page' :
        S.tab === 'explore' ? ', in its ' + ({ graph: 'Graph', map: 'The tiny map', search: 'Search', layers: 'Layers and topics' }[S.explore] || S.explore) + ' view' :
          S.tab === 'add' ? ', adding ' + ({ note: 'a fact or note', rule: 'a rule', task: 'a task', event: 'an event', topic: 'a topic', person: 'a person',
            place: 'a place', email: 'an email', doc: 'a document', files: 'files' }[S.addMode] || S.addMode) : '';
      if (S.tab === 'activity' && node.closest('#synTraceDetail')) view = ', in the steps of one operation';
      bits.push('on the ' + tab + ' tab of a dataset' + view);
    }
    return bits.join(', ');
  }

  function sectionOf(node) {
    var heading = node.tagName === 'H4' || node.tagName === 'H6';
    for (var a = node.parentElement; a && a.id !== 'synBody'; a = a.parentElement) {
      if (a.tagName === 'DETAILS' && a.classList.contains('syn-step') && a.firstElementChild && a.firstElementChild.contains(node) === false) {
        var t = a.querySelector(':scope > summary .syn-step-title') || a.querySelector(':scope > summary');
        if (t) return explainLabel(t);
      }
      if (heading) continue;
      var heads = a.querySelectorAll(':scope > h4, :scope > h6, :scope > summary');
      for (var i = heads.length - 1; i >= 0; i--) {
        var h = heads[i];
        if (h === node || h.contains(node)) continue;
        if (h.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING) return explainLabel(h);
      }
    }
    return '';
  }

  function explainHint(node) {
    var lab = node.closest('.syn-set-label');
    if (!lab) return '';
    var note = lab.querySelector('.syn-set-note');
    var ref = lab.querySelector('.syn-ref');
    return [ref ? ref.textContent : '', note ? note.textContent : ''].filter(Boolean).join(': ');
  }

  function openExplain(button, node) {
    closeExplain(false);
    var label = explainLabel(node);
    var place = explainPlace(node);
    var key = place + '\n' + label;
    var box = el('div', 'syn-pop');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'What "' + label + '" means');
    var head = el('div', 'syn-pop-head');
    var close = el('button', 'syn-pop-x', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    close.addEventListener('click', function () { closeExplain(true); });
    add(head, el('strong', 'syn-pop-label', label), close);
    var text = el('p', 'syn-pop-text');
    text.setAttribute('aria-live', 'polite');
    var asked = el('div', 'syn-pop-asked');
    var again = el('button', 'syn-pop-again', '🤷‍♂️');
    again.type = 'button';
    again.title = 'I still don\'t get it: say it another way';
    again.setAttribute('aria-label', 'I still don\'t get it: say it another way');
    // His own words about the explanation in front of him: what made sense, what
    // did not, a question. The next one is written around them (fr_8f9b0f6b0fa4).
    // A plain row rather than a form, so nothing depends on a frame allowing forms.
    var form = el('div', 'syn-pop-ask');
    var input = el('input', 'syn-pop-input');
    input.type = 'text';
    input.placeholder = 'Ask, or say what was clear';
    input.setAttribute('aria-label', 'Your question about this explanation');
    input.setAttribute('enterkeyhint', 'send');
    input.maxLength = 1000;
    var send = el('button', 'syn-pop-send', 'Ask');
    send.type = 'button';
    add(form, input, send);
    var foot = el('div', 'syn-pop-foot');
    var count = el('span', 'syn-pop-count');
    var earlier = el('details', 'syn-pop-earlier');
    var earlierHead = el('summary', '', '');
    var earlierList = el('ol', 'syn-pop-earlier-list');
    add(earlier, earlierHead, earlierList);
    add(foot, again, count);
    add(box, head, asked, text, form, foot, earlier);
    document.body.appendChild(box);
    POP.box = box; POP.anchor = button; POP.key = key; POP.show = null;
    button.setAttribute('aria-expanded', 'true');
    button.classList.add('on');

    // texts[i] is the i-th explanation and asks[i] what he said that brought it
    // ('' for the first and for a 🤷‍♂️), so each one is seen tied to his question.
    var seen = EXPLAINED[key] || (EXPLAINED[key] = { texts: [], asks: [] });
    // The answer may arrive after this box was closed and another opened on the
    // same label, so it redraws whichever box is open on it then.
    function refresh() { if (POP.key === key && POP.show) POP.show(); }
    function show() {
      var n = seen.texts.length;
      var last = seen.texts[n - 1];
      var q = seen.busy ? seen.pending || '' : seen.error ? '' : seen.asks[n - 1] || '';
      asked.textContent = q ? 'You asked: ' + q : '';
      asked.hidden = !q;
      text.className = 'syn-pop-text' + (seen.error ? ' bad' : '') + (seen.busy ? ' busy' : '');
      text.textContent = seen.busy ? (seen.pending ? 'Rewriting it around what you asked...' : n ? 'Saying it another way...' : 'Writing an explanation...') :
        seen.error ? seen.error : (last || '');
      again.disabled = !!seen.busy;
      again.textContent = !n && seen.error && !seen.busy ? 'Try again' : '🤷‍♂️';
      form.hidden = !n;
      input.disabled = send.disabled = !!seen.busy;
      count.textContent = n > 1 ? 'Said ' + n + ' ways' : '';
      // The earlier versions stay readable, newest first, folded away under the new one.
      var older = n - (seen.busy || seen.error ? 0 : 1);
      earlier.hidden = older < 1;
      earlierHead.textContent = older === 1 ? 'The earlier explanation' : 'The ' + older + ' earlier explanations';
      earlierList.textContent = '';
      for (var i = older - 1; i >= 0; i--) {
        var li = el('li', '');
        li.value = i + 1;
        if (seen.asks[i]) add(li, el('div', 'syn-pop-asked', 'You asked: ' + seen.asks[i]));
        add(li, el('div', '', seen.texts[i]));
        add(earlierList, li);
      }
      placeExplain();
    }
    function ask(question) {
      seen.busy = true; seen.error = ''; seen.pending = question || '';
      refresh();
      api('/explain', { body: { label: label, place: place, hint: explainHint(node), before: seen.texts, asks: seen.asks, question: question || '' } }).then(function (j) {
        seen.busy = false; seen.pending = '';
        if (j && j.ok && j.text) { seen.texts.push(j.text); seen.asks.push(question || ''); }
        else { seen.error = (j && j.why) || 'No explanation came back.'; if (question && POP.key === key && !input.value) input.value = question; }
        refresh();
      }).catch(function (e) {
        seen.busy = false; seen.pending = ''; seen.error = e.message;
        if (question && POP.key === key && !input.value) input.value = question;
        refresh();
      });
    }
    again.addEventListener('click', function () { if (!seen.busy) ask(); });
    function submit() {
      var q = input.value.trim();
      if (!q || seen.busy || !seen.texts.length) return;
      input.value = '';
      ask(q);
    }
    send.addEventListener('click', submit);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); submit(); }
    });
    POP.show = show;
    if (seen.texts.length || seen.busy) show(); else ask();
    again.focus({ preventScroll: true });
  }

  function placeExplain() {
    var box = POP.box, b = POP.anchor;
    if (!box || !b || !b.isConnected) return;
    var r = b.getBoundingClientRect();
    var vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var w = Math.min(360, vw - 32);
    box.style.width = w + 'px';
    var left = Math.max(16, Math.min(r.left - 12, vw - w - 16));
    box.style.left = left + 'px';
    var h = box.offsetHeight;
    var top = r.bottom + 8;
    if (top + h > vh - 16 && r.top - 8 - h >= 16) top = r.top - 8 - h;
    box.style.top = Math.max(16, Math.min(top, vh - h - 16)) + 'px';
  }

  function closeExplain(refocus) {
    if (!POP.box) return;
    var b = POP.anchor;
    POP.box.remove();
    POP.box = null; POP.anchor = null; POP.key = ''; POP.show = null;
    if (b) { b.setAttribute('aria-expanded', 'false'); b.classList.remove('on'); if (refocus && b.isConnected) b.focus({ preventScroll: true }); }
  }

  document.addEventListener('pointerdown', function (e) {
    if (!POP.box) return;
    if (POP.box.contains(e.target) || (POP.anchor && POP.anchor.contains(e.target))) return;
    closeExplain(false);
  }, true);
  document.addEventListener('keydown', function (e) {
    if (!POP.box || e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    closeExplain(true);
  }, true);
  window.addEventListener('resize', placeExplain);
  document.addEventListener('scroll', placeExplain, true);

  document.addEventListener('keydown', function (e) {
    if (!S.open || S.tab !== 'retrieve' || !S.queryData) return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
    var frames = ((S.queryData.walk || {}).frames || []);
    if (!frames.length) return;
    if (e.key === 'ArrowRight') { S.frame = Math.min(frames.length - 1, S.frame + 1); renderTab(); }
    if (e.key === 'ArrowLeft') { S.frame = Math.max(0, S.frame - 1); renderTab(); }
  });
})();
