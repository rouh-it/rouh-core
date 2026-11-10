/* The messages on Rouh's one WebSocket, both ways, for the type checker
 * (tools/typecheck). PROTOCOL.md is where each is described in words; this is
 * the same tables as types, and the two are kept in step: a message or a field
 * added to one is added to the other in the same change.
 *
 * A message is `{type, ...fields}`. `ServerMessage` is every one the server
 * sends, `ClientMessage` every one the page sends, and `FromServer<'ready'>` /
 * `ToServer<'hello'>` one of them by its type. handleMessage (app/socket.js)
 * takes a ServerMessage, so `switch (m.type)` narrows each case to its own
 * fields, and send() takes a ClientMessage, so an object literal with a field
 * the protocol does not have is an error rather than a field the server never
 * reads. The values are mostly `any` for now; what matters first is that the
 * names are right, and a value's type can be pinned down message by message.
 *
 * Never loaded by a browser: a .d.ts file is types and nothing else.
 */

/** Every message the server sends, by type, with its fields (PROTOCOL.md, "Server to client"). */
export interface ServerMessages {
  ready: { session_id: any; voice: any; ears: any; state: any; running: any; tools: any; transcript: any; active_chat: any; answering: any; conflicts: any; one_deploying: any; assets: string;
    /** When this Rouh started (ms), and whether the one before it stopped on purpose (`rouh/restarts.py`). */
    started?: number; planned?: boolean; orb: any; browser: any; now: any;
    /** Not in PROTOCOL.md's row until 5 October 2026, sent all along. */
    voice_reply: boolean; pictures: any;
    /** The chat this tab is in, as its own row, until the list comes in `chats` (23 October 2026). */
    chat?: any;
    /** Where the rows before `transcript` end, for `/api/transcript`; "" when it is all of it (23 October 2026). */
    older?: string;
    /** The chats' fields too (`chats` below), on the handshake. */
    draft?: any; forks?: any; general?: string;
    /** As on `chats`. */ asked?: number;
    /** Only on a copy of a handshake from before 23 October 2026, when the lists came with it. */
    chats?: any; folders?: any; objects?: any; tasks?: any; workspace?: any; };
  mode: { voice_reply: any; };
  state: { value: any; turn_id?: any; chat?: any; };
  turn_end: { turn_id: any; chat: any; };
  stt: { text: any; final: any; turn_id?: any; };
  assistant_delta: { text: any; turn_id: any; chat: any; };
  assistant_done: { text: any; usage: any; spent: any; turn_id: any; chat: any; };
  transcript_add: { role: any; text: any; attachments?: any; ts: any; chat: any; id?: number; notice?: boolean;
    /** Said from the phone, on no screen: not drawn in demo mode (`rouh/demo.py`). */
    from_phone?: boolean;
    /** Sent while an answer is being written and not read yet: the page's name for it (`Session.typed`). */
    steer?: string; };
  /** Messages sent while an answer was being written, read by the model now (`Brain._take_steer`). `question` is true when the answer had ended first and the first of them is the next turn's question. */
  steer_taken: { taken: { id: string; message_id: number | null; text: string; attachments: any[]; }[];
    root: number | null; question?: boolean; turn_id?: any; chat?: any; };
  assistant_retract: { turn_id: any; };
  exchange: { root: any; version: any; versions: any; edited: any; turn_id: any; chat: any; note?: any; route?: any; };
  retry: { root: any; version: any; text: any; turn_id: any; chat: any; };
  version_picked: { root: any; version: any; versions: any; edited: any; messages: any[]; chat: any; };
  dictation: { on: any; };
  tool_start: { id: any; name: any; input: any; what: any; detail: any; orb_only?: boolean; };
  /** What Synapse Master's look-ups did for one of the person's messages: its whole timeline, sent whenever it changes (`rouh/recalling.py`). */
  recall: { timeline: RecallTimeline; msg: number | null; note: boolean; turn_id?: any; chat?: any; };
  /** Every step of the turn now running, sent whenever it changes (`rouh/turntrace.py`): the label in place of the dots, the model decision as soon as it is made, and the timeline in the reply. */
  trace: { trace: TurnTrace; turn_id?: any; chat?: any; };
  tool_update: { id: any; name: any; input: any; what: any; detail: any; };
  tool_end: { id: any; name: any; ok: any; summary: any; results?: any; output?: any; orb_only?: boolean; };
  ui: { spec: any; in_place?: any; };
  pictures: { set: any; state: any; rid?: any; count?: any; shape?: any; caption?: any; prompt?: any; pictures?: any; missing?: any; cost?: any; said?: any; turn_id?: any; };
  picture_partial: { set: any; slot: any; src: any; };
  card_filed: { spec: any; };
  audio_start: { turn_id: any; sample_rate: any; };
  audio_end: { turn_id: any; };
  task: { model?: string; actual_model?: string; agent?: string; id: any; status: any; title: any; detail: any; asking: any; options: any; /** Which tab of Metabolism the run is on (`runs.kind_of`). */ kind?: 'mutation' | 'everyday'; };
  tasks: { tasks: any[]; /** The whole list, after a handshake: a run not in it is gone. */ whole?: boolean; };
  rouh_version: { service: any; state: any; running: any; available: any; content: any; };
  one_version: { service: any; state: any; running: any; available: any; content: any; };
  one_deploy: { ok: any; error: any; };
  conflict_done: { id: any; choice: any; label: any; carried: any; said: any; };
  conflict_gone: { id: any; why: any; };
  card_ask_said: { card: any; why: any; again: any; };
  card_pick_said: { card: any; pick: any; why: any; again: any; };
  card_compose_said: { card: any; why: any; again: any; };
  contact_note_said: { card: any; why: any; };
  card_compose_saved: { card: any; at: any; };
  card_inbox_said: { rid: any; do: any; ok: any; why?: any; [more: string]: any; };
  card_inbox_changed: { id: any; archived?: any; unarchived?: any; unread?: any; };
  browser: { open: any; url?: any; title?: any; control?: any; why?: any; asked?: any; doing?: any; mark?: any; from_chat?: any; width?: any; height?: any; show?: any; };
  browser_frame: { data: any; width: any; height: any; };
  browser_forgot: { had: any; };
  clock: { reminders: any; goals: any; telegram: any; };
  /** How many decisions wait on the person, how many of them are urgent, and how many are snoozed (`rouh/decision_desk.py`); and how many actions only they can do wait on Your part, and how many of those hold work up (`rouh/actions.py`). */
  decisions: { open: number; now: number; snoozed: number; actions?: number; actions_blocking?: number; };
  /** Every notice under the bell, newest first, and how many are still to read (`rouh/notices.py`). */
  notices: { items: Notice[]; unread: number; grace: number; };
  clock_shown: { view: any; id?: any; said?: any; chat: any; /** What changed, in a sentence for the bar. */ what?: string; /** A goal's own page. */ address?: string; };
  /** How many thoughts the person keeps, by status, sent on connect and whenever one changes (`rouh/thoughts.py`). */
  thoughts: { open: number; developed: number; archived: number; kept: number; };
  /** Rouh kept a thought in this conversation (`open` false), or was asked to show them (`open` true): one by its `id`, or the list found by `q` and `tag`. */
  /** Rouh was asked to show one section of Anatomy, by its name in `genes.SECTIONS`. */
  settings_shown: { group: string; chat?: string; turn_id?: number; };
  /** An idea in the Incubator changed in this conversation, or the list was asked to be shown (`rouh/incubator.py`). */
  incubator_changed: { open: boolean; number: number; chat?: any; };
  thoughts_shown: { id?: number; open: boolean; what?: string; q?: string; tag?: string; chat: any; };
  /** He asked for a box in this conversation: the Box page opens with an empty one ready (`rouh/boxes.py`). */
  box_open: { chat?: string; };
  /** A box of theirs was saved, changed, deleted or given to Rouh: how many they keep now (`rouh/boxes.py`). */
  boxes: { count: number; };
  tree: { tree: any; now: any; };
  chats: { chats: any[]; folders: any[]; active_chat: any; draft: any; forks: any; /** General's chat id. */ general?: string; /** The chats with a turn running. */ answering?: string[];
    /** The newest `ask` of this tab's the tab's chat and strip in this message were worked out after; older than the page's newest, they are behind it. */ asked?: number; };
  workspace: { tasks: any[]; };
  chat_switched: { chat: any; transcript: any; running: any; forks: any; /** As on `ready`. */ older?: string;
    /** Never on the wire: a move along the strip the page made itself (`stripGo` in app/chats.js). */ local?: boolean;
    /** As on `chats`. */ asked?: number;
    /** The chat already on the tab, drawn again from the top: a branch of its conversation (`branch_redraw`). */ redraw?: boolean;
    /** With `redraw`: the exchange the branch was taken at, which the page scrolls back to. */ focus?: number; };
  chat_peek: { id: string; messages: number; transcript: any[]; marks: any[]; };
  answer_chat: { chat: any; };
  note_sent: { ok: any; parent?: any; note?: any; why?: any; };
  fork_refused: { text: any; why: any; root?: any; };
  stopped: { text?: any; turns?: any; chat: any; };
  error: { message: any; fatal: any; lasting?: any; };
  canvas: { mode: any; task?: any; step?: any; page?: any; stay?: any; chat?: any; };
  objects: { tasks: any[]; projects: any[]; workspaces: any[]; policies: any[]; /** Which kinds can own which (`owning.OWNERS_FOR`). */ owners_for?: Record<string, string[]>; };
  attached: { ok: any; kind: any; id: any; owner?: any; why?: any; };
  search_results: { query: any; kind: any; gen: any; counts: any; results: any[]; /** Which box asked: '' for the search over everything, 'detach' for detaching a fork. */ box?: string; };
  search_labels: { kind: any; labels: any; };
  task_refs: { asked: string[]; refs: Record<string, { title: string; number: string; url: string; icon: string; img: string }>; };
  object_found: { ok: any; row?: any; why?: any; };
  object_changed: { ok: any; act: any; kind: any; id: any; why?: any; pinned?: any; };
  delete_plan: { ok: any; kind: any; id: any; folder: any; label?: any; counts?: any; also?: any; sentence?: any; running?: any; total?: any; why?: any; /** What the server calls it: a task, a subtask, a project. */ what?: string; };
  deleted: { ok: any; kind: any; id: any; label: any; gone: any[]; counts: any; folders: any[]; orphan_links: any; did: any; };
  under: { kind: any; id: any; under: any; };
  run_started: { ok: any; id?: any; title?: any; workspace?: any; policy?: any; note?: any; why?: any; /** Which tab of Metabolism it went on. */ kind?: 'mutation' | 'everyday'; };
  pong: {};
  /** Demo mode for this account, turned on or off on any device, or what is approved changed (`rouh/demo.py`). */
  demo: { on: boolean; preview?: boolean; since?: number; device?: string; dots?: boolean;
    shown?: { numbers: string[]; chats: string[]; settings: string[]; cards: string[]; }; changed?: number; };
  /* Sent by the server, and not in PROTOCOL.md's table until 5 October 2026. */
  /** The default models were changed in Settings: ask for them again (`modeldefaults`). */
  model_defaults: {};
  /** Cheap, Smart or Auto for one chat, the control beside the composer (`chatkinds.choice_of`): said back to
   *  the tab that asked or set it, and to every other tab of the person's when it was set. */
  chat_model: { chat: string; choice?: string; own?: boolean; default?: string; chooses?: boolean; mode?: string;
    options?: { id: string; name: string; hint: string; model: string; model_name: string; }[]; error: string; };
  /** A blind comparison under an answer, with the opt-in on (`rouh/modelvotes.py`, app/compare.js): the
   *  two answers, A and B, the models' names hidden, and the one-time word the vote is posted with. */
  model_compare: { token: string; root?: number | null; a: string; b: string; };
  /** Ask AI's question and answer, written into the chat it was asked from. */
  askai_said: { rows: any[]; };
  /** A tool asks before it runs (`rouh/permissions.py`). */
  permission_ask: { id: string; call_id: any; name: string; question: string; what: any; detail: string; choices: string[]; seconds: number; where: string; };
  /** That question is over: answered, refused, or out of time. */
  permission_done: { id: string; answer: string; timed_out?: boolean; where: string; };
  /** A question answered on another screen is gone from this one. */
  permission_gone: { id: string; };
  /** The model opened or closed a panel, or the orb (`set_panels`). The
   *  transcript is `transcript`, never `chat`: every message carries `chat`
   *  as the id of the chat it belongs to. */
  panels: { tasks?: boolean; transcript?: boolean; canvas?: boolean; orb?: boolean; };
  /** One change to the work tree. Handled by asking for the whole tree; the server does not send it today. */
  tree_delta: {};
  /** Gene therapy (what was Feedback) changed: the board reads it again. */
  gene_therapy: {};
  /** These jobs are gone from the list. */
  tasks_forgotten: { ids: any[]; };
  /** What became of actions done offline, on this device or the other (`rouh/offline.py`). */
  offline_results: { results: OfflineResult[]; };
}

