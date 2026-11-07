#!/bin/bash
#
# Refuse an image that holds anybody's data, or a base or protected core that
# holds Rouh's code. Run on every image before it is pushed to ghcr.io
# (.github/workflows/base.yml), and by hand on any build:
#
#   deploy/container/check-image.sh rouh-base:latest base
#   deploy/container/check-image.sh rouh-guard:latest guard
#
# The base must hold no Rouh code at all (Petar, 23 October 2026): /code is an
# empty folder the code volume is mounted over, and nothing of rouh/ or one/ is
# anywhere in it. The protected core (task 98, step 98-23) holds its own files
# in /opt/rouh-guard, exactly guard/'s, and no Rouh code either. The code
# image is gone since that day: a Rouh's code comes from rouh.land.
#
# It exports the image's whole filesystem and checks it, rather than trusting
# .dockerignore: the images leave this server (to ghcr.io, private, and to
# machines that pull them). Rouh's code repository holds no workspace since 21
# October 2026 - the workspace is a repository of its own - and this still
# refuses one, wherever it came from.
#
#  - The code image's code folder holds only what .dockerignore lets in, by name, with
#    no workspace/ at all, and of bin/ only Rouh's commands for a workspace.
#  - No .git, no .env (only the blank .env.example, for INSTALL-LINUX-VM.md),
#    no key or certificate file, no ssh folder, no test stand-ins or
#    fixtures, no screenshots, anywhere Rouh's own files are.
#  - The home folder holds only what the Dockerfile made there.
#  - No file of Rouh's own holds anything shaped like a real key or token.
#
# Prints the code folder's top level, a count of its files and the size, and
# exits 1 with every reason when any check fails.
set -euo pipefail

image="$1"
kind="$2"            # base | guard
work="$(mktemp -d)"
trap 'rm -rf "$work"; [ -n "${cid:-}" ] && docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT

cid="$(docker create "$image" 2>/dev/null)"
docker export "$cid" | tar -tf - | sed 's|^\./||; s|/$||' | sort > "$work/files"

case "$kind" in
  base) code="code" ;;
  guard) code="opt/rouh-guard" ;;
  *) echo "check-image.sh: kind is base or guard" >&2; exit 2 ;;
esac

fail=0
bad() { echo "REFUSED $image: $1" >&2; fail=1; }

if [ "$kind" = base ]; then
  # 1. No Rouh code anywhere: /code empty, and no copy of it elsewhere.
  extra="$(grep -E '^code/.' "$work/files" || true)"
  [ -z "$extra" ] || bad "/code is not empty in the base: $(echo "$extra" | head -5 | tr '\n' ' ')"
  extra="$(grep -E '(^|/)(rouh/(server|brain|tools)\.py|one/program\.py|manage\.py)$' "$work/files" \
    | grep -vE '^(usr|opt/venv)/lib/python[0-9.]+/site-packages/' || true)"
  [ -z "$extra" ] || bad "Rouh's code is in the base: $(echo "$extra" | head -5 | tr '\n' ' ')"
  for gone in opt/rouh opt/rouh-release; do
    grep -qxE "$gone" "$work/files" && bad "the base has $gone, which only the code image may have"
  done
else
  # 1. The protected core's folder is exactly guard/'s top level.
  allowed="Dockerfile Dockerfile.dockerignore VERSION bin frozen level.env policy rouh_guard"
  top="$(grep -E "^$code/[^/]+$" "$work/files" | sed "s|^$code/||" | sort -u | tr '\n' ' ' | sed 's/ $//')"
  [ "$top" = "$allowed" ] || bad "$code holds [$top], not exactly [$allowed]"
  # 2. No Rouh code anywhere in it.
  extra="$(grep -E '(^|/)(rouh/(server|brain|tools)\.py|one/program\.py|manage\.py)$' "$work/files" \
    | grep -vE '^usr/(local/)?lib/python[0-9.]+/' || true)"
  [ -z "$extra" ] || bad "Rouh's code is in the protected core: $(echo "$extra" | head -5 | tr '\n' ' ')"
  grep -qE '^code(/|$)' "$work/files" && bad "the protected core has a /code folder"
fi

# 3. Nothing shaped like data or a secret where Rouh's files are.
mine="$(grep -E "^($code|home/rouh|opt/rouh-base)(/|$)" "$work/files" || true)"
hits="$(echo "$mine" | grep -E '(^|/)(\.git|\.env(\..*)?|\.ssh|\.one|\.rouh|\.claude|\.mcp\.json|node_modules|__pycache__|screenshots|tests?|testing)(/|$)|\.(pem|key|p12|pfx|crt|sqlite3?|db|dump|tar|gz|zip)$|(^|/)id_(rsa|ed25519|ecdsa)' || true)"
[ -z "$hits" ] || bad "data- or secret-shaped paths: $(echo "$hits" | head -8 | tr '\n' ' ')"

# 4. The home folder holds what useradd and the Dockerfile put there, nothing more.
if [ "$kind" = base ]; then
  extra="$(grep -E '^home/rouh/' "$work/files" | grep -vxE 'home/rouh/\.(gitconfig|bashrc|profile|bash_logout)' || true)"
  [ -z "$extra" ] || bad "unexpected files in /home/rouh: $(echo "$extra" | head -5 | tr '\n' ' ')"
fi

# 5. No key or token in Rouh's own files. The one exception is YouTube's
# public InnerTube key (rouh/youtube.py), which every watch page carries.
mkdir "$work/x"
docker export "$cid" | tar -xf - -C "$work/x" "$code" opt/rouh-base 2>/dev/null || true
secrets="$(grep -rnIE 'sk-ant-(api|admin)[0-9]{2}-[A-Za-z0-9_-]{20,}|sk-(proj|svcacct)-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[0-9]{6,}-|AIza[0-9A-Za-z_-]{35}' "$work/x/$code" "$work/x/opt/rouh-base" 2>/dev/null \
  | grep -v '/rouh/youtube\.py:[0-9]*:PUBLIC_INNERTUBE_KEY = ' | cut -d: -f1-2 || true)"
[ -z "$secrets" ] || bad "key- or token-shaped text in: $(echo "$secrets" | sed "s|$work/x/||" | head -5 | tr '\n' ' ')"

count="$(grep -cE "^$code/.*[^/]$" "$work/files" || true)"
if [ "$kind" = base ]; then
  echo "$image (base): no Rouh code, /code empty; $(grep -c . "$work/files") paths"
else
  echo "$image (guard): $code = [$top], $count entries, $(du -sh "$work/x/$code" | cut -f1)"
fi
[ "$fail" = 0 ] && echo "  clean: no workspace data, .git, .env, keys, tokens or test fixtures"
exit "$fail"
