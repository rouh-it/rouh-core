# The base line's version list

This folder is the exact list of versions every published base image is built with, in main since 30 October 2026.
One commit of main holds both the code and these versions, and a release names that one commit with a tag, `base-<level>` (base 1.0.5 is the commit tagged `base-1.0.5`).

| File | What it is |
|---|---|
| `line.json` | The line (1.0), its patch number and level (1.0.4), the commit the line was cut from, and every pin that is not a Python library: the Python and Node images, Codex, Playwright MCP, and the database image by its digest with the PostgreSQL inside it. |
| `pyproject.toml` | The cut commit's, each pinned library held within its minor line. Only for the lock below; nothing installs Rouh from it. |
| `uv.lock` | The line's lock: the cut's versions, moved on by patch levels only. |
| `requirements.txt` | That lock written out; `Dockerfile.base` installs exactly this. |
| `plan.json` | What this level changes over the one before, and what is newer than a patch, listed and left for genes. The signed release carries its changes. |

Never edit these by hand.
A new level comes from the Creator Rouh's nightly patch job (the maker's own Rouh, `rouh/base_patches.py`), as a pull request on main that `.github/workflows/base.yml` tests on Intel and Arm and merges by itself only when every check passes; a new line comes from that workflow run by hand with `cut`.
`deploy/container/base_patch.py` says how each file is made.

What a build made is not kept here or anywhere else in git: how the check went on each platform, what was published, the signed release, and every Debian package in the images are on that level's GitHub Release, `https://github.com/rouh-it/rouh-core/releases/tag/base-<level>`.

Until 30 October 2026 these files lived on a branch of their own, `base`, with the build records beside them.
That branch is kept, read-only, as `archive/base-branch-until-2026-10`; nothing reads it.
