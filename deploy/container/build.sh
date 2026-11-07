#!/bin/bash
#
# Build Rouh's two images from this checkout, for Intel and Arm (linux/amd64
# and linux/arm64), and keep them as image archives, with no registry involved:
#
#   deploy/container/build.sh                         # tag: the commit, and latest
#   deploy/container/build.sh --out /srv/rouh-images --tag 0.1
#   deploy/container/build.sh --platform linux/amd64  # one machine's only, faster
#
#   rouh-base   Dockerfile.base: what everything runs on, no Rouh code
#   rouh-guard  guard/Dockerfile: the protected core, which a Rouh uses and
#               cannot edit (guard/README.md)
#
# This is a build of this checkout, for trying things, with this commit's own
# version list (deploy/container/base/: line.json's images and tools, and
# requirements.txt). The published base, its line and its patch levels are
# .github/workflows/base.yml's, built from a tagged commit of main
# (deploy/container/base_patch.py).
#
# Needs Docker with the containerd image store (the default since Docker 29),
# so one tag holds both platforms, and QEMU's binfmt handlers for the platform
# this machine is not. Each archive is `docker save` of one image, both
# platforms in it; `docker load -i <file>` puts it back on any machine.
# Nothing is pushed anywhere.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
platform="linux/amd64,linux/arm64"
tag="$(git -C "$repo" rev-parse --short=8 HEAD)"
out=""
prefix="${ROUH_IMAGE_PREFIX:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --tag) tag="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    *) echo "build.sh: unknown option $1" >&2; exit 2 ;;
  esac
done

commit="$(git -C "$repo" rev-parse HEAD)"
pin() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$here/base/line.json" "$1"; }
echo "== ${prefix}rouh-base:$tag ($platform)"
docker buildx build --platform "$platform" -f "$here/Dockerfile.base" \
  --build-arg PYTHON_IMAGE="$(pin python_image)" --build-arg NODE_IMAGE="$(pin node_image)" \
  --build-arg CODEX_VERSION="$(pin codex)" --build-arg PLAYWRIGHT_MCP_VERSION="$(pin playwright_mcp)" \
  --build-arg BASE_LINE=dev --build-arg BASE_LEVEL="dev-$tag" \
  --label "org.opencontainers.image.source=rouh" \
  -t "${prefix}rouh-base:$tag" -t "${prefix}rouh-base:latest" --load "$repo"
echo "== ${prefix}rouh-guard:$tag ($platform)"
docker buildx build --platform "$platform" -f "$repo/guard/Dockerfile" --build-arg GUARD_LEVEL="dev-$tag" \
  --build-arg PYTHON_IMAGE="$(pin python_image)" \
  --label "org.opencontainers.image.revision=$commit" --label "org.opencontainers.image.source=rouh" \
  -t "${prefix}rouh-guard:$tag" -t "${prefix}rouh-guard:latest" --load "$repo"
if [ -n "$out" ]; then
  mkdir -p "$out"
  for name in rouh-base rouh-guard; do
    file="$out/${name}-${tag}.tar"
    echo "== saving ${prefix}$name:$tag to $file"
    docker save -o "$file" "${prefix}$name:$tag"
  done
  (cd "$out" && sha256sum rouh-*-"$tag".tar > "SHA256SUMS-$tag")
fi
docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E "rouh-(base|guard):$tag" || true
