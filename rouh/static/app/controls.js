/* Rouh's page, controls, composer, the speakers (section 11 of what was one app.js).
 *
 * Imports app/welcome.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import 'app/welcome.js';
import { shared } from 'app/shared.js';
import { $, drawerLayout, el, safeParse } from 'app/helpers.js';
import { cfg, DEFAULTS, load, saveCfg, store } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { S, send, tabChatWanted } from 'app/socket.js';
import { A, acquireMic, beginUtterance, endUtterance, MIC, releaseMic } from 'app/voice.js';
import { PB, speakerReady, stopPlayback } from 'app/playback.js';
import { orbExpand, orbMenu, orbRowHeight, ORBX, setState } from 'app/orb.js';
import { atBottom, closeAssistant, drawWaiting, drawWords, fitActs, keepEnd, newTurn, onTranscriptScroll, readerHand,
  scrollDown, setBusy, showStop, stopTheTurn, T, transcriptEl, watchTheTurn } from 'app/transcript.js';
import { CARDS_UP, cardsBackInPlace, cardsGoOut, cardsSettle, cardsUncover, layerOpen, LAYERS, paintCovered } from 'app/cards.js';
import { canvasTask, growToLines, projectsClose, rowsFollowSidebar } from 'app/runs.js';
import { chatById, CHATS, forkBtnPaint, forkComeNow, FORKS, isSendKey, sendKeys, withSendKeys } from 'app/chats.js';
import { ADDR, addrChatIsShowing, addrTouch, freshChatFirst } from 'app/address.js';
import { attReady, attUploading, clearAttachments, drawTurnFiles, PICS, sendPicture, unlockAudio } from 'app/attachments.js';

/* ----------------------------------------------------------------- 11 */

function bindSlider(id, key, fmt) {
  var input = $(id), out = $(id + 'Val');
  input.value = cfg[key];
  out.textContent = fmt(cfg[key]);
  input.addEventListener('input', function () {
    cfg[key] = parseFloat(input.value);
    out.textContent = fmt(cfg[key]);
    saveCfg();
  });
}

bindSlider('openRatio', 'openRatio', function (v) { return v.toFixed(1); });
bindSlider('closeRatio', 'closeRatio', function (v) { return v.toFixed(1); });
bindSlider('silenceMs', 'silenceMs', function (v) { return Math.round(v) + ' ms'; });
bindSlider('preRollMs', 'preRollMs', function (v) { return Math.round(v) + ' ms'; });

$('resetSettings').addEventListener('click', function () {
  for (var k in DEFAULTS) cfg[k] = DEFAULTS[k];
  saveCfg();
  ['openRatio', 'closeRatio', 'silenceMs', 'preRollMs'].forEach(function (id) {
    $(id).value = cfg[id];
    $(id).dispatchEvent(new Event('input'));
  });
  setVoice(cfg.voiceReply);
});

// Dictation: press to start, say it all, press to finish. Pauses never end
// the turn while it is on, however long - the backup for when a long pause
// must not even start an answer. Ctrl+Shift+Space does the same from anywhere
// on the page, including while typing.
function showDictation(on) {
  S.dictating = !!on;
  var b = $('dictateBtn');
  if (b) {
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.title = on ? 'Finish (Ctrl+Shift+Space): Rouh answers the whole of it'
                 : 'Dictate (Ctrl+Shift+Space): press, say it all, press again when you have finished. Pauses never end your turn.';
  }
  var label = $('dictateLabel');
  if (label) label.textContent = on ? 'Finish' : 'Dictate';
  var note = $('dictationNote');
  if (note) note.hidden = !on;
}

function setDictation(on) {
  on = !!on;
  if (on === !!S.dictating) return;
  // Dictating with no microphone is not a state. Whoever turns it on has
  // already opened one: every caller goes through `withMic` first.
  if (on && !S.micReady) return;
  showDictation(on);
  // The server is told as well, and not because it decides anything here:
  // the browser holds the utterance open itself. It is so that nothing is
  // answered on a clock while somebody is still dictating, however long
  // they pause (rouh/turnmarks.py).
  send({ type: 'dictation', on: on });
  if (on) {
    // Dictation holds the utterance open itself and nothing but the hard
    // cap closes it.
    A.held = true;
    if (!A.utterance) beginUtterance();
  } else {
    A.held = false;
    endUtterance('released');
  }
}

// Pressing Dictate is asking to be listened to, so it is one of the two
// presses allowed to open the microphone - the other being the microphone
// button itself - and the only thing that does the opening is `withMic`,
// which owns that decision for both of them.
function toggleDictation() {
  if (S.dictating) { setDictation(false); return; }
  withMic(function () { setDictation(true); });
}

var dictateBtn = $('dictateBtn');
if (dictateBtn) dictateBtn.addEventListener('click', toggleDictation);
document.addEventListener('keydown', function (e) {
  if (e.code === 'Space' && e.ctrlKey && e.shiftKey && !e.altKey && !e.metaKey && !e.repeat) {
    e.preventDefault();
    toggleDictation();
  }
});

// The build lines in Settings are filled in when the page is served. Opened
// straight from the folder there is nobody to fill them in, so the curly
// braces become something a person can read instead.
(function () {
  var num = $('verNum'), rev = $('verRev'), v = $('verWhen');
  if (num && num.textContent.indexOf('{{') >= 0) num.textContent = 'dev';
  if (rev && rev.textContent.indexOf('{{') >= 0) rev.textContent = 'local';
  if (!v) return;
  // The tooltip carries the same line and is filled in the same way, so it
  // needs the same fallback.
  if (v.title.indexOf('{{') >= 0) v.title = 'Opened from the folder, not served';
  var t = v.textContent;
  if (t.indexOf('{{') >= 0) { v.textContent = 'not a checkout'; return; }
  // "729d3fb, committed 8 Sep 2026". The commit is on the line above, so the
  // only thing this row has left to say is the date.
  var at = t.indexOf(', committed ');
  v.textContent = at >= 0 ? t.slice(at + 12) : t;
}());

/* ------------------------------------------------ folding the columns */

/* ------------------------------------------------ the sidebar, and the fold

   The navigation down the left is one thing in three sizes of window, and
   the width of the window decides which, with one exception for a finger:

     wide    1100 and over. Docked: it is a track of the grid, it pushes the
             page over, and everything beside it resizes with it.
     narrow  641 to 1099, and a touch screen up to 1366, an iPad Pro lying
             down (since 10 October 2026). Folded by itself, because the
             reading gets tight. Opened, it floats on top of the page rather
             than pushing it, and a press anywhere past it closes it again.
     mobile  640 and under. The same drawer, and it takes about four fifths
             of the width rather than all of it: the strip of page left
             beside it is dimmed, and a press on that strip closes it.

   Wherever it is a drawer, the orb's circle is the button that opens it,
   and grows into the row at its foot (`orbMenu` in app/orb.js).

   Folding by itself must never fight a decision somebody made. So a person's
   own press is honoured for as long as the window stays the size it was when
   they made it, and only a move from one of the three to another puts the
   sidebar back to what that size opens with: open when docked, away
   otherwise. The wide one is remembered between reloads, beside the fold of
   the transcript; the other two are not, because arriving on a phone to a
   screen covered by navigation is not what anybody wants.

   `--sb-w` is the width it was dragged to, in this browser, and the CSS
   builds the grid's first track out of it. */

/* The transcript can still be folded away for the length of a visit -
   `set_panels` asks for it out loud, and the index does it while it has the
   window - but nothing on the page is a button for it any longer, and so
   **it is never written down**.

   It was, and that is how a browser could be left with no conversation in
   it at all. The control that folded it was the one on the canvas bar that
   gave the canvas the whole screen; it wrote `chat: false` here, and when
   it went on 21 September 2026 the last thing that could write `true` went
   with it. Anybody who had ever pressed it came back to a page with the
   column gone, a New chat they could not see and a chat in the rail that
   opened into nothing. A setting no control can undo must not outlive the
   tab, whatever is in this key from before.

   Since 23 October 2026 there is a control for it again, the Chat rail
   that a hidden chat leaves at the side of the screen, which can always
   undo it.
   So the fold is written down once more, but per chat and beside the
   canvas's, never in this key (`KEY_PANELS`, under "the two panels"). */
var KEY_COLS = 'rouh.columns.v1';
var KEY_SB_W = 'rouh.sidebar.width.v1';
// 240 rather than 200 since 20 September 2026. It was the head that needed
// it then, for the name, the four statuses and the switch on one row; since
// 23 September it is the foot, where the statuses sit beside the person's
// name with search and Gene therapy, and below 240 they stop fitting.
var SB_MIN = 240, SB_MAX = 400, SB_DEFAULT = 264;

var cols = (function () {
  // `chat` is not read back from this key: see above. It and `canvas` are
  // the conversation's own, read back per chat (`panelsForChat`). `canvas` is the conversation's own, read
  // back per chat once the page knows which chat it is in (`panelsForChat`);
  // until then it is what the address says (`panelsAtLoad`).
  var out = { tasks: true, chat: true, canvas: true };
  var saved = safeParse(load(KEY_COLS)) || {};
  if (typeof saved.tasks === 'boolean') out.tasks = saved.tasks;
  return out;
})();

// The navigation is a drawer at every width since 12 October 2026
// (`drawerLayout`), so `wide`, the docked column a desk had until then, is
// never the answer now. Its branches here and in app/orb.js are kept behind
// that one switch rather than torn out.
function sbSize() {
  if (window.innerWidth <= 640) return 'mobile';
  if (drawerLayout()) return 'narrow';
  return 'wide';
}

var SB = { size: sbSize(), open: false };
SB.open = SB.size === 'wide' ? cols.tasks : false;

// What the app element is told, which is the whole of the difference between
// the shapes: the stylesheet reads this attribute and nothing else.
//
// There were three of them and there are two: a phone used to get `full`, a
// sidebar covering the screen edge to edge, and now gets the same `over` a
// narrow window gets - a drawer over most of the width with the page dimmed
// beside it. Petar, 23 September 2026: "when navigation opens, it shouldn't
// take up the entire screen like we currently have it. It should take about
// 70% to 80%. The right side is darkened, and I can tap on it to discard the
// sidebar." How wide the drawer is at that size is the stylesheet's, not
// this function's.
function sbState() {
  if (!SB.open) return 'shut';
  if (SB.size === 'wide') return 'docked';
  return 'over';
}

/* What the tasks hold of the window while they are loaded, and what they
   give back.

   The conversation, for the whole of the tasks and not only for the index.
   The index is two columns of tasks and a task's own page is a page built to
   be read; neither of them is a third of a window. Walking from the index
   into a task and having the window shrink under the press is the shape of
   the thing changing for no reason the person asked for.

   **The navigation is not theirs to take.** It was, until 22 September 2026:
   opening the tasks folded it away and closing them put it back. That is one
   column too many. The navigation is the way to every other part of Rouh and
   it has a glyph, a key and a saved fold of its own, so where the person
   left it is where it stays - open beside the tasks if that is how they had
   it, shut if not. Nothing here reads or writes it any more, which is also
   why there is no "what it was before" to keep: there is no before.

   The cross is what gives the conversation back, and it is beside the
   breadcrumb where the reader already is.

   One exception, and it is the whole of `chatIsWanted`: somebody opening a
   conversation gets one they can see. The rail and the list of chats and
   tasks are lists of conversations, so picking a row there is asking to read
   it, and New chat is asking to start one. The column comes back and stays
   back until the tasks are closed - taking it away again on the next press
   of the breadcrumb would be arguing with them. */
var TASKS_ON = false;
var TASKS_FULL = false;

//: Whether the conversation has been asked for since the tasks took the
//: window. It is on the page for the rest of this visit to them.
var CHAT_KEPT = false;

function tasksHold(on) {
  on = !!on;
  if (on !== TASKS_ON) {
    TASKS_ON = on;
    if (on) CHAT_KEPT = false;
  }
  TASKS_FULL = on && !CHAT_KEPT;
  sbApply();
  growInput();
}

