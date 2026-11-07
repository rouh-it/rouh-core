#!/usr/bin/env bash
# install-from-mac.sh: put the two grant commands on this Mac and their helper on the host. Run it
# on the Mac, from a copy of rouh-core (deploy/grants/README.md says how to get one):
#
#   bash deploy/grants/install-from-mac.sh
#
# 1. rouh-github-grant, rouh-proxy-grant and rouh-open into the first of /opt/homebrew/bin,
#    /usr/local/bin, ~/.local/bin that this user can write, and rouh-jobs-keys (what rouh-open
#    sends to the relay and runs there as root) into ~/.local/share/rouh-grants;
# 2. rouh-grant, its install.sh, rouh-jobs-keys and the key proxy that reads grants copied to the host (scp), and
#    install.sh run there with sudo (ssh -t, so sudo can ask your password if it wants it).
# Run it again whenever these change (rouh-proxy-grant update does, after fetching the latest):
# it changes nothing that is already right, and keeps every grant that is open.
# Settings, in ~/.config/rouh/grants.env (written the first time from the commands installed before,
# or from the shell): ROUH_HOST_SSH (user@address of the machine the stack runs on), ROUH_HOST_SSH_PORT
# (22), and ROUH_HOST_IDENTITY_FILE (none): the one key to log in with, a private key file or the .pub of a
# key your agent holds. Every ssh and scp here runs with IdentitiesOnly=yes, so only the key your
# ~/.ssh/config names for the host (or this file) is offered, never every key in the agent, which
# made the host close with "Too many authentication failures" before the right one was tried.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# The Mac's LANG and LC_* are never sent to the host (rouh-open says why).
ssh_clean() {
  local v u=()
  for v in $(compgen -e); do case "$v" in LANG|LANGUAGE|LC_*) u+=(-u "$v") ;; esac; done
  env "${u[@]}" "$@"
}
ROOT=$(cd "$HERE/../.." && pwd)
# This installation's values were defaults in these commands until 7 November 2026. The first
# install after that writes them into the two settings files, from the copies installed before or
# from the shell, so nothing the owner typed before stops working; nothing is written over after.
ENV_FILE=${ROUH_GRANTS_ENV:-$HOME/.config/rouh/grants.env}
OPEN_CONF=${ROUH_OPEN_CONFIG:-$HOME/.config/rouh/rouh-open.conf}
seed_settings() {
  local old h p k table
  mkdir -p "$(dirname "$ENV_FILE")" "$(dirname "$OPEN_CONF")"
  if [ ! -f "$ENV_FILE" ]; then
    h=${ROUH_HOST_SSH:-${ROUH_MOZART_SSH:-}}; p=${ROUH_HOST_SSH_PORT:-${ROUH_MOZART_SSH_PORT:-}}
    k=${ROUH_HOST_IDENTITY_FILE:-${ROUH_MOZART_IDENTITY_FILE:-}}
    old=$(command -v rouh-proxy-grant 2>/dev/null || true)
    if [ -n "$old" ] && [ -f "$old" ]; then
      [ -n "$h" ] || h=$(sed -n 's/^HOST=\${ROUH_MOZART_SSH:-\(.*\)}$/\1/p' "$old" | head -1)
      [ -n "$p" ] || p=$(sed -n 's/^PORT=\${ROUH_MOZART_SSH_PORT:-\(.*\)}$/\1/p' "$old" | head -1)
    fi
    if [ -n "$h" ]; then
      { echo "# This installation's grants settings (deploy/grants/README.md), written by install-from-mac.sh"
        echo "ROUH_HOST_SSH=$h"; echo "ROUH_HOST_SSH_PORT=${p:-22}"
        [ -z "$k" ] || echo "ROUH_HOST_IDENTITY_FILE=$k"; } > "$ENV_FILE"
      chmod 600 "$ENV_FILE"; echo "0. This installation's values written to $ENV_FILE (from the commands installed before)."
    fi
  fi
  if ! grep -q '^# seeded by install-from-mac.sh' "$OPEN_CONF" 2>/dev/null; then
    old=$(command -v rouh-open 2>/dev/null || true); table=""
    [ -z "$old" ] || [ ! -f "$old" ] || table=$(awk "/^DEFAULTS='\$/{f=1;next} f&&/^'/{exit} f" "$old")
    if [ -n "$(printf '%s' "$table" | tr -d '[:space:]')" ]; then
      { echo "# seeded by install-from-mac.sh: the servers rouh-open had as defaults until 7 November 2026"
        printf '%s\n' "$table"
        [ ! -f "$OPEN_CONF" ] || { echo "# what this file held before"; cat "$OPEN_CONF"; }; } > "$OPEN_CONF.new"
      chmod 600 "$OPEN_CONF.new"; mv "$OPEN_CONF.new" "$OPEN_CONF"
      echo "0. rouh-open's servers written to $OPEN_CONF (from the rouh-open installed before)."
    fi
  fi
}
seed_settings
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ROUH_[A-Z0-9_]*) [ -n "${!k:-}" ] || export "$k=$v" ;; esac
  done < <(grep -E '^ROUH_[A-Z0-9_]+=' "$ENV_FILE")