/** Every message the page sends, by type, with its fields (PROTOCOL.md, "Client to server"). */
export interface ClientMessages {
  hello: { client: any; chat?: any; /** The device's time zone, the person's clock (`rouh/clock.py`). */ tz?: string;
    /** Where the tab's strip of forks around that chat ends, or '' (`forks.strip`). */ strip?: string; };
  speech_start: {};
  speech_end: { discard?: any; finish?: any; };
  interrupt: {};
  dictation: { on: any; };
  text: { text: any; attachments?: any; answers?: any;
    /** Sent while an answer is being written: the page's own name for it, said back in `steer_taken`. */
    steer?: string; };
  dismiss_question: { task: any; asked: any; };
  retry: { root: any; text?: any; tier?: 'cheaper' | 'smart'; };
  pick_version: { root: any; version: any; };
  /** The arrows on a card's head: that card drawn in place as one of its versions, on this tab only. */
  card_version: { card: number; version: number; };
  ui_event: { id: any; value: any; };
  set_mode: { voice_reply?: boolean; };
  ping: {};
  set_orb: { cfg: any; };
  /** Read one chat's model choice, or set it with `choice` ("cheap", "smart", "auto", or "" for the Models page's). */
  chat_model: { chat: string; choice?: string; };
  /** A press or a swipe on notices: drawn while the person looked, put away, read, or dismissed. */
  notice: { act: 'seen' | 'later' | 'read' | 'dismiss'; ids: number[]; };
  list_tasks: {};
  list_workspace: {};
  archive_task: { id: any; on: any; };
  mark_seen: { kind?: any; id?: any; ids?: any; deep?: any; };
  get_state: {};
  get_tree: {};
  list_chats: {};
  new_chat: { folder?: any; task?: any; };
  open_chat: { id: any; /** The end of the strip of forks to lay out with it; left out, a chat on the tab's strip keeps it and any other opens alone. */ strip?: string; };
  peek_chat: { id: string; };
  answer_chat: { task: any; };
  note_to_parent: { chat: any; text: any; };
  fork: { from: any; text: any; attachments?: any; /** The exchange to fork after, from a message's own Fork. */ root?: any; };
  close_fork: { id: any; };
  detach_fork: { id: any; /** The task it goes into: a fork is detached into a task or not at all. */ task: string; };
  rename_chat: { id: any; title: any; };
  move_chat: { id: any; folder: any; };
  new_folder: { name: any; owner?: any; };
  rename_folder: { id: any; name: any; };
  delete_folder: { id: any; };
  open_thread: { id?: any; task?: any; alone?: boolean; redraw?: boolean; };
  promote_thread: { id?: any; };
  file_card: { id: any; };
  pin_thread: { id?: any; on: any; };
  delete_chat: { id: any; };
  list_objects: {};
  search: { q: any; kind?: any; gen?: any; /** Which box is asking, said back on the answer. */ box?: string; };
  search_labels: { kind: any; ids: any[]; };
  task_refs: { numbers: string[]; };
  find_object: { kind: any; id: any; };
  pin_object: { kind: any; id: any; on: any; };
  rename_object: { kind?: any; id?: any; folder?: any; title?: any; };
  new_task: { title: any; };
  start_run: { brief: any; workspace?: any; policy?: any; title?: any; owner_type?: any; owner_id?: any; /** 'codex' for Codex rather than Claude Code. */ agent?: string; /** 'api' to bill Codex to the key. */ billing?: string; };
  attach: { kind: any; id: any; owner_kind?: any; owner_id?: any; };
  list_under: { kind: any; id: any; };
  delete_plan: { kind?: any; id?: any; folder?: any; };
  delete_object: { kind: any; id: any; };
  conflict_answer: { id: any; choice: any; };
  card_ask: { card: any; choice: any; /** Where the person is, when the card asked for it (`locate`). */ given?: any; };
  contact_note: { card: any; contact: any; field: any; value: any; };
  card_pick: { card: any; pick: any; };
  card_compose: { card: any; do: any; edits: any; };
  card_inbox: { token: any; do: any; rid: any; id?: any; mode?: any; edits?: any; keep?: any; when?: any; };
  picture_make: { rid: any; prompt: any; model?: any; shape?: any; quality?: any; count?: any; background?: any; references?: any; provider?: any; };
  picture_edit: { rid: any; source: any; source_chat?: any; prompt?: any; mask?: any; image?: any; preview?: any; variation?: any; model?: any; quality?: any; count?: any; };
  browser_watch: { on: any; w?: any; h?: any; phone?: any; };
  browser_take: {};
  browser_give: {};
  browser_stop: {};
  browser_input: { kind: any; x?: any; y?: any; dx?: any; dy?: any; text?: any; key?: any; url?: any; };
  browser_forget: {};
  /* Read by the server, and not in PROTOCOL.md's table until 5 October 2026. */
  /** Allow or refuse what a tool asked (`permission_ask`). */
  permission_answer: { id: string; allow: boolean; };
}

