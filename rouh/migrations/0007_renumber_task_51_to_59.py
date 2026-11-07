"""Task 51 was two pieces of work, and the second is task 59 now, once.

The second half of "dedup the other tasks too" (Petar, 24 September 2026);
`0006` was the first. Task 51 was made in Rouh at 10:32 on 22 September 2026,
"Parallel feature runs merging", out of the chat a run was started in, with
one step, "The eleven runs, where they stand". Its folder was written into
this machine's checkout and never committed, so a job working from main that
afternoon could not see it, took 51 for "Rouh debugging, wave three" and
committed that under the same number. Rouh's row followed each folder in turn
(`conversations._the_folder`).

The workspace's own rule for a number two pieces of work both took is that
the later one takes the next free number and changes every reference to it,
and the commit this ships with does that in git: the folder, its four steps,
their notes, its page, its CLAUDE.md, its list of steps and `_tasks.md`, all now
59. What is here is the database's half, so the rows say what the files say:

- the row `task-59` - made, or kept when this machine's reconcile took the
  folder in first - named, numbered and filed under Assistant, as its
  `.object.json` says;
- its four step rows, which were task 51's, moved into it, at their new
  folders;
- everything that names a file of it by path moved with the files: the card
  its page is (`artifact.path`), a public link to it (`public_pages.rel`)
  and an Ask AI thread about it (`askai_threads.doc`);
- the row `task-51` back on its own folder and its own name, which is where
  its chat, its step and its card have been all along.

Only when the files are already where the commit put them and the old folder
is gone, and said in the deploy's log. On a database or a workspace that
never had any of it, it does nothing.
"""
import json
import time
import uuid
from pathlib import Path

from django.db import migrations

ASSISTANT = "3660e2e2-8784-4567-b9d8-57fc274ae269"
OLD = "private/assistant/51.rouh-debugging-wave-three"
NEW = "private/assistant/59.rouh-debugging-wave-three"
PARALLEL = "private/assistant/51.parallel-feature-runs-merging"
STEPS = {
    "c144386d-6cb8-45e4-9cd2-ff6fd8679218": "the-unfinished-item",
    "dd3d7b54-b90c-4df3-a4e2-847b5eafe46d": "the-jumpy-card",
    "89fc5b22-4474-4b7a-9be2-c7f446e7d605": "chats-and-runs-inside-projects",
    "c21f08a3-4b48-4c14-909d-10ecd49cb981": "empty-chats-and-the-tree",
}
#: The step folders, old name to new, in the order they are numbered.
RENAMED = {f"51-0{n}.{slug}": f"59-0{n}.{slug}"
           for n, slug in enumerate(STEPS.values(), start=1)}


def say(what: str) -> None:
    print(f"task 51 and 59: {what}")


def read_json(path: Path) -> dict:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def moved(path: str) -> str:
    """Where a path under the old folder is now, or the path as it was.

    The folder is renamed, the step folder in it is renamed, and a step's own
    notes, named with its number, are renamed with it: `51-02.what-was-done.md`
    in `51-02.the-jumpy-card` is `59-02.what-was-done.md` in `59-02.the-jumpy-card`.
    """
    path = str(path or "")
    if path != OLD and not path.startswith(OLD + "/"):
        return path
    parts = [part for part in path[len(OLD):].split("/") if part]
    if parts and parts[0] in RENAMED:
        old, new = parts[0], RENAMED[parts[0]]
        parts[0] = new
        if len(parts) > 1 and parts[1].startswith(old[:5] + "."):
            parts[1] = new[:5] + parts[1][5:]
    return "/".join([NEW, *parts])


def own(Link, owner: tuple[str, str], kind: str, ident: str) -> None:
    """Give one object this owner: the one `owns` link it hangs by, moved or made."""
    got = Link.objects.filter(rel="owns", dst_type=kind, dst_id=ident)
    if got.exists():
        got.update(src_type=owner[0], src_id=owner[1])
    else:
        Link.objects.create(id=f"link-{uuid.uuid4().hex[:12]}", rel="owns",
                            src_type=owner[0], src_id=owner[1],
                            dst_type=kind, dst_id=ident, created_at=time.time())


