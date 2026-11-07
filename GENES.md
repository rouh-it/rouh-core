# Genes: Rouh's abilities, one manifest each, and the navigation drawn from them

Rouh's features are called **genes**: not features, apps or plugins.
Petar named them on 12 October 2026, the day the registry was built: "build that grouping and architecture change with contracts."
It was `rouh/features/` and `FEATURES.md` for its first hours.

## What a gene is

A gene is an ability Rouh has: Decisions, Clockwork, Thoughts, Synapse, Payments, the task browser.
It is an idea, written down once, that can be shared between Rouhs, and each Rouh grows it in its own way: its own data, its own settings, how far it has taken it.
Two Rouhs can carry the same gene and be different with it, the way two people carry the same gene and are different with it.

A gene is not execution.
Execution is what the orb's lines show, and only that: a spike out of the core is a job, a branch off it is a sub-agent, a twig along a line is a tool call (`rouh/static/app/orb.js`, the work tree, `TELEMETRY.md`).
Those come and go as work runs; a gene stays whether or not anything is running.
**A gene is never drawn as a line on the orb**, and nothing in the orb reads the gene registry (`python3 -m rouh.genes` fails if it does).
A gene may of course start work that the orb then shows, as Synapse's nightly run does, but the line is the run, never the gene.

## What a gene may change: everything but the protected core

Petar decided on 12 October 2026 that a gene "can really modify Rouh in any possible way".
On 24 October 2026, asking for the protected core to be built (task 98, step 98-23: "okay build 98-23 please"), he narrowed it, and this is the rule now:

**A gene may change Rouh in any way except the protected core.**

The protected core is the `rouh-guard` image (`guard/`, `guard/README.md`): the key proxy, the check a new base and every change must pass with its frozen security checks, the start scripts, the signature check on a shared gene, the doctor, and the change step that keeps undo points.
A Rouh uses it and cannot edit it; only the makers' signed releases change it.
Everything a person feels stays the Rouh's to change: every page, skill, tool, prompt, rule and approval screen, the one program, its own checks in `rouh/selfcheck/`, its libraries in `/extra`, and its stack file (`deploy/stack/compose.yml`), within the rights the stack check allows.

So a gene can no longer:

- edit the doctor or stop it from going back, or delete or rewrite an undo point;
- edit the key proxy, or read a model key from the worker;
- edit the stack check, or apply its stack file itself (only Rouh for Mac does, after the check);
- edit the frozen security checks that decide whether a change goes live;
- accept a shared gene whose signature does not check out;
- remove the guard or key proxy service from its stack, or change their mounts.

A gene that needs something the protected core does not have yet says so with `needs_guard` in its manifest.
The core talks to a Rouh only through numbered contracts (keys, changes, check, and the check face, `rouh/checkface.py`); within one number it only adds, and an old number is kept for at least a year, so a gene written against one keeps working.

## The gene registry

Every gene declares itself once, in one file, its gene manifest, and everything that lists Rouh's genes reads that file and nothing else.
The registry is `rouh/genes/`: one JSON gene manifest per gene in `rouh/genes/manifests/<id>.json`, read and checked by `rouh/genes/__init__.py`.
From it come:

- **the navigation's links**, beside its rail of six group boxes, which the page draws from the registry (`NAV_GROUPS`, `rouh/templates/rouh/_nav_row.html`) and has no link of its own written into it;
- **Search**, which finds a gene by its name and by the words people use for it, on All, first (`searching.gene_lines`);
- **the count of presses** in Settings, Stats, of each group box and each link beside it, and the flow from one to the next (`rouh/navtaps.py`, `genes.nav_keys`, `genes.GROUPS`);
- **the page's copy**, as JSON (`#rouhGenes`), which `rouh/static/app/navgroups.js` uses to pick the group, open a link and draw a found gene's glyph.

## The rule for anything new

1. **A new gene ships its manifest.** A page, a destination, a place on the canvas, a Settings group: one gene manifest in `rouh/genes/manifests/`, named by its id.
2. **It never adds a hard-coded navigation link.** Not in `index.html`, not in a template, not from a script. If it belongs in the navigation, its manifest says `"place": "list"` and the group it belongs in, and the link appears.
3. **A new gene starts as a lab.** `"maturity": "lab"` marks it with a small LAB tag and lists it last in its group. When the owner accepts it, the same commit that says so changes it to `"accepted"`. What the nightly feature run builds are genes in the lab, behind their switch (`"switch"`), off until the owner keeps each in Mutations (EVOLUTION.md).
4. **Check it**: `python3 -m rouh.genes`. `land.sh` runs it (`genes_guard`) before it pushes work that touches the registry, the page's markup or its script, and will not land work that breaks the contract.

## The six groups

The groups are a rail of six stacked boxes down the left of the navigation, each the group's own glyph over its name, and beside the rail a column of the picked group's links (Petar, 12 October 2026, from the sketch on card 1462: "I like the sketch you had with the vertically stacked boxes for the categories where they have also icons").
The rail and the column share the navigation's width, the rail 62 pixels of it, and on a phone or a tablet they are the same inside the menu the orb opens.
The boxes stand in this order, top to bottom, always; nothing reorders them, by use or otherwise.
Each group's glyph is in the registry beside its name (`GROUP_ICONS` in `rouh/genes/__init__.py`), held to the same contract as a gene's icon: Now a dot in a circle, Work a stack, Time a clock, Memory a few nodes joined into a network, Evolution a fork, Anatomy a pair of lungs.
The fifth group was Machine, under a cog, until 13 October 2026, when Petar renamed it (fr_d3dbbd554a2a): "we're not a robot. We're a living thing"; its memory glyph, a spark, went the same day, because "our memory is made up of interconnected nodes".
Only its name changed: its id is still `machine`, in every manifest, shared gene, count of presses and remembered group.
Evolution was added right before Anatomy on 13 October 2026 (task 94, step 94-08: "an extra tab box in the navigation that is called evolution right before anatomy ... Evolution will have an icon of forking"), with exactly two links, Parameters and the Gene library; the deck, Decide later, mutations, questions and learning are views inside the library, never links of their own.
On 14 October 2026 Petar made the Gene Pool a third link of its own and renamed the Gene library Mutations (fr_a982710d30c7): "So gene pool need to be its own item in evolution. Gene library competes as name so it should be renamed to mutations."

