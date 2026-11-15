/* Rouh's page, what the models cost, in the orb's place
 * (out of app/orb.js).
 *
 * Nothing here runs when the module is loaded: app/orb.js calls wireOrbUsage()
 * at the place in it where this code used to be, so everything happens in
 * the order it always did.
 */
import { goToAddress } from 'app/cards.js';
import { $, el, linkTo } from 'app/helpers.js';
import { orbExpand, orbTipHide, ORBX } from 'app/orb.js';
import { orbPanelShow } from 'app/orb_panel.js';

/* ---------- what the models cost, in the orb's place -------------------
 *
 * Petar, 29 September 2026 (fr_f861da23d084): "On the full screen of the
 * orb, I would like an icon button next to volume that will give me a
 * screen with [stats] on LLM usage instead of orb. Pull from our log and
 * give me a day by day cost split in models". 3 October (fr_f318d715a378):
 * the calls beside the cost, what one call costs, and what the calls were
 * for. 4 October (fr_2b021ac5bac9): the day by day chart as upright bars.
 *
 * Petar, 12 and 15 November 2026 (task 182): "currently I have great charts
 * but drill down is not possible", and "build the drilldowns so I can try to
 * understand through them what is going on". So every bar, part of a bar
 * and row can be pressed, and goes one level down: the total paid per use,
 * a company, a model, a use, a day, the chat, job or page that started the
 * calls, the calls, and one call with why it cost what it did. The trail at
 * the top says where he is, every step of it can be pressed, and Up one
 * level, or Escape, goes one step back; at the top Escape is the orb again.
 *
 * Every level is one question to the server (`rouh/usage_drill.py`), which
 * adds the log up in the database: /api/usage/level, /api/usage/calls and
 * /api/usage/call. Nothing is priced or added up here.
 */

//: A colour for each of a level's largest rows, from the page's own palette.
// Never the accent, which is the screen's own colour for what can be pressed, and never
// the amber of a rise.
var OU_COLOURS = ['#ab8ff3', '#4cc4b0', '#f07ea2', '#72a6f7', '#7ec86c', '#d9dee6'];
//: Each company keeps its colour on every view; anything else is given one by its own name,
//: so the same model, use or chat is the same colour wherever it appears.
var OU_FIXED = { anthropic: '#ab8ff3', openai: '#4cc4b0', voyage: '#f07ea2', google: '#72a6f7', xai: '#7ec86c' };
function ouColour(key) {
  if (OU_FIXED[key]) return OU_FIXED[key];
  var h = 0;
  for (var i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return OU_COLOURS[h % OU_COLOURS.length];
}
//: The default order down, as the server has it (`usage_drill.ORDER`).
var OU_ORDER = ['provider', 'model', 'purpose', 'day', 'origin'];

/**
 * Where the screen is: the period, the choices made on the way down in the
 * order they were made, what the level is split by, and whether it shows the
 * level, its calls or one call.
 * @type {{seq: number, period: {kind: string, at: string, start: string, end: string},
 *   filters: Array<[string, string]>, by: string, view: string, call: number, order: string,
 *   offset: number, last: any, trail: any, thin: (() => void) | null}}
 */
var OU = { seq: 0, period: { kind: 'month', at: '', start: '', end: '' }, filters: [], by: '',
  view: 'level', call: 0, order: 'cost', offset: 0, last: null, trail: null, thin: null };

function orbUsageOpen() {
  var v = $('orbUsageView');
  return !!v && !v.hidden;
}

function orbUsageShow(on) {
  var view = $('orbUsageView'), btn = $('orbUsage');
  if (!view || !btn) return;
  on = !!on && ORBX.state === 'open';
  if (on === !view.hidden) return;
  view.hidden = !on;
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  btn.title = on ? 'Back to the orb' : 'What the models cost';
  // The orb's settings are about the shape, which is not on the screen:
  // one closes the other, whichever is opened second (`orbPanelShow`).
  if (on) orbPanelShow(false);
  orbTipHide();
  if (on) {
    // It opens where it was left, so a look at the orb and back loses nothing.
    view.scrollTop = 0;
    orbUsageLoad();
    $('orbUsageBack').focus();
  } else if (view.contains(document.activeElement)) {
    btn.focus();
  }
}

/* ---- where the screen is, and going up and down ------------------------ */

function ouHas(dim) {
  return OU.filters.some(function (f) { return f[0] === dim; });
}

// The split a level gets when nobody picked one: the use, for a day (Petar
// asked for a spike straight to that day by use), else the next in order.
function ouNext() {
  var oneDay = ouHas('day') || OU.period.kind === 'day';
  if (oneDay && !ouHas('purpose')) return 'purpose';
  for (var i = 0; i < OU_ORDER.length; i++) {
    // One day is not split by day.
    if (OU_ORDER[i] === 'day' && oneDay) continue;
    if (!ouHas(OU_ORDER[i])) return OU_ORDER[i];
  }
  return '';
}

function ouDown(dim, value, view) {
  OU.filters = OU.filters.filter(function (f) { return f[0] !== dim; }).concat([[dim, value]]);
  OU.by = ouNext();
  OU.view = view || 'level';
  OU.offset = 0;
  orbUsageLoad(true);
}

// One step back up the trail. False at the top, where Escape means the orb.
function orbUsageUp() {
  if (OU.view === 'call') { OU.view = 'calls'; orbUsageLoad(true); return true; }
  if (OU.view === 'calls') { OU.view = 'level'; OU.offset = 0; orbUsageLoad(true); return true; }
  if (!OU.filters.length) return false;
  var last = OU.filters[OU.filters.length - 1];
  OU.filters = OU.filters.slice(0, -1);
  if (last[0] === 'hour') OU.filters = OU.filters.filter(function (f) { return f[0] !== 'hour'; });
  OU.by = last[0] === 'hour' ? '' : last[0];
  orbUsageLoad(true);
  return true;
}

function ouTo(depth) {
  OU.filters = OU.filters.slice(0, depth);
  OU.by = '';
  OU.view = 'level';
  OU.offset = 0;
  orbUsageLoad(true);
}

function ouQuery(extra) {
  var q = new URLSearchParams();
  var p = OU.period;
  q.set('period', p.kind);
  if (p.kind === 'range') {
    if (p.start) q.set('start', p.start);
    if (p.end) q.set('end', p.end);
  } else if (p.at) {
    q.set('at', p.at);
  }
  OU.filters.forEach(function (f) { q.set(f[0], f[1]); });
  Object.keys(extra || {}).forEach(function (k) { if (extra[k] !== '' && extra[k] != null) q.set(k, String(extra[k])); });
  return q.toString();
}

function orbUsageLoad(moved) {
  var mine = ++OU.seq;
  var body = $('orbUsageBody');
  body.setAttribute('aria-busy', 'true');
  var url = OU.view === 'call' ? '/api/usage/call?id=' + OU.call
    : OU.view === 'calls' ? '/api/usage/calls?' + ouQuery({ order: OU.order, offset: OU.offset })
      : '/api/usage/level?' + ouQuery({ by: OU.by });
  if (!OU.last) {
    body.textContent = '';
    body.appendChild(el('p', 'ou-wait', 'Reading the log…'));
  }
  fetch(url, { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        return j;
      });
    })
    .then(function (u) {
      if (mine !== OU.seq) return;
      OU.last = u;
      if (u.trail) OU.trail = u.trail;
      body.removeAttribute('aria-busy');
      if (OU.view === 'call') ouPaintCall(u);
      else if (OU.view === 'calls') ouPaintCalls(u);
      else ouPaintLevel(u);
      if (moved) {
        var view = $('orbUsageView');
        if (view) view.scrollTop = 0;
        var head = body.querySelector('.ou-headline');
        if (head) /** @type {HTMLElement} */ (head).focus({ preventScroll: true });
      }
    })
    .catch(function (err) {
      if (mine !== OU.seq) return;
      body.removeAttribute('aria-busy');
      body.textContent = '';
      var p = el('p', 'ou-note ou-fail', 'The log could not be read: ' + (err && err.message || err));
      body.appendChild(p);
      var again = el('button', 'ou-btn', 'Try again');
      again.type = 'button';
      again.addEventListener('click', function () { orbUsageLoad(); });
      body.appendChild(again);
    });
}

