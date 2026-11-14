#!/usr/bin/env bash
# Builds Rouh's own WSL Linux as a .wsl file (task 186, step 186-04), on Linux with Docker:
#
#     deploy/windows/wsl/build.sh --arch amd64|arm64 [--version YYYYMMDDHHMMSS] [--out DIR]
#
# docker build of the Dockerfile beside this, for that architecture; docker export of the result,
# without the files only a container has (/.dockerenv, which would make systemd think it runs in
# Docker), gzip'd: that is the .wsl format WSL imports (learn.microsoft.com/windows/wsl/build-custom-distro).
# Writes DIR/rouh-wsl-<version>-<x64|arm64>.wsl, its .sha256, and .contents (what is in it: Debian,
# Docker, Compose, Python, by version). GitHub builds it for both, .github/workflows/wsl-image.yml.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
arch="" version="$(date -u +%Y%m%d%H%M%S)" out="$PWD/wsl-out"
while [ $# -gt 0 ]; do
  case "$1" in
    --arch) arch="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
case "$arch" in
  amd64) win=x64 ;;
  arm64) win=arm64 ;;
  *) echo "--arch must be amd64 or arm64" >&2; exit 2 ;;
esac
[[ "$version" =~ ^[0-9]{14}$ ]] || { echo "--version is YYYYMMDDHHMMSS" >&2; exit 2; }
mkdir -p "$out"
tag="rouh-wsl:$version-$arch"
name="rouh-wsl-$version-$win.wsl"

docker buildx build --platform "linux/$arch" --load --pull -t "$tag" "$here"
cid="$(docker create --platform "linux/$arch" "$tag" /bin/true)"
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
docker cp "$cid:/etc/rouh-wsl-release" "$out/$name.contents"
echo "version=$version" >> "$out/$name.contents"
# The export, as one tar, filtered and gzip'd without a timestamp of its own (-n).
docker export "$cid" | python3 "$here/strip_container_files.py" | gzip -n -6 > "$out/$name"
( cd "$out" && sha256sum "$name" > "$name.sha256" )
echo "built $out/$name ($(du -h "$out/$name" | cut -f1)), $(cut -d' ' -f1 "$out/$name.sha256")"
