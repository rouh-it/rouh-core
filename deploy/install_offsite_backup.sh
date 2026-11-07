#!/bin/bash
# Install Rouh's weekly backup to R2 (deploy/backup_offsite.py), as root.
# Makes the gpg passphrase once (never replaced: old copies need it), writes the
# service from its template with this installation's own paths, installs it and
# the timer, and starts the timer. Run again after either unit changes.
#
# The paths are the installation's settings, read the way deploy/rouh.sh reads
# them (deploy/installation.env.example lists them):
#
#   ROUH_APP_DIR   Rouh's checkout, whose deploy/backup_offsite.py the timer runs
#   ROUH_VENV      the Python environment it runs with
#
# and any of ROUH_DATA_DIR, ROUH_BACKUP_KEYS, ROUH_BACKUP_PASSPHRASE,
# ROUH_BACKUP_DUMPS and ROUH_BACKUP_WORK that is set is written into the
# service, so the backup reads the same values every Sunday.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
here="$(cd "$(dirname "$0")" && pwd)"

# Every setting is read as ROUH_<name> and then as the JARVIS_<name> it was
# called before the rename, the same way deploy/rouh.sh reads them.
setting() {                       # setting NAME DEFAULT
  local new="$1" old="JARVIS_${1#ROUH_}" said
  said="${!new:-}"
  [ -n "$said" ] || said="${!old:-}"
  printf '%s' "${said:-$2}"
}
app="$(setting ROUH_APP_DIR /var/www/rouh/app)"
venv="$(setting ROUH_VENV /var/www/rouh/.venv)"
keys="$(setting ROUH_BACKUP_KEYS /etc/rouh/r2-backup.json)"
passphrase="$(setting ROUH_BACKUP_PASSPHRASE /etc/rouh/backup-passphrase)"
[ -f "$app/deploy/backup_offsite.py" ] || { echo "no $app/deploy/backup_offsite.py: set ROUH_APP_DIR to Rouh's checkout"; exit 1; }
[ -x "$venv/bin/python" ] || { echo "no $venv/bin/python: set ROUH_VENV to Rouh's Python environment"; exit 1; }

[ -s "$keys" ] || { echo "no $keys: the R2 endpoint, bucket and key go there"; exit 1; }
if [ ! -s "$passphrase" ]; then
  umask 077
  mkdir -p "$(dirname "$passphrase")"
  head -c 36 /dev/urandom | base64 | tr -d '\n' > "$passphrase"
  echo "made $passphrase: keep a copy of it off this machine"
fi
chmod 600 "$passphrase" "$keys"

# Only what is set, so an installation on the defaults gets a service with no
# Environment= line at all.
environment=""
for name in ROUH_DATA_DIR ROUH_BACKUP_KEYS ROUH_BACKUP_PASSPHRASE ROUH_BACKUP_DUMPS ROUH_BACKUP_WORK; do
  [ -n "${!name:-}" ] && environment+="Environment=\"$name=${!name}\""$'\n'
done
unit="$(mktemp)"
trap 'rm -f "$unit"' EXIT
APP="$app" VENV="$venv" ENVIRONMENT="${environment%$'\n'}" "$venv/bin/python" - "$here/rouh-offsite-backup.service" >"$unit" <<'PY'
import os, sys
text = open(sys.argv[1]).read()
text = text.replace("@ROUH_APP_DIR@", os.environ["APP"]).replace("@ROUH_VENV@", os.environ["VENV"])
env = os.environ["ENVIRONMENT"]
text = text.replace("@ENVIRONMENT@\n", env + "\n" if env else "")
sys.stdout.write(text)
PY
install -m 644 "$unit" /etc/systemd/system/rouh-offsite-backup.service
install -m 644 "$here/rouh-offsite-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rouh-offsite-backup.timer
systemctl list-timers rouh-offsite-backup.timer --no-pager