fi
HOST=${ROUH_HOST_SSH:-${ROUH_MOZART_SSH:-}}
PORT=${ROUH_HOST_SSH_PORT:-${ROUH_MOZART_SSH_PORT:-22}}
[ -n "$HOST" ] || { echo "Which machine runs the Rouh stack? Put ROUH_HOST_SSH=user@address (and ROUH_HOST_SSH_PORT) in $ENV_FILE, then run this again."; exit 1; }
SSH_OPTS=(-o IdentitiesOnly=yes)
KEY=${ROUH_HOST_IDENTITY_FILE:-${ROUH_MOZART_IDENTITY_FILE:-}}
if [ -n "$KEY" ]; then
  # shellcheck disable=SC2088  # a ~/ written in the setting, made whole here
  case "$KEY" in "~/"*) KEY=$HOME/${KEY#"~/"} ;; esac
  [ -f "$KEY" ] && [ -r "$KEY" ] || { echo "ROUH_HOST_IDENTITY_FILE is not a readable file: $KEY"; exit 1; }
  SSH_OPTS+=(-i "$KEY")
fi

for f in "$HERE/mac/rouh-github-grant" "$HERE/mac/rouh-proxy-grant" "$HERE/mac/rouh-open" "$HERE/servers/rouh-jobs-keys" "$HERE/host/rouh-grant" \
         "$HERE/host/install.sh" "$ROOT/guard/rouh_guard/keyproxy.py"; do
  [ -f "$f" ] || { echo "Not found: $f. Run this from a whole copy of rouh-core."; exit 1; }
done

bin=""
for d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
  if [ -d "$d" ] && [ -w "$d" ]; then bin=$d; break; fi
done
[ -n "$bin" ] || { mkdir -p "$HOME/.local/bin"; bin=$HOME/.local/bin; }
install -m 0755 "$HERE/mac/rouh-github-grant" "$bin/rouh-github-grant"
install -m 0755 "$HERE/mac/rouh-proxy-grant" "$bin/rouh-proxy-grant"
install -m 0755 "$HERE/mac/rouh-open" "$bin/rouh-open"
share=$HOME/.local/share/rouh-grants
mkdir -p "$share" && install -m 0644 "$HERE/servers/rouh-jobs-keys" "$share/rouh-jobs-keys"
# Any other copy of the three on PATH is one of ours from an earlier install, and the shell may
# find it first: on 3 November 2026 an update put the new rouh-open in place and the old one
# went on answering. So every older copy is replaced too, and the one the shell finds is checked.
stale=()
for name in rouh-github-grant rouh-proxy-grant rouh-open; do
  while IFS= read -r other; do
    if [ -z "$other" ] || [ ! -f "$other" ] || [ "$other" -ef "$bin/$name" ]; then continue; fi
    grep -q "^# $name:" "$other" 2>/dev/null || continue
    if [ -w "$other" ] && [ -w "$(dirname "$other")" ]; then
      install -m 0755 "$HERE/mac/$name" "$other"; echo "Replaced an older copy: $other"
    else
      stale+=("$other")
    fi
  done < <(type -ap "$name" 2>/dev/null)
done
want="rouh-open $(sed -n 's/^ROUH_OPEN_VERSION=//p' "$HERE/mac/rouh-open")"
commit=$(cat "$ROOT/.rouh-grants-commit" 2>/dev/null || true)
found=$(command -v rouh-open 2>/dev/null || true)
got=$([ -n "$found" ] && "$found" --version 2>/dev/null || true)
echo "On this Mac: rouh-open, rouh-github-grant and rouh-proxy-grant in $bin${commit:+ (rouh-core ${commit:0:8})}."
mac_ok=yes
if [ ${#stale[@]} -gt 0 ]; then
  mac_ok=""
  echo "Older copies this user cannot replace, which your shell may run instead. Remove them:"
  for f in "${stale[@]}"; do echo "  sudo rm '$f'"; done
fi
if [ -z "$found" ]; then
  mac_ok=""
  echo "$bin is not on your PATH, so the shell finds no rouh-open. Add it to ~/.zshrc:"
  echo "  export PATH=\"$bin:\$PATH\""
elif [ "$got" != "$want" ]; then
  mac_ok=""
  echo "The rouh-open your shell runs ($found) says \"${got:-nothing}\", not \"$want\"."
else
  echo "Checked: rouh-open is $found and says \"$got\". (In a shell already open, run: hash -r)"
fi

dir=/tmp/rouh-grants-$$
echo "To the host ($HOST, port $PORT, key: ${KEY:-the one ~/.ssh/config names for it}):"
ssh_clean ssh "${SSH_OPTS[@]}" -p "$PORT" "$HOST" "mkdir -m 700 '$dir'" || {
  echo "Could not log in to the host with only that key. If ~/.ssh/config does not name the approved key for"
  echo "$HOST, run this again with ROUH_HOST_IDENTITY_FILE set to it (deploy/grants/README.md, Installing)."
  exit 1
}
ssh_clean scp -q "${SSH_OPTS[@]}" -P "$PORT" "$HERE/host/rouh-grant" "$HERE/host/install.sh" "$HERE/servers/rouh-jobs-keys" \
  "$ROOT/guard/rouh_guard/keyproxy.py" "$HOST:$dir/"
ssh_clean ssh -t "${SSH_OPTS[@]}" -p "$PORT" "$HOST" "sudo bash '$dir/install.sh'; status=\$?; rm -rf '$dir'; exit \$status" \
  || { echo "the host's part did not finish (above). This Mac's part is in place."; exit 1; }
[ -n "$mac_ok" ] || { echo "Not finished on this Mac: see above."; exit 1; }
echo "Done: $want on this Mac, and the host's part."
