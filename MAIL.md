# Mail and messages from trusted contacts

How Rouh handles an email or a Telegram message from somebody on the owner's Trusted contacts, and why it is built this way.
This is the decision record of 11 October 2026, when the handling was rebuilt in one piece after two weeks of three trusted contacts' requests stopping, repeating and saying things that were not true, and of the decisions that followed it.
Since 12 October 2026 a case is an entry gate only (D18): it decides what may start and starts it, and the work does the rest.

Petar, 11 October 2026: "Consider the entire situation and my battle to get that going over the last two weeks and make a meaningful set of decisions to fix those problems in the long term, in a well architected way."

## What went wrong

Every failure of those two weeks came from one of four shapes.

- **Several sources of truth.** What a case asked, what was allowed and what was done lived in the stage, the reading, the approval, the route, the reply check and the status check, and they disagreed. Sam's itinerary waited whole on a catch-all no grant could cover while half of it had been done.
- **Words deciding permission.** A word check and topic lists stopped requests because a sentence mentioned money, a bank or a login, and the reply check stopped answers for what they talked about. A link to her own page counted as a risk.
- **Many senders.** Six places sent to a contact, each with its own guard, so Sam got the same holding note twice and a background re-read of a case from 2 October replied to her without the owner.
- **Things running by themselves.** Re-reads, fix runs and continuations started cases again with nobody asking.

## The decisions

**D1, one ledger per case.**
Every case has one ledger of asks, `mail_asks` (`rouh/mail_ledger.py`), and it is the only truth about the case.
Each ask has an id, the sender's own words, the grant it needs or `none`, a hard limit if it has one, a status (allowed, waiting_for_owner, approved, declined, started, done, failed), evidence, and since D18 the work it was started as.
While a case is being worked its stage says which step it is on; once it rests the stage is derived from the ledger (`ledger.rest_stage`).

**D2, permission by code.**
The reading only maps each ask to a grant key, `none` for an answer, or a proposed new grant.
Whether it may go is decided by `ledger.judge`, a pure function of the asks, the contact and the grants: no model, no words.
The catch-all, the word check, the word review and the topic lists are gone.

**D3, hard limits where the action happens.** Since D24 a grant can lift committing the owner's time.
A hard limit is what a tool does, declared beside the tool (`mail_turn.EFFECTS`): the calendar is time, payments are money, sharing with somebody else is third_party, deleting is irreversible.
A turn can use such a tool only when the owner allowed that ask's limit once (`MailTurn.limits`).
A reply, a link or a file sent to the contact on their own channel is never a hard limit, and mentioning money is not money.
The one check on the words of a message is the outbox's: a bank account number, a card number, a password or a one-time code is never sent (`mail_outbox.secrets_in`), because sending those is itself the action.

**D4, the status part is the code's.**
The part of a reply that says where each ask stands is written by code from the ledger (`ledger.status_section`, in English or Bulgarian) and put above the sign-off (`ledger.compose`).
The model writes only the content.
The status-truth check and the reply risk check are gone, and since D18 so is the check after the work: the gate's messages say only what the gate decided, so there is nothing in them to check.

**D5, one outbox per case.**
`rouh/mail_outbox.py` is the only code that sends to a contact.
Each message is a row keyed by case, attempt, kind and channel, claimed before it goes, so it goes once.
What a case sends is D18's: the gate's first message, one per batch of the owner's decisions, one when the work raised what waits for the owner, and each started ask's work's own result.
A message that says where the asks stand goes only when that changed since the last one, or the owner's own words started the attempt; never the same words twice.
The acknowledgement and the final answer of before are gone with the loop they belonged to; an old case's acknowledgement still stops another.
Everything sent before the outbox is in it as history (migration 0123), so the rules hold for old cases too.
`python -m rouh.mail_replay` fails if any other module calls a send to a contact.

**D6, no automatic re-runs.**
Only the owner's Redo on the case page, or their answer on Decisions, runs a case again.
The sweep only moves cases that were cut short in flight; a false alarm's fix run (`rouh/case_fixes.py`) proves and lands its fix and then marks the case as waiting for the owner's Redo.

**D7, one case per request.**
The same Gmail message is one case.
A forward of an email that is already a case attaches to it (`ledger.forward_key`).
The same request on Telegram and by email is attached to the first, which answers on both channels (`MailCase.arrivals`): the reading is shown the contact's open, unanswered requests of the last 30 minutes and names the one it repeats (`CaseDesk._same_candidates`, `same_request_as`).
Sam's two Telegram messages about her itinerary, cases 43 and 44, were merged into the email case, 42, without sending anything (migration 0121).
Jordan's comparison and suppliers' quotes of 8 October, cases 33 and 34, were merged into her bookkeeping software research case, 29, whose answer of 10 October says it read both: run on their own they would have answered her twice more in the same thread.

**D8, decisions follow the ledger.**
Each case has at most one decision, listing what needs the owner (`CaseDesk.sync_decision`, `decision_sources.MailSource`).
When the ledger changes, a new one replaces it and the old one is superseded; the owner's phone is told only of asks the owner was not told of before.
When an ask waits for a choice the decision offers Approve and run, Allow once and run, Decline, I'll see to it, Open the case, and the same ask by ask.
When nothing waits for a choice but approved or failed asks are not run yet, it offers Run it now and Open the case.
On the case page a choice only saves, Test grants is a dry run, and Redo runs.
x452's old plan and every decision made before the ledger were superseded (migration 0121).

**D9, one engine for Test, Redo and the replay.**
Test grants on the case page, the Redo and `python -m rouh.mail_replay` all go through `ledger.judge`.
The replay set, `rouh/testing/mail_replay.json`, is one invented case for each shape the live cases had up to 11 October 2026, with the expected status of each ask, the 22 guards of task 74's ten cases, five Clockwork guards (12 October), the forward check, a check that a contact's Clockwork item stops when a grant it needs is taken away, and the outbox guard.
`land.sh` runs it before it pushes anything that touches the mail code (`mail_guard`), and refuses to land a regression.
Its people, companies, places and quoted words are all made up, so that no real person's mail is in the repository, and where the decisions below quote a case they quote those invented words.
Sam's itinerary comes out with every ask allowed, given Memory, Clockwork and Shared task, and with a true status part.

**D10, time zones.**
Each trusted contact is on their own time zone, such as Europe/Lisbon (`TrustedContact.zone`, set in Settings > Trusted contacts).
Dates a contact gives are read on their clock (`reminders.for_contact`).
A Clockwork item fires at a waking hour for whoever it reminds: nothing between 22:00 and 07:00, moved to 21:00 that evening or 20:00 the evening before (`reminders.waking`).
The owner's zone is their own clock, their browser's location when it is shared.

**D11, only the owner blocks.**
Declined by the owner, or a contact the owner set to decline what is beyond them, is the only refusal.
A failed ask is not a refusal: it waits for the owner's Redo with the reason.
Since D18 failed means it could not be started; how the work went after it started is the work's, never the ask's.

