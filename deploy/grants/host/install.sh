#!/usr/bin/env bash
# install.sh: the grants' side on the machine the Rouh stack runs on (the host). Run as root, from the
# folder that holds it, rouh-grant, rouh-jobs-keys and keyproxy.py (install-from-mac.sh copies them):
#
#   sudo bash install.sh
#
# What it does, and nothing else (deploy/grants/README.md):
#   1. rouh-grant into /usr/local/sbin (root's), and this checkout's keyproxy.py and rouh-jobs-keys
#      (the host's own login for the jobs, `rouh-grant jobs-key`) into /usr/local/lib/rouh-grant; the owner's servers' list there too,
#      the first time only, empty (rouh-proxy-grant servers add fills it), never written over after;
#   2. one sudo rule, /etc/sudoers.d/rouh-grant: the user who ran this may run rouh-grant, and
#      nothing else, without a password, so the commands on the Mac can call it over SSH. It is
#      checked with visudo before it is put in place;
#   3. rouh-grant-prune.timer: every minute, an ended grant is deleted from the keys volume;
#   4. if the running key proxy does not read this helper's grants yet, `rouh-grant keyproxy`: the
#      same key proxy with this keyproxy.py, only the key proxy recreated (a second or two; Rouh
#      keeps running).
# Running it again changes nothing that is already right. Open grants are kept: they are in the
# keys volume, which this never touches, and the new proxy reads the older list as well.
set -Eeuo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ "$(id -u)" = 0 ] || { echo "Run it with sudo: sudo bash $0"; exit 1; }
for f in rouh-grant rouh-jobs-keys keyproxy.py; do
  [ -f "$HERE/$f" ] || { echo "Not found beside this script: $f. Nothing was changed."; exit 1; }
done
grep -q '^ROUH_GRANTS_FORMAT = ' "$HERE/keyproxy.py" || { echo "keyproxy.py here does not read these grants. Nothing was changed."; exit 1; }
WHO=${SUDO_USER:-}
[ -n "$WHO" ] && [ "$WHO" != root ] || { echo "Run it with sudo from your own user, so the rule names you. Nothing was changed."; exit 1; }

# 1.
install -o root -g root -m 0755 "$HERE/rouh-grant" /usr/local/sbin/rouh-grant
install -d -o root -g root -m 0755 /usr/local/lib/rouh-grant
install -o root -g root -m 0644 "$HERE/keyproxy.py" /usr/local/lib/rouh-grant/keyproxy.py
install -o root -g root -m 0755 "$HERE/rouh-jobs-keys" /usr/local/lib/rouh-grant/rouh-jobs-keys
# A copy put in place by an earlier `jobs-key open` is brought up to this one too, so its timer
# runs the same prune.
[ ! -f /usr/local/sbin/rouh-jobs-keys ] || install -o root -g root -m 0755 "$HERE/rouh-jobs-keys" /usr/local/sbin/rouh-jobs-keys
if [ ! -f /usr/local/lib/rouh-grant/servers ]; then
  cat > /usr/local/lib/rouh-grant/servers <<'LIST'
# The owner's own servers, which `rouh-proxy-grant servers` opens: NAME [ADDRESS...] a line.
# Written by rouh-grant servers add / remove. A name with no address is looked up when opened.
LIST
  chmod 0644 /usr/local/lib/rouh-grant/servers
fi
install -d -o root -g root -m 0700 /var/lib/rouh-grant
touch /var/log/rouh-grant.log /var/log/rouh-grant-connections.log
chmod 0640 /var/log/rouh-grant.log /var/log/rouh-grant-connections.log
echo "1. rouh-grant is in /usr/local/sbin; your servers' list: $(grep -cv '^#' /usr/local/lib/rouh-grant/servers) servers."

# 2.
rule=$(mktemp)
printf '# Written by rouh-grant install.sh: %s may run rouh-grant as root, and nothing else, without a password.\n%s ALL=(root) NOPASSWD: /usr/local/sbin/rouh-grant\n' "$WHO" "$WHO" > "$rule"
if visudo -cqf "$rule"; then
  install -o root -g root -m 0440 "$rule" /etc/sudoers.d/rouh-grant
  echo "2. $WHO may run sudo rouh-grant without a password."
else
  echo "2. The sudo rule did not pass visudo; it was not put in place."
fi
rm -f "$rule"

# 3.
cat > /etc/systemd/system/rouh-grant-prune.service <<'UNIT'
[Unit]
Description=Delete the Rouh grants whose end has passed (rouh-grant prune)

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rouh-grant prune
UNIT
cat > /etc/systemd/system/rouh-grant-prune.timer <<'UNIT'
[Unit]
Description=Delete the Rouh grants whose end has passed, every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now rouh-grant-prune.timer >/dev/null
echo "3. rouh-grant-prune.timer: $(systemctl is-active rouh-grant-prune.timer)."

# 4.
if /usr/local/sbin/rouh-grant keyproxy --check >/dev/null 2>&1; then
  echo "4. The running key proxy reads these grants already."
else
  echo "4. Putting a key proxy that reads these grants in place:"
  /usr/local/sbin/rouh-grant keyproxy
fi
echo
echo "the host's part is in place."