/* ---- the parts every level has: the trail and the period --------------- */

function ouPaintTrail(u) {
  var nav = $('orbUsageTrail');
  nav.textContent = '';
  var up = el('button', 'ou-up', 'Up one level');
  up.type = 'button';
  up.title = 'Up one level (Esc)';
  up.hidden = !OU.filters.length && OU.view === 'level';
  up.addEventListener('click', function () { orbUsageUp(); });
  nav.appendChild(up);
  var list = el('ol', 'ou-crumbs');
  var steps = [{ name: 'Paid per use', what: 'Everything' }].concat(
    (u.trail || []).map(function (t) { return { name: t.name, what: t.what }; }));
  if (OU.view === 'calls' || OU.view === 'call') steps.push({ name: 'Calls', what: '' });
  if (OU.view === 'call') steps.push({ name: 'One call', what: '' });
  steps.forEach(function (s, i) {
    var li = el('li');
    var lastOne = i === steps.length - 1;
    if (lastOne) {
      var here = el('span', 'ou-crumb ou-here', s.name);
      here.setAttribute('aria-current', 'page');
      li.appendChild(here);
    } else {
      var b = el('button', 'ou-crumb', s.name);
      b.type = 'button';
      if (s.what) b.title = s.what;
      var depth = i;
      var filtersShown = (u.trail || []).length;
      b.addEventListener('click', function () {
        if (depth <= filtersShown) ouTo(depth);
        else { OU.view = 'calls'; orbUsageLoad(true); }
      });
      li.appendChild(b);
    }
    list.appendChild(li);
  });
  nav.appendChild(list);
}

