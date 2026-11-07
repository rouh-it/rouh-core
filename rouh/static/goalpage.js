/* A goal's own page, at its task's `goal.md` (`objectindex.goal_page`).

   Petar, 27 September 2026 (fr_b083c37a634d), looking at the roadmap drawn
   on a goal's task page: "first of all, I need this to be a separate page.
   the homepage should remain with list of things (chats, subtasks, etc), and
   just like HTML can be clicked the goal can be clicked to go to the
   specialized page. the specialized page should have the ability to reorder
   but also manage things that can go in parallel streams. I this should be
   visual and interactive. everything that can be done without me should be
   done without me. at every stream I should see that it is waiting on me to
   unblock it - decision or action that AI can't take. it should be obvious
   what is required from me and everything that has been prepared for me to
   help me make the decision or take action should be gathered and presented
   easily to help me: research information crunched, steps to take an action
   etc."

   And, the same afternoon, looking at that first version: "please don't
   make decision points in separate category ... i should be able to look at
   the map and see that something requires my attention. also the streams
   should be split by itself. anything that can be done in parallel should
   be done in parallel. i feel like those should be listed vertically on the
   left and so i can see it a little bit like a waterfall chart. every task
   or list of tasks in a stream ends with completion or request for my
   interaction at the very right."

   So the page is when the goal is due, at the right of its name (`due`),
   and then the map (`board`): one row per stream, listed down the left, its
   steps flowing left to right in the order they follow one another. The
   step a stream waits on him for is amber on the map, and that is the whole
   of how he sees it: the column of stream ends that repeated it at the right
   is gone (fr_ddae0c0dac24, "this entire colum is not needed since the
   streams give me the yellow boxes on hte map"). Any step opens under its
   row (`panel`): its title, one line of Problem, Solution and Method, each
   a label whose words are in a tooltip (fr_bb6210d0d47a), Rouh's part and
   his each in a line with an icon for how it stands and a link to the
   step's explainer, and the buttons. Results opens Rouh's research and How to do it his own
   page, where Mark as complete is; Do it again asks what he did not like. A plan
   arrives already in streams: Rouh splits it as it plans (`goals.split`,
   from `tools._plan_goal`), and never again by itself, on opening, on a
   reload or later. Petar, 27 September 2026 (fr_48647091affa), after his
   own arrangement kept being undone: "once plan is made it shouldn't be
   changed on its own all the time". And the same evening (fr_f9eb62fe270a):
   "we shouldn't have a button Split into streams. But I should be able to:
   1) be able to manage streams on this screen naturally. 2) be able to tell
   ai how to reorder streams and tasks in there." So there is no Split
   button. A step is dragged by its handle, or moved with the arrow keys on
   it, along its stream or into another; a stream's name is pressed to rename
   it, and its arrows move the whole stream up or down; a stream emptied of
   its steps is gone. Anything else, a new stream or the streams arranged his
   way in his own words, he asks for in the goal's chat, like any other
   change to the map: the page has no box, button or drop row for it, no
   line of instructions under the map, and no Why it needs help paragraph
   (fr_18f774bf26e9, "the generic chat can do any operation on the
   map/chart. the instructions should not exist, they should be
   self-evident. the last paragraph has no value either"). The streams go on at the same time, each step Rouh
   takes up a background run of its own, and the goal has one chat, its own
   (fr 27 September 2026: "the main chat is the one for the entire goal"):
   every stream Rouh can take up starts the moment
   the plan is written, with nobody asked (fr_a25fe6a202a3,
   `timekeeper.start_streams`). Let Rouh go, under a stream's name, starts it
   again when it stopped, and Let Rouh do all it can does that for every
   stream (`timekeeper.let_go`). On a phone each row is a column. What he wrote is
   last.

   The page is sandboxed with an origin of its own, so no press reaches the
   server from here: each goes up to Rouh (`taskGoalMap` and
   `taskGoalRevise` in app.js), which finds the goal from the page it
   framed, never from this page, and hands the goal back as it is after the
   press, and again whenever it changes anywhere else (`rouh-goal-view`). It
   is drawn again from that in place, so nothing jumps and a step being
   changed keeps what was typed. At its own address, with no Rouh around it,
   it is drawn without buttons. */
