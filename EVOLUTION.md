# Evolution: Parameters, Mutations and the Gene Pool

What the nightly feature run grows for the owner, and how they decide on it and learn it.
Asked for in task 94, step 94-08 ("Learning ten genes a night"), and built on 13 October 2026 in run 2e72efa9, when Petar said "Okay, it is time. Build" it.
The proposal, its research and its demos are the step's page (`workspace/rouh/assistant/94.nightly-rouh-feature-run/94-08.learning-ten-genes-a-night/`); this file is what Rouh does.

## Where it is

A sixth box in the navigation's rail, **Evolution**, right before Anatomy, under a fork glyph (`GROUPS` and `GROUP_ICONS` in `rouh/genes/__init__.py`), with its links, each a gene manifest:

- **Parameters**, `/evolution/parameters` (`evolution-parameters.json`);
- **Mutations**, `/evolution/mutations` (`mutations.json`), with its views `/new` (where it opens), `/trial`, `/passed`, `/failed` and `/month` (the older `/out`, `/week`, `/deck`, `/review`, `/rouh` and `/off` are sent on to the view that holds them now), and one gene on a page of its own, `/gene/<id>` (an old tab's address, `/gene/<id>/<mutations|decisions|questions|learning>`, opens that page at that part); and since 13 October 2026 (task 98, step 98-17) the **Gene log**, `/log` and `/log/<id>`, every gene in Rouh with its use (GENES.md, "The gene log"), drawn by `genelogpage.js` inside the same layer;
- **Incubator**, `/evolution/incubator`, and one idea at `/evolution/incubator/INC-<n>` (`incubator.json`), right under Mutations, below under "Incubator";
- **Nightly run**, `/evolution/nightly` (`nightly-run.json`), beside it, below under "Nightly run";
- **Trials**, `/evolution/trials` (the jobs), one job at `/evolution/trials/job/<n>`, one try at `/evolution/trials/<n>`, the problems at `/evolution/trials/problems` and one at `/evolution/trials/problem/<n>`, the testers at `/evolution/trials/testers` and one at `/evolution/trials/tester/<name>`, and how it works at `/evolution/trials/how` (`trials.json`), below under "Trials";
- **Gene Pool**, `/evolution/pool` and one family of it at `/pool/<id>` (`gene-pool.json`, GENES.md, "The Gene Pool"), drawn by `genepoolpage.js` inside the same layer; and since 22 October 2026 the review list of this Rouh's own genes on their way to it, `/pool/yours`, and one of them as it would leave, `/pool/yours/<id>` (`yours`, because `out` is an old name of Mutations' Passed view). Since 25 October 2026 (task 141, step 141-15) the Pool's page says where this Rouh stands, joined at its birth by itself, and opens **Outgoing genes**, `/pool/outgoing` (that list, with its setting; `/pool/yours` opens it) and one gene at `/pool/outgoing/<id>`, and **Incoming genes**, `/pool/incoming` (its setting, the picks, every gene and what is installed).

Mutations was called the **Gene library**, at `/evolution/library`, until 14 October 2026, and the Gene Pool was one of its views, at `/evolution/library/pool`.
Petar asked that day (fr_a982710d30c7): "So gene pool need to be its own item in evolution. Gene library competes as name so it should be renamed to mutations."
Every old address is sent on to the same view at its new one, with `?chat=` kept (`evolution_library_old_address` in `rouh/project/urls.py`), and a link to one kept in a notice or a decision opens there too (`app/address.js`).
Inside, too, nothing is called library since the same day ("Do not keep the internal evolution/library. Make it into evolution/mutations"): its manifest's id is `mutations` (was `gene-library`), its server address `/api/evolution/mutations`, its tables `mutations_genes` and `mutations_gene_events` (models `MutationsGene` and `MutationsGeneEvent`), and the gene log's column for a nightly gene's key `mutations_key`. Migration `0150_mutations` moved everything kept under the old id with it: its gene and sub-genes in the gene log, its use, marks and evaluations, and the presses of its link. A `Gene: gene-library` line in an older commit is read as `mutations` (`genelog.RENAMED`).

The page is `rouh/static/evolutionpage.js` and `evolutionpage.css`, drawn in the `#evolutionView` layer (`app/runs.js` opens it, `app/address.js` addresses it). The server is `rouh/evolution.py`, `rouh/gene_questions.py` and `rouh/web/evolution.py`; the tables are migration `0140_evolution`.


## Incubator

Petar, 3 November 2026, on task 166's Gene Nursery, a Markdown file: "I don't think this task 166 is the right format. I think it needs to be a feature separately put in navigation with its own page and database + tooling for LLM to manage."
He rejected the name Gene Nursery; an idea incubates until it hatches into a gene or a mutation.
It is every Rouh's, not a setup of his.

**What an idea is.** A row of `incubator_ideas` (`rouh/models/incubator.py`, `rouh/incubator.py`), with every change in `incubator_events`: its number, shown as `INC-<n>` (the nightly run's own list used `I-001` to `I-179`, so the Incubator's prefix cannot be read as one of them); a title; its kind, a new gene or a mutation of a named gene, or not known yet; one main category and any tags; a status; its sources; its name in its source (`I-028`, `N-019`, `70-01`); the full original text exactly as written, and the same text in sections; triage notes; and links to its task, step, chat, pages and files.
The original words are never edited: corrections go in the notes.
Every row carries `org_id` and `user_id`, and every query names both.

