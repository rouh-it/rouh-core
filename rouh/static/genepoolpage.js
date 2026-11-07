/* The Gene Pool, Evolution's page at `/evolution/pool` (`rouh/genepool.py`, `rouh/web/genepool.py`),
   and the Sharing part of a gene's page in the gene log. It was a view of the Gene library, now
   Mutations, until 14 October 2026, when Petar made it its own item (fr_a982710d30c7).

   Petar, 13 October 2026 (task 98, step 98-16): "There needs to be a browser for other people's genes,
   a list of my generated genes from which I can choose which ones to upload ... I'd like to be able to
   tell it how I want it different. That would fork the gene ... a lot of the decisions will have to be
   made by AI." So: joining with an invitation, genes picked for this person by a model with why, every
   family to browse with its signals, installing one as it is or made different, thanking its giver,
   and in the gene log a switch on each gene, off until a person turns it on, that shares it.

   The Pool is closed while who may join is undecided; this page says so and asks nothing of it until
   this Rouh has joined. Its name comes from the server (`genepool.NAME`), so renaming it is one change.

   Petar, 22 October 2026 (task 141, step 141-09): "I would like to see those genes before they go to
   the pool. If there is a place where I can click and see them, let me know. If there isn't, then that
   should be created." So the review list, `pool/yours`: every gene of the log on its way to the Pool,
   where it stands, and one of them at `pool/yours/<id>` with the exact body each node would send, what
   the checks found, and Approve, Decline and Edit; and the sharing mode, manual unless an
   administrator chose otherwise.

   Task 141, step 141-14: two Rouhs built from the same code already have the same genes, so a Pool
   gene that is one of this Rouh's own (by its identity in the code) says "Already here: in your
   Rouh's code" where Install was, a gene of this Rouh's that another Rouh already gave says so on the
   review list, and a newer version another Rouh gave of a gene this Rouh has from its code is said,
   never installed.

   Petar, 25 October 2026 (task 141, step 141-15): "there is no join button. As soon as you have a
   birthday and the Rouh is given birth, it should be joining the pool. Then two things need to
   happen: control outgoing genes and control incoming genes. Both of those need to have their own
   pages ... By default both of those will be manual or in other words not exchanging, but a person
   can choose something else." So no Join and no Leave: the Pool's page says where this Rouh stands
   and opens two pages, Outgoing genes at `pool/outgoing` (the setting and the review list that was
   `pool/yours`) and Incoming genes at `pool/incoming` (the setting, picks, every gene, installed),
   each with its own setting in the same control (`settingBox`). */