/* The tasks take the conversation back.
 *
 * The mirror of `chatIsWanted` below, and the one thing that undoes it: the
 * task browser pressed in the navigation is the person asking for the whole
 * of the window beside it (`tasksBrowse`), which outranks a conversation
 * they opened earlier in this visit to the tasks. Nothing else clears this:
 * a press of the breadcrumb is not an argument about the columns.
 */
function tasksTakeChat() { CHAT_KEPT = false; }

// Somebody is opening a conversation, so the conversation has to be on the
// page. What is loaded in the canvas is left exactly as it is, and so is the
// navigation: this is about the one column that has no control of its own.
function chatIsWanted() {
  CHAT_KEPT = true;
  // The projects are laid over this column, so a chat opened while they are
  // up would be opened onto a screen nobody can see.
  projectsClose();
  if (!TASKS_FULL && cols.chat) return;
  TASKS_FULL = false;
  // And whatever folded it before this - `set_panels`, asked out loud - is
  // over too. They are opening a conversation; they get one they can see.
  cols.chat = true;
  sbApply();
  growInput();
}

/* The conversation put away, from the cross over it or a second press of
   the sparkle on the page, so the page has the window. Petar, 1 October
   2026: "sometimes I want the full screen for the content and I want to
   invoke the chat only at some moments."

   The mirror of `chatIsWanted`, and nothing more than a fold: what was said
   on either side is all still there when the sparkle brings it back. Over
   the tasks it is the tasks holding the window again, exactly as they did
   before it was opened; anywhere else it is the column folded, as
   `set_panels` folds it. Neither is remembered past this visit. On a phone
   the conversation is a pane, and putting it away is going to the other. */
function chatPutAway() {
  if (narrow()) { setPane('canvas'); return; }
  // Whatever puts the conversation away gives the canvas the window, so the
  // screen is never left with neither of them on it.
  cols.canvas = true;
  if (TASKS_ON) { CHAT_KEPT = false; TASKS_FULL = true; }
  else { cols.chat = false; panelsKeep(); }
  var col = $('chatCol');
  if (col && document.activeElement && col.contains(document.activeElement)) {
    try { /** @type {HTMLElement} */ (document.activeElement).blur(); } catch (err) {}
  }
  sbApply();
  growInput();
}

// Whether the conversation is on the screen now, wherever it is.
function chatOnScreen() {
  if (narrow()) return pane === 'chat';
  return addrChatIsShowing();
}

// One fold glyph, fixed in the corner of the window, and it says what
// pressing it does now: in words, with its key beside it. There were two of
// them until 20 September 2026, one in the sidebar and one beside the
// breadcrumb, so the control moved into the conversation's own panel every
// time it was used.
function markFold() {
  var btn = $('sidebarToggle');
  if (!btn) return;
  var shown = SB.open;
  btn.setAttribute('aria-expanded', shown ? 'true' : 'false');
  // A drawer over the page is closed, at whatever width it is a drawer, and
  // the button is drawn as a cross saying so (the stylesheet, on `over`).
  var says = shown ? (sbState() === 'over' ? 'Close the navigation' : 'Hide sidebar')
    : 'Show sidebar';
  var what = btn.querySelector('.sb-tip-what');
  if (what) what.textContent = says;
  // "Drag to resize" is about the edge beside it, so it is only said where
  // there is an edge: not while the sidebar is folded away, and not on a
  // phone, where the sidebar is the screen and has no edge.
  var sub = btn.querySelector('.sb-tip-sub');
  if (sub) sub.hidden = !(shown && SB.size !== 'mobile');
  btn.setAttribute('aria-label', says);
}

function sbApply(silent) {
  var app = $('app');
  if (!app) return;
  // On the first pass the saved state is where the page starts, so it must
  // not be animated into place.
  if (silent) app.style.transition = 'none';
  app.setAttribute('data-sb', sbState());
  // What `set_panels` and the saved fold have always called this column, and
  // it is the wide screen's answer alone. A phone folds the navigation away
  // by itself and is closed again with the cross, and neither of those is
  // the person saying anything about the desk they will open this on next.
  if (SB.size === 'wide') cols.tasks = SB.open;
  panelsPaint(silent);
  markFold();
  // Wherever the navigation is a drawer the orb's circle is the menu button,
  // and the open menu is that circle grown into the row at the foot of it.
  orbMenu(SB.open && SB.size !== 'wide', silent);
  drawerHistory();
  // The press-past-it that closes a floating sidebar. There is nothing to
  // press past when it is docked, and nothing showing when it is away.
  var scrim = $('sbScrim');
  if (scrim) scrim.hidden = sbState() !== 'over';
  // The sidebar's fold, and nothing else. `chat` is this visit's only.
  store(KEY_COLS, JSON.stringify({ tasks: cols.tasks }));
  // The row menu and the rename field hang over the sidebar's rows rather
  // than inside it, so they go when it does. This is the one place that
  // opens and closes it, from every way of asking.
  rowsFollowSidebar(SB.open);
  // The links are at the foot of the column, where a thumb is. A window too
  // short for all of them opens the column scrolled to its foot, so the
  // links are there first and what is above them is the part scrolled to.
  var body = SB.open && document.querySelector('.sb-body');
  if (body) body.scrollTop = body.scrollHeight;
  if (silent) requestAnimationFrame(function () { app.style.transition = ''; });
}

/* The press that navigated was also the press that is done with the
 * navigation.
 *
 * Everywhere but a wide window the sidebar is a drawer lying over the page,
 * so whatever was just opened is underneath it and the drawer has nothing
 * left to say. Petar, 23 September 2026: "Whenever I choose something from
 * the sidebar that would load a page, the sidebar goes away again, and I
 * have the navigation button up top."
 *
 * What it is **not** is every press inside the drawer. Drilling in stays
 * put: the three dots on a row, the chevron that shows a task's steps, a
 * project that narrows the list under it. Those are the person still
 * reading the navigation, and closing it under them would be taking the
 * menu away at the moment they opened it.
 */
function sidebarDone() {
  if (SB.size !== 'wide') sbSet(false);
}

// A deliberate press, from the glyph, the key or the assistant. It works the
// same whether or not the tasks are loaded, and is remembered either way.
function sbSet(open) {
  open = !!open;
  if (SB.open === open) return;
  SB.open = open;
  sbApply();
  growInput();
}

// The window changed size. Only a move from one of the three to another
// touches the fold: within one of them, what the person asked for stands.
function sbResized() {
  var size = sbSize();
  if (size === SB.size) return;
  SB.size = size;
  SB.open = size === 'wide' ? cols.tasks : false;
  sbApply();
  growInput();
}

// Set from outside: the assistant asking for a column to open or close.
// Only the keys that were sent are changed, so "hide the transcript" leaves
// the sidebar alone.
window.setCols = function (want) {
  var touched = false;
  if (typeof want.tasks === 'boolean') { SB.open = want.tasks; touched = true; }
  if (typeof want.chat === 'boolean') { cols.chat = want.chat; touched = true; }
  if (typeof want.canvas === 'boolean') { cols.canvas = want.canvas; touched = true; }
  if (!touched) return;
  // Never neither: whichever was asked for last stays (`panelsShown`).
  if (!cols.chat && !cols.canvas) {
    if (want.canvas === false) cols.chat = true; else cols.canvas = true;
  }
  // Asked for out loud is as much the person's choice as a press of a
  // panel's own control, so it is this chat's from now on.
  if (typeof want.chat === 'boolean' || typeof want.canvas === 'boolean') panelsKeep();
  // Being asked out loud for a column is the person saying what they want on
  // the screen, which outranks anything the tasks are holding. They hold
  // nothing after this, so closing them gives nothing back over it either.
  TASKS_ON = TASKS_FULL = false;
  sbApply();
  if (narrow()) { var p = paneForCols(want); if (p) setPane(p); }
  growInput();
};

if ($('sidebarToggle')) {
  $('sidebarToggle').addEventListener('click', function () {
    // The button is over everything, the orb opened over the whole screen
    // included, so from there it puts the orb back first: the navigation
    // it opens is what the person asked for, and it has to be seen.
    if (ORBX.open) { orbExpand(false); sbSet(true); return; }
    sbSet(!SB.open);
  });
}
if ($('sbScrim')) {
  $('sbScrim').addEventListener('click', function () { sbSet(false); });
}

/* Back closes the navigation, and so does Escape, wherever it is a drawer
   over the page (a phone's alone until 10 October 2026, and a tablet's too
   since).

   There the open navigation is a screen over the page, and Back is how
   a phone or a tablet leaves a screen. So opening it there adds one entry to the history,
   at the same address and marked as the drawer's, and Back takes that entry
   off by closing the drawer, with nothing else on the page touched. Closed
   any other way - the cross, the page beside it, Escape, a link followed,
   the row opening the orb - it takes its entry back off itself, so the
   history is exactly what it was before the drawer opened, and the next
   Back goes where it would have gone.

   While that is happening the address waits (`drawerUnwinding`, read by
   app/address.js): a link followed from the drawer writes its own address,
   and written before the drawer's entry is off it would be written on top of
   it and then taken off with it. */
var DRAWER = { entry: false, unwinding: false, timer: 0 };

function drawerHistory() {
  var want = SB.open && SB.size !== 'wide';
  if (want && !DRAWER.entry && !DRAWER.unwinding) {
    try {
      history.pushState({ rouhDrawer: 1 }, '', location.href);
      DRAWER.entry = true;
    } catch (err) { /* no history to add to: Back is then the browser's own */ }
  } else if (!want && DRAWER.entry) {
    DRAWER.entry = false;
    DRAWER.unwinding = true;
    // Back always answers, but not always at once, and the address must not
    // wait on it for ever.
    clearTimeout(DRAWER.timer);
    DRAWER.timer = setTimeout(drawerUnwound, 800);
    history.back();
  }
}

function drawerUnwound() {
  if (!DRAWER.unwinding) return;
  DRAWER.unwinding = false;
  clearTimeout(DRAWER.timer);
  addrTouch();
  // Opened again while the last entry was coming off: it gets its own.
  drawerHistory();
}

function drawerUnwinding() { return DRAWER.unwinding; }

/* The address is about to be written while the drawer's entry is the one
   on top - a link in the drawer that leaves it open. The new address takes
   that entry's place rather than going on top of it, and the drawer has no
   entry of its own after that: Back from there is the page's. */
function drawerEntryTaken() {
  if (!DRAWER.entry) return false;
  DRAWER.entry = false;
  return true;
}

/* Back or Forward, asked first by the address (its `popstate` in
   app/address.js), so that the drawer's entry coming off is never taken for
   the person going somewhere. True when it was the drawer's and nothing else
   is to be done: the entry this page took off itself, or Back pressed with
   the drawer open, which closes it and leaves the page under it as it is. */
function drawerPopped() {
  if (DRAWER.unwinding) { drawerUnwound(); return true; }
  if (!DRAWER.entry) return false;
  DRAWER.entry = false;
  sbSet(false);
  return true;
}
// A page reloaded with the drawer open comes back with it shut, on the
// drawer's entry: it is the address's entry from here on.
try {
  if (history.state && history.state.rouhDrawer) history.replaceState(null, '', location.href);
} catch (err) {}

/* Escape. Before anything under the drawer hears it: one press closes one
   thing, and the drawer is the thing in front. A menu open inside it, a
   name being typed into it, or the notifications its bell opened over it
   (`notices.js`), is nearer still and keeps the key. */
window.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || e.defaultPrevented || sbState() !== 'over' || ORBX.open) return;
  if (document.querySelector('.menu:not([hidden]), #notices[data-mode="list"]')) return;
  var where = document.activeElement;
  if (where && where.closest && where.closest('input, textarea, select, dialog, [contenteditable="true"]')) return;
  e.preventDefault();
  e.stopPropagation();
  sbSet(false);
}, true);

/* The key. Cmd+B on a Mac, Ctrl+B everywhere else, which is what every
   program with a sidebar has settled on. It is taken even while the text box
   has the cursor: a plain textarea does nothing with it, and the person
   pressing it meant the sidebar. */