**Statuses**: New, Triaged, Go, In build, Built (with what it became), Parked, Rejected, and Merged into another idea (which then holds both ideas' sources and links, and lists the merged one).

**Categories**, one line each (`incubator.CATEGORIES`):

| Category | What it holds |
|---|---|
| UX and UI | what the person sees and touches, and how clear it is |
| Communication | mail, Slack, Telegram, voice, and how Rouh talks and writes |
| Memory and knowledge | Synapse, and what Rouh remembers, finds and connects |
| Autonomy and agents | jobs, runs, the heartbeat, and Rouh acting in the world by itself |
| Integrations | other services, accounts and devices Rouh connects to |
| Security and privacy | keys, permissions, approvals, and data that must not leak |
| Stability and refactoring | fewer breakages, cleaner code, safer changes |
| Speed | answers, pages and runs that come back sooner |
| Cost and models | which model answers, and what Rouh spends |
| Platform and setup | installing and onboarding, the Mac app, the Gene Pool, open source |

An idea given no category gets the one its words point to most (`guess_category`), and anybody changes it in the row.

**Sources**: Ideas project, Nightly feature run, Gene Nursery, Chat, and You, directly.

**The page, redesigned around decisions** (`incubatorpage.js`, `incubatorpage.css`, `rouh/web/incubator.py`, 7 November 2026, task 166 step 166-05, the full tier of the design standard).
Petar: "Imagine journeys and things I actually need to do. Make decisions, pick out what is valuable, connect things that look the same, quickly grasp what was meant and it's vision as well as give my feedback, or chat about the future thing."
The list opens on To decide (New and Triaged) with one sentence of what waits ("16 ideas wait for your decision"), the views with their counts, and "Impact against size", a small grid of the ideas in view by impact (1 to 5) and size (small, medium, large) whose cells filter the list.
Then the search (`/`), Group by (value, category, status, nothing), Sort by (the score, any part, size, how often it came back, number, newest), Add an idea, Chat about the list and the keys (`?`).
The labels are as they were: status, category, kind and source, a line each, the eye in front hiding the ideas that carry it, a press showing only its ideas, the count inside; folded under Filters on a narrow screen, the closed line naming what is on.
Each idea is a row: its score as a bar ranked among the rest, with its number, and the stars; its number and title, and under it "In a line", Rouh's plain sentence of what it is and why it matters; its status, category, size, how often it came back, and "Looks like INC-n" for a lookalike; and four decisions, Take (Go: Gene therapy builds it), Park, Drop (Rejected) and Merge.
A decision changes the row at once, the row stays where it was, dimmed and saying what was done, until the list is put in order again (R), and a message at the bottom says what was done with Undo (or Z); Take waits six seconds before it hands the idea on, so Undo never has to take back a feature request, and a Take still waiting when the page goes away is sent then.
The keys: the arrows and j, k move, T, P, D and M decide the selected row (the one under the pointer), Space opens "At a glance", Enter opens the idea, 1, 2, 3 and 0 set the stars, Z undoes, R re-sorts, Escape closes.
"At a glance", on hover after a moment, on Space or on the row's arrow, shows only what the row does not: the vision, the problem, who it helps, what it looks like in use, where it came from (its sources, its name there, its links) and its size, with its lookalikes; it replaced the preview of the whole text, which repeated the row. The score's own breakdown is still on its hover.
Merge, or a press on a lookalike, opens Compare, a drawer with the two ideas side by side: merge either way (the one with the higher score kept by default), Link them (each lists the other) or Not the same, which the page keeps in the person's settings (`apart`) so the pair is never offered again; each with Undo where it can be undone.
One idea is a page of its own at `/evolution/incubator/INC-<n>`: back to the list as it was, previous and next through the list's order (j, k); its vision and its line first, then the decisions (Take is the page's one primary button, every status and category beside them), At a glance, its feedback and its chat, its words as written in sections (drawn, or the exact characters), its value (score bar, stars, every part with its menu and reason, the formula, how often it came back, Score it again), its lookalikes, links and merged ideas with Compare, where it came from with its pages read in place, and its history.
Feedback is kept with the idea: in its history (`feedback`) and in its notes, dated, so Gene therapy, the scorer and every chat read it; "Chat about this idea" opens the idea's own chat (`incubator-<user id>--inc-<n>`) beside the page, in which the model is told that idea whole.
The tick boxes and their bar still set a status, a category or a merge for many ideas at once.
The page is laid out by its own width, as wide as the screen or as narrow as the space beside the conversation, and on a phone the decisions are a row of their own under each idea, 44 pixels high.
Escape closes a menu, then Compare, then the idea's page, and only then the layer.

**Replaced (7 November 2026, by the paragraph above):** the page as it was from 3 November 2026:
the page (`incubatorpage.js`, `incubatorpage.css`, `rouh/web/incubator.py`): a table with a sticky header; columns sorted by pressing their heading, shown, hidden and moved in Columns or by dragging a heading, and widened by a heading's edge, all kept for the person on the server (`user_settings`, `incubator_page`), with the sort and their own saved views; status, category, kind and source as the task browser's labels (`labels.js`, `labels.css`, shared with it since 3 November 2026), a line each, every label with its eye in front, which hides the ideas that carry it, and its count inside it, kept up to date with the other filters, a press on the label showing only its ideas; the date added and a search over titles, words, notes and source names; views for All, New, Go and in build, From nightly and Still open, and the person's own, which keep their eyes too; and the filters as they were left (labels chosen and hidden, dates, search, view) kept with the rest on the server, saved as they change, so the list is the same from any browser or phone; a preview of the whole text on hover; a side panel with the original words in sections (drawn, or as the exact characters), the links by kind, its pages read in place, the ideas merged into it and its history; status and category changed in the row; and many rows chosen for a status, a category or a merge.
Escape closes a menu, then the panel, and only then the page.

**Scores** (`rouh/incubator_score.py`, 4 November 2026).
Petar: "go implement it. lets see how it feels", and "zero friction on action, the bottle neck should be only my decision".
Every idea has a score, worked out from its parts and never stored itself:

    Score = Impact² × Confidence × Frequency × Pain × Stars × Clarity ÷ Risk

- Impact, 1 to 5, squared, so it weighs most: how much better Rouh gets when the idea works; an idea that unblocks others is raised, with no part of its own for it.
- Confidence, 50% to 100%: how sure we are that it matters.
- Frequency, 1 to 4 (4 daily, 3 weekly, 2 now and then, 1 once), raised by demand: how often the idea came back, counted from the ideas merged into it, the other sources it is known from, the chats it is linked to, and a nightly run proposing it again (`proposed_again` in its history).
- Pain: ×2 broken today, ×1.5 annoying, ×1 nice to have.
- Stars, 1 to 3, ×1, ×1.5 or ×2: Rouh suggests them (`stars_suggested`), the person's own (`stars_mine`) win.
- Clarity, ×0.9 to ×1, and Risk, ÷1 to ÷1.5, both light weights. There is no part for effort.

Rouh's model, on the Models page's "Scoring the Incubator's ideas" (`incubator_score`, Smart to start with), writes every part with a one-line reason and the suggested stars, in batches of eight, four at a time, from each idea's own words (the first 5,000 characters), category, status, sources, links and how often it came back, with every idea's number and title beside them so it can see what an idea unblocks or repeats.
An idea added by any road is scored a few seconds later in the background, and Mutations' beat scores any idea still without one.
A part or stars set by hand are kept beside Rouh's value, which a re-score refreshes without touching them.
Each idea's parts are kept in `score_parts` (migration 0230); the score is never stored.