(function () {
  'use strict';

  var API = '/api/genes/pool';
  var P = { data: null, said: '', busy: false, error: '', at: '', q: '', words: '', open: '',
            out: null, one: null, show: '', oq: '', editing: 0, sure: '', about: {} };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(cls, text) { var b = el('button', cls, text); b.type = 'button'; return b; }
  function chip(text, cls) { return el('span', 'evo-chip ' + (cls || ''), text); }

  function post(path, body) {
    return fetch(path, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                         headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not do that just now. Try again in a moment.'); }
          return j;
        });
      });
  }

  function load(sub, fresh) {
    // A pick's proposed fork rides along into its family's page; going back to the list drops it.
    if (sub !== P.at) {
      P.said = ''; P.at = sub; P.editing = 0; P.sure = '';
      if (sub === 'pool') { P.open = ''; }
      if (!/^pool\/outgoing\/\d+$/.test(sub)) { P.one = null; }
    }
    P.error = '';
    var one = /^pool\/outgoing\/(\d+)$/.exec(sub);
    var wants = [get(API).then(function (j) { if (fresh() && j) { P.data = j; } })];
    if (sub === 'pool/outgoing') { wants.push(get(API + '/out').then(function (j) { if (fresh() && j) { P.out = j; } })); }
    if (one) {
      wants.push(get(API + '/out/' + one[1]).then(function (j) { if (fresh() && j) { P.one = j; } }, function (err) {
        if (fresh()) { P.one = { missing: String((err && err.message) || err) }; }
      }));
    }
    return Promise.all(wants).catch(function (err) {
      if (fresh()) { P.error = String((err && err.message) || err); }
    });
  }

  function get(path) {
    return fetch(path, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not read that just now. Try again in a moment.'); }
        return j;
      });
    });
  }

  function act(ctx, path, body, after) {
    if (P.busy) { return; }
    P.busy = true;
    P.said = '';
    ctx.redraw();
    post(path, body).then(function (j) {
      P.busy = false;
      P.said = (j && j.said) || 'Done.';
      if (after) { after(j); }
      ctx.reload();
    }, function (err) {
      P.busy = false;
      P.said = String((err && err.message) || err);
      ctx.reload();
    });
  }

  function said(wrap) {
    if (!P.said) { return; }
    var s = el('p', 'evo-said', P.said);
    s.setAttribute('role', 'status');
    wrap.appendChild(s);
  }

  function draw(wrap, sub, ctx) {
    var j = P.data;
    if (P.error) { wrap.appendChild(el('p', 'evo-error', P.error)); }
    if (!j) { wrap.appendChild(el('p', 'evo-loading', 'Reading the Gene Pool…')); return; }
    if (sub === 'pool/outgoing') { drawOut(wrap, ctx); return; }
    var mine = /^pool\/outgoing\/(\d+)$/.exec(sub);
    if (mine) { drawOne(wrap, mine[1], ctx); return; }
    if (sub === 'pool/incoming') { drawIncoming(wrap, ctx); return; }
    var fam = /^pool\/([0-9a-f]+)$/.exec(sub);
    if (fam) { drawFamily(wrap, fam[1], ctx); return; }
    if (ctx.host.moved) { ctx.host.moved('pool', '', j.name); }
    wrap.appendChild(el('p', 'evo-lede', 'Genes are what your Rouh can do. In the ' + j.name + ' Rouhs give them to each other. ' +
      'Nothing is sold: genes are given, and thanked.'));
    if (!j.on) { wrap.appendChild(el('p', 'glog-off', 'The ' + j.name + ' is switched off here (gene_pool, under Other switches in Evolution, Mutations).')); }
    said(wrap);
    drawStanding(wrap, j);
    var r = j.review || { review: 0, approved: 0, sent: 0 };
    var outBits = [];
    if (r.review) { outBits.push(r.review + ' to review'); }
    if (r.approved) { outBits.push(r.approved + ' approved'); }
    if (r.sent) { outBits.push(r.sent + ' in the ' + j.name); }
    var inBits = [];
    if (j.installed.length) { inBits.push(j.installed.length + ' installed'); }
    var ups = j.installed.filter(function (g) { return g.update; }).length;
    if (ups) { inBits.push(ups + (ups === 1 ? ' update waits' : ' updates wait')); }
    var ways = el('div', 'pool-ways');
    ways.appendChild(wayCard('Outgoing genes', 'Your genes, given to other Rouhs', (j.mode_names || {})[j.mode] || 'Manual',
      (j.modes || {})[j.mode] || '', outBits.join(' · '), '/evolution/pool/outgoing', function () { ctx.go('pool/outgoing'); }));
    ways.appendChild(wayCard('Incoming genes', 'Genes of other Rouhs, into yours', (j.incoming_names || {})[j.incoming] || 'Manual',
      (j.incomings || {})[j.incoming] || '', inBits.join(' · '), '/evolution/pool/incoming', function () { ctx.go('pool/incoming'); }));
    wrap.appendChild(ways);
  }

  /* Where this Rouh stands with the Pool: joined at its birth, by itself, or why not yet. */
  function drawStanding(wrap, j) {
    var st = j.join || {};
    var p = el('p', st.state === 'member' ? 'glog-meta pool-standing' : 'pool-closed pool-standing', st.said || '');
    if (st.state === 'unborn' || st.state === 'independent' || st.state === 'dead') {
      p.appendChild(document.createTextNode(' '));
      var a = el('a', 'evo-link', 'Your Rouh');
      a.href = (j.born && j.born.route) || '/anatomy/your-rouh';
      p.appendChild(a);
    }
    wrap.appendChild(p);
    if (st.state === 'member' && j.membership && j.membership.error) { wrap.appendChild(el('p', 'evo-error', j.membership.error)); }
  }

  function wayCard(title, sub, setting, words, bits, href, go) {
    var a = link('', href, 'pool-way', go);
    var top = el('span', 'evo-row-top');
    top.appendChild(el('span', 'pool-way-h', title));
    top.appendChild(chip(setting, setting === 'Manual' || setting === 'Off' ? 'evo-quiet' : 'glog-shared'));
    a.appendChild(top);
    a.appendChild(el('span', 'evo-row-sub', sub));
    a.appendChild(el('span', 'evo-row-said', words));
    if (bits) { a.appendChild(el('span', 'evo-row-sub', bits)); }
    return a;
  }

  /* One setting of the Pool, Outgoing's or Incoming's, in the same control: a choice of a few, the
     default said, what each does in a sentence, and a confirmation for the one that needs it. */
  function settingBox(wrap, ctx, s) {
    var box = el('fieldset', 'pool-modes');
    var lg = el('legend', null, s.legend);
    box.appendChild(lg);
    if (s.about) {
      var info = button('tc-info', 'i');
      info.setAttribute('aria-expanded', 'false');
      info.setAttribute('aria-label', s.aboutLabel);
      var about = el('div', 'pool-about');
      // Kept open across a redraw, as the person left it.
      about.hidden = !P.about[s.name];
      info.setAttribute('aria-expanded', String(!about.hidden));
      s.about.forEach(function (t) { about.appendChild(el('p', null, t)); });
      info.addEventListener('click', function () {
        about.hidden = !about.hidden;
        P.about[s.name] = !about.hidden;
        info.setAttribute('aria-expanded', String(!about.hidden));
      });
      lg.appendChild(info);
      box.appendChild(about);
    }
    Object.keys(s.words).forEach(function (k) {
      var row = el('label', 'pool-mode' + (s.value === k ? ' on' : ''));
      var input = el('input');
      input.type = 'radio';
      input.name = s.name;
      input.value = k;
      input.checked = s.value === k;
      input.disabled = !s.admin || P.busy;
      row.appendChild(input);
      var words = el('span', 'pool-mode-w');
      words.appendChild(el('strong', null, s.names[k] + (k === 'manual' ? ' (the default)' : '')));
      words.appendChild(el('span', 'evo-hint', s.words[k]));
      row.appendChild(words);
      input.addEventListener('change', function () {
        if (k !== s.confirm) { act(ctx, s.path, { mode: k }); return; }
        input.checked = false;
        P.sure = s.name + ':' + k;
        ctx.redraw();
      });
      box.appendChild(row);
    });
    if (s.by && s.value !== 'manual') { box.appendChild(el('p', 'evo-hint', 'Chosen by ' + s.by + (s.when ? ' ' + s.when : '') + '.')); }
    if (!s.admin) { box.appendChild(el('p', 'evo-hint', 'Only an administrator of this Rouh changes it.')); }
    if (s.confirm && P.sure === s.name + ':' + s.confirm) {
      var g = el('div', 'glog-sure');
      g.setAttribute('role', 'group');
      g.setAttribute('aria-label', 'Confirm ' + s.names[s.confirm]);
      g.appendChild(el('p', null, s.confirmWords));
      var yes = button('ctl small danger', s.confirmYes);
      yes.addEventListener('click', function () { P.sure = ''; act(ctx, s.path, { mode: s.confirm, confirm: true }); });
      var no = button('ctl small', 'Cancel');
      no.addEventListener('click', function () { P.sure = ''; ctx.redraw(); });
      g.appendChild(yes); g.appendChild(no);
      box.appendChild(g);
      setTimeout(function () { yes.focus(); }, 0);
    }
    wrap.appendChild(box);
  }

  var IN_CODE = 'Already here: in your Rouh’s code';

  function relationName(r, long) {
    if (r === 'root') { return 'The gene'; }
    if (r === 'sub') { return long ? 'Sub-gene, grown by its giver' : 'Sub-gene'; }
    if (r === 'version') { return long ? 'The same gene, given by another Rouh' : 'Another Rouh’s version'; }
    return long ? 'Fork, made different' : 'Fork';
  }

  /* ---- Outgoing genes: the setting, and the review list of your genes on their way to the Pool ---- */

  function link(text, href, cls, go) {
    var a = el('a', cls, text);
    a.href = href;
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
      e.preventDefault();
      go();
    });
    return a;
  }

  function backTo(text, href, go) { return link('← ' + text, href, 'evo-back', go); }

  function drawOut(wrap, ctx) {
    var j = P.data, o = P.out;
    wrap.appendChild(backTo(j.name, '/evolution/pool', function () { ctx.go('pool'); }));
    if (ctx.host.moved) { ctx.host.moved('pool', 'outgoing', 'Outgoing genes'); }
    wrap.appendChild(el('h4', 'evo-gene-name', 'Outgoing genes'));
    if (!o) { wrap.appendChild(el('p', 'evo-loading', 'Reading your genes…')); return; }
    said(wrap);
    drawMode(wrap, o, ctx);
    if (!o.joined) {
      wrap.appendChild(el('p', 'pool-closed', 'Nothing is sent: this Rouh is not in the ' + o.name + ' yet. ' + ((j.join && j.join.said) || '') +
        ' What you approve goes when it joins, and only that.'));
    }
    var show = P.show;
    if (!show) {
      var rev = o.shows.filter(function (x) { return x.id === 'review'; })[0];
      show = rev && rev.count ? 'review' : 'all';
    }
    var bar = el('div', 'evo-bar');
    var tabs = el('div', 'evo-views');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Which genes');
    o.shows.forEach(function (x) {
      var b = button('evo-vtab' + (show === x.id ? ' on' : ''), x.name);
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', show === x.id ? 'true' : 'false');
      b.appendChild(el('span', 'evo-count', x.count));
      b.addEventListener('click', function () { P.show = x.id; ctx.redraw(); });
      tabs.appendChild(b);
    });
    bar.appendChild(tabs);
    var find = el('input', 'evo-find');
    find.type = 'search';
    find.placeholder = 'Find a gene';
    find.setAttribute('aria-label', 'Find one of your genes');
    find.value = P.oq;
    bar.appendChild(find);
    wrap.appendChild(bar);
    var ul = el('ul', 'evo-list pool-out');
    function fill() {
      ul.textContent = '';
      var q = P.oq.toLowerCase();
      o.rows.filter(function (r) {
        return (show === 'all' || r.show === show) && (!q || (r.name + ' ' + r.sentence + ' ' + r.key).toLowerCase().indexOf(q) >= 0);
      }).forEach(function (r) {
        var li = el('li', 'evo-row');
        var b = link('', '/evolution/pool/outgoing/' + r.id, 'evo-row-btn', function () { ctx.go('pool/outgoing/' + r.id); });
        var top = el('span', 'evo-row-top');
        top.appendChild(el('span', 'evo-row-name', r.name));
        top.appendChild(chip(r.state_words, 'pool-state-' + (r.state || 'none')));
        b.appendChild(top);
        if (r.sentence) { b.appendChild(el('span', 'evo-row-said', r.sentence)); }
        var bits = [r.nodes + (r.nodes === 1 ? ' node' : ' nodes'), r.origin_name, 'changed ' + r.changed_words];
        if (r.uses) { bits.push(r.uses + (r.uses === 1 ? ' use' : ' uses') + ' in 30 days'); }
        if (r.blocks) { bits.push(r.blocks + (r.blocks === 1 ? ' check blocks it' : ' checks block it')); }
        else if (r.looks) { bits.push(r.looks + ' to look at'); }
        b.appendChild(el('span', 'evo-row-sub', bits.join(' · ')));
        li.appendChild(b);
        ul.appendChild(li);
      });
      if (!ul.childNodes.length) { ul.appendChild(el('li', 'glog-none', q ? 'No gene has those words.' : 'None here.')); }
    }
    find.addEventListener('input', function () { P.oq = find.value; fill(); });
    fill();
    wrap.appendChild(ul);
  }

  function drawMode(wrap, o, ctx) {
    settingBox(wrap, ctx, {
      legend: 'Outgoing: how your genes leave', name: 'poolMode', path: API + '/mode', admin: o.admin,
      value: o.mode, words: o.modes, names: o.mode_names || { manual: 'Manual', preselect: 'Suggested', auto: 'Automatic' },
      by: o.mode_by, when: o.mode_words, confirm: 'auto', confirmYes: 'Yes, send by itself',
      confirmWords: 'Automatic sends every gene that passes every check, now and as your Rouh grows more, without asking you. ' +
        'A gene a check found something in still waits for you. Choosing Manual again stops it at once: what it approved and had not sent yet waits for you again; ' +
        'what it sent stays in the ' + o.name + ' until you take it out.',
      aboutLabel: 'What leaves your Rouh', about: [
        'A gene leaves as words only: its name, its sentence, what it does and a short description, with people’s names, addresses and numbers taken out. Never its code, a chat or a message.',
        'Before a gene leaves, checks look for secrets, which block it in every setting, and for names, addresses, private paths, outside accounts or money, which wait for you.',
        'Joining sent only your Rouh’s own name and its public key, which rouh.land already had from its birth. Your own name is never sent.',
        'Once a month, for each gene you gave or installed, a rough share of how much it is used goes too: never a count, a time or anything you said.'
      ]
    });
  }

  function drawOne(wrap, id, ctx) {
    var j = P.data, o = P.one;
    wrap.appendChild(backTo('Outgoing genes', '/evolution/pool/outgoing', function () { ctx.go('pool/outgoing'); }));
    if (!o) { wrap.appendChild(el('p', 'evo-loading', 'Reading what it would send…')); return; }
    if (o.missing) { wrap.appendChild(el('p', 'evo-error', o.missing)); return; }
    var g = o.gene;
    if (ctx.host.moved) { ctx.host.moved('pool', 'outgoing/' + id, g.name); }
    var head = el('div', 'evo-row-top');
    head.appendChild(el('h4', 'evo-gene-name', g.name));
    head.appendChild(chip(o.state_words, 'pool-state-' + (o.state || 'none')));
    wrap.appendChild(head);
    if (g.sentence) { wrap.appendChild(el('p', 'evo-row-said', g.sentence)); }
    var meta = el('p', 'glog-meta', g.status_name + ' · ' + g.origin_name + (o.gene_id ? ' · id ' + o.gene_id : '') + ' · came ' + g.made_words + ' · ');
    meta.appendChild(link('its page in the gene log', '/evolution/mutations/log/' + g.id, 'evo-link', function () { ctx.go('log/' + g.id); }));
    wrap.appendChild(meta);
    said(wrap);
    if (!o.eligible) { wrap.appendChild(el('p', 'pool-closed', 'It cannot go to the ' + o.name + ': ' + o.why_not)); }
    if (o.eligible && !o.gene_id) {
      wrap.appendChild(el('p', 'pool-closed', 'It has no id in Rouh’s code (no gene manifest, and not in the gene map), so a Rouh built from the same code cannot tell that it already has it. Preselect and Auto leave it to you.'));
    }
    var dup = o.pooled;
    if (dup && o.eligible) {
      wrap.appendChild(el('p', 'pool-closed pool-pooled', 'Already in the ' + o.name + ', given by ' + dup.giver + '. ' + (dup.same
        ? 'Its words here are the same as theirs, so there is nothing to send.'
        : 'Its words here differ from theirs: approving sends it as a new version of their gene, not as a new gene.')));
    }
    var live = o.nodes.filter(function (n) { return n.state !== 'skipped'; });
    var blocked = live.filter(function (n) { return n.state === 'blocked'; }).length;
    var waiting = live.filter(function (n) { return n.state === 'review' || n.state === 'changed'; }).length;
    wrap.appendChild(el('p', 'evo-hint', 'Below is everything it would send, node by node, exactly as it would leave. ' +
      'No code leaves: only these words. ' + (o.joined ? '' : 'Nothing is sent before this Rouh joins the ' + o.name + '.')));
    if (o.admin && o.eligible) {
      var acts = el('div', 'evo-acts pool-review-acts');
      if (waiting && !(dup && dup.same)) {
        var yes = button('ctl small primary', (o.joined ? 'Approve and send ' : 'Approve ') + (waiting === 1 ? 'it' : 'these ' + waiting));
        yes.disabled = P.busy;
        yes.addEventListener('click', function () {
          var shas = {};
          o.nodes.forEach(function (n) { shas[String(n.id)] = n.sha; });
          act(ctx, API + '/out/' + g.id + '/approve', { shas: shas });
        });
        acts.appendChild(yes);
      }
      if (g.share !== 'declined') {
        var no = button('ctl small', g.share === 'selected' ? 'Take it out of the ' + o.name : 'Decline');
        no.disabled = P.busy;
        no.addEventListener('click', function () {
          act(ctx, g.share === 'selected' ? '/api/genes/log/' + g.id + '/share' : API + '/out/' + g.id + '/decline',
              g.share === 'selected' ? { share: false } : {});
        });
        acts.appendChild(no);
      }
      if (acts.childNodes.length) { wrap.appendChild(acts); }
      if (blocked) { wrap.appendChild(el('p', 'evo-error', blocked + (blocked === 1 ? ' node is' : ' nodes are') + ' blocked by a check and never sent until you edit what ' + (blocked === 1 ? 'it sends' : 'they send') + '.')); }
    }
    var ul = el('ul', 'glog-tree glog-tree-top pool-out-tree');
    ul.setAttribute('aria-label', 'What ' + g.name + ' would send');
    var kids = {};
    o.nodes.forEach(function (n) { var k = n.parent && o.nodes.some(function (x) { return x.id === n.parent; }) ? n.parent : 0; (kids[k] = kids[k] || []).push(n); });
    (kids[0] || []).forEach(function (n) { ul.appendChild(outNode(n, kids, o, ctx, true)); });
    wrap.appendChild(ul);
  }

  var WHERE = { name: 'its name', sentence: 'its sentence', contract: 'its contract', brief: 'its brief' };

  function outNode(n, kids, o, ctx, first) {
    var li = el('li', 'glog-node pool-node');
    var card = el('article', 'evo-card pool-out-card');
    card.setAttribute('aria-label', n.body.name);
    var top = el('div', 'evo-card-top');
    top.appendChild(chip(relationName(n.relation, false), 'evo-quiet'));
    top.appendChild(chip(n.state_words, 'pool-state-' + n.state));
    if (n.edited.length) { top.appendChild(chip('Edited by you', 'glog-shared')); }
    card.appendChild(top);
    card.appendChild(el('h4', 'evo-card-name', n.body.name));
    if (n.checks.length) {
      var cl = el('ul', 'pool-checks');
      cl.setAttribute('aria-label', 'What the checks found');
      n.checks.forEach(function (c) {
        var item = el('li', 'pool-check pool-check-' + c.level);
        item.appendChild(el('strong', null, c.level === 'block' ? 'Blocks it: ' : 'Look at: '));
        item.appendChild(document.createTextNode(c.what + ' In ' + (WHERE[c.where] || c.where) + ': “' + c.found + '”.'));
        cl.appendChild(item);
      });
      card.appendChild(cl);
    }
    if (n.approved_by && n.state !== 'review') {
      card.appendChild(el('p', 'evo-hint', (n.state === 'changed' || n.state === 'blocked' ? 'An earlier version was approved by ' : 'Approved by ') +
        (n.approved_by === 'automatic' ? 'auto' : n.approved_by) + (n.approved_words ? ' ' + n.approved_words : '') +
        (n.synced_words && n.state === 'sent' ? ' · sent ' + n.synced_words : '') + '.'));
    }
    if (n.error) { card.appendChild(el('p', 'evo-error', n.error)); }
    var body = el('details', 'pool-body');
    if (first || n.state === 'blocked' || P.editing === n.id) { body.open = true; }
    body.appendChild(el('summary', null, 'What it sends'));
    var dl = el('dl', 'glog-contract');
    [['Name', n.body.name], ['Sentence', n.body.sentence], ['Brief', n.body.brief]].forEach(function (r) {
      dl.appendChild(el('dt', null, r[0]));
      dl.appendChild(el('dd', r[0] === 'Brief' ? 'pool-pre' : null, r[1] || '(empty)'));
    });
    dl.appendChild(el('dt', null, 'Contract'));
    dl.appendChild(el('dd', 'pool-pre', JSON.stringify(n.body.contract, null, 2)));
    body.appendChild(dl);
    var raw = el('details', 'pool-raw');
    raw.appendChild(el('summary', null, 'Exactly as sent'));
    raw.appendChild(el('pre', 'pool-pre', JSON.stringify(n.body, null, 2)));
    body.appendChild(raw);
    if (o.admin && o.eligible) {
      if (P.editing === n.id) { body.appendChild(editForm(n, ctx)); }
      else {
        var ed = button('ctl small', 'Edit what it sends');
        ed.addEventListener('click', function () { P.editing = n.id; ctx.redraw(); });
        body.appendChild(ed);
      }
    }
    card.appendChild(body);
    li.appendChild(card);
    var k = kids[n.id] || [];
    if (k.length) {
      var ul = el('ul', 'glog-tree');
      k.forEach(function (x) { ul.appendChild(outNode(x, kids, o, ctx, false)); });
      li.appendChild(ul);
    }
    return li;
  }

  function editForm(n, ctx) {
    var form = el('form', 'pool-form pool-edit');
    form.setAttribute('aria-label', 'Edit what ' + n.body.name + ' sends');
    var name = el('input'); name.id = 'poolEditName' + n.id; name.value = n.body.name; name.maxLength = 160;
    field(form, 'Name', name);
    var sentence = el('textarea'); sentence.id = 'poolEditSentence' + n.id; sentence.rows = 2; sentence.value = n.body.sentence; sentence.maxLength = 600;
    field(form, 'Sentence', sentence);
    var brief = el('textarea'); brief.id = 'poolEditBrief' + n.id; brief.rows = 8; brief.value = n.body.brief; brief.maxLength = 4000;
    field(form, 'Brief', brief, 'Its contract is what the gene does, so it is not edited here: change the gene, and its contract follows.');
    var acts = el('div', 'evo-acts');
    var save = button('ctl small primary', 'Save');
    save.type = 'submit';
    acts.appendChild(save);
    if (n.edited.length) {
      var back = button('ctl small', 'Use the log’s own words');
      back.addEventListener('click', function () {
        P.editing = 0;
        act(ctx, API + '/out/' + n.id + '/edit', { name: '', sentence: '', brief: '' });
      });
      acts.appendChild(back);
    }
    var cancel = button('ctl small', 'Cancel');
    cancel.addEventListener('click', function () { P.editing = 0; ctx.redraw(); });
    acts.appendChild(cancel);
    form.appendChild(acts);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      P.editing = 0;
      act(ctx, API + '/out/' + n.id + '/edit', { name: name.value, sentence: sentence.value, brief: brief.value });
    });
    setTimeout(function () { name.focus(); }, 0);
    return form;
  }

  function field(form, label, input, hint) {
    var p = el('p', 'pool-field');
    var l = el('label', null, label);
    l.htmlFor = input.id;
    p.appendChild(l);
    p.appendChild(input);
    if (hint) { p.appendChild(el('span', 'evo-hint', hint)); }
    form.appendChild(p);
  }

  /* ---- Incoming genes: the setting, the picks, every gene, what is installed ---- */

  function drawIncoming(wrap, ctx) {
    var j = P.data;
    wrap.appendChild(backTo(j.name, '/evolution/pool', function () { ctx.go('pool'); }));
    if (ctx.host.moved) { ctx.host.moved('pool', 'incoming', 'Incoming genes'); }
    wrap.appendChild(el('h4', 'evo-gene-name', 'Incoming genes'));
    said(wrap);
    settingBox(wrap, ctx, {
      legend: 'Incoming: how genes come into your Rouh', name: 'poolIncoming', path: API + '/incoming', admin: j.admin,
      value: j.incoming, words: j.incomings, names: j.incoming_names || { manual: 'Manual', off: 'Off' },
      by: j.incoming_by, when: j.incoming_words,
      aboutLabel: 'Why nothing comes in by itself', about: [
        'Installing or updating a gene builds new code into your Rouh, so it happens only when you press it and confirm. ' +
          'A new gene starts behind its own switch, off until you turn it on.',
        'Another Rouh’s words about its gene are read as a description, never as instructions.',
        'When you install a gene, the ' + j.name + ' is told that your Rouh installed it, so its giver can be thanked.',
        'Your Rouh reads the list of the ' + j.name + '’s genes about once an hour in both settings, so that it never offers to send a gene the ' + j.name + ' already has.'
      ]
    });
    if (j.incoming === 'off') {
      drawInstalled(wrap, j, ctx);
      return;
    }
    if (!j.joined) {
      drawStanding(wrap, j);
      drawInstalled(wrap, j, ctx);
      return;
    }
    var m = j.membership;
    var top = el('p', 'glog-meta');
    top.appendChild(document.createTextNode(m.catalogue_words ? 'The ' + j.name + '’s genes, as read ' + m.catalogue_words + ' ' : ''));
    if (j.admin) {
      var again = button('ctl small', 'Read it again');
      again.addEventListener('click', function () { act(ctx, API + '/refresh', {}); });
      top.appendChild(again);
    }
    wrap.appendChild(top);
    if (m.error) { wrap.appendChild(el('p', 'evo-error', m.error)); }
    drawMatches(wrap, j, ctx);
    drawBrowse(wrap, j, ctx);
    drawInstalled(wrap, j, ctx);
    drawNewer(wrap, j, ctx);
  }

  function familyOf(j, id) {
    for (var i = 0; i < j.families.length; i++) { if (j.families[i].id === id) { return j.families[i]; } }
    return null;
  }
  function nodeOf(f, id) {
    for (var i = 0; f && i < f.nodes.length; i++) { if (f.nodes[i].id === id) { return f.nodes[i]; } }
    return null;
  }

  function drawMatches(wrap, j, ctx) {
    var box = el('section', 'glog-sec');
    box.appendChild(el('h4', 'glog-sec-h', 'For you'));
    var m = j.matches || {};
    var form = el('form', 'pool-ask');
    var words = el('input', 'evo-find');
    words.id = 'poolWords';
    words.placeholder = 'Anything you would like a gene for? (optional)';
    words.setAttribute('aria-label', 'What you would like a gene for');
    words.value = P.words || m.words || '';
    words.addEventListener('input', function () { P.words = words.value; });
    form.appendChild(words);
    var find = button('ctl small primary', P.busy ? 'Picking…' : (m.picks.length ? 'Pick again' : 'Find genes for me'));
    find.type = 'submit';
    find.disabled = P.busy;
    form.appendChild(find);
    form.addEventListener('submit', function (e) { e.preventDefault(); act(ctx, API + '/match', { words: words.value }); });
    box.appendChild(form);
    box.appendChild(el('p', 'evo-hint', 'A model reads how you use your Rouh (your genes and how much you use ' +
      'each, never a chat) and the ' + j.name + '’s genes, and picks the gene and the branch of it that fit you.'));
    if (!m.picks.length) {
      box.appendChild(el('p', 'evo-hint', m.when ? 'Nothing in the ' + j.name + ' fits you better than what you have (' + m.when + ').' : 'No picks yet.'));
    }
    var ul = el('ul', 'pool-picks');
    m.picks.forEach(function (p) {
      var f = familyOf(j, p.family), n = nodeOf(f, p.node);
      if (!f) { return; }
      var li = el('li', 'pool-pick');
      var head = el('div', 'evo-row-top');
      head.appendChild(el('span', 'evo-row-name', n ? n.name : f.name));
      if (n && n.relation !== 'root') { head.appendChild(chip(n.relation === 'sub' ? 'a sub-gene of ' + f.name : n.relation === 'version' ? 'another Rouh’s version of ' + f.name : 'a fork of ' + f.name, 'evo-quiet')); }
      head.appendChild(chip('fits ' + p.fit + ' of 5', 'evo-quiet'));
      li.appendChild(head);
      if (n && n.sentence) { li.appendChild(el('p', 'evo-row-said', n.sentence)); }
      li.appendChild(el('p', 'pool-why', 'Why: ' + p.why));
      if (p.fork) { li.appendChild(el('p', 'pool-fork-idea', 'Made different for you: ' + p.fork)); }
      var acts = el('div', 'evo-acts');
      var open = button('ctl small', 'Open');
      open.addEventListener('click', function () { P.open = p.fork ? 'fork:' + p.node + ':' + p.fork : ''; ctx.go('pool/' + f.id); });
      acts.appendChild(open);
      li.appendChild(acts);
      ul.appendChild(li);
    });
    box.appendChild(ul);
    if (m.when && m.picks.length) { box.appendChild(el('p', 'evo-hint', 'Picked ' + m.when + (m.model ? ' by ' + m.model : '') + '.')); }
    wrap.appendChild(box);
  }

  function drawBrowse(wrap, j, ctx) {
    var box = el('section', 'glog-sec');
    box.appendChild(el('h4', 'glog-sec-h', 'Every gene · ' + j.families.length));
    var find = el('input', 'evo-find');
    find.type = 'search';
    find.placeholder = 'Find a gene';
    find.setAttribute('aria-label', 'Find a gene in the ' + j.name);
    find.value = P.q;
    box.appendChild(find);
    var ul = el('ul', 'evo-list pool-families');
    function fill() {
      ul.textContent = '';
      var q = P.q.toLowerCase();
      j.families.filter(function (f) {
        return !q || f.nodes.some(function (n) { return (n.name + ' ' + n.sentence + ' ' + n.giver).toLowerCase().indexOf(q) >= 0; });
      }).forEach(function (f) {
        var root = f.nodes[0] || {};
        var s = root.signals || {};
        var li = el('li', 'evo-row');
        var b = button('evo-row-btn');
        var top = el('span', 'evo-row-top');
        top.appendChild(el('span', 'evo-row-name', f.name));
        if (f.nodes.some(function (n) { return n.mine; })) { top.appendChild(chip('Yours', 'glog-shared')); }
        if (f.nodes.some(function (n) { return n.here; })) { top.appendChild(chip('Installed here', 'glog-origin-pool')); }
        if (f.in_code) { top.appendChild(chip(IN_CODE, 'glog-origin-pool pool-in-code')); }
        if (f.newer) { top.appendChild(chip(f.newer.giver + ' has a newer version', 'glog-shared')); }
        if (f.nodes.length > 1) { top.appendChild(chip(f.nodes.length + ' in its family', 'evo-quiet')); }
        b.appendChild(top);
        if (root.sentence) { b.appendChild(el('span', 'evo-row-said', root.sentence)); }
        b.appendChild(el('span', 'evo-row-sub', 'Given by ' + root.giver + ' · score ' + s.score + ' · ' +
          (s.installs || 0) + (s.installs === 1 ? ' install' : ' installs') + ' · ' + (s.thanks || 0) + ' thanks'));
        b.addEventListener('click', function () { ctx.go('pool/' + f.id); });
        li.appendChild(b);
        ul.appendChild(li);
      });
      if (!ul.childNodes.length) { ul.appendChild(el('li', 'glog-none', j.families.length ? 'No gene has those words.' : 'No gene has been given yet.')); }
    }
    find.addEventListener('input', function () { P.q = find.value; fill(); });
    fill();
    box.appendChild(ul);
    wrap.appendChild(box);
  }

  function drawInstalled(wrap, j, ctx) {
    if (!j.installed.length) { return; }
    var box = el('section', 'glog-sec');
    box.appendChild(el('h4', 'glog-sec-h', 'Installed from the ' + j.name + ' · ' + j.installed.length));
    var ul = el('ul', 'evo-list');
    j.installed.forEach(function (g) {
      var li = el('li', 'evo-row');
      var b = button('evo-row-btn');
      var top = el('span', 'evo-row-top');
      top.appendChild(el('span', 'evo-row-name', g.name));
      top.appendChild(chip(g.status_name, 'glog-status-' + g.status));
      b.appendChild(top);
      var o = g.pool_origin || {};
      if (g.update) { top.appendChild(chip('An update waits', 'glog-shared')); }
      b.appendChild(el('span', 'evo-row-sub', 'Given by ' + (o.giver || 'another Rouh') + (o.how === 'fork' ? ' · made different: “' + o.words + '”' : ' · as it is') +
        (o.run ? ' · run ' + o.run : '')));
      b.addEventListener('click', function () { ctx.go('log/' + g.id); });
      li.appendChild(b);
      if (g.update && j.admin) {
        var up = el('div', 'pool-update');
        up.appendChild(el('p', 'evo-hint', 'Its giver changed it' + (g.update.contract_changed ? ', and what it does' : '') + ': “' + g.update.sentence + '”.'));
        var go = button('ctl small', 'Update…');
        go.addEventListener('click', function () {
          up.textContent = '';
          var sure = el('div', 'glog-sure');
          sure.setAttribute('role', 'group');
          sure.setAttribute('aria-label', 'Confirm updating ' + g.name);
          sure.appendChild(el('p', null, 'A run changes ' + g.name + ' in your Rouh to the new version, keeping what you made different. ' +
            'If it is wrong, turn it off on its page in the gene log, or take it out.'));
          var yes = button('ctl small primary', 'Yes, update it');
          yes.addEventListener('click', function () { act(ctx, API + '/update', { gene: g.id, confirm: true }); });
          var no = button('ctl small', 'Cancel');
          no.addEventListener('click', function () { ctx.redraw(); });
          sure.appendChild(yes); sure.appendChild(no);
          up.appendChild(sure);
          yes.focus();
        });
        up.appendChild(go);
        li.appendChild(up);
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    wrap.appendChild(box);
  }

  function drawNewer(wrap, j, ctx) {
    if (!j.newer || !j.newer.length) { return; }
    var box = el('section', 'glog-sec');
    box.appendChild(el('h4', 'glog-sec-h', 'Newer in the ' + j.name + ' · ' + j.newer.length));
    var ul = el('ul', 'evo-list');
    j.newer.forEach(function (g) {
      var li = el('li', 'evo-row');
      var b = link('', '/evolution/pool/' + g.family, 'evo-row-btn', function () { ctx.go('pool/' + g.family); });
      var top = el('span', 'evo-row-top');
      top.appendChild(el('span', 'evo-row-name', g.name));
      top.appendChild(chip(g.giver + ' has a newer version', 'glog-shared'));
      b.appendChild(top);
      b.appendChild(el('span', 'evo-row-said', g.sentence ? '“' + g.sentence + '”' : g.name));
      b.appendChild(el('span', 'evo-row-sub', 'In your Rouh’s code · nothing is installed'));
      li.appendChild(b);
      ul.appendChild(li);
    });
    box.appendChild(ul);
    wrap.appendChild(box);
  }

  /* ---- one family ---- */

  function backLink(ctx) {
    return backTo('Incoming genes', '/evolution/pool/incoming', function () { ctx.go('pool/incoming'); });
  }

  function drawFamily(wrap, id, ctx) {
    var j = P.data;
    wrap.appendChild(backLink(ctx));
    var f = j.joined ? familyOf(j, id) : null;
    if (!f) {
      wrap.appendChild(el('p', 'evo-error', j.incoming === 'off' ? 'Incoming genes are Off: the ' + j.name + '’s genes are not shown.'
        : j.joined ? 'That gene is not in the ' + j.name + ' any more.' : 'This Rouh is not in the ' + j.name + ' yet.'));
      return;
    }
    if (ctx.host.moved) { ctx.host.moved('pool', f.id, f.name); }
    wrap.appendChild(el('h4', 'evo-gene-name', f.name));
    wrap.appendChild(el('p', 'evo-hint', 'One gene’s family: the gene, the sub-genes its giver grew, and the forks other Rouhs made different. ' +
      'Averages are shown only from ' + (j.at_least || 5) + ' Rouhs, and only ever relative.'));
    said(wrap);
    var byParent = {};
    f.nodes.forEach(function (n) { var k = n.parent && nodeOf(f, n.parent) ? n.parent : ''; (byParent[k] = byParent[k] || []).push(n); });
    var ul = el('ul', 'glog-tree glog-tree-top pool-tree');
    ul.setAttribute('aria-label', 'Family tree of ' + f.name);
    (byParent[''] || []).forEach(function (n) { ul.appendChild(nodeCard(n, f, byParent, j, ctx)); });
    wrap.appendChild(ul);
  }

  function signalsText(s, atLeast) {
    var bits = ['score ' + s.score + ' of 100' + (s.enough ? '' : ', from ' + s.reports + ' report' + (s.reports === 1 ? '' : 's') + ': too few to say much')];
    bits.push((s.installs || 0) + (s.installs === 1 ? ' install' : ' installs'));
    if (s.still_on_30 != null) { bits.push(Math.round(s.still_on_30 * 100) + '% still on after 30 days'); }
    if (s.still_on_90 != null) { bits.push(Math.round(s.still_on_90 * 100) + '% after 90'); }
    if (s.ai_mean != null) { bits.push('the models’ mean ' + s.ai_mean + ' of 5'); }
    if (s.marks) { bits.push('marked Essential by ' + (s.marks.essential || 0)); }
    if (s.forks) { bits.push(s.forks + (s.forks === 1 ? ' fork' : ' forks')); }
    bits.push((s.thanks || 0) + ' thanks');
    return bits.join(' · ');
  }

  function nodeCard(n, f, byParent, j, ctx) {
    var li = el('li', 'glog-node pool-node');
    var card = el('article', 'evo-card');
    card.setAttribute('aria-label', n.name);
    var top = el('div', 'evo-card-top');
    top.appendChild(chip(relationName(n.relation, true), 'evo-quiet'));
    top.appendChild(chip('Given by ' + n.giver, 'evo-quiet'));
    if (n.mine) { top.appendChild(chip('Yours', 'glog-shared')); }
    if (n.here) { top.appendChild(chip('Installed here', 'glog-origin-pool')); }
    card.appendChild(top);
    card.appendChild(el('h4', 'evo-card-name', n.name));
    if (n.sentence) { card.appendChild(el('p', 'evo-card-said', n.sentence)); }
    var c = n.contract || {}, t = c.touches || {};
    var dl = el('dl', 'glog-contract');
    [['Where it appears', c.where], ['What it may do', (t.permissions || []).join(', ')], ['Outside accounts', (t.accounts || []).join(', ')],
     ['Tables', (t.tables || []).join(', ')], ['Scheduled work', (t.jobs || []).join(', ')], ['How to remove it', c.remove]
    ].forEach(function (r) { if (r[1]) { dl.appendChild(el('dt', null, r[0])); dl.appendChild(el('dd', null, r[1])); } });
    card.appendChild(dl);
    card.appendChild(el('p', 'pool-signals', signalsText(n.signals || {}, j.at_least)));
    if (f.newer && f.newer.node === n.id) {
      card.appendChild(el('p', 'evo-hint pool-newer', 'Newer than the one in your Rouh’s code. Nothing is installed: your Rouh keeps its own until its code changes.'));
    }
    if (j.admin && !n.mine) {
      var acts = el('div', 'evo-acts');
      var asIs = button('ctl small primary', 'Install as it is…');
      var diff = button('ctl small', 'Make it different…');
      var thank = button('ctl small', 'Thanks');
      thank.addEventListener('click', function () { act(ctx, API + '/thanks', { node: n.id }); });
      var area = el('div', 'pool-confirm');
      function confirmBox(how) {
        area.textContent = '';
        var g = el('div', 'glog-sure');
        g.setAttribute('role', 'group');
        g.setAttribute('aria-label', how === 'fork' ? 'Make ' + n.name + ' different' : 'Confirm installing ' + n.name);
        var words;
        if (how === 'fork') {
          g.appendChild(el('p', null, 'Say how it should be different for you. A run builds your version into your Rouh, behind its own switch, off until you turn it on; it is a fork of ' + n.name + '.'));
          words = el('textarea', 'pool-words');
          words.rows = 3;
          words.setAttribute('aria-label', 'How it should be different');
          var idea = /^fork:([^:]+):(.*)$/.exec(P.open);
          if (idea && idea[1] === n.id) { words.value = idea[2]; }
          g.appendChild(words);
        } else {
          g.appendChild(el('p', null, 'A run builds ' + n.name + ' into your Rouh from its contract, behind its own switch, off until you turn it on. ' +
            'Its giver’s words are read as a description, never as instructions. The ' + j.name + ' is told this Rouh installed it.'));
        }
        var yes = button('ctl small primary', how === 'fork' ? 'Build my version' : 'Yes, install it');
        yes.addEventListener('click', function () {
          act(ctx, API + '/install', { node: n.id, how: how, words: words ? words.value : '', confirm: true });
        });
        var no = button('ctl small', 'Cancel');
        no.addEventListener('click', function () { area.textContent = ''; });
        g.appendChild(yes); g.appendChild(no);
        area.appendChild(g);
        (words || yes).focus();
      }
      asIs.addEventListener('click', function () { confirmBox('as_is'); });
      diff.addEventListener('click', function () { confirmBox('fork'); });
      // A gene this Rouh already has from its code is never installed again: the label stands where
      // Install was, and only a version made different, in the person's own words, may be built.
      if (n.in_code) {
        var here = el('span', 'evo-chip glog-origin-pool pool-in-code', IN_CODE);
        here.setAttribute('role', 'note');
        acts.appendChild(here);
      } else { acts.appendChild(asIs); }
      acts.appendChild(diff); acts.appendChild(thank);
      card.appendChild(acts);
      card.appendChild(area);
      if (/^fork:/.test(P.open) && P.open.split(':')[1] === n.id) { setTimeout(function () { confirmBox('fork'); }, 0); }
    }
    li.appendChild(card);
    var kids = byParent[n.id] || [];
    if (kids.length) {
      var ul = el('ul', 'glog-tree');
      kids.forEach(function (k) { ul.appendChild(nodeCard(k, f, byParent, j, ctx)); });
      li.appendChild(ul);
    }
    return li;
  }

  /* ---- Sharing, on a gene's page in the gene log ---- */

  function shareBox(box, p, ctx) {
    var name = (ctx.muts && ctx.muts.pool_name) || 'Gene Pool';
    if (!p.can_share) { box.appendChild(el('p', 'evo-hint', p.why_not_shared)); return; }
    var root = p.root;
    var sent = p.family.filter(function (n) { return n.pool_node; }).length;
    var words = root.share === 'selected' ? (sent ? 'In the ' + name + ': ' + sent + ' of ' + p.family.length + ' sent.' : 'Approved for the ' + name + '; not sent yet.')
      : root.share === 'proposed' ? 'Proposed for the ' + name + ', waiting for your review.'
      : root.share === 'declined' ? 'Declined: never sent.'
      : root.share === 'stopped' ? 'Taken out of the ' + name + '.'
      : 'Not chosen for the ' + name + '. Nothing of it is sent until you approve it.';
    box.appendChild(el('p', 'pool-share-state', words));
    var acts = el('div', 'evo-acts');
    acts.appendChild(link('See what it would send', '/evolution/pool/outgoing/' + root.id, 'ctl small primary pool-open', function () { ctx.go('pool/outgoing/' + root.id); }));
    if (root.share === 'selected') {
      var out = button('ctl small', 'Take it out of the ' + name);
      out.addEventListener('click', function () { sharing(ctx, '/api/genes/log/' + root.id + '/share', { share: false }); });
      acts.appendChild(out);
    }
    box.appendChild(acts);
  }

  function sharing(ctx, path, body) {
    if (window.RouhGeneLog && window.RouhGeneLog.said) { window.RouhGeneLog.said(''); }
    post(path, body).then(function (j) {
      if (window.RouhGeneLog) { window.RouhGeneLog.said((j && j.said) || 'Done.'); }
      ctx.reload();
    }, function (err) {
      if (window.RouhGeneLog) { window.RouhGeneLog.said(String((err && err.message) || err)); }
      ctx.reload();
    });
  }

  window.RouhGenePool = { load: load, draw: draw, shareBox: shareBox };
}());
