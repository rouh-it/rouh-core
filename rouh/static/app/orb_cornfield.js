// SPDX-License-Identifier: Apache-2.0
/* Rouh's page, the open orb's music as a version of "Cornfield Chase"
 * (used by app/orb_sound.js, only when this Rouh's switch says so).
 *
 * Asked for on 12 November 2026: "change the music on the orb with a modelled
 * version of the song cornfield chase. So the background should be
 * continuous, then when we have a few twigs, it should start having the
 * melody, then when we have a lot of work it should go into the heavy part of
 * the song, layered ... the idea is for people to recognize the song."
 * And the same evening, after hearing the first version: "it is too fast and
 * doesn't feel like cornfield chase at all. Needs to slow down. Also, can you
 * make the sounds less electronic and more close to the real sound of the
 * orchestra instruments?"
 *
 * RIGHTS. "Cornfield Chase" (Hans Zimmer, Interstellar, 2014) belongs to its
 * composer and publisher. This is an arrangement in its manner - A minor, the
 * pipe organ rocking between two notes over a bass that climbs two steps and
 * falls back one, a slow melody of long notes over it - written out here note
 * by note. Nothing in it comes from the soundtrack: no recording, no sample,
 * no file of it. It is still an arrangement of somebody else's composition,
 * so it sits behind its own feature switch, `orb_cornfield`, which is off on
 * every installation until its owner turns it on (`rouh/web/views.py`,
 * `_orb_cornfield`). It must NOT ship on by default in a public release of
 * Rouh without the rights being cleared. With the switch off the orb plays
 * its own music, the chords and the notes in app/orb_sound.js, as before.
 *
 * THE INSTRUMENTS are real recordings: a pipe organ (quiet flue stops, the
 * main voice, and the full registration with a 16' for the climax, each with
 * its pedal), an upright piano, a violin section, a cello section and a
 * contrabass, from the Versilian Community Sample Library, VSCO 2 Community
 * Edition, which is CC0 1.0 - given to the public domain by Versilian Studios
 * (the organ and piano sampled by Simon Dalzell of Ivy Audio). A few notes of
 * each are packed into rouh/static/orb_cornfield/samples.bin, MP3, about 670 KB
 * in all, the rest reached by playing them faster or slower; LICENSE.md
 * beside them has the credits, and tools/orb_cornfield/build_samples.py makes
 * them again. They are fetched only when the switch is on and the orb is
 * opened with its sound on, once per page. Until they have arrived, or if
 * they never do, the same score is played on the small organ and string tones
 * made here, quietly and without a word in the console.
 *
 * What it plays follows the same live tree the orb draws: spikes are jobs,
 * branches are helpers (sub-agents), twigs are tool calls, and Rouh's own
 * turn is a line of its own.
 *
 *   level 0, always   the organ's rocking figure alone, soft and unhurried
 *   level 1           a few twigs open: the melody comes in, long notes on
 *                     organ and piano with space between the phrases, and
 *                     the pedal holds the bass under it
 *   level 2           a lot of work: the climax, layered - the full organ
 *                     with its 16' pedal, violins on the melody an octave up,
 *                     cellos and basses under, the piano doubling the figure
 *
 * Busier work adds layers and volume, never speed. The tempo is one named
 * number, CF_TEMPO_BPM; a new twig may lean on it by a couple of percent at
 * most, glided over seconds, which nobody hears as a change of tempo. The
 * levels crossfade over about three seconds, and the counts are smoothed and
 * held so a burst of calls starting and stopping does not flap them.
 *
 * The step counter never resets while it plays, every note is scheduled ahead
 * on the audio clock with a soft start and end, and a layer only ever moves by
 * its gain, so nothing gaps or clicks at the loop or between levels. */
import { clamp } from 'app/helpers.js';
import { SCENE, SELF } from 'app/orb.js';

/* ---------- the numbers to change ------------------------------------ */

//: The tempo: quarter notes a minute. The organ's figure moves in eighth
//: notes, so this is two notes a second, a bar of four seconds.
var CF_TEMPO_BPM = 60;
var CF_EIGHTH = 60 / CF_TEMPO_BPM / 2;

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
//: The barely-there lean of new work: each new twig asks for this much more
//: speed, never past CF_LEAN_MAX in all (3%), and the asking dies away with
//: CF_LEAN_DECAY_S. The tempo follows what is asked with CF_TEMPO_GLIDE_S, so
//: any change is spread over several seconds.
var CF_LEAN = 0.01, CF_LEAN_MAX = 0.03, CF_LEAN_DECAY_S = 10, CF_TEMPO_GLIDE_S = 4;
//: How much louder the organ's figure plays in the climax.
var CF_HEAVY_SWELL = 1.35;
//: The church: the reverb's length in seconds and how much of it is heard.
var CF_HALL_S = 4.6, CF_HALL_WET = 0.3;
//: How far ahead notes are put on the audio clock, in seconds.
var CF_AHEAD = 0.6;