function ouIso(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function ouDate(iso) {
  var p = iso.split('-');
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

function ouPaintPeriod(span) {
  var box = $('orbUsagePeriod');
  box.textContent = '';
  if (!span) return;
  var kinds = el('div', 'ou-kinds');
  kinds.setAttribute('role', 'group');
  kinds.setAttribute('aria-label', 'Period');
  var dayChosen = ouHas('day');
  [['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['range', 'Range']].forEach(function (k) {
    var b = el('button', 'ou-kind', k[1]);
    b.type = 'button';
    var on = !dayChosen && OU.period.kind === k[0];
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.addEventListener('click', function () {
      // A day chosen on the way down is the period until another is picked.
      OU.filters = OU.filters.filter(function (f) { return f[0] !== 'day' && f[0] !== 'hour'; });
      // The new period is the one holding the last day shown: Week from a month is its last week.
      OU.period = { kind: k[0], at: span.to, start: span.from, end: span.to };
      OU.offset = 0;
      if (OU.view === 'call') OU.view = 'calls';
      if (k[0] === 'range') { ouPaintPeriod(span); var f = box.querySelector('input'); if (f) /** @type {HTMLElement} */ (f).focus(); return; }
      orbUsageLoad(true);
    });
    kinds.appendChild(b);
  });
  box.appendChild(kinds);

  var step = el('div', 'ou-step');
  var back = el('button', 'ou-arrow', '‹');
  back.type = 'button';
  back.setAttribute('aria-label', 'The period before');
  var fwd = el('button', 'ou-arrow', '›');
  fwd.type = 'button';
  fwd.setAttribute('aria-label', 'The period after');
  fwd.disabled = !!span.is_now;
  var said = el('span', 'ou-when', span.said);
  var move = function (dir) {
    var day = dayChosen ? 'day' : OU.period.kind;
    var at = ouDate(dir < 0 ? span.from : span.to);
    if (day === 'day') at.setDate(at.getDate() + dir);
    else if (day === 'week') at.setDate(at.getDate() + 7 * dir);
    else if (day === 'month') { at = ouDate(span.from); at.setMonth(at.getMonth() + dir); }
    else {
      var n = span.days;
      var a = ouDate(span.from), b = ouDate(span.to);
      a.setDate(a.getDate() + n * dir); b.setDate(b.getDate() + n * dir);
      OU.period.start = ouIso(a); OU.period.end = ouIso(b);
    }
    if (dayChosen) {
      OU.filters = OU.filters.map(function (f) { return /** @type {[string, string]} */ (f[0] === 'day' ? [f[0], ouIso(at)] : f); })
        .filter(function (f) { return f[0] !== 'hour'; });
    } else if (day !== 'range') {
      OU.period.at = ouIso(at);
    }
    if (OU.view === 'call') OU.view = 'calls';
    OU.offset = 0;
    orbUsageLoad(true);
  };
  back.addEventListener('click', function () { move(-1); });
  fwd.addEventListener('click', function () { move(1); });
  step.appendChild(back);
  step.appendChild(said);
  step.appendChild(fwd);
  box.appendChild(step);

  if (OU.period.kind === 'range' && !dayChosen) {
    var form = el('form', 'ou-range');
    var from = /** @type {HTMLInputElement} */ (el('input'));
    from.type = 'date'; from.value = OU.period.start || span.from; from.id = 'ouFrom'; from.max = span.today;
    var to = /** @type {HTMLInputElement} */ (el('input'));
    to.type = 'date'; to.value = OU.period.end || span.to; to.id = 'ouTo'; to.max = span.today;
    var lf = el('label', '', 'From'); lf.htmlFor = 'ouFrom';
    var lt = el('label', '', 'To'); lt.htmlFor = 'ouTo';
    var go = el('button', 'ou-btn', 'Show');
    go.type = 'submit';
    form.appendChild(lf); form.appendChild(from); form.appendChild(lt); form.appendChild(to); form.appendChild(go);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      OU.period = { kind: 'range', at: '', start: from.value, end: to.value };
      OU.offset = 0;
      orbUsageLoad(true);
    });
    box.appendChild(form);
  }
}

/* ---- one level ----------------------------------------------------------- */

function ouCount(n) { return (n || 0).toLocaleString('en-GB'); }
function ouCalls(n) { return ouCount(n) + (n === 1 ? ' call' : ' calls'); }

function ouChange(c, cls) {
  var s = el('span', 'ou-chg ' + (cls || '') + ' ou-d-' + (c && c.dir || 'none'));
  var mark = c && c.dir === 'up' ? '▲ ' : c && c.dir === 'down' ? '▼ ' : '';
  s.textContent = mark + (c ? c.said : '');
  return s;
}

