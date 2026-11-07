# Whose Rouh it is: the owner, the installation, and a fresh setup

Petar, 20 October 2026: Rouh is to be ready for fresh installations by other people.
His name, his addresses, his company, his people, his clock and his permissions are not to be written into the code, the prompts or the defaults.
They come from the person and the installation the work is for, and a new installation starts with none of them.

This file says who uses that, how each of them gets there, how the code finds out whose Rouh it is, and what a fresh installation does.
It was written before the change it describes, and the last sections were filled in as it landed.

## Who uses it, and their paths

### 1. The existing owner (Petar, on the live server)

He changes nothing and notices nothing.
Every page, every prompt, every scheduled job and every outbound message behaves as it did before this change.

- **Signing in, talking, his mail, his calendar, his heartbeat, his phone.** All the same: what used to be his name in the code is now read from his own account. The account's first name is "Petar", so a prompt that said "Ask Petar" still says "Ask Petar", word for word.
- **You, About You** (Settings, Profile until 4 November 2026). He can see and change what the prompts call him: his name and his pronouns (new, set to "he" by the live migration below). His company is on his own contact card, under Contact card there, since 4 November 2026, carried there once from his organisation's name; until he gives one, the prompts use the organisation's name.
- **Everything about the installation** that used to be a default in the code (its public address, the address its letters are sent from, Rouh's own mailbox, the time zone a new person starts on, the words the transcriber listens for) is set for his machine in a systemd drop-in that the deploy never touches, `/etc/systemd/system/rouh.service.d/installation.conf`.
- **His data stays where it is.** His contacts, memories, thoughts, chats, calendar, decisions and messages are not touched or rewritten, even where they say his name. History is history.

### 2. The new installer

Somebody setting Rouh up on a machine of their own, from this repository.

1. They get the code without anybody's workspace: `tools/distribution/export.sh` makes the tree of the code, because a workspace is somebody's own work and is a repository of its own, never part of the code; `manage.py setup` makes the new installation's own.
2. They give the installation its settings in their own environment file, from `deploy/installation.env.example`: the public address, the address letters come from, Rouh's own mailbox if it has one, the time zone a new person starts on.
3. They run `python manage.py setup`, which makes the database, the organisation (with the name they give), the empty workspace and the first account, the owner, with the name, email, time zone and pronouns they give. It asks for the password and never prints it.
4. They start the service. Nothing is connected: no Google, no Telegram, no Slack, no Apple contacts, no Hue, no Dreame, no Stripe, no cards, no shipping options, no trusted contacts, no grants, no heartbeat duties. Each is connected later, in Settings, by the owner.

### 3. The fresh owner

The person the new installation is for, signing in for the first time.

1. They sign in with the account the installer made.
2. Rouh calls them by their own name, on their own clock, from the first word: the prompts say their name, the time is theirs.
3. You, About You shows their name and pronouns, and their company on their contact card, and they can change them.
4. Anything outbound that needs a connection that is not there says so and stops: "Telegram is not set up", "Rouh has no mailbox of its own here", "No card has been added". Nothing falls back to anybody else's account, address, chat or card.
5. None of Petar's rules, grants, trusted contacts, quests, shipping options, purchasing permissions, agent instructions or principles are there. The general rules Rouh ships with are written for "the owner", in the owner's name.

## How the code knows whose Rouh it is

**The owner is a person's account, never a word in the code.**
`rouh/owner.py` is the one answer, and it reuses the stores Rouh already had rather than adding one beside them:

| What | Where it is kept | Already there? |
|---|---|---|
| Name (what the prompts call them) | `users.first_name`, else the profile's nickname | yes |
| Full name | `users.first_name` and `users.last_name` | yes |
| Pronouns | the profile (`user_settings`, `profile`, `pronouns`) | new field |
| Their email addresses | the account's email and the card picked in Settings (`my_card.own_addresses`) | yes |
| Their clock | `user_settings`, `zone` (`rouh/clock.py`) | yes |
| Their organisation's name | `organisations.name` | yes |
| The installation's address, mail sender, Rouh's own mailbox, starting time zone, transcriber's words | the service's environment (`rouh/config.py`), set per machine | the setting was there; the default was Petar's |

**Who is asking** is answered the way it already was (`rouh/tenancy.py`): the signed-in person on a request, the socket's person in a turn, the person a background job or a case belongs to (`user_id` on its row, passed on as `who`), and only when nothing says, the one account an installation with exactly one account has.
With two accounts and nobody named, there is no owner, and the text says "the owner" rather than anybody's name.
Nothing anywhere falls back to a username, an address or a chat written in the code.

**Text names the owner with a mark, and the mark is filled in where the text leaves Rouh.**
A prompt, a tool's description or a tool's answer that is about the owner says `‹owner›` where it used to say "Petar", and `‹he›`, `‹him›`, `‹his›`, `‹himself›` (and `‹He›`, `‹His›`, `‹Owner›`) where it used to say his pronouns.
`owner.say(text, who)` fills them in, and it is called at every place text leaves Rouh:

- every request made of a model, in `rouh/llmlog.py`, which every request already goes through, so a prompt reaches the model exactly as it was written before, with the owner's name in it;
- every message on the page's socket and every page and JSON answer, as a last safety net;
- every Telegram message and every letter Rouh sends;
- every brief a background worker is started with.

With pronouns not set, a pronoun mark is the name again ("Alex decides", "Alex's phone"), because the prompts' verbs were written for one person and "they decides" is not English.

**Values that are words of the protocol** and used to be `petar` (who does a goal's step, whom a reminder goes to, what a contact may never do in the owner's name) are `owner` now, and the old word is still read wherever a row or a model might still say it.

## The live migration

`python manage.py owner_profile` is how the live owner's private values reach the private places, and it is run on the server, never committed with values in it.

- It is given the values in a file outside the repository (`--from /var/www/rouh/private/owner.json`) and writes only what differs: the profile's pronouns, the organisation's name, the time zone.
- It backs up what it changes first, in the data folder's `backups/` (`--backups` says another), and `--undo <backup>` puts every value back.
- Run twice, it changes nothing the second time and says so.

The installation's values went into the drop-in described above, with the values the code used to default to, so the live machine reads exactly what it read before.

## A fresh installation, step by step

1. **Get the code without anybody's workspace.**
   `tools/distribution/export.sh /path/to/rouh` writes the tree of a commit with `workspace/` left out except its two tools.
2. **Install what Rouh runs on**, as the README's "Running it" says: Python with uv, PostgreSQL with the `vector`, `pg_trgm` and `pg_search` extensions, nginx in front.
3. **Give the installation its own settings** in its environment file, from `deploy/installation.env.example`.
   The ones that matter on day one are `ROUH_PUBLIC_URL` (the address it is opened at), `ROUH_PUBLIC_HOSTS`, `ROUH_DEFAULT_ZONE`, and `ROUH_MAIL_FROM` and `ROUH_OWN_MAILBOXES` once it has mail of its own.
   `ROUH_BIRTH_URL` and `ROUH_BIRTH_KEY_FILE` (a file with a public key in PEM) are set only by a test world or an installation with a birth service of its own; unset, a Rouh is born with rouh.land's (`rouh/birth.py`).
   Keys (Anthropic, OpenAI, ElevenLabs) go in the same file and nowhere else; the Telegram bot and Brevo keys go in their own files under `/var/www/rouh/.secrets/`, readable only by the service's user.
4. **Run the setup**, which migrates the database and makes the owner, the organisation and an empty workspace:

   ```bash
   python manage.py setup --username alex --email alex@example.com --first-name Alex --last-name Morgan \
       --pronouns "" --org-name "Example Co" --zone Europe/Lisbon --workspace /srv/rouh-workspace
   ```

   It asks for the password twice and never prints it.
   It says which installation settings are still blank and that nothing is connected.
   Run again, it changes nothing; run with another username once there is an owner, it refuses.
5. **Point Rouh at the workspace** with `ROUH_ASSISTANT_REPO=/srv/rouh-workspace`, and start the service.
6. **The owner signs in** and connects, in Settings, only what they want: Google, their own mailboxes, Telegram, Slack, Apple contacts, Hue, Dreame, Stripe, cards, shipping addresses, Cloudflare.
   Until they do, everything that would need one says it is not set up and does nothing.
7. **The owner signs the agents in, with no terminal.**
   In the containers Rouh's runs are Claude Code and Codex in the worker, each on the owner's own plan: Claude Code at `/setup/claude`, and Codex with a ChatGPT plan at `/setup/codex`, both also under Settings, Models, Agents' sign-ins.
   Codex's is one press: the page shows OpenAI's address and a one-time code, large and as a QR code, sends them to Telegram as well if the page is left unseen, and changes by itself once the code is approved, then proves it with one small Codex run (`one/codex_signin.py`).
   Somebody with no ChatGPT plan can choose there to bill Codex runs to an OpenAI API key instead, per use; it is off until they turn it on.
   Both sign-ins live on the worker's home volume, so they outlive a rebuilt or redeployed worker.

What a fresh installation has, measured on 20 October 2026 with a second, invented owner (Sam Rivera, she, New York, "Rivera Studio") and no production credentials: one account, one organisation, its two starting silos (Work and Personal), two scheduled jobs that do nothing until their task exists (the Control Room's naming and the nightly refactoring run), and nothing of anybody else's - no contacts, grants, trusted contacts, rules, thoughts, quests, cards, shipping options, agent instructions of anybody's own, Telegram or Slack destinations.

## What changed, and why each choice

- **Marks filled in where text leaves, rather than a name looked up where text is written.**
  A prompt is a constant written once and used for whoever the turn is for, and there were about nine hundred of them.
  Filling them where the request goes out (`rouh/llmlog.py`, which every model request already passes) means one place decides whose name it is, for every prompt, every tool's description and every tool's answer, in a turn, a background job and a nightly run alike, and a prompt on the first owner's installation is the same, word for word, as it was.
  The other places text leaves (the page's socket, every page and JSON answer, Telegram, letters, Slack, workers' briefs, files written to the workspace) fill them in too, so a mark never reaches a person.
- **Pronouns are a choice of three.** He, she, or the name again. "They" is not offered because the prompts' verbs are singular ("they decides").
- **The words of the protocol are "owner".** `waiting_for_owner`, `needs_owner`, `as_owner`, `for_owner`, `notify_owner`, and `owner` where a goal's step or a reminder says who. Migration 0195 rewrote the stored rows; the code still reads the old words, and a worker told `notify_petar` before this change is still answered.
- **The installation's values moved to its environment**, the canonical place every other installation value already was; the owner's values to their account, profile and organisation, which already existed. Nothing new stores a person.
- **Personal data migrations do nothing on a fresh database.** Every one of them had already run on the first installation, where its data stays; on a fresh database they now write nothing (relationships, a signature, a thought, heartbeat rules, contacts' cases).
- **The Synapse benchmark** was built from the first owner's real mail. It is read from the installation's data folder (`SYNAPSE_BENCHMARK_FILE`, else `<data>/synapse/benchmarks/synapse_eval_v1.json`) and is not in the repository any more.
- **Defaults that were one person's preferences are empty**: the morning brief's YouTube channels, the transcriber's words, the second language, the phone country code (`ROUH_PHONE_COUNTRY`), the Bulgarian spelling of the owner's name in letters (`ROUH_OWNER_NAMES_BG`), the calendar zone, the one program's ssh host (`ONE_HOST`).
- **Kept as product limits, not permissions**: the 100 dollar caps a new payment card starts with and the nightly run's card cap. They restrict; nothing is allowed by them.

## What still names the first owner, and why

- **History.** Comments and docstrings that say who asked for what and when ("Petar, 5 October 2026: ..."), about 2,000 lines, are the design record of the code and were kept, as `git log` is.
  Private details in them (family, partner, child, health, addresses, money) were taken out.
- **Old words still read**: `petar` and the `_petar` statuses in the readers that accept rows written before 0195, the column names `mail_alert_seen.from_petar` and `slack_promises.by_petar`, and the migration file names `0037_petars_mail_signatures` and `0060_reprepare_nikolas_guide` (Django knows a migration by its name).
- **The agent instructions' update keys** (`ADDED`/`REVISED` in `rouh/agent_instructions.py`) say which request an update came from; they mark which updates an installation already has, so changing them would hand every update out again.
- **The workspace** is the owner's own work, a git repository of its own beside the code, named by `ROUH_WORKSPACE`; Rouh's code repository holds none, and `python manage.py setup` makes a new installation an empty one.
- **The test worlds** copy that workspace for the `talking` world, so a world's tasks have his task titles. The worlds' own account and every stand-in are invented (Alex Morgan, Example Co).
- **Git history** is unchanged; rewriting it was not asked for.