(function () {
  'use strict';
  var root = document.getElementById('goalPage');
  var v = linked(window.ROUH_GOAL);
  if (!root || !v || !v.id) { return; }
  var BACK = 'rouh-frame-project', MAP = 'rouh-page-goalmap', REVISE = 'rouh-page-goalrevise';
  var VIEW = 'rouh-goal-view';
  var framed = !!v.framed;

  // Complete is the person's word only (`goals.ROUH_DONE`, fr_a5668026d08d).
  var STATUS = { 'not-started': 'To do', 'in-progress': 'Doing', waiting: 'Waiting',
                 done: 'Complete' };
  var WORDING = ['title', 'kind', 'ask', 'options', 'outcome', 'how', 'challenge', 'solution'];
  // What is open: steps opened in place, the step being picked a time or a
  // step for or changed, with its draft; the deadline being set; the stream
  // being renamed; a step being dragged; and a line saying what happened.
  var G = { panel: '', stepOpen: null, dueOpen: false, busy: false, renaming: '',
            say: '', sayAt: 0, sayKind: '', sayChat: false, sayHref: '', drag: null, focus: '', more: '',
            reveal: '', steering: false, steer: '' };

  // The goal's chat, its only one, by its address, which the goals Rouh
  // hands on do not carry (`addressing.url_for`).
  function chatHref(chat) { return chat ? '/chat/' + encodeURIComponent(chat) : ''; }
  function linked(goal) {
    if (goal && !goal.chat_href && goal.chat) { goal.chat_href = chatHref(goal.chat); }
    return goal;
  }

  // Where a step is talked over: the goal's own chat. A step is worked by a
  // background run, never in a chat (`goals.brief_for_step`).
  function workHref() { return v.chat_href; }

  /* ---- talking to Rouh around the page ---- */

  var toastEl = null, toastTimer = null;
  function toast(words) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast bad';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = words;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, 9000);
  }

  var seq = 0, asked = {};
  window.addEventListener('message', function (e) {
    var m = e.data;
    if (!m || e.source !== window.parent) { return; }
    // The goal changed somewhere else - Rouh finished a step, another tab
    // pressed one - and Rouh hands the page every goal as it is now.
    if (m.type === VIEW) {
      (m.goals || []).forEach(function (g) { if (g && g.id === v.id) { take(g); } });
      return;
    }
    // An address with #step-<id> on it, such as a quest's page links to: that
    // step opened, and brought into sight.
    if (m.type === 'rouh-frame-hash' && /^#step-/.test(String(m.hash || ''))) {
      var wanted = String(m.hash).slice(6);
      if (stepById(wanted)) {
        G.panel = wanted;
        G.reveal = wanted;
        draw();
      }
      return;
    }
    if (m.type !== BACK || !asked[m.id]) { return; }
    var said = asked[m.id];
    delete asked[m.id];
    if (!m.ok) {
      toast(m.error || 'That did not work.');
      if (said.refused) { said.refused(m); }
    } else if (said.done) {
      said.done(m);
    }
  });

  function tell(type, said, refused, done) {
    var up;
    try { up = window.parent; } catch (err) { up = null; }
    if (!framed || !up || up === window) {
      toast('Rouh could not be reached.');
      if (refused) { refused({}); }
      return;
    }
    var id = 'g' + (++seq);
    asked[id] = { refused: refused, done: done };
    said.type = type;
    said.id = id;
    try { up.postMessage(said, '*'); }
    catch (err) {
      delete asked[id];
      toast('Rouh could not be reached.');
      if (refused) { refused({}); }
    }
  }

  // The goal as it is now. What is open stays open, with what was typed.
  function take(goal) {
    if (!goal || goal.id !== v.id || G.drag) { return; }
    var was = v;
    v = linked(goal);
    v.framed = framed;
    v.task_href = was.task_href;
    // What the line said was about the goal before this change, unless it
    // was said just now: the goal comes back again as every tab hears of it.
    if (!G.busy && Date.now() - G.sayAt > 4000) { G.say = ''; }
    if (G.stepOpen && !stepById(G.stepOpen.id)) { G.stepOpen = null; }
    draw();
  }

  /* ---- small makers ---- */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = String(text); }
    return n;
  }

  function button(label, cls, run) {
    var b = el('button', 'ogs-btn small ' + (cls || ''), label);
    b.type = 'button';
    b.addEventListener('click', run);
    if (!framed || G.busy) { b.disabled = true; }
    return b;
  }

  function link(label, href, cls) {
    var a = el('a', cls || 'ogs-btn small', label);
    a.href = href;
    return a;
  }

  function tomorrow() {
    var d = new Date();
    d.setDate(d.getDate() + 1);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }

  function allSteps() {
    var all = [];
    (function walk(items) {
      items.forEach(function (s) { all.push(s); walk(s.parts || []); });
    })(v.steps || []);
    return all;
  }

  function stepById(id) {
    return allSteps().filter(function (s) { return s.id === id; })[0] || null;
  }

  function laneOf(stepId) {
    return (v.streams || []).filter(function (l) { return l.steps.indexOf(stepId) >= 0; })[0] || null;
  }

  // Whose a step is. "petar" is how a step written before 20 October 2026 says "owner".
  function whoKey(s) { return s.who === 'petar' ? 'owner' : s.who; }

  function who(s) {
    var key = whoKey(s);
    var kind = key === 'rouh' || key === 'owner' || key === 'together' || key === 'quest'
      ? key : 'other';
    var chip = el('span', 'goal-who w-' + kind, s.who_words);
    if (s.who_means) { chip.title = s.who_means; }
    return chip;
  }

  function statusWords(s) {
    if (s.hollow) { return 'Marked done, but nothing was made'; }
    if (s.done_by === 'rouh') { return 'Complete · Rouh did it'; }
    if (!s.rouh_done) { return STATUS[s.status] || s.status; }
    return s.who === 'rouh' || s.who === 'together' ? 'Rouh’s part done · waiting on you'
      : 'Waiting on you to mark it complete';
  }

  /* ---- the page ---- */

  function draw() {
    var focused = document.activeElement;
    var keep = focused && focused.getAttribute ? focused.getAttribute('data-keep') : '';
    root.textContent = '';
    root.className = 'gp st-' + v.stage;
    about();
    due();
    if (G.say) {
      var say = el('p', 'gm-say ' + G.sayKind, G.say);
      say.setAttribute('role', 'status');
      var watch = G.sayChat ? (G.sayHref || v.chat_href) : '';
      if (watch) {
        say.appendChild(document.createTextNode(' '));
        say.appendChild(link('Watch it in the chat', watch, 'gm-say-do'));
      }
      root.appendChild(say);
    }
    if ((v.steps || []).length) { root.appendChild(stands()); }
    var who = delegates();
    if (who) { root.appendChild(who); }
    if (v.stage === 'understanding' && !(v.steps || []).length) {
      root.appendChild(asking());
    } else if (!(v.steps || []).length) {
      root.appendChild(el('p', 'none', 'No steps yet. Ask Rouh in the goal’s chat to lay out '
        + 'the plan.'));
    } else {
      root.appendChild(board());
    }
    // A button pressed with the keyboard is drawn again; the focus goes back
    // to the same one, so arrows on a step's handle keep moving it.
    var again = G.focus || keep;
    G.focus = '';
    if (again) {
      var back = root.querySelector('[data-keep="' + again + '"]');
      if (back) {
        back.focus({ preventScroll: false });
        // Typing in the line to Rouh carries on at the end of what was typed.
        if (back.tagName === 'INPUT') { back.setSelectionRange(back.value.length, back.value.length); }
      }
    }
    // A step just opened is brought into sight, along its row and down the page.
    var reveal = G.reveal;
    G.reveal = '';
    var grown = reveal && root.querySelector('.gp-card.open[data-step="' + reveal + '"]');
    if (grown) { grown.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
  }

  /* Who decides for this goal by the person's grant, and the last things they did,
     each with their own words (`rouh/delegation.py`). Folded, beside the map. */
  function delegates() {
    var g = v.delegates || { deciders: [], acts: [] };
    if (!g.deciders.length && !g.acts.length) { return null; }
    var d = el('details', 'gp-delegates');
    var head = el('summary', null, g.deciders.length
      ? g.deciders.join(' and ') + ' decides for this goal' : 'Decided by a delegate');
    if (g.acts.length) { head.appendChild(el('span', 'gp-delegates-n', ' · ' + g.acts.length + ' lately')); }
    d.appendChild(head);
    if (g.deciders.length) {
      d.appendChild(el('p', 'gp-delegates-said', 'By your grant: its decisions, its steps and its plan. '
        + 'Money, deleting, publishing, sending and commitments stay yours.'));
    }
    var ul = el('ul', 'gp-delegates-list');
    g.acts.slice(0, 8).forEach(function (a) {
      var li = el('li', 'gp-delegates-' + a.outcome);
      li.appendChild(document.createTextNode((a.outcome === 'for_owner' || a.outcome === 'for_petar' ? 'Held for you: '
        : a.outcome === 'undone' ? 'Undone: ' : 'Decided by ' + a.name + ': ') + (a.said || a.why)));
      if (a.words) { li.appendChild(el('span', 'gp-delegates-words', ' \u201c' + a.words + '\u201d')); }
      ul.appendChild(li);
    });
    if (ul.childNodes.length) { d.appendChild(ul); }
    return d;
  }

  /* What the person wrote, the first thing on the page, with when it is due
     beside it (`#goalAbout` in `objectindex.goal_page`, fr_11a135ffd563).
     Folded, so the map is still what the eye lands on; open stays open when
     the page is drawn again. */
  function about() {
    var box = document.getElementById('goalAbout');
    if (!box) { return; }
    var was = box.querySelector('details');
    var open = was ? was.open : false;
    box.textContent = '';
    if (!v.about) { return; }
    var d = el('details', 'goal-about');
    d.open = open;
    d.appendChild(el('summary', null, 'What you wrote'));
    d.appendChild(el('p', null, v.about));
    box.appendChild(d);
  }

  /* When it is due, at the right of the goal's name (`#goalDue` in
     `objectindex.goal_page`). Petar, 27 September 2026 (fr_500dd237083e), on
     the box of progress, tiles and deadline that stood above the map: "remove
     this entire block. only leave the set a deadline link/item but maybe it
     can be up top on the title level floating right." So the date and how
     long is left, or Set a deadline, is all that is left of it; the map
     already says how far along the goal is and what waits on him. */
  function due() {
    var box = document.getElementById('goalDue');
    if (!box) { return; }
    box.textContent = '';
    box.className = 'gm-due' + (v.deadline ? '' : ' unset') + (G.dueOpen ? ' open' : '');
    if (G.dueOpen) {
      var day = el('input');
      day.type = 'date';
      day.value = v.deadline || '';
      day.setAttribute('aria-label', 'Deadline');
      box.appendChild(day);
      box.appendChild(button('Save', 'primary', function () {
        if (!day.value) { day.focus(); return; }
        act('deadline', null, { deadline: day.value });
      }));
      if (v.deadline) {
        box.appendChild(button('Remove', '', function () { act('deadline', null, { deadline: '' }); }));
      }
      box.appendChild(button('Cancel', '', function () { G.dueOpen = false; draw(); }));
      setTimeout(function () { day.focus(); }, 0);
      return;
    }
    if (v.deadline) {
      box.appendChild(el('span', 'gm-due-k', 'Due'));
      box.appendChild(el('strong', null, v.deadline_words));
      if (v.deadline_left) {
        box.appendChild(el('span', 'gm-due-left' + (/ago|yesterday/.test(v.deadline_left)
          ? ' late' : ''), v.deadline_left));
      }
    }
    if (framed) {
      var change = el('button', 'gm-link', v.deadline ? 'Change' : 'Set a deadline');
      change.type = 'button';
      change.addEventListener('click', function () { G.dueOpen = true; draw(); });
      box.appendChild(change);
    }
  }

  /* Where it stands: the goal as a responsibility Rouh carries between
     conversations, in one strip above the map. Asked for on 2 October 2026,
     after OpenAI's Dots: what state it is in, how far along, what happens
     next and who does it, the first thing waiting on him, and his two
     controls over it. Pause holds it - nothing new starts until Resume, and
     runs already going finish - and Redirect keeps his words on the goal,
     told to every run started after it, while Rouh looks the plan over in
     the goal's chat (`timekeeper.pause`, `resume`, `redirect`). What Rouh may
     do for it is folded under it, read from the rules the code enforces
     (`goals.BOUNDARIES`), not a setting. */
  function stands() {
    var st = v.standing || {};
    var box = el('section', 'gs st-' + (st.state || 'other'));
    box.setAttribute('aria-label', 'Where it stands');
    var top = el('div', 'gs-top');
    top.appendChild(el('span', 'gs-state', st.words || ''));
    top.appendChild(el('span', 'gs-progress', v.progress_words || ''));
    var acts = el('div', 'gs-acts');
    if (framed && st.state !== 'complete') {
      if (v.paused) {
        acts.appendChild(button('Resume', 'primary', function () { act('resume', null, {}); }));
      } else {
        var hold = button('Pause', '', function () { act('pause', null, {}); });
        hold.title = 'Nothing of this goal starts until you resume it. Runs already going finish.';
        acts.appendChild(hold);
      }
      var steer = button('Redirect', '', function () {
        G.steering = !G.steering;
        G.steer = G.steering ? (v.direction || '') : '';
        draw();
      });
      steer.title = 'Tell Rouh what should change. Every run from now on is told it.';
      steer.setAttribute('aria-expanded', G.steering ? 'true' : 'false');
      acts.appendChild(steer);
    }
    top.appendChild(acts);
    box.appendChild(top);
    var d = st.decision || {};
    var ql = questLine();
    if (ql) { box.appendChild(ql); }
    if (st.next) {
      var nx = el('p', 'gs-line');
      nx.appendChild(el('span', 'gs-k', 'Next'));
      // What waits on him opens the step it is on, with all that is ready for it.
      nx.appendChild(st.state === 'you' && d.step ? needLink(d, st.next)
        : document.createTextNode(st.next));
      box.appendChild(nx);
    }
    if (d.step && st.state !== 'you') {
      // Still waiting on him though the goal is paused: said, and one press away.
      var nd = el('p', 'gs-line gs-need');
      nd.appendChild(el('span', 'gs-k', 'Needs you'));
      nd.appendChild(needLink(d));
      box.appendChild(nd);
    }
    if (d.step && d.more) {
      box.appendChild(el('p', 'gs-line gs-more', d.more + ' more waiting on you, amber on the map.'));
    }
    if (G.steering) {
      box.appendChild(steerBox());
    } else if (v.direction) {
      var dir = el('p', 'gs-line gs-dir');
      dir.appendChild(el('span', 'gs-k', 'Direction'));
      dir.appendChild(el('q', null, v.direction));
      if (framed) {
        var clear = el('button', 'gm-link', 'Clear');
        clear.type = 'button';
        clear.disabled = G.busy;
        clear.addEventListener('click', function () { act('redirect', null, { direction: '' }); });
        dir.appendChild(document.createTextNode(' '));
        dir.appendChild(clear);
      }
      box.appendChild(dir);
    }
    var may = el('details', 'gs-may');
    may.open = !!G.mayOpen;
    may.addEventListener('toggle', function () { G.mayOpen = may.open; });
    may.appendChild(el('summary', null, 'What Rouh may do for this goal'));
    var list = el('dl', 'gs-rules');
    (v.boundaries || []).forEach(function (b) {
      list.appendChild(el('dt', 'r-' + b.key, b.label));
      list.appendChild(el('dd', null, b.words));
    });
    may.appendChild(list);
    box.appendChild(may);
    return box;
  }

  /* ---- what the quest's beats do next (`rouh/questcheck.py`) ----

     Petar, 6 October 2026, on goal 89 the night step 9 was complete and step
     10, the quest's, still said To do: "nothing makes that obivous for me ...
     has to be on hte goals map. but also on the quest I guess. and I have to
     have an option to 'heartbeat' once, no?" So a step that is the quest's
     says on its card what happens to it next - blocked on a step before it,
     or ready and waiting on the quest's next check, and why - and opened, who
     does it, its last check and whether something newer made it out of date,
     the earliest the next one may come, and Check now: one beat on the quest,
     the same as on the quest's own page and from the same state. */

  function nextWords(q) {
    var n = q.next || {};
    if (!n.when) { return ''; }
    return n.soon ? 'any moment now' : n.when + ' (' + q.zone + ' time, in ' + n.in + ')';
  }

  // The goal's one line about its quest, in Where it stands: what the quest's
  // step that comes next is waiting on, one press from opening it.
  function questLine() {
    var q = v.quest;
    if (!q) { return null; }
    var mine = allSteps().filter(function (s) { return s.exec; });
    var ready = mine.filter(function (s) { return !s.exec.blocked_by; })[0] || mine[0];
    var line = el('p', 'gs-line gs-quest');
    line.appendChild(el('span', 'gs-k', 'Quest ' + q.number));
    var when = q.next && q.next.when ? ' · next automatic check ' + nextWords(q) + ', at the earliest'
      : '';
    if (ready) {
      var b = el('button', 'gm-link gs-step', 'Step ' + ready.n + ' “' + ready.title + '”: '
        + ready.exec.label + when + '.');
      b.type = 'button';
      b.addEventListener('click', function () {
        G.panel = ready.id;
        G.reveal = ready.id;
        draw();
      });
      line.appendChild(b);
    } else {
      line.appendChild(document.createTextNode(q.label + when + '.'));
    }
    return line;
  }

  // Under a closed card: the one thing that says most about what happens next.
  function execLine(s) {
    var x = s.exec, q = v.quest || {};
    var words;
    var cls = 'gp-exec-line';
    if (x.blocked_by) {
      words = 'Starts once step ' + x.blocked_by.n + ' is complete';
    } else if (q.live) {
      words = q.live.status === 'running' ? 'Checking now' : 'Asked ' + q.live.when;
    } else if (x.news) {
      words = 'New since its last check: step ' + x.after.n + ' completed';
      cls += ' news';
    } else if (q.next && q.next.when) {
      words = 'Next check ' + (q.next.soon ? 'any moment now' : 'from ' + q.next.when);
    } else if ((q.held || []).length) {
      words = 'No automatic checks: ' + q.held[0].words.replace(/\.$/, '').toLowerCase();
    } else {
      words = 'Waiting for the quest';
    }
    return el('span', cls, words);
  }

  function fact(list, label, value) {
    list.appendChild(el('dt', null, label));
    var dd = el('dd');
    if (typeof value === 'string') { dd.textContent = value; } else if (value) { dd.appendChild(value); }
    list.appendChild(dd);
    return dd;
  }

  function execBox(s) {
    var x = s.exec, q = v.quest;
    var box = el('section', 'gp-exec x-' + x.state);
    box.setAttribute('aria-label', 'What happens next');
    var head = el('div', 'gp-exec-head');
    head.appendChild(el('span', 'gp-exec-k', 'What happens next'));
    head.appendChild(el('span', 'gp-exec-state x-' + x.state, x.label));
    box.appendChild(head);
    var dl = el('dl', 'gp-exec-facts');
    var whoBits = el('span');
    whoBits.appendChild(document.createTextNode(q.executor + ' '));
    whoBits.appendChild(link('Quest ' + q.number, q.href, 'gm-link'));
    fact(dl, 'Who does it', whoBits);
    if (x.blocked_by) {
      var b = x.blocked_by;
      var open = el('button', 'gm-link', 'Step ' + b.n + ' “' + b.title + '”');
      open.type = 'button';
      open.addEventListener('click', function () { G.panel = b.id; G.reveal = b.id; draw(); });
      var why = el('span');
      why.appendChild(document.createTextNode('A step before it is not complete: '));
      why.appendChild(open);
      why.appendChild(document.createTextNode(b.label ? ' (' + b.label.toLowerCase() + ').'
        : ', ' + b.who_words + '.'));
      fact(dl, 'Blocked on', why);
    } else if (x.after) {
      var a = x.after;
      var got = el('span');
      got.appendChild(document.createTextNode('Step ' + a.n + ' “' + a.title + '” was completed'
        + (a.when ? ' ' + a.when : '') + ' by ' + a.by + '.'));
      if (a.note) { got.appendChild(el('q', 'gp-exec-note', a.note)); }
      (a.links || []).forEach(function (u) {
        var l = link(u.length > 60 ? u.slice(0, 57) + '…' : u, u, 'gm-link gp-exec-url');
        l.target = '_blank';
        l.rel = 'noopener noreferrer';
        got.appendChild(l);
      });
      fact(dl, 'Ready since', got);
    }
    if (q.live) { fact(dl, 'Now', q.live.words); }
    var last = q.last_full;
    if (last) {
      var lw = el('span');
      lw.appendChild(document.createTextNode(last.full_when + ': ' + last.words));
      if (last.outdated) { lw.appendChild(el('strong', 'gp-exec-outdated', last.outdated)); }
      fact(dl, 'Last check', lw);
    } else {
      fact(dl, 'Last check', 'None yet.');
    }
    if (q.last && (!last || q.last.id !== last.id)) {
      fact(dl, 'Last look', q.last.full_when + ': ' + q.last.words);
    }
    var reasons = (q.held || []).concat(q.waits || []);
    if (reasons.length) {
      var ul = el('ul', 'gp-exec-why');
      reasons.forEach(function (r) { ul.appendChild(el('li', 'k-' + r.key, r.words)); });
      fact(dl, 'Why it waits', ul);
    }
    if (q.next && q.next.when) {
      var nx = el('span');
      nx.appendChild(el('strong', null, q.next.soon ? 'Any moment now' : q.next.when));
      if (!q.next.soon) {
        nx.appendChild(document.createTextNode(' ' + q.zone + ' time, in ' + q.next.in
          + ', at the earliest.'));
      }
      nx.appendChild(el('span', 'gp-exec-small', q.next.words));
      fact(dl, 'Next automatic check', nx);
    } else {
      fact(dl, 'Next automatic check', 'None: ' + (((q.held || [])[0] || {}).words
        || 'nothing would wake it.'));
    }
    box.appendChild(dl);
    box.appendChild(checkControl(q));
    return box;
  }

  // Check now: one beat on the quest (`questcheck.ask`). Said before the press
  // what it does and what it costs; a paused quest only with the box ticked.
  function checkControl(q) {
    var c = q.check || {};
    var wrap = el('div', 'gp-check');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Check the quest now');
    var once = null;
    if (c.needs_yes) {
      var lab = el('label', 'gp-check-once');
      once = el('input');
      once.type = 'checkbox';
      once.setAttribute('data-keep', 'check-once');
      lab.appendChild(once);
      lab.appendChild(el('span', null, c.yes_words));
      wrap.appendChild(lab);
    }
    var row = el('div', 'gp-check-row');
    var go = button(q.live ? (q.live.status === 'running' ? 'Checking…' : 'Check queued') : 'Check now',
      'primary gp-check-btn', function () {
        act('check', null, { while_paused: !!(once && once.checked) });
      });
    go.setAttribute('data-keep', 'check-now');
    if (!c.can || (once && !once.checked)) { go.disabled = true; }
    if (once) {
      once.addEventListener('change', function () { go.disabled = !framed || G.busy || !once.checked; });
    }
    row.appendChild(go);
    row.appendChild(el('span', 'gp-check-help', c.help));
    wrap.appendChild(row);
    if (c.refused) {
      wrap.appendChild(el('p', 'gp-check-no', 'Check now is not available: ' + c.refused));
    }
    return wrap;
  }

  function needLink(d, label) {
    var b = el('button', 'gm-link gs-step', label
      || (d.label + ' · step ' + d.n + ' “' + d.title + '”: ' + d.words));
    b.type = 'button';
    b.addEventListener('click', function () {
      G.panel = d.step;
      G.stepOpen = null;
      G.reveal = d.step;
      draw();
    });
    return b;
  }

  function steerBox() {
    var wrap = el('div', 'gs-steer');
    var lab = el('label', 'gm-field');
    lab.appendChild(document.createTextNode('What should change from now on'));
    var said = el('textarea');
    said.rows = 3;
    said.maxLength = 1200;
    said.value = G.steer;
    said.setAttribute('data-keep', 'steer');
    said.placeholder = 'Only EU-hosted tools, and look at open-source ones before anything else';
    said.addEventListener('input', function () { G.steer = said.value; });
    lab.appendChild(said);
    wrap.appendChild(lab);
    var acts = el('div', 'goal-step-acts');
    acts.appendChild(button('Redirect Rouh', 'primary', function () {
      if (!said.value.trim()) { said.focus(); return; }
      act('redirect', null, { direction: said.value.trim() });
    }));
    acts.appendChild(button('Cancel', '', function () { G.steering = false; G.steer = ''; draw(); }));
    wrap.appendChild(acts);
    wrap.appendChild(el('p', 'gs-hint', 'Rouh keeps this on the goal, tells every run it starts '
      + 'from now on, and looks the plan over in the goal’s chat. Runs already going finish as they are.'));
    setTimeout(function () { if (document.activeElement !== said) { said.focus(); } }, 0);
    return wrap;
  }

  // Rouh has read it and is asking: that is the one thing waiting on him.
  function asking() {
    var card = el('article', 'gp-panel gp-asking');
    var top = el('div', 'gp-need-top');
    top.appendChild(el('span', 'gp-kind', 'Your answers'));
    card.appendChild(top);
    card.appendChild(el('h3', 'gp-need-title', 'Rouh is asking you what it needs to know'));
    card.appendChild(el('p', 'gp-need-words', 'Rouh has read what you wrote and asked its '
      + 'questions in the goal’s own chat. Once you have answered, it lays out the plan here, '
      + 'in streams.'));
    if (v.chat_href) {
      var acts = el('div', 'goal-step-acts');
      acts.appendChild(link('Answer in the chat', v.chat_href, 'ogs-btn small primary'));
      card.appendChild(acts);
    }
    return card;
  }

  function heading(words, count, extra) {
    var h = el('h2', 'divider', words);
    if (count != null) { h.appendChild(el('span', 'c', count)); }
    (extra || []).forEach(function (x) { h.appendChild(x); });
    return h;
  }

  /* ---- the map ----

     Petar, 27 September 2026, on the first version of this page: "please
     don't make decision points in separate category ... i should be able to
     look at the map and see that something requires my attention ... those
     should be listed vertically on the left and so i can see it a little bit
     like a waterfall chart. every task or list of tasks in a stream ends with
     completion or request for my interaction at the very right."

     So each stream is a row: its name on the left, its steps flowing to the
     right in the order they follow one another, and the step it waits on him
     for in amber. A column of where each row ends, lined up at the right, was
     tried and taken out the same day: "this entire colum is not needed since
     the streams give me the yellow boxes on hte map and it is very visible
     where my attention is needed" (fr_ddae0c0dac24). So the steps have the
     whole width. Pressing a step opens it in its own card, with everything
     prepared for it. On a phone a row is a column: name, then steps
     downward. */

  function board() {
    var sec = el('section', 'gp-board');
    var lanes = v.streams || [];
    var extra = [];
    if (framed && lanes.some(function (l) { return l.startable; })) {
      var all = button('Let Rouh do all it can', 'primary gp-goall', function () {
        act('go', null, {});
      });
      all.title = 'Rouh starts every stream it can carry on with by itself, and goes on with '
        + 'each until it needs you';
      extra.push(all);
    }
    sec.appendChild(heading('Streams', lanes.length, extra));
    var map = el('div', 'gp-map');
    lanes.forEach(function (lane, i) { map.appendChild(row(lane, i, lanes.length)); });
    sec.appendChild(map);
    return sec;
  }

  function row(lane, at, count) {
    var box = el('section', 'gp-row s-' + lane.state);
    box.setAttribute('data-stream', lane.id);
    box.setAttribute('aria-label', 'Stream ' + lane.name + ': ' + lane.words);
    box.appendChild(rowHead(lane, at, count));
    var flow = el('ol', 'gp-flow');
    lane.steps.forEach(function (id) {
      var s = stepById(id);
      if (s) { flow.appendChild(card(s, lane)); }
    });
    if (flow.querySelector('.gp-card.open')) { flow.classList.add('has-open'); }
    box.appendChild(flow);
    return box;
  }

  // The step opened in this card: the step itself, or one of its parts.
  function openIn(s) {
    if (!G.panel) { return null; }
    if (G.panel === s.id) { return s; }
    return (s.parts || []).filter(function (p) { return p.id === G.panel; })[0] || null;
  }

  function rowHead(lane, at, count) {
    var head = el('header', 'gp-row-head');
    if (G.renaming === lane.id) {
      var name = el('input', 'gp-rename');
      name.type = 'text';
      name.value = lane.name;
      name.maxLength = 40;
      name.setAttribute('aria-label', 'Name of the stream');
      var save = function () {
        var said = name.value.trim();
        G.renaming = '';
        if (!said || said === lane.name) { draw(); return; }
        arrange(function (lanes) {
          lanes.forEach(function (l) { if (l.id === lane.id) { l.name = said; } });
        });
      };
      name.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); save(); }
        if (e.key === 'Escape') { e.preventDefault(); G.renaming = ''; draw(); }
      });
      name.addEventListener('blur', function () { if (G.renaming === lane.id) { save(); } });
      head.appendChild(name);
      setTimeout(function () { name.focus(); name.select(); }, 0);
    } else if (framed) {
      var nb = el('button', 'gp-lane-name', lane.name);
      nb.type = 'button';
      nb.title = 'Rename this stream';
      nb.setAttribute('aria-label', 'Rename the stream ' + lane.name);
      nb.addEventListener('click', function () { G.renaming = lane.id; draw(); });
      head.appendChild(nb);
    } else {
      head.appendChild(el('span', 'gp-lane-name', lane.name));
    }
    var line = el('span', 'gp-lane-line');
    line.appendChild(el('span', 'gp-lane-count', lane.done + ' of ' + lane.steps.length));
    if (framed && count > 1) {
      line.appendChild(laneArrow(lane, at, -1, count));
      line.appendChild(laneArrow(lane, at, 1, count));
    }
    head.appendChild(line);
    // Where it stands, so several streams under way at once each say so.
    if (lane.state !== 'empty') { head.appendChild(el('span', 'gp-lane-state', lane.words)); }
    if (lane.startable && framed) {
      var go = button('Let Rouh go', 'primary', function () {
        act('go', null, { stream: lane.id, name: lane.name });
      });
      go.title = 'Rouh does the next step of this stream now, as a run in the background, and '
        + 'carries on with its steps after it until one needs you';
      head.appendChild(go);
    }
    return head;
  }

  // A whole stream one place up or down the map, its steps going with it.
  function laneArrow(lane, at, by, count) {
    var to = at + by;
    var b = el('button', 'gp-lane-move');
    b.type = 'button';
    b.textContent = by < 0 ? '↑' : '↓';
    b.setAttribute('data-keep', 'lane-' + lane.id + (by < 0 ? '-up' : '-down'));
    b.setAttribute('aria-label', 'Move the stream ' + lane.name + (by < 0 ? ' up' : ' down'));
    b.title = by < 0 ? 'Move this stream up' : 'Move this stream down';
    b.disabled = !framed || G.busy || to < 0 || to >= count;
    b.addEventListener('click', function () {
      G.focus = 'lane-' + lane.id + (by < 0 ? '-up' : '-down');
      arrange(function (lanes) {
        var moved = lanes.splice(at, 1)[0];
        lanes.splice(to, 0, moved);
      }, lane.name + ' is ' + (to === 0 ? 'first' : to === count - 1 ? 'last'
        : 'stream ' + (to + 1) + ' of ' + count) + ' now.');
    });
    return b;
  }

  /* A step pressed opens in its own card, which grows to hold it, and the
     steps after it make room. Petar, 28 September 2026 (fr_fefce7acb58c):
     "When I click on a task, details appear under the last task in the
     lane. Instead it should expand itself to give extra details, not create
     another box somewhere else". Its title, or the ×, folds it again. */
  function card(s, lane) {
    var isHead = lane.head === s.id;
    var opened = openIn(s);
    var li = el('li', 'gp-card s-' + (s.hollow ? 'hollow' : s.status) + ' w-' + whoKey(s)
      + (s.rouh_done ? ' rouh-done' : '') + (isHead ? ' head' : '')
      + (isHead && lane.state === 'you' ? ' needs' : '') + (opened ? ' open' : ''));
    li.setAttribute('data-step', s.id);
    if (isHead && lane.state === 'you' && s.needs && s.needs.words) { li.title = s.needs.words; }
    var top = el('div', 'gp-card-top');
    if (framed) {
      var grip = el('button', 'gp-grip');
      grip.type = 'button';
      grip.setAttribute('data-keep', 'grip-' + s.id);
      grip.setAttribute('aria-label', 'Move step ' + s.n + ', ' + s.title
        + '. Left and right move it along its stream; up and down move it to the stream above or below');
      grip.title = 'Drag to move, or use the arrow keys';
      grip.innerHTML = '<svg viewBox="0 0 12 16" aria-hidden="true"><circle cx="3" cy="3" r="1.3"/>'
        + '<circle cx="9" cy="3" r="1.3"/><circle cx="3" cy="8" r="1.3"/><circle cx="9" cy="8" r="1.3"/>'
        + '<circle cx="3" cy="13" r="1.3"/><circle cx="9" cy="13" r="1.3"/></svg>';
      grip.addEventListener('pointerdown', function (e) { dragStart(e, s, li); });
      grip.addEventListener('keydown', function (e) { keyMove(e, s); });
      top.appendChild(grip);
    }
    /* A finished step keeps its number, with its check beside it. Petar,
       6 October 2026 (fr_8154d64497e4): "I like that completed tasks have a
       nice green check ... but I don't like the fact that I can't see the
       step number. even if completed I want to see which number that is, so
       I can comment it." */
    var mark = el('span', 'goal-node', String(s.n));
    mark.setAttribute('aria-hidden', 'true');
    top.appendChild(mark);
    if (s.hollow || s.status === 'done') {
      var tick = el('span', 'gp-done-mark' + (s.hollow ? ' hollow' : ''), s.hollow ? '!' : '✓');
      tick.setAttribute('aria-hidden', 'true');
      top.appendChild(tick);
    }
    if (opened) {
      var x = el('button', 'gp-x', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Close step ' + s.n);
      x.title = 'Fold this step';
      x.addEventListener('click', function () {
        G.panel = '';
        G.stepOpen = null;
        G.focus = 'title-' + s.id;
        draw();
      });
      top.appendChild(x);
    }
    li.appendChild(top);
    var name = el('button', 'gp-card-title', s.title);
    name.type = 'button';
    name.setAttribute('aria-expanded', opened ? 'true' : 'false');
    name.setAttribute('data-keep', 'title-' + s.id);
    name.addEventListener('click', function () {
      G.panel = opened ? '' : s.id;
      G.stepOpen = null;
      G.focus = 'title-' + s.id;
      G.reveal = G.panel;
      draw();
    });
    li.appendChild(name);
    var line = el('div', 'gp-card-line');
    line.appendChild(who(s));
    // A step that is the quest's says what its beats do next, not just To do
    // (`questcheck.for_goal`).
    line.appendChild(el('span', 'goal-status' + (s.exec ? ' gp-exec-label x-' + s.exec.state : ''),
      isHead && lane.state === 'you' && s.needs ? s.needs.label
        : s.exec ? s.exec.label : statusWords(s)));
    li.appendChild(line);
    if (s.exec) { li.className += ' has-exec x-' + s.exec.state; }
    if (opened) {
      li.appendChild(panel(opened, lane, opened !== s));
      return li;
    }
    if (s.exec) { li.appendChild(execLine(s)); }
    if (s.run && s.run.words && s.run.mode !== 'now') {
      li.appendChild(el('span', 'goal-run r-' + s.run.mode, s.run.words));
    }
    if (s.parts && s.parts.length) {
      var done = s.parts.filter(function (p) { return p.status === 'done' && !p.hollow; }).length;
      li.appendChild(el('span', 'gp-parts', done + ' of ' + s.parts.length + ' parts'));
    }
    return li;
  }

  /* One step opened under its row, in four plain blocks. Petar, 27
     September 2026 (fr_e2dde690a576), on this panel: "too many things that
     are confusing and don't give me clear idea. I need the following 1.
     what needs to be done as a whole (title maybe good enough) 2. what ai
     has planned to do. A link to the results (html explainer page in this
     subtask ...) and a icon for status (to do, doing, done, blocked (if it
     requires me to continue)) 3. what is required of me to do, link to
     where I do it, steps described etc. ... and status icon if I have done
     it. 4. buttons for actions 5. those can be hovers on one word each
     "How" "Hard part", "what to do"", and "remove entire line: MOVE earlier
     later To another stream".

     So: the step's title; Rouh's part and his, each a row with its icon,
     what it is in a line and the link to the step's explainer
     (`objectindex.step_explainer`), which is where everything Rouh made and
     every step to take are; and the buttons. Problem, Solution and Method
     are one line under the title (`more`). The handle and the arrow keys
     still move a step. */
  function panel(s, lane, part) {
    var box = el('div', 'gp-panel');
    box.setAttribute('data-step', s.id);
    var need = lane.head === s.id && lane.state === 'you' ? s.needs || {} : null;
    if (need) { box.className += ' k-' + (need.kind || 'action'); }
    // The card says the step's title already; a part opened in it says its own.
    if (part) {
      var title = el('h3', 'gp-need-title');
      title.appendChild(el('span', 'snum', s.n));
      title.appendChild(document.createTextNode(' ' + s.title));
      box.appendChild(title);
    }
    if (G.stepOpen && G.stepOpen.id === s.id && G.stepOpen.kind === 'edit') {
      box.appendChild(editor(s));
      return box;
    }
    var words = more(s);
    if (words) { box.appendChild(words); }
    if (s.exec && v.quest) { box.appendChild(execBox(s)); }
    box.appendChild(sides(s, need));
    if (s.run && s.run.words) {
      var run = el('p', 'goal-run r-' + s.run.mode, s.run.words);
      if (framed && s.run.mode !== 'now' && s.status !== 'done') {
        var off = el('button', 'gm-link', 'Cancel');
        off.type = 'button';
        off.addEventListener('click', function () { act('clear', s); });
        run.appendChild(document.createTextNode(' '));
        run.appendChild(off);
      }
      box.appendChild(run);
    }
    var acts = G.stepOpen && G.stepOpen.id === s.id && G.stepOpen.kind === 'again' && framed
      ? againBox(s) : need ? needActs(s, need) : stepActs(s);
    if (acts.childNodes.length) { box.appendChild(acts); }
    return box;
  }

  // How each part stands (`goals.part_states`), said beside its icon.
  var PART = { todo: 'To do', doing: 'Doing', done: 'Done', blocked: 'Blocked: needs you' };

  function mark(state) {
    var m = el('span', 'gp-mark m-' + state);
    m.setAttribute('aria-hidden', 'true');
    m.textContent = state === 'done' ? '✓' : state === 'blocked' ? '!' : '';
    return m;
  }

  // The first sentence of a paragraph, which is what a row has room for;
  // the whole of it is under How, and on the explainer.
  function lead(text) {
    var t = String(text || '').trim();
    var m = /^[\s\S]*?[.!?](?=\s|$)/.exec(t);
    var one = m ? m[0] : t;
    return one.length > 170 ? one.slice(0, 160).replace(/\s+\S*$/, '') + '…' : one;
  }

  // One row: whose part, its icon and state, what it is, and where it goes.
  function side(label, state, words, links, cls) {
    var row = el('div', 'gp-side ' + (cls || ''));
    row.appendChild(mark(state));
    var main = el('div', 'gp-side-main');
    var head = el('div', 'gp-side-head');
    head.appendChild(el('span', 'gp-side-who', label));
    head.appendChild(el('span', 'gp-side-state s-' + state, PART[state] || state));
    main.appendChild(head);
    if (words) { main.appendChild(el('p', 'gp-side-words', words)); }
    row.appendChild(main);
    var go = el('div', 'gp-side-go');
    links.forEach(function (a) { if (a) { go.appendChild(a); } });
    row.appendChild(go);
    return row;
  }

  function subRows(parts, rouh) {
    if (!parts.length) { return null; }
    var ol = el('ol', 'gp-subs');
    parts.forEach(function (p) {
      var st = rouh && p.rouh_state ? p.rouh_state : p.your_state;
      var li = el('li', 'gp-sub-row');
      li.appendChild(mark(st));
      li.appendChild(el('span', 'gp-sub-t', p.title));
      var state = el('span', 'gp-side-state s-' + st, PART[st] || st);
      li.appendChild(state);
      var to = rouh ? (p.explainer ? p.explainer + '#rouh' : '') : yoursHref(p);
      if (to) { li.appendChild(link(rouh ? 'Results' : 'Open', to, 'gp-go small')); }
      ol.appendChild(li);
    });
    return ol;
  }

  // His own page for a step: what he does, his inputs and Mark as complete
  // (`objectindex.step_yours`, fr_6acc50075110). Results is Rouh's research.
  function yoursHref(s) {
    // A step that asks nothing of him has no page of his (`goals.part_states`).
    if (!s.your_state) { return ''; }
    return s.yours_page || (s.explainer ? s.explainer + '#you' : '');
  }

  function whereLink(s) {
    if (!s.where) { return null; }
    if (/^https?:\/\/\S+$/.test(s.where)) {
      var a = link('Where', s.where, 'gp-go');
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.title = s.where;
      return a;
    }
    return null;
  }

  // Rouh's part and his: what each is, how it stands, and where to look.
  function sides(s, need) {
    var box = el('div', 'gp-sides');
    var rouhParts = (s.parts || []).filter(function (p) {
      return p.who === 'rouh' || p.who === 'together';
    });
    var yourParts = (s.parts || []).filter(function (p) { return p.who !== 'rouh'; });
    if (s.rouh_state || rouhParts.length) {
      var rstate = s.rouh_state || partsState(rouhParts, true);
      // Rouh's own part of the step links its results; parts link their own.
      var results = s.explainer && s.rouh_state ? link(s.rouh_state === 'done' ? 'Results'
        : 'Its page', s.explainer + '#rouh', 'gp-go') : null;
      if (results) { results.title = 'What Rouh does in this step, and what it made'; }
      // What it gets ready for his part says it best, when the step has one.
      var rouh = side('Rouh', rstate, s.rouh_state ? lead(s.prep || s.how) || 'Its part of this step.'
        : '', [results], 'k-rouh');
      var rsub = subRows(rouhParts, true);
      if (rsub) { rouh.querySelector('.gp-side-main').appendChild(rsub); }
      box.appendChild(rouh);
    }
    // A step of Rouh's alone asks nothing of him: no row of his
    // (fr_5404edbbea30, "I only should make decisions or actions rouh can't do").
    if (!s.your_state) { return box; }
    var mine = s.your_words || '';
    if (s.how && mine === s.how) { mine = lead(mine); }
    var guide = yoursHref(s) ? link('How to do it', yoursHref(s),
      'gp-go' + (need ? ' primary' : '')) : null;
    if (guide) {
      guide.title = 'What you do in this step, with room for your notes, and Mark as complete';
    }
    var you = side('You', s.your_state, mine, [whereLink(s), guide],
      'k-you' + (need ? ' now' : ''));
    if (s.where && !whereLink(s)) {
      var at = el('p', 'gp-side-where');
      at.appendChild(el('strong', null, 'Where '));
      at.appendChild(document.createTextNode(s.where));
      you.querySelector('.gp-side-main').appendChild(at);
    }
    if (s.options && s.options.length && s.your_state !== 'done') {
      var opts = el('ul', 'gp-options');
      opts.setAttribute('aria-label', 'The options');
      s.options.forEach(function (o) { opts.appendChild(el('li', null, o)); });
      you.querySelector('.gp-side-main').appendChild(opts);
    }
    // His part broken into steps he ticks on How to do it (fr_84b6c5266a52).
    if (s.your_steps && s.your_steps.length) {
      var ticked = s.your_steps.filter(function (x) { return x.done; }).length;
      var count = el('p', 'gp-side-where gp-steps-count' + (ticked === s.your_steps.length
        ? ' all' : ''));
      count.appendChild(el('strong', null, 'Step by step '));
      count.appendChild(document.createTextNode(ticked + ' of ' + s.your_steps.length + ' done'));
      you.querySelector('.gp-side-main').appendChild(count);
    }
    if (s.outcome && s.your_state !== 'done') { you.title = 'Complete when: ' + s.outcome; }
    var ysub = subRows(yourParts, false);
    if (ysub) { you.querySelector('.gp-side-main').appendChild(ysub); }
    box.appendChild(you);
    return box;
  }

  // Where a set of parts stands together: blocked before doing before to do.
  function partsState(parts, rouh) {
    var states = parts.map(function (p) { return rouh && p.rouh_state ? p.rouh_state : p.your_state; });
    if (states.every(function (x) { return x === 'done'; })) { return 'done'; }
    if (states.indexOf('blocked') >= 0) { return 'blocked'; }
    if (states.indexOf('doing') >= 0 || states.indexOf('done') >= 0) { return 'doing'; }
    return 'todo';
  }

  /* Problem, Solution and Method: one line of three labels under the
     step's title, each showing its words in a tooltip. Petar, 27 September
     2026 (fr_bb6210d0d47a): "Under the title, above the ROUH and YOU action
     boxes, there should be one line that says: PROBLEM, SOLUTION, METHOD
     each should be with a hover tooltip that shows the content." They are
     the step's challenge, solution and how. A label with nothing to say is
     left out. The tooltip opens under a pointer resting on the label, on
     focus from the keyboard, or on a press or a tap, for a finger has no
     hover; Escape, or a press anywhere else, closes it. It is as wide as
     the panel at most and wraps, so it never leaves the screen. Earlier
     (fr_6acc50075110) these were "labels, not buttons", which is why they
     are plain small capitals rather than pills. */
  function more(s) {
    var items = [['hard', 'Problem', s.challenge], ['fix', 'Solution', s.solution],
                 ['how', 'Method', s.how]].filter(function (m) { return m[2]; });
    if (!items.length) { return null; }
    var row = el('div', 'gp-more');
    items.forEach(function (m) {
      var key = s.id + ':' + m[0];
      var wrap = el('span', 'gp-more-w k-' + m[0] + (G.more === key ? ' open' : ''));
      var b = el('button', 'gp-more-b', m[1]);
      b.type = 'button';
      b.setAttribute('aria-expanded', G.more === key ? 'true' : 'false');
      b.setAttribute('data-keep', 'more-' + key);
      var pop = el('span', 'gp-more-pop');
      pop.id = 'gp-more-' + s.id.replace(/[^\w-]/g, '_') + '-' + m[0];
      pop.setAttribute('role', 'tooltip');
      b.setAttribute('aria-describedby', pop.id);
      pop.appendChild(el('strong', null, m[1]));
      pop.appendChild(document.createTextNode(' ' + m[2]));
      b.addEventListener('click', function () { moreOpen(G.more === key ? '' : key); });
      b.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') { return; }
        e.preventDefault();
        e.stopPropagation();
        moreOpen('');
        wrap.classList.add('shut');
      });
      // Escape hides a tooltip the focus or the pointer is holding open too.
      b.addEventListener('blur', function () { wrap.classList.remove('shut'); });
      wrap.addEventListener('mouseleave', function () { wrap.classList.remove('shut'); });
      wrap.setAttribute('data-more', key);
      wrap.appendChild(b);
      wrap.appendChild(pop);
      row.appendChild(wrap);
    });
    return row;
  }

  // The one tooltip held open by a press, or none, without drawing again.
  function moreOpen(key) {
    G.more = key;
    Array.prototype.forEach.call(root.querySelectorAll('.gp-more-w'), function (w) {
      var on = !!key && w.getAttribute('data-more') === key;
      w.classList.toggle('open', on);
      w.querySelector('.gp-more-b').setAttribute('aria-expanded', on ? 'true' : 'false');
    });
  }

  document.addEventListener('click', function (e) {
    if (G.more && !(e.target.closest && e.target.closest('.gp-more-w'))) { moreOpen(''); }
  });

  /* Do it again: Petar, 27 September 2026 (fr_6acc50075110): "do it again
     should also be in the actions, review on my behalf. If I really don't
     like the research, I will click this button input what I didn't like and
     then will trigger redo." Offered once Rouh's part is done: a box for what
     he did not like, and Rouh does the step again told that
     (`goals.again_why`). */
  function canAgain(s) {
    // A step Rouh completed by itself too: he did not have to look at it,
    // but he may, and may not like it (fr_5404edbbea30).
    return s.rouh_state === 'done' && (s.status !== 'done' || s.done_by === 'rouh')
      && !(s.run && s.run.mode === 'now');
  }

  function againButton(s) {
    var b = button('Do it again', 'goal-again', function () {
      G.stepOpen = { id: s.id, kind: 'again', text: '' };
      G.focus = 'again-' + s.id;
      draw();
    });
    b.title = 'Tell Rouh what you did not like, and it does the research again';
    return b;
  }

  function againBox(s) {
    var open = G.stepOpen;
    var box = el('div', 'goal-again-box');
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'Do it again');
    var wrap = el('label', 'gm-field');
    wrap.appendChild(el('span', null, 'What did you not like about it?'));
    var said = el('textarea');
    said.rows = 3;
    said.maxLength = 2000;
    said.placeholder = 'For example: it left out Teams, and the prices are for one seat, not six';
    said.value = open.text || '';
    said.setAttribute('data-keep', 'again-' + s.id);
    said.addEventListener('input', function () {
      open.text = said.value;
      // The line asking for words goes once there are some.
      var ask = box.querySelector('.goal-edit-note');
      if (ask && said.value.trim()) { ask.remove(); open.note = ''; }
    });
    wrap.appendChild(said);
    box.appendChild(wrap);
    var note = open.note ? el('p', 'goal-edit-note bad', open.note) : null;
    if (note) { note.setAttribute('role', 'status'); box.appendChild(note); }
    var acts = el('div', 'goal-step-acts');
    acts.appendChild(button('Do it again', 'primary', function () {
      if (!said.value.trim()) {
        open.note = 'Say what you did not like first.';
        G.focus = 'again-' + s.id;
        draw();
        return;
      }
      act('again', s, { feedback: said.value.trim() });
    }));
    acts.appendChild(button('Cancel', '', function () { G.stepOpen = null; draw(); }));
    box.appendChild(acts);
    return box;
  }

  // Mark as complete lives on his How to do it page; only a step with no
  // page of its own keeps it here.
  function markHere(s, cls) {
    return yoursHref(s) ? null : button('Mark complete', 'goal-done ' + (cls || ''), function () {
      act('status', s, { status: 'done' });
    });
  }

  function put(box, b) { if (b) { box.appendChild(b); } }

  function needActs(s, need) {
    var box = el('div', 'goal-step-acts');
    if (!framed) { return box; }
    if (need.label === 'Start it with Rouh') {
      box.appendChild(button('Start with Rouh', 'primary', function () { act('now', s); }));
      put(box, markHere(s));
    } else if (need.label === 'Rouh is stuck') {
      if (workHref(s)) { box.appendChild(link('See what it needs', workHref(s), 'ogs-btn small primary')); }
      box.appendChild(button('Try again', '', function () { act('now', s); }));
      put(box, markHere(s));
    } else {
      put(box, markHere(s, 'primary'));
      if (canAgain(s)) { box.appendChild(againButton(s)); }
      box.appendChild(change(s, 'Change'));
      if (workHref(s)) { box.appendChild(link('Chat', workHref(s), 'ogs-btn small')); }
    }
    return box;
  }

  // What can be done with one step: Rouh's three ways to start it, and done.
  function stepActs(s) {
    var box = el('div', 'goal-step-acts');
    var open = G.stepOpen && G.stepOpen.id === s.id ? G.stepOpen.kind : '';
    var mine = s.who === 'rouh' && !s.rouh_done && (s.status !== 'done' || s.hollow);
    var going = s.run && s.run.mode === 'now';
    if (!framed) { return box; }
    if (open === 'at') {
      var at = el('div', 'goal-pick');
      var day = el('input');
      day.type = 'date';
      day.value = tomorrow();
      day.setAttribute('aria-label', 'Day');
      var time = el('input');
      time.type = 'time';
      time.value = '09:00';
      time.setAttribute('aria-label', 'Time');
      at.appendChild(day);
      at.appendChild(time);
      at.appendChild(button('Set', 'primary', function () {
        act('at', s, { date: day.value, time: time.value });
      }));
      at.appendChild(button('Cancel', '', function () { G.stepOpen = null; draw(); }));
      box.appendChild(at);
      setTimeout(function () { day.focus(); }, 0);
      return box;
    }
    if (open === 'after') {
      var pick = el('div', 'goal-pick');
      var sel = el('select');
      sel.setAttribute('aria-label', 'After which step');
      allSteps().forEach(function (o) {
        if (o.id === s.id) { return; }
        var opt = el('option', null, o.n + '  ' + o.title + (o.status === 'done' ? ' (complete)' : ''));
        opt.value = o.id;
        sel.appendChild(opt);
      });
      pick.appendChild(sel);
      pick.appendChild(button('Set', 'primary', function () { act('after', s, { after: sel.value }); }));
      pick.appendChild(button('Cancel', '', function () { G.stepOpen = null; draw(); }));
      box.appendChild(pick);
      setTimeout(function () { sel.focus(); }, 0);
      return box;
    }
    if (mine && !going) {
      box.appendChild(button(s.hollow ? 'Do it again' : 'Do it now', 'primary',
        function () { act('now', s); }));
      box.appendChild(change(s, 'Change first'));
      box.appendChild(button('At a time', '', function () {
        G.stepOpen = { id: s.id, kind: 'at' };
        draw();
      }));
      if (allSteps().length > 1) {
        box.appendChild(button('After a step', '', function () {
          G.stepOpen = { id: s.id, kind: 'after' };
          draw();
        }));
      }
    } else if (s.who === 'together' && s.status !== 'done' && !s.rouh_done && !going) {
      var begin = button('Start with Rouh', 'primary', function () { act('now', s); });
      begin.title = s.who_means || '';
      box.appendChild(begin);
      box.appendChild(change(s, 'Change'));
    } else if ((s.status !== 'done' || s.rouh_done) && !going) {
      box.appendChild(change(s, 'Change'));
    }
    if (canAgain(s)) { box.appendChild(againButton(s)); }
    // Only the person completes a step, on its How to do it page.
    put(box, s.status === 'done'
      ? button('Reopen', 'goal-undone', function () { act('status', s, { status: 'not-started' }); })
      : markHere(s, s.rouh_done ? 'primary' : ''));
    return box;
  }

  /* ---- arranging the streams, and moving steps ---- */

  function copyLanes() {
    return (v.streams || []).map(function (l) {
      return { id: l.id, name: l.name, steps: l.steps.slice() };
    });
  }

  // The streams changed here and sent up. Drawn at once as they will be, and
  // put back if Rouh says no.
  function arrange(change, said) {
    if (G.busy) { return; }
    var was = v.streams;
    var lanes = copyLanes();
    change(lanes);
    lanes = lanes.filter(function (l) { return l.steps.length; });
    // Drawn at once from what is known: the server answers with where each
    // stream then stands.
    v.streams = lanes.map(function (l) {
      var old = was.filter(function (o) { return o.id === l.id; })[0] || {};
      return { id: l.id, name: l.name, steps: l.steps, head: old.head || '',
               state: old.state || 'rouh', words: old.words || '', done: old.done || 0 };
    });
    G.busy = true;
    draw();
    tell(MAP, { act: 'arrange', streams: lanes }, function () {
      G.busy = false;
      v.streams = was;
      draw();
    }, function (m) {
      G.busy = false;
      if (m.goal) { v = linked(m.goal); v.framed = framed; }
      G.say = said || '';
      G.sayAt = Date.now();
      G.sayKind = 'good';
      G.sayChat = false;
      draw();
    });
  }

  // One step to a place: `to` a stream's id, `index` where in it,
  // counted before the step is taken out of where it was.
  function move(stepId, to, index) {
    var from = laneOf(stepId);
    if (!from) { return; }
    var s = stepById(stepId);
    var title = s ? s.title : '';
    var target = (v.streams || []).filter(function (l) { return l.id === to; })[0];
    arrange(function (lanes) {
      var src = lanes.filter(function (l) { return l.id === from.id; })[0];
      var at = src.steps.indexOf(stepId);
      src.steps.splice(at, 1);
      var dst = lanes.filter(function (l) { return l.id === to; })[0];
      if (dst === src && index > at) { index -= 1; }
      dst.steps.splice(Math.max(0, Math.min(index, dst.steps.length)), 0, stepId);
    }, target && target.id !== from.id ? '“' + title + '” is in ' + target.name + ' now.'
      : 'Moved “' + title + '”.');
  }

  // Arrows on a step's handle: left and right along its stream, up and down
  // to the same place in the stream above or below.
  function keyMove(e, s) {
    var lane = laneOf(s.id);
    if (!lane || G.busy) { return; }
    var lanes = v.streams || [];
    var li = lanes.indexOf(lane);
    var at = lane.steps.indexOf(s.id);
    var done = true;
    if (e.key === 'ArrowLeft' && at > 0) { move(s.id, lane.id, at - 1); }
    else if (e.key === 'ArrowRight' && at < lane.steps.length - 1) { move(s.id, lane.id, at + 2); }
    else if (e.key === 'ArrowUp' && li > 0) { move(s.id, lanes[li - 1].id, at); }
    else if (e.key === 'ArrowDown' && li < lanes.length - 1) { move(s.id, lanes[li + 1].id, at); }
    else { done = false; }
    if (done) {
      e.preventDefault();
      G.focus = 'grip-' + s.id;
      draw();
    }
  }

  /* Dragging by the handle, with the pointer - a mouse, a pen or a finger -
     rather than the browser's own drag and drop, which a finger cannot do.
     A line shows where the step will go; letting go there moves it, and
     letting go anywhere else, or Escape, puts it back. */
  function dragStart(e, s, li) {
    if (!framed || G.busy || (e.button != null && e.button !== 0)) { return; }
    e.preventDefault();
    var grip = e.currentTarget;
    try { grip.setPointerCapture(e.pointerId); } catch (err) {}
    var box = li.getBoundingClientRect();
    var ghost = el('div', 'gp-ghost', s.title);
    ghost.style.width = Math.min(box.width, 260) + 'px';
    document.body.appendChild(ghost);
    var line = el('li', 'gp-drop');
    G.drag = { id: s.id, li: li, ghost: ghost, line: line, dx: e.clientX - box.left,
               dy: e.clientY - box.top, to: null, moved: false, x0: e.clientX, y0: e.clientY };
    li.classList.add('dragging');
    place(e);

    function moveTo(ev) { place(ev); }
    function end(ev) {
      grip.removeEventListener('pointermove', moveTo);
      grip.removeEventListener('pointerup', end);
      grip.removeEventListener('pointercancel', cancel);
      document.removeEventListener('keydown', esc, true);
      var d = G.drag;
      G.drag = null;
      finish(d, ev && ev.type === 'pointerup');
    }
    function cancel() { end(null); }
    function esc(ev) {
      if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); end(null); }
    }
    grip.addEventListener('pointermove', moveTo);
    grip.addEventListener('pointerup', end);
    grip.addEventListener('pointercancel', cancel);
    document.addEventListener('keydown', esc, true);
  }

  function place(e) {
    var d = G.drag;
    if (!d) { return; }
    d.ghost.style.left = Math.min(e.clientX - Math.min(d.dx, 40), window.innerWidth - 60) + 'px';
    d.ghost.style.top = (e.clientY - d.dy / 2) + 'px';
    if (Math.abs(e.clientX - d.x0) + Math.abs(e.clientY - d.y0) > 4) { d.moved = true; }
    var under = document.elementFromPoint(e.clientX, e.clientY);
    var lane = under && under.closest ? under.closest('.gp-row') : null;
    document.querySelectorAll('.gp-row.over').forEach(function (x) { x.classList.remove('over'); });
    if (d.line.parentNode) { d.line.parentNode.removeChild(d.line); }
    d.to = null;
    if (!lane) { return; }
    lane.classList.add('over');
    var id = lane.getAttribute('data-stream');
    var ol = lane.querySelector('.gp-flow');
    // Along the row at a desk; down the column on a phone.
    var across = getComputedStyle(ol).flexDirection !== 'column';
    var cards = Array.prototype.slice.call(ol.children).filter(function (c) {
      return c.classList.contains('gp-card');
    });
    var index = cards.length;
    for (var i = 0; i < cards.length; i++) {
      var r = cards[i].getBoundingClientRect();
      if (across ? e.clientX < r.left + r.width / 2 : e.clientY < r.top + r.height / 2) {
        index = i;
        break;
      }
    }
    d.line.className = 'gp-drop' + (across ? '' : ' down');
    ol.insertBefore(d.line, cards[index] || null);
    d.to = { stream: id, index: index };
    // Near the edge of the page, it scrolls, so a step can be taken to a
    // stream below the fold.
    var edge = 48;
    if (e.clientY > window.innerHeight - edge) { window.scrollBy(0, 12); }
    else if (e.clientY < edge) { window.scrollBy(0, -12); }
  }

  function finish(d, dropped) {
    if (!d) { return; }
    if (d.ghost.parentNode) { d.ghost.parentNode.removeChild(d.ghost); }
    if (d.line.parentNode) { d.line.parentNode.removeChild(d.line); }
    d.li.classList.remove('dragging');
    document.querySelectorAll('.gp-row.over').forEach(function (x) { x.classList.remove('over'); });
    if (!dropped || !d.moved || !d.to) { return; }
    var from = laneOf(d.id);
    if (!from) { return; }
    if (d.to.stream === from.id) {
      var at = from.steps.indexOf(d.id);
      if (d.to.index === at || d.to.index === at + 1) { return; }
    }
    move(d.id, d.to.stream, d.to.index);
  }

  /* ---- changing a step before it is started ----

     Petar, 27 September 2026: "I should be able to have an extra option to
     correct what it says there and to steer it in my direction before
     submitting it be done." Nothing is kept until he saves it or has it done
     (`goals.reword`). */
  function change(s, label) {
    var b = button(label, 'goal-change', function () {
      var draft = {};
      WORDING.forEach(function (k) { draft[k] = s[k] || ''; });
      // A decision's options are typed one a line.
      draft.options = (s.options || []).join('\n');
      // What the step asks of him now, so he changes what he sees.
      if (!draft.ask && s.left) { draft.ask = s.left; }
      if (!draft.kind && s.needs && s.needs.kind) { draft.kind = s.needs.kind; }
      G.panel = s.id;
      G.stepOpen = { id: s.id, kind: 'edit', draft: draft, ask: '', prev: null,
                     note: '', noteKind: '', asking: false };
      draw();
      var f = root.querySelector('.gp-panel[data-step="' + s.id + '"] .goal-edit-steer input');
      if (f) { f.focus({ preventScroll: false }); }
    });
    b.title = 'Change what this step says and asks of you, yourself or by telling Rouh';
    return b;
  }

  function editor(s) {
    var open = G.stepOpen;
    var mine = s.who === 'rouh';
    // Not a form: the page is sandboxed without forms, so nothing submits.
    var form = el('div', 'goal-edit');
    form.setAttribute('role', 'group');
    form.setAttribute('aria-label', 'Change step ' + s.n);
    var top = el('div', 'goal-step-top');
    top.appendChild(el('span', 'goal-edit-head', 'Changing step ' + s.n));
    top.appendChild(who(s));
    form.appendChild(top);

    function field(key, label, long) {
      var wrap = el('label', 'gm-field');
      wrap.appendChild(el('span', null, label));
      var box = el(long ? 'textarea' : 'input');
      if (long) { box.rows = 2; } else { box.type = 'text'; }
      box.value = open.draft[key] || '';
      box.disabled = open.asking;
      box.addEventListener('input', function () { open.draft[key] = box.value; });
      wrap.appendChild(box);
      form.appendChild(wrap);
    }
    field('title', 'Step', false);
    // What the step asks of him, which is what it delivers (fr_14155d5f5e95).
    var kinds = el('div', 'goal-edit-kind');
    kinds.setAttribute('role', 'radiogroup');
    kinds.setAttribute('aria-label', 'What this step asks of you');
    kinds.appendChild(el('span', 'goal-edit-kind-l', 'What this step asks of you'));
    // Nothing is the step Rouh does alone, complete once it has: he is never
    // asked to review Rouh's work (fr_5404edbbea30).
    [['', 'Nothing, Rouh does it'], ['action', 'Do something'],
     ['decision', 'Make a decision']].forEach(function (k) {
      var opt = el('label', 'goal-edit-kind-o' + (open.draft.kind === k[0] ? ' on' : ''));
      var r = el('input');
      r.type = 'radio';
      r.name = 'kind-' + s.id;
      r.value = k[0];
      r.checked = open.draft.kind === k[0];
      r.disabled = open.asking;
      r.addEventListener('change', function () {
        if (!r.checked) { return; }
        open.draft.kind = k[0];
        // Nothing asked of him: no words of what he does are kept either.
        if (!k[0]) { open.draft.ask = ''; open.draft.options = ''; }
        draw();
      });
      opt.appendChild(r);
      opt.appendChild(document.createTextNode(' ' + k[1]));
      kinds.appendChild(opt);
    });
    form.appendChild(kinds);
    var decide = open.draft.kind === 'decision';
    if (open.draft.kind) { field('ask', decide ? 'What you decide' : 'What you do', false); }
    if (decide) { field('options', 'The options, one a line', true); }
    field('outcome', 'Complete when', false);
    field('how', mine ? 'What Rouh will do, and how' : 'How', true);
    field('challenge', 'Hard part', true);
    field('solution', 'What to do about it', true);

    var steer = el('div', 'goal-edit-steer');
    var ask = el('label', 'gm-field');
    ask.appendChild(el('span', null, 'Or tell Rouh what to change'));
    var row = el('div', 'goal-edit-ask');
    var said = el('input');
    said.type = 'text';
    said.placeholder = 'For example: only tools that work with Google Meet, and keep it short';
    said.value = open.ask;
    said.disabled = open.asking;
    said.addEventListener('input', function () { open.ask = said.value; });
    said.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); revise(s); }
    });
    row.appendChild(said);
    var go = button(open.asking ? 'Rewriting…' : 'Rewrite', '', function () { revise(s); });
    go.disabled = go.disabled || open.asking;
    row.appendChild(go);
    ask.appendChild(row);
    steer.appendChild(ask);
    if (open.note) {
      var note = el('p', 'goal-edit-note ' + (open.noteKind || ''), open.note);
      note.setAttribute('role', 'status');
      if (open.prev) {
        var undo = el('button', 'gm-link', 'Undo');
        undo.type = 'button';
        undo.addEventListener('click', function () {
          open.draft = open.prev;
          open.prev = null;
          open.note = 'Back to how it was before Rouh rewrote it.';
          open.noteKind = '';
          draw();
        });
        note.appendChild(document.createTextNode(' '));
        note.appendChild(undo);
      }
      steer.appendChild(note);
    }
    form.appendChild(steer);

    var acts = el('div', 'goal-step-acts');
    if (mine) {
      acts.appendChild(button('Do it now', 'primary', function () {
        act('now', s, { wording: open.draft });
      }));
    }
    acts.appendChild(button('Save', mine ? '' : 'primary', function () {
      act('reword', s, { wording: open.draft });
    }));
    acts.appendChild(button('Cancel', '', function () { G.stepOpen = null; draw(); }));
    Array.prototype.forEach.call(acts.querySelectorAll('button'), function (b) {
      b.disabled = open.asking || G.busy;
    });
    form.appendChild(acts);
    return form;
  }

  function revise(s) {
    var open = G.stepOpen;
    if (!open || open.asking) { return; }
    if (!open.ask.trim()) {
      open.note = 'Say what to change first, then press Rewrite.';
      open.noteKind = 'bad';
      draw();
      var f = root.querySelector('.gp-panel[data-step="' + s.id + '"] .goal-edit-steer input');
      if (f) { f.focus({ preventScroll: true }); }
      return;
    }
    open.asking = true;
    open.note = 'Rouh is rewriting it…';
    open.noteKind = '';
    draw();
    tell(REVISE, { step: s.id, wording: open.draft, ask: open.ask }, function (m) {
      if (G.stepOpen !== open) { return; }
      open.asking = false;
      open.note = (m && m.error) || 'Rouh could not rewrite it. Try again.';
      open.noteKind = 'bad';
      draw();
    }, function (m) {
      if (G.stepOpen !== open) { return; }
      open.asking = false;
      if (!m.wording) {
        open.note = 'Rouh could not rewrite it. Try again.';
        open.noteKind = 'bad';
      } else {
        open.prev = open.draft;
        // What Rouh left out of its answer stays as it was.
        open.draft = Object.assign({}, open.prev, m.wording);
        if (Array.isArray(m.wording.options)) { open.draft.options = m.wording.options.join('\n'); }
        open.ask = '';
        open.note = 'Rouh rewrote it the way you asked. Change it more, ask again, or '
          + (s.who === 'rouh' ? 'have it done.' : 'save it.');
        open.noteKind = 'good';
      }
      draw();
    });
  }

  // One press, handed up; the goal comes back as it now is.
  function act(what, s, more) {
    if (G.busy || !framed) { return; }
    G.busy = true;
    var said = { act: what };
    if (s) { said.step = s.id; }
    Object.keys(more || {}).forEach(function (k) { if (k !== 'name') { said[k] = more[k]; } });
    draw();
    tell(MAP, said, function () {
      G.busy = false;
      draw();
    }, function (m) {
      G.busy = false;
      G.stepOpen = null;
      G.dueOpen = false;
      if (what === 'redirect') { G.steering = false; G.steer = ''; }
      if (m.goal) { v = linked(m.goal); v.framed = framed; }
      var title = more && more.wording ? more.wording.title : (s ? s.title : '');
      G.sayHref = '';
      G.say = {
        now: (s && s.who === 'together'
          ? 'Rouh is getting “' + title + '” ready for you in the background, and will say what is left for you'
          : 'Rouh is doing “' + title + '” now, in the background')
          + (more && more.wording ? ', the way you worded it.' : '.'),
        go: more && more.name
          ? 'Rouh is carrying on with ' + more.name + ' by itself, in the background, until it needs you.'
          : 'Rouh is carrying on by itself with every stream it can, all at once in the background, until each needs you.',
        at: 'Rouh will do “' + title + '” then, in the background.',
        after: 'Rouh will do “' + title + '” as soon as that step is done.',
        again: 'Rouh is doing “' + title + '” again in the background, with what you did not like.',
        clear: 'Rouh will not do “' + title + '” by itself.',
        reword: 'Kept your wording of “' + title + '”.',
        status: more && more.status === 'done' ? 'Complete: “' + title + '”.'
          : '“' + title + '” is back to do.',
        deadline: more && more.deadline ? 'The deadline is ' + v.deadline_words + '.'
          : 'The goal has no deadline now.',
        pause: 'Paused. Nothing new starts until you resume it.',
        resume: 'Resumed. Whatever Rouh can do by itself goes on.',
        redirect: more && more.direction
          ? 'Redirected. Rouh is looking the plan over in the goal’s chat.'
          : 'The direction is cleared.',
        check: m.said || 'Check queued.'
      }[what] || '';
      G.sayAt = Date.now();
      G.sayKind = 'good';
      // A line lands in the goal's chat when a run finishes, not the work;
      // a redirect is Rouh looking the plan over there, which can be watched.
      G.sayChat = what === 'redirect' && !!(more && more.direction);
      draw();
    });
  }

  draw();
}());