function ouPaintLevel(u) {
  ouPaintTrail(u);
  ouPaintPeriod(u.period);
  var body = $('orbUsageBody');
  body.textContent = '';
  OU.by = u.by || '';
  var colour = {};
  // Each keeps its own colour where it can; a second one that would share it takes the next
  // colour nobody in this view has, so the parts of a bar can always be told apart.
  var taken = {};
  (u.series && u.series.keys || []).forEach(function (k) {
    var c = ouColour(k);
    if (taken[c] && !OU_FIXED[k]) {
      var start = OU_COLOURS.indexOf(c);
      for (var j = 1; j <= OU_COLOURS.length; j++) {
        var next = OU_COLOURS[(start + j) % OU_COLOURS.length];
        if (!taken[next]) { c = next; break; }
      }
    }
    taken[c] = true;
    colour[k] = c;
  });
  var paint = function (k) { return colour[k] || 'var(--dimmer)'; };

  // The headline: what this level cost, against the period before.
  var where = (u.trail || []).filter(function (t) { return t.dim !== 'day' && t.dim !== 'hour'; })
    .map(function (t) { return t.name; });
  var subject = where.length ? where[where.length - 1] : 'Paid per use';
  var h = el('h2', 'ou-headline');
  h.tabIndex = -1;
  var before = u.before || {};
  var then = u.period.days === 1 ? 'the day before'
    : u.period.kind === 'month' && u.period.is_now && !ouHas('day') ? 'the same days of ' + ouMonth(u.period.before_from)
      : u.period.kind === 'month' ? ouMonth(u.period.before_from)
        : u.period.kind === 'week' ? 'the week before' : 'the ' + u.period.days + ' days before';
  var vs = before.none ? '' : !(before.cost > 0) ? ', with nothing in ' + then
    : u.change.dir === 'same' ? ', about the same as ' + then : ', ' + u.change.said + ' on ' + then;
  var hourSaid = ouHas('hour') ? ' between ' + (u.trail.filter(function (t) { return t.dim === 'hour'; })[0] || {}).name : '';
  var span = ouLower(u.period.said);
  h.textContent = subject + ': ' + u.total.said + (u.period.days === 1 ? ' on ' : / to /.test(span) && !/^this week/.test(span) ? ' from ' : ' in ') +
    span + hourSaid + vs + '.';
  body.appendChild(h);
  // The chat, job, page or memory this level is about, one press away.
  var at = (u.trail || []).filter(function (t) { return t.link; }).pop();
  if (at) {
    var go = /** @type {HTMLAnchorElement} */ (linkTo(el('a', 'ou-link ou-open', 'Open ' + at.name), at.link));
    go.addEventListener('click', ouLeave);
    body.appendChild(go);
  }

  var figs = el('div', 'ou-figs');
  var big = el('div', 'ou-total', u.total.said);
  figs.appendChild(big);
  var facts = el('dl', 'ou-facts');
  var fact = function (k, v, node) {
    var d = el('div');
    d.appendChild(el('dt', '', k));
    var dd = el('dd', '', v);
    if (node) dd.appendChild(node);
    d.appendChild(dd);
    facts.appendChild(d);
  };
  fact('Calls', ouCount(u.total.calls));
  fact('Per priced call', u.total.per_call_said);
  fact('Whose', u.whose === 'organisation' ? 'Everyone in your organisation' : 'Only your own calls');
  if (!before.none) {
    fact(u.period.days === 1 ? 'The day before' : 'The period before', before.said + ' ', el('small', '', u.period.before_said));
    var cd = el('div');
    cd.appendChild(el('dt', '', 'Change'));
    var cdd = el('dd');
    cdd.appendChild(ouChange(u.change));
    cd.appendChild(cdd);
    facts.appendChild(cd);
  }
  figs.appendChild(facts);
  body.appendChild(figs);

  // What is not in these dollars, said where it matters.
  var notes = [];
  if (u.plans && (u.plans.claude || u.plans.codex || u.plans.codex_on_key)) {
    var runs = [];
    if (u.plans.claude) runs.push(ouCount(u.plans.claude) + ' Claude Code ' + (u.plans.claude === 1 ? 'run' : 'runs'));
    if (u.plans.codex) runs.push(ouCount(u.plans.codex) + ' Codex ' + (u.plans.codex === 1 ? 'run' : 'runs'));
    var plan = el('div', 'ou-plans');
    plan.appendChild(el('b', '', 'Not in these dollars: '));
    plan.appendChild(document.createTextNode(
      (runs.length ? runs.join(' and ') + ' on the subscriptions, paid by the monthly plans. Their tokens are not logged. ' +
        'Every dollar above is extra, paid per use through Rouh\'s own keys.' : '') +
      (u.plans.codex_on_key ? ' ' + ouCount(u.plans.codex_on_key) + ' Codex ' + (u.plans.codex_on_key === 1 ? 'run was' : 'runs were') +
        ' billed to the OpenAI key instead; that cost is not logged either.' : '')));
    body.appendChild(plan);
  }
  if (u.total.unpriced) {
    notes.push(ouCalls(u.total.unpriced) + ' had no price, so ' + (u.total.unpriced === 1 ? 'it is' : 'they are') +
      ' counted in the calls but not in the dollars.');
  }
  if (before.none) notes.push('The log begins on ' + ouDay(u.began) + ', so there is nothing before this to compare with.');
  else if (before.partial) notes.push('The log begins on ' + ouDay(u.began) + ', part way through the period before, so that period is not complete.');
  if (u.began && u.period.from < u.began && !before.none) notes.push('The log begins on ' + ouDay(u.began) + '.');
  if (notes.length) {
    var n = el('p', 'ou-note');
    n.textContent = notes.join(' ');
    body.appendChild(n);
  }

  if (!u.total.calls) {
    var empty = el('div', 'ou-empty');
    empty.appendChild(el('p', '', 'No calls in ' + ouLower(u.period.said) + '.'));
    var upb = el('button', 'ou-btn', OU.filters.length ? 'Up one level' : 'Back to this month');
    upb.type = 'button';
    upb.addEventListener('click', function () {
      if (OU.filters.length) orbUsageUp();
      else { OU.period = { kind: 'month', at: '', start: '', end: '' }; orbUsageLoad(true); }
    });
    empty.appendChild(upb);
    body.appendChild(empty);
    return;
  }

  ouPaintChart(body, u, paint);
  ouPaintSplit(body, u, paint);

  var all = el('div', 'ou-callsbar');
  var see = el('button', 'ou-btn ou-primary', 'See the ' + ouCount(u.total.calls) + (u.total.calls === 1 ? ' call' : ' calls'));
  see.type = 'button';
  see.addEventListener('click', function () { OU.view = 'calls'; OU.offset = 0; orbUsageLoad(true); });
  all.appendChild(see);
  all.appendChild(el('span', 'ou-hint', 'Each call with its tokens, cost and what started it.'));
  body.appendChild(all);
}

function ouMonth(iso) {
  return ouDate(iso).toLocaleDateString('en-GB', { month: 'long' });
}

// A link out of the screen to the chat, job or page, opened the way every
// other link inside Rouh opens a place (`goToAddress`), with the orb back in
// its corner first so the place it opens is what is on the screen.
function ouLeave(e) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
  var a = /** @type {HTMLAnchorElement} */ (e.currentTarget);
  var href = a && a.getAttribute('href');
  if (!href) return;
  e.preventDefault();
  orbUsageShow(false);
  orbExpand(false);
  goToAddress(href);
}

