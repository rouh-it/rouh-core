/* Rouh's page, settings (section 2 of what was one app.js).
 *
 * Imports app/helpers.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { hexToRgb, safeParse } from 'app/helpers.js';

/* ------------------------------------------------------------------ 2 */

var KEY_CFG = 'rouh.settings.v1';

var DEFAULTS = {
  openRatio: 4.2,
  closeRatio: 2.0,
  silenceMs: 700,
  preRollMs: 300,
  voiceReply: true,
  //: Whether the person has pressed the voice button on this browser. Until
  //: they have, the machine decides, and it says so in `ready`.
  //:
  //: It is a separate flag because `voiceReply` alone cannot answer the
  //: question. `setVoice` runs once at load with whatever the default is and
  //: saves it, so every browser that has ever opened Rouh has
  //: `voiceReply: true` stored whether or not anybody chose it, and a
  //: machine-level default would be masked by that for ever.
  voiceChosen: false
};

var BARGE_MULTIPLIER = 1.8;   // how much louder speech must be while Rouh talks
var MAX_UTTERANCE_MS = 30000; // hard stop on one turn
// Consecutive loud 20 ms frames before we call it speech. Six is 120 ms,
// which is long enough to reject the things a room throws at a microphone -
// a tumbling dryer, a door, a keyboard - and still short enough to catch the
// start of a word. At three it opened on a dryer roughly once every seven
// seconds, and each of those was a wasted transcription.
var OPEN_FRAMES = 6;
var FRAME_MS = 20;
var FRAME_SAMPLES = 320;      // 20 ms at 16 kHz
var MIN_FLOOR = 0.0012;       // stops a digitally silent mic making every breath "speech"

var cfg = (function () {
  var out = {};
  for (var k in DEFAULTS) out[k] = DEFAULTS[k];
  try {
    var raw = localStorage.getItem(KEY_CFG);
    if (raw) {
      var saved = safeParse(raw) || {};
      for (var j in DEFAULTS) if (typeof saved[j] === typeof DEFAULTS[j]) out[j] = saved[j];
    }
  } catch (e) { /* private mode */ }
  return out;
})();

function saveCfg() {
  try { localStorage.setItem(KEY_CFG, JSON.stringify(cfg)); } catch (e) {}
}

/* Everything this page remembers on the device is under `rouh.`. It was
   under `jarvis.` until 22 September 2026, and a setting nobody has touched
   since is still there under the old name on every browser that has ever
   opened this page: the column widths, the orb's sliders, the voice
   thresholds, which rail was open. So a read that finds nothing looks once
   under the old name, and moves the value across when it finds it. Nothing
   is ever written back under the old name. RENAME.md says which other names
   moved and which did not. */
var MINE = /^rouh\./;
function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function load(k) {
  try {
    var said = localStorage.getItem(k);
    if (said !== null || !MINE.test(k)) return said;
    var was = k.replace(MINE, 'jarvis.');
    said = localStorage.getItem(was);
    if (said !== null) { store(k, said); localStorage.removeItem(was); }
    return said;
  } catch (e) { return null; }
}
function drop(k) { try { localStorage.removeItem(k); } catch (e) {} }

/* Which conversation this tab is in, which is this tab's alone.

   Petar, 29 September 2026 (fr_349273a9377e): "I want to have different
   tabs doing different things for comparison purposes and multitasking".
   Until then the server kept one active chat for every tab, and opening a
   chat in one tab moved every other tab into it. Now each tab says which
   chat it is in when its socket opens (`hello`), and only a tab that asks
   is moved. It is kept in sessionStorage, which is this tab's own and
   survives a reload of it, and never in localStorage, which every tab of
   this browser shares. The address says it too, where the address names a
   conversation; this is for the ones that do not, such as `/tasks`. */
var KEY_TAB_CHAT = 'rouh.tab.chat';
function tabChatKeep(id) {
  try { if (id) sessionStorage.setItem(KEY_TAB_CHAT, id); } catch (e) {}
}
function tabChatSaid() {
  try { return sessionStorage.getItem(KEY_TAB_CHAT) || ''; } catch (e) { return ''; }
}

// The one colour read out of the stylesheet: the panel's. The orb draws the
// underside of every line in it, so wherever a nearer line crosses a farther
// one it keeps a thin gap. Everything else it draws with is its own. The page
// has one set of colours and they never change, so it is read once.
var panelRgb = hexToRgb(getComputedStyle(document.documentElement)
  .getPropertyValue('--panel'));

export { BARGE_MULTIPLIER, cfg, DEFAULTS, drop, FRAME_MS, FRAME_SAMPLES, load, MAX_UTTERANCE_MS,
  MIN_FLOOR, OPEN_FRAMES, panelRgb, saveCfg, store, tabChatKeep, tabChatSaid };
