/* Rouh's page, tasks, and one of Rouh's own jobs on the canvas (sections 10 and 10a of what was one app.js).
 *
 * Imports app/cards.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { goToAddress, showConflictCard, showLayer, svgEl } from 'app/cards.js';
import { $, el, linkTo, now } from 'app/helpers.js';
import { load, store } from 'app/settings.js';
import { notify } from 'app/notices.js';
import { send } from 'app/socket.js';
import { orbExpand, ORBX } from 'app/orb.js';
import { oneIsOpen, oneOpen, oneOwnerPaint, openOwner, ownerWords, pinMark, pinnedRuns,
  renderProjects, ROWMENU, rowMenuShow, runHosts, runKind, runsInTab, RUNSVIEW, runsViewing,
  threadUnread } from 'app/runs.js';
import { chatById, CHATS } from 'app/chats.js';
import { runsArrived } from 'app/search.js';
import { addrOf, addrPlaceLink, addrTouch } from 'app/address.js';
import { narrow, sidebarDone } from 'app/controls.js';

/* ----------------------------------------------------------------- 10 */

/* The background jobs.
 *
 * Two messages carry them and they are not interchangeable. `tasks` is the
 * whole list, read from the database, and arrives with `ready` and again
 * whenever anything changes. `task` is one job announcing a change, and it
 * carries fields the list does not - the question it stopped to ask. So one
 * is merged into the other, keyed by id, and nothing is ever removed: a card
 * that vanishes is a job you stop looking for.
 */

/* What each status means to somebody who did not start the job.
 *
 * `idle` and `done` are two different things and were one word until
 * 22 September 2026. A run of the one program that has finished its turn is
 * still open: its terminal is alive, its checkout is where it left it, and
 * it is waiting at its prompt for the next thing said to it, until a person
 * closes it (D49). `done` is a run that is over. Calling both of them Done
 * is how six open runs came to read as six finished ones. */
var TASK_WORDS = {
  starting: 'Starting',
  running: 'Working',
  // A run of the one program whose turn is over, at its prompt, while the program lands
  // and deploys its work. It was called Working until 12 October 2026, which said a run at
  // its prompt was working (MAIL.md, D17).
  saving: 'Saving its work',
  waiting: 'Needs you',
  idle: 'Finished its turn',
  done: 'Done',
  // A job whose worker ended without ever saying how it went. It was "Lost"
  // and a grey card until 24 September 2026, which read as quiet rather
  // than as broken: see `taskCard`.
  lost: 'Died',
  killed: 'Stopped',
  // A run of the one program stopped at its time limit (one/scheduler.py).
  reaped: 'Cleaned up',
  failed: 'Failed'
};
var TASK_MEANS = {
  starting: 'Just launched.',
  running: 'Working now.',
  saving: 'It finished its turn and is at its prompt; its work is being landed on main and deployed.',
  waiting: 'It has stopped and is asking a question.',
  idle: 'It is at its prompt and still open. Send it a message to carry it on.',
  done: 'It is over.',
  lost: 'It died without reporting how it went.',
  killed: 'Stopped on purpose.',
  reaped: 'Stopped by cleanup: its Claude Code reached the time limit, and everything it started was closed with it.',
  failed: 'Ended badly.'
};

var taskRecs = Object.create(null);
var taskSeen = 0;

function taskKey(status) { return String(status || '').toLowerCase(); }

function taskClass(status) {
  var s = taskKey(status);
  if (TASK_WORDS[s]) return 's-' + s;
  // A status nobody here has seen still deserves a colour.
  if (/(done|complete|finished|ok|success)/.test(s)) return 's-done';
  if (/(fail|error|cancel)/.test(s)) return 's-failed';
  if (/(run|work|progress|start)/.test(s)) return 's-running';
  return 's-starting';
}

/* Whether a run has **stopped**, which is the whole of what the red dot on
 * the rail's Runs tab means. Asking a question, ended badly, lost its
 * window, sitting open at its prompt, or over: all of those are stopped,
 * because all of them are something for the person to go and look at.
 *
 * `s-idle` counts because a run that has finished its turn has not finished:
 * it is still open, its terminal is still there, and it is waiting to be
 * carried on or closed.
 *
 * Named the other way round - the two that are going, rather than the six
 * that have stopped - because `taskClass` answers `s-starting` for a status
 * this page has never heard of, and a word nobody has taught it yet should
 * not start putting dots on the rail on its own.
 */
var RUN_GOING = ['s-starting', 's-running', 's-saving'];

function runStopped(rec) {
  return !!rec && RUN_GOING.indexOf(taskClass(rec.status)) < 0;
}

/* And of a task there is no such function here, on purpose. A task stops
   when its state is waiting or done, and a **step** never stops at all -
   it is the record of work already done, so what finishes it is its page
   being written. Both are one question, and the server answers it on every
   row it sends: `new` (`owning._ready_at`, `objects.STOPPED`). A second
   copy of half the rule on this side is a second copy to fall behind. */

function taskWord(status) {
  var s = taskKey(status);
  if (TASK_WORDS[s]) return TASK_WORDS[s];
  if (!s) return 'Queued';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// "4 min ago". Times arrive as ISO strings and may be missing.
function ago(iso) {
  if (!iso) return '';
  var t = Date.parse(iso);
  return isFinite(t) ? since(t) : '';
}

function since(t) {
  var s = (now() - t) / 1000;
  if (s < 0) s = 0;
  if (s < 45) return 'just now';
  if (s < 90) return '1 min ago';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 5400) return '1 hour ago';
  if (s < 86400) return Math.round(s / 3600) + ' hours ago';
  if (s < 172800) return 'yesterday';
  return Math.round(s / 86400) + ' days ago';
}

var TASK_FIELDS = ['model', 'actual_model','title', 'status', 'mode', 'created_at', 'updated_at',
  'finished_at', 'exit_code', 'repo', 'branch', 'detail', 'asking', 'options',
  // What it was for, in one sentence written from its brief as it began,
  // which a green card shows in place of `detail` (`rouh/runsummary.py`).
  'summary',
  // Which tab of Metabolism it is on: 'mutation', a run that changes Rouh
  // itself, or 'everyday' (`runs.kind_of`).
  'kind',
  // The conflict its work is stuck on, and the card that decides it. Only a
  // person can move one of these, so its row is red rather than amber.
  'conflict', 'card_id',
  // A run of the one program carries two more: whether the person has put it
  // out of the way, and whether its terminal session is open right now.
  'archived', 'terminal',
  // And the person's own mark, which is the other thing entirely: archiving
  // puts a run away, pinning keeps it at the top of the column.
  'pinned',
  // Whether they have looked at this run since it stopped. The red dot on
  // the Metabolism link counts the ones that have stopped and are not seen, and
  // the register clears this again every time a run stops afresh.
  'seen',
  // Rouh deploying itself carries one more. There is no terminal behind
  // that row and no checkout to leave alone, so its button throws the card
  // away rather than filing it: see self_update.py.
  'dismiss',
  // Who owns this run, or null when nobody does, which is the default and
  // what every run starts as (rouh/owning.py). Null is a real answer here
  // and not a missing field, so it is merged on its own below.
  'owned_by',
  // A job that died, and what became of that: whether its card can start
  // it again, and the job that did, once one has (`runtime._how_the_dead_restart`).
  'restartable', 'restarted_as',
  // The conversation it was started from, which its report goes into, or ""
  // for a run no conversation started (`runs.report_chat`). Its card has a
  // button to it (`chatButton`).
  'chat',
  // And the project the chain above it ends in, or "" for a run in none.
  // A run under a task under Acme is in Acme and nobody filed it
  // there, which is why this is walked on the server rather than read off
  // the owner: it is what the runs list groups by (`owning.decorate`).
  'project_id'];

//: Fields whose null means null. Everything else in TASK_FIELDS leaves what
//: is already known alone when a message does not carry it, because `tasks`
//: and `task` each carry half the truth; an owner taken away is the one
//: thing that has to be able to arrive as nothing.
var TASK_NULLABLE = { owned_by: true };

function mergeTask(m) {
  var id = (m && m.id != null && m.id !== '') ? String(m.id) : ('t' + (taskSeen + 1));
  var rec = taskRecs[id];
  // `at` is when this browser first heard of the job, and it is written once
  // and never again: it stands in for a start time the message did not carry,
  // and a stand-in that moved would move the row with it.
  if (!rec) {
    taskSeen++;                      // only to name the next job that has no id
    rec = taskRecs[id] = { id: id, at: now() };
  }
  // A field the message does not carry leaves the one already known alone.
  // That is the whole merge: `tasks` has no question in it, `task` has no
  // created_at, and both are true at once.
  for (var i = 0; i < TASK_FIELDS.length; i++) {
    var k = TASK_FIELDS[i];
    if (m[k] === undefined) continue;
    if (m[k] === null && !TASK_NULLABLE[k]) continue;
    rec[k] = m[k];
  }
  return rec;
}

// When a job started, which is the only thing this column is ordered by.
// Not when it last did something: that used to be the order, and it meant
// the list rearranged itself while the person was reading it. A job with no
// start time on it falls back to when this browser first saw it.
function taskStart(rec) {
  var t = Date.parse(rec.created_at || '');
  return isFinite(t) ? t : (rec.at || 0);
}

