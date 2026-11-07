/* Rouh's page, the voice detector, and the one place the microphone is opened (section 5 of what was one app.js).
 *
 * Imports app/socket.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { S, send, sendBinary } from 'app/socket.js';
import { $, now } from 'app/helpers.js';
import { BARGE_MULTIPLIER, cfg, FRAME_MS, FRAME_SAMPLES, MAX_UTTERANCE_MS, MIN_FLOOR,
  OPEN_FRAMES } from 'app/settings.js';
import { pbEnsure, pbFlush, speakerReady, stopPlayback } from 'app/playback.js';
import { setState } from 'app/orb.js';
import { closeAssistant, T } from 'app/transcript.js';
import { freshChatFirst } from 'app/address.js';
import { setMic } from 'app/controls.js';

/* ------------------------------------------------------------------ 5 */

var A = {
  ctx: null,
  //: A microphone has been opened at some point in this visit. Not the same
  //: thing as having an AudioContext: a speaker is made on demand when a
  //: reply arrives (`speakerArmed`) and opens no device, while a microphone
  //: is only ever opened by somebody asking for one. It is here so that
  //: "there is a speaker running but nobody has ever listened" can be told
  //: apart from "the voice is in use", which is what the readout says.
  woken: false,
  //: A voice note being recorded for when there is no connection
  //: (app/offlineview.js): every frame from the microphone is kept here, and
  //: none of it is sent or heard as speech while it is.
  note: /** @type {Int16Array[]|null} */ (null),
  stream: null,
  track: null,
  node: null,
  source: null,
  sink: null,
  ring: [],
  hist: new Float32Array(150),   // 3 s of RMS at 20 ms a frame
  histN: 0,
  histI: 0,
  scratch: new Float32Array(150),
  floor: MIN_FLOOR,
  level: 0,
  utterance: false,
  held: false,          // dictation is holding the turn open
  vad: null,            // the Silero module, once it has loaded
  vadP: 0,              // latest probability that what we are hearing is speech
  vadBuf: null,         // samples waiting to make up a whole model frame
  vadFill: 0,
  openCount: 0,
  quietSince: 0,
  startedAt: 0
};

var debug = {
  micFrames: 0, maxRms: 0,
  sentFrames: 0, prerollFrames: 0, utterances: 0, ready: 0,
  audioChunks: 0, audioBuffers: 0, audioSeconds: 0, audioDropped: 0, interrupts: 0,
  //: Chunks thrown away because the browser would not let this page make a
  //: sound, counted apart from the ones dropped on purpose after an
  //: interruption. It is the number that means "the person was owed speech
  //: and did not get it", so it is the one shown on screen.
  audioBlocked: 0,
  //: Times the tail-drop after an interruption was let go of because no
  //: `audio_start` ever came to end it. Non-zero means a start message was
  //: lost; the voice kept working, which is the point of counting it.
  dropLatchReleased: 0
};

function preRollFrames() { return Math.round(cfg.preRollMs / FRAME_MS) + 1; }

function pushHist(rms) {
  A.hist[A.histI] = rms;
  A.histI = (A.histI + 1) % A.hist.length;
  if (A.histN < A.hist.length) A.histN++;
}

// Listen to the room before listening for speech.
//
// Steady background sound - a dryer, a fan, air conditioning - is easy to
// ignore once the floor has risen to meet it, because a voice is far louder.
// The trouble is getting there. The floor starts near silence and creeps up
// at 2% a frame, so for the first several seconds of a session a steady hum
// sits far above it and reads as speech. That is what opened the microphone
// every few seconds in a room with a dryer running.
//
// So the first CALIBRATE_FRAMES are spent measuring and nothing else: no
// utterance can start, and the floor is set to what the room actually sounds
// like. After that the tracker takes over.
var CALIBRATE_FRAMES = 40;   // 0.8 s

// Silero answers "is this speech", between 0 and 1. Two thresholds rather
// than one so a probability hovering around the middle cannot chatter the
// microphone open and shut.
var VAD_OPEN = 0.5;
var VAD_CLOSE = 0.35;
// Talking over Rouh has to be meant, because his own voice leaks into the
// microphone and scores well above zero.
var VAD_BARGE_IN = 0.85;

function updateFloor() {
  var n = A.histN, i;
  if (n < 12) { A.floor = Math.max(A.floor, MIN_FLOOR); return; }
  for (i = 0; i < n; i++) A.scratch[i] = A.hist[i];
  var s = A.scratch.subarray(0, n);
  s.sort(function (a, b) { return a - b; });
  var p20 = s[Math.floor(n * 0.2)];

  if (debug.micFrames <= CALIBRATE_FRAMES) {
    // Still measuring: take the room at its word rather than easing towards it.
    A.floor = Math.max(p20, MIN_FLOOR);
    return;
  }

  // Falls quickly when the room goes quiet. Rises more slowly, but fast enough
  // to catch a dryer that starts mid-conversation within a couple of seconds.
  if (p20 < A.floor) A.floor += (p20 - A.floor) * 0.35;
  else if (!A.utterance) A.floor += (p20 - A.floor) * 0.06;
  A.floor = Math.max(A.floor, MIN_FLOOR);
}