| Group | What is in it | Its links today |
|---|---|---|
| `now` | What needs the owner now | Decisions, Morning brief, Live browser (while a browser is open) |
| `work` | The work | Task browser (with New task), Control room, Goals, Quests |
| `time` | What happens at a time | Clockwork |
| `memory` | What is kept | Thoughts, Rules, Trusted contacts, Synapse (lab), Receipts (lab, behind its switch), Boxes (lab) |
| `evolution` | What grows and changes Rouh, and the runs that do the work (EVOLUTION.md) | Metabolism, Parameters (lab), Mutations (lab), Gene Pool (lab) |
| `machine` (shown as Anatomy) | Rouh itself | You, Your Rouh, Connections, Behaviour, Money and Meta, Anatomy's own groups |

Anatomy is one link since 14 October 2026 (card 1554), in place of Settings and of the links beside it that repeated Settings' pages (Payments, Models, Heartbeat, Services, Stats) and Offline.
It opens `/anatomy`, a status board with a line for each of Anatomy's own six groups, You, Your Rouh, Connections, Behaviour, Money and Meta (`genes.ANATOMY`), saying only what needs attention in each, or All fine (`rouh/anatomy.py`).
Rouh Land Account is the sixth since 4 November 2026 (Petar: "in the settings it needs to be clear what is relevant to rouh.land"): Your profile (the rouh.land account, `rouh/landaccount.py`), Rouh profile (Birthday until then), Models and the Gene Pool (Meta's Genes until then); the same day Trusted contacts moved from Connections and Offline from Meta to Behaviour, and This build, which was under You, Account, became a section of Meta.
**Replaced (7 November 2026, task 141, step 141-17, "one home for each journey"):** Rouh Land Account is **Your Rouh**, one page about the Rouh itself at `/anatomy/your-rouh` (a group with one section is that section's page): a headline and three tiles (Name, rouh.land, URL), Needs you only when something is wrong, then the rouh.land card (connect, connect now with rouh.land's code, try again, disconnect with a sheet), Your Rouh's URL (Connections, Phone until then, with an (i) that says what kind of URL it is), Name (official name, what you call it, owner) and What others can see. The person's own rouh.land account is a card on You, **Your account** (`landaccountpage.js`), which also has the password About You had; Models moved to Behaviour and the gene registry and lab to Meta, Gene registry. Your profile, Rouh profile and Phone have no old address.
Each group is a page at `/anatomy/<group>` that is a menu of its sections, each its name over a line saying what it is (`genes.about`), and each section is a page of its own at `/anatomy/<group>/<section>`, with Back to its group's menu (Petar, 14 October 2026, fr_d9e20791f108: "You for example should have a menu with the you items, not one single page where everything is put").
A section is a gene whose `route` is `/anatomy/<group>/<section>` and which has `anatomy.order`: that one manifest gives it its place in the side list's group, its address and its section, and nothing else lists them (`genes.anatomy`, `genes.SECTIONS`).
A section that is a view of another section's page says so with `anatomy.under`, naming that section: its group's menu does not list it, and it is reached from that page's own tabs, as the heartbeat's beats are from the Heartbeat page since 7 November 2026 (task 169, step 169-13).
Every old `/settings/<section>` address, and `/settings` itself, is sent on to the same section (`addressing.anatomy_address`), except a section moved on 4 November 2026 (`genes.MOVED`): "when I say move, don't leave backup forwarding links", so its old addresses, under `/settings` and under its old group, are not found.
The one exception is rouh.land's own return address, `/anatomy/meta/birthday`, which rouh.land's site writes itself and accepts no other: only a return carrying `?birth=` or `?recovery=` is sent on to Your Rouh (`addressing.ROUH_LAND_RETURN`).

The Anatomy box's links are its groups, each with its own glyph (`genes.ANATOMY_ICONS`), each opening its group's page straight away (Petar, 14 October 2026, fr_d9e20791f108: "all the 5 groups under anatomy should be in the navigation under the anatomy square tab").
There is no Anatomy link above them since 15 October 2026 ("remove the anatomy link that is at the top, within the anatomy section. No need for that, each subsection goes to the subpage, they can have a link to go up one level"): a group's page has Back to the status board, and Search still finds Anatomy.
They are not genes: the Anatomy gene's manifest says `"as": "anatomy"`, so its link is drawn as those groups, from `genes.ANATOMY`, the same list the side list, the status board and the menus are (`genes.as_links`).
Their presses are counted under `anatomy-<group>`, as part of the Anatomy gene's use.
The same glyphs stand beside the groups on the Anatomy page, and each section's gene's own glyph beside it in its group's menu.
The same day Metabolism, the page of runs, moved from Anatomy to Evolution, at his word: "Metabolism should go in evolution".

The picked box is lit in the accent on the panel's colour.
Only Now carries a count, a small badge on its box: how many decisions wait on the owner's answer, red while one is urgent.
The group that shows when the page loads is the one holding the page the address opens; otherwise the one picked last on that device (`localStorage`, `rouh.navGroup`); otherwise Now.

What is not in the links and never changes with them: the orb and the way it opens the navigation, the close button where the orb was, the orb's row and its expansion to the whole screen, and the dedicated area under the links - Rouh, Gene therapy, the profile row with the notifications and Search.
Those have genes too (`"place": "dedicated"`), so Search finds them, but nothing here draws them.

The menu behind the person's own name holds Edit, which opens About You (`/anatomy/you/about-you`, the `profile` gene; You, Profile until 4 November 2026), and Sign out, and nothing else.
Petar took Settings, Rules and Offline out of it on 13 October 2026 (fr_02048b1ef832), since Settings is in Anatomy and Rules in Memory, and moved Offline into Anatomy; Voice detection went to a group of Settings the same day.

Waiting tasks and the inbox are not links of their own: Decisions is where everything waiting on the owner is answered, a task's question included, and Petar had a Waiting on you row taken out of the sidebar on 24 September 2026.

## A gene manifest

```json
{
  "id": "payments",
  "name": "Payments",
  "title": "Payments: the card vault, the spending caps and Stripe",
  "aliases": ["card", "money", "stripe", "spending", "budget"],
  "group": "machine",
  "route": "/settings/payments",
  "icon": "<rect x=\"3\" y=\"5.5\" width=\"18\" height=\"13\" rx=\"2.2\"/><path d=\"M3 10h18M6.5 14.8h4\"/>",
  "attaches_to": [],
  "maturity": "accepted",
  "nav": { "place": "list", "order": 30, "opens": "address" },
  "touches": {
    "permissions": ["charges a sealed card only within the caps set here"],
    "accounts": ["Stripe"],
    "tables": ["payment_settings", "payment_cards", "card_charges", "stripe_links"],
    "jobs": [],
    "remove": "How to take it out again, or undo it."
  }
}
```

| Field | What it is |
|---|---|
| `id` | Lowercase letters, digits and dashes, the same as the file's name. It is also the link's `data-nav`, so presses are counted under it. |
| `name` | What the link says. |
| `title` | The link's hover text, and the line under it in Search. |
| `aliases` | The words people use for it, so Search (and, later, voice) finds it: "inbox" finds Decisions, "reminders" finds Clockwork. |
| `group` | One of `now`, `work`, `time`, `memory`, `evolution`, `machine`. |
| `route` | Its address in Rouh, or `null` when it has none (Rules is a page opened from a button). Moving a page's URL is not done by changing this. |
| `icon` | The inside of a 24 by 24 line drawing: `path`, `circle`, `rect`, `line`, `polyline`, `polygon`, `ellipse`, nothing else. |
| `attaches_to` | What it may later be a tab on: any of `task`, `step`, `person`, `meeting`, `email`, or `[]` for none. Declared now; nothing draws those tabs yet. |
| `maturity` | `lab` or `accepted`. |
| `switch` | Optional: the feature switch (`rouh/switches.py`) it is behind. While it is off for an organisation, the gene is not in its navigation or its Search. |
| `anatomy` | Optional: for a section of one of Anatomy's group pages, `{"order": <where it stands on the page>}`, and `"name"` when the section's heading is not the gene's name. Required exactly when `route` is `/anatomy/<group>/<section>`; the section's name must not be a group's, and is unique. |
| `nav.place` | `list` (a link shown while its group's box in the rail is picked), `dedicated` (the area under the links), `account` (the menu behind the person's own name) or `none` (reached from elsewhere, found by Search). |
| `nav.order` | For a link: where it stands in its group, among the accepted ones or among the labs. Unique within a group. |
| `nav.opens` | `own` (the page's own code wires the link by `nav.row` or `nav.class`), `address` (Rouh goes to the route, as any link inside it does), `press` (presses the control whose id is `nav.press`) or `page` (a server page outside the app). |
| `nav.row`, `nav.controls`, `nav.class`, `nav.marks`, `nav.plus`, `nav.while` | The link's element id (otherwise `nav-<id>`), the layer it opens (`aria-controls`), an extra class, what follows the name (a count `sb-row-hint`, a red dot `sb-row-dot`, the Live browser's `sb-web-who`), a plus beside it (New task on the Task browser), and `browser-open` for a link drawn hidden and shown by the page. |
| `nav.counts` | For a row of the dedicated area, whether its presses are counted in Stats. |
| `nav.as` | Optional, on a plain link: `anatomy` draws it as Anatomy's groups, in its place, each with its glyph and opening its own page. |
| `touches` | `permissions` it acts with, outside `accounts` and services, the `tables` it owns, the scheduled `jobs` it runs, and how to `remove` or undo it. Lists are empty when there is nothing; `remove` is never empty. |
| `uses` | Optional: what counts as using it, so its use is counted as its own (`genes.claims`, the gene log): the `tools` Rouh's model calls for it, the `places` and `settings` groups it opens at, its scheduled `jobs` as `schedule.ran` names them, and the `purposes` of model calls made for it. Its link's presses and its route are its own without saying so. A tool, job or purpose is claimed by one gene only (`python3 -m rouh.genes` refuses a second claim); anything no gene claims is counted as Rouh's own gene, `rouh`. |
| `capabilities` | Optional: what it lets Rouh do for somebody other than the owner (CAPABILITIES.md, `rouh/capabilities.py`): each an id, a version, what it does, the kind of thing it acts on, its effects, its limits, and the tools that carry it out with how their arguments name the resource and the limited values. Checked with the manifest, and against `rouh/capabilities.lock.json` by `python -m rouh.capabilities check`: a change in what one does needs a new version. |
| `signals` | Required for a gene with a switch: how it says it was used, for its trial, below under "How a gene says it was used". |
| `needs_guard` | Optional: the oldest protected core it works with, such as `">=1.0"` (`guard/VERSION`), below under "What a gene may change". The change step reads it: a change whose gene needs a newer core waits, and the gene says "Waiting for a Rouh update", until that core arrives. |

## How a gene says it was used

Petar, 19 October 2026: Sources checked's trial offered "Its own code saying you used it", ticked, though its code never said anything, so the box could never count; its one real use, opening its page, was not counted because that box was unticked.
The same evening: "opening a page, pressing a nav link, or Rouh calling a tool should NOT count as using a gene. Visiting a page usually isn't use."
So how a gene reports that it was used is one contract (`rouh/genes/signals.py`), and the gene's own report is the only use that counts.

- **Declared in one place.** Every gene with a switch has `"signals"` in its manifest, or, with no manifest, in its entry in `rouh/genes/owners.json`: `events`, the named points in its own code where the person uses it, each with one plain line of what the person did ("You pressed PDF in a page's Share menu"), at least one; and, if it has any, `runs`, the points where it acts by itself ("Rouh read the mail with a meeting's guests and said what to raise"), which count for nothing and only say its moment came. A gene that is about a page reports opening it from that page's code, as one of its events (Sources checked: "You opened a task's Sources to look at what its pages cite").
- **Reported through one function.** Its code reports an event or a run with `evolution.used("<switch>", "<event>", who=who, detail=...)`, both written out (the switch may be the module's `SWITCH`). An event the gene does not declare is logged as a fault in `rouh.log` and counts for nothing. There is no other way: `evolution.ran` and `evolution.note` are gone.
- **Checked before landing.** `python -m rouh.genes.signals` fails on a gene with a switch and no events, a declaration of the wrong shape, an event or run declared and never reported anywhere in Rouh's code, or one reported and not declared. `land.sh` runs it before every push of Rouh's Python or the registry (`signals_guard`). `nightly_gene` refuses a gene that declares none.
- **What the trial shows.** A gene's Trial tab lists exactly its events, in their own words, and nothing else: no box for its link, its page, its tools, being taken when offered or running by itself. Every one is ticked when a trial starts; Parameters sets only the days and the uses that pass it.

## The gene log

Petar, 13 October 2026 (task 98, step 98-16): "Everything that remains in my Rouh needs to be formulated as a gene in a list. There will be a log of implemented genes. This log should be automatically populated by anything I build".
The gene log is every gene that remains in this Rouh, one family tree a gene, filled by itself (`rouh/genelog.py`, tables `gene_log`, `gene_log_events`, `gene_log_commits`, migration 0141).
It is a view of Mutations (the Gene library until 14 October 2026), **Gene log**, at `/evolution/mutations/log`, and one gene at `/evolution/mutations/log/<id>` (`genelogpage.js`).

- **Where its genes come from.** Every gene manifest is a gene, born with the contract its manifest had when it was first written. Every gene of Mutations is a gene, with the library's state: waiting for Keep while the library has it to review, kept once kept, off, removed (`follow_library`, called by every answer in the library). Every change that lands is read from the deployed checkout's history (`scan`) and, since 19 October 2026, put to every gene whose files it touched ("Every file belongs to a gene", below); a change from before then was put to a gene by its `Gene: <key>` line (AGENTS.md, "Every change names its gene"), by each manifest it changes, by the night or switch its message names, by the name before its subject's colon, and otherwise by the gene writer, a model call (the use `gene_writer` on the Models page), up to 120 changes a quarter hour.
- **Kept or waiting.** A gene from a change the owner asked for is kept at once: they keep everything they requested. A gene from the nightly run is on and on trial the moment it is built, as Mutations has it (the morning deck it once waited in was taken out on 19 October 2026).
- **A revision or a sub-gene.** A change lands on the family's tip as a revision, unless it changes the gene's contract (what it is, where it appears, what it touches, how to remove it), and then it grows a sub-gene below the tip, which becomes the tip. A manifest's contract is compared before and after the commit; for a gene with no manifest the gene writer says. A version the nightly run built from a mutation request is a sub-gene too.
- **Recency first, or use.** The list is newest change first, or most used, by the number on every row: this person's uses in thirty days (`rouh/geneuse.py`).
- **A use** is one moment a person got something from a gene: its link pressed or its page opened (one moment, whichever is more that day), a tool called for it, its scheduled work run, a model call made for it, or a gene's own word (`evolution.used`), read from the event log and `llm_requests` by the manifest's `uses` and counted a day at a time in `gene_use_daily`. A whole family's use is its root's. Beside the count: its share of all the person's uses, the days it was used and its rank.
- **Marks and the evaluation.** The person marks a gene Essential, Useful or Not for me, and their mark wins. From the 25th of each month, and on Evaluate now, a model reads each gene used that month - its contract and its relative use, never a chat - and gives a score of 1 to 5, what it replaced and about how many minutes a month it saves (the use `gene_eval`).
- **Taking it out** follows its contract: Turn it off (its switch, where it has one), or Take it out, which starts a run briefed with the contract's own "how to remove it" and the changes the log put to it, ending its commit with `Gene-removed: <key>`. A gene from the nightly run is turned off or taken out in Mutations, as it always was.
- **Its switches.** `gene_log` stops reading changes and the gene writer; `gene_usage` stops counting uses and the evaluations. What is already kept stays.

## Every file belongs to a gene

Petar, 19 October 2026, in conversation: "there is no plumbing that is not gene".
Every part of Rouh is a gene, the shared parts underneath included, and every change Rouh gets, from feedback, a chat, the nightly runs, `improve_myself` or any other route, is written into the history of some gene.

- **The map.** `rouh/genes/owners.json` maps every file of the repository, by its path or a pattern, to one or more genes (`rouh/genes/owners.py`). The person's own `workspace/` is outside it: it is their work, not Rouh. A gene's key is a manifest's id or a key of the gene log, so every gene kept its id; a gene with no manifest says its `name` and `what` in the map, which is its record. The most exact pattern wins, and a file two genes share is listed under both. A gene's manifest is its own without being listed.
- **The genes the shared parts became** (19 October 2026): Foundation (the Django project, settings, migrations), Conversation turns (the turn loop), The screen and its cards, Model calls (the LLM service), Landing and deploying, Genes and their history (this map, the gene log, the switches), Test worlds, Talking and listening, and Automatic memory recall, which with Meeting guest research (`meeting-guest-research`, its id kept) were the two switches of Other switches that had no gene. A shared gene lists the genes that need it (`needed_by`, from what imports what: `python -m rouh.genes.owners needs <gene>`).
- **Core.** `"core": true` marks a gene Rouh breaks without: Foundation, Conversation turns, the screen, Model calls, the LLM request log, Landing, Genes, the one program (`run-program`), Account, Rouh, Models, Synapse, Email and calendar, Runs, Tasks, Decisions, Clockwork and Anatomy. A core gene has versions, history and sharing like any gene, and no off switch: its page in the gene log says "Rouh cannot work without it, so it has no off switch", and the map refuses a core gene with a switch. Every other gene keeps its switch.
- **The check.** `land.sh` asks `python -m rouh.genes.owners changed` before every push (`owners_guard`): a change that adds or changes a file no gene owns is refused, naming the file, until the map gives it an owner. Every route that changes Rouh lands through `land.sh` (a run of the one program, a crew job, Rouh's saves of the workspace, a landing by hand), so no route skips it. `python -m rouh.genes` holds the map's own shape, and `python -m rouh.genes.owners check` the whole repository.
- **A version per gene.** The gene log puts every landed change to each gene whose files it touched, as one version in its history (`_attribute_by_map`), or a sub-gene when it changed a manifest's contract. No model is asked. A title, a word or a fix is a version of a gene that is there; a gene is new only when the map gains one, which is Rouh gaining an ability.
- **Where it was asked for.** `land.sh` writes which run landed which commits (`landed.tsv` in the landing folder), and each version says where its run came from: the person's words in a chat or by voice, their feedback, a mutation request, the nightly feature or refactoring run, or by hand (`genelog.source_of`).
- **Nothing new to decide or see.** A change the owner asked for lands as it does today. A gene's history on its page is closed until opened. Only a brand-new gene nobody asked for (one a nightly run added to the map) is one line in Mutations, under On trial, saying what it is, with no yes or no.
- **Switches.** A switch a gene has, from its manifest or the map, is turned on that gene's page in the gene log or its row in Mutations; Other switches holds only switches no gene has.

## The Gene Pool

Petar, 13 October 2026 (task 98, step 98-16): "the gene registry should be within Rouh and not be public-facing ... My Rouh needs to be registered with the repository, and it needs to know who's submitting it ... I also need to look at the browser and install it, but I'd like to be able to tell it how I want it different. That would fork the gene".
The Gene Pool (a working name, `genepool.NAME`, one change to rename) is where Rouhs give genes to each other: this Rouh's side is `rouh/genepool.py` and Evolution's **Gene Pool** page (`/evolution/pool`, one family at `/pool/<id>`, `genepoolpage.js`, its own manifest `gene-pool.json`; a view of the Gene library until 14 October 2026); the Pool itself is the `pool` app of rouh.land's registry (task 98's 98-11 project), on only with `ROUH_IT_POOL=1`.

- **Every gene listed at once, unreviewed.** Petar, 7 November 2026 (task 141, after 141-16): "we will not scan people's gene pool additions. too expensive. at some point we can do it and that would be a new section 'approved'. for now, just everything goes up in the server." A gene a member sends is listed in the catalogue the moment it arrives; nothing on rouh.land scans or reviews it, and every node carries `approved` (false) for the reviewed section that may come later. What a Rouh still checks is its own: its owner approves the exact words before anything leaves (below). Signing up on rouh.land is joining the Pool; nothing is shared or installed at sign-up.
- **Closed to all but its members.** The Pool answers registered Rouhs and nobody else: anything that is not a member's signed request gets the closed registry's sign-in redirect, the same as every other registry address.
- **Joined at birth, exchanging nothing.** Petar, 25 October 2026 (task 141, step 141-15): "there is no join button. As soon as you have a birthday and the Rouh is given birth, it should be joining the pool. Then two things need to happen: control outgoing genes and control incoming genes. Both of those need to have their own pages ... By default both of those will be manual or in other words not exchanging, but a person can choose something else."
  A Rouh born on rouh.land joins in the same moment, and an independent one the moment it is registered there (`genepool.join_at_birth`, called by `birth.be_born` and `birth.connect`, and on the beat when rouh.land could not be reached then, at most once an hour). It sends only its name and daily public key, which rouh.land already has from its birth. It does not join when it is not born, not registered, its key is dead, or it left under the same key. There is no Join and no Leave on the page. A Rouh that rouh.land does not know joins only with an invitation the Pool's staff made (`manage.py pool_invite`), by `manage.py gene_pool join`.
  Membership exchanges nothing by itself: the Pool's page (`/evolution/pool`) says where the Rouh stands and opens two pages, **Outgoing genes** (`/evolution/pool/outgoing`) and **Incoming genes** (`/evolution/pool/incoming`), each with its own setting, Manual unless an administrator chose otherwise, in the same control.
- **Registered and signed.** Joining makes this Rouh an Ed25519 key; its private half is sealed (`rouh/encryption.py`) in `pool_membership` and never leaves. Every request carries the Rouh's id, the time, a nonce and the signature; a request older than five minutes or seen before is refused. Every answer is signed by the registry's key, pinned in Rouh (rouh.land's, key id `f6283d53ebeabac7`, unless an administrator pins another), or refused.
- **Nothing leaves before a person has seen it.** Petar, 22 October 2026 (task 141, step 141-09): "I would like to see those genes before they go to the pool. If there is a place where I can click and see them, let me know. If there isn't, then that should be created."
  Every gene of the log is on the review list, on **Outgoing genes**, `/evolution/pool/outgoing` (`/pool/yours` until 25 October 2026, which still opens it; linked from the Pool's page and from each gene's Sharing box in the gene log), with where it stands: Not chosen, Proposed, Approved, Changed since you approved, In the Pool, Declined, Blocked by a check, or Cannot go (not kept, from the Pool unchanged, or part of Rouh's core, which every Rouh already has).
  One gene's page, `/evolution/pool/outgoing/<id>`, shows the exact body each node of its family would send (name, sentence, brief and contract, and the JSON exactly as sent), what the checks found, and Approve, Decline, Take it out of the Gene Pool, and Edit what it sends (name, sentence and brief; the contract is the gene's own).
- **The checks** (`genepool.checks`): a private key, an API key, a password or token written out, or a web address with a password in it **blocks** a node in every mode (shown masked); a person's or the company's name (the organisation's people and trusted contacts), an email address, a phone or bank number, a path on the machine, a machine's address, an outside account or something about money **ask for a look**. People's names, addresses and numbers are taken out of the giver's revision notes in the brief by themselves (`scrub`). No code leaves: only words.
- **Approval is of the exact body.** What is approved is each node's body hash (`gene_log.approved_sha`): a new revision, a new sub-gene, or an edit is a new body and waits for approval again, and an approval pressed on a page that went stale approves nothing. Approving a gene approves its family as shown; a sub-gene can be approved on its own once its gene is.
- **Outgoing** is the sharing mode (`pool_membership.share_mode`, `genepool.MODES`, shown as `MODE_NAMES`), an administrator's: **Manual** (where every Rouh starts: only what a person approves), **Suggested** (`preselect`, called Preselect until 25 October 2026: Rouh proposes each kept gene whose gene node passes every check; a person still approves each) and **Automatic** (`auto`: what passes every check is approved by itself and sent once joined; set only after a confirmation saying so, and anything a check found still waits). Leaving Auto puts everything it approved and had not sent yet back to waiting. A gene a person declined is never proposed or approved by itself.
- **Kept in sync, behind the gate.** An approved family goes to the Pool as soon as this Rouh is a member, parent before child; the beat sends approved bodies and holds the rest. Taking it out, or declining it, withdraws every node of it from the Pool. A gene installed from the Pool as it is is its giver's and cannot be shared again; a fork can.
- **What leaves.** For an approved gene: its name, sentence, contract, a brief written from them with people taken out of its notes, and its number of revisions; joining sends this Rouh's name and public key, and no owner's name (131-05, change 2). Once a day, for each gene given or installed, this month's banded share of the owner's use, days used and rank, whether it is still on, the owner's mark and the model's score. Never a chat, a message, a count, a time, code or a gene nobody approved.
- **Signals.** The Pool scores a node from each Rouh's latest month (the owner's mark first, then the model's score, then share of use, and taken out counts against it), pulled toward 50 when few report, and shows averages only from five Rouhs; installs, forks, still-on rates at 30 and 90 days and thanks beside it (`pool/signals.py`).
- **Incoming** (`pool_membership.incoming_mode`, `genepool.INCOMING`, step 141-15), an administrator's: **Manual** (where every Rouh starts: the Pool's genes are shown, and one is installed or updated only when a person presses it and confirms) or **Off** (nothing comes in: no picks, no installs, no updates and no thanks, refused in code by `genepool._taking`, and the Pool's genes are not shown; genes already installed stay as they are). Nothing installs or updates by itself in either, because each is a build of code into this Rouh. The catalogue is still read hourly in both, so that Outgoing never offers a gene the Pool already has.
- **The nightly feature run installs from the Pool.** Petar, 7 November 2026 (task 141, after 141-16): "nightly improvements may be installing through gene pool so that needs to be activated. either at the nightly or the gene pool itself. you figure it out".
  The night pulls, rather than the Pool pushing: the nightly feature run (`rouh/nightly_feature.py`), the one run the owner authorised to build genes into this Rouh unattended, is told the Pool's genes not here yet in its brief (`genepool.night_brief`) and has the tool `nightly_pool` (`list`, `read`, `install`, `genepool.night_pool`). Install writes the gene into the gene log as installed from the Pool by the nightly run and tells the Pool, and hands the night the same install brief a person's Install starts a run with; the night builds it in its own checkout behind its own switch, lands it with its `Gene:` line and registers it with `nightly_gene`, so it is on trial in Mutations and asked about in the morning like every gene of the night.
  It was put in the night rather than in the Pool because the night is already the authorised, capped, undoable builder: a Pool that installed by itself would be a second unattended builder with none of that. Incoming **Manual** allows it, **Off** refuses it in code (`_taking`), and the switch `gene_pool` stops it. Nothing else installs by itself: no beat, catalogue read or match.
- **Matches.** For you asks a model (the use `gene_match`) which families and which node of each fit this person, from their genes and relative use (never a chat) and the catalogue, with why and, where it would fit better, how to make it different.
- **Installing is a build.** Install as it is, or Make it different with the person's own words (a fork), starts a run briefed with the node's contract and brief as data and only the person's words as instructions; it builds the gene behind its own switch, off, and ends its commit with `Gene: <key>`. The gene log shows it Being installed, then Off once its build lands, and Turn it on keeps it. The Pool is told of the install, and of its removal. Thanks is the only thing a Rouh gives back: nothing is sold or paid.
- **Updates.** An installed gene remembers the version it was built from (`pool_origin.version`). When the catalogue holds a newer one (its giver sent it since, with a changed contract or more revisions), the Pool's page says An update waits, and Update is a build run like Install, briefed with the new version as data and keeping what the person made different; never by itself. The versions it was updated from are kept in `pool_origin.versions`. If an update is wrong: its switch turns it off at once, and Take it out removes it.
- **The same gene from the same code.** Since 23 October 2026 (task 141, step 141-14) two Rouhs built from the same code, which already have the same genes, never see one another's as new. Every family has an identity, `genepool.identity`: its gene's id as the code commits it, and nothing else - the manifest's id (`rouh/genes/manifests/<id>.json`, such as `n19-page-listen`), or for a gene with no manifest its key in the gene map (`rouh/genes/owners.json`, such as `turn-loop`), after `genelog.now_called` for a renamed one. It is never a key made in one installation and never a hash of what the gene says, so it is the same in every Rouh with that code and through every version, and a fork, whose key is its own, has another. A family's root sends it as `identity`, and the Pool keeps it on the family and on the node and lists it in the catalogue.
  A gene the code does not name has no identity: a draft or a night's gene before its build lands a manifest, and the entries the gene writer named from old commits in one Rouh's database (on 23 October 2026 Petar's log had 17 such roots, 10 of them kept, among them `apple-contacts-2`, a key made in that installation). Nothing is assigned to them, since there is no file of theirs to commit an id with; their family is known by its Pool node only, as before, and Preselect and Auto leave it to a person, whose review page says why. An id comes with a manifest committed for the gene, and the manifest is the place to give one.
  **Where the ids reach.** They are in the code, so a Rouh has them once it runs code from 23 October 2026 (main 369d500) or later. A Rouh deployed from main, as on this server, has them when it is deployed. A new container install starts from its base line's cut (`line.json`'s `cut_commit`; line 1.0 is cut at d6abf3de, before this), so it has them only from the first line cut after it. An existing container install, Rouh for Mac's included, never takes new code from an image, a base update or a pull (`deploy/container/code-init.sh`; the Mac app only switches bases and never touches `/code`): it has them only once its own code is changed to this, by a gene built into it, and nothing does that by itself today. A Rouh on older code sends no identity, and its families are matched by node only.
  On the receiving side, a Pool family whose identity is one of this Rouh's own genes (kept, on trial or installing, `genepool._here`) says **Already here: in your Rouh's code** in the list and where Install was; `install` refuses it as it is, in code, and Make it different still builds a fork from it with the person's own words; matching leaves it out, a kept pick of it is dropped, and the local gene gets no `pool_origin`, because it was not installed from the Pool. A fork in that family is still installable unless its own identity is here.
  On the giving side, a gene another Rouh already gave is **Already in the Pool, given by ‹its name›** on the review list (its own tab, Given by another Rouh); preselect does not propose it and auto does not approve it, and a person can send it only as a new version of that family, when its words differ, said so on its page; with the same words there is no Approve and the server refuses it. The Pool holds the same line: a node with a known identity joins the existing family as a `version`, only when the request says a person sent it (`as_version`), and never with the same words as one already there.
  When another Rouh sends a newer version of a gene this Rouh has from its code (after this Rouh's last change of it, with a contract none of its versions has, or more revisions), the Pool page says so under **Newer in the Gene Pool** and on the family, and nothing is installed (`genepool.newer_in_pool`).
- **Joining under its own name.** Since 23 October 2026 (task 141, step 141-11) a Rouh joins under the name its birth gave it (below, "Birthday"), never a typed name, the owner's or the organisation's; until it is born it joins as "A Rouh". A Rouh born or registered on rouh.land joins with no invitation, signing with its birth's daily key, which the membership follows when it is replaced (`private_key` stays empty, `birth.seed_for`); a key revoked there speaks for nobody from that moment. A gene's giver is shown by its name, with its tag only where two members share a name.
- **From a terminal**, `python manage.py gene_pool` says where this Rouh stands (read only), and `gene_pool join --invitation-file F --user NAME` joins with an invitation read from a file, never printed (a Rouh born on rouh.land needs no file).
- **Its switch** `gene_pool` stops every request to the Pool, joining included; Take it out, or Decline, on Outgoing genes withdraws a gene this Rouh gave.

## Birthday: a Rouh's birth, its own name and its keys

Petar, 23 October 2026 (task 141, step 141-11): "Rouh is the species; each Rouh has its own real name, not chosen by the person."
The gene `birthday` is Anatomy, **Your Rouh** (`/anatomy/your-rouh`; Rouh Land Account, Rouh profile from 4 to 7 November 2026, Meta, Birthday before, `rouh/birth.py`, `birthpage.js`; rouh.land's side is the registry's `birth` app, on only with `ROUH_IT_BIRTH=1`, behind its closed door).

- **Its name** comes from its birth public key and nothing else (`rouh/names`, standard library only): a quality and a thing of nature, two words, such as Still Heron, from frozen lists pinned by their hashes (759 qualities, 1,873 nature words, a list of banned pairs and a rule against pairs that would read as an imitation of any people's names). A four-letter tag from the same key, such as ·k7q2, is shown only where names clash. Nobody chooses it, nobody can reroll it, rouh.land included, and it never changes when a key is replaced. `python3 -m rouh.names <public key>` works it out offline.
- **Two keys at birth.** The daily key signs everything and is sealed in `rouh_birth`, so it is in every backup of the database and a restored backup is the same Rouh (with the installation's encryption key, as for every credential). The recovery key is twelve words (BIP-39), shown once and then deleted from the server; it only signs "my new daily key is this one". Its words belong in a password manager or on paper, never in a box of this Rouh.
- **A free Rouh, then a birth on rouh.land.** Petar, 4 November 2026: "free rouh will get birth and official name by connecting to rouh.land. before that, only a nickname by the person. so no keys needed." A Rouh that never connected has no birth, no name and no keys; it works fully, answers to Rouh, and to the nickname each person gives it. Connecting it (the first run's Connect to rouh.land, or Your Rouh) is its birth: its keys are made in that moment and rouh.land grants its official name in its signed card (a version 2 birth, which names nothing). If rouh.land cannot be reached, nothing is kept.
- **Keys are opaque.** No page, card, setting, screen or message shows a key, a key id, a registry id or recovery words, and no setup shows or asks for words. A Rouh's standing is one plain sentence (`birth.standing`).
- **Rouhs from before.** A Rouh born on its own before 4 November 2026 keeps the name its birth key gave it and its keys, and registers with them; a registered Rouh keeps its name and keys. Account recovery or a key change with words begun before still finishes; nothing offers them now.
- **Separate and priced.** How it reaches models is its own choice; a rouh.land account never starts a bill. Born on rouh.land, or registered there, it joins the Gene Pool by itself and exchanges no gene: Outgoing and Incoming genes stay Manual until the owner chooses otherwise (step 141-15).
- **What people call it.** Each person may give it a private nickname, shown to them only (`rouh_nickname`).
- **A second name.** About a hundred days after its birth it reads its own history (counts and gene names, never a chat) and gives itself a second name with a line on why, through the use `second_name` on the Models page; the owner sees it and cannot veto it.
- A Rouh that lived before births existed is born the same way and keeps its history ("It had already lived since ..."). `python manage.py rouh_birth` says where it stands, read only; a birth is never done from a terminal, because its words are shown once to the person who pressed for it.

## Genes on the fly

Petar, 13 October 2026, in the chat "On-the-fly gene formulation": "Let's discuss how we can start formulating genes on the fly".
Rouh's proposal that day (card 1504) is built: `rouh/genedraft.py` and the tool `gene_draft`.

- **Draft.** When the person says "that should be a gene" or asks for one, Rouh's model drafts its contract (what it does, where it appears, what it touches, how to remove it) with `gene_draft`, and shows it. It is a node of the gene log, origin Drafted on the fly, status Draft, listed under Drafts at the top of the Gene log.
- **Shape.** Every revision, by voice or on the draft's page (Change it here), is a version kept in order.
- **Grow it.** Only on the person's words or the page's Grow it: a run builds it from the contract they shaped, behind a switch of its own, off; the log shows it Being built, then Off once its commit (`Gene: <key>`) lands, and Turn it on keeps it. A contract that does not yet say how to take it out is not grown.
- **Leave it for the nightly run.** It goes into the night's brief (`evolution.nightly_brief`), which adds it to task 94's `ideas.md` as an entry of its own and may pick it. Rouh does not write the workspace itself.
- **Drop** throws a draft away; a grown gene is taken out instead.
- **May Rouh offer one by itself?** Petar's question, not answered yet, so it is a setting of the owner's in Evolution's Parameters, Genes on the fly (`evolution_settings.propose`): Only when I ask for one (the default) or Rouh may offer one; with the second, a line in the instructions of the owner's own turns lets Rouh offer once a conversation.
- **Its switch** `gene_drafts` turns the tool off.

## Shared genes from a registry

A gene can also come from somewhere else: a gene registry (task 98, step 98-13; rouh.land, closed for now) lists genes other people publish, each a contract in this same shape, and signs its list.
Petar decided on 12 October 2026 that a gene "can really modify Rouh in any possible way", that it needs no particular permissions, and that genes are rated: so what a gene touches is shown before it is installed, as information and never as a gate.
Since 24 October 2026 that is "in any way except the protected core" (above, "What a gene may change"), and the signature checks below are the protected core's (`guard/rouh_guard/geneverify.py`), asked over its socket.
Rouh's receiving side is `rouh/genelab.py`, drawn by Meta, Gene registry (`/anatomy/meta/gene-pool`, `genespage.js`; Meta, Genes until 4 November 2026, then Rouh Land Account, Gene Pool until 7 November).

- **Off until the owner points it at a registry.** With no address set, Rouh asks nobody anything. The address and the registry's Ed25519 public key are set on the page, and the key is pinned there.
- **Signed lists only.** The index (`index.json`) and the blocklist (`blocklist.json`) are each `{payload, key_id, signature}`, the signature over the payload as sorted, spaceless JSON. A list is refused when its signature does not hold against the pinned key, when it is older than the list Rouh already has (a replayed blocklist would lift a block), or when it is the other kind of list.
- **The contract first.** A gene's page in Rouh (`/anatomy/rouh-land/gene-pool/<publisher>/<name>`) draws its whole contract as the registry signed it: what it is, where it appears, what it touches (what it does, its accounts, its tables, its scheduled jobs) and how to remove it, with its publisher, its rating and its version.
- **Installed only on a yes, into the lab.** Install asks once more; the press carries the hash of the contract shown, and a contract changed since is refused. The files are fetched from where the index points, checked against the index's SHA-256 and, where the registry gives one, against their Sigstore signature and the build that must have made it. They are kept in the database and never run. The gene arrives as a lab, behind a switch of its own, off.
- **Switched on, it is where its contract says,** as a link in its group or found by Search, marked Shared, and it opens its page in Meta, Gene registry. That is all a shared gene's contract can ask of the page: it never presses a control, never takes the dedicated area or the account menu, and its glyph is redrawn from lines and shapes alone. The lab has a switch of its own (`gene_lab`) that turns every shared gene off at once.
- **Nothing a gene's text says is an instruction to Rouh.** A contract, a brief and every file are drawn as text for the person to read. None of it reaches a model, and nothing acts on it.
- **Removing is checked.** Remove deletes the gene's files, its row and its switch, then looks for each of them, its link and its line in Search, and compares what the lab holds with what it held just before the gene came. The page says what it found, and the lab's history keeps it.
- **The blocklist, every hour** (`genelab.Watch`): an installed gene it names is switched off at once, every open tab drops its link, and whoever installed it gets a notice (and the phone, if it is left). A hard block cannot be switched on again; a soft one can. A newer version is shown with what changed in its contract, and told once; it is never installed by itself, and an update keeps the switch as it was.

A shared gene is not built into Rouh by being installed: its brief and tests are kept in the lab to be read. Building one into Rouh's own code is a separate step, not built yet.

## Not yet

- Tabs on a task, a person, a meeting or an email from `attaches_to`: the next step.
- Building a shared gene's brief into Rouh's own code, from the lab (98-04 idea 2, 62-17's carrying).
- Settings' own list of groups, inside the Settings page, is still written into the page; its groups have genes (`"place": "none"`) so Search finds them.
