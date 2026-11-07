/* Rouh's page, playback scheduler (section 6 of what was one app.js).
 *
 * Imports app/voice.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { A, debug } from 'app/voice.js';
import { $, now } from 'app/helpers.js';
import { cfg } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { S } from 'app/socket.js';
import { setState } from 'app/orb.js';
import { noteTurnSign, showStop } from 'app/transcript.js';
import { ADDR } from 'app/address.js';
import { micSays } from 'app/controls.js';

/* ------------------------------------------------------------------ 6 */

var PB = {
  gain: null,
  analyser: null,
  analyserBuf: null,
  rate: 24000,
  next: 0,
  sources: [],
  pending: [],
  pendingBytes: 0,
  leftover: null,
  timer: null,
  turn: null,
  //: When the tail of an interrupted reply stops being dropped, as a clock
  //: reading rather than a flag. A flag was fail-silent: `stopPlayback` set
  //: it and only an `audio_start` cleared it, so one lost start message, or
  //: a socket that died between the interrupt and the next reply, left every
  //: chunk for the rest of the visit being thrown away with nothing on the
  //: screen to say why. A deadline cannot get stuck: the worst a lost
  //: message costs now is the fraction of a second in TAIL_MS.
  dropTailUntil: 0
};

//: How long after an interruption the reply that was cut off may still be
//: arriving. The server stops sending the moment it hears the interrupt, so
//: this only has to cover what was already in flight, and anything still
//: coming after it is a new reply that deserves to be heard.
var TAIL_MS = 1500;

//: Bytes of audio to hold while the speaker is waiting to be allowed to
//: start. A browser hands back a running AudioContext within a tick of being
//: asked, so for the ordinary reply this is only "a reply may begin a moment
//: late". For a tab nobody has pressed it is the whole reply: the sound is
//: let out by the first click, tap or key anywhere on the page, and that
//: press can be a while coming. Holding two seconds of it would start the
//: person in the middle of a sentence and call that delivered. A minute is
//: longer than anything Rouh says in one turn and 2.9 MB of PCM is not
//: worth being careful about, so a minute is what is kept. It is still a cap
//: and not a queue: past it the oldest goes and is counted as lost.
function pbHoldCap() { return PB.rate * 2 * 60; }   // a minute, PCM16 mono

function pbEnsure() {
  if (PB.gain || !A.ctx) return;
  PB.gain = A.ctx.createGain();
  PB.analyser = A.ctx.createAnalyser();
  PB.analyser.fftSize = 256;
  PB.analyser.smoothingTimeConstant = 0.5;
  PB.analyserBuf = new Uint8Array(PB.analyser.fftSize);
  PB.gain.connect(PB.analyser);
  PB.analyser.connect(A.ctx.destination);
}

/* ---------- arming the speaker ---------------------------------------

   Until "no splash screen, and the orb is the press that wakes the voice"
   the AudioContext was made behind the Start button, so by the time a reply
   arrived there always was one. There was no Start button after that, and
   the one press the page collected went to the orb - so a person who typed
   their question and never touched the orb had no AudioContext at all, and
   every chunk of the answer was thrown away at the top of `onAudioChunk`
   with nothing on the screen to say so. The voice button still said "Voice
   replies on", and it was telling the truth.

   A speaker does not need a press of its own. An AudioContext can be
   constructed at any moment; whether it is allowed to run is the browser's
   autoplay rule, and every browser answers that with "has this page been
   clicked, tapped or typed into at any point in this visit". Someone who
   typed the question has, so the answer plays with nothing more asked of
   them. A page that was reloaded and not touched since has not, and that is
   the one case where the person has to be told - which is what the notice
   and the microphone button do below.

   A microphone is the other thing entirely, and `acquireMic` above is the
   only thing that opens one. */

var SPK = {
  //: The notice put up when the browser refused, so it can be taken down
  //: again the moment a word is actually played.
  note: null,
  //: The person has been told. Said once per refusal and not once per chunk,
  //: and only unsaid by a word actually being played.
  told: false,
  //: A resume is already in flight; asking again would only stack timers.
  resuming: false,
  //: A press has been taken as permission at some point in this visit, so
  //: the speaker has been built and started from inside one.
  unlocked: false,
  //: The silent element that holds an audio session open on iOS. See
  //: `holdAudioSession`.
  session: null
};

var NEEDS_A_PRESS =
  'Rouh is speaking, but this browser will not play sound until the page ' +
  'has been touched. Press the microphone button in the composer, or click ' +
  'anywhere on the page, to let the voice through.';

//: Every browser on an iPhone or an iPad, whatever its name on the App
//: Store, because iOS gives them all the same WebKit. iPadOS calls itself a
//: Mac and is told apart by having a touchscreen, which no Mac has.
function anIPhone() {
  var ua = navigator.userAgent || '';
  if (/iPhone|iPad|iPod/.test(ua)) return true;
  return /Mac/.test(ua) && (navigator.maxTouchPoints || 0) > 1;
}