function openThreshold() {
  var m = S.state === 'speaking' ? BARGE_MULTIPLIER : 1;
  return A.floor * cfg.openRatio * m;
}

function loadVad() {
  if (A.vad) return;
  import('../vad.js').then(function (mod) {
    return mod.load().then(function () {
      A.vad = mod;
      setVadBadge('speech detection on');
      debug.vadLoaded = true;
    });
  }).catch(function (err) {
    // Not fatal. The loudness detector stays in charge and everything works,
    // it is just easier to fool in a noisy room.
    setVadBadge('loudness only');
    console.warn('speech detection unavailable:', err && err.message);
  });
}

function setVadBadge(textValue) {
  var el = $('roDetector');
  if (el) el.textContent = textValue;
}

function feedVad(pcm) {
  // The worklet hands over 20 ms of Int16; the model wants 512 float samples,
  // which is 32 ms. Accumulate, and never wait for the answer: a frame is
  // dropped rather than queued if inference is still running, because being
  // one frame behind is invisible and a backlog is not.
  var v = A.vad;
  if (!v || !v.ready()) return;
  if (!A.vadBuf) { A.vadBuf = new Float32Array(v.frameSize); A.vadFill = 0; }
  for (var i = 0; i < pcm.length; i++) {
    A.vadBuf[A.vadFill++] = pcm[i] / 32768;
    if (A.vadFill === v.frameSize) {
      var frame = A.vadBuf.slice(0);
      A.vadFill = 0;
      v.probability(frame).then(function (p) {
        if (p !== null && p !== undefined) A.vadP = p;
      }).catch(function () { /* one bad frame is not worth reporting */ });
    }
  }
}

function speechNow(rms) {
  // Silero when it is loaded, loudness when it is not. The loudness rule is
  // kept because the page must work in the second before the model arrives,
  // and if it never arrives at all.
  if (A.vad && A.vad.ready()) {
    var open = S.state === 'speaking' ? VAD_BARGE_IN : VAD_OPEN;
    return A.utterance ? A.vadP > VAD_CLOSE : A.vadP > open;
  }
  return A.utterance ? rms > A.floor * cfg.closeRatio : rms > openThreshold();
}

function onMicFrame(pcm, rms) {
  debug.micFrames++;
  feedVad(pcm);
  if (rms > debug.maxRms) debug.maxRms = rms;
  A.level = Math.max(rms, A.level * 0.80);
  pushHist(rms);
  updateFloor();

  A.ring.push(pcm);
  var cap = preRollFrames();
  while (A.ring.length > cap) A.ring.shift();

  if (A.note) { A.note.push(pcm); return; }
  if (S.muted || !S.micReady) return;

  // Nothing counts as speech until the room has been measured. Dictation
  // is exempt: that is a person saying they are talking now.
  if (debug.micFrames <= CALIBRATE_FRAMES && !A.held) return;

  var t = now();
  if (!A.utterance) {
    if (A.held) { beginUtterance(); return; }
    if (speechNow(rms)) {
      A.openCount++;
      if (A.openCount >= OPEN_FRAMES) beginUtterance();
    } else {
      A.openCount = 0;
    }
    return;
  }

  sendBinary(pcm.buffer);

  if (speechNow(rms)) A.quietSince = 0;
  else if (!A.quietSince) A.quietSince = t;

  // While dictation is on the person decides when the turn ends, not the
  // detector. Only the hard cap still applies.
  if (A.held) { if (t - A.startedAt >= MAX_UTTERANCE_MS) endUtterance('cap'); return; }
  if (A.quietSince && t - A.quietSince >= cfg.silenceMs) endUtterance('silence');
  else if (t - A.startedAt >= MAX_UTTERANCE_MS) endUtterance('cap');
}

function beginUtterance() {
  // A microphone left open from before the page went back to the front door
  // (`frontDoorGo`): the same rule as opening one, so the words cannot land
  // in the conversation the person walked away from (see 10g).
  freshChatFirst(null);
  A.utterance = true;
  A.openCount = 0;
  A.quietSince = 0;
  A.startedAt = now();
  T.typed = null;
  debug.utterances++;

  if (S.state === 'speaking') {
    // Barge-in: kill what is queued before anything else, then tell the server.
    stopPlayback();
    send({ type: 'interrupt' });
    closeAssistant();
    debug.interrupts++;
  }

  setState('listening');
  send({ type: 'speech_start' });

  for (var i = 0; i < A.ring.length; i++) {
    if (sendBinary(A.ring[i].buffer) && i < A.ring.length - 1) debug.prerollFrames++;
  }
}

