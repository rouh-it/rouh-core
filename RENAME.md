# Jarvis is called Rouh

Petar decided it on 22 September 2026, through the one program, from his voice:
everything called Jarvis, and before that "rou", is called **Rouh**.
Rouh's own mailbox took the new name with it.

The rename is deliberately **not a cutover**.
Both names answer, both systems stay up, and nothing was switched off to make room for the new one.
This file is the record of which is which, so that whoever picks the rest of it up later knows what is deliberate and what is simply not done yet.

## The rule

**What a person reads says Rouh. What a machine reads still says jarvis.**

That line is the whole of the decision.
A string on a screen, in a spoken turn, in a notification, or in a prompt the model is handed, says Rouh.
An identifier, a file path, a service name, an environment variable, a cookie, a database column, a wire message type, a Python module: still `jarvis`, because renaming those is how a deployment breaks, and none of them is read by anybody but this machine.

The case is the seam and it is worth knowing.
Capital `Jarvis` was always the product in prose; lower case `jarvis` was always the thing on disk.
So the rename was a case-sensitive replacement of `Jarvis` with `Rouh`, and everything lower case was left exactly where it was.

## What now says Rouh

### The interface

| Where | Was | Is |
|---|---|---|
| The browser tab, `rouh/static/index.html` | Jarvis | Rouh |
| The sign-in page, `rouh/server.py` | "Sign in to Jarvis", heading "Jarvis" | "Sign in to Rouh", heading "Rouh" |
| The sidebar head | Jarvis | Rouh |
| The home-screen app, `manifest.webmanifest` | Jarvis | Rouh |
| The version chip in the top bar | the letter **J**, read out as "jarvis 0c5cde5" | the letter **R**, read out as "rouh 0c5cde5" |
| The version chip's hover text and panel | "Jarvis is answering from ...", "Deploy Jarvis to catch up." | Rouh |
| The composer | "Type to Jarvis" | "Type to Rouh" |
| Every answer in the transcript | headed **JARVIS** | headed **ROUH** |
| The Stop control's hover text | "It stops Jarvis talking and thinking." | Rouh |
| The voice settings | "when Jarvis thinks you have started talking" | Rouh |
| The orb's machine stats | `jarvis + one` | `rouh + one` |
| The orb's cards | "Jarvis itself", "Jarvis, answering you", "Held by Jarvis + one" | Rouh |
| The update bar | "Jarvis has been updated." | "Rouh has been updated." |
| The deploy card, `rouh/self_update.py` | "Updating Jarvis" | "Updating Rouh" |
| A card with no title of its own, `rouh/artifacts.py` | Jarvis | Rouh |
| A page asked for without a sign-in, `rouh/pages.py` | "Sign in to Jarvis first." | "Sign in to Rouh first." |
| The Google consent messages, `rouh/google_oauth.py`, `google_web.py` | "Jarvis now needs permission to ..." | Rouh |
| Every "not paired", "not connected", "cannot be heard here" notice | Jarvis | Rouh |

### What is said out loud, and what the model is told