//: A second of silence as a real file, built here rather than pasted in as
//: twenty kilobytes of base64. PCM16 mono at 8 kHz: a WAV header and then
//: zeroes, which every browser decodes and none of them can be heard.
function silenceUrl() {
  var rate = 8000, n = rate, bytes = 44 + n * 2;
  var buf = new ArrayBuffer(bytes), v = new DataView(buf), i = 0;
  function str(s) { for (var k = 0; k < s.length; k++) v.setUint8(i++, s.charCodeAt(k)); }
  function u32(x) { v.setUint32(i, x, true); i += 4; }
  function u16(x) { v.setUint16(i, x, true); i += 2; }
  str('RIFF'); u32(bytes - 8); str('WAVE');
  str('fmt '); u32(16); u16(1); u16(1); u32(rate); u32(rate * 2); u16(2); u16(16);
  str('data'); u32(n * 2);      // and the samples themselves are already zero
  return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
}

/* Holding the audio session open, which is the whole of the mute switch.

   Web Audio on iOS plays into an audio session the Ring/Silent switch
   silences. An HTMLMediaElement plays into one it does not. So on a phone
   with that switch on - which is where a great many phones live all day -
   every number on this page can be right, the context running, the buffers
   scheduled, the analyser moving, and nothing comes out of the phone. There
   is nothing to catch and nothing to report: it is simply quiet.

   A silent element looping for the visit puts the page in the second kind of
   session, and the voice is heard with the switch where it was. It is
   started by the same press that starts the speaker, because a browser will
   not start one of these outside a press either.

   Only on iOS. Elsewhere it buys nothing and costs something real: a browser
   that is playing a media element says so on the tab and in the system's own
   volume mixer, and a page that appears to be playing something for ever
   when Rouh is saying nothing is worse than the problem. */
function holdAudioSession() {
  if (!anIPhone()) return;
  if (!SPK.session) {
    var el = document.createElement('audio');
    el.id = 'audioSession';
    el.loop = true;
    el.preload = 'auto';
    // Inline, or iOS is entitled to take the whole screen to play it.
    /** @type {any} */ (el).playsInline = true;
    el.setAttribute('playsinline', '');
    el.setAttribute('webkit-playsinline', '');
    el.setAttribute('aria-hidden', 'true');
    el.style.display = 'none';
    el.src = silenceUrl();
    document.body.appendChild(el);
    SPK.session = el;
  }
  if (SPK.session.paused) {
    var p = SPK.session.play();
    if (p && p.catch) p.catch(function () {});
  }
}

//: The oldest unlock there is: a buffer of one silent sample played on the
//: context itself. WebKit counts it as the page having used the speaker
//: inside a press, which is what it wants before it will let anything else
//: through. Inaudible, and free.
function silentTick() {
  if (!A.ctx) return;
  try {
    var b = A.ctx.createBuffer(1, 1, A.ctx.sampleRate);
    var s = A.ctx.createBufferSource();
    s.buffer = b;
    s.connect(A.ctx.destination);
    s.start(0);
  } catch (e) {}
}

//: Build the speaker. Says whether there is one afterwards.
function makeSpeaker() {
  if (A.ctx) return true;
  var Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) {
    speakerBlocked('This browser has no Web Audio support, so Rouh cannot be heard here. What he says is still written out.');
    return false;
  }
  try { A.ctx = new Ctx(); } catch (e) {
    speakerBlocked('This browser would not open a speaker, so Rouh cannot be heard. What he says is still written out.');
    return false;
  }
  // However it comes to start - a press caught below, the tab coming back,
  // the browser changing its mind after speakerResume had given up -
  // whatever is held goes out at that moment rather than waiting for a
  // chunk that may be the last one.
  A.ctx.onstatechange = function () {
    if (A.ctx && A.ctx.state === 'running') { speakerReady(); pbFlush(false); }
  };
  pbEnsure();
  return true;
}

function speakerArmed() {
  if (!makeSpeaker()) return false;
  if (A.ctx.state === 'running') { speakerReady(); return true; }
  speakerResume();
  return false;
}

