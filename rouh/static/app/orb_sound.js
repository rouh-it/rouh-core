/* Rouh's page, the sound of the open orb
 * (out of app/orb.js).
 *
 * Nothing here runs when the module is loaded: app/orb.js calls wireOrbSound()
 * at the place in it where this code used to be, so everything happens in
 * the order it always did.
 */
import { holdAudioSession, makeSpeaker, silentTick } from 'app/playback.js';
import { $, clamp, now } from 'app/helpers.js';
import { load, store } from 'app/settings.js';
import { S } from 'app/socket.js';
import { A } from 'app/voice.js';
import { stillSpeaking } from 'app/transcript.js';
import { speakerNudge } from 'app/attachments.js';
import { ORB_CFG, orbW, ORBX } from 'app/orb.js';

/* ---------- the sound of the open orb ---------------------------------

   Asked for on 24 September 2026 (fr_f3ced3c15b3e): with the orb open over
   the whole screen, every new thing that appears on it makes a short sound,
   the light blue ones one sound and the purple ones another - distinct, but
   belonging together, melodic rather than a scatter of effects, in the
   piano, the violin and the orchestra - and under them some music, very
   quietly.

   The light blue things are the lines: a job out of the core (`ORB_PAL.job`),
   a helper off a job (`agent`), and Rouh's own line while it answers, in
   the core's pale colour. The purple things are the twigs along them, the
   tool calls: a shell command is violet and an edit magenta, and between
   them they are most of the colour a job puts on the screen. Every twig
   sounds, whatever its colour, because every new thing was asked to; they
   are all one kind of thing and sound as one.

     a line      a soft piano note; a job adds the octave under it
     a twig      a violin plucked, pizzicato: shorter, lower and quieter
     underneath  bowed strings holding four slow chords, very quietly

   All of it is in one key. The notes are D major's five-note scale, and the
   four chords underneath (D, B minor, G and A) are built from those same
   five notes, bar the G at the bottom of the G chord, two octaves under the
   notes, where an F sharp over it is only its major seventh. So no note
   ever lands against the music. Each voice walks the scale a step or two
   from its last note rather than jumping anywhere in it, so a run of
   arrivals is a phrase. They wait for the next quarter of a second, so a
   burst of tool calls is a quick run of notes in time rather than a smear;
   past a handful waiting the rest are let go, and the picture still shows
   every one of them.

   Nothing is recorded and nothing is fetched. Every sound is made here in
   Web Audio, out of oscillators and a reverb built from noise, so there is
   no file to find and no licence to hold.

   Only while the orb is open over the whole screen, the page is being
   looked at, and this browser has not been told to be quiet. Opening it
   brings the chords in; what was already on the screen at that moment makes
   no sound, only what arrives afterwards. Closing it, or the tab going out
   of sight, fades all of it out in about half a second and stops it. While
   Rouh is speaking the music and the notes step back under the voice.

   The speaker is the page's one AudioContext (`makeSpeaker`), the one the
   voice plays through, so any press that lets the voice out lets this out
   too, and the press that opens the orb is one. The button beside the cog
   turns it off and on for this browser, because a phone in a meeting is not
   the desk; the cog's panel has the two levels, which are the person's own
   like every other number there. */

var KEY_ORB_SOUND = 'rouh.orb.sound.v1';

var ORB_SOUND = {
  on: false,            // read from the store by wireOrbSound, where it always was
  live: false,          // sounding right now
  whole: false,         // the next tree is everything there already was, not news
  ctx: null,            // the context the graph below belongs to
  master: null, notes: null, music: null, padIn: null, padTone: null, wave: null,
  lfo: null,
  queue: [],            // arrivals waiting for their slot
  slot: 0,              // the context time of the last slot a note took
  timer: 0,
  stopTimer: 0,
  chord: 0,             // the next of the four chords
  chordAt: 0,           // and when it comes in
  pad: [],              // chords still sounding
  walk: { line: -1, call: -1 },
  levels: '',
  played: []            // the last notes, for the checks
};

