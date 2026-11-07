#!/usr/bin/env bash
#
# Put the one program on this machine, or bring it up to date. Run as root.
# Safe to run again: every step checks before it changes anything.
#
#   bash /srv/one/app/one/deploy/install.sh            everything
#   bash /srv/one/app/one/deploy/install.sh --update   new code and restart only
#
# What it sets up, and why each is separate from Rouh:
#   user one            the program runs as this user, never as root
#   /srv/one/app        its own checkout of the repository (ONE_REPO), so a
#                       Rouh deploy never changes the running program
#   /srv/one/venv       its own Python packages
#   /var/lib/one        the list, each run's terminal log, the views' position
#   /srv/one-runs       each run's checkout, owned by the assistant user
#   /srv/spaces         every repository added as a space, owned by assistant
#   /etc/sudoers.d/one  the one command the program may run as assistant
#   /etc/sudoers.d/assistant
#                       every run works as assistant, which may use sudo (D42)
#   the assistant user  a git name for every run's commits, and the server's
#                       own GitHub key first in its ssh settings
#   one.service         the service, with a watchdog and a processor limit
#
# The rollback for a code update is printed at the end. Runs are not stopped
# by any of this: only the program restarts, and it reconnects to them.
set -euo pipefail

# bash reads a script while it runs it, and this one resets its own
# checkout: on 14 September a deploy ran half the old script and half of
# whatever the new file held at the same place. So it runs from a copy,
# and once the code has moved it starts again from the new version.
if [ -z "${ONE_INSTALL_COPY:-}" ]; then
  copy="$(mktemp /tmp/one-install.XXXXXX)"
  cp "$0" "$copy"
  ONE_INSTALL_COPY="$copy" exec bash "$copy" "$@"
fi
trap 'rm -f "$ONE_INSTALL_COPY"' EXIT

APP=/srv/one/app
VENV=/srv/one/venv
REPO=${ONE_REPO:-git@github.com:rouh-it/rouh-core.git}
UPDATE=0
[ "${1:-}" = "--update" ] && UPDATE=1

say() { echo "==> $*"; }

BEFORE=""
if [ -d "$APP/.git" ]; then
  BEFORE=$(git -C "$APP" rev-parse HEAD)
fi

if [ "$UPDATE" = 0 ]; then
  say "the user"
  id one >/dev/null 2>&1 || useradd --system --home-dir /var/lib/one --shell /usr/sbin/nologin one
  install -d -o one -g one -m 0750 /var/lib/one /var/log/one
  install -d -o assistant -g assistant -m 0755 /srv/one-runs /srv/one-runs/scratch
  install -d -o root -g one -m 0750 /etc/one
  install -d -o root -g root -m 0755 /srv/one
fi

say "the code"
if [ ! -d "$APP/.git" ]; then
  git clone -q "$REPO" "$APP"
fi
git -C "$APP" fetch -q origin
git -C "$APP" reset -q --hard origin/main
chown -R root:root "$APP"
chmod -R go-w "$APP"
AFTER=$(git -C "$APP" rev-parse HEAD)
if [ -z "${ONE_INSTALL_BEFORE:-}" ] && [ -n "$BEFORE" ] && [ "$BEFORE" != "$AFTER" ]; then
  copy="$(mktemp /tmp/one-install.XXXXXX)"
  cp "$APP/one/deploy/install.sh" "$copy"
  rm -f "$ONE_INSTALL_COPY"
  ONE_INSTALL_COPY="$copy" ONE_INSTALL_BEFORE="$BEFORE" exec bash "$copy" "$@"
fi
if [ -n "${ONE_INSTALL_BEFORE:-}" ]; then BEFORE="$ONE_INSTALL_BEFORE"; fi

say "the packages"
if [ ! -x "$VENV/bin/python" ]; then
  /usr/bin/python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP/one/requirements.txt"
"$VENV/bin/python" -m compileall -q "$APP/one" "$APP/rouh/tree.py" "$APP/rouh/worklabel.py" || true

say "checking the code imports before anything restarts"
(cd "$APP" && "$VENV/bin/python" -c "import one.program, one.cli, one.holder")
/usr/bin/python3 -I "$APP/one/asuser.py" --help >/dev/null