function speakerResume() {
  if (SPK.resuming || !A.ctx || A.ctx.state === 'running') return;
  SPK.resuming = true;
  // A browser that wants a press refuses by rejecting, not by throwing, so
  // the catch below is not enough on its own: without this the refusal
  // arrives as an unhandled rejection in the console, which is a poor way to
  // report something this file handles perfectly well.
  try {
    var asked = A.ctx.resume();
    if (asked && asked.catch) asked.catch(function () {});
  } catch (e) {}
  // Deliberately not hung off resume()'s promise. A browser refusing for
  // want of a press leaves that promise pending for ever - it settles if and
  // when the press finally comes - so the answer to "did it start" is the
  // state a moment later, and nothing else.
  setTimeout(function () {
    SPK.resuming = false;
    if (A.ctx && A.ctx.state === 'running') { speakerReady(); pbFlush(false); }
    // Only when there is something waiting to be heard. Every press on the
    // page asks the speaker to start, so without this guard a click on a
    // page where Rouh is not speaking would answer itself with a notice
    // about sound being blocked.
    else if (PB.pendingBytes) speakerBlocked(NEEDS_A_PRESS);
  }, 250);
}

// Said once, and taken back the moment a word is played.
function speakerBlocked(why) {
  if (!cfg.voiceReply) return;          // silence is what was asked for
  speakerNotice(true);
  if (SPK.told) return;
  SPK.told = true;
  SPK.note = notify(why, { tone: 'error', lasting: true });
  // The notice is for the person. This is for whoever is asked why the
  // phone was quiet, which is the first place they will look and was the
  // one place that said nothing at all.
  try {
    console.warn('rouh: the speaker is blocked, so speech is being held - ' + why);
  } catch (e) {}
}

function speakerReady() {
  SPK.told = false;
  if (SPK.note) { SPK.note.remove(); SPK.note = null; }
  speakerNotice(false);
}

// A notice is dismissed and forgotten, and "why can I not hear him" is asked
// while looking at the controls, so the microphone button says it too.
function speakerNotice(on) {
  var mb = $('micBtn');
  if (!mb) return;
  if (mb.classList.contains('needs-press') === !!on) return;
  mb.classList.toggle('needs-press', on);
  micSays();
}

/* ---------------------------------------------------------------------- */

/** @param {import('./protocol').FromServer<'audio_start'>} m */
function onAudioStart(m) {
  // A turn the person stopped never gets the speaker back, whatever is still
  // arriving from the server for it. Without this line one late chunk turned
  // playback on again and Rouh carried on talking after Escape.
  if (S.stopped) return;
  pbEnsure();
  PB.rate = Number(m.sample_rate) || 24000;
  PB.turn = m.turn_id || null;
  PB.next = 0;      // forces a resync on the first chunk of the reply
  PB.leftover = null;
  // A new reply is never the tail of the one that was interrupted, so the
  // drop ends here whatever the clock says. Replies while the voice is off
  // are dropped by `cfg.voiceReply` in `onAudioChunk`, which is a separate
  // question and the one that used to be muddled into this line.
  PB.dropTailUntil = 0;
  // A reply is starting: the speaker may be suspended after a reload or a
  // spell in a background tab, and asking now rather than on the first chunk
  // is what keeps the first word of the answer.
  speakerArmed();
  setState('speaking');
}

function onAudioEnd() {
  if (S.stopped) { PB.turn = null; return; }
  pbFlush(true);
  PB.turn = null;
}

function onAudioChunk(buf) {
  if (!cfg.voiceReply) { debug.audioDropped++; return; }
  // Sound belongs to a conversation as surely as words do, and a page at the
  // front door is in none: an answer still being spoken into the chat the
  // person walked out of is not read aloud to an empty screen. The bytes
  // carry no thread of their own - the message that announced them did, and
  // was dropped with everything else of that chat's (see 10g).
  if (ADDR.front) { debug.audioDropped++; return; }
  // After an interrupt the server's audio keeps arriving for a moment. Playing it
  // would mean Rouh talks over the person who just cut him off. The drop
  // has a deadline rather than waiting for an `audio_start` that may never
  // come; see PB.dropTailUntil.
  if (PB.dropTailUntil) {
    if (now() < PB.dropTailUntil) { debug.audioDropped++; return; }
    debug.dropLatchReleased++;
    PB.dropTailUntil = 0;
  }
  var ready = speakerArmed();
  debug.audioChunks++;
  noteTurnSign();
  PB.pending.push(new Uint8Array(buf));
  PB.pendingBytes += buf.byteLength;
  if (!ready) {
    // Held, not thrown away: a speaker usually starts within a chunk or two
    // of being asked, and one that is only waiting for a press starts the
    // instant it gets one, so keeping the bytes is what makes that press
    // worth giving.
    //
    // Unless there is no speaker to start. When `A.ctx` never opened - no
    // Web Audio here, or the browser would not build a context - nothing is
    // ever going to play these, and holding a minute of them only puts off
    // saying so. Then the cap is nothing and every chunk is counted as lost,
    // which is what the dropped and blocked numbers are for.
    var cap = A.ctx ? pbHoldCap() : 0;
    var keep = A.ctx ? 1 : 0;
    while (PB.pendingBytes > cap && PB.pending.length > keep) {
      PB.pendingBytes -= PB.pending.shift().length;
      debug.audioDropped++;
      debug.audioBlocked++;
    }
    return;
  }
  // Coalesce whatever lands close together into one buffer, but never wait long.
  if (PB.pendingBytes >= PB.rate * 2 * 0.2) { pbFlush(false); return; }
  if (!PB.timer) PB.timer = setTimeout(function () { PB.timer = null; pbFlush(false); }, 12);
}

