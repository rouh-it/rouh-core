# Rouh

A personal voice assistant that runs on one server. You open a web page, press
once, and talk. It hears you, answers out loud, and puts anything worth reading
on a screen beside it.

Each installation lives at its own address (`ROUH_PUBLIC_URL`, SETUP.md), behind a
sign-in: a username and a password, on an account of your own.

## What it does

- **Talks**, in the languages the installation names (`ROUH_STT_LANGUAGE`,
  `ROUH_STT_SECONDARY`). Speech in over a websocket while you are
  still speaking; speech out sentence by sentence while the model is still
  writing the next one.
- **Takes a typed message of any length.** Enter starts a new line, and Ctrl+Enter (Cmd+Enter on a Mac) or the arrow sends it.
  On a phone the return key is a new line and the arrow sends.
  The box grows with the lines, up to fifteen, and then scrolls.
  Every box a message is written in has the same keys: editing a message, Ask AI, a task's question, a project's first message and a comment on a page.
  Petar, 26 September 2026 (fr_06ec274f0b97): "Can you make the keyboard button make a new line instead of submitting the chat message?"
- **Stops when you tell it to.** A **Stop** button sits beside Send while an
  answer is being worked out or said, and Escape does the same from the
  keyboard, including with the cursor still in the text box.
  Rouh is an agentic loop rather than one call, so a turn can be several model
  calls and several tool calls deep by then: the press ends all of it at the
  next point the loop can be left cleanly, and the audio already queued in the
  browser is thrown away in the same press rather than a second later.
  It stops Rouh and nothing else.
  A background worker, a job you handed to your assistant and a run of the one
  program all carry on, and a tool call already in flight is left to finish with
  its answer thrown away, because some of those have already started work
  somewhere else.
  The conversation keeps a line saying the turn was stopped, so the next thing
  you say is answered knowing the last one was cut short.
- **Shows.** Anything that is a table, a number, a chart, code, a picture or a
  link goes on the screen instead of being read aloud, and anything none of
  those is a shape for is written as markup at the time and drawn in a frame of
  its own. The screen is a black canvas the cards float on, it is kept on disk,
  and it is still there after a restart: the page reads back the newest ten when
  it opens and the rest as you scroll.
  Where a card is read is decided by the screen and by nothing else.
  At a desk every card goes out on the canvas by itself as it is drawn, and the
  conversation keeps a line in its place with the card's number and title, so it
  still reads in order.
  The canvas holds one card, the newest; the one it held folds to its line, and
  pressing a line puts that card back on the canvas.
  A page loaded on the canvas - a task, a run - is never covered by a card: one
  drawn while it is up is read in the conversation, and goes out when the page
  is closed.
  On a phone there is no second column to put it in, so every card stays in the
  chat, and a card of markup is read as what it is - an ordinary page, scrolling
  sideways inside its own frame when it is wider than the glass.
  One press overrules that for one card: "Bring it back here" keeps it in the
  conversation until it is opened on the canvas again.
  Asked for one of them to be different, it changes that card in place rather
  than drawing a second one, and every version it has had is kept: the card
  wears **v2 of 2** and "what did it say before" brings the older one back.
- **Fits a phone.** On a wide screen there are three columns: the sidebar on
  the left, the conversation in the middle, the canvas on the right.
  Below 900 pixels the two panes do not fit beside each other, so exactly one of
  them is on screen at a time, filling the glass, and it is the only thing on
  the page that scrolls; the sidebar is navigation and lies over whichever pane
  is showing.
  One glyph in the top right corner of the window, beside the chat's name, says
  which: it opens the canvas over the whole screen, and a cross in that same
  corner closes it again.
  A swipe left or right moves between them, and nothing at all is drawn across
  the foot of the screen, so the whole of that height belongs to what is being
  read.
  The pane you were on is the one you come back to after a reload.
  It installs to a home screen as an app of its own - standalone, dark, and
  clear of the notch and the home indicator - which is what takes the browser's
  own address pill and keyboard bar off a phone.
- **Chats, not one endless thread.** What you say is split into chats, each with
  its own history, its own context window and its own canvas, and one of them is
  the one you are talking in - the voice answers into it whichever device woke
  it. **Chats** at the top lists them in the middle column, newest activity
  first, with what each is called, when it last had something said in it and how
  many messages it holds; clicking one loads it in the column on the right and
  you carry on in it. **New chat**, beside it, starts an empty one. A chat names
  itself from its own first exchange, in a few words with an emoji in front -
  "🚚 Server migration" - written by Haiku the moment the first answer is
  finished. You can rename it yourself, or ask Rouh to ("call this chat Budget
  2025"), and either wins from then on. Chats can be put in projects, and the projects are made,
  renamed and deleted from the projects dashboard, and from the middle column
  too; deleting one takes the chats in it with it, and says how many before it
  does. All of it is on disk, so it is still there
  after a restart, and everything said before there were chats is the first
  chat, whole and in order.
- **Forks a conversation to ask about it, without losing it.**
  Petar, 24 September 2026: "anytime I'm in a conversation and don't understand something, I would like to ask for clarification ... but at the same time, I don't want to lose where we are in the main thread."
  **Fork**, beside Send, or Ctrl+Shift+Enter (Cmd on a Mac), sends what is typed into a new side chat instead of into this one.
  The fork opens to the right, and this chat moves left and stays there, cut off by the edge of the column.
  Rouh answers in the fork having read everything in this chat up to that moment, and nothing said in the fork goes back into it, so the main thread is never "diluted".
  A fork can be forked again, as deep as anybody likes, and the chats lie side by side in the order they came from each other, with the canvas after all of them, where it always was.
  They are a row that slides sideways, and the chats either side of the one being talked in are the chats themselves - its head, its bubbles, the lines of its cards and forks, its box with Send - cut off by the edge.
  The first version drew a narrow card with a name, a few lines and "Back" there; Petar's answer was a screenshot of the edge of a real conversation, "this is what I want", and on the phone: "the vertical bar should be the actual chat, not a button ... I don't want it to snap and immediately see something else. I want to be able to slide like a side scroll".
  So the row moves under a finger, a trackpad, a wheel turned over a chat at the edge, or a press on one, and nothing snaps it: a little way across and let go stays a little way across; let go with another chat most in view and the row carries on to it, and that is the chat being talked in.
  About a fifth of a chat shows at a desk and forty pixels on a phone, and the room is kept for the whole strip, so moving along it never moves the canvas, and what is on the canvas stays there: a chart being asked about is still beside the fork asking about it.
  Every fork is marked in the chat it came off, at the point it came off, with the whole of what was asked in it rather than its title, and the mark opens it again.
  Each fork on the strip has its own round cross in its top right corner, which rides with it as the row slides: it closes that fork and every fork below it, and puts you back in the chat it came off; nothing is deleted, and each mark still opens its fork.
  It replaced a single cross in the head of the screen, which on 26 September 2026 did not say which of the chats side by side it would close.
  Sliding along the strip never reads a chat back: each one stays exactly as it was, with its box, and a turn still running in one goes on arriving while another is on screen, so its tool calls and its answer are there when it is slid back.
  A chat not shown on the page since it was loaded is read from the server the first time, and so is one that had something happen in it while the socket was away.
  Forking a chat that already has a fork open lays the new one in its place, and the one it replaced is closed, not lost.
  A fork is in no list - "They're just attachments to the main chat" - so the sidebar lights the chat it all started in, deleting that chat deletes its forks with it and says how many, and a fork is never pinned, filed or numbered.
  On a phone a swipe on past the last chat reaches the canvas.
  **Which forks are laid out is each tab's own** (since 22 October 2026, task 62 step 62-23): the desk, the phone and the Mac each keep their own strip, a close on one is never undone by another opening the fork, and the address says the strip as `/chat/<the chat in the middle>?strip=<the fork at its far end>`, so a reload, a link and Back bring the same strip back.
  **Moving along the strip is the page's own act** (since 23 October 2026): every chat of the strip is on the page already, the chat being left is kept as it is (its very conversation, never a copy of it), and the chat moved to is live the moment the slide ends; the server is told after, and its answer draws nothing. A close is the same. Until then each move waited for the server with an inert copy in the middle, a second press undid the first, and a list of the chats sent before a close laid the fork out again for a moment.
  Until then which forks were open was one flag per fork in the database, set by every screen on its way into a chat and told to every screen, which is how "close it and it comes back two seconds later" happened.
  `rouh/forks.py` is the whole of what a fork is; `fork` and `close_fork` in PROTOCOL.md are the wire.
- **The same chat on every device.** The phone, the desktop and a browser
  opened for the first time all show the same one, and a turn made on one of
  them appears on the others as it happens rather than after a reload. Opening
  a chat on the desktop opens it on the phone too. Opening Rouh somewhere new
  does not stand the other one down: both stay live.
- **Looks at what you give it.** Drop a screenshot on the conversation, paste one
  from the clipboard, or pick files with the paperclip. Pictures and PDFs go to
  the model as pictures and PDFs, text files go in as text, and anything it
  cannot open itself is saved and handed on by its path.
- **Keeps every link at the foot of the sidebar, where a thumb reaches it.**
  The sidebar is one group of links at the bottom of the column, above your
  own name: **New chat** and **New task**; then **Task browser**, **Runs**,
  **General**, **Morning brief**, **Control room**, **Reminders** and
  **Goals** (and **Live browser** while one is open); then **Search** and
  **Gene therapy** (Feedback until 12 October 2026). Above them the column is empty on purpose.
  Until 30 September 2026 the sidebar was one of three lists at a time -
  **Tasks**, **Chats**, **Runs** - behind a switch of three icons at its top,
  each list opening with a **Pinned** section. The owner goes everywhere through
  the task browser and used only the runs, so the switch, the list of tasks
  and the list of chats went with their Pinned sections, and the runs became
  a page of their own at `/runs`, opened from their link like Reminders and
  Goals, with everything the list had: **New run**, the tally, the archived
  tick, Pinned (your pinned projects and runs), the projects that hold runs,
  and the cards with their dots. The Control Room and its pins are untouched.
  Since 14 October 2026 that page is **Metabolism**, at `/metabolism` (`/runs`
  is sent on to it), split in two tabs, each with its own count: **Everyday
  work**, your own errands and jobs in your workspace, and **Mutations**, at
  `/metabolism/mutations`, the runs that change Rouh itself - improve_myself,
  delegate_task on this server, the nightly feature run, anything in the one
  program's `rouh` space. Each run says which when it starts (`run.kind`,
  `runs.kind_of`). A run waiting on you keeps its amber mark in its own tab,
  the tab carries a mark too, and how many runs need you is on the page over
  both tabs. It opens on Everyday work, and on Mutations from Evolution or
  from a mutation's own run.
  A conversation a numbered task of your assistant workspace owns **is** that
  task - "30 Jarvis" and `tasks/30.jarvis` are one object, not two that can
  drift - and is on that task's page, which the task browser opens. Every
  other chat is loose: one question, one answer, no number and no folder
  anywhere. **Search**, with nothing typed, lists them, latest first - General
  at the top, then what you pinned, then the rest by when each was last used -
  and finds any of them by what was said in it.
  A loose chat becomes a task when you say so - **Make this a task** in the
  menu beside its name - and never by itself: starting a run in it does not
  make it one (`conversations.promote`). It takes the next number, keeps every
  message and its folder is written into the workspace from the row.
  A chat stays until you delete it. Nothing removes one for you, however long
  it has been quiet.
  **General** is always there for you and Rouh to talk in, and for anything
  with no home yet, so nothing has to be filed before it can be said: it is the
  one conversation everything was folded into, it is never numbered, and the
  sidebar calls it General because of which thread it is rather
  than by renaming it, so the title the model writes for it is still its own.
  Its link in the sidebar opens it, on every press, and carries a red dot when
  something new is in it.
  A run reports back into the chat it was asked in, General included (Petar,
  12 October 2026): its report card says what it was asked, how it ended, what
  it changed and links to the run, Rouh says it there, and its notice, its
  phone message and its card on the Metabolism page all lead to that chat
  (`runs.report_chat`, `rouh/run_report.py`). The notice's own words, title
  and all, are kept in that chat as one of Rouh's messages too, so they can be
  read again once the notice is gone; the model is not sent them twice
  (`Memory.add_notice`, fr_c8fb46a5a132). A run no conversation started -
  the Start box, the Gene therapy board's builds, a mail case's work - keeps its
  report on its own card on the Metabolism page, which carries a dot until it is
  opened, and a page it made is on its task's page (`runs.report_stays`). Only
  a question a run is stopped on, a conflict waiting for a pick, and an email a
  job queued for you are still brought to you in General then.
- **Pins what you are in this week, and gives every row the same menu.** Every
  project and run on the Metabolism page, and every search result, carries three
  dots at its end, and behind them are the
  things there are to do to one: **Un-pin** (or **Pin**), **Rename**,
  **Delete**, on a chat's row **Change project** and **Remove from project**,
  and on a task's row **What is under it**.
  Rename happens where the name is: the row's own name becomes a field with
  the name in it, selected, and Enter or clicking away keeps it while Escape
  puts the old one back. Change project opens the projects beside the menu,
  the one the chat is in already ticked, and pressing one files it there. Those
  two are on a chat and not on a task or a project of the workspace, because
  those are folders in git and moving one moves its folder with it, which is
  the task browser's own filing.
  Pinning is
  the one mark you put on a row yourself, and it leaves the order under it
  exactly as it was - the chats by when you last used one, the runs by when
  each started, the tasks by number. What is pinned is drawn in the **Pinned**
  section at the head of its own list and is taken out of the list below it,
  so nothing in the column is ever drawn twice: a pinned project
  goes there rather than in the runs' Projects group, a chat, a task or a run
  goes there rather than staying where it was, and a project you open says
  "Its chats are pinned, above" rather than showing them again - its count
  still counts them, because it does hold them. A project in Pinned opens
  where it stands on the chats and the runs, and what it holds is listed
  underneath; on the tasks it opens its own page in the canvas, because what
  is under a project there is a page and not four rows. **General** is never
  in Pinned: it carries the mark because it is the thread that is always
  there, not because you put it there, and it stays at the head of the chats.
  Nothing is kept from anything by being pinned: nothing here is archived or
  deleted on a clock, so a pin is a note to yourself and not a reprieve. The
  same pin is offered on every row of a search result, and on every card on
  the projects page.
  A task is not born pinned. It was until 22 September 2026, while nothing
  drew the mark; a pin that all 49 of them had sorted nothing and said nothing.
- **Has one menu, wherever there are three dots.** The dots on a row, on a
  run's card, on a search result, at the head of the chat you are in and on a
  project's own page, the task browser's menu on a project and the menu behind
  your own name all open the same menu (`rouh/static/menu.js` and `menu.css`,
  put into the framed pages as well): a small icon in front of a short word -
  **Rename**, **Move**, **Pin**, **Delete** - and whatever cannot be undone
  last, under a thin line, in red, turning solid red with white words under
  the pointer. The arrow keys walk it, Escape closes it and gives the focus
  back to the dots. Petar, 24 September 2026: "make that three-dot pop-up menu
  universal around." The chat you are in has **Delete** on its own dots too,
  the same delete dialog as everywhere else, and deleting the chat you are in
  leaves you in General. Every chat has it except General, which is never
  deleted.
- **Keeps the running work one press away, and out of the way.** The **Runs**
  link carries a **red dot** when a run has **stopped** and you have not
  looked at it yet, and so does the card of each run it is about; General's
  link carries one when an answer in it has not been read.
  Stopped is the whole of what it means: a run that finished, ended badly or
  stopped to ask. Work going on carries no dot - there is nothing for you to do
  about a job that is running, and while the dot meant that it was lit all day.
  Opening the Metabolism page is looking at the runs, so the link's dot goes out at
  once, and the cards keep theirs until the next visit; opening a run or
  archiving it takes its own dot off. The mark is a column on the row, so it
  survives a reload, a restart and your other device, and every fresh stop is
  unseen again: a run carried on and finished a second time is a second thing
  to look at. The switch of three icons that carried these dots for the
  tasks, the chats and the runs went on 30 September 2026.
- **Has one page for the projects.** The projects dashboard opens over the
  conversation and the canvas together; closing it gives back exactly what was
  there. It was **All projects**, under New on each of the sidebar's lists,
  until 23 September 2026, when the task browser took that row: it is reached
  from search now, and what it is still for is a project of your own, which
  holds chats, has no folder in the workspace and so has no page in the
  browser. It lists every
  project, nested the way they own one another - Work and Personal at the top,
  what is inside them stepped in under them - with what is in each one under
  its name. A project of your own is made, renamed, made inside another and
  deleted here, and either kind is pinned here.
  A project made at the top is not one of your own for chats: the top is where
  Work, Personal and Rouh are, every project there is a column of the task
  browser, and a column is a folder of the workspace, so it is given one the
  moment it is made (`objecttree.columns_are_folders`). **Rouh** was the one
  that was not: the 🪸Rouh chat folder of 19 September 2026 came across as a
  row with no folder at the top, so Manage projects listed it and refused it,
  the task browser left it out, and General, which sat in that old folder,
  was drawn inside it. Since 29 September 2026 it is the folder `rouh/`, the
  same kind of object as `work/` and `private/`, with the chats it held still
  in it; and **General is never in a project** (`conversations.let_general_go`).
  The projects of your workspace are folders in git and are read
  here rather than changed here: the **task browser** is where those move.
  **Deleting a project deletes what is in it**, and it says so in the number of
  things it is about to take before it takes them: `"test project" and all of
  its chats will be permanently deleted. This can't be undone.` It is the one
  delete in Rouh that follows ownership down rather than letting go of it.
  Two things it lets go of instead, because neither is the project's to
  destroy: a folder of your workspace, and General.
- **Folds away, and remembers how wide you like it.** The panel glyph in the
  top left corner of the window hides it and brings it back, and so does Cmd+B,
  or Ctrl+B. That glyph never moves: open, folded away or lying over the page,
  it is in the same corner, and what is left of the column while the sidebar is
  away is the strip it sits in, empty under it. Drag the gap on its right to set
  its width, between 240 and 400 pixels, and this browser keeps it. Wide, it is
  docked and the page resizes around it. Narrower than about 1100 pixels it
  folds itself away, and opening it then floats it over the page rather than
  pushing it aside, so what you were reading stays where it was; a press past it
  closes it again. On a phone it covers the screen, with a cross where the glyph
  was. Folding itself away never overrules you: what you asked for at this size
  stands until the window changes size in earnest.
- **Is one flat surface, flush with the window.** No border, no rounded corners
  and nothing between it and the edge of the screen: it is a shade darker than
  everything beside it, and that is the whole of what separates them. What it
  holds scrolls as one thing rather than in three windows of its own, so the
  projects and the chats under them move together.
  The orb's small circle is fixed in the top left corner of the window and the
  navigation button in the bottom left, each over whatever is there and never
  moving with it: Petar asked on 30 September 2026 for the two to swap, so the
  button is beside the links at the foot of the sidebar where a thumb reaches
  it, and the orb stays put rather than riding the foot of whichever column
  was leftmost. Pressed, the circle still opens the orb over the whole screen,
  and the button stays on top of that too.
- **Has no bar across the top of it.** There was one, and it held a name, four
  things to glance at and three buttons; it cost a row of every screen to do
  it. The name is on the sidebar's one head row now. The four statuses - whether the socket is
  up, whether the voice is ready, and a mark for each of the two services on
  this machine - went to its foot beside your own name, and off the screen on
  13 October 2026; the bell and Search are at the end of that row, and Settings
  and signing out are behind that name. The microphone tuning is Settings,
  Voice detection (`/settings/voice`), since 13 October 2026; it was a drawer
  of its own with no close button until then. The button that
  folded the transcript away is gone, and so is the one that gave the canvas
  the whole screen: `set_panels` still folds the transcript if you ask out
  loud, and the tasks fold it by themselves. That fold lasts the
  visit and is never written down - nothing on the page is a button for it any
  more, and a fold no control can undo must not outlive the tab. Opening a
  chat, or starting one, gives the column back whatever folded it.
- **Says where you are, and lets you move from there.** Whatever is loaded in
  the canvas carries a breadcrumb along its top bar, in the same design your
  workspace's own pages carry: **All tasks / Task 30 · Rouh / 30-38 · The
  merged chat and canvas**, and then the page's own title. The words on each
  chip go to that level, so it climbs to a parent a level at a time; the
  chevron beside them lists that level's siblings - every other task, every
  other step of this task - so you move sideways without going back up first.
  Escape climbs the same ladder, one press at a time, and the cross at the end
  of the bar closes what is loaded and gives the columns back. On a phone the
  breadcrumb scrolls rather than squeezing, and it sits at its end, so where
  you are is what you see and the parents are one swipe to the left.

  There are no mode buttons. There were five until 21 September 2026 - index,
  task, page, source and now - and four of them said what the workspace's own
  index says better, on a dial in a corner of the canvas that never connected
  with anything. The canvas has two modes now, the tasks and now, and a task or
  a step is opened by clicking it rather than by pressing a mode.

  Say it instead of pressing it: the numbers you already say out loud are the
  address of everything. A task is one number and a step is two - "thirty dash
  six" - and either one loads in the canvas.
- **Writes a step as one file, which is both faces.** A step made from now on is
  a single markdown file, `step.md`, in its numbered folder: front matter
  saying the task, the step, the title and the state, then prose, then blocks
  fenced with three colons, or more where a block's own body holds a line of
  them. The block names are the ones the canvas already
  draws, so nothing is authored twice and there is no HTML to keep in step with
  a separate context.

  ```
  ---
  task: 30.jarvis
  step: 30-06
  state: decided
  ---

  ## Decision

  The task folder is the record.

  :::stat
  label: Permanent stores
  value: one
  :::
  ```

  It stays plain text, which is a hard requirement rather than a preference:
  the record has to be greppable, diffable and readable with nothing running,
  so it survives Rouh being off. The pages already in your workspace are not
  converted and not rewritten - a step folder holding an `index.html` is served
  and framed exactly as it always was, and `step.md` is only what a new step is
  written as. `rouh/steps.py` is the whole of the format.
- **Opens a task or a step to its own page, and shows a page only as itself.**
  Pressing a task or a subtask, in the task browser, the rail or the breadcrumb, opens its own page (`_level` in `rouh/objectindex.py`).
  Its name is at the top, with the date it last changed at the right of the same line, and nothing else: the path and the counts under the name went on 24 September 2026, when Petar asked for the page to be reordered (fr_a52896d17de5).
  Under it, in this order: its **Chats**, the one talked in last first, each saying how many cards it drew; its **Page**, when it built one itself, as a panel across the page, because the page is what the work was for; its **Decision**, what a waiting task asks you, as a compact card that opens in place when pressed and folds again on a second press, since a decision has no page of its own; its **Subtasks**, one panel each, with the page each built one press away; and last, what is **Directly in this task**: its runs, its cards, its `.md` files, its other files and its folders.
  A card one of those chats drew is not listed there: it is in that chat, and **Cards**, on the chat's three dots, lays every card the chat ever drew side by side on the canvas.
  Which chat drew a card is written down, not guessed: each card's version names the message it came after, and that message is one chat's (`artifacts.chats_drawn_in`).
  A card that only showed one of the task's pages is not listed either, because that is the page and is listed once.
  A page opens as the page it is, at full width; a `.md`, a `AGENTS.md` or a `step.md` opens read on the same page, a folder as a list of what is in it, and a code file as its text, each with the way back above it (`rouh/docview.py`), and none of them is ever served as a file.
- **Says what a waiting task is waiting on you for.**
  A task whose next move is yours carries the Waiting pill, and until 24 September 2026 that pill was all it said: what was being asked was somewhere in a page of the task's notes, on a dozen tasks at once.
  Petar, 22 September 2026: "I am not sure what this is, how it is triggered, what is the exact action I need to do and how do I get through it so I am not needed."
  Now the question is said on the task's own page, and in the tooltip on its question mark in the rail.
  The task browser says only that it is waiting, with the pill, and **Waiting on you**, first in the row of project buttons, keeps only those tasks, which is the list of what is waiting on you.
  It also said what each one asks, in a line under the task's name and in full on each card of Waiting on you, until Petar, 24 September 2026: "remove the entire block Waiting on you including the specifics of what it is awaiting. keep only the waiting label."
  Nothing is guessed: `rouh/waiting.py` finds the passage in the task's `AGENTS.md` by the marks the notes use - a paragraph opening "Waiting on" and the owner's name, or "The ask", a heading such as "Open questions for the user", a line that opens "It asks" or "Open:" - and a task whose notes say none of those says so, with **Ask what it needs**.
  The agent instructions every run starts with (`rouh/agent_instructions.py`) ask it to write the question in the first of those shapes.