//: D, E, F sharp, A and B: the five notes every arrival is taken from.
var SOUND_SCALE = [2, 4, 6, 9, 11];

//: The four chords underneath, as MIDI notes, each held eleven seconds:
//: D (6/9), B minor (11), G (6/9) and A with its fourth. Every note in them
//: is one of the five above except the G2 under the G chord.
var SOUND_CHORDS = [
  [50, 57, 59, 64, 66],
  [47, 54, 57, 62, 64],
  [43, 50, 57, 59, 64],
  [45, 52, 57, 59, 62]
];
var CHORD_SECS = 11, CHORD_FADE = 5;

//: Arrivals land on a grid a quarter of a second apart, one to a slot.
var SOUND_SLOT = 0.25;
//: How many may wait for a slot, and for how long, before they are let go.
var SOUND_QUEUE = 6, SOUND_STALE_MS = 1500;

function scaleBetween(lo, hi) {
  var out = [];
  for (var m = lo; m <= hi; m++) if (SOUND_SCALE.indexOf(m % 12) >= 0) out.push(m);
  return out;
}
// The piano from E4 to D6, the plucked strings from A3 to E5: overlapping,
// but each is centred where its instrument sounds best, and the plucks sit
// under the piano.
var LINE_NOTES = scaleBetween(64, 86), CALL_NOTES = scaleBetween(57, 76);

function mtof(m) { return 440 * Math.pow(2, (m - 69) / 12); }

// A slider's per cent, as a gain: squared, so the middle of the slider
// sounds like the middle rather than nearly as loud as the top.
function soundLevel(pct) { var v = clamp((pct || 0) / 100, 0, 1); return v * v; }

// The next note for a voice: a step or two along the scale from its last,
// turning back at either end of its range, now and then the same note again.
function nextNote(voice) {
  var list = voice === 'line' ? LINE_NOTES : CALL_NOTES, at = ORB_SOUND.walk[voice];
  if (at < 0) at = Math.floor(list.length / 2);
  else {
    var steps = [-2, -1, -1, 0, 1, 1, 2], d = steps[Math.floor(Math.random() * steps.length)];
    if (at + d < 0 || at + d >= list.length) d = -d;
    at = clamp(at + d, 0, list.length - 1);
  }
  ORB_SOUND.walk[voice] = at;
  return list[at];
}

// A room for the notes to sound in: stereo noise, darkening and dying away
// over three seconds the way a hall loses its treble first, after a short
// gap before the first reflection.
function soundRoom(ctx, secs) {
  var rate = ctx.sampleRate, n = Math.floor(rate * secs), gap = Math.floor(rate * 0.018);
  var buf = ctx.createBuffer(2, n, rate), c, i, d, lp, k;
  for (c = 0; c < 2; c++) {
    d = buf.getChannelData(c);
    lp = 0;
    for (i = gap; i < n; i++) {
      k = (i - gap) / (n - gap);
      lp += (Math.random() * 2 - 1 - lp) * (0.55 - 0.45 * k);
      d[i] = lp * Math.pow(1 - k, 2.4);
    }
  }
  return buf;
}

// A bowed string's tone for the chords: a sawtooth with its top rounded
// off, so it is strings rather than a buzz.
function soundBow(ctx) {
  var n = 24, re = new Float32Array(n), im = new Float32Array(n);
  for (var k = 1; k < n; k++) im[k] = Math.exp(-k / 6) / k;
  return ctx.createPeriodicWave(re, im);
}