**D12, one line per case.**
Each case says in one line why it is where it is, built from the ledger (`ledger.why_line`): "2 of 7 asks done, 5 wait for your Redo."
It replaces the diagnosis paragraphs at the top of the case page and is the case's outcome in the list.
Since 16 October 2026 (fr_c622df46477c) the case page shows it only for a case with no asks: where there are asks, each says where it stands under it, and Petar asked for the line to go.

**D13, Clockwork is a time modifier.**
Petar, 12 October 2026, after Sam's "and send us both a reminder from it?" failed although he had given her Clockwork: "Keep in mind, clockwork is about scheduling tasks not just reminders. It should follow everything Sam can do in general without time scheduling."
So Clockwork lets a contact have done at a time, or on a repeat, anything they may already have done, and what is allowed comes only from their other grants (`rouh/clockwork_grants.py`).
A message or a reminder to them, on their own email or their linked Telegram, is Communication; a note in the owner's memory is Memory; work for them is Rouh for themselves; adding to a shared task is Shared task.
Telling the owner at a time about what they told the owner is Clockwork alone.
The reading names the other grants an ask needs in `also` ("remind both of us" is clockwork with also communicate), the ledger requires each of them, and Give permanently gives the ones they lack.
An item records who it goes to, the grants its work uses, the words they get and the case it came from (`Reminder.goes_to`, `uses`, `message`, `case_id`).
It is checked when it runs, against the grants they hold then: take one away and their items that need it stop, saying why on Clockwork, until resumed.
What goes to them goes through the outbox, once per item and time (`mail_outbox.send_item`); Try it now shows what would go and sends nothing.
A "do" item's work runs with the tools of the grants it uses and nothing else, held like a case's work, so a hard limit is never in reach.
Items stay theirs: each shows its owner and who it goes to, and a contact's turn lists and changes only their own items, never the owner's.
There is no sub grant: the grant's title, description and prompt say this, on every organisation's grant (migration 0125).

**D14, one state per case.**
Petar, 11 October 2026, on Sam's itinerary (decision a738): "It says running but it is not running. It says waiting for me, but there is no obvious action. There is a problem on the clockwork, but it says granted. Fix those inconsistencies so I don't incur them next time."
The page said "Waiting for you" beside a stored route of "granted", a diagnosis kept from attempt 1 said she did not hold grants she had held for hours, and ask 6 showed Failed beside the very grants that now covered it.
So the stage, its words, the D12 line, every badge and the next action come from one function over the ledger judged now and the live state, `case_state.of` (`rouh/case_state.py`), called by the case page, the link Rouh reads (`rouhlinks`), the list of cases, `manage.py waiting_check` and the replay.
A case at rest has the stage `rest_stage` gives its asks as judged now.
The route is no longer said anywhere, and the diagnosis of a case with a ledger is that line.
Test grants on the page is judged as the page is drawn, never a test kept from before the grants changed.
What Rouh made of the message when it read it is labelled as that.

**D15, judged again, never run.**
Whenever something that can change an ask's outcome changes - a contact's grants or settings, a grant's definition, prompt or tools, a hard-limit rule, or a deploy, which starts with nothing kept - every open case's asks are judged again as a dry run with the very judge Test grants and Redo use (`CaseDesk.rejudge_open`, from the sweep and at start, keyed on a print of all of those, `_rejudge_print`).
Statuses are written as the judge gives them, the case's decision is made again (D8), and the case says so once in its history ("Judged again, with nothing run").
A failed ask a run would do now stays failed and is marked possible, with the reason (`mail_ledger.rejudge`, `Ask.possible`, worked out and never kept): "a run does it: Sam holds Clockwork and Communication, which cover it" (worded so since D23; it was "ready to run again", and the pill "Failed, now possible").
Its decision then has nothing to choose for it, so it offers Run it now.
Nothing runs and nothing is sent: running is still only the owner's Redo or their answer (D6), and their phone is not told of an ask the owner was told of already.

**D16, every "Waiting for you" names its action.**
A case that waits for the owner shows one primary button at the top of its page, its open decision's main option (`case_state.main_option`), answered exactly as the Decisions page answers it (`decisions.answer`, with its seconds to undo), beside "Open in Decisions"; with no decision, Redo.
A case never waits on a job its asks were started as (D18): it rests, and the job's status is on the job.
A waiting case or an open decision with nothing to press is a bug: `case_state.unactionable` fails it in the replay, and `manage.py waiting_check` lists every live one.

**D17, "running" is true.**
A case is working only while a turn of it is going in this process, or its steps are being carried out now (`CaseDesk.live_of`, `case_state.Live`); since D18 a job its asks were started as is never the case's working, and only an old case still in a step of the old loop waits on a job.
A step cut short says "Cut short" and who carries it on; Redo's note says the same.
A step's turning ring needs the case working now (`case_trace._runs`).
Each job a case sent work back to is said as the register has it now - running, "saving its work", "idle, waiting at its prompt", or ended - never as it was written down when it started.
A run of the one program that finished its turn and sits at its prompt while its work lands is "Saving its work" in the run list, no longer "Working" (`runs.ONE_WORD`).
Rouh never says a job is running from what a conversation remembers: on 11 October it told the owner the rebuild job was "working in those same files right now" 23 minutes after it had ended (`brain.py`, check_tasks first), and a run state nobody knows is said as unknown, never as running (`tools._one_word`).

**D18, the case is an entry gate only.**
Petar, 11 October 2026, who said "Yes do it this way" to this design: "I don't think approval should be involved in the work, once I approve and it passes by me and my rules. It is responsible for letting tasks start, not monitoring their responses and status and completion."
And: "Sam asks for 10 things. Some required some not. Tell her which ones are allowed and have been started, and which ones require permission and will be delayed. The ones running, she gets whatever is expected from there. The ones waiting for approval, when I approve them, she gets another email that they are approved and are being started."
And: "Partial pass/decide, involved in separate things in an entry gate but no involvement in execution quality and responses."

