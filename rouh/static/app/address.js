/* Rouh's page, the address of what is on the screen, and the front door (sections 10f and 10g of what was one app.js).
 *
 * Imports app/search.js first so that it runs after it, exactly where its
 * code ran in the one file: app.js says why that matters.
 */
import { findGo, RUN_WANTED } from 'app/search.js';
import { shared } from 'app/shared.js';
import { $, browserTakes, inAppLink, linkTo } from 'app/helpers.js';
import { navMark } from 'app/navgroups.js';
import { notify } from 'app/notices.js';
import { S, send } from 'app/socket.js';
import { stopPlayback } from 'app/playback.js';
import { endTurnOnScreen, wipeTranscript } from 'app/transcript.js';
import { CARDVIEW, cardViewing, clearTheCards, standingDown, WORKSPACE_ROUTE } from 'app/cards.js';
import { JOBVIEW, jobViewing, taskRecs, webOpen, webViewing } from 'app/tasks.js';
import { BRIEF, briefOpen, briefViewing, CANVAS, canvasDoc, controlOpen, controlViewing, CRUMB_HOME,
  WORK, workOpen, workViewing, DECIDE, decisionsOpen, decisionsViewing, receiptsOpen,
  receiptsViewing, homeOpen, homeViewing, APPROVALS, approvalsOpen, approvalsViewing, SOURCES, sourcesOpen, sourcesViewing, THOUGHTS, thoughtsOpen, thoughtsViewing,
  EVO, evolutionOpen, evolutionViewing,
  BOX, boxOpen, boxViewing,
  crumbLevels, goalsOpen, goalsViewing, goNow, MEMORY, memoryAddress, memoryOpen, memoryViewing, ONE, remindersOpen,
  remindersViewing, renderThreads, runsOpen, RUNSVIEW, runsViewing, SETTINGS, settingsAddress, settingsGroupName,
  settingsOpen, settingsRead, settingsViewing, SYNAPSE, synapseOpen, synapseViewing, TASK_PREFIX, tasksOpen,
  TASKS_VIEW, tasksViewing, TC, tcAddAsked, tcPerson, threadName, wsProjects } from 'app/runs.js';
import { chatById, CHATS, chatShow, forkTip, showCrumb } from 'app/chats.js';
import { welcomeShow } from 'app/welcome.js';
import { offlineOpen, offlineViewing } from 'app/offlineview.js';
import { canvasShown, chatIsWanted, panelsChoseCanvas, cols, drawerEntryTaken, drawerPopped, drawerUnwinding, narrow, setPane, TASKS_FULL,
  tasksTakeChat } from 'app/controls.js';

/* ---------------------------------------------------------------- 10f */

/* The address.
 *
 * Rouh is one document, so for a long time every one of its screens was the
 * same address: `/`. A chat opened, a task read, a project browsed and a run
 * watched were all `/`, and so none of them could be sent to anybody,
 * bookmarked, opened in a second tab, or reached again with Back. The person
 * asked for that on 22 September 2026: every chat, run, task, project or
 * other thing on the screen should have a URL of its own, and opening that
 * URL should go straight to that thing with that layout.
 *
 * Now it does. The scheme is one segment saying what it is and then the name
 * the thing already has, and `rouh/addressing.py` is the whole of it:
 *
 *     /chat/<id>                      a conversation
 *     /task/work/acme/19.pricing      a task, or a step of one
 *     /project/work/acme              a project
 *     /run/<id>                       a run
 *     /artifact/<id>                  a card
 *
 * **Navigation is not in the address.** Whether the sidebar is open, which
 * of its three lists is showing, whether the projects dashboard, Settings,
 * the search box or the Gene therapy drawer are up, and which pane a phone is
 * on, are all things a person does in order to look at an object. They are
 * not the object. None of them belongs in something you paste to somebody
 * else, so none of them is in it: there is no `?panel=`, no `#sidebar`, no
 * `&pane=`, and nothing in an address that a person would not recognise.
 *
 * Three rules keep the bar level with the screen, and they are the whole of
 * this section.
 *
 * 1. **What is written is read off the screen's own state, never
 *    remembered.** `addrNow` asks the same variables the drawing asks - the
 *    run being watched, the canvas's address, the active chat - so the bar
 *    cannot say something the screen does not, however the person got there.
 *    A task opened by clicking inside the workspace's own frame is addressed
 *    as surely as one opened from a row.
 * 2. **It is written once a press has finished happening.** One press moves
 *    several things: `showLayer` stands the other layers down, the chat
 *    follows the task, the rail redraws. `addrTouch` defers to the end of
 *    the tick so the bar is written from where all of that ended rather than
 *    three times on the way, which would have put two dead entries in the
 *    history for every click.
 * 3. **An address that has not been arrived at yet is never written over.**
 *    A page opened at `/task/…` is told which chat is active before it has
 *    finished opening the task, and that chat would otherwise overwrite
 *    where the page was going. `ADDR.wanted` holds the bar still until the
 *    page is there.
 *
 * Back and Forward are the same one path as everything else: the address is
 * read, the server is asked what it names (`find_object`), and what comes
 * back is the same open instruction a search result carries, pressed the
 * same way (`findGo`). A link, a search result, a second tab, a bookmark and
 * the Back button are one behaviour, not five.
 */

var ADDR = {
  // The address as this page last wrote it. A write that would change
  // nothing is not made, so nothing lands in the history for it.
  at: '',
  // Where the page is on its way to, and whether it has been asked for yet.
  // Nothing is written while this is set: see rule 3 above.
  wanted: null,
  asked: false,
  // Answers still to come for addresses the person has since pressed past
  // (`addrPressed`). The server answers one socket's questions in order, so
  // the next this many are dropped rather than opened over what they chose.
  dropping: 0,
  // The place in the page the address named, while that page is being
  // opened for it (`addrFound`).
  hash: '',
  // The first write of a page's life replaces rather than pushes: nobody
  // navigated, the page simply settled on what it was already showing.
  settled: false,
  // And so does the one after Back or Forward, for the same reason: the
  // person moved through the history, they did not add to it.
  replace: false,
  // What the server has said a workspace folder is, for the moment before
  // the rail's own list of projects has arrived (`findGo`).
  kinds: Object.create(null),
  // A conversation opened because an address named it. The canvas follows
  // the conversation everywhere else; here the address has already said
  // what goes on the canvas, so this one switch does not move it.
  forChat: '',
  // And the other way round: a page opened because an address named it
  // beside a conversation. Opening a task's page picks that task's own
  // conversation everywhere else (`pickThread`); here the address has
  // already said which conversation is beside it, so this one load does
  // not replace it (`addrFound`).
  chatNamed: false,
  // Whether this page is at the front door: opened at `/`, which names
  // nothing, and nothing opened on it since. See 10g.
  front: false,
  // The task whose conversation opening its page has asked the server for
  // (`pickThread`), and the address written while it was on its way. The
  // page is on the screen a round trip before its conversation is beside
  // it, so the bar is written twice for the one press: the task beside the
  // conversation that was open, then the task beside its own. Both were
  // pushed until 23 September 2026, which left an entry for every task
  // opened that Back landed on - the task, beside General - instead of
  // going back to where the person was. The second write replaces the first
  // now, as long as nothing else has been written in between
  // (`onChatSwitched`).
  thread: '',
  half: '',
  // The person pressed somewhere before the handshake had said which
  // conversation they are in (`addrPressed`). When it does, the bar takes
  // that conversation beside what they chose, and that is no step of theirs:
  // it replaces, or Back would land on the same page without it.
  early: false
};

/* The tab's title on a page of Trials: the page's own name when it said one, then where it is. */
function trialsTitle(sub, title) {
  var where = sub === 'problems' ? 'Problems' : sub === 'testers' ? 'Testers' : sub === 'testers/new' ? 'New tester'
    : sub === 'how' ? 'How trials work' : /^job\//.test(sub) ? 'Job ' + sub.slice(4)
    : /^problem\//.test(sub) ? 'Problem ' + sub.slice(8) : /^tester\//.test(sub) ? 'Tester'
    : /^\d+$/.test(sub) ? 'Try ' + sub : '';
  if (!where) return 'Trials';
  return (title ? title + ' - ' : '') + where + ' - Trials';
}

/* One object's address. The two that are folders in the workspace are named
   by their folder, because that is what they are called everywhere a person
   meets them; the other three have no folder and are named by their id.
   Same rule as `addressing.name_of`, and the server is what decides it for
   a row (`searching._line` puts the address on every one). */
function addrOf(kind, name) {
  if (!kind || !name) return '';
  return '/' + kind + '/'
    + String(name).split('/').map(encodeURIComponent).join('/');
}

//: The five words an address may begin with, and the five the server
//: answers (`addressing.KINDS`). Anything else is not an address.
var ADDR_KINDS = ['chat', 'task', 'project', 'run', 'artifact'];

/* The task browser's own top, which is the one address that names a place
   rather than an object (`addressing.BROWSER`). It had none until
   22 September 2026, and the cost of that was not a missing link: with
   nothing of its own to say, the bar fell through to the conversation
   underneath, and a conversation a numbered task owns carries that task's
   address - so pressing Task browser after reading task 19 left the bar
   saying `/task/work/acme/19.pricing` over a screen showing the whole
   workspace. Plural, against `/task/<folder>` singular. */
