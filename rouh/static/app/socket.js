/* Rouh's page, the socket, with reconnection (section 4 of what was one app.js).
 *
 * Imports app/settings.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import 'app/settings.js';
import 'app/offline.js';
import { shared } from 'app/shared.js';
import { $, now, safeParse } from 'app/helpers.js';
import { cfg, tabChatKeep, tabChatSaid } from 'app/settings.js';
import { debug, endUtterance } from 'app/voice.js';
import { onAudioChunk, onAudioEnd, onAudioStart, PB, stopPlayback } from 'app/playback.js';
import { applyTree, noteServerClock, ORB_SOUND, orbExpand, orbFromServer, setState } from 'app/orb.js';
import { addTurnFromElsewhere, askaiSaid, closeEmptyAssistant, endTurnOnScreen, markStopped,
  noteTurnSign, onDelta, onDone, onTaskRefs, onExchange, onPermissionAsk, onPermissionDone, onRecallMessage, onRetract, onTrace,
  onRetryStart, onStt, onSteerTaken, onToolEnd, onToolStart, onToolUpdate, onTurnEnd, onVersionPicked,
  olderFrom, openTheStream, pickUpRunningTurn, setBusy, showStop, turnIsRunning, branchFocus } from 'app/transcript.js';
import { askSaid, cardFiled, cardsEarly, composeKept, composeSaid, contactNoteSaid, inboxChanged, inboxLost,
  inboxSaid, notedConflicts, onConflictDone, pickSaid, renderCard, taskAnswerHere,
  taskAnswerSettled, taskPageRenamed } from 'app/cards.js';
import { applyTaskList, forgetTasks, upsertTask, webFrame, webState, webViewing, webWatch } from 'app/tasks.js';
import { applyObjects, applyWorkspace, browserZone, canvasLeftBehind, canvasMessage,
  cardWasFiled, clockHeard, clockLoad, clockShown, decisionsHeard, delPlanned, drawUnder, memoryHeard,
  thoughtsHeard, thoughtsShown, incubatorHeard, settingsShown, boxShown, boxesHeard,
  modelsLoad, movedTell, runsOpen } from 'app/runs.js';
import { applyChats, chatById, CHATS, forkHold, forkKeptStale, forkPark, forkRefused,
  forkBehind, forkPeeked, forkReplay, forkResume, FORKS, forkTip, forkWithin, onChatSwitched,
  onNoteSent } from 'app/chats.js';
import { detachAnswer, detachAnswered, FIND, findAnswer, findAsk, findChanged, findLabels, findReconnected,
  findMsgReveal } from 'app/search.js';
import { ADDR, addrAsk, addrFound, addrSocketGone, FRESH } from 'app/address.js';
import { earlyFlush, earlyLift, panelsForChat, setMic, setVoice, showDictation } from 'app/controls.js';
import { onPicturePartial, onPictures, picturesReady } from 'app/attachments.js';
import { gtBoardRefresh } from 'app/gene_therapy.js';
import { welcomeShow } from 'app/welcome.js';
import { notify, noteBuild, noticesHeard } from 'app/notices.js';
import { offlineHeard, offlineRepaint, offlineResults, offlineSocketDown } from 'app/offline.js';
import { compareShow } from 'app/compare.js';
import { demoAsk, demoHeard } from 'app/demo.js';

/* ------------------------------------------------------------------ 4 */

//: How long after the first handshake what can wait is let go (`rouhLater` in index.html).
var LATER_AFTER = 1500;

var S = {
  state: 'idle',
  busy: false,
  micReady: false,
  muted: false,
  //: Which conversation this page is in, as the server said in `ready`. It
  //: is never remembered here and never sent: there is one conversation and
  //: the server decides it, so a phone, a desktop and a browser opened for
  //: the first time all show the same thread. It is kept only because an
  //: attachment is uploaded to `/attachments/{session}` before the message
  //: carrying it is sent.
  sessionId: null,
  //: A handshake has come on this page since it opened: a socket that comes
  //: back has a conversation on the screen already (`cardsEarly`, `S.outbox`).
  readyOnce: false,
  //: The socket open now has had its handshake: a socket that has come back
  //: is not where a held message goes until it has (`conversationUp`).
  readyHere: false,
  ws: null,
  wantOpen: false,
  backoff: 500,
  reconnectTimer: null,
  //: The socket was closed by Rouh going down on purpose to start again (close
  //: code 1012, `RENEWING_CODE`), so the drop says so rather than sounding like a
  //: lost connection. Held through every failed try while it is down, and
  //: cleared by the handshake that finds it back.
  renewing: false,
  //: The Rouh this page last shook hands with: when it started, and the build
  //: it served (`rouh/restarts.py`). A handshake or a `/healthz` from a Rouh
  //: that started since, after going on purpose, is a deploy this page slept
  //: through (`bootChanged`).
  boot: /** @type {null | {started: number, assets: string}} */ (null),
  //: The socket went with no word why, and `/healthz` is being asked whether
  //: Rouh is starting again (`probeDrop`). Until it answers the pill says no
  //: word, rather than Reconnecting for what may be a deploy.
  dropUnsure: false,
  probing: false,
  //: The connection that came back is to a Rouh that evolved while this page
  //: was away, so the green pill says Evolved rather than Alive.
  evolved: false,
  //: The socket went while a turn was on the screen, so what the screen
  //: holds of that turn is not what happened to it: the next handshake draws
  //: the conversation again from the record (`openTheStream`).
  turnCut: false,
  countdownTimer: null,
  pingTimer: null,
  //: Another conversation has been asked for and the server has not yet
  //: switched to it, so what is on the screen is the one being left. Set by
  //: `send` for each of `SWITCHES`, cleared by `chat_switched` and by a
  //: handshake, which says afresh which conversation is open.
  switching: false,
  //: The turn on screen was stopped by the person, here or on another
  //: device. Anything of it still arriving - a word the model had already
  //: written, a finished answer - belongs to a turn that is over and is
  //: dropped. Cleared the moment the next turn starts.
  stopped: false,
  //: The highest turn number this page has heard of. A turn ending is only
  //: this screen's turn ending when it is not an older one being cleared up
  //: behind a newer one that has already started. See `onTurnEnd`.
  turn: 0,
  //: When something last arrived that belongs to the turn on screen: a word
  //: of it, a tool of its, a chunk of it being spoken, a state. The watchdog
  //: reads this clock, and only this clock (`watchTheTurn`).
  turnSign: 0,
  //: When this page last asked the server whether that turn is really still
  //: running, so it asks at most once every TURN_QUIET_MS.
  turnAsked: 0,
  //: The words of the answer are all here. From here on the only thing that
  //: can still be coming is the sound of them.
  textDone: false,
  //: Tool calls of Rouh's own that have started and not finished. Counted
  //: rather than looked for on screen, and reset by every new turn, so one
  //: lost `tool_end` cannot keep a turn looking alive for ever.
  tools: 0
};