- **Asks it with the answers, and is answered right there.**
  Petar, 24 September 2026, about the yellow box on task 61: "easy options for answers predefined for me and option to give my own. but right there. and it has to be clear what happens afterwards. would the chat continue? the task will continue?"
  Under **Decision** on a waiting task's own page, folded to one compact card until it is pressed, the box says four things in order (`_waiting_panel` in `rouh/objectindex.py`).
  What has stopped: **Paused** - the task does nothing more until you answer.
  The question.
  The answers to pick, each a row with a number and a line under it that sends with one press (or, where several may be picked, marks it for one Send), and a field for your own words under them, sent with its arrow or Ctrl+Enter (Cmd+Enter on a Mac).
  And what answering does: it goes straight to Rouh in the chat the task already has, named on the box, and Rouh hands it to a job that writes it into the task and carries the task on (`WAITING` in `rouh/brain.py`).
  It never opens a second chat beside that one. Petar, 24 September 2026 (fr_d262eeec7d44): "that should go to the main chat, not opne a new chat. only open a new chat If there was no such chat before that", after answering task 61 made "Website content integration task" beside its "Website architecture review".
  Of the chats a task holds, the answer goes into the one its question was raised in, which is the one the newest job about the task was started from, and otherwise into the task's own conversation, the oldest (`conversations.answer_for_task`). Only a task with no chat at all gets a new one, which the answer makes the task's own. The screen moves to that chat, or stays on it; if Rouh is still answering something there, the answer waits in the box, in sight, and goes the moment that turn ends.
  The answers come from whatever asked: a job that marks a task waiting (`rouh-task status <number> waiting`, which changes it in the database, the only place a task's status is kept) puts a `question` into its meta with `rouh-task meta` - `ask`, `options` with a `label` and a `detail` each, `several`, and `then`, what answering will do (`waiting.question_of`, and the statement "Waiting tasks and their questions" in the agent instructions). A task with none still gets the passage from its notes and the field.
  A task that is **done** and still asks something is drawn in slate as **An optional question**: nothing waits on it, and answering opens the task again.
  The answer is written down as it is sent (`rouh/answering.py`, the `task_answer` table), so from then on the box is teal and says **Answered**: what it asked, what you answered and when, the chat it is in and the job started from that chat - running, asking you something, finished or stopped - with **Answer again**. The page loads itself again once Rouh has replied, which is when that job appears. The task's pill says Answered rather than Waiting, the rail's question mark comes off, and the task browser's Waiting on you leaves it out, until the job has changed the task and the question is gone.
  **Dismiss**, at the right of the box's heading, closes it without an answer ("i also need the option to dismiss it"). Nothing is sent and the task is left as it is; the box folds to one dashed line - "Question dismissed today at 17:52. Nothing was sent, and the task stays paused, and is not counted as waiting on you." - with **Show the question** to answer after all. It is written down like an answer (`dismissed` in `task_answer`), so it stays folded, the task loses its Waiting pill and the rail's question mark, and the task browser keeps it out of Waiting on you, with no pill and no line under its name. An answered box can be dismissed too: the line then says what you answered and which job has it.
- **Files what it draws when you ask it to, and not before.** A card is a card.
  Nothing on this machine turns one into numbered work by itself, and nothing
  turns a chat into a task by itself either: that was taken out on 22 September
  2026, in your words - "tasks should be created out of chats only when I ask
  for it, never automatically". Until then a card drawn while the thread was
  task 30 was written into `tasks/30.jarvis` as its next numbered step the
  moment it was drawn, and a run started in a loose chat numbered that chat.
  What is kept is every way of asking. A card drawn in a thread that is a task
  carries a quiet **File as a step** button; press it and the card says
  **Filed as 30-09** with the number that opens it. Say "make a task out of
  this" or "file that one" and the same two things happen from the voice
  (`make_a_task`). The item in the chat menu still makes the thread itself a
  task, and what it drew goes in with it as its steps. Filing never commits
  by itself - the workspace is a git checkout of its own repository - and
  Rouh's saver lands what it made (`rouh/saving.py`).
- **Deletes anything, and takes what belongs to it.** A card, a numbered step
  and a built page are all one thing - an `artifact` row with its versions
  (`rouh/artifacts.py`) - and each of them **belongs** to something on
  purpose: a task, a thread, or nothing at all. So does every chat, every run
  and every task. There is one delete for all five (`owning.remove`) and it
  cascades: deleting a project deletes its tasks, their threads and the cards
  those drew, and the folders on disk go with the rows. You are always asked
  first, with the thing named in quotes and a count of what goes with it. A run
  still going is stopped before its record is taken away. A **reference** is
  never followed: a run that came `from` a deleted chat is exactly where it
  was. The database is the record and the folders under the workspace are
  written out from it, so where the two disagree the row wins.
- **Starts a run that belongs to nothing, and lets you say later where it
  belongs.** **Start a run** over the run list asks for three things and no
  more: what it should do, which workspace it works in, and under what rules.
  It runs, it is on the orb, it is on the list, and it is nobody's - which is
  the ordinary state of things here rather than a half-made one. A run, a chat
  and a task each carry **Move**, which says where it belongs, and it is one
  dialog, offering whatever the ranking allows: project, task, chat, run,
  artifact, downwards only. Putting a run under a task takes its diff, its artifacts and what it
  cost under that task, because those were the run's own all along, and taking
  it back out gives them back. **New task** makes a task like any other: it
  takes the next number, its folder is written out of its row, and the model
  that reads what each project is for files it into one.
- **Shows your own workspace, and it is the one way in.** The **Task browser**
  link, first of the links at the foot of the sidebar, loads your assistant
  workspace's own index of every project and every task at once, in the canvas:
  one column per top-level project, Work on the left and Personal on the
  right. That order is written down
  (`objectindex.COLUMNS`) rather than worked out, because there is nothing to
  work it out from - neither carries a number and both were imported in the
  same instant, so the only rule going was the alphabet, and the alphabet is
  not how anybody reads these two. The buttons across the top and the headings
  in the move menu follow it. A third top-level project comes after them, by
  name.
  It takes the conversation - two columns of tasks want the width and squeezed
  into a third of it they are neither - and so does everything you open out of
  it, because a task's page is built to be read and the shape should not change
  under a press. The cross beside the breadcrumb gives it back, and so does
  opening a chat or starting one, which brings the conversation back beside
  what you are reading and keeps it there.
  Pressing **Task browser** in the navigation takes it again, from wherever you
  were: that press is you saying what the window is for, and it is the one
  thing that overrules a conversation you asked for while you were in the
  tasks. Pressing the breadcrumb's own first chip is not - it is a step back up
  inside them, and it leaves your columns alone.
  **The navigation is left exactly where you had it**, open beside the tasks or
  shut, because it is the way to every other part of Rouh and it has a glyph, a
  key and a saved fold of its own. It folded itself away and put itself back
  until 22 September 2026, which was one column too many being decided for you.
  The one screen where pressing Task browser does put it away is the one where
  it lies over the page rather than beside it - narrow, or a phone - because
  there the browser opens underneath it and the press would otherwise look like
  it did nothing. Every other row there does the same.
  A link at the end of the breadcrumb's line opened the published copy of the
  same workspace on a separate site in a new tab until 23 September 2026, and
  so did the arrow on the Task browser row. That copy is not used any more and
  both are gone. What is published now is published from here, one page at a
  time, and **Share** in that same line is the control - "Public pages", below.
  Click a task for its steps, click a step for that step's page. Escape and the
  breadcrumb walk back up, and the cross gives the bare canvas back.
  **The tree is tasks and nothing else.** A task has an arrow only when it has
  steps, and opening it lists those steps and their own steps; a task with none
  is one flat line. What a task holds that is not a task - the pages it built,
  its chats, its runs, its cards - is on the task's own page, which its name
  opens, and never a line under it here.
  A button across the top for each project, with how many tasks are in it:
  hover one to light up its tasks where they sit, click it to keep only them
  across the full width with every step listed, and hold Shift to keep two.
  The column name over each side does the same for the whole column. The search
  box filters by task, step, title or project, and a search that finds a task
  only through one of its steps opens that task showing just the steps that
  matched. **Expand all** opens every task's steps in place and says
  **Collapse all** once they are open. A column past fifty tasks folds the
  older ones behind a line that says how many.
  It takes the keyboard when it loads: the arrows walk the tasks, left and
  right cross to the same place in the column beside, Enter opens what is
  highlighted, Space unfolds one, `/` goes to its search box, Backspace and
  Alt + Left go back a level. Escape clears the search, then goes back to both
  columns, and once there is nothing of its own left to undo it goes back a
  level like the others.
  It is drawn from the object rows and the `owns` links between them
  (`rouh/objectindex.py`), so a task made a minute ago is there on the next
  load.
  **Where a task belongs is changed here**, by dragging it onto a project
  button or clicking the project name on its line, and **Manage projects**
  renames a project, moves it between the two columns, adds one and deletes an
  empty one. Every one of those goes through `rouh/objecttree.py`, which is the
  one create path and the one move path there is: the row first and the folder
  out of the row, a move carrying the folder with `git mv`, and a move the three
  rules refuse - a project under a task - coming back as a sentence rather than
  happening. The page is sandboxed and cannot write by itself, so each change
  is handed to Rouh's own page, which is signed in and asks
  `POST /api/workspace/filing`; what it hands over is an action name and object
  ids, never an address. Opened at its own address, away from Rouh, there is no
  page around it to carry a change, so it says so and is read only.
  **This is the only place on a screen where a project of the workspace is made,
  renamed or moved, and where a task is filed.** The rail had **Arrange the
  workspace**, a second way into the same two writes, until 22 September 2026,
  and the link and the dialog behind it both went at Petar's word - "this entire
  functionality needs to be removed, because we will be doing something else".
  It was the workspace's own index page, served by `assistant-askai.service`
  beside the separate workspace, and it went with it on 21 September 2026. What
  replaced it was a list, so on 22 September the page itself came back, on the
  object rows rather than on `_categories.json`.
  It was a modal over the whole window until 21 September 2026, which put a
  sheet over the Ask AI drawer below and took all three columns to show one of
  the two.
  Everything about tasks starts here: clicking a task in the list of chats and
  tasks loads exactly what clicking it here loads, and so does asking for it out
  loud.
- **Asks about the page you are reading, and changes it, from one place.**
  The conversation column has two tabs over it while a page from the workspace
  is loaded: **This page** and **Rouh**. One of them is on the screen at a time
  and there is never a second chat beside it.
  **This page** is Ask AI. Select a passage and press **Ask** on the little bar
  that appears over it, or press the star in the corner of the page, and the
  passage is quoted above the box. The answer is grounded in the page and in
  the working notes beside it, and the panel names which files it read; a page
  in a folder inside a step, such as a booklet's `pages/p027.html`, is answered
  from that step's notes as well, whole.
  **Topics** is everything asked about this page before; they are conversations
  of their own (`askai_threads`), never chats in the project, so a page you
  asked six questions about leaves no chats behind it.
  A passage you asked about stays marked on the page; clicking the mark reopens
  that topic in the same panel, and the topics are kept, so they are still there
  the next time you open the page.
  **It changes the page too.** "Take that heading out", "make these cards
  blue", "add a button that hides the intro": Ask AI carries a request out on
  the page itself and says what it did, and a question is still just answered.
  To say which part, select a passage and press **Change** on the bar over it,
  or press **Point** under the box and point at the part of the page itself -
  a box follows the pointer round whatever is under it and says what it is,
  and a click picks it. Every element of the page is marked with where it is
  in the file as the page is sent, so the model is handed exactly that
  element's source, and no page has to carry an id of its own
  (`pages.with_marks`). **Edit**, the pencil in the page's floating bar, or E,
  is the same pointing started from the page itself and kept on, as C is for
  comments: the pointer is a pencil, and every part clicked is handed to the
  box as the thing to change, one after another, until E, Escape, Done or the
  pencil again. The change is written into the page, the page comes
  back where you were reading, and the line that says what changed has
  **Undo** on it, in the topic for good. It is saved to main like everything
  else Rouh writes into the workspace (`rouh/saving.py`).
  Petar, 24 September 2026: "Now I want Ask AI to also be able to edit that
  content... Consider whether Ask AI should be doing it on its own or passing
  that request to ROUH." On its own: a page is one file the model already has
  in front of it, and a reader a page is shared with has no Rouh to pass
  anything to. **Rouh**, the other tab, is the whole assistant, for anything
  bigger than the page.
  **It is Ask AI's tier on the Models page, and says so** beside the box
  (`rouh/modeldefaults.py`, which assistant jobs and runs are started on too).
  Rouh's log names every tier and use at every start (`models:`).
  **No page is too big to be changed** by a size of Rouh's own: the page's
  source and its text go to the model whole. The only limit is the model's
  context window, a million tokens, and a question past it is told so in words,
  with the count the API gave ("That is more than Opus 5.5 can read at once:
  ... come to 1,542,123 tokens, and Opus 5.5's context window holds
  1,000,000"), never "The model answered 400". Until 24 September 2026 a page
  over 400 KB could be asked about and not changed, and its text was cut at
  120,000 characters; Petar met it on task 61's 429 KB site (fr_934145d6e00e).
  Until 23 September 2026 there were two chats on this screen: this column, and
  an Ask AI drawer that slid over the page beside it.
  Petar: "it is confusing to have two chats, so they need to be merged into one
  thing... I should not have two chats on the same screen at the same time."
  The page still carries the whole of Ask AI in it (`rouh/static/askai/`), and
  it is split rather than switched off: `ASKAI_HOSTED` says this column is
  drawing the conversation, and `ASKAI_CAN_EDIT` - deliberately a second
  question - says whether this reader may have the page changed.
  Where Rouh is framing the page for its owner the drawer in it is put away
  and this column draws the conversation instead; a reader it is shared with
  gets the drawer in the page.
  The page itself cannot reach Rouh: it is sandboxed, so what the reader
  presses is handed up to the page around it, which carries it.
- **Keeps every page's history, and the versions worth switching between.**
  **History**, beside the sparkle in the page's floating control, lists every
  change to the page, newest first, with who made it and when, and opens any
  of them as the page was then, read only. Every change Ask AI makes asks
  whether to keep the version before it as an option; kept, the part of the
  page gets a small purple tab and a pop-up to switch between its versions,
  drawn over the page rather than written into it, and anybody reading the
  page may pick the one everybody sees. "A page's history, and its options",
  below, is the whole of it.
- **Shares one of those pages with anybody, or with one person.** **Share**,
  in the top bar beside the breadcrumb and in that one place whatever page is
  loaded, makes a page public: a link anybody can open with no account, no
  sign-in and no password.
  **Copy link** puts the page's one link on the clipboard rather than printing
  it on the screen - the same link every time, public or not, with who it lets
  in decided by who has access - and **See all public pages** lists everything that is public
  right now with the control that takes each of them down again.
  One page travels, as it is on disk, and nothing around it: a link inside it
  to another page of the workspace still asks a stranger to sign in.
  A visitor reads it and nothing more, unless the page was made changeable for
  them - then they get Ask AI on it, which answers and changes it.
  **Add people by email** shares it with one person instead: they get a letter
  from Rouh with the link, sign in with rouh.land as that address (no account is
  made here), and see the page - and everything else shared with that address -
  at `/shared`, with Ask AI on it. Only a Connected Rouh does this. "Public pages", below, is the whole of it.
  Rouh does the same when asked out loud: "make task 56 public" publishes every
  page of that task, after saying what is about to go out and hearing a yes,
  and a separate yes for any money, health detail or contact details in it.
- **Takes comments pinned to a page, the way Figma does.** The comment button
  sits beside the Ask AI sparkle in one floating control at the page's top
  right; it, or C, starts commenting, and a click on any part of the page
  pins a thread there. People tag each other with @ and are emailed, threads
  are resolved and can be shown again faded where they were, and a comment
  whose part of the page was later taken out keeps its place and shows what
  that part looked like. For the page's owner and everybody it is shared
  with by email. The chevron also has Ask AI go through every open thread in
  one pass and add to it, tagging whoever gets a decision, with a report in
  the page's chat. "Comments on a shared page", below, is the whole of it.
- **Reads and writes your mail, your files, your documents and your calendar.**
  Connect a Google account in **Settings** and Rouh can read the mailbox and
  search the Drive, list what is inside any folder or at the root of My Drive,
  name the shared drives the account can see and list one of those, and it can
  send mail, reply in thread, write drafts, label, archive and bin messages,
  save and rename files, and make and edit Google Docs.
  It reads every calendar the account can see, its own and every one shared
  with it, answers "what do I have tomorrow", puts events on a calendar,
  moves, renames and re-invites them, answers invitations, and deletes one
  only after saying which and hearing a yes. Settings lists the calendars it
  can see and adds one somebody has shared with the account (`GOOGLE.md`,
  "Calendar").
  It also decides who can open a file: a link anyone who has it can use, or a
  named person by their email address, and back to private again. It says out
  loud what it is about to share and with whom first, because a link that has
  been sent cannot be unsent.
  Everything that writes is recorded in `{data_dir}/logs/google-writes.log` as
  it happens, with what it did and to whom, because a sent message cannot be
  taken back. There is no confirmation dialogue: Rouh asks out loud before it
  sends and says afterwards exactly what it did. Each organisation registers
  its own Google Cloud OAuth client - Google will not approve one public app
  for this - and its administrator enters the client id and secret in Settings
  once; everyone in that organisation then connects their own account through
  it and sees only their own mail and files. `GOOGLE.md` has the whole of it,
  including what to do in the Google Cloud console.
- **Looks people up in your Apple contacts, and adds or changes them.**
  Enter your Apple ID and an app-specific password under **Apple Contacts** in
  **Settings**, and Rouh keeps a copy of your iCloud address book, synced over
  CardDAV every quarter of an hour, so "what is Ana's number" is answered at
  once. It adds a contact or changes one only when you ask, writes it back to
  iCloud with the card's ETag so a change made on the phone at the same moment
  is caught rather than overwritten, and keeps both versions when the two
  really disagree. A sync only ever reads. `APPLE.md` has the whole of it.
- **Talks with you on Telegram, both ways.** It texts you with `send_telegram`,
  which is how it reaches you when you are not at the screen, and since 26
  September 2026 you can write back to the same bot from your phone: each
  message is a turn in General, exactly as if you had typed it into the box,
  shown on every screen standing in General and answered with the same tools,
  memory and rules, and the answer comes back to the phone as plain text.
  A card it draws is named in the answer with a link to it on Rouh, and its
  words go too when they are short; footnoted sources become a short list of
  links; a long answer goes in several messages; "typing..." shows while it
  works. Photos and files you send are attached in General the way a picture
  dropped in the browser is, and a voice note is read with the same
  speech-to-text the microphone uses. Whatever it asks before doing, it asks
  there too, and your yes on Telegram counts, because only your own chat is
  ever read: a message from anybody else, a group or another bot is written in
  the log and dropped, never answered and never shown to the model.
  It reads with a long poll, so nothing here has to be reachable from outside,
  and keeps where it got to in the database, so a restart never answers a
  message twice; a message a restart cut off is named on the phone when it
  comes back.
  **Forks from the phone** (since 27 September 2026), with /fork and nothing
  else: /fork written as a reply to one of its answers makes a new fork of that
  chat that comes off just below that answer - the same fork the screen makes,
  laid beside its parent and marked in it with its first message - and that
  first message is the words after /fork, or, with none, the next thing you
  send (/cancel puts it down). Not as a reply, /fork forks the chat as it
  stands. /fork, /cancel and /help are in the menu of the chat, set for your
  account only.
  **Each fork opens in a new group of its own**, the way a project of your own
  might open a group for an idea. A bot cannot make a group, so Rouh
  makes it as you: connect your own Telegram account once, in
  Settings under Telegram account (the API id and hash from my.telegram.org,
  your phone number, the code Telegram sends, and your two-step verification
  password if you have one). From then on every /fork makes a group named
  after its first message, with Rouh's bot in it as its admin; the bot says
  where the fork came off, your first message is posted there as yours, and
  the answer follows. Whatever you write in that group goes to that fork, and
  /fork there forks it again, into a group of its own. The private chat is
  told the group's name, with a link into it. The account is used for that
  and nothing else - none of your chats is read - its session is kept
  encrypted, and Disconnect logs it out (`rouh/telegram_account.py`). Without
  it, a fork is on the screen only: its first message is answered there and
  the answer comes back to the private chat once, with the fork's link.
  **The private chat is always General** (since 27 September 2026): whatever
  you write to the bot directly is written in General, drawn on every screen
  standing in it and there after a reload, in its place in time, as if you
  had typed it there, with Rouh's answer under it. For a day the private chat
  could move into a fork, with /chats, and stayed there, so what you wrote to
  the bot never reached General; /chats and /general now only say this.
  Nothing moves on the screen and nothing is copied: a fork is one chat,
  written from either side. A fork waiting for its first message and each
  fork's group are kept in the database, so a restart leaves them as they
  were (`rouh/telegram_forks.py`).
  Its own bot, separate from the bot the development machine's
  `tg-ask` and the one program's phone share, which still only sends. Only
  one process may read a bot, so only the service does: every test world is
  pointed at a file that is not there.
  The bot's key and the chat it talks to live in one file on the server, outside
  this repository, owned by the user the service runs as and mode 0600
  (`ROUH_TELEGRAM_FILE`, `/var/www/rouh/.secrets/rouh_telegram.json`); with
  no file there Rouh says it is not set up rather than pretending it sent
  something, and reads nothing. `rouh/telegram.py` is the bot,
  `rouh/telegram_chat.py` the conversation, `rouh/telegram_forks.py` which
  chat the phone is in and the forks made there, and
  `rouh/telegram_account.py` your own account, which makes their groups. The
  stand-in (`rouh/testing/fake_telegram.py`) has a phone page, `/phone?chat=<id>`, with
  the chats and groups, the "/" menu and the buttons on it, for a browser to
  press, and it stands in for your own account too (`/_account/...`), so a
  test world connects one and makes groups without Telegram.
- **Handles every new email itself, the moment it arrives, and tells you.**
  Gmail tells Google Cloud Pub/Sub, Pub/Sub posts to `/hooks/gmail/<token>`
  on this server, and Rouh reads what was added to the inbox and hands each
  message to itself, in a conversation of its own that starts with the email.
  It finds out who wrote it - their contact, who they are to you, and online
  research it does itself when there is none - asks you on Telegram who they
  are if you never said, and answers what it may. Somebody else's email or
  Telegram message that went through cleanly - done, checked, and answered in
  full, or needing nothing - ends quietly, with nothing to your phone: you are
  sent a note with a link only when it needs your decision, stopped, was
  refused or declined for you, or was only partly done (5 October 2026,
  `ended_cleanly` in `rouh/mail_cases.py`). Your own mail, from any
  of your addresses and confirmed by Gmail, is your instruction: marked read,
  done, answered with the results and archived. Anybody else's can reach only
  a few tools, and is only ever answered in its own thread, once you have said
  who they are. The small model that used to decide whether a message was
  worth a note is gone (25 September 2026). Turned on and watched in Settings,
  under **New mail**, which also shows whether the watch is active and what
  Rouh did with the last few messages. An administrator sets up the Pub/Sub
  topic once. `GOOGLE.md`, "New mail, handled by Rouh itself", and
  `rouh/mail_alerts.py`.
- **Judges somebody's email ask by ask, against grants you set.** What a
  trusted contact may be given is a tree of grants per organisation, each with
  a name, a description for you and the words Rouh's reading is told, edited,
  merged and put back by version in Settings > Trusted contacts > Grants
  (`rouh/grants.py`). Since 11 October 2026 each case has one ledger of asks,
  the only truth about it: the reading maps each ask to a grant, code decides
  what may go, a hard limit is what a tool does, the status part of a reply is
  written from the ledger, and one outbox is the only sender, so nothing goes
  twice and nothing runs again without your Redo. Test grants on a case shows at
  once what a run would let through, and `python -m rouh.mail_replay` replays
  every kept case before a landing that touches the mail code. `MAIL.md` is the
  decision record.
- **Knows who people are.** Every contact carries who they are to you, in your
  words, and online research about them, both Rouh's own and never written to
  iCloud, both shown and changeable on the contact's card. `APPLE.md`, "Who
  they are, and what is known about them", and `rouh/people.py`.
- **Remembers** between conversations, in a file you can read and delete.
- **Searches the web and reads pages**, with Anthropic's server-side
  `web_search` and `web_fetch`, called from the turn like any other tool.
  Both carry `allowed_callers: ["direct"]`, which is what says the model may
  call them itself.
  Without it they exist only inside Anthropic's code execution sandbox, which
  has no network, and every search fails silently and is answered from memory
  instead.
  For the same reason the code execution tool is off (`ROUH_CODE_EXEC`): those
  two already run code on Anthropic's side, and a second sandbox declared
  beside them takes the searching away again.
  **Reads a page again in a browser when the fetch could not get it**
  (`rouh/fetchfallback.py`).
  When `web_fetch` fails because the site turned it away, it was busy or
  broken, or the page is a kind it does not read, Rouh stops the reply at that
  failed fetch, opens the same address once in a headless browser of its own,
  and hands the model what the browser read as the result of a `browser_fetch`
  call it adds to the reply, and the model carries on from the page.
  That browser starts with nobody's logins and goes out through the Live
  browser's gatekeeper and jail, so it reaches the public internet and nothing
  else.
  The chat shows it as a line under the failed fetch's; when the browser fails
  too, that line says both reasons and the model says so.
  A refusal is never tried again: a private address, robots.txt, an address
  nobody gave the model, and the use limit stay refusals.
  **Says where each thing came from.** An answer written from the web ends with
  a numbered Sources list, and every piece of it that came from a page carries
  that page's number, which can be pressed. Rouh's own words and Ask AI's are
  numbered by the server from the citations the API returns, never by the
  model and never aloud (`rouh/citing.py`); a card has a `sources` block and
  the numbers the model writes after its items; a job's research follows the
  statement "Sources and footnotes" in the agent instructions every run starts with
  (`rouh/agent_instructions.py`).
- **Reads what was said in a YouTube video**, with `youtube_transcript`, and
  finds videos with `youtube_search` (`rouh/youtube.py`).
  These are Rouh's own rather than Anthropic's, because a transcript is not
  on the page `web_fetch` would read: it is in a blob of JSON the watch page
  builds itself from, behind a bot check.
  So the transcript tool climbs a ladder and says which rung answered - the
  watch page over plain HTTP, then the same video asked for through YouTube's
  own phone player, which is what gets past the check on this server, and only
  then a real headless Chromium with a throwaway profile of its own, which
  presses the page's Show transcript button and reads the panel a person
  reads.
  It tells three failures apart, because they are three different things to say
  out loud: the video has no captions, YouTube blocked this machine, or the
  video is private, age-gated or gone.
  Long videos come back cut with the timestamp to continue from.
  Since 22 October 2026 (fr_5e01b7502268) every video transcribed is kept in the
  database, one row per organisation, video id and language asked for
  (`youtube_transcripts`, `rouh/youtube_store.py`), and looked up there before
  anything goes to YouTube, so any link to the same video - youtu.be, watch?v=,
  /shorts/ - is answered from the row and never transcribed twice; the morning
  brief reads from the same store.
  The line under the call in the chat says which it was: "Used the stored
  transcript of this video from <day>" or "Transcribed now, and stored".
  Rows are kept for good and nothing refreshes them; the fortnight's file cache
  that came before was not brought in.
  Search uses the Data API v3 when `YOUTUBE_API_KEY` is in the environment,
  says plainly when it is not, tells a spent quota apart from a failure, and
  falls back to reading YouTube's own results page, saying in the answer that
  it did.
  Both are quoted as somebody else's words (`rouh/untrusted.py`): a video's
  description is written by whoever made it.
- **Researches a person on LinkedIn, once you have said which one** (`rouh/linkedin.py`).
  Petar, 26 September 2026: a separate HR project on the server could already harvest a whole profile from its address; what was missing was finding the right person when all he has is a name, or a name several people share.
  `linkedin_search` takes a name and whatever else is known - a place, a company, a job title, a school - and draws the people it found as a numbered card, each with their face, name, headline, location and a link to the profile, and a Research button.
  It asks HarvestAPI's LinkedIn Profile Search by Name three times side by side and keeps everybody, because LinkedIn answers a logged-out search with a short page about half the time.
  Pressing Research harvests that person at once on the server (`card_pick`); saying "the second one" does the same through `linkedin_profile` with the card and the number; a LinkedIn address skips the search.
  The harvest is the HR project's own two scrapers, the profile and the latest posts, drawn as a card laid out like its Lookup page, and the conversation is told who it was.
  Nobody is harvested who was not picked, and a search that finds nobody says so.
  The key is the HR project's Apify token, `APIFY_API_TOKEN` in `/var/www/rouh/.env`; without it neither tool is offered.
  Each search costs about a cent and each harvest about two.
  A test world's are a stand-in, `rouh/testing/fake_apify.py`.
- **Knows who is coming to your meetings before they start** (`rouh/meeting_people.py`).
  Petar, 7 October 2026: every guest of a meeting is to be researched on LinkedIn ahead of time and kept on their profile in Synapse, face included when the contact has none.
  A pass of Rouh's own reads the next week's meetings from Google every hour, and two minutes after the Synapse calendar sync sees a new or changed invitation, and looks up every guest who is not the owner, not Rouh, not a room and not a list, and who did not decline.
  A meeting with more than 20 people invited (the owner included, rooms not), or sent to a group or list whose size Google does not give, is a training or a seminar: nobody on it is looked up or asked about, and it is said to be skipped as a large group meeting (`headcount`); `ROUH_MEETING_PEOPLE_LARGE` changes the 20, and a shared mailbox such as info@ is not taken for a list.
  Each guest is a person of his Synapse Master, found by address or made; the search is their name with the organisation behind their email's domain, and only one sure match - the name, and a headline or current job at that organisation or at a company the invitation names - is harvested, then checked again against the whole profile.
  What is kept is a short, sourced section of the person's online research (role, before, education, place, expertise, the profile's address, the day, how sure), added below anything already there and never written over the owner's own edits, and the LinkedIn photo, kept on this machine and never sent to iCloud (`/api/people/<id>/photo`).
  Anybody it is not sure of waits on their contact card with the candidates and a Research button each, and a meeting within a day asks once in Decisions (`decision_sources.MeetingSource`).
  `meeting_people` draws who is coming to a meeting from what is kept; at most `ROUH_MEETING_PEOPLE_DAILY_CALLS` (200) HarvestAPI runs a day, logged in the `meeting_people_calls` setting; `manage.py meeting_people status|run|meeting` looks and runs it now; its switch is `meeting_people`.
- **Uses a real browser for your errands, and you watch it live** (`rouh/browsing.py`).
  Petar, 24 September 2026, answering task 60's research into Meta's Muse: "for now I only want 9 - the live visual browser."
  The `browser` tool opens a site, reads the page as an outline in which everything it can act on carries a ref, and clicks, types, picks from lists and presses keys by those refs - the outline Playwright MCP reads, so a page is read here the way every background run already reads one.
  **The Live browser** is where you see it: a layer on the canvas that opens by itself when Rouh starts an errand in the chat you are in, a row in the sidebar while a browser is open, and `/browser` as an address.
  Its screen streams live, only while somebody is watching, and what Rouh is doing is written under it with a ring round the thing it is about to press.
  At a desk the page is laid out 1024 wide and drawn as tall as the box; on a phone it is laid out for the phone and drawn one to one, and a phone is offered it in a note rather than being taken away from the conversation.
  **Take control** stops Rouh and gives you the mouse, the wheel, the keys and the address bar (and a box to type into, on a phone); **Hand back** gives it back, and Rouh is told in the errand's own chat where the page is now and whether you clicked and typed - never what you typed.
  Rouh hands it over itself for anything that is yours to do: logging in, a code, a captcha, paying, and pressing the button that orders, sends, books or submits.
  A field for a password, a one-time code or a card is refused to it in code, whatever it was told.
  **Stop** closes the browser.
  Your logins are kept between errands, and only sealed in the database with the key every other credential is sealed with, one row per person keyed by the person and their organisation; **Forget them** deletes them.
  It reaches the public internet and nothing else: every connection goes through a SOCKS proxy inside Rouh that looks the name up itself, refuses loopback, the private ranges and anything else not public, and connects to the address it checked, so a page cannot talk it into this machine or its network.
  Rouh runs as root and the browser never does: it is started as `ROUH_BROWSER_USER` (nobody), inside bubblewrap with a filesystem holding the system's libraries, fonts, certificates, its own build and its profile and nothing else, and with none of Rouh's environment.
  Where Playwright's build is in /root, out of that user's reach, it is hard-linked into `ROUH_BROWSER_BUILDS` (`/var/lib/rouh-browser`) the first time.
  It closes itself after a quarter of an hour nobody has used it, an hour if you took it and walked away.
  What it does not have yet is a card Rouh cannot fake before it presses something that cannot be undone; that was idea 2 of the same research, and not wanted now.
  A test world names its own stand-in site in `ROUH_BROWSER_ALLOW`, host:port pairs the proxy lets through although they are on 127.0.0.1.
  **Which browser does what** is Petar's rule of 24 September 2026: this one for anything in the owner's own accounts, anything a person may have to step into (a login, a code, a captcha, a card, paying) and anything that ends in booking, buying, sending, submitting or signing up; `web_search` and `web_fetch` for plain reading; and a background job's own headless Playwright for everything that runs unattended - testing, reading public pages, reading many, checks that repeat.
  **A job hands a step across** (`rouh/browser_handoff.py`): a job whose headless browser reaches a login, a code, a captcha, a payment or a button that cannot be undone stops there, commits what it has and ends its turn with `LIVE BROWSER NEEDED` and four lines - the address, the step, what it had ready and what it needs sent back - which every worker's brief shows it (`one/agents.py`, `rouh/crew.py`).
  Wherever that job's end reaches Rouh - a run of the one program, a workspace job or a server job - Rouh draws a "Needs you" card with the step, even in General, marks the run as waiting on the person with the step as its question (`runs.one_run`, `runs.crew_run`), and is told to open the address here, get it ready, hand it over and, once it is handed back, send the job what it asked for with `reply_to_task`; `check_tasks` and `look_at_task` show the same, for when the person comes back to it later.
  The live browser does not share the job's logins, so a job asks to be sent what it needs to know, never for a session, and none of the rules above loosen: Rouh still never types a password, a code or a card, and never presses the button that books, buys, sends or submits.
- **Makes a morning brief** (`rouh/morning_brief.py`, `briefpage.js`).
  Petar, 29 September 2026 (fr_c01a16e51a05): "Make a morning brief please ... Calendar is primary importance ... Important piece of world news. Weather ... Figure out where I will get it."
  Then the same day (fr_a2b5a77d76b3): "Move the weather on top. I only need two days calendar - today and tomorrow. For world news make those 3 pieces, the most significant. For ai news, please scan YouTube videos from my favorite channels ... Transcribe and then crunch for 3 -5 items".
  One short page, **Morning brief** at the top of the sidebar's second group and at `/brief`, in this order: today's weather from Open-Meteo (no key); today's and tomorrow's events from Google Calendar and nothing further out, each day saying so when it is empty; three stories from BBC News' world feed, the three the default model judges the most significant of the whole feed (the newsroom's first three when no model can be asked); the AI news, which is each new video since the last brief from the person's YouTube channels (Matt Wolfe, Matthew Berman and The AI Grid until changed; Shorts left out), its captions fetched (`rouh/youtube.py`), and the lot condensed by the default model into three to five items, each naming its channel and linking to its video; then the inbox's unread mail since yesterday and today's reminders.
  The weather, calendar, inbox and reminders are what their source said; the world stories are the feed's own words, picked; the AI items are the model's, each tied to its video. A source that cannot be reached, or transcripts that cannot be fetched, is a line saying so, with the videos listed to watch.
  It is made at the person's time every morning (07:00 on their own clock until changed) and kept one row a day (`morning_briefs`). Opening the page never makes one: it shows the newest brief there is at once, before seven yesterday's, saying so, and says plainly when there has never been one (fr_e7c51081dc50). **Update** reads every part again and does the work of a model again only for what is new since the brief before: a meeting already worked out keeps What to raise, world news with no new story keeps its three, videos already condensed keep their items and only new ones are read, and today's history is kept; it then says which parts changed, or that nothing had.
  For the person the Telegram bot reaches, the morning one is also sent to the phone as a few lines and the link, once a day (`sent_at`), and not at all if it is more than three hours late.
  **Settings**, under **Morning brief**, turns it on or off, sets the time, the place for the weather (none until set, looked up by name) and the YouTube channels for the AI news (a handle or a link a line, looked up on YouTube).
