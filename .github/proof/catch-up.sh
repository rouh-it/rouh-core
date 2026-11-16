#!/bin/bash
# Proof (task 187, run 221fc2f4): a Rouh installed from 10 November 2026 code, by the real
# rouh-code-install of base 1.0.17, with a change of its own on top, running its own 10 November
# stack file on the released base 1.0.17 images; then bin/rouh-catch-up-mac as a Mac runs it; then
# the stack file of the new code applied, as Rouh for Mac does; then the undo it prints.
set -uo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
out="${OUT:-$repo/.proof}"; mkdir -p "$out"
OLD=287d2b9567b5b15e0c1ef646272133a23ecc82e2
say() { echo "proof: $*"; }
die() { say "FAILED: $*"; exit 1; }
rel="$(curl -fsS https://rouh.land/mac/release/stable.json)"
img() { python3 -c 'import json,sys; e=json.loads(sys.argv[1]); p=json.loads(e["payload"]) if "payload" in e else e; print(p["images"][sys.argv[2]])' "$rel" "$1"; }
base="$(img base)" guard="$(img guard)" postgres="$(img postgres)"
say "release images: $base $guard $postgres"
for i in "$base" "$guard" "$postgres"; do docker pull -q "$i" >/dev/null || die "could not pull $i"; done

old="$(mktemp -d)"; git -C "$repo" fetch -q --depth 1 origin "$OLD" && git -C "$repo" archive "$OLD" | tar -C "$old" -xf - || die "no $OLD"
project=rouh port=8420
settings="$out/settings.env" release="$out/release.env"
{ cat "$old/tests/stack/settings.env"; echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  echo "ROUH_STACK_NAME=$project"; echo "ROUH_PORT=$port"; echo "ROUH_PUBLIC_URL=http://127.0.0.1:$port"; } > "$settings"
{ echo "ROUH_BASE_IMAGE=$base"; echo "ROUH_GUARD_IMAGE=$guard"; echo "ROUH_POSTGRES_IMAGE=$postgres"
  echo "ROUH_SETTINGS_FILE=$settings"; echo "ROUH_RELEASE_COMMIT=$OLD"; } > "$release"
stackfile() { echo docker compose -p "$project" --env-file "$settings" --env-file "$release" -f "$1/deploy/stack/compose.yml" -f "$1/tests/stack/compose.test.yml"; }
compose=($(stackfile "$old"))

# 1. A first start of 10 November: the real installer of base 1.0.17, told that release, with
# rouh.land out of reach so it takes the pin, the code from GitHub's rouh-land.
docker volume create "${project}_code" >/dev/null; docker volume create "${project}_extra" >/dev/null
docker volume create guardfiles >/dev/null
docker run --rm --user 0:0 -v guardfiles:/out --entrypoint /opt/rouh-guard/bin/rouh-guard-install "$guard" /out >/dev/null
docker run --rm --user 0:0 -v guardfiles:/opt/rouh-guard:ro -v "${project}_code:/code" -v "${project}_extra:/extra" \
  -e ROUH_SITE_URL=http://127.0.0.1:9 -e ROUH_INSTALL_URL=http://127.0.0.1:9/x -e ROUH_RELEASE_COMMIT=$OLD \
  --entrypoint python "$base" -I /opt/rouh-guard/bin/rouh-code-install 2>&1 | tee "$out/install.log"
grep -q "is now this Rouh's own code" "$out/install.log" || die "the 10 November install did not finish"

# 2. A change of its own: a gene, and a line of AGENTS.md the release also changes (a clash).
docker run --rm --user 10001:10001 -e HOME=/tmp -v "${project}_code:/code" --entrypoint bash "$base" -c '
  set -e; cd /code; mkdir -p docs; echo "A gene of this Rouh own." > docs/own-gene.md
  sed -i "576s/.*/Her own words on line 576./" AGENTS.md; git add -A
  git -c user.name=Rouh -c user.email=rouh@localhost commit -qm "Its own gene and words" -m "Gene: own-gene"
  git log --oneline' | tee "$out/own.log"
before="$(docker run --rm -v "${project}_code:/code" --entrypoint git "$base" -c safe.directory='*' -C /code rev-parse HEAD)"

up() {
  "$@" up -d 2>&1 | tail -3
  for i in $(seq 1 90); do
    code=$(curl -s -o "$out/healthz.json" -w '%{http_code}' "http://127.0.0.1:$port/healthz")
    [ "$code" = 200 ] && grep -q '"ok":true' "$out/healthz.json" && return 0
    sleep 10
  done
  "$@" ps -a; "$@" logs --no-color --tail 60 core guard; return 1
}
sha() { curl -s "http://127.0.0.1:$port/healthz" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("git") or {}).get("sha") or d.get("build") or "")'; }
say "starting the 10 November Rouh on base 1.0.17"
up "${compose[@]}" || die "the 10 November Rouh did not come up"
say "it answers, at $(sha)"

# 3. Its first run, and something it remembers, with the stack test of that day.
setup="$("${compose[@]}" exec -T core python manage.py setup_link | tr -d '\r' | tail -1)"; say "setup address: ${setup%%code=*}code=..."
python3 "$old/tests/stack/smoke.py" --setup-url "$setup" --url "http://127.0.0.1:$port" --features "$old/CONTAINERS.md" --out "$out/old" \
  --compose "$(printf '%q ' "${compose[@]}")" --only first-run,tool.memory | tee "$out/old-smoke.log"