(function () {
  var mac = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '');
  var caps = document.querySelectorAll('.sb-key');
  for (var i = 0; i < caps.length; i++) caps[i].textContent = mac ? '⌘B' : 'Ctrl+B';
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'b' && e.key !== 'B') return;
    if (e.altKey || e.shiftKey) return;
    if (mac ? !e.metaKey : !(e.ctrlKey && !e.metaKey)) return;
    e.preventDefault();
    sbSet(!SB.open);
  });
}());

/* --------------------------------------------- the edges, dragged

   Two boundaries on this page are dragged: the sidebar's right edge, and the
   line between the conversation and the canvas. The gesture is one gesture,
   so it is written once, in `dragEdge`, and each edge hands it the three
   things that are its own - what a pointer means in pixels, what to do with
   a width, and where to write the width down.

   Every width goes on the root element rather than on the column it belongs
   to, because what actually moves is a track of the grid and not the element
   sitting in it; writing it on the element would have left the track the
   width it always was. The easing on those tracks is off for the length of a
   drag, so the edge follows the pointer exactly rather than trailing it. */

/* `spec.at(e)` turns a pointer into the width being asked for, `spec.set(px)`
   puts a width on the page and answers with the one it settled on, and
   `spec.now()` reads back what is on the page this moment. `spec.key` is
   where it is remembered between visits. */