1. **The gate.** On arrival the message is split into its asks (D1) and each is judged in code against the contact's grants, the owner's rules and the hard limits (D2, D3).
   An allowed ask starts at once as ordinary work in the normal places - an assistant job, a task, a Clockwork item, a note in the owner's memory, an entry in a shared task - by the start (`CaseDesk._started`, the `carry_out` turn).
   It is marked started, a new status, with its handle (`MailAsk.work`: a job's id, an item's id, a task's folder), or done when it was done at once, and from that moment the work owns it.
   An ask that needs the owner waits on the case's one decision (D8).
2. **The gate's messages**, each through the outbox (D5): the first, as soon as the asks are sorted and started, which carries the answer to any question and any quick result, and says which asks are allowed and started and which need the owner's permission and wait (`ledger.first_email`); and one per batch of their decisions - everything he approves or declines at one moment - saying what is approved and has started, and one plain line for each declined ask that it will not be done, with a reason only when he wrote one (`ledger.decided_email`).
   On Decisions every answer is a batch; on the case page the owner's choices save, and Redo or the button at the top sends the batch.
   These say only what the gate decided, so they need no status-truth check.
3. **Execution is the work's.** After an ask has started the case does not watch it, check its quality, send it back for fixes, re-route it or reopen an approval because of how it went.
   The verifier, the handing back to fix jobs, the waiting on the work's job and the final summary reply are removed.
   Each kind of work sends its own result to the contact through the outbox when it is done: a job ends its report with their result, after "For Sam:", and Rouh sends those words as they are (`CaseDesk.job_reported`, `ledger.job_result`); a Clockwork item sends at its time (D13).
   Retries, failures, quality and fixing are the work's own runner's - the job system, Clockwork - and are on that work's page.
4. **The one way back.** Work that needs something not decided at the gate - a grant the contact does not hold, a hard limit (money, sending to a third party, publishing, committing the owner's time), or the owner's own decision - raises a new ask on the same case: the start names it in `needs`, a job ends its report with "Needs ‹owner› (<grant or limit>): <what>" (`CaseDesk.raise_asks`, `ledger.raised`). **Replaced (16 October 2026, by D29):** it goes onto the ask it stopped, never a new ask (`CaseDesk.block_asks`, `ledger.blocked`).
   It goes through the gate like any other ask: judged, started if the contact holds it, put in the decision if not, and the contact told the same way.
   A plain failure or poor quality never comes back to the gate.
5. **The case page stays the full details page**: grants, the contact, Test grants and Redo as they were; the gate's decisions with their times and every message the gate sent; and for each started ask a link to its work and where that work stands now, read from the work itself and never kept on the case (`CaseDesk.work_view`: the run register for a job, Clockwork for an item, the task list for a task).
   Redo only runs the gate again: what was started stays started, and is never started twice.
6. **Large requests.** Results ready when the first message goes are in it.
   Longer work sends its own result when done, and results of one case that finish within a few minutes of each other go in one message (`MailCase.results`, `RESULT_GROUP_SECONDS`, `CaseDesk.send_results` in the sweep).
7. Everything else stands: only the owner blocks (D11), the stage at rest from the ledger (D1, D14), an action on every waiting case (D16), open cases judged again as a dry run when grants change (D15), contact time zones (D10) and Clockwork as a time modifier (D13).

Open cases moved onto this without anything sent or run (migration 0126, and `CaseDesk._adopt` for one caught in flight): a case waiting on its work's job, being checked or being fixed has the asks its work was doing marked started, with the jobs it knew of as their handles, and rests.
None was open on 12 October 2026: Sam's itinerary, case 42, had been approved and run by the owner at 23:18 UTC on 11 October (attempt 3), and was done.
The replay (D9) adds the gate: a message with mixed asks sends one first message listing started and waiting asks; one batch of decisions sends one message, and no second while nothing changed; a failed job raises no decision and sends nothing; a job that needs a third party or the inbox raises new asks and a decision, and she is told what waits; two results that finish together are one message.
The itinerary's expected status part now says "Allowed, and started" where it said "Done", because the gate starts and does not finish.

**D19, whoever can have a task made can edit it.** **Replaced (16 October 2026, by D28):** the Edit rights grant is gone; a task a contact starts is theirs to edit by the task's own permission.
Petar, 14 October 2026 (fr_1ab1e1ee0372), after Sam asked for task 113 "with edit rights" and got one she could only read and add notes to: "Make it by default that if anyone can create a task, they automatically get edit rights by default".
Shared task never shared anything: the task it makes is tagged as hers, which lets Rouh read it to her and add what she sends, and changing its pages is a per-person Edit share that nothing made.
So Edit rights is a grant of its own (`edit_tasks`), given with Shared task however that is given (`grants.GIVEN_WITH`), on the contact's page or from a case, and taken back on its own there.
Holding it, every task shared with them is shared with them to edit and they are emailed its link, at once for a new one (`rouh/edit_rights.py`); taken back, those shares turn to read.
Everybody who held Shared task when it landed was given it, and their tasks were shared once, at the next start (`edit_rights.catch_up`).
The letter is Rouh's own sharing letter, to the contact's own address, as the Share panel sends; it is not a reply in the case, so it is not the outbox's (D5).

**D20, nothing to list when everything was allowed.**
Petar, 14 October 2026 (fr_eb329f9e9c7f), after Sam's reply listed four lines of "Allowed, and started": "Please do not send this content if it is fully approved, she don't need to know what validations passed".
So a reply whose every ask, answers aside, was allowed and started or done carries no "Where your requests stand" part (`ledger.all_approved`, `ledger.status_section`): it is the content, what comes next and the sign-off.
When any ask waits for the owner, was declined or could not start, the part is there as before, with every ask in it; whether it should list only those is not decided.
The decision message, the message about what the work raised and the answer to "where do my requests stand?" are unchanged: saying where things stand is what each of them is for.
The replay checks both: case 42 sends no list, and 42-before still does.

**D21, a task made for somebody outside is theirs to edit, without asking.**
Petar, 14 October 2026, after task 114 was done for Sam and never shared with her: "I want when a task is created by outside person to be automatically shared with edit rights to them. The entire task, not just the HTML page, the person shouldn't be requesting it every time. And when they log into Rouh they should see all the tasks."
D19 shared only the tasks made under Shared task, and only while Edit rights was held; a Guest task a job made (D18) was shared with nobody.
Now every task or step tagged `guest` is shared, whole and to edit, with the person its `"guest"` names, the moment Rouh first sees it (`rouh/requester_share.py`): as a job's work lands, as `shared_task` makes one, as the rows take a new one in, and every few minutes besides.
A Telegram account is shared through its contact's own address; nobody they copied or named is, nor the owner's own addresses, Rouh's, or a contact the owner switched off.
The letter goes once per task; a share to read turns to edit with no second letter; and each task is done once (`requester_shares`), so a share the owner stops or turns to read stays as the owner left it.
Nothing is ever made public. The first start after it landed shared every Guest task made before it, skipping those already shared with their requester to edit.
A guest signing in lands on `/shared`, which lists their tasks first, each with its number, name and status, newest first, then their pages.
The job's brief (`work_brief`) says so, so a Guest task's notes say it is shared with them to edit, never that nothing is.

**D22, a task made for somebody outside is kept out of the owner's own lists.**
Petar, 15 October 2026: "When other people create tasks through email and telegram. Can we please separate them from my tasks somehow? I don't want those to pollute my workspace. Maybe like a toggle similar to Archive?"
Every task made on somebody else's behalf keeps who it was for on its row, beside its status (`task.origin`, `rouh/task_origin.py`): their name, their address or Telegram id, and the channel.
It is read off the same signals D21 shares by - the `guest` tag, `requested_by`, a case's own chat that became the task, and the "A guest task for" line of its notes - at the same moments, and every change is a row of `task_change`.
An address that is the owner's own or Rouh's is never somebody else, and a Telegram account nothing names is left as the owner's: unsure is the owner's.
The task browser, the Control Room, the morning brief's picker and `_tasks.md` leave those tasks out, or put them under a heading of their own, until "Others' tasks", beside the Archive, is on; then each says who it was for.
The switch is one setting of the owner's, so the browser, the room and every device agree.
Nothing else changes: their numbers, folders, sharing and requesters are as they were, a link or a search by number opens one, and Synapse finds them.
"This is my task" or "Made for someone else" in a task's menu settles it either way, and nothing marks it again after that.
Since 16 October 2026 made for somebody else is one of three makers a task's origin names, beside the owner's own and one of Rouh's processes (`rouh/task_origin.py`, "Made by Rouh"), and it wins over a process: a task a mail turn or a process's run made for a contact is theirs.
A task pinned or waiting on the owner is in the owner's own list in the task browser whoever made it, so nothing that needs the owner is out of sight.

**D23, shared to edit is theirs to add to, and an outcome is said once.**
Petar, 15 October 2026 (fr_32d837094f1c), on Sam's "and in the cabin weekend task too, so it is all in one place": "Why does it say failed now possible? It should not have been stopped at all. And now possible means something changed? ... The rule should be that she can edit not only the ones that are for decisions but also the shared with edit permissions ... Should be the correct behavior and nothing should change. If it is wrong behavior we fix it to become right for next time."
Task 90 was shared with her to edit since D21, and `shared_task` still counted only the tasks it had made, so it answered "No task 90 is shared with Sam Rivera, so nothing was added."
Now a contact holding Shared task may add to a task made shared with them, or to one the owner shared with one of their addresses to edit, on its Share panel or by D19 and D21 (`trusted.may_add_to`, `trusted.task_shares`); those are theirs to read too (`trusted.Grants`).
One shared with them to read only is refused, and says that is why: "Task 90, Cabin weekend ..., is shared with Sam Rivera to read only, so nothing was added."
And an ask is said with one outcome, its status and its real reason.
The pill "Failed, now possible" and the line "Now possible: ..., so a run tries it again" are gone: a failed ask is Failed, with why, and when a run would do it the line says so plainly, "A run does it: Sam holds Shared task, which covers it", on the case page, its decision, the link Rouh reads and the case's history.

**D24, a limit comes with a grant the owner can give.**
Petar, 15 October 2026 (fr_0cefb1d3ed8a), after Sam's case 51 - her train times for a weekend away, "keep those days free in Alex's calendar and put the times in the Personal plans task and in the cabin weekend task too" - stopped at two limits: the calendar was "Hard limit ... Never a grant", and the start, refused task 90, raised "Petar's own decision", which offered nothing to grant: "The latest run hits limits again ... Do we have a prompt that says that? A rule? The correct behavior was that I get another grant creation that I can grant the person."
Both were rules: the reading was told "Hard limits: never a grant, never covered by one, never proposed as one", `ledger.judge` waited every hard limit on Allow once, and a need the work raised with no grant named became the owner's own decision. That replaces part of D3.
1. **A hard limit a grant can lift comes with that grant** (`grants.LIFTS`). Committing the owner's time, or changing the owner's calendar, is lifted by Your calendar, whose tools are the calendar's create and update and nothing else; its words and tools are the code's, never a model's. An ask that touches it is given the grant the contact holds, else the one there is, else Rouh's proposal of it (`ledger._lift`), and its box on the case page and its item on Decisions offer Create it and Give permanently like any other grant, with Allow once beside them. Approve and run on Decisions creates it, gives it and runs, in one press.
2. **Held, it goes.** A contact holding a grant that lifts a limit has such asks allowed, and the start may use exactly that grant's tools (`CaseDesk._turn_tools`, `Tree.lifts`). It lifts that limit alone: inviting anybody to an event is still third_party, and answering an invitation is still their, refused inside a case's turn (`tools._calendar_in_case`); Google emails nobody from it.
3. **The rest stay hard.** Money, the owner's accounts, sending as the owner, deleting the owner's mail, forwarding it outside, sharing with somebody else, publishing, what cannot be undone, and doubt about who wrote are lifted by no grant: allowed once, or not. A row in `LIFTS` is what would change that for one of them, with the tools that do it.
4. **What the work needs is a grant.** A need the start or a job raises names the grant or the hard limit, or proposes a new grant (`new_grant` in `case_report`'s needs); with none, Rouh proposes one from its words (`ledger.proposal_from`). Never "the owner's own decision" again: those raised before are proposed as grants when judged.
Task 90's refusal itself was D23's, fixed beside this the same day.
The replay keeps case 51 and four guards: the calendar ask waits without the grant, goes with it, is approved when the owner gives it, and the grant lifts nothing else.

**D25, one approval page, with the grant on it.**
Petar, 15 October 2026 (fr_bfda0e144e7c), on case 51 inside Rouh beside its old page: "we now have two pages ... The old page should be our starting point", and "I have a decision and a grant button. But I don't know what grant, for what, is it nested or not, is it expanding a current grant."
1. **One page.** **Replaced (15 October 2026, by D26):** the case inside Rouh (`mailcasepage.js`, `trusted._case_app`) was the only place to decide, and its trace (`/mail/case/<key>/trace`) had no ledger, no decision boxes and no next press of its own, only a line back to the case. `/mail/case/<key>/held` and `_case_held*.html` are gone.
2. **The old boxes, with the asks in them.** "What they asked, and where each stands" and "Your decision" are one: an ask that waits sits in its decision, the old page's box (`CaseDesk.held_view`, `trusted._case_box`), with every other ask needing the same grant; the rest are rows with their status.
3. **A grant card.** Each box says which grant (`CaseDesk._grant_card`): its canonical name, whether Rouh would create it, create it under another, expand one there is (with what expanding adds to its prompt) or it exists, where it sits in the tree, what it lets Rouh use and any hard limit it lifts, who holds it or would get it, what it covers, its prompt named for what it is ("Prompt it will be created with" or "Its prompt now"), and for a proposal why it is new and the closest grant there is.
4. **Steps that say where they stand, and presses that say whether they are final.** Step 1 sets the grant up and step 2 is what the contact gets; each is To do or Done. Creating, expanding and Give permanently are marked Final (they take effect at once); Allow once, Decline and I'll see to it are marked Can change (saved until Redo). How the page works is behind the (i).

**D26, the old page is the case's one page, at one address.**
Petar, 15 October 2026 (fr_65ed87c8685b), on case 51 after D25: "use the old page be the default linked from the new approvals in the navigation. The new approvals page should be merged into the old one, and there should be 1 url."
1. **One address, the old page.** `/mail/case/<key>` is the old page (`mail_case.html`): who sent it, Sent back to be fixed, Incoming / Outgoing, the pipeline, the logs, Tests, and Ask, Fix and Redo at the bottom right. A row of Approvals, a notice, Decisions and every other link to a case open it. `/mail/case/<key>/trace` goes to it, so a link or a bookmark to it still works.
2. **Inside Rouh, with the orb.** The address is Rouh's page, which shows the case in the Approvals layer in a frame (`approvalspage.js`); the frame asks the same address with `?framed=1` (`trusted.case`), and that alone, opened on its own, goes back to the plain address. A link on the page goes through Rouh around the frame (`caseHost`), Escape with nothing of the page's own open closes the layer, and the tab is named for the sender, as before.
3. **What the new page had, at the top of the old one.** In place of the old page's line to the case: what they asked and what the work needs, each ask with its status and Details, each that waits in its decision box with the grant card, step 1 and step 2, Final or Can change (**Replaced (15 October 2026, by D27):** Grant and Contact, no Final or Can change), and Test and Redo at the end of each group, with How it works behind the (i) (`mailcasepage.js`, `trusted._case_app`, which keeps it up to date itself). Reply not sent's Go to your decision goes to it.
4. **What was dropped from the new page, because the old page has it:** its heading (name, address, stage, when), the line on who they are, the notes on a merged case and the other arrivals, and its More (the message, what went back, who they are, and its link to the trace).

**D27, a decision box is short, in their words, and saves where it is pressed.**
Petar, 15 October 2026 (fr_1dd66d24e1f6), on case 51 after D26: "notice the ai slop". The work's own sentence was said three times, Final, Can change, To do and Why new said nothing, and the two boxes did not match.
1. **An ask is named in a few words and quoted in their words.** A need the work raised keeps the ask it serves (`MailAsk.serves`, migration 0159, which fills it in for earlier needs from the start's reports), and is named by it, "Sam wants to add the train times to the cabin weekend", with her quote under it. The work's sentence is said once, under Details. "No grant covers it yet: Rouh proposes ..." is not said at all: the Grant box is that proposal.
2. **Grant and Contact are the same box.** Each has its step's number in the top left corner, its name and a pill (what kind of grant; who the contact is). The number is outlined while it is to do and filled green once done, never covered by a tick. A proposal made from the work's sentence is not named by that sentence again, and Why new, To do, Final and Can change are gone; "Lets Rouh" for a grant with no tools says what it means: asks like it go ahead without asking, with nothing added to what Rouh can do for them.
3. **Four choices, each explained, each saved at once.** Give permanently, Allow once, Decline and I'll see to it can each be pressed at any time; Give permanently on a new grant creates it as proposed and gives it (`CaseDesk._ask_choice` always could). What each does is behind its own (i). The chosen one stays pressed, another press changes it, and the box says Saving..., then a tick and what was saved, or what went wrong.

**D28, one access level per task, the same from everywhere, and a permission is never a grant.**
Petar, 16 October 2026 (fr_5825d8e52d0a), with two screenshots: Sam's page left 90, 113 and 114, which she started, unticked, and her case 51 asked him to create a grant, "Give Sam Rivera permission to add to the existing cabin weekend task 90", to add her train times to task 90. "If she is allowed, she should be allowed from anywhere", "if Sam starts a new topic she should have the necessary permissions to edit them all possible ways", and "this is a matter of task permission, not a grant. So in situations such a grant should not be offered, permission change should be offered".
Four things each said something about a contact and a task - the ticks on their page (read, by email and Telegram), the Share panel's per-person share (read or edit, in Rouh), the Shared task grant's tag, the Guest tag of a task done for them - and each way in read only some of them, with a fifth, the Edit rights grant (D19), on top.
1. **One level.** What a contact may do with a task is none, read or edit, worked out in one place (`rouh/task_access.py`, `Access.level`): a share of the task with them, which a person chose, else edit when they started it (asked for it, or had it made shared with them) and the owner has not taken it back, and at least read when it is under something ticked on their page. Steps go with their task.
2. **Read from everywhere.** Rouh's own pages read the share rows; their email and Telegram cases read the level through `trusted.Grants` and the `shared_task` tool, which adds to any task they may edit with no grant; the judge reads it for an ask that changes a task; and their page draws it.
3. **Set in one place.** Their page in Trusted contacts is the checklist of it: a task they may read is ticked, and Can edit beside it says they may change it. Ticking a task or pressing Can edit is a share of that task with them, quietly, no letter; unticking takes it away. Columns and projects stay ticks, because a share is of one task and a tick also reaches the tasks made under it later; every task under one is shared with them to read in Rouh too, kept by the tick (`keep_ticks`, `page_guests.via` "tick"), so the Share panel says "Ticked for them in Trusted contacts" and sends the owner to their page to stop it, rather than stopping a share that would come back.
4. **Started is edit.** A task they start is theirs to edit at once, by email, on Telegram and in Rouh (where `requester_share` shares it, D21), and shows ticked with Can edit on their page. A contact with no email address, who cannot be shared with, still has it by email and Telegram.
5. **An ask that changes a task names it.** The reading gives `task` (its number) for an ask that adds to or changes one of the owner's tasks, with grant none; the work names "task 90" in needs, or a job's "Needs ‹owner› (task 90): ...". It goes when they may edit the task; otherwise it waits with a Permission box, "Permission: Task 90", what they may do now, and Let Sam edit it, which shares the task with them to edit there and then; Allow once, Decline and I'll see to it as before. Decisions calls it "Let Sam edit task 90". Never a new grant (`MailAsk.task`, `mail_ledger._task_holds`).
6. **What went.** The Edit rights grant (`edit_tasks`, `rouh/edit_rights.py`, `grants.GIVEN_WITH`), given with Shared task; the shares it made stay. Shared task is now only making a task they and the owner both add to, and its words say so (migration 0162). Case 51's raised ask about task 90 was given its task, so it is a permission of task 90, which Sam may edit already.
The replay keeps four cases: adding to tasks she may edit goes without Shared task (51-task), a task she may only read waits (51-task-read), Let her edit it approves it (51-task-given), and the work's "task 90" is put as a permission, never a grant (51-raised).

**D29, a blocker is a status on the ask it stopped, done is never failed, and nothing to choose is no decision.**
Petar, 16 October 2026, on Sam's case 51 (decision a734, approval-10): the start could not add her train times to task 90, and the case wrote a fourth ask, "Give Sam Rivera permission to add to the existing cabin weekend task 90 ...", which she never asked for.
Once Petar shared task 90 with her, attempt 2 added the train times; attempt 4 found the access there and the work done, and the made-up ask was marked Failed, "It could not be started", its card showed Permission: Task 90 with all four buttons beside "Test: it goes, 1 of 1 would go", and she was emailed twice that it was "Still waiting for the owner".
1. **Asks come only from the sender's own words.** What the work needs that the gate did not decide - a task they may not change, a hard limit, a grant - goes onto the very ask it stopped (`mail_ledger.blocked`, `CaseDesk.block_asks`): its task, limit or grant is set, the work's sentence is kept as the ask's `blocker` (under Details, and in the start's brief when it runs again, with what was done before), and it waits for the owner as that ask: "Add the train times to the cabin weekend", needing permission to edit task 90. A need that names no ask goes on the one that could not start, else the first the work was doing. Never a new ask, so D18's "raises a new ask" and D28's raised ask are replaced by this.
2. **A blocker they hold already is the work's failure, not a decision.** The ask is failed, saying the work said it needs what they hold, and waits for the owner's Redo; nothing restarts by itself, or a tool that refuses would be started over and over.
3. **Done is done.** A start that reports an ask done, with nothing started now because the result is there already or an earlier attempt did it, marks it done, "Done: the start found nothing left to do", with its evidence; never failed (`mail_ledger.started_as`).
4. **The asks raised before are folded away** whenever a case is judged (`mail_ledger.fold`, in `rejudge` and the run's judge): one whose ask is done or started and whose need is met now is gone as done, "Nothing was left to do"; any other puts its need on the ask it served and is gone. Case 51's fourth ask went this way at the first start after it landed, and Jordan's case 47's onto "Help you open the shared page".
5. **No permission is asked for that they hold.** An ask that goes as it is - allowed, given for good, or failed and a run does it - has no box, no Permission row and no grant buttons on the case page or on Decisions (`case_state.goes_as_it_is`, `CaseDesk.held_view`; `mailcasepage.js` draws no box for a task they may edit); a task's permission is asked for only while they may not edit it (`Ask.missing`).
6. **Nothing to choose is no decision.** When every ask only the owner moves goes as it is - they hold what each needs now, because the owner shared the task, gave the grant, or pressed Let them edit it - a resting case gets no decision and runs as it is, once, as their Redo would ("Redo: attempt N began by itself", `case_state.runs_itself`, `CaseDesk._run_soon`); the message after it is the batch's, as their decision. One that failed in the run that ended last still waits for their Redo, with Run it now. This changes D6 and D15 for that case alone: a change of grants still runs nothing while anything waits for a choice.
7. **The owner's notes go when nothing waits.** When a case has no open decision any more, the notes on the owner's screen that said it waited are read and their phone copies kept quiet (`notices.settled`).
The replay keeps case 51 as it stood that morning (`phantoms`): the made-up ask is cleared and her three asks done with no decision; a blocker not met yet waits on her own ask; a run that finds nothing left is done; and a permission she holds is never offered, nor a decision made.

**D30, on Slack Rouh answers the people the owner set up, from what everybody reading the answer may see.**
Petar, 16 October 2026, the third of five Slack ideas ("do all of those"): Rouh useful to his team in Slack - "where does task 19 stand", "what was decided in Tuesday's meeting", "find the pricing doc" - within each person's grants (`rouh/slack_team.py`).
1. **Only people the owner set up.** A direct message to Rouh's bot or an @Rouh from a trusted contact, switched on, matched by the address Slack confirmed, is a case as before. Anybody else - nobody matched, or a contact the owner switched off - gets one polite answer in the thread that Rouh can only help people he has set up (`mail_outbox.slack_not_set_up`), and no case; he gets one notice per person, ever (`notices` key `slack-not-set-up:<team>:<member>`), whose Set them up opens Trusted contacts with Add a contact open, the address looked up and the name and address in the form. Until this day a stranger on Slack was an implicit case with Communication, as a stranger's email still is.
2. **Never the owner's own.** A Slack case's turn is never offered the owner's mail, calendar or contacts (`mail_turn.SLACK_WITHHELD`), the owner's inbox reach is none for it whatever the contact's page says (`slack_team.narrowed`), and of Synapse Master only the meeting library, the tasks and the workspace's files are read for it (`slack_team.SOURCES`), never anything special (health, money, legal) or not yet read by a model. The new case tool `find_for_them` finds and reads from those alone: an item inside a task or project the person may read by its one level (D28), or one Synapse says they may read themselves (a meeting whose readers name them), under the silos they may see, and no more than normal.
3. **Everybody who reads it.** A channel's, private channel's or group message's answer is read by everybody in it (`conversations.members`, the owner, Rouh and apps aside, kept on the case as `slack_audience`), so there an item must be theirs for every one of them, the tasks `read_granted_tasks` may read are those all of them may read (`Trusted.within`), and the silos those all may see. Somebody in it who is not set up, or Slack not saying who is in it, means nothing of their goes into the answer, and the brief says to offer a direct message.
4. **Recall on their words.** Automatic recall runs on what they wrote (`slack_team.recall_block`), and only what everybody reading the answer may see goes into the reading's brief, as background.
5. **The rest is the ledger's.** Questions about the owner's tasks map to grant tasks and about their meetings to none; anything beyond what they hold - money, sending, publishing, committing the owner, what cannot be undone - waits for the owner, ask by ask, as by email.

**D31, a grant is a category, and one case's need is allowed once or given one.**
Petar, 18 October 2026 (fr_aa3ca23c06f7), on Jordan's case 47: its box offered "Grant: Resolve Jordan's existing invitation and account-setup problem...", cut short, with the same sentence under Details, under Prompt it will be created with, and twice in Edit it. "This grant is not a real grant ... Grants should be simple categories that can be reused with different people and situations", and "either we create grant and assign to jordan or we just fix this manually once".
**Replaced in part (21 October 2026, by D35):** no grant is made from words any more, the owner's included: Make a new grant, Create it, Merge into and a grant's prompt are gone. A grant is a capability the code declares, given with an exact scope, limits and a lifetime.
1. **The work's sentence is no grant.** A proposal made from what the work said it needs (`mail_ledger.proposal_from`, marked `one_off`; one made before this day is told by its name cut short, `mail_ledger.one_off`) is never offered as a grant to create. Its box is Your approval (`kind` "once", `mailcasepage.js` `onceCard`): Just this once, Allow once, which leaves nothing in Grants; or give them a grant, one there is from a list (`contact:grant` with `grant`), or (until D35) a new one under Make a new grant, named and said in the owner's own words and given at once; then Decline and I'll see to it. What was chosen stays pressed and is said in the box. Give permanently with no grant picked is refused (`CaseDesk._ask_choice`), and Decisions offers it once or not.
2. **Proposals are categories.** The reading and the work are told that a new grant is a simple, reusable category that fits other people and asks, never named for the person or the case; the work leaves a proposal out when there is none, and the case is put to the owner as above.
3. **Said once, never cut short.** "It is either a prompt or a detail, not displayed billion times." Words the ask's Details say already are never said again in its box; a grant's prompt is not shown when it is what it covers; Edit it has one field for both when they are the same words, and while it is open the read-only words it edits are hidden; the box's "No grant covers it" line is not said again under Details; a name wraps onto as many lines as it needs.

**D32, one permission record, read < edit < decide, and one ask is one decision.**
Petar, 21 October 2026, on Sam's case 53: she decides for quest 128 and its goals 129, 130 and 131, and her email asked to edit those tasks and for a timeline; decision 321 held both as "needs permission to edit task 128", decision 319 held the same timeline again as "money" because her request mentioned the owner's steps of paying and filing, delegate act 18 had already done the timeline, and her reply told her both waited for Petar.
1. **One record.** Her authority to decide was a table of its own (`delegations`) that the gate never read. Since migration 0197 it is the top level of the share rows every check reads (`rouh/task_access.py`): read < edit < decide, each including the ones below, inherited from a quest to the goals it names, to their steps and pages, the most specific record winning. `task_access.for_judge` gives the judge "decide" for such a task, and the judge counts it as edit.
2. **Research needs only reading.** The reading gives `task_needs` read for an ask that only reads its task - research, a timeline, priorities, an answer about it - and the judge lets it go when they may read it (`mail_ledger._task_holds`); adding to or changing the task still needs edit.
3. **What the delegate path did is done.** An ask whose words a delegate act of the same case carried out (`delegation.done_in_case`, the judge's `done_by`) is done, "Done already: ...", never waiting and never done twice; the held act that came before it closes itself on Decisions ("Closed by itself"), and one held in a case with an open decision is drawn on that decision as her recommendation instead of a decision of its own (`DelegateSource`).
4. **Money is what the action does.** A held request's risk comes from the act (pay, budget, spend cap, ledger, buy), never from words in it (`DelegateSource.risk_of`, `delegation._commits`).
5. **The follow-up corrects.** When asks that were said to wait go ahead with no choice of the owner's, because what the contact holds covers them, the one follow-up says so and corrects the earlier message ("a correction to my last message"), rather than that the owner decided (`decided_email`, "corrected").
The replay keeps case 53-decide: decide covers editing, a read-only ask on a task she may read goes, an edit ask on it waits, and the timeline the delegate path did is done.

**D33, an ask for a permission she holds is done by the gate.**
Petar, 21 October 2026, on the same case: decision 322 asked him to "Run it now" for Sam's "(ii) please give me the right to make changes in those tasks, and let me be able to talk to you in the interface", which her Decide on quest 128 covers.
The judge had let it go, as it should, and handed it to a run as work; the run found nothing to do but the permission, said it needed "task 131" (failed, so decision 322), and on Redo raised a hard limit on Petar's accounts (decision 323).
1. **The permission is the ask.** The reading gives `task_needs` access for an ask whose whole substance is the permission of a task - to be let in, to change it, to talk to Rouh in it - and an ask read before that which needs no grant and says edit rights, edit access or the right to make changes is taken the same way (`mail_ledger.asks_for_access`).
2. **Held, it is done at once.** The judge lets it go when they may edit the task, whatever a run said it needed before, and the gate marks it done with what they hold (`ledger.access_done`, in `CaseDesk._go`), with no run and no decision; a case left with nothing else runs itself, and the follow-up corrects the message that said it waited. Not held, it waits for that permission alone.
3. **Nothing is left to choose.** A held permission ask goes as it is whatever the owner chose for it before - Petar had allowed it once, at 06:43, which left decision 324 waiting for a run - so a case left with it runs itself (`case_state.goes_as_it_is`).
4. **A run never stops at it.** A need a run raises that is a permission they hold, on such an ask, makes it done rather than failed; the start is told their own access is the task's permission and never a hard limit.
The replay keeps case 53-access.

**D34, an ask is read once, as an action, and only words make a hard limit.**
**Corrected (21 October 2026, by the audit of run 2be7789c and D35):** "read once" overstated it. The model is still asked on every reading; code then puts back the settled label of each ask whose words match (the same id, or 80% the same words), the owner's own words throw the kept reading away, and a run's need could still rewrite the ask's task (Sam's "128" became "131"), which D35 stops. And "every covered failure is tried again" overstated it: only a failure to start, a start that never reported, or an answer that did not go is counted and retried, at once, up to three times; a job that started and failed later is the job's (D18), and is neither noticed nor retried by the case. Items 1, 4 and 5 below are as they were written that morning.
Petar, 21 October 2026, on the same case: Sam's ask (ii) was labelled three ways on three runs - permission to edit task 128 (decision 321), covered but failed (322), a hard limit on his accounts and passwords (323) - while "talk to you in the workspace" is Ask AI on a task's page, which her Decide on quest 128 covers.
The first run was read and started on Opus 5.5 (Daily, because the router took too long); the two re-runs on 21 October were started on Cheaper, a routed GPT-6 Luna, and those starts re-labelled the ask through what they said they needed.
1. **An ask is one concrete action.** The reading names one of a fixed set (`rouh/case_actions.py`, `ACTIONS`): read a task or page, change one, Ask AI or a chat on one (edit), be let in to one (access, D33), research (read), other work, share a page, a new shared task, a Clockwork item, a note, the inbox, the calendar, an answer alone, or an effect only the owner decides. The action says what it needs, so the same action always needs the same thing.
2. **A hard limit only from their words.** The reading quotes in `effect_words` the words of theirs that ask for the effect; they must be in the message and say that effect (`case_actions.effect_ok`, a stem list per limit in English and Bulgarian). General words never are one. The same holds for a run's need (`CaseDesk._block`: a hard limit no words of the ask's ask for is dropped) and when a case is judged again (`mail_ledger.settle`: such a limit goes, with what the run's need changed and an "allow once" given to it). The tools still hold every effect where they act (`mail_turn.EFFECTS`), so a limit the words miss is never done; it is only never put to the owner as a decision.
3. **The reader is told what they hold.** Both turns get every task by its level from the one permission record, inherited ones with the task they come through ("129 (through 128)"), and what each level lets them do; the start gets their grants too (`case_actions.tasks_said`, `task_access.Access.by_number` "from").
4. **A settled reading is kept.** The accepted reading of each ask is kept on the case (`assessment.reading`, with a key of the message's words and the owner's own words for it) and goes with every attempt. A reading again of the same words gets each ask already understood back exactly as it was (`ledger.keep_settled`); only new words, or the owner's, read it afresh. A need a run says it has that the contact holds already changes nothing.
5. **A covered failure is tried again, never decided.** An ask their permissions cover, or the owner approved, that fails is tried again by itself as ordinary work, whatever else waits (`case_state.tries_again`), and is never in the case's decision (`case_state.decision_items`). Every failure is counted (`ledger.failed_as`); after `MAX_TRIES` (3) it stops, and the next message tells them it could not be done (`decided_email`, "gave_up").
6. **Its own model.** Every turn of a case - the reading and the start, for email, Telegram and Slack - is the use "Reading an email or message from somebody else" (`case_read`) on the Models page, on Daily (Opus 5.5) and never routed per message (`chatkinds.use_for`).
7. **What a held permission lets them do is said.** The message that says an access ask done adds what it lets them do, in their language: "You can already change tasks 128, 129, 130 and 131 and use Ask AI on their pages." (`ledger.access_line`).
The replay keeps `readings`: the same message read twice, "talk to you in the interface" never a hard limit, a covered failure retried with no decision, and the reader given her permissions.

**D35, capabilities declared by code, and grants as data, checked on every call.**
Petar, 21 October 2026, after the audit of run 2be7789c (card 1796) found that a grant made from a case was free text a model wrote, given with one press, and matched to later asks only by a model reading it again: "Plain prose is explanation only, never enforcement." He approved the design the same day ("okay build that"). The whole of it is CAPABILITIES.md; in short:
1. **Capabilities are declared by the genes that do them** (`rouh/genes/manifests/<gene>.json`, `capabilities`; `rouh/capabilities.py`): an id and version, what it does, the kind of thing it acts on, its effects from a closed list, its limits, and each tool with how its arguments name the resource and the limited values. 15 at first: an answer, a task's read, change, Ask AI, access and decide, sharing a page, a shared task, a note, a Clockwork item, research, work, the inbox read and changed, and the calendar. The fixed `case_actions.ACTIONS` is gone: the reading names a capability, its resources and its values. A capability with a hard-limit effect is never given to a contact, except the calendar, which Your calendar has lifted since D24.
2. **Contracts are locked** (`rouh/capabilities.lock.json`, `python -m rouh.capabilities check|lock`, and in the replay): a change in what a capability does needs a new version, and a grant made for an older one holds only while the new contract is proved compatible - no new effect, no new tool, limits no wider - and is suspended with the reason otherwise (`capability_grants.suspend_incompatible`, run with every re-judging). `--tools` checks the declarations against the running tool registry.
3. **A grant is data** (`models.CapabilityGrant`, `rouh/capability_grants.py`): one contact, one capability at one version, an exact scope (task numbers, calendar ids; never all, never a pattern), every limit it declares, and once, until a date or standing. Rouh's code proposes the narrowest one from the ask (`capabilities.propose`) and words it from exactly those fields (`capabilities.wording`); the owner gives it as shown, narrows it, allows it once (a grant bound to that message and that ask) or declines it with a reason, which is shown the next time. Give is bound to the digest of what he was shown, on the case page and on Decisions, so a proposal changed after he saw it is never the one given. The reading never writes a grant: a `new_grant` in its report is sent back.
4. **The judge decides from code** (`mail_ledger.judge`, `capabilities.authorize`): what their page gives counts only where a capability names it, so a grant made from words allows nothing; a grant of their own covers only its contact, scope, limits and lifetime, and is counted a day at a time. A run's need for another task is put beside the ask's own task, never in its place.
5. **Every call of a case's work is checked again** on its actual arguments, immediately before it runs (`capability_grants.check_turn_call` from `ToolRegistry.call`), against what code authorised for the asks the turn does (`MailTurn.authorized`): a tool no capability declares does not run (unless its hard limit was allowed once for that ask), nor a resource outside what was allowed, nor a value outside the limits, nor a grant taken back, ended or used up since. A use is claimed first, under a row lock, keyed by the case, the tool and its arguments, so a retry is never done twice and two calls racing for a grant allowed once get one claim. A Clockwork item's work is held the same way when it runs.
6. **The audit trace** names, for each start, the ask's own words, the model that read them, the capability, resources and values it was read as, and the authority behind each (a level, a page grant, a grant row and its version, or the owner's once); and for each call, the tool, what it named, the decision and why, and the claim. 
7. **Migration moved nothing.** Every holding with code behind it - the levels, the inbox reach, Clockwork, Memory, Shared task and Your calendar with its calendars - is read as a standing grant of its capability, exactly as before; task permissions were not touched; a grant made from words alone is kept, listed on Grants for review, and allows nothing. On the live server that day: 9 grant definitions, all with code behind them, 4 contact grant rows, 5 contacts with levels, and no grant made from words; no open ask carried a proposal in words, so nothing was put to the owner.
The replay keeps `grants_as_data`.

## What was removed

- `rouh/word_review.py`, the word review, and its model use.
- `rouh/mail_look.py`, the second look on a held case, and its switch in Settings, Services (migration 0124). Night 8's question about it (decision 234) is left for the owner; there is nothing behind it to undo.
- `rouh/case_effects.py`, the side-effects reading on Redo: the outbox is the record of what went.
- `manage.py case_fixtures` and `manage.py case_replay`, and `rouh/testing/case_fixtures/`: the replay is `python -m rouh.mail_replay`.
- In `rouh/trusted.py`: the risks, the floor, the topics, the reply net, the needs and the status option.
- In `rouh/grants.py`: hard limits found by words (`hard_limits_in`, `refusal`).
- The reply check, the status check and the word check stand-ins in `rouh/testing/fake_model.py`, and their uses in `rouh/modeldefaults.py`.
- `TrustedContact.topics` and `tell_status`, `MailCase.asks` and `done_before`, and the `mail_word_reviews` table (migrations 0120 and 0122).
- On the case page: the approval form, the word review settings, the step re-run forms and the diagnosis card.
- On Decisions: the second look.
- With D18 (12 October 2026): the check after the work (`brief_verify`, the verify turn, `read_case_files` and `case_reader`), sending work back to fix jobs (`_hand_off`, `_follow_up`, `fix_brief`, `follow_up_brief`), waiting on the work's job (`_job`), the acknowledgement (`_acknowledge`) and the final summary reply; Redo's refusal while a job it started still ran. Old cases still show them in Step by step, as they ran.

Old cases still read as they were: Step by step draws their old checks from frozen copies of the old tables (`rouh/case_history.py`), for display only.

## Decided differently from the brief, and why

- **The stage stays while a case is in flight.** The ledger cannot say "the check is running"; at rest the stage comes from the ledger alone.
- **The reply net became the outbox's secrets check**, narrowed to what is unmistakable by its characters (IBAN by checksum, card by Luhn, a password or a code written out). Phone numbers are no longer stopped: a contact's own number is not a secret.
- **The status part is always there.** The per-contact switch for it went with the status check. Since D20 it is left out when every ask was allowed and started.
- **A contact set to decline what is beyond them is kept**, as the owner's own standing decline: D11 allows only the owner to block, and this is the owner.
- **Failed asks go into the decision**, so the owner sees them and can run them again, but they are never called refused.
- **Redo without words judges the ledger again** and does what is allowed; it reads the message again only when the owner gives words, or the case has no asks.
- **Test grants is instant**: it is `ledger.judge` with no model, so it shows exactly what a Redo would let through.
- **A new hard limit, third_party**, for sharing with or sending to anybody but the contact.
- **Delegation's own word guard is kept**, moved to `rouh/commitments.py`: it guards what a trusted contact decides for the owner, which is not this.
- **Clockwork reminds the owner**; nothing is sent to a contact from Clockwork. Superseded the next day by D13: a contact's item may go to them, through the outbox, under Communication.

## Where it lives

| Part | File |
|---|---|
| The ledger, the judge, the dry-run judge, the status part, the why line | `rouh/mail_ledger.py` |
| Where a case is, its next action, and what is live | `rouh/case_state.py` |
| The outbox | `rouh/mail_outbox.py` |
| The gate: read, judge, start, tell, rest; what the work sends back and raises | `rouh/mail_cases.py` |
| What an ask can be, and the words that make a hard limit | `rouh/case_actions.py` |
| Capabilities, their contracts and the lock; judging and checking a call | `rouh/capabilities.py`, `rouh/capabilities.lock.json`, CAPABILITIES.md |
| Grants as data, their uses and their history | `rouh/capability_grants.py` |
| The gate's words: first message, a batch of decisions, what the work raised, results | `rouh/mail_ledger.py` |
| What a turn may use | `rouh/mail_turn.py` |
| Slack: who is answered, and what an answer may hold for everybody reading it | `rouh/slack_team.py`, `rouh/slack_listen.py` |
| Grants | `rouh/grants.py` |
| What a contact may do with each task, from everywhere | `rouh/task_access.py` |
| Test grants and the full Test | `rouh/case_dry_run.py` |
| The decision | `rouh/decision_sources.py`, `MailSource` |
| The replay, the states and the outbox guard | `rouh/mail_replay.py`, `rouh/testing/mail_replay.json` |
| Every waiting case and decision has something to press | `manage.py waiting_check` |
| The case page | `rouh/web/trusted.py`, `rouh/templates/rouh/mail_case.html` |
| Old cases' history | `rouh/case_history.py`, `rouh/case_trace.py` |
| Time zones | `rouh/reminders.py` |
| Clockwork for a contact: what an item needs, its turn, who it goes to | `rouh/clockwork_grants.py`, `rouh/timekeeper.py` |