// Newest started at the top, oldest at the bottom. Two jobs started in the
// same millisecond are separated by their id, so they never swap either.
function byStart(a, b) {
  var d = taskStart(b) - taskStart(a);
  if (d) return d;
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

// The box a job or a run goes into, or comes back out of. Putting one away
// stops it: the terminal behind it is closed, and only its folder is left
// alone. Bringing it back is the flag alone and starts nothing.
function archiveIcon(archived) {
  var svg = svgEl('svg', { viewBox: '0 0 24 24', width: '13', height: '13', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round' });
  svg.setAttribute('aria-hidden', 'true');
  svg.appendChild(svgEl('rect', { x: '3', y: '4', width: '18', height: '4', rx: '1' }));
  svg.appendChild(svgEl('path', { d: 'M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8' }));
  // A line on the box to put it away; an arrow out of it to bring it back.
  svg.appendChild(svgEl('path', { d: archived ? 'M12 17.5V12' : 'M10 13h4' }));
  if (archived) svg.appendChild(svgEl('path', { d: 'M9.5 14.5 12 12l2.5 2.5' }));
  return svg;
}

// What a row is called in the button's words: a run of the one program, or
// one of Rouh's own background jobs.
function taskNoun(rec) { return rec.mode === 'one' ? 'run' : 'job'; }

// A speech bubble, for the chat a run was asked in.
function chatIcon() {
  var svg = svgEl('svg', { viewBox: '0 0 24 24', width: '13', height: '13', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round' });
  svg.setAttribute('aria-hidden', 'true');
  svg.appendChild(svgEl('path', { d: 'M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z' }));
  return svg;
}

/* The chat a run was started from, where its report goes when it finishes.
 * Petar, 12 October 2026: "A run that was started through a chat should pass
 * the chat id. So that when the run completes the chat receives the report
 * and the notification has a link to the chat too." The dot on this card is
 * that notification on the Runs list, so the card leads to the chat as well
 * as to the run. Only on a run some conversation started: the rest have no
 * chat, and keep their report on the run. */
function chatButton(rec) {
  var chat = chatById(rec.chat);
  var name = rec.chat === CHATS.general ? 'General' : (chat && chat.title) || 'its chat';
  var b = el('button', 'icon-btn tiny task-act task-chat');
  b.type = 'button';
  b.setAttribute('data-act', 'chat');
  b.title = 'Open the chat it was asked in: ' + name;
  b.setAttribute('aria-label', 'Open the chat the ' + taskNoun(rec) + ' was asked in: ' + name);
  b.appendChild(chatIcon());
  return b;
}

// A bin, for the row that has nothing behind it to keep.
function trashIcon() {
  var svg = svgEl('svg', { viewBox: '0 0 24 24', width: '13', height: '13', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round',
    'stroke-linejoin': 'round' });
  svg.setAttribute('aria-hidden', 'true');
  svg.appendChild(svgEl('path', { d: 'M4 7h16' }));
  svg.appendChild(svgEl('path', { d: 'M9.5 7V5.2a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7' }));
  svg.appendChild(svgEl('path', { d: 'M6.5 7v12a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V7' }));
  svg.appendChild(svgEl('path', { d: 'M10.5 11v5' }));
  svg.appendChild(svgEl('path', { d: 'M13.5 11v5' }));
  return svg;
}

function archiveButton(rec) {
  var want = !rec.archived;
  var noun = taskNoun(rec);
  var b = el('button', 'icon-btn tiny task-act');
  b.type = 'button';
  // What the click means is written on the button rather than closed over
  // by a listener, because the click is caught on the column: see below.
  b.setAttribute('data-act', rec.dismiss ? 'dismiss' : (want ? 'archive' : 'unarchive'));
  if (rec.dismiss) {
    b.title = 'Dismiss this card';
    b.setAttribute('aria-label', 'Dismiss the card: ' + (rec.title || rec.id));
    b.appendChild(trashIcon());
    return b;
  }
  b.title = want ? 'Archive this ' + noun : 'Unarchive';
  b.setAttribute('aria-label', (want ? 'Archive the ' + noun + ': ' : 'Unarchive the ' + noun + ': ')
    + (rec.title || rec.id));
  b.appendChild(archiveIcon(!!rec.archived));
  return b;
}

/* And the three dots beside it, which are the other thing entirely.
 *
 * Archiving puts a run out of the way and keeps it. The menu behind these
 * dots is the same one every row of the sidebar's three lists carries: pin
 * this run so it sits at the top of the column, edit what it is called, or
 * delete it - with its sub-agents, its diff and everything it owns, and the
 * confirmation counting them first. A run still going is stopped before its
 * record goes, because a record deleted out from under a live agent orphans
 * it. The cross that used to be here is the menu's third item.
 *
 * What the press means is on the button as `data-act`, like the archive
 * beside it, because the click is caught on the column and not on the card:
 * the whole column is rebuilt on every `tasks` message, and a listener added
 * to a card is a listener on a node that may already have been thrown away.
 * The card with nothing behind it keeps its bin and no menu - there is no
 * run to pin, rename or delete, only a card to dismiss.
 */
function taskDots(rec) {
  var b = el('button', 'icon-btn tiny task-act row-dots', '\u22ef');
  b.type = 'button';
  b.setAttribute('data-act', 'menu');
  b.setAttribute('aria-haspopup', 'menu');
  b.setAttribute('aria-expanded', 'false');
  b.setAttribute('aria-controls', 'rowMenu');
  // The address of the row, so the menu and the rename field can find it
  // again after this column has been rebuilt under them, which it is on
  // every `tasks` message.
  b.setAttribute('data-row', 'run:' + rec.id);
  b.title = 'What to do with this ' + taskNoun(rec) + ': pin it, rename it, delete it';
  b.setAttribute('aria-label', 'What to do with the ' + taskNoun(rec) + ': '
    + (rec.title || rec.id));
  return b;
}

// Every row on the list archives, and the page always asks Rouh. A run of
// the one program keeps its flag in the program, beside the run, and Rouh
// passes the press on over its own connection, which the program has
// paired; every other job keeps it in Rouh's database. Whoever holds it
// stops the work first if it is still going, and says so again to every
// tab with the new status on it, which is what turns the card from running
// to stopped.
//
// It used to go from this page straight to the program, which only answers
// a browser it has been paired with. A phone that had never been paired
// could see every run and archive none of them: the press put "The one
// program has not let this browser in" over the list and the run stayed
// where it was (fr_e40fdd64f4a8, 1 October 2026). Putting a run away needs
// no terminal, so it needs no pairing.
function archiveTask(rec, want) {
  function moved() {
    // Whoever holds the flag says so again to every tab; this is only so
    // the column answers the click at once. Putting a run away is looking
    // at it, so the red dot goes with it in the same instant; the register
    // writes that mark down itself, wherever the flag is kept
    // (`objects.update_run`), and says so again on the next list.
    mergeTask({ id: rec.id, archived: want, seen: want || rec.seen });
    // And the dot this visit had put on its card, because putting a run away
    // is deciding about it: a card carried back into view by "Show archived"
    // wearing a dot would be asking again about the one thing they answered.
    if (want) delete runsFlagged[rec.id];
    renderTasks();
  }
  if (send({ type: 'archive_task', id: rec.id, on: want })) moved();
  else notify('Rouh is not connected.', { tone: 'error' });
}

/* Every click in the column is caught here, on the column itself.
 *
 * It used to be a listener per card, added while the card was being built.
 * The whole column is rebuilt from scratch on every `tasks` message, so the
 * node under the person's finger between pressing and releasing could be a
 * node that had already been thrown away, and the click they made landed on
 * nothing. That is what made the trash button on a stuck "Updating Rouh"
 * card look dead: the card was being redrawn under it. The column outlives
 * every card in it, so the listener lives there and the card is found from
 * the event.
 */
function taskFrom(node) {
  var card = node && node.closest ? node.closest('.task') : null;
  var id = card ? card.getAttribute('data-id') : null;
  return id ? taskRecs[id] : null;
}

// What the click means is on the button as `data-act`, and that attribute is
// what this looks for rather than a class: `.task-act` is the square icon
// button's look - 22 by 22 - and the owner on a row is words, not an icon.
// A contract carried by a style was a contract the next control broke.
function onTaskClick(e) {
  var rec = taskFrom(e.target);
  if (!rec) return;
  var act = e.target.closest ? e.target.closest('[data-act]') : null;
  if (act) { taskAct(act.getAttribute('data-act'), rec, act, e); return; }
  openTask(rec);
}

function onTaskKey(e) {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  // A button turns Enter and space into a click of its own, and that click
  // comes through here too. Acting on the key as well would open the row
  // behind the button that was just pressed.
  if (e.target.closest && e.target.closest('[data-act]')) return;
  var rec = taskFrom(e.target);
  if (!rec) return;
  if (e.preventDefault) e.preventDefault();
  openTask(rec);
}

function taskAct(what, rec, b, e) {
  if (what === 'own') { openOwner('run', rec.id, rec.title || rec.id, taskNoun(rec)); return; }
  // A job that died: start it again, or go to the job that did.
  if (what === 'restart') { restartTask(rec); return; }
  if (what === 'restarted') { jobGo(rec.restarted_as); return; }
  if (what === 'dismiss') { dismissTask(rec); return; }
  // Its chat, where its report is: reading the report is looking at the run,
  // so the dot on its card goes out on the way, as opening the run puts it out.
  if (what === 'chat') { runLooked(rec); goToAddress('/chat/' + encodeURIComponent(rec.chat)); return; }
  // The dot on the card, pressed. It puts itself out and opens nothing,
  // which is the literal answer to "what do I have to click to make it
  // disappear" that every other dot in this column already gives.
  if (what === 'looked') { runLooked(rec); return; }
  if (what === 'menu') {
    // Pressing the dots that already have it open closes it again, which is
    // what a person expects of the button that opened one.
    if (ROWMENU.dots === b) { rowMenuShow(false); return; }
    rowMenuShow(true, { kind: 'run', id: rec.id, label: rec.title || rec.id,
                        title: rec.title || '', pinned: !!rec.pinned }, b);
    // From the keyboard, into it, as from the dots on every row (`rowDots`).
    if (e && !e.detail) RouhMenu.first($('rowMenu'));
    return;
  }
  archiveTask(rec, what !== 'unarchive');
}

// A card for something nobody is keeping: it goes from this tab at once and
// the server is told to drop it, so it is gone from the other tabs too and
// does not come back on the next snapshot. Nothing here waits to be told it
// may go. A row the person has dismissed must never still be there because
// the socket was busy, and this is the row they most want rid of.
function dismissTask(rec) {
  delete taskRecs[rec.id];
  delete runsFlagged[rec.id];
  renderTasks();
  if (!send({ type: 'archive_task', id: rec.id, on: true })) {
    notify('Rouh is not connected, so that card may come back when it is.', { tone: 'error' });
  }
}

// Every row answers a click, and there are two things that can mean. A run
// of the one program opens where the cards are (D45); every other row opens
// in place, under the line it already shows. Until 19 September 2026 only a
// run answered at all, so the deploy card - the one row with nowhere else to
// look - was the one row nobody could look at.
function openTask(rec) {
  // Opening it is looking at it, whichever of the three things the press
  // turns out to mean, so the mark goes first and the red dot on the Runs
  // tab has one thing less to count - and so does the dot on this card,
  // which is the other half of what "I clicked a run" has to mean.
  runLooked(rec);
  // A job whose work will not go onto main has one thing to do and it is not
  // on this row: the card with the four choices on it. So the row opens that,
  // wherever the job itself lives.
  if (rec.conflict && showConflictCard(rec.conflict)) return;
  if (rec.mode === 'one') { oneOpen(rec.id); return; }
  // One of Rouh's own jobs opens on the canvas too, like a run of the one
  // program beside it (`jobOpen`). Only the deploy card, which has no job
  // behind it, still unfolds where it is.
  if (jobOpens(rec)) { jobOpen(rec.id); return; }
  rec.open = !rec.open;
  renderTasks();
}

/* ---------------------------------------------------------------- 10a */

/* One of Rouh's own jobs, on the canvas.
 *
 * A worker started by improve_myself, delegate_task or assistant_job used
 * to open by unfolding its card in the sidebar, to an id, two times, where
 * it was working and who owned it. Petar asked on 24 September 2026 for it
 * to open where every other job opens, in the canvas: its title, what it was
 * asked, how it ended, what it printed - and for a job that died, what it
 * died of and a Restart button, the same one its card carries.
 *
 * What the page knows about the job from the task list is drawn at once;
 * the rest - the brief, the log, the cause - is asked of the server
 * (`GET /api/job/<id>`, `starting.about`) and drawn when it comes. The card
 * and this view are one job, so the view is repainted whenever the column
 * is, and asked again whenever the job's status moves.
 */
var JOBVIEW = { id: '', asked: 0, got: null, status: '', logFor: '' };

//: What a died job's card and page say when nothing could be read about
//: why: the worker ended before anything was written down.
var DIED_UNKNOWN = 'Died without a report';

function jobViewing() { return !!(JOBVIEW && JOBVIEW.id); }
function jobIsOpen(id) { return jobViewing() && JOBVIEW.id === String(id); }

// Every row that is one of Rouh's own jobs. Not a run of the one program,
// which has its own view, and not the deploy card, which has no job behind it.
function jobOpens(rec) { return !!rec && rec.mode !== 'one' && !rec.dismiss; }

function jobOpen(id) {
  var want = String(id || '');
  if (!want) return;
  var fresh = JOBVIEW.id !== want;
  JOBVIEW.id = want;
  if (fresh) { JOBVIEW.got = null; JOBVIEW.logFor = ''; }
  if (ORBX.open) orbExpand(false);
  showLayer('jobView');
  // It opens on the canvas, which may be under a sidebar lying over it.
  sidebarDone();
  if (fresh) $('jobView').scrollTop = 0;
  jobAsk();
  renderTasks();
}

// The job a link names, wherever it lives: a run of the one program opens
// its run, and one of Rouh's own jobs opens here.
function jobGo(id) {
  var rec = taskRecs[id];
  if (rec) openTask(rec); else jobOpen(id);
}

function jobAsk() {
  var id = JOBVIEW.id, mine = ++JOBVIEW.asked;
  var rec = taskRecs[id];
  JOBVIEW.status = rec ? String(rec.status || '') : '';
  jobPaint();
  fetch('/api/job/' + encodeURIComponent(id),
        { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        return { ok: r.ok, status: r.status, body: body };
      });
    })
    .catch(function () {
      return { ok: false, status: 0, body: { error: 'Rouh could not be reached, so this job could not be read.' } };
    })
    .then(function (a) {
      // Only the newest ask counts, and only while this job is still open.
      if (JOBVIEW.asked !== mine || !jobIsOpen(id)) return;
      JOBVIEW.got = a.ok ? (a.body || {}) : { error: (a.body && a.body.error)
        || ('This job could not be read: the server said ' + a.status + '.') };
      jobPaint();
    });
}

function jobClose() {
  // JOBVIEW as well as its id: this is a layer's closer, and those are all
  // called while the page is still being built. See `oneClose`.
  if (!JOBVIEW || !JOBVIEW.id) return;
  JOBVIEW.id = '';
  JOBVIEW.got = null;
  JOBVIEW.status = '';
  JOBVIEW.logFor = '';
  JOBVIEW.asked++;
  showLayer(null);
  renderTasks();
}

// The column was redrawn, so something about some job moved. If it was this
// one's status, what the server says about it is asked for again - a job
// that has just died has a cause now, and a log - and otherwise the view is
// only repainted from what the card now says.
function jobFollow() {
  if (!jobViewing()) return;
  var rec = taskRecs[JOBVIEW.id];
  if (rec && String(rec.status || '') !== JOBVIEW.status) { jobAsk(); return; }
  jobPaint();
}

// Text into a box only when it has changed, so a repaint does not move
// somebody who is reading a long log.
function jobText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function jobPaint() {
  if (!jobViewing()) return;
  var id = JOBVIEW.id, rec = taskRecs[id] || { id: id }, got = JOBVIEW.got || {};
  // The card is the newer of the two about the job's state: it hears every
  // change as it happens, and the server's answer is from when it was asked.
  var status = String(rec.status || got.status || '');
  var died = taskKey(status) === 'lost';
  $('jobTitle').textContent = rec.title || got.title || ('Job ' + id);

  var meta = $('jobMeta');
  meta.textContent = '';
  meta.appendChild(el('span', died ? 'task-state' : 'one-state ' + taskClass(status),
                      taskWord(status)));
  meta.appendChild(el('span', null, 'Job ' + id));
  if (got.kind_words) meta.appendChild(el('span', null, got.kind_words));
  var began = rec.created_at || got.created_at, ended = rec.finished_at || got.finished_at;
  if (began) meta.appendChild(el('span', null, 'Started ' + atTime(began) + ', ' + ago(began)));
  if (ended && taskKey(status) !== 'running') {
    meta.appendChild(el('span', null, (died ? 'Died ' : 'Ended ') + atTime(ended)));
  }
  var where = rec.branch || got.branch || rec.repo || got.repo;
  if (where) meta.appendChild(el('span', 'job-where', where));
  var code = typeof rec.exit_code === 'number' ? rec.exit_code : got.exit_code;
  if (typeof code === 'number') meta.appendChild(el('span', null, 'Exit code ' + code));
  // Where it belongs, and the way to change it, as on its card.
  var own = el('button', 'owner-pick', 'Belongs to ' + ownerWords(rec.owned_by));
  own.type = 'button';
  own.title = 'Move this job';
  own.addEventListener('click', function () {
    openOwner('run', id, rec.title || got.title || id, 'job');
  });
  meta.appendChild(own);
  // The job it was restarted as, and the job it is a restart of.
  var again = rec.restarted_as || got.restarted_as;
  if (again) meta.appendChild(jobLink('Restarted as job ' + again, again));
  if (got.restart_of) meta.appendChild(jobLink('A restart of job ' + got.restart_of, got.restart_of));

  var restart = $('jobRestart');
  restart.hidden = !(died && !again && (rec.restartable === true || got.restartable === true));
  restart.disabled = !!rec.restarting;
  restart.textContent = rec.restarting ? 'Restarting\u2026' : 'Restart';
  restart.title = 'Start this job again, with the same brief, as a new job';

  var why = $('jobDied');
  why.textContent = '';
  why.hidden = !died;
  if (died) {
    why.appendChild(el('strong', null, 'Why it died'));
    why.appendChild(document.createTextNode(
      (got.death && got.death.line) || rec.detail || DIED_UNKNOWN));
  }
  var said = $('jobSaid'), words = got.closing || '';
  said.textContent = '';
  said.hidden = !words;
  if (words) {
    said.appendChild(el('strong', null, 'It said'));
    said.appendChild(document.createTextNode(words));
  }

  jobText($('jobBrief'), got.brief || rec.brief || (JOBVIEW.got ? '' : 'Reading it\u2026'));
  var log = $('jobLog'), none = $('jobLogNone');
  if (got.log) {
    jobText(log, got.log);
    log.hidden = false;
    none.hidden = true;
    // The end of it is what matters, so a log is opened at its last line,
    // once, rather than every time the view is repainted.
    if (JOBVIEW.logFor !== id) { JOBVIEW.logFor = id; log.scrollTop = log.scrollHeight; }
  } else {
    log.hidden = true;
    none.hidden = false;
    none.textContent = !JOBVIEW.got ? 'Reading its log\u2026'
      : got.error ? got.error
      : died ? 'No log was written for this job: it died before anything could be kept.'
      : 'Nothing has been written to its log yet.';
  }
  addrTouch();
}

function jobLink(words, id) {
  // A link to that job's address, so it opens in a tab of its own too.
  var b = linkTo(el('a', 'job-link', words), function () { return addrPlaceLink(addrOf('run', id)); });
  b.addEventListener('click', function () { jobGo(id); });
  return b;
}

/* Start a job that died again, from its card or its page.

   The same brief, the same kind and the same files hint, as a fresh job
   with a new id (`POST /api/job/<id>/restart`, `starting.restart`). The
   button goes quiet the moment it is pressed and stays so until the answer
   is back, and the server takes one restart per job whatever arrives, so a
   double click starts one job. The dead card is put away and the new one
   takes its place, and a page that was showing the dead job shows the new
   one. */
function restartTask(rec) {
  if (!rec || rec.restarting || rec.restarted_as) return;
  rec.restarting = true;
  renderTasks();
  fetch('/api/job/' + encodeURIComponent(rec.id) + '/restart', {
    method: 'POST', credentials: 'same-origin', headers: { 'Accept': 'application/json' }
  }).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      return { ok: r.ok, status: r.status, body: body };
    });
  }).catch(function () {
    return { ok: false, status: 0, body: { error: 'Rouh could not be reached, so the job was not restarted.' } };
  }).then(function (a) {
    rec.restarting = false;
    var id = a.ok && a.body && a.body.id ? String(a.body.id) : '';
    if (!a.ok) {
      notify((a.body && a.body.error)
        || ('The job could not be restarted: the server said ' + a.status + '.'), { tone: 'error' });
    }
    var wasOpen = jobIsOpen(rec.id);
    if (id) {
      rec.restarted_as = id;
      rec.restartable = false;
      rec.archived = true;
      if (!taskRecs[id]) {
        mergeTask({ id: id, title: a.body.title || rec.title, status: a.body.status || 'starting',
                    mode: a.body.mode || rec.mode });
      }
    }
    renderTasks();
    if (id && wasOpen) jobOpen(id);
  });
}

