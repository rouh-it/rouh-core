/* Rouh's page, what the models cost, in the orb's place
 * (out of app/orb.js).
 *
 * Nothing here runs when the module is loaded: app/orb.js calls wireOrbUsage()
 * at the place in it where this code used to be, so everything happens in
 * the order it always did.
 */
import { $ } from 'app/helpers.js';
import { orbTipHide, ORBX } from 'app/orb.js';
import { orbPanelShow } from 'app/orb_panel.js';

/* ---------- what the models cost, in the orb's place -------------------
 *
 * Petar, 29 September 2026 (fr_f861da23d084): "On the full screen of the
 * orb, I would like an icon button next to volume that will give me a
 * screen with [stats] on LLM usage instead of orb. Pull from our log and
 * give me a day by day cost split in models".
 *
 * The button beside the sound opens it over the open orb and closes it
 * again; so does Back to the orb, and so does Escape. It reads
 * /api/usage/daily afresh every time it opens (`rouh/usage.py`), which adds
 * up the cost of every request in the log, `llm_requests`, per day on the
 * person's own clock and per model. The cost is the log's own, in dollars at
 * list price; nothing is priced here.
 *
 * Petar, 3 October 2026 (fr_f318d715a378): "Make this into a bar graph, and
 * I also want to see the number of calls, not only the cost. Also, put
 * somewhere: average cost per call for each model. I'd like a separate
 * table that shows me what type of calls are made". So the line of model
 * totals became a bar graph, two bars to a model, its cost in its colour
 * and its calls in grey, each against the largest of its own kind, with the
 * cost, the calls and what one call cost written beside them; and under it
 * a table of the calls by the log's own `purpose`.
 */
var OU = { seq: 0 };
//: A colour for each model, dearest first, from the page's own palette.
var OU_COLOURS = ['#5ec2ff', '#a97bf5', '#57d9a3', '#f2b45e', '#ff7a70', '#89cff0', '#e7ecf3', '#8d9aac'];

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
  btn.title = on ? 'Back to the orb' : 'LLM cost and calls';
  // The orb's settings are about the shape, which is not on the screen:
  // one closes the other, whichever is opened second (`orbPanelShow`).
  if (on) orbPanelShow(false);
  orbTipHide();
  if (on) {
    view.scrollTop = 0;
    orbUsageLoad();
    $('orbUsageBack').focus();
  } else if (view.contains(document.activeElement)) {
    btn.focus();
  }
}

function orbUsageLoad() {
  var mine = ++OU.seq;
  $('orbUsageTotal').textContent = '--';
  $('orbUsageSub').textContent = 'Reading the log\u2026';
  $('orbUsageModels').textContent = '';
  $('orbUsageTypes').textContent = '';
  $('orbUsageDays').textContent = '';
  $('orbUsageNote').hidden = true;
  ['orbUsageByModel', 'orbUsageByType', 'orbUsageByDay'].forEach(function (id) { $(id).hidden = true; });
  fetch('/api/usage/daily?days=30', { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error((j && j.error) || ('HTTP ' + r.status));
        return j;
      });
    })
    .then(function (u) { if (mine === OU.seq) orbUsagePaint(u); })
    .catch(function (err) {
      if (mine !== OU.seq) return;
      $('orbUsageSub').textContent = 'The log could not be read: ' + (err && err.message || err);
    });
}

// "2026-09-29" as a person reads a day: "Tue 29 Sep", and how long ago.
function orbUsageDay(iso, today) {
  var p = iso.split('-'), d = new Date(+p[0], +p[1] - 1, +p[2]);
  var t = today.split('-'), n = new Date(+t[0], +t[1] - 1, +t[2]);
  var back = Math.round((n.getTime() - d.getTime()) / 86400000);
  return {
    said: d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }),
    when: back === 0 ? 'today' : back === 1 ? 'yesterday' : ''
  };
}

