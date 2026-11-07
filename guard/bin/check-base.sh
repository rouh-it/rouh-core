#!/bin/bash
#
# Check a base image with a Rouh's code before anything moves onto it: a
# throwaway PostgreSQL and the check container on a network of their own with
# no way out, no keys, nothing of anybody's, all removed afterwards. Part of the
# protected core (guard/, the rouh-guard image) since 24 October 2026.
#
#   guard/bin/check-base.sh --base REF --guard REF (--code-dir DIR | --code-volume NAME)
#       [--postgres REF] [--extra-volume NAME] [--name PREFIX]
#
# The check runs on the base being checked, with the protected core's own files
# (the guard image, copied into a throwaway volume with rouh-guard-install) at
# /opt/rouh-guard, read-only, and the Rouh's code read-only at /code: a folder
# (--code-dir, what CI checks main with) or a Rouh's own code volume
# (--code-volume, what Rouh for Mac does before it switches, StackUpdater.check,
# the same steps in Swift). /extra, the libraries a gene added, is mounted
# read-only when --extra-volume names it.
#
# The stacks before the protected core (base releases of format 1) checked a
# code image instead, the base with the release's code on top:
#
#   guard/bin/check-base.sh --base REF --code REF [--code-volume NAME] ...
#
# which runs the base's own /usr/local/bin/rouh-check. Kept until no release
# of that format is made.
#
# The check container runs rouh-check: the base's own parts, the headless
# browser over MCP, the frozen security checks and the Rouh's own checks. Its
# last line is "ROUH-CHECK {json}"; this exits with its exit code.
set -uo pipefail

base="" code="" guard="" codedir="" postgres="pgvector/pgvector:0.8.2-pg18-trixie" volume="" extra="" name="rouh-check-$$"
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="$2"; shift 2 ;;
    --code) code="$2"; shift 2 ;;
    --guard) guard="$2"; shift 2 ;;
    --code-dir) codedir="$2"; shift 2 ;;
    --postgres) postgres="$2"; shift 2 ;;
    --code-volume) volume="$2"; shift 2 ;;
    --extra-volume) extra="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    *) echo "check-base.sh: unknown option $1" >&2; exit 2 ;;
  esac
done
[ -n "$base" ] || { echo "check-base.sh: --base is needed" >&2; exit 2; }
if [ -n "$guard" ]; then
  [ -n "$codedir$volume" ] || { echo "check-base.sh: with --guard, give --code-dir or --code-volume" >&2; exit 2; }
else
  [ -n "$code" ] || { echo "check-base.sh: give --guard (and the code), or --code for a release of format 1" >&2; exit 2; }
fi

net="$name-net" db="$name-db" box="$name" guardvol="$name-guard"
cleanup() {
  docker rm -f "$box" "$db" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  docker volume rm "$guardvol" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create --internal "$net" >/dev/null || exit 1
docker run -d --name "$db" --network "$net" --tmpfs /var/lib/postgresql:rw,size=2g --shm-size 256m \
  -e POSTGRES_USER=rouh -e POSTGRES_DB=rouh -e POSTGRES_PASSWORD=check "$postgres" >/dev/null || exit 1
for i in $(seq 1 60); do
  docker exec "$db" pg_isready -U rouh -d rouh >/dev/null 2>&1 && break
  [ "$i" = 60 ] && { echo "check-base.sh: the throwaway database did not start" >&2; docker logs "$db" | tail -20; exit 1; }
  sleep 1
done

mounts=()
if [ -n "$guard" ]; then
  # The protected core's files, from its own image, into a volume of their own:
  # the check runs on the base, with them beside it and nothing of theirs changeable.
  docker volume create "$guardvol" >/dev/null || exit 1
  docker run --rm --network none --user 0:0 --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER -v "$guardvol:/out" --entrypoint /opt/rouh-guard/bin/rouh-guard-install "$guard" /out \
    || { echo "check-base.sh: the protected core's files could not be put beside the check" >&2; exit 1; }
  mounts+=(-v "$guardvol:/opt/rouh-guard:ro")
  if [ -n "$codedir" ]; then
    mounts+=(-v "$(cd "$codedir" && pwd):/code:ro")
  else
    mounts+=(-v "$volume:/code:ro")
  fi
  image="$base" entry=/opt/rouh-guard/bin/rouh-check
else
  # A release of format 1: the code image, the base with the release's copy on top.
  [ -n "$volume" ] && mounts+=(-v "$volume:/code:ro")
  image="$code" entry=/usr/local/bin/rouh-check
fi
[ -n "$extra" ] && mounts+=(-v "$extra:/extra:ro")

docker run --name "$box" --network "$net" --user 10001:10001 --read-only \
  --tmpfs /tmp:rw,exec,size=1g --shm-size 512m --cap-drop ALL --security-opt no-new-privileges:true \
  -e ROUH_DB_HOST="$db" -e ROUH_DB_USER=rouh -e ROUH_DB_NAME=rouh -e ROUH_DB_PASSWORD=check \
  "${mounts[@]}" --entrypoint "$entry" "$image"
status=$?
exit "$status"