// Below this an utterance is a click or a knock, not a word. Deliberately low:
// "yes" and "stop" are around 300 ms and must survive. It is not what stops a
// noisy room - the dryer that caused all this produced bursts of one to two
// seconds, far longer than any threshold could reject. The thing that makes
// noise harmless is that it no longer cancels a reply; this only saves a
// pointless round trip for a knock on the desk.
var MIN_UTTERANCE_MS = 220;

function endUtterance(why, silent) {
  if (!A.utterance) return;
  var lasted = now() - A.startedAt;
  A.utterance = false;
  A.openCount = 0;
  A.quietSince = 0;
  if (!silent) {
    if (lasted < MIN_UTTERANCE_MS && why !== 'released') {
      // Too short to be anything said. Tell the server to forget the audio
      // rather than transcribe it. Dictation is exempt: if a person said
      // they were talking, they meant it.
      debug.tooShort = (debug.tooShort || 0) + 1;
      send({ type: 'speech_end', discard: true });
      if (S.state === 'listening') setState('idle');
      return;
    }
    // `released` is the Finish button: the person has said they are done,
    // so the whole of what they have said is answered rather than judged
    // for whether they had finished (rouh/turnmarks.py).
    send({ type: 'speech_end', finish: why === 'released' });
    setState('thinking');
  }
}

/* ---------- the one place the microphone is opened and closed ----------

   There are exactly two functions in this file that touch a MediaStream:
   `acquireMic` opens one and `releaseMic` ends one. Nothing else anywhere
   may call getUserMedia, keep a stream of its own, or try to quieten a
   microphone by other means.

   That is not tidiness. A microphone is open or it is not, and every
   operating system tells its owner which: iOS lights an orange dot in the
   status bar, macOS a dot in the menu bar, Android a chip at the top of the
   screen. `track.enabled = false` does not turn any of them off, because the
   track is still open - the browser is still holding the device and merely
   handing out silence. Rouh used to do exactly that: it opened the
   microphone the moment the voice was woken and then "muted" it by flipping
   `enabled`, so an iPhone showed the orange dot for the whole visit even
   though nobody was listening. That is the bug this section exists to make
   impossible.

   So the rules are:

     * nothing opens the microphone on load, and nothing opens it early "so
       it is ready". `acquireMic` is called from the microphone button and
       from Dictate, and from nowhere else;
     * turning it off ends every track, drops every node and forgets the
       stream, which is what puts the indicator out;
     * turning it on again asks the browser afresh. On iOS that may show the
       permission prompt again, and being asked is the honest cost of not
       being listened to in between.

   The speaker is a separate thing and is dealt with in the next section. It
   opens no device, so it does not belong to any of this. */

function withTimeout(p, ms, message) {
  return new Promise(function (resolve, reject) {
    var done = false;
    var t = setTimeout(function () { if (!done) { done = true; reject(new Error(message)); } }, ms);
    p.then(function (v) { if (!done) { done = true; clearTimeout(t); resolve(v); } },
      function (e) { if (!done) { done = true; clearTimeout(t); reject(e); } });
  });
}

//: The microphone as this page holds it. `gen` counts openings: an open that
//: is still half finished when the microphone is turned off again belongs to
//: an older generation and throws its own stream away rather than installing
//: it, which is what stops a quick on-off-on leaving a track behind.
var MIC = { opening: null, gen: 0 };

function stopStream(stream) {
  if (!stream) return;
  var tracks;
  try { tracks = stream.getTracks(); } catch (e) { return; }
  for (var i = 0; i < tracks.length; i++) {
    try { tracks[i].stop(); } catch (e) {}
  }
}

// The AudioContext the worklet needs, made and resumed. This is only ever
// called from inside a real press, which is the one moment a browser will
// start one. It opens no device; see `speakerArmed` for the other caller's
// side of the same context.
function audioUnlock() {
  var Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return Promise.reject(new Error('this browser has no Web Audio support'));
  if (!A.ctx) A.ctx = new Ctx();
  var resumed = A.ctx.state === 'suspended' ? A.ctx.resume() : Promise.resolve();
  return resumed.catch(function () { /* the press below is what starts it */ })
    .then(function () {
      // A press is a press: whatever the speaker was refused a moment ago
      // can be played now.
      pbEnsure();
      if (A.ctx.state === 'running') { speakerReady(); pbFlush(false); }
    });
}