def forward(apps, schema_editor):
    from rouh.config import config

    where = str(getattr(config, "assistant_repo", "") or "")
    if not where or not Path(where).is_dir():
        return
    root = Path(where)
    side = read_json(root / NEW / ".object.json")
    if side.get("id") != "task-59" or (root / OLD).exists():
        return
    Task = apps.get_model("rouh", "Task")
    # A database with no history of task 51 is a new one, and the rows for
    # task 59 are made there the ordinary way, out of the folder's own
    # `.object.json`, once its projects exist (`conversations._take_in`).
    if not Task.objects.filter(id__in=["task-51", *STEPS]).exists():
        return
    Project = apps.get_model("rouh", "Project")
    Link = apps.get_model("rouh", "Link")
    Artifact = apps.get_model("rouh", "Artifact")
    PublicPage = apps.get_model("rouh", "PublicPage")
    AskThread = apps.get_model("rouh", "AskThread")

    # The number is the person's and unique: if anything else has taken 59
    # since, nothing here is the right answer and it is said instead.
    other = Task.objects.filter(number=59).exclude(id="task-59").values("id").first()
    if other is not None:
        say(f"left alone: 59 is {other['id']}'s now, so {NEW} needs a number of its own")
        return
    now = time.time()
    title = str(side.get("title") or "").strip() or "Rouh debugging, wave three"
    # Open: what its folder said of its status was only ever read on the installation this
    # was written for, and nothing in a folder says it now.
    state = "open"
    made = not Task.objects.filter(id="task-59").exists()
    if made:
        Task.objects.create(id="task-59", number=59, slug="rouh-debugging-wave-three",
                            title=title, state=state, folder=NEW, pinned=False,
                            created_at=now, updated_at=now)
    else:
        Task.objects.filter(id="task-59").update(
            number=59, slug="rouh-debugging-wave-three", title=title, state=state,
            folder=NEW, updated_at=now)
    if Project.objects.filter(id=ASSISTANT).exists():
        own(Link, ("project", ASSISTANT), "task", "task-59")

    steps = 0
    for ident, slug in STEPS.items():
        row = Task.objects.filter(id=ident).values("folder").first()
        if row is None:
            continue
        folder = moved(row["folder"]) if row["folder"] else ""
        if not folder.startswith(NEW + "/"):
            folder = next(f"{NEW}/{new}" for new in RENAMED.values() if new.endswith(slug))
        Task.objects.filter(id=ident).update(folder=folder, slug=folder.rsplit("/", 1)[-1],
                                             updated_at=now)
        own(Link, ("task", "task-59"), "task", ident)
        steps += 1

    cards = 0
    for art in Artifact.objects.filter(path__startswith=OLD + "/").values("id", "path"):
        Artifact.objects.filter(id=art["id"]).update(path=moved(art["path"]))
        Link.objects.filter(rel="owns", dst_type="artifact", dst_id=art["id"],
                            src_type="task", src_id="task-51").update(src_id="task-59")
        cards += 1
    shared = 0
    for share in PublicPage.objects.filter(rel__startswith=OLD + "/").values("token", "rel"):
        PublicPage.objects.filter(token=share["token"]).update(rel=moved(share["rel"]))
        shared += 1
    asked = 0
    for thread in AskThread.objects.filter(doc__startswith=OLD + "/").values("id", "doc"):
        AskThread.objects.filter(id=thread["id"]).update(doc=moved(thread["doc"]))
        asked += 1

    back = ""
    parallel = read_json(root / PARALLEL / ".object.json")
    if parallel.get("id") == "task-51" and Task.objects.filter(id="task-51").exists():
        Task.objects.filter(id="task-51").update(
            folder=PARALLEL, slug="parallel-feature-runs-merging",
            title=str(parallel.get("title") or "").strip() or "Parallel feature runs merging",
            updated_at=now)
        back = f"; task 51 is {PARALLEL} again"
    say(f"{'made' if made else 'kept'} task-59 at {NEW}, under Assistant, with {steps} "
        f"step(s); {cards} card(s), {shared} public link(s) and {asked} Ask AI "
        f"thread(s) follow its files{back}")

    # The content index is derived, and these rows' files have moved: read
    # them again now rather than leaving search pointing at the old folder.
    try:
        from rouh import objects, objecttree

        objecttree.refresh(root, objects.ObjectStore(),
                           ["task-59", "task-51", *STEPS])
    except Exception as exc:  # derived; never a reason the deploy fails
        say(f"the search index for them was not rebuilt: {exc}")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0006_remove_empty_task_copies"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