- **Does things at a time, and works out and does your goals** (`rouh/reminders.py`, `rouh/goals.py`, `rouh/timekeeper.py`).
  Petar, 26 September 2026, answering task 60 again: "1 is not very valuable. maybe I have to see how it works ... 4 I can't see it working ... Fine - please implement 1 and 4. think carefully about the interface that should be visible and easy and friendly".
  Ideas 1 and 4 of the Meta Muse research: until this, "remind me on Friday at nine" had nowhere to go, and nothing followed a personal aim past the chat it was said in.
  **Reminders** are two kinds of thing done at a time, once or every day, weekday, week (on chosen days) or month: a **reminder**, where Rouh says what you asked to be reminded of, and a **job**, where Rouh does a piece of work then - reads your inbox, your calendar, the web - and says what it found, or nothing at all when there is nothing new.
  At the time it is said in the chat it was asked for in, as a turn of Rouh's own started by a note, spoken when you are standing in that chat with spoken replies on, and sent to your phone through Telegram with a link back.
  A turn nobody asked for just now runs with nobody watching. Since 5 October 2026 it may do whatever the person would ask of Rouh - send mail as Rouh, change the calendar, share and write in Drive, publish, steer runs - except three groups, which are neither offered to it nor callable from it (`rouh/protected.py`, the one list, read in `ToolRegistry.definitions` and `call`, and imported by anything else that starts such a turn):
  money and commitments (the live browser reads, navigates and fills in, and stops at the press that pays, buys, books, submits or signs up, hands the browser over and tells the phone), permanent deletion (binning mail or a Drive file is fine), and Rouh's own guardrails (changing Rouh, this server, its models, or its own rules and permissions, answering a run's permission question, or starting a run aimed at Rouh's own code).
  Everything it did outside Rouh is said by the code after the turn, in the chat and on the phone (`reminders.Handling.did`).
  Sharing and giving a trusted contact authority are not guardrails since 11 October 2026 (Petar: "I will be asking you many times in the future to do a chain of actions that only the last one might be sharing and it may be the result of clockwork").
  Every row keeps the person's own words that asked for it (`Reminder.asked`): what they typed on the Clockwork page, or their own messages in the chat a turn of theirs scheduled it from, never Rouh's words, an email's or a tool's.
  The note a row's turn starts with quotes them, and on them alone that turn may grant, revoke or undo with `delegate` (`ToolRegistry._delegate`, `DELEGATION.md`); a row with none, such as a goal's step, gives none, and a heartbeat beat never may.
  A row may be made for a trusted contact under their Clockwork grant (Petar, 11 October 2026, `rouh/grants.py`): it carries them as its owner (`Reminder.owner_contact_id`), which is the only sign it is somebody else's, and the page, `upcoming` and the morning brief say "For <name>" on it.
  Their grant reaches only the rows they own (`clockwork_for_contact`), and such a row's scheduled work, when it comes due, is told it is theirs, held to their grants, with nothing sent as the owner (`reminders.note_for`).
  A row that fell due while Rouh was down is said a few seconds after it comes back, late and saying so; the loop sleeps until the next row is due, at most thirty seconds, and wakes the moment one is added or changed.
  **Goals** are something you want to reach and want help working out how to, since 27 September 2026, when Petar put in his first real one and found the page was built around counting and check-in reminders: "Goals should be mostly about designing the plan and action and analyzing difficulties and who will do them and how and helping with the difficulties."
  A goal is one numbered task tagged Goal (`"tags": ["goal"]` in its meta), filed under a project like any task, with what you know about it in its `goal.md` and a chat of its own that the task owns.
  You give it a short name and everything you know; Rouh reads it in that chat and asks what it needs to know, including why this is a goal you need help with rather than something you would just do.
  Then it writes the plan with `plan_goal`: the steps as the task's steps, and a big step's parts as that step's steps, each with who does it (Rouh, you, together, or somebody named), how, what is hard about it and what to do about that (a `goal_step` block in each step's meta).
  Every step Rouh can do can be done **now** (a turn in the goal's chat), **at a time** (a job of kind `do` in that chat, which runs unattended like any job), or **after another step** is marked done, which starts it by itself (`timekeeper.step_status`); `goal_step` marks steps done, waiting or started and changes any of it.
  The goals are in every turn's prompt in a line each, and a turn in a goal's own chat is told the whole goal: what you wrote, why it needs help, and the plan with every step's id (`goals.block`).
  **The two pages** are layers on the canvas, `/reminders` and `/goals`, opened from two rows at the top of the sidebar that are there whichever list is showing and say the next reminder's time and how many goals there are.
  Reminders lists what is coming up by Today, Tomorrow, Later, then Paused and Already said, each with when, what, how it repeats and what happened the last time; **Try it now** says one straight away, leaving its time alone, so what it does can be seen; the three dots edit, pause and delete. It says what it is for and gives four things to say, which go into the message box when pressed, and has a short form.
  Goals is a **list**, since 27 September 2026 (fr_b7586f638301): a row per goal with its name and its deadline if it has one, and beside it at a desk, under it on a phone, how it works and four examples. **New goal** is a page of its own - a name and a large box for everything you know - and it is where Goals opens when there are no goals, so an empty list is never shown. Saving makes the task and opens its chat, where Rouh is already asking, with the goal's own task page beside it.
  **A goal lives on its task, on a page of its own.** The task's page is a list like any task's - its chats, then **Goal**, one line that says where the goal stands and how many streams need you, then its subtasks - and pressing that line, or a goal in the list, opens the goal's own page at the task's `goal.md` (`objectindex.goal_page`, drawn by `rouh/static/goalpage.js`; fr_b083c37a634d). Under progress and the deadline is the **map**: one row per stream, listed down the left, its steps flowing left to right in the order they follow one another, and the step a stream waits on you for (your decision or your action) in amber. There is no separate list of decisions and no column of stream ends at the right (fr_ddae0c0dac24): what needs you is the amber step on the map. Pressing any step opens it under its row in four plain blocks (fr_e2dde690a576): its title; **Rouh** and **You**, a row each with an icon for how that part stands (to do, doing, done, or blocked when Rouh needs you to go on), what it is in a line, its parts, and a link to the step's **explainer**; the buttons - Mark complete, Not yet, Talk it over, or for any step Do it now, Change first, At a time, After a step, Mark complete or Reopen; and **How**, **Hard part** and **What to do** as a word each, whose paragraph shows under a pointer resting on it, or a press or a tap. The explainer is a page, never a Markdown file: at the step's folder with `?doc=explainer` it is drawn fresh from the step (`objectindex.step_explainer`) - what Rouh does, what it made (its `step.md` drawn, its other files), what you do, **Where** (a step's `where`, from `plan_goal` or `goal_step`), the steps to take and when it is complete - and an `explainer.html` Rouh wrote into the step is used instead. A link to another site in any framed page opens in a tab of its own (`pages.follow_script`, `frameOut` in app.js), which the sandbox would otherwise refuse. Streams are kept in the goal block (`goals.STREAMS`); a plan nobody has split is split by Rouh the moment its page opens, so everything that can go on at the same time does, each stream ending where it needs you (`goals.split`, with `goals.split_guess` when the model cannot be asked), and **Split it again** does it on purpose. A step is dragged by its handle, or moved with the arrow keys on its handle (left and right along its stream, up and down to the next), onto New stream too; a stream's name is pressed to rename it (`goals.arrange`). **Let Rouh go**, under a stream's name, or **Let Rouh do all it can**, starts the stream's next step and sets Rouh's steps straight after it to follow, so it carries on until something needs you (`timekeeper.let_go`). Rouh may name the streams itself when it plans (a step's `stream` in `plan_goal`), moves a step with `goal_step`'s `stream`, and is told the plan by stream. On a phone each row is a column. Every press goes up to Rouh (`taskGoalMap` in app.js), which finds the goal from the page it framed, and the page is drawn again in place from the goal as it now is. A deadline is optional, a day in the goal block, set there or by Rouh with `set_goal` or `plan_goal`.
  When Rouh adds one in the conversation you are in, the page opens beside it at a desk, with the new row lit for a moment, and a phone gets a note with Open instead of being taken away from the conversation.
  Every reminder carries the person and their organisation, and every query names both; a goal is a task of the workspace like any other.
  The server works out every word and number both pages draw, so the page and the voice say the same "3 of 8 steps done".
- **Delegates.** A real job goes to Claude Code running in a tmux window in its
  own git worktree, and Rouh can then read that worker's terminal, read its
  log, answer a question it is asking, and stop it.
- **Updates itself.** It can change this repository, push, and redeploy, with an
  automatic rollback if the new version does not come up healthy. A change to
  its own code made by a run of the one program is deployed the moment it is on
  main, with nobody asked (`rouh/one_jobs.py`), and what was pushed and what
  was deployed are both put on the screen.
  A deploy is both services on this machine, not one: `update-all.sh` puts the
  one program and Rouh on the same commit, the program first because
  restarting Rouh takes away the process that asked.
  The card on the task list for that deploy is the one thing on it that cannot
  report its own result, because the process that started the update is the
  process the restart kills, so the deploy writes itself down and the next
  Rouh to start finishes the card (`rouh/self_update.py`).
- **Is the voice of the one program**, which runs beside it on the same server
  (see below): it can list that program's runs, start one, say something to one
  that lands at that run's own prompt, read its screen and its log, stop one,
  answer a question one is waiting on, and take or hand back a run a terminal
  watches.

## One kind of running work

There used to be three notions of a running thing here, kept in three places
and read in three more, and they disagreed with each other all the time: a
background worker was a row of `crewmates` in `crew.py`; a run of the one
program lived in that program's list, on the far end of a socket; and a
sub-agent inside either was written down nowhere at all - it existed only as a
node the work tree derived from a stream of hook events, so it was on the orb
and on no list.

They are one thing now, and it is a row of `run` in `rouh/objects.py`. What
told them apart is two columns rather than three models:

* **`workspace`** - where the work belongs: the checkout a job works in, or
  the space a run of the one program works in.
* **`policy`** - under what rules it works: `yolo`, `auto`, `safe`, `self`,
  `local-only`, `direct-pr`, or `one` for the one program's own rules, where
  every tool call is decided by `one/rules.py` rather than by a permission mode.

`state` is one of five words - `running`, `waiting`, `done`, `failed`,
`conflict` - with `question` set while it is waiting, and a sub-agent is a run
with `parent_run_id` set. That column is the only reason the orb can draw a
helper as a branch off its parent rather than as a spike of its own.

**The database is the source of truth.** The worktrees, the logs, the branches
and the tmux windows are a supportive structure written out from it, never read
back in as the truth. Where the two disagree the row wins, and what is on disk
is an inbound change to reconcile into the row: that is why reading a worker's
screen writes what it found back into its row instead of leaving it on a screen
for whoever looks next.

One register, read three ways, so they cannot disagree again: `runs.rows` is
the task list and `check_tasks`, `runs.describe_one_runs` is `one_runs`, and
`runs.tree` is `what_is_running` and the orb. Three things are still read
somewhere else, and each is deliberate: a running worker's screen, for the
question it is asking; the tool calls inside a run, which are steps rather than
runs and come from that run's own hooks; and whether a terminal has a run open,
which is a fact about a terminal.

`ROUH_OBJECT_MODEL_ENABLED=0` stops the register answering. It does not put
anything back on an older path: there was one until step five, the two lists
the task list used to be stitched together from, and it is deleted. Two ways of
answering "what is running" is the exact thing this model exists to be rid of.
The conversations are the one thing the flag does not cover: they have lived in
`objects.chat` since step three and have nowhere else to be, and a flag that
hid a person's chats would not be a safety valve.

## A conversation is a row, and a numbered task owns it

A thread used to be matched to a piece of numbered work by its name: a chat
carried the string `tasks/30.jarvis`, and thread "30 Jarvis" and that folder
were the same thing because the two names lined up. Rename the folder and the
thread was about nothing; number a second thread the same way and two rows both
claimed to be task 30.

Since 21 September 2026 a conversation is a row of `objects.chat`, a piece of
numbered work is a row of `objects.task`, and one row of `objects.link` with
`rel='owns'` on it ties them together. There is no name matching left anywhere,
and the partial unique index `link_one_owner` means it can only ever be one
chat. `rouh/conversations.py` is the whole of it, and this is what it does:

* **Loose chats stay out of the numbered work.** A chat nobody has promoted has
  no owner, no number and no folder on disk at all, and it lives in a list of
  its own ordered by when it was last spoken in. Most conversations are one
  question and an answer, and fifty of those a week must never become fifty
  numbered tasks.
* **Promotion is the person asking for it, and nothing else.** The item in the
  chat menu, the `make_a_task` tool when they say so out loud, and no third
  thing: a run started in a loose chat leaves it a loose chat since 22
  September 2026, and carries only the `from` link saying which conversation
  asked for it. Promotion takes the next free number, keeps every message, and
  carries what it owns and the project it was filed under with it - its cards
  go in as its numbered steps. General is never promoted.
* **A project said out loud is where the task is made.** "Put those in a new
  task, Messaging, part of Acme" hands `make_a_task` the project as it
  was said - Acme, Health, or a path like `work/acme` - and the
  task is made inside that project's folder from the first moment, owned by it
  in the link table and drawn under it in the task browser. Until 24 September
  2026 it was made in `unfiled/` and moved a minute later by the filing model,
  which is how task 61 ended up moved on the server and still in `unfiled/` on
  main. The name is matched against the projects that exist (`filing.find`):
  one that fits none, or two, or names a column rather than a project, makes
  nothing and is said back to the model with the list, so it asks rather than
  guesses. `move_task` puts an existing task into a project the same way, and
  refuses while a job is still running in it, because the job's checkout says
  the folder is where it was. A task placed by the person is never re-filed by
  the model, even into Miscellaneous.
* **Nothing deletes a chat but a person.** A conversation goes when somebody
  deletes it and at no other moment: there is no expiry clock, no archiving on
  a clock and no sweep anywhere in Rouh. Until 22 September 2026 a loose,
  unpinned chat was archived after thirty days of quiet and deleted after
  ninety by `ChatSweep` in the server; the person's answer was "Remove deleting
  chats at 90 days. No automatic removal", and the sweep, its schedule, the
  `expires_at` column and the query behind it were taken out rather than
  switched off. Keeping a chat is still here and is now a mark and nothing
  more. A person's own delete does cascade, and says what it will take before
  it takes it.
* **The database is the source of truth.** A task's number, slug, title and
  state are columns of its row, and `tasks/NN.slug` in the workspace is written
  out from them. A folder nobody has a row for is taken in as one, a folder
  somebody renamed hands its change to the row, and a row whose folder is gone
  has it written again. The file is an inbound change to reconcile, never an
  override.

### Talking about a task

Every task's and every step's own page has one chat button, **Start chat**, floating in its bottom right corner, and nothing else on the page offers a chat.
Pressing it always starts one: an empty conversation about the task, beside the page with the cursor in it, and on a phone the conversation's pane.
While nothing has been said about the task it is the task's own conversation, the one opening the task opens; once something has, it is a new chat filed under the task, named from what is said in it (`conversations.start_for_task`).
Pressed again before anything is said, it is the same empty chat.
A step's page starts a chat about its task, because a step is talked about there.

Petar asked for a way to start a chat about a task from its page on the afternoon of 23 September 2026, and that evening there were two, a big button under the task's name and the floating one, both saying "continue": "i don't need a button to continue chat, I need a button to start a chat. and I don't need 2 places on that scren. bottom right is good enough".
So the button under the name went, and the one that stayed never goes back into a conversation with something in it.
The chats a task already holds are listed on its page under Chats, and its own conversation is still what opening the task and its number said out loud bring back.

The other half is the head of the conversation.
A task's chat is headed with the task's mark and **Task 30 · Jarvis ›**, and pressing it opens the task's own page beside the chat.
Nothing is written until the first thing is said: the chat is a draft until then (`conversations.open_draft`), and its empty screen says whose chat it is.

A task has one conversation of its own, because that is what the rest of Rouh already means by a task: it is what opening the task opens, what "thirty" means said out loud, and what `/task/<folder>` brings back.
Any other chat under a task, one Start chat began or one put there with **Move** on the chat's three dots, is listed under Chats on the task's page, keeps its own title, and is addressed as `?chat=` beside the task's page, since the task's address alone brings back the task's own.
A task's chats were on the sidebar's Chats list as well, under their own names, with the task's number at the end of the row, from 24 September 2026 until that list went on 30 September 2026.
Now a task's chats are on its page, and Search finds any of them by name or by what was said in them.

## Starting work, and what belongs to what

**There is one call that starts anything** (`rouh/starting.py`). There used
to be four - `assistant_job`, `delegate_task`, `improve_myself`, `one_start` -
and four code paths behind them, and the four paths were the same path. Every
one of them is Claude Code doing a job; what actually differed was the two
columns above. So the four names stay on the surface, because the spoken model
routes with them and the person must never be asked to choose between them, and
each is a preset over the one call: a workspace, a policy, and whatever is
genuinely its own - the assistant's brief composed into the workspace's words, a
change to Rouh landed with `land.sh`, a job on this server (with sudo only where the machine gives it, and none in the
containers, `one/briefs.py` `machine_words`) -
as a field of that preset rather than as a fourth code path. The policy is also
what picks the transport, because the policy *is* the difference: `one` is the
one program's own rules and so is a run of the program, and anything else is a
Claude Code permission mode and so is a worker here.

**Everything is made on its own and owned by nothing, and that is the default
rather than a half-made state.** A run can be started from the interface with a
brief, a workspace and a policy and belong to nothing; a chat is made on its
own; a task can be made on its own, with no number, in no project and in nobody's
workspace. What changes is `objects.attach`, one upsert, the same operation for
every pair the ranking allows - project > task > chat > run > artifact - with
at most one owner enforced by a partial unique index rather than by whoever
remembers to check. `rouh/owning.py` is where the rest of Rouh reaches it.

Attaching moves nothing. A run's diff is an artifact the run owns and made, so
attaching the run to task 30 puts its diff, its artifacts and its cost under
task 30 because they were the run's all along, and detaching takes them back.

**A run outlives the chat it came from.** Which conversation asked for a run is
a `from` link, which is a reference and never a hold: deleting that chat takes
its messages and leaves the run, its diff and its cost exactly where they were.
**Ownership is the opposite, and is followed.** Deleting an owner deletes what
it owns, all the way down - so a card the chat owned goes with the chat, while
the run it merely started does not. That is the whole of the difference between
the one relationship that is ownership and the three that are references.

### When the person asks to be emailed about a job

Delivering that email stays Rouh's obligation, and the job only queues the text (`rouh/outbox.py`).
A background job cannot send mail, whichever preset started it and whichever transport ran it, and every reason for that stays exactly as it is.
It has no Google token: `google_store` seals the access and refresh tokens with `encryption.SecretBox` and never hands them out.
It may not read the server's `.env`, which holds the database login and the encryption key.
This machine has no mail transfer agent, and `send_mail` exists only in Rouh's own turn loop.

So every agent on this machine is given one tool of Rouh's, `notify_owner(subject, body)` (the old name `notify_petar` is still accepted), by the `rouh` MCP server in `mcp-servers.json` (`rouh/worker_mcp.py`).
It posts the two to `/internal/outbox`, which only this machine may call, and Rouh writes one pending row into `worker_outbox`, tagged with the job's own id.
That id comes from the environment the launcher set, `ROUH_JOB` for a worker of the crew and `ONE_RUN` for a run of the one program, and never from anything the model wrote.
When the job's report reaches the conversation it was started from, its pending notes go inside that report, with their subject, their body and their ids, so Rouh has the text in hand in the same turn.
Rouh then says who it would go to and the gist, and on the person's yes sends it with its own `send_mail` and marks the row sent with `worker_outbox`, the small tool on Rouh's side that lists what is waiting and marks a note sent or dismissed.

Three things a note can never do.
**Choose where it goes:** there is no recipient anywhere in the path - not a column, not an argument, not a field the endpoint reads - and the address is the person's own, worked out by Rouh at the moment it sends, from what they asked it to remember as their email address, then their Rouh account's email, then the Google account they connected.
A job that has read a hostile page can put words in a note, and those words reach Rouh boxed as a job's words (`rouh/untrusted.py`); it cannot make Rouh mail a stranger.
**Send itself:** a queued note is a request to send, never a send, and nothing is sent without the person hearing who and what and saying yes.
**Be marked sent by anybody but Rouh:** the one door a worker can reach writes pending rows and nothing else, and `worker_outbox` only marks a note sent for a message `send_mail` really sent, from this process, to the person's own address.

### Rouh's tools for every background job

Petar, 25 October 2026: background jobs kept stopping when they needed something only Rouh has - a login, an integration, a tool - and each gap had been given a fix of its own, the last two tools for files out of mail (fr_e86680eb9365).
"Okay implement that now": one gateway, one permission check, and a way to ask for the rest.

**One gateway.** The same `rouh` MCP server every job has (`rouh/worker_mcp.py`) asks Rouh, at `/internal/jobtools` (this machine only, with the job's id from its launcher's environment), which tools this job has, and lists them; each call is posted there by name.
Rouh's own code runs it through the very tool registry a chat turn uses, with Rouh's own logins, so a job never holds a login, a token or a card (`rouh/job_gateway.py`).
No model of Rouh's sits in a plain call: the job's own model, on its own subscription, reads the answer.
What only makes sense in a live chat with the owner is never listed: the screen and the canvas, the orb, boxes and thoughts, and what answers for them (decisions, a run's permission question, a conflict's pick, who decides for them), and what would have Rouh's own model do the work.

**One permission check**, in code and never a model: `job_policy.decide`, on whom the job works for and the tool's class, both written out as tables in `rouh/job_policy.py`.
Whom it works for is decided from the run register, walking up the runs that started it: a trusted contact's job reaches only that contact's conversation and its files; a job one of Rouh's own processes started (the heartbeat, quests, the nights) reads what a beat reads, Rouh's own inbox and never the owner's; a job from the owner's own words reaches what the owner's own turn reaches.
A read runs at once within that scope.
A write inside the job's own work runs: a draft, a private file nobody else is given, a calendar event with nobody else on it, an email kept in a task.
Anything risky - sending, forwarding, sharing, publishing, paying, binning or deleting, contacts, other people's calendars, Rouh's own settings, models, rules and code, starting or steering other work - never runs on a job's call.
It is queued once, as an entry of the heartbeat's approval queue, which is the Decisions page's own approval path: on the owner's yes exactly what was queued runs and nothing else, and the job that asked is told the answer at its prompt if it is still running, or reads it with `request_status`.
The same call asked again, by any job, waits on the one decision.
Where a standing rule already lets it go - mail from Rouh's own inbox to the people of the quest a beat started the job for (`heartbeat._mail_refusal`) - it goes, as the beat's would.
A tool that is in no table is risky: it fails closed.

**"Rouh, I need X."** For what no tool gives, a job calls `request_from_rouh` with what it needs, why, and what it does meanwhile, and carries on.
That alone asks a model, on its own pick on the Models page ("What a job asks Rouh for", Cheaper), through the LLM service: whether a tool the job already has does it, whether only the owner can give it (one decision, shared by every job that asks the same gap), or neither.
Every such ask, and every call that waited on the owner, is a row of `job_requests` with its job, scope, outcome and cost, and Metabolism lists them by gap, the most asked first, in a brown toggle, "What jobs asked Rouh for".

**Files out of mail** are two of the gateway's tools (`rouh/job_mail.py`).
`mail_find` takes a Gmail search and lists the emails it finds, each with its id and its files (part, name, kind, size).
`mail_file` takes an email's id and a file's part or name, and saves the file, exactly as it was sent, into the job's own working folder; a path outside that folder is refused, and a file already there is not written over unless asked.
When a file cannot be had, the job is told the true reason, such as Google having withdrawn the connection or the email not being in the conversation it may reach.

### Notifications: the screen first, the phone if it is left

Petar, 10 October 2026 (fr_8f09d161935f): "you first give me a notification, and I can look at it and dismiss it. If not, I also get a Telegram notification."
So everything Rouh used to send straight to Telegram on its own initiative is a notice first (`rouh/notices.py`, table `notices`): a job that finished or needs him, a reminder, the morning brief, a note before a meeting, an email's note, an urgent decision, a landing's conflict, the heartbeat's messages, a card filled, and the `send_telegram` tool unless he asked for his phone in so many words (`straight_to_phone`).
It drops in at the top of every open tab of his, iOS style (`app/notices.js`, `notices.css`); more than one stack.
Swiped left it is dismissed, swiped right it goes where it leads (and nothing happens when it leads nowhere), pushed up or Later puts it away; a tap opens the column of all of them, and a tap in the column opens one in place, with the decision it asks drawn inside it.
Going where one leads - its button, a swipe right, or a link inside the decision it asks - dismisses it in the same press, on every screen, so it is not waiting under the bell afterwards (fr_a7c05457e6a3).
The bell at the right hand end of the person's own row, at the foot of the sidebar, opens the same column, with how many are still to read; with the sidebar folded its button carries a dot, and on a phone the orb's circle does.
Left untouched for `notices.GRACE` (45) seconds its Telegram copy is sent, with the same link, and the card says so; drawn by no screen at all within `GLANCE` (8) seconds it is sent at once.
Anything done with it on the screen keeps the phone quiet.
What never went to the phone still does not: a finished job is on the screen only, unless `ROUH_PHONE_DONE_JOBS` says otherwise.
The waiting is a row, so a notice said just before a deploy is sent by the Rouh that comes back (`notices.Sweeper`).
Opened, a notice says all of it (fr_70b1c378cc0e: "in full with ellipsis ... that is not in full"): a finished job's notice keeps every word the job closed with, drawn as markdown, while the phone's copy stays a line or two; a card that shows only the first three lines says See more where they stop.

A tab a deploy left behind says nothing of its own about it: the finished run that put the new build live carries a Reload on its notice. The page's own "Rouh has been updated" notice (a bar until 10 October 2026, a notification until 13 October) is gone at Petar's asking (fr_ee6b8d91a861).

## Finding any of it again

One box over the whole screen, from the glass beside your own name at the foot
of the sidebar or from Cmd+K, or Ctrl+K, anywhere - including inside a task
page loaded on the canvas, which takes the whole window and holds the keyboard
inside its frame (`pages.FRAME_KEYS`).

**One list, not five.** `rouh/searching.py` asks all five tables at once
through `ObjectStore.find` and ranks them against each other, because somebody
looking for "migration" wants the chat, the task and the run called that. The
pills under the field - All, Chats, Tasks, Projects, Artifacts, Runs, Files -
narrow what has already come back rather than asking a different question, so
pressing one is instant and each carries how many are behind it.

**Nothing is indexed for it.** The words already exist and are asked where they
live: a chat is its messages, a run is its brief and the line it is showing, an
artifact is the body of its head version, and a project and a task are the
files in their folders, through the derived content index the task browser is
drawn from (`content_file`, and its PostgreSQL full-text vector, `content_file.search`).
A sixth copy of the same words would be one more thing to drift. On this
machine that is about a thousand names, two megabytes of messages and bodies,
and nineteen megabytes of files behind FTS5; a search answers in about twenty
milliseconds.

### Files the person uploaded

Petar, 24 September 2026: "the files I give it are not searchable. The uploads that is. The should be extracted in Md and those mds should be searchable but also not show Md, show original file".

A file sent in a chat message, added to a project with its Add files button, or uploaded to a task or a subtask with Upload on its own page, is found by the words in it, under the Files pill, and opening it opens the file itself.
A task's files are also named, with where they are on disk, in every turn of a chat about that task, and a subtask's chat hears its parent task's as well (`objectindex.files_block`).
It is the one thing search reads that is a copy, because the words in a PDF or a .docx are locked inside it until something reads them out.

- **Reading** is `rouh/extracting.py`, run as a process of its own per file (`python -m rouh.extracting <file>`), with a two-minute limit and a one-gigabyte memory ceiling, so a PDF that never finishes or a spreadsheet that unzips to gigabytes costs that process and never Rouh.
  It reads PDF (with `pypdf`), Word, Excel and PowerPoint, OpenDocument, HTML, RTF and anything that is text.
  A picture, a recording, an archive and the old binary Office formats are found by their names only; there is no OCR on this machine.
- **The Markdown is kept beside the original**, as `.extracted.md` in the file's own attachment folder, a name no upload can have.
  It is never shown to anybody.
  It is also what the model is handed for a .docx, a spreadsheet or a deck, which until 24 September 2026 it was told it could not open.
- **The index is `uploaded_file`**, a row per file with the same PostgreSQL full-text vector `content_file` keeps, so a word means one thing in both.
  It is derived: on every start `uploads.catch_up` takes in any file that was given and has no row, and drops the row of any file taken off a project or given to a chat or a project since deleted.
  The first start after this landed is what took in everything uploaded before it.
- **Only what was given is found.** A chat's files are taken in when the message carrying them is sent, not when they land in the composer, and a file whose chat or project has been deleted is never found.
  The Gene therapy drawer's files belong to the Gene therapy board and are never in it.
- **Reading starts on upload**, on one thread of its own that takes the files one at a time, so by the time the message is sent the words are nearly always there; a sent message waits up to eight seconds for the words of a file the model cannot open itself.

A file's row is its own name, a few of its words round the match with the Markdown's marks taken out, and the date it was uploaded; a picture, which has no words, says which chat or project it was given in, and the tooltip says it for every file.
Its menu is Open and Open in new tab and nothing else, because a file is not one of the five: there is nothing to pin or rename, and it has no address but its own.
Open does what a press on it in the conversation does, decided by `attachments.serving`: a picture opens in the viewer, a PDF or plain text in a tab of its own, and anything else is downloaded.

A result is one line: the type as a glyph, the name, a little of what matched
cut with an ellipsis, and the date it was last worked on. Hovering one - or, on
a phone, simply having it on the screen - shows the three dots and an enter
sign at its right. The menu behind the dots is Open, Open in new tab, Pin,
Rename and Delete, numbered 1 to 5, and those numbers are live keys while the
menu is open. The arrows move the highlight, the right arrow opens the menu,
Enter opens the row and Escape closes the menu and then the box.

**How each of the five opens is decided on the server**, in `searching._open`,
so the browser keeps no copy of the rules to fall behind: a chat is opened, a
task or a workspace project is its folder on the canvas, a step is the page it
built, one of the person's own projects is the projects dashboard, an artifact
is the step it was filed as or the card itself, and a run is its row on the
task list. "Open in new tab" is that object's own address, below, which the
new tab hands back through `find_object` to get the same instruction a result
row carries.

**Delete goes down the one delete.** The row's Delete opens the same dialog
every cross on the page opens: the thing named, what else goes with it counted
by the server off the links the delete walks, and a button that stays disabled
until that sentence has arrived. There is not a second delete for search
results, and a search result cascades exactly as the cross beside the same
thing in the rail does.

Pin means the same thing on all five: a mark the person sets, and nothing more,
because nothing here is archived or deleted on a clock. `project` and `run` got
a `pinned` column on 22 September 2026 so that they could carry it too, rather
than the menu offering a word that meant nothing on two of the five.

## Everything has an address

Rouh is one document, so every screen of it used to be one address: `/`. A
chat opened, a task read, a project browsed and a run watched were all `/`, and
so none of them could be sent to anybody, bookmarked, opened in a second tab or
reached again with Back. Since 22 September 2026 each of them has an address of
its own, and `rouh/addressing.py` is the whole of the scheme:

```
/chat/<id>                          a conversation
/task/work/acme/19.pricing          a task, or a step of one
/task/work/acme/19.pricing/19-01.research/notes.md
                                    one of its notes, a folder, a code file
                                    or a page it built, by its path
/project/work/acme                  a project
/run/<id>                           a run: Read, its transcript as a page,
                                    or Terminal, its terminal (card 723)
/artifact/<id>                      a card, read by itself
/tasks                              the task browser, with nothing opened
                                    out of it yet
/browser                            the Live browser: the browser Rouh
                                    uses for errands, live
/reminders                          everything Rouh will say or do at a
                                    time
/goals                              your goals, a list; each opens its own page, inside its task
/p/<token>                          one page of the workspace, made public.
                                    The only address here that answers
                                    somebody who is not signed in
```

**A card opens on a layer of its own over the canvas**, with its name at the
top, its blocks under it and a cross that puts the reader back on whatever they
opened it from. That layer is what `/artifact/<id>` has meant since 22
September 2026, and until then the address named a thing nothing could show.
Petar found it on the artifacts listed on a task's page: "when I click on any
of the artifacts. nothing happens. just blinks and nothing happens." Every card
on a task's page is owned by that task, and what a click on one asked for was
"open whatever owns this" - so the answer was the page he was already looking
at, fetched and framed a second time, which is the whole of what the blink was.

**Two of them name a place rather than an object.** `/browser` is the second, the Live browser, for the same reason; the first is the task browser's top.
The task browser's own top - both columns, every project, nothing opened out of
it - is somewhere a person can be and stay, and it is not any one object: Work
and Personal are two top-level projects and it is the both of them at once. It
had no address until 22 September 2026, and what that cost was not a missing
link. With nothing of its own to say, the bar fell through to whatever was
underneath, which is the conversation - and the rule two paragraphs down means
a conversation a numbered task owns carries that task's address. So pressing
**Task browser** after reading task 19 left the bar saying
`/task/work/acme/19.pricing` over a screen showing the whole workspace: it
named something you had walked away from. It is plural where a task's address
is singular; it takes `?chat=` beside it like any other path, so a conversation
opened next to the browser is in the link too; and it is the one address the
page acts on itself rather than asking the server what it names, because there
is no row to look up.

**An object is addressed by its own name.** A task and a project are named by
their folder, because that is what they are called in the workspace, in git, in
the breadcrumb and in the canvas's own address; a chat, a run and a card have
no folder and are named by their id, which is the only name they have. One
rule, not two. Reading one back is the same rule in reverse, and a name that
matches no folder is tried as an id as well, so a task that never had a folder
is still reachable.

**What is inside a task has an address too, and it is its path.**
A task's page lists its subtasks and what is directly in its folder - its `.md` files, its `source-code`, the page it built - and a subtask's page lists the same one level down; every line of it opens on the canvas.
Until 23 September 2026 none of those had an address, so the bar stayed on the task, Back could not undo one click inside it, and the only way out was the close button, which shuts the whole task.
Petar: "if I click on folder or notes, the url doesn't change, so I can't go back ... urls should change on every click."
So the name goes on downward: `/task/work/acme/19.pricing/19-01.research/source-code/research` is that folder, and a note in it is the same path with the note's file name on the end, which is also what the eyebrow over the note says.
Read back, a name that is not itself a task or a project is the deepest one it starts with, and the rest is a path inside that one's folder (`addressing.inside`).
A page opens as itself and anything else is read on that object's page, exactly as the press on its line did, and Back and Forward walk through them one press at a time.

**A conversation a numbered task owns is addressed as that task**, because the
two are one object and not two that can drift - the same rule the rail keeps
when it names such a thread after its task. **The canvas follows the
conversation** for that reason: being in a task's thread means having that
task's page beside it, and opening a loose chat takes off whatever page was
loaded, because that page belongs to something else. The rail had always done
this when a thread was picked in it; it is `onChatSwitched` now, so it is true
however the chat was opened - from a list, from a link, from Back, from the
phone, or out loud - and it is what lets one address say both which
conversation you are in and what is beside it.

**The middle of the screen is two panels, and an address names both.** The
conversation is one and the canvas is the other, and they are often two
different things - a run watched beside a chat, a project's page read beside
the conversation you are in. So the conversation goes on the end when it is
not already implied:

```
/run/25d54848?chat=chat-9f2a1b3c   a run, and the conversation beside it
/project/work/acme?chat=…          a project's page, and the conversation
/task/work/acme/19.pricing         one thing: the task's page and the task's
                                   own thread, which is the same object twice
```

It is only there when there is something to say. A task beside its own thread
is one object; a step beside its task's thread is the same; a page browsed
with the conversation folded away is one panel. This was wrong for a few hours
on 22 September 2026 - the bar said `/run/42e4cff6` and said nothing about the
chat two inches to its left, so the link brought the run back beside whichever
conversation happened to be active.

**Navigation is still not in an address.** There is no `?panel=`, no
`#sidebar`, no `&pane=`. `chat` names an object, by the only name a
conversation has. Whether the sidebar is open, whether the projects dashboard, Settings, the search box or the
Gene therapy drawer are up, and which pane a phone is on are things a person does
in order to look at an object; they are not objects, and none of them belongs
in something you paste to somebody else. Settings goes further: it is a layer over the
canvas, so opening it stands down whatever was there, and the address is
**held** for as long as it is up and what it names is **put back** when it
closes (`addrBack` in `app.js`). A panel does not move you.

Every one of the five addresses is answered by the server with the one page
(`index` in `rouh/web/views.py`, registered in `rouh/project/urls.py` in a loop over `addressing.KINDS`,
so a sixth kind is one line in one file). Nothing is resolved there: the
browser reads the address and asks what it names over the socket, through the
same `find_object` a search result's "open in new tab" uses, and presses the
same open instruction a result row carries. A link, a second tab, a bookmark,
a search result and the Back button are one behaviour rather than five.

The address bar is written from what is on the screen and never from what was
remembered, once a press has finished happening rather than three times on the
way, and never while the page is still on its way to an address it was opened
at. Those three rules are section 10f of `app.js`, `rouh/static/app/address.js`. The tab's own name is the
object's, so a bookmark and a pasted link read as the thing rather than as the
app.

One press can still take two writes, and they are one entry.
Opening a task's page also opens its conversation, which is a round trip to the server, so the bar says the task beside the conversation that was open and then, a moment later, the task beside its own.
Both were pushed until 23 September 2026, so every task opened left an entry that Back landed on - the task, beside General - instead of going back to where the person was.
The second write replaces the first now, as long as nothing else was written in between (`ADDR.thread` in `app.js`).

**And one address names nothing at all, which is the front door.**
`/` is the address of no object, and a page opened there used to go looking for something to be: the handshake says which chat the person is in, the page drew it, and the bar followed it.
So opening the bare address landed on whatever task was last open, with last night's conversation on the screen.
Petar asked for that to stop on 22 September 2026, in these words: going to the root should not redirect to the last thing, and should not load anything on the screen, neither chat nor anything in the canvas.
So it is a place now, and the place is empty: no conversation, no transcript, no cards, nothing on the canvas, the bar left at `/` and the tab called Rouh - the shell, the box and the controls, ready for a fresh start.
Empty is not bare, though: like every empty conversation that is not a task's, it says hello to the person by name with the box in the middle of the column, and puts four things to try on the canvas, each of which fills the box when pressed (`welcomeShow` in `app.js`), until the first thing is said.
The first thing said there opens a conversation to say it in, which is a new chat and the same one the New chat button makes, and typing, attaching a file and opening the microphone all count as saying something.
A conversation opened anywhere - from the rail, from a task, on the phone - closes the front door behind you, and Back to `/` opens it again with nothing on it.
Section 10g of `app.js`, in `rouh/static/app/address.js`, is the whole of it, and none of it is on the wire: which chat is active belongs to the person and is shared by every device, and a page standing at the front door changes nothing for any other.

`/?open=<type>:<id>`, which is what "open in new tab" put in the bar before
this, is still read, so a link written down then still opens.

## The turn loop, and what it does that a plain loop does not

`rouh/brain.py` is a hand-written agent loop rather than an SDK runner, for
the three reasons at the top of that file.
Ten things the Claude Agent SDK gives that it did not are now in it, each in a
module of its own, and `/gaps` is a page that says how far that work has got,
read out of `rouh/gaps.json`.

| What | Where | Off by default |
|---|---|---|
| General is sent a window of its newest messages, every other chat is sent whole | `chatkinds.py` | no |
| Old tool results leave General's window, the reasoning stays | `context_editing.py` | no, `ROUH_CONTEXT_EDITING=0` turns it off |
| A helper with a window of its own, whose window is thrown away (`look_into`) | `subagent.py` | no, `ROUH_SUBAGENTS=0` turns it off |
| Fetched text framed as somebody else's words | `untrusted.py` | no |
| Retries and backoff, always on the same model (no fallback model since 18 October 2026) | `retrying.py` | no |
| Tools that have to be asked about first | `permissions.py` | yes, `ROUH_CONFIRM_TOOLS` names them |
| External MCP servers, namespaced into the tool list | `mcp.py` | yes, `ROUH_MCP_SERVERS` or `ROUH_MCP_CONFIG` |
| Branching a chat, and a turn a restart killed saying so | `memory.py` | no |
| Thinking that carries across tool calls, never spoken, its summary kept in the log of requests | `brain.py`, `config.thinking_for` | on for the 5 generation, which thinks either way; `ROUH_THINKING` asks any model |
| run_command inside a sandbox the kernel holds shut | `sandbox.py` | no, needs the `bubblewrap` package or Linux 6.7's Landlock |
| What a turn cost, in tokens and money, request by request | `costs.py` | no |
| Every round trip of a turn reads the one before it out of the prompt cache, and every turn reads the one before it | `promptcache.py` | no |
| Every tool declared, none loaded until a search asks for it, with a catalogue of one line per tool in the cached prompt | `toolsearch.py` | no, `ROUH_TOOL_SEARCH=off` sends every tool whole |
| Every request made of a model written down, with its reasoning, answer, tokens and cost | `llmlog.py` | no |

Which tools are sent whole on every request anyway is one list,
`TOOLS_ALWAYS_LOADED` in `rouh/config.py`, empty since 26 September 2026 so the
difference shows; `ROUH_TOOLS_ALWAYS_LOADED` overrides it on one machine.
How long each turn took to its first token, its first words and its first
spoken sentence, and which tools it loaded, is in the `spend` table beside what
it cost, and in a `turn timing:` line in the log.

Two of those want something from the machine rather than from the
configuration.
The sandbox needs `bubblewrap` installed (`apt-get install bubblewrap`), or,
where bubblewrap cannot make its namespaces (inside a container), the kernel's
Landlock on Linux 6.7 or later, which holds the same two things; without either,
commands are still held to the read-only command rules and `server_health`
says which this machine is in.
In the containers every Rouh instance runs, commands run in the worker under
Landlock, with `ROUH_SANDBOX=required`, so with no box nothing runs.
An MCP server is whatever its configuration says it is, and one that will not
start costs its own tools and nothing else.

## The nightly code refactoring run

Petar, 15 October 2026: "Every night at 3, start a refactoring job ... The goal is to keep code well organized instead of layered bozocity due to added hundreds of features ... We are going open source soon, so it needs to get in shape."
It is Rouh's own server job on Clockwork, "Nightly code refactoring run", daily at 03:00 on the owner's clock, an hour after the nightly feature run (`rouh/nightly_refactor.py`).
It starts one run of the one program on Rouh's own code, on the Models page's "Nightly refactoring run" (its tier's model: Claude Code on a Claude model, Codex on an OpenAI one), with a brief fixed in the code.
The run reads its home task in the workspace, "Nightly code refactoring run" (refactoring-rules.md, which the owner revises, notes.md, and the two ledgers to-refactor.json and refactored.json), adds what it finds to the list, picks a few separate refactors or one major one, changes only how the code is organised, checks before and after, and lands each refactor through land.sh as its own commit, with no approval asked.
It never runs beside the feature run: while that night's run is still going or still landing, or while the home task is not in the workspace, the night waits, looks again every two minutes, and starts the moment it may, or at two hours (05:00) starts anyway to survey only and refactor nothing, as the task's rules say; a waiting night is a row in `nightly_refactor_nights`, so it is waited for again after the restart a landing's deploy makes.
At the end the run calls `refactor_done` (`rouh/worker_mcp.py`, `/internal/refactoring`, its own run only), which is the Clockwork line and the morning brief's Report, with an Undo there that asks once and then starts a run reverting exactly that night's commits (`POST /api/brief/refactoring/<n>/undo`).

## The heartbeat: Rouh's own turn, that nobody asked for

Since 5 October 2026 Rouh has a heartbeat (`rouh/heartbeat.py`): its own turn that nobody asked for, part of its arsenal like any other tool.
Petar, the same day: "Heartbeat is the functionality you have to have in general. It has nothing to do with the money project/experiment."
So there are three separate things, each with a page of its own.

**The heartbeat** (`rouh/heartbeat.py`, Settings, Heartbeat, `/settings/heartbeat`).

- **Its duties**, an editable list with each on or off, and the owner's own words besides: anything waiting on them they have not seen (told once, never again: `heartbeat_end` names what it told them), finished jobs and runs nobody reported, unhandled mail in Rouh's own inbox, calendar events coming up, Rouh's own goal steps, and the quests it carries. A beat on its duties runs in its own chat, Heartbeat, never General.
- **What wakes it.** The timer, every 30 minutes by default inside working hours (08:00 to 22:00 on the owner's clock); a job or run finishing; new mail in Rouh's own inbox; and the owner answering its queue. Each can be turned off. A flood guard lets an event wake it at most once every 30 seconds and five times in ten minutes; the rest are merged into the next beat. In quiet hours (00:00 to 07:00) nothing beats at all.
- **When it does nothing**, decided in code before any model call and written down with the reason: paused; quiet hours; a turn of Rouh's already running; today's spend across every beat at its daily cap (3 dollars); no duty on; nothing new and a full beat less than four hours ago; and for a quest, paused, not carried, outside its dates or its budget spent.
- **How it ends a beat**: with nothing, a silent note for Rouh's next real turn with the owner, or a Telegram, only for what they ticked as worth one (their yes, a human step, money in, a breakage, a daily summary), at most one an hour and six a day by default, and kept back in their quiet hours for messages until they end.
- **What it may do by itself** is decided where tools are dispatched (`heartbeat.check`, read by `tools.ToolRegistry`): research, reading Rouh's own inbox, calendar, goals, Docs, Drive and runs, starting runs and steering the ones it started, Rouh's own goal steps, mailing the owner themselves and, in a beat on a quest, from Rouh's own inbox the trusted contacts who decide for or edit it (DELEGATION.md), private files, Stripe's reads, and, in a beat on a quest only, that quest's Stripe products and links and the card through `browser fill_card`; the live browser never past the last button. Everything else goes to the approval queue (`heartbeat_ask`), which says what, to whom, why, at what cost and which duty or quest raised it; on the owner's yes, on the page or "yes 3" on Telegram, exactly that runs.
- The `heartbeat` tool in conversation and "pause the heartbeat" on Telegram control it.

**Quests, the long-running work it carries** (`rouh/quests.py`, Quests in the sidebar, `/quests` and `/quests/<task number>`).
Since the evening of 5 October 2026 a quest is part of the task model, the way a goal is: a numbered task tagged Quest (`"tags": ["quest"]` and a `"quest"` block in its meta), filed under a project and found in the task browser like any task, whose plan's steps can be its real numbered steps.
Its goal and rules (the owner's) and its plan and notebook (kept by its beats with `heartbeat_brief`) are four files in its folder, `quest-goal.md`, `quest-rules.md`, `quest-plan.md` and `quest-notebook.md`, saved to main by Rouh (`rouh/saving.py`).
Everything that must not live in git is its record, a row of `long_work` keyed by `org_id` and `user_id` and joined by the task's id and number: its dates, a budget counting its model and tool spend and its card charges, a spending cap a purchase under the Payments caps, a ledger of its card charges, the Stripe payments from its links and whatever is written in, pause and resume, whether the heartbeat carries it, its waiting events, its next beat, the runs, threads and files that are its own, and its own chat, owned by its task, where every beat on it runs.
Every money figure is in the database only.
The Quests page lists every quest with its number, state, dates, spend against budget, income, net, what waits for a yes and its last and next beat, and has New quest; each quest's page edits any of its fields in place, and Reset and Delete, which asks whether its task is archived with its files (the default), kept or deleted with them.
The first is Petar's experiment, "Can Rouh earn more than it spends?" (30 days from 5 October 2026, 100 dollars), record 1, which became quest 89 at the first start after the change (`quests.adopt`, which joins a record to the task with exactly its title, or makes one); its earliest beats stay in the Heartbeat chat, linked from its page.
The `quest` tool reads and changes them, and finds one by its number as said ("eighty-nine"); `long_work` is its old name, kept so a call made under it still works, and the old `/work/<id>` addresses are sent on to the quest's page.

**Payments** (`rouh/payments.py`, Settings, Payments, `/settings/payments`), for any work to use.

- **The card vault.** The owner types each card themselves, and may keep several (`payment_cards`); each is sealed whole with `encryption.SecretBox`, security code included, because a checkout asks for it, and the Payments page shows only its brand, its number masked to the last four, the name and the expiry, while everything else says its brand and last four. Each card may be for one silo, picked on the Payments page; the card filled is the one named by its last four, else the card of the purchase's silo (its quest's task's, else its chat's task's or project's, else its run's), else the default: the card for no silo saved most recently, or the one saved most recently when every card is some silo's. Deleting a silo moves its cards with everything else in it. The one place a card is opened is `browser fill_card`, which fills a checkout's card fields in the live browser straight from the vault, in every frame (`browsing.Desk.fill_card`); every outline of that page read back afterwards has the number, expiry and code scrubbed out (`browsing.scrub_card`). The spending caps are each card's own (since 14 October 2026; there was one pair for the whole vault before, which every card was given): the most a purchase, a day and a calendar month (`payment_cards.per_purchase`, `per_day`, `per_month`), each optional, set on the Payments page under the card, a new card's starting at 100 dollars a purchase and a day; a card with none says so. A purchase over one of its card's caps, the quest's own cap or its budget is refused before the fill, and no other card is filled instead; each is written down with the merchant, amount, reason and quest, and the owner is told on Telegram. Rouh never stores or types a password or a one-time code.
- **Billing entities** (`billing_entities`, since 14 October 2026). Every card is kept under the entity its purchases are billed to, such as two companies and Personal: a name, an optional company name, VAT number, registration number and invoice email, and the billing address. Filling a card fills its entity's address and whichever of those details are set into the checkout, and tells Rouh them so it can type any the page asks for elsewhere; an empty one is never filled, so a personal entity's invoice has no company or VAT line. Each purchase keeps who it was billed to as it was then (`card_charges.billed_to`). A card saved before entities had its address in its seal; it is carried over into an entity the first time the vault is read (`payments.carry_over`). An entity with cards under it cannot be removed until they are moved or removed.
- **Stripe.** A restricted key, sealed and shown masked, made with write on Products, Prices, Payment Links, Checkout Sessions and Webhook Endpoints, read on Balance, Charges, Payment Intents, Customers and Events, and nothing else. The `stripe` tool makes products, prices and payment links against a quest and reads payments and the balance; one button makes Rouh's own webhook at `/hooks/stripe/<token>`, whose signing secret is sealed and checked on every event (`payments.verify`). Each payment is money in against the quest it came from, and the owner is told. Refunds go to the approval queue; payouts and account changes are the owner's. A test world has a stand-in for Stripe (`rouh/testing/fake_stripe.py`).

**Shipping** (`rouh/shipping.py`, Settings, Shipping, `/settings/shipping`), since 14 October 2026: where a parcel should go, in the owner's favourite order, so Rouh picks the right one at any seller's checkout.

- **An option** (`shipping_options`) is three parts kept apart: the logistics company (free text, with Speedy, Econt, BOX NOW, DHL, Bulgarian Posts, UPS, FedEx and Any courier suggested), the type of place (a locker or box, an office, or a door address), and the specific place (the courier's own locker or office code and name, or the street, entrance, floor, apartment, door code, city, postcode and country). With them go a label, the recipient's name and phone (empty for the page's default recipient, which starts as the profile's name and the contact card's first phone), notes for the courier, a place in the main order and an on/off switch. Options are reordered by dragging a handle, with Move up and Move down, or with the arrow keys on the handle.
- **Situations** (`shipping_situations`), such as Big or heavy or Abroad, each order the saved options their own way; Default always exists and is the main order. Every list ends with "Then: ask me".
- **Choosing** (`shipping.decide`): given what a checkout offers - its couriers and kinds of place, or pairs of them, and optionally a situation and the destination country - the first option that is on, in that country, of an offered kind and with an offered courier (or Any courier) is picked, with why each one before it was skipped ("Speedy locker near home skipped, the seller offers no lockers"), or Rouh is told to ask. The `shipping` tool lists and chooses in any turn the owner may see it in, and adds, changes, reorders and deletes only in a turn they started, in their own words. `browser fill_shipping {option}` fills a checkout's delivery fields (never one marked billing) and presses nothing; the locker or office is then picked in the page's own list. The prompt says to do this at every checkout and to tell the owner which and why, and that ordering stays theirs.
- **Private.** Every option and situation is labelled with the Personal silo: a turn limited to other silos, such as a trusted contact's, sees none of it, and deleting the silo moves them like everything else in it.

**Cloudflare** (`rouh/cloudflare.py`, Settings, Cloudflare, `/settings/cloudflare`), since 12 October 2026: one API token per zone, typed by an administrator into the zone's row so it never passes through a chat or a model.

- **Saving.** A token is checked with Cloudflare before it is kept, with task 86-02's checks (`cf_rouh_is.py`): active, sees exactly that zone (and its known zone and account id), DNS and SSL and Certificates answer it, and it may change the zone's settings (Zone Settings Edit, proved by reading always_use_https and writing back exactly the value read, so nothing changes; since 2 November 2026, when a token with Read only passed and then could not change rouh.land's settings); Cache Purge is optional. The page asks for Zone Read, DNS Edit, Zone Settings Edit and SSL and Certificates Edit, and Cache Purge as optional. A token that fails is refused, and the page lists each check and says which permission is missing. A kept one is sealed with `encryption.SecretBox` in `cloudflare_zones`, by organisation, and shown only as set, its last four, when it was saved and when it was last checked, with Replace, Check again and Remove. Only an organisation's administrators change tokens.
- **The zones.** An organisation starts with none, and each is added by its domain name.
- **Using one.** Rouh's code asks by zone name: `cloudflare.cloudflare_token("example.com")`, or `cloudflare.zone_api("example.com")`, which makes the calls itself. The `cloudflare` tool says whether each zone has a token, opens the page (`settings_shown`) and reads a zone's DNS records, always by zone name; the model never sees a token. `ROUH_CLOUDFLARE_API` points it at the stand-in, `rouh/testing/fake_cloudflare.py`, which the `talking` world starts.

**Genes from a registry** (`rouh/genelab.py`, Meta, Gene registry, `/anatomy/meta/gene-pool`), since 12 October 2026: Rouh's receiving side of the gene registry (task 98, step 98-13), where shared genes are read before they are installed and arrive in a lab. GENES.md, "Shared genes from a registry", has the whole of it.

- **Off until pointed.** No registry address, no request to anybody. The address and the registry's Ed25519 public key are set on the page, by an administrator; the key is pinned there, and a signed list whose signature does not hold against it, that is older than the one kept, or that is the wrong kind of list, is refused.
- **Install, update, remove.** Only on an administrator's press on the gene's own page, after its whole contract was drawn there; the press carries the hash of the contract shown. Files are checked against the signed index's SHA-256 and, where the registry gives one, their Sigstore signature against the build it names (`sigstore`, pinned in pyproject.toml); they are kept in `shared_genes` and never run. Remove deletes the row and the gene's switch and then checks nothing named for it is left.
- **The beat** (`genelab.Watch`, hourly, `ROUH_GENES_EVERY_MINUTES`): the blocklist switches an installed gene off and tells whoever installed it; an update is noted with what changed in its contract and told, never installed.

## The log of every request made of a model

Every request any part of Rouh sends to a model is a row of `llm_requests`, written by `rouh/llmlog.py`: Petar asked on 26 September 2026 for "a full log of every single LLM request we do, including cost, reasoning etc.", after the `LLMInteraction` log of another of Petar's projects.
A row says whose it was (person, organisation, chat and turn), what it was for (`turn`, `subagent`, `chat_title`, `filing`, `triage`, `askai`, `comment_pass`) and which function sent it, the model, effort and thinking asked for, how it ended (`ok`, `error`, `stopped`, or `sent` for one the process went away in the middle of), the four token counts and web searches, the cost at list price (`costs.request_cost`), the time to the first word and to the end, the words of the answer, the reasoning the model returned, and the whole answer as it came.

- **Nothing gets past it.** Every Anthropic client in Rouh is made by `llmlog.client`, and its HTTP client writes the row, so a retry, the SDK's own retries, a request stopped half way and one that failed before a byte came back are each a row of their own. A new place that asks a model makes its client there too, and says what it is asking for with `llmlog.about(...)`, or `llmlog.said(...)` inside an async generator.
- **And every place that asks a model is on the Models page.** Since 5 October 2026 a new call to a model is also a `Use` in `rouh/modeldefaults.py`, and asks `modeldefaults.use_pair` for its model, so it is on a tier in Settings under Models (AGENTS.md, "Every call to a model").
- **What was asked is kept once.** A request is its settings plus the digests of its system prompt, its tools and each message; `llm_pieces` holds each of those once, however many requests re-send it, and `llmlog.request_of` puts a request back together as it was sent.
- **The reasoning is there because it is asked for.** The 5 generation thinks either way and returns its thinking empty unless asked for a summary, so every request to one asks for `display: "summarized"` (`config.thinking_for`). It changes what comes back and nothing else: never spoken, never in a transcript, billed the same.
- **Nothing waits for it.** One thread of its own writes the rows in order; a turn is never slower for it, and a database that is down costs a warning in the log and never a turn.

Reading it, on the server: `python manage.py llm_log` lists the newest requests, `--chat`, `--turn`, `--purpose` and `--days` narrow it, `--totals` adds it up by purpose and model, and `llm_log <id>` shows one whole, with `--request` for exactly what was sent.
It is also plain SQL: `select purpose, model, status, cost_usd, reasoning from llm_requests order by id desc limit 20`.

## The record of every turn

Every turn of every chat is kept for good in `turn_records` (`rouh/turnrecords.py`, Petar, 23 October 2026), so speed can be weighed against quality later.
One row per turn, keyed by its chat, the person's message (`message_id`, `root`, `version`) and the turn's name, which is also its `turn_id` in the log of requests and its `call` in `route_timelines`.
It holds what nothing else kept: the whole timeline under the reply (`trace`, which the reply is drawn from after a reload), when the answer's first token, first written word and first spoken word came, how the turn ended (finished, stopped, failed, unfinished, replaced), which tier and model wrote it, its rows and words, every look-up of Synapse with the items it found and its trace's steps (`synapse`), and what it all cost, by part (`costs`).
The requests themselves stay in `llm_requests`, linked by the turn's name; the router's are under its `subject`.
`labels` is empty, for later: the person's correction, a thumb, a judge's score from a double call.
It is not deleted with its chat.

**How a reply was made, at the top of the reply** (`app/turnline.js`, Petar, 24 October 2026: "timetables should be unified ... the entire thing should be hidden under one optional default closed toggle of one line").
One quiet line, closed until pressed and remembered open or closed per reply on that device, says it all at once: the tier that answered as a two-part Cheaper and Smart marker (pressing a part answers the exchange again on that tier), the model, how sure the router was against its bar and how long it took, what memory did ("Memory 7 look-ups, 7 in time, 11 items"), and on the right the whole turn's time and cost.
Opened, it is one timeline across the whole width of the chat: a row per step (the message received, the model decision, memory, each wait, each request of the model, each tool call, saving, speaking, the end) on one time axis with its scale at the top, each row's time and cost in one fixed column of one line, its bar in the colours of the orb's twigs for tools and its own colours for model requests and for Synapse.
A row's details are in a popover, on hover with a mouse and on a tap or Enter: start and end, tokens in, cached and out, what a tool was given and said back, the router's reasons.
Memory opens into its look-ups, each with how it ended and the items it found as chips; Details opens everything kept, with this turn's record as JSON and the day's turns as CSV.
It is drawn live from `trace`, and from the turn's record after a reload; a reply from before turns were recorded draws its kept decision and memory in the same line.
The memory line under the person's message, the "Model decision" line with its buttons and the timeline box in the reply that came before it are gone.

    /api/turns/export?from=2026-10-20&to=2026-10-23&format=csv     a row per turn
    /api/turns/export?from=2026-10-23                             JSON, whole, with each turn's requests
    /api/turns/export?turn=<turn-id>                              that one turn, whatever its day
    python manage.py turn_records [--from D --to D --format lines|json|csv] [turn-id]

## What a conversation is told: the Rules page

Since 21 October 2026 every instruction in a conversation's system prompt is a rule on the Rules page, and nothing else writes one (Petar: "I imagined 1 place should rule the behavior and this is rules").
Since 30 October 2026 every rule is equal and in one place, the person's Synapse Master (`rouh/rules.py`): Petar, "Fully remove that lock", "Every rule should be in a database and editable. Nothing should be hardcoded", and "Built in concept should disappear ... all rules should be equal".
Until then Rouh's own rules were "built-in", rows of a table of their own made from a seed in the code, twenty of them locked on; migration 0221 moved every one into each person's Master with its words unchanged, and the seed, the tables and the lock are gone.

`Brain._system` puts the prompt together through `rouh/prompting.py` from two things, and the Rules page shows the first.

- **Rules**, each a rule of the person's, written, reworded, turned off and deleted on the page like any other. A rule's row says when it is told: in which kinds of work (`rules.reach`: chats, runs, Synapse's answers), under which conditions of a conversation turn (`when`: the tools the turn has, Claude or an OpenAI model, a written or spoken reply, a turn from Telegram, a fact the code worked out), for which person, task or project, and, for the ones that were Rouh's own, its place in the prompt (`place`) and whether its words hold live values such as `{now}` (`fills`).
  Each row on the page has a "Conditions:" line written from the same data the prompt is put together from (`rules.conditions`), so the two cannot disagree.
- **Live context** the code works out each turn: the date and the time, Rouh's own address, the mailboxes, goals, what Synapse found, the tool catalogue made from the registry. Labelled as live, never a rule.

Where each kind of rule goes: a conversation turn of Rouh's (typed and spoken chats and their forks, Telegram, a mail case, Slack, Clockwork and the heartbeat) is told every rule that reaches chats and whose conditions hold; the brief of every job and run started for the person's own work (`rules.run_block`) every rule that reaches runs; Synapse's answers (`synapse/recall.py`) every rule that reaches them. Helpers (look_into), Ask AI and the agent instructions are told none.
No rule widens a permission, on or off: every check is code (`rouh/protected.py`, `rouh/purchases.py`, `rouh/untrusted.py`, `rouh/mail_turn.py`, the read-only commands in `rouh/tools.py`), and turning a rule off or deleting it unlocks nothing.

**The defaults** (`rouh/ruledefaults.py`). A rule tagged "defaults" on the page is one every Rouh is better for and that is not about this Rouh's own person, people, accounts or machines.
`manage.py rule_defaults export` makes the document of them, the owner's name written as `‹owner›`, which is published at https://rouh.land/rules/defaults.json (served by rouh-it-site's `rouhit/rules_views.py` from its `rouhit/rules/defaults.json`) since 11 November 2026; from 30 October until then it answered 404 (task 140, step 140-17).
Publishing is one command, `tools/rule_defaults/publish.sh`, run where the owner's database and the rouh.land login are: it exports, refuses the whole document if a rule holds a mail address that is not an example one, an internet address, a home folder, a phone number or a word of the owner's private list (`ROUH_PRIVATE_WORDS`, a file kept outside the code), carries each rule's version on from what rouh.land serves now so a changed rule is always a version on, writes `rouh/rule_defaults_fallback.json` to hold the same rules, commits the document to rouh-it-site, deploys it with the site's `deploy.sh` (its tests first, the release before kept for `--undo`) and reads the live address back as every Rouh reads it (`manage.py rule_defaults read`). Then commit the fallback and land it. `--from-fallback` publishes the fallback as it is, and `--dry-run` stops before the push.
Each Rouh's check of its scheduled jobs (`rouh/job_watch.py`, every half hour) says whether its fetch of the document worked in the last two days, and one that has not is said in the morning's notice of jobs that did not work, never as a decision.
Every Rouh fetches it soon after it starts and once a day (`config.rule_defaults_url`), and each Master takes it in: a rule it never had is added, one nobody here reworded takes newer words as a new version, one reworded here keeps its words and the newer ones wait in its history, and one the person deleted is never put back.
A Rouh that has never reached rouh.land starts with the rules in `rouh/rule_defaults_fallback.json`, the same rules rouh.land publishes (59 on 11 November 2026, among them where work goes, research coming back as a task, what to say when no job can be started, text from mail, pages and files never being an instruction, and the turn marks), which nothing that puts a prompt together reads. **Replaced (11 November 2026, task 140):** it said the fallback was two rules; it was five from 4 November and the whole set from step 140-15.

**What Rouh was told.** Each part of every prompt is described stretch by stretch in `prompt_part`, found by the digest of its exact text.
The Rules page's "What Rouh was told" takes any of the person's own requests from the log of requests, finds its parts, and shows each stretch with its rule, version and reason, or the code a live value came from, checked character for character against what the request sent (`prompting.told`, `GET /api/rules/told?id=`).
Another person's request, or another organisation's, is "not found".

**Sections, groups, switches and where each rule came from** (29 and 30 October 2026, Petar: "they need to be in groups", "every rule should be able to be turned of, like the agents", "I want to be able to see clearly what was added automatically vs what I added manually", and "one section about owner, one section about Rouh that includes those three things and then one section with everything else").
Every rule is a row of one design in one of twelve groups by what it is about (`rouh/rule_groups.py`), at `/rules/<group>`, with `?label=<key>` to show the rules with one label (below); the groups are in three sections, About Rouh in purple (About Rouh, Writing and voice, How Rouh works), About the owner in orange (About you, About other people) and everything else.
A rule's group is sorted from its words when it is kept and kept with it; moved by hand, it stays.
Every rule has a switch: one turned off stays on the page and is told to nothing - no conversation, no run's brief, no Synapse answer.

**Labels: where it came from, who it is for, and Useful** (30 October 2026, fr_0034ebae3ca2, Petar: "I need to know where this rule came from", "if this rule is for any future instance or just for myself", and "a "Useful" label and a button "Make standard" which will convert it to template for everybody else").
Every row carries two labels in sight, drawn differently so they are never confused, and the landing page `/rules` explains each under its question.
- **Where it came from**, a round outlined flag (`rules.ORIGINS`, kept as `meta.origin.from` with a sentence saying what added it, shown by pressing the flag): Manually added (`manual`, on this page or in Synapse's lab), From chat (`chat`, out of a conversation, the person asking or Rouh deciding; an email the person handled with Rouh counts), From agents (`agents`, a job's report, a scheduled turn, Synapse reading a note, a job applying a plan), Gene update (`gene`, a gene or mutation from the pool, which is how the defaults arrive), or Origin not known (`unknown`) when nothing kept says, never a guess. Until that day they were "you", "auto" and "rouh"; `rules.origin_kind` reads those by their sentence and `rules.settle` writes them again in the new names when the page is opened.
- **Who it is for**, a square filled tag with a person or a globe (`rules.scope_of`): Creator only, never published, or Rouh instances, which is the "defaults" tag above, on a rule `ruledefaults.export` gives away. A rule for one person, task or project, and one Synapse attached, are always Creator only (`rules.can_standard`).
- **Useful**, on a Creator only rule that could help others (`meta.useful`), set by the person in the rule's Edit form or by Rouh when it keeps the rule (`remember`'s `useful`), with **Make standard** beside it (`POST /api/rules/standard`, `rules.make_standard`): the rule is tagged defaults, so it is Rouh instances and goes out with the next `manage.py rule_defaults export`, and the Useful label and button go.

**Vocabulary** (`rouh/vocabulary.py`, 30 October 2026). Petar: "the rules have something called words. this feature is confusing ... should we create a new functionality called vocabulary ... that will be embeded naturally in the synapse. and therefore should be picked up by the synapse, not by passed automatically always through the rules."
What the person means by a word or a nickname is an entry of kind `vocabulary` in their Synapse Master - the word, what it means, its other names, what it is about and its silos - on the Synapse lab's Vocabulary page, `/synapse/vocabulary`, in the Memory group, and kept by `remember` as vocabulary.
It is a meaning, never an instruction, and says so wherever it is told.
It is told only when it is used: a message holding the word or another name of it, whole and in any case, gets the entry first in its background memory block, matched rather than searched, so a short nickname is never missed (`synapse/autorecall.py`); a run's brief holding it gets it in its standing section (`rules.run_block`); and a rule for a person is told when an entry about them is used (`rules.involved_people`).
Until that day these were "Your words" on this page, every one told in every turn and to every agent. They were moved by what each does (`vocabulary.classify`): a pure meaning into Vocabulary, its words unchanged; one holding an address or an id, which an action depends on, into a rule word for word, for the person the address belongs to when it is somebody's and for every turn when it is nobody's, with who that person is in Vocabulary too. `manage.py vocabulary plan|move` says what that does or did.

What stays outside the Rules page, on purpose: the tools' schemas (the registry that runs them is their one source), the model provider's own rules, every permission check, the one-off prompts of single-purpose model calls that answer in a fixed shape (titles, filing, the mail case's own reading, a helper's brief, Ask AI), and what a background job is told, which is the Agent instructions page.

## Rouh's updates: ride along, update when pressed, or its own path

Petar, 11 November 2026 (task 140, step 140-18): "one time click that updates your code from our repo", and "an option to stay in sync with the creator rouh ... people that will be happy to just ride along".
A Rouh's code is its own (`/code`, changed by its genes and by itself, each change through its protected core), so until this nothing newer reached it after its first start.

**The choice**, on Anatomy, Meta, Changes, in the card Rouh's updates, and through the `update_rouh` tool:

- **Ride along** (the default): the Rouh takes each new release by itself, at a quiet moment (no turn in progress, no run going, no deploy waiting), at most once a day.
- **Update when I press**: nothing comes in until the person presses "Update to the newest Rouh", which shows the version they have, the newest, and a short list of what is new.
- **My own path**: the Rouh never looks for releases by itself; the button still works.

A Rouh on its own (Independent) asks nobody anything by itself, so it never rides along and asks rouh.land only when its person presses a button.
A Rouh with no protected core beside it (a server, a test world) shows the card and says its code is updated by `land.sh` there.

**A release** is a checked boundary on the shared main branch of `rouh-it/rouh-core`, including changes published by collaborators.
It is eligible after the master's checks pass and it runs a day on an authorised early-test Rouh without being put back (`rouh/code_release.py`).
Initially there is one early tester; collaborators can be authorised through the release service's registry allow-list.
The exact source commit must also have a successful **Tests on main** run at GitHub (including Intel and Arm); a later successful commit does not approve an earlier failed one. If that result cannot be read, publishing waits.
The public release pointer remains `/mac/code/release.json`.
A private change on an early tester cannot become a release: the publisher verifies that the commit is on shared main and contains the preceding release.

**An update** takes the changes up to that boundary in order, grouped by the purpose in each commit and its diff (`rouh/code_evolution.py`).
It fetches shared main and verifies that the installed version and the released boundary belong to that history.
The durable record, `code-update/ledger.json`, keeps every change since installation, its purpose, result, plain reason and protected undo point.
Released purposes appear in the record before Update is pressed, without applying code or spending on a model.
For older installations that kept full Git history, the protected core’s first recorded version establishes the verified shared-main starting point; master commits already present are recorded as such. An unknown starting point is refused rather than guessed.
Settings, Meta, Changes shows the counts and the full record: copied exactly, adapted for this Rouh, not taken yet, or waiting for an earlier change.
The record makes drift visible; a waiting change never makes this Rouh appear up to date.

- When all touched files still match the preceding master version, copy exactly those files, including deletions, binary contents and modes, with no model call.
- Otherwise a background adapting job reads the master commit, diff, change tests, checks catalogue and README alongside this Rouh's files, own commits and genes.
  It replans and builds the purpose for this Rouh, preserving local behaviour, then the protected core runs its adapted master proof and this Rouh's own checks.
  Tests may be fitted to local code, never weakened.
  Large files are supplied as marked excerpts; the job can inspect additional local or master lines and diffs, and must use exact edits rather than replacing an incompletely read file.
- Every accepted change goes through the protected core as its own undo point, with code backups; a restart resumes the remaining changes from the durable ledger.
- A change that truly cannot be fitted stays not taken yet with its reason.
  Later changes touching its files, directly importing its modules, or naming it with a `Depends-on:` commit trailer wait for it.
  Unrelated changes can continue.
  Waiting changes are retried on the next update; urgent security work is retried in half an hour, using the already downloaded release. My own path still prevents automatic retries.
  General gives one plain note per outcome, including what was copied, adapted and waiting, without asking a person to solve implementation details.

**The model bar.** `ROUH_CODE_UPDATE_MODEL_TIER=smart` is the required frontier tier; a lower bar is refused.
Models has a dedicated use, **Adapting master updates** (`code_adapt`), initially Smart.
The actual selected model must belong to the published standard's Smart tier, including when the use is Custom or the installation is in Saver.
The LLM service checks the tier again immediately before asking, and does not fall back to a weaker model.
If it cannot ask a frontier model, the change waits as **needs a frontier model**, and the person is told once.
Sensitive database and security changes always need these frontier checks, including when the original files match exactly.
Ordinary exact copies need no model key and spend nothing.
The job's brief is the editable Agent rule **Adapting a released master change**, shipped through the same rule-default machinery as the other agent rules.
It tells the job to be responsible and choose what is best for this Rouh.

**Database changes** are adapted, never automatically skipped.
The protected core's gate (`guard/rouh_guard/database_update.py`) makes a fresh full database backup, restores it into a private, disk-backed PostgreSQL instance, rehearses the adapted atomic migration there, and checks counts and preservation of existing row values for every table, allowing declared table and column renames.
The job's change proof and this Rouh's own self-checks run on that copy before anything is applied for real.
The code still running must also pass its own checks against the migrated copy, so activation or an undo can safely retain the earlier code. A migration that breaks it must be replanned as expand and contract.
For the real migration, the core holds writer locks while taking another full backup of that exact snapshot, runs migrations and preservation checks in one transaction, then reads back the result after commit.
Original values are compared while writer locks still hold; later committed counts are recorded separately, because the running app may update sessions or memory as soon as those locks release.
The applied database is copied into a second private instance and the change proof and self-checks run again there.
Both private instances, including their WAL, are removed; protected backup and result records remain. Rehearsals require free disk space for the real database rather than the ordinary checks’ small synthetic database.
The materialised code and proof stay root-owned and read-only; the check users can only write scratch data.
The live helper starts without usable credentials, refuses database access during application startup, and receives its live connection only after startup is complete.
A failed rehearsal never changes the real database; a failed transaction rolls back.
If final verification is interrupted after application may have started, the protected record marks the outcome as needing checking, never as a known rollback.
Backups, table counts, preservation results, the job's reverse or restore procedure and the outcome are kept in the protected core's `database-updates/` folder, outside the Rouh's own code.
An operation that is not atomic must be replanned as expand and contract, preserving the old representation until it can safely be retired.
The stack gives only the protected core a migration connection to the live database; ordinary checks and the worker never receive it.
An older protected core without this gate makes these updates wait until the signed core update arrives.

**Security changes** are also adapted.
The same named assertions must demonstrate the vulnerability before and its closure after, with an explicit result and the expected failure and success codes; a crashed check does not count as a reproduced hole.
A change proved not to apply records that proof with the same assertions passing before and after.
Waiting security work is visibly urgent and is retried soon.

The three modes, Independent choice, existing button and chat tool keep their meaning.
A server checkout continues to use `land.sh`.
`ROUH_CODE_MASTER` is an installation/test override for the shared source; its default is the public rouh-core repository, never an early tester's private code.

## Where the code lives, and how to change it

This repository is the only copy of Rouh's code. On a development machine it is
checked out at `~/www/jarvis`. Until 14 September 2026 a second copy lived in the
assistant workspace (task 30, `30-01.build/source-code/`) and was copied in here
by `push-to-github.sh`; that copy and that script are gone.

To change Rouh: edit it here, prove the change yourself, commit, push to `main`, then

```bash
ssh <the server> 'bash /var/www/rouh/app/update-all.sh'
```

which resolves `origin/main` once and puts both services on it: the one program
first (`one/deploy/update.sh`) and Rouh second (`deploy/rouh.sh`), each
checking the new code imports, restarting its own service, and putting the
previous commit back by itself if it does not come up healthy. It is also what
every deploy started from inside Rouh runs.

**It is the only way to deploy, and the halves refuse to run without it.** Each
checks for the marker `update-all.sh` sets and stops with one sentence
otherwise. Rouh's half used to be `update.sh`, sitting at the root and
reading like something you could run; on 20 September 2026 somebody ran it and
Rouh went to `aeb3790` while the one program stayed on `df982eb`, with
nothing saying so until a person read the two version numbers off his own
screen. If only one service is behind, run `update-all.sh` anyway: it says
"already at <commit>, nothing to do" for the other half and moves only what
needs moving.

Rouh also edits this repository itself (`improve_myself`), so pull before
starting.

### Landing work on main, and the one thing allowed to push

`land.sh`, at the root of this repository, is the only thing that pushes to
`main`. Every job ends with it: a change to Rouh's own code, a run of the one
program, a job in the person's workspace. Nothing else pushes, and the briefs
say so.

It exists because of 20 September 2026, when three jobs finished good work and
pushed none of it. 5f932c8 was already on main from an earlier attempt and
collided with itself. 65cd518 collided with the sidebar. b950d2c collided with
two runs that landed around it. Every one of the three was recoverable, none was
recovered automatically, and nobody was told. Cards 488 and 489 are the design
that ends that, and `land.sh` is the ladder off card 488, in order:

1. **Already landed?** Compared by patch rather than by text, with `git cherry`
   and `patch-id`. Work that is already on main drops its duplicate, exits
   success and says "already on main as `<sha>`". 5f932c8 needed nothing else.
2. **One at a time.** An exclusive lock, on a file under `/srv/rouh-land`,
   round the whole fetch, rebase and push, so two jobs never land in the same
   moment and the second replays onto a main that has stopped moving. It is a
   file descriptor this process holds, so it is released on every exit path,
   failure included.
3. **Rebase with memory.** `rerere`, `diff3` conflict markers and `autostash`,
   written into the repository's own config. rerere's cache is the
   repository's, so a conflict resolved once in one job's worktree is resolved
   by itself in the next one's, and these jobs retry the same work.
4. **A real conflict goes back to the job that wrote the code.** The run does
   not end. It is handed both sides, the files, and the branch holding its work
   exactly as it wrote it, and told to reconcile the intent rather than the
   text and to prove the result in a browser again before it may push.
5. **If that job is gone, redo rather than untangle.** A fresh job is started
   from the current main with the old commit message, the old diff and what
   landed in the meantime, and told to write the change again. That is what
   actually worked on the thread-ownership fix.
6. **Twice failed, or both sides rewrote the same thing: Rouh merges it.**
   Petar's standing instruction is that Rouh resolves merge clashes itself and
   he is not asked (card 1684, 18 October 2026). The rebase stops at the
   collision and `rouh/merge_pass.py` runs one Claude Code pass in the checkout,
   given both diffs, both sides' commit messages and the run's brief, to write
   the version that keeps both intents. Not one conflict marker may be left,
   every Python, JSON and shell file it wrote must still parse, and nothing
   outside the colliding files may change; then the checks every push gets
   prove it and it lands. Its model is "Merging a clash" on the Models page,
   which Rouh writes into `/srv/rouh-land/merge-pass.json` for `land.sh` to read.
   `./land.sh --merge` goes straight to this rung.
   **Only when the two sides truly want opposite things does the person
   decide**: one deletes or reverses what the other adds, and both cannot hold.
   One JSON record is written - both diffs, both commit messages, the
   conflicting files, the pre-resolution branch, the question in one line and
   Rouh's recommendation - and from it one card with exactly four choices,
   each a command `land.sh` already knows how to run. `rouh/conflicts.py` is
   that record, those words and that card. It is said once per conflict, ever:
   the record remembers it was sent and said, and it is checked again the
   moment before it is said.

   Three things never reach anybody. A generated file - the workspace task
   list, made out of Rouh's database - is taken as main has it and made again
   by Rouh's saver. A replay that stops with no file colliding is an error in
   git's own words, not a clash (Rouh's saver once asked three times about a
   rebase that only lacked a committer name; the author of the work is now the
   committer). And a record from a scratch repository - a test's checkout
   under the system's temporary folder or a run's `.one/tmp` - is never
   written into `/srv/rouh-land`, so a test cannot reach the owner; `./e2e.sh`, the
   one program's test conftest and its throwaway world also give every test a
   landing directory of its own, which the program passes to `land.sh`.
7. **Deploy, and check.** The push is not the end of a landing.
   Once main has the commit, `land.sh` runs the deploy itself - `update-all.sh`
   out of Rouh's own checkout, the one program first and Rouh second - in a
   detached session, so the restart cannot kill the job that asked for it, and
   then waits for both services to answer their own health pages with the
   commit that was just pushed.
   Only then does it report success.
   A deploy that fails, rolls back or never comes up is a failure of the
   landing, exit 13, `deployed: false` and a sentence saying why: never a
   success with a note.

**Landing includes deploying, and only the deployed commit counts.**
Rung 7 is there because of 21 September 2026.
Job 711a5e4a landed 9890a50 at about 01:40 and the running server stayed on 3edf051 for six hours: `land.sh` pushed and left the deploy to whatever might notice the new commit, and nothing did.
The work was correct, the person's screen never changed, and the run reported itself as not landed because nothing visible had moved.
Petar's standing rule is that a change is done when it is committed, merged to main **and** deployed, so a commit sitting on main unserved is now something this script refuses to call a success.
It is also why a landing whose work is already on main still checks: if main is ahead of what the machine is serving, that landing deploys it.

**One deploy at a time.**
The lock for that is inside `update-all.sh`, not in any one caller, because every way of starting a deploy goes through that script: `land.sh`'s last step, `deploy_myself`, the deploy that follows a landed change, and a person running it by hand.
A second deploy waits for the first rather than racing it over the same two checkouts, because the second one is somebody's work going live.

**One number, one task.**
Right before every push, whichever rung got there, `land.sh` asks `rouh/numbering.py` whether this landing would put a task number or an object id on a second folder of the workspace.
If it would, nothing is pushed: exit 1, `duplicate: true`, and a sentence naming the folder already on main, the one this adds, and the next free number to take instead.
Only what the landing adds is refused; main as it already is never stops anybody else's work.
It is there because task 56 was two tasks from 22 to 24 September 2026, 51 was two pieces of work under one number, and 02 was a move a deploy half undid, and every one of them reached main or the server with nothing asking.

**What Rouh makes in the workspace, Rouh saves.**
A task the person asks for, a card filed as a step, a task moved into a project: Rouh writes all of those into the live workspace the server serves, and nothing saved them after the workspace's own `bin/sync` went on 21 September 2026.
So a task Rouh made existed on the server alone, and a job Rouh started for the same request, working from main, made its own under the same number.
`rouh/saving.py` lands them now: whenever the tree changes shape (`objecttree.WRITTEN`), and every five minutes for anything that changed it without saying, it lands through `land.sh`, with `--no-deploy`, exactly what the server's checkout holds that main has not got - a new object folder, a `git mv`, a `git rm` - and leaves alone anything main already has.
Since 24 September 2026 that includes **a page Ask AI changed**, because every deploy resets the server's checkout to main and a change nobody saved would be gone at the next one.
Main's copy of the page is merged with the change the way git merges, so a job that changed the same page on main meanwhile keeps its change; a merge that meets in the same lines is left unsaved and said in the log.
A run started from a task's conversation waits for that save and is told in its brief which task it is and where, so it works in that task instead of making another (`starting.with_its_task`).
It is switched on by `ROUH_SAVE_WORKSPACE=1` in `/etc/systemd/system/rouh.service.d/save-workspace.conf` on the server and nowhere else, because every test world, the laptop and every job's checkout have the real repository as their remote too.

**The workspace is a repository of its own.**
Since 21 October 2026 Rouh's code and the person's workspace are two repositories: the code is `rouh-it/rouh-core`, which holds nothing of anybody's life and is public since 7 November 2026, under the Apache License 2.0 (`LICENSE`, `NOTICE`; its history before that day is kept privately),  and the workspace is the person's own private repository, checked out on the server at `/var/www/rouh/workspace`, beside the code and never inside it.
Rouh has three repositories: this one, which holds Rouh, the one program and the protected core (`guard/`) and from which the images are built (never kept as repositories of their own); the workspace; and Rouh for Mac, `rouh-it/rouh-mac` since 27 October 2026, which follows the releases made here through rouh.land and never builds from this repository.
The images, all in `ghcr.io/rouh-it/`: `rouh-base`, public, what every Rouh runs on (`deploy/container/Dockerfile.base`); `rouh-guard`, the protected core (`guard/Dockerfile`), public; both made by `.github/workflows/base.yml`, which fails a build while either cannot be pulled without a sign-in, so a new install is never asked for a GitHub token.
`rouh-core`, `rouh-workers` and `rouh-keyproxy` are the images of before 23 October 2026, private and no longer built, kept because Rouh for Mac before 0.3.3 still pulls them and rouh.land's gate for the Mac app asks whether a sign-in may pull `rouh-core` (`deploy/container/README.md`).
The repositories before these two, `rouh-it/rouh` (once `mgpepe/jarvis`; GitHub still sends that name there) and `mgpepe/assistant`, the workspace until 22 September 2026, are archived: read-only, nothing reads them, and their history is kept (task 140).
Neither is a submodule of the other, and nothing else is kept in step with them: the person's assistant is the jobs and runs on the server (Claude Code or Codex as workers), not a program on a computer of the person's own, so no copy elsewhere takes a change in and nobody has to clone either repository to see their work. Where each one is, and its remote, is the installation's (`ROUH_WORKSPACE`, the code's own checkout), never the code's.
The one link between them is a setting, `ROUH_WORKSPACE` (`rouh/config.py`; `ROUH_ASSISTANT_REPO` is its old name and is still read), and nothing is set is no workspace at all, never the code checkout's.
Every git question about the workspace - what the saver commits, which numbers main has, a page's history - asks the repository that holds it and the workspace's path inside it (`rouh/workspace_repo.py`), so the same code works for a workspace of its own and for one that is still a folder of a bigger repository.
`land.sh` lands both kinds: a branch with `_migration-map.json` at its top is a workspace, and its landing ends by moving the live workspace onto the commit (`update-all.sh --workspace`) instead of deploying, with nothing restarted; everything else is code and deploys.
The commands a run uses on a workspace are Rouh's code, in `bin/`, and every run has that folder on its PATH: `rouh-task` (a task's status, summary and meta, the old `bin/task`) and `rouh` (`rouh objecttree ...`, which asks Rouh on this machine to run it against the checkout it is run in, `/internal/objecttree`, because it needs Rouh's database and a run has no login to it; `rouh numbering ...` and `rouh xray ...`, which read only git and files and run where they are typed).

A task's meta is its steps' titles, descriptions and groups, the groups and arrows between steps, its tags, a goal's and a goal step's blocks, a waiting task's `question` and the replies the owner sends himself.
Petar, 22 October 2026: "should be in DB".
It is the task row's `meta` column and nothing else (`rouh/taskmeta.py`), every change a row of `task_change`, changed by Rouh's code through `taskmeta.change` and from a run with `rouh-task meta <task> merge|append|set`.
A run of the one program in the `assistant` space works in a checkout of the workspace (`ONE_WORKSPACE`, `/srv/spaces/workspace`); one that also changes the code makes a checkout of `/srv/spaces/rouh` beside it and lands that with its own `./land.sh`, and a run in the code that has to write into a task does the opposite (`workspace_repo.code_run_note`, `ROUH_WORKSPACE_SPACE`).

**Nothing is ever discarded.** Before any resolution the work exactly as the job
wrote it is put on `land/pre/<run>/<attempt>`, and that branch is never deleted,
so every attempt is one `git checkout` away. Taking main's side keeps the job's
work there; dropping a duplicate keeps it on `land/dropped/<run>/<when>`.

The question reaches the person in four places, carrying enough with it that
they never have to go back to the conversation it came from: the orb goes red,
dashed and NEEDS YOU and pressing the red line opens the card; the job's row on
the task list turns red with the one line on it; Rouh reads them the line and
the four options and takes a spoken "take mine"; and it goes to Telegram if
they are away from the screen. The pick goes back to the same job, which
resolves, proves it in a browser again, pushes and deploys. `screenshots/`
has all three of those on screen.

**The cheap prevention comes first.** A job says up front which files it expects
to touch, and the program queues a job whose files overlap one already working
rather than starting both. A collision prevented costs the minutes the job ahead
was taking anyway; a collision resolved costs a whole turn of a model, or a
person.

## The one program

`one/` is a separate program, from task 30's step 07, running beside Rouh on
the same server as its own service, `one`, under its own Linux user. It holds
runs of Claude Code that a terminal can take over and hand back, writes
everything that happens into one list of plain text files, decides every tool
call a run makes, and answers a terminal, a browser, the phone and Rouh's
voice. Rouh reaches into it through `rouh/one_client.py`; it never reaches
back, and Rouh works exactly as before when it is not there. How to run and
change it is in `one/README.md`.

Because it is a separate service with its own checkout, `/srv/one/app`, the two
can come apart. On 16 September Rouh was deployed at `f4eb8a4` with a button
that archives a run, while the program behind that button was still at `5d1d755`
and had never heard of archiving; the only sign was an error in the browser when
it was pressed. It happened again on 19 September: Rouh reached `7596716`
while the program sat four commits behind on `6edd106`, because the automatic
deploy reached for the program's update script only when a change happened to
touch `one/`. A deploy runs `update-all.sh` now and moves both, which is the fix
for the cause; the marks below are what catches it when something has left them
apart anyway.

The marks are not on the screen any more.
On 13 October 2026 Petar had them taken off, with the socket's and the voice's icons beside them (fr_f247c02864da): "They're for debugging, and Rouh has been handling them very well".
The server still reads both commits and still sends them in `ready` and `one_version`, and `POST /api/one/deploy` still deploys the one program, but nothing on the page draws them or presses it.
What follows is how they worked while they were there.

So the foot of the sidebar carried a version mark for each of the two services,
lettered with that service's own initial, beside the person's own name.
They were in a bar across the top of the page until 20 September 2026, came
down into the sidebar's head with the name and the other two statuses when it
went, and moved to the foot on 23 September 2026.
Pressing one opens its two commits in a panel that rises out of it.
Each mark compares like with like: the commit that service is answering from,
against the commit `origin/main` is at in the checkout that service is deployed
from.
The jarvis mark reads `/var/www/rouh/app` and the one mark reads
`/srv/one/app`, and a mark goes amber when its own two commits differ in code.
A service whose checkout is ahead of it only under its content paths is current:
while the workspace was `workspace/` in the code repository, that was the
person's tasks, notes and pages, which `land.sh` moved onto without restarting
anything, so there was nothing to deploy. With the workspace a repository of its
own there are none, and every commit of the code is code. The mark stays green, shows
the running commit as Available, and its sentence says where `origin/main` is and
how many workspace-only commits lie between. The list of content paths is
`ROUH_CONTENT_PATHS`, the same setting `land.sh` and `update-all.sh` read, and
anything git cannot answer, or a running commit `main` does not contain, is
still called behind.
They used to be one pair that compared the one program's running commit against
Rouh's checkout, which is a different service's copy of the repository: those
two were never commits of the same thing, so they could never agree, and every
deploy of Rouh announced an update for the one program.
That is `rouh/versions.py`, which does the reading, with
`rouh/rouh_version.py` and `rouh/one_version.py` as the two marks.

The comparison is the commit and nothing softer. A version number is written by
hand and a fix that forgot to bump it is invisible, which is exactly the failure
the marks exist to catch; two commits either are the same commit or they are
not. The version a person says out loud is still on the screen, in Settings, and
the rule for moving the one program's is in `one/README.md` under "Its version".

Pressing the amber mark opens the two commits, and under the one program's a
button that says `Deploy 5d1d755`, naming the commit it is about to put there.
It fetches `main` into `/srv/one/app`, fast-forwards the checkout onto it,
installs the program's packages if `one/requirements.txt` was one of the things
that changed, imports the new code before anything restarts, restarts
`one.service`, and puts the old commit back if the program does not answer its
own health check within twenty seconds.
That is `one/deploy/update.sh`, which a person can also run by hand;
`rouh/one_deploy.py` is what starts it, refuses a second one while the first
is running, and tells every open tab how it went.
That button deploys the one program and nothing else, because a person pressing
it is asking for that program by name and is not asking to be restarted
themselves. Everything else that deploys - the voice asking, and a run's change
reaching main - runs `update-all.sh` and moves both services onto one commit.

When the two services are answering from different commits, both panels say so
in as many words, whatever each mark says about its own service: each mark only
compares its own service against its own checkout, so both can read "same"
while this machine is serving two versions of one repository.

## The backend: Django on PostgreSQL

Since 23 September 2026 Rouh is one Django project, on PostgreSQL, managed with uv on pyenv's Python.
Until then it was a FastAPI application whose stores each kept their own tables in one SQLite file; Petar asked for "something stable, meaningful, and secure", and the platform he chose was Django.

What that means, part by part:

- **The addresses are Django's.** Every address the page, the hooks and the deploy use is in `rouh/project/urls.py`, answered by a view in `rouh/web/`, and every one is the address it was, answering what it answered: the page did not change to fit the server.
- **The websocket is Django Channels** (`rouh/web/consumers.py`), on the same `/ws`, with the same messages (`PROTOCOL.md`), the same 4401 for a socket nobody is signed in on, and a refusal for one opened by a page on another site.
- **The data is Django models in PostgreSQL** (`rouh/models/`), made and changed by migrations (`rouh/migrations/`), with every table under the name it had. Each store - `memory.py`, `objects.py`, `crew.py`, `gene_therapy.py` (`feedback.py` until 12 October 2026) and the rest - kept its methods and what they answer, and reads and writes through the ORM underneath. The database carries out the same foreign keys and checks SQLite did, and the workspace's full-text search is PostgreSQL's own.
- **The sign-in is Django's**: accounts, sessions, password hashing, CSRF protection on every write, and the admin at `/admin/` for managing people. Rouh's own throttling of a wrong password is on top, and the way in is an email, a link or code sent to it, a passkey as an extra, or a password where no mail can go (see Signing in by email).
- **The process is still one process.** Rouh holds the voice, the task list's feeds, the background workers and the one program's socket open for as long as it runs; `rouh/runtime.py` is that, started and stopped by the ASGI lifespan (`rouh/project/asgi.py`). It calls its stores from the event loop as it always did, which is why `DJANGO_ALLOW_ASYNC_UNSAFE` is set for this process and nowhere else; the asgi module says why that is safe here.
- **uvicorn still serves it**, as `rouh.server:app`, so the systemd unit and `run-server.sh`, which live outside the checkout, did not change.
- **The database connections are lent from one bounded pool** (since 21 October 2026, task 137): Django's psycopg pool, `max_size` 50 (`ROUH_DB_POOL_MAX`), in `rouh/project/db/base.py`.
  A connection is taken for a unit of work and given back after it: by Django at the end of each request, by the gate as soon as the sign-in is read (so a stream such as Ask AI's answer holds none), by every `asyncio.to_thread` and Rouh's own thread pools once their thread has nothing to do (`rouh/dbwork.py`), by the loops that close after each beat, and whatever else happens when its thread ends.
  Background threads (named `synapse-...`, `slack-backfill`, `silos-refill`, `content-index`) share all but 12 of the pool, so a request always finds one; a connection a borrower left a `SET`, a session advisory lock or a temporary table on is reset before it is lent again; one the server closed is noticed without a round trip and replaced.
  When none is free in time (10 s, 2 s on the event loop's own thread) the request is answered 503 with `Retry-After`, never a 500, and `/healthz` says how much of the pool is out (`database_pool`).
  A new thread or thread pool that reads the database should be a `dbwork.Executor`, or be one of the threads above; until then every thread kept a connection for ever, and every web request left one behind until the garbage collector found it, which filled PostgreSQL several times an hour.

**How the move was made.** The deploy that switched the server to Django ran `manage.py predeploy` before restarting anything (`deploy/rouh.sh`): it made the PostgreSQL role and database, ran the migrations, stopped the old service, copied every row out of `/var/www/rouh/data/rouh.sqlite3` in one transaction (`rouh/sqlite_import.py`; about fifteen thousand rows in five seconds), and sent Petar his username and a new password **before** the new code started, by Telegram and by email from Rouh's own Google account, each tried and at least one required - it would have put the old Rouh back if the password had reached neither (`rouh/handover.py`). The SQLite file is left exactly where it was, read-only, as the record of the moment before the move. A rollback to a commit from before the move runs the old code on that file; the next deploy of the Django code notices the file has been written since and moves it again.

**The one program too.** Its web address (`one/web.py`) - the runs page, pairing a browser, its socket, a file dropped on a terminal, the phone's question page and every run's hooks - is a Django application built inside the program's own process, with Channels for the socket, the same Django and the same pins as Rouh (`one/requirements.txt`).
It has no database, no sessions and no middleware because it never had any: a browser is known by its device cookie, a phone by the token in a question's address, and a hook by coming from this machine.
The only things in the repository still written on FastAPI are the stand-ins in `rouh/testing/`, small web servers pretending to be Anthropic, Google, ElevenLabs and Telegram, which are not anybody's backend.

## Backups

Two, on the server, both whole.

- **Nightly, on this disk.** Debian's `pg_dump@18-main` timer dumps the whole PostgreSQL cluster (Rouh's database and the roles; the meeting library's too, until the library moved to a server of its own on 1 November 2026, which Rouh now reaches only at its public HTTPS address, `rouh/synapse/sources/meetings.py`) at 03:40 into `/var/backups/postgresql/18-main`, seven kept (drop-ins in `/etc/systemd/system/pg_dump@18-main.{timer,service}.d/`, 4 October 2026). They mend a bad migration or bad data, not a lost machine.
- **Weekly, off it, to Cloudflare R2** (Petar, 5 October 2026: "You have r2, setup weekly backups"). Sundays at 04:40 `rouh-offsite-backup.timer` runs `deploy/backup_offsite.py`: the newest nightly dump folder and `/var/www/rouh/data` (without `workspace-saves`, a checkout of main, and the SQLite left from before PostgreSQL), one tar encrypted with gpg AES-256 before it leaves, uploaded under `rouh-backups/<host>/` in the `notes` bucket, checked by size and SHA-256, eight kept. `/var/backups/rouh-offsite/last.json` says how the last one went.

What it needs is root-only in `/etc/rouh`: `r2-backup.json` (the R2 endpoint, bucket and key, the meeting library's, which reaches that one bucket) and `backup-passphrase`.
**A copy of the passphrase has to be kept off the machine** (a password manager), or the copies in R2 are lost with it. Not in any copy: `/var/www/rouh/.env`, whose keys come back from their providers; `ROUH_ENCRYPTION_KEY` among them opens the credentials kept in the database, so it is worth keeping beside the passphrase.

```bash
sudo deploy/install_offsite_backup.sh                                   # the timer, and the passphrase the first time
sudo /var/www/rouh/.venv/bin/python deploy/backup_offsite.py run        # a copy now
sudo /var/www/rouh/.venv/bin/python deploy/backup_offsite.py list       # what R2 holds
sudo /var/www/rouh/.venv/bin/python deploy/backup_offsite.py check      # the newest, downloaded, decrypted, every dump read back
```

Restoring: download the object, `gpg --decrypt --passphrase-file /etc/rouh/backup-passphrase <file> | tar -x`, then `pg_restore` each dump onto a PostgreSQL with pg_search preloaded (without it, its five objects fail and everything else restores).
The first copy (5 October 2026, 667 MB) was restored that way into a scratch cluster and matched the live tables row for row.

## Shape of it

| File | What it is |
|---|---|
| `rouh/server.py` | The front door: the ASGI application uvicorn serves, `rouh.server:app`, which is Django (`rouh/project/asgi.py`). The name stays because systemd and the deploy both say it. |
| `rouh/project/` | **The Django project.** `settings.py` (every value read through `config.py`), `urls.py` (every address Rouh answers, in one list), `asgi.py` (Django for HTTP, Channels for the websocket, and the lifespan that starts and stops the process), and `db/` (PostgreSQL, with a connection that heals itself after the database restarts). |
| `rouh/web/` | **The views.** `gate.py` is the sign-in gate in front of every address; `auth.py` signing in and out; `reset.py` a forgotten password; `signin.py` the signed-in side of signing in (Account's email and passkeys, a guest's way back in); `views.py` the page and its JSON; `gene_therapy.py` and `google.py` the Gene therapy board and Settings; `rules.py` the Rules page under the person's name (`rouh/rules.py`: rules loaded word for word into every turn, and the old memory to review, all in Synapse Master); `vocabulary.py` the person's Vocabulary in the Synapse lab (`rouh/vocabulary.py`), which reads and changes what the model's `remember`, `forget` and `list_memory` tools do; `assets.py` the page's own files; `consumers.py` the websocket, one per tab. A view reads the request, asks `runtime.py`, and answers: the work is never written here. |
| `rouh/models/` | **Every table, as Django models, in PostgreSQL**, with the names they had in SQLite. `rouh/migrations/` makes and changes them; the stores below still own what the rows mean. |
| `rouh/runtime.py` | The process. One WebSocket per browser tab, and one turn at a time per thread: a turn belongs to the thread it was asked in and runs to the end there, whatever the screen moves to. It was `server.py` until the move to Django, beside the routes; it is the stores, the voice, the tabs and the turns now, and knows nothing about HTTP. |
| `rouh/sqlite_import.py` | The move out of SQLite, once: every row, in one transaction, run by the deploy that switched Rouh to Django (`manage.py import_sqlite`, `manage.py predeploy`). |
| `rouh/handover.py` | A password is only set once it has been delivered, by Telegram and by email. What the cutover to Django did for the owner, and what `manage.py handover` does for anybody. |
| `rouh/templates/rouh/` | The page (`index.html`), the sign-in (`login.html`) and the gaps page, as Django templates. |
| `rouh/brain.py` | One turn of conversation, streamed, with tools. Cuts the reply into speakable sentences. |
| `rouh/llmlog.py` | **Every request made of a model, written down**: the one way an Anthropic client is made, the row it writes for each request, what was asked kept once as pieces, and `manage.py llm_log` to read it back. "The log of every request made of a model", above. |
| `rouh/luna.py` | **The same turn, answered by OpenAI's GPT-6 Luna** or any other OpenAI model a chat's tier is: Rouh's tools as functions, OpenAI's own web search with its footnotes, the marks, the voice and the rest, over the Responses API. What cannot be matched there is written at its top. |
| `rouh/speech.py` | Ears and mouth. Realtime transcription in, streamed synthesis out. |
| `rouh/tools.py` | Everything Rouh can do, including the worker tools. |
| `rouh/crew.py` | Background workers: tmux, git worktrees, Claude Code, and reading their screens. |
| `rouh/objects.py` | The five objects - project, task, chat, run, artifact - their two cascading children and the one link table that joins them, with at most one owner per object enforced by the database. **Projects nest and tasks nest**; a task may never own a project; and `content_file` holds a derived copy of what the workspace's files say. |
| `rouh/objecttree.py` | **The workspace as a tree of objects, and the one place that writes it.** The `.object.json` in every object folder, the migration map, taking the tree into the database, the single create path and the single move path (row first, then the folder, moved with `git mv`), `verify` for checking the two against each other, and the derived content index - which keeps itself up to date on a create and a move, and builds itself at start-up when it is empty. **And `tidy`**, the repairs the tree makes to itself whenever it is read: a second row claiming a folder is removed and what it held goes to the row the folder itself names, a project renamed in its committed sidecar is followed by its row, and a task in no project is filed into the fallback, folder and all. |
| `rouh/objectindex.py` | **The task browser**, in the canvas, drawn from the object rows rather than from the folders. The only one. Two columns, a button per project, the search, the keyboard and dragging a task onto a project; `rouh/static/taskbrowser.css` and `taskbrowser.js` are the page itself, and `menu.css` and `menu.js` the one menu every three dots open, all put into it rather than linked because a sandboxed frame would fetch them without a sign-in. `change` is what it writes, and it writes through `objecttree.py` like everything else. **And one object's own page**: a task is what is under it, and a project is that with a screen on it - what the project is for under its name, a box at the top that starts a chat in it, the files attached to it, its instructions (its own `AGENTS.md`), and the three dots that open Edit. `rouh/static/projectpage.js` is that screen, and everything it saves goes up through the page around it because a sandboxed page cannot write. A task's or a step's page has one control, Start chat, floating in its bottom right corner (`rouh/static/taskpage.js`), which always starts a new conversation about the task. |
| `rouh/docview.py` | **A task's notes, read.** Every `.md` in an object's folder is listed on its own page as Notes and opened there at `/workspace/_task/<folder>/?doc=<name>`: plain Markdown escaped and then shaped, or a `step.md` read with `steps.py`'s own parser. Behind the sign-in and out of Share's reach, which is why a note is read here and `pages.py` still never serves one. |
| `rouh/searching.py` | **Search over all five, and the files the person uploaded, as one question and one list.** The snippet, the ranking, and how each is opened; `ObjectStore.find` is the query underneath it, and `uploads.find` for the files. Nothing is indexed for the five - the words are asked where they already live. |
| `rouh/runs.py` | **The run register: every kind of running work as one type.** A background worker, a run of the one program and a sub-agent inside either are all rows of `run`, and the task list, `check_tasks`, `one_runs`, `what_is_running` and the orb are all answered from it. |
| `rouh/outbox.py` | **The worker outbox: what a job asks Rouh to email the person.** The `worker_outbox` table, the rules for queueing and marking a note, the person's own address, and the notes put inside a job's report. |
| `rouh/worker_mcp.py` | **Rouh's tools for every background job**, as an MCP server of its own that `mcp-servers.json` gives every agent: `notify_owner`, which queues a note and nothing else, and Rouh's own tools as its gateway lists them for the job (`rouh/job_gateway.py`), writing a file Rouh hands back into the job's working folder. Standard library only, run from the deployment's own copy. |
| `rouh/job_gateway.py` | **Rouh's tools for every background job**: whom a job works for, from the run register; its tools listed and run by Rouh's own code for `/internal/jobtools`; risky calls queued as one decision; `request_from_rouh` and its log, `job_requests`. |
| `rouh/job_policy.py` | **The one permission check for a job's call**: every tool's class (read, own work, risky, never) and the ruling for each scope, in code, failing closed. |
| `rouh/job_mail.py` | **Files out of mail for a background job**: the search and the file read with Rouh's own Google login, within the job's scope, for the gateway's `mail_find` and `mail_file`. |
| `rouh/starting.py` | **The one call that starts work.** `assistant_job`, `delegate_task`, `improve_myself` and `one_start` are presets over it, differing by a workspace and a policy; so is the Start box in the interface, with nothing preset. |
| `rouh/owning.py` | **Who owns what.** Attach and detach, what a person may be offered as an owner, what is under one object, and a run's diff as the artifact it is. |
| `rouh/conversations.py` | **The conversations: a chat is a row, a numbered task owns it, and the folder is written out from the row.** Loose chats, promotion, and reconciling the workspace on disk as an inbound change. Nothing here deletes a chat on a clock. **And nothing makes one before something is said in it**: opening a task and pressing New chat hand the page a draft - the id the chat will have, remembered in `app_state` - and `make` writes the chat, under that id and owned by what it was for, on the first turn or card (23 September 2026). |
| `rouh/emptychats.py` | The empty chats opening a task used to leave behind, and the rules that say which of them are provably that and nothing more. `rouh/migrations/0004_remove_empty_task_chats.py` removed those once, in the deploy; `manage.py empty_chats` lists every chat with nothing in it and why each is kept or not, and deletes nothing. |
| `rouh/memory.py` | The transcripts and the remembered facts, in PostgreSQL: the tape the model is replayed from, with its tool calls and the tries behind a question asked twice. What a chat **is** is next door, in `conversations.py`. |
| `rouh/rules.py` | **Rules, words and notes, in Synapse Master** (5 October 2026). A rule is how Rouh must act, told word for word to every turn, or when its person, task or project is involved; a word is what the person means by a name; a note is a fact in Synapse, found by search. The old `facts` wait on the Rules page with a proposed home each (`manage.py rules propose`), still told to every turn until moved. `keeping.py` keeps the project lookups and a project's rules for its page. |
| `rouh/chats.py` | What a chat is called: the model asked for a few words with an emoji in front, and the wrangling of what it answers. |
| `rouh/filing.py` | **Which project a new task goes in, decided by a small model.** Every project's description - the person's own words, written in Manage projects - and the task go to Haiku, and the one project it names is where the task is moved. An answer that names no project, and every way of not getting one, ends in the fallback project, Miscellaneous, rather than in a guess: there is no "Not sorted" heading for work to wait under since 23 September 2026, so every task is in a project and `objecttree.tidy` is what keeps that true. |
| `rouh/accounts.py` | Who may sign in, on top of Django's accounts: the old password hashes, the throttling of a wrong password, and `manage.py account`. |
| `rouh/admin.py` | The Django admin at `/admin/`, for whoever manages accounts: people, their organisation, whether they manage it, and an organisation's Google sign-in. |
| `rouh/settings.py` | **What one person has set for themselves**, as against what this machine is configured with, which is `config.py`. The orb's sliders are the first: they were a browser's local storage until 22 September 2026, so a look tuned on the desktop was not on the phone and went with that browser's site data. Keyed by who, both ids in every query, and the shape of what may be stored is checked here while what it means stays in the page that draws it. |
| `rouh/attachments.py` | Files the person attaches: on disk, in the message, in front of the model. |
| `rouh/uploads.py` | **The files the person uploads, found by what is written in them.** Which files were given, the one thread that reads and indexes them, `uploaded_file`, the catch-up at start, and `find`, which hands the search box its Files. |
| `rouh/extracting.py` | The words in one uploaded file, as Markdown, in a process of its own with a time limit and a memory ceiling. No Django, and it writes nothing. |
| `rouh/version.py` | Which build is running: the commit on the page, and the date and branch when asked. |
| `rouh/versions.py` | Reading a commit out of a checkout, once, for both version marks. |
| `rouh/jarvis_version.py` | The jarvis mark: the commit serving, against the one waiting in Rouh's own checkout. |
| `rouh/one_client.py` | The voice's way into the one program: its tools, its runs on the orb, its questions said out loud. |
| `rouh/one_version.py` | The one mark: the commit that program is serving, against the one waiting in its own checkout. |
| `rouh/one_deploy.py` | Starting a deploy: both services (`update-all.sh`), and the one program alone from the button under its mark. |
| `rouh/pages.py` | Your workspace's pages, served read-only to a signed-in session and kept apart from Rouh. |
| `rouh/sharing.py` | **Which of those pages are public**, and under what token, and what a visitor may do - read it, or change it with Ask AI; and **which people each is shared with** by email (`Guests`). The owner's side is scoped to them, `user_id` and `org_id` both; the visitor's side is one lookup by token and never a listing. |
| `rouh/web/guests.py` | **A page read by somebody who is not its owner**: the invitation and its letter, making an account from it, a guest's list at `/shared`, and one reader's page - the shared page in a frame with Ask AI in it - for a guest and for a visitor to a link that may change it. |
| `rouh/comments.py` | **Comments pinned to a shared page**: the threads and their messages, who may do what to them, who can be tagged, and the letters a tag sends. Everything is the page's as its owner shared it, `user_id`, `org_id` and path together. `rouh/web/comments.py` is its two routes; the page draws it all (`rouh/static/askai/comments.js`). |
| `rouh/mailer.py` | **Rouh's own letters**, through Brevo, from the installation's `ROUH_MAIL_FROM`: invitations, notes, a guest's password link, and the letter to somebody tagged in a comment. The key is in one file on the server, never here. |
| `rouh/artifacts.py` | **Everything Rouh puts out, as one thing.** A card, a numbered step and a built page are all `artifact` rows, versioned, each owned on purpose by a task, a thread or nothing. |
| `rouh/steps.py` | A step as one markdown file: the fence vocabulary, both faces of it, a task's steps, the index, and writing a card out into a task. |
| `rouh/askai.py` | Ask AI on a workspace page: the drawer (`rouh/static/askai/`, Rouh's own since the separate workspace was retired), the prompt, and the answers behind it. The **page** the retired proxy served is gone; the **drawer** is a live feature and is here. Since 23 September 2026 it is drawn in Rouh's own conversation column when Rouh is framing the page (`ASKAI_HOSTED`), so there is one chat on the screen rather than two; the drawer itself stays in the page for a reader who is not the owner. Since 24 September it **changes the page** too - the page's source in front of the model, one `edit_page` tool, every change kept whole so Undo can put it back - and knows exactly which element a reader pointed at (`pages.with_marks`). |
| `rouh/browser_handoff.py` | **A background job handing a step to the Live browser**: the statement a worker ends with at a login, a code, a captcha, a payment or a button that cannot be undone, finding it in a job's last message, and what Rouh is told and shows so the person does the step and the job carries on. |
| `rouh/pagehistory.py` | **A page's history, and the options kept over it.** Every change to a page - every Ask AI change, by whoever asked, and every version a job saved in git - each one openable as the page was then; and the changes kept as options, beside the page rather than in it (`page_options`), drawn over it by the Ask AI layer. "A page's history, and its options", below. |
| `rouh/reminders.py` | **Reminders**: things done at a time, once or on a repeat - a reminder said, or a job done - with the rule arithmetic on the person's own clock, the rows (`Reminder`), the words the page and the model are given, the note a due row starts a turn with, the loop that says a row when it is due, and the tools a turn nobody is watching may not use. |
| `rouh/goals.py` | **Goals**: a task tagged Goal, with what the person knows in `goal.md`, its plan as its steps and their parts, who does each and the hard parts, and its streams and what each waits on the person for, and every word the Goals list, a goal's own page and Rouh are given about one; the notes that start Rouh reading one and doing a step. |
| `rouh/timekeeper.py` | The one place reminders and goals are made, changed and said, for the tools and the two pages alike (`rouh/web/clock.py`): a goal's own chat and the turns started in it - reading it, doing a step now, at a time or after another - the `clock` message to the person's tabs, and saying a due row in its chat and on the phone. |
| `rouh/browsing.py` | **The Live browser**: the real browser Rouh drives for errands and the person watches, takes over and hands back. The `browser` tool's actions, the screencast to the tabs that are watching, the person's clicks and keys, the logins sealed per person (`BrowserLogins`), the SOCKS proxy that lets it reach nothing but the public internet, and the jail that keeps it off root. |
| `rouh/fetchfallback.py` | **A page web_fetch could not get, read again in a browser**: which of web_fetch's errors get a second try and which are refusals, cutting the reply at the failed fetch, the `browser_fetch` call Rouh adds and answers with what `browsing.Desk.read` read, and why the page goes back as text rather than as a cited search result. |
| `rouh/machine_load.py` | How busy this box is - CPU, processes and the machine's memory in use - in the few numbers the orb polls for. |
| `rouh/static/` | The page. No build step, no dependencies, no network requests. |
| `PROTOCOL.md` | The wire protocol, which is the contract between the two halves. |
| `TELEMETRY.md` | The work tree, and the orb that draws it. |
| `rouh/self_update.py` | The "Updating Rouh" card: written down before the restart, finished by the Rouh that comes up after it. |
| `update-all.sh` | **The deploy, and the only one.** Both services onto one commit, the one program first and Rouh last. |
| `deploy/rouh.sh` | Rouh's half of it: pull, install with uv, `manage.py predeploy` (the database, the migrations, the move out of SQLite once, the owner's password once), restart, health check, and roll back if any of it broke. Refuses to run on its own. |
| `pyproject.toml`, `uv.lock`, `.python-version` | The project, managed with uv on pyenv's Python 3.12.14. `rouh/requirements.txt` is generated from the lock for the deploy. |
| `manage.py` | Django's command line: `migrate`, `account`, `import_sqlite`, `handover`, `predeploy`, `empty_chats`. |
| `verify.py` | Checks against the live site, through the public address. |
| `run-local.sh` | Rouh on the laptop: `uv sync`, PostgreSQL (the laptop's own, or `ROUH_LOCAL_PG=1` for a cluster of its own), the keys read from the workspace's `.env`. |
| `one/` | The one program, beside Rouh: see above. |
| `tests/e2e/conftest.py` | The harness: a real server on a free port, with an account, a workspace and no keys, thrown away afterwards. No tests, by design. |
| `tests/e2e/serve.py` | The same worlds, stood up and held, for a browser driven over Playwright MCP. |
| `e2e.sh` | Builds `.venv-e2e` and the browser, and `./e2e.sh serve` stands a world up. |
| `.mcp.json` | Playwright MCP, so a worker here has a real browser without being asked for permission. |
| `mcp-servers.json` | The MCP servers every agent on this machine gets, wherever it runs: Playwright, and Rouh's own `rouh/worker_mcp.py`. `{repo}` in it is the checkout it is read from. |
| `AGENTS.md` | The standing instruction for anyone working here, whatever agent they are, starting with the browser rule. It was `CLAUDE.md` until 26 September 2026, and there is deliberately no `CLAUDE.md` anywhere in the repository, because Claude Code reads `AGENTS.md` only where none sits in the folder or above it. |

## Running it

Rouh is a Django project on PostgreSQL, managed with uv on pyenv's Python (23 September 2026; until then it was a FastAPI app on one SQLite file).

```bash
pyenv install 3.12.14                 # the interpreter .python-version names
uv sync                               # .venv, exactly what uv.lock says
createdb rouh                         # or ROUH_DB_* to point anywhere else
uv run manage.py migrate
uv run manage.py account add alex --generate
export ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=...
uv run python -m uvicorn rouh.server:app --host 127.0.0.1 --port 8021
```

`./run-local.sh` does all of that on the laptop.
**As containers** (since 20 October 2026, task 98 step 98-05 WP9): `deploy/container/` has Rouh's three images (core, workers, key proxy) for Intel and Arm and a Compose stack with PostgreSQL 18 and pgvector; a fresh one makes its owner at `/setup` with the code in the core's log (`rouh/web/firstrun.py`). Its README says how the parts are kept apart and, plainly, what does not work there yet.
On the server nothing is run by hand: the deploy installs, migrates and restarts (`deploy/rouh.sh`), and the database was made by the first deploy of the Django code, as the role `rouh` with its password in a file only root can read.

Settings are all environment variables and all listed in `rouh/config.py`, each
with the reasoning next to it.
There is no setting for access: see below.

Chats are of two kinds, and each kind has its own rules and its own model (`rouh/chatkinds.py`, since 26 September 2026).
**General** is the conversation that is always there and never ends: it is sent a window of its newest 40 messages (`ROUH_HISTORY_TURNS`) with the old tool results in that window trimmed (`rouh/context_editing.py`).
**Every other chat** - a topic, a task's thread, the chat an email is handled in, a fork - is sent whole, every message and every tool result as it came back, with nothing trimmed or summarised.
A fork carries the chat it came off the way that chat is sent, so a fork of General carries General's window.
A chat too long for its model is never cut to fit: the model refuses it, and the person is told so in a notification that stays until they dismiss it.
Both kinds keep the prompt cache, which changes what a request costs and never what it says.

**Which model answers is set in Settings, under Models, as a mode, two tiers and a tier for every use** (`rouh/modeldefaults.py`, since 18 October 2026, when Petar asked for it because "most Rouh users will not know which model to pick").
- **The mode**, since 23 October 2026 (card 1842), the one choice most people see: **Best** answers every chat message on Smart; **Balanced**, the default, has the router decide each one; **Saver** answers them on Cheaper, and puts every use paid per token on Cheaper too, except the runs that go through a subscription the person already has (Claude Code and Codex runs, `Use.subscription`), which keep Smart. Picking Saver says once that unattended runs on the cheap model can make mistakes and deploy them. A locked use keeps its own whatever the mode, and a Codex run whose ChatGPT subscription runs out in Saver waits for it to reset rather than being offered the API key (`one/billing.py`, `saver`, from `model-mode.json` in the landing directory). A run started from a turn Cheaper answered carries the person's own words, and is told to check its brief against them (`tools._with_their_words`). Everything else is behind **Customise**, closed until pressed: the router's bar, the two tiers, and every use.
- **Two tiers** since 23 October 2026: **Cheaper** (GPT-6 Luna, and Haiku 4.5) and **Smart** (Opus 5.5, and GPT-6.1 Sol), Smart being what Daily was; Best (GPT-6 Astra) went, and anything that names Daily or Best means Smart (migration 0210 moved every organisation's own settings). Until then: **Three tiers**, each holding one of OpenAI's models and one of Anthropic's, one of the two its main one: **Cheaper** (GPT-6 Luna, and Haiku 4.5), **Daily**, the daily driver (Opus 5.5, and GPT-6.1 Sol), and **Best**, the most capable and the most expensive (GPT-6 Astra, and Fable 5.1). Daily was called Recommended until the evening of 18 October 2026; "recommended" now only names the dot on the standard's own choice. Pressing a tier opens a chooser with OpenAI's models and Anthropic's side by side, with the Main switch over them; each press is saved, and Done closes it. Every use asks the tier's main model, except the few that truly can only ask one company (Claude Code runs, Codex runs, Ask AI's and look_into's loops), which ask the tier's pick of that company; their (i) says why, and the tier's card shows that pick under its own only while such a use is on it. Petar, that evening: until then a use that could only ask Anthropic answered with Haiku 4.5 while every tier on the page said an OpenAI model, which was hidden behaviour; and most of those uses could only ask Anthropic because they were handed Anthropic's client. Now everything that asks one question asks it through `rouh/llm.py`, of either company, and **nothing swaps a model**: one that cannot be asked here (no key for its company) is said in plain words under the use, and the call fails rather than asking another.
- **Every use of a model is on a tier, or on a model of its own**: Rouh itself (General and its forks), every other chat, a chat's title, a run, Ask AI and every other place Rouh asks a model (`USES`), each one line on every screen: its name, an (i), one control of icons (Cheaper a leaf, Daily the sun, Best a star, Custom sliders, and Off for the one use that may be off; no use has an Auto of its own) with a dot on the standard's choice, and a lock. **Custom** opens the same chooser for that use alone, and the control then shows the model and its level ("Sonnet 5 · High"). The exact model and level a use asks is in its (i), in each icon's tooltip, and beside the control when the card is wide enough. The heartbeat's wake-up check may also be off.
- **Routing** (`rouh/modelrouter.py`), since 23 October 2026: in Balanced, for the chats the standard marks `routed`, OpenAI's Decisions API on GPT-6 Luna reads each message with the last few turns and the chat's title and says how sure it is that the message is easy; Cheaper answers only at or above the bar (0.9 from the service, changed under Customise), and below it, or when the router is off, slow (`ROUH_ROUTER_SECONDS`, 8 s), refused or failing, Smart answers. No reasoning step, and the prompt cache a switch loses is not weighed. Its decision is sent the moment it is made, on the turn's timeline (`rouh/turntrace.py`), so the "Model decision" line no longer waits for the question to be written. What follows is the router of 18 October, now gone: with Each use on Auto, for the uses the standard marks `routed` (Rouh and every other chat), before each turn a model reads the message with the few before it and picks Cheaper, Daily or Best, never a model, by judging as a whole how complex the message is and how much it matters. Petar: "No quick rules. Just look at the complexity and try to decide on that as a whole." Its prompt describes the three tiers and asks for that judgement, with no rules or examples. The router is its own use ("Choosing the tier on Auto", Cheaper), thinking as little as its model allows; it runs beside the memory look-up a turn does anyway, and a router that fails, answers nonsense or takes longer than `ROUH_ROUTER_SECONDS` (2) leaves the turn on Daily. The tier is decided once, and the turn keeps its model through every tool loop; the router is told the tier the conversation was last answered on, so it moves when a message calls for it. Under each answer on Auto an (i) says the tier, the model and the router's one line on why, read back with the conversation.
- **How deeply a model thinks comes with the model**: one level each, from its benchmarks and score cards, with the reason and the source (`rouh/model_standard.json`, `efforts`). Opus 5.5 thinks at medium wherever it answers. Nobody picks a level.
- **Every call goes through the model selection** (Petar: "Whatever we select here should be the one called. No exceptions"): one question through `llm.ask(use, ...)`, and the loops (a chat's turn, Ask AI, look_into, Synapse's engine) with their use's model; Synapse's six model jobs are uses on the page (group Synapse) rather than numbers of its lab, and the judge of double calls is one too. `python -m rouh.llmguard`, run by `land.sh` and the deploy, fails on a model asked past the LLM service or named in code. Not on the page: Synapse's embeddings, which belong to a dataset's stored vectors, and the picture models, picked in the picture editor.

**The standard.** The tiers, the levels and the tier each use starts on are one small versioned JSON document, the model standard (`rouh/model_standard.json`, its shape `rouh/model_standard.schema.json`, version 3, checked by `modelstandard.check`). Version 3 has two tiers, `cheaper` and `smart`, and adds `modes` (what each mode means, and the default) and `router` (`bar`); version 2, three tiers, is still read, its `daily` being Smart and its `best` dropped. Version 2 gives each tier `main`, `openai` and `anthropic`, and calls the middle tier `daily`; version 1, a tier's `model` with a stand-in of each company and a middle tier called `recommended`, is still read.
Petar sets it, and publishes it at https://rouh.land/models/standard.json (the site's `rouhit/standard/models.json`, shipped with its `deploy.sh`; task 98, step 98-11).
Every Rouh fetches it once a day (`modelstandard.fetch`, `ROUH_MODEL_STANDARD_URL`), and a fetch that fails keeps the last good standard, is written down quietly (`app_state` `model_standard_fetch`) and is tried again an hour later.
**Auto, Sync and locks** (Petar, the evening of 18 October 2026: "sync and share should be one toggle. You get the benefit of optimized models if you share stats and double calls", then "Auto should be an option to the right of title in model boxes ... Auto is a toggle. Sync is a one time button press", and then "Single items like Rouh should not have individually auto"). Each of the page's two boxes, **Models** (the three tier cards, `auto_tiers`) and **Each use** (`auto_uses`), has its own **Auto** switch right of its title, on by default and independent of the other, with an (i) beside it in one or two sentences. A box on Auto follows the **Rouh model service** on rouh.land, the daily standard: every item in it is what the standard says, except what is locked, and every selection in the box is shown but cannot be changed (the locks still can). With Each use on Auto, Rouh and every other chat are routed where the standard says (`routed`, below). Until 24 October 2026, while **either** box was on Auto the day's anonymous counts went to rouh.land and Rouh took part in **double calls**; since then each is a choice of its own (Sharing, above): for the share of read-only answers the standard says (`double_calls.rate`, 2% to start), such as titles, filing, summaries and plain answers, never anything that sends, buys or changes something, the same request is asked of a second model (the tier's other company's, or the next tier's) after the person's answer is given, a judge on the Cheaper tier (use `double_judge`) says which was better, and only that conclusion is kept (`model_double`) and counted, never the request or the answers (`rouh/llm.py`, `modeloutcomes.note_double`); each (i) says what double calls added this month. Auto off in a box: the organisation's own **manual settings** apply there and can be changed (`manual`, written from what everything showed the moment Auto goes off), and no standard moves them; they are kept while Auto is on, so turning it off again brings them back exactly. **Sync**, a button in each box shown only while that box's Auto is off, is a one-time press: that box's manual settings made what the service says now, except what is locked, with no confirmation; what it replaced is kept (`undo`) until the next change, and an Undo notice after the press puts it back. Every tier card and every use has a **lock** (`locked`): a locked item keeps its own manual value, which Auto, Sync, Reset to defaults and a new standard leave alone (locking one while Auto is on keeps what it shows). **Reset to defaults**, in a box with Auto off and only while something in it differs, puts that box's manual settings not locked back to the standard built into this Rouh, with the same Undo. There is no per-use Auto: routing a chat's messages is the service's (`uses.<id>.routed`; revision 2026-10-18.2's `"tier": "auto"` is read as Daily and routed), only with Each use on Auto; with it off a chat answers on its own tier. "Join the Rouh pool" and "Copy from pool" were these until the evening of 18 October 2026 (migrations 0185 and 0186).
To publish a new standard: change `rouh/model_standard.json` here, move its `revision` on, copy it to the site's `rouhit/standard/models.json` (with `$schema` pointing at rouh.land), and run the site's `deploy.sh`.

Only an administrator of the organisation may change them, in three ways that all do the same thing: the Models page in Settings, which saves a press the moment it is made; asking Rouh, which has the `model_defaults` tool (a tier and a model, or which company's pick is main; a use and a tier or a model of its own; a lock; sync on or off; `copy_from_sync`; or `reset`); and `python manage.py model_defaults` on the machine (`--tier cheaper=claude-sonnet-5`, `--main daily=anthropic`, `--use chat_title=daily`, `--use run_summary=claude-sonnet-5`, `--lock code_runs`, `--unlock best`, `--sync off`, `--copy-from-sync`, `--reset`, `--fetch-standard`).
**When Petar asks for a different model for something, it is these values that change, not the code.**
Every turn, run and feedback reads them fresh, and every open tab is told when the page or Rouh changes them.
There is no box beside the composer any more: until 18 October 2026 a model could be picked there for one chat (`chat.model`), and that pick, its column and the two old pairs of a model and a level are gone.
A run of the one program is told the model and the level by Rouh for every run Rouh starts; one started from a terminal or from the program's own page gets the program's own, Opus 5.5 at medium (`ONE_MODEL`, `ONE_EFFORT`).

**Four providers, ordered lists, and an order for each use** (Petar, 24 October 2026; `rouh/modeldefaults.py` and `rouh/modelstandard.py` hold the decisions in their docstrings).
Rouh asks Anthropic, OpenAI, Google (Gemini) and xAI (Grok); Google's and xAI's keys are typed into Anatomy, Behaviour, Models, under Providers, and kept sealed per organisation (`rouh/providerkeys.py`, table `model_provider_key`), never shown again but for their last four characters; an installation may also set `GEMINI_API_KEY` and `XAI_API_KEY`.
Both are asked through their OpenAI-compatible Chat Completions endpoints, through the clients that write every request down with its cost (`llmlog.compat_client`, `costs.PRICES`), one question in `rouh/llm.py` and a chat's turn in `rouh/compat.py`.
Each tier is an ordered list of models across the providers (standard schema 4, `tiers.<tier>.models`), and so is a use on models of its own (Custom); a use asks the first model on its list whose provider has a key here, so an install with one provider's key works end to end, and each use has its own order for each tier in the standard (`uses.<use>.order`), which rouh.land moves from that use's blind votes.
The default order until there is data is Anthropic, OpenAI, Google, xAI, except that Cheaper keeps GPT-6 Luna first, the model it ran on the day the lists came; the two-company tiers kept before are read as their main model, then the other, then the standard's Google and xAI models, so nothing anybody ran on changed.
A use tied to one provider says what it does without that provider's key: Claude Code and Codex runs sign in on their own subscription; Balanced without OpenAI asks the cheapest model a plain "easy or hard?" question (use `router_question`); Ask AI, its comment pass and look_into answer as one plain question to the first model there is.
**A job asked for with an OpenAI model is a run of Codex** (Petar, 9 November 2026, task 178).
Two jobs asked for "with openai astra" started as Claude Code, which then ran `codex exec` inside them: eight Codex sessions spent the ChatGPT plan's five-hour window and showed nowhere.
Now a request that names Codex, an OpenAI model (Astra, Sol, Luna, Terra, or an id from `config.OPENAI_CHOICES`) or OpenAI as who does the work starts as Codex on the ChatGPT subscription with that model, unless the tool's agent "claude" was passed on purpose (`rouh/codex_route.py`, `starting.route_to_codex`); the run's brief keeps the sentence saying which word did it.
Astra and full model ids count anywhere, as whole words ("astral" is not Astra); Sol, Luna, Terra, Codex and OpenAI count only as who does the work ("with Luna", "using Codex"), so a brief about Luna's voice is not routed.
A run that still calls Codex inside itself shows it on its page: every rollout under `~/.codex/sessions` whose folder is the run's, counted by the one program (`one/codex_usage.py`, the `codex` field of its `run` answer): sessions, turns, tokens, model, plan, the five-hour and weekly windows with when each resets, and "Out of credits" when Codex stopped on it.

The chooser on the Models page edits a list: arrows move a model, a cross takes it off, and every provider's models are listed under it to add.
Test worlds: `talking_openai`, `talking_google`, `talking_xai`, `talking_nokeys` and `talking_all` (`tests/e2e/serve.py`), with `rouh/testing/fake_compat.py` standing in for Google and xAI.

**Sharing, two choices of their own** (Petar, 24 October 2026), on the Models page's Sharing card and no longer part of Auto: **Share anonymous totals with rouh.land** (`share_totals`, on unless turned off; migration 0213 carried each organisation's Auto over), with **See exactly what was sent** (`GET /api/settings/models/sent`, the payload as it was kept), and **Compare answers blind** (`compare`, off until turned on, `compare_per_day` at most a person a day, 1 to start), which says plainly that it sends the request to a second provider.
With comparisons on, now and then a chat's answer that was words alone, with no tool called, is also asked of the first model on the same list from another provider, after the answer was shown; a comparison appears under it (`model_compare` on the socket, `app/compare.js`): A and B, names hidden, sides shuffled, and A, B, Tie, Neither, Skip; ignored is Skip, with no notice.
Only the use, the two models, which side was which and the vote are kept (`model_vote`) and sent (`rouh/modelvotes.py`); the double calls of 18 October, judged by a model, run only with comparisons on too, since they also send a request to a second provider.
How often a comparison is offered is `ROUH_COMPARE_CHANCE` (0.25).

**Which model succeeds** (`rouh/modeloutcomes.py`, table `model_outcome`).
Every call to a model is written down as a small conclusion, never its words: the use, the tier, the model, the level, whether it worked, why not, the cost and how long it took.
A call is a turn with every request it made, a run of the one program, or one request of anything else, and it is written from the log of requests (`llmlog`), so every call Rouh makes is one.
A turn on Auto is written down with the router's tier, its reason, how long it took and what it cost, and its counts are kept apart from a fixed tier's (`auto` in the payload, with the router's cost, median time and how often it fell back), so the data shows whether Auto does better.
It is a failure when the person asks the same thing again within five minutes, presses Redo, stops the answer (Stop, or talking over it), says it was wrong ("no", "that's wrong", "I meant"), or rejects what a model made with a reason (Mutations' Reject, against the night's run); a run is a failure when it ends failed, unfinished, lost or refused. Anything that nothing found wanting within five minutes is a success, one shot.
Since 24 October 2026 a call nobody did anything about within five minutes is only quiet, never a success, and none of these signals ranks a model: they and each call's errors, cost and time are measurements for troubleshooting and reliability; what ranks models is the blind votes.
Once a day each organisation that shares its totals sends counts per day, use, tier, model and level (calls, each signal, errors, cost, time), the double calls and the votes to `ROUH_MODEL_OUTCOMES_URL`, with one word that tells installs apart and nothing else, a hash of a secret kept here, the organisation and the month (payload schema 3): no words, no names, nothing that says whose Rouh it is.
rouh.land leaves out any model or use from fewer than 20 installs before it uses or shows it, and keeps and logs no address of the sender for that route (`rouhit/outcomes_views.py`, `rouhit/rankings.py`).
Sending is a dry run unless `ROUH_MODEL_OUTCOMES_SEND` is set (off by default since 24 October 2026, until Petar switches it on): every day the payload is made and kept as what would have been sent (`app_state` `model_outcomes_sent`), which is what See exactly what was sent shows. A day's payload is split into posts of at most 60 KB.

The 5 generation thinks adaptively of its own accord, so the level is the only thing that says how deeply, and it refuses a temperature, a top_p, a top_k or extended thinking set by hand with a 400 on every turn - none of which Rouh sends.
The request is built for whichever model answers: Haiku 4.5 is of the generation before, and takes neither a reasoning level nor adaptive thinking, so none is sent with it, and the standard gives it none.
**GPT-6 Luna**, OpenAI's `gpt-6-luna`, is asked through OpenAI's Responses API by a loop of its own, `rouh/luna.py`, so nothing about Anthropic's models changed with it.
It needs `OPENAI_API_KEY` in Rouh's service environment - on the server, a line `OPENAI_API_KEY=sk-...` in `/var/www/rouh/.env`, then `sudo systemctl restart rouh` - and without one a tier on an OpenAI model says "No OpenAI key here" and its uses ask the tier's Anthropic stand-in instead; the start-up log says which (`luna=` in `rouh.log`).
It reasons at the level that comes with it, and every tool, tool search, the web search and its footnotes, the turn marks, the voice, trimming, attachments, the log of requests and Stop work on it; what has no match on OpenAI's side, and what it does instead, is at the top of `rouh/luna.py`.
Opus 5 is not offered anywhere any more: since 24 September 2026 a model setting, a fallback list or a page still showing the old list that names `claude-opus-5` is read as `claude-opus-5-5` (`REPLACED` in `rouh/config.py`).

## Signing in

Every address Rouh answers on is behind an account.
There is no shared word and no way to turn the sign-in off - until 16 September 2026 there was one shared passphrase in the environment, and an empty one meant "open to anyone", which is not a switch that should exist on a machine that is on the internet.

Accounts are Django's, in PostgreSQL, with the organisation a person is in and whether they manage it added on top (`rouh/models/accounts.py`).
A password is stored by Django's scrypt hasher with its own salt and the cost written into the stored string; nothing anywhere can turn one back into a password.
The hashes the SQLite accounts table held were carried over as they were and are read by `rouh.accounts.LegacyScryptHasher`, which Django rewrites into its own format the first time each is used.
Make an account, or change a password, with the admin command:

```bash
# on the server, as root
cd /var/www/rouh/app
/var/www/rouh/.venv/bin/python manage.py account add alice --email alice@example.com --generate
/var/www/rouh/.venv/bin/python manage.py account passwd alex
/var/www/rouh/.venv/bin/python manage.py account list
/var/www/rouh/.venv/bin/python manage.py account signout alex
/var/www/rouh/.venv/bin/python manage.py handover alex       # a new password, sent by Telegram and email
```

`python -m rouh.accounts ...` still works and runs the same thing.
`--generate` makes up a password and prints it once; it is stored nowhere it can be read back.
Without it you are asked for one, and it is never echoed and never taken from the command line unless you put it there yourself.
Changing a password signs out every browser that was signed in as that account.
The command writes the database the running server reads, so a new account works on the next request with no restart.
`--staff` makes an account that may also open the Django admin at `/admin/`, where people are added, moved between organisations, switched off and given passwords.

**A forgotten password.** The sign-in page has "Forgot password?" beside the password box (`rouh/web/reset.py`, `rouh/password_reset.py`).
The person types their username or the email on their account, and is told the same thing whoever they are, in the same time, so the page never says which names have an account.
For an active account with a password, Rouh makes a link with Django's own reset token: it works once, for an hour, and dies when the password changes or the account signs in.
Rouh has no mail server, and a server-wide mail account would be the global credential the house rules forbid, so the link goes out through the Google account that person connected in Settings, to that account's own address.
It is their own credential, used for them, to a mailbox Google has vouched is theirs; an address typed onto the account by an administrator is never where a link goes.
An account with no connected Google account that may send mail cannot be reached, and the page says so to everybody alike: ask whoever runs your Rouh, who uses `manage.py account passwd` above or the admin.
Setting the new password goes through the same validators as everywhere else and signs the account out everywhere, so the old password and the link both stop working.

**The rules a password is held to** are Django's validators as `AUTH_PASSWORD_VALIDATORS` in `rouh/project/settings.py` sets them: at least 10 characters, not too like the person's name, username or email address, and not one of Django's twenty thousand common passwords.
Both forms that set a password, the invitation's and the forgotten password's, list exactly those under the password box, read out of the settings (`rouh/password_rules.py`), with one line of the form's own, the same password in both boxes.
Each line turns green with a tick as the person types (`rouh/static/password-rules.js`, which judges each rule the way Django does), so when every line is green the server takes it.
Nothing typed leaves the page to be judged: the common-password list is fetched once, from `/login/common-passwords`.
The link's token is kept out of the address as soon as it arrives, and out of the log: uvicorn's request lines and Django's go into `rouh.log`, which other users on the machine can read, so `HideResetTokens` blanks it there.
At most three emails go to one account in an hour, and one address may ask six times in a quarter of an hour before it is told to wait.

**Signing in by email** (4 November 2026, `rouh/signin.py`, `rouh/web/auth.py`).
Petar: "Google is just a source of data. It never decides who you are", and "passkey/face/touch should be extra, not default".
The sign-in page is one email box and Continue, for the owner and every guest alike, and Rouh decides what follows; the person never picks a method.
- A passkey this browser added for that email (remembered in the browser only, so the server is never asked) is offered first, with "Send me a link instead" under it.
- Otherwise, when this Rouh can send mail, a letter with a link that works once for 15 minutes and a six-digit code for reading it on another device, and the page says "Check your email". A Rouh connected to a rouh.land account sends it through rouh.land (`birth.sign_in_letter`, from noreply@rouh.land); else through the owner's connected Gmail, as Rouh; else through this installation's own mail service (`rouh/mailer.py`).
- Otherwise a password, set once at the first run for the owner and when a guest first opens their invitation. Once mail works the password stays a quiet fallback under "Can't get the email?", never offered beside the link.
The page answers the same for every address, the letter is sent after the page has answered, and the limits count unknown addresses alike: one letter per address every 30 seconds, five an hour, twenty an hour from one place, five wrong codes per letter.
A link opened in a browser other than the one that asked shows one press first, so a mail service that opens links to check them never uses one up.
The addresses that sign people in are their own table (`sign_in_emails`), apart from the account's contact email; a changed address keeps the old one working until the new one has signed in once, so a change can never lock anybody out.
Whether somebody may come in is never asked of rouh.land: if it is down, or the account there is gone, only the mail route falls back.
**Recovery**: by link when there is mail; without it, the owner types the Rouh's twelve recovery words (`/login/help`); a guest asks the owner, who sends a new sign-in or makes a one-time link from the guest's contact card (`rouh/web/signin.py`).
**The way in when everything else fails**: `python manage.py signin_link EMAIL` on the machine prints a one-time link and code; `python manage.py signin_email list|set|remove` shows and changes who signs in with what.
**Connected to rouh.land, one email runs both**: rouh.land's signed status answer carries the account's email and whether it is an administrator's, and the owner's sign-in here follows it (`signin.follow_land`); Connect opens rouh.land with the owner's email filled in, and a different one is warned about on both sides and moves the Rouh's sign-in only once rouh.land holds it, proven by its link. Disconnecting keeps the email, stops Gene Pool sharing, and leaves the rouh.land account as it is.
Signing in with Google, and making an account through Google, were taken out the same day; Google stays connected as mail, calendar and Drive only.

### Sharing a page with a person

> "I invite a specific person with a specific email. If that person doesn't have an account, he receives an email saying he needs to register. They can register, and when they go to the website, they would see the thing I have shared with them. That would be like the guest account: just a list of the things that have been shared with them, and then they can use the Ask AI active feature... If they have an account, they're just notified that there is a new thing that's been shared with them."

**Add people by email** on the panel takes an address and **Can edit** or **Can view**, and **Invite** shares the page with that address (`page_guests`, one row per page per address) and sends a letter from Rouh's own address.
**Since 11 November 2026 (task 176, step 176-26) rouh.land says who they are** (`rouh/landshare.py`), on Petar's word: "make the sharing now work through rouh.land, not through people making accounts in your own rouh installation."
The letter links to the share on this Rouh's relay address (the phone's), and somebody not signed in goes to `/shared/in`, then to rouh.land's `vouch/` page, where they sign in with the one-email sign-in, or create a rouh.land account themselves if they have none, and press Continue.
Since the evening of 11 November 2026 nobody gets an account by opening a link (Petar: "people should not have accounts in places they did not explicitly agree to signup for"): `/shared/in` first says who shared what and that a rouh.land account is needed to view it, with two presses, **Create a rouh.land account** and **Sign in**, and rouh.land's sign-up asks for a ticked box agreeing to its Terms and Privacy Notice and makes the account only when the emailed link confirming the address is pressed; its sign-in link never makes one.
rouh.land sends them back to `/shared/in/back` with a note of their email signed by its own key (kind `rouh-identity`), which this Rouh holds to its signature, to itself, to its relay name, to the one-time state in that browser's session and to its five minutes; the share then lets in only the address it names, view or edit as before.
rouh.land never sees what was shared: it only vouches for an email.
What is kept here is a bare guest record by that email with rouh.land's id for it (`User.land_id`): no name, no password, and no sign-in of its own (`landshare.may_stay` ends any other).
A guest from before keeps their account and its sign-in until they first come in through rouh.land; an account of this Rouh's own people is never signed in on rouh.land's word.
A Rouh On its own cannot share with a person and says so (`landshare.refusal`); public links are unchanged.
**Before then, and still on a Rouh On its own for an invitation already sent:** somebody with no account yet gets an invitation: `/join/<token>`, where the address is the invitation's and cannot be changed, and they give their first name and last name, both of them, kept apart on the account, and, only when this Rouh cannot send mail, a password. Opening the invitation proves the address; from then on they sign in by email (above), to this Rouh. On a Connected Rouh `/join/<token>` now goes straight to the share.
Every invitation to the address is put on the account (`Guests.claim`), and somebody whose address already has an account is signed in to it instead.
The invitation sends somebody who already has an account to the sign-in page with their address filled in (`/login?next=/shared/<token>&email=`), so the link works the second time as well.
An empty name is refused by the server as well as the form, and the form says under the box which one is missing.
Somebody who already has an account gets a note that there is something new, linking straight to it.
Everybody the page is shared with is listed under who has access, with whether they have an account yet and what they may do, and the cross beside each one stops it at once.

> "When sharing a link with someone send them an email with the link... If the sharing is done manually through the ui, have an option to send email or not, default yes, and let me edit the message. A little bit like how Google Drive sharing does it" - Petar, 13 October 2026 (fr_55056f9ffcc2).

So, as soon as an address is typed, **Notify by email** appears under it, ticked, with a message box filled with a line he can change or clear.
Ticked, the button says **Send**, and the letter carries his message between what was shared and the link to it (`share_and_tell` and `_letter` in `rouh/web/guests.py`).
Unticked, the box goes, the button says **Share**, the page is shared and no letter goes, and the line under the box says so, and what that means for somebody with no account yet: they cannot open it until they are sent the invitation.
Such a person's row says **not emailed**.
Asked from a chat, or done by something scheduled, there is no box to untick: `share_with_person` always sends the letter, and Rouh says in its reply that it went and to whom.

The page itself is `/shared/<token>`: the same reader's page as a changeable link, answering only somebody signed in with that address, so a forwarded letter is a sign-in page and nothing more.
`/shared` is everything shared with the address signed in, which is the whole of what a guest has.

An account made from an invitation is a **guest** (`users.is_guest`), and the gate holds it to `/shared` and signing out (`rouh/web/gate.py`): every other page sends it to `/shared`, every other route answers 403, and the socket the voice rides on closes on it.
It belongs to no organisation - it is never adopted into one, never an administrator of one, and never "the one account" a background job falls back to (`rouh/tenancy.py`).
Its name to sign in with is its address, and the sign-in page takes an email address for anybody now.
A guest who forgets their password is sent the link at the address the invitation proved, from Rouh's own address, because they have no Google account to send it through (`rouh/password_reset.py`).
A guest may ask two hundred questions a day.

### Comments on a shared page

> "On the collaborative page, where I have shared it with other people and they can use the Ask AI feature, I'd like to be able to ... add comments in the style of Figma ... make the interactions with comments the same as in Figma. Whatever hover does, do the same thing. Whatever click does, do the same thing." - Petar, 24 September 2026 (fr_5879c0745f99).

The page carries it all itself (`rouh/static/askai/comments.js`), beside the Ask AI drawer and drawn in a shadow root so no page's own styles reach it; `rouh/comments.py` is what is kept and who may do what.

- **The floating control.** The comment button, its chevron and the Ask AI sparkle are one control at the page's top right, fixed while the page scrolls. The button counts the open threads.
- **Commenting.** The button, or C when nothing is being typed, is comment mode, as in Figma: the pointer is a comment pointer, the element under it is outlined and named, and a click pins a new thread there with a box for its first message. The page's own links and buttons do nothing while it is on. Escape, or Done on the hint at the bottom, leaves. Shift+C hides or shows every comment. C works wherever the keyboard is: on Rouh's canvas it is sent down into the page, and on a shared page's own bar too.
- **Pins and threads.** A pin is its author's initials in their colour. Hovering one opens it out, from its point, into the first message, who wrote it, when, and how many replies; clicking it opens the thread beside it with a box to reply at the bottom. A press on the page, or Escape, puts it away. Messages can be edited by who wrote them and deleted by who wrote them or the page's owner; deleting the first deletes the thread, and a deletion asks by being pressed twice, because a sandboxed page cannot open a window to ask.
- **Tagging.** @ in any box offers everybody who can open the page - its owner and everybody it is shared with, invited or joined - by name and address. Whoever is picked gets a letter from Rouh's own address with the comment and a link that opens the page with that thread open: Rouh's own address for the page, for its owner; their `/shared/<token>` link, for somebody it is shared with; and the invitation, carrying the thread through the sign-up, for somebody with no account yet. The page says who was emailed, and why a letter did not go when one did not. A tag is checked on the server against who can open the page and against the words of the message; a person may cause a hundred letters a day.
- **Resolving.** The tick at a thread's top resolves it, and its pin goes. The chevron's **Show resolved comments** draws resolved threads again where they were, at half strength and grey with a green tick, full strength while one is hovered or open, and the tick re-opens it. **All comments** lists every thread, open first, with its replies, whether it is resolved and whether its element is still there; a row opens its thread wherever it is on the page.
- **When the element goes.** Each comment keeps where its element was - its place among its kind from `<body>` down, its words, the point clicked as a share of it, and the point as a place on the page - and a snapshot of it: its markup, with the styles the browser worked out for it written onto each part, pictures inside it when they are small. When the page changes the element is found again: by its id, by its place holding the same words, by the same words anywhere, or by its place with words that are still mostly the same, which is an element edited where it stands. When none of those finds it, the pin stays roughly where it was, with a dashed amber edge and a "!", and its hover and its thread say the part of the page was removed and show the snapshot. Undo the change that removed it and the pin is on its element again.

Who may comment is everybody who can open the page as themselves: its owner, on Rouh's canvas, and every person it is shared with by email, including those who may only view it, as Figma lets a viewer comment.
A public link shows no comments and has no route for them: a visitor to it is nobody, with no name to put on a pin and no address to tag, and the names and addresses of the people commenting are not for everybody who has the link.
The threads belong to the page as its owner shared it - the owner's `user_id` and `org_id` and the page's path, the same three a share is kept under - and every query names all three (`page_comments`, `page_comment_messages`).
The page is only ever told names and addresses, never the token of anybody's link.
A snapshot is somebody else's markup, so the page never puts it in as markup: it reads it into a document that runs nothing, rebuilds it from a short list of elements and attributes, drops anything that would fetch, and draws it in a shadow root of its own, scaled to fit and clipped to its box.
The page cannot call out, so what it asks goes to `/api/comments` and is carried by the page around it: `askRelay` in app.js for the owner, to `/api/comments?doc=<page>`, and `reader.js` for a person it is shared with, to `/shared/<token>/comments` (`rouh/web/comments.py`).
Threads are fetched again every fifteen seconds while the page is on the screen, so two people on one page see each other's comments without reloading.

#### Ask AI answering the comments

> "I'd like it, in one pass, to answer and contribute to my comments. It needs to bring something useful and valuable ... It could also give us, or me, a task to do, something to think about, and a decision to make. In this case it should tag me. This option should be clickable from the chevron of the comments ... If it already wrote in that thread and nobody else said anything more, it should not add the second message. I also want a quick report on the whole run ... in the chat, the same chat that edits the page." - Petar, 24 September 2026 (fr_662a64715b9f).

**Answer comments with Ask AI** is the first line of the chevron's menu, for whoever may change the page: its owner, and a person it was shared with to change.
`rouh/commentpass.py` is all of it.

- **Which threads.** Every open thread whose last message is not Ask AI's own. A thread Ask AI already answered is left alone until somebody writes in it again, and a pass with nothing to answer says so and asks the model nothing.
- **What the model is given.** The page's working notes - for the owner the whole folder and project: the step's notes, the task's, the task's other steps' and the project's background from `_context/` (`askai.notes_beside`, wide) - the words on the page as the reader sees them, everybody who can open it, and for each thread the element it is pinned to: what kind of element it is, the heading it is under, how far down the page, and its markup. A thread on a part of the page with options is shown every version and the reason each exists.
- **What it does.** It replies where a reply adds something - a solution, better wording, a claim checked, good practice for that kind of element, with web search - and skips the rest, saying why. A reply that gives somebody a task, something to think about or a decision tags them. Where people are weighing an option's versions it may offer one more, with its reason, beside the others and nobody's default (`pagehistory.propose`); it is held to markup, with nothing that runs or loads.
- **Its messages** are drawn with the sparkle, under the name Ask AI, and never twice in a row in one thread.
- **Letters.** Everybody tagged gets one letter for the whole pass, with each reply and a link to it - apart from whoever started the pass, who is reading its report.
- **The report** is a topic in the page's own chat, the one that answers questions about the page and changes it: what was answered and how, what was skipped and why, who was tagged, and what versions were offered. It opens there by itself when the pass is done - Rouh's column on the canvas, the drawer on a shared page - and a line on the page says the same in a sentence.

The pass runs on the server rather than in the request that started it, one per page at a time, and the page asks after it every three seconds while it runs; pressing again joins it.
A guest's pass counts as one of their questions for the day and is never given the project's background, because a project's background is its money, clients and people.
The owner's own questions in the page's chat are given the whole folder and project the same way; the chat names the first few notes it read and folds the rest into "and N more".
The `talking` world's stand-in model answers a pass on its own (`fake_model.a_comment_pass`), so the whole of it can be driven without a key.

### Rouh's own mail

> "What we're missing here is an email service, and I think we're going to use Brevo... the sender is noreply@example.com." - Petar, 24 September 2026.

The invitations, the notes, a guest's password link and the letter to somebody tagged in a comment go through Brevo's API from the installation's own sender, `ROUH_MAIL_FROM` (`rouh/mailer.py`).
This is the install's own key, like its Anthropic key: it sends Rouh's few letters from Rouh's own address and never anybody's mail, so it is not the global credential the rules forbid.
The key is in one file on the server, outside the checkout, root's and mode 0600, like Telegram's: `/var/www/rouh/.secrets/brevo.json`, `{"api_key": "..."}` (`ROUH_BREVO_FILE`).
With no file there an invitation is still made and the panel says the letter did not go.
The `talking` world stands in for Brevo (`rouh/testing/fake_brevo.py`), with an inbox at the address `./e2e.sh serve talking` prints, whose letters' links can be pressed.

The first letters, on 24 September 2026, reached Rouh's own mailbox within seconds with DKIM, SPF and DMARC all passing for the sending domain, and Gmail still filed them as spam, which is what a sending address with no history gets; the panel says a letter may land in spam for that reason.

### Asking Rouh to do it

> "Do you have tools to make a task public?" - Petar, 23 September 2026. The answer was no, and now it is yes.

Two of Rouh's own tools reach the same rows, the same tokens and the same `/p/<token>` route as the Share button, so saying "make task 56 public" does exactly what pressing Share on each of its pages would.

- **`publish_task`** takes the task the way the person says it - "56", a step's "56-01", or its path - and `access` on or off.
  With nothing else it covers the whole task: every built page in the task itself and in each of its steps (`steps.pages_in`), each with a link of its own.
  Never what a step was made from (`source-code/`, `images/`), never a task inside it, and never its notes or its chat.
  `pages` narrows it to some of them.
  It puts the links on the screen itself, on a card, and hands them back so they can go into a message; it never reads one out.
- **`check_task_sharing`** says whether each of those pages is public and what its link is, and changes nothing.
  It also says what publishing the rest would put out, which is what Rouh reads before it asks, and who the task, a task above it, its subtasks and its pages are shared with by email, each with **can view** or **can edit**.
- **`share_with_person`** shares a task, or one page of it, with one email address, exactly as the panel's **Send** does, and always emails them the link, with a line of the person's own if they gave one (fr_55056f9ffcc2).
  Nobody else can open it, so it needs no yes beyond the person naming what and who; Rouh says in its reply that the email went, to whom, and what they can do.
  Its `role` is view or edit, for a whole task as for one page, and follows what the person asked: "editable", "so he can edit", "let her change it" is edit, anything else view.

> "Change your instruction that sharing can mean read or edit depending on my ask." - Petar, 13 October 2026, after asking for task 107 to be shared "editable" with a contact and getting a Google Doc copy instead.

So a task shared with a person can be **Can edit** as well as **Can view**, from the panel and from `share_with_person` alike; a task's public link is still only ever read (`sharing.role_for`).
With edit, every page of the task and of its subtasks opens, from the task's own view at `/shared/<token>`, in the reader's page with Ask AI that can change it, at `/shared/<token>?at=<where it is in the task>`, exactly as one page shared to change does: every route of it carries the same `at`, and `taskshare.page_at` is the one rule for which pages that reaches (`_for_guest` in `rouh/web/guests.py`).
Its notes are read and ground what Ask AI answers; nothing in Rouh changes a note with Ask AI, so neither can they.
With view, the task is read as before, with no Ask AI.
The letter says which it is, and the reader's list under `/shared` says **You can change it** or **You can read it**.

The rules are in the tool's own description and in the system prompt both (the rule "publishing" on the Rules page, one of the defaults): only on the person's own words, never because something looks shareable; say out loud what is about to be public and get a yes first; taking it down is always allowed without asking.

One of them is enforced rather than trusted.
A task whose notes or pages hold money, health detail or somebody's contact details is not published without its own yes, and Rouh has usually not read the task it is asked to publish.
So `sharing.sensitive` looks, over the pages about to go out and the task's own `AGENTS.md`, and `publish_task` publishes nothing at all until `agreed_to` names every kind it found.
It looks for words and shapes, not meaning: a ticket price is money, and it can miss what nobody wrote plainly.
What it hands back is the matched words themselves - "7,50 €", "salaries", an address - and never the sentence around them, because a sentence of a page is somebody's writing and could say anything to the model reading it.

The link is built from `ROUH_PUBLIC_URL`, the address Rouh is reached at from outside, because it is going into a message to somebody who is not looking at Rouh at all.
The `talking` world sets that to its own address, so a link made there opens there.

## Synapse's lab

Synapse is the memory Rouh is growing into (task 85, the design spec in step 85-01).
Its first version is a lab: the Synapse row in the sidebar opens `/synapse`, its datasets, and for each a debugger at `/synapse/<dataset>`, with the one Synapse chat beside them all: it acts on the dataset on the screen, and a fork of it stays on the dataset it was made over (`rouh/synapse/chat.py`).
Nothing else in Rouh reads from it yet, and it replaces nothing.
The code is `rouh/synapse/` (one module per part of the spec, each naming its decisions), the API `rouh/web/synapse.py`, the page `rouh/static/synapse.js`, and the tables a `synapse` schema (migration 0062), with pgvector and `pg_trgm` made by `manage.py predeploy` as PostgreSQL's own user.
Its models are OpenAI's, written down in `llm_requests` like every other (`llmlog` now records `/embeddings` and `/decisions` too); its tools (`synapse_*`) are offered only in the Synapse chat, its forks, and the chats datasets had of their own before 4 October 2026.
Step 85-02's notes say how each part is built and what it measured.

**At 10,000 items and 100,000** (migration 0071, 4 October 2026): every step costs what its answer costs, never what the dataset holds.
Search draws its word candidates from the question's rarest words in the GIN index (`synapse.term_df` counts how many passages hold each word) and ranks only those; readers are a stored column (`can_read`, kept by triggers) filtered inside the scan and checked once per result; a new item's link candidates are structure first, then one nearest-neighbour search on its vector, then its 5 to 10 rarest words; an import stores many items at once (`rouh/synapse/batch.py`) and its model parts run on the queue's backfill lane, which never takes a live slot.
**`python manage.py synapse_bench` is the test of all of it.** Run it before and after any change to Synapse's search, link candidates, storing, queue or schema.
It loads fictional items into a throwaway PostgreSQL of its own, with vectors made by code (nothing sent, nothing paid), times link candidates and search at 10,000 and 100,000 items, and exits 1 when, at 100,000, link candidates take over 50 ms or search over 300 ms at the 95th percentile.

**Automatic recall before each of the owner's messages** (`rouh/synapse/autorecall.py`, asked for by voice on 6 October 2026).
Before the model answers a message the person wrote or said themselves, two small models of two companies read what it is about at the same moment, with structured output, and the first answer is used (Petar, 10 October 2026: "let's always make both calls and take the first's results"): Synapse's decision model (`decision_model`, gpt-4.1-mini) and the second reader (`recall_second_model`, Haiku 4.5, never the same company), each given the message, the chat's title, task and last six turns, Master's 150 people who matter most with the person's own words for them on the Rules page (nicknames such as "Sam"), the projects, and the open and recently done tasks and steps by code.
It answers with people, tasks, projects (only one the message names), at most three topics as the phrases the person is talking about ("living software", "open source ideas"), and whether they bear on each other.
Until 10 October 2026 code picked them; Petar, that day, of a recall that picked "define" and "vitality" out of a message about living software for task 98-04: "It really has no concept what I am trying to do and what it relates to ... we should have an LLM call instead", and "I see no reason to leave code". So there is no code to fall back on: when neither reading is back in 2 s, nothing is looked up.
It runs one find per thing picked, each holding exactly what was picked, and, only when the model says they bear on each other, one background `synapse_query` asking how they connect, of which at most 3 items count, each scored highly and holding one of the things picked; all in parallel, as the owner.
Replayed over the 48 recall traces of 9 and 10 October on a copy of Master: 5.4 items a message against 8.5, the first answer of the two 1.3 s at the median and 1.7 s at the 95th (over 2 s once in 98, against 4 times for gpt-4.1-mini alone), both together $1.73 a thousand messages with each company's prompt cache, under a cent a message even with none (`autorecall.py` has the whole measurement).
Since 10 October 2026 ("I definitely don't want answers to be limited to 2.5 seconds") nothing is dropped at a deadline (`rouh/recalling.py`): the turn's first request waits for the look-ups at most `recall_wait_ms`, a number of Master's (10 s since 14 October 2026, 6 s before, on Synapse's numbers), from the moment the message came; they run on to 30 s; what comes back after the first request goes in after the tool results of the turn's next request, and what comes back after the turn has ended is given to the next message in the same chat. The seed look-up's late matches are treated the same way.
The best of it, at most about 1,500 tokens with near-duplicates and generated files left out, goes beside the clock as one block labelled "Background memory", in the untrusted box, and a standing paragraph in the cached prompt (`autorecall.PROMPT`) says how to use it: quietly, never recited, live sources first.
A message about nothing to look up (hello, a timer, the time, yes) looks nothing up, nor does a job's report or a beat of the heartbeat, nor anybody else's email, and nor do Synapse's own chats (whose conversations are still copied into Master like every other chat, `master.sync_chats`).
Two notes do, on the person's own words only (10 October 2026): a Clockwork reminder or scheduled work of theirs coming due, on its title and description (`autorecall.WORDS`, set by `timekeeper.deliver`), and an email from one of their own addresses that Gmail's own Authentication-Results passed (SPF, DKIM or DMARC; `mail_alerts.authenticated`), on its subject and body (`mail_turn.MailTurn.recall_words`); mail that only claims their address, or has no such header, gets none.
The model's reading and each look-up is a twig on the turn's line on the orb (`orb_only` on `tool_start` and `tool_end`), a bar on the message's timeline, the whole of it a `recall` trace in Master's Activity (each look-up's start, end, items and outcome), and a line in the log; its switch is `memory_recall`, under Other switches in Evolution, Mutations.
**In the line at the top of each reply** (`app/turnline.js`, since 24 October 2026; under the person's message before then) the memory says what the look-ups did ("Memory 5 look-ups, 4 in time, 1 late, 12 items") and opens into them: one bar per look-up, the seed look-up among them, on one time axis from the moment the message came, coloured by outcome (in time with results, in time with nothing, late, for the next message, failed), with markers at the old 2.5 s and at the wait, what was picked out of the message, which model answered first and how long each took, and which items went into the prompt and when (the `recall` message in PROTOCOL.md). It updates live while the look-ups run, and is kept with the message (`recall_timelines`).
`synapse_find` and `synapse_query` are loaded in every turn beside the search tool (`config.TOOLS_ALWAYS_LOADED`), and an item id from the block reads that item whole with `synapse_find`.

## The X-ray of a long report

A report page with `<page>.xray.json` beside it gets an **X-ray** button: the report's argument as a numbered outline of one-sentence claims (1, 1.2, 1.2.3), each opening to why, its evidence in the report's own words with the report's own sources, and a jump that opens the right part of the report and lights the passage.
A Doubts tab gathers every caveat, disagreement and unknown, and a picture shows how strongly each branch is backed.
It is put into the page as the page is sent, like the Ask AI drawer, so the report itself never changes, and every quote is found in the page before it is shown or it is left out.
`rouh/xray.py` has the format and `python -m rouh.xray check <page>`; the workspace's `bb-report-xray` skill is how a job writes one.

## Sources checked

> "can you please verify the sources. I want to make sure that sources don't turn out to be fake/hallucinated." - Petar, 7 October 2026, about the deck in task 96.

Any `index.html` in the workspace with at least three footnoted sources (`<li id="source-3">`, the workspace's rule for research) can have each source read against the sentence the page cites it for, when the owner presses **Check sources** beside it (`rouh/source_check.py`, the nightly feature run's night 10, behind the switch `source_check`).
Until 17 October 2026 every such page was checked by itself as soon as git said it changed; he asked then for it to be off by default and on demand (fr_563bcb1bdb26): "make the check sources off by default and on demand with click of a button. I will be using it only for specific cases that require it".
So nothing is fetched or read for a page until he presses the button for that page, and a page checked once is not checked again by itself: a page that changed since has **Check again**.
Code reads the page's footnotes and fetches each source from Rouh's own server, refusing private addresses as a picture fetch does; one call reads ten sources at a time (Models, "Checking a page's sources", starting on Sonnet 5) and says Holds, Says less, Not in the source or Says otherwise, with the source's own words, which code checks are really in what was fetched.
A source that cannot be read says why and costs no call.
**Sources** belongs to a task and is reached from it: a task's or a step's own page has a Sources section (`objectindex._sources_section`), one line for each page with footnotes inside it: a checked one with how many of its sources to look at, one never checked with its Check sources button, which starts the check and opens its Sources, where it is seen being read; a line opens Sources for that page's folder (`/sources/<folder>`, `rouh/static/sourcespage.js`), which lists only the pages inside that folder; a page opened there shows the sources to look at first, with Open the page here (the page on the canvas, at that source) and **It holds**, which keeps his word for that source and sentence for good.
It was in the navigation's Work group for its first day, and Petar took it out on 13 October 2026 (fr_fce8f51c00d6): "Sources should not be in the main navigation, only in the sources of each task".
So there is no list of every checked page, and `/sources` with no folder, from an old link or a bookmark, opens the task browser.
Nothing is drawn over the page itself, on Petar's word of 13 October 2026: "All this content should be in the sources page".
What was found is kept per page in `page_source_checks`, and a source is read again only when its address or its sentences change.
In a test world, `SOURCE_CHECK_ALLOW` lets it read a stand-in site on this machine.

## Night 11's genes: asked again, drafts that learn, a page as a PDF

Three genes the nightly feature run built on 14 October 2026 (task 94, step 94-10), each behind its own switch, off until the owner keeps it in Mutations (EVOLUTION.md).

- **Asked again** (`rouh/asked_again.py`, switch `asked_again`). When a message of his is the same request as messages he typed on two other days in the last four weeks (their meaningful words, found by code, no model call), the turn's prompt says when he asked and the rhythm and time those asks fall into, and Rouh offers in one sentence to do it as scheduled work on Clockwork; his yes makes it with `schedule`. Each request is offered once (`user_settings` `asked_again_offered`), never one already on Clockwork, and only in a turn he started (`brain._asked_again_block`). In a test world, typing a request, then moving its `messages.ts` back a day, twice, makes the third ask the one offered.
- **Drafts learn your edits** (`rouh/draft_edits.py`, switch `draft_edits`), recorded only since mutation request 2 (16 October 2026: "Don't modify responses. For now we will log changes"). A draft card keeps the draft as Rouh first wrote it (`first` on its compose block), because the card saves what he types as he goes; when he presses Send on one he changed, the draft as Rouh wrote it, the email as it went and each place they differ are a row of `draft_edits`, every one, for an analysis once there are hundreds. Nothing reads them back into a prompt. He reads them in Anatomy, Behaviour, Draft edits (`/anatomy/behaviour/draft-edits`, `draftedits.js`, `GET /api/settings/draft-edits`), newest first, a page at a time. A draft sent unchanged has nothing to record.
- **A page as a printable PDF** (`rouh/page_pdf.py`, switch `page_pdf`, the tool `print_page`). Asked to print a page, Rouh opens it in a headless Chromium on its own server, opens every slide, tab and fold, takes the content out of the screen's layout and lays it out again for Letter or A4 with page numbers, keeps the PDF in the task's folder beside the page, and draws a card whose link downloads it (a `/files/` link on a card is saved, never opened as a place in Rouh, `cards.js`). The page may load its own folder's files and public https, nothing else. Since night 12 (15 October 2026, Petar's mutation request) it has a **PDF** button beside Share wherever Share is (a task's or subtask's page with a page of its own, an HTML page of the workspace), asking Letter or A4; the PDF is made on the server while he does anything else (`POST /api/page-pdf`, `rouh/web/page_pdf.py`), and a notice says when it is ready with Download the PDF, Open the page and Open the task (a `/files/` link in a notice is saved, `notices.js`). A PDF already kept beside the page, newer than it, is offered in the same menu.

## A page's history, and its options

> "Whenever someone makes a change on the website, I want a history of every change, including who made it and when. I want to be able to click on each entry and see how the page looked at that moment... Additionally, for every change, I have to decide whether I want to keep it in the options." - Petar, 24 September 2026 (fr_b91369ea7ba2).

`rouh/pagehistory.py` is all of it, and the Ask AI layer in the page draws it (`rouh/static/askai/askai.js`, "history and options").

**The floating bar.**
Where the page has comments ("Comments on a shared page"), History and Options are in their floating control, in the order Petar gave: Comment, then History, then the Ask AI sparkle, with Options before History where the page has any.
They are askai.js's own buttons pressed through that control (`mirror` in `comments.js`), the way the sparkle is, so each shows what its own button shows.
Where there are no comments - a page read through a link, or an old version from the history - askai.js's own bar is there instead, running down the edge from the sparkle: History under it, Options under that.
It runs down rather than along because a page's own menu runs along the top: side by side, the three covered the last tab of task 61's site.

**History** lists every change to the page, newest first, each with who made it and when.
- **An Ask AI change** is one line: one `edit_page` call, the same unit that has one Undo. It names whoever asked - the owner, a person the page is shared with, or "Someone with the link" - because a guest's change is filed under the owner's page (`askai_edits.page_org_id`), not under the guest.
- **A change put back** is a line of its own, at the time it was put back.
- **A default picked** among a page's options is a line, under the name of whoever picked it.
- **A version saved in git** - a job that built or rebuilt the page - is a line with the commit's author and subject. Rouh's own commits are left out, because they are Rouh saving the Ask AI changes already listed.

Pressing a line loads the page as it was then into the same frame, read only, with a bar across the top saying which moment it is and **Back to the current page**.
Nothing else on the screen moves: the breadcrumb, the address and the conversation are still about the page as it is now, and the next change sends the frame back there.

History is the owner's, for now.
An old version can show what the owner took out of a page before sharing it, so a person it is shared with and a visitor to its link are not given it.

**Keeping a change as an option.**
Under every Ask AI change the owner makes, in the conversation, is **Keep both versions as options?** with **Keep both** and **No, final**, the same size, because the answer is usually no.
Pressing nothing is no: the change stands and nothing is offered, and History still asks, on that change's line, for changes made by anybody.
A change is kept as the elements it touched, whole, before and after (`pagehistory.parts_of`): a button made orange in the page's style sheet is that style sheet, a reworded line is that paragraph.
A change that reaches across the page's whole body cannot be one switch, and is not asked about.

**The options are a layer over the page, never in it.**
The page on disk holds the default and not one marker; the other versions are kept beside it (`page_options`).
Each part with versions gets a small tab in task 61-01's purple (`#b9a2ff`), on the element itself or, for a style, on the first thing the changed rule styles.
The tab opens a pop-up under the part, listing its versions:
- **Pressing a version** swaps it in on this reader's screen only. An element whose insides are the same in both versions keeps itself and has its attributes changed, so a script the page hung on a button still works.
- **Make default** makes it the version everybody sees when the page opens. Anybody who can read the page may press it, a person it is shared with to view included, and the last press stands. It writes the page, so it is saved to main like any change and is a line in the history.
- **Stop offering these options**, for whoever may change the page, keeps the default and lets the rest go.

Every version says why it exists, under its name.
> "Each option for how something should look or what we should choose needs to have reasoning somewhere around it so that we know why somebody picked that specific option to exist." - Petar, 24 September 2026 (fr_662a64715b9f).

A change Ask AI made carries the reason the model gave with it (`edit_page`'s `reason`, kept on `askai_edits.reason`); the version before it says what it was before; a version Ask AI offered while answering the comments carries its own.
Whoever may change the page can write or rewrite any version's reason in place (**Add a reason**, **Change the reason**).
When the pop-up fits neither under the part nor over it, it opens beside it, so the part it switches stays in view.

The sliders in the floating bar list every option on the page, which is the way to the ones with nothing on the screen to hang a tab on.
A later change to an element that already has versions carries them with it, and kept as an option itself it becomes another version of the same switch rather than a second one on top: red, then orange, then green is one switch of three.
Undo takes back the version it added.

**Not decided yet, and so built the simple way:** whether one Ask AI request that made several changes should be one line of history or several (several, one per `edit_page` call); whether guests should see the history (no); and whether the purple switcher built into task 61-01's own page should move onto this layer (it is left as it is).

Pages of any size can be changed by Ask AI since 24 September 2026, so task 61's two sites, 403 KB and 429 KB, have Ask AI changes to keep as options like any other page; until then they were just over a 400 KB limit that has gone.

## Attached files, and the one server setting they need

Files the person attaches in the chat are stored under `ROUH_DATA_DIR`, in
`attachments/<conversation>/<id>/<name>`, and nothing is ever written at a path
built from the name the browser sent.
The cap is sixty-four megabytes per file.

Almost anything may be attached.
The rule is not a list of allowed formats but a short list of refused ones: the formats an operating system runs when you open them, `BLOCKED` in `rouh/attachments.py`, plus anything whose first bytes are a program whatever it is called.
A shell script is not on that list, because it is source, and nothing written here has an execute bit.

An uploaded `.html` or `.svg` is stored whole and read to the model as text, and it is never served back as a page on Rouh's own address.
It comes back as `application/octet-stream` with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and a `Content-Security-Policy` that sandboxes it.
A script served from this address would be inside the signed-in session: it could read the conversation and act as the person.
Only png, jpeg, gif, webp, pdf and plain text are ever rendered in place (`INLINE_SAFE`).

They are written so that nobody else on the machine can read them: the files
0640 and the folders 2750, set outright rather than left to the umask, which on
this server is 002 and would otherwise make every screenshot readable by every
Linux user on the box.
The group is `rouh-attachments` (`ROUH_ATTACHMENTS_GROUP`), which opens nothing but this tree, and its members are the two users that are handed these files by their path: `rouh`, which runs the crew's workers, and `assistant`, which runs the one program's runs.
The folders are set-group-id, so a file that gets there some other way keeps the group too.
Until 1 October 2026 the group was `rouh`, so a run told to look at the owner's screenshot got "Permission denied"; putting `assistant` in `rouh` would have opened the crew's worktrees and Rouh's home to it as well.
`sudo python manage.py attachments_access --apply --member assistant` makes the group, adds its members and gives the tree to it, and changes nothing when run again; with no options it says how things are.
A machine without the group falls back to the crew user's own group.
Every run and worker is also told, in its brief, to stop and ask when a file it was given will not open, rather than guess what it shows (`attachments.WORKER_RULE`).

nginx has its own limit on how large a request body may be, and the default is
one megabyte.
Until the site's server block says otherwise, every attachment over a
megabyte fails with an nginx error page that does not mention Rouh at all.
Inside that server block:

```nginx
    client_max_body_size 520M;   # attachments are capped at 512 MB in the app
```

Until 23 October 2026 the server block said `25M` while the app took 64 MB, so a
screen recording of a call, "call details.mov", came back "That upload came back
413." (fr_b9d6a78fa5d3).
Both Rouh sites on the server, `rouh` and `rouh-is`, now say `520M`, and the app
takes 512 MB a file (`attachments.MAX_BYTES`).
The page is handed that number on the file picker (`data-max`), so a bigger file
is refused on the screen, naming the limit, before any of it goes up.
A file over 64 MB is copied to disk as it is rather than read into memory, in the
browser and on the server (`Attachments.save_upload`).

`verify.py` checks it against the live site: "and 511 MB gets through the
proxy".

## Pictures, drawn and changed

Petar asked for pictures on 26 September 2026 (fr_77013fa4c9bc): OpenAI now, perhaps Google's Gemini later, a way to change only one area of a picture, and whatever else the provider offers.

The chat side knows nothing about who draws.
`rouh/imaging.py` speaks in an `Ask` and gets back `Made` pictures, and a provider is a class with three methods - whether it is set up here, what its models can do, and draw - registered in `PROVIDERS`.
`rouh/imaging_openai.py` is the one there is: OpenAI's Images API with its own key, `OPENAI_API_KEY`, the same one Luna uses.
Gemini would be one more file and one more line in `PROVIDERS`, and the page builds every choice it offers from what each provider says of its models (`imaging.options`, on `ready`).

Three ways to ask, all ending the same way:

- **The picture button** beside the paperclip switches the box to a picture: the settings go on a line above the text (model, shape, quality, how many, background), Send draws, and nothing waits on a model.
  Pictures attached to the ask are handed to the provider to draw from.
- **In words**, typed or said: the model has `make_picture` and `change_picture`, in the Pictures area of the catalogue, and a short paragraph in its prompt, both only when a provider is set up.
  It is told to use them only when a picture is asked for.
- **Under a picture** opened full size: **Change an area** opens the editor, where a brush, a box and an eraser paint the area and the words say what goes there instead; **More like this** draws two variations; **Download** saves the file.
  Uploaded pictures can be changed too, not only drawn ones.

While a set is drawn the page shows one frame per picture with a spinner, then each rough preview as the provider streams it, then the pictures, with a line under them naming the model, the shape, the quality and what it cost.
A failure is a readable sentence in the chat.
Each picture is kept in the chat's own files, with `made` in its record, and written into the conversation as a message of Rouh's carrying its marker, so it is there after a reload; a change is a new picture beside the original, which is kept.
The model reads each picture it drew as a line of words - which picture, drawn from what - never as the picture, so a chat full of pictures costs no more to answer in (`attachments._made_block`).
Every request is a row of `llm_requests` with its cost, without the picture bytes, and priced from `costs.IMAGE_PRICES`.

What OpenAI offered on 26 September 2026, and what became of it:

- **Models.** `gpt-image-2.5-flare`, fast, draws and changes by default; `gpt-image-2.5-sunburst`, slower and finer, can be picked for new pictures, whole-picture changes and variations. `ROUH_IMAGE_MODEL` and `ROUH_IMAGE_EDIT_MODEL` move the defaults.
- **Changing only an area** is an edit with a mask, transparent where the picture may change. OpenAI calls the mask guidance rather than a stencil, and the editor says so. Flare does it well. Sunburst, asked on the real API with the guide's own mask and three other shapes of one, gave the painted area back black every time, so it is never sent a mask: with an area painted the editor greys it out, and the server refuses it in words.
- **Several at once**, up to four, as a row of thumbnails to pick from; each is its own request, so each fills in on its own.
- **Rough previews** (`partial_images`). At draft quality OpenAI often sends the finished picture before any preview, which its documentation says it may.
- **Shapes** square, landscape, portrait, 16:9 and 9:16; **quality** draft to best; **background** solid, transparent or the model's choice. Every picture is a PNG.
- **Variations**: OpenAI's variations endpoint takes only DALL-E 2, so More like this is an edit with no mask and words asking for another take.

At draft quality a Flare picture cost about half a cent and an area change about two cents on the real API.

## Rouh offline

Petar, 12 October 2026, on card 1457 ("Rouh offline, on laptop and phone"): "Do it".
He is sometimes on his laptop and sometimes on his phone, and Rouh keeps working with him when there is no internet.
This is phase one of that plan: the copy on each device, and one outbox for what he does with none.
Rouh is a web page on both, so it is a progressive web app: a service worker, IndexedDB and WebCrypto, and nothing native.

**The page with no connection.**
`/sw.js` (`rouh/static/sw.js`, served by `rouh/web/offline.py` with the build and the page's files written into it) keeps the page's own files at their hashed addresses, and the person's own page and what the canvas reads (a task's page, the task browser, the cards, the decisions) as they were last fetched.
`app/offline.js` keeps what the socket's handshake and the lists after it said, and with no connection hands them to the same code again (`offlineReplay`), so the chats, the transcript with its cards, the task list and the canvas come up as they last were.
Only on a page opened with no connection: a page the live server has drawn since it opened keeps its own screen when the socket goes, because the copy is older than it (since 23 October 2026, when Rouh restarting after a deploy put back, over the chat Petar was in, whichever chat was open when the copy was kept).
A pill just under the top bar, on every screen, says Offline, Evolving or Reconnecting while there is no connection, turns green and says Alive, after a cloud, for a few seconds when it is back and then fades, says how many actions wait to be sent, and opens the Offline page.
Evolving is only said when Rouh closed the socket on purpose to start again, which uvicorn does with WebSocket's close code 1012 (Service Restart) on every deploy; any other drop is Reconnecting.
Its words are `CONN_WORDS` in `rouh/static/app/socket.js`, together, so they can be tried and changed (Petar, 12 October 2026).

**The copy, `/offline`.**
Petar, 12 October 2026: "Calendar - 30 days back and forward. Emails - 30 days. Chats - Rouh - 2 weeks back and all its forks. Tasks - all tasks in control room that have been selected above status 'quiet'. Full content of - clockwork, quests, and goals, task browser mechanics with the airplane. Feedback - available to submit, synced on connect."
So the copy is the same on the laptop and the phone, and holds nine kinds, in his order (`KINDS` in `app/offline.js`):
the calendar, every event from 30 days before today to 30 days after on every calendar Rouh shows, whole (`pack_calendar`, read five days at a time so Google's page of 250 is never the edge);
the decisions;
Clockwork, the goals and the quests, kept as their own pages read them (`/api/reminders`, `/api/goals` with every goal's page and its steps' pages, `/api/quests` and `/api/quests/<n>`), by the device itself through the service worker, so they open with no connection exactly as they do with one;
the tasks, every task listed with its name, status and project, and whole (notes, steps, and the pages the canvas opens for the task, its steps and what they built, whose pictures and styles come inside each page) for every task of a Control Room cluster above its quiet edge, read from `controlroom.room` afresh each time, and every pinned task;
the chats, every chat with something said in it in the last two weeks, whole with its cards, each with all its forks whatever their age (`pack_chats`);
the email, both inboxes, thirty days of headers and bodies, five days to a request (`pack_mail`);
and the contacts.
`GET /api/offline/pack/<part>` makes the server's parts, `?page=` for mail and chats.
A device short of room shares the room out from the top: once a kind does not fit, it and every kind after it are left out and what they held goes, and the Offline page says which, beside every kind's count, the days it covers, when it was made and its size.
A goal or a task whose pages have not changed since they were kept is not read again.
It is made while the page is open: when it opens, when it comes back into view, and every 15 minutes; never by itself on a connection the browser says is mobile or saving data.
Never in the background: an iPhone gives a web app no time there, and the page says so.
The Offline page shows what is held, one search over all of it, and everything in it in tabs: the calendar a week at a time with every event whole, the mail by day, the chats with their forks under them and what each fork carried.
With no connection the task browser lists every task and marks the ones whose pages are not on the device "Not available offline", and opening one says so on the canvas instead of failing; a task's address, or anything inside it, is opened from the copy the way the server would answer it (`addrOffline`).

**Act now, carried out later.**
Answering a decision (the Decisions page, a task's page or the Offline page: `decision.js` sends it to the outbox when there is no connection), a reply or a new email, an edit to a task's own notes (`AGENTS.md`, `step.md`, and the files `saving._kept_in_place` keeps), a reminder, a new task, a note or a voice note for Rouh, a change on Clockwork, a goal's step or a quest made on its own page (pausing, changing or deleting a reminder, ticking one of his steps, marking a step complete, pausing a quest, its ledger), and feedback from the Gene therapy drawer each go into the device's outbox with an id of its own, the device, the time and the version of what it acted on.
What starts work now (Try it now, Do it now, Check now) waits for a connection rather than being kept for later.
With a connection they go at once, the same way.

**The one outbox.**
`POST /api/offline/outbox` carries out each action once (`offline.take`): a row of `OfflineAction` (`offline_actions`, migration 0127) under the device's id for it, so a retry or the other device sending the same one gets the first answer back and nothing is done twice.
Each kind goes through the path that does it online: a decision through `Desk.act` with his exact words and the channel `offline`, a reminder through Clockwork, a task through `owning.new_task`, a note as his own message in General (a voice note written out by `runtime.ears` first, the recording attached), a change on Clockwork, a goal or a quest through the very view the page posts it to, as him (`offline.CLOCK_ROUTES`), and feedback through the board's own store, dated when it was written and taken up by itself as the drawer's Send is.
A reply is a draft in Rouh's own mailbox (his mailboxes are read only, so a reply to one of them is a new email from Rouh's); it is sent only when Send was ticked and confirmed on the device and the send rules allow it (`mail_cases.holds_reply`, nothing newer in the thread), and otherwise it waits as a gated decision to send.
What moved meanwhile is not carried out over the newer version: a decision answered or asked differently, a newer email in the thread, a note changed in the same lines, or a reminder or a goal's step changed elsewhere become a decision of the source `offline` (`decision_sources.OfflineSource`, `offline.question_of`) showing both versions.
A note changed on both sides in different places is merged line by line (`rouh/offline_merge.py`) and written.
Every result goes to every open tab of the person (`offline_results`, PROTOCOL.md), and each device reads both devices' results when it reconnects (`GET /api/offline/outbox?since=`).

**Private.**
Everything kept is sealed with AES-GCM under a key the page makes with WebCrypto as not extractable, kept in the browser's own store; the service worker seals what it keeps with the same key.
It is kept only under the person the page names (`<meta name="rouh-owner">`, `X-Rouh-Owner`, a hash and never the id itself): a page for anybody else clears it before anything is kept, nothing of `/p/`, `/shared/` or `/join/` is ever kept, and signing out deletes it and the key (the sign-in page clears it too, so a session that ran out takes it with it).
The device's own encryption (FileVault, the iPhone's passcode) is what protects it when the device is lost: a key the browser can open without asking is a key the device's owner can open.

Later phases plug into the same two halves: models on the device answer from the copy, a handoff between devices passes outbox entries that are carried out once by their ids, and the Gmail-to-Synapse mirror becomes another part of the pack.

## Gene therapy: feedback, and what is done about it

Gene therapy is what this was called Feedback until 12 October 2026, when Petar renamed it, gene emoji and all: "Can we also change the name of the feedback function to be called gene therapy with a gene emoji and rename all the code files, not just the link in navigation. Also make it playful, how would you like to mutate me?"
So the row under the menu button says 🧬 Gene therapy, the drawer asks "How would you like to mutate me?", Send is **Mutate**, and the files are `rouh/gene_therapy.py`, `rouh/web/gene_therapy.py`, `rouh/static/app/gene_therapy.js` and the gene `gene-therapy`, whose words include feedback, mutate and gene therapy so Search and Rouh still find it by any of them.
What it keeps did not change name: a feedback and a feature request, in the tables `feedback`, `feature_request`, `feedback_board` and `feedback_file`, untouched by any migration.
The views answer at `/api/gene-therapy/...` and still at `/api/feedback/...`, `/gene-therapy` opens the page with the drawer open, and `/feedback` is sent on to it.
The environment's `ROUH_FEEDBACK_AUTO` and `ROUH_FEEDBACK_SWEEP_MINUTES`, the offline outbox's `feedback` kind and a workspace page's `rouh-page-feedback` message keep their names too, because they are written down outside this code.

Two things, and the whole design is in that sentence.

**A feedback is what somebody said.**
A sentence, a screenshot, a file, and the screen they were on when they said it.
It is never edited into something else: what a person wrote stays what they wrote.

**A feature request is what is going to be done about it.**
It has a type - feature, bug, improvement, question - a title, a description of how the solution should work, and its own files as extra guidance.
One is made *from* a feedback and remembers which one; one can also be made on its own, because not everything worth building came out of somebody complaining.

They are two tables (`rouh/gene_therapy.py`) because they have two lifetimes and two status sets, and folding them into one row with a flag on it is what makes "which of these did the person actually say" unanswerable six months later.

```
feedback         new -> triaged -> planned -> done, or declined
feature_request  proposed -> building -> shipped, or declined
```

Both are the organisation's: every row carries `org_id` and `user_id`, and there is no query in that file that does not name an organisation.
Nothing in the views (`rouh/web/gene_therapy.py`) reads either out of the request body; both come from `Tenancy.current`, like everything else that belongs to somebody.

### The drawer, and the board

The row is under the menu button, beside Rouh: 🧬 Gene therapy.
It opens a drawer down the right, and the drawer **pushes the page in rather than lying over it**: it is the fourth track of the app's grid (`--gt-track` in `app.css`), nothing wide until it is opened and `--gt-w` once it is, so whatever the person is writing about is still on the screen beside what they are writing.
On a phone there are no columns to push, so it is a full-height sheet instead.

Files are uploaded the moment they are attached, into a folder of their own, through the same `POST /attachments/{session}` route the composer uses - so the wait for a twenty megabyte recording happens while the person is still typing, and pressing Send while one is still going up sends it by itself the moment the last one lands.
Sending is what binds those ids to the row.
Screenshots can be pasted into the box and files dropped anywhere on the drawer.

On **Mutate** the form goes, **Noted. The mutation is queued.** takes its place, and under it, when the machine really is taking it up by itself, one line saying what is happening to it: it is being read, written up as a feature request and given a run to splice it in.
Then the drawer slides back off to the right by itself.

**All mutations** replaces the conversation and the canvas with the board: what people said on the left, what is going to be done about it on the right, each with its own status filter and counts, and one search box over both.
The sidebar is untouched, because it is how you leave.
On a phone the two columns stack.

Pressing either kind opens it in full - who, when, the screen they were on, every word, every file - and Back returns to the two columns.
From a feedback there is one form that turns it into a feature request, with the type, the title, how the solution should work, and files as extra guidance; the feedback itself is not touched beyond its status, which becomes `planned`.

### Starting a run for one

A feature request has a Start box: a workspace and a policy, the same two lists the sidebar's own Start box offers, and it goes through `starting.start` like every other way of starting work on this machine.
A run started from a card is therefore a run of exactly the same kind, told apart by its workspace and its policy and by nothing else.
The policy it offers first comes from the server saying whether this machine has a one program at all, not from whether the browser has paired with one: those are two different questions.

What the run is briefed with is `gene_therapy.compose_brief`: the title, how the solution should work, the feedback it came out of in the person's own words, and every attached file **by its path on disk**, which is how `attachments.py` already hands a file to something that can open it.
Nothing is invented and nothing is summarised.

Starting one writes the run's id onto the request and moves it to `building` in the same statement, so a card can never say "proposed" while a run started from it is going.
After that the card reads the run's state straight off the ordinary run feed - the same `task` message every other run sends - so "run running" and then "run idle" appear on it with nothing polling.
A run of the one program can be opened from the card.

### Nobody presses either of those buttons any more

Both presses above - turn this into a feature request, start a run for it - are done by the machine the moment a feedback lands (`rouh/triage.py`).
Petar, 22 September 2026: "the feedbacks should be automatically converted to feature requests and should automatically be put in RUNS to be completed."

```
a feedback arrives  ->  read it  ->  a feature request  ->  a run
```

**Reading it is a model call and nothing else is.**
The model is given what the person wrote, the screen they were on and what they attached, and answers with three fields: the kind, a title, and how the solution should work, which is the field the run is briefed from.
Everything else there is plain code.

**A reading is never the person's words.**
The feedback row is untouched, the request says on its face that a machine wrote it (`automatic`, "written by Rouh" on the card), and the brief says which half is which: "the section on how the solution should work is a reading of what the person wrote; the feedback itself is their own words. Where the two disagree, their words are the ones to build to."

**Nothing may fail to convert.**
A model that is not configured, is overloaded, is slow, or answers something that is not JSON all end in `triage.guess`: the title is the person's own first line, the kind is read off their words, and the body says plainly that nobody has read it yet.
A feedback that was never converted because the clever path broke is exactly the feedback nobody ever sees again.

**Starting the run may fail, and then it is tried again.**
A machine with no worker and no one program cannot start anything: the reason is written on the row (`run_note`), the card says it - "no run yet: There is nothing on this machine to run it" - and the sweep tries again, five times before it leaves it alone.

**The sweep is the second half of the promise.**
Immediately is what a submission gets; every `ROUH_FEEDBACK_SWEEP_MINUTES` (five) a sweep walks every organisation's board and picks up what was left behind - a feedback written while this process was restarting, a conversion cut off half way, a run nothing would take the first time.
A feature request somebody typed themselves is never started by it: the Start box is right there under it, and starting a run under somebody who is still writing is interference rather than automation.

The run is started under the `improve_myself` preset - Rouh's own code, the one program first and a worker here if there is no program - because feedback on this board is feedback about Rouh.
`ROUH_FEEDBACK_AUTO=0` turns the whole of it off, and then the board is what it was: two buttons somebody presses.

## Tests

**Every feature proves itself, and nothing else is run.** There are no committed
tests here at all: not a browser test, not a unit test, not an end-to-end test.
Nothing is committed, and nothing is reported as done, until whoever built it has
opened the running app in a real browser over Playwright MCP, done what the
person would do, and seen it work. A Python test is still the right tool for
logic with no face, and it is written, run and left out of the commit. No suite
is run before a commit or a deploy, and nothing that was not changed is
re-checked. The rule, the worlds the harness can build and a worked example are
in [AGENTS.md](AGENTS.md), which is the standing instruction for anyone working
in this repository.

```bash
./e2e.sh                                    # build .venv-e2e and the browser
./e2e.sh serve                              # Rouh, up and held, for a browser to drive
./e2e.sh path/to/your_check.py              # a check of your own, run and then thrown away
./.venv/bin/python verify.py                # against the live site
```

`./e2e.sh` builds `.venv-e2e` the first time and installs the browser it needs;
after that it is one command that takes half a minute. That venv holds both
apps' pinned requirements and Playwright, so a check of your own runs in it
whatever it imports. `./e2e.sh serve` stands one of the harness's worlds up on a
free port and prints the address, the sign-in and the process id to stop it
with; `tests/e2e/conftest.py` is what builds them and is not to be trimmed.
Every world has a PostgreSQL of its own - a whole cluster in its folder, on a
socket nothing else can reach, with the schema migrated in - made by
`rouh/testing/postgres.py` and stopped with the world, so no world ever shares
a database with another or with the server's.

Playwright MCP is configured in `.mcp.json` and allowed in
`.claude/settings.json`, headless and with a profile that is never written to
disk, because there is no display on the server and several jobs share the
machine. It brings its own browser build: `npx @playwright/mcp@latest
install-browser chrome-for-testing` puts it in `~/.cache/ms-playwright` on a
machine that has never had it.

The stand-ins the deleted tests were built on are still here, in
`rouh/testing/`, because a live drive wants them even more than a test did.
`rouh/testing/fake_model.py` is a real HTTP server that speaks enough of the
Messages API to be the far end of Anthropic's own SDK and writes every request
body down, so what actually went out can be read back.
`rouh/testing/fake_voice.py` is the same idea one service along, for the far
end of `rouh/speech.py`: point `ELEVENLABS_BASE_URL` at it and a reply really
is synthesised into PCM and really arrives at the browser as the frames it
plays, with no key and no network. There are stand-ins for Google, MCP and
Telegram beside them.
`rouh/testing/browser.py` puts a Rouh in front of the first two, and
`./e2e.sh serve talking` is how you get one: a Rouh that really answers and
really speaks, for a browser to be driven at.

The tests themselves went on 20 September 2026, on Petar's instruction: 2,029
under `rouh/` and 334 under `one/tests`. They are in git history and nothing
about them is lost. `git log --diff-filter=D --oneline -- rouh/test_brain.py`
names the commit that removed one, `git show <sha>^:rouh/test_brain.py` reads
it back, and `git checkout <sha>^ -- <file>` puts it in a checkout if a piece of
work genuinely wants it back for an afternoon.

### Every worker gets a tmux server of its own

Several workers and Rouh itself run on this one machine, under the same users,
out of copies of this one repository.
A tmux client that names no socket does not reach a server of its own: it
reaches the one server every job on this machine lives in.

On 17 September 2026 that is what happened.
A teardown in one of the old browser tests stopped a whole tmux server without
naming which one, and it was the server every job lives in: three jobs died in
the same second with nothing committed, and the assistant anyone would have
asked about it was down.

Two things stand in the way of that now, and neither of them is a rule about
what a job may do.

* **Every tmux command in this repository's own code names its socket.**
  `tmux -L <label>` or `tmux -S <path>`, always.
  `TMUX_TMPDIR` on its own is not isolation: a tmux client reads `TMUX` first,
  and tmux sets `TMUX` in every pane it opens, so a command run from inside a
  pane - which is where a worker runs - ignores `TMUX_TMPDIR` and talks to the
  pane's own server.
  `rouh/testing/tmux_sandbox.py` is a throwaway server done properly, and
  `ROUH_CREW_TMUX_SOCKET` is how a check of your own points a whole Rouh at
  one.
* **Every worker gets a tmux world of its own.**
  The crew starts each one through `env -u TMUX TMUX_TMPDIR=<its own directory>`
  (`CrewManager._own_tmux_env`), so a tmux command inside a worker reaches only
  a server that worker started itself, and the job's private server is stopped
  by socket path and removed when the job is (`close_tmux_dir`).
  The directory is made before the window opens, because tmux quietly falls
  back to a shared socket in `/tmp` when it is missing.

That is the whole of it, and it is a boundary rather than a restriction: a job
can stop anything it means to stop, and cannot take Rouh or a sibling with it
by accident.

What is deliberately **not** done is a cgroup or a process group per worker.
Each tmux pane is already its own process session, because tmux starts it
through `forkpty`, which calls `setsid`: a signal sent to a process group or a
session cannot cross from one worker to another, and killing a process tree is
therefore already contained.
What a cgroup would not contain is the thing that actually went wrong, which is
naming rather than scope - a process picked out by pattern is found in any
cgroup, and a tmux client with no socket named finds the shared server from
inside any of them.
A `systemd-run --scope` per worker would add a boundary that stops neither,
while changing how a pane is started, how its exit status is read and what has
to be cleaned up when a run is lost, all of which the crew's reconciliation
depends on.
The day there is a reason for one - a memory limit per worker, say - it belongs
in `WorkerProfile`, beside `run_as`.

### A worker that dies says why, and can be started again

A job whose worker ends without ever saying how it went has died, and until
24 September 2026 nothing said why.
b0e4656f, "Kept notes missing from a project", was started and found
dead in the same second, with no `session.log` and nothing in the journal.
It had been started with `runuser -u jarvis`, and the machine's `jarvis` user
had been renamed `rouh` two days before; so had d05698d4 ten minutes earlier.
`runuser` said so on a terminal that was gone before anybody could read it,
because tmux was only told to keep the window and log it a moment after the
program had started.

Four things stand in the way of that now.

* **The workers' user is the machine's.**
  `ROUH_CREW_USER` is `rouh` by default, and a setting that still names a
  renamed user is read as the new name (`config.RENAMED_USERS`).
  A user that does not exist, or one Rouh cannot switch to because it is not
  running as root, is refused before anything is made, in a sentence the
  person is told (`crew._cannot_run_as`).
* **Every worker starts behind `rouh/crew_launch.py`.**
  It waits until the crew has set `remain-on-exit` and started `pipe-pane`, so
  the log has the worker's first byte and the window survives it, then runs
  the worker on the same terminal and writes `.rouh/exit.json` when it ends:
  its exit code, and when it started and stopped.
* **A death is written down when it is found.**
  Every path that marks a job `lost` goes through `_set_status`, which reads
  the log, the dead window's last screen and the launcher's record, and keeps
  what it finds on the row as `death` (`crew.death_of`): whether it died at
  launch, its exit code, and the last thing it printed that reads as a reason.
  That line is the card's `detail`, and what Rouh says out loud about it.
* **A died job has a page and a Restart button.**
  Its card says DIED in red where the dot would be, with the cause under the
  brief; it opens on the canvas like any other job (`GET /api/job/<id>`), with
  what it was asked and what it printed; and Restart starts the same worker
  again - same brief, same kind, same checkout, same files hint - as a new job
  (`starting.restart`, `POST /api/job/<id>/restart`).
  The dead job is archived and points at the new one, the conversation and
  task it belonged to follow, and a feature request its death had marked
  failed is building again.
  Pressing twice starts one job.
