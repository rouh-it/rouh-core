# deploy/windows: Rouh on Windows

Task 186. `deploy/container/INSTALL-WINDOWS.md` is the whole account; this is where each part is.

| Part | Where | What |
|---|---|---|
| Rouh's own WSL Linux | `wsl/Dockerfile`, `wsl/files/` | Debian 13, Docker Engine, systemd, locked down; `rouh-wsl`, the helper the Windows side talks to |
| Its build | `wsl/build.sh` | `docker build` and `docker export` as a `.wsl` file, without the container's own files |
| Its check on Linux | `wsl/check-image.sh` | the file, then booted with systemd and Rouh installed in it from the live release |
| Its signed record | `wsl_image.py` | each file's SHA-256, signed with Rouh's release key; rouh.land serves it at `/windows/wsl/stable.json` |
| Built at GitHub | `../../.github/workflows/wsl-image.yml` | x64 and Arm; on main, released as `wsl-<version>` and signed (the release-signing environment's Approve) |
| The installer | rouh-it-site `rouhit/install/install.ps1` | `irm https://rouh.land/install.ps1 \| iex` |
| The tray app | `rouh-it/rouh-windows` | Tauri, `.msi`, carries the installer |
| The release check | `release-check/` | what a real Windows computer proves before rouh.land offers Windows |