/* ---------- the score -------------------------------------------------- */

// A minor, eight bars of eight eighth notes, round and round, 32 seconds at
// the tempo above. The bass climbs two steps and falls back one, A B C B,
// then C D and up to E, the dominant, which leads back to A.
var CF_STEPS = 64;
//: Each bar: the bass, the chord the climax holds, and the moving lower note
//: of the organ's figure (its upper note stays on E5 all the way).
var CF_BARS = [
  { bass: 45, chord: [57, 60, 64], low: 69 }, // Am       A2 | A4
  { bass: 47, chord: [55, 59, 64], low: 71 }, // Em/B     B2 | B4
  { bass: 48, chord: [55, 60, 64], low: 72 }, // C        C3 | C5
  { bass: 47, chord: [55, 59, 64], low: 71 }, // Em/B     B2 | B4
  { bass: 48, chord: [55, 60, 64], low: 72 }, // C        C3 | C5
  { bass: 50, chord: [57, 62, 65], low: 74 }, // Dm       D3 | D5
  { bass: 52, chord: [56, 59, 64], low: 71 }, // E        E3 | B4
  { bass: 52, chord: [56, 59, 62], low: 68 }  // E7       E3 | G#4
];
//: The upper note the figure rocks back to.
var CF_PIVOT = 76; // E5
//: The melody: [MIDI, first eighth, eighths held] across the 64. Long notes,
//: two phrases of four bars, each ending with room to breathe.
var CF_TUNE = [
  [76, 0, 7],                     // E5 . . . . . .
  [74, 8, 4], [71, 12, 4],        // D5 . . .  B4 . . .
  [72, 16, 6], [74, 22, 2],       // C5 . . . . .  D5 .
  [71, 24, 6],                    // B4 . . . . .      (breath)
  [76, 32, 4], [79, 36, 4],       // E5 . . .  G5 . . .
  [77, 40, 6], [76, 46, 2],       // F5 . . . . .  E5 .
  [74, 48, 4], [71, 52, 4],       // D5 . . .  B4 . . .
  [68, 56, 6]                     // G#4 . . . . .     (breath, back to A)
];
//: The cellos' line in the climax: a half note each half bar, under the tune.
var CF_CELLOS = [60, 64, 59, 62, 60, 55, 59, 55, 60, 64, 62, 57, 59, 56, 59, 56];

/* ---------- the instruments ------------------------------------------- */

//: How each instrument is played: its attack and release in seconds, a trim
//: on its level, and how the fallback makes it when the samples are not here.
var CF_VOICES = {
  organ: { attack: 0.04, release: 0.28, trim: 1, synth: 'organ' },
  organ_full: { attack: 0.05, release: 0.4, trim: 0.9, synth: 'organ' },
  pedal: { attack: 0.12, release: 0.5, trim: 1.1, synth: 'pedal' },
  pedal_full: { attack: 0.12, release: 0.6, trim: 1.1, synth: 'pedal' },
  piano: { attack: 0.004, release: 0.5, trim: 1.3, synth: 'piano' },
  violins: { attack: 0.35, release: 0.6, trim: 0.9, synth: 'bow' },
  cellos: { attack: 0.3, release: 0.6, trim: 0.9, synth: 'bow' },
  basses: { attack: 0.3, release: 0.6, trim: 1, synth: 'bow' }
};

/* ---------- state ------------------------------------------------------ */

var CF = {
  ctx: null,
  organ: null, bow: null, hall: null,
  notes: null, ost: null, mel: null, heavy: null, wideL: null, wideR: null,
  // The samples: where they are (from the page), and once decoded, each
  // instrument's notes as [{ midi, buffer, loop }]. `loading` is the fetch
  // in flight; `failed` once it has given up, which leaves the fallback.
  urls: null, bank: null, loading: null, failed: false, bankCtx: null,
  step: 0, stepAt: 0,
  lean: 0, speed: 1,
  calls: 0, lines: 0,     // the smoothed counts
  raw: { calls: 0, lines: 0, jobs: 0, helpers: 0, self: false },
  level: 0, levelAt: 0,
  fadeUntil: [0, 0, 0],   // until when each layer may still be heard fading out
  lastT: 0,
  voices: [],             // every source still to finish: [node, ends]
  played: 0, sampled: 0, nudges: 0
};

