#!/bin/bash
#
# The stack test: the real stack (deploy/stack/compose.yml), on images built from this checkout,
# with this checkout as the Rouh's own code, every outside service a stand-in, and then every
# feature in CONTAINERS.md that the containers are said to carry, checked from outside as the
# person would use it (tests/stack/smoke.py). Petar, 29 October 2026: every feature the Creator
# Rouh has must work in the containers every Rouh instance runs, and a change that breaks one
# must fail.
#
#   tests/stack/run.sh [--base IMAGE --guard IMAGE] [--keep] [--only ID,ID] [--out DIR] [--record]
#
# --record writes the result down on the branch stack-checks, results/<commit>.json, as the
# workflow does, saying which machine and architecture it ran on, so land.sh can read a run made
# here when GitHub cannot make one (land.sh, stack_guard). Only for a whole run of a clean checkout.
#
# Without --base and --guard it builds both from this checkout first (Docker with buildx). It
# needs Docker with Compose, Python 3.12 and, for the smoke test, a Python with Playwright's
# Chromium (tests/stack/requirements.txt). .github/workflows/stack-tests.yml runs it on Intel
# and on Arm for every push to main and for every branch land.sh hands it (land.sh, stack_guard).
#
# It prints a line per check and, last, "STACK-TEST {json}"; it exits 0 only when every feature
# CONTAINERS.md says works passed. Everything it made is taken down again unless --keep.
set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$repo/tests/stack"
base="" guard="" keep="" only="" record="" out="${STACK_TEST_OUT:-$repo/.stack-test}"
postgres="${ROUH_POSTGRES_IMAGE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="$2"; shift 2 ;;
    --guard) guard="$2"; shift 2 ;;
    --postgres) postgres="$2"; shift 2 ;;
    --keep) keep=1; shift ;;
    --record) record=1; shift ;;
    --only) only="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    *) echo "run.sh: unknown option $1" >&2; exit 2 ;;
  esac
done

say() { echo "stack-test: $*"; }
mkdir -p "$out"
out="$(cd "$out" && pwd)"
# Its own name and ports, so several can run side by side on one Docker.
project="${STACK_TEST_PROJECT:-rouh-stack-test}"
port="${STACK_TEST_PORT:-8420}" google_port="${STACK_TEST_GOOGLE_PORT:-19015}" hue_port="${STACK_TEST_HUE_PORT:-19011}"

# The line's own pins (deploy/container/base/line.json, main's version list): the same Python, Node
# and PostgreSQL the base built from this commit has, so a difference here is the change's and not the pins'.
line="$(cat "$repo/deploy/container/base/line.json" 2>/dev/null || echo '{}')"
pin() { python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2]) or sys.argv[3])' "$line" "$1" "$2"; }
[ -n "$postgres" ] || postgres="$(pin postgres_image pgvector/pgvector:0.8.7-pg18-trixie)"

if [ -z "$base" ] || [ -z "$guard" ]; then
  say "building the base and the protected core from this checkout"
  base="rouh-base:$project" guard="rouh-guard:$project"
  docker buildx build --load -f "$repo/deploy/container/Dockerfile.base" \
    --build-arg PYTHON_IMAGE="$(pin python_image python:3.12.16-slim-trixie)" \
    --build-arg NODE_IMAGE="$(pin node_image node:24.22.1-trixie-slim)" \
    --build-arg CODEX_VERSION="$(pin codex 0.163.0)" --build-arg PLAYWRIGHT_MCP_VERSION="$(pin playwright_mcp 0.0.83)" \
    --build-arg BASE_LINE=test --build-arg BASE_LEVEL="test-$(git -C "$repo" rev-parse --short=8 HEAD)" \
    ${STACK_TEST_CACHE:+--cache-from "$STACK_TEST_CACHE"} \
    -t "$base" "$repo" || { say "the base did not build"; exit 1; }
  docker buildx build --load -f "$repo/guard/Dockerfile" \
    --build-arg PYTHON_IMAGE="$(pin python_image python:3.12.16-slim-trixie)" --build-arg GUARD_LEVEL=test \
    -t "$guard" "$repo" || { say "the protected core did not build"; exit 1; }