// Everything the notes and the chords go through, built once on the page's
// one context. The master is silent until the orb is open: nothing reaches
// the speaker from here at any other time.
function soundGraph(ctx) {
  var S_ = ORB_SOUND;
  if (S_.ctx === ctx) return true;
  try {
    var master = ctx.createGain();
    master.gain.value = 0;
    master.connect(ctx.destination);
    var room = ctx.createConvolver();
    room.buffer = soundRoom(ctx, 3.2);
    room.connect(master);
    var notes = ctx.createGain(), notesWet = ctx.createGain();
    notes.gain.value = 0;
    notesWet.gain.value = 0.35;
    notes.connect(master);
    notes.connect(notesWet);
    notesWet.connect(room);
    var padIn = ctx.createGain(), padTone = ctx.createBiquadFilter();
    var music = ctx.createGain(), musicWet = ctx.createGain();
    padTone.type = 'lowpass';
    padTone.frequency.value = 1000;
    padTone.Q.value = 0.4;
    music.gain.value = 0;
    musicWet.gain.value = 0.6;
    padIn.connect(padTone);
    padTone.connect(music);
    music.connect(master);
    music.connect(musicWet);
    musicWet.connect(room);
    S_.wave = soundBow(ctx);
    S_.master = master; S_.notes = notes; S_.music = music;
    S_.padIn = padIn; S_.padTone = padTone;
    S_.ctx = ctx;
    return true;
  } catch (e) {
    return false;
  }
}

// A note's own place left or right: where on the screen the thing that
// made it appeared. Anything not drawn yet sits near the middle.
function soundPan(n) {
  var pts = n && n.sp, m = n ? n.pn || 0 : 0;
  if (!pts || m < 1 || !orbW || !pts[m - 1]) return (Math.random() - 0.5) * 0.3;
  return clamp((pts[m - 1].x / orbW) * 2 - 1, -1, 1) * 0.6;
}

function soundOut(ctx, pan) {
  if (!pan || !ctx.createStereoPanner) return ORB_SOUND.notes;
  var p = ctx.createStereoPanner();
  p.pan.value = pan;
  p.connect(ORB_SOUND.notes);
  return p;
}

// A piano note: six partials, stretched a little the way a real string's
// are, struck, falling away quickly at first and then ringing on, the high
// partials dying first and the low notes ringing longest.
function soundPiano(midi, t, vel, pan) {
  var ctx = ORB_SOUND.ctx, f0 = mtof(midi), out = soundOut(ctx, pan);
  var amps = [1, 0.36, 0.17, 0.08, 0.04, 0.02];
  var ring = 1.5 * Math.pow(261.6 / f0, 0.35);
  for (var n = 1; n <= amps.length; n++) {
    var f = f0 * n * Math.sqrt(1 + 0.0004 * n * n);
    if (f > 10000) break;
    var o = ctx.createOscillator(), g = ctx.createGain();
    var a = vel * amps[n - 1] * 0.2, tau = ring / (1 + 0.7 * (n - 1));
    o.frequency.value = f;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(a, t + 0.006);
    g.gain.setTargetAtTime(a * 0.4, t + 0.006, 0.08);
    g.gain.setTargetAtTime(0, t + 0.2, tau * 0.6);
    o.connect(g);
    g.connect(out);
    o.start(t);
    o.stop(t + 0.2 + tau * 3);
  }
}

// A plucked violin string: a bright sawtooth closed down to its body in a
// tenth of a second, with the round thump of the fundamental under it.
function soundPluck(midi, t, vel, pan) {
  var ctx = ORB_SOUND.ctx, f0 = mtof(midi), out = soundOut(ctx, pan);
  var a = vel * 0.15, die = 0.13 * Math.pow(220 / f0, 0.3);
  var o = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
  o.type = 'sawtooth';
  o.frequency.value = f0;
  lp.type = 'lowpass';
  lp.Q.value = 1.8;
  lp.frequency.setValueAtTime(Math.min(f0 * 9, 7000), t);
  lp.frequency.setTargetAtTime(f0 * 1.5, t, 0.05);
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(a, t + 0.003);
  g.gain.setTargetAtTime(0, t + 0.003, die);
  o.connect(lp); lp.connect(g); g.connect(out);
  var s = ctx.createOscillator(), sg = ctx.createGain();
  s.frequency.value = f0;
  sg.gain.setValueAtTime(0, t);
  sg.gain.linearRampToValueAtTime(a * 0.7, t + 0.004);
  sg.gain.setTargetAtTime(0, t + 0.004, die * 1.3);
  s.connect(sg); sg.connect(out);
  o.start(t); s.start(t);
  o.stop(t + 0.1 + die * 6); s.stop(t + 0.1 + die * 8);
}

