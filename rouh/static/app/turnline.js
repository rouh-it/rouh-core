/* How one reply was made, at the top of the reply: one closed line, and behind it one timeline.

   Petar, 24 October 2026: "we now have 3 things under the message - timetable, memory and
   model selection. timetables should be unified. the model selection and the topics from the
   memory should be embed as interface in the timetable with hovers or something ... the
   timetable should span the entire width of the chat ... the entire thing should be hidden
   under one optional default closed toggle of one line".

   So the model decision (`route`, `modelrouter.timeline`), the message's memory look-ups
   (`recall`, `recalling.MessageMemory.timeline`) and the turn's steps (`trace`,
   `rouh/turntrace.py`, kept in its record, `rouh/turnrecords.py`) are drawn together, here
   and nowhere else:

   - closed, one line: which tier answered as a two-part marker (pressing a part answers the
     exchange again on that tier, `retry` with `tier`), the model, how sure the router was
     and how long it took, the memory's counts, and the whole turn's time and cost. On a
     narrow screen the words end in "..." and are whole once it is opened (W5);
   - opened, across the whole width of the chat: one row per step on one time axis with its
     scale at the top, and each row's time and cost in one fixed column on the right;
   - each row's details in a popover, on hover with a mouse and on a tap or Enter anywhere;
     the memory row opens into its look-ups with their items; Details opens everything kept.

   Open or closed is remembered per reply on this device. A reply from before turns were
   recorded draws what it kept, its decision and its memory, in the same line. The line can
   be turned off on this device in Settings under Models; the label in place of the dots stays. */
import { el } from 'app/helpers.js';
import { kindOf } from 'app/orb.js';
import { shared } from 'app/shared.js';

/** Whether the line is drawn on this device: on until it is turned off. */
var KEY = 'rouh.trace.v1';
/** The replies left open on this device, by turn (or exchange), newest last. */
var OPEN_KEY = 'rouh.tline.open.v1';
var OPEN_MOST = 300;

function traceOn() {
  try { return localStorage.getItem(KEY) !== 'off'; } catch (e) { return true; }
}

function traceSet(on) {
  try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (e) { /* this tab only */ }
  traceShowAll();
}

/** Every line on the page shown or hidden, as the switch says. */
function traceShowAll() {
  var on = traceOn();
  document.documentElement.classList.toggle('trace-off', !on);
  var sw = document.getElementById('traceSwitch');
  if (sw) sw.setAttribute('aria-checked', String(on));
}

function openKeys() {
  try { return JSON.parse(localStorage.getItem(OPEN_KEY) || '[]') || []; } catch (e) { return []; }
}

function keepOpen(key, open) {
  if (!key) return;
  var keys = openKeys().filter(function (k) { return k !== key; });
  if (open) keys.push(key);
  try { localStorage.setItem(OPEN_KEY, JSON.stringify(keys.slice(-OPEN_MOST))); } catch (e) { /* this tab only */ }
}

// --- words --------------------------------------------------------------------------------

/** "840 ms", "2.4 s", "12 s". */
function took(ms) {
  if (ms == null) return '';
  if (ms < 1000) return Math.round(ms) + ' ms';
  return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + ' s';
}

/** "0.54 s": the router's and the memory's own times, to the hundredth. */
function secs(ms) {
  return ms == null ? '' : (ms / 1000).toFixed(2) + ' s';
}

/** "$0.043", "$0.0043", "$0". */
function dollars(cost) {
  if (cost == null) return '';
  if (!cost) return '$0';
  if (cost < 0.0001) return '<$0.0001';
  return '$' + (cost >= 0.01 ? cost.toFixed(3) : cost.toFixed(4));
}

function tokens(n) {
  if (!n) return '0';
  return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n);
}

function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

/** A moment of the turn, from the message reaching the server: "+0.42 s". */
function at(ms) { return '+' + (ms / 1000).toFixed(2) + ' s'; }

/** The wall-clock time of a moment, to the millisecond: "01:40:12.345". */
function clockAt(sec) {
  var d = new Date(sec * 1000);
  var two = function (n) { return (n < 10 ? '0' : '') + n; };
  return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds()) + '.' +
    String(d.getMilliseconds()).padStart(3, '0');
}

/** How a turn ended. */
var ENDED = { finished: 'Answer finished', stopped: 'Stopped', failed: 'Failed',
  unfinished: 'Waiting for the rest of the question', replaced: 'Replaced by the next message' };

/** What a model's request is doing while it runs. */
var PHASE = { waiting: 'waiting for its first word', thinking: 'thinking', writing: 'writing',
  calling: 'choosing a tool' };

/** How a memory look-up ended. */
var MEMORY = { in_time: 'back in time', empty: 'back in time, nothing found', late: 'late, into a later request',
  carried: 'kept for the next message', failed: 'failed', timeout: 'ran out of time',
  slower: 'answered second, not used', back: 'back', running: 'running' };

/** The tiers an answer can be asked again on, as the Models page names them. */
var TIERS = [['cheaper', 'Cheaper'], ['smart', 'Smart']];

/** A tier as it is named now, from a line kept before 23 October 2026. */
function tierNow(tier) {
  return ({ daily: 'smart', best: 'smart', recommended: 'smart' })[tier] || tier;
}

/** What a tier button does: answer the exchange of the person's message again on a tier.
    Set by app/transcript.js, which owns asking again (`askAgain`). */
var redo = /** @type {null|function(Element, string): boolean} */ (null);
function onRedo(fn) { redo = fn; }

// --- where the line lives -----------------------------------------------------------------

/** The person's message of the exchange `turn` is part of, or null. */
function questionOf(turn) {
  if (!turn) return null;
  if (turn.classList.contains('user')) return turn;
  var root = turn.getAttribute('data-root');
  var host = turn.parentNode;
  if (!root || !host) return null;
  return host.querySelector('.turn.user:not(.steered)[data-root="' + root + '"]');
}

/** The first part of the answer to `question`, which carries the line, or null. */
function answerOf(question) {
  var root = question && question.getAttribute('data-root');
  var host = question && question.parentNode;
  if (!root || !host) return null;
  return host.querySelector('.turn.assistant[data-root="' + root + '"]');
}

/** The line already drawn for `question`'s answer, or for the placeholder standing for it. */
function boxFor(question) {
  var answer = answerOf(question);
  var box = answer && answer.querySelector(':scope > .tline');
  if (box) return box;
  var host = question && question.parentNode;
  var all = host ? host.querySelectorAll('.tline') : [];
  for (var i = 0; i < all.length; i++) if (all[i].__q === question) return all[i];
  return null;
}