var ADDR_BROWSER = '/tasks';
//: The Live browser, which is a place like the task browser's top rather
//: than an object (`addressing.WEB`).
var ADDR_WEB = '/browser';
//: Clockwork and the Goals page, two more places (`addressing.CLOCKWORK`,
//: `addressing.GOALS`). Clockwork was Reminders, at /reminders, until 8 October
//: 2026; that address is read as Clockwork's still, and the bar then says
//: /clockwork, so an old link or bookmark lands where it always did.
var ADDR_REMINDERS = '/clockwork';
var ADDR_REMINDERS_OLD = '/reminders';
var ADDR_GOALS = '/goals';
//: The Control Room, one more place (`addressing.CONTROL`).
var ADDR_CONTROL = '/control';
//: Metabolism, the runs page, one more (`addressing.METABOLISM`): everyday work
//: at /metabolism, and the runs that change Rouh itself at /metabolism/mutations.
//: It was Runs, at /runs, until 14 October 2026; that address is read as
//: Metabolism's still, and the bar then says /metabolism.
var ADDR_RUNS = '/metabolism';
var ADDR_RUNS_OLD = '/runs';
//: The morning brief (`addressing.BRIEF`).
var ADDR_BRIEF = '/brief';
//: The heartbeat's old address, which lands on its section of Anatomy
//: (`addressing.HEARTBEAT`), and the quests, every one and each by its task's number
//: (`addressing.QUESTS`). A quest's old address, `/work/<id>`, is sent on by the server.
var ADDR_HEARTBEAT = '/heartbeat';
var ADDR_WORK = '/quests';
//: Decisions, every one and one in focus by its number (`addressing.DECISIONS`).
var ADDR_DECISIONS = '/decisions';
//: Receipts, every receipt and invoice in the mail by month (`addressing.RECEIPTS`).
var ADDR_RECEIPTS = '/receipts';
//: Home, the house's lights and devices (`addressing.HOME`).
var ADDR_HOME = '/home';
//: Agent instructions, what every agent Rouh starts is told first (`addressing.AGENT_INSTRUCTIONS`): rules since
//: 30 October 2026, so the address opens the Rules page on those with their Agent switch on, `/rules?label=agent`.
var ADDR_INSTR = '/agent-instructions';
//: Rules, every rule Rouh follows, one group of them open at /rules/<group>, and What context/rules were included at
//: /rules/told; `?label=` shows only the rules with the labels it names, one or several, `?label=from-chat,agent`
//: (`?from=`, its name until 30 October 2026, still does) (`addressing.RULES`).
var ADDR_RULES = '/rules';
//: Approvals, what Rouh stopped on for the person's decision (`addressing.MAIL_APPROVALS`).
var ADDR_APPROVALS = '/mail/approvals';
//: One of them, a mail case, by its random key, in the same layer (`addressing.MAIL_CASE`).
var ADDR_CASE = '/mail/case';
//: One task's footnoted pages, their sources checked, by the task's or step's folder
//: (`addressing.SOURCES`). Alone, with no folder, it is the task browser's: Sources
//: belongs to a task since 13 October 2026 (fr_fce8f51c00d6).
var ADDR_SOURCES = '/sources';
//: Evolution: Parameters; Mutations, its views and one gene (with the old views' and the
//: morning deck's addresses, which `evolutionpage.js` sends on); and the Gene Pool and one
//: family of it (`addressing.EVOLUTION`, `rouh/evolution.py`).
var ADDR_EVOLUTION = '/evolution';
// Its lists are `new` (where it opens), `trial`, `passed` and `failed`, and its month view `month`,
// since 19 October 2026 (fr_650809f11685); `out` (Out of trial, 18 October), `week`, `deck` and the four older
// names are still read, and open the view each became (fr_d658dc2bb730).
var EVO_SUB = /^(new|trial|passed|failed|unused|month|out|review|rouh|off|rejected|week|deck|log|log\/\d+|gene\/\d+(\/(essence|trial|versions|history|card|mutations|decisions|questions|learning))?)$/;
// The Pool's families by id; since 25 October 2026 its two pages, `outgoing` (with one gene on it) and
// `incoming`; `yours`, the outgoing list's address from 22 October, still opens it.
var EVO_POOL = /^([0-9a-f]{1,16}|yours|yours\/\d+|outgoing|outgoing\/\d+|incoming)$/;
//: The person's thoughts, every one and one in focus by its number (`addressing.THOUGHTS`).
var ADDR_THOUGHTS = '/thoughts';
//: The box, what the person keeps from the model (`addressing.BOX`).
var ADDR_BOX = '/box';
//: What this device keeps for when there is no connection (`addressing.OFFLINE`).
var ADDR_OFFLINE = '/offline';
//: Gene therapy, a door rather than a place (`addressing.GENE_THERAPY`): the page with the
//: drawer open, which is navigation and so never what the bar says afterwards. It was
//: Feedback until 12 October 2026, and /feedback is sent here by the server.
var ADDR_GENE_THERAPY = '/gene-therapy';
//: Synapse's lab, and one dataset of it (`addressing.SYNAPSE`).
var ADDR_SYNAPSE = '/synapse';
//: Anatomy, its groups under it and a section of each under that (`addressing.ANATOMY`),
//: and Settings, whose addresses until 14 October 2026 each name a section of one now.
var ADDR_ANATOMY = '/anatomy';
var ADDR_SETTINGS = '/settings';

/* What one address holds, or null where it holds nothing - which is what
   the front door is.

   The path is the object on the canvas and `chat` is the conversation
   beside it, and an address may carry either on its own: `/chat/<id>` is a
   conversation with nothing loaded, `/run/<id>` is a run beside whatever
   conversation is open, and the two together are the whole screen. */
/* `strip` is where the strip of forks laid out around that conversation
   ends, when it goes on past it to the right: `/chat/<id>?strip=<fork>` is
   a chat with a fork of it open beside it (`forks.strip`). The strip is the
   tab's own, and the address is how a reload, a link and Back bring the
   same one back (principle B2). */