/* The words for a drop and a return, on the pill (app/offline.js) and in the
 * words of the socket's unseen status (`setConn`). Kept here, together, to be tried
 * and changed. Petar, 12 October 2026: "something less computery and more
 * organic", and neither sleep nor death, since a drop is neither; and a word
 * like evolving is only true when Rouh is restarting on purpose, never when it
 * is somebody's bad internet. */
var CONN_WORDS = {
  //: Rouh is starting again by choice: a deploy, or Rouh updating itself.
  //: Petar, 22 October 2026 (fr_2a692d9e4fbf): Evolving, which was Renewing.
  renewing: 'Evolving',
  //: The connection went and nobody meant it to: the network, a crash, a phone asleep.
  reconnecting: 'Reconnecting',
  //: Back after Evolving, said in green for a moment in place of Alive, so a
  //: deploy reads as one from the drop to the return (fr_4ba66bbb733a).
  evolved: 'Evolved',
  //: It is back, said in green for a moment, after the pill's cloud. Alive, with
  //: its 'a' on purpose for a living thing, which was Live (fr_2a692d9e4fbf).
  live: 'Alive'
};

/* WebSocket's own close code for "Service Restart". Uvicorn closes every open
   socket with it when the process is told to stop (systemd's restart on a
   deploy, `update-all.sh`), before anything else goes down; a crash, a dead
   network or a sleeping phone closes with 1006 and never with this. */
var RENEWING_CODE = 1012;

/* Whether what a Rouh says of itself, on its handshake or its `/healthz`, is a
   Rouh that evolved since this page last shook hands: one that started since
   and either served a new build or was preceded by a stop on purpose
   (`rouh/restarts.py`). A crash, which leaves no mark, and the same build is
   not; nor is the first handshake of a page, which has nothing to compare.
   @param {any} said */
function bootChanged(said) {
  var was = S.boot;
  if (!was || !said || !said.started || said.started === was.started) return false;
  return !!said.planned || !!(said.assets && was.assets && said.assets !== was.assets);
}

/* The socket went with no close code to say why: a phone asleep through a
   deploy never sees uvicorn's 1012, and neither does a socket that dies
   while Rouh is already down. Petar, 27 October 2026 (fr_4ba66bbb733a):
   "make sure all upgrades and changes we do go through evolving, not
   reconnecting". So `/healthz`, which answers with no sign-in, is asked:
   the proxy in front answering 5xx is Rouh down while the way to it works,
   which is Rouh starting again; a Rouh that answers and has evolved since
   (`bootChanged`) is the same. Anything else - no answer at all, the same
   Rouh as before - is the connection, and is Reconnecting. */
function probeDrop() {
  if (S.probing || S.renewing) return;
  S.probing = true;
  var ctl = typeof AbortController === 'function' ? new AbortController() : null;
  var late = setTimeout(function () { if (ctl) ctl.abort(); }, 3000);
  var settle = function () {
    clearTimeout(late);
    S.probing = false;
    S.dropUnsure = false;
    offlineRepaint();
  };
  fetch('/healthz', { cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined })
    .then(function (res) {
      if (res.status >= 500) { S.renewing = true; return null; }
      return res.ok ? res.json() : null;
    })
    .then(function (said) { if (said && bootChanged(said)) S.renewing = true; })
    .catch(function () { /* no answer at all: the connection */ })
    .then(settle);
}

function wsUrl() {
  var q = new URLSearchParams(location.search).get('ws');
  if (q) return q;
  return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
}

// How the socket is, in words, on a status nobody sees: a screen reader is
// told when it changes, and the harness and Gene therapy's reports read it.
// It was a green, amber or red plug at the foot of the sidebar, one of the
// four icons there, until 13 October 2026, when Petar had all four taken
// off the screen (fr_f247c02864da): "They're for debugging, and Rouh has been
// handling them very well". The other three went altogether.
function setConn(kind, text) {
  var c = $('conn');
  c.setAttribute('data-state', kind);
  c.setAttribute('aria-label', text);
  c.textContent = text;
}

//: What asks the server to put another conversation on the screen. It
//: answers with `chat_switched`, and until it has, an empty transcript is
//: the chat being left and says nothing about the one on its way
//: (`welcomeHeld`).
var SWITCHES = { open_chat: true, new_chat: true, open_thread: true };

//: What moves this tab to a chat, or changes the strip of forks around it.
//: Each is numbered as it is sent (`ask`), and the server stamps everything
//: it says about the tab's chat and strip with the newest number it had
//: handled when it worked that out (`asked`), so a list built before a move
//: and sent after it cannot put the screen back (`forkBehind` in
//: app/chats.js). The handshake is one: a page that connects again says
//: where it is, and everything before that is behind it.
var MOVES = { hello: true, open_chat: true, new_chat: true, open_thread: true, close_fork: true,
              fork: true, fork_chat: true, answer_chat: true, detach_fork: true, delete_chat: true,
              delete_folder: true, delete_object: true };

/** @param {import('./protocol').ClientMessage} obj */
function send(obj) {
  if (S.ws && S.ws.readyState === 1) {
    if (MOVES[obj.type]) obj.ask = ++FORKS.asked;
    S.ws.send(JSON.stringify(obj));
    // Rouh in the navigation pressed in General itself moves nowhere: only
    // the forks beside it go, and the answer is `chats`, not a switch.
    if (SWITCHES[obj.type] && !(obj.type === 'open_thread' && obj.alone && obj.id === CHATS.active)) {
      S.switching = true;
    }
    return true;
  }
  return false;
}

function sendBinary(buf) {
  if (S.ws && S.ws.readyState === 1) {
    S.ws.send(buf);
    debug.sentFrames++;
    return true;
  }
  return false;
}

/* The chat this tab asks to be put back into when its socket opens: the one
   on its screen, after a dropped socket; the one its address names, when it
   is opened at one; or the one it was in before it was reloaded. None at
   the front door, which is in no chat (see 10g). */
function tabChatWanted() {
  if (ADDR.front) return '';
  if (CHATS && CHATS.active) return CHATS.active;
  var want = ADDR.wanted;
  if (want && want.chat) return want.chat;
  if (want && want.kind === 'chat' && want.id) return want.id;
  return tabChatSaid();
}