/** The line in `turn`, made the first time there is something to say in it. */
function boxIn(turn) {
  var box = turn.querySelector(':scope > .tline');
  if (box) return box;
  box = el('div', 'tline');
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'How this reply was made');
  var head = el('div', 'tl-head');
  var toggle = el('button', 'tl-toggle');
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.appendChild(el('span', 'tl-chev'));
  toggle.appendChild(el('span', 'tl-sum'));
  toggle.appendChild(el('span', 'tl-total'));
  toggle.addEventListener('click', function () { setOpen(box, !box.__open, true); });
  head.appendChild(toggle);
  head.appendChild(el('div', 'tl-tiers'));
  box.appendChild(head);
  var body = el('div', 'tl-body');
  body.hidden = true;
  box.appendChild(body);
  var who = turn.querySelector(':scope > .turn-who');
  turn.insertBefore(box, who ? who.nextSibling : turn.firstChild);
  box.__open = false;
  box.__mem = false;
  return box;
}

/** The name this reply's open or closed state is remembered by. */
function keyOf(box) {
  var tl = box.__tl;
  if (tl && tl.turn_id) return 't' + tl.turn_id;
  var turn = box.parentNode;
  var root = turn && turn.getAttribute && turn.getAttribute('data-root');
  return root ? 'r' + root : '';
}

function setOpen(box, open, pressed) {
  var toggle = box.querySelector('.tl-toggle');
  var scroller = pressed ? box.closest('.transcript') : null;
  var was = scroller ? toggle.getBoundingClientRect().top : 0;
  box.__open = open;
  box.classList.toggle('open', open);
  box.querySelector('.tl-toggle').setAttribute('aria-expanded', open ? 'true' : 'false');
  box.querySelector(':scope > .tl-body').hidden = !open;
  if (pressed) keepOpen(keyOf(box), open);
  popClose();
  paint(box);
  if (open) tick(box);
  // What was pressed stays where it was on the screen: the chat does not follow its end away from it (B1).
  if (scroller) holdStill(scroller, toggle, was);
}

function holdStill(scroller, toggle, was) {
  shared.stick = false;
  scroller.scrollTop += toggle.getBoundingClientRect().top - was;
  shared.stick = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= 4;
}

/** Open again a reply left open, once it is known by its name. */
function remembered(box) {
  if (box.__asked) return;
  var key = keyOf(box);
  if (!key) return;
  box.__asked = true;
  if (openKeys().indexOf(key) >= 0) setOpen(box, true, false);
}

// --- what the line is told ----------------------------------------------------------------

/** The turn's steps (`trace`), live or read back, in `turn`: a reply, or the placeholder standing for
    it. `question` is the person's message it answers, when the caller knows it better than the stream. */
function traceDraw(turn, tl, live, question) {
  if (!turn || !tl) return null;
  var box = boxIn(turn);
  if (question) box.__q = question;
  box.__tl = tl;
  box.__at = Date.now();
  box.__live = !!live;
  if (tl.route) box.__route = tl.route;
  remembered(box);
  paint(box);
  if (live && tl.state === 'running') tick(box);
  return box;
}

/** The line moves from the placeholder into the reply that took its place. */
function traceMove(from, to) {
  var box = from && from.querySelector(':scope > .tline');
  if (!box || !to || to.querySelector(':scope > .tline')) return;
  var who = to.querySelector(':scope > .turn-who');
  to.insertBefore(box, who ? who.nextSibling : to.firstChild);
}

/** How the exchange's model was decided, with the person's message (`turn` is theirs) or with the
    answer (an exchange begun by a note has only that). */
function routeDraw(turn, route) {
  if (!turn || !route) return;
  if (!route.tier_name && !route.model_name) return;
  if (turn.classList.contains('user')) {
    turn.__route = route;
    var box = boxFor(turn);
    if (!box) {
      var answer = answerOf(turn);
      if (answer) box = boxIn(answer);
    }
    if (box) { box.__route = route; box.__q = turn; paint(box); }
    return;
  }
  var first = questionOf(turn) ? answerOf(questionOf(turn)) || turn : turn;
  var b = boxIn(first);
  b.__route = route;
  paint(b);
}

/** Whether a memory timeline has anything to draw (`recalling.shown`). */
function shown(tl) {
  return !!tl && ((tl.bars && tl.bars.length > 0) || (tl.applies === true && tl.named_ms != null));
}

/** The message's memory timeline, with the person's message `turn`, drawn in its answer's line. */
function recallDraw(turn, tl, live) {
  if (!turn) return;
  turn.__recall = shown(tl) ? tl : null;
  turn.__recallAt = Date.now();
  turn.__recallLive = !!live;
  var box = boxFor(turn);
  if (!box && turn.__recall) {
    var answer = answerOf(turn);
    if (answer) box = boxIn(answer);
  }
  if (box) {
    box.__q = turn;
    paint(box);
    if (live && tl && tl.state === 'running') tick(box);
  }
}

/** An answer read back: its line, from whatever its exchange kept, when nothing else drew it. */
function lineFor(answer) {
  var q = questionOf(answer);
  if (!q || answerOf(q) !== answer) return;
  if (!q.__recall && !q.__route) return;
  var box = boxIn(answer);
  box.__q = q;
  if (!box.__route && q.__route) box.__route = q.__route;
  remembered(box);
  paint(box);
}

/** The person's message a live `recall` is about: by the turn, by the message, by the exchange, or
    the newest of theirs not yet in an exchange. */
function recallTurn(host, m) {
  var tl = m.timeline || {};
  var turn = m.turn_id ? host.querySelector('.turn.user[data-recall="' + m.turn_id + '"]') : null;
  if (!turn && tl.msg) turn = host.querySelector('.turn.user[data-msg="' + tl.msg + '"]');
  if (!turn && tl.root) turn = host.querySelector('.turn.user[data-root="' + tl.root + '"]');
  if (!turn) {
    var asks = host.querySelectorAll('.turn.user:not([data-recall]):not([data-root]):not(.partial)');
    turn = asks.length ? asks[asks.length - 1] : null;
  }
  if (turn && m.turn_id) turn.setAttribute('data-recall', String(m.turn_id));
  if (turn && tl.msg && !turn.getAttribute('data-msg')) turn.setAttribute('data-msg', String(tl.msg));
  return turn;
}

/** A live `recall` message. */
function onRecall(host, m) {
  if (!host || m.note) return;
  var turn = recallTurn(host, m);
  if (turn) recallDraw(turn, m.timeline, true);
}

// --- the numbers it is drawn from ---------------------------------------------------------

/** Milliseconds since the turn began, now. */
function nowMs(box) {
  var tl = box.__tl;
  if (!tl) return 0;
  if (tl.state !== 'running' || !box.__live) return tl.elapsed_ms || 0;
  return (tl.elapsed_ms || 0) + (Date.now() - box.__at);
}

