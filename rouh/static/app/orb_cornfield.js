/* Rouh's page, the open orb's music as a version of "Cornfield Chase"
 * (used by app/orb_sound.js, only when this Rouh's switch says so).
 *
 * Asked for on 12 November 2026: "change the music on the orb with a modelled
 * version of the song cornfield chase. So the background should be
 * continuous, then when we have a few twigs, it should start having the
 * melody, then when we have a lot of work it should go into the heavy part of
 * the song, layered ... it is not going to sound like the real thing, because
 * the timing will be distorted, but the idea is for people to recognize the
 * song."
 *
 * RIGHTS. "Cornfield Chase" (Hans Zimmer, Interstellar, 2014) belongs to its
 * composer and publisher. This is an arrangement in its style, played from
 * notes written here and made live in Web Audio: no recording, no sample and
 * no file from the soundtrack. It is still an arrangement of somebody else's
 * composition, so it sits behind its own feature switch, `orb_cornfield`,
 * which is off on every installation until its owner turns it on
 * (`rouh/web/views.py`, `_orb_cornfield`). It must NOT ship on by default in
 * a public release of Rouh without the rights being cleared. With the switch
 * off the orb plays its own music, the chords and the notes in
 * app/orb_sound.js, exactly as before.
 *
 * What it plays follows the same live tree the orb draws: spikes are jobs,
 * branches are helpers (sub-agents), twigs are tool calls, and Rouh's own
 * turn is a line of its own.
 *
 *   level 0, always   the organ ostinato, the repeating pulse of the piece,
 *                     soft and steady, over a low held root
 *   level 1           a few twigs open: the long-note melody comes in over it
 *   level 2           a lot of work: the heavy, layered climax - a low organ
 *                     pedal, sixteenth-note arpeggios spread left and right,
 *                     a bowed counter-line, the pulse doubled and louder
 *
 * The levels crossfade over a few seconds, the counts are smoothed so a burst
 * of calls starting and stopping does not flap them, and each new twig pushes
 * the music on a little (it plays faster for a moment, so the next melody
 * note comes sooner): the timing follows the work.
 *
 * The step counter never resets while it plays, every note is scheduled ahead
 * on the audio clock with a soft start and end overlapping the next, and a
 * layer only ever moves by its gain, so nothing gaps or clicks at the loop or
 * between levels. */
import { clamp } from 'app/helpers.js';
import { SCENE, SELF } from 'app/orb.js';

/* ---------- the numbers to change ------------------------------------ */

//: The pulse: quarter notes a minute, and an eighth note's length from it.
var CF_BPM = 96;
var CF_EIGHTH = 60 / CF_BPM / 2;

//: Level 1, the melody: on once the smoothed count of open tool calls reaches
//: MELODY_ON, off again only once it has fallen under MELODY_OFF.
var CF_MELODY_ON = 2, CF_MELODY_OFF = 1;
//: Level 2, the heavy part: on at HEAVY_CALLS open tool calls, or HEAVY_LINES
//: jobs and helpers running at once; off under the _OFF numbers.
var CF_HEAVY_CALLS = 7, CF_HEAVY_CALLS_OFF = 5;
var CF_HEAVY_LINES = 3, CF_HEAVY_LINES_OFF = 2;
//: How long a level is held before the music may come down from it, in ms.
var CF_HOLD_MS = 5000;
//: How the counts are smoothed: seconds to follow a rise, and a fall.
var CF_RISE_S = 0.8, CF_FALL_S = 4;
//: The crossfade between levels: the time constant, in seconds (a layer is
//: there in about three of them).
var CF_FADE_S = 1.1;
//: Each new twig speeds the music up by this much for a moment, never past
//: CF_PUSH_MAX, and the push dies away with this time constant in seconds.
var CF_PUSH = 0.18, CF_PUSH_MAX = 0.7, CF_PUSH_DECAY_S = 2.2;
//: How far ahead notes are put on the audio clock, in seconds.
var CF_AHEAD = 0.3;

/* ---------- the arrangement ------------------------------------------- */