/* And where the strip of forks around that chat ends (`forks.strip`): the
   one on its screen, or the one its address names. The strip is the tab's
   own, so a tab that connects again lays out exactly the strip it had, and
   nothing any other tab did since changes it. */
function tabStripWanted() {
  if (ADDR.front) return '';
  if (CHATS && CHATS.active) return forkTip();
  var want = ADDR.wanted;
  return (want && want.strip) || '';
}

function connect() {
  S.wantOpen = true;
  clearTimeout(S.reconnectTimer);
  clearInterval(S.countdownTimer);
  setConn('connecting', 'Connecting');
  var ws;
  try {
    ws = new WebSocket(wsUrl());
  } catch (e) {
    scheduleReconnect();
    return;
  }
  ws.binaryType = 'arraybuffer';
  S.ws = ws;

  ws.onopen = function () {
    // The time zone this device is on is the person's clock for every time
    // Rouh says or works out (`rouh/clock.py`).
    var chat = tabChatWanted();
    send({ type: 'hello', client: 'rouh-web/1.0', tz: browserZone(), chat: chat,
           strip: tabStripWanted() });
    // The canvas's first cards, asked for now rather than once the handshake
    // is back, for the conversation that is opening (`cardsEarly`). Only for a
    // page that has not drawn one yet: a socket that came back keeps its own.
    if (!S.readyOnce && !ADDR.front) cardsEarly(chat);
    clearInterval(S.pingTimer);
    S.pingTimer = setInterval(function () { send({ type: 'ping' }); }, 25000);
  };

  /* A message that cannot be handled must not take the page down with it.
   *
   * `handleMessage` draws most of the screen, and `ready` in particular is
   * the whole handshake: the chats, the transcript, the cards, the task
   * list, the tree and the word Connected are all one pass through it. A
   * throw anywhere in that pass used to leave every line after it unrun,
   * with nothing anywhere saying so - the page simply sat there half drawn,
   * on an open socket, saying Connecting for ever. That is what one
   * duplicated variable name did on 22 September 2026, and the cost of
   * finding it was the whole of a morning.
   *
   * So the throw is caught, named on the console with the message that
   * caused it, and said where the socket's own state is said (`setConn`),
   * which Gene therapy's reports carry (`connText`); it was an amber icon at
   * the foot of the sidebar until 13 October 2026. The page is still wrong
   * when this happens - something did not get drawn - but it says so, and
   * everything that had already been drawn goes on working.
   */
  ws.onmessage = function (ev) {
    if (HELD.on) heldHear(ev.data);
    else takeFrame(ev.data);
  };

  ws.onerror = function () { /* a close always follows */ };

  ws.onclose = function (ev) {
    // A socket that had its handshake, rather than a try that never got one.
    var wasUp = S.readyHere;
    S.readyHere = false;
    // What arrived before it went is handled before it is said to be gone.
    releaseMessages();
    clearInterval(S.pingTimer);
    if (S.ws === ws) S.ws = null;
    // Whatever this socket was still to answer about an address is not coming.
    addrSocketGone();
    // Rouh going down on purpose says so once, as it goes; the tries that fail
    // while it is down say nothing about why, so they leave this as it is.
    if (ev && ev.code === RENEWING_CODE) S.renewing = true;
    // A drop with no word why is asked about (`probeDrop`); the pill holds its
    // word until it is answered, only for the drop itself and not for every
    // try that fails after it, which ask again without taking the pill away.
    S.evolved = false;
    if (!S.renewing && (!ev || ev.code !== 4401)) {
      if (wasUp) S.dropUnsure = true;
      probeDrop();
    }
    // With no connection the page goes on from this device's copy (app/offline.js).
    if (!ev || ev.code !== 4401) offlineSocketDown();
    // A conversation asked for at the front door and never answered died
    // with this socket, and so did whatever was waiting on it. What was
    // typed is still in the box: pressing send again asks again (see 10g).
    FRESH.asked = false;
    FRESH.waiting = [];
    inboxLost();
    endUtterance('socket', true);
    // No socket means no reply is coming, so nothing is waiting on one - and
    // that is the whole turn, not only the send button. A page that lost its
    // socket while Rouh was answering was left with the Stop control on
    // screen and Rouh's own line lit on the orb, and nothing that could
    // ever arrive afterwards was about that turn: it died with the socket.
    // A page with no turn running is left alone, microphone and all.
    if (turnIsRunning()) { S.turnCut = true; endTurnOnScreen(); } else setBusy(false);
    // 4401 is the server saying there is no sign-in behind this cookie any
    // more: the session ran out, or it was signed out from somewhere else.
    // Reconnecting would only be refused again every few seconds forever, so
    // the page goes where the person has to go anyway. The socket is the one
    // thing that is always reconnecting, so this is also what catches a
    // session that ends while the page is just sitting open.
    if (ev && ev.code === 4401) {
      S.wantOpen = false;
      setConn('offline', 'Signed out');
      location.href = '/login?next=' + encodeURIComponent(location.pathname);
      return;
    }
    if (S.wantOpen) scheduleReconnect();
    else setConn('offline', 'Offline');
  };
}

/** @param {any} data one frame off the socket: a message, or a piece of sound */
function takeFrame(data) {
  if (typeof data === 'string') {
    var msg = safeParse(data);
    if (!msg || !msg.type) return;
    // The real handshake, and not the copy of one an offline page is drawn from.
    if (msg.type === 'ready') {
      // Rouh coming back from Evolving, or found to have evolved while this
      // page was away, comes back saying Evolved (app/offline.js).
      S.evolved = S.renewing || bootChanged(msg);
      S.renewing = false;
      S.dropUnsure = false;
      S.boot = { started: msg.started || 0, assets: msg.assets || '' };
    }
    try {
      handleMessage(msg);
      // What the page was drawn from, kept for drawing it with no connection (app/offline.js).
      offlineHeard(msg);
    } catch (err) {
      console.error('rouh: the "' + msg.type + '" message could not be handled:', err);
      setConn('waiting', 'Connected, but the "' + msg.type
        + '" message could not be handled: ' + (err && err.message ? err.message : err));
    }
  } else {
    onAudioChunk(data);
  }
}

