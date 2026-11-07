# Timed grants: GitHub, and servers past the key proxy's lists

Petar, 2 November 2026: "I need a command to give you full github access for certain amount of hours to run from my computer, just like we have for the servers. Also something similar for the url proxy. That has been blocking me."

Petar, the same day, a little later: "no proxy should be open in general. I can't be thinking and asking a host and port every time. if I need access to somewhere I need it to be enabled either by name or everything together or options for various things."

Three commands the owner runs on their own Mac, each opening something to the runs for some hours, each running out by itself at its end.
`rouh-open` runs the other two together, and also opens the owner's own servers whose logins refuse the jobs' keys until a grant lets them in: rouh.land, the relay and the host itself (below, "The owner's own servers").
Nothing takes a grant away when a job finishes: it lasts until its end, or until the owner revokes it.

```bash
rouh-open 8                         # the usual: GitHub as you, the internet, rouh.land's, the relay's and the host's logins, 8 hours
rouh-open add the host                # one server's login added to what is already open, ending when it ends
rouh-open status                    # the same block: what is open, and until when
rouh-open status --details          # and the token's scopes, and the host's own list
rouh-open close                     # all of it closed now (only the owner closes; a job never does)
rouh-open update                    # the newest of these commands, here and on the host, checked
rouh-open --version                 # which one this is

rouh-proxy-grant internet 8         # any public server, any port (never a private address); `all` is its older name
rouh-proxy-grant ssh 8              # ssh ports (22, 222, 2022, 2222, 22022) on any public server
rouh-proxy-grant servers 8          # your own servers, by name, on any port
rouh-proxy-grant lan 8              # the office network and the host itself, any port (never Rouh's containers)
rouh-proxy-grant example.com 8      # that name and every name under it, any port
rouh-proxy-grant rouh.land:22 8     # one port of one server, as before
rouh-proxy-grant internet lan 8     # several at once
rouh-proxy-grant list               # each open grant and when it ends, in plain words
rouh-proxy-grant log                # what the grants were used for: where, which port, which grant
rouh-proxy-grant revoke internet    # that one closed
rouh-proxy-grant revoke all         # every proxy grant closed (GitHub is rouh-github-grant revoke)
rouh-proxy-grant revoke ssh         # one closed
rouh-proxy-grant servers list       # the servers list, kept on the host
rouh-proxy-grant servers add NAME-OR-IP [ADDRESS]
rouh-proxy-grant servers remove NAME-OR-IP
rouh-proxy-grant update             # the latest of all of this, on the Mac and on the host

rouh-github-grant 8                 # GitHub as you (gh auth token on the Mac), 8 hours; 1 to 72
rouh-github-grant 8 --token         # a token you paste or pipe in instead, such as a fine-grained one
rouh-github-grant status            # open or not, until when, as which GitHub user (--details: its scopes)
rouh-github-grant revoke
```

HOURS is a whole number from 1 to 72, 8 when left out.

### What stays closed in every mode

