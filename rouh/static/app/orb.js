/* Rouh's page, the orb (section 7 of what was one app.js).
 *
 * Imports app/playback.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import 'app/playback.js';
import { shared } from 'app/shared.js';
import { $, clamp, drawerLayout, el, now, safeParse } from 'app/helpers.js';
import { cfg, drop, load, panelRgb, store } from 'app/settings.js';
import { S, send } from 'app/socket.js';
import { A, debug, MIC, openThreshold } from 'app/voice.js';
import { showStop, stillSpeaking } from 'app/transcript.js';
import { CARDS, showConflictCard } from 'app/cards.js';
import { taskRecs } from 'app/tasks.js';
import 'app/attachments.js';
import { sbSet } from 'app/controls.js';
import { ORB_SOUND, orbSoundArrived, orbSoundSync, wireOrbSound } from 'app/orb_sound.js';
import { orbUsageOpen, orbUsageShow, wireOrbUsage } from 'app/orb_costs.js';
import { orbPanelOpen, orbPanelPaint, orbPanelShow, wireOrbPanel } from 'app/orb_panel.js';

/* ------------------------------------------------------------------ 7 */

/* The four states a turn moves through. There is no word for them on the
   screen any more: the top bar used to spell one out beside the name, and it
   was the same thing the orb was already saying as movement and the
   transcript as thinking dots, so the word went and the two pictures of it
   stayed. What is left here is the state itself, which is what decides
   whether the page is busy, whether there is a turn to stop, and what the
   orb draws. */
var STATES = { idle: 1, listening: 1, thinking: 1, speaking: 1 };

function setState(v) {
  if (!STATES[v]) return;
  if (S.state === v) return;
  S.state = v;
  if (v === 'speaking') A.openCount = 0;
  // Stop is on screen exactly while there is a turn to stop, and the state
  // is the other half of knowing that: an answer goes on being said for
  // several seconds after the last word of it was written.
  showStop();
}

/* ---------- the work tree, drawn as a structure -----------------------

   The server sends a tree of what is happening right now: the jobs it has
   running, the helpers those started, and the tool calls underneath each
   of them. This draws that tree as an object turning slowly on one axis.

     the machine   the core: three thin crossing rings, with a ring round
                   them breathing slowly - the only thing that moves when
                   nothing is running
     a job         a thick line out of the core, tapering as it goes out
     a helper      a thinner, paler line off its job, 55% of the way out
     a tool call   a short twig along the line that made it, with a mark at
                   its tip for what kind of call it is; the longer the call
                   ran, the longer the twig
     running       a ring breathing at the tip of the line
     waiting       the line turns red and dashed, with a filled square at
                   its tip, a square breathing round it, a ring turning
                   against the rotation and the words NEEDS YOU - never
                   colour alone
     finished      grey and faint for ten seconds, then gone

   The look is the design "Fourth", made and tuned in Claude Design and
   approved on 14 September 2026, and every number below is that design's
   own, except the ones the user set the same day, marked below. It is flat strokes on one 2D canvas: no library, no WebGL, no glow,
   no blur and nothing added together, which is what keeps it calm beside
   the text people are reading. */

var ORB_FRAME_MS = 1000 / 30;
var ORB_CFG = {
  limbLen: 0.4,      // how far a job reaches (the user's; the design had 1)
  bend: 0.23,        // lines bow gently rather than running dead straight
  taperAmt: 0.85,    // a line ends at 15% of the width it starts with
  twigLen: 2,        // how long twigs are (the user's; the design had 1)
  twigSplay: 0.6,    // how far twigs lean out from their line (the user's; the design had 0.25)
  glyphScale: 1,
  wJob: 4, wHelper: 2.9, wAct: 1.65,   // widths in pixels where each starts (wAct the user's; the design had 0.85)
  ghostHold: 10,     // finished work stays this many seconds as a ghost (the user's; the design had 5.5)
  ghostLevel: 0.3,   // at this opacity (the user's; the design had 0.28)
  spin: 0.07,        // radians a second, about one axis only
  zoom: 2.4,         // how much of its frame the object fills (the user's; the design had 1.45)
  spreadK: 2.7,      // how hard lines off the same parent push each other apart
  driftK: 0,         // how fast each line wanders on its own (the user's; the design had 1)
  // Not the design's: the sound of the orb opened over the whole screen,
  // asked for on 24 September 2026 (fr_f3ced3c15b3e). Per cent of the
  // loudest each is built to be, which is already soft. See `ORB_SOUND`.
  noteVol: 70,       // the note each new line or tool call plays
  musicVol: 45       // the string chords underneath them
};
// A finished tool call fades to its ghost over 1.2 s, a job or a helper over
// 1.5 s; after the hold, the ghost leaves over 1.8 s.
var GHOST_IN_STEP = 1.2, GHOST_IN_NODE = 1.5, GHOST_OUT = 1.8;
var MAX_TWIGS = 22;       // the newest calls on one line; older ones are not drawn
var MAX_ITEMS = 2400;     // a ceiling on what one frame can be asked to draw

/* ---------- the settings behind the cog wheel -------------------------

   Every number in ORB_CFG is the approved design's, and the drawing loop
   reads that object on every frame. So the cog wheel in the corner of the
   open orb edits the live object and the shape changes under the slider:
   there is no scene to rebuild, because the shape is rebuilt thirty times a
   second anyway.

   ORB_BASE is the approved design, kept aside so any setting can be put
   back. What is saved is only what differs from it, so a later change to the
   design reaches anybody who never touched that slider.

   The panel is the design "Orb Editor", made in Claude Design: three groups
   of sliders, each row its label and its value, and the value in the unit
   the design chose. Four of the design's ranges ended exactly where the
   user's own setting sits - zoom, twig length, ghost opacity and ghost hold -
   so those sliders could not be pushed further than the value they opened
   on; the first two are widened here. The ghost hold is not: the orb
   promises that finished work is gone within 13.5 seconds, and with the fade
   in at 1.5 s and the fade out at 1.8 s, ten seconds is the whole of what is
   left. The design's other ranges are its own. */

var KEY_ORB = 'rouh.orb.v1';

var ORB_BASE = (function () {
  var out = {};
  for (var k in ORB_CFG) out[k] = ORB_CFG[k];
  return out;
})();

// [key, label, min, max, step, unit]. The unit is written after the value.
var ORB_GROUPS = [
  ['geometry', [
    ['zoom', 'zoom', 0.6, 4, 0.05, 'x'],
    ['limbLen', 'limb length', 0.15, 1.4, 0.05, 'x'],
    ['bend', 'limb bend', 0, 0.5, 0.01, ''],
    ['taperAmt', 'taper strength', 0, 0.95, 0.05, ''],
    ['twigLen', 'twig length', 0.4, 3, 0.05, 'x'],
    ['twigSplay', 'twig splay', 0, 1.4, 0.05, ''],
    ['glyphScale', 'glyph size', 0.4, 2, 0.1, 'x'],
    ['wJob', 'job thickness', 0.8, 6, 0.1, 'px'],
    ['wHelper', 'helper thickness', 0.5, 4, 0.1, 'px'],
    ['wAct', 'tool-call thickness', 0.5, 3, 0.05, 'px']
  ]],
  ['motion', [
    ['spin', 'rotation speed', 0, 0.4, 0.01, ''],
    ['spreadK', 'sibling repulsion', 0, 6, 0.1, 'x'],
    ['driftK', 'idle drift', 0, 3, 0.1, 'x']
  ]],
  ['lifecycle', [
    ['ghostHold', 'ghost lingers', 0, 10, 0.5, 's'],
    ['ghostLevel', 'ghost opacity', 0, 0.4, 0.02, '']
  ]],
  ['sound', [
    ['noteVol', 'notes', 0, 100, 5, '%'],
    ['musicVol', 'music', 0, 100, 5, '%']
  ]]
];

var ORB_ROWS = (function () {
  var out = Object.create(null), i, j, rows;
  for (i = 0; i < ORB_GROUPS.length; i++) {
    rows = ORB_GROUPS[i][1];
    for (j = 0; j < rows.length; j++) out[rows[j][0]] = rows[j];
  }
  return out;
})();

// A saved value is only taken if it is a number of the same kind as the
// design's and inside the slider it came from. A stored file from an older
// build, or one somebody has edited by hand, must not be able to put the orb
// somewhere the panel cannot bring it back from.
function orbSane(key, v) {
  var row = ORB_ROWS[key];
  if (typeof v !== 'number' || !isFinite(v) || !row) return null;
  return clamp(v, row[2], row[3]);
}

/* ---------- where these are kept, and whose they are ------------------

   They are the person's settings, and until 22 September 2026 they were only
   this browser's: one object in local storage, keyed by nothing and known to
   nobody. What that meant is that a look tuned on the desktop was not on the
   phone, and was gone from the desktop too the moment that browser dropped
   its site data, which a phone does by itself. Two sliders moved and a
   sign-in later, the panel was back at the approved design.

   So the truth is a row of Rouh's own database, keyed by who
   (`rouh/settings.py`). It arrives with `ready` and goes back with
   `set_orb`, and it is what crosses a refresh, a restart of the service and
   a second device.

   The browser's copy stays, as a mirror rather than as the truth. It draws
   the first frame - the orb is running well before there is a socket to ask
   on - and it is how two tabs of one browser follow each other. Where the
   two disagree the server wins, because it is the one both devices can see.

   What is saved either side is only what differs from the approved design,
   so a later change to the design still reaches anybody who never touched
   that slider. */

function orbOffDesign() {
  var out = {}, k;
  for (k in ORB_BASE) if (ORB_CFG[k] !== ORB_BASE[k]) out[k] = ORB_CFG[k];
  return out;
}

function orbAny(out) { for (var k in out) return true; return false; }

// The browser's own copy. Nothing left to remember means nothing kept: a
// page that has been put back to the design must not find a stale object
// here and draw it before the socket can say otherwise.
function orbMirror(out) {
  if (orbAny(out)) store(KEY_ORB, JSON.stringify(out));
  else drop(KEY_ORB);
}

/* One saved object onto the live one the drawing loop reads. Whatever it
   does not name goes back to the design, so this is the whole of the
   settings and never a patch over what happened to be there: the server
   saying "nothing is moved" has to be able to move a slider back. Says
   whether anything actually changed. */
function orbTake(saved) {
  var k, v, moved = false;
  saved = (saved && typeof saved === 'object') ? saved : {};
  for (k in ORB_BASE) {
    v = Object.prototype.hasOwnProperty.call(saved, k) ? orbSane(k, saved[k]) : null;
    if (v === null) v = ORB_BASE[k];
    if (ORB_CFG[k] !== v) { ORB_CFG[k] = v; moved = true; }
  }
  return moved;
}

function orbLoadCfg() { orbTake(safeParse(load(KEY_ORB))); }

/* Saved on a timer rather than on every frame of a drag. The live object is
   written at once, so the picture never waits; thirty writes a second to the
   browser's store and thirty messages a second up the socket, each one
   turning the whole of the settings into text, would be work nobody asked
   for. Flushed the moment the page goes away. */
var orbSaveAt = 0;

/* What was saved and did not reach the server, because the socket was not
   open at that moment. Sent on the next `ready`, which is also what stops
   that handshake handing back the older copy the server still has over the
   newer one this page is showing. */
var orbUnsent = null;

function orbPush(out) {
  orbUnsent = out;
  if (send({ type: 'set_orb', cfg: out })) orbUnsent = null;
}

function orbWriteCfg() {
  var out = orbOffDesign();
  orbMirror(out);
  orbPush(out);
}

function orbSaveSoon() {
  if (orbSaveAt) clearTimeout(orbSaveAt);
  orbSaveAt = setTimeout(function () { orbSaveAt = 0; orbWriteCfg(); }, 300);
}

function orbSaveNow() {
  if (orbSaveAt) { clearTimeout(orbSaveAt); orbSaveAt = 0; }
  orbWriteCfg();
}

/* The settings as the server has them, on every connect. Three answers:

     something   this person's saved settings, and they win. An empty object
                 is one of these and means they put everything back.
     nothing     they have never saved any. The copy this browser already
                 has is theirs too - it was set before there was anywhere
                 else to keep it - so it goes up rather than being thrown
                 away. That is the whole of the migration.
     ours first  something written here never got out. It goes now, and the
                 server's older copy is not taken. */
function orbFromServer(saved) {
  if (orbUnsent) { orbPush(orbUnsent); return; }
  if (!saved || typeof saved !== 'object') {
    var mine = orbOffDesign();
    if (orbAny(mine)) orbPush(mine);
    return;
  }
  if (!orbTake(saved)) return;
  orbMirror(orbOffDesign());
  // The panel is a column of sliders drawn from these numbers, so if it is
  // open while this lands it is redrawn rather than left saying the old ones.
  if (typeof orbPanelOpen === 'function' && orbPanelOpen()) orbPanelPaint();
}

// Whether a setting has been moved off the design, which is what decides
// whether its own "put it back" control is there to be used.
function orbMoved(key) { return ORB_CFG[key] !== ORB_BASE[key]; }

orbLoadCfg();
window.addEventListener('pagehide', orbSaveNow);
// Another tab moving a slider moves this one's orb too, so two tabs open
// side by side never disagree about what the orb looks like. The tab that
// moved it has already told the server, so this one only reads.
window.addEventListener('storage', function (e) {
  if (e && e.key && e.key !== KEY_ORB) return;
  orbLoadCfg();
  if (typeof orbPanelPaint === 'function') orbPanelPaint();
});

var slowMo = false;
try { slowMo = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) {}

/* The design's palette. The design is dark, as the page is, so there is one
   set of these and nothing chooses between them. */
var ORB_PAL = {
  ink: '#cfd9ee', dim: '#6f7590',
  job: '#2ab6de', agent: '#86d8ef', wait: '#ff2b4a',
  search: '#e8b456', page: '#e07b2a', code: '#57c98a',
  shell: '#7a6bd0', read: '#6e7793', edit: '#ff3ec8',
  // The storage ring round the core: light grey while the disk has room,
  // amber from 65% used, red above 80% (the page's --warn and --bad).
  disk: '#c3cad4', diskWarm: '#f2b45e', diskHot: '#ff7a70'
};

/* Six kinds of tool call. Each is said twice, by its colour and by the mark
   at its tip, so the kind survives greyscale, colour blindness and the
   96 px circle. `mark` is the same mark written as text, for the labels. */
var ORB_KIND = {
  search: { glyph: 'chev', mark: '›' },
  page:   { glyph: 'square', mark: '▭' },
  code:   { glyph: 'tri', mark: '▲' },
  shell:  { glyph: 'bars', mark: '‖' },
  read:   { glyph: 'dot', mark: '·' },
  edit:   { glyph: 'cross', mark: '×' }
};

/* Which kind a tool call is. Covers both vocabularies that reach the orb:
   Claude Code's tools inside a job, and Rouh's own. Anything else is
   drawn as reading, the quietest colour and the safest guess. */
function kindOf(label, what) {
  switch (String(label || '')) {
    case 'WebSearch': case 'web_search':
      return 'search';
    case 'WebFetch': case 'web_fetch':
      return 'page';
    case 'code_execution': case 'bash_code_execution': case 'text_editor_code_execution':
      // A search is its own call now, so it arrives here as web_search above.
      // This stays for code that searches or reads anyway: web_search and
      // web_fetch run code on Anthropic's side themselves to sift a page, and
      // a background job can run code too. The code's words, from worklabel,
      // say when it searches or reads, and it is drawn as what it does;
      // otherwise research never showed as research.
      if (/^Running code that searches the web/.test(what || '')) return 'search';
      if (/^Running code that reads /.test(what || '')) return 'page';
      return 'code';
    case 'Bash': case 'BashOutput': case 'KillShell': case 'run_command':
      return 'shell';
    case 'Edit': case 'MultiEdit': case 'Write': case 'NotebookEdit':
      return 'edit';
    default:
      return 'read';
  }
}

// A colour part of the way to another: how a finished call loses its colour
// to the structural grey, so only live work is bright. Worked out once each.
var INK_MEMO = Object.create(null);
function hexMix(a, b, t) {
  var key = a + b + t;
  if (INK_MEMO[key]) return INK_MEMO[key];
  var o = '#';
  for (var i = 1; i < 7; i += 2) {
    var x = parseInt(a.slice(i, i + 2), 16), y = parseInt(b.slice(i, i + 2), 16);
    var v = Math.round(x + (y - x) * t).toString(16);
    o += v.length < 2 ? '0' + v : v;
  }
  return (INK_MEMO[key] = o);
}

/* ---------- vectors and directions ---------- */

function hash01(s) {
  var h = 2166136261, i;
  s = String(s);
  for (i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 100003) / 100003;
}