function dragEdge(handle, spec) {
  if (!handle) return;
  var held = 0, grab = 0;

  function done() {
    handle.classList.remove('dragging');
    $('app').classList.remove('edge-dragging');
    document.body.style.removeProperty('cursor');
    if (handle.releasePointerCapture && held) {
      try { handle.releasePointerCapture(held); } catch (err) { /* already gone */ }
    }
    held = 0;
    store(spec.key, String(spec.now()));
    window.dispatchEvent(new Event('resize'));
  }

  handle.addEventListener('pointerdown', function (e) {
    if (e.button) return;
    // Stops the drag selecting the text either side of the edge, and with it
    // the focus a press would have given the separator - so it is given
    // here, which is what puts the arrow keys on the edge just pressed.
    e.preventDefault();
    if (handle.focus) handle.focus({ preventScroll: true });
    held = e.pointerId;
    // Where on the handle it was taken hold of: the line is in the middle of
    // a gap wider than it, and the edge must not jump to the pointer on the
    // first move.
    grab = spec.at(e) - spec.now();
    handle.classList.add('dragging');
    // Focused by a pointer, which is not a keyboard's focus to be lit for
    // once the pointer has let go and moved off it.
    handle.classList.add('pointed');
    $('app').classList.add('edge-dragging');
    // Whatever the pointer crosses while it is held, it is still resizing.
    document.body.style.cursor = 'col-resize';
    if (handle.setPointerCapture) handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', function (e) { if (held) spec.set(spec.at(e) - grab); });
  handle.addEventListener('blur', function () { handle.classList.remove('pointed'); });
  handle.addEventListener('pointerup', done);
  handle.addEventListener('pointercancel', done);
  // A separator is walked with the arrows as well as dragged, and a drag is
  // the one gesture a keyboard cannot make at all.
  handle.addEventListener('keydown', function (e) {
    var step = e.key === 'ArrowLeft' ? -16 : e.key === 'ArrowRight' ? 16 : 0;
    if (!step) return;
    handle.classList.remove('pointed');
    e.preventDefault();
    store(spec.key, String(spec.set(spec.now() + step)));
    window.dispatchEvent(new Event('resize'));
  });
}

/* The sidebar's right edge. Between 240 and 400, and `--sb-w` is the grid's
   first track. */
var SB_W = SB_DEFAULT;

function sbWidth(px) {
  var w = Math.max(SB_MIN, Math.min(SB_MAX, Math.round(px)));
  SB_W = w;
  document.documentElement.style.setProperty('--sb-w', w + 'px');
  var handle = $('sbResize');
  if (handle) handle.setAttribute('aria-valuenow', String(w));
  return w;
}

sbWidth(Number(load(KEY_SB_W)) || SB_DEFAULT);

dragEdge($('sbResize'), {
  key: KEY_SB_W,
  at: function (e) { return e.clientX - $('tasksPanel').getBoundingClientRect().left; },
  set: sbWidth,
  now: function () { return SB_W; }
});

/* The edge between the conversation and the canvas.

   It has no width of its own until somebody moves it: the stylesheet gives
   the two columns shares of what is left, and that is what everybody who
   never drags it goes on seeing. The moment it is dragged the conversation
   becomes the width it was dragged to - written as a track whose smallest
   size is nothing, so a window too narrow for that width squeezes the
   conversation rather than pushing the page off the side of itself - and the
   canvas takes the rest with a floor of its own under it. The floor is what
   stops either column being dragged away to nothing, and it is in the grid
   rather than only in the clamp below, so it holds when the window narrows,
   when the sidebar is dragged wider, and when the Gene therapy drawer pushes the
   page in. None of those has to tell this code anything, and the width the
   person chose is given straight back when the room for it returns.

   Remembered in this browser, and one width for the whole page: walking into
   a task and back out again finds the edge where it was left. */
var KEY_CHAT_W = 'rouh.chat.width.v1';
// 300 is the narrowest this column has ever been allowed to be - it is the
// floor the stylesheet uses between 900 and 1180 - and 320 keeps a card on
// the canvas readable. Neither is a width anybody would choose; they are the
// two ends nobody may drag past.
var CHAT_MIN = 300, CANVAS_MIN = 320;
//: The width the conversation was dragged to, or 0 while nobody has.
var CHAT_W = 0;

// What there is to share: the conversation, the gutter between the two, and
// the canvas. Both ends of it stand still while the edge is dragged, so it
// can be measured on every frame without the answer moving under the drag.
// Nothing to measure while the conversation is folded away, and nothing to
// drag either, because the handle is inside the column and goes with it.
function chatRoom() {
  var chat = $('chatCol'), canvas = $('canvasPanel');
  if (!chat || !canvas) return null;
  var a = chat.getBoundingClientRect(), b = canvas.getBoundingClientRect();
  if (!a.width || !b.width) return null;
  return { width: a.width, room: b.right - a.left, gutter: Math.max(0, b.left - a.right) };
}

// The widest the conversation may be, which is whatever leaves the canvas
// its floor. There is no number to write down for it: it moves with the
// window, the sidebar and the Gene therapy drawer.
function chatMost(box) {
  return Math.round(Math.max(CHAT_MIN, box.room - box.gutter - CANVAS_MIN - FORKS.reserve));
}

// What the separator says about itself, which a screen reader reads and
// nobody else sees.
function chatSay(w, most) {
  var handle = $('chatResize');
  if (!handle) return;
  handle.setAttribute('aria-valuenow', String(w));
  handle.setAttribute('aria-valuemax', String(most));
}

/* `px` is the conversation itself, edge to edge, which is what the pointer
   is pointing at and what is worth writing down. A track is wider than the
   column standing in it by the margin that makes the gutter, so the gutter
   is added back here - in CSS rather than in the arithmetic, because it is
   10 rather than 12 between 900 and 1180 and the grid may as well work that
   out for itself. */
function chatWidth(px) {
  var box = chatRoom();
  if (!box) return CHAT_W;
  var most = chatMost(box);
  var w = Math.max(CHAT_MIN, Math.min(most, Math.round(px)));
  CHAT_W = w;
  // A dragged width is the conversation's own; the room for a strip of
  // forks either side of it is added on top (`forkTrack`).
  FORKS.pinned = 0;
  var root = document.documentElement.style;
  root.setProperty('--chat-track',
    'minmax(0px, calc(' + w + 'px + var(--fork-w) + var(--gutter)))');
  root.setProperty('--canvas-track',
    'minmax(calc(' + CANVAS_MIN + 'px + 2 * var(--gutter)), 2fr)');
  chatSay(w, most);
  return w;
}

// Where the edge is now. Before anything is dragged that is whatever share
// the stylesheet gave the column, which is what the arrow keys have to start
// from: stepping from nothing would snap the edge to its floor on the first
// press.
function chatNow() {
  if (CHAT_W) return CHAT_W;
  var box = chatRoom();
  return box ? Math.round(box.width - FORKS.reserve) : CHAT_MIN;
}

// Put back after `sbApply` and not before it: what there is to share is
// measured off the page, and until the sidebar has been told whether it is
// docked the page is not yet the shape this browser last left it in.
function chatRestore() {
  var saved = Number(load(KEY_CHAT_W)) || 0;
  if (saved) { chatWidth(saved); return; }
  // Nothing written down, so the stylesheet's share stands. The separator
  // still has to be able to say where it is and how far it goes.
  var box = chatRoom();
  if (box) chatSay(Math.round(box.width - FORKS.reserve), chatMost(box));
}

dragEdge($('chatResize'), {
  key: KEY_CHAT_W,
  at: function (e) {
    return e.clientX - $('chatCol').getBoundingClientRect().left - FORKS.reserve;
  },
  set: chatWidth,
  now: chatNow
});

// Who is signed in, at the foot of the sidebar. The name is stamped into the
// page when it is served - the nickname on their profile, their name, or the
// name they sign in with - so there is nothing to ask anybody for; the circle
// is its first letter, or its first two words' letters where it has two.
// Saving the profile says it again (`ownName`).
ownName('');

/** @param {string} said what the profile now calls them, or '' for what the page was served with */
function ownName(said) {
  var login = ($('whoAmI') && $('whoAmI').textContent || '').trim();
  var name = $('sbAccountName'), face = $('sbAvatar');
  var who = String(said || '').trim() || (name && name.textContent || '').trim();
  if (!who || who === 'Account') who = login;
  if (!who) return;
  if (name) { name.textContent = who; }
  var row = $('accountRow');
  if (row) row.title = 'Signed in as ' + (login || who);
  if (face) {
    // Two letters where there are two words to take them from, one where
    // there is one: "AL" for alex is not initials, it is the start of a
    // word with the rest cut off.
    var parts = who.split(/[\s._-]+/).filter(Boolean);
    face.textContent = parts.length > 1
      ? parts[0].charAt(0) + parts[1].charAt(0) : who.charAt(0);
  }
}

// What is behind the person's own name: Edit, which opens their profile,
// and signing out. They were two loose icons on a row under the name until
// 20 September 2026, which spent a row of the column on two things nobody
// presses in a day.
//
// The same menu as every three dots here (`menu.js`): a press anywhere
// else puts it away, and so do Escape and choosing an item.
var accountMenu = RouhMenu.bind($('accountRow'), $('accountMenu'), { align: accountMenuPlace });

/* Where that menu goes: against the name that opened it, and never over the
   orb. Petar, 13 October 2026 (fr_02048b1ef832): "that menu should not appear
   over the orb. Should be glued to the button that pressed it - the profile
   with name". It rose from above the orb's row until then, the row standing
   between it and the name.

   Straight above the name, its left edge on the name's, wherever that clears
   the orb: on a tablet or a phone, where the rows under the orb are a finger
   high, it always does. Where it would reach the orb - a desk, whose rows are
   shorter - it opens beside the name instead, its foot on the name's foot,
   out over the bell and Search, which nobody presses while the menu is up.
   Fixed to the window and placed afresh each time it opens and whenever the
   window changes, so it is wherever the name is.
   @param {HTMLElement} menu @param {HTMLElement} button */
function accountMenuPlace(menu, button) {
  var b = button.getBoundingClientRect();
  if (!b.width && !b.height) return;
  var GAP = 4, EDGE = 8, W = window.innerWidth;
  menu.style.width = Math.round(Math.min(Math.max(b.width, 184), W - 2 * EDGE)) + 'px';
  var w = menu.offsetWidth, h = menu.offsetHeight;
  var orb = /** @type {HTMLElement | null} */ (document.querySelector('.orb-layer .orb-box'));
  var o = orb && orb.getClientRects().length ? orb.getBoundingClientRect() : null;
  /** @param {number} left @param {number} top */
  function clear(left, top) {
    return !o || left >= o.right || left + w <= o.left || top >= o.bottom + GAP || top + h <= o.top - GAP;
  }
  var left = Math.max(EDGE, Math.min(b.left, W - w - EDGE));
  var top = b.top - GAP - h;
  if (top < EDGE || !clear(left, top)) {
    var beside = Math.max(EDGE, Math.min(b.right + GAP, W - w - EDGE));
    var low = Math.max(EDGE, b.bottom - h);
    if (clear(beside, low)) { left = beside; top = low; }
  }
  menu.style.left = Math.round(left) + 'px';
  menu.style.top = Math.round(Math.max(EDGE, top)) + 'px';
}

/* ------------------------------------- the two panels: Chat and Canvas

   Petar, 24 October 2026 (fr_5b66b98dfb63), from his mockups: each panel
   hides itself from the outer end of its own head (`#chatHide`,
   `#canvasHide`), and a panel put away leaves a narrow rail at its own side
   of the screen, its glyph and its name, which brings it back (`#railChat`,
   `#railCanvas`). The one panel still open cannot be turned off: an empty
   screen is not a state. Until then it was a pill of two buttons on the
   line between the panels (23 October), then a notch of two glyphs there.

   One state for every way of asking. `cols.chat` and `cols.canvas` are what
   the panels' controls, `set_panels` said out loud, the page's sparkle and a card
   arriving all change, and `panelsShown` is the one answer to what is on the
   screen, which is what the grid draws (`no-chat`, `no-canvas`), and the
   panels' controls with it. On a phone or a tablet one pane shows at a time
   and the corner glyph is the way across, as it has been; those controls
   are not drawn there, and the same two flags say which pane a desk's choice becomes.

   **Per chat.** A conversation keeps the way its panels were left, in this
   browser, so a reload, Back and coming back to it find it the same
   (`KEY_PANELS`). One nobody has chosen for starts with the conversation
   alone, unless it is a task's chat, which has its task's page.

   A chat that is not a task's always opens with the conversation alone,
   whatever it was left with: it has nothing of its own for the canvas, and
   the cards it drew earlier are read as their lines in the conversation
   (`CARDS.bare`). Petar, 26 October 2026 (fr_9feadc24353b): "unless that
   canvas was generated now, or I clicked show in canvas, the canvas should
   be blank and also closed." The canvas used to stand open beside every chat,
   holding whatever an older chat of the same task had drawn there. Nothing
   is deleted or renumbered by this: with the canvas away a card is read in
   the conversation, where it was drawn (`cardsGoOut`).

   And the canvas opens by itself for what is put on it: a card drawn in this
   chat, one shown again, a page, a run or Settings opened from anywhere. */
var KEY_PANELS = 'rouh.panels.v1';
//: How many chats' choices are kept before the oldest is let go.
var PANELS_KEPT = 400;
//: The length of the move, which is the grid's own easing (app.css).
var PANEL_MS = 260;
var PANELS = { chat: '', chosen: false, wantedAt: 0, hold: false, quietUntil: 0,
  timers: /** @type {Record<string, number>} */ ({}) };

// What is on the screen this moment: the conversation unless it is folded
// or the tasks are holding the window, and the canvas unless it was put away
// while the conversation is there to take its place.
function panelsShown() {
  var chat = !!cols.chat && !TASKS_FULL;
  return { chat: chat, canvas: !!cols.canvas || !chat };
}

function canvasShown() { return panelsShown().canvas; }

function panelsAll() {
  var all = safeParse(load(KEY_PANELS));
  return all && typeof all === 'object' ? all : {};
}

// This chat's panels, as the person has just left them.
function panelsKeep() {
  var id = CHATS && CHATS.active;
  if (!id || ADDR.front) return;
  var now = panelsShown();
  var all = panelsAll();
  delete all[id];
  all[id] = now.chat && now.canvas ? 'both' : now.chat ? 'chat' : 'canvas';
  var keys = Object.keys(all);
  for (var i = 0; i < keys.length - PANELS_KEPT; i++) delete all[keys[i]];
  store(KEY_PANELS, JSON.stringify(all));
  PANELS.chosen = true;
}

// Before the page knows which chat it is in: the address. A conversation's
// own address is that chat's, and the front door is a conversation alone;
// any other address names something on the canvas.
function panelsAtLoad() {
  var path = location.pathname;
  var m = /^\/chat\/([^/?#]+)/.exec(path);
  if (m) {
    // A chat's own address is a chat that is not a task's, or one whose
    // task is not known yet: the conversation alone until it is
    // (`panelsForChat`).
    cols.canvas = false;
  } else if (path === '/' || path === '') {
    cols.canvas = false;
  }
}
panelsAtLoad();

/* A chat is on the screen now: its panels as it left them, or as it starts.

   `chat` is the chat's row, or null at the front door. Not along a strip of
   forks, where the canvas is the strip's and nothing moves. */
function panelsForChat(chat) {
  var id = chat && chat.id ? chat.id : '';
  // The page arriving: what it settles into in the next moment is where it
  // opens, not a move anybody should watch.
  if (!S.readyOnce) PANELS.quietUntil = Date.now() + 2000;
  if (id && id === PANELS.chat) return;
  PANELS.chat = id;
  var task = !!(chat && chat.task);
  var saved = id && task ? panelsAll()[id] : '';
  PANELS.chosen = !!saved;
  if (saved) {
    cols.chat = saved !== 'canvas';
    cols.canvas = saved !== 'chat';
  } else {
    cols.chat = true;
    cols.canvas = task;
  }
  // Something was put on the canvas a moment ago and opening it is what
  // brought this chat: a task picked in the navigation loads its page and
  // then its thread. The page is what was asked for.
  if (Date.now() - PANELS.wantedAt < 2500) cols.canvas = true;
  if (narrow()) {
    var shown = panelsShown();
    if (!shown.canvas && typeof pane !== 'undefined' && pane === 'canvas') cols.canvas = true;
  }
  sbApply(Date.now() < PANELS.quietUntil);
  growInput();
}

// The person left this chat with the canvas alone on the screen.
function panelsChoseCanvas() {
  var id = CHATS && CHATS.active;
  return !!id && !narrow() && panelsAll()[id] === 'canvas';
}

/* While a chat is being opened, the canvas it brings with it - a task's own
   page - must not overrule what the person chose for that chat. */
function panelsHold(on) { PANELS.hold = !!on && PANELS.chosen; }

/* Something has been put on the canvas: open it, if it is away.

   A page, a run or Settings opened there is not remembered as this chat's:
   its address brings it back on a reload, and the canvas with it. A card
   drawn in this chat is (`keep`), since the card is the chat's own and is on
   the screen from now on, a reload included. */
function canvasIsWanted(keep) {
  if (PANELS.hold) return;
  PANELS.wantedAt = Date.now();
  if (canvasShown() && cols.canvas) return;
  cols.canvas = true;
  if (keep && PANELS.chosen) panelsKeep();
  sbApply(Date.now() < PANELS.quietUntil);
  growInput();
}

/* The canvas put away when there is nothing on it: no card, no page, no run.
   Pressing Rouh is going to the conversation, and a bare canvas beside it
   is only an empty column. Petar, 26 October 2026 (fr_9feadc24353b): the
   canvas should be blank and also closed unless something was put on it. */
function canvasAwayIfBare() {
  if (narrow() || !cols.canvas || layerOpen()) return;
  var out = $('cards');
  if (out && out.querySelector('.card')) return;
  cols.canvas = false;
  sbApply();
  growInput();
}

/* A press of a panel's Hide, or of the rail a hidden panel leaves. */
function panelsPress(which) {
  var now = panelsShown();
  if (which === 'chat') {
    if (now.chat) { if (now.canvas) chatPutAway(); return; }
    chatIsWanted();
    panelsKeep();
    return;
  }
  if (now.canvas) {
    if (!now.chat) return;
    cols.canvas = false;
  } else {
    cols.canvas = true;
    canvasRefill();
  }
  panelsKeep();
  sbApply();
  growInput();
}

/* The canvas brought back with nothing on it, in a task's chat: its task's
   page is what belongs there, as it does when the chat is opened. Only when
   nothing is: a page left on it while it was away is still there. */
function canvasRefill() {
  var chat = CHATS && CHATS.active ? chatById(CHATS.active) : null;
  if (!chat || !chat.task || layerOpen()) return;
  try { canvasTask(chat.task); } catch (err) { /* the canvas stays bare */ }
  // A task's page takes the window by itself as it loads (`tasksHold`), and
  // the conversation it was opened beside is what was on the screen.
  chatIsWanted();
}

/* Hidden panels keep their width while they are away, so nothing in them is
   laid out again: the conversation keeps its place in the scroll, a page on
   the canvas its own. A panel coming back keeps it for the length of the
   move and is then given the width of its track. Only at a desk: the
   stylesheet reads `--held-w` there and nowhere else. */
function panelHold(node, key, hide, animate) {
  if (!node) return;
  clearTimeout(PANELS.timers[key]);
  if (hide) {
    if (!animate) { node.classList.remove('held'); return; }
    var w = node.getBoundingClientRect().width;
    if (w > 0) {
      node.style.setProperty('--held-w', Math.round(w) + 'px');
      node.classList.add('held');
    }
    return;
  }
  if (!node.classList.contains('held')) return;
  if (!animate) { node.classList.remove('held'); return; }
  PANELS.timers[key] = window.setTimeout(function () {
    node.classList.remove('held');
  }, PANEL_MS + 40);
}

function reducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function panelsPaint(silent) {
  var app = $('app');
  if (!app) return;
  var now = panelsShown();
  var noChat = !now.chat, noCanvas = !now.canvas;
  var wasChat = app.classList.contains('no-chat');
  var wasCanvas = app.classList.contains('no-canvas');
  if (wasChat !== noChat || wasCanvas !== noCanvas) {
    shared.foldMoved = Date.now();
    var animate = !silent && !reducedMotion() && !narrow();
    if (wasChat !== noChat) panelHold($('chatCol'), 'chat', noChat, animate);
    if (wasCanvas !== noCanvas) panelHold($('canvasPanel'), 'canvas', noCanvas, animate);
    if (!animate) app.style.transition = 'none';
    app.classList.toggle('no-chat', noChat);
    app.classList.toggle('no-canvas', noCanvas);
    if (!animate) requestAnimationFrame(function () { app.style.transition = ''; });
    // A card is read on the canvas while there is one, and in the
    // conversation while there is not. After this has been drawn, and not
    // inside it: putting a card out is what may have asked for the canvas.
    if (wasCanvas !== noCanvas) window.setTimeout(cardsSettle, 0);
    // The address names what is on the screen, and the canvas is or is not.
    if (wasCanvas !== noCanvas) addrTouch();
  }
  panelsCtlPaint(now);
}

/* What each panel's controls say. A hidden button is not in the tab order,
   so the one panel left open has no Hide and the panel away has its rail;
   the stylesheet draws them from `no-chat` and `no-canvas`, and this keeps
   the controls a screen reader is given the same. */
function panelsCtlPaint(now) {
  var both = now.chat && now.canvas;
  var set = [['chatHide', !both], ['canvasHide', !both],
             ['railChat', now.chat], ['railCanvas', now.canvas]];
  for (var i = 0; i < set.length; i++) {
    var btn = $(set[i][0]);
    if (!btn) continue;
    var off = /** @type {boolean} */ (set[i][1]);
    if (off) btn.setAttribute('aria-hidden', 'true'); else btn.removeAttribute('aria-hidden');
    btn.tabIndex = off ? -1 : 0;
  }
}

if ($('chatHide')) $('chatHide').addEventListener('click', function () { panelsPress('chat'); });
if ($('canvasHide')) $('canvasHide').addEventListener('click', function () { panelsPress('canvas'); });
if ($('railChat')) $('railChat').addEventListener('click', function () { panelsPress('chat'); });
if ($('railCanvas')) $('railCanvas').addEventListener('click', function () { panelsPress('canvas'); });

// Crossing from a desk to a phone or a tablet: the panel that was alone on
// the desk is the pane, and nothing is held at a width a pane does not have.
var WAS_NARROW = narrow();
window.addEventListener('resize', function () {
  var n = narrow();
  if (n === WAS_NARROW) return;
  WAS_NARROW = n;
  ['chatCol', 'canvasPanel'].forEach(function (id) { if ($(id)) $(id).classList.remove('held'); });
  if (!n) return;
  var shown = panelsShown();
  if (!shown.chat) setPane('canvas');
  else if (!shown.canvas) setPane('chat');
});

// Three sizes of window, and the sidebar is a different thing in each. The
// pane row below has its own listener on the same event; neither knows about
// the other, and neither has to.
window.addEventListener('resize', sbResized);

sbApply(true);
chatRestore();

/* -------------------------------------- one pane at a time, on a phone */

/* Below 900px the conversation and the canvas do not fit beside each other,
   so exactly one of them is on screen: one glyph in the top right corner of
   the window names it, and pressing it moves to the other, the new pane
   sliding in from the side it is on.

   A swipe left or right across the pane did the same until 26 September
   2026, and it went. A thumb scrolling a conversation is never quite
   vertical, and it took the person to the canvas when all they meant was
   to read on. Petar: "There seems to be some kind of slide action that
   opens the canvas while I am on a chat... Can you please remove that? I
   have a canvas button." So the corner is the only way across, and a finger
   on either pane only ever scrolls it.

   That corner was a strip of two labelled tabs across the foot of the
   screen until 21 September 2026. It cost every screen a row of height, on
   the one device with none to spare, to say what the corner beside the
   chat's name says in a glyph.

   The sidebar is not one of these panes. It is navigation: it opens from the
   fold glyph beside the breadcrumb, over whatever is on screen, and closes
   again. It was a third pane until 20 September 2026, which meant reaching
   the navigation replaced what you were reading and there was no way to see
   both at once.

   Which pane it was is kept in this browser beside the folded transcript
   above, so a reload comes back where the person was. Above 900px the
   corner button is not drawn: the attribute is still set and the stylesheet
   ignores it. */
var KEY_PANE = 'rouh.pane.v1';
// Left to right, the same order as the columns on a wide screen: the
// conversation, the canvas. The slide between them comes in from the side
// the pane is on, so it has to say the same thing as the grid.
var PANES = ['chat', 'canvas'];

var pane = (function () {
  var saved = load(KEY_PANE);
  // The conversation, because that is how you talk to it. A browser that
  // last had the runs pane, from before the sidebar stopped being one, comes
  // back to the conversation rather than to a pane that is not there.
  return PANES.indexOf(saved) >= 0 ? saved : 'chat';
})();

function narrow() {
  return !!(window.matchMedia && window.matchMedia('(max-width: 899px)').matches);
}

// The element the pane on screen is made of. The orb sits in its corner, so
// it needs to know which it is.
function paneEl() {
  if (pane !== 'chat') return $('canvasPanel');
  /* The conversation's pane is whichever of its two panels is showing. It
     used to be the transcript and only the transcript, and the moment the
     page's own side of the surface was on instead, the transcript measured
     nothing - so the orb fell back to the corner of the window and sat on
     top of the text box it is supposed to ride above. */
  var ask = $('pagePanel');
  if (ask && !ask.hidden) return ask;
  return document.querySelector('.panel-transcript');
}

// The corner button says both what pressing it does and where the person
// is: the canvas glyph on the conversation, the cross on the canvas. The
// stylesheet picks the glyph off `data-pane`; this says it in words, for
// anybody reading the page rather than looking at it.
//
// And whether the canvas behind it holds anything: a card, or a page, a
// task, a run or Settings opened over it. `holds` turns the glyph's lines
// orange, so the conversation says at a glance that there is something to
// go back to. Petar, 26 September 2026: "if there is anything on canvas,
// can you make the white lines orange from the icon? So something hints me
// something Is there." That is the one thing it says: the dot it wore until
// 24 September said something else, and why it went is in the stylesheet
// beside `#canvasToggle`.
function canvasHolds() {
  var out = $('cards');
  return !!layerOpen() || !!(out && out.querySelector('.card'));
}

function paintPaneButton() {
  var btn = $('canvasToggle');
  if (!btn) return;
  var open = pane === 'canvas';
  var holds = canvasHolds();
  var out = $('cards');
  var borrowed = (CARDS_UP || !cardsGoOut()) && !!(out && out.querySelector('.card'));
  var label = !open ? (holds ? 'Open the canvas, which has something on it' : 'Open the canvas')
    : borrowed && (CARDS_UP || !layerOpen()) ? 'Put this card back in the conversation'
      : layerOpen() ? 'Show the conversation, and keep this open' : 'Show the conversation';
  btn.title = label;
  btn.setAttribute('aria-label', label);
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  btn.classList.toggle('holds', holds);
}

// Said again the moment it changes, rather than by every way of putting a
// card on the canvas or a layer over it remembering to: a card going out or
// coming home is a child of `#cards` arriving or leaving, and a layer is its
// `hidden` going on or off.
(function () {
  if (typeof MutationObserver !== 'function') return;
  var watch = new MutationObserver(function () { paintCovered(); paintPaneButton(); });
  var out = $('cards');
  if (out) watch.observe(out, { childList: true });
  for (var i = 0; i < LAYERS.length; i++) {
    var node = $(LAYERS[i]);
    if (node) watch.observe(node, { attributes: true, attributeFilter: ['hidden'] });
  }
})();

function applyPane() {
  var app = $('app');
  if (!app) return;
  app.setAttribute('data-pane', pane);
  paintPaneButton();
}

function setPane(next) {
  if (PANES.indexOf(next) < 0 || next === pane) return;
  var was = pane;
  pane = next;
  // The pane a phone moves to is a panel the desk will have open too.
  if (next === 'canvas') cols.canvas = true; else cols.chat = true;
  panelsPaint(true);
  applyPane();
  store(KEY_PANE, pane);
  slidePane(was, next);
  // The pane that has arrived is a different size and in a different place
  // from the one that went, and the orb, the text box and a run's terminal
  // all measure themselves against whatever they are in.
  window.dispatchEvent(new Event('resize'));
  // A card that was only on the canvas to be read full screen goes back
  // into the conversation as the conversation comes back, at the place it
  // was read from.
  if (next === 'chat') { cardsUncover(); cardsBackInPlace(); }
}

/* The slide. The pane that arrives comes in from its own side - the canvas
   from the right, the conversation from the left, the order of the columns
   at a desk - and pushes the one that goes off the other way, so a press
   of the corner reads as a move between two places side by side rather than
   as the screen being swapped. Petar asked for exactly that of a card sent
   full screen: "canvas slides sideways to fill screen".

   The pane that goes is `display: none` the moment `data-pane` changes, so
   `pane-leaving` holds it on screen for the length of the slide. Only on a
   phone, and never for somebody who has asked their system for less
   motion: they get the pane at once, faded in as it always was. */
var SLIDE_MS = 240;
var SLIDING = null;

function paneRoot(which) { return which === 'canvas' ? $('canvasPanel') : $('chatCol'); }

function slidePane(was, next) {
  if (SLIDING) SLIDING();
  if (!narrow() || !was || typeof Element.prototype.animate !== 'function') return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var comes = paneRoot(next), goes = paneRoot(was);
  if (!comes || !goes) return;
  var right = PANES.indexOf(next) > PANES.indexOf(was);
  var ease = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
  goes.classList.add('pane-leaving');
  comes.classList.add('pane-arriving');
  var a = comes.animate([{ transform: 'translateX(' + (right ? '100%' : '-100%') + ')' },
                         { transform: 'translateX(0)' }], { duration: SLIDE_MS, easing: ease });
  var b = goes.animate([{ transform: 'translateX(0)', opacity: 1 },
                        { transform: 'translateX(' + (right ? '-30%' : '30%') + ')', opacity: 0.4 }],
                       { duration: SLIDE_MS, easing: ease, fill: 'forwards' });
  var done = false;
  function end() {
    if (done) return;
    done = true;
    SLIDING = null;
    goes.classList.remove('pane-leaving');
    comes.classList.remove('pane-arriving');
    b.cancel();
    // Anything that measured the pane while it was on its way in measured
    // it off the side of the screen - the orb, which is placed against its
    // corner on the next frame, was left out there - so everything is told
    // again, now that the pane is where it stays.
    window.dispatchEvent(new Event('resize'));
  }
  SLIDING = function () { a.cancel(); end(); };
  a.onfinish = end;
  a.oncancel = end;
  // And by the clock as well, in case the animation is never run to its
  // end - a tab put in the background halfway through - since until then
  // the pane that went is still on the page under the one that came.
  window.setTimeout(end, SLIDE_MS + 120);
}

applyPane();

/* One corner, two things to say. On the conversation it opens the canvas
   over the whole screen; on the canvas it is a speech bubble, and it goes
   back to the conversation.

   It is a switch between two places, never a close. Whatever is open on
   the canvas - a task, a page, the Synapse debugger, a run, Settings -
   stays open behind it, and the canvas glyph, orange while it holds
   something, brings back exactly that. Petar, 4 October 2026: "I should
   basically not be closing it but switching between chats (including
   forks) and content." (fr_30f188faa389)

   From 24 September until then it was a cross that closed the layer down
   its own closer and only gave the conversation back once nothing was
   left, so the canvas glyph opened onto a bare canvas and the task had to
   be found again from the task browser. Before that it had kept the layer,
   but beside the layer's own cross, and two crosses doing two things were
   the trouble then (see `#tasksClose` in the stylesheet). The layer's own
   cross is still not drawn on a phone, and nothing there needs it: opening
   anything else from the navigation puts it in place of what was open.

   A card opened full screen from the conversation is not one of those
   layers: giving the conversation back is what puts it back in its place
   there (`cardsBackInPlace`, in `setPane`). On a phone that reads cards on
   the canvas (`cardsGoOut`) the card stays out, as it would at a desk, and
   the glyph the corner turns back into is orange. */
function canvasCross() {
  setPane('chat');
}

if ($('canvasToggle')) {
  $('canvasToggle').addEventListener('click', function () {
    if (pane === 'canvas') canvasCross();
    else setPane('canvas');
  });
}

// Which pane the assistant means when it is asked to open or close a column.
// On a wide screen "hide the transcript" folds a column away; there are no
// columns to fold here, so the same words mean "show me this one instead".
// Asking for the sidebar is not one of them: the sidebar opens over whatever
// pane is showing and does not replace it, so `setCols` has already done the
// whole of that by the time this is asked.
function paneForCols(want) {
  if (want.chat === true) return 'chat';
  if (want.chat === false) return 'canvas';
  if (want.canvas === true) return 'canvas';
  if (want.canvas === false) return 'chat';
  return '';
}

/* -------------------------------- the screen, when a keyboard is over it */

/* On a phone the page is exactly the height of the window and nothing on it
   scrolls as a page, which is what stops the scroll-within-a-scroll. That
   only works while "the window" and "what you can see" are the same thing,
   and the moment the on-screen keyboard comes up they are not. iOS does not
   shrink the layout viewport for the keyboard: `100dvh` still measures all
   the way down to the foot of the glass, so the text box is underneath the
   keys, and the page cannot be scrolled to reach it because it is
   deliberately not scrollable.

   `window.visualViewport` is the part that is left, and it is the thing to
   measure. Its height goes into `--screen-h`, the stylesheet builds the page
   out of that instead of `100dvh`, and the text box ends up sitting on top
   of the keyboard where a person expects it.

   A pinch zoom shrinks the visual viewport as well, and rebuilding the page
   around a magnifying glass is not what anybody means by zooming in, so a
   scale above 1 is left alone and the window is the honest answer. */

/* The belt to the meta tag's brace: pin the width in numbers.

   Safari had widened the layout viewport to 506 CSS pixels on a 430 pixel
   screen and drawn everything at 0.85, with nothing on the page wider than
   the page's own shell - so there was nothing to find and nothing to fix by
   making things narrower. `minimum-scale=1` in the meta tag forbids the
   zoom-out that does it. This checks whether it was listened to, and if the
   layout viewport still does not match the glass, says the width as a
   number instead of as `device-width`, which leaves nothing to interpret.

   `screen.width` is the glass and does not move when Safari zooms, which is
   what makes the comparison meaningful. Once per load and once per turn of
   the phone, never in a loop: if the second attempt does not take either,
   the page is not the thing deciding this. */
function pinTheViewport() {
  var glass = screen.width;
  var meta = document.querySelector('meta[name="viewport"]');
  if (!glass || !meta) return;
  var laid = document.documentElement.clientWidth;
  if (!laid || glass / laid > 0.99) return;
  if (meta.getAttribute('data-pinned-at') === String(glass)) return;
  meta.setAttribute('data-pinned-at', String(glass));
  meta.setAttribute('content',
    'width=' + glass + ', initial-scale=1, minimum-scale=1, shrink-to-fit=no,' +
    ' viewport-fit=cover, interactive-widget=resizes-content');
}

// What a person can see of the window, in pixels.
function screenHeight() {
  var vv = window.visualViewport;
  if (vv && vv.scale <= 1.01 && vv.height > 0) return vv.height;
  return window.innerHeight;
}

/* Putting the page back where it belongs.

   Nothing on a phone is a page that scrolls: the html element and the body
   are both the height of the visible window and both hide their overflow, so
   a scroll offset of any kind is the browser having shoved the document
   about to lift a focused field clear of the keyboard. It has nothing to
   lift it out of the way of any more, so it goes back to zero.

   This used to do more, and the more was worse than the bug. If Safari had
   panned the layout viewport up under the visual one it wrote the offset
   into a `--screen-top` that brought the pinned body down to match. The
   offset it read is a moment in the middle of Safari moving the page, and
   the value latched: Safari panned back, no further event came, and the body
   stayed pinned three hundred pixels down its own screen with nothing but
   background above it. That is the black screen of 20 September 2026, and
   scrolling up to find the message box is what a person had to do about it.
   Pinning the page is what stops the pan happening at all, so there is
   nothing left to compensate for and nothing left to latch. */
/* Measured on an iPhone on 20 September 2026, and these are the numbers the
   three failed attempts were each missing a piece of.

   The layout viewport is 912 pixels tall and stays 912 whatever the keyboard
   does. It is the whole of the area Safari can slide the window over, and
   `document.documentElement.clientHeight` is it.

   The visual viewport is what the person can see. With the keyboard up it is
   428, and `visualViewport.offsetTop` said 457: Safari had slid the window
   457 pixels down the page. `window.scrollY` was 0 at the same moment, every
   time, which is the fact that had been guessed wrong twice. It is not the
   document scrolling. Nothing JavaScript can do puts it back, and every
   `scrollTo(0, 0)` written here was aimed at something that was never moving.
   The page has to go to where the window is instead.

   So a page 428 tall pinned at the top of a 912 tall layout viewport, with
   the window showing 457 to 885 of it, is a person looking at a part of the
   page that has nothing on it. That is the black screen, and it is the whole
   of the black screen.

   The other number in the same readings: when Safari collapses its toolbars
   it zooms the page out to 0.85, and `visualViewport.height` then reports up
   to 1218 - more than the 912 the page has to live in. Written straight into
   the height, that is a page taller than the window, which is the other half
   of the report: "the page is too big and I have to scroll to get to the
   inputs". Both are fixed by measuring against the layout viewport and never
   trusting the visual one to be smaller than it. */
// Whether a field of this page's own has the focus, which is the only time
// an on-screen keyboard can be standing in for part of the window.
function typingHere() {
  /** @type {any} */
  var el = document.activeElement;
  if (!el || el === document.body) return false;
  var tag = el.tagName;
  if (tag === 'INPUT') return !/^(button|checkbox|color|file|hidden|image|radio|range|reset|submit)$/i.test(el.type);
  return tag === 'TEXTAREA' || tag === 'SELECT' || !!el.isContentEditable;
}

function screenMetrics() {
  var vv = window.visualViewport;
  // The pannable area. Never the visual viewport, which lies in both
  // directions: smaller under a keyboard, larger under a zoom-out.
  var page = document.documentElement.clientHeight || window.innerHeight;
  if (!vv) return { page: page, seen: page, top: 0 };
  /* Nobody typing, no keyboard: the page is the whole window.

     The visual viewport is only ever asked while one of this page's own
     fields has the focus, because that is the only time a keyboard can be
     over it for a reason this page has to answer. Otherwise its height is
     not believed at all. Petar, 3 October 2026, on an iPad
     (fr_56dcf4e03baf): "There is some kind of line that breaks my page into
     two", and then "Still have that split after refresh". The page stopped
     about 660 pixels down a window 1080 tall, the canvas's black edge drawn
     across it as a line and the bare background under it, and a reload did
     not mend it: the height came from the visual viewport, nothing on the
     page had the focus, and the layout viewport - which the navigation
     button, fixed to the foot of it, showed was the whole window - was the
     number that should have been used. A field inside the canvas's frame
     is not one of this page's: the frame is the active element then, and
     the layout viewport, which `interactive-widget=resizes-content` shrinks
     for a keyboard, is the measure for it. */
  if (!typingHere()) return { page: page, seen: page, top: 0 };
  var seen = Math.round(vv.height);
  /* Zoomed out - which Safari does to itself as it collapses its toolbars -
     the visual viewport covers more of the page than there is window to put
     it in, and reports a height the page cannot have: 1218 on a 912 layout
     viewport, measured. That one is clamped. At a scale of 1 it is the
     honest number and is taken as it is, even when the layout viewport is a
     frame behind it: clamping it there held the page at 432 for a frame
     after the keyboard had gone and the window was 731 again, which is 299
     pixels of nothing at the foot of the screen. */
  if (vv.scale < 0.99) seen = Math.min(seen, page);
  /* Where the window is, and nothing more. This used to be clamped to what
     was left of the layout viewport below the window, on the assumption
     that the layout viewport does not move when a keyboard arrives. With
     `interactive-widget=resizes-content` it does: measured at the moment
     Safari had slid the window 299 pixels down, the layout viewport had
     already shrunk to the same 432 as the window, so the clamp worked out
     as 0 and pinned the page 299 pixels above what could be seen. A
     screenful of nothing, for as long as the keyboard took to arrive. */
  var top = Math.max(0, Math.round(vv.offsetTop || 0));
  return { page: page, seen: seen, top: top };
}

(function () {
  var vv = window.visualViewport;
  if (!vv) return;
  var root = document.documentElement;

  function setScreenHeight() {
    /* Zoomed in, by a pinch or by Safari deciding a field wanted a closer
       look. Rebuilding the page around a magnifying glass is not what
       anybody means by zooming in, so the page stops being pinned and goes
       back to being an ordinary document that pans the ordinary way.

       Leaving it pinned was the other half of 20 September 2026: the body
       stayed `position: fixed` at the full height of the window while the
       person was looking at a third of it through a magnifying glass, so
       panning around went off the bottom of the page into the background and
       the way back to the message box was not obvious. A page in the normal
       flow pans over its own content and cannot do that. */
    var zoomed = vv.scale > 1.01;
    root.classList.toggle('zoomed', zoomed);
    if (zoomed) {
      root.style.removeProperty('--screen-h');
      root.style.removeProperty('--screen-top');
      return;
    }
    /* Both are written every single time, including when they are 0. An
       earlier version wrote the offset only when it was worth writing and
       left it behind when it was not, which is a value that can stick; this
       cannot, because every event that could change it rewrites it. */
    var m = screenMetrics();
    root.style.setProperty('--screen-h', m.seen + 'px');
    root.style.setProperty('--screen-top', m.top + 'px');
    // How tall the text box is allowed to grow is a share of the screen, and
    // the screen has just changed size.
    growInput();
  }

  /* Every measurement is read once more after the screen has had time to
     settle, and that later reading is the one that stays.

     Petar, 3 October 2026, on an iPad, with a page on the canvas
     (fr_56dcf4e03baf): "There is some kind of line that breaks my page into
     two and cause problems. We shouldn't have two sections". The page ended
     a keyboard's height above the foot of the glass, with the bare
     background under it and the navigation button alone at the bottom: the
     height read while a keyboard was up, or on its way down, had stayed
     after it had gone. Safari tells the page the keyboard is moving, but
     nothing promises an event once it has stopped, and a field inside the
     canvas's frame never reaches the focus handlers below at all. So every
     event that could move the window also books two later readings, and a
     window resize, focus leaving a field, focus coming back from the frame
     and the page being shown again are each such an event. */
  var settleTimers = [];
  function measureAndSettle() {
    setScreenHeight();
    settleTimers.forEach(clearTimeout);
    settleTimers = [setTimeout(setScreenHeight, 300), setTimeout(setScreenHeight, 900)];
  }

  vv.addEventListener('resize', measureAndSettle);
  vv.addEventListener('scroll', measureAndSettle);
  window.addEventListener('resize', measureAndSettle);
  window.addEventListener('focus', measureAndSettle);
  window.addEventListener('blur', measureAndSettle);
  window.addEventListener('pageshow', measureAndSettle);
  document.addEventListener('focusout', measureAndSettle);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) measureAndSettle();
  });
  window.addEventListener('orientationchange', function () {
    // The measurement is wrong until the turn is over, and the glass is a
    // different width now, so the width is worth pinning again.
    setTimeout(function () { pinTheViewport(); setScreenHeight(); }, 120);
  });
  /* A field taking focus is the moment the browser does the shoving, and it
     does it after the focus event rather than during it - sometimes twice,
     once for the scroll into view and once when the keyboard has finished
     coming up. So the page is put back on the way out of this turn, on the
     next frame, and once more when the keyboard is up. */
  document.addEventListener('focusin', function (e) {
    var tag = e.target && /** @type {HTMLElement} */ (e.target).tagName;
    if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') return;
    setScreenHeight();
    requestAnimationFrame(setScreenHeight);
    setTimeout(setScreenHeight, 180);
    setTimeout(setScreenHeight, 420);
    setTimeout(setScreenHeight, 1200);
  });
  window.addEventListener('scroll', setScreenHeight, { passive: true });
  pinTheViewport();
  setScreenHeight();
}());

/* A button tapped while a field is typed in is pressed on that one tap:
   `press.js`, which this page loads beside the module and Rouh puts into every
   page it frames (fr_43689e0df2c9, fr_f180995a3a50). */

/*
 * The microphone off and on, and the only two callers of the two functions
 * that own it.
 *
 * Off is not mute. There is no such thing here as a microphone that is open
 * but not listening: off ends the track, so the dot in the phone's status
 * bar goes out, and on asks the browser for a new one.
 *
 * It returns a promise so that a control which needs the microphone before
 * it can do its job - hold to talk, dictation - can wait for it.
 */
function setMic(muted) {
  muted = !!muted;
  // Turning the microphone off mid-dictation is being done with it.
  if (muted && S.dictating) setDictation(false);
  S.muted = muted;
  if (muted) {
    releaseMic();
    micSays();
    return Promise.resolve();
  }
  // Started first, so the button can say it is asking rather than looking
  // pressed and doing nothing while an iPhone shows its permission prompt.
  var asking = acquireMic();
  micSays();
  return asking.then(function () {
    micSays();
  }, function (err) {
    S.muted = true;
    releaseMic();
    micSays();
    micRefused(err);
  });
}

//: What went wrong the last time the microphone was asked for, if anything.
//: Cleared by the next attempt, so the button never goes on complaining
//: about something that has since worked.
var micTrouble = '';

// What the microphone button says. Three things decide it: whether the
// speaker is waiting for a press, what the microphone is doing, and whether
// the last attempt at one failed. The press wins, because a reply nobody can
// hear is the larger silence of the two and it is the one the button can do
// something about. A button that has already said there is no microphone at
// all is left alone.
function micSays() {
  var mb = $('micBtn');
  if (!mb || mb.disabled) return;
  var opening = !!MIC.opening && !S.micReady;
  var on = S.micReady && !S.muted;
  mb.classList.toggle('off', !on);
  mb.classList.toggle('opening', opening);
  mb.setAttribute('aria-pressed', on ? 'false' : 'true');
  var text = mb.classList.contains('needs-press')
    ? 'Press to turn on the voice - this browser will not play sound yet'
    : opening ? 'Asking for the microphone'
    : on ? 'Microphone on'
    : micTrouble || 'Turn on the microphone';
  $('micLabel').textContent = text;
  mb.title = on ? 'Turn the microphone off - it is closed, not muted' : text;
}

// Said on the screen, not to the console. A microphone that will not open is
// the one failure a person cannot see for themselves: nothing happens, and
// without this they would be left talking to a page that is not listening.
function micRefused(err) {
  var why = err && err.name === 'NotAllowedError'
    ? 'this browser is not allowing it. Turn the microphone back on for this'
      + ' site in its settings, then press the microphone button again.'
    : (err && err.message ? err.message : 'the browser refused.');
  notify('The microphone did not open: ' + why + ' Typing still works.', { tone: 'error' });
  micTrouble = 'The microphone did not open. Press to try again.';
  micSays();
}

$('micBtn').addEventListener('click', function () {
  // `setMic` is given the state to go to, and its argument is "off". Open
  // now means turn it off; anything else means open one, and a press is
  // also all a browser ever wanted before it would start the speaker.
  micTrouble = '';
  setMic(S.micReady && !S.muted);
});

// A voice control pressed while the microphone is closed opens it first, and
// then does what it was pressed for. This is the only reason any of them is
// allowed to reach `acquireMic`.
function withMic(then) {
  if (S.micReady && !S.muted) { then(); return; }
  setMic(false).then(function () {
    if (S.micReady && !S.muted) then();
  });
}

//: `chosen` is true only when a person pressed the button. Everything else
//: - the value restored at load, and the machine's setting arriving with
//: `ready` - is a default, and a default must never look like a decision.
function setVoice(on, chosen) {
  cfg.voiceReply = !!on;
  if (chosen) cfg.voiceChosen = true;
  saveCfg();
  $('voiceBtn').setAttribute('aria-pressed', on ? 'true' : 'false');
  $('voiceBtn').classList.toggle('off', !on);
  $('voiceLabel').textContent = on ? 'Voice replies on' : 'Voice replies off';
  $('voiceBtn').title = $('voiceLabel').textContent;
  if (on) S.toldAboutVoice = false;
  send({ type: 'set_mode', voice_reply: !!on });
  if (!on) {
    stopPlayback();
    // Nothing is owed any more, so the complaint about a silent speaker goes
    // with it. Switching the voice back on starts the question again.
    speakerReady();
  } else {
    // Switching the voice off stops playback, which arms the tail-drop. It
    // must not outlive the switch: a reply already in flight when the button
    // goes back on is one the person has just asked to hear.
    PB.dropTailUntil = 0;
  }
}

$('voiceBtn').addEventListener('click', function () {
  setVoice(!cfg.voiceReply, true);
  // Switching the voice on is itself the press a browser is waiting for, and
  // without this line it is the one press that gets wasted: `unlockAudio`
  // runs from a listener on the document, which sees the click before this
  // handler does, and at that moment voice replies are still off, so it
  // declines to build a speaker. Then the next reply arrives with no press
  // in hand. Asking again here spends the same press, now that the answer
  // has changed.
  if (cfg.voiceReply) unlockAudio();
});
setVoice(cfg.voiceReply);

// The Stop button. Escape does the same thing from the keyboard.
$('stopBtn').addEventListener('click', function () { stopTheTurn(); });
showStop();
// And the beat that takes it away again when the turn it belongs to ended
// without saying so. See `watchTheTurn`.
setInterval(watchTheTurn, 1000);

/* ------------------------------------------------------- the composer */

var input = $('input');
var composerBox = $('composerBox');
var composerControls = $('composerControls');

// The text, the level meter and the control line are three rows of one
// column, each with its own room: the stylesheet does that, and nothing here
// needs to measure the controls to keep the text clear of them. What is left
// to decide is how tall the text is allowed to get, which is the only thing
// the control line's height still changes - the taller it is, the less of
// the window is left for the text.
//
// Grows upward, because the composer is pinned to the bottom of the column
// and the transcript above it gives up the height. Fifteen lines, or nearly
// half the window, whichever comes first, and then it scrolls instead of
// growing (`growToLines`).
function growInput() {
  if (!input) return;
  // The meter and the controls under the text are part of the block the
  // person sees, so the share of the window is shared with them.
  var below = 0;
  if (composerBox) below = Math.max(0, composerBox.clientHeight - input.offsetHeight);
  growToLines(input, Math.round(screenHeight() * 0.45) - below);
}

if (input) {
  input.addEventListener('input', growInput);
  input.addEventListener('input', forkBtnPaint);
  input.addEventListener('keydown', function (e) {
    // Ctrl+Shift+Enter, or Cmd+Shift+Enter on a Mac, sends as a fork: the
    // same as Fork beside Send (`rouh/forks.py`).
    if (e.key === 'Enter' && e.shiftKey && (e.ctrlKey || e.metaKey) && !e.isComposing) {
      e.preventDefault();
      sendTyped(true);
      return;
    }
    // Ctrl+Enter, or Cmd+Enter, sends (`isSendKey`). Enter on its own is the
    // new line the box makes of it, and `growInput` makes room for it.
    if (isSendKey(e)) {
      e.preventDefault();
      $('composer').requestSubmit ? $('composer').requestSubmit() : sendTyped();
    }
  });
  input.placeholder = withSendKeys(input.placeholder);
  $('sendBtn').title = 'Send (' + sendKeys() + ')';
}

// Anywhere on the block, including the empty space on the control line,
// means "put the cursor back in the text".
if (composerBox) {
  composerBox.addEventListener('mousedown', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('button, select, a, textarea, input, label')) return;
    e.preventDefault();
    if (input) input.focus();
  });
}