fi

work="$(mktemp -d)"
settings="$work/settings.env" release="$work/release.env"
{ cat "$here/settings.env"; echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  echo "ROUH_STACK_NAME=$project"; echo "ROUH_PORT=$port"; echo "ROUH_PUBLIC_URL=http://127.0.0.1:$port"
  echo "ROUH_GOOGLE_AUTH_URL=http://127.0.0.1:$google_port/o/oauth2/v2/auth"; echo "ROUH_HUE_SIGN_IN=http://127.0.0.1:$hue_port"
  echo "STACK_GOOGLE_PORT=$google_port"; echo "STACK_HUE_PORT=$hue_port"; } > "$settings"
# The weekly copy off the machine is encrypted for a key made here with the real age, which the
# check opens it with (backup.offsite, tests/stack/checks_backup.py); without age it is not set up.
if command -v age-keygen >/dev/null 2>&1; then
  age-keygen -o "$work/offsite.key" 2>/dev/null
  echo "ROUH_OFFSITE_RECIPIENT=$(age-keygen -y "$work/offsite.key")" >> "$settings"
  export STACK_OFFSITE_KEY="$work/offsite.key"
fi
{ echo "ROUH_BASE_IMAGE=$base"; echo "ROUH_GUARD_IMAGE=$guard"; echo "ROUH_POSTGRES_IMAGE=$postgres"
  echo "ROUH_SETTINGS_FILE=$settings"; echo "ROUH_RELEASE_COMMIT=$(git -C "$repo" rev-parse HEAD)"; } > "$release"
compose=(docker compose -p "$project" --env-file "$settings" --env-file "$release"
         -f "$repo/deploy/stack/compose.yml" -f "$here/compose.test.yml")

down() {
  "${compose[@]}" logs --no-color --timestamps > "$out/stack.log" 2>&1 || true
  "${compose[@]}" ps -a > "$out/ps.txt" 2>&1 || true
  if [ -z "$keep" ]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    # The second stack an existing Rouh is brought into (import.existing), if a check left it up.
    "${compose[@]}" -p "$project-import" down -v --remove-orphans >/dev/null 2>&1 || true
    docker volume rm "$project-guard-files" >/dev/null 2>&1 || true
  fi
  rm -rf "$work"
}
trap down EXIT
"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true

# 1. The stack file a release would sign passes the stack check it would be held to, out of
# the protected core's image built here, exactly as linux_stack.py runs it.
say "the stack check, on deploy/stack/compose.yml alone"
python3 "$repo/guard/rouh_guard/stackpolicy.py" check --stack "$repo/deploy/stack" --env-file "$settings" \
  --env-file "$release" --reference "$repo/deploy/stack/compose.yml" > "$out/stack-check.txt" 2>&1
policy=$?
cat "$out/stack-check.txt"

# 2. The Rouh's own code, as a first start leaves it (guard/bin/rouh-code-install): this
# checkout, without the release tools a Rouh never runs, committed as its first commit and
# owned by its user, with the libraries it needs beside the base in /extra.
say "putting this checkout in the code volume, as a first start would"
docker volume create "${project}_code" >/dev/null
docker volume create "${project}_extra" >/dev/null
docker volume create "$project-guard-files" >/dev/null
docker run --rm --user 0:0 --network none -v "$project-guard-files:/out" \
  --entrypoint /opt/rouh-guard/bin/rouh-guard-install "$guard" /out >/dev/null
docker run --rm --user 0:0 --network none -v "$repo:/src:ro" -v "${project}_code:/code" --entrypoint /bin/bash "$base" -c '
  set -e
  tar -C /src --exclude=./.git --exclude=./.venv-e2e --exclude=./.stack-test --exclude=./.one -cf - . | tar -C /code -xf -
  rm -rf /code/guard /code/mac /code/.github /code/deploy/container
  chown -R 10001:10001 /code
  setpriv --reuid=10001 --regid=10001 --init-groups -- bash -c "cd /code && git init -q -b main && git add -A \
    && git -c user.name=Rouh -c user.email=rouh@localhost commit -q -m \"Rouh as installed, for the stack test\" \
    && printf \"__pycache__/\n*.pyc\n\" > .git/info/exclude"