/** The memory look-ups, counted as the line says them. */
function memCounts(bars, used, seedsIn) {
  var c = { all: 0, in_time: 0, back: 0, late: 0, carried: 0, failed: 0, running: 0, items: 0 };
  for (var i = 0; i < bars.length; i++) {
    var b = bars[i];
    if (b.tool === 'recall_pick') continue;
    c.all++;
    if (b.outcome === 'in_time' || b.outcome === 'empty') c.in_time++;
    else if (b.outcome === 'late') c.late++;
    else if (b.outcome === 'carried') c.carried++;
    else if (b.outcome === 'failed' || b.outcome === 'timeout') c.failed++;
    else if (b.outcome === 'back') c.back++;
    else c.running++;
    if (seedsIn && b.id === 'seeds' && (b.outcome === 'in_time' || b.outcome === 'late')) c.items += b.count || 0;
  }
  c.items += (used || []).length;
  return c;
}

/** The memory's few words on the closed line: "Memory 7 look-ups, 7 in time, 11 items". */
function memWords(m, lanes) {
  if (m) {
    var looked = (m.bars || []).filter(function (b) { return b.id !== 'seeds' && b.tool !== 'recall_pick'; }).length;
    var c = memCounts(m.bars || [], m.used, true);
    if (m.why && !looked) return 'Memory: ' + m.why + (c.items ? ', ' + plural(c.items, 'item', 'items') : '');
    if (!c.all) return 'Memory: reading the message';
    return 'Memory ' + countsWords(c);
  }
  var bars = lanes.map(function (l) { return { id: l.id, tool: /reading the message/.test(l.name) ? 'recall_pick' : '',
    outcome: l.outcome }; });
  var d = memCounts(bars, [], false);
  return d.all ? 'Memory ' + countsWords(d) : '';
}

function countsWords(c) {
  var parts = [plural(c.all, 'look-up', 'look-ups')];
  if (c.in_time) parts.push(c.in_time + ' in time');
  if (c.back) parts.push(c.back + ' back');
  if (c.late) parts.push(c.late + ' late');
  if (c.carried) parts.push(c.carried + ' for the next message');
  if (c.failed) parts.push(c.failed + ' failed');
  if (c.running) parts.push(c.running + ' running');
  if (c.items || !c.running) parts.push(plural(c.items, 'item', 'items'));
  return parts.join(', ');
}

/** How the model was decided, in a few words: "Opus 5.5 · 74% sure easy (bar 90%) · 0.54 s". */
function decisionWords(r, tl) {
  var model = (r && r.model_name) || (tl && tl.model_name) || '';
  if (!r) return model;
  var bits = [model];
  if (r.outcome === 'chosen') bits.push('picked by you');
  else if (r.outcome === 'chat') bits.push('chat set to ' + (r.chat_choice_name || r.tier_name));
  else if (!r.auto && (r.mode === 'best' || r.mode === 'saver')) bits.push(r.mode === 'best' ? 'Best mode' : 'Saver mode');
  else if (!r.auto) bits.push('fixed tier');
  else if (r.outcome === 'picked') {
    if (r.easy != null) bits.push(Math.round(r.easy * 100) + '% sure easy' + (r.bar ? ' (bar ' + Math.round(r.bar * 100) + '%)' : ''));
    var t = r.took_ms != null ? r.took_ms : r.decided_ms;
    if (t != null) bits.push(secs(t));
    if (r.chat_choice === 'auto') bits.push('chat set to Auto');
  } else if (r.outcome === 'timeout') bits.push('router timed out' + (r.limit_ms ? ' after ' + secs(r.limit_ms) : ''));
  else if (r.outcome === 'unreadable') bits.push('router\'s answer unreadable');
  else if (r.outcome === 'no_router') bits.push('no router');
  else bits.push('router failed');
  return bits.filter(Boolean).join(' · ');
}

function routerName(r) {
  if (r.via === 'decisions') return 'the Decisions API (' + (r.router_name || 'Luna') + ')';
  return r.router_name || 'the router';
}

/** Which colour a row is: the orb's twigs for tools, its own for model requests and for Synapse. */
function colourOf(lane) {
  if (lane.kind === 'memory' || lane.kind === 'memgroup') return 'c-synapse';
  if (lane.kind === 'model' || lane.kind === 'router') return 'c-model';
  if (lane.kind === 'tool') {
    if (/^synapse_/.test(lane.name)) return 'c-synapse';
    return 'c-' + kindOf(lane.name, lane.what);
  }
  return 'c-quiet';
}

/** The rows, in the order drawn: the message's arrival, the decision, memory, the rest as they began,
    and the end. Memory is one row whose look-ups open under it. */