window.addEventListener('resize', growInput);
if (window.ResizeObserver && composerControls) {
  new ResizeObserver(growInput).observe(composerControls);
}
growInput();

/* On a phone the navigation button stands just above the text box, never on
   it. It is fixed in the bottom left corner, and the box at the foot of the
   conversation grows a line at a time, gains a row of attachments and moves
   up over the keyboard, so where "just above" is has to be measured. It sat
   level with the line that was typed on until 30 September 2026, with the
   words starting past it; Petar: "Navigation button sits on top of the
   input. It needs to be above it".

   Its place is the stylesheet's, on every screen: just above where a
   one-line box rests at the foot, whether or not there is a box there. It
   sat on the stylesheet's lower corner wherever there was no box until
   1 October 2026, so it jumped between a chat and the welcome or the
   canvas; Petar: "the navigation button is moving up and down depending on
   whether we have input. Can we just keep it always above the input and
   not have a shift?" It only ever goes higher than that place, and only
   while a box docked at the foot of the conversation reaches above it -
   more lines, attachments, or the keyboard - so it is never on the box.
   The one measurement corrects itself against where the button really
   landed, so it is right whatever the page is fixed to.

   The open drawer is measured exactly as the page under it is, so the cross
   that closes it is the button that opened it, in the same spot. Until
   1 October 2026 the drawer put it back at the stylesheet's corner, lower
   down, with the person's name under it; Petar: "make the close button of
   the navigation to be in the exact same place as the open navigation
   button. Everything in there should move up above the close button." So
   how far the drawer's links have to stop above its foot, for the button
   and its gap to fit between them, is handed to the stylesheet as
   `--fold-nav-room`. The person's name stays at the very foot, under the
   button ("Profile should remain on the bottom of the sidebar though"). */