// A minor, eight bars of eight eighth notes, round and round:
// Am Am F F C C G G.
var CF_STEPS = 64;
//: Each bar's chord as MIDI notes, root first, in the third octave.
var CF_CHORDS = [
  [57, 60, 64], [57, 60, 64], [53, 57, 60], [53, 57, 60],
  [48, 52, 55], [48, 52, 55], [55, 59, 62], [55, 59, 62]
];
//: The ostinato: every other eighth rocks back to the E above, the ones
//: between walk a note per bar, so the pulse is two notes rocking.
var CF_PIVOT = 76; // E5
var CF_WALK = [69, 71, 72, 69, 67, 72, 71, 74]; // A4 B4 C5 A4 G4 C5 B4 D5
//: The melody: long notes [MIDI, first eighth, eighths held] across the 64.
var CF_TUNE = [
  [81, 0, 6], [83, 6, 2],
  [84, 8, 6], [83, 14, 2],
  [81, 16, 8],
  [76, 24, 4], [77, 28, 4],
  [79, 32, 6], [76, 38, 2],
  [84, 40, 4], [83, 44, 4],
  [83, 48, 8],
  [86, 56, 4], [84, 60, 2], [83, 62, 2]
];
//: The bowed counter-line of the heavy part: a half note each half bar.
var CF_COUNTER = [64, 62, 60, 59, 60, 57, 57, 59, 55, 57, 55, 52, 62, 59, 62, 64];

/* ---------- state ------------------------------------------------------ */

var CF = {
  ctx: null,
  organ: null, bow: null,
  notes: null, ost: null, mel: null, heavy: null, wideL: null, wideR: null,
  step: 0, stepAt: 0,
  push: 0,
  calls: 0, lines: 0,     // the smoothed counts
  raw: { calls: 0, lines: 0, jobs: 0, helpers: 0, self: false },
  level: 0, levelAt: 0,
  fadeUntil: [0, 0, 0],   // until when each layer may still be heard fading out
  lastT: 0,
  voices: [],             // every oscillator still to finish: [osc, ends]
  played: 0, nudges: 0
};

function mtof(m) { return 440 * Math.pow(2, (m - 69) / 12); }

// A pipe organ's tone: the drawbars at 8', 4', 2 2/3', 2' and a little of
// the higher ones, so it is round and reedy at once.
function organWave(ctx) {
  var n = 17, re = new Float32Array(n), im = new Float32Array(n);
  var bars = { 1: 1, 2: 0.55, 3: 0.32, 4: 0.28, 6: 0.1, 8: 0.09, 10: 0.03, 12: 0.03, 16: 0.02 };
  for (var k in bars) im[+k] = bars[k];
  return ctx.createPeriodicWave(re, im);
}

function bowWave(ctx) {
  var n = 24, re = new Float32Array(n), im = new Float32Array(n);
  for (var k = 1; k < n; k++) im[k] = Math.exp(-k / 6) / k;
  return ctx.createPeriodicWave(re, im);
}

// The three layers, built once per context: the ostinato into the music's
// level, the melody and the heavy part into the notes' level, so the cog's
// two sliders and the step back under Rouh's voice work as they always did.
function cfGraph(ctx, music, notes) {
  if (CF.ctx === ctx) return;
  CF.notes = notes;
  CF.organ = organWave(ctx);
  CF.bow = bowWave(ctx);
  CF.ost = ctx.createGain(); CF.ost.gain.value = 0; CF.ost.connect(music);
  CF.mel = ctx.createGain(); CF.mel.gain.value = 0; CF.mel.connect(notes);
  CF.heavy = ctx.createGain(); CF.heavy.gain.value = 0; CF.heavy.connect(notes);
  // The heavy part is wide: its arpeggios alternate between the two sides.
  CF.wideL = side(ctx, -0.75); CF.wideR = side(ctx, 0.75);
  CF.ctx = ctx;
}

function side(ctx, pan) {
  if (!ctx.createStereoPanner) return CF.heavy;
  var p = ctx.createStereoPanner();
  p.pan.value = pan;
  p.connect(CF.heavy);
  return p;
}

// One note: two oscillators a few cents apart for the chorus of a big
// instrument, a soft start and a soft end, so a note never clicks and the
// next has already begun as it goes.
function cfNote(midi, t, dur, vel, out, opts) {
  var ctx = CF.ctx, o = opts || {};
  var atk = o.attack || 0.015, rel = o.release || 0.07, end = t + dur;
  var g = ctx.createGain(), f = mtof(midi), dest = g;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(vel, t + atk);
  g.gain.setValueAtTime(vel, Math.max(t + atk, end - rel));
  g.gain.linearRampToValueAtTime(0, end + rel);
  if (o.dark) {
    var lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = o.dark;
    lp.Q.value = 0.3;
    g.connect(lp);
    lp.connect(out);
  } else g.connect(out);
  var pair = o.single ? [0] : [-4, 4];
  for (var i = 0; i < pair.length; i++) {
    var osc = ctx.createOscillator();
    osc.setPeriodicWave(o.wave || CF.organ);
    osc.frequency.value = f;
    osc.detune.value = pair[i];
    osc.connect(dest);
    osc.start(t);
    osc.stop(end + rel + 0.05);
    CF.voices.push([osc, end + rel + 0.05]);
  }
  CF.played++;
}