// One chord underneath: every note two bowed strings a few cents apart,
// coming in over seconds and going out over five, overlapping the next.
function soundChord(i, t, attack) {
  var S_ = ORB_SOUND, ctx = S_.ctx, notes = SOUND_CHORDS[i % SOUND_CHORDS.length];
  var end = t + CHORD_SECS, off = end + CHORD_FADE;
  var v = { oscs: [], gain: ctx.createGain(), off: off };
  v.gain.gain.setValueAtTime(0, t);
  v.gain.gain.setTargetAtTime(1, t, attack / 3);
  v.gain.gain.setTargetAtTime(0, end, CHORD_FADE / 4);
  v.gain.connect(S_.padIn);
  for (var j = 0; j < notes.length; j++) {
    for (var k = 0; k < 2; k++) {
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.setPeriodicWave(S_.wave);
      o.frequency.value = mtof(notes[j]);
      o.detune.value = (k ? 5 : -5) + (Math.random() * 4 - 2);
      g.gain.value = (j === 0 ? 0.07 : 0.045);
      o.connect(g); g.connect(v.gain);
      o.start(t);
      o.stop(off + 0.2);
      v.oscs.push(o);
    }
  }
  S_.pad.push(v);
}

// Keep the next chord ready a second and a half before it is due, and let
// go of the ones that have finished.
function soundChords(t) {
  var S_ = ORB_SOUND, i;
  while (S_.chordAt < t + 1.5) {
    soundChord(S_.chord, S_.chordAt, S_.first ? 2.4 : 5);
    S_.first = false;
    S_.chord = (S_.chord + 1) % SOUND_CHORDS.length;
    S_.chordAt += CHORD_SECS;
  }
  for (i = S_.pad.length - 1; i >= 0; i--) {
    if (S_.pad[i].off + 0.3 < t) {
      try { S_.pad[i].gain.disconnect(); } catch (e) {}
      S_.pad.splice(i, 1);
    }
  }
}

// The two levels, from the cog's sliders, stepped back while Rouh speaks.
// A slider is followed at once; the music comes back up slowly once Rouh
// has finished, rather than jumping in behind the last word. Only written
// when they change: a new automation event every tick would pile up for as
// long as the orb is open.
function soundLevels(t) {
  var S_ = ORB_SOUND;
  var talking = S.state === 'speaking' || stillSpeaking();
  var nv = soundLevel(ORB_CFG.noteVol) * (talking ? 0.55 : 1);
  var mv = soundLevel(ORB_CFG.musicVol) * (talking ? 0.35 : 1);
  var key = nv.toFixed(4) + '/' + mv.toFixed(4) + '/' + talking;
  if (key === S_.levels) return;
  var after = !talking && /\/true$/.test(S_.levels);
  S_.levels = key;
  S_.notes.gain.setTargetAtTime(nv, t, 0.08);
  S_.music.gain.setTargetAtTime(mv, t, after ? 0.8 : 0.1);
}

function soundPlay(item, t) {
  var vel = 0.8 + Math.random() * 0.2, pan = soundPan(item.node), m;
  if (item.voice === 'line') {
    m = nextNote('line');
    if (item.kind === 'self') vel *= 0.75;
    soundPiano(m, t, vel, pan);
    if (item.kind === 'worker') soundPiano(m - 12, t, vel * 0.5, pan);
  } else {
    m = nextNote('call');
    soundPluck(m, t, vel, pan);
  }
  ORB_SOUND.played.push({ voice: item.voice, kind: item.kind, midi: m, at: t });
  if (ORB_SOUND.played.length > 60) ORB_SOUND.played.shift();
}

