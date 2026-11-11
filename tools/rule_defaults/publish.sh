#!/usr/bin/env bash
# Publish the rules every Rouh starts with at https://rouh.land/rules/defaults.json, in one command
# (task 140, step 140-17). Until 11 November 2026 this was a manual step nobody took, and every Rouh born
# since 30 October 2026 had only the few rules of its fallback.
#
#   tools/rule_defaults/publish.sh                  export from the Rouh that sets them (its rules tagged
#                                                   "defaults"), then everything below
#   tools/rule_defaults/publish.sh --doc FILE       publish an export made already (manage.py rule_defaults export)
#   tools/rule_defaults/publish.sh --from-fallback  publish the rules this checkout's fallback holds
#   tools/rule_defaults/publish.sh --dry-run ...    everything but the push and the deploy
#
# What it does, in order:
#   1. the export: `manage.py rule_defaults export --user $ROUH_DEFAULTS_USER` (default 1) run where the
#      live database is: $ROUH_EXPORT_CMD if set, else `docker compose exec -T core ...` in $ROUH_STACK_DIR
#      (the stack's folder on the Creator Rouh's machine), else this checkout's manage.py;
#   2. `manage.py rule_defaults prepare`: refused whole if a rule holds a mail address that is not an example
#      one, an internet address, a home folder, a phone number, or a word of $ROUH_PRIVATE_WORDS (a file kept
#      outside the code, one word a line: the owner's people, accounts, machines and places); each rule's
#      version carried on from what rouh.land serves now; and rouh/rule_defaults_fallback.json written to hold
#      the same rules;
#   3. the site: rouh-it/rouh-it-site cloned, rouhit/rules/defaults.json replaced, committed, pushed to main
#      and deployed with the site's deploy.sh (its tests first; the release before kept for undo);
#   4. the live address read back as every Rouh reads it (`manage.py rule_defaults read`): 200, JSON, the
#      revision just published.
# Then commit rouh/rule_defaults_fallback.json here and land it, so a new Rouh's code starts with the same.
#
# Needs a GitHub grant (rouh-it/rouh-it-site) and the rouh.land login (`ssh rouh-land`, with sudo).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/../.." && pwd)
URL=${ROUH_RULE_DEFAULTS_URL:-https://rouh.land/rules/defaults.json}
SITE_REPO=${ROUH_SITE_REPO:-https://github.com/rouh-it/rouh-it-site.git}
WORDS=${ROUH_PRIVATE_WORDS:-$HOME/.config/rouh/private-words.txt}
PY=${ROUH_PYTHON:-}
if [ -z "$PY" ]; then
  if [ -x "$HERE/.venv-e2e/bin/python" ]; then PY=$HERE/.venv-e2e/bin/python; else PY=python3; fi
fi
DOC=""; FROM_FALLBACK=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --doc) DOC=$(readlink -f "$2"); shift 2 ;;
    --from-fallback) FROM_FALLBACK=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
manage() { (cd "$HERE" && "$PY" manage.py rule_defaults "$@"); }

# 1. The export.
if [ "$FROM_FALLBACK" = 1 ]; then
  cp "$HERE/rouh/rule_defaults_fallback.json" "$WORK/export.json"
elif [ -n "$DOC" ]; then
  cp "$DOC" "$WORK/export.json"
elif [ -n "${ROUH_EXPORT_CMD:-}" ]; then
  bash -c "$ROUH_EXPORT_CMD" > "$WORK/export.json"
elif [ -n "${ROUH_STACK_DIR:-}" ]; then
  (cd "$ROUH_STACK_DIR" && docker compose exec -T core python manage.py rule_defaults export \
     --user "${ROUH_DEFAULTS_USER:-1}") > "$WORK/export.json"
else
  manage export --user "${ROUH_DEFAULTS_USER:-1}" > "$WORK/export.json"
fi

# 2. Ready to publish, and the fallback in step with it.
code=$(curl -s -o "$WORK/live.json" -w '%{http_code}' "$URL?schema=1" || true)
[ "$code" = 200 ] || : > "$WORK/live.json"
args=(--doc "$WORK/export.json" --published "$WORK/live.json" --out "$WORK/ready.json"
      --fallback "$HERE/rouh/rule_defaults_fallback.json")
[ -f "$WORDS" ] && args+=(--words "$WORDS")
manage prepare "${args[@]}"
REV=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$WORK/ready.json")

# 3. The site.
if [ "$code" = 200 ] && cmp -s <("$PY" -m json.tool --sort-keys "$WORK/live.json") \
                               <("$PY" -m json.tool --sort-keys "$WORK/ready.json"); then
  echo "rouh.land already serves revision $REV: nothing to deploy"
elif [ "$DRY" = 1 ]; then
  echo "dry run: would publish revision $REV ($WORK/ready.json is removed on exit)"
  exit 0
else
  git clone -q "$SITE_REPO" "$WORK/site"
  mkdir -p "$WORK/site/rouhit/rules"
  cp "$WORK/ready.json" "$WORK/site/rouhit/rules/defaults.json"
  git -C "$WORK/site" add rouhit/rules/defaults.json
  git -C "$WORK/site" -c user.name="${GIT_AUTHOR_NAME:-Rouh}" -c user.email="${GIT_AUTHOR_EMAIL:-rouh@rouh.land}" \
    commit -q -m "The rules every Rouh starts with: revision $REV (published by rouh-core's tools/rule_defaults/publish.sh)"
  git -C "$WORK/site" push -q origin HEAD:main
  "$WORK/site/deploy.sh" "rules-$REV"
fi

# 4. Read back as every Rouh reads it.
for i in 1 2 3 4 5 6; do
  got=$(manage read --url "$URL" 2>&1) && break
  sleep 5
done
echo "$got"
echo "$got" | grep -q "\"revision\": \"$REV\"" || { echo "rouh.land does not serve revision $REV"; exit 5; }
git -C "$HERE" diff --quiet -- rouh/rule_defaults_fallback.json \
  || echo "rouh/rule_defaults_fallback.json changed: commit it and land it, so a new Rouh starts with the same rules"
echo "published: $URL serves revision $REV"