function rowsOf(box) {
  var tl = box.__tl;
  var r = box.__route;
  var q = box.__q || questionOf(box.parentNode);
  var m = q && q.__recall;
  var rows = /** @type {any[]} */ ([]);
  var mem = /** @type {any[]} */ ([]);
  var others = /** @type {any[]} */ ([]);
  // A turn before its record: its decision and its memory on the decision's clock.
  var shift = 0;
  if (!tl && m && r && r.turn_at != null && m.began != null) shift = Math.round((m.began - r.turn_at) * 1000);
  rows.push({ id: 'mark', kind: 'mark', name: 'Message received', start_ms: 0, end_ms: 0, state: 'done' });
  var routerLane = /** @type {any} */ (null);
  if (tl) {
    (tl.lanes || []).forEach(function (l) {
      if (l.kind === 'memory') mem.push(l);
      else if (l.kind === 'router') routerLane = l;
      else others.push(l);
    });
  }
  if (!tl && m) {
    var now = nowRecall(q);
    (m.bars || []).forEach(function (b) {
      var end = b.end_ms == null ? null : shift + b.end_ms;
      mem.push({ id: 'memory-' + b.id, kind: 'memory', name: b.tool === 'recall_pick' ? 'Reading the message with ' + b.what : b.what,
        start_ms: Math.max(0, shift + (b.start_ms || 0)), end_ms: end == null ? null : Math.max(0, end),
        state: b.end_ms == null && m.state === 'running' ? 'running' : 'done', outcome: b.outcome, count: b.count,
        ids: b.ids, error: b.error, cost: b.cost, model: b.model, live_end: shift + now });
    });
  }
  if (r) {
    var dec = /** @type {any} */ ({ id: 'router', kind: 'router', name: 'Model decision', route: r, lane: routerLane });
    if (routerLane) {
      dec.start_ms = routerLane.start_ms; dec.end_ms = routerLane.end_ms; dec.state = routerLane.state;
      dec.cost = routerLane.cost;
    } else if (r.sent_ms != null) {
      dec.start_ms = r.sent_ms;
      dec.end_ms = r.back_ms != null ? r.back_ms : r.decided_ms != null ? r.decided_ms : r.sent_ms;
      dec.state = r.outcome === 'picked' ? 'done' : 'failed';
      dec.cost = r.cost;
    } else {
      dec.start_ms = 0; dec.end_ms = 0; dec.state = 'done'; dec.point = true;
    }
    rows.push(dec);
  } else if (routerLane) {
    rows.push({ id: 'router', kind: 'router', name: 'Model decision', lane: routerLane, start_ms: routerLane.start_ms,
      end_ms: routerLane.end_ms, state: routerLane.state, cost: routerLane.cost });
  }
  if (mem.length) {
    var start = Infinity, end = 0, running = false, cost = 0, priced = false;
    mem.forEach(function (l) {
      start = Math.min(start, l.start_ms);
      if (l.end_ms == null) running = true;
      else end = Math.max(end, l.end_ms);
      if (l.cost != null) { cost += l.cost; priced = true; }
    });
    var failed = mem.every(function (l) { return l.state === 'failed'; });
    rows.push({ id: 'memgroup', kind: 'memgroup', name: 'Memory', start_ms: start, end_ms: running ? null : end,
      state: running ? 'running' : failed ? 'failed' : 'done', cost: priced ? cost : null, lanes: mem, recall: m });
  }
  others.sort(function (a, b) { return a.start_ms - b.start_ms; });
  rows = rows.concat(others);
  if (!tl && m && m.first_ms != null) {
    rows.push({ id: 'asked', kind: 'mark', name: 'The answer was asked for', start_ms: Math.max(0, shift + m.first_ms),
      end_ms: Math.max(0, shift + m.first_ms), state: 'done' });
  }
  if (tl && tl.state !== 'running' && tl.outcome) {
    var e = tl.elapsed_ms || 0;
    rows.push({ id: 'end', kind: 'end', name: ENDED[tl.outcome] || tl.outcome, start_ms: e, end_ms: e,
      state: tl.outcome === 'failed' ? 'failed' : tl.outcome === 'finished' ? 'done' : 'stopped' });
  }
  return rows;
}

/** Milliseconds since the person's message came, as of now, for a memory timeline still running. */
function nowRecall(q) {
  var m = q.__recall;
  if (!m) return 0;
  var base = m.elapsed_ms || 0;
  return q.__recallLive && m.state === 'running' ? base + (Date.now() - (q.__recallAt || Date.now())) : base;
}

/** Where a row's bar ends, now. */
function endOf(row, now) {
  if (row.end_ms != null) return row.end_ms;
  return row.live_end != null ? row.live_end : now;
}

// --- drawing ------------------------------------------------------------------------------

function paint(box) {
  var tl = box.__tl;
  var r = box.__route;
  var q = box.__q || questionOf(box.parentNode);
  var m = q && q.__recall;
  var now = nowMs(box);
  var memLanes = tl ? (tl.lanes || []).filter(function (l) { return l.kind === 'memory'; }) : [];
  // The closed line.
  var words = [decisionWords(r, tl), memWords(m, memLanes)].filter(Boolean).join(' · ');
  if (!words && tl && tl.state === 'running') words = tl.now || 'Starting';
  var sum = box.querySelector('.tl-sum');
  if (sum.textContent !== words) sum.textContent = words;
  var total = '';
  if (tl) {
    total = took(tl.state === 'running' && box.__live ? now : tl.elapsed_ms || 0);
    if (tl.cost != null) total += ' · ' + dollars(tl.cost);
  }
  var tot = box.querySelector('.tl-total');
  if (tot.textContent !== total) tot.textContent = total;
  box.classList.toggle('running', !!(tl && tl.state === 'running' && box.__live));
  tiers(box, q, (r && r.tier) || (tl && tl.tier) || '');
  if (!box.__open) return;
  body(box, rowsOf(box), now);
}

/** The two-part marker of the tier that answered; a press answers it again on the one pressed. */
function tiers(box, q, tier) {
  var group = box.querySelector('.tl-tiers');
  var on = tierNow(tier);
  group.hidden = !on;
  if (!on) return;
  if (!group.firstChild) {
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'The tier that answered; press the other to answer again on it');
    TIERS.forEach(function (t) {
      var b = el('button', 'tl-tier', t[1]);
      b.type = 'button';
      b.setAttribute('data-tier', t[0]);
      b.addEventListener('click', function () {
        var mine = box.__q || questionOf(box.parentNode);
        if (mine && redo && redo(mine, t[0])) b.classList.add('asking');
      });
      group.appendChild(b);
    });
  }
  var btns = group.querySelectorAll('.tl-tier');
  for (var i = 0; i < btns.length; i++) {
    var t = btns[i].getAttribute('data-tier');
    var pressed = t === on;
    btns[i].setAttribute('aria-pressed', pressed ? 'true' : 'false');
    btns[i].disabled = !q;
    btns[i].title = !q ? 'Answered on ' + (pressed ? btns[i].textContent : '') + '; only a message of yours can be asked again'
      : pressed ? 'Answered on ' + btns[i].textContent + '. Press to answer again on it'
      : 'Answer this again on ' + btns[i].textContent;
    if (!btns[i].classList.contains('asking')) continue;
    if (pressed) btns[i].classList.remove('asking');
  }
}

/** The scale: round steps, as many as the room for their labels allows, never more than six. */
function stepOf(span, most) {
  var steps = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000];
  for (var i = 0; i < steps.length; i++) if (span / steps[i] <= most) return steps[i];
  return 120000;
}

function tickWords(t) {
  if (t === 0) return '0';
  return (t % 1000 ? (t / 1000).toFixed(1) : String(t / 1000)) + ' s';
}

