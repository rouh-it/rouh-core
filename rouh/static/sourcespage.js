/* Sources, at /sources/<a task's or step's folder>: that task's research pages
   with footnotes, newest first, and what their sources really say
   (`rouh/source_check.py`, `rouh/web/sources.py`). It is opened from the
   Sources section on the task's own page (`objectindex._sources_section`), and
   lists only what is inside that folder: Petar, 13 October 2026
   (fr_fce8f51c00d6), "Sources should not be in the main navigation, only in
   the sources of each task". A step's folder holds one page, which is opened
   at once.

   Built by the nightly feature run, night 10, 13 October 2026 (task 94, idea
   I-069), behind the switch `source_check`. Each page says how many of its
   sources to look at; opened, those come first, each with what the page says,
   what the source says and why, a way to the page at that source, and It
   holds, which keeps Petar's word for it for good. Nothing is drawn over the
   page itself: he asked for all of it to be here, on 13 October 2026.

   Since 17 October 2026 nothing is checked until Petar asks (fr_563bcb1bdb26):
   "make the check sources off by default and on demand with click of a
   button. I will be using it only for specific cases that require it". A
   page never checked is listed with Check sources, a page that changed since
   its check with Check again, and while one is being read the list is read
   again every few seconds, so it is seen filling in.

   The layer, its address and its row in the navigation are app/runs.js's
   (`sourcesOpen`), handed over through `window.RouhSourcesHost`. */