/** Anything that belongs to one thread says which, and a turn's messages which
 *  turn they are, whatever their type (`Turn.emit` sets both). */
/** One notice (`rouh/notices.py`). `state` is new (on the screen), later (put away), or read;
 * `phone` is what became of its Telegram copy: "", due, sending, sent, skipped or failed. */
export interface Notice {
  id: number; kind: string; title: string; body: string; link: string; link_label: string;
  decision: number | null; state: 'new' | 'later' | 'read'; phone: string; at: number;
  phoned_at: number | null;
  /** The commit a finished run put live, or "": a page from before it reloads from this notice. */
  deployed?: string;
  /** Every place it leads, each a button of its own, or [] for one with `link` alone. */
  links?: NoticeLink[];
}

/** One place a notice leads (`run_report.destinations`): a finished run's run, chat, task or
 *  page, as `to` says, with the word on its button and what it opens said in full. */
export interface NoticeLink { to: string; label: string; href: string; title?: string; }

interface Threaded { chat?: any; turn_id?: any }

/** One action done offline, as the server says what became of it (`offline.as_dict`). */
export interface OfflineResult {
  id: string;
  kind: string;
  status: string;
  result?: string;
  device?: string;
  device_kind?: string;
  made_at?: number;
  received_at?: number;
  done_at?: number | null;
  updated_at?: number;
  outcome?: Record<string, any>;
  label?: string;
}