- **Private addresses**, unless a `lan` grant is open: the host, the office network, and every container. `internet` never includes them.
- **Rouh's own containers**, even under `lan`: the core, its database, the guard, checkdb and the key proxy itself. `lan` reaches the private networks of the host's own interfaces that are not Docker's, and the host's own addresses; every network Docker has stays refused but for the host's own address on it. The keys volume is not on any network at all.
- **Loopback and link-local** addresses (the proxy itself, and a cloud's metadata address), whatever is open.
- **The keys.** The Anthropic and OpenAI keys and the GitHub token are added by the proxy only; no grant hands a worker any of them.

Every address is looked up once, and the connection is made to the address that was checked.
Each connection a grant let through, rather than the standing rules (ports 80 and 443 to public servers, and `ROUH_KEYPROXY_ALLOW`), is logged by the proxy as `GRANT <grant> <how> host:port address`, with no header and no key.
`rouh-grant prune` gathers those lines each minute into `/var/log/rouh-grant-connections.log` on the host, which outlives the proxy's container, and `rouh-proxy-grant log` shows it.

## The owner's own servers: rouh.land, the relay and the host

Petar, 2 November 2026: "lets fix the missing permissions by adding them to the "rouh-open 8" command. also let's add ssh admin@203.0.113.20 sudo rouh-land-admin grant in it too."

Opening the key proxy is not enough for a server whose own login refuses the jobs' keys.
On 2 November 2026 (run c89efbb5, task 165) the network path to rouh.land and the relay was open for 8 hours and both still answered `Permission denied (publickey)`.
So `rouh-open HOURS` opens them too, each from the owner's Mac with the owner's own key, which is never on the host, so nobody who breaks into Rouh or the host can open them:

- **rouh.land** (203.0.113.20): `ssh admin@203.0.113.20 sudo -n /usr/local/sbin/rouh-land-admin grant HOURS`. That server's own command puts the jobs' key in `rouh`'s keys with an end time, and its 5-minute timer throws it out after (task 165, step 165-03). If it grants fewer hours than asked, `rouh-open` asks again for its most and says so on the line. `close` runs its `lock`, which also says whether any SSH, sudo, user or cron file changed while the jobs were in. The jobs reach it as `ssh rouh-land`.
- **The relay** (203.0.113.30, rouh.page): it has no grant command of its own, so `rouh-open` sends `servers/rouh-jobs-keys` over the owner's root login and runs it there. It writes one line into `/root/.ssh/authorized_keys`, `expiry-time="YYYYMMDDHHMMZ",from="198.51.100.10,198.51.100.11",no-agent-forwarding,no-X11-forwarding` and the `rouh-jobs-to-relay` key, in place of any earlier line of that key, so sshd itself refuses it after its end (UTC). The first time, it also puts itself in `/usr/local/sbin/rouh-jobs-keys` and starts `rouh-jobs-keys-prune.timer`, which every 5 minutes takes out a jobs' key line whose time is up, or that has no end at all, and ends its sessions still open. Only lines holding a jobs' key it keeps in `/etc/rouh-jobs-keys/` are ever written or taken out; it checks every other line is the same after each write and puts the file back if not, and the file as it was before its first write is kept beside it as `authorized_keys.before-rouh-open`. `close` takes the line out and ends the sessions that logged in with it (found by the key's fingerprint in sshd's log). The jobs reach it as `ssh relay`.

The servers are a small table at the top of `mac/rouh-open`, and `~/.config/rouh/rouh-open.conf` (or the file `ROUH_OPEN_CONFIG` names) changes or adds to it, a line the same shape for each:

```
# name    | how     | login on it        | shown as  | its grant command, or the jobs' public key
rouh-land | admin   | admin@203.0.113.20 | rouh.land | /usr/local/sbin/rouh-land-admin
relay     | keyline | root@203.0.113.30 | relay     | ssh-ed25519 AAAA... rouh-jobs-to-relay
host      | host    | -                  | host      | ssh-ed25519 AAAA... rouh-jobs-to-host
jobs-from | 198.51.100.10,198.51.100.11
```

`admin` is a server with a command of its own that takes `grant HOURS`, `status` and `lock`; `keyline` is any server where the owner logs in as root (or with sudo), and needs nothing installed on it first; `host` is the host itself, reached the way the host is (`ROUH_HOST_SSH`), its key kept in the owner's own account there by `rouh-grant jobs-key`; `NAME | off` leaves one out.
A host may carry a port, `user@host:2222`.
On the Mac, `ROUH_OPEN_<NAME>_USER` and `ROUH_OPEN_<NAME>_KEY` change the user and the key for one server (the name in capitals, `-` and `.` as `_`: `ROUH_OPEN_RELAY_KEY=~/.ssh/petar-laptop-to-relay.pub`, `ROUH_OPEN_ROUH_LAND_USER`).
Every ssh offers one key only, with `IdentitiesOnly=yes`: the one given, else the one `~/.ssh/config` names for that host, else ssh's own default files.

`rouh-open add NAME...` opens one or more of these servers on their own, ending when what is already open ends (the latest end the host has a record of), so a server new to the table joins an open window without anything open being closed, shortened or lengthened; rouh.land's own command takes whole hours, so there it is rounded up.

A new server for the jobs: make it a key in the worker (`rouh-ssh-key NAME`), add a `Host` for it to the worker's `~/.ssh/config`, add its line to the table, and it opens and closes with the rest.

### The host itself

Petar, 4 November 2026: "my latest temporary grant commands give access to a few things: rouh-open 14 -> Open for Rouh's runs until 00:19 tomorrow (14 h): GitHub as mgpepe / Internet any public server, any port (office network stays closed) / rouh.land server login / relay server login / Close early: rouh-open close. but it seems accessing the host parent computer is not on the list. can we add this too?"

So `rouh-open HOURS` has a fifth line, `the host  server login`: the machine Rouh's containers run on (198.51.100.10, SSH on a port of its own), where the jobs otherwise have no SSH and no sudo.
It is the relay's design, run by the host's own helper instead of over a root login:

- **Opened only from the owner's Mac.** `rouh-open` logs in to the host the way it already does, as `admin` with the owner's own approved key, and runs `sudo -n /usr/local/sbin/rouh-grant jobs-key open the host HOURS FROM <key>`, the one command admin may run with sudo and no password (`/etc/sudoers.d/rouh-grant`). Nothing inside Rouh or the host holds a key that can run it, so nothing there can open it by itself.
- **The account is admin**, the owner's own admin account on the host and the one `rouh-open` logs in as: `rouh-grant` writes the key into the keys of whoever ran it with sudo (`SUDO_USER`), never root's. admin's sudo is the owner's admin; `rouh-open` says on the line if admin's sudo asks a password, because then the jobs can log in but have no sudo.
- **A key of its own**, `rouh-jobs-to-host` (`~/.ssh/jobs-to-host` in the worker), written as one line into `~admin/.ssh/authorized_keys` with `expiry-time="<the end>Z"`, `from=` the addresses the jobs' connections arrive from, `no-agent-forwarding` and `no-X11-forwarding`, by `servers/rouh-jobs-keys` (kept in `/usr/local/lib/rouh-grant` and, once opened, `/usr/local/sbin`). Only that key's line is ever written or taken out; every other line is checked unchanged after each write and the file put back if not, and the file as it was before the first write is kept beside it as `authorized_keys.before-rouh-open`. Its `rouh-jobs-keys-prune.timer` takes the line out every 5 minutes once its time is up, or at once if it has no end, and ends the sessions still open that logged in with it (by the key's fingerprint in sshd's log), never admin's own other sessions.
- **Where the jobs come from.** A job reaches the host as `ssh host`, out through the key proxy (the `internet` grant `rouh-open` opens in the same command, logged as `GRANT all` like every other grant, `rouh-proxy-grant log`) to the host's public address, `198.51.100.10:2222`, which the office router hands back to the host; `ssh the host-backup` is the same over a backup line, `198.51.100.11:22`. So `from=` is the two lines, `jobs-from` in the table, and the gateway of each of the host's default routes, which `rouh-grant` adds on the host because a router may show a connection that turns back at it as coming from its own address. A run never reaches the host's private addresses: those stay `lan`, which `rouh-open` does not open.
- **Closing.** `rouh-open close` takes the line out, ends the jobs' sessions, and, as rouh.land's `lock` does, says whether any SSH, sudo, user or cron file changed while the jobs were in: the helper fingerprints `sshd_config` and its folder, every `authorized_keys` (without the jobs' own lines), `sudoers` and its folder, `passwd`, `group`, `shadow`, the cron files and itself when the key opens, and names under a `WARNING` line each that differs when it is closed or pruned. The relay gets the same report now, from the same helper. `rouh-open status` reads the key's end from the host (`jobs-key until the host`). Every open and close is in `/var/log/rouh-grant.log`, and the helper's in the system log (`logger -t rouh-jobs-keys`).

**How it fits the host's rule that only approval-backed keys get in.**
The rule stands for every other key and nothing about it is loosened: no sshd setting is changed, and no key but the jobs' one line is ever written.
The jobs' key is the one exception, and each time it is the owner's approval that lets it in: it can be written only by a command the owner runs from their Mac, through a login that itself needs their Bitwarden approval or their iPhone's Face ID, and only for the hours they give.
After that sshd itself refuses it at its end, from any address but the jobs', and the timer is the second lock.
If the host's sshd would not take a plain key for admin at all (only security keys, or a key and a code, or admin not among `AllowUsers`, read with `sshd -T`), `rouh-grant` says so and writes nothing, rather than changing sshd to let it in.

What the jobs can do while it is open: log in to the host as admin, so everything admin can do, and with admin's sudo, root on the machine, the Docker that runs Rouh's own containers included.
That is the reason it is only ever open for the hours the owner gives, and why closing reports what changed.

## What it prints

Petar, 3 November 2026, of the first version: "put some meaning and order in the rest of the stuff - no duplicates, no things that are unclear".
So `rouh-open` prints one short block and nothing else: the commands it calls are told to be quiet (`ROUH_GRANT_QUIET=1`), and there is no "Tell Rouh" line, because Rouh reads the grants itself (below).

```
Open for Rouh's runs until 22:55 today (14 h):
  GitHub         as mgpepe
  Internet       any public server, any port (office network stays closed)
  rouh.land      server login
  relay          server login
  the host         server login
Close early: rouh-open close
```

A part that failed says `NOT open:` and why, in plain words ("no answer from 203.0.113.30 (is this Mac online? is the server up?)", "did not take this Mac's key (name the key it takes: ROUH_OPEN_RELAY_KEY)"), and the others open all the same; the command then ends with 1.
When the parts end at different times (rouh.land granting fewer hours than asked), each line says its own end instead of the heading.
Times are on the Mac's own clock: "22:55 today", "09:00 tomorrow", "Thu 5 Nov 09:00".
`status` is the same block, read from the host (`rouh-grant summary`) and from each server itself; `close` is a block of the same lines, with rouh.land's report of any file that changed while the jobs were in under it.
Run on their own, `rouh-github-grant` and `rouh-proxy-grant` print one line a grant, in the same words.

## Rouh reads the grants itself

Everything the owner opens is in the keys volume on the host: `github_grant.json`, `keyproxy_grants.json` and, since 3 November 2026, `server_logins.json`, the record `rouh-open` keeps there of the servers' logins it opened (`rouh-grant login open NAME HOURS`, `login close NAME`; the prune deletes ended ones).
That last one is only a record: the servers themselves hold the keys and refuse them at their end.
Rouh's core mounts the keys volume, and `server_health` (a tool both a conversation and a job have) answers under `access` what is open and until when, on the person's clock, never the token (`_access_section` in `rouh/tools.py`).
So the owner never has to tell Rouh what they opened.

## The locale

On 3 November 2026 every call to the host printed `manpath: can't set the locale; make sure $LC_* and $LANG are correct`.
macOS's ssh sends `LANG` and `LC_*` to the server (`SendEnv LANG LC_*` in `/etc/ssh/ssh_config`), the host's sshd takes them (`AcceptEnv`), and a Mac's shell often has `LC_CTYPE=UTF-8`, a locale on macOS and no locale on Linux, so a program in admin's shell start on the host that calls `manpath` complained.
Every ssh and scp these commands make now runs without the Mac's `LANG` and `LC_*` (`ssh_clean`), so the server uses its own locale; `-o SendEnv=-LC_*` cannot do it, because the system's file adds them back after the command line.
Nothing needs changing on the Mac for these commands. For a plain `ssh` of your own to stop it too, put `export LANG=en_US.UTF-8 LC_CTYPE=en_US.UTF-8` in `~/.zshrc`.

## What the key proxy refuses without them, and why

The runs live in the worker container, on a network with no way out.
Their only way out is the key proxy (`guard/rouh_guard/keyproxy.py`), which adds the model keys on the way so that no run ever holds one.
For anything else it is a plain forward proxy, with two limits:

- **Ports.** It tunnels only to the ports in `ROUH_KEYPROXY_PORTS`, 80 and 443 unless the settings file says otherwise. So ssh (port 22) to any server is refused: "port 22 is not one the workers may reach".
- **Private addresses.** It never connects to a private, loopback or link-local address (the machine itself, the office network, other containers), so a run cannot walk into the network Rouh sits on. It looks a name up once and connects to the very address it checked, so a name cannot pass the check with one address and connect to another.

The one way past both is `ROUH_KEYPROXY_ALLOW` in the stack's settings file, `/srv/rouh-stack/.env` on the host: host:port pairs reached whatever the port and wherever the host is.
The proxy reads it once, when it starts, and the settings are also written into the resolved stack file, so changing it took root on the host, an edit of two files and a restart of the proxy (task 165, steps 165-03 and 165-05).
That is what stopped task 165 on 2 November 2026 (step 165-04): `ssh old-site` (203.0.113.40:22) and `ssh rouh-land` (203.0.113.20:22) were both refused at the proxy, while server-a, which the list had, went through.

GitHub had a different gap.
A run reaches GitHub over https, which is a sealed tunnel the proxy cannot read, so it could not add a token the way it adds the model keys, and the worker holds none of its own.

## How the two grants work

Both live in the keys volume the key proxy already reads (read-only), so no setting, stack file or restart changes.

- **GitHub.** `github_grant.json`: the token, its end (seconds since 1970) and the GitHub user it is. Until the end the proxy adds the token to every request a run sends to github.com, api.github.com, uploads.github.com, codeload.github.com and raw.githubusercontent.com, as a password for git and a bearer for the rest, and always takes off whatever credential the run sent. The run sends those requests to the proxy as plain http, and the proxy sends them on as https, so it can read them: git through `url.http://github.com/.insteadOf https://github.com/`, and gh over its own `http_unix_socket` setting, a socket in the worker's home that hands each connection to the proxy. `bin/rouh-github setup` sets both up in the worker (and fetches gh, its checksum checked). Every answer carries `X-Rouh-GitHub-Grant`: `open until ... as <user>`, `none` or `ended`. The token never reaches the worker, a log or an argument; only the core, which holds every key, could read the keys volume.
- **Everything else.** `keyproxy_grants.json`: each open grant with its kind (`all`, `ssh`, `servers`, `lan`, `name`, `pair`) and end, the servers' names and addresses from the list kept on the host (`/usr/local/lib/rouh-grant/servers`, which `install.sh` starts with the owner's servers and `servers add` and `remove` change), and what `lan` reaches, worked out on the host (`ip -j addr` and `docker network inspect`) and refreshed by the prune while a `lan` grant is open. The proxy reads it again whenever it changes, and a grant whose end has passed counts for nothing. A `servers` grant matches a server by the name the run connects to, or by its address, so `ssh server-a` (whose HostName is an address) is covered. The older `keyproxy_allow_timed` (one `host:port end` a line) is still read, and folded into the new file the next time it is written.

At its end a grant stops counting at once, in the proxy, with nobody doing anything.
`rouh-grant-prune.timer` on the host deletes ended grants from the keys volume every minute.

## The parts

| File | Where it runs | What it is |
|---|---|---|
| `mac/rouh-github-grant`, `mac/rouh-proxy-grant`, `mac/rouh-open` | the owner's Mac | the three commands (`rouh-open` is the other two together, and the owner's own servers); each calls `sudo -n /usr/local/sbin/rouh-grant` on the host over SSH (`ssh -p PORT admin@198.51.100.10`; `ROUH_HOST_SSH`, `ROUH_HOST_SSH_PORT`), the token on standard input |
| `host/rouh-grant` | the host, as root | writes, lists, revokes and prunes the two files in the keys volume, keeps the servers list, and gathers the record of what grants were used for (`docker volume inspect rouh_keys`); checks a token with GitHub before keeping it; logs to `/var/log/rouh-grant.log` without the token; `rouh-grant keyproxy` puts a key proxy that reads grants in place (below) |
| `host/install.sh` | the host, as root | `rouh-grant` into `/usr/local/sbin`, the servers list the first time, a sudo rule letting the installing user run it and nothing else without a password, the prune timer, and the key proxy |
| `servers/rouh-jobs-keys` | the relay (any `keyline` server) and the host, as root | sent by `rouh-open` on each open, status and close to the relay, and run by `rouh-grant jobs-key` on the host; keeps a jobs' key in root's keys, or one account's (`ROUH_JOBS_KEYS_USER`), with an end time, its 5-minute prune timer, and the report of files changed while it was in. On the Mac it is kept in `~/.local/share/rouh-grants` |
| `install-from-mac.sh` | the owner's Mac | both sides at once: the commands on the Mac (and every older copy on PATH), checked by version, then the helper copied to the host and `install.sh` run there with sudo |
| `../../bin/rouh-github` | the worker | `setup` (git and gh), `status`, and the socket gh talks over |

