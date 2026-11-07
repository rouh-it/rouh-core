# Rouh on a Linux machine, or in a Linux VM on a Mac

How to run Rouh's containers on a Linux machine of your own, or in an arm64 Linux virtual machine on an Apple Silicon Mac, from a signed release on rouh.land.
Rouh for Mac does all of this by itself; this is the same by hand.

Since 24 October 2026 (task 98, step 98-23) a release names three images, each by its digest: `ghcr.io/rouh-it/rouh-base` (what every part runs on, no Rouh code), `ghcr.io/rouh-it/rouh-guard` (the protected core, which a Rouh uses and cannot edit) and PostgreSQL.
There is no code image: on its first start a Rouh fetches the newest version of Rouh that passed its tests from rouh.land, with an install code from your account there, and from then on its code is its own, in the code volume, and no update writes to it.
The stack file is the Rouh's own too (`/code/deploy/stack/compose.yml`); before applying it, check it (step 6).

## 1. Make the VM

Any tool that runs an arm64 Linux VM works.
These steps use UTM (free, from mac.getutm.app) with Ubuntu Server 24.04 for ARM.

1. Download the Ubuntu Server 24.04 **ARM64** installer from ubuntu.com/download/server/arm.
2. In UTM: Create a New Virtual Machine, then Virtualize, then Linux. Pick the installer file.
3. Give it at least **4 CPU cores, 8 GB of memory and 64 GB of disk**.
   The stack takes about 2 GB, and each run of Claude Code or Codex takes about 1.7 GB more (`ONE_MAX_RUNS=2` by default; with more, raise `ROUH_WORKER_MEMORY` in the settings file to match).
4. Leave the network on **Shared Network**.
5. Install Ubuntu with the defaults. When it asks, tick **Install OpenSSH server**.
6. After the restart, sign in on the VM's screen and find its address with `ip -4 addr show | grep inet`.
   It is usually something like `192.168.64.5`.
   From here on, you can do everything from the Mac's Terminal with `ssh <you>@<the VM's address>`.

## 2. Install Docker and Compose

On the VM, with Docker's own packages (from docs.docker.com/engine/install/ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Sign out and back in, so that `docker` works without `sudo`.
Check it with `docker compose version`.

## 3. The images need no sign-in

The two packages a release names, `rouh-base` and `rouh-guard`, are public, so the Rouh instance this machine runs (any Rouh but the Creator Rouh, the maker's own) pulls them with no GitHub account and no token, and step 6 pulls them as they are.
If you signed Docker in to `ghcr.io` for an earlier install, sign it out (`docker logout ghcr.io`) and delete that token on GitHub: nothing needs it, and a token that has run out is refused even for a public image.

## 4. Get the updater

`linux_stack.py` does what Rouh for Mac does by itself: it takes a release from rouh.land only when its signature is good, and it starts a stack only after the stack check passed it.
It and `mac_release.py` beside it decide which releases are trusted, so take them from the commit a release names, not from a `main` nobody has checked:

```bash
git clone git@github.com:rouh-it/rouh-core.git ~/rouh-core   # Rouh's code, private for now: needs access to it
commit="$(curl -fsS https://rouh.land/mac/release/stable.json | python3 -c 'import json,sys; print(json.loads(json.load(sys.stdin)["payload"])["commit"])')"
git -C ~/rouh-core checkout -q "$commit"
[ -f ~/rouh-core/deploy/container/linux_stack.py ] || git -C ~/rouh-core checkout -q main   # a release made before linux_stack.py existed has none: the one time main is used
python3 ~/rouh-core/deploy/container/mac_release.py release-status
```

The last line checks the live release's signature with the public key in that checkout and says what it holds.

## 5. The settings file and the install code

```bash
mkdir -p ~/rouh && chmod 700 ~/rouh
cp ~/rouh-core/deploy/stack/settings.env.example ~/rouh/.env
chmod 600 ~/rouh/.env
```

Set `POSTGRES_PASSWORD` (make one up: `openssl rand -base64 33`) and `ROUH_INSTALL_CODE`: sign in at https://rouh.land/registry/birth/account/ (a link comes by email), press **Make an install code**, and paste it.
The code works for a week, for up to five first starts.

## 6. Start it

```bash
python3 ~/rouh-core/deploy/container/linux_stack.py update
docker compose -p rouh -f ~/rouh/stack/stack.json logs -f code-install core | grep -m1 setup
```

The first time there is no code yet, so the release's own stack file runs.
`code-install` fetches Rouh's code once; `core` then prints `Open http://127.0.0.1:8420/setup?code=...`.
Open that whole address and make the owner there; the code in it is what keeps anybody else who reaches the page from making the owner first, and nobody types it: the page takes it out of the address at once.
The page then takes you through the rest of the first run: your name and email, Connected or on its own, its birth on rouh.land if you chose Connected (or a free Rouh with the nickname you give it), and a checked Anthropic or OpenAI key (`rouh/web/firstrun.py`).
The owner has no password: to sign in again later, run `docker compose -p rouh -f ~/rouh/stack/stack.json exec core python manage.py setup_link` and open the address it prints, which works once.