export type FromServer<K extends keyof ServerMessages> = { type: K } & Threaded & ServerMessages[K];
export type ServerMessage = { [K in keyof ServerMessages]: FromServer<K> }[keyof ServerMessages];
/** `ask` numbers each message that moves the tab to a chat or changes its strip of forks, so the server can say which of them a message about the tab already reflects (`asked`, `MOVES` in app/socket.js). */
export type ToServer<K extends keyof ClientMessages> = { type: K; ask?: number } & ClientMessages[K];
export type ClientMessage = { [K in keyof ClientMessages]: ToServer<K> }[keyof ClientMessages];

/* The blocks a card is made of (PROTOCOL.md, "The `ui` spec"). The first ten
 * are the ones the model draws with show_on_screen, and their fields are the
 * tool's own schema (`SCREEN_SCHEMA` in rouh/tools.py); the rest are built by
 * Rouh's own tools, each by the module named beside it. renderBlock
 * (app/cards.js) takes a Block, so `switch (b.block)` narrows each case to its
 * own fields, and each block's drawing function takes its own BlockOf<kind>. */

/** What any block may carry: the id a press on it reports, and a label over it. */
interface BlockBase { id?: string; label?: string; }

export interface Blocks {
  stat: { value?: string | number; hint?: string; };
  /** A row is a list of cells; a bare value is drawn as a row of one. */
  table: { columns?: string[]; rows?: any[]; };
  list: { items?: string[]; };
  text: { text?: string; };
  code: { text?: string; language?: string; };
  chart: { kind?: 'bar' | 'line'; labels?: string[]; values?: number[]; title?: string; points?: any; };
  link: { href?: string; text?: string; };
  image: { src?: string; alt?: string; caption?: string; width?: number; height?: number; };
  html: { html?: string; text?: string; title?: string; height?: number; };
  /** Each page by `url` (the tool's word) or `href`; a bare address is read as one too. */
  sources: { sources?: Array<{ url?: string; href?: string; title?: string; }>; };
  /** A page from the workspace, as a tile that opens it (rouh/pages.py). */
  frame: { href?: string; title?: string; };
  /** A job's work that will not go onto main, waiting on a decision (rouh/conflicts.py). */
  conflict: { id?: string; title?: string; heading?: string; question?: string; state?: string; choice?: any;
              run?: string; pre_branch?: string; sides?: any[]; options?: any[]; };
  /** A contact to save to iCloud, and whether it was (rouh/apple_contacts.py). */
  contact: { name?: string; rows?: any[]; state?: string; status?: string; foot?: string; new?: boolean;
             was_name?: string; remark?: string; contact?: any; me?: boolean; research_said?: string;
             /** Their face: their iCloud picture, else the LinkedIn photo Rouh kept (rouh/meeting_people.py). */
             photo?: string;
             /** What they are also known as - Slack members, names, Rouh's own addresses - and the history of
              *  linking them, from their Synapse dataset `people_ds` (rouh/synapse/aka.py, personlinks.js). */
             aka?: any; people_ds?: string;
             /** Every address of theirs as one list, with label, source, silo and mailbox state
              *  (rouh/person_addresses.py, personaddresses.js). */
             addresses?: { person: string; rows: any[]; silos: any[]; me: boolean; }; };
  /** One email, whole (rouh/mail_alerts.py). `from_photo` is the sender's face when they are a contact. */
  email: { from?: string; to?: string; cc?: string; date?: string; subject?: string; body?: string; filed?: any;
           files?: Array<{ name: string; [field: string]: any; }>; checked?: any; from_photo?: string; };
  /* Built by their own tools and not pinned down yet: any field. */
  ask: { [field: string]: any; };
  people: { [field: string]: any; };
  profile: { [field: string]: any; };
  compose: { [field: string]: any; };
  inbox: { [field: string]: any; };
}