## This installation's values

Nothing in these commands names a machine: each installation's values are two files on the owner's Mac.

- `~/.config/rouh/grants.env` (or the file `ROUH_GRANTS_ENV` names), lines of `NAME=value`: `ROUH_HOST_SSH` (user@address of the machine the Rouh stack runs on), `ROUH_HOST_SSH_PORT` (22 if not given) and `ROUH_HOST_IDENTITY_FILE` (the one key to log in with). A value set in the shell wins over the file. `ROUH_MOZART_SSH`, `ROUH_MOZART_SSH_PORT` and `ROUH_MOZART_IDENTITY_FILE` are their older names and are still read.
- `~/.config/rouh/rouh-open.conf` (or `ROUH_OPEN_CONFIG`): rouh-open's servers, the table above, and `jobs-from`.

Until 7 November 2026 one installation's values were these commands' defaults.
The first `install-from-mac.sh` after that (which `rouh-open update` runs) writes them into the two files from the copies installed before, or from the shell, and never writes over either file after, so nothing the owner typed before stops working.
On the host, the servers' list (`/usr/local/lib/rouh-grant/servers`) starts empty and is filled with `rouh-proxy-grant servers add`.

## Installing

On the Mac, once, from a copy of this repository (`gh` signed in):

```bash
rm -rf ~/.rouh-grants && mkdir ~/.rouh-grants && gh api repos/rouh-it/rouh-core/tarball/main | tar -xz -C ~/.rouh-grants --strip-components=1
bash ~/.rouh-grants/deploy/grants/install-from-mac.sh
```

