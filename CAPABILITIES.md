# Capabilities and structured grants

What Rouh may do for somebody other than the owner, said in code rather than in sentences.
Petar approved this design on 21 October 2026 ("okay build that"), after the audit of run 2be7789c (card 1796) found that a grant made from a case was free text written by a model, accepted with one press, and matched to later asks only by a model reading that text again.

## The weakness this replaces

Before this change (adae513 and earlier):

- A new grant was a name, a title, a description and a prompt that the reading model wrote (`new_grant`), created as written by "Give permanently" (`CaseDesk._grant_setup`, `grants.create`).
- "Merge into" added a model's sentence to an existing grant's prompt, widening it for everybody who held it (`grants.append_prompt`).
- Nothing in code matched a later ask to such a grant: the reading model saw every grant's prompt (`grants.Tree.brief`) and picked an id.
- A grant had no subject scope beyond the contact, no resource, no limits and no expiry, and a grant with no tools could be "held" while nothing could do the work.
- A case's start was given the tools of the grants of the asks it started, but nothing checked the actual arguments of a tool call against what was asked and allowed.

## The shape

Three things, each owned by one place.

1. **Object permissions** are unchanged: read, edit or decide on a task, a quest, a goal or a page, one record per person and object, inherited down the tree, the nearest record winning (`rouh/task_access.py`, `page_guests`).
   They stay the only way to say which of the owner's things somebody may open, change or decide for.
2. **Capabilities** are what Rouh can do for a contact, declared by the code that does it: an id, a version, the kind of thing it acts on, the limits it can enforce, its effects, and the tools that carry it out with how each tool's arguments name the resource and the limited values.
   They are declared in the gene manifests (`rouh/genes/manifests/<gene>.json`, `capabilities`), so a gene deployed tomorrow brings its own, and the catalogue is whatever the deployed manifests declare (`rouh/capabilities.py`).
   There is no hand-kept list of all actions, and a model can never create a capability.
3. **Grants** are records that bind one contact to one capability, with an exact scope, typed limits, a lifetime (once, until a date, or standing) and the capability's contract version (`rouh/capability_grants.py`, table `capability_grants`).
   What the contact page already gave - the levels, the inbox reach, Clockwork, Memory, Shared task and Your calendar with its ticked calendars - are standing grants of the capabilities whose `legacy_grant` names them, read where they are kept, exactly as before.

Hard limits are unchanged and are not grants (`grants.HARD_LIMITS`): money, the owner's accounts, sending as the owner, deleting or forwarding their mail, sending or sharing with somebody else, publishing, what cannot be undone, and doubt about who wrote.
A capability whose effects include one is never grantable to a contact, except committing the owner's time, which Your calendar has lifted since 15 October 2026 (`grants.LIFTS`).
This change gives no contact any new financial, sending, publishing, deleting or other reserved authority.

## Who uses it, and the paths

- **A trusted contact** writes an email, a Telegram message or a Slack message.
  Every one of them becomes a case (`rouh/mail_cases.py`), and the same pipeline below applies to all three.
- **The owner** sees what waits in the case page's boxes and on Decisions, gives, narrows, allows once or declines, and takes grants back on the contact's page.
- **Rouh's reading model** (model use `case_read`) turns the contact's untrusted words into proposed actions.
- **Rouh's start** (the carry-out turn, and the work it starts) acts, and every tool call it makes is checked.
- **A developer or a job** adding a gene declares its capabilities in its manifest and locks their contracts.

### 1. Reading: words into proposed actions