/* ---------- following the work ---------------------------------------- */

// What is open on the orb right now: tool calls (twigs), jobs (spikes) and
// helpers (branches), and whether Rouh's own turn is running.
function cfCount() {
  var calls = 0, jobs = 0, helpers = 0;
  for (var id in SCENE) {
    var n = SCENE[id];
    if (!n || n.fade || n.closed) continue;
    if (n.state && n.state !== 'running') continue;
    if (n.kind === 'tool') calls++;
    else if (n.kind === 'worker') jobs++;
    else if (n.kind === 'subagent') helpers++;
  }
  var self = !!(SELF && SELF.opened && !SELF.fade);
  CF.raw = { calls: calls, lines: jobs + helpers + (self ? 1 : 0), jobs: jobs, helpers: helpers, self: self };
}

function follow(cur, want, dt) {
  var tau = want > cur ? CF_RISE_S : CF_FALL_S;
  return cur + (want - cur) * (1 - Math.exp(-dt / tau));
}

function cfLevelNow(wall) {
  var up = CF.level, c = CF.calls, l = CF.lines;
  if (c >= CF_HEAVY_CALLS - 0.5 || l >= CF_HEAVY_LINES - 0.5) up = 2;
  else if (CF.level < 1 && c >= CF_MELODY_ON - 0.5) up = 1;
  if (up > CF.level) return up;
  var down = CF.level;
  if (CF.level === 2 && c < CF_HEAVY_CALLS_OFF && l < CF_HEAVY_LINES_OFF) down = c >= CF_MELODY_OFF ? 1 : 0;
  else if (CF.level === 1 && c < CF_MELODY_OFF) down = 0;
  if (down < CF.level && wall - CF.levelAt >= CF_HOLD_MS) return down;
  return CF.level;
}

// Each layer's gain toward where the level wants it. Written only when the
// level changes, so the automation does not pile up.
function cfLayers(t) {
  var L = CF.level, i, want = [L === 2 ? 1.3 : 1, L >= 1 ? 1 : 0, L === 2 ? 1 : 0];
  var nodes = [CF.ost, CF.mel, CF.heavy];
  for (i = 0; i < 3; i++) {
    var was = nodes[i].gain.value;
    nodes[i].gain.cancelScheduledValues(t);
    nodes[i].gain.setValueAtTime(nodes[i].gain.value, t);
    nodes[i].gain.setTargetAtTime(want[i], t, CF_FADE_S);
    // A layer going out is still played until it can no longer be heard;
    // one that was silent already is not played at all.
    CF.fadeUntil[i] = want[i] === 0 && was > 0.001 ? t + CF_FADE_S * 6 : 0;
  }
}

/* ---------- the score, a step at a time ------------------------------- */

function cfStep(s, t, dur) {
  var bar = Math.floor(s / 8) % 8, inBar = s % 8, chord = CF_CHORDS[bar];
  var heavyOn = CF.level === 2 || t < CF.fadeUntil[2];
  var melOn = CF.level >= 1 || t < CF.fadeUntil[1];
  // The ostinato, always: the walking note, then the E it rocks back to.
  var m = inBar % 2 ? CF_PIVOT : CF_WALK[bar];
  cfNote(m, t, dur * 0.96, inBar === 0 ? 0.075 : 0.06, CF.ost);
  // Under it, the root held through the bar, low and dark.
  if (inBar === 0) cfNote(chord[0] - 12, t, dur * 8, 0.05, CF.ost, { attack: 0.25, release: 0.4, dark: 900 });
  if (melOn) {
    for (var i = 0; i < CF_TUNE.length; i++) {
      if (CF_TUNE[i][1] !== s % CF_STEPS) continue;
      var len = dur * CF_TUNE[i][2];
      cfNote(CF_TUNE[i][0], t, len, 0.075, CF.mel, { attack: 0.09, release: 0.35 });
      // In the heavy part the tune is doubled an octave under, organ full.
      if (heavyOn) cfNote(CF_TUNE[i][0] - 12, t, len, 0.05, CF.heavy, { attack: 0.12, release: 0.4 });
    }
  }
  if (heavyOn) {
    // The pedal: the root two octaves down, held through the bar.
    if (inBar === 0) cfNote(chord[0] - 24, t, dur * 8, 0.11, CF.heavy, { attack: 0.3, release: 0.5, dark: 500 });
    // The counter-line, bowed, a half note each half bar.
    if (inBar % 4 === 0) cfNote(CF_COUNTER[(bar * 2 + inBar / 4) % CF_COUNTER.length], t, dur * 4, 0.05, CF.heavy,
      { wave: CF.bow, attack: 0.25, release: 0.3, dark: 2400 });
    // Sixteenth-note arpeggios over the chord, two octaves up, side to side.
    var tones = [chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[0] + 24, chord[1] + 24, chord[2] + 24];
    var walk = [0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3];
    for (var h = 0; h < 2; h++) {
      var k = (inBar * 2 + h) % walk.length;
      cfNote(tones[walk[k]], t + h * dur / 2, dur / 2 * 0.9, 0.035, h ? CF.wideR : CF.wideL,
        { single: true, release: 0.05 });
    }
    // The pulse doubled an octave up.
    cfNote(m + 12, t, dur * 0.9, 0.03, CF.heavy, { single: true });
  }
}