function pbFlush(final) {
  if (PB.timer) { clearTimeout(PB.timer); PB.timer = null; }
  if (!PB.pending.length && !(final && PB.leftover)) return;
  // A buffer scheduled on a suspended context is not played late, it is
  // played all at once when the context starts, on top of everything else
  // scheduled while it was asleep. So nothing is scheduled until there is a
  // speaker to schedule it on; what is pending waits, and the next chunk or
  // the resume itself comes back here.
  if (!A.ctx || A.ctx.state !== 'running') return;
  pbEnsure();
  if (!PB.gain) return;

  var total = PB.pendingBytes + (PB.leftover ? PB.leftover.length : 0);
  var bytes = new Uint8Array(total);
  var off = 0;
  if (PB.leftover) { bytes.set(PB.leftover, 0); off = PB.leftover.length; PB.leftover = null; }
  for (var i = 0; i < PB.pending.length; i++) { bytes.set(PB.pending[i], off); off += PB.pending[i].length; }
  PB.pending.length = 0;
  PB.pendingBytes = 0;

  // Odd byte counts happen when a frame is split across the wire; hold the half sample.
  var usable = total - (total % 2);
  if (usable < total) PB.leftover = bytes.slice(usable);
  if (usable === 0) return;

  var pcm = new Int16Array(bytes.buffer, 0, usable / 2);
  var n = pcm.length;
  var audio = A.ctx.createBuffer(1, n, PB.rate);
  var ch = audio.getChannelData(0);
  for (var k = 0; k < n; k++) ch[k] = pcm[k] / 32768;

  var src = A.ctx.createBufferSource();
  src.buffer = audio;
  src.connect(PB.gain);

  var t = A.ctx.currentTime;
  var at = PB.next;
  if (at < t + 0.02) at = t + 0.05;   // first chunk, or the cursor fell behind: resync
  src.start(at);
  PB.next = at + audio.duration;

  PB.sources.push(src);
  src.onended = function () {
    var idx = PB.sources.indexOf(src);
    if (idx >= 0) PB.sources.splice(idx, 1);
    // The last of the sound is out. An answer is finished when it has been
    // said and not when it was written, so this is where a turn whose words
    // were done a while ago actually ends: the word in the title bar rests,
    // Stop goes, and Rouh's own line on the orb starts to fade.
    if (!PB.sources.length && !PB.pending.length && PB.turn === null) {
      if (!S.busy && S.state === 'speaking') setState('idle');
      showStop();
    }
  };

  debug.audioBuffers++;
  debug.audioSeconds += audio.duration;
}

// What is passing through the speaker this instant, 0 to 1, read off the
// analyser the audio goes through on its way to the output. A context that
// is running but playing nothing reads 0, which is the whole difference
// between sound having been scheduled and sound actually coming out - and
// the difference a test has to be able to see to claim a reply was heard.
function pbLevel() {
  if (!PB.analyser || !PB.analyserBuf) return 0;
  PB.analyser.getByteTimeDomainData(PB.analyserBuf);
  var peak = 0;
  for (var i = 0; i < PB.analyserBuf.length; i++) {
    var d = Math.abs(PB.analyserBuf[i] - 128);
    if (d > peak) peak = d;
  }
  return peak / 128;
}

function stopPlayback() {
  if (PB.timer) { clearTimeout(PB.timer); PB.timer = null; }
  for (var i = 0; i < PB.sources.length; i++) {
    try { PB.sources[i].onended = null; PB.sources[i].stop(); } catch (e) {}
    try { PB.sources[i].disconnect(); } catch (e) {}
  }
  PB.sources.length = 0;
  PB.pending.length = 0;
  PB.pendingBytes = 0;
  PB.leftover = null;
  PB.next = 0;
  // Nothing of that turn is being spoken any more, which is half of what
  // says there is still a turn to stop (`stillSpeaking`). Without this line
  // the Stop control stayed on screen after a stop, waiting for an
  // `audio_end` belonging to a turn that had been abandoned.
  PB.turn = null;
  PB.dropTailUntil = now() + TAIL_MS;
}

export { holdAudioSession, makeSpeaker, onAudioChunk, onAudioEnd, onAudioStart, PB, pbEnsure,
  pbFlush, pbLevel, silentTick, speakerReady, SPK, stopPlayback };