The reading is given the catalogue (each capability's id, what it does, the kind of thing it acts on and the limits it takes), the contact's actual permissions (task levels and grants, as deterministic wording) and the hard limits.
For each ask it reports, as data: `capability` (an id from the catalogue), `resource` (the ids it acts on: task numbers, calendar ids), and `values` (what it asks within the limits, such as who a Clockwork item goes to), or `hard_limit` with the sender's own `effect_words` (MAIL.md D34).
It may call `read_capability` to read a capability's full contract, its tools' input schemas and their handlers' own documentation, read only, before it proposes.
It never writes a grant's words, and a report that does (`new_grant`, a grant id that is not code-backed, an unknown capability, a resource of the wrong kind, a value no limit takes) is sent back to it to report again (`mail_cases.clean_asks`).
When nothing in the catalogue can do what was asked, the ask is `unsupported`: it waits, and the owner can only see to it or decline; nothing is granted.

### 2. Judging: code against permissions

`mail_ledger.judge` decides every ask from what is held, with no model, in this order: done already, the owner's own choice, the contact removed, doubt about who wrote, a hard limit, allowed once, switched off, and then `capabilities.authorize`.
`authorize` resolves, deterministically:

- the subject: the authenticated contact of the case, never a name in the message;
- the capability: known in the catalogue, at a version the grant was made for or one proved compatible with it;
- the resource: every id the ask names inside the grant's exact scope (no wildcard, no empty scope for a scoped kind), or, for a task, the contact's level on it through the one permission record with its inheritance;
- the limits: every value the ask names inside the grant's limits, and the uses left for today and in all;
- the lifetime: not expired, not revoked, not suspended, and for a once grant not spent.

The answer is allowed with the grant that covers it and the reason in words, or waiting with the reason and, when a grant could cover it, a proposal.

### 3. Proposals: built by code, worded by code

A proposal is built by code from the ask's own capability, resource and values (`capabilities.propose`): exactly the resources the ask names, the narrowest default of every limit the capability declares, standing, and the contract version of now.
A required limit is never left out, a scope is never wider than the ask, and a capability that is not grantable is never proposed.
Its words are made from those fields alone (`capabilities.wording`): "Let Sam keep notes they give in your memory, marked as theirs, up to 3 a day, from now on, until you take it back."
Its digest is a hash of exactly those fields (`capabilities.digest`).

### 4. Approval: bound to what was shown

The case page and Decisions show the wording, with the effects and the contract version behind (i).
The owner can give it as shown, narrow it (fewer resources, lower limits, a date it ends, or once), allow it once, decline it with a reason, or see to it themselves.
Giving sends the digest of what was shown; the server rebuilds the proposal from the ask as it is now and refuses when the digest differs ("it changed since you saw it").
A narrowed proposal is validated again, worded again and shown again, and only that shown digest can be given.
The model cannot approve, widen, change effects or create a grant: only the owner's press writes one (`capability_grants.approve`).
A decline with a reason is kept with the proposal and shown the next time the same thing is proposed.

### 5. Execution: the actual arguments, checked again

The start is given the tools of the capabilities of the asks it starts, and each authorisation it may act on (`MailTurn.authorized`).
Immediately before any tool runs in a case's turn (`ToolRegistry.call`), `capabilities.check_call` reads the tool's declared binding:

- which capability this call is (some tools are several, by an argument: `shared_task` action create is making a task, action add is changing one);
- the resource the arguments name and the limited values they carry.

It refuses a tool no capability declares (unless the owner approved that tool's hard limit for this ask), a call whose resource is outside the authorised scope, a value outside the limits, and a grant revoked, expired or spent since the turn began.
For a grant row it claims a use first (`capability_grants.claim`): under a row lock, in one transaction, with a key made of the case, the ask, the tool and the arguments.
Two concurrent uses of a once grant get one claim and one refusal; a retry with the same key finds the claim done and does not run the effect again.
Clockwork items made under a grant are checked again each time they run (`clockwork_grants.refusal`), so a grant taken back or ended stops them.

### 6. Versions: grants bound to contract semantics

A capability's contract is its resource kind, authority, effects, tools with their bindings, and limits; its words are not part of it.
`rouh/capabilities.lock.json` keeps every version's contract and its hash.
`python -m rouh.capabilities check` fails when a manifest's contract differs from the locked one at the same version, so a change in what a capability does needs a new version, and `python -m rouh.capabilities lock` writes it.
A grant made at an older version keeps working when the new contract is proved compatible with it: the same kind of resource and authority, no new effect, no new tool, and the same limits no wider.
Otherwise it is suspended, with the reason ("it gained the effect: share pages with them"), and only an ask that needs it puts a new proposal to the owner.
A version the lock does not know, or a newer one than the code, fails closed.
`python -m rouh.capabilities check --tools` also checks every declared tool against the running tool registry: that it exists, that every bound argument is in its input schema, and that its hard-limit effect (`mail_turn.EFFECTS`) is among the capability's effects.

## Migration

- Nothing that existed is deleted: grant definitions, their versions, contact grants, levels, inbox reach, task records and every case's history stay where they were.
- Every existing holding whose meaning is code (the seeded grants, and a grant made to lift a hard limit whose tools are exactly the code's `LIFTS` tools) is read as a standing grant of its capability, with exactly the access it had: the same contacts, the same tasks, the same calendars, the same inbox reach.
- A grant made from free text with no code behind it no longer allows anything; it is kept, and listed on the Grants page as kept for review, with who held it.
- Task permissions (read, edit, decide) are not touched at all.
- `python manage.py capabilities` prints the counts: holdings mapped, free-text grants kept for review, open proposals.
- The owner is asked nothing because of the migration: an ask that needs what changed puts that one proposal to the owner when it comes.
- On the live server on 21 October 2026, read before landing: 9 grant definitions, every one with code behind it (the 8 seeded, and Your calendar, whose tools are exactly the calendar lift's); 4 contact grant rows (Elena's Memory, Clockwork, Shared task and Your calendar on one calendar); 5 contacts with levels, 1 with an inbox reach; 303 task permission records, untouched; no grant made from words alone; no open ask with a proposal in words. So nothing was put to the owner, and nothing is listed for review.

## What was removed

- The free-text `new_grant` in the reading's report, the case page's "Make a new grant" with its name and words, "Merge into" (a widening by text), and making a grant on the Grants page.
- A model reading a grant's prompt to decide whether a later ask is covered.
- `case_actions.ACTIONS` as a fixed list in code: the actions are the catalogue's.

## What is still the model's, and what is not yet code

- **Which capability an ask is.** The reading still decides which capability an ask is and which resource it names: that is translating untrusted words, which is what a model is for. Every one of its answers is validated (an unknown capability, a wildcard, a value no limit takes, a hard limit without the sender's words and a `new_grant` are all sent back) and judged by code, and every call is checked again on its arguments.
- **Inside a background job.** A job started for a contact (`assistant_job`, capability `work.research` or `work.job`) is a whole worker: what it does inside its run is held by its brief and the workspace's rules, not by these checks. Starting it is checked, a grant's per-day limit counts it, and a grant taken back stops the next start, not a job already running.
- **Three tools check their own resource.** `share_granted_page` (a page of a task they may read), the calendar tools (the calendars a grant names, through `MailTurn.calendars`) and `delegate_act` (DELEGATION.md) are bound with `guard: tool`: the capability must be authorised for the turn, and the tool's own code checks which page, calendar or decision; the catalogue does not bind their resource argument itself.
- **What the contact page gives is unconstrained, as before.** A level, the inbox reach and a ticked grant on the contact's page are standing grants of their capabilities with no scope, limits or end, exactly as they were; only a grant given from a case (or allowed once) has those. The inbox and the levels are given on the page only, never as a grant of their own.
- **Counting.** A per-day limit counts the calls a grant of its own covered in the last 24 hours. The same call of the same case - the same tool with the same arguments - is one use, so a contact's two identical requests in one message are done once.
- **Channels.** Email, Telegram and Slack messages all go through the same case pipeline; email and Telegram were driven in a test world, Slack was not.