/* ---------- what app/orb_sound.js calls ------------------------------- */

// Started with the rest of the orb's sound: the layers built, the pulse in
// at once and the rest where the work already is.
function cfStart(ctx, music, notes) {
  cfGraph(ctx, music, notes);
  var t = ctx.currentTime;
  CF.stepAt = t + 0.08;
  CF.lastT = t;
  CF.push = 0;
  cfCount();
  CF.calls = CF.raw.calls;
  CF.lines = CF.raw.lines;
  CF.level = 0;
  CF.level = cfLevelNow(performance.now());
  CF.levelAt = performance.now();
  CF.fadeUntil = [0, 0, 0];
  cfLayers(t);
}

// Every tick while it sounds: the counts followed, the level moved if it
// should be, and the next notes put on the clock.
function cfTick(ctx) {
  var t = ctx.currentTime, wall = performance.now();
  var dt = clamp(t - CF.lastT, 0, 1);
  CF.lastT = t;
  cfCount();
  CF.calls = follow(CF.calls, CF.raw.calls, dt);
  CF.lines = follow(CF.lines, CF.raw.lines, dt);
  CF.push *= Math.exp(-dt / CF_PUSH_DECAY_S);
  var lv = cfLevelNow(wall);
  if (lv !== CF.level) { CF.level = lv; CF.levelAt = wall; cfLayers(t); }
  // A speaker the browser still holds back has a stopped clock: nothing is
  // put on it, and the pulse starts from the press that lets it out.
  if (ctx.state !== 'running') { CF.stepAt = t + 0.08; return; }
  if (CF.stepAt < t) CF.stepAt = t + 0.02;
  while (CF.stepAt < t + CF_AHEAD) {
    var dur = CF_EIGHTH / (1 + CF.push);
    cfStep(CF.step, CF.stepAt, dur);
    CF.step++;
    CF.stepAt += dur;
  }
  for (var i = CF.voices.length - 1; i >= 0; i--) if (CF.voices[i][1] < t) CF.voices.splice(i, 1);
}

// Something new on the orb: a twig pushes the music on, a new line a little more.
function cfNudge(voice) {
  CF.push = Math.min(CF_PUSH_MAX, CF.push + (voice === 'call' ? CF_PUSH : CF_PUSH * 1.5));
  CF.nudges++;
}

// The notes slider moved: one note of the tune at the new level.
function cfPreview(ctx) {
  if (CF.ctx !== ctx || ctx.state !== 'running') return;
  cfNote(81, ctx.currentTime + 0.03, 0.6, 0.075, CF.notes, { attack: 0.05, release: 0.3 });
}

// Everything still sounding stopped outright, once it can no longer be heard.
function cfHush(t) {
  for (var i = 0; i < CF.voices.length; i++) {
    try { CF.voices[i][0].stop(t); } catch (e) {}
  }
  CF.voices.length = 0;
}

// For the page's checks (`window.__rouh.orbSound`).
function cfState() {
  return {
    level: CF.level, calls: +CF.calls.toFixed(2), lines: +CF.lines.toFixed(2), raw: CF.raw,
    push: +CF.push.toFixed(3), step: CF.step, played: CF.played, nudges: CF.nudges,
    voices: CF.voices.length,
    gains: CF.ost ? [CF.ost.gain.value, CF.mel.gain.value, CF.heavy.gain.value].map(function (g) { return +g.toFixed(3); }) : []
  };
}

export { cfHush, cfNudge, cfPreview, cfStart, cfState, cfTick };