// The same numbers for the same id every time, so a line keeps the
// direction it was given across a reload.
function orbRand(seed) {
  var s = Math.floor(seed * 2147483646) + 1;
  return function () { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
}

function vnorm(v) {
  var m = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
  v[0] /= m; v[1] /= m; v[2] /= m;
  return v;
}

function randDir(r) {
  var z = r() * 2 - 1, a = r() * 6.2831853, s = Math.sqrt(1 - z * z);
  return [Math.cos(a) * s, z, Math.sin(a) * s];
}

// The point a fraction t of the way from a to b, written into `out`.
function vmix(a, b, t, out) {
  out[0] = a[0] + (b[0] - a[0]) * t;
  out[1] = a[1] + (b[1] - a[1]) * t;
  out[2] = a[2] + (b[2] - a[2]) * t;
  return out;
}

/* ---------- the scene: one record per node, kept across updates -------

   The tree that arrives is the truth about what is running. This is the
   picture of it, which has to remember a little more than the tree does: the
   direction a line was given, and how far through fading a finished one is. */

var SCENE = Object.create(null);
var ORDER = [];               // parents before children, always
var treeStamp = 0;
var haveTree = false;
var pruneAt = 0;
shared.askedTreeAt = 0;

/* The tree's times are read off the server's clock, and this browser's clock
   is a different one. With finished work gone in a second and a half, a
   browser two seconds behind the server would keep a stopped job on screen
   until its own clock caught up. Every tree carries the server's time as it
   was sent; the largest recent gap is the one with the least network delay
   in it, so that is the one used. */
var clockGaps = [];
var serverAhead = 0;      // milliseconds the server's clock is ahead of this one
function noteServerClock(sec) {
  var gap = sec * 1000 - Date.now();
  if (!isFinite(gap)) return;
  clockGaps.push(gap);
  if (clockGaps.length > 40) clockGaps.shift();
  serverAhead = Math.max.apply(null, clockGaps);
}

function clampTime(sec, fallback) {
  var ms = sec * 1000 - serverAhead;
  var t = now();
  if (!(ms > 0) || ms > t + 60000 || ms < t - 3600000) return fallback;
  return ms;
}

function applyTree(root) {
  if (!root || typeof root !== 'object') return;
  haveTree = true;
  var stamp = ++treeStamp;
  var t = now();
  var order = [];
  var stack = [[root, null, 0]];
  var guard = 0;
  var born = [];

  while (stack.length && guard++ < 2000) {
    var top = stack.pop();
    var raw = top[0], parentId = top[1], depth = top[2];
    if (!raw || typeof raw !== 'object') continue;
    var id = String(raw.id == null ? (parentId || '') + '#' + order.length : raw.id);
    var n = SCENE[id];
    var fresh = !n;
    if (!n) {
      n = SCENE[id] = {
        id: id, parent: parentId, depth: depth,
        kind: raw.kind || 'tool', label: raw.label || '',
        state: raw.state || 'running',
        opened: clampTime(raw.opened_at, t), closed: 0,
        fade: 0, alpha: 1, jit: hash01(id), dir: null, seen: 0
      };
    }
    n.kind = raw.kind || n.kind;
    n.label = raw.label || n.label;
    n.state = raw.state || n.state;
    n.raw = raw;
    n.depth = depth;
    n.seen = stamp;
    // Something this page watched running starts its fade the moment the
    // news arrives, so the end is always seen in full, whatever second the
    // server rounded the time to. Something first seen already finished
    // fades from when it finished, so a reconnect does not bring it back.
    if (n.state === 'done' || n.state === 'failed' || n.state === 'lost') {
      if (!n.closed) n.closed = clampTime(raw.closed_at, t);
      if (!n.fade) n.fade = fresh ? n.closed : Math.max(n.closed, t);
    } else {
      n.closed = 0;
      n.fade = 0;
    }
    if (fresh && parentId) born.push(n);
    order.push(id);
    var kids = raw.children;
    if (kids && kids.length) {
      for (var i = kids.length - 1; i >= 0; i--) stack.push([kids[i], id, depth + 1]);
    }
  }

  // Anything the tree no longer mentions is over. It is not deleted at once;
  // it fades to a ghost and then out, so the end is seen rather than blinking out.
  var k, seenSet = Object.create(null);
  for (k = 0; k < order.length; k++) seenSet[order[k]] = 1;
  var tail = [];
  for (k = 0; k < ORDER.length; k++) {
    var old = SCENE[ORDER[k]];
    if (!old || seenSet[old.id]) continue;
    if (!old.fade) old.fade = t;
    tail.push(old.id);
  }
  ORDER = order.concat(tail);
  // Everything that was not on the screen a moment ago, for the sound the
  // orb makes when it is open (`orbSoundArrived`).
  if (born.length) orbSoundArrived(born);
}

// A line's own direction, its slow wander, where along its parent it sits
// if it is a tool call, and where in its slow bow it starts - all from its id.
function motionOf(n) {
  if (n.dir) return;
  var r = orbRand(n.jit);
  n.dir = randDir(r);
  n.axis = randDir(r);
  n.spin = n.kind === 'tool' ? 0.03 : (r() - 0.5) * (n.kind === 'subagent' ? 0.08 : 0.06);
  n.along = 0.3 + r() * 0.65;
  n.phase = r() * 6.2831853;
  n.ldir = [0, 0, 0];        // the direction it is drawn in, after its parent's pull
  n.wp = [];                 // its points in space
  n.sp = [];                 // and on the screen
  n.pn = 0;                  // how many of them this frame
}

// Every line wanders slowly about an axis of its own, so the object keeps
// moving even when nothing changes.
function drift(n, dt) {
  var ang = n.spin * dt, ax = n.axis, d = n.dir, c = Math.cos(ang), s = Math.sin(ang);
  var dot = ax[0] * d[0] + ax[1] * d[1] + ax[2] * d[2];
  var cx = ax[1] * d[2] - ax[2] * d[1], cy = ax[2] * d[0] - ax[0] * d[2], cz = ax[0] * d[1] - ax[1] * d[0];
  var x = d[0] * c + cx * s + ax[0] * dot * (1 - c);
  var y = d[1] * c + cy * s + ax[1] * dot * (1 - c);
  var z = d[2] * c + cz * s + ax[2] * dot * (1 - c);
  d[0] = x; d[1] = y; d[2] = z;
  vnorm(d);
}

// Lines off the same parent push each other apart, harder the closer they
// are, so they spread out evenly and move aside over a second or two when a
// new one arrives rather than jumping.
function spread(list, dt, k, still) {
  var n = list.length, i, j;
  for (i = 0; i < n; i++) {
    var a = list[i], fx = 0, fy = 0, fz = 0;
    for (j = 0; j < n; j++) {
      if (i === j) continue;
      var b = list[j];
      var dx = a.dir[0] - b.dir[0], dy = a.dir[1] - b.dir[1], dz = a.dir[2] - b.dir[2];
      var w = k / (dx * dx + dy * dy + dz * dz + 0.02);
      fx += dx * w; fy += dy * w; fz += dz * w;
    }
    a.dir[0] += fx * dt * 2.2; a.dir[1] += fy * dt * 2.2; a.dir[2] += fz * dt * 2.2;
    vnorm(a.dir);
    if (!still) drift(a, dt * ORB_CFG.driftK);
  }
}

// How much of a piece is showing: all of it while it runs; once it has
// finished, down to a ghost, held there, then out.
function orbAlpha(n, tnow) {
  if (!n.fade) return 1;
  var e = (tnow - n.fade) / 1000, into = n.kind === 'tool' ? GHOST_IN_STEP : GHOST_IN_NODE;
  var lvl = ORB_CFG.ghostLevel, hold = ORB_CFG.ghostHold;
  if (e < into) return 1 - (1 - lvl) * (e / into);
  if (e < into + hold) return lvl;
  return Math.max(0, lvl * (1 - (e - into - hold) / GHOST_OUT));
}

// Whether Rouh is at work on an answer, and so whether its own line is
// drawn: from the moment it starts on one until it has said the last of it,
// and while any call of its own is open. Then it leaves the way finished
// work does, through a ghost, and comes back without growing again if the
// answer carries on while the ghost is still showing.
function selfTurn(tnow) {
  var open = false, i;
  for (i = 0; i < ORB_OWN.length; i++) if (!ORB_OWN[i].fade) open = true;
  // A stopped turn ends the line there and then, whatever is still open on
  // it. The person ended the turn, so the picture of it ends too - and it
  // ends marked, with a bar across the tip, rather than fading away the way
  // an answer that ran to the end does.
  // `stillSpeaking` is here for the same reason it is in `turnIsRunning`:
  // the answer goes on being said for seconds after the last word of it was
  // written, and the line belongs to the work, not to the writing. It is
  // also what ends the line - once the turn is over by that measure too,
  // nothing holds it open and it leaves the way finished work does.
  var working = (open || S.busy || S.state === 'thinking' || S.state === 'speaking'
                 || stillSpeaking())
    && !S.stopped;
  if (working) {
    if (!SELF.opened || orbAlpha(SELF, tnow) <= 0.005) {
      SELF.opened = tnow;
      orbSoundArrived([SELF]);
    }
    SELF.fade = 0; SELF.closed = 0; SELF.state = 'running';
  } else if (SELF.opened && !SELF.fade) {
    SELF.fade = tnow; SELF.closed = tnow;
    SELF.state = S.stopped ? 'stopped' : 'done';
  }
  SELF.alpha = SELF.opened ? orbAlpha(SELF, tnow) : 0;
  if (SELF.alpha <= 0.005 && SELF.fade) { SELF.opened = 0; SELF.fade = 0; SELF.closed = 0; }
  SELF.calls = ORB_OWN;
  if (SELF.alpha > 0.005) motionOf(SELF);
}

// Every frame: each piece's opacity, which line each hangs off, and the push
// between lines off the same parent.
function orbScene(tnow, dt, still) {
  var i, n, p, list = ORDER, k = ORB_CFG.spreadK;
  ORB_JOBS.length = 0;
  ORB_OWN.length = 0;
  for (i = 0; i < list.length; i++) {
    n = SCENE[list[i]];
    if (!n) continue;
    if (n.subs) { n.subs.length = 0; n.calls.length = 0; } else { n.subs = []; n.calls = []; }
  }
  for (i = 0; i < list.length && i < 1200; i++) {
    n = SCENE[list[i]];
    if (!n) continue;
    n.alpha = orbAlpha(n, tnow);
    if (!n.parent) continue;
    p = SCENE[n.parent];
    if (!p) { n.alpha = 0; continue; }
    motionOf(n);
    if (!p.parent) (n.kind === 'tool' ? ORB_OWN : ORB_JOBS).push(n);
    else (n.kind === 'tool' ? p.calls : p.subs).push(n);
  }
  selfTurn(tnow);
  if (SELF.alpha > 0.005) ORB_JOBS.push(SELF);
  if (!(dt > 0)) return;
  spread(ORB_JOBS, dt, 0.055 * k, still);
  spread(ORB_OWN, dt, 0.03 * k, still);
  for (i = 0; i < list.length; i++) {
    n = SCENE[list[i]];
    if (!n || !n.parent || n.kind === 'tool') continue;
    if (n.subs.length) spread(n.subs, dt, 0.05 * k, still);
    if (n.calls.length) spread(n.calls, dt, 0.03 * k, still);
  }
}

function prune() {
  var keep = Object.create(null), out = [], i, id, n;
  for (i = ORDER.length - 1; i >= 0; i--) {
    id = ORDER[i]; n = SCENE[id];
    if (!n) continue;
    if (n.alpha > 0.004 || keep[id]) {
      out.push(id);
      if (n.parent) keep[n.parent] = 1;
    } else {
      delete SCENE[id];
    }
  }
  out.reverse();
  ORDER = out;
}

/* Idle draws nothing but the core.

   It used to draw seven short stubs off the core, each with a dot at the end
   and some with a small twig, so the thing would look alive rather than
   switched off. They looked exactly like work - a spike, a tip, a branch - and
   were read as work: an idle page with no jobs was taken to be busy, and the
   lines could not be pointed at because no job was behind them. A line now
   always means something is being done. */

/* ---------- the canvas ---------- */

var orb = $('orb');
var octx = orb.getContext('2d');

/* ---------- what a piece of the shape is, when you point at it ----------
 *
 * The shape is meant to be understood the way you understand a room is busy
 * without counting the people in it, and it does that. What it cannot do is
 * answer "what IS that one" - and with several spikes standing there and an
 * empty task list, that is the first thing anybody asks.
 *
 * So every piece knows which node drew it, and pointing at it says so.
 */
var WHAT = {
  root: 'This machine',
  worker: 'A background job',
  subagent: 'A helper inside a job',
  tool: 'One thing being done',
  self: 'Rouh itself',
  disk: 'The storage ring'
};

function durationWords(seconds) {
  // A duration, never an age. "just now" here put "Took: just now" on the
  // card of a call that had taken a third of a second.
  if (seconds < 1) return 'under a second';
  if (seconds < 60) return Math.round(seconds) + 's';
  var m = Math.floor(seconds / 60);
  return m + 'm ' + Math.round(seconds - m * 60) + 's';
}

// Who runs a background job, in the words the tip and the card use.
var OWNER_WORDS = {
  assistant: 'your assistant',
  self: 'Rouh, on its own code',
  server: 'Rouh, on the server',
  one: 'the one program'
};

// Shortened for a glance; the card has the whole of it.
function clipWords(text, max) {
  text = String(text == null ? '' : text);
  return text.length > max ? text.slice(0, max - 1).replace(/\s+$/, '') + '…' : text;
}

function jobTitleOf(job) {
  var rec = (typeof taskRecs !== 'undefined' && taskRecs[job.id]) || {};
  return rec.title || job.label || job.id;
}

// A tool call's kind as the orb draws it: its mark, in its colour.
function kindMark(label, waiting, what) {
  var k = kindOf(label, what), pal = ORB_PAL;
  return '<span class="g" style="color:' + (waiting ? pal.wait : pal[k]) + '">' + ORB_KIND[k].mark + '</span>';
}

// How busy the machine is, in one line: the core's label, the corner
// circle's and the core's card all say it the same way.
function busyWords(ms) {
  if (ms.idle) return 'Idle - nothing is running';
  var parts = [];
  if (ms.self) parts.push('Rouh is working on an answer');
  if (ms.jobs || !ms.self) {
    parts.push(ms.jobs + ' job' + (ms.jobs === 1 ? '' : 's') + ', ' + ms.open + ' thing' +
      (ms.open === 1 ? '' : 's') + ' being done');
  }
  return parts.join('; ');
}

// What Rouh's own line is doing, in words.
function selfDoing() {
  for (var i = ORB_OWN.length - 1; i >= 0; i--) {
    var c = ORB_OWN[i];
    if (!c.fade) return (c.raw && c.raw.what) || DOES[c.label] || ('Using ' + c.label);
  }
  if (SELF.state === 'stopped') return 'Stopped by you part way through';
  if (SELF.fade) return 'Finished answering';
  return S.state === 'speaking' ? 'Saying its answer' : 'Working out its answer';
}

// One line of a card's list of tool calls: its mark, what it did, how long it took.
function stepLine(c) {
  var took = c.ms != null ? durationWords(c.ms / 1000) : (c.state === 'running' ? 'running' : '');
  if (c.state === 'failed' || c.state === 'lost') took = c.state + (took ? ', ' + took : '');
  var live = c.state === 'running' || c.state === 'waiting';
  return '<li' + (live ? '' : ' class="done"') + '>' + kindMark(c.tool, c.state === 'waiting', c.what) +
    '<span class="s"><span>' + escapeHtml(c.what || 'tool') + '</span>' +
    (c.helper ? '<span class="h">by its helper “' + escapeHtml(clipWords(c.helper, 60)) + '”</span>' : '') +
    '</span><span class="t">' + escapeHtml(took) + '</span></li>';
}

// What a line is, when it is pointed at: whose job it is, what it is doing
// now, and how long it has been going. Three lines and nothing else, on the
// user's instruction (14 September 2026); the card a click opens has the rest.
function orbTipShow(node, clientX, clientY) {
  var tip = $('orbTip');
  if (!tip) return;
  if (node.kind === 'disk') {
    var dw = diskWords(DISK.reading);
    if (!dw) { orbTipHide(); return; }
    tip.innerHTML = '<div class="l">' + escapeHtml(dw) + '</div>';
    tip.hidden = false;
    placeTip(tip, clientX, clientY);
    return;
  }
  if (node.kind === 'root') {
    tip.innerHTML = '<div class="l">' + escapeHtml(busyWords(machineSummary())) + '</div>';
    tip.hidden = false;
    placeTip(tip, clientX, clientY);
    return;
  }
  // Both are milliseconds on this machine's clock, set by clampTime. Reading
  // them as seconds turned ninety seconds of work into "1266m 40s".
  var open = (node.closed ? node.closed : now()) - node.opened;
  open = open / 1000;
  var raw = node.raw || {};
  var parent = node.parent ? SCENE[node.parent] : null;
  var job = node.kind === 'worker' ? node : jobOf(parent || node);
  var mine = node.kind === 'self' || (node.kind === 'tool' && (!parent || parent.kind === 'root'));
  var name = mine ? 'Rouh, answering you' : (job ? jobTitleOf(job) : (node.label || 'A job'));
  var over = { failed: 'failed', lost: 'lost' }[node.state] || 'done';
  var doing;
  if (node.kind === 'self') doing = escapeHtml(selfDoing());
  else if (node.kind === 'tool') {
    doing = kindMark(node.label, node.state === 'waiting', raw.what) + ' ' +
      escapeHtml(raw.what || DOES[node.label] || (node.label ? 'Using ' + node.label : 'A tool'));
  } else if (node.closed) {
    doing = { failed: 'Failed', lost: 'Stopped without saying how it ended' }[node.state] || 'Finished';
  } else doing = escapeHtml(raw.doing || raw.what || 'Working');
  // The job's task and step in the workspace, "30-02", before its name.
  var no = !mine && job && job.raw && job.raw.step ? String(job.raw.step) : '';
  var lines = '<div class="l">' + (no ? '<span class="no">' + escapeHtml(no) + '</span> ' : '') +
    escapeHtml(name) + '</div>';
  if (node.state === 'waiting' && !node.fade) {
    var rec = job && typeof taskRecs !== 'undefined' ? taskRecs[job.id] || {} : {};
    lines += '<div class="nw">NEEDS YOU' + (rec.asking ? ' - ' + escapeHtml(clipWords(rec.asking, 140)) : '') + '</div>';
  } else {
    lines += '<div class="n">' + doing + '</div>';
  }
  lines += '<div class="d">' + escapeHtml(durationWords(Math.max(0, open))) +
    (node.kind === 'tool' && node.closed ? ' · ' + over : '') + '</div>';
  tip.innerHTML = lines;
  tip.hidden = false;
  placeTip(tip, clientX, clientY);
}

// What of the screen can be seen: the part the browser shows. Nothing is cut
// off the top of the orb's layer any more, because nothing sits across the
// top of the page for it to be cut off under.
function tipScreen(tip) {
  var vv = window.visualViewport, layer = tip.parentNode;
  var s = vv ? { left: vv.offsetLeft, top: vv.offsetTop,
                 right: vv.offsetLeft + vv.width, bottom: vv.offsetTop + vv.height }
             : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
  var cut = /^inset\(\s*([\d.]+)px/.exec(window.getComputedStyle(layer).clipPath || '');
  if (cut) s.top = Math.max(s.top, layer.getBoundingClientRect().top + parseFloat(cut[1]));
  return s;
}

// How big the tip is with the whole width to itself. Placed absolutely, it
// gets only the width between its left edge and the screen's right edge, so
// measured where it last stood, near that edge it came out narrower and
// taller than it is where it goes.
function tipSize(tip) {
  tip.style.left = '0px';
  tip.style.top = '0px';
  return { w: tip.offsetWidth, h: tip.offsetHeight };
}

// Put the tip's top-left corner at (x, y) on the screen, moved back inside
// `area`, 8 px from its edges, where it would run out of it.
function tipPut(tip, x, y, size, area) {
  var p = tip.parentNode.getBoundingClientRect();
  x = Math.max(area.left + 8, Math.min(x, area.right - 8 - size.w));
  y = Math.max(area.top + 8, Math.min(y, area.bottom - 8 - size.h));
  tip.style.left = (x - p.left) + 'px';
  tip.style.top = (y - p.top) + 'px';
}

function placeTip(tip, clientX, clientY) {
  // Kept inside what can be seen of the box the orb is drawn in, which is
  // the whole screen when it is open. Placed against the whole screen
  // regardless, a tip ran past the box it belongs to. Along a direction the
  // tip does not fit in that area, the visible screen.
  var s = tipScreen(tip), b = $('orbBox').getBoundingClientRect(), size = tipSize(tip);
  var l = Math.max(s.left, b.left), r = Math.min(s.right, b.right);
  var t = Math.max(s.top, b.top), d = Math.min(s.bottom, b.bottom);
  var fitsX = r - l >= size.w + 16, fitsY = d - t >= size.h + 16;
  var area = { left: fitsX ? l : s.left, right: fitsX ? r : s.right,
               top: fitsY ? t : s.top, bottom: fitsY ? d : s.bottom };
  // Below the pointer and to its right; above it, or to its left, where it
  // would run out of the area that way.
  var x = clientX + 14, y = clientY + 14;
  if (x + size.w > area.right - 8) x = clientX - size.w - 14;
  if (y + size.h > area.bottom - 8) y = clientY - size.h - 14;
  tipPut(tip, x, y, size, area);
}

function orbTipHide() {
  var tip = $('orbTip');
  if (tip) tip.hidden = true;
}

function escapeHtml(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
// Pointing at the shape.
//
// Every line and twig drawn in the last frame is kept as a line on the
// screen with a reach round it, and the nearest to the pointer wins, so a
// line can be pointed at anywhere along it, not only at its tip. The reach
// is the design's: 14 px either side of a job's or a helper's line, 16 at
// its tip, 22 round a question waiting for the person, 9 either side of a
// twig and 12 at its tip, with twigs given a 3 px head start so a busy line
// does not swallow its own calls. Firing a ray at the geometry never worked:
// a line is a stroke a few pixels wide, and a sweep of the whole canvas once
// hit nothing at all.
var LIMB_RADIUS = 14, TIP_RADIUS = 16, WAIT_RADIUS = 22;
var TWIG_RADIUS = 9, TWIG_TIP_RADIUS = 12, TWIG_BIAS = 3;
var CORE_RADIUS = 34;           // the core can be asked from this far out, when nothing else is nearer
// Every line starts at the core, so right on the core every line is near.
// Within about the core's drawn size the core wins, and never further out
// than this; beyond it the lines do, and past them the core up to CORE_RADIUS.
var CORE_HOLD = 16;

// True when the pointer is over the shape, which is only ever the orb opened
// over the whole screen.
//
// The orb is never drawn inside the canvas, so there is no second place to
// look: in the corner it is a 96 px circle that is one button, and the canvas
// underneath takes every click of its own.
function overOpenCanvas(target) {
  if (!target || !target.closest) return false;
  if (ORBX.state !== 'open') return false;
  // The orb's own box is the open canvas - less the settings panel, which is
  // inside the box and is not a button, so without this every slider on it
  // showed the label of a line behind it and every click on one opened that
  // line's card.
  return !!target.closest('#orbBox') && !target.closest('button, #orbPanel');
}

function coreNode() {
  return SCENE.root || { id: 'root', kind: 'root', label: '', state: 'running', parent: null };
}

// How far the point (px, py) is from the line between a and b.
function segDist(px, py, ax, ay, bx, by) {
  var dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
  var t = len2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  var ex = ax + t * dx - px, ey = ay + t * dy - py;
  return Math.sqrt(ex * ex + ey * ey);
}

function nodeAt(clientX, clientY) {
  if (!orbW) return null;
  var r = orb.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  // Everything below is in the canvas's own units, which are the page's
  // pixels except for the few frames of a move.
  var k = orbW / r.width;
  var x = (clientX - r.left) * k, y = (clientY - r.top) * k;
  var c = ORB_HIT.core;
  var toCore = Math.sqrt((c.x - x) * (c.x - x) + (c.y - y) * (c.y - y));
  if (onDiskRing(x, y)) return DISK_NODE;
  if (toCore <= Math.max(6, Math.min(CORE_HOLD, c.r * 2.5))) return coreNode();
  var best = null, bestScore = Infinity;
  for (var i = 0; i < pickCount; i++) {
    var p = PICKS[i];
    var d = segDist(x, y, p.x0, p.y0, p.x1, p.y1);
    if (d >= p.r) continue;
    var score = p.twig ? d - TWIG_BIAS : d;
    if (score < bestScore) { bestScore = score; best = p.n; }
  }
  if (best) return best;
  // The core is the one thing always on screen, so it can be asked too - and
  // at idle it is how "is anything running?" gets an answer.
  return toCore < CORE_RADIUS ? coreNode() : null;
}

(function () {
  var host = $('orb');
  if (!host || !host.parentNode) return;
  // One place a pointer meets the shape: the orb opened over the whole
  // screen, where the orb's own box takes every event. In the corner the
  // circle is a single button and says what it is itself.
  var surface = $('orbBox');
  if (!surface) return;
  surface.addEventListener('pointermove', function (e) {
    if (e.target && e.target.closest && e.target.closest('#orbOpen')) return;   // it says what it is itself
    if (!overOpenCanvas(e.target)) { orbTipHide(); surface.style.cursor = ''; return; }
    var node = nodeAt(e.clientX, e.clientY);
    if (!node) { orbTipHide(); surface.style.cursor = ''; return; }
    surface.style.cursor = 'pointer';
    orbTipShow(node, e.clientX, e.clientY);
  });
  surface.addEventListener('pointerleave', function () {
    orbTipHide(); surface.style.cursor = '';
  });
  // A click - or a tap, which has no hover - opens the full card.
  surface.addEventListener('click', function (e) {
    if (!overOpenCanvas(e.target)) return;
    var node = nodeAt(e.clientX, e.clientY);
    if (!node) return;
    orbTipHide();
    openNodeCard(node);
  });
})();

/* ---------- the card that opens when a part of the shape is clicked ----- */

// What a tool does, in words. Covers both vocabularies that reach the shape:
// Claude Code's tools inside a background job, and Rouh's own.
var DOES = {
  WebSearch: 'Searching the web', web_search: 'Searching the web',
  WebFetch: 'Reading a web page', web_fetch: 'Reading a web page',
  read_rouh_link: 'Reading a page of Rouh’s own, inside Rouh',
  code_execution: 'Running code on Anthropic’s side',
  Bash: 'Running a shell command', BashOutput: 'Reading a shell command’s output',
  KillShell: 'Stopping a shell command', run_command: 'Running a read-only command',
  Edit: 'Editing a file', MultiEdit: 'Editing a file', Write: 'Writing a file',
  NotebookEdit: 'Editing a notebook', Read: 'Reading a file', Grep: 'Searching inside files',
  Glob: 'Finding files by name', LS: 'Listing a folder', TodoWrite: 'Updating its to-do list',
  Task: 'Starting a helper', Agent: 'Starting a helper',
  tool_search_tool_regex: 'Loading a tool it is about to use',
  tool_search_tool_bm25: 'Loading a tool it is about to use',
  find_tools: 'Loading a tool it is about to use',
  tool_search: 'Loading a tool it is about to use',
  show_on_screen: 'Putting something on the canvas',
  show_workspace_page: 'Putting a workspace page on the canvas', show_again: 'Bringing a card back',
  read_card: 'Reading past work',
  publish_task: 'Making a task public, or private again',
  check_task_sharing: 'Checking whether a task is public',
  revise_on_screen: 'Revising a card on the canvas',
  delegate_task: 'Starting a background job', check_tasks: 'Checking the job list',
  look_at_task: 'Reading a job’s screen', reply_to_task: 'Answering a job’s question',
  read_task_log: 'Reading a job’s log', stop_task: 'Stopping a job',
  tidy_tasks: 'Tidying finished jobs', what_is_running: 'Reading what is running',
  what_was_on_screen: 'Looking back through the canvas', set_panels: 'Opening or closing a column, or the orb',
  remember: 'Remembering a fact', forget: 'Forgetting a fact', list_memory: 'Reading its memory',
  server_health: 'Checking the server', improve_myself: 'Changing its own code',
  deploy_myself: 'Deploying its own code'
};

// Milliseconds in, "HH:MM:SS" out. Named apart from clockOf below, which takes
// seconds: two functions of one name in one scope means the later silently
// replaces the earlier, and a job's start time was multiplied by a thousand.
function clockOfMs(ms) {
  if (!(ms > 0)) return '';
  var d = new Date(ms);
  function two(v) { return (v < 10 ? '0' : '') + v; }
  return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
}

function durationOf(n) {
  var raw = n.raw || {};
  if (raw.ms != null && n.closed) return durationWords(raw.ms / 1000);
  var end = n.closed ? n.closed : now();
  return durationWords(Math.max(0, (end - n.opened) / 1000));
}

function stateWords(n) {
  if (n.state === 'waiting') return '<span class="w">Stopped, waiting for you</span>';
  if (n.state === 'failed') return 'Failed';
  if (n.state === 'lost') return 'Lost - it stopped without reporting how it ended';
  if (n.state === 'stopped') return 'Stopped by you part way through';
  if (n.closed || n.state === 'done') return 'Finished';
  return 'Running';
}

// Everything underneath a node, counted, and its most recent tool calls.
function below(raw) {
  var out = { helpers: 0, tools: 0, toolsOpen: 0, recent: [] };
  (function walk(list) {
    for (var i = 0; i < (list || []).length; i++) {
      var c = list[i];
      if (!c) continue;
      if (c.kind === 'subagent') out.helpers++;
      if (c.kind === 'tool') {
        out.tools++;
        if (c.state === 'running' || c.state === 'waiting') out.toolsOpen++;
        out.recent.push(c);
      }
      walk(c.children);
    }
  })(raw && raw.children);
  out.recent.sort(function (x, y) { return (y.opened_at || 0) - (x.opened_at || 0); });
  out.recent = out.recent.slice(0, 6);
  return out;
}

function machineSummary() {
  var jobs = 0, helpers = 0, open = 0, own = 0;
  for (var i = 0; i < ORDER.length; i++) {
    var n = SCENE[ORDER[i]];
    if (!n || !n.parent || n.closed || n.state === 'done') continue;
    if (n.kind === 'worker') jobs++;
    else if (n.kind === 'subagent') helpers++;
    else if (n.kind === 'tool') { open++; if (n.parent === 'root') own++; }
  }
  var self = SELF.alpha > 0.005 && !SELF.fade;
  return { jobs: jobs, helpers: helpers, open: open, own: own, self: self,
           idle: !jobs && !helpers && !open && !self };
}

function jobOf(n) {
  // Walk up to the background job this belongs to, if any.
  var cur = n, guard = 0;
  while (cur && cur.parent && guard++ < 20) {
    if (cur.kind === 'worker') return cur;
    cur = SCENE[cur.parent];
  }
  return null;
}

function fact(dt, dd) {
  return '<dt>' + escapeHtml(dt) + '</dt><dd>' + dd + '</dd>';
}

function openNodeCard(node) {
  var wrap = $('nodeCard');
  if (!wrap) return;
  var kind = node.kind || 'tool';
  var raw = node.raw || {};
  var title = '', facts = '', more = '';

  if (kind === 'disk') {
    var dr = DISK.reading;
    title = diskWords(dr) || 'Storage of this machine';
    if (dr && dr.total_bytes) {
      facts += fact('Used', escapeHtml(loadGb(dr.used_bytes) + ' GB (' + Math.round(dr.percent_used) + '%)'));
      facts += fact('Free', escapeHtml(loadGb(dr.free_bytes, true) + ' GB'));
      facts += fact('Size', escapeHtml(loadGb(dr.total_bytes, true) + ' GB'));
    }
    more = '<p class="node-card-note">The ring round the core is how full this machine\u2019s disk is, ' +
      'filled clockwise from the top. It is light grey while there is room, amber from 65% used ' +
      'and red above 80%. It is read once a minute.</p>';
  } else if (kind === 'root') {
    var m = machineSummary();
    title = m.idle ? 'Idle - nothing is running' : 'Working';
    facts += fact('Background jobs', String(m.jobs));
    facts += fact('Helpers inside them', String(m.helpers));
    facts += fact('Things being done now', String(m.open) +
      (m.own ? ' (' + m.own + ' by Rouh itself)' : ''));
    // The same memory reading the inner ring is drawn from, off the same
    // poll: the core is this machine, and what it is holding is part of what
    // it is doing.
    //
    // Whatever the last poll said, and nothing if none has answered yet: a
    // card opened in that first second says less rather than saying "--".
    var load = LOAD.last;
    var loadRam = load && load.memory;
    if (loadRam && loadRam.total_bytes) {
      facts += fact('Memory used',
        loadGb(loadRam.used_bytes) + ' / ' + loadGb(loadRam.total_bytes, true) +
        ' GB (' + Math.round(loadRam.percent_used) + '%)');
    }
    more = '<p class="node-card-note">This is the core. Every line coming out of it is a piece ' +
      'of work happening right now: a spike is a background job, a branch is a helper inside ' +
      'one, a short twig is one thing being done, and a line in the core’s own colour is ' +
      'Rouh itself working on an answer. ' +
      (m.idle ? 'Nothing is running, so there are no lines.' : 'Point at a line to see which.') +
      '</p>';
  } else if (kind === 'worker') {
    var rec = (typeof taskRecs !== 'undefined' && taskRecs[node.id]) || {};
    title = rec.title || node.label || 'A background job';
    if (raw.owner) {
      var by = OWNER_WORDS[raw.owner] || raw.owner;
      facts += fact('Run by', escapeHtml(by.charAt(0).toUpperCase() + by.slice(1)));
    }
    if (raw.doing && !node.closed) facts += fact('Doing now', escapeHtml(raw.doing));
    facts += fact('Status', stateWords(node));
    facts += fact(node.closed ? 'Took' : 'Running for', escapeHtml(durationOf(node)));
    if (node.opened) facts += fact('Started', escapeHtml(clockOfMs(node.opened)));
    if (rec.mode || raw.mode) facts += fact('Mode', escapeHtml(rec.mode || raw.mode));
    if (raw.effort) facts += fact('Effort', escapeHtml(raw.effort));
    facts += fact('Job id', '<code>' + escapeHtml(node.id) + '</code>');
    if (node.state === 'waiting') {
      // A job whose work will not go onto main carries its own question,
      // because there is no screen to read it off: land.sh wrote it down as
      // a record and the question travels with the thing that is waiting.
      var asked = raw.conflict ? (raw.detail || '') : (rec.asking || '');
      more += '<div class="node-card-wait">NEEDS YOU' +
        (asked ? '<br>' + escapeHtml(asked) : '') +
        (raw.conflict
          ? '<br><button type="button" class="node-card-open" data-conflict="' +
            escapeHtml(String(raw.conflict)) + '">Open the card and pick</button>'
          : '') + '</div>';
    }
  } else if (kind === 'subagent') {
    var job = jobOf(SCENE[node.parent] || node);
    var jrec = job && typeof taskRecs !== 'undefined' ? taskRecs[job.id] || {} : {};
    title = raw.what || node.label || 'A helper';
    if (raw.detail) facts += fact('Its task', escapeHtml(raw.detail));
    if (raw.doing && !node.closed) facts += fact('Doing now', escapeHtml(raw.doing));
    facts += fact('Status', stateWords(node));
    facts += fact(node.closed ? 'Took' : 'Running for', escapeHtml(durationOf(node)));
    if (job) facts += fact('Inside the job', escapeHtml(jrec.title || job.label || job.id));
    if (raw.what && node.label) facts += fact('Kind of helper', escapeHtml(node.label));
    if (raw.effort) facts += fact('Effort', escapeHtml(raw.effort));
  } else if (kind === 'self') {
    title = 'Answering you';
    facts += fact('Doing now', escapeHtml(selfDoing()));
    facts += fact('Status', node.fade ? 'Finished' : 'Running');
    facts += fact(node.fade ? 'Took' : 'Running for', escapeHtml(durationOf(node)));
    more = '<p class="node-card-note">This line is Rouh itself at work on an answer: working ' +
      'it out, using its own tools and saying it. Each twig along it is one of its own tool calls.</p>';
    var mine = ORB_OWN.slice(-6).reverse();
    if (mine.length) {
      more += '<div class="node-card-sub">Tool calls</div><ul class="node-card-list">';
      for (var j = 0; j < mine.length; j++) {
        var oc = mine[j], ocRaw = oc.raw || {};
        more += stepLine({ what: ocRaw.what || DOES[oc.label] || oc.label, tool: oc.label, ms: ocRaw.ms,
                           state: oc.fade && oc.state === 'running' ? 'done' : oc.state });
      }
      more += '</ul>';
    }
  } else {
    var owner = SCENE[node.parent];
    var belongs;
    if (!owner || owner.kind === 'root') belongs = 'Rouh itself, while answering you';
    else if (owner.kind === 'worker') {
      var orec = typeof taskRecs !== 'undefined' ? taskRecs[owner.id] || {} : {};
      belongs = 'The background job “' + (orec.title || owner.label || owner.id) + '”';
    } else {
      var oj = jobOf(owner);
      belongs = 'Its helper “' + ((owner.raw && owner.raw.what) || owner.label || 'unnamed') + '”' +
        (oj ? ', inside the job “' + jobTitleOf(oj) + '”' : '');
    }
    title = raw.what || DOES[node.label] || ('Using ' + (node.label || 'a tool'));
    if (raw.detail) facts += fact('What exactly', escapeHtml(raw.detail));
    facts += fact('Tool', '<code>' + escapeHtml(node.label || '?') + '</code>');
    facts += fact('Status', stateWords(node));
    facts += fact(node.closed ? 'Took' : 'Running for', escapeHtml(durationOf(node)));
    facts += fact('Done by', escapeHtml(belongs));
  }

  if (kind === 'worker' || kind === 'subagent') {
    var b = below(raw);
    facts += fact('Helpers inside', String(b.helpers));
    // Counted from what is in the tree now, which forgets a finished step
    // after two seconds, so it is the running steps that it can count.
    facts += fact('Steps running now', String(b.toolsOpen));
    // The server lists the last steps before it forgets finished ones; a tree
    // from a server that does not falls back to what is still in the tree.
    var steps = raw.recent || b.recent.map(function (s) {
      return { what: DOES[s.label] || s.label || 'tool', state: s.state, ms: s.ms, tool: s.label };
    });
    if (steps.length) {
      // Newest first, each with its kind's mark in its colour; finished ones faint.
      more += '<div class="node-card-sub">Tool calls</div><ul class="node-card-list">';
      for (var i = 0; i < steps.length; i++) more += stepLine(steps[i]);
      more += '</ul>';
    }
  }

  $('nodeCardKind').textContent = WHAT[kind] || kind;
  $('nodeCardTitle').textContent = title;
  $('nodeCardFacts').innerHTML = facts;
  $('nodeCardMore').innerHTML = more;
  NC.back = document.activeElement;
  wrap.hidden = false;
  $('nodeCardClose').focus();
}

var NC = { back: null };

function closeNodeCard() {
  var wrap = $('nodeCard');
  if (!wrap || wrap.hidden) return;
  wrap.hidden = true;
  if (NC.back && NC.back.focus) { try { NC.back.focus(); } catch (e) {} }
  NC.back = null;
}

(function () {
  var wrap = $('nodeCard');
  if (!wrap) return;
  $('nodeCardClose').addEventListener('click', closeNodeCard);
  wrap.addEventListener('click', function (e) {
    // The red node on the orb is a job whose work will not go onto main, and
    // pressing it is meant to end with the person picking one of four. So the
    // card behind the node opens the decision card itself rather than only
    // describing it: it closes, the canvas comes forward, and the conflict
    // card is brought into view with its first button under the hand.
    var open = e.target && e.target.closest && e.target.closest('.node-card-open');
    if (open) {
      e.preventDefault();
      closeNodeCard();
      orbExpand(false);
      showConflictCard(open.getAttribute('data-conflict'));
      return;
    }
    if (e.target && e.target.hasAttribute && e.target.hasAttribute('data-close')) closeNodeCard();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !wrap.hidden) { e.preventDefault(); closeNodeCard(); }
  });
})();

/* ---------- drawing a frame ----------

   Everything is placed in a space where 1.0 is as far as a job reaches,
   turned, and projected by hand: a point is divided by its distance from
   the camera, so near work is bigger, and far work is drawn fainter and
   thinner so the turning object reads as solid. Every stroke is collected
   with its distance first and painted far to near. */

var orbW = 0, orbH = 0, orbR = 1;
shared.orbSizedAt = -1e9;
var orbLast = 0, orbRaf = 0, orbYaw = 0, orbFrameNo = 0;
var orbStats = { frames: 0, segs: 0, marks: 0, nodes: 0, ms: 0 };
var ORIGIN = [0, 0, 0], ORIGIN_WP = [ORIGIN];
var ORB_JOBS = [], ORB_OWN = [];       // jobs out of the core, and Rouh's own calls
// Rouh's own turn - working out an answer, using its own tools, saying it -
// as a line of its own out of the core, in the core's colour, with its own
// tool calls as twigs along it. Without it, a search Rouh ran while
// talking was a twig 4 px long beside the core, and under a pixel in the
// corner circle, so the orb looked idle through every conversation. It is
// not in the tree: the page itself knows when Rouh is at work on an answer.
var SELF = { id: 'rouh-self', kind: 'self', parent: 'root', label: 'Answering you',
             state: 'running', opened: 0, closed: 0, fade: 0, alpha: 0, jit: 0.4242,
             dir: null, raw: {}, subs: [], calls: [] };
var PJ = { cx: 0, cy: 0, S: 1, cyw: 1, syw: 0, cpi: 1, spi: 0 };
var ITEMS = [], DRAW = [], itemN = 0, segN = 0, markN = 0;
var PICKS = [], pickN = 0, pickCount = 0;
var ORB_HIT = { core: { x: 0, y: 0, r: 0 }, disk: { x: 0, y: 0, r: 0 } };

/* ---------- the storage ring round the core ----------

   Petar, 9 November 2026: "a third ring on the outside, with light gray.
   That would be the storage of the machine. Should be red after 80% and
   yellow/amber after 65%". Outside the core's crossing rings and the ring
   breathing round them, flat to the screen so it reads as a gauge: a faint
   track all the way round and, from twelve o'clock clockwise, an arc as long
   a share of it as the disk is full. The same drawing in the corner circle
   and opened over the whole screen, because they are the same orb. The
   reading is the poll's (`disk` from /api/machine/load, which the server
   reads at most once a minute), so the frame only reads two numbers. */
var DISK = { reading: null, share: null };
var DISK_NODE = { id: 'disk', kind: 'disk', label: 'Storage', state: 'running', parent: null, raw: {} };
//: Past the breathing ring's widest (2.4 core radii) with air between.
var DISK_RING = 3.4;
var DISK_WARM = 65, DISK_HOT = 80;

function diskShade(pal, pct) {
  return pct > DISK_HOT ? pal.diskHot : pct >= DISK_WARM ? pal.diskWarm : pal.disk;
}

// "Storage of this machine: 47% used, 220 GB free of 454 GB", or '' with no reading.
function diskWords(d) {
  if (!d || !d.total_bytes) return '';
  return 'Storage of this machine: ' + Math.round(d.percent_used) + '% used, ' +
    loadGb(d.free_bytes, true) + ' GB free of ' + loadGb(d.total_bytes, true) + ' GB';
}

function diskTake(v) {
  var d = v && v.disk;
  DISK.reading = d && d.total_bytes ? d : null;
  DISK.share = DISK.reading ? clamp(Number(d.percent_used) || 0, 0, 100) : null;
}

// Whether a point, in the canvas's own units, is on the storage ring.
function onDiskRing(x, y) {
  var h = ORB_HIT.disk;
  if (DISK.share === null || !(h.r > 0)) return false;
  var d = Math.hypot(x - h.x, y - h.y);
  return Math.abs(d - h.r) <= Math.max(4, h.r * 0.3);
}

function drawDisk(g, pal, cmp, x, y, r) {
  ORB_HIT.disk.x = x; ORB_HIT.disk.y = y; ORB_HIT.disk.r = r;
  if (DISK.share === null) return;
  var top = -Math.PI / 2;
  g.lineCap = 'butt';
  g.lineWidth = cmp ? 0.9 : 1.2;
  g.strokeStyle = pal.dim;
  g.globalAlpha = 0.28;
  g.beginPath(); g.arc(x, y, r, 0, 6.2831853); g.stroke();
  if (DISK.share > 0) {
    g.strokeStyle = diskShade(pal, DISK.share);
    g.globalAlpha = 0.9;
    g.beginPath(); g.arc(x, y, r, top, top + 6.2831853 * DISK.share / 100); g.stroke();
  }
  g.lineCap = 'round';
}
var ORB_MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

function sizeOrb(ts) {
  // Four layout reads a second rather than thirty: nothing here moves when
  // the window is still, and a forced layout every frame is exactly the
  // kind of cost this must not add to a conversation. A move sets orbSizedAt
  // back, so the picture follows its box on every frame of one.
  if (ts - shared.orbSizedAt < 250) return;
  shared.orbSizedAt = ts;
  // The canvas's own box, not the box it sits in: beside the settings panel
  // the canvas is the part of the box the panel leaves, and the shape has to
  // be drawn in the middle of what can be seen rather than half under the
  // column. It is also the box the pointer is measured against in `nodeAt`,
  // so both now read the same rectangle.
  var host = orb.getBoundingClientRect();
  var w = Math.max(1, Math.round(host.width || 300));
  var h = Math.max(1, Math.round(host.height || 300));
  // Sharp on a high-density screen, up to twice its pixels, and never more
  // than about four million of them to clear and draw thirty times a second
  // behind a conversation.
  var ratio = Math.max(0.5, Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(4e6 / (w * h))));
  if (w === orbW && h === orbH && ratio === orbR) return;
  orbW = w; orbH = h; orbR = ratio;
  orb.width = Math.round(w * ratio);
  orb.height = Math.round(h * ratio);
}

function project(p, out) {
  var x = p[0] * PJ.cyw + p[2] * PJ.syw, z0 = -p[0] * PJ.syw + p[2] * PJ.cyw;
  var y = p[1] * PJ.cpi - z0 * PJ.spi, z = p[1] * PJ.spi + z0 * PJ.cpi;
  var d = 3.15 + z, f = 2.15 / Math.max(0.4, d);
  out.x = PJ.cx + x * PJ.S * f;
  out.y = PJ.cy + y * PJ.S * f;
  out.z = d;
  out.s = f;
  return out;
}

function addItem(z, type) {
  if (itemN >= MAX_ITEMS) return null;
  var it = ITEMS[itemN] || (ITEMS[itemN] = {});
  itemN++;
  it.z = z;
  it.t = type;
  DRAW.push(it);
  if (type === 'seg') segN++; else markN++;
  return it;
}

function addSeg(p0, p1, col, w, a, dash) {
  var it = addItem((p0.z + p1.z) / 2, 'seg');
  if (!it) return;
  it.x0 = p0.x; it.y0 = p0.y; it.z0 = p0.z; it.x1 = p1.x; it.y1 = p1.y;
  it.col = col; it.w = w; it.a = a; it.dash = !!dash;
}

function addPick(p0, p1, r, n, twig) {
  if (pickN >= 6000) return;
  var k = PICKS[pickN] || (PICKS[pickN] = {});
  pickN++;
  k.x0 = p0.x; k.y0 = p0.y; k.x1 = p1.x; k.y1 = p1.y; k.r = r; k.n = n; k.twig = twig;
}

function byOpened(a, b) { return a.opened - b.opened; }
function byFar(a, b) { return b.z - a.z; }

// How long a call ran, from 0 to 1, which is how long its twig is. The
// design sizes a twig by what the call cost; Rouh has no price for one
// call, and the time it took is the honest stand-in: a quick file read is a
// stub, a long search reaches out. Thirty seconds or more is the whole length.
function costOf(a, tnow) {
  var raw = a.raw || {};
  var secs = raw.ms != null && a.closed ? raw.ms / 1000
    : Math.max(0, ((a.closed || tnow) - a.opened) / 1000);
  return clamp(Math.log(1 + secs) / Math.log(31), 0, 1);
}

// One tool call: a twig off the line that made it, or off the core when it
// is Rouh's own.
function drawTwig(a, wp, pdir, depth, A, tnow, pal, cmp) {
  var aa = a.alpha * A;
  if (aa <= 0.005) return;
  var C = ORB_CFG;
  var on = !a.fade && a.state === 'running';
  var asks = !a.fade && a.state === 'waiting';
  var kind = kindOf(a.label, a.raw && a.raw.what);
  var col = asks ? pal.wait : pal[kind];
  // Finished work drops its colour towards the structural grey.
  var ink = on || asks ? col : hexMix(col, pal.dim, 0.72);
  var N = wp.length - 1;
  var base = wp[Math.max(0, Math.min(N, Math.round(N * a.along)))];
  var dir = a.ldir;
  if (pdir) vnorm(vmix(pdir, a.dir, C.twigSplay * 0.72, dir));
  else { dir[0] = a.dir[0]; dir[1] = a.dir[1]; dir[2] = a.dir[2]; }
  var age = Math.max(0, (tnow - a.opened) / 1000);
  var full = (cmp ? 0.1 : 0.145) * C.twigLen * (0.4 + 1.25 * costOf(a, tnow)) * (depth === 1 ? 1 : 0.8);
  var L = full * Math.min(1, age / 0.22);          // twigs snap out fast
  var e3 = a.wp[1] || (a.wp[1] = [0, 0, 0]);
  e3[0] = base[0] + dir[0] * L; e3[1] = base[1] + dir[1] * L; e3[2] = base[2] + dir[2] * L;
  var b = project(base, a.sp[0] || (a.sp[0] = {}));
  var e = project(e3, a.sp[1] || (a.sp[1] = {}));
  a.pn = 2;
  a.drawn = orbFrameNo;
  var wid = C.wAct * (on ? 1.25 : 0.85) * (cmp ? 0.7 : 1);
  addSeg(b, e, ink, wid, aa * (on ? 1 : 0.8), asks);
  if (!cmp) addPick(b, e, TWIG_RADIUS, a, true);
  addPick(e, e, cmp ? 8 : TWIG_TIP_RADIUS, a, true);
  var dl = Math.hypot(e.x - b.x, e.y - b.y) || 1, ux = (e.x - b.x) / dl, uy = (e.y - b.y) / dl;
  // The mark rides the twig and is sized off its stroke, never bigger than
  // the line it ends. Old ghosts lose it, or the orb turns into confetti.
  if (!cmp && (on || aa > 0.55)) {
    var g = addItem(e.z - 0.002, 'glyph');
    if (g) {
      g.x0 = e.x; g.y0 = e.y; g.ux = ux; g.uy = uy; g.on = on; g.col = ink; g.k = kind;
      g.r = Math.max(1.4, Math.min(3.4, (1 + wid * 0.7) * C.glyphScale * (on ? 1 : 0.8))) * Math.max(0.5, e.s * 0.55);
      g.a = aa * (on ? 0.95 : 0.5);
    }
  }
  // A bar across the end: the call ended and gave nothing back.
  if (a.fade && (a.state === 'failed' || a.state === 'lost')) {
    var c = addItem(e.z - 0.0025, 'cut');
    if (c) { c.x0 = e.x; c.y0 = e.y; c.ux = ux; c.uy = uy; c.col = col; c.a = aa * 0.9; c.cmp = cmp; }
  }
}

// A job, or a helper inside one: its line, its calls, its tip, and the
// helpers off it.
function drawLimb(n, base, depth, parentDir, t, tnow, pal, cmp) {
  var A = n.alpha;
  if (A <= 0.005) return;
  var C = ORB_CFG, s, f;
  var waiting = !n.fade && n.state === 'waiting';
  var age = Math.max(0, (tnow - n.opened) / 1000);
  // A job reaches half its length at once and the rest over its first ten
  // seconds; a helper is shorter. Both grow in over 0.7 s.
  var L = (depth === 1 ? 0.5 + 0.5 * Math.min(1, age / 10) : 0.42) * Math.min(1, age / 0.7) * C.limbLen;
  var dir = n.ldir;
  if (depth === 1) { dir[0] = n.dir[0]; dir[1] = n.dir[1]; dir[2] = n.dir[2]; }
  else vnorm(vmix(parentDir, n.dir, 0.62, dir));     // a helper fans forward, never back
  var N = depth === 1 ? 6 : 4;
  // The bow, square to the line; a line waiting for the person runs straight.
  var px = -dir[2], py = 0.35, pz = dir[0], pl = Math.sqrt(px * px + py * py + pz * pz) || 1;
  var bow = waiting ? 0 : C.bend * Math.sin(n.phase + (slowMo ? 0 : t * 0.25)) / pl;
  for (s = 0; s <= N; s++) {
    f = s / N;
    var w3 = n.wp[s] || (n.wp[s] = [0, 0, 0]);
    var off = bow * Math.sin(f * Math.PI);
    w3[0] = base[0] + dir[0] * L * f + px * off;
    w3[1] = base[1] + dir[1] * L * f + py * off;
    w3[2] = base[2] + dir[2] * L * f + pz * off;
    project(w3, n.sp[s] || (n.sp[s] = {}));
  }
  n.wp.length = N + 1;
  n.pn = N + 1;
  n.drawn = orbFrameNo;
  var sp = n.sp;
  var wBase = (depth === 1 ? C.wJob : C.wHelper) * (cmp ? 0.7 : 1);
  // Rouh's own line is in the core's colour: the core itself at work.
  var own = n.kind === 'self' ? pal.ink : (depth === 1 ? pal.job : pal.agent);
  var col = waiting ? pal.wait : own;
  var la = A * (depth === 1 ? 1 : 0.8);
  for (s = 0; s < N; s++) {
    addSeg(sp[s], sp[s + 1], col, wBase * (1 - C.taperAmt * (s / N)), la, waiting);
    addPick(sp[s], sp[s + 1], cmp ? 9 : LIMB_RADIUS, n, false);
  }
  var tip = sp[N];
  addPick(tip, tip, cmp ? 10 : TIP_RADIUS, n, false);

  var calls = n.calls;
  if (calls.length > MAX_TWIGS) calls.sort(byOpened);
  for (s = Math.max(0, calls.length - MAX_TWIGS); s < calls.length; s++) {
    drawTwig(calls[s], n.wp, dir, depth, A, tnow, pal, cmp);
  }

  if (waiting) {
    var wm = addItem(tip.z - 0.02, 'wait');
    if (wm) { wm.x0 = tip.x; wm.y0 = tip.y; wm.r = (cmp ? 3.4 : 6) * Math.max(0.5, tip.s * 0.5); wm.a = A; wm.cmp = cmp; }
    addPick(tip, tip, cmp ? 13 : WAIT_RADIUS, n, false);
  } else if (!n.fade && n.state === 'running') {
    var ring = addItem(tip.z - 0.003, 'ring');
    if (ring) {
      ring.x0 = tip.x; ring.y0 = tip.y; ring.col = own; ring.a = A * 0.9;
      ring.r = (cmp ? 1.7 : 2.7) * (1 + 0.3 * Math.sin(t * 3 + n.phase)) * Math.max(0.4, tip.s * 0.5);
    }
  } else if (n.state === 'stopped') {
    // A bar across the end: this line was stopped, not finished. The same
    // mark a tool call that gave nothing back gets, for the same reason.
    var before = sp[Math.max(0, N - 1)];
    var bx = tip.x - before.x, by = tip.y - before.y;
    var bl = Math.hypot(bx, by) || 1;
    var bar = addItem(tip.z - 0.0025, 'cut');
    if (bar) {
      bar.x0 = tip.x; bar.y0 = tip.y; bar.ux = bx / bl; bar.uy = by / bl;
      bar.col = own; bar.a = A * 0.9; bar.cmp = cmp;
    }
  }

  var at = n.wp[Math.min(N, Math.round(N * 0.55))];
  for (s = 0; s < n.subs.length; s++) drawLimb(n.subs[s], at, depth + 1, dir, t, tnow, pal, cmp);
}

// The mark at the tip of a twig, one shape per kind of call.
function paintGlyph(g, it) {
  var x = it.x0, y = it.y0, ux = it.ux, uy = it.uy, s = it.r, px = -uy, py = ux;
  g.globalAlpha = it.a;
  g.strokeStyle = it.col;
  g.fillStyle = it.col;
  g.lineWidth = it.on ? 1.15 : 0.85;
  g.beginPath();
  switch (ORB_KIND[it.k].glyph) {
    case 'chev':
      g.moveTo(x - ux * s + px * s, y - uy * s + py * s);
      g.lineTo(x + ux * s * 0.9, y + uy * s * 0.9);
      g.lineTo(x - ux * s - px * s, y - uy * s - py * s);
      g.stroke();
      break;
    case 'square':
      g.rect(x - s * 0.85, y - s * 0.85, s * 1.7, s * 1.7);
      g.stroke();
      break;
    case 'tri':
      g.moveTo(x + ux * s * 1.1, y + uy * s * 1.1);
      g.lineTo(x - ux * s * 0.6 + px * s * 0.85, y - uy * s * 0.6 + py * s * 0.85);
      g.lineTo(x - ux * s * 0.6 - px * s * 0.85, y - uy * s * 0.6 - py * s * 0.85);
      g.closePath();
      if (it.on) g.fill(); else g.stroke();
      break;
    case 'bars':
      g.moveTo(x + px * s * 0.9 - ux * s * 0.5, y + py * s * 0.9 - uy * s * 0.5);
      g.lineTo(x + px * s * 0.9 + ux * s * 0.5, y + py * s * 0.9 + uy * s * 0.5);
      g.moveTo(x - px * s * 0.9 - ux * s * 0.5, y - py * s * 0.9 - uy * s * 0.5);
      g.lineTo(x - px * s * 0.9 + ux * s * 0.5, y - py * s * 0.9 + uy * s * 0.5);
      g.stroke();
      break;
    case 'cross':
      g.moveTo(x - s, y - s); g.lineTo(x + s, y + s);
      g.moveTo(x + s, y - s); g.lineTo(x - s, y + s);
      g.stroke();
      break;
    default:
      g.arc(x, y, s * 0.72, 0, 6.2831853);
      if (it.on) g.fill(); else g.stroke();
  }
}

function paintItem(g, it, pal, under, t) {
  var s, r;
  switch (it.t) {
    case 'seg':
      var dz = clamp(1.5 / it.z0, 0.1, 1);
      var alpha = it.a * (0.25 + 0.75 * dz), lw = it.w * (0.55 + 0.55 * dz);
      // The underside first, in the colour of the panel behind it and set
      // down and to the right: a matte tube, never a glow, and a thin gap
      // wherever a nearer line crosses a farther one.
      g.globalAlpha = alpha * 0.45;
      g.strokeStyle = under;
      g.lineWidth = lw * 1.5;
      g.beginPath(); g.moveTo(it.x0 + 0.9, it.y0 + 1.1); g.lineTo(it.x1 + 0.9, it.y1 + 1.1); g.stroke();
      g.globalAlpha = alpha;
      g.strokeStyle = it.col;
      g.lineWidth = lw;
      if (it.dash) g.setLineDash([3 * Math.max(0.6, lw), 4 * Math.max(0.6, lw)]);
      g.beginPath(); g.moveTo(it.x0, it.y0); g.lineTo(it.x1, it.y1); g.stroke();
      if (it.dash) g.setLineDash([]);
      break;
    case 'glyph':
      paintGlyph(g, it);
      break;
    case 'cut':
      s = it.cmp ? 2.2 : 3.6;
      g.globalAlpha = it.a;
      g.strokeStyle = it.col;
      g.lineWidth = it.cmp ? 1.2 : 1.8;
      g.beginPath();
      g.moveTo(it.x0 - it.uy * s, it.y0 + it.ux * s);
      g.lineTo(it.x0 + it.uy * s, it.y0 - it.ux * s);
      g.stroke();
      break;
    case 'ring':
      g.globalAlpha = it.a;
      g.strokeStyle = it.col;
      g.lineWidth = 1.2;
      g.beginPath(); g.arc(it.x0, it.y0, it.r, 0, 6.2831853); g.stroke();
      break;
    case 'wait':
      // Four signs at once, so waiting survives greyscale, colour blindness
      // and the 96 px circle: a hard filled square, a square breathing
      // round it, a ring turning against the rotation, and the words.
      var pulse = 0.5 + 0.5 * Math.sin(t * 2.3), sz = it.r;
      g.globalAlpha = it.a;
      g.fillStyle = pal.wait;
      g.fillRect(it.x0 - sz, it.y0 - sz, sz * 2, sz * 2);
      g.strokeStyle = pal.wait;
      g.lineWidth = 1.2;
      g.globalAlpha = it.a * (0.18 + 0.45 * (1 - pulse));
      r = sz * (2 + pulse * 1.4);
      g.beginPath(); g.rect(it.x0 - r, it.y0 - r, r * 2, r * 2); g.stroke();
      g.globalAlpha = it.a * 0.75;
      g.lineWidth = 1.1;
      g.beginPath();
      g.ellipse(it.x0, it.y0, sz * 3, Math.max(1, sz * 3 * Math.abs(Math.cos(t * 1.05))), 0, 0, 6.2831853);
      g.stroke();
      if (!it.cmp) {
        g.globalAlpha = it.a;
        g.font = '600 10px ' + ORB_MONO;
        g.fillText('NEEDS YOU', it.x0 + sz + 7, it.y0 + 3.5);
      }
      break;
  }
}

// The core: three thin crossing rings turning slowly, and one ring round
// them breathing, red while anything waits for the person.
function drawCore(g, pal, t, cmp, live, waiting) {
  var r = (cmp ? 7 : 15) * (2.15 / 3.15) * 0.5, x = PJ.cx, y = PJ.cy, k;
  g.strokeStyle = pal.ink;
  g.globalAlpha = 0.5;
  g.lineWidth = 1;
  for (k = 0; k < 3; k++) {
    g.beginPath();
    g.ellipse(x, y, r, r * Math.abs(Math.cos(t * 0.2 + k * 1.05)) + 0.6, k * 1.05, 0, 6.2831853);
    g.stroke();
  }
  var br = 0.5 + 0.5 * Math.sin(t * 1.5);
  g.globalAlpha = 0.10 + 0.14 * br * (live ? 1 : 0.4);
  g.strokeStyle = waiting ? pal.wait : pal.ink;
  g.beginPath(); g.arc(x, y, r * (1.5 + br * 0.9), 0, 6.2831853); g.stroke();
  drawDisk(g, pal, cmp, x, y, r * DISK_RING);
  g.globalAlpha = 1;
  ORB_HIT.core.x = x; ORB_HIT.core.y = y; ORB_HIT.core.r = r;
}

function renderOrb(t, dt) {
  var pal = ORB_PAL;
  var w = orbW, h = orbH, g = octx, i, j;
  // The small circle draws the same thing with less: thinner lines, shorter
  // twigs, no marks at the tips and no words.
  // So does the row at the foot of a phone's navigation, which is wide but
  // only a slit of it is seen.
  var cmp = w < 170 || ORBX.state === 'menu';
  var tnow = now();
  orbFrameNo++;
  orbScene(tnow, dt, slowMo);
  if (!slowMo) orbYaw += dt * ORB_CFG.spin;
  var pitch = -0.28;
  PJ.cx = w / 2 + orbSlitShift(w, h); PJ.cy = h / 2;
  PJ.S = (ORBX.anim ? ORBX.fit : orbFit(ORBX.state, w, h)) * 0.46 * ORB_CFG.zoom;
  PJ.cyw = Math.cos(orbYaw); PJ.syw = Math.sin(orbYaw);
  PJ.cpi = Math.cos(pitch); PJ.spi = Math.sin(pitch);
  itemN = 0; segN = 0; markN = 0; pickN = 0;
  DRAW.length = 0;
  var live = 0, waiting = 0;
  for (i = 0; i < ORB_JOBS.length; i++) {
    j = ORB_JOBS[i];
    if (!j.fade && j.state === 'running') live++;
    if (!j.fade && j.state === 'waiting') waiting++;
    drawLimb(j, ORIGIN, 1, null, t, tnow, pal, cmp);
  }
  for (i = 0; i < ORB_OWN.length; i++) {
    if (!ORB_OWN[i].fade && ORB_OWN[i].state === 'waiting') waiting++;
    // Along Rouh's own line while that is drawn; straight off the core only
    // if a call of its own outlives the line's ghost.
    if (SELF.alpha <= 0.005) drawTwig(ORB_OWN[i], ORIGIN_WP, null, 1, 1, tnow, pal, cmp);
  }
  DRAW.sort(byFar);
  g.setTransform(orbR, 0, 0, orbR, 0, 0);
  g.clearRect(0, 0, w, h);
  g.lineCap = 'round';
  g.lineJoin = 'round';
  var under = 'rgb(' + panelRgb.join(',') + ')';
  for (i = 0; i < DRAW.length; i++) paintItem(g, DRAW[i], pal, under, t);
  drawCore(g, pal, t, cmp, live, waiting);
  pickCount = pickN;
  orbRowSay(live, waiting);
}

/* What the row at the foot of a phone's navigation is called to a screen
   reader, out of the same count the core is drawn from: the jobs running, or
   that somebody is waiting for the person, which outranks any number. Only
   its name: nothing is written on the row, since Petar had the words there
   taken away on 11 October 2026 (fr_cbe86497eed2, "I don't need it"), and
   the dot says it alone. Written only when it changes, which is not thirty
   times a second. */
function orbRowSay(live, waiting) {
  var say = waiting ? 'needs you' : live ? live + ' running' : 'nothing running';
  if (say === ORBX.now) return;
  ORBX.now = say;
  var row = $('orbRow');
  if (row) row.setAttribute('aria-label', 'Open the orb, ' + say);
}

/* Through the row, the core sits in the middle of the room the cross leaves
   it, between the cross and the row's right hand end, rather than in the
   middle of the whole row with the cross in it. Petar, 11 October 2026,
   once the words beside it had gone: "center the dot a bit better.
   Slightly to the right". The cross ends the row's height less 6 pixels in
   from its left (`.orb-menu-close`), so the core moves half that. It comes
   in from nothing as the circle stretches into the row and goes again as
   it shrinks back, so a circle is never drawn off its own middle, and
   anywhere but the row it is nothing. */
function orbSlitShift(w, h) {
  var slit = ORBX.state === 'menu' || (ORBX.anim && ORBX.anim.menu);
  return slit ? Math.max(0, Math.min((h - 6) / 2, (w - h) / 2)) : 0;
}

// A point on a piece's drawn line where a real pointer gets that piece and
// nothing else, tried from the middle of the line outwards: well inside the
// box, where the line moves least as the object turns, and clear of a twig,
// a helper or a question sitting on part of it. For the checks, which point with a real
// mouse the way a person does. `k` is page pixels to one canvas unit.
function orbPointAt(n, r, k) {
  var pts = n.sp, m = n.pn || 0, i, lens = [], total = 0;
  if (m < 2) return null;
  for (i = 1; i < m; i++) {
    var l = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    lens.push(l);
    total += l;
  }
  var tries = [0.55, 0.45, 0.65, 0.35, 0.75, 0.25, 0.85, 0.15, 0.94, 0.08];
  for (var step = 0; step < tries.length; step++) {
    var want = total * tries[step], at = 0;
    for (i = 0; i < lens.length; i++) {
      if (at + lens[i] < want && i < lens.length - 1) { at += lens[i]; continue; }
      var f = lens[i] > 0 ? clamp((want - at) / lens[i], 0, 1) : 0;
      var cx = r.left + (pts[i].x + (pts[i + 1].x - pts[i].x) * f) * k;
      var cy = r.top + (pts[i].y + (pts[i + 1].y - pts[i].y) * f) * k;
      // Only where it can be seen: the box cuts off whatever reaches past it.
      var seen = cx > r.left + 24 && cx < r.right - 24 && cy > r.top + 24 && cy < r.bottom - 24;
      if (seen && nodeAt(cx, cy) === n) return { x: cx, y: cy };
      break;
    }
  }
  return null;
}

function drawOrb(ts) {
  orbRaf = 0;
  if (document.hidden) return;              // visibilitychange starts it again
  // Every frame while the orb is moving, so its picture keeps up with its box.
  if (ORBX.anim) orbMove(ts);
  else {
    // What it sits over has moved or changed size: follow it on this frame,
    // not at the next one drawn.
    if (ORBX.dirty) { ORBX.dirty = false; orbApply(); }
    if (ts - orbLast < ORB_FRAME_MS - 1) { orbRaf = requestAnimationFrame(drawOrb); return; }
  }
  // A longer step is taken as this long, so a tab coming back from the
  // background does not throw every line round the sphere at once.
  var dt = orbLast ? Math.min((ts - orbLast) / 1000, 0.08) : 0.033;
  orbLast = ts;
  var t0 = performance.now();
  sizeOrb(ts);
  renderOrb(ts / 1000, dt);
  if (ts - pruneAt > 1000) { pruneAt = ts; prune(); }
  orbStats.frames++;
  orbStats.segs = segN;
  orbStats.marks = markN;
  orbStats.nodes = ORDER.length;
  orbStats.ms = orbStats.ms * 0.9 + (performance.now() - t0) * 0.1;
  orbRaf = requestAnimationFrame(drawOrb);
}

function startOrb() {
  if (!orbRaf && !document.hidden) { orbLast = 0; orbRaf = requestAnimationFrame(drawOrb); }
}
function stopOrb() {
  if (orbRaf) { cancelAnimationFrame(orbRaf); orbRaf = 0; }
}

/* ---------- how busy the machine is ----------
 *
 * One poll for the whole page. /api/machine/load answers with the CPU as a
 * percentage of everything this box could be doing, how many processes are
 * running, and how much memory is in use; the ring round the circle in the
 * corner and the readout under the orb opened over the whole screen are two
 * drawings of the same answer, and a second timer for the second of them
 * would ask the server the same question twice a second apart.
 *
 * So: whoever wants the numbers asks to be told them, the timer runs while
 * somebody is listening and the tab is being looked at, and it stops the
 * moment nobody is.
 */
var LOAD = { fns: [], timer: null, last: null, asking: false };

//: Often enough that a machine getting busy shows within a breath, rarely
//: enough that a page left open all day is not a load of its own.
var LOAD_EVERY = 3000;

/* The one place the thresholds live: green while there is room, orange from
   half, red once it is really working. The class goes on the row and the
   stylesheet gives each one the page's own colour, chosen to read on its
   background. */
function loadClass(pct) {
  if (typeof pct !== 'number' || !isFinite(pct)) return '';
  if (pct > 70) return 'load-hot';
  if (pct >= 50) return 'load-warm';
  return 'load-ok';
}

/* The other scale: the one the machine's memory is drawn on, the ring
   round the circle and the number in the readout both.

   Not the CPU's colours, and not a blend from end to end either. It was that
   blend at first, and it was wrong: mixing from baby blue to purple across
   the whole of the bottom half drew a box sitting at a third of its memory -
   a healthy box, with room to spare - in half purple, so the corner was
   warning about something that was not happening.

   Memory reads in bands, and these are the bands:

     0 to 50     baby blue. There is room.
     50 to 75    purple. It is filling.
     75 and up   red.

   Each band is its own colour flat across the whole of it, so 35% is the
   same baby blue as 5% and says the same thing about the box. What is
   blended is the threshold itself, and only the few per cent either side of
   it, so a ring creeping past half changes colour rather than jumping. At 50
   it is halfway from the first colour to the second, which is what a
   threshold looks like when it is crossed rather than stepped over, and by
   53 it is purple with nothing of the blue left in it.

   The three stops are the stylesheet's (--mem-cool, --mem-mid, --mem-hot),
   written there as plain six-digit hex so this can take them apart without
   handing the browser a colour to parse. A stop that is missing or is
   written some other way gives no colour at all, which leaves the arc
   undrawn rather than drawn in whatever a browser falls back to. */
var MEM_STOPS = ['--mem-cool', '--mem-mid', '--mem-hot'];

//: Where baby blue gives way to purple, and purple to red.
var MEM_WARM = 50, MEM_HOT = 75;

//: How far either side of a threshold the two colours are mixed. Three per
//: cent: wide enough that the change reads as a change rather than a jump,
//: narrow enough that 35% is baby blue and 60% is purple with none of the
//: other colour in either of them.
var MEM_BLEND = 3;

function cssHex(name) {
  var raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
  var m = /^#([0-9a-fA-F]{6})$/.exec(raw);
  if (!m) return null;
  var n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function memColour(pct) {
  if (typeof pct !== 'number' || !isFinite(pct)) return '';
  var stops = [], i;
  for (i = 0; i < MEM_STOPS.length; i++) {
    var stop = cssHex(MEM_STOPS[i]);
    if (!stop) return '';
    stops.push(stop);
  }
  var p = clamp(pct, 0, 100);
  // Inside a band it is that band's colour and nothing else; across a
  // threshold, and only within MEM_BLEND of one, it is the two either side
  // of it in proportion.
  var lo = stops[0], hi = stops[0], t = 0;
  if (p >= MEM_HOT + MEM_BLEND) {
    lo = hi = stops[2];
  } else if (p > MEM_HOT - MEM_BLEND) {
    lo = stops[1]; hi = stops[2];
    t = (p - (MEM_HOT - MEM_BLEND)) / (2 * MEM_BLEND);
  } else if (p >= MEM_WARM + MEM_BLEND) {
    lo = hi = stops[1];
  } else if (p > MEM_WARM - MEM_BLEND) {
    lo = stops[0]; hi = stops[1];
    t = (p - (MEM_WARM - MEM_BLEND)) / (2 * MEM_BLEND);
  }
  var out = [];
  for (i = 0; i < 3; i++) out.push(Math.round(lo[i] + (hi[i] - lo[i]) * t));
  return 'rgb(' + out.join(', ') + ')';
}

function loadTell(v) {
  for (var i = 0; i < LOAD.fns.length; i++) {
    try { LOAD.fns[i](v); } catch (e) {}
  }
}

function loadAsk() {
  // One request at a time. A server that takes longer to answer than the
  // interval should not be given a queue of questions about it.
  if (LOAD.asking || document.hidden || !LOAD.fns.length) return;
  LOAD.asking = true;
  fetch('/api/machine/load', { credentials: 'same-origin', headers: { 'X-Rouh-Later': '1' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (v) {
      LOAD.asking = false;
      if (!v || !LOAD.fns.length) return;
      LOAD.last = v;
      loadTell(v);
    })
    .catch(function () { LOAD.asking = false; });   // the next tick asks again
}

function loadTimer() {
  var want = LOAD.fns.length > 0 && !document.hidden;
  if (want === !!LOAD.timer) return;
  if (want) {
    LOAD.timer = setInterval(loadAsk, LOAD_EVERY);
    loadAsk();                        // rather than three seconds of nothing
  } else {
    clearInterval(LOAD.timer);
    LOAD.timer = null;
  }
}

// Ask to be told, and be told the last answer at once if there is one: a
// readout opened between two ticks shows numbers rather than dashes.
function loadWatch(fn) {
  if (LOAD.fns.indexOf(fn) < 0) LOAD.fns.push(fn);
  if (LOAD.last) { try { fn(LOAD.last); } catch (e) {} }
  loadTimer();
}

function loadUnwatch(fn) {
  var i = LOAD.fns.indexOf(fn);
  if (i >= 0) LOAD.fns.splice(i, 1);
  loadTimer();
}

document.addEventListener('visibilitychange', loadTimer);
// The orb is on the screen in every state, so its storage ring always wants the reading.
loadWatch(diskTake);
window.addEventListener('pagehide', function () { LOAD.fns.length = 0; loadTimer(); });

/* The readout itself: three numbers in the bottom-right corner of the orb
   opened over the whole screen. Only there - at 96 px there is no room for
   it - and it never takes a pointer event, so the shape behind it is still
   clickable everywhere. */
// Thousands grouped, because a token count is read at a glance and
// "1247382" is not.
function num(n) {
  return (typeof n === 'number' && isFinite(n))
    ? n.toLocaleString('en-US') : String(n == null ? 0 : n);
}

function loadGb(bytes, whole) {
  var gb = bytes / (1024 * 1024 * 1024);
  // "1.4 / 30 GB": the total is a round number of gigabytes once there are
  // enough of them for a tenth to be noise.
  return (whole && gb >= 10) ? String(Math.round(gb)) : gb.toFixed(1);
}

// What leftover working files are holding is a few hundred megabytes on a
// quiet day and several gigabytes after a busy one, and "0.2 GB" is not an
// answer to the first of those. So: megabytes until there
// is a gigabyte of it, gigabytes after that.
function loadSize(bytes) {
  var mb = bytes / (1024 * 1024);
  return mb < 1024 ? Math.round(mb) + ' MB' : (mb / 1024).toFixed(1) + ' GB';
}

function orbStatsPaint(v) {
  var row = $('orbStatCpuRow'), cpu = $('orbStatCpu');
  var proc = $('orbStatProc'), ram = $('orbStatRam');
  if (!row || !cpu || !proc || !ram) return;
  var pct = (v && typeof v.cpu_percent === 'number') ? v.cpu_percent : null;
  cpu.textContent = pct === null ? '--' : Math.round(pct) + '%';
  row.className = 'orb-stat' + (pct === null ? '' : ' ' + loadClass(pct));
  proc.textContent = (v && typeof v.processes === 'number') ? String(v.processes) : '--';
  // What it has spent today, beside how hard it is working. Same poll, same
  // readout: the two are the same question asked twice.
  var spendEl = $('orbStatSpend'), spendRow = $('orbStatSpendRow');
  if (spendEl && spendRow) {
    var sp = v && v.spend;
    var on = !!(sp && sp.today && sp.today.turns);
    spendRow.hidden = !on;
    if (on) {
      spendEl.textContent = sp.said.today + ' \u00b7 ' +
        sp.today.turns + (sp.today.turns === 1 ? ' turn' : ' turns') + ' \u00b7 ' +
        sp.said.cached + '% cached';
    }
  }
  // The memory line, in the colour of its ring in the corner: the number and
  // the arc are one reading and must never be two answers.
  var m = v && v.memory;
  ram.textContent = (m && m.total_bytes)
    ? loadGb(m.used_bytes) + ' / ' + loadGb(m.total_bytes, true) + ' GB ('
      + Math.round(m.percent_used) + '%)'
    : '--';
  ram.style.color = (m && m.total_bytes) ? memColour(m.percent_used) : '';

  // Memory held by working files nothing is using any more. On this server
  // /tmp is a filesystem that lives in memory, so a world left there by a
  // run that proved a change is memory still held after the run is over. The
  // one program's reaper sweeps it; this is the same figure it acts on, so
  // that the leak is visible on the screen before anybody feels it. The row
  // stays hidden while there is nothing loose, which makes it appearing the
  // whole of the news.
  var loose = v && v.leftovers, looseRow = $('orbStatLooseRow'), looseEl = $('orbStatLoose');
  if (looseRow && looseEl) {
    var anyLoose = !!(loose && loose.loose_bytes > 0);
    looseRow.hidden = !anyLoose;
    if (anyLoose) {
      looseEl.textContent = loadSize(loose.loose_bytes) + ' in ' + loose.loose
        + (loose.loose === 1 ? ' folder' : ' folders');
      looseEl.style.color = memColour(loose.percent_used);
    }
  }
}

function orbStatsShow(on) {
  var box = $('orbStats');
  if (!box) return;
  if (on === !box.hidden) return;
  box.hidden = !on;
  if (on) loadWatch(orbStatsPaint);
  else loadUnwatch(orbStatsPaint);
}

/* The other drawing of the same answer: the two rings round the 96 px
   circle in the corner. Each is an arc from twelve o'clock, clockwise, as
   long a share of the circle as its own reading is of this machine - 12% is
   43 degrees of it, half is half of it - and they are nested, outside in:
   the CPU on the rim in the same three colours as the readout, then how full
   the machine's memory is, thinner and on its own banded scale. There was a
   third, inside that, for what Rouh and the one program held between them;
   Petar had it taken away on 11 October 2026 (fr_73b8a5917def), and the
   machine's total is the only memory the orb tracks.

   Each arc is drawn as geometry, the piece of its circle its reading stands
   for (ringArcPath), so the number on the ring is the number the endpoint
   said, in any browser and at any size the corner is given.

   The colour goes on the arc itself, as a class the stylesheet colours. An
   arc with no reading behind it - the poll has not answered yet, or this
   machine cannot be read - is given no class and no path, so it is not
   drawn at all, rather than drawn all the way round in whatever the browser
   would otherwise stroke it with. */
// The share of a reading, 0 to 100, or null when there is nothing to draw.
// A tenth of a per cent is a third of a degree; anything finer is noise
// written into the markup on every tick.
function loadShare(pct) {
  return (typeof pct === 'number' && isFinite(pct))
    ? Math.round(clamp(pct, 0, 100) * 10) / 10 : null;
}

/* The arc for a share of a ring, as a path: from twelve o'clock, clockwise,
   round a circle of radius r about the middle of the ring's 100-unit box.

   It was a dashed circle once - the whole circle, pathLength="100", and a
   dash of "78 100" for 78% - and that is exact everywhere but here. The
   rings keep their stroke two real pixels wide with non-scaling-stroke, and
   Chromium and WebKit both then lay the dash out in screen pixels after
   having scaled it to the circle's length in the box's own units. So a ring
   drawn smaller than 100 px across drew every dash too long, by 100 over its
   size: a quarter too long on the 80 px circle a phone gets, which put the
   memory ring nearly all the way round, and red, on a phone whose open orb
   said 78% (fr_b69466fa2890, 24 September 2026), and a twenty-fifth too long
   on the 96 px one. A path has no dash to scale: its end is where the
   reading says, whatever the browser does with the stroke's width. */
function ringArcPath(r, share) {
  if (!(share > 0)) return '';
  var top = 'M 50 ' + (50 - r);
  // A path that ends where it began is no arc at all, so a whole ring is
  // two halves of one.
  if (share >= 100) {
    return top + ' A ' + r + ' ' + r + ' 0 1 1 50 ' + (50 + r) +
      ' A ' + r + ' ' + r + ' 0 1 1 50 ' + (50 - r);
  }
  var a = share / 50 * Math.PI;
  return top + ' A ' + r + ' ' + r + ' 0 ' + (share > 50 ? 1 : 0) + ' 1 ' +
    (50 + r * Math.sin(a)).toFixed(2) + ' ' + (50 - r * Math.cos(a)).toFixed(2);
}

//: How long a ring takes to move from one reading to the next, eased out: a
//: ring that sweeps to its new place reads as the machine changing, one that
//: jumps reads as the page redrawing.
var RING_SWEEP_MS = 240;

// Where each ring is drawn now, by the ring's id, and the frame moving it.
var RING_AT = {};

// How long an arc is, on either ring, in per cent of its own
// circle. The radius is the markup's, off data-r.
function ringArcLength(el, share) {
  if (!el) return;
  var r = parseFloat(el.getAttribute('data-r'));
  var at = RING_AT[el.id] || (RING_AT[el.id] = { share: 0, raf: 0 });
  var from = at.share, to = share === null ? 0 : share;
  if (at.raf) { cancelAnimationFrame(at.raf); at.raf = 0; }
  function draw(s) { at.share = s; el.setAttribute('d', ringArcPath(r, s)); }
  // A reading that went away goes at once, and nobody is shown a sweep who
  // asked for less motion or is not looking.
  if (share === null || from === to || slowMo || document.hidden) { draw(to); return; }
  var t0 = performance.now();
  function step(now) {
    var k = clamp((now - t0) / RING_SWEEP_MS, 0, 1);
    draw(from + (to - from) * (1 - Math.pow(1 - k, 3)));
    at.raf = k < 1 ? requestAnimationFrame(step) : 0;
  }
  at.raf = requestAnimationFrame(step);
}

function orbRingPaint(v) {
  var arc = $('orbRingArc');
  if (!arc) return;
  var cpu = loadShare(v && v.cpu_percent);
  ringArcLength(arc, cpu);
  arc.setAttribute('class', 'orb-ring-arc' + (cpu === null ? '' : ' ' + loadClass(cpu)));

  // The machine's memory, inside it, and the only memory the orb tracks.
  // Same start, same direction, as long a share of its own circle as its
  // reading; what differs is the radius, the thinner stroke and the scale
  // the colour comes off. The colour goes on the element itself, because it
  // is blended rather than chosen, and an empty one puts the ring back to
  // the stylesheet's `stroke: none` so a reading that did not arrive is not
  // drawn at all. Coloured from the reading itself, so the arc and the
  // number beside it in the open orb are never two different answers.
  var ram = $('orbRingRam');
  if (!ram) return;
  var mem = v && v.memory;
  var share = loadShare(mem && mem.percent_used);
  ringArcLength(ram, share);
  ram.style.stroke = share === null ? '' : memColour(share);
}

function orbRingShow(on) {
  var ring = $('orbRing');
  if (!ring) return;
  if (on === ORBX.ring) return;
  ORBX.ring = on;
  if (on) loadWatch(orbRingPaint);
  else { loadUnwatch(orbRingPaint); orbRingPaint(null); }
}

/* A red plug at the top right of the orb while this machine is running on
   its UPS battery: NUT's status has OB in it (`power_section` in
   rouh/machine_load.py, on the same poll as the rings). It goes the moment
   the status does. No reading - no NUT, no UPS - is no plug.

   Two of them, one function: the circle's is fixed to the window just off
   the circle's upper right, the way the notification dot is (`orbDotPlace`
   in app/notices.js), because the circle's own box clips to a circle; the
   open orb's sits in the row of its controls. Pointed at, or tapped, either
   says what it means in one line. */
var PLUG = { power: null, watching: false, held: false, hover: null, timer: 0 };

function plugWords(p) {
  if (p.low) return 'On battery power, low: ' + (p.host || 'this machine') + ' will shut down soon';
  return 'On battery power' + (typeof p.charge === 'number' ? ', ' + p.charge + '%' : '');
}

function plugPaint(v) {
  var p = v && v.power;
  PLUG.power = (p && p.on_battery) ? p : null;
  var words = PLUG.power ? plugWords(PLUG.power) : '';
  ['orbPlug', 'orbPlugOpen'].forEach(function (id) {
    var b = $(id);
    if (!b) return;
    b.setAttribute('aria-label', words || 'On battery power');
    b.classList.toggle('low', !!(PLUG.power && PLUG.power.low));
  });
  var says = $('orbPlugSays');
  if (says && !says.hidden) {
    if (words) says.textContent = words; else plugSay(null);
  }
  plugPlace();
}

function plugPlace() {
  var on = !!PLUG.power && PLUG.watching;
  var layer = $('orbLayer'), state = layer ? layer.getAttribute('data-orb') : '';
  var box = $('orbBox'), corner = $('orbPlug'), open = $('orbPlugOpen');
  if (open) open.hidden = !(on && state === 'open');
  if (!corner || !box) return;
  var r = box.getBoundingClientRect();
  var shown = on && state === 'corner' && r.width > 0 && !box.classList.contains('moving');
  corner.hidden = !shown;
  if (!shown) { if ($('orbPlugSays') && PLUG.held === corner) plugSay(null); return; }
  // Just off the circle's upper right, half over its rim. The notification
  // dot has that spot on a phone when it is lit, so the plug steps left of it.
  var dot = document.querySelector('.nt-orb-dot:not([hidden])');
  corner.style.left = Math.round(r.right - (dot ? 28 : 14)) + 'px';
  corner.style.top = Math.round(r.top - 3) + 'px';
}

// The one line, under the plug it belongs to, kept on the screen; null
// takes it away.
function plugSay(btn) {
  var says = $('orbPlugSays');
  if (!says) return;
  clearTimeout(PLUG.timer);
  if (!btn || !PLUG.power) { says.hidden = true; PLUG.held = false; return; }
  says.textContent = plugWords(PLUG.power);
  says.hidden = false;
  PLUG.held = btn;
  var b = btn.getBoundingClientRect(), w = says.offsetWidth;
  var x = Math.max(8, Math.min(b.right - w, window.innerWidth - 8 - w));
  if (b.left < window.innerWidth / 2) x = Math.max(8, Math.min(b.left, window.innerWidth - 8 - w));
  says.style.left = Math.round(x) + 'px';
  says.style.top = Math.round(b.bottom + 6) + 'px';
}

function plugWatch(on) {
  if (on === PLUG.watching) { plugPlace(); return; }
  PLUG.watching = on;
  if (on) loadWatch(plugPaint);
  else loadUnwatch(plugPaint);
  plugSay(null);
  plugPlace();
}

(function plugWire() {
  ['orbPlug', 'orbPlugOpen'].forEach(function (id) {
    var b = $(id);
    if (!b) return;
    // A press here is the plug's, not the orb's under it.
    b.addEventListener('pointerdown', function (e) { e.stopPropagation(); });
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      // A mouse already showed it on the way in; a second tap takes it away.
      if (PLUG.hover === b) { plugSay(b); return; }
      if (PLUG.held === b) { plugSay(null); return; }
      plugSay(b);
      PLUG.timer = setTimeout(function () { plugSay(null); }, 4000);
    });
    b.addEventListener('pointerenter', function (e) {
      if (e.pointerType === 'mouse') { PLUG.hover = b; plugSay(b); }
    });
    b.addEventListener('pointerleave', function (e) {
      if (e.pointerType === 'mouse') { PLUG.hover = null; plugSay(null); }
    });
  });
  document.addEventListener('pointerdown', function () { if (PLUG.held && !PLUG.hover) plugSay(null); });
  var box = $('orbBox');
  if (box && window.MutationObserver) {
    new MutationObserver(plugPlace).observe(box, { attributes: true, attributeFilter: ['style', 'class'] });
  }
  window.addEventListener('resize', plugPlace);
})();

/* ---------- where the orb sits ----------
 *
 * A layer of its own over the whole screen, above every panel; only the
 * node card, the settings and the notifications sit higher. Two places, and
 * on a phone a third, kept on the layer - and on the app, for the room it
 * leaves - as data-orb.
 *
 * corner  The bubble: a small circle at the bottom-left of the screen, or
 *         flicked across, its mirror at the bottom-right (`ORBX.side`) - over
 *         the task list when that is open, over the canvas when it is not,
 *         and on a phone just above the text box - and only the circle takes
 *         a click. This is where the orb is whenever it is not open, an empty
 *         canvas included. It is never drawn inside the canvas: a full page
 *         there has to be usable, and a shape underneath it that also answers
 *         the mouse leaves nobody able to tell which of the two a click will
 *         reach - and an empty canvas is the canvas's own to say it is empty.
 * open    Opened from the circle - by a click, the keyboard or the voice -
 *         over the whole screen. Escape or its close button puts it back,
 *         and so does a new card arriving. On a phone a press on the circle
 *         is the menu instead, and holding it is the orb.
 * menu    Wherever the navigation is a drawer (a phone's alone until
 *         10 October 2026, a tablet's too since): the navigation open, and
 *         the circle grown into
 *         the row pinned at the foot of it (`orbMenu`).
 *
 * The box's place and size are set from here in every state, measured
 * against what it sits over, so a move between two is one animation and
 * the picture in it changes size with the box.
 */
var ORBX = { state: 'corner', open: false, menu: false, back: null, anim: null, dirty: true,
             ring: false, fit: 0, now: '', side: 'left', drag: null };
var ORB_MOVE_MS = 300;
/* The circle growing into the row at the foot of a phone's navigation, and
   shrinking back, in step with the drawer sliding in and out (`.sidebar` at
   the foot of app.css, which uses the same length and the same two curves):
   a little quicker than a page opening in an iPhone's Settings, easing out
   on the way in and in on the way out. */
var ORB_MENU_MS = 250;
function easeOut(k) { return 1 - Math.pow(1 - k, 3); }
function easeIn(k) { return k * k * k; }
// The row is a slit onto the orb drawn at the row's width, this much closer.
var ORB_SLIT_ZOOM = 1.15;
// The row's height: the circle's, and 6 pixels round the cross that stands
// where the circle was. The circle is 66 across since 10 October 2026, half
// as big again as the 44 that is the least a finger is given here, because
// Petar found he had to aim for it ("I feel like I have to aim for it").
function orbRowHeight(circle) { return circle + 12; }
// How long a press on the circle is held before it is the orb rather than
// the menu.
var ORB_HOLD_MS = 450;

// Wherever the navigation is a drawer - a phone, a tablet either way up, a
// narrow window - the circle is the menu button (`drawerLayout`).
function orbMenuButton() {
  return drawerLayout();
}

function orbWanted() {
  return ORBX.open ? 'open' : ORBX.menu ? 'menu' : 'corner';
}

function orbRect(box) {
  var b = box.getBoundingClientRect();
  return { x: b.left, y: b.top, w: b.width, h: b.height };
}

// Where the box goes in each place, in screen coordinates. The layer is fixed
// to the screen at its top-left, so these are the box's own.
function orbTarget(state) {
  if (state === 'open') return { x: 0, y: 0, w: window.innerWidth, h: window.innerHeight };
  /* Wherever the navigation is a drawer - a phone, a tablet, a narrow
     window - the circle is the menu button, so it is where that button
     was: at the bottom left, just above the text box and never on it. The
     button is still on the page there, unseen, and `placeFold` in
     app/controls.js still keeps it clear of the box as the box grows and
     rides up over the keyboard, so this reads its place rather than working
     it out a second time. Open, the navigation is the circle grown into a
     row across the drawer, its end cap round the very same centre. */
  var fold = orbMenuButton() && $('sidebarToggle'), f = fold ? fold.getBoundingClientRect() : null;
  if (f && f.width) {
    var cx = f.left + f.width / 2, cy = f.top + f.height / 2;
    if (state === 'menu') {
      var nav = $('tasksPanel'), right = nav ? parseFloat(getComputedStyle(nav).width) : window.innerWidth * 0.78;
      // As far in from the drawer's right hand edge as from the screen's left.
      var rowH = orbRowHeight(f.height), half = rowH / 2, x = cx - half;
      return { x: x, y: cy - half, w: Math.max(rowH, right - 2 * x), h: rowH };
    }
    // Flicked to the right, the circle rests in the mirror of that spot: as
    // far in from the right hand edge, at the same height (`ORBX.side`).
    return { x: ORBX.side === 'right' ? orbLayerWidth() - f.right : f.left, y: f.top, w: f.width, h: f.height };
  }
  /* The top left corner of the window, in the square the navigation button
     had until 30 September 2026, and it never moves. Petar: "swap the
     places of the orb and the navigation. But orb is not always on top. It
     kind of slides away. I want it to be always there just like the
     navigation button is now." It rode the foot of whichever column was
     leftmost until then, so it moved whenever a column opened or closed and
     went under the drawer on a phone.

     The square is `#orbSpot`, fixed in the stylesheet exactly where that
     button was, so the notch's inset and a phone's bigger glyph are the
     stylesheet's to say and this only reads them. */
  var spot = $('orbSpot'), r = spot ? spot.getBoundingClientRect() : null;
  if (r && r.width) return { x: r.left, y: r.top, w: r.width, h: r.height };
  return { x: 10, y: 7, w: 30, h: 30 };
}

// The width of the screen the layer covers, which a desk's scrollbar is not
// part of.
function orbLayerWidth() {
  var layer = $('orbLayer');
  return (layer && layer.getBoundingClientRect().width) || window.innerWidth;
}

function orbSet(box, r) {
  var s = box.style;
  s.left = r.x + 'px'; s.top = r.y + 'px';
  s.width = r.w + 'px'; s.height = r.h + 'px';
}

// Put the box where it belongs now, unless it is on its way there.
function orbApply() {
  var box = $('orbBox');
  if (!box || ORBX.anim || ORBX.drag) return;
  var r = orbTarget(ORBX.state), s = box.style;
  if (s.left === r.x + 'px' && s.top === r.y + 'px' &&
      s.width === r.w + 'px' && s.height === r.h + 'px') return;
  orbSet(box, r);
  shared.orbSizedAt = -1e9; // the picture follows at the next frame
}

/* Nothing of the microphone's rides on the orb.

   There was once a lozenge in the middle of the shape, and on the bubble in
   the corner the whole bubble became a microphone button, which meant the
   orb - the picture of everything the machine is doing - was simply not on
   the screen until somebody had pressed it. On a phone that bubble is most
   of what there is room for. The orb is the orb in both its places now, and
   the microphone lives in the composer's button row with the other
   controls, where a control belongs. */

// Everything the page shows differently in one place or the other: which
// controls are there, what the numbers and the ring are doing, and what the
// pointer is being told. Kept apart from the move below so it can be said
// once at startup, where the orb is already in its corner and nothing is
// going to move: a page that only ever said this while changing place opened
// with no button on the bubble and no poll behind its ring.
function orbShow(next) {
  var layer = $('orbLayer'), box = $('orbBox');
  if (!layer || !box) return;
  layer.setAttribute('data-orb', next);
  if ($('app')) $('app').setAttribute('data-orb', next);
  $('orbOpen').hidden = next !== 'corner';
  $('orbClose').hidden = next !== 'open';
  // The row at the foot of a phone's open navigation: the orb behind it and
  // the cross that closes the navigation.
  $('orbRow').hidden = $('orbMenuClose').hidden = next !== 'menu';
  orbOpenSays();
  // The cog, and its panel, belong to the orb opened over the whole screen
  // and to nothing else. Whatever moves the orb out of that - a card
  // arriving, the voice, the close button - takes the panel with it, so a
  // panel is never left standing over a 96 px circle.
  $('orbCog').hidden = next !== 'open';
  // And so do the numbers under it: how busy the machine is belongs to the
  // orb being read, and the poll behind them stops with them.
  orbStatsShow(next === 'open');
  // Round the circle in the corner, the same answer as an arc. Only there:
  // over the whole screen the numbers say it in words, and a ring round the
  // edge of the screen would be a second answer to the same question. The
  // one poll feeds whichever of the two is on the screen, and stops when
  // neither is.
  orbRingShow(next === 'corner');
  // The plug, on the circle and on the open orb alike.
  plugWatch(next === 'corner' || next === 'open');
  if (next !== 'open') orbPanelShow(false);
  // The sound, and the button that turns it off, are the open orb's too:
  // back in the corner it is quiet, whatever was playing.
  $('orbSound').hidden = next !== 'open';
  orbSoundSync();
  // And the button beside it, for what the models cost. The screen it opens
  // is the open orb's: back in the corner it is gone, and opened again the
  // orb is what shows.
  $('orbUsage').hidden = next !== 'open';
  if (next !== 'open') orbUsageShow(false);
  orbTipHide();
  box.style.cursor = '';
}

function orbPlace(next, silent) {
  var layer = $('orbLayer'), box = $('orbBox');
  if (!layer || !box || next === ORBX.state) return;
  // From wherever it is now, halfway through an earlier move included, and
  // at whatever size the picture was being drawn there.
  var from = orbRect(box), was = ORBX.state;
  var fromFit = ORBX.fit || orbFit(was, from.w, from.h);
  ORBX.state = next;
  orbShow(next);
  shared.orbSizedAt = -1e9; // the picture follows at the next frame
  var to = orbTarget(next);
  var still = silent || document.hidden || !from.w ||
    (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  if (still) {
    ORBX.anim = null; box.style.pointerEvents = ''; box.classList.remove('moving');
    orbSet(box, to);
    return;
  }
  // Into the row or out of it is the drawer's move, so it takes the drawer's
  // time and curve; every other move is the orb's own.
  var menu = next === 'menu' || was === 'menu';
  ORBX.drag = null;
  /* From the right, the row it grows into is across the screen, at the foot
     of the drawer sliding in from the left: the menu stays where it is
     whichever side the circle rests on (Petar: "Keep the menu the same").
     So the circle rolls across the foot of the screen to the row's end cap,
     still a circle, while the drawer comes in under it, and only then opens
     out into the row; closing, the row shuts back into the circle first and
     the circle rolls home. Two moves told one after the other, so it reads
     as the orb going to the menu rather than a pill smeared across the
     screen. */
  var cross = menu && ORBX.side === 'right';
  ORBX.anim = { t0: performance.now(), from: from, to: to, fromFit: fromFit,
                toFit: orbFit(next, to.w, to.h),
                ms: cross ? ORB_CROSS_MS : menu ? ORB_MENU_MS : ORB_MOVE_MS, menu: menu,
                cross: cross ? (next === 'menu' ? 'in' : 'out') : '',
                ease: menu && next !== 'menu' ? easeIn : easeOut };
  // On its way it is neither the circle nor the open orb yet. Shrinking away
  // from the canvas it passes under the pointer, and a click or a hover there
  // belongs to the canvas, not to a button about to be somewhere else.
  box.style.pointerEvents = 'none';
  box.classList.add('moving');
  orbSet(box, from);
  startOrb();
}

// How big the picture is drawn in a box this size, in each place: as big as
// fits, except through the row, where it is drawn at the row's width and a
// little closer, so the row is a slit onto the middle of it.
function orbFit(state, w, h) {
  return state === 'menu' ? w * ORB_SLIT_ZOOM : Math.min(w, h);
}

// One step of a move, taken from the drawing loop so the box and the
// picture in it change size in the same frame. Moved by CSS instead, the
// renderer - which re-reads its size at most four times a second - would
// trail the box and the shape would jump.
function orbMove(ts) {
  var a = ORBX.anim, box = $('orbBox');
  if (!a || !box) return;
  if (a.swing) { orbSwingStep(a, ts, box); return; }
  var k = clamp((ts - a.t0) / a.ms, 0, 1);
  if (k >= 1) {
    ORBX.anim = null; ORBX.fit = 0;
    box.style.pointerEvents = ''; box.classList.remove('moving');
    orbSet(box, orbTarget(ORBX.state)); shared.orbSizedAt = -1e9;
    return;
  }
  var e = a.ease(k);
  // Where it goes, and how big it gets on the way, are one curve, except
  // across the screen to the menu and back (`cross` above): the left edge
  // travels while the size holds, then the size changes while the place
  // holds, overlapping a little so it never stops dead between the two.
  var ex = e, es = e;
  if (a.cross === 'in') { ex = easeInOut(clamp(k / 0.62, 0, 1)); es = easeOut(clamp((k - 0.48) / 0.52, 0, 1)); }
  else if (a.cross === 'out') { es = easeInOut(clamp(k / 0.42, 0, 1)); ex = easeInOut(clamp((k - 0.3) / 0.7, 0, 1)); }
  ORBX.fit = a.fromFit + (a.toFit - a.fromFit) * es;
  orbSet(box, {
    x: a.from.x + (a.to.x - a.from.x) * ex, y: a.from.y + (a.to.y - a.from.y) * es,
    w: a.from.w + (a.to.w - a.from.w) * es, h: a.from.h + (a.to.h - a.from.h) * es
  });
  shared.orbSizedAt = -1e9;
}

/* ---------- which side the circle rests on ----------

   Petar, 15 October 2026 (fr_433ab0e3e283): "I love the orb positioning.
   But sometimes I wish I could swing the orb to the other side with. Flick
   of a finger. Can we make it swingable to right side and back? Keep the
   menu the same."

   So the circle has two resting places, the one it has always had at the
   bottom left and its mirror at the bottom right, and nowhere in between.
   A finger, or the mouse, that takes hold of it and moves sideways carries
   it along; let go, it swings to whichever side it was thrown towards - or,
   barely thrown, the side it is nearer - on a spring, so it arrives with
   the speed it was given and settles with a small overshoot rather than
   stopping on a line. Short of the slop below, a press is still a press:
   the menu, or held, the orb.

   Petar, 27 October 2026 (fr_97bc569ba365): "Can we allow user to drag it
   all around, but keep the snap to the current two positions ... Sometimes
   it covers a bit of text and I just need it slightly up and away so I can
   read the line and then return to the same spot." So while it is held it
   follows the finger anywhere on the screen, up and down as well, and never
   past its edges; let go, the spring brings it back down to its height at
   the same moment as it swings to its side. There is still nowhere else for
   it to rest.

   The side is this browser's, like the orb's own numbers: a phone held in
   the right hand and a desk are different places to reach from. Only the
   circle moves. The menu opens from the left whichever side it rests on, and
   the circle goes to it there (`cross` in `orbPlace`). */
var KEY_ORB_SIDE = 'rouh.orb.side.v1';
ORBX.side = load(KEY_ORB_SIDE) === 'right' ? 'right' : 'left';
// How far a press may wander before it is a drag and not a tap: the usual
// slop of a finger on glass.
var ORB_FLICK_SLOP = 10;
// A throw at least this fast (px per ms) goes the way it was thrown, from
// wherever it is let go. Slower, it goes to the side it would have coasted
// nearer to in this many milliseconds, the way a page thrown on a phone does.
var ORB_FLICK_SPEED = 0.25, ORB_COAST_MS = 250;
// The spring it settles on: a swing of about 0.45 s, damped to an overshoot
// of a few pixels.
var ORB_SPRING_K = 0.0002, ORB_SPRING_C = 0.021;
// The menu from the right: across the screen, then into the row.
var ORB_CROSS_MS = 440;
function easeInOut(k) { return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; }

// The two places the circle rests, left edges, in screen coordinates.
function orbRests() {
  var side = ORBX.side, out = { left: 0, right: 0 };
  ORBX.side = 'left'; out.left = orbTarget('corner').x;
  ORBX.side = 'right'; out.right = orbTarget('corner').x;
  ORBX.side = side;
  return out;
}

// Taken hold of: it stops wherever it is, a swing still on its way included.
function orbDragStart() {
  var box = $('orbBox');
  if (!box) return { x: 0, y: 0 };
  var r = orbRect(box);
  ORBX.anim = null;
  ORBX.drag = { x: r.x, y: r.y };
  box.classList.add('held');
  box.style.pointerEvents = '';
  orbTipHide();
  return { x: r.x, y: r.y };
}

// Carried along, anywhere: harder to pull past either resting place the
// further it goes sideways, the way a page is at the end of a scroll, and
// never off what can be seen of the screen, a phone's keyboard included.
function orbDragTo(x, y) {
  var box = $('orbBox');
  if (!box || !ORBX.drag) return;
  var rest = orbRests(), r = orbRect(box), vv = window.visualViewport;
  function give(over) { return over / (1 + over / 40); }
  if (x < rest.left) x = rest.left - give(rest.left - x);
  else if (x > rest.right) x = rest.right + give(x - rest.right);
  var top = vv ? vv.offsetTop : 0, bottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
  x = clamp(x, 0, Math.max(0, orbLayerWidth() - r.w));
  y = clamp(y, top, Math.max(top, bottom - r.h));
  ORBX.drag.x = x; ORBX.drag.y = y;
  box.style.left = x + 'px';
  box.style.top = y + 'px';
}

// Let go at `v` px per ms sideways and `vy` up or down: thrown, it goes the
// way it was thrown; dropped, to the side it would coast nearer to. Either
// way it comes back to its own height.
function orbDragEnd(v, vy) {
  var box = $('orbBox');
  if (!box || !ORBX.drag) return;
  var x = ORBX.drag.x, rest = orbRests(), side;
  ORBX.drag = null;
  box.classList.remove('held');
  if (Math.abs(v) >= ORB_FLICK_SPEED) side = v > 0 ? 'right' : 'left';
  else {
    var coast = x + v * ORB_COAST_MS;
    side = coast - rest.left > rest.right - coast ? 'right' : 'left';
  }
  orbSwing(side, v, vy);
}

// Send the circle to a side, from wherever it is, at speed `v` (and `vy`).
function orbSwing(side, v, vy) {
  var box = $('orbBox');
  side = side === 'right' ? 'right' : 'left';
  if (side !== ORBX.side) {
    ORBX.side = side;
    if (side === 'right') store(KEY_ORB_SIDE, 'right');
    else drop(KEY_ORB_SIDE);
  }
  if (!box || ORBX.state !== 'corner') return;
  ORBX.drag = null;
  box.classList.remove('held');
  var from = orbRect(box), to = orbTarget('corner');
  var still = document.hidden || !from.w ||
    (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  if (still || (Math.abs(from.x - to.x) < 0.5 && Math.abs(from.y - to.y) < 0.5 && !v && !vy)) {
    ORBX.anim = null;
    orbSet(box, to);
    return;
  }
  ORBX.anim = { swing: true, x: from.x, v: v || 0, y: from.y, vy: vy || 0, last: performance.now() };
  orbSet(box, { x: from.x, y: from.y, w: to.w, h: to.h });
  startOrb();
}

// One frame of the spring, stepped a few milliseconds at a time so a slow
// frame does not throw it further than it would have gone.
function orbSwingStep(a, ts, box) {
  var to = orbTarget('corner');
  var dt = clamp(ts - a.last, 0, 48);
  a.last = ts;
  for (var left = dt; left > 0; left -= 4) {
    var h = Math.min(4, left);
    a.v += (-ORB_SPRING_K * (a.x - to.x) - ORB_SPRING_C * a.v) * h;
    a.x += a.v * h;
    a.vy += (-ORB_SPRING_K * (a.y - to.y) - ORB_SPRING_C * a.vy) * h;
    a.y += a.vy * h;
  }
  if (Math.abs(a.x - to.x) < 0.3 && Math.abs(a.v) < 0.01 &&
      Math.abs(a.y - to.y) < 0.3 && Math.abs(a.vy) < 0.01) {
    ORBX.anim = null;
    orbSet(box, to);
    return;
  }
  orbSet(box, { x: a.x, y: a.y, w: to.w, h: to.h });
}

// Open or close the orb over the whole screen. There is always something to
// open, and always a corner to go back to, so this never refuses.
function orbExpand(open) {
  open = !!open;
  if (open === ORBX.open) return true;
  var box = $('orbBox'), active = document.activeElement;
  var focusWasInside = !active || active === document.body || (box && box.contains(active));
  if (open) ORBX.back = active;
  ORBX.open = open;
  orbPlace(orbWanted());
  if (open) {
    $('orbClose').focus();
  } else {
    var back = ORBX.back;
    ORBX.back = null;
    // Opened from the row, which went with the navigation it was in: the
    // circle it came out of is the way back to both.
    if (back && box && box.contains(back) && !back.getClientRects().length) back = $('orbOpen');
    // Only when the focus was in the orb: somebody who has since clicked
    // into the text box keeps it there.
    if (focusWasInside && back && back.focus && document.contains(back)) {
      try { back.focus(); } catch (e) {}
    }
  }
  return true;
}

/* The navigation, opened or closed as a drawer, from whatever way it was
   asked for: the circle, its cross, the page beside it, Escape, Back, a link
   followed, or the key. The circle grows into the row at the foot of the
   drawer as the drawer slides in, and shrinks back as it slides out; the orb
   opened over the whole screen is left where it is. Called by `sbApply` in
   app/controls.js, the one place the navigation opens and closes. */
function orbMenu(on, silent) {
  on = !!on;
  if (on === ORBX.menu) return;
  var box = $('orbBox'), active = document.activeElement;
  var hadFocus = !!(box && active && box.contains(active));
  // Only a keyboard's focus is carried across; a finger's press leaves none
  // to carry, and a ring drawn round the cross it never touched would be one.
  var shown = hadFocus && active.matches(':focus-visible');
  ORBX.menu = on;
  orbPlace(orbWanted(), silent);
  orbOpenSays();
  // The button that had the focus is the one that just went: it goes to the
  // one in that same spot now, the cross or the circle.
  if (hadFocus && !ORBX.open) {
    var to = $(on ? 'orbMenuClose' : 'orbOpen');
    if (shown && to) try { to.focus({ preventScroll: true }); } catch (e) {}
    else if (active && /** @type {HTMLElement} */ (active).blur) /** @type {HTMLElement} */ (active).blur();
  }
}

// What the circle is to a screen reader: the menu button wherever the
// navigation is a drawer, and the way to the orb everywhere else.
function orbOpenSays() {
  var btn = $('orbOpen');
  if (!btn) return;
  if (orbMenuButton()) {
    btn.setAttribute('aria-label', 'Open menu');
    btn.setAttribute('aria-expanded', ORBX.menu ? 'true' : 'false');
    btn.setAttribute('aria-controls', 'tasksPanel');
  } else {
    btn.setAttribute('aria-label', 'Open the orb, the live picture of everything running on this machine');
    btn.removeAttribute('aria-expanded');
    btn.removeAttribute('aria-controls');
  }
}

// What the circle in the corner says when it is pointed at or focused: how
// busy the machine is, and which jobs, each with what it is doing now. At
// 96 px the lines are too small to point at one by one.
function orbCornerTip() {
  var tip = $('orbTip'), box = $('orbBox');
  // On a phone the circle is the menu button, and the row it opens into
  // says what is running in its own words.
  if (!tip || !box || ORBX.state !== 'corner' || orbMenuButton()) return;
  var ms = machineSummary(), waiting = 0, jobs = [];
  for (var i = 0; i < ORDER.length; i++) {
    var n = SCENE[ORDER[i]];
    if (!n || !n.parent || n.closed) continue;
    if (n.state === 'waiting') waiting++;
    if (n.kind === 'worker' && n.state !== 'done') jobs.push(n);
  }
  // A job waiting for the person first, then the newest.
  jobs.sort(function (a, b) {
    return (Number(b.state === 'waiting') - Number(a.state === 'waiting')) || (b.opened - a.opened);
  });
  var line = waiting ? '<span class="w">' + (waiting === 1 ? 'Something is' : waiting + ' things are') +
      ' waiting for you</span>'
    : escapeHtml(busyWords(ms));
  var list = '';
  for (var j = 0; j < jobs.length && j < 3; j++) {
    var doing = (jobs[j].raw && jobs[j].raw.doing) || '';
    list += '<div class="j' + (jobs[j].state === 'waiting' ? ' w' : '') + '">' +
      escapeHtml(clipWords(jobTitleOf(jobs[j]), 40)) +
      (doing ? ' - ' + escapeHtml(clipWords(doing, 60)) : '') + '</div>';
  }
  if (jobs.length > 3) list += '<div class="j">and ' + (jobs.length - 3) + ' more</div>';
  tip.innerHTML = '<span class="k">The orb</span><span class="l">' + line + '</span>' + list +
    '<div class="d">Click to open it over the whole screen</div>';
  tip.hidden = false;
  // Above the circle and level with it; below it where there is no room
  // above, and always inside what can be seen. On a phone the circle can sit
  // near the top of the screen, and its tip went off it and back over the
  // circle itself.
  var s = tipScreen(tip), b = box.getBoundingClientRect(), size = tipSize(tip);
  var y = b.top - size.h - 8;
  if (y < s.top + 8) y = b.bottom + 8;
  tipPut(tip, b.left, y, size, s);
}

/* The sound of the open orb (app/orb_sound.js), what the models cost in its
   place (app/orb_costs.js), and the cog wheel and the panel behind it
   (app/orb_panel.js), wired here, where their code always ran. */
wireOrbSound();
wireOrbUsage();
wireOrbPanel();

(function () {
  var btn = $('orbOpen'), close = $('orbClose'), host = $('transcript');
  if (!btn || !close || !host) return;
  /* A press on the circle. Where the navigation is a drawer it is the menu
     button, and held for a moment it is still the orb, so there is a single gesture to that too; at
     every other width it is the orb either way. The hold is timed from the
     finger going down, so the orb opens while it is still held rather than
     when it lifts, and the click that follows the lift is not a second
     press. */
  var held = { timer: 0, done: -1e9 };
  function letGo() { clearTimeout(held.timer); held.timer = 0; }
  // The click a lift may still send, after a hold or a flick, lands on
  // whatever is under the finger by then, and it was not a press on it.
  // A hold's lift can come a while after the orb opened; a flick's comes at
  // once, if a finger's drag sends one at all, and a tap a moment later is a
  // tap.
  function eatClick(within) {
    var at = performance.now();
    held.done = at;
    document.addEventListener('click', function (e) {
      if (performance.now() - at > within) return;
      e.preventDefault();
      e.stopPropagation();
    }, { capture: true, once: true });
  }
  /* The press being followed: where it went down, and where it has been in
     the last tenth of a second, which is what says how hard it was thrown.
     `moved` once it is a drag; `wandered` once it went further than a tap
     may, in any direction, so it is not a tap either. */
  var flick = null;
  btn.addEventListener('pointerdown', function (e) {
    if (e.button) return;
    letGo();
    flick = null;
    // Only the circle at rest, or swinging, is taken hold of: on its way to
    // or from the menu or the whole screen it is the move's.
    if (ORBX.state === 'corner' && (!ORBX.anim || ORBX.anim.swing)) {
      var r = orbRect($('orbBox'));
      flick = { id: e.pointerId, x0: e.clientX, y0: e.clientY, at: { x: r.x, y: r.y },
                moved: false, wandered: false, trail: [{ t: e.timeStamp, x: e.clientX, y: e.clientY }] };
      // A mouse is followed off the circle too; a finger always is.
      try { btn.setPointerCapture(e.pointerId); } catch (err) {}
      // Caught mid-swing, it stops under the finger.
      if (ORBX.anim) { flick.at = orbDragStart(); flick.moved = true; }
    }
    held.timer = setTimeout(function () {
      held.timer = 0;
      if (flick && flick.moved) return;
      flick = null;
      eatClick(1500);
      orbExpand(true);
    }, ORB_HOLD_MS);
  });
  btn.addEventListener('pointermove', function (e) {
    var f = flick;
    if (!f || e.pointerId !== f.id) return;
    var dx = e.clientX - f.x0, dy = e.clientY - f.y0;
    if (!f.moved) {
      if (Math.abs(dx) < ORB_FLICK_SLOP && Math.abs(dy) < ORB_FLICK_SLOP) return;
      // Gone too far to be a tap, or a hold: it is a drag, in any direction.
      letGo();
      f.wandered = true;
      f.moved = true;
      f.at = orbDragStart();
    }
    f.trail.push({ t: e.timeStamp, x: e.clientX, y: e.clientY });
    while (f.trail.length > 2 && e.timeStamp - f.trail[0].t > 100) f.trail.shift();
    orbDragTo(f.at.x + dx, f.at.y + dy);
  });
  function release(e) {
    var f = flick;
    if (!f || e.pointerId !== f.id) return;
    flick = null;
    letGo();
    if (f.wandered || f.moved) eatClick(400);
    if (!f.moved) return;
    // How fast it was going as it was let go, over the last tenth of a second.
    var first = f.trail[0], dt = e.timeStamp - first.t;
    var up = e.type === 'pointerup' && dt > 0;
    var v = up ? (e.clientX - first.x) / dt : 0, vy = up ? (e.clientY - first.y) / dt : 0;
    orbDragEnd(clamp(v, -4, 4), clamp(vy, -4, 4));
  }
  btn.addEventListener('pointerup', release);
  btn.addEventListener('pointercancel', release);
  btn.addEventListener('pointerleave', function () { if (!flick) letGo(); });
  btn.addEventListener('lostpointercapture', function (e) { if (flick && e.pointerId === flick.id) release(e); });
  // Held, a phone would offer to copy or share what is under the finger.
  btn.addEventListener('contextmenu', function (e) {
    if (held.timer || flick || performance.now() - held.done < 1500) e.preventDefault();
  });
  // The keyboard's flick: the arrow towards the other side sends it there.
  btn.addEventListener('keydown', function (e) {
    if ((e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') || e.altKey || e.ctrlKey || e.metaKey) return;
    if (ORBX.state !== 'corner') return;
    e.preventDefault();
    orbSwing(e.key === 'ArrowRight' ? 'right' : 'left', 0);
  });
  // Another tab of this browser moved it: so does this one.
  window.addEventListener('storage', function (e) {
    if (e && e.key === KEY_ORB_SIDE) orbSwing(e.newValue === 'right' ? 'right' : 'left', 0);
  });
  /* The storage ring round the core is drawn in the corner too, and a mouse
     can point at it there: pointed at, it says how full the disk is, and
     clicked, it opens its card rather than the menu. A finger is broader
     than the ring is wide at this size, so a tap is the circle's as it
     always was; held, the orb opens and the ring is there to tap. */
  var lastKind = '';
  btn.addEventListener('pointerdown', function (e) { lastKind = e.pointerType; }, true);
  btn.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse' || flick || ORBX.state !== 'corner') return;
    if (nodeAt(e.clientX, e.clientY) === DISK_NODE) orbTipShow(DISK_NODE, e.clientX, e.clientY);
    else if (orbMenuButton()) orbTipHide();
    else orbCornerTip();
  });
  btn.addEventListener('click', function (e) {
    letGo();
    if (lastKind === 'mouse' && ORBX.state === 'corner' && nodeAt(e.clientX, e.clientY) === DISK_NODE) {
      orbTipHide();
      openNodeCard(DISK_NODE);
      return;
    }
    if (orbMenuButton()) sbSet(true);
    else orbExpand(true);
  });
  close.addEventListener('click', function () { orbExpand(false); });
  // The row: anywhere on it but the cross opens the orb over the whole
  // screen, and the navigation goes, because the orb is what was asked for.
  $('orbRow').addEventListener('click', function () {
    orbExpand(true);
    sbSet(false);
  });
  $('orbMenuClose').addEventListener('click', function () { sbSet(false); });
  window.addEventListener('resize', orbOpenSays);
  btn.addEventListener('pointerenter', orbCornerTip);
  btn.addEventListener('pointerleave', orbTipHide);
  btn.addEventListener('focus', orbCornerTip);
  btn.addEventListener('blur', orbTipHide);
  // Escape puts it back - after the card opened from it, if one is open: that
  // card's handler runs first and marks the key as used, so one press closes
  // one thing.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented || !ORBX.open) return;
    e.preventDefault();
    // The settings panel is a thing too, and it is the nearer one: one press
    // shuts the panel and leaves the orb open behind it.
    if (orbPanelOpen()) { orbPanelShow(false); return; }
    // So is the usage screen: one press brings the orb back behind it.
    if (orbUsageOpen()) { orbUsageShow(false); return; }
    orbExpand(false);
  });
  // The box follows whatever it is placed against: the bottom-left of the
  // columns, or on a phone the pane that is showing, whose text box moves as
  // the page scrolls. Either changing marks it, and the next frame puts it
  // back in place.
  var follow = function () { ORBX.dirty = true; };
  window.addEventListener('resize', follow);
  window.addEventListener('scroll', follow, true);
  if (window.ResizeObserver) {
    var watch = new ResizeObserver(follow);
    // The menu button too, which the circle sits on: anything that ever takes
    // it off the page or gives it back changes its size from or to nothing.
    ['app', 'transcript', 'composer', 'sbFoot', 'sidebarToggle'].forEach(function (id) { if ($(id)) watch.observe($(id)); });
  }
  // On a phone the circle is where the menu button is kept, which
  // `placeFold` moves up and down with the text box by its style alone.
  if (window.MutationObserver && $('sidebarToggle')) {
    new MutationObserver(function () { ORBX.dirty = true; }).observe($('sidebarToggle'), {
      attributes: true, attributeFilter: ['style'],
    });
  }
  // And on a phone the square itself moves a row down while the
  // conversation is the screen, and back to the corner for the canvas, the
  // drawer, the task browser and the Gene therapy board (`.orb-spot` in
  // app.css), none of which changes anybody's size. Put there at once, not
  // at the next frame, so it is never seen over the canvas on the way.
  // The open Gene therapy sheet on a phone takes the menu button off the
  // page (`data-gt` in app.css), so the circle falls back to the square at
  // the top; closed, the button is back and so is the circle, at once. Left
  // out of this list, the orb stayed small at the very top after the sheet
  // closed, until something was resized or scrolled. Petar, 13 October 2026
  // (fr_bb5858ac3490): "After I exit some screens, the orb is small and at
  // the very top".
  if (window.MutationObserver && $('app')) {
    new MutationObserver(orbApply).observe($('app'), {
      attributes: true, attributeFilter: ['data-pane', 'data-sb', 'data-board', 'data-gt', 'class'],
    });
  }
  // The place the page opens in, said out loud rather than assumed from the
  // markup, and the box put where that place is.
  orbShow(ORBX.state);
  orbApply();
  // A new card puts an open orb back in its corner: the person just asked for
  // that card and cannot see it under the orb. Cards read back from the
  // server do not, because nobody asked for those now: they were already in
  // the conversation before the page opened. Nothing else about the
  // conversation moves the orb - the bubble is where it lives whether there
  // is anything on the screen or not.
  new MutationObserver(function (list) {
    if (!ORBX.open) return;
    if (CARDS && CARDS.restoring) return;
    for (var i = 0; i < list.length; i++) {
      var nodes = list[i].addedNodes;
      for (var j = 0; j < nodes.length; j++) {
        var added = /** @type {Element} */ (nodes[j]);
        if (added.classList && added.classList.contains('card-slot')) {
          orbExpand(false);
          return;
        }
      }
    }
  // The whole stream: a card drawn in an answer is inside that answer.
  }).observe(host, { childList: true, subtree: true });
})();

// A tab nobody is looking at draws nothing at all.
document.addEventListener('visibilitychange', function () {
  if (document.hidden) { stopOrb(); return; }
  ORBX.dirty = true;
  startOrb();
});
window.addEventListener('pagehide', stopOrb);
startOrb();

/* --------------------------------------------------- level meter + readouts */

function dbPct(v) {
  if (!(v > 0)) return 0;
  var db = 20 * Math.log10(v);
  return clamp((db + 60) / 60, 0, 1) * 100;
}

setInterval(function () {
  var pct = dbPct(A.level);
  $('meterFill').style.width = pct.toFixed(1) + '%';
  $('meter').setAttribute('aria-valuenow', Math.round(pct));
  $('meterOpen').style.left = dbPct(openThreshold()).toFixed(1) + '%';
  // "off" means off: no track, nothing open, no dot in anybody's status bar.
  $('meterVal').textContent = S.micReady ? Math.round(pct) + '%'
    : (MIC.opening ? 'opening' : 'off');
  // The numbers in Settings, Voice detection, worked out only while they
  // can be read.
  var voice = /** @type {HTMLElement | null} */ (document.querySelector('#settingsView .settings-section[data-section="voice"]'));
  if (voice && !voice.hidden && !$('settingsView').hidden) {
    $('roRoom').textContent = A.floor.toFixed(4);
    $('roOpen').textContent = openThreshold().toFixed(4);
    $('roClose').textContent = (A.floor * cfg.closeRatio).toFixed(4);
    var vp = $('roVadP');
    if (vp) vp.textContent = (A.vad && A.vad.ready()) ? A.vadP.toFixed(2) : 'n/a';
    $('roNow').textContent = A.level.toFixed(4);
    showSpeakerReadout();
  }
}, 100);

// What the speaker did with the audio the server sent, in the same readout
// as what the microphone heard. `Audio dropped` is hidden while it is zero
// and nothing was asked of the speaker, so it is only ever there when it
// has something to say.
function showSpeakerReadout() {
  var sp = $('roSpeaker');
  if (sp) {
    sp.textContent = !A.ctx ? 'not started'
      : A.ctx.state === 'running' ? (S.micReady ? 'on' : 'on (no microphone)')
      : A.ctx.state;
  }
  var sd = $('roSpoken');
  if (sd) sd.textContent = debug.audioSeconds.toFixed(1) + ' s in ' + debug.audioBuffers;
  var row = $('roDroppedRow'), val = $('roDropped'), lost = $('audioLost');
  var dropped = debug.audioDropped;
  if (row) row.hidden = !dropped;
  if (val) val.textContent = String(dropped) + (debug.audioBlocked ? ' (' + debug.audioBlocked + ' unplayable)' : '');
  if (lost) {
    var say = cfg.voiceReply && debug.audioBlocked;
    lost.hidden = !say;
    if (say) {
      lost.textContent = 'Some of what Rouh said could not be played here: ' +
        debug.audioBlocked + ' pieces of audio were lost because this browser ' +
        'would not open a speaker. Press the microphone button in the composer to turn the voice on.';
    }
  }
}

export { applyTree, clipWords, clockOfMs, haveTree, KEY_ORB, memColour, noteServerClock, num,
  orb, ORB_BASE, ORB_CFG, ORB_HIT, ORB_ROWS, ORB_SOUND, orbExpand, orbFrameNo, orbFromServer,
  orbMenu, orbMoved, orbRowHeight, orbPanelOpen, orbPlace, orbPointAt, orbRaf, orbStats, orbUnsent, orbW, orbWanted,
  ORBX, ORDER, SCENE, SELF, setState };
// For the sound, the model costs and the cog's panel, in modules of their own.
// And which kind a tool call is, for the reply's timeline, whose rows wear the twigs' colours (app/turnline.js).
export { kindOf, ORB_GROUPS, orbSane, orbSaveNow, orbSaveSoon, orbTipHide, slowMo };
