/* The one program's page: every run, its terminal, what it did, and the questions.
 *
 * It talks to the program over one websocket with the same messages the
 * terminal uses (one/protocol.py). It can look at everything, start and stop
 * runs, send a run a message, answer questions, and type into a run's
 * terminal, taking its keyboard on the first key (D46).
 *
 * Every piece of text from the program goes in with textContent, never as HTML.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const STATE_WORDS = {
    queued: "Queued", starting: "Starting", working: "Working",
    asking: "Needs you", saving: "Saving its work", idle: "Finished its turn",
    done: "Done", unfinished: "Unfinished", failed: "Failed", lost: "Lost",
    refused: "Refused", reaped: "Cleaned up",
  };
  const ENDED = new Set(["done", "unfinished", "failed", "lost", "refused", "reaped"]);

  // What this browser remembers for itself between reloads. Anything about a
  // run itself is kept by the program, never here.
  function load(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function store(key, value) {
    try { localStorage.setItem(key, String(value)); } catch (e) { /* a private window */ }
  }

  const state = {
    ws: null, connected: false, next: 0, waiting: new Map(),
    device: null, runs: new Map(), devices: new Map(), questions: [],
    selected: null, showEnded: true, view: "runs", tree: null,
    // Runs the person put out of the way are off the list until they ask.
    showArchived: load("one.showArchived") === "yes",
  };

  // --- talking to the program --------------------------------------------------

  function send(t, fields = {}) {
    return new Promise((resolve, reject) => {
      if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        reject(new Error("not connected"));
        return;
      }
      const id = ++state.next;
      state.waiting.set(id, { resolve, reject });
      state.ws.send(JSON.stringify({ t, id, ...fields }));
    });
  }

  let retry = 500;
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const base = location.pathname.replace(/\/[^/]*$/, "");
    const ws = new WebSocket(`${proto}//${location.host}${base}/ws`);
    state.ws = ws;
    ws.addEventListener("open", async () => {
      retry = 500;
      try {
        const hello = await send("hello");
        state.device = hello;
        setConnected(true);
        $("device").textContent = hello.name || "";
        const [runs, questions, devices] = await Promise.all([
          send("runs", { watch: true, limit: 200 }),
          send("questions", { watch: true }),
          send("devices"),
        ]);
        state.runs = new Map(runs.runs.map((r) => [r.id, r]));
        state.devices = new Map(devices.devices.map((d) => [d.id, d]));
        state.questions = questions.questions;
        if (state.view === "tree") watchTree();
        renderAll();
        const wanted = new URLSearchParams(location.hash.slice(1)).get("run");
        if (state.selected) select(state.selected, { force: true });
        else if (wanted) select(wanted);
      } catch (err) {
        console.warn("one: could not start", err);
      }
    });
    ws.addEventListener("message", (event) => handle(JSON.parse(event.data)));
    ws.addEventListener("close", (event) => {
      setConnected(false);
      for (const { reject } of state.waiting.values()) reject(new Error("closed"));
      state.waiting.clear();
      if (event.code === 4401) {
        location.href = "pair";
        return;
      }
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 10000);
    });
  }

  function setConnected(on) {
    state.connected = on;
    $("conn").classList.toggle("on", on);
    $("conn").setAttribute("aria-label", on ? "Connected" : "Not connected, trying again");
  }

  function handle(m) {
    if (m.re !== undefined && state.waiting.has(m.re)) {
      const { resolve, reject } = state.waiting.get(m.re);
      state.waiting.delete(m.re);
      if (m.t === "err") reject(new Error(m.why)); else resolve(m);
      return;
    }
    switch (m.t) {
      case "driving":
        if (m.run === state.selected) driving = m.run;
        break;
      case "watching":
        if (driving === m.run) driving = null;
        break;
      case "run":
        state.runs.set(m.run.id, m.run);
        scheduleRender();
        // Given back meanwhile, by leaving it quiet: the next key takes it again.
        if (driving === m.run.id && m.run.driver !== (state.device && state.device.device)) driving = null;
        if (m.run.id === state.selected) {
          renderRunHead();
          if (ENDED.has(m.run.state)) termWanted = m.run.id;
          else wantTerm(m.run.id);
        }
        break;
      case "questions":
        state.questions = m.questions;
        renderQuestions();
        if (state.selected) renderRunAsk();
        break;
      case "tree":
        state.tree = m.tree;
        if (state.view === "tree") renderTree();
        break;
      case "screen":
        if (m.run === state.selected) showScreen(m);
        break;
      case "tty":
        if (m.run === state.selected && term) term.write(bytes(m.b64));
        break;
      case "size":
        // Somebody sized the run's terminal (D51): drawn at its new size.
        if (m.run === state.selected && term) {
          term.options.fontSize = fontSizeFor(m.cols);
          term.resize(m.cols, m.rows);
        }
        break;
      case "entry":
        if (m.entry.run === state.selected) {
          addTimeline(m.entry, true);
          // Started again - after a crash, or moved onto the API key - it is
          // a new process on a new terminal, and the one on the screen is the
          // old one's last picture. Ask for the new one.
          if (m.entry.kind === "run.restarted") termWanted = m.entry.run;
          wantTerm(m.entry.run);
        }
        break;
      case "err":
        if (m.why) console.warn("one:", m.why);
        break;
    }
  }

  const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

  // --- the list of runs ------------------------------------------------------------

  let renderQueued = false;
  function scheduleRender() {
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => { renderQueued = false; renderList(); renderSummary(); });
  }

  function renderAll() {
    renderList();
    renderSummary();
    renderQuestions();
  }

  // The run asked for most recently at the top, the oldest at the bottom, and
  // nothing a run does afterwards moves it. This list used to put the run
  // asking a question first and the ended ones last, so a row jumped the
  // moment a run changed state - under the hand of whoever was reaching for
  // it. What state a run is in is on the row itself. `requested_at` is always
  // the same shape of text, so it is compared as text; the id separates two
  // runs asked for in the same millisecond.
  function sortedRuns() {
    const runs = [...state.runs.values()]
      .filter((r) => state.showEnded || !ENDED.has(r.state))
      .filter((r) => state.showArchived || !r.archived);
    const key = (r) => `${r.requested_at}\u0000${r.id}`;
    return runs.sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : 0));
  }

  function renderList() {
    const list = $("run-list");
    const runs = sortedRuns();
    list.replaceChildren(...runs.map(runRow));
    const hiding = state.runs.size > 0 && runs.length === 0;
    $("no-runs").textContent = hiding
      ? 'Nothing to show. Tick "Ended too" or "Archived too" to see what is hidden.'
      : "No runs yet. Start one with the button at the top.";
    $("no-runs").hidden = runs.length > 0;
  }

  function runRow(run) {
    const li = el("li", "run-row" + (ENDED.has(run.state) ? " ended" : "")
      + (run.archived ? " archived" : ""));
    li.tabIndex = 0;
    li.dataset.id = run.id;
    if (run.id === state.selected) li.setAttribute("aria-current", "true");
    const dot = el("span", `dot ${run.state}`);
    dot.title = stateWords(run);
    // The age is the run's own age, because that is what the list is ordered
    // by: a row saying "just now" sitting under one saying "5 min ago" would
    // make the order look broken. What the run last did is the line below it.
    li.append(dot, el("span", "title", run.title),
              el("span", "age", ago(run.requested_at)), archiveButton(run));
    const sub = el("span", "sub");
    if (run.archived) {
      const pill = el("span", "pill-archived", "Archived");
      pill.title = "Put out of the way, and stopped if it was still going. Its checkout is kept.";
      sub.append(pill);
    }
    const engine = enginePill(run);
    if (engine) sub.append(engine);
    sub.append(el("span", null, subline(run)));
    li.append(sub);
    li.addEventListener("click", () => select(run.id));
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") select(run.id); });
    return li;
  }

  const SVG = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const node = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  }

  // The box a run goes into, or comes back out of.
  function archiveIcon(archived) {
    const svg = svgEl("svg", { viewBox: "0 0 24 24", width: "13", height: "13", fill: "none",
      stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round",
      "stroke-linejoin": "round", "aria-hidden": "true" });
    svg.append(svgEl("rect", { x: "3", y: "4", width: "18", height: "4", rx: "1" }));
    svg.append(svgEl("path", { d: "M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" }));
    // A line on the box to put it away; an arrow out of it to bring it back.
    svg.append(svgEl("path", { d: archived ? "M12 17.5V12" : "M10 13h4" }));
    if (archived) svg.append(svgEl("path", { d: "M9.5 14.5 12 12l2.5 2.5" }));
    return svg;
  }

  // Whether the program will take this message: it says at hello which ones it
  // takes. A program that did not say is taken at its word and asked.
  function allows(t) {
    const allowed = state.device && state.device.allowed;
    return !allowed || allowed.includes(t);
  }

  // Something the program would not do, said where the person is looking. The
  // start box's error line is no good here: it is inside a dialog that is shut.
  function runsNote(text) {
    const note = $("runs-note");
    note.textContent = text || "";
    note.hidden = !text;
  }

  // Archiving a run that is still going stops it: the person is done with it,
  // so the terminal behind it is closed too. Its checkout is left where it is.
  // Every row has the button, whatever state the run is in; on a run already
  // archived it is the way back, and bringing one back starts nothing.
  function archiveButton(run) {
    const want = !run.archived;
    const b = el("button", "row-act");
    b.type = "button";
    b.title = want ? "Archive this run" : "Unarchive";
    b.setAttribute("aria-label",
      (want ? "Archive the run: " : "Unarchive the run: ") + (run.title || run.id));
    b.append(archiveIcon(!!run.archived));
    b.addEventListener("click", async (ev) => {
      ev.stopPropagation();          // the row itself opens the run
      // A program older than this page does not know the message at all, and
      // refuses it in words about rules rather than about versions.
      if (!allows("archive")) {
        runsNote("The program running here is older than this page: "
          + "putting a run out of the way needs it updated.");
        return;
      }
      b.disabled = true;
      runsNote("");
      try {
        const got = await send("archive", { run: run.id, on: want });
        // The program tells every page anyway; this only answers the click now.
        if (got.run) state.runs.set(got.run.id, got.run);
        renderList();
      } catch (err) {
        b.disabled = false;
        runsNote(err.message);
      }
    });
    b.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") ev.stopPropagation();
    });
    return b;
  }

  // A run's state in one phrase. A queued run says what it is waiting for and
  // what ends the wait, because "waiting to start" on its own reads as stuck.
  // The scheduler works the reason out (one/scheduler.py why_wait) and puts it
  // on the run; a run queued for the instant before the scheduler has looked
  // at it has none yet, and "Queued" alone is the truth about it.
  function stateWords(run) {
    const word = STATE_WORDS[run.state] || run.state;
    // An unfinished run always says what is unfinished about it. "Unfinished"
    // on its own would only move the question along.
    if (run.state === "unfinished" && run.left) return `${word} - ${run.left}`;
    // A lost run says what took it (one/runs.py adopt_all), never only "Lost".
    if (run.state === "lost" && run.ended_why) return `${word} - ${run.ended_why}`;
    // Stopped by the program's own clock (one/scheduler.py close_overdue),
    // which is neither a finish nor a crash, and says so.
    if (run.state === "reaped") {
      return `${word} - stopped at the time limit` + (run.left ? `, and ${run.left}` : "");
    }
    if (run.state !== "queued" || !run.queued_because) return word;
    return `${word} - ${run.queued_because}`;
  }

  // Which agent a run is, in the words a person would use. Claude Code is
  // what a run is unless Codex was asked for, so it is not said on every row:
  // saying it everywhere would make the one row that matters harder to see.
  const ENGINE_WORDS = { claude: "Claude Code", codex: "Codex" };

  function engineWords(run) {
    return ENGINE_WORDS[run.engine] || ENGINE_WORDS.claude;
  }

  function enginePill(run) {
    if (!run.engine || run.engine === "claude") return null;
    const api = billedToKey(run);
    const pill = el("span", "pill-engine" + (api ? " api" : ""),
      `${engineWords(run)} · ${api ? "API key" : "subscription"}`);
    pill.title = `This run is ${engineWords(run)}, not Claude Code. ${billingWords(run)}.`;
    return pill;
  }

  // Who pays for a run of Codex (one/billing.py): the ChatGPT subscription
  // Codex is logged in with, unless the OpenAI API key was chosen for it. A run
  // on the key says so wherever the run is shown, so it is never billed quietly.
  function billedToKey(run) { return run.engine === "codex" && run.billing === "api"; }

  function billingWords(run) {
    if (run.engine !== "codex") return "";
    if (!billedToKey(run)) return "Billed to the ChatGPT subscription";
    return run.billing_was === "subscription"
      ? "Billed per token to the OpenAI API key, since the person moved it off the subscription"
      : "Billed per token to the OpenAI API key";
  }

  function subline(run) {
    if (run.state === "asking") return run.waiting_on_terminal ? `Needs you in its terminal: ${run.waiting_on_terminal}` : "Needs you: it is asking a question";
    // Queued says what it waits for; cleaned up says why it ended, which its
    // last message, written before the program stopped it, never says.
    if (run.state === "queued" || run.state === "reaped") return stateWords(run);
    if (run.state === "working" && run.doing) return run.doing;
    if (run.driver) return driverNote(run.driver);
    if (run.last_message) return run.last_message;
    return stateWords(run);
  }

  // "you is driving it" was on the run list whenever the person's own page had
  // a run's keyboard (16 September).
  function driverNote(driver) {
    const who = deviceName(driver);
    return who === "you" ? "You are driving it" : `${who} is driving it`;
  }

  // Open is two things (D49): a run that is working, and a run that has
  // finished its turn and waits at its prompt to be carried on or closed.
  // "32 open" over a list that said "Finished its turn" twenty times read as
  // thirty-two things going on (29 September 2026), so the two are counted
  // apart, and an archived run, which the person put away, is neither.
  function renderSummary() {
    const open = [...state.runs.values()].filter((r) => !ENDED.has(r.state) && !r.archived);
    const asking = open.filter((r) => r.state === "asking").length;
    const resting = open.filter((r) => r.state === "idle").length;
    const busy = open.length - resting - asking;
    const parts = [];
    if (busy) parts.push(`${busy} working`);
    if (resting) parts.push(`${resting} finished ${resting === 1 ? "its" : "their"} turn`);
    if (asking) parts.push(`${asking} waiting for you`);
    const text = open.length === 0 ? "Nothing running" : `${open.length} open: ${parts.join(", ")}`;
    $("summary").textContent = text;
    document.title = asking ? `(${asking}) one` : "one";
  }

  // --- questions ---------------------------------------------------------------------

  function renderQuestions() {
    const box = $("questions");
    box.replaceChildren(...state.questions.map((q) => questionCard(q, true)));
    box.hidden = state.questions.length === 0;
    document.body.classList.toggle("has-questions", state.questions.length > 0);
  }

  function questionCard(q, withRun) {
    const card = el("div", "question");
    const text = el("div");
    text.append(el("span", "needs-you", "NEEDS YOU "));
    text.append(el("span", "q-text", q.text));
    if (withRun) {
      const run = state.runs.get(q.run);
      text.append(el("span", "q-run", run ? `Run ${run.id}: ${run.title}` : `Run ${q.run}`));
    }
    if (q.detail) text.append(el("span", "q-detail mono", q.detail));
    const buttons = el("div", "q-buttons");
    // A posed choice says what each button does; a tool call is allowed or denied.
    const choices = q.choices || {};
    const yes = el("button", "yes", choices.yes || "Allow");
    const no = el("button", "no", choices.no || "Deny");
    for (const [btn, answer] of [[yes, "yes"], [no, "no"]]) {
      btn.type = "button";
      btn.addEventListener("click", async () => {
        yes.disabled = no.disabled = true;
        try { await send("answer", { question: q.id, answer }); }
        catch (err) { yes.disabled = no.disabled = false; alertText(err.message); }
      });
    }
    buttons.append(yes, no);
    card.append(text, buttons);
    return card;
  }

  function alertText(text) {
    const box = $("start-error");
    box.textContent = text;
    console.warn("one:", text);
  }

  // --- one run -------------------------------------------------------------------------

  let term = null;
  // The run whose terminal this page still has to ask for. A run started from
  // the Start box is shown before it has a terminal, and a run carried on gets
  // a new one. On 15 September the page asked once, was told there was none,
  // and never asked again.
  let termWanted = null;
  // Typing into the run (D46): the run whose keyboard this page holds, keys
  // waiting to go, and whether a take is on its way.
  let driving = null;
  let typed = [];
  let taking = false;

  function makeTerm(cols, rows) {
    if (term) term.dispose();
    term = new window.Terminal({
      cols, rows, disableStdin: false, cursorBlink: false, convertEol: false,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: fontSizeFor(cols), scrollback: 5000, allowProposedApi: false,
      // Option and drag selects in this page's own terminal while the run has the mouse.
      macOptionClickForcesSelection: true,
      theme: { background: "#0f1116", foreground: "#e6e8ee", cursor: "#e6e8ee" },
    });
    term.open($("term"));
    term.onData(keys);
    term.attachCustomWheelEventHandler(wheel);
    term.parser.registerOscHandler(52, clipboard);
  }

  // The wheel (D51): to the run's program when it asks for the mouse, as
  // Claude Code does on its full screen, where it scrolls back through the
  // whole run; otherwise the terminal's own history. Never arrow keys (D50).
  function wheel(ev) {
    if (!term) return false;
    const mouse = term.modes ? term.modes.mouseTrackingMode : "none";
    if (mouse === "none" && term.buffer.active.type === "normal") return true;
    ev.preventDefault();
    if (mouse !== "none") scrollRun(ev.deltaY, ev.deltaMode, ev.clientX, ev.clientY);
    return false;
  }

  // Turns of the wheel or of a finger, in lines of the terminal, sent
  // together every 40 ms. `mode` is a wheel's deltaMode: pixels, lines or pages.
  const turned = { px: 0, lines: 0, col: 1, row: 1, timer: 0 };

  function scrollRun(delta, mode, x, y) {
    const screen = $("term").querySelector(".xterm-screen");
    if (!term || !screen) return;
    const box = screen.getBoundingClientRect();
    const cellW = box.width / term.cols, cellH = box.height / term.rows;
    if (!(cellH > 0)) return;
    turned.px += mode === 1 ? delta * cellH : mode === 2 ? delta * box.height : delta;
    const lines = turned.px < 0 ? Math.ceil(turned.px / cellH) : Math.floor(turned.px / cellH);
    if (!lines) return;
    turned.px -= lines * cellH;
    turned.lines += lines;
    turned.col = Math.max(1, Math.min(term.cols, Math.floor((x - box.left) / cellW) + 1));
    turned.row = Math.max(1, Math.min(term.rows, Math.floor((y - box.top) / cellH) + 1));
    if (!turned.timer) turned.timer = setTimeout(sendScroll, 40);
  }

  // A finger over the terminal (fr_66d95f663c91). Once the run asks for the
  // mouse, as Claude Code does on its full screen, xterm.js leaves a touch
  // alone and that screen keeps no history of its own, so no swipe on a phone
  // moved it. A finger drawn up or down now turns the run's history the way
  // the wheel does, a line for every row it travels, and a flick carries on
  // and slows to a stop. A tap is left alone, so it still brings up the
  // keyboard; where xterm.js has a history of its own, the finger is its.
  const finger = { id: null, y: 0, at: 0, speed: 0, glide: 0 };

  function fingerTurns() {
    return !!term && (term.modes ? term.modes.mouseTrackingMode : "none") !== "none";
  }

  function fingerDown(ev) {
    glideStop();
    finger.id = ev.touches.length === 1 && fingerTurns() ? ev.touches[0].identifier : null;
    if (finger.id === null) return;
    finger.y = ev.touches[0].clientY;
    finger.at = ev.timeStamp;
    finger.speed = 0;
  }

  function fingerMove(ev) {
    if (finger.id === null) return;
    const p = ev.touches.length === 1 ? ev.touches[0] : null;
    if (!p || p.identifier !== finger.id) { finger.id = null; return; }
    // Nothing else under a finger on the terminal scrolls, and a touch whose
    // first move the page lets through becomes the browser's to pan.
    if (ev.cancelable) ev.preventDefault();
    const dy = finger.y - p.clientY, dt = ev.timeStamp - finger.at;
    if (!dy) return;
    // Pixels a millisecond, the latest move counting most, for the flick.
    if (dt > 0) finger.speed = 0.8 * (dy / dt) + 0.2 * finger.speed;
    finger.y = p.clientY;
    finger.at = ev.timeStamp;
    scrollRun(dy, 0, p.clientX, p.clientY);
  }

  function fingerUp(ev) {
    if (finger.id === null) return;
    const p = [...ev.changedTouches].find((t) => t.identifier === finger.id);
    finger.id = null;
    // A finger that stopped before it lifted was not flicking.
    if (ev.type === "touchend" && p && ev.timeStamp - finger.at < 80 && Math.abs(finger.speed) > 0.3) {
      glide(finger.speed, p.clientX, p.clientY);
    }
  }

  // The flick: it carries on at the finger's speed and slows to a stop in
  // about a second, or at once when the finger comes down again.
  function glide(speed, x, y) {
    const id = state.selected;
    let last = 0;
    const step = (now) => {
      finger.glide = 0;
      const dt = last ? Math.min(now - last, 50) : 16;
      last = now;
      speed *= Math.pow(0.997, dt);
      if (Math.abs(speed) < 0.05 || state.selected !== id || !fingerTurns()) return;
      scrollRun(speed * dt, 0, x, y);
      finger.glide = requestAnimationFrame(step);
    };
    finger.glide = requestAnimationFrame(step);
  }

  function glideStop() {
    if (finger.glide) cancelAnimationFrame(finger.glide);
    finger.glide = 0;
  }

  $("term").addEventListener("touchstart", fingerDown, { passive: true });
  $("term").addEventListener("touchmove", fingerMove, { passive: false });
  $("term").addEventListener("touchend", fingerUp, { passive: true });
  $("term").addEventListener("touchcancel", fingerUp, { passive: true });

  function sendScroll() {
    const id = state.selected, lines = turned.lines;
    turned.timer = 0;
    turned.lines = 0;
    if (!lines || !id) return;
    send("scroll", { run: id, lines, col: turned.col, row: turned.row })
      .catch((err) => { $("typing").textContent = err.message; });
  }

  // What the mouse did over the terminal once the run asks for the mouse
  // (D51): presses, releases and drags go to the run, together every 40 ms;
  // the wheel goes as scroll, and a move with no button held goes nowhere.
  const MOUSE = /\x1b\[<(\d+);\d+;\d+[Mm]/g;
  const clicks = { data: "", timer: 0 };
  let mouseAt = 0;

  function mouseReports(data) {
    for (const m of data.matchAll(MOUSE)) {
      const b = +m[1];
      if ((b & 64) || ((b & 32) && (b & 3) === 3)) continue;
      clicks.data += m[0];
      mouseAt = Date.now();
    }
    if (clicks.data && !clicks.timer) clicks.timer = setTimeout(sendMouse, 40);
  }

  function sendMouse() {
    const id = state.selected, data = clicks.data;
    clicks.data = "";
    clicks.timer = 0;
    if (!data || !id) return;
    send("mouse", { run: id, b64: btoa(data) })
      .catch((err) => { $("typing").textContent = err.message; });
  }

  // Claude Code copies a selection with OSC 52; only the page whose person
  // used the mouse in the last five seconds puts it on its clipboard (D51).
  function clipboard(data) {
    const b64 = String(data).split(";").pop();
    if (!b64 || b64 === "?" || Date.now() - mouseAt > 5000 || !navigator.clipboard) return true;
    try {
      const text = new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
      navigator.clipboard.writeText(text).catch((err) => console.warn("one: the clipboard said no:", err.message));
    } catch (err) {
      console.warn("one: the clipboard said no:", err.message);
    }
    return true;
  }

  // A key in the terminal takes the run's keyboard if this page does not hold
  // it yet, then goes to the run. Keys typed while the take is on its way wait
  // for it; if somebody else holds it, they are not sent.
  // What xterm.js sends back by itself, typed by nobody: its answers to the
  // run's questions about the terminal, focus in and out, and the mouse. They
  // neither take the keyboard nor go to the run (15 September).
  const REPORTS = /\x1b\[[?>=]?[\d;]*[cnRt]|\x1b\[\?[\d;]*\$?[uy]|\x1b\[[IO]|\x1b\[<[\d;]*[Mm]|\x1b\[M[\s\S]{3}|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1bP[\s\S]*?\x1b\\/g;

  function keys(data) {
    const id = state.selected, run = state.runs.get(id);
    if (!id || !run || ENDED.has(run.state)) return;
    data = String(data || "");
    mouseReports(data);  // what the mouse did goes on its own, not as typing (D51)
    data = data.replace(REPORTS, "");
    if (data) typed.push(data);
    else if (!typed.length) return;
    if (driving === id) { sendKeys(); return; }
    if (taking) return;
    taking = true;
    send("take", { run: id })
      .then(() => { if (state.selected === id) { driving = id; sendKeys(); } })
      .catch((err) => { typed = []; $("typing").textContent = err.message; })
      .finally(() => { taking = false; });
  }

  function sendKeys() {
    if (!typed.length) return;
    const id = driving, text = typed.join("");
    typed = [];
    let s = "";
    for (const byte of new TextEncoder().encode(text)) s += String.fromCharCode(byte);
    send("input", { run: id, b64: btoa(s) }).catch(() => {
      // Given back meanwhile: take it again, and send these keys after all.
      if (driving === id) driving = null;
      typed.unshift(text);
      if (state.selected === id) keys("");
    });
  }

  /* --- dropping a file on it (D52) ---
   *
   * Claude Code turns a path pasted at its prompt into an attachment and shows
   * it as [Image #1]; a path typed key by key stays a path. So a screenshot dropped here never travels down the
   * run's terminal as bytes: the program writes it into a folder the run can
   * read (one/drops.py) and says what to type, and the page types that the
   * way it types a key (D46). No Enter is sent: the person adds their words
   * and presses it themselves.
   */

  // Whether a drag is over the terminal is "did a dragover arrive just now",
  // not dragenter counted against dragleave. Counting flickers as the pointer
  // crosses something inside the box, and leaves the box on screen for ever
  // when a drag ends outside the window and the last dragleave never comes.
  const dropping = { at: 0, timer: null, dragging: false, busy: false, clear: 0 };

  function dropSay(text, how) {
    const box = $("drop");
    $("drop-say").textContent = text || "";
    box.className = "drop" + (how ? " " + how : "");
    box.hidden = !text;
    clearTimeout(dropping.clear);
    if (how === "done" || how === "bad") {
      dropping.clear = setTimeout(() => {
        if (!dropping.busy && !dropping.dragging) dropSay("");
      }, how === "bad" ? 9000 : 4000);
    }
  }

  // Forgets a drag and anything the box was saying: a different run is open now.
  function dropClear() {
    dragDone();
    dropping.busy = false;
    dropSay("");
  }

  function dragAlive() {
    dropping.at = Date.now();
    if (!dropping.busy) {
      dropping.dragging = true;
      dropSay("Drop to attach to this terminal");
    }
    if (dropping.timer) return;
    dropping.timer = setInterval(() => {
      if (Date.now() - dropping.at < 350) return;
      dragDone();
    }, 150);
  }

  function dragDone() {
    dropping.at = 0;
    if (dropping.timer) { clearInterval(dropping.timer); dropping.timer = null; }
    if (!dropping.dragging) return;
    dropping.dragging = false;
    if (!dropping.busy) dropSay("");
  }

  // Whether a run that can still take a file is open here.
  function dropOpen() {
    const run = state.runs.get(state.selected);
    return !!(state.selected && run && !ENDED.has(run.state));
  }

  // A drag carrying files, rather than text dragged out of the page itself.
  function dragged(ev) {
    return !!(ev.dataTransfer && Array.prototype.includes.call(ev.dataTransfer.types, "Files"));
  }

  for (const kind of ["dragenter", "dragover"]) {
    $("term-wrap").addEventListener(kind, (ev) => {
      if (!dragged(ev) || !dropOpen()) return;
      // Without this the browser takes the drop itself and leaves the run to
      // show the file.
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
      dragAlive();
    });
  }
  $("term-wrap").addEventListener("drop", (ev) => {
    if (!dragged(ev)) return;
    ev.preventDefault();
    ev.stopPropagation();
    dragDone();
    dropFiles(ev.dataTransfer.files);
  });

  // A file dropped anywhere else on the page must not take the browser to it:
  // missing the terminal by a few pixels would otherwise leave the run for a
  // picture of the file.
  window.addEventListener("dragover", (ev) => { if (dragged(ev)) ev.preventDefault(); });
  window.addEventListener("drop", (ev) => { if (dragged(ev)) ev.preventDefault(); });
  window.addEventListener("dragend", dragDone);

  // Ctrl or Cmd and V of a picture while the terminal has the keyboard: the
  // same as dropping it. Caught before xterm.js sees it; pasted text is still
  // xterm's to send to the run as keys.
  $("term-wrap").addEventListener("paste", (ev) => {
    const files = ev.clipboardData && ev.clipboardData.files;
    if (!files || !files.length || !dropOpen()) return;
    ev.preventDefault();
    ev.stopPropagation();
    dropFiles(files);
  }, true);

  // The path goes in as a paste, not as keystrokes. Claude Code only turns a
  // path into an attachment when it arrives as one paste: sent key by key it
  // stays a path on the screen and the picture never reaches the model (D52).
  // It still takes the run's keyboard first, the way any key does (D46), and
  // sends no Enter.
  async function pastePath(text) {
    const id = state.selected;
    let s = "";
    for (const byte of new TextEncoder().encode(text)) s += String.fromCharCode(byte);
    if (driving !== id) {
      await send("take", { run: id });
      driving = id;
    }
    await send("input", { run: id, b64: btoa(s), paste: true });
  }

  async function dropFiles(files) {
    const id = state.selected, list = Array.from(files || []);
    if (!list.length) return;
    if (!dropOpen()) { dropSay("This run has ended: there is nothing to attach a file to.", "bad"); return; }
    if (dropping.busy) { dropSay("One at a time: the last file is still going up.", "bad"); return; }
    dropping.busy = true;
    dropSay("Uploading " + list.map((f) => f.name || "the file").join(", ") + "…", "busy");
    const body = new FormData();
    body.append("run", id);
    for (const file of list) body.append("file", file, file.name || "drop");
    try {
      const res = await fetch(dropUrl(), { method: "POST", body, credentials: "same-origin" });
      const got = await res.json().catch(() => ({}));
      if (!res.ok || !got.ok) throw new Error(got.why || (res.status === 413
        ? "that file is too big: the most one may be is 20 MB"
        : "the program could not take that file"));
      if (state.selected !== id) { dropping.busy = false; return; }
      const kept = (got.files || []).map((f) => f.name);
      const run = state.runs.get(id), me = state.device && state.device.device;
      // Somebody else holding the keyboard cannot be typed over: the file is
      // saved all the same, and its folder is where they find it.
      if (run && run.driver && run.driver !== me) {
        dropping.busy = false;
        dropSay(`${kept.join(", ")} is saved in the run's folder, but ${deviceName(run.driver)}`
                + " has its keyboard, so nothing was typed in.", "bad");
        return;
      }
      await pastePath(got.typed);
      dropping.busy = false;
      if (state.selected !== id) return;
      if (term) term.focus();
      dropSay(kept.join(", ") + (kept.length > 1 ? " are" : " is")
              + " at its prompt. Add words, then press Enter.", "done");
    } catch (err) {
      dropping.busy = false;
      dropSay(err.message, "bad");
    }
  }

  // The program's own address, beside its socket.
  function dropUrl() {
    return location.pathname.replace(/\/[^/]*$/, "") + "/drop";
  }

  function typingNote(run) {
    const me = state.device && state.device.device;
    $("typing").textContent = ENDED.has(run.state) ? "It has ended. Send it a message below to carry it on."
      : run.driver && run.driver === me ? "You have its keyboard. It goes back when you leave the run or stop typing for two minutes."
      : run.driver ? `${deviceName(run.driver)} is typing in it.`
      : "Click in the terminal and type: your keys go straight to it.";
  }

  function fontSizeFor(cols) {
    const width = $("term-wrap").clientWidth - 20;
    const size = Math.floor(width / (cols * 0.602));
    return Math.max(9, Math.min(14, size || 13));
  }

  function showScreen(m) {
    if (!term || term.cols !== m.cols || term.rows !== m.rows) makeTerm(m.cols, m.rows);
    else term.reset();
    $("term-none").hidden = true;
    $("term").hidden = false;
    term.write(bytes(m.b64));
  }

  async function select(id, { force = false } = {}) {
    const run = state.runs.get(id);
    if (!run) return;
    if (state.selected === id && !force && state.view === "runs") return;
    const previous = state.selected;
    if (previous && previous !== id) send("detach", { run: previous }).catch(() => {});
    state.selected = id;
    showView("runs");
    history.replaceState(null, "", `#run=${id}`);
    document.body.classList.add("viewing");
    $("placeholder").hidden = true;
    $("run").hidden = false;
    driving = null;
    typed = [];
    dropClear();
    $("timeline").replaceChildren();
    renderRunHead();
    renderRunAsk();
    renderList();
    try {
      const detail = await send("run", { run: id, entries: 200 });
      if (state.selected !== id) return;
      state.runs.set(id, detail.run);
      renderRunHead();
      for (const entry of detail.entries) addTimeline(entry, false);
      const last = detail.entries.length ? detail.entries[detail.entries.length - 1].n : undefined;
      await send("tail", { run: id, since: last === undefined ? 0 : last });
    } catch (err) { console.warn("one:", err.message); }
    await attach(id);
  }

  async function attach(id) {
    termWanted = null;
    try {
      await send("attach", { run: id, history: true });
    } catch {
      if (state.selected !== id) return;
      termWanted = id;
      if (term) { term.dispose(); term = null; }
      const run = state.runs.get(id);
      $("term").hidden = true;
      $("term-none").textContent = run && !ENDED.has(run.state)
        ? "Its terminal appears here as soon as it starts." : "This run has no terminal now.";
      $("term-none").hidden = false;
    }
  }

  // Ask for the selected run's terminal again, when the page still needs it
  // and the run is going.
  function wantTerm(id) {
    const run = state.runs.get(id);
    if (termWanted === id && run && !ENDED.has(run.state)) attach(id);
  }

  function renderRunHead() {
    const run = state.runs.get(state.selected);
    if (!run) return;
    $("run-title").textContent = run.title;
    const meta = $("run-meta");
    const st = el("span", `state ${run.state}`);
    st.append(el("span", `dot ${run.state}`), document.createTextNode(stateWords(run)));
    const bits = [st, el("span", "", `Run ${run.id}`), el("span", "", engineWords(run))];
    if (run.engine === "codex") {
      bits.push(el("span", billedToKey(run) ? "billing-api" : "", billingWords(run)));
    }
    if (run.space) bits.push(el("span", "", spaceName(run.space)));
    if (run.step) bits.push(el("span", "", `Step ${run.step}`));
    if (run.landed && run.compare) {
      const pr = el("a", "", `Pushed on ${run.pushed}: open its pull request`);
      pr.href = run.compare; pr.target = "_blank"; pr.rel = "noopener";
      bits.push(pr);
    } else if (run.landed && run.pushed) {
      bits.push(el("span", "", `Pushed on ${run.pushed}`));
    } else if (run.landed) {
      bits.push(el("span", "", `Saved to ${run.target || "main"} at ${run.landed.slice(0, 7)}`));
    }
    if (run.by) bits.push(el("span", "", `Asked for by ${deviceName(run.by)}`));
    bits.push(el("span", "", ENDED.has(run.state) ? `Ended ${ago(run.ended_at)}` : `Started ${ago(run.started_at || run.requested_at)}`));
    meta.replaceChildren(...bits);
    const said = $("run-said");
    const words = run.land_reason && !run.landed ? `Could not save to main: ${run.land_reason}` : run.last_message;
    said.hidden = !words;
    if (words) {
      said.replaceChildren(el("strong", "", run.land_reason && !run.landed ? "Needs you" : "It said"), document.createTextNode(words));
    }
    $("stop-btn").hidden = ENDED.has(run.state);
    // A run at its prompt stays open until you close it (D49).
    $("stop-btn").textContent = run.state === "idle" ? "Close" : "Stop";
    $("say-form").hidden = run.kind !== "agent";
    $("say-text").placeholder = ENDED.has(run.state) ? "Carry it on with a message" : "Send it a message";
    typingNote(run);
  }

  function renderRunAsk() {
    const box = $("run-ask");
    const qs = state.questions.filter((q) => q.run === state.selected);
    box.replaceChildren(...qs.map((q) => questionCard(q, false)));
    box.hidden = qs.length === 0;
  }

  // --- what happened ------------------------------------------------------------------

  // Characters of one event shown before "Show all".
  const LONG = 320;

  const SKIP = new Set(["tool.closed", "run.attached", "run.detached", "work.nothing-new",
                        "subagent.closed", "agent.session", "phone.sent", "run.adopted",
                        "run.stop-requested", "agent.ended"]);

  function describe(e) {
    const b = e.body || {};
    switch (e.kind) {
      case "run.requested": return ["Asked for", `by ${deviceName(e.by)}${b.surface === "voice" ? ", out loud" : ""}`, "person"];
      case "run.queued": return ["Waiting", b.why];
      case "run.started": return ["Started", b.branch ? `on its own branch, ${b.branch}` : (b.cwd || "")];
      case "run.restarted": return ["Started again", b.why];
      case "run.instructions": return ["Instructions", b.what || ""];
      // A box the person named for this run, put in its folder; never what is in it.
      case "run.boxes": return ["Handed boxes", `${(b.numbers || []).map((n) => `box ${n}`).join(", ")}, as files in .secrets`, "person"];
      case "run.boxes-shredded": return ["Boxes shredded", b.shredded ? `${b.shredded} file${b.shredded === 1 ? "" : "s"} overwritten and deleted` : "nothing was left to shred", "good"];
      // A run's first prompt is the person's request with the program's own
      // instructions after a line of three dashes; only the request is theirs.
      case "agent.prompted": return ["Told", String(b.text || "").split("\n---\n")[0]];
      // With full access nothing is refused; a call the guarded rules would
      // have stopped says so, so it stands out.
      case "tool.opened": return b.guarded
        ? [b.tool || "Tool", `${b.detail || b.what || b.tool} (the guarded rules would have ${b.guarded === "deny" ? "refused it" : "asked you first"})`, b.guarded === "deny" ? "bad" : ""]
        : [b.tool || "Tool", b.detail || b.what || b.tool];
      case "subagent.opened": return ["Helper", b.agent_type || "a helper started"];
      case "permission.decided": return ["Refused", `${b.what || b.tool}. ${b.why || ""}`, "bad"];
      case "hook.missed": return b.hook === "Stop"
        ? ["Turn end heard late", "The program never heard this turn end; it saved the work when Claude Code said it was waiting", ""]
        : b.caught
        ? ["Asked late", `${b.what || b.tool}: the program was asked only when Claude Code was about to ask you, and decided then`, ""]
        : ["Not asked", `${b.what || b.tool} ran without the program being asked first; Claude Code allowed it by itself`, "bad"];
      case "question.asked": return ["Asked you", b.text, "bad"];
      case "question.answered": return ["Answered", b.said ? `${deviceName(e.by)} chose "${b.said}"` : `${deviceName(e.by)} said ${b.answer === "yes" ? "allow" : "deny"}`, "person"];
      case "run.billing": return ["Billing changed", `Now billed to the ${b.billing === "api" ? "OpenAI API key, per token" : "ChatGPT subscription"}${b.fresh ? ", in a fresh session" : ""}: ${b.why || ""}`, "person"];
      case "codex.turn-failed": return ["Codex stopped", b.message || b.info, "bad"];
      case "codex.resume-failed": return ["Did not carry over", b.why, "bad"];
      case "codex.not-switched": return ["Not moved to the API key", b.why, "bad"];
      case "question.expired": return ["No answer", "Nobody answered in time, so it was not allowed"];
      case "question.withdrawn": return ["Question closed", b.why];
      case "agent.stopped": return b.paused
        ? ["Waiting", `${b.message ? b.message + " " : ""}It carries on when this reports: ${(b.background || []).join(", ")}`]
        : ["Finished a turn", b.message || ""];
      case "agent.pause-ended": return ["Stopped waiting", `${b.why}, so its turn was called over`, "bad"];
      case "agent.notified": return b.type === "idle_prompt" ? null : ["Needs you", b.message || b.type, "bad"];
      case "work.landed": return ["Saved to main", `${b.commits || 0} commit${b.commits === 1 ? "" : "s"}, ${(b.files || []).length} file${(b.files || []).length === 1 ? "" : "s"}${b.sha ? `, ${b.sha.slice(0, 7)}` : ""}`, "good"];
      case "work.not-landed": return [b.sent_back ? "Sent back" : "Not saved", b.sent_back ? "Its work clashed with main; it was sent back to fix it" : b.reason, b.sent_back ? "" : "bad"];
      case "run.taken-over": return ["Taken over", `${deviceName(b.device)} took the keyboard`, "person"];
      case "run.handed-back": return ["Handed back", `${deviceName(b.device)} handed it back after ${Math.max(1, Math.round((b.minutes || 0) * 60))} seconds`, "person"];
      case "input.typed": return ["Typed", b.text, "person"];
      case "message.sent": return ["Sent it", b.text, "person"];
      case "message.queued": return ["Queued for it", b.text, "person"];
      case "message.failed": return ["Not delivered", `${b.why || "It never reached the run."} ${b.text || ""}`.trim(), "bad"];
      case "work.unfinished": return ["Sent back", `It ended a turn with work uncommitted: ${b.why}. It was asked to finish it`, ""];
      case "run.ended": return ["Ended", endedWords(b), endedBadly(b) ? "bad" : ""];
      default: return [e.kind, ""];
    }
  }

  // Whether an ended run failed. The program works this out and records it as
  // ok; entries written before 16 September 2026 have no ok, so they are read
  // the way they were read then.
  function endedBadly(b) {
    if (b.ok !== undefined) return !b.ok;
    return b.how === "exited" && !!b.code;
  }

  // The exit code a process gives when SIGTERM ends it, 128 + 15. Claude Code
  // answers SIGTERM by closing its session properly and exiting with it.
  const TERM_EXIT = 143;

  // What a run left behind that never reached its branch, in the same words the
  // program uses (`work_left` in one/views.py). It goes on the Ended line,
  // because "closed to make room" on its own is what let run 8109f4b5 read as
  // finished on 17 September while the whole of its work sat uncommitted.
  function leftBehind(b) {
    if (b.dirty) return "it left changes that were never committed";
    if (b.unsaved) return `it left ${b.unsaved} commit${b.unsaved === 1 ? "" : "s"}`
      + ` that never reached ${b.target || "main"}`;
    return "";
  }

  function endedWords(b) {
    const left = leftBehind(b);
    return endedHow(b) + (left ? ` - and ${left}` : "");
  }

  function endedHow(b) {
    // It was asked to leave and would not, so the terminal was taken away.
    const pushed = b.forced === "SIGKILL" ? ", after it had to be killed"
      : b.forced ? ", after it would not leave when asked" : "";
    if (b.how === "stopped") return "stopped by a person" + pushed;
    if (b.how === "closed-idle") return "closed after sitting unwatched" + pushed;
    if (b.how === "closed-for-room") return "closed to make room: the program was near its memory limit" + pushed;
    if (b.how === "lost") return b.why || "its terminal was gone";
    if (b.how === "failed-to-start") return `could not start: ${b.why || ""}`;
    if (b.signal) return `terminated by signal ${b.signal}`;
    if (b.code === TERM_EXIT && !endedBadly(b)) return "terminated after its work was done";
    return b.code ? `exited with code ${b.code}` : "exited";
  }

  function addTimeline(entry, live) {
    if (SKIP.has(entry.kind)) return;
    const said = describe(entry);
    if (!said) return;
    const [kind, what, tone] = said;
    const li = el("li", tone || "");
    const time = el("time", "", clock(entry.at));
    time.dateTime = entry.at;
    const body = el("span", "what");
    const full = String(what || "");
    const text = document.createTextNode(full.length > LONG ? full.slice(0, LONG).trimEnd() + "…" : full);
    body.append(el("span", "kind", kind), text);
    if (full.length > LONG) {
      const more = el("button", "more", "Show all");
      more.type = "button";
      more.addEventListener("click", () => {
        const open = more.textContent === "Show all";
        text.textContent = open ? full : full.slice(0, LONG).trimEnd() + "…";
        more.textContent = open ? "Show less" : "Show all";
      });
      body.append(more);
    }
    li.append(time, body);
    const list = $("timeline");
    list.prepend(li);
    while (list.children.length > 400) list.lastChild.remove();
    if (live) renderRunHead();
  }

  // --- the work tree -----------------------------------------------------------------

  let treeWatched = false;
  async function watchTree() {
    try {
      const got = await send("tree", { watch: !treeWatched });
      treeWatched = true;
      state.tree = got.tree;
      renderTree();
    } catch (err) { console.warn("one:", err.message); }
  }

  function renderTree() {
    const root = $("tree-root");
    const kids = (state.tree && state.tree.children) || [];
    root.replaceChildren(...kids.map(treeNode));
    $("tree-empty").hidden = kids.length > 0;
  }

  function treeNode(node) {
    const li = el("li");
    const line = el("span", `node ${node.kind}`);
    const st = node.queued ? "queued" : node.state === "waiting" ? "asking" : node.state === "running" ? "working" : node.state;
    line.append(el("span", `dot ${st}`));
    line.append(document.createTextNode(node.kind === "worker" ? node.label : (node.what || node.label || node.id)));
    if (node.kind === "tool" && node.label) line.append(el("span", "label", node.label));
    li.append(line);
    if (node.children && node.children.length) {
      const ul = el("ul");
      ul.append(...node.children.map(treeNode));
      li.append(ul);
    }
    return li;
  }

  function showView(view) {
    state.view = view;
    $("tree").hidden = view !== "tree";
    $("tree-btn").setAttribute("aria-pressed", String(view === "tree"));
    if (view === "tree") {
      $("placeholder").hidden = true;
      $("run").hidden = true;
      document.body.classList.add("viewing");
      watchTree();
    } else {
      $("run").hidden = !state.selected;
      $("placeholder").hidden = !!state.selected;
    }
  }

  // --- small things -------------------------------------------------------------------

  // What a space is called on the screen. A run carries the name its space had
  // when it started, and `jarvis` was renamed `rouh` on 22 September 2026, so a
  // run from before then would otherwise name a folder nobody has any more.
  // `OLD_NAMES` in one/config.py is the same map on the server. RENAME.md.
  const SPACE_WAS = { jarvis: "rouh" };
  function spaceName(space) {
    const now = SPACE_WAS[space] || space;
    return now === "assistant" ? "The assistant" : `Space ${now}`;
  }

  function deviceName(id) {
    if (!id) return "someone";
    if (id === "console") return "the server's terminal";
    if (id === "program") return "the program";
    if (id === "phone") return "the phone";
    if (id === "run") return "the run";
    if (state.device && id === state.device.device) return "you";
    const dev = state.devices.get(id);
    return dev ? dev.name : id;
  }

  function when(at) { return at ? new Date(at).getTime() : 0; }
  function ago(at) {
    if (!at) return "";
    const s = Math.max(0, (Date.now() - when(at)) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }
  function clock(at) {
    return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }

  // --- wiring ---------------------------------------------------------------------------

  $("show-ended").addEventListener("change", (e) => { state.showEnded = e.target.checked; renderList(); });
  $("show-archived").checked = state.showArchived;
  $("show-archived").addEventListener("change", (e) => {
    state.showArchived = e.target.checked;
    store("one.showArchived", state.showArchived ? "yes" : "no");
    renderList();
  });
  $("term-wrap").addEventListener("click", () => { if (term) term.focus(); });
  $("back").addEventListener("click", () => {
    document.body.classList.remove("viewing");
    if (state.selected) send("detach", { run: state.selected }).catch(() => {});
    state.selected = null;
    history.replaceState(null, "", location.pathname);
    showView("runs");
    renderList();
  });
  $("tree-btn").addEventListener("click", () => {
    if (state.view === "tree") {
      showView("runs");
      if (!state.selected) document.body.classList.remove("viewing");
    } else showView("tree");
  });
  $("stop-btn").addEventListener("click", async () => {
    const run = state.runs.get(state.selected);
    if (!run) return;
    $("stop-btn").disabled = true;
    try { await send("stop", { run: run.id }); } catch (err) { console.warn("one:", err.message); }
    $("stop-btn").disabled = false;
  });
  $("say-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("say-text").value.trim();
    if (!text || !state.selected) return;
    try {
      await send("say", { run: state.selected, text });
      $("say-text").value = "";
    } catch (err) { $("say-text").placeholder = err.message; $("say-text").value = ""; }
  });
  // The spaces a run can work in, the assistant first (D42), and two ways to
  // add one: a folder by its project's name, or a repository (D44).
  let foldersBase = "";
  function showFolderHint() {
    const name = $("start-folder").value.trim();
    $("start-folder-hint").textContent = foldersBase
      ? `On the server: ${foldersBase}/${name || "…"}, made if it is not there yet.` : "";
  }
  function showAdd() {
    const chosen = $("start-space").value;
    $("start-folder-label").hidden = chosen !== "+folder";
    $("start-repo-label").hidden = chosen !== "+repo";
    showFolderHint();
  }
  // Who pays is a question only for Codex. The key is offered only where the
  // program has one (its hello says), and picking it says what it costs.
  function showBilling() {
    const codex = $("start-engine").value === "codex";
    const can = !!(state.device && state.device.codex_api);
    $("start-billing-label").hidden = !codex;
    const keyOption = $("start-billing").querySelector('option[value="api"]');
    keyOption.disabled = !can;
    if (!can && $("start-billing").value === "api") $("start-billing").value = "subscription";
    $("start-billing-hint").textContent = !can
      ? "The OpenAI API key has not reached the program here, so only the subscription can be used."
      : $("start-billing").value === "api"
        ? "Billed per token to the OpenAI API account, for this run only. Every other run stays on the subscription."
        : "If the subscription runs out, the run pauses and asks before anything is billed to the API key.";
  }
  $("start-engine").addEventListener("change", showBilling);
  $("start-billing").addEventListener("change", showBilling);

  async function fillSpaces() {
    try {
      const got = await send("spaces", {});
      foldersBase = got.folders || "";
      const pick = $("start-space");
      const chosen = pick.value;
      const addFolder = el("option", "", "Add a folder…");
      addFolder.value = "+folder";
      const addRepo = el("option", "", "Add a repository…");
      addRepo.value = "+repo";
      pick.replaceChildren(...got.spaces.map((s) => {
        const o = el("option", "", s.name === "assistant" ? "The assistant, in your workspace"
          : s.folder ? `${s.name} (the folder ${s.folder})`
          : (s.repo ? `${s.name} (${s.repo})` : s.name));
        o.value = s.name;
        return o;
      }), addFolder, addRepo);
      pick.value = chosen.startsWith("+") || got.spaces.some((s) => s.name === chosen) ? chosen : "assistant";
    } catch (err) { /* the assistant alone stays on the list */ }
    showAdd();
  }
  $("start-space").addEventListener("change", showAdd);
  $("start-folder").addEventListener("input", showFolderHint);
  $("start-btn").addEventListener("click", () => {
    $("start-error").hidden = true;
    fillSpaces();
    $("start-billing").value = "subscription";
    showBilling();
    $("start-dialog").showModal();
    $("start-brief").focus();
  });
  $("start-cancel").addEventListener("click", () => $("start-dialog").close());
  $("start-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const brief = $("start-brief").value.trim();
    if (!brief) return;
    const button = $("start-form").querySelector("button.primary");
    try {
      let space = $("start-space").value;
      if (space === "+folder" || space === "+repo") {
        // What is added here becomes a space, then the run starts in it.
        const folder = space === "+folder";
        const box = $(folder ? "start-folder" : "start-repo");
        const given = box.value.trim();
        if (!given) {
          throw new Error(folder ? "Write the project's name."
            : "Write the repository's name as GitHub shows it: owner/name.");
        }
        button.disabled = true;
        button.textContent = "Adding it…";
        space = (await send("add_space", folder ? { folder: given } : { repo: given })).space;
        box.value = "";
        await fillSpaces();
        $("start-space").value = space;
        showAdd();
      }
      const engine = $("start-engine").value;
      const fields = { brief, space, engine };
      // Said only when it is the key, so a run on the subscription is asked
      // for in exactly the words it always was.
      if (engine === "codex" && $("start-billing").value === "api") fields.billing = "api";
      const got = await send("start", fields);
      $("start-dialog").close();
      $("start-brief").value = "";
      setTimeout(() => select(got.run), 150);
    } catch (err) {
      $("start-error").textContent = err.message;
      $("start-error").hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Start";
    }
  });
  window.addEventListener("hashchange", () => {
    const wanted = new URLSearchParams(location.hash.slice(1)).get("run");
    if (wanted && wanted !== state.selected) select(wanted);
  });
  window.addEventListener("resize", () => {
    if (term) term.options.fontSize = fontSizeFor(term.cols);
  });
  setInterval(() => { renderList(); if (state.selected) renderRunHead(); }, 30000);

  connect();
})();