function mtof(m) { return 440 * Math.pow(2, (m - 69) / 12); }

// The fallback's pipe organ: drawbars at 8', 4', 2 2/3' and 2', round.
function organWave(ctx) {
  var n = 17, re = new Float32Array(n), im = new Float32Array(n);
  var bars = { 1: 1, 2: 0.45, 3: 0.22, 4: 0.18, 6: 0.06, 8: 0.05 };
  for (var k in bars) im[+k] = bars[k];
  return ctx.createPeriodicWave(re, im);
}

function bowWave(ctx) {
  var n = 24, re = new Float32Array(n), im = new Float32Array(n);
  for (var k = 1; k < n; k++) im[k] = Math.exp(-k / 6) / k;
  return ctx.createPeriodicWave(re, im);
}

// A large stone church's answer: two channels of noise that darken and die
// away over CF_HALL_S, after the short gap before the first reflection.
function hallImpulse(ctx) {
  var rate = ctx.sampleRate, n = Math.floor(rate * CF_HALL_S), gap = Math.floor(rate * 0.03);
  var buf = ctx.createBuffer(2, n, rate), c, i, d, lp, k;
  for (c = 0; c < 2; c++) {
    d = buf.getChannelData(c);
    lp = 0;
    for (i = gap; i < n; i++) {
      k = (i - gap) / (n - gap);
      lp += (Math.random() * 2 - 1 - lp) * (0.5 - 0.42 * k);
      d[i] = lp * Math.exp(-k * 6.2) * (i < gap * 2 ? (i - gap) / gap : 1);
    }
  }
  return buf;
}

// The three layers, built once per context: the organ's figure into the
// music's level, the melody and the climax into the notes' level, so the
// cog's two sliders and the step back under Rouh's voice work as they always
// did. Each layer is heard dry and through the church.
function cfGraph(ctx, music, notes) {
  if (CF.ctx === ctx) return;
  CF.notes = notes;
  CF.organ = organWave(ctx);
  CF.bow = bowWave(ctx);
  CF.ost = layer(ctx, music);
  CF.mel = layer(ctx, notes);
  CF.heavy = layer(ctx, notes);
  // The climax is wide: its strings to one side, the piano to the other.
  CF.wideL = side(ctx, -0.55); CF.wideR = side(ctx, 0.55);
  CF.ctx = ctx;
}

function layer(ctx, dest) {
  var g = ctx.createGain();
  g.gain.value = 0;
  g.connect(dest);
  try {
    var hall = ctx.createConvolver(), wet = ctx.createGain();
    if (!CF.hall || CF.hall.sampleRate !== ctx.sampleRate) CF.hall = hallImpulse(ctx);
    hall.buffer = CF.hall;
    wet.gain.value = CF_HALL_WET;
    g.connect(hall);
    hall.connect(wet);
    wet.connect(dest);
  } catch (e) {}
  return g;
}

function side(ctx, pan) {
  if (!ctx.createStereoPanner) return CF.heavy;
  var p = ctx.createStereoPanner();
  p.pan.value = pan;
  p.connect(CF.heavy);
  return p;
}

/* ---------- the samples ----------------------------------------------- */

// Fetched once per page, only from here, which only runs with the switch on
// and the orb open with its sound on. The manifest says where in the one
// file each note is; each is decoded on its own.
function cfLoad(ctx) {
  if (CF.loading || CF.failed || !CF.urls || !CF.urls.json || !CF.urls.bin) return;
  CF.loading = Promise.all([
    fetch(CF.urls.json).then(function (r) { if (!r.ok) throw new Error('manifest'); return r.json(); }),
    fetch(CF.urls.bin).then(function (r) { if (!r.ok) throw new Error('samples'); return r.arrayBuffer(); })
  ]).then(function (got) {
    var manifest = got[0], blob = got[1], jobs = [], bank = {};
    Object.keys(manifest.instruments || {}).forEach(function (name) {
      var inst = manifest.instruments[name];
      bank[name] = [];
      inst.zones.forEach(function (z) {
        jobs.push(decode(ctx, blob.slice(z.at, z.at + z.size)).then(function (buffer) {
          bank[name].push({ midi: z.midi, buffer: buffer, loop: z.loop });
        }));
      });
    });
    return Promise.all(jobs).then(function () {
      Object.keys(bank).forEach(function (name) { bank[name].sort(function (a, b) { return a.midi - b.midi; }); });
      CF.bank = bank;
      CF.bankCtx = ctx;
    });
  }).catch(function () {
    // Quietly the fallback, for good on this page.
    CF.failed = true;
    CF.bank = null;
  });
}