/* What the server sends, held back while the strip of forks moves, and
   then handled in the order it came. Petar, 21 October 2026
   (fr_74e2f2bd025d): closing a fork "should immediately close and slide
   over to the previous (parent) chat", and opening one "should immediately
   expand to the right". So the strip moves the moment it is pressed
   (`stripMove` in app/chats.js), to where the server's answer will put it,
   and the answer - with everything that comes before and after it - waits
   until the movement is over, so that it cannot land in the middle of it.

   `until` is the kinds of message that are the answer: once one has come and
   the movement is over (`heldMoved`), everything held is handled. `stop` is
   the kinds that say there will be none, such as a fork refused. Either
   way the hold ends after `most` milliseconds, and when it ends with no
   answer `undo` puts the strip back as the page last heard it. */
var HELD = {
  on: false, q: /** @type {any[]} */ ([]), timer: 0, moving: false, heard: false,
  until: /** @type {string[]} */ ([]), stop: /** @type {string[]} */ ([]),
  answered: false, undo: /** @type {null | (() => void)} */ (null)
};

/** @param {{most: number, until: string[], stop?: string[], undo?: () => void}} how */
function holdMessages(how) {
  // A hold already on, for a press a moment ago, is handed over as it is.
  if (HELD.on) releaseMessages();
  HELD.on = true;
  HELD.q = [];
  HELD.moving = true;
  HELD.heard = false;
  HELD.answered = false;
  HELD.until = how.until || [];
  HELD.stop = how.stop || [];
  HELD.undo = how.undo || null;
  clearTimeout(HELD.timer);
  HELD.timer = window.setTimeout(releaseMessages, how.most);
}

/** @param {any} data */
function heldHear(data) {
  HELD.q.push(data);
  if (typeof data !== 'string') return;
  var type = (safeParse(data) || {}).type;
  if (HELD.until.indexOf(type) >= 0) { HELD.heard = true; HELD.answered = true; }
  else if (HELD.stop.indexOf(type) >= 0) HELD.heard = true;
  if (HELD.heard && !HELD.moving) releaseMessages();
}

// The strip has got to where it was going.
function heldMoved() {
  HELD.moving = false;
  if (HELD.on && HELD.heard) releaseMessages();
}

function releaseMessages() {
  if (!HELD.on) return;
  clearTimeout(HELD.timer);
  HELD.on = false;
  var q = HELD.q, undo = HELD.answered ? null : HELD.undo;
  HELD.q = [];
  HELD.undo = null;
  for (var i = 0; i < q.length; i++) takeFrame(q[i]);
  if (undo) undo();
}

function scheduleReconnect() {
  var wait = S.backoff;
  S.backoff = Math.min(S.backoff * 2, 15000);
  var due = now() + wait;
  var tick = function () {
    var left = Math.max(0, Math.ceil((due - now()) / 1000));
    var word = S.renewing ? CONN_WORDS.renewing : CONN_WORDS.reconnecting;
    setConn('waiting', left > 0 ? word + ', trying again in ' + left + 's' : word);
  };
  tick();
  clearInterval(S.countdownTimer);
  S.countdownTimer = setInterval(tick, 500);
  clearTimeout(S.reconnectTimer);
  S.reconnectTimer = setTimeout(function () {
    clearInterval(S.countdownTimer);
    connect();
  }, wait);
}

