/* The gene log, inside Mutations (`rouh/genelog.py`, `rouh/geneuse.py`, `rouh/web/genelog.py`).

   Petar, 13 October 2026 (task 98, step 98-16): "There will be a log of implemented genes ... there
   should be a number in the list. I'd rather have the list sorted by default by recency, but I
   should be able to sort it by usage count." Every gene in his Rouh, one row a family, its number
   of uses in thirty days on the right; newest change first, or most used; one gene opens on its
   use, his mark, the model's evaluation, its contract, its family tree and its history, with the
   way to take it out that its contract gives.

   Drawn inside Evolution's layer by `evolutionpage.js`, which hands over where to go and how to
   redraw (`ctx`). The Gene Pool's view is `genepoolpage.js`'s. Nothing is kept in this browser
   but the sort, a convenience of this device. */
(function () {
  'use strict';

  var API = '/api/genes/log';
  var SORT_KEY = 'rouh.geneLogSort';
  var L = { list: null, page: null, pageId: 0, said: '', error: '', busy: false, q: '', at: '',
            sort: readSort() };

  function readSort() {
    try { return localStorage.getItem(SORT_KEY) === 'uses' ? 'uses' : 'recent'; } catch (e) { return 'recent'; }
  }
  function keepSort(v) { try { localStorage.setItem(SORT_KEY, v); } catch (e) { /* only a convenience */ } }

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
  function chip(text, cls) { return el('span', 'evo-chip ' + (cls || ''), text); }

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

  /* ---- loading ---- */

  function load(sub, fresh) {
    var one = /^log\/(\d+)$/.exec(sub);
    if (sub !== L.at) { L.said = ''; L.at = sub; }
    if (/^pool/.test(sub)) {
      return window.RouhGenePool ? window.RouhGenePool.load(sub, fresh) : Promise.resolve();
    }
    L.error = '';
    var jobs = [call('').then(function (j) { if (fresh() && j) { L.list = j; } })];
    if (one) {
      L.pageId = +one[1];
      jobs.push(call('/' + one[1]).then(function (j) { if (fresh() && j) { L.page = j; } }, function (err) {
        if (fresh()) { L.page = { missing: String((err && err.message) || err) }; }
      }));
    } else {
      L.page = null;
    }
    return Promise.all(jobs).catch(function (err) { if (fresh()) { L.error = String((err && err.message) || err); } });
  }

  function draw(wrap, sub, ctx) {
    if (/^pool/.test(sub)) {
      if (window.RouhGenePool) { window.RouhGenePool.draw(wrap, sub, ctx); }
      return;
    }
    if (L.error) { wrap.appendChild(el('p', 'evo-error', L.error)); }
    if (/^log\/\d+$/.test(sub)) { drawGene(wrap, ctx); } else { drawList(wrap, ctx); }
  }

  function act(ctx, path, body, done) {
    if (L.busy) { return; }
    L.busy = true;
    L.said = '';
    ctx.redraw();
    call(path, body).then(function (j) {
      L.busy = false;
      L.said = (j && j.said) || 'Done.';
      if (done) { done(j); }
      ctx.reload();
    }, function (err) {
      L.busy = false;
      L.said = String((err && err.message) || err);
      // A refusal can still have changed something (a switch turned off first): read it again.
      ctx.reload();
    });
  }

  /* ---- the list ---- */

  function sortBy(list) {
    var out = list.slice();
    if (L.sort === 'uses') {
      out.sort(function (a, b) { return (b.uses - a.uses) || (b.uses_all - a.uses_all) || (b.changed_at - a.changed_at); });
    } else {
      out.sort(function (a, b) { return b.changed_at - a.changed_at || a.id - b.id; });
    }
    return out;
  }

  function matches(g) {
    if (!L.q) { return true; }
    var hay = (g.name + ' ' + g.sentence + ' ' + g.key + ' ' + g.origin_name).toLowerCase();
    return L.q.toLowerCase().split(/\s+/).every(function (w) { return !w || hay.indexOf(w) >= 0; });
  }

  function drawList(wrap, ctx) {
    var j = L.list;
    if (ctx.host.moved) { ctx.host.moved('mutations', 'log', 'Gene log'); }
    if (!j) { wrap.appendChild(el('p', 'evo-loading', 'Reading the gene log…')); return; }
    wrap.appendChild(el('p', 'evo-lede', 'Every gene in your Rouh, written down by itself: Rouh’s own, everything ' +
      'you asked for, and what the nightly run built once you keep it. A change that alters what a gene is ' +
      'or touches grows a sub-gene; anything else is a revision of it.'));
    if (!j.on) {
      wrap.appendChild(el('p', 'glog-off', 'The gene log is switched off (gene_log, under Other switches in Evolution, Mutations): it is ' +
        'not reading what lands. What it already holds is below.'));
    }
    var bar = el('div', 'glog-bar');
    var sorts = el('div', 'glog-sort');
    sorts.setAttribute('role', 'group');
    sorts.setAttribute('aria-label', 'Sort the gene log');
    [['recent', 'Newest change'], ['uses', 'Most used']].forEach(function (o) {
      var b = button('evo-vtab' + (L.sort === o[0] ? ' on' : ''), o[1]);
      b.setAttribute('aria-pressed', L.sort === o[0] ? 'true' : 'false');
      b.addEventListener('click', function () { L.sort = o[0]; keepSort(o[0]); ctx.redraw(); });
      sorts.appendChild(b);
    });
    bar.appendChild(sorts);
    var find = el('input', 'evo-find glog-find');
    find.type = 'search';
    find.placeholder = 'Find a gene';
    find.setAttribute('aria-label', 'Find a gene in the log');
    find.value = L.q;
    find.addEventListener('input', function () {
      L.q = find.value;
      var list = wrap.querySelector('.glog-list');
      if (list) { fillList(list, j, ctx); }
    });
    bar.appendChild(find);
    wrap.appendChild(bar);
    var meta = el('p', 'glog-meta');
    var c = j.commits || {};
    meta.appendChild(document.createTextNode(j.genes.length + (j.genes.length === 1 ? ' gene' : ' genes') +
      ' · ' + (c.read || 0) + ' changes read' + (c.waiting ? ' · ' + c.waiting + ' waiting for the gene writer' : '') +
      (j.usage_on ? ' · uses are yours, in the last 30 days' : ' · counting uses is switched off (gene_usage)')));
    var readBtn = button('ctl small glog-read', L.busy ? 'Reading…' : 'Read what landed now');
    readBtn.disabled = L.busy;
    readBtn.addEventListener('click', function () { act(ctx, '/read', {}); });
    meta.appendChild(readBtn);
    wrap.appendChild(meta);
    if (L.said) { var s = el('p', 'evo-said', L.said); s.setAttribute('role', 'status'); wrap.appendChild(s); }
    if (j.drafts && j.drafts.length) {
      wrap.appendChild(el('h4', 'evo-sec-h', 'Drafts · ' + j.drafts.length));
      wrap.appendChild(el('p', 'evo-sec-p', 'Genes drafted in a conversation: a contract, not built yet, or being built.'));
      var dl = el('ul', 'evo-list glog-drafts');
      j.drafts.forEach(function (g) { dl.appendChild(rowOf(g, ctx, true)); });
      wrap.appendChild(dl);
    }
    var ul = el('ul', 'evo-list glog-list');
    ul.setAttribute('aria-label', 'Genes, ' + (L.sort === 'uses' ? 'most used first' : 'newest change first'));
    fillList(ul, j, ctx);
    wrap.appendChild(ul);
  }

  function fillList(ul, j, ctx) {
    ul.textContent = '';
    var shown = sortBy(j.genes).filter(matches);
    shown.forEach(function (g) { ul.appendChild(rowOf(g, ctx, false)); });
    if (!shown.length) {
      var li = el('li', 'glog-none', L.q ? 'No gene in the log has those words.' : 'The log is empty for now.');
      ul.appendChild(li);
    }
  }

  function rowOf(g, ctx, draft) {
    var li = el('li', 'evo-row glog-row');
    var b = button('evo-row-btn glog-row-btn');
    var usesWords = g.uses === 1 ? '1 use' : (g.uses || 0) + ' uses';
    b.setAttribute('aria-label', g.name + ', ' + g.status_name + ', ' + usesWords + ' in 30 days');
    var main = el('span', 'glog-row-main');
    var top = el('span', 'evo-row-top');
    top.appendChild(el('span', 'evo-row-name', g.name));
    top.appendChild(chip(g.origin_name, 'glog-origin-' + g.origin));
    if (g.status !== 'kept') { top.appendChild(chip(g.status_name, 'glog-status-' + g.status)); }
    if (g.subs) { top.appendChild(chip(g.subs + (g.subs === 1 ? ' sub-gene' : ' sub-genes'), 'evo-quiet')); }
    if (g.forks) { top.appendChild(chip(g.forks + (g.forks === 1 ? ' fork' : ' forks'), 'evo-quiet')); }
    if (g.share === 'selected') { top.appendChild(chip(g.pool_node ? 'In the Pool' : 'Approved for the Pool', 'glog-shared')); }
    else if (g.share === 'proposed') { top.appendChild(chip('Proposed for the Pool', 'glog-shared')); }
    main.appendChild(top);
    if (g.sentence) { main.appendChild(el('span', 'evo-row-said', g.sentence)); }
    var sub = [];
    if (g.changed_words) { sub.push((draft ? 'Drafted ' : 'Changed ') + g.changed_words); }
    if (g.revisions) { sub.push(g.revisions + (g.revisions === 1 ? ' revision' : ' revisions')); }
    if (!draft && g.share_of_use) { sub.push(Math.round(g.share_of_use * 1000) / 10 + '% of your uses'); }
    main.appendChild(el('span', 'evo-row-sub', sub.join(' · ')));
    b.appendChild(main);
    if (!draft) {
      var num = el('span', 'glog-uses');
      num.appendChild(el('span', 'glog-uses-n', String(g.uses || 0)));
      num.appendChild(el('span', 'glog-uses-w', g.uses === 1 ? 'use' : 'uses'));
      num.setAttribute('aria-hidden', 'true');
      b.appendChild(num);
    }
    b.addEventListener('click', function () { ctx.go('log/' + g.id); });
    li.appendChild(b);
    return li;
  }

  /* ---- one gene ---- */

  function backLink(ctx, text, sub) {
    var a = el('a', 'evo-back', text);
    a.href = '/evolution/mutations/' + sub;
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
      e.preventDefault();
      ctx.go(sub);
    });
    return a;
  }

  function section(wrap, title) {
    var box = el('section', 'glog-sec');
    box.appendChild(el('h4', 'glog-sec-h', title));
    wrap.appendChild(box);
    return box;
  }

  function drawGene(wrap, ctx) {
    wrap.appendChild(backLink(ctx, '← Gene log', 'log'));
    var p = L.page;
    if (!p || (p.gene && p.gene.id !== L.pageId)) { wrap.appendChild(el('p', 'evo-loading', 'Reading the gene…')); return; }
    if (p.missing) { wrap.appendChild(el('p', 'evo-error', p.missing)); return; }
    var g = p.gene, root = p.root;
    if (ctx.host.moved) { ctx.host.moved('mutations', 'log/' + g.id, g.name); }
    var head = el('div', 'evo-gene-head');
    head.appendChild(el('h4', 'evo-gene-name', g.name));
    var chips = el('div', 'evo-chips');
    chips.appendChild(chip(g.origin_name, 'glog-origin-' + g.origin));
    chips.appendChild(chip(g.status_name, 'glog-status-' + g.status));
    if (g.relation === 'sub') { chips.appendChild(chip('Sub-gene of ' + root.name, 'evo-quiet')); }
    if (g.relation === 'fork') { chips.appendChild(chip('Fork', 'evo-quiet')); }
    if (root.share === 'selected') { chips.appendChild(chip((root.pool_node ? 'In the ' : 'Approved for the ') + poolName(ctx), 'glog-shared')); }
    head.appendChild(chips);
    if (g.sentence) { head.appendChild(el('p', 'evo-card-said', g.sentence)); }
    wrap.appendChild(head);
    if (L.said) { var s = el('p', 'evo-said', L.said); s.setAttribute('role', 'status'); wrap.appendChild(s); }
    if (g.origin === 'draft' && (g.status === 'draft' || g.status === 'growing')) {
      drawDraft(section(wrap, g.status === 'draft' ? 'A draft' : 'Being built'), p, ctx);
      drawContract(section(wrap, 'Its contract'), g);
      drawHistory(wrap, p);
      return;
    }
    drawUse(section(wrap, 'How much you use it'), p, ctx);
    drawContract(section(wrap, 'Its contract'), g, p.needed_by);
    drawFamily(section(wrap, 'Its family'), p, ctx);
    if (window.RouhGenePool && window.RouhGenePool.shareBox) {
      window.RouhGenePool.shareBox(section(wrap, 'Sharing'), p, ctx, function () { ctx.reload(); });
    }
    drawRemove(section(wrap, 'Taking it out'), p, ctx);
    drawHistory(wrap, p);
  }

  function poolName(ctx) { return (ctx.muts && ctx.muts.pool_name) || 'Gene Pool'; }

  function drawUse(box, p, ctx) {
    var u = p.usage || {};
    if (!u.on) { box.appendChild(el('p', 'evo-hint', 'Counting uses is switched off (gene_usage, under Other switches in Evolution, Mutations).')); }
    var nums = el('div', 'glog-nums');
    [[u.uses || 0, 'uses in 30 days'], [Math.round((u.share || 0) * 1000) / 10 + '%', 'of all your uses'],
     [u.days || 0, 'days used of 30'], [u.rank ? '#' + u.rank : '–', 'among your genes'], [u.all || 0, 'uses kept in all']
    ].forEach(function (n) {
      var d = el('div', 'glog-num');
      d.appendChild(el('span', 'glog-num-n', String(n[0])));
      d.appendChild(el('span', 'glog-num-w', n[1]));
      nums.appendChild(d);
    });
    box.appendChild(nums);
    var series = u.series || [];
    var most = 0;
    series.forEach(function (d) { most = Math.max(most, d.uses); });
    var bars = el('div', 'glog-days');
    bars.setAttribute('role', 'img');
    bars.setAttribute('aria-label', 'Uses a day over the last 30 days: ' + (u.uses || 0) + ' in all');
    series.forEach(function (d) {
      var b = el('span', 'glog-day');
      b.style.height = most ? Math.max(4, Math.round(d.uses / most * 100)) + '%' : '4%';
      if (!d.uses) { b.classList.add('none'); }
      b.title = d.day + ': ' + d.uses;
      bars.appendChild(b);
    });
    box.appendChild(bars);
    var ways = Object.keys(u.parts || {});
    var WAYS = { press: 'pressed its link', open: 'opened its page', tool: 'Rouh used it for you', job: 'it ran by itself',
                 model: 'asked a model for it', own: 'its own code said so', message: 'messages to Rouh' };
    box.appendChild(el('p', 'evo-hint', ways.length
      ? 'How: ' + ways.map(function (w) { return (WAYS[w] || w) + ' ' + u.parts[w]; }).join(' · ') +
        '. A press of its link and the page it opens are one use.'
      : 'No use is recorded in the last 30 days. A gene that works in the background is judged by what it does, not by presses.'));
    var markBox = el('div', 'glog-marks');
    markBox.setAttribute('role', 'group');
    markBox.setAttribute('aria-label', 'Your mark');
    markBox.appendChild(el('span', 'glog-marks-w', 'Your mark'));
    Object.keys(u.marks || {}).forEach(function (k) {
      var b = button('glog-mark' + (u.mark === k ? ' on' : ''), u.marks[k]);
      b.setAttribute('aria-pressed', u.mark === k ? 'true' : 'false');
      b.addEventListener('click', function () { act(ctx, '/' + p.gene.id + '/mark', { mark: u.mark === k ? '' : k }); });
      markBox.appendChild(b);
    });
    box.appendChild(markBox);
    var ev = u.evaluation;
    var evBox = el('div', 'glog-eval');
    if (ev) {
      evBox.appendChild(el('p', 'glog-eval-score', ev.score + ' of 5, for ' + ev.month));
      if (ev.reason) { evBox.appendChild(el('p', 'glog-eval-p', ev.reason)); }
      var more = [];
      if (ev.replaced) { more.push('Replaced: ' + ev.replaced); }
      if (ev.minutes != null) { more.push('Saves about ' + ev.minutes + ' minutes a month'); }
      if (ev.model) { more.push('By ' + ev.model); }
      if (more.length) { evBox.appendChild(el('p', 'evo-hint', more.join(' · '))); }
      if (u.mark) { evBox.appendChild(el('p', 'evo-hint', 'Your own mark wins over the model’s score.')); }
    } else {
      evBox.appendChild(el('p', 'evo-hint', 'No evaluation yet. The model reads each gene you used once a month, ' +
        'from its contract and your relative use, never your chats.'));
    }
    var evBtn = button('ctl small', L.busy ? 'Asking…' : 'Evaluate now');
    evBtn.disabled = L.busy;
    evBtn.addEventListener('click', function () { act(ctx, '/' + p.gene.id + '/evaluate', {}); });
    evBox.appendChild(evBtn);
    box.appendChild(evBox);
  }

  function drawContract(box, g, needs) {
    var c = g.contract || {};
    var dl = el('dl', 'glog-contract');
    function row(k, v) {
      if (!v || (Array.isArray(v) && !v.length)) { return; }
      dl.appendChild(el('dt', null, k));
      var dd = el('dd');
      if (Array.isArray(v)) { dd.textContent = v.join(', '); } else { dd.textContent = v; }
      dl.appendChild(dd);
    }
    var t = c.touches || {};
    row('What it is', c.what);
    row('Where it appears', c.where);
    row('What it may do', t.permissions);
    row('Outside accounts', t.accounts);
    row('Tables', t.tables);
    row('Scheduled work', t.jobs);
    row('How to remove it', c.remove || 'Its contract does not say yet.');
    row('Needed by', needs);
    box.appendChild(dl);
    box.appendChild(el('p', 'evo-hint', 'A contract says truthfully what a gene does and how to take it out. It is ' +
      'information, never a permission: a gene may change Rouh in any way except its protected core.'));
  }

  function drawFamily(box, p, ctx) {
    var byParent = {};
    p.family.forEach(function (n) { (byParent[n.parent || 0] = byParent[n.parent || 0] || []).push(n); });
    function branch(n) {
      var li = el('li', 'glog-node' + (n.id === p.gene.id ? ' here' : ''));
      var b = button('glog-node-btn', n.name);
      b.setAttribute('aria-current', n.id === p.gene.id ? 'true' : 'false');
      b.addEventListener('click', function () { ctx.go('log/' + n.id); });
      li.appendChild(b);
      var bits = [n.relation === 'sub' ? 'sub-gene' : n.relation === 'fork' ? 'fork' : 'the gene', n.status_name];
      if (n.revisions) { bits.push(n.revisions + (n.revisions === 1 ? ' revision' : ' revisions')); }
      if (n.tip) { bits.push('new work lands here'); }
      li.appendChild(el('span', 'glog-node-sub', bits.join(' · ')));
      var kids = byParent[n.id] || [];
      if (kids.length) {
        var ul = el('ul', 'glog-tree');
        kids.forEach(function (k) { ul.appendChild(branch(k)); });
        li.appendChild(ul);
      }
      return li;
    }
    var ul = el('ul', 'glog-tree glog-tree-top');
    ul.setAttribute('aria-label', 'Family tree of ' + p.root.name);
    (byParent[0] || []).forEach(function (n) { ul.appendChild(branch(n)); });
    box.appendChild(ul);
    box.appendChild(el('p', 'evo-hint', 'Building on a gene is a revision of it; a change to its contract grows a ' +
      'sub-gene here; a person who installs it made different grows a fork in their own Rouh.'));
  }

  function drawRemove(box, p, ctx) {
    var r = p.removable || {};
    if (r.said) { box.appendChild(el('p', 'glog-remove-said', r.mutations || r.core ? r.said : 'Its contract says: ' + r.said)); }
    var acts = el('div', 'evo-acts');
    if (r.mutations && p.mutations) {
      var a = button('ctl small', 'Open its card in Mutations');
      a.addEventListener('click', function () { ctx.openMutationsGene(p.mutations.id); });
      acts.appendChild(a);
    }
    if (r.off) {
      var off = button('ctl small', 'Turn it off');
      off.addEventListener('click', function () { act(ctx, '/' + p.gene.id + '/turn', { on: false }); });
      acts.appendChild(off);
    }
    if (r.on) {
      var on = button('ctl small', 'Turn it on again');
      on.addEventListener('click', function () { act(ctx, '/' + p.gene.id + '/turn', { on: true }); });
      acts.appendChild(on);
    }
    if (r.out) {
      var out = button('ctl small danger', 'Take it out…');
      out.addEventListener('click', function () {
        var sure = box.querySelector('.glog-sure');
        if (sure) { sure.hidden = false; return; }
        sure = el('div', 'glog-sure');
        sure.setAttribute('role', 'group');
        sure.setAttribute('aria-label', 'Confirm taking it out');
        sure.appendChild(el('p', null, 'A run takes ' + p.root.name + ' out of Rouh’s code as its contract says, ' +
          'proves Rouh still works, and deploys.' + (p.root.switch ? ' Its switch goes off at once.' : '')));
        var yes = button('ctl small danger', 'Yes, take it out');
        yes.addEventListener('click', function () { act(ctx, '/' + p.gene.id + '/remove', { confirm: true }); });
        var no = button('ctl small', 'Cancel');
        no.addEventListener('click', function () { sure.hidden = true; });
        sure.appendChild(yes);
        sure.appendChild(no);
        box.appendChild(sure);
        yes.focus();
      });
      acts.appendChild(out);
    }
    if (acts.childNodes.length) { box.appendChild(acts); }
    if (p.gene.removal && p.gene.removal.said) { box.appendChild(el('p', 'evo-hint', p.gene.removal.said)); }
  }

  /* A gene drafted on the fly (`rouh/genedraft.py`): its versions, and what can be done with it. */
  function drawDraft(box, p, ctx) {
    var g = p.gene, d = g.draft || {};
    var versions = d.versions || [];
    if (g.status === 'growing') {
      box.appendChild(el('p', 'glog-remove-said', 'Run ' + (d.run || '') + ' is building it into Rouh, behind its own switch, off until you turn it on here.'));
      return;
    }
    box.appendChild(el('p', 'evo-hint', 'Version ' + versions.length + (d.idea ? ' · why: ' + d.idea : '') +
      (d.night ? ' · left for the nightly run, which adds it to its ideas list' : '')));
    var acts = el('div', 'evo-acts');
    var grow = button('ctl small primary', 'Grow it…');
    grow.addEventListener('click', function () {
      if (box.querySelector('.glog-sure')) { return; }
      var sure = el('div', 'glog-sure');
      sure.setAttribute('role', 'group');
      sure.setAttribute('aria-label', 'Confirm growing it');
      sure.appendChild(el('p', null, 'A run builds ' + g.name + ' into Rouh from this contract, proves it and deploys it, behind its own switch, off until you turn it on.'));
      var yes = button('ctl small primary', 'Yes, grow it');
      yes.addEventListener('click', function () { act(ctx, '/' + g.id + '/draft', { action: 'grow', confirm: true }); });
      var no = button('ctl small', 'Cancel');
      no.addEventListener('click', function () { sure.remove(); });
      sure.appendChild(yes); sure.appendChild(no);
      box.appendChild(sure);
      yes.focus();
    });
    acts.appendChild(grow);
    var night = button('ctl small', d.night ? 'Take it back from the night' : 'Leave it for the nightly run');
    night.addEventListener('click', function () { act(ctx, '/' + g.id + '/draft', { action: d.night ? 'back' : 'night' }); });
    acts.appendChild(night);
    var drop = button('ctl small danger', 'Drop the draft');
    drop.addEventListener('click', function () {
      act(ctx, '/' + g.id + '/draft', { action: 'drop' }, function () { ctx.go('log'); });
    });
    acts.appendChild(drop);
    box.appendChild(acts);
    var form = el('form', 'pool-form glog-revise');
    form.setAttribute('aria-label', 'Change the draft');
    var c = g.contract || {};
    [['name', 'Its name', g.name], ['what', 'What it does', c.what], ['where', 'Where it appears', c.where],
     ['remove', 'How to take it out', c.remove]].forEach(function (f) {
      var p2 = el('p', 'pool-field');
      var lab = el('label', null, f[1]);
      var input = el(f[0] === 'name' ? 'input' : 'textarea');
      input.id = 'draft_' + f[0];
      input.name = f[0];
      input.value = f[2] || '';
      if (input.tagName === 'TEXTAREA') { input.rows = 2; }
      lab.htmlFor = input.id;
      p2.appendChild(lab); p2.appendChild(input);
      form.appendChild(p2);
    });
    var save = button('ctl small', 'Save as a new version');
    save.type = 'submit';
    form.appendChild(save);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var body = { action: 'revise' };
      ['name', 'what', 'where', 'remove'].forEach(function (k) { body[k] = form.elements[k].value; });
      act(ctx, '/' + g.id + '/draft', body);
    });
    var more = el('details', 'pool-more');
    more.appendChild(el('summary', null, 'Change it here'));
    more.appendChild(form);
    box.appendChild(more);
    if (versions.length > 1) {
      var ul = el('ul', 'glog-hist');
      versions.slice().reverse().forEach(function (v, i) {
        var li = el('li');
        li.appendChild(el('span', 'glog-hist-what', 'Version ' + (versions.length - i)));
        li.appendChild(el('span', 'glog-hist-p', (v.contract && v.contract.what) + (v.said ? ' · ' + v.said : '')));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
  }

  /* Every version of the gene, newest first, with what changed and where it was asked for: closed
     until opened (Petar, 19 October 2026: nothing new to see unless he looks). */
  function drawHistory(wrap, p) {
    var box = el('details', 'glog-sec glog-hist-box');
    var sum = el('summary', 'glog-sec-h', 'Its history');
    sum.appendChild(el('span', 'evo-count', String(p.events.length)));
    box.appendChild(sum);
    wrap.appendChild(box);
    var ul = el('ul', 'glog-hist');
    p.events.slice(0, 60).forEach(function (e) {
      var li = el('li');
      var top = el('span', 'glog-hist-top');
      top.appendChild(el('span', 'glog-hist-what', e.kind_words));
      if (e.gene !== p.gene.id && e.gene_name) { top.appendChild(el('span', 'glog-hist-node', e.gene_name)); }
      top.appendChild(el('span', 'glog-hist-when', e.when + (e.commit ? ' · ' + e.commit.slice(0, 7) : '')));
      li.appendChild(top);
      if (e.detail) { li.appendChild(el('span', 'glog-hist-p', e.detail)); }
      if (e.source) {
        li.appendChild(el('span', 'glog-hist-from', e.source.said + (e.source.words ? ': \u201c' + e.source.words + '\u201d' : '') +
          (e.source.feedback ? ' (' + e.source.feedback + ')' : '')));
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    if (p.events.length > 60) { box.appendChild(el('p', 'evo-hint', 'The newest 60 of ' + p.events.length + '.')); }
  }

  window.RouhGeneLog = { load: load, draw: draw, said: function (t) { L.said = t || ''; } };
}());