The second line asks for the host's key approval (and sudo's password, if admin's sudo wants one), and ends with "Done.".

After that, `rouh-proxy-grant update` (or `rouh-open update`) does both lines: it asks GitHub for main's commit, fetches that very commit into `~/.rouh-grants` (written in `.rouh-grants-commit`), and runs the installer.
The installer also replaces any older copy of the three commands it finds on PATH, then runs the `rouh-open` the shell finds and checks it says this version (`rouh-open --version`), and ends with "Done: rouh-open ..." only when it does; an older copy it cannot replace is named with the `sudo rm` that removes it.
On 3 November 2026 an update put the new `rouh-open` in place and the old one went on answering; that is what this check is for.
The installer changes nothing that is already right, keeps every open grant (they are in the keys volume, which it never touches), and puts a new key proxy in place only when the running one is not the one this helper carries.

Every ssh and scp the installer and the two commands make runs with `IdentitiesOnly=yes`, so only one key is offered, never every key in your agent.
Without it, a Mac whose agent holds several keys is turned away with "Too many authentication failures" before the approved one is tried, because the host allows only a few attempts.
By default the key is the one your `~/.ssh/config` names for the host (`IdentityFile` under a `Host 198.51.100.10` entry, or under the alias you give as `ROUH_HOST_SSH`).
If your config names none, or the wrong one, name it yourself, for the installer and for each command alike:

