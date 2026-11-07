/* A task's or a step's own page at /workspace/_task/<its folder>/.

   The markup is `objectindex.build_task`, and the one thing on it that asks
   Rouh for anything is this: **Start chat**, floating in the bottom right
   corner, where a project's page has its New. It is the only way into a chat
   the page offers, and it is in reach at the bottom of a task with forty
   steps as much as at the top.

   Petar, 23 September 2026, the afternoon he first asked for it: he wanted to
   start a chat about a task from the task's own page, and there was nothing
   on the page to press. That evening there were two - a big button under the
   task's name and this one - and both said "continue": "i don't need a button
   to continue chat, I need a button to start a chat. and I don't need 2
   places on that scren. bottom right is good enough". So this is the one, and
   it starts a chat every time: an empty conversation about the task, the
   task's own while nothing has been said about it and a new one beside it
   once something has (`conversations.start_for_task`). The chats the task
   already holds are listed on the page under Chats.

   How it asks
   -----------

   It cannot open anything itself. The page is sandboxed with an origin of its
   own, so it hands the press to the page around it, which is signed in and
   holds the socket: `rouh-page-chat` with this task's id on it, the message a
   project's page starts a chat with. Which task the chat is about is Rouh's
   own answer, read off the page it framed, and never this page's (`taskChat`
   in app.js). The answer comes back as `rouh-frame-project`, and only a
   refusal has anything in it to show.

   Opened at its own address there is no page around it, so it is not drawn.

   Answering it, right there
   -------------------------

   A task that is waiting on the person asks in its page's Decision, a
   compact card that opens in place (`objectindex._waiting_panel`): what has
   stopped, the question, the answers it offers, a field for their own words,
   and what answering does. Opening and folding it is the page's own
   `<details>`, and needs nothing from here.
   Until 24 September 2026 it had one button, Answer, which put the question
   in Rouh's box and left the person to write the rest. Petar: "easy options
   for answers predefined for me and option to give my own. but right there."

   So an option is sent with one press, and the field with Enter or its
   arrow. Where several may be picked, a press marks one and the button under
   them sends every one marked. What goes up is the same press as Start chat
   with the words to say on it, and it does not start a chat: Rouh sends
   them, as if typed, in the chat the task already has, beside the page, and
   in a new one only when the task has none (`taskChat` in app.js; Petar, 24
   September 2026: "that should go to the main chat, not opne a new chat").
   With them go what was asked and what was answered, so the server can
   write the answer down (`rouh/answering.py`). The box then says it was
   sent and where, at once, and Rouh loads the page again once it has
   answered, when the box says which job has it. A refusal from Rouh puts
   the box back as it was. */