(function () {
  var restart = $('jobRestart'), close = $('jobClose');
  if (restart) restart.addEventListener('click', function () {
    if (JOBVIEW.id) restartTask(taskRecs[JOBVIEW.id] || mergeTask({ id: JOBVIEW.id }));
  });
  if (close) close.addEventListener('click', jobClose);
})();

/* ---------- the Live browser ----------

   Petar, 24 September 2026, answering task 60: "for now I only want 9 - the
   live visual browser." A real browser Rouh drives for errands
   (rouh/browsing.py), on the canvas: its screen live, what Rouh is doing in
   it with a ring round the thing it is about to press, and Take control and
   Hand back, which give the person the mouse and the keyboard and give them
   back to Rouh.

   The screen is JPEG frames the server sends only while this layer is open
   on some tab (`browser_watch`), so a browser nobody is looking at costs
   nothing to draw. What the person clicks and types while they have it goes
   up as `browser_input`, in the page's own pixels, and the server refuses
   it whenever it is Rouh's turn rather than theirs.

   It opens by itself on the screen that is in the errand's chat, when Rouh
   starts an errand or hands the browser over; at a phone's width it says so
   instead, with a button, rather than taking the person away from the
   conversation they are reading. The row in the sidebar opens it whenever a
   browser is open. */