grep -q '^ok    first-run\|^ok  first-run' "$out/old-smoke.log" || grep -q 'ok  *first-run' "$out/old-smoke.log" || die "the first run failed"
PASS="$(cd "$old/tests/stack" && python3 -c 'import smoke; print(smoke.STACK_PASSWORD)')"
python3 "$repo/.github/proof/browse.py" "http://127.0.0.1:$port" "$PASS" "$out" before '!Update to the newest Rouh' || die "the 10 November Changes page"
db() { "${compose[@]}" exec -T postgres pg_dump -U rouh rouh 2>/dev/null; }
keys() { "${compose[@]}" exec -T core sh -c 'cd /keys && find . -type f -exec sha256sum {} + | sort'; }
remembered_before=$(db | grep -c "likes plain words"); keys > "$out/keys-before.txt"
users_before=$("${compose[@]}" exec -T postgres psql -U rouh -Atc "select count(*) from auth_user" 2>/dev/null || echo "?")
say "before: remembered $remembered_before, users $users_before, keys $(wc -l < "$out/keys-before.txt")"

# 4. The catch-up, as a Mac runs it (its own copy of rouh-catch-up beside it).
say "running bin/rouh-catch-up-mac"
DOCKER_HOST=unix:///var/run/docker.sock ROUH_STACK_NAME=$project bash "$repo/bin/rouh-catch-up-mac" 2>&1 | tee "$out/catch-up.log"
grep -q '^ROUH-CATCH-UP {"ok": true' "$out/catch-up.log" || die "the catch-up did not go live"
undo="$(grep -o 'bash -s undo [0-9]* rouh-[0-9-]*\.dump' "$out/catch-up.log" | tail -1)"
[ -n "$undo" ] || die "it printed no undo line"
sleep 30
for i in $(seq 1 60); do s=$(sha); [ -n "$s" ] && [ "$s" != "${before}" ] && [ "${s:0:7}" != "${before:0:7}" ] && break; sleep 10; done
after="$(docker run --rm -v "${project}_code:/code" --entrypoint git "$base" -c safe.directory='*' -C /code rev-parse HEAD)"
say "it answers again, at $(sha); /code is $after"
docker run --rm -v "${project}_code:/code" --entrypoint bash "$base" -c '
  cd /code; git -c safe.directory=* log --format="%h %s%n  %(trailers:key=Rouh-release)" -4; cat docs/own-gene.md; sed -n 576p AGENTS.md; ls rouh/code_update.py' | tee "$out/after.txt"
grep -q "Rouh-release: cc492ed2\|Rouh-release: [0-9a-f]\{40\}" "$out/after.txt" || die "no Rouh-release line"
grep -q "A gene of this Rouh own" "$out/after.txt" && grep -q "Her own words on line 576" "$out/after.txt" || die "its own change was lost"
grep -q "rouh/code_update.py" "$out/after.txt" || die "the new code is not there"

# 5. The new code's own stack file applied, as Rouh for Mac does once the code changes.
new="$(mktemp -d)"; docker run --rm -v "${project}_code:/code:ro" --entrypoint tar "$base" -C /code -cf - deploy/stack tests/stack | tar -C "$new" -xf -
compose=($(stackfile "$new"))
say "applying the new code's own stack file"
up "${compose[@]}" || die "the new stack file did not come up"
python3 "$repo/.github/proof/browse.py" "http://127.0.0.1:$port" "$PASS" "$out" after "How new releases come" "16 November 2026" || die "the new Changes page"
remembered_after=$(db | grep -c "likes plain words"); keys > "$out/keys-after.txt"
users_after=$("${compose[@]}" exec -T postgres psql -U rouh -Atc "select count(*) from auth_user" 2>/dev/null || echo "?")
say "after: remembered $remembered_after, users $users_after"
[ "$remembered_after" -ge 1 ] && [ "$remembered_after" -ge "$remembered_before" ] || die "what it remembered was lost"
diff -q "$out/keys-before.txt" "$out/keys-after.txt" || die "the keys changed"
"${compose[@]}" exec -T core python manage.py shell -c "from rouh import code_update; print(code_update.base())" | tee "$out/base-after.txt"
grep -q "'how': 'update'" "$out/base-after.txt" || die "the new code does not know where it stands"

# 6. The undo it printed.
say "undo: $undo"
DOCKER_HOST=unix:///var/run/docker.sock ROUH_STACK_NAME=$project bash "$repo/bin/rouh-catch-up-mac" ${undo#bash -s } 2>&1 | tee "$out/undo.log"
grep -q "done: Rouh starts again" "$out/undo.log" || die "the undo did not finish"
sleep 30
compose=($(stackfile "$old"))
up "${compose[@]}" || die "the 10 November Rouh did not come back"
back="$(docker run --rm -v "${project}_code:/code" --entrypoint git "$base" -c safe.directory='*' -C /code rev-parse HEAD)"
[ "$back" = "$before" ] || die "the code is $back after the undo, not $before"
python3 "$repo/.github/proof/browse.py" "http://127.0.0.1:$port" "$PASS" "$out" undone '!How new releases come' || die "the undone Changes page"
say "PASSED: catch-up from $before to $after, and back"
