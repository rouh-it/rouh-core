/* Evolution (`rouh/evolution.py`, `rouh/web/evolution.py`): Parameters, Mutations and the Gene Pool.

   Petar, 13 October 2026, task 94 step 94-08: a navigation box called Evolution, right before
   Anatomy. Parameters sets how many genes a night the nightly run builds and how many of each of
   the four kinds, always adding up, 0 pausing the building. Mutations, called the Gene library
   until 14 October 2026 (fr_a982710d30c7: "Gene library competes as name so it should be renamed
   to mutations"), holds every gene the run built for him, in three lists, On trial, Passed and
   Failed (Passed and Failed were one, Out of trial, from 18 October 2026, when every gene became on
   by default, to 19 October), a month view and the gene log, with the switches no gene has under
   Passed; each gene opens on one page with no tabs (fr_2d2b3726ebb0), its mutation folded at the
   bottom. The morning deck, the new genes on trial one card at a time, was taken out on 19 October
   2026 (fr_650809f11685). The Gene Pool, a view of the Gene library until the same day ("gene pool need
   to be its own item in evolution"), is a page of its own, at `/evolution/pool`.

   Everything here is read from and written to the server, which keeps it per person; nothing is
   kept in this browser but the draft of Parameters before Save. The layer, its address and the
   message box are app/runs.js's, handed over as `window.RouhEvolutionHost`. */
