# May decide for: a trusted contact's authority over a quest, a goal, a task or a step

Petar, 9 October 2026, by voice, about a trusted contact and the legal side of open-sourcing Rouh (task 98): "You do the research, she asks for more research if needed, she makes the decisions, approves goal steps and modifies plan and quest. If needed plan modification to yourself with extra permissions that can be assigned to trusted contacts, assign to [her]."

Until that day only the owner decided anything: the decisions list, a goal's steps and plan, a quest's brief.
A trusted contact's levels (`rouh/trusted.py`) let them read the owner's tasks and have Rouh work for them, and every decision on the owner's behalf waited for the owner.
This is the one general thing that changes that, for any trusted contact and any piece of work, and nothing in it is special to the contact it was first made for.
The code is `rouh/delegation.py`; the tables are `delegations` and `delegate_acts` (migration 0111).

## One permission record (21 October 2026)

Petar, 21 October 2026: "Combine delegate grants and task/page shares into ONE permission record that every check reads. Do not keep two flags in sync."
A grant is now a record of the one permission (`rouh/task_access.py`, `models.PageGuest`): one person, by email address, one thing, and a level, read < edit < decide, each including the ones below.
Migration 0197 moved every active row of `delegations` into it (raising a share already there to the grant's level), and 0198 dropped the table; a delegate act names the record it was done under by its token (`DelegateAct.grant`).

- **Who may hold what.** Anybody with an email address may hold read or edit, which is sharing as it always was: they sign in with that address, and the link is emailed when it is shared. Only a trusted contact, switched on, may hold decide, and only over a quest, a goal, a task or a step (`sharing.decider_refusal`); a decide record of anybody else counts as edit.
- **Inherited down the tree.** A record on a quest reaches the goals the quest names (its meta quest block, `"goals": [task ids]`, set with the quest tool's `goals` action, or when a goal is made for a quest with `set_goal`'s `quest`), a goal or a task its steps, and any of them its pages. The most specific record wins, so a lower one may narrow what is inherited as well as widen it. A tick on the contact's page is a floor of read, never a record that narrows.
- **One function reads it**: `task_access.Access` (and `for_email`, `level_of_share`, `for_judge`), for the Share panel, which also lists who has access here through a record above; the guest pages and Ask AI on them; `trusted.Grants` for their email and Telegram; the mail gate; the decisions list and the delegate's tools (`Scope`); and their page in Trusted contacts, whose one tree has every task, step, quest and goal with its level.
- **Written in three places, one record.** Give authority on their page, the `delegate` tool and `manage.py delegate` (`grant`, `revoke`), and the Share panel and `share_with_person`, which may also give decide to a trusted contact.
- **Dedupe.** `manage.py delegate --dedupe [--apply]` takes away decide records their contact would have anyway, inherited from above, each only after checking that what they may do stays the same.
- **Never part of any level**: money, deleting, publishing, sending, signing or committing the owner to anybody, and changes to Rouh itself (`NEVER`).
- **Their decisions are theirs.** A decision a delegate decides is kept off the owner's Decisions list, its count and his phone (`decisions.delegated`); it stays at its own address, in what the delegate is emailed and in the record of acts.

What follows was written for the grants table and holds for the record, except where it says the table.

## The grant

**Explicit, by object, and only the owner's press.**
A row of `delegations` names one trusted contact and one thing: a goal (its task's id), a quest (its record's id), a task (its id) or a step (its id), with its number and title as they were.
A step's number is the task it is in, and what it is called by, "98-03", is read from its folder (`delegation.code_of_row`).
It is made in Settings, on the contact's page, by the level beside the row in its one tree (`delegation.set_on`), on the task's Share panel, or by the owner's own words through Rouh's `delegate` tool.

**The owner's own words, wherever they said them.**
The tool takes `his_words`, which must be words the owner said themselves, and checks them in code (`tools.ToolRegistry._delegate`).
In a turn the owner is in, they may be from any message of theirs in that conversation, typed, said or sent from their phone (`memory.his_own_words`), and never from a tool's result, a note of Rouh's software, an attachment or the page an Ask AI question was about.
In something scheduled on Clockwork, they are the owner's words stored with it when they asked for it (`Reminder.asked`, `reminders.asked_of`), which its note quotes; a row with none gives no authority.
Petar, 10 October 2026, after a grant he had asked for in General ("Okay, but also share 19-17 fully with her, and the link to Rouh task") was refused when the Clockwork job made from it ran, and again in a later turn because his newest message was about something else: "Remove that rule. I will be asking you many times in the future to do a chain of actions that only the last one might be sharing and it may be the result of clockwork."
A grant, revoke or undo something scheduled made is written on the act with the owner's words and channel `clockwork`, its line on the contact's page says "Done by Clockwork", and it is said in the scheduled turn's report and on the owner's phone.
Never in a heartbeat beat, and never in a turn about somebody's email.
In Settings what it is over is found with a search, not picked from a list: Petar, 10 October 2026, "The task picker should be a search, not a dropdown, because I have way too many already."
The search (`rouh/workpicker.py`, `GET /api/settings/trusted/work?q=`) finds every task, step, goal and quest by name or by number as it is said ("98", "98-03", "98 03", "9803"), at most 20, leaves archived work out unless asked, and says on screen what a grant on the one picked reaches before Give authority is pressed.
Nothing else writes one, with one exception below (Extending a promise).

**What it covers.**
A goal covers the goal's task and every step under it.
A quest covers its record and its task, and the goal in that task when the quest is a goal too.
A task covers the task and everything under it.
A step covers that step and everything under it, its notes, its pages and its own steps, and nothing else of the task it is in: they decide only the decisions inside it and read only its folder, and `read_granted_tasks` lists it on its own, by its number.
Being granted authority over something is being granted reading it: `trusted.Grants` adds every task a contact may decide for to what they may read, whatever their levels say.

**Read only, with a promise.**
A row may be `read` rather than `decide`: it lets them read the thing and decide nothing.
A row may also carry a promise (`pending`): words the owner approved, such as "The quest and goals Rouh makes for the open-source legal work, once Sam accepts".
That is how a grant is made before the work it is for exists.
In Settings the field is called "Also give authority over work that does not exist yet (optional)", with a line under it saying what to write and an (i) saying it never covers anything outside what it describes and that every extension is written down; Petar could not tell what it was for under its first name.

**Revoked at once.**
Revoking is a press on her page (or the tool), sets the row `revoked` with the time, and every check reads the rows at the moment it acts, so the next action after it is refused.
Switching the contact off (`trusted` false), or taking her address off, stops every grant too: a contact switched off decides nothing.

## Extending a promise

When the work a promise names is made, Rouh extends it with one call, in any turn that is not about somebody's email:

```
delegate {"action": "extend", "contact": "Sam Rivera", "goals": ["101"], "quests": ["102"]}
```

It only extends a contact that holds a promise, only to goals and quests (never a plain task), only to ones made after the promise was, and every extension is written down as Rouh's, shown on her page and in the morning brief, and revocable like any other.
The owner can make the same call for any contact, promise or not, as `"action": "grant"`.

## What a contact with authority may do

Within what is granted, exactly as the owner can:

- **Answer its decisions** (kept off the owner's list since 21 October 2026), on the one decisions list (`rouh/decisions.py`): a goal step's, a task's, and a quest's approvals that run nothing that spends, sends or publishes. Her answer goes the one way every answer goes, with its undo window, and is recorded as hers: `answered_by` is `delegate:<contact id>`, the channel is `email`, and her exact words are kept on the answer and in the history, never a paraphrase.
- **Mark the steps of the goal complete, approve or reject them, and answer what they ask** (`goals.change_step`, `timekeeper.step_status`); rejecting one has Rouh do it again with her words.
- **Change the plan**: add, remove (archived, never deleted), reword, reorder and regroup steps, change who does a step, and set or move the deadline.
- **Change the quest**: its goal, rules, plan and notebook text; pause and resume it; ask for a beat now.
- **Ask for more research**: on a goal, a new step of Rouh's, started at once; on a quest, an event for its next beat, and a beat now.

## What is never hers, even within what is granted

- Money: a quest's budget and spend cap, its ledger, the card vault, Stripe, anything that spends, and any decision whose risk is money.
- Resetting or deleting a quest, deleting a task or a goal.
- Publishing, sharing pages with anybody further, public links, and any decision whose risk is publishing.
- Sending mail or messages to anybody else on the owner's behalf, or anything in the owner's name, and committing the owner or their company to anybody: signing, filing, registering a foundation, applying, paying fees (`trusted.commitments`). Rouh may prepare these; they become decisions for the owner.
- Changing Rouh's code, rules, permissions or anybody's grants, her own included.
- Anything outside the grant: the owner's other tasks, their mail, calendar and private data.

A decision of hers that falls in that list is not refused into nothing: it becomes the owner's, with her recommendation and her words on it, attributed to her (`outcome` `for_owner`).
On a decision that already exists (one whose risk is gated) her recommendation is drawn on its card; anything else is a decision of its own for the owner (source `delegate`), whose yes says it in the work's own chat as the owner's words.

## How she acts: email, for now

She writes to Rouh's address from her own, the way every trusted contact does (`rouh/mail_cases.py`).
When the case's contact holds authority, its turn is offered one more tool, `delegate_act`, which lists her scope and its open decisions and carries out what she decided, and its brief says so.
The tool checks everything again itself, at the moment it acts, whatever the model was told:

- the turn is a case's, the case's contact is the one with the grant, switched on, and the sender is exactly one of her ticked addresses (or her linked Telegram account);
- Gmail confirmed the sender (DMARC alignment of DKIM or SPF, `MailCase.identity_ok`); anything else is a question back to her, never an action;
- the words the action is taken on are hers, found in her message's own text and not in what it quotes;
- the thing is inside a grant of hers, and nothing in the never list.

The same email read twice does the same action once (`delegate_acts` by case, action, thing and words).
An action is the one write a case's reading turn may make, because it is her decision and not Rouh's: it is checked here and not by the case's route.
The reply that confirms it still goes the way every reply goes, checked; a confirmation of something she decided within her grant does not wait for the owner because the email touches a legal question or a commitment that was hers to make (`route_for`, `delegated`).

Rouh's pages: a guest page (`rouh/sharing.py`) is one shared page with its comments and Ask AI, and has no notion of a decision or a step, so the first version is email only.
The goal's page, the quest's page and the decisions she decides are the owner's pages; on them every action of hers is drawn.

## How Rouh works with her

- **The decisions in her scope are hers.** When a decision is taken in that falls inside a contact's grant and nothing in it is gated, the desk emails her its brief from Rouh's own address, once, in a warm and professional tone, with its handle and how to answer, and does not tell the owner's phone (`delegation.brief_delegates`). Since 21 October 2026 it is not on the owner's Decisions list; it stays at its own address, where the owner can still answer it.
- **Rouh writes to her itself about the work.** Petar, 23 October 2026, after a quest's beat queued for his yes an email to the delegate of the timeline she had asked for herself: "she should have been able to make decisions on the stuff she is working on. and also fix it so it doesn't happen again". Sending, in what stays his, means sending to somebody else or in his name; Rouh writing from its own inbox to the person the work was given to, about that work, is working with her. So a beat on a quest may `send_mail` from Rouh's own inbox (inbox "rouh") to every trusted contact, switched on, who decides for or edits that quest, its task or a goal it names (`delegation.people_of_quest`), copying the owner or not, with nobody's yes: delivering what she asked for, asking for her decisions, the reminders the plan allows, replies to her mail. It is decided in code, from the addresses and the inbox alone (`heartbeat._mail_refusal`), and the beat is told who they are ("PEOPLE YOU WORK WITH ON IT"). The quest's own rules on when and how often still hold. `heartbeat_ask` does not queue such a mail, and one queued before this runs once by itself, exactly as queued, marked "needed nobody's yes" and never as the owner's yes (`Heartbeat.settle_by_rule`, approval state `rule`). Mail to anybody else, from the owner's inbox, or a draft, still waits for the owner.
- **Goal step runs and quest beats know.** `goals.brief_for_step` and the quest's beat say who decides for the work, that a decision left for the person goes to her, and that the never list still goes to the owner.
- **Rouh's own prompt says so** (`brain.DECISIONS`): decisions can belong to a delegate, and Rouh does not ask the owner for those.

## Accountability

Every action is a row of `delegate_acts`: who, what, on what, when, her exact words, what Rouh did, and what it would take to undo it.
It is drawn on her page in Settings, on the goal's page and the quest's page ("Decided by Sam Rivera"), and on the decision itself on /decisions.
On her page in Settings it is one tree, since 21 October 2026 (Petar, on a contact's page: "I still see the two separate. I expected one interface"): the workspace by column and project, every task with its steps and every quest with the goals it names, each with one level control, None, Read, Edit or Decide, the same control as the Share panel's (`levelPick`), saved at the press and changing only the rows it moves.
A level that comes from above shows dimmed with what it comes from ("from Quest 128"); a row's own level overrides it, says "Over Decide from Quest 128", and Clear takes it away; None takes a record away, which is what Revoke was; a promise and "Added by Rouh" are notes on the row; columns and projects are ticked to give everything in them to read.
What the levels mean is behind the (i) beside "Tasks, quests and goals".
Under the tree, closed until opened, "What Sam did lately": only what she did and what was held for the owner, each under the work it was in, with Undo.
Tasks ticked one by one before a task had a level of its own (the grey "Can edit" pills) became records of read in migration 0201.
Neither shows anybody's quoted words, his or hers: Petar, 12 October 2026, "I don't need to prove it here that I have allowed it". The words stay in the row.
The morning brief's Report lists what every delegate decided since the last brief.
The owner can undo any of them (Undo on her page): an answer still in its window is taken back; a step, a plan change, a deadline, a quest's text or pause is put back as it was; a decision already carried out is opened again for him where its source can (a goal step reopened), and otherwise said plainly.

## Silos

Since 12 October 2026 (card 1499, then `rouh/silos.py`) every trusted contact, and so every delegate, sees only some of the owner's silos: the ones ticked on their page in Trusted contacts (`trusted_contacts.sees`), or, until the owner ticks theirs, the silos shown to others (Settings, Silos), which is Work to start with.
A set that holds every silo is no limit at all; any other set sees a thing only when it shares a silo with it, and never a thing in no silo.
For them Synapse is filtered in code at the readers check: an item in none of their silos, and one in no silo, special or unlabelled, is never found, by search, by a link, by its id or through synapse_why.
What the owner granted by name (a task, a project, a goal) stays theirs; what they reach beyond it, the jobs Rouh has running and a job started for them, keeps to their silos, and a contact in none of their silos is not looked up for them.
`delegate` lists what each contact sees, and `delegate {"action": "sees", "sees": [silo names]}` changes it, on the owner's own words.

## By hand on the server

`python manage.py delegate` lists every grant and the last things delegates did; `--contact <name> --goal N --quest N --task N [--read] [--promise "..."]` grants, `--extend` keeps a promise, and `--revoke <grant id>` takes one back.
It is for a job the person asked to give, extend or take back authority, which is their own request to write it.

## An example

A trusted contact, Sam Rivera, is given reading of a task and nothing to decide yet, with the promise "The quest and goals Rouh makes for the legal work, once Sam accepts".
The task stays private: a reading grant shares nothing and makes nothing public.
When she accepts and Rouh has made the quest and the goals, one call gives her authority over them:

```
delegate {"action": "extend", "contact": "Sam Rivera", "goals": ["<goal number>"], "quests": ["<quest number>"]}
```

or on the server, `python manage.py delegate --extend --contact "Sam Rivera" --goal <n> --quest <n>`.

## Not in the first version

- Acting from a Rouh page: a delegate decides by email (and by their linked Telegram account, which is checked the same way). Their page shares are pages to read and comment on, not a place to decide.
- A goal's page still says a step's decision is "Your decision" and the goal is "Waiting on you"; the box "Sam decides for this goal" above the map says whose it is.
- The briefs go by email only, once per decision; nothing reminds a delegate of a decision they leave waiting.
