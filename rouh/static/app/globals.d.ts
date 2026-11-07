/* What the page's other scripts put on window for app.js, and what app.js puts
 * there for them, for the type checker (tools/typecheck). Never loaded by a
 * browser: a .d.ts file is types and nothing else. */

interface Window {
  /** What can wait until the conversation is on the screen, and the call that lets it go (index.html). */
  rouhLater: (fn: () => void) => void;
  rouhLaterGo: () => void;
  /** The composer's code has run, and Send was pressed before it had (index.html). */
  rouhComposer: boolean;
  /** Every script of the page has run (index.html). */
  rouhScriptsRan: boolean;
  rouhSendPressed: boolean;
  /** Hosts app.js hands the pages it frames (app/runs.js). */
  RouhControlHost: Record<string, any>;
  RouhSynapseHost: Record<string, any>;
  RouhBriefHost: Record<string, any>;
  RouhHeartbeatHost: Record<string, any>;
  RouhBeatsHost: Record<string, any>;
  /** What statspage.js is handed: which of its tabs shows, for the address. */
  RouhStatsHost: Record<string, any>;
  /** The page's event tracker (track.js): `RouhTrack.event(name, fields)`. */
  RouhTrack?: any;
  RouhWorkHost: Record<string, any>;
  RouhDecisionsHost: Record<string, any>;
  RouhActionsHost: Record<string, any>;
  RouhReceiptsHost: Record<string, any>;
  RouhHomeHost: Record<string, any>;
  RouhInstrHost: Record<string, any>;
  RouhApprovalsHost: Record<string, any>;
  RouhSourcesHost: Record<string, any>;
  RouhEvolutionHost: Record<string, any>;
  RouhThoughtsHost: Record<string, any>;
  RouhBoxHost: Record<string, any>;
  RouhGenesHost: Record<string, any>;
  /** The pages themselves, once controlroom.js, synapse.js and briefpage.js have run. */
  RouhControl?: any;
  /** Gene therapy's drawer, filled by Rouh's own pages (gene_therapy.js `gtHandOver`): Trials' "Send as feedback". */
  RouhGeneTherapy?: { fill: (body: string, shots: string[], opts?: { edit?: boolean, onSent?: (feedback: any) => void }) => Promise<any> };
  RouhSynapse?: any;
  /** Also known as: one person's identifiers, linked and unlinked, on the contact card and in Synapse
   *  (personlinks.js, rouh/synapse/aka.py). */
  RouhPersonLinks?: { section(opts: Record<string, any>): HTMLElement & { __said(why: string): void } };
  /** A person's email addresses as one list (personaddresses.js, rouh/person_addresses.py). */
  RouhAddresses?: { list(opts: Record<string, any>): HTMLElement & { __redraw(data?: any): void } };
  RouhBrief?: any;
  RouhHeartbeat?: any;
  RouhBeats?: any;
  RouhPayments?: any;
  RouhShipping?: any;
  RouhServices?: any;
  /** Settings, Stats, and the counting of presses in the navigation (statspage.js). */
  RouhStats?: any;
  RouhSignups?: any;
  RouhBirth?: any;
  /** Rouh Land Account, Your profile, and the Gene Pool's standing card (landaccountpage.js). */
  RouhLandAccount?: any;
  RouhPoolStand?: any;
  /** Anatomy, You, Account, and a guest's way back in on their contact card (signinpage.js). */
  RouhSignIn?: any;
  RouhGuestSignIn?: any;
  RouhCloudflare?: any;
  RouhPhone?: any;
  RouhChanges?: any;
  RouhSlack?: any;
  RouhHue?: any;
  RouhDreame?: any;
  /** Anatomy, Behaviour, Draft edits (draftedits.js). */
  RouhDraftEdits?: any;
  RouhSilos?: any;
  /** Rouh Land Account, Gene Pool: shared genes from a registry, and the lab (genespage.js). */
  RouhGenes?: any;
  /** The navigation's links drawn again from the server after a gene's switch (app/navgroups.js). */
  RouhNav?: { refresh(): Promise<void>; route(id: string): string };
  RouhWork?: any;
  RouhQuests?: any;
  /** The Decisions page, and the one drawing of a decision (decisionspage.js, decision.js). */
  RouhDecisions?: any;
  RouhActions?: any;
  /** The Receipts page (receiptspage.js). */
  RouhReceipts?: any;
  /** The Home page (homepage.js), and the sections each kind of device adds to it. */
  RouhHome?: any;
  RouhHomeSections?: any[];
  RouhInstr?: any;
  /** The Mail approvals page, under Now (approvalspage.js). */
  RouhApprovals?: any;
  RouhSources?: any;
  RouhEvolution?: any;
  /** The Thoughts page (thoughtspage.js). */
  RouhThoughts?: any;
  /** The Box page (boxpage.js). */
  RouhBox?: any;
  RouhDecision?: any;
  /** Rouh offline: the outbox and this device's copy (app/offline.js), for decision.js. */
  RouhOffline?: any;
  RouhOfflinePanel?: any;
  RouhAnatomy?: any;
  /** What the tests reach (app/gene_therapy.js). */
  __rouh: Record<string, any>;
  /** The column widths, from the console (app/controls.js). */
  setCols: (want?: any) => any;
  /** xterm.js and its fit add-on, plain scripts loaded before app.js. */
  Terminal?: any;
  FitAddon?: any;
  /** Safari before 14.1. */
  webkitAudioContext?: typeof AudioContext;
  /** The canvas's page drawn again from the server (app/runs.js), for demo mode (app/demo.js). */
  rouhCanvasRedraw?: () => void;
}

/** The one three-dot menu (menu.js, a plain script loaded before app.js). */
declare var RouhMenu: {
  dress(root?: ParentNode): void;
  label(item: Element | null, text: string): void;
  icon(item: Element | null, name: string): void;
  items(menu: Element): HTMLElement[];
  first(menu: Element): void;
  keys(menu: Element, e: KeyboardEvent): boolean;
  place(menu: HTMLElement, anchor: Element, how?: string): void;
  bind(button: Element | null, menu: Element | null, opts?: any): any;
};

/* The page keeps a little of its own state on the elements it draws, under
 * names that start with two underscores (`node.__reset`, `frame.__said`), so
 * that state goes when the element does. */
interface Element {
  [expando: `__${string}`]: any;
}


/* A frame on the canvas remembers which load of it is the newest and which
 * workspace page it is showing (`frameLoad` in app/cards.js), and the last
 * request of its page's own settings, which the next one waits on (`stateRelay`). */
interface HTMLIFrameElement {
  rouhLoad?: number;
  rouhAt?: string;
  rouhState?: Promise<unknown>;
}