/** The opened timeline. Rows are kept and only changed, so nothing on the page jumps (B1). */
function body(box, rows, now) {
  var panel = box.querySelector(':scope > .tl-body');
  var span = Math.max(1, now);
  rows.forEach(function (row) {
    span = Math.max(span, endOf(row, now));
    (row.lanes || []).forEach(function (l) { span = Math.max(span, endOf(l, now)); });
  });
  var axis = panel.querySelector(':scope > .tl-axis');
  if (!axis) {
    axis = el('div', 'tl-axis');
    axis.appendChild(el('span', 'tl-axis-name'));
    axis.appendChild(el('span', 'tl-ticks'));
    var more = el('button', 'tl-details', 'Details');
    more.type = 'button';
    more.addEventListener('click', function () { details(box); });
    axis.appendChild(more);
    panel.appendChild(axis);
    panel.appendChild(el('div', 'tl-rows'));
  }
  // The scale, at the top, with a faint line down through the rows at each step.
  var ticks = axis.querySelector('.tl-ticks');
  var room = ticks.clientWidth || 300;
  var step = stepOf(span, Math.max(2, Math.min(6, Math.floor(room / 44))));
  span = Math.ceil(span / step) * step;
  var pct = function (ms) { return (100 * Math.max(0, Math.min(span, ms)) / span).toFixed(2) + '%'; };
  var said = span + '/' + step + '/' + room;
  if (ticks.__said !== said) {
    ticks.__said = said;
    ticks.textContent = '';
    var lines = panel.querySelector('.tl-grid') || el('div', 'tl-grid');
    lines.textContent = '';
    for (var t = 0; t <= span; t += step) {
      var tk = el('span', 'tl-tick', tickWords(t));
      tk.style.left = pct(t);
      if (t === 0) tk.classList.add('first');
      else if (t >= span) tk.classList.add('last');
      ticks.appendChild(tk);
      var ln = el('span', 'tl-gridline');
      ln.style.left = pct(t);
      lines.appendChild(ln);
    }
    if (!lines.parentNode) panel.querySelector('.tl-rows').appendChild(lines);
  }
  var list = panel.querySelector('.tl-rows');
  var seen = {};
  var before = null;
  for (var i = rows.length - 1; i >= 0; i--) {
    var row = rows[i];
    if (row.kind === 'memgroup') {
      // Its look-ups, when it is open, come right after it.
      var kids = box.__mem ? row.lanes.slice().sort(function (a, b) { return a.start_ms - b.start_ms; }) : [];
      for (var k = kids.length - 1; k >= 0; k--) {
        var chips = chipsRow(list, kids[k], row.recall, 'chips-' + kids[k].id);
        seen['chips-' + kids[k].id] = true;
        before = place(list, chips, before);
        var kid = rowEl(list, box, kids[k], 'sub-' + kids[k].id, now, pct, span);
        kid.classList.add('sub');
        seen['sub-' + kids[k].id] = true;
        before = place(list, kid, before);
      }
    }
    var node = rowEl(list, box, row, row.id, now, pct, span);
    seen[row.id] = true;
    before = place(list, node, before);
  }
  Array.prototype.forEach.call(list.querySelectorAll(':scope > [data-row]'), function (n) {
    if (!seen[n.getAttribute('data-row')]) n.remove();
  });
  // A popover open on a row shows its numbers as they are now.
  if (POP.box === box && POP.row && POP.el && !POP.el.hidden) {
    var fresh = rows.filter(function (x) { return x.id === POP.row.id; })[0];
    if (!fresh) {
      rows.forEach(function (x) { (x.lanes || []).forEach(function (l) { if ('sub-' + l.id === POP.key) fresh = l; }); });
    }
    if (fresh) { POP.row = fresh; popFill(box, fresh); }
  }
}

/** Put `node` just before `before` in `list`, unless it is there already. */
function place(list, node, before) {
  if (node.nextSibling !== before || node.parentNode !== list) list.insertBefore(node, before);
  return node;
}

/** A row's name. */
function nameOf(row) {
  if (row.kind === 'model') return (row.model_name || row.name) + (row.request > 1 ? ' · request ' + row.request : '');
  if (row.kind === 'memory') return String(row.name || '').replace(/^Memory: /, '').replace(/^./, function (c) { return c.toUpperCase(); });
  if (row.kind === 'tool') return row.what || row.name;
  if (row.kind === 'memgroup') {
    var n = row.lanes.filter(function (l) { return !/reading the message/i.test(l.name); }).length;
    return 'Memory · ' + plural(n, 'look-up', 'look-ups');
  }
  if (row.kind === 'router') {
    var r = row.route;
    var tier = r ? r.tier_name : row.lane && row.lane.pick_name;
    return 'Model decision' + (tier ? ': ' + tier : '');
  }
  return row.name;
}

/** A row's one short line on the right: how long, and what it cost. */
function timeOf(row, now, box) {
  if (row.kind === 'mark' && row.id === 'mark') {
    var tl = box.__tl, r = box.__route;
    var t = (tl && tl.turn_at) || (r && r.turn_at);
    return t ? clockAt(t).slice(0, 8) : '';
  }
  if (row.kind === 'mark') return at(row.start_ms);
  if (row.kind === 'end') {
    var all = took(row.start_ms);
    return box.__tl && box.__tl.cost != null ? all + ' · ' + dollars(box.__tl.cost) : all;
  }
  if (row.point) return '';
  var spent = took(Math.max(0, endOf(row, now) - row.start_ms));
  return row.cost != null ? spent + ' · ' + dollars(row.cost) : spent;
}

/** One row: its name, its bar on the axis, and its time. Made once and changed after that. */
function rowEl(list, box, row, key, now, pct, span) {
  var node = /** @type {HTMLElement} */ (list.querySelector(':scope > [data-row="' + CSS.escape(String(key)) + '"]'));
  if (!node) {
    node = el('div', 'tl-row');
    node.setAttribute('data-row', String(key));
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    node.appendChild(el('span', 'tl-name'));
    var track = el('span', 'tl-track');
    track.appendChild(el('span', 'tl-bar'));
    node.appendChild(track);
    node.appendChild(el('span', 'tl-time'));
    wire(node, box);
  }
  node.__row = row;
  node.className = 'tl-row k-' + row.kind + ' s-' + row.state + ' ' + colourOf(row) + (row.point ? ' point' : '') +
    (row.kind === 'memory' && row.outcome ? ' o-' + row.outcome : '') + (key.indexOf('sub-') === 0 ? ' sub' : '');
  if (row.kind === 'memgroup') {
    node.setAttribute('aria-expanded', box.__mem ? 'true' : 'false');
    node.classList.toggle('opened', !!box.__mem);
  } else {
    node.removeAttribute('aria-expanded');
  }
  var name = node.querySelector('.tl-name');
  var said = nameOf(row);
  if (name.textContent !== said) name.textContent = said;
  var bar = /** @type {HTMLElement} */ (node.querySelector('.tl-bar'));
  var end = endOf(row, now);
  bar.style.left = pct(row.start_ms || 0);
  bar.style.width = row.kind === 'mark' || row.kind === 'end' || row.point ? ''
    : 'max(3px, ' + (100 * Math.max(0, end - (row.start_ms || 0)) / span).toFixed(2) + '%)';
  var time = node.querySelector('.tl-time');
  var t = timeOf(row, now, box);
  if (time.textContent !== t) time.textContent = t;
  node.setAttribute('aria-label', said + (t ? ', ' + t : '') + (row.kind === 'memgroup' ? ', press to show its look-ups' : ', press for its details'));
  return node;
}