/** @param {import('./protocol').ServerMessage} m */
function handleMessage(m) {
  // Anything that belongs to one thread says which (`Turn.emit` on the
  // server). A turn goes on being answered in the thread it was asked in
  // after the person has opened another one, so its words can still be on
  // the wire when they land somewhere else, and those words are not this
  // screen's to draw. `chat_switched` is the exception and carries the chat
  // as a row rather than as an id, which is why the type is checked.
  //
  // A page at the front door is in no conversation at all, so nothing that
  // belongs to one is its to draw: a turn still being answered in the chat
  // the person was in last goes on arriving here and is dropped (see 10g).
  //
  // Except a chat of the strip of forks this page is keeping as it was while
  // another of the strip is on screen: that is held for it, and drawn the
  // moment it is slid back into view (`forkHold`).
  if (typeof m.chat === 'string' && m.chat && CHATS
      && m.chat !== CHATS.active) {
    forkHold(m);
    return;
  }
  switch (m.type) {
    case 'ready':
      S.backoff = 500;
      // Demo mode may have been turned on or off while the socket was away (`rouh/demo.py`).
      demoAsk();
      // What arrived for the chats kept beside this one while the socket was
      // away is lost with it (`forkHold`).
      forkKeptStale();
      // Whatever was asked of the socket before this one is not coming:
      // this says which conversation is open.
      S.switching = false;
      // The conversation on the screen, before this says which one is open.
      // Nearly always the same one, which is left as it is; when it is not -
      // a fork closed with no socket to say so on, a chat deleted elsewhere -
      // the one on the screen is not this tab's any more and is drawn again.
      var onScreen = !ADDR.front && CHATS ? CHATS.active : null;
      // A search asked while the socket was down, or lost with it.
      findReconnected();
      // Which build of the page this server is serving. A deploy restarts
      // Rouh, so this is the first thing said on the connection that comes
      // back, which is exactly the moment the tab became the old page; the
      // run that deployed it then carries the Reload on its own notice.
      noteBuild(m.assets);
      // Where an utterance begins and ends is this browser's to decide: it
      // watches the level, opens an utterance, closes it after a quiet
      // moment, and sends only what it judged to be speech. Whether that
      // utterance was a whole question is the model's, on the server
      // (rouh/turnmarks.py).
      //
      // A new connection starts with dictation off on the server.
      if (S.dictating) showDictation(false);
      // Which conversation this tab's uploads belong to. None at the
      // front door, where there is no conversation to put a file in until
      // something has been said in one (see 10g).
      S.sessionId = ADDR.front ? null : (m.session_id || null);
      tabChatKeep(S.sessionId);
      // The chat this tab is in, as its own row, for its head until the whole
      // list comes in the `chats` that follows (`conversation_snapshot`).
      if (m.chat) CHATS.own = m.chat;
      // The chats, and which of them this transcript belongs to. Before the
      // transcript is drawn, so the name beside "Transcript" is right the
      // first time rather than a moment later. Since 23 October 2026 the
      // handshake carries only the conversation, and the lists - every chat,
      // the tasks and projects, the runs, the workspace - follow it as their
      // own messages; a copy of an older handshake still carries them, and
      // they are drawn from it as they were.
      applyChats(m);
      // Its panels, as it was left or as it starts (`panelsForChat`). At the
      // front door there is no chat, and the conversation is alone.
      panelsForChat(ADDR.front ? null : (CHATS.own && CHATS.own.id === CHATS.active ? CHATS.own
        : chatById(CHATS.active) || { id: CHATS.active }));
      // The tasks and the projects, and the workspaces and policies a new
      // run may be started with. Before the run list is applied, so a run's
      // card can say who owns it the first time it is drawn.
      if (m.objects) applyObjects(m.objects);
      // What was said in the chat that is active, and what was drawn in
      // it - unless this page is at the front door, which is in no chat:
      // nothing of last night's conversation is on this screen (see 10g).
      // Only a handshake on an open socket says what the record holds now: the
      // copy drawn while there is no connection (`offlineReplay`) is the one
      // kept when the page opened, and it waits for the real one.
      var heard = !!S.ws && S.ws.readyState === WebSocket.OPEN;
      var moved = !!onScreen && onScreen !== CHATS.active;
      // What was sent before this is held off the screen while the
      // conversation is drawn, and goes into it below (`earlyFlush`).
      earlyLift();
      if (!ADDR.front) {
        var redrawn = !S.readyOnce || (S.turnCut && heard) || moved;
        openTheStream(m.transcript, (S.turnCut && heard) || moved);
        // Where what came before begins, for reading it back as the reader scrolls
        // up - when what is on the screen is what this handshake drew. A socket
        // that came back under a conversation left as it was goes on from where
        // that had got to.
        if (redrawn) olderFrom(S.sessionId || '', m.older || '');
      }
      if (heard) S.turnCut = false;
      // What the picture controls may offer here, if anything.
      picturesReady(m.pictures);
      $('sessId').textContent = S.sessionId || '-';
      $('sessId').title = S.sessionId || '';
      setConn('live', 'Connected');
      // What this tab should be showing, from the one thing that knows. A
      // page that reconnects in the middle of an answer is still in the
      // middle of it: the turn belongs to the thread and did not go with the
      // socket, so `m.running` is it, with the words written so far, and the
      // rest of them arrive the ordinary way. Nothing running settles the
      // screen instead, rather than leaving a Stop control nothing will ever
      // take away.
      pickUpRunningTurn(ADDR.front ? null : m.running);
      // The whole list comes with the handshake, so a tab that has just
      // opened shows every job rather than waiting for one to change. And a
      // tab that has just reconnected takes it as the whole truth: a card
      // the server has no row for is one left over from before the restart.
      if (Array.isArray(m.tasks)) applyTaskList(m.tasks, true);
      if (Array.isArray(m.workspace)) applyWorkspace(m.workspace);
      // Which conflicts are still waiting on a decision. A card is drawn
      // from the canvas, which is history, and history does not know a
      // question was answered an hour ago on the phone.
      notedConflicts(m.conflicts);
      // The orb as this person set it, which is theirs rather than this
      // browser's: a slider moved on the desktop is moved on the phone, and
      // is still moved after this browser has dropped its site data, which
      // is what it never was while local storage was the only place it went.
      orbFromServer(m.orb);
      // The machine's own setting, for a browser nobody has chosen on. It
      // arrives here rather than being asked for, so there is no moment when
      // the page is showing one thing and the server believes another.
      if (!cfg.voiceChosen && typeof m.voice_reply === 'boolean'
          && m.voice_reply !== cfg.voiceReply) {
        setVoice(m.voice_reply);
      }
      send({ type: 'set_mode', voice_reply: !!cfg.voiceReply });
      // A fresh socket cannot be carrying the tail of a reply that was
      // interrupted on the old one, so whatever the drop deadline says, it
      // is spent. This is the reconnect that used to leave a page silent:
      // barge in, lose the socket, and every chunk after it was thrown away
      // because the `audio_start` that would have cleared the latch belonged
      // to the connection that died.
      PB.dropTailUntil = 0;
      // The server sends the work tree with `ready` when it has one. Asking
      // costs one small message and covers the server that does not.
      // What it answers with is what was already there while the socket was
      // away, not work that has just appeared, so the open orb stays quiet
      // for it (`orbSoundArrived`).
      ORB_SOUND.whole = true;
      send({ type: 'get_tree' });
      // Whether the Live browser is open, and a view of it that was open
      // before the socket dropped asks for its pictures again: the server
      // forgot who was watching when the socket went.
      webState(m.browser);
      if (webViewing()) webWatch();
      // What the Reminders and Goals rows say, and the pages if they are
      // open: anything may have been said or logged while the socket was away.
      // On the first handshake, once the conversation has had its moment.
      if (S.readyOnce) clockLoad(); else window.rouhLater(clockLoad);
      // And the address this page was opened at, which names one object
      // and could not be asked about before there was a socket to ask on -
      // once every script of the page has run. The handshake can now come
      // before the pages the address may open have loaded (Approvals,
      // Decisions, the brief, each a script after this one), and opening one
      // before its script is there opened nothing at all.
      // Whether an empty conversation says hello is decided again once the
      // address has been asked: held while it was on its way, it would
      // otherwise stay down or go up by which of it and the list of chats
      // came first (`welcomeShow`).
      if (window.rouhScriptsRan) { addrAsk(); welcomeShow(); }
      else document.addEventListener('DOMContentLoaded', function () { addrAsk(); welcomeShow(); earlyFlush(); }, { once: true });
      S.readyHere = true;
      if (!S.readyOnce) {
        S.readyOnce = true;
        // The lists follow the handshake and the canvas is asked for; what
        // can wait (index.html) goes after them.
        setTimeout(window.rouhLaterGo, LATER_AFTER);
      }
      // Whatever was sent before the conversation was there goes into it now,
      // if the address has been answered; otherwise once it is (`chat_switched`).
      earlyFlush();
      debug.ready++;
      break;
    case 'browser':
      // The Live browser: open or closed, who has it, where it is, and what
      // Rouh is doing in it (`rouh/browsing.py`).
      webState(m);
      break;
    case 'browser_frame':
      // One picture of its screen, sent only while this tab is watching.
      webFrame(m);
      break;
    case 'demo':
      // Demo mode turned on or off, on this device or another, or what is approved changed
      // (`rouh/demo.py`, app/demo.js).
      demoHeard(m);
      break;
    case 'notices':
      // What Rouh has to tell the person: dropped in at the top, and under the bell
      // (`rouh/notices.py`, app/notices.js).
      noticesHeard(m);
      break;
    case 'decisions':
      // How many questions wait on the person, from every part of Rouh that asks
      // (`rouh/decision_desk.py`): the count on the Decisions row, and the page read again.
      decisionsHeard(m);
      break;
    case 'thoughts':
      // How many thoughts the person keeps, and that the list moved (`rouh/thoughts.py`).
      thoughtsHeard(m);
      break;
    case 'incubator_changed':
      // An idea in the Incubator was added or changed in a chat, or Rouh was asked to show the list.
      incubatorHeard(m);
      break;
    case 'thoughts_shown':
      // Rouh kept one in this conversation, or was asked to show them.
      thoughtsShown(m);
      break;
    case 'box_open':
      // He asked for a box: the Box page opens with an empty one ready (`rouh/boxes.py`).
      boxShown(m);
      break;
    case 'boxes':
      // A box was saved, changed, deleted or given to Rouh (`rouh/boxes.py`).
      boxesHeard(m);
      break;
    case 'clock':
      // A reminder or a goal changed, here or on another screen of the
      // person's, or one was said (`rouh/timekeeper.py`).
      clockHeard(m);
      break;
    case 'settings_shown':
      // Rouh was asked to show one group of Settings, such as Cloudflare.
      settingsShown(m);
      break;
    case 'clock_shown':
      // Rouh added or changed one in this conversation: the page opens.
      clockShown(m);
      break;
    case 'browser_forgot':
      notify(m.had ? 'The browser\u2019s saved logins are forgotten.'
                   : 'The browser had no saved logins to forget.', { tone: m.had ? 'success' : 'info' });
      break;
    case 'objects':
      // Every task and every project, and what a new run may be started
      // with. Broadcast whenever any of it changes, because who owns what is
      // one answer for the person rather than one per tab.
      applyObjects(m);
      break;
    case 'attached':
      // An attach or a detach was carried out, or refused in the store's own
      // words. The lists that carry an owner - the tasks, the chats, the
      // runs - are sent again by the server, so there is nothing to patch
      // here: the dialog closes and the move says where the thing is now
      // (`movedTell`), or it says why it would not. A fork detached into a
      // task is answered the same way, in the box it was picked in.
      if (detachAnswered(m)) break;
      if (m.ok) { $('ownerDialog').close(); movedTell(m); }
      else if ($('ownerDialog').open) {
        $('ownerError').textContent = m.why || 'That is not allowed.';
        $('ownerError').hidden = false;
      } else {
        // The row menu's Change project asks for this too, and its menu is
        // gone by the time the answer lands. A refusal with nowhere to be
        // read is a press that did nothing and said nothing.
        notify(m.why || 'That is not allowed.', { tone: 'warning' });
      }
      break;
    case 'under':
      // What one thing owns, walked down. Asked for when its panel opened.
      drawUnder(m);
      break;
    case 'delete_plan':
      // What deleting the thing in the dialog would take with it, counted by
      // the server. Nothing has been written; this is the sentence the
      // person is being asked to agree to.
      delPlanned(m);
      break;
    case 'deleted':
      // It is gone, and so is everything that belonged to it. Every list
      // that held it is sent again by the server, so there is nothing to
      // patch here beyond the canvas, which holds one page rather than a
      // list and would otherwise go on drawing the task that was deleted.
      notify(m.did || 'It is gone.', { tone: 'success' });
      canvasLeftBehind(m.folders);
      // And the search box, where the row that has just gone is still drawn.
      if (FIND.open) findAsk(true);
      break;
    case 'run_started':
      // A run started from the Start box. The run itself arrives on the task
      // list and on the orb like any other; this is only the yes or no.
      if (m.ok) {
        $('oneStartDialog').close();
        $('oneStartBrief').value = '';
        // On the tab it went on, so the run just started is the one in front.
        runsOpen(m.kind);
      } else {
        $('oneStartError').textContent = m.why || 'It could not be started.';
        $('oneStartError').hidden = false;
      }
      $('oneStartGo').disabled = false;
      $('oneStartGo').textContent = 'Start';
      break;
    case 'chats':
      // Every chat and every project, sent whenever any of them changes -
      // including when a title the model wrote lands, which is the one that
      // arrives without anybody on this page having done anything.
      //
      // One worked out before this page's newest move says which chat this
      // tab is in, and its strip, as they were before it: the lists are
      // taken and that is not (`forkBehind`).
      if (forkBehind(m)) applyChats(Object.assign({}, m, { active_chat: undefined, forks: undefined, draft: undefined }));
      else applyChats(m);
      break;
    case 'search_results':
      // What the search box asked for. It carries the page's own counter
      // back, so an answer to the word before this one is thrown away. The
      // box a fork is detached from asks the same question (`detachAsk`),
      // and says so, so each box hears only its own answers.
      if (m.box === 'detach') detachAnswer(m);
      else findAnswer(m);
      break;
    case 'task_refs':
      // What the task numbers in an answer are, to draw each as its name.
      onTaskRefs(m);
      break;
    case 'search_labels':
      // The task numbers for the list the box shows before anything is typed.
      findLabels(m);
      break;
    case 'object_found':
      // What one address names, turned back into the same instruction a
      // result row carries. A link, a second tab and Back all land here.
      addrFound(m);
      break;
    case 'object_changed':
      // A pin or a rename from a row's menu: yes, or the sentence saying why
      // not. Deleting comes back as `deleted`, like every other delete. A
      // rename from a task's own page is answered on that page.
      if (!taskPageRenamed(m)) findChanged(m);
      break;
    case 'note_sent':
      onNoteSent(m);
      break;
    case 'chat_switched':
      // The server's answer to a move along the strip this page has already
      // made (`stripGo`): the chat is on the screen. One followed by another
      // move of the page's own is behind it and is passed over whole; the last
      // is taken as the chat already on screen, which draws nothing.
      if (!m.local && forkBehind(m)) break;
      // This tab asked for another chat, and is now in it. Only this tab:
      // another tab, or the phone in the person's hand, stays in its own.
      //
      // And there is a conversation on this page now, so the front door is
      // behind it. Before `applyChats`, which is what takes the active chat
      // and will not take it at the front door (see 10g).
      ADDR.front = false;
      S.switching = false;
      // Whether this is a move along a strip of forks, read before the strip
      // this message carries replaces the one on screen (`forkWithin`).
      FORKS.within = forkWithin(m);
      // The chat being left, kept itself, as it is, for its card beside the
      // next one and for when it is slid back
      // (`forkPark`); and the chat arriving put back the same way, when it
      // was kept. Only along a strip: nowhere else is either drawn again.
      // Before the strip is taken below, which draws the marks of the chat
      // arriving into the conversation on screen.
      FORKS.resumed = null;
      // The chat already on the screen, sent again with its strip changed:
      // its conversation stays as it is (`onChatSwitched`).
      FORKS.same = !!(m.chat && m.chat.id && m.chat.id === CHATS.active && !ADDR.front);
      // Unless the server asks for it to be drawn again: a branch of its
      // conversation is the one being read now (`branch_redraw`).
      if (m.redraw) FORKS.same = false;
      if (FORKS.within) {
        forkPark(CHATS.active);
        FORKS.resumed = forkResume(m);
      }
      if (m.chat && m.chat.fork_of) FORKS.rows[m.chat.id] = m.chat;
      applyChats({ active_chat: m.chat && m.chat.id, forks: m.forks });
      earlyLift();
      onChatSwitched(m);
      // And what arrived for it while it was kept, in the order it came, as
      // though it were arriving now.
      forkReplay(m);
      // And the message a search result was opened at (`findMsgReveal`).
      findMsgReveal(m.chat && m.chat.id);
      // A branch drawn again goes back to where it was taken.
      if (m.redraw && m.focus) branchFocus(m.focus);
      // And what was sent before this conversation was on the screen.
      earlyFlush();
      break;
    case 'chat_peek':
      // A chat beside this one, whole, for its card (`forkPeeked`).
      forkPeeked(m);
      break;
    case 'answer_chat':
      // An answer from a task's page, and the chat it goes into is the one
      // open already, so nothing was switched (`taskAnswerHere`).
      taskAnswerHere(m.chat || '');
      break;
    case 'fork_refused':
      // Fork was pressed in a chat with nothing in it to fork. What was
      // typed goes back in the box, and the sentence says why.
      forkRefused(m);
      break;
    case 'mode':
      // Confirmation of a settings change. It must never cause another
      // set_mode to be sent, or the two sides ping-pong for ever.
      break;
    case 'model_defaults':
      // The models in Settings changed, here or anywhere: read them again,
      // which also names the right model beside the This page side's box.
      modelsLoad();
      break;
    case 'exchange':
      // Which exchange the turn now running is writing into, and how many
      // tries it has behind it. It is what puts retry, copy and edit under a
      // message drawn live rather than only under one read back.
      onExchange(m);
      break;
    case 'retry':
      // That exchange is being answered again, here or on another device.
      onRetryStart(m);
      break;
    case 'version_picked':
      // Somebody stepped an exchange to another of its tries.
      onVersionPicked(m);
      break;
    case 'askai_said':
      // An exchange the person had in Ask AI, now part of this
      // conversation too (`runtime.askai_said`).
      askaiSaid(m.rows);
      break;
    case 'transcript_add':
      // A turn made on another device. There is one conversation across all
      // of them, so it belongs on this screen now and not only after a
      // reload.
      addTurnFromElsewhere(m);
      break;
    case 'state':
      noteTurnSign(m.turn_id);
      // A turn starting is the one thing that clears the stop: from here on
      // what arrives belongs to the next question and is drawn.
      if (m.value === 'thinking') S.stopped = false;
      if (S.stopped && m.value === 'speaking') break;
      // Idle is the end of a turn however it got there, including the turns
      // that went wrong, so it is the backstop that frees the send button.
      if (m.value === 'idle') {
        taskAnswerSettled();
        // Not while the last of it is still coming out of the speaker. The
        // server calls a turn over as soon as it has sent the last byte and
        // a second of it is still in this browser, so the words half of it
        // is done now and the word in the title bar follows the sound
        // (`src.onended`). Read off the buffers really scheduled rather than
        // off `stillSpeaking`: those are certain to drain and to come back
        // here, and an `audio_end` that never arrives is not.
        if (PB.sources.length) { setBusy(false); closeEmptyAssistant(); showStop(); break; }
        endTurnOnScreen();
        break;
      }
      setState(m.value);
      if (m.value === 'thinking') setBusy(true);
      break;
    case 'turn_end':
      // A turn the server has declared over without declaring anything
      // about the state, because by then it was not the turn on the front of
      // the screen: it was cancelled, or replaced by the next question.
      onTurnEnd(m.turn_id);
      break;
    case 'stt':
      noteTurnSign(m.turn_id);
      if (m.final === true && !m.text) {
        debug.wasted = (debug.wasted || 0) + 1;
        var w = $('roWasted'); if (w) w.textContent = String(debug.wasted);
      }
      onStt(m.text || '', !!m.final, m.turn_id);
      break;
    case 'assistant_delta':
      noteTurnSign(m.turn_id);
      // A word of a stopped turn is a word of a turn that is over. The model
      // had already written it when the flag landed; it is not said and it
      // is not drawn.
      if (S.stopped) break;
      onDelta(m.text || '', m.turn_id);
      break;
    case 'assistant_done':
      noteTurnSign(m.turn_id);
      if (S.stopped) break;
      onDone(m.text, m.usage, m.turn_id, m.spent);
      setBusy(false);
      // Every word of the answer is here, so the only thing that can still
      // be coming is the sound of it. If none starts, the watchdog above
      // ends the turn rather than waiting on a message that may never come.
      S.textDone = true;
      break;
    case 'model_compare':
      // A blind comparison under an answer, with the opt-in on (app/compare.js).
      compareShow(m);
      break;
    case 'stopped':
      // The turn was stopped. Either this page pressed it a moment ago, in
      // which case everything below has already happened and does nothing
      // twice, or it was stopped on another device and this screen is
      // hearing about it for the first time. A tab with nothing running is
      // in the same conversation but was not the one talking, and draws
      // nothing: a line saying "you stopped this" under an answer that
      // finished an hour ago would be a lie.
      if (!turnIsRunning() && !S.stopped) break;
      S.stopped = true;
      stopPlayback();
      markStopped();
      setBusy(false);
      setState('idle');
      break;
    case 'steer_taken':
      // Messages sent while the answer was being written, read by the model
      // now: the mark comes off and they move to where they were read.
      noteTurnSign(m.turn_id);
      onSteerTaken(m);
      break;
    case 'assistant_retract':
      // The person carried on talking before the answer was finished, so it
      // answered a question they had not finished asking: it goes.
      onRetract(m.turn_id);
      break;
    case 'dictation':
      // The server confirming the switch; the button already shows it.
      break;
    case 'recall':
      // What Master's look-ups are doing for the person's message, drawn in
      // the line of its answer (app/turnline.js).
      onRecallMessage(m);
      break;
    case 'trace':
      // Every step of the turn now running: the label in place of the dots, the
      // model decision as soon as it is made, and the line in the reply
      // (app/turnline.js, `rouh/turntrace.py`).
      onTrace(m);
      break;
    case 'tool_start':
      noteTurnSign(m.turn_id);
      // Automatic recall's look-ups are twigs on the orb, which the server
      // draws from the same message, and never a line in the chat.
      if (!m.orb_only) onToolStart(m);
      break;
    case 'pictures':
      // A set of pictures: its frames while it is drawn, then the pictures
      // or why there are none (`imaging.draw`).
      onPictures(m);
      break;
    case 'picture_partial':
      onPicturePartial(m);
      break;
    case 'tool_update':
      noteTurnSign(m.turn_id);
      onToolUpdate(m);
      break;
    case 'tool_end':
      noteTurnSign(m.turn_id);
      if (m.orb_only) break;
      onToolEnd(m);
      memoryHeard(m);
      break;
    case 'permission_ask':
      onPermissionAsk(m);
      break;
    case 'permission_done':
      onPermissionDone(m);
      break;
    case 'conflict_done':
      onConflictDone(m);
      break;
    case 'conflict_gone':
      onConflictDone({ id: m.id, why: m.why || 'Already answered.' });
      break;
    case 'card_compose_said':
      // A save or a Send on a card the person writes in that could not be
      // done: Gmail out of reach, or it had already gone. A card that did
      // send is drawn again instead, as `ui`, saying Sent.
      composeSaid(m.card, m.why, m.again);
      break;
    case 'card_compose_saved':
      composeKept(m.card);
      break;
    case 'card_inbox_said':
      // The answer to one ask of an inbox card: the list, a message, a
      // form filled in, or what was done and why not (rouh/inbox.py).
      inboxSaid(m);
      break;
    case 'card_inbox_changed':
      inboxChanged(m);
      break;
    case 'contact_note_said':
      // A relationship or research typed on a contact card that could not
      // be kept. One that was kept comes back as `ui`, the card drawn again.
      contactNoteSaid(m.card, m.why);
      break;
    case 'card_ask_said':
      // A press on a card's Save or Don't save that could not be honoured:
      // iCloud out of reach, or it was answered already. A card that did
      // what it was asked is drawn again instead, as `ui`.
      askSaid(m.card, m.why, m.again);
      break;
    case 'card_pick_said':
      // Research pressed on somebody a LinkedIn search found, and not done:
      // LinkedIn slow or out of reach, no profile there any more, or a list
      // too old to press. One that was done comes back as two `ui`s, the
      // profile and the list saying which card it is on.
      pickSaid(m.card, m.why, m.again);
      break;
    case 'permission_gone':
      // Answered on another device, or it ran out of time while this one
      // was reading it. A button that does nothing looks like a broken
      // button, so it is said.
      onPermissionDone({ id: m.id, answer: 'refuse', gone: true });
      break;
    case 'ui':
      if (m.spec) renderCard(m.spec, false, !!m.in_place);
      // A card filed into the task being looked at is a step that was not
      // there a second ago, so the list it belongs on is read again. Without
      // this the person is standing in the one place the new step should be
      // and cannot see it until they leave and come back.
      if (m.spec && m.spec.filed_rel) cardWasFiled(m.spec.filed_rel);
      break;
    case 'card_filed':
      // The answer to asking for one card to be put on the record, whether
      // the press was on the card or the words were said out loud. The card
      // is already on screen and stays where it is; what changes is the chip
      // it wears (`cardFiled`), and the canvas if the new step belongs to
      // what it is showing.
      if (m.spec) cardFiled(m.spec);
      if (m.spec && m.spec.filed_rel) cardWasFiled(m.spec.filed_rel);
      break;
    case 'panels':
      // The columns answer to the voice as well as to the two buttons, since
      // this is meant to be usable without touching anything.
      if (window.setCols) window.setCols({ tasks: m.tasks, chat: m.transcript, canvas: m.canvas });
      // And so does the orb: "show me the orb", "put the orb away".
      if (typeof m.orb === 'boolean') orbExpand(m.orb);
      break;
    case 'tree':
      // Everything running right now, as one tree. The orb is the only thing
      // that reads it, and nothing on the page waits for it to arrive.
      noteServerClock(m.now);
      applyTree(m.tree);
      ORB_SOUND.whole = false;
      break;
    case 'tree_delta':
      // One mutation rather than the whole thing. Applying a delta wrongly
      // leaves a structure on screen that nothing will ever correct, so this
      // asks for the whole tree instead - at most once a second.
      if (now() - shared.askedTreeAt > 1000) { shared.askedTreeAt = now(); send({ type: 'get_tree' }); }
      break;
    case 'audio_start':
      noteTurnSign(m.turn_id);
      onAudioStart(m);
      break;
    case 'audio_end':
      noteTurnSign(m.turn_id);
      onAudioEnd();
      break;
    case 'task':
      upsertTask(m);
      // A run started from a feature request is an ordinary run, so it
      // arrives here like every other one. This is the message that carries
      // a single run moving - the whole list below is only sent on connect -
      // and it is what puts "run running" and then "run finished" on that
      // request's card with nothing polling (section 12).
      gtBoardRefresh(m.id);
      break;
    case 'tasks':
      // `whole` is the list that follows a handshake, which is the truth: a
      // card for a run the server has no row for is left over from before.
      applyTaskList(m.tasks, !!m.whole);
      gtBoardRefresh();
      break;
    case 'gene_therapy':
      // Something on the Gene therapy board moved with nobody pressing
      // anything: a feedback read and turned into a feature request, or a run
      // started for one (rouh/triage.py). The board redraws itself, so
      // somebody watching their own mutation sees it picked up. The message
      // was `feedback` until 12 October 2026.
      gtBoardRefresh();
      break;
    case 'tasks_forgotten':
      forgetTasks(m.ids);
      break;
    case 'workspace':
      applyWorkspace(m.tasks);
      break;
    case 'canvas':
      // Rouh pointing the canvas, because the person asked for something
      // out loud. The numbers they already say are the address of
      // everything: a task loads that task, a step loads that step, and
      // asking what they have on opens the task browser.
      canvasMessage(m);
      break;
    case 'offline_results':
      // What became of actions done offline, here or on the other device (`rouh/offline.py`).
      offlineResults(m.results, false);
      break;
    case 'error':
      // `lasting` is a failure the person has to act on - a chat grown past
      // what its model can read - and stays until they close it.
      notify(m.message || 'Something failed.', { tone: 'error', lasting: !!m.fatal || !!m.lasting });
      setBusy(false);
      if (m.fatal) setMic(true);
      break;
    case 'pong':
      break;
    default:
      break; // unknown types are ignored on purpose
  }
}

export { connect, CONN_WORDS, handleMessage, heldMoved, holdMessages, releaseMessages, S, send, sendBinary, setConn,
  tabChatWanted };