function decode(ctx, data) {
  return new Promise(function (ok, no) {
    var p = ctx.decodeAudioData(data, ok, no);
    if (p && p.then) p.then(ok, no);
  });
}

// The recorded note nearest the one wanted.
function zoneFor(name, midi) {
  var zones = CF.bank && CF.bankCtx === CF.ctx && CF.bank[name];
  if (!zones || !zones.length) return null;
  var best = zones[0];
  for (var i = 1; i < zones.length; i++) if (Math.abs(zones[i].midi - midi) < Math.abs(best.midi - midi)) best = zones[i];
  return best;
}

/* ---------- one note -------------------------------------------------- */

// One note on one instrument, from its recording when it is here, else made.
function cfPlay(name, midi, t, dur, vel, out) {
  var v = CF_VOICES[name], ctx = CF.ctx;
  var atk = v.attack, rel = v.release, end = t + dur;
  var g = ctx.createGain(), level = vel * v.trim;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(level, t + atk);
  g.gain.setValueAtTime(level, Math.max(t + atk, end));
  g.gain.setTargetAtTime(0, Math.max(t + atk, end), rel / 3);
  g.connect(out);
  var stopAt = end + rel * 1.6 + 0.05;
  var zone = zoneFor(name, midi);
  if (zone) {
    var src = ctx.createBufferSource();
    src.buffer = zone.buffer;
    src.playbackRate.value = Math.pow(2, (midi - zone.midi) / 12);
    if (zone.loop) {
      src.loop = true;
      src.loopStart = zone.loop[0];
      src.loopEnd = zone.loop[1];
    } else {
      stopAt = Math.min(stopAt, t + zone.buffer.duration / src.playbackRate.value);
    }
    src.connect(g);
    src.start(t);
    src.stop(stopAt);
    CF.voices.push([src, stopAt]);
    CF.sampled++;
  } else {
    synth(v.synth, midi, t, stopAt, g);
  }
  CF.played++;
}

// The fallback: two oscillators a few cents apart, darkened for the low and
// the bowed voices, a piano left to fade.
function synth(kind, midi, t, stopAt, g) {
  var ctx = CF.ctx, dest = g, f = mtof(midi);
  if (kind !== 'organ') {
    var lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = kind === 'pedal' ? 600 : kind === 'bow' ? 2200 : 3000;
    lp.Q.value = 0.3;
    lp.connect(g);
    dest = lp;
  }
  if (kind === 'piano') {
    var fall = ctx.createGain();
    fall.gain.setValueAtTime(1, t);
    fall.gain.setTargetAtTime(0.15, t + 0.01, 0.8);
    fall.connect(dest);
    dest = fall;
  }
  var pair = kind === 'piano' ? [0] : [-4, 4];
  for (var i = 0; i < pair.length; i++) {
    var osc = ctx.createOscillator();
    osc.setPeriodicWave(kind === 'bow' ? CF.bow : CF.organ);
    osc.frequency.value = f;
    osc.detune.value = pair[i];
    osc.connect(dest);
    osc.start(t);
    osc.stop(stopAt);
    CF.voices.push([osc, stopAt]);
  }
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
  var L = CF.level, i, want = [L === 2 ? CF_HEAVY_SWELL : 1, L >= 1 ? 1 : 0, L === 2 ? 1 : 0];
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
  var at = s % CF_STEPS, b = Math.floor(at / 8), inBar = at % 8, bar = CF_BARS[b];
  var heavyOn = CF.level === 2 || t < CF.fadeUntil[2];
  var melOn = CF.level >= 1 || t < CF.fadeUntil[1];
  // The organ's figure, always: the moving note, then the E it rocks back
  // to, each held just into the next so the organ never stops sounding. The
  // first of each bar leans a little, and the bar breathes in and out.
  var m = inBar % 2 ? CF_PIVOT : bar.low;
  var vel = 0.55 * (inBar === 0 ? 1.12 : inBar === 4 ? 1.05 : 1) * (0.94 + 0.06 * Math.sin(Math.PI * inBar / 8));
  cfPlay('organ', m, t, dur * 1.04, vel, CF.ost);
  if (melOn) {
    // The pedal holds the bass through the bar.
    if (inBar === 0) cfPlay('pedal', bar.bass - 12, t, dur * 8, 0.13, CF.mel);
    for (var i = 0; i < CF_TUNE.length; i++) {
      if (CF_TUNE[i][1] !== at) continue;
      var len = dur * CF_TUNE[i][2], note = CF_TUNE[i][0];
      cfPlay('organ', note + 12, t, len, 0.1, CF.mel);
      cfPlay('piano', note, t, len, 0.28, CF.mel);
      // In the climax the violins sing it an octave up, the full organ under.
      if (heavyOn) {
        cfPlay('violins', note + 12, t, len + dur * 0.5, 0.26, CF.wideL);
        cfPlay('organ_full', note, t, len, 0.12, CF.heavy);
      }
    }
  }
  if (heavyOn) {
    if (inBar === 0) {
      // The full organ holds the chord, the 16' pedal and the basses the root.
      for (var c = 0; c < bar.chord.length; c++) cfPlay('organ_full', bar.chord[c], t, dur * 8, 0.13, CF.heavy);
      cfPlay('pedal_full', bar.bass - 12, t, dur * 8, 0.25, CF.heavy);
      cfPlay('basses', bar.bass - 12, t, dur * 8, 0.22, CF.heavy);
    }
    // The cellos, a half note each half bar.
    if (inBar % 4 === 0) cfPlay('cellos', CF_CELLOS[(b * 2 + inBar / 4) % CF_CELLOS.length], t, dur * 4.2, 0.22, CF.wideL);
    // The piano doubles the organ's figure an octave up.
    cfPlay('piano', m + 12, t, dur, 0.14, CF.wideR);
  }
}