var FOLD_GAP = 8;
function placeFold() {
  var btn = $('sidebarToggle'), app = /** @type {HTMLElement} */ (document.querySelector('.app'));
  if (!btn || !app) return;
  // Hidden - the Gene therapy sheet takes it off the page - it has no box to
  // measure, and a box of nothing read as its place moved it a screen's
  // height off the bottom: the sheet closed onto a page with no way to the
  // navigation. Petar, 1 October 2026, on an iPad: "when I open feedback
  // then close it the menu button is missing". It is measured again the
  // moment it is back (the marks watched below).
  if (!btn.getClientRects().length) return;
  /** @type {HTMLElement | null} */
  var box = null;
  if (window.matchMedia('(max-width: 899px)').matches) {
    /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('.col-chat:not(.welcome) .composer')).forEach(function (c) {
      if (!box && c.getBoundingClientRect().height > 0) box = c;
    });
  }
  // A box gliding to the foot from the welcome is somewhere it is not
  // staying: the button waits where it is, and is placed when the box has
  // landed (`welcomeGlide`).
  var gliding = /** @type {HTMLElement | null} */ (box);
  if (gliding && gliding.getAnimations && gliding.getAnimations().length) return;
  app.classList.toggle('fold-docked', !!box);
  // Back to its own place first, then up only if the box reaches it.
  btn.style.removeProperty('bottom');
  if (box) {
    var want = box.getBoundingClientRect().top - FOLD_GAP;
    var now = parseFloat(getComputedStyle(btn).bottom) || 0;
    var off = btn.getBoundingClientRect().bottom - want;
    if (off >= 0.5) btn.style.bottom = Math.round(now + off) + 'px';
  }
  var foot = $('sbFoot'), fr = foot && foot.getBoundingClientRect();
  if (fr && fr.height > 0) {
    // Wherever the navigation is a drawer what stands there in it, open, is
    // the orb's row, taller than the circle and round the same centre.
    var br = btn.getBoundingClientRect(), row = SB.size !== 'wide';
    var half = row ? orbRowHeight(br.height) / 2 : br.height / 2;
    var top = br.top + br.height / 2 - half;
    var room = Math.max(0, Math.round(fr.top - top + FOLD_GAP));
    app.style.setProperty('--fold-nav-room', room + 'px');
    // And under the row, Rouh and Gene therapy side by side on one line
    // (`.sb-under` in app.css), in the room between it and the person's name.
    if (row) app.style.setProperty('--fold-under-top', Math.round(top + 2 * half + 2) + 'px');
  }
}
var foldQueued = false;
function queueFold() {
  if (foldQueued) return;
  foldQueued = true;
  requestAnimationFrame(function () { foldQueued = false; placeFold(); });
}
window.addEventListener('resize', queueFold);
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', queueFold);
  window.visualViewport.addEventListener('scroll', queueFold);
}
if (window.ResizeObserver) {
  var foldWatch = new ResizeObserver(queueFold);
  document.querySelectorAll('.col-chat .composer').forEach(function (c) { foldWatch.observe(c); });
}
// Which pane is showing, the welcome coming and going, the drawer opening,
// the Gene therapy sheet and board closing and giving the button back: each
// moves the box, or the button, without changing the box's size.
if (window.MutationObserver) {
  var foldMarks = new MutationObserver(queueFold);
  var foldApp = document.querySelector('.app');
  if (foldApp) foldMarks.observe(foldApp, { attributes: true, attributeFilter: ['data-pane', 'data-sb', 'data-gt', 'data-board'] });
  document.querySelectorAll('.col-chat').forEach(function (c) {
    foldMarks.observe(c, { attributes: true, attributeFilter: ['class', 'data-chat'] });
  });
}
queueFold();