/** Under a look-up, when memory is open: how it ended and what it found, as chips. */
function chipsRow(list, lane, m, key) {
  var node = /** @type {HTMLElement} */ (list.querySelector(':scope > [data-row="' + CSS.escape(key) + '"]'));
  if (!node) {
    node = el('div', 'tl-chips');
    node.setAttribute('data-row', key);
  }
  var ids = lane.ids || [];
  if (lane.id === 'memory-seeds' && m && m.seed_ids) ids = m.seed_ids;
  var used = (m && m.used) || [];
  var byId = {};
  used.forEach(function (u) { byId[String(u.id)] = u; });
  var sig = [lane.outcome, lane.count, lane.error || '', ids.join(','), used.length].join('|');
  if (node.__sig === sig) return node;
  node.__sig = sig;
  node.textContent = '';
  var how = MEMORY[lane.outcome] || lane.outcome || (lane.state === 'running' ? 'running' : '');
  if (/reading the message/i.test(lane.name)) {
    how = (how ? how + ', ' : '') + plural(lane.count || 0, 'thing picked', 'things picked');
  } else if (lane.count != null && lane.outcome !== 'empty') {
    how = (how ? how + ', ' : '') + plural(lane.count || 0, 'item', 'items');
  }
  if (lane.error) how += ' (' + lane.error + ')';
  node.appendChild(el('span', 'tl-said', how));
  var shown = 0;
  ids.forEach(function (id) {
    var u = byId[String(id)];
    if (!u) return;
    shown++;
    var chip = el('span', 'tl-chip k-' + (u.kind || 'item'), u.title || '(untitled)');
    chip.title = (u.kind || 'item') + ' ' + u.id + (u.when === 'late' ? ', in a later request' : u.when === 'next' ? ', with the next message' : '');
    node.appendChild(chip);
  });
  var rest = ids.length - shown;
  if (rest > 0) {
    var more = el('span', 'tl-chip more', '+' + rest + ' not used');
    more.title = ids.filter(function (id) { return !byId[String(id)]; }).join('\n');
    node.appendChild(more);
  }
  return node;
}

// --- the popover --------------------------------------------------------------------------

var POP = { el: /** @type {HTMLElement|null} */ (null), box: null, row: null, key: '', anchor: null, pinned: false, timer: 0 };
var FINE = typeof matchMedia === 'function' && matchMedia('(hover: hover) and (pointer: fine)').matches;

function wire(node, box) {
  node.addEventListener('click', function () { press(node, box); });
  node.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); press(node, box); }
  });
  if (!FINE) return;
  node.addEventListener('mouseenter', function () {
    if (POP.pinned) return;
    clearTimeout(POP.timer);
    POP.timer = setTimeout(function () { popOpen(node, box, false); }, 140);
  });
  node.addEventListener('mouseleave', function () {
    clearTimeout(POP.timer);
    if (!POP.pinned) POP.timer = setTimeout(function () { if (!POP.pinned && !popHovered()) popClose(); }, 160);
  });
}

function popHovered() {
  return !!(POP.el && POP.el.matches(':hover'));
}

/** A press on a row: memory opens or closes its look-ups; any other row pins its popover, or lets it go. */
function press(node, box) {
  var row = node.__row;
  if (row.kind === 'memgroup') {
    var scroller = box.closest('.transcript');
    var was = node.getBoundingClientRect().top;
    box.__mem = !box.__mem;
    paint(box);
    if (scroller) holdStill(scroller, node, was);
    return;
  }
  if (POP.anchor === node && POP.pinned) { popClose(); return; }
  popOpen(node, box, true);
}

function popEl() {
  if (POP.el) return POP.el;
  var p = el('div', 'tl-pop');
  p.setAttribute('role', 'dialog');
  p.setAttribute('aria-label', 'Details of this step');
  p.hidden = true;
  p.tabIndex = -1;
  p.addEventListener('mouseleave', function () {
    if (!POP.pinned) POP.timer = setTimeout(function () { if (!POP.pinned) popClose(); }, 160);
  });
  p.addEventListener('mouseenter', function () { clearTimeout(POP.timer); });
  document.body.appendChild(p);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && POP.el && !POP.el.hidden) {
      var back = POP.anchor;
      popClose();
      if (back && back.isConnected) back.focus();
      e.stopPropagation();
    }
  }, true);
  document.addEventListener('pointerdown', function (e) {
    if (!POP.el || POP.el.hidden) return;
    var t = /** @type {Node} */ (e.target);
    if (POP.el.contains(t) || (POP.anchor && POP.anchor.contains(t))) return;
    popClose();
  }, true);
  // It is placed against its row; when the page moves under it, it goes.
  document.addEventListener('scroll', function (e) {
    if (POP.el && !POP.el.hidden && !POP.el.contains(/** @type {Node} */ (e.target))) popClose();
  }, true);
  window.addEventListener('resize', function () { popClose(); });
  POP.el = p;
  return p;
}

function popOpen(node, box, pinned) {
  var p = popEl();
  POP.box = box;
  POP.row = node.__row;
  POP.key = node.getAttribute('data-row');
  POP.anchor = node;
  POP.pinned = pinned;
  Array.prototype.forEach.call(document.querySelectorAll('.tl-row.popped'), function (n) { n.classList.remove('popped'); });
  node.classList.add('popped');
  popFill(box, node.__row);
  p.hidden = false;
  // Under its row, or over it where there is no room below; inside the screen either way.
  var rect = node.getBoundingClientRect();
  var w = Math.min(380, window.innerWidth - 16);
  p.style.width = w + 'px';
  var left = Math.min(Math.max(8, rect.left + Math.min(rect.width * 0.3, 160)), window.innerWidth - w - 8);
  p.style.left = left + 'px';
  var h = p.offsetHeight;
  var vh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  var top = rect.bottom + 4;
  if (top + h > vh - 8) top = Math.max(8, rect.top - h - 4);
  p.style.top = top + 'px';
}

function popClose() {
  clearTimeout(POP.timer);
  if (POP.el) POP.el.hidden = true;
  if (POP.anchor) POP.anchor.classList.remove('popped');
  POP.box = null; POP.row = null; POP.key = ''; POP.anchor = null; POP.pinned = false;
}

/** A label and its value, as one line of a popover or of Details. */
function pair(dl, label, value) {
  if (value == null || value === '') return;
  dl.appendChild(el('dt', '', label));
  dl.appendChild(el('dd', '', String(value)));
}

function popFill(box, row) {
  var p = popEl();
  p.textContent = '';
  p.appendChild(el('div', 'tl-pop-head', nameOf(row)));
  var dl = el('dl', 'tl-pop-list');
  facts(dl, box, row, false);
  p.appendChild(dl);
}

