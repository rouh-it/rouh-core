# Rouh on Windows

How Rouh runs on a Windows computer, and how far that is proved.
Since 14 November 2026 (task 186, steps 186-03 to 186-06), on Petar's decision: "we build a and b".

**A preview.** Everything below is built, and tested as far as a computer that is not Windows, and GitHub's Windows machines, can test it.
GitHub's Windows machines cannot run WSL2 (they offer no nested virtualisation), and Rouh has no Windows test computer yet, so **nothing here has run on a real Windows computer**.
rouh.land does not offer Windows to anyone until the Windows release check (below) has passed on one.
"Proved" in this file means only what a check really did; everything else is said as not proved.

## How it works

Rouh is not built again for Windows.
Windows has a real Linux built in, WSL2 (the Windows Subsystem for Linux: a small Linux computer Windows runs out of sight), and Rouh runs inside it exactly as on a Linux server: the same containers, from the same signed release, set up by the same `https://rouh.land/install.sh`.
What is new is only the Windows wrapper around it, in three parts:

1. **Rouh's own WSL Linux**, a `.wsl` file (`deploy/windows/wsl/`): Debian 13 with Docker Engine (never Docker Desktop), systemd on, and `rouh-wsl`, the helper the Windows side talks to. Locked down: no Windows drive is mounted inside, nothing inside can start a Windows program, and the Linux user has no general sudo, only the commands Rouh's own `rouh` command runs with sudo on any Linux. Built at GitHub for x64 and Arm (`.github/workflows/wsl-image.yml`), and trusted only through rouh.land's record of it, signed with Rouh's release key, which names each file's SHA-256 (`deploy/windows/wsl_image.py`, `/windows/wsl/stable.json`).
2. **The thin installer**, `install.ps1`, served by rouh.land (rouh-it-site, `rouhit/install/install.ps1`):

   ```powershell
   irm https://rouh.land/install.ps1 | iex
   ```

   In this order, and it can be run again at any time:
   1. checks the computer: Windows 10 2004 (build 19041) or Windows 11, a 64-bit Intel, AMD or Arm processor, 2 cores, 8 GB of memory, 20 GB of free disk, virtualisation on;
   2. switches WSL2 on when it is not (`wsl --install --no-distribution`: an administrator's yes once, perhaps one restart), or updates a WSL older than 2.0;
   3. gets rouh.land's record of Rouh's Linux, checks its Ed25519 signature with Rouh's release key (written in the script; Windows has no openssl, so the check is RFC 8032's, in PowerShell), downloads the file for this processor and checks every byte against the SHA-256 the record names, then `wsl --import Rouh %LOCALAPPDATA%\Rouh\wsl <file> --version 2`;
   4. sets WSL up for a Linux that stays on, in `%USERPROFILE%\.wslconfig`: `[wsl2] memory=` half the computer's memory (4 to 16 GB), `vmIdleTimeout=-1`, `[general] instanceIdleTimeout=-1`. A setting the person already has is kept, and the file before is kept as `.wslconfig.before-rouh`. WSL is restarted for it only when none of the person's own Linux is running;
   5. keeps Rouh running from sign-in: a task in Task Scheduler, "Rouh keeps running", for this user, no administrator, that holds one process open in Rouh's Linux (`rouh-wsl keep-awake`) with no window (`conhost.exe --headless`). Rouh for Windows does this itself instead;
   6. starts Rouh: `rouh-wsl first-start`, which runs `https://rouh.land/install.sh --yes --no-setup` inside, as on any Linux server;
   7. opens setup in the browser: the one-time address `rouh-wsl link` gives (`http://127.0.0.1:8420/setup?code=...`), after checking that Rouh answers on 127.0.0.1 from Windows.

   It keeps itself as `%LOCALAPPDATA%\Rouh\rouh.ps1`, Rouh's command on Windows:

   ```powershell
   powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Rouh\rouh.ps1" <command>
   ```

   | Command | What it does |
   |---|---|
   | `install` (none) | Installs, or updates Rouh when it is installed |
   | `open` | A one-time sign-in address, opened in the browser |
   | `status` | Running or not, its release, set up or not, the task at sign-in |
   | `update` | `rouh update` inside: the newest signed release, going back by itself if unhealthy |
   | `back` | `rouh back` inside: the release before |
   | `compact` | Gives WSL's disk file back the space Rouh freed: trims inside, stops WSL, compacts with diskpart (an administrator's yes) |
   | `uninstall -Keep` | Keep my data: `rouh uninstall --keep` inside (the checked copy), then the whole Linux saved as `%LOCALAPPDATA%\Rouh\Kept\Rouh-kept-<time>.tar`, then removed. Installing again brings it back |
   | `uninstall -Wipe` | Wipe my data: removed for good, after typing WIPE (`-Yes` does not ask) |

   `$env:ROUH_DRY_RUN='1'` says every change it would make and makes none. Run with `irm ... | iex` it lives in a module of its own: it leaves the PowerShell window as it was, and never closes it.