(function () {
  'use strict';

  var API = '/api/evolution';
  var KIND_ORDER = ['invisible', 'shows_up', 'ask_for', 'changes_work'];
  /* Lists, each at its own address (Petar, 18 October 2026: "there are genes in trial and genes
     out of trial. That should be clear division and screens"): New, On trial, Passed and Failed.
     New, the first and where Mutations opens, is every gene on trial he has not decided anything
     about; On trial is the ones he has (19 October 2026: "Essentially I want a list that I
     haven't reviewed yet, different than things in trial"). The views before them are sent on to
     the one that holds them now. */
  /* Failed was split on 27 October 2026 (fr_c1aa7f60359d: "If that the category for the things I
     reject only, let's call it so. If those are rejected by some other mechanism should be a
     different category"): Rejected is what he rejected or turned off himself, Not used what its
     trial failed by itself. */
  var VIEWS = [['new', 'New'], ['trial', 'On trial'], ['passed', 'Passed'], ['rejected', 'Rejected'], ['unused', 'Not used'],
               ['month', 'Month'], ['log', 'Gene log']];
  /* Out of trial was one view of Passed and Failed until 19 October 2026, the month view the week
     view, and the morning deck a page of its own (Petar, fr_650809f11685: "where it says out of
     trial, make it two separate items - pass n fail", "week should be month", "Remove the morning
     deck button and functionality"): their old addresses are sent on, Out of trial to Passed. */
  var OLD_VIEWS = { review: 'trial', rouh: 'trial', off: 'rejected', failed: 'rejected', out: 'passed',
                    week: 'month', deck: 'new' };
  /* The Pool's review list was `pool/yours` until 25 October 2026, when it became Outgoing genes
     (task 141, step 141-15): its addresses open the page it is now. */
  function newSub(page, sub) {
    if (page === 'pool') { return String(sub || '').replace(/^yours(\/|$)/, 'outgoing$1'); }
    return OLD_VIEWS[sub] || sub || '';
  }
  function viewName(id) {
    for (var i = 0; i < VIEWS.length; i++) { if (VIEWS[i][0] === id) { return VIEWS[i][1]; } }
    return id;
  }
  /* The gene log and the Gene Pool are drawn by `genelogpage.js` (`window.RouhGeneLog`), inside this
     layer and its address: every gene in Rouh with its use, a view of Mutations, and the Pool, a
     page of its own. Both speak in their own words for where they are, `log/<id>` and
     `pool/<family>`; `extSub` and `extCtx` turn the Pool's into its page and back. */
  function ext() { return window.RouhGeneLog || null; }
  function isExt(sub) { return /^(log|pool)(\/|$)/.test(sub || ''); }
  function extSub() { return R.page === 'pool' ? 'pool' + (R.sub ? '/' + R.sub : '') : R.sub; }
  /* Where a sub of the gene log's or the Pool's own words is: the Pool's page, or Mutations. */
  function goSub(sub) {
    var pool = /^pool(?:\/(.*))?$/.exec(sub || '');
    if (pool) { go('pool', pool[1] || ''); } else { go('mutations', sub); }
  }
  var R = { open: false, page: 'mutations', sub: '', seq: 0, error: '', said: '',
            params: null, draft: null, weights: null, saving: false,
            muts: null, q: '', gene: null, geneId: 0, focus: '', tab: 'essence',
            month: null, asking: false, topic: 0 };

  function host() { return window.RouhEvolutionHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text, title) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (title) { b.title = title; }
    return b;
  }
  function link(text, href, cls) {
    var a = el('a', cls || 'evo-link', text);
    a.href = href;
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
      e.preventDefault();
      if (host().go) { host().go(href); } else { location.href = href; }
    });
    return a;
  }

  /* ---- talking to the server ---- */

  function call(path, body) {
    var init = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) {
      init.method = 'POST';
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    return fetch(API + path, init).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that just now. Try again in a moment.'); }
        return j;
      });
    });
  }

  function load() {
    var seq = ++R.seq;
    R.error = '';
    var want = R.page === 'parameters' ? call('/parameters').then(function (j) {
      if (seq !== R.seq || !j) { return; }
      R.params = j;
      if (!R.draft) { R.draft = pick(j.parameters); R.weights = pick(j.parameters); }
    }) : R.page === 'pool' ? poolLoad(seq)
      // The Incubator and the nightly run read their own answers once mounted (`incubatorpage.js`).
      : R.page === 'incubator' || R.page === 'nightly' || R.page === 'trials' ? Promise.resolve() : mutationsLoad(seq);
    return want.then(draw, function (err) {
      if (seq !== R.seq) { return; }
      R.error = String((err && err.message) || err);
      draw();
    });
  }

  /* The Gene Pool's page: the Pool's own answer, and Mutations' for the Pool's name. */
  function poolLoad(seq) {
    return Promise.all([
      R.muts ? Promise.resolve() : call('/mutations').then(function (j) { if (seq === R.seq && j) { R.muts = j; } }),
      ext() ? ext().load(extSub(), function () { return seq === R.seq; }) : Promise.resolve()
    ]);
  }

  function mutationsLoad(seq) {
    var sub = R.sub;
    if (isExt(sub) && ext()) {
      return Promise.all([
        R.muts ? Promise.resolve() : call('/mutations').then(function (j) { if (seq === R.seq && j) { R.muts = j; } }),
        ext().load(sub, function () { return seq === R.seq; })
      ]);
    }
    var gene = /^gene\/(\d+)(?:\/(\w+))?$/.exec(sub);
    var jobs = [call('/mutations' + (R.q ? '?q=' + encodeURIComponent(R.q) : '')).then(function (j) {
      if (seq === R.seq && j) { R.muts = j; }
    })];
    if (gene) {
      R.geneId = +gene[1];
      jobs.push(call('/genes/' + R.geneId).then(function (j) {
        if (seq === R.seq && j) { R.gene = j; }
      }, function (err) {
        // Said once, above the way back; the rest of Mutations still loads.
        if (seq === R.seq) { R.gene = { missing: String((err && err.message) || err) }; }
      }));
    } else if (sub === 'month') {
      jobs.push(call('/month').then(function (j) { if (seq === R.seq && j) { R.month = j; } }));
    }
    return Promise.all(jobs);
  }

  function pick(p) {
    var out = { total: +p.total || 0 };
    KIND_ORDER.forEach(function (k) { out[k] = +p[k] || 0; });
    return out;
  }

  /* ---- where the layer is ---- */

  function go(page, sub) {
    R.page = page;
    R.sub = newSub(page, sub);
    if (R.sub.indexOf('gene/') !== 0) { R.gene = null; }
    aim();
    R.said = '';
    var title = R.gene && R.gene.card ? R.gene.card.name : '';
    if (host().moved) { host().moved(page, R.sub, title); }
    load();
    draw();
    var body = $('evolutionBody');
    if (body) { body.scrollTop = 0; }
  }

  /* A gene's page has four tabs, each with its own address (fr_44acd06b1e00, 19 October 2026:
     "I break it down into different things depending on what I want to know"): Essence at
     /gene/<id>, then /trial, /versions and /history. The parts it had before, /card, /learning,
     /mutations, /decisions and /questions, open the tab that holds that part now. */
  var GENE_TABS = [['essence', 'Essence'], ['trial', 'Trial'], ['versions', 'Versions'], ['history', 'History']];
  var OLD_PARTS = { card: 'essence', questions: 'essence', learning: 'trial', mutations: 'versions', decisions: 'history' };

  function openGene(id, part) { go('mutations', 'gene/' + id + (part ? '/' + part : '')); }

  function geneSub(id, tab) { return 'gene/' + id + (tab && tab !== 'essence' ? '/' + tab : ''); }

  function aim() {
    var g = /^gene\/(\d+)(?:\/(\w+))?$/.exec(R.sub);
    var part = (g && g[2]) || '';
    R.tab = OLD_PARTS[part] || (GENE_TABS.some(function (t) { return t[0] === part; }) ? part : 'essence');
    // Questions are under every tab, so /questions still opens the page at them.
    R.focus = part === 'questions' ? 'questions' : '';
    if (g) { R.sub = geneSub(g[1], R.tab); }
  }

  /* Another tab of the gene drawn in place, from what is already read: nothing is asked of the
     server again (B1), and the address follows so Back and reload come back to it (B2). */
  function geneTab(tab) {
    var c = R.gene && R.gene.card;
    if (!c || tab === R.tab) { return; }
    R.tab = tab;
    R.sub = geneSub(c.id, tab);
    if (host().moved) { host().moved('mutations', R.sub, c.name); }
    drawTab();
    // A change made in place on another tab, such as a trial's days, is in History at once: the
    // gene is read again behind the tab, which is drawn again only if anything in it changed (B3).
    var seq = R.seq, was = JSON.stringify(R.gene);
    call('/genes/' + c.id).then(function (j) {
      if (seq !== R.seq || tab !== R.tab || !j || !j.card || !R.gene || !R.gene.card || R.gene.card.id !== c.id
          || JSON.stringify(j) === was) { return; }
      R.gene = j;
      drawTab();
    }, function () {});
  }

  /* Only the tab list and the panel change: the answers above and Questions below stay as they
     are, with anything half typed in them. */
  function drawTab() {
    var panel = $('evoGenePanel');
    if (!panel || !R.gene || !R.gene.card) { draw(); return; }
    var tabs = document.querySelectorAll('.evo-gene-tabs [role="tab"]');
    Array.prototype.forEach.call(tabs, function (b) {
      var on = b.id === 'evoGeneTab-' + R.tab;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      if (on && document.activeElement !== b) { b.focus({ preventScroll: true }); }
    });
    panel.textContent = '';
    fillTab(panel, R.gene);
  }

  function fillTab(panel, p) {
    panel.setAttribute('aria-labelledby', 'evoGeneTab-' + R.tab);
    if (R.tab === 'trial') { trialTab(panel, p); }
    else if (R.tab === 'versions') { versionsTab(panel, p); }
    else if (R.tab === 'history') { historyTab(panel, p); }
    else { essenceTab(panel, p); }
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('evolutionBody');
    if (!body || !R.open) { return; }
    var keep = body.scrollTop;
    body.textContent = '';
    var wrap = el('div', 'evo-in');
    body.appendChild(wrap);
    var title = $('evolutionTitle');
    var meta = $('evolutionMeta');
    if (title) {
      title.textContent = R.page === 'parameters' ? 'Parameters'
        : R.page === 'incubator' ? 'Incubator' : R.page === 'nightly' ? 'Nightly run' : R.page === 'trials' ? 'Trials'
        : R.page === 'pool' ? poolName()
        : /^log/.test(R.sub) ? 'Gene log' : 'Mutations';
      // One gene's page has its back link and its own name, not a title of Mutations as well
      // (fr_fa2525969751).
      title.hidden = R.page === 'mutations' && /^gene\//.test(R.sub);
    }
    // Mutations has no line under its name: the counts are in its views' badges (fr_ca2be28fa511).
    // Trials has no line under its name either: "Evolution" there was a word its own trial tripped on.
    if (meta) { meta.textContent = R.page === 'mutations' || R.page === 'trials' ? '' : 'Evolution'; }
    if (R.error) { wrap.appendChild(el('p', 'evo-error', R.error)); }
    if (R.page === 'parameters') { drawParameters(wrap); }
    else if (R.page === 'incubator' || R.page === 'nightly' || R.page === 'trials') {
      // Each owns its part of the layer and draws it again itself, so a filter or a sort never
      // waits for this whole layer to be drawn (`incubatorpage.js`, `nightlyrunpage.js`, `trialspage.js`).
      wrap.classList.add('evo-wide');
      var mod = R.page === 'incubator' ? window.RouhIncubator : R.page === 'trials' ? window.RouhTrials : window.RouhNightlyRun;
      if (!mod) { wrap.appendChild(el('p', 'evo-loading', 'Reading…')); }
      else if (R.page === 'incubator' || R.page === 'trials') { mod.mount(wrap, R.sub, wideHost()); }
      else { mod.mount(wrap, wideHost()); }
    }
    else if (R.page === 'pool') { drawPool(wrap); }
    else { drawMutationsPage(wrap); }
    body.scrollTop = keep;
  }

  /* ---- Parameters ---- */

  function kindName(k) {
    var kinds = (R.params && R.params.kinds) || (R.muts && R.muts.kinds) || [];
    for (var i = 0; i < kinds.length; i++) { if (kinds[i].id === k) { return kinds[i].name; } }
    return k;
  }

  function spread(total, weights) {
    var base = {}, whole = 0;
    KIND_ORDER.forEach(function (k) { base[k] = Math.max(0, weights[k] || 0); whole += base[k]; });
    if (!whole) {
      var d = (R.params && R.params.defaults) || { invisible: 4, shows_up: 3, ask_for: 2, changes_work: 1 };
      KIND_ORDER.forEach(function (k) { base[k] = d[k]; whole += d[k]; });
    }
    var out = {}, exact = {}, sum = 0;
    KIND_ORDER.forEach(function (k) { exact[k] = total * base[k] / whole; out[k] = Math.floor(exact[k]); sum += out[k]; });
    KIND_ORDER.slice().sort(function (a, b) {
      return (exact[b] - out[b]) - (exact[a] - out[a]) || KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b);
    }).slice(0, total - sum).forEach(function (k) { out[k] += 1; });
    return out;
  }

  function setTotal(n) {
    var most = (R.params && R.params.most) || 20;
    n = Math.max(0, Math.min(most, n));
    var kinds = spread(n, R.weights || R.draft);
    R.draft.total = n;
    KIND_ORDER.forEach(function (k) { R.draft[k] = kinds[k]; });
  }

  function setKind(k, n) {
    var most = (R.params && R.params.most) || 20;
    var others = R.draft.total - R.draft[k];
    // A kind stops where the total would pass the most a night may be.
    n = Math.max(0, Math.min(most - others, n));
    R.draft[k] = n;
    R.draft.total = others + n;
    R.weights = pick(R.draft);
  }

  function same(a, b) {
    if (!a || !b) { return false; }
    return a.total === b.total && KIND_ORDER.every(function (k) { return a[k] === b[k]; });
  }

  function slider(label, value, most, hint, onMove, id) {
    var row = el('div', 'evo-slide');
    var head = el('div', 'evo-slide-head');
    var lab = el('label', 'evo-slide-name', label);
    lab.htmlFor = id + 'Range';
    head.appendChild(lab);
    var num = el('input', 'evo-num');
    num.type = 'number'; num.min = '0'; num.max = String(most); num.step = '1'; num.inputMode = 'numeric';
    num.value = String(value);
    num.id = id + 'Number';
    num.setAttribute('aria-label', label + ', as a number');
    head.appendChild(num);
    row.appendChild(head);
    var range = el('input', 'evo-range');
    range.type = 'range'; range.min = '0'; range.max = String(most); range.step = '1';
    range.value = String(value);
    range.id = id + 'Range';
    range.addEventListener('input', function () { onMove(+range.value); });
    num.addEventListener('change', function () {
      var raw = num.value.trim();
      var n = Number(raw);
      if (raw === '' || !isFinite(n) || n !== Math.floor(n) || n < 0 || n > most) {
        R.said = label + ' takes a whole number from 0 to ' + most + '. Nothing was changed.';
        refreshParams();
        return;
      }
      R.said = '';
      onMove(n);
    });
    row.appendChild(range);
    if (hint) { row.appendChild(el('p', 'evo-hint', hint)); }
    return { row: row, range: range, num: num };
  }

  /* Parameters is built once and then only its values move, so a slider is never rebuilt
     under the finger dragging it. */
  function drawParameters(wrap) {
    var j = R.params;
    if (!j) { wrap.appendChild(el('p', 'evo-loading', 'Reading your Parameters…')); return; }
    var most = j.most || 20, d = R.draft;
    var ui = R.ui = { kinds: {} };
    wrap.appendChild(el('p', 'evo-lede', 'How many genes the nightly run builds each night, and of which ' +
      'kinds. The four kinds always add up to the genes a night.'));
    ui.when = el('p', 'evo-when' + (j.schedule && j.schedule.paused ? ' paused' : ''), j.schedule ? j.schedule.line : '');
    wrap.appendChild(ui.when);
    var form = el('div', 'evo-params');
    ui.total = slider('Genes a night', d.total, most,
      '0 pauses the night’s building. Moving this spreads the total over the kinds in the proportions you last set.',
      function (n) { setTotal(n); refreshParams(); }, 'evoTotal');
    form.appendChild(ui.total.row);
    form.appendChild(el('p', 'evo-sec', 'Of which kinds'));
    (j.kinds || []).forEach(function (k) {
      ui.kinds[k.id] = slider(k.name, d[k.id], most, k.said, function (n) { setKind(k.id, n); refreshParams(); },
        'evoKind_' + k.id);
      form.appendChild(ui.kinds[k.id].row);
    });
    wrap.appendChild(form);
    ui.summary = el('div', 'evo-summary');
    ui.summary.setAttribute('aria-live', 'polite');
    wrap.appendChild(ui.summary);
    ui.said = el('p', 'evo-said');
    ui.said.setAttribute('role', 'status');
    wrap.appendChild(ui.said);
    var acts = el('div', 'evo-acts');
    ui.save = button('ctl small primary', 'Save');
    ui.save.addEventListener('click', saveParameters);
    acts.appendChild(ui.save);
    ui.undo = button('ctl small', 'Undo changes');
    ui.undo.addEventListener('click', function () {
      var saved = pick(R.params.parameters);
      R.draft = pick(saved); R.weights = pick(saved); R.said = ''; refreshParams();
    });
    acts.appendChild(ui.undo);
    ui.back = button('ctl small', 'Back to the proposal’s ' + j.defaults.total);
    ui.back.addEventListener('click', function () {
      R.draft = pick(R.params.defaults); R.weights = pick(R.params.defaults); R.said = ''; refreshParams();
    });
    acts.appendChild(ui.back);
    ui.state = el('span', 'evo-state');
    acts.appendChild(ui.state);
    wrap.appendChild(acts);
    var notes = el('ul', 'evo-notes');
    ['A warning such as “mutated from the original” is not a kind: the mutation check finds it after a gene is built, so it cannot be ordered here.',
     'The night’s caps stay as they are, however many genes it builds: at most 100 dollars and two sign-ups a night.',
     'With 0, the night still reads your comments, carries out your answers and builds your mutation requests, because you asked for each one.'
    ].forEach(function (t) { notes.appendChild(el('li', null, t)); });
    wrap.appendChild(notes);
    drawDrafts(wrap, j.drafts);
    drawTrialDefaults(wrap, j);
    refreshParams();
  }

  /* What a new trial starts with, its days and the uses that pass it; a trial already running keeps
     its own (`evolution.trial_defaults`). What counts is each gene's own use signals, every one of
     them ticked when its trial starts, so there is nothing to pick here. */
  function drawTrialDefaults(wrap, j) {
    if (!j.trial) { return; }
    var box = el('fieldset', 'evo-params evo-drafts');
    box.appendChild(el('legend', 'evo-slide-name', 'New trials'));
    box.appendChild(trialForm(j.trial, [], function (body) {
      return call('/parameters', { trial: body }).then(function (got) {
        R.params.trial = got.trial;
        return { said: 'Saved.', trial: got.trial };
      });
    }));
    wrap.appendChild(box);
  }

  /* Genes on the fly (`rouh/genedraft.py`): whether Rouh may offer to draft a gene by itself. Petar
     was asked on 13 October 2026 and has not answered, so it starts at "only when I ask". */
  function drawDrafts(wrap, d) {
    if (!d) { return; }
    var box = el('fieldset', 'evo-params evo-drafts');
    box.appendChild(el('legend', 'evo-slide-name', 'Genes on the fly'));
    box.appendChild(el('p', 'evo-hint', 'Rouh drafts a gene\u2019s contract in a conversation, you shape it, and \u201cgrow it\u201d builds it in, off until you turn it on. ' +
      'Should it offer one by itself when it sees you doing something by hand?' + (d.on ? '' : ' (Switched off here: gene_drafts, under Other switches in Mutations, Passed.)')));
    var said = el('p', 'evo-said');
    said.setAttribute('role', 'status');
    said.hidden = true;
    Object.keys(d.choices).forEach(function (k) {
      var lab = el('label', 'evo-radio');
      var r = el('input');
      r.type = 'radio'; r.name = 'evoPropose'; r.value = k; r.checked = d.value === k;
      r.addEventListener('change', function () {
        if (!r.checked) { return; }
        fetch('/api/genes/drafts/propose', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: k }) })
          .then(function (x) { return x.json().then(function (j) { if (!x.ok) { throw new Error(j.error); } return j; }); })
          .then(function (j) { d.value = k; said.textContent = j.said; said.hidden = false; },
                function (err) { said.textContent = String((err && err.message) || err); said.hidden = false; });
      });
      lab.appendChild(r);
      lab.appendChild(el('span', null, d.choices[k]));
      box.appendChild(lab);
    });
    box.appendChild(said);
    wrap.appendChild(box);
  }

  function refreshParams() {
    var ui = R.ui, j = R.params, d = R.draft;
    if (!ui || !j || !d || !ui.total || !document.body.contains(ui.total.row)) { return; }
    var saved = pick(j.parameters);
    function put(s, v) {
      if (document.activeElement !== s.num) { s.num.value = String(v); }
      s.range.value = String(v);
      s.range.setAttribute('aria-valuetext', String(v));
    }
    put(ui.total, d.total);
    KIND_ORDER.forEach(function (k) { if (ui.kinds[k]) { put(ui.kinds[k], d[k]); } });
    ui.summary.textContent = '';
    summary(ui.summary, d);
    ui.said.textContent = R.said || '';
    ui.said.hidden = !R.said;
    ui.save.textContent = R.saving ? 'Saving…' : 'Save';
    ui.save.disabled = R.saving || same(d, saved);
    ui.undo.disabled = same(d, saved);
    ui.back.disabled = same(d, pick(j.defaults));
    ui.state.textContent = same(d, saved)
      ? (j.parameters.default ? 'The proposal’s starting night: you have not changed it yet.'
        : 'Saved' + (j.parameters.by ? ' by ' + j.parameters.by : '') + '.')
      : 'Not saved yet: the night reads what is saved.';
    ui.when.textContent = j.schedule ? j.schedule.line : '';
  }

  function summary(box, d) {
    if (!d.total) {
      box.appendChild(el('p', 'evo-sum-main', 'Paused: the night builds no new genes.'));
      return box;
    }
    var parts = KIND_ORDER.filter(function (k) { return d[k]; }).map(function (k) { return d[k] + ' ' + kindName(k).toLowerCase(); });
    box.appendChild(el('p', 'evo-sum-main', d.total + (d.total === 1 ? ' gene' : ' genes') + ' a night: ' + parts.join(', ') + '.'));
    return box;
  }

  function saveParameters() {
    R.saving = true;
    R.said = '';
    refreshParams();
    call('/parameters', R.draft).then(function (j) {
      R.saving = false;
      if (!j) { return; }
      R.params = j;
      R.draft = pick(j.parameters);
      R.weights = pick(j.parameters);
      R.said = 'Saved. ' + (j.schedule ? j.schedule.line : '');
      refreshParams();
    }, function (err) {
      R.saving = false;
      R.said = String((err && err.message) || err);
      refreshParams();
    });
  }

  /* ---- the Gene Pool ---- */

  function poolName() { return (R.muts && R.muts.pool_name) || 'Gene Pool'; }

  function drawPool(wrap) {
    if (!window.RouhGenePool || !ext()) { wrap.appendChild(el('p', 'evo-loading', 'Reading the ' + poolName() + '…')); return; }
    ext().draw(wrap, extSub(), extCtx());
  }

  /* ---- Mutations ---- */

  function drawMutationsPage(wrap) {
    var muts = R.muts;
    if (!muts) { wrap.appendChild(el('p', 'evo-loading', 'Reading your mutations…')); return; }
    var gene = /^gene\/(\d+)/.exec(R.sub);
    if (gene) { drawGene(wrap); return; }
    var view = R.sub || 'new';
    if (isExt(view) && view.indexOf('/') > 0 && ext()) { ext().draw(wrap, view, extCtx()); return; }
    /* Where everything stands, first (Petar, 7 November 2026: "Make the journeys first and then pass
       it on for redesign and restructuring"; the journeys are in the commit that made this): one
       sentence, then the five lists in the order a gene goes through them, each its count and its
       name, the one open marked, and under them one bar of their shares. Month and the Gene log,
       opened rarely, are links beside Find a gene rather than tabs of their own. */
    wrap.appendChild(standing(muts, view));
    var bar = el('div', 'evo-bar evo-tools');
    var find = el('input', 'evo-find');
    find.type = 'search';
    find.placeholder = 'Find a gene';
    find.setAttribute('aria-label', 'Find a gene by its name or what it does');
    find.value = R.q;
    find.addEventListener('input', function () {
      R.q = find.value;
      clearTimeout(R.findTimer);
      R.findTimer = setTimeout(function () { load().then(function () { var f = document.querySelector('.evo-find'); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 250);
    });
    if (!isExt(view)) { bar.appendChild(find); }
    var more = el('nav', 'evo-more');
    more.setAttribute('aria-label', 'More of Mutations');
    [['month', 'Month'], ['log', 'Gene log']].forEach(function (v) {
      var a = link(v[1], '/evolution/mutations/' + v[0], 'evo-more-link');
      if (view === v[0]) { a.setAttribute('aria-current', 'page'); }
      more.appendChild(a);
    });
    bar.appendChild(more);
    wrap.appendChild(bar);
    if (isExt(view)) {
      if (ext()) { ext().draw(wrap, view, extCtx()); }
      return;
    }
    if (R.said) { wrap.appendChild(el('p', 'evo-said', R.said)); }
    if (view === 'month') { drawMonth(wrap); return; }
    var found = muts.found ? muts.found : null;
    // A gene is found when any of its versions is, and is still shown as its newest.
    function shown(list) {
      return found ? list.filter(function (g) {
        return [g].concat(g.older || []).some(function (x) { return found.indexOf(x.id) >= 0; });
      }) : list;
    }
    // A find that matches nothing in this list says so, rather than leaving the list blank.
    function list(of, none, how) {
      var got = shown(of);
      section(wrap, '', got, how);
      if (!of.length) { empty(wrap, none, ''); }
      else if (!got.length) { empty(wrap, 'No gene in ' + viewName(view) + ' matches \u201c' + R.q + '\u201d.', 'Clear Find a gene to see all ' + of.length + '.'); }
    }
    /* No lede and no line under each heading: Petar did not read them, and the rows say what each
       gene is, whether it is on and how its trial stands or ended (fr_ca2be28fa511). */
    if (view === 'passed') {
      list(muts.views.passed, 'No gene has passed yet.');
      // The switches no gene has are Rouh's own and shared genes', each on or off: under Passed,
      // where the genes that stay on are.
      otherSwitches(wrap, muts.switches || []);
    } else if (view === 'unused') {
      list(muts.views.unused, 'No gene has gone unused in its trial.');
    } else if (view === 'rejected') {
      list(muts.views.rejected, 'You have rejected no gene.');
      // Beside the rejections, every gene he had mutated: a minor reject the nights weigh too
      // (fr_c6b2abc655cf), so it is found where the rejections are, labelled as a mutation.
      mutatedSection(wrap, (muts.mutated || []).filter(function (r) {
        return !found || found.indexOf(r.gene_id) >= 0 || found.indexOf(r.result_gene_id) >= 0;
      }));
    } else if (view === 'trial') {
      building(wrap, muts);
      list(muts.views.trial, 'Nothing is on trial that you kept there.');
    } else {
      building(wrap, muts);
      // Every answer here takes its row out in place, the rest left where they are (B1).
      list(muts.views['new'] || [], 'Nothing new to look at.', { place: 'new', done: leftNew });
      unasked(wrap, muts.unasked || []);
    }
  }

  /* A gene answered in New leaves it at once, its row folded away where it was, and is counted in
     the list its answer put it in; Mutations is read again behind it for the other lists, and
     nothing on the screen is drawn again (B1). */
  function leftNew(c, j) {
    var muts = R.muts;
    if (!muts) { return; }
    muts.views['new'] = (muts.views['new'] || []).filter(function (g) { return g.id !== c.id; });
    muts.counts['new'] = muts.views['new'].length;
    var to = (j && j.gene && j.gene.group) || 'trial';
    if (to !== 'new' && muts.counts[to] != null) { muts.counts[to] += 1; }
    counts(muts.counts);
    // The row going is the answer seen (N1); only Reject and Mutate say more, whether the run that
    // takes its code out or builds the change has started.
    R.said = (j && j.said && (j.run || j.mutation || j.gene && j.gene.rejected)) ? j.said : '';
    var said = document.querySelector('#evolutionBody .evo-said');
    if (!said && R.said) {
      said = el('p', 'evo-said');
      var bar = document.querySelector('#evolutionBody .evo-bar');
      if (bar) { bar.after(said); }
    }
    if (said) { said.textContent = R.said; }
    var li = document.querySelector('#evolutionBody .evo-list [data-gene="' + c.id + '"]');
    if (li) {
      li.style.height = li.offsetHeight + 'px';
      li.classList.add('evo-leaving');
      requestAnimationFrame(function () { requestAnimationFrame(function () { li.style.height = '0px'; }); });
      setTimeout(function () {
        var ul = li.parentNode;
        li.remove();
        if (ul && !ul.children.length) {
          var box = el('div', 'evo-empty');
          box.appendChild(el('p', 'evo-empty-h', 'Nothing new to look at.'));
          ul.replaceWith(box);
        }
      }, 260);
    }
    var seq = R.seq;
    call('/mutations' + (R.q ? '?q=' + encodeURIComponent(R.q) : '')).then(function (got) {
      if (seq !== R.seq || !got) { return; }
      R.muts = got;
      counts(got.counts);
    }, function () {});
  }

  /* The five lists' counts, changed in place, with the bar of their shares and the sentence. */
  function counts(n) {
    var box = document.querySelector('#evolutionBody .evo-stand');
    if (box && R.muts) { box.replaceWith(standing(R.muts, box.dataset.view)); }
  }

  var GENE_LISTS = ['new', 'trial', 'passed', 'rejected', 'unused'];

  /* What the list view opens with: one sentence of what waits for him, then the five lists as one
     strip, each its count over its name, and one thin bar of their shares under it. The strip is
     how a list is opened; Cmd-click, Ctrl-click or the middle button opens one in a new tab (B2). */
  function standing(muts, view) {
    var n = muts.counts || {};
    var box = el('div', 'evo-stand');
    box.dataset.view = view;
    var fresh = n['new'] || 0, trial = n.trial || 0, building = (muts.requests || []).length;
    var head = el('p', 'evo-stand-h');
    head.appendChild(words(fresh ? fresh + (fresh === 1 ? ' new gene waits' : ' new genes wait') + ' for your first look.'
      : 'Nothing new to look at.'));
    var rest = [trial + ' on trial'];
    if (building) { rest.push(building + (building === 1 ? ' change of yours' : ' changes of yours') + ' being built'); }
    head.appendChild(el('span', 'evo-stand-rest', ' ' + rest.join(', ') + '.'));
    box.appendChild(head);
    var strip = el('nav', 'evo-lists');
    strip.setAttribute('aria-label', 'Lists of genes');
    GENE_LISTS.forEach(function (id) {
      var a = el('a', 'evo-list-cell');
      a.href = '/evolution/mutations/' + id;
      a.dataset.view = id;
      if (view === id) { a.setAttribute('aria-current', 'page'); }
      a.appendChild(el('b', 'evo-list-n', n[id] || 0));
      a.appendChild(el('span', 'evo-list-name', viewName(id)));
      a.setAttribute('aria-label', viewName(id) + ', ' + (n[id] || 0));
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
        e.preventDefault();
        go('mutations', id);
      });
      strip.appendChild(a);
    });
    box.appendChild(strip);
    var total = GENE_LISTS.reduce(function (t, id) { return t + (n[id] || 0); }, 0);
    var share = el('div', 'evo-share');
    share.setAttribute('aria-hidden', 'true');
    GENE_LISTS.forEach(function (id) {
      if (!n[id]) { return; }
      var seg = el('i', 'evo-share-' + id);
      seg.style.flexGrow = String(n[id]);
      share.appendChild(seg);
    });
    if (total) { box.appendChild(share); }
    return box;
  }

  /* Every change he asked for that is not finished with, on New and On trial, so whether it has
     started, is being built or waits on him is seen without opening the gene; a row opens the
     gene's Versions, where Start now, Change, Withdraw and Review version are. */
  function building(wrap, muts) {
    var list = muts.requests || [];
    if (!list.length) { return; }
    var names = {};
    GENE_LISTS.forEach(function (id) {
      ((muts.views || {})[id] || []).forEach(function (g) {
        names[g.id] = g.name;
        (g.older || []).forEach(function (x) { names[x.id] = g.name; });
      });
    });
    wrap.appendChild(el('h4', 'evo-sec-h', 'Your changes being built \u00b7 ' + list.length));
    var ul = el('ul', 'evo-list evo-building');
    list.forEach(function (r) {
      var li = el('li', 'evo-row');
      var b = button('evo-row-btn');
      var top = el('span', 'evo-row-top');
      top.appendChild(el('span', 'evo-row-name', (names[r.gene] || 'A gene') + ' \u00b7 your change to version ' + r.from_version));
      top.appendChild(chip(reqWords(r), r.result_waiting ? 'evo-state-candidate' : 'evo-req-' + r.status));
      b.appendChild(top);
      b.appendChild(el('span', 'evo-row-said', '\u201c' + r.words + '\u201d'));
      var sub = el('span', 'evo-row-sub', 'Asked ' + r.made_words + ' \u00b7 ');
      sub.appendChild(el('span', 'evo-open-hint', 'Open its versions'));
      b.appendChild(sub);
      b.setAttribute('aria-label', (names[r.gene] || 'A gene') + ', your change: ' + reqWords(r));
      b.addEventListener('click', function () { openGene(r.gene, 'versions'); });
      li.appendChild(b);
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
  }

  /* A brand-new gene nobody asked for that has no card here (one the nightly run added to the gene
     map, say): one line each, saying what it is, opening its page in the gene log. No yes or no:
     Petar, 19 October 2026 (GENES.md, "Every file belongs to a gene"). */
  function unasked(wrap, list) {
    if (!list.length) { return; }
    // In a fold closed until pressed, so thirty of them never push the genes to look at off the
    // screen (journey 1); its count is on the fold.
    var fold = el('details', 'evo-fold');
    fold.appendChild(el('summary', 'evo-fold-h', 'New genes nobody asked for \u00b7 ' + list.length));
    var ul = el('ul', 'evo-list evo-unasked');
    list.forEach(function (g) {
      var li = el('li', 'evo-row');
      var b = button('evo-row-btn');
      var main = el('span', 'evo-other-words');
      main.appendChild(el('span', 'evo-row-name', g.name));
      if (g.sentence && g.sentence !== g.name) { main.appendChild(el('span', 'evo-row-said', g.sentence)); }
      b.appendChild(main);
      b.addEventListener('click', function () { go('mutations', 'log/' + g.id); });
      li.appendChild(b);
      ul.appendChild(li);
    });
    fold.appendChild(ul);
    wrap.appendChild(fold);
  }

  /* ---- the outside services a gene brought in, and the other switches ----

     The nightly run writes what it signs up for in its task's services.md, and a gene's Card names
     the ones it brought in, so Reject, which takes its code out, is seen to cover them. Anatomy, Money, Services is
     something else: what is paid for, kept by hand (Petar, 15 October 2026). */

  var SVC_FIELDS = [['address', 'Sign-up address'], ['account', 'Account'], ['login', 'Login kept'],
                    ['cancel', 'How to cancel'], ['renewal', 'Renews'], ['trial_end', 'Trial ends'],
                    ['reminder', 'Reminder']];
  var SVC_STATUS = [[/cancel|closed|deleted|refund/i, 'evo-svc-gone'], [/fail|error|refused/i, 'evo-warn'],
                    [/wait|pending|card|signing/i, 'evo-svc-wait'], [/active|live|trial|signed|paid|ok/i, 'evo-svc-on']];

  function words(text) { return document.createTextNode(text); }

  function spentWords(v) {
    var t = String(v || '').trim();
    return !t || /^\$?\s*0+(\.0+)?\s*(\$|usd|dollars?)?$/i.test(t) ? 'nothing spent' : t;
  }

  function serviceRow(v) {
    var li = el('li', 'evo-svc');
    var top = el('div', 'evo-row-top');
    top.appendChild(el('span', 'evo-row-name', v.service));
    if (v.status) {
      var cls = '';
      for (var i = 0; i < SVC_STATUS.length; i++) { if (SVC_STATUS[i][0].test(v.status)) { cls = SVC_STATUS[i][1]; break; } }
      top.appendChild(chip(v.status, cls));
    }
    top.appendChild(el('span', 'evo-svc-spent', spentWords(v.spent)));
    li.appendChild(top);
    var dl = el('dl', 'evo-svc-dl');
    function field(name, value) {
      dl.appendChild(el('dt', null, name));
      var dd = el('dd');
      if (typeof value === 'string') { dd.textContent = value; } else { dd.appendChild(value); }
      dl.appendChild(dd);
    }
    SVC_FIELDS.forEach(function (f) { if (v[f[0]]) { field(f[1], v[f[0]]); } });
    if (dl.childNodes.length) { li.appendChild(dl); }
    return li;
  }

  function otherSwitch(w) {
    var li = el('li', 'evo-row evo-other');
    var box = el('div', 'evo-other-words');
    box.appendChild(el('span', 'evo-row-name', w.title || w.name));
    var under = [w.name];
    if (w.night) { under.push('night ' + w.night); }
    box.appendChild(el('span', 'evo-row-sub evo-mono', under.join(' · ')));
    li.appendChild(box);
    var sw = button('evo-switch' + (w.on ? ' on' : ''), null, w.on ? 'Turn ' + (w.title || w.name) + ' off' : 'Turn ' + (w.title || w.name) + ' on');
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', w.on ? 'true' : 'false');
    sw.setAttribute('aria-label', w.title || w.name);
    sw.appendChild(el('span', 'evo-switch-track')).appendChild(el('span', 'evo-switch-knob'));
    sw.appendChild(el('span', 'evo-switch-word', w.on ? 'On' : 'Off'));
    sw.addEventListener('click', function () {
      sw.disabled = true;
      call('/switches', { name: w.name, on: !w.on }).then(function (j) {
        if (R.muts) { R.muts.switches = j.switches || []; }
        R.said = j.said || '';
        draw();
      }, function (err) { sw.disabled = false; fail(err); });
    });
    li.appendChild(sw);
    return li;
  }

  /* Other switches: every feature switch no gene here has, Rouh's own and any shared gene's,
     a small section under Passed. A gene's own switch is on its row. */
  function otherSwitches(wrap, list) {
    if (!list.length) { return; }
    wrap.appendChild(el('h4', 'evo-sec-h', 'Other switches · ' + list.length));
    wrap.appendChild(el('p', 'evo-sec-p', 'Switches no gene has. Off stops it at once.'));
    var ul = el('ul', 'evo-list evo-others');
    list.forEach(function (w) { ul.appendChild(otherSwitch(w)); });
    wrap.appendChild(ul);
  }

  /* The outside services a gene brought in, on its page: Reject cancels them. */
  function geneServices(p) {
    var list = p.services || [];
    if (!list.length) { return null; }
    var box = el('section', 'evo-svc-box');
    box.setAttribute('aria-label', 'Outside services it brought in');
    box.appendChild(el('p', 'evo-k', 'Outside services it brought in'));
    var ul = el('ul', 'evo-list');
    list.forEach(function (v) { ul.appendChild(serviceRow(v)); });
    box.appendChild(ul);
    box.appendChild(el('p', 'evo-hint', 'Reject takes its code out and cancels each of these by its How to cancel.'));
    return box;
  }

  /* What `genelogpage.js` is handed to draw inside this layer. */
  function extCtx() {
    return {
      go: goSub,
      redraw: draw,
      reload: load,
      openMutationsGene: function (id) { openGene(id); },
      muts: R.muts,
      host: host()
    };
  }

  function empty(wrap, head, text) {
    var box = el('div', 'evo-empty');
    box.appendChild(el('p', 'evo-empty-h', head));
    if (text) { box.appendChild(el('p', 'evo-empty-p', text)); }
    wrap.appendChild(box);
  }

  function chip(text, cls) { return el('span', 'evo-chip ' + (cls || ''), text); }

  function kindChip(g) { return chip(g.kind_name || 'Not sorted', 'evo-kind-' + (g.kind || 'none')); }

  function section(wrap, head, list, how) {
    if (!list || !list.length) { return; }
    if (head) {
      var h = el('h4', 'evo-sec-h', head + ' · ' + list.length);
      wrap.appendChild(h);
    }
    var ul = el('ul', 'evo-list');
    list.forEach(function (g) { ul.appendChild(row(g, how)); });
    wrap.appendChild(ul);
  }

  /* Whether a gene is on, as a switch: one press turns it off, or on, as Turn off, Turn on again
     and Keep do on its card; the server refuses what it cannot do, with why. A gene with no switch,
     and a replaced or removed version, whose switch is its newer version's or gone, has none. */
  function onSwitch(g, how) {
    if (g.on !== true && g.on !== false) { return null; }
    if (['replaced', 'removed', 'removing'].indexOf(g.state) >= 0) { return null; }
    var sw = button('evo-switch' + (g.on ? ' on' : ''), null, g.on ? 'Turn ' + g.name + ' off' : 'Turn ' + g.name + ' on');
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', g.on ? 'true' : 'false');
    sw.setAttribute('aria-label', g.name);
    sw.appendChild(el('span', 'evo-switch-track')).appendChild(el('span', 'evo-switch-knob'));
    sw.appendChild(el('span', 'evo-switch-word', g.on ? 'On' : 'Off'));
    sw.addEventListener('click', function (e) {
      e.stopPropagation();
      var what = g.on ? 'turn_off' : ['off', 'off_disuse', 'rejected'].indexOf(g.state) >= 0 ? 'turn_on' : 'keep';
      act(g, what, sw, how);
    });
    return sw;
  }

  function row(g, how) {
    var li = el('li', 'evo-row');
    li.dataset.gene = g.id;
    var b = button('evo-row-btn');
    b.setAttribute('aria-label', g.name + ', ' + g.kind_name + ', ' + g.state_name);
    var top = el('span', 'evo-row-top');
    top.appendChild(el('span', 'evo-row-name', g.name + (g.version > 1 ? ' · version ' + g.version : '')));
    top.appendChild(kindChip(g));
    if (g.flagged) { top.appendChild(chip('Mutated from the original', 'evo-warn')); }
    b.appendChild(top);
    if (g.sentence) { b.appendChild(el('span', 'evo-row-said', g.sentence)); }
    // Where in Rouh it changes, under what it does and above its trial (fr_a7af64799d94).
    if (g.place && PLACES[g.place] !== null) {
      b.appendChild(labelled('Where in Rouh', chip(placeWord(g.place), 'evo-quiet'), 'The part of Rouh it changes.'));
    }
    // Where it stands, said once; whether it is on is the switch beside it. No night: genes will
    // be built whenever Rouh is idle, so which night built one says nothing.
    // A gene off, kept or taken out says why in its verdict ("Turned off by you"), which then says
    // it alone rather than after its state ("Turned off · Turned off by you").
    // On trial: its day. Passed or Failed: its result, which says Passed or Failed and who decided.
    var sub = [g.result || g.state_name];
    if (g.trial_day && g.state === 'trial') { sub.push('day ' + Math.min(g.trial_day, g.trial_of) + ' of ' + g.trial_of); }
    // In New it is on trial too, but the list it is in says so; its row says how far its trial is.
    if (how && how.place === 'new' && g.trial_day) { sub = ['Day ' + Math.min(g.trial_day, g.trial_of) + ' of its ' + g.trial_of + '-day trial']; }
    b.appendChild(el('span', 'evo-row-sub', sub.join(' · ')));
    b.addEventListener('click', function () { openGene(g.id); });
    li.appendChild(b);
    var sw = onSwitch(g, how);
    if (sw) { li.appendChild(sw); }
    // In New a gene is answered on its row, with the answers its page has and Keep in trial.
    if (how && how.place === 'new') {
      li.classList.add('evo-row-new');
      li.appendChild(answers(g, how));
    }
    // No previous versions inside the row since 19 October 2026 (fr_a7af64799d94): they are in
    // the gene's Versions tab.
    return li;
  }

  /* One gene he had mutated: what it was, his words, and what it became once built. It opens
     the version it became, or the one he asked of while that is still being built. */
  function mutatedSection(wrap, list) {
    if (!list.length) { return; }
    wrap.appendChild(el('h4', 'evo-sec-h', 'Mutated · ' + list.length));
    var ul = el('ul', 'evo-list');
    list.forEach(function (r) {
      var li = el('li', 'evo-row');
      li.dataset.mutation = r.id;
      var b = button('evo-row-btn');
      b.setAttribute('aria-label', r.name + ', mutated, a minor reject');
      var top = el('span', 'evo-row-top');
      top.appendChild(el('span', 'evo-row-name', r.name + (r.to_version ? ' · version ' + r.from_version + ' to ' + r.to_version
                                                                         : ' · version ' + r.from_version)));
      top.appendChild(chip('Mutation, a minor reject', 'evo-quiet'));
      b.appendChild(top);
      b.appendChild(el('span', 'evo-row-said', '\u201c' + r.reason + '\u201d'));
      if (r.before) { b.appendChild(labelled('Was', el('span', 'evo-row-said', r.before))); }
      if (r.after) { b.appendChild(labelled('Became', el('span', 'evo-row-said', r.after))); }
      b.appendChild(el('span', 'evo-row-sub', [reqWords(r), r.when].filter(Boolean).join(' · ')));
      b.addEventListener('click', function () { openGene(r.result_gene_id || r.gene_id); });
      li.appendChild(b);
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
  }

  /* Each says whether it waits on him: only a built version he has not answered does. Landing
     is the run's own last step, so built and landed read the same to him. */
  var REQ_WORDS = { requested: 'Not started yet', building: 'Being built now', built: 'Built',
                    landed: 'Built', withdrawn: 'Withdrawn', failed: 'Could not be built' };

  function reqWords(r) {
    if (r.result_waiting) { return 'Built: waiting for your review'; }
    // A request a night took, rather than its own run, is built that night.
    return r.status === 'building' && r.night ? 'Being built tonight' : (REQ_WORDS[r.status] || r.status);
  }

  /* `here` is the gene whose page it is on: a request that built this very version says so
     rather than linking to the page already open. */
  function requestRow(r, here) {
    var li = el('li', 'evo-req');
    var top = el('div', 'evo-row-top');
    top.appendChild(chip(reqWords(r), r.result_waiting ? 'evo-state-candidate' : 'evo-req-' + r.status));
    li.appendChild(top);
    li.appendChild(el('blockquote', 'evo-words', r.words));
    var sub = 'Asked ' + r.made_words + (r.outcome ? ' · ' + r.outcome : '');
    li.appendChild(el('p', 'evo-row-sub', sub));
    if (r.result_gene && r.result_gene === here) {
      li.appendChild(el('p', 'evo-row-sub', 'It built this version.'));
    } else if (r.result_gene && r.result_waiting) {
      li.appendChild(link('Review version ' + r.result_version, '/evolution/mutations/gene/' + r.result_gene,
        'ctl small primary'));
    } else if (r.result_gene) {
      li.appendChild(link('Open version it built', '/evolution/mutations/gene/' + r.result_gene, 'evo-link'));
    } else if (r.run && r.status === 'building' && !r.night) {
      li.appendChild(link('Follow its run', '/run/' + encodeURIComponent(r.run), 'evo-link'));
    }
    if (r.status === 'requested') {
      var acts = el('div', 'evo-acts');
      var start = button('ctl small primary', 'Start now');
      start.addEventListener('click', function () {
        start.disabled = true;
        call('/mutations/' + r.id, { start: true }).then(function (j) { R.said = j.said; load(); },
          function (err) { start.disabled = false; fail(err); });
      });
      acts.appendChild(start);
      var change = button('ctl small', 'Change');
      change.addEventListener('click', function () {
        acts.hidden = true;
        var box = mutateBox(r.words, 'Save the change', function (words) {
          return call('/mutations/' + r.id, { words: words });
        }, null, 'Saving changes only the words. Start now then builds them; the new version then takes this one’s place, on trial.');
        box.onGone = function () { acts.hidden = false; };
        li.appendChild(box);
        box.querySelector('textarea').focus();
      });
      acts.appendChild(change);
      var drop = button('ctl small', 'Withdraw');
      drop.addEventListener('click', function () {
        drop.disabled = true;
        call('/mutations/' + r.id, { withdraw: true }).then(function (j) { R.said = j.said; load(); }, fail);
      });
      acts.appendChild(drop);
      li.appendChild(acts);
    }
    return li;
  }

  function fail(err) {
    R.said = String((err && err.message) || err);
    draw();
  }

  /* ---- one gene, on its own page ----

     fr_44acd06b1e00 (19 October 2026, after fr_2d2b3726ebb0's one long page): its name with its
     switch at the right, the answers, then four tabs - Essence, Trial, Versions and History - and
     only the one picked, in one card whose text wraps within its width (fr_5654dc340c44), with
     Questions at the bottom of it under every tab. */

  function drawGene(wrap) {
    var p = R.gene;
    // Back to the list it is in: New, On trial, Passed, Rejected or Not used.
    var group = p && p.card && ['new', 'passed', 'rejected', 'unused'].indexOf(p.card.group) >= 0 ? p.card.group : 'trial';
    var back = link('← ' + viewName(group), '/evolution/mutations/' + group, 'evo-back');
    wrap.appendChild(back);
    if (!p) { wrap.appendChild(el('p', 'evo-loading', 'Reading the gene…')); return; }
    if (p.missing) { wrap.appendChild(el('p', 'evo-error', p.missing)); return; }
    var c = p.card;
    if (host().moved && c) { host().moved('mutations', R.sub, c.name); }
    // fr_44acd06b1e00: the name on one line with its switch at the right edge of it; then the
    // answers, so they are there whichever tab is open; then the tabs, the one picked, and
    // Questions under every tab. Whether its trial is on is said once, on the Trial tab, not in
    // a tag beside the name as well (Petar, 19 October 2026).
    var head = el('div', 'evo-gene-head');
    var name = el('div', 'evo-gene-title');
    name.appendChild(el('h4', 'evo-gene-name', c.name + (c.version > 1 ? ' · version ' + c.version : '')));
    head.appendChild(name);
    var sw = onSwitch(c);
    if (sw) { head.appendChild(sw); }
    wrap.appendChild(head);
    var stands = geneStanding(c, p);
    if (stands) { wrap.appendChild(stands); }
    if (R.said) { wrap.appendChild(el('p', 'evo-said', R.said)); }
    var how = { place: 'gene', page: p };
    wrap.appendChild(answers(c, how));
    var tabs = el('div', 'evo-views evo-gene-tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Parts of ' + c.name);
    GENE_TABS.forEach(function (t, i) {
      var on = R.tab === t[0];
      var b = button('evo-vtab' + (on ? ' on' : ''), t[1]);
      b.setAttribute('role', 'tab');
      b.id = 'evoGeneTab-' + t[0];
      b.setAttribute('aria-controls', 'evoGenePanel');
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      if (t[0] === 'versions' && earlier(p)) {
        // How many versions there are besides the latest, as a badge (Petar, 19 October 2026).
        b.appendChild(el('span', 'evo-count', earlier(p)));
        b.setAttribute('aria-label', 'Versions, ' + earlier(p) + ' before the latest');
      }
      if (t[0] === 'trial') {
        // The Trial tab says whether the trial runs: a green dot and On, or a grey one and Off.
        var running = c.state === 'trial';
        var mark = el('span', 'evo-tab-state' + (running ? ' on' : ''));
        mark.appendChild(el('span', 'evo-tab-dot'));
        mark.appendChild(words(running ? 'On' : 'Off'));
        b.appendChild(mark);
        b.setAttribute('aria-label', 'Trial, ' + (running ? 'on' : 'off'));
      }
      b.addEventListener('click', function () { geneTab(t[0]); });
      // Arrow keys move between the tabs, as in any tab list.
      b.addEventListener('keydown', function (e) {
        var step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        if (!step) { return; }
        e.preventDefault();
        geneTab(GENE_TABS[(i + step + GENE_TABS.length) % GENE_TABS.length][0]);
      });
      tabs.appendChild(b);
    });
    wrap.appendChild(tabs);
    var box = el('article', 'evo-card' + (c.flagged ? ' flagged' : ''));
    box.setAttribute('aria-label', c.name);
    var panel = el('div', 'evo-gene-panel');
    panel.id = 'evoGenePanel';
    panel.setAttribute('role', 'tabpanel');
    fillTab(panel, p);
    box.appendChild(panel);
    box.appendChild(questionsSection(c, p));
    wrap.appendChild(box);
    var to = R.focus && wrap.querySelector('[data-part~="' + R.focus + '"]');
    R.focus = '';
    if (to) { requestAnimationFrame(function () { to.scrollIntoView({ block: 'start' }); }); }
  }

  /* How this gene is doing, at the top of its page whichever tab is open (journey 5): on trial,
     day X of Y and its uses so far of those needed, with a bar of its days; ended, its one result;
     and whether a change he asked for is on its way. The Trial tab keeps the same and its settings. */
  function geneStanding(c, p) {
    var t = (p.learning || {}).trial || {};
    if (!t.on_trial && !t.outcome_said && !c.result && !c.request) { return null; }
    var box = el('div', 'evo-standing');
    box.setAttribute('role', 'status');
    var line = el('p', 'evo-standing-h');
    if (t.on_trial) {
      var day = Math.min(t.day || 1, t.of || t.days || 1), of = t.of || t.days || 1;
      line.appendChild(el('strong', null, (c.reviewed ? 'On trial' : 'New, on trial') + ' \u00b7 day ' + day + ' of ' + of));
      if (t.needed) { line.appendChild(words(' \u00b7 ' + (t.uses || 0) + ' of ' + t.needed + (t.needed === 1 ? ' use' : ' uses'))); }
      if (t.ends_words) { line.appendChild(el('span', 'evo-standing-sub', ' \u00b7 ends ' + t.ends_words)); }
      box.appendChild(line);
      if (of <= 60) {
        var days = el('div', 'evo-days');
        days.setAttribute('aria-hidden', 'true');
        days.style.gridTemplateColumns = 'repeat(' + of + ', minmax(0, 1fr))';
        for (var i = 1; i <= of; i++) { days.appendChild(el('i', i <= day ? 'past' : '')); }
        box.appendChild(days);
      }
      if (t.extended && t.outcome_said) { box.appendChild(el('p', 'evo-standing-sub', t.outcome_said)); }
    } else {
      // A rejected gene's reason is in its Rejected box just below, so it is said there only.
      line.appendChild(el('strong', null, c.rejected ? 'Failed: you rejected it' : (t.outcome_said || c.result || c.state_name)));
      if (t.ended_words) { line.appendChild(el('span', 'evo-standing-sub', ', ' + t.ended_words)); }
      box.appendChild(line);
    }
    if (c.request) {
      box.appendChild(el('p', 'evo-standing-sub', c.request.status === 'requested'
        ? 'Your change has not started. Start it now in Versions.'
        : 'Your change is being built now. When it is built, the new version takes this one\u2019s place, on trial.'));
    }
    return box;
  }

  /* The labels that say how Petar uses the gene and the part of Rouh it touches, then a warning
     box of its own only when the mutation check found a difference, and where a rejection stands.
     At the top of a gene's Essence tab. */
  function cardHead(box, c) {
    // Each label says what it is (fr_fa2525969751). Which version it builds on is in its name
    // and in Versions.
    var top = el('div', 'evo-card-top');
    top.appendChild(labelled('How you use it', kindChip(c), kindSaid(c.kind)));
    if (c.place && PLACES[c.place] !== null) {
      top.appendChild(labelled('Where in Rouh', chip(placeWord(c.place), 'evo-quiet'), 'The part of Rouh it changes.'));
    }
    box.appendChild(top);
    if (c.flagged) {
      var warn = el('div', 'evo-warnbox');
      warn.setAttribute('role', 'note');
      warn.appendChild(el('strong', null, 'Mutated from the original'));
      warn.appendChild(el('p', null, c.check.said));
      box.appendChild(warn);
    }
    if (c.rejected && c.verdict) {
      // fr_5654dc340c44: Reject takes the code out, so the box says where that stands too.
      var no = el('div', 'evo-rejected');
      no.setAttribute('role', 'note');
      no.appendChild(el('strong', null, 'Rejected' + (c.answered_words ? ', ' + c.answered_words : '')));
      no.appendChild(el('p', null, c.verdict.replace(/^Rejected: /, '')));
      no.appendChild(el('p', 'evo-rejected-code', c.state === 'removing' ? 'Its code is being taken out of Rouh, then deployed.'
        : c.state === 'removed' ? 'Its code was taken out of Rouh.'
        : 'Its code is still in: the run that takes it out did not start. Reject again to try once more.'));
      box.appendChild(no);
    }
    if (c.kept_reason) {
      // fr_c1aa7f60359d: why he kept it, in his words, as the rejected box says why not.
      var yes = el('div', 'evo-kept-why');
      yes.setAttribute('role', 'note');
      yes.appendChild(el('strong', null, 'Kept' + (c.kept_reason.words ? ', ' + c.kept_reason.words : '')));
      yes.appendChild(el('p', null, c.kept_reason.reason));
      box.appendChild(yes);
    }
    if (c.sentence) { box.appendChild(el('p', 'evo-card-said', c.sentence)); }
  }

  /* Essence: what the gene does and how you use it - its labels, its one sentence, its moment
     and how, the outside services it brought in, and See it in use. */
  function essenceTab(box, p) {
    var c = p.card, l = p.learning || {};
    cardHead(box, c);
    var facts = el('dl', 'evo-facts');
    function fact(k, v) { if (!v) { return; } facts.appendChild(el('dt', null, k)); facts.appendChild(el('dd', null, v)); }
    fact('When', l.moment || (c.kind === 'ask_for' ? 'No “when” sentence was written for it.' : ''));
    fact('How', l.words);
    if (c.kind === 'ask_for') {
      fact('Offered at its moment', l.offerable ? 'Yes: Rouh may offer it in one line when its moment comes, at most three offers a day.' : 'No.');
    }
    if (facts.firstChild) { box.appendChild(facts); }
    var brought = geneServices(p);
    if (brought) { box.appendChild(brought); }
    box.appendChild(seeItInUse(c));
  }

  var PLACES = { brief: 'Morning brief', decisions: 'Decisions', memory: 'Memory', pages: 'Task pages',
                 meetings: 'Meetings', mail: 'Mail', chat: 'Chats', none: null };
  function placeWord(p) { return PLACES[p] || (p.charAt(0).toUpperCase() + p.slice(1)); }

  /* A grey label before a value, and on hover what it means: "How you use it: You ask for it". */
  function labelled(label, value, said) {
    var span = el('span', 'evo-labelled');
    span.appendChild(el('span', 'evo-label', label + ':'));
    span.appendChild(value);
    if (said) { span.title = said; }
    return span;
  }

  function kindSaid(k) {
    var kinds = (R.muts && R.muts.kinds) || (R.params && R.params.kinds) || [];
    for (var i = 0; i < kinds.length; i += 1) { if (kinds[i].id === k) { return kinds[i].said; } }
    return '';
  }

  var LISTS = [['reads', 'Reads'], ['changes', 'Changes'], ['sends', 'Sends'], ['jobs', 'On a schedule'], ['accounts', 'Outside accounts']];

  function compare(c) {
    var o = c.original || {}, v = c.observed || {}, check = c.check || {};
    var diff = {};
    (check.differences || []).forEach(function (d) { diff[d.list + '\u0000' + d.item] = true; });
    var grid = el('div', 'evo-compare');
    function side(title, sub, data, said, observed) {
      var col = el('div', 'evo-side' + (observed ? ' observed' : ''));
      col.appendChild(el('p', 'evo-side-h', title));
      col.appendChild(el('p', 'evo-side-sub', sub));
      if (said) { col.appendChild(el('p', 'evo-side-said', said)); }
      var any = false;
      LISTS.forEach(function (l) {
        var items = data[l[0]] || [];
        if (!items.length) { return; }
        any = true;
        var p = el('p', 'evo-side-list');
        p.appendChild(el('span', 'evo-k', l[1]));
        items.forEach(function (it, i) {
          var span = el('span', observed && diff[l[0] + '\u0000' + it] ? 'evo-diff' : '', it);
          if (i) { p.appendChild(document.createTextNode(', ')); }
          p.appendChild(span);
        });
        col.appendChild(p);
      });
      if (!any && !said) { col.appendChild(el('p', 'evo-side-none', observed ? 'Nothing was observed from its test install.' : 'Nothing written down.')); }
      return col;
    }
    grid.appendChild(side('Original gene', 'what it says it does', o, o.does, false));
    grid.appendChild(side('Mutated version for us', 'what it did in its test install', v, v.did, true));
    var out = el('div', 'evo-compare-wrap');
    out.appendChild(grid);
    // A flagged gene says so once, in its warning box above; the others say what the check found.
    if (check.status === 'mutated') { return out; }
    var verdict = el('p', 'evo-check evo-check-' + (check.status || 'unchecked'));
    verdict.appendChild(el('strong', null, check.status === 'same' ? '✓ No mutation from the original'
      : check.status === 'mutated' ? '⚠ Mutated from the original' : 'Not checked'));
    verdict.appendChild(document.createTextNode(' ' + (check.said || 'The mutation check has not run on this gene.')));
    out.appendChild(verdict);
    return out;
  }

  function answers(c, how) {
    var wrap = el('div', 'evo-answers');
    var lines = c.answers || {};
    var acts = el('div', 'evo-acts');
    var said = el('ul', 'evo-answer-lines');
    // On the gene's own page and on a row in New each answer stands alone, as Petar asked
    // (fr_2d2b3726ebb0): what it does is only on hover.
    var under = how && (how.place === 'gene' || how.place === 'new') ? el('ul') : said;
    function add(label, what, line, cls) {
      var b = button('ctl small' + (cls ? ' ' + cls : ''), label, line);
      b.addEventListener('click', function () { act(c, what, b, how); });
      acts.appendChild(b);
      answerLine(under, label, line);
      return b;
    }
    // Every answer is his deciding over what the trial would (Petar, 18 October 2026: "I should
    // be able to jump in and look at things and decide and overwrite"), and the result says so.
    // Turning it off is its switch's, in the gene's head and on its row.
    if (c.state === 'trial') {
      if (c.flagged) {
        keepButton(acts, under, c, 'Keep with the mutation', 'keep_mutation', lines.keep, how);
        add('Keep the original', 'keep_original', lines.keep_original);
      } else {
        keepButton(acts, under, c, 'Keep', 'keep', lines.keep, how);
      }
      // A gene he has not decided anything about yet is in New, and Keep in trial moves it to On
      // trial as it is (Petar, 19 October 2026).
      if (!c.reviewed) { add('Keep in trial', 'keep_trial', lines.keep_trial); }
      rejectButton(acts, under, c, lines.reject, how);
      add('Restart trial', 'restart', lines.restart, 'evo-act-more');
      mutateButton(acts, under, c, lines.mutate, how);
    } else if (c.state === 'kept') {
      add('Restart trial', 'restart', lines.restart, 'evo-act-more');
      rejectButton(acts, under, c, lines.reject, how);
      mutateButton(acts, under, c, lines.mutate, how);
    } else if (c.state === 'off' || c.state === 'off_disuse' || c.state === 'rejected') {
      add('Turn on again', 'turn_on', lines.turn_on, 'primary');
      add('Restart trial', 'restart', lines.restart, 'evo-act-more');
      // A rejected gene still here has its code in: its run did not start, and Reject tries again.
      rejectButton(acts, under, c, lines.reject, how);
      mutateButton(acts, under, c, lines.mutate, how);
    }
    // Petar, 15 October 2026: "Mutation should start right away". While his change is built the
    // gene stays as it is; the new version then takes its place, on trial.
    if (c.request && !(how && how.place === 'gene')) {
      said.appendChild(el('li', null, c.request.status === 'requested'
        ? 'Your change has not started. Start it now in Versions.'
        : 'Your change is being built now. When it is built, the new version takes this one’s place, on trial. Follow it in Versions.'));
    }
    // A gene whose code was taken out, or is being, has nothing left to answer; its page says so
    // rather than showing no answers at all.
    if (!acts.firstChild && (c.state === 'removed' || c.state === 'removing')) {
      wrap.appendChild(el('p', 'evo-hint', c.state === 'removed'
        ? 'Its code was taken out of Rouh, so it cannot be turned on again. To have something like it, ask for it in a chat or the Incubator.'
        : 'Its code is being taken out of Rouh. Nothing can be done with it until that run ends.'));
      return wrap;
    }
    wrap.appendChild(acts);
    if (said.firstChild) { wrap.appendChild(said); }
    return wrap;
  }

  /* An answer's line, under its button where lines are shown; its button carries it on hover. */
  function answerLine(list, label, line) {
    if (!line) { return; }
    var li = el('li');
    li.appendChild(el('strong', null, label + ': '));
    li.appendChild(document.createTextNode(line));
    list.appendChild(li);
  }

  /* Keep: opens a box for why he keeps it, which he may leave empty (fr_c1aa7f60359d: "When I
     press keep on the gene trial, I can be given input. This way I can add positive signal why I
     decided to keep it"). The reason is shown on the gene's card and every night weighs it. */
  function keepButton(acts, said, c, label, what, line, how) {
    var b = button('ctl small primary', label, line);
    b.addEventListener('click', function () {
      var holder = acts.parentNode;
      var open = holder.querySelector('.evo-keep');
      if (open) { open.querySelector('textarea').focus(); return; }
      holder.appendChild(keepBox(c, what, how));
      holder.querySelector('.evo-keep textarea').focus(); holder.lastChild.scrollIntoView({ block: 'nearest' });
    });
    acts.appendChild(b);
    answerLine(said, label, line);
  }

  function keepBox(c, what, how) {
    var box = el('div', 'evo-mutate evo-keep');
    var lab = el('label', 'evo-k', 'Why do you keep it? Your own words, if you like.');
    var ta = el('textarea', 'evo-text');
    ta.rows = 3;
    ta.maxLength = 1000;
    ta.id = 'evoKeep' + Math.random().toString(36).slice(2, 8);
    lab.htmlFor = ta.id;
    box.appendChild(lab);
    box.appendChild(ta);
    var err = el('p', 'evo-error');
    var acts = el('div', 'evo-acts');
    var save = button('ctl small primary', 'Keep it');
    function keep() {
      save.disabled = true;
      call('/genes/' + c.id + '/answer', { answer: what, reason: ta.value.trim() }).then(function (j) {
        if (how && how.done) { how.done(c, j); return; }
        R.said = j.said;
        load();
      }, function (e) { save.disabled = false; err.textContent = String((e && e.message) || e); });
    }
    save.addEventListener('click', keep);
    var cancel = button('ctl small', 'Cancel');
    cancel.addEventListener('click', function () { box.remove(); });
    ta.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); box.remove(); }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); keep(); }
    });
    acts.appendChild(save);
    acts.appendChild(cancel);
    box.appendChild(acts);
    box.appendChild(err);
    return box;
  }

  /* Reject…: says no to a gene with a reason, which it then shows and the nights weigh before
     choosing what to build (fr_509a4e1d7867), and takes its code out (fr_5654dc340c44: "Reject
     should delete the code"). Not the same as Turn off, which keeps it as it was. */
  function rejectButton(acts, said, c, line, how) {
    var b = button('ctl small evo-act-more', 'Reject…', line);
    b.addEventListener('click', function () {
      var holder = acts.parentNode;
      var open = holder.querySelector('.evo-reject');
      if (open) { open.querySelector('textarea').focus(); return; }
      holder.appendChild(rejectBox(c, how));
      holder.querySelector('.evo-reject textarea').focus(); holder.lastChild.scrollIntoView({ block: 'nearest' });
    });
    acts.appendChild(b);
    answerLine(said, 'Reject', line);
  }

  function rejectBox(c, how) {
    var box = el('div', 'evo-mutate evo-reject');
    var lab = el('label', 'evo-k', 'Why do you reject it? Your own words.');
    var ta = el('textarea', 'evo-text');
    ta.rows = 3;
    ta.maxLength = 1000;
    ta.id = 'evoRej' + Math.random().toString(36).slice(2, 8);
    lab.htmlFor = ta.id;
    if (c.state === 'rejected' && c.verdict) { ta.value = c.verdict.replace(/^Rejected: /, ''); }
    box.appendChild(lab);
    box.appendChild(ta);
    box.appendChild(el('p', 'evo-hint', 'Rejecting switches it off and starts a run that takes its code out of Rouh and deploys' +
      ', cancelling any outside service it brought in. Its card and your words stay here.'));
    var err = el('p', 'evo-error');
    var acts = el('div', 'evo-acts');
    var save = button('ctl small danger', 'Reject it');
    save.addEventListener('click', function () {
      if (ta.value.trim().split(/\s+/).length < 2) { err.textContent = 'Say in a few words why you reject it.'; return; }
      save.disabled = true;
      call('/genes/' + c.id + '/answer', { answer: 'reject', reason: ta.value.trim() }).then(function (j) {
        if (how && how.done) { how.done(c, j); return; }
        R.said = j.said;
        load();
      }, function (e) { save.disabled = false; err.textContent = String((e && e.message) || e); });
    });
    var cancel = button('ctl small', 'Cancel');
    cancel.addEventListener('click', function () { box.remove(); });
    ta.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); box.remove(); } });
    acts.appendChild(save);
    acts.appendChild(cancel);
    box.appendChild(acts);
    box.appendChild(err);
    return box;
  }

  function bookControl(acts, said, c, how, line) {
    var t = el('input', 'evo-when-pick');
    t.type = 'datetime-local';
    t.setAttribute('aria-label', 'When to try ' + c.name + ' for ten minutes');
    var soon = new Date(Date.now() + 86400000);
    soon.setHours(10, 0, 0, 0);
    t.value = new Date(soon.getTime() - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    acts.appendChild(t);
    var b = button('ctl small primary', 'Book ten minutes', line);
    b.addEventListener('click', function () {
      var at = new Date(t.value).getTime();
      if (!t.value || !isFinite(at)) { R.said = 'Pick when to try it.'; draw(); return; }
      act(c, 'book', b, how, { at: at / 1000 });
    });
    acts.appendChild(b);
    answerLine(said, 'Book ten minutes', line);
  }

  function mutateButton(acts, said, c, line, how) {
    var b = button('ctl small evo-act-more', 'Mutate…', line);
    b.addEventListener('click', function () {
      var holder = acts.parentNode;
      if (holder.querySelector('.evo-mutate')) { holder.querySelector('textarea').focus(); return; }
      var box = mutateBox('', 'Start the mutation', function (words) {
        return call('/genes/' + c.id + '/mutate', { words: words });
      }, how, null, c);
      holder.appendChild(box);
      box.querySelector('textarea').focus();
      box.scrollIntoView({ block: 'nearest' });
    });
    acts.appendChild(b);
    answerLine(said, 'Mutate', line);
  }

  function mutateBox(words, label, send, how, hint, c) {
    var box = el('div', 'evo-mutate');
    var lab = el('label', 'evo-k', 'How should it change for you? Your own words.');
    var ta = el('textarea', 'evo-text');
    ta.rows = 3;
    ta.maxLength = 2000;
    ta.value = words || '';
    var id = 'evoMut' + Math.random().toString(36).slice(2, 8);
    ta.id = id;
    lab.htmlFor = id;
    box.appendChild(lab);
    box.appendChild(ta);
    var err = el('p', 'evo-error');
    var acts = el('div', 'evo-acts');
    var save = button('ctl small primary', label);
    save.addEventListener('click', function () {
      if (ta.value.trim().split(/\s+/).length < 2) { err.textContent = 'Say in a few words how it should change.'; return; }
      save.disabled = true;
      send(ta.value.trim()).then(function (j) {
        if (c && how && how.done) { how.done(c, j); return; }
        R.said = j.said || 'Saved.';
        load();
      }, function (e) { save.disabled = false; err.textContent = String((e && e.message) || e); });
    });
    var cancel = button('ctl small', 'Cancel');
    // A row whose buttons made way for the box gets them back (`box.onGone`).
    function gone() { box.remove(); if (box.onGone) { box.onGone(); } }
    cancel.addEventListener('click', gone);
    ta.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); gone(); } });
    acts.appendChild(save);
    acts.appendChild(cancel);
    box.appendChild(acts);
    box.appendChild(err);
    box.appendChild(el('p', 'evo-hint', hint || 'A run starts building it at once, checked against the original, and the new version takes this one’s place, on trial.'));
    return box;
  }

  function act(c, what, b, how, more) {
    b.disabled = true;
    var body = { answer: what };
    if (more) { Object.keys(more).forEach(function (k) { body[k] = more[k]; }); }
    call('/genes/' + c.id + '/answer', body).then(function (j) {
      if (how && how.done) { how.done(c, j); return; }
      R.said = j.said;
      load();
    }, function (err) { b.disabled = false; fail(err); });
  }

  /* Ask a question, answered right on the card by Rouh, from the gene's own record, with
     follow-ups in the same topic; the topics are kept under Questions on the gene's own page. */
  function askBox(c, how) {
    var box = el('div', 'evo-ask');
    // Under Questions on the gene's own page that heading says it, and only a new question after
    // earlier ones is named.
    var label = how.place === 'gene' ? how.label : 'Ask a question';
    if (label) { box.appendChild(el('p', 'evo-k', label)); }
    var log = el('div', 'evo-ask-log');
    box.appendChild(log);
    var topic = how.topic || 0;
    if (how.turns) {
      how.turns.forEach(function (t) { log.appendChild(turn(t.question, t.answer)); });
    }
    var ta = el('textarea', 'evo-text');
    ta.rows = 2;
    ta.maxLength = 2000;
    ta.placeholder = topic ? 'Ask a follow-up' : 'Does it send anything? What does it read?';
    ta.setAttribute('aria-label', topic ? 'Ask a follow-up about ' + c.name : 'Ask a question about ' + c.name);
    box.appendChild(ta);
    var acts = el('div', 'evo-acts');
    var ask = button('ctl small', topic ? 'Ask the follow-up' : 'Ask');
    var err = el('p', 'evo-error');
    ask.addEventListener('click', function () {
      var q = ta.value.trim();
      if (!q) { err.textContent = 'Ask something first.'; return; }
      ask.disabled = true;
      ta.disabled = true;
      err.textContent = '';
      var pending = turn(q, null);
      log.appendChild(pending);
      call('/genes/' + c.id + '/ask', { question: q, topic: topic || null }).then(function (j) {
        pending.replaceWith(turn(j.question, j.answer));
        topic = j.topic;
        ta.value = '';
        ta.disabled = false;
        ask.disabled = false;
        ask.textContent = 'Ask the follow-up';
        ta.placeholder = 'Ask a follow-up';
        ta.focus();
      }, function (e) {
        pending.remove();
        ta.disabled = false;
        ask.disabled = false;
        err.textContent = String((e && e.message) || e);
      });
    });
    ta.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); ask.click(); }
    });
    acts.appendChild(ask);
    box.appendChild(acts);
    box.appendChild(err);
    return box;
  }

  /* One question and its answer, as the conversation's own bubbles (`.turn` in app.css): the
     question on the right in the person's tint, the answer on the left in Rouh's, both drawn as
     Markdown by the conversation's own renderer (fr_24e65b501ddb). While the answer is worked
     on it is the conversation's three dots. */
  function turn(q, a) {
    var t = el('div', 'evo-turn');
    t.appendChild(bubble('user', q));
    if (a == null) {
      var wait = el('div', 'turn assistant typing');
      var dots = el('div', 'turn-body');
      dots.setAttribute('aria-label', 'Rouh is reading the gene’s record');
      for (var i = 0; i < 3; i++) { dots.appendChild(el('span', 'dot')); }
      wait.appendChild(dots);
      t.appendChild(wait);
    } else {
      t.appendChild(bubble('assistant', a));
    }
    return t;
  }

  function bubble(who, words) {
    var b = el('div', 'turn ' + who);
    var body = el('div', 'turn-body rendered');
    var text = el('div', 'b-text');
    var draw = host().markdown;
    if (typeof draw === 'function') { text.innerHTML = draw(String(words || '')); }
    else { text.textContent = String(words || ''); }
    body.appendChild(text);
    b.appendChild(body);
    return b;
  }

  /* See it in use: the screenshots in a row that slides sideways, each opening full screen on a
     press, where it zooms and pans as a photo does (fr_5654dc340c44). A plain part with its
     heading, never a fold (Petar, 18 October
     2026: "Don't use toggle that is always open"). */
  function seeItInUse(c) {
    var d = part('See it in use', 'use');
    var shots = c.screenshots || [];
    if (shots.length) {
      var pics = shots.map(function (p, i) {
        return { src: '/workspace/' + p.split('/').map(encodeURIComponent).join('/'),
                 name: p.split('/').pop().replace(/\.png$/i, '').replace(/[-_]/g, ' '),
                 alt: c.name + ', screenshot ' + (i + 1) + ' of ' + shots.length };
      });
      var strip = el('div', 'evo-shots');
      pics.forEach(function (pic, i) {
        var fig = el('figure', 'evo-shot');
        var open = button('evo-shot-open');
        open.setAttribute('aria-label', 'See screenshot ' + (i + 1) + ' of ' + pics.length + ' full screen: ' + pic.name);
        var img = el('img');
        img.loading = 'lazy';
        img.alt = pic.alt;
        img.src = pic.src;
        open.appendChild(img);
        open.addEventListener('click', function () { viewPictures(pics, i); });
        fig.appendChild(open);
        fig.appendChild(el('figcaption', null, pic.name));
        strip.appendChild(fig);
      });
      d.appendChild(strip);
    } else {
      d.appendChild(el('p', 'evo-hint', 'No screenshot was taken.'));
    }
    var steps = c.steps || [];
    if (steps.length) {
      d.appendChild(el('p', 'evo-k', 'If you have it, step by step'));
      var ol = el('ol', 'evo-steps');
      steps.forEach(function (t) { ol.appendChild(el('li', null, t)); });
      d.appendChild(ol);
    }
    return d;
  }

  /* One picture at a time, full screen, over everything and changing nothing behind it
     (fr_5654dc340c44: "a full screen zoomable version that I can easily and natively look at in
     details without breaking the layout behind. Then an obvious close button that would return to
     the card"). A modal <dialog>, so it is in the top layer above Rouh's own chrome, the page
     behind stays exactly where it was, and Escape and Close give focus back to the picture
     pressed. Two fingers pinch and move it, one finger moves it once zoomed and swipes to the next
     picture when it is not, a double tap or double click zooms in and out at that spot, and on a
     desk the wheel zooms, the arrows step and 0 fits it again. */
  function viewPictures(pics, at) {
    var dlg = el('dialog', 'evo-viewer');
    dlg.setAttribute('aria-label', 'Screenshots, full screen');
    var stage = el('div', 'evo-viewer-stage');
    var missing = el('p', 'evo-viewer-missing', 'This screenshot could not be loaded.');
    missing.hidden = true;
    dlg.appendChild(stage);
    var close = button('evo-viewer-close', 'Close');
    close.setAttribute('aria-label', 'Close the picture and go back to the card');
    dlg.appendChild(close);
    var prev = button('evo-viewer-step prev', '‹');
    prev.setAttribute('aria-label', 'Previous screenshot');
    var next = button('evo-viewer-step next', '›');
    next.setAttribute('aria-label', 'Next screenshot');
    var foot = el('div', 'evo-viewer-foot');
    var caption = el('p', 'evo-viewer-caption');
    foot.appendChild(caption);
    if (pics.length > 1) { dlg.appendChild(prev); dlg.appendChild(next); }
    dlg.appendChild(foot);

    /* Three pictures lie side by side, GAP apart, as in a phone's photos (fr_be8b4c59aa0d: a swipe
       that "gives up and returns" while the picture changed anyway). The one shown is `img`; the
       ones before and after it wait just off either edge, so a finger drags all three together and
       what the slide shows on release is what happens: past a third of the width, or flicked, it
       carries on to the next one, and otherwise it springs back. There is no wrapping round: at
       either end the drag pulls like a rubber band and springs back. */
    var GAP = 24;
    function slot() {
      var s = el('img', 'evo-viewer-img');
      s.draggable = false;
      s.style.visibility = 'hidden';
      s.addEventListener('load', function () {
        s._bad = false;
        fitSlot(s);
        s.style.visibility = '';
        if (s === img) { fit(); } else { paint(slid); }
      });
      s.addEventListener('error', function () {
        s._bad = true;
        s._fit = null;
        s.style.visibility = 'hidden';
        if (s === img) { v.w = 0; v.h = 0; v.z = 1; missing.hidden = false; dlg.classList.remove('zoomed'); }
      });
      stage.appendChild(s);
      return s;
    }
    var before = slot(), img = slot(), after = slot();
    stage.appendChild(missing);

    // The shown picture fits the stage at zoom 1: base is its fitted size, z the zoom on top, x and
    // y where its top left corner is, in the stage's pixels. `slid` is how far the row is dragged.
    var v = { base: 1, w: 0, h: 0, z: 1, x: 0, y: 0, most: 4 }, slid = 0;
    function size() { var r = stage.getBoundingClientRect(); return { W: r.width, H: r.height }; }
    function clamp() {
      var S = size(), w = v.w * v.z, h = v.h * v.z;
      v.x = w <= S.W ? (S.W - w) / 2 : Math.min(0, Math.max(S.W - w, v.x));
      v.y = h <= S.H ? (S.H - h) / 2 : Math.min(0, Math.max(S.H - h, v.y));
    }
    function fitSlot(s) {
      if (!s.naturalWidth || s._bad) { s._fit = null; return; }
      var S = size(), nw = s.naturalWidth, nh = s.naturalHeight || 1;
      var base = Math.min(S.W / nw, S.H / nh), w = nw * base, h = nh * base;
      s.style.width = w + 'px';
      s.style.height = h + 'px';
      s._fit = { base: base, w: w, h: h, x: (S.W - w) / 2, y: (S.H - h) / 2 };
    }
    function paint(slide) {
      slid = slide || 0;
      var W = size().W;
      img.style.transform = 'translate3d(' + (v.x + slid) + 'px,' + v.y + 'px,0) scale(' + v.z + ')';
      missing.style.transform = 'translate3d(' + slid + 'px,-50%,0)';
      [[before, -1], [after, 1]].forEach(function (p) {
        var f = p[0]._fit;
        if (f) { p[0].style.transform = 'translate3d(' + (f.x + slid + p[1] * (W + GAP)) + 'px,' + f.y + 'px,0)'; }
      });
      dlg.classList.toggle('zoomed', v.z > 1.01);
    }
    function fit() {
      fitSlot(img);
      var f = img._fit;
      if (!f) { return; }
      v.base = f.base; v.w = f.w; v.h = f.h;
      // Up to twice its own pixels, and never less than four times the fitted size.
      v.most = Math.max(4, 2 / v.base);
      v.z = 1;
      clamp();
      paint();
    }
    function zoomAt(z, px, py) {
      if (!v.w) { return; }
      z = Math.max(1, Math.min(v.most, z));
      var ix = (px - v.x) / v.z, iy = (py - v.y) / v.z;
      v.z = z;
      v.x = px - ix * z;
      v.y = py - iy * z;
      clamp();
      paint();
    }
    function glide(fn) {
      img.classList.add('glide');
      fn();
      setTimeout(function () { img.classList.remove('glide'); }, 220);
    }
    function load(s, i) {
      s._fit = null;
      s._bad = false;
      s.style.visibility = 'hidden';
      s.setAttribute('aria-hidden', 'true');
      if (i < 0 || i >= pics.length) { s.removeAttribute('src'); s.alt = ''; return; }
      s.alt = pics[i].alt;
      if (s.getAttribute('src') === pics[i].src && s.complete && s.naturalWidth) {
        fitSlot(s);
        s.style.visibility = '';
      } else {
        s.src = pics[i].src;
      }
    }
    function label() {
      var pic = pics[at];
      caption.textContent = pic.name + (pics.length > 1 ? '  ·  ' + (at + 1) + ' of ' + pics.length : '');
      prev.setAttribute('aria-disabled', String(at === 0));
      next.setAttribute('aria-disabled', String(at === pics.length - 1));
    }
    // The picture just slid into place becomes the shown one, with nothing reloaded or moved.
    function become(dir) {
      var gone = dir > 0 ? before : after;
      img.setAttribute('aria-hidden', 'true');
      if (dir > 0) { before = img; img = after; after = gone; } else { after = img; img = before; before = gone; }
      load(gone, at + dir);
      img.removeAttribute('aria-hidden');
      missing.hidden = !img._bad;
      v.z = 1;
      v.w = 0; v.h = 0;
      fit();
      paint();
    }

    // The row glides to `to` (a slide in pixels) and then `done` runs. A finger put down while it is
    // still gliding finishes it at once, so the next swipe starts from where the eye already is.
    var settling = null;
    function settle(to, ms, done) {
      stage.style.setProperty('--slide-ms', Math.round(ms) + 'ms');
      stage.classList.add('sliding');
      paint(to);
      var t = setTimeout(finish, ms + 20);
      settling = finish;
      function finish() {
        clearTimeout(t);
        settling = null;
        stage.classList.remove('sliding');
        if (done) { done(); } else { paint(0); }
      }
    }
    function go(dir, vel) {
      if (settling) { settling(); }
      var to = at + dir;
      if (to < 0 || to >= pics.length) { settle(0, 260); return; }
      if (v.z > 1.01) { v.z = 1; clamp(); paint(); }
      var S = size(), end = -dir * (S.W + GAP), left = Math.abs(end - slid);
      // A flick leaves at its own speed (the curve starts at about two and a half times its
      // average), a slow drag or a press at a calm one.
      var ms = Math.max(200, Math.min(400, vel ? 2.5 * left / Math.abs(vel) : 320));
      at = to;
      label();
      settle(end, ms, function () { become(dir); });
    }
    function show(i) {
      at = i;
      load(before, at - 1);
      load(after, at + 1);
      load(img, at);
      img.removeAttribute('aria-hidden');
      label();
    }

    // How far the row moves for a finger dx: all of it, unless there is nothing that way, and then
    // less and less the further it is pulled.
    function slideFor(dx) {
      if ((dx > 0 && at > 0) || (dx < 0 && at < pics.length - 1)) { return dx; }
      var W = size().W || 1, a = Math.abs(dx);
      return (dx < 0 ? -1 : 1) * (1 - 1 / (a * 0.55 / W + 1)) * W;
    }

    var pts = new Map(), pinch = null, drag = null, tap = null;
    function rel(e) { var r = stage.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    stage.addEventListener('pointerdown', function (e) {
      if (e.pointerType === 'mouse' && e.button !== 0) { return; }
      e.preventDefault();
      if (settling) { settling(); }
      try { stage.setPointerCapture(e.pointerId); } catch (err) { /* already gone */ }
      pts.set(e.pointerId, rel(e));
      if (pts.size === 2) {
        if (slid) { paint(0); }
        var p = Array.from(pts.values());
        var mid = { x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 };
        pinch = { d: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1, z: v.z,
                  ix: (mid.x - v.x) / v.z, iy: (mid.y - v.y) / v.z };
        drag = null;
        tap = null;
      } else if (pts.size === 1) {
        var q = rel(e), now = Date.now();
        drag = { x: q.x, y: q.y, vx: v.x, vy: v.y, moved: 0, t: now, lx: 0, lt: now, vel: 0 };
      }
    });
    stage.addEventListener('pointermove', function (e) {
      if (!pts.has(e.pointerId)) { return; }
      pts.set(e.pointerId, rel(e));
      if (pinch && pts.size >= 2) {
        if (!v.w) { return; }
        var p = Array.from(pts.values());
        var mid = { x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 };
        var z = Math.max(1, Math.min(v.most, pinch.z * Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) / pinch.d));
        v.z = z;
        v.x = mid.x - pinch.ix * z;
        v.y = mid.y - pinch.iy * z;
        clamp();
        paint();
        return;
      }
      if (!drag) { return; }
      var q = rel(e), dx = q.x - drag.x, dy = q.y - drag.y, now = Date.now();
      drag.moved = Math.max(drag.moved, Math.hypot(dx, dy));
      // The finger's speed across, in pixels a millisecond, smoothed over its last few moves.
      if (now > drag.lt) {
        drag.vel = 0.7 * (dx - drag.lx) / (now - drag.lt) + 0.3 * drag.vel;
        drag.lx = dx;
        drag.lt = now;
      }
      if (v.z > 1.01) {
        v.x = drag.vx + dx;
        v.y = drag.vy + dy;
        clamp();
        paint();
      } else {
        paint(slideFor(dx));
      }
    });
    function lift(e) {
      if (!pts.has(e.pointerId)) { return; }
      pts.delete(e.pointerId);
      if (pinch) {
        if (pts.size < 2) { pinch = null; }
        if (pts.size === 1) {
          var left = Array.from(pts.values())[0];
          drag = { x: left.x, y: left.y, vx: v.x, vy: v.y, moved: 99, t: 0, lx: 0, lt: Date.now(), vel: 0 };
        }
        return;
      }
      if (!drag) { return; }
      var q = rel(e), dx = q.x - drag.x, d = drag;
      drag = null;
      if (v.z <= 1.01) {
        // A finger that stopped before it lifted has no flick left in it.
        var vel = Date.now() - d.lt > 80 ? 0 : d.vel;
        var dir = dx < 0 ? 1 : -1, W = size().W;
        var far = Math.abs(dx) > W * 0.33 && !(vel * dx < 0 && Math.abs(vel) > 0.3);
        var flick = Math.abs(dx) > 16 && Math.abs(vel) > 0.35 && vel * dx > 0;
        if (e.type !== 'pointercancel' && d.moved >= 10 && (far || flick) && pics[at + dir]) {
          go(dir, Math.abs(vel) > 0.35 ? vel : 0);
          return;
        }
        if (slid) { settle(0, Math.max(200, Math.min(320, Math.abs(slid) * 1.2))); }
      } else if (e.type === 'pointercancel') {
        glide(function () { clamp(); paint(); });
        return;
      }
      if (e.type !== 'pointercancel' && d.moved < 10 && Date.now() - d.t < 350) {
        var now = Date.now();
        if (tap && now - tap.t < 320 && Math.hypot(q.x - tap.x, q.y - tap.y) < 30) {
          tap = null;
          glide(function () { if (v.z > 1.01) { v.z = 1; clamp(); paint(); } else { zoomAt(Math.min(v.most, 2.5), q.x, q.y); } });
        } else {
          tap = { t: now, x: q.x, y: q.y };
        }
      }
    }
    stage.addEventListener('pointerup', lift);
    stage.addEventListener('pointercancel', lift);
    stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      var q = rel(e);
      zoomAt(v.z * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), q.x, q.y);
    }, { passive: false });
    // Safari's own page zoom must not take the pinch; the stage has it.
    dlg.addEventListener('gesturestart', function (e) { e.preventDefault(); });
    dlg.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight' && pics.length > 1) { e.preventDefault(); go(1); }
      else if (e.key === 'ArrowLeft' && pics.length > 1) { e.preventDefault(); go(-1); }
      else if (e.key === '+' || e.key === '=') { e.preventDefault(); var S = size(); glide(function () { zoomAt(v.z * 1.5, S.W / 2, S.H / 2); }); }
      else if (e.key === '-') { e.preventDefault(); var T = size(); glide(function () { zoomAt(v.z / 1.5, T.W / 2, T.H / 2); }); }
      else if (e.key === '0') { e.preventDefault(); glide(function () { v.z = 1; clamp(); paint(); }); }
      e.stopPropagation();
    });
    prev.addEventListener('click', function () { go(-1); });
    next.addEventListener('click', function () { go(1); });
    function onResize() {
      if (settling) { settling(); }
      fitSlot(before);
      fitSlot(after);
      if (img.complete && img.naturalWidth) { fit(); }
    }
    function onBack() { if (dlg.open) { dlg.close(); } }
    close.addEventListener('click', function () { dlg.close(); });
    dlg.addEventListener('close', function () {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('popstate', onBack);
      dlg.remove();
    });
    window.addEventListener('resize', onResize);
    window.addEventListener('popstate', onBack);
    document.body.appendChild(dlg);
    show(at);
    dlg.showModal();
    close.focus();
  }

  /* A part of the gene's own page: a heading, and what is under it. `part` is what an old tab's
     address names, so /gene/<id>/questions still opens the page at its questions. */
  function part(head, name) {
    var sec = el('section', 'evo-part');
    sec.setAttribute('aria-label', head);
    sec.dataset.part = name;
    sec.appendChild(el('h5', 'evo-part-h', head));
    return sec;
  }

  var USE_WORDS = { used: 'Used', ran: 'Ran by itself', offered: 'Offered', taken: 'Offer taken', declined: 'Offer turned down', tried: 'Tried from its card' };

  /* Trial (fr_2d2b3726ebb0; Usage on 18 October 2026, Trial Status on 19 October,
     fr_62370104d867, and its own tab the same day, fr_44acd06b1e00): the trial as it really
     stands, with its settings to change in place, then the signs of use. */
  function trialTab(sec, p) {
    var l = p.learning || {}, c = p.card;
    var t = l.trial || {};
    // A version replaced by a newer one has no trial of its own to say anything about.
    if (t.on_trial || t.outcome_said) { sec.appendChild(trialPart(c, t)); }
    else { sec.appendChild(el('p', 'evo-sec-p', 'This version has no trial of its own.')); }
    var uses = l.uses || [];
    sec.appendChild(el('p', 'evo-k', 'Signs of use' + (c.trial_started_at ? ' since its trial started' : ' in the last seven days')));
    if (!uses.length) { sec.appendChild(el('p', 'evo-sec-p', 'None recorded.')); return; }
    var ol = el('ol', 'evo-history');
    uses.slice().reverse().forEach(function (u) {
      var li = el('li');
      li.appendChild(el('span', 'evo-when-at', u.when));
      li.appendChild(el('strong', null, USE_WORDS[u.kind] || u.kind));
      if (u.how) { li.appendChild(el('span', 'evo-by', u.how)); }
      ol.appendChild(li);
    });
    sec.appendChild(ol);
  }

  /* The gene's trial (Petar, 18 October 2026): where it stands, day X of Y and uses so far of
     those needed, or its one result once it ended; and while it runs, its three settings, saved
     on the gene at once. Keep, with the answers, ends it as Passed. */
  function trialPart(c, t) {
    var box = el('div', 'evo-trial');
    var status = el('p', 'evo-trial-status');
    status.setAttribute('role', 'status');
    function say(v) {
      status.textContent = '';
      var uses = (v.uses || 0) + ' of ' + v.needed + (v.needed === 1 ? ' use' : ' uses');
      if (v.on_trial) {
        status.appendChild(el('strong', null, 'Day ' + Math.min(v.day, v.of) + ' of ' + v.of));
        status.appendChild(words(' · ' + uses + (v.extended ? ' · ' + v.outcome_said : '')));
      } else if (v.outcome_said) {
        // Its one result, Passed or Failed, and who decided it: he did, or the data did.
        status.appendChild(el('strong', null, v.outcome_said));
        status.appendChild(words((v.ended_words ? ', ' + v.ended_words : '') + (v.outcome ? ' · ' + uses : '')));
      }
    }
    say(t);
    box.appendChild(status);
    if (t.editable) {
      box.appendChild(trialForm(t, (t.items || []).map(function (i) { return { id: i.key, said: i.said }; }), function (body) {
        return call('/genes/' + c.id + '/trial', body).then(function (j) {
          if (R.gene && R.gene.card && R.gene.card.id === c.id) {
            R.gene.card = j.gene;
            if (R.gene.learning) { R.gene.learning.trial = j.trial; }
          }
          say(j.trial);
          return { said: j.said, trial: j.trial };
        });
      }, { least: t.least_days || 1 }));
    }
    return box;
  }

  /* A trial's settings, the same on a gene's Trial Status and in Parameters (V1): its length in
     days, the uses that pass it, and, on a gene, what counts as using it: the use signals it
     declares, each in its own words of what happened (`rouh/genes/signals.py`), and none drawn
     when it has none. Each change is saved at once; a change the server refuses is put back, with
     why. */
  function trialForm(t, items, save, opts) {
    opts = opts || {};
    var now = { days: t.days, needed: t.needed, counts: (t.counts || []).slice() };
    var box = el('div', 'evo-trial-form');
    var said = el('p', 'evo-said');
    said.setAttribute('role', 'status');
    said.hidden = true;
    function tell(text) { said.textContent = text || ''; said.hidden = !text; }
    function send(body, ctl, undo) {
      ctl.disabled = true;
      save(body).then(function (j) {
        ctl.disabled = false;
        if (j && j.trial) { now = { days: j.trial.days, needed: j.trial.needed, counts: (j.trial.counts || []).slice() }; }
        tell(j && j.said);
      }, function (err) { ctl.disabled = false; undo(); tell(String((err && err.message) || err)); });
    }
    var nums = el('div', 'evo-trial-nums');
    function number(label, key, lo, hi) {
      var lab = el('label', 'evo-trial-num');
      lab.appendChild(el('span', null, label));
      var n = el('input', 'evo-num');
      n.type = 'number'; n.min = String(lo); n.max = String(hi); n.step = '1'; n.inputMode = 'numeric';
      n.value = String(now[key]);
      n.addEventListener('change', function () {
        var v = Number(n.value.trim());
        if (n.value.trim() === '' || v !== Math.floor(v) || v < lo || v > hi) {
          n.value = String(now[key]);
          tell(label + ' takes a whole number from ' + lo + ' to ' + hi + '. Nothing was changed.');
          return;
        }
        var body = {};
        body[key] = v;
        send(body, n, function () { n.value = String(now[key]); });
      });
      lab.appendChild(n);
      nums.appendChild(lab);
    }
    number('Days', 'days', opts.least || 1, (R.params && R.params.trial_most_days) || 90);
    number('Uses that pass it', 'needed', 1, (R.params && R.params.needed_most) || 50);
    box.appendChild(nums);
    if (!items.length) { box.appendChild(said); return box; }
    var counts = el('fieldset', 'evo-trial-counts');
    counts.appendChild(el('legend', null, 'What counts as using it'));
    var boxes = [];
    items.forEach(function (it) {
      var lab = el('label', 'evo-radio');
      var cb = el('input');
      cb.type = 'checkbox'; cb.value = it.id; cb.checked = now.counts.indexOf(it.id) >= 0;
      cb.addEventListener('change', function () {
        var picked = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
        send({ counts: picked }, cb, function () { boxes.forEach(function (b) { b.checked = now.counts.indexOf(b.value) >= 0; }); });
      });
      boxes.push(cb);
      lab.appendChild(cb);
      lab.appendChild(el('span', null, it.said));
      counts.appendChild(lab);
    });
    box.appendChild(counts);
    box.appendChild(said);
    return box;
  }

  /* Right under the answers: every question asked about it, each with its follow-ups, then a
     new one, answered by Rouh from the gene's own record. */
  function questionsSection(c, p) {
    var sec = part('Questions', 'questions');
    (p.topics || []).forEach(function (t) {
      sec.appendChild(askBox(c, { place: 'gene', topic: t.topic, turns: t.turns }));
    });
    sec.appendChild(askBox(c, { place: 'gene', label: (p.topics || []).length ? 'A new question' : '' }));
    return sec;
  }

  /* Versions (fr_44acd06b1e00): everything about the mutation, which was a fold at the bottom
     of the page until 19 October 2026 - what changed, the original beside our version, every
     version, and every change he asked for. Taking the code out is Reject's. */
  function earlier(p) { return Math.max(0, (p.versions || []).length - 1); }

  function versionsTab(body, p) {
    var c = p.card;
    var ms = p.mutations || [];
    // A gene never mutated has nothing here but that; a change he asked for that is still being
    // built is listed under it, since it is on its way to being one (Petar, 19 October 2026).
    if (!earlier(p)) {
      body.appendChild(el('p', 'evo-sec-p', 'No previous versions.'));
      if (ms.length) { changesAsked(body, ms, c); }
      return;
    }
    if (c.builds_on && c.changed) {
      body.appendChild(el('h5', 'evo-part-h', 'What changed'));
      body.appendChild(el('p', 'evo-sec-p', c.builds_on));
      body.appendChild(el('p', 'evo-card-changed', c.changed));
    }
    body.appendChild(el('h5', 'evo-part-h', 'The original and our version'));
    body.appendChild(compare(c));
    body.appendChild(el('h5', 'evo-part-h', 'Versions'));
    var vs = el('ol', 'evo-versions');
    (p.versions || []).forEach(function (v) {
      var li = el('li', 'evo-version' + (v.current ? ' on' : ''));
      var top = el('div', 'evo-row-top');
      top.appendChild(el('span', 'evo-row-name', 'Version ' + v.version + (v.current ? ', this one' : '')));
      top.appendChild(chip(v.state_name, 'evo-state-' + v.state));
      top.appendChild(chip(v.check === 'same' ? 'No mutation from the original' : v.check === 'mutated' ? 'Mutated from the original' : 'Not checked',
        v.check === 'mutated' ? 'evo-warn' : 'evo-quiet'));
      li.appendChild(top);
      if (v.sentence) { li.appendChild(el('p', 'evo-row-said', v.sentence)); }
      if (!v.current) { li.appendChild(link('Open version ' + v.version, '/evolution/mutations/gene/' + v.id, 'evo-link')); }
      vs.appendChild(li);
    });
    body.appendChild(vs);
    changesAsked(body, ms, c);
  }

  function changesAsked(body, ms, c) {
    body.appendChild(el('h5', 'evo-part-h', 'Changes you asked for · ' + ms.length));
    if (!ms.length) { body.appendChild(el('p', 'evo-sec-p', 'None yet. Mutate…, above the tabs, asks for one in your own words.')); }
    var ul = el('ul', 'evo-list');
    ms.forEach(function (r) { ul.appendChild(requestRow(r, c.id)); });
    if (ms.length) { body.appendChild(ul); }
  }

  /* History (fr_44acd06b1e00): the log of what has happened to the gene, newest first. */
  function historyTab(body, p) {
    var ol = el('ol', 'evo-history');
    (p.decisions || []).slice().reverse().forEach(function (e) {
      var li = el('li');
      li.appendChild(el('span', 'evo-when-at', e.when));
      li.appendChild(el('strong', null, e.kind_words));
      if (e.by && e.by !== 'rouh') { li.appendChild(el('span', 'evo-by', e.by === 'person' ? 'you' : e.by)); }
      if (e.detail) { li.appendChild(el('p', null, e.detail)); }
      ol.appendChild(li);
    });
    if (ol.firstChild) { body.appendChild(ol); } else { body.appendChild(el('p', 'evo-sec-p', 'Nothing yet.')); }
  }

  /* ---- the month view: the last thirty days (the week view, of seven, until 19 October 2026,
     fr_650809f11685: "week should be month") ---- */

  var MARKS = { used: ['★', 'used it yourself'], taken: ['◐', 'offered, you took it'], offered: ['○', 'offered, not taken'],
                declined: ['✕', 'turned the offer down'], ran: ['·', 'ran by itself'] };

  function drawMonth(wrap) {
    var w = R.month;
    wrap.appendChild(el('p', 'evo-lede', 'The last thirty days of every gene in your Rouh or answered this month: what was used, what ran by itself, and what each verdict is. “Learned” means you used it without being asked.'));
    if (!w) { wrap.appendChild(el('p', 'evo-loading', 'Reading the month…')); return; }
    var legend = el('p', 'evo-legend');
    Object.keys(MARKS).forEach(function (k) {
      var s = el('span');
      s.appendChild(el('b', 'evo-mark evo-mark-' + k, MARKS[k][0]));
      s.appendChild(document.createTextNode(' ' + MARKS[k][1]));
      legend.appendChild(s);
    });
    wrap.appendChild(legend);
    if (!w.genes.length) { empty(wrap, 'Nothing to show for this month.', 'Genes you keep show here, day by day.'); return; }
    // Each day is its weekday's first letter over its date, and a week starts at a Monday's line.
    // Thirty days leave no room for a column of verdicts, so each gene's is under its name.
    function dayCls(d) { return 'evo-day' + (d.monday ? ' evo-monday' : ''); }
    function dayWords(d) { return d.day + ' ' + d.date; }
    var scroll = el('div', 'evo-month-scroll');
    var table = el('table', 'evo-month');
    var thead = el('thead');
    var hr = el('tr');
    hr.appendChild(el('th', 'evo-month-name', 'Gene'));
    w.days.forEach(function (d) {
      var th = el('th', dayCls(d));
      th.setAttribute('aria-label', dayWords(d));
      th.title = dayWords(d);
      th.appendChild(el('span', 'evo-day-w', d.day.charAt(0)));
      th.appendChild(el('span', 'evo-day-n', d.date));
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    var tb = el('tbody');
    w.genes.forEach(function (g) {
      var tr = el('tr', g.state === 'off_disuse' ? 'evo-going' : '');
      var name = el('td', 'evo-month-name');
      var b = button('evo-req-gene', g.name);
      b.addEventListener('click', function () { openGene(g.id, 'learning'); });
      name.appendChild(b);
      name.appendChild(el('span', 'evo-row-sub', g.kind_name + (g.signal ? '' : ' · no use signal')));
      var v = el('span', 'evo-month-verdict', g.verdict);
      name.appendChild(v);
      tr.appendChild(name);
      g.marks.forEach(function (m, i) {
        var td = el('td', dayCls(w.days[i]));
        if (m) {
          td.appendChild(el('b', 'evo-mark evo-mark-' + m, MARKS[m][0]));
          td.setAttribute('aria-label', dayWords(w.days[i]) + ': ' + MARKS[m][1]);
          td.title = dayWords(w.days[i]) + ': ' + MARKS[m][1];
        }
        tr.appendChild(td);
      });
      if (g.state === 'off_disuse') {
        var keep = button('ctl small', 'Turn on again');
        keep.addEventListener('click', function () {
          keep.disabled = true;
          call('/genes/' + g.id + '/answer', { answer: 'turn_on' }).then(function (j) { R.said = j.said; load(); }, fail);
        });
        name.appendChild(keep);
      }
      tb.appendChild(tr);
    });
    table.appendChild(tb);
    scroll.appendChild(table);
    wrap.appendChild(scroll);
    // Where the table slides sideways it opens at today, the newest days, as a calendar does.
    requestAnimationFrame(function () { scroll.scrollLeft = scroll.scrollWidth; });
  }

  /* ---- the layer ---- */

  function shown(page, sub) {
    var moved = !R.open || R.page !== page || R.sub !== (sub || '');
    R.open = true;
    var wasIncubator = R.page === 'incubator';
    R.page = page === 'parameters' || page === 'pool' || page === 'incubator' || page === 'nightly' || page === 'trials' ? page : 'mutations';
    R.sub = newSub(R.page, sub);
    if (wasIncubator && R.page !== 'incubator' && window.RouhIncubator) { window.RouhIncubator.hidden(); }
    if (moved) {
      R.said = '';
      if (R.sub.indexOf('gene/') !== 0) { R.gene = null; }
      if (R.page === 'parameters') { R.draft = null; }
      aim();
    }
    if (R.sub !== (sub || '') && host().moved) { host().moved(R.page, R.sub, R.gene && R.gene.card ? R.gene.card.name : ''); }
    draw();
    load();
  }

  function hidden() {
    R.open = false;
    if (window.RouhIncubator) { window.RouhIncubator.hidden(); }
  }

  /* What the Incubator and the nightly run's page are handed: going somewhere in Rouh, saying where
     inside the layer they are now (one idea, by its number), and the conversation's Markdown. */
  function wideHost() {
    return {
      go: function (href) { if (host().go) { host().go(href); } else { location.href = href; } },
      markdown: host().markdown,
      beside: function () { if (host().beside) { host().beside(); } },
      moved: function (page, sub, title) {
        R.sub = String(sub || '');
        if (host().moved) { host().moved(page, R.sub, title || ''); }
      }
    };
  }

  window.RouhEvolution = { shown: shown, hidden: hidden, reload: load };

  var x = $('evolutionClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
