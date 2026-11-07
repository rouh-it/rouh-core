"""Synapse, Rouh's new memory, as a lab (task 85, steps 85-01 and 85-02).

The design is the spec in the workspace,
`workspace/rouh/assistant/85.rouh-memory/85-01.one-memory-for-rouh-design-spec/`,
and the decision numbers in the comments here (D1 to D79) are its. This is its
first build: a lab Petar experiments with until he understands it and gets good
results, with nothing else in Rouh reading from it. It does not replace the
remember tool, contacts, the workspace, mail or any other store.

What each part is:

- `numbers`   every starting number in the spec, each adjustable per dataset (D5)
- `db`        plain SQL over the `synapse` schema (migration 0062)
- `ai`        OpenAI: embeddings, the helper and answer models, and `decide` (D66)
- `trace`     every operation written down step by step, for the debugger
- `text`      passages, compact lines, quote checks
- `datasets`  the sets of data, each isolated, with its own side chat
- `ingest`    storing, editing and deleting an item, every step traced
- `search`    hybrid search, words and meaning fused (D36 to D39, D70)
- `walk`      the budgeted best-first traversal (D41 to D48, D71)
- `recall`    the pack, the rules, the checkpoint and the answer (D46, D50, D59)
- `layers`    thread, topic and profile layers, updated by diff (D53 to D55)
- `mapping`   the tiny map (D13 to D18)
- `learning`  usage feedback on link strengths (D57)
- `evaluate`  evaluation sets and runs, with and without decision models (D79)
- `seeds`     the example datasets, all fictional
- `worker`    the queue of ingest and layer jobs
- `chat`      the tools Rouh has in a dataset's side chat
- `sources/`  the connectors that bring things in: Gmail (`gmailsync`), Calendar (`calsync`), the meeting
              library (`meetings`), iCloud contacts (`contacts`), and files and mail read as items
              (`parsing`, `mailfiles`)
- `lab/`      the nightly self-improvement lab: `nightly`, `improvements`, `recalibrate` and the scale
              benchmark (`benchmark`)

Every module that moved into `sources/` or `lab/` is still reachable at its old path,
`rouh.synapse.<name>`, as the very same module object (`_OldPath` below), so nothing that imports it
changed with the move.
"""
import importlib
import importlib.abc
import importlib.util
import sys

#: Each module that moved, and the subpackage it lives in now.
MOVED = {"gmailsync": "sources", "calsync": "sources", "meetings": "sources", "contacts": "sources",
         "mailfiles": "sources", "parsing": "sources",
         "benchmark": "lab", "improvements": "lab", "nightly": "lab", "recalibrate": "lab"}


class _OldPath(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """`rouh.synapse.<name>` for a module that moved: the module at its new path, imported there once,
    never a second copy. Asked only after the ordinary finders found no file at the old path."""

    def find_spec(self, fullname, path=None, target=None):
        parent, _, name = fullname.rpartition(".")
        if parent != __name__ or name not in MOVED:
            return None
        return importlib.util.spec_from_loader(fullname, self)

    def create_module(self, spec):
        name = spec.name.rpartition(".")[2]
        module = importlib.import_module(f"{__name__}.{MOVED[name]}.{name}")
        spec.loader_state = module.__spec__
        return module

    def exec_module(self, module):
        # The import system has just put the old path's spec on it; the module keeps its own.
        module.__spec__ = module.__spec__.loader_state


if not any(isinstance(f, _OldPath) for f in sys.meta_path):
    sys.meta_path.append(_OldPath())


def __getattr__(name):
    """`rouh.synapse.<name>` as an attribute, for a module that moved, even before anything imported it there."""
    if name in MOVED:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