// Every sixty milliseconds while it is sounding: the chords kept ahead, the
// levels followed, and whatever has arrived put on the next free slot. A
// quarter of a second is the most a note is ever scheduled ahead, so
// closing the orb never has a queue of them still to come out.
function soundTick() {
  var S_ = ORB_SOUND, ctx = S_.ctx;
  if (!S_.live || !ctx) return;
  var t = ctx.currentTime, wall = performance.now();
  soundChords(t);
  soundLevels(t);
  // A speaker the browser is still holding back has a clock that is not
  // moving: notes put on it would all come out at once at the first press.
  // The chord already waiting is what that press should bring in; arrivals
  // until then are let go, as they would be past a handful.
  if (ctx.state !== 'running') { S_.queue.length = 0; return; }
  while (S_.queue.length && wall - S_.queue[0].seen > SOUND_STALE_MS) S_.queue.shift();
  while (S_.queue.length) {
    var slot = Math.max(S_.slot + SOUND_SLOT, Math.ceil((t + 0.04) / SOUND_SLOT) * SOUND_SLOT);
    if (slot > t + 0.3) break;
    S_.slot = slot;
    soundPlay(S_.queue.shift(), slot);
  }
}

// New things on the orb, from the tree or from Rouh starting on an answer.
// Found already finished and faint - the end of something that was over
// before this page saw it - is not an arrival.
function orbSoundArrived(nodes) {
  var S_ = ORB_SOUND;
  if (!S_.live || S_.whole) return;
  var t = now(), wall = performance.now(), i, n;
  for (i = 0; i < nodes.length; i++) {
    n = nodes[i];
    if (!n || (n.fade && t - n.fade > 1200)) continue;
    S_.queue.push({ voice: n.kind === 'tool' ? 'call' : 'line', kind: n.kind, node: n, seen: wall });
  }
  // Too many at once: the lines are kept before the twigs, and the oldest
  // twig goes first.
  while (S_.queue.length > SOUND_QUEUE) {
    for (i = 0; i < S_.queue.length && S_.queue[i].voice !== 'call'; i++) {}
    S_.queue.splice(i < S_.queue.length ? i : 0, 1);
  }
}

function orbSoundWanted() {
  return ORB_SOUND.on && ORBX.open && !document.hidden;
}

function orbSoundSync() {
  if (orbSoundWanted()) orbSoundStart(); else orbSoundStop();
}

function orbSoundStart() {
  var S_ = ORB_SOUND;
  if (S_.live) return;
  // The context is the voice's. Made inside the press that opened the orb
  // it starts at once; opened by the voice, the next press anywhere starts
  // it (`orbSoundPress`), and nothing is held back until then.
  holdAudioSession();
  if (!makeSpeaker() || !soundGraph(A.ctx)) return;
  silentTick();
  speakerNudge();
  // Opened again while the last closing was still fading: that one is cut
  // off here, so two sets of chords never overlap.
  if (S_.stopTimer) { clearTimeout(S_.stopTimer); S_.stopTimer = 0; soundHush(); }
  var ctx = S_.ctx, t = ctx.currentTime;
  S_.live = true;
  S_.queue.length = 0;
  S_.slot = 0;
  S_.levels = '';
  S_.master.gain.cancelScheduledValues(t);
  S_.master.gain.setValueAtTime(S_.master.gain.value, t);
  S_.master.gain.setTargetAtTime(1, t, 0.05);
  // The chords breathe: the strings open and close a little over a quarter
  // of a minute, so the same chord held is never quite still.
  try {
    S_.lfo = ctx.createOscillator();
    var depth = ctx.createGain();
    S_.lfo.frequency.value = 0.045;
    depth.gain.value = 320;
    S_.lfo.connect(depth);
    depth.connect(S_.padTone.frequency);
    S_.lfo.start(t);
  } catch (e) { S_.lfo = null; }
  S_.chordAt = t + 0.05;
  S_.first = true;
  soundTick();
  S_.timer = setInterval(soundTick, 60);
}