function addrRead(path, query) {
  var got = addrReadPlace(path, query);
  if (got) {
    var found = /[?&]strip=([^&#]*)/.exec(String(query || ''));
    var strip = '';
    if (found) {
      try { strip = decodeURIComponent(found[1]); } catch (err) { strip = found[1]; }
    }
    got.strip = strip;
  }
  return got;
}

function addrReadPlace(path, query) {
  var parts = String(path || '').split('?')[0].split('/').filter(Boolean);
  var chat = '';
  var found = /[?&]chat=([^&#]*)/.exec(String(query || ''));
  if (found) {
    try { chat = decodeURIComponent(found[1]); } catch (err) { chat = found[1]; }
  }
  // The one that names no object on the canvas. It carries `browser` rather
  // than a kind and an id, and `addrAsk` acts on it there instead of asking
  // the server; it takes a conversation beside it like any other path.
  if (parts.length === 1 && '/' + parts[0] === ADDR_BROWSER) {
    // And which list it shows, `?view=rouh=thoughts` (`addrWithView`).
    var view = /[?&]view=([^&#]*)/.exec(String(query || ''));
    var said = '';
    if (view) {
      try { said = decodeURIComponent(view[1]); } catch (err) { said = view[1]; }
    }
    return { kind: '', id: '', chat: chat, browser: true, view: said };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_WEB) {
    return { kind: '', id: '', chat: chat, web: true };
  }
  if (parts.length === 1 && ('/' + parts[0] === ADDR_REMINDERS || '/' + parts[0] === ADDR_REMINDERS_OLD)) {
    return { kind: '', id: '', chat: chat, clock: 'reminders' };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_GOALS) {
    return { kind: '', id: '', chat: chat, clock: 'goals' };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_CONTROL) {
    return { kind: '', id: '', chat: chat, control: true };
  }
  // `runs` is the tab named, or '' for none, which opens on Everyday work unless
  // it was opened from Evolution or over a mutation's run (`runsOpen`).
  if ('/' + parts[0] === ADDR_RUNS || '/' + parts[0] === ADDR_RUNS_OLD) {
    if (parts.length === 1) return { kind: '', id: '', chat: chat, runs: '' };
    if (parts.length === 2 && (parts[1] === 'mutations' || parts[1] === 'everyday')) {
      return { kind: '', id: '', chat: chat, runs: parts[1] === 'mutations' ? 'mutation' : 'everyday' };
    }
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_BRIEF) {
    return { kind: '', id: '', chat: chat, brief: '' };
  }
  // Every brief kept, and one of them by its day (fr_5fb00def9d2d).
  if (parts.length === 2 && '/' + parts[0] === ADDR_BRIEF &&
      (parts[1] === 'past' || /^\d{4}-\d{2}-\d{2}$/.test(parts[1]))) {
    return { kind: '', id: '', chat: chat, brief: parts[1] };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_HEARTBEAT) {
    return { kind: '', id: '', chat: chat, settings: 'heartbeat' };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_WORK) {
    return { kind: '', id: '', chat: chat, work: '' };
  }
  // A quest by its record, `/work/<id>`, as its first links said: the server
  // knows its number (`web/quests.old_address`).
  if (parts.length === 2 && parts[0] === 'work' && /^\d+$/.test(parts[1])) {
    return { kind: '', id: '', chat: chat, work: '', record: parts[1] };
  }
  if (parts.length === 2 && '/' + parts[0] === ADDR_WORK && /^\d+$/.test(parts[1])) {
    return { kind: '', id: '', chat: chat, work: parts[1] };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_DECISIONS) {
    return { kind: '', id: '', chat: chat, decisions: '' };
  }
  // One by its number (`decision_numbers.py`). A handle it had (a482) is sent on to its
  // number by the server (`web/decisions.old_address`).
  if (parts.length === 2 && '/' + parts[0] === ADDR_DECISIONS && /^\d+$/.test(parts[1])) {
    return { kind: '', id: '', chat: chat, decisions: parts[1] };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_RECEIPTS) {
    return { kind: '', id: '', chat: chat, receipts: true };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_HOME) {
    return { kind: '', id: '', chat: chat, home: true };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_INSTR) {
    return { kind: '', id: '', chat: chat, rules: '', from: 'agent' };
  }
  if ('/' + parts[0] === ADDR_RULES && (parts.length === 1 || (parts.length === 2 && /^[a-z]{2,20}$/.test(parts[1])))) {
    var from = /[?&](?:label|from)=([a-z,-]+)/.exec(String(query || ''));
    return { kind: '', id: '', chat: chat, rules: parts[1] || '', from: from ? from[1] : '' };
  }
  if (parts.length === 2 && '/' + parts.join('/') === ADDR_APPROVALS) {
    return { kind: '', id: '', chat: chat, approvals: true };
  }
  // Only the case itself: its files and the rest under it are the server's.
  if (parts.length === 3 && '/' + parts.slice(0, 2).join('/') === ADDR_CASE && /^[A-Za-z0-9_-]{6,80}$/.test(parts[2])) {
    return { kind: '', id: '', chat: chat, approvals: true, mailCase: parts[2] };
  }
  if ('/' + parts[0] === ADDR_SOURCES) {
    if (parts.length === 1) return { kind: '', id: '', chat: chat, browser: true };
    return { kind: '', id: '', chat: chat, sources: addrTrimmed(parts.slice(1).join('/')) };
  }
  if ('/' + parts[0] === ADDR_EVOLUTION) {
    if (parts.length === 1) return { kind: '', id: '', chat: chat, evolution: { page: 'mutations', sub: '' } };
    if (parts.length === 2 && parts[1] === 'parameters') {
      return { kind: '', id: '', chat: chat, evolution: { page: 'parameters', sub: '' } };
    }
    // The Incubator, and one idea in it by its number; and the nightly feature run's own page.
    if (parts[1] === 'incubator' && (parts.length === 2 || (parts.length === 3 && /^(INC-)?\d{1,6}$/i.test(parts[2])))) {
      return { kind: '', id: '', chat: chat, evolution: { page: 'incubator', sub: parts.length === 3 ? 'INC-' + parts[2].replace(/^INC-/i, '') : '' } };
    }
    // Trials: every try, one try by its number, and the list of problems.
    // Trials: the jobs, one job, one try by its number, the problems and one problem, the testers, one
    // tester and the form that adds or changes one, and how trials work.
    if (parts[1] === 'trials' && /^(?:|\d{1,6}|problems|job\/\d{1,6}|problem\/\d{1,6}|testers|testers\/new|tester\/[a-z0-9]{1,40}(?:\/edit)?|how)$/
        .test(parts.slice(2).join('/'))) {
      return { kind: '', id: '', chat: chat, evolution: { page: 'trials', sub: parts.slice(2).join('/') } };
    }
    if (parts.length === 2 && parts[1] === 'nightly') {
      return { kind: '', id: '', chat: chat, evolution: { page: 'nightly', sub: '' } };
    }
    // Mutations was the Gene library, at `/evolution/library`, until 14 October 2026, and the
    // Gene Pool one of its views (fr_a982710d30c7): a link kept in a notice or a decision from
    // then opens where it is now.
    var evoOld = parts[1] === 'library' && parts[2] === 'pool';
    if (parts[1] === 'pool' || evoOld) {
      var poolSub = parts.slice(evoOld ? 3 : 2).join('/');
      if (!poolSub || EVO_POOL.test(poolSub)) {
        return { kind: '', id: '', chat: chat, evolution: { page: 'pool', sub: poolSub } };
      }
    }
    if (parts[1] === 'mutations' || parts[1] === 'library') {
      var evoSub = parts.slice(2).join('/');
      if (!evoSub || EVO_SUB.test(evoSub)) {
        return { kind: '', id: '', chat: chat, evolution: { page: 'mutations', sub: evoSub } };
      }
    }
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_BOX) {
    return { kind: '', id: '', chat: chat, box: '' };
  }
  if (parts.length === 2 && '/' + parts[0] === ADDR_BOX && /^\d+$/.test(parts[1])) {
    return { kind: '', id: '', chat: chat, box: parts[1] };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_THOUGHTS) {
    return { kind: '', id: '', chat: chat, thoughts: '' };
  }
  if (parts.length === 2 && '/' + parts[0] === ADDR_THOUGHTS && /^\d+$/.test(parts[1])) {
    return { kind: '', id: '', chat: chat, thoughts: parts[1] };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_OFFLINE) {
    return { kind: '', id: '', chat: chat, offline: true };
  }
  if (parts.length === 1 && '/' + parts[0] === ADDR_GENE_THERAPY) {
    return { kind: '', id: '', chat: chat, geneTherapy: true };
  }
  // The lab's Improvements page, and one attempt on it (`rouh/synapse/improvements.py`).
  if (parts.length === 3 && '/' + parts[0] === ADDR_SYNAPSE && parts[1] === 'improvements' && /^\d+$/.test(parts[2])) {
    return { kind: '', id: '', chat: chat, synapse: 'improvements/' + parts[2] };
  }
  // A dataset's Dreams page, one night on it, or what waits (`rouh/synapse/dreaming.py`).
  if ((parts.length === 3 || parts.length === 4) && '/' + parts[0] === ADDR_SYNAPSE && parts[2] === 'dreams' &&
      /^[0-9a-f-]{36}$/.test(parts[1]) && (parts.length === 3 || /^(\d+|waiting)$/.test(parts[3]))) {
    return { kind: '', id: '', chat: chat, synapse: parts.slice(1).join('/') };
  }
  if (parts.length <= 2 && parts.length && '/' + parts[0] === ADDR_SYNAPSE) {
    return { kind: '', id: '', chat: chat, synapse: parts[1] || '' };
  }
  // Anatomy's status board, one of its groups, or a section of one with what is opened in
  // it; and Settings' old addresses, each the section it named (`settingsRead`). A name this
  // page does not know is the board, where the groups are there to pick from.
  if (parts.length && ('/' + parts[0] === ADDR_ANATOMY || '/' + parts[0] === ADDR_SETTINGS)) {
    var at = settingsRead(parts.slice(1), '/' + parts[0] === ADDR_SETTINGS);
    // A moved section's old address is nowhere on this page: the server's, which is not found.
    if (at.gone) return null;
    // Somebody to set up on Trusted contacts, asked for by address (`tcAddAsked`).
    var asked = new URLSearchParams(String(query || ''));
    // And what a section keeps in the query, such as the beats' filters (`beatspage.js`).
    var kept = new URLSearchParams(String(query || ''));
    ['chat', 'strip', 'add', 'name'].forEach(function (k) { kept.delete(k); });
    return { kind: '', id: '', chat: chat, settings: at.where, item: at.item,
      add: asked.get('add') || '', addName: asked.get('name') || '', query: kept.toString() };
  }
  if (!parts.length || ADDR_KINDS.indexOf(parts[0]) < 0) {
    return chat ? { kind: '', id: '', chat: chat } : null;
  }
  var name = parts.slice(1).map(function (p) {
    try { return decodeURIComponent(p); } catch (err) { return p; }
  }).join('/');
  if (!name) return chat ? { kind: '', id: '', chat: chat } : null;
  return { kind: parts[0], id: name, chat: chat };
}

/* Where in the workspace the canvas is, as two paths.

   `folder` is the task or project whose page it is, which decides the word
   at the front of the address. `rel` is exactly what is shown, which is the
   rest of it: that folder itself, or one of its notes, a folder of one of
   its steps, a code file, or a page one of them built. Read off `CANVAS`
   rather than kept beside it: `canvasLoad` is reached from the rail, the
   breadcrumb, a search result and a link clicked inside the frame, and only
   the address it ended at is true for all four.

   `rel` went no deeper than the step until 23 September 2026, so opening a
   folder or a note on a task's page left the bar on the task and Back had
   nothing to go back to. Petar: "urls should change on every click." It is
   the path of the thing now, the same path the eyebrow over it shows, and
   `addressing.inside` reads it back. */
function addrPlace() {
  if (!tasksViewing()) return { folder: '', rel: '' };
  var at = String(CANVAS.at || ''), path = at.split('?')[0], rel;
  if (path.indexOf(TASK_PREFIX) === 0) {
    rel = addrTrimmed(path.slice(TASK_PREFIX.length));
    var doc = canvasDoc();
    return { folder: rel, rel: doc ? rel + '/' + doc : rel };
  }
  // A page is named by where it is, which is its own file.
  if (path.indexOf(WORKSPACE_ROUTE) === 0) {
    rel = addrTrimmed(path.slice(WORKSPACE_ROUTE.length));
    if (rel) return { folder: CANVAS.task || rel, rel: rel };
  }
  // A step drawn from its blocks (`canvasStep`), which has no address of
  // its own in the frame.
  rel = CANVAS.step || CANVAS.task || '';
  return { folder: rel, rel: rel };
}

function addrTrimmed(rel) {
  try { rel = decodeURIComponent(rel); } catch (err) {}
  return rel.replace(/^\/+|\/+$/g, '');
}

// What the canvas is showing, as a workspace path (`addrPlace`).
function addrFolder() { return addrPlace().rel; }

/* Is this folder one of the workspace's projects rather than a task? The
   rail already holds every project with its folder (`wsProjects`), so the
   two are told apart here without asking the server, which is what lets the
   bar be written in the same tick as the click. */
function addrIsProject(rel) {
  if (ADDR.kinds[rel]) return ADDR.kinds[rel] === 'project';
  var all = wsProjects(), i;
  for (i = 0; i < all.length; i++) if (all[i].folder === rel) return true;
  return false;
}

/* A workspace folder's address, a project's or a task's by which it is. */
function addrOfFolder(rel) {
  return addrOf(addrIsProject(rel) ? 'project' : 'task', rel);
}

/* What is on the screen, as an address.

   In the order one thing covers another: a run's terminal and a workspace
   page are both on the canvas and only one of them can be there, and
   underneath both of them there is always a conversation.

   A run with no terminal of its own - a worker here rather than a run of
   the one program - opens on the canvas as well since 24 September 2026
   (`jobOpen`), and is addressed the same way, `/run/<id>`: to whoever
   follows the link, a job is a job. */
function addrOnCanvas() {
  // A card being read is the thing on the canvas, and it has an address of
  // its own, so the bar says it and a link to it comes back to it.
  if (cardViewing()) return addrOf('artifact', CARDVIEW.id);
  // Settings lies over whatever else is open, so it is what is in front.
  if (settingsViewing()) return settingsAddress();
  if (ONE && ONE.viewing && ONE.selected) return addrOf('run', ONE.selected);
  if (jobViewing()) return addrOf('run', JOBVIEW.id);
  if (webViewing()) return ADDR_WEB;
  if (remindersViewing()) return ADDR_REMINDERS;
  if (goalsViewing()) return ADDR_GOALS;
  if (controlViewing()) return ADDR_CONTROL;
  if (synapseViewing()) return ADDR_SYNAPSE + (SYNAPSE.ds ? '/' + SYNAPSE.ds : '');
  if (runsViewing()) return ADDR_RUNS + (RUNSVIEW.kind === 'mutation' ? '/mutations' : '');
  if (briefViewing()) return ADDR_BRIEF + (BRIEF.view ? '/' + BRIEF.view : '');
  if (workViewing()) return ADDR_WORK + (WORK.id ? '/' + WORK.id : '');
  if (decisionsViewing()) return ADDR_DECISIONS + (DECIDE.id ? '/' + DECIDE.id : '');
  if (receiptsViewing()) return ADDR_RECEIPTS;
  if (homeViewing()) return ADDR_HOME;
  if (memoryViewing()) return memoryAddress();
  if (approvalsViewing()) return APPROVALS.key ? ADDR_CASE + '/' + encodeURIComponent(APPROVALS.key) : ADDR_APPROVALS;
  if (sourcesViewing()) return ADDR_SOURCES + '/' + SOURCES.folder.split('/').map(encodeURIComponent).join('/');
  if (evolutionViewing()) return ADDR_EVOLUTION + '/' + EVO.page + (EVO.page !== 'parameters' && EVO.page !== 'nightly' && EVO.sub ? '/' + EVO.sub : '');
  if (thoughtsViewing()) return ADDR_THOUGHTS + (THOUGHTS.id ? '/' + THOUGHTS.id : '');
  if (boxViewing()) return ADDR_BOX + (BOX.id ? '/' + BOX.id : '');
  if (offlineViewing()) return ADDR_OFFLINE;
  if (!tasksViewing()) return '';
  var place = addrPlace();
  // The tasks are up with nothing opened out of them, which is the browser's
  // own top and has its own address. Answering '' here is what let the bar
  // fall through to the conversation and name a task nobody was looking at.
  if (!place.rel) return ADDR_BROWSER;
  return addrOf(addrIsProject(place.folder) ? 'project' : 'task', place.rel);
}

/* Is what the canvas is showing the conversation's own?

   A task's page beside that task's thread is one object on the screen, not
   two: they are the same task, and one address says both. A step of it is
   the same task's as well. Anything else - a project beside a chat, a run
   beside a chat - is two things, and the address has to say both of them. */
function addrIsTheChats(rel, chat) {
  if (!addrIsTasksOwn(chat)) return false;
  return rel === chat.task || rel.indexOf(chat.task + '/') === 0;
}

/* Is this chat the one its task's address brings back?

   A task has one conversation, the one opening it opens, and only that one
   is the task twice over. Another chat put under the task with Where this
   belongs is the task's too, but `/task/<folder>` alone opens the task's
   own and not that one, so that one is named beside the task's page like
   any other chat is (`thread`, from `conversations._as_row`). A row from a
   server older than the flag has none and is taken as the task's own, which
   is what every task chat was taken as before. */
function addrIsTasksOwn(chat) {
  return !!(chat && chat.task && chat.thread !== false);
}

/* Is the conversation one of the panels, or is it folded away?

   A project browsed on its own takes the whole window, and a column that
   has been folded is not on the screen - naming a conversation that is not
   there would be the same fault from the other end. The fold and nothing
   else: which pane a phone is showing is navigation, both panes are open
   behind it, and an address is the same address on a phone and at a desk
   (`sbApply` draws exactly this pair as `no-chat`). */
function addrChatIsShowing() {
  return !!(typeof cols !== 'undefined' && cols.chat && !TASKS_FULL);
}

/* What is on the screen, as an address - **both panels of it**.

   The middle of this page is two panels, and for a while the address named
   only one. Petar caught it on 22 September 2026 with a run open beside a
   conversation: the bar said `/run/42e4cff6` and said nothing about the
   chat two inches to its left, so opening that link again put the run next
   to whichever conversation happened to be active rather than next to that
   one. The screen was two things and the address was one.

   So it is two now, when they are two:

       /task/work/acme/19.pricing            one thing: the task's page, and
                                             the task's own thread beside it
       /run/42e4cff6?chat=chat-9f2a1b3c      two: the run, and the
                                             conversation it is open beside
       /project/work/acme?chat=…             two: the project's page, and
                                             the conversation beside it

   **The query names an object, never a panel.** It is the conversation - a
   chat, by the only name a chat has - and it is there for exactly the
   reason the path is there: something is on the screen and a link has to
   bring it back. There is still no `?panel=`, no `?sidebar=`, no `?pane=`,
   and nothing in an address that is not a thing you can point at. */
/* The task browser's top with the list it is showing: the Archive, Others'
   tasks, Made by Rouh and the process picked there, a column or a project
   (`taskbrowser.js`, `rouh-page-view`), as `/tasks?view=rouh=thoughts`. In the
   address, so a reload, a link opened in a new tab and Back from a task come
   to the same list (principle B2). */
function addrWithView(addr) {
  // The beats' search and filters, the same way (`beatspage.js`).
  if (settingsViewing() && SETTINGS.section === 'beats' && SETTINGS.beatsQuery) {
    return addr + (addr.indexOf('?') === -1 ? '?' : '&') + SETTINGS.beatsQuery;
  }
  if (!TASKS_VIEW.view || addr.split('?')[0] !== ADDR_BROWSER) return addr;
  return addr + (addr.indexOf('?') === -1 ? '?' : '&') + 'view=' + encodeURIComponent(TASKS_VIEW.view);
}

/* The end of the strip of forks around the conversation, when it goes on
   past the conversation to the right, or '' (`addrRead`). */
function addrStripNow() {
  var tip = forkTip();
  return tip && CHATS && tip !== CHATS.active ? tip : '';
}

function addrWithStrip(addr) {
  var tip = addrStripNow();
  if (!tip) return addr;
  return addr + (addr.indexOf('?') === -1 ? '?' : '&') + 'strip=' + encodeURIComponent(tip);
}

function addrNow() {
  var chat = CHATS && CHATS.active ? chatById(CHATS.active) : null;
  // A canvas put away is not on the screen, so the address does not name
  // what is left loaded on it - not even a task's page beside its own chat,
  // which would open the canvas again on a reload (`canvasShown`).
  var away = !narrow() && !canvasShown();
  var on = away ? '' : addrOnCanvas();
  if (!on) {
    if (!chat) return CHATS && CHATS.active ? addrWithStrip(addrOf('chat', CHATS.active)) : '/';
    if (away) return addrWithStrip(addrOf('chat', chat.id));
    // A conversation a numbered task owns **is** that task - one object, not
    // two that can drift, which is the whole of why the rail names such a
    // thread after its task and there is nothing to switch to. So it has one
    // address and that address is the task's. Opening it comes back to
    // exactly here: the task's page on the canvas, and its thread picked.
    return addrWithStrip(addrIsTasksOwn(chat) ? addrOf('task', chat.task) : addrOf('chat', chat.id));
  }
  if (!addrChatIsShowing()) return addrWithView(on);
  if (addrIsTheChats(addrFolder(), chat)) return addrWithView(addrWithStrip(on));
  var id = chat ? chat.id : (CHATS && CHATS.active) || '';
  // A place whose address has a query of its own (`/rules?label=agent`) takes the conversation after it.
  return addrWithView(addrWithStrip(id ? on + (on.indexOf('?') === -1 ? '?' : '&') + 'chat=' + encodeURIComponent(id) : on));
}

/* A link to one of the places, made from where the person is now.

   The place, and the conversation they are in beside it - which is exactly
   what the bar says once a plain press has opened it there (`addrNow`) - so
   a new tab opened onto Clockwork with Cmd is the same screen the press
   would have made in this one. At the front door there is no conversation,
   and the place goes alone. */
function addrPlaceLink(place) {
  var id = CHATS && CHATS.active;
  return id && !ADDR.front ? place + '?chat=' + encodeURIComponent(id) : place;
}

/* The sidebar's rows are links (`linkTo`), to these addresses. The task
   browser's is `/tasks` alone: it takes the conversation's column as well,
   so there is nothing beside it to name. Rouh's own row is its chat, once
   the server has said which chat that is. */
[['runsRow', ADDR_RUNS], ['briefRow', ADDR_BRIEF], ['controlRow', ADDR_CONTROL],
 ['synapseRow', ADDR_SYNAPSE], ['remindersRow', ADDR_REMINDERS], ['goalsRow', ADDR_GOALS],
 ['questsRow', ADDR_WORK], ['decisionsRow', ADDR_DECISIONS], ['crDecisions', ADDR_DECISIONS],
 ['receiptsRow', ADDR_RECEIPTS], ['homeBtn', ADDR_HOME], ['approvalsRow', ADDR_APPROVALS], ['thoughtsRow', ADDR_THOUGHTS],
 ['boxRow', ADDR_BOX],
 ['webRow', ADDR_WEB]].forEach(function (row) {
  var a = $(row[0]);
  if (a) linkTo(a, function () { return addrPlaceLink(row[1]); });
});
if ($('generalRow')) {
  linkTo($('generalRow'), function () {
    return CHATS && CHATS.general ? addrOf('chat', CHATS.general) : '';
  });
}

/* What the tab is called, so a bookmark and a pasted link read as the thing
   rather than as the app. The name is the one already on the screen for
   whatever `addrNow` just addressed. */
function addrName() {
  if (cardViewing()) return CARDVIEW.title || 'Card';
  // Anatomy lies over whatever else is open, as `addrOnCanvas` says, so the tab is called
  // what is in front and not Metabolism or a run left under it.
  if (settingsViewing()) {
    if (SETTINGS.section === 'trusted-contacts' && TC.open === 'grants') return 'Grants - Trusted contacts';
    var opened = SETTINGS.section === 'trusted-contacts' && TC.open && tcPerson(TC.open);
    if (opened) return (opened.name || 'Trusted contact') + ' - Trusted contacts';
    // A section is a page of its own inside its group: "Payments - Money".
    if (SETTINGS.section) return settingsGroupName(SETTINGS.section) + ' - ' + settingsGroupName(SETTINGS.page);
    return settingsGroupName(SETTINGS.page) || 'Anatomy';
  }
  if (ONE && ONE.viewing && ONE.selected) return addrRunName(ONE.selected);
  if (jobViewing()) return addrRunName(JOBVIEW.id);
  if (webViewing()) return 'Live browser';
  if (remindersViewing()) return 'Clockwork';
  if (goalsViewing()) return 'Goals';
  if (controlViewing()) return 'Control room';
  if (synapseViewing()) return SYNAPSE.ds && SYNAPSE.name ? SYNAPSE.name + ' - Synapse' : 'Synapse';
  if (runsViewing()) return RUNSVIEW.kind === 'mutation' ? 'Mutations - Metabolism' : 'Metabolism';
  if (briefViewing()) {
    if (BRIEF.view === 'past') return 'Past briefs';
    if (!BRIEF.view) return 'Morning brief';
    // "Morning brief, Wednesday 7 October", for one kept on another day.
    var on = new Date(BRIEF.view + 'T12:00:00Z');
    return 'Morning brief, ' + (isNaN(on.getTime()) ? BRIEF.view : on.toLocaleDateString('en-GB',
      { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long' }));
  }
  if (workViewing()) return WORK.id ? (WORK.title || 'Quest ' + WORK.id) + ' - Quests' : 'Quests';
  if (decisionsViewing()) return 'Decisions';
  if (receiptsViewing()) return 'Receipts';
  if (homeViewing()) return 'Home';
  if (memoryViewing()) {
    if (MEMORY.group === 'told') return 'What context/rules were included - Rules';
    if (MEMORY.group === 'agents') return 'What agents start with - Rules';
    var g = ((MEMORY.data && MEMORY.data.groups) || []).filter(function (x) { return x.key === MEMORY.group; })[0];
    return g ? g.name + ' - Rules' : 'Rules';
  }
  if (approvalsViewing()) return APPROVALS.key ? (APPROVALS.name ? APPROVALS.name + ' - Approvals' : 'Approvals') : 'Approvals';
  if (sourcesViewing()) return SOURCES.title ? 'Sources - ' + SOURCES.title : 'Sources';
  if (evolutionViewing()) return EVO.page === 'parameters' ? 'Parameters - Evolution'
    : EVO.page === 'incubator' ? (EVO.sub ? EVO.sub + (EVO.title ? ' ' + EVO.title : '') + ' - Incubator' : 'Incubator')
    : EVO.page === 'nightly' ? 'Nightly run - Evolution'
    : EVO.page === 'trials' ? trialsTitle(EVO.sub, EVO.title)
    : EVO.page === 'pool' ? (EVO.sub && EVO.title ? EVO.title + ' - Gene Pool' : EVO.title || 'Gene Pool')
    : (EVO.title ? EVO.title + ' - Mutations' : 'Mutations');
  if (thoughtsViewing()) return THOUGHTS.id ? 'Thought ' + THOUGHTS.id + ' - Thoughts' : 'Thoughts';
  if (boxViewing()) return BOX.id ? 'Box ' + BOX.id + ' - Boxes' : 'Boxes';
  if (offlineViewing()) return 'Offline';
  var rel = addrFolder();
  // The browser's own top, called what the breadcrumb already calls it.
  if (!rel && tasksViewing()) return CRUMB_HOME;
  if (rel) {
    // The page's own title where it has one, and otherwise the name the
    // breadcrumb is already showing, off the same `crumbLevels` the bar is
    // drawn from - so the tab and the bar can never say two different
    // things about one object. The home level is skipped: "All tasks" is
    // the top of the tree and not the name of what is loaded.
    var levels = crumbLevels(), named = '', i;
    for (i = 1; i < levels.length; i++) {
      named = levels[i].words || levels[i].name || named;
    }
    return CANVAS.title || named || rel.split('/').pop();
  }
  var chat = CHATS && CHATS.active ? chatById(CHATS.active) : null;
  return chat ? threadName(chat) : '';
}

/* What a run is called: what the one program says about it where that has
   arrived, and otherwise what its card in the rail already says. The two
   are asked in that order because the program's detail is fetched after the
   run is opened, and the tab should not be called "Run" for the half second
   in between. */
function addrRunName(id) {
  var run = ONE && ONE.runs ? ONE.runs[id] : null, rec = taskRecs[id];
  return (run && run.title) || (rec && (rec.title || rec.brief)) || 'Run';
}

var addrSoon = null;

function addrTouch() {
  if (addrSoon) return;
  addrSoon = setTimeout(function () { addrSoon = null; addrShow(); }, 0);
}

function addrShow() {
  // The drawer's own entry is coming off the history: written now, this
  // would go on top of it and come off with it (`drawerHistory`). It is
  // written the moment that is done.
  if (drawerUnwinding()) return;
  if (ADDR.wanted || RUN_WANTED) return;
  /* Every panel over the canvas is a place with an address of its own now.
     Memory, the Rules page, was the last one held on the conversation it was
     opened over, with no address of its own, until 29 October 2026, when its
     groups were each given one (Petar's B2: Back, a reload and Cmd-click work);
     `addrOnCanvas` names it like every other place. Settings was a panel like
     it until 30 September 2026 (fr_59e04ad20ac8). */
  var want = addrNow();
  // Nothing is on the screen yet, which is the moment between the page
  // loading and the server saying which chat is active. The bar is left
  // exactly as it is: writing `/` here would settle the page on the front
  // door, and the real address a heartbeat later would then be pushed on
  // top of it, leaving a dead entry that Back lands on and nothing happens.
  //
  // Unless the page is at the front door, where `/` is not a moment on the
  // way to an address: it is the address, nothing is open, and the bar and
  // the tab say exactly that. Settling on it is also what makes the next
  // thing opened a step forward, so Back comes back here (see 10g).
  if (!want) return;
  if (want === '/' && !ADDR.front) return;
  var handshake = ADDR.early && !!(CHATS && CHATS.active);
  if (handshake) ADDR.early = false;
  var here = location.pathname + (location.search || '');
  if (want !== here) {
    try {
      var overDrawer = drawerEntryTaken();
      if (ADDR.settled && !ADDR.replace && !overDrawer && !handshake) history.pushState(null, '', want);
      else history.replaceState(null, '', want);
    } catch (err) { return; }
  }
  ADDR.at = want;
  ADDR.settled = true;
  ADDR.replace = false;
  navMark(want);
  // The first address written while a task's conversation is on its way is
  // the half its arrival writes over; a different one after it is another
  // press altogether, and that one is kept.
  if (ADDR.thread) {
    if (!ADDR.half) ADDR.half = want;
    else if (ADDR.half !== want) { ADDR.thread = ''; ADDR.half = ''; }
  }
  var name = addrName();
  document.title = name ? name + ' - Rouh' : 'Rouh';
}

/* Going to what an address names. The server turns the path into the same
   open instruction a result row carries, so this is one message and no
   rules of its own. Sent once the socket is up, because it cannot be sent
   before.

   The conversation goes first and the canvas after it, because the canvas
   follows the conversation (`onChatSwitched`) and the last one to move is
   the one that wins. `ADDR.forChat` is how that follow is stood down for
   this one switch: the address has already said what belongs on the canvas,
   and it is not what this chat would have put there. */
function addrAsk() {
  if (!ADDR.wanted || ADDR.asked) return;
  var want = ADDR.wanted;
  // The conversation, unless it is already the one open: asking for a chat
  // that is active hands every tab its transcript again for nothing, and a
  // link followed while you are already in that conversation is the
  // ordinary case rather than a rare one.
  if (want.chat && want.chat !== (CHATS && CHATS.active)) {
    ADDR.forChat = want.chat;
    if (!send({ type: 'open_chat', id: want.chat, strip: want.strip || '' })) return;
  } else if (want.chat && (want.strip || '') !== addrStripNow()) {
    // The conversation already open, with another strip around it: Back
    // onto a fork that was open beside it. Only the strip changes.
    if (!send({ type: 'open_chat', id: want.chat, strip: want.strip || '' })) return;
  }
  /* A conversation's own address, naming the conversation the handshake
     has already opened, which is every page opened or reloaded at one: it
     is on the screen, so nothing is asked again. Until 22 October 2026 it
     was asked for a second time, and the answer emptied the conversation
     and drew it again a moment after the page had drawn it. */
  if (want.kind === 'chat' && !want.hash && CHATS && want.id === CHATS.active) {
    if ((want.strip || '') !== addrStripNow()) {
      if (!send({ type: 'open_chat', id: want.id, strip: want.strip || '' })) return;
    }
    ADDR.wanted = null;
    ADDR.asked = false;
    // The conversation is on the screen - unless it was put away in this
    // chat, which its own address coming back must not undo (`panelsForChat`).
    if (!panelsChoseCanvas()) {
      chatIsWanted();
      if (narrow()) setPane('chat');
    }
    addrTouch();
    // The welcome was held while the address was on its way (`addrOpen`).
    welcomeShow();
    return;
  }
  /* The browser's own top names no object on the canvas, so there is
     nothing to resolve: it is opened here, down the same call the sidebar
     button makes, and the conversation the address named is put back beside
     it exactly as `addrFound` puts it back beside a page. */
  if (want.browser) {
    ADDR.wanted = null;
    ADDR.asked = false;
    if (!want.opened) browserOpen(want);
    if (want.chat) chatIsWanted();
    return;
  }
  // The Live browser names no object either: it is opened here, the way
  // its row in the sidebar opens it, whether or not a browser is open.
  if (want.web) {
    ADDR.wanted = null;
    ADDR.asked = false;
    webOpen();
    if (want.chat) chatIsWanted();
    return;
  }
  // So do Clockwork and the Goals page, which is where a reminder sent to
  // the phone links to.
  if (want.clock) {
    ADDR.wanted = null;
    ADDR.asked = false;
    if (want.clock === 'goals') goalsOpen(); else remindersOpen();
    if (want.chat) chatIsWanted();
    return;
  }
  // And the Control Room.
  if (want.control) {
    ADDR.wanted = null;
    ADDR.asked = false;
    controlOpen();
    if (want.chat) chatIsWanted();
    return;
  }
  // And Metabolism, on the tab its address names.
  if (want.runs !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    runsOpen(want.runs);
    if (want.chat) chatIsWanted();
    return;
  }
  // And Synapse, its homepage or one dataset with its chat beside it.
  if (want.synapse !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    synapseOpen(want.synapse);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the morning brief, which is where its link on the phone goes.
  if (want.brief !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    briefOpen(want.brief);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the quests, or one quest, which is where its link on the phone goes.
  if (want.work !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    workOpen(want.work);
    if (want.record) {
      fetch('/work/' + want.record, { method: 'HEAD', credentials: 'same-origin' })
        .then(function (r) {
          var got = /\/quests\/(\d+)$/.exec(new URL(r.url).pathname);
          if (got && WORK.open && !WORK.id) workOpen(got[1]);
        })
        .catch(function () {});
    }
    if (want.chat) chatIsWanted();
    return;
  }
  // And the decisions, or one in focus, which is where a Telegram about one links to.
  if (want.decisions !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    decisionsOpen(want.decisions);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the receipts.
  if (want.receipts) {
    ADDR.wanted = null;
    ADDR.asked = false;
    receiptsOpen();
    if (want.chat) chatIsWanted();
    return;
  }
  // And the house.
  if (want.home) {
    ADDR.wanted = null;
    ADDR.asked = false;
    homeOpen();
    if (want.chat) chatIsWanted();
    return;
  }
  // And the rules, one group of them, or What context/rules were included.
  if (want.rules !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    memoryOpen(want.rules, want.from);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the mail approvals.
  if (want.approvals) {
    ADDR.wanted = null;
    ADDR.asked = false;
    // A step of the case (#approval-2) is carried to its page.
    approvalsOpen(want.mailCase || '', want.mailCase ? want.hash || '' : '');
    if (want.chat) chatIsWanted();
    return;
  }
  // And one task's checked sources.
  if (want.sources) {
    ADDR.wanted = null;
    ADDR.asked = false;
    sourcesOpen(want.sources);
    if (want.chat) chatIsWanted();
    return;
  }
  // And Evolution: Parameters, Mutations at one of its views or one gene, or the Gene Pool.
  if (want.evolution) {
    ADDR.wanted = null;
    ADDR.asked = false;
    evolutionOpen(want.evolution.page, want.evolution.sub);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the box.
  if (want.box !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    boxOpen(false, want.box);
    if (want.chat) chatIsWanted();
    return;
  }
  // And the thoughts, or one of them in focus.
  if (want.thoughts !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    thoughtsOpen(want.thoughts);
    if (want.chat) chatIsWanted();
    return;
  }
  // And what this device keeps offline, which needs no connection to open.
  if (want.offline) {
    ADDR.wanted = null;
    ADDR.asked = false;
    offlineOpen('', '');
    if (want.chat) chatIsWanted();
    return;
  }
  // And Gene therapy's drawer, opened the way the person opens it: its own row, pressed.
  // Pressed rather than called, so this module does not import the drawer's and move
  // where that one runs (app.js says why the order matters).
  if (want.geneTherapy) {
    ADDR.wanted = null;
    ADDR.asked = false;
    var gt = $('geneTherapyBtn');
    if (gt && gt.getAttribute('aria-expanded') !== 'true') gt.click();
    if (want.chat) chatIsWanted(); else addrTouch();
    return;
  }
  // And Anatomy, at its status board, a group's page or a section of one.
  if (want.settings !== undefined) {
    ADDR.wanted = null;
    ADDR.asked = false;
    if (want.add) TC.addWant = { address: want.add, name: want.addName || '' };
    settingsOpen(want.settings, want.item, want.query);
    tcAddAsked();
    if (want.chat) chatIsWanted();
    return;
  }
  if (!want.kind) { ADDR.wanted = null; ADDR.asked = false; addrTouch(); return; }
  ADDR.asked = send({ type: 'find_object', kind: want.kind, id: want.id });
  // With no connection a task or a project is its own address: its page is opened from this
  // device's copy, which says so plainly when the page is not in it (`canvasLost`).
  if (!ADDR.asked && (want.kind === 'task' || want.kind === 'project')
      && window.RouhOffline && !window.RouhOffline.online()) {
    addrOffline(want);
  }
}

/* An address of a task, a project or what is inside one, answered on this device with no
   connection, the way the server answers it (`searching._inside_line`): the object's own page,
   a page inside it as itself, and a note, a goal's page or a step's How to do it on the
   object's page (`?doc=`). Whatever the copy does not hold says so on the canvas. */
function addrOffline(want) {
  var parts = String(want.id || '').split('/').filter(Boolean);
  // The deepest numbered folder is the task or step; anything after it is inside it.
  var at = -1, top = -1;
  for (var i = 0; i < parts.length; i++) {
    if (/^\d+(-\d+)*\./.test(parts[i]) && !/\.(md|html?|txt|json)$/i.test(parts[i])) {
      at = i;
      if (top < 0) top = i;
    }
  }
  var row;
  if (at < 0 || at === parts.length - 1) {
    row = { type: want.kind, open: { how: 'task', task: want.id } };
  } else {
    var enc = function (/** @type {string[]} */ list) { return list.map(encodeURIComponent).join('/'); };
    var folder = parts.slice(0, at + 1), inside = parts.slice(at + 1);
    var page = /\.html?$/i.test(inside[inside.length - 1])
      ? '/workspace/' + enc(folder.concat(inside))
      : '/workspace/_task/' + enc(folder) + '/?doc=' + encodeURIComponent(inside.join('/'));
    row = { type: want.kind, open: { how: 'page', task: parts.slice(0, top + 1).join('/'), page: page, kind: 'task' } };
  }
  addrOpen({ type: 'object_found', ok: true, row: row });
}

/* The server's answer to `find_object`. One the person has pressed past
   while it was on its way is theirs no longer (`addrPressed`). */
/** @param {import('./protocol').FromServer<'object_found'>} m */
function addrFound(m) {
  if (ADDR.dropping > 0) { ADDR.dropping--; return; }
  addrOpen(m);
}

/* The answer, whatever it was, from the server or from this device's copy
   (`addrOffline`). The bar is let go of either way: an address for something
   since deleted says so and stays where the page really is, rather than
   holding the whole address bar still for the rest of the session. */
/** @param {import('./protocol').FromServer<'object_found'>} m */
function addrOpen(m) {
  var want = ADDR.wanted;
  ADDR.wanted = null;
  ADDR.asked = false;
  if (!m || !m.ok || !m.row) {
    notify(m && m.why ? m.why : 'That is not there any more.', { tone: 'warning' });
    addrTouch();
    return;
  }
  // The page goes up without taking the conversation the address named
  // away: `/task/<folder>?chat=<id>` reloaded used to come back to the
  // task's own conversation instead, because loading the task's page asked
  // for it. A chat put under a task with Move this chat is addressed
  // exactly this way, so it could not be reloaded or linked to at all.
  ADDR.chatNamed = !!(want && want.chat);
  // A place in the page the address named (`#evidence`), which the server
  // never sees: the page is taken there once it is in the frame, as it is
  // for a link inside a page (`canvasLoad`). A link opened in a new tab
  // from a page's own "source 1" lands on the source (`_rouh_address`).
  ADDR.hash = (want && want.hash) || '';
  try {
    // A conversation's own address opens it with the strip of forks the
    // address names around it, or with none (`addrRead`).
    if (want && want.kind === 'chat' && !want.hash && m.row.open && m.row.open.how === 'chat') {
      chatShow(m.row.open.id, want.strip || '');
    } else {
      findGo(m.row);
    }
  } finally { ADDR.chatNamed = false; ADDR.hash = ''; }
  // The address named a conversation beside what has just been opened, so
  // the conversation is part of the screen being put back. A project's page
  // takes the whole window when it is browsed on its own (`findGo`), and
  // this is not that: it is two panels, and both of them are in the link.
  if (want && want.chat) chatIsWanted();
  // The welcome was held while the page was on its way here. An address
  // that opens a conversation holds it again until that arrives; one that
  // does not - a run, a card - leaves the conversation that is open, and
  // that is what decides now.
  welcomeShow();
}

/* A panel that was covering the canvas has closed. The address was held
   still while it was up, so what it says is still where the person was; the
   canvas was emptied underneath to make room for the panel, so this is what
   puts it back, down the same one path a link takes. Nothing happens in the
   ordinary case, where the address already says what is on the screen. */
function addrBack() {
  // Not while this closer is one of the layers being stood down for another
  // that is opening. That is a move to somewhere else, not a panel closing,
  // and the address is about to follow it.
  if (standingDown || ADDR.wanted) return;
  var want = addrRead(location.pathname, location.search);
  // An address that is only a conversation needs no putting back: closing
  // the panel reveals it, which is the whole of what a chat's address
  // means. An address that names a conversation **beside** something keeps
  // it, because that conversation is one of the two panels being restored
  // and loading a page over it folds it away (`addrFound`). The browser's
  // own top has no kind and is still something to put back: the canvas was
  // emptied for the panel and the browser was what was in it.
  if (!want || (!want.kind && !want.browser && !want.web) || want.kind === 'chat') return;
  // And `addrOnCanvas` rather than `addrNow`, which falls back to the
  // conversation: a task's conversation carries that task's own address, so
  // asking `addrNow` here would answer "already there" for the one case
  // this exists for - a task's page stood down for Settings.
  if (addrOnCanvas() === location.pathname) return;
  ADDR.wanted = want;
  ADDR.asked = false;
  addrAsk();
}

/* Back and Forward. The address changed without this page doing it, so the
   page goes to whatever it now names, and what that opens is written back
   as a replacement rather than as a new entry - the person moved through
   the history, they did not add to it. */
window.addEventListener('popstate', function () {
  // The navigation drawer's own entry on a phone, which is not a place.
  if (drawerPopped()) return;
  ADDR.settled = true;
  ADDR.replace = true;
  ADDR.asked = false;
  ADDR.wanted = addrRead(location.pathname, location.search) || frontDoorShut();
  if (ADDR.wanted) { addrAsk(); return; }
  frontDoorGo();
});

/* The task browser, as an address opens it. */
function browserOpen(want) {
  want.opened = true;
  // `/tasks` with no conversation beside it is the browser across the
  // whole window, which is how the navigation's own button opens it
  // (`tasksBrowse`). Without this, Back or Forward onto it from a task's
  // page kept that page's conversation open beside it, and the bar then
  // said so, over an entry that had not.
  if (!want.chat) tasksTakeChat();
  if (typeof want.view === 'string') TASKS_VIEW.view = want.view;
  tasksOpen();
}

/* A page opened at `/tasks` opens the browser at once.

   The browser is a page of the workspace, fetched like any other, and needs
   nothing from the socket. Until 22 October 2026 it waited for the handshake
   all the same, as an object's address must (`addrAsk`), and the handshake
   is the longest thing a page waits for: on the first Rouh, a minute after
   deploy and with six other tabs open, Petar typed the address, waited
   sixteen seconds without the browser, and opened it from the navigation
   instead (fr_35eeac6a7875), where it opens on a socket that is already
   up. So it is opened here, as
   the page starts, before the socket and ahead of everything else this
   page fetches. A conversation the address names beside it still needs the
   socket, and is opened when the handshake comes, by `addrAsk`. Called by
   app.js once every module has run, because opening it touches state that
   modules after this one make (the columns, Gene therapy's board). */
function addrEarly() {
  var want = ADDR.wanted;
  if (!want || !want.browser || want.opened) return;
  browserOpen(want);
  if (!want.chat) ADDR.wanted = null;
}

/* The front door is shut (see 10g).

   Petar, 21 October 2026 (fr_d621c6a10c3a), of `/` with its hello and its
   things to try: "remove those two screens from [my Rouh], instead - redirect
   to [my Rouh]/chat/conversation". So an address that names nothing -
   `/`, `/one/`, an old bookmark, the app opened from a phone's home screen,
   a "Back to Rouh" link - is read as General's own address, and the bar is
   made to say so, as a replacement: nobody went to `/`, so there is no
   entry for Back to land on. `/?chat=<id>` opens that chat instead.

   It is done here and not by the server, because the service worker keeps
   its copy of the page by asking `/` for it, and a redirect there would stop
   it keeping one (`sw.js`). */
function frontDoorShut() {
  var found = /[?&]chat=([^&#]*)/.exec(location.search || '');
  var chat = '';
  if (found) {
    try { chat = decodeURIComponent(found[1]); } catch (err) { chat = found[1]; }
  }
  // General's id, written out: `CHATS` may not be made yet when this runs.
  var to = addrOf('chat', chat || 'conversation');
  try { history.replaceState(null, '', to + location.hash); } catch (err) {}
  return addrRead(to, '');
}

/* The person's own press wins.

   An address on its way - the one the page was opened at, before the
   handshake has let it be asked about, or one Back or a link has just named -
   holds the bar still (rule 3 above) and is opened the moment it is answered.
   Somebody who presses a link in the navigation in that moment has chosen
   somewhere else. Until 17 October 2026 their press opened, the bar stayed on
   the address the page was opened at, and the answer then opened that page
   over the one they had chosen (fr_4551bf5b86f4), on every page the loading
   screen does not cover, online and offline alike.

   So a press on one of the page's own links lets go of the address on its
   way, first, in capture, before the link's own handler opens what it names:
   that open writes the bar the ordinary way, and an answer already asked for
   is dropped when it comes (`ADDR.dropping`). The conversation the address
   named is left alone: a switch already asked for still arrives, and
   `ADDR.forChat` still keeps it from moving the canvas.

   And what they chose is a step forward from the address the bar still says,
   rather than written over it: Back goes to that address and opens it, the
   way Back goes to anywhere else this tab has been. */
function addrPressed() {
  if (!ADDR.wanted) return;
  if (ADDR.asked) ADDR.dropping++;
  ADDR.wanted = null;
  ADDR.asked = false;
  ADDR.settled = true;
  ADDR.replace = false;
  if (!(CHATS && CHATS.active)) ADDR.early = true;
}

window.addEventListener('click', function (e) {
  if (!ADDR.wanted || browserTakes(e) || !inAppLink(e)) return;
  addrPressed();
}, true);

/* The socket is gone, and with it every answer it still owed. An address that
   was asked about is asked again on the next one (`ready`), or opened from
   this device's copy if there is no next one (`offlineReplay`). */
function addrSocketGone() {
  ADDR.asked = false;
  ADDR.dropping = 0;
}

/* A page opened at an object's own address, or at one of the `/?open=…`
   links that were what "open in new tab" put in the bar until this section
   existed. Either way the address names one object and the page goes there.
   The old shape is tidied out of the bar as it is read, because it has been
   acted on and the object's own address is about to be written over it. */
(function () {
  var want = addrRead(location.pathname, location.search);
  if (!want) {
    var found = /[?&]open=([^&#]+)/.exec(location.search || '');
    if (found) {
      var said = found[1];
      try { said = decodeURIComponent(said); } catch (err) {}
      var cut = said.indexOf(':');
      if (cut > 0) {
        want = { kind: said.slice(0, cut), id: said.slice(cut + 1), chat: '' };
      }
      try {
        history.replaceState(null, '', location.pathname + location.hash);
      } catch (err) {}
    }
  }
  if (!want) want = frontDoorShut();
  if (want && /^#./.test(location.hash || '')) want.hash = location.hash;
  ADDR.wanted = want;
  ADDR.front = !want;
}());

/* The loading screen, for a page opened at an address.

   Getting to what an address names is several steps, and every one of them
   used to be drawn: the sidebar before the script had sorted its lists, the
   conversation that was active on the server, the one the address named, a
   task's bar over an empty frame, and at last the task. On 29 September 2026
   Petar opened a task's page on his phone and watched a broken page, a blank
   one and a chat go by before it (fr_ba374cbf694f), and asked that nothing
   be on the screen that is not meant to be displayed.

   So a page opened at an address starts covered, by `#bootVeil` in
   index.html, and the head of that page decides it before anything is
   painted (`html.booting`). It comes off once, in one step, when the screen
   is what the address named: the address has been answered (`ADDR.wanted`)
   and the conversation it opened has arrived (`S.switching`). A page on the
   canvas is not waited for: it has its own loading line (`canvasLoad`). The front
   door has nothing on its way, and a notice the page says by itself (`notify`)
   is something to read, so either
   takes it off at once; and it never outlasts `BOOT_LONGEST`, whatever
   failed to answer. */
var BOOT = { settledAt: 0 };
var BOOT_LONGEST = 15000;
// Some switches are never answered with a `chat_switched` (the one asked
// for was already open), so one still pending this long after everything
// else is there is taken as done.
var BOOT_SWITCH_GRACE = 1500;

// What the loading screen is still waiting for, or '' when nothing.
function bootWaiting() {
  if (ADDR.front) return '';
  if (ADDR.wanted) return 'address';
  // Not the page on the canvas (23 October 2026): it shows its own loading
  // line, and a task's page can take seconds to build. Waiting for it kept
  // the conversation, there a second after the address was opened, under
  // this screen for nine seconds more on the first Rouh.
  if (S.switching) {
    if (!BOOT.settledAt) BOOT.settledAt = performance.now();
    if (performance.now() - BOOT.settledAt < BOOT_SWITCH_GRACE) return 'chat';
  }
  return '';
}

function bootWatch() {
  var root = document.documentElement;
  if (!root.classList.contains('booting')) return;
  // Two frames running, so that what has just been put in place is painted
  // under the cover before the cover comes off.
  var calm = 0;
  (function tick() {
    var give = performance.now() > BOOT_LONGEST
      || !!document.querySelector('#notices:not([hidden]) .nt-card[data-tone]');
    calm = bootWaiting() ? 0 : calm + 1;
    if (give || calm >= 2) {
      root.classList.remove('booting');
      return;
    }
    requestAnimationFrame(tick);
  }());
}
bootWatch();

/* ---------------------------------------------------------------- 10g */

/* The front door.
 *
 * `/` names nothing, and until 22 September 2026 a page opened there went
 * looking for something to be: the handshake says which chat the person is
 * in, the page drew it, and the bar followed it. So opening the site's root
 * put you back in the last task's page with last
 * night's conversation on the screen. Petar asked for that to stop, in
 * these words: going to the root should not redirect to the last thing, and
 * should not load anything on the screen - neither chat nor anything in the
 * canvas.
 *
 * So `/` is a place now, and the place is empty. No conversation, no
 * transcript, no cards, nothing on the canvas, the bar left at `/` and the
 * tab called Rouh: the shell, the box and the controls, ready for a fresh
 * start - with a hello and things to try, the way every empty conversation
 * has them (the welcome, below). Every other address is untouched - `/task/…`, `/chat/…` and the
 * rest open exactly what they name, which is what they are for.
 *
 * Shut since 21 October 2026 (`frontDoorShut`): an address that names
 * nothing opens General, at `/chat/conversation`, and nothing below is
 * reached from an address any more.
 *
 * Three rules, and they are the whole of it.
 *
 * 1. **Nothing is opened for you.** The handshake still carries the active
 *    chat, because the rail draws every chat and marks none of them open,
 *    and it still carries that chat's transcript and whatever turn is
 *    running in it. None of that is drawn here (`ready`), the page takes no
 *    session id for it, and anything that arrives for it afterwards is
 *    dropped - the same rule, and the same line, as for a conversation the
 *    page has left.
 * 2. **The first thing said opens a conversation.** There is none to say it
 *    in, so saying it makes one: a new chat, the same one the New chat
 *    button makes, and the words go into that rather than into whatever was
 *    open last night. Typing, attaching a file and opening the microphone
 *    are all saying something, and all three go through `freshChatFirst`.
 *    What is typed is not sent until the server says the chat is open:
 *    opening a chat wipes the transcript, and a message drawn before that
 *    arrived would have been wiped along with it.
 * 3. **The front door closes behind you, and Back opens it again.** A
 *    conversation opened in this tab - from the rail, from a task, or by
 *    the first thing said here - ends it, and this is an
 *    ordinary page again. Back to `/` returns to it with nothing on it
 *    (`frontDoorGo`), because Back is meant to put the person where they
 *    were, and where they were was a page with nothing on it.
 *
 * None of this is on the wire. Which chat a tab is in is that tab's own
 * (`tabChatWanted`), and the front door is one more such state: a page at
 * it changes nothing for any other, and the first thing said here is an
 * ordinary `new_chat`, which moves this tab and no other.
 */

//: What the front door has asked the server for, and what is waiting on it.
//: More than one thing can be: a file going up and the message it was
//: attached to are two presses and one conversation to put them both in.
var FRESH = { asked: false, waiting: [] };

/* A conversation to say it in, before this is done.
 *
 * Returns true when it has taken the work over, so the caller stops: it is
 * run again, unchanged, the moment the new chat is open. False means there
 * is already a conversation and the caller carries on as it always did -
 * which is every page that is not at the front door, so this costs nothing
 * anywhere else.
 *
 * `go` may be left out where there is nothing to run afterwards: opening
 * the microphone only needs the chat to exist by the time speech reaches
 * the server, and the server takes one socket's messages in order.
 */
function freshChatFirst(go) {
  if (!ADDR.front) return false;
  // Asked for once, however many things are waiting on it: a file attached
  // and the message it was attached to are two presses and one conversation.
  if (!FRESH.asked) {
    // Not connected: the caller is left to fail in its own words, which say
    // more than anything that could be said here.
    if (!send({ type: 'new_chat' })) return false;
    FRESH.asked = true;
  }
  if (go) FRESH.waiting.push(go);
  return true;
}

// The conversation asked for above is open, and the screen has settled on
// it. Whatever was waiting goes now, into a page that is no longer at the
// front door.
function freshChatOpened() {
  var waiting = FRESH.waiting;
  FRESH.asked = false;
  FRESH.waiting = [];
  for (var i = 0; i < waiting.length; i++) waiting[i]();
}

/* Back to the front door: `/`, with nothing on it.
 *
 * A page opens there and Back returns to it, and both are this, so the two
 * cannot drift apart. Everything that belonged to the conversation being
 * left goes with it - the words, the cards, the sound - and the canvas goes
 * back to bare. Nothing is said to the server: which chat is active is the
 * person's, and they have not left it, they have walked out to the front of
 * the house.
 */
function frontDoorGo() {
  ADDR.front = true;
  ADDR.wanted = null;
  ADDR.asked = false;
  CHATS.active = '';
  S.sessionId = null;
  S.turn = 0;
  shared.THREAD_ASKED = '';
  $('sessId').textContent = '-';
  $('sessId').title = '';
  // The sound of the conversation being left goes with it, exactly as it
  // does when another one is opened (`onChatSwitched`), and so does the Stop
  // control: whatever is still being answered is being answered in there,
  // and there is nothing on this screen to stop.
  stopPlayback();
  endTurnOnScreen();
  wipeTranscript();
  clearTheCards();
  goNow();
  showCrumb();
  renderThreads();
  addrShow();
}

export { ADDR, ADDR_BROWSER, addrAsk, addrBack, addrEarly, addrChatIsShowing, addrFound, addrOffline, addrIsTasksOwn, addrSocketGone,
  addrOf, addrOfFolder, addrOnCanvas, addrPlaceLink, addrRead, addrTouch, bootWaiting, FRESH, freshChatFirst, freshChatOpened };