var WEB = { viewing: false, state: null, frameW: 1024, frameH: 720,
            moveAt: 0, wheel: null, touchY: null, note: null };

function webViewing() { return !!(WEB && WEB.viewing); }
function webMine() { return !!(WEB.state && WEB.state.control === 'person'); }

// A `browser` message: whether a browser is open, who has it, where it is.
/** @param {import('./protocol').FromServer<'browser'>} m */
function webState(m) {
  var was = WEB.state;
  WEB.state = m && m.open ? m : null;
  webRow();
  if (WEB.state && m.show && CHATS && m.from_chat === CHATS.active && !webViewing()) {
    var asked = m.control === 'person' && m.asked;
    if (!narrow()) { webOpen(); }
    else {
      if (WEB.note) WEB.note.remove();
      WEB.note = notify(asked ? 'Rouh has handed you its browser: ' + (m.why || 'it needs you.')
                              : 'Rouh is using its browser.',
                        { tone: asked ? 'warning' : 'info', kind: 'browser',
                          action: { label: asked ? 'Open it' : 'Watch', run: webOpen } });
    }
  }
  if (webViewing()) webPaint(was);
}

function webRow() {
  // In Now, among the navigation's links, and only while a browser is open.
  var row = $('webRow'), who = $('webRowWho');
  if (!row) return;
  var st = WEB.state;
  row.hidden = !st;
  if (!st) return;
  who.textContent = st.control !== 'person' ? 'Rouh' : st.asked ? 'Waiting for you' : 'Yours';
  who.className = 'sb-web-who' + (st.control === 'person' ? ' yours' : ' busy');
  row.classList.toggle('on', webViewing());
}

function webOpen() {
  // The phone's note that offered it has done its work.
  if (WEB.note) { WEB.note.remove(); WEB.note = null; }
  if (ORBX.open) orbExpand(false);
  WEB.viewing = true;
  showLayer('webView');
  // It opens on the canvas, which may be under a sidebar lying over it.
  sidebarDone();
  webWatch();
  webPaint(null);
  webRow();
}

// Watching, with the shape of the box the picture is drawn in and whether
// this is the phone's layout: the browser's window is made that shape, so
// the picture fills the box, and a phone gets the page as a phone would lay
// it out (`Desk._fit`).
function webWatch() {
  var box = $('webScreen');
  send({ type: 'browser_watch', on: true, phone: narrow(),
         w: box.clientWidth || 0, h: box.clientHeight || 0 });
}

function webClose() {
  // WEB as well as the flag: this is a layer's closer, and those are called
  // while the page is still being built (see `oneClose`).
  if (!WEB || !WEB.viewing) return;
  WEB.viewing = false;
  send({ type: 'browser_watch', on: false });
  $('webImg').hidden = true;
  $('webImg').removeAttribute('src');
  showLayer(null);
  webRow();
}

function webPaint(was) {
  var st = WEB.state, mine = webMine();
  var view = $('webView');
  view.classList.toggle('mine', mine);
  $('webScreen').classList.toggle('mine', mine);
  $('webTitle').textContent = st ? (st.title || webHost(st.url) || 'Live browser') : 'Live browser';
  var meta = $('webMeta');
  meta.textContent = '';
  if (st) {
    meta.appendChild(el('span', 'one-state ' + (mine ? 's-asking' : 's-working'),
      mine ? (st.asked ? 'Waiting for you' : 'You have it') : 'Rouh has it'));
    meta.appendChild(el('span', null, 'Live browser'));
  }
  var take = $('webTake'), stop = $('webStop');
  take.hidden = stop.hidden = !st;
  take.textContent = mine ? 'Hand back' : 'Take control';
  take.title = mine ? 'Give the browser back to Rouh, and tell it where the page is now'
                    : 'Stop Rouh, and use the browser yourself';
  var ask = $('webAsk');
  ask.textContent = '';
  ask.hidden = !(st && mine && st.asked);
  if (!ask.hidden) {
    ask.appendChild(el('strong', null, 'Rouh asks you'));
    ask.appendChild(document.createTextNode(
      (st.why ? st.why.replace(/[.\s]+$/, '') + '. ' : '') + 'Press Hand back when you are done.'));
  }
  $('webBar').hidden = !st;
  var url = $('webUrl');
  url.readOnly = !mine;
  if (document.activeElement !== url || !mine) url.value = st ? (st.url || '') : '';
  $('webBack').disabled = !mine;
  $('webType').hidden = !(st && mine);
  var none = $('webNone');
  if (!st) {
    $('webImg').hidden = true;
    none.hidden = false;
    none.textContent = 'The browser is closed. Ask Rouh to go to a website, and it opens here.';
  } else if ($('webImg').hidden) {
    none.hidden = false;
    none.textContent = 'Waiting for the browser’s screen…';
  }
  $('webSay').textContent = !st ? ''
    : mine ? 'Click, scroll and type on the page: it is yours until you press Hand back.'
    : st.doing ? st.doing + '…'
    : 'Rouh has the browser. Press Take control to use it yourself.';
  webMarkPlace();
  // Taken or handed back, the keys follow: the page itself has the focus
  // while it is theirs, so typing goes to it without a click first.
  if (mine && !(was && was.control === 'person') && document.activeElement !== url) {
    $('webScreen').focus({ preventScroll: true });
  }
  addrTouch();
}