/** Everything known about one row. `whole` is for Details: nothing shortened. */
function facts(dl, box, row, whole) {
  var tl = box.__tl;
  var now = nowMs(box);
  var turnAt = (tl && tl.turn_at) || (box.__route && box.__route.turn_at);
  var when = function (ms) { return at(ms) + (turnAt ? ' (' + clockAt(turnAt + ms / 1000) + ')' : ''); };
  if (row.kind === 'mark' && row.id === 'mark') {
    pair(dl, 'At', turnAt ? clockAt(turnAt) : '');
    return;
  }
  if (row.kind === 'mark') { pair(dl, 'At', when(row.start_ms)); return; }
  if (row.kind === 'end') {
    pair(dl, 'Ended', when(row.start_ms));
    if (tl) {
      if (tl.first_token_ms != null) pair(dl, 'First token', at(tl.first_token_ms));
      if (tl.first_word_ms != null) pair(dl, 'First word', at(tl.first_word_ms));
      if (tl.last_word_ms != null) pair(dl, 'Last word', at(tl.last_word_ms));
      if (tl.spoken_ms != null) pair(dl, 'First spoken', at(tl.spoken_ms));
      if (tl.cost != null) pair(dl, 'Cost in all', dollars(tl.cost));
      pair(dl, 'What went wrong', tl.error);
    }
    return;
  }
  if (row.kind === 'router') { routerFacts(dl, row, when, whole); return; }
  if (!row.point && row.start_ms != null) {
    pair(dl, 'Started', when(row.start_ms));
    pair(dl, row.end_ms == null ? 'Running for' : 'Ended', row.end_ms == null ? took(endOf(row, now) - row.start_ms) : when(row.end_ms));
    if (row.end_ms != null) pair(dl, 'Took', took(row.end_ms - row.start_ms));
  }
  if (row.state === 'running' && row.kind === 'model') pair(dl, 'Now', PHASE[row.phase] || 'running');
  if (row.kind === 'memgroup') { memFacts(dl, row, whole); return; }
  if (row.kind === 'model') {
    pair(dl, 'Model', row.model);
    if (row.first_ms != null) pair(dl, 'First token', at(row.first_ms));
    if (row.first_word_ms != null) pair(dl, 'First word', at(row.first_word_ms));
    if (row.tokens_in || row.tokens_out) {
      pair(dl, 'Tokens in', tokens(row.tokens_in) + (row.cache_read ? ', ' + tokens(row.cache_read) + ' cached' : '') +
        (row.cache_write ? ', ' + tokens(row.cache_write) + ' written to the cache' : ''));
      pair(dl, 'Tokens out', tokens(row.tokens_out));
    }
    pair(dl, 'Request', row.request_id != null ? 'row ' + row.request_id + ' of the log of requests' : '');
  }
  if (row.kind === 'memory') {
    pair(dl, 'How it ended', MEMORY[row.outcome] || row.outcome);
    if (row.count != null) pair(dl, 'Found', plural(row.count, 'item', 'items'));
    pair(dl, 'Model', row.model);
    pair(dl, 'What went wrong', row.error);
    if (row.ids && row.ids.length) pair(dl, 'Item ids', whole || row.ids.length <= 6 ? row.ids.join(', ')
      : row.ids.slice(0, 6).join(', ') + ' and ' + (row.ids.length - 6) + ' more');
  }
  if (row.kind === 'tool') {
    pair(dl, 'Tool', row.name);
    if (row.size != null) pair(dl, 'Gave back', plural(row.size, 'character', 'characters'));
    if (row.count != null) pair(dl, 'Found', plural(row.count, 'item', 'items'));
    pair(dl, 'Synapse query', row.synapse_trace);
    pair(dl, 'Given', row.input);
    pair(dl, 'Said back', row.result);
  }
  if (row.cost != null) pair(dl, 'Cost', dollars(row.cost));
  if (row.state === 'failed') pair(dl, 'State', 'failed');
  if (row.state === 'stopped') pair(dl, 'State', 'stopped');
}

function routerFacts(dl, row, when, whole) {
  var r = row.route, lane = row.lane;
  if (r) pair(dl, 'Decided', [r.tier_name, r.model_name].filter(Boolean).join(', '));
  else if (lane) pair(dl, 'Decided', [lane.pick_name, lane.picked_name].filter(Boolean).join(', '));
  if (r && r.outcome === 'chosen') { pair(dl, 'How', 'You picked this tier, so no router ran'); return; }
  if (r && r.outcome === 'chat') {
    pair(dl, 'How', 'This chat is set to ' + (r.chat_choice_name || r.tier_name) + ' beside the box, so no router ran');
    return;
  }
  if (r && r.chat_choice === 'auto') pair(dl, 'Chat', 'Set to Auto beside the box');
  if (r && !r.auto) {
    pair(dl, 'How', r.mode === 'best' || r.mode === 'saver' ? (r.mode === 'best' ? 'Best' : 'Saver') + ' mode: no router'
      : 'This chat is on a fixed tier: no router');
    return;
  }
  var easy = r ? r.easy : lane && lane.easy;
  var bar = r ? r.bar : lane && lane.bar;
  if (easy != null) pair(dl, 'How sure it is easy', Math.round(easy * 100) + '%');
  if (bar) pair(dl, 'The bar for Cheaper', Math.round(bar * 100) + '%');
  if (r) pair(dl, 'Router', routerName(r) + (r.router && r.router_name !== r.router ? ' (' + r.router + ')' : ''));
  else if (lane) pair(dl, 'Router', lane.model_name || lane.model);
  var t = r && (r.took_ms != null ? r.took_ms : r.decided_ms);
  if (t == null && lane && lane.end_ms != null) t = lane.end_ms - lane.start_ms;
  pair(dl, 'Took', t != null ? secs(t) : '');
  if (!row.point && row.start_ms != null) pair(dl, 'Asked', when(row.start_ms));
  if (r && r.limit_ms) pair(dl, 'Limit', secs(r.limit_ms));
  if (r && r.outcome && r.outcome !== 'picked') pair(dl, 'Outcome', ({ timeout: 'timed out', error: 'failed',
    unreadable: 'its answer could not be read', no_router: 'no router to choose with' })[r.outcome] || r.outcome);
  var tin = r ? r.tokens_in : lane && lane.tokens_in;
  if (tin) pair(dl, 'Tokens in', tokens(tin));
  var cost = r && r.cost != null ? r.cost : lane && lane.cost;
  if (cost != null) pair(dl, 'Cost', dollars(cost));
  pair(dl, 'Its reasons', (r && r.reason) || (lane && lane.result));
  pair(dl, 'What went wrong', (r && r.error) || (lane && lane.error));
  if (whole && r && r.decisions_error) pair(dl, 'The Decisions API', r.decisions_error);
}