function orbUsagePaint(u) {
  var colour = {};
  (u.models || []).forEach(function (m, i) { colour[m.model] = OU_COLOURS[i % OU_COLOURS.length]; });
  var swatch = function (model) {
    var sw = document.createElement('i');
    sw.className = 'ou-sw';
    sw.style.background = colour[model] || OU_COLOURS[OU_COLOURS.length - 1];
    return sw;
  };
  var days = u.days || [];
  $('orbUsageTotal').textContent = u.said || '--';
  var from = orbUsageDay(u.began && u.began > u.from ? u.began : u.from, u.to).said;
  $('orbUsageSub').textContent = 'Last ' + u.stretch + ' days, ' + from + ' to today \u00b7 ' +
    (u.requests || 0).toLocaleString('en-GB') + (u.requests === 1 ? ' request' : ' requests') +
    ' \u00b7 US dollars at list price' +
    (u.whose === 'organisation' ? ' \u00b7 everyone in your organisation' : ' \u00b7 your own requests');

  var count = function (n) { return (n || 0).toLocaleString('en-GB'); };
  var cell = function (cls, text) {
    var c = document.createElement('div');
    c.className = cls;
    c.setAttribute('role', 'cell');
    c.textContent = text;
    return c;
  };
  // The calls, and under them how many had no price, which are in the count
  // and not in the cost.
  var calls = function (into, one) {
    into.textContent = count(one.requests);
    if (one.unpriced) {
      var small = document.createElement('small');
      small.textContent = count(one.unpriced) + ' not priced';
      into.appendChild(small);
    }
    return into;
  };
  var models = u.models || [];
  var dearest = 0, busiest = 0;
  models.forEach(function (m) {
    if (m.cost > dearest) dearest = m.cost;
    if (m.requests > busiest) busiest = m.requests;
  });
  var chart = $('orbUsageModels');
  var head = document.createElement('div');
  head.className = 'ou-mrow ou-mhead';
  head.setAttribute('role', 'row');
  [['ou-mname', 'Model'], ['ou-mbars', ''], ['ou-mfig', 'Cost'], ['ou-mfig', 'Calls'],
    ['ou-mfig', 'Per call']].forEach(function (h) {
    var c = cell(h[0], h[1]);
    c.setAttribute('role', 'columnheader');
    head.appendChild(c);
  });
  chart.appendChild(head);
  models.forEach(function (m) {
    var row = document.createElement('div');
    row.className = 'ou-mrow';
    row.setAttribute('role', 'row');
    var name = cell('ou-mname', '');
    name.appendChild(swatch(m.model));
    name.appendChild(document.createTextNode(m.name));
    var bars = document.createElement('div');
    bars.className = 'ou-mbars';
    bars.setAttribute('aria-hidden', 'true');
    var costBar = document.createElement('span');
    costBar.className = 'ou-mcost';
    costBar.style.width = (dearest > 0 && m.cost > 0 ? Math.max(m.cost / dearest * 100, 0.6) : 0) + '%';
    costBar.style.background = colour[m.model];
    var callBar = document.createElement('span');
    callBar.className = 'ou-mcalls';
    callBar.style.width = (busiest > 0 ? Math.max(m.requests / busiest * 100, 0.6) : 0) + '%';
    bars.appendChild(costBar);
    bars.appendChild(callBar);
    row.appendChild(name);
    row.appendChild(bars);
    row.appendChild(cell('ou-mfig ou-mcostn', m.said));
    row.appendChild(calls(cell('ou-mfig', ''), m));
    row.appendChild(cell('ou-mfig', m.per_call_said || 'not priced'));
    chart.appendChild(row);
  });
  var key = document.createElement('p');
  key.className = 'ou-mkey';
  key.textContent = 'The coloured bar is the cost and the grey one the calls, each against the ' +
    'largest of its kind. Per call is the cost over the calls that had a price.';
  chart.appendChild(key);
  $('orbUsageByModel').hidden = !models.length;

  var types = u.purposes || [];
  var tbody = $('orbUsageTypes');
  types.forEach(function (t) {
    var tr = document.createElement('tr');
    var th = document.createElement('th');
    th.scope = 'row';
    th.textContent = t.name;
    // The log's own name for it, whenever the words above are not it.
    if (t.purpose && t.name !== t.purpose.replace(/_/g, ' ')) {
      var code = document.createElement('code');
      code.textContent = t.purpose;
      th.appendChild(code);
    }
    tr.appendChild(th);
    tr.appendChild(calls(document.createElement('td'), t));
    [t.said, t.per_call_said || 'not priced'].forEach(function (v) {
      var td = document.createElement('td');
      td.textContent = v;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  $('orbUsageByType').hidden = !types.length;
  $('orbUsageByDay').hidden = !days.length;

  var notes = [];
  if (u.began && u.began > u.from) {
    notes.push('The log begins on ' + orbUsageDay(u.began, u.to).said +
      ', so nothing before it is counted.');
  }
  if (u.unpriced) {
    notes.push(u.unpriced + (u.unpriced === 1 ? ' request was' : ' requests were') +
      ' to a model with no price on it, or ended before it reported what it used, and ' +
      (u.unpriced === 1 ? 'is' : 'are') + ' not in these amounts.');
  }
  if (!days.length) notes.push('Nothing in the log for these ' + u.stretch + ' days.');
  $('orbUsageNote').textContent = notes.join(' ');
  $('orbUsageNote').hidden = !notes.length;

  // Petar, 4 October 2026 (fr_2b021ac5bac9): "This should be a vertical bar
  // chart where the x-axis is the day and the y-axis is the price, and there
  // should be one legend underneath". One upright bar to a day, oldest on
  // the left, each split into its models' costs in their colours, against a
  // dollar scale; one key under it, and the day's own figures in a tip when
  // a bar is pointed at or tapped.
  orbUsageDaysChart(u, days, colour, swatch);
}

// A round step for an axis that reaches `top`: 1, 2, 2.5 or 5 of a power of
// ten, about four of them.
function orbUsageStep(top) {
  if (!(top > 0)) return 1;
  var rough = top / 4, ten = Math.pow(10, Math.floor(Math.log10(rough)));
  var step = [1, 2, 2.5, 5, 10].map(function (k) { return k * ten; })
    .filter(function (s) { return s >= rough; })[0];
  return step;
}

function orbUsageDaysChart(u, days, colour, swatch) {
  var box = $('orbUsageDays');
  box.textContent = '';
  if (!days.length) return;
  // Every day of the stretch, from the start of the log if it began later,
  // so a day nothing was spent on stands as a gap rather than vanishing.
  var byDay = {};
  days.forEach(function (d) { byDay[d.day] = d; });
  var first = u.began && u.began > u.from ? u.began : u.from;
  var all = [];
  var p = first.split('-'), at = new Date(+p[0], +p[1] - 1, +p[2]);
  var q = u.to.split('-'), end = new Date(+q[0], +q[1] - 1, +q[2]);
  for (; at <= end; at.setDate(at.getDate() + 1)) {
    var iso = at.getFullYear() + '-' + String(at.getMonth() + 1).padStart(2, '0') + '-' +
      String(at.getDate()).padStart(2, '0');
    all.push(byDay[iso] || { day: iso, cost: 0, said: '$0.00', requests: 0, unpriced: 0, models: [] });
  }

  var most = 0;
  all.forEach(function (d) { if (d.cost > most) most = d.cost; });
  var step = orbUsageStep(most);
  var top = Math.max(step, Math.ceil(most / step - 1e-9) * step);
  // As many places as the step has, so $2.5 and $0.25 are said whole.
  var places = (String(+step.toFixed(6)).split('.')[1] || '').length;
  var money = function (v) { return '$' + v.toFixed(places); };

  var chart = document.createElement('div');
  chart.className = 'ou-chart';
  var yAxis = document.createElement('div');
  yAxis.className = 'ou-yaxis';
  yAxis.setAttribute('aria-hidden', 'true');
  var plot = document.createElement('div');
  plot.className = 'ou-plot';
  plot.setAttribute('role', 'list');
  plot.setAttribute('aria-label', 'Cost per day, oldest first');
  for (var v = 0; v <= top + 1e-9; v += step) {
    var pos = (v / top * 100) + '%';
    var tick = document.createElement('span');
    tick.className = 'ou-ytick';
    tick.style.bottom = pos;
    tick.textContent = money(v);
    yAxis.appendChild(tick);
    var grid = document.createElement('i');
    grid.className = 'ou-grid' + (v === 0 ? ' ou-base' : '');
    grid.style.bottom = pos;
    plot.appendChild(grid);
  }
  var xAxis = document.createElement('div');
  xAxis.className = 'ou-xaxis';
  xAxis.setAttribute('aria-hidden', 'true');
  var tip = document.createElement('div');
  tip.className = 'ou-tip';
  tip.hidden = true;

  var cols = [];
  all.forEach(function (d) {
    var when = orbUsageDay(d.day, u.to);
    var col = document.createElement('div');
    col.className = 'ou-col';
    col.setAttribute('role', 'listitem');
    col.tabIndex = 0;
    col.setAttribute('aria-label', when.said + (when.when ? ', ' + when.when : '') + ': ' + d.said +
      (d.models.length ? ' - ' + d.models.map(function (m) { return m.name + ' ' + m.said; }).join(', ') : ''));
    var stack = document.createElement('div');
    stack.className = 'ou-stack';
    stack.style.height = (top > 0 ? d.cost / top * 100 : 0) + '%';
    d.models.forEach(function (m) {
      if (!(m.cost > 0)) return;
      var seg = document.createElement('span');
      seg.className = 'ou-seg';
      // Each model's share of the day, in hundredths: flex-grow that adds up
      // to less than one fills only that much of the bar, which drew a day
      // under a dollar a fraction of its height.
      seg.style.flex = (m.cost / d.cost * 100) + ' 1 0';
      seg.style.background = colour[m.model];
      stack.appendChild(seg);
    });
    col.appendChild(stack);
    plot.appendChild(col);
    var lab = document.createElement('span');
    lab.className = 'ou-xtick';
    var dd = new Date(+d.day.slice(0, 4), +d.day.slice(5, 7) - 1, +d.day.slice(8, 10));
    lab.textContent = dd.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    xAxis.appendChild(lab);
    cols.push({ col: col, day: d, when: when, lab: lab });
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
    var h = document.createElement('div');
    h.className = 'ou-tiphead';
    var dn = document.createElement('span');
    dn.textContent = c.when.said + (c.when.when ? ' · ' + c.when.when : '');
    var dc = document.createElement('b');
    dc.textContent = c.day.said;
    h.appendChild(dn);
    h.appendChild(dc);
    tip.appendChild(h);
    if (!c.day.models.length) {
      var none = document.createElement('div');
      none.className = 'ou-tipnone';
      none.textContent = 'Nothing in the log';
      tip.appendChild(none);
    }
    c.day.models.forEach(function (m) {
      var r = document.createElement('div');
      r.className = 'ou-tiprow';
      var n = document.createElement('span');
      n.appendChild(swatch(m.model));
      n.appendChild(document.createTextNode(m.name));
      var a = document.createElement('span');
      a.textContent = m.said + (m.unpriced ? ' (+' + m.unpriced + ' not priced)' : '');
      r.appendChild(n);
      r.appendChild(a);
      tip.appendChild(r);
    });
    tip.hidden = false;
    // Beside the bar, on whichever side has the room, and never off the plot.
    var pw = plot.clientWidth, x = c.col.offsetLeft, w = c.col.offsetWidth, tw = tip.offsetWidth;
    var left = x + w / 2 < pw / 2 ? x + w + 6 : x - tw - 6;
    tip.style.left = Math.max(0, Math.min(pw - tw, left)) + 'px';
  };
  cols.forEach(function (c) {
    c.col.addEventListener('pointerenter', function () { show(c); });
    c.col.addEventListener('focus', function () { show(c); });
    c.col.addEventListener('click', function (e) { e.stopPropagation(); show(showing === c && e.pointerType !== 'mouse' ? null : c); });
  });
  plot.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse') show(null); });
  plot.addEventListener('focusout', function (e) { if (!plot.contains(/** @type {Node} */ (e.relatedTarget))) show(null); });
  box.addEventListener('click', function () { show(null); });

  chart.appendChild(yAxis);
  chart.appendChild(plot);
  chart.appendChild(document.createElement('span'));
  chart.appendChild(xAxis);
  box.appendChild(chart);

  // The one key, under the chart: every model that cost anything here.
  var seen = {}, key = document.createElement('div');
  key.className = 'ou-legend';
  (u.models || []).forEach(function (m) {
    if (seen[m.model]) return;
    seen[m.model] = true;
    var one = document.createElement('span');
    one.appendChild(swatch(m.model));
    one.appendChild(document.createTextNode(m.name));
    key.appendChild(one);
  });
  box.appendChild(key);

  // As many day labels as fit without touching, always today's.
  var thin = function () {
    if (!box.isConnected || !plot.clientWidth) return;
    var room = plot.clientWidth / all.length, every = Math.max(1, Math.ceil(46 / room));
    cols.forEach(function (c, i) {
      c.lab.style.left = (c.col.offsetLeft + c.col.offsetWidth / 2) + 'px';
      c.lab.hidden = (all.length - 1 - i) % every !== 0;
    });
  };
  thin();
  OU.thin = thin;
}

// Wired from app/orb.js, at the place in it where this code always ran.
function wireOrbUsage() {
  var btn = $('orbUsage'), back = $('orbUsageBack');
  if (!btn || !back) return;
  btn.addEventListener('click', function () { orbUsageShow(!orbUsageOpen()); });
  back.addEventListener('click', function () { orbUsageShow(false); });
  window.addEventListener('resize', function () { if (OU.thin && orbUsageOpen()) OU.thin(); });
}

export { orbUsageOpen, orbUsageShow, wireOrbUsage };