function ouLower(s) {
  // "November 2026 so far" stays; "Today, Sun 15 Nov" reads "today, Sun 15 Nov" mid-sentence.
  return /^(Today|This week)/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

function ouDay(iso) {
  if (!iso) return '';
  return ouDate(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}

// A round step for an axis that reaches `top`: 1, 2, 2.5 or 5 of a power of
// ten, about four of them.
function orbUsageStep(top) {
  if (!(top > 0)) return 1;
  var rough = top / 4, ten = Math.pow(10, Math.floor(Math.log10(rough)));
  return [1, 2, 2.5, 5, 10].map(function (k) { return k * ten; })
    .filter(function (s) { return s >= rough; })[0];
}

function ouPaintChart(body, u, paint) {
  var s = u.series || { points: [], unit: 'day', keys: [] };
  var pts = s.points || [];
  if (!pts.length) return;
  var part = el('section', 'ou-part');
  var hourly = s.unit === 'hour';
  var title = el('h3', 'ou-h', hourly ? 'Hour by hour' : 'Day by day');
  part.appendChild(title);
  var names = {};
  (u.rows || []).forEach(function (r) { names[r.key] = r.name; });
  part.appendChild(el('p', 'ou-hint', hourly ? 'Press an hour to see its calls by use.' : 'Press a day to see what it was spent on.'));

  var most = 0;
  pts.forEach(function (d) { if (d.cost > most) most = d.cost; });
  var step = orbUsageStep(most);
  var top = Math.max(step, Math.ceil(most / step - 1e-9) * step);
  var places = (String(+step.toFixed(6)).split('.')[1] || '').length;
  var money = function (v) { return '$' + v.toFixed(places); };

  var chart = el('div', 'ou-chart');
  var yAxis = el('div', 'ou-yaxis');
  yAxis.setAttribute('aria-hidden', 'true');
  var plot = el('div', 'ou-plot');
  plot.setAttribute('role', 'group');
  plot.setAttribute('aria-label', hourly ? 'Cost per hour' : 'Cost per day, oldest first');
  for (var v = 0; v <= top + 1e-9; v += step) {
    var pos = (v / top * 100) + '%';
    var tick = el('span', 'ou-ytick', money(v));
    tick.style.bottom = pos;
    yAxis.appendChild(tick);
    var grid = el('i', 'ou-grid' + (v === 0 ? ' ou-base' : ''));
    grid.style.bottom = pos;
    plot.appendChild(grid);
  }
  var xAxis = el('div', 'ou-xaxis');
  xAxis.setAttribute('aria-hidden', 'true');
  var tip = el('div', 'ou-tip');
  tip.hidden = true;

  var label = function (d) {
    if (hourly) return d.at + ':00';
    return ouDate(d.at).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  };
  // A bar opens that day (or hour) as it is, split by use: the coloured parts
  // are only a picture of the split, and the rows under the chart open those.
  var open = function (d) {
    if (hourly) {
      if (!ouHas('day')) OU.filters = OU.filters.concat([['day', u.period.from]]);
      ouDown('hour', String(+d.at));
      return;
    }
    ouDown('day', d.at);
  };
  var cols = [];
  pts.forEach(function (d) {
    var col = el('button', 'ou-col');
    col.type = 'button';
    col.setAttribute('aria-label', label(d) + ': ' + (!hourly && u.began && d.at < u.began ? 'not logged, before the log began.'
      : d.said + ', ' + ouCalls(d.calls) + (d.calls ? '. Open it.' : '.')));
    if (!d.calls) col.disabled = true;
    var stack = el('span', 'ou-stack');
    stack.style.height = (top > 0 ? d.cost / top * 100 : 0) + '%';
    (d.segs || []).forEach(function (g) {
      if (!(g.cost > 0)) return;
      var seg = el('span', 'ou-seg');
      seg.style.flex = (g.cost / d.cost * 100) + ' 1 0';
      seg.style.background = paint(g.key);
      seg.dataset.key = g.key;
      stack.appendChild(seg);
    });
    col.appendChild(stack);
    plot.appendChild(col);
    var lab = el('span', 'ou-xtick', hourly ? d.at : ouDate(d.at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }));
    xAxis.appendChild(lab);
    cols.push({ col: col, day: d, lab: lab });
    col.addEventListener('click', function () { open(d); });
  });
  plot.appendChild(tip);

  var showing = null;
  var show = function (c) {
    if (showing === c) return;
    if (showing) showing.col.classList.remove('on');
    showing = c;
    if (!c) { tip.hidden = true; return; }
    c.col.classList.add('on');
    tip.textContent = '';
    var head = el('div', 'ou-tiphead');
    head.appendChild(el('span', '', label(c.day)));
    var unlogged = !hourly && u.began && c.day.at < u.began;
    head.appendChild(el('b', '', c.day.calls ? c.day.said : unlogged ? 'not logged' : 'nothing'));
    tip.appendChild(head);
    if (!c.day.calls) tip.appendChild(el('div', 'ou-tipnone', unlogged ? 'The log begins on ' + ouDay(u.began) + '.' : 'No calls'));
    (c.day.segs || []).forEach(function (g) {
      var r = el('div', 'ou-tiprow');
      var nm = el('span');
      var sw = el('i', 'ou-sw');
      sw.style.background = paint(g.key);
      nm.appendChild(sw);
      nm.appendChild(document.createTextNode(g.key === '__other__' ? 'Everything else' : (names[g.key] || g.key || 'Not said')));
      r.appendChild(nm);
      r.appendChild(el('span', '', g.said));
      tip.appendChild(r);
    });
    if (c.day.calls) tip.appendChild(el('div', 'ou-tipnone', ouCalls(c.day.calls) + '. Press to open.'));
    tip.hidden = false;
    var pw = plot.clientWidth, x = c.col.offsetLeft, w = c.col.offsetWidth, tw = tip.offsetWidth;
    var left = x + w / 2 < pw / 2 ? x + w + 6 : x - tw - 6;
    tip.style.left = Math.max(0, Math.min(pw - tw, left)) + 'px';
  };
  cols.forEach(function (c) {
    c.col.addEventListener('pointerenter', function () { show(c); });
    c.col.addEventListener('focus', function () { show(c); });
  });
  plot.addEventListener('pointerleave', function () { show(null); });
  plot.addEventListener('focusout', function (e) { if (!plot.contains(/** @type {Node} */ (e.relatedTarget))) show(null); });

  chart.appendChild(yAxis);
  chart.appendChild(plot);
  chart.appendChild(el('span'));
  chart.appendChild(xAxis);
  part.appendChild(chart);

  if (s.split && (s.keys || []).length) {
    var key = el('div', 'ou-legend');
    var other = false;
    pts.forEach(function (d) { (d.segs || []).forEach(function (g) { if (g.key === '__other__') other = true; }); });
    s.keys.concat(other ? ['__other__'] : []).forEach(function (k) {
      var one = el('span');
      var sw = el('i', 'ou-sw');
      sw.style.background = paint(k);
      one.appendChild(sw);
      one.appendChild(document.createTextNode(k === '__other__' ? 'Everything else' : (names[k] || k || 'Not said')));
      key.appendChild(one);
    });
    part.appendChild(key);
  }
  body.appendChild(part);

  var thin = function () {
    if (!part.isConnected || !plot.clientWidth) return;
    var room = plot.clientWidth / pts.length, every = Math.max(1, Math.ceil((hourly ? 26 : 58) / room));
    cols.forEach(function (c, i) {
      // In hundredths of the plot, so a label stays under its bar at any width.
      c.lab.style.left = ((c.col.offsetLeft + c.col.offsetWidth / 2) / plot.clientWidth * 100) + '%';
      c.lab.hidden = (pts.length - 1 - i) % every !== 0;
    });
  };
  OU.thin = thin;
  requestAnimationFrame(thin);
}

function ouPaintSplit(body, u, paint) {
  if (!u.by) return;
  var part = el('section', 'ou-part');
  var head = el('div', 'ou-splithead');
  head.appendChild(el('h3', 'ou-h', 'Split by'));
  var chips = el('div', 'ou-chips');
  chips.setAttribute('role', 'group');
  chips.setAttribute('aria-label', 'Split by');
  (u.can_split || []).forEach(function (c) {
    var b = el('button', 'ou-chip', c.said);
    b.type = 'button';
    b.setAttribute('aria-pressed', c.dim === u.by ? 'true' : 'false');
    b.addEventListener('click', function () { OU.by = c.dim; orbUsageLoad(); });
    chips.appendChild(b);
  });
  head.appendChild(chips);
  part.appendChild(head);

  var rows = u.rows || [];
  var dearest = 0;
  rows.forEach(function (r) { if (r.cost > dearest) dearest = r.cost; });
  /** @type {any} */
  var grow = null;
  if (u.by !== 'day') rows.forEach(function (r) { if (r.change && r.change.delta > 0.005 && (!grow || r.change.delta > grow.change.delta)) grow = r; });
  if (grow && rows.length > 1 && !(u.before && u.before.none)) {
    part.appendChild(el('p', 'ou-grew', 'Grew the most: ' + grow.name + ', ' + grow.change.said + '.'));
  }
  var list = el('ul', 'ou-rows');
  var labels = el('li', 'ou-row ou-rowhead');
  labels.setAttribute('aria-hidden', 'true');
  [[u.by_said, 'ou-rname'], ['', 'ou-rbar ou-rbarhead'], ['Cost', 'ou-rfig'], ['Calls', 'ou-rfig'], ['Against before', 'ou-rfig']]
    .forEach(function (t) { labels.appendChild(el('span', t[1], t[0])); });
  list.appendChild(labels);
  var next = ouNextAfter(u.by);
  rows.forEach(function (r) {
    var li = el('li');
    var b = el('button', 'ou-row');
    b.type = 'button';
    var name = el('span', 'ou-rname');
    var sw = el('i', 'ou-sw');
    sw.style.background = paint(r.key);
    name.appendChild(sw);
    name.appendChild(el('span', 'ou-rtext', r.name));
    var bar = el('span', 'ou-rbar');
    bar.setAttribute('aria-hidden', 'true');
    var fill = el('i');
    fill.style.width = (dearest > 0 && r.cost > 0 ? Math.max(r.cost / dearest * 100, 0.8) : 0) + '%';
    fill.style.background = paint(r.key);
    bar.appendChild(fill);
    var cost = el('span', 'ou-rfig ou-rcost', r.said);
    var calls = el('span', 'ou-rfig');
    var n = el('span', 'ou-n', ouCount(r.calls));
    n.dataset.unit = r.calls === 1 ? ' call' : ' calls';
    calls.appendChild(n);
    if (r.unpriced) calls.appendChild(el('small', '', ouCount(r.unpriced) + ' not priced'));
    var chg = el('span', 'ou-rfig');
    // Days are each their own, so a day against the period before says nothing.
    if (u.by !== 'day') chg.appendChild(ouChange(r.change));
    b.appendChild(name);
    b.appendChild(bar);
    b.appendChild(cost);
    b.appendChild(calls);
    b.appendChild(chg);
    b.setAttribute('aria-label', r.name + ': ' + r.said + ', ' + ouCalls(r.calls) + ', ' + (r.change ? r.change.said : '') +
      '. Open it' + (next ? ', split by ' + next : '') + '.');
    b.addEventListener('click', function () { ouDown(u.by, r.key); });
    li.appendChild(b);
    list.appendChild(li);
  });
  part.appendChild(list);
  if (u.more) {
    part.appendChild(el('p', 'ou-note', 'And ' + ouCount(u.more.count) + ' more, ' + u.more.said + ' together over ' +
      ouCalls(u.more.calls) + '. See the calls below for every one.'));
  }
  body.appendChild(part);
}

function ouNextAfter(dim) {
  var keep = OU.filters;
  OU.filters = keep.concat([[dim, '_']]);
  var n = ouNext();
  OU.filters = keep;
  return ({ provider: 'company', model: 'model', purpose: 'use', day: 'day', origin: 'chat, job or page' })[n] || '';
}

/* ---- the calls ---------------------------------------------------------- */

function ouTokens(n) {
  if (!n) return '0';
  if (n < 1000) return String(n);
  if (n < 100000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  return Math.round(n / 1000) + 'k';
}

function ouPaintCalls(u) {
  ouPaintTrail(u);
  ouPaintPeriod(u.period);
  var body = $('orbUsageBody');
  body.textContent = '';
  var where = (u.trail || []).filter(function (t) { return t.dim !== 'day' && t.dim !== 'hour'; })
    .map(function (t) { return t.name; });
  var h = el('h2', 'ou-headline');
  h.tabIndex = -1;
  h.textContent = ouCount(u.count) + (u.order === 'failed' ? ' failed' : '') + (u.count === 1 ? ' call' : ' calls') +
    (where.length ? ' for ' + where[where.length - 1] : '') + (u.period.days === 1 ? ' on ' : ' in ') + ouLower(u.period.said) +
    (u.order === 'failed' ? ', newest first.' : ', ' + (u.order === 'time' ? 'newest' : 'dearest') + ' first.');
  body.appendChild(h);

  var sort = el('div', 'ou-chips');
  sort.setAttribute('role', 'group');
  sort.setAttribute('aria-label', 'Order');
  [['cost', 'Dearest first'], ['time', 'Newest first'], ['failed', 'Failed only']].forEach(function (o) {
    var b = el('button', 'ou-chip', o[1]);
    b.type = 'button';
    b.setAttribute('aria-pressed', u.order === o[0] ? 'true' : 'false');
    b.addEventListener('click', function () { OU.order = o[0]; OU.offset = 0; orbUsageLoad(); });
    sort.appendChild(b);
  });
  body.appendChild(sort);
  body.appendChild(el('p', 'ou-hint', 'Tokens are the pieces of text a model reads and writes; a thousand tokens are about 750 words. ' +
    'Fresh is read at the full price, from cache far cheaper. Press a call to see why it cost what it did.'));

  var list = el('ul', 'ou-calls');
  var head = el('li', 'ou-call ou-callhead');
  head.setAttribute('aria-hidden', 'true');
  ['When', 'What for', 'Fresh in', 'From cache', 'To cache', 'Out', 'Cost', 'Took'].forEach(function (t, i) {
    head.appendChild(el('span', i < 2 ? 'ou-cw' : 'ou-cn', t));
  });
  list.appendChild(head);
  (u.calls || []).forEach(function (c) {
    var li = el('li');
    var b = el('button', 'ou-call');
    b.type = 'button';
    var when = el('span', 'ou-cw ou-cwhen', c.when);
    var what = el('span', 'ou-cw ou-cwhat');
    what.appendChild(el('b', '', c.use));
    what.appendChild(el('small', '', c.model + ' – ' + c.origin.name + (c.status !== 'ok' ? ' – ' + c.status_said : '')));
    b.appendChild(when);
    b.appendChild(what);
    [['Fresh in', c.fresh], ['From cache', c.cache_read], ['To cache', c.cache_write], ['Out', c.output]].forEach(function (t) {
      var n = el('span', 'ou-cn');
      n.appendChild(el('i', 'ou-clab', t[0] + ' '));
      n.appendChild(document.createTextNode(ouTokens(t[1])));
      b.appendChild(n);
    });
    var cost = el('span', 'ou-cn ou-ccost');
    cost.appendChild(el('i', 'ou-clab', 'Cost '));
    cost.appendChild(document.createTextNode(c.said));
    b.appendChild(cost);
    var took = el('span', 'ou-cn');
    took.appendChild(el('i', 'ou-clab', 'Took '));
    took.appendChild(document.createTextNode(c.took));
    b.appendChild(took);
    b.setAttribute('aria-label', c.when + ', ' + c.use + ' on ' + c.model + ', ' + c.said + '. Why it cost this.');
    b.addEventListener('click', function () { OU.call = c.id; OU.view = 'call'; orbUsageLoad(true); });
    li.appendChild(b);
    list.appendChild(li);
  });
  body.appendChild(list);

  var pages = el('div', 'ou-pages');
  if (u.offset > 0) {
    var prev = el('button', 'ou-btn', 'The 50 before');
    prev.type = 'button';
    prev.addEventListener('click', function () { OU.offset = Math.max(0, u.offset - 50); orbUsageLoad(true); });
    pages.appendChild(prev);
  }
  pages.appendChild(el('span', 'ou-hint', (u.count ? (u.offset + 1) + ' to ' + (u.offset + (u.calls || []).length) + ' of ' : '') + ouCount(u.count)));
  if (u.more) {
    var nextb = el('button', 'ou-btn', 'The next 50');
    nextb.type = 'button';
    nextb.addEventListener('click', function () { OU.offset = u.offset + 50; orbUsageLoad(true); });
    pages.appendChild(nextb);
  }
  body.appendChild(pages);
}

/* ---- one call ----------------------------------------------------------- */

function ouPaintCall(c) {
  ouPaintTrail({ trail: OU.trail || ouTrailNow() });
  $('orbUsagePeriod').textContent = '';
  var body = $('orbUsageBody');
  body.textContent = '';
  var h = el('h2', 'ou-headline');
  h.tabIndex = -1;
  h.textContent = c.why;
  body.appendChild(h);
  body.appendChild(el('p', 'ou-sub', c.when + ' – ' + c.use + ' – ' + c.company + ', ' + c.model));

  var parts = c.parts || [];
  if (parts.length) {
    var sec = el('section', 'ou-part');
    sec.appendChild(el('h3', 'ou-h', 'What the cost is made of'));
    var bar = el('div', 'ou-split');
    bar.setAttribute('aria-hidden', 'true');
    parts.forEach(function (p, i) {
      if (!(p.share > 0)) return;
      var s = el('i');
      s.style.flex = (p.share * 100) + ' 1 0';
      s.style.background = OU_COLOURS[i % OU_COLOURS.length];
      bar.appendChild(s);
    });
    sec.appendChild(bar);
    var t = el('table', 'ou-ptable');
    var th = el('thead');
    var tr = el('tr');
    ['Part', 'Tokens', 'Price a million', 'Cost'].forEach(function (x) { var c2 = el('th', '', x); c2.scope = 'col'; tr.appendChild(c2); });
    th.appendChild(tr);
    t.appendChild(th);
    var tb = el('tbody');
    parts.forEach(function (p, i) {
      var r = el('tr');
      var nm = el('th');
      nm.scope = 'row';
      var sw = el('i', 'ou-sw');
      sw.style.background = OU_COLOURS[i % OU_COLOURS.length];
      nm.appendChild(sw);
      nm.appendChild(document.createTextNode(p.name));
      nm.appendChild(el('small', '', p.said));
      r.appendChild(nm);
      r.appendChild(el('td', '', p.tokens == null ? String(p.count) : ouCount(p.tokens)));
      r.appendChild(el('td', '', p.per_million == null ? '' : '$' + (+p.per_million.toFixed(3))));
      r.appendChild(el('td', 'ou-pcost', p.money));
      tb.appendChild(r);
    });
    t.appendChild(tb);
    sec.appendChild(t);
    if (!c.parts_match) {
      sec.appendChild(el('p', 'ou-note', 'The log says this call cost ' + c.said + '; these parts are worked out from its tokens and list prices, ' +
        'and differ, because this model is billed at a rate of its own.'));
    }
    body.appendChild(sec);
  } else if (c.cost == null && c.status === 'ok') {
    body.appendChild(el('p', 'ou-note', 'Only its tokens are logged for this call, not its price, so it has no dollars here.'));
  }

  var pieces = (c.pieces || []).filter(function (p) { return p.chars; });
  if (pieces.length) {
    var ps = el('section', 'ou-part');
    ps.appendChild(el('h3', 'ou-h', 'What it sent'));
    ps.appendChild(el('p', 'ou-hint', (c.sent ? ouCount(c.sent) + ' tokens in all, ' + Math.round((c.cached_share || 0) * 100) +
      '% of them read from the cache. ' : '') + 'Made of, in characters:'));
    var most = 0;
    pieces.forEach(function (p) { if (p.chars > most) most = p.chars; });
    var pl = el('ul', 'ou-pieces');
    pieces.forEach(function (p) {
      var li = el('li');
      li.appendChild(el('span', 'ou-rtext', p.name));
      var b = el('span', 'ou-rbar');
      var f = el('i');
      f.style.width = Math.max(p.chars / most * 100, 1) + '%';
      b.appendChild(f);
      li.appendChild(b);
      li.appendChild(el('span', 'ou-rfig', ouCount(p.chars)));
      pl.appendChild(li);
    });
    ps.appendChild(pl);
    var conv = (c.pieces || []).filter(function (p) { return p.last; })[0];
    if (conv && (c.pieces || []).some(function (p) { return /\d+ messages$/.test(p.name); })) ps.appendChild(el('p', 'ou-hint', 'The newest message was ' + ouCount(conv.last) + ' characters; the rest is the conversation so far, sent again with every call.'));
    body.appendChild(ps);
  } else {
    body.appendChild(el('p', 'ou-note', 'What this call sent is not logged in parts, only its size: ' + ouCount(c.request_bytes) + ' bytes.'));
  }

  var fs = el('section', 'ou-part');
  fs.appendChild(el('h3', 'ou-h', 'Everything else the log knows'));
  var dl = el('dl', 'ou-facts ou-callfacts');
  var fact = function (k, v, node) {
    if (!v && !node) return;
    var d = el('div');
    d.appendChild(el('dt', '', k));
    var dd = el('dd', '', v || '');
    if (node) dd.appendChild(node);
    d.appendChild(dd);
    dl.appendChild(d);
  };
  var started = null;
  if (c.origin && c.origin.link) {
    started = /** @type {HTMLAnchorElement} */ (linkTo(el('a', 'ou-link', c.origin.name), c.origin.link));
    started.addEventListener('click', ouLeave);
  }
  fact('What started it', started ? '' : (c.origin && c.origin.name), started);
  fact('Paid', 'Per use, through Rouh\'s own ' + c.company + ' key');
  fact('Thinking', [c.thinking, c.effort ? 'effort ' + c.effort : ''].filter(Boolean).join(', '));
  fact('Longest answer allowed', c.max_tokens ? ouCount(c.max_tokens) + ' tokens' : '');
  fact('How it ended', c.status_said + (c.error ? ': ' + c.error : ''));
  fact('Took', c.took + (c.first_word !== 'not logged' ? ', first word after ' + c.first_word : ''));
  fact('Try', c.attempt > 1 ? 'Try ' + c.attempt + ': it was sent again after a failure' : 'The first try');
  if (c.same_turn && c.same_turn.calls > 1) fact('The same reply', c.same_turn.calls + ' calls in all, ' + c.same_turn.said + ' together');
  if (c.same_request > 0) fact('Sent again word for word', c.same_request + (c.same_request === 1 ? ' more time' : ' more times'));
  fs.appendChild(dl);
  body.appendChild(fs);
}

function ouTrailNow() {
  return OU.filters.map(function (f) { return { dim: f[0], value: f[1], name: f[1], what: '' }; });
}

// Wired from app/orb.js, at the place in it where this code always ran.
function wireOrbUsage() {
  var btn = $('orbUsage'), back = $('orbUsageBack');
  if (!btn || !back) return;
  btn.addEventListener('click', function () { orbUsageShow(!orbUsageOpen()); });
  back.addEventListener('click', function () { orbUsageShow(false); });
  window.addEventListener('resize', function () { if (OU.thin && orbUsageOpen()) OU.thin(); });
}

export { orbUsageOpen, orbUsageShow, orbUsageUp, wireOrbUsage };