From then on Rouh's stack file is its own, in its code. After it changes it, apply it with:

```bash
python3 ~/rouh-core/deploy/container/linux_stack.py apply
```

It reads the stack folder out of the code volume, resolves it with this machine's Compose sealed in a container that sees only that folder and the two settings files (so a stack file cannot fold a file of the machine into itself through `env_file`, `label_file`, `include` or `extends`), and runs the protected core's own check (`guard/rouh_guard/stackpolicy.py`) out of the release's guard image, with no network, against the allow-list the release signs.
Refused, it says each reason in a sentence and keeps the last of the Rouh's own stack files that passed, or else the release's; nothing refused is ever started.
`linux_stack.py status` says which stack runs and what was refused.
Nothing inside the machine can apply a stack file: no container has the Docker socket.

## 7. A new release

Each night that finds patch-level fixes publishes a new level. Run `linux_stack.py update` again, by hand or from a timer:

1. the newest release of this Rouh's line, its signature checked; one no newer, or one that failed here before, changes nothing;
2. its images pulled, beside the ones that run;
3. the database saved in `~/rouh/backups/` (the two newest are kept);
4. the new base checked with this Rouh's own code, with the release's own protected core;
5. the stack chosen and checked as in step 6;
6. started, and every part waited for; if it is not healthy, the release before and its stack run again, and that release is not taken again by itself.

`linux_stack.py back` goes back to the release before, on the images kept for it; nothing is downloaded again.
To put a database backup back: `docker compose -p rouh -f ~/rouh/stack/stack.json cp <the .dump> postgres:/tmp/r.dump`, then `... exec -T postgres pg_restore -U rouh -d rouh --clean --if-exists --no-owner /tmp/r.dump`.

A machine set up by hand before 29 October 2026, with `release.json` in `~/rouh`, keeps its volumes: the first `update` takes that release as the one in use when its signature is good, and moves the containers onto `~/rouh/stack/stack.json`.

## 8. Backups

Every night the stack's backup part copies the database into the stack's `backups` volume, with PostgreSQL's own `pg_dump`, at `ROUH_BACKUP_AT` (03:40 UTC unless the settings file says otherwise, or the first minute after it that the machine is awake), and keeps the newest seven.
Ask Rouh how the server is, and it says when the newest copy was made.

```bash
docker compose -p rouh -f ~/rouh/stack/stack.json exec backup /opt/rouh-guard/bin/rouh-backup now    # a copy now
docker compose -p rouh -f ~/rouh/stack/stack.json exec backup /opt/rouh-guard/bin/rouh-backup list   # the copies
python3 ~/rouh-core/deploy/container/linux_stack.py restore              # the newest put back
python3 ~/rouh-core/deploy/container/linux_stack.py restore rouh-20261029-034000.dump
```

`restore` stops the core, makes one more copy of the database as it is, so the restore itself can be undone, restores the copy you named into a new database and only then puts it in the place of Rouh's own (a restore that fails changes nothing), and starts the core again.

Once a week the core also sends one encrypted copy off the machine, to Cloudflare R2 or any S3, when the settings file says where (`ROUH_OFFSITE_*` under "Backups" in `settings.env.example`).
It is the whole Rouh in one file: the newest nightly copy of the database, both keys, the data directory and the workspace, encrypted in age's format for the public key or the passphrase you give, so nothing readable reaches the bucket.
Nothing is installed on this machine for it, and without those settings nothing is sent.