function webHost(url) {
  var m = /^[a-z]+:\/\/([^\/?#]+)/i.exec(String(url || ''));
  return m ? m[1].replace(/^www\./, '') : '';
}

/** @param {import('./protocol').FromServer<'browser_frame'>} m */
function webFrame(m) {
  if (!webViewing() || !m.data) return;
  var img = $('webImg');
  WEB.frameW = Number(m.width) || 1024;
  WEB.frameH = Number(m.height) || 720;
  img.src = 'data:image/jpeg;base64,' + m.data;
  if (img.hidden) {
    img.hidden = false;
    $('webNone').hidden = true;
  }
  webMarkPlace();
}

// The ring round what Rouh is about to press, in the picture's own place.
function webMarkPlace() {
  var mark = $('webMark'), img = $('webImg'), st = WEB.state;
  var box = st && !webMine() ? st.mark : null;
  if (!box || img.hidden || !img.clientWidth) { mark.hidden = true; return; }
  var scale = img.clientWidth / WEB.frameW;
  mark.style.left = (img.offsetLeft + box.x * scale - 3) + 'px';
  mark.style.top = (img.offsetTop + box.y * scale - 3) + 'px';
  mark.style.width = (box.width * scale + 6) + 'px';
  mark.style.height = (box.height * scale + 6) + 'px';
  mark.hidden = false;
}

// Where on the page the pointer is, in the page's own pixels, or null when
// it is not over the picture.
function webAt(clientX, clientY) {
  var img = $('webImg');
  if (img.hidden) return null;
  var r = img.getBoundingClientRect();
  if (!r.width || clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) {
    return null;
  }
  return { x: Math.round((clientX - r.left) / r.width * WEB.frameW),
           y: Math.round((clientY - r.top) / r.height * WEB.frameH) };
}

function webInput(what) {
  if (!webMine()) return;
  what.type = 'browser_input';
  send(what);
}

//: The keys that go to the page by name. Anything else a key makes is a
//: character, and goes as text.
var WEB_KEYS = { Enter: 1, Escape: 1, Tab: 1, Backspace: 1, Delete: 1, Home: 1, End: 1,
                 PageUp: 1, PageDown: 1, ArrowUp: 1, ArrowDown: 1, ArrowLeft: 1,
                 ArrowRight: 1 };

(function () {
  var screen = $('webScreen');
  if (!screen) return;
  $('webRow').addEventListener('click', function () {
    if (webViewing()) webClose(); else webOpen();
  });
  $('webClose').addEventListener('click', webClose);
  $('webTake').addEventListener('click', function () {
    send({ type: webMine() ? 'browser_give' : 'browser_take' });
  });
  $('webStop').addEventListener('click', function () { send({ type: 'browser_stop' }); });
  $('webForget').addEventListener('click', function () {
    if (!confirm('Forget every login the browser has kept? You will have to log in '
                 + 'again the next time Rouh uses a site for you.')) return;
    send({ type: 'browser_forget' });
  });
  $('webBack').addEventListener('click', function () { webInput({ kind: 'back' }); });
  $('webBar').addEventListener('submit', function (e) {
    e.preventDefault();
    var url = $('webUrl').value.trim();
    if (url) webInput({ kind: 'go', url: url });
    $('webScreen').focus({ preventScroll: true });
  });
  $('webType').addEventListener('submit', function (e) {
    e.preventDefault();
    var box = $('webTypeText');
    if (box.value) webInput({ kind: 'text', text: box.value });
    box.value = '';
  });
  $('webEnter').addEventListener('click', function () { webInput({ kind: 'key', key: 'Enter' }); });

  screen.addEventListener('click', function (e) {
    if (!webMine()) return;
    var at = webAt(e.clientX, e.clientY);
    screen.focus({ preventScroll: true });
    if (at) webInput({ kind: 'click', x: at.x, y: at.y });
  });
  // Hover matters on a web page - a menu that opens under the pointer - so
  // the pointer's place goes up too, a few times a second at most.
  screen.addEventListener('mousemove', function (e) {
    if (!webMine() || Date.now() - WEB.moveAt < 120) return;
    var at = webAt(e.clientX, e.clientY);
    if (!at) return;
    WEB.moveAt = Date.now();
    webInput({ kind: 'move', x: at.x, y: at.y });
  });
  // The wheel, gathered for a moment and sent as one scroll, so a trackpad
  // does not send sixty messages a second.
  screen.addEventListener('wheel', function (e) {
    if (!webMine()) return;
    var at = webAt(e.clientX, e.clientY);
    if (!at) return;
    e.preventDefault();
    var scale = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
    if (!WEB.wheel) {
      WEB.wheel = { x: at.x, y: at.y, dx: 0, dy: 0 };
      setTimeout(function () {
        var w = WEB.wheel;
        WEB.wheel = null;
        if (w && (w.dx || w.dy)) webInput({ kind: 'wheel', x: w.x, y: w.y, dx: w.dx, dy: w.dy });
      }, 80);
    }
    WEB.wheel.dx += e.deltaX * scale;
    WEB.wheel.dy += e.deltaY * scale;
  }, { passive: false });
  // A finger dragged over the page scrolls the page, not this one.
  screen.addEventListener('touchstart', function (e) {
    WEB.touchY = webMine() && e.touches.length === 1 ? e.touches[0].clientY : null;
  }, { passive: true });
  screen.addEventListener('touchmove', function (e) {
    if (WEB.touchY === null || !webMine()) return;
    var t = e.touches[0], at = webAt(t.clientX, t.clientY);
    if (!at) return;
    e.preventDefault();
    var dy = (WEB.touchY - t.clientY) * (WEB.frameW / Math.max(1, $('webImg').clientWidth));
    if (Math.abs(dy) < 8) return;
    WEB.touchY = t.clientY;
    webInput({ kind: 'wheel', x: at.x, y: at.y, dx: 0, dy: dy });
  }, { passive: false });
  screen.addEventListener('keydown', function (e) {
    if (!webMine() || e.isComposing) return;
    var key = e.key, mod = e.ctrlKey || e.metaKey;
    // Copy and paste belong to the person's own computer: the paste arrives
    // below as text, and a copy out of the page is not a thing it can do.
    if (mod && /^[cvx]$/i.test(key)) return;
    if (mod && /^[a-z0-9]$/i.test(key)) {
      e.preventDefault();
      webInput({ kind: 'key', key: (e.metaKey ? 'Meta+' : 'Control+') + key.toLowerCase() });
      return;
    }
    if (e.altKey) return;
    if (key === 'Tab' && e.shiftKey) { e.preventDefault(); webInput({ kind: 'key', key: 'Shift+Tab' }); return; }
    if (WEB_KEYS[key]) { e.preventDefault(); webInput({ kind: 'key', key: key }); return; }
    if (key.length === 1) { e.preventDefault(); webInput({ kind: 'text', text: key }); }
  });
  screen.addEventListener('paste', function (e) {
    if (!webMine()) return;
    var text = e.clipboardData ? e.clipboardData.getData('text') : '';
    if (!text) return;
    e.preventDefault();
    webInput({ kind: 'text', text: text });
  });
  // The picture's box changes size with the window, and with what is drawn
  // above it - Rouh's note when it hands the browser over takes a line or
  // two. The ring goes with it at once, and once the box has settled the
  // browser is made its new shape.
  var fitting = null;
  function refit() {
    if (!webViewing()) return;
    webMarkPlace();
    clearTimeout(fitting);
    fitting = setTimeout(function () { if (webViewing()) webWatch(); }, 400);
  }
  if (window.ResizeObserver) new ResizeObserver(refit).observe(screen);
  else window.addEventListener('resize', refit);
})();

/* The person has looked at this now that it has finished.
 *
 * One doorway for every list that has a dot: a run's card, a task's row, a
 * step's row, and a project's row. The mark is the server's - it is a
 * column on the row, so it survives a reload, a restart and the person's
 * other device - and this is the only thing on the page that sets it.
 * Archiving is not here: a run is archived from three places and the
 * register marks it seen itself, so no path can forget to
 * (`objects.update_run`).
 *
 * `there` is whether this row has anything left to clear, worked out by
 * whoever is calling: a run that has stopped and is not seen, a task or a
 * step whose own `new` is set. Nothing is said about a row with nothing to
 * mark, because the answer is a `tasks` or `objects` list to every tab,
 * which is too much to send for a press that changes nothing.
 *
 * `deep` is the dot itself being pressed rather than the row: that row and
 * everything under it. It always has something to do - that is what the dot
 * it was pressed on means - so it is not asked `there`.
 *
 * Set here as well as sent, so the dot answers the press rather than the
 * round trip. The message that comes back says the same thing.
 */
function markSeen(kind, row, there, deep) {
  if (!row || !row.id || (!deep && !there)) return;
  row.seen = true;
  row.new = false;
  // A project's dot is counted off what is under it, so the runs page's
  // projects are drawn again for anything but a run.
  if (kind === 'run') railPaint(); else renderProjects();
  send({ type: 'mark_seen', kind: kind, id: row.id, deep: !!deep });
}

/* And the whole of the runs list at once, which is landing on it.
 *
 * The same mark and the same message, with a list instead of an id, because
 * this is not a press on a row: it is the tab's dot being answered, and it
 * can stand for twenty runs. One `mark_seen` each would be one task list
 * built and broadcast to every tab each, for one glance at one column.
 */
function markRunsSeen(rows) {
  if (!rows.length) return;
  var ids = [], i;
  for (i = 0; i < rows.length; i++) { rows[i].seen = true; ids.push(rows[i].id); }
  railPaint();
  send({ type: 'mark_seen', kind: 'run', ids: ids });
}

/* Bound to the whole runs page and not to the runs list, because a card is
   drawn in three places on it: the flat list of loose runs, inside a
   project that is open over its runs, and the Pinned section at the top.
   While this was on `#tasksList` alone, a card in either of the other two
   answered nothing - it could not be opened, archived, or have its menu
   opened - which is how a run inside a project has been since the projects
   learnt to unfold on 22 September 2026. `taskFrom` finds the card the
   press was in and gives up quietly when it was in none, so a press
   anywhere else in the column goes where it always did. */
var tasksHost = $('runsView');
if (tasksHost) {
  tasksHost.addEventListener('click', onTaskClick);
  tasksHost.addEventListener('keydown', onTaskKey);
}

// The time of day, for the two times the card shows only as "just now".
// "started just now" says how long ago; this says when, which is what
// somebody reading a card an hour later actually wants.
function atTime(iso) {
  var t = Date.parse(iso || '');
  if (!isFinite(t)) return '';
  var d = new Date(t);
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
}

// What a card shows once it is opened, which is only ever what is not on it
// already: its id, the two clock times, where it is working and where it
// belongs. What it is doing is the dot in front of its brief, and saying
// that again in words here would be two copies of one thing on one card.
function taskMore(rec) {
  var more = el('div', 'task-more');
  function line(label, value) {
    if (value == null || value === '') return;
    var row = el('div', 'task-more-row');
    row.appendChild(el('span', 'task-more-key', label));
    row.appendChild(el('span', 'task-more-val', String(value)));
    more.appendChild(row);
  }
  line('id', rec.id);
  line('started', atTime(rec.created_at));
  line('finished', atTime(rec.finished_at));
  line('where', rec.branch || rec.repo || '');
  if (typeof rec.exit_code === 'number') line('exit', String(rec.exit_code));
  // Where it belongs, and the way to change it. It was on a line every card
  // in the column carried until 22 September 2026; a card is its brief and
  // its dot now, so the owner is here with the rest of what is worth reading
  // once. A run of the one program does not open its card - it opens the run
  // - and carries the same button on the run's own heading instead.
  //
  // An orphan is legal and "Nowhere" is the ordinary answer rather than a
  // missing one. Attaching a run to a task takes its diff, its artifacts and
  // its cost under that task; detaching gives them back.
  var own = el('div', 'task-more-row');
  own.appendChild(el('span', 'task-more-key', 'owner'));
  own.appendChild(ownerButton(rec));
  more.appendChild(own);
  return more;
}

// Where a job or a run belongs, as a few words that are pressed. What the
// click means is on the button as `data-act`, so the column's one listener
// catches it the way it catches every other control on a card.
function ownerButton(rec) {
  var words = ownerWords(rec.owned_by);
  var b = el('button', 'owner-pick', words);
  b.type = 'button';
  b.setAttribute('data-act', 'own');
  b.title = 'Move this ' + taskNoun(rec);
  b.setAttribute('aria-label', 'Belongs to ' + words + '. Move this ' + taskNoun(rec));
  return b;
}

/* A card is one line: the status as a dot, the brief, and the button that
 * puts the run away, in the top right corner.
 *
 * It was three. The status was a word in a chip under the brief, and under
 * that ran "started 14 min ago · terminal open · one · Nowhere". Petar
 * asked on 22 September 2026 for both of those gone: the word is self
 * evident from the colour, so it is what the dot says when it is pointed at,
 * and everything the third line carried is on the run itself when it is
 * opened - its times and where it belongs on its heading, or under the card
 * for one of Rouh's own jobs.
 *
 * What the dot says with no words at all: blue and blinking while it works,
 * green when it is finished, red when it ended badly, amber when it has
 * stopped to ask. Hollow green is a run at its prompt with its terminal
 * still open, which is what "terminal open" used to say in two words.
 */
function taskCard(rec) {
  var s = taskKey(rec.status);
  // A link to the run's own address, so Cmd-click, the middle button and
  // Open link in new tab take it to a tab of its own (`linkTo`). A plain
  // press is still the column's one listener (`onTaskClick`), and so is a
  // press on any button on the card.
  var node = el('a', 'task ' + taskClass(rec.status) + (rec.archived ? ' archived' : ''));

  var top = el('div', 'task-top');
  var word = taskWord(rec.status);
  // A job that died says so in a word, in red, where every other card has
  // its dot. Petar, 24 September 2026: the grey dot a dead job had read as
  // a card with nothing to say, and he could not tell at a glance that the
  // job had died. The dot's colours are the quiet states; this one is not.
  var died = s === 'lost';
  var dot = el('span', died ? 'task-state' : 'task-dot', died ? word : null);
  dot.title = word + (TASK_MEANS[s] ? '\n' + TASK_MEANS[s] : '');
  if (!died) {
    // A picture with a name, so the column reads to a screen reader the way
    // it reads on the screen, and so the word is a hover away for everybody
    // else.
    dot.setAttribute('role', 'img');
    dot.setAttribute('aria-label', word);
  }
  top.appendChild(dot);
  top.appendChild(el('div', 'task-title', rec.title || rec.id));
  // And which run it is that the dot on the Runs tab was about. Two dots on
  // one card say two different things and neither is the other: the
  // coloured one at the start of the line is what this run is doing, and
  // this one is that nobody has looked at it since it stopped.
  if (runWantsLook(rec)) top.appendChild(runDot(rec));
  // Kept in view, at the top of the column, by the person's own hand.
  if (rec.pinned) top.appendChild(pinMark('it is at the top of this column'));
  if (rec.archived) {
    var pill = el('span', 'chip pill-archived', 'Archived');
    pill.title = 'Put out of the way. It was stopped; its folder is untouched.';
    top.appendChild(pill);
  }
  // The chat it was asked in, where its report goes (`chatButton`).
  if (rec.chat) top.appendChild(chatButton(rec));
  // Every row carries it, whatever it is and whatever state it is in: a run
  // of the one program, one of Rouh's own jobs, running, finished or
  // already archived, where it is the button that brings it back.
  top.appendChild(archiveButton(rec));
  // And the dots, which are not the same thing at all: archiving keeps the
  // run and puts it away, and behind these are pin, rename and delete. Not on
  // the card that has no run behind it - the deploy card - whose one control
  // is the bin that dismisses it.
  if (!rec.dismiss) top.appendChild(taskDots(rec));
  node.appendChild(top);
  if (rec.actual_model || rec.model) {
    node.appendChild(el('div', 'task-detail', rec.actual_model
      ? 'Model: ' + rec.actual_model : 'Requested model: ' + rec.model));
  }

  // A job whose work will not go onto main is not the same kind of waiting as
  // a job that stopped to ask Claude Code a question, and it must not look
  // like one: only a person can move it, so it is the orb's own NEEDS YOU red
  // rather than the amber every other kind of waiting wears.
  if (rec.conflict) {
    node.classList.add('s-conflict');
    dot.title = word + '\nIts work will not go onto main. '
      + 'Pick one of the four on its card.';
  }

  // What it was for, once it has finished well. Petar, 29 September 2026
  // (fr_0b6dec937436): a column of green runs each showing the last line
  // its terminal printed could not be read a day later. So a green run -
  // done, or finished its turn at its prompt - shows the sentence written
  // from its brief as it began instead, and its last line stays one click
  // away on the run itself and a hover away here. A run still going, or one
  // that failed, died or is asking, keeps its own line: that is the thing
  // to read then.
  var summed = !!rec.summary && !rec.conflict && !rec.asking && (s === 'done' || s === 'idle');
  if (summed) {
    var said = el('div', 'task-detail task-summary', rec.summary);
    if (rec.detail) said.title = 'Its last line: ' + rec.detail;
    node.appendChild(said);
  } else if (rec.detail && !died) {
    // The question it stopped to ask, when there is one.
    var d = el('div', 'task-detail' + (rec.asking ? ' asking' : '')
      + (rec.conflict ? ' conflict' : ''), rec.detail);
    node.appendChild(d);
  }
  if (died) diedOnCard(node, rec);

  var where = rec.branch || rec.repo;
  node.title = where ? (rec.title || rec.id) + '\n' + where : (rec.title || rec.id);

  // The id is on the card because that is how the column's one listener
  // finds the row a click belongs to.
  node.setAttribute('data-id', rec.id);
  node.classList.add('opens');
  var opens = rec.mode === 'one' || jobOpens(rec);
  // The deploy card has no run behind it and unfolds where it is: a button.
  linkTo(node, opens ? function () { return addrPlaceLink(addrOf('run', rec.id)); } : '');
  if (rec.mode === 'one') {
    if (oneIsOpen(rec.id)) node.classList.add('open');
    node.setAttribute('aria-label', 'Open the run: ' + (rec.title || rec.id));
  } else if (jobOpens(rec)) {
    if (jobIsOpen(rec.id)) node.classList.add('open');
    node.setAttribute('aria-label', 'Open the job: ' + (rec.title || rec.id));
  } else {
    node.setAttribute('aria-expanded', rec.open ? 'true' : 'false');
    node.setAttribute('aria-label',
      (rec.open ? 'Hide what this is: ' : 'Show what this is: ')
      + (rec.title || rec.id));
    if (rec.open) node.appendChild(taskMore(rec));
  }
  return node;
}

/* What a card that died carries under its brief: what it died of, in one
   line, and the button that starts it again - or, once it has been, the job
   it was restarted as. The line is the server's, read off the worker's log
   or its launcher's record when it was found dead (`crew.death_of`) and
   sent as `detail`; a death nothing could be read about says so. */
function diedOnCard(node, rec) {
  var why = el('div', 'task-detail died');
  why.appendChild(el('span', null, rec.detail || DIED_UNKNOWN));
  why.title = rec.detail || DIED_UNKNOWN;
  node.appendChild(why);
  var b;
  if (rec.restarted_as) {
    b = el('button', 'task-again', 'Restarted as job ' + rec.restarted_as);
    b.setAttribute('data-act', 'restarted');
    b.title = 'Open the job it was restarted as';
  } else if (rec.restartable === true) {
    b = el('button', 'ctl small task-restart', rec.restarting ? 'Restarting\u2026' : 'Restart');
    b.setAttribute('data-act', 'restart');
    b.disabled = !!rec.restarting;
    b.title = 'Start this job again, with the same brief, as a new job';
    b.setAttribute('aria-label', 'Restart the job: ' + (rec.title || rec.id));
  }
  if (!b) return;
  b.type = 'button';
  var row = el('div', 'task-acts');
  row.appendChild(b);
  node.appendChild(row);
}

function renderTasks() {
  var host = $('tasksList');
  if (!host) return;

  // Before a single card is built, so the cards that were waiting to be
  // looked at are drawn wearing the dot they have just been given.
  runsLanding();

  var all = [], deploy = null, k;
  for (k in taskRecs) {
    // Rouh updating itself is not a run, so it is not on the list of runs:
    // it is the note over it (`renderDeploy`).
    if (isDeploy(taskRecs[k])) deploy = taskRecs[k];
    else all.push(taskRecs[k]);
  }
  renderDeploy(deploy);

  // The tabs count both halves, and what waits on the person over both.
  runsTabsPaint(all);

  // Only the half of Metabolism that is showing: everyday work or mutations.
  var mine = all.filter(runsInTab);
  // Archived runs are out of the way unless the person asks for them.
  var shown = SHOW_ARCHIVED ? mine : mine.filter(function (r) { return !r.archived; });

  /* And a run that is in a project is drawn under that project, in the group
     above this one, rather than here as well (`renderProjects`). Only if the
     project really is on that list: a run whose project is not drawn - which
     is a project the list of projects has not heard of - stays here, because
     a run on no list anywhere is the bug this work is about. */
  var hosts = {};
  runHosts().forEach(function (p) { hosts[p.id] = true; });
  shown = shown.filter(function (r) { return !hosts[r.project_id]; });

  // And a run the person has pinned is in the Pinned section at the top of
  // the column, so it is not here as well.
  var pinned = pinnedRuns().length;
  shown = shown.filter(function (r) { return !r.pinned; });

  // One list in one order, and the order is when each job started. The
  // column used to be split into "Still open" and "Finished", with the job
  // asking a question lifted to the top of the first: every one of those
  // moved a row the moment the job behind it changed, which is exactly what
  // the person asked to stop. A job's status is on its card instead.
  shown.sort(byStart);

  var keep = host.scrollTop;
  // Where the keyboard was. The whole column is rebuilt on every change, so
  // without this a `tasks` message arriving while somebody was tabbing
  // through it dropped them back at the top of the page.
  var had = focusedTask(host);
  host.textContent = '';

  if (!shown.length) {
    var inside = Object.keys(hosts).length;
    var p = el('p', 'empty', !mine.length
      ? (RUNSVIEW.kind === 'mutation' ? 'No run has changed Rouh itself yet.'
        : 'Nothing is running in the background.')
      : pinned && inside
        ? 'Nothing loose. Your runs are pinned, or in the projects above.'
        : pinned ? 'Nothing loose. Your runs are pinned above.'
        : inside ? 'Nothing loose. Your runs are in the projects above.'
        : 'Everything here is archived. Tick "Show archived" to see it.');
    p.id = 'tasksEmpty';
    host.appendChild(p);
  } else {
    shown.forEach(function (r) { host.appendChild(taskCard(r)); });
  }

  runsTally(shown);
  host.scrollTop = keep;
  if (had) refocusTask(host, had);
  // The projects over this list are drawn from these same rows, so they are
  // drawn again whenever the rows change.
  renderProjects();
  railPaint();
  // The run open on the canvas shows where it belongs, and this is the
  // message that says it has changed.
  oneOwnerPaint();
  // And so does one of Rouh's own jobs open there, which is the same job
  // as its card and follows it: its status, its owner, its restart.
  jobFollow();
}

//: The row the server sends for Rouh restarting onto its own new code
//: (`self_update.row`). Every other row on the list is a run.
function isDeploy(rec) { return !!rec && rec.mode === 'deploy'; }

//: How long the note says an update worked before it goes by itself. One
//: that failed stays until it is dismissed, because that is news.
var DEPLOY_LINGER = 2 * 60 * 1000;
var deployTimer = 0;

/* Rouh updating itself, over the runs and not among them.
 *
 * "Is this an actual code run? If not, [it should not] be listed in the same
 * list as code runs. Should be something else temporary appearing on top
 * maybe?" Petar, 3 October 2026, about an "Updating Rouh" card that sat
 * among his runs five hours after the deploy, with "owner Nowhere" on it.
 *
 * It is not a run: no terminal, no checkout, no owner. So it is a note at
 * the top of the page, drawn and worded apart from the cards: there while
 * the update is going, there for a couple of minutes after it worked, and
 * then gone by itself. One that failed stays, with its reason, until the
 * person dismisses it, which drops the record for every tab (`dismissTask`).
 */
function renderDeploy(rec) {
  var box = $('runsDeploy');
  if (!box) return;
  clearTimeout(deployTimer);
  var c = rec ? taskClass(rec.status) : '';
  var going = c === 's-starting' || c === 's-running';
  var failed = c === 's-failed' || c === 's-lost';
  if (rec && !going && !failed) {
    var ended = Date.parse(rec.finished_at || rec.updated_at || '') || 0;
    var left = ended + DEPLOY_LINGER - Date.now();
    if (left <= 0) rec = null;
    else deployTimer = setTimeout(function () { renderDeploy(taskRecs[rec.id]); }, left + 50);
  }
  box.textContent = '';
  box.hidden = !rec;
  if (!rec) return;
  box.className = 'runs-deploy ' + (going ? 'going' : failed ? 'failed' : 'done');

  var mark = el('span', 'runs-deploy-mark');
  mark.setAttribute('aria-hidden', 'true');
  box.appendChild(mark);
  var words = el('div', 'runs-deploy-words');
  words.appendChild(el('div', 'runs-deploy-title',
    going ? 'Rouh is updating itself'
      : failed ? 'Rouh\'s update did not work' : 'Rouh has updated itself'));
  if (rec.detail) words.appendChild(el('div', 'runs-deploy-detail', rec.detail));
  words.appendChild(el('div', 'runs-deploy-note',
    going ? 'Not a run: Rouh restarting onto its new code. This goes away once it is done.'
      : failed ? 'Not a run: Rouh\'s own update. Dismiss this once you have read it.'
      : 'Not a run: Rouh\'s own update. This goes away by itself.'));
  box.appendChild(words);
  if (!going) {
    var x = el('button', 'runs-deploy-x', '\u00d7');
    x.type = 'button';
    x.title = 'Dismiss';
    x.setAttribute('aria-label', 'Dismiss the note about Rouh\'s update');
    x.addEventListener('click', function () { dismissTask(rec); });
    box.appendChild(x);
  }
}

/* Metabolism's two tabs, and what waits on the person over both of them.
 *
 * Each tab says how many runs it holds - the same runs its list would draw,
 * so archived ones only while "Show archived" is ticked - and carries a mark
 * when something in it wants the person: amber when a run in it is waiting on
 * them, the red of the dot on the navigation's link when one has stopped
 * since they last looked. Waiting wins, because it is the one with a question.
 * And the runs waiting on the person are counted over both tabs, on the page
 * whichever tab is open, so a question on the other tab is never out of sight.
 */
function runsTabsPaint(all) {
  var n = { everyday: 0, mutation: 0 }, wait = { everyday: 0, mutation: 0 },
      look = { everyday: 0, mutation: 0 };
  all.forEach(function (r) {
    var k = runKind(r);
    if (!SHOW_ARCHIVED && r.archived) return;
    n[k]++;
    if (!r.archived && (taskClass(r.status) === 's-waiting' || r.conflict)) wait[k]++;
    else if (runWantsLook(r)) look[k]++;
  });
  [['runsTabEveryday', 'everyday', 'Everyday work'],
   ['runsTabMutation', 'mutation', 'Mutations']].forEach(function (t) {
    var tab = $(t[0]);
    if (!tab) return;
    var on = RUNSVIEW.kind === t[1], k = t[1];
    tab.classList.toggle('on', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    tab.tabIndex = on ? 0 : -1;
    var count = tab.querySelector('.runs-tab-count');
    if (count) count.textContent = String(n[k]);
    var mark = /** @type {HTMLElement|null} */ (tab.querySelector('.runs-tab-mark'));
    var says = t[2] + ': ' + howMany(n[k], { one: 'run', many: 'runs' });
    if (mark) {
      mark.hidden = !wait[k] && !look[k];
      mark.classList.toggle('wait', !!wait[k]);
      if (wait[k]) says += ', ' + wait[k] + ' waiting on you';
      else if (look[k]) says += ', ' + look[k] + ' stopped that you have not looked at';
    }
    tab.setAttribute('aria-label', says);
  });
  var box = $('runsWaiting');
  if (!box) return;
  var total = wait.everyday + wait.mutation;
  box.hidden = !total;
  box.textContent = total === 1 ? '1 run needs you' : total + ' runs need you';
  box.title = total ? 'Waiting on you: ' + [wait.everyday ? wait.everyday + ' in Everyday work' : '',
    wait.mutation ? wait.mutation + ' in Mutations' : ''].filter(Boolean).join(', ') : '';
}

/* What the cards in the Runs column are doing, counted apart under its
 * heading. The number beside the heading is every card, and on 29 September
 * 2026 thirty-odd of them were twenty that had finished their turn and a
 * handful working: open is not the same as working (D49), and a run at its
 * prompt is open, waiting to be carried on or closed. So the kinds are said
 * in words - working, needs you, finished their turn, over - in that order,
 * each only when there is one. */
function runsTally(shown) {
  var box = $('runsTally');
  if (!box) return;
  var n = { going: 0, saving: 0, asking: 0, idle: 0, over: 0 };
  shown.forEach(function (r) {
    var c = taskClass(r.status);
    if (c === 's-starting' || c === 's-running') n.going++;
    else if (c === 's-saving') n.saving++;
    else if (c === 's-waiting' || r.conflict) n.asking++;
    // Archiving stops a run, so one put away at its prompt is over too.
    else if (c === 's-idle' && !r.archived) n.idle++;
    else n.over++;
  });
  var parts = [];
  if (n.going) parts.push(n.going + ' working');
  if (n.saving) parts.push(n.saving + ' saving ' + (n.saving === 1 ? 'its' : 'their') + ' work');
  if (n.asking) parts.push(n.asking + ' need' + (n.asking === 1 ? 's' : '') + ' you');
  if (n.idle) parts.push(n.idle + ' finished ' + (n.idle === 1 ? 'its' : 'their') + ' turn');
  if (n.over) parts.push(n.over + ' over');
  box.textContent = parts.join(', ');
  box.hidden = !parts.length;
  box.title = n.idle
    ? 'A run that finished its turn is still open at its prompt. '
      + 'Send it a message to carry it on, or archive it to close it.'
    : '';
}

/* The dot on the Runs row, and the one on General's.
 *
 * One question: **has something here stopped that I have not looked at?**
 * Done, ended badly, stopped to ask - all of them are stopped, because all
 * of them are something to go and look at. Work actually going on is not,
 * and puts no dot anywhere: there is nothing for anybody to do about a job
 * that is running, and while the dot meant that it was lit all day and said
 * nothing (Petar, 22 September 2026).
 *
 * One colour too, and it is red, ringed in the column's own near-black so
 * it reads on a row that is lit as well as on one that is not (`.sb-row-dot`
 * in app.css).
 *
 * These dots were on the three buttons of the switch at the top of the
 * sidebar until 30 September 2026. The chats and the tasks went with their
 * lists; the runs' dot is on the Runs row that opens their page, and
 * General's, which the chat bubble used to carry, is on General's row.
 * The number is in the row's own tooltip.
 */
//: What the runs are called, which row and which dot are theirs, and how
//: their own kind of stopped reads in words.
var RAIL_WORDS = {
  runs: { tab: 'runsRow', dot: 'runsBadge', plain: 'Metabolism',
          one: 'run', many: 'runs',
          stopped: ' stopped that you have not looked at' }
};

function railPaint() {
  railDot('runs', runsUnseen());
  var general = CHATS && CHATS.general ? chatById(CHATS.general) : null;
  var dot = $('generalBadge'), row = $('generalRow');
  if (dot && row) {
    var fresh = !!general && general.id !== CHATS.active && threadUnread(general);
    dot.hidden = !fresh;
    row.title = fresh ? 'Rouh, with something new in it'
                      : 'Rouh, the chat that is always there';
  }
}

//: "1 run", "3 runs".
function howMany(n, words) {
  return n + ' ' + (n === 1 ? words.one : words.many);
}

function railDot(which, count) {
  var words = RAIL_WORDS[which];
  var tab = words && $(words.tab), dot = words && $(words.dot);
  if (!tab || !dot) return;
  dot.hidden = !(count > 0);
  var says = count > 0
    ? words.plain + ': ' + howMany(count, words) + words.stopped
    : words.plain;
  tab.title = says;
  tab.setAttribute('aria-label', says);
}

// What is on the runs list worth a dot: a run that has stopped (`runStopped`)
// and that the person has not opened or archived since it stopped.
//
// Only what the list would show: a run they have archived is out of the way
// on purpose, and a dot that announced it would be putting it back.
function runsUnseen() {
  var count = 0, k, rec;
  for (k in taskRecs) {
    rec = taskRecs[k];
    if (isDeploy(rec)) continue;
    if (!SHOW_ARCHIVED && rec.archived) continue;
    if (!rec.seen && runStopped(rec)) count++;
  }
  return count;
}

/* Which run it is, and not only that there is one.
 *
 * "When I come to the runs of side drawer, and there is a orange dot up top
 * to tell me something needs my attention, then I need to know which run is
 * the one requiring attention. Also, as I land on that page, the runs should
 * not be requiring attention, so the dot on top should disappear. The dots
 * on the runs can stay until the next time I come, when they should be gone.
 * Basically we can change the status but not the visuals just yet. Also - if
 * I click a run obviously the orange dot should disappear."
 * Petar, 23 September 2026.
 *
 * So the dot on the tab is about the list and a dot on a card is about that
 * run, and landing on the list is looking at it: every run the tab was
 * counting is marked seen the moment the list is on the screen, which takes
 * the tab's dot off at once, and the cards that were counted keep their own
 * dots for the rest of the visit. Clearing both in the same instant would be
 * answering "which one" by rubbing out the answer.
 *
 * `runsFlagged` is what holds that: the ids that were flagged when this
 * visit began, in this tab and for this visit alone. Nothing is written
 * down, because the state is already changed - the marks on the rows say
 * seen - and this is only the picture of it, kept until the person looks
 * away. Switching lists, closing the drawer and reloading the page all end
 * the visit, and what comes back next time is drawn from the rows, which by
 * then have nothing to say.
 *
 * A run that stops **while the list is open** is a new reason to look, and
 * is not covered by any of that: it is not in the set and it is not seen,
 * so it lights its own card and the tab above it again. That is why the
 * question below is asked two ways rather than one.
 */
var runsFlagged = Object.create(null);
//: Whether this visit has been counted as a landing yet.
var runsLanded = false;
//: Whether a list of runs has ever arrived. The rail can be on the runs
//: before a single row has - it is where this browser was left, and the
//: socket comes up after the page does - and a landing on a list nothing
//: has reached yet would mark the empty set seen and count itself done.
var RUNS_KNOWN = false;

//: Whether this run is one to go and look at: it stopped and nobody has
//: opened it since, or it was one of those when this visit began.
function runWantsLook(rec) {
  if (!rec) return false;
  return !!runsFlagged[rec.id] || (!rec.seen && runStopped(rec));
}

/* The dot on a run's own card. The same dot, in the same red, as the one on
   the tab above the list and the one on a task's row: it is one trail about
   one thing, and a trail that changes colour half way down is a trail nobody
   follows (`.sb-new` in app.css).

   A `data-act` rather than a listener of its own, because every press on a
   card is delegated to `onTaskClick` and Enter and space are answered in
   `onTaskKey`; a button that handled its own click would be pressed and open
   the run behind it as well. */
function runDot(rec) {
  var b = el('button', 'sb-new task-new');
  b.type = 'button';
  b.setAttribute('data-act', 'looked');
  var says = 'Needs a look: ' + taskWord(rec.status).toLowerCase()
    + ', and nobody has opened it since.\nPress to put this dot out.';
  b.title = says;
  b.setAttribute('aria-label', says);
  return b;
}

/* The person has looked at this one run: its dot was pressed, or the run
   itself was opened. Both take the dot off that card in the same instant,
   whichever of the two things it was standing for. */
function runLooked(rec) {
  if (!rec) return;
  var had = runWantsLook(rec);
  delete runsFlagged[rec.id];
  markSeen('run', rec, runStopped(rec) && !rec.seen);
  // `markSeen` repaints the tab and nothing else, because everything else it
  // is asked about is a row that redraws itself on the answer. A card is
  // drawn here, so the dot comes off here.
  if (had) renderTasks();
}

/* The runs list is on the screen, so it has been looked at.
 *
 * Called from `renderTasks`, so a list that arrives while the person is
 * already on it lands too, and from the two things that can put the list in
 * front of them: the switch at the top of the column and the drawer opening.
 * It asks the same question `runsUnseen` asks, because the tab's dot is what
 * it is here to put out.
 */
function runsLanding() {
  if (runsLanded || !RUNS_KNOWN) return;
  if (!runsViewing()) return;
  runsLanded = true;
  var look = [], k, rec;
  for (k in taskRecs) {
    rec = taskRecs[k];
    if (isDeploy(rec)) continue;
    if (!SHOW_ARCHIVED && rec.archived) continue;
    if (rec.seen || !runStopped(rec)) continue;
    runsFlagged[rec.id] = true;
    look.push(rec);
  }
  markRunsSeen(look);
}

//: The visit is over: they have switched to another list or closed the
//: drawer. The cards go back to saying what the rows say, which is nothing,
//: so the next visit starts clean - "the dots on the runs can stay until the
//: next time I come, when they should be gone".
function runsVisitOver() {
  runsLanded = false;
  var any = false, k;
  for (k in runsFlagged) { any = true; break; }
  if (!any) return;
  runsFlagged = Object.create(null);
  renderTasks();
}

//: Which of the two it is: the runs page opening or closing.
function runsShowing() {
  if (runsViewing()) runsLanding();
  else runsVisitOver();
}

// Walked rather than asked, because this runs against the page's own nodes
// and against the stand-in the column's tests drive it with.
function inside(host, node) {
  while (node) { if (node === host) return true; node = node.parentNode; }
  return false;
}

function focusedTask(host) {
  var on = document.activeElement;
  if (!on || !on.closest || !inside(host, on)) return null;
  var card = on.closest('.task');
  if (!card) return null;
  return { id: card.getAttribute('data-id'), act: !!on.closest('[data-act]') };
}

function refocusTask(host, had) {
  var cards = host.querySelectorAll('.task'), i, node;
  for (i = 0; i < cards.length; i++) {
    if (cards[i].getAttribute('data-id') !== had.id) continue;
    node = had.act ? cards[i].querySelector('[data-act]') : cards[i];
    if (node && node.focus) node.focus();
    return;
  }
}

/* The whole list.
 *
 * `whole` says this is a snapshot to be believed over what the tab already
 * holds, and only the handshake sends one: a fresh socket is a fresh start,
 * and what the server knows on it is the whole truth about this machine.
 * Anything else this tab is holding was told to it by a server that is not
 * there any more.
 *
 * That is what a stuck card is. Rouh restarting onto new code killed the
 * job that owned the "Updating Rouh" card mid-flight, so no finish was
 * ever sent; the page put its socket back, merged the list it was given, and
 * kept the card because merging never dropped anything. It said WORKING
 * until the page was reloaded. Now it does not survive the reconnect.
 *
 * Every other `tasks` message is still merged and nothing is dropped. A card
 * can be ahead of the database for a moment - a job announcing itself as it
 * starts - and a snapshot that crossed with it must not take it back off the
 * screen.
 */
function applyTaskList(list, whole) {
  if (!Array.isArray(list)) return;
  // A list of runs has reached this tab, so landing on the column means
  // something now. An empty list counts: it is an answer.
  RUNS_KNOWN = true;
  var here = Object.create(null), i;
  for (i = 0; i < list.length; i++) if (list[i]) here[String(mergeTask(list[i]).id)] = true;
  if (whole) {
    for (var k in taskRecs) if (!here[k]) delete taskRecs[k];
  }
  renderTasks();
  // And a page opened straight at a run's own address, which asked for it
  // before this list existed (see 10f).
  runsArrived(whole);
}

// Jobs the server has deleted for good: the throwaway ones a live check
// started. A list never drops an id, so the server names them, and they go
// from this tab at once rather than at the next reload.
function forgetTasks(ids) {
  if (!Array.isArray(ids)) return;
  for (var i = 0; i < ids.length; i++) delete taskRecs[ids[i]];
  renderTasks();
}

// One job changed. Merged by id, never a replacement for the list.
/** @param {import('./protocol').FromServer<'task'>} m */
function upsertTask(m) {
  mergeTask(m);
  renderTasks();
  runsArrived(false);
}

// Whether the column shows the runs the person has archived. The flag itself
// lives in the one program, with the run; this is only what this browser
// looks at, and it is remembered between reloads.
var SHOW_ARCHIVED = load('rouh.showArchived') === 'yes';
var showArchivedBox = $('showArchived');
if (showArchivedBox) {
  showArchivedBox.checked = SHOW_ARCHIVED;
  showArchivedBox.addEventListener('change', function () {
    SHOW_ARCHIVED = !!showArchivedBox.checked;
    store('rouh.showArchived', SHOW_ARCHIVED ? 'yes' : 'no');
    renderTasks();
  });
}

export { ago, applyTaskList, byStart, forgetTasks, jobClose, jobOpens, JOBVIEW, jobViewing,
  markSeen, openTask, railPaint, renderTasks, runsShowing, SHOW_ARCHIVED, since, taskCard,
  taskRecs, upsertTask, webClose, webFrame, webOpen, webState, webViewing, webWatch };