export type BlockOf<K extends keyof Blocks> = { block: K } & BlockBase & Blocks[K];
export type Block = { [K in keyof Blocks]: BlockOf<K> }[keyof Blocks];

/** One card as the page draws it (`renderCard` in app/cards.js): the tool's
 *  title, description and blocks, and what Rouh adds when it keeps it. */
export interface CardSpec {
  title?: string;
  description?: string;
  blocks?: Block[];
  /** Its number in the thread, and when it was drawn (unix seconds). */
  card_id?: number;
  at?: number;
  /** Which version of it this is, of how many (`revise_on_screen`). */
  version?: number;
  versions?: number;
  /** Drawn again from the history rather than new. */
  again?: boolean;
  /** Where it was filed, when it was made into a task's step. */
  filed?: any;
  /** The message it came after, which places it in the transcript. */
  after_message_id?: any;
  /** The call whose line it sits under, inside the answer that drew it. */
  after_call?: string;
  /** Drawn inside an answer with no call to go by: after what its message drew. */
  in_answer?: boolean;
  /** When it was last put at the end of the conversation (unix seconds). */
  placed_at?: number;
}

/** One turn's steps (`turntrace.Trace.snapshot`): every time in ms from the moment the message reached the server (`turn_at`, unix seconds). */
export interface TurnTrace {
  v: number; turn_at: number; elapsed_ms: number; state: 'running' | 'done';
  model: string; model_name: string; tier: string; now: string; note: boolean; root: number | null;
  /** How the turn ended, once it has, and what went wrong; its first token, first written and first spoken word; what its lanes cost in all. */
  outcome?: '' | 'finished' | 'stopped' | 'failed' | 'unfinished' | 'replaced'; error?: string;
  first_token_ms?: number | null; first_word_ms?: number | null; spoken_ms?: number | null; cost?: number | null;
  /** When the answer's last word reached the screen. */
  last_word_ms?: number | null;
  lanes: { id: string; kind: 'router' | 'memory' | 'model' | 'tool' | 'step' | 'wait'; name: string; start_ms: number;
    end_ms: number | null; state: 'running' | 'done' | 'failed' | 'stopped'; model?: string; model_name?: string;
    phase?: 'waiting' | 'thinking' | 'writing' | 'calling'; request?: number; what?: string; tokens_in?: number;
    tokens_out?: number; cost?: number | null; pick?: string; pick_name?: string; easy?: number | null; bar?: number;
    outcome?: string; count?: number; error?: string;
    /** A request's first token (ms on the turn's clock), what it read from and wrote to the cache, and its row in `llm_requests`. */
    first_ms?: number; cache_read?: number; cache_write?: number; request_id?: number | null;
    /** What a tool gave back, in characters, and a look-up of Synapse's trace. */
    size?: number; synapse_trace?: string;
    /** A request's first visible word; a tool's arguments; a tool's short result or the router's reason; what a look-up found. */
    first_word_ms?: number; input?: string; result?: string; ids?: string[]; }[];
  /** How the answer's model was decided, the "Model decision" line, once it is (`modelrouter.timeline`). */
  route?: any;
}

