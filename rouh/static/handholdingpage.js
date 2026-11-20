/* Handholding, at /handholding: the guided way into Rouh for someone who has never seen it
   (`rouh/handholding.py`, `rouh/web/handholding.py`, the words in `rouh/handholding.json`).

   Petar, 20 November 2026: "I want to be able to put a person that has never seen rouh and step
   by step the guide should lead him to using the absolute maximum of rouh." Designed on the full
   tier: journeys first (the first visit and coming back are the two most frequent: one Next step,
   always the first step not done), then one direction.

   Top to bottom: the hero (the ring, Next step, Ask anything), What Rouh is (a diagram of the
   concepts, each opening into a few sentences and See it), Your path (seven stages, each a
   checklist of steps with Try saying, Show me and Done), Lessons (searchable, filterable, each at
   /handholding/lessons/<id>), and Ask anything.

   Every word is the data file's; this only draws it. Done is kept per person on the server; a
   step Rouh can see for itself (a connection that is live, a first task) is ticked by itself and
   marked Detected. The layer, its address and its row in the navigation are app/runs.js's
   (`handholdingOpen`), handed over through `window.RouhHandholdingHost`. */
(function () {
  'use strict';

  var H = {
    open: false, page: '', lesson: '', data: null, error: '', loading: false, seq: 0,
    // Which stages and steps are open, by id; which concept is picked; the lesson filters.
    stages: {}, steps: {}, concept: '', q: '', area: '', level: '',
    // A step whose save failed, with the words to show on its row.
    failed: {}, arrived: false, said: '',
    // Where to scroll once a page is drawn; the feature switches as their own pages read them;
    // which area the tips are narrowed to.
    scrollTo: '', feat: {}, featRead: false, tipArea: ''
  };

  function host() { return window.RouhHandholdingHost || {}; }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }
  function button(text, cls, fn) {
    var b = el('button', cls, text);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }
  var SVG = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs) {
    var n = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  /** A line drawing of 24 by 24, from the data file's own `icon`. */
  function glyph(inner, size) {
    var s = svg('svg', { viewBox: '0 0 24 24', width: String(size || 20), height: String(size || 20),
                         fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
                         'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
    s.innerHTML = inner || '';
    return s;
  }
  /** A link: an address in Rouh opens in Rouh, a web address in a new tab. */
  function link(href, text, cls) {
    var a = el('a', cls || 'hh-link', text);
    a.href = href;
    if (/^https?:\/\//.test(href)) {
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
    } else {
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) { return; }
        if (!host().go) { return; }
        e.preventDefault();
        host().go(href);
      });
    }
    return a;
  }
  function plural(n, one, many) { return n === 1 ? one : many; }
  /** Show me or See it: a page in Rouh by its address, or one of Rouh's own controls pressed
      (the orb, the Voice button, the message box), which have no address. */
  function showLink(show, words, cls, key) {
    if (show.href) { return k(link(show.href, words, cls), key); }
    var b = k(button(words, cls + ' hh-press', function () { if (host().press) { host().press(show.press); } }), key);
    return b;
  }

  /* ---- what is done ---- */

  function content() { return (H.data && H.data.content) || { stages: [], concepts: [], lessons: [], pages: [] }; }
  /** The section's sub-pages, as the data file lists them; the one open, or the first. */
  function pages() { return content().pages || []; }
  function pageDef() {
    var all = pages();
    return all.filter(function (p) { return p.id === H.page; })[0] || all[0] || { id: '', views: ['hero'] };
  }
  /** The first page that draws a view, for a press that leads there: Next step, a lesson's way back. */
  function pageWith(view) {
    return pages().filter(function (p) { return (p.views || []).indexOf(view) >= 0; })[0] || null;
  }
  function goPage(id) {
    if (!id) { return; }
    if (host().go) { host().go('/handholding/' + id); }
  }
  function allSteps() {
    var out = [];
    (content().stages || []).forEach(function (s) {
      (s.steps || []).forEach(function (t) { out.push({ stage: s, step: t }); });
    });
    return out;
  }
  function detected(id) { return !!(H.data && H.data.detected && H.data.detected[id]); }
  function ticked(id) { return !!(H.data && H.data.progress && H.data.progress[id] > 0); }
  /** An optional step the person said is not for them: done, as far as the path is concerned. */
  function skipped(id) { return !!(H.data && H.data.progress && H.data.progress[id] < 0); }
  /** A connection whose live state Rouh knows is done only when Rouh sees it connected: a tick by
      hand would say it is set up while its badge says it is not. One whose state is not known, or
      that has none, is ticked by hand like any step. */
  function liveOnly(id) {
    var st = stepById(id);
    var key = st && st.connection && st.connection.key;
    var s = key ? status(key) : null;
    return !!(s && s.kind !== 'unknown');
  }
  function stepById(id) {
    var all = allSteps();
    for (var i = 0; i < all.length; i++) { if (all[i].step.id === id) { return all[i].step; } }
    return null;
  }
  function isDone(id) { return detected(id) || skipped(id) || (ticked(id) && !liveOnly(id)); }
  function counts() {
    var all = allSteps();
    var done = all.filter(function (x) { return isDone(x.step.id); }).length;
    return { done: done, all: all.length, pct: all.length ? Math.round(done * 100 / all.length) : 0 };
  }
  /** The first step not done; a step marked optional only once every other one is done. */
  function nextStep() {
    var all = allSteps();
    var later = null;
    for (var i = 0; i < all.length; i++) {
      if (isDone(all[i].step.id)) { continue; }
      if (!all[i].step.optional) { return all[i]; }
      if (!later) { later = all[i]; }
    }
    return later;
  }
  function stageCounts(stage) {
    var steps = stage.steps || [];
    return { done: steps.filter(function (t) { return isDone(t.id); }).length, all: steps.length };
  }
  /** What a connection's badge says, from what Rouh knows of it now. */
  function status(key) {
    var st = H.data && H.data.status;
    if (!key) { return null; }
    if (!st) { return { kind: 'unknown', words: 'Status unknown' }; }
    var s = st[key];
    if (!s) { return { kind: 'unknown', words: 'Status unknown' }; }
    return s;
  }

  /* ---- reading and saving ---- */

  function load() {
    var seq = ++H.seq;
    H.loading = !H.data;
    H.error = '';
    if (!H.data) { draw(); }
    return fetch('/api/handholding', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { location.href = '/login'; return null; }
        return r.json().catch(function () { return null; }).then(function (j) {
          if (seq !== H.seq) { return; }
          H.loading = false;
          if (!r.ok || !j || !j.content) {
            H.error = (j && j.error) || 'Handholding could not be read. Try again in a moment.';
          } else {
            H.data = j;
            if (!H.page) { H.page = pageDef().id; if (host().place) { host().place(H.page, H.lesson); } }
            if (!H.arrived) { arrive(); }
          }
          draw();
        });
      })
      .catch(function () {
        if (seq !== H.seq) { return; }
        H.loading = false;
        H.error = 'Handholding could not be read. Check the connection and try again.';
        draw();
      });
  }

  /** The first drawing with data: the stage holding the next step is open, the others closed. */
  function arrive() {
    H.arrived = true;
    var nx = nextStep();
    if (nx) { H.stages[nx.stage.id] = true; }
  }

  function save(id, done, skip) {
    var before = H.data.progress[id];
    if (done) { H.data.progress[id] = (skip ? -1 : 1) * Date.now() / 1000; } else { delete H.data.progress[id]; }
    delete H.failed[id];
    H.said = skip ? 'Left out: not for you.' : done ? 'Marked done.' : 'Marked not done.';
    draw();
    fetch('/api/handholding/progress', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: id, done: !!done, skip: !!skip })
    }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j || !j.progress) { var e = new Error(''); e.said = (j && j.error) || ''; throw e; }
        H.data.progress = j.progress;
        draw();
      });
    }).catch(function (e) {
      if (before) { H.data.progress[id] = before; } else { delete H.data.progress[id]; }
      H.failed[id] = (e && e.said) || 'That could not be saved. Check the connection and try again.';
      H.said = H.failed[id];
      draw();
    });
  }

  /* ---- pressing ---- */

  /** Put words in the message box, ready to send or change. */
  function say(words) {
    if (host().say) { host().say(words); return; }
  }
  /** Next step: the Next steps page, where the very next step is open at the top; without one,
      the step opened in place on the Journey. */
  function goNext() {
    var p = pageWith('next');
    if (p && p.id !== pageDef().id) { goPage(p.id); return; }
    var first = document.querySelector('#hh-next .hh-nextfirst .hh-step');
    if (!first) { return; }
    first.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' });
    var t = first.querySelector('.hh-saybtn') || first.querySelector('.hh-steptitle');
    if (t) { t.focus({ preventScroll: true }); }
  }
  function reduced() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  /** A lesson's address is under the page that holds the lessons; '' is that page, at its list. */
  function lessonsPage() { var p = pageWith('lessons'); return p ? p.id : ''; }
  function lessonHref(id) { return '/handholding/' + lessonsPage() + '/' + id; }
  function goLesson(id) {
    if (!lessonsPage()) { return; }
    if (!id) { H.scrollTo = 'hh-lessons'; }
    if (host().go) { host().go(id ? lessonHref(id) : '/handholding/' + lessonsPage()); }
    if (!id && pageDef().id === lessonsPage() && !H.lesson) { draw(); }
  }

  /* ---- drawing ---- */

  function draw() {
    var body = $('handholdingBody');
    if (!body || !H.open) { return; }
    var keep = document.activeElement && body.contains(document.activeElement) ? focusKey(document.activeElement) : '';
    var top = body.scrollTop;
    body.textContent = '';
    body.setAttribute('aria-busy', H.loading ? 'true' : 'false');
    var page = el('div', 'hh-page');
    body.appendChild(page);
    if (H.loading && !H.data) { page.appendChild(el('p', 'hh-wait', 'Reading your path')); return; }
    if (!H.data) {
      var e = el('div', 'hh-empty');
      e.appendChild(el('p', 'hh-empty-big', 'Handholding is not here yet'));
      e.appendChild(el('p', 'hh-empty-small', H.error));
      e.appendChild(button('Try again', 'hh-quiet', function () { load(); }));
      page.appendChild(e);
      return;
    }
    var def = pageDef();
    if (H.lesson) {
      page.appendChild(lessonPage(H.lesson));
    } else {
      (def.views || []).forEach(function (v) {
        var words = (content().sections || {})[v];
        var drawn = VIEWS[v] ? VIEWS[v](words ? Object.assign({}, def, { title: words.title, lede: words.lede || '' }) : def) : null;
        if (drawn) { page.appendChild(drawn); }
      });
    }
    if (H.lesson || (def.views || []).indexOf('hero') < 0) { page.appendChild(ask()); }
    var live = el('p', 'hh-sr', H.said);
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    page.appendChild(live);
    body.scrollTop = top;
    if (H.scrollTo && $(H.scrollTo)) {
      $(H.scrollTo).scrollIntoView({ block: 'start' });
      H.scrollTo = '';
    }
    if (keep) {
      var back = body.querySelector('[data-k="' + keep + '"]');
      if (back) { back.focus({ preventScroll: true }); }
    }
  }
  /** Each control that can hold focus carries a key, so a redraw puts focus back where it was. */
  function focusKey(n) { return (n && n.getAttribute && n.getAttribute('data-k')) || ''; }
  function k(n, key) { n.setAttribute('data-k', key); return n; }

  function ring(pct) {
    var wrap = el('div', 'hh-ring');
    wrap.setAttribute('role', 'img');
    wrap.setAttribute('aria-label', pct + ' percent of your path done');
    var r = 52, c = 2 * Math.PI * r;
    var s = svg('svg', { viewBox: '0 0 120 120', width: '120', height: '120', 'aria-hidden': 'true' });
    s.appendChild(svg('circle', { cx: '60', cy: '60', r: String(r), class: 'hh-ring-track' }));
    var arc = svg('circle', { cx: '60', cy: '60', r: String(r), class: 'hh-ring-arc',
                              'stroke-dasharray': String(c),
                              'stroke-dashoffset': String(c * (1 - pct / 100)),
                              transform: 'rotate(-90 60 60)' });
    s.appendChild(arc);
    wrap.appendChild(s);
    var mid = el('div', 'hh-ring-mid');
    mid.appendChild(el('span', 'hh-ring-pct', pct + '%'));
    mid.appendChild(el('span', 'hh-ring-word', 'done'));
    wrap.appendChild(mid);
    return wrap;
  }

  function hero() {
    var c = counts();
    var nx = nextStep();
    var sec = el('section', 'hh-hero');
    sec.setAttribute('aria-labelledby', 'hh-hero-h');
    var words = el('div', 'hh-hero-words');
    var h = el('h3', 'hh-h1', (content().hero && content().hero.title) || 'Your path to everything Rouh can do');
    h.id = 'hh-hero-h';
    words.appendChild(h);
    var line;
    if (!c.done) {
      line = (content().hero && content().hero.fresh) || 'Start with the first step. Each one takes a minute or two.';
    } else if (nx) {
      line = c.done + ' of ' + c.all + ' steps done. You are on ' + stageName(nx.stage) + '.';
    } else {
      line = doneLine(c) + ' The lessons go deeper whenever you want.';
    }
    words.appendChild(el('p', 'hh-lede', line));
    // Beside the list of next steps the hero only says where you are: the step itself is right
    // below it, and the section's pages are in the navigation.
    var withList = (pageDef().views || []).indexOf('next') >= 0;
    var acts = el('div', 'hh-acts');
    if (withList) {
      // Here the answer is the heading: where you are, then how far; the slogan steps aside.
      h.textContent = !nx ? 'You have done every step' : !c.done ? 'Start with ' + stageName(nx.stage)
        : 'You are on ' + stageName(nx.stage);
      words.querySelector('.hh-lede').textContent = !c.done
        ? ((content().hero && content().hero.fresh) || '')
        : doneLine(c);
      acts.appendChild(k(button('Ask anything', 'hh-quiet', function () { say(askWords()); }), 'ask-top'));
      words.appendChild(acts);
      sec.classList.add('hh-hero-slim');
      sec.appendChild(ring(c.pct));
      sec.appendChild(words);
      return sec;
    }
    if (nx) {
      var go = k(button('', 'hh-main', goNext), 'next');
      go.appendChild(el('span', 'hh-main-k', 'Next step'));
      go.appendChild(el('span', 'hh-main-t', nx.step.title));
      acts.appendChild(go);
    } else {
      acts.appendChild(k(button('Browse the lessons', 'hh-main', function () { goLesson(''); }), 'next'));
    }
    acts.appendChild(k(button('Ask anything', 'hh-quiet', function () { say(askWords()); }), 'ask-top'));
    words.appendChild(acts);
    var others = pages().filter(function (p) { return p.id !== pageDef().id; });
    if (others.length) {
      var jumps = el('nav', 'hh-jumps');
      jumps.setAttribute('aria-label', 'Handholding');
      others.forEach(function (p) { jumps.appendChild(k(link('/handholding/' + p.id, p.name, 'hh-jump'), 'jump-' + p.id)); });
      words.appendChild(jumps);
    }
    sec.appendChild(ring(c.pct));
    sec.appendChild(words);
    return sec;
  }
  /** How far along, in words: done, and how many of those were left out as not for you. */
  function doneLine(c) {
    var left = allSteps().filter(function (x) { return skipped(x.step.id) && !detected(x.step.id); }).length;
    return c.done + ' of ' + c.all + ' steps done' + (left ? ', ' + left + ' of them left out as not for you' : '') + '.';
  }
  function stageName(stage) { return 'Stage ' + stage.n + ', ' + stage.title; }
  function askWords() { return (content().ask && content().ask.prefix) || 'Help me with Handholding: '; }

  /* What Rouh is: the one assistant in the middle, and what it works with round it. The nodes are
     real buttons laid over the lines; on a narrow page they are a grid of the same buttons. */
  function concepts(def) {
    var list = content().concepts || [];
    var sec = el('section', 'hh-sec hh-concepts');
    sec.id = 'hh-concepts';
    sec.setAttribute('aria-labelledby', 'hh-concepts-h');
    heading(sec, 'hh-concepts-h', def, 'What Rouh is');
    if (!H.concept && list.length) { H.concept = list[0].id; }
    var map = el('div', 'hh-map');
    var lines = svg('svg', { class: 'hh-map-lines', viewBox: '0 0 100 100', preserveAspectRatio: 'none',
                             'aria-hidden': 'true' });
    map.appendChild(lines);
    var ringOf = list.slice(1);
    var grid = el('div', 'hh-map-nodes');
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', 'The parts of Rouh');
    list.forEach(function (c, i) {
      var b = k(button('', 'hh-node' + (i === 0 ? ' hh-node-hub' : '') + (H.concept === c.id ? ' on' : ''),
                       function () { H.concept = c.id; H.said = c.name; draw(); conceptInView(); }), 'concept-' + c.id);
      b.setAttribute('aria-pressed', H.concept === c.id ? 'true' : 'false');
      b.setAttribute('aria-controls', 'hh-concept-card');
      b.appendChild(glyph(c.icon, i === 0 ? 26 : 20));
      var t = el('span', 'hh-node-t');
      t.appendChild(el('span', 'hh-node-name', c.name));
      t.appendChild(el('span', 'hh-node-short', c.short));
      b.appendChild(t);
      if (i > 0) {
        // Round the hub, clockwise from the top, as a share of the box (the CSS places it).
        var a = (-90 + (i - 1) * 360 / ringOf.length) * Math.PI / 180;
        var x = 50 + 36 * Math.cos(a), y = 50 + 37 * Math.sin(a);
        b.style.setProperty('--x', x.toFixed(2) + '%');
        b.style.setProperty('--y', y.toFixed(2) + '%');
        lines.appendChild(svg('line', { x1: '50', y1: '50', x2: x.toFixed(2), y2: y.toFixed(2),
                                        class: 'hh-map-line' + (H.concept === c.id ? ' on' : ''),
                                        'vector-effect': 'non-scaling-stroke' }));
      }
      grid.appendChild(b);
    });
    map.appendChild(grid);
    sec.appendChild(map);
    var pick = list.filter(function (c) { return c.id === H.concept; })[0];
    if (pick) {
      var card = el('div', 'hh-ccard');
      card.id = 'hh-concept-card';
      card.setAttribute('aria-live', 'polite');
      var head = el('div', 'hh-ccard-head');
      head.appendChild(glyph(pick.icon, 22));
      head.appendChild(el('h4', 'hh-h3', pick.name));
      card.appendChild(head);
      (pick.body || []).forEach(function (p) { card.appendChild(el('p', 'hh-ccard-p', p)); });
      if (pick.see) {
        var row = el('div', 'hh-ccard-foot');
        row.appendChild(showLink(pick.see, 'See it: ' + pick.see.label, 'hh-see', 'see-' + pick.id));
        card.appendChild(row);
      }
      sec.appendChild(card);
    }
    return sec;
  }

  /** The words of the part just pressed, brought into view when they are below the fold. */
  function conceptInView() {
    var card = $('hh-concept-card');
    var body = $('handholdingBody');
    if (!card || !body) { return; }
    var r = card.getBoundingClientRect(), b = body.getBoundingClientRect();
    if (r.bottom > b.bottom) { card.scrollIntoView({ block: 'nearest', behavior: reduced() ? 'auto' : 'smooth' }); }
  }

  /* Your path: the stages, a line joining their markers, each one a checklist. */
  function path(def) {
    var sec = el('section', 'hh-sec hh-path');
    sec.id = 'hh-path';
    sec.setAttribute('aria-labelledby', 'hh-path-h');
    heading(sec, 'hh-path-h', def, 'Your journey');
    var ol = el('ol', 'hh-stages');
    var nx = nextStep();
    (content().stages || []).forEach(function (stage) {
      var sc = stageCounts(stage);
      var open = !!H.stages[stage.id];
      var li = el('li', 'hh-stage' + (open ? ' open' : '') + (sc.done === sc.all && sc.all ? ' all' : '') +
                        (nx && nx.stage.id === stage.id ? ' here' : ''));
      var mark = el('span', 'hh-mark');
      mark.setAttribute('aria-hidden', 'true');
      if (sc.done === sc.all && sc.all) {
        mark.appendChild(glyph('<path d="M6 12.5l4 4 8-9"/>', 16));
      } else {
        mark.textContent = String(stage.n);
      }
      li.id = 'hh-stage-' + stage.id;
      li.appendChild(mark);
      var box = el('div', 'hh-stage-box');
      var hd = el('h4', 'hh-stage-h');
      var t = k(button('', 'hh-stage-t', function () { H.stages[stage.id] = !open; draw(); }), 'stage-' + stage.id);
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
      t.setAttribute('aria-controls', 'hh-stage-body-' + stage.id);
      var tw = el('span', 'hh-stage-words');
      tw.appendChild(el('span', 'hh-stage-n', 'Stage ' + stage.n));
      tw.appendChild(el('span', 'hh-stage-name', stage.title));
      tw.appendChild(el('span', 'hh-stage-why', stage.why));
      var conn = connSummary(stage);
      if (conn) { tw.appendChild(conn); }
      t.appendChild(tw);
      var meter = el('span', 'hh-stage-meter');
      meter.appendChild(el('span', 'hh-stage-count', sc.done + ' of ' + sc.all));
      var bar = el('span', 'hh-bar');
      var fill = el('span', 'hh-bar-fill');
      fill.style.width = (sc.all ? Math.round(sc.done * 100 / sc.all) : 0) + '%';
      bar.appendChild(fill);
      meter.appendChild(bar);
      t.appendChild(meter);
      t.appendChild(glyph('<path d="M7 10l5 5 5-5"/>', 18));
      hd.appendChild(t);
      box.appendChild(hd);
      var steps = el('ul', 'hh-steps');
      steps.id = 'hh-stage-body-' + stage.id;
      steps.hidden = !open;
      if (open) { (stage.steps || []).forEach(function (st) { steps.appendChild(stepRow(stage, st)); }); }
      box.appendChild(steps);
      li.appendChild(box);
      ol.appendChild(li);
    });
    sec.appendChild(ol);
    return sec;
  }

  /** On a stage of connections, what Rouh knows of them, so it shows with the stage closed. */
  function connSummary(stage) {
    var n = { live: 0, attention: 0 };
    var any = false;
    (stage.steps || []).forEach(function (st) {
      if (!st.connection || !st.connection.key) { return; }
      any = true;
      var s = status(st.connection.key);
      if (s && n[s.kind] !== undefined) { n[s.kind] += 1; }
    });
    if (!any) { return null; }
    var w = el('span', 'hh-stage-conn');
    w.appendChild(badge({ kind: 'count', words: n.live + ' connected' }));
    if (n.attention) { w.appendChild(badge({ kind: 'attention', words: n.attention + ' ' + plural(n.attention, 'needs', 'need') + ' attention' })); }
    return w;
  }

  function badge(s) {
    var b = el('span', 'hh-badge hh-badge-' + s.kind);
    var shape = { live: '<path d="M6 12.5l4 4 8-9"/>', attention: '<path d="M12 7v6M12 16.5v.5"/>',
                  off: '<circle cx="12" cy="12" r="5"/>', unknown: '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5M12 16.5v.5"/>' };
    if (s.kind !== 'count') { b.appendChild(glyph(shape[s.kind] || shape.unknown, 14)); }
    b.appendChild(el('span', '', s.words));
    return b;
  }

  function stepRow(stage, st, withStage) {
    var open = !!H.steps[st.id];
    var done = isDone(st.id), det = detected(st.id);
    var li = el('li', 'hh-step' + (done ? ' done' : '') + (open ? ' open' : ''));
    li.id = 'hh-step-' + st.id;
    var top = el('div', 'hh-step-top');
    if (!det && skipped(st.id)) {
      var sk = el('span', 'hh-det hh-det-skip');
      sk.setAttribute('role', 'img');
      sk.setAttribute('aria-label', 'Not for me');
      sk.appendChild(glyph('<path d="M7 12h10"/>', 18));
      top.appendChild(sk);
    } else if (!det && liveOnly(st.id)) {
      // No box: this one is done when Rouh sees it connected, and says so with its badge.
      var wait = el('span', 'hh-det hh-det-wait');
      wait.setAttribute('role', 'img');
      wait.setAttribute('aria-label', 'Done when Rouh sees it connected');
      wait.title = 'Done when Rouh sees it connected';
      wait.appendChild(glyph('<circle cx="12" cy="12" r="7"/>', 18));
      top.appendChild(wait);
    } else if (det) {
      var d = el('span', 'hh-det');
      d.title = H.data.detected[st.id];
      d.appendChild(glyph('<path d="M6 12.5l4 4 8-9"/>', 18));
      d.setAttribute('role', 'img');
      d.setAttribute('aria-label', 'Done, detected: ' + H.data.detected[st.id]);
      top.appendChild(d);
    } else {
      var lab = el('label', 'hh-tick');
      var cb = k(el('input'), 'done-' + st.id);
      cb.type = 'checkbox';
      cb.checked = ticked(st.id);
      cb.setAttribute('aria-label', 'Done: ' + st.title);
      cb.addEventListener('change', function () { save(st.id, cb.checked); });
      lab.appendChild(cb);
      var face = el('span', 'hh-tick-face');
      face.setAttribute('aria-hidden', 'true');
      face.appendChild(glyph('<path d="M6 12.5l4 4 8-9"/>', 16));
      lab.appendChild(face);
      top.appendChild(lab);
    }
    var t = k(button('', 'hh-steptitle', function () { H.steps[st.id] = !open; draw(); }), 'step-' + st.id);
    t.setAttribute('aria-expanded', open ? 'true' : 'false');
    t.setAttribute('aria-controls', 'hh-step-body-' + st.id);
    var tw = el('span', 'hh-step-words');
    tw.appendChild(el('span', 'hh-step-name', st.title));
    tw.appendChild(el('span', 'hh-step-out', st.outcome));
    if (withStage) { tw.appendChild(el('span', 'hh-step-stage', stageName(stage))); }
    t.appendChild(tw);
    var side = el('span', 'hh-step-side');
    var meta = el('span', 'hh-step-meta');
    if (det) { meta.appendChild(el('span', 'hh-det-word', 'Detected')); }
    if (st.optional && !done) { meta.appendChild(el('span', 'hh-tag-opt', 'Optional')); }
    if (skipped(st.id) && !det) { meta.appendChild(el('span', 'hh-tag-opt', 'Not for me')); }
    var s = st.connection ? status(st.connection.key) : null;
    if (s) { meta.appendChild(badge(s)); }
    if (meta.childNodes.length) { side.appendChild(meta); }
    side.appendChild(glyph('<path d="M7 10l5 5 5-5"/>', 18));
    t.appendChild(side);
    top.appendChild(t);
    if (st.connection && st.show && !open) {
      top.appendChild(showLink(st.show, (s && s.kind === 'live') || done ? 'Open' : 'Set up', 'hh-show hh-rowshow', 'rowshow-' + st.id));
      top.lastChild.setAttribute('aria-label', 'Show me: ' + st.show.label);
      top.classList.add('hh-step-top-conn');
    }
    li.appendChild(top);
    if (H.failed[st.id]) { li.appendChild(el('p', 'hh-failed', H.failed[st.id])); }
    var body = el('div', 'hh-step-body');
    body.id = 'hh-step-body-' + st.id;
    body.hidden = !open;
    if (open) { fillStep(body, st, s); }
    li.appendChild(body);
    return li;
  }

  function fillStep(body, st, s) {
    var c = st.connection;
    if (c) {
      if (s && s.said) { body.appendChild(el('p', 'hh-said hh-said-' + s.kind, s.said)); }
      var facts = el('dl', 'hh-facts');
      if (c.why) { fact(facts, 'What it unlocks', c.why); }
      if (c.needs) { fact(facts, 'What you need', c.needs); }
      body.appendChild(facts);
      if (c.clicks && c.clicks.length) {
        body.appendChild(el('p', 'hh-k', 'The clicks'));
        var ol = el('ol', 'hh-clicks');
        c.clicks.forEach(function (x) { ol.appendChild(el('li', '', x)); });
        body.appendChild(ol);
      }
    }
    (st.more || []).forEach(function (p) { body.appendChild(el('p', 'hh-more', p)); });
    if (st.say) { body.appendChild(sayBox(st.say, 'say-' + st.id, c ? 'Check it works, say' : 'Say')); }
    var foot = el('div', 'hh-step-foot');
    if (st.show) { foot.appendChild(showLink(st.show, 'Show me: ' + st.show.label, 'hh-show', 'show-' + st.id)); }
    if (st.lesson) {
      var les = lessonById(st.lesson);
      if (les) {
        foot.appendChild(k(button('Lesson: ' + les.title, 'hh-quiet hh-small', function () { goLesson(les.id); }),
                           'les-' + st.id));
      }
    }
    if (st.optional && !detected(st.id)) {
      foot.appendChild(skipped(st.id)
        ? k(button('I want this after all', 'hh-quiet hh-small', function () { save(st.id, false); }), 'unskip-' + st.id)
        : k(button('Not for me', 'hh-quiet hh-small', function () { save(st.id, true, true); }), 'skip-' + st.id));
    }
    if (foot.childNodes.length) { body.appendChild(foot); }
  }
  function fact(dl, key, val) {
    var w = el('div', 'hh-fact');
    w.appendChild(el('dt', '', key));
    w.appendChild(el('dd', '', val));
    dl.appendChild(w);
  }
  /** A phrase to say, and the one button that puts it in the message box. */
  function sayBox(words, key, label) {
    var w = el('div', 'hh-say');
    var q = el('p', 'hh-say-q');
    q.appendChild(el('span', 'hh-say-k', label || 'Try saying'));
    q.appendChild(el('span', 'hh-say-w', '“' + words + '”'));
    w.appendChild(q);
    var b = k(button('', 'hh-saybtn', function () { say(words); }), key);
    b.setAttribute('aria-label', 'Try saying: ' + words);
    b.appendChild(glyph('<path d="M4 12h12M12 6l6 6-6 6"/>', 16));
    b.appendChild(el('span', '', 'Try saying'));
    w.appendChild(b);
    return w;
  }

  /* ---- lessons ---- */

  function lessonById(id) {
    return (content().lessons || []).filter(function (l) { return l.id === id; })[0] || null;
  }
  function areaName(id) {
    var a = (content().areas || []).filter(function (x) { return x.id === id; })[0];
    return a ? a.name : id;
  }
  function levelName(id) {
    var a = (content().levels || []).filter(function (x) { return x.id === id; })[0];
    return a ? a.name : id;
  }
  function matches(l) {
    if (H.area && l.area !== H.area) { return false; }
    if (H.level && l.level !== H.level) { return false; }
    var q = H.q.trim().toLowerCase();
    if (!q) { return true; }
    var hay = [l.title, l.summary, areaName(l.area)].concat(l.steps || [], l.say || []).join(' ').toLowerCase();
    return q.split(/\s+/).every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function lessons(def) {
    var all = content().lessons || [];
    var sec = el('section', 'hh-sec hh-lessons');
    sec.id = 'hh-lessons';
    sec.setAttribute('aria-labelledby', 'hh-lessons-h');
    heading(sec, 'hh-lessons-h', def, 'Lessons');
    var tools = el('div', 'hh-ltools');
    var sl = el('label', 'hh-search');
    sl.appendChild(glyph('<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>', 18));
    var inp = k(el('input'), 'q');
    inp.type = 'search';
    inp.placeholder = 'Search the lessons';
    inp.setAttribute('aria-label', 'Search the lessons');
    inp.value = H.q;
    inp.addEventListener('input', function () { H.q = inp.value; drawLessonList(); });
    sl.appendChild(inp);
    tools.appendChild(sl);
    var lv = el('div', 'hh-levels');
    lv.setAttribute('role', 'group');
    lv.setAttribute('aria-label', 'Level');
    [{ id: '', name: 'Every level' }].concat(content().levels || []).forEach(function (x) {
      var b = k(button(x.name, 'hh-seg' + (H.level === x.id ? ' on' : ''), function () { H.level = x.id; draw(); }),
                'lv-' + (x.id || 'all'));
      b.setAttribute('aria-pressed', H.level === x.id ? 'true' : 'false');
      lv.appendChild(b);
    });
    tools.appendChild(lv);
    sec.appendChild(tools);
    var chips = el('div', 'hh-chips');
    chips.setAttribute('role', 'group');
    chips.setAttribute('aria-label', 'Area');
    [{ id: '', name: 'All areas' }].concat(content().areas || []).forEach(function (x) {
      var n = x.id ? all.filter(function (l) { return l.area === x.id; }).length : all.length;
      if (x.id && !n) { return; }
      var b = k(button(x.name, 'hh-chip' + (H.area === x.id ? ' on' : ''), function () { H.area = x.id; draw(); }),
                'ar-' + (x.id || 'all'));
      b.setAttribute('aria-pressed', H.area === x.id ? 'true' : 'false');
      chips.appendChild(b);
    });
    sec.appendChild(chips);
    var holder = el('div', 'hh-lholder');
    holder.id = 'hh-lholder';
    sec.appendChild(holder);
    fillLessonList(holder);
    return sec;
  }
  function drawLessonList() {
    var holder = $('hh-lholder');
    if (!holder) { draw(); return; }
    holder.textContent = '';
    fillLessonList(holder);
  }
  function fillLessonList(holder) {
    var all = content().lessons || [];
    var got = all.filter(matches);
    var cnt = el('p', 'hh-lcount', got.length + ' ' + plural(got.length, 'lesson', 'lessons') +
                 (got.length !== all.length ? ' of ' + all.length : ''));
    cnt.setAttribute('aria-live', 'polite');
    holder.appendChild(cnt);
    if (!got.length) {
      var e = el('div', 'hh-empty');
      e.appendChild(el('p', 'hh-empty-big', 'No lesson matches that'));
      e.appendChild(el('p', 'hh-empty-small', 'Try another word, or ask Rouh: it can show you how to do almost anything here.'));
      var row = el('div', 'hh-acts');
      row.appendChild(k(button('Clear the search', 'hh-quiet', function () { H.q = ''; H.area = ''; H.level = ''; draw(); }), 'clear'));
      row.appendChild(k(button('Ask Rouh', 'hh-quiet', function () { say(askWords() + H.q); }), 'ask-les'));
      e.appendChild(row);
      holder.appendChild(e);
      return;
    }
    var ul = el('ul', 'hh-lrows');
    got.forEach(function (l) {
      var li = el('li');
      var a = k(link(lessonHref(l.id), '', 'hh-lrow'), 'l-' + l.id);
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) { return; }
        e.preventDefault();
        e.stopImmediatePropagation();
        goLesson(l.id);
      }, true);
      var w = el('span', 'hh-lrow-words');
      w.appendChild(el('span', 'hh-lrow-t', l.title));
      w.appendChild(el('span', 'hh-lrow-s', l.summary));
      a.appendChild(w);
      var m = el('span', 'hh-lrow-meta');
      m.appendChild(el('span', 'hh-tag', areaName(l.area)));
      m.appendChild(el('span', 'hh-tag hh-tag-lv', levelName(l.level)));
      m.appendChild(el('span', 'hh-min', l.minutes + ' min'));
      a.appendChild(m);
      li.appendChild(a);
      ul.appendChild(li);
    });
    holder.appendChild(ul);
  }

  function lessonPage(id) {
    var l = lessonById(id);
    var wrap = el('article', 'hh-lesson');
    wrap.appendChild(k(button('', 'hh-back', function () { goLesson(''); }), 'back'));
    wrap.firstChild.appendChild(glyph('<path d="M15 6l-6 6 6 6"/>', 18));
    wrap.firstChild.appendChild(el('span', '', 'All lessons'));
    if (!l) {
      var e = el('div', 'hh-empty');
      e.appendChild(el('p', 'hh-empty-big', 'There is no such lesson'));
      e.appendChild(el('p', 'hh-empty-small', 'It may have been renamed. Every lesson is on the list.'));
      wrap.appendChild(e);
      return wrap;
    }
    var h = el('h3', 'hh-h1', l.title);
    h.setAttribute('tabindex', '-1');
    wrap.appendChild(h);
    var m = el('p', 'hh-lmeta');
    m.appendChild(el('span', 'hh-tag', areaName(l.area)));
    m.appendChild(el('span', 'hh-tag hh-tag-lv', levelName(l.level)));
    m.appendChild(el('span', 'hh-min', 'About ' + l.minutes + ' minutes'));
    wrap.appendChild(m);
    wrap.appendChild(el('p', 'hh-lede', l.summary));
    var ol = el('ol', 'hh-lsteps');
    (l.steps || []).forEach(function (s) { ol.appendChild(el('li', '', s)); });
    wrap.appendChild(ol);
    if (l.say && l.say.length) {
      wrap.appendChild(el('h4', 'hh-h3', 'Things to say'));
      var says = el('div', 'hh-says');
      l.say.forEach(function (s, i) { says.appendChild(sayBox(s, 'lsay-' + i, 'Say')); });
      wrap.appendChild(says);
    }
    var foot = el('div', 'hh-step-foot');
    if (l.show) { foot.appendChild(showLink(l.show, 'Show me: ' + l.show.label, 'hh-show', 'lshow')); }
    foot.appendChild(k(button('Ask about this lesson', 'hh-quiet', function () { say(askWords() + l.title + '. '); }), 'lask'));
    wrap.appendChild(foot);
    return wrap;
  }

  /** A page's own heading and line, from the data file, over the view it opens with. */
  function heading(sec, id, def, fallback) {
    var h = el('h3', 'hh-h2', (def && def.title) || fallback);
    h.id = id;
    h.setAttribute('tabindex', '-1');
    sec.appendChild(h);
    if (def && def.lede) { sec.appendChild(el('p', 'hh-sub', def.lede)); }
  }

  /** The steps not done yet, in the order the path has them: every step that is not optional
      first, then the optional ones. */
  function upcoming(n) {
    var all = allSteps().filter(function (x) { return !isDone(x.step.id); });
    var must = all.filter(function (x) { return !x.step.optional; });
    var may = all.filter(function (x) { return x.step.optional; });
    return must.concat(may).slice(0, n);
  }

  /* Next steps: worked out from what is done, the very next step open at the top and the few
     after it below, each with its stage beside it. */
  function nextView(def) {
    var sec = el('section', 'hh-sec hh-next');
    sec.id = 'hh-next';
    sec.setAttribute('aria-labelledby', 'hh-next-h');
    heading(sec, 'hh-next-h', def, 'Your next steps');
    var c = counts();
    if ((pageDef().views || []).indexOf('hero') < 0) { sec.appendChild(progressLine(c)); }
    var list = upcoming(Math.max(1, Number(def.count) || 5));
    if (!list.length) {
      var e = el('div', 'hh-empty');
      e.appendChild(el('p', 'hh-empty-big', 'You have done every step'));
      e.appendChild(el('p', 'hh-empty-small', doneLine(c) + ' The lessons go deeper whenever you want.'));
      var row = el('div', 'hh-acts');
      row.appendChild(k(button('Browse the lessons', 'hh-main', function () { goLesson(''); }), 'next-les'));
      e.appendChild(row);
      sec.appendChild(e);
      return sec;
    }
    var first = list[0];
    if (H.steps[first.step.id] === undefined) { H.steps[first.step.id] = true; }
    var top = el('div', 'hh-nextfirst');
    top.appendChild(el('p', 'hh-k', 'Your next step, from ' + stageName(first.stage)));
    var ul = el('ul', 'hh-steps hh-steps-loose');
    ul.appendChild(stepRow(first.stage, first.step));
    top.appendChild(ul);
    sec.appendChild(top);
    if (list.length > 1) {
      var then = el('div', 'hh-nextthen');
      then.appendChild(el('p', 'hh-k', 'After that'));
      var ul2 = el('ul', 'hh-steps hh-steps-loose');
      list.slice(1).forEach(function (x) { ul2.appendChild(stepRow(x.stage, x.step, true)); });
      then.appendChild(ul2);
      sec.appendChild(then);
    }
    return sec;
  }
  function progressLine(c) {
    var w = el('div', 'hh-progline');
    var bar = el('span', 'hh-bar hh-bar-wide');
    var fill = el('span', 'hh-bar-fill');
    fill.style.width = c.pct + '%';
    bar.appendChild(fill);
    w.appendChild(el('span', 'hh-progwords', c.done + ' of ' + c.all + ' steps done, ' + c.pct + '%'));
    w.appendChild(bar);
    return w;
  }

  /* Connections: every step that is a connection, wherever its stage is, with its live state. */
  function connectionsView(def) {
    var sec = el('section', 'hh-sec hh-conns');
    sec.id = 'hh-conns';
    sec.setAttribute('aria-labelledby', 'hh-conns-h');
    heading(sec, 'hh-conns-h', def, 'Connections');
    var rows = allSteps().filter(function (x) { return x.step.connection; });
    var n = { live: 0, attention: 0 };
    rows.forEach(function (x) {
      var s = x.step.connection.key ? status(x.step.connection.key) : null;
      if (s && n[s.kind] !== undefined) { n[s.kind] += 1; }
    });
    var keyed = rows.filter(function (x) { return x.step.connection.key; }).length;
    var sum = el('div', 'hh-stage-conn');
    sum.appendChild(badge({ kind: 'count', words: n.live + ' of ' + keyed + ' connected' }));
    if (n.attention) { sum.appendChild(badge({ kind: 'attention', words: n.attention + ' ' + plural(n.attention, 'needs', 'need') + ' attention' })); }
    sec.appendChild(sum);
    var ul = el('ul', 'hh-steps hh-steps-loose');
    rows.forEach(function (x) { ul.appendChild(stepRow(x.stage, x.step)); });
    sec.appendChild(ul);
    return sec;
  }

  /** Start here's map of the path: each stage, how far along, and a way into it on the Journey. */
  function stageList(def) {
    var j = pageWith('journey');
    var sec = el('section', 'hh-sec');
    sec.setAttribute('aria-labelledby', 'hh-stagelist-h');
    heading(sec, 'hh-stagelist-h', def, 'Your path at a glance');
    var ol = el('ol', 'hh-stagelist');
    var nx = nextStep();
    (content().stages || []).forEach(function (stage) {
      var sc = stageCounts(stage);
      var li = el('li');
      var a = k(link(j ? '/handholding/' + j.id : '#', '', 'hh-stagelink' + (nx && nx.stage.id === stage.id ? ' here' : '')),
                'sl-' + stage.id);
      a.addEventListener('click', function () { H.stages[stage.id] = true; H.scrollTo = 'hh-stage-' + stage.id; }, true);
      a.appendChild(el('span', 'hh-sl-n', String(stage.n)));
      var w = el('span', 'hh-sl-words');
      w.appendChild(el('span', 'hh-sl-t', stage.title));
      w.appendChild(el('span', 'hh-sl-why', stage.why));
      a.appendChild(w);
      a.appendChild(el('span', 'hh-sl-c', sc.done + ' of ' + sc.all));
      li.appendChild(a);
      ol.appendChild(li);
    });
    sec.appendChild(ol);
    return sec;
  }

  /** A page holding several parts says so first, with a way to each. */
  function jumpsView() {
    var names = { concepts: 'What Rouh is', journey: 'Your journey', lessons: 'Lessons', connections: 'Connections',
                  features: 'Features', tips: 'Pro tips' };
    var ids = { concepts: 'hh-concepts', journey: 'hh-path', lessons: 'hh-lessons', connections: 'hh-conns',
                features: 'hh-feats', tips: 'hh-tips' };
    var nav = el('nav', 'hh-jumps hh-jumps-top');
    nav.setAttribute('aria-label', 'On this page');
    (pageDef().views || []).forEach(function (v) {
      if (!ids[v]) { return; }
      nav.appendChild(k(button(names[v], 'hh-jump', function () {
        var n = $(ids[v]);
        if (n) {
          n.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' });
          var h = n.querySelector('h3');
          if (h) { h.focus({ preventScroll: true }); }
        }
      }), 'top-' + v));
    });
    return nav;
  }

  /* ---- the features that switch on and off ----

     Each switch is read and flipped through the very address its own Settings page uses, so it
     is the same setting, flipped in either place. One that cannot be read here has no switch:
     it says so, and links to its page. Never a switch that is not wired. */

  function getJSON(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok || !j) { throw new Error((j && j.error) || ''); }
        return j;
      });
    });
  }
  function postJSON(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
                        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) {
        return r.json().catch(function () { return null; }).then(function (j) {
          if (!r.ok || !j) { throw new Error((j && j.error) || ''); }
          return j;
        });
      });
  }
  var SWITCHES = {
    // Anatomy, Meta, What Rouh keeps and runs, and the Heartbeat's own settings (`rouh/lean.py`).
    heartbeat: {
      read: function () {
        return getJSON('/api/anatomy/keeps').then(function (j) {
          var it = (j.items || []).filter(function (x) { return x.id === 'heartbeat'; })[0];
          if (!it) { throw new Error(''); }
          return { on: it.mode === 'on' };
        });
      },
      write: function (on) { return postJSON('/api/anatomy/keeps', { item: 'heartbeat', mode: on ? 'on' : 'off', where: 'heartbeat' }); }
    },
    // Anatomy, Behaviour, Morning brief settings (`rouh/morning_brief.py`).
    brief: {
      read: function () { return getJSON('/api/settings/brief').then(function (j) { return { on: !!j.on }; }); },
      write: function (on) { return postJSON('/api/settings/brief', { on: !!on }); }
    },
    // Connections, Email and calendar, New mail (`rouh/mail_alerts.py`).
    mail_alerts: {
      read: function () {
        return getJSON('/api/settings/mail-alerts').then(function (j) {
          var a = j.alerts || {};
          return { on: !!a.on, why: a.on ? '' : (a.why_not || '') };
        });
      },
      write: function (on) { return postJSON('/api/settings/mail-alerts/' + (on ? 'on' : 'off'), {}); }
    }
  };
  function readFeatures() {
    H.featRead = true;
    (content().features || []).forEach(function (f) {
      var sw = SWITCHES[f.switch];
      if (!sw) { H.feat[f.id] = { failed: true }; return; }
      H.feat[f.id] = { loading: true };
      sw.read().then(function (got) { H.feat[f.id] = got; draw(); })
        .catch(function () { H.feat[f.id] = { failed: true }; draw(); });
    });
  }
  function flip(f, on) {
    var sw = SWITCHES[f.switch];
    var st = H.feat[f.id] || {};
    st.busy = true;
    st.said = '';
    H.feat[f.id] = st;
    draw();
    sw.write(on).then(function (j) {
      return sw.read().then(function (got) {
        got.said = (j && j.said) || (f.name + ' is ' + (got.on ? 'on' : 'off') + '.');
        H.feat[f.id] = got;
        H.said = got.said;
        draw();
      });
    }).catch(function (e) {
      st.busy = false;
      st.said = (e && e.message) || 'That could not be changed here. Open its Settings page and try there.';
      st.bad = true;
      H.said = st.said;
      draw();
    });
  }
  function featuresView(def) {
    if (!H.featRead) { readFeatures(); }
    var sec = el('section', 'hh-sec hh-feats');
    sec.id = 'hh-feats';
    sec.setAttribute('aria-labelledby', 'hh-feats-h');
    heading(sec, 'hh-feats-h', def, 'Features you can switch on and off');
    var ul = el('ul', 'hh-featlist');
    (content().features || []).forEach(function (f) {
      var st = H.feat[f.id] || { loading: true };
      var li = el('li', 'hh-feat');
      var top = el('div', 'hh-feat-top');
      var words = el('div', 'hh-feat-words');
      var name = el('h4', 'hh-h3', f.name);
      name.id = 'hh-feat-' + f.id;
      words.appendChild(name);
      words.appendChild(el('p', 'hh-feat-what', f.what));
      top.appendChild(words);
      var ctl = el('div', 'hh-feat-ctl');
      if (st.loading) {
        ctl.appendChild(el('span', 'hh-feat-state', 'Reading'));
      } else if (st.failed) {
        ctl.appendChild(badge({ kind: 'unknown', words: 'Status unknown' }));
      } else {
        var b = k(button('', 'hh-switch' + (st.on ? ' on' : ''), function () { flip(f, !st.on); }), 'sw-' + f.id);
        b.setAttribute('role', 'switch');
        b.setAttribute('aria-checked', st.on ? 'true' : 'false');
        b.setAttribute('aria-labelledby', 'hh-feat-' + f.id);
        b.disabled = !!st.busy || (!st.on && !!st.why);
        b.appendChild(el('span', 'hh-switch-knob'));
        ctl.appendChild(b);
        ctl.appendChild(el('span', 'hh-feat-state', st.busy ? 'Changing' : st.on ? 'On' : 'Off'));
      }
      top.appendChild(ctl);
      li.appendChild(top);
      if (st.failed) {
        li.appendChild(el('p', 'hh-feat-note', 'Rouh could not read this setting here, so there is no switch for it. Its own page has it.'));
      } else if (!st.loading && !st.on && st.why) {
        li.appendChild(el('p', 'hh-feat-note', st.why));
      } else if (!st.loading && !st.on && f.off) {
        li.appendChild(el('p', 'hh-feat-note', f.off));
      }
      if (st.said) { li.appendChild(el('p', 'hh-feat-note' + (st.bad ? ' hh-feat-bad' : ''), st.said)); }
      if (f.say) { li.appendChild(sayBox(f.say, 'fsay-' + f.id, 'Say')); }
      if (f.show) {
        var foot = el('div', 'hh-step-foot');
        foot.appendChild(showLink(f.show, 'Show me: ' + f.show.label, 'hh-show', 'fshow-' + f.id));
        li.appendChild(foot);
      }
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    return sec;
  }

  /* ---- pro tips ---- */

  function tipsView(def) {
    var all = content().tips || [];
    var sec = el('section', 'hh-sec hh-tips');
    sec.id = 'hh-tips';
    sec.setAttribute('aria-labelledby', 'hh-tips-h');
    heading(sec, 'hh-tips-h', def, 'Pro tips');
    var chips = el('div', 'hh-chips');
    chips.setAttribute('role', 'group');
    chips.setAttribute('aria-label', 'Area');
    [{ id: '', name: 'All areas' }].concat(content().areas || []).forEach(function (x) {
      var n = x.id ? all.filter(function (t) { return t.area === x.id; }).length : all.length;
      if (x.id && !n) { return; }
      var b = k(button(x.name, 'hh-chip' + (H.tipArea === x.id ? ' on' : ''), function () { H.tipArea = x.id; draw(); }),
                'ta-' + (x.id || 'all'));
      b.setAttribute('aria-pressed', H.tipArea === x.id ? 'true' : 'false');
      chips.appendChild(b);
    });
    sec.appendChild(chips);
    var got = all.filter(function (t) { return !H.tipArea || t.area === H.tipArea; });
    var cnt = el('p', 'hh-lcount', got.length + ' ' + plural(got.length, 'tip', 'tips'));
    cnt.setAttribute('aria-live', 'polite');
    sec.appendChild(cnt);
    var ul = el('ul', 'hh-tiplist');
    got.forEach(function (t) {
      var li = el('li', 'hh-tip');
      li.appendChild(el('span', 'hh-tag', areaName(t.area)));
      li.appendChild(el('h4', 'hh-h3', t.title));
      li.appendChild(el('p', 'hh-tip-body', t.body));
      if (t.say) { li.appendChild(sayBox(t.say, 'tsay-' + t.id, 'Say')); }
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    return sec;
  }

  var VIEWS = {
    hero: function () { return hero(); },
    next: nextView,
    stages: stageList,
    jumps: jumpsView,
    concepts: concepts,
    journey: path,
    lessons: lessons,
    connections: connectionsView,
    features: featuresView,
    tips: tipsView
  };

  function ask() {
    var sec = el('section', 'hh-askband');
    sec.setAttribute('aria-labelledby', 'hh-ask-h');
    var w = el('div', 'hh-askwords');
    var h = el('h3', 'hh-h2', (content().ask && content().ask.title) || 'Stuck, or curious?');
    h.id = 'hh-ask-h';
    w.appendChild(h);
    w.appendChild(el('p', 'hh-sub', (content().ask && content().ask.line) ||
      'Ask Rouh anything about itself. It knows every page here and can walk you through it.'));
    sec.appendChild(w);
    sec.appendChild(k(button('Ask anything', 'hh-quiet hh-askbtn', function () { say(askWords()); }), 'ask-end'));
    return sec;
  }

  /* ---- the layer ---- */

  function shown(page, lesson) {
    H.open = true;
    var was = H.page + '/' + H.lesson;
    H.page = page || '';
    H.lesson = lesson || '';
    if (!H.page && H.data) { H.page = pageDef().id; }
    if (H.page && host().place) { host().place(H.page, H.lesson); }
    var aimed = H.scrollTo;
    var body = $('handholdingBody');
    if (body && !aimed && H.page + '/' + H.lesson !== was) { body.scrollTop = 0; }
    draw();
    if (body && !aimed && H.page + '/' + H.lesson !== was) {
      body.scrollTop = 0;
      var h = body.querySelector('h3[tabindex]');
      if (h && was !== '/') { h.focus({ preventScroll: true }); }
    }
    load();
  }
  function hidden() { H.open = false; }

  window.RouhHandholding = { shown: shown, hidden: hidden, reload: load };

  var x = $('handholdingClose');
  if (x) { x.addEventListener('click', function () { if (host().close) { host().close(); } }); }
}());