1. In Cloudflare: R2, Create bucket; then Manage R2 API Tokens, Create API token, **Object Read & Write**, for that bucket only.
   Put the S3 endpoint it shows (`https://<account id>.r2.cloudflarestorage.com`), the bucket's name, the Access Key ID and the Secret Access Key into `ROUH_OFFSITE_ENDPOINT`, `ROUH_OFFSITE_BUCKET`, `ROUH_OFFSITE_KEY_ID` and `ROUH_OFFSITE_SECRET`.
2. On your own computer, not this machine, make a key with age (age-encryption.org; `brew install age` on a Mac): `age-keygen -o rouh-offsite.key`.
   Put the public key it prints (`age1...`) into `ROUH_OFFSITE_RECIPIENT`, and keep `rouh-offsite.key` safe and off this machine: it is the only thing that opens the copies, and nothing here can.
   Or set `ROUH_OFFSITE_PASSPHRASE` to a long passphrase instead, and keep a copy of it off this machine.
3. `python3 ~/rouh-core/deploy/container/linux_stack.py apply`, so the core reads the new settings.
   `docker compose -p rouh -f ~/rouh/stack/stack.json exec core python manage.py offsite_backup run` sends the first copy at once; from then on the core sends one a week, and keeps the newest eight under `rouh-backups/<ROUH_STACK_NAME>/`.

To restore after losing the machine: download the newest copy (from Cloudflare's dashboard, or `offsite_backup fetch --to FILE` on any Rouh with the same settings), open it where the key is, `age -d -i rouh-offsite.key -o rouh.bundle <the copy>.bundle.age` (or `age -d` and the passphrase), and bring the bundle into a fresh stack as in step 9.

## 9. Bringing in a Rouh you already have

A Rouh that runs somewhere else, on a server without containers or in another stack, comes in whole: its database, the key every saved login is sealed with, the key sign-ins are signed with, its data directory (attachments and files) and its workspace.
It goes into a fresh stack, before that stack's first start, in place of steps 6 and 7.

1. On the Rouh you have, make its bundle, one file, with its own settings, so the command finds its data, keys and database where that Rouh keeps them.
   On a server Rouh, as root (here with the layout `deploy/rouh.sh` makes; another installation names its own paths):

   ```bash
   systemd-run --quiet --wait --pipe --collect -p EnvironmentFile=-/var/www/rouh/.env \
     -p WorkingDirectory=/var/www/rouh/app /var/www/rouh/.venv/bin/python \
     manage.py export_rouh --out - > /var/tmp/rouh.bundle
   chmod 600 /var/tmp/rouh.bundle
   ```

   It dumps the database with that machine's `pg_dump`, which must be as new as its PostgreSQL server.
   From another stack: `docker compose ... exec backup /opt/rouh-guard/bin/rouh-backup now`, then `docker compose ... exec --user 10001 core python manage.py export_rouh --out /data/rouh.bundle --dump newest`, and `docker compose ... cp core:/data/rouh.bundle .`.
   The bundle opens every saved login it holds: it is written readable by its owner alone, never to a terminal, and no key is printed. Treat it as you would the keys.
2. Copy it to this machine, over ssh: `scp server:/var/tmp/rouh.bundle ~/rouh/`, and delete it on the server.
3. Steps 1 to 5 above, if this machine is new: Docker, the updater, the settings file with `POSTGRES_PASSWORD` and an install code.
4. Bring it in:

   ```bash
   python3 ~/rouh-core/deploy/container/linux_stack.py import ~/rouh/rouh.bundle
   ```

   It takes the newest release, as `update` does, and checks the bundle; then it restores the database into the stack's PostgreSQL, puts the encryption key into the keys volume as `encryption.key` (rouh's alone, as the core's start keeps it), and the Django key, the data directory and the workspace into `core-data`.
   It refuses a stack that has started before, and changes nothing then.
5. Start it, as in step 6: `python3 ~/rouh-core/deploy/container/linux_stack.py update`.
   The code is the newest tested Rouh from rouh.land, as for any new stack; the core runs the database's migrations up to it.
   The owner is the one the old Rouh had, and every saved login opens: sign in with the address `docker compose -p rouh -f ~/rouh/stack/stack.json exec core python manage.py setup_link` prints, or with the password you had.
6. Delete `~/rouh/rouh.bundle` once Rouh is up.

The old Rouh's settings file is not part of the bundle: put its keys for other services (Telegram, Brevo, the voice and the rest) into this machine's settings file, `~/rouh/.env`, and its model keys too, or type them in on Rouh's page.