/* `asFork` is Fork beside Send, or Ctrl+Shift+Enter: the same words, asked
   in a new fork of this chat instead of in it (`rouh/forks.py`). The fork
   opens in every tab, and this one draws the words there once it has
   (`forkTypedArrived`), the way it draws them here for Send. */
function sendTyped(asFork) {
  asFork = asFork === true;
  // The box is asking for a picture rather than a reply.
  if (PICS.on && !asFork) { sendPicture(); return; }
  var text = input.value.trim();
  var files = attReady();
  // A message can be a screenshot with nothing typed under it.
  if (!text && !files.length) return;
  // Sent before the conversation it is for is on the screen: it is held, on
  // the screen as the person's own, and goes the moment it is (`earlyHold`).
  if (!asFork && !files.length && !conversationUp()) { earlyHold(text); return; }
  // Sent while an answer is being written, it waits for the model to read it
  // at its next step rather than stopping the answer (`drawWaiting`). A fork
  // is a new chat asked from this one as it stands, which it does not yet.
  var steer = S.busy && !asFork;
  if (S.busy && asFork) return;
  // A fork is of a chat with something in it, and Fork is only drawn in one.
  // The keys can still be pressed in an empty one, and a press that does
  // nothing has to say why.
  if (asFork && ($('forkBtn').hidden || ADDR.front)) {
    notify('There is nothing in this chat to fork yet. Send it as it is, and fork from the answer.',
      { tone: 'warning' });
    return;
  }
  // Nothing has been said at the front door yet, so there is no conversation
  // for this to go into. Saying it opens one, and then this runs again with
  // the box exactly as the person left it (see 10g).
  if (freshChatFirst(sendTyped)) return;
  // Something is still going up. Rather than refuse, remember that send was
  // pressed and go by itself the moment the last one settles.
  if (attUploading()) {
    shared.sendWhenUploaded = asFork ? 'fork' : true;
    notify('Sending as soon as the upload finishes.', { tone: 'info' });
    return;
  }
  var broken = shared.attached.length - files.length;
  var ids = files.map(function (a) { return a.id; });
  /** @type {import('./protocol').ToServer<'fork'> | import('./protocol').ToServer<'text'>} */
  var msg = asFork ? { type: 'fork', from: CHATS.active, text: text, attachments: ids }
    : { type: 'text', text: text, attachments: ids };
  // The page's own name for a message that waits, which the server says back
  // when the model has read it (`steer_taken`).
  var steerId = steer ? 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8) : '';
  if (steerId) /** @type {import('./protocol').ToServer<'text'>} */ (msg).steer = steerId;
  // An answer from a task's page goes with the words it was sent as, and
  // only while they are still those words (`taskSaidIt`).
  if (!asFork && shared.TYPED_ANSWER && shared.TYPED_ANSWER.text === text) {
    /** @type {import('./protocol').ToServer<'text'>} */ (msg).answers = shared.TYPED_ANSWER.answers;
  }
  shared.TYPED_ANSWER = null;
  if (!send(msg)) {
    notify('Not connected, so that message was not sent. It will not be queued.', { tone: 'error' });
    return;
  }
  if (broken > 0) {
    notify(broken + (broken === 1 ? ' file was' : ' files were') +
           ' not attached, so ' + (broken === 1 ? 'it was' : 'they were') + ' left out.', { tone: 'warning' });
  }
  input.value = '';
  growInput();
  endUtterance('typed', true);
  // The answer being written goes on being written above it.
  if (!steerId) closeAssistant();
  // The chips move from above the composer into the message, drawn from the
  // server's own copy so what is on screen is what was actually stored.
  /** @type {Array<{id: string, name: string, size: number, media_type: string, kind: string, session_id?: string}>} */
  var drawn = files.map(function (a) {
    return {
      id: a.id, name: a.name, size: a.size,
      media_type: a.media_type || '', kind: a.kind || 'file'
    };
  });
  clearAttachments();
  if (asFork) {
    // Drawn in the fork, which is not open yet. Nothing else may be sent
    // meanwhile, the same as after Send. The files are kept under this
    // chat, where they were attached, so that is where the fork reads
    // them from: its own has none, and a picture read from there was a
    // broken one.
    var here = CHATS.active;
    drawn.forEach(function (f) { f.session_id = here; });
    FORKS.typed = { from: here, text: text, files: drawn };
    setBusy(true);
    // And it opens on the right now, not when the server has made it.
    forkComeNow({ text: text });
    return;
  }
  if (steerId) { drawWaiting(text, drawn, steerId); return; }
  drawTyped(text, drawn);
}