```bash
ROUH_HOST_IDENTITY_FILE=~/.ssh/host.pub bash ~/.rouh-grants/deploy/grants/install-from-mac.sh
export ROUH_HOST_IDENTITY_FILE=~/.ssh/host.pub   # in ~/.zshrc, for rouh-github-grant and rouh-proxy-grant
```

It is passed with `-i` to every ssh and scp, so the folder, the copy and the sudo install all log in with the same key.
It may be a private key file, or the public half (`.pub`) of a key an agent holds, such as Bitwarden's: ssh then asks the agent for that key and no other.
`ssh-add -L` lists the keys your agent holds; save the approved one's line to a `.pub` file to point at it.

### The key proxy itself

The key proxy runs from the protected core's image, which reaches a Rouh in a signed release (`.github/workflows/base.yml`), so a change to `keyproxy.py` on main is not running on the host until a release carries it and the host takes it (`linux_stack.py update`).
Until then, `rouh-grant keyproxy` (which `install.sh` runs when it is needed) builds the running key proxy's own image again with this `keyproxy.py` on top, points only the key proxy at it in `/srv/rouh-stack/stack/stack.json` (a copy kept beside it), and recreates only the key proxy; Rouh keeps running.
The next `linux_stack.py update` or `apply` writes the release's own image back. If that release does not read grants yet, the grants stop counting until `sudo rouh-grant keyproxy` is run again; `rouh-grant github status` and `list` say so whenever the running proxy does not read them. Which grants a proxy reads is the line `ROUH_GRANTS_FORMAT = 2` in `keyproxy.py`; `rouh-grant keyproxy` also puts its own copy in place again when a proxy it put there earlier is an older copy.

## Checking it from a run

```bash
/code/bin/rouh-github setup         # once per worker home
/code/bin/rouh-github status        # "GitHub grant open until ... as <user>; GitHub answered 200"
gh api user --jq .login             # the owner's GitHub user
git ls-remote https://github.com/rouh-it/rouh-core.git HEAD

ssh rouh-land true                  # while rouh-open is open (the proxy grant and rouh.land's own)
ssh relay true                      # the same, for the relay
ssh the host true                     # the same, for the host itself (a second name for it over a backup line, if it has one)
/opt/rouh-guard/bin/rouh-connect 10.0.0.1 22 </dev/null   # with no lan grant: "the key proxy refused 10.0.0.1:22"
```

The stack test holds both (`CONTAINERS.md`, `runs.github` and `runs.proxy-grant`: `all` on an unusual port and refused after its end and `revoke`, never a private address, a name's subdomains, several at once, `servers add`, `lan` without the containers, and the log).
