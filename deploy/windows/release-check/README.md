# The Windows release check

`windows-release-check.ps1` is what a real Windows 11 computer proves before rouh.land offers Rouh to Windows, and again for each release (task 186, step 186-06).
GitHub's Windows machines cannot run WSL2, so it runs on Rouh's own Windows test computer: by hand, or as the self-hosted runner of `.github/workflows/windows-release-check.yml`, which writes each result to the branch `windows-checks`.
There is no such computer yet; buying one is Petar's decision (task 186's page has the recommendation).

## What it checks

1. **From empty:** install.ps1 as a person runs it, then from Windows: the Linux is WSL 2, no Windows drive inside, no Windows program runs from inside, no general sudo, systemd and Docker up, `.wslconfig`, the task at sign-in, `http://127.0.0.1:8420` answering in Windows, no owner yet, the setup address opening, Landlock in WSL's kernel, the worker running as a user, the nightly timer.
2. **Left alone** for 15 minutes (`-IdleMinutes`): still answering.
3. **Update**, and **Back** when there is a release before.
4. **Sleep and wake** (`-Sleep`): suspended for two minutes, woken by a timer, answering again within two minutes.
5. **Keep my data**, then install again: the same Rouh (`rouh fingerprint` before and after).
6. **Wipe my data**: nothing of Rouh's left (`-KeepAfter` skips it).

A person adds, on the same computer, what a script cannot: a restart of Windows (Rouh answers after sign-in with nothing pressed), Rouh for Windows' `.msi` (SmartScreen, the tray icon, its menu, Quit and start again), and a real phone through the relay after an overnight idle.

## The test computer

Rouh's recommendation, as of 14 November 2026 (to be priced when it is bought):

- **A small Windows 11 Pro PC**, about 400 to 600 euros: an Intel or AMD processor with virtualisation (VT-x or AMD-V) in its firmware, 4 cores or more, **16 GB of memory** (Rouh's Linux takes half), **a 512 GB SSD**, wired Ethernet, and a firmware setting to power on after a power cut. Windows 11 Pro rather than Home only for Remote Desktop, so a job can be watched; WSL2 runs on both.
- It stays on, signed in to a local account made for it, and runs GitHub's self-hosted runner as a service with the labels `self-hosted, windows, wsl2` (Settings, Actions, Runners, New self-hosted runner, in rouh-it/rouh-core).
- **Later, for Arm:** a Snapdragon X laptop, or a cloud Arm Windows machine by the hour, before Arm is called supported.
- **Instead, by the hour:** a cloud Windows 11 machine that allows nested virtualisation (for example Azure's Dv5 or Ev5 sizes) works for one check at a time, but sleep and wake cannot be tested on it, and it costs every time it is used.