/* Typed and sent before the conversation was there (23 October 2026).

   The box is on the screen from the very first paint, and the conversation
   comes when the handshake does. Petar could not tell whether what he typed
   in that moment would go to the right chat, and it did not go at all: the
   page said "Not connected, so that message was not sent", or, once the
   socket was open, sent it into whichever conversation the server opened
   before the address had been answered. So a message sent before then is
   held here, bound to the chat the address names, and drawn at once as the
   person's own, marked as sending. When that conversation is on the screen
   it is sent there, as if it had just been typed. If the page has by then
   gone somewhere else - another chat pressed meanwhile, or a chat that is
   not there any more - it is not sent anywhere: the words go back into the
   box, and the page says why. */
var EARLY = { list: /** @type {Array<{text: string, chat: string, path: string, turn: any}>} */ ([]), timer: 0 };

// Whether a message sent now goes into the conversation the address names.
function conversationUp() {
  return S.readyHere && !!S.ws && S.ws.readyState === WebSocket.OPEN && !S.switching
    && !ADDR.wanted && !!CHATS.active;
}

/** @param {string} text */
function earlyHold(text) {
  EARLY.list.push({ text: text, chat: tabChatWanted(), path: location.pathname, turn: earlyDraw(text) });
  input.value = '';
  growInput();
  // Asked again every moment while anything is held, besides the handshake
  // and the switch that usually let it go.
  if (!EARLY.timer) {
    EARLY.timer = window.setInterval(function () {
      if (!EARLY.list.length) { clearInterval(EARLY.timer); EARLY.timer = 0; return; }
      earlyFlush();
    }, 400);
  }
}

/** @param {string} text */
function earlyDraw(text) {
  var turn = newTurn('You', 'user');
  drawWords(turn.body, text);
  turn.turn.classList.add('sending');
  turn.turn.appendChild(el('div', 'turn-sending', 'Sending\u2026'));
  scrollDown(true);
  return turn;
}

// Off the screen before the conversation is drawn under it, which draws only into an empty one.
function earlyLift() {
  EARLY.list.forEach(function (x) { if (x.turn && x.turn.turn) x.turn.turn.remove(); x.turn = null; });
}

// The conversation is here: what was held goes, as one message, or back into the box.
function earlyFlush() {
  if (!EARLY.list.length) return;
  if (!conversationUp()) {
    // Still on its way: still on the screen, under whatever was drawn meanwhile.
    EARLY.list.forEach(function (x) {
      if (!x.turn || !x.turn.turn || !x.turn.turn.isConnected) x.turn = earlyDraw(x.text);
    });
    return;
  }
  var held = EARLY.list;
  EARLY.list = [];
  held.forEach(function (x) { if (x.turn && x.turn.turn) x.turn.turn.remove(); });
  var text = held.map(function (x) { return x.text; }).join('\n\n');
  var moved = held.some(function (x) {
    return (x.chat && x.chat !== CHATS.active) || x.path !== location.pathname;
  });
  if (moved || S.busy || !send({ type: 'text', text: text, attachments: [] })) {
    input.value = text + (input.value.trim() ? '\n\n' + input.value : '');
    growInput();
    notify(moved ? 'Not sent: the page went to another conversation before it was ready. Your words are back in the box.'
      : 'Not sent yet: your words are back in the box.', { tone: 'warning' });
    return;
  }
  endUtterance('typed', true);
  drawTyped(text, []);
}

// A message this tab typed, on the screen as it was sent, and the turn it
// starts.
function drawTyped(text, files) {
  T.typed = newTurn('You', 'user');
  drawTurnFiles(T.typed, files);
  drawWords(T.typed.body, text);
  fitActs(T.typed.turn);
  scrollDown(true);
  setState('thinking');
  // Nothing else may be sent until the reply lands. Typing carries on.
  setBusy(true);
}

$('composer').addEventListener('submit', function (e) {
  e.preventDefault();
  sendTyped();
});
// Send pressed before this code had loaded (index.html), carried out once every module
// after this one has run too: the modules run one after another in one go, and sending
// now would reach for the picture controls and the attachments before they exist.
window.rouhComposer = true;
if (window.rouhSendPressed) {
  window.rouhSendPressed = false;
  setTimeout(function () { sendTyped(); }, 0);
}

/* The pill takes the reader to the very end of the conversation, and does
   nothing else.

   It used to put the cursor in the text box as well, and on a phone that is
   the keyboard coming up: the window shrinks by the keyboard's height from
   the bottom, the conversation is cut short by exactly that much, and the
   last thing said is under the text box again. Petar, 23 September 2026:
   "should bring me down all the way, but not activate the keyboard and
   input". So focus is left wherever it was - a press that is refused on
   mousedown is one that does not move it, which is what keeps a keyboard
   that was already up from going down again as well.

   And the end is held for a moment after the press, in case the
   conversation is still growing when it lands: a picture coming in, the
   last of a card being drawn. The reader scrolling away ends that at once,
   and a reply still being written is followed by scrollDown() as ever. */
var jumpBtn = $('jumpLatest');
var jumpHold = 0;
function toLatest() {
  var t = transcriptEl();
  if (!t) return;
  scrollDown(true);
  var mine = ++jumpHold, at = t.scrollTop, until = Date.now() + 1500;
  (function hold() {
    if (mine !== jumpHold || !shared.stick) return;
    // Growing leaves scrollTop where it was; only the reader moves it up.
    if (t.scrollTop < at - 1 && !atBottom(1)) return;
    t.scrollTop = t.scrollHeight;
    at = t.scrollTop;
    if (Date.now() < until) requestAnimationFrame(hold);
  }());
}
if (jumpBtn) {
  jumpBtn.addEventListener('mousedown', function (e) { e.preventDefault(); });
  jumpBtn.addEventListener('click', function () {
    // Pressed from the keyboard, the focus is on the pill, which is about to
    // go. It goes to the conversation it was in rather than to nowhere. Asked
    // first, because the browser drops it the moment the pill is laid out
    // as hidden, which the scroll below does.
    var had = document.activeElement === jumpBtn;
    toLatest();
    if (had) transcriptEl().focus({ preventScroll: true });
  });
}
transcriptEl().addEventListener('scroll', onTranscriptScroll, { passive: true });
['wheel', 'touchstart', 'touchmove', 'keydown', 'pointerdown'].forEach(function (kind) {
  transcriptEl().addEventListener(kind, readerHand, { passive: true });
});
['pointerup', 'pointercancel'].forEach(function (kind) {
  window.addEventListener(kind, readerHand, { passive: true });
});
// A conversation at its end stays at its end when its box changes size: the
// keyboard coming up under a phone's text box, the text box growing a line,
// the window being made smaller. The box shrinks from the bottom, and
// without this it took the latest message with it.
//
// And when anything in it does, by itself, with nothing calling
// scrollDown(): a tool's line opening onto what it found, a picture in a
// card arriving, the words wrapping again in a column that changed width.
// Every message, card and line of the conversation is watched, as it
// arrives and for as long as it is there.
if (window.ResizeObserver) {
  var pinEnd = new ResizeObserver(keepEnd);
  pinEnd.observe(transcriptEl());
  [].forEach.call(transcriptEl().children, function (c) { pinEnd.observe(c); });
  new MutationObserver(function (changes) {
    changes.forEach(function (c) {
      [].forEach.call(c.addedNodes, function (n) { if (n.nodeType === 1) pinEnd.observe(n); });
      [].forEach.call(c.removedNodes, function (n) { if (n.nodeType === 1) pinEnd.unobserve(n); });
    });
  }).observe(transcriptEl(), { childList: true });
}

export { accountMenu, ownName, CANVAS_MIN, canvasAwayIfBare, canvasIsWanted, canvasShown, CHAT_W, chatIsWanted, chatOnScreen, chatPutAway, chatRoom,
  cols, drawerEntryTaken, drawerPopped, drawerUnwinding, drawTyped, earlyFlush, earlyLift, growInput, input, micSays, narrow, paintPaneButton, pane, queueFold, SB, screenHeight,
  panelsChoseCanvas, panelsForChat, panelsHold, panelsShown, sbSet, sendTyped, setMic, setPane, setVoice, showDictation, sidebarDone, TASKS_FULL,
  tasksHold, tasksTakeChat };