/* ---------- what app/orb_sound.js calls ------------------------------- */

// Started with the rest of the orb's sound: the layers built, the samples
// asked for if they are not here yet, the figure in at once and the rest
// where the work already is.
function cfStart(ctx, music, notes, urls) {
  if (urls) CF.urls = urls;
  cfGraph(ctx, music, notes);
  cfLoad(ctx);
  var t = ctx.currentTime;
  CF.stepAt = t + 0.08;
  CF.lastT = t;
  CF.lean = 0;
  CF.speed = 1;
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
  CF.lean *= Math.exp(-dt / CF_LEAN_DECAY_S);
  CF.speed += (1 + CF.lean - CF.speed) * (1 - Math.exp(-dt / CF_TEMPO_GLIDE_S));
  var lv = cfLevelNow(wall);
  if (lv !== CF.level) { CF.level = lv; CF.levelAt = wall; cfLayers(t); }
  // A speaker the browser still holds back has a stopped clock: nothing is
  // put on it, and the figure starts from the press that lets it out.
  if (ctx.state !== 'running') { CF.stepAt = t + 0.08; return; }
  if (CF.stepAt < t) CF.stepAt = t + 0.02;
  while (CF.stepAt < t + CF_AHEAD) {
    var dur = CF_EIGHTH / CF.speed;
    cfStep(CF.step, CF.stepAt, dur);
    CF.step++;
    CF.stepAt += dur;
  }
  for (var i = CF.voices.length - 1; i >= 0; i--) if (CF.voices[i][1] < t) CF.voices.splice(i, 1);
}

// Something new on the orb: it leans on the tempo, barely.
function cfNudge(voice) {
  CF.lean = Math.min(CF_LEAN_MAX, CF.lean + (voice === 'call' ? CF_LEAN : CF_LEAN * 1.5));
  CF.nudges++;
}

// The notes slider moved: one note of the tune at the new level.
function cfPreview(ctx) {
  if (CF.ctx !== ctx || ctx.state !== 'running') return;
  cfPlay('piano', 76, ctx.currentTime + 0.03, 0.8, 0.28, CF.notes);
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
    tempo: +(CF_TEMPO_BPM * CF.speed).toFixed(2), speed: +CF.speed.toFixed(4), lean: +CF.lean.toFixed(4),
    step: CF.step, played: CF.played, sampled: CF.sampled, nudges: CF.nudges,
    samples: CF.bank ? Object.keys(CF.bank).map(function (k) { return k + ':' + CF.bank[k].length; }).join(' ')
      : CF.failed ? 'failed' : CF.loading ? 'loading' : 'none',
    voices: CF.voices.length,
    gains: CF.ost ? [CF.ost.gain.value, CF.mel.gain.value, CF.heavy.gain.value].map(function (g) { return +g.toFixed(3); }) : []
  };
}

export { cfHush, cfNudge, cfPreview, cfStart, cfState, cfTick };
