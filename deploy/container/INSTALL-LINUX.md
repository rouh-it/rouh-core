# Rouh on a Linux server

How to run Rouh on a Linux machine of your own: a server you reach only over SSH (a "headless" server, with no screen), a desktop, or a virtual machine.
Rouh for Mac does all of this by itself on a Mac.
Since 11 November 2026 (task 176, step 176-24) a server needs nothing but SSH: setup happens in the terminal, and nothing of Rouh's is reachable from the network until its owner exists.

## The one command

```bash
curl -fsSL https://rouh.land/install.sh | sh
```

Run it as a normal user with sudo, not as root (it refuses `/root`).
It goes in this order, and can be run again at any time:

1. **It checks the server and says what it found**: which Linux, the processor and its cores (2 at least, 4 to run well), memory (4 GB at least, 8 to run well), free disk (15 GB at least, 64 to run well), Python, whether port 8420 is free, and whether the server reaches rouh.land, ghcr.io (GitHub's container registry) and github.com.
   Ubuntu 22.04 and 24.04 and Debian 12 and 13 are tested; others may work.
2. **It says what it will do, and asks once**: what it installs, about 2 GB to download, about 5 minutes. `--yes` does not ask, for a script or cloud-init (`curl -fsSL https://rouh.land/install.sh | sh -s -- --yes`).
3. **It installs what is missing**: curl, git, openssl, Docker with Compose (Docker's own get.docker.com), and, when the server's Python is older than 3.12 (Debian 12 has 3.11), a standalone Python 3.12 for Rouh's updater, pinned by its SHA-256, into `~/.local/share/rouh/python`.
4. **It trusts nothing it has not checked.** rouh.land's release and its newest tested code are each signed with Rouh's release key (Ed25519, the key is written in the script); a release that does not check out stops the install with nothing used.
   The updater, rouh-core, is checked out into `~/rouh-core` at exactly the signed commit, never at whatever `main` is.
5. **It hands over to the `rouh` command** it installs as `/usr/local/bin/rouh`: the settings file `~/rouh/.env` (with a database password of its own, mode 600), Bring back your Rouh when a kept one is on the server, the nightly update, the first start (`linux_stack.py update`), and then `rouh setup`, in the same terminal.
   `--no-setup` stops after the start; run `rouh setup` later.

## Setup, in the terminal

`rouh setup` is Rouh's first run, the same as Rouh for Mac's and the web's, in the same order and words, through the same setup API on 127.0.0.1 (`rouh/web/setup_api.py`, with the setup code as its key):

1. **What kind of Rouh**: a **Connected Rouh** (recommended: a free rouh.land account and its own address on rouh.page, which works behind any router with no port opened) or an **Independent Rouh** (nothing leaves the server).
2. **About you**: first and last name, email, your time zone, and a password, typed twice and hidden, its rules shown before you type.
3. **Connected only: check your email.** rouh.land sends a 6-digit code; type it. `r` resends it, `c` changes the email, `i` makes it Independent instead.
4. **Born**: its Name (in orange), its Birthday and its URL. It always answers to Rouh; a nickname is optional.
5. **A brain**: an Anthropic or OpenAI API key, required, checked live with a real answer from the company.
6. **A plan for its agents**, strongly recommended: a Claude plan (open Claude's sign-in address on any device, or scan the QR code, and paste back the code Claude shows) or a ChatGPT plan (Codex's device code: allow device code sign-in in ChatGPT's security settings first, then approve the code shown). Going on without one needs **Go on without a plan…** and a yes to the cost warning: every job then costs much more, on the API key.
7. **Ready**: a one-time sign-in link, with a QR code for a phone. Connected: `https://<its name>.rouh.page/...`. Independent: the `ssh -L` line to type on your own computer, and a link for it.

Stopped half way? `rouh setup` carries on where you left off.
The setup code is never printed: `rouh setup` asks the core for it and writes a new one each time, a start never puts it in `docker logs`, and on a server it lasts 24 hours while there is no owner (`ROUH_SETUP_CODE_HOURS`).

## The rouh command

| Command | What it does |
|---|---|
| `rouh status` | Running or not, its name and kind, its address, the release (signature checked), the nightly update and the last one, backups, the open ports, and its AI (it reminds you while no plan is connected) |
| `rouh setup` | The first run, in the terminal; again, to connect a plan later |
| `rouh open` | A one-time sign-in link: your own domain, else its rouh.page address, else the `ssh -L` line and a local link |
| `rouh update` | Update now; `--off` and `--on` turn the nightly update off and on |
| `rouh back` | Back to the release before, on the images kept for it |
| `rouh logs [PART] [-f]` | The last lines of a part (`core` by default) |
| `rouh backup` | A copy of the database now; `--list`; `--restore NAME` |
| `rouh domain NAME` | Your own domain with HTTPS; `--off` |
| `rouh relay URL --domain D` | A relay of your own for a Connected Rouh's phone address; `--default`, `--off` |
| `rouh doctor` | Checks the server, Docker, the release, the ports, the firewall, the setup code, its AI and the address, and says what to fix |
| `rouh uninstall` | Keep my data (recommended) or Wipe my data |

`--debug` on any of them shows the commands and their output.

## Updates, and going back

`rouh-update.timer` runs `rouh update --nightly` every night at a time between 03:00 and 05:00 (server time) chosen once per server, and catches up after a night the server was off.
It first brings the updater to rouh.land's newest tested, signed commit (forward only), then runs `linux_stack.py update`: the newest signed release, its images pulled beside the running ones, the database saved first, the new base checked with this Rouh's own code, then started, and if it is not healthy the release before runs again by itself.
Its log is `~/rouh/logs/update.log`; `rouh status` shows the last line.
`rouh update --off` turns it off; `rouh update` updates now.

## Reaching it from a phone

- **A Connected Rouh** has its own address, `https://<its name>.rouh.page`, from its birth: it dials out to the relay and needs no open port, no domain and no router setting. `rouh open` gives a sign-in link and QR code for it.
- **An Independent Rouh** has three ways:
  1. **An SSH tunnel**: `rouh open` prints the line to type on your own computer, `ssh -L 8420:127.0.0.1:8420 you@server`; then the link it gives opens Rouh there.
  2. **Tailscale or WireGuard** (a private network between your own devices): put the server and your laptop on it, and the tunnel works from anywhere, with no SSH port open to the internet. Rouh's page itself stays on the server's 127.0.0.1.
  3. **Your own domain**, below.

### Your own domain

```bash
rouh domain rouh.example.com
```

For an Independent or a Connected Rouh alike, once Rouh has its owner.
First point the name at the server: an A record (and AAAA for IPv6) at your DNS provider; a Cloudflare record must be grey (DNS only).
`rouh domain` checks that the name points at this server and that nothing else listens on 80 or 443, then turns on the stack's `edge` part: Caddy, pinned by its digest in the signed stack file, which gets and renews a Let's Encrypt certificate and passes every request on to Rouh, marked as from the internet.
Only then does anything of Rouh's listen beyond the server: ports 80 and 443, nothing else.
The stack check holds the edge part to the release's own, and refuses 80 and 443 for any part, and for the edge without a domain set (`guard/policy/stack-policy.json`, `public_ports`).
Through the edge, the setup pages are never reachable, and before an owner exists nothing is: Rouh answers 503.
`rouh open` then gives a sign-in link on your domain. `rouh domain --off` closes 80 and 443 again.
Docker's published ports go round ufw; that is intended for 80 and 443 here, and `rouh doctor` says so.

### A relay of your own

A Connected Rouh's phone address goes through rouh.land's relay (rouh.page) unless its settings say another:

```bash
rouh relay https://relay.example.com/relay/ --domain rouh.example.com
rouh relay --default     # rouh.land's again
rouh relay --off         # no phone address at all
```

Rouh claims its address at `<URL>claim` and dials out to the relay that answers (`rouh/relay.py`, `PROTOCOL.md`, "The relay").
**Not yet possible:** the relay's own server (rouh-it/rouh-relay: frps and its judge, relayd) and the claim endpoint, which today is part of rouh.land's birth service, are not public, so there is no relay to run yourself yet. Until they are, an Independent Rouh with your own domain gives the same: your own address, with nothing between you and your Rouh.

## Firewall

The installer does not turn ufw on (Ubuntu's simple firewall): on a server whose SSH is on another port that can lock you out, and Rouh needs no port open to the outside.
`rouh doctor` lists what listens, and when nothing protects the server suggests `sudo ufw allow OpenSSH && sudo ufw enable`.

## Uninstall, and Bring back

```bash
rouh uninstall
```

It asks what should happen to Rouh's data, as Rouh for Mac does (step 176-17):

- **Keep my data (recommended)**: Rouh stops, its database alone starts and is saved with `pg_dump`, then restored once into a throwaway database (`rouh_keep_check`) and its tables counted; the volumes that make it itself (the workspace, its own code, the libraries it added, its keys, its identity and data, its undo points and its agents' sign-ins) are saved as tars, read back, with `git fsck --full` on the code and the workspace; all of it goes into `~/rouh-kept/<date>/` (folders 0700, files 0600: it holds Rouh's keys) with each file's SHA-256 checked after the copy, with the settings file and the release.
  Nothing is removed unless the whole copy checks out; otherwise Rouh is started again.
- **Wipe my data**: only after `WIPE` is typed.

Then it removes Rouh's containers, images, volumes and networks, the nightly update, the `rouh` command, `~/rouh` and `~/rouh-core`.
It never removes Docker, your other containers, or a Connected Rouh's rouh.land account.

Install Rouh again with the same command, and it finds the kept copy and offers **Bring back your Rouh** (the default) or **Start fresh**.
Bring back checks every SHA-256 again, makes each volume with Compose's own labels, unpacks it (`git fsck` again), and restores the database into the new PostgreSQL, counting its tables, all before Rouh first starts; the Rouh that starts is the same one, with the same owner and keys.

## Signing in again

`rouh open`, any time, from the server's terminal: a one-time link (ten minutes) on your domain or rouh.page, or the tunnel line and a local link that works once.
Or sign in with your email and the password you chose in setup, at any address Rouh answers on.

# By hand, and the rest

The sections below are what the command does, by hand, and what goes beyond it.

## 1. A Linux virtual machine on a Mac (UTM)

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
git clone https://github.com/rouh-it/rouh-core.git ~/rouh-core   # Rouh's code, public since 7 November 2026
commit="$(curl -fsS https://rouh.land/mac/release/stable.json | python3 -c 'import json,sys; print(json.loads(json.load(sys.stdin)["payload"])["commit"])')"
git -C ~/rouh-core checkout -q "$commit"
[ -f ~/rouh-core/deploy/container/linux_stack.py ] || git -C ~/rouh-core checkout -q main   # a release made before linux_stack.py existed has none: the one time main is used
python3 ~/rouh-core/deploy/container/mac_release.py release-status
```

The last line checks the live release's signature with the public key in that checkout and says what it holds.

## 5. The settings file

```bash
mkdir -p ~/rouh && chmod 700 ~/rouh
cp ~/rouh-core/deploy/stack/settings.env.example ~/rouh/.env
chmod 600 ~/rouh/.env
```

Set `POSTGRES_PASSWORD` (make one up: `openssl rand -base64 33`).
Nothing else is needed: Rouh is free to download and install, and no account on rouh.land is asked for.
Leave `ROUH_INSTALL_CODE=free` as it is: it is not a secret, and only lets a release made before 8 November 2026 start without an account.
An account on rouh.land is for the optional connected services, chosen later inside Rouh.

## 6. Start it

```bash
python3 ~/rouh-core/deploy/container/linux_stack.py update
docker compose -p rouh -f ~/rouh/stack/stack.json logs -f code-install core | grep -m1 "no owner yet"
```

The first time there is no code yet, so the release's own stack file runs.
`code-install` fetches Rouh's code once. Then run `rouh setup` (the wizard above), or `docker compose -p rouh -f ~/rouh/stack/stack.json exec core python manage.py setup_link` and open the whole address it prints, and make the owner there (since 11 November 2026 the core no longer prints it into its log); the code in it is what keeps anybody else who reaches the page from making the owner first, and nobody types it: the page takes it out of the address at once.
The page then takes you through the rest of the first run: your name and email, Connected or on its own, its birth on rouh.land if you chose Connected (or a free Rouh with the nickname you give it), and a checked Anthropic or OpenAI key (`rouh/web/firstrun.py`).
To sign in again later: `rouh open`, or `docker compose -p rouh -f ~/rouh/stack/stack.json exec core python manage.py setup_link` and open the address it prints, which works once.

From then on Rouh's stack file is its own, in its code. After it changes it, apply it with:

```bash
python3 ~/rouh-core/deploy/container/linux_stack.py apply
```

It reads the stack folder out of the code volume, resolves it with this machine's Compose sealed in a container that sees only that folder and the two settings files (so a stack file cannot fold a file of the machine into itself through `env_file`, `label_file`, `include` or `extends`), and runs the protected core's own check (`guard/rouh_guard/stackpolicy.py`) out of the release's guard image, with no network, against the allow-list the release signs.
Refused, it says each reason in a sentence and keeps the last of the Rouh's own stack files that passed, or else the release's; nothing refused is ever started.
`linux_stack.py status` says which stack runs and what was refused.
Nothing inside the machine can apply a stack file: no container has the Docker socket.

## 7. A new release

Each night that finds patch-level fixes publishes a new level. `rouh-update.timer` runs `linux_stack.py update` every night (above); by hand it does:

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
3. Steps 1 to 5 above, if this machine is new: Docker, the updater, the settings file with `POSTGRES_PASSWORD`.
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