function orbSoundStop() {
  var S_ = ORB_SOUND;
  if (!S_.live) return;
  S_.live = false;
  clearInterval(S_.timer);
  S_.timer = 0;
  S_.queue.length = 0;
  var t = S_.ctx.currentTime;
  S_.master.gain.cancelScheduledValues(t);
  S_.master.gain.setValueAtTime(S_.master.gain.value, t);
  S_.master.gain.setTargetAtTime(0, t, 0.1);
  S_.stopTimer = setTimeout(function () { S_.stopTimer = 0; soundHush(); }, 700);
}

// Everything still sounding, stopped outright once it can no longer be heard.
function soundHush() {
  var S_ = ORB_SOUND, t = S_.ctx ? S_.ctx.currentTime : 0, i, j;
  for (i = 0; i < S_.pad.length; i++) {
    for (j = 0; j < S_.pad[i].oscs.length; j++) {
      try { S_.pad[i].oscs[j].stop(t); } catch (e) {}
    }
    try { S_.pad[i].gain.disconnect(); } catch (e) {}
  }
  S_.pad.length = 0;
  if (S_.lfo) {
    try { S_.lfo.stop(t); S_.lfo.disconnect(); } catch (e) {}
    S_.lfo = null;
  }
}

// A press while it is sounding is permission the browser may still have
// been waiting for: the orb opened by the voice, with no press yet.
function orbSoundPress() {
  if (!ORB_SOUND.live || !A.ctx || A.ctx.state === 'running') return;
  holdAudioSession();
  silentTick();
  speakerNudge();
}

// The notes slider moved: one note at the new level, so it is heard rather
// than guessed at. At most one waiting at a time, however fast the drag.
function orbSoundPreview() {
  var S_ = ORB_SOUND;
  if (!S_.live || S_.queue.length) return;
  S_.queue.push({ voice: 'call', kind: 'preview', node: null, seen: performance.now() });
}

function orbSoundPaint() {
  var b = $('orbSound');
  if (!b) return;
  b.setAttribute('aria-pressed', ORB_SOUND.on ? 'true' : 'false');
  b.title = ORB_SOUND.on ? 'Sound on: a note for everything new, and quiet music. Press to turn it off'
    : 'Sound off. Press to hear a note for everything new, and quiet music';
}

// Wired from app/orb.js, at the place in it where this code always ran.
// Whether it is on is read from the store first, as it was where
// ORB_SOUND was made.
function wireOrbSound() {
  ORB_SOUND.on = load(KEY_ORB_SOUND) !== '0';
  var b = $('orbSound');
  if (!b) return;
  orbSoundPaint();
  b.addEventListener('click', function () {
    ORB_SOUND.on = !ORB_SOUND.on;
    store(KEY_ORB_SOUND, ORB_SOUND.on ? '1' : '0');
    orbSoundPaint();
    orbSoundSync();
  });
  ['pointerdown', 'touchend', 'keydown', 'click'].forEach(function (kind) {
    document.addEventListener(kind, orbSoundPress, true);
  });
  document.addEventListener('visibilitychange', orbSoundSync);
  // Another tab of this browser turning it off turns it off here too.
  window.addEventListener('storage', function (e) {
    if (!e || e.key !== KEY_ORB_SOUND) return;
    ORB_SOUND.on = load(KEY_ORB_SOUND) !== '0';
    orbSoundPaint();
    orbSoundSync();
  });
}

export { ORB_SOUND, orbSoundArrived, orbSoundPreview, orbSoundSync, wireOrbSound };