say "sudo"
# On an update too: the rules changed when every run became the assistant (D42).
install -m 0440 -o root -g root "$APP/one/deploy/sudoers" /etc/sudoers.d/one.new
visudo -cqf /etc/sudoers.d/one.new
mv /etc/sudoers.d/one.new /etc/sudoers.d/one
install -m 0440 -o root -g root "$APP/one/deploy/sudoers-assistant" /etc/sudoers.d/assistant.new
visudo -cqf /etc/sudoers.d/assistant.new
mv /etc/sudoers.d/assistant.new /etc/sudoers.d/assistant

say "spaces, and the assistant user's way to GitHub (D42)"
install -d -o assistant -g assistant -m 0755 /srv/spaces
# Folders added by a project's name are made here (D44), the same path as the
# person's projects on their Mac; the folders above it stay root's.
FOLDERS=$(sed -n 's/^Environment=ONE_FOLDERS_DIR=//p' "$APP/one/deploy/one.service")
if [ -n "$FOLDERS" ]; then
  mkdir -p "$FOLDERS"
  chown assistant:assistant "$FOLDERS"
  chmod 0755 "$FOLDERS"
fi
# Runs reach GitHub with the server's own key on the person's account, tried
# before the workspace's deploy key. The key is made once, by hand:
#   sudo -u assistant ssh-keygen -t ed25519 -N "" -C one-program@server -f ~assistant/.ssh/github_one
# and its public half added at https://github.com/settings/ssh/new.
CFG=/home/assistant/.ssh/config
if [ -f /home/assistant/.ssh/github_one ] && ! grep -q github_one "$CFG" 2>/dev/null; then
  python3 - "$CFG" <<'PY'
import sys

path = sys.argv[1]
try:
    lines = open(path).read().splitlines()
except FileNotFoundError:
    lines = []
out, done = [], False
for line in lines:
    out.append(line)
    if not done and line.strip().lower() == "host github.com":
        out.append("  IdentityFile ~/.ssh/github_one")
        done = True
if not done:
    out += ["Host github.com", "  User git", "  IdentityFile ~/.ssh/github_one", "  IdentitiesOnly yes"]
with open(path, "w") as fh:
    fh.write("\n".join(out) + "\n")
PY
  chown assistant:assistant "$CFG"
  chmod 600 "$CFG"
fi
# Every run's commits carry this checkout's name, which is the person's.
if [ -z "$(sudo -u assistant -H git config --global --get user.name || true)" ]; then
  sudo -u assistant -H git config --global user.name \
    "$(git -C "$APP" config --get user.name)"
  sudo -u assistant -H git config --global user.email \
    "$(git -C "$APP" config --get user.email)"
fi

say "the service and the command"
install -m 0644 "$APP/one/deploy/one.service" /etc/systemd/system/one.service
install -m 0755 "$APP/one/deploy/one-cli" /usr/local/bin/one
# The two units of the separate workspace, kept off.
#
# It was a repository of its own at /srv/assistant, with an Ask AI page server
# beside it (`assistant-askai`, 127.0.0.1:1111) and a timer that ran its
# `bin/sync` against GitHub every thirty seconds (`assistant-sync`). The
# workspace is `workspace/` in this repository now: Rouh serves its pages
# itself at `/workspace/` with the Ask AI drawer on them, work reaches it
# through `land.sh` and the deploy, and nothing reads that folder at all. It is
# archived and moved aside to /srv/assistant.retired, and `workspace/README.md`
# says how to bring it back.
#
# Turned off here rather than only by hand, so that a machine this script is run
# on again does not quietly bring either of them back - which is the failure
# this block exists to stop, and which is easy to cause, because neither unit
# file is in this repository. They are left where they are, so enabling one is
# the whole of putting it back.
#
# assistant-sync is the one that matters most. It moves a git checkout and
# pushes to GitHub, so a copy of it coming back up against a folder that is not
# there any more, or worse against a folder somebody restored, is a background
# process changing a repository nobody is watching.
for unit in assistant-askai.service assistant-sync.timer assistant-sync.service; do
  if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
    systemctl disable -q --now "$unit" 2>/dev/null || true
  fi
done
systemctl daemon-reload
systemctl enable -q one
systemctl restart one

say "health"
for i in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:8031/one/healthz 2>/dev/null; then echo; break; fi
  sleep 1
done
systemctl is-active one


echo
if [ -n "$BEFORE" ] && [ "$BEFORE" != "$AFTER" ]; then
  echo "rollback: git -C $APP reset -q --hard $BEFORE && systemctl restart one"
fi