(function () {
  'use strict';
  var DATA = window.ROUH_TASK || {};
  var CHAT = 'rouh-page-chat', DISMISS = 'rouh-page-dismiss', BACK = 'rouh-frame-project';
  var GOAL = 'rouh-page-goal';
  var TASK = 'rouh-page-task';

  // A goal is on a page of its own (`goalpage.js`), and its task's page lists
  // it as one line among its chats and subtasks.

  if (!DATA.framed) { return; }

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
    if (!m || m.type !== BACK || !asked[m.id]) { return; }
    var said = asked[m.id];
    delete asked[m.id];
    if (!m.ok) {
      // An upload says why on its own line under Files, and not twice.
      if (!said.quiet) { toast(m.error || 'Rouh could not start the chat.'); }
      if (typeof said.refused === 'function') { said.refused(m); }
    } else if (typeof said.done === 'function') {
      said.done(m);
    }
  });

  /* One press handed up to Rouh: `type` and what goes with it. `refused` is
     called when Rouh says no, or cannot be reached; `done`, when it has done
     it, with what it answered. `moving` is what is transferred rather than
     copied: a file's bytes. */
  function tell(type, said, refused, done, moving, quiet) {
    var up;
    try { up = window.parent; } catch (err) { up = null; }
    if (!up || up === window) {
      toast('Rouh could not be reached.');
      if (refused) { refused(); }
      return;
    }
    var id = 't' + (++seq);
    asked[id] = { refused: refused, done: done, quiet: !!quiet };
    said.type = type;
    said.id = id;
    try { up.postMessage(said, '*', moving || []); }
    catch (err) {
      delete asked[id];
      toast('Rouh could not be reached.');
      if (refused) { refused(); }
    }
  }

  /* `more` is what else goes up with the press: `say`, words to send at
     once in the task's chat, and `answers`, what was asked and answered. */
  function startChat(more, refused) {
    var said = { task: String(DATA.task || '') };
    if (more && typeof more.say === 'string' && more.say) { said.say = more.say; }
    if (more && more.answers) { said.answers = more.answers; }
    tell(CHAT, said, refused);
  }

  /* A bubble where the project page's New has its plus, and the words say
     what it does. The name a screen reader hears says what the chat is
     about, which on a subtask's page is the subtask: its chat is its own. */
  var start = document.createElement('button');
  start.type = 'button';
  start.className = 'pjnew tknew';
  start.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" '
    + 'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M20.5 11.6a7.6 7.6 0 0 1-10.9 6.9L4 20l1.6-5.2A7.6 7.6 0 1 1 20.5 11.6z"/></svg>';
  start.appendChild(document.createTextNode('Start chat'));
  var named = 'Start a new chat about ' + (DATA.about || 'this task');
  start.setAttribute('aria-label', named);
  start.title = named;
  start.addEventListener('click', function () { startChat(); });
  document.body.appendChild(start);

  /* A step of a goal: its buttons (`objectindex._goal_step_panel`). Start
     with Rouh, or Do it now, has Rouh start the step in the goal's chat,
     which opens beside the page; Mark done and Reopen change its status.
     Which step is Rouh's answer, read off the page it framed, never this
     page's (`taskGoalStep` in app.js), and Rouh loads the page again once
     it is done, so what it says after the press is the step as it is. */
  var goalActs = document.getElementById('ogsActs');
  /* Other, on a step's How to do it page: picked, a field opens under it for
     what he wants instead, and his words go up as the choice. */
  var otherPick = document.getElementById('ogsOtherPick');
  var otherBox = document.getElementById('ogsOtherBox');
  var otherText = document.getElementById('ogsOther');
  if (otherPick && otherBox && otherText) {
    Array.prototype.forEach.call(document.querySelectorAll('input[name="ogsChoice"]'), function (r) {
      r.addEventListener('change', function () {
        otherBox.hidden = !otherPick.checked;
        if (otherPick.checked) { otherText.focus(); }
      });
    });
  }
  if (goalActs) {
    goalActs.hidden = false;
    Array.prototype.forEach.call(goalActs.querySelectorAll('button[data-goal-act]'), function (b) {
      b.addEventListener('click', function () {
        var all = goalActs.querySelectorAll('button');
        Array.prototype.forEach.call(all, function (x) { x.disabled = true; });
        var said = { act: b.getAttribute('data-goal-act') };
        // A step's How to do it page (`objectindex.step_yours`): what he
        // wrote and picked goes with Save and with Mark as complete.
        var note = document.getElementById('ogsNote');
        if (note && said.act !== 'undone') {
          said.note = note.value;
          var picked = document.querySelector('input[name="ogsChoice"]:checked');
          if (picked && picked === otherPick) {
            // Other is his own words, and there must be some.
            var own = otherText.value.trim();
            if (!own) {
              Array.prototype.forEach.call(all, function (x) { x.disabled = false; });
              toast('Write what you want under Other first.');
              otherText.focus();
              return;
            }
            said.choice = own;
          } else if (picked) { said.choice = picked.value; }
        }
        tell(GOAL, said, function () {
          Array.prototype.forEach.call(all, function (x) { x.disabled = false; });
        });
      });
    });
  }

  /* A step's How to do it page: his part as steps to tick, one by one
     (`objectindex._your_steps_html`, fr_84b6c5266a52). A press is drawn at
     once - struck through and dimmed, the count and the bar moved on - and
     handed up to be kept on the step (`goals.tick_your_step`); if Rouh says
     no, the box goes back to how it was and the toast says why. Ticking the
     last one does not complete the step: Mark as complete stays his. */
  var stepsBox = document.getElementById('ogsSteps');
  if (stepsBox) {
    var boxes = stepsBox.querySelectorAll('input[type="checkbox"][data-step]');
    var drawSteps = function () {
      var ticked = 0;
      Array.prototype.forEach.call(boxes, function (x) {
        if (x.checked) { ticked += 1; }
        var li = x.closest('li');
        if (li) { li.classList.toggle('is-done', x.checked); }
      });
      var count = document.getElementById('ogsCount');
      if (count) { count.textContent = ticked + ' of ' + boxes.length + ' done'; }
      var bar = document.getElementById('ogsBar');
      if (bar) { bar.style.width = (boxes.length ? Math.round(100 * ticked / boxes.length) : 0) + '%'; }
      stepsBox.classList.toggle('all-done', boxes.length > 0 && ticked === boxes.length);
    };
    drawSteps();
    Array.prototype.forEach.call(boxes, function (x) {
      x.addEventListener('change', function () {
        var now = x.checked;
        drawSteps();
        tell(GOAL, { act: 'tick', index: Number(x.getAttribute('data-step')),
                     text: x.getAttribute('data-text') || '', done: now }, function () {
          x.checked = !now;
          drawSteps();
        });
      });
    });
  }

  /* The three dots at the right of the name: Rename, Move, Archive and Delete.

     Petar, 27 September 2026 (fr_3273da8d3be9), on a task's page: "just like
     a chat, I should have ... and then a menu that allows me to rename and
     delete this task." The same menu every three dots in Rouh open
     (`menu.js`), with the chat's two items in the chat's order.

     Rename is where the name is: it becomes a field with the name in it,
     selected, as a row's name does in Rouh's lists (`renameStart` in
     app.js). Enter keeps it, and so does clicking away; Escape puts the old
     one back. Rouh writes it (`rename_object`), and the name on this page
     changes at once and goes back if Rouh says no.

     Delete does nothing here but hand the press up: Rouh opens its one
     delete dialog, which names the task and counts what goes with it - its
     chats, its subtasks, its goal and the files in its folder - and nothing
     is deleted until its button is pressed. Which task, for either, is
     Rouh's own answer, read off the address it framed (`taskPageAct` in
     app.js), never this page's. */
  var tkBar = document.getElementById('tkBar');
  var tkMore = document.getElementById('tkMore');
  var tkMenu = document.getElementById('tkMenu');
  var tkName = document.getElementById('tkName');
  if (tkBar && tkMore && tkMenu && tkName && window.RouhMenu) {
    tkBar.hidden = false;
    window.RouhMenu.bind(tkMore, tkMenu);
    document.getElementById('tkRename').addEventListener('click', renameStart);
    /* Move: Rouh's picker, over the page, of every project and task this
       one could go into (`moveOpen` in app.js). Once it has moved, Rouh
       loads its page at the new address, under its new number. */
    var tkMove = document.getElementById('tkMove');
    if (tkMove) {
      tkMove.addEventListener('click', function () { tell(TASK, { act: 'move' }); });
    }
    /* A subtask's two ways out of its task (`rouh/moving.py`): the first
       subtask of a new task made for it, or a task of its own. Rouh moves it
       and loads its new place, under its new number. */
    ['tkNewTask', 'tkPromote'].forEach(function (key) {
      var b = document.getElementById(key);
      if (b) { b.addEventListener('click', function () { tell(TASK, { act: b.getAttribute('data-act') }); }); }
    });
    document.getElementById('tkDelete').addEventListener('click', function () {
      tell(TASK, { act: 'delete' });
    });
    /* Archive, or Unarchive on one that is archived: Rouh archives it and
       everything under it, and loads this page again, which then wears the
       Archived pill and offers Unarchive (`rouh/archiving.py`). */
    var tkArchive = document.getElementById('tkArchive');
    if (tkArchive) {
      tkArchive.addEventListener('click', function () {
        tell(TASK, { act: tkArchive.getAttribute('data-on') === 'false' ? 'unarchive' : 'archive' });
      });
    }
    /* Whose task it is (`rouh/task_origin.py`): two of "This is my task",
       "Made for someone else" and "Made by Rouh", the two it is not. Rouh
       keeps it, nothing marks it again, and this page is loaded again, which
       then says who made it. */
    Array.prototype.forEach.call(document.querySelectorAll('.tkwhose'), function (b) {
      b.addEventListener('click', function () { tell(TASK, { act: b.getAttribute('data-act') }); });
    });
  }

  /* Each item's own three dots, at the end of its line: a page, a .md
     (`objectindex._item_line`). Petar, 15 October 2026 (fr_4c075039223f):
     "Each item in the folder of a task or sub task should have its
     dotdotdot menu and then inside could be the PDF option". So PDF is made
     of the one item whose dots were pressed and nothing else, on the paper
     its item says; Rouh puts the folder it framed in front of the item's
     path and starts it, and its notifications say when it is ready
     (`taskPageAct` in app.js, `rouh/page_pdf.py`). The menu is the item's,
     so what else an item can have done to it later goes in the same box. */
  /* Since the same evening a chat, a fork, a subtask and a page under
     Sources have their own three dots too (fr_e8be3507d4d6): "The chats and
     the page and finals don't have dots, and they should. Chat should be
     pdf-able as well as pages. Subtasks can have at least the dots if not
     pdf". Each line says what it is - `data-item` a file in this task,
     `data-chat` a chat, `data-sub` a subtask's folder under this one - and
     every item of its menu hands its `data-act` up with that, for Rouh to do
     to the thing the line names (`taskPageAct` in app.js). A Pin is drawn as
     Un-pin once Rouh has done it, and back. */
  /* Check sources, at the end of a page's line under Sources
     (`objectindex._sources_section`). Petar, 17 October 2026
     (fr_563bcb1bdb26): "make the check sources off by default and on demand
     with click of a button". So a page's sources are read only once this is
     pressed: Rouh starts the check of that one page and opens its Sources,
     where it is seen being read (`taskPageAct` in app.js). */
  Array.prototype.forEach.call(document.querySelectorAll('.ocheck'), function (b) {
    var words = b.textContent;
    b.hidden = false;
    b.addEventListener('click', function () {
      b.disabled = true;
      b.textContent = 'Starting…';
      tell(TASK, { act: 'check_sources', item: b.getAttribute('data-check') }, function () {
        b.disabled = false;
        b.textContent = words;
      });
    });
  });

  if (window.RouhMenu) {
    var itemMenus = [];
    Array.prototype.forEach.call(document.querySelectorAll('.imenu'), function (menu) {
      var line = menu.parentElement;
      var dots = line && line.querySelector('.odots');
      if (!dots) { return; }
      dots.hidden = false;
      itemMenus.push(window.RouhMenu.bind(dots, menu, { align: 'end' }));
      Array.prototype.forEach.call(menu.querySelectorAll('[data-act]'), function (b) {
        b.addEventListener('click', function () {
          var act = b.getAttribute('data-act');
          if (act === 'rename') { itemRenameStart(line, dots); return; }
          var said = { act: act };
          ['item', 'chat', 'sub', 'name', 'title'].forEach(function (k) {
            var v = line.getAttribute('data-' + k);
            if (v) { said[k] = v; }
          });
          if (act === 'pdf') { said.paper = b.getAttribute('data-paper') || 'letter'; }
          // Quiet for a PDF: Rouh says how it went in its own notifications, once.
          tell(TASK, said, null, function () {
            if (act !== 'pin' && act !== 'unpin') { return; }
            var on = act === 'pin';
            b.setAttribute('data-act', on ? 'unpin' : 'pin');
            window.RouhMenu.label(b, on ? 'Un-pin' : 'Pin');
            window.RouhMenu.icon(b, on ? 'unpin' : 'pin');
          }, null, act === 'pdf');
        });
      });
    });
    // Fixed to the frame, so a scroll would leave it behind its dots.
    window.addEventListener('scroll', function () {
      itemMenus.forEach(function (show) { show(false); });
    }, { passive: true });
  }

  /* Rename, in an item's three dots: a page under Page given another name in
     place, as the task's own name is (`renameStart`). Petar, 26 October 2026
     (fr_0234d21daa0b): "Add rename to this context menu". Enter keeps it, and
     so does clicking away; Escape puts the old one back. A step's own page is
     called what the step is, so renaming it renames the step, and the step's
     name over the page changes with it (`data-names`, `objectindex._item_line`).
     Any other page keeps its file and changes its own title, which is a line
     in its history with an Undo (`pagehistory.retitle`). */
  function itemRenameStart(line, dots) {
    var name = line.querySelector('.oname');
    if (!name || line.querySelector('.oname-edit')) { return; }
    var link = line.querySelector('a[href]');
    var was = name.textContent;
    var field = document.createElement('input');
    field.type = 'text';
    field.className = 'oname-edit';
    field.value = was;
    field.maxLength = 200;
    field.setAttribute('aria-label', 'The new name');
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('spellcheck', 'false');
    // The name is inside the line's link: a press in the field must not open the page.
    function hold(e) { e.preventDefault(); }
    if (link) { link.addEventListener('click', hold); }
    name.hidden = true;
    name.parentNode.insertBefore(field, name.nextSibling);
    var step = line.getAttribute('data-names') === 'step';
    function show(words) {
      name.textContent = words;
      if (dots) {
        dots.setAttribute('aria-label', 'What to do with ' + words);
        dots.title = 'What to do with ' + words;
      }
      if (step && tkName) {
        tkName.textContent = words;
        document.title = words;
      }
    }
    var done = false;
    function stop(keep) {
      if (done) { return; }
      done = true;
      var said = field.value.replace(/\s+/g, ' ').trim();
      if (field.parentNode) { field.parentNode.removeChild(field); }
      name.hidden = false;
      // Let go after the press that ended it, which would otherwise open the page.
      setTimeout(function () { if (link) { link.removeEventListener('click', hold); } }, 0);
      if (!keep || !said || said === was) { return; }
      show(said);
      tell(TASK, step ? { act: 'rename', title: said }
                      : { act: 'retitle', item: line.getAttribute('data-item') || '', title: said },
           function () { show(was); });
    }
    field.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); });
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        stop(true);
      } else if (e.key === 'Escape') {
        // Stopped here, so it does not also climb Rouh's canvas a level.
        e.preventDefault();
        e.stopPropagation();
        stop(false);
        if (dots) { dots.focus(); }
      }
    });
    field.addEventListener('blur', function () { stop(true); });
    field.focus();
    field.select();
  }

  /* The pin, before the three dots: one press pins this task or subtask to
     the Control Room, one more unpins it (`rouh/pinning.py`). Petar, 29
     September 2026: in the header of every task and step page, not in the
     menu. It is drawn at once and put back if Rouh says no; it pins this
     one only, never the task above it or the steps under it. */
  var tkPin = document.getElementById('tkPin');
  if (tkPin && tkBar && !tkBar.hidden) {
    var drawPin = function (on) {
      tkPin.setAttribute('aria-pressed', on ? 'true' : 'false');
      tkPin.setAttribute('aria-label', on ? 'Unpin from the Control Room' : 'Pin to the Control Room');
      tkPin.title = on ? 'Pinned to the Control Room. Press to unpin' : 'Pin to the Control Room';
      tkPin.querySelector('.opin-w').textContent = on ? 'Pinned' : 'Pin';
    };
    tkPin.addEventListener('click', function () {
      var on = tkPin.getAttribute('aria-pressed') !== 'true';
      drawPin(on);
      tkPin.disabled = true;
      tell(TASK, { act: on ? 'pin' : 'unpin' }, function () {
        drawPin(!on);
        tkPin.disabled = false;
      }, function () { tkPin.disabled = false; });
    });
  }

  /* Upload, before the pin: files onto this task or subtask, from the
     browser's own picker, several at once (`objectindex._upload_button`).

     Petar, 15 October 2026 (fr_f79f49b86538): "when I open a task, please
     put an upload button so I can upload files directly there". A button
     rather than an item in the three dots, which are for rarer things.

     The picker is in this page, because a picker opens only on a press the
     person really made. The bytes go up to Rouh as an ArrayBuffer,
     transferred, the way a project's Add files sends them and for the same
     reason: a `File` this sandboxed page hands up is refused inside the
     browser (`projectpage.js` says how). Rouh uploads it signed in, to the
     task it framed (`taskUpload` in app.js), and answers with the task's
     files as they now are.

     Each file chosen is a line under Files at once, saying it is uploading;
     it becomes the file once it is up, or says in red why not, with a cross
     to clear it, and that line is the whole of the error: no toast as well. One at a time, in the order chosen. A file dropped on the
     page is uploaded the same way. */
  var upBtn = document.getElementById('tkUpload');
  var filesSet = document.getElementById('tkFilesSet');
  var fileRows = document.getElementById('tkFileRows');
  var fileCount = document.getElementById('tkFileCount');
  // The lines that are not files on the task: those still going up, and
  // those that did not go, which stay until their cross is pressed. Both
  // are put back under the files every time the files are drawn again.
  var going = [];
  var stuck = [];

  // As the server says it (`attachments.human_size`), so a line drawn here
  // reads the same as one the page was served with.
  function human(n) {
    n = Number(n) || 0;
    if (n < 1024) { return n + ' bytes'; }
    if (n < 1048576) { return (n / 1024).toFixed(0) + ' kB'; }
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function cell(tag, cls, words) {
    var n = document.createElement(tag);
    n.className = cls;
    if (words != null) { n.textContent = String(words); }
    return n;
  }

  function crossFor(row, name, act) {
    var x = cell('button', 'fdrop', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', act + ' ' + name);
    x.title = act + ' ' + name;
    row.appendChild(x);
    return x;
  }

  /* A file that is on the task: its line opens it, and its cross takes it off. */
  function bindDrop(row) {
    var link = row.querySelector('.oname');
    var name = link ? link.textContent : 'this file';
    var x = crossFor(row, name, 'Take off');
    x.addEventListener('click', function () {
      x.disabled = true;
      tell(TASK, { act: 'drop_file', file: row.getAttribute('data-file') || '' }, function () {
        x.disabled = false;
      }, function (m) {
        drawFiles(m.files || []);
      });
    });
  }

  function drawFiles(files) {
    if (!fileRows) { return; }
    fileRows.textContent = '';
    files.forEach(function (one) {
      var row = cell('div', 'orow frow');
      row.setAttribute('data-file', one.id);
      row.appendChild(cell('span', 'omark', '\ud83d\udcce'));
      var open = cell('a', 'oname', one.name);
      open.href = one.at;
      open.target = '_blank';
      open.rel = 'noopener';
      row.appendChild(open);
      row.appendChild(cell('span', 'ometa-cell', human(one.size)));
      bindDrop(row);
      fileRows.appendChild(row);
    });
    stuck.concat(going).forEach(function (row) { fileRows.appendChild(row); });
    counted();
  }

  // The count on the rule is the files that are on the task; the section is
  // there while it holds anything at all, a line still uploading included.
  function counted() {
    if (!fileRows || !filesSet) { return; }
    var on = fileRows.querySelectorAll('.frow[data-file]').length;
    if (fileCount) { fileCount.textContent = String(on); }
    filesSet.hidden = !fileRows.children.length;
  }

  function pendingRow(one) {
    var row = cell('div', 'orow frow is-up');
    uploadingLine(row, one);
    going.push(row);
    fileRows.appendChild(row);
    counted();
    return row;
  }

  function uploadingLine(row, one) {
    row.className = 'orow frow is-up';
    row.setAttribute('role', 'status');
    row.textContent = '';
    row.appendChild(cell('span', 'omark fspin'));
    row.appendChild(cell('span', 'oname', one.name));
    row.appendChild(cell('span', 'ometa-cell', 'Uploading\u2026'));
    // Where the cross is on every other line, so the words line up.
    row.appendChild(cell('span', 'fgap'));
  }

  /* The failed line goes back to uploading where it is, and the file goes up
     after whatever is already going. */
  function retryOne(row, one) {
    stuck = stuck.filter(function (r) { return r !== row; });
    going.push(row);
    uploadingLine(row, one);
    if (upBtn) { upBtn.classList.add('is-busy'); }
    queue = queue.then(function () { return sendOne(one, row); }).then(function () {
      if (!going.length && upBtn) { upBtn.classList.remove('is-busy'); }
    });
  }

  function failed(row, one, why) {
    going = going.filter(function (r) { return r !== row; });
    stuck.push(row);
    row.className = 'orow frow is-bad';
    row.setAttribute('role', 'alert');
    row.textContent = '';
    row.appendChild(cell('span', 'omark', '!'));
    // The name once: Rouh's reason usually starts with it.
    var said = cell('span', 'oname', one.name);
    var rest = why.indexOf(one.name) === 0 ? why.slice(one.name.length) : ': ' + why;
    said.appendChild(cell('span', 'fwhy', rest));
    said.title = one.name + rest;
    row.appendChild(said);
    var meta = cell('span', 'ometa-cell fbad', 'Not uploaded');
    // Retry: the same file again, from this line, without the picker.
    var again = cell('button', 'fretry', 'Retry');
    again.type = 'button';
    again.title = 'Upload ' + one.name + ' again';
    again.setAttribute('aria-label', 'Retry uploading ' + one.name);
    again.addEventListener('click', function () { retryOne(row, one); });
    meta.appendChild(again);
    row.appendChild(meta);
    var x = crossFor(row, one.name, 'Clear the failed upload of');
    x.addEventListener('click', function () {
      stuck = stuck.filter(function (r) { return r !== row; });
      if (row.parentNode) { row.parentNode.removeChild(row); }
      counted();
    });
  }

  /* One file's bytes, read here: Rouh cannot reach into this page's origin. */
  function bytesOf(one) {
    return new Promise(function (ok, no) {
      var reader = new FileReader();
      reader.onload = function () { ok(reader.result); };
      reader.onerror = function () { no(new Error('It could not be read from your device.')); };
      reader.readAsArrayBuffer(one);
    });
  }

  function sendOne(one, row) {
    return bytesOf(one).then(function (buffer) {
      return new Promise(function (ok) {
        tell('rouh-page-upload', { task: true, name: one.name, media_type: one.type || '',
                                   bytes: buffer },
          function (m) {
            var why = (m && m.error) || 'Rouh could not be reached.';
            failed(row, one, why);
            ok(false);
          },
          function (m) {
            going = going.filter(function (r) { return r !== row; });
            drawFiles(m.files || []);
            ok(true);
          }, [buffer], true);
      });
    }, function (err) {
      failed(row, one, err.message);
      return false;
    });
  }

  var queue = Promise.resolve();

  function uploadAll(chosen) {
    if (!chosen.length || !fileRows) { return; }
    var rows = chosen.map(pendingRow);
    // Where the person can see it: the Files rule, brought into view.
    if (filesSet && filesSet.scrollIntoView) {
      filesSet.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    if (upBtn) { upBtn.classList.add('is-busy'); }
    queue = chosen.reduce(function (before, one, i) {
      return before.then(function () { return sendOne(one, rows[i]); });
    }, queue).then(function () {
      if (!going.length && upBtn) { upBtn.classList.remove('is-busy'); }
    });
  }

  if (upBtn && tkBar && !tkBar.hidden && fileRows) {
    var picker = document.createElement('input');
    picker.type = 'file';
    picker.multiple = true;
    picker.className = 'vh';
    // The button is the control; this is only how the browser is asked.
    picker.tabIndex = -1;
    picker.setAttribute('aria-hidden', 'true');
    document.body.appendChild(picker);
    upBtn.addEventListener('click', function () { picker.click(); });
    picker.addEventListener('change', function () {
      var chosen = Array.prototype.slice.call(picker.files || []);
      picker.value = '';
      uploadAll(chosen);
    });
    Array.prototype.forEach.call(fileRows.querySelectorAll('.frow[data-file]'), bindDrop);

    /* Files dragged in from the desktop, dropped anywhere on the page. Only
       a drag that carries files is taken: a row dragged inside the page is
       not one. */
    var depth = 0;
    var carriesFiles = function (e) {
      var kinds = e.dataTransfer && e.dataTransfer.types;
      return !!kinds && Array.prototype.indexOf.call(kinds, 'Files') !== -1;
    };
    document.addEventListener('dragenter', function (e) {
      if (!carriesFiles(e)) { return; }
      depth += 1;
      document.body.classList.add('tk-dropping');
    });
    document.addEventListener('dragleave', function (e) {
      if (!carriesFiles(e)) { return; }
      depth = Math.max(0, depth - 1);
      if (!depth) { document.body.classList.remove('tk-dropping'); }
    });
    document.addEventListener('dragover', function (e) {
      if (!carriesFiles(e)) { return; }
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    document.addEventListener('drop', function (e) {
      if (!carriesFiles(e)) { return; }
      e.preventDefault();
      depth = 0;
      document.body.classList.remove('tk-dropping');
      uploadAll(Array.prototype.slice.call(e.dataTransfer.files || []));
    });
  } else if (upBtn) {
    upBtn.hidden = true;
  }

  var editing = null;

  function renameStart() {
    if (editing) { editing.focus(); return; }
    var was = tkName.textContent;
    var field = document.createElement('input');
    field.type = 'text';
    field.className = 'oname-edit';
    field.value = was;
    field.maxLength = 200;
    field.setAttribute('aria-label', 'The new name');
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('spellcheck', 'false');
    tkName.hidden = true;
    tkName.parentNode.insertBefore(field, tkName.nextSibling);
    editing = field;
    var done = false;
    function stop(keep) {
      if (done) { return; }
      done = true;
      editing = null;
      var said = field.value.replace(/\s+/g, ' ').trim();
      if (field.parentNode) { field.parentNode.removeChild(field); }
      tkName.hidden = false;
      if (!keep || !said || said === was) { return; }
      tkName.textContent = said;
      document.title = said;
      tell(TASK, { act: 'rename', title: said }, function () {
        tkName.textContent = was;
        document.title = was;
      });
    }
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        stop(true);
      } else if (e.key === 'Escape') {
        // Stopped here, so it does not also climb Rouh's canvas a level
        // (`pages.keys_script` hands up only what nothing here took).
        e.preventDefault();
        e.stopPropagation();
        stop(false);
        tkMore.focus();
      }
    });
    field.addEventListener('blur', function () { stop(true); });
    field.focus();
    field.select();
  }

  /* The Slack channels linked to this task (`objectindex._slack_section`,
     `rouh/slack_tasks.py`): Unlink on each one's line, and a cross on each
     decision written from it, which takes that line out of the task's notes.
     Petar, 16 October 2026: "link #pricing to 19". Both are handed up to Rouh
     (`taskPageAct` in app.js), which answers with the channels as they now
     are, and the section is drawn again from that, in place. */
  var slackSet = document.getElementById('tkSlack');
  if (slackSet) {
    var slackMark = slackSet.querySelector('.oslack-mark');
    slackMark = slackMark ? slackMark.outerHTML : '';

    var slackLink = function (href, words) {
      var a = cell('a', '', words);
      a.href = href;
      a.target = '_blank';
      a.rel = 'noopener';
      return a;
    };

    var slackDraw = function (list) {
      var open = {};
      Array.prototype.forEach.call(slackSet.querySelectorAll('.oslink'), function (one) {
        var d = one.querySelector('details');
        if (d && d.open) { open[one.getAttribute('data-link')] = true; }
      });
      slackSet.textContent = '';
      (list || []).forEach(function (one) {
        var box = cell('div', 'oslink');
        box.setAttribute('data-link', String(one.id));
        var line = cell('p', 'oslink-line');
        line.innerHTML = slackMark;
        var words = cell('span', 'oslink-w', 'Decisions in ');
        words.appendChild(one.url ? slackLink(one.url, one.name) : document.createTextNode(one.name));
        words.appendChild(document.createTextNode(' go into the notes'));
        line.appendChild(words);
        var x = cell('button', 'obtn oslink-x', 'Unlink');
        x.type = 'button';
        line.appendChild(x);
        box.appendChild(line);
        var made = one.decisions || [];
        if (made.length) {
          var det = cell('details', 'osmade');
          det.open = !!open[String(one.id)];
          det.appendChild(cell('summary', '', made.length + ' decision' + (made.length === 1 ? '' : 's')
                               + ' written into the notes'));
          var ul = cell('ul', '');
          made.forEach(function (d) {
            var li = cell('li', 'osd');
            li.setAttribute('data-decision', String(d.id));
            var w = cell('span', 'osd-w');
            w.appendChild(cell('span', 'osd-day', d.day));
            w.appendChild(document.createTextNode(', ' + d.who + ': ' + d.decision + ' '));
            if (d.link) { w.appendChild(slackLink(d.link, 'In Slack')); }
            li.appendChild(w);
            var dx = cell('button', 'fdrop osd-x', '×');
            dx.type = 'button';
            dx.setAttribute('aria-label', 'Take it out of the notes');
            dx.title = 'Take it out of the notes';
            li.appendChild(dx);
            ul.appendChild(li);
          });
          det.appendChild(ul);
          box.appendChild(det);
        }
        slackSet.appendChild(box);
      });
      slackSet.hidden = !slackSet.children.length;
    };

    Array.prototype.forEach.call(slackSet.querySelectorAll('.oslink-x, .osd-x'), function (b) {
      b.hidden = false;
    });
    slackSet.addEventListener('click', function (e) {
      var x = e.target.closest ? e.target.closest('.oslink-x, .osd-x') : null;
      if (!x || x.disabled) { return; }
      var unlinking = x.classList.contains('oslink-x');
      var what = unlinking ? x.closest('.oslink').getAttribute('data-link')
        : x.closest('.osd').getAttribute('data-decision');
      x.disabled = true;
      tell(TASK, { act: unlinking ? 'slack_unlink' : 'slack_remove', slack: what }, function (m) {
        x.disabled = false;
        if (m && m.slack) { slackDraw(m.slack); }
      }, function (m) {
        slackDraw(m.slack || []);
      });
    });
  }

  /* To send from your mail (night 24, `rouh/to_send.py`, switch `to_send`): a reply this task
     drafted for the person to send from their own mail. Write it in Gmail opens Gmail's own
     window, filled in, and Rouh is told it was pressed; Not sending lets it go, with Undo. */
  var sendSet = document.getElementById('tkToSend');
  if (sendSet) {
    Array.prototype.forEach.call(sendSet.querySelectorAll('.osend'), function (row) {
      var n = Number(row.getAttribute('data-n'));
      var subject = row.getAttribute('data-subject') || '';
      var said = row.querySelector('.osend-said');
      var skip = row.querySelector('.osend-skip');
      var write = row.querySelector('.osend-write');
      function say(words) { if (said) { said.textContent = words || ''; } }
      if (write) {
        write.addEventListener('click', function () {
          tell(TASK, { act: 'to_send', n: n, do: 'opened', subject: subject }, null, null, null, true);
        });
      }
      if (!skip) { return; }
      skip.hidden = false;
      skip.addEventListener('click', function () {
        var undoing = row.classList.contains('let-go');
        skip.disabled = true;
        tell(TASK, { act: 'to_send', n: n, do: undoing ? 'undo' : 'let_go', subject: subject },
          function (m) {
            skip.disabled = false;
            say(String((m && m.error) || 'That did not go through.'));
          }, function () {
            skip.disabled = false;
            row.classList.toggle('let-go', !undoing);
            skip.textContent = undoing ? 'Not sending' : 'Undo';
            say(undoing ? '' : 'Let go: Rouh stops waiting for it.');
          });
      });
    });
  }

  /* Open on this task (night 28, `rouh/open_items.py`, switch `open_items`): each item the
     notes' Where this stands still says is open. Done marks it done in the notes, struck
     through and labelled, so every job and chat in the task knows; Undo puts it back. */
  var openSet = document.getElementById('tkOpen');
  if (openSet) {
    Array.prototype.forEach.call(openSet.querySelectorAll('.oopen'), function (row) {
      var key = row.getAttribute('data-key') || '';
      var done = row.querySelector('.oopen-done');
      var said = row.querySelector('.oopen-said');
      if (!done) { return; }
      done.hidden = false;
      done.addEventListener('click', function () {
        var undoing = row.classList.contains('closed');
        done.disabled = true;
        tell(TASK, { act: 'open_item', key: key, do: undoing ? 'undo' : 'done' },
          function (m) {
            done.disabled = false;
            if (said) { said.textContent = String((m && m.error) || 'That did not go through.'); }
          }, function () {
            done.disabled = false;
            row.classList.toggle('closed', !undoing);
            done.textContent = undoing ? 'Done' : 'Undo';
            if (said) { said.textContent = undoing ? '' : 'Marked done in the notes.'; }
          });
      });
    });
  }

  /* Time before its date (night 32, `rouh/task_time.py`, switch `task_time`): drawn only when the
     notes' Where this stands name a date something is due by, soon. Find time says how many
     working hours are still free on his main calendar before it and offers up to three two-hour
     gaps; Block it puts Google's own focus time in one, which declines new invitations then. */
  var timeSet = document.getElementById('tkTime');
  if (timeSet) {
    var timeFind = timeSet.querySelector('.otime-find');
    var timeSaid = timeSet.querySelector('.otime-said');
    if (timeFind && timeSaid) {
      timeFind.hidden = false;
      var timeLine = function (words, bad) {
        var p = document.createElement('p');
        p.className = 'otime-line' + (bad ? ' bad' : '');
        p.textContent = words;
        return p;
      };
      timeFind.addEventListener('click', function () {
        timeFind.disabled = true;
        timeFind.textContent = 'Reading your calendar\u2026';
        tell(TASK, { act: 'task_time', do: 'find' }, function (m) {
          timeFind.disabled = false;
          timeFind.textContent = 'Find time';
          var why = String((m && m.error) || 'Rouh could not be reached.');
          timeSaid.textContent = '';
          timeSaid.appendChild(timeLine(/will not change that task/.test(why)
            ? 'Rouh has to be reloaded for this: reload the page and press it again.' : why, true));
        }, function (m) {
          timeFind.disabled = false;
          timeFind.textContent = 'Find time again';
          timeSaid.textContent = '';
          var hours = Math.round(Number((m && m.hours) || 0));
          var gaps = (m && m.gaps) || [];
          timeSaid.appendChild(timeLine((hours ? hours + ' working hour' + (hours === 1 ? ' is' : 's are')
            : 'No working time is') + ' still free on your calendar before ' + String((m && m.until) || 'its date') + '.' +
            (gaps.length ? '' : ' There is no two-hour gap left before it.')));
          if (!gaps.length) { return; }
          var ul = document.createElement('ul');
          ul.className = 'otime-gaps';
          gaps.forEach(function (one) {
            var li = document.createElement('li');
            var when = document.createElement('span');
            when.className = 'otime-when';
            when.textContent = String(one.said || '');
            li.appendChild(when);
            var go = document.createElement('button');
            go.type = 'button';
            go.className = 'obtn otime-go';
            go.textContent = 'Block it';
            go.setAttribute('aria-label', 'Block ' + String(one.said || 'it') + ' as focus time');
            go.addEventListener('click', function () {
              go.disabled = true;
              go.textContent = 'Blocking\u2026';
              tell(TASK, { act: 'task_time', do: 'block', start: String(one.start || '') }, function (r) {
                go.disabled = false;
                go.textContent = 'Block it';
                li.appendChild(timeLine(String((r && r.error) || 'Rouh could not be reached.'), true));
              }, function (r) {
                go.remove();
                var done = document.createElement('span');
                done.className = 'otime-done';
                done.textContent = 'blocked';
                li.appendChild(done);
                if (r && r.link) {
                  var a = document.createElement('a');
                  a.href = r.link;
                  a.target = '_blank';
                  a.rel = 'noopener';
                  a.className = 'otime-open';
                  a.textContent = 'Open it';
                  li.appendChild(a);
                }
                li.appendChild(timeLine(String((r && r.said) || 'Blocked.')));
              }, null, true);
            });
            li.appendChild(go);
            ul.appendChild(li);
          });
          timeSaid.appendChild(ul);
        }, null, true);
      });
    }
  }

  /* The task's documents (night 20, `rouh/task_docs.py`): every Google document its notes
     link to, each with What changed, which Rouh reads from Drive's saved versions since the
     last time this page was open (`doc_changes` in cards.js) and which is shown right under
     its line, in place. A second press folds it away; a third reads it again. */
  var docSet = document.getElementById('tkDocs');
  if (docSet) {
    Array.prototype.forEach.call(docSet.querySelectorAll('.odoc-what, .odoc-onpage, .odoc-rehearse, .odoc-attach'), function (b) {
      b.hidden = false;
    });
    // Add a document (night 23, `rouh/task_docs.py`, switch `doc_add`): a Google Doc, Sheet
    // or Slides link pasted here is kept in the task's notes, and its line is put in the list
    // in place, where every other document of the task is.
    var addForm = docSet.querySelector('.odoc-add');
    if (addForm) {
      addForm.hidden = false;
      var addLink = addForm.querySelector('.odoc-add-link');
      var addGo = addForm.querySelector('.odoc-add-go');
      var addSaid = addForm.querySelector('.odoc-add-said');
      var addSay = function (words, bad) {
        addSaid.textContent = words || '';
        addSaid.hidden = !words;
        addSaid.classList.toggle('bad', !!bad);
      };
      var addIt = function () {
        var pasted = String(addLink.value || '').trim();
        if (!pasted) { addLink.focus(); return; }
        addGo.disabled = true;
        addGo.textContent = 'Adding…';
        addSay('');
        tell(TASK, { act: 'doc_add', link: pasted }, function (m) {
          addGo.disabled = false;
          addGo.textContent = 'Add';
          var why = String((m && m.error) || 'Rouh could not be reached.');
          addSay(/will not change that task/.test(why)
            ? 'Rouh has to be reloaded to add one here: reload the page and try again.' : why, true);
        }, function (m) {
          addGo.disabled = false;
          addGo.textContent = 'Add';
          addLink.value = '';
          var doc = (m && m.doc) || {};
          var row = document.createElement('div');
          row.className = 'odoc';
          row.setAttribute('data-doc', String(doc.id || ''));
          var line = document.createElement('p');
          line.className = 'odoc-line';
          var a = document.createElement('a');
          a.className = 'odoc-name';
          a.href = String(doc.url || '#');
          a.target = '_blank';
          a.rel = 'noopener';
          a.textContent = String(doc.title || doc.kind || 'Google Doc');
          var kind = document.createElement('span');
          kind.className = 'odoc-kind';
          kind.textContent = String(doc.kind || '');
          var what = document.createElement('button');
          what.type = 'button';
          what.className = 'obtn odoc-what';
          what.textContent = 'What changed';
          line.appendChild(a);
          line.appendChild(kind);
          line.appendChild(what);
          var said = document.createElement('div');
          said.className = 'odoc-said';
          said.hidden = true;
          row.appendChild(line);
          row.appendChild(said);
          docSet.querySelector('.rows').insertBefore(row, docSet.querySelector('.rows').firstChild);
          var count = docSet.querySelector('h2 .c');
          var n = docSet.querySelectorAll('.odoc').length;
          if (count) { count.textContent = String(n); }
          else {
            count = document.createElement('span');
            count.className = 'c';
            count.textContent = String(n);
            docSet.querySelector('h2').appendChild(count);
          }
          addSay(m && m.readable ? 'Kept in the task’s notes.'
            : 'Kept in the task’s notes. Rouh’s Google account cannot open it yet: share it with Rouh to read it here.');
        }, null, true);
      };
      addGo.addEventListener('click', addIt);
      addLink.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); addIt(); }
      });
    }
    // A document drawn with the notes' words for it is named as Drive names it, once Rouh
    // has asked Drive; the page drawn next time has the name already.
    if (docSet.querySelector('.odoc[data-unnamed]')) {
      tell(TASK, { act: 'doc_names' }, null, function (m) {
        var names = (m && m.names) || {};
        Array.prototype.forEach.call(docSet.querySelectorAll('.odoc[data-unnamed]'), function (row) {
          var name = names[row.getAttribute('data-doc') || ''];
          var a = row.querySelector('.odoc-name');
          if (name && a) { a.textContent = name; row.removeAttribute('data-unnamed'); }
        });
      }, null, true);
    }
    // On the page? (night 21, `rouh/doc_on_page.py`): which of a Google Doc's paragraphs are on
    // this task's pages word for word, said under its line, in place, as What changed is.
    docSet.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.odoc-onpage') : null;
      if (!b || b.disabled) { return; }
      var row = b.closest('.odoc');
      var out = row && row.querySelector('.odoc-said');
      if (!row || !out) { return; }
      if (!out.hidden && out.textContent && out.getAttribute('data-by') === 'onpage') {
        out.hidden = true;
        out.textContent = '';
        b.textContent = 'On the page?';
        return;
      }
      b.disabled = true;
      b.textContent = 'Comparing…';
      tell(TASK, { act: 'doc_on_page', doc: row.getAttribute('data-doc') || '' }, function (m) {
        b.disabled = false;
        b.textContent = 'On the page?';
        var why = String((m && m.error) || 'Rouh could not be reached.');
        out.textContent = /will not change that task/.test(why)
          ? 'Rouh has to be reloaded to read this here: reload the page and press it again.' : why;
        out.hidden = false;
      }, function (m) {
        b.disabled = false;
        b.textContent = 'Fold it away';
        var what = row.querySelector('.odoc-what');
        if (what) { what.textContent = 'What changed'; }
        out.setAttribute('data-by', 'onpage');
        out.textContent = String((m && m.text) || '');
        out.hidden = false;
      }, null, true);
    });
    docSet.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.odoc-what') : null;
      if (!b || b.disabled) { return; }
      var row = b.closest('.odoc');
      var out = row && row.querySelector('.odoc-said');
      if (!row || !out) { return; }
      if (!out.hidden && out.textContent && out.getAttribute('data-by') !== 'onpage') {
        out.hidden = true;
        out.textContent = '';
        b.textContent = 'What changed';
        return;
      }
      b.disabled = true;
      b.textContent = 'Reading…';
      tell(TASK, { act: 'doc_changes', doc: row.getAttribute('data-doc') || '' }, function (m) {
        b.disabled = false;
        b.textContent = 'What changed';
        // Said under its line, where it was pressed. Rouh's screen loaded before this
        // section existed does not know the press yet, and says so in general words.
        var why = String((m && m.error) || 'Rouh could not be reached.');
        out.textContent = /will not change that task/.test(why)
          ? 'Rouh has to be reloaded to read this here: reload the page and press it again.' : why;
        out.hidden = false;
      }, function (m) {
        b.disabled = false;
        b.textContent = 'Fold it away';
        var onpage = row.querySelector('.odoc-onpage');
        if (onpage) { onpage.textContent = 'On the page?'; }
        out.removeAttribute('data-by');
        out.textContent = String((m && m.text) || '');
        out.hidden = false;
      }, null, true);
    });
    // Comments on the task's documents (night 26, `rouh/task_comments.py`): a document with
    // open comments gets a button with how many, and only then. Pressing it reads them again
    // and shows them under its line, each with a link to it, and Have a job apply them; a
    // second press folds them away.
    var cmtSay = function (list, words, bad) {
      var said = list.querySelector('.odoc-cmts-said');
      said.textContent = words || '';
      said.hidden = !words;
      said.classList.toggle('bad', !!bad);
    };
    var cmtDraw = function (row, list, comments) {
      var ol = list.querySelector('ol');
      ol.textContent = '';
      comments.forEach(function (c) {
        var li = document.createElement('li');
        li.className = 'odoc-cmt';
        var head = document.createElement('p');
        head.className = 'odoc-cmt-head';
        var who = document.createElement('b');
        who.textContent = String(c.who || 'Somebody');
        head.appendChild(who);
        head.appendChild(document.createTextNode(' \u00b7 ' + String(c.day || '')));
        if (c.answers) {
          head.appendChild(document.createTextNode(' \u00b7 ' + (c.answers === 1 ? '1 answer' : c.answers + ' answers')));
        }
        li.appendChild(head);
        if (c.on) {
          var on = document.createElement('p');
          on.className = 'odoc-cmt-on';
          on.textContent = '\u201c' + String(c.on) + '\u201d';
          li.appendChild(on);
        }
        var words = document.createElement('p');
        words.className = 'odoc-cmt-words';
        words.textContent = String(c.words || '');
        li.appendChild(words);
        var open = document.createElement('a');
        open.className = 'odoc-cmt-open';
        open.href = String(c.link || '#');
        open.target = '_blank';
        open.rel = 'noopener';
        open.textContent = 'Open in the document';
        li.appendChild(open);
        ol.appendChild(li);
      });
      var b = row.querySelector('.odoc-cmts');
      var n = comments.length;
      if (b) { b.setAttribute('data-n', String(n)); }
      list.querySelector('.odoc-cmts-apply').hidden = !n;
      if (!n) { cmtSay(list, 'No comment on it is open now.'); }
    };
    tell(TASK, { act: 'doc_comments' }, null, function (m) {
      var docs = (m && m.docs) || {};
      Array.prototype.forEach.call(docSet.querySelectorAll('.odoc'), function (row) {
        var mine = docs[row.getAttribute('data-doc') || ''] || [];
        if (!mine.length || row.querySelector('.odoc-cmts')) { return; }
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'obtn odoc-cmts';
        b.setAttribute('aria-expanded', 'false');
        b.setAttribute('data-n', String(mine.length));
        b.textContent = mine.length === 1 ? '1 open comment' : mine.length + ' open comments';
        var line = row.querySelector('.odoc-line');
        var what = line.querySelector('.odoc-what');
        line.insertBefore(b, what ? what.nextSibling : null);
        var list = document.createElement('div');
        list.className = 'odoc-cmts-list';
        list.hidden = true;
        list.appendChild(document.createElement('ol'));
        var go = document.createElement('button');
        go.type = 'button';
        go.className = 'obtn odoc-cmts-apply';
        go.textContent = 'Have a job apply them';
        list.appendChild(go);
        var said = document.createElement('p');
        said.className = 'odoc-cmts-said';
        said.setAttribute('role', 'status');
        said.hidden = true;
        list.appendChild(said);
        row.appendChild(list);
      });
    }, null, true);
    docSet.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.odoc-cmts') : null;
      if (!b || b.disabled) { return; }
      var row = b.closest('.odoc');
      var list = row && row.querySelector('.odoc-cmts-list');
      if (!list) { return; }
      var label = function () {
        var n = Number(b.getAttribute('data-n') || 0);
        return n === 1 ? '1 open comment' : n + ' open comments';
      };
      if (!list.hidden) {
        list.hidden = true;
        b.setAttribute('aria-expanded', 'false');
        b.textContent = label();
        return;
      }
      b.disabled = true;
      b.textContent = 'Reading\u2026';
      tell(TASK, { act: 'doc_comments', doc: row.getAttribute('data-doc') || '' }, function (m) {
        b.disabled = false;
        b.textContent = label();
        var why = String((m && m.error) || 'Rouh could not be reached.');
        list.hidden = false;
        list.querySelector('.odoc-cmts-apply').hidden = true;
        cmtSay(list, /will not change that task/.test(why)
          ? 'Rouh has to be reloaded to read this here: reload the page and press it again.' : why, true);
      }, function (m) {
        b.disabled = false;
        cmtSay(list, '');
        cmtDraw(row, list, ((m && m.docs) || {})[row.getAttribute('data-doc') || ''] || []);
        list.hidden = false;
        b.setAttribute('aria-expanded', 'true');
        b.textContent = 'Fold them away';
      }, null, true);
    });
    docSet.addEventListener('click', function (e) {
      var go = e.target.closest ? e.target.closest('.odoc-cmts-apply') : null;
      if (!go || go.disabled) { return; }
      var row = go.closest('.odoc');
      var list = row && row.querySelector('.odoc-cmts-list');
      if (!list) { return; }
      go.disabled = true;
      go.textContent = 'Starting\u2026';
      tell(TASK, { act: 'doc_comments_apply', doc: row.getAttribute('data-doc') || '' }, function (m) {
        go.disabled = false;
        go.textContent = 'Have a job apply them';
        cmtSay(list, String((m && m.error) || 'Rouh could not be reached.'), true);
      }, function (m) {
        go.textContent = 'A job is applying them';
        cmtSay(list, String((m && m.said) || 'A job is applying them.'));
      }, null, true);
    });
    // Attach to a meeting (night 31, `rouh/meeting_attach.py`): the meetings he organises about this
    // task or document, under its line, each with Attach, which puts the document on the meeting's
    // invitation. A second press on the button folds the list away.
    docSet.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.odoc-attach') : null;
      if (!b || b.disabled) { return; }
      var row = b.closest('.odoc');
      var out = row && row.querySelector('.odoc-said');
      var doc = row && row.getAttribute('data-doc');
      if (!row || !out || !doc) { return; }
      if (!out.hidden && out.getAttribute('data-by') === 'attach') {
        out.hidden = true;
        out.textContent = '';
        out.removeAttribute('data-by');
        b.textContent = 'Attach to a meeting';
        return;
      }
      b.disabled = true;
      b.textContent = 'Finding meetings\u2026';
      var said = function (words, bad) {
        out.textContent = '';
        var p = document.createElement('p');
        p.className = 'odoc-attach-said' + (bad ? ' bad' : '');
        p.setAttribute('role', 'status');
        p.textContent = words;
        out.appendChild(p);
        out.setAttribute('data-by', 'attach');
        out.hidden = false;
      };
      tell(TASK, { act: 'doc_attach', doc: doc }, function (m) {
        b.disabled = false;
        b.textContent = 'Attach to a meeting';
        var why = String((m && m.error) || 'Rouh could not be reached.');
        said(/will not change that task/.test(why)
          ? 'Rouh has to be reloaded to attach it here: reload the page and press it again.' : why, true);
      }, function (m) {
        b.disabled = false;
        b.textContent = 'Fold it away';
        var what = row.querySelector('.odoc-what');
        if (what) { what.textContent = 'What changed'; }
        var list = (m && m.meetings) || [];
        out.textContent = '';
        out.setAttribute('data-by', 'attach');
        out.hidden = false;
        if (!list.length) {
          said('No meeting you organise in the next two weeks has a title that shares a word with this task or document.');
          return;
        }
        var head = document.createElement('p');
        head.className = 'odoc-attach-head';
        head.textContent = 'Put ' + String(m.doc || 'it') + ' on the invitation of:';
        out.appendChild(head);
        var ul = document.createElement('ul');
        ul.className = 'odoc-attach-list';
        list.forEach(function (one) {
          var li = document.createElement('li');
          var name = document.createElement('span');
          name.className = 'odoc-attach-name';
          name.textContent = String(one.title || 'a meeting');
          var when = document.createElement('span');
          when.className = 'odoc-attach-when';
          when.textContent = String(one.when || '');
          li.appendChild(name);
          li.appendChild(when);
          if (one.attached) {
            var had = document.createElement('span');
            had.className = 'odoc-attach-had';
            had.textContent = 'attached already';
            li.appendChild(had);
          } else {
            var go = document.createElement('button');
            go.type = 'button';
            go.className = 'obtn odoc-attach-go';
            go.textContent = 'Attach';
            go.setAttribute('aria-label', 'Attach to ' + String(one.title || 'the meeting') + ', ' + String(one.when || ''));
            go.addEventListener('click', function () {
              go.disabled = true;
              go.textContent = 'Attaching\u2026';
              tell(TASK, { act: 'doc_attach', doc: doc, key: String(one.key || '') }, function (r) {
                go.disabled = false;
                go.textContent = 'Attach';
                var note = li.querySelector('.odoc-attach-note') || document.createElement('span');
                note.className = 'odoc-attach-note bad';
                note.textContent = String((r && r.error) || 'Rouh could not be reached.');
                li.appendChild(note);
              }, function (r) {
                go.remove();
                var done = document.createElement('span');
                done.className = 'odoc-attach-had';
                done.textContent = 'attached';
                li.appendChild(done);
                var note = document.createElement('p');
                note.className = 'odoc-attach-said';
                note.setAttribute('role', 'status');
                note.textContent = String((r && r.said) || 'Attached.');
                out.appendChild(note);
              }, null, true);
            });
            li.appendChild(go);
          }
          ul.appendChild(li);
        });
        out.appendChild(ul);
      }, null, true);
    });
    // Rehearse (night 27, `rouh/rehearse.py`): only on a Google Slides deck. The deck read slide
    // by slide, over the page: the slide's picture, its speaker notes large, Previous and Next,
    // a clock from the first slide, and at the end the time it took and the pace of the whole.
    docSet.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.odoc-rehearse') : null;
      if (!b || b.disabled) { return; }
      var row = b.closest('.odoc');
      var doc = row && row.getAttribute('data-doc');
      if (!doc) { return; }
      b.disabled = true;
      b.textContent = 'Reading\u2026';
      tell(TASK, { act: 'deck_rehearse', doc: doc }, function (m) {
        b.disabled = false;
        b.textContent = 'Rehearse';
        var why = String((m && m.error) || 'Rouh could not be reached.');
        toast(/will not change that task/.test(why)
          ? 'Rouh has to be reloaded to rehearse here: reload the page and press it again.' : why);
      }, function (m) {
        b.disabled = false;
        b.textContent = 'Rehearse';
        if (m && m.deck) { rehearse(m.deck, b); }
      }, null, true);
    });
  }

  function rehearse(deck, opener) {
    var slides = deck.slides || [];
    var at = 0;
    var spent = slides.map(function () { return 0; });
    var seen = {};
    var started = 0;
    var since = 0;
    var tick = null;
    var pictures = {};
    var ended = false;
    var wrap = document.createElement('div');
    wrap.className = 'rh';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', 'Rehearse ' + String(deck.title || 'the deck'));
    var bar = document.createElement('div');
    bar.className = 'rh-bar';
    var name = document.createElement('p');
    name.className = 'rh-name';
    name.textContent = String(deck.title || 'Deck');
    var where = document.createElement('p');
    where.className = 'rh-where';
    var clockEl = document.createElement('p');
    clockEl.className = 'rh-clock';
    clockEl.setAttribute('aria-label', 'Time so far');
    var stop = document.createElement('button');
    stop.type = 'button';
    stop.className = 'obtn rh-stop';
    stop.textContent = 'Finish';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'rh-close';
    close.setAttribute('aria-label', 'Close');
    close.textContent = '\u00d7';
    bar.appendChild(name);
    bar.appendChild(where);
    bar.appendChild(clockEl);
    bar.appendChild(stop);
    bar.appendChild(close);
    var body = document.createElement('div');
    body.className = 'rh-body';
    var pic = document.createElement('div');
    pic.className = 'rh-pic';
    var notes = document.createElement('div');
    notes.className = 'rh-notes';
    body.appendChild(pic);
    body.appendChild(notes);
    var foot = document.createElement('div');
    foot.className = 'rh-foot';
    var prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'obtn rh-prev';
    prev.textContent = 'Previous';
    var next = document.createElement('button');
    next.type = 'button';
    next.className = 'obtn rh-next';
    var open = document.createElement('a');
    open.className = 'rh-open';
    open.target = '_blank';
    open.rel = 'noopener';
    open.textContent = 'Open in Google Slides';
    foot.appendChild(prev);
    foot.appendChild(open);
    foot.appendChild(next);
    wrap.appendChild(bar);
    wrap.appendChild(body);
    wrap.appendChild(foot);
    document.body.appendChild(wrap);
    document.documentElement.classList.add('rh-on');

    function mmss(sec) {
      sec = Math.max(0, Math.round(sec));
      var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
      return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }
    function minutes(sec) {
      var m = Math.round(sec / 60);
      return m < 1 ? 'under a minute' : m === 1 ? '1 minute' : m + ' minutes';
    }
    function now() { return Date.now() / 1000; }
    function count() {
      if (since) { spent[at] += now() - since; since = now(); }
    }
    function total() { return spent.reduce(function (a, b) { return a + b; }, 0); }
    function showClock() { clockEl.textContent = mmss(total() + (since ? now() - since : 0)); }
    function picture(i) {
      var s = slides[i];
      if (!s || pictures[s.id] !== undefined || !s.id) { return; }
      pictures[s.id] = '';
      tell(TASK, { act: 'deck_picture', doc: deck.id, slide: s.id }, function () {}, function (m) {
        pictures[s.id] = String((m && m.url) || '');
        if (!ended && slides[at] && slides[at].id === s.id) { draw(); }
      }, null, true);
    }
    function draw() {
      var s = slides[at];
      where.textContent = 'Slide ' + s.n + ' of ' + slides.length;
      pic.textContent = '';
      var url = pictures[s.id];
      if (url) {
        var img = document.createElement('img');
        img.src = url;
        img.alt = 'Slide ' + s.n + (s.title ? ': ' + s.title : '');
        pic.appendChild(img);
      } else {
        var card = document.createElement('div');
        card.className = 'rh-card';
        var t = document.createElement('p');
        t.className = 'rh-card-title';
        t.textContent = String(s.title || 'Slide ' + s.n);
        card.appendChild(t);
        if (s.text && s.text !== s.title) {
          var w = document.createElement('p');
          w.className = 'rh-card-text';
          w.textContent = String(s.text);
          card.appendChild(w);
        }
        pic.appendChild(card);
      }
      notes.textContent = '';
      if (s.notes) {
        String(s.notes).split(/\n+/).forEach(function (para) {
          if (!para.trim()) { return; }
          var p = document.createElement('p');
          p.textContent = para;
          notes.appendChild(p);
        });
      } else {
        var none = document.createElement('p');
        none.className = 'rh-none';
        none.textContent = 'No speaker notes on this slide.';
        notes.appendChild(none);
      }
      notes.scrollTop = 0;
      prev.disabled = at === 0;
      next.textContent = at === slides.length - 1 ? 'Finish' : 'Next';
      open.href = String(s.link || deck.link || '#');
      picture(at);
      picture(at + 1);
    }
    function go(i) {
      if (ended || i < 0 || i >= slides.length) { return; }
      count();
      at = i;
      seen[at] = true;
      draw();
    }
    function finish() {
      if (ended) { return; }
      count();
      since = 0;
      ended = true;
      if (tick) { clearInterval(tick); tick = null; }
      var took = total();
      var n = Object.keys(seen).length;
      body.textContent = '';
      foot.hidden = true;
      stop.hidden = true;
      where.textContent = 'Done';
      showClock();
      var end = document.createElement('div');
      end.className = 'rh-end';
      var h = document.createElement('p');
      h.className = 'rh-end-head';
      h.textContent = (n === slides.length ? 'All ' + n + ' slides' : n + ' of ' + slides.length + ' slides') +
        ' in ' + minutes(took) + '.';
      end.appendChild(h);
      if (n) {
        var avg = document.createElement('p');
        avg.textContent = 'About ' + mmss(took / n) + ' a slide.' + (n < slides.length
          ? ' At that pace the whole deck takes about ' + minutes(took / n * slides.length) + '.' : '');
        end.appendChild(avg);
      }
      var longest = spent.map(function (sec, i) { return { i: i, sec: sec }; })
        .filter(function (x) { return x.sec >= 1; })
        .sort(function (a, b) { return b.sec - a.sec; }).slice(0, 3);
      if (longest.length > 1) {
        var lh = document.createElement('p');
        lh.className = 'rh-end-sub';
        lh.textContent = 'Longest:';
        end.appendChild(lh);
        var ol = document.createElement('ol');
        ol.className = 'rh-end-list';
        longest.forEach(function (x) {
          var li = document.createElement('li');
          var a = document.createElement('a');
          a.href = String(slides[x.i].link || '#');
          a.target = '_blank';
          a.rel = 'noopener';
          a.textContent = 'Slide ' + slides[x.i].n + (slides[x.i].title ? ', ' + slides[x.i].title : '');
          li.appendChild(a);
          li.appendChild(document.createTextNode(' \u00b7 ' + mmss(x.sec)));
          ol.appendChild(li);
        });
        end.appendChild(ol);
      }
      var again = document.createElement('button');
      again.type = 'button';
      again.className = 'obtn rh-again';
      again.textContent = 'Close';
      again.addEventListener('click', shut);
      end.appendChild(again);
      body.appendChild(end);
      again.focus();
      tell(TASK, { act: 'deck_rehearsed', doc: deck.id, seconds: took, seen: n, count: slides.length },
           function () {}, function () {}, null, true);
    }
    function shut() {
      if (tick) { clearInterval(tick); tick = null; }
      document.removeEventListener('keydown', keys);
      document.documentElement.classList.remove('rh-on');
      wrap.remove();
      if (opener) { opener.focus(); }
    }
    function keys(e) {
      if (e.key === 'Escape') { e.preventDefault(); shut(); return; }
      if (ended) { return; }
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || (e.key === ' ' && e.target === document.body)) {
        e.preventDefault();
        if (at === slides.length - 1) { finish(); } else { go(at + 1); }
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault();
        go(at - 1);
      }
    }
    prev.addEventListener('click', function () { go(at - 1); });
    next.addEventListener('click', function () {
      if (at === slides.length - 1) { finish(); } else { go(at + 1); }
    });
    stop.addEventListener('click', finish);
    close.addEventListener('click', shut);
    document.addEventListener('keydown', keys);
    started = now();
    since = started;
    seen[0] = true;
    tick = setInterval(showClock, 1000);
    draw();
    showClock();
    next.focus();
  }

  /* The question box. What goes up is written for Rouh to read as much as
     for the person, since it is what arrives in the conversation: which
     task, what it asked, and the answer. `brain.WAITING` is what reads it. */
  var box = document.getElementById('owait');
  var form = document.getElementById('owaitForm');
  var gone = document.getElementById('owaitGone');
  if (box && form) { answerBox(box, form); }
  if (box && gone) { dismissible(box, gone); }

  /* Dismiss, at the right of the open box's foot: "i also need the option to
     dismiss it". The box folds to the one line drawn for it at once, and
     Rouh writes it down (`taskDismiss` in app.js), so it stays folded and
     the lists stop marking the task as waiting on them. Nothing is sent to
     anybody. The line has the way back: the box, as it was, to answer after
     all. A refusal from Rouh unfolds it again. */
  function dismissible(box, gone) {
    var x = document.getElementById('owaitX');
    var back = document.getElementById('owaitBack');
    var asking = box.getAttribute('data-asked') || '';
    // The Waiting beside the task's name, which a dismissed question takes
    // off, as the page drawn again would.
    var pill = document.querySelector('h1 .task-status[data-status="waiting"]');
    // Back, and open: the line was pressed to see the question again, not
    // its folded card.
    function unfold() {
      gone.hidden = true;
      box.hidden = false;
      box.open = true;
    }
    if (back) {
      back.hidden = false;
      back.addEventListener('click', function () {
        unfold();
        var first = box.querySelector('.owait-opt:not([disabled])') || document.getElementById('owaitText') || x;
        if (first && !first.hidden) { first.focus(); }
      });
    }
    if (!x) { return; }
    x.hidden = false;
    x.addEventListener('click', function () {
      box.hidden = true;
      gone.hidden = false;
      if (pill) { pill.hidden = true; }
      if (back) { back.focus(); }
      tell(DISMISS, { asked: asking }, function () {
        unfold();
        if (pill) { pill.hidden = false; }
        x.focus();
      });
    });
  }

  function answerBox(box, form) {
    var number = box.getAttribute('data-number') || '';
    var asking = box.getAttribute('data-asked') || '';
    var done = box.getAttribute('data-state') === 'done';
    // Where it goes: the chat the task already has, by name when it has one,
    // or a new one when the task has no chat yet (`_waiting_panel`).
    var titled = box.getAttribute('data-chat') || '';
    var where = box.getAttribute('data-into') === 'new' ? 'a new chat about this task,'
      : titled ? 'the task\u2019s chat, \u201c' + titled + '\u201d,' : 'the task\u2019s chat,';
    var several = form.hasAttribute('data-several');
    var text = document.getElementById('owaitText');
    var arrow = document.getElementById('owaitSend');
    var picked = document.getElementById('owaitPicked');
    var again = document.getElementById('owaitAgain');
    var options = [].slice.call(form.querySelectorAll('.owait-opt'));
    var which = number ? 'Task ' + number : 'This task';
    var head = document.getElementById('owaitHead');
    var pill = box.querySelector('.owait-pill');
    var was = { head: head ? head.textContent : '', pill: pill ? pill.textContent : '' };
    var sent = null;

    // Answered already, the form is behind Answer again; otherwise it is
    // the box.
    if (form.hasAttribute('data-again') && again) {
      again.hidden = false;
      again.addEventListener('click', function () {
        form.hidden = false;
        again.hidden = true;
        var first = form.querySelector('.owait-opt') || text;
        if (first) { first.focus(); }
      });
    } else {
      form.hidden = false;
    }

    function said(answer) {
      if (!asking) {
        return which + ' is marked as waiting on me, and its notes do not say what for.'
          + '\nMy answer: ' + answer;
      }
      return which + (done ? ' is done, and it asked me this: ' : ' is waiting on me for this: ')
        + asking + '\nMy answer: ' + answer;
    }

    // Said at once, where it was pressed: the box says it went, and where,
    // before anything has come back. Rouh loads the page again once it has
    // answered, and the page then says which job has it.
    // Sent, the box is waiting to be drawn again with the answer in it, and
    // is not dismissed in between: the line it would fold to is the
    // question's, which has just been answered.
    var dismiss = document.getElementById('owaitX');

    function showSent(answer, words) {
      box.classList.add('is-sent');
      if (dismiss) { dismiss.hidden = true; }
      if (head) { head.textContent = answer ? 'Answered' : 'Asked'; }
      if (pill) { pill.textContent = 'Sent'; }
      sent = document.createElement('div');
      sent.className = 'owait-sent';
      sent.setAttribute('role', 'status');
      var now = document.createElement('p');
      now.className = 'owait-now';
      var lead = document.createElement('strong');
      lead.textContent = answer ? 'Sent to Rouh.' : 'Asked.';
      now.appendChild(lead);
      now.appendChild(document.createTextNode(answer
        ? ' Your answer is in ' + where + ' where Rouh hands it to a job to '
          + 'carry the task on. This box shows that job once it has started.'
        : ' Rouh is reading the task, in ' + where + ' and says there what it is '
          + 'waiting on you for.'));
      sent.appendChild(now);
      if (answer) {
        var mine = document.createElement('blockquote');
        mine.className = 'owait-mine';
        var k = document.createElement('span');
        k.className = 'owait-wk';
        k.textContent = 'You answered, just now';
        mine.appendChild(k);
        mine.appendChild(document.createTextNode(words));
        sent.appendChild(mine);
      }
      box.insertBefore(sent, box.querySelector('.owait-now') || form);
    }

    // Rouh said no, or could not be reached: the box as it was, with what
    // was typed still in it.
    function putBack() {
      box.classList.remove('is-sent');
      if (dismiss) { dismiss.hidden = false; }
      if (head) { head.textContent = was.head; }
      if (pill) { pill.textContent = was.pill; }
      if (sent && sent.parentNode) { sent.parentNode.removeChild(sent); }
      sent = null;
      busy(false);
    }

    function busy(on) {
      options.forEach(function (b) { b.disabled = on; });
      if (picked) { picked.disabled = on || !chosen().length; }
      if (text) { text.disabled = on; }
      if (arrow) { arrow.disabled = on; }
    }

    function send(answer) {
      answer = String(answer || '').trim().slice(0, 4000);
      if (!answer || box.classList.contains('is-sent')) { return; }
      busy(true);
      showSent(true, answer);
      startChat({ say: said(answer), answers: { asked: asking, answer: answer } }, putBack);
    }

    function chosen() {
      return options.filter(function (b) { return b.getAttribute('aria-pressed') === 'true'; })
        .map(function (b) { return b.getAttribute('data-answer') || ''; });
    }

    // "Walk it as each buyer and Decide only what is open".
    function together(labels) {
      if (labels.length < 2) { return labels.join(''); }
      return labels.slice(0, -1).join(', ') + ' and ' + labels[labels.length - 1];
    }

    function paintPicked() {
      if (!picked) { return; }
      var n = chosen().length;
      picked.disabled = !n;
      picked.textContent = n ? 'Send the ' + (n === 1 ? 'one' : n) + ' picked'
        : 'Pick one or more';
    }

    options.forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.hasAttribute('data-find')) {
          if (box.classList.contains('is-sent')) { return; }
          busy(true);
          showSent(false, '');
          startChat({ say: which + ' is marked as waiting on me, and its notes do not say '
            + 'what for. What does it need from me?' }, putBack);
          return;
        }
        if (several) {
          b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
          paintPicked();
          return;
        }
        send(b.getAttribute('data-answer'));
      });
    });

    if (picked) {
      picked.addEventListener('click', function () {
        var labels = chosen();
        if (!labels.length) { return; }
        var mine = text ? text.value.trim() : '';
        send(together(labels) + (mine ? '. ' + mine : ''));
      });
    }

    // A line at a time as the words wrap, with no scrollbar, up to fifteen
    // lines, and only then a scrollbar, in the box's own colours: the chat
    // standard (`workspace/.claude/skills/bb-chat-interface`), which this box
    // broke at 180 pixels with the browser's grey bar. Petar, 24 September
    // 2026 (fr_224c13b2160c): "that should expand vertically without scroll
    // up to a certain limit of lines then appear scroll". Fewer than fifteen
    // where half the frame will not hold them. The same as `fitLines` in
    // projectpage.js, and `growToLines` in Rouh's own app.js.
    function fitLines(box) {
      var cs = getComputedStyle(box);
      var line = parseFloat(cs.lineHeight) || 22;
      var pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
      var room = Math.floor((window.innerHeight / 2 - pad) / line);
      var most = Math.max(1, Math.min(15, room)) * line + pad;
      box.style.height = 'auto';
      var want = box.scrollHeight;
      box.style.height = Math.min(want, most) + 'px';
      box.classList.toggle('scrolls', want > most + 1);
    }

    function grow() {
      if (text && text.offsetParent !== null) { fitLines(text); }
    }

    // Their own words. Not a form: the page is sandboxed without forms, so a
    // submit never fires, and Enter and the arrow send it themselves.
    function sendOwn() {
      var mine = text.value.trim();
      if (!mine) { text.focus(); return; }
      var labels = several ? chosen() : [];
      send(labels.length ? together(labels) + '. ' + mine : mine);
    }

    if (text) {
      text.addEventListener('input', grow);
      // A wider or narrower page wraps the same words onto more or fewer lines.
      window.addEventListener('resize', grow);
      // Enter is a new line and Ctrl+Enter, or Cmd+Enter on a Mac, sends, as
      // in Rouh's own box (`isSendKey` in app.js, and why). The empty box says
      // so where there is a keyboard to press it on.
      text.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey
            && !e.isComposing) {
          e.preventDefault();
          sendOwn();
        }
      });
      if (window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
        var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
        text.placeholder += ' (' + (mac ? '\u2318\u21a9' : 'Ctrl+Enter') + ' to send)';
      }
      if (arrow) { arrow.addEventListener('click', sendOwn); }
    }
  }
}());
