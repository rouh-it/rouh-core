/* Rouh's page, the one program's runs, opened on the canvas; the Start box; your workspace's tasks (section 10b of what was one app.js).
 *
 * Imports app/tasks.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { ago, byStart, JOBVIEW, jobViewing, markSeen, railPaint, renderTasks, runsShowing,
  SHOW_ARCHIVED, since, taskCard, taskRecs } from 'app/tasks.js';
import { shared } from 'app/shared.js';
import { $, el, esc, linkTo, safeParse, siloChip } from 'app/helpers.js';
import { anatomyGroups, anatomyMoved, navNowCount } from 'app/navgroups.js';
import { drop, load, store } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { S, send } from 'app/socket.js';
import { clockOfMs, orbExpand, orbPlace, orbWanted, ORBX } from 'app/orb.js';
import { scrollDown } from 'app/transcript.js';
import { ASK_ROUTE, cardViewClose, clockOf, contentOpen, drawnClose, drawnOpen, FILING,
  footnotes, frameLoad, goalMapTell, goToAddress, layerOpen, mdCells, mdIsRule, renderBlock,
  renderMarkdown, showLayer, sourcesLast, standingDown, svgEl, taskPageFolder, WORKSPACE_ROUTE } from 'app/cards.js';
import { chatById, chatMenuShow, CHATS, FORKS, isSendKey, openChat, sendKeys, showCrumb, withSendKeys } from 'app/chats.js';
import { detachAsk } from 'app/search.js';
import { ADDR, ADDR_BROWSER, addrAsk, addrBack, addrIsTasksOwn, addrOf, addrOfFolder, addrPlaceLink, addrRead,
  addrTouch } from 'app/address.js';
import { tryThis } from 'app/welcome.js';
import { traceOn, traceSet, traceShowAll } from 'app/turnline.js';
import { accountMenu, canvasAwayIfBare, canvasIsWanted, chatIsWanted, chatOnScreen, chatPutAway, growInput, input, narrow,
  ownName, screenHeight, setPane, sidebarDone, tasksHold, tasksTakeChat } from 'app/controls.js';
import { dragHasFiles, drawTurnFiles } from 'app/attachments.js';
import { gtBoardClose } from 'app/gene_therapy.js';

/* ---------------------------------------------------------------- 10b */

/* The one program's runs, opened on the canvas, and your workspace's tasks.
 *
 * The person asked on 15 September for one page: Rouh's voice, the orb,
 * the runs and the tasks of their assistant workspace (D45). The runs were
 * already on the task list, through Rouh's server. Clicking one now opens
 * it where the cards are: its terminal live, what it did, a box to send it a
 * message, and Stop. For that this page talks to the program itself, on the
 * program's own socket (/one/ws) with the program's messages
 * (one/protocol.py): a run's terminal never shares a socket with the voice's
 * audio, and Rouh restarting does not cut it. The program lets in only a
 * browser paired with it once, with a code; the column says nothing about
 * that, and pressing a run on an unpaired browser goes and gets it paired.
 *
 * Every piece of text from the program goes in with textContent.
 */

// The program's own states, in words, and which of them are a run that is
// over (`ENDED` in one/views.py). `unfinished` - a run that ended with work
// its checkout still held - was in neither, so a run in that state had the
// raw word "unfinished" under its title and was treated as though it were
// still going: Stop offered, the message box that carries an ended run on
// hidden, and a terminal asked for that had gone with the run.
var ONE_WORDS = {
  queued: 'Queued', starting: 'Starting', working: 'Working',
  asking: 'Needs you', saving: 'Saving its work', idle: 'Finished its turn',
  done: 'Done', unfinished: 'Unfinished', failed: 'Failed', lost: 'Died',
  refused: 'Refused', reaped: 'Cleaned up'
};
var ONE_ENDED = { done: 1, unfinished: 1, failed: 1, lost: 1, refused: 1, reaped: 1 };

// The run somebody asked for before this browser was paired with the
// program. It is kept here while they are away at the pairing page, so the
// click that sent them there finishes by itself when they come back, and it
// is thrown away after a few minutes: a run wanted half a day ago is not
// what the person means to open on their next visit.
var PAIR_WANTED = 'rouh.one.pairWanted';
var PAIR_WANTED_FOR = 10 * 60 * 1000;

var ONE = {
  ws: null, next: 0, waiting: {}, backoff: 500,
  device: null, devices: {}, runs: {}, questions: [],
  // Whether this browser is paired: null until the program has said.
  paired: null,
  selected: null, viewing: false, term: null,
  // Who sized the run's terminal when it was not this page (D51): it is
  // drawn at their size until this page is used again. When that somebody
  // is a real terminal the size is theirs until they close it, and nothing
  // this page does may change it (D52).
  sizedBy: null, sizedHard: false,
  // When this page last sent the run a click, so only it takes a copy (D51).
  mouseAt: 0,
  // The run whose terminal this page still has to ask for: one just started
  // has none yet, and one carried on gets a new one.
  termWanted: null,
  // Typing into the run (D46): the run whose keyboard this page holds, keys
  // waiting to go, and whether a take is on its way.
  driving: null, typed: [], taking: false,
  // The run has no terminal to show, so its last words and a message box
  // stand in for it (D48).
  noTerm: false,
  // Sizes the run's terminal to this page's box (D50).
  fit: null
};

// Called by the orb before this section has run, so ONE may not exist yet.
function oneViewing() { return !!(ONE && ONE.viewing); }
function oneIsOpen(id) { return oneViewing() && ONE.selected === id; }

// The program's socket, beside this page where nginx sends /one/. For a
// test on the laptop against a program on another port, ?one= may name
// another, and only on the laptop.
function oneUrl() {
  var local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  var asked = local ? new URLSearchParams(location.search).get('one') : null;
  if (asked) return asked;
  return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/one/ws';
}

// The program's pairing page, which sends the browser back here when done.
// Nothing on the column links to it any more - the sentence that did is
// gone - but `oneAskToPair` still has to take the person there.
function onePairUrl() {
  var page = oneUrl().replace(/^ws/, 'http').replace(/\/ws$/, '/pair');
  return page + '?next=' + encodeURIComponent(location.pathname);
}

function oneSend(t, fields) {
  return new Promise(function (resolve, reject) {
    var ws = ONE.ws;
    if (!ws || ws.readyState !== 1) { reject(new Error('The one program is not connected.')); return; }
    var id = ++ONE.next;
    ONE.waiting[id] = { resolve: resolve, reject: reject };
    var msg = { t: t, id: id }, k;
    for (k in (fields || {})) msg[k] = fields[k];
    ws.send(JSON.stringify(msg));
  });
}

function oneConnect() {
  var ws;
  try { ws = new WebSocket(oneUrl()); } catch (e) { return; }
  ONE.ws = ws;
  ws.onopen = function () {
    ONE.backoff = 500;
    oneSend('hello').then(function (hello) {
      ONE.device = hello;
      onePaired(true);
      return Promise.all([
        oneSend('runs', { watch: true, limit: 200 }),
        oneSend('questions', { watch: true }),
        oneSend('devices')
      ]);
    }).then(function (got) {
      ONE.runs = {};
      (got[0].runs || []).forEach(function (r) { ONE.runs[r.id] = r; });
      ONE.questions = got[1].questions || [];
      ONE.devices = {};
      (got[2].devices || []).forEach(function (d) { ONE.devices[d.id] = d; });
      if (ONE.viewing && ONE.selected) oneRejoin(ONE.selected);
      else oneOpenAfterPairing();
    }).catch(function (err) { console.warn('one:', err.message); });
  };
  ws.onmessage = function (ev) {
    var m = safeParse(ev.data);
    if (m) oneHandle(m);
  };
  ws.onclose = function (ev) {
    if (ONE.ws === ws) ONE.ws = null;
    var id;
    for (id in ONE.waiting) ONE.waiting[id].reject(new Error('The one program closed the connection.'));
    ONE.waiting = {};
    // Not paired: the program says so with 4401, and asking again changes
    // nothing until this browser is paired.
    if (ev.code === 4401) { onePaired(false); return; }
    setTimeout(oneConnect, ONE.backoff);
    ONE.backoff = Math.min(ONE.backoff * 2, 15000);
  };
}

function oneHandle(m) {
  if (m.re !== undefined && ONE.waiting[m.re]) {
    var w = ONE.waiting[m.re];
    delete ONE.waiting[m.re];
    if (m.t === 'err') w.reject(new Error(m.why || 'The one program said no.'));
    else w.resolve(m);
    return;
  }
  switch (m.t) {
    case 'driving':
      if (oneIsOpen(m.run)) ONE.driving = m.run;
      break;
    case 'watching':
      if (ONE.driving === m.run) ONE.driving = null;
      break;
    case 'run':
      ONE.runs[m.run.id] = m.run;
      // Given back meanwhile, by leaving it quiet: the next key takes it again.
      if (ONE.driving === m.run.id && m.run.driver !== (ONE.device && ONE.device.device)) {
        ONE.driving = null;
      }
      if (oneIsOpen(m.run.id)) {
        if (ONE_ENDED[m.run.state]) { ONE.termWanted = m.run.id; ONE.noTerm = true; }
        oneRenderHead();
        if (!ONE_ENDED[m.run.state]) oneWantTerm(m.run.id);
      }
      break;
    case 'questions':
      ONE.questions = m.questions || [];
      if (ONE.viewing) oneRenderAsk();
      break;
    case 'screen':
      if (oneIsOpen(m.run)) oneShowScreen(m);
      break;
    case 'tty':
      if (oneIsOpen(m.run) && ONE.term) ONE.term.write(oneBytes(m.b64));
      break;
    case 'size':
      if (oneIsOpen(m.run)) oneFollow(m);
      break;
    case 'entry':
      if (m.entry && oneIsOpen(m.entry.run)) {
        // Started again - after a crash, or moved onto the API key - it is a
        // new process on a new terminal, and the one on the screen is the
        // old one's last picture. Ask for the new one.
        if (m.entry.kind === 'run.restarted') ONE.termWanted = m.entry.run;
        oneWantTerm(m.entry.run);
      }
      break;
    case 'transcript':
      if (oneIsOpen(m.run)) oneReadHear(m);
      break;
    case 'err':
      if (m.why) console.warn('one:', m.why);
      break;
  }
}

// Whether this browser may open runs of the one program. Until the program
// has let it in the rows stay as they are; the column itself says nothing
// about it, because a standing notice over the list was in the way of the
// thing the person came to read (19 September 2026).
//
// Starting a run no longer waits on it. A run is a run whoever runs it
// (rouh/starting.py), so the Start box is always there and what it offers
// is a workspace and a policy - the program's spaces among them when the
// program has told this browser what they are.
function onePaired(yes) {
  ONE.paired = yes;
}

// This browser has asked the program for something it will not answer until
// it is paired, so it goes and gets paired.
//
// Until 19 September this only un-hid a sentence in the column and put the
// keyboard on its link. On a browser that was already showing that sentence
// - which is every unpaired browser, because the program closes its socket
// with 4401 and `onePaired(false)` showed it - that changed nothing anybody
// could see. A run's row is dressed as a row that opens whether or not this
// browser may open one, so clicking a run looked exactly like a broken
// button: the cursor and the hover said "press me" and the press did
// nothing at all. That is what happened when the person's browser met this
// machine's program for the first time, at a new address it had never
// paired at.
//
// So the press now goes to the one page that fixes it, which sends the
// browser straight back here, and the run it was for is remembered so it
// opens on the way back. The sentence itself has since gone from the column
// for good, which is why there is nothing to un-hide here any more.
function oneAskToPair(run) {
  if (run) store(PAIR_WANTED, JSON.stringify({ run: run, at: Date.now() }));
  location.href = onePairUrl();
}

// The run that press was for, once this browser is paired. Their click is
// finished here rather than being dropped at the pairing page: a run that
// is no longer on the program's list, or was asked for long enough ago that
// they have moved on, is forgotten instead.
function oneOpenAfterPairing() {
  var said = load(PAIR_WANTED);
  if (!said) return;
  drop(PAIR_WANTED);
  var want;
  try { want = JSON.parse(said); } catch (err) { return; }
  if (!want || !want.run) return;
  if (Date.now() - (want.at || 0) > PAIR_WANTED_FOR) return;
  if (!ONE.runs[want.run]) return;
  oneOpen(want.run);
}

// --- one run, over the canvas ---

function oneOpen(id) {
  if (ONE.paired === false) { oneAskToPair(id); return; }
  var previous = ONE.selected;
  if (previous && previous !== id) oneSend('detach', { run: previous }).catch(function () {});
  ONE.selected = id;
  ONE.viewing = true;
  ONE.termWanted = null;
  ONE.noTerm = !!(ONE.runs[id] && ONE_ENDED[ONE.runs[id].state]);
  ONE.driving = null;
  ONE.typed = [];
  ONE.sizedBy = null;
  ONE.sizedHard = false;
  oneDropClear();
  // Opened again, as a socket that has come back opens it, it is read from
  // the start: the program forgot who was reading when the socket went.
  oneReadLeave();
  if (ORBX.open) orbExpand(false);
  if (ONE.term) { ONE.term.dispose(); ONE.term = null; }
  $('oneTerm').hidden = true;
  $('oneTermNone').textContent = 'Connecting to its terminal…';
  $('oneTermNone').hidden = false;
  // The program is asked for the run and its terminal before any of this is
  // drawn, and not after it.
  //
  // Both are one turn of the loop either way - the sends go out now and the
  // answers come back after the drawing has finished - so nothing is slower
  // for it, and one thing is very much safer: the ask can no longer be lost
  // to a fault in the drawing. It was, on 22 September 2026. `renderTasks`
  // threw on its way through the rail, six lines above this, and the throw
  // took `oneSend('run')` and the `attach` that follows it with it, leaving
  // the words this function had just put on the screen - "Connecting to its
  // terminal" - as the last thing that ever happened to that pane.
  //
  // Only the run and its newest entry: the terminal shows what it did, and
  // the entries that follow are only a nudge to ask for the terminal again.
  oneWatch(id, true);
  showLayer('runView');
  // Read or Terminal, as this browser last chose (card 723).
  oneShowTab(oneTabWanted(), false);
  // The run opens on the canvas, which is underneath a sidebar that is lying
  // over the page rather than beside it.
  sidebarDone();
  oneCopyReset(false);
  oneRenderHead();
  oneRenderAsk();
  renderTasks();
  orbPlace(orbWanted());
  // On a phone everything is one column: go to where the run now is.
  if (window.matchMedia && window.matchMedia('(max-width: 899px)').matches) {
    $('canvasPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
}

// Ask the program for the run, its newest entry and the ones after it, and
// then for its terminal. `attach` false leaves the terminal on the screen as
// it is, for a run that has ended: it has none to attach to any more.
function oneWatch(id, attach) {
  return oneSend('run', { run: id, entries: 1 }).then(function (detail) {
    if (!oneIsOpen(id)) return null;
    ONE.runs[id] = detail.run;
    if (ONE_ENDED[detail.run.state]) ONE.noTerm = true;
    oneRenderHead();
    var entries = detail.entries || [];
    var last = entries.length ? entries[entries.length - 1].n : 0;
    return oneSend('tail', { run: id, since: last });
  }).catch(function (err) {
    console.warn('one:', err.message);
  }).then(function () {
    if (attach && oneIsOpen(id)) oneAttach(id);
  });
}

/* The program's socket came back with this run still open.

   Until 5 October 2026 this was `oneOpen` again, the whole of a press on the
   run's row, and a press is the person asking to look at the run. So every
   time the socket dropped and came back - a deploy restarting the program, a
   phone on a weak signal, a tab woken from the background - the run was
   pressed again for them: on a phone the canvas slid back over the
   conversation they had gone to, the Read tab was emptied to "Reading its
   transcript…" and drawn again from the top and dropped to its end, and the
   terminal was thrown away and drawn again. Petar, on his iPhone, with run
   3803bad4 open behind a chat (fr_88dbfd9818fd): "after a few seconds runs
   cover my screen again ... the read part of the terminal refreshes from
   time to time". His phone's socket to the program had closed twice in
   two minutes while Rouh's own stayed up.

   What the program forgot when the socket went is asked for again and
   nothing else: the run and its entries, its terminal, the transcript being
   read, and who holds the keyboard. Nothing is shown, slid in or scrolled,
   and what is on the screen stays there until the answers replace it in
   place. */
function oneRejoin(id) {
  if (!ONE.runs[id]) { oneWatch(id, true); return; }
  ONE.driving = null;
  ONE.typed = [];
  var ended = !!ONE_ENDED[ONE.runs[id].state];
  oneWatch(id, !ended);
  // Whichever tab is up: a transcript read before and left for the
  // terminal is shown again as it stands, without being asked for.
  if (ONE.read.run === id || ONE.tab === 'read') oneReadRejoin(id);
  oneRenderHead();
  oneRenderAsk();
}

function oneClose() {
  // ONE as well as ONE.viewing: this is a layer's closer, and showLayer
  // calls every one of them to stand the others down, which can happen
  // while the page is still being built. See `projectsViewing`.
  if (!ONE || !ONE.viewing) return;
  if (ONE.selected) oneSend('detach', { run: ONE.selected }).catch(function () {});
  ONE.viewing = false;
  ONE.selected = null;
  ONE.termWanted = null;
  ONE.noTerm = false;
  ONE.driving = null;
  ONE.typed = [];
  ONE.sizedBy = null;
  ONE.sizedHard = false;
  oneDropClear();
  oneReadLeave();
  ONE.tab = null;
  $('runView').classList.remove('reading');
  $('oneTermWrap').style.width = '';
  $('oneTermWrap').style.height = '';
  if (ONE.term) { ONE.term.dispose(); ONE.term = null; }
  showLayer(null);
  oneCopyReset(true);
  renderTasks();
  orbPlace(orbWanted());
}

// The command that takes this run over in a real terminal: `one take`, the
// one program's own name for it (one/cli.py). `one attach` only watches,
// and on 16 September a terminal opened with it read as frozen, because
// nothing typed into it reached the run.
//
// The program says how to run it from where this page is being looked at
// (D52): `one take <run>` in a shell on the server itself and on the
// person's laptop, whose one command reaches the server through ssh; and,
// for a machine with no one command of its own, the same behind ssh to the
// server's own address. The whole id is copied, not the first few letters
// the CLI would also take, so what is copied can never mean another run.
function oneAttachCommand() {
  var id = $('oneCopyCmd').getAttribute('data-run');
  var how = (ONE.device && ONE.device.attach) || {};
  return id ? (how.take || 'one take') + ' ' + id : '';
}

// The same command behind ssh, for a machine that has no one command.
function oneAttachOverSsh() {
  var how = (ONE.device && ONE.device.attach) || {}, command = oneAttachCommand();
  return (command && how.ssh && !how.here) ? how.ssh + ' ' + command : '';
}

function oneCopyTitle() {
  var lines = ['Copy the command that takes this run over in your terminal:',
               oneAttachCommand()];
  var far = oneAttachOverSsh();
  if (far) lines.push('On a machine without the one command: ' + far);
  lines.push('Ctrl-] hands it back and leaves.');
  return lines.join('\n');
}

var ONE_COPY = { timer: 0 };

// Show or hide the copy button beside the heading, and put it back to the
// two rectangles after a click has turned it into a tick.
function oneCopyReset(hide) {
  var b = $('oneCopyCmd');
  clearTimeout(ONE_COPY.timer);
  ONE_COPY.timer = 0;
  b.classList.remove('copied');
  b.setAttribute('data-run', ONE.selected || '');
  b.title = oneCopyTitle();
  b.setAttribute('aria-label', oneCopyTitle());
  b.hidden = !!hide;
}

// The clipboard a browser gives a script is only there on a secure page:
// https, or the machine's own localhost. A page opened over plain http at
// another machine's address is not one, and copies the old way instead,
// through a textarea that is selected and gone again in the same breath.
function copyText(text) {
  // A secure page is not a promise that the browser will do it: the
  // permission can be refused, and a page that does not have the window's
  // focus is refused outright. So a rejection falls through to the old way
  // rather than being handed to the caller as "this browser would not".
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).catch(function () {
      return copyTheOldWay(text);
    });
  }
  return copyTheOldWay(text);
}

function copyTheOldWay(text) {
  return new Promise(function (resolve, reject) {
    var box = document.createElement('textarea');
    box.value = text;
    box.setAttribute('readonly', '');
    box.style.position = 'fixed';
    box.style.top = '-1000px';
    document.body.appendChild(box);
    box.select();
    var done = false;
    try { done = document.execCommand('copy'); } catch (err) { done = false; }
    box.remove();
    if (done) resolve(); else reject(new Error('This browser would not copy it.'));
  });
}

// A run's state in one phrase. A run that cannot start yet says what it is
// waiting for and what ends the wait: "Queued" on its own reads as stuck.
// The program works the reason out (one/scheduler.py why_wait) and puts it on
// the run. A run queued for the moment before the program has looked at it
// has none yet, and "Queued" alone is the truth about it.
function oneStateWords(run) {
  var word = ONE_WORDS[run.state] || run.state;
  if (run.state === 'reaped') {
    return word + ' - stopped at the time limit' + (run.left ? ', and ' + run.left : '');
  }
  if (run.state !== 'queued' || !run.queued_because) return word;
  return word + ' - ' + run.queued_because;
}

function oneRenderHead() {
  var run = ONE.runs[ONE.selected];
  if (!run) return;
  $('oneTitle').textContent = run.title || 'A run';
  // The run's own name has arrived, so the tab can stop saying "Run".
  addrTouch();
  var meta = $('oneMeta');
  meta.textContent = '';
  meta.appendChild(el('span', 'one-state s-' + run.state, oneStateWords(run)));
  meta.appendChild(el('span', null, 'Run ' + run.id));
  // Who pays for a run of Codex, always said, and loudly when it is the
  // OpenAI API key (one/billing.py): it is never billed quietly.
  if (run.engine === 'codex') {
    var api = run.billing === 'api';
    var paid = el('span', 'one-billing' + (api ? ' api' : ''),
      api ? 'Codex · billed per token to the OpenAI API key'
          : 'Codex · ChatGPT subscription');
    paid.title = api
      ? (run.billing_was === 'subscription'
        ? 'Moved off the ChatGPT subscription onto the API key, because somebody said yes to it.'
        : 'Started on the OpenAI API key.')
      : "On Codex's own ChatGPT login. If that runs out, the run pauses and asks before the API key is used.";
    meta.appendChild(paid);
  }
  if (run.space) meta.appendChild(el('span', null, run.space === 'assistant' ? 'The assistant' : 'Space ' + run.space));
  if (run.landed && run.compare) {
    var pr = el('a', null, 'Pushed on ' + run.pushed + ': open its pull request');
    pr.href = run.compare;
    pr.target = '_blank';
    pr.rel = 'noopener noreferrer';
    meta.appendChild(pr);
  } else if (run.landed && run.pushed) {
    meta.appendChild(el('span', null, 'Pushed on ' + run.pushed));
  } else if (run.landed) {
    meta.appendChild(el('span', null, 'Saved to ' + (run.target || 'main') + ' at ' + String(run.landed).slice(0, 7)));
  }
  if (run.by) meta.appendChild(el('span', null, 'Asked for by ' + oneWho(run.by)));
  // Where the run belongs, and the way to change it. Rouh holds that and
  // the one program does not, so it is read off the card's own record rather
  // than off `run`, and repainted whenever the column is.
  var own = el('button', 'owner-pick');
  own.id = 'oneOwner';
  own.type = 'button';
  own.addEventListener('click', function () {
    var rec = ONE.selected ? taskRecs[ONE.selected] : null;
    if (rec) openOwner('run', rec.id, rec.title || rec.id);
  });
  meta.appendChild(own);
  oneOwnerPaint();
  var ended = !!ONE_ENDED[run.state];
  var when = ago(ended ? run.ended_at : (run.started_at || run.requested_at));
  if (when) meta.appendChild(el('span', null, (ended ? 'Ended ' : 'Started ') + when));

  var said = $('oneSaid');
  var failed = run.land_reason && !run.landed;
  var words = failed ? 'Could not save to main: ' + run.land_reason : run.last_message;
  said.textContent = '';
  // The terminal shows what the run said. Its last words stand in for it
  // when there is none, and work that could not be saved is always said (D48).
  // Read shows them too, in the transcript, so there it is only a failure.
  said.hidden = !words || (!failed && (ONE.tab === 'read' || !ONE.noTerm));
  if (words) {
    said.appendChild(el('strong', null, failed ? 'Needs you' : 'It said'));
    said.appendChild(document.createTextNode(words));
  }
  $('oneStop').hidden = ended;
  // A run at its prompt stays open until you close it (D49).
  $('oneStop').textContent = run.state === 'idle' ? 'Close' : 'Stop';
  // A run with its terminal on screen is typed into; the message box is for
  // carrying on one that has none (D48), and for Read, which has no keys.
  $('oneSay').hidden = run.kind !== 'agent' || (!ONE.noTerm && ONE.tab !== 'read');
  if ($('oneSay').hidden) $('oneSayNote').hidden = true;
  $('oneSayText').placeholder = ended ? 'Carry it on with a message' : 'Send it a message';
  oneTypingNote(run);
  oneTabsPaint(run);
}

// Where the open run belongs, on its heading. It says so whenever the column
// is drawn, because that is when Rouh has said the owner changed.
function oneOwnerPaint() {
  var b = $('oneOwner');
  if (!b) return;
  var rec = ONE && ONE.selected ? taskRecs[ONE.selected] : null;
  b.hidden = !rec;
  if (!rec) return;
  var words = ownerWords(rec.owned_by);
  b.textContent = 'Belongs to ' + words;
  b.title = 'Move this run';
  b.setAttribute('aria-label', 'Belongs to ' + words + '. Move this run');
}

// Who has the run's keyboard, under its terminal (D46).
function oneTypingNote(run) {
  var note = $('oneTyping'), me = ONE.device && ONE.device.device;
  if (ONE_ENDED[run.state]) note.textContent = 'It has ended. Send it a message below to carry it on.';
  else if (run.driver && run.driver === me) note.textContent = 'You have its keyboard. It goes back when you leave the run or stop typing for two minutes.';
  else if (run.driver) note.textContent = oneWho(run.driver) + ' is typing in it.';
  else note.textContent = 'Click in the terminal and type: your keys go straight to it.';
  // A real terminal has it open, so it is drawn at that terminal's size and
  // can be wider than this box (D52): say so, or the writing looks small
  // for no reason and the right of it looks lost.
  if (ONE.sizedHard) {
    note.textContent += ' It is drawn at that terminal\u2019s size'
      + (oneOverflows() ? '; scroll the terminal to see the rest.' : '.');
  }
}

/* A run's question is a decision (`rouh/decisions.py`), drawn on its card the one
   way every question is (`decision.js`) and answered the one way, with its risk
   confirmed where allowing it cannot be undone. Until Rouh has read it - the
   program tells this page a moment before it tells Rouh - it is the two buttons
   it always was, which answer the program directly. */
/** @type {Record<string, {at: number, d: any}>} */
var ONE_DECIDED = {};
/** @type {Record<string, any>} */
var ONE_DECISION_CARDS = {};
var ONE_DECISION_HOST = null;

function oneDecisionHost() {
  if (!ONE_DECISION_HOST && window.RouhDecision) {
    ONE_DECISION_HOST = window.RouhDecision.fetchHost({ go: function (href) { goToAddress(href); } });
  }
  return ONE_DECISION_HOST;
}

/** @param {string} qid */
function oneDecisionFetch(qid) {
  var had = ONE_DECIDED[qid];
  if (had && (had.d || Date.now() - had.at < 3000)) return;
  ONE_DECIDED[qid] = { at: Date.now(), d: null };
  fetch('/api/decisions/of/run/' + encodeURIComponent(qid), { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (j) {
      if (!j || !j.decision) {
        setTimeout(function () { if (ONE.questions.some(function (q) { return q.id === qid; })) oneRenderAsk(); }, 3200);
        return;
      }
      ONE_DECIDED[qid] = { at: Date.now(), d: j.decision };
      oneRenderAsk();
    })
    .catch(function () {});
}

function oneRenderAsk() {
  var box = $('oneAsk');
  box.textContent = '';
  var mine = ONE.questions.filter(function (q) { return q.run === ONE.selected; });
  mine.forEach(function (q) {
    var had = ONE_DECIDED[q.id];
    if (had && had.d && window.RouhDecision && oneDecisionHost()) {
      box.appendChild(window.RouhDecision.kept(ONE_DECISION_CARDS, had.d, oneDecisionHost(), { place: 'context' }));
      return;
    }
    box.appendChild(oneQuestion(q));
    oneDecisionFetch(q.id);
  });
  box.hidden = !mine.length;
}

function oneQuestion(q) {
  var card = el('div', 'one-q');
  card.appendChild(el('div', null, q.text));
  if (q.detail) card.appendChild(el('div', 'one-q-detail mono', q.detail));
  var row = el('div', 'one-q-buttons');
  // A choice says what each button does; a tool call is allowed or denied.
  var choices = q.choices || {};
  [[choices.yes || 'Allow', 'yes'], [choices.no || 'Deny', 'no']].forEach(function (pair) {
    var b = el('button', 'ctl small', pair[0]);
    b.type = 'button';
    b.addEventListener('click', function () {
      var all = row.querySelectorAll('button'), i;
      for (i = 0; i < all.length; i++) all[i].disabled = true;
      oneSend('answer', { question: q.id, answer: pair[1] }).catch(function (err) {
        for (i = 0; i < all.length; i++) all[i].disabled = false;
        notify(err.message, { tone: 'error' });
      });
    });
    row.appendChild(b);
  });
  card.appendChild(row);
  return card;
}

// --- its terminal ---

function oneBytes(b64) {
  var s = atob(b64), out = new Uint8Array(s.length);
  for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

// As large as the canvas lets the run's own columns and rows be, within reason.
function oneFont(cols, rows) {
  var wrap = $('oneTermWrap');
  var size = Math.floor(Math.min((wrap.clientWidth - 18) / (cols * 0.602),
                                 (wrap.clientHeight - 18) / (rows * 1.2)));
  return Math.max(9, Math.min(13, size || 12));
}

function oneShowScreen(m) {
  if (!window.Terminal) return;
  // A real terminal has this run open: it is that terminal's size, and this
  // page shows it at that size rather than pushing its own box's (D52). The
  // screen says who, every time, so a page that opens the run again after
  // the terminal has gone is its own size once more.
  if (m.sized_by) oneSizedByTerminal(m.sized_by);
  else if (ONE.sizedHard) { ONE.sizedHard = false; ONE.sizedBy = null; }
  if (!ONE.term || ONE.term.cols !== m.cols || ONE.term.rows !== m.rows) {
    if (ONE.term) ONE.term.dispose();
    var run = ONE.runs[ONE.selected], me = ONE.device && ONE.device.device;
    var theirs = !!(ONE.sizedBy || (run && run.driver && run.driver !== me));
    ONE.term = new window.Terminal({
      cols: m.cols, rows: m.rows, disableStdin: false, cursorBlink: false, convertEol: false,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      // The run's terminal takes this page's size (D50), so a font to read;
      // sized by somebody else's keyboard, it is shrunk to fit instead.
      fontSize: theirs ? oneFont(m.cols, m.rows) : 13, scrollback: 5000, allowProposedApi: false,
      // A drag goes to the run once it asks for the mouse; Option and drag
      // still selects in this page's own terminal, as Shift and drag does elsewhere.
      macOptionClickForcesSelection: true,
      theme: { background: '#0b0d12', foreground: '#e6e8ee', cursor: '#e6e8ee' }
    });
    ONE.fit = window.FitAddon ? new window.FitAddon.FitAddon() : null;
    if (ONE.fit) ONE.term.loadAddon(ONE.fit);
    ONE.term.open($('oneTerm'));
    ONE.term.onData(oneKeys);
    ONE.term.attachCustomWheelEventHandler(oneWheel);
    ONE.term.parser.registerOscHandler(52, oneClipboard);
    setTimeout(oneFit, 30);
    if (theirs) setTimeout(oneShrinkToFit, 50);
    oneFollowing();
  } else {
    ONE.term.reset();
  }
  $('oneTermNone').hidden = true;
  $('oneTerm').hidden = false;
  ONE.term.write(oneBytes(m.b64));
  if (ONE.noTerm) { ONE.noTerm = false; oneRenderHead(); }
  // Once it is drawn, the line under it can say whether it fits (D52).
  if (ONE.sizedHard) setTimeout(oneRenderHead, 80);
}

// The run's terminal takes the size of this page's box (D50), unless
// somebody else has its keyboard: its size is theirs then.
var oneFitTimer = 0;
function oneFit() {
  var id = ONE.selected, run = ONE.runs[id], me = ONE.device && ONE.device.device;
  if (!ONE.term || !ONE.fit || !oneIsOpen(id) || !run || ONE_ENDED[run.state]) return;
  // Under Read the terminal is out of sight and its box is not its own: the
  // run keeps its size until the terminal is looked at again (card 723).
  if (ONE.tab === 'read') return;
  if ((run.driver && run.driver !== me) || ONE.sizedBy) return;
  // A real terminal's size is the person's own window, and the program
  // refuses to change it while they are in it (D52).
  if (ONE.sizedHard) return;
  var want = ONE.fit.proposeDimensions();
  if (!want || !(want.cols > 0) || !(want.rows > 0)) return;
  if (want.cols === ONE.term.cols && want.rows === ONE.term.rows) return;
  // This page's terminal first, then the run's: what the run draws for its
  // new size then lands in a terminal already that size (D51).
  var was = { cols: ONE.term.cols, rows: ONE.term.rows };
  ONE.term.resize(want.cols, want.rows);
  oneSend('resize', { run: id, cols: want.cols, rows: want.rows }).then(function (got) {
    if (!ONE.term || !oneIsOpen(id) || !got.cols) return;
    if (got.cols !== ONE.term.cols || got.rows !== ONE.term.rows) ONE.term.resize(got.cols, got.rows);
  }).catch(function (err) {
    if (ONE.term && oneIsOpen(id)) ONE.term.resize(was.cols, was.rows);
    console.warn('one:', err.message);
  });
}

// Somebody else sized the run's terminal (D51): this page draws it at their
// size, its font made to fit, until its own person uses it again.
//
// A real terminal is not "somebody else" who can be talked round: it is a
// window on a person's screen with a size of its own, and the run is that
// size until they close it (D52). No click, key or new box on this page
// changes it, and when the terminal goes the program says so with a size
// nobody owns, which this page takes back.
function oneFollow(m) {
  if (!ONE.term) return;
  if (!m.by) {
    ONE.sizedBy = null;
    ONE.sizedHard = false;
    ONE.term.options.fontSize = 13;
    oneFollowing();
    oneFit();
    oneRenderHead();
    return;
  }
  if (m.terminal) oneSizedByTerminal(m.by);
  else ONE.sizedBy = m.by;
  ONE.term.options.fontSize = oneFont(m.cols, m.rows);
  ONE.term.resize(m.cols, m.rows);
  oneFollowing();
  setTimeout(function () { oneShrinkToFit(); oneRenderHead(); }, 50);
}

// Whether what the run draws is bigger than the box this page gives it.
function oneOverflows() {
  var wrap = $('oneTermWrap'), screen = $('oneTerm').querySelector('.xterm-screen');
  if (!screen || !screen.offsetHeight) return false;
  return screen.offsetWidth > wrap.clientWidth - 8 || screen.offsetHeight > wrap.clientHeight - 8;
}

function oneSizedByTerminal(who) {
  ONE.sizedBy = who || 'a terminal';
  ONE.sizedHard = true;
}

// While the run is a real terminal's size, this page is a window onto it:
// the box scrolls if what the terminal draws is bigger than the box, rather
// than the writing being shrunk until it cannot be read.
function oneFollowing() {
  $('oneTermWrap').classList.toggle('following', !!ONE.sizedHard);
}

// oneFont guesses a row's height from the font's size, and a real row can
// be taller: on 15 September the last row of a run followed at 9px was cut
// off. Measured once drawn, a terminal larger than its box is made smaller,
// down to 9px and no further: on 16 September a page following a terminal
// 204 columns wide drew it at 6px, which the person could not read. What
// still does not fit at 9px is scrolled to instead.
var ONE_SMALLEST = 9;
function oneShrinkToFit() {
  var t = ONE.term, wrap = $('oneTermWrap'), screen = $('oneTerm').querySelector('.xterm-screen');
  if (!t || !screen || !screen.offsetHeight || ONE.tab === 'read') return;
  var room = Math.min((wrap.clientWidth - 16) / screen.offsetWidth,
                      (wrap.clientHeight - 16) / screen.offsetHeight);
  var size = t.options.fontSize;
  if (room >= 1 || size <= ONE_SMALLEST) return;
  t.options.fontSize = Math.max(ONE_SMALLEST, Math.min(size - 1, Math.floor(size * room)));
  setTimeout(oneShrinkToFit, 50);
}

// Used again, by a click, a key or a new size of its box, this page sizes
// the run's terminal to its box once more - unless a real terminal has the
// run open, when the size is that terminal's and this page only fits what
// it draws into its own box (D52).
function oneTakeSize() {
  // Out of sight under Read, the terminal is not being used (card 723).
  if (ONE.tab === 'read') return;
  if (ONE.sizedHard) {
    if (ONE.term) ONE.term.options.fontSize = oneFont(ONE.term.cols, ONE.term.rows);
    setTimeout(oneShrinkToFit, 50);
    return;
  }
  if (ONE.sizedBy) {
    ONE.sizedBy = null;
    if (ONE.term) ONE.term.options.fontSize = 13;
  }
  oneFit();
}

if (window.ResizeObserver) {
  new ResizeObserver(function () {
    clearTimeout(oneFitTimer);
    oneFitTimer = setTimeout(oneTakeSize, 150);
  }).observe($('oneTermWrap'));
}

// The wheel (D51). Claude Code draws on the terminal's full screen, which
// keeps no history, and asks to be told of the mouse: the wheel goes to it,
// without taking the keyboard, and it draws what came before, back to the
// run's beginning. A terminal with a history of its own scrolls that. The
// wheel never becomes arrow keys: on 15 September those reached Claude Code
// as typing (D50).
function oneWheel(ev) {
  var t = ONE.term;
  if (!t) return false;
  // A run a real terminal has open can be drawn larger than this box: the
  // wheel then moves this box over it, rather than scrolling the run under
  // the hands of the person typing in the terminal (D52).
  if (ONE.sizedHard && oneOverflows()) return true;
  var mouse = t.modes ? t.modes.mouseTrackingMode : 'none';
  if (mouse === 'none' && t.buffer.active.type === 'normal') return true;
  ev.preventDefault();
  if (mouse !== 'none') oneScroll(ev.deltaY, ev.deltaMode, ev.clientX, ev.clientY);
  return false;
}

// Turns of the wheel or of a finger, in lines of the terminal, sent
// together every 40 ms. `mode` is a wheel's deltaMode: pixels, lines or pages.
var ONE_WHEEL = { px: 0, lines: 0, col: 1, row: 1, timer: 0 };

function oneScroll(delta, mode, x, y) {
  var t = ONE.term, screen = $('oneTerm').querySelector('.xterm-screen');
  if (!t || !screen) return;
  var box = screen.getBoundingClientRect(), w = ONE_WHEEL;
  var cellW = box.width / t.cols, cellH = box.height / t.rows;
  if (!(cellH > 0)) return;
  w.px += mode === 1 ? delta * cellH : mode === 2 ? delta * box.height : delta;
  var lines = w.px < 0 ? Math.ceil(w.px / cellH) : Math.floor(w.px / cellH);
  if (!lines) return;
  w.px -= lines * cellH;
  w.lines += lines;
  w.col = Math.max(1, Math.min(t.cols, Math.floor((x - box.left) / cellW) + 1));
  w.row = Math.max(1, Math.min(t.rows, Math.floor((y - box.top) / cellH) + 1));
  if (!w.timer) w.timer = setTimeout(oneScrollSend, 40);
}

// A finger over the terminal (fr_66d95f663c91). Once the run asks for the
// mouse, as Claude Code does on its full screen, xterm.js leaves a touch
// alone, and that screen keeps no history of its own to move: on 24
// September Petar could tap into a run's terminal on a phone and type, but
// no swipe moved it at all. A finger drawn up or down over it now turns the
// run's history the way the wheel does, a line for every row the finger
// travels, and a flick carries on and slows to a stop. A tap is left alone,
// so it still brings up the keyboard. Where xterm.js has a history of its
// own, or the box scrolls over a real terminal's larger screen (D52), the
// finger is left to them, as the wheel is.
var ONE_TOUCH = { id: null, y: 0, at: 0, speed: 0, glide: 0 };

function oneTouchTurns() {
  var t = ONE.term;
  if (!t || (ONE.sizedHard && oneOverflows())) return false;
  return (t.modes ? t.modes.mouseTrackingMode : 'none') !== 'none';
}

function oneTouchStart(ev) {
  var f = ONE_TOUCH;
  oneGlideStop();
  f.id = ev.touches.length === 1 && oneTouchTurns() ? ev.touches[0].identifier : null;
  if (f.id === null) return;
  f.y = ev.touches[0].clientY;
  f.at = ev.timeStamp;
  f.speed = 0;
}

function oneTouchMove(ev) {
  var f = ONE_TOUCH;
  if (f.id === null) return;
  var p = ev.touches.length === 1 ? ev.touches[0] : null;
  if (!p || p.identifier !== f.id) { f.id = null; return; }
  // Nothing else under a finger on the terminal scrolls, and a touch whose
  // first move the page lets through becomes the browser's to pan.
  if (ev.cancelable) ev.preventDefault();
  var dy = f.y - p.clientY, dt = ev.timeStamp - f.at;
  if (!dy) return;
  // Pixels a millisecond, the latest move counting most, for the flick.
  if (dt > 0) f.speed = 0.8 * (dy / dt) + 0.2 * f.speed;
  f.y = p.clientY;
  f.at = ev.timeStamp;
  oneScroll(dy, 0, p.clientX, p.clientY);
}

function oneTouchEnd(ev) {
  var f = ONE_TOUCH, x, y;
  if (f.id === null) return;
  for (var i = 0; i < ev.changedTouches.length; i++) {
    if (ev.changedTouches[i].identifier === f.id) { x = ev.changedTouches[i].clientX; y = ev.changedTouches[i].clientY; }
  }
  f.id = null;
  // A finger that stopped before it lifted was not flicking.
  if (ev.type === 'touchend' && x !== undefined && ev.timeStamp - f.at < 80 && Math.abs(f.speed) > 0.3) {
    oneGlide(f.speed, x, y);
  }
}

// The flick: it carries on at the finger's speed and slows to a stop in
// about a second, or at once when the finger comes down again.
function oneGlide(speed, x, y) {
  var id = ONE.selected, last = 0;
  function step(now) {
    ONE_TOUCH.glide = 0;
    var dt = last ? Math.min(now - last, 50) : 16;
    last = now;
    speed *= Math.pow(0.997, dt);
    if (Math.abs(speed) < 0.05 || !oneIsOpen(id) || !oneTouchTurns()) return;
    oneScroll(speed * dt, 0, x, y);
    ONE_TOUCH.glide = requestAnimationFrame(step);
  }
  ONE_TOUCH.glide = requestAnimationFrame(step);
}

function oneGlideStop() {
  if (ONE_TOUCH.glide) cancelAnimationFrame(ONE_TOUCH.glide);
  ONE_TOUCH.glide = 0;
}

$('oneTerm').addEventListener('touchstart', oneTouchStart, { passive: true });
$('oneTerm').addEventListener('touchmove', oneTouchMove, { passive: false });
$('oneTerm').addEventListener('touchend', oneTouchEnd, { passive: true });
$('oneTerm').addEventListener('touchcancel', oneTouchEnd, { passive: true });

function oneScrollSend() {
  var w = ONE_WHEEL, id = ONE.selected, lines = w.lines;
  w.timer = 0;
  w.lines = 0;
  if (!lines || !oneIsOpen(id)) return;
  oneSend('scroll', { run: id, lines: lines, col: w.col, row: w.row }).catch(function (err) {
    $('oneTyping').textContent = err.message;
  });
}

// What the mouse did over the terminal, as xterm.js reports it once the run
// asks for the mouse (D51): in Claude Code's fullscreen renderer a click
// moves the cursor or opens a result, and a drag selects. Presses, releases
// and drags go to the run, together every 40 ms; the wheel goes as scroll,
// and a move with no button held goes nowhere.
var ONE_MOUSE = /\x1b\[<(\d+);\d+;\d+[Mm]/g;
var ONE_CLICKS = { data: '', timer: 0 };

function oneMouse(data) {
  var m, b;
  ONE_MOUSE.lastIndex = 0;
  while ((m = ONE_MOUSE.exec(data))) {
    b = +m[1];
    if ((b & 64) || ((b & 32) && (b & 3) === 3)) continue;
    ONE_CLICKS.data += m[0];
    ONE.mouseAt = Date.now();
  }
  if (ONE_CLICKS.data && !ONE_CLICKS.timer) ONE_CLICKS.timer = setTimeout(oneMouseSend, 40);
}

function oneMouseSend() {
  var id = ONE.selected, data = ONE_CLICKS.data;
  ONE_CLICKS.data = '';
  ONE_CLICKS.timer = 0;
  if (!data || !oneIsOpen(id)) return;
  oneSend('mouse', { run: id, b64: oneB64(data) }).catch(function (err) {
    $('oneTyping').textContent = err.message;
  });
}

// Claude Code copies what is selected on its full screen with OSC 52, the
// terminal's way of setting the clipboard (D51). Only the page whose person
// used the mouse in the last five seconds copies it, not every page watching.
function oneClipboard(data) {
  var b64 = String(data).split(';').pop();
  if (!b64 || b64 === '?' || Date.now() - ONE.mouseAt > 5000 || !navigator.clipboard) return true;
  try {
    var bin = atob(b64), bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    navigator.clipboard.writeText(new TextDecoder().decode(bytes)).catch(function (err) {
      console.warn('one: the clipboard said no:', err.message);
    });
  } catch (err) {
    console.warn('one: the clipboard said no:', err.message);
  }
  return true;
}

// On 15 September a run opened as it was started asked for its terminal a
// second before it had one, was told there was none, and never asked again.
// Now it asks again whenever the run changes, until it is watching.
function oneAttach(id) {
  ONE.termWanted = null;
  return oneSend('attach', { run: id, history: true }).catch(function () {
    if (!oneIsOpen(id)) return;
    ONE.termWanted = id;
    if (ONE.term) { ONE.term.dispose(); ONE.term = null; }
    var run = ONE.runs[id];
    $('oneTerm').hidden = true;
    $('oneTermNone').textContent = run && !ONE_ENDED[run.state]
      ? 'Its terminal appears here as soon as it starts.' : 'This run has no terminal now.';
    $('oneTermNone').hidden = false;
    ONE.noTerm = !!(run && ONE_ENDED[run.state]);
    oneRenderHead();
  });
}

function oneWantTerm(id) {
  var run = ONE.runs[id];
  if (ONE.termWanted === id && run && !ONE_ENDED[run.state]) oneAttach(id);
}

// --- typing into it (D46) ---

// A key in the terminal takes the run's keyboard if this page does not hold
// it yet, then goes to the run. Keys typed while the take is on its way wait
// for it. If somebody else holds it, they are not sent, and the line under
// the terminal says who.
// What xterm.js sends back by itself, typed by nobody: its answers to the
// run's questions about the terminal (what it is, where the cursor is, its
// colours), focus in and out, and the mouse. On 15 September a real Claude
// Code asked, and the page took the keyboard before a key was pressed. They
// neither take the keyboard nor go to the run.
var ONE_REPORTS = /\x1b\[[?>=]?[\d;]*[cnRt]|\x1b\[\?[\d;]*\$?[uy]|\x1b\[[IO]|\x1b\[<[\d;]*[Mm]|\x1b\[M[\s\S]{3}|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1bP[\s\S]*?\x1b\\/g;

function oneKeys(data) {
  var id = ONE.selected, run = ONE.runs[id];
  if (!oneIsOpen(id) || !run || ONE_ENDED[run.state]) return;
  data = String(data || '');
  // What the mouse did goes to the run on its own, not as typing (D51).
  oneMouse(data);
  data = data.replace(ONE_REPORTS, '');
  if (data) { ONE.typed.push(data); if (ONE.sizedBy) oneTakeSize(); }
  else if (!ONE.typed.length) return;
  if (ONE.driving === id) { oneSendKeys(); return; }
  if (ONE.taking) return;
  ONE.taking = true;
  oneSend('take', { run: id }).then(function () {
    if (!oneIsOpen(id)) return;
    ONE.driving = id;
    oneSendKeys();
  }).catch(function (err) {
    ONE.typed = [];
    $('oneTyping').textContent = err.message;
  }).then(function () { ONE.taking = false; });
}

function oneSendKeys() {
  if (!ONE.typed.length) return;
  var id = ONE.driving, text = ONE.typed.join('');
  ONE.typed = [];
  oneSend('input', { run: id, b64: oneB64(text) }).catch(function () {
    // Given back meanwhile: take it again, and send these keys after all.
    if (ONE.driving === id) ONE.driving = null;
    ONE.typed.unshift(text);
    if (oneIsOpen(id)) oneKeys('');
  });
}

function oneB64(text) {
  var bytes = new TextEncoder().encode(text), s = '';
  for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

$('oneTermWrap').addEventListener('click', function () {
  if (!ONE.term) return;
  ONE.term.focus();
  if (ONE.sizedBy) oneTakeSize();
});

/* --- dropping a file on it (D52) ---
 *
 * Claude Code turns a path pasted at its prompt into an attachment and shows
 * it as [Image #1]; a path typed key by key stays a path. So a screenshot dropped here never travels down the
 * run's terminal as bytes: the program writes it into a folder the run can
 * read (one/drops.py) and says what to type, and the page types that the
 * way it types a key (D46). No Enter is sent: the person adds their words
 * and presses it themselves.
 */

// The program's own address, beside its socket.
function oneDropUrl() {
  return oneUrl().replace(/^ws/, 'http').replace(/\/ws$/, '/drop');
}

// Whether a drag is over the terminal is "did a dragover arrive just now",
// not dragenter counted against dragleave. Counting flickers as the pointer
// crosses something inside the box, and leaves the box on screen for ever
// when a drag ends outside the window and the last dragleave never comes:
// the lesson the conversation's own drop zone wrote down (11c).
var ONE_DROP = { at: 0, timer: null, dragging: false, busy: false, clear: 0 };

function oneDropSay(text, how) {
  var box = $('oneDrop');
  $('oneDropSay').textContent = text || '';
  box.className = 'one-drop' + (how ? ' ' + how : '');
  box.hidden = !text;
  clearTimeout(ONE_DROP.clear);
  if (how === 'done' || how === 'bad') {
    ONE_DROP.clear = setTimeout(function () {
      if (!ONE_DROP.busy && !ONE_DROP.dragging) oneDropSay('');
    }, how === 'bad' ? 9000 : 4000);
  }
}

// Forgets a drag and anything the box was saying: a different run is open now.
function oneDropClear() {
  oneDragDone();
  ONE_DROP.busy = false;
  oneDropSay('');
}

function oneDragAlive() {
  ONE_DROP.at = Date.now();
  if (!ONE_DROP.busy) {
    ONE_DROP.dragging = true;
    oneDropSay('Drop to attach to this terminal');
  }
  if (ONE_DROP.timer) return;
  ONE_DROP.timer = setInterval(function () {
    if (Date.now() - ONE_DROP.at < 350) return;
    oneDragDone();
  }, 150);
}

function oneDragDone() {
  ONE_DROP.at = 0;
  if (ONE_DROP.timer) { clearInterval(ONE_DROP.timer); ONE_DROP.timer = null; }
  if (!ONE_DROP.dragging) return;
  ONE_DROP.dragging = false;
  if (!ONE_DROP.busy) oneDropSay('');
}

// Whether a run that can still take a file is open here.
function oneDropOpen() {
  var run = ONE.runs[ONE.selected];
  return !!(oneViewing() && ONE.selected && run && !ONE_ENDED[run.state]);
}

['dragenter', 'dragover'].forEach(function (kind) {
  $('oneTermWrap').addEventListener(kind, function (ev) {
    if (!dragHasFiles(ev) || !oneDropOpen()) return;
    // Without this the browser takes the drop itself and leaves the run to
    // show the file; stopping it here keeps it off the conversation's own
    // drop zone, which is the other place on this page that takes a file.
    ev.preventDefault();
    ev.stopPropagation();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
    oneDragAlive();
  });
});
$('oneTermWrap').addEventListener('drop', function (ev) {
  if (!dragHasFiles(ev)) return;
  ev.preventDefault();
  ev.stopPropagation();
  oneDragDone();
  oneDropFiles(ev.dataTransfer.files);
});

// Ctrl or Cmd and V of a picture while the terminal has the keyboard: the
// same as dropping it. Caught before xterm.js sees it; pasted text is still
// xterm's to send to the run as keys.
$('oneTermWrap').addEventListener('paste', function (ev) {
  var files = ev.clipboardData && ev.clipboardData.files;
  if (!files || !files.length || !oneDropOpen()) return;
  ev.preventDefault();
  ev.stopPropagation();
  oneDropFiles(files);
}, true);

// The path goes in as a paste, not as keystrokes. Claude Code only turns a
// path into an attachment when it arrives as one paste: sent key by key it
// stays a path on the screen and the picture never reaches the model, which
// is what a drop on 16 September did (D52). It still takes the run's
// keyboard first, the way any key does (D46), and sends no Enter.
function onePastePath(text) {
  var id = ONE.selected;
  function put() {
    return oneSend('input', { run: id, b64: oneB64(text), paste: true });
  }
  if (ONE.driving === id) return put();
  return oneSend('take', { run: id }).then(function () {
    ONE.driving = id;
    return put();
  });
}

function oneDropFiles(files) {
  var id = ONE.selected, list = Array.prototype.slice.call(files || []);
  if (!list.length) return;
  if (!oneDropOpen()) { oneDropSay('This run has ended: there is nothing to attach a file to.', 'bad'); return; }
  if (ONE_DROP.busy) { oneDropSay('One at a time: the last file is still going up.', 'bad'); return; }
  var named = list.map(function (f) { return f.name || 'the file'; }).join(', ');
  ONE_DROP.busy = true;
  oneDropSay('Uploading ' + named + '…', 'busy');
  var body = new FormData();
  body.append('run', id);
  list.forEach(function (f) { body.append('file', f, f.name || 'drop'); });
  fetch(oneDropUrl(), { method: 'POST', body: body, credentials: 'same-origin' })
    .then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (got) {
        if (!res.ok || !got.ok) throw new Error(got.why || (res.status === 413
          ? 'that file is too big: the most one may be is 20 MB'
          : 'the program could not take that file'));
        return got;
      });
    })
    .then(function (got) {
      if (!oneIsOpen(id)) { ONE_DROP.busy = false; return; }
      var kept = (got.files || []).map(function (f) { return f.name; }).join(', ');
      var run = ONE.runs[id], me = ONE.device && ONE.device.device;
      // Somebody else holding the keyboard cannot be typed over: the file is
      // saved all the same, and its folder is where they find it.
      if (run && run.driver && run.driver !== me) {
        ONE_DROP.busy = false;
        oneDropSay(kept + ' is saved in the run\'s folder, but ' + oneWho(run.driver)
                   + ' has its keyboard, so nothing was typed in.', 'bad');
        return;
      }
      return onePastePath(got.typed).then(function () {
        ONE_DROP.busy = false;
        if (!oneIsOpen(id)) return;
        if (ONE.term) ONE.term.focus();
        oneDropSay(kept + ((got.files || []).length > 1 ? ' are' : ' is')
                   + ' at its prompt. Add words, then press Enter.', 'done');
      });
    })
    .catch(function (err) {
      ONE_DROP.busy = false;
      oneDropSay(err.message, 'bad');
    });
}

/* --- reading it (card 723) ---
 *
 * A run's terminal is a poor thing to read on a phone. Claude Code draws on
 * the terminal's full screen, so a finger's swipe goes to the server as
 * scroll reports and the picture comes back a line further on: it lags,
 * moves a line at a time and runs past where the finger stopped, and the
 * terminal took most of the phone's screen, so the rest of the page was hard
 * to scroll too.
 *
 * So a run of an agent has two tabs. Terminal is the terminal, as it always
 * was. Read is the run's own transcript - the file Claude Code writes as it
 * goes, which the program reads and sends as items (one/transcripts.py) - set
 * as an ordinary page: what it was asked, what it answered with its Markdown
 * drawn, and each tool call as one line that opens on a tap. The page
 * scrolls it itself, so a finger moves it at once.
 *
 * The terminal stays attached under Read the whole time, drawn where nobody
 * sees it, so going back to it is going back to the live terminal and not
 * to a new one. The choice of tab is this browser's own and is remembered;
 * with none yet, a touch screen opens on Read and a computer on Terminal.
 * Everything from the program goes in as text, and a reply's Markdown is
 * drawn from escaped text only.
 */

var ONE_TAB_KEY = 'rouh.one.tab';
// How close to the end counts as being at the end, in pixels.
var READ_NEAR_END = 48;

function oneReadFresh(run) {
  return { run: run || null, loaded: false, items: {}, els: {}, open: {}, whole: {},
           following: true, fresh: false };
}
ONE.read = oneReadFresh(null);
ONE.tab = null;

// Whether the run has two tabs at all: a shell keeps no transcript.
function oneReads(run) {
  return !run || run.kind === 'agent';
}

function oneTabWanted() {
  var said = load(ONE_TAB_KEY);
  if (said === 'read' || said === 'terminal') return said;
  var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  return touch ? 'read' : 'terminal';
}

// Show one tab. `remember` is a person choosing it, which this browser keeps.
function oneShowTab(tab, remember) {
  var run = ONE.runs[ONE.selected];
  if (!oneReads(run)) tab = 'terminal';
  var was = ONE.tab;
  ONE.tab = tab;
  if (remember) store(ONE_TAB_KEY, tab);
  var reading = tab === 'read', wrap = $('oneTermWrap');
  // The terminal's box keeps the size it had while it is out of sight, so
  // putting it away never resizes the run, and bringing it back finds it the
  // size it was.
  if (reading && was !== 'read' && wrap.offsetWidth && wrap.offsetHeight) {
    wrap.style.width = wrap.offsetWidth + 'px';
    wrap.style.height = wrap.offsetHeight + 'px';
  }
  if (!reading) { wrap.style.width = ''; wrap.style.height = ''; }
  $('runView').classList.toggle('reading', reading);
  if (reading) oneReadEnd();
  $('oneRead').hidden = !reading;
  $('oneTermWrap').setAttribute('aria-hidden', reading ? 'true' : 'false');
  $('oneTabRead').setAttribute('aria-selected', reading ? 'true' : 'false');
  $('oneTabTerm').setAttribute('aria-selected', reading ? 'false' : 'true');
  $('oneTabRead').tabIndex = reading ? 0 : -1;
  $('oneTabTerm').tabIndex = reading ? -1 : 0;
  $('oneTabRead').classList.toggle('on', reading);
  $('oneTabTerm').classList.toggle('on', !reading);
  if (reading) {
    // Keys go nowhere they cannot be seen going.
    if (ONE.term && ONE.term.blur) ONE.term.blur();
    oneReadOpen(ONE.selected);
  } else {
    $('oneLatest').hidden = true;
    if (was === 'read' && ONE.term) {
      // Back to the terminal it left, drawn again at its own box's size.
      ONE.term.refresh(0, ONE.term.rows - 1);
      setTimeout(oneTakeSize, 30);
    }
  }
  oneRenderHead();
}

// The run to read, asked for once and then only told what changes.
function oneReadOpen(id) {
  if (!id) return;
  if (ONE.read.run === id) { oneReadSettle(); return; }
  oneReadLeave();
  ONE.read = oneReadFresh(id);
  $('oneReadList').textContent = '';
  oneReadSay('Reading its transcript…');
  oneSend('transcript', { run: id, watch: true }).then(function (got) {
    if (ONE.read.run !== id) return;
    oneReadAll(got.items || [], got.why);
  }).catch(function (err) {
    if (ONE.read.run !== id) return;
    oneReadSay('Its transcript could not be read: ' + err.message);
  });
}

// The same run read again over a socket that has come back: the program
// forgot it was being read when the socket went, so it is asked again, and
// what comes back is laid into the list that is already on the screen -
// only what changed is drawn again - rather than the list being emptied and
// read from the top. Where the reader was, and what they had opened, stays.
function oneReadRejoin(id) {
  var R = ONE.read;
  if (R.run !== id || !R.loaded) { oneReadLeave(); oneReadOpen(id); return; }
  oneSend('transcript', { run: id, watch: true }).then(function (got) {
    if (ONE.read !== R || !oneIsOpen(id)) return;
    var items = got.items || [], list = $('oneReadList'), keep = {};
    items.forEach(function (item) {
      keep[item.id] = true;
      var li = R.els[item.id], was = R.items[item.id];
      R.items[item.id] = item;
      if (!li) {
        // Said while the socket was away, so after everything already here.
        li = rdItem(item);
        R.els[item.id] = li;
        list.appendChild(li);
        if (!R.following) R.fresh = true;
      } else if (JSON.stringify(was) !== JSON.stringify(item)) {
        rdFill(li, item);
      }
    });
    Object.keys(R.els).forEach(function (key) {
      if (keep[key]) return;
      R.els[key].remove();
      delete R.els[key];
      delete R.items[key];
    });
    oneReadSay(items.length ? '' : (got.why || 'Nothing has been said in it yet.'));
    oneReadSettle();
  }).catch(function (err) {
    console.warn('one:', err.message);
  });
}

// Stop being told about the run being read, if there is one.
function oneReadLeave() {
  var id = ONE.read.run;
  ONE.read = oneReadFresh(null);
  $('oneLatest').hidden = true;
  if (id) oneSend('transcript', { run: id, watch: false }).catch(function () {});
}

function oneReadSay(text) {
  var none = $('oneReadNone');
  none.textContent = text || '';
  none.hidden = !text;
}

// Everything read so far, drawn at once, and the reader put at its end,
// unless `stay` says they had scrolled away from it.
function oneReadAll(items, why, stay) {
  var R = ONE.read;
  $('oneReadList').textContent = '';
  R.items = {};
  R.els = {};
  R.whole = {};
  R.loaded = true;
  var frag = document.createDocumentFragment();
  items.forEach(function (item) {
    var li = rdItem(item);
    R.items[item.id] = item;
    R.els[item.id] = li;
    frag.appendChild(li);
  });
  $('oneReadList').appendChild(frag);
  oneReadSay(items.length ? '' : (why || 'Nothing has been said in it yet.'));
  oneRenderHead();
  R.following = !stay;
  oneReadSettle();
}

// What the program says changed, as it changes.
function oneReadHear(m) {
  var R = ONE.read;
  // Before the first answer, the answer has all of it; a reset is the
  // first answer when the run had no transcript yet.
  if (m.run !== R.run || (!R.loaded && !m.reset)) return;
  // Read again from the start: the run has only now said where its
  // transcript is, or the file was cut back.
  if (m.reset) { oneReadAll(m.items || [], m.why, !R.following); return; }
  var added = false;
  (m.items || []).forEach(function (item) {
    R.items[item.id] = item;
    var li = R.els[item.id];
    if (li) { rdFill(li, item); return; }
    li = rdItem(item);
    R.els[item.id] = li;
    $('oneReadList').appendChild(li);
    added = true;
  });
  if (m.why && !(m.items || []).length) oneReadSay(m.why);
  else if (added) oneReadSay('');
  if (added && !R.following) R.fresh = true;
  oneReadSettle();
}

// Follow the end while the reader is at it, and offer the way back to it
// once they have left it.
function oneReadSettle() {
  var R = ONE.read, v = $('runView');
  if (ONE.tab !== 'read') return;
  if (R.following) {
    v.scrollTop = v.scrollHeight;
    R.fresh = false;
  }
  oneLatestPaint();
}

// How much room the view keeps at its foot, which on a phone is the orb's
// (app.css); the message box reaches over it rather than floating above it.
function oneReadEnd() {
  var v = $('runView');
  v.style.setProperty('--view-end', getComputedStyle(v).paddingBottom || '12px');
}
window.addEventListener('resize', function () { if (ONE.tab === 'read') oneReadEnd(); });

function oneReadAtEnd() {
  var v = $('runView');
  return v.scrollHeight - v.scrollTop - v.clientHeight < READ_NEAR_END;
}

function oneLatestPaint() {
  var b = $('oneLatest'), R = ONE.read;
  b.hidden = ONE.tab !== 'read' || !R.loaded || R.following;
  b.classList.toggle('fresh', !!R.fresh);
  b.textContent = R.fresh ? 'Latest, new below' : 'Latest';
}

$('runView').addEventListener('scroll', function () {
  if (ONE.tab !== 'read' || !ONE.read.loaded) return;
  var at = oneReadAtEnd();
  if (at === ONE.read.following) return;
  ONE.read.following = at;
  if (at) ONE.read.fresh = false;
  oneLatestPaint();
}, { passive: true });

$('oneLatest').addEventListener('click', function () {
  var v = $('runView'), far = v.scrollHeight - v.scrollTop - v.clientHeight;
  ONE.read.following = true;
  ONE.read.fresh = false;
  oneLatestPaint();
  v.scrollTo({ top: v.scrollHeight, behavior: far > 2400 ? 'auto' : 'smooth' });
});

// The two tabs, pressed or walked with the arrows.
['oneTabRead', 'oneTabTerm'].forEach(function (id) {
  $(id).addEventListener('click', function () {
    oneShowTab(id === 'oneTabRead' ? 'read' : 'terminal', true);
  });
});
$('oneTabs').addEventListener('keydown', function (e) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  e.preventDefault();
  var next = ONE.tab === 'read' ? 'terminal' : 'read';
  oneShowTab(next, true);
  $(next === 'read' ? 'oneTabRead' : 'oneTabTerm').focus();
});
$('oneWaitsGo').addEventListener('click', function () { oneShowTab('terminal', true); });

// The parts of the run's view that depend on the tab, drawn with its head.
function oneTabsPaint(run) {
  var two = oneReads(run), reading = ONE.tab === 'read';
  // It turned out to be a shell, which is its terminal and nothing else.
  if (!two && reading) { oneShowTab('terminal', false); return; }
  $('oneTabs').hidden = !two;
  // Claude Code asking on its own screen is only answered there.
  var waits = reading && run.waiting_on_terminal && !ONE_ENDED[run.state];
  $('oneWaits').hidden = !waits;
  if (waits) $('oneWaitsSay').textContent = 'It is waiting on its terminal: ' + run.waiting_on_terminal;
  $('oneTyping').hidden = reading;
  var state = $('oneReadState');
  var words = !reading || !ONE.read.loaded ? '' :
    run.state === 'working' || run.state === 'starting' || run.state === 'saving' ? oneStateWords(run) :
    run.state === 'asking' ? 'It needs you: the question is at the top.' :
    run.state === 'idle' ? 'It has finished its turn. Send it a message below to carry on.' :
    ONE_ENDED[run.state] ? oneStateWords(run) + '. Send it a message below to carry it on.' :
    oneStateWords(run);
  state.textContent = words;
  state.hidden = !words;
  state.className = 'rd-state s-' + run.state;
}

/* An item of the transcript, as the program sends it (one/transcripts.py):
   a prompt, a reply, a thought, a tool call or a note. */

function rdItem(item) {
  var li = el('li');
  rdFill(li, item);
  return li;
}

function rdFill(li, item) {
  item = rdWholeOf(item);
  li.textContent = '';
  li.className = 'rd rd-' + item.kind;
  li.setAttribute('data-id', item.id);
  if (item.kind === 'reply') {
    var md = el('div', 'rd-md');
    // Every piece of it went through esc first (rdInline, rdMarkdown).
    md.innerHTML = rdMarkdown(item.text);
    li.appendChild(md);
    if (rdCut(item, 'text')) li.appendChild(rdWholeButton(li, item));
  } else if (item.kind === 'prompt') {
    if (item.from === 'program') li.classList.add('rd-program');
    var head = el('div', 'rd-who');
    head.appendChild(el('span', null, item.from === 'program' ? 'From the program'
      : item.queued ? 'Prompt, sent while it worked' : 'Prompt'));
    var at = item.at ? Date.parse(item.at) : 0;
    if (at) head.appendChild(el('time', null, clockOfMs(at).slice(0, 5)));
    li.appendChild(head);
    var text = el('div', 'rd-text', item.text);
    li.appendChild(text);
    rdClamp(li, text, item);
    if (rdCut(item, 'text')) li.appendChild(rdWholeButton(li, item));
  } else if (item.kind === 'tool' || item.kind === 'thinking') {
    var tool = item.kind === 'tool';
    if (tool && !item.done) li.classList.add('running');
    if (tool && item.error) li.classList.add('bad');
    var line = el('button', 'rd-line');
    line.type = 'button';
    line.appendChild(el('span', 'rd-mark'));
    line.appendChild(el('span', 'rd-name', tool ? item.name : 'Thinking'));
    line.appendChild(el('span', 'rd-sum', tool ? (item.line || '') : rdFirstLine(item.text)));
    var open = !!ONE.read.open[item.id];
    line.setAttribute('aria-expanded', open ? 'true' : 'false');
    line.title = tool ? (item.name + (item.line ? ': ' + item.line : '')) : 'What it thought';
    line.addEventListener('click', function () {
      ONE.read.open[item.id] = !ONE.read.open[item.id];
      rdFill(li, ONE.read.items[item.id] || item);
    });
    li.appendChild(line);
    if (open) {
      var body = tool ? rdToolBody(item) : rdThought(item);
      if (rdCut(item, 'detail') || rdCut(item, 'result') || rdCut(item, 'text')) {
        body.appendChild(rdWholeButton(li, item));
      }
      li.appendChild(body);
    }
  } else {
    if (item.error) li.classList.add('bad');
    li.appendChild(el('span', null, item.text || ''));
    if (rdCut(item, 'text')) li.appendChild(rdWholeButton(li, item));
  }
}

/* Anything long is sent cut to its start and its end, with how much is
   left out between them said in its place, and `cut` naming what was cut
   (one/transcripts.py, sent). The whole of it is asked for on a press and
   kept while the run is read, so the Read tab never ends where the
   terminal did not (fr_631835dca7bb). */

function rdCut(item, field) {
  return !!(item.cut && item.cut.indexOf(field) >= 0);
}

// The item whole, once it has been asked for and while it still says the
// same: a tool call that has come back since is cut again until asked.
function rdWholeOf(item) {
  var whole = ONE.read.whole[item.id];
  if (!whole) return item;
  if (!!whole.done !== !!item.done) { delete ONE.read.whole[item.id]; return item; }
  return whole;
}

function rdWholeButton(li, item) {
  var b = el('button', 'rd-more rd-whole', 'Show all of it');
  b.type = 'button';
  b.addEventListener('click', function () {
    var run = ONE.read.run;
    b.disabled = true;
    b.textContent = 'Reading all of it…';
    oneSend('transcript', { run: run, item: item.id }).then(function (got) {
      if (ONE.read.run !== run || !got.item) return;
      ONE.read.whole[item.id] = got.item;
      rdFill(li, ONE.read.items[item.id] || item);
    }).catch(function (err) {
      b.disabled = false;
      b.textContent = 'It could not be read whole (' + err.message + '). Try again';
    });
  });
  return b;
}

// A long prompt, a brief say, is shown to twelve lines with a way to the rest.
function rdClamp(li, text, item) {
  if (String(item.text || '').split('\n').length <= 12 && String(item.text || '').length <= 900) return;
  var whole = !!ONE.read.open[item.id];
  text.classList.toggle('clamped', !whole);
  var more = el('button', 'rd-more', whole ? 'Show less' : 'Show all');
  more.type = 'button';
  more.addEventListener('click', function () {
    ONE.read.open[item.id] = !ONE.read.open[item.id];
    rdFill(li, item);
  });
  li.appendChild(more);
}

function rdFirstLine(text) {
  var line = String(text || '').split('\n').filter(function (l) { return l.trim(); })[0] || '';
  return line.replace(/[*_`#>]/g, '').trim();
}

function rdToolBody(item) {
  var box = el('div', 'rd-body');
  if (item.detail) box.appendChild(rdPre(item.detail, item.diff));
  if (!item.done) box.appendChild(el('p', 'rd-quiet', 'Still running…'));
  else if (item.result) {
    var out = rdPre(item.result, false);
    out.classList.add('rd-out');
    if (item.error) out.classList.add('bad');
    box.appendChild(out);
  } else box.appendChild(el('p', 'rd-quiet', item.error ? 'It failed, and said nothing.' : 'Nothing came back.'));
  return box;
}

function rdThought(item) {
  var box = el('div', 'rd-body');
  box.appendChild(el('div', 'rd-thought', item.text || ''));
  return box;
}

// Text as it was, wrapped to the width rather than scrolled sideways. The
// lines of an edit are marked as taken out or put in.
function rdPre(text, diff) {
  var pre = el('pre', 'rd-pre');
  if (!diff) { pre.textContent = text; return pre; }
  String(text).split('\n').forEach(function (line, i) {
    if (i) pre.appendChild(document.createTextNode('\n'));
    var c = line.charAt(0) === '+' ? 'rd-add' : line.charAt(0) === '-' ? 'rd-cut' : null;
    pre.appendChild(el('span', c, line));
  });
  return pre;
}

/* Markdown, the way Claude Code's replies use it: headings, paragraphs,
   lists (inside one another too), code in fences, quotes, rules and tables,
   and in a line code, bold, italics and links. It is the chat's own
   renderer's cousin rather than the chat's own, because a reply of a run is
   mostly code, nested lists and quotes, which the chat's does not draw.
   Every piece of text is escaped before anything is made of it. */

function rdInline(s) {
  // Code first, so nothing inside it is read as bold or as a link.
  var parts = String(s).split(/(`[^`\n]+`)/), out = '';
  for (var i = 0; i < parts.length; i++) {
    if (i % 2) { out += '<code>' + esc(parts[i].slice(1, -1)) + '</code>'; continue; }
    out += esc(parts[i])
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^\w*])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>')
      .replace(/\[([^\]\n]+)\]\(((?:https?:|mailto:)[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }
  return out;
}

var RD_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;

function rdLead(line) { return line.length - line.replace(/^\s+/, '').length; }

function rdMarkdown(src) {
  var lines = String(src == null ? '' : src).replace(/\r/g, '').split('\n');
  var out = [], para = [], i = 0;
  function flush() {
    if (para.length) out.push('<p>' + rdInline(para.join('\n')).replace(/\n/g, '<br>') + '</p>');
    para = [];
  }
  while (i < lines.length) {
    var line = lines[i];
    var fence = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence) {
      flush();
      var code = [];
      for (i++; i < lines.length && lines[i].trim().indexOf(fence[1]) !== 0; i++) code.push(lines[i]);
      i++;
      out.push('<pre class="rd-code"><code>' + esc(code.join('\n')) + '</code></pre>');
      continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    var h = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) {
      flush();
      var level = Math.min(6, h[1].length + 2);
      out.push('<h' + level + '>' + rdInline(h[2]) + '</h' + level + '>');
      i++;
      continue;
    }
    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); i++; continue; }
    if (/^\s{0,3}>/.test(line)) {
      flush();
      var quote = [];
      for (; i < lines.length && /^\s{0,3}>/.test(lines[i]); i++) quote.push(lines[i].replace(/^\s{0,3}> ?/, ''));
      out.push('<blockquote>' + rdMarkdown(quote.join('\n')) + '</blockquote>');
      continue;
    }
    var cells = line.indexOf('|') >= 0 ? mdCells(line) : null;
    if (cells && mdIsRule(lines[i + 1] || '', cells.length)) {
      flush();
      var rows = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].indexOf('|') >= 0; i++) rows.push(mdCells(lines[i]));
      out.push('<div class="rd-table"><table><thead><tr>' +
        cells.map(function (c) { return '<th>' + rdInline(c) + '</th>'; }).join('') +
        '</tr></thead><tbody>' +
        rows.map(function (r) {
          return '<tr>' + r.map(function (c) { return '<td>' + rdInline(c) + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>');
      continue;
    }
    if (RD_ITEM.test(line)) { flush(); i = rdList(lines, i, out); continue; }
    para.push(line.trim());
    i++;
  }
  flush();
  return out.join('');
}

// One list from lines[i], with whatever is indented under an item drawn
// inside that item: another list, a paragraph, a block of code.
function rdList(lines, i, out) {
  var first = RD_ITEM.exec(lines[i]);
  var indent = first[1].length, ordered = /\d/.test(first[2]);
  var start = ordered ? parseInt(first[2], 10) : 1;
  var items = [];
  while (i < lines.length) {
    var line = lines[i], m = RD_ITEM.exec(line);
    if (m && m[1].length === indent) {
      if (/\d/.test(m[2]) !== ordered) break;
      items.push({ head: m[3], rest: [] });
      i++;
      continue;
    }
    if (!line.trim()) {
      // A blank line ends the list unless what follows it is still in it.
      var next = lines[i + 1] || '';
      if (next.trim() && (rdLead(next) > indent || (RD_ITEM.test(next) && rdLead(next) === indent))) {
        if (items.length) items[items.length - 1].rest.push('');
        i++;
        continue;
      }
      break;
    }
    if (rdLead(line) > indent && items.length) {
      items[items.length - 1].rest.push(line);
      i++;
      continue;
    }
    break;
  }
  var tag = ordered ? 'ol' : 'ul';
  out.push('<' + tag + (ordered && start !== 1 ? ' start="' + start + '"' : '') + '>' +
    items.map(function (it) {
      var rest = it.rest, cut = Infinity;
      rest.forEach(function (l) { if (l.trim()) cut = Math.min(cut, rdLead(l)); });
      var inner = rest.length ? rdMarkdown(rest.map(function (l) { return l.slice(cut === Infinity ? 0 : cut); }).join('\n')) : '';
      return '<li>' + rdInline(it.head) + inner + '</li>';
    }).join('') + '</' + tag + '>');
  return i;
}

// --- who someone is ---

function oneWho(id) {
  if (!id) return 'someone';
  if (id === 'console') return "the server's terminal";
  if (id === 'program') return 'the program';
  if (id === 'phone') return 'the phone';
  if (id === 'run') return 'the run';
  if (ONE.device && id === ONE.device.device) return 'you';
  var dev = ONE.devices[id];
  return dev ? dev.name : id;
}

$('oneBack').addEventListener('click', oneClose);
// A tick, and the tooltip says what was copied, for a second and a half.
$('oneCopyCmd').addEventListener('click', function () {
  var b = this, command = oneAttachCommand();
  if (!command) return;
  copyText(command).then(function () {
    clearTimeout(ONE_COPY.timer);
    b.classList.add('copied');
    b.title = 'Copied: ' + command;
    b.setAttribute('aria-label', 'Copied: ' + command);
    ONE_COPY.timer = setTimeout(function () { oneCopyReset(b.hidden); }, 1500);
  }).catch(function (err) { notify(err.message, { tone: 'error' }); });
});
$('oneStop').addEventListener('click', function () {
  var id = ONE.selected, b = $('oneStop');
  if (!id) return;
  b.disabled = true;
  oneSend('stop', { run: id }).catch(function (err) { notify(err.message, { tone: 'error' }); })
    .then(function () { b.disabled = false; });
});
$('oneSay').addEventListener('submit', function (e) {
  e.preventDefault();
  var box = $('oneSayText'), text = box.value.trim();
  if (!text || !ONE.selected) return;
  oneSend('say', { run: ONE.selected, text: text }).then(function (got) {
    box.value = '';
    oneSayNote(got.how);
  }).catch(function (err) { notify(err.message, { tone: 'error' }); });
});

// Where a message went, for a few seconds under the box: at once, after
// what the run is doing now, or into a run carried on (one/runs.py say).
var ONE_SAY_NOTE = 0;
function oneSayNote(how) {
  var note = $('oneSayNote');
  note.textContent = how === 'queued' ? 'It is working, so it gets this as soon as it finishes what it is doing.'
    : how === 'carried on' ? 'Carrying it on with that.' : 'Sent.';
  note.hidden = false;
  clearTimeout(ONE_SAY_NOTE);
  ONE_SAY_NOTE = setTimeout(function () { note.hidden = true; }, how === 'queued' ? 8000 : 3000);
}

// --- the Start box: a brief, a workspace and a policy ---
//
// The same `starting.start` the four spoken verbs are presets over, with
// nothing preset: the person names where the work belongs and under what
// rules, and the run that comes out is a run of exactly the same kind, in
// no chat and under no task until somebody says otherwise.
//
// The workspaces are Rouh's own named ones plus the one program's spaces,
// which the program tells this browser itself and which can also be added
// from here (D44).

var oneFolders = '';

function oneFolderHint() {
  var name = $('oneStartFolder').value.trim();
  $('oneStartFolderHint').textContent = oneFolders
    ? 'On the server: ' + oneFolders + '/' + (name || '…') + ', made if it is not there yet.' : '';
}

function oneShowAdd() {
  var chosen = $('oneStartSpace').value;
  $('oneStartFolderLabel').hidden = chosen !== '+folder';
  $('oneStartRepoLabel').hidden = chosen !== '+repo';
  oneFolderHint();
}

//: What each policy means, in the words a person reads rather than the word
//: the register keeps. The register's words are `objects.POLICIES` and the
//: server sends them, so this page never has a list of its own to fall
//: behind: a policy with nothing said about it here is still offered.
var POLICY_MEANS = {
  one: "the one program's own rules - a terminal can take it over",
  yolo: 'no permission prompts at all; it runs to the end unattended',
  auto: 'unattended, and the riskiest steps stop and ask',
  safe: 'it stops and asks, so somebody has to be watching',
  self: "Rouh's own code, landed with land.sh",
  'local-only': 'it stops and asks, and may not push',
  'direct-pr': 'it may open a pull request'
};

function fillPolicies() {
  var pick = $('oneStartPolicy');
  if (!pick || !OBJ.policies.length) return;
  var chosen = pick.value;
  pick.textContent = '';
  OBJ.policies.forEach(function (name) {
    var o = el('option', null, name + (POLICY_MEANS[name] ? ' - ' + POLICY_MEANS[name] : ''));
    o.value = name;
    pick.appendChild(o);
  });
  // The program's own rules when this browser can reach it, and an
  // unattended worker here when it cannot: either way, something that runs
  // to the end rather than something that stops and waits for a watcher.
  pick.value = chosen || (ONE.paired ? 'one' : 'yolo');
  policyHint();
}

function policyHint() {
  var chosen = $('oneStartPolicy').value;
  $('oneStartPolicyHint').textContent = chosen === 'one'
    ? 'A run of the one program, in the space above.'
    : 'A worker here, in the workspace above, under Claude Code ' + chosen + ' mode.';
  oneAgentShow();
}

// Codex is only ever a run of the one program, and a run of Codex is paid
// for by its ChatGPT subscription unless the OpenAI API key is picked for
// it, here, for this run alone (one/billing.py). The key is offered only
// when the program has one: it says so in its hello.
function oneAgentShow() {
  var one = $('oneStartPolicy').value === 'one';
  if (!one) $('oneStartAgent').value = 'claude';
  var codex = one && $('oneStartAgent').value === 'codex';
  var can = !!(ONE.device && ONE.device.codex_api);
  var pick = $('oneStartBilling');
  $('oneStartAgentLabel').hidden = !one;
  $('oneStartBillingLabel').hidden = !codex;
  pick.querySelector('option[value="api"]').disabled = !can;
  if (!can && pick.value === 'api') pick.value = 'subscription';
  $('oneStartBillingHint').textContent = !can
    ? 'The OpenAI API key has not reached the one program, so only the subscription can be used.'
    : pick.value === 'api'
      ? 'Billed per token to the OpenAI API account, for this run only. Every other run stays on the subscription.'
      : 'If the subscription runs out, the run pauses and asks before anything is billed to the API key.';
}

function oneFillSpaces() {
  var pick = $('oneStartSpace'), chosen = pick.value, known = false;
  pick.textContent = '';
  function put(value, words) {
    var o = el('option', null, words);
    o.value = value;
    if (value === chosen) known = true;
    pick.appendChild(o);
  }
  OBJ.workspaces.forEach(function (w) { put(w.name, w.label); });
  // And the program's own spaces, which it answers for itself.
  return oneSend('spaces', {}).then(function (got) {
    oneFolders = got.folders || '';
    (got.spaces || []).forEach(function (sp) {
      if (!sp.name) return;
      var already = false, i;
      for (i = 0; i < pick.options.length; i++) {
        if (pick.options[i].value === sp.name) already = true;
      }
      if (already) return;
      put(sp.name, sp.name === 'assistant' ? 'The assistant, in your workspace'
        : sp.folder ? sp.name + ' (the folder ' + sp.folder + ')'
        : (sp.repo ? sp.name + ' (' + sp.repo + ')' : sp.name));
    });
  }).catch(function () { /* the named ones alone stay on the list */ })
    .then(function () {
      var addFolder = el('option', null, 'Add a folder…');
      addFolder.value = '+folder';
      var addRepo = el('option', null, 'Add a repository…');
      addRepo.value = '+repo';
      pick.appendChild(addFolder);
      pick.appendChild(addRepo);
      pick.value = chosen.charAt(0) === '+' || known ? chosen
        : (pick.options.length ? pick.options[0].value : '');
      oneShowAdd();
    });
}

$('oneStartSpace').addEventListener('change', oneShowAdd);
$('oneStartPolicy').addEventListener('change', policyHint);
$('oneStartAgent').addEventListener('change', oneAgentShow);
$('oneStartBilling').addEventListener('change', oneAgentShow);
$('oneStartFolder').addEventListener('input', oneFolderHint);
$('oneStart').addEventListener('click', function () {
  $('oneStartError').hidden = true;
  $('oneStartAgent').value = 'claude';
  $('oneStartBilling').value = 'subscription';
  fillPolicies();
  oneAgentShow();
  oneFillSpaces();
  $('oneStartDialog').showModal();
  $('oneStartBrief').focus();
});
$('oneStartCancel').addEventListener('click', function () { $('oneStartDialog').close(); });
$('oneStartForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var brief = $('oneStartBrief').value.trim();
  if (!brief) return;
  var button = $('oneStartGo'), error = $('oneStartError');
  var space = $('oneStartSpace').value;
  var chain = Promise.resolve(space);
  error.hidden = true;
  if (space === '+folder' || space === '+repo') {
    // What is added here becomes a space of the one program's, then the run
    // starts in it.
    var folder = space === '+folder';
    var box = $(folder ? 'oneStartFolder' : 'oneStartRepo');
    var given = box.value.trim();
    if (!given) {
      error.textContent = folder ? "Write the project's name."
        : "Write the repository's name as GitHub shows it: owner/name.";
      error.hidden = false;
      return;
    }
    button.textContent = 'Adding it…';
    chain = oneSend('add_space', folder ? { folder: given } : { repo: given })
      .then(function (got) {
        box.value = '';
        return oneFillSpaces().then(function () {
          $('oneStartSpace').value = got.space;
          oneShowAdd();
          return got.space;
        });
      });
  }
  button.disabled = true;
  chain.then(function (sp) {
    // Starting a worker here makes a worktree and, the first time, a tmux
    // session, which is seconds rather than milliseconds. The button says so
    // rather than sitting there greyed out with nothing happening.
    button.textContent = 'Starting…';
    // Over Rouh's own socket, not the program's: which of the two
    // actually runs it is decided by the policy, on the server, in the one
    // place that decides it for every other way of starting work too.
    /** @type {import('./protocol').ToServer<'start_run'>} */
    var start = { type: 'start_run', brief: brief, workspace: sp,
                  policy: $('oneStartPolicy').value };
    if (start.policy === 'one' && $('oneStartAgent').value === 'codex') {
      start.agent = 'codex';
      // Said only when it is the key: the subscription is what a run is.
      if ($('oneStartBilling').value === 'api') start.billing = 'api';
    }
    send(start);
  }).catch(function (err) {
    error.textContent = err.message;
    error.hidden = false;
    button.disabled = false;
    button.textContent = 'Start';
  });
});

/* ---------- the five objects: what belongs to what ----------

   A project, a task, a chat, a run and an artifact are five things, each
   made on its own and owned by nothing. Owning is one link, one owner at
   most, and it only ever points down:

       project > task > chat > run > artifact

   So there is one dialog here and not five, Move, opened from a run's
   card, from a chat's menu and from a task's row, and it offers exactly
   what the ranking allows plus Nowhere, which is first because an orphan
   is legal and is what everything starts as.

   Moving is attaching, and nothing is copied when it happens. A run's
   diff, its artifacts and its cost were the run's own all along; attaching
   the run to a task is what puts them under that task, and detaching is
   what takes them back. */

var OBJ = { tasks: [], projects: [], workspaces: [], policies: [], owners: {} };

//: What one thing can be, in words, for the dialog's heading and its rows.
//: An artifact is a **card** wherever a person reads it - that is what they
//: are called on the screen they appear on - and `owning.WORDS` on the
//: server says the same, so the delete dialog's heading and the sentence
//: under it cannot use two names for one thing.
var OBJ_WORDS = { project: 'project', task: 'task', chat: 'chat', run: 'run',
                  artifact: 'card' };

/** @param {import('./protocol').FromServer<'objects'>} m */
function applyObjects(m) {
  if (!m) return;
  if (Array.isArray(m.tasks)) OBJ.tasks = m.tasks;
  if (Array.isArray(m.projects)) OBJ.projects = m.projects;
  if (Array.isArray(m.workspaces)) OBJ.workspaces = m.workspaces;
  if (Array.isArray(m.policies)) OBJ.policies = m.policies;
  // The ranking, sent rather than kept here: it lives in objects.RANK and a
  // second copy in this file is a second copy to fall behind.
  if (m.owners_for) OBJ.owners = m.owners_for;
  // The breadcrumb's menu of tasks was read once and kept, and leaves the
  // archived out: a task archived or brought back in the task browser comes
  // down this message, so it is read again the next time the bar is drawn.
  TASKS.asked = false;
  // The projects over that list carry a dot when something under them is
  // finished and unseen, and that dot comes down this very message, so they
  // are drawn again whenever it arrives.
  renderProjects();
  // The owner dialog and the Start box are both drawn from this, so a task
  // made on the phone is on the list here without anybody reloading.
  if ($('ownerDialog').open) ownerFill();
  fillPolicies();
}

// A task's own name as a row reads it: its number in front when it has one,
// which is what says at a glance that it is the workspace's rather than one
// made here.
function objTaskName(t) {
  return (t.number != null ? t.number + ' ' : '') + (t.title || t.id);
}

//: The tasks in the order a picker reads best: the loose ones first, then
//: the highest number down. The order the rail's own list is in is the
//: server's and is when each one last moved.
function tasksByNumber() {
  return (OBJ.tasks || []).slice().sort(function (a, b) {
    var an = a.number == null, bn = b.number == null;
    if (an !== bn) return an ? -1 : 1;
    if (an) return 0;
    return b.number - a.number;
  });
}

function objTaskById(id) {
  var i;
  for (i = 0; i < OBJ.tasks.length; i++) if (OBJ.tasks[i].id === id) return OBJ.tasks[i];
  return null;
}

// Who owns something, in one short line. "Nowhere" rather than a blank,
// because having no owner is an answer and not a missing one.
function ownerWords(owned) {
  if (!owned) return 'Nowhere';
  var name = owned.label || owned.id;
  if (owned.type === 'task') return 'Task ' + (owned.number != null ? owned.number + ' ' : '') + name;
  return (OBJ_WORDS[owned.type] || owned.type).replace(/^./, function (c) {
    return c.toUpperCase();
  }) + ' ' + name;
}

// The task a chat is about, as the head of that chat names it: "task 30 ·
// Jarvis", with a capital where it starts the line. The dot keeps the
// number from reading as the first word of the name.
function taskWords(owned, capital) {
  var name = owned.label || owned.id;
  if (owned.parent || (owned.number == null && owned.step)) {
    // A subtask, by its own number out of its folder: "subtask 68-01 ·
    // Offer for Micro Company" (`rouh/subtasknotes.py`).
    var sub = capital ? 'Subtask' : 'subtask';
    return owned.step ? sub + ' ' + owned.step + ' · ' + name : sub + ' “' + name + '”';
  }
  var word = capital ? 'Task' : 'task';
  return owned.number != null ? word + ' ' + owned.number + ' · ' + name
    : word + ' “' + name + '”';
}

/* ---------- what is new, all the way down ----------

   Petar, 22 September 2026: "the tasks button has a dot for new but at the
   same time on the navigation nothing tells me what is new and what do I
   have to click to make it disappear."

   It was a dead end, and the dead end was the whole of the bug: the dot said
   something had happened and the list underneath it said nothing at all,
   and pressing the button put the dot out whether or not the person had
   seen a single thing. So the mark now runs the length of the column -
   project dot, task dot, step dot - and nothing clears it except opening
   the thing it is on.

   What "new" is, is the server's answer and not this file's
   (`owning._ready_at`): a task or a step is new from the moment its
   artifact is ready to display until the person opens it. Every row arrives
   carrying its own `new`, so nothing here has to guess. */

/* The dot itself, and it is a button rather than a mark, because "what do I
   have to click to make it disappear" deserved a literal answer. Pressing
   the row opens the thing and clears that one thing's dot; pressing the dot
   clears what the dot was standing for, without opening anything. On a
   task or a step that is the row and nothing else, because every step is a
   row of its own with a dot of its own; on a project it is everything in
   it, which the server does whatever it is asked (`owning.mark_seen`). */
function newDot(spec) {
  var b = el('button', 'sb-new');
  b.type = 'button';
  b.title = spec.title;
  b.setAttribute('aria-label', spec.title);
  b.addEventListener('click', function (e) {
    if (e.stopPropagation) e.stopPropagation();
    markSeen(spec.kind, spec.row, true, !!spec.deep);
  });
  return b;
}

/* Every task and every step, however deep, as one list, and which of them
   are steps. The server sends the tree, because the tab's dot and the
   project dots are counted over it; this is the same rows laid end to end.
   Worked out once for each list of tasks that arrives. */
var FLAT = { tasks: null, rows: [], step: {}, width: 0 };

function flatten() {
  if (FLAT.tasks === OBJ.tasks) return FLAT;
  var rows = [], step = {}, width = 0;
  (function walk(list, under) {
    (list || []).forEach(function (t) {
      rows.push(t);
      if (under) step[t.id] = true;
      width = Math.max(width, rowNumberText(t, under).length);
      walk(t.steps, true);
    });
  }(OBJ.tasks, false));
  FLAT = { tasks: OBJ.tasks, rows: rows, step: step, width: width };
  return FLAT;
}

function flatTasks() {
  return flatten().rows;
}

function isStep(t) {
  return !!flatten().step[t.id];
}

//: The number a row is read by: a task's own, and a step's whole place.
function rowNumberText(t, step) {
  if (step) return t.step || '';
  return t.number != null ? String(t.number) : '';
}

/* Opening a step: its own page, where it is and what it holds, whatever it
   built. It used to open the page the step had built, straight away, and
   Petar said on 23 September 2026 why that was confusing: the same page was
   then listed again among the task's artifacts, and a step with two pages
   had no saying which one a press would open. So a press opens the step,
   and its page has the page it built first of all. A step
   with no folder has no page, and what is under it is said in a dialog. */
function openStepItem(s) {
  if (s.folder) canvasStepPage(s.folder);
  else openUnder('task', s.id, (s.step ? s.step + ' ' : '') + (s.title || s.id));
  // A page on the canvas, or the dialog that says what is under it: either
  // way what was opened is in front of a sidebar that is a drawer at this
  // width, so the press that opened it is also the press that is done with
  // the navigation (`sidebarDone`).
  sidebarDone();
}

// Picking a task is picking its conversation. Where it has none yet the
// server hands back a draft of one, and the chat is only written when
// something is said in it, so this is the same press whether anything has
// been said in it or not and opening a task leaves nothing behind
// (`open_thread` in PROTOCOL.md).
function openTaskThread(t) {
  send({ type: 'open_thread', task: t.folder });
  canvasTask(t.folder);
  chatIsWanted();
  sidebarDone();
}

// --- where one thing belongs ---

var OWNING = { kind: '', id: '', what: '' };

// `noun` is the word the button that opened it used, where that is not the
// kind's own: a background job is a run underneath and a job on its card.
function openOwner(kind, id, what, noun) {
  OWNING = { kind: kind, id: id, what: what || id };
  $('ownerError').hidden = true;
  $('ownerHead').textContent = 'Move this ' + (noun || OBJ_WORDS[kind] || kind);
  ownerFill();
  $('ownerDialog').showModal();
}

// The sentence under the heading: what it can go in, in the words of the
// list below it, and that on its own is an answer too. It said "One owner
// at most, and none is the ordinary answer" until Petar said on 24
// September 2026 that it sounded strange; this is the same rule in plain
// words. Drawn with the list, because the ranking it reads can arrive
// after the dialog has opened.
function ownerHint() {
  var can = (OBJ.owners[OWNING.kind] || []).filter(function (kind) {
    return kind === 'project' || kind === 'task' || kind === 'chat';
  }).map(function (kind) { return OBJ_WORDS[kind]; });
  var last = can.pop();
  var one = !last ? 'place' : can.length ? can.join(', ') + ' or ' + last : last;
  $('ownerWhat').textContent = '"' + OWNING.what + '" can be in one ' + one
    + ', or on its own.';
}

function ownerFill() {
  var host = $('ownerList');
  if (!host || !OWNING.kind) return;
  ownerHint();
  host.textContent = '';
  var mine = ownerNow(OWNING.kind, OWNING.id);
  host.appendChild(ownerChoice('', '', 'Nowhere - on its own', !mine));
  // Only what the ranking allows, in its order, and the server said what
  // that is: a task may belong to a project, a chat to a project or a task,
  // a run to any of those three.
  (OBJ.owners[OWNING.kind] || []).forEach(function (kind) {
    if (kind === 'project') {
      OBJ.projects.forEach(function (pr) {
        // Which kind of project it is, because both are on this list: one of
        // the person's own for chats, or a folder in the workspace.
        host.appendChild(ownerChoice('project', pr.id,
          'Project ' + pr.title + (pr.folder ? ' - in the workspace' : ''),
          !!mine && mine.type === 'project' && mine.id === pr.id));
      });
    } else if (kind === 'task') {
      // By number here, and not in the order the rail draws them. The rail
      // is newest first because it is a list of what has just happened; this
      // is a picker, and somebody looking for task 19 in it wants it where
      // 19 belongs. A task made on its own has no number and comes first,
      // because the one just made is the one being filed.
      tasksByNumber().forEach(function (t) {
        if (OWNING.kind === 'task' && t.id === OWNING.id) return;
        host.appendChild(ownerChoice('task', t.id, 'Task ' + objTaskName(t),
          !!mine && mine.type === 'task' && mine.id === t.id));
      });
    } else if (kind === 'chat' && CHATS) {
      (CHATS.list || []).forEach(function (c) {
        if (OWNING.kind === 'chat' && c.id === OWNING.id) return;
        host.appendChild(ownerChoice('chat', c.id, 'Chat ' + (c.title || c.id),
          !!mine && mine.type === 'chat' && mine.id === c.id));
      });
    }
  });
}

// What the page already knows about this one thing's owner, whichever list
// it is on: the tasks, the chats, or the runs.
function ownerNow(kind, id) {
  var i;
  if (kind === 'task') {
    var t = objTaskById(id);
    return t ? t.owned_by : null;
  }
  if (kind === 'chat') {
    var c = chatById(id);
    return c ? c.owned_by : null;
  }
  if (kind === 'run') return taskRecs[id] ? taskRecs[id].owned_by : null;
  return null;
}

function ownerChoice(kind, id, words, on) {
  var b = el('button', 'owner-choice' + (on ? ' on' : ''), words);
  b.type = 'button';
  b.setAttribute('role', 'radio');
  b.setAttribute('aria-checked', on ? 'true' : 'false');
  b.addEventListener('click', function () {
    send({ type: 'attach', kind: OWNING.kind, id: OWNING.id,
           owner_kind: kind, owner_id: id });
  });
  return b;
}

/* ---------- where it went ----------

   Petar, 24 September 2026, reading a day spent as a new customer: "It
   moved - and vanished from my chats, without saying where it went."

   A chat given to a task left the Chats list then, and what was wrong was
   the silence: the row went, and nothing on the screen said where to. So
   every move that lands says, in the tab that made it, where the thing is
   now and which list holds it, with the one press that shows it there.

   A chat given to a task stays on the Chats list since the evening of the
   same day, when Petar said so of one Rouh filed itself: "I don't see it in
   the list of chats, and I should" (`railChats`). The sentence still says
   where it went, which is the task, and that it is still where it was.

   Worked out here rather than on the server. The server's answer names the
   new owner, and that is all it can know: which list the rail keeps a chat
   in is this page's arrangement. It is read the instant the answer arrives,
   before the lists that follow it are drawn, so what the page holds about
   the thing is still what it was before the move. */

var MOVED = { note: null };

/* `how` is 'detached' for a fork detached into a task (`detachAsk`), which
   was cut from the chat it came off as well as moved, and says both. */
/** @param {import('./protocol').FromServer<'attached'>} m @param {string} [how] */
function movedTell(m, how) {
  var kind = String(m.kind || ''), id = String(m.id || '');
  var owner = m.owner || null, before = ownerNow(kind, id);
  var was = kind === 'chat' ? chatById(id) : null;
  var name = movedName(kind, id), where = owner ? placeWords(owner) : '';
  // Only what this page keeps an owner for can be said to be there already;
  // a card's or a project's owner is not on any list here.
  var known = ['chat', 'run', 'task'].indexOf(kind) >= 0;
  var same = known && (owner ? !!before && before.type === owner.type && before.id === owner.id
    : !before);
  var said;
  if (same) said = capital(name) + (owner ? ' is in ' + where + ' already.' : ' is on its own already.');
  else if (owner && how === 'detached') said = 'Detached ' + name + ' and moved it to ' + where + '.';
  else if (owner) said = 'Moved ' + name + ' to ' + where + '.';
  else said = capital(name) + ' is on its own now, in no project or task.';
  if (MOVED.note) MOVED.note.remove();
  var act = movedAction(kind, id, owner);
  // It leaves the stack by itself, unlike a notice with a button on it anywhere
  // else: what it has to say is said in the reading, and the button is only a
  // way to look. The list that holds the thing now is the line under it.
  MOVED.note = notify(said, { tone: 'success', body: movedListed(kind, owner) || '',
                              action: act, for: MOVED_FOR });
  if (!same) movedRedraw(before, owner);
}

var MOVED_FOR = 15000;

/* The page on the canvas, read again when it is the page of the place the
   thing left or the place it went. A task's page counts and lists its chats
   and runs, and one still saying "1 chat" about a chat that has just left
   it is the same silence from the other side. The conversation stays where
   it is, as it does for a card filed into the task being read
   (`cardWasFiled`). */
function movedRedraw(before, owner) {
  if (!tasksViewing() || !CANVAS.at) return;
  var hit = [before, owner].some(function (o) {
    if (!o || (o.type !== 'task' && o.type !== 'project')) return false;
    var row = o.type === 'task' ? flatTaskById(o.id) : projectById(o.id);
    return !!row && !!row.folder
      && (row.folder === CANVAS.task || row.folder === CANVAS.step);
  });
  if (!hit) return;
  CANVAS.taskData = null;
  ADDR.chatNamed = true;
  CANVAS.redraw = true;
  try { canvasLoad(CANVAS.at); } finally { ADDR.chatNamed = false; CANVAS.redraw = false; }
}

/* The chats the task's page on the canvas lists, as this page last heard
   them: each one's id and name, for the task or step on the canvas and
   everything under it, which is what its Chats section walks
   (`objectindex._Under`). */
function canvasChatsSaid() {
  var place = CANVAS.step || CANVAS.task, out = [], i, c;
  if (!place || typeof CHATS === 'undefined' || !CHATS) return '';
  for (i = 0; i < CHATS.list.length; i++) {
    c = CHATS.list[i];
    if (c.task && (c.task === place || c.task.indexOf(place + '/') === 0)) {
      out.push(c.id + '\u0000' + c.title);
    }
  }
  return out.sort().join('\u0001');
}

/* The task's page read again when the chats it lists have changed: one
   filed under it, one gone from it, or one renamed - by the person, by
   Rouh when asked, or by the naming after a chat's first exchange. The
   page is drawn by the server when it loads and says nothing after that,
   so the Chats list beside it had the new name and the page under the
   task still had the old one. Only the task's own page, never a document
   or a page inside it, and only when a chat of its own changed, so a turn
   finishing anywhere else never reloads what is being read. */
function canvasChatsFollow() {
  if (!tasksViewing() || !CANVAS.at) return;
  var place = CANVAS.step || CANVAS.task;
  if (!place || CANVAS.at !== taskUrl(place)) return;
  // Loaded before the list came: what it lists is the server's answer of that moment.
  if (CANVAS.chats === null) { if (CHATS.listed) CANVAS.chats = canvasChatsSaid(); return; }
  if (canvasChatsSaid() === CANVAS.chats) return;
  CANVAS.taskData = null;
  ADDR.chatNamed = true;
  CANVAS.redraw = true;
  try { canvasLoad(CANVAS.at); } finally { ADDR.chatNamed = false; CANVAS.redraw = false; }
}

function capital(words) {
  return words.charAt(0).toUpperCase() + words.slice(1);
}

//: A task or a step, however deep, by its id.
function flatTaskById(id) {
  var rows = flatTasks(), i;
  for (i = 0; i < rows.length; i++) if (rows[i].id === id) return rows[i];
  return null;
}

//: What was moved, as the sentence names it: its type and its own name.
function movedName(kind, id) {
  var found = null;
  if (kind === 'chat') found = chatById(id);
  else if (kind === 'run') found = taskRecs[id] || null;
  else if (kind === 'task') found = flatTaskById(id);
  else if (kind === 'project') found = projectById(id);
  var title = found ? (found.title || found.name || '') : '';
  var word = OBJ_WORDS[kind] || kind;
  return title ? 'the ' + word + ' \u201c' + title + '\u201d' : 'the ' + word;
}

//: Where it is now, in the words the rest of the page uses for that place:
//: the head of a chat under task 30 reads "Task 30 · Jarvis".
function placeWords(owner) {
  if (owner.type === 'task') {
    var t = flatTaskById(owner.id);
    if (t && isStep(t) && t.step) return 'step ' + t.step + ' \u00b7 ' + (t.title || owner.label);
    return taskWords(owner, false);
  }
  if (owner.type === 'project') {
    var pr = projectById(owner.id);
    return 'the project ' + (pr ? (pr.folder ? pr.name : projectParts(pr).name) : owner.label);
  }
  return 'the ' + (OBJ_WORDS[owner.type] || owner.type) + ' \u201c' + owner.label + '\u201d';
}

//: Where a chat is found now, which is the half of the answer the person
//: was missing. It said which list of the sidebar held it until 30
//: September 2026, when the list of chats went: Search lists the latest
//: chats before anything is typed (`findRecent`).
function movedListed(kind, owner) {
  if (kind !== 'chat') return '';
  if (owner && owner.type === 'chat') return '';
  if (owner && owner.type === 'task') return 'It is on the task\u2019s page, and in Search.';
  return 'Search finds it, among the latest chats.';
}

/* The press that shows it, named for what it opens. A place with a page of
   its own - a task, a step, a project of the workspace - opens that page,
   which lists everything in it. A place with none shows the thing itself. */
function movedAction(kind, id, owner) {
  if (owner && owner.type === 'task') {
    var t = flatTaskById(owner.id);
    if (t && t.folder) {
      return {
        label: 'Open ' + (isStep(t) && t.step ? 'step ' + t.step
          : t.number != null ? 'task ' + t.number : 'the task'),
        run: function () { movedOpen(t.folder, kind, id); }
      };
    }
    return { label: 'Show the task',
             run: function () { openUnder('task', owner.id, owner.label); } };
  }
  if (owner && owner.type === 'project') {
    var pr = projectById(owner.id);
    if (pr && pr.folder) {
      return { label: 'Open ' + pr.name, run: function () { movedOpen(pr.folder, kind, id); } };
    }
  }
  if (owner && owner.type === 'chat') {
    return { label: 'Open the chat', run: function () { openChat(owner.id); } };
  }
  if (['chat', 'task', 'run'].indexOf(kind) < 0) return null;
  return { label: 'Show it', run: function () { movedReveal(kind, id); } };
}

// The new place's own page on the canvas, beside the conversation the
// person is in: seeing where a thing went is not leaving the chat for it.
function movedOpen(folder, kind, id) {
  ADDR.chatNamed = true;
  try { canvasTask(folder); } finally { ADDR.chatNamed = false; }
  chatIsWanted();
  if (narrow()) setPane('canvas');
}

/* The thing itself, where it is read. A chat and a task were lit on their
   lists in the sidebar until 30 September 2026, when those lists went: a
   chat opens now, and a task opens its page. A run is lit on the runs
   page, inside its project when it is in one. */
function movedReveal(kind, id) {
  var q = function (v) { return String(v).replace(/["\\]/g, '\\$&'); };
  if (kind === 'chat') { openChat(id); return; }
  if (kind === 'task') {
    var t = flatTaskById(id);
    if (t && t.folder) { canvasTask(t.folder); chatIsWanted(); }
    else openUnder('task', id, (t && t.title) || '');
    return;
  }
  if (kind !== 'run') return;
  var rec = taskRecs[id];
  if (rec && rec.project_id) POPEN['runs:' + rec.project_id] = true;
  runsOpen(runKind(rec));
  railLight('.task[data-id="' + q(id) + '"]');
}

// One card lit on the runs page, the copy of it that is on the screen: a
// pinned run is drawn in Pinned and not again below it, but a run in a
// project can be in the project and in Pinned at once.
function railLight(sel) {
  var all = document.querySelectorAll('#runsView ' + sel), row = null, i, box;
  for (i = 0; i < all.length && !row; i++) {
    box = all[i].getBoundingClientRect();
    if (box.width || box.height) row = all[i];
  }
  if (!row) return;
  row.scrollIntoView({ block: 'nearest' });
  row.classList.remove('rail-lit');
  void /** @type {HTMLElement} */ (row).offsetWidth;
  row.classList.add('rail-lit');
  window.setTimeout(function () { row.classList.remove('rail-lit'); }, 1800);
}

// --- what is under one thing ---

var UNDER = { kind: '', id: '', what: '' };

function openUnder(kind, id, what) {
  UNDER = { kind: kind, id: id, what: what || id };
  $('underHead').textContent = 'Under ' + UNDER.what;
  $('underBody').textContent = '';
  $('underBody').appendChild(el('p', 'hint', 'Reading…'));
  $('underOwner').textContent = 'Belongs to: ' + ownerWords(ownerNow(kind, id));
  $('underDialog').showModal();
  send({ type: 'list_under', kind: kind, id: id });
}

/** @param {import('./protocol').FromServer<'under'>} m */
function drawUnder(m) {
  if (!m || m.id !== UNDER.id) return;
  var host = $('underBody');
  host.textContent = '';
  var kids = (m.under && m.under.children) || [];
  if (!kids.length) {
    host.appendChild(el('p', 'hint', 'Nothing belongs to it yet. Attach a run, a '
      + 'chat or an artifact to it and it appears here, with everything of its own.'));
    return;
  }
  kids.forEach(function (child) { host.appendChild(underRow(child, 0)); });
  var cost = Number((m.under && m.under.cost_usd) || 0);
  if (cost > 0) {
    host.appendChild(el('p', 'under-cost', 'Cost of everything under it: $'
      + cost.toFixed(2)));
  }
}

function underRow(child, depth) {
  var box = el('div', 'under-row d' + Math.min(depth, 3));
  var head = el('div', 'under-head');
  head.appendChild(el('span', 'under-kind', child.type));
  head.appendChild(el('span', 'under-name', child.label || child.id));
  if (child.state) head.appendChild(el('span', 'chip', child.state));
  if (child.kind) head.appendChild(el('span', 'chip', child.kind));
  box.appendChild(head);
  var bits = [];
  if (child.workspace) bits.push(child.workspace);
  if (child.policy) bits.push(child.policy);
  if (child.branch) bits.push(child.branch);
  if (typeof child.cost_usd === 'number' && child.cost_usd > 0) {
    bits.push('$' + child.cost_usd.toFixed(2));
  }
  if (bits.length) box.appendChild(el('div', 'under-meta', bits.join(' · ')));
  // A diff is the one artifact every run has, and it is what a person opens
  // this to read: what the run actually did to the files.
  if (child.body) box.appendChild(el('pre', 'under-diff', child.body));
  (child.children || []).forEach(function (kid) {
    box.appendChild(underRow(kid, depth + 1));
  });
  return box;
}

/* ---------- deleting, which is one dialog and one message ----------

   The person asked for this on 22 September 2026: "We should be able to
   delete items of all types - chats, runs, tasks, projects. Delete cascades
   if there are relationships."

   So there is one `askDelete` here and every cross on this page calls it,
   rather than a confirm written out again beside each list with a different
   amount remembered in it. Two messages, always in this order:

     delete_plan     what would go, counted by the server off the very links
                     the delete walks. Nothing is written.
     delete_object   it goes.

   The Delete button stays disabled until that first answer is on the screen,
   because agreeing to a sentence that has not arrived yet is not agreeing to
   anything. A refusal - General, which is never deleted - arrives the same
   way and leaves the button disabled with the reason on it.

   A dialog rather than window.confirm, for two reasons that are both about
   the phone: a confirm cannot say the thing's name in the page's own type
   over three lines of what else goes with it, and on iOS it is a system
   sheet that arrives with no relation to what was pressed. */

var DEL = { kind: '', id: '', label: '', folder: '', page: '' };

//: `folder` names a task by where it is, for a task's own page, which
//: knows that and not its id; the plan says the id back (`delPlanned`).
//: `page` is the task's page on the canvas it was asked from, for a chat or
//: a subtask on it, which is loaded again once it has gone (`canvasLeftBehind`).
function askDelete(kind, id, label, folder, page) {
  if (!kind || !(id || folder)) return;
  DEL = { kind: kind, id: id || '', label: String(label || id || folder),
          folder: id ? '' : String(folder || ''), page: String(page || '') };
  $('delHead').textContent = 'Delete this ' + (OBJ_WORDS[kind] || kind) + '?';
  $('delWhat').textContent = '\u201c' + DEL.label + '\u201d';
  $('delAlso').textContent = 'Working out what else goes with it\u2026';
  $('delError').hidden = true;
  $('delUndone').hidden = false;
  $('delGo').disabled = true;
  if (!$('delDialog').open) $('delDialog').showModal();
  /** @type {import('./protocol').ToServer<'delete_plan'>} */
  var ask = { type: 'delete_plan', kind: kind, id: DEL.id };
  if (DEL.folder) ask.folder = DEL.folder;
  if (!send(ask)) {
    delRefused('Rouh is not connected, so nothing can be deleted yet.');
  }
}

function delRefused(why) {
  $('delAlso').textContent = '';
  $('delUndone').hidden = true;
  $('delError').textContent = why;
  $('delError').hidden = false;
  $('delGo').disabled = true;
}

// What the server says would go. Ignored unless it is about the thing this
// dialog is open on: two crosses pressed quickly is two plans coming back,
// and the second one must not describe the first one's subject.
/** @param {import('./protocol').FromServer<'delete_plan'>} m */
function delPlanned(m) {
  if (!m || m.kind !== DEL.kind) return;
  if (DEL.folder ? m.folder !== DEL.folder : m.id !== DEL.id) return;
  if (!$('delDialog').open) return;
  if (m.ok === false || !m.id) { delRefused(m.why || 'That cannot be deleted.'); return; }
  DEL.id = m.id;
  // What the server calls it: a task inside a task is a subtask.
  if (m.what) $('delHead').textContent = 'Delete this ' + m.what + '?';
  if (m.label) {
    DEL.label = m.label;
    $('delWhat').textContent = '\u201c' + m.label + '\u201d';
  }
  $('delAlso').textContent = m.sentence || '';
  $('delError').hidden = true;
  $('delUndone').hidden = false;
  $('delGo').disabled = false;
  $('delGo').focus();
}

/* ---------- Move, from a task's or a subtask's three dots ----------

   Petar, 29 September 2026 (fr_2c31bc88941c): "We want to be able to move
   any subtask or task to any other task or project. If moved to project it
   becomes top level task with the next available number".

   The places come from the server (`rouh/moving.py`), every project and
   task under its column in the order they nest, each with why it cannot be
   picked when it cannot: the one being moved, what is inside it, and where
   it is now. Typing narrows the list, and then each line says where it is,
   since the indenting no longer can. Picking one says what the moved one
   will become there, and Move sends it; the page is then loaded again at
   the folder it moved to, under its new number. */
var MOVE = { folder: '', places: [], pick: '', what: 'task', gen: 0 };

//: `name` is what it is called, for a subtask moved from its task's page,
//: whose title on the canvas is its task's.
function moveOpen(folder, name) {
  var gen = ++MOVE.gen;
  MOVE.folder = folder;
  MOVE.places = [];
  MOVE.pick = '';
  MOVE.what = /^\d+\./.test(folder.split('/').pop()) ? 'task' : 'subtask';
  $('moveHead').textContent = 'Move this ' + MOVE.what;
  $('moveWhat').textContent = '“' + (name || CANVAS.title || folder.split('/').pop()) + '”';
  $('moveFind').value = '';
  $('moveList').textContent = '';
  moveSay('Reading the projects and tasks…');
  $('moveError').hidden = true;
  $('moveGo').disabled = true;
  if (!$('moveDialog').open) $('moveDialog').showModal();
  $('moveFind').focus();
  fetch('/api/workspace/destinations?folder=' + encodeURIComponent(folder),
        { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      return r.json().catch(function () { return { ok: false }; });
    })
    .then(function (got) {
      if (!got || gen !== MOVE.gen) return;
      if (!got.ok) { moveRefused(got.why || got.error || 'It cannot be moved from here.'); return; }
      MOVE.places = got.places || [];
      MOVE.what = got.what || MOVE.what;
      $('moveHead').textContent = 'Move this ' + MOVE.what;
      if (got.title) {
        $('moveWhat').textContent = '“' + (got.label ? got.label + ' · ' : '')
          + got.title + '”';
      }
      moveSay('Pick a project or a task.');
      moveDraw();
    })
    .catch(function () {
      if (gen === MOVE.gen) moveRefused('Rouh could not be reached. Try again in a moment.');
    });
}

function moveSay(words) { $('moveWill').textContent = words; }

function moveRefused(why) {
  $('moveError').textContent = why;
  $('moveError').hidden = false;
  $('moveGo').disabled = !MOVE.pick;
}

function moveDraw() {
  var host = $('moveList');
  var q = $('moveFind').value.replace(/\s+/g, ' ').trim().toLowerCase();
  host.textContent = '';
  var shown = 0;
  MOVE.places.forEach(function (p) {
    if (p.kind === 'column') {
      if (q) return;
      var head = document.createElement('div');
      head.className = 'move-col';
      head.textContent = p.title;
      host.appendChild(head);
      return;
    }
    var words = ((p.label || '') + ' ' + p.title + ' ' + (p.within || '')).toLowerCase();
    if (q && words.indexOf(q) === -1) return;
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'move-row';
    row.setAttribute('role', 'option');
    row.setAttribute('data-kind', p.kind);
    row.setAttribute('data-key', p.key);
    row.setAttribute('aria-selected', p.key === MOVE.pick ? 'true' : 'false');
    row.style.setProperty('--depth', String(q ? 0 : Math.max(0, (p.depth || 1) - 1)));
    if (p.blocked) {
      row.setAttribute('aria-disabled', 'true');
      row.title = p.blocked;
    }
    if (p.label) {
      var num = document.createElement('span');
      num.className = 'num';
      num.textContent = p.label;
      row.appendChild(num);
    }
    var text = document.createElement('span');
    text.className = 'text';
    var name = document.createElement('span');
    name.className = 'name';
    name.textContent = p.title;
    text.appendChild(name);
    if (q && p.within) {
      var inside = document.createElement('span');
      inside.className = 'in';
      inside.textContent = p.within;
      text.appendChild(inside);
    }
    row.appendChild(text);
    if (p.blocked) {
      var why = document.createElement('span');
      why.className = 'why';
      why.textContent = p.blocked;
      row.appendChild(why);
    }
    row.addEventListener('click', function () { movePick(p.key); });
    row.addEventListener('dblclick', function () { if (!p.blocked) moveGo(); });
    host.appendChild(row);
    shown++;
  });
  // A pick the words have hidden is dropped, so Move never sends one the
  // person can no longer see.
  if (MOVE.pick && !host.querySelector('.move-row[aria-selected="true"]')) {
    MOVE.pick = '';
    $('moveGo').disabled = true;
    moveSay('Pick a project or a task.');
  }
  if (!shown) {
    var none = document.createElement('p');
    none.className = 'empty';
    none.textContent = q ? 'Nothing is called that.' : 'There is nowhere to move it.';
    host.appendChild(none);
  }
}

function movePlace(key) {
  for (var i = 0; i < MOVE.places.length; i++) {
    if (MOVE.places[i].key === key) return MOVE.places[i];
  }
  return null;
}

function movePick(key) {
  var p = movePlace(key);
  if (!p || p.blocked || p.kind === 'column') return;
  MOVE.pick = key;
  $('moveList').querySelectorAll('.move-row').forEach(function (row) {
    var on = row.getAttribute('data-key') === key;
    row.setAttribute('aria-selected', on ? 'true' : 'false');
    if (on) row.scrollIntoView({ block: 'nearest' });
  });
  $('moveError').hidden = true;
  $('moveGo').disabled = false;
  moveSay(p.kind === 'project'
    ? (MOVE.what === 'subtask'
      ? 'It becomes a task in ' + p.title + ', with the next free task number.'
      : 'It goes into ' + p.title + ', and keeps its number.')
    : 'It becomes the next subtask of ' + (p.label ? p.label + ' · ' : '') + p.title
      + ', numbered to fit there.');
}

// Up and down from the box walk the places that can be picked.
function moveStep(by) {
  var rows = Array.prototype.filter.call($('moveList').querySelectorAll('.move-row'),
    function (row) { return row.getAttribute('aria-disabled') !== 'true'; });
  if (!rows.length) return;
  var at = -1;
  rows.forEach(function (row, i) { if (row.getAttribute('data-key') === MOVE.pick) at = i; });
  var next = at === -1 ? (by > 0 ? 0 : rows.length - 1)
    : Math.max(0, Math.min(rows.length - 1, at + by));
  movePick(rows[next].getAttribute('data-key'));
}

function moveGo() {
  if (!MOVE.pick || $('moveGo').disabled) return;
  var gen = MOVE.gen, folder = MOVE.folder;
  $('moveGo').disabled = true;
  moveSay('Moving it…');
  moveSend(folder, MOVE.pick).then(function (out) {
    if (gen !== MOVE.gen || out.ok) return;
    moveRefused(out.error);
    movePick(MOVE.pick);
  });
}

/* What a new task is called, asked before "Move to new task" makes it, from
   any of its three places: the subtask's own page, its line on its task's
   page, and its line in the task browser (`fileRelay`). Petar, 22 October
   2026: "when I press "move to new task" it seems that it creates a task with
   the same name. instead I should be asked what the name of the task." It
   starts with the subtask's name, selected, so typing replaces it. */
var NAMING = { done: null };

/** @param {string} what the subtask, as its line names it
 * @param {string} title its name, which the box starts with
 * @returns {Promise<string|null>} the name, or null when it was cancelled */
function askTaskName(what, title) {
  if (NAMING.done) NAMING.done(null);
  return new Promise(function (ok) {
    NAMING.done = function (name) { NAMING.done = null; ok(name); };
    $('nameWhat').textContent = what ? '“' + what + '” becomes its first subtask.' : '';
    $('nameField').value = title || '';
    $('nameGo').disabled = !String(title || '').trim();
    if (!$('nameDialog').open) $('nameDialog').showModal();
    $('nameField').focus();
    $('nameField').select();
  });
}

$('nameField').addEventListener('input', function () {
  $('nameGo').disabled = !$('nameField').value.trim();
});
$('nameForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var name = $('nameField').value.replace(/\s+/g, ' ').trim();
  if (!name) return;
  var done = NAMING.done;
  $('nameDialog').close();
  if (done) done(name);
});
$('nameCancel').addEventListener('click', function () { $('nameDialog').close(); });
$('nameDialog').addEventListener('close', function () { if (NAMING.done) NAMING.done(null); });

/** The task or subtask at `folder` moved to `where` - a place from the picker,
 * or `+task` (Promote to task) or `+new` (Move to new task) from a subtask's
 * dots (`rouh/moving.py`) - and, once it has, its new place on the canvas.
 * `go` shows the new place even when it was moved from its task's page, and
 * `name` is what a new task is called.
 * Answers {ok} or {ok: false, error}, and never fails.
 * @param {string} folder @param {string} where @param {boolean} [go] @param {string} [name]
 * @returns {Promise<{ok: boolean, error?: string}>} */
function moveSend(folder, where, go, name) {
  return clockPost(FILING, { action: 'relocate', folder: folder, where: where, name: name || '' })
    .then(function (answer) {
      var out = answer.out || {};
      if (!answer.ok || !out.ok) return { ok: false, error: out.error || 'It could not be moved.' };
      if ($('moveDialog').open) $('moveDialog').close();
      // A subtask moved to a new task: the new task's page, which it is the
      // first subtask of, so both new numbers are in sight.
      var to = out.task || out.rel;
      // Its page, where it is now: the breadcrumb and its number say where.
      if (to && tasksViewing() && (go || taskPageFolder() === folder)) canvasLoad(taskUrl(to));
      // A subtask moved from its task's page: that page again, without it.
      else if (tasksViewing() && folder.indexOf(taskPageFolder() + '/') === 0 && tasksFrame()) {
        frameLoad(tasksFrame(), CANVAS.at);
      }
      return { ok: true };
    }).catch(function () {
      return { ok: false, error: 'Rouh could not be reached. Try again in a moment.' };
    });
}

$('moveFind').addEventListener('input', moveDraw);
$('moveFind').addEventListener('keydown', function (e) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    moveStep(e.key === 'ArrowDown' ? 1 : -1);
  } else if (e.key === 'Enter' && !e.isComposing) {
    e.preventDefault();
    moveGo();
  }
});
$('moveCancel').addEventListener('click', function () { $('moveDialog').close(); });
$('moveGo').addEventListener('click', moveGo);
$('moveDialog').addEventListener('close', function () { MOVE.gen++; });

$('delCancel').addEventListener('click', function () { $('delDialog').close(); });
$('delGo').addEventListener('click', function () {
  if ($('delGo').disabled || !DEL.id) return;
  $('delGo').disabled = true;
  if (!send({ type: 'delete_object', kind: DEL.kind, id: DEL.id })) {
    delRefused('Rouh is not connected, so nothing can be deleted yet.');
    return;
  }
  $('delDialog').close();
});

/* The cross itself, made here so it is the same control everywhere: the
   chat list, and the projects dashboard.

   The type and then the name go into the label a screen reader reads, so
   "Delete the chat Groceries" is what is announced rather than a bare cross,
   and the click is stopped from carrying on into the row behind it - every
   one of these sits inside something that opens when it is pressed. */
function deleteCross(kind, id, label) {
  var b = el('button', 'del-x', '\u00d7');
  b.type = 'button';
  b.title = 'Delete ' + (OBJ_WORDS[kind] || kind) + ' \u201c' + label + '\u201d';
  b.setAttribute('aria-label', 'Delete the ' + (OBJ_WORDS[kind] || kind)
    + ' ' + label);
  b.setAttribute('data-del', kind);
  b.addEventListener('click', function (e) {
    if (e.stopPropagation) e.stopPropagation();
    askDelete(kind, id, label);
  });
  return b;
}

/* ---------- the row menu ----------

   Petar, 22 September 2026: "Everything that is pinned gets a three-dot menu
   with three options: un-pin, edit, delete."

   So every row of the three lists carries three dots and the dots open one
   menu. It is on every row and not only on the pinned ones, because the
   first item is also the only way something becomes pinned: it reads Pin on
   a row that is not and Un-pin on one that is, and there is nowhere else in
   this column to say it from.

   The cross that used to sit at the end of each of these rows has gone into
   the menu's last item. One control per row rather than one control and two
   things with nowhere to press them.

   Later the same day, with three screenshots of the menu he wanted:
   "rename should rename it inline ... change project should list projects
   sidewise ... we don't have groups yet ignore that one ... those will
   replace EDIT."

   So Edit is gone, and with it the box the browser popped up in the middle
   of the screen to ask for a name. In its place:

     Rename              the row's own name becomes a field with the name in
                         it, selected, where the name already is. Enter or
                         clicking away keeps it, Escape puts it back.
     Change project      the projects, beside the menu, one press each. The
                         one it is in now has a tick on it.
     Remove from project out of the project it is in, drawn only when it is
                         in one.

   Groups are not a thing here yet, so the item the screenshots have for
   them is not built and there is no room left for it either.

   One menu, moved to whichever row asked for it, the way the search results'
   own menu works: thirty rows with a menu each is thirty menus to keep in
   step. It is fixed to the window because the lists it is opened over
   scroll, and it lives outside every panel in the markup so that a column
   with its own overflow cannot clip it.

   All of it goes down paths this page already had. Pin and Rename are
   `pin_object` and `rename_object` (PROTOCOL.md), which are one message for
   all five types and which send a chat's down the one writer a chat has.
   The two project items are `attach`, with an owner and without one, which
   is the one message that changes who owns what. Delete is `askDelete`, the
   single delete dialog every cross on this page has always opened, which
   counts what else would go before its button will do anything.

   The two project items are drawn for a **chat** and for nothing else.
   Which project a chat is in is one link and nothing more, so `attach` is
   the whole of moving it; a task or a project of the workspace is a folder
   in git, moving it moves the folder with `git mv`, and that is the task
   browser's own filing. One menu offering both would be one word meaning
   two different writes.

   "What is under it" is on a row that asks for it (`under` on the spec)
   and on no other. It is the way into the panel that says what
   one thing owns and where it belongs, which a task's row carried as the
   owner's name written at the end of it until 22 September 2026. The name
   came off the line; the way in had to go somewhere, and the menu is where
   everything else a row can do already is.

   `spec` is the row: what kind of thing it is, its id, what to call it out
   loud, the name to put in the rename field, whether it is pinned this
   instant, and whether it offers what is under it. It is closed over when
   the row is drawn, and every list here is redrawn from the server's own
   message whenever any of that changes, so a stale spec cannot outlive the
   row it came from. */

var ROWMENU = { spec: null, dots: null };

/* The dots themselves, made here so they are one control everywhere.

   The click is stopped from carrying on into the row behind it: every one
   of these sits inside something that opens when it is pressed. Pressing
   the same dots again closes the menu, which is what a person expects of a
   button that opened one. */
function rowDots(spec) {
  var b = el('button', 'row-dots', '\u22ef');
  b.type = 'button';
  b.setAttribute('aria-haspopup', 'menu');
  b.setAttribute('aria-expanded', 'false');
  b.setAttribute('aria-controls', 'rowMenu');
  b.setAttribute('data-row', spec.kind + ':' + spec.id);
  b.title = 'What to do with the ' + (OBJ_WORDS[spec.kind] || spec.kind)
    + ' ' + spec.label;
  b.setAttribute('aria-label', b.title);
  b.addEventListener('click', function (e) {
    if (e.stopPropagation) e.stopPropagation();
    if (ROWMENU.dots === b) { rowMenuShow(false); return; }
    rowMenuShow(true, spec, b);
    // Opened from the keyboard, the keyboard goes into it, the way it does
    // on every menu here (`menu.js`). A press with the pointer leaves the
    // focus where it was: moving it would scroll a half-hidden row.
    if (!e.detail) RouhMenu.first($('rowMenu'));
  });
  return b;
}

/* The dots on one object's row, found again after the list was redrawn.

   Every list here is rebuilt whole whenever the server says anything about
   it, so the node the menu was opened against is thrown away and an
   identical one is drawn in its place. `data-row` is how the new one is
   found, which is what lets the menu and the rename field stay with their
   row across a turn finishing in some other thread.

   Whichever copy of the row is actually on the screen, and there can be
   two: the rail draws one list at a time and hides the others with CSS, so
   a task has a row on the chats list and a row on the tasks list and one of
   them is a rectangle of no size. Placing anything against that one would
   put it in the corner of the window. */
function rowDotsFor(kind, id) {
  var all = document.querySelectorAll('[data-row="'
    + String(kind + ':' + id).replace(/["\\]/g, '\\$&') + '"]');
  var i, box;
  for (i = 0; i < all.length; i++) {
    box = all[i].getBoundingClientRect();
    if (box.width || box.height) return all[i];
  }
  return null;
}

/* The name on a row, whichever of the lists the row is in.

   The dots and the name are always inside one parent - `.sb-row` on a
   project, `.task-top` on a run's card - so this is the
   one place that has to know what a name is called in each of them. */
function rowNameNode(dots) {
  if (!dots || !dots.parentNode || !dots.parentNode.querySelector) return null;
  return dots.parentNode.querySelector('.sb-row-name, .task-title');
}

/* Open it against a row, or put it away.

   Placed under the dots that asked for it and nudged back onto the screen
   when there is not room below or to the right: the sidebar is at the left
   edge of a window that can be 320 px wide, and a menu half off the side of
   it is a menu with an item nobody can press. */
function rowMenuShow(on, spec, dots) {
  var menu = $('rowMenu');
  if (!menu) return;
  if (ROWMENU.dots) ROWMENU.dots.setAttribute('aria-expanded', 'false');
  if (!on || !spec || !dots) {
    rowPickShow(false);
    menu.hidden = true;
    ROWMENU.spec = null;
    ROWMENU.dots = null;
    return;
  }
  rowPickShow(false);
  ROWMENU.spec = spec;
  ROWMENU.dots = dots;
  dots.setAttribute('aria-expanded', 'true');
  RouhMenu.label($('rowMenuPin'), spec.pinned ? 'Un-pin' : 'Pin');
  RouhMenu.icon($('rowMenuPin'), spec.pinned ? 'unpin' : 'pin');
  $('rowMenuUnder').hidden = !spec.under;
  // Every card it drew, side by side on the canvas: a chat's, and only a
  // chat's (`drawnOpen`).
  $('rowMenuCards').hidden = spec.kind !== 'chat';
  // A chat is the one thing here that is filed into a project by a link, so
  // it is the one thing offered a project. And there is nothing to remove
  // from until it is in one.
  //
  // Unless it is filed under a task. Its project is then its task's, and
  // both items would be something else under that name: a project picked
  // here takes the chat out of the task, and "Remove from project" takes
  // the task away from it. The task is moved to move it.
  $('rowMenuProject').hidden = spec.kind !== 'chat' || !!spec.inTask;
  $('rowMenuUnproject').hidden = !rowProjectNow(spec);
  menu.hidden = false;
  rowMenuPlace();
}

//: Which project the row's object is in this instant, or '' for none. A
//: chat's is the project the rail files it under, which is the link walked
//: up: a chat under a task under Acme is in Acme.
function rowProjectNow(spec) {
  if (!spec || spec.kind !== 'chat' || !CHATS) return '';
  var chat = chatById(spec.id);
  if (!chat || chat.task || !chat.folder_id || !projectById(chat.folder_id)) return '';
  return chat.folder_id;
}

/* Whether a row is not on the screen any more, however it went.

   Scrolled out of the window, in either direction. Or the sidebar itself
   gone: on a narrow window it lies over the page and is put away when the
   window is made narrower still, and it goes by being made invisible rather
   than by being moved, so its rows keep a rectangle on the screen that
   nobody can see. `checkVisibility` is the one question that answers both,
   and it is asked only where it is offered. */
function rowOffScreen(node, box) {
  if (node && node.checkVisibility
      && !node.checkVisibility({ visibilityProperty: true, opacityProperty: true })) {
    return true;
  }
  return box.bottom < 0 || box.top > window.innerHeight
    || box.right < 0 || box.left > window.innerWidth;
}

/* Put it back against its own row, wherever that row is now.

   Called again on every scroll, on a resize and whenever a list is redrawn,
   so the menu follows the row it belongs to instead of floating over
   somebody else's. It has to: a button pressed while it is only half on
   screen is scrolled into view by the browser as it takes the focus, and
   that scroll arrives **after** the click that opened the menu. A menu that
   closed on a scroll closed itself the instant it opened, on every row near
   the bottom of a long list.

   A row that has scrolled right out of the window takes the menu with it,
   and so does one that is really gone - as against one that was thrown away
   and drawn again a millisecond later, which is what every one of these
   lists does whenever the server says anything at all. */
function rowMenuPlace() {
  var menu = $('rowMenu'), dots = ROWMENU.dots;
  if (!menu || !dots) return;
  if (!dots.isConnected) {
    dots = ROWMENU.spec ? rowDotsFor(ROWMENU.spec.kind, ROWMENU.spec.id) : null;
    if (!dots) { rowMenuShow(false); return; }
    dots.setAttribute('aria-expanded', 'true');
    ROWMENU.dots = dots;
  }
  var box = dots.getBoundingClientRect();
  if (rowOffScreen(dots, box)) { rowMenuShow(false); return; }
  RouhMenu.place(menu, dots, 'start');
  rowPickPlace();
}

/* ---------- the projects, beside the menu ----------

   "change project should list projects sidewise", with a screenshot of a
   list opening from the item rather than a dialog over the page. So the
   projects open beside the menu, the chat is filed by pressing one, and the
   menu goes away as it lands.

   Both kinds of project are on the list, in the order the rail draws them:
   the ones made here to hold chats, then the workspace's own folders. A
   chat can be filed into either - `chatHosts` in this file is drawn from
   exactly that - and leaving the workspace's off would leave half the
   answer off. The one the chat is in now carries a tick.

   It opens on a hover as well as a press, because that is what an arrow on
   a menu item means, and it stays open until something else is pressed:
   there is no timer anywhere in here, so the pointer can take whatever path
   it likes between the item and the list without the list disappearing on
   the way. */
function rowPickShow(on, focus) {
  var fly = $('rowProjects'), item = $('rowMenuProject');
  if (!fly || !item) return;
  if (!on || !ROWMENU.spec) {
    fly.hidden = true;
    item.setAttribute('aria-expanded', 'false');
    return;
  }
  $('rowProjectsFind').value = '';
  rowPickFill('');
  fly.hidden = false;
  item.setAttribute('aria-expanded', 'true');
  rowPickPlace();
  // Not on a hover: taking the keyboard away from somebody who is only
  // moving the pointer across a menu is rude, and they have not asked for
  // this list yet.
  if (focus) $('rowProjectsFind').focus();
}

function rowPickPlace() {
  var fly = $('rowProjects'), menu = $('rowMenu'), item = $('rowMenuProject');
  if (!fly || fly.hidden || !menu || !item) return;
  var m = menu.getBoundingClientRect(), it = item.getBoundingClientRect();
  var w = fly.offsetWidth, h = fly.offsetHeight;
  // Beside the menu, on whichever side there is room for it: the sidebar is
  // at the left edge of the window, and on a narrow one the menu itself is
  // most of the width.
  var left = m.right + 2;
  if (left + w > window.innerWidth - 8) left = m.left - w - 2;
  var top = Math.min(it.top - 6, window.innerHeight - h - 8);
  fly.style.left = Math.max(8, left) + 'px';
  fly.style.top = Math.max(8, top) + 'px';
}

function rowPickFill(filter) {
  var host = $('rowProjectsList'), spec = ROWMENU.spec;
  if (!host || !spec) return;
  host.textContent = '';
  var now = rowProjectNow(spec);
  var want = String(filter || '').trim().toLowerCase();
  var all = chatProjects().concat(wsProjects()), drawn = 0, i, parts, name;
  for (i = 0; i < all.length; i++) {
    parts = projectParts(all[i]);
    name = all[i].folder ? all[i].name : parts.name;
    if (want && name.toLowerCase().indexOf(want) < 0) continue;
    host.appendChild(rowPickRow(all[i], name, all[i].id === now));
    drawn++;
  }
  if (drawn) return;
  // The two ways there is nothing to show, and they are not the same thing.
  host.appendChild(el('p', 'empty', all.length
    ? 'No project of that name.'
    : 'No projects yet. New project, in Projects, makes one.'));
}

function rowPickRow(project, name, on) {
  var ws = !!project.folder;
  var b = el('button', 'row-pick');
  b.type = 'button';
  b.setAttribute('role', 'menuitemradio');
  b.setAttribute('aria-checked', on ? 'true' : 'false');
  b.appendChild(el('span', 'row-pick-emoji', ws ? '\uD83D\uDDC2'
    : projectParts(project).emoji));
  b.appendChild(el('span', 'row-pick-name', name));
  if (on) b.appendChild(el('span', 'row-pick-tick', '\u2713'));
  b.title = on ? 'It is in ' + name + ' already'
    : 'Put it in ' + name + (ws ? ' (' + project.folder + ')' : '');
  b.setAttribute('aria-label', b.title);
  b.addEventListener('click', function () {
    var spec = ROWMENU.spec;
    rowMenuShow(false);
    if (!spec || on) return;
    send({ type: 'attach', kind: spec.kind, id: spec.id,
           owner_kind: 'project', owner_id: project.id });
  });
  return b;
}

/* ---------- renaming a row where the row is ----------

   "rename should rename it inline", with a screenshot of the chat's own row
   in the list with its name selected in a field. So: one field, put exactly
   over the name, with the name in it. Enter keeps it, so does clicking
   away, and Escape puts the old one back.

   The field is fixed to the window and lives outside all three lists rather
   than being built into the row, because those lists are rebuilt whole
   every time the server says anything about them - a turn finishing in
   another thread, a title the model wrote landing, a run starting. An input
   inside one of those rows would be thrown away mid-word with whatever had
   been typed into it. This one is not in the row at all: it follows it. */

var RENAME = { kind: '', id: '', was: '' };

function renameStart(spec) {
  var box = $('rowRename');
  if (!box || !spec) return;
  RENAME = { kind: spec.kind, id: spec.id, was: spec.title || spec.label || '' };
  box.value = RENAME.was;
  box.hidden = false;
  // A row with no name this knows how to sit over is renamed the way every
  // rename here was until today, rather than being an item that does
  // nothing at all. There is no such row on the page as it stands - a chat,
  // a task, a project and a run each keep their name in one of the three
  // spans `rowNameNode` asks for - and this is for the row somebody adds
  // later without one.
  if (!renamePlace()) { renameStop(false); renameAsk(spec); return; }
  box.focus();
  // Selected rather than with the caret at the end, so the first thing
  // typed replaces the name, which is what the screenshot shows and what
  // renaming a thing usually means.
  box.select();
}

function renameAsk(spec) {
  var said = window.prompt('What should this be called?',
                           spec.title || spec.label || '');
  if (said === null || !said.trim()) return;
  send({ type: 'rename_object', kind: spec.kind, id: spec.id, title: said.trim() });
}

//: Over the name, and as wide as what is left of the row. False when there
//: is no row to be over any more, which is the caller's cue to stop.
function renamePlace() {
  var box = $('rowRename');
  if (!box || !RENAME.kind) return false;
  var dots = rowDotsFor(RENAME.kind, RENAME.id);
  var name = rowNameNode(dots);
  if (!name) return false;
  var at = name.getBoundingClientRect(), row = dots.getBoundingClientRect();
  if (!at.width && !at.height) return false;
  if (rowOffScreen(name, at)) return false;
  var left = Math.max(4, at.left - 4);
  var high = Math.max(22, at.height + 6);
  var wide = Math.max(90, Math.min(row.right - left, window.innerWidth - left - 4));
  var top = Math.max(2, Math.min(at.top - 3, window.innerHeight - high - 2));
  box.style.left = left + 'px';
  box.style.top = top + 'px';
  box.style.width = wide + 'px';
  box.style.height = high + 'px';
  return true;
}

/* Keep what was typed, or put the old name back.

   What is being renamed is forgotten **before** the field is hidden, so the
   blur that follows - and the blur a click somewhere else on the page fires
   - cannot come back through here and send the same rename twice.

   An empty name and the name it already had are both nothing to do rather
   than something to refuse: the server refuses an empty one in its own
   sentence, and there is no reason to make it say so about a field somebody
   cleared and clicked out of. */
function renameStop(commit) {
  var box = $('rowRename');
  if (!box || !RENAME.kind) return;
  var was = RENAME, said = box.value.trim();
  RENAME = { kind: '', id: '', was: '' };
  box.hidden = true;
  if (!commit || !said || said === was.was) return;
  send({ type: 'rename_object', kind: was.kind, id: was.id, title: said });
}

/* The sidebar has just been opened or put away, and the two things that
   hang over its rows have to go with it: a menu or a half-typed name
   floating over a column that is not there belongs to a row nobody can see.

   It is asked here rather than noticed afterwards because the sidebar fades
   out rather than moving, so at the moment the window is resized its rows
   are still exactly where they were and still say they are visible. A row
   outside the sidebar - there is none today, and there was none when this
   was written either - keeps whatever is over it. */
function rowsFollowSidebar(open, where) {
  if (open) return;
  where = where || '.sidebar';
  if (ROWMENU.dots && ROWMENU.dots.closest
      && ROWMENU.dots.closest(where)) rowMenuShow(false);
  if (!RENAME.kind) return;
  var dots = rowDotsFor(RENAME.kind, RENAME.id);
  // Keeping what was typed, which is what clicking away from it does, and
  // putting the sidebar away is clicking away from it.
  if (dots && dots.closest && dots.closest(where)) renameStop(true);
}

/* A list was drawn again, so whatever is hanging over one of its rows is put
   back against it. Without this the menu closes and the rename field is left
   over the wrong row every time a turn finishes anywhere on this machine. */
function rowsRedrawn() {
  // Both of those are declared below two of the three lists that call this,
  // and a page can be asked to draw a list before it gets there - the same
  // rule `renderThreads` keeps about `CHATS`.
  if (!ROWMENU || !RENAME) return;
  if (ROWMENU.spec) rowMenuPlace();
  // The row is gone for good - deleted, or filtered off the list. Keeping
  // what was typed is the same answer as clicking away from it.
  if (RENAME.kind && !renamePlace()) renameStop(true);
}

/* What each item does. A press that is refused comes back as
   `object_changed` or `attached` with the server's own sentence on it, which
   goes into a notice when nothing is open to put it in. */
function rowMenuAct(what) {
  var spec = ROWMENU.spec;
  if (!spec) return;
  // The one item that does not put the menu away, because what it does is
  // open a list beside it. A press opens it and never closes it: the
  // pointer that did the pressing has already opened it on the way in, and
  // a press that shut what hovering had just opened was one press doing
  // nothing at all. Escape and a press anywhere else put it away.
  if (what === 'project') {
    rowPickShow(true, true);
    return;
  }
  rowMenuShow(false);
  if (what === 'under') {
    openUnder(spec.kind, spec.id, spec.label);
    return;
  }
  if (what === 'cards') {
    drawnOpen(spec.id, spec.label);
    // Where the sidebar covers the canvas or floats over it, asking to see
    // the cards is also being done with the navigation, or they open under it.
    sidebarDone();
    return;
  }
  if (what === 'pin') {
    send({ type: 'pin_object', kind: spec.kind, id: spec.id, on: !spec.pinned });
    return;
  }
  if (what === 'rename') { renameStart(spec); return; }
  // No owner on it at all is how an owner is taken away (PROTOCOL.md), and
  // an orphan is a legal thing to be.
  if (what === 'unproject') {
    send({ type: 'attach', kind: spec.kind, id: spec.id });
    return;
  }
  if (what === 'delete') askDelete(spec.kind, spec.id, spec.label);
}

(function () {
  var menu = $('rowMenu'), fly = $('rowProjects'), box = $('rowRename');
  if (!menu || !fly || !box) return;
  menu.addEventListener('click', function (e) {
    var item = e.target.closest ? e.target.closest('[data-do]') : null;
    if (item) rowMenuAct(item.getAttribute('data-do'));
  });
  // The arrow keys walk it, as they walk every menu here, and Tab leaves it.
  menu.addEventListener('keydown', function (e) {
    if (RouhMenu.keys(menu, e)) return;
    if (e.key === 'Tab') rowMenuShow(false);
  });
  // An arrow on a menu item means it opens on a hover as well as a press.
  // Nothing closes it on a hover, so the pointer can go any way it likes
  // from the item to the list without the list going out from under it.
  menu.addEventListener('mouseover', function (e) {
    var item = e.target.closest ? e.target.closest('[data-do]') : null;
    if (item && item.getAttribute('data-do') === 'project' && fly.hidden) {
      rowPickShow(true, false);
    }
  });
  // Narrowing the list moves what is under the box, so the list is placed
  // again: it is anchored to the menu and its height has just changed.
  $('rowProjectsFind').addEventListener('input', function () {
    rowPickFill(this.value);
    rowPickPlace();
  });
  // Enter takes the first one that is still on the list, which is the whole
  // point of having typed into it.
  $('rowProjectsFind').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    if (e.preventDefault) e.preventDefault();
    var first = $('rowProjectsList').querySelector('.row-pick');
    if (first) first.click();
  });
  // The rename field keeps what was typed on Enter and on losing the focus,
  // and puts the old name back on Escape. The Escape is stopped here so it
  // is not also read as "close whatever is open on this page".
  box.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      if (e.preventDefault) e.preventDefault();
      renameStop(true);
    } else if (e.key === 'Escape') {
      if (e.preventDefault) e.preventDefault();
      if (e.stopPropagation) e.stopPropagation();
      renameStop(false);
    }
  });
  box.addEventListener('blur', function () { renameStop(true); });
  // Anywhere else on the page puts it away, and so does Escape. Caught
  // going down rather than coming up, so a press on a row underneath does
  // not both close the menu and open something.
  document.addEventListener('mousedown', function (e) {
    var t = /** @type {HTMLElement} */ (e.target);
    if (!t.closest) return;
    if (RENAME.kind && !t.closest('#rowRename')) renameStop(true);
    if (!ROWMENU.spec) return;
    if (t.closest('#rowMenu') || t.closest('#rowProjects')
        || t.closest('.row-dots')) return;
    rowMenuShow(false);
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !ROWMENU.spec) return;
    if (e.stopPropagation) e.stopPropagation();
    // The list of projects is over the menu, so Escape closes that first
    // and leaves the menu where it was: one press, one layer.
    if (!fly.hidden) {
      rowPickShow(false);
      $('rowMenuProject').focus();
      return;
    }
    // Back to the dots that opened it, when the keyboard was in it.
    var dots = ROWMENU.dots, inside = menu.contains(document.activeElement);
    rowMenuShow(false);
    if (inside && dots && dots.isConnected) dots.focus();
  }, true);
  // The lists underneath it scroll, and the window can be resized with it
  // open. Either way the row has moved, so what is over it moves with it
  // rather than floating over somebody else's row or closing itself.
  document.addEventListener('scroll', function () {
    if (ROWMENU.spec) rowMenuPlace();
    if (RENAME.kind && !renamePlace()) renameStop(true);
  }, true);
  window.addEventListener('resize', function () {
    if (ROWMENU.spec) rowMenuPlace();
    if (RENAME.kind && !renamePlace()) renameStop(true);
  });
}());

/* The mark on a row that is pinned, wherever the row is. Small, dim, and
   never instead of anything the row already says. */
function pinMark(what) {
  var mark = el('span', 'pin-mark', '\uD83D\uDCCC');
  mark.title = 'Pinned' + (what ? ' - ' + what : '');
  mark.setAttribute('aria-label', 'Pinned');
  return mark;
}

/* A list with what is pinned at the head of it, and each half left in the
   order it arrived in.

   That is the whole of what a pin does to a list, and the orders underneath
   it are deliberate and stay: the chats are by when the person last used
   one, the runs by when each of them started and never by what it is doing,
   the tasks by their number. A pin lifts the two or three rows somebody
   marked over the top of that and changes nothing else.

   `sort` has been stable in every browser this page runs in since 2019, so
   the half that is not pinned comes out in exactly the order it went in. */
function pinnedFirst(rows) {
  return (rows || []).slice().sort(function (a, b) {
    return (b && b.pinned ? 1 : 0) - (a && a.pinned ? 1 : 0);
  });
}

$('ownerCancel').addEventListener('click', function () { $('ownerDialog').close(); });
$('underClose').addEventListener('click', function () { $('underDialog').close(); });
$('underOwn').addEventListener('click', function () {
  $('underDialog').close();
  openOwner(UNDER.kind, UNDER.id, UNDER.what);
});
// The object's own view is where a person reads what belongs to it, so it is
// the one place where "and everything under it" is not a surprise. The
// panel closes on the way, because it is about to be about nothing.
$('underDelete').addEventListener('click', function () {
  $('underDialog').close();
  askDelete(UNDER.kind, UNDER.id, UNDER.what);
});
$('newTaskBtn').addEventListener('click', function () {
  var said = window.prompt('What is the task called?');
  if (said === null) return;
  if (!said.trim()) return;
  send({ type: 'new_task', title: said.trim() });
});
$('ownChatBtn').addEventListener('click', function () {
  var chat = CHATS && chatById(CHATS.active);
  chatMenuShow(false);
  if (!chat) return;
  // A fork is moved by being unlinked into the task picked for it: filed
  // anywhere while it still hung off another chat, it would be in two places
  // at once (Petar, 6 October 2026, fr_efa418fa7e82).
  if (chat.fork_of) { detachAsk(chat); return; }
  openOwner('chat', chat.id, chat.title || chat.id);
});

/* ---------- threads ----------

   A thread is the unit. It is a subject that stays open for months, it owns
   its messages and its cards, and a thread whose subject is a numbered task
   of the person's workspace IS that task: thread "19 Pricing" and
   work/acme/19.pricing are one object rather than two that can drift. So picking
   the thread is picking the task, and there is no "switch to the assistant"
   anywhere on this page, because there is nothing to switch to.

   A thread is a chat (see the chats section below). What makes it a task is
   one field, `task`, which the server keeps on the chat. General is the
   thread that is always there, so nobody is ever made to file something
   before they can say it.

   Clicking a thread that is a task loads that task in the canvas, which is
   what clicking it in the task browser does and what clicking it in the list
   of chats and tasks does. One behaviour, wherever it is clicked. */

/* `WS` is the workspace's own tasks, and this file is one scope, so the name
   is taken: a second `var WS` further down does not make a second variable,
   it makes the later assignment win. One did for a day, and `WS.tasks` was
   undefined from the moment the page loaded until the workspace list
   arrived, so `wsTask` - which every chat that belongs to a task goes
   through - threw on `WS.tasks.length` before that. The throw was inside
   `ws.onmessage`, in the middle of the `ready` handler, which is why it cost
   the whole handshake: no "Connected", no transcript, no cards and no task
   list, on 22 September 2026. */
var WS = { tasks: [] };

/* What the canvas is showing.

   `mode` is `now` - the bare canvas, live work, the orb large - or `tasks`,
   and there is no third. Inside `tasks`, `at` is the one address loaded in
   the frame, and `task` and `step` are where that address is in the
   workspace, read off the address itself. They are workspace paths, so the
   numbers the person says out loud are still the address of everything.

   `taskData` is the task's steps, for the breadcrumb; `title` is the loaded
   page's own title, read out of its markup as it arrived. `chats` is the
   chats a task's page lists as they were when it loaded
   (`canvasChatsFollow`). */
var CANVAS = { mode: 'now', at: '', task: '', step: '', redraw: false,
               taskData: null, stepData: null, title: '', chats: '' };

function applyWorkspace(list) {
  if (!Array.isArray(list)) return;
  WS.tasks = list;
  renderThreads();
}

// The workspace task at that address, or null. The list is asked for before
// it has arrived on every connect - `applyChats` draws the rail from the
// `ready` message a few lines before `applyWorkspace` fills this in - so a
// list that is not there yet is an ordinary state and answers "no task",
// never a throw. See the note on `WS` above for what one throw here costs.
function wsTask(rel) {
  var all = WS.tasks || [];
  for (var i = 0; i < all.length; i++) {
    if (all[i].rel === rel) return all[i];
  }
  return null;
}

/* Every chat, in the order a chat is looked for in: General first, because
 it is where anything with no home yet goes, then what the person pinned,
 then the rest by when each was last used. It drew the sidebar's list of
 chats until that list went on 30 September 2026; Search draws the loose
 ones from it now, before anything is typed (`findRecent`). */
function railChats() {
  var rows = [];
  if (!CHATS) return rows;
  // Every chat, however long ago anything was said in it. Nothing takes a
  // conversation out of this list on a clock any more: one is here until
  // the person deletes it. A draft is not in `CHATS.list` and so not here.
  for (var i = 0; i < CHATS.list.length; i++) rows.push(CHATS.list[i]);
  // `updated_at` is when the person last **used** this chat: said something
  // in it, or edited it - named it, filed it, pinned it, made it a task. Not
  // when they last opened it, which is the whole of what was asked for:
  // "the last time I used (not just opened) should be on top." The server
  // keeps that clock and sends the list in this order already; the sort is
  // here for the two things that come before it.
  //
  // General is held at the top whatever its clock says, then what the person
  // has pinned, then the rest by that clock. A pin is the one thing a person
  // may say about this order themselves, so it wins over the clock and loses
  // to the thread that is always there.
  rows.sort(function (a, b) {
    if (a.id === CHATS.general) return -1;
    if (b.id === CHATS.general) return 1;
    if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
    return (b.updated_at || 0) - (a.updated_at || 0);
  });
  return rows;
}

/* What a thread is called at the head of the conversation and in the
 * page's title.
 *
 * A task's own conversation is named by the task, not by whatever the chat
 * happened to be titled: the task is the object, and its name is what the
 * person says after the number. The number is not in the words: it is
 * beside them wherever it is drawn, and every task row in the rail read
 * "12 12 The rail" until 21 September 2026. The Chats list names every chat
 * by its own title instead (`railName`).
 */
function threadName(chat) {
  // The thread that is always there is called Rouh because of which
  // thread it is, not because of what its title says. Its title is its own
  // and the model still writes one from what is said in it, which is why the
  // row carries that underneath rather than instead. It was called General
  // until 30 September 2026, when Petar asked for it to be Rouh; the code
  // and the server still call its role General.
  if (chat.id === CHATS.general) return 'Rouh';
  // A task's own conversation is called what the task is called, because it
  // is the task. Another chat put under the task is not, and keeps its own
  // title: two chats both called "Jarvis" could not be told apart.
  if (chat.task && !addrIsTasksOwn(chat)) return chat.title || 'New thread';
  var task = chat.task ? wsTask(chat.task) : null;
  if (task) return task.name;
  // A subtask is on no list of tasks here, and says its own name on the row
  // that owns it (`owned_by`).
  if (chat.owned_by && chat.owned_by.type === 'task' && chat.owned_by.label) {
    return chat.owned_by.label;
  }
  if (chat.task) {
    var bare = chat.task.split('/').pop().replace(/^[\d-]+\./, '').replace(/[-_]/g, ' ');
    return bare.charAt(0).toUpperCase() + bare.slice(1);
  }
  return chat.title || 'New thread';
}

/* What a chat is called on the Chats list, which is its own name.

   The same as `threadName` for every loose chat. The one difference is a
   task's own conversation, which the head of the conversation calls by the
   task's name because it is the task: on the Chats list it is a chat among
   chats, and the name it was given - by the person, by the model when they
   asked, or by the naming after its first exchange - is the name they look
   for it by. "Renamed the chat and filed the chat under that task" was what
   Petar watched happen, and the list has to show him that chat. One nobody
   has named yet is still called by its task, which is a better name than
   New chat. */
function railName(chat) {
  if (chat.id !== CHATS.general && chat.task && chat.titled && chat.title) {
    return chat.title;
  }
  return threadName(chat);
}

/* The chats changed. The list of them in the sidebar went on 30 September
   2026, so what is drawn from them now is the projects on the runs page,
   which carry their chats' dots, the head of the conversation, and General's
   dot in the navigation.

   `CHATS` is declared a few hundred lines below this, and the page can be
   asked to draw before it gets there: coming home from Google lands on an
   address that opens Settings, and a closer that ran this far unguarded
   threw and left the page saying Offline. */
function renderThreads() {
  if (!CHATS) return;
  renderProjects();
  showCrumb();
  railPaint();
}

/* ---------- the projects, pinned above the chats they hold ----------

   A project is the thing that holds chats together, and that is the only
   word for it anywhere a person can read one: in this column, in the list of
   chats and tasks, in every tooltip. It was called a folder in half those
   places until 21 September 2026, which is two names for one thing and one
   of them had to go. The socket still says `folder` (PROTOCOL.md) - that is
   a wire, not an interface, and renaming it would move rows in a database
   for nothing.

   Its emoji is its own: a project somebody named with one in front keeps it
   and loses it from the words, so the column is a column of pictures to
   scan rather than a column of words to read, and a project named without
   one is given the plain mark so no row is indented past its neighbours. It
   is the same rule `rouh/chats.py` keeps for a chat's title, for the same
   reason.

   Pressing a project opens it where it stands: what it holds is drawn
   underneath it, indented, and pressing it again folds it away. It is this
   browser's choice and nothing is sent, because what a project holds is
   already known here.

   It narrowed the list below to its chats until 22 September 2026, and
   everything in every other project went off the screen while it did. What
   the person asked for instead, in these words: "Projects should appear in
   the chats section and in the runs section, each expandable with a chevron,
   so you can click a project and see the chats or runs that belong to it."
   So nothing is hidden to show something any more. */

//: Which projects are open, by the list they are open on: a project can be
//: open over its chats and shut over its runs, because they are two
//: questions. `<list>:<id>`, this browser's, and not remembered between
//: reloads: it is a glance, not a setting.
var POPEN = {};

function projectOpen(which, id) { return !!POPEN[which + ':' + id]; }

function projectToggle(which, id) {
  var key = which + ':' + id;
  if (POPEN[key]) delete POPEN[key]; else POPEN[key] = true;
}

function projectById(id) {
  if (!CHATS) return null;
  for (var i = 0; i < CHATS.folders.length; i++) {
    if (CHATS.folders[i].id === id) return CHATS.folders[i];
  }
  return null;
}

/* Two kinds of project come down this wire and `folder` is what tells them
   apart. One the person made in the rail to hold chats is a row and nothing
   else. One of the workspace - Work, Personal, Acme, Research - is a
   folder in the tree, and since the workspace became rows on 21 September
   2026 both arrive in the same list.

   They were drawn as one list for a day, which put ten workspace projects in
   the rail wearing the same folder picture as the person's own, each with a
   rename and a delete beside it and each narrowing the chat list to nothing,
   because no chat is ever in one. So: the person's own are the projects that
   hold chats, and the workspace's are listed under a line of their own and
   open the workspace instead. Nothing can be moved from one list to the
   other, here or on the server (`rouh/objecttree.py` refuses it). */
function chatProjects() {
  var out = [];
  if (!CHATS) return out;
  for (var i = 0; i < CHATS.folders.length; i++) {
    if (!CHATS.folders[i].folder) out.push(CHATS.folders[i]);
  }
  return out;
}

function wsProjects() {
  var out = [];
  if (!CHATS) return out;
  for (var i = 0; i < CHATS.folders.length; i++) {
    if (CHATS.folders[i].folder) out.push(CHATS.folders[i]);
  }
  return out;
}

// The runs one project holds, in the order the runs list draws them. Walked
// up on the server: a run under a task under Acme is in Acme and
// nobody filed it there (`owning.decorate`).
function runsIn(projectId) {
  var out = [], k, rec;
  for (k in taskRecs) {
    rec = taskRecs[k];
    if (rec.project_id !== projectId) continue;
    if (!SHOW_ARCHIVED && rec.archived) continue;
    // A project holds the runs of the tab that is showing, and is not drawn on
    // a tab where it holds none (`runHosts`).
    if (!runsInTab(rec)) continue;
    out.push(rec);
  }
  out.sort(byStart);
  return pinnedFirst(out);
}

// Every project that holds a run worth drawing. Empty ones are left off on
// both kinds here: a project with no run in it has nothing to say on a list
// of runs, and unlike the chats there is no New run that puts one in it.
function runHosts() {
  var all = chatProjects().concat(wsProjects()), out = [], i;
  for (i = 0; i < all.length; i++) {
    if (runsIn(all[i].id).length) out.push(all[i]);
  }
  return out;
}

// Where in Unicode an emoji is, near enough for a first character: the same
// blocks `rouh/chats.py` names, and letters, digits and punctuation are
// never one whatever block they fall in.
function startsWithEmoji(text) {
  var ch = (text || '').charAt(0);
  if (!ch || /[\w\s.,:;!?'"()\[\]{}<>\/\\|@#$%^&*+=~`-]/.test(ch)) return false;
  var at = text.codePointAt(0);
  return (at >= 0x1F000 && at <= 0x1FAFF) || (at >= 0x2600 && at <= 0x27BF)
    || (at >= 0x2190 && at <= 0x21FF) || (at >= 0x2B00 && at <= 0x2BFF)
    || (at >= 0x203C && at <= 0x3299) || at === 0xFE0F;
}

// A project's picture and its words, taken apart.
function projectParts(project) {
  var name = String(project.name || '').trim();
  if (!startsWithEmoji(name)) return { emoji: '\u{1F4C1}', name: name };
  var at = name.codePointAt(0);
  var wide = at > 0xFFFF ? 2 : 1;
  // A variation selector belongs to the character in front of it.
  if (name.charCodeAt(wide) === 0xFE0F) wide++;
  return { emoji: name.slice(0, wide), name: name.slice(wide).trim() || name };
}

/* The one group of projects left in the column, over the **runs**: every
   project that holds one, opening where it stands.

   There were three, one over each of the three lists the rail switches
   between. Petar, 22 September 2026: "remove the projects sections from
   chats and tasks." So on those two the projects reach him through the
   Pinned section instead, and only the runs keep a group of their own,
   because that is what he asked for in the same breath.

   A pinned project is not drawn here. It is in the Pinned section above,
   built by this very function's `projectRow` with the same chevron and the
   same runs under it, and one project on two rows of one column is one of
   them pressed to find out they are the same project. */
function renderProjects() {
  var runHost = $('sbRunProjectList'), runGroup = $('sbRunProjects'), i;
  if (runHost && runGroup && CHATS) {
    var running = runHosts().filter(function (pr) { return !pr.pinned; });
    runGroup.hidden = !running.length;
    runHost.textContent = '';
    for (i = 0; i < running.length; i++) {
      runHost.appendChild(projectRow(running[i]));
    }
  }
  renderPinned();
  if (projectsViewing()) renderProjectsView();
  rowsRedrawn();
}

/* Whether a project holds anything finished and unseen, however deep.
 *
 * Asked of `OBJ.projects` and not of the row being drawn, because the rail
 * draws its projects from the chats message (`CHATS.folders`) and the mark
 * is worked out where the tree is, on the server: a step three levels down
 * that nobody has opened lights the project it is in. The two lists are the
 * same projects under the same ids, so this is a lookup and not a second
 * copy of anything.
 */
function objProjectNew(id) {
  var rows = (OBJ && OBJ.projects) || [], i;
  for (i = 0; i < rows.length; i++) {
    if (rows[i].id === id) return !!rows[i].new;
  }
  return false;
}

/* Petar, 22 September 2026: "the folders which are actually projects should
   also have a dot if a task in them is activated as something that needs my
   attention." The top of the trail, on a project wherever it is drawn: in
   the Pinned section, and over the runs it holds. */
function projectNewDot(project, name) {
  if (!objProjectNew(project.id)) return null;
  return newDot({
    kind: 'project', row: project, deep: true,
    title: name + ' holds work that has finished since you last looked at'
      + ' it.\nOpen it to see which, or press this dot to mark everything'
      + ' in it seen.'
  });
}

/* A project says what is happening inside it, with the same two dots its
   threads carry.

   Pressing a project narrows the list below to its chats, so a thread in
   another project is not drawn at all - and a turn belongs to the thread it
   was asked in and goes on being answered there whatever the sidebar is
   filtered to. Without this, the person filters to one project, an answer
   lands in another, and there is nothing anywhere on the screen to say so.
   Being answered wins over something new, because it is the live one. */
function projectMark(project) {
  var mark = { answering: false, unread: false }, i, chat;
  if (!CHATS) return mark;
  for (i = 0; i < CHATS.list.length; i++) {
    chat = CHATS.list[i];
    if (chat.folder_id !== project.id) continue;
    if (threadAnswering(chat)) mark.answering = true;
    else if (threadUnread(chat)) mark.unread = true;
  }
  return mark;
}

//: The chevron on a project row: the one glyph that says this opens.
function chevron() {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'sb-chev');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2.2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M9 6l6 6-6 6');
  svg.appendChild(path);
  return svg;
}

/* One project on the runs page, and the runs it holds when it is open.

   What it draws inside is the very card the list below draws, `taskCard`,
   so a run inside a project opens, pins, archives and deletes exactly as
   one outside it does, and nothing about it is a second implementation. It
   showed a project's chats on the chats list as well until 30 September
   2026, when that list went. */
function projectRow(project) {
  var which = 'runs';
  var parts = projectParts(project);
  var ws = !!project.folder;
  var open = projectOpen(which, project.id);
  var held = runsIn(project.id);
  /* What it holds, less whatever is pinned: that is drawn in the Pinned
     section at the head of the column, and one card twice in one column -
     a few pixels apart when this project is pinned too - is what that
     section exists to stop. The count on the row is still `held`, because
     the project does hold it; only the drawing of it has moved. */
  var shown = held.filter(function (one) { return !one.pinned; });
  var mark = projectMark(project);
  var doing = mark.answering ? 'A thread in it is being answered now'
    : mark.unread ? 'Something new in one of its threads' : '';
  var word = held.length === 1 ? '1 run' : held.length + ' runs';

  var box = el('div', 'sb-project-box');
  var row = el('div', 'sb-row sb-pair sb-project' + (open ? ' open' : ''));
  row.setAttribute('data-project', project.id);
  row.setAttribute('data-rail-list', which);
  var pick = el('button', 'sb-pair-main');
  pick.type = 'button';
  pick.setAttribute('aria-expanded', open ? 'true' : 'false');
  pick.appendChild(chevron());
  pick.appendChild(el('span', 'sb-emoji', ws ? '\uD83D\uDDC2' : parts.emoji));
  pick.appendChild(el('span', 'sb-row-name', ws ? project.name : parts.name));
  if (doing) pick.appendChild(el('span', mark.answering ? 'thread-live' : 'thread-new'));
  if (project.pinned) pick.appendChild(pinMark('it is in the Pinned section'));
  pick.appendChild(el('span', 'sb-holds', String(held.length)));
  pick.title = (open ? 'Hide the ' : 'Show the ')
    + word + ' in ' + (ws ? project.name : parts.name)
    + (ws ? ' (' + project.folder + ')' : '')
    + (doing ? '. ' + doing + '.' : '');
  pick.setAttribute('aria-label', pick.title);
  pick.addEventListener('click', function () {
    projectToggle(which, project.id);
    renderTasks();
  });
  row.appendChild(pick);
  // And the dot that says something under it has finished and nobody has
  // opened it: the head of the trail that runs project, task, step.
  var fresh = projectNewDot(project, ws ? project.name : parts.name);
  if (fresh) row.appendChild(fresh);
  row.appendChild(projectDots(project, ws ? project.name : parts.name));
  box.appendChild(row);

  if (open) {
    var inside = el('div', 'sb-inside');
    if (!shown.length) {
      // Empty because there is nothing in it, or empty because all of it is
      // pinned: two different things, and a project that says "none yet"
      // over a run it holds is saying the wrong one.
      inside.appendChild(el('p', 'empty', held.length
        ? 'Its runs are pinned, above.' : 'No runs in this project yet.'));
    } else {
      shown.forEach(function (one) { inside.appendChild(taskCard(one)); });
    }
    // The way in to the project itself, for one of the workspace's: its
    // page is everything under it, which is more than a list of runs.
    if (ws) {
      // A link to the project's page, so it opens in a tab of its own too.
      var whole = linkTo(el('a', 'sb-row sb-inside-more'), function () {
        return addrPlaceLink(addrOf('project', project.folder));
      });
      whole.appendChild(el('span', 'sb-row-name', 'Open ' + project.name));
      whole.title = 'Open ' + project.name + ' in the canvas ('
        + project.folder + ')';
      whole.setAttribute('aria-label', whole.title);
      whole.addEventListener('click', function () {
        canvasTask(project.folder);
      });
      inside.appendChild(whole);
    }
    box.appendChild(inside);
  }
  return box;
}

// A project just opened from somewhere else in the column, brought into
// view: opening a row off the bottom of a scrolled list is a press with
// nothing on the screen to show for it.
function scrollProjectIntoView(id) {
  var row = document.querySelector('#runsView [data-project="'
    + String(id).replace(/"/g, '\\"') + '"]');
  if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
}

/* The three dots on a project, wherever the project is drawn: in the Pinned
   section when it is pinned, and over the runs it holds when it is not. One
   builder, so a project has the same menu in both places and the pin it
   shows is the pin the row was drawn from. */
function projectDots(project, name) {
  return rowDots({ kind: 'project', id: project.id, label: name,
                   title: project.name || name, pinned: !!project.pinned });
}

/* ---------- the Pinned section ----------

   Petar, 22 September 2026, asked for a Pinned section over each of the
   sidebar's three lists: the pinned projects, then that list's own pinned
   things. The chats and the tasks went on 30 September 2026 with their
   Pinned sections, and the runs kept theirs when they became a page: the
   pinned projects, each the very row `renderProjects` draws, chevron and
   all, and then the pinned runs, each the very card the list below draws.

   Nothing is drawn twice: the list below leaves out what is pinned, the
   projects group leaves out the projects that are, and an open project
   leaves out the runs that are, because they are in here. This section is
   the one place that never leaves anything out - it is the list of what the
   person pinned, and a pin that puts a row somewhere it cannot be found is
   not a pin. The Control Room's pins are the tasks', and are not these. */
function pinnedProjects() {
  var out = [], i;
  if (!CHATS) return out;
  for (i = 0; i < CHATS.folders.length; i++) {
    if (CHATS.folders[i].pinned) out.push(CHATS.folders[i]);
  }
  return out;
}

function pinnedRuns() {
  var out = [], k, rec;
  for (k in taskRecs) {
    rec = taskRecs[k];
    if (!rec.pinned) continue;
    // Archived is archived wherever it is read: a pin does not drag a run
    // the person put away back onto the screen.
    if (!SHOW_ARCHIVED && rec.archived) continue;
    if (!runsInTab(rec)) continue;
    out.push(rec);
  }
  return out.sort(byStart);
}

function renderPinned() {
  var host = $('sbPins');
  if (!host) return;
  var projects = pinnedProjects(), items = pinnedRuns(), i;
  host.textContent = '';
  for (i = 0; i < projects.length; i++) host.appendChild(projectRow(projects[i]));
  for (i = 0; i < items.length; i++) host.appendChild(taskCard(items[i]));
  // Empty, it says how it is filled. This section is the only thing on the
  // screen that says a row can be pinned at all, and a heading over nothing
  // teaches nobody anything.
  if (!projects.length && !items.length) {
    host.appendChild(el('p', 'empty', 'Nothing pinned. The \u22EF at the end'
      + ' of a project or a run pins it here.'));
  }
  rowsRedrawn();
}

/* The heading folds the section away, and this browser remembers it.
   Somebody with a dozen things pinned wants past them to the list
   underneath, and folding is the only way there in a column that is one
   scroller from top to bottom. */
var PINS_OPEN = load('rouh.pins') !== 'shut';

function pinsFold(open, remember) {
  PINS_OPEN = !!open;
  var block = $('sbPinned'), head = $('sbPinsFold');
  if (block) block.setAttribute('data-open', PINS_OPEN ? 'yes' : 'no');
  if (head) {
    head.setAttribute('aria-expanded', PINS_OPEN ? 'true' : 'false');
    head.title = PINS_OPEN ? 'Fold away what is pinned'
                           : 'Show what is pinned';
    head.setAttribute('aria-label', head.title);
  }
  if (remember) store('rouh.pins', PINS_OPEN ? 'open' : 'shut');
}

(function () {
  var head = $('sbPinsFold');
  if (!head) return;
  head.addEventListener('click', function () { pinsFold(!PINS_OPEN, true); });
  pinsFold(PINS_OPEN, false);
}());

/* ---------- the projects dashboard ----------

   Petar, 22 September 2026: "Projects link should be present on any of those
   in the sidebar right under New (task/chat/run). When I click projects it
   should open projects dashboard that will replace the chat and canvas. I
   can then close it to go back to chat and canvas setup or whatever was
   before that."

   **It is not in the navigation any more.** The three All projects links
   under each New went on 23 September 2026, when the person asked for the
   task browser in their place: the browser is every project and every task
   at once, so a dashboard of the projects alone beside it was the same
   shelf read twice with less on it. This is still where a project of the
   person's own is made, renamed, pinned and deleted - it has no folder and
   no page in the workspace, so the browser has nothing to draw for it - and
   search is the way in (`searching._open`, `findGo`).

   So it is deliberately not one of the canvas layers. A run, the tasks,
   Settings and the list of chats all open over the canvas and leave the
   conversation beside them; a project holds chats, and arranging them beside
   an open one is the same list read twice. This is a grid item laid across
   both of those columns, and the two underneath go quiet rather than being
   unloaded - a run's terminal keeps its size, the transcript keeps its
   scroll - so closing it gives back exactly what was there, whatever it was.

   What it holds is every project, nested the way they own one another, and
   the three things done to one: made, renamed, deleted.

   **Deleting one deletes what is in it**, which is the one place in Rouh
   where deleting an owner takes what it owned, and is what the person asked
   for in those words. The sentence on the confirmation is the walk the
   server is about to make and not the top of it: the counts are asked for
   the moment the cross is pressed, and nothing is written until they are
   back and the person has said yes.
*/

var PROJ = { open: false };

// Asked before this section has run - `showLayer` stands every layer down on
// the load that comes home from Google - so it answers for a page that is
// still being built, the same way `settingsViewing` does.
function projectsViewing() { return !!(PROJ && PROJ.open); }

/* How deep a project may be nested from this page. `objects.py` has no
   opinion about depth and says so in as many words: how deep the nesting may
   go is a decision for the screen. This is that decision, and three is what
   the person's own tree is - Work, then a company, then what is inside it.
   A row deeper than this is still drawn, at the last indent, because a
   project that vanishes rather than being drawn badly is a project nobody
   can delete. */
var PROJ_DEPTH = 3;

//: What is in a project, in the order a row says them under its name: a
//: project first, then the work, the conversations, the runs and what they
//: drew. One word for one of them and one for several, because "1 chats"
//: reads as a bug. The delete's own sentence is the server's, in the same
//: shape (`owning._count_words`).
var HOLDS_WORDS = [['project', 'project', 'projects'],
                   ['task', 'task', 'tasks'],
                   ['chat', 'chat', 'chats'],
                   ['run', 'run', 'runs'],
                   ['artifact', 'artifact', 'artifacts']];

function projectsOpen() {
  if (projectsViewing()) return;
  // The Gene therapy board covers the same two columns. Two of them at once is
  // one screen nobody can see under another.
  gtBoardClose();
  PROJ.open = true;
  var app = $('app'), view = $('projectsView');
  if (app) app.classList.add('projects-open');
  if (view) view.hidden = false;
  projectsSaid('');
  // Asked for again on opening, so a dashboard reached from a tab that has
  // been sitting open is the projects as they are now.
  send({ type: 'list_chats' });
  renderProjectsView();
  if (view && view.focus) view.focus();
  // On a screen the sidebar covers or floats over, the dashboard is
  // underneath it, so the press that opened it is also the press that is
  // done with the navigation.
  sidebarDone();
}

function projectsClose() {
  if (!projectsViewing()) return;
  PROJ.open = false;
  var app = $('app'), view = $('projectsView');
  if (app) app.classList.remove('projects-open');
  if (view) view.hidden = true;
  projectsSaid('');
  // The two columns underneath are a size again, and the orb, the text box
  // and a run's terminal all measure themselves against what they are in.
  window.dispatchEvent(new Event('resize'));
}

// Why something was refused, in the server's own sentence, until the next
// press. "" clears it.
function projectsSaid(why) {
  var box = $('projectsSaid');
  if (!box) return;
  box.textContent = why || '';
  box.hidden = !why;
}

/* Which project each one is inside, as far as this page is concerned.

   A project whose owner is not on the same list is drawn at the top of it
   rather than under a row that is not there - which is what one of the
   person's own filed under a project of the workspace is. */
function projectsUnder(rows) {
  var have = {}, under = {}, i, row, owner;
  for (i = 0; i < rows.length; i++) have[rows[i].id] = true;
  for (i = 0; i < rows.length; i++) {
    row = rows[i];
    owner = have[row.owner] ? row.owner : '';
    (under[owner] = under[owner] || []).push(row);
  }
  return under;
}

/* The rows of one list, parents before children, each drawn by `make`.

   `seen` is not tidiness: two types nest inside themselves, so three
   projects can in principle be written into a ring, and a walk with nothing
   remembering where it has been would draw that ring until the page fell
   over. `objects.attach` refuses to write one; this refuses to draw one. */
function projectList(host, rows, make) {
  var under = projectsUnder(rows), seen = {};
  (function walk(ownerId, depth) {
    var list = under[ownerId] || [], i;
    if (depth > 8) return;
    for (i = 0; i < list.length; i++) {
      if (seen[list[i].id]) continue;
      seen[list[i].id] = true;
      host.appendChild(make(list[i], depth));
      walk(list[i].id, depth + 1);
    }
  })('', 0);
}

// One step of indent per level of nesting, and no more after the last one:
// a project five deep is still a project, and a row indented off the side of
// the column is a row nobody can press.
function indentClass(depth) {
  var at = Math.min(depth, PROJ_DEPTH - 1);
  return at >= 2 ? ' deeper' : at === 1 ? ' deep' : '';
}

// What is in a project, in words, under its name. The counts are the whole
// walk down, which is the same number the confirmation is written from.
function holdsLine(holds) {
  var said = [], i, n;
  for (i = 0; i < HOLDS_WORDS.length; i++) {
    n = (holds && holds[HOLDS_WORDS[i][0]]) || 0;
    if (n) said.push(n + ' ' + (n === 1 ? HOLDS_WORDS[i][1] : HOLDS_WORDS[i][2]));
  }
  return said.length ? said.join(' · ') : 'Nothing in it yet';
}

function askNewProject(ownerId, ownerName) {
  projectsSaid('');
  var said = window.prompt(ownerId
    ? 'What should the project inside "' + ownerName + '" be called?'
    : 'What should the project be called?', '');
  if (said == null || !said.trim()) return;
  send({ type: 'new_folder', name: said, owner: ownerId || '' });
}

function askRenameProject(project, shown) {
  projectsSaid('');
  var said = window.prompt('What should this project be called?', project.name);
  if (said == null || !said.trim()) return;
  send({ type: 'rename_folder', id: project.id, name: said });
}

// One of the person's own: the three things that can be done to it, and what
// is in it said under its name so the size of the delete is on the screen
// beside the control that does it.
function projectCard(project, depth) {
  var parts = projectParts(project);
  var row = el('div', 'pv-row' + indentClass(depth));
  row.setAttribute('data-project', project.id);
  row.appendChild(el('span', 'pv-emoji', parts.emoji));
  var name = el('div', 'pv-name');
  name.appendChild(el('span', 'pv-name-line', parts.name));
  name.appendChild(el('span', 'pv-holds', holdsLine(project.has)));
  row.appendChild(name);

  // A project may own a project, which is half of the nesting the hierarchy
  // is made of. A task may never own one, so there is no button like this
  // anywhere on a task.
  if (depth + 1 < PROJ_DEPTH) {
    var inside = el('button', 'icon-btn tiny', '+');
    inside.type = 'button';
    inside.title = 'Make a project inside ' + parts.name;
    inside.setAttribute('aria-label', inside.title);
    inside.addEventListener('click', function () {
      askNewProject(project.id, parts.name);
    });
    row.appendChild(inside);
  }

  row.appendChild(pinToggle(project, parts.name));

  var ren = el('button', 'icon-btn tiny', '✎');
  ren.type = 'button';
  ren.title = 'Rename this project';
  ren.setAttribute('aria-label', 'Rename the project ' + parts.name);
  ren.addEventListener('click', function () { askRenameProject(project); });
  row.appendChild(ren);

  // The same cross as the chat list's: it asks the server what it is about
  // to take before it asks the person, so the sentence they read is the walk
  // that is about to happen and not the top of it - a project holding one
  // project holding forty chats says forty.
  // Nothing is written until the answer is back and they have said yes.
  var del = deleteCross('project', project.id, parts.name);
  del.classList.add('pv-del');
  row.appendChild(del);
  return row;
}

/* One of the workspace's. It is a folder in a git repository with the
   person's work in it, so it is read here and arranged in the workspace:
   renaming this row would say one thing while the folder said another, and
   deleting it would take the row away, leave the folder, and have the row
   put straight back the next time the tree was read
   (`objecttree.ensure_imported`). The server refuses both in those words;
   this does not offer them. What it does offer is the way in. */
function wsProjectCard(project, depth) {
  var row = el('div', 'pv-row theirs' + indentClass(depth));
  row.setAttribute('data-ws-project', project.id);
  row.appendChild(el('span', 'pv-emoji', '\u{1F5C2}'));
  var name = el('div', 'pv-name');
  name.appendChild(el('span', 'pv-name-line', project.name));
  name.appendChild(el('span', 'pv-holds',
    project.folder + ' · ' + holdsLine(project.has)));
  row.appendChild(name);
  var open = linkTo(el('a', 'ctl small', 'Open'), function () {
    return addrPlaceLink(addrOf('project', project.folder));
  });
  open.title = 'Open ' + project.name + ' in the canvas (' + project.folder + ')';
  open.setAttribute('aria-label', open.title);
  open.addEventListener('click', function () {
    projectsClose();
    canvasTask(project.folder);
  });
  row.appendChild(pinToggle(project, project.name));
  row.appendChild(open);
  return row;
}

/* Pin this project, or take the pin off. On both kinds of card, because a
   pin is the person's own note about a row and takes nothing from the
   folder underneath it: a project of the workspace is arranged in the
   workspace and is read here, and marking it as one of the two or three
   they are in this month is not arranging it.

   A pinned project is drawn in the Pinned section at the head of whichever
   of the three lists the sidebar is showing, so this is one of the two
   controls that puts it there - the other is Pin in the three-dot menu on
   the project's own row. */
function pinToggle(project, name) {
  var on = !!project.pinned;
  var b = el('button', 'icon-btn tiny pv-pin' + (on ? ' on' : ''),
             '\uD83D\uDCCC');
  b.type = 'button';
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  b.title = on ? 'Un-pin ' + name + ' from Pinned in the sidebar'
               : 'Pin ' + name + ' to Pinned in the sidebar';
  b.setAttribute('aria-label', b.title);
  b.addEventListener('click', function () {
    projectsSaid('');
    send({ type: 'pin_object', kind: 'project', id: project.id, on: !on });
  });
  return b;
}

function renderProjectsView() {
  var host = $('projectsBody');
  if (!host || !CHATS) return;
  var mine = chatProjects(), theirs = wsProjects();
  var meta = $('projectsMeta');
  if (meta) {
    meta.textContent = '';
    meta.appendChild(el('span', null,
      mine.length === 1 ? '1 project' : mine.length + ' projects'));
    if (theirs.length) {
      meta.appendChild(el('span', null, theirs.length + ' in your workspace'));
    }
    meta.appendChild(el('span', null, 'A project holds chats, tasks and runs'));
  }
  host.textContent = '';
  if (!mine.length) {
    host.appendChild(el('p', 'empty', 'No projects of your own yet. New project '
      + 'makes one, and a chat goes into it from its own menu.'));
  } else {
    projectList(host, mine, projectCard);
  }
  if (!theirs.length) return;
  host.appendChild(el('h3', 'pv-sub', 'In your workspace'));
  host.appendChild(el('p', 'pv-sub-note', 'Folders in your workspace, in git, with '
    + 'your work in them. They are made, renamed and moved in the task '
    + 'browser, so they are read here rather than changed here.'));
  projectList(host, theirs, wsProjectCard);
}

(function () {
  if ($('projectsClose')) {
    $('projectsClose').addEventListener('click', function () { projectsClose(); });
  }
  if ($('projectsNew')) {
    $('projectsNew').addEventListener('click', function () { askNewProject('', ''); });
  }
})();

/* The runs, as a page of their own on the canvas: Metabolism, at `/metabolism`.
 *
 * They were one of three lists the sidebar switched between - the tasks,
 * the chats and the runs - until 30 September 2026. Petar never used the
 * other two, and asked for the switch and both of them to go and for the
 * runs to open like Reminders and Goals, from a row in the navigation. So
 * this is a layer like theirs, and everything the list held is on it
 * unchanged: New run, the tally, the archived tick, what is pinned, the
 * projects that hold runs and the cards with their dots.
 *
 * It was Runs, at `/runs`, until 14 October 2026. Petar: "use metabolism.
 * and within the runs page, split it in two types - mutations and everyday
 * work." So it has two tabs, each with its own count: Everyday work, the
 * person's own errands, at `/metabolism`, and Mutations, the runs that change
 * Rouh itself, at `/metabolism/mutations`. Which a run is on is the server's
 * word, sent on its row as `kind` (`runs.kind_of`). It opens on Everyday work,
 * unless it is opened from Evolution or over a mutation's own run, which is
 * where somebody looking for a mutation comes from.
 *
 * Opening it is looking at the runs, and closing it ends the visit
 * (`runsShowing`), which is what the switch and the drawer did before.
 */
var RUNSVIEW = { open: false, kind: 'everyday' };

function runsViewing() { return !!(RUNSVIEW && RUNSVIEW.open); }

/** Which tab of Metabolism a run is on: 'mutation' or 'everyday'.
 * @param {any} rec */
function runKind(rec) { return rec && rec.kind === 'mutation' ? 'mutation' : 'everyday'; }

/** Whether a run is on the tab that is showing. @param {any} rec */
function runsInTab(rec) { return runKind(rec) === RUNSVIEW.kind; }

/* Which tab to open on when nothing named one: Mutations from Evolution, or
   from a mutation's own run on the canvas; Everyday work otherwise. Asked
   before the page is shown, while what it was opened from is still there. */
function runsKindHere() {
  if (EVO.open) return 'mutation';
  var id = ONE && ONE.viewing && ONE.selected ? ONE.selected : jobViewing() ? JOBVIEW.id : '';
  return id && taskRecs[id] ? runKind(taskRecs[id]) : 'everyday';
}

/** @param {string} [kind] 'mutation' or 'everyday'; left out, `runsKindHere` */
function runsOpen(kind) {
  var want = kind === 'mutation' || kind === 'everyday' ? kind : runsKindHere();
  if (RUNSVIEW.open) {
    if (want !== RUNSVIEW.kind) runsTab(want);
    return;
  }
  if (ORBX.open) orbExpand(false);
  RUNSVIEW.kind = want;
  RUNSVIEW.open = true;
  showLayer('runsView');
  sidebarDone();
  runsRowPaint();
  runsShowing();
  renderTasks();
  jobWordsLoad();
  if (!narrow()) $('runsView').focus({ preventScroll: true });
}

/** One of the two tabs, by the person's press or by an address. @param {string} kind */
function runsTab(kind) {
  RUNSVIEW.kind = kind === 'mutation' ? 'mutation' : 'everyday';
  renderTasks();
  if (RUNSVIEW.open) addrTouch();
}

function runsClose() {
  if (!RUNSVIEW.open) return;
  RUNSVIEW.open = false;
  // A menu or a half-typed name over a card goes with the page it was on.
  rowsFollowSidebar(false, '#runsView');
  showLayer(null);
  runsRowPaint();
  runsShowing();
}

/* What background jobs asked Rouh for (`rouh/job_gateway.py`), on Metabolism in a
   brown toggle: each gap once, with how often it was asked, and the asks under it,
   closed until pressed. Read from /api/job-requests each time it is opened. */
/** @param {number} at seconds */
function jobAskWhen(at) {
  if (!at) return '';
  return new Date(at * 1000).toLocaleString([], { month: 'short', day: 'numeric',
                                                   hour: '2-digit', minute: '2-digit' });
}

var JOB_ASK_OUTCOME = {
  asking: 'Being read', tool: 'A tool does it', owner: 'Asked you', cannot: 'Cannot be had',
  pending: 'Waiting on your yes', rule: 'Your rule let it go', yes: 'You said yes',
  no: 'You said no', failed: 'Yes, but it failed', answered: 'You answered',
  error: 'Could not be read', word: 'Ran on your word', cleared: 'Not put to you, nothing ran'
};

/** @param {any} got */
function jobAsksPaint(got) {
  var body = $('jobAsksBody');
  if (!body) return;
  body.textContent = '';
  var asks = (got && got.asks) || [];
  if (!asks.length) {
    body.appendChild(el('p', 'job-asks-none', 'No job has asked Rouh for anything yet.'));
    return;
  }
  /** @type {Object<string, any[]>} */
  var under = {};
  asks.forEach(function (a) {
    var key = a.kind + ':' + (a.gap || a.tool);
    (under[key] = under[key] || []).push(a);
  });
  (got.gaps || []).forEach(function (g) {
    var list = under[g.kind + ':' + g.gap] || [];
    if (!list.length) return;
    var row = el('details', 'job-ask');
    var head = el('summary', 'job-ask-head');
    head.appendChild(el('span', 'job-ask-what', g.kind === 'tool' ? g.gap + ' (needs your yes)'
                                                                 : g.gap));
    head.appendChild(el('span', 'job-ask-count', g.n === 1 ? 'once' : g.n + ' times'));
    head.appendChild(el('span', 'job-ask-state', JOB_ASK_OUTCOME[list[0].outcome] || list[0].outcome));
    row.appendChild(head);
    list.forEach(function (a) {
      var one = el('div', 'job-ask-one');
      var top = el('div', 'job-ask-top');
      var job = el('a', 'job-ask-job', a.job_title || ('Job ' + a.job_id));
      job.href = '/run/' + encodeURIComponent(a.job_id);
      top.appendChild(job);
      top.appendChild(el('span', 'job-ask-meta', [jobAskWhen(a.created_at),
        JOB_ASK_OUTCOME[a.outcome] || a.outcome,
        a.cost_usd != null ? '$' + Number(a.cost_usd).toFixed(4) : ''].filter(Boolean).join(' · ')));
      one.appendChild(top);
      one.appendChild(el('p', 'job-ask-need', a.kind === 'tool' ? a.tool + ' ' + a.need : a.need));
      if (a.why) one.appendChild(el('p', 'job-ask-why', 'Why: ' + a.why));
      if (a.answer) one.appendChild(el('p', 'job-ask-answer', a.answer));
      row.appendChild(one);
    });
    body.appendChild(row);
  });
}

/* "Done on your word" (Petar, 2 November 2026; `rouh/his_word.py`): what background jobs
   had Rouh do without asking, because his own words for the job already asked for it. Each
   line names the job, the call, the words that covered it, why, and how to undo it. Read
   from /api/job-requests whenever Metabolism opens. */
/** @param {any} got */
function jobWordsPaint(got) {
  var body = $('jobWordsBody');
  if (!body) return;
  body.textContent = '';
  var done = (got && got.on_word) || [];
  var count = $('jobWordsCount');
  if (count) count.textContent = done.length ? String(done.length) : '';
  if (!done.length) {
    body.appendChild(el('p', 'job-asks-none', 'Nothing has run on your word without asking yet.'));
    return;
  }
  done.forEach(function (a) {
    var one = el('div', 'job-word');
    var top = el('div', 'job-ask-top');
    var job = el('a', 'job-ask-job', a.job_title || ('Job ' + a.job_id));
    job.href = '/run/' + encodeURIComponent(a.job_id);
    top.appendChild(job);
    top.appendChild(el('span', 'job-ask-meta', jobAskWhen(a.created_at)));
    one.appendChild(top);
    one.appendChild(el('p', 'job-ask-need', a.tool + ' ' + (a.need || '')));
    var words = String(a.words || '').replace(/^\[[^\]]*\]\n/, '');
    if (words) one.appendChild(el('p', 'job-word-said', '\u201c' + (words.length > 400 ? words.slice(0, 399) + '\u2026' : words) + '\u201d'));
    if (a.judged) one.appendChild(el('p', 'job-ask-why', 'Why it was yours: ' + a.judged));
    if (a.undo) one.appendChild(el('p', 'job-ask-why', 'To undo it: ' + a.undo));
    body.appendChild(one);
  });
}

function jobWordsLoad() {
  var body = $('jobWordsBody');
  if (!body) return;
  if (!body.childNodes.length) body.appendChild(el('p', 'job-asks-none', 'Reading\u2026'));
  fetch('/api/job-requests', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (got) {
      if (got) jobWordsPaint(got);
      else body.textContent = 'Rouh could not read them just now.';
    })
    .catch(function () { body.textContent = 'Rouh could not read them just now.'; });
}

function jobAsksLoad() {
  var body = $('jobAsksBody');
  if (body && !body.childNodes.length) body.appendChild(el('p', 'job-asks-none', 'Reading…'));
  fetch('/api/job-requests', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (got) {
      if (got) jobAsksPaint(got);
      else if (body) body.textContent = 'Rouh could not read them just now.';
    })
    .catch(function () { if (body) body.textContent = 'Rouh could not read them just now.'; });
}

(function () {
  var box = $('jobAsks');
  if (box) box.addEventListener('toggle', function () {
    if (/** @type {HTMLDetailsElement} */ (box).open) jobAsksLoad();
  });
})();

function runsRowPaint() {
  var row = $('runsRow');
  if (!row) return;
  row.classList.toggle('on', RUNSVIEW.open);
  row.setAttribute('aria-expanded', RUNSVIEW.open ? 'true' : 'false');
}

(function () {
  var row = $('runsRow');
  if (row) {
    row.addEventListener('click', function () {
      if (runsViewing()) runsClose(); else runsOpen();
    });
  }
  if ($('runsClose')) $('runsClose').addEventListener('click', function () { runsClose(); });
  ['runsTabEveryday', 'runsTabMutation'].forEach(function (id) {
    var tab = $(id);
    if (!tab) return;
    tab.addEventListener('click', function () { runsTab(tab.getAttribute('data-kind') || ''); });
    // The two are one control: the arrow keys move between them, as a tab list's do.
    tab.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      var other = $(id === 'runsTabEveryday' ? 'runsTabMutation' : 'runsTabEveryday');
      if (!other) return;
      other.focus();
      runsTab(other.getAttribute('data-kind') || '');
    });
  });
  if ($('generalRow')) $('generalRow').addEventListener('click', function () { openGeneral(true); });
})();

/* A chat or a task, on one line.
 *
 * It used to be a card: a title that wrapped, a chip saying "Waiting on you"
 * in words, and the task's path underneath. Three lines each is six chats on
 * a laptop's screen, and a list you have to scroll to see is a list nobody
 * scans. So it is one line that runs out into an ellipsis, and what the
 * other two lines said is still here in a form that costs no height: the
 * task it is filed under is the number at the row's end, and the whole of
 * it - the task by name, how much has been said - is the row's own tooltip.
 *
 * A row carries one dot, and it is the chat's own: a turn belongs to the
 * thread it was asked in rather than to the screen (`Turn` in
 * rouh/server.py), so an answer carries on after the person has opened
 * something else and lands in a thread they are not looking at. Pulsing blue
 * is a thread being answered this instant, amber is one with an answer in it
 * nobody has seen. It says nothing out loud and does not take the view back.
 *
 * Nothing on a chat's row says what state its task is in. On 24 September
 * 2026 a dot at the end of the row did, and then a bar down its left edge,
 * both in the task's colour, and Petar found that neither matched anything
 * on the Tasks list. They could not: they were read from a file in the
 * task's folder (in progress, not started, stopped), while the Tasks list
 * reads the task's own row (open, waiting, done), which followed the file
 * only once it was reconciled. And a task can hold several chats, so one task
 * waiting on him lit every chat in it. He asked for the two to be the same
 * or for the bars to go, for the sake of simplicity. They went, and a task
 * waiting on the person says so once, on its own row (`askMark`).
 */
function threadAnswering(chat) {
  return !!(CHATS && CHATS.answering && CHATS.answering.indexOf(chat.id) >= 0);
}

function threadUnread(chat) {
  return !!(chat.unread && chat.id !== CHATS.active);
}

/* Picking a chat opens that chat.

   A chat under a task is opened by its own id and never by its task's
   folder, and the task's page follows it onto the canvas when it lands
   (`onChatSwitched`). By the folder, the task's own conversation is what
   comes back, which is the wrong one for any other chat under the task;
   and with one of those open the page already counts the task's thread as
   open (`THREAD_ASKED`), so pressing the task's own chat by its folder did
   nothing at all. By its id it is the chat that was pressed, every time,
   and from a list whose folders may be a message behind a move. A loose
   chat leaves the canvas where it is, because there is nothing in the
   workspace to open.

   On a screen the sidebar is lying over rather than beside, picking one is
   also the person saying they are done with the sidebar: what they picked
   is underneath it. */
/** @param {any} chat @param {boolean} [alone] with no fork laid out beside it (`openGeneral`) */
function openThread(chat, alone) {
  if (chat.task) openChat(chat.id);
  else {
    // The front door is in no chat, whichever one the server holds this tab
    // in, so the chat is drawn even when the server has the tab in it
    // already (`redraw`). Without it Rouh pressed there opened nothing.
    /** @type {import('./protocol').ToServer<'open_thread'>} */
    var m = { type: 'open_thread', id: chat.id };
    if (alone) m.alone = true;
    if (ADDR.front) m.redraw = true;
    send(m);
    if (CANVAS.mode !== 'now') goNow();
  }
  // The rail is a list of conversations. Picking one is asking to read it,
  // so the conversation is on the page even where what it is fills the
  // window: after the load, or the load would take it away again.
  chatIsWanted();
  sidebarDone();
}

/* General, from the speech bubble at the head of the sidebar.

   Petar, 24 September 2026 (fr_03e3838ad4ca): "when I press on the chat
   icon in the taskbar, I would like immediately by default that my GENERAL
   channel activates. this is where my main communication will go. only
   then if I want a separate chat I will go somewhere else". So the bubble
   does two things: it puts the Chats list up, as it always did, and it
   opens General, on every press and from wherever the person was. That is
   the press on General's row at the top of that list, which is exactly the
   press it saves them, and every other chat is still on the list under it.

   The chat is only asked for when it is not already the one open: asking
   again would draw it again and read its cards back from the start, for
   nothing. The rest is done either way - the canvas let go of a task's
   page, the conversation on the screen, the sidebar out of the way where
   it lies over the page - and the cursor goes into the box, ready for the
   first words. Not on a phone, where that would put the keyboard over the
   conversation they have only just been taken to; there it waits for a tap
   like every other box.

   Pressed as Rouh in the navigation (`alone`), it is General and nothing
   else. Petar, 15 October 2026 (fr_5c306c1cf386): "When I press Rouh from
   the navigation don't want any fork chats". General used to open with the
   fork he was last in still laid out beside it, and from inside a fork the
   press only slid him one chat to the left along the strip. So the forks
   off General are taken off its strip as it opens (`forks.alone`); each is
   still marked in the conversation where it came off, and opens again from
   there. */
/** @param {boolean} [alone] open it with no fork laid out beside it */
function openGeneral(alone) {
  var id = CHATS && CHATS.general;
  if (!id) return;
  if (CHATS.active !== id) {
    openThread(chatById(id) || { id: id }, alone);
    return focusTheBox();
  }
  if (alone && FORKS.strip.length > 1) send({ type: 'open_thread', id: id, alone: true });
  if (CANVAS.mode !== 'now') goNow();
  if (ASK.tab !== 'rouh') askTab('rouh');
  chatIsWanted();
  canvasAwayIfBare();
  sidebarDone();
  if (narrow()) setPane('chat');
  // Already open, it is still opened at its latest message, wherever it was
  // left scrolled to: that is what pressing Rouh is for (fr_5fcd2acebed7).
  scrollDown(true);
  focusTheBox();
}

function focusTheBox() {
  if (narrow() || !input) return;
  try { input.focus(); } catch (err) {}
}

/* ---------- the tasks, in the canvas ----------

   There is one way in and it is the task browser: every project and every
   task in the workspace, Work and Personal at the top and the projects inside
   them, drawn out of the object rows by `objectindex.py`. It is an ordinary
   view of the canvas, the middle column, the same layer a run opens on.

   Until 21 September 2026 it was a modal over the whole window, and four
   canvas modes stood beside it saying half the same things: index, task,
   page and source, on a dial in the far corner of the canvas that never
   connected with now. All four are gone. The canvas has two modes, `now` and
   `tasks`, and inside `tasks` what is loaded is decided by what was clicked:
   a task, a step, a page. There is no mode to press for any of it.

   What is loaded is one address, `CANVAS.at`, and the breadcrumb in the
   canvas bar reads it: the index, then the task, then the step, then the
   page's own title. Each level climbs to its parent, and the chevron on each
   lists its siblings, which is how the reader moves sideways without going
   back up first.

   The body is a frame holding the workspace's own page, with one exception:
   a step Rouh itself filed as a `step.md` has no built page for the
   workspace to draw, so its blocks are typeset here by the same renderer a
   card is. */

//: The two things the canvas can be showing. Nothing anywhere may ask for
//: index, task, page or source: they were modes and they are gone.
var CANVAS_MODES = ['tasks', 'now'];

//: Where the workspace's index lives, and the prefix of a task's own page
//: under it. Everything loaded in the canvas is an address under the first.
var BROWSE_ROOT = WORKSPACE_ROUTE;
var TASK_PREFIX = WORKSPACE_ROUTE + '_task/';

//: Which list the task browser was showing - the project or column pressed
//: and the words in its search box - kept for this tab. The browser's frame
//: is thrown away every time something is opened out of it, so it cannot
//: keep this itself; it says it here as it changes and asks for it back
//: when it is opened again, which is what makes Back from a task or a page
//: come back to the list the person left (`rouh-page-view`,
//: pages.VIEW_MESSAGE).
var TASKS_VIEW = { view: '', q: '' };

// Keys the page inside the frame owns - the workspace index walks its tasks
// with the arrows, opens one with Enter, unfolds one with Space and goes to
// its search box with "/". When the keyboard is on Rouh's own chrome
// instead of in the frame, they are sent down to it.
// C starts a comment on a page, as it does in Figma (`comments.js`), E
// points at the part of it to change (Edit, `askai.js`), and H is the
// highlighter (`highlights.js`).
var BROWSE_KEYS = ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Enter', ' ', '/',
                   'c', 'C', 'e', 'E', 'h', 'H'];

//: What the top of the browser is called, in the breadcrumb's first chip and
//: in the tab's name at `/tasks`. One word for it, so the two cannot drift.
var CRUMB_HOME = 'All tasks';

function tasksViewing() { return CANVAS.mode === 'tasks'; }

function tasksFrame() {
  var body = $('tasksBody');
  return body ? body.querySelector('iframe') : null;
}

// One address as the canvas holds it: without the answers Rouh puts in and
// takes out again, so the same page is never two different places.
function browseKey(href) {
  var u = new URL(href, location.href);
  u.searchParams.delete('framed');
  u.searchParams.delete('hosted');
  u.searchParams.delete('y');
  u.searchParams.delete('comment');
  return u.pathname + (u.search || '');
}

// The address of one task's own page, and of the index itself.
function taskUrl(rel) {
  return TASK_PREFIX + String(rel || '').split('/').map(encodeURIComponent).join('/') + '/';
}

function pageUrl(rel) {
  return WORKSPACE_ROUTE + String(rel || '').split('/').map(encodeURIComponent).join('/');
}

/* A task folder's name: a number, a dot, a name. `30-06.the-merge` is a step
   and not this, because its third character is a dash. It is the same rule
   `steps.py` keeps, and it is what tells the two levels apart now that a
   task is not always two folders down. */
var TASK_NAME = /^\d+\./;

/* The task a workspace path is in: up to and including its numbered folder.

   `tasks/30.jarvis/30-06.x` and `private/assistant/30.jarvis/30-06.x` are
   both in task 30, and the second is the shape the workspace has had since
   it was reshaped into projects: a task sits under the projects that own it,
   at whatever depth those go. A path with no numbered folder in it falls
   back to its first two parts, which is what the flat workspace's paths are
   and is what this always used to return. */
function taskOf(parts) {
  for (var i = 0; i < parts.length; i++) {
    if (TASK_NAME.test(parts[i])) return parts.slice(0, i + 1).join('/');
  }
  return parts.slice(0, 2).join('/');
}

/* Where an address is in the workspace, read off the address itself.

   Three shapes and nothing else:

     /workspace/                                        the index
     /workspace/_task/work/acme/19.pricing/             one task's own page
     /workspace/work/acme/19.pricing/19-04.x/p.html     one page of one step

   So the breadcrumb is worked out from the one thing that is always true -
   what is actually loaded - rather than from a trail of what was clicked,
   which goes wrong the moment the reader is sent somewhere directly. */
function placeOf(url) {
  var at = { task: '', step: '' };
  var path = String(url || '');
  var rest;
  if (path.indexOf(TASK_PREFIX) === 0) {
    rest = path.slice(TASK_PREFIX.length);
  } else if (path.indexOf(WORKSPACE_ROUTE) === 0) {
    rest = path.slice(WORKSPACE_ROUTE.length);
  } else {
    return at;
  }
  try { rest = decodeURIComponent(rest.split('?')[0]); } catch (err) { return at; }
  var parts = rest.split('/').filter(function (p) { return !!p; });
  var task = taskOf(parts);
  var deep = task ? task.split('/').length : 0;
  if (deep >= 2) at.task = task;
  if (deep >= 2 && parts.length > deep) at.step = task + '/' + parts[deep];
  return at;
}

function stepTask(rel) {
  var parts = String(rel || '').split('/').filter(function (p) { return !!p; });
  return parts.length >= 2 ? taskOf(parts) : '';
}

/* The working file an object's own page is reading, or ''. One of its
   notes, a folder, a code file: `?doc=` on that page's address
   (`objectindex.doc_url`), which is what every file on a task's page opens
   and every line of a folder listing. */
function canvasDoc() {
  var at = String(CANVAS.at || '');
  if (at.indexOf(TASK_PREFIX) !== 0 || at.indexOf('?') < 0) return '';
  var doc = '';
  try { doc = new URL(at, location.href).searchParams.get('doc') || ''; } catch (err) {}
  return doc.replace(/^\/+|\/+$/g, '');
}

/* One read of the workspace, as JSON.

   Every caller checks for itself whether the answer is still the one it
   wants - `canvasStep` against the step it asked about, `crumbFill` against
   the task - because two of these are in flight together the first time the
   breadcrumb is drawn: the list of every task, and the steps of the one
   being looked at. A single "only the newest answer counts" counter here
   threw one of those two away, whichever came back second, and the list of
   tasks is asked for once, so losing it lost the task level's siblings for
   as long as the page stayed open. */
function canvasGet(url) {
  return fetch(url, { credentials: 'same-origin' })
    .then(function (r) { return r.json().catch(function () { return {}; }); })
    .catch(function () { return { error: 'That could not be read.' }; });
}

// --- what is loaded, and loading it ---

// The index itself: the task browser, and the top of everything.
function tasksOpen() {
  canvasLoad(BROWSE_ROOT);
}

/* The same index, asked for from the navigation.
 *
 * Petar, 23 September 2026: "wherever I am, when I click Task Browser, it
 * should fill both columns: the chat column and the canvas column. I should
 * see it as full screen, so to speak, beside the sidebar, because this is an
 * extensive page that requires real estate."
 *
 * So it is not quite `tasksOpen`. That one is also the breadcrumb's first
 * chip and the way back from a page that would not load, and both of those
 * are pressed from inside the tasks, where a conversation the person asked
 * for while they were there stays beside them (`chatIsWanted`). This press
 * comes from outside and is them saying what the window is for, so the
 * conversation is taken again whatever was open in it.
 */
function tasksBrowse() {
  tasksTakeChat();
  tasksOpen();
  // On a screen the sidebar covers or floats over, the press that opens the
  // browser is also the press that is done with the navigation - the same
  // thing New chat and a project's row both do.
  sidebarDone();
}

// One task's own page, drawn by the workspace. This is what clicking a task
// does, in the browser, in the breadcrumb and in the list of chats and tasks
// alike: there is one behaviour and this is it.
function canvasTask(rel) {
  if (!rel) return;
  canvasLoad(taskUrl(rel));
}

/* A step's own page, the way a press on the step opens it: the same page a
   task has, drawn for the step (`objectindex.build_task`). `canvasStep`
   below is the other thing, the step's content itself, for the model
   showing it and for a card filed as one. */
function canvasStepPage(rel) {
  if (!rel) return;
  canvasLoad(taskUrl(rel));
}

/* Picking a task is picking its thread, and a task is picked from four
   places: the browser, the breadcrumb, the rail and the list of chats and
   tasks. One sender for all four, so no two of them can drift.

   Only when it really changes. Switching chats is told to the tab and
   hands it a fresh transcript, so sending it again for every page
   of the task already open would cut the voice off mid-sentence for a pick
   the person did not make. `THREAD_ASKED` follows what actually happened,
   including a chat opened on another device (`onChatSwitched`). */
shared.THREAD_ASKED = '';

/* The task whose page Start chat was pressed on, until the chat it asked
   for is open (`taskChat`). A switch into a task's chat with that task's
   page on the canvas is otherwise the page being loaded, and on a phone the
   person stays on the page they loaded (`onChatSwitched`); this one they
   asked for, and they are taken to it. */
shared.TASK_CHAT_ASKED = '';

/* Which conversation goes beside what the canvas holds.

   A task's page is beside the task's own conversation. A subtask's page is
   beside the subtask's own once it has one - its chats are its own and stay
   local to it (Petar, 29 September 2026, fr_3113364c29fa, and
   `rouh/subtasknotes.py`) - and beside its task's while it has none, which
   is the background it would otherwise be talked about in. A subtask's chat
   that is open already is left open, whichever of its chats it is. */
function threadHere() {
  var step = CANVAS.step, i;
  if (!step) return CANVAS.task;
  var open = CHATS ? chatById(CHATS.active) : null;
  if (open && open.task === step) return step;
  for (i = 0; CHATS && i < CHATS.list.length; i++) {
    if (CHATS.list[i].task === step) return step;
  }
  return CANVAS.task;
}

// Whether the canvas is on this task's or this subtask's page, or inside it.
function canvasOn(rel) {
  return !!rel && (rel === CANVAS.task || rel === CANVAS.step);
}

function pickThread(task) {
  if (!task || task === shared.THREAD_ASKED) return;
  shared.THREAD_ASKED = task;
  // A page an address opened beside the conversation it named: that one
  // stays, and the rest of this task's pages leave it where it is too.
  if (ADDR.chatNamed) return;
  if (send({ type: 'open_thread', task: task })) { ADDR.thread = task; ADDR.half = ''; }
}

/* One step. A step built the old way has a page and is framed; a step Rouh
   filed as a `step.md` has none, and the workspace's own index cannot draw
   it, so its blocks are drawn here instead. Which of the two is a question
   for the server, so this asks before it loads. */
function canvasStep(rel) {
  if (!rel) return;
  CANVAS.mode = 'tasks';
  CANVAS.at = '';
  CANVAS.step = rel;
  CANVAS.task = stepTask(rel);
  CANVAS.stepData = null;
  showLayer('tasksView');
  tasksHold(true);
  pickThread(threadHere());
  drawCrumb();
  holdOn('Reading the step…');
  canvasGet('/api/workspace/step?rel=' + encodeURIComponent(rel)).then(function (got) {
    if (!got || CANVAS.step !== rel) return;
    if (got.error) { holdOn(got.error); return; }
    if (got.page) { canvasLoad(pageUrl(got.page)); return; }
    CANVAS.stepData = got;
    drawStepBlocks(got);
  });
}

// One address in the frame. A fresh frame every time rather than steering
// the one that is there: the page inside is a whole page with its own
// scripts still running in it, and a new frame is the one certain way to
// stop them.
//: How long a page's frame is kept hidden behind its loading line at most.
var FRAME_WAIT_LONGEST = 10000;
function canvasLoad(url) {
  var asked = new URL(url, location.href);
  var at = browseKey(asked.href);
  if (at.indexOf(WORKSPACE_ROUTE) !== 0) return;
  CANVAS.mode = 'tasks';
  CANVAS.at = at;
  CANVAS.title = '';
  var place = placeOf(at);
  CANVAS.task = place.task;
  CANVAS.step = place.step;
  CANVAS.stepData = null;
  // Null while the list of chats has not come yet (`CHATS.listed`): the page is
  // the server's own word on them, and the list arriving is not a change to it.
  CANVAS.chats = CHATS.listed ? canvasChatsSaid() : null;
  showLayer('tasksView');
  // The conversation, for the index and for everything opened out of it.
  // The navigation is the person's own fold and is left alone.
  tasksHold(true);
  pickThread(threadHere());
  var body = $('tasksBody');
  // Loading, until the page inside the frame has drawn itself: the frame
  // is hidden and a quiet line stands where the page will be, rather than
  // an empty black box under the bar (fr_ba374cbf694f). The loading screen
  // a page opened at an address starts under waits for the same moment.
  body.className = 'tasks-body loading';
  body.textContent = '';
  var frame = document.createElement('iframe');
  // Scripts, and downloads: a task's file is saved from the Download under
  // its name and on its line, by a link that carries its own credential
  // (`rouh/filelinks.py`), which a browser refuses to save out of a frame
  // without `allow-downloads`. Nothing else is given.
  //
  // And new tabs, which is what makes a link in the page a plain link: Cmd,
  // Ctrl, Shift or the middle button on one opens it the way the browser
  // opens any link, and right-click's Open in new tab and Copy link work
  // (`pages.follow_script`, fr_2d5208267e36). A tab it opens escapes the
  // sandbox, because it is a page of its own at its own address, and the
  // server sends a tab opened onto a workspace file on to Rouh's address
  // for it, with this frame and this sandbox around it again.
  frame.setAttribute('sandbox',
    'allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox');
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.title = at === BROWSE_ROOT ? 'Every task in your workspace' : 'A page from your workspace';
  body.appendChild(frame);
  body.appendChild(el('p', 'tasks-wait', 'Loading…'));
  function drawn() {
    if (frame.parentNode === body) body.classList.remove('loading');
  }
  // With the place in the page the link named, if it named one: the frame
  // is taken there once the page is in it (`frameLoad`).
  frameLoad(frame, at + (asked.hash || ADDR.hash || '')).then(function (got) {
    if (!tasksViewing() || CANVAS.at !== at) { drawn(); return; }
    // Nothing came back. The frame is taken away rather than left showing
    // the browser's own blank page with a grey line on it, and Rouh says
    // what happened in its own chrome, with the way back on it.
    if (got && !got.ok) { drawn(); canvasLost(at, got); return; }
    // The page went into the frame (`frameWrite`), and is drawn once it has
    // loaded there - its styles and its script with it - or after
    // `FRAME_WAIT_LONGEST` if something in it never finishes.
    frame.addEventListener('load', drawn, { once: true });
    setTimeout(drawn, FRAME_WAIT_LONGEST);
    // Rouh may have sent the request somewhere else on the way: a task
    // whose whole content is one page is that page. The breadcrumb says
    // where the reader actually is, so it follows.
    if (got && got.landed && got.landed !== at) {
      CANVAS.at = got.landed;
      var landedIn = placeOf(got.landed);
      CANVAS.task = landedIn.task || CANVAS.task;
      CANVAS.step = landedIn.step;
    }
    if (got && got.title) { CANVAS.title = got.title; addrTouch(); }
    drawCrumb();
    // The keyboard goes into the frame once there is a page in it to take
    // it, so the arrows and "/" work without the reader clicking first.
    tasksFocus();
  });
  drawCrumb();
  orbPlace(orbWanted());
  renderThreads();
  // The page read again in place, because what it lists changed, is not the
  // person asking for it: on a phone they stay in the conversation, here
  // and in `showLayer`. Until 29 September 2026 the first message in a chat
  // started from a task's page reloaded that page (its Chats list had a new
  // chat) and slid the phone back to it, away from the answer.
  if (narrow() && !CANVAS.redraw) setPane('canvas');
}

// A line in the body where a page would be: reading, or why there is not one.
function holdOn(words) {
  var body = $('tasksBody');
  body.className = 'tasks-body blocks';
  body.textContent = '';
  body.appendChild(el('p', 'empty', words));
  orbPlace(orbWanted());
  if (narrow()) setPane('canvas');
}

/* The page that was asked for did not come back.
 *
 * Until 23 September 2026 this was the frame's own problem and the frame
 * drew it: a sentence in grey on a page with no background, which is a
 * white sheet in the middle of a dark app, with nothing on it to press. It
 * is the screen the person sent in and said "the error I sometimes get",
 * and the address behind it was a page whose task had moved out from under
 * it (`objecttree.move`, and `_mended` in objectindex.py).
 *
 * The cause is fixed; this is the other half, and it holds for whatever
 * fails next. Rouh says what happened in its own chrome and in its own
 * colours, names the address, and puts the two ways back on the screen:
 * the task this page belongs to, and the browser.
 */
function canvasLost(at, got) {
  var status = got && got.status ? got.status : 0;
  var body = $('tasksBody');
  body.className = 'tasks-body blocks';
  body.textContent = '';
  var box = el('div', 'lost');
  // No connection, and the page is not in this device's copy: a task outside the Control
  // Room's active clusters, or one never opened since the copy was made (app/offline.js).
  var away = !status && window.RouhOffline && !window.RouhOffline.online();
  if (away) {
    box.appendChild(el('h2', null, 'Not available offline'));
    box.appendChild(el('p', 'lost-why', 'This page is not in this device’s copy. The copy keeps every task the '
      + 'Control Room ranks above quiet, and every pinned one, whole; this one opens again once you are back online.'));
  }
  if (!away) box.appendChild(el('h2', null, status === 404
    ? 'That page is not here any more'
    : (status === 401 || status === 403
      ? 'Your sign-in has run out'
      : 'That page could not be read')));
  if (!away) box.appendChild(el('p', 'lost-why', status === 404
    ? 'Nothing answers at ' + at + '. It has been moved, renamed or deleted '
      + 'since something last linked to it.'
    : (status === 401 || status === 403
      ? 'Reload Rouh to read this page.'
      : 'Rouh asked for ' + at + ' and got '
        + (status ? 'a ' + status + ' back.' : ((got && got.why) || 'no answer.')))));
  var row = el('div', 'lost-acts');
  // The task this page sits in, when that is somewhere else to go. A page
  // that failed and is itself the task's own page has only the browser left.
  if (CANVAS.task && taskUrl(CANVAS.task) !== at) {
    var task = CANVAS.task;
    var back = linkTo(el('a', 'lost-btn', 'Back to this task'), addrOfFolder(task));
    back.addEventListener('click', function () { canvasTask(task); });
    row.appendChild(back);
  }
  var home = linkTo(el('a', 'lost-btn', CRUMB_HOME), ADDR_BROWSER);
  home.addEventListener('click', tasksOpen);
  row.appendChild(home);
  box.appendChild(row);
  body.appendChild(box);
  drawCrumb();
  orbPlace(orbWanted());
  if (narrow()) setPane('canvas');
}

// A step with no built page: its blocks, typeset by the same renderer a card
// is drawn with, so nothing is authored twice.
function drawStepBlocks(step) {
  CANVAS.title = step.title || step.folder || '';
  var body = $('tasksBody');
  body.className = 'tasks-body blocks';
  body.textContent = '';
  if (step.blocks && step.blocks.length) {
    var blocks = sourcesLast(step.blocks);
    for (var i = 0; i < blocks.length; i++) {
      var node = renderBlock(blocks[i], 0);
      if (node) body.appendChild(node);
    }
    footnotes(body);
  } else if (step.source) {
    body.appendChild(el('pre', 'step-source', step.source));
  } else {
    body.appendChild(el('p', 'empty', 'There is nothing in this step folder yet.'));
  }
  drawCrumb();
  orbPlace(orbWanted());
  renderThreads();
  if (narrow()) setPane('canvas');
}

function tasksClose() {
  if (!tasksViewing()) return;
  CANVAS.mode = 'now';
  CANVAS.at = '';
  CANVAS.task = '';
  CANVAS.step = '';
  CANVAS.stepData = null;
  CANVAS.title = '';
  // The frame goes rather than being left loaded and hidden: it is a whole
  // page with its own scripts still running in it.
  $('tasksBody').textContent = '';
  showLayer(null);
  // The conversation the reader had before the tasks took it. The
  // navigation was never theirs to take, so there is nothing to give back.
  tasksHold(false);
  crumbMenuClose();
  drawCrumb();
  renderThreads();
  orbPlace(orbWanted());
}

/* The canvas was showing something that has just been deleted.
 *
 * The lists all redraw from a message the server sends again; the canvas
 * does not, because it holds one address and nothing tells it that address
 * has stopped existing. So a task deleted while its own page was open left
 * the page on the screen, reading as though nothing had happened, until
 * something else was clicked.
 *
 * `gone` is the workspace folders that really were removed, so a step inside
 * a deleted task matches on the prefix without being named itself.
 */
//: When a deleted page was left for the level above it, so the chat switch
//: that follows the delete leaves that level on the canvas.
shared.LEFT_UP = 0;

function canvasLeftBehind(gone) {
  // A chat or a subtask deleted from the task's page it is listed on: that
  // page again, without it.
  var page = DEL.page;
  DEL.page = '';
  if (page && tasksViewing() && CANVAS.at === page && tasksFrame()) {
    frameLoad(tasksFrame(), page);
    return;
  }
  if (!Array.isArray(gone) || !gone.length || !tasksViewing()) return;
  var here = [CANVAS.step, CANVAS.task], i, j, rel;
  for (i = 0; i < gone.length; i++) {
    rel = String(gone[i] || '').replace(/\/+$/, '');
    if (!rel) continue;
    for (j = 0; j < here.length; j++) {
      if (!here[j]) continue;
      if (here[j] === rel || here[j].indexOf(rel + '/') === 0) {
        // To the level above what went, rather than off the tasks: a
        // subtask's task, a task's project, which is where the person was
        // before they opened it (fr_3273da8d3be9). The workspace itself
        // when what went was at the top.
        var up = rel.split('/').slice(0, -1).join('/');
        if (up) canvasLoad(taskUrl(up)); else tasksOpen();
        // The task's own chat went with it, so the server is about to move
        // this tab into General, and a loose chat clears the canvas
        // (`onChatSwitched`). Not this once: the person is on the level
        // above what they deleted, which is where they are going next.
        shared.LEFT_UP = Date.now();
        return;
      }
    }
  }
}

// Off the tasks side altogether: the bare canvas, live work, the orb large.
function goNow() {
  if (tasksViewing()) { tasksClose(); return; }
  CANVAS.mode = 'now';
  showLayer(null);
  drawCrumb();
  orbPlace(orbWanted());
}

// Where the keyboard is while the tasks are loaded: in the frame, so the
// page's own keys work at once. Escape and Back still reach Rouh, because
// the page inside hands those two back up (pages.keys_script).
function tasksFocus() {
  var frame = tasksFrame();
  try { if (frame) { frame.focus(); return; } } catch (err) {}
  var view = $('tasksView');
  try { if (view) view.focus(); } catch (err) {}
}

// A link followed inside the frame. Clicking a piece of content is the whole
// of how the canvas is moved, so this is not a special case of anything: it
// loads what was clicked.
function browseGo(href) {
  if (!tasksViewing()) return;
  var key, hash;
  try {
    var went = new URL(href, location.href);
    key = browseKey(went.href);
    hash = went.hash;
  } catch (err) { return; }
  if (key.indexOf(BROWSE_ROOT) !== 0) return;
  canvasLoad(key + hash);
}

// Back out one level: a page to its step's task, a task to the index, the
// index to the bare canvas. This is what Escape does, and it is the same
// ladder the breadcrumb climbs.
function tasksUp() {
  if (!tasksViewing()) return;
  if (CANVAS.step) { canvasTask(CANVAS.task); return; }
  if (CANVAS.task) { canvasLoad(BROWSE_ROOT); return; }
  tasksClose();
}


/* ---------- the page's side of the one conversation ----------

   There were two chats on this screen at once until 23 September 2026: this
   column, and the Ask AI drawer that slid over the page in the canvas beside
   it. Each had its own box, its own history and its own idea of what was
   being talked about.

   Petar: "on my interface, it is confusing to have two chats, so they need
   to be merged into one thing... I should not have two chats on the same
   screen at the same time."

   So there is one surface, and it is this column. A tab over it decides
   which of two things it is showing, and they are deliberately not one
   thread:

   - **This page**, below, answers questions about the page the canvas is
     showing, and since 24 September 2026 changes it when that is what is
     asked. It is grounded in that page and in the working notes beside it
     (askai.py), it quotes the passage the reader selected or names the
     element they pointed at, and its topics are its own rows in Rouh's
     database rather than chats in the project.
   - **Rouh** is the transcript above, with everything Rouh can do, for
     anything bigger than the page.

   Two chats kept apart under one roof rather than one chat that can do
   everything, for a reason that is not about this screen at all: the page
   is shared. A reader it is shared with gets the page's side and must never
   be able to reach the other, and "one chat with the dangerous half
   switched off" is not a thing that can be made safe. The page itself
   carries that side already (askai.js, which is what such a reader is
   served, `rouh/web/guests.py`); what changed here is that the owner reads
   it in this column instead of in a second panel laid over the page.

   What stays inside the page is what can only be there: the bar that appears
   over a passage as it is selected, the box that follows the pointer while
   the reader points at part of the page, and the mark over every passage
   already asked about. Those are handed up as `rouh-askai` messages and answered
   with `rouh-askai-do` ones, which is the same arrangement that already
   carries a clicked link and the keyboard across the frame's edge. Nothing
   in that channel names an address or writes anything: it carries a passage,
   a topic number and the page's own words, and which page all of it is about
   is this page's answer, read off the frame it loaded. */

//: How long this page waits for the frame to hand back the words on it.
//: A question is worth asking without them - the model still gets the
//: working notes - so this never holds the asking up for longer than this.
var ASK_CONTEXT_WAIT = 1500;

//: The most of a passage carried as a quote. `askai.SELECTION_MAX` is the
//: server's own number and this is the same one, so nothing is cut twice.
var ASK_QUOTE_MAX = 8000;

//: What the box says when there is nothing in the topic yet.
var ASK_EMPTY = 'Ask about the page, or say what to change. Select a passage, or Point at ' +
  'part of the page, to say which part.';

var ASK = {
  doc: '',        // the page this side is about, as the workspace addresses it
  tab: 'rouh',    // which side of the surface is on screen
  thread: 0,      // the topic being carried on; 0 starts a new one
  quote: '',      // the passage the question is about, if there is one
  busy: false,
  stop: null,     // the AbortController for an answer still arriving
  meta: {},       // what the topics list said about each topic
  picked: null,   // the element pointed at on the page, as the page described it
  pointing: false, // whether the page is waiting for the reader to point
  y: 0,           // how far down the page the reader was, when last asked
  patches: [],    // the changes the answer arriving made, for the page to make
  /** @type {{line: HTMLElement, heading: string} | null} */
  showing: null   // Show me pressed, waiting for the page to say what it found
};

//: What the box says when the page may be changed from it, and when a
//: passage or an element is what is being talked about.
var ASK_PLACEHOLDER = withSendKeys('Ask about this page, or say what to change',
                                   'Ask, or say what to change');
var ASK_CHANGE_HERE = withSendKeys('What should change here?');

/* The page the canvas is showing, as the workspace addresses it, or nothing.

   Three things are loaded in that canvas and only one of them is a page: the
   task browser and a task's own page are drawn by `objectindex.py` out of
   the database and have no file to ask about, and a step Rouh filed as a
   `step.md` has no built page at all. So this is the same rule
   `server.workspace_page` uses to decide whether to put Ask AI in at all. */
function askDoc() {
  var at = (CANVAS && CANVAS.at) || '';
  if (!tasksViewing() || at.indexOf(WORKSPACE_ROUTE) !== 0) return '';
  if (at === BROWSE_ROOT || at.indexOf(TASK_PREFIX) === 0) return '';
  var rel = at.slice(WORKSPACE_ROUTE.length).split('?')[0];
  if (!/\.html?$/i.test(rel)) return '';
  try { return decodeURIComponent(rel); } catch (err) { return ''; }
}

// What to call the page in the panel's own head. The title it came with
// where there is one, and its folder where there is not.
function askName(doc) {
  if (CANVAS && CANVAS.title) return CANVAS.title;
  var parts = String(doc || '').split('/').filter(function (p) { return !!p; });
  return parts.length > 1 ? parts[parts.length - 2] : (parts[0] || '');
}

/* Which side is on screen, and whether there is a second side at all.

   Called from `drawCrumb`, which is the one thing every way of changing what
   the canvas holds already goes through, so the row of tabs can never be
   left saying something about a page that is no longer loaded. */
function askShows() {
  var col = $('chatCol'), tabs = $('chatTabs');
  if (!col || !tabs) return;
  var doc = askDoc();
  if (doc !== ASK.doc) askStartOver(doc);
  seenTouch(doc);
  tabs.hidden = !doc;
  // Nothing loaded is one conversation and no tabs over it.
  if (!doc) ASK.tab = 'rouh';
  var on = ASK.tab === 'page';
  col.setAttribute('data-chat', on ? 'page' : 'rouh');
  var page = $('chatTabPage'), rouh = $('chatTabRouh');
  page.classList.toggle('on', on);
  page.setAttribute('aria-selected', on ? 'true' : 'false');
  rouh.classList.toggle('on', !on);
  rouh.setAttribute('aria-selected', on ? 'false' : 'true');
  $('pagePanel').hidden = !on;
  $('askComposer').hidden = !on;
  var dot = $('chatTabPageDot');
  if (on && dot) dot.hidden = true;
  var where = $('askWhere');
  if (where) where.textContent = doc ? askName(doc) : '';
}

/* The Rouh tab pressed over a page of a task: the conversation under it is
   that task's own.

   Petar, 17 October 2026 (fr_4cb844a4b7d5): "So I am at the 122 tasks and
   i press the purple icon for chat, then I click Rouh instead of the 'this
   page' option and it turns out I am at another chat, not the chat of this
   task. At this point the right chat needs to load that is relevant to the
   content on the side". Step 122-01's page had been opened beside the
   Hue chat whose job made it (`stay`, and an address naming a chat, both
   keep the conversation where it is: `pickThread`), so Rouh under it was
   about something else. Pressing the tab is the person asking to talk
   about what is beside it, so the task's conversation is opened then,
   whatever kept the other one: the subtask's own where it has one, the
   task's where it has not (`threadHere`), and a draft of it where the task
   has none yet (`conversations.open_for_task`). A chat that is already
   this task's or this subtask's stays, and so does one laid out along a
   strip of forks with one of theirs on it. */
function askRouhHere() {
  if (!CHATS || !CANVAS.task || !askDoc()) return;
  var open = chatById(CHATS.active);
  if (open && open.task && canvasOn(open.task)) return;
  for (var i = 0; i < FORKS.strip.length; i++) {
    var laid = chatById(FORKS.strip[i].id) || FORKS.strip[i];
    if (laid.task && canvasOn(laid.task)) return;
  }
  var task = threadHere();
  shared.THREAD_ASKED = task;
  send({ type: 'open_thread', task: task });
}

/* A different page is loaded, so this side starts again. A conversation
   about one page is not a conversation about another, and carrying a topic
   across would quietly ask the model about the wrong thing. */
function askStartOver(doc) {
  askAbort();
  ASK.doc = doc;
  ASK.thread = 0;
  ASK.quote = '';
  ASK.meta = {};
  ASK.picked = null;
  askPointing(false);
  askDrawPicked();
  askDrawQuote();
  askClear();
  askSources(null);
  var dot = $('chatTabPageDot');
  if (dot) dot.hidden = true;
}

// Moving between the two sides. It is also somebody asking for a
// conversation, and this column may be folded away - the tasks take it when
// a page is loaded - so it comes back the way every other way of opening one
// brings it back.
function askTab(which) {
  var want = which === 'page' ? 'page' : 'rouh';
  if (want === 'page' && !askDoc()) return;
  ASK.tab = want;
  chatIsWanted();
  // On a phone the conversation and the canvas are two panes and only one of
  // them is on the screen. Asking for a side of the conversation - from the
  // sparkle on the page, or from a passage selected on it - is asking to be
  // taken there, the same as opening a chat is.
  if (narrow()) setPane('chat');
  askShows();
  growInput();
  askGrow();
  var box = want === 'page' ? $('askInput') : input;
  if (box) setTimeout(function () { try { box.focus(); } catch (err) {} }, 0);
  /* A transcript that was off the screen could not be scrolled while it was
     there - an element with no layout has no scroll - so anything that
     arrived in it while the page's side was showing is above the fold the
     moment it comes back. It goes to the end, which is where somebody
     returning to a conversation is looking. */
  if (want === 'rouh') setTimeout(function () { scrollDown(true); }, 0);
  /* And once more when the column has finished sliding open. A box measured
     while the grid is still animating is measured at the width it is leaving
     rather than the one it is arriving at, and the first press of the
     sparkle - which is the press that opens the column - is exactly when
     that happens. */
  setTimeout(askGrow, 320);
}

/* A passage selected on the page, on its way into the box.

   This is the whole of what "select the text and click the hover" was, with
   the conversation in this column instead of in a second panel. A new
   passage is a new topic: a topic holds exactly one passage, which is what
   makes a mark on the page and a topic in the list the same thing rather
   than two records that can disagree. */
function askCite(text) {
  var passage = String(text || '').trim().slice(0, ASK_QUOTE_MAX);
  if (!passage) return;
  if (passage !== ASK.quote) {
    askAbort();
    ASK.thread = 0;
    askClear();
    askSources(null);
  }
  ASK.quote = passage;
  askDrawQuote();
  var box = $('askInput');
  if (box) box.placeholder = ASK_PLACEHOLDER;
  askTab('page');
}

function askDrawQuote() {
  var box = $('askQuote'), words = $('askQuoteText');
  if (!box || !words) return;
  words.textContent = ASK.quote;
  box.hidden = !ASK.quote;
}

function askClear() {
  var msgs = $('askMsgs');
  if (!msgs) return;
  msgs.textContent = '';
  msgs.appendChild(el('p', 'empty', ASK_EMPTY));
}

function askDown() {
  var msgs = $('askMsgs');
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function askBubble(kind, words) {
  var msgs = $('askMsgs');
  if (!msgs) return null;
  var empty = msgs.querySelector('.empty');
  if (empty) empty.remove();
  var node = el('div', 'ask-msg ' + kind);
  if (words != null) node.textContent = words;
  msgs.appendChild(node);
  askDown();
  return node;
}

function askDots() {
  var msgs = $('askMsgs');
  if (!msgs) return null;
  var empty = msgs.querySelector('.empty');
  if (empty) empty.remove();
  var node = el('div', 'ask-dots');
  node.appendChild(el('i'));
  node.appendChild(el('i'));
  node.appendChild(el('i'));
  msgs.appendChild(node);
  askDown();
  return node;
}

/* Which working notes the answer was grounded in, by name.

   It is the point of this side of the surface and not a detail: the page is
   the polished summary and the `.md` files in the same task folder are the
   reasoning behind it, so a reader is told which of them was read. */
//
// The owner's questions read the whole task and the project's background
// (`askai.notes_beside`), which is twenty and more files: the first few are
// named, which are the page's own and its task's, and the rest are one
// press away rather than a wall of paths under every answer.
function askSources(files) {
  var line = $('askSources');
  if (!line) return;
  line.textContent = '';
  if (!files || !files.length) { line.hidden = true; return; }
  var SHOWN = 3;
  line.appendChild(document.createTextNode('Grounded in ' + files.slice(0, SHOWN).join(', ')));
  if (files.length > SHOWN) {
    var more = el('button', 'ask-sources-more', 'and ' + (files.length - SHOWN) + ' more');
    more.type = 'button';
    more.title = files.slice(SHOWN).join('\n');
    more.addEventListener('click', function () {
      line.textContent = 'Grounded in ' + files.join(', ');
    });
    line.appendChild(document.createTextNode(' '));
    line.appendChild(more);
  }
  line.hidden = false;
}

/* A chat's box grows a line at a time, with no scrollbar, up to fifteen
   lines, and only then scrolls: the chat standard every chat in the
   workspace keeps (`workspace/.claude/skills/bb-chat-interface`). Fifteen,
   or as many whole lines as `room` pixels hold where the window is too
   short for fifteen, so a full box never stops half way down a line; and
   however little room there is, one line of it is the person's.

   The scrollbar is `.scrolls` and nothing else: without it the box hides
   its overflow, so a box still growing never shows one, and with it the
   bar is drawn in the box's own colours (`.composer-input` in app.css).
   Petar, 24 September 2026 (fr_224c13b2160c): "that should expand
   vertically without scroll up to a certain limit of lines then appear
   scroll", and in a colour consistent with the background.

   The fifteen is in here rather than beside it because a box can be grown
   before this part of the file has run. */
function growToLines(box, room) {
  var CHAT_LINES = 15;
  var cs = getComputedStyle(box);
  var line = parseFloat(cs.lineHeight) || 20;
  var chrome = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) +
    parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
  var lines = Math.max(1, Math.min(CHAT_LINES, Math.floor((room - chrome) / line)));
  var max = lines * line + chrome;
  box.style.height = 'auto';
  var want = box.scrollHeight;
  box.style.height = Math.min(want, max) + 'px';
  box.classList.toggle('scrolls', want > max + 1);
}

// The page's side of the column keeps the same rule as Rouh's own box
// under it, with nothing beneath the text to share the window with but its
// own line of controls.
function askGrow() {
  var box = $('askInput');
  if (!box || box.offsetParent === null) return;
  var form = $('askComposerBox');
  var below = form ? Math.max(0, form.clientHeight - box.offsetHeight) : 0;
  growToLines(box, Math.round(screenHeight() * 0.45) - below);
}

function askBusy(on) {
  ASK.busy = !!on;
  var go = $('askSend'), stop = $('askStop');
  if (go) go.disabled = ASK.busy;
  if (stop) stop.hidden = !ASK.busy;
}

function askAbort() {
  if (ASK.stop) {
    try { ASK.stop.abort(); } catch (err) {}
    ASK.stop = null;
  }
  askBusy(false);
}

/* ---------- what crosses the frame's edge ---------- */

var ASK_ASKED = 0;
var ASK_WAITING = {};

/* The words on the page, out of the frame.

   This page holds the markup it handed the frame, not what the page's own
   scripts drew from it, and every one of these pages draws itself: the
   receipts page is a table built in script and the markup it came from says
   nothing about what is on screen. So the page is asked, and it answers with
   what a reader can actually see.

   A frame that does not answer - one that has just been replaced, or a page
   whose script did not run - costs a second and a half and then the question
   goes without it. */
function askContext() {
  var frame = tasksFrame();
  if (!frame) return Promise.resolve('');
  var id = ++ASK_ASKED;
  return new Promise(function (ready) {
    var timer = setTimeout(function () {
      delete ASK_WAITING[id];
      ready('');
    }, ASK_CONTEXT_WAIT);
    ASK_WAITING[id] = function (text) { clearTimeout(timer); ready(text); };
    // Where the reader is on the page comes back with its words, so a page
    // sent again after a change opens where they were reading.
    try {
      frame.contentWindow.postMessage(
        { type: 'rouh-askai-do', what: 'context', id: id }, '*');
    } catch (err) {
      clearTimeout(timer);
      delete ASK_WAITING[id];
      ready('');
    }
  });
}

// Draw the marks again, because a passage just asked about has become one.
function askMarks() {
  var frame = tasksFrame();
  if (!frame) return;
  try {
    frame.contentWindow.postMessage({ type: 'rouh-askai-do', what: 'marks' }, '*');
  } catch (err) {}
}

/* A page in the canvas saying what the reader did in it.

   Only the canvas's own frame, the same rule the filing relay keeps: a page
   framed inside a card is served with its own drawer and never sends any of
   this, and one that did would be ignored rather than answered. */
function askFromPage(frame, m) {
  if (frame !== tasksFrame()) return;
  var what = String(m.what || '');
  if (what === 'context') {
    var ready = ASK_WAITING[m.id];
    if (!ready) return;
    delete ASK_WAITING[m.id];
    if (Number(m.y) >= 0) ASK.y = Math.round(Number(m.y) || 0);
    ready(typeof m.text === 'string' ? m.text : '');
    return;
  }
  if (!askDoc()) return;
  // The sparkle in the corner of the page, or a passage selected and Ask
  // pressed over it.
  if (what === 'open') { askTab('page'); return; }
  // The sparkle pressed by itself: it opens the conversation, and pressed
  // again while the conversation is on the screen, it puts it away.
  if (what === 'toggle') {
    if (chatOnScreen()) chatPutAway(); else askTab('page');
    return;
  }
  // The page's layer changed the page itself - a default picked among its
  // options - and asks for it again, where the reader was.
  if (what === 'reload') {
    if (Number(m.y) >= 0) ASK.y = Math.round(Number(m.y) || 0);
    askReload();
    return;
  }
  // A line of the page's history pressed: the page as it was then, or as
  // it is now.
  if (what === 'version') { askVersion(String(m.version || '')); return; }
  // A change kept as an option, or as final, from the page's history.
  if (what === 'kept') { askKept(Number(m.edit) || 0, String(m.keep || '')); return; }
  if (what === 'ask') { askCite(m.text); return; }
  // A mark on the page pressed: that topic, read again, in this column.
  if (what === 'thread') { askLoad(m.id); return; }
  // Change pressed over a passage while reading: the passage is quoted and
  // the box asks what should change. Ask AI makes the change (askai.py).
  if (what === 'change') { askCite(m.text); askChangeHere(); return; }
  // Something on the page pointed at, after Point was pressed here, or
  // while Edit is on in the page (E, or its pencil), which stays on.
  if (what === 'picked') { askPicked(m.picked, !!m.still); return; }
  // Pointing started on the page itself with Edit, or given up there with
  // Escape, Done or Stop.
  if (what === 'pointing') { askPointing(!!m.on); return; }
  // Show me, answered: whether the part a change made is on the screen (`askShowWhere`).
  if (what === 'shown') { askShown(m); return; }
}

/* ---------- asking ---------- */

/** @param {string} [said] a question a button asks, instead of the box's
 *  @param {Object<string, any>} [more] what that button sends with it */
function askAsk(said, more) {
  var box = $('askInput');
  var doc = askDoc();
  if (!box || !doc || ASK.busy) return;
  var question = said || box.value.trim();
  if (!question) return;
  if (!said) box.value = '';
  askGrow();
  askBubble('you', question);
  var spinner = askDots();
  askBusy(true);
  var control = window.AbortController ? new AbortController() : null;
  ASK.stop = control;
  var mine = doc;
  askContext().then(function (context) {
    return fetch(ASK_ROUTE + 'ask?doc=' + encodeURIComponent(doc), {
      credentials: 'same-origin',
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: control ? control.signal : undefined,
      body: JSON.stringify(Object.assign({
        doc: doc,
        threadId: ASK.thread || null,
        selectedText: ASK.quote,
        context: context,
        question: question,
        picked: ASK.picked,
        // The conversation beside it, which the exchange is written into
        // as well: the one the orb talks in (`runtime.askai_said`).
        chat: S.sessionId || '',
        title: askName(doc)
      }, more || {}))
    });
  }).then(function (r) {
    if (!r.ok || !r.body) {
      throw new Error(r.status === 401 || r.status === 403
        ? 'your sign-in has run out, so reload Rouh and ask again'
        : 'the server said ' + r.status);
    }
    return askRead(r.body, spinner);
  }).catch(function (err) {
    if (spinner) spinner.remove();
    if (control && control.signal && control.signal.aborted) return;
    askBubble('ai bad', 'That could not be answered: ' +
      ((err && err.message) || 'Rouh could not be reached') + '.');
    return 0;
  }).then(function (changed) {
    if (ASK.stop === control) ASK.stop = null;
    askBusy(false);
    // The page this landed on may have been changed under it while the
    // answer was arriving, and the marks belong to the page that is there.
    if (askDoc() !== mine) return;
    // The page on disk is not the page on the screen any more. It is sent
    // again, where the reader was, and what was pointed at is let go: its
    // place in the file has moved.
    if (changed) {
      ASK.picked = null;
      askDrawPicked();
      askPatch(ASK.patches);
    } else askMarks();
    var dot = $('chatTabPageDot');
    if (dot && ASK.tab !== 'page') dot.hidden = false;
  });
}

// The answer, as it is written. The events are askai.py's own, and the same
// ones askai.js reads, so a page being read by somebody who is not the owner
// and this column are answered by one route in one shape.
function askRead(body, spinner) {
  var reader = body.getReader(), dec = new TextDecoder(), buf = '';
  var target = null, said = '', changed = 0, wrote = false;
  ASK.patches = [];
  function seen(ev) {
    if (ev.type === 'thread') { ASK.thread = Number(ev.threadId) || 0; return; }
    if (ev.type === 'sources') { askSources(ev.files); return; }
    if (ev.type === 'done') return;
    if (spinner) { spinner.remove(); spinner = null; }
    if (ev.type === 'edited') {
      askEditLine(ev.edit, ev.summary, false, '', !!ev.keepable, !!ev.show);
      changed++;
      ASK.patches.push(ev.patch || null);
      target = null;
      return;
    }
    if (ev.type === 'tool') {
      askBubble('ai tool', (ev.name || 'Tool') + (ev.detail ? ' - ' + ev.detail : ''));
      target = null;
      return;
    }
    if (ev.type === 'text') {
      if (!target) { target = askBubble('ai'); said = ''; }
      wrote = true;
      said += ev.text || '';
      target.innerHTML = renderMarkdown(said);
      // Over the whole column: a search between two pieces of one answer
      // puts its numbers in one bubble and its list in the next.
      footnotes($('askMsgs') || target);
      askDown();
      return;
    }
    if (ev.type === 'error') {
      askBubble('ai bad', ev.message || 'That could not be answered.');
      target = null;
      // Nothing was answered, so nothing was grounded in the files the
      // line under the answer would name: a page too big for the model is
      // told so, not told what its answer was grounded in.
      if (!wrote && !changed) askSources(null);
    }
  }
  return (function pump() {
    return reader.read().then(function (got) {
      if (got.done) { if (spinner) { spinner.remove(); spinner = null; } return changed; }
      buf += dec.decode(got.value, { stream: true });
      var parts = buf.split('\n\n');
      buf = parts.pop();
      parts.forEach(function (chunk) {
        var line = chunk.split('\n').filter(function (l) {
          return l.indexOf('data:') === 0;
        })[0];
        if (!line) return;
        var ev = safeParse(line.slice(5).trim());
        if (ev && ev.type) seen(ev);
      });
      return pump();
    });
  })();
}

/* Everything asked about this page before, inside this surface.

   Petar: "you also have a history of topics, but I wouldn't want those to be
   a separate chat the way our current system is. It would have too many
   chats for the same project, so I'd like this model to remain separate."

   So they are rows of their own (`askai_threads`), read here, and nothing
   about a page anybody asked six questions about ever appears in the list of
   chats. */
function askTopicList() {
  var doc = askDoc();
  if (!doc) return;
  askAbort();
  ASK.thread = 0;
  // The list is not a topic, so the passage goes with the topic it belonged
  // to: typing a question while looking at the list is a question about the
  // page, not about whatever was quoted before it was opened.
  ASK.quote = '';
  askDrawQuote();
  askClear();
  askSources(null);
  askTab('page');
  var msgs = $('askMsgs');
  msgs.textContent = '';
  var wrap = el('div', 'ask-topics');
  wrap.appendChild(el('h3', null, 'Asked about this page'));
  msgs.appendChild(wrap);
  fetch(ASK_ROUTE + 'threads?doc=' + encodeURIComponent(doc), { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      if (askDoc() !== doc) return;
      if (!Array.isArray(rows) || !rows.length) {
        wrap.appendChild(el('p', 'ask-topic-m',
          'Nothing yet. Select a passage on the page, or just ask.'));
        return;
      }
      rows.forEach(function (t) {
        ASK.meta[t.id] = t;
        var row = el('button', 'ask-topic');
        row.type = 'button';
        row.appendChild(el('span', 'ask-topic-q',
          t.first_question || t.title || ('Topic ' + t.id)));
        row.appendChild(el('span', 'ask-topic-m',
          (t.msg_count || 0) + (t.msg_count === 1 ? ' message' : ' messages') +
          (t.selected_text ? ' - about a passage' : '')));
        row.addEventListener('click', function () { askLoad(t.id); });
        wrap.appendChild(row);
      });
    })
    .catch(function () {
      wrap.appendChild(el('p', 'ask-topic-m', 'Those could not be read.'));
    });
}

// One topic, read again. Reached from the list above and from a mark pressed
// on the page itself, which is the same topic seen from the other end.
function askLoad(id) {
  var doc = askDoc();
  var thread = Number(id) || 0;
  if (!doc || !thread) return;
  askAbort();
  ASK.thread = thread;
  var meta = ASK.meta[thread];
  ASK.quote = (meta && meta.selected_text) || '';
  askDrawQuote();
  askClear();
  askSources(null);
  askTab('page');
  var msgs = $('askMsgs');
  msgs.textContent = '';
  fetch(ASK_ROUTE + 'threads/' + thread + '?doc=' + encodeURIComponent(doc),
        { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (rows) {
      if (askDoc() !== doc || ASK.thread !== thread) return;
      if (!Array.isArray(rows) || !rows.length) {
        askBubble('ai bad', 'That topic could not be read.');
        return;
      }
      rows.forEach(function (m) {
        if (m.role === 'user') askBubble('you', m.content);
        else if (m.role === 'edit') askEditLine(m.edit, m.content, !!m.undone, m.keep || '',
                                                !!m.keepable, !!m.show);
        else {
          var node = askBubble('ai');
          if (node) { node.innerHTML = renderMarkdown(m.content || ''); footnotes(node); }
        }
      });
      if (!ASK.quote) {
        for (var i = 0; i < rows.length; i++) {
          if (rows[i].selected_text) { ASK.quote = rows[i].selected_text; break; }
        }
        askDrawQuote();
      }
    })
    .catch(function () { askBubble('ai bad', 'That topic could not be read.'); });
}

/* ---------- reading it, and changing it ----------

   Petar, 23 September 2026: "sometimes I like to ask questions about things,
   but sometimes I read this and decide that it needs to be modified.
   Therefore, I need to be able to modify it."

   And on 24 September (fr_edecde0ad6e6): "Now I want Ask AI to also be able
   to edit that content. I would say: remove that title, change the color,
   or add some functionality, and then it should be able to do it... for
   editing, pointing to a section might be a better approach."

   Until then a change was carried over to the Rouh tab and asked there.
   Now Ask AI makes it: the page's own source is in front of it, and it
   changes the file and says what it did (askai.py, "Changing the page").
   A question is answered and a request is carried out, from the one box,
   and the page is sent again the moment it has changed. Anything bigger
   than the page it says it cannot do, and the Rouh tab is beside it for
   that.

   Two ways to say what "this" is. A passage selected and Change pressed on
   the bar over it, which quotes it; or Point, here, which lets the reader
   point at the part of the page itself - a heading, a box, a picture - and
   hands over exactly which element in the file it is (`pages.with_marks`).
   Every change is a line of its own in the conversation with Undo on it. */

// The passage quoted, and the box asking what should change about it.
function askChangeHere() {
  askTab('page');
  var box = $('askInput');
  if (!box) return;
  box.placeholder = ASK_CHANGE_HERE;
  setTimeout(function () { try { box.focus(); } catch (err) {} }, 0);
}

function askToFrame(what) {
  var frame = tasksFrame();
  if (!frame) return false;
  try { frame.contentWindow.postMessage({ type: 'rouh-askai-do', what: what }, '*'); }
  catch (err) { return false; }
  return true;
}

// Whether the page is waiting for the reader to point, as the button says it.
function askPointing(on) {
  ASK.pointing = !!on;
  var btn = $('askPoint');
  if (!btn) return;
  btn.classList.toggle('on', ASK.pointing);
  btn.setAttribute('aria-pressed', ASK.pointing ? 'true' : 'false');
}

// Point, pressed: the page starts pointing, and pressed again it stops.
function askPoint() {
  if (!askDoc()) return;
  if (ASK.pointing) { askToFrame('unpoint'); askPointing(false); return; }
  if (!askToFrame('point')) return;
  askPointing(true);
  // On a phone the page is the other pane: pointing is done on it, and the
  // pick brings the box back (`askChangeHere`, through `askTab`).
  if (narrow()) setPane('canvas');
}

// Something on the page, pointed at. It is what the next question is about.
// `still` is Edit in the page, which goes on pointing after a pick.
function askPicked(said, still) {
  askPointing(!!still);
  if (!said || typeof said !== 'object' || !said.tag) return;
  ASK.picked = {
    at: Number(said.at) || 0,
    tag: String(said.tag).slice(0, 40),
    text: String(said.text || '').slice(0, 300),
    label: String(said.label || said.tag).slice(0, 80),
    version: String(said.version || '').slice(0, 40)
  };
  askDrawPicked();
  askChangeHere();
}

function askDrawPicked() {
  var box = $('askPicked'), what = $('askPickedWhat'), words = $('askPickedText');
  if (!box) return;
  var p = ASK.picked;
  box.hidden = !p;
  if (what) what.textContent = p ? p.label : '';
  if (words) words.textContent = p ? p.text : '';
  var input = $('askInput');
  if (input && !p && !ASK.quote) input.placeholder = ASK_PLACEHOLDER;
}

/* A change made to the page, as a line of its own, with Undo on it. The
   same line for a change just made and for one read again in a topic. */
function askEditLine(id, summary, undone, keep, keepable, show) {
  var line = askBubble('ai edit' + (undone ? ' undone' : ''));
  if (!line) return null;
  line.setAttribute('data-edit', String(Number(id) || 0));
  line.appendChild(el('span', 'ask-edit-w', 'Changed the page: ' + (summary || 'done')));
  if (!undone && Number(id) > 0) {
    // Show me where (night 24, `rouh/askai_show.py`, switch `askai_show`): that part of the
    // page brought into view and lit for a moment, kept together with Undo when the line wraps.
    var acts = show ? el('span', 'ask-edit-acts') : line;
    if (show) {
      var where = el('button', 'ctl small ask-show', 'Show me');
      where.type = 'button';
      where.title = 'Bring the part of the page this changed into view';
      where.addEventListener('click', function () { askShowWhere(Number(id), line, where); });
      acts.appendChild(where);
      line.appendChild(acts);
    }
    var undo = el('button', 'ctl small', 'Undo');
    undo.type = 'button';
    undo.title = 'Put the page back as it was before this change';
    undo.addEventListener('click', function () { askUndo(Number(id), line, undo); });
    acts.appendChild(undo);
  }
  askKeepRow(line, Number(id) || 0, keep || '', !!keepable && !undone);
  askDown();
  return line;
}

/* Whether the change stays as it is, or the version before it is kept too,
   as an option anybody reading the page can switch to.

   Petar, 24 September 2026 (fr_b91369ea7ba2): "for every change, I have to
   decide whether I want to keep it in the options... I may decide that I
   don't need that. It's an optional thing, but each change essentially
   needs to ask me." So every change asks, under its own line, and no is one
   press the same size as yes. Pressing nothing is no: the change stands and
   nothing is offered, and the page's History still asks. A change too wide
   to swap as one part of the page - its whole body - is not asked about. */
function askKeepRow(line, id, keep, keepable) {
  var was = line.querySelector('.ask-keep');
  if (was) was.remove();
  if (keep === 'option') {
    line.appendChild(el('span', 'ask-keep kept', 'Kept both versions as options on the page'));
    return;
  }
  if (keep === 'final' || !keepable || !(id > 0)) return;
  var row = el('span', 'ask-keep');
  row.appendChild(el('span', 'ask-keep-q', 'Keep both versions as options?'));
  var yes = el('button', 'ctl small ask-keep-yes', 'Keep both');
  yes.type = 'button';
  yes.title = 'Keep this change and the version before it, so people can switch between them';
  var no = el('button', 'ctl small', 'No, final');
  no.type = 'button';
  no.title = 'Keep this change as it is, with no switch';
  yes.addEventListener('click', function () { askKeep(id, 'option', line, yes, no); });
  no.addEventListener('click', function () { askKeep(id, 'final', line, yes, no); });
  row.appendChild(yes);
  row.appendChild(no);
  line.appendChild(row);
}

function askKeep(id, choice, line, yes, no) {
  var doc = askDoc();
  if (!doc) return;
  yes.disabled = no.disabled = true;
  fetch(ASK_ROUTE + 'keep?doc=' + encodeURIComponent(doc), {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc: doc, edit: id, keep: choice })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      return { ok: r.ok, said: j };
    });
  }).catch(function () {
    return { ok: false, said: { error: 'Rouh could not be reached.' } };
  }).then(function (got) {
    if (!got.ok || !got.said || got.said.error) {
      yes.disabled = no.disabled = false;
      askBubble('ai bad', (got.said && got.said.error) || 'That could not be saved.');
      return;
    }
    askKeepRow(line, id, got.said.keep, false);
    // The page draws its options itself, over the page, so it is handed
    // them rather than sent again.
    if (askDoc() === doc && got.said.options) askToFrameSay({ what: 'options', options: got.said.options });
  });
}

// The same decision, made on the page's own History instead: the line for
// that change here says so too, if it is on the screen.
function askKept(id, keep) {
  var msgs = $('askMsgs');
  var line = id > 0 && msgs && msgs.querySelector('.ask-msg.edit[data-edit="' + id + '"]');
  if (line) askKeepRow(line, id, keep, false);
}

function askToFrameSay(said) {
  var frame = tasksFrame();
  if (!frame) return;
  said.type = 'rouh-askai-do';
  try { frame.contentWindow.postMessage(said, '*'); } catch (err) {}
}

/* Show me: where the change is, from Rouh (`rouh/askai_show.py`), and the page told to bring it
   into view and light it (`askai.js`, "show"). What the page found comes back as `shown`. */
function askShowWhere(id, line, button) {
  var doc = askDoc();
  var frame = tasksFrame();
  if (!doc || !frame) return;
  button.disabled = true;
  askShowSaid(line, '');
  fetch(ASK_ROUTE + 'where?doc=' + encodeURIComponent(doc), {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc: doc, edit: id })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      return { ok: r.ok, said: j };
    });
  }).catch(function () {
    return { ok: false, said: { error: 'Rouh could not be reached.' } };
  }).then(function (got) {
    button.disabled = false;
    if (!got.ok || !got.said || got.said.error) {
      askShowSaid(line, (got.said && got.said.error) || 'Where that change is could not be read.');
      return;
    }
    ASK.showing = { line: line, heading: String(got.said.heading || '') };
    // On a phone the page is the other pane: it is brought on screen first (`askShown` comes
    // back to the conversation when there is nothing on the page to see).
    if (narrow()) setPane('canvas');
    try {
      frame.contentWindow.postMessage({ type: 'rouh-askai-do', what: 'show', tag: got.said.tag || '',
        text: got.said.text || '', nth: Number(got.said.nth) || 0, heading: got.said.heading || '' }, '*');
    } catch (err) {
      askShowSaid(line, 'The page could not be reached.');
    }
  });
}

/* What the page said it found: nothing to say when it is on the screen; otherwise where it is. */
function askShown(m) {
  var at = ASK.showing;
  if (!at) return;
  ASK.showing = null;
  if (m.found && !m.hidden) { askShowSaid(at.line, ''); return; }
  if (narrow()) setPane('chat');
  var under = at.heading ? ' It is under \u201c' + at.heading + '\u201d' : '';
  askShowSaid(at.line, m.found
    ? 'That part is not showing on the page now.' + (under ? under + ': open that part of the page.' : '')
    : 'That part could not be found on the page as it is drawn now.' + (under ? under + '.' : ''));
}

function askShowSaid(line, words) {
  var was = line.querySelector('.ask-show-said');
  if (!words) { if (was) was.remove(); return; }
  if (!was) { was = el('span', 'ask-show-said', ''); line.appendChild(was); }
  was.textContent = words;
}

function askUndo(id, line, button) {
  var doc = askDoc();
  if (!doc) return;
  button.disabled = true;
  fetch(ASK_ROUTE + 'undo?doc=' + encodeURIComponent(doc), {
    credentials: 'same-origin',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc: doc, edit: id })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (j) {
      return { ok: r.ok, said: j };
    });
  }).catch(function () {
    return { ok: false, said: { error: 'Rouh could not be reached.' } };
  }).then(function (got) {
    if (!got.ok || !got.said || got.said.error) {
      button.disabled = false;
      askBubble('ai bad', (got.said && got.said.error) || 'That change could not be put back.');
      return;
    }
    line.classList.add('undone');
    button.remove();
    // Show me goes with it: the change is no longer on the page (`askShowWhere`).
    var shown = line.querySelector('.ask-edit-acts');
    if (shown) shown.remove();
    askShowSaid(line, '');
    var keep = line.querySelector('.ask-keep');
    if (keep) keep.remove();
    if (askDoc() === doc) askPatch([got.said.patch]);
  });
}

/* One line of the page's history, opened: the page as it was then, in the
   same frame, read only, with a bar across it saying which moment it is and
   the way back (`rouh/pagehistory.py`). Nothing else on the screen moves:
   the breadcrumb, the address and this column are still about the page,
   and asking about it, or changing it, is about the page as it is now,
   which is where the next change sends the frame back to. An empty one is
   the page as it is now. */
function askVersion(v) {
  var frame = tasksFrame();
  if (!frame || !CANVAS.at) return;
  var u = new URL(CANVAS.at, location.href);
  u.searchParams.delete('y');
  if (/^([ebu][0-9]{1,18}|g[0-9a-f]{40})$/.test(v)) u.searchParams.set('version', v);
  else u.searchParams.delete('version');
  frameLoad(frame, u.pathname + u.search);
}

/* The page again, in the same frame, where the reader was reading. The
   conversation beside it stays as it is: it is the same page, changed. */
// Changes Ask AI made, onto the page where the reader is, rather than the
// page sent again (`patchPage` in askai.js, fr_65039fdac5a2): a page that
// keeps which of its own pages it is showing went back to its start after
// every change. The page asks to be sent again itself when one of them
// cannot be made on it, and so does this, when one never came.
function askPatch(patches) {
  var frame = tasksFrame();
  if (!frame) return;
  if (!patches.length || patches.some(function (p) { return !p; })) { askReload(); return; }
  try {
    frame.contentWindow.postMessage({ type: 'rouh-askai-do', what: 'patch', patches: patches }, '*');
  } catch (err) { askReload(); }
}

function askReload() {
  var frame = tasksFrame();
  if (!frame || !CANVAS.at) return;
  // The page that comes back is not pointing at anything, whatever Edit
  // was doing on the one it replaces.
  askPointing(false);
  var u = new URL(CANVAS.at, location.href);
  if (ASK.y > 0) u.searchParams.set('y', String(ASK.y));
  frameLoad(frame, u.pathname + u.search);
}

/* ---------- the controls ---------- */

/* What changed (gene since_read, version 2, `rouh/since_read.py`).

   Petar, 27 October 2026, of version 1, a question Ask AI could answer: "I
   would never think of writing that, I am blind. What maybe would work is to
   track if anything has changed since I last saw it, and if yes, then show me
   a button that would generate those changes. I done want this generation of
   summary to happen in advance."

   So, as Google Docs says "See new changes": every time a page is opened on
   the canvas the server keeps the visit with the page's words, and says
   whether they changed since the visit before. Only then is What changed on
   the bar, and only pressing it asks - this page's Ask AI, beside it, with
   what was added and taken out since. Pressed, it goes: that visit has been
   told. Nothing is asked of a model before the press. */
var SEEN = { doc: '', asked: 0, /** @type {any} */ state: null };

function seenTouch(doc) {
  if (doc === SEEN.doc) return;
  SEEN.doc = doc;
  SEEN.state = null;
  seenDraw();
  if (!doc) return;
  var n = ++SEEN.asked;
  fetch('/api/since-read?doc=' + encodeURIComponent(doc), { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (got) {
      if (n !== SEEN.asked || doc !== SEEN.doc) return;
      SEEN.state = got;
      seenDraw();
    });
}

function seenDraw() {
  var button = $('whatChangedBtn');
  if (!button) return;
  var s = SEEN.state || {};
  button.hidden = !(s.on && s.changed && SEEN.doc && SEEN.doc === askDoc());
  if (!button.hidden) {
    button.title = 'This page changed since you last saw it' + (s.when ? ', on ' + s.when : '') +
      '. Press to hear what changed.';
  }
}

function seenPress() {
  var doc = askDoc();
  if (!doc || doc !== SEEN.doc || ASK.busy) return;
  SEEN.state = null;
  seenDraw();
  askAbort();
  ASK.thread = 0;
  ASK.quote = '';
  askDrawQuote();
  askClear();
  askSources(null);
  askTab('page');
  askAsk('What changed since I last saw this page?', { since_read: true });
}

function askInit() {
  var page = $('chatTabPage'), rouh = $('chatTabRouh'), form = $('askComposer');
  if (!page || !rouh || !form) return;
  page.addEventListener('click', function () { askTab('page'); });
  rouh.addEventListener('click', function () { askRouhHere(); askTab('rouh'); });
  $('askTopics').addEventListener('click', askTopicList);
  $('askNew').addEventListener('click', function () {
    askAbort();
    ASK.thread = 0;
    ASK.quote = '';
    askDrawQuote();
    askClear();
    askSources(null);
    askTab('page');
  });
  $('askQuoteX').addEventListener('click', function () {
    ASK.quote = '';
    askDrawQuote();
    askDrawPicked();
    var box = $('askInput');
    if (box) box.focus();
  });
  $('askStop').addEventListener('click', askAbort);
  $('whatChangedBtn').addEventListener('click', seenPress);
  $('askPoint').addEventListener('click', askPoint);
  // Escape while the page waits to be pointed at stops the pointing and
  // closes nothing (`somethingElseIsOver` steps aside for it).
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !ASK.pointing) return;
    e.preventDefault();
    askToFrame('unpoint');
    askPointing(false);
  }, false);
  $('askPickedX').addEventListener('click', function () {
    ASK.picked = null;
    askToFrame('unpick');
    askDrawPicked();
    var box = $('askInput');
    if (box) box.focus();
  });
  form.addEventListener('submit', function (e) { e.preventDefault(); askAsk(); });
  var box = $('askInput');
  box.placeholder = ASK_PLACEHOLDER;
  $('askSend').title = 'Ask (' + sendKeys() + ')';
  box.addEventListener('input', askGrow);
  // Enter is a new line here too, and Ctrl+Enter asks (`isSendKey`).
  box.addEventListener('keydown', function (e) {
    if (isSendKey(e)) {
      e.preventDefault();
      askAsk();
    }
  });
  // Anywhere on the block means "put the cursor back in the text", which is
  // what the conversation's own box does.
  $('askComposerBox').addEventListener('mousedown', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('button, select, a, textarea, input, label')) return;
    e.preventDefault();
    box.focus();
  });
  window.addEventListener('resize', askGrow);
  askShows();
}

askInit();

// --- the breadcrumb ---

/* The levels, in order, exactly as the bar draws them. Each one says how to
   go there and how to list its siblings; a level with no siblings worth
   listing simply has no `kind`.

   The last entry is the page's own title, which is words rather than a
   control: there is nowhere below it to go. */
function crumbLevels() {
  /** @type {Array<{home?: boolean, kind?: string, num?: string, name?: string, on?: boolean, go?: () => void, href?: string, words?: string}>} */
  var out = [{ home: true, name: CRUMB_HOME, go: tasksOpen, href: ADDR_BROWSER }];
  if (!CANVAS.task) return out;
  var task = CANVAS.taskData && CANVAS.taskData.rel === CANVAS.task ? CANVAS.taskData : null;
  out.push({
    kind: 'task',
    num: task && task.number != null ? 'Task ' + task.number : '',
    name: task ? task.name : CANVAS.task.split('/').pop(),
    on: !CANVAS.step,
    go: function () { canvasTask(CANVAS.task); },
    href: addrOfFolder(CANVAS.task)
  });
  if (!CANVAS.step) {
    // One of the task's notes or folders, read on its page: named after the
    // task, the same way a page is named after its step below, so the bar
    // says what the address says.
    if (CANVAS.title && canvasDoc()) out.push({ words: CANVAS.title });
    return out;
  }
  var row = crumbStepRow();
  out.push({
    kind: 'step',
    num: row ? row.number : CANVAS.step.split('/').pop().split('.')[0],
    // A step with no folder left has no line in the task's steps, which are
    // read off the disk, but on its own page the page has named it: a row
    // whose folder went (fr_bb3ff32f17b9) read "75-02.brainstorm-x-ray".
    name: row ? row.title
      : (CANVAS.at === taskUrl(CANVAS.step) && CANVAS.title) || CANVAS.step.split('/').pop(),
    on: true,
    go: (function (rel) { return function () { canvasStepPage(rel); }; }(CANVAS.step)),
    href: addrOf('task', CANVAS.step)
  });
  // The page's own title, read out of the markup as it arrived. Left out
  // when it would only repeat the step above it, and on the step's own page,
  // where the step is the whole of what is shown.
  if (CANVAS.title && CANVAS.title !== (row && row.title)
      && CANVAS.at !== taskUrl(CANVAS.step)) out.push({ words: CANVAS.title });
  return out;
}

function crumbStepRow() {
  var task = CANVAS.taskData;
  if (!task || task.rel !== CANVAS.task || !task.steps) return null;
  for (var i = 0; i < task.steps.length; i++) {
    if (task.steps[i].rel === CANVAS.step) return task.steps[i];
  }
  return null;
}

function drawCrumb() {
  // The conversation column's two tabs say what is loaded as much as this
  // row does, so they are drawn from the same one place. Every way of
  // changing what the canvas holds already comes through here, which is why
  // it is here and not repeated at each of them.
  askShows();
  var bar = $('canvasCrumb');
  if (!bar) return;
  // The chevron a menu was dropped from is about to be replaced, so the menu
  // would be left hanging under a bar that no longer says the same thing.
  crumbMenuClose();
  bar.textContent = '';
  var strip = $('canvasBar'), shut = $('tasksClose');
  if (shut) shut.hidden = !tasksViewing();
  /* The whole row, not merely what is in it, belongs to what is loaded.

     With nothing loaded there is no breadcrumb to draw, so the row goes:
     no bar, no hairline and no height at the top of a bare canvas. It used
     to stay behind holding a single "All tasks" chip, on the reasoning that
     the navigation column closes and the way in must survive it. The
     sidebar is that way in now, and a strip across the canvas that says one
     word is not worth the line it draws. */
  if (strip) strip.hidden = !tasksViewing();
  // Share belongs to the page that is loaded, not to the row, so it is
  // settled on the way past whether or not there is a breadcrumb to draw.
  shareTouch();
  if (!tasksViewing()) return;

  var levels = crumbLevels();
  for (var i = 0; i < levels.length; i++) {
    if (i) bar.appendChild(el('span', 'tcrumb-sep', '/'));
    bar.appendChild(levels[i].words ? el('span', 'tcrumb-title', levels[i].words)
                                    : crumbChip(levels[i]));
  }
  // Scrolled so the deepest level starts at the left edge, which is where
  // the reader is. To the end and no further: a chip cut down the middle
  // leaves its chevron sitting on its own at the edge of the row, reading as
  // a control belonging to nothing. It only scrolls at all when the levels
  // are wider than the row, which is a phone.
  var chips = bar.querySelectorAll('.tcrumb-chip');
  var deepest = chips.length ? chips[chips.length - 1] : null;
  if (deepest) {
    bar.scrollLeft += deepest.getBoundingClientRect().left - bar.getBoundingClientRect().left;
  }
  // A level scrolled half out of the row fades into the edge rather than
  // ending in a hard cut: a chevron on its own at the edge of the screen
  // reads as a control belonging to nothing. Only when there really is more
  // than fits, or the fade would eat the first level for no reason.
  bar.classList.toggle('over', bar.scrollWidth > bar.clientWidth + 1);
  // What the levels need to say their names and list their siblings. Asked
  // for once each and kept, so climbing and stepping sideways fetch nothing.
  crumbFill();
}

function crumbChip(level) {
  var chip = el('span', 'tcrumb-chip' + (level.home ? ' home' : '') + (level.on ? ' on' : ''));
  // A link to the level's own address, so Cmd-click and Open link in new
  // tab take it to a tab of its own (`linkTo`).
  var go = linkTo(el('a', 'tcrumb-go'), level.href || ADDR_BROWSER);
  if (level.home) {
    go.appendChild(crumbIcon('M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z', 13));
  }
  if (level.num) go.appendChild(el('span', 'tcrumb-n', level.num));
  if (level.num && level.name) go.appendChild(el('span', 'tcrumb-d', '·'));
  if (level.name) go.appendChild(el('span', 'tcrumb-t', level.name));
  go.title = level.home ? 'Every task in your workspace' : 'Go to ' + level.name;
  if (level.on) go.setAttribute('aria-current', 'true');
  go.addEventListener('click', level.go);
  chip.appendChild(go);
  if (level.kind) {
    var more = el('button', 'tcrumb-more');
    more.type = 'button';
    more.setAttribute('aria-haspopup', 'true');
    more.setAttribute('aria-expanded', 'false');
    more.title = level.kind === 'task' ? 'Another task' : 'Another step of this task';
    more.setAttribute('aria-label', more.title);
    more.appendChild(crumbIcon('M6 9l6 6 6-6', 12));
    more.addEventListener('click', function (e) {
      e.stopPropagation();
      crumbMenu(more, level.kind);
    });
    chip.appendChild(more);
  }
  return chip;
}

// One stroked path in a box, which is every glyph on this bar.
function crumbIcon(path, size) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  var d = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  d.setAttribute('d', path);
  svg.appendChild(d);
  return svg;
}

// --- what the breadcrumb knows ---
//
// Two lists, each read off the workspace once and kept: every task, which is
// what the task level's siblings are, and the steps of the task being looked
// at, which is what the step level's are. They are also where the levels get
// their names: an address alone would read "12.the-rail".

var TASKS = { all: [], asked: false };

function crumbFill() {
  if (!TASKS.asked) {
    TASKS.asked = true;
    canvasGet('/api/workspace/index').then(function (got) {
      if (!got) return;
      TASKS.all = Array.isArray(got.tasks) ? got.tasks : [];
      if (tasksViewing()) drawCrumb();
    });
  }
  var want = CANVAS.task;
  if (!want || (CANVAS.taskData && CANVAS.taskData.rel === want)) return;
  // A project's own page opens on the canvas exactly the way a task's does,
  // and a project has no steps: `/api/workspace/task` refuses it, rightly,
  // and the 400 was an error in the console for a question that never had
  // an answer. The task level is a task only when its last part is a
  // numbered folder; anything else has nothing under it to ask about.
  if (!TASK_NAME.test(want.split('/').pop() || '')) return;
  canvasGet('/api/workspace/task?rel=' + encodeURIComponent(want)).then(function (got) {
    if (!got || got.error || CANVAS.task !== want) return;
    CANVAS.taskData = got;
    if (tasksViewing()) drawCrumb();
  });
}

var CRUMB_MENU = { open: null };

function crumbMenuClose() {
  var menu = $('tcrumbMenu');
  if (menu) menu.hidden = true;
  if (CRUMB_MENU.open) {
    try { CRUMB_MENU.open.setAttribute('aria-expanded', 'false'); } catch (err) {}
    CRUMB_MENU.open = null;
  }
}

// The siblings of one level, under the chevron that asked for them. Fixed to
// the window, because the bar clips what overflows it.
function crumbMenu(button, kind) {
  if (CRUMB_MENU.open === button) { crumbMenuClose(); return; }
  crumbMenuClose();
  var menu = $('tcrumbMenu');
  if (!menu) {
    menu = el('div', 'tcrumb-menu');
    menu.id = 'tcrumbMenu';
    menu.setAttribute('role', 'menu');
    document.body.appendChild(menu);
  }
  menu.textContent = '';
  var rows = kind === 'task' ? TASKS.all
    : (CANVAS.taskData && CANVAS.taskData.rel === CANVAS.task && CANVAS.taskData.steps) || [];
  // Never an archived one, unless it is the one being read: it is in its
  // task's Archive, at the bottom of the task's page (fr_0a87db94c515).
  rows = rows.filter(function (row) {
    return !row.archived || row.rel === (kind === 'task' ? CANVAS.task : CANVAS.step);
  });
  if (!rows.length) {
    menu.appendChild(el('p', 'empty', kind === 'task'
      ? 'The workspace has no tasks to move to.'
      : 'This task has no other steps.'));
  }
  for (var i = 0; i < rows.length; i++) menu.appendChild(crumbMenuRow(rows[i], kind));
  menu.hidden = false;
  var box = button.getBoundingClientRect();
  menu.style.top = Math.round(box.bottom + 5) + 'px';
  menu.style.left = Math.round(Math.max(8,
    Math.min(box.left - 60, window.innerWidth - menu.offsetWidth - 8))) + 'px';
  button.setAttribute('aria-expanded', 'true');
  CRUMB_MENU.open = button;
}

function crumbMenuRow(row, kind) {
  var item = linkTo(el('a', null), addrOf('task', row.rel));
  item.setAttribute('role', 'menuitem');
  var here = kind === 'task' ? row.rel === CANVAS.task : row.rel === CANVAS.step;
  if (here) item.setAttribute('aria-current', 'true');
  var num = kind === 'task' ? (row.number != null ? String(row.number) : '') : row.number;
  if (num) item.appendChild(el('span', 'tcrumb-n', num));
  item.appendChild(el('span', 'tcrumb-t', kind === 'task' ? row.name : row.title));
  item.addEventListener('click', function () {
    crumbMenuClose();
    if (kind === 'task') canvasTask(row.rel);
    else canvasStepPage(row.rel);
  });
  return item;
}

document.addEventListener('click', function (e) {
  if (!CRUMB_MENU.open) return;
  var t = /** @type {HTMLElement} */ (e.target);
  if (t && t.closest && t.closest('.tcrumb-menu, .tcrumb-more')) return;
  crumbMenuClose();
});

// --- what the rest of the page asks of all this ---

// Demo mode approved or took back something (app/demo.js): the page on the canvas is drawn again
// from the server, which now shows it or blurs it.
window.rouhCanvasRedraw = function () { if (CANVAS.at) canvasLoad(CANVAS.at); };

// A card has just been written into a task as a step. Only the task being
// looked at is read again: filing into task 30 while the reader is on task 7
// changes nothing they can see.
function cardWasFiled(rel) {
  if (!tasksViewing() || !CANVAS.task || stepTask(rel) !== CANVAS.task) return;
  CANVAS.taskData = null;
  if (CANVAS.at) canvasLoad(CANVAS.at); else drawCrumb();
}

/* What the model asked for, over the socket (PROTOCOL.md, `canvas`).

   Two modes and nothing else. A task or a step named with them is not a
   third mode: it is what to load, and it is loaded the same way a click
   loads it. */
/** @param {import('./protocol').FromServer<'canvas'>} m */
function canvasMessage(m) {
  var mode = String(m && m.mode || '');
  if (CANVAS_MODES.indexOf(mode) < 0) return;
  if (mode === 'now') return goNow();
  // `stay` is a finished job's page, opened beside the conversation it
  // reports in (`Lander._open`). Loading a page moves the conversation to
  // its task's, and Rouh's words about the page are said in this one, so
  // this one stays beside it the way it does for a page an address opened.
  if (m.page && m.stay) {
    ADDR.chatNamed = true;
    try { canvasLoad(pageUrl(m.page)); } finally { ADDR.chatNamed = false; }
    return;
  }
  if (m.page) return canvasLoad(pageUrl(m.page));
  if (m.step) return canvasStep(m.step);
  if (m.task) return canvasTask(m.task);
  tasksOpen();
}

// The keyboard while the tasks view has it but the frame does not: the
// reader is on the breadcrumb, or the page inside has not arrived yet.
// Rouh's own keys are acted on here; every key the page inside owns is
// sent down to it, and the frame takes the keyboard with it, so the next one
// goes straight there.
$('tasksView').addEventListener('keydown', function (e) {
  if (!tasksViewing() || e.defaultPrevented || e.ctrlKey) return;
  if (e.key === 'Escape') { e.preventDefault(); tasksUp(); return; }
  if (e.key === 'Backspace' || (e.key === 'ArrowLeft' && (e.altKey || e.metaKey))) {
    e.preventDefault();
    tasksUp();
    return;
  }
  // A button or a link in the bar keeps its own Enter and its own space.
  if (e.target && e.target.closest && e.target.closest('button, a, input, textarea, select')) return;
  if (BROWSE_KEYS.indexOf(e.key) < 0 || e.altKey || e.metaKey) return;
  e.preventDefault();
  var frame = tasksFrame();
  if (!frame || !frame.contentWindow) return;
  try {
    frame.contentWindow.postMessage({
      type: 'rouh-frame-key', key: e.key,
      alt: !!e.altKey, ctrl: !!e.ctrlKey, meta: !!e.metaKey, shift: !!e.shiftKey
    }, '*');
  } catch (err) {}
  tasksFocus();
});

/* The Task browser row, and there are three of them: one under each list's
   New, because every project and every task at once is not one of the three
   lists and is the way into all of them. They are wired by class rather than
   by id for that reason, the way the navigation's other repeated row was.

   `tasksBrowse` and not `tasksOpen`, because a press from the navigation
   takes both columns. */
(function () {
  var rows = document.querySelectorAll('.sb-browse'), i;
  for (i = 0; i < rows.length; i++) {
    rows[i].addEventListener('click', tasksBrowse);
  }
})();
$('tasksClose').addEventListener('click', tasksClose);
// The cross on a card being read by itself. The same one control every layer
// has, and Escape does the same thing (`LAYER_CLOSE`).
$('cardViewClose').addEventListener('click', function () { cardViewClose(); });
$('drawnClose').addEventListener('click', function () { drawnClose(); });

/* ---------- sharing a page ----------
 *
 * One page of the workspace, made readable by anybody who has its link: no
 * account, no sign-in, no password. `rouh/sharing.py` is the store and says
 * what is shared and what is not; this is the whole of the browser's half.
 *
 * Where the button is, and why. Petar, 23 September 2026: "I also need a
 * share button, and since that's going to be unified and always the same, it
 * probably needs to go in the top bar where the breadcrumb is." So it is in
 * the canvas bar, at the end of the breadcrumb's own line, and it is in that
 * one place whatever page is loaded.
 *
 * What works, and what is drawn and dead. "Anyone with the link" works, and
 * since 24 September 2026 so does inviting a person by email: they get a
 * letter, make an account from it if they have none, and see the page with
 * Ask AI on it (`rouh/web/guests.py`). What each may do - read it, or change
 * it with Ask AI - is chosen per person, and for the link behind the
 * chevron. Sharing with a team and choosing a theme are still on the panel
 * and disabled: there are no teams, and Rouh is dark.
 *
 * The link is never printed. "We don't need to display it; just give me a
 * Copy public link button." So the panel has one, and says that it copied.
 *
 * One link per page, and it never changes. Petar, 7 October 2026
 * (fr_d687af2e4fd1): "now that I have shared this with someone or made it
 * public, the copy link button should be working. in google drive I think
 * the public link stays the same, here also we should keep the public link
 * stable and just manage permissions." So the server hands the panel the
 * page's link whether or not it is public, Copy link works on every page,
 * and making it public, taking it down or sharing it with somebody changes
 * only who that same link lets in (`sharing.py`, "One link per page").
 */

var SHARE = { rel: '', state: null, asked: 0, busy: false };

//: What a shared task's path starts with, where a page's is the page
//: (`taskshare.PREFIX`).
var SHARE_TASK = '_task/';

/* What the panel is about, in one word: "page", "task" or "subtask". */
function shareWord(rel) {
  var at = String(rel === undefined ? SHARE.rel : rel || '');
  if (at.indexOf(SHARE_TASK) !== 0) return 'page';
  return /^\d+-/.test(at.split('/').pop() || '') ? 'subtask' : 'task';
}

function sharePanel() { return $('sharePanel'); }

function sharePanelOpen() {
  var panel = sharePanel();
  return !!(panel && !panel.hidden);
}

/* The page or the task the Share button is about, or nothing.
 *
 * An `.html` page of the workspace, or - since 12 October 2026
 * (fr_80eaca4ddcbf) - a task or a subtask on its own page, named the way
 * the server keeps it: `_task/` and its folder (`rouh/taskshare.py`). The
 * browser's own top, a project's page and a note being read are not
 * shared, so Share is hidden on those rather than offered and then refused.
 * It is the same rule the server keeps (`_shareable`), said here so the
 * button is never shown for something that could not be shared.
 */
function shareRel() {
  if (!tasksViewing()) return '';
  var at = String(CANVAS.at || '').split('?')[0];
  if (at.indexOf(TASK_PREFIX) === 0) {
    if (canvasDoc()) return '';
    var folder = '';
    try { folder = decodeURIComponent(at.slice(TASK_PREFIX.length)); } catch (err) { return ''; }
    folder = folder.replace(/^\/+|\/+$/g, '');
    // A task is `44.name` and a subtask `44-03.name`; a project's folder has
    // no number, and is not shared.
    return /^\d+[.-]/.test(folder.split('/').pop() || '') ? SHARE_TASK + folder : '';
  }
  if (at.indexOf(WORKSPACE_ROUTE) !== 0) return '';
  var rest = at.slice(WORKSPACE_ROUTE.length);
  if (!rest || !/\.html$/i.test(rest)) return '';
  try { return decodeURIComponent(rest); } catch (err) { return ''; }
}

/* Whether the button belongs on the bar, and which page it is about.
 *
 * Called from `drawCrumb`, which is called every time what is loaded
 * changes and several times when it does not. So it only throws the panel
 * away when the page really has changed underneath it: a panel that closed
 * itself because the breadcrumb learnt a task's name would be a panel that
 * shuts while you are reading it.
 */
function shareTouch() {
  var button = $('shareBtn');
  if (!button) return;
  var rel = shareRel();
  button.hidden = !rel;
  // PDF is of a page open on its own, and never of a task or a subtask: that
  // made its index.html without saying so (fr_4c075039223f). A task's items
  // each have their own menu with PDF in it, on the task's page.
  pdfTouch(rel.indexOf(SHARE_TASK) === 0 ? '' : rel);
  gdocTouch(rel.indexOf(SHARE_TASK) === 0 ? '' : rel);
  if (rel === SHARE.rel) return;
  SHARE.rel = rel;
  SHARE.state = null;
  shareShut();
}

/* A page as a printable PDF, from the PDF section of the Share menu (gene
 * page_pdf, version 2, `rouh/page_pdf.py`, `rouh/web/page_pdf.py`).
 *
 * Petar, 15 October 2026, asking this gene to change: "I would like to also
 * have a button to do that from the task page or from the HTML explainer
 * page. Next to share button maybe or in the "..." menu. Maybe e should get a
 * notification that the PDF is ready with link to download and go to task or
 * page or whatever else is relevant".
 *
 * So it is wherever Share is - a task's page, a subtask's, an HTML page of
 * the workspace - and only while the server says the switch is on and there
 * is a page there to print.
 *
 * Since the same evening it is on an HTML page alone (fr_4c075039223f): on a
 * task it silently made the task's index.html, and Petar: "What if we had two
 * pdfs? Which one would be prepared? ... So it should follow the granularity
 * of sharing". A task's or a subtask's page has a menu on each of its items
 * instead, a page or a .md, whose PDF is that item and nothing else
 * (`objectindex._item_line`, `taskItemPdf` in cards.js). Its menu asks the paper; the making goes on on
 * the server while he reads or goes elsewhere, and Rouh's notifications say
 * when it is ready, with the download, the page and the task. A PDF already
 * kept beside the page, and still as new as it, is offered to save at once.
 *
 * It was a button of its own beside Share until Petar, the same day
 * (fr_167c36b97e6e): "I think the pdf button should be in the share option.
 * So the share should become a box with arrow going up out of it. And then
 * we have share section and pdf section." So the share icon opens one menu,
 * `shareMenu`, with Share over PDF, and this section of it is shown only
 * where there is a page to print.
 */
var PDF = { rel: '', state: null, asked: 0, poll: 0 };

function pdfTouch(rel) {
  var section = $('pdfSection');
  if (!section) return;
  if (rel === PDF.rel) return;
  PDF.rel = rel;
  PDF.state = null;
  section.hidden = true;
  clearTimeout(PDF.poll);
  if (shareMenuShow) shareMenuShow(false);
  if (rel) pdfAsk();
}

function pdfAsk() {
  var rel = PDF.rel, n = ++PDF.asked;
  fetch('/api/page-pdf?at=' + encodeURIComponent(rel), { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (got) {
      if (n !== PDF.asked || rel !== PDF.rel) return;
      PDF.state = got;
      pdfDraw();
      // While one is being made, look again now and then, so the menu says
      // when it is done even if the notice was put away.
      clearTimeout(PDF.poll);
      if (got && got.making) PDF.poll = setTimeout(pdfAsk, 4000);
    });
}

function pdfDraw() {
  var s = PDF.state || {}, section = $('pdfSection');
  if (!section) return;
  section.hidden = !(s.on && s.page);
  var making = s.making || '';
  if (making) section.setAttribute('aria-busy', 'true');
  else section.removeAttribute('aria-busy');
  var made = s.made, item = $('pdfMade');
  item.hidden = !made;
  if (made) {
    var when = new Date(made.at * 1000);
    RouhMenu.label(item, 'Download the one made ' + when.toLocaleDateString(undefined,
      { day: 'numeric', month: 'short' }) + ', ' + when.toLocaleTimeString(undefined,
      { hour: '2-digit', minute: '2-digit' }));
    item.title = 'Save ' + made.doc;
  }
  $('pdfHead').textContent = making ? 'PDF · being made for ' + making + ' paper' : 'PDF';
}

function pdfMake(paper) {
  var rel = PDF.rel;
  if (!rel) return;
  fetch('/api/page-pdf', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ at: rel, paper: paper })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'The PDF could not be started.' }; });
  }).catch(function () {
    return { error: 'The PDF could not be started: Rouh did not answer.' };
  }).then(function (got) {
    if (!got || got.error) {
      notify((got && got.error) || 'The PDF could not be started.', { tone: 'error', kind: 'page_pdf' });
      return;
    }
    notify(got.already ? 'That PDF is already being made.'
                       : 'Making the PDF for ' + got.paper + ' paper.',
           { tone: 'info', kind: 'page_pdf',
             body: 'You will be told here when it is ready, with its download. Carry on with anything meanwhile.' });
    if (rel !== PDF.rel) return;
    PDF.state = Object.assign({}, PDF.state || {}, { making: got.paper });
    pdfDraw();
    clearTimeout(PDF.poll);
    PDF.poll = setTimeout(pdfAsk, 4000);
  });
}

function pdfSave() {
  var made = PDF.state && PDF.state.made;
  if (!made) return;
  var a = document.createElement('a');
  a.href = made.link;
  a.setAttribute('download', made.doc);
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* A Google Doc of this page (night 21, gene page_gdoc, `rouh/page_gdoc.py`).
 *
 * A section of the share icon's menu, on a page open on its own: Make a Google Doc of this page
 * turns it into a Google Doc in Drive, keeping its headings, lists, tables and links, and the
 * same press afterwards (Update the Google Doc) puts the page as it is now into the same
 * document, so its link never changes. Open the Google Doc opens it in a tab of its own. A
 * notice says when it is ready, with the same Open.
 */
var GDOC = { rel: '', state: null, asked: 0, busy: false };

function gdocTouch(rel) {
  var section = $('gdocSection');
  if (!section || rel === GDOC.rel) return;
  GDOC.rel = rel;
  GDOC.state = null;
  GDOC.busy = false;
  section.hidden = true;
  if (rel) gdocAsk();
}

function gdocAsk() {
  var rel = GDOC.rel, n = ++GDOC.asked;
  fetch('/api/page-gdoc?at=' + encodeURIComponent(rel), { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (got) {
      if (n !== GDOC.asked || rel !== GDOC.rel) return;
      GDOC.state = got;
      gdocDraw();
    });
}

function gdocDraw() {
  var s = GDOC.state || {}, section = $('gdocSection');
  if (!section) return;
  section.hidden = !(s.on && s.page);
  var made = s.made;
  var make = $('gdocMake');
  RouhMenu.label(make, made ? 'Update the Google Doc' : 'Make a Google Doc of this page');
  make.title = made ? 'Put the page as it is now into the same Google Doc' : '';
  make.disabled = GDOC.busy;
  $('gdocOpen').hidden = !made;
  $('gdocHead').textContent = GDOC.busy ? 'Google Doc · being made' : 'Google Doc';
}

function gdocOpenIt(made, rel) {
  if (!made || !made.link) return;
  window.open(made.link, '_blank', 'noopener');
  fetch('/api/page-gdoc', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ at: rel, act: 'opened' })
  }).catch(function () {});
}

function gdocMake() {
  var rel = GDOC.rel;
  if (!rel || GDOC.busy) return;
  GDOC.busy = true;
  gdocDraw();
  fetch('/api/page-gdoc', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ at: rel })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'The Google Doc could not be made.' }; });
  }).catch(function () {
    return { error: 'The Google Doc could not be made: Rouh did not answer.' };
  }).then(function (got) {
    if (rel === GDOC.rel) GDOC.busy = false;
    if (!got || got.error || !got.made) {
      if (rel === GDOC.rel) gdocDraw();
      notify((got && got.error) || 'The Google Doc could not be made.', { tone: 'error', kind: 'page_gdoc' });
      return;
    }
    var made = got.made;
    notify((got.updated ? 'Your Google Doc is up to date: ' : 'Your Google Doc is ready: ') + made.title,
      { tone: 'info', kind: 'page_gdoc', lasting: true,
        body: got.updated ? 'The page as it is now is in the same document, at the same link.'
                          : 'Made from the page, with its headings, lists, tables and links.'
                            + (got.shared ? ' You can edit it as ' + got.shared + '.' : ''),
        action: { label: 'Open the Google Doc', run: function () { gdocOpenIt(made, rel); } } });
    if (rel !== GDOC.rel) return;
    GDOC.state = Object.assign({}, GDOC.state || {}, { made: made });
    gdocDraw();
  });
}

/* The share icon's menu: Share over PDF. A press on the icon while the
 * sharing panel is up closes the panel, as the button always did, rather
 * than putting the menu over it. The breadcrumb's own menu is shut as it
 * opens, because the press that opened this one goes no further. */
var shareMenuShow = RouhMenu.bind($('shareBtn'), $('shareMenu'), {
  align: 'end',
  open: function () {
    if (sharePanelOpen()) { shareShut(); return false; }
    crumbMenuClose();
    RouhMenu.label($('shareOpenItem'), 'Share this ' + shareWord());
    if (PDF.rel) pdfAsk();
    if (GDOC.rel && !GDOC.busy) gdocAsk();
  }
});
$('shareOpenItem').addEventListener('click', function () { shareMenuShow(false); shareOpen(); });
// A press inside the page on the canvas never reaches this document, so the
// menu would stay open over it; the window losing the focus to that frame
// is what says it happened.
window.addEventListener('blur', function () { shareMenuShow(false); });
$('pdfLetter').addEventListener('click', function () { pdfMake('letter'); });
$('pdfA4').addEventListener('click', function () { pdfMake('a4'); });
$('pdfMade').addEventListener('click', pdfSave);
$('gdocMake').addEventListener('click', function () { shareMenuShow(false); gdocMake(); });
$('gdocOpen').addEventListener('click', function () {
  shareMenuShow(false);
  gdocOpenIt(GDOC.state && GDOC.state.made, GDOC.rel);
});

// The link, built from where this browser actually is. The server hands back
// the path and no more: a link to the Rouh in front of the person is the one
// that will answer it, and this page cannot know what another one is called.
function shareLink() {
  var path = SHARE.state && SHARE.state.path;
  return path ? location.origin + path : '';
}

function shareSay(words, kind) {
  if (!words) shareInviteSay('');
  var here = ['shareSaid', 'shareSaid2'], i;
  for (i = 0; i < here.length; i++) {
    var box = $(here[i]);
    if (!box) continue;
    box.textContent = words || '';
    box.className = 'share-said' + (kind ? ' ' + kind : '');
  }
}

/* How tall the panel may be: from its own top to the foot of what can be
 * seen, less a margin, so the last button is always on the screen once it
 * is scrolled to (fr_b912b40b6fdb). The panel hangs from the canvas bar, so
 * its top is measured rather than assumed. While a field of the panel has
 * the focus on a phone, the visual viewport is what the keyboard has left;
 * zoomed out, it may claim more than the window, so the window caps it.
 */
function shareFit() {
  var panel = sharePanel();
  if (!panel || panel.hidden) return;
  var vv = window.visualViewport;
  var bottom = window.innerHeight;
  if (vv && vv.height > 0) bottom = Math.min(bottom, vv.offsetTop + vv.height);
  var room = Math.floor(bottom - panel.getBoundingClientRect().top - 12);
  panel.style.setProperty('--share-max', Math.max(160, room) + 'px');
}

window.addEventListener('resize', shareFit);
if (window.visualViewport) window.visualViewport.addEventListener('resize', shareFit);

function shareFace(which) {
  var panel = sharePanel();
  if (panel) panel.scrollTop = 0;
  var main = $('shareFaceMain'), settings = $('shareFaceSettings');
  if (main) main.hidden = which !== 'main';
  if (settings) settings.hidden = which !== 'settings';
  var who = $('shareWho');
  if (who) who.setAttribute('aria-expanded', which === 'settings' ? 'true' : 'false');
}

function shareOpen() {
  var rel = shareRel();
  if (!rel) return;
  if (sharePanelOpen()) { shareShut(); return; }
  shareMenuShow(false);
  SHARE.rel = rel;
  sharePanel().hidden = false;
  shareFit();
  $('shareBtn').classList.add('held');
  shareFace('main');
  shareSay('');
  // Who owns it: the account that is signed in, which the page already
  // knows because Settings is drawn with it in.
  var me = ($('whoAmI') && $('whoAmI').textContent || '').trim() || 'You';
  $('shareOwnerName').textContent = me;
  $('shareOwnerMark').textContent = me.slice(0, 2);
  shareWords();
  shareNotifyReset();
  shareDraw();
  shareAsk();
}

function shareShut() {
  if (!sharePanelOpen()) return;
  sharePanel().hidden = true;
  var button = $('shareBtn');
  if (button) button.classList.remove('held');
  shareFace('main');
  shareSay('');
}

/* The panel's own words, for a page or for a task. A task's link is only
   ever read, so what a visitor may do is not offered for one; a person it is
   shared with may be given either, and a task starts at Can view, as asking
   the assistant does (`sharing.role_for`). */
function shareWords() {
  var word = shareWord(), task = word !== 'page';
  $('shareHead').textContent = 'Share ' + word;
  $('shareHead2').textContent = 'Share ' + word + ' settings';
  $('shareSubLine').textContent = task
    ? 'The ' + word + ' as it is now: its pages, its notes and its subtasks. '
      + 'Its chats and runs stay yours.'
    : 'The page as it is now, and nothing else in the workspace.';
  $('shareOwnerSub').textContent = 'This ' + word + ' is in your workspace.';
  var role = $('shareRole');
  if (role) role.value = task ? 'view' : 'edit';
  // Deciding for the owner is over a task, a goal, a quest or a step, never one page.
  var decide = $('shareRoleDecide');
  if (decide) { decide.hidden = !task; decide.disabled = !task; }
  shareNotifyDraw();
}

/* Notify by email, as Google Drive asks it (fr_55056f9ffcc2): under the
   address once one is typed, ticked, with a line that can be changed before
   it goes. Unticked, the page is shared and nobody is emailed, so the
   message goes too and the button says Share rather than Send. */
var SHARE_MESSAGE = 'Have a look at this when you have a moment, and let me know what you think.';

function shareNotifyReset() {
  var tick = $('shareNotify'), words = $('shareMessage');
  if (tick) tick.checked = true;
  if (words) words.value = SHARE_MESSAGE;
  shareNotifyDraw();
}

function shareNotifyDraw() {
  var box = $('shareNotifyBox'), tick = $('shareNotify'), words = $('shareMessage');
  var email = $('shareEmail'), go = $('shareInvite'), none = $('shareNoMail');
  if (!box || !tick || !words) return;
  // Said by the server when the panel opened: with no mail service on this
  // machine nothing can be sent, so the box is not offered as if it could.
  var mailless = !!(SHARE.state && SHARE.state.can_mail === false);
  if (mailless) tick.checked = false;
  tick.disabled = mailless;
  if (none) none.hidden = !mailless;
  box.hidden = !(email && email.value.trim());
  words.hidden = !tick.checked;
  if (go) {
    go.textContent = tick.checked ? 'Send' : 'Share';
    go.title = 'Share this ' + shareWord() + ' with that address'
      + (tick.checked ? ', and email them the link' : ', without emailing them');
  }
}

// How the page stands, off the server, for the page the panel is about.
function shareAsk() {
  var rel = SHARE.rel, mine = ++SHARE.asked;
  if (!rel) return;
  canvasGet('/api/share?rel=' + encodeURIComponent(rel)).then(function (got) {
    if (mine !== SHARE.asked || SHARE.rel !== rel) return;
    if (!got || got.error) {
      shareSay(got && got.error ? got.error : 'That could not be read.', 'bad');
      return;
    }
    SHARE.state = got;
    shareDraw();
    shareMeetingsAsk();
  });
}

/* With a meeting's guests (night 30, `rouh/share_meeting.py`): up to three of his meetings about
   this page or task, from three days ago to a week ahead, each with its guests from outside not on
   it yet. Pressing one says who; Share with them shares with all of them, at the level picked and
   with the letter as Notify by email says, the way Send shares with one. Nothing while it is off. */
var SHARE_MEETINGS = { rel: '', list: [], open: '', busy: false };

function shareMeetingsAsk() {
  var rel = SHARE.rel;
  if (!rel) return;
  canvasGet('/api/share/meetings?rel=' + encodeURIComponent(rel)).then(function (got) {
    if (SHARE.rel !== rel) return;
    SHARE_MEETINGS.rel = rel;
    SHARE_MEETINGS.list = (got && got.meetings) || [];
    if (SHARE_MEETINGS.list.every(function (m) { return m.key !== SHARE_MEETINGS.open; })) SHARE_MEETINGS.open = '';
    shareMeetingsDraw();
  });
}

function shareMeetingsDraw() {
  var box = $('shareMeetings');
  if (!box) return;
  box.textContent = '';
  var list = SHARE_MEETINGS.rel === SHARE.rel ? SHARE_MEETINGS.list : [];
  box.hidden = !list.length;
  if (!list.length) return;
  box.appendChild(el('p', 'share-label', 'With a meeting\u2019s guests'));
  list.forEach(function (m) {
    var open = SHARE_MEETINGS.open === m.key;
    var row = el('button', 'share-row share-go share-meeting' + (open ? ' is-open' : ''));
    row.type = 'button';
    row.setAttribute('aria-expanded', open ? 'true' : 'false');
    var ico = el('span', 'share-ico', '');
    ico.setAttribute('aria-hidden', 'true');
    ico.appendChild(shareGlyph('M4 6h16v14H4zM4 10h16M9 3v4M15 3v4'));
    row.appendChild(ico);
    var main = el('span', 'share-row-main');
    main.appendChild(el('span', 'share-row-title', m.title));
    var when = String(m.when || '');
    main.appendChild(el('span', 'share-row-sub', when.charAt(0).toUpperCase() + when.slice(1) + ' \u00b7 ' + m.guests.length +
      (m.guests.length === 1 ? ' guest' : ' guests') + ' not on it yet'));
    row.appendChild(main);
    row.addEventListener('click', function () {
      SHARE_MEETINGS.open = open ? '' : m.key;
      // Drawn again after the press has travelled on: drawn now, the row pressed would be gone
      // from the panel by the time the outside-click rule asks whether the press was inside it.
      setTimeout(shareMeetingsDraw, 0);
    });
    box.appendChild(row);
    if (!open) return;
    var more = el('div', 'share-meeting-more');
    more.appendChild(el('p', 'share-sub', m.guests.join(', ')));
    var go = el('button', 'ctl small share-meeting-go', 'Share with them');
    go.type = 'button';
    go.disabled = SHARE_MEETINGS.busy;
    var role = $('shareRole');
    go.title = 'Share this ' + shareWord() + ' with ' + m.guests.length + (m.guests.length === 1 ? ' person' : ' people') +
      ' as ' + (role && role.selectedOptions[0] ? role.selectedOptions[0].textContent : 'Edit');
    go.addEventListener('click', function () { shareMeetingGo(m, go); });
    more.appendChild(go);
    box.appendChild(more);
  });
}

function shareMeetingGo(m, button) {
  var rel = SHARE.rel, role = $('shareRole'), tick = $('shareNotify'), words = $('shareMessage');
  if (!rel || SHARE_MEETINGS.busy) return;
  SHARE_MEETINGS.busy = true;
  button.disabled = true;
  shareInviteSay('Sharing it with ' + m.guests.length + (m.guests.length === 1 ? ' person' : ' people') + '\u2026');
  var mailless = !!(SHARE.state && SHARE.state.can_mail === false);
  var notify = !mailless && (!tick || tick.checked);
  sharePost('/api/share/meetings', {
    rel: rel, key: m.key, role: role ? role.value : 'edit', notify: notify,
    message: notify ? ((words && words.value) || SHARE_MESSAGE) : ''
  }).then(function (got) {
    SHARE_MEETINGS.busy = false;
    if (SHARE.rel !== rel) return;
    if (!got || got.error) {
      button.disabled = false;
      shareInviteSay((got && got.error) || 'That could not be shared.', 'bad');
      return;
    }
    SHARE_MEETINGS.open = '';
    if (SHARE.state) { SHARE.state.people = got.people || []; SHARE.state.inherited = got.inherited || []; }
    shareDraw();
    shareMeetingsAsk();
    shareInviteSay(got.said || 'Shared.', got.sent || !notify ? 'good' : 'bad');
  });
}

// The panel, drawn from what is known. Called before the server has answered
// as well as after, so the panel opens with something on it rather than
// blank, and settles when the answer arrives.
function shareDraw() {
  var on = !!(SHARE.state && SHARE.state.public);
  var edits = on && SHARE.state.role === 'edit';
  var people = ((SHARE.state && SHARE.state.people) || [])
    .concat((SHARE.state && SHARE.state.inherited) || []);
  var name = $('shareWhoName'), sub = $('shareWhoSub'), icon = $('shareWhoIcon');
  if (name) {
    name.textContent = on ? 'Anyone with the link'
                          : (people.length ? 'Only you and the people below' : 'Only you');
  }
  if (sub) {
    sub.textContent = edits ? 'No sign in needed, and they can change it with Ask AI.'
      : (on ? 'No sign in needed to open it.'
            : 'It is behind your sign-in, as everything here is.');
  }
  if (icon) {
    icon.className = 'share-ico' + (on ? ' on' : '');
    icon.textContent = '';
    icon.appendChild(shareGlyph(on
      ? 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.7 2.5 15.3 0 18'
      : 'M6 11V8a6 6 0 0 1 12 0v3M5 11h14v10H5z'));
  }
  // Dead only until the server has said what the link is, which is the
  // moment the panel opens: every page has one, public or not.
  var copy = $('shareCopy');
  if (copy) {
    copy.disabled = !shareLink();
    copy.title = on ? 'Copy the link to this ' + shareWord() + '. Anyone with it can open it.'
                    : 'Copy the link to this ' + shareWord() + '. It opens for you'
                      + (people.length ? ' and the people above.' : ', until you share it.');
  }
  var pick = $('shareAccess');
  if (pick) pick.value = on ? 'public' : 'private';
  var role = $('shareLinkRole');
  if (role) role.value = edits ? 'edit' : 'view';
  sharePeople((SHARE.state && SHARE.state.people) || [], (SHARE.state && SHARE.state.inherited) || []);
  shareFacts();
  shareNotifyDraw();
}

// The three things "anyone with the link" really means, shown only while
// that is what is about to be saved - and what a visitor may do with it.
function shareFacts() {
  var facts = $('shareFacts'), pick = $('shareAccess'), wrap = $('shareLinkRoleWrap');
  var open = !!pick && pick.value === 'public';
  var word = shareWord();
  if (facts) facts.hidden = !open;
  // A task's link is only ever read, so there is nothing to choose.
  if (wrap) wrap.hidden = !open || word !== 'page';
  var ask = $('shareFactAsk'), role = $('shareLinkRole');
  if (!ask || !role) return;
  ask.textContent = '';
  if (word !== 'page') {
    ask.appendChild(el('strong', null, 'Read only.'));
    ask.appendChild(document.createTextNode(
      ' A visitor reads the ' + word + ', its pages, its notes and its subtasks. ' +
      'Its chats, runs and files stay yours, and there is no Ask AI on it.'));
  } else if (role.value === 'edit') {
    ask.appendChild(el('strong', null, 'They can change it.'));
    ask.appendChild(document.createTextNode(
      ' A visitor gets Ask AI on the page, which answers and changes it, up to sixty ' +
      'questions a day on your account. Every change can be put back, and is saved.'));
  } else {
    ask.appendChild(el('strong', null, 'No Ask AI.'));
    ask.appendChild(document.createTextNode(
      ' A visitor reads the page. The drawer is yours and stays behind your sign-in.'));
  }
}

/* One person's level on one thing - None, Read, Edit or Decide - in the one control that sets
   it wherever it is set: a trusted contact's tree and the Share panel (`rouh/task_access.py`,
   V1). Decide is offered only where one of your trusted contacts, switched on, may hold it. */
var LEVEL_WORDS = { '': 'None', view: 'Read', edit: 'Edit', decide: 'Decide' };

function levelPick(opts) {
  var pick = el('select', 'level-pick', null);
  ['', 'view', 'edit', 'decide'].forEach(function (k) {
    if (k === 'decide' && !opts.decide) return;
    var o = el('option', '', LEVEL_WORDS[k]);
    o.value = k;
    pick.appendChild(o);
  });
  pick.setAttribute('aria-label', opts.label || 'What they may do');
  return pick;
}

/* The level a control shows, and how: dimmed when it comes from above, with None left out
   then, since what is above still holds. */
function levelPickSet(pick, value, opts) {
  opts = opts || {};
  pick.value = value || '';
  ['none', 'view', 'edit', 'decide'].forEach(function (k) {
    pick.classList.toggle('lv-' + k, (value || 'none') === k);
  });
  pick.classList.toggle('inherited', !!opts.inherited);
  var none = pick.querySelector('option[value=""]');
  if (none) none.disabled = !!opts.noNone;
}

/* Everybody the page is shared with by email: the address, how far they
   have got - invited, or with an account - and what they may do, with the
   way to stop sharing it with them. */
function sharePeople(people, inherited) {
  var box = $('sharePeople');
  if (!box) return;
  box.textContent = '';
  for (var i = 0; i < people.length; i++) box.appendChild(sharePerson(people[i]));
  // Who may do something here by a record above it (rouh/task_access.py): said, and changed
  // where that record is, or narrowed here by sharing it with them again.
  var own = people.map(function (p) { return p.email; });
  for (var j = 0; j < (inherited || []).length; j++) {
    if (own.indexOf(inherited[j].email) < 0) box.appendChild(shareInherited(inherited[j]));
  }
}

/* Somebody who may do something here only through a record above it, or a ticked project on
   their page in Trusted contacts: the level dimmed, with what it comes from. A level set here
   is a record of its own, which overrides it. */
function shareInherited(p) {
  var row = el('div', 'share-row share-person share-inherited');
  row.appendChild(el('span', 'share-ico share-avatar', String(p.email || '?').slice(0, 2)));
  var main = el('span', 'share-row-main');
  main.appendChild(el('span', 'share-row-title', p.email));
  main.appendChild(el('span', 'share-row-sub', 'from ' + (p.from || 'what it is in')));
  row.appendChild(main);
  row.appendChild(shareLevel(p, true));
  return row;
}

function sharePerson(p) {
  var tick = p.via === 'tick';
  var row = el('div', 'share-row share-person' + (tick ? ' share-inherited' : ''));
  row.appendChild(el('span', 'share-ico share-avatar', String(p.email || '?').slice(0, 2)));
  var main = el('span', 'share-row-main');
  main.appendChild(el('span', 'share-row-title', p.email));
  var how = p.joined ? 'Has an account' : 'Invited';
  if (p.mail_error) how += ', and the email did not go';
  else if (!p.mailed) how = (p.joined ? 'Has an account' : 'No account yet') + ', not emailed';
  // Kept by a ticked project on their page in Trusted contacts (rouh/task_access.py).
  if (tick) how = 'from ' + (p.from || 'a ticked project') + ', in Trusted contacts';
  var sub = el('span', 'share-row-sub' + (p.mail_error ? ' bad' : ''), how);
  if (p.mail_error) sub.title = p.mail_error;
  main.appendChild(sub);
  // When they last opened it, while that gene is on (rouh/share_opens.py).
  if ('opened' in p) {
    var seen = el('span', 'share-row-sub share-opened' + (p.opened ? ' is-opened' : ''),
      p.opened ? 'Opened ' + whenWords(p.opened) : 'Not opened yet');
    // Remind them, while that gene is on (rouh/share_remind.py): a new email to them in Gmail,
    // in his own mailbox, with their link; Rouh sends nothing.
    if (!p.opened && p.remind) {
      seen.appendChild(document.createTextNode(' · '));
      var remind = el('a', 'share-remind', 'Remind them');
      remind.href = p.remind;
      remind.target = '_blank';
      remind.rel = 'noopener noreferrer';
      remind.title = 'A new email to ' + p.email + ' in Gmail, with their link';
      remind.addEventListener('click', function () { sharePost('/api/share/remind', { rel: SHARE.rel }); });
      seen.appendChild(remind);
    }
    main.appendChild(seen);
  }
  // Until, while that gene is on (rouh/share_ends.py): the share is taken away by itself then.
  if ('ends' in p && !tick) main.appendChild(shareUntil(p));
  row.appendChild(main);
  row.appendChild(shareLevel(p, tick));
  return row;
}

/* Until: no end, or a day, a week, two weeks or a month from now. The end already set is the
   first choice while there is one, said as a date. */
var SHARE_UNTIL = [[0, 'No end'], [1, 'A day'], [7, 'A week'], [14, 'Two weeks'], [30, 'A month']];

function shareUntilDate(at) {
  var d = new Date(at * 1000);
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) +
    ', ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function shareUntil(p) {
  var line = el('span', 'share-row-sub share-until');
  var label = el('label', null, p.ends ? 'Ends ' : 'Until ');
  var pick = el('select', 'share-until-pick', null);
  pick.setAttribute('aria-label', 'Until when ' + p.email + ' may open it');
  if (p.ends) {
    var now = el('option', '', shareUntilDate(p.ends));
    now.value = 'kept';
    pick.appendChild(now);
  }
  SHARE_UNTIL.forEach(function (c) {
    var o = el('option', '', c[0] ? c[1] + ' from now' : 'No end');
    o.value = String(c[0]);
    pick.appendChild(o);
  });
  pick.value = p.ends ? 'kept' : '0';
  pick.addEventListener('change', function () {
    if (pick.value === 'kept') return;
    var rel = SHARE.rel;
    pick.disabled = true;
    sharePost('/api/share/ends', { rel: rel, token: p.token, days: Number(pick.value) })
      .then(function (got) {
        if (SHARE.rel !== rel) return;
        pick.disabled = false;
        if (!got || got.error) {
          shareInviteSay((got && got.error) || 'That end could not be set.', 'bad');
          pick.value = p.ends ? 'kept' : '0';
          return;
        }
        if (SHARE.state) { SHARE.state.people = got.people || []; SHARE.state.inherited = got.inherited || []; }
        shareDraw();
        shareInviteSay(got.ends ? p.email + ' may open it until ' + shareUntilDate(got.ends) +
          '; then it is taken away by itself.' : p.email + "'s share has no end now.", 'good');
      });
  });
  label.appendChild(pick);
  line.appendChild(label);
  return line;
}

/* The level control on one person's row: changing it turns their record, None takes it away
   (the old x), at once and with no letter. */
function shareLevel(p, inherited) {
  var pick = levelPick({ decide: shareWord() !== 'page' && (p.decides || p.role === 'decide'),
    label: 'What ' + p.email + ' may do with this ' + shareWord() });
  levelPickSet(pick, p.role, { inherited: inherited, noNone: inherited });
  pick.addEventListener('change', function () {
    if (!pick.value) shareUninvite(p, pick);
    else shareSetLevel(p, pick.value, pick);
  });
  return pick;
}

function shareSetLevel(p, role, control) {
  var rel = SHARE.rel;
  if (!rel) return;
  control.disabled = true;
  sharePost('/api/share/invite', { rel: rel, email: p.email, role: role, notify: false })
    .then(function (got) {
      if (SHARE.rel !== rel) return;
      control.disabled = false;
      if (!got || got.error) {
        shareInviteSay((got && got.error) || 'That could not be changed.', 'bad');
        levelPickSet(control, p.role, { inherited: control.classList.contains('inherited') });
        return;
      }
      if (SHARE.state) { SHARE.state.people = got.people || []; SHARE.state.inherited = got.inherited || []; }
      shareDraw();
      shareInviteSay(p.email + ' may ' + ({ view: 'read', edit: 'edit', decide: 'decide for' })[role] +
        ' this ' + shareWord() + ' now.', 'good');
    });
}

// What became of an invitation, on its own line under the box, where two
// lines are room enough to say it whole.
function shareInviteSay(words, kind) {
  var line = $('shareInviteSaid');
  if (!line) return;
  line.textContent = words || '';
  line.className = 'share-invite-said' + (kind ? ' ' + kind : '');
  line.hidden = !words;
}

function sharePost(url, body) {
  return fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'That could not be saved.' }; });
  }).catch(function () {
    return { error: 'Rouh could not be reached.' };
  });
}

// Send: share this page with the address typed, and email them the link with
// the message, unless Notify by email is unticked.
function shareInvite() {
  var rel = SHARE.rel, box = $('shareEmail'), role = $('shareRole'), go = $('shareInvite');
  var tick = $('shareNotify'), words = $('shareMessage');
  if (!rel || !box || SHARE.busy) return;
  var email = box.value.trim();
  if (!email) { box.focus(); return; }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) {
    shareInviteSay('That is not an email address.', 'bad');
    box.focus();
    return;
  }
  SHARE.busy = true;
  go.disabled = true;
  shareInviteSay('Sharing it with ' + email + '\u2026');
  var notify = !tick || tick.checked;
  sharePost('/api/share/invite', {
    rel: rel, email: email, role: role ? role.value : 'edit',
    notify: notify, message: notify && words ? words.value : ''
  })
    .then(function (got) {
      SHARE.busy = false;
      go.disabled = false;
      if (SHARE.rel !== rel) return;
      if (!got || got.error) {
        shareInviteSay((got && got.error) || 'That could not be shared.', 'bad');
        return;
      }
      box.value = '';
      shareNotifyReset();
      if (SHARE.state) { SHARE.state.people = got.people || []; SHARE.state.inherited = got.inherited || []; }
      shareDraw();
      shareMeetingsAsk();
      shareInviteSay(got.said || 'Shared.', got.notified === false ? '' : (got.sent ? 'good' : 'bad'));
    });
}

function shareUninvite(p, button) {
  var rel = SHARE.rel;
  if (!rel) return;
  button.disabled = true;
  sharePost('/api/share/uninvite', { rel: rel, token: p.token }).then(function (got) {
    if (SHARE.rel !== rel) return;
    if (!got || got.error) {
      button.disabled = false;
      if (button.tagName === 'SELECT') levelPickSet(button, p.role, { inherited: button.classList.contains('inherited') });
      shareInviteSay((got && got.error) || 'That could not be changed.', 'bad');
      return;
    }
    if (SHARE.state) { SHARE.state.people = got.people || []; SHARE.state.inherited = got.inherited || []; }
    shareDraw();
    var still = (got.inherited || []).filter(function (x) { return x.email === p.email; })[0];
    shareInviteSay(still ? p.email + ' has no level of their own here now, and still may ' +
      ({ view: 'read', edit: 'edit', decide: 'decide for' })[still.role] + ' it from ' + still.from + '.'
      : 'This ' + shareWord() + ' is not shared with ' + p.email + ' any more.', 'good');
  });
}

function shareGlyph(path) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '15');
  svg.setAttribute('height', '15');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  var d = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  d.setAttribute('d', path);
  svg.appendChild(d);
  return svg;
}

// Save: make it public, or take it down. The one write on the panel.
function shareSave() {
  var rel = SHARE.rel, pick = $('shareAccess');
  if (!rel || !pick || SHARE.busy) return;
  var want = pick.value === 'public';
  SHARE.busy = true;
  $('shareSave').disabled = true;
  var role = $('shareLinkRole');
  shareSay(want ? 'Making it public…' : 'Taking it down…');
  fetch('/api/share', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rel: rel, public: want, role: role ? role.value : 'view' })
  }).then(function (r) {
    return r.json().catch(function () { return { error: 'That could not be saved.' }; });
  }).catch(function () {
    return { error: 'That could not be saved.' };
  }).then(function (got) {
    SHARE.busy = false;
    $('shareSave').disabled = false;
    if (SHARE.rel !== rel) return;
    if (!got || got.error) { shareSay((got && got.error) || 'That could not be saved.', 'bad'); return; }
    SHARE.state = got;
    shareDraw();
    shareFace('main');
    var word = shareWord(rel);
    shareSay(got.public ? (got.role === 'edit' ? 'This page is public, and can be changed.'
                                              : 'This ' + word + ' is public.')
                        : 'This ' + word + ' is not public any more.', 'good');
  });
}

/* The link on the clipboard, and a word to say it is there.
 *
 * Said in the footer beside the button rather than by the button changing
 * to "Copied": one press should say one thing, and the line is where every
 * other answer from this panel already appears.
 */
function shareCopyLink() {
  var link = shareLink();
  if (!link) return;
  var on = !!(SHARE.state && SHARE.state.public);
  var people = (SHARE.state && SHARE.state.people) || [];
  copyText(link).then(function () {
    shareSay(on ? 'Link copied. Anyone with it can open the ' + shareWord() + '.'
                : (people.length ? 'Link copied. It opens for you and the people above.'
                                 : 'Link copied. Only you can open it until you share it.'),
             'good');
  }, function () {
    shareSay('This browser would not copy it.', 'bad');
  });
}

/* ---------- every page that is public ----------
 *
 * "We need to have a place where you can see all public pages so you can
 * remember what else in the past was shared and take it down because it no
 * longer needs to be public."
 *
 * A layer on the canvas like a run, a task and a card, so it opens, closes
 * and answers Escape the same way. It is opened from the sharing panel, and
 * closing it puts the reader back on the page they opened it from.
 */

var SHARES = { open: false, back: '', asked: 0 };

function sharesOpen() {
  // Read before anything is stood down: opening this layer closes the tasks,
  // and closing the tasks forgets which page was loaded.
  var back = tasksViewing() ? (CANVAS.at || '') : '';
  shareShut();
  SHARES.open = true;
  SHARES.back = back;
  showLayer('sharesView');
  sharesDraw(null);
  sharesFill();
}

function sharesClose() {
  if (!SHARES.open) return;
  SHARES.open = false;
  var back = SHARES.back;
  SHARES.back = '';
  SHARES.asked++;
  var body = $('sharesBody');
  if (body) body.textContent = '';
  showLayer(null);
  // Back to the page it was opened from, the way a card goes back to what it
  // was read out of. Never while this closer is one of the layers being
  // stood down for another that is opening: that is a move somewhere else.
  if (back && !standingDown && !contentOpen()) canvasLoad(back);
}

function sharesFill() {
  var mine = ++SHARES.asked;
  canvasGet('/api/share/all').then(function (got) {
    if (mine !== SHARES.asked || !SHARES.open) return;
    if (!got || got.error) { sharesDraw([], (got && got.error) || 'That could not be read.'); return; }
    sharesDraw(Array.isArray(got.pages) ? got.pages : []);
  });
}

function sharesDraw(rows, problem) {
  var body = $('sharesBody'), meta = $('sharesMeta');
  if (!body) return;
  body.textContent = '';
  if (problem) {
    if (meta) meta.textContent = '';
    body.appendChild(el('p', 'empty', problem));
    return;
  }
  if (rows === null) {
    if (meta) meta.textContent = '';
    body.appendChild(el('p', 'empty', 'Reading what is public…'));
    return;
  }
  if (meta) meta.textContent = '';
  if (!rows.length) {
    body.appendChild(el('p', 'empty',
      'Nothing is public. Share, in the top bar on a page or a task, makes one public.'));
    return;
  }
  for (var i = 0; i < rows.length; i++) body.appendChild(shareItem(rows[i]));
  sharesCount();
}

// How many are still public, counted off the rows on the screen rather than
// kept beside them. A row taken down stays where it is, struck through, so
// the number above it has to follow the presses and not only the fetch.
function sharesCount() {
  var meta = $('sharesMeta'), body = $('sharesBody');
  if (!meta || !body) return;
  var live = body.querySelectorAll('.share-item:not(.gone)').length;
  meta.textContent = live
    ? (live === 1 ? '1 is public' : live + ' are public')
    : 'None of these is public any more.';
}

// One public page: what it is called, where it is, and the way to take it
// down. The row stays after it is taken down and says so, rather than
// vanishing under the press and leaving the reader unsure which one went.
function shareItem(row) {
  var item = el('div', 'share-item');
  var main = el('div', 'share-item-main');
  // A task's row names its folder, which is where it is (`taskshare.PREFIX`).
  var where = String(row.rel || '');
  if (where.indexOf(SHARE_TASK) === 0) where = where.slice(SHARE_TASK.length);
  main.appendChild(el('div', 'share-item-name', row.title || where));
  main.appendChild(el('div', 'share-item-where', where));
  item.appendChild(main);

  var state = el('span', 'share-item-state');
  item.appendChild(state);

  var stop = el('button', 'ctl small', 'Make it not public');
  stop.type = 'button';
  stop.addEventListener('click', function () {
    if (stop.disabled) return;
    stop.disabled = true;
    state.textContent = 'Taking it down…';
    fetch('/api/share/stop', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: row.token })
    }).then(function (r) {
      return r.json().catch(function () { return { error: 'no' }; });
    }).catch(function () {
      return { error: 'no' };
    }).then(function (got) {
      if (!got || got.error || !got.stopped) {
        stop.disabled = false;
        state.textContent = 'That could not be taken down.';
        return;
      }
      item.classList.add('gone');
      state.textContent = 'Not public any more';
      stop.remove();
      sharesCount();
      // The page the panel is about may be this one, so what it says is no
      // longer true. It is asked again the next time it opens.
      if (SHARE.rel === row.rel) SHARE.state = null;
    });
  });
  item.appendChild(stop);
  return item;
}

// --- the presses ---

$('shareClose').addEventListener('click', shareShut);
$('shareClose2').addEventListener('click', shareShut);
$('shareWho').addEventListener('click', function () { shareFace('settings'); shareSay(''); });
$('shareGear').addEventListener('click', function () { shareFace('settings'); shareSay(''); });
$('shareBack').addEventListener('click', function () { shareFace('main'); shareSay(''); });
$('shareCancel').addEventListener('click', function () { shareDraw(); shareFace('main'); shareSay(''); });
$('shareAccess').addEventListener('change', shareFacts);
$('shareLinkRole').addEventListener('change', shareFacts);
$('shareSave').addEventListener('click', shareSave);
$('shareInvite').addEventListener('click', shareInvite);
$('shareEmail').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); shareInvite(); }
});
$('shareEmail').addEventListener('input', shareNotifyDraw);
$('shareNotify').addEventListener('change', shareNotifyDraw);
$('shareCopy').addEventListener('click', shareCopyLink);
$('shareAllBtn').addEventListener('click', sharesOpen);
$('sharesClose').addEventListener('click', sharesClose);

/* A press anywhere else closes the panel, the way the breadcrumb's own menu
 * goes.
 *
 * Not a press inside the panel, and not the button that opened it - that
 * one is a toggle and closes the panel itself. The press is left to travel
 * on rather than stopped here, because the same outside-click rule is what
 * closes the breadcrumb's sibling menu, and a press that Share swallowed
 * left that menu hanging open under the panel.
 */
document.addEventListener('click', function (e) {
  if (!sharePanelOpen()) return;
  var button = $('shareBtn'), menu = $('shareMenu');
  if (sharePanel().contains(e.target)) return;
  if (button && button.contains(e.target)) return;
  // Share this page in the menu is what opened it, a moment ago.
  if (menu && menu.contains(e.target)) return;
  shareShut();
}, false);

/* Escape closes the panel before it closes anything under it.
 *
 * `somethingElseIsOver` already knows the panel is up, so the handler that
 * closes a layer has stepped aside by the time this runs; this is the other
 * half of that pair, and it is registered later on purpose.
 */
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || e.defaultPrevented || !sharePanelOpen()) return;
  e.preventDefault();
  shareShut();
}, false);

// The first draw of the canvas bar. After the sharing block and not before
// it: `drawCrumb` settles the Share button as well, and it cannot do that
// until `SHARE` exists.
drawCrumb();

/* ---------- Settings ----------
 *
 * The same layer over the canvas as a run and the task browser, so it opens,
 * closes and answers Escape identically.
 *
 * Everything it draws comes from GET /api/settings/google, which answers for
 * whoever is signed in and for their organisation only. Two levels, kept
 * apart on the page because they belong to different people:
 *
 *   Your organisation's Google app   the OAuth client an administrator
 *                                    registered in their own Google Cloud
 *                                    project. Administrators only: an
 *                                    ordinary member is told it exists and
 *                                    nothing more, because the server does
 *                                    not send them the client id and has
 *                                    never sent anyone the secret.
 *   Your connection                  this person's own Google account.
 *
 * The secret is write-only from the page's side. It is typed, posted once,
 * and after that the page is told only that one is set and when it last
 * changed. There is no request that gives it back, so there is nothing to
 * read out of the DOM, out of a response, or out of a screenshot.
 */

// `page` is the group of Anatomy showing, '' for the status board, and `section` the one of its
// sections the address names, '' for the page itself (`settingsShowGroup`).
var SETTINGS = { open: false, data: null, editingClient: false, page: '', section: '', from: null, beats: '',
                 beatsQuery: '', stats: '', gene: '', heartbeat: '' };

// The Apple Contacts card's own state (GET /api/settings/apple). Declared up
// here with SETTINGS rather than beside its handlers, because Settings can be
// opened while the page is still being built - coming home from Google does
// it - and the card is drawn as part of opening it.
var APPLE = { data: null, editing: false, timer: null, tell: false };

// The Telegram account card's (GET /api/settings/telegram-account), up here
// for the same reason. `again` is Start again pressed on a login that is
// waiting for a code or a password: the first form, whatever the server holds.
var TGACC = { data: null, again: false };

// The New mail card's (GET /api/settings/mail-alerts), up here for the
// same reason.
var MAIL = { data: null, editingTopic: false, guide: false, timer: null };

// The Models card's (GET /api/settings/models), and the one save in flight.
var MODELS = { data: null, saving: false };
/* The two boxes, each with its own Auto, Sync and Reset to defaults. */
var MODELS_BOXES = [{ id: 'tiers', key: 'Tiers' }, { id: 'uses', key: 'Uses' }];

function settingsViewing() { return !!(SETTINGS && SETTINGS.open); }

/* Anatomy's groups, You, Rouh Land Account, Connections, Behaviour, Money and Meta, each a page
   of its own at `/anatomy/<group>` with its row in the side list (Rouh Land Account since 4
   November 2026). Petar, 14 October 2026 (card 1554): "I kind
   of liked the one page where all settings are listed. but I am willing to try what you are
   proposing. keep 5 groups please". A group's page is a menu of its sections, and each section
   is a page of its own at `/anatomy/<group>/<section>`, with Back to the menu; the same day
   (fr_d9e20791f108): "each of the five groups should lead to another page with selections. You
   for example should have a menu with the you items, not one single page where everything is
   put". Which section is in which group, in which order, and what each group and section is
   called, are the gene manifests' (`genes.anatomy`, `anatomyGroups`), as the side list's rows,
   the menus and the server's addresses are; the cards themselves are the markup's
   (`.settings-section`). `/anatomy` itself is the status board (`anatomyBoardLoad`). Until that
   day Settings was a list of twenty groups at `/settings/<group>`, and each of those is a
   section's name now. */
function anatomyGroup(id) {
  var groups = anatomyGroups();
  for (var i = 0; i < groups.length; i++) if (groups[i].id === id) return groups[i];
  return null;
}

/** The group whose page a section is on, and the section, or null. @param {string} id */
function anatomySection(id) {
  var groups = anatomyGroups();
  for (var i = 0; i < groups.length; i++) {
    for (var j = 0; j < groups[i].sections.length; j++) {
      if (groups[i].sections[j].id === id) return { group: groups[i].id, section: groups[i].sections[j] };
    }
  }
  return null;
}

/* Each section named for what reads the page aloud, by the name the manifest gives it, which
   the heading over it says on the screen. Done once, before anything is drawn into them. */
(function () {
  var body = document.querySelector('#settingsView .settings-body');
  if (!body) return;
  anatomyGroups().forEach(function (g) {
    g.sections.forEach(function (sec) {
      var part = body.querySelector('.settings-section[data-section="' + sec.id + '"]');
      if (part) part.setAttribute('aria-label', sec.name);
    });
  });
})();

/** What a group or a section is called, or '' for neither. @param {string} id */
function settingsGroupName(id) {
  var group = anatomyGroup(id);
  if (group) return group.name;
  var sec = anatomySection(id);
  return sec ? sec.section.name : '';
}

/* What an address under `/anatomy`, or an old one under `/settings`, names, as `settingsOpen`
   takes it: a group, a section, or '' for the status board, and what is opened inside a
   section that has more than one view (a trusted contact, the beats of one quest, Stats'
   event log, one shared gene). A name it does not know is the status board.
   @param {string[]} parts the address's parts after its first @param {boolean} old */
function settingsRead(parts, old) {
  var where = '', rest = [];
  // A section moved on 4 November 2026 has no old address (`genes.MOVED`): Petar, "when I say
  // move, don't leave backup forwarding links". Gone, so the address is the server's to answer,
  // which is not found.
  var moved = anatomyMoved();
  if (old) {
    if (moved.indexOf(parts[0] || '') >= 0) return { where: '', item: '', gone: true };
    if (anatomySection(parts[0] || '')) { where = parts[0]; rest = parts.slice(1); }
  } else if (anatomyGroup(parts[0] || '')) {
    var sec = anatomySection(parts[1] || '');
    if (sec && sec.group === parts[0]) { where = parts[1]; rest = parts.slice(2); }
    else if (parts.length > 1 && moved.indexOf(parts[1] || '') >= 0) return { where: '', item: '', gone: true };
    else where = parts.length === 1 ? parts[0] : '';
  }
  var item = '';
  if (where === 'beats' && rest.length === 1 && /^(\d+|heartbeat)$/.test(rest[0])) item = rest[0];
  else if (where === 'heartbeat' && rest.length === 1 && rest[0] === 'settings') item = rest[0];
  else if (where === 'stats' && rest.length === 1 && rest[0] === 'events') item = rest[0];
  else if (where === 'trusted-contacts' && rest.length === 1 && /^(\d+|grants)$/.test(rest[0])) item = rest[0];
  else if (where === 'gene-pool' && rest.length === 2 && /^[a-z0-9][a-z0-9_-]{0,62}$/.test(rest[0]) &&
           /^[a-z][a-z0-9-]{1,62}$/.test(rest[1])) item = rest.join('/');
  else if (rest.length) where = anatomySection(where) ? anatomySection(where).group : '';
  return { where: where, item: item, gone: false };
}

/* Where Anatomy is, as an address: the status board, a group's page, or the section the
   person was sent to or moved within, with what is opened inside it. */
function settingsAddress() {
  var sec = SETTINGS.section;
  var inside = sec === 'trusted-contacts' ? TC.open : sec === 'beats' ? SETTINGS.beats
    : sec === 'heartbeat' ? SETTINGS.heartbeat
    : sec === 'stats' ? SETTINGS.stats : sec === 'gene-pool' ? SETTINGS.gene : '';
  return '/anatomy' + (SETTINGS.page ? '/' + SETTINGS.page : '') +
    (sec ? '/' + sec + (inside ? '/' + inside : '') : '');
}

/** Whether a section is the page that shows now. @param {string} id */
function sectionShows(id) {
  return !!(SETTINGS.open && id && SETTINGS.section === id);
}

/* Show a group's menu of its sections when named by the group, a section alone when named by
   it, or the status board for ''. Everything is still read and drawn when Anatomy opens,
   whichever page is showing, so each card behaves exactly as it did on Settings' one long
   page. */
function settingsShowGroup(where, item, query) {
  var sec = anatomySection(where);
  var page = sec ? sec.group : anatomyGroup(where) ? where : '';
  var section = sec ? where : '';
  var moved = page !== SETTINGS.page || section !== SETTINGS.section;
  SETTINGS.page = page;
  SETTINGS.section = section;
  var here = function (/** @type {string} */ id) { return !!id && id === section; };
  // One trusted contact opened, or their list (`tcShow`).
  var person = section === 'trusted-contacts' ? String(item || '') : '';
  if (person !== TC.open) {
    TC.open = person;
    if (person) TC.marked = '';
    tcDraw();
  }
  // The status board, a group's menu of its sections, or one section alone.
  var parts = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('#settingsView .settings-section'));
  for (var i = 0; i < parts.length; i++) parts[i].hidden = !here(parts[i].dataset.section || '');
  var menus = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('#settingsView .anatomy-menu'));
  for (var k = 0; k < menus.length; k++) menus[k].hidden = !!section || menus[k].dataset.group !== page;
  $('anatomyBoard').hidden = !!page;
  // The heading names the section, else the group, the person is in. Back above it goes one
  // level up: from a section to its group's menu, and from a group's menu to the board.
  $('settingsTitle').textContent = (sec && sec.section.name) || settingsGroupName(page) || 'Anatomy';
  $('settingsView').classList.toggle('settings-in', !!page);
  // The heartbeat's three views - Today, its beats' table and its settings - take the whole
  // width, the side list put away (`heartbeatpage.js`, `beatspage.js`).
  $('settingsView').classList.toggle('settings-wide', section === 'beats' || section === 'heartbeat');
  var back = /** @type {HTMLAnchorElement} */ ($('settingsBack'));
  var up = section ? settingsGroupName(page) : 'Anatomy';
  back.href = section ? '/anatomy/' + page : '/anatomy';
  back.title = up;
  back.setAttribute('aria-label', 'Back to ' + up);
  /** @type {HTMLElement} */ (back.querySelector('span')).textContent = up;
  var rows = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('#settingsNav .settings-nav-row'));
  for (var j = 0; j < rows.length; j++) {
    var on = rows[j].dataset.group === page;
    rows[j].classList.toggle('on', on);
    if (on) rows[j].setAttribute('aria-current', 'page');
    else rows[j].removeAttribute('aria-current');
  }
  // The beats filtered to one piece of work, `/anatomy/behaviour/beats/<work>`
  // (`beatspage.js`), or every beat for ''.
  // Its search, filters, sort, page and the beat opened are the address's query
  // (`/anatomy/behaviour/beats?q=...&kind=note`), so Back between two of them refilters.
  var beatsFor = section === 'beats' ? String(item || '') : '';
  var beatsQuery = section === 'beats' ? String(query || '').replace(/^\?/, '') : '';
  var refilter = !moved && SETTINGS.open && here('beats') &&
    (beatsFor !== SETTINGS.beats || beatsQuery !== SETTINGS.beatsQuery);
  SETTINGS.beats = beatsFor;
  SETTINGS.beatsQuery = beatsQuery;
  if (refilter && window.RouhBeats) window.RouhBeats.shown(beatsFor, beatsQuery);
  // The heartbeat's view: Today for '', its settings for 'settings' (`heartbeatpage.js`).
  var hbView = section === 'heartbeat' && item === 'settings' ? 'settings' : '';
  var reHeart = !moved && SETTINGS.open && here('heartbeat') && hbView !== SETTINGS.heartbeat;
  SETTINGS.heartbeat = hbView;
  if (reHeart && window.RouhHeartbeat) window.RouhHeartbeat.shown(hbView);
  // Stats' tab, `/anatomy/meta/stats/events` for the event log and the navigation's
  // taps for '' (`statspage.js`).
  var statsTab = section === 'stats' && item === 'events' ? 'events' : '';
  var retab = !moved && SETTINGS.open && here('stats') && statsTab !== SETTINGS.stats;
  SETTINGS.stats = statsTab;
  if (retab && window.RouhStats) window.RouhStats.shown(statsTab);
  // One shared gene's page, `/anatomy/rouh-land/gene-pool/<publisher>/<name>` (`genespage.js`),
  // or the registry and the lab for ''.
  var geneNow = section === 'gene-pool' ? String(item || '') : '';
  var regene = !moved && SETTINGS.open && here('gene-pool') && geneNow !== SETTINGS.gene;
  SETTINGS.gene = geneNow;
  if (regene && window.RouhGenes) window.RouhGenes.shown(geneNow);
  // The contact card hangs on Apple Contacts, which may have been connected
  // a moment ago on another page: read it again on the way in, and the
  // profile with it, whose name may follow the card.
  if (moved && here('about-you') && SETTINGS.open) { meLoad(); profLoad(); }
  // The sections drawn by pages of their own read them on the way in and stop
  // looking once they are left (`heartbeatpage.js`, `paymentspage.js`, ...).
  if (moved || !SETTINGS.open) settingsPages(section);
  if (moved) {
    // What was said was about the page being left.
    settingsSay('');
    var body = $('settingsView').querySelector('.settings-body');
    if (body) body.scrollTop = 0;
  }
  if (!page) anatomyBoardLoad();
}

/** The sections a page of their own draws, told which section shows now. @param {string} section */
function settingsPages(section) {
  var pages = { heartbeat: window.RouhHeartbeat, beats: window.RouhBeats, payments: window.RouhPayments,
                shipping: window.RouhShipping, services: window.RouhServices, signups: window.RouhSignups,
                cloudflare: window.RouhCloudflare, phone: window.RouhPhone, slack: window.RouhSlack, hue: window.RouhHue, dreame: window.RouhDreame,
                'draft-edits': window.RouhDraftEdits,
                'gene-pool': window.RouhGenes, changes: window.RouhChanges, silos: window.RouhSilos,
                stats: window.RouhStats, offline: window.RouhOfflinePanel, 'rouh-profile': window.RouhBirth,
                'your-profile': window.RouhLandAccount, account: window.RouhSignIn };
  for (var name in pages) {
    var drawn = pages[name];
    if (!drawn) continue;
    if (name === section) {
      if (name === 'beats') drawn.shown(SETTINGS.beats, SETTINGS.beatsQuery);
      else drawn.shown(name === 'stats' ? SETTINGS.stats : name === 'gene-pool' ? SETTINGS.gene :
                       name === 'heartbeat' ? SETTINGS.heartbeat : undefined);
    } else drawn.hidden();
  }
  // The Gene Pool's first card, where this Rouh stands in the Pool (`landaccountpage.js`).
  var stand = window.RouhPoolStand;
  if (stand) { if (section === 'gene-pool') stand.shown(); else stand.hidden(); }
}

/* A section, or a card in one, brought to the top of the page and held there while the
   sections above it are still being drawn: each reads its own server and grows when it
   answers, which would otherwise push it down out of sight a moment after it was shown. Held
   until the person scrolls, touches, clicks or types in the page themselves, or for a few
   seconds once nothing has moved. @param {string | Element | null} target */
var PIN = { target: /** @type {Element | null} */ (null), watch: /** @type {ResizeObserver | null} */ (null),
            timer: 0, stop: /** @type {(() => void) | null} */ (null) };
function settingsPin(target) {
  settingsUnpin();
  var body = /** @type {HTMLElement | null} */ ($('settingsView').querySelector('.settings-body'));
  var found = typeof target === 'string'
    ? document.querySelector('#settingsView .settings-section[data-section="' + target + '"]') : target;
  if (!body || !found) return;
  PIN.target = found;
  var place = function () {
    if (!PIN.target || !body) return;
    var gap = PIN.target.getBoundingClientRect().top - body.getBoundingClientRect().top;
    if (Math.abs(gap) > 1) body.scrollTop += gap;
    clearTimeout(PIN.timer);
    PIN.timer = window.setTimeout(settingsUnpin, 2500);
  };
  place();
  requestAnimationFrame(place);
  if (typeof ResizeObserver === 'function') {
    PIN.watch = new ResizeObserver(function () { place(); });
    for (var i = 0; i < body.children.length; i++) PIN.watch.observe(body.children[i]);
  }
  PIN.stop = settingsUnpin;
  ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach(function (ev) {
    body.addEventListener(ev, settingsUnpin, { passive: true });
  });
}

function settingsUnpin() {
  if (PIN.watch) PIN.watch.disconnect();
  clearTimeout(PIN.timer);
  var body = $('settingsView') && $('settingsView').querySelector('.settings-body');
  if (body && PIN.stop) {
    var stop = PIN.stop;
    ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach(function (ev) { body.removeEventListener(ev, stop); });
  }
  PIN.target = null; PIN.watch = null; PIN.stop = null;
}

/* The status board, `/anatomy`: each group's line says what needs attention in it, from the
   server (`rouh/anatomy.py`), with what only this device knows added to Behaviour's, where
   Offline is since 4 November 2026: that it is offline, and what waits to be sent. A group with
   nothing to say is All fine. */
var BOARD = { at: 0, groups: /** @type {any[] | null} */ (null) };
function anatomyBoardLoad() {
  anatomyBoardDraw();
  if (typeof fetch !== 'function' || Date.now() - BOARD.at < 2000) return;
  BOARD.at = Date.now();
  fetch('/api/anatomy', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (got) {
      if (!got || !got.groups) return;
      BOARD.groups = got.groups;
      anatomyBoardDraw();
    })
    .catch(function () {});
}

window.RouhAnatomy = { repaint: function () { if (SETTINGS.open && !SETTINGS.page) anatomyBoardDraw(); } };

function anatomyBoardDraw() {
  var facts = /** @type {Record<string, string[]>} */ ({});
  (BOARD.groups || []).forEach(function (g) {
    facts[g.id] = (g.facts || []).map(function (f) { return String(f.text || ''); });
  });
  var off = window.RouhOffline;
  if (off && !off.online()) (facts.behaviour = facts.behaviour || []).unshift('Offline');
  var waits = off && off.waiting ? off.waiting() : 0;
  if (waits) (facts.behaviour = facts.behaviour || []).push(waits + (waits === 1 ? ' action waits' : ' actions wait') + ' to be sent');
  var lines = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('#anatomyBoard .anatomy-line'));
  for (var i = 0; i < lines.length; i++) {
    var said = facts[lines[i].dataset.group || ''] || [];
    var box = /** @type {HTMLElement} */ (lines[i].querySelector('.anatomy-facts'));
    box.textContent = '';
    lines[i].classList.toggle('needs', said.length > 0);
    if (!BOARD.groups && !said.length) continue;
    if (!said.length) { box.appendChild(el('span', 'anatomy-fine', 'All fine')); continue; }
    said.forEach(function (text) { box.appendChild(el('span', 'anatomy-fact', text)); });
  }
}

/* Anatomy, at its status board (''), a group's page, or a section of one, scrolled to it.
   @param {string} [where] @param {string} [item] */
/** @param {string} [where] @param {string} [item] @param {string} [query] what a section keeps in the address's query */
function settingsOpen(where, item, query) {
  // Where the person was, so closing Anatomy can put it back: it has
  // an address of its own, so the bar no longer holds it (`addrShow`).
  if (!SETTINGS.open) {
    var from = addrRead(location.pathname, location.search);
    SETTINGS.from = from && from.settings === undefined ? from : null;
  }
  settingsShowGroup(where || '', item, query);
  if (!SETTINGS.open) {
    SETTINGS.open = true;
    showLayer('settingsView');
    orbPlace(orbWanted());
    settingsLoad();
    if (window.matchMedia && window.matchMedia('(max-width: 899px)').matches) {
      $('canvasPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  } else addrTouch();
  // A section is a page of its own and opens at its top (`settingsShowGroup`): nothing above it
  // grows and pushes it away, so there is nothing to hold.
  settingsUnpin();
}

/* Rouh was asked to show one group of Settings (`settings_shown`), such as
   Cloudflare, whose tokens are typed there and never into a conversation. A
   desk opens it, unless a page the person is reading is in front; a phone, or
   a desk with such a page up, gets a note with Open. */
/** @param {import('./protocol').FromServer<'settings_shown'>} m */
function settingsShown(m) {
  if (m.chat && CHATS && m.chat !== CHATS.active) return;
  var group = settingsGroupName(m.group) ? m.group : '';
  var open = function () { settingsOpen(group); };
  var layer = layerOpen();
  if (!narrow() && (!layer || layer === 'settingsView')) {
    open();
    return;
  }
  notify('Anatomy' + (group ? ', ' + settingsGroupName(group) : '') + '.',
         { tone: 'info', action: { label: 'Open', run: open }, for: 15000 });
}

function settingsClose() {
  if (!settingsViewing()) return;
  SETTINGS.open = false;
  SETTINGS.editingClient = false;
  // A typed secret does not stay in the page after it is closed.
  $('googleClientSecret').value = '';
  $('applePassword').value = '';
  $('tgApiHash').value = '';
  $('tgCode').value = '';
  $('tgPassword').value = '';
  $('pwCurrent').value = ''; $('pwNew').value = ''; $('pwAgain').value = '';
  $('pwSaid').hidden = true;
  $('googleCalendarSaid').hidden = true;
  APPLE.editing = false;
  clearTimeout(APPLE.timer);
  MAIL.editingTopic = false;
  MAIL.guide = false;
  clearTimeout(MAIL.timer);
  TC.open = '';
  settingsUnpin();
  settingsPages('');
  showLayer(null);
  orbPlace(orbWanted());
  // And back to whatever Settings was opened over (see 10f).
  var from = SETTINGS.from;
  SETTINGS.from = null;
  settingsBack(from);
}

/* Settings was closed with its own close button or Escape, not left for
   somewhere else: the canvas was emptied for it, so what was there goes back,
   down the same one path a link takes. A conversation is left as it is now,
   because a different one picked while Settings was up is where the person
   is. Nothing to put back for an address that was only a conversation, or
   the front door: closing Settings reveals it. */
function settingsBack(from) {
  if (standingDown || ADDR.wanted || !from) return;
  // Settings lay over it, so it is still there.
  if (contentOpen()) return;
  if (!from.kind && !from.browser && !from.web && !from.clock && !from.control &&
      !from.runs && !from.brief && !from.work && from.synapse === undefined) return;
  if (from.kind === 'chat') return;
  var want = {};
  for (var k in from) if (Object.prototype.hasOwnProperty.call(from, k)) want[k] = from[k];
  if (want.chat && want.chat !== (CHATS && CHATS.active)) want.chat = (CHATS && CHATS.active) || '';
  ADDR.wanted = want;
  ADDR.asked = false;
  addrAsk();
}

function settingsSay(text, kind) {
  var box = $('settingsSay');
  box.className = 'settings-say' + (kind ? ' ' + kind : '');
  box.textContent = text || '';
  box.hidden = !text;
}

function settingsLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  locLoad();
  modelsLoad();
  sigLoad();
  profLoad();
  meLoad();
  briefSettingsLoad();
  mboxLoad();
  appleLoad();
  tgLoad();
  mailLoad();
  tcLoad();
  return fetch('/api/settings/google', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('settings ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      SETTINGS.data = data;
      settingsDraw();
      googleCalendarsLoad(data.connection);
    })
    .catch(function () {
      settingsSay('Settings could not be read from the server. Try again in a moment.', 'bad');
    });
}

/* The calendars the Google connection can see, under Calendars on the card
 * (GET /api/settings/google/calendars). Asked for once the rest of the card
 * is drawn rather than with it: it is a call to Google, and the card should
 * not wait on Google to appear. `seq` drops an answer that arrives after a
 * newer question, so a slow Google cannot draw the list of an account that
 * has just been disconnected. */
var CALENDARS = { seq: 0, shown: null };

function googleCalendarsLoad(conn) {
  var part = $('googleCalendarPart');
  var mine = ++CALENDARS.seq;
  if (!conn || !conn.connected || typeof fetch !== 'function') {
    part.hidden = true;
    return;
  }
  part.hidden = false;
  $('googleCalendarState').className = 'settings-help';
  $('googleCalendarState').textContent = 'Asking Google which calendars this account can see...';
  fetch('/api/settings/google/calendars', { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (out) { return { ok: r.ok, out: out }; });
    })
    .then(function (a) {
      if (mine !== CALENDARS.seq) return;
      googleCalendarsDraw(a.ok ? a.out
        : { granted: true, calendars: [], say: a.out.error || 'Google did not list the calendars.' });
    })
    .catch(function () {
      if (mine !== CALENDARS.seq) return;
      googleCalendarsDraw({ granted: true, calendars: [],
        say: 'The calendars could not be read. Try again in a moment.' });
    });
}

function googleCalendarsDraw(d) {
  var list = $('googleCalendarList'), state = $('googleCalendarState');
  var cals = d.calendars || [];
  var account = d.account || 'this account';
  CALENDARS.shown = d;
  list.textContent = '';
  cals.forEach(function (c) {
    var li = el('li');
    var line = el('div', 'me-card-line');
    var words = el('div', 'me-card-words');
    var name = el('span', 'cal-name', c.name || c.id);
    // Whose it is, when that is not the name itself: the person's own
    // calendar shared with Rouh's account, or that account's own.
    if (c.theirs) name.appendChild(el('span', 'cal-whose', 'Yours'));
    else if (c.primary) name.appendChild(el('span', 'cal-whose', 'This account\'s own'));
    words.appendChild(name);
    var can = c.can ? c.can.charAt(0).toUpperCase() + c.can.slice(1) : '';
    words.appendChild(el('span', 'cal-can', can + (c.zone ? ' - ' + c.zone : '')));
    words.appendChild(el('span', 'cal-id mono', c.id));
    line.appendChild(words);
    // The account's own main calendar cannot leave its list: Disconnect
    // above, for the whole account, is how that one goes.
    if (!c.primary) {
      var acts = el('div', 'me-card-acts');
      var off = el('button', 'ctl small', 'Disconnect');
      off.type = 'button';
      off.setAttribute('aria-label', 'Disconnect ' + (c.name || c.id));
      off.addEventListener('click', function () { googleCalendarRemove(c, li, off); });
      acts.appendChild(off);
      line.appendChild(acts);
    }
    li.appendChild(line);
    list.appendChild(li);
  });
  list.hidden = !cals.length;
  // Not granted yet is a note, the same as the one above it; Google failing
  // to answer, with Calendar granted, is a fault.
  state.className = 'settings-help' + (d.say && d.granted ? ' bad' : '');
  state.textContent = d.say || (cals.length
    ? 'Rouh can see ' + cals.length + ' calendar' + (cals.length === 1 ? '' : 's') + ' through ' + account + '.'
    : account + ' has no calendars on its list.');
  $('googleCalendarForm').hidden = !d.granted;
  $('googleCalendarAccount').textContent = account;
  $('googleCalendarShareTo').textContent = account;
  // Sharing your calendar with the account only makes sense when the
  // account is not already you.
  var yours = cals.some(function (c) { return c.theirs && c.primary; });
  $('googleCalendarShareTo').parentNode.hidden = yours;
}

/* Take one calendar off the account's list (fr_6d4c861d976e): Rouh stops
 * reading it and acting on it, and nothing changes at Google. Gone from the
 * list the moment Google agrees; a refusal leaves the row where it was, with
 * the reason under it. */
function googleCalendarRemove(c, li, button) {
  var name = c.name || c.id;
  if (!window.confirm('Disconnect ' + name + '? Rouh stops reading and changing it. '
      + 'The calendar and its events stay as they are in Google Calendar.')) return;
  var said = li.querySelector('.cal-can.bad');
  if (said) said.remove();
  button.disabled = true;
  fetch('/api/settings/google/calendars/remove', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ calendar: c.id }),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
      function () { return { ok: false, out: {} }; });
  }).then(function (a) {
    if (!a.ok) return refused(a.out && a.out.error);
    var d = CALENDARS.shown || {};
    googleCalendarsDraw(Object.assign({}, d, {
      calendars: (d.calendars || []).filter(function (one) { return one.id !== c.id; }),
    }));
  }).catch(function () { refused(''); });

  function refused(why) {
    button.disabled = false;
    li.querySelector('.me-card-words').appendChild(el('span', 'cal-can bad',
      name + ' could not be removed. ' + (why || 'Try again in a moment.')));
  }
}

// When something was last changed, said the way a person says it.
function whenWords(unixSeconds) {
  if (!unixSeconds) return '-';
  var d = new Date(unixSeconds * 1000);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' }) +
         ', ' + clockOf(unixSeconds);
}

function settingsDraw() {
  var d = SETTINGS.data;
  if (!d) return;
  var setup = d.setup || {}, conn = d.connection || {};

  $('googleApis').textContent = (setup.apis || []).join(', ');
  $('googleRedirect').textContent = setup.redirect_uri || '';

  // (1) The organisation's app. An ordinary member never gets this part.
  var mayEdit = !!setup.may_edit;
  $('googleOrgPart').hidden = !mayEdit;
  $('googleOrgLocked').hidden = mayEdit;
  if (mayEdit) {
    var done = !!setup.configured;
    var editing = SETTINGS.editingClient || !done;
    $('googleNotSetUp').hidden = done;
    $('googleOrgState').hidden = !done;
    if (done) {
      $('googleClientIdShown').textContent = setup.client_id || '';
      $('googleSecretState').textContent = setup.secret_set
        ? 'Set, last changed ' + whenWords(setup.secret_changed_at)
        : 'Not set';
    }
    // The guide is in the way once it has been followed, and is exactly what
    // is wanted while it has not.
    $('googleGuide').hidden = done && !editing;
    $('googleClientForm').hidden = !editing;
    $('googleCancelClient').hidden = !done;
    $('googleClientActions').hidden = editing || !done;
    $('googleSaveClient').textContent = done ? 'Replace' : 'Save';
    if (!editing) $('googleClientSaid').hidden = true;
  }

  // (2) This person's own connection.
  var connected = !!conn.connected;
  $('googleNotConnected').hidden = connected;
  $('googleConnState').hidden = !connected;
  $('googleDisconnect').hidden = !connected;
  if (connected) {
    $('googleAccount').textContent = conn.email || '(address not known)';
    $('googleWhen').textContent = whenWords(conn.connected_at);
    $('googleCaps').textContent = (conn.capabilities || []).join(', ') || 'none';
  }
  // Two different things say "press Connect again", and the page has to tell
  // them apart. A withdrawn grant is the Google account saying no. A grant
  // that is older than what Rouh now asks for - sending mail, drafts,
  // editing documents, calendars - is nothing being wrong at all, so it is
  // said as a note rather than as a fault, and the button says what it will do.
  var more = !!conn.needs_more_access;
  $('googleTrouble').hidden = !(conn.needs_reconnect || more);
  $('googleTrouble').classList.toggle('bad', !!conn.needs_reconnect && !more);
  if (more) {
    $('googleTrouble').textContent = conn.trouble
      || 'Rouh needs more access to this Google account than it was given. '
       + 'Press the button below to grant it.';
  } else if (conn.needs_reconnect) {
    $('googleTrouble').textContent =
      'Google has withdrawn this connection. Connect the account again.';
  }
  var can = !!d.can_connect;
  $('googleConnect').disabled = !can;
  $('googleConnect').textContent = more ? 'Grant the new access'
    : (connected ? 'Reconnect' : 'Connect Google');
  // Why the button is off, said to the person who can do something about it.
  // An administrator is told to fill the form above; everybody else is told
  // whose job it is, because they have no form to fill.
  $('googleWhyOff').textContent = mayEdit
    ? 'Enter your organisation\'s Google app above before you can connect an account.'
    : 'Your organisation has to register its Google app before anyone can connect an account.';
  $('googleWhyOff').hidden = can;

}

// Edit, behind the person's own name: their profile, a group of Settings
// (fr_02048b1ef832). It opens over the canvas, which is underneath the drawer
// the name is in, so the drawer goes first. A link, so Cmd-click is the
// browser's (`helpers.js`).
$('profileBtn').addEventListener('click', function (e) {
  if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
  accountMenu(false);
  sidebarDone();
  settingsOpen('about-you');
});
$('settingsClose').addEventListener('click', settingsClose);

// A group in the settings sidebar. A real link, so it can be opened in a
// new tab; an ordinary press moves within the page, and the address follows.
$('settingsNav').addEventListener('click', function (e) {
  var row = e.target.closest('.settings-nav-row');
  if (!row || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  settingsOpen(row.dataset.group);
});

// Back one level: from a section to its group's menu, or from a group's menu to
// the status board. A link, for the same reasons a row is one.
$('settingsBack').addEventListener('click', function (e) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  settingsOpen(SETTINGS.section ? SETTINGS.page : '');
});

// A line of the status board opens its group's menu, and a line of a menu its
// section, in place. Links too, so Cmd-click opens one in a tab of its own.
$('settingsView').querySelector('.settings-body').addEventListener('click', function (e) {
  var line = /** @type {HTMLElement | null} */ (/** @type {Element} */ (e.target).closest('a.anatomy-line'));
  if (!line || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  settingsOpen(line.dataset.section || line.dataset.group || '');
});

$('googleCopyRedirect').addEventListener('click', function () {
  var text = $('googleRedirect').textContent || '';
  var button = $('googleCopyRedirect');
  var done = function () {
    button.textContent = 'Copied';
    setTimeout(function () { button.textContent = 'Copy'; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, done);
  } else {
    done();
  }
});

$('googleReplaceClient').addEventListener('click', function () {
  SETTINGS.editingClient = true;
  $('googleClientSecret').value = '';
  settingsDraw();
  $('googleClientSecret').focus();
});

$('googleCancelClient').addEventListener('click', function () {
  SETTINGS.editingClient = false;
  $('googleClientSecret').value = '';
  $('googleClientSaid').hidden = true;
  settingsDraw();
});

$('googleClientForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var said = $('googleClientSaid');
  said.hidden = true;
  var body = JSON.stringify({
    client_id: $('googleClientId').value.trim(),
    client_secret: $('googleClientSecret').value,
  });
  // The secret leaves the page in this one request and is wiped out of the
  // box whatever the answer is: a form left holding it is a screenshot away
  // from being somewhere else.
  $('googleClientSecret').value = '';
  $('googleSaveClient').disabled = true;
  fetch('/api/settings/google/client', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: body,
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    $('googleSaveClient').disabled = false;
    if (!answer.ok) {
      said.textContent = answer.out.error || 'That was not accepted.';
      said.hidden = false;
      return;
    }
    SETTINGS.editingClient = false;
    settingsSay('Your organisation\'s Google app is saved. Anyone here can now connect their account.', 'good');
    return settingsLoad();
  }).catch(function () {
    $('googleSaveClient').disabled = false;
    said.textContent = 'That could not be saved. Try again in a moment.';
    said.hidden = false;
  });
});

$('googleRemoveClient').addEventListener('click', function () {
  fetch('/api/settings/google/client/remove', {
    method: 'POST', credentials: 'same-origin',
  }).then(function () {
    SETTINGS.editingClient = false;
    settingsSay('Your organisation\'s Google app has been removed. Nobody here can connect an account until a new one is entered.', null);
    return settingsLoad();
  });
});


$('googleCalendarForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var said = $('googleCalendarSaid');
  var wanted = $('googleCalendarId').value.trim();
  said.hidden = true;
  if (!wanted) {
    said.className = 'settings-help bad';
    said.textContent = 'Enter the calendar\'s id: for a person\'s own calendar, their email address.';
    said.hidden = false;
    return;
  }
  $('googleCalendarAdd').disabled = true;
  fetch('/api/settings/google/calendars/add', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ calendar: wanted }),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (a) {
    $('googleCalendarAdd').disabled = false;
    if (!a.ok) {
      said.className = 'settings-help bad';
      said.textContent = a.out.error || 'Google would not add that calendar.';
      said.hidden = false;
      return;
    }
    var cal = a.out.calendar || {};
    $('googleCalendarId').value = '';
    said.className = 'settings-help';
    said.textContent = 'Added ' + (cal.name || wanted) + '. Rouh ' + (cal.can || 'can see it') + '.';
    said.hidden = false;
    googleCalendarsLoad(SETTINGS.data && SETTINGS.data.connection);
  }).catch(function () {
    $('googleCalendarAdd').disabled = false;
    said.className = 'settings-help bad';
    said.textContent = 'That calendar could not be added. Try again in a moment.';
    said.hidden = false;
  });
});

$('googleConnect').addEventListener('click', function () {
  // A full page visit, not a fetch: the consent screen is Google's own page
  // and the person has to see it, read it and press the button on it.
  location.href = '/auth/google/start';
});

$('googleDisconnect').addEventListener('click', function () {
  $('googleDisconnect').disabled = true;
  fetch('/auth/google/disconnect', { method: 'POST', credentials: 'same-origin' })
    .then(function () {
      $('googleDisconnect').disabled = false;
      settingsSay('That Google account is disconnected and its tokens are gone.', null);
      return settingsLoad();
    })
    .catch(function () {
      $('googleDisconnect').disabled = false;
      settingsSay('Google could not be disconnected. Try again in a moment.', 'bad');
    });
});

/* ---------- Settings: Models ----------
 *
 * Petar, 23 October 2026 (card 1842): the mode first, Best, Balanced or Saver, the one
 * choice most people make; everything below it is behind Customise, closed until
 * pressed: the router's bar, the two tiers and every use. Saver says once, as it is
 * picked, that unattended runs on the cheap model can make mistakes and deploy them.
 *
 * Two tiers, Cheaper and Smart (Daily and Best until that day), each holding one of OpenAI's models and
 * one of Anthropic's, and every use of a model on a tier or on a model of its
 * own (`rouh/modeldefaults.py`). Petar, 18 October 2026: "most Rouh users will
 * not know which model to pick." And that evening, from his iPhone: every row
 * shows the model it really asks, a use is one line, its choices are icons, and
 * a tier or a use can be locked, and each box (the tiers, Each use) has its own
 * Auto, which follows the Rouh model service, and Sync, which copies it once.
 * The organisation's, so only its administrators may change them; everybody
 * else sees them, greyed.
 *
 * A press is saved the moment it is made, and the page is drawn again from
 * what the server answers, so it never shows something that was not saved.
 * Nothing is said when it worked: the control has moved. Every tab is told
 * too (`model_defaults` on the socket).
 */

/* The agents' sign-ins on the Models page (`rouh/web/codex_signin.py`): drawn only where
   /setup/codex answers, which is the containers. The button posts the page's own form, so
   the sign-in goes on at /setup/codex with its code; here is only where it stands. */
function agentsSigninLoad() {
  var card = $('agentsSignin');
  if (!card || typeof fetch !== 'function') return;
  var json = function (r) { return r.ok ? r.json() : null; };
  fetch('/setup/codex/state', { credentials: 'same-origin', cache: 'no-store' }).then(json).then(function (s) {
    if (!s) { card.hidden = true; return; }
    card.hidden = false;
    $('agentCodexSaid').textContent = s.state === 'signed_in' ? s.said.replace(/^Codex: /, '')
      : s.state === 'waiting' ? 'Waiting for its code to be approved.'
      : s.state === 'starting' ? 'The worker is not answering yet.'
      : s.failed ? 'Not signed in. The last try failed.' : 'Not signed in.';
    var start = /** @type {HTMLButtonElement} */ ($('agentCodexStart'));
    $('agentCodexForm').hidden = s.state === 'signed_in' || s.state === 'waiting';
    start.disabled = s.state === 'starting';
    start.textContent = s.failed ? 'Try again' : 'Sign in Codex with ChatGPT';
    $('agentCodexOpen').hidden = !$('agentCodexForm').hidden;
    $('agentCodexRow').classList.toggle('on', s.state === 'signed_in');
  }).catch(function () { card.hidden = true; });
  fetch('/setup/claude/state', { credentials: 'same-origin', cache: 'no-store' }).then(json).then(function (s) {
    if (!s) return;
    $('agentClaudeSaid').textContent = s.state === 'signed_in' ? 'Signed in.'
      : s.state === 'starting' ? 'The worker is not answering yet.'
      : s.state === 'waiting_for_code' ? 'Waiting for its code.' : 'Not signed in.';
    $('agentClaudeRow').classList.toggle('on', s.state === 'signed_in');
  }).catch(function () { /* the row keeps what it said */ });
}

function modelsLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  agentsSigninLoad();
  return fetch('/api/settings/models', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('models ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      MODELS.data = data;
      modelsDraw();
    })
    .catch(function () {
      $('modelsWhen').textContent = 'The models could not be read from the server. ' +
        'Try again in a moment.';
    });
}

/* "Opus 5.5 · Medium": a model and the level it thinks at. */
function modelsLine(name, effortName) {
  return name + (effortName ? ' · ' + effortName : '');
}

/* The small mark on the choice the standard recommends, here and in the chooser. */
function modelsMark() {
  var mark = el('span', 'models-rec');
  mark.setAttribute('aria-hidden', 'true');
  return mark;
}

/* One icon for each choice a use can be on, the same above each tier's name:
   Off, Cheaper (a leaf), Daily (the sun), Best (a star), Custom (sliders),
   and the lock, shut and open. Drawn in the text colour, 16 pixels. */
var MODEL_ICONS = {
  off: ['M12 3v8', 'M7.05 6.05a7 7 0 1 0 9.9 0'],
  smart: ['M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z'],
  cheaper: ['M5 19c0-8 5-13 14-14 0 9-5 14-13 14z', 'M5 19l7-7'],
  daily: ['M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 1 0 0-7z',
    'M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8'],
  best: ['M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z'],
  custom: ['M4 7h9M17 7h3M4 17h3M11 17h9', 'M15 5v4M9 15v4'],
  locked: ['M6.5 11h11v9h-11z', 'M9 11V8a3 3 0 0 1 6 0v3'],
  unlocked: ['M6.5 11h11v9h-11z', 'M9 11V8a3 3 0 0 1 5.8-1.1'],
};

function modelsIcon(kind) {
  var svg = svgEl('svg', { viewBox: '0 0 24 24', width: '16', height: '16', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false', 'class': 'models-icon' });
  (MODEL_ICONS[kind] || []).forEach(function (d) { svg.appendChild(svgEl('path', { d: d })); });
  return svg;
}

/* The lock beside a tier or a use: pressed is locked. */
function modelsLock(item, label) {
  var b = /** @type {HTMLButtonElement} */ (el('button', 'models-lock'));
  b.type = 'button';
  b.setAttribute('data-lock', item);
  b.addEventListener('click', function () {
    modelsSave({ which: item, lock: b.getAttribute('aria-pressed') !== 'true' });
  });
  b.__label = label;
  return b;
}

function modelsLockDraw(b, on, locked) {
  if (b.getAttribute('aria-pressed') !== String(on)) {
    b.textContent = '';
    b.appendChild(modelsIcon(on ? 'locked' : 'unlocked'));
  }
  b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', 'Lock ' + b.__label);
  b.title = on ? 'Locked: Auto, Sync, Reset to defaults and a new standard leave it as it is'
    : 'Not locked';
  b.disabled = locked || MODELS.saving;
}

/* The three modes, one press each, the picked one filled, the service's default with
   the dot. Each says in a few words which model answers, by the tiers' models now. */
function modesDraw(d, locked) {
  var box = $('modelsModes');
  if (!box) return;
  var tier = function (id) {
    return (d.tiers.filter(function (t) { return t.id === id; })[0] || {}).model_name || 'a model with a key';
  };
  var said = {
    best: 'Always ' + tier('smart'),
    balanced: tier('smart') + ', or ' + tier('cheaper') + ' when a message is easy',
    saver: 'Always ' + tier('cheaper')
  };
  if (!box.firstChild) {
    (d.modes || []).forEach(function (m) {
      var b = /** @type {HTMLButtonElement} */ (el('button', 'models-mode'));
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('data-mode', m.id);
      var name = el('span', 'models-mode-name', m.name);
      if (m.id === d.mode_default) name.appendChild(modelsMark());
      b.appendChild(name);
      b.appendChild(el('span', 'models-mode-said'));
      b.addEventListener('click', function () {
        if (b.getAttribute('aria-checked') === 'true') return;
        modelsSave({ which: 'mode', mode: m.id }, m.id === 'saver' ? function () {
          notify('Saver is on. Unattended runs on the cheap model can make mistakes and deploy them.',
            { tone: 'warning', for: 12000 });
        } : null);
      });
      box.appendChild(b);
    });
  }
  (d.modes || []).forEach(function (m) {
    var b = /** @type {HTMLButtonElement} */ (box.querySelector('[data-mode="' + m.id + '"]'));
    if (!b) return;
    var on = m.id === d.mode;
    b.setAttribute('aria-checked', String(on));
    b.tabIndex = on ? 0 : -1;
    b.disabled = locked || MODELS.saving;
    b.title = m.why || '';
    b.querySelector('.models-mode-said').textContent = said[m.id] || '';
  });
  $('modesLocked').hidden = !locked;
  // The router's bar, under Customise.
  var bar = /** @type {HTMLInputElement} */ ($('modelsBar'));
  var pct = Math.round((d.bar || 0.9) * 100);
  if (document.activeElement !== bar) bar.value = String(pct);
  $('modelsBarVal').textContent = bar.value + '%';
  bar.disabled = locked || MODELS.saving;
  var back = /** @type {HTMLButtonElement} */ ($('modelsBarService'));
  back.hidden = !d.bar_set;
  back.textContent = 'Use the service\'s (' + Math.round((d.bar_standard || 0.9) * 100) + '%)';
  back.disabled = locked || MODELS.saving;
}

function modelsDraw() {
  var d = MODELS.data;
  if (!d || !d.tiers) return;
  var locked = !d.can_change;
  modesDraw(d, locked);
  var box = $('modelsTiers');
  if (!box.firstChild) {
    d.tiers.forEach(function (t) {
      var card = el('div', 'models-tier');
      card.setAttribute('data-tier', t.id);
      var b = /** @type {HTMLButtonElement} */ (el('button', 'models-tier-open'));
      b.type = 'button';
      var name = el('span', 'models-tier-name');
      name.appendChild(modelsIcon(t.id));
      name.appendChild(el('span', null, t.name));
      b.appendChild(name);
      b.appendChild(el('span', 'models-tier-model'));
      b.appendChild(el('span', 'models-tier-other'));
      b.appendChild(el('span', 'models-tier-note'));
      b.addEventListener('click', function () { pickOpen({ tier: t.id }); });
      card.appendChild(b);
      card.appendChild(modelsLock(t.id, t.name));
      box.appendChild(card);
    });
  }
  d.tiers.forEach(function (t) {
    var card = box.querySelector('[data-tier="' + t.id + '"]');
    if (!card) return;
    var b = /** @type {HTMLButtonElement} */ (card.querySelector('.models-tier-open'));
    // With the box on Auto every selection shows what the service sets and cannot be changed.
    b.disabled = locked || MODELS.saving || !!d.auto.tiers;
    // The model asked here, the first on the list with a key; then the rest that could
    // answer, in order. One with no key here is named only in the chooser.
    card.querySelector('.models-tier-model').textContent = t.none ? 'No model with a key here'
      : modelsLine(t.model_name, t.effort_name);
    var rest = (t.models || []).filter(function (m) { return !m.asked && m.has_key; });
    var other = card.querySelector('.models-tier-other');
    other.textContent = rest.length ? 'Then ' + rest.map(function (m) { return m.name; }).join(', ') : '';
    other.hidden = !rest.length;
    var note = card.querySelector('.models-tier-note');
    var keyless = (t.models || []).filter(function (m) { return !m.has_key; }).length;
    note.textContent = keyless ? keyless + ' more without a key' : '';
    note.hidden = !keyless;
    b.setAttribute('aria-label', t.name + ': ' + (t.none ? 'no model with a key here' : t.model_name +
      (t.effort_name ? ', ' + t.effort_name.toLowerCase() + ' reasoning' : '')) +
      (rest.length ? ', then ' + rest.map(function (m) { return m.name; }).join(', ') : '') +
      '. Change the list');
    modelsLockDraw(/** @type {HTMLButtonElement} */ (card.querySelector('.models-lock')), t.locked, locked);
  });
  // Each box's Auto, and its Sync and Reset, which are for the manual settings: so
  // only with that box's Auto off.
  MODELS_BOXES.forEach(function (box) {
    var auto = $('modelsAuto' + box.key);
    auto.setAttribute('aria-checked', String(!!d.auto[box.id]));
    /** @type {HTMLButtonElement} */ (auto).disabled = locked || MODELS.saving;
    var sync = /** @type {HTMLButtonElement} */ ($('modelsSync' + box.key));
    sync.hidden = !!d.auto[box.id];
    sync.disabled = locked || MODELS.saving;
    var reset = /** @type {HTMLButtonElement} */ ($('modelsReset' + box.key));
    reset.hidden = !!d.auto[box.id] || !d.differs[box.id];
    reset.disabled = locked || MODELS.saving;
  });
  providersDraw(d, locked);
  sharingDraw(d, locked);
  var st = d.standard || {};
  // The public site it is fetched from, by its own name (`rouh/site.py`). 'rouh.it' as the
  // source is only the word the server marks a fetched standard with, not an address.
  var site = String(st.url || '').split('/')[2] || 'rouh.land';
  $('modelsStandard').textContent = 'The standard now is ' + (st.revision || '') +
    (st.source === 'rouh.it' ? ', from ' + site : ', built into this Rouh') +
    (st.checked_at ? ' (' + site + ' last checked ' + whenWords(st.checked_at) +
      (st.checked_ok ? '' : ', and it did not answer') + ')' : '') + '.';
  $('poolRate').textContent = Math.round((d.double_rate || 0) * 1000) / 10 + '%';
  modelUsesDraw(d, locked);
  $('modelsLocked').hidden = !locked;
  $('modelsWhen').textContent = d.changed_at && (d.differs.tiers || d.differs.uses)
    ? 'Last changed by ' + (d.changed_by || 'somebody') + ', ' + whenWords(d.changed_at) + '.' : '';
  // The This page side names its model, which is Ask AI's.
  var tag = $('askModel');
  if (tag && d.work_model_name) {
    tag.textContent = d.work_model_name;
    tag.title = 'Ask AI answers with ' + d.work_model_name + ' (' + d.work_model + ')' +
      (d.work_effort ? ', thinking at ' + d.work_effort + ' effort' : '');
  }
  if ($('tierDialog').open) pickFill();
}

/* Every use of a model, grouped by area, each one line: its name, an (i) with
   what it is, the model it asks now and why it starts where it does, its
   choices as one control of icons, and its lock. Built once and then only
   brought up to date, so a press in the middle of the list keeps its place and
   its focus. */
function modelUsesDraw(d, locked) {
  var box = $('modelUses');
  if (!box || !d.uses) return;
  if (!box.firstChild) {
    (d.groups || []).forEach(function (group) {
      var uses = d.uses.filter(function (u) { return u.group === group; });
      if (!uses.length) return;
      var part = el('div', 'mu-group');
      part.setAttribute('role', 'group');
      var head = el('h5', null, group);
      head.id = 'muGroup' + group.replace(/[^A-Za-z]/g, '');
      part.setAttribute('aria-labelledby', head.id);
      part.appendChild(head);
      uses.forEach(function (u) { part.appendChild(modelUseRow(u)); });
      box.appendChild(part);
    });
  }
  d.uses.forEach(function (u) {
    var row = box.querySelector('[data-use="' + u.id + '"]');
    if (!row) return;
    var now = u.tier === 'off' ? (u.off_said || 'Off') : modelsLine(u.model_name, u.effort_name);
    // Beside the control when the card has room: the model a tier gives it, over its
    // level. Custom says its model in the control, Off says itself, and a routed
    // chat says so on a line of its own.
    var nowBox = row.querySelector('.mu-now');
    nowBox.textContent = '';
    if (u.tier !== 'off' && u.tier !== 'custom' && !u.routed && u.model) {
      nowBox.appendChild(el('span', null, u.model_name));
      if (u.effort_name) nowBox.appendChild(el('span', 'mu-custom-effort', u.effort_name));
    }
    var choiceName = (u.options.filter(function (o) { return o.id === u.tier; })[0] || {}).name || '';
    // Its list, first asked first, the one asked named and one with no key said so.
    var listed = (u.list || []).map(function (m) {
      return m.name + (m.has_key ? '' : ' (no key)');
    }).join(', then ');
    row.querySelector('.mu-asks').textContent = u.tier === 'off' ? now
      : !u.model ? 'No model on its list has a key here' + (listed ? ': ' + listed + '.' : '.')
      : u.routed ? 'In Balanced the router picks Cheaper or Smart for each message; ' +
        choiceName + ' (' + modelsLine(u.model_name, u.effort_name) + ') answers when it is not sure.'
      : 'Asks ' + modelsLine(u.model_name, u.effort_name) +
        (u.tier === 'custom' ? ', its own pick.' : ', from ' + choiceName + '.') +
        ((u.list || []).length > 1 ? ' Its list: ' + listed + '.' : '');
    var routed = row.querySelector('.mu-note');
    var modeName = ((d.modes || []).filter(function (m) { return m.id === d.mode; })[0] || {}).name || '';
    routed.textContent = u.routed ? 'The router picks for each message.'
      : u.moved ? modeName + ' puts it on ' + choiceName + '.' : '';
    routed.hidden = !routed.textContent;
    var recName = (u.options.filter(function (o) { return o.id === u.recommended; })[0] || {}).name;
    row.querySelector('.mu-why').textContent = (recName ? 'The standard puts it on ' + recName + '. ' : '') +
      (u.recommended_why || '') + (u.needs ? ' It can only ask ' +
      (d.provider_names || {})[u.only] + ': ' + u.needs : '') +
      (u.fallback_said && !u.blocked ? ' ' + u.fallback_said : '');
    // A model that cannot be asked here is said plainly under the line, never swapped.
    var stop = row.querySelector('.mu-blocked');
    stop.textContent = u.blocked || '';
    stop.hidden = !u.blocked;
    Array.prototype.forEach.call(row.querySelectorAll('.mu-opt'), function (node) {
      var b = /** @type {HTMLButtonElement} */ (node);
      var o = u.options.filter(function (x) { return x.id === b.getAttribute('data-choice'); })[0];
      if (!o) return;
      var on = o.id === u.tier;
      b.setAttribute('aria-pressed', String(on));
      b.disabled = locked || MODELS.saving || !!d.auto.uses;
      var custom = !!(u.custom && u.custom.length);
      var said = o.id === 'custom' ? (custom ? modelsLine(u.model_name || 'No key', u.effort_name) : 'Custom')
        : o.model_name ? o.name + ': ' + modelsLine(o.model_name, o.effort_name)
        : (u.off_said || o.name);
      b.setAttribute('aria-label', (o.id === 'custom' && custom ? 'Custom: ' : '') + said +
        (o.id === u.recommended ? ' (recommended)' : ''));
      b.title = (o.id === 'custom' && custom ? 'Custom: ' : '') + said;
      if (o.id === 'custom') {
        // On Custom the control says the model, not the word.
        var word = /** @type {HTMLElement} */ (b.querySelector('.mu-custom-name'));
        var icon = /** @type {SVGElement} */ (b.querySelector('.models-icon'));
        // The model over its level, two short lines, so the row stays one line on a phone.
        word.textContent = '';
        if (custom) {
          word.appendChild(el('span', null, u.model_name || 'No key'));
          if (u.effort_name) word.appendChild(el('span', 'mu-custom-effort', u.effort_name));
        }
        word.hidden = !custom;
        if (icon) icon.style.display = custom ? 'none' : '';
      }
    });
    modelsLockDraw(/** @type {HTMLButtonElement} */ (row.querySelector('.models-lock')), u.locked, locked);
  });
}

function modelUseRow(u) {
  var row = el('div', 'mu-row');
  row.setAttribute('data-use', u.id);
  var top = el('div', 'mu-top');
  var name = el('span', 'mu-name', u.name);
  name.id = 'mu-' + u.id + '-name';
  var info = /** @type {HTMLButtonElement} */ (el('button', 'tc-info', 'i'));
  info.type = 'button';
  info.setAttribute('aria-expanded', 'false');
  info.setAttribute('aria-controls', 'mu-' + u.id + '-said');
  info.setAttribute('aria-label', 'About ' + u.name);
  top.appendChild(name);
  top.appendChild(info);
  var said = el('div', 'mu-said');
  said.id = 'mu-' + u.id + '-said';
  said.hidden = true;
  said.appendChild(el('p', 'mu-asks'));
  said.appendChild(el('p', null, u.said));
  said.appendChild(el('p', 'mu-why'));
  info.addEventListener('click', function () {
    said.hidden = !said.hidden;
    info.setAttribute('aria-expanded', String(!said.hidden));
  });
  var seg = el('div', 'mu-seg');
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-labelledby', name.id);
  u.options.forEach(function (o) {
    var b = /** @type {HTMLButtonElement} */ (el('button', 'mu-opt'));
    b.type = 'button';
    b.setAttribute('data-choice', o.id);
    b.appendChild(modelsIcon(o.id));
    if (o.id === 'custom') {
      var word = el('span', 'mu-custom-name');
      word.hidden = true;
      b.appendChild(word);
    }
    if (o.id === u.recommended) b.appendChild(modelsMark());
    b.addEventListener('click', function () {
      if (o.id === 'custom') pickOpen({ use: u.id });
      else if (b.getAttribute('aria-pressed') !== 'true') modelsSave({ which: u.id, tier: o.id });
    });
    seg.appendChild(b);
  });
  row.appendChild(top);
  row.appendChild(el('span', 'mu-now'));
  row.appendChild(seg);
  row.appendChild(modelsLock(u.id, u.name));
  var note = el('p', 'mu-note');
  note.hidden = true;
  row.appendChild(note);
  var stop = el('p', 'mu-blocked');
  stop.hidden = true;
  stop.setAttribute('role', 'status');
  row.appendChild(stop);
  row.appendChild(said);
  return row;
}

/* The chooser: a tier's list of models, or a use's own (Custom), first asked first, with
   arrows to move one up or down and a cross to take it off; and under it every provider's
   models, a press adding one to the end of the list or taking it off. Each press is saved,
   and it stays open until Done. The dot is the standard's choice. A provider with no key
   here is said so over its column, and a model of a provider a use cannot ask is greyed. */
var TIER_PICK = { tier: '', use: '' };

function pickOpen(what) {
  TIER_PICK.tier = what.tier || '';
  TIER_PICK.use = what.use || '';
  $('tierMore').hidden = true;
  $('tierInfo').setAttribute('aria-expanded', 'false');
  pickFill();
  var dlg = /** @type {HTMLDialogElement} */ ($('tierDialog'));
  dlg.showModal();
  $('tierHead').focus();
}

/** The list the chooser edits now, as ids. */
function pickList(t, u) {
  if (t) return (t.models || []).map(function (m) { return m.id; });
  return (u.custom && u.custom.length) ? u.custom.slice() : (u.list || []).map(function (m) { return m.id; });
}

function pickSave(list) {
  if (TIER_PICK.tier) modelsSave({ which: TIER_PICK.tier, models: list });
  else modelsSave({ which: TIER_PICK.use, models: list });
}

function pickFill() {
  var d = MODELS.data;
  if (!d) return;
  var t = TIER_PICK.tier && d.tiers.filter(function (x) { return x.id === TIER_PICK.tier; })[0];
  var u = TIER_PICK.use && d.uses.filter(function (x) { return x.id === TIER_PICK.use; })[0];
  if (!t && !u) return;
  var names = d.provider_names || {};
  $('tierHeadWords').textContent = t ? t.name : u.name;
  $('tierMoreUse').hidden = !u;
  if (u) {
    $('tierMoreUse').textContent = 'Models of its own for ' + u.name + ', whatever its tier says.' +
      (u.only ? ' It can only ask ' + names[u.only] + '.' : '');
  }
  var all = {};
  Object.keys(d.models || {}).forEach(function (p) {
    (d.models[p] || []).forEach(function (m) { all[m.id] = m; });
  });
  var list = pickList(t, u);
  var standard = t ? (t.standard || []) : [u.recommended_model];
  var can = !d.can_change || MODELS.saving;
  // The list, in order.
  var order = $('tierOrder');
  order.textContent = '';
  list.forEach(function (id, i) {
    var m = all[id] || { id: id, name: id, company: '', effort_name: '', has_key: false };
    var li = el('li', 'tier-order-row' + (m.has_key ? '' : ' no-key'));
    var words = el('span', 'tier-order-words');
    var name = el('span', 'tier-model-name', m.name);
    if (standard.indexOf(id) >= 0 && i === standard.indexOf(id)) name.appendChild(modelsMark());
    words.appendChild(name);
    words.appendChild(el('span', 'tier-model-effort', (names[m.company] || '') +
      (m.effort_name ? ' · ' + m.effort_name : '') + (m.has_key ? '' : ' · no key here')));
    li.appendChild(words);
    var acts = el('span', 'tier-order-acts');
    /** @type {{ act: string, mark: string, said: string, no: boolean }[]} */
    var buttons = [{ act: 'up', mark: '↑', said: 'Move ' + m.name + ' up', no: i === 0 },
      { act: 'down', mark: '↓', said: 'Move ' + m.name + ' down', no: i === list.length - 1 },
      { act: 'off', mark: '×', said: 'Take ' + m.name + ' off the list', no: list.length === 1 }];
    buttons.forEach(function (a) {
      var b = /** @type {HTMLButtonElement} */ (el('button', 'tier-order-btn', a.mark));
      b.type = 'button';
      b.setAttribute('aria-label', a.said);
      b.title = a.said;
      b.disabled = can || a.no;
      b.addEventListener('click', function () {
        var next = list.slice();
        if (a.act === 'off') next.splice(i, 1);
        else {
          var j = a.act === 'up' ? i - 1 : i + 1;
          next[i] = next[j]; next[j] = id;
        }
        pickSave(next);
      });
      acts.appendChild(b);
    });
    li.appendChild(acts);
    order.appendChild(li);
  });
  // Every provider's models, to add or take off.
  var cols = $('tierCols');
  cols.textContent = '';
  Object.keys(d.models || {}).forEach(function (p) {
    var cannot = !!(u && (u.providers || []).indexOf(p) < 0);
    var col = el('div', 'tier-col' + (cannot ? ' off' : ''));
    col.setAttribute('role', 'group');
    var head = el('h3', null, names[p] || p);
    head.id = 'tierCol-' + p;
    col.setAttribute('aria-labelledby', head.id);
    col.appendChild(head);
    var prov = (d.providers || []).filter(function (x) { return x.id === p; })[0] || {};
    var said = cannot ? (u.name + ' cannot ask ' + (names[p] || p) + '.') : prov.has ? '' : 'No key here yet.';
    var note = el('p', 'tier-col-note', said);
    note.hidden = !said;
    col.appendChild(note);
    var box = el('div', 'tier-models');
    (d.models[p] || []).forEach(function (m) {
      var b = /** @type {HTMLButtonElement} */ (el('button', 'tier-model'));
      b.type = 'button';
      var on = list.indexOf(m.id) >= 0;
      b.setAttribute('aria-pressed', String(on));
      var name = el('span', 'tier-model-name', m.name);
      if (standard.indexOf(m.id) >= 0) name.appendChild(modelsMark());
      b.appendChild(name);
      b.appendChild(el('span', 'tier-model-effort', m.effort_name));
      b.title = (on ? 'On the list: press to take it off. ' : 'Press to add it to the end of the list. ') + (m.why || '');
      b.disabled = can || cannot || (on && list.length === 1);
      b.addEventListener('click', function () {
        pickSave(on ? list.filter(function (x) { return x !== m.id; }) : list.concat([m.id]));
      });
      box.appendChild(b);
    });
    col.appendChild(box);
    cols.appendChild(col);
  });
}

/* The providers, each with whether it can be asked here. Google's and xAI's keys are typed
   here, kept sealed, and never shown again but for their last four characters. */
function providersDraw(d, locked) {
  var box = $('modelProviders');
  if (!box || !d.providers) return;
  d.providers.forEach(function (p) {
    var row = box.querySelector('[data-provider="' + p.id + '"]');
    if (!row) {
      row = el('div', 'prov-row');
      row.setAttribute('data-provider', p.id);
      row.appendChild(el('span', 'prov-name', p.name));
      row.appendChild(el('span', 'prov-state'));
      if (p.typed) {
        var form = /** @type {HTMLFormElement} */ (el('form', 'prov-form'));
        var input = /** @type {HTMLInputElement} */ (el('input', 'prov-key'));
        input.type = 'password';
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.placeholder = p.name + ' API key';
        input.setAttribute('aria-label', p.name + ' API key');
        var save = /** @type {HTMLButtonElement} */ (el('button', 'ctl small prov-save', 'Save'));
        save.type = 'submit';
        var drop = /** @type {HTMLButtonElement} */ (el('button', 'ctl small prov-remove', 'Remove'));
        drop.type = 'button';
        form.appendChild(input);
        form.appendChild(save);
        form.appendChild(drop);
        form.addEventListener('submit', function (e) {
          e.preventDefault();
          if (!input.value.trim()) return;
          keySave(p.id, input.value, function () { input.value = ''; });
        });
        drop.addEventListener('click', function () { keySave(p.id, '', null); });
        row.appendChild(form);
      }
      box.appendChild(row);
    }
    row.querySelector('.prov-state').textContent = !p.has ? 'No key'
      : p.source === 'settings' ? 'Key ending ' + p.last4 + (p.saved_by ? ', saved by ' + p.saved_by : '')
      : 'This server\'s key';
    row.classList.toggle('on', !!p.has);
    var f = row.querySelector('.prov-form');
    if (f) {
      Array.prototype.forEach.call(f.querySelectorAll('input, button'), function (n) {
        /** @type {HTMLInputElement} */ (n).disabled = locked || MODELS.saving;
      });
      /** @type {HTMLElement} */ (f.querySelector('.prov-remove')).hidden = p.source !== 'settings';
    }
  });
}

function keySave(provider, key, then) {
  if (MODELS.saving) return;
  MODELS.saving = true;
  modelsDraw();
  fetch('/api/settings/models/keys', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: provider, key: key }),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    MODELS.saving = false;
    if (answer.out && answer.out.tiers) MODELS.data = answer.out;
    modelsDraw();
    if (!answer.ok) settingsSay(answer.out.error || 'That was not saved.', 'bad');
    else if (then) then();
  }).catch(function () {
    MODELS.saving = false;
    modelsDraw();
    settingsSay('That could not be saved. Try again in a moment.', 'bad');
  });
}

/* The two sharing choices, each on its own: the totals, and the blind comparisons. */
function sharingDraw(d, locked) {
  var totals = $('shareTotals');
  totals.setAttribute('aria-checked', String(!!d.share_totals));
  /** @type {HTMLButtonElement} */ (totals).disabled = locked || MODELS.saving;
  var compare = $('shareCompare');
  compare.setAttribute('aria-checked', String(!!d.compare));
  /** @type {HTMLButtonElement} */ (compare).disabled = locked || MODELS.saving;
  var day = /** @type {HTMLSelectElement} */ ($('shareCompareDay'));
  var n = String(d.compare_per_day || 1);
  if (!day.querySelector('option[value="' + n + '"]')) {
    var extra = /** @type {HTMLOptionElement} */ (el('option', null, n + ' times a day'));
    extra.value = n;
    day.appendChild(extra);
  }
  if (document.activeElement !== day) day.value = n;
  day.disabled = locked || MODELS.saving || !d.compare;
  day.parentElement.hidden = !d.compare;
  $('sharingLocked').hidden = !locked;
}

$('shareTotals').addEventListener('click', function () {
  modelsSave({ which: 'share', on: $('shareTotals').getAttribute('aria-checked') !== 'true' });
});
$('shareCompare').addEventListener('click', function () {
  modelsSave({ which: 'compare', on: $('shareCompare').getAttribute('aria-checked') !== 'true' });
});
$('shareCompareDay').addEventListener('change', function () {
  modelsSave({ which: 'compare', per_day: Number(/** @type {HTMLSelectElement} */ ($('shareCompareDay')).value) });
});

/* The line at the top of each reply, on this device (app/turnline.js). */
$('traceSwitch').addEventListener('click', function () { traceSet(!traceOn()); });
traceShowAll();

$('modelsBar').addEventListener('input', function () {
  $('modelsBarVal').textContent = /** @type {HTMLInputElement} */ ($('modelsBar')).value + '%';
});
$('modelsBar').addEventListener('change', function () {
  modelsSave({ which: 'bar', bar: Number(/** @type {HTMLInputElement} */ ($('modelsBar')).value) / 100 });
});
$('modelsBarService').addEventListener('click', function () {
  modelsSave({ which: 'bar', bar: null });
});

$('tierCancel').addEventListener('click', function () {
  /** @type {HTMLDialogElement} */ ($('tierDialog')).close();
});

/* Behind each Auto's (i): what double calls cost this month, and behind the
   Models box's, exactly what is sent today. */
function modelsShareShow() {
  if (typeof fetch !== 'function') return;
  fetch('/api/settings/models/share', { credentials: 'same-origin' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (p) {
      if (!p) return;
      var last = p.last || {};
      var spend = p.double_spend || { calls: 0, usd: 0 };
      var cost = 'This month double calls added ' + spend.calls + ' call' +
        (spend.calls === 1 ? '' : 's') + ' and $' + (spend.usd || 0).toFixed(2) + '.';
      Array.prototype.forEach.call(document.querySelectorAll('.models-spend'), function (n) {
        n.textContent = cost;
      });
      $('shareMode').textContent = !p.on ? 'Sharing is off: nothing is sent.'
        : p.sending ? 'Sent to ' + p.url + ' once a day' +
          (last.mode === 'sent' ? ', last ' + whenWords(last.at) :
            last.mode === 'failed' ? '; the last try did not reach it' : '') + '.'
        : 'Not sent yet: this Rouh keeps each day\'s totals here as what would have been sent.';
      $('sharePreview').textContent = JSON.stringify(p.payload, null, 2);
    })
    .catch(function () { $('shareMode').textContent = ''; });
}

/* The (i) beside a heading: the help under it, shown and hidden. */
[['modelsInfoTiers', 'modelsMoreTiers'], ['modelsInfoUses', 'modelsMoreUses'],
  ['tierInfo', 'tierMore'], ['providersInfo', 'providersMore'],
  ['shareTotalsInfo', 'shareTotalsMore']].forEach(function (pair) {
  $(pair[0]).addEventListener('click', function () {
    var more = $(pair[1]);
    more.hidden = !more.hidden;
    $(pair[0]).setAttribute('aria-expanded', String(!more.hidden));
    if (!more.hidden && pair[1] !== 'tierMore' && pair[1] !== 'providersMore') modelsShareShow();
  });
});

/* After Sync or Reset to defaults: how many settings moved, with Undo for that one
   press, which puts back what it replaced. Nothing moved, nothing to undo. */
function modelsAfterCopy(what) {
  return function (out) {
    var n = out.changed || 0;
    if (!n) { notify(what + ': nothing changed. Everything not locked was already the same.'); return; }
    notify(what + ': ' + n + ' setting' + (n === 1 ? '' : 's') + ' changed.', {
      tone: 'success', for: 9000,
      action: { label: 'Undo', run: function () { modelsSave({ which: 'undo_sync' }); } } });
  };
}

MODELS_BOXES.forEach(function (box) {
  $('modelsAuto' + box.key).addEventListener('click', function () {
    modelsSave({ which: 'auto', box: box.id,
      on: $('modelsAuto' + box.key).getAttribute('aria-checked') !== 'true' });
  });
  $('modelsSync' + box.key).addEventListener('click', function () {
    modelsSave({ which: 'sync', box: box.id }, modelsAfterCopy('Synced with the Rouh model service'));
  });
  $('modelsReset' + box.key).addEventListener('click', function () {
    modelsSave({ which: 'reset', box: box.id }, modelsAfterCopy('Reset to defaults'));
  });
});

function modelsSave(sent, then) {
  var d = MODELS.data;
  if (!d || MODELS.saving) return;
  MODELS.saving = true;
  modelsDraw();
  fetch('/api/settings/models', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sent),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    MODELS.saving = false;
    if (answer.out && answer.out.tiers) MODELS.data = answer.out;
    modelsDraw();
    if (!answer.ok) settingsSay(answer.out.error || 'That was not saved.', 'bad');
    else {
      if (then) then(answer.out);
      if (!$('modelsMoreTiers').hidden || !$('modelsMoreUses').hidden || !$('shareTotalsMore').hidden) {
        modelsShareShow();
      }
    }
  }).catch(function () {
    MODELS.saving = false;
    modelsDraw();
    settingsSay('That could not be saved. Try again in a moment.', 'bad');
  });
}

/* ---------- Settings: Email signatures ----------
 *
 * The person's own two signatures, from GET /api/settings/signatures: one
 * for a new email and one for a reply or a forward (`rouh/signatures.py`).
 * Both are saved together by Save; an empty box is no signature. What comes
 * back from the save is what was kept, and the boxes are drawn from it. A
 * box typed in since is never written over by a read that lands late
 * (`edited`): that would save empty boxes over what was just typed.
 */

var SIG = { saving: false, edited: false };

function sigDraw(data) {
  $('sigNew').value = data.new || '';
  $('sigReply').value = data.reply || '';
}

function sigLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/signatures', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('signatures ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data || SIG.saving || SIG.edited) return;
      sigDraw(data);
      $('sigSaid').textContent = '';
    })
    .catch(function () {
      $('sigSaid').textContent = 'The signatures could not be read from the server. ' +
        'Try again in a moment.';
    });
}

['sigNew', 'sigReply'].forEach(function (id) {
  $(id).addEventListener('input', function () { SIG.edited = true; });
});

$('sigForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (SIG.saving) return;
  SIG.saving = true;
  $('sigSave').disabled = true;
  $('sigSaid').textContent = 'Saving...';
  fetch('/api/settings/signatures', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 'new': $('sigNew').value, reply: $('sigReply').value }),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    SIG.saving = false;
    $('sigSave').disabled = false;
    if (!answer.ok) {
      $('sigSaid').textContent = answer.out.error || 'That was not saved.';
      return;
    }
    SIG.edited = false;
    sigDraw(answer.out);
    var none = [];
    if (!answer.out.new) none.push('new emails');
    if (!answer.out.reply) none.push('replies and forwards');
    $('sigSaid').textContent = 'Saved.' + (none.length
      ? ' No signature on ' + none.join(' or ') + '.' : '');
  }).catch(function () {
    SIG.saving = false;
    $('sigSave').disabled = false;
    $('sigSaid').textContent = 'That could not be saved. Try again in a moment.';
  });
});

/* ---------- Settings: My contact card ----------
 *
 * The one iCloud card whose emails are the person's own, from GET
 * /api/settings/my-card (`rouh/my_card.py`, `rouh/web/mycard.py`). Picked
 * by searching the iCloud contacts and pressing This is me; its emails are
 * added, changed and removed here, on the real card in iCloud. Nothing is
 * guessed: with no card picked only the account's address is the person's,
 * and the card says so in red until one is.
 */

var ME = { data: null, picking: false, busy: false, editing: '', timer: 0, asked: '' };

function meEl(tag, cls, text) {
  var el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function meSaid(text, bad) {
  var p = $('meCardSaid');
  p.textContent = text || '';
  p.hidden = !text;
  p.classList.toggle('bad', !!bad);
}

function meLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/my-card', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('my card ' + r.status);
      return r.json();
    })
    .then(function (data) { if (data && !ME.busy) { ME.data = data; meDraw(); } })
    .catch(function () {
      $('meCardNone').textContent = 'Your contact card could not be read from the server. Try again in a moment.';
      $('meCardNone').hidden = false;
    });
}

function meDraw() {
  var d = ME.data;
  if (!d) return;
  var apple = d.apple || {};
  var ready = apple.on && apple.connected && !apple.needs_new_password;
  var chosen = d.chosen;
  var off = '';
  if (!apple.on) off = 'Apple Contacts are switched off on this server, so no card can be picked.';
  else if (!apple.connected) off = 'Connect Apple Contacts first, under Apple Contacts on the left, then pick your card here.';
  else if (apple.needs_new_password) off = 'iCloud stopped accepting the app-specific password. Enter a new one under Apple Contacts before changing your card.';
  else if (!apple.synced) off = 'Your iCloud contacts are still being fetched. Your card can be picked once they are here.';
  $('meCardOff').textContent = off;
  $('meCardOff').hidden = !off;

  // No card is a choice, said plainly; a card that was picked and has gone
  // from iCloud is not, and is said in red. Picking a card is never called
  // connecting it: connected is what a mailbox is (rouh/person_addresses.py).
  var none = '';
  var only = d.account ? 'only ' + d.account + ' counts as yours' : 'no address counts as yours';
  if (d.missing) none = 'The card you picked is no longer in your iCloud contacts. Until you pick your card again, ' + only + '.';
  else if (!chosen) none = 'No card picked. Your profile is yours alone, and for mail ' + only + '.';
  $('meCardNone').textContent = none;
  $('meCardNone').hidden = !none;
  $('meCardNone').classList.toggle('bad', !!d.missing);

  $('meCardChosenPart').hidden = !chosen;
  if (chosen) {
    $('meCardName').textContent = chosen.name || '(no name)';
    $('meCardOrg').textContent = chosen.organisation || '';
    $('meCardOrg').hidden = !chosen.organisation;
  }
  $('meCardAddForm').hidden = !(chosen && ready);
  // Searching for a card only once Pick (or Pick another card) is
  // pressed: picking is the person's choice, never a form waiting to be
  // filled in.
  var picking = ready && apple.synced && ME.picking;
  $('meCardPickPart').hidden = !picking;
  $('meCardPickActions').hidden = !picking;
  $('meCardPickAgain').hidden = !ready || picking;
  $('meCardConnectPart').hidden = !!chosen || picking || !(ready && apple.synced);
  meDrawAddresses(d, chosen, ready);
}

/* Every address of theirs as one list (personaddresses.js, the same rows
   their contact card draws): label, where it comes from, silo, and whether
   it is a mailbox connected to Rouh. An address on the picked card can be
   changed or taken off it here, on the real card in iCloud. */
function meDrawAddresses(d, chosen, ready) {
  var box = $('meCardAddresses');
  box.textContent = '';
  var data = d.addresses || { person: '', rows: (d.own || []).map(function (a) {
    return { address: a, label: '', source_said: a === d.account ? 'your Rouh account' : 'iCloud card' };
  }), silos: [] };
  if (!window.RouhAddresses) return;
  var onCard = {};
  ((chosen && chosen.emails) || []).forEach(function (one) {
    onCard[String(one.address || '').toLowerCase()] = one;
  });
  var list = window.RouhAddresses.list({
    data: data, title: 'Your email addresses', editable: !!data.person,
    extra: function (row, li) {
      var one = onCard[String(row.address || '').toLowerCase()];
      if (!one) return;
      if (one.never) li.appendChild(meEl('p', 'pa-acts cal-can bad', 'Rouh\'s own address: never counted as yours.'));
      if (!ready) return;
      var acts = meEl('div', 'pa-acts', null);
      if (ME.editing && ME.editing === one.address) {
        var form = meEl('form', 'me-card-row', null);
        form.setAttribute('autocomplete', 'off');
        var input = /** @type {HTMLInputElement} */ (meEl('input', '', null));
        input.type = 'text';
        input.value = one.address;
        input.spellcheck = false;
        input.setAttribute('autocapitalize', 'off');
        input.setAttribute('inputmode', 'email');
        input.setAttribute('aria-label', 'Change ' + one.address + ' to');
        var save = meEl('button', 'ctl small primary', 'Save');
        save.type = 'submit';
        var cancel = meEl('button', 'ctl small', 'Cancel');
        cancel.type = 'button';
        cancel.addEventListener('click', function () { ME.editing = ''; meDraw(); });
        form.appendChild(input);
        form.appendChild(save);
        form.appendChild(cancel);
        form.addEventListener('submit', function (e) {
          e.preventDefault();
          var now = input.value.trim();
          if (!now || now.toLowerCase() === one.address.toLowerCase()) { ME.editing = ''; meDraw(); return; }
          // Its label goes with it, so the card keeps saying what it said.
          meWrite({ add: [{ address: now, label: one.label || '' }], remove: [one.address] },
            'Changing ' + one.address + ' to ' + now + ' in iCloud...');
        });
        acts.appendChild(form);
        setTimeout(function () { input.focus(); input.select(); }, 0);
      } else {
        var change = meEl('button', 'ctl small', 'Change');
        change.type = 'button';
        change.setAttribute('aria-label', 'Change ' + one.address + ' on your card');
        change.addEventListener('click', function () { ME.editing = one.address; meDraw(); });
        var remove = meEl('button', 'ctl small', 'Remove from card');
        remove.type = 'button';
        remove.setAttribute('aria-label', 'Remove ' + one.address + ' from your card');
        remove.addEventListener('click', function () {
          meWrite({ remove: [one.address] }, 'Removing ' + one.address + ' from your card in iCloud...');
        });
        acts.appendChild(change);
        acts.appendChild(remove);
      }
      li.appendChild(acts);
    }
  });
  box.appendChild(list);
}

function mePost(url, body) {
  return fetch(url, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out || {} }; });
  });
}

function meButtons(on) {
  /** @type {NodeListOf<HTMLButtonElement>} */
  var buttons = document.querySelectorAll('#meCardChosenPart button, #meCardAddresses button, #meCardAddForm button');
  for (var i = 0; i < buttons.length; i++) buttons[i].disabled = !on;
}

function meWrite(change, doing) {
  if (ME.busy) return;
  ME.busy = true;
  meSaid(doing, false);
  meButtons(false);
  mePost('/api/settings/my-card/emails', change).then(function (answer) {
    ME.busy = false;
    meButtons(true);
    if (answer.out.apple) ME.data = answer.out;
    if (answer.ok) { ME.editing = ''; $('meCardAdd').value = ''; }
    meDraw();
    meSaid(answer.ok ? (answer.out.said || 'Saved to iCloud.')
      : (answer.out.error || 'Nothing was changed.'), !answer.ok);
  }).catch(function () {
    ME.busy = false;
    meButtons(true);
    meDraw();
    meSaid('That could not be saved. Nothing was changed. Try again in a moment.', true);
  });
}

$('meCardAddForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var address = $('meCardAdd').value.trim();
  if (!address) { meSaid('Type the address to add.', true); return; }
  meWrite({ add: [{ address: address, label: 'other' }] },
    'Adding ' + address + ' to your card in iCloud...');
});

function meSearch() {
  var q = $('meCardSearch').value.trim();
  var found = $('meCardFound');
  var said = $('meCardFoundSaid');
  ME.asked = q;
  if (!q) { found.textContent = ''; said.hidden = true; return; }
  fetch('/api/settings/my-card/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (out) {
      if (ME.asked !== q) return;
      found.textContent = '';
      var rows = (out && out.found) || [];
      said.textContent = out && out.error ? out.error
        : (rows.length ? '' : 'Nobody in your iCloud contacts matches "' + q + '".');
      said.hidden = !said.textContent;
      rows.forEach(function (one) {
        var li = meEl('li', 'me-card-email', null);
        var line = meEl('div', 'me-card-line', null);
        var words = meEl('div', 'me-card-words', null);
        words.appendChild(meEl('span', 'cal-name', one.name || '(no name)'));
        if (one.organisation) words.appendChild(meEl('span', 'cal-can', one.organisation));
        var emails = (one.emails || []).map(function (e) { return e.address; }).join(', ');
        words.appendChild(meEl('span', 'cal-id mono', emails || 'No emails on this card'));
        line.appendChild(words);
        var pick = meEl('button', 'ctl small primary', 'This is me');
        pick.type = 'button';
        pick.setAttribute('aria-label', 'This is me: ' + (one.name || one.id));
        pick.addEventListener('click', function () { mePick(one.id); });
        var acts = meEl('div', 'me-card-acts', null);
        acts.appendChild(pick);
        line.appendChild(acts);
        li.appendChild(line);
        found.appendChild(li);
      });
    })
    .catch(function () {
      said.textContent = 'The contacts could not be searched just now. Try again in a moment.';
      said.hidden = false;
    });
}

function mePick(id) {
  if (ME.busy) return;
  ME.busy = true;
  mePost('/api/settings/my-card', { contact_id: id }).then(function (answer) {
    ME.busy = false;
    if (answer.out.apple) ME.data = answer.out;
    if (answer.ok) {
      ME.picking = false;
      $('meCardSearch').value = '';
      $('meCardFound').textContent = '';
      $('meCardFoundSaid').hidden = true;
    }
    meDraw();
    meSaid(answer.ok ? answer.out.said : '', false);
    if (answer.ok) profLoad();
    if (!answer.ok) {
      $('meCardFoundSaid').textContent = answer.out.error || 'That card was not picked.';
      $('meCardFoundSaid').hidden = false;
    }
  }).catch(function () {
    ME.busy = false;
    $('meCardFoundSaid').textContent = 'That card could not be picked just now. Try again in a moment.';
    $('meCardFoundSaid').hidden = false;
  });
}

$('meCardSearchForm').addEventListener('submit', function (e) {
  e.preventDefault();
  clearTimeout(ME.timer);
  meSearch();
});
$('meCardSearch').addEventListener('input', function () {
  clearTimeout(ME.timer);
  ME.timer = setTimeout(meSearch, 250);
});
$('meCardPickAgain').addEventListener('click', function () {
  ME.picking = true;
  meSaid('', false);
  meDraw();
  $('meCardSearch').focus();
});
$('meCardPickCancel').addEventListener('click', function () {
  ME.picking = false;
  meDraw();
});
$('meCardForget').addEventListener('click', function () {
  if (ME.busy) return;
  ME.busy = true;
  mePost('/api/settings/my-card', { forget: true }).then(function (answer) {
    ME.busy = false;
    if (answer.out.apple) ME.data = answer.out;
    ME.picking = false;
    ME.editing = '';
    meDraw();
    meSaid('', false);
    profLoad();
  }).catch(function () { ME.busy = false; });
});
$('meCardConnect').addEventListener('click', function () {
  ME.picking = true;
  meSaid('', false);
  meDraw();
  $('meCardSearch').focus();
});

/* ---------- Settings: Profile ----------
 *
 * The person's own profile, opened by Edit behind their name
 * (fr_02048b1ef832), from GET /api/settings/profile (`rouh/profile.py`):
 * their name, a nickname, the email they sign in with, a few words about
 * themselves, and the password. While their name follows the contact card
 * connected above, the two name boxes show the card's and cannot be typed in.
 */

var PROF = { data: null, busy: false };

function profSaid(id, text, bad) {
  var p = $(id);
  p.textContent = text || '';
  p.hidden = !text;
  p.classList.toggle('bad', !!bad);
}

function profLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/profile', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('profile ' + r.status);
      return r.json();
    })
    .then(function (data) { if (data && !PROF.busy) { PROF.data = data; profDraw(true); } })
    .catch(function () { profSaid('profSaid', 'Your profile could not be read from the server. Try again in a moment.', true); });
}

/** What the profile calls the person at the foot of the navigation. @param {any} d */
function profOwnName(d) {
  var full = [d.first_name, d.last_name].filter(Boolean).join(' ');
  return d.nickname || full || d.username || '';
}

/** @param {boolean} fields whether the boxes are filled in again, or only what is read from them */
function profDraw(fields) {
  var d = PROF.data;
  if (!d) return;
  var following = !!(d.card && d.follow_card);
  if (fields) {
    /** @type {HTMLInputElement} */ ($('profFirst')).value = d.first_name || '';
    /** @type {HTMLInputElement} */ ($('profLast')).value = d.last_name || '';
    /** @type {HTMLInputElement} */ ($('profNick')).value = d.nickname || '';
    /** @type {HTMLInputElement} */ ($('profEmail')).value = d.email || '';
    /** @type {HTMLSelectElement} */ ($('profPronouns')).value = d.pronouns || '';
  }
  // Who you are and your company: your own contact's, under Contact card (`profile.py`).
  if (fields) {
    /** @type {HTMLInputElement} */ ($('meCardCompany')).value = d.card_company || '';
    /** @type {HTMLTextAreaElement} */ ($('meCardAbout')).value = d.card_about || '';
  }
  $('meCardAboutPart').hidden = !d.card_contact;
  $('meCardCompanyHelp').textContent = d.card_icloud
    ? 'What Rouh calls your company. It is your iCloud card\u2019s company, so a change reaches your phone too.'
    : 'What Rouh calls your company: a company, or whatever says who you are.';
  /** @type {HTMLInputElement} */ ($('profFirst')).readOnly = following;
  /** @type {HTMLInputElement} */ ($('profLast')).readOnly = following;
  $('profFromCard').textContent = following
    ? 'Your name comes from your contact card, ' + (d.card.name || 'below') + '. To type your own, turn off keeping it in step, under Contact card.'
    : '';
  $('profFromCard').hidden = !following;
  $('profUser').textContent = d.username || '';
  /** @type {HTMLInputElement} */ ($('pwUser')).value = d.username || '';
  /** @type {HTMLInputElement} */ ($('profFollow')).checked = !!d.follow_card;
  $('pwCurrentField').hidden = !d.has_password;
  $('pwSave').textContent = d.has_password ? 'Change password' : 'Set a password';
  ownName(profOwnName(d));
}

$('profForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (PROF.busy) return;
  var body = {
    nickname: /** @type {HTMLInputElement} */ ($('profNick')).value,
    email: /** @type {HTMLInputElement} */ ($('profEmail')).value,
    pronouns: /** @type {HTMLSelectElement} */ ($('profPronouns')).value
  };
  if (!(PROF.data && PROF.data.card && PROF.data.follow_card)) {
    body.first_name = /** @type {HTMLInputElement} */ ($('profFirst')).value;
    body.last_name = /** @type {HTMLInputElement} */ ($('profLast')).value;
  }
  profSave(body, 'profSave', 'profSaid', true);
});

// Who you are and your company, kept on your own contact (`profile.py`, `people.People.me`).
$('meCardAboutForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (PROF.busy) return;
  profSave({ card_company: /** @type {HTMLInputElement} */ ($('meCardCompany')).value,
             card_about: /** @type {HTMLTextAreaElement} */ ($('meCardAbout')).value },
           'meCardAboutSave', 'meCardAboutSaid', true);
});

$('profFollow').addEventListener('change', function () {
  profSave({ follow_card: /** @type {HTMLInputElement} */ ($('profFollow')).checked }, '', 'meCardSaid', false);
});

/** @param {Object<string, any>} body @param {string} button @param {string} said @param {boolean} refill */
function profSave(body, button, said, refill) {
  PROF.busy = true;
  if (button) /** @type {HTMLButtonElement} */ ($(button)).disabled = true;
  mePost('/api/settings/profile', body).then(function (answer) {
    PROF.busy = false;
    if (button) /** @type {HTMLButtonElement} */ ($(button)).disabled = false;
    if (answer.out.username) PROF.data = answer.out;
    // A refusal leaves what was typed in the boxes, to put right.
    profDraw(answer.ok && (refill || !button));
    profSaid(said, answer.ok ? answer.out.said : (answer.out.error || 'Nothing was changed.'), !answer.ok);
  }).catch(function () {
    PROF.busy = false;
    if (button) /** @type {HTMLButtonElement} */ ($(button)).disabled = false;
    profSaid(said, 'That could not be saved. Nothing was changed. Try again in a moment.', true);
  });
}

$('pwForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (PROF.busy) return;
  var boxes = ['pwCurrent', 'pwNew', 'pwAgain'].map(function (id) { return /** @type {HTMLInputElement} */ ($(id)); });
  PROF.busy = true;
  /** @type {HTMLButtonElement} */ ($('pwSave')).disabled = true;
  mePost('/api/settings/profile/password', { current: boxes[0].value, 'new': boxes[1].value, again: boxes[2].value })
    .then(function (answer) {
      PROF.busy = false;
      /** @type {HTMLButtonElement} */ ($('pwSave')).disabled = false;
      if (answer.ok) {
        boxes.forEach(function (b) { b.value = ''; });
        if (PROF.data) { PROF.data.has_password = true; profDraw(false); }
      }
      profSaid('pwSaid', answer.ok ? answer.out.said : (answer.out.error || 'The password was not changed.'), !answer.ok);
    }).catch(function () {
      PROF.busy = false;
      /** @type {HTMLButtonElement} */ ($('pwSave')).disabled = false;
      profSaid('pwSaid', 'The password could not be changed just now. Try again in a moment.', true);
    });
});

// A way from one group to another inside Settings: Email and calendar's
// Open your profile.
$('settingsView').addEventListener('click', function (e) {
  var a = /** @type {Element} */ (e.target).closest && /** @type {Element} */ (e.target).closest('a[data-section-link]');
  if (!a || /** @type {MouseEvent} */ (e).button || /** @type {MouseEvent} */ (e).metaKey
      || /** @type {MouseEvent} */ (e).ctrlKey || /** @type {MouseEvent} */ (e).shiftKey) return;
  settingsOpen(a.getAttribute('data-section-link') || '');
});

/* ---------- Settings: Location ----------
 *
 * The very first card (fr_ed03633d613c): where the person is, and the time
 * zone it gives, from GET /api/settings/location (`rouh/location.py`). The
 * point comes from the browser's location permission here; a phone app will
 * post the same thing to the same route. Nothing asks the browser for a
 * location until Share my location is pressed; once permission is granted,
 * every visit reads it again quietly (`locQuiet`), so a person who travels
 * is where they are, and on their clock, without doing anything.
 *
 * The zone is a name and the offset is the server's reading of it now, with
 * the next change of the clocks, so summer and winter time are always right.
 */

/** @type {{data: any, busy: boolean, trouble: string, perm: string, still?: boolean,
 *            typing?: boolean, stop?: ?function(): void, secondBusy?: boolean}} */
var LOC = { data: null, busy: false, trouble: '', perm: '' };

function locHeaders(json) {
  var h = { 'X-Time-Zone': browserZone() };
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

function locAsk(url, body) {
  return fetch(url, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    headers: locHeaders(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return null; }
    return r.json().then(function (out) {
      if (!r.ok) throw new Error(out.error || ('location ' + r.status));
      return out;
    });
  });
}

function locPermission() {
  if (!navigator.permissions || !navigator.permissions.query) return Promise.resolve('');
  return navigator.permissions.query({ name: 'geolocation' })
    .then(function (p) { return p.state || ''; }, function () { return ''; });
}

/* Where this device is, for a press (fr_89af9a2376cf). Petar, on a plane
 * with Wi-Fi, pressed Try again on an iPad and got Safari's "The operation
 * couldn't be completed. (kCLErrorDomain error 0.)": CoreLocation saying it
 * does not know where it is yet, which it says at once and then goes on
 * trying. One `getCurrentPosition` takes that first answer as the end of it.
 * So a press watches instead: it asks for the GPS (`enableHighAccuracy`) and
 * waits past every "not yet", ending at the first position or a refusal.
 * After `LOC_WAIT` with nothing, `late(err)` hears it, if given, and the watch
 * goes on quietly until `LOC_KEEP`, because a GPS starting cold in a moving
 * plane can take minutes; a position then still reaches `done`. With no
 * `late`, `LOC_WAIT` is the end. The browser's own `timeout` is not used: it
 * would end the watch at the first wait. `still(err)` hears each "not yet";
 * `done(pos, err)` hears the end, once. What it gives back stops the watch
 * without a word, for a place typed meanwhile or another press. */
var LOC_WAIT = 45000;
var LOC_KEEP = 10 * 60000;

/**
 * @param {function(?GeolocationPosition, ?{code: number, message: string}): void} done
 * @param {function({code: number, message: string}): void} [still]
 * @param {function({code: number, message: string}): void} [late]
 * @returns {function(): void}
 */
function locFind(done, still, late) {
  var geo = navigator.geolocation, id = /** @type {?number} */ (null);
  var last = /** @type {?{code: number, message: string}} */ (null), over = false, told = false;
  /** @type {any} */
  var soon = null;
  /** @type {any} */
  var backstop = null;
  /** @param {?GeolocationPosition} pos @param {?{code: number, message: string}} err @param {boolean} [quiet] */
  function end(pos, err, quiet) {
    if (over) return;
    over = true;
    clearTimeout(soon);
    clearTimeout(backstop);
    if (id !== null) geo.clearWatch(id);
    if (!quiet) done(pos, err);
  }
  var nothing = function () { return last || { code: 3, message: '' }; };
  soon = setTimeout(function () {
    if (!late) { end(null, nothing()); return; }
    told = true;
    late(nothing());
  }, LOC_WAIT);
  // Told already, the end of the listening is quiet: the card said so.
  backstop = setTimeout(function () { end(null, nothing(), told); }, late ? LOC_KEEP : LOC_WAIT + 60000);
  try {
    id = geo.watchPosition(function (pos) { end(pos, null); }, function (err) {
      last = { code: err ? err.code : 2, message: (err && err.message) || '' };
      if (last.code === 1) end(null, last);
      else if (still && !told) still(last);
    }, { enableHighAccuracy: true, maximumAge: 5 * 60000 });
  } catch (e) {
    setTimeout(function () { end(null, { code: 2, message: '' }); }, 0);
  }
  return function () { end(null, null, true); };
}

// Why the device gave no position, in words a person can act on, never the
// browser's own: Safari's are CoreLocation's error codes.
/** @param {?{code: number}} err */
function locWhy(err) {
  var code = err && err.code;
  if (code === 1) {
    return 'Your browser is not letting Rouh see your location. Allow location for this site ' +
      'in the browser’s settings (on an iPad or iPhone: Settings, Privacy & Security, ' +
      'Location Services, then Safari Websites) and press Try again, or type where you are below.';
  }
  // Petar, 15 October 2026, on that plane again: "Still not working". His
  // iPad's status bar showed Wi-Fi and no cellular signal: a Wi-Fi-only
  // iPad, which has no GPS at all, so there is no position to be had.
  return 'Your device has not found where it is. Without GPS it places itself by the ' +
    'Wi-Fi networks around it, which it cannot do on a plane, and an iPad without a SIM ' +
    'card has no GPS at all. Type where you are below.';
}

function locClockNow(zone) {
  try {
    return new Date().toLocaleTimeString('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit' });
  } catch (err) { return ''; }
}

function locDraw() {
  var data = LOC.data;
  var said = $('locSaid'), help = $('locHelp');
  var share = $('locShare'), forget = $('locForget');
  var kept = data && data.location;
  var z = data && data.zone;
  said.className = 'settings-note';
  help.className = 'settings-help';
  share.disabled = LOC.busy;
  forget.disabled = LOC.busy;
  if (data) {
    briefWeatherFor(kept ? kept.place || (Number(kept.lat).toFixed(2) + ', ' +
                                          Number(kept.lon).toFixed(2)) : '');
  }
  forget.hidden = !kept;

  if (z) {
    var season = z.change ? (z.summer ? ', summer time' : ', winter time') : '';
    $('locZone').textContent = z.zone + ' · ' + z.offset + season +
      (z.abbreviation && z.abbreviation.charAt(0) !== '+' && z.abbreviation.charAt(0) !== '-'
        ? ' (' + z.abbreviation + ')' : '');
    // In the town the person is in, when that is where the zone came from.
    var town = kept && kept.place && data.zone_from === 'location'
      ? kept.place.split(',')[0] : z.city;
    $('locNow').textContent = (locClockNow(z.zone) || z.time) + ' in ' + town;
    $('locChangeRow').hidden = !z.change;
    $('locChange').textContent = z.change
      ? z.change.day + ', ' + z.change.words : '';
    $('locChange').title = z.change ? 'Then ' + z.change.to : '';
  }
  $('locReadout').hidden = !z;
  $('locPlace').parentNode.hidden = !kept;
  if (kept) {
    $('locPlace').textContent = kept.place ||
      (kept.lat.toFixed(4) + ', ' + kept.lon.toFixed(4));
    $('locPlace').title = kept.lat + ', ' + kept.lon;
  }

  var zoneWords = '';
  if (data && data.zone_from === 'location') {
    zoneWords = 'Rouh keeps time by the zone of this place, so summer and winter time change on their own.';
  } else if (kept) {
    zoneWords = 'The time zone of this place could not be worked out just now, so your device’s is used.';
  } else if (data && data.zone_from === 'device') {
    zoneWords = 'Until then Rouh keeps time by the zone your device is on.';
  } else if (data) {
    zoneWords = data.default_place
      ? 'Until then Rouh keeps ' + data.default_place + ' time.'
      : 'Until then Rouh keeps the installation’s own time.';
  }

  if (LOC.busy) {
    said.hidden = false;
    said.textContent = LOC.still
      ? 'Your device does not know where it is yet. Still trying, with GPS if it has it...'
      : 'Finding where you are...';
  } else if (LOC.trouble) {
    said.hidden = false;
    said.className = 'settings-note bad';
    said.textContent = LOC.trouble;
  } else if (!data) {
    said.hidden = false;
  } else if (kept) {
    said.hidden = true;
  } else if (!navigator.geolocation) {
    said.hidden = false;
    said.textContent = 'This browser cannot share a location. Type where you are below.';
  } else {
    said.hidden = false;
    said.textContent = 'Rouh does not know where you are yet.';
  }

  var parts = [];
  if (kept && kept.source === 'typed') {
    parts.push('Typed in by you ' + since(kept.at * 1000) + '. Rouh keeps it until you change it.');
  } else if (kept) {
    parts.push('Shared from ' + (kept.source === 'phone' ? 'your phone' : 'this browser') + ' ' +
      since(kept.at * 1000) + (kept.accuracy ? ', to within about ' + locMetres(kept.accuracy) : '') + '.');
  } else if (data && navigator.geolocation && !LOC.trouble) {
    parts.push('Share your location and Rouh will know where you are and keep time by the zone there.');
  }
  if (zoneWords) parts.push(zoneWords);
  help.textContent = parts.join(' ');
  help.hidden = !parts.length;

  share.hidden = !navigator.geolocation || !data;
  share.textContent = LOC.trouble ? 'Try again'
    : kept && kept.source === 'typed' ? 'Use my device’s position'
    : kept ? 'Update now' : 'Share my location';
  $('locTyped').hidden = !data;
  $('locTypedGo').disabled = !!LOC.typing;
  locSecondDraw();
}

/* The second time zone (fr_1da7cddc045b): a clock to read times on beside
 * the one Rouh keeps, picked here and kept as the person's
 * (`location.second_zone`). The morning brief's calendar shows every time
 * on it too. Every zone the browser knows is offered, each with its offset
 * now. */

var LOC_COMMON = ['UTC', 'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'America/New_York',
                  'America/Chicago', 'America/Los_Angeles', 'Asia/Tokyo', 'Australia/Sydney'];

function locZoneOffset(zone) {
  try {
    var parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, timeZoneName: 'shortOffset' })
      .formatToParts(new Date());
    var named = parts.filter(function (p) { return p.type === 'timeZoneName'; })[0];
    return named ? named.value : '';
  } catch (err) { return ''; }
}

function locSecondFill() {
  var pick = $('locSecond');
  if (!pick || pick.options.length > 1) return;
  var zones = LOC_COMMON;
  try { if (Intl.supportedValuesOf) zones = Intl.supportedValuesOf('timeZone'); } catch (err) {}
  if (zones.indexOf('UTC') < 0) zones = zones.concat(['UTC']);
  zones.forEach(function (zone) {
    var off = locZoneOffset(zone);
    var opt = document.createElement('option');
    opt.value = zone;
    opt.textContent = zone.replace(/_/g, ' ') + (off ? ' (' + off + ')' : '');
    pick.appendChild(opt);
  });
}

function locSecondDraw() {
  var pick = $('locSecond');
  if (!pick || LOC.secondBusy) return;
  locSecondFill();
  var z = LOC.data && LOC.data.second_zone;
  var want = z ? z.zone : '';
  if (want && !Array.prototype.some.call(pick.options, function (o) { return o.value === want; })) {
    var opt = document.createElement('option');
    opt.value = want;
    opt.textContent = want.replace(/_/g, ' ');
    pick.appendChild(opt);
  }
  pick.value = want;
  pick.disabled = !LOC.data;
  var said = $('locSecondSaid');
  said.className = 'settings-help';
  said.textContent = z
    ? 'Now ' + (locClockNow(z.zone) || z.time) + ' in ' + z.city + ', ' + z.offset +
      '. The morning brief shows your calendar’s times there too.'
    : 'The morning brief shows your calendar’s times in this zone too.';
}

$('locSecond').addEventListener('change', /** @this {HTMLSelectElement} */ function () {
  var pick = this, said = $('locSecondSaid');
  LOC.secondBusy = true;
  pick.disabled = true;
  said.className = 'settings-help';
  said.textContent = 'Saving...';
  locAsk('/api/settings/location/second', { zone: pick.value }).then(function (out) {
    LOC.secondBusy = false;
    if (out) LOC.data = out;
    locSecondDraw();
    // The brief reads it as it is drawn: an open one shows it at once.
    if (window.RouhBrief && window.RouhBrief.zonesChanged) window.RouhBrief.zonesChanged();
  }).catch(function (err) {
    LOC.secondBusy = false;
    locSecondDraw();
    said.className = 'settings-help bad';
    said.textContent = 'That could not be saved: ' + (err.message || 'the server did not answer') + '.';
  });
});

function locMetres(m) {
  return m >= 1000 ? (Math.round(m / 100) / 10) + ' km' : Math.round(m) + ' m';
}

function locLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return Promise.all([locAsk('/api/settings/location'), locPermission()])
    .then(function (got) {
      if (!got[0]) return;
      LOC.data = got[0];
      LOC.perm = got[1];
      locDraw();
      // Already allowed: read it again, quietly, so it is where they are now.
      if (LOC.perm === 'granted' && !LOC.busy) locRead(false);
    })
    .catch(function () {
      $('locSaid').hidden = false;
      $('locSaid').className = 'settings-note bad';
      $('locSaid').textContent = 'Your location could not be read from the server. Try again in a moment.';
    });
}

// Ask the browser where it is and keep it. `loud` is a press of the button,
// which watches for a while (`locFind`) and says on the card why it found
// nothing; a quiet read asks once, and if it fails says nothing and leaves
// what was kept.
function locRead(loud) {
  if (!navigator.geolocation || LOC.busy) return;
  /** @param {GeolocationPosition} pos */
  function keep(pos) {
    locAsk('/api/settings/location', {
      lat: pos.coords.latitude, lon: pos.coords.longitude,
      accuracy: pos.coords.accuracy, source: 'browser', asked: !!loud,
    }).then(function (out) {
      LOC.busy = false;
      LOC.trouble = '';
      if (out) LOC.data = out;
      locDraw();
    }).catch(function (err) {
      LOC.busy = false;
      if (loud) LOC.trouble = 'Your location could not be kept: ' + (err.message || 'the server did not answer') + '.';
      locDraw();
    });
  }
  if (!loud) {
    navigator.geolocation.getCurrentPosition(keep, function () {},
      { enableHighAccuracy: false, timeout: 20000, maximumAge: 5 * 60000 });
    return;
  }
  if (LOC.stop) { LOC.stop(); LOC.stop = null; }
  LOC.busy = true;
  LOC.still = false;
  LOC.trouble = '';
  locDraw();
  LOC.stop = locFind(function (pos, err) {
    LOC.stop = null;
    LOC.still = false;
    if (pos) { LOC.busy = true; keep(pos); return; }
    LOC.busy = false;
    LOC.trouble = locWhy(err);
    locDraw();
  }, function () {
    if (!LOC.still) { LOC.still = true; locDraw(); }
  }, function (err) {
    // Said now, and still listened for: a position that comes later is kept.
    LOC.busy = false;
    LOC.still = false;
    LOC.trouble = locWhy(err) +
      ' Rouh goes on listening for a few minutes and keeps a position if one comes.';
    locDraw();
  });
}

$('locShare').addEventListener('click', function () { locRead(true); });

// A place typed by hand, for when the device cannot say (fr_89af9a2376cf).
// It wins over a watch still going: the person has said where they are.
$('locTyped').addEventListener('submit', function (e) {
  e.preventDefault();
  var box = /** @type {HTMLInputElement} */ ($('locTypedIn'));
  var said = $('locTypedSaid');
  var text = box.value.trim();
  if (!text) { box.focus(); return; }
  if (LOC.typing) return;
  if (LOC.stop) { LOC.stop(); LOC.stop = null; LOC.busy = false; LOC.still = false; }
  LOC.typing = true;
  said.hidden = false;
  said.className = 'settings-help';
  said.textContent = 'Looking for ' + text + '...';
  locDraw();
  locAsk('/api/settings/location/place', { place: text }).then(function (out) {
    LOC.typing = false;
    LOC.trouble = '';
    if (out) LOC.data = out;
    box.value = '';
    said.hidden = true;
    locDraw();
  }).catch(function (err) {
    LOC.typing = false;
    said.className = 'settings-help bad';
    said.textContent = (err && err.message) || 'That place could not be looked up. Try again in a moment.';
    locDraw();
  });
});

$('locForget').addEventListener('click', function () {
  if (LOC.busy) return;
  if (LOC.stop) { LOC.stop(); LOC.stop = null; }
  LOC.busy = true;
  LOC.trouble = '';
  locDraw();
  $('locSaid').textContent = 'Forgetting...';
  locAsk('/api/settings/location/forget', {}).then(function (out) {
    LOC.busy = false;
    if (out) LOC.data = out;
    locDraw();
  }).catch(function () {
    LOC.busy = false;
    LOC.trouble = 'Your location could not be forgotten just now. Try again in a moment.';
    locDraw();
  });
});

// Every visit, when the browser has already said yes: where the person is
// now, without opening Settings. Never asks: a browser that has not said
// yes is left alone until the button is pressed.
setTimeout(function () {
  if (!navigator.geolocation || typeof fetch !== 'function') return;
  locPermission().then(function (state) {
    if (state !== 'granted') return;
    navigator.geolocation.getCurrentPosition(function (pos) {
      locAsk('/api/settings/location', {
        lat: pos.coords.latitude, lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy, source: 'browser',
      }).then(function (out) {
        if (out) { LOC.data = out; if (settingsViewing() && !LOC.busy) locDraw(); }
      }).catch(function () {});
    }, function () {}, { enableHighAccuracy: false, timeout: 20000, maximumAge: 5 * 60000 });
  });
}, 1500);

/* ---------- Settings: Read-only mailboxes ----------
 *
 * The person's own mailboxes, from GET /api/settings/mailboxes
 * (`rouh/mailboxes.py`), each connected read-only for the brief's Waiting on
 * others (task 71). Connect a mailbox is a full page visit to Google's
 * account chooser, like Connect Google, and comes back to
 * `?settings=mailboxes`. Disconnect forgets the mailbox's tokens here and
 * its snoozes and dismissals with it. Allow forwarding is the same visit for
 * one mailbox, asking Google for sending as well (`?forward=<id>`), so Rouh
 * can forward an email or a conversation from it when the person asks
 * (4 October 2026); everything else in it stays read-only.
 */

var MBOX = { data: null, busy: false };

function mboxDraw() {
  var d = MBOX.data;
  var list = $('mboxList');
  list.textContent = '';
  if (!d) return;
  var rows = d.mailboxes || [];
  list.hidden = !rows.length;
  $('mboxNone').hidden = !!rows.length;
  $('mboxNotSetUp').hidden = !!d.can_connect;
  $('mboxConnect').disabled = !d.can_connect || MBOX.busy || rows.length >= d.most;
  $('mboxConnect').textContent = rows.length ? 'Connect another mailbox' : 'Connect a mailbox';
  rows.forEach(function (m) {
    var li = document.createElement('li');
    li.className = 'mbox-row';
    var main = document.createElement('div');
    main.className = 'mbox-main';
    var email = document.createElement('span');
    email.className = 'mbox-email';
    email.textContent = m.email || 'A mailbox';
    var sub = document.createElement('span');
    sub.className = 'mbox-sub';
    sub.textContent = (m.read_only ? 'Read-only' : 'Access wider than read-only') +
      (m.can_forward ? ', and forwards when you ask' : '') +
      ' · connected ' + whenWords(m.connected_at);
    main.appendChild(email);
    main.appendChild(sub);
    li.appendChild(main);
    if (!m.can_forward && !m.needs_reconnect) {
      var fwd = document.createElement('button');
      fwd.type = 'button';
      fwd.className = 'ctl small';
      fwd.textContent = 'Allow forwarding';
      fwd.title = 'Let Rouh forward an email or a whole conversation from this mailbox ' +
        'when you ask. Google asks you to let Rouh send email as it; nothing else changes.';
      fwd.setAttribute('aria-label', 'Allow forwarding from ' + (m.email || 'this mailbox'));
      fwd.disabled = MBOX.busy;
      fwd.addEventListener('click', function () {
        // A full page visit: Google's own consent screen, for this mailbox.
        location.href = '/auth/mailbox/start?forward=' + encodeURIComponent(m.id);
      });
      li.appendChild(fwd);
    }
    var off = document.createElement('button');
    off.type = 'button';
    off.className = 'ctl small';
    off.textContent = 'Disconnect';
    off.setAttribute('aria-label', 'Disconnect ' + (m.email || 'this mailbox'));
    off.disabled = MBOX.busy;
    off.addEventListener('click', function () { mboxDisconnect(m); });
    li.appendChild(off);
    if (m.needs_reconnect) {
      var bad = document.createElement('p');
      bad.className = 'settings-note bad';
      bad.textContent = 'Google no longer accepts this mailbox. Press Connect another ' +
        'mailbox and choose it again.' + (m.trouble ? ' Google said: ' + m.trouble : '');
      li.appendChild(bad);
    }
    list.appendChild(li);
  });
}

function mboxLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/mailboxes', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('mailboxes ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      MBOX.data = data;
      mboxDraw();
    })
    .catch(function () {
      $('mboxSaid').textContent = 'The mailboxes could not be read from the server. ' +
        'Try again in a moment.';
    });
}

function mboxDisconnect(m) {
  if (MBOX.busy) return;
  MBOX.busy = true;
  mboxDraw();
  $('mboxSaid').textContent = 'Disconnecting ' + m.email + '...';
  fetch('/api/settings/mailboxes/disconnect', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: m.id })
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (out) {
      MBOX.busy = false;
      $('mboxSaid').className = 'settings-help' + (r.ok ? '' : ' bad');
      if (!r.ok) {
        $('mboxSaid').textContent = out.error || 'That mailbox could not be disconnected.';
        mboxDraw();
        return;
      }
      $('mboxSaid').textContent = m.email + ' is disconnected and its tokens are gone' +
        (out.revoked ? ', and Google was asked to withdraw Rouh\'s access to it.'
          : out.shared ? '. Google\'s grant was left in place, because Rouh\'s own Google ' +
            'connection uses the same account.' : '.');
      if (window.RouhBrief && window.RouhBrief.mailboxesChanged) {
        window.RouhBrief.mailboxesChanged();
      }
      return mboxLoad();
    });
  }).catch(function () {
    MBOX.busy = false;
    mboxDraw();
    $('mboxSaid').textContent = 'That could not be done. Try again in a moment.';
  });
}

$('mboxConnect').addEventListener('click', function () {
  // A full page visit: Google's own account chooser and consent screen.
  location.href = '/auth/mailbox/start';
});

/* ---------- Settings: Morning brief ----------
 *
 * The person's own brief settings, from GET /api/settings/brief
 * (`rouh/morning_brief.py`): whether it is made every morning, at what time
 * on their own clock, and the YouTube channels the AI news is read from.
 * Each new channel is looked up when it is saved, and what comes back is
 * each channel's handle, so the box says exactly what was found. Where the
 * weather is for is only said here: it is the person's location, from the
 * Location card, and is changed there (fr_5d364b8f6ed5). The phone is named only for the person whose
 * Telegram the bot reaches, because nobody else's brief goes there.
 */

var BRIEFSET = { saving: false, edited: false };

function briefSettingsDraw(data) {
  $('briefOn').checked = !!data.on;
  $('briefTime').value = data.time || '07:00';
  briefWeatherFor(data.place);
  $('briefChannels').value = data.channels || '';
  $('briefOnWords').textContent = data.telegram && data.phone_is_mine
    ? 'Make it every morning and send the link to your Telegram'
    : 'Make it every morning';
}

// Said again whenever Location changes (`locDraw`), so it is never the
// place from before the person pressed Share or Forget.
function briefWeatherFor(place) {
  $('briefWeatherFor').textContent = place
    ? 'The weather is for where you are: ' + place + ', from Location.'
    : 'There is no weather until you share your location, under Location.';
}

function briefSettingsLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/brief', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('brief ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data || BRIEFSET.saving || BRIEFSET.edited) return;
      briefSettingsDraw(data);
      $('briefSaid').textContent = '';
    })
    .catch(function () {
      $('briefSaid').textContent = 'The morning brief settings could not be read from the ' +
        'server. Try again in a moment.';
    });
}

['briefOn', 'briefTime', 'briefChannels'].forEach(function (id) {
  $(id).addEventListener('input', function () { BRIEFSET.edited = true; });
});

$('briefForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (BRIEFSET.saving) return;
  BRIEFSET.saving = true;
  $('briefSave').disabled = true;
  $('briefSaid').textContent = 'Saving...';
  fetch('/api/settings/brief', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on: $('briefOn').checked, time: $('briefTime').value,
                           channels: $('briefChannels').value })
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    BRIEFSET.saving = false;
    $('briefSave').disabled = false;
    if (!answer.ok) {
      $('briefSaid').textContent = answer.out.error || 'That was not saved.';
      return;
    }
    BRIEFSET.edited = false;
    briefSettingsDraw(answer.out);
    var names = answer.out.channel_names || [];
    var from = names.length
      ? ' The AI news is from ' + (names.length === 1 ? names[0]
        : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]) + '.'
      : ' There are no channels for the AI news.';
    $('briefSaid').textContent = (answer.out.on
      ? 'Saved. Made every morning at ' + answer.out.time + '.'
      : 'Saved. It is not made by itself now; press Update on the Morning brief to make ' +
        'today\'s.') + from;
    if (window.RouhBrief) window.RouhBrief.settingsChanged();
  }).catch(function () {
    BRIEFSET.saving = false;
    $('briefSave').disabled = false;
    $('briefSaid').textContent = 'That could not be saved. Try again in a moment.';
  });
});

/* ---------- Settings: Trusted contacts ----------
 *
 * Who Rouh may deal with by email, by exact address, and for what, from
 * GET /api/settings/trusted (`rouh/web/trusted.py`). A group of Settings of
 * its own since 2 October 2026 (fr_ce3a4480d9b4): it opens on a list of
 * people, a row each with only who they are, and nothing to change there;
 * a row opens that one person at /anatomy/behaviour/trusted-contacts/<id>, the only
 * place they are seen whole and changed. Saving goes back to the list with
 * the row just saved marked, so the change is seen where it landed.
 *
 * Every press answers with the whole group again, so what is drawn is
 * always what the server holds now.
 */
var TC = { data: null, open: '', marked: '', found: null, asked: '', addAsked: '', busy: false,
  /** @type {{address: string, name: string} | null} */ addWant: null,
  /** @type {Object<string, any>} */ levels: {},
  /** @type {Object<string, any>} */ nodes: {},
  /** @type {Object<string, string>} */ parent: {},
  /** @type {Object<string, HTMLElement>} */ rows: {} };

/* Where Trusted contacts is, from the gene manifests (`anatomySection`): Behaviour's since 4
   November 2026. */
function tcRoute() {
  var sec = anatomySection('trusted-contacts');
  return sec ? sec.section.route : '/anatomy';
}

function tcLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/trusted', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('trusted ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      TC.data = data;
      $('tcTrouble').hidden = true;
      tcDraw();
      // The tab is named after the person opened, known only now.
      if (TC.open) addrTouch();
      tcAddAsked();
    })
    .catch(function () {
      $('tcTrouble').textContent = 'Trusted contacts could not be read from the server. Try again in a moment.';
      $('tcTrouble').hidden = false;
    });
}

/* One press, posted; the answer is the whole group again. */
function tcPost(body) {
  return fetch('/api/settings/trusted', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
      function () { return { ok: false, out: {} }; });
  }).then(function (a) {
    if (a.ok) TC.data = a.out;
    return a;
  });
}

function tcPerson(id) {
  var rows = (TC.data && TC.data.rows) || [];
  for (var i = 0; i < rows.length; i++) if (String(rows[i].id) === String(id)) return rows[i];
  return null;
}

function tcLevelName(key) {
  var levels = (TC.data && TC.data.levels) || [];
  for (var i = 0; i < levels.length; i++) if (levels[i].key === key) return levels[i].name;
  return key;
}

/* Open one person, or the list for ''. The address follows. */
function tcShow(id) {
  TC.open = id ? String(id) : '';
  if (TC.open) TC.marked = '';
  // The Grants panel is read afresh each time it is opened.
  if (TC.open === TCG_KEY) TCG.data = null;
  TC.tgCode = null;
  tcDraw();
  // The address names the section now, and the page is brought to it.
  SETTINGS.section = 'trusted-contacts';
  settingsPin('trusted-contacts');
  addrTouch();
}

function tcDraw() {
  var d = TC.data;
  var grantsOpen = TC.open === TCG_KEY;
  var person = TC.open && !grantsOpen && d ? tcPerson(TC.open) : null;
  if (TC.open && !grantsOpen && d && !person) {
    // An address for somebody since removed, or never here.
    TC.open = '';
    settingsSay('That contact is not in your trusted contacts.', 'bad');
    addrTouch();
  }
  var opened = !!TC.open;
  $('tcListCard').hidden = opened;
  $('tcQueues').hidden = opened;
  $('tcPerson').hidden = !opened || grantsOpen;
  $('tcGrants').hidden = !grantsOpen;
  if (grantsOpen) { if (TCG.data) tcgDraw(); else tcgLoad(TCG.open); }
  if (!d) return;
  if (person) tcDrawPerson(person);
  tcDrawList();
  tcDrawQueues();
  tcInboxPicks($('tcAdd'));
}

/* The "Your inbox - how far" pick on the add forms: every standing reach but
   A sender or label, which needs its senders named on the person's page. */
function tcInboxPicks(root) {
  var d = TC.data;
  if (!d || !root) return;
  root.querySelectorAll('select.tc-inbox-pick').forEach(function (select) {
    var was = select.value || 'none';
    select.textContent = '';
    (d.inbox_scopes || []).forEach(function (c) {
      if (c.key === 'senders') return;
      var o = el('option', '', c.name);
      o.value = c.key;
      if (c.key === was) o.selected = true;
      select.appendChild(o);
    });
  });
}

function tcRadio(name, value, checked, title, said, note) {
  var label = el('label', 'tc-check', null);
  var box = el('input', '', null);
  box.type = 'radio';
  box.name = name;
  box.value = value;
  box.checked = !!checked;
  label.appendChild(box);
  var words = el('span', '', null);
  words.appendChild(title);
  if (said) words.appendChild(el('span', 'tc-said', said));
  if (note) words.appendChild(el('span', 'tc-note', note));
  label.appendChild(words);
  return label;
}

function tcPicked(box, name) {
  var on = box.querySelector('input[name=' + name + ']:checked');
  return on ? on.value : '';
}

/* The senders box shows only while A sender or label is picked. */
function tcSyncInbox() {
  $('tcInboxFromField').hidden = tcPicked($('tcInbox'), 'inbox') !== 'senders';
}

function tcDrawList() {
  var d = TC.data;
  var rows = d.rows || [];
  var n = d.trusted_count || 0;
  $('tcCount').textContent = n === 1 ? '1 trusted now.' : n + ' trusted now.';
  $('tcNobody').hidden = rows.length > 0;
  var list = $('tcList');
  list.textContent = '';
  rows.forEach(function (p) {
    var li = el('li', '', null);
    var a = el('a', 'tc-row' + (String(p.id) === TC.marked ? ' marked' : ''), null);
    a.href = tcRoute() + '/' + p.id;
    a.dataset.id = String(p.id);
    var main = el('span', 'tc-row-main', null);
    main.appendChild(el('span', 'tc-row-name', p.name || '(no name)'));
    var addrs = p.addresses || [];
    var line = addrs.length ? addrs[0] : 'No address ticked';
    if (addrs.length > 1) line += '  +' + (addrs.length - 1) + ' more';
    main.appendChild(el('span', 'tc-row-addr' + (addrs.length ? ' mono' : ''), line));
    a.appendChild(main);
    var side = el('span', 'tc-row-side', null);
    side.appendChild(el('span', 'tc-pill' + (p.trusted ? ' good' : ''), p.trusted ? 'Trusted' : 'Not trusted'));
    var levels = p.levels || [];
    if (p.trusted && levels.length) side.appendChild(el('span', 'tc-row-level', tcLevelName(levels[levels.length - 1])));
    a.appendChild(side);
    var chev = el('span', 'tc-chev', null);
    chev.setAttribute('aria-hidden', 'true');
    a.appendChild(chev);
    li.appendChild(a);
    list.appendChild(li);
  });
}

function tcDrawTiming() {
  var t = TC.data.timing || {};
  // Never over what is being typed: only when the box does not have the cursor.
  if (document.activeElement === $('tcRemindHours')) return;
  $('tcRemindHours').value = t.remind_hours != null ? String(t.remind_hours) : '';
}

function tcDrawQueues() {
  tcDrawTiming();
  var groups = TC.data.groups || [];
  var list = $('tcQueueList');
  list.textContent = '';
  groups.forEach(function (g) {
    var li = el('li', 'me-card-line', null);
    var words = el('span', 'me-card-words', null);
    words.appendChild(el('span', 'tc-q-name', g.name));
    words.appendChild(el('span', 'tc-q-count', g.members === 1 ? '1 contact' : g.members + ' contacts'));
    li.appendChild(words);
    var gone = el('button', 'ctl small', 'Remove');
    gone.type = 'button';
    gone.setAttribute('aria-label', 'Remove the queue ' + g.name);
    gone.addEventListener('click', function () {
      tcPost({ act: 'remove_group', group: g.id }).then(tcAnswered);
    });
    li.appendChild(gone);
    list.appendChild(li);
  });
  if (!groups.length) list.appendChild(el('li', 'me-card-none', 'No queues yet.'));
}

function tcCheck(name, value, checked, title, said) {
  var label = el('label', 'tc-check', null);
  var box = el('input', '', null);
  box.type = 'checkbox';
  box.name = name;
  box.value = value;
  box.checked = !!checked;
  label.appendChild(box);
  var words = el('span', '', null);
  words.appendChild(title);
  if (said) words.appendChild(el('span', 'tc-said', said));
  label.appendChild(words);
  return label;
}

function tcDrawPerson(p) {
  var d = TC.data;
  $('tcPName').textContent = p.name || '(no name)';
  $('tcPPill').className = 'tc-pill' + (p.trusted ? ' good' : '');
  $('tcPPill').textContent = p.trusted ? 'Trusted' : 'Not trusted';
  $('tcPOrg').textContent = p.organisation || '';
  $('tcPOrg').hidden = !p.organisation;
  $('tcName').value = p.name || '';
  $('tcMore').value = '';
  $('tcNote').value = p.note || '';
  $('tcSaid').hidden = true;

  var addrs = $('tcAddrs');
  addrs.textContent = '';
  (p.addresses || []).forEach(function (a) {
    addrs.appendChild(tcCheck('address', a, true, el('span', 'mono', a)));
  });
  (p.others || []).forEach(function (a) {
    var words = el('span', 'mono', a);
    words.appendChild(el('span', 'tc-dim', ' on their card, not trusted'));
    addrs.appendChild(tcCheck('address', a, false, words));
  });
  if (!(p.addresses || []).length && !(p.others || []).length) {
    addrs.appendChild(el('span', 'tc-dim', 'No address yet. Add one below.'));
  }

  var levels = $('tcLevels');
  levels.textContent = '';
  (d.levels || []).forEach(function (c) {
    levels.appendChild(tcCheck('level', c.key, (p.levels || []).indexOf(c.key) >= 0,
      document.createTextNode(c.name), c.said));
  });

  tcDrawTree(p);
  tcSyncLevels(null);
  tcDrawMoreGrants(p);

  var name0 = p.name || 'them';
  $('tcInboxSaid').textContent = 'How far Rouh may read your own inbox for ' + name0 + ', when what they ask needs it. ' +
    'Only from the addresses ticked above. Every read is written down, and the latest are below.';
  var inbox = $('tcInbox');
  inbox.textContent = '';
  (d.inbox_scopes || []).forEach(function (c) {
    inbox.appendChild(tcRadio('inbox', c.key, (p.inbox_scope || 'none') === c.key,
      document.createTextNode(c.name), c.said, c.key === 'write' ? d.inbox_note : ''));
  });
  $('tcInboxFrom').value = (p.inbox_from || []).join(', ');
  tcSyncInbox();
  var reads = $('tcReads');
  reads.textContent = '';
  (p.inbox_reads || []).forEach(function (r) {
    var li = el('li', '', null);
    li.appendChild(el('span', 'tc-when', r.when));
    var what = el('span', 'tc-what', null);
    what.appendChild(document.createTextNode(r.what + (r.inbox ? ', in ' + r.inbox : '') +
      (r.once ? ' (allowed once)' : '') + ' '));
    if (r.case) {
      var a = el('a', '', 'Its email');
      a.href = r.case;
      what.appendChild(a);
    }
    li.appendChild(what);
    reads.appendChild(li);
  });
  if (!(p.inbox_reads || []).length) reads.appendChild(el('li', '', null)).appendChild(
    el('span', 'tc-none', 'Nothing read for them yet.'));
  $('tcZone').value = p.zone || '';

  // The silos they see (rouh/silos.py): the ones shown to others until you tick theirs.
  var sees = $('tcSees');
  sees.textContent = '';
  var seesNow = p.sees_now || [];
  (d.silos || []).forEach(function (c) {
    sees.appendChild(tcCheck('sees', c.key, seesNow.indexOf(c.key) >= 0, siloChip(c), null));
  });
  var others = (d.silos || []).filter(function (c) { return (d.silos_others || []).indexOf(c.key) >= 0; })
    .map(function (c) { return c.name; });
  sees.appendChild(el('p', 'tc-said', (p.sees == null ? 'Until you change it, what you show others: ' :
    'Others see, until you set theirs: ') + (others.join(', ') || 'nothing') +
    '. Ticking every silo shows them everything, things in no silo too.'));

  var beyond = $('tcBeyond');
  beyond.textContent = '';
  (d.beyonds || []).forEach(function (c) {
    beyond.appendChild(tcRadio('beyond', c.key, (p.beyond || 'ask') === c.key,
      document.createTextNode(c.name), c.said));
  });

  var select = $('tcGroup');
  select.textContent = '';
  var none = el('option', '', 'No queue');
  none.value = '';
  select.appendChild(none);
  (d.groups || []).forEach(function (g) {
    var o = el('option', '', g.name);
    o.value = String(g.id);
    if (g.id === p.group_id) o.selected = true;
    select.appendChild(o);
  });

  var name = p.name || 'them';
  $('tcToggle').textContent = p.trusted ? 'Stop trusting ' + name : 'Trust ' + name + ' again';
  $('tcSave').disabled = false;
  tcDrawTelegram(p);
  tcLatelyDraw(p);
}

/* The one tree on a contact's page (`task_access.page_tree`; Petar, 21 October 2026: "I
   expected one interface"): every task, step, quest and goal, each with one level - None,
   Read, Edit or Decide - in the control the Share panel has too (`levelPick`), reading and
   writing the one record (`rouh/task_access.py`). A level that comes from above shows dimmed,
   with what it comes from; a row's own level overrides it, and Clear takes that away again.
   Columns and projects are ticked to give everything in them to read, now and later. Every
   press is saved at once and changes only the rows it moves: nothing is drawn again, nothing
   folds and nothing jumps (B1). A task's rows under it are made the first time it opens. */
function tcDrawTree(p) {
  var d = TC.data || {};
  var tree = $('tcTree');
  tree.textContent = '';
  TC.levels = p.task_levels || {};
  TC.nodes = {};
  TC.parent = {};
  TC.rows = {};
  (d.tree || []).forEach(function (n) { tcIndex(n, ''); });
  (d.tree || []).forEach(function (n) { tree.appendChild(tcTreeRow(n)); });
  if (!(d.tree || []).length) tree.appendChild(el('li', 'tc-dim', 'There are no tasks on this machine.'));
  // What is given on its own shows: every row above it is opened.
  Object.keys(TC.levels).forEach(function (id) {
    var lv = TC.levels[id];
    if (lv.own || lv.from === 'started') tcReveal(TC.parent[id]);
  });
  (p.grants || []).forEach(function (id) { if (TC.nodes[id]) tcReveal(TC.parent[id]); });
  $('tcFind').value = '';
  var first = (p.name || 'them').split(' ')[0];
  $('tcTreeSaid').textContent = 'Read lets ' + first + ' open it. Edit lets them change it too, and talk to Rouh in it. ' +
    'Decide lets them decide there as you would, by email: Rouh sends them its decisions and does not ask you. ' +
    'Each includes the ones before it. A quest reaches its goals, and a task its steps; a row set on its own overrides what it gets from above. ' +
    'A ticked column or project gives everything in it to read, now and later. Never theirs, even where they decide:';
  var never = $('tcNever');
  never.textContent = '';
  (d.never || []).forEach(function (n) { never.appendChild(el('li', '', n.charAt(0).toUpperCase() + n.slice(1) + '.')); });
  $('tcTreeOff').textContent = first + ' is switched off, so nothing here counts until you trust them again.';
  $('tcTreeOff').hidden = !!p.trusted;
  tcTreeSync();
}

function tcIndex(n, parent) {
  TC.nodes[n.id] = n;
  TC.parent[n.id] = parent;
  (n.kids || []).forEach(function (k) { tcIndex(k, n.id); });
}

/* One row: a fold when it has rows under it, the tick, its number, kind and name, the notes
   under them, and for a task, step, quest or goal the level. */
function tcTreeRow(n) {
  var item = n.kind !== 'column' && n.kind !== 'project';
  var li = el('li', 'tc-node' + (item ? ' tc-item' : ' tc-folder'), null);
  li.dataset.id = n.id;
  var row = el('div', 'tc-line', null);
  var kids = (n.kids || []).length;
  var fold = el(kids ? 'button' : 'span', 'tc-fold', null);
  if (kids) {
    fold.setAttribute('type', 'button');
    fold.setAttribute('aria-expanded', 'false');
    fold.setAttribute('aria-label', 'Show what is in ' + n.title);
  }
  row.appendChild(fold);
  var tick = el('input', 'tc-tick', null);
  tick.type = 'checkbox';
  tick.setAttribute('aria-label', (item ? 'Let them read ' : 'Let them read everything in ') +
    (n.code ? (TC_KIND[n.kind] || '') + ' ' + n.code + ', ' : '') + n.title);
  row.appendChild(tick);
  var words = el('span', 'tc-words', null);
  var name = el('span', 'tc-name', null);
  if (n.code) name.appendChild(el('span', 'tc-code', n.code));
  if (n.kind === 'quest' || n.kind === 'goal') name.appendChild(el('span', 'tc-pick-kind ' + n.kind, TC_KIND[n.kind]));
  name.appendChild(document.createTextNode(n.title));
  words.appendChild(name);
  words.appendChild(el('span', 'tc-notes', null));
  row.appendChild(words);
  if (item) row.appendChild(levelPick({ decide: true, label: 'What they may do with ' + (n.code ? n.code + ' ' : '') + n.title }));
  li.appendChild(row);
  if (kids) {
    var under = el('ul', 'tc-kids', null);
    under.hidden = true;
    li.appendChild(under);
    // Everything starts closed, and opens when pressed or when something in it is held.
  }
  TC.rows[n.id] = li;
  return li;
}

/* A row opened or closed; what is under it is made the first time. */
function tcFold(li, open) {
  var under = li.querySelector(':scope > .tc-kids');
  if (!under) return;
  if (open && !under.dataset.made) {
    under.dataset.made = '1';
    var n = TC.nodes[li.dataset.id];
    (n.kids || []).forEach(function (k) { under.appendChild(tcTreeRow(k)); });
    tcTreeSync(under);
  }
  under.hidden = !open;
  var fold = li.querySelector(':scope > .tc-line > .tc-fold');
  if (fold) fold.setAttribute('aria-expanded', String(open));
}

/* Every row above this one opened, and this one, so what is under it shows. */
function tcReveal(id) {
  var line = [];
  for (var at = id; at; at = TC.parent[at]) line.unshift(at);
  line.forEach(function (one) { if (TC.rows[one]) tcFold(TC.rows[one], true); });
}

var TC_LEVEL = { view: 'Read', edit: 'Edit', decide: 'Decide' };

/* Whether a column or project above this row is ticked. */
function tcCoveredBy(id, grants) {
  for (var at = TC.parent[id]; at; at = TC.parent[at]) if (grants.indexOf(at) >= 0) return at;
  return '';
}

/* The rows made so far, or those inside `within`, drawn as the levels say now. */
function tcTreeSync(within) {
  var p = tcPerson(TC.open);
  if (!p) return;
  var grants = p.grants || [];
  var rows = within ? within.querySelectorAll('li.tc-node') : Object.keys(TC.rows).map(function (id) { return TC.rows[id]; });
  Array.prototype.forEach.call(rows, function (li) { tcRowDraw(li, p, grants); });
}

function tcRowDraw(li, p, grants) {
  var id = li.dataset.id;
  var n = TC.nodes[id];
  var row = li.querySelector(':scope > .tc-line');
  var tick = /** @type {HTMLInputElement} */ (row.querySelector('.tc-tick'));
  var notes = row.querySelector('.tc-notes');
  notes.textContent = '';
  var off = !p.trusted;
  if (n.kind === 'column' || n.kind === 'project') {
    var covered = tcCoveredBy(id, grants);
    tick.checked = grants.indexOf(id) >= 0 || !!covered;
    tick.disabled = off || !!covered;
    li.classList.toggle('is-inherited', !!covered);
    if (covered) notes.appendChild(el('span', 'tc-line-note', 'from ' + TC.nodes[covered].title));
    return;
  }
  var lv = TC.levels[id] || {};
  var level = lv.level || '';
  var own = lv.own || (lv.from === 'started' ? level : '');
  var inherited = !!level && !own;
  var pick = /** @type {HTMLSelectElement} */ (row.querySelector('select.level-pick'));
  levelPickSet(pick, level, { inherited: inherited, noNone: inherited });
  pick.disabled = off;
  tick.checked = !!level;
  tick.disabled = off || inherited;
  li.classList.toggle('is-inherited', inherited);
  li.classList.toggle('is-held', !!level);
  if (inherited && lv.via) notes.appendChild(el('span', 'tc-line-note', 'from ' + lv.via));
  if (lv.from === 'started') notes.appendChild(el('span', 'tc-line-note', 'They asked for it'));
  if (lv.own && lv.above) {
    notes.appendChild(el('span', 'tc-line-note', 'Over ' + (TC_LEVEL[lv.above] || lv.above) +
      (lv.above_via ? ' from ' + lv.above_via : '')));
    var clear = el('button', 'tc-clear', 'Clear');
    clear.type = 'button';
    clear.disabled = off;
    clear.setAttribute('aria-label', 'Clear the level set on ' + (n.code ? n.code + ' ' : '') + n.title +
      ', back to ' + (TC_LEVEL[lv.above] || lv.above) + ' from above');
    notes.appendChild(clear);
  }
  if (lv.by_rouh) notes.appendChild(el('span', 'tc-line-note', 'Added by Rouh'));
  if (lv.promise) notes.appendChild(el('span', 'tc-line-note tc-line-promise', 'Promise: ' + lv.promise));
}

/* One press in the tree, or an Undo under it, posted; the answer is this contact's levels,
   ticks and acts alone, put in place of what the page held. */
function tcRowPost(body, control) {
  var p = tcPerson(TC.open);
  if (!p || TC.busy) { tcTreeSync(); return Promise.resolve(null); }
  TC.busy = true;
  if (control) control.disabled = true;
  body.id = p.id;
  return fetch('/api/settings/trusted', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
      function () { return { ok: false, out: {} }; });
  }).then(function (a) {
    TC.busy = false;
    if (control) control.disabled = false;
    if (!a.ok) {
      settingsSay((a.out && a.out.error) || 'That was not accepted.', 'bad');
    } else {
      var now = tcPerson(a.out.id) || p;
      now.task_levels = a.out.task_levels || {};
      now.grants = a.out.grants || [];
      now.authority = a.out.authority || now.authority;
      // Ticking a project turns Your tasks on, which the form above shows as it is now.
      (now.levels = a.out.levels || now.levels || []);
      $('tcLevels').querySelectorAll('input[name=level]').forEach(function (x) {
        if (now.levels.indexOf(x.value) >= 0) x.checked = true;
      });
      if (String(now.id) === String(TC.open)) {
        TC.levels = now.task_levels;
        tcLatelyDraw(now);
      }
      settingsSay(a.out.said || '', 'good');
    }
    tcTreeSync();
    return a;
  }).catch(function () {
    TC.busy = false;
    if (control) control.disabled = false;
    settingsSay('That could not be saved. Try again in a moment.', 'bad');
    tcTreeSync();
    return null;
  });
}

$('tcTree').addEventListener('click', function (e) {
  var t = /** @type {HTMLElement} */ (e.target);
  var fold = t.closest('button.tc-fold');
  if (fold) {
    var li = fold.closest('li.tc-node');
    tcFold(li, fold.getAttribute('aria-expanded') !== 'true');
    return;
  }
  var clear = t.closest('button.tc-clear');
  var at = /** @type {HTMLElement | null} */ (clear && clear.closest('li.tc-node'));
  if (clear && at) tcRowPost({ act: 'task_level', task: at.dataset.id, level: '' }, clear);
});

$('tcTree').addEventListener('change', function (e) {
  var t = /** @type {HTMLInputElement} */ (e.target);
  var li = /** @type {HTMLElement | null} */ (t.closest('li.tc-node'));
  if (!li) return;
  var id = li.dataset.id;
  var n = TC.nodes[id];
  if (t.classList.contains('level-pick')) {
    tcRowPost({ act: 'task_level', task: id, level: t.value }, t);
  } else if (t.classList.contains('tc-tick')) {
    if (n.kind === 'column' || n.kind === 'project') tcRowPost({ act: 'tick', node: id, on: t.checked }, t);
    // Ticking a row with nothing on it gives Read; unticking it takes its own level away.
    else tcRowPost({ act: 'task_level', task: id, level: t.checked ? 'view' : '' }, t);
  }
});

/* Find in the tree: the rows whose name or number has what is typed, and the rows they are
   in, opened; everything else is out of the way until the box is empty again. */
$('tcFind').addEventListener('input', function () {
  var q = this.value.trim().toLowerCase().replace(/^#/, '');
  var keep = {};
  if (q) {
    Object.keys(TC.nodes).forEach(function (id) {
      var n = TC.nodes[id];
      if ((n.code && (n.code === q || n.code.indexOf(q) === 0)) || n.title.toLowerCase().indexOf(q) >= 0) {
        for (var at = id; at; at = TC.parent[at]) keep[at] = true;
        tcReveal(TC.parent[id]);
      }
    });
  }
  Object.keys(TC.rows).forEach(function (id) { TC.rows[id].hidden = !!q && !keep[id]; });
});

$('tcTreeInfo').addEventListener('click', function () {
  var more = $('tcTreeMore');
  more.hidden = !more.hidden;
  this.setAttribute('aria-expanded', String(!more.hidden));
});

/* Lately: only what they did where they decide, with Undo, closed until opened. What was
   given them is the tree's, and nobody's quoted words are shown: Petar, 12 October 2026, "I
   don't need to prove it here that I have allowed it". The words stay in the record
   (`DelegateAct.words`). */
function tcLatelyDraw(p) {
  var auth = p.authority || { acts: [] };
  var first = (p.name || 'them').split(' ')[0];
  var OUT = { done: 'Done', refused: 'Refused', for_owner: 'Held for you', answered: 'You answered', undone: 'Undone' };
  var theirs = (auth.acts || []).filter(function (x) {
    return ['grant', 'extend', 'revoke', 'undo'].indexOf(x.act) < 0;
  });
  $('tcLatelyHead').textContent = 'What ' + first + ' did lately' + (theirs.length ? ' (' + theirs.length + ')' : '');
  var acts = $('tcLately');
  acts.textContent = '';
  theirs.forEach(function (x) {
    // A row written before 20 October 2026 may still say for_petar.
    if (x.outcome === 'for_petar') x.outcome = 'for_owner';
    var li = el('li', 'tc-auth-row', null);
    var main = el('div', 'tc-auth-main', null);
    if (x.work_title || x.work_code) main.appendChild(tcAuthWork(x.work_kind, x.work_code, x.work_title, ''));
    var line = el('span', 'tc-auth-line', null);
    if (OUT[x.outcome]) line.appendChild(el('span', 'tc-auth-pill ' + x.outcome, OUT[x.outcome]));
    var what = x.outcome === 'refused' ? (x.why || x.said) : (x.said || x.why);
    if (what) line.appendChild(el('span', 'tc-auth-what', what));
    main.appendChild(line);
    if (x.undone_said) main.appendChild(el('span', 'tc-auth-sub', 'Undone: ' + x.undone_said));
    main.appendChild(el('span', 'tc-auth-day', tcDay(x.at)));
    li.appendChild(main);
    if (x.can_undo) {
      var u = el('button', 'ctl small', 'Undo');
      u.type = 'button';
      u.dataset.actId = String(x.id);
      u.setAttribute('aria-label', 'Undo: ' + (x.said || x.act));
      li.appendChild(u);
    }
    acts.appendChild(li);
  });
  if (!theirs.length) acts.appendChild(el('li', 'tc-none', 'Nothing yet.'));
}

$('tcLately').addEventListener('click', function (e) {
  var b = /** @type {HTMLButtonElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('button[data-act-id]'));
  if (!b) return;
  tcRowPost({ act: 'authority_undo', act_id: b.dataset.actId }, b);
});

/* The work a decision is in, on one line in bold: "19-17 Pricing architecture v2", "Quest 4
   Find a venue". */
function tcAuthWork(kind, code, title, href) {
  var nameEl = el('span', 'tc-auth-name', null);
  var said = (kind === 'quest' ? 'Quest ' : '') + (code ? code + ' ' : '') + (title || '');
  if (href) {
    var a = el('a', '', said);
    a.href = href;
    nameEl.appendChild(a);
  } else nameEl.textContent = said;
  return nameEl;
}

/* A day as Petar says it, "10 Oct", with the year only when it is not this one. */
function tcDay(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  var thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString('en-GB', thisYear ? { day: 'numeric', month: 'short' }
    : { day: 'numeric', month: 'short', year: 'numeric' });
}

var TC_KIND = { task: 'Task', step: 'Step', goal: 'Goal', quest: 'Quest' };

/* Their own Telegram account (`rouh/telegram_guests.py`): Petar makes a code,
   they send it to the bot from their own Telegram, and he confirms the
   account here. Nothing is linked any other way. The code is shown only in
   the answer to the press that made it, and never again. */
function tcWhen(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function tcDrawTelegram(p) {
  var d = TC.data || {};
  var t = p.telegram || {};
  var name = p.name || 'them';
  var acts = $('tcTgActs');
  acts.textContent = '';
  var code = TC.tgCode && String(TC.tgCode.id) === String(p.id) && t.state === 'waiting' ? TC.tgCode : null;
  $('tcTgCode').hidden = !code;
  function button(label, act, cls, extra) {
    var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), label);
    b.type = 'button';
    b.dataset.act = act;
    if (extra) b.dataset.tg = extra;
    acts.appendChild(b);
    return b;
  }
  var said;
  if (t.state === 'linked') {
    said = 'Linked to ' + t.account + ' since ' + tcWhen(t.linked_at) + '. What ' + name +
      ' writes to Rouh there is handled exactly as their email is: the same levels, grants and approvals, and the answer goes back on Telegram.';
    button('Unlink', 'tg_unlink', 'danger');
  } else if (t.state === 'claimed') {
    said = 'A Telegram account sent ' + name + '\'s code on ' + tcWhen(t.claimed_at) + ': ' + t.account +
      '. Confirm it only if that is ' + name + '\'s own account. Nothing it sends reaches Rouh until you do.';
    button('Confirm it is ' + name + '\'s', 'tg_confirm', 'primary', t.tg_user_id);
    button('Refuse', 'tg_refuse', '');
  } else if (t.state === 'waiting') {
    said = 'A link code is out until ' + tcWhen(t.expires_at) + '. Nothing is linked until ' + name +
      ' sends it to the bot from their own Telegram and you confirm the account here.';
    button('Make a new code', 'tg_code', '');
    button('Withdraw the code', 'tg_unlink', '');
  } else {
    said = (t.state === 'lapsed' ? 'The last code lapsed unused. ' : '') +
      'Not linked. Rouh answers ' + name + ' on Telegram only once they link their own account: make a code here and send it to them, ' +
      'they send it to the bot from their own Telegram, and you confirm the account here before anything they write there is read.';
    var make = button('Make a link code', 'tg_code', '');
    if (d.telegram_off) {
      make.disabled = true;
      said += ' ' + d.telegram_off;
    }
  }
  $('tcTgSaid').textContent = said;
  if (code) {
    $('tcTgCodeSaid').textContent = 'Send ' + name + ' this link to open on their own phone, or the line under it to send to the bot. It works once, until ' + tcWhen(code.until) + ', and is not shown again.';
    $('tcTgLink').hidden = !code.link;
    $('tcTgLink').href = code.link || '#';
    $('tcTgLink').textContent = code.link || '';
    $('tcTgCommand').textContent = code.command;
  }
}

$('tcTgActs').addEventListener('click', function (e) {
  var b = e.target.closest('button[data-act]');
  var p = tcPerson(TC.open);
  if (!b || !p || TC.busy) return;
  var act = b.dataset.act;
  if (act === 'tg_unlink' && (p.telegram || {}).state === 'linked' &&
      !window.confirm('Unlink ' + (p.name || 'them') + '\'s Telegram account? Nothing they write there reaches Rouh after this.')) return;
  TC.busy = true;
  b.disabled = true;
  tcPost({ act: act, id: p.id, tg_user_id: b.dataset.tg || '' }).then(function (a) {
    TC.busy = false;
    TC.tgCode = a.ok && a.out.tg_code ? a.out.tg_code : null;
    tcAnswered(a);
    if (!a.ok) b.disabled = false;
  }).catch(function () {
    TC.busy = false;
    b.disabled = false;
    settingsSay('That could not be done. Try again in a moment.', 'bad');
  });
});

/* Ticking a level ticks the ones above it, and unticking one unticks the
   ones below. */
function tcSyncLevels(changed) {
  var levels = Array.prototype.slice.call($('tcLevels').querySelectorAll('input[name=level]'));
  var at = levels.indexOf(changed);
  if (changed && changed.checked) levels.slice(0, at).forEach(function (x) { x.checked = true; });
  if (changed && !changed.checked) levels.slice(at + 1).forEach(function (x) { x.checked = false; });
}

function tcTicked(box, name) {
  return Array.prototype.slice.call(box.querySelectorAll('input[name=' + name + ']'))
    .filter(function (x) { return x.checked && !x.disabled; })
    .map(function (x) { return x.value; });
}

/* More grants on a contact's page (`rouh/grants.py`): every grant given as a row -
   Clockwork, Memory, Shared task and any made under Grants - ticked one by one. One that
   sits under another the contact has, a grant ticked here or a level ticked above, comes
   with it, and shows so, ticked and not to be unticked on its own. */
function tcDrawMoreGrants(p) {
  var d = TC.data || {};
  var given = p.extra_grants || [];
  var first = (p.name || 'them').split(' ')[0];
  $('tcMoreSaid').textContent = 'Beyond the levels, each given to ' + first + ' on its own. ' +
    'One under another comes with it.';
  var box = $('tcMoreGrants');
  box.textContent = '';
  (d.more_grants || []).forEach(function (g) {
    if (g.by_calendar) { box.appendChild(tcCalendarGrant(g, given)); return; }
    var label = el('label', 'tc-check', null);
    label.style.setProperty('--depth', String(g.depth || 0));
    var input = el('input', '', null);
    input.type = 'checkbox';
    input.name = 'more_grant';
    input.value = g.key;
    input.checked = given.indexOf(g.key) >= 0;
    input.dataset.was = input.checked ? '1' : '';
    label.appendChild(input);
    var words = el('span', '', null);
    words.appendChild(document.createTextNode(g.name));
    if (g.description) words.appendChild(el('span', 'tc-said', g.description));
    var note = el('span', 'tc-said tc-comes', '');
    note.hidden = true;
    words.appendChild(note);
    label.appendChild(words);
    box.appendChild(label);
  });
  if (!(d.more_grants || []).length) box.appendChild(el('span', 'tc-dim', 'There are none yet.'));
  tcDrawCapGrants(p, box);
  tcSyncMore();
  if (box.querySelector('.tc-cal-grant')) tcCalendarsLoad(p);
}

/** @type {Object<string, string>} */
var TC_CAP_EVENT = { approved: 'Given by you', allowed_once: 'Allowed once by you', used: 'Used',
  freed: 'Free again: the call it was used for made nothing', revoked: 'Taken back',
  suspended: 'Suspended', resumed: 'In force again', declined: 'Declined' };

/* Their grants of their own (CAPABILITIES.md): each in the one sentence Rouh's code made from
   exactly what it gives, its state, and under Details what it lets Rouh do, how often it was
   used, the message it came from and its history. One in force can be taken back here, at
   once. Nothing is drawn when they have none. */
function tcDrawCapGrants(p, box) {
  var mine = p.cap_grants || [];
  if (!mine.length) return;
  var list = el('div', 'tc-capgrants', null);
  list.id = 'tcCapGrants';
  mine.forEach(function (g) {
    var live = g.state_now === 'active' || g.state_now === 'suspended';
    var row = el('div', 'tc-capgrant' + (live ? '' : ' tc-capgrant-off'), null);
    row.id = 'capGrant-' + g.id;
    var top = el('div', 'tc-capgrant-top', null);
    top.appendChild(el('span', 'tc-capgrant-words', g.wording));
    top.appendChild(el('span', 'tc-auth-pill ' + (g.state_now === 'active' ? 'done' : g.state_now === 'suspended' ? 'refused' : ''), g.state_said));
    row.appendChild(top);
    if (g.state_now === 'suspended' && g.suspended_reason) row.appendChild(el('span', 'tc-note', g.suspended_reason));
    var more = el('details', 'tc-capgrant-more', null);
    more.id = 'capGrantMore-' + g.id;
    more.appendChild(el('summary', '', 'Details'));
    (g.effects || []).forEach(function (e) { more.appendChild(el('span', 'tc-said', 'It lets Rouh ' + e + '.')); });
    if (g.about) more.appendChild(el('span', 'tc-said', g.about));
    more.appendChild(el('span', 'tc-said', 'Used ' + g.uses_done + ' time' + (g.uses_done === 1 ? '' : 's') +
      (g.uses_today ? ', ' + g.uses_today + ' in the last day' : '') + '. ' + g.name + ', version ' + g.version + '.'));
    if (g.case_href) {
      var from = el('span', 'tc-said', 'From ');
      var a = el('a', '', 'the message it was asked in');
      a.href = g.case_href;
      from.appendChild(a);
      more.appendChild(from);
    }
    if (g.reason) more.appendChild(el('span', 'tc-said', 'Your reason: “' + g.reason + '”'));
    var hist = el('ul', 'tc-auth-acts tc-capgrant-history', null);
    (g.events || []).forEach(function (e) {
      var li = el('li', 'tc-said', null);
      li.textContent = new Date(e.at * 1000).toLocaleString() + ': ' + (TC_CAP_EVENT[e.kind] || e.kind) +
        (e.detail && e.detail.reason ? ' - “' + e.detail.reason + '”' : '') +
        (e.detail && e.detail.why ? ' - ' + e.detail.why : '');
      hist.appendChild(li);
    });
    more.appendChild(hist);
    row.appendChild(more);
    if (live) {
      var back = el('button', 'ctl small tc-capgrant-back', 'Take it back');
      back.type = 'button';
      back.id = 'capGrantBack-' + g.id;
      back.addEventListener('click', function () {
        if (TC.busy) return;
        TC.busy = true;
        back.disabled = true;
        tcPost({ act: 'cap_revoke', id: p.id, grant: g.id }).then(function (r) {
          TC.busy = false;
          tcAnswered(r);
        }).catch(function () {
          TC.busy = false;
          back.disabled = false;
          settingsSay('That could not be done. Try again in a moment.', 'bad');
        });
      });
      row.appendChild(back);
    }
    list.appendChild(row);
  });
  box.appendChild(list);
}

/* A grant that lifts committing Petar's time is given one calendar at a time (Petar, 16 October
   2026, fr_6c6d23abe250: "you pick which calendar specifically you approve"). Its own box is
   not drawn: it is held while at least one calendar under it is ticked, and only those are
   reached (`grants.calendars_of`). The calendars are asked of Google as the page is drawn. */
function tcCalendarGrant(g, given) {
  var wrap = el('div', 'tc-cal-grant', null);
  wrap.style.setProperty('--depth', String(g.depth || 0));
  wrap.dataset.grant = g.key;
  var head = el('div', 'tc-cal-head', null);
  var input = el('input', '', null);
  input.type = 'checkbox';
  input.name = 'more_grant';
  input.value = g.key;
  input.hidden = true;
  input.checked = given.indexOf(g.key) >= 0;
  input.dataset.was = input.checked ? '1' : '';
  head.appendChild(input);
  var words = el('span', '', null);
  words.appendChild(el('span', 'tc-cal-name', g.name));
  if (g.description) words.appendChild(el('span', 'tc-said', g.description));
  var note = el('span', 'tc-said tc-comes', '');
  note.hidden = true;
  words.appendChild(note);
  head.appendChild(words);
  wrap.appendChild(head);
  var list = el('div', 'tc-cals', null);
  list.appendChild(el('span', 'tc-dim', 'Asking Google which calendars Rouh can change...'));
  wrap.appendChild(list);
  return wrap;
}

var TC_CALS = { seq: 0 };

function tcCalendarsLoad(p) {
  var mine = ++TC_CALS.seq;
  if (typeof fetch !== 'function') return;
  fetch('/api/settings/google/calendars', { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (out) { return { ok: r.ok, out: out }; });
    })
    .then(function (a) {
      if (mine !== TC_CALS.seq) return;
      tcCalendarsDraw(p, a.ok ? a.out : { say: (a.out && a.out.error) || 'Google did not list the calendars.' });
    })
    .catch(function () {
      if (mine !== TC_CALS.seq) return;
      tcCalendarsDraw(p, { say: 'The calendars could not be read. Try again in a moment.' });
    });
}

/* Only the calendars Rouh may change are offered: the grant is for changing them. One given
   before there was a choice reaches every calendar, so all of them start ticked. If Google
   cannot be asked, nothing about the grant changes on Save. */
function tcCalendarsDraw(p, d) {
  var cals = (d.calendars || []).filter(function (c) { return c.access === 'owner' || c.access === 'writer'; });
  var reach = p.grant_calendars || {};
  $('tcMoreGrants').querySelectorAll('.tc-cal-grant').forEach(function (wrap) {
    var key = wrap.dataset.grant;
    var list = wrap.querySelector('.tc-cals');
    list.textContent = '';
    if (!cals.length) {
      var why = d.say || (d.connected === false ? 'Google is not connected, so there are no calendars to pick yet.'
        : 'Rouh cannot change any calendar through ' + (d.account || 'its Google account') + ' yet.');
      list.appendChild(el('span', 'tc-dim', why));
      return;
    }
    var held = Object.prototype.hasOwnProperty.call(reach, key);
    var ids = held ? reach[key] : [];
    cals.forEach(function (c) {
      var name = el('span', '', c.name || c.id);
      if (c.theirs) name.appendChild(el('span', 'cal-whose', 'Yours'));
      else if (c.primary) name.appendChild(el('span', 'cal-whose', 'This account\'s own'));
      var on = held && (ids === null || ids.indexOf(c.id) >= 0);
      var label = tcCheck('grant_calendar', c.id, on, name, c.id !== (c.name || c.id) ? c.id : '');
      label.querySelector('input').dataset.was = on ? '1' : '';
      list.appendChild(label);
    });
    if (held && ids === null) {
      list.appendChild(el('span', 'tc-said', 'Given before calendars could be picked, so it reaches every calendar, ' +
        'and any connected later, until you save.'));
    }
    wrap.dataset.drawn = '1';
  });
  tcSyncMore();
}

/* The grant is held while a calendar under it is ticked. */
function tcSyncCalendarGrant(wrap) {
  var master = /** @type {HTMLInputElement} */ (wrap.querySelector('input[name=more_grant]'));
  if (master.disabled) return;
  master.checked = !!wrap.querySelector('input[name=grant_calendar]:checked');
}

/* The calendars ticked under each calendar grant, by its key, for the ones drawn from Google
   and not coming with something above. */
function tcCalendarsTicked() {
  /** @type {Object<string, string[]>} */
  var out = {};
  $('tcMoreGrants').querySelectorAll('.tc-cal-grant').forEach(function (wrap) {
    var master = /** @type {HTMLInputElement} */ (wrap.querySelector('input[name=more_grant]'));
    if (wrap.dataset.drawn !== '1' || master.disabled) return;
    out[wrap.dataset.grant] = Array.prototype.slice.call(wrap.querySelectorAll('input[name=grant_calendar]'))
      .filter(function (x) { return x.checked; })
      .map(function (x) { return x.value; });
  });
  return out;
}

function tcMoreGrant(key) {
  var list = (TC.data && TC.data.more_grants) || [];
  for (var i = 0; i < list.length; i++) if (list[i].key === key) return list[i];
  return null;
}

/* Which of them come with something ticked: a grant above, or a level above. */
function tcSyncMore() {
  var boxes = Array.prototype.slice.call($('tcMoreGrants').querySelectorAll('input[name=more_grant]'));
  var levels = tcTicked($('tcLevels'), 'level');
  var on = {};
  boxes.forEach(function (b) { if (b.checked && !b.disabled) on[b.value] = true; });
  boxes.forEach(function (box) {
    var g = tcMoreGrant(box.value);
    var from = '';
    (g ? g.above : []).forEach(function (k) {
      if (from) return;
      if (on[k] || (g.above_levels.indexOf(k) >= 0 && levels.indexOf(k) >= 0)) from = g.above_names[k] || k;
    });
    var note = /** @type {HTMLElement} */ (box.parentElement.querySelector('.tc-comes'));
    if (from) {
      if (!box.disabled) box.dataset.was = box.checked ? '1' : '';
      box.checked = true;
      box.disabled = true;
      note.textContent = 'Comes with ' + from + '.';
      note.hidden = false;
    } else {
      if (box.disabled) { box.disabled = false; box.checked = box.dataset.was === '1'; }
      note.hidden = true;
    }
    // A calendar grant that comes with something above reaches every calendar with it.
    var wrap = box.closest('.tc-cal-grant');
    if (wrap) {
      wrap.querySelectorAll('input[name=grant_calendar]').forEach(function (c) {
        if (from && !c.disabled) { c.dataset.was = c.checked ? '1' : ''; c.checked = true; c.disabled = true; }
        else if (!from && c.disabled) { c.disabled = false; c.checked = c.dataset.was === '1'; }
      });
      if (!from) tcSyncCalendarGrant(wrap);
    }
  });
}

/* What is given as rows: what is ticked on its own, and what was given before and now also
   comes with something above, so taking that away later leaves it as it was. */
function tcMoreTicked() {
  return Array.prototype.slice.call($('tcMoreGrants').querySelectorAll('input[name=more_grant]'))
    .filter(function (x) { return x.checked && (!x.disabled || x.dataset.was === '1'); })
    .map(function (x) { return x.value; });
}

/* ---------- Settings: Trusted contacts > Grants ----------
 *
 * What can be given a trusted contact (`rouh/grants.py`), from GET /api/settings/grants,
 * at /anatomy/behaviour/trusted-contacts/grants. Petar, 11 October 2026: grants are data, with a
 * name and a description for him and the words Rouh's reading is told, in a tree where a
 * grant brings what sits under it; he renames, rewords, moves and merges them here, and
 * every change is a version that can be put back.
 */
var TCG_KEY = 'grants';
var TCG = { data: null, open: '', fresh: false, busy: false };

function tcgLoad(versionsOf) {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/grants' + (versionsOf ? '?versions=' + encodeURIComponent(versionsOf) : ''),
    { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('grants ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      TCG.data = data;
      $('tcGTrouble').hidden = true;
      tcgDraw();
    })
    .catch(function () {
      $('tcGTrouble').textContent = 'The grants could not be read from the server. Try again in a moment.';
      $('tcGTrouble').hidden = false;
    });
}

function tcgPost(body) {
  return fetch('/api/settings/grants', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
      function () { return { ok: false, out: {} }; });
  }).then(function (a) {
    if (a.ok) {
      TCG.data = a.out;
      // What contacts' pages offer follows the grants.
      tcLoad();
    }
    return a;
  });
}

function tcgGrant(key) {
  var rows = (TCG.data && TCG.data.grants) || [];
  for (var i = 0; i < rows.length; i++) if (rows[i].key === key) return rows[i];
  return null;
}

function tcgHeldSaid(g) {
  if (g.holding === 'level') {
    return (g.held ? 'Held by ' + g.holders.join(', ') + '. ' : 'Nobody holds it yet. ') +
      'Given on a contact\'s page, under What they may do.';
  }
  if (g.holding === 'inbox') {
    return (g.held ? 'Held by ' + g.holders.join(', ') + '. ' : 'Nobody holds it yet. ') +
      'Set on a contact\'s page, under Your inbox - how far.';
  }
  if (!g.held) return 'Nobody holds it yet. Give it on a contact\'s page, under More grants.';
  var through = g.holders.filter(function (n) { return g.given.indexOf(n) < 0; });
  var said = [];
  if (g.given.length) said.push('Given to ' + g.given.join(', ') + '.');
  if (through.length) said.push('Held through a grant above it by ' + through.join(', ') + '.');
  return said.join(' ');
}

function tcgDraw() {
  var d = TCG.data;
  if (!d) return;
  var limits = $('tcGLimits');
  limits.textContent = '';
  (d.limits || []).forEach(function (l) { limits.appendChild(el('li', '', l)); });
  limits.appendChild(el('li', '', 'Whatever is granted, these wait for you every time, and the code refuses a grant whose words would cover one.'));
  var list = $('tcGList');
  list.textContent = '';
  (d.grants || []).forEach(function (g) {
    var li = el('li', '', null);
    var row = el('button', 'tc-row' + (TCG.open === g.key && !TCG.fresh ? ' open' : ''), null);
    row.type = 'button';
    row.dataset.key = g.key;
    row.style.marginLeft = Math.min(g.depth || 0, 4) * 18 + 'px';
    row.style.width = 'calc(100% - ' + Math.min(g.depth || 0, 4) * 18 + 'px)';
    row.setAttribute('aria-expanded', TCG.open === g.key && !TCG.fresh ? 'true' : 'false');
    var main = el('span', 'tc-row-main', null);
    main.appendChild(el('span', 'tc-row-name', g.name));
    // Its title, one line on what it lets Rouh do for them; the whole description is in the form.
    if (g.title || g.description) main.appendChild(el('span', 'tc-row-desc', g.title || g.description));
    // Made from words with nothing in code behind it: kept, and allows nothing (CAPABILITIES.md).
    if (g.for_review) main.appendChild(el('span', 'tc-note', 'Made from words alone: it allows nothing now, and is kept for you to look at.'));
    row.appendChild(main);
    var side = el('span', 'tc-row-side', null);
    side.appendChild(el('span', 'tc-pill' + (g.held ? ' good' : ''), g.held === 1 ? '1 holds it' : g.held + ' hold it'));
    if (g.holding !== 'grant') side.appendChild(el('span', 'tc-row-kind', g.holding === 'level' ? 'A level' : 'Your inbox'));
    row.appendChild(side);
    var chev = el('span', 'tc-chev', null);
    chev.setAttribute('aria-hidden', 'true');
    row.appendChild(chev);
    li.appendChild(row);
    list.appendChild(li);
  });
  tcgDrawForm();
}

function tcgOption(value, words, selected) {
  var o = el('option', '', words);
  o.value = value;
  if (selected) o.selected = true;
  return o;
}

function tcgDrawForm() {
  var form = $('tcGForm');
  var g = TCG.fresh ? null : tcgGrant(TCG.open);
  if (!TCG.fresh && !g) { form.hidden = true; return; }
  form.hidden = false;
  $('tcGSaid').hidden = true;
  var rows = (TCG.data && TCG.data.grants) || [];
  // The boxes are filled when a grant, or a new version of it, is opened, and never over
  // what is being typed: the list is read again under it while it is open.
  var stamp = g ? g.key + '@' + g.revision : 'new';
  var typing = form.dataset.stamp === stamp;
  form.dataset.stamp = stamp;
  $('tcGFormHead').textContent = g ? g.name : 'New grant';
  $('tcGVersion').hidden = !g;
  if (g) $('tcGVersion').textContent = 'Version ' + g.revision;
  $('tcGHeld').textContent = g ? tcgHeldSaid(g) : 'Nobody holds it until you give it, on a contact\'s page under More grants. ' +
    'Under another grant, everybody who holds that one holds this too.';
  if (!typing) {
    $('tcGName').value = g ? g.name : '';
    $('tcGTitle').value = g ? g.title || '' : '';
    $('tcGDesc').value = g ? g.description : '';
  }
  // What it lets Rouh do, as the code declares it: not the words above (CAPABILITIES.md).
  var allows = $('tcGAllows');
  allows.textContent = '';
  ((g && g.allows) || []).forEach(function (c) {
    allows.appendChild(el('li', '', c.name + ': it lets Rouh ' + (c.effects || []).join('; ') + '.'));
  });
  if (g && !(g.allows || []).length) allows.appendChild(el('li', '', 'Nothing: it was made from words alone, and words allow nothing.'));
  var parent = $('tcGParent');
  parent.textContent = '';
  parent.appendChild(tcgOption('', 'Nothing: a grant of its own', g ? !g.parent : true));
  var allowed = g ? g.parents : rows.filter(function (r) { return r.holding !== 'inbox'; }).map(function (r) { return r.key; });
  rows.forEach(function (r) {
    if (allowed.indexOf(r.key) < 0 && !(g && r.key === g.parent)) return;
    parent.appendChild(tcgOption(r.key, r.path, g ? g.parent === r.key : false));
  });
  parent.disabled = !!(g && !g.movable);
  $('tcGPlace').hidden = !(g && !g.movable);
  $('tcGPlace').textContent = g && !g.movable ? 'It keeps its place: where it sits says what comes with what, and Rouh\'s code relies on it.' : '';
  $('tcGSave').textContent = 'Save';

  var vers = $('tcGVersions');
  vers.textContent = '';
  var known = TCG.data.versions && g && TCG.data.versions.key === g.key ? TCG.data.versions.list : null;
  $('tcGVerPart').hidden = !g;
  if (g && !known) vers.appendChild(el('li', '', null)).appendChild(el('span', 'tc-none', 'Reading the versions...'));
  (known || []).forEach(function (v) {
    var li = el('li', '', null);
    li.appendChild(el('span', 'tc-when', 'Version ' + v.revision));
    var what = el('span', 'tc-what', null);
    what.appendChild(document.createTextNode(tcWhen(v.at) + (v.by_said ? ' · ' + v.by_said : '') +
      (v.revision === g.revision ? ' · as it is now' : '')));
    var why = el('span', 'tc-gv-why', (v.name !== g.name ? v.name + ': ' : '') + (v.why || ''));
    what.appendChild(why);
    if (v.case) {
      var a = el('a', '', 'Its email');
      var href = '/mail/case/' + encodeURIComponent(v.case);
      // Inside Rouh, beside the orb, like the case it names (`approvalspage.js`).
      linkTo(a, href);
      a.addEventListener('click', function (e) {
        if (e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
        goToAddress(href);
      });
      why.appendChild(document.createTextNode(' '));
      why.appendChild(a);
    }
    if (v.revision !== g.revision) {
      var back = el('button', 'ctl small', 'Put this version back');
      back.type = 'button';
      back.dataset.revision = String(v.revision);
      back.setAttribute('aria-label', 'Put version ' + v.revision + ' of ' + g.name + ' back');
      what.appendChild(el('br', '', null));
      what.appendChild(back);
    }
    li.appendChild(what);
    vers.appendChild(li);
  });
  if (g && !known) tcgLoad(g.key);
}

function tcgOpen(key, fresh) {
  TCG.open = key || '';
  TCG.fresh = !!fresh;
  $('tcGForm').dataset.stamp = '';
  tcgDraw();
  $('tcGForm').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  $('tcGName').focus({ preventScroll: true });
}

function tcgAnswered(a, onFail) {
  if (!a.ok) {
    var why = (a.out && a.out.error) || 'That was not accepted.';
    if (onFail) { onFail.textContent = why; onFail.hidden = false; } else settingsSay(why, 'bad');
    return false;
  }
  settingsSay(a.out.said || '', 'good');
  tcgDraw();
  return true;
}

$('tcGList').addEventListener('click', function (e) {
  var row = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('.tc-row'));
  if (!row) return;
  var key = row.dataset.key || '';
  if (TCG.open === key && !TCG.fresh) { TCG.open = ''; tcgDraw(); return; }
  tcgOpen(key, false);
});
$('tcGClose').addEventListener('click', function () { TCG.open = ''; TCG.fresh = false; tcgDraw(); });

$('tcGForm').addEventListener('submit', function (e) {
  e.preventDefault();
  if (TCG.busy) return;
  var g = TCG.fresh ? null : tcgGrant(TCG.open);
  if (!TCG.fresh && !g) return;
  if (!g) return;
  var body = { act: 'save', key: g.key, name: $('tcGName').value,
    title: $('tcGTitle').value, description: $('tcGDesc').value };
  if (!g || g.movable) body.parent = $('tcGParent').value;
  var before = g ? g.revision : 0;
  TCG.busy = true;
  $('tcGSave').disabled = true;
  tcgPost(body).then(function (a) {
    TCG.busy = false;
    $('tcGSave').disabled = false;
    if (!a.ok) { tcgAnswered(a, $('tcGSaid')); return; }
    TCG.open = a.out.shown || TCG.open;
    TCG.fresh = false;
    if (document.activeElement && $('tcGForm').contains(document.activeElement)) /** @type {HTMLElement} */ (document.activeElement).blur();
    tcgAnswered(a);
    var now = tcgGrant(TCG.open);
    if (g && now && now.revision !== before) {
      // A few seconds to take it back, by putting the version before it back.
      var key = g.key;
      notify(a.out.said || 'Saved.', { tone: 'success', for: 9000, action: { label: 'Undo', run: function () {
        tcgPost({ act: 'undo', key: key, revision: before }).then(function (b) { TCG.open = key; tcgAnswered(b); });
      } } });
    }
  }).catch(function () {
    TCG.busy = false;
    $('tcGSave').disabled = false;
    $('tcGSaid').textContent = 'That could not be saved. Try again in a moment.';
    $('tcGSaid').hidden = false;
  });
});

$('tcGVersions').addEventListener('click', function (e) {
  var b = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (e.target).closest('button[data-revision]'));
  var g = tcgGrant(TCG.open);
  if (!b || !g) return;
  tcgPost({ act: 'undo', key: g.key, revision: Number(b.dataset.revision) }).then(function (a) {
    tcgAnswered(a, $('tcGSaid'));
  });
});

/* What a press said, and the list or the person drawn again. */
function tcAnswered(a) {
  if (!a.ok) {
    settingsSay((a.out && a.out.error) || 'That was not accepted.', 'bad');
    return a;
  }
  settingsSay(a.out.said || '', 'good');
  tcDraw();
  return a;
}

$('tcLevels').addEventListener('change', function (e) {
  if (e.target.name === 'level') { tcSyncLevels(e.target); tcSyncMore(); }
});
$('tcMoreGrants').addEventListener('change', function (e) {
  var box = /** @type {HTMLInputElement} */ (e.target);
  if (box.name === 'grant_calendar') tcSyncCalendarGrant(box.closest('.tc-cal-grant'));
  tcSyncMore();
});
$('tcInbox').addEventListener('change', tcSyncInbox);

$('tcForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var p = tcPerson(TC.open);
  if (!p || TC.busy) return Promise.resolve(null);
  TC.busy = true;
  $('tcSave').disabled = true;
  $('tcSaid').hidden = true;
  tcPost({
    act: 'save', id: p.id, contact_id: p.contact_id || '', trusted: !!p.trusted,
    name: $('tcName').value, addresses: tcTicked($('tcAddrs'), 'address'),
    more: $('tcMore').value, levels: tcTicked($('tcLevels'), 'level'),
    more_grants: tcMoreTicked(),
    grant_calendars: tcCalendarsTicked(),
    inbox_scope: tcPicked($('tcInbox'), 'inbox') || 'none', inbox_from: $('tcInboxFrom').value,
    beyond: tcPicked($('tcBeyond'), 'beyond') || 'ask',
    sees: tcTicked($('tcSees'), 'sees'),
    zone: $('tcZone').value.trim(),
    group: $('tcGroup').value, note: $('tcNote').value,
  }).then(function (a) {
    TC.busy = false;
    $('tcSave').disabled = false;
    if (!a.ok) {
      $('tcSaid').textContent = (a.out && a.out.error) || 'That was not accepted.';
      $('tcSaid').hidden = false;
      return;
    }
    // Back to the list, with the row just saved marked.
    TC.marked = String(a.out.saved || p.id);
    TC.open = '';
    tcAnswered(a);
    var body = $('settingsView').querySelector('.settings-body');
    if (body) body.scrollTop = 0;
    addrTouch();
  }).catch(function () {
    TC.busy = false;
    $('tcSave').disabled = false;
    $('tcSaid').textContent = 'That could not be saved. Try again in a moment.';
    $('tcSaid').hidden = false;
  });
});

$('tcToggle').addEventListener('click', function () {
  var p = tcPerson(TC.open);
  if (!p) return;
  tcPost({ act: p.trusted ? 'untrust' : 'trust', id: p.id }).then(tcAnswered);
});

$('tcRemove').addEventListener('click', function () {
  var p = tcPerson(TC.open);
  if (!p) return;
  if (!window.confirm('Remove ' + (p.name || 'them') + ' from your trusted contacts? ' +
    'Their email is then answered with Communication only, like anybody else.')) return;
  tcPost({ act: 'remove', id: p.id }).then(function (a) {
    if (a.ok) { TC.open = ''; addrTouch(); }
    tcAnswered(a);
  });
});

// A row, Back and Cancel are real links, so they open in a new tab too; an
// ordinary press moves within the page.
function tcLinkPress(e, id) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  settingsSay('');
  tcShow(id);
}
$('tcList').addEventListener('click', function (e) {
  var row = e.target.closest('.tc-row');
  if (row) tcLinkPress(e, row.dataset.id);
});
$('tcBack').addEventListener('click', function (e) { tcLinkPress(e, ''); });
$('tcGBack').addEventListener('click', function (e) { tcLinkPress(e, ''); });
$('tcGrantsBtn').addEventListener('click', function (e) { tcLinkPress(e, TCG_KEY); });
$('tcCancel').addEventListener('click', function (e) { tcLinkPress(e, ''); });

$('tcAddBtn').addEventListener('click', function () {
  var open = $('tcAdd').hidden;
  $('tcAdd').hidden = !open;
  $('tcAddBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
  $('tcAddBtn').textContent = open ? 'Close' : 'Add a contact';
  $('tcAddBtn').classList.toggle('primary', !open);
  if (open) $('tcFindBox').focus();
});

$('tcFindForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var q = $('tcFindBox').value.trim();
  var box = $('tcFound');
  if (!q) { box.hidden = true; return; }
  TC.asked = q;
  fetch('/api/settings/trusted/find?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (out) {
      if (TC.asked !== q) return;
      tcDrawFound(out.found || [], q);
    })
    .catch(function () {
      box.textContent = '';
      box.appendChild(el('p', 'settings-note bad', 'Your contacts could not be searched. Try again in a moment.'));
      box.hidden = false;
    });
});

function tcDrawFound(found, q) {
  var box = $('tcFound');
  box.textContent = '';
  box.hidden = false;
  if (!found.length) {
    box.appendChild(el('p', 'settings-help', 'Nobody in your contacts matches “' + q + '”, or they are already in the list.'));
    // Asked for by address and not in the contacts: the form below already holds them.
    if (TC.addAsked && q === TC.addAsked) $('tcManual').open = true;
    return;
  }
  found.forEach(function (f) {
    var form = el('form', 'tc-hit', null);
    var who = el('div', 'me-card-who', null);
    who.appendChild(el('span', 'me-card-name', f.name || '(no name)'));
    if (f.organisation) who.appendChild(el('span', 'me-card-org', f.organisation));
    form.appendChild(who);
    var emails = f.emails || [];
    if (emails.length) {
      form.appendChild(el('span', 'tc-k', 'Tick each address to trust, exactly'));
      var checks = el('div', 'tc-checks', null);
      emails.forEach(function (a) {
        checks.appendChild(tcCheck('address', a, emails.length === 1, el('span', 'mono', a)));
      });
      form.appendChild(checks);
    } else {
      form.appendChild(el('span', 'tc-dim', 'No address on this contact.'));
    }
    var pick = el('label', 'models-field', 'Your inbox - how far');
    var inboxPick = el('select', 'tc-inbox-pick', null);
    pick.appendChild(inboxPick);
    form.appendChild(pick);
    var said = el('p', 'settings-help bad', null);
    said.hidden = true;
    form.appendChild(said);
    var go = el('button', 'ctl small primary', 'Trust ' + (f.name || 'them'));
    go.type = 'submit';
    go.disabled = !emails.length;
    var acts = el('div', 'setting-actions', null);
    acts.appendChild(go);
    form.appendChild(acts);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      tcAdd({ contact_id: f.id, name: f.name || '', addresses: tcTicked(form, 'address'),
        inbox_scope: inboxPick.value || 'none' }, said);
    });
    box.appendChild(form);
  });
  tcInboxPicks(box);
}

/* Somebody Rouh could not help, asked for by address (?add=<address>&name=<name>, read into
   `TC.addWant` with the rest of the address): the button of the notice Rouh gives when a person
   it does not know writes to it on Slack (`rouh/slack_team.py`). Add a contact opens with them
   looked up in the contacts and their name and address in the form below, so trusting them is
   one press. Once the group's list is drawn, and once. */
function tcAddAsked() {
  var want = TC.addWant;
  if (!want || !TC.data || TC.open) return;
  TC.addWant = null;
  TC.addAsked = want.address;
  $('tcAdd').hidden = false;
  $('tcAddBtn').setAttribute('aria-expanded', 'true');
  $('tcAddBtn').textContent = 'Close';
  $('tcAddBtn').classList.remove('primary');
  $('tcFindBox').value = want.address;
  $('tcNewName').value = want.name;
  $('tcNewAddr').value = want.address;
  $('tcFind').click();
}

/* Somebody new, trusted with Communication, and marked in the list. */
function tcAdd(who, said) {
  said.hidden = true;
  var body = { act: 'save', trusted: true, levels: ['communicate'] };
  for (var k in who) if (Object.prototype.hasOwnProperty.call(who, k)) body[k] = who[k];
  tcPost(body).then(function (a) {
    if (!a.ok) {
      said.textContent = (a.out && a.out.error) || 'That was not accepted.';
      said.hidden = false;
      return;
    }
    TC.marked = String(a.out.saved || '');
    $('tcAdd').hidden = true;
    $('tcAddBtn').setAttribute('aria-expanded', 'false');
    $('tcAddBtn').textContent = 'Add a contact';
    $('tcAddBtn').classList.add('primary');
    $('tcFound').hidden = true;
    $('tcFindBox').value = '';
    $('tcNewName').value = '';
    $('tcNewAddr').value = '';
    $('tcNewInbox').value = 'none';
    $('tcManual').open = false;
    a.out.said = (a.out.said || '') + ' Open them in the list to grant more.';
    tcAnswered(a);
  }).catch(function () {
    said.textContent = 'That could not be saved. Try again in a moment.';
    said.hidden = false;
  });
}

$('tcNewForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var said = $('tcNewForm').querySelector('.tc-new-said');
  if (!said) {
    said = el('p', 'settings-help bad tc-new-said', null);
    said.setAttribute('role', 'alert');
    $('tcNewForm').insertBefore(said, $('tcNewForm').lastElementChild);
  }
  tcAdd({ name: $('tcNewName').value, more: $('tcNewAddr').value,
    inbox_scope: $('tcNewInbox').value || 'none' }, said);
});

$('tcQueueForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var name = $('tcQueueName').value.trim();
  if (!name) return;
  tcPost({ act: 'add_group', group_name: name }).then(function (a) {
    if (a.ok) $('tcQueueName').value = '';
    tcAnswered(a);
  });
});

$('tcTimingForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var remind = $('tcRemindHours').value.trim();
  if (remind === '') {
    settingsSay('Give the time, in hours. 0 means never.', 'bad');
    return;
  }
  $('tcTimingSave').disabled = true;
  tcPost({ act: 'timing', remind_hours: Number(remind) })
    .then(function (a) {
      $('tcTimingSave').disabled = false;
      var focused = document.activeElement;
      if (focused instanceof HTMLElement) focused.blur();
      tcAnswered(a);
    })
    .catch(function () {
      $('tcTimingSave').disabled = false;
      settingsSay('The time could not be saved. Try again in a moment.', 'bad');
    });
});

// A link elsewhere in Settings to one of its groups, such as the line under
// New mail that says where trusted contacts are now.
$('settingsView').addEventListener('click', function (e) {
  var link = e.target.closest('a[data-settings-go]');
  if (!link || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  settingsOpen(link.dataset.settingsGo);
});

/* ---------- Settings: Apple Contacts ----------
 *
 * Each person's own iCloud address book, from GET /api/settings/apple. There
 * is no organisation half: iCloud needs no app registered anywhere.
 *
 * The app-specific password goes one way, like Google's client secret. It is
 * typed, posted once to be checked against iCloud, and wiped out of the box
 * whatever the answer; the server keeps it only if iCloud accepted it, and
 * never sends it back. What comes back is the Apple ID, how many contacts
 * there are, and when the last sync finished and what it changed.
 *
 * A sync runs in the background on the server, straight after a password is
 * accepted and whenever Sync now is pressed. While one is running the card
 * asks again every second and a half, and says what it did when it ends.
 */

function appleLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/apple', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (r.status === 503) return r.json().then(function (out) { return { off: out.error }; });
      if (!r.ok) throw new Error('apple ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      APPLE.data = data;
      appleDraw();
    })
    .catch(function () {
      $('appleTrouble').textContent = 'Apple Contacts could not be read from the server. Try again in a moment.';
      $('appleTrouble').hidden = false;
    });
}

function appleChanged(n) {
  n = n || 0;
  return n === 1 ? '1 card changed' : n + ' cards changed';
}

function appleDraw() {
  var d = APPLE.data;
  if (!d) return;
  clearTimeout(APPLE.timer);
  if (d.off) {
    $('appleNotConnected').textContent = d.off;
    $('appleSetup').hidden = true;
    return;
  }
  var c = d.connection || {};
  var connected = !!c.connected;
  var revoked = !!c.needs_new_password;
  $('appleNotConnected').hidden = connected;
  $('appleState').hidden = !connected;
  $('appleActions').hidden = !connected;
  if (connected) {
    $('appleAccount').textContent = c.apple_id || '';
    $('appleWhen').textContent = whenWords(c.connected_at);
    $('appleCount').textContent = c.last_sync_at ? String(c.contacts)
      : (d.syncing ? 'counting…' : '-');
    $('appleSynced').textContent = d.syncing ? 'Syncing now…'
      : (c.last_sync_at ? whenWords(c.last_sync_at) + ', ' + appleChanged(c.last_sync_changed)
                        : 'Not yet');
  }
  // Two kinds of trouble, told apart: iCloud refusing the password, which
  // only a new one fixes, and a sync that could not finish this time, which
  // the next one may well.
  var trouble = '';
  // Not revoked: sealed under a key this server does not have, so iCloud
  // was never asked and must not be blamed.
  var unreadable = 'Rouh cannot open the stored app-specific password with this server\'s '
    + 'encryption key, so it has to be entered again below.';
  if (connected && revoked && c.unreadable) {
    trouble = unreadable;
  } else if (connected && revoked) {
    trouble = 'iCloud stopped accepting the app-specific password'
      + (c.last_attempt_at ? ' on ' + whenWords(c.last_attempt_at) : '') + '. It was probably '
      + 'revoked at account.apple.com, or the Apple ID\'s own password was changed, which '
      + 'revokes every app-specific password. Make a new one there and enter it below. '
      + 'Until then Rouh can still look people up in its copy, but not change them.';
  } else if (connected && c.last_error && c.last_attempt_at >= c.last_sync_at) {
    trouble = 'The last sync did not finish: ' + c.last_error;
  }
  $('appleTrouble').textContent = trouble;
  $('appleTrouble').hidden = !trouble;
  $('appleSync').disabled = !!d.syncing || revoked;
  $('appleSync').textContent = d.syncing ? 'Syncing…' : 'Sync now';
  $('appleReplace').hidden = revoked;

  var form = !connected || revoked || APPLE.editing;
  $('appleSetup').hidden = !form;
  $('appleCancel').hidden = !(connected && !revoked);
  $('appleConnect').disabled = false;
  $('appleConnect').textContent = connected ? 'Check and save' : 'Connect';
  if (!$('appleId').value) $('appleId').value = (c.apple_id || d.suggested_apple_id || '');

  if (d.syncing && settingsViewing()) {
    APPLE.timer = setTimeout(appleLoad, 1500);
  } else if (APPLE.tell) {
    APPLE.tell = false;
    if (revoked && c.unreadable) {
      settingsSay(unreadable, 'bad');
    } else if (revoked) {
      settingsSay('iCloud did not accept the app-specific password this time. Enter a new one below.', 'bad');
    } else if (c.last_error && c.last_attempt_at >= c.last_sync_at) {
      settingsSay('The sync from iCloud did not finish: ' + c.last_error, 'bad');
    } else if (c.last_sync_at) {
      settingsSay('Synced from iCloud: ' + c.contacts + ' contacts, ' + appleChanged(c.last_sync_changed) + '.', 'good');
    }
  }
}

$('appleForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var said = $('appleSaid');
  said.hidden = true;
  var body = JSON.stringify({
    apple_id: $('appleId').value.trim(),
    app_password: $('applePassword').value,
  });
  // Out of the box before the answer comes back, whatever it is.
  $('applePassword').value = '';
  $('appleConnect').disabled = true;
  $('appleConnect').textContent = 'Checking with iCloud…';
  fetch('/api/settings/apple', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: body,
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    if (answer.out && answer.out.connection) APPLE.data = answer.out;
    if (!answer.ok) {
      appleDraw();
      said.textContent = answer.out.error || 'That was not accepted.';
      said.hidden = false;
      return;
    }
    APPLE.editing = false;
    APPLE.tell = true;
    settingsSay(answer.out.said || 'iCloud accepted it.', 'good');
    appleDraw();
  }).catch(function () {
    $('appleConnect').disabled = false;
    $('appleConnect').textContent = 'Connect';
    said.textContent = 'That could not be checked. Try again in a moment.';
    said.hidden = false;
  });
});

$('appleReplace').addEventListener('click', function () {
  APPLE.editing = true;
  $('appleSaid').hidden = true;
  appleDraw();
  $('applePassword').focus();
});

$('appleCancel').addEventListener('click', function () {
  APPLE.editing = false;
  $('applePassword').value = '';
  $('appleSaid').hidden = true;
  appleDraw();
});

$('appleSync').addEventListener('click', function () {
  $('appleSync').disabled = true;
  fetch('/api/settings/apple/sync', { method: 'POST', credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (out) { return { ok: r.ok, out: out }; });
    })
    .then(function (answer) {
      if (answer.out && answer.out.connection) APPLE.data = answer.out;
      if (!answer.ok) {
        settingsSay(answer.out.error || 'The sync could not be started.', 'bad');
      } else {
        APPLE.tell = true;
        settingsSay('Syncing with iCloud…', null);
      }
      appleDraw();
    })
    .catch(function () {
      $('appleSync').disabled = false;
      settingsSay('The sync could not be started. Try again in a moment.', 'bad');
    });
});

$('appleDisconnect').addEventListener('click', function () {
  $('appleDisconnect').disabled = true;
  fetch('/api/settings/apple/disconnect', { method: 'POST', credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (out) {
      $('appleDisconnect').disabled = false;
      APPLE.editing = false;
      if (out && out.connection) APPLE.data = out;
      settingsSay('Apple Contacts are disconnected. The password and Rouh\'s copy of your contacts are gone; nothing in iCloud was touched.', null);
      appleDraw();
    })
    .catch(function () {
      $('appleDisconnect').disabled = false;
      settingsSay('Apple Contacts could not be disconnected. Try again in a moment.', 'bad');
    });
});

/* ---------- Settings: Telegram account ----------
 *
 * The person's own Telegram account, which opens a group for each fork made
 * on Telegram (`rouh/telegram_account.py`). A login is three forms at most,
 * one at a time, and the server says which it is waiting for: the app and
 * the phone number, the code Telegram sends, and the two-step verification
 * password. The API hash, the code and the password are wiped out of their
 * boxes as they are sent, whatever the answer; nothing secret comes back.
 */

function tgLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/telegram-account', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (r.status === 503) return r.json().then(function (out) { return { off: out.error }; });
      if (!r.ok) throw new Error('telegram account ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      TGACC.data = data;
      tgDraw();
    })
    .catch(function () {
      $('tgTrouble').textContent = 'The Telegram account could not be read from the server. Try again in a moment.';
      $('tgTrouble').hidden = false;
    });
}

function tgDraw() {
  var d = TGACC.data;
  if (!d) return;
  if (d.off) {
    $('tgNotConnected').textContent = d.off;
    $('tgSetup').hidden = true;
    return;
  }
  var a = d.account || {};
  var connected = !!a.connected;
  $('tgNotConnected').hidden = connected;
  $('tgState').hidden = !connected;
  $('tgActions').hidden = !connected;
  if (connected) {
    $('tgName').textContent = a.name || 'Your account';
    $('tgPhone').textContent = a.phone_hint || '-';
    $('tgWhen').textContent = whenWords(a.connected_at);
  }
  var trouble = '';
  if (a.unreadable) {
    trouble = 'Rouh cannot open the stored Telegram session with this server\'s encryption key, so connect the account again below.';
  }
  $('tgTrouble').textContent = trouble;
  $('tgTrouble').hidden = !trouble;
  // Which form: none once connected, else the step the login waits for.
  var step = connected ? '' : (TGACC.again ? 'start' : (a.state === 'code' || a.state === 'password' ? a.state : 'start'));
  $('tgSetup').hidden = connected;
  $('tgStartForm').hidden = step !== 'start';
  $('tgCodeForm').hidden = step !== 'code';
  $('tgPasswordForm').hidden = step !== 'password';
  $('tgGuide').hidden = step !== 'start';
  $('tgSend').disabled = false;
  $('tgSend').textContent = 'Send code';
  $('tgConnect').disabled = false;
  $('tgConnect').textContent = 'Connect';
  $('tgPasswordGo').disabled = false;
  $('tgPasswordGo').textContent = 'Connect';
  if (step === 'start' && !$('tgApiId').value && a.api_id) $('tgApiId').value = String(a.api_id);
}

// One POST of the login, and what to do with its answer: the next form, or
// the words it came back with under the form it was sent from.
function tgPost(path, body, button, busy, saidId) {
  var said = $(saidId);
  said.hidden = true;
  button.disabled = true;
  button.textContent = busy;
  return fetch(path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(function (r) {
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    if (answer.out && answer.out.account) TGACC.data = answer.out;
    tgDraw();
    if (!answer.ok) {
      said.textContent = (answer.out && answer.out.error) || 'That was not accepted.';
      said.hidden = false;
      return false;
    }
    settingsSay(answer.out.said || '', (answer.out.account || {}).connected ? 'good' : null);
    return true;
  }).catch(function () {
    tgDraw();
    said.textContent = 'Telegram could not be asked. Try again in a moment.';
    said.hidden = false;
    return false;
  });
}

$('tgStartForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var body = {
    api_id: $('tgApiId').value.trim(),
    api_hash: $('tgApiHash').value.trim(),
    phone: $('tgPhoneNumber').value.trim(),
  };
  $('tgApiHash').value = '';
  TGACC.again = false;
  tgPost('/api/settings/telegram-account', body, $('tgSend'), 'Asking Telegram…', 'tgStartSaid')
    .then(function (ok) { if (ok) $('tgCode').focus(); });
});

$('tgCodeForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var body = { code: $('tgCode').value.trim() };
  $('tgCode').value = '';
  tgPost('/api/settings/telegram-account/code', body, $('tgConnect'), 'Checking with Telegram…', 'tgCodeSaid')
    .then(function (ok) {
      if (ok && !$('tgPasswordForm').hidden) $('tgPassword').focus();
    });
});

$('tgPasswordForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var body = { password: $('tgPassword').value };
  $('tgPassword').value = '';
  tgPost('/api/settings/telegram-account/password', body, $('tgPasswordGo'), 'Checking with Telegram…', 'tgPasswordSaid');
});

Array.prototype.forEach.call(document.querySelectorAll('.tg-again'), function (b) {
  b.addEventListener('click', function () {
    TGACC.again = true;
    $('tgCode').value = '';
    $('tgPassword').value = '';
    $('tgCodeSaid').hidden = true;
    $('tgPasswordSaid').hidden = true;
    tgDraw();
    $('tgApiHash').focus();
  });
});

$('tgDisconnect').addEventListener('click', function () {
  $('tgDisconnect').disabled = true;
  fetch('/api/settings/telegram-account/disconnect', { method: 'POST', credentials: 'same-origin' })
    .then(function (r) { return r.json(); })
    .then(function (out) {
      $('tgDisconnect').disabled = false;
      if (out && out.account) TGACC.data = out;
      TGACC.again = false;
      settingsSay('Your Telegram account is disconnected: Rouh\'s session was logged out and forgotten. Forks made from now on live in the private chat with the bot.', null);
      tgDraw();
    })
    .catch(function () {
      $('tgDisconnect').disabled = false;
      settingsSay('The Telegram account could not be disconnected. Try again in a moment.', 'bad');
    });
});

/* ---------- Settings: New mail ----------
 *
 * New mail in the person's Gmail inbox, read the moment Google says it
 * arrived and handed to Rouh itself, which tells them about every message
 * on Telegram (`rouh/mail_alerts.py`). Everything drawn comes from
 * GET /api/settings/mail-alerts, and every button answers with the whole of
 * it again, which is what is drawn: never what the page guessed a press did.
 *
 * Two levels, like the Google card. An administrator is sent the topic and
 * the push address, and sets them up once; nobody else is sent either. The
 * switch and the list of what came lately are each person's own. Each
 * message in that list opens the conversation Rouh handled it in.
 *
 * While alerts are on and Settings is open the card asks again every
 * fifteen seconds, so a message sent to the inbox shows up under Lately
 * without anything being pressed. That is how a person sees it working.
 */

function mailLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/settings/mail-alerts', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (r.status === 503) return r.json().then(function (out) { return { off: out.error }; });
      if (!r.ok) throw new Error('mail alerts ' + r.status);
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      MAIL.data = data;
      mailDraw();
    })
    .catch(function () {
      mailSay('The New mail card could not be read from the server. Try again in a moment.', 'bad');
    });
}

function mailSay(text, kind) {
  var box = $('mailSaid');
  box.className = 'settings-help' + (kind === 'bad' ? ' bad' : '');
  box.textContent = text || '';
  box.hidden = !text;
}

// Where the notes go, said the way the person thinks of it.
function mailPhone(tg) {
  if (!tg.configured) return 'Nowhere: Telegram is not set up on this server';
  if (tg.yours) return 'Telegram, on your phone';
  return 'Telegram, on ' + (tg.owner ? tg.owner + '\'s' : 'somebody else\'s') + ' phone';
}

function mailDraw() {
  var d = MAIL.data;
  if (!d) return;
  clearTimeout(MAIL.timer);
  if (d.off) {
    $('mailOrgPart').hidden = true;
    $('mailLatelyPart').hidden = true;
    $('mailTurnOn').disabled = true;
    $('mailWhyNot').textContent = d.off;
    $('mailWhyNot').hidden = false;
    return;
  }
  var setup = d.setup || {}, a = d.alerts || {}, tg = d.telegram || {};

  // (1) The organisation's push. An ordinary member is never sent it.
  var mayEdit = !!setup.may_edit;
  $('mailOrgPart').hidden = !mayEdit;
  if (mayEdit) {
    var done = !!setup.configured;
    var editing = MAIL.editingTopic || !done;
    $('mailNoTopic').hidden = done;
    $('mailOrgState').hidden = !done;
    if (done) {
      $('mailTopicShown').textContent = setup.topic || '';
      $('mailOrgLastPush').textContent = setup.last_push_at ? whenWords(setup.last_push_at) : 'None yet';
    }
    $('mailAccount').textContent = setup.account || $('mailAccount').textContent;
    $('mailAddress').textContent = setup.address || '';
    // The steps are what is wanted until they have been followed, and in
    // the way after, unless somebody asks to see them again.
    $('mailGuide').hidden = done && !editing && !MAIL.guide;
    $('mailTopicForm').hidden = !editing;
    $('mailCancelTopic').hidden = !done;
    $('mailTopicActions').hidden = editing || !done;
    $('mailShowGuide').textContent = MAIL.guide ? 'Hide the steps' : 'Show the steps';
    $('mailSaveTopic').disabled = false;
    if (!editing) $('mailTopicSaid').hidden = true;
  }

  // (2) This person's alerts.
  var on = !!a.on;
  $('mailOn').textContent = on ? 'On' : 'Off';
  $('mailMailbox').textContent = a.mailbox || 'No Google account connected';
  $('mailWatch').textContent = !on ? 'Not watching'
    : (a.watching ? 'Active until ' + whenWords(a.expires_at) : 'Not active');
  $('mailRenewed').textContent = on && a.renewed_at ? whenWords(a.renewed_at) : '-';
  $('mailLastPush').textContent = a.last_push_at ? whenWords(a.last_push_at) : (on ? 'None yet' : '-');
  $('mailPhone').textContent = mailPhone(tg);
  $('mailTrouble').textContent = a.trouble || '';
  $('mailTrouble').hidden = !a.trouble;
  $('mailWhyNot').textContent = a.why_not || '';
  $('mailWhyNot').hidden = on || !a.why_not;
  $('mailTurnOn').hidden = on;
  $('mailTurnOn').disabled = !!a.why_not;
  $('mailTurnOn').textContent = 'Turn on';
  $('mailTurnOff').hidden = !on;
  $('mailTurnOff').disabled = false;

  // (2b) What came lately, newest first, and what Rouh did about each. The
  // words are the server's (`mail_alerts.outcome_of`), so this list, the
  // log and what Rouh says about the mail cannot disagree.
  var list = $('mailLately');
  var lately = a.lately || [];
  list.textContent = '';
  lately.forEach(function (m) {
    var li = el('li');
    li.appendChild(el('span', 'ml-what',
      (m.from || 'Somebody') + ' - ' + (m.subject || '(no subject)')));
    var tone = m.outcome === 'sent' ? ' sent' : (m.outcome === 'failed' ? ' bad' : '');
    li.appendChild(el('span', 'ml-said' + tone, m.line || m.said || ''));
    if (m.error) li.appendChild(el('span', 'ml-error', m.error));
    var foot = el('span', 'ml-when', whenWords(m.at));
    if (m.chat_link) {
      foot.appendChild(document.createTextNode(' \u00b7 '));
      var open = el('a', 'ml-open', 'Open the conversation');
      open.href = m.chat_link;
      foot.appendChild(open);
    }
    li.appendChild(foot);
    list.appendChild(li);
  });
  // Shown whenever there is a card at all, empty or not: the link to the
  // decision log is in it, and an empty log still says why it is empty.
  $('mailLatelyPart').hidden = false;
  $('mailLately').hidden = !lately.length;
  $('mailLatelyNone').hidden = !!lately.length;

  if (on && settingsViewing()) MAIL.timer = setTimeout(mailLoad, 15000);
}

// One press, one POST, and the whole card back. `said` is where the answer
// is put: the line under the switch, or the one in the form that was used.
function mailPost(path, body, said) {
  return fetch('/api/settings/mail-alerts' + path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return null; }
    return r.json().then(function (out) { return { ok: r.ok, out: out }; });
  }).then(function (answer) {
    if (!answer) return null;
    if (answer.out && answer.out.alerts) MAIL.data = answer.out;
    return answer;
  });
}

$('mailTurnOn').addEventListener('click', function () {
  var button = $('mailTurnOn');
  button.disabled = true;
  button.textContent = 'Asking Gmail…';
  mailSay('', null);
  mailPost('/on').then(function (answer) {
    if (!answer) return;
    mailDraw();
    mailSay(answer.ok ? answer.out.said : (answer.out.error || 'Alerts could not be turned on.'),
            answer.ok ? null : 'bad');
  }).catch(function () {
    mailDraw();
    mailSay('Alerts could not be turned on. Try again in a moment.', 'bad');
  });
});

$('mailTurnOff').addEventListener('click', function () {
  $('mailTurnOff').disabled = true;
  mailSay('', null);
  mailPost('/off').then(function (answer) {
    if (!answer) return;
    mailDraw();
    mailSay(answer.ok ? answer.out.said : (answer.out.error || 'Alerts could not be turned off.'),
            answer.ok ? null : 'bad');
  }).catch(function () {
    mailDraw();
    mailSay('Alerts could not be turned off. Try again in a moment.', 'bad');
  });
});

$('mailTopicForm').addEventListener('submit', function (e) {
  e.preventDefault();
  var said = $('mailTopicSaid');
  said.hidden = true;
  $('mailSaveTopic').disabled = true;
  mailPost('/topic', { topic: $('mailTopic').value }).then(function (answer) {
    if (!answer) return;
    if (!answer.ok) {
      $('mailSaveTopic').disabled = false;
      said.textContent = answer.out.error || 'That was not saved.';
      said.hidden = false;
      return;
    }
    MAIL.editingTopic = false;
    MAIL.guide = false;
    $('mailTopic').value = '';
    mailDraw();
    mailSay(answer.out.said, null);
  }).catch(function () {
    $('mailSaveTopic').disabled = false;
    said.textContent = 'That was not saved. Try again in a moment.';
    said.hidden = false;
  });
});

$('mailChangeTopic').addEventListener('click', function () {
  MAIL.editingTopic = true;
  var setup = (MAIL.data && MAIL.data.setup) || {};
  $('mailTopic').value = setup.topic || '';
  mailDraw();
  $('mailTopic').focus();
});

$('mailCancelTopic').addEventListener('click', function () {
  MAIL.editingTopic = false;
  $('mailTopic').value = '';
  $('mailTopicSaid').hidden = true;
  mailDraw();
});

$('mailShowGuide').addEventListener('click', function () {
  MAIL.guide = !MAIL.guide;
  mailDraw();
});

$('mailRemoveTopic').addEventListener('click', function () {
  $('mailRemoveTopic').disabled = true;
  mailPost('/topic', { remove: true }).then(function (answer) {
    $('mailRemoveTopic').disabled = false;
    if (!answer) return;
    mailDraw();
    mailSay(answer.ok ? answer.out.said : (answer.out.error || 'It was not removed.'),
            answer.ok ? null : 'bad');
  }).catch(function () {
    $('mailRemoveTopic').disabled = false;
    mailSay('It was not removed. Try again in a moment.', 'bad');
  });
});

// The two things an administrator pastes into the Cloud console.
function mailCopy(button, source) {
  button.addEventListener('click', function () {
    var text = source.textContent || '';
    var done = function () {
      button.textContent = 'Copied';
      setTimeout(function () { button.textContent = 'Copy'; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
    } else {
      done();
    }
  });
}
mailCopy($('mailCopyAccount'), $('mailAccount'));
mailCopy($('mailCopyAddress'), $('mailAddress'));

/* ---------- Rules ----------
 *
 * Every rule Rouh follows (`rouh/rules.py`, `rouh/web/rules.py`): for
 * everything, and for a person, task or project, at /rules (the person's
 * own words are in Vocabulary in Synapse since 30 October 2026, `synapse.js`), in groups in three sections (About Rouh, About the owner and
 * everything else), each rule equal and each saying when it is told. It was the Memory page until 5 October 2026, and
 * the layer, the button under his name and the ids are still Memory's.
 *
 * Petar, 29 October 2026: "way too many things for me to generally
 * understand. they need to be in groups", "every rule needs to have the same
 * UI", "every rule should be able to be turned of, like the agents", and "I
 * want to be able to see clearly what was added automatically vs what I
 * added manually". So every rule is a row of one design (`ruleRow`) in a
 * topic by what it is about (`rouh/rule_groups.py`), each row with its tags
 * of where it came from and who it is for, its date, its two switches and a
 * ⋯ holding Edit, History and Delete (Petar, 30 October 2026: "Fully remove
 * that lock").
 *
 * Since 30 October 2026 the page is the design Petar attached that day
 * (fr_886d9f55d466, "AI Assistant Rules Reorganization"): topics, one at a
 * time, and tags, any number, are two controls. Wide, the topics are a rail
 * beside the rules, every topic is listed under a head that stays at the top,
 * and picking one scrolls to it; a facet's button over the rules opens its
 * labels, each with what it means and its count, to tick any number of
 * (`memoryPopDraw`). Narrower the rail slides in from a Topics button. As
 * narrow as a phone, a topic button opens a picker over the whole page and a
 * topic picked is shown alone, and Tags opens a sheet of chips
 * (`memorySheetDraw`). Inspect - What context was included and What agents
 * start with - is at the foot of the rail and of the picker.
 *
 * Each topic has its address, /rules/<group>, and `?label=` holds the tags
 * picked, one or several (`?label=from-chat,agent`), so Back, a reload and a
 * link in a new tab all land where the person was. Until 29 October 2026 the
 * page was a panel with no address, held on the conversation it was opened
 * over.
 *
 * GET /api/rules is the whole page; every change answers with the whole page
 * again, and that is what is drawn. One thing is open at a time (a rule being
 * edited, a delete being asked about), and a page that arrives while one is
 * waits until it is put away.
 */

var MEMORY = { open: false, data: null, editing: '', confirming: '', busy: false, stale: false,
               // The topic picked, by its key ('' for none, 'told' and 'agents' for Inspect's two), and the
               // labels picked (`RULE_LABELS`, none for every rule): both in the address.
               group: '', /** @type {string[]} */ tags: [],
               // What is open over the rules: a facet's popover (its key), the phone's topic picker (and what is
               // typed in its box) and tags sheet (and the label held down in it), the rail slid in, the
               // phone's search.
               pop: '', picker: false, pickerFind: '', sheet: false, means: '', drawer: false, finding: false,
               // Rules whose conditions are open, by ref.
               /** @type {Object<string, boolean>} */
               conds: {},
               // The group whose (i) is open, by key ('' for none).
               info: '',
               // Groups opened or closed by hand since the page was opened, by key.
               /** @type {Object<string, boolean>} */
               opened: {},
               // Rows saying where they came from, by ref: 'from'.
               /** @type {Object<string, string>} */
               why: {},
               // A rule's history, by ref, while it is shown.
               /** @type {Object<string, any[]>} */
               history: {},
               // An old fact's choice as the person changes it: { home, text, for, term, meaning }.
               choices: {},
               // Who a new rule is for, picked before Add.
               newFor: [],
               // What is typed in a box, by the box ('rule', 'term', 'meaning', 'edit:<ref>'), so a redraw,
               // and above all a refusal, never takes the person's words away.
               /** @type {Object<string, string>} */
               drafts: {},
               // The server's refusal of an add or an edit, shown under the box it came from: { at, text }.
               /** @type {{at: string, text: string} | null} */
               refused: null };

// The replies a rule can be kept to (rouh/rules.py MODES); '' is every reply.
var RULE_MODES = [['', 'Every reply'], ['text', 'Written replies'], ['voice', 'Spoken replies']];
var RULE_HOMES = [['rule', 'A rule, every conversation'], ['rulefor', 'A rule for a person, task or project'],
                  ['vocabulary', 'Vocabulary in Synapse'], ['note', 'A note in Synapse'], ['drop', 'Drop it']];
// Where a rule came from (rouh/rules.py ORIGINS), as its flag says it and as the filter offers it.
var RULE_FROM = { manual: 'Manually added', chat: 'From chat', agents: 'From agents', gene: 'Gene update',
                  unknown: 'Origin not known' };
// Who a rule is for (rouh/rules.py SCOPES), as its tag says it.
var RULE_SCOPE = { creator: 'Creator only', instances: 'Rouh instances' };
// Every label a rule's row carries, under the four questions Petar asked each to answer (30 October 2026,
// fr_0034ebae3ca2): where it came from (one flag on every rule), who it is for (one tag on every rule), whether
// a rule for its creator alone could help others (Useful), and where it is told (its two switches). Each has its
// key (in the address, `?label=`), its words as the row shows them, what it means, which rows have it, and the
// icon and colour it has everywhere it is drawn - the filter, the tags sheet, the chips of the tags picked and
// the rows (the design Petar attached on 30 October 2026, fr_886d9f55d466, "AI Assistant Rules
// Reorganization"). Until that day the meanings were a card of their own on the landing page; now they are
// beside each label where it is picked.
var RULE_ICONS = {
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"/>',
  bubble: '<path d="M4 5h16v11H9l-5 4V5z"/>',
  agent: '<path d="M7 8h10v10H7zM12 4v4M9 13h.01M15 13h.01M4 13h3M17 13h3"/>',
  gene: '<path d="M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12M8 7h8M8 17h8"/>',
  unknown: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5h.01"/>',
  person: '<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c1-4 4-6 8-6s7 2 8 6"/>',
  globe: '<path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  megaphone: '<path d="M4 10v4h3l8 4V6L7 10H4zM18 9a4 4 0 0 1 0 6M8 14l1 5h2l-1-4"/>',
  bolt: '<path d="M13 3L5 14h6l-1 7 8-11h-6l1-7z"/>',
  off: '<path d="M12 3v8M6.3 6.8a8 8 0 1 0 11.4 0"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  down: '<path d="M7 10l5 5 5-5"/>',
  dots: '<circle cx="5.5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18.5" cy="12" r="1.3" fill="currentColor"/>'
};
/** @type {Array<{key: string, kind: string, name: string, icon: string, color: string, dashed?: boolean, means: string, has: (r: any) => boolean}>} */
var RULE_LABELS = [
  { key: 'manual', kind: 'from', name: RULE_FROM.manual, icon: 'pencil', color: '#5cc3f0',
    has: function (r) { return r.from === 'manual'; },
    means: 'You added it yourself, on this page or in Synapse\'s lab.' },
  { key: 'from-chat', kind: 'from', name: RULE_FROM.chat, icon: 'bubble', color: '#3ec9b0',
    has: function (r) { return r.from === 'chat'; },
    means: 'It came out of a conversation: you asked Rouh to keep it, or Rouh decided it should.' },
  { key: 'from-agents', kind: 'from', name: RULE_FROM.agents, icon: 'agent', color: '#e0b050',
    has: function (r) { return r.from === 'agents'; },
    means: 'Work done by Rouh\'s agents led to it: a job\'s report, a scheduled turn, or Synapse reading a note.' },
  { key: 'gene', kind: 'from', name: RULE_FROM.gene, icon: 'gene', color: '#a78bfa',
    has: function (r) { return r.from === 'gene'; },
    means: 'A gene or mutation from the pool added or changed it, such as the defaults every Rouh starts with.' },
  { key: 'unknown', kind: 'from', name: RULE_FROM.unknown, icon: 'unknown', color: '#8a90a0', dashed: true,
    has: function (r) { return !RULE_FROM[r.from] || r.from === 'unknown'; },
    means: 'Nothing kept says where it came from, so it is not guessed.' },
  { key: 'creator', kind: 'scope', name: RULE_SCOPE.creator, icon: 'person', color: '#c3c7d1',
    has: function (r) { return r.scope !== 'instances'; },
    means: 'For you, who made it, alone. It is never published.' },
  { key: 'instances', kind: 'scope', name: RULE_SCOPE.instances, icon: 'globe', color: '#4ade80',
    has: function (r) { return r.scope === 'instances'; },
    means: 'In the defaults every Rouh installed from now on starts with.' },
  // Its two switches (fr_61e683ffbada), kept with /agent-instructions opening ?label=agent.
  { key: 'chat', kind: 'switch', name: 'Chat', icon: 'megaphone', color: '#5cc3f0',
    has: function (r) { return !!r.chat; },
    means: 'Its Chat switch is on: your chats with Rouh are told it.' },
  { key: 'agent', kind: 'switch', name: 'Agent', icon: 'bolt', color: '#f472b6',
    has: function (r) { return !!r.agent; },
    means: 'Its Agent switch is on: every agent Rouh starts (a job, a run, a worker) is told it.' },
  { key: 'off', kind: 'switch', name: 'Off', icon: 'off', color: '#8a90a0', dashed: true,
    has: function (r) { return !r.on; },
    means: 'Both its switches are off: kept, greyed, and told to nothing until one is turned on.' },
  { key: 'useful', kind: 'useful', name: 'Useful', icon: 'bulb', color: '#a3e635',
    has: function (r) { return !!r.useful; },
    means: 'For you alone now, and could help others: Make standard turns it into a rule for every Rouh.' }
];
// The four facets the labels are in, in the order the filter bar and the tags sheet list them: its key, its
// name on the filter bar's button, and its question as the popover and the sheet head it. Any number of labels
// can be picked: any of one facet's, and every facet picked (`memoryTagged`).
var RULE_FACETS = [
  { key: 'from', name: 'Origin', title: 'Where it came from' },
  { key: 'scope', name: 'Audience', title: 'Who it is for' },
  { key: 'switch', name: 'Told in', title: 'Where it is told' },
  { key: 'useful', name: 'Could help others', title: 'Could it help others' }
];
// The three sections' colours (rouh/rule_groups.py SECTIONS), in the rail, the topic picker and each topic's head.
var RULE_TONES = { rouh: '#a78bfa', owner: '#f08a4b', other: '#c3c7d1' };
/** @param {string} key */
function ruleLabel(key) { return RULE_LABELS.filter(function (l) { return l.key === key; })[0] || null; }

/* The labels named in an address or a call ('from-chat,agent', or a list), each once, in the page's order. */
/** @param {string | string[]} [from] */
function memoryTagsOf(from) {
  var want = Array.isArray(from) ? from : String(from || '').split(',');
  return RULE_LABELS.filter(function (l) { return want.indexOf(l.key) >= 0; }).map(function (l) { return l.key; });
}

function memoryViewing() { return !!(MEMORY && MEMORY.open); }

/* The address of what the page shows: /rules, a topic's /rules/<key>, and ?label= for the tags picked. */
function memoryAddress() {
  return '/rules' + (MEMORY.group ? '/' + MEMORY.group : '') + (MEMORY.tags.length ? '?label=' + MEMORY.tags.join(',') : '');
}

/** @param {string} [group] @param {string | string[]} [from] */
function memoryOpen(group, from) {
  group = String(group || '');
  var was = MEMORY.open;
  if (group !== MEMORY.group) { MEMORY.opened = {}; MEMORY.editing = ''; MEMORY.confirming = ''; if (was) memorySay(''); }
  MEMORY.group = group;
  MEMORY.tags = memoryTagsOf(from);
  if (!was) {
    MEMORY.open = true;
    showLayer('memoryView');
    $('memoryBtn').setAttribute('aria-expanded', 'true');
    orbPlace(orbWanted());
    memorySay('');
    memoryLoad();
    if (narrow()) $('canvasPanel').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  memoryDraw();
  addrTouch();
  if (was) memoryShowGroup();
}

function memoryClose() {
  if (!memoryViewing()) return;
  MEMORY.open = false;
  MEMORY.editing = ''; MEMORY.confirming = ''; MEMORY.history = {}; MEMORY.why = {};
  MEMORY.pop = ''; MEMORY.sheet = false; MEMORY.picker = false; MEMORY.drawer = false; MEMORY.finding = false;
  memoryMenuShut(false);
  TOLD.told = null; TOLD.toldList = null;
  $('memorySearch').value = '';
  showLayer(null);
  $('memoryBtn').setAttribute('aria-expanded', 'false');
  orbPlace(orbWanted());
  addrBack();
}

function memorySay(text, kind) {
  var box = $('memorySay');
  box.className = 'settings-say' + (kind ? ' ' + kind : '');
  box.textContent = text || '';
  box.hidden = !text;
}

function memoryLoad() {
  if (typeof fetch !== 'function') return Promise.resolve();
  return fetch('/api/rules', { credentials: 'same-origin' })
    .then(function (r) {
      if (r.status === 401) { location.href = '/login'; return null; }
      if (!r.ok) throw new Error('rules ' + r.status);
      return r.json();
    })
    .then(function (data) { if (data) memoryTake(data); })
    .catch(function () { memorySay('The rules could not be read from the server. Try again in a moment.', 'bad'); });
}

function memoryTake(data) {
  if (!data || !data.rows) return;
  var first = !MEMORY.data;
  MEMORY.data = data;
  memoryDraw();
  // The tab is called after the group, which is only known by name once the groups have come.
  if (first) addrTouch();
  // The first time the rules arrive, the page goes back to where it was scrolled to before a
  // reload, or else to the group picked.
  if (first && !memoryScrollBack()) memoryShowGroup();
}

// Rouh kept or forgot something while the page is up.
/** @param {import('./protocol').FromServer<'tool_end'>} m */
function memoryHeard(m) {
  if (!memoryViewing() || !m || m.ok === false) return;
  if (m.name !== 'remember' && m.name !== 'forget') return;
  if (MEMORY.editing || MEMORY.confirming || MEMORY.busy) { MEMORY.stale = true; return; }
  memoryLoad();
}

function memoryDone() {
  MEMORY.editing = ''; MEMORY.confirming = ''; MEMORY.refused = null;
  if (MEMORY.stale) { MEMORY.stale = false; memoryLoad(); } else { memoryDraw(); }
}

function memoryPost(path, body) {
  return fetch(path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return { ok: false, out: {} }; }
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
                         function () { return { ok: false, out: {} }; });
  });
}

// Every change: sent, then the page as the server now holds it, and a sentence. `at` names the box it
// was typed in, and its drafts: a refusal is shown under that box with the words still in it, and the
// drafts go once it is kept.
/** @param {{at: string, drafts: string[]}} [at] */
function memoryChange(path, body, said, at) {
  if (MEMORY.busy) return Promise.resolve(false);
  MEMORY.busy = true;
  return memoryPost(path, body).then(function (answer) {
    MEMORY.busy = false;
    if (answer.out && answer.out.rows) MEMORY.data = answer.out;
    if (!answer.ok) {
      var why = (answer.out && answer.out.error) || 'That did not work. Try again in a moment.';
      if (at) { MEMORY.refused = { at: at.at, text: why }; memorySay(''); } else { memorySay(why, 'bad'); }
      memoryDraw();
      return false;
    }
    if (at) at.drafts.forEach(function (k) { delete MEMORY.drafts[k]; });
    memorySay(said, 'good');
    memoryDone();
    return true;
  }).catch(function () {
    MEMORY.busy = false;
    memorySay('The server could not be reached. Nothing was changed.', 'bad');
    return false;
  });
}

// A box that keeps what is typed in it across redraws (MEMORY.drafts).
/** @param {HTMLInputElement | HTMLTextAreaElement} box */
function memoryDraft(box, key, start) {
  box.value = Object.prototype.hasOwnProperty.call(MEMORY.drafts, key) ? MEMORY.drafts[key] : (start || '');
  box.addEventListener('input', function () { MEMORY.drafts[key] = box.value; });
}

// The server's refusal of what was typed in the box `at`, under that box; null when there is none.
function memoryRefusal(at) {
  if (!MEMORY.refused || MEMORY.refused.at !== at) return null;
  var p = el('p', 'settings-say bad memory-refused', MEMORY.refused.text);
  p.setAttribute('role', 'alert');
  return p;
}

function memoryDay(unixSeconds) {
  if (!unixSeconds) return '';
  var d = new Date(unixSeconds * 1000), now = new Date();
  /** @type {Intl.DateTimeFormatOptions} */
  var opts = { day: 'numeric', month: 'long' };
  if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
  return d.toLocaleDateString(undefined, opts);
}

function memoryQuery() { return ($('memorySearch').value || '').trim().toLowerCase(); }

function memoryHit(text) {
  var q = memoryQuery();
  return !q || String(text || '').toLowerCase().indexOf(q) >= 0;
}

function ctl(words, cls, onClick) {
  var b = el('button', 'ctl small' + (cls ? ' ' + cls : ''), words);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

function memoryCard(id, title, help) {
  var card = el('section', 'setting-card memory-card');
  card.setAttribute('aria-labelledby', id);
  var h = el('h4', null, title);
  h.id = id;
  card.appendChild(h);
  if (help) card.appendChild(el('p', 'settings-help', help));
  return card;
}

/* Whether a rule has the tags picked: any of one facet's, and every facet with one picked. So From chat and
   From agents is either of them, and From chat and Chat is both. */
function memoryTagged(r) {
  return RULE_FACETS.every(function (f) {
    var on = RULE_LABELS.filter(function (l) { return l.kind === f.key && MEMORY.tags.indexOf(l.key) >= 0; });
    return !on.length || on.some(function (l) { return l.has(r); });
  });
}

/* Which rows the page shows now: those with the tags picked that the search finds, and the one being edited. */
function memoryShown(rows) {
  return rows.filter(function (r) {
    if (r.ref === MEMORY.editing) return true;
    return memoryTagged(r) && memoryHit(r.title + ' ' + r.text + ' ' + ' ' +
      (r['for'] || []).map(function (f) { return f.name; }).join(' '));
  });
}

function memoryFiltering() { return MEMORY.tags.length > 0 || !!memoryQuery(); }

function memoryAside() { return MEMORY.group === 'told' || MEMORY.group === 'agents'; }

/* Whether the page is drawn as on a phone (the design's 2a): its row of a topic and Tags is on the screen, which
   the stylesheet decides from how wide the Rules page is. There, a topic picked is shown alone; wider, every
   topic is listed and picking one scrolls to it (1a). */
function memoryNarrow() {
  var c = $('rulesControls');
  return !!c && getComputedStyle(c).display !== 'none';
}

/* The rows a count is out of: the topic picked when it is shown alone, else every rule. */
function memoryScope(rows) {
  if (!memoryNarrow() || !MEMORY.group || memoryAside()) return rows;
  return rows.filter(function (r) { return r.group === MEMORY.group; });
}

/* Which control has the keyboard's focus, so a redraw gives it back: a row's control by its rule and its
   name, a group's head, or a link in the rail. */
function memoryFocusKey() {
  var a = document.activeElement;
  var view = $('memoryView');
  if (!a || !view || !view.contains(a) || a === $('memorySearch')) return null;
  var row = a.closest('li[data-ref]');
  var head = a.closest('.rules-group-head');
  var link = a.closest('.rules-nav-row');
  var keyed = a.closest('[data-focus]');
  if (row) return { ref: row.getAttribute('data-ref'), side: a.getAttribute('data-side') || '', words: a.textContent };
  if (head) return { head: head.getAttribute('aria-controls') };
  if (link) return { href: link.getAttribute('href') };
  if (keyed) return { focus: keyed.getAttribute('data-focus') };
  return null;
}

/** @param {any} key */
function memoryFocusBack(key) {
  if (!key) return;
  var view = $('memoryView'), got = null;
  if (key.ref) {
    var row = view.querySelector('li[data-ref="' + CSS.escape(key.ref) + '"]');
    if (!row) return;
    got = [].slice.call(row.querySelectorAll('button, summary')).filter(function (b) {
      return key.side ? b.getAttribute('data-side') === key.side : b.textContent === key.words;
    })[0] || row.querySelector('[role="switch"]');
  } else if (key.head) {
    got = view.querySelector('.rules-group-head[aria-controls="' + key.head + '"]');
  } else if (key.href) {
    got = [].slice.call(view.querySelectorAll('.rules-nav-row')).filter(function (x) { return x.getAttribute('href') === key.href; })[0];
  } else if (key.focus) {
    got = view.querySelector('[data-focus="' + CSS.escape(key.focus) + '"]');
  }
  if (got) got.focus({ preventScroll: true });
}

function memoryDraw() {
  var focus = memoryFocusKey();
  memoryDrawn();
  memoryFocusBack(focus);
}

function memoryDrawn() {
  var body = $('memoryBody'), scroller = $('rulesScroll');
  var d = MEMORY.data;
  if (!body) return;
  memoryMenuShut(false);
  var view = $('memoryView');
  view.classList.toggle('rules-drawer-open', !!MEMORY.drawer);
  $('rulesTopicsBtn').setAttribute('aria-expanded', MEMORY.drawer ? 'true' : 'false');
  view.classList.toggle('rules-finding', !!MEMORY.finding);
  view.classList.toggle('rules-aside', memoryAside());
  memoryNav();
  memoryBar();
  memoryOverlays();
  if (!d) return;
  // A redraw keeps the page where it was scrolled to (Petar's B1): an edit, a switch or a refusal never
  // moves what the person is looking at.
  var top = scroller ? scroller.scrollTop : 0;
  body.replaceChildren();
  if (memoryAside()) {
    body.appendChild(MEMORY.group === 'told' ? toldCard() : agentsCard());
    if (scroller) scroller.scrollTop = top;
    return;
  }
  if (d.old.length) body.appendChild(memoryOldCard(d.old));
  var adding = memoryAdding();
  if (adding) body.appendChild(adding);
  var alone = memoryNarrow() && !!MEMORY.group;
  var filtering = memoryFiltering();
  var shown = memoryShown(d.rows);
  var any = false;
  // Every topic in its section's order (rouh/rule_groups.py), each under a head that stays at the top while its
  // rules go by; on a phone a topic picked is shown alone. Filtered, a topic with none of the rules is left out.
  (d.sections || []).forEach(function (sec) {
    d.groups.filter(function (g) { return g.section === sec.key; }).forEach(function (g) {
      if (alone && g.key !== MEMORY.group) return;
      var rows = shown.filter(function (r) { return r.group === g.key; })
        .sort(function (a, b) { return a.order - b.order; });
      if (!rows.length && filtering && !alone) return;
      any = true;
      body.appendChild(memoryTopic(sec, g, rows));
    });
  });
  if (!any) body.appendChild(el('p', 'settings-note rules-none', 'No rule matches.'));
  if (scroller) scroller.scrollTop = top;
  memorySpy();
}

/* A label as a tag: its icon and its words in its colour, as every place draws it. */
/** @param {any} l @param {string} [tag] */
function ruleTag(l, tag) {
  var t = el(tag || 'span', 'rule-tag' + (l.dashed ? ' dashed' : ''));
  t.style.setProperty('--tag', l.color);
  t.appendChild(ruleIcon(RULE_ICONS[l.icon]));
  t.appendChild(el('span', 'rule-tag-name', l.name));
  return t;
}

/* A round button of the page's own, with an icon: the ⋯ on a rule, and the phone's search and add. */
function ruleRound(icon, label, cls, onClick) {
  var b = el('button', 'rules-round' + (cls ? ' ' + cls : ''));
  b.type = 'button';
  b.setAttribute('aria-label', label);
  b.title = label;
  b.appendChild(ruleIcon(RULE_ICONS[icon]));
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

/** @param {string[]} tags */
function memoryPick(tags) {
  memoryOpen(MEMORY.group, tags);
}

/** @param {string} key */
function memoryToggleTag(key) {
  var on = MEMORY.tags.indexOf(key) >= 0;
  memoryPick(on ? MEMORY.tags.filter(function (k) { return k !== key; }) : MEMORY.tags.concat([key]));
}

/* The rail: every rule, the topics of each section under its name in its colour, each with how many rules it
   shows now and each a link to its own address; and at its foot, Inspect: what a request was sent and what an
   agent starts with. Wide, it stands beside the rules; narrower, it slides in from the Topics button. */
function memoryNav() {
  var nav = $('rulesNav');
  if (!nav) return;
  var d = MEMORY.data;
  nav.replaceChildren();
  var shown = d ? memoryShown(d.rows) : [];
  var link = function (key, href, words, count, go) {
    var li = el('li');
    var a = el('a', 'rules-nav-row');
    a.href = href;
    a.setAttribute('data-key', key);
    a.appendChild(el('span', 'rules-nav-name', words));
    if (count !== null) a.appendChild(el('span', 'rules-nav-count', String(count)));
    a.addEventListener('click', function (e) {
      // A new tab or window takes the address as it is.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault();
      MEMORY.drawer = false;
      go();
    });
    li.appendChild(a);
    return li;
  };
  var tags = MEMORY.tags.length ? '?label=' + MEMORY.tags.join(',') : '';
  var all = el('ul', 'rules-nav-list');
  all.appendChild(link('all', '/rules' + tags, 'All rules', d ? shown.length : null, function () {
    memoryOpen('', MEMORY.tags);
    var s = $('rulesScroll');
    if (s) s.scrollTop = 0;
    memorySpy();
  }));
  nav.appendChild(all);
  ((d && d.sections) || []).forEach(function (sec) {
    var list = el('ul', 'rules-nav-list rules-nav-section');
    list.style.setProperty('--tone', RULE_TONES[sec.key] || RULE_TONES.other);
    list.setAttribute('aria-label', sec.name);
    list.appendChild(el('li', 'rules-nav-head', sec.name));
    ((d && d.groups) || []).filter(function (g) { return g.section === sec.key; }).forEach(function (g) {
      var n = shown.filter(function (r) { return r.group === g.key; }).length;
      list.appendChild(link(g.key, '/rules/' + g.key + tags, g.name, n, function () {
        memoryOpen(g.key, MEMORY.tags);
      }));
    });
    nav.appendChild(list);
  });
  var told = el('ul', 'rules-nav-list rules-nav-inspect');
  told.setAttribute('aria-label', 'Inspect');
  told.appendChild(el('li', 'rules-nav-head', 'Inspect'));
  told.appendChild(link('told', '/rules/told', 'What context was included', null, memoryToldOpen));
  told.appendChild(link('agents', '/rules/agents', 'What agents start with', null, memoryAgentsOpen));
  nav.appendChild(told);
  memorySpy();
}

function memoryToldOpen() {
  // Read afresh each time it is pressed, so a message sent since is in the list.
  TOLD.told = null; TOLD.toldList = null;
  memoryOpen('told', '');
}

function memoryAgentsOpen() {
  AGENTS.text = null; AGENTS.runs = null; AGENTS.open = {};
  memoryOpen('agents', '');
}

/* Which topic the rail lights: the one at the top of the rules as they are scrolled, Every rule at the very top,
   and Inspect's own while it is open. Changed in place, never by drawing the rail again. */
function memorySpy() {
  var nav = $('rulesNav'), s = $('rulesScroll');
  if (!nav || !s) return;
  var at = '';
  if (memoryAside()) {
    at = MEMORY.group;
  } else if (memoryNarrow()) {
    at = MEMORY.group || 'all';
  } else if (s.scrollTop > 4 || MEMORY.group) {
    var line = s.getBoundingClientRect().top + 24;
    [].slice.call(s.querySelectorAll('.rules-topic')).forEach(function (t) {
      if (t.getBoundingClientRect().top <= line) at = t.getAttribute('data-key') || '';
    });
    if (!at) at = s.scrollTop > 4 ? '' : MEMORY.group;
  }
  if (!at) at = 'all';
  [].slice.call(nav.querySelectorAll('.rules-nav-row')).forEach(function (a) {
    var on = a.getAttribute('data-key') === at;
    a.classList.toggle('on', on);
    if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
  });
}

/* What is over the rules: on a phone the topic picked and the Tags button, with a chip for every tag picked
   that takes it off; wider, a button for each facet and how many rules are shown. */
function memoryBar() {
  var d = MEMORY.data;
  var rows = d ? d.rows : [];
  var scope = memoryScope(rows), shownN = memoryScope(memoryShown(rows)).length;
  var said = memoryFiltering() ? shownN + ' of ' + scope.length : String(scope.length);
  $('rulesAddBtn').hidden = memoryAside();
  $('rulesVocab').hidden = memoryAside();
  $('memorySearch').hidden = memoryAside();
  $('rulesFindBtn').hidden = memoryAside();
  $('rulesAddRound').hidden = memoryAside();
  $('rulesFindBtn').setAttribute('aria-expanded', MEMORY.finding ? 'true' : 'false');

  // The phone's row: the topic, as a button that opens the picker, and Tags.
  var ctl = $('rulesControls');
  ctl.replaceChildren();
  var row = el('div', 'rules-controls-row');
  var topic = el('button', 'rules-topic-btn');
  topic.type = 'button';
  topic.setAttribute('data-focus', 'topic');
  topic.setAttribute('aria-haspopup', 'dialog');
  topic.setAttribute('aria-expanded', MEMORY.picker ? 'true' : 'false');
  var g = d ? d.groups.filter(function (x) { return x.key === MEMORY.group; })[0] : null;
  var sec = g && d ? (d.sections || []).filter(function (x) { return x.key === g.section; })[0] : null;
  var aside = memoryAside();
  var tone = aside ? '#8a90a0' : sec ? RULE_TONES[sec.key] || RULE_TONES.other : '';
  if (tone) topic.style.setProperty('--tone', tone);
  topic.appendChild(el('span', 'rules-topic-dot' + (tone ? '' : ' none')));
  var words = el('span', 'rules-topic-words');
  if (sec || aside) words.appendChild(el('span', 'rules-topic-sec', aside ? 'Inspect' : sec.name));
  words.appendChild(el('span', 'rules-topic-name', aside ? (MEMORY.group === 'told' ? 'What context was included'
    : 'What agents start with') : g ? g.name : 'All topics'));
  topic.appendChild(words);
  if (!aside && d) topic.appendChild(el('span', 'rules-nav-count', String(shownN)));
  topic.appendChild(ruleIcon(RULE_ICONS.down));
  topic.setAttribute('aria-label', 'Topic: ' + (g ? g.name : aside ? 'Inspect' : 'All topics') + '. Pick another');
  topic.addEventListener('click', function () { MEMORY.picker = true; MEMORY.pickerFind = ''; memoryDraw(); });
  row.appendChild(topic);
  if (!aside) {
    var tags = el('button', 'rules-tags-btn' + (MEMORY.tags.length ? ' on' : ''), 'Tags');
    tags.type = 'button';
    tags.setAttribute('data-focus', 'tags');
    tags.setAttribute('aria-haspopup', 'dialog');
    tags.setAttribute('aria-expanded', MEMORY.sheet ? 'true' : 'false');
    if (MEMORY.tags.length) tags.appendChild(el('span', 'rules-tags-badge', String(MEMORY.tags.length)));
    tags.setAttribute('aria-label', 'Tags' + (MEMORY.tags.length ? ', ' + MEMORY.tags.length + ' picked' : ''));
    tags.addEventListener('click', function () { MEMORY.sheet = true; MEMORY.means = ''; memoryDraw(); });
    row.appendChild(tags);
  }
  ctl.appendChild(row);
  if (MEMORY.tags.length && !aside) {
    var on = el('div', 'rules-active');
    MEMORY.tags.forEach(function (k) {
      var l = ruleLabel(k);
      if (!l) return;
      var chip = ruleTag(l, 'span');
      chip.classList.add('rules-chip-on');
      var x = ruleRound('x', 'Take off ' + l.name, 'rules-chip-x', function () { memoryToggleTag(k); });
      x.setAttribute('data-focus', 'off:' + k);
      chip.appendChild(x);
      on.appendChild(chip);
    });
    on.appendChild(el('span', 'rules-count', said));
    ctl.appendChild(on);
  }

  // Wider: a button for each facet, the count, and Clear.
  var bar = $('rulesFilters');
  bar.replaceChildren();
  if (aside) return;
  RULE_FACETS.forEach(function (f) {
    var picked = RULE_LABELS.filter(function (l) { return l.kind === f.key && MEMORY.tags.indexOf(l.key) >= 0; });
    var b = el('button', 'rules-facet-btn' + (picked.length ? ' on' : ''));
    b.type = 'button';
    b.setAttribute('data-facet', f.key);
    b.setAttribute('data-focus', 'facet:' + f.key);
    b.setAttribute('aria-haspopup', 'true');
    b.setAttribute('aria-expanded', MEMORY.pop === f.key ? 'true' : 'false');
    if (picked.length) b.style.setProperty('--tag', picked[0].color);
    b.appendChild(el('span', null, f.name + (picked.length ? ': ' + picked[0].name +
      (picked.length > 1 ? ' +' + (picked.length - 1) : '') : '')));
    b.appendChild(ruleIcon(RULE_ICONS.down));
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      MEMORY.pop = MEMORY.pop === f.key ? '' : f.key;
      memoryDraw();
    });
    bar.appendChild(b);
  });
  var tail = el('div', 'rules-filters-tail');
  tail.appendChild(el('span', 'rules-count', said + (scope.length === 1 && !memoryFiltering() ? ' rule' : ' rules')));
  if (memoryFiltering()) {
    var clear = el('button', 'rules-link', 'Clear');
    clear.type = 'button';
    clear.addEventListener('click', function () { $('memorySearch').value = ''; MEMORY.pop = ''; memoryPick([]); });
    tail.appendChild(clear);
  }
  bar.appendChild(tail);
}

/* How many rules have a label, out of those a count is out of. */
function memoryHas(l) {
  return memoryScope((MEMORY.data && MEMORY.data.rows) || []).filter(l.has).length;
}

/* What opens over the rules: a facet's popover, the phone's topic picker, and its tags sheet. */
function memoryOverlays() {
  memoryPopDraw();
  memoryPickerDraw();
  memorySheetDraw();
}

/* One facet's labels, each with a box to tick, what it means and how many rules have it; any number ticked. */
function memoryPopDraw() {
  var pop = $('rulesPop');
  var f = RULE_FACETS.filter(function (x) { return x.key === MEMORY.pop; })[0];
  var btn = f ? document.querySelector('#rulesFilters .rules-facet-btn[data-facet="' + f.key + '"]') : null;
  pop.replaceChildren();
  if (!f || !btn || memoryAside()) { pop.hidden = true; return; }
  pop.setAttribute('aria-label', f.title);
  pop.appendChild(el('div', 'rules-pop-head', f.title));
  RULE_LABELS.filter(function (l) { return l.kind === f.key; }).forEach(function (l) {
    var on = MEMORY.tags.indexOf(l.key) >= 0;
    var b = el('button', 'rules-pop-row' + (on ? ' on' : ''));
    b.type = 'button';
    b.setAttribute('role', 'menuitemcheckbox');
    b.setAttribute('aria-checked', on ? 'true' : 'false');
    b.setAttribute('data-focus', 'pop:' + l.key);
    b.style.setProperty('--tag', l.color);
    var box = el('span', 'rules-pop-box');
    if (on) box.appendChild(ruleIcon(RULE_ICONS.check));
    b.appendChild(box);
    var mid = el('span', 'rules-pop-mid');
    mid.appendChild(ruleTag(l));
    mid.appendChild(el('span', 'rules-pop-means', l.means));
    b.appendChild(mid);
    b.appendChild(el('span', 'rules-nav-count', String(memoryHas(l))));
    b.addEventListener('click', function (e) { e.stopPropagation(); memoryToggleTag(l.key); });
    pop.appendChild(b);
  });
  pop.hidden = false;
  var view = $('memoryView').getBoundingClientRect(), at = btn.getBoundingClientRect();
  var w = Math.min(420, view.width - 24);
  pop.style.width = w + 'px';
  pop.style.left = Math.max(12, Math.min(at.left - view.left, view.width - w - 12)) + 'px';
  pop.style.top = (at.bottom - view.top + 6) + 'px';
}

/* The phone's topic picker, over the whole page: every topic of each section, one picked at a time, a box that
   finds one by its name, and Inspect's two at the foot. Picking one goes back to the rules. */
function memoryPickerDraw() {
  var box = $('rulesPicker');
  var d = MEMORY.data;
  box.replaceChildren();
  if (!MEMORY.picker || !d) { box.hidden = true; return; }
  var head = el('div', 'rules-sheet-head');
  var back = ruleRound('back', 'Back to the rules', 'rules-back', function () { memoryPickerShut(); });
  back.setAttribute('data-focus', 'picker-back');
  head.appendChild(back);
  head.appendChild(el('h4', 'rules-sheet-title', 'Topics'));
  head.appendChild(ruleRound('x', 'Close the topics', 'rules-x', function () { memoryPickerShut(); }));
  box.appendChild(head);
  var find = el('input', 'memory-search rules-picker-find');
  find.type = 'search';
  find.placeholder = 'Find a topic';
  find.setAttribute('aria-label', 'Find a topic');
  find.value = MEMORY.pickerFind || '';
  box.appendChild(find);
  var list = el('div', 'rules-picker-list');
  var shown = memoryShown(d.rows);
  var pick = function (key, name, count, tone, go) {
    var on = key === (MEMORY.group || 'all');
    var b = el('button', 'rules-picker-row' + (on ? ' on' : ''));
    b.type = 'button';
    b.setAttribute('data-name', name.toLowerCase());
    if (tone) b.style.setProperty('--tone', tone);
    if (on) b.setAttribute('aria-current', 'true');
    b.appendChild(el('span', 'rules-nav-name', name));
    if (on) b.appendChild(ruleIcon(RULE_ICONS.check));
    if (count !== null) b.appendChild(el('span', 'rules-nav-count', String(count)));
    b.addEventListener('click', function () { MEMORY.picker = false; go(); var s = $('rulesScroll'); if (s) s.scrollTop = 0; });
    return b;
  };
  list.appendChild(pick('all', 'All topics', shown.length, '', function () { memoryOpen('', MEMORY.tags); }));
  (d.sections || []).forEach(function (sec) {
    var grp = el('div', 'rules-picker-group');
    var tone = RULE_TONES[sec.key] || RULE_TONES.other;
    grp.style.setProperty('--tone', tone);
    grp.appendChild(el('div', 'rules-picker-head', sec.name));
    d.groups.filter(function (g) { return g.section === sec.key; }).forEach(function (g) {
      grp.appendChild(pick(g.key, g.name, shown.filter(function (r) { return r.group === g.key; }).length, tone,
        function () { memoryOpen(g.key, MEMORY.tags); }));
    });
    list.appendChild(grp);
  });
  var ins = el('div', 'rules-picker-group');
  ins.style.setProperty('--tone', '#8a90a0');
  ins.appendChild(el('div', 'rules-picker-head', 'Inspect'));
  ins.appendChild(pick('told', 'What context was included', null, '#8a90a0', memoryToldOpen));
  ins.appendChild(pick('agents', 'What agents start with', null, '#8a90a0', memoryAgentsOpen));
  list.appendChild(ins);
  // And the person's own words, which are Vocabulary in Synapse, as beside Add a rule where the page is wider.
  var syn = el('div', 'rules-picker-group');
  syn.style.setProperty('--tone', '#8a90a0');
  syn.appendChild(el('div', 'rules-picker-head', 'Synapse'));
  syn.appendChild(pick('vocabulary', 'Vocabulary', null, '#8a90a0', function () { goToAddress('/synapse/vocabulary'); }));
  list.appendChild(syn);
  box.appendChild(list);
  // Found in place, so the box keeps its focus and what is typed.
  var filter = function () {
    var q = find.value.trim().toLowerCase();
    MEMORY.pickerFind = find.value;
    [].slice.call(list.querySelectorAll('.rules-picker-row')).forEach(function (r) {
      r.hidden = !!q && (r.getAttribute('data-name') || '').indexOf(q) < 0;
    });
    [].slice.call(list.querySelectorAll('.rules-picker-group')).forEach(function (grp) {
      grp.hidden = !grp.querySelector('.rules-picker-row:not([hidden])');
    });
  };
  find.addEventListener('input', filter);
  filter();
  box.hidden = false;
}

function memoryPickerShut() {
  MEMORY.picker = false;
  memoryDraw();
  var b = document.querySelector('#rulesControls .rules-topic-btn');
  if (b) /** @type {HTMLElement} */ (b).focus();
}

/* The phone's tags sheet: every label of each facet as a chip, any number on, and the count it comes to. A long
   press on a chip says what it means. */
function memorySheetDraw() {
  var wrap = $('rulesSheet');
  wrap.replaceChildren();
  if (!MEMORY.sheet || memoryAside()) { wrap.hidden = true; return; }
  var shade = el('div', 'rules-shade');
  shade.addEventListener('click', function () { memorySheetShut(); });
  wrap.appendChild(shade);
  var sheet = el('div', 'rules-sheet');
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-modal', 'true');
  sheet.setAttribute('aria-labelledby', 'rulesSheetTitle');
  sheet.appendChild(el('div', 'rules-grabber'));
  var head = el('div', 'rules-sheet-head');
  var title = el('h4', 'rules-sheet-title', 'Tags');
  title.id = 'rulesSheetTitle';
  head.appendChild(title);
  var clear = el('button', 'rules-link', 'Clear all');
  clear.type = 'button';
  clear.setAttribute('data-focus', 'sheet-clear');
  clear.disabled = !MEMORY.tags.length;
  clear.addEventListener('click', function () { memoryPick([]); });
  head.appendChild(clear);
  sheet.appendChild(head);
  var inner = el('div', 'rules-sheet-body');
  RULE_FACETS.forEach(function (f) {
    var grp = el('div', 'rules-sheet-group');
    grp.setAttribute('role', 'group');
    grp.setAttribute('aria-label', f.title);
    grp.appendChild(el('div', 'rules-picker-head', f.title));
    var chips = el('div', 'rules-sheet-chips');
    RULE_LABELS.filter(function (l) { return l.kind === f.key; }).forEach(function (l) {
      var on = MEMORY.tags.indexOf(l.key) >= 0;
      var b = ruleTag(l, 'button');
      b.classList.add('rules-sheet-chip');
      if (on) b.classList.add('on');
      /** @type {HTMLButtonElement} */ (b).type = 'button';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.setAttribute('data-focus', 'chip:' + l.key);
      b.title = l.means;
      b.appendChild(el('span', 'rules-sheet-n', String(memoryHas(l))));
      if (on) b.appendChild(ruleIcon(RULE_ICONS.check));
      var held = 0, long = false;
      b.addEventListener('pointerdown', function () {
        long = false;
        clearTimeout(held);
        held = setTimeout(function () { long = true; MEMORY.means = l.key; memoryMeans(); }, 500);
      });
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(function (ev) {
        b.addEventListener(ev, function () { clearTimeout(held); });
      });
      b.addEventListener('contextmenu', function (e) { e.preventDefault(); });
      b.addEventListener('click', function () {
        if (long) { long = false; return; }
        memoryToggleTag(l.key);
      });
      chips.appendChild(b);
    });
    grp.appendChild(chips);
    inner.appendChild(grp);
  });
  var means = el('p', 'rules-sheet-means');
  means.id = 'rulesSheetMeans';
  means.setAttribute('aria-live', 'polite');
  inner.appendChild(means);
  sheet.appendChild(inner);
  var foot = el('div', 'rules-sheet-foot');
  var n = memoryScope(memoryShown((MEMORY.data && MEMORY.data.rows) || [])).length;
  var show = el('button', 'rules-primary rules-show', 'Show ' + n + (n === 1 ? ' rule' : ' rules'));
  show.type = 'button';
  show.addEventListener('click', function () { memorySheetShut(); });
  foot.appendChild(show);
  sheet.appendChild(foot);
  wrap.appendChild(sheet);
  wrap.hidden = false;
  memoryMeans();
}

/* What the label held down means, or how to find out. */
function memoryMeans() {
  var p = $('rulesSheetMeans');
  if (!p) return;
  var l = ruleLabel(MEMORY.means || '');
  p.replaceChildren();
  if (!l) { p.textContent = 'Long-press a tag to see what it means.'; return; }
  p.appendChild(ruleTag(l));
  p.appendChild(el('span', null, ' ' + l.means));
}

function memorySheetShut() {
  MEMORY.sheet = false;
  memoryDraw();
  var b = document.querySelector('#rulesControls .rules-tags-btn');
  if (b) /** @type {HTMLElement} */ (b).focus();
}

/* One topic: a head that stays at the top while its rules go by - its section, its name, its count and its (i)
   - and its rules. */
function memoryTopic(sec, g, rows) {
  var box = el('section', 'rules-topic');
  box.id = 'rulesGroup-' + g.key;
  box.setAttribute('data-key', g.key);
  box.setAttribute('aria-labelledby', 'rulesTopic-' + g.key);
  box.style.setProperty('--tone', RULE_TONES[sec.key] || RULE_TONES.other);
  var head = el('div', 'rules-topic-head');
  head.appendChild(el('span', 'rules-topic-sec', sec.name));
  var h = el('h4', 'rules-topic-title', g.name);
  h.id = 'rulesTopic-' + g.key;
  head.appendChild(h);
  head.appendChild(el('span', 'rules-nav-count', String(rows.length)));
  // Its (i): when the rules in it are told to a model, one sentence from the server (`rules.included_said`).
  var info = /** @type {HTMLButtonElement} */ (el('button', 'tc-info rules-group-info', 'i'));
  info.type = 'button';
  info.setAttribute('data-group', g.key);
  info.setAttribute('aria-controls', 'rulesGroupInfo-' + g.key);
  info.setAttribute('aria-expanded', MEMORY.info === g.key ? 'true' : 'false');
  info.setAttribute('aria-label', 'When the rules in ' + g.name + ' are used');
  info.addEventListener('click', function () { memoryInfo(MEMORY.info === g.key ? '' : g.key); });
  head.appendChild(info);
  box.appendChild(head);
  var said = el('p', 'settings-help rules-group-said', g.included || '');
  said.id = 'rulesGroupInfo-' + g.key;
  said.hidden = MEMORY.info !== g.key;
  box.appendChild(said);
  var list = el('ul', 'memory-list rules-list');
  rows.forEach(function (r) { list.appendChild(ruleRow(r)); });
  if (!rows.length) list.appendChild(el('li', 'settings-note', memoryFiltering() ? 'Nothing here matches.' : 'Nothing here yet.'));
  box.appendChild(list);
  return box;
}

/* The one menu behind every rule's ⋯ - Edit, History, Delete - moved to whichever row opened it (`menu.js`
   draws it and walks it with the keys). */
var RULES_MENU = { ref: '', /** @type {HTMLElement | null} */ button: null };

function memoryMenuOpen(r, b) {
  var menu = $('rulesMenu');
  if (!menu) return;
  if (RULES_MENU.ref === r.ref && !menu.hidden) { memoryMenuShut(true); return; }
  memoryMenuShut(false);
  RULES_MENU.ref = r.ref;
  RULES_MENU.button = b;
  var hist = menu.querySelector('[data-act="history"]');
  if (hist) RouhMenu.label(/** @type {HTMLElement} */ (hist), MEMORY.history[r.ref] ? 'Hide history' : 'History');
  menu.setAttribute('aria-label', 'More for: ' + r.title);
  menu.hidden = false;
  b.setAttribute('aria-expanded', 'true');
  RouhMenu.place(menu, b, 'end');
  RouhMenu.first(menu);
}

/** @param {boolean} focus */
function memoryMenuShut(focus) {
  var menu = $('rulesMenu');
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  var b = RULES_MENU.button;
  RULES_MENU.ref = ''; RULES_MENU.button = null;
  if (b) { b.setAttribute('aria-expanded', 'false'); if (focus && b.isConnected) b.focus(); }
}

(function () {
  var menu = $('rulesMenu');
  if (!menu) return;
  RouhMenu.dress(menu);
  menu.addEventListener('click', function (e) {
    var item = /** @type {Element} */ (e.target).closest('[data-act]');
    if (!item) return;
    var ref = RULES_MENU.ref;
    var r = ((MEMORY.data && MEMORY.data.rows) || []).filter(function (x) { return x.ref === ref; })[0];
    memoryMenuShut(false);
    if (!r) return;
    var act = item.getAttribute('data-act');
    if (act === 'edit') {
      delete MEMORY.drafts['edit:' + r.ref];
      MEMORY.editing = r.ref; MEMORY.confirming = ''; MEMORY.refused = null; memoryDraw();
    } else if (act === 'history') {
      if (MEMORY.history[r.ref]) { delete MEMORY.history[r.ref]; memoryDraw(); } else ruleHistory(r.ref);
    } else if (act === 'delete') {
      MEMORY.confirming = r.ref; MEMORY.editing = ''; memoryDraw();
    }
  });
  menu.addEventListener('keydown', function (e) {
    if (RouhMenu.keys(menu, e)) return;
    if (e.key === 'Tab') memoryMenuShut(false);
  });
  document.addEventListener('click', function (e) {
    var t = /** @type {Element} */ (e.target);
    if (!menu.hidden && !menu.contains(t) && !(RULES_MENU.button && RULES_MENU.button.contains(t))) memoryMenuShut(false);
    // A facet's popover closes with a press anywhere but itself.
    var pop = $('rulesPop');
    if (MEMORY.pop && pop && !pop.contains(t) && !(t.closest && t.closest('.rules-facet-btn'))) {
      MEMORY.pop = '';
      memoryDraw();
    }
  });
  var s = $('rulesScroll');
  if (s) s.addEventListener('scroll', function () { memoryMenuShut(false); }, { passive: true });
})();

// Escape closes what is open over the rules, one thing a press, before it closes the page.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || !memoryViewing()) return;
  var menu = $('rulesMenu');
  var b = null;
  if (menu && !menu.hidden) { memoryMenuShut(true); }
  else if (MEMORY.pop) {
    var was = MEMORY.pop;
    MEMORY.pop = '';
    memoryDraw();
    b = document.querySelector('.rules-facet-btn[data-facet="' + was + '"]');
  }
  else if (MEMORY.sheet) { memorySheetShut(); }
  else if (MEMORY.picker) { memoryPickerShut(); }
  else if (MEMORY.drawer) { MEMORY.drawer = false; memoryDraw(); b = $('rulesTopicsBtn'); }
  else return;
  e.preventDefault();
  e.stopPropagation();
  if (b) /** @type {HTMLElement} */ (b).focus();
}, true);

// The page is drawn again when it crosses from a phone's shape to a wider one, since a topic is shown alone on
// one and among the rest on the other.
(function () {
  var view = $('memoryView');
  if (!view || typeof ResizeObserver !== 'function') return;
  var was = null;
  new ResizeObserver(function () {
    if (!memoryViewing()) return;
    var now = memoryNarrow();
    if (was !== null && now !== was) memoryDraw();
    was = now;
  }).observe(view);
})();

/* The section of the picked group, scrolled to the top of the page. */
function memoryShowGroup() {
  if (!MEMORY.group || MEMORY.group === 'told' || MEMORY.group === 'agents') return;
  var sec = document.getElementById('rulesGroup-' + MEMORY.group);
  var scroller = $('rulesScroll');
  if (!sec || !scroller) return;
  scroller.scrollTop += sec.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 4;
}

/* Where the page was scrolled to, kept for a reload of the same address (Petar's B1). */
function memoryScrollKey() { return 'rouh.rules.scroll:' + memoryAddress(); }

function memoryScrollBack() {
  var scroller = $('rulesScroll');
  var at = 0;
  try { at = Number(sessionStorage.getItem(memoryScrollKey()) || 0); } catch (err) { at = 0; }
  if (!scroller || !at) return false;
  scroller.scrollTop = at;
  return true;
}

(function () {
  var scroller = $('rulesScroll'), timer = 0;
  if (!scroller) return;
  var spying = 0;
  scroller.addEventListener('scroll', function () {
    if (!MEMORY.data) return;
    if (!spying) spying = requestAnimationFrame(function () { spying = 0; memorySpy(); });
    clearTimeout(timer);
    timer = setTimeout(function () {
      try { sessionStorage.setItem(memoryScrollKey(), String(Math.round(scroller.scrollTop))); } catch (err) { /* kept for this visit only */ }
    }, 150);
  }, { passive: true });
})();

/* One group of rules that opens and closes, in What context/rules were included: whether it is open and what
   pressing its head does, how each of its rows is drawn, and what it says with none. The Rules page's own list
   is in topics (`memoryTopic`) since 30 October 2026. */
/** @param {{open: boolean, toggle: () => void, row: (r: any) => HTMLElement, empty: string}} how */
function memoryGroup(g, rows, how) {
  var sec = el('section', 'rules-group');
  sec.id = 'rulesGroup-' + g.key;
  var open = how.open;
  var head = el('button', 'rules-group-head');
  head.type = 'button';
  head.setAttribute('aria-expanded', open ? 'true' : 'false');
  head.setAttribute('aria-controls', 'rulesGroupBody-' + g.key);
  head.appendChild(el('span', 'rules-group-name', g.name));
  head.appendChild(el('span', 'rules-nav-count', String(rows.length)));
  head.addEventListener('click', function () { how.toggle(); });
  var h = el('h4', 'rules-group-title');
  h.appendChild(head);
  // Its (i): when the rules in it are told to a model, one sentence from the server (`rules.included_said`).
  var info = /** @type {HTMLButtonElement} */ (el('button', 'tc-info rules-group-info', 'i'));
  info.type = 'button';
  info.setAttribute('data-group', g.key);
  info.setAttribute('aria-controls', 'rulesGroupInfo-' + g.key);
  info.setAttribute('aria-expanded', MEMORY.info === g.key ? 'true' : 'false');
  info.setAttribute('aria-label', 'When the rules in ' + g.name + ' are used');
  info.addEventListener('click', function () { memoryInfo(MEMORY.info === g.key ? '' : g.key); });
  h.appendChild(info);
  sec.appendChild(h);
  var said = el('p', 'settings-help rules-group-said', g.included || '');
  said.id = 'rulesGroupInfo-' + g.key;
  said.hidden = MEMORY.info !== g.key;
  sec.appendChild(said);
  var list = el('ul', 'memory-list rules-list');
  list.id = 'rulesGroupBody-' + g.key;
  list.hidden = !open;
  if (open) {
    rows.forEach(function (r) { list.appendChild(how.row(r)); });
    if (!rows.length) list.appendChild(el('li', 'settings-note', how.empty));
  }
  sec.appendChild(list);
  return sec;
}

/* Show the sentence behind one group's (i), and put away any other; '' puts them all away. In place, not
   by drawing the page again, so the (i) pressed keeps its focus. */
function memoryInfo(key) {
  MEMORY.info = key;
  var view = $('memoryView');
  if (!view) return;
  [].slice.call(view.querySelectorAll('.rules-group-info')).forEach(function (b) {
    var on = b.getAttribute('data-group') === key;
    b.setAttribute('aria-expanded', on ? 'true' : 'false');
    var said = document.getElementById(b.getAttribute('aria-controls') || '');
    if (said) said.hidden = !on;
  });
}

// An open (i) closes with Escape, before Escape closes the page, and with a press anywhere else.
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape' || !MEMORY.info || !memoryViewing()) return;
  e.preventDefault();
  e.stopPropagation();
  var b = document.querySelector('.rules-group-info[data-group="' + MEMORY.info + '"]');
  memoryInfo('');
  if (b) /** @type {HTMLElement} */ (b).focus();
}, true);
document.addEventListener('click', function (e) {
  if (!MEMORY.info) return;
  var t = /** @type {Element} */ (e.target);
  if (t && t.closest && (t.closest('.rules-group-info') || t.closest('.rules-group-said'))) return;
  memoryInfo('');
}, true);

/* ---------- One rule ----------
 *
 * Every rule on the page, whatever it is, is drawn here and nowhere else:
 * its title (the first line as written), its full text whenever there is
 * more, its flag of where it came from, its date, and its four
 * controls, always the same four in the same order. */

function ruleIcon(path) {
  var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '13');
  svg.setAttribute('height', '13');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.innerHTML = path;
  return svg;
}
var RULE_INFO = '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>';

// Show or put away the line under a row that says where it came from.
function ruleWhy(r, which) {
  if (MEMORY.why[r.ref] === which) delete MEMORY.why[r.ref]; else MEMORY.why[r.ref] = which;
  memoryDraw();
}

function ruleWhyText(r, which) {
  if (which === 'from') return r.from_said || 'Nothing kept says where it came from.';
  return '';
}

/* The switch every rule has (Petar, 30 October 2026: "Fully remove that lock"): `on` and its words, and
   what pressing it does. One drawing for a rule's own switch and for its defaults tag while it is edited. */
function ruleToggle(on, label, onPress) {
  var b = el('button', 'gt-switch rule-switch');
  b.type = 'button';
  b.setAttribute('role', 'switch');
  b.setAttribute('aria-checked', on ? 'true' : 'false');
  b.setAttribute('aria-label', label);
  var track = el('span', 'gt-switch-track');
  track.appendChild(el('span', 'gt-switch-knob'));
  b.appendChild(track);
  b.appendChild(el('span', 'gt-switch-state', on ? 'On' : 'Off'));
  b.addEventListener('click', onPress);
  return b;
}

/* A rule's two switches (Petar, 30 October 2026, fr_61e683ffbada: "each rule will have 2 toggles: Chat ON/OFF
   button and Agent ON/OFF button"): Chat, whether its chats are told it, and Agent, whether every agent Rouh
   starts is (`rules.switches`). Each takes effect and is kept the moment it is pressed; both off is the rule
   turned off. One a rule cannot have on (its `*_can`) is greyed, and pressing it says why. */
var RULE_SIDES = [
  { key: 'chat', name: 'Chat', on: 'Your chats are told it.', off: 'No chat is told it.',
    turnedOn: 'Chat on. Your chats are told it from the next message.',
    turnedOff: 'Chat off. No chat is told it from the next message.' },
  { key: 'agent', name: 'Agent', on: 'Every agent Rouh starts is told it.', off: 'No agent is told it.',
    turnedOn: 'Agent on. Every agent that starts from now on is told it.',
    turnedOff: 'Agent off. No agent that starts from now on is told it.' }
];

function ruleSide(r, side) {
  var on = !!r[side.key], can = r[side.key + '_can'] !== false;
  var b = ruleToggle(on, side.name + ' ' + (on ? 'on' : 'off') + ': ' + r.title, function () {
    if (!can) { memorySay(r[side.key + '_why'] || '', 'bad'); return; }
    var body = { ref: r.ref, which: side.key, on: !on };
    memoryChange('/api/rules/switch', body, on ? side.turnedOff : side.turnedOn);
  });
  b.classList.add('rule-side', 'rule-side-' + side.key);
  b.setAttribute('data-side', side.key);
  b.insertBefore(el('span', 'rule-side-name', side.name), b.lastChild);
  if (!can) b.setAttribute('aria-disabled', 'true');
  b.title = !can ? r[side.key + '_why'] || '' : (on ? side.on : side.off) + ' Press to turn it ' + (on ? 'off.' : 'on.');
  return b;
}

function ruleSwitches(r) {
  var box = el('div', 'rule-sides');
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Where it is told');
  RULE_SIDES.forEach(function (side) { box.appendChild(ruleSide(r, side)); });
  return box;
}

function ruleFlag(r) {
  var l = ruleLabel(r.from === 'chat' ? 'from-chat' : r.from === 'agents' ? 'from-agents' : r.from) || ruleLabel('unknown');
  var b = ruleTag(l, 'button');
  b.classList.add('rule-flag');
  /** @type {HTMLButtonElement} */ (b).type = 'button';
  b.setAttribute('aria-expanded', MEMORY.why[r.ref] === 'from' ? 'true' : 'false');
  b.setAttribute('aria-label', l.name + ': where it came from');
  b.title = r.from_said || '';
  b.addEventListener('click', function () { ruleWhy(r, 'from'); });
  return b;
}

function ruleTitle(r) {
  return el('div', 'rule-title', r.title);
}

/* `bare` is the same row without its controls (its switches and its ⋯) and their lines, for What context/rules
   were included: Petar, 30 October 2026, "the UI ... should be exactly the same as the ui in the rules list minus
   the controls". */
function ruleRow(r, bare) {
  var li = el('li', 'memory-row rule-row' + (r.on ? '' : ' off') + (bare ? ' bare' : ''));
  li.setAttribute('data-ref', r.ref);
  if (!bare && MEMORY.editing === r.ref) return ruleEdit(r, li);
  var main = el('div', 'rule-main');
  main.appendChild(ruleTitle(r));
  // Its whole text, always in sight (Petar, 30 October 2026: "remove the toggle 'full text' and display the
  // full text always"), whenever it says more than its title.
  if (r.long) {
    var full = el('div', 'rule-full');
    if (r.newer) full.appendChild(el('p', 'settings-note', 'The defaults have newer words for this rule. They are in its history, to put back if you want them.'));
    full.appendChild(memoryText(r.flow ? ruleFlow(r.text) : r.text, ''));
    main.appendChild(full);
  }
  var meta = el('div', 'rule-meta');
  // Where it came from, and who it is for: on every rule, in sight without opening it.
  meta.appendChild(ruleFlag(r));
  meta.appendChild(ruleTag(ruleLabel(r.scope === 'instances' ? 'instances' : 'creator')));
  // For its creator alone and could help others: Useful, and the way to make it a rule for every Rouh.
  if (r.useful) {
    meta.appendChild(ruleTag(ruleLabel('useful')));
    if (!bare) {
      var std = ctl('Make standard', 'rule-standard', function () {
        memoryChange('/api/rules/standard', { ref: r.ref },
          'Made standard. It is in the defaults every Rouh installed from now on starts with.');
      });
      std.title = 'Turn it into a rule for every Rouh instance';
      meta.appendChild(std);
    }
  }
  (r.silo_chips || []).forEach(function (c) { meta.appendChild(siloChip(c)); });
  if (r.at) meta.appendChild(el('span', 'memory-when', r.at_said + ' ' + memoryDay(r.at)));
  // When it is told, from what its row says (rules.condition_lines), the same the prompt is put together
  // from: closed behind its count until pressed, then one condition to a bullet.
  var conds = [].concat(r.conditions || []);
  if (conds.length) {
    var open = !!MEMORY.conds[r.ref];
    var cb = el('button', 'rule-conds-btn', conds.length + (conds.length === 1 ? ' condition' : ' conditions'));
    cb.type = 'button';
    cb.setAttribute('aria-expanded', open ? 'true' : 'false');
    cb.setAttribute('aria-controls', 'ruleConds-' + r.ref);
    cb.appendChild(ruleIcon(RULE_ICONS.down));
    cb.addEventListener('click', function () {
      if (open) delete MEMORY.conds[r.ref]; else MEMORY.conds[r.ref] = true;
      memoryDraw();
    });
    meta.appendChild(cb);
  }
  main.appendChild(meta);
  if (conds.length && MEMORY.conds[r.ref]) {
    var ul = el('ul', 'rule-conditions rule-conditions-list');
    ul.id = 'ruleConds-' + r.ref;
    ul.setAttribute('aria-label', 'When it is told');
    conds.forEach(function (c) { ul.appendChild(el('li', null, c)); });
    main.appendChild(ul);
  }
  var which = MEMORY.why[r.ref];
  if (which) {
    var why = el('p', 'rule-why');
    why.appendChild(ruleIcon(RULE_INFO));
    why.appendChild(el('span', null, ruleWhyText(r, which)));
    main.appendChild(why);
  }
  li.appendChild(main);
  if (bare) return li;
  li.appendChild(ruleActs(r));
  var h = MEMORY.history[r.ref];
  if (h) li.appendChild(ruleHistoryList(r, h));
  return li;
}

/* Its two switches and its ⋯, which holds Edit, History and Delete; or, while a delete is asked about, that. */
function ruleActs(r) {
  if (MEMORY.confirming === r.ref) {
    var foot = el('div', 'memory-foot rule-confirm');
    foot.appendChild(el('span', 'memory-ask', 'Delete this rule?'));
    var acts = el('div', 'setting-actions');
    acts.appendChild(ctl('Delete it', 'danger', function () {
      memoryChange('/api/rules/delete', { ref: r.ref }, 'Deleted. Rouh no longer follows it.');
    }));
    acts.appendChild(ctl('Keep it', '', function () { memoryDone(); }));
    foot.appendChild(acts);
    return foot;
  }
  var box = el('div', 'rule-acts');
  box.appendChild(ruleSwitches(r));
  var more = ruleRound('dots', 'More for this rule: Edit, History, Delete', 'rule-more', function (e) {
    e.stopPropagation();
    memoryMenuOpen(r, more);
  });
  more.setAttribute('data-side', 'more');
  more.setAttribute('aria-haspopup', 'menu');
  more.setAttribute('aria-expanded', 'false');
  box.appendChild(more);
  return box;
}

// A select of the groups, for a rule being edited or added; '' is "sorted by what it says".
function ruleGroupPick(current, auto) {
  var pick = el('select', 'rules-home');
  pick.setAttribute('aria-label', 'Its group');
  if (auto) {
    var o0 = el('option', null, 'Sorted by what it says');
    o0.value = '';
    pick.appendChild(o0);
  }
  ((MEMORY.data && MEMORY.data.groups) || []).forEach(function (g) {
    var o = el('option', null, g.name);
    o.value = g.key;
    if (g.key === current) o.selected = true;
    pick.appendChild(o);
  });
  return pick;
}

function ruleField(words, control) {
  var lab = el('label', 'rule-field');
  lab.appendChild(el('span', 'memory-when', words));
  lab.appendChild(control);
  return lab;
}

/* Editing one rule: its words, its group, who it is for, and its silos and which replies it is kept to.
   Save sends them all at once. */
function ruleEdit(r, li) {
  li.classList.add('editing');
  var box = el('textarea', 'memory-edit');
  memoryDraft(box, 'edit:' + r.ref, r.text);
  box.setAttribute('aria-label', 'The words of the rule');
  li.appendChild(box);
  if (r.values && r.values.length) {
    li.appendChild(el('p', 'memory-when', 'Rouh fills in ' + r.values.map(function (v) { return '{' + v + '}'; }).join(', ') +
      ' live (' + r.values_said + '). Keep them where the value goes.'));
  }
  var refused = memoryRefusal(r.ref);
  if (refused) li.appendChild(refused);
  var group = ruleGroupPick(r.group, false);
  li.appendChild(ruleField('Group', group));
  var picked = (r.silos || []).slice(), mode = r.mode || '';
  var scope = r.scope === 'instances' ? 'instances' : 'creator', useful = !!r.useful;
  if (r.kind === 'rule') {
    // Who it is for, and its Useful label while it is for its creator alone, kept with Save: Rouh instances
    // is the defaults tag every Rouh's first rules are made from (rouh/ruledefaults.py).
    var scopeBox = el('div', 'rule-scope-pick');
    var drawScope = function () {
      scopeBox.textContent = '';
      var pick = el('div', 'memory-modes');
      pick.setAttribute('role', 'radiogroup');
      pick.setAttribute('aria-label', 'Who the rule is for');
      ['creator', 'instances'].forEach(function (k) {
        var b = el('button', 'memory-mode', RULE_SCOPE[k]);
        b.type = 'button';
        b.setAttribute('role', 'radio');
        b.setAttribute('aria-checked', scope === k ? 'true' : 'false');
        if (k === 'instances' && r.standard_no) b.disabled = true;
        b.addEventListener('click', function () { scope = k; drawScope(); });
        pick.appendChild(b);
      });
      scopeBox.appendChild(pick);
      if (r.standard_no) { scopeBox.appendChild(el('p', 'memory-when', r.standard_no)); return; }
      if (scope === 'creator') {
        var row = el('div', 'rule-useful-pick');
        row.appendChild(ruleToggle(useful, 'Useful to others: ' + (useful ? 'on' : 'off'), function () {
          useful = !useful; drawScope();
        }));
        row.appendChild(el('span', 'memory-when', 'Useful to others: labels it Useful, with Make standard beside it'));
        scopeBox.appendChild(row);
      }
    };
    drawScope();
    // A group of controls, not one, so not a label: pressing its words must not press the first of them.
    var scopeField = el('div', 'rule-field');
    scopeField.setAttribute('role', 'group');
    scopeField.setAttribute('aria-label', 'Who it is for');
    scopeField.appendChild(el('span', 'memory-when', 'Who it is for'));
    scopeField.appendChild(scopeBox);
    li.appendChild(scopeField);
    // Its silos (rouh/silos.py), each pressed in or out, kept with Save.
    var silos = el('div', 'silo-toggles memory-silos');
    silos.setAttribute('role', 'group');
    silos.setAttribute('aria-label', 'Silos of the rule');
    var drawSilos = function () {
      silos.textContent = '';
      ((MEMORY.data && MEMORY.data.silos) || []).forEach(function (c) {
        var on = picked.indexOf(c.key) >= 0;
        var b = el('button', 'silo-toggle');
        b.type = 'button';
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.appendChild(siloChip(c));
        b.addEventListener('click', function () {
          picked = on ? picked.filter(function (k) { return k !== c.key; }) : picked.concat([c.key]);
          drawSilos();
        });
        silos.appendChild(b);
      });
    };
    drawSilos();
    if ((MEMORY.data && MEMORY.data.silos || []).length) li.appendChild(silos);
    // Which replies it is kept to (rouh/replymode.py): every one, those read on a screen, or those said aloud.
    var modes = el('div', 'memory-modes');
    modes.setAttribute('role', 'radiogroup');
    modes.setAttribute('aria-label', 'When Rouh follows the rule');
    var drawModes = function () {
      modes.textContent = '';
      RULE_MODES.forEach(function (m) {
        var b = el('button', 'memory-mode', m[1]);
        b.type = 'button';
        b.setAttribute('role', 'radio');
        b.setAttribute('aria-checked', mode === m[0] ? 'true' : 'false');
        b.addEventListener('click', function () { mode = m[0]; drawModes(); });
        modes.appendChild(b);
      });
    };
    drawModes();
    li.appendChild(modes);
  }
  var foot = el('div', 'memory-foot');
  var acts = el('div', 'setting-actions');
  var drafts = ['edit:' + r.ref];
  acts.appendChild(ctl('Save', 'primary', function () {
    var body = { ref: r.ref, group: group.value, text: box.value };
    if (r.kind === 'rule') {
      body.silos = picked; body.mode = mode; body.defaults = scope === 'instances';
      body.useful = scope === 'creator' && useful;
    }
    memoryChange('/api/rules/edit', body, 'Saved. Rouh follows it as it reads now.', { at: r.ref, drafts: drafts });
  }));
  acts.appendChild(ctl('Cancel', '', function () {
    drafts.forEach(function (k) { delete MEMORY.drafts[k]; });
    memoryDone();
  }));
  foot.appendChild(acts);
  li.appendChild(foot);
  // Tall enough for the whole rule, so a long one is edited as it reads.
  setTimeout(function () {
    box.style.height = Math.min(box.scrollHeight + 4, 520) + 'px'; box.focus();
  }, 0);
  return li;
}

/* What a rule or an old fact says, written as it was
   written: paragraphs apart, a "- " line a list, **bold** bold. Petar, 4
   October 2026, on Rouh's character waiting here as one 1860-character
   run: "This entire block of text is unreadable." A one-line rule is one
   paragraph and looks as it always did. */
function memoryText(text, cls) {
  var d = el('div', 'memory-value memory-md' + (cls ? ' ' + cls : ''));
  d.innerHTML = renderMarkdown(text);
  return d;
}

// The words of a rule that was one of Rouh's own as they read, not as they were wrapped: the prompt's own lines
// were cut at eighty characters, so a line that only carries the sentence on is joined to the one before it. A
// heading ("The screen:"), a list item and an indented line keep their own line. The words kept are untouched.
function ruleFlow(text) {
  return String(text || '').split(/\n{2,}/).map(function (para) {
    var out = [];
    para.split('\n').forEach(function (line) {
      var prev = out.length ? out[out.length - 1] : null;
      var own = /^\s*[-*\d]/.test(line) || /^\s{2,}\S/.test(line) && !/^\s*-/.test(prev || '') ||
        prev === null || /:$/.test(prev) && out.length === 1;
      if (own) out.push(line); else out[out.length - 1] = prev + ' ' + line.trim();
    });
    return out.join('\n');
  }).join('\n\n');
}

var RULE_DID = { made: 'Added', reworded: 'Reworded', on: 'Turned on', off: 'Turned off', group: 'Moved',
                 restore: 'Put back', held: 'Newer words from the defaults, kept aside',
                 'chat on': 'Chat turned on', 'chat off': 'Chat turned off', 'agent on': 'Agent turned on',
                 'agent off': 'Agent turned off',
                 'defaults on': 'Set to Rouh instances', 'defaults off': 'Set to Creator only',
                 standard: 'Made standard', 'useful on': 'Marked useful', 'useful off': 'Useful mark taken off' };

function ruleHistory(ref) {
  return fetch('/api/rules/history?ref=' + encodeURIComponent(ref), { credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error('history ' + r.status); return r.json(); })
    .then(function (data) { MEMORY.history[ref] = data.history || []; memoryDraw(); })
    .catch(function () { memorySay('Its history could not be read. Try again in a moment.', 'bad'); });
}

function ruleHistoryList(r, h) {
  var wrap = el('ol', 'rule-history');
  wrap.setAttribute('aria-label', 'History of ' + r.title);
  var now = r.text;
  h.forEach(function (c) {
    var li = el('li', 'rule-change');
    var line = el('div', 'memory-foot');
    line.appendChild(el('span', 'memory-when', (RULE_DID[c.did] || c.did) + (c.group ? ' to ' + c.group : '') +
      (c.version ? ', version ' + c.version : '') + ', ' + memoryDay(c.at) + (c.by ? '. ' + c.by : '')));
    var acts = el('div', 'setting-actions');
    if (c.id && c.text && c.text !== now) {
      acts.appendChild(ctl('Put these words back', '', function () {
        memoryChange('/api/rules/restore', { ref: r.ref, change: c.id }, 'Put back. Rouh is told these words from the next message.')
          .then(function (ok) { if (ok) delete MEMORY.history[r.ref]; memoryDraw(); });
      }));
    }
    line.appendChild(acts);
    li.appendChild(line);
    if (c.text && c.text !== now) {
      var words = el('details', 'rule-was');
      words.appendChild(el('summary', null, 'Its words then'));
      words.appendChild(memoryText(c.text, 'rules-was'));
      li.appendChild(words);
    }
    wrap.appendChild(li);
  });
  if (!h.length) wrap.appendChild(el('li', 'settings-note', 'No changes yet.'));
  return wrap;
}

/* Adding a rule: its form at the head of the rules, opened by Add a rule beside the search. Until 30 October 2026
   Add a word was beside it; that day the person's own words became Vocabulary in Synapse (`rouh/vocabulary.py`),
   which the Vocabulary link beside Add a rule opens. */
function memoryAdding() {
  if (MEMORY.editing !== 'add-rule') return null;
  var wrap = el('div', 'rules-adding');
  wrap.appendChild(memoryAddRule());
  return wrap;
}

// The group a new rule goes into: the one picked in the list, or sorted by what it says.
function memoryNewGroup() {
  return MEMORY.group && MEMORY.group !== 'told' ? MEMORY.group : '';
}

// Who a rule is for: chosen people, tasks and projects as chips, and a box that finds more.
function memoryForPicker(chosen, onChange, noneYet) {
  var wrap = el('div', 'rules-for');
  var chips = el('div', 'rules-chips');
  var draw = function () {
    chips.replaceChildren();
    if (!chosen.length) chips.appendChild(el('span', 'memory-when', noneYet || 'Every conversation'));
    chosen.forEach(function (t, i) {
      var c = el('span', 'rules-chip', t.name + ' (' + t.type + ')');
      var x = el('button', 'rules-chip-x', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Remove ' + t.name);
      x.addEventListener('click', function () { chosen.splice(i, 1); draw(); onChange(); });
      c.appendChild(x);
      chips.appendChild(c);
    });
  };
  var box = el('input', 'memory-search rules-find');
  box.type = 'search';
  box.placeholder = 'For a person, task or project (optional)';
  box.setAttribute('aria-label', 'Find a person, task or project the rule is for');
  var found = el('ul', 'rules-found');
  var seq = 0, timer = 0;
  box.addEventListener('input', function () {
    clearTimeout(timer);
    var q = box.value.trim(), mine = ++seq;
    if (!q) { found.replaceChildren(); return; }
    timer = setTimeout(function () {
      fetch('/api/rules/targets?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : { targets: [] }; })
        .then(function (j) {
          if (mine !== seq) return;
          found.replaceChildren();
          (j.targets || []).forEach(function (t) {
            var li = el('li');
            var b = el('button', 'rules-pick', t.name);
            b.type = 'button';
            b.appendChild(el('span', 'memory-when', ' ' + t.about));
            b.addEventListener('click', function () {
              if (!chosen.some(function (c) { return c.type === t.type && c.id === t.id; })) chosen.push(t);
              box.value = ''; found.replaceChildren(); draw(); onChange();
            });
            li.appendChild(b);
            found.appendChild(li);
          });
          if (!(j.targets || []).length) found.appendChild(el('li', 'memory-when', 'Nobody and nothing by that name.'));
        });
    }, 220);
  });
  draw();
  wrap.appendChild(chips);
  wrap.appendChild(box);
  wrap.appendChild(found);
  return wrap;
}

function memoryAddRule() {
  var form = el('div', 'rules-add');
  var box = el('textarea', 'memory-edit');
  box.placeholder = 'A new rule, in your words: “Never sign my name on emails.”';
  box.setAttribute('aria-label', 'A new rule');
  memoryDraft(box, 'rule', '');
  form.appendChild(box);
  var refused = memoryRefusal('add');
  if (refused) form.appendChild(refused);
  form.appendChild(memoryForPicker(MEMORY.newFor, function () {}));
  var group = ruleGroupPick(memoryNewGroup(), true);
  form.appendChild(ruleField('Group', group));
  var acts = el('div', 'setting-actions');
  acts.appendChild(ctl('Add the rule', 'primary', function () {
    if (!box.value.trim()) { box.focus(); return; }
    memoryChange('/api/rules/add', { text: box.value, 'for': MEMORY.newFor, group: group.value },
                 MEMORY.newFor.length ? 'Added. Rouh follows it whenever that is involved.' :
                                        'Added. Rouh follows it from its next answer on.',
                 { at: 'add', drafts: ['rule'] }).then(function (ok) {
      if (ok) MEMORY.newFor = [];
    });
  }));
  acts.appendChild(ctl('Cancel', '', function () { delete MEMORY.drafts.rule; memoryDone(); }));
  form.appendChild(acts);
  setTimeout(function () { box.focus(); }, 0);
  return form;
}

// What the person has chosen for an old fact so far, starting from what was proposed.
function memoryChoice(f) {
  var c = MEMORY.choices[f.id];
  if (!c) {
    var p = f.proposal || {};
    c = MEMORY.choices[f.id] = {
      // 'word' is what a proposal made before 30 October 2026 says for Vocabulary.
      home: p.home === 'rule' && (p['for'] || []).length ? 'rulefor' : p.home === 'word' ? 'vocabulary' : (p.home || 'rule'),
      text: p.text || f.value, 'for': (p['for'] || []).slice(), term: p.term || '', meaning: p.meaning || '' };
  }
  return c;
}

function memoryApplyBody(f) {
  var c = memoryChoice(f);
  return { fact: f.id, home: c.home === 'rulefor' ? 'rule' : c.home, text: c.text,
           'for': c.home === 'rulefor' ? c['for'] : [], term: c.term, meaning: c.meaning };
}

function memoryOldCard(old) {
  var card = memoryCard('rulesOldHead', 'From your old memory: ' + old.length + ' to review',
    'Each fact Rouh kept before is shown with where Rouh proposes it goes now. Change anything, then Apply it; ' +
    'until you do, Rouh is still told it in every conversation, so nothing is lost on the way.');
  var all = ctl('Apply all as shown', 'primary', function () {
    if (MEMORY.busy) return;
    var queue = old.slice(), done = 0, skipped = [];
    var next = function () {
      if (!queue.length) {
        memorySay('Moved ' + done + ' from the old memory.' + (skipped.length ? ' Left for you to pick who they are for: ' +
                  skipped.join(', ') + '.' : ''), skipped.length ? '' : 'good');
        memoryLoad();
        return;
      }
      var f = queue.shift();
      var c = memoryChoice(f);
      if (c.home === 'rulefor' && !c['for'].length) { skipped.push(f.key); next(); return; }
      memoryPost('/api/rules/apply', memoryApplyBody(f)).then(function (a) {
        if (a.ok) { done += 1; delete MEMORY.choices[f.id]; }
        if (a.out && a.out.rows) { MEMORY.data = a.out; memoryDraw(); }
        next();
      });
    };
    memorySay('Moving them…');
    next();
  });
  var top = el('div', 'setting-actions');
  top.appendChild(all);
  card.appendChild(top);
  var list = el('ul', 'memory-list');
  old.filter(function (f) { return memoryHit(f.key + ' ' + f.value); }).forEach(function (f) {
    list.appendChild(memoryOldRow(f));
  });
  card.appendChild(list);
  return card;
}

function memoryOldRow(f) {
  var c = memoryChoice(f);
  var li = el('li', 'memory-row rules-old');
  li.appendChild(el('span', 'memory-key', f.key + (f.project ? ' · in ' + f.project : '')));
  li.appendChild(memoryText(f.value, 'rules-was'));
  if (f.proposal && f.proposal.why) li.appendChild(el('p', 'memory-when', 'Why: ' + f.proposal.why));
  var pick = el('select', 'rules-home');
  pick.setAttribute('aria-label', 'Where “' + f.key + '” goes');
  RULE_HOMES.forEach(function (h) {
    var o = el('option', null, h[1]);
    o.value = h[0];
    if (h[0] === c.home) o.selected = true;
    pick.appendChild(o);
  });
  pick.addEventListener('change', function () { c.home = pick.value; memoryDraw(); });
  li.appendChild(pick);
  if (c.home === 'rule' || c.home === 'rulefor' || c.home === 'note') {
    var box = el('textarea', 'memory-edit');
    box.value = c.text;
    box.setAttribute('aria-label', c.home === 'note' ? 'The note' : 'The rule');
    box.addEventListener('input', function () { c.text = box.value; });
    li.appendChild(box);
  }
  if (c.home === 'rulefor') {
    li.appendChild(memoryForPicker(c['for'], function () {}, 'Nobody picked yet: find who it is for'));
  }
  if (c.home === 'vocabulary') {
    var row = el('div', 'rules-word');
    var term = el('input', 'memory-search');
    term.value = c.term; term.placeholder = 'The word'; term.setAttribute('aria-label', 'The word');
    term.addEventListener('input', function () { c.term = term.value; });
    var meaning = el('input', 'memory-search');
    meaning.value = c.meaning; meaning.placeholder = 'What you mean by it';
    meaning.setAttribute('aria-label', 'What you mean by it');
    meaning.addEventListener('input', function () { c.meaning = meaning.value; });
    row.appendChild(term); row.appendChild(meaning);
    li.appendChild(row);
  }
  var foot = el('div', 'memory-foot');
  var acts = el('div', 'setting-actions');
  acts.appendChild(ctl(c.home === 'drop' ? 'Drop it' : 'Apply', c.home === 'drop' ? 'danger' : '', function () {
    if (c.home === 'rulefor' && !c['for'].length) {
      memorySay('Pick who “' + f.key + '” is for first, or make it a rule for every conversation.', 'bad');
      return;
    }
    memoryChange('/api/rules/apply', memoryApplyBody(f), {
      rule: 'Moved: now a rule every conversation.', rulefor: 'Moved: now a rule for ' +
        c['for'].map(function (t) { return t.name; }).join(', ') + '.', vocabulary: 'Moved: now in Vocabulary in Synapse.',
      note: 'Moved: now a note in Synapse.', drop: 'Dropped.' }[c.home]).then(function (ok) {
      if (ok) delete MEMORY.choices[f.id];
    });
  }));
  foot.appendChild(acts);
  li.appendChild(foot);
  return li;
}

/* ---------- What context/rules were included ----------
 *
 * The person's latest conversation requests from the log of requests, and
 * for one of them every stretch of its system prompt, which rule at which
 * version and why, or which live value, each checked against what the
 * request really sent (GET /api/rules/told). Its own place on the page,
 * /rules/told, beside the groups.
 *
 * It was "What Rouh was told" until 30 October 2026, when Petar asked
 * (fr_88108b80c467) for the name it has now, for the message he wrote and
 * the file he attached beside what was included, and for the rules to be
 * in the navigation's sections and groups and drawn as the list draws
 * them, without their controls. So a rule is its row in the list
 * (`ruleRow`, bare) in its group (`memoryGroup`), and what is not a rule -
 * live values, the tool catalogue - is a stretch after them.
 */

var TOLD = { told: null, toldList: null, toldBusy: false, toldAsked: '', toldOpen: {}, toldGroups: {} };

/* ---------- What agents start with ----------
 *
 * At /rules/agents: the text every agent Rouh starts is given before anything else, made from the rules with
 * their Agent switch on (GET /api/agent-instructions/preview), and, closed in a brown toggle, the latest runs
 * and what each was given (GET /api/agent-instructions/issued). It was on the Agent instructions page until 30
 * October 2026, when that page became the Agent switch on every rule here. */

var AGENTS = { text: null, runs: null, /** @type {Object<string, string>} */ open: {}, failed: false };

function agentsLoad() {
  var get = function (path) {
    return fetch(path, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(path + ' ' + r.status);
      return r.json();
    });
  };
  Promise.all([get('/api/agent-instructions/preview'), get('/api/agent-instructions/issued')])
    .then(function (got) { AGENTS.text = got[0]; AGENTS.runs = got[1].issued || []; AGENTS.failed = false; })
    .catch(function () { AGENTS.failed = true; AGENTS.text = AGENTS.text || { text: '', chars: 0 }; AGENTS.runs = AGENTS.runs || []; })
    .then(function () { if (MEMORY.group === 'agents') memoryDraw(); });
}

function agentsCard() {
  var c = memoryCard('rulesAgentsHead', 'What agents start with',
    'Every agent Rouh starts, a job, a run or a worker, is given this before anything else: the rules with their Agent switch on, under their headings. A run for one task also gets that task’s status, summary and AGENTS.md after it.');
  if (AGENTS.text === null) {
    c.appendChild(el('p', 'settings-note', 'Reading what an agent is given…'));
    agentsLoad();
    return c;
  }
  if (AGENTS.failed) c.appendChild(el('p', 'settings-say bad', 'This could not be read from the server. Try again in a moment.'));
  var see = el('a', 'rules-picked-back', 'Show the rules agents are told');
  see.href = '/rules?label=agent';
  see.addEventListener('click', function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    MEMORY.opened = {};
    memoryOpen('', 'agent');
  });
  c.appendChild(see);
  if (AGENTS.text.text) {
    c.appendChild(el('p', 'settings-help', AGENTS.text.chars.toLocaleString() + ' characters.'));
    var whole = el('div', 'rules-agents-text');
    whole.appendChild(memoryText(AGENTS.text.text, ''));
    c.appendChild(whole);
  }
  var runs = /** @type {HTMLDetailsElement} */ (el('details', 'brown-toggle rules-agents-runs'));
  runs.open = !!AGENTS.open.list;
  runs.addEventListener('toggle', function () { AGENTS.open.list = runs.open ? '1' : ''; });
  runs.appendChild(el('summary', null, 'What each run was given'));
  var inner = el('div', 'brown-toggle-body');
  if (!AGENTS.runs.length) inner.appendChild(el('p', 'settings-note', 'No run has started since this was kept.'));
  var list = el('ul', 'memory-list told-list');
  AGENTS.runs.forEach(function (q) {
    var li = el('li', 'memory-row');
    var b = el('button', 'told-pick');
    b.type = 'button';
    b.setAttribute('aria-expanded', AGENTS.open[q.id] !== undefined ? 'true' : 'false');
    b.appendChild(el('span', 'told-chat', q.title || q.run_id || 'A run'));
    b.appendChild(el('span', 'memory-when', memoryDay(q.at) + ' ' + toldTime(q.at) + (q.via ? ', ' + q.via : '') +
      ', ' + Number(q.chars || 0).toLocaleString() + ' characters'));
    b.addEventListener('click', function () {
      if (AGENTS.open[q.id] !== undefined) { delete AGENTS.open[q.id]; memoryDraw(); return; }
      AGENTS.open[q.id] = '';
      fetch('/api/agent-instructions/issued?id=' + encodeURIComponent(q.id), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : { text: 'This could not be read.' }; })
        .then(function (got) { AGENTS.open[q.id] = got.text || ''; memoryDraw(); },
              function () { AGENTS.open[q.id] = 'This could not be read.'; memoryDraw(); });
    });
    li.appendChild(b);
    if (AGENTS.open[q.id]) li.appendChild(el('pre', 'rules-agents-given', AGENTS.open[q.id]));
    list.appendChild(li);
  });
  inner.appendChild(list);
  runs.appendChild(inner);
  c.appendChild(runs);
  return c;
}

function toldCard() {
  var c = memoryCard('rulesToldHead', 'What context/rules were included',
    'Pick one of your messages to see what you wrote, and the rules and live values Rouh’s model was sent with it.');
  var form = el('div', 'told-form');
  var box = el('input', 'memory-search told-id');
  box.type = 'text'; box.inputMode = 'numeric'; box.placeholder = 'Request number';
  box.setAttribute('aria-label', 'Request number');
  box.value = TOLD.toldAsked;
  box.addEventListener('input', function () { TOLD.toldAsked = box.value; });
  box.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); toldOpen(box.value); } });
  form.appendChild(box);
  form.appendChild(ctl('Open', '', function () { toldOpen(box.value); }));
  c.appendChild(form);
  if (TOLD.told) { c.appendChild(toldView(TOLD.told)); return c; }
  if (TOLD.toldList === null) {
    c.appendChild(el('p', 'settings-note', 'Reading your latest messages…'));
    toldLoad();
    return c;
  }
  if (!TOLD.toldList.length) {
    c.appendChild(el('p', 'settings-note', 'Nothing yet: your next message to Rouh will be here.'));
    return c;
  }
  var list = el('ul', 'memory-list told-list');
  TOLD.toldList.forEach(function (q) {
    var li = el('li', 'memory-row');
    var b = el('button', 'told-pick');
    b.type = 'button';
    b.appendChild(el('span', 'told-num', '#' + q.id));
    b.appendChild(el('span', 'told-chat', q.chat || 'A conversation'));
    b.appendChild(el('span', 'memory-when', memoryDay(q.started_at) + ' ' + toldTime(q.started_at) + (q.model ? ', ' + q.model : '')));
    b.addEventListener('click', function () { toldOpen(String(q.id)); });
    li.appendChild(b);
    list.appendChild(li);
  });
  c.appendChild(list);
  return c;
}

function toldTime(s) {
  if (!s) return '';
  var d = new Date(s * 1000);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function toldLoad() {
  if (TOLD.toldBusy) return;
  TOLD.toldBusy = true;
  fetch('/api/rules/told', { credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error('told ' + r.status); return r.json(); })
    .then(function (data) { TOLD.toldBusy = false; TOLD.toldList = data.requests || []; memoryDraw(); })
    .catch(function () { TOLD.toldBusy = false; TOLD.toldList = []; memorySay('Your latest messages could not be read. Try again in a moment.', 'bad'); memoryDraw(); });
}

function toldOpen(ident) {
  ident = String(ident || '').replace(/[^0-9]/g, '');
  if (!ident) { memorySay('Give the number of a request, such as 12345.', 'bad'); return; }
  TOLD.toldAsked = ident;
  fetch('/api/rules/told?id=' + ident, { credentials: 'same-origin' })
    .then(function (r) {
      return r.json().then(function (out) { return { ok: r.ok, out: out }; }, function () { return { ok: false, out: {} }; });
    })
    .then(function (a) {
      if (!a.ok) { memorySay((a.out && a.out.error) || 'That request could not be read.', 'bad'); return; }
      memorySay('');
      TOLD.told = a.out.told; TOLD.toldOpen = {}; TOLD.toldGroups = {};
      memoryDraw();
    })
    .catch(function () { memorySay('The server could not be reached.', 'bad'); });
}

var TOLD_KIND = { rule: 'Rule', builtin: 'Rule', personal: 'Your rules', context: 'Live', catalogue: 'Tools', unknown: 'Not described' };

function toldView(t) {
  var wrap = el('div', 'told-view');
  var head = el('div', 'memory-foot');
  head.appendChild(el('span', 'told-head', 'Request #' + t.id + ', ' + memoryDay(t.at) + ' ' + toldTime(t.at) + ', ' + t.model));
  var acts = el('div', 'setting-actions');
  acts.appendChild(ctl('Back to the list', '', function () { TOLD.told = null; TOLD.toldList = null; memoryDraw(); }));
  head.appendChild(acts);
  wrap.appendChild(head);
  wrap.appendChild(toldAsked(t.asked || { found: false }));
  var all = 0, ok = 0;
  t.parts.forEach(function (p) { p.stretches.forEach(function (s) { all++; if (s.matches) ok++; }); });
  wrap.appendChild(el('p', 'memory-when told-check' + (ok === all ? ' good' : ''),
    ok === all ? 'Everything below is word for word what the request sent.'
               : (all - ok) + ' of ' + all + ' stretches could not be matched to how they were made; their words are still what was sent.'));
  var got = toldRules(t);
  var d = MEMORY.data || { sections: [], groups: [] };
  // The navigation's three sections and their groups, in its order, each group with the rules of it that were
  // included.
  (d.sections || []).forEach(function (sec) {
    var box = el('section', 'rules-section rules-section-' + sec.key);
    box.setAttribute('aria-labelledby', 'toldSection-' + sec.key);
    var h = el('h3', 'rules-section-title', sec.name);
    h.id = 'toldSection-' + sec.key;
    box.appendChild(h);
    (d.groups || []).filter(function (g) { return g.section === sec.key; }).forEach(function (g) {
      var rows = got.rules.filter(function (x) { return x.row.group === g.key; });
      // Closed until pressed (Petar, 30 October 2026), each with its count of the rules included.
      var open = !!TOLD.toldGroups[g.key];
      box.appendChild(memoryGroup(g, rows, {
        open: open,
        toggle: function () { TOLD.toldGroups[g.key] = !open; memoryDraw(); },
        row: function (x) { return toldRule(x); },
        empty: 'None of these was included.',
      }));
    });
    wrap.appendChild(box);
  });
  if (got.rest.length) {
    wrap.appendChild(el('h5', 'told-part', 'Not rules: what was worked out for this request'));
    var list = el('ul', 'memory-list');
    got.rest.forEach(function (s, i) { list.appendChild(toldStretch(s, 'rest:' + i)); });
    wrap.appendChild(list);
  }
  wrap.appendChild(el('p', 'memory-when', t.tools.count + ' tools were sent with it, from ' + t.tools.from + '.'));
  return wrap;
}

/* What the person wrote in the message the request answered, with the files they attached drawn as the chat
   draws them (`drawTurnFiles`). */
function toldAsked(a) {
  var box = el('section', 'told-asked');
  box.setAttribute('aria-labelledby', 'toldAskedHead');
  var h = el('h5', 'told-part', 'Your message');
  h.id = 'toldAskedHead';
  box.appendChild(h);
  if (!a.found) {
    box.appendChild(el('p', 'settings-note', a.note
      ? 'This answered a note Rouh’s own software wrote in your place, such as a job’s report, not a message of yours.'
      : 'The message this answered could not be found.'));
    return box;
  }
  var said = el('div', 'told-said');
  var words = a.text ? el('p', 'told-words', a.text) : null;
  if (words) said.appendChild(words);
  if (a.attachments && a.attachments.length) drawTurnFiles({ turn: said, body: words }, a.attachments);
  else said.appendChild(el('p', 'memory-when', 'No file was attached.'));
  box.appendChild(said);
  return box;
}

/* The rules a request was told, each as its row on the page ({row, version}), and every stretch that is not a
   rule, or names a rule there is no row for any more ({rest}). A rule told on its own has its stretch; the
   person's rules come in a stretch of several, which says which. */
function toldRules(t) {
  var rows = (MEMORY.data && MEMORY.data.rows) || [];
  var byRef = {};
  rows.forEach(function (r) { byRef[r.ref] = r; });
  var rules = [], rest = [], seen = {};
  var take = function (r, version) {
    if (seen[r.ref]) return;
    seen[r.ref] = true;
    rules.push({ row: r, version: version });
  };
  t.parts.forEach(function (p) {
    p.stretches.forEach(function (s) {
      if (s.kind === 'rule') {
        var r = byRef['r:' + s.key];
        // Deleted since: drawn from what was told, in the group its words put it in.
        take(r || { ref: 'r:' + s.key, kind: 'rule', title: s.title || 'A rule', text: s.text, long: true,
                    from: 'unknown', from_said: 'This rule has been deleted since it was told.', on: true,
                    group: s.group || '', 'for': [], silo_chips: [] }, s.version);
      } else if (s.kind === 'personal' && s.rules && s.rules.length) {
        var lost = false;
        s.rules.forEach(function (x) { var r = byRef['r:' + x.id]; if (r) take(r, x.version); else lost = true; });
        if (lost) rest.push(s);
      } else {
        rest.push(s);
      }
    });
  });
  return { rules: rules, rest: rest };
}

/* One included rule: its row in the list, without the controls, and a line when it has been changed since. */
function toldRule(x) {
  var li = ruleRow(x.row, true);
  if (x.version && x.row.version && x.version !== x.row.version) {
    li.appendChild(el('p', 'rule-conditions', 'Included at version ' + x.version + '; it is at version ' + x.row.version + ' now.'));
  }
  return li;
}

/* A stretch that is not a rule, closed until pressed, with its words as they were sent. */
function toldStretch(s, id) {
  var li = el('li', 'memory-row told-stretch');
  var box = el('details', 'told-fold');
  box.open = !!TOLD.toldOpen[id];
  box.addEventListener('toggle', function () { TOLD.toldOpen[id] = box.open; });
  var sum = el('summary', 'told-sum');
  sum.appendChild(el('span', 'told-kind told-' + s.kind, TOLD_KIND[s.kind] || s.kind));
  sum.appendChild(el('span', 'told-title', s.title + (s.version ? ', version ' + s.version : '')));
  if (s.matches === false) sum.appendChild(el('span', 'told-kind off', 'Differs'));
  box.appendChild(sum);
  var inner = el('div', 'told-inner');
  inner.appendChild(el('p', 'memory-when', s.why + (s.rule_kind === 'protected' ? '. Protected.' : '')));
  if (s.rules && s.rules.length) {
    inner.appendChild(el('p', 'memory-when', s.rules.map(function (x) { return x.why + ' (version ' + x.version + ')'; }).join('; ')));
  }
  inner.appendChild(el('pre', 'told-text', s.text));
  box.appendChild(inner);
  li.appendChild(box);
  return li;
}

$('memoryBtn').addEventListener('click', function () {
  accountMenu(false);
  if (memoryViewing()) { memoryClose(); return; }
  sidebarDone();
  memoryOpen('', '');
});
$('memoryClose').addEventListener('click', memoryClose);
$('rulesAddBtn').addEventListener('click', memoryAddOpen);
$('rulesAddRound').addEventListener('click', memoryAddOpen);
// The person's own words are Vocabulary in Synapse since 30 October 2026, a link away.
$('rulesVocab').addEventListener('click', function (e) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
  e.preventDefault();
  goToAddress('/synapse/vocabulary');
});
$('rulesFindBtn').addEventListener('click', function () {
  MEMORY.finding = !MEMORY.finding;
  if (!MEMORY.finding && $('memorySearch').value) $('memorySearch').value = '';
  memoryDraw();
  if (MEMORY.finding) $('memorySearch').focus();
});
$('rulesTopicsBtn').addEventListener('click', function () {
  MEMORY.drawer = !MEMORY.drawer;
  memoryDraw();
  var on = /** @type {HTMLElement | null} */ (document.querySelector('#rulesNav .rules-nav-row.on'));
  if (MEMORY.drawer && on) on.focus();
});
$('rulesDrawerShade').addEventListener('click', function () { MEMORY.drawer = false; memoryDraw(); });

/* Add a rule: its form at the head of the rules, scrolled to. */
function memoryAddOpen() {
  MEMORY.editing = 'add-rule'; MEMORY.confirming = ''; MEMORY.refused = null;
  memoryDraw();
  var s = $('rulesScroll');
  if (s) s.scrollTop = 0;
}

$('memorySearch').addEventListener('input', function () {
  MEMORY.confirming = '';
  memoryDraw();
});
$('memorySearch').addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  e.preventDefault();
  e.stopPropagation();
  if (this.value) { this.value = ''; memoryDraw(); return; }
  memoryClose();
});

// Coming back from Google. The callback sends the browser here with what
// happened in the address; it is read once, shown, and taken out of the
// address so a reload does not say it again. `?settings=mail` is the other
// way in: the mail alerts' decision log links back to its card with it.
(function () {
  var q = new URLSearchParams(location.search);
  var which = q.get('settings');
  if (which !== 'google' && which !== 'mail' && which !== 'telegram' &&
      which !== 'mailboxes') return;
  var outcome = q.get('google') || '';
  var said = q.get('say') || '';
  var whenReady = function () {
    settingsOpen(which === 'telegram' ? 'telegram' : 'email');
    if (which === 'mailboxes') {
      // Back from connecting a read-only mailbox (`rouh/web/mailboxes.py`).
      var box = q.get('mailbox') || '';
      settingsPin($('mboxHead').closest('section'));
      // Said beside the card, which is where the person is looking.
      var mSaid = $('mboxSaid');
      if (box === 'connected') {
        mSaid.className = 'settings-help';
        mSaid.textContent = (q.get('as') || 'The mailbox') + ' is connected, read-only.';
      } else if (box === 'forwarding') {
        mSaid.className = 'settings-help';
        mSaid.textContent = 'Rouh can now forward from ' + (q.get('as') || 'that mailbox') +
          ' when you ask. Everything else in it is still read-only.';
      } else if (box) {
        mSaid.className = 'settings-help bad';
        mSaid.textContent = said || 'No mailbox was connected.';
      }
      return;
    }
    if (which === 'mail' || which === 'telegram') {
      settingsPin($(which === 'mail' ? 'mailHead' : 'tgAccountHead').closest('section'));
      return;
    }
    if (outcome === 'connected') {
      settingsSay('Google is connected' + (q.get('as') ? ' as ' + q.get('as') : '') + '.', 'good');
    } else if (outcome === 'denied') {
      settingsSay(said || 'You did not give Rouh permission, so nothing was connected.', 'bad');
    } else if (outcome === 'not-set-up') {
      settingsSay('Your organisation has not registered a Google app yet, so there was nothing to connect through.', 'bad');
    } else if (outcome === 'error') {
      settingsSay(said || 'That did not work.', 'bad');
    }
  };
  // Once the whole of this script has run, not now: it is still being built
  // here, and opening a layer closes the Gene therapy board, whose state is
  // declared far below. Opened straight away, that threw, and a person back
  // from connecting Google landed on a blank Settings.
  setTimeout(whenReady, 0);
  var clean = new URL(location.href);
  ['settings', 'google', 'mailbox', 'say', 'as'].forEach(function (k) {
    clean.searchParams.delete(k);
  });
  history.replaceState(null, '', clean.pathname + (clean.search || '') + clean.hash);
})();

// The IANA name of the time zone this device is on ("Europe/Lisbon"), which
// a phone or a laptop sets from where it is. Empty if the browser will not say.
function browserZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) { return ''; }
}

/* ---------- Clockwork and Goals ----------
 *
 * Clockwork was called Reminders until 8 October 2026. Petar, that day:
 * "Rename reminders to clockwork and see what else inside needs readjusting,
 * for example the 'new reminder' button needs a change and the instructions
 * inside", because most of what is on it is work done at a time - Rouh's
 * nightly jobs, scheduled jobs, goal steps set for a time - and only some of
 * it reminders. The page is Clockwork; one thing on it is a reminder when it
 * is one (kind remind) and scheduled work when it is not. The ids, the
 * functions and /api/reminders kept their old names.
 *
 * Petar, 26 September 2026, answering task 60 again: "1 is not very
 * valuable. maybe I have to see how it works ... 4 I can't see it working.
 * I can't think of special goals ... Fine - please implement 1 and 4. think
 * carefully about the interface that should be visible and easy and
 * friendly".
 *
 * So each is a page of its own on the canvas, the same layer Memory and
 * Settings are, and each is two rows at the top of the sidebar that are
 * always there, whichever of the three lists is showing, saying what is in
 * them at a glance: the next reminder's time, and how many goals.
 *
 * Every page says what it is for. Reminders offers four things to say to
 * Rouh that go into the message box when pressed, because saying it is the
 * quickest way and the one that works on a phone in a pocket, and a form of
 * five fields. Goals is a name and everything the person knows, and then the
 * plan (see "Goals: the cards" below).
 *
 * The server works out every word and number these pages draw
 * (`rouh/reminders.py`, `rouh/goals.py`), so the page and the voice say the
 * same thing: "3 of 8 steps done". Every change answers with the whole
 * list again, and every other tab of the person's is told by a `clock`
 * message, which carries what the two sidebar rows say.
 *
 * When Rouh adds a reminder or a goal in the conversation on this screen,
 * the page opens by itself on the canvas at a desk, with the new row lit for
 * a moment (`clock_shown`), unless a page the person is reading is on the
 * canvas; on a phone, and over such a page, a note says so with Open. */

var CLOCK = { summary: null, reminders: null, goals: null, telegram: false, silos: [], rSilos: [],
              rOpen: false, gOpen: false,
              // The row lit for a moment because it was just added or changed.
              flash: '',
              // A reminder or goal whose Delete is being asked about, on its row.
              confirming: '',
              // The reminder or goal the form is open on; 'new' for a new one.
              rEditing: '', gEditing: '',
              // What the reminder's words were last read as (`remindersRead`),
              // and which fields the person set by hand, which the words then
              // leave alone.
              rRead: null, rOwn: {}, rAsking: null,
              // The reminders whose whole description is open (`remindersMore`).
              rOpenDetails: {},
              days: [],
              // Which of the Goals page's two it is: the list of goals, or
              // New goal ('list' | 'new').
              gPage: 'list',
              // The goal's chat the Goals page opened beside itself.
              keepFor: '',
              busy: false };

function remindersViewing() { return !!(CLOCK && CLOCK.rOpen); }
function goalsViewing() { return !!(CLOCK && CLOCK.gOpen); }

var REMINDER_TRY = [
  { kind: 'soon', head: 'In a few minutes',
    say: 'Remind me in ten minutes to take the washing out.' },
  { kind: 'day', head: 'On a day',
    say: 'Remind me on Friday at nine to call the dentist.' },
  { kind: 'daily', head: 'Every weekday',
    say: 'Every weekday at half past eight, tell me what is in my calendar today.' },
  { kind: 'weekly', head: 'A job every week',
    say: 'Every Monday at nine, look through my inbox for anything still waiting on me.' }
];
// Under the Goals page's four steps. Petar, 27 September 2026: "On this
// page you can give me a few examples below." Each is a name and the kind
// of thing to write under it; pressing one opens New goal with the name in
// and those words as the hint in the big box, which stays empty, so nothing
// of an example is ever saved as his.
var GOAL_TRY = [
  { kind: 'reach', head: 'Close three pilots by December',
    say: 'Who is warm and who went quiet, what each one needs from us, what stopped '
      + 'the last one, and what I can promise.' },
  { kind: 'move', head: 'Move to Lisbon next summer',
    say: 'Who comes, the dates that matter, what has to happen with the flat, the '
      + 'company and the school, and what worries me most.' },
  { kind: 'hire', head: 'Hire a first engineer',
    say: 'What they will build first, the budget, where good people are found, and why '
      + 'the last try went nowhere.' },
  { kind: 'body', head: 'Run a half marathon in April',
    say: 'Where I am now, the knee that hurts, how many mornings a week I really have, '
      + 'and what made me stop last time.' }
];
var CLOCK_GLYPH = {
  soon: '<path d="M7 3.5h10M7 20.5h10"/><path d="M8 3.5c0 4.5 8 5 8 8.5s-8 4-8 8.5M16 3.5'
    + 'c0 4.5-8 5-8 8.5s8 4 8 8.5"/>',
  day: '<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M8.5 3v4M15.5 3v4"/>'
    + '<circle cx="12" cy="15" r="1.6" fill="currentColor"/>',
  daily: '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
  weekly: '<rect x="3.5" y="6" width="17" height="12.5" rx="2"/><path d="M4 7l8 6 8-6"/>',
  reach: '<path d="M5.5 21V4"/><path d="M5.5 4.5h11l-2.2 4 2.2 4h-11"/>',
  move: '<path d="M4 11.5 12 5l8 6.5"/><path d="M6.5 10v9.5h11V10"/><path d="M10 19.5v-5h4v5"/>',
  hire: '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0"/>'
    + '<path d="M19 8v6M16 11h6"/>',
  body: '<path d="M4 20c3-1 4.5-3.5 6-7s3.5-6 7-7"/><circle cx="18.5" cy="5" r="1.6"/>'
    + '<path d="M4 20h16"/>'
};

function clockTryCard(item, press) {
  var card = el('button', 'try-card try-' + item.kind);
  card.type = 'button';
  card.title = press ? 'Start a goal from this example' : 'Put this in the message box';
  var mark = el('span', 'try-mark');
  mark.setAttribute('aria-hidden', 'true');
  mark.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
    + ' stroke="currentColor" stroke-width="1.7" stroke-linecap="round"'
    + ' stroke-linejoin="round">' + CLOCK_GLYPH[item.kind] + '</svg>';
  card.appendChild(mark);
  var words = el('span', 'try-words');
  words.appendChild(el('span', 'try-head', item.head));
  words.appendChild(el('span', 'try-say', item.say));
  card.appendChild(words);
  card.addEventListener('click', press ? function () { press(item); }
    : function () { tryThis(item.say); });
  var row = el('div', 'try-item');
  row.setAttribute('role', 'listitem');
  row.appendChild(card);
  return row;
}

function clockTries() {
  /** @type {Array<[string, any[], ((example: any) => void)?]>} */
  var lists = [['remindersTry', REMINDER_TRY], ['goalsTry', GOAL_TRY, goalsEdit]];
  lists.forEach(function (pair) {
    var list = $(pair[0]);
    if (!list || list.children.length) return;
    pair[1].forEach(function (item) { list.appendChild(clockTryCard(item, pair[2])); });
  });
}

/* ---- what the two sidebar rows say ---- */

// "18:30" today, "Tomorrow 09:00", "Mon 09:00" this week, "9 Oct" later.
function clockSoon(v) {
  if (!v || !v.time) return '';
  if (v.day === 'Today') return v.time;
  if (v.day === 'Tomorrow') return 'Tomorrow ' + v.time;
  if (/^[A-Z][a-z]+day$/.test(v.day)) return v.day.slice(0, 3) + ' ' + v.time;
  return v.day.replace(/^[A-Z][a-z]{2} /, '');
}

function clockRows() {
  var s = CLOCK.summary || {};
  var r = s.reminders || {}, g = s.goals || {};
  var rh = $('remindersHint'), gh = $('goalsHint');
  if (rh) {
    rh.textContent = r.next ? clockSoon(r.next) : '';
    rh.title = r.next ? 'Next: ' + (r.next.title || r.next.what) + ', ' + r.next.when : '';
  }
  if (gh) {
    gh.textContent = g.count ? String(g.count) : '';
    gh.title = g.count ? g.count + (g.count === 1 ? ' goal' : ' goals') : '';
  }
  var rr = $('remindersRow'), gr = $('goalsRow');
  if (rr) {
    rr.classList.toggle('on', remindersViewing());
    rr.setAttribute('aria-expanded', remindersViewing() ? 'true' : 'false');
  }
  if (gr) {
    gr.classList.toggle('on', goalsViewing());
    gr.setAttribute('aria-expanded', goalsViewing() ? 'true' : 'false');
  }
}

// The summary, worked out from the lists when they are what arrived.
function clockSummarise() {
  var s = CLOCK.summary || { reminders: {}, goals: {} };
  if (CLOCK.reminders) {
    var live = CLOCK.reminders.filter(function (v) { return v.state === 'on' && v.next_at; });
    live.sort(function (a, b) { return a.next_at - b.next_at; });
    s.reminders = { count: live.length, next: live[0] || null };
  }
  if (CLOCK.goals) s.goals = { count: CLOCK.goals.length };
  s.telegram = CLOCK.telegram;
  CLOCK.summary = s;
  clockRows();
}

/* ---- reading and writing ---- */

/** @param {string} path @param {boolean} [later] nobody is waiting on it: the sidebar's rows (`rouh.dbwork.later`) */
function clockGet(path, later) {
  if (typeof fetch !== 'function') return Promise.resolve(null);
  /** @type {Record<string, string>} */
  var headers = { 'X-Time-Zone': browserZone() };
  if (later) headers['X-Rouh-Later'] = '1';
  return fetch(path, { credentials: 'same-origin', headers: headers }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return null; }
    if (!r.ok) throw new Error(path + ' ' + r.status);
    return r.json();
  });
}

/* A change on Clockwork or a goal. With no connection it goes into this device's outbox
   (app/offline.js) and is carried out once there is one, through the same view, unless what it
   changed moved meanwhile (`offline._clock`); the page is drawn at once as it will be, and the
   answer says `queued`. What starts work now, or asks Luna, waits for a connection. */
function clockPost(path, body) {
  var off = window.RouhOffline;
  if (off && !off.online()) return clockOffline(path, body);
  return fetch(path, {
    method: 'POST', credentials: 'same-origin',
    // Every time on these pages is on the person's own clock (`rouh/web/clock.py`).
    headers: { 'Content-Type': 'application/json', 'X-Time-Zone': browserZone() },
    body: JSON.stringify(body)
  }).then(function (r) {
    if (r.status === 401) { location.href = '/login'; return { ok: false, out: {} }; }
    return r.json().then(function (out) { return { ok: r.ok, out: out }; },
                         function () { return { ok: false, out: {} }; });
  });
}

//: What a page may change with no connection, by its address: every act it takes from the outbox.
var CLOCK_OFFLINE = {
  '/api/reminders/act': ['pause', 'resume', 'delete'],
  '/api/reminders/save': null,
  '/api/goals/step': ['tick', 'status', 'note', 'reword', 'pause', 'resume', 'redirect', 'deadline', 'at',
                      'after', 'clear']
};

function clockOffline(path, body) {
  var acts = CLOCK_OFFLINE[path];
  if (acts === undefined || (acts && acts.indexOf(String(body.act || '')) < 0)) {
    return Promise.resolve({ ok: false, out: { error: path === '/api/reminders/read'
      ? 'There is no connection, so Rouh cannot read your words now. Fill in the fields below.'
      : 'That needs a connection to Rouh: it starts work now. It is not kept for later.' } });
  }
  var was = clockWas(path, body);
  var payload = { path: path, body: body, label: clockLabel(path, body, was), zone: browserZone() };
  return window.RouhOffline.queue('clock', payload, clockBase(path, was)).then(function () {
    return { ok: true, queued: true, out: clockLocally(path, body, was) };
  });
}

/* What the change acts on, as this page has it: the reminder, or the goal and its step. */
function clockWas(path, body) {
  if (path.indexOf('/api/reminders/') === 0) {
    return { reminder: (CLOCK.reminders || []).filter(function (v) { return String(v.id) === String(body.id); })[0] || null };
  }
  var folder = String(body.folder || '');
  var found = { goal: null, step: null };
  (CLOCK.goals || []).forEach(function (g) {
    if (g.folder === folder) found.goal = g;
    (function walk(list) {
      (list || []).forEach(function (s) {
        if (s.folder === folder || (found.goal === g && body.step && (s.id === body.step || s.n === body.step))) {
          found.goal = g;
          found.step = s;
        }
        walk(s.parts);
      });
    })(g.steps);
  });
  return found;
}

/* The version it was changed from, which the server holds it against. */
function clockBase(path, was) {
  if (was.reminder) {
    var r = was.reminder;
    return { state: r.state, title: r.title, what: r.what, repeat: r.repeat, days: r.days, at_time: r.at_time,
             kind: r.kind };
  }
  if (was.step) return { status: was.step.status };
  return {};
}

function clockLabel(path, body, was) {
  var r = was.reminder, name = r ? '“' + (r.title || r.what) + '”' : '';
  if (path === '/api/reminders/act') {
    return { pause: 'Pause ' + name + ' in Clockwork', resume: 'Turn ' + name + ' back on in Clockwork',
             delete: 'Delete ' + name + ' from Clockwork' }[body.act] || 'Change ' + name;
  }
  if (path === '/api/reminders/save') {
    return body.id ? 'Change ' + name + ' in Clockwork' : 'Schedule “' + (body.title || body.what) + '” in Clockwork';
  }
  var step = was.step ? '“' + was.step.title + '”' : 'a step';
  var goal = was.goal ? ' of “' + was.goal.title + '”' : '';
  if (body.act === 'tick') return (body.done ? 'Tick ' : 'Untick ') + '“' + (body.text || 'a step') + '” on ' + step + goal;
  if (body.act === 'status') {
    return body.status === 'done' ? 'Mark ' + step + goal + ' complete'
      : 'Set ' + step + goal + ' to ' + String(body.status || '').replace(/-/g, ' ');
  }
  if (body.act === 'pause' || body.act === 'resume') {
    return (body.act === 'pause' ? 'Pause' : 'Resume') + ' the goal' + (was.goal ? ' “' + was.goal.title + '”' : '');
  }
  if (body.act === 'redirect') return 'Redirect the goal' + (was.goal ? ' “' + was.goal.title + '”' : '');
  return 'Change ' + step + goal;
}

/* The page's own lists, as they will be once the change is carried out, so it is drawn so now
   and a page drawn again from this device's copy shows it too. */
function clockLocally(path, body, was) {
  if (path.indexOf('/api/reminders/') === 0) {
    var list = (CLOCK.reminders || []).map(function (v) { return Object.assign({}, v); });
    var saved = body.id || '';
    if (path === '/api/reminders/act') {
      if (body.act === 'delete') list = list.filter(function (v) { return String(v.id) !== String(body.id); });
      list.forEach(function (v) {
        if (String(v.id) !== String(body.id)) return;
        if (body.act === 'pause' || body.act === 'resume') {
          v.state = body.act === 'pause' ? 'paused' : 'on';
          v.group = body.act === 'pause' ? 'paused' : clockGroup(v.next_at);
        }
        v.queued = true;
      });
    } else {
      var when = (body.date ? body.date + ' ' : '') + (body.time || '');
      var fields = { title: body.title || '', what: body.what || '', details: body.what || '', kind: body.kind || 'remind',
                     repeat: body.repeat || 'once', days: body.days || [], date: body.date || '', time: body.time || '',
                     at_time: body.time || '', when: when, day: body.date || '', queued: true };
      if (body.id) {
        list.forEach(function (v) { if (String(v.id) === String(body.id)) Object.assign(v, fields); });
      } else {
        saved = 'offline-' + Date.now().toString(36);
        var at = body.date && body.time ? new Date(body.date + 'T' + body.time).getTime() / 1000 : 0;
        list.unshift(Object.assign({ id: saved, state: 'on', titled: !!body.title, next_at: at, repeats: '',
                                     group: clockGroup(at), fired: 0 }, fields));
      }
    }
    var answer = { ok: true, saved: saved, reminders: list, telegram: CLOCK.telegram };
    window.RouhOffline.prime('/api/reminders', { reminders: list, telegram: CLOCK.telegram });
    return answer;
  }
  var goals = JSON.parse(JSON.stringify(CLOCK.goals || []));
  var goalId = was.goal ? was.goal.id : '';
  goals.forEach(function (g) {
    if (g.id !== goalId) return;
    if (body.act === 'pause') g.paused = { at: Date.now() / 1000 };
    if (body.act === 'resume') g.paused = null;
    (function walk(steps) {
      (steps || []).forEach(function (s) {
        if (was.step && s.id === was.step.id) {
          if (body.act === 'status') s.status = body.status;
          if (body.act === 'tick' && s.your_steps && s.your_steps[body.index]) s.your_steps[body.index].done = !!body.done;
          if (body.act === 'note' && typeof body.note === 'string') s.note = body.note;
        }
        walk(s.parts);
      });
    })(g.steps);
  });
  window.RouhOffline.prime('/api/goals', { goals: goals, telegram: CLOCK.telegram });
  return { ok: true, goal: goalId, goals: goals, telegram: CLOCK.telegram };
}

// Which of Clockwork's lists a row going on is in, by when it is next: as `reminders._group` says.
function clockGroup(at) {
  if (!at) return 'later';
  var gap = Math.round((new Date(new Date(at * 1000).toDateString()).getTime()
    - new Date(new Date().toDateString()).getTime()) / 86400000);
  return gap <= 0 ? 'today' : gap === 1 ? 'tomorrow' : 'later';
}

//: What a page says when a change was kept on this device for when it is back online.
var CLOCK_KEPT = 'Kept on this device: it goes to Rouh when you are back online.';

function remindersLoad() {
  return clockGet('/api/reminders', !remindersViewing()).then(function (data) {
    if (data) remindersTake(data);
  }).catch(function () {
    if (remindersViewing()) clockSay('reminders', 'Clockwork could not be read from the '
      + 'server. Try again in a moment.', 'bad');
  });
}

function goalsLoad() {
  return clockGet('/api/goals', !goalsViewing()).then(function (data) {
    if (data) goalsTake(data);
  }).catch(function () {
    if (goalsViewing()) clockSay('goals', 'Your goals could not be read from the server. '
      + 'Try again in a moment.', 'bad');
  });
}

// Both, for the sidebar's two rows: when the socket comes up.
function clockLoad() {
  remindersLoad();
  goalsLoad();
}

function remindersTake(data) {
  if (!data || !data.reminders) return;
  CLOCK.reminders = data.reminders;
  CLOCK.silos = data.silos || [];
  CLOCK.telegram = !!data.telegram;
  clockSummarise();
  if (remindersViewing()) remindersDraw();
}

function goalsTake(data) {
  if (!data || !data.goals) return;
  CLOCK.goals = data.goals;
  CLOCK.telegram = !!data.telegram;
  clockSummarise();
  if (goalsViewing()) goalsDraw();
  goalMapTell(data.goals);
}

// Something changed, on this tab or another, by a press or out loud.
/** @param {import('./protocol').FromServer<'clock'>} m */
function clockHeard(m) {
  CLOCK.summary = m;
  CLOCK.telegram = !!m.telegram;
  clockRows();
  // A page with its form open or a row being asked about is left as it is,
  // and read again once that is put away: redrawing would take the fields
  // out from under the person's hands.
  if (remindersViewing() && !CLOCK.rEditing && !CLOCK.busy) remindersLoad();
  else if (!remindersViewing()) CLOCK.reminders = null;
  if (goalsViewing() && !CLOCK.gEditing && !CLOCK.busy) goalsLoad();
  // A goal's own page on the canvas draws itself again from what
  // comes back (`goalMapTell`): Rouh finished a step, another tab pressed.
  else if (!goalsViewing() && tasksViewing() && CANVAS.at.indexOf(TASK_PREFIX) === 0) goalsLoad();
  else if (!goalsViewing()) CLOCK.goals = null;
}

function clockSay(which, text, kind, action) {
  var box = $(which + 'Say');
  if (!box) return;
  box.className = 'settings-say' + (kind ? ' ' + kind : '');
  box.textContent = text || '';
  if (text && action) {
    var go = el('button', 'job-link clock-say-do', action.label);
    go.type = 'button';
    go.addEventListener('click', action.run);
    box.appendChild(document.createTextNode(' '));
    box.appendChild(go);
  }
  box.hidden = !text;
}

/* ---- opening and closing ---- */

function remindersOpen(flash) {
  if (ORBX.open) orbExpand(false);
  CLOCK.rOpen = true;
  if (flash) CLOCK.flash = 'r' + flash;
  showLayer('remindersView');
  sidebarDone();
  clockTries();
  clockSay('reminders', '');
  remindersDraw();
  remindersLoad();
  clockRows();
  if (!narrow()) $('remindersView').focus({ preventScroll: true });
}

function remindersClose() {
  if (!CLOCK || !CLOCK.rOpen) return;
  CLOCK.rOpen = false;
  CLOCK.rEditing = '';
  CLOCK.confirming = '';
  $('remindersForm').hidden = true;
  showLayer(null);
  clockRows();
}

function goalsOpen(flash) {
  if (ORBX.open) orbExpand(false);
  CLOCK.gOpen = true;
  if (flash) CLOCK.flash = 'g' + flash;
  showLayer('goalsView');
  sidebarDone();
  clockTries();
  clockSay('goals', '');
  // The list, which is New goal when there are none (`goalsDraw`).
  CLOCK.gEditing = '';
  goalsPage('list');
  goalsLoad();
  clockRows();
  if (!narrow()) $('goalsView').focus({ preventScroll: true });
}

function goalsClose() {
  if (!CLOCK || !CLOCK.gOpen) return;
  CLOCK.gOpen = false;
  CLOCK.gEditing = '';
  CLOCK.gPage = 'list';
  CLOCK.confirming = '';
  $('goalsForm').hidden = true;
  showLayer(null);
  clockRows();
}

// Rouh added or changed one in the conversation on this screen.
/** @param {import('./protocol').FromServer<'clock_shown'>} m */
function clockShown(m) {
  if (m.chat && CHATS && m.chat !== CHATS.active) return;
  var goals = m.view === 'goals';
  // One goal is its own page, at its task's goal.md; the Goals page is only
  // the list of them (fr_b7586f638301, fr_b083c37a634d). Already open on
  // it, or on its task's page, it is left where it is: the page draws the
  // goal again as it changes.
  var page = goals && typeof m.address === 'string' && m.address.indexOf('/task/') === 0
    ? m.address : '';
  var folder = page.slice('/task/'.length).replace(/\/goal\.md$/, '');
  var there = '';
  try { there = decodeURIComponent(CANVAS.at.split('?')[0]); } catch (err) {}
  if (page && tasksViewing() && CANVAS.at.indexOf(TASK_PREFIX) === 0
      && there.replace(/\/+$/, '').slice(-folder.length) === folder) return;
  var open = function () {
    if (page) { goalsClose(); goToAddress(page); }
    else if (goals) goalsOpen(m.id); else remindersOpen(m.id);
  };
  var layer = layerOpen();
  var ours = layer === 'remindersView' || layer === 'goalsView';
  if (!narrow() && (!layer || ours)) {
    open();
    return;
  }
  if (!m.id) return;
  // A phone, or another panel in front: the page is not taken away, and the
  // bar says what Rouh did and where to see it. It used to say only "Your
  // goal is on its own page.", which named neither the goal nor what had
  // happened to it, and Petar could not tell why it came (fr_f9bcb1df4d62).
  // `what` is the server's sentence of what changed; an older server sends
  // none, and then the bar says as much as it can without it.
  var what = typeof m.what === 'string' ? m.what.trim() : '';
  var words, label;
  if (goals) {
    words = (what || 'Rouh changed one of your goals.') + ' ' +
      (page ? 'Open the goal to see it.'
            : 'Open your goals to see it.');
    label = page ? 'Open the goal' : 'Open goals';
  } else {
    words = what || 'Added to Clockwork' + (m.said ? ', for ' + m.said : '') + '.';
    label = 'Open Clockwork';
  }
  notify(words, { tone: 'success', kind: goals ? 'heartbeat' : 'reminder',
                  action: { label: label, run: open }, for: 15000 });
}

/* ---- the three dots on a row ---- */

var clockMenuFor = null;

function clockMenu(button, items) {
  var menu = $('clockMenu');
  if (!menu.hidden && clockMenuFor === button) { clockMenuClose(); return; }
  menu.textContent = '';
  items.forEach(function (item) {
    if (item.rule) { menu.appendChild(el('hr', 'menu-rule')); return; }
    var b = el('button', 'menu-item' + (item.danger ? ' danger' : ''), item.label);
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.setAttribute('data-icon', item.icon);
    b.addEventListener('click', function () { clockMenuClose(); item.run(); });
    menu.appendChild(b);
  });
  RouhMenu.dress(menu);
  menu.hidden = false;
  clockMenuFor = button;
  button.setAttribute('aria-expanded', 'true');
  RouhMenu.place(menu, button, 'end');
  RouhMenu.first(menu);
}

function clockMenuClose() {
  var menu = $('clockMenu');
  if (menu.hidden) return;
  menu.hidden = true;
  if (clockMenuFor) clockMenuFor.setAttribute('aria-expanded', 'false');
  clockMenuFor = null;
}

function clockDots(label) {
  var dots = el('button', 'icon-btn tiny clock-dots');
  dots.type = 'button';
  dots.setAttribute('aria-haspopup', 'menu');
  dots.setAttribute('aria-expanded', 'false');
  dots.setAttribute('aria-label', label);
  dots.title = 'More';
  dots.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"'
    + ' fill="currentColor"><circle cx="5.5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/>'
    + '<circle cx="18.5" cy="12" r="1.7"/></svg>';
  return dots;
}

(function () {
  var menu = $('clockMenu');
  if (!menu) return;
  menu.addEventListener('keydown', function (e) {
    if (RouhMenu.keys(menu, e)) return;
    if (e.key === 'Tab') clockMenuClose();
  });
  document.addEventListener('click', function (e) {
    if (menu.hidden) return;
    if (menu.contains(e.target) || (clockMenuFor && clockMenuFor.contains(e.target))) return;
    clockMenuClose();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || menu.hidden) return;
    e.preventDefault();
    e.stopPropagation();
    var back = clockMenuFor;
    clockMenuClose();
    if (back) back.focus();
  }, true);
  window.addEventListener('resize', clockMenuClose);
})();

/* ---- Reminders: the list ---- */

var REMINDER_GROUPS = [['today', 'Today'], ['tomorrow', 'Tomorrow'], ['later', 'Later'],
                       ['paused', 'Paused'], ['done', 'Done']];

function remindersDraw() {
  var list = $('remindersList'), meta = $('remindersMeta');
  var rows = CLOCK.reminders;
  list.textContent = '';
  meta.textContent = '';
  if (!rows) {
    list.appendChild(el('p', 'settings-note clock-empty', 'Reading Clockwork…'));
    return;
  }
  var coming = rows.filter(function (v) { return v.state === 'on'; });
  // With nothing at all, the line in the list says so; this would say it twice.
  if (rows.length) {
    meta.appendChild(el('span', null, coming.length
      ? coming.length + ' coming up' : 'Nothing coming up'));
  }
  if (coming.length && coming[0].day) {
    meta.appendChild(el('span', null, 'Next: ' + coming[0].day + ' ' + coming[0].time));
  }
  $('remindersIntro').classList.toggle('lone', !rows.length);
  // Nothing yet: a line that says so, then what the page is for and the four
  // things to say.
  if (!rows.length) {
    list.appendChild(el('p', 'settings-note clock-empty clock-none', 'Nothing in Clockwork yet. '
      + 'Ask Rouh to remind you of something, or to do a piece of work at a time or on a repeat.'));
    return;
  }
  REMINDER_GROUPS.forEach(function (g) {
    var mine = rows.filter(function (v) { return v.group === g[0]; });
    if (!mine.length) return;
    var part = el('section', 'clock-group clock-g-' + g[0]);
    part.appendChild(el('h5', 'clock-group-name', g[1]));
    var ul = el('ul', 'clock-rows');
    mine.forEach(function (v) { ul.appendChild(reminderRow(v)); });
    part.appendChild(ul);
    list.appendChild(part);
  });
  remindersMore(list);
  clockFlash();
}

// A description longer than three lines is cut there, with More under it to
// read the rest in place, so the list is still scanned by its titles.
function remindersMore(list) {
  Array.prototype.forEach.call(list.querySelectorAll('.clock-details'), function (d) {
    var key = d.getAttribute('data-key');
    if (CLOCK.rOpenDetails[key]) d.classList.add('open');
    else if (d.scrollHeight <= d.clientHeight + 1) return;
    var more = el('button', 'clock-more', d.classList.contains('open') ? 'Less' : 'More');
    more.type = 'button';
    more.setAttribute('aria-expanded', d.classList.contains('open') ? 'true' : 'false');
    more.addEventListener('click', function () {
      var open = d.classList.toggle('open');
      if (open) CLOCK.rOpenDetails[key] = true; else delete CLOCK.rOpenDetails[key];
      more.textContent = open ? 'Less' : 'More';
      more.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    d.parentNode.insertBefore(more, d.nextSibling);
  });
}

// Words with the addresses in them made into links, opened in a tab of their own.
function clockLinked(node, text) {
  String(text || '').split(/(https?:\/\/[^\s)]+)/).forEach(function (part, i) {
    if (!(i % 2)) { if (part) node.appendChild(document.createTextNode(part)); return; }
    var a = el('a', 'clock-link', part);
    a.href = part;
    a.target = '_blank';
    a.rel = 'noopener';
    node.appendChild(a);
  });
  return node;
}

function reminderRow(v) {
  var id = String(v.id);
  var li = el('li', 'clock-row r-' + v.kind + ' s-' + v.state);
  li.setAttribute('data-key', 'r' + id);
  var done = v.state === 'done';
  var at = el('div', 'clock-at');
  at.appendChild(el('strong', null, done ? v.last_time : v.time));
  at.appendChild(el('span', null, done ? v.last_day : v.day));
  li.appendChild(at);

  // Its one line, which the list is scanned by, and the rest under it, quieter
  // (Petar, 8 October 2026, fr_b6dabdcc28e2).
  var main = el('div', 'clock-main');
  main.appendChild(el('p', 'clock-what', v.title || v.what));
  if (v.details) {
    var details = clockLinked(el('p', 'clock-details'), v.details);
    details.setAttribute('data-key', 'r' + id);
    main.appendChild(details);
  }
  var sub = el('p', 'clock-sub');
  var kind = el('span', 'clock-kind k-' + v.kind);
  kind.appendChild(el('span', 'clock-kind-ic k-' + v.kind));
  kind.appendChild(document.createTextNode(v.kind_words));
  sub.appendChild(kind);
  if (v.repeat !== 'once') sub.appendChild(el('span', 'clock-rep', v.repeats));
  if (v.state === 'paused') sub.appendChild(el('span', 'clock-paused-word', 'Paused'));
  // Its silos (rouh/silos.py), as small chips.
  (v.silo_chips || []).forEach(function (c) { sub.appendChild(siloChip(c)); });
  // About Rouh itself (Petar, 18 October 2026, fr_5db528986cf6).
  if (v.about_rouh) {
    var rouh = el('span', 'clock-rouh', 'About Rouh');
    if (v.repeat !== 'once') rouh.title = 'Not in the morning brief, because it repeats';
    sub.appendChild(rouh);
  }
  // Made for a trusted contact under their Clockwork grant: its owner, and nothing on
  // the person's own (Petar, 11 October 2026).
  if (v.owner) {
    var owner = el('span', 'clock-owner', 'For ' + v.owner);
    owner.title = 'Made for ' + v.owner + ' under their Clockwork grant. Rouh changes only their own items.';
    sub.appendChild(owner);
    // Who it goes to: you, them, or both (Petar, 12 October 2026: Clockwork does at a time
    // what their other grants allow, and a reminder to them is Communication's).
    if (v.to_said) sub.appendChild(el('span', 'clock-to', v.to_said));
  }
  main.appendChild(sub);
  // A contact's item that stopped when it came due, because a grant it needs was taken away.
  if (v.stopped_why) main.appendChild(el('p', 'clock-stopped', 'Stopped: ' + v.stopped_why));
  if (v.last_said && v.last_time && !v.stopped_why) {
    // "Last time, today at 09:00: handed to Rouh in General, which started a
    // run and messaged your phone"; a reminder already said has its time on
    // the left, so only what became of it, with a capital. The chat it was
    // handed to has the whole of it, one press away (fr_0d01a6cf1316).
    var last = el('p', 'clock-last', done
      ? v.last_said.charAt(0).toUpperCase() + v.last_said.slice(1)
      : 'Last time, ' + v.last_day.toLowerCase() + ' at ' + v.last_time + ': ' + v.last_said);
    if (v.last_said.indexOf('handed to Rouh') >= 0 || v.last_said.indexOf('done in') >= 0) {
      // A link to that chat (`linkTo`), so it opens in a tab of its own too.
      var see = linkTo(el('a', 'clock-see', 'See it in the chat'), function () {
        var to = v.chat || CHATS.general;
        return to ? addrOf('chat', to) : '';
      });
      see.addEventListener('click', function () { clockToChat(v.chat); });
      last.appendChild(document.createTextNode(/[.!?\u201d]$/.test(v.last_said) ? ' ' : '. '));
      last.appendChild(see);
    }
    main.appendChild(last);
  }
  li.appendChild(main);

  if (CLOCK.confirming === 'r' + id) {
    var ask = el('div', 'clock-confirm');
    ask.appendChild(el('span', 'memory-ask', v.kind === 'remind' ? 'Delete this reminder?'
      : 'Delete this scheduled work?'));
    var yes = el('button', 'ctl small danger', 'Delete');
    yes.type = 'button';
    yes.addEventListener('click', function () { reminderAct(v, 'delete'); });
    var no = el('button', 'ctl small', 'Keep it');
    no.type = 'button';
    no.addEventListener('click', function () { CLOCK.confirming = ''; remindersDraw(); });
    ask.appendChild(yes);
    ask.appendChild(no);
    li.appendChild(ask);
    setTimeout(function () { no.focus(); }, 0);
    return li;
  }

  var acts = el('div', 'clock-acts');
  // Rouh's own server job (the nightly Synapse run): started by code, never a chat turn. It is paused,
  // resumed or started now, and what it did is on its own page, so there is no Edit and no Delete.
  var server = v.kind === 'server';
  if (!done && !server) {
    var now = el('button', 'ctl small clock-now', 'Try it now');
    now.type = 'button';
    now.title = 'Have it said now, to see how it arrives. Its time stays as it is';
    now.addEventListener('click', function () { reminderAct(v, 'try'); });
    acts.appendChild(now);
  }
  if (server && v.job === 'synapse_nightly') {
    var see = linkTo(el('a', 'ctl small clock-now', 'See the attempts'), '/synapse/improvements');
    see.title = 'Every attempt to make Synapse better, on the Synapse lab\'s Improvements page';
    see.addEventListener('click', function () { goToAddress('/synapse/improvements'); });
    acts.appendChild(see);
  }
  var dots = clockDots('More for ' + (v.title || v.what));
  dots.addEventListener('click', function (e) {
    e.stopPropagation();
    var items = [];
    // Whether it is about Rouh, put right in one press, on every row (fr_5db528986cf6).
    var rouhItem = v.about_rouh
      ? { label: 'Not about Rouh', icon: 'rouh', run: function () { reminderAct(v, 'not_rouh'); } }
      : { label: 'About Rouh', icon: 'rouh', run: function () { reminderAct(v, 'rouh'); } };
    if (server) {
      if (!done) {
        items.push({ label: 'Start it now', icon: 'resume', run: function () { reminderAct(v, 'try'); } });
        items.push(v.state === 'paused'
          ? { label: 'Resume', icon: 'resume', run: function () { reminderAct(v, 'resume'); } }
          : { label: 'Pause', icon: 'pause', run: function () { reminderAct(v, 'pause'); } });
      }
      items.push(rouhItem);
      clockMenu(dots, items);
      return;
    }
    items.push({ label: done ? 'Again, at a new time' : 'Edit', icon: 'edit',
                 run: function () { remindersEdit(v); } });
    if (!done) {
      items.push(v.state === 'paused'
        ? { label: 'Resume', icon: 'resume', run: function () { reminderAct(v, 'resume'); } }
        : { label: 'Pause', icon: 'pause', run: function () { reminderAct(v, 'pause'); } });
    }
    items.push(rouhItem);
    items.push({ rule: true });
    items.push({ label: 'Delete', icon: 'delete', danger: true, run: function () {
      CLOCK.confirming = 'r' + id;
      remindersDraw();
    } });
    clockMenu(dots, items);
  });
  acts.appendChild(dots);
  li.appendChild(acts);
  return li;
}

function reminderAct(v, act) {
  if (CLOCK.busy) return;
  CLOCK.busy = true;
  clockPost('/api/reminders/act', { id: v.id, act: act }).then(function (answer) {
    CLOCK.busy = false;
    CLOCK.confirming = '';
    if (answer.out && answer.out.reminders) remindersTake(answer.out);
    if (!answer.ok) {
      clockSay('reminders', (answer.out && answer.out.error) || 'That did not work. Try again '
        + 'in a moment.', 'bad');
      return;
    }
    if (act === 'try') {
      var where = v.chat ? 'the chat it was set in' : 'its main chat';
      clockSay('reminders', v.kind === 'do'
        ? 'Rouh is doing it now, in ' + where
          + (CLOCK.telegram ? '. What it finds goes to your phone too.' : '.')
        : 'Handed to Rouh now, in ' + where + '. It decides what to do, and what it did '
          + 'shows on this row.', 'good',
        { label: 'Open the chat', run: function () { clockToChat(v.chat); } });
    } else if (answer.queued) {
      CLOCK.flash = 'r' + v.id;
      clockFlash();
      clockSay('reminders', (act === 'delete' ? 'Deleted “' + (v.title || v.what) + '”. ' : '') + CLOCK_KEPT, null);
    } else if (act === 'delete') {
      clockSay('reminders', 'Deleted “' + (v.title || v.what) + '”.', null);
    } else {
      CLOCK.flash = 'r' + v.id;
      clockFlash();
    }
  }).catch(function () {
    CLOCK.busy = false;
    clockSay('reminders', 'That did not work. Try again in a moment.', 'bad');
  });
}

function clockToChat(chat) {
  if (!chat) { openGeneral(); return; }
  // A goal's chat is its task's, and opening a task's chat puts the task's
  // page on the canvas (`onChatSwitched`). Asked for from the Goals page, it
  // opens beside it instead: the plan is drawn here, and this is where the
  // person is working on it.
  CLOCK.keepFor = goalsViewing() ? chat : '';
  openChat(chat);
  if (narrow()) setPane('chat');
}

// The row just added or changed says so, in its own place, for a moment.
function clockFlash() {
  if (!CLOCK.flash) return;
  var key = CLOCK.flash;
  var node = document.querySelector('[data-key="' + key + '"]');
  if (!node) return;
  CLOCK.flash = '';
  node.classList.add('lit');
  try { node.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (err) {}
  setTimeout(function () { node.classList.remove('lit'); }, 2600);
}

/* ---- Reminders: the form ---- */

function clockToday(offsetDays) {
  var d = new Date();
  d.setDate(d.getDate() + (offsetDays || 0));
  var m = d.getMonth() + 1, day = d.getDate();
  return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
}

function clockNextHour() {
  var d = new Date();
  var h = d.getHours() + 1;
  return { date: clockToday(h > 23 ? 1 : 0), time: (h % 24 < 10 ? '0' : '') + (h % 24) + ':00' };
}

var CLOCK_DAYS = [['mon', 'M', 'Monday'], ['tue', 'T', 'Tuesday'], ['wed', 'W', 'Wednesday'],
                  ['thu', 'T', 'Thursday'], ['fri', 'F', 'Friday'], ['sat', 'S', 'Saturday'],
                  ['sun', 'S', 'Sunday']];

function remindersDaysDraw() {
  var box = $('remindersDays');
  box.textContent = '';
  box.hidden = $('remindersRepeat').value !== 'weekly';
  CLOCK_DAYS.forEach(function (d) {
    var b = el('button', 'clock-day', d[1]);
    b.type = 'button';
    b.title = d[2];
    b.setAttribute('aria-label', d[2]);
    var on = CLOCK.days.indexOf(d[0]) >= 0;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.addEventListener('click', function () {
      var at = CLOCK.days.indexOf(d[0]);
      if (at >= 0) CLOCK.days.splice(at, 1); else CLOCK.days.push(d[0]);
      remindersDaysDraw();
      box.querySelectorAll('.clock-day')[CLOCK_DAYS.indexOf(d)].focus();
    });
    box.appendChild(b);
  });
}

function remindersKind() {
  var picked = /** @type {HTMLInputElement} */ (document.querySelector('input[name="rkind"]:checked'));
  return picked ? picked.value : 'remind';
}

function remindersHelp() {
  var job = remindersKind() === 'do';
  $('remindersKindHelp').textContent = job
    ? 'At that time Rouh does this with its tools and tells you what it said and did. It acts '
      + 'only on your words here, and never pays, books or deletes anything for good by itself.'
    : 'At that time this is handed to Rouh, which decides what to do: message your phone, '
      + 'use its tools, or start a run. It never pays, books or deletes anything for good by itself.';
  $('remindersWhat').placeholder = job
    ? 'Every Monday at nine, look through my inbox for anything still waiting on me'
    : 'Alarm in 1h to call the dentist';
  // A row not titled yet shows the line it is drawn with until then, which
  // is kept only if the person writes it in.
  if (!$('remindersTitle').getAttribute('data-rough')) {
    $('remindersTitle').placeholder = job ? 'Look through my inbox for anything waiting on me'
                                          : 'Call the dentist to move the cleaning';
  }
  $('remindersWhere').textContent = 'It is handed to Rouh in its main chat'
    + (CLOCK.telegram ? ', and reaches your phone.'
                      : '. Telegram is not set up on this machine, so it does not reach your phone.');
}

/* Its silos on the form: every silo of the person's, each pressed in or out
   (rouh/silos.py). A new one is in none until a silo is pressed; one made in
   a task's chat came with that task's. */
function remindersSilosDraw() {
  var box = $('remindersSilos');
  if (!box) return;
  box.textContent = '';
  var all = CLOCK.silos || [];
  /** @type {HTMLElement} */ (box.parentNode).hidden = !all.length;
  all.forEach(function (c) {
    var on = (CLOCK.rSilos || []).indexOf(c.key) >= 0;
    var b = el('button', 'silo-toggle');
    b.type = 'button';
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.appendChild(siloChip(c));
    b.addEventListener('click', function () {
      CLOCK.rSilos = on ? CLOCK.rSilos.filter(function (k) { return k !== c.key; }) : (CLOCK.rSilos || []).concat([c.key]);
      remindersSilosDraw();
    });
    box.appendChild(b);
  });
}

function remindersEdit(v) {
  CLOCK.rEditing = v ? String(v.id) : 'new';
  CLOCK.confirming = '';
  var form = $('remindersForm');
  $('remindersFormHead').textContent = !v ? 'Schedule something'
    : v.state === 'done' ? 'The same again, at a new time'
    : v.kind === 'remind' ? 'Change the reminder' : 'Change the scheduled work';
  var kind = v && v.kind === 'do' ? 'do' : 'remind';
  /** @type {HTMLInputElement} */ (document.querySelector('input[name="rkind"][value="' + kind + '"]')).checked = true;
  // A new one starts from the words; one that is there is its title and its
  // description, each changed in place.
  $('remindersWhat').value = '';
  $('remindersWordsField').hidden = !!v;
  $('remindersTitle').value = v && v.titled ? v.title : '';
  if (v && !v.titled) {
    $('remindersTitle').setAttribute('data-rough', '1');
    $('remindersTitle').placeholder = v.title;
  } else {
    $('remindersTitle').removeAttribute('data-rough');
  }
  $('remindersDetails').value = v ? v.details || '' : '';
  // A new one has no time until the words give one or the person picks
  // one: nothing is made up for them.
  $('remindersDate').value = v && v.date && v.state !== 'done' ? v.date
    : v ? clockNextHour().date : '';
  $('remindersTime').value = v && (v.time || v.at_time) ? (v.time || v.at_time) : '';
  CLOCK.rRead = null;
  CLOCK.rAsking = null;
  CLOCK.rOwn = v ? { kind: true, date: true, time: true, repeat: true, title: true, details: true, rouh: true } : {};
  $('remindersRead').hidden = true;
  remindersNeeds([]);
  $('remindersRepeat').value = v ? v.repeat : 'once';
  CLOCK.days = v && v.days ? v.days.slice() : [];
  CLOCK.rSilos = v && v.silos ? v.silos.slice() : [];
  remindersSilosDraw();
  /** @type {HTMLInputElement} */ ($('remindersRouh')).checked = !!(v && v.about_rouh);
  $('remindersError').hidden = true;
  remindersHelp();
  remindersDaysDraw();
  form.hidden = false;
  clockSay('reminders', '');
  // The form is the first thing on the page, so the page goes to its top,
  // heading and all, rather than to wherever the caret happens to be.
  form.parentNode.scrollTop = 0;
  $(v ? 'remindersTitle' : 'remindersWhat').focus({ preventScroll: true });
}

/* ---- Reminders: the words read into the form ----
 *
 * Petar, 27 September 2026 (fr_07085c53b032): "I should not have to fill
 * those, they should be extracted from my text. alarm in 1h to do
 * something." And of a first try that read the words with rules: "this
 * should be determined by a luna model call. as i stop typing (debounce)".
 * So the first box takes the whole sentence and, once the person stops
 * typing, Luna reads it (`rouh/reminder_words.py`, on the person's own
 * clock) and the fields under it fill themselves in: the day, the time,
 * how it repeats, and whether it is a job. What the words did not say is
 * left empty and marked, and that is all there is left to fill. A field the
 * person set by hand is theirs, and the words leave it alone after that. */

function remindersNeeds(missing) {
  $('remindersDateField').classList.toggle('needs',
    missing.indexOf('day') >= 0 && !$('remindersDate').value);
  $('remindersTimeField').classList.toggle('needs',
    missing.indexOf('time') >= 0 && !$('remindersTime').value);
}

function remindersReadSoon() {
  clearTimeout(CLOCK.rTimer);
  // Once typing stops: a pause this long is the end of a thought, not a
  // letter being looked for, and each read is a request of Luna's.
  CLOCK.rTimer = setTimeout(remindersRead, 700);
}

// Read the box now. The answer is dropped if the words changed meanwhile.
function remindersRead() {
  clearTimeout(CLOCK.rTimer);
  var words = $('remindersWhat').value;
  if (CLOCK.rRead && CLOCK.rRead.words === words) return Promise.resolve(CLOCK.rRead);
  if (!words.trim()) {
    CLOCK.rRead = null;
    $('remindersRead').hidden = true;
    remindersNeeds([]);
    return Promise.resolve(null);
  }
  // The same words already on their way are waited for, not asked again.
  if (CLOCK.rAsking && CLOCK.rAsking.words === words) return CLOCK.rAsking.promise;
  var line = $('remindersRead');
  line.textContent = '';
  line.appendChild(el('span', 'clock-read-busy', 'Luna is reading your words\u2026'));
  line.hidden = false;
  var asking = { words: words };
  asking.promise = clockPost('/api/reminders/read', { words: words }).then(function (answer) {
    if (CLOCK.rAsking === asking) CLOCK.rAsking = null;
    if ($('remindersWhat').value !== words) return CLOCK.rRead;
    if (!answer.ok) {
      remindersReadFailed((answer.out && answer.out.error)
        || 'Your words could not be read just now: pick the day and the time below.');
      return null;
    }
    CLOCK.rRead = Object.assign({ words: words }, answer.out);
    remindersApply(CLOCK.rRead);
    return CLOCK.rRead;
  }).catch(function () {
    if (CLOCK.rAsking === asking) CLOCK.rAsking = null;
    if ($('remindersWhat').value === words) {
      remindersReadFailed('Your words could not be read just now: pick the day and the '
        + 'time below.');
    }
    return null;
  });
  CLOCK.rAsking = asking;
  return asking.promise;
}

function remindersReadFailed(why) {
  var line = $('remindersRead');
  line.textContent = '';
  line.appendChild(el('span', 'bad', why));
  line.hidden = false;
}

function remindersApply(got) {
  var own = CLOCK.rOwn;
  if (!own.kind) {
    /** @type {HTMLInputElement} */ (document.querySelector('input[name="rkind"][value="'
      + (got.kind === 'do' ? 'do' : 'remind') + '"]')).checked = true;
    remindersHelp();
  }
  if (!own.title) $('remindersTitle').value = got.title || '';
  if (!own.details) $('remindersDetails').value = got.details || '';
  if (!own.rouh) /** @type {HTMLInputElement} */ ($('remindersRouh')).checked = !!got.about_rouh;
  if (!own.date) $('remindersDate').value = got.date || '';
  if (!own.time) $('remindersTime').value = got.time || '';
  if (!own.repeat) {
    $('remindersRepeat').value = got.repeat || 'once';
    CLOCK.days = (got.days || []).slice();
    remindersDaysDraw();
  }
  remindersNeeds(got.missing || []);
  var line = $('remindersRead');
  line.textContent = '';
  var said = got.title ? '\u201c' + got.title + '\u201d' : '';
  var missing = got.missing || [];
  if (got.problem) {
    line.appendChild(el('span', 'bad', got.problem + ' Give a later time.'));
  } else if (got.when) {
    line.appendChild(document.createTextNode(said ? 'Rouh reads: ' : 'When: '));
    if (said) line.appendChild(el('b', null, said));
    line.appendChild(document.createTextNode((said ? ', ' : '') + got.when + '.'));
    if (!got.title) line.appendChild(document.createTextNode(' What should it be about?'));
  } else if (missing.indexOf('day') >= 0) {
    if (said) { line.appendChild(el('b', null, said)); line.appendChild(document.createTextNode('. ')); }
    line.appendChild(document.createTextNode('When? Say it in your words, such as \u201cin an hour\u201d '
      + 'or \u201ctomorrow at 9\u201d, or pick a day and a time below.'));
  } else {
    if (said) { line.appendChild(el('b', null, said)); line.appendChild(document.createTextNode(', ')); }
    line.appendChild(document.createTextNode((got.day || 'that day')
      + '. What time? Pick it below.'));
  }
  line.appendChild(el('span', 'clock-read-zone', ' Times are ' + got.zone + ' time, UTC'
    + got.offset + ', where you are.'));
  line.hidden = false;
}

function remindersFormDone() {
  CLOCK.rEditing = '';
  $('remindersForm').hidden = true;
}

function remindersSave(e, again) {
  if (e) e.preventDefault();
  if (CLOCK.busy) return;
  var err = $('remindersError');
  // Words typed and not read yet are read first, so Save straight after
  // typing saves what they say.
  if (!again && $('remindersWhat').value.trim() && CLOCK.rOwn.typed
      && !(CLOCK.rRead && CLOCK.rRead.words === $('remindersWhat').value)) {
    remindersRead().then(function () { remindersSave(null, true); });
    return;
  }
  var read = CLOCK.rOwn.typed && CLOCK.rRead
    && CLOCK.rRead.words === $('remindersWhat').value ? CLOCK.rRead : null;
  // The title and the description are what the fields hold, filled in from
  // the words or written by hand. Words nobody could read are kept whole as
  // the description, and Rouh gives them a title (`rouh/reminder_titles.py`).
  var title = $('remindersTitle').value.trim();
  var what = $('remindersDetails').value.trim();
  if (!title && !what && !read && CLOCK.rEditing === 'new') what = $('remindersWhat').value.trim();
  if (!title && !what) {
    err.textContent = 'Say what Rouh should remind you of, or do.';
    err.hidden = false;
    $(CLOCK.rEditing === 'new' && !read ? 'remindersWhat' : 'remindersTitle').focus();
    return;
  }
  if (!$('remindersTime').value) {
    err.textContent = 'When should it be? Your words did not say a time: add one to them, '
      + 'or pick it below.';
    err.hidden = false;
    remindersNeeds(['time']);
    $('remindersTime').focus();
    return;
  }
  var repeat = $('remindersRepeat').value;
  if (repeat === 'weekly' && !CLOCK.days.length) {
    err.textContent = 'Pick at least one day of the week.';
    err.hidden = false;
    return;
  }
  var body = { kind: remindersKind(), title: title, what: what, date: $('remindersDate').value,
               time: $('remindersTime').value, repeat: repeat, days: CLOCK.days, silos: CLOCK.rSilos || [],
               about_rouh: /** @type {HTMLInputElement} */ ($('remindersRouh')).checked };
  if (CLOCK.rEditing && CLOCK.rEditing !== 'new') {
    var was = (CLOCK.reminders || []).filter(function (v) {
      return String(v.id) === CLOCK.rEditing;
    })[0];
    if (was && was.state !== 'done') body.id = CLOCK.rEditing;
  }
  CLOCK.busy = true;
  $('remindersSave').disabled = true;
  clockPost('/api/reminders/save', body).then(function (answer) {
    CLOCK.busy = false;
    $('remindersSave').disabled = false;
    if (!answer.ok) {
      err.textContent = (answer.out && answer.out.error) || 'That could not be saved.';
      err.hidden = false;
      return;
    }
    remindersFormDone();
    CLOCK.flash = 'r' + answer.out.saved;
    remindersTake(answer.out);
    var row = (CLOCK.reminders || []).filter(function (v) {
      return v.id === answer.out.saved;
    })[0];
    if (answer.queued) {
      clockSay('reminders', 'Saved for ' + ((row && row.when) || 'the time you gave') + '. ' + CLOCK_KEPT, 'good');
    } else if (row) {
      clockSay('reminders', row.repeat === 'once'
        ? 'Saved. ' + (row.kind === 'do' ? 'Rouh does it ' : 'Rouh reminds you ') + row.when + '.'
        : 'Saved: ' + row.repeats.charAt(0).toLowerCase() + row.repeats.slice(1)
          + '. The first time is ' + row.when + '.', 'good');
    }
  }).catch(function () {
    CLOCK.busy = false;
    $('remindersSave').disabled = false;
    err.textContent = 'That could not be saved. Try again in a moment.';
    err.hidden = false;
  });
}

/* ---- Goals: the list, and New goal ----
 *
 * Petar, 27 September 2026 (fr_b7586f638301): "This entire goal information
 * should be as part of the tasks ... I click goals. I have a list of goals:
 * their titles only and if they have a deadline. On the side (desktop) and
 * below (mobile) are the two sections for how this works and examples. If I
 * want I can click new goal and go to a page that has the two inputs to
 * start a goal. Which is the default page if there are no goals currently
 * ... clicking a goal should take me to the task from the task browser.
 * That's where the goal would live."
 *
 * So the page is one of two: the list (CLOCK.gPage 'list'), a row per goal
 * with its name and its deadline, which opens the goal's own page, inside
 * its task (`goalpage.js`); or New goal ('new'), the
 * name and the big box. With no goals the list is never shown: Goals opens
 * on New goal. How it works and the examples are beside both at a desk, and
 * under them on a phone. */

function goalsPage(page) {
  CLOCK.gPage = page;
  var rows = CLOCK.goals;
  var fresh = page === 'new';
  var any = !!(rows && rows.length);
  $('goalsHead').textContent = fresh ? 'New goal' : 'Goals';
  $('goalsNew').hidden = fresh;
  $('goalsBack').hidden = !(fresh && any);
  $('goalsCancel').hidden = !any;
  $('goalsForm').hidden = !fresh;
  $('goalsList').hidden = fresh;
  $('goalsView').classList.toggle('g-new', fresh);
  goalsDraw();
}

function goalsDraw() {
  var list = $('goalsList'), meta = $('goalsMeta');
  var rows = CLOCK.goals;
  list.textContent = '';
  meta.textContent = '';
  if (!rows) {
    if (CLOCK.gPage !== 'new') {
      list.appendChild(el('li', 'settings-note clock-empty', 'Reading your goals…'));
    }
    return;
  }
  // Nothing to list: New goal instead, unless something is being said on
  // the page (a goal just saved is on its way into the list).
  if (!rows.length && CLOCK.gPage !== 'new') {
    goalsEdit();
    return;
  }
  if (CLOCK.gPage === 'new') {
    meta.appendChild(el('span', null, 'A name, and everything you know about it'));
    return;
  }
  meta.appendChild(el('span', null, rows.length + (rows.length === 1 ? ' goal' : ' goals')));
  rows.forEach(function (v) { list.appendChild(goalRow(v)); });
  clockFlash();
}

// One goal: its name, and its deadline when it has one. Pressed, its own
// page, with its streams. A goal whose every step is complete
// (`goals.standing`) carries a check before its name, and nothing else
// about it changes: it stays where it is (fr_de07e5455a93).
function goalRow(v) {
  var done = !!(v.standing && v.standing.state === 'complete');
  var li = el('li', 'goal-li');
  // A link to the goal's own address (`linkTo`), so Cmd-click opens it in
  // a tab of its own.
  var row = linkTo(el('a', 'goal-row' + (done ? ' complete' : '')), v.address || '');
  row.setAttribute('data-key', 'g' + v.id);
  if (done) {
    var tick = el('span', 'goal-row-done');
    tick.title = 'Complete: every step is done';
    tick.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none"'
      + ' stroke="currentColor" stroke-width="3" stroke-linecap="round"'
      + ' stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
    row.appendChild(tick);
  }
  row.appendChild(el('span', 'goal-row-title', v.title));
  if (done) row.appendChild(el('span', 'goal-row-state', 'Complete'));
  if (v.deadline && !done) {
    var due = el('span', 'goal-row-due' + (/ago|yesterday/.test(v.deadline_left) ? ' late' : ''));
    due.appendChild(el('span', 'goal-row-due-k', 'Due '));
    due.appendChild(document.createTextNode(v.deadline_words));
    due.title = v.deadline_left ? 'Due ' + v.deadline_words + ', ' + v.deadline_left : '';
    row.appendChild(due);
  }
  var go = el('span', 'goal-row-go');
  go.setAttribute('aria-hidden', 'true');
  go.textContent = '›';
  row.appendChild(go);
  row.setAttribute('aria-label', v.title + (done ? ', complete'
    : v.deadline ? ', due ' + v.deadline_words : '') + '. Open the goal');
  row.addEventListener('click', function () { goalOpen(v); });
  li.appendChild(row);
  return li;
}

function goalOpen(v) {
  goalsClose();
  goToAddress(v.address);
}

/* ---- Goals: the form ---- */

// From an example (GOAL_TRY) the name is its name, and what it says goes in
// as the hint only: the box is his to fill.
function goalsEdit(example) {
  var about = $('goalsAbout');
  CLOCK.gEditing = 'new';
  about.dataset.hint = about.dataset.hint || about.placeholder;
  $('goalsTitle').value = example ? example.head : '';
  about.value = '';
  about.placeholder = example ? example.say : about.dataset.hint;
  $('goalsError').hidden = true;
  goalsPage('new');
  if (example) clockSay('goals', '');
  $('goalsForm').closest('.settings-body').scrollTop = 0;
  (example ? about : $('goalsTitle')).focus({ preventScroll: true });
}

// Back to the list, which is New goal again when there is nothing in it.
function goalsFormDone() {
  CLOCK.gEditing = '';
  goalsPage('list');
}

function goalsSave(e) {
  if (e) e.preventDefault();
  if (CLOCK.busy) return;
  var err = $('goalsError');
  var name = $('goalsTitle').value.trim();
  var about = $('goalsAbout').value.trim();
  if (!name || !about) {
    err.textContent = !name ? 'Give the goal a short name.'
      : 'Write what you know about it - the more the better.';
    err.hidden = false;
    $(!name ? 'goalsTitle' : 'goalsAbout').focus();
    return;
  }
  CLOCK.busy = true;
  $('goalsSave').disabled = true;
  $('goalsSave').textContent = 'Saving…';
  clockPost('/api/goals/save', { name: name, about: about }).then(function (answer) {
    CLOCK.busy = false;
    $('goalsSave').disabled = false;
    $('goalsSave').textContent = 'Save goal';
    if (!answer.ok) {
      err.textContent = (answer.out && answer.out.error) || 'That could not be saved.';
      err.hidden = false;
      return;
    }
    CLOCK.gEditing = '';
    CLOCK.gPage = 'list';
    goalsTake(answer.out);
    var saved = (answer.out.goals || []).filter(function (g) { return g.id === answer.out.saved; })[0];
    // Straight to the goal's own page, where its streams will be, with
    // its chat beside it, where Rouh is asking what it needs to know; on a
    // phone, the chat, with the page a press away.
    // By the address the server answered with: the new task is filed into
    // a project as it is made, so the folder the chat first knew it by is
    // not where it is any more.
    goalsClose();
    if (saved) goToAddress(saved.address, answer.out.chat ? '?chat=' + answer.out.chat : '');
    else if (answer.out.chat) openChat(answer.out.chat);
  }).catch(function () {
    CLOCK.busy = false;
    $('goalsSave').disabled = false;
    $('goalsSave').textContent = 'Save goal';
    err.textContent = 'That could not be saved. Try again in a moment.';
    err.hidden = false;
  });
}

/* ---------------------------------------------------------------- control

   The Control Room, at `/control` (`rouh/controlroom.py`): the map of what
   is on Petar's mind, drawn by `controlroom.js`, which reads `/api/control` and
   keeps nothing of its own. This is only the layer's side of it: opening
   and closing it like any other page on the canvas, its row in the
   sidebar and its address. It reads the work once, when it is opened, and
   is never told to read again (Petar, 1 October 2026). It only reads; every line on it opens its own page. */

var CONTROL = { open: false };

function controlViewing() { return CONTROL.open; }

function controlOpen() {
  if (ORBX.open) orbExpand(false);
  CONTROL.open = true;
  showLayer('controlView');
  sidebarDone();
  controlRow();
  if (window.RouhControl) window.RouhControl.shown();
  if (!narrow()) $('controlView').focus({ preventScroll: true });
}

function controlClose() {
  if (!CONTROL.open) return;
  CONTROL.open = false;
  if (window.RouhControl) window.RouhControl.hidden();
  showLayer(null);
  controlRow();
}

function controlRow() {
  var row = $('controlRow');
  if (!row) return;
  row.classList.toggle('on', CONTROL.open);
  row.setAttribute('aria-expanded', CONTROL.open ? 'true' : 'false');
}

// What `controlroom.js` is handed: going to an address the way a link in
// Rouh goes there, closing the layer, and the pin on a card, which is the
// same `pin_object` the rail's menu sends (`rouh/pinning.py`). False when
// the socket is not open, and nothing was sent.
window.RouhControlHost = {
  go: function (href) { goToAddress(href); },
  close: controlClose,
  pin: function (id, on) { return !!send({ type: 'pin_object', kind: 'task', id: id, on: !!on }); }
};

(function () {
  var row = $('controlRow');
  if (!row) return;
  row.addEventListener('click', function () {
    if (controlViewing()) controlClose(); else controlOpen();
  });
})();

/* ---------------------------------------------------------------- synapse

   Synapse's lab, at `/synapse` and `/synapse/<dataset>` (`rouh/synapse/`):
   the new memory's datasets and, for each, a debugger, drawn by
   `synapse.js`. This is only the layer's side of it, like the Control
   Room's: opening and closing it, its row in the sidebar, its address, and
   the Synapse chat put beside it the way a task's chat sits beside the
   task's page: one chat for the whole of Synapse, whatever dataset is open
   (`rouh/synapse/chat.py`). */

var SYNAPSE = { open: false, ds: '', name: '' };

function synapseViewing() { return SYNAPSE.open; }

function synapseOpen(ds) {
  if (ORBX.open) orbExpand(false);
  SYNAPSE.open = true;
  SYNAPSE.ds = ds || '';
  showLayer('synapseView');
  sidebarDone();
  synapseRow();
  if (window.RouhSynapse) window.RouhSynapse.shown(SYNAPSE.ds);
  if (!narrow()) $('synapseView').focus({ preventScroll: true });
  addrTouch();
}

function synapseClose() {
  if (!SYNAPSE.open) return;
  SYNAPSE.open = false;
  if (window.RouhSynapse) window.RouhSynapse.hidden();
  showLayer(null);
  synapseRow();
  addrTouch();
}

function synapseRow() {
  var row = $('synapseRow');
  if (!row) return;
  row.classList.toggle('on', SYNAPSE.open);
  row.setAttribute('aria-expanded', SYNAPSE.open ? 'true' : 'false');
}

// What `synapse.js` is handed: the dataset it is showing (for the address),
// the Synapse chat put beside it, links that go where a link in Rouh
// goes, and closing the layer.
window.RouhSynapseHost = {
  dataset: function (id, name) {
    SYNAPSE.ds = id || '';
    SYNAPSE.name = name || '';
    addrTouch();
  },
  chat: function (id, show) {
    if (!id) return;
    // Pressed on a phone: the conversation is the other pane, so go to it.
    if (show && narrow()) setPane('chat');
    if (CHATS && CHATS.active === id) { if (!narrow()) chatIsWanted(); return; }
    // The address already says what is on the canvas: the chat is opened
    // beside it, and the canvas is not taken over by the switch.
    ADDR.forChat = id;
    send({ type: 'open_chat', id: id });
    if (!narrow()) { chatIsWanted(); return; }
    // On a phone the dataset stays on the screen: the chat is opened in the
    // other pane, a press away, unless the press was for the chat itself.
    if (show) return;
    [250, 900].forEach(function (ms) {
      setTimeout(function () { if (synapseViewing() && SYNAPSE.ds) setPane('canvas'); }, ms);
    });
  },
  activeChat: function () { return (CHATS && CHATS.active) || ''; },
  go: function (href) { goToAddress(href); },
  close: synapseClose,
  narrow: function () { return narrow(); }
};

(function () {
  var row = $('synapseRow');
  if (row) {
    row.addEventListener('click', function () {
      if (synapseViewing() && !SYNAPSE.ds) synapseClose(); else synapseOpen('');
    });
  }
  var x = $('synClose');
  if (x) x.addEventListener('click', synapseClose);
})();

/* ------------------------------------------------------------------ brief

   The morning brief, at `/brief` (`rouh/morning_brief.py`): today's
   calendar, weather, world news and AI on one page, drawn by `briefpage.js`
   from `/api/brief`. This is only the layer's side of it, as with the
   Control Room: opening and closing it, its row in the sidebar and its
   address, which is where the link sent to the phone each morning goes. */

// `view` is which brief: '' for today's, 'past' for every one kept, and a day
// (YYYY-MM-DD) for that day's as it was kept (fr_5fb00def9d2d), each at
// `/brief`, `/brief/past` and `/brief/<day>`.
var BRIEF = { open: false, view: '' };

function briefViewing() { return BRIEF.open; }

/** @param {string} [view] */
function briefOpen(view) {
  if (ORBX.open) orbExpand(false);
  var want = view || '';
  if (BRIEF.open) {
    // Already up: only which brief it shows moves, and the address with it.
    if (BRIEF.view !== want) {
      BRIEF.view = want;
      if (window.RouhBrief) window.RouhBrief.shown(want);
      addrTouch();
    }
    return;
  }
  BRIEF.open = true;
  BRIEF.view = want;
  showLayer('briefView');
  sidebarDone();
  briefRow();
  if (window.RouhBrief) window.RouhBrief.shown(want);
  if (!narrow()) $('briefView').focus({ preventScroll: true });
}

function briefClose() {
  if (!BRIEF.open) return;
  BRIEF.open = false;
  if (window.RouhBrief) window.RouhBrief.hidden();
  showLayer(null);
  briefRow();
}

function briefRow() {
  var row = $('briefRow');
  if (!row) return;
  row.classList.toggle('on', BRIEF.open);
  row.setAttribute('aria-expanded', BRIEF.open ? 'true' : 'false');
}

// What `briefpage.js` is handed: closing the layer, and Settings, where
// the brief's time and channels are changed.
window.RouhBriefHost = {
  close: briefClose,
  // Today's brief, every one kept, or one day's: '' / 'past' / YYYY-MM-DD.
  show: function (view) { briefOpen(view); },
  // An address in Rouh, from the Report: last night's attempt in the Synapse lab.
  go: function (href) { goToAddress(href); },
  // Waiting on others' Connect a mailbox: Settings, at the mailboxes card.
  mailboxes: function () {
    settingsOpen('email');
    settingsPin($('mboxHead') && $('mboxHead').closest('section'));
  },
  settings: function () {
    settingsOpen('brief');
  }
};

(function () {
  var row = $('briefRow');
  if (!row) return;
  row.addEventListener('click', function () {
    if (briefViewing()) briefClose(); else briefOpen('');
  });
})();

/* ------------------------------------------------------------------ quests

   The quests the heartbeat carries (`rouh/quests.py`): every one at `/quests`,
   with New quest, and each at `/quests/<its task's number>`, drawn by
   `questspage.js` from `/api/quests`; the first is the owner's own,
   quest 89. This is only the layer's side of it, as with the brief: opening
   and closing it, its row in the sidebar and its address. The heartbeat
   itself is a group of Settings, `/settings/heartbeat`, drawn by
   `heartbeatpage.js`. `WORK.id` is the quest's number, or '' for the list. */

var WORK = { open: false, id: '', title: '' };

function workViewing() { return WORK.open; }

/** @param {string|number} [id] a quest's number, or '' for every quest */
function workOpen(id) {
  if (ORBX.open) orbExpand(false);
  var want = id === undefined || id === null ? '' : String(id);
  var moved = WORK.open && WORK.id !== want;
  WORK.id = want;
  WORK.title = '';
  if (window.RouhWork) window.RouhWork.shown(WORK.id);
  if (WORK.open) {
    // Open already, but under another layer such as Anatomy: brought to the front, so a
    // link to it from that layer (the heartbeat's quests and questions) does something.
    if ($('workView').hidden || settingsViewing()) { showLayer('workView'); sidebarDone(); addrTouch(); }
    workRows();
    if (moved) addrTouch();
    return;
  }
  WORK.open = true;
  showLayer('workView');
  sidebarDone();
  workRows();
  if (!narrow()) $('workView').focus({ preventScroll: true });
}

function workClose() {
  if (!WORK.open) return;
  WORK.open = false;
  if (window.RouhWork) window.RouhWork.hidden();
  showLayer(null);
  workRows();
}

function workRows() {
  var row = $('questsRow');
  if (!row) return;
  row.classList.toggle('on', WORK.open);
  row.setAttribute('aria-expanded', WORK.open ? 'true' : 'false');
}

// What `questspage.js` is handed: opening and closing the layer, its title for
// the address bar, and an address in Rouh, such as a quest's own chat or task.
window.RouhWorkHost = {
  open: function (id) { workOpen(id); },
  close: workClose,
  rows: workRows,
  titled: function (title) {
    if (!WORK.open || WORK.title === title) return;
    WORK.title = title;
    addrTouch();
  },
  go: function (href) { goToAddress(href); }
};

(function () {
  var row = $('questsRow');
  if (!row) return;
  row.addEventListener('click', function () {
    if (WORK.open && !WORK.id) workClose(); else workOpen('');
  });
})();

/* ------------------------------------------------------------------ decisions

   Everything waiting on the person, from every part of Rouh that asks
   (`rouh/decisions.py`): every one at `/decisions`, one in focus at
   `/decisions/<id>`, drawn by `decisionspage.js`. This is the layer's side of
   it, as with the quests: opening and closing it, its row in the sidebar with
   the count of what waits (red when one is urgent), and its address.
   `DECIDE.id` is the one in focus, or ''. The count comes over the socket
   (`decisions`) and from the page's own first read. */

var DECIDE = { open: false, id: '', count: 0, now: 0 };

function decisionsViewing() { return DECIDE.open; }

/** @param {string|number} [id] one decision to put in focus, or '' for all of them */
function decisionsOpen(id) {
  if (ORBX.open) orbExpand(false);
  var want = id === undefined || id === null ? '' : String(id);
  var moved = DECIDE.open && DECIDE.id !== want;
  DECIDE.id = want;
  if (window.RouhDecisions) window.RouhDecisions.shown(DECIDE.id);
  if (DECIDE.open) {
    // Open already, but under another layer such as Anatomy: brought to the front, so a
    // link to it from that layer (the heartbeat's quests and questions) does something.
    if ($('decisionsView').hidden || settingsViewing()) { showLayer('decisionsView'); sidebarDone(); addrTouch(); }
    decisionsRows();
    if (moved) addrTouch();
    return;
  }
  DECIDE.open = true;
  showLayer('decisionsView');
  sidebarDone();
  decisionsRows();
  if (!narrow()) $('decisionsView').focus({ preventScroll: true });
}

function decisionsClose() {
  if (!DECIDE.open) return;
  DECIDE.open = false;
  if (window.RouhDecisions) window.RouhDecisions.hidden();
  showLayer(null);
  decisionsRows();
}

function decisionsRows() {
  var row = $('decisionsRow');
  if (!row) return;
  row.classList.toggle('on', DECIDE.open);
  row.classList.toggle('urgent', DECIDE.now > 0);
  row.setAttribute('aria-expanded', DECIDE.open ? 'true' : 'false');
  var hint = $('decisionsHint');
  if (hint) hint.textContent = DECIDE.count ? String(DECIDE.count) : '';
  // And on the navigation's Now tab, the one tab that carries a count.
  navNowCount(DECIDE.count, DECIDE.now > 0);
  row.title = DECIDE.count
    ? 'Decisions: ' + DECIDE.count + ' waiting on your answer' + (DECIDE.now ? ', ' + DECIDE.now + ' urgent' : '')
    : 'Decisions: everything waiting on your answer';
  var room = $('crDecisions');
  if (room) {
    room.hidden = !DECIDE.count;
    room.textContent = DECIDE.count === 1 ? '1 decision waiting' : DECIDE.count + ' decisions waiting';
    room.classList.toggle('urgent', DECIDE.now > 0);
  }
}

/** @param {{open?: number, now?: number}} m the `decisions` message: how many wait, and how many are urgent */
function decisionsHeard(m) {
  DECIDE.count = Number(m.open) || 0;
  DECIDE.now = Number(m.now) || 0;
  decisionsRows();
  if (window.RouhDecisions) window.RouhDecisions.moved();
}

// What `decisionspage.js` is handed: closing the layer, an address in Rouh to
// open a decision's context at, and the count it read.
window.RouhDecisionsHost = {
  open: function (id) { decisionsOpen(id); },
  close: decisionsClose,
  go: function (href) { goToAddress(href); },
  // In place of the address it is at: /decisions/42 opening the item's own page, so Back
  // goes to where the person was before, never to a page that forwards again.
  forward: function (href) { ADDR.replace = true; goToAddress(href); },
  counted: function (n, now) {
    DECIDE.count = n;
    DECIDE.now = now;
    decisionsRows();
  }
};

(function () {
  var row = $('decisionsRow');
  if (row) {
    row.addEventListener('click', function () {
      if (DECIDE.open && !DECIDE.id) decisionsClose(); else decisionsOpen('');
    });
  }
  var room = $('crDecisions');
  if (room) room.addEventListener('click', function () { decisionsOpen(''); });
})();

/* ------------------------------------------------------------------ receipts

   Every receipt and invoice in the person's mail, by month, with one download
   for the accountant (`rouh/receipts.py`), at `/receipts`, drawn by
   `receiptspage.js`. Built by the nightly feature run, night 4, 7 October 2026,
   behind the switch `receipts`: off, the server leaves its row out of the
   sidebar. This is the layer's side, as with the decisions. */

var RECEIPTS = { open: false };

function receiptsViewing() { return RECEIPTS.open; }

function receiptsOpen() {
  if (ORBX.open) orbExpand(false);
  if (RECEIPTS.open) return;
  RECEIPTS.open = true;
  showLayer('receiptsView');
  sidebarDone();
  receiptsRow();
  if (window.RouhReceipts) window.RouhReceipts.shown();
  if (!narrow()) $('receiptsView').focus({ preventScroll: true });
}

function receiptsClose() {
  if (!RECEIPTS.open) return;
  RECEIPTS.open = false;
  if (window.RouhReceipts) window.RouhReceipts.hidden();
  showLayer(null);
  receiptsRow();
}

function receiptsRow() {
  var row = $('receiptsRow');
  if (!row) return;
  row.classList.toggle('on', RECEIPTS.open);
  row.setAttribute('aria-expanded', RECEIPTS.open ? 'true' : 'false');
}

// What `receiptspage.js` is handed: closing the layer.
window.RouhReceiptsHost = { close: receiptsClose };

(function () {
  var row = $('receiptsRow');
  if (row) {
    row.addEventListener('click', function () {
      if (RECEIPTS.open) receiptsClose(); else receiptsOpen();
    });
  }
})();

/* ------------------------------------------------------------------ home

   The house itself, at `/home`, drawn by `homepage.js`: its lights first,
   through Philips Hue, and every other kind of device as a section of its own
   (`window.RouhHomeSections`). Opened from the house at the right hand end of
   the navigation's head, across from Rouh's name. Petar, 17 October 2026:
   "chat is not going to cut it. Very cumbersome. I need interface and quick
   access... a house icon in the top, right corner of the navigation, across
   from Rouh 'logo'". This is the layer's side, as with the receipts. */

var HOME = { open: false };

function homeViewing() { return HOME.open; }

function homeOpen() {
  if (ORBX.open) orbExpand(false);
  sidebarDone();
  // Open already, perhaps under Settings or a card lying over it (Back from Settings, the
  // house pressed again): those stand down and Home is what is on screen.
  if (HOME.open) { showLayer('homeView'); return; }
  HOME.open = true;
  showLayer('homeView');
  homeMark();
  if (window.RouhHome) window.RouhHome.shown();
  if (!narrow()) $('homeView').focus({ preventScroll: true });
}

function homeClose() {
  if (!HOME.open) return;
  HOME.open = false;
  if (window.RouhHome) window.RouhHome.hidden();
  showLayer(null);
  homeMark();
}

function homeMark() {
  var b = $('homeBtn');
  if (!b) return;
  b.classList.toggle('on', HOME.open);
  if (HOME.open) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
}

// What `homepage.js` is handed: closing the layer, and going to an address in Rouh.
window.RouhHomeHost = { close: homeClose, go: function (href) { goToAddress(href); } };

(function () {
  var b = $('homeBtn');
  if (b) b.addEventListener('click', function () { homeOpen(); });
})();

/* ------------------------------------------------------------------ mail approvals

   Every email and message Rouh stopped on for the person's decision, in its
   group's queue, and the latest after them (`rouh/mail_cases.py`), at
   `/mail/approvals`, under Now, drawn by `approvalspage.js`. A page of its own
   drawn by the server until 15 October 2026, when Petar asked for it inside
   Rouh with the orb: "It is not a setting page, it is content page"
   (fr_37cea76c6db3). One case, `/mail/case/<key>`, is this layer too: "every
   time I need to get on or off it, things relapse and I don't have my orb"
   (fr_7d4948ef128b). Its one page, the server's, is in a frame here
   (`approvalspage.js`, fr_65ed87c8685b). `APPROVALS.key` is that case, or ''
   for the list; `APPROVALS.name` who sent it, for the tab's title. This is the
   layer's side, as with the receipts. */

var APPROVALS = { open: false, key: '', name: '' };

function approvalsViewing() { return APPROVALS.open; }

/** @param {string} [key] one case to show, or '' for the list
    @param {string} [hash] the step of the case to open it at, such as #approval-2 */
function approvalsOpen(key, hash) {
  if (ORBX.open) orbExpand(false);
  var want = key ? String(key) : '';
  var moved = APPROVALS.open && APPROVALS.key !== want;
  if (APPROVALS.key !== want) APPROVALS.name = '';
  APPROVALS.key = want;
  if (APPROVALS.open) {
    if ((moved || hash) && window.RouhApprovals) window.RouhApprovals.shown(want, hash);
    if (moved) addrTouch();
    return;
  }
  APPROVALS.open = true;
  showLayer('approvalsView');
  sidebarDone();
  approvalsRow();
  if (window.RouhApprovals) window.RouhApprovals.shown(want, hash);
  if (!narrow()) $('approvalsView').focus({ preventScroll: true });
}

function approvalsClose() {
  if (!APPROVALS.open) return;
  APPROVALS.open = false;
  if (window.RouhApprovals) window.RouhApprovals.hidden();
  showLayer(null);
  approvalsRow();
}

function approvalsRow() {
  var row = $('approvalsRow');
  if (!row) return;
  row.classList.toggle('on', APPROVALS.open);
  row.setAttribute('aria-expanded', APPROVALS.open ? 'true' : 'false');
}

// What `approvalspage.js`, and a case's page in its frame (`mail_case.html`), are
// handed: closing the layer, going to an address inside Rouh (a case, the list,
// Trusted contacts), and the name of whoever sent the case on screen, for the
// tab's title.
window.RouhApprovalsHost = {
  close: approvalsClose,
  go: function (href) { goToAddress(href); },
  titled: function (name) {
    if (APPROVALS.name === name) return;
    APPROVALS.name = String(name || '');
    addrTouch();
  }
};

(function () {
  var row = $('approvalsRow');
  if (row) {
    row.addEventListener('click', function () {
      if (APPROVALS.open && !APPROVALS.key) approvalsClose(); else approvalsOpen('');
    });
  }
})();

/* ------------------------------------------------------------------ sources

   One task's footnoted pages, their sources read against what each page says
   they say (`rouh/source_check.py`), at `/sources/<the task's or step's
   folder>`, drawn by `sourcespage.js`. Built by the nightly feature run,
   night 10, 13 October 2026, behind the switch `source_check`.

   It is reached from the task, and only from there: the Sources section on a
   task's page (`objectindex._sources_section`) links each checked page to
   its folder's Sources. Petar took it out of the navigation the same day
   (fr_fce8f51c00d6): "Sources should not be in the main navigation, only in
   the sources of each task". */

var SOURCES = { open: false, folder: '', title: '', from: '' };

function sourcesViewing() { return SOURCES.open; }

/** @param {string} folder */
function sourcesOpen(folder) {
  folder = String(folder || '').replace(/^\/+|\/+$/g, '');
  if (!folder) return;
  if (ORBX.open) orbExpand(false);
  if (SOURCES.open && SOURCES.folder === folder) return;
  if (SOURCES.folder !== folder) SOURCES.title = '';
  // The task's page it was opened from, which its close goes back to.
  SOURCES.from = tasksViewing() ? taskPageFolder() : '';
  SOURCES.folder = folder;
  SOURCES.open = true;
  showLayer('sourcesView');
  sidebarDone();
  if (window.RouhSources) window.RouhSources.shown(folder);
  if (!narrow()) $('sourcesView').focus({ preventScroll: true });
}

function sourcesClose() {
  if (!SOURCES.open) return;
  SOURCES.open = false;
  if (window.RouhSources) window.RouhSources.hidden();
  showLayer(null);
}

// What `sourcespage.js` is handed: closing the layer, an address in Rouh to
// open a checked page at, at one of its sources, and the task's name once it
// knows it, for the tab's title.
window.RouhSourcesHost = {
  // Back to the task: the page it was opened from, or the folder's own page
  // for one opened by its address alone.
  close: function () {
    var back = SOURCES.from || SOURCES.folder;
    sourcesClose();
    if (back) goToAddress(addrOfFolder(back));
  },
  go: function (href) { goToAddress(href); },
  named: function (title) {
    SOURCES.title = String(title || '');
    if (SOURCES.open) addrTouch();
  }
};

/* ------------------------------------------------------------------ evolution

   Evolution (`rouh/evolution.py`), drawn by `evolutionpage.js`: Parameters at
   `/evolution/parameters`, how many genes a night the nightly run builds and of
   which kinds; Mutations at `/evolution/mutations`, with its views and one gene;
   and the Gene Pool at
   `/evolution/pool`. Petar, 13 October 2026, task 94 step 94-08; Mutations was the
   Gene library and the Pool one of its views until 14 October (fr_a982710d30c7).
   Every link is the registry's (`opens` address), so this is only the layer:
   opening it at a page, closing it, and the address it is at. */

var EVO = { open: false, page: 'mutations', sub: '', title: '' };

function evolutionViewing() { return EVO.open; }

/** Which of Evolution's pages a name is: Mutations unless it is one of the other two.
 * @param {string} page */
function evolutionPage(page) {
  return page === 'parameters' || page === 'pool' || page === 'incubator' || page === 'nightly' || page === 'trials' ? page : 'mutations';
}

/** @param {string} page 'parameters', 'mutations' or 'pool' @param {string} [sub] a view, a gene or a family */
function evolutionOpen(page, sub) {
  if (ORBX.open) orbExpand(false);
  var want = evolutionPage(page);
  var moved = EVO.open && (EVO.page !== want || EVO.sub !== (sub || ''));
  EVO.page = want;
  EVO.sub = want === 'parameters' || want === 'nightly' ? '' : String(sub || '');
  // A gene's name is the tab's title only while its page is open: going back to a list by its
  // link drops it, and the gene's page puts it back as it draws.
  if (moved) EVO.title = '';
  if (window.RouhEvolution) window.RouhEvolution.shown(EVO.page, EVO.sub);
  if (EVO.open) {
    if (moved) addrTouch();
    return;
  }
  EVO.open = true;
  showLayer('evolutionView');
  sidebarDone();
  if (!narrow()) $('evolutionView').focus({ preventScroll: true });
}

function evolutionClose() {
  if (!EVO.open) return;
  EVO.open = false;
  EVO.title = '';
  if (window.RouhEvolution) window.RouhEvolution.hidden();
  showLayer(null);
}

// What `evolutionpage.js` is handed: closing the layer, going to an address in
// Rouh, saying where inside the layer it now is (so the address follows), and
// putting a gene's words in the box where the person types to Rouh.
window.RouhEvolutionHost = {
  close: evolutionClose,
  // The Markdown drawing the conversation's own bubbles use, for the answers on a gene's card.
  markdown: renderMarkdown,
  go: function (href) { goToAddress(href); },
  /** @param {string} page @param {string} sub @param {string} [title] */
  moved: function (page, sub, title) {
    EVO.page = evolutionPage(page);
    EVO.sub = EVO.page === 'parameters' ? '' : String(sub || '');
    EVO.title = String(title || '');
    addrTouch();
  },
  /* The page and its conversation side by side: what the Incubator asks for after it opens its own chat,
     whose switch folds an empty chat's canvas away, and with it this layer (`incubatorpage.js`). */
  beside: function () {
    canvasIsWanted();
    chatIsWanted();
  },
  /** @param {string} text */
  compose: function (text) {
    var box = /** @type {HTMLTextAreaElement|null} */ ($('input'));
    if (!box) return false;
    evolutionClose();
    box.value = String(text || '');
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.focus();
    return true;
  }
};

/** The Incubator's list moved, from a tool in a chat (`rouh/tools.py`): an open Incubator page draws it
 * again, and asked to show it, the page opens, at the idea when one is named.
 * @param {import('./protocol').FromServer<'incubator_changed'>} m */
function incubatorHeard(m) {
  if (m.open) goToAddress('/evolution/incubator' + (m.number ? '/INC-' + m.number : '') + location.search);
  var page = /** @type {any} */ (window).RouhIncubator;
  if (page && page.heard) page.heard();
}

/* ------------------------------------------------------------------ thoughts

   The person's own thoughts, kept in their words (`rouh/thoughts.py`): every
   one at `/thoughts`, newest first by month, and one in focus at
   `/thoughts/<its number>`, drawn by `thoughtspage.js`. Petar, 12 October
   2026: a thought he wants kept was a note found only by search, and "that is
   exactly what I was interested in getting solved". This is the layer's side,
   as with the decisions: opening and closing it, its row in the sidebar with
   how many are kept, and its address. The count comes over the socket
   (`thoughts`), on connect and whenever one is kept or changed. */

var THOUGHTS = { open: false, id: '', kept: 0 };

function thoughtsViewing() { return THOUGHTS.open; }

/** @param {string|number} [id] one thought to put in focus, or '' for all of them */
function thoughtsOpen(id) {
  if (ORBX.open) orbExpand(false);
  var want = id === undefined || id === null ? '' : String(id);
  var moved = THOUGHTS.open && THOUGHTS.id !== want;
  THOUGHTS.id = want;
  if (window.RouhThoughts) window.RouhThoughts.shown(THOUGHTS.id);
  if (THOUGHTS.open) {
    thoughtsRow();
    if (moved) addrTouch();
    return;
  }
  THOUGHTS.open = true;
  showLayer('thoughtsView');
  sidebarDone();
  thoughtsRow();
  if (!narrow()) $('thoughtsView').focus({ preventScroll: true });
}

function thoughtsClose() {
  if (!THOUGHTS.open) return;
  THOUGHTS.open = false;
  if (window.RouhThoughts) window.RouhThoughts.hidden();
  showLayer(null);
  thoughtsRow();
}

function thoughtsRow() {
  var row = $('thoughtsRow');
  if (!row) return;
  row.classList.toggle('on', THOUGHTS.open);
  row.setAttribute('aria-expanded', THOUGHTS.open ? 'true' : 'false');
  var hint = $('thoughtsHint');
  if (hint) hint.textContent = THOUGHTS.kept ? String(THOUGHTS.kept) : '';
}

// How many are kept, and that the list moved: the row's count, and the page
// read again when it is open.
/** @param {import('./protocol').FromServer<'thoughts'>} m */
function thoughtsHeard(m) {
  THOUGHTS.kept = Number(m.kept) || 0;
  thoughtsRow();
  if (window.RouhThoughts) window.RouhThoughts.moved();
}

// Rouh kept one in this conversation, or was asked to show them. Asked to
// show them, the page opens at a desk, as Clockwork does; kept, or on a
// phone, or over a page being read, a note says so with Open.
/** @param {import('./protocol').FromServer<'thoughts_shown'>} m */
function thoughtsShown(m) {
  if (m.chat && CHATS && m.chat !== CHATS.active) return;
  var id = m.id ? String(m.id) : '';
  var open = function () {
    thoughtsOpen(id);
    if (window.RouhThoughts && (m.q || m.tag)) window.RouhThoughts.find(m.q || '', m.tag || '');
  };
  var layer = layerOpen();
  if (m.open && !narrow() && (!layer || layer === 'thoughtsView')) {
    open();
    return;
  }
  if (THOUGHTS.open && !m.open) {
    // The page is up already, and draws the new one at the top.
    if (window.RouhThoughts) window.RouhThoughts.flash(id);
    return;
  }
  var what = typeof m.what === 'string' && m.what.trim() ? m.what.trim() : 'Your thoughts.';
  notify(what, { tone: 'success', kind: 'reminder',
                 action: { label: id ? 'Open the thought' : 'Open thoughts', run: open }, for: 15000 });
}

// What `thoughtspage.js` is handed: closing the layer, putting one thought in
// focus, an address in Rouh to go to (the chat a thought was said in), and
// the count it read.
window.RouhThoughtsHost = {
  close: thoughtsClose,
  focus: function (id) { thoughtsOpen(id); },
  go: function (href) { goToAddress(href); },
  counted: function (kept) {
    THOUGHTS.kept = kept;
    thoughtsRow();
  }
};

(function () {
  var row = $('thoughtsRow');
  if (row) {
    row.addEventListener('click', function () {
      if (THOUGHTS.open && !THOUGHTS.id) thoughtsClose(); else thoughtsOpen('');
    });
  }
})();

/* ------------------------------------------------------------------ box

   The box (`rouh/boxes.py`): somewhere to put words the model never sees, at
   `/box`, drawn by `boxpage.js`. Petar, 13 October 2026: "I want to be able
   to say give me a box and save something there so LLM doesn't see it." This
   is the layer's side: opening it with an empty box ready (`box_open`, sent
   when he asks for one), closing it, its row and its address, and putting an
   idea he chooses to give Rouh into the message box. */

var BOX = { open: false, id: '' };

function boxViewing() { return BOX.open; }

/**
 * @param {boolean} [fresh] an empty box at the top, focused, to type or paste into
 * @param {string} [id] one box's number to put in focus, from `/box/<n>`
 */
function boxOpen(fresh, id) {
  if (ORBX.open) orbExpand(false);
  var want = fresh ? '' : String(id || '');
  var moved = BOX.open && BOX.id !== want;
  BOX.id = want;
  if (window.RouhBox) window.RouhBox.shown(!!fresh, want);
  if (BOX.open) {
    if (moved) addrTouch();
    return;
  }
  BOX.open = true;
  showLayer('boxView');
  sidebarDone();
  boxRow();
  if (!narrow() && !fresh) $('boxView').focus({ preventScroll: true });
}

function boxClose() {
  if (!BOX.open) return;
  BOX.open = false;
  if (window.RouhBox) window.RouhBox.hidden();
  showLayer(null);
  boxRow();
}

function boxRow() {
  var row = $('boxRow');
  if (!row) return;
  row.classList.toggle('on', BOX.open);
  row.setAttribute('aria-expanded', BOX.open ? 'true' : 'false');
}

// He asked for a box, in this conversation: the page opens with one ready,
// at a desk and on a phone alike, because asking for it is asking to see it.
/** @param {import('./protocol').FromServer<'box_open'>} m */
function boxShown(m) {
  if (m.chat && CHATS && m.chat !== CHATS.active) return;
  boxOpen(true);
}

// A box was saved, changed, deleted or given to Rouh, here or on another
// screen of theirs: an open Boxes page reads them again.
/** @param {import('./protocol').FromServer<'boxes'>} m */
function boxesHeard(m) {
  if (window.RouhBox && m) window.RouhBox.moved();
}

// What `boxpage.js` is handed: closing the layer, a note on the screen, and
// an idea he chose to give Rouh, put into the message box for him to send
// when he chooses. Nothing is sent from here.
window.RouhBoxHost = {
  close: boxClose,
  focus: function (id) { boxOpen(false, id); },
  go: function (href) { goToAddress(href); },
  say: function (text, tone) { notify(text, { tone: tone }); },
  give: function (text) {
    boxClose();
    if (narrow()) setPane('chat');
    var was = input.value.trim();
    input.value = was ? was + '\n\n' + text : text;
    growInput();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
};

(function () {
  var row = $('boxRow');
  if (row) {
    row.addEventListener('click', function () {
      if (BOX.open && !BOX.id) boxClose(); else boxOpen(false);
    });
  }
})();

// What `heartbeatpage.js`, `paymentspage.js` and `draftedits.js` are handed: an address in
// Rouh, such as the Heartbeat chat or a quest's page.
window.RouhHeartbeatHost = {
  go: function (href) { goToAddress(href); },
  /* The heartbeat's own view, which the address says (`/anatomy/behaviour/heartbeat/settings`,
     or the section alone for Today), moved to without a reload. */
  viewed: function (view) {
    var now = view === 'settings' ? 'settings' : '';
    if (!sectionShows('heartbeat') || SETTINGS.heartbeat === now) return;
    SETTINGS.heartbeat = now;
    SETTINGS.section = 'heartbeat';
    addrTouch();
  }
};

// What `statspage.js` is handed: which of its tabs shows, which the address
// says (`/settings/stats/events`, or `/settings/stats` for the navigation's).
window.RouhStatsHost = {
  tabbed: function (tab) {
    var now = tab === 'events' ? 'events' : '';
    if (!sectionShows('stats') || SETTINGS.stats === now) return;
    SETTINGS.stats = now;
    SETTINGS.section = 'stats';
    addrTouch();
  }
};

/* What Rouh Land Account, Gene Pool is handed (`genespage.js`): going to a gene's own page, or back to the list. */
window.RouhGenesHost = {
  go: function (href) { goToAddress(href); }
};

/* What `beatspage.js` is handed: an address in Rouh, and where its table is, which the address
   says: the quest it is filtered to in the path (`/anatomy/behaviour/beats/<work>`) and the rest
   in the query. A search being typed replaces the entry rather than adding one a letter. */
window.RouhBeatsHost = {
  go: function (href) { goToAddress(href); },
  filtered: function (work, query, typing) {
    var now = work && work !== 'all' ? String(work) : '';
    var q = String(query || '');
    if (!sectionShows('beats') || (SETTINGS.beats === now && SETTINGS.beatsQuery === q)) return;
    SETTINGS.beats = now;
    SETTINGS.beatsQuery = q;
    SETTINGS.section = 'beats';
    if (typing) ADDR.replace = true;
    addrTouch();
  }
};

/* ---- wiring ---- */

(function () {
  if (!$('remindersView')) return;
  $('remindersRow').addEventListener('click', function () {
    if (remindersViewing()) remindersClose(); else remindersOpen();
  });
  $('goalsRow').addEventListener('click', function () {
    if (goalsViewing()) goalsClose(); else goalsOpen();
  });
  $('remindersClose').addEventListener('click', remindersClose);
  $('goalsClose').addEventListener('click', goalsClose);
  $('remindersNew').addEventListener('click', function () { remindersEdit(null); });
  $('goalsNew').addEventListener('click', function () { goalsEdit(); });
  $('goalsBack').addEventListener('click', function () {
    goalsFormDone();
    goalsLoad();
    $('goalsNew').focus();
  });
  $('remindersForm').addEventListener('submit', remindersSave);
  $('remindersWhat').addEventListener('input', function () {
    CLOCK.rOwn.typed = true;
    remindersReadSoon();
  });
  // One sentence is the whole of it, so Enter saves (Shift+Enter is a new line).
  $('remindersWhat').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    $('remindersForm').requestSubmit();
  });
  // A field set by hand is the person's, and the words leave it alone.
  [['remindersTitle', 'title'], ['remindersDetails', 'details']].forEach(function (pair) {
    $(pair[0]).addEventListener('input', function () { CLOCK.rOwn[pair[1]] = true; });
  });
  [['remindersDate', 'date'], ['remindersTime', 'time'], ['remindersRepeat', 'repeat']]
    .forEach(function (pair) {
      $(pair[0]).addEventListener('input', function () {
        CLOCK.rOwn[pair[1]] = true;
        remindersNeeds(CLOCK.rRead ? CLOCK.rRead.missing || [] : []);
      });
    });
  $('goalsForm').addEventListener('submit', goalsSave);
  // Put away, and read again: whatever changed while the form was open was
  // held back from the list so as not to redraw under the fields.
  $('remindersCancel').addEventListener('click', function () {
    remindersFormDone();
    remindersLoad();
    $('remindersNew').focus();
  });
  $('goalsCancel').addEventListener('click', function () {
    goalsFormDone();
    goalsLoad();
    $('goalsNew').focus();
  });
  Array.prototype.forEach.call(document.querySelectorAll('input[name="rkind"]'), function (r) {
    r.addEventListener('change', function () { CLOCK.rOwn.kind = true; remindersHelp(); });
  });
  $('remindersRouh').addEventListener('change', function () { CLOCK.rOwn.rouh = true; });
  $('remindersRepeat').addEventListener('change', function () {
    if ($('remindersRepeat').value === 'weekly' && !CLOCK.days.length) {
      var d = new Date($('remindersDate').value + 'T12:00');
      if (!isNaN(d.getTime())) CLOCK.days = [CLOCK_DAYS[(d.getDay() + 6) % 7][0]];
    }
    remindersDaysDraw();
  });
  // Escape inside a form puts the form away rather than closing the page.
  ['remindersForm', 'goalsForm'].forEach(function (id) {
    $(id).addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      $(id === 'remindersForm' ? 'remindersCancel' : 'goalsCancel').click();
    });
  });
})();

oneConnect();

export { applyObjects, applyWorkspace, ASK, askDelete, askFromPage, BRIEF, briefClose, briefOpen,
  WORK, workClose, workOpen, workViewing,
  DECIDE, decisionsClose, decisionsHeard, decisionsOpen, decisionsViewing,
  receiptsClose, receiptsOpen, receiptsViewing, HOME, homeClose, homeOpen, homeViewing, SOURCES, sourcesClose, sourcesOpen, sourcesViewing,
  APPROVALS, approvalsClose, approvalsOpen, approvalsViewing,
  EVO, evolutionClose, evolutionOpen, evolutionViewing, incubatorHeard,
  THOUGHTS, thoughtsClose, thoughtsHeard, thoughtsOpen, thoughtsShown, thoughtsViewing, settingsShown,
  BOX, boxClose, boxesHeard, boxOpen, boxShown, boxViewing,
  briefViewing, BROWSE_ROOT, browseGo, browserZone, CANVAS, canvasChatsFollow, canvasDoc,
  canvasLeftBehind, canvasLoad, canvasMessage, canvasOn, canvasStep, canvasStepPage, canvasTask,
  cardWasFiled, CLOCK, clockHeard, clockLoad, clockPost, clockShown, controlClose, controlOpen,
  controlViewing, copyText, CRUMB_HOME, crumbLevels, delPlanned, drawCrumb, drawUnder,
  goalsClose, goalsOpen, goalsTake, goalsViewing, goNow, growToLines, locFind, locPermission,
  memoryAddress, memoryClose, memoryHeard, memoryOpen, memoryViewing, MEMORY, modelsLoad, movedTell, moveOpen, moveSend, askTaskName, OBJ, ONE, oneClose,
  oneIsOpen, oneOpen, oneOwnerPaint, oneViewing, openOwner, openTaskThread, openUnder,
  ownerWords, pageUrl, pinMark, pinnedRuns, POLICY_MEANS, projectById, projectParts,
  projectsClose, projectsOpen, projectsViewing, railChats, railName, remindersClose,
  remindersOpen, remindersViewing, renderProjects, renderThreads, ROWMENU, rowMenuShow,
  rowsFollowSidebar, runHosts, runKind, runsClose, runsInTab, runsOpen, RUNSVIEW, runsTab,
  runsViewing, SETTINGS, settingsAddress, settingsClose,
  settingsGroupName, settingsOpen, settingsRead, settingsViewing, sharePanelOpen, tcAddAsked, SHARES, sharesClose,
  SYNAPSE, synapseClose, synapseOpen, synapseViewing, TASK_PREFIX, TASKS, TASKS_VIEW,
  tasksClose, tasksFrame, tasksOpen, tasksUp, tasksViewing, taskUrl, taskWords, TC, tcPerson,
  threadName, threadUnread, whenWords, wsProjects };