(function () {
  'use strict';

  var API = '/api/sources';
  var R = { open: false, folder: '', data: null, error: '', loading: false, seq: 0, page: '',
            pages: {}, all: {}, timer: 0, starting: {} };
  //: Being read because he asked (`source_check.ASKED`).
  var ASKED = 'asked';

  function host() { return window.RouhSourcesHost || {}; }
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
  function when(at) {
    if (!at) { return ''; }
    var d = new Date(at * 1000);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ', ' +
      d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  }
  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
  }
  function kindOf(s) { return s.held ? 'held' : (s.verdict || 'pending'); }
  function nameOf(kind, p) {
    // A source with no verdict on a check that stopped is not being read.
    return kind === 'pending' && p && p.state !== ASKED ? 'Not checked' : NAMES[kind];
  }

  var NAMES = { holds: 'Holds', partly: 'Says less', missing: 'Not in the source',
    otherwise: 'Says otherwise', unread: 'Could not be read', held: 'You said it holds',
    pending: 'Being checked' };
  var ORDER = ['partly', 'missing', 'otherwise', 'unread', 'held', 'holds', 'pending'];

  /* ---- reading ---- */

  function get(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || 'Rouh could not read that. Try again in a moment.'); }
        return j;
      });
    });
  }

  function load() {
    var seq = ++R.seq;
    R.loading = !R.data;
    R.error = '';
    if (R.loading) { draw(); }
    return get(API + '?task=' + encodeURIComponent(R.folder)).then(function (j) {
      if (seq !== R.seq || !j) { return; }
      R.loading = false;
      R.data = j;
      // One page here, as in a step's folder: it is what was pressed, so it is open.
      var only = (j.pages || []).length === 1 && j.pages[0].state !== 'unchecked' ? j.pages[0].doc : '';
      if (only && !R.page) { R.page = only; }
      if (host().named) { host().named(taskName(j.pages || [])); }
      // A page open below its row is read again too, so its sources keep up.
      if (R.page) { loadPage(R.page); }
      if (R.open) { draw(); }
      watch();
    }).catch(function (err) {
      if (seq !== R.seq) { return; }
      R.loading = false;
      R.error = String((err && err.message) || err);
      if (R.open) { draw(); }
    });
  }

  function loadPage(doc) {
    return get(API + '?doc=' + encodeURIComponent(doc)).then(function (j) {
      if (!j) { return; }
      R.pages[doc] = j;
      // Its line in the list says the same as what is open under it.
      ((R.data && R.data.pages) || []).forEach(function (p) {
        if (p.doc !== doc || !j.state) { return; }
        if (R.data.look != null && j.counts) { R.data.look += (j.counts.look || 0) - ((p.counts || {}).look || 0); }
        p.state = j.state;
        if (j.counts) { p.counts = j.counts; }
      });
      if (R.open) { draw(); }
    }).catch(function (err) {
      R.pages[doc] = { error: String((err && err.message) || err) };
      if (R.open) { draw(); }
    });
  }

  // While a page is being checked, read the list again every few seconds.
  function watch() {
    clearTimeout(R.timer);
    var busy = R.data && (R.data.pages || []).some(function (p) { return p.state === ASKED; });
    if (R.open && busy) { R.timer = setTimeout(load, 4000); }
  }

  // Check sources, or Check again: this page alone is read from now, and only
  // because he pressed it.
  function check(p, btn, err) {
    btn.disabled = true;
    R.starting[p.doc] = true;
    btn.textContent = 'Starting…';
    fetch(API, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc: p.doc, check: true })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || !j || j.error || !j.doc) {
          throw new Error((j && j.error) || 'Rouh could not start the check: it said ' + r.status + '.');
        }
        delete R.starting[p.doc];
        R.page = p.doc;
        delete R.pages[p.doc];
        load();
      });
    }).catch(function (e) {
      delete R.starting[p.doc];
      btn.disabled = false;
      btn.textContent = p.state === 'unchecked' ? 'Check sources' : 'Check again';
      if (err) { err.textContent = String((e && e.message) || e); err.hidden = false; }
    });
  }

  function toggle(doc) {
    R.page = R.page === doc ? '' : doc;
    if (R.page && !R.pages[R.page]) { loadPage(R.page); }
    draw();
  }

  function hold(doc, s, holds, btn, err) {
    btn.disabled = true;
    fetch(API, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc: doc, key: s.key, holds: holds })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || !j || j.error || !j.sources) {
          throw new Error((j && j.error) || 'Rouh could not keep that: it said ' + r.status + '.');
        }
        R.pages[doc] = j;
        // The page's count in the list moves with it.
        (R.data.pages || []).forEach(function (p) {
          if (p.doc === doc && j.counts) {
            R.data.look += (j.counts.look || 0) - (p.counts.look || 0);
            p.counts = j.counts;
          }
        });
        draw();
      });
    }).catch(function (e) {
      btn.disabled = false;
      err.textContent = String((e && e.message) || e);
      err.hidden = false;
    });
  }

  function openAt(doc, n) {
    if (host().go) { host().go('/task/' + doc + (n ? '#source-' + n : '')); }
  }

  /* ---- drawing ---- */

  function chip(kind, text) {
    var c = el('span', 'sc-chip sc-' + kind);
    c.appendChild(el('i', ''));
    c.appendChild(document.createTextNode(text));
    return c;
  }

  function pageChip(p) {
    var c = p.counts || {};
    if (p.state === 'unchecked') { return null; }
    if (p.state === ASKED) {
      return chip('pending', 'Checking, ' + (p.sources - (c.pending || 0)) + ' of ' + p.sources);
    }
    if (c.look) { return chip('partly', c.look + ' to look at'); }
    if (p.state === 'stopped') {
      return chip('pending', (p.sources - (c.pending || 0)) + ' of ' + p.sources + ' checked');
    }
    return chip('holds', 'All ' + p.sources + ' checked');
  }

  function item(doc, s) {
    var box = el('div', 'sc-item');
    var top = el('div', 'sc-top');
    top.appendChild(el('span', 'sc-num', '[' + s.n + ']'));
    top.appendChild(chip(kindOf(s), nameOf(kindOf(s), R.pages[doc]) || s.label));
    box.appendChild(top);
    var src = el('a', 'sc-src', s.title);
    src.href = s.url;
    src.target = '_blank';
    src.rel = 'noopener noreferrer';
    src.title = s.url;
    src.appendChild(el('span', 'sc-host', hostOf(s.url)));
    box.appendChild(src);
    var said = el('div', 'sc-said');
    var page = el('div', '');
    page.appendChild(el('span', 'sc-k', 'The page says'));
    (s.claims || []).forEach(function (c) { page.appendChild(el('blockquote', '', c)); });
    said.appendChild(page);
    if (s.quote) {
      var from = el('div', '');
      from.appendChild(el('span', 'sc-k', 'The source says'));
      from.appendChild(el('blockquote', 'sc-from sc-' + kindOf(s), s.quote));
      said.appendChild(from);
    }
    box.appendChild(said);
    if (s.why) { box.appendChild(el('p', 'sc-why', s.why)); }
    var acts = el('div', 'sc-acts');
    var go = button('ctl small', 'Open the page here', 'Open the page at source ' + s.n + ' in its Sources list');
    go.addEventListener('click', function () { openAt(doc, s.n); });
    acts.appendChild(go);
    var err = el('p', 'sc-error');
    err.hidden = true;
    var keep = button('ctl small', s.held ? 'Undo It holds' : 'It holds',
                      s.held ? 'Flag it again' : 'Keep your word that this source holds for what the page says');
    keep.addEventListener('click', function () { hold(doc, s, !s.held, keep, err); });
    acts.appendChild(keep);
    box.appendChild(acts);
    box.appendChild(err);
    return box;
  }

  function detail(p) {
    var d = R.pages[p.doc];
    var wrap = el('div', 'sc-detail');
    if (!d) { wrap.appendChild(el('p', 'sc-loading', 'Reading its sources…')); return wrap; }
    if (d.error) { wrap.appendChild(el('p', 'sc-error', d.error)); return wrap; }
    var srcs = d.sources || [];
    var tally = {};
    srcs.forEach(function (s) { var k = kindOf(s); tally[k] = (tally[k] || 0) + 1; });
    var chips = el('div', 'sc-tally');
    ORDER.forEach(function (k) { if (tally[k]) { chips.appendChild(chip(k, nameOf(k, d) + ' ' + tally[k])); } });
    var open = button('ctl small sc-openpage', 'Open the page');
    open.addEventListener('click', function () { openAt(p.doc, 0); });
    chips.appendChild(open);
    wrap.appendChild(chips);
    var look = srcs.filter(function (s) { return s.look; });
    var held = srcs.filter(function (s) { return s.held; });
    var fine = srcs.filter(function (s) { return !s.look && !s.held; });
    wrap.appendChild(el('h5', 'sc-sec', 'To look at'));
    if (look.length) {
      look.forEach(function (s) { wrap.appendChild(item(p.doc, s)); });
    } else {
      wrap.appendChild(el('p', 'sc-empty-line', p.state === ASKED
        ? 'Nothing so far. The rest are still being read.'
        : 'Every source checked says what the page says it says.'));
    }
    if (held.length) {
      wrap.appendChild(el('h5', 'sc-sec', 'You said these hold'));
      held.forEach(function (s) { wrap.appendChild(item(p.doc, s)); });
    }
    if (fine.length) {
      var shown = !!R.all[p.doc];
      var head = el('h5', 'sc-sec', (p.state === ASKED ? 'Holding so far, or being read: '
        : p.state === 'stopped' ? 'The ones that hold, or not checked: ' : 'The ones that hold: ') + fine.length);
      wrap.appendChild(head);
      if (shown) {
        var list = el('ul', 'sc-fine');
        fine.forEach(function (s) {
          var li = el('li', '');
          li.appendChild(el('span', 'sc-num', '[' + s.n + ']'));
          var a = el('a', '', s.title);
          a.href = s.url;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.title = s.url;
          li.appendChild(a);
          li.appendChild(chip(kindOf(s), nameOf(kindOf(s), d)));
          list.appendChild(li);
        });
        wrap.appendChild(list);
      } else {
        var more = button('ctl small sc-more', 'Show them');
        more.addEventListener('click', function () { R.all[p.doc] = true; draw(); });
        wrap.appendChild(more);
      }
    }
    return wrap;
  }

  function row(p) {
    var unchecked = p.state === 'unchecked';
    var li = el('li', 'sc-page' + (R.page === p.doc && !unchecked ? ' on' : ''));
    var line = el('div', 'sc-line');
    var head = unchecked ? el('div', 'sc-head sc-still') : button('sc-head');
    var what = el('span', 'sc-what');
    what.appendChild(el('span', 'sc-title', p.title));
    what.appendChild(el('span', 'sc-where', (p.step ? 'Step ' + p.step + ' · ' : '') +
      (unchecked ? p.sources + ' sources, not checked'
        : (p.state === ASKED ? 'asked ' : 'checked ') + when(p.checked_at))));
    head.appendChild(what);
    var c = pageChip(p);
    if (c) { head.appendChild(c); }
    if (!unchecked) {
      head.setAttribute('aria-expanded', R.page === p.doc ? 'true' : 'false');
      head.addEventListener('click', function () { toggle(p.doc); });
    }
    line.appendChild(head);
    var err = null;
    if (unchecked || ((p.changed || p.state === 'stopped') && p.state !== ASKED)) {
      var go = button('ctl small sc-check', R.starting[p.doc] ? 'Starting…'
        : unchecked ? 'Check sources' : 'Check again',
        unchecked ? 'Read each source this page cites against what it says'
          : p.changed ? 'The page changed since it was checked' : 'Read the sources not checked yet');
      go.disabled = !!R.starting[p.doc];
      err = el('p', 'sc-error');
      err.hidden = true;
      go.addEventListener('click', function () { check(p, go, err); });
      line.appendChild(go);
    }
    li.appendChild(line);
    if (err) { li.appendChild(err); }
    if (R.page === p.doc && !unchecked) { li.appendChild(detail(p)); }
    return li;
  }

  function draw() {
    var body = $('sourcesBody');
    var meta = $('sourcesMeta');
    if (!body) { return; }
    body.setAttribute('aria-busy', R.loading ? 'true' : 'false');
    var keep = body.scrollTop;
    body.textContent = '';
    var page = el('div', 'sc-wrap-in');
    body.appendChild(page);
    var d = R.data;
    if (d && d.off) {
      if (meta) { meta.textContent = ''; }
      var off = el('div', 'sc-empty');
      off.appendChild(el('p', 'sc-empty-h', 'Sources checked is switched off.'));
      off.appendChild(el('p', 'sc-empty-p', 'Turn it on in Evolution, Mutations.'));
      page.appendChild(off);
      return;
    }
    if (R.error) { page.appendChild(el('p', 'sc-error', R.error)); }
    if (R.loading) { page.appendChild(el('p', 'sc-loading', 'Reading the checked pages…')); return; }
    if (!d) { return; }
    var pages = d.pages || [];
    if (meta) {
      meta.textContent = pages.length
        ? pages.length + (pages.length === 1 ? ' page' : ' pages') + ' · ' +
          (d.look ? d.look + (d.look === 1 ? ' source' : ' sources') + ' to look at'
            : pages.some(function (p) { return p.state === ASKED; }) ? 'being checked'
            : pages.some(function (p) { return p.state !== 'unchecked'; }) ? 'nothing to look at' : 'not checked')
        : '';
    }
    var name = taskName(pages);
    page.appendChild(el('p', 'sc-lede', (name ? 'Pages with footnotes in ' + name + '. ' : '') +
      'Check sources reads each source a page cites against the sentence it is ' +
      'cited for, and says which ones do not hold.'));
    if (!pages.length) {
      var none = el('div', 'sc-empty');
      none.appendChild(el('p', 'sc-empty-h', 'No page here cites three sources or more.'));
      page.appendChild(none);
      return;
    }
    var list = el('ul', 'sc-list');
    pages.forEach(function (p) { list.appendChild(row(p)); });
    page.appendChild(list);
    body.scrollTop = keep;
  }

  /* ---- the layer ---- */

  // What the folder is called: the step's name when it is one step's, else its task's.
  function taskName(pages) {
    var steps = {}, tasks = {};
    pages.forEach(function (p) { steps[p.step || ''] = 1; tasks[p.task || ''] = 1; });
    var oneStep = Object.keys(steps), oneTask = Object.keys(tasks);
    var folderIsStep = /\/\d+-\d+\.[^/]*$/.test(R.folder);
    if (folderIsStep && oneStep.length === 1 && oneStep[0]) { return 'Step ' + oneStep[0]; }
    return oneTask.length === 1 && oneTask[0] ? 'Task ' + oneTask[0] : '';
  }

  function shown(folder) {
    folder = String(folder || '');
    if (folder !== R.folder) {
      // Another task's: nothing of the last one's is kept on the screen.
      R.folder = folder;
      R.data = null;
      R.page = '';
      R.pages = {};
      R.all = {};
      R.error = '';
      R.seq++;
    }
    R.open = true;
    load();
    draw();
  }
  function hidden() { R.open = false; clearTimeout(R.timer); }

  window.RouhSources = { shown: shown, hidden: hidden, reload: load };

  var x = $('sourcesClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