3. **Rouh for Windows**, the tray app (`rouh-it/rouh-windows`, private for now): Tauri 2, an `.msi` for x64 and Arm built at GitHub. It carries the same `install.ps1` (its build refuses one that is not rouh.land's), starts at sign-in, holds Rouh's Linux awake itself, runs the installer in a window the first time, and has Open Rouh, Update, Back to the release before, Compact disk, Uninstall (Keep my data or Wipe my data) and Quit in its menu. Its builds are not signed until there is a signing account.

The release Windows follows is the one Linux follows, at the neutral address `https://rouh.land/release/<line>.json` (the same file as `/mac/release/<line>.json`, which every Mac keeps reading). `linux_stack.py` reads `/release/` and falls back to `/mac/release/` while rouh.land does not answer it.

## What is proved, and where

Every row names the check that ran and where; nothing here ran on a real Windows computer.

| What | Proved by | Result |
|---|---|---|
| Rouh's own WSL Linux builds for x64 and Arm | `wsl-image.yml` at GitHub, run 43578707235 (14 Nov 2026) | built; Debian 13.7, Docker 29.9.3, Compose 5.7.1, Python 3.13.5 |
| The `.wsl` file: its SHA-256, no container leftovers, `wsl.conf` (systemd on, no drives, no interop), the `rouh` user (uid 1000, docker group, no password), the sudo rule narrower than general sudo | `check-image.sh`, same run, both processors | passed |
| Booted with systemd as its first process: systemd up, Docker under systemd, Docker for `rouh`, `sudo -n true` refused, the one sudo command install.sh needs allowed | same run, both processors | passed |
| Rouh installed in it by `rouh-wsl first-start`: the live `https://rouh.land/install.sh`, the signed release (base 1.0.14) and signed code checked, the updater at the signed commit, every part healthy | same run, both processors | passed |
| `rouh-wsl state` (running, no owner yet), `http://127.0.0.1:8420/healthz` from outside the Linux, the setup address opening, the nightly timer on, `rouh update`, a restart of the Linux with Rouh back by itself | same run, both processors | passed |
| Keep my data, then Bring back: all seven volumes and the database's 243 tables identical (`rouh fingerprint`) | same run, both processors | passed |
| The installer's 23 tests, with a stand-in `wsl.exe`: install from empty, Arm, bad signature, wrong key, wrong file, old Windows, little memory, small disk, no virtualisation, WSL off and the restart, old WSL, the person's own `.wslconfig` kept, their running Linux not stopped, run again, Bring back, the tray app's way, no answer on 127.0.0.1, a failed first start, dry run, open, status, update, back, uninstall Keep (and a copy that does not check out), Wipe, compact, an unknown word, and `irm \| iex` leaving the window as it was | rouh-windows `windows-test.yml` on GitHub's Windows machine in Windows PowerShell 5.1 and PowerShell 7, and on Linux | 23 of 23 passed in each |
| The Ed25519 check in PowerShell: rouh.land's real release with the real key, RFC 8032's vectors, 12 random signatures, and each changed by a byte or a bit | PowerShell 7 on Linux (this run) | all good ones accepted, all changed ones refused |
| A record signed by `wsl_image.py` accepted by rouh.land's code and by `install.ps1`; tampered and misshapen records refused by rouh.land | the site's tests (114 passed, on the server too) and this run | passed |
| `install.ps1` lint for PowerShell 5.1 and 7 | PSScriptAnalyzer, on GitHub's Windows machine | no errors |
| The neutral release address: `/release/stable.json` the same bytes as `/mac/release/stable.json` on rouh.land; `linux_stack.py` falling back to `/mac/release/` while it was not served | live rouh.land, 14 Nov 2026, release 20261114T091841Z-186-04-windows | passed |
| Rouh for Windows' `.msi` for x64 and Arm builds; the x64 one installs, the app starts and still runs 20 seconds later (starting the installer's window, as on a first run), and uninstalls | rouh-windows `windows-build.yml`, run 43578752945 | passed |

## What only a real Windows computer can prove

Each is in the Windows release check (`deploy/windows/release-check/windows-release-check.ps1`), and each is unproved until it passes there:

- WSL2 switched on by the installer, the administrator's yes and the restart, on Windows 10 and 11.
- `wsl --import` of the `.wsl` file, and WSL starting systemd in it with `wsl.conf` as written (no drives, no interop).
- Docker Engine inside WSL's own kernel (Microsoft's kernel, not GitHub's), its iptables, and the worker's Landlock walls in that kernel.
- WSL's idle shut-down held off by the keep-awake process and `.wslconfig` (microsoft/WSL #13416); the `dbus-launch true` way OpenClaw uses is the one to try if it is not.
- `127.0.0.1:8420` inside WSL reached from Windows' browser (WSL's localhost forwarding), and the phone relay's held-open connection over WSL's network, overnight and across sleep and wake (186-02: NAT stalls, fixed elsewhere with TCP keepalive).
- Sleep and wake, a restart of Windows, Task Scheduler's task at sign-in, the tray app's Run key.
- Uninstall Keep and Bring back with `wsl --export` and `--import` of the kept Linux.
- `compact` with diskpart on a real WSL disk.
- An Arm (Snapdragon) laptop.
- The `.msi` on a computer with SmartScreen, unsigned (it warns) and later signed.

## Windows' own problems, and the answers in it

From 186-01 and 186-02 (how OpenClaw runs on Windows):

| Problem | The answer here |
|---|---|
| WSL stops a Linux nobody uses | A process held open from sign-in (task or tray app), and the idle timeouts off in `.wslconfig` |
| Docker Desktop's licence and its start only at sign-in | Docker Engine inside Rouh's own Linux, started by systemd |
| Windows drives seen from Linux are slow and lose permissions; a Linux that can start Windows programs is a way out | `wsl.conf`: no drives mounted, interop off; nothing of Rouh's on `C:` but the Linux's disk file |
| The disk file only grows | `rouh.ps1 compact` / Compact disk (not sparse: WSL calls that unsafe for the data) |
| Arm laptops | Images and the `.wsl` built for Arm from the first version |
| Administrator rights | Only to switch WSL on (once) and for diskpart's compact; everything else is per user |
| An unsigned installer meets SmartScreen | Signing step ready and switched off until there is a signing account (task 186) |