On the page the Score column, coloured from cool to warm by where a score stands among the rest, is the first sort, highest first, and an idea without a score goes last whichever way the list is turned.
In it are three stars: Rouh's suggestion as outlines, the person's own filled.
One press on a star sets the person's stars, a press on the one they already have goes back to Rouh's, saved at once with nothing asked, the score changing on the screen before the server answers.
The row under the pointer is the selected row: 1, 2 and 3 set its stars, 0 clears them, the arrows and j and k move (and move the open panel with them), Enter opens it, and R puts the list in order, which a change never does by itself, so a row never moves from under the pointer; "Order changed · R to re-sort" says when the order is stale.
None of the keys work while something is typed in a field or the chat, and a small legend of them can be closed and stays closed.
Hovering a score takes it apart: each part, its value, whose it is and why, and the formula with its numbers.
Each part has a column of its own, hidden to start with and shown from Columns, where it can be changed in place; Sort by sorts by the score or any part whether or not its column is shown; the side panel has every part with its menu, whose it is (yours, or Rouh's with what Rouh said) and its reason, the formula, how often the idea came back, and Score again.
"How scores work" beside Sort by says all of this on the page.
Every change of stars or of a part is in the idea's history (`stars`, `part`, `scored`).
Settings kept before scores were read once as version 2: the Score column put in after the number and the list sorted by score.
On a phone the stars are pressed the same way, larger, and the legend is not shown.

The nightly run's brief lists its pickable ideas highest score first (`nightly_ideas.pickable`), so the stars reach what a night builds.

**Summaries** (`rouh/incubator_gist.py`, 7 November 2026).
Petar: "titles are not very meaningful, because they are short, so I need extra information to quickly ramp me up to speed and different levels of depth".
Rouh's model, on the Models page's "Summing up the Incubator's ideas" (`incubator_gist`, Smart to start with), writes for each idea, once, in batches of eight, four at a time, from its own words (the first 3,500 characters), its kind, category, status, sources and notes, with every idea's number, title and line beside them: `line` (one sentence, what it is and why it matters, never the title again), `problem`, `helps`, `in_use`, `vision`, `size` (small, medium or large, with `size_why`) and `alike` (the ideas that are the same idea).
They are kept on the idea (`gist`, migration 0243) with a fingerprint of the title and words they were written from, so a changed title is summed up again; nothing is written on a view.
An idea is summed up a few seconds after it is added, with its score, and Mutations' beat sums up a few batches of the rest, those still to decide first; the page says how many are missing, with "Sum them up now".
Size is shown beside the score and is never part of it.
Lookalikes are the ideas the model named joined with the ideas whose words are close (TF-IDF, a measure of shared rare words, over title, line, problem and the start of the text, standard library only, above 0.24), leaving out ideas merged, pairs linked, and pairs the person said are not the same.

**Its own chat.** Each person has one chat for the Incubator, `incubator-<user id>`, opened beside the list with Chat about the list, and one for each idea, `incubator-<user id>--inc-<n>`, opened with Chat about this idea on its page.
**Replaced (7 November 2026, by the line above):** Each person has one chat for the Incubator, `incubator-<user id>`, opened beside the list with Chat about it, or about one idea with Ask about it.
In it the model is told that it is the Incubator's chat and what the list holds (`incubator.prompt_block`, put in by `brain.py`).
A change made by a tool in any chat redraws an open Incubator page (`incubator_changed`, `PROTOCOL.md`).

**The tools**, in the tool registry under Server and self, and found by searching for "incubator": `incubator_list`, `incubator_read`, `incubator_add`, `incubator_edit`, `incubator_status`, `incubator_merge`, `incubator_link` and `incubator_score` (explain a score, set a part or the stars, score again; `incubator_list` sorts by the score or a part).
Go is set by a tool only in a turn the person started.
Jobs and runs use `bin/rouh-incubator` (`list` with `--sort score` or a part, `read`, `add`, `edit`, `status`, `merge`, `link`, `import`, `score`, `set`, `stars`, `rescore` one or `--all`, and `scoring`), which reaches Rouh as `rouh-task` does, at `/internal/incubator`.

**One way of building.** Setting an idea to Go hands it to Gene therapy as a feedback in its own words, and the converter every feedback goes through (`rouh/triage.py`) reads it into a feature request and starts its run when the board builds by itself.
The idea keeps the feedback, then the request once it is there, and moves to In build; when the request ships it is Built, and if it is declined it is Parked (`incubator.follow`, on every read and on Mutations' quarter-hour beat).
There is no second pipeline.

**Importing** (`rouh/incubator_import.py`, `rouh-incubator import`): every task and step of a project, each one idea, its words every Markdown and text file of its own (never a step's, which is its own idea), its pages linked and read in place, its other files linked, its chat linked; every `### I-nnn` entry of the nightly run's `ideas.md`; and every `### N-nnn` entry of the Gene Nursery.
A nursery entry that names a nightly idea is merged into it; one whose only source is a single task or step that no other nursery entry shares is merged into that one; the rest stay ideas of their own, linked to where they came from.
Importing again changes nothing; nothing is deleted or moved.
With `--mark`, each imported task and step is renamed with " [in incubator]" at the end, by the same rename a person's own uses.

## Nightly run

Petar, 3 November 2026: the nightly feature run was a row on Clockwork, a reminder of Rouh's own; it is a feature of its own, beside the Incubator.
Its page (`nightlyrunpage.js`, `rouh/web/nightly_run.py`) has its switch and its time, its next night and what the last one said, Start a night now, its rules (100 dollars and two sign-ups a night, sign-ups and payments only in a night's first 20 hours), links to Parameters, its ideas in the Incubator and its task, the lessons of its task's `feedback.md`, and every night with what it built and the answer it got.
Its schedule is still kept in the same scheduled row (`nightly_feature.ensure`), so its time, pauses and history carry over and the scheduler that has started every night starts every night still; that row is shown on its page and no longer listed on Clockwork (`rouh/web/clock.py`).
**Replaced (4 November 2026, by the lines below):** its ideas are the Incubator's: its brief tells the night to pick with `rouh-incubator list` and `read`, to add what its research finds with `--source nightly`, and to move each idea as it goes (`nightly_feature.brief_for`).
Petar, 4 November 2026: "now can you modify the nightly build to use the incubator to pick ideas, rather than its own list it used to use?"
So since then Rouh does the choosing, not a sentence in the brief (`rouh/nightly_ideas.py`).
A night picks only an idea that is New or Triaged, not tagged technical, never handed to Gene therapy (no feedback or feature request), not already built, and the first of any ideas with the same title; Go, In build, Built, Parked, Rejected and Merged are never picked, and Go is left out because Gene therapy builds it.
Nothing changes a status to make an idea pickable.
The brief lists the ideas that are pickable as the night starts, with the rule, and tells it never to pick from `ideas.md` or `ledger.md`.
The night's tool `nightly_idea` (list, read, pick, add, drop) reaches the Incubator through `/internal/nightly`, as its other tools do, so it works whenever they do: pick refuses an idea the rule leaves out, add is source nightly with a link to the night and refuses a title already there, and drop is Parked or Rejected with why.
`nightly_gene` with `ideas` links each idea to its gene in Mutations and sets it Built.
At every night's start the old list is put in the Incubator once (`adopt_legacy`): every `### I-nnn` entry of `ideas.md` not there yet, and every idea a night wrote only into `ledger.md` (I-180 to I-183, from night 33, which could not reach the Incubator), its line kept as written and set Built with a link to its gene when the gene it was picked as is in Mutations; neither file is written.
The page's rules say the rule and how many ideas can be picked now.

## Trials

Petar, 4 November 2026: "Rouh is bad at human usability. What it builds tends to be complicated and confusing, and its explanations are hard to read."
So a change a person sees is tried by a made-up person before it ships, and that is a stage of gene therapy of its own, right after the Playwright proof: Playwright checks that it works, the trial checks that a person can use it, the two reports are kept apart, and a gene passes both.
The code is `rouh/trials/`, its tables migrations `0238_trials` (`trials`, `trial_steps`, `trial_problems`, `trial_sightings`) and `0239_trial_jobs_testers` (`trial_testers`, `trial_jobs`, `trial_notes`, and a job, a verdict and what should have happened on the rows before), its page `trialspage.js` (`rouh/web/trials.py`), and the browser driver `bin/rouh-trial`.

**Redesigned the same day.** Petar on the first version: "Terrible first version of trials." What he asked for: "1. I need to be able to see and manage the people testing the software. I want to be able to add more people and remove them. I want to see their full profile and everything written on them. 2. I want a list of jobs. Each job will have multiple tries and has to say who did it, but only when I click on the job. Then I see the trials for that job specifically, and for each try, I want to see the different problems and discuss them." With the best of the two earlier tests he liked, Mira Koleva's ten use cases (step 30-43) and Teodora Angelova's bug hunt (30-44): a tester who reads like a real person, each try told step by step with its screenshot and the tester's own words, problems worst first with what should have happened, what did and how to fix it, a filter by how bad, screenshots that open full size, ticking and copying, Send as feedback and Edit before sending, and a page on how it works with its words.

**The tester** is the model on the Smart tier, as the Models page has it for "Trials tester" (`trial_tester`), asked one step at a time through the LLM service.
Its whole context is its persona, a short brief ("You've had Rouh, a personal assistant on your phone and computer, for two weeks. A friend set it up for you. You talk or type to it and it does things for you."), the goal of the trial in one sentence as the person would put it, and how to test: think out loud as this person, say what you see and think at every step, say when you are unsure and never guess what a word means, behave like this person (`trials.GUIDANCE`).
It knows nothing of Rouh's code, plans, commits, chats or words.
It sees only what a person sees: `rouh-trial` drives a headless Chromium at an iPhone's size (390 by 844), and at each step sends the screen as a picture, the words on the screen, and a yellow number beside each thing that can be pressed or typed in with the words drawn on it, never a hidden label; the tester answers in JSON what it sees, thinks and does, and `rouh-trial` taps, types, scrolls or goes back.
On a screen new to it, it answers What is this? What do I do here? What happens when I do it?, and one it cannot answer clearly is a problem.

**Testers** (called personas until the redesign) are the person's own rows (`trial_testers`): name, age, job, city, one line, phone or computer, her, him or them, and the whole profile in Markdown, written to them in the second person with a heading a part (life, work and day, family, money, devices and apps, skills, temperament, reading, what annoys them, what they want from an assistant, quirks; `trials.SECTIONS`), which is exactly what the tester is told.
Vesela Dimitrova (41, head of HR at a logistics company in Plovdiv, on her iPhone, careful, English her second language) and Boris Stoyanov (29, a car sales manager in Sofia, quick, impatient, skims) are written from `rouh/trials/personas/<name>.md` the first time a person's Trials are read (`trials.ensure_testers`), and are rows like any other from then on.
The Testers page lists them with a face (their initials on a colour of their own), age, job, city, their line, which one tries every change, and their tries and problems found; a tester's page has the whole profile in sections (said of them: "Vesela's work") and their tries. Add a tester is a form, or one sentence from which Rouh writes the whole profile (`trial_writer`, Smart) to read and change before saving. Any tester can be changed; removing one archives them (asked first), so their tries still say who did them, and the one who tries every change cannot be removed until another is made that. Who tries every change is one setting (`trials_persona`).

**Two modes** (Petar, 4 November 2026, the same evening; `Trial.mode`, migration `0240_trial_mode`).
An **automatic test while building** (`auto`, `rouh-trial run`, the gene therapy stage) is the default: the builder fixes what tripped the tester, within what the feature was already asked and approved to be, and tries again, at most two rounds of fixes, and then it ships; nobody is asked, and no problem waits on a choice.
A **review you asked for** (`review`) is only when the owner asks in their own words for someone to test something ("Have Vesela test this"): the `trials` tool's `run`, Ask for a review on a job's or a try's page, `rouh-trial queue` or `run --review`. Naming a tester alone never makes one. It is a report, like Mira's ten suggestions: the whole walk-through, what was found and the suggested fixes, and nothing is fixed or shipped from it until the owner goes through the problems and chooses (Fix it like this, Not a problem, Won't fix, right on each problem of the review's page). Its problems not decided yet are marked Waiting for your choice, everywhere they appear and to every builder (`awaiting_choice`, "leave it alone"); Fix the ones I chose (`trials.fix_chosen`, `POST /api/trials/<n>/fix`, the tool's `fix_chosen` on the owner's words) starts one run that fixes those, their way, and nothing else. A review has no rounds and never posts "Shipped anyway".

**Jobs.** Every try belongs to a job (`trial_jobs`), what is being tested, such as "Sign up and sign in to Rouh for the first time": its name, the goal in the tester's words, what it covers, where it starts and its gene. `rouh-trial run --job "..."` names it; a later round goes into its first round's job; with no name it is the job called the same as the subject, or with the same goal, or a new one. The tries kept before the redesign were put into jobs by their subject. The Jobs page lists jobs only: name, what it covers, the latest result, the number of tries, the problems not fixed and when it was last tried, never who tried; that is on a job's page, each try with the tester's face and name, when, its round, passed or not, its time, steps and problems, and Start a new try with any tester.

**A trial** ends with whether the persona managed it (yes, partly, no), its steps, its time and where they nearly gave up, in their words.
It passes when they managed it with no problem that stopped or confused them.
A failed trial is fixed by the builder and tried again by a new tester with `--round 2`, then `--round 3`; after the third the change ships anyway, its problems stay open, and the owner is told in one notice ("Shipped anyway: ...").

**Problems accumulate** on one list: each with what the tester expected and what happened instead (said by the tester with the problem), a suggested fix (written by `trial_matcher` for a new problem), its screen (the address with its numbers taken out, `trials.screen_key`), the persona's words, the screenshot, how bad (blocked, confused, annoyed, minor, said on the page as Stopped them, Confused them, Annoyed them and Small), and the trial and gene it came from.
At a trial's end the Smart model (`trial_matcher`) says which new problem is one already open on the same screen; that one's count goes up and the sighting is kept with it, and when the model cannot be asked, the same screen and the same words are the match.
A problem is closed only by a later trial that passes and visits its screen without tripping on it, never by hand, and it stays on the list as fixed, with when and by which trial; one closed too soon is opened again with `reopen`.
The owner's own confusions go on the same list, as found by the owner: a term they ask the meaning of in a chat, read by the same code that keeps the terms Plain words explains (`plain_words.asked_terms`), and saying something is confusing ("this is confusing", "I don't understand this", "не разбирам"), from `_plain_words_block` in `brain.py`, only in a turn the owner started.

**Where it runs.** Every run of gene therapy starts through the `improve_myself` preset (improve_myself, the nightly feature run, growing a gene, a mutation, the nightly refactor), and `starting.start` adds the stage to its brief (`trials.STAGE`): after the Playwright proof, for a change a person sees, `rouh-trial run --url <the test world's page> --user --password --goal --subject --gene`, from the run's checkout.
The browser runs there, in the run's own test world; each step goes to `/internal/trials`, where the screenshot is kept under the data folder's `trials/`, the tester is asked and the step written down, so every trial is in the owner's database whichever run made it.
By hand, "trial this page with Boris" (the `trials` tool's `run`) or Run this trial again on a try's page queues the trial and starts a run that only stands a test world up and runs it (`trials.run_by_hand`), changing no code.

**A try's page** is Mira's walk-through: the tester's face and name, when, its round, the result, whether they managed it, steps, time and problems; then each step with its picture (opening full size), what they saw, said and did, the three answers, and the problems found there; then how it ended; then its problems worst first, each Teodora's card (the picture, the tester's words, what should have happened, what happened, how to fix it or the owner's decision, and where it stands), a filter by how bad, ticking and copying, and Try it again.

**Discussing a problem** (`trial_notes`). A problem's page has every sighting, linked to its try and step, and a thread: the owner writes and Rouh answers there (`trials.say`, `trial_discuss` on the Smart tier, with the problem, its first screenshot and the whole try in front of it). From it the owner sets a verdict (`trials.set_verdict`): Fix it like this (`decided`, with how, which `rouh-trial problems --status decided` gives the next round's builder, and the stage tells it to follow), Not a problem or Won't fix (set aside: a tester who runs into it again no longer fails a try), or Send as feedback, which hands the report and its screenshot to Gene therapy's drawer (`window.RouhGeneTherapy.fill`) and sends it, or with Edit before sending puts the cursor in the words, and marks it sent once it is. Where a problem stands (not fixed, decided, fixed, set aside) is shown wherever it appears. The Problems page lists every job's problems, not fixed first and the worst first, filtered by where they stand, who found them (a tester, or the owner, marked Found by you) and the job.
**The tools** (Petar, 4 November 2026: "make sure once this is built, the tools for running and managing it are available to you and the agents"), the same actions in both:

- Rouh's `trials` tool, in Server and self, found by tool search and listed in the tools of its prompt: `run` (a page, a URL or a gene, a goal, a job, a tester if not the default; or a job's number to try it again), `jobs` and `job`, `list` and `read` (every step, the three answers, the ending), `problems` and `problem` (by where they stand, tester, job, screen and source; one with its discussion), `record`, `sighting`, `reopen`, `decide` (only on the owner's own words), `personas`, `persona`, `tester_add` (fields, or one sentence it writes the profile from), `tester_edit`, and `tester_remove` and `default` (only on the owner's own words).
- `rouh-trial`, in `bin/`, which every run, worker and job has on its PATH as it has `rouh-task`, reaching `/internal/trials` with the worker's key: `run` (in a test world it stood up; `--job` names what is tested, and `--signed-out --given "..."` starts it signed out with what the tester was given, which is never kept), `queue` (Rouh starts a run that does), `jobs`, `job`, `list`, `read`, `wait`, `problems` (`--status decided` is what the person said to fix, and how), `problem`, `record`, `sighting`, `reopen`, `personas`, `persona`, `tester-add`, `tester-edit`, `tester-remove` and `default`. The instructions every agent starts with say so, after its rules (`trials.FOR_AGENTS`, from `agent_instructions._gene_run_parts`). It finds Playwright in the checkout's `.venv-e2e`, or the worker's own Python.

## Parameters

How many genes a night the nightly run builds, 0 to 20, and how many of each of the four kinds: invisible, shows up by itself, you ask for it, changes how you work. The kinds always add up to the total: moving the total spreads it in the proportions last set, moving a kind moves the total, a kind stops where the total would pass 20, and a typed number that is not whole or not 0 to 20 is refused and changes nothing. One row per person (`evolution_settings`, with its history); no row is the proposal's ten, 4, 3, 2 and 1.

**Genes on the fly**, under the sliders: whether Rouh may offer to draft a gene by itself (GENES.md, "Genes on the fly"); it starts at Only when I ask for one, until the owner decides otherwise. Drafts the owner leaves for the night are in the night's brief.

**0 pauses the building, not the run:** the night still reads his comments, carries out his answers and builds any mutation request still waiting (one he asks for starts its own run at once, "Mutations" below).

**When it takes effect.** The nightly run reads Parameters when it starts, at its time on Clockwork (`nightly_feature.start`, `evolution.nightly_brief`, put into the night's brief with the mutation requests to build). The page says when that is, from the run's row on Clockwork, or that it is paused there. Saving starts nothing and schedules nothing: the one nightly row is the only thing that runs, and a second start while a night is running is refused, as it always was. The night's caps do not grow with the count: 100 dollars and two sign-ups a night in all.

A warning ("mutated from the original") is not a kind and cannot be ordered: the mutation check finds it after a gene is built.

## Mutations

Called the Gene library until 14 October 2026.

Every gene the nightly run built for the person, one row per version (`mutations_genes`), its whole history (`mutations_gene_events`), its mutation requests (`gene_mutations`) and its questions (`gene_questions`). Every row has `org_id` and `user_id`, every query names both, and an id of anybody else's is "not found".

**On by default** (Petar, 18 October 2026: "The gene automatic creation and evaluation should run automatically without my inputs. However I should be able to jump in and look at things and decide and overwrite. On that note. Everything that is produced should be ON by default. So there are genes in trial and genes out of trial. That should be clear division and screens. Also trial should be very clearly success or not. Either by me saying it or by data supporting it.").
A gene `nightly_gene` registers is switched on and starts its trial at once (`evolution.register`); a new version from his own words does the same and takes its parent's place (`_replace_parent`). Nothing about a gene waits on him: Decisions has no line for it. Migration 0189 put every gene that was waiting (built and off, already on, left for later, booked, or waiting on a change) on, on trial.

**New** (`/evolution/mutations/new`, where Mutations opens; Petar, 19 October 2026: "Items I have never seen that I need to decide if I want them for trial or if they should continue trial, and items I have decided I want trial for them. Currently those two mix and I keep reading again and again the same items ... Essentially I want a list that I haven't reviewed yet, different than things in trial").
A gene on trial that the owner has not decided anything about is in New; once they have, it is in the list its answer put it in, and On trial holds only the genes they chose to keep on trial.
Every decision of his keeps when and which on the version (`mutations_genes.reviewed_at`, `reviewed_as`, the kind of its event; `evolution.group_of`): any answer, Reject, Mutate (the gene stays on trial), a change to its trial's settings, and **Keep in trial** (answer `keep_trial`, event `kept_in_trial`), which changes nothing but moves it to On trial.
A row in New carries the answers its page has, with Keep in trial, and an answer there folds its row away in place, the others left where they are; only Reject and Mutate say a line, whether their run started.
A new version built from a mutation is a version he has not seen, so it comes to New.
Migration 0191 counted a version as reviewed when its history had a decision of his (`by` "person"; Try it now's `tried` is not one), at the time and kind of the latest.
A gene the data settles before he looks at it leaves New for Passed or Failed as before.

**The journeys first** (Petar, 7 November 2026: "Next I want you to look and fix the mutations pages. Make the journeys first and then pass it on for redesign and restructuring.").
Mutations was redesigned around eight journeys, in order of how often: what is new for me to look at; decide about a new gene; where does everything stand; is the change I asked for being built; how is this gene doing; change my mind about a gene that ended; find one gene; see what was built when and every gene in Rouh.
So every list view opens with one sentence of what waits for him ("3 new genes wait for your first look. 2 on trial, 1 change of yours being built."), then the five lists as one strip in the order a gene goes through them, New, On trial, Passed, Rejected, Not used, each its count over its name, the one open marked, and one thin bar of their shares under it; the strip is how a list is opened, each at its own address.
Find a gene sits under it, with Month and Gene log as plain links beside it rather than tabs of their own; a find that matches nothing in the list open says so.
**Your changes being built** is on New and On trial whenever a change he asked for is not finished: the gene, his words and how far it has got, opening the gene's Versions, where Start now, Change and Withdraw are. Before, a change on its way was seen only on its gene's page.
A row in New says "Day X of its N-day trial"; its answers come in two weights, the deciding ones first (Keep, or Keep with the mutation and Keep the original, and Keep in trial) and the quieter ones after (Reject…, Restart trial, Mutate…), every one still on the row, and its Keep is outlined rather than filled, so a list has no row louder than another.
The genes nobody asked for are in New still, in a fold closed until pressed with their count on it, so forty of them never push the genes to decide about off the screen.
A gene's page says how it is doing at the top, whichever tab is open: on trial, "On trial · day X of Y · N of M uses · ends ...", with a bar of its days; ended, its one result ("Failed: you rejected it", the reason being in the Rejected box below); and whether a change he asked for has started or is being built. The Trial tab keeps the same with its settings.

**Where a gene stands**, and the list it is in:

| State | Means | Switch | List |
|---|---|---|---|
| `trial` | On trial: day X of Y, uses so far of those needed | on | New until he decides about it, then On trial (`/evolution/mutations/trial`) |
| `kept` | Passed | on | Passed (`/evolution/mutations/passed`) |
| `off` | Failed: he turned it off | off | Rejected (`/evolution/mutations/rejected`) |
| `rejected`, `removing`, `removed` | Failed: he rejected it, with his reason; its code is being or was taken out | off, then gone | Rejected |
| `off_disuse` | Failed: the data failed it, not used in its trial | off | Not used (`/evolution/mutations/unused`) |
| `replaced` | A newer version took its place | (the newer one's) | inside the newer version's row |
| `candidate`, `review_on`, `later`, `mutation`, `booked` | The waiting states of before 18 October 2026; nothing makes them now | | On trial |

Failed was one list until 27 October 2026, when Petar asked whether it held only what he rejected (fr_c1aa7f60359d: "If that the category for the things I reject only, let's call it so. If those are rejected by some other mechanism should be a different category").
It held both, so it is two lists: Rejected, what he rejected or turned off himself, with the mutations beside them as minor rejects, and Not used, what its trial failed by itself (`evolution.UNUSED`, `group_of`).
The old view addresses `review`, `rouh`, `off` and `failed` open the list that holds those genes now.

**Every trial ends with one result**, Passed or Failed, and a reason that says whether he decided it or the data did (`evolution.result_line`, `mutations_genes.trial` with `outcome`, `by` "you" or "data", and `said`):
- "Passed: you kept it" (Keep), "Passed: you turned it on again" (Turn on again on a failed gene);
- "Passed: used N times" (enough uses that count, by the end of the trial);
- "Passed: its moment never came, so it was kept" (no offer, use or run in the trial, and none in the one extension of the same length, shown meanwhile as "Trial extended: its moment did not come"; it has cost him nothing, and what is made is on by default);
- "Passed: Rouh cannot see its use, so it was kept" (a gene with no use signal at all);
- "Failed: you rejected it: <reason>" (Reject), "Failed: you turned it off" (its switch);
- "Failed: not used when its moment came N times" (offers, turned-down offers or uses that do not count, and not enough that do), or "Failed: not used in its N days" for a gene that was there to use every day.
Passed stays on; Failed is switched off, not deleted, and Turn on again or Restart trial brings it back; a rejected gene's code is taken out as well, as below. No result sends a notice or asks anything (N1); a gene's notice is read when its page is opened.

**What a row shows** (fr_ca2be28fa511, 14 October 2026): the gene's name, its kind, the sentence, and on trial "On trial · day X of Y", under Passed or Failed its result, with its switch as an On/Off toggle beside it. The toggle is an answer: on to off is Turn off (Failed), off to on is Turn on again (Passed).

**Answers** (`evolution.answer`), each him deciding over what the trial would, carried out at once and kept with its time: Keep (ends the trial as Passed, on for good; End trial is its old name), Keep with the mutation or Keep the original (a flagged gene; Keep the original becomes a mutation request to take out what the original does not describe, and the gene stays on meanwhile), Turn off, Turn on again (Keep anyway is its old name), Restart trial (on, and a new trial from today with its settings), and Reject (with his reason, and its code taken out, below; `evolution.reject`, as it starts a run). A gene from a night answers that night too (`nightly_feature.decide`), so the next night's brief still hears it.

**Keep takes a reason, if he gives one** (fr_c1aa7f60359d, 27 October 2026: "When I press keep on the gene trial, I can be given input. This way I can add positive signal why I decided to keep it").
Keep, and Keep with the mutation, open a box asking why, which may be left empty, and Keep it carries out the answer; the reason is the `reason` in the `kept` or `kept_mutation` event's data, and the card shows it in a Kept box while the gene stays kept (`evolution.kept_reason`).
Every night's brief lists the genes he kept himself and that are still kept, with his reason or "kept, with no reason given" (`evolution.kept_for_night`, in `nightly_brief`), beside the rejected and the mutated, so what to build next is chosen from all of his feedback; a gene the data passed is not his feedback and is not listed.

**Reject is not Turn off** (fr_509a4e1d7867, 15 October 2026: "Is reject different than turning it off? ... I do actually need Reject option and reason for rejection. Those then should be considered when deciding what to build next").
Turn off only switches a gene that is on; Reject says no to it, asks why in his own words, switches it off and moves it to Rejected, as `rejected`, its card showing Rejected with the reason.
The reason is the `rejected` event's detail and the verdict "Rejected: ...", and every night's brief lists the rejected genes with their reasons (`evolution.rejected_for_night`, in `nightly_brief`) to weigh before choosing what to build; a gene from a night answers that night too, with the reason.
**Reject takes the code out** (fr_5654dc340c44, 15 October 2026: "the 'take code out' option should be deleted. Reject should delete the code"). There is no Take its code out any more, and no `/genes/<id>/remove`: Reject, after keeping the reason, starts the run that takes the code out and deploys, as Take its code out did - the night's Reject and undo for a gene from a night, or a run that reverts the gene's commits (`removal_brief`, which carries his reason) for one a run registered - and cancels the outside services it brought in.
The gene goes from `rejected` to `removing` to `removed`, keeping the verdict "Rejected: ..." throughout (`is_rejected`), so it stays in Rejected and told to the nights, and its card's Rejected box says whether its code is being taken out or was.
A run that cannot start leaves it `rejected` and off with its code in, says so, and Reject (its reason filled in again) tries once more; Turn on again brings a gene still `rejected` back, and it is no longer told to the nights.
Rejecting a newer version leaves the version it came from as it was.
Rejected genes are in Rejected, each row saying its reason.

**A mutation is a minor reject** (fr_c6b2abc655cf, 27 October 2026: "We should also record the mutations, as this is also a learning point and more or less a minor reject for some reason").
Every mutation request he makes with Mutate, but one he withdrew, is a lesson beside the rejections (`evolution.mutated_for_night`): what the gene was (its version's sentence), his words, and once built what it became (the new version's `changed`, else its sentence).
Every night's brief lists them under the rejections, as minor rejects weighed for less: the idea is not ruled out, how it was first built is, so anything like it is built the way it became.
Rejected lists them under the rejected genes, as Mutated, each row labelled "Mutation, a minor reject" and opening the version it became.
Only his own requests count: the night's own mutated version for us, flagged by the mutation check, is not one.

**Decisions** has no line for a gene since 18 October 2026 (`evolution.waiting` is empty, `decision_sources.GeneSource` makes none and closes the ones from before): every gene is on, on trial, and its trial decides by itself. Before that, each gene waiting on him was a line of its own there.

**A gene's own page** (`/evolution/mutations/gene/<id>`, fr_44acd06b1e00, 19 October 2026: "I break it down into different things depending on what I want to know"): no "Mutations" title over it, only the back link, then the name with its version, with its On/Off switch at the right edge of the same line.
Under it the answers (Keep, Reject…, Restart trial, Mutate…), so they are there whichever tab is open, and then four tabs, each with its own address, drawn in place from what was already read:
- **Essence** (`/gene/<id>`): what it does and how you use it - "How you use it:" before the kind and "Where in Rouh:" before the part of Rouh it changes, a red warning box only when the check found a difference, where a rejection stands, its one sentence, its When and How, the outside services it brought in, and **See it in use**: the screenshots in one row that slides sideways, each opening in a full-screen viewer (`viewPictures`) that pinches, pans, zooms and swipes.
- **Trial** (`/gene/<id>/trial`), whose tab says whether the trial runs, a green dot and On or a grey one and Off; the tag beside the name that said On trial, Passed or Failed was taken out the same day at Petar's word, so it is said once: day X of Y and uses so far, its three settings to change in place, and its signs of use.
- **Versions** (`/gene/<id>/versions`), whose tab has a badge of how many versions there are besides the latest and none when there are none: for a gene never mutated it says only No previous versions (and any change he asked for that is on its way); otherwise what changed, the original beside our version with the check's verdict, every version, and every change he asked for.
- **History** (`/gene/<id>/history`): the log of what has happened to it, newest first.
**Questions** are at the bottom of the card under every tab: every topic with its follow-ups, then a new question.
The card's single column never grows wider than the card, so every line, and every long unbroken string, wraps within it.
The parts' older addresses open the tab that holds them now: `/card` and `/questions` Essence (`/questions` scrolled to the questions), `/learning` Trial, `/mutations` Versions and `/decisions` History.
The "Try it out" toggle, with its Try it now button, was taken out on 19 October 2026 at Petar's word (fr_666eae944e93), with the gene's `try_it` field and its `/tried` address; "Tried from its card" events from before stay in each gene's signs of use.

**Replaced (19 October 2026, by the tabs above):** A gene's own page (`/evolution/mutations/gene/<id>`, fr_fa2525969751, 15 October 2026): no "Mutations" title over it, only the back link, then the name with its version, then the switch and where it stands on one line.
Its card says each label in words: "How you use it:" before the kind, and "Where in Rouh:" before the part of Rouh it changes (`place`, "Task pages" for `pages`); "Update of version ..." is not shown, because the name has the version and its story is told below.
"What changed" is a brown toggle, closed until pressed (AGENTS.md, "Brown toggles").
The "Try it out" toggle, with its Try it now button, was taken out on 19 October 2026 at Petar's word (fr_666eae944e93), with the gene's `try_it` field and its `/tried` address; "Tried from its card" events from before stay in each gene's signs of use.
One page, no tabs (fr_2d2b3726ebb0, 15 October 2026): the page's tabs, Card, Mutations, Decisions, Questions and Learning, are gone, and it reads top to bottom.
What it does, then **Learn it: when to use it**, the Learning tab and the card's When as one part, its moment first.
Then the answers, with no line under each: they stand alone, and what each does is on hover.
The Decisions tab's second copy of the answers is gone with it.
**Questions** come right under the answers: every topic with its follow-ups, then a new question.
Then **See it in use**, open from the start (fr_5654dc340c44): the screenshots in one row of even height that slides sideways, each opening on a press in a full-screen viewer (`viewPictures`, a modal `<dialog>` in the top layer, so nothing behind it moves) that pinches, pans, double-taps to zoom, swipes or arrows to the next and closes with an obvious Close or Escape, back to the card exactly as it was.
Then the outside services it brought in.
Last, **The mutation**, one fold closed until pressed, holds everything about the mutation: what changed, the original beside our version with the check's verdict, every version, the mutation requests and its history.
It is a plain fold like the card's other parts, not a brown toggle: nothing in it is at risk of going, it is only kept tidy (fr_5654dc340c44).
All of it is inside the one card, whose single column never grows wider than the card, so every line, and every long unbroken string, wraps within it.
It stays open or closed as the page is drawn again after an answer, and an address naming the old Mutations or Decisions tab opens the page with it open.

**The morning deck was taken out on 19 October 2026** (fr_650809f11685, Petar: "Remove the morning deck button and functionality"), with its button on Mutations, its page `/deck` (now sent on to On trial), `GET /api/evolution/deck`, the invisible bundle's `POST /api/evolution/bundle`, Leave on trial (`seen`), the shelf that paced it (`evolution.release`) and the morning brief's Mutations part that counted it. Every new gene is listed On trial the moment it is built. The `released_at` column and the old `released` and `seen` events are kept as history. **Replaced (19 October 2026, by the line above):** The morning deck (`evolution.deck`): no clock, "Card 3 of 8". Genes left for later on an earlier morning first, then a new version from his own words, then flagged genes, then you ask for it, changes how you work, shows up by itself; invisible genes that the mutation check saw match their original and that touch nobody ride in one bundle kept with one press. Keys Y, N (Reject, which asks why) and L; on a phone, swipe right, left or up. Every card has one kind label, a red warning box only when the check found a difference, Original gene beside Mutated version for us, a line under each answer saying what it does for that gene, Ask a question, and See it in use, folded.

**Replaced (19 October 2026):** The shelf (`evolution.release`): invisible and shows-up genes reach the deck the morning after they are built; at most two you ask for a morning and one that changes how you work a week; the rest wait, built and off.

## Other switches, and the services a gene brought in

**Other switches**, a small section under Passed (under Out of trial until it was split on 19 October 2026): every feature switch no gene has (since 19 October 2026 a switch a gene of the gene log has, from its manifest or the gene map, is turned on that gene's page, so `memory_recall` and `meeting_people` left this list; GENES.md, "Every file belongs to a gene") (`evolution.other_switches`, sent with `GET /api/evolution/mutations` as `switches`): Rouh's own, such as `memory_recall`, `meeting_people` and the gene log's, and any shared gene's, each with its On/Off toggle (`POST /api/evolution/switches`, `evolution.set_switch`).
A gene's own switch is refused there and said to be on its row, so its own answers (Keep, Turn off, Turn on again, Restart trial) stay the only way a gene is switched.
Feature switches are genes, so they are here and nowhere else in the page.

**The services the nightly run signs up for** are its own: its task's `services.md`, which it writes and nothing in Rouh writes, and from which a gene's Card names what that gene brought in.
They are not Anatomy, Money, **Services** (`rouh/services.py`), which is what Rouh and its owner pay for again and again, kept by hand to be tracked and cancelled.
On 14 October 2026 Services was folded into Mutations for a few hours and then put back in Settings with the nightly run's sign-ups; on 15 October Petar parted the two: "Services should have nothing to do with nightly gene creation. Services are things we purchase and we need to track and maybe unsubscribe."

**Which gene a service was for** (`evolution.gene_of_service`, `evolution.with_genes`): its For column naming a gene's switch, key or name; else a night it names that built one gene; else the night that counted the service with `nightly_signup`, when that night built one gene.
A matched service is listed on its gene's Card, under **Outside services it brought in**, and its card says Reject cancels them: for a gene from a night, the night's undo run cancels them from services.md as it always did; for a gene the night registered, `evolution.removal_brief` lists them for the removal run to cancel by their How to cancel.

## The mutation check

`evolution.mutation_check` compares the mutated version for us (what the night's run saw its gene do in the test world: what it read, changed, sent, scheduled and which outside accounts it used) with the original gene (what it is written to do, in the same five lists). Every observed item the original does not describe is a difference, said plainly ("its version for us also changed contact cards"). With nothing observed it says it could not run, never that the two match. It is advice: it changes no permission, cap or approval anywhere in Rouh. Rouh does not yet watch the test install itself; the observation is the night's run's report.

## Mutations

Mutate keeps his own words as a request and starts a run that builds it at once (`evolution.mutate_now`, `start_mutation`).
Petar, 15 October 2026 (fr_680c7262913d), after the page said his request waited on the next night: "I definitely don't want to wait until next night. Mutation should start right away".
The request is `building` from that moment, with its run's id (`gene_mutations.run_id`), so it can no longer be changed or withdrawn and the night leaves it alone; its row in Versions, on the gene's page, says Being built now, with Follow its run.
The run is one run of the one program on the nightly feature run's model ("Nightly feature run" on the Models page), told to build this request alone, as run.md sections 4 and 8 say, with a line in task 94's ledger (`mutation_brief`).
Its tools are `nightly_switch` and `nightly_gene` only (`nightly_feature.ROLES`, role `mutation`): no sign-ups and no payments, which stay the night's, inside the night's caps, and `nightly_gene` takes no request but its own.
It registers the new version with `mutation_of` (`built`): a new row with the same key, one more version, the old one as its parent, on trial with "what changed" in his words, and a notice, exactly as a night's would be. It is `landed` only once its commits are in the code Rouh runs (`git merge-base --is-ancestor`).
A run that cannot start, or ends without registering anything (`settle`), gives the request back as `requested`, Not started, with Start now, Change and Withdraw; the next night still builds whatever is left waiting, as before. A night that ends without building one it took gives it back the same way; one that could not be built is `failed` with why. Withdraw puts the gene back where it was.
A change he asked for that is not built yet is said under the gene's answers and in Versions on its page (`evolution.mutations`, `requests`): Not started yet (with Start now, Change and Withdraw) or Being built now. Once built, the new version is on, on trial, in its place.
The gene being changed is not listed again under a heading of its own: Petar, 17 October 2026 (fr_fe599883251f), of the old "Mutation requested" section, "I don't know what mutation requested is. Is it created? Am I approving it? Is it requested for later?".
Wherever the gene's state is shown, it says how far the change has got (`evolution.state_name`): "Your change has not started", "Your change is being built", or "Version N is built and waits for your review".
Several mutations of different genes may build at once, each landing through `land.sh`, which replays one onto another; a gene has one request at a time.

## Questions

Ask a question on a card is answered there by a model (`gene_questions.ask`, through `llmlog`, under its own pick on the Models page, "Questions about a gene", `gene_question`) from the gene's own record only: its card, both sides of the check, its versions and requests, its history and signs of use, and its night's report page. It is told to say when the record does not say. Follow-ups carry their topic; every turn is kept under Questions on the gene's page.

## Learning

- **Evidence of use** (`evolution.evidence`): the gene's own events (`evolution.used`, which its code calls at the points it declares; offers; Try it now, until 19 October 2026), and what the event log already records (`analytics.event`): its navigation link pressed, its page opened, its tools called. Since 19 October 2026 the only use that counts is one of the events the gene declares under `signals`, reported by its own code (GENES.md, "How a gene says it was used"), each shown in its own words; its runs are shown and only say its moment came, and the event log's presses, openings and tool calls are not read at all. Before, it was the gene's `use` row and a generic "its own code saying you used it". A gene with no use signal says so, and use never decides it.
- **Trials** (`evolution.settle`, every quarter hour in `runtime._evolution_loop`, and before a gene's page is drawn). Every gene is on trial from the moment it is built. A trial has three settings, shown and changed in place on the gene's Trial tab (called Usage until 19 October 2026, then Trial Status the same day) while it runs (`evolution.put_trial`): its length in days, the uses that pass it, and what counts as a use (`evolution.use_items`: the events the gene declares, in their own words, and nothing else; every one ticked when the trial starts); a trial cannot be made shorter than the day it is on, and at least one thing counts. A trial starts from Parameters' New trials, its days and uses (`trial_defaults`, `evolution_settings.trial_days` and `trial_needed`); Parameters' kinds of use to count were taken out on 19 October 2026, when what counts became each gene's own signals. Trial Status says day X of Y and uses so far of those needed, and the result once it ends, as listed above under "Every trial ends with one result". Not liking a gene is never the trial's to decide: it is Reject with his reason, at any time, which the nights weigh as before; a gene the data failed teaches the nights nothing against it. A trial with no settings of its own (one started before 18 October 2026) runs its rhythm's length with every use counting.
- **Offers at the moment**: a kept gene you ask for, with its "when" sentence, is in the instructions of the person's own turns (`brain._gene_offers_block`, never in a note, a heartbeat, a mail turn or an unattended one), and `gene_offer` records each offer inside limits kept in code: three a day, a gene offered twice and not taken is not offered again, "never" is for good.
- **The day-2 and day-7 question** ("When is it for?") was taken out on 18 October 2026, at Petar's word: nothing asks it, in the brief or on a gene's page. Its answers already given stay in each gene's history as `day_question` and `day_answer` events.
- **The month view** (`evolution.month`, `GET /api/evolution/month`, `/evolution/mutations/month`): every gene in your Rouh or answered in the last thirty days, day by day, with its verdict. It was the week view, of seven days at `/week`, until 19 October 2026 (fr_650809f11685: "week should be month"); `/week` is sent on to it.

## Not built

- Rouh watching a test install itself for the mutation check.
- The spoken ninety seconds at 07:30.
- Use signals for the genes from before the library that show up by themselves or work invisibly.