/** One message's look-ups in Synapse Master, as its timeline draws them (`recalling.MessageMemory.timeline`). Every time is in ms from the moment the message came. */
export interface RecallTimeline {
  v: number; source: 'message' | 'clockwork' | 'email'; msg: number | null; root: number | null;
  began: number; elapsed_ms: number; state: 'running' | 'done'; applies: boolean | null;
  wait_ms: number; mark_ms: number; ceiling_ms: number; first_ms: number | null; over_ms: number | null;
  named: { kind: string; label: string; }[]; named_ms: number | null; why: string;
  /** The model's reading of the message, once it has answered or failed (`autorecall.Pick.shown`). */
  pick?: { model: string; provider: string; ms: number; ok: boolean; error: string; cost: number; related: boolean;
    mode: string; readers: { model: string; provider: string; ms: number | null; ok: boolean; error: string;
      won: boolean; agreed: boolean | null; cost: number; }[]; } | null;
  bars: { id: string; tool: string; what: string; start_ms: number; end_ms: number | null; count: number;
    outcome: 'running' | 'back' | 'in_time' | 'empty' | 'late' | 'carried' | 'slower' | 'failed'; error?: string;
    won?: boolean; ids?: string[]; trace?: string; model?: string; cost?: number; tokens_in?: number;
    tokens_cached?: number; tokens_out?: number; }[];
  /** What the seed look-up found, and the recall's own trace in Master's Activity once it is written. */
  seed_ids?: string[]; trace?: string;
  used: { id: string; kind: string; title: string; when: 'first' | 'late' | 'next'; }[];
  tokens: number; carried_in: { text: string; items: number; titles: string[]; }[];
}