function acquireMic() {
  if (S.micReady) return Promise.resolve();
  if (MIC.opening) return MIC.opening;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return Promise.reject(new Error('this browser has no microphone access'));
  }
  // Opening a microphone at the front door is somebody about to speak, so
  // the conversation to speak into is asked for now rather than when the
  // first word lands. Nothing here waits for it: the server takes what one
  // socket sends in the order it was sent, so the chat is open before any
  // speech reaches it, and a permission prompt never sits in front of an
  // audio context being unlocked inside the press that opened it (10g).
  freshChatFirst(null);
  var gen = ++MIC.gen;
  var stale = function () { return gen !== MIC.gen; };
  var gaveUp = false;

  MIC.opening = audioUnlock().then(function () {
    if (stale()) return null;
    var asking = navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1
      }
    });
    // A permission prompt the operating system never answers leaves
    // getUserMedia pending for ever, which would look like the page had
    // simply stopped. So the wait gives up - and then, if the prompt is
    // answered half an hour later, a microphone nobody is expecting opens
    // behind everybody's back. This ends that one on arrival.
    asking.then(function (late) {
      if (gaveUp || stale()) stopStream(late);
    }, function () { /* a refusal is reported by the wait below */ });
    return withTimeout(asking, 12000, 'the microphone did not answer')
      .catch(function (err) { gaveUp = true; throw err; });
  }).then(function (stream) {
    if (!stream) return null;
    // Turned off again while the browser was still deciding: this stream is
    // nobody's, so it is ended here rather than installed.
    if (stale()) { stopStream(stream); return null; }
    loadVad();
    return A.ctx.audioWorklet.addModule('mic-worklet.js').then(function () {
      if (stale()) { stopStream(stream); return null; }
      return stream;
    }, function (err) { stopStream(stream); throw err; });
  }).then(function (stream) {
    if (!stream) return;
    A.stream = stream;
    A.track = stream.getAudioTracks()[0];
    // A device unplugged, or iOS taking the microphone back for a phone
    // call, ends the track without telling anybody. Tidy up rather than sit
    // on a dead graph pretending to listen.
    if (A.track) {
      A.track.addEventListener('ended', function () {
        if (A.stream === stream) setMic(true);
      });
    }
    A.source = A.ctx.createMediaStreamSource(stream);
    A.node = new AudioWorkletNode(A.ctx, 'mic-processor', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { targetRate: 16000, frameSamples: FRAME_SAMPLES }
    });
    A.node.port.onmessage = function (e) {
      var d = e.data;
      if (!d || !d.pcm) return;
      onMicFrame(new Int16Array(d.pcm), d.rms || 0);
    };
    // The graph only pulls nodes that reach the destination, so the worklet hangs
    // off a silent gain. Without this its process() is never called at all.
    A.sink = A.ctx.createGain();
    A.sink.gain.value = 0;
    A.source.connect(A.node);
    A.node.connect(A.sink);
    A.sink.connect(A.ctx.destination);
    // The room has not been measured yet: this is a new microphone, and it
    // may not be in the room the last one was in.
    debug.micFrames = 0;
    A.floor = MIN_FLOOR;
    A.histN = 0; A.histI = 0;
    S.micReady = true;
    A.woken = true;
    $('meter').classList.add('armed');
  });

  // A failure that belongs to an opening nobody wants any more is not worth
  // telling anybody about: somebody pressed off while it was asking, which
  // is the answer they were going to get anyway.
  MIC.opening = MIC.opening.catch(function (err) {
    if (stale()) return;
    throw err;
  });

  var settle = function () { if (gen === MIC.gen) MIC.opening = null; };
  MIC.opening.then(settle, settle);
  return MIC.opening;
}

function releaseMic() {
  // Anything still opening belongs to a generation nobody wants now.
  MIC.gen++;
  MIC.opening = null;
  S.micReady = false;
  // Dictation is what holds a turn open, and a turn cannot be held open on
  // a microphone that has just been closed.
  A.held = false;
  endUtterance('stop', true);
  try { if (A.node) A.node.port.postMessage('stop'); } catch (e) {}
  try { if (A.node) A.node.port.onmessage = null; } catch (e) {}
  try { if (A.source) A.source.disconnect(); } catch (e) {}
  try { if (A.node) A.node.disconnect(); } catch (e) {}
  try { if (A.sink) A.sink.disconnect(); } catch (e) {}
  stopStream(A.stream);
  A.node = null; A.source = null; A.sink = null; A.stream = null; A.track = null;
  A.ring.length = 0;
  A.vadBuf = null; A.vadFill = 0; A.level = 0;
  var meter = $('meter');
  if (meter) meter.classList.remove('armed');
}

// Nothing is left holding the device when the page goes away, including the
// page put into the back-forward cache, which `beforeunload` alone misses.
window.addEventListener('pagehide', releaseMic);
window.addEventListener('beforeunload', releaseMic);

export { A, acquireMic, beginUtterance, debug, endUtterance, MIC, openThreshold, releaseMic };