* `rouh/brain.py` - the system prompt opens **"You are Rouh, ‹owner›'s personal assistant"** (the owner's name, filled in by `rouh/owner.py`), and a new short section names the assistant: Rouh is what it calls itself, it was called Jarvis until 22 September 2026 and should still understand that name when it is said, and its own email address is Rouh's own mailbox (`ROUH_OWN_MAILBOXES`).
  That one sentence about the old name is the single place in the prompt where "Jarvis" still appears, on purpose.
* `rouh/config.py` - the speech-to-text key terms now carry **both** `Rouh` and `Jarvis`, so a spoken "Jarvis" is still transcribed correctly while the two names are both in use.
* `rouh/subagent.py`, `rouh/crew.py`, `rouh/assistant_job.py`, `one/agents.py` - the briefs handed to a research subagent, a crewmate and a background job say Rouh.
* `rouh/tools.py` - every tool description the model reads, and every sentence a tool hands back to be said out loud.
* `rouh/turnmarks.py` - the note the software inserts into a turn.

### Outward

* `rouh/picture.py` - the User-Agent this server fetches a picture with is `Rouh/1.0`.
* The Telegram bot was already named for Rouh, display name Rouh. Nothing there had to change.

### The documents

`README.md`, `PROTOCOL.md`, `AGENTS.md`, `GOOGLE.md`, `TELEMETRY.md`, `one/README.md` and every docstring and comment in the code call the assistant Rouh.

## The address

On Petar's installation the new name got an address of its own, live since 18 September 2026, and the old name's address was kept answering beside it.
The site file names both in its `server_name`, so both reach the same app, and `/nginx-healthz` answers with the name it was asked under, so which one arrived can be seen.
Nothing was switched off to do it.

The old name's record still pointed at the first rented server, which ran a copy of its own; repointing it was a change in the Cloudflare dashboard, left to Petar.
Until then the old name went on reaching that copy, which is exactly the "both systems live at once" that was asked for.

Since 20 October 2026 an installation's addresses are its own and are not in the repository at all: `ROUH_PUBLIC_URL`, `ROUH_PUBLIC_HOSTS`, `ONE_PUBLIC_URL` and `ONE_PUBLIC_HOSTS` are set per machine (`deploy/installation.env.example`, `SETUP.md`), and the site file is a template, `deploy/nginx-rouh.conf.example`, which each machine copies and keeps as its own.

## The second stage: the names machines read

Petar asked for the rest of it the same day: "rename the repository and files that are currently in use and have jarvis inside, as well as processes and statuses", naming two he could see on the run details page - **Space jarvis** and **Asked for by Jarvis**.

Everything below moved.
The rule for all of it is one rule, and it is what makes a rename of this size safe: **the new name is what is written, the old name is still read.**
Nothing was cut over, nobody was signed out, no setting was lost, and every path anybody still has in their fingers still resolves.

### In this repository

| Was | Is |
|---|---|
| the package `jarvis/` | **`rouh/`** - every import, every `python -m rouh.x`, every `getLogger("rouh.x")` |
| `jarvis/jarvis_version.py` | **`rouh/rouh_version.py`** |
| `deploy/jarvis.sh` | **`deploy/rouh.sh`**. The one-line `deploy/jarvis.sh` wrapper left beside it was deleted on 29 October 2026, with the fallback to it in `update-all.sh`: nothing called it any more |
| `JARVIS_*`, about seventy settings | **`ROUH_*`**. `_env` in `rouh/config.py` reads the old name when the new one is unset, and the three shell scripts have a `setting` helper that does the same |
| the cookie `jarvis_session` | **`rouh_session`**, and the old one is still accepted, so nobody was signed out |
| `jarvis.settings.v1`, `jarvis.orb.v1`, `jarvis.columns.v1`, `jarvis.pane.v1`, `jarvis.rail`, `jarvis.showArchived`, ... | **`rouh.*`**. `load()` in `app.js` looks under the old key when the new one is empty and moves the value across, so no column width, orb slider or voice threshold was thrown away. `rouh.orb.v1` has since stopped being where the orb's settings live at all: they are the person's and are a row of the database (`rouh/settings.py`), with that key kept as the browser's mirror, so a slider that only ever reached local storage still goes up on the next connect |
| `jarvis.sqlite3` | **`rouh.sqlite3`**, and `config.db_path` uses the old file wherever that is the one that exists |
| `jarvis-page-ask`, `jarvis-page-follow`, `jarvis-page-key`, `jarvis-frame-key`, `jarvis-page-address`, `jarvis-page-answer`, `jarvis-html-size` | **`rouh-…`**. Both ends are ours - `rouh/pages.py` injects the sender and `app.js` receives - so they moved together, and no built workspace page names them |
| `jarvis_version` on the socket | **`rouh_version`**, sent under both names for one cycle so a tab open across the deploy still draws its version mark |
| `where: "jarvis"` | **`where: "rouh"`** |
| `jarvis-web/1.0`, `jarvis-self`, `application/vnd.jarvis.card+json` | **`rouh-web/1.0`**, **`rouh-self`**, **`application/vnd.rouh.card+json`** |
| `jarvisIcon`, `jarvisDetail`, `jarvisNowSha`, `jarvisFlag`, `window.__jarvis` | **`rouhIcon`**, **`rouhDetail`**, **`rouhNowSha`**, **`rouhFlag`**, **`window.__rouh`** |
| the worlds `jarvis_app`, `jarvis_with_tree`, `jarvis_with_one` | **`rouh_app`**, **`rouh_with_tree`**, **`rouh_with_one`**. `./e2e.sh serve jarvis` still works, as an alias |
| the commit scope `jarvis:` | **`rouh:`**, and `rouh/conflicts.py` strips either |
| a run's scratch folder `.jarvis/` | **`.rouh/`** |

### On the machine

| Was | Is | How the old name keeps working |
|---|---|---|
| `/var/www/jarvis` | **`/var/www/rouh`** | `/var/www/jarvis` is a symlink to it, so every path anybody still has resolves, including the `.env` systemd loads and the venv's own shebangs |
| `jarvis.service` | **`rouh.service`** | `/etc/systemd/system/jarvis.service` is a symlink to it, which is systemd's own alias mechanism, so `systemctl restart jarvis` still works |
| the five `jarvis.service.d` drop-ins | **`rouh.service.d`** | each sets its setting under **both** names, so code from before the rename still reads them |
| `/srv/jarvis-land` | **`/srv/rouh-land`** | symlinked |
| `/srv/spaces/jarvis` | **`/srv/spaces/rouh`** | not symlinked, because the spaces folder is listed and two entries would read as two spaces. `OLD_NAMES` in `one/config.py` maps `jarvis` to `rouh` so a run asking for the old name still lands in the right place, and `OLD_PROFILES` in `one/views.py` does the same for every run already in the list - so **Space jarvis** on a run from last week now reads **Space rouh** |
| the Linux user and group `jarvis` | **`rouh`** | the uid and gid did not change, so every file they own followed them; `/etc/sudoers.d/jarvis` became `/etc/sudoers.d/rouh`. The setting that names the workers' user did not follow: `ROUH_CREW_USER` defaulted to `jarvis` until 24 September 2026, so every background worker in between was started as a user that no longer existed and died in the second it was started. It is `rouh` now, and a setting that still says `jarvis` is read as `rouh` (`config.RENAMED_USERS`) |
| the one program's device **Jarvis** | **Rouh** | it is the device Rouh pairs as, so **Asked for by Jarvis** now reads **Asked for by Rouh** |
| `logs/jarvis.log` | **`logs/rouh.log`** | |

### The two things that carry a rollback

A deploy that fails is rolled back to the commit before it, and a commit from before the rename has a `jarvis/` package, not a `rouh/` one.
Two things make that safe rather than fatal, and they are the reason this could be done at all.

* **`deploy/run-server.sh`**, installed outside the checkout at `/var/www/rouh/run-server.sh`, is what `ExecStart` names.
  It asks the checkout which package it has and serves whichever it finds.
  A unit naming `rouh.server:app` by hand would have made every rollback across the rename come up dead, with no way back except a person at the machine.
* **`deploy/rouh.sh`** asks the same question twice: for which requirements file to install, and for which module to import in the check it runs before it restarts anything.

Both halves can go once nothing on main has a `jarvis/` package to roll back to.
That is a decision to take with this file open, not a tidy-up.

### Why it landed in two commits

The script that runs a deploy is the copy that was on disk when the deploy started, which is the one from **before** the commit being deployed.
So the deploy that carried the rename would have been run by a script that still said `pip install -r jarvis/requirements.txt` and `import jarvis.server`, and would have rolled the whole thing back for the two reasons above.

The first commit therefore did one thing: it made that script tolerant of either layout.
The second did the rename, under a script that already knew about it.
Anything of this shape has to be landed the same way.

## What still says jarvis, on purpose

Every one of these is read by a machine, not by a person, and every one of them is read rather than written: the new name is what anything writes now.

| Still `jarvis` | Where | Why it stays |
|---|---|---|
| ~~`mgpepe/jarvis`~~ | GitHub | **Replaced (27 October 2026):** the repository was moved to `rouh-it/rouh` instead of being renamed, and on 21 October 2026 the code went on as `rouh-it/rouh-core` and the workspace as a private repository of its own (task 98, step 98-21). `rouh-it/rouh` was archived on 27 October 2026 (task 140): read-only, nothing reads it, and GitHub still sends `mgpepe/jarvis` to it. Every remote here, `one/deploy/install.sh` and `land.sh` already name `rouh-it/rouh-core`. |
| `JARVIS_*` in `/var/www/rouh/.env` | the server | The secrets file, which nothing here is allowed to read and no deploy writes. `rouh/config.py` and all three shell scripts read both prefixes, so the file works untouched and can be changed over whenever somebody is at the machine, with nothing depending on the moment. |
| `jarvis_session`, the `jarvis.*` browser keys, `jarvis.sqlite3`, `jarvis/requirements.txt`, `jarvis.service`, `/var/www/jarvis`, `/srv/jarvis-land`, `jarvis_version`, `OLD_NAMES`, `OLD_PROFILES` | everywhere | Each is the **old** name only, read and never written, and each is one line to delete when the transition is over. |
| "Jarvis" in `workspace/` | the person's own notes | Task **30 Jarvis** and task **36 Jarvis and the workspace** are dated records of work done under that name, and their folders are `30.jarvis` and `36.jarvis-and-the-workspace`. Renaming them would rewrite history rather than rename a product, and would move folders the object tree, the migration map and every link into them depend on. They are the only "Jarvis" a person still sees, and they are content, not chrome. |
| "30 Jarvis" in `README.md` and `PROTOCOL.md` | two worked examples | They quote that task by its real title, so they say what the machine really answers. |

## What is left

All of it is done, and what remains is only taking the old names back out.
None of it is urgent and none of it is a migration.

1. ~~Rename `mgpepe/jarvis`.~~ Done another way: the code is `rouh-it/rouh-core`, and the old repository is archived (above).
2. **Change `/var/www/rouh/.env` over from `JARVIS_` to `ROUH_`**, while somebody is at the machine. Nothing depends on when.
3. **Delete the old names, a line at a time.** The `jarvis/requirements.txt` fallback and the `jarvis.server` branches (the `deploy/jarvis.sh` wrapper went first, on 29 October 2026) in `deploy/rouh.sh` and `run-server.sh` go together, once nothing on main has a `jarvis/` package to roll back to. Then `OLD_COOKIE`, `OLD_PREFIX`, the old-key read in `load()`, the `jarvis.sqlite3` fallback in `db_path`, the second `jarvis_version` on the socket, and the `/var/www/jarvis`, `/srv/jarvis-land` and `jarvis.service` symlinks.

The workspace tasks stay as they are.