' || { say "the code volume could not be filled"; exit 1; }
docker run --rm --user 0:0 -v "$project-guard-files:/opt/rouh-guard:ro" -v "${project}_extra:/extra" \
  -v "${project}_code:/code:ro" --entrypoint python "$base" -I /opt/rouh-guard/bin/rouh-code-install --extra-only /code \
  || { say "the libraries the code needs could not be put in /extra"; exit 1; }

# 3. The stack, started the way an install starts it, and every part waited for.
say "starting the stack"
"${compose[@]}" up -d 2>&1 | tail -5
healthy=""
for i in $(seq 1 120); do
  state="$("${compose[@]}" ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}' 2>/dev/null)"
  bad="$(printf '%s\n' "$state" | awk -F'|' '($2=="exited" && $4!="0") || $3=="unhealthy"')"
  if [ -n "$bad" ]; then say "a part did not start: $bad"; break; fi
  waiting="$(printf '%s\n' "$state" | awk -F'|' '$2!="exited" && $3!="healthy" && $3!=""')"
  if printf '%s\n' "$state" | grep -q '^core|running|healthy' && [ -z "$waiting" ]; then healthy=1; break; fi
  sleep 10
done
printf '%s\n' "$state"
if [ -z "$healthy" ]; then
  say "the stack did not come up healthy; the last of each part's log:"
  for s in code-install guard core worker keyproxy browser standins; do echo "--- $s"; "${compose[@]}" logs --no-color --tail 40 "$s" 2>&1; done
  exit 1
fi

# 4. Every feature, from outside, as the person uses it.
say "the stack is up; checking every feature (CONTAINERS.md)"
"${STACK_TEST_PYTHON:-python3}" "$here/smoke.py" --url "http://127.0.0.1:$port" --features "$repo/CONTAINERS.md" --out "$out" \
  --compose "$(printf '%q ' "${compose[@]}")" ${only:+--only "$only"}
smoke=$?
[ "$policy" = 0 ] || say "the stack check refused deploy/stack/compose.yml (above)"
ok=false; [ "$policy" = 0 ] && [ "$smoke" = 0 ] && ok=true
if [ -n "$record" ] && [ -z "$only" ] && [ -z "$(git -C "$repo" status --porcelain)" ]; then
  commit="$(git -C "$repo" rev-parse HEAD)" rec="$(mktemp -d)"
  if git -C "$repo" fetch -q origin stack-checks 2>/dev/null; then git -C "$repo" worktree add -q --detach "$rec/w" FETCH_HEAD
  else git -C "$repo" worktree add -q --detach "$rec/w" HEAD && git -C "$rec/w" checkout -q --orphan stack-checks && git -C "$rec/w" rm -rfq .; fi
  mkdir -p "$rec/w/results"
  python3 -c 'import json,sys,platform,socket,time; json.dump({"commit": sys.argv[1], "ok": sys.argv[2] == "true", "result": "success" if sys.argv[2] == "true" else "failure",
    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "where": f"{socket.gethostname()}, {platform.machine()}, tests/stack/run.sh", "run": ""},
    open(sys.argv[3], "w"))' "$commit" "$ok" "$rec/w/results/$commit.json"
  git -C "$rec/w" add results && git -C "$rec/w" -c user.name="stack test" -c user.email=stack-test@localhost \
    commit -q -m "stack test of ${commit:0:12} on $(hostname), $(uname -m): $ok" \
    && git -C "$rec/w" push -q origin HEAD:refs/heads/stack-checks && say "written down on the branch stack-checks"
  git -C "$repo" worktree remove --force "$rec/w"; rm -rf "$rec"
fi
[ "$ok" = true ]