/** One model's reading of the message: "claude-haiku-4-5 (Anthropic) 1.48 s, agreed". */
function readerSaid(x) {
  var who = x.model + ' (' + (x.provider === 'anthropic' ? 'Anthropic' : x.provider === 'openai' ? 'OpenAI' : x.provider) + ')';
  if (x.ms == null) return who + ' not asked';
  var said = who + ' ' + secs(x.ms);
  if (!x.ok) return said + ', failed' + (x.error ? ' (' + x.error + ')' : '');
  if (x.won) said += ', answered first';
  if (x.agreed === true) said += ', agreed';
  else if (x.agreed === false) said += ', picked differently';
  return said;
}

function memFacts(dl, row, whole) {
  var m = row.recall;
  if (row.cost != null) pair(dl, 'Cost', dollars(row.cost));
  if (!m) return;
  var kinds = [['person', 'People'], ['task', 'Tasks'], ['project', 'Projects'], ['topic', 'Topics']];
  kinds.forEach(function (k) {
    var these = (m.named || []).filter(function (n) { return n.kind === k[0]; });
    if (these.length) pair(dl, k[1], these.map(function (n) { return n.label; }).join(', '));
  });
  if (m.why) pair(dl, 'Looked up', m.why);
  if (m.pick && m.pick.readers) pair(dl, 'Read by', m.pick.readers.map(readerSaid).join('; '));
  if (m.wait_ms) pair(dl, 'The answer waits up to', secs(m.wait_ms));
  var used = m.used || [];
  [['first', 'In the first request'], ['late', 'In a later request'], ['next', 'With the next message']].forEach(function (g) {
    var these = used.filter(function (u) { return u.when === g[0]; });
    if (these.length) pair(dl, g[1], whole ? these.map(function (u) { return u.title + ' (' + u.id + ')'; }).join('; ')
      : plural(these.length, 'item', 'items'));
  });
  (m.carried_in || []).forEach(function (c) {
    pair(dl, 'Carried in', plural(c.items, 'item', 'items') + ' from "' + c.text.slice(0, 60) + (c.text.length > 60 ? '…' : '') + '"');
  });
}

// --- Details ------------------------------------------------------------------------------

/** Everything kept about the reply, every row whole, for a phone as much as for a mouse. */
function details(box) {
  popClose();
  var dlg = /** @type {HTMLDialogElement} */ (document.getElementById('tlDetails'));
  if (!dlg) {
    dlg = /** @type {HTMLDialogElement} */ (el('dialog', 'one-dialog tl-dialog'));
    dlg.id = 'tlDetails';
    dlg.setAttribute('aria-labelledby', 'tlDetailsHead');
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    document.body.appendChild(dlg);
  }
  dlg.textContent = '';
  var top = el('div', 'tl-dialog-top');
  var h = el('h2', '', 'How this reply was made');
  h.id = 'tlDetailsHead';
  top.appendChild(h);
  var close = el('button', 'ctl small', 'Close');
  close.type = 'button';
  close.addEventListener('click', function () { dlg.close(); });
  top.appendChild(close);
  dlg.appendChild(top);
  var inner = el('div', 'tl-dialog-body');
  inner.appendChild(el('p', 'tl-dialog-sum', box.querySelector('.tl-sum').textContent +
    (box.querySelector('.tl-total').textContent ? ' · ' + box.querySelector('.tl-total').textContent : '')));
  rowsOf(box).forEach(function (row) {
    var sec = el('section', 'tl-dialog-row ' + colourOf(row));
    sec.appendChild(el('h3', '', nameOf(row) + (timeOf(row, nowMs(box), box) ? ' · ' + timeOf(row, nowMs(box), box) : '')));
    var dl = el('dl', 'tl-pop-list');
    facts(dl, box, row, true);
    if (dl.firstChild) sec.appendChild(dl);
    inner.appendChild(sec);
    (row.lanes || []).forEach(function (l) {
      var sub = el('section', 'tl-dialog-row sub ' + colourOf(l));
      sub.appendChild(el('h3', '', nameOf(l) + ' · ' + timeOf(l, nowMs(box), box)));
      var d2 = el('dl', 'tl-pop-list');
      facts(d2, box, l, true);
      var q = box.__q || questionOf(box.parentNode);
      var m = q && q.__recall;
      var byId = {};
      ((m && m.used) || []).forEach(function (u) { byId[String(u.id)] = u; });
      var usedHere = (l.ids || []).filter(function (id) { return byId[String(id)]; });
      if (usedHere.length) pair(d2, 'Used', usedHere.map(function (id) { return byId[String(id)].title + ' (' + id + ')'; }).join('; '));
      sub.appendChild(d2);
      inner.appendChild(sub);
    });
  });
  // The record itself, to keep or to weigh against others (`/api/turns/export`).
  var tl = box.__tl;
  var links = el('p', 'tl-dialog-links');
  if (tl && tl.turn_id) {
    var one = el('a', '', 'This turn, whole, as JSON');
    one.href = '/api/turns/export?format=json&turn=' + encodeURIComponent(String(tl.turn_id));
    links.appendChild(one);
  }
  var day = new Date((((tl && tl.turn_at) || (box.__route && box.__route.turn_at)) || Date.now() / 1000) * 1000);
  var ymd = day.getFullYear() + '-' + String(day.getMonth() + 1).padStart(2, '0') + '-' + String(day.getDate()).padStart(2, '0');
  var csv = el('a', '', 'Every turn of that day as CSV');
  csv.href = '/api/turns/export?format=csv&from=' + ymd;
  links.appendChild(csv);
  inner.appendChild(links);
  dlg.appendChild(inner);
  try { dlg.showModal(); } catch (err) { dlg.setAttribute('open', ''); }
  close.focus();
}

// A screen turned or a window made narrower: the scale is laid out again for the room it now has.
window.addEventListener('resize', function () {
  Array.prototype.forEach.call(document.querySelectorAll('.tline.open'), function (box) { paint(box); });
});

// --- the clock ----------------------------------------------------------------------------

/** Every 200 ms while anything runs and the line is on the page. */
function tick(box) {
  if (box.__timer) return;
  box.__timer = setInterval(function () {
    var tl = box.__tl;
    var q = box.__q;
    var memRunning = q && q.__recall && q.__recall.state === 'running' && q.__recallLive &&
      Date.now() - (q.__recallAt || 0) < 35000;
    var running = (tl && tl.state === 'running' && box.__live) || memRunning;
    if (!box.isConnected || !running) {
      clearInterval(box.__timer);
      box.__timer = 0;
      if (box.isConnected) paint(box);
      return;
    }
    paint(box);
  }, 200);
}

export { lineFor, onRecall, onRedo, recallDraw, routeDraw, traceDraw, traceMove, traceOn, traceSet, traceShowAll };
