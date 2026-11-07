# The workspace

This is the owner's workspace: the projects, tasks and steps Rouh and its background jobs work in.
It was made empty by `python manage.py setup` (SETUP.md in Rouh's repository).

## Layout

```
_migration-map.json     every object: its id, its type, its owner; written by Rouh's own commands
bin/                    task (a task's status and summary, in Rouh's database)
work/                   Work, a project at the top
private/                Personal, a project at the top
  misc/                 Miscellaneous, where a task Rouh cannot place is filed
```

A task is a numbered folder under the project that owns it, `work/acme/12.pricing`, with its steps inside it, `12-01.first-look`.
Make projects, tasks and steps with Rouh, or with `rouh objecttree create` (Rouh's `bin/rouh`) from inside the workspace; never by hand.
