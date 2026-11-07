#!/usr/bin/env bash
# Rouh's code for a fresh installation, without anybody's workspace (SETUP.md).
#
#   tools/distribution/export.sh /tmp/rouh-export        # from the commit checked out
#   tools/distribution/export.sh /tmp/rouh-export main   # from another commit
#
# A workspace - tasks, research, notes - is a repository of its own, never part
# of Rouh's code, and never part of what another installation gets: this
# writes the tree of a commit of the code, and `python manage.py setup` makes
# the new installation's own empty workspace. The commands a run uses on a
# workspace (`rouh-task`, `rouh`) are in the code's own `bin/`. Nothing is
# pushed or published; the export is a folder, and what is done with it is
# the person's to decide.
set -euo pipefail

out="${1:?say where the export goes}"
rev="${2:-HEAD}"
here="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -e "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ]; then
  echo "$out is not empty; give an empty or new folder." >&2
  exit 2
fi
mkdir -p "$out"

# Rouh's code repository holds no workspace since 21 October 2026; the exclude
# stays for a revision from before then.
git -C "$here" archive --format=tar "$rev" -- . ':(exclude)workspace' ':(exclude).gitmodules' \
  | tar -x -C "$out"

# What is left that names a person, for whoever reads the export: historical
# comments and the design record say who asked for what, and the legacy words
# that rows written before 20 October 2026 still hold are read, never written.
echo "exported $rev to $out, without any workspace"
echo "next: deploy/installation.env.example, then python manage.py setup (SETUP.md)"
