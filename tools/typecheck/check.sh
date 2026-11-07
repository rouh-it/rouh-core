#!/usr/bin/env bash
#
# The type check for Rouh's page: `tsc --noEmit` over tsconfig.json at the top
# of the repository, which covers app.js and its modules in rouh/static/app/.
#
#   tools/typecheck/check.sh        check, and say every error; exit 0 when clean
#   tools/typecheck/check.sh DIR    the same over another copy of the files,
#                                   which is how land.sh checks the commit it
#                                   is about to push rather than the worktree
#
# The modules are plain JavaScript with JSDoc types, checked in place: nothing
# is compiled, nothing is written, and nothing here ever reaches the server's
# runtime or a browser. TypeScript is a tool for whoever changes the page,
# pinned in package.json beside this file and installed the first time this
# runs, into a cache outside the checkout (one per version of the lock file),
# so a job's fresh worktree does not download it again.
#
# land.sh runs this before it pushes anything that touches the page's code,
# and refuses to land work that does not pass (`types_guard` there). The
# types worth knowing are in rouh/static/app/protocol.d.ts (the WebSocket
# messages and the card blocks) and globals.d.ts (what other scripts put on
# window). AGENTS.md, under "The page's types", says how to work with it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${1:-$(cd "$HERE/../.." && pwd)}"
LOCK="$HERE/package-lock.json"

KEY="$(sha256sum "$LOCK" | cut -c1-16)"
CACHE="${ROUH_TYPECHECK_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/rouh-typecheck}"
TOOL="$CACHE/$KEY"

if [ ! -x "$TOOL/node_modules/.bin/tsc" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "typecheck: npm is not installed here, so the page could not be type checked" >&2
    exit 3
  fi
  mkdir -p "$CACHE"
  # Installed beside where it goes and moved there whole, so two jobs
  # installing at the same moment never see half of one.
  BUILD="$(mktemp -d "$CACHE/.install-XXXXXX")"
  cp "$HERE/package.json" "$LOCK" "$BUILD/"
  if ! (cd "$BUILD" && npm ci --silent --no-audit --no-fund >/dev/null 2>&1); then
    rm -rf "$BUILD"
    echo "typecheck: TypeScript could not be installed (npm ci in $CACHE failed)" >&2
    exit 3
  fi
  mv -T "$BUILD" "$TOOL" 2>/dev/null || rm -rf "$BUILD"
fi

exec "$TOOL/node_modules/.bin/tsc" -p "$REPO/tsconfig.json" --noEmit --pretty false
