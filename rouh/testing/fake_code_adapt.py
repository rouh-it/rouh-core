"""Deterministic adaptation plans for the stack's fictional master changes, no model spend.

Called by the Messages stand-in only for the adapting-job rule. Unknown purposes wait, so this
cannot quietly bless a new fixture. Each plan includes behavioural assertions run by the guard.
"""
from __future__ import annotations

import json


def matches(body: dict) -> bool:
    return "When adapting a released master change," in json.dumps(body.get("system", ""))


def answer(body: dict) -> str:
    content = body.get("messages", [{}])[-1].get("content", "")
    if isinstance(content, list):
        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
    try:
        context = json.loads(content)
    except (ValueError, TypeError):
        return json.dumps({"waiting": "The stand-in received no change context."})
    purpose = context.get("change", {}).get("purpose", "")
    if purpose == "Stack release 1":
        local = context["local_files"]["README.md"]
        return json.dumps({"reason": "Kept this Rouh's own title and added the release's purpose below it.",
                           "files": {"docs/stack-release-1.md": "New in release 1.\n"},
                           "edits": {"README.md": [{"before": local.splitlines()[0],
                                                   "after": local.splitlines()[0] + "\n\nRelease 1 words, fitted to this Rouh."}]},
                           "proof": "from pathlib import Path\n"
                                    "s=Path('README.md').read_text()\n"
                                    "assert s.startswith('# Rouh (this Rouh own words)')\n"
                                    "assert 'Release 1 words, fitted' in s\n"
                                    "assert 'New in release 1' in Path('docs/stack-release-1.md').read_text()\n"})
    if purpose == "Stack release 3":
        return json.dumps({"reason": "Closed the access hole while keeping the local greeting.",
                           "files": {"rouh/stack_access.py": "GREETING = 'local greeting'\ndef allowed(name):\n return name == 'owner'\n"},
                           "proof": "import json\nfrom rouh.stack_access import allowed,GREETING\n"
                                    "assert GREETING == 'local greeting'\nv=allowed('stranger')\n"
                                    "print('ROUH-SECURITY '+json.dumps({'vulnerable':v,'checks':['stranger denied','local greeting kept']}))\n"
                                    "raise SystemExit(1 if v else 0)\n"})
    if purpose == "Stack release 4":
        migration = ("from django.db import migrations\nclass Migration(migrations.Migration):\n"
                     " dependencies=[('rouh','9000_local_update_memory')]\n"
                     " operations=[migrations.RunSQL('ALTER TABLE update_memory_local ADD COLUMN source text',"
                     "'ALTER TABLE update_memory_local DROP COLUMN source')]\n")
        return json.dumps({"reason": "Added master's field to this Rouh's renamed memory table, preserving its local column.",
                           "files": {"rouh/migrations/9001_master_update.py": migration},
                           "database_plan": {"tables": {}, "columns": {},
                                             "restore": "Restore the protected immediately-before.dump into a new database, check it, then switch database names and start the preceding undo point."},
                           "proof": "import django;django.setup()\nfrom django.db import connection\n"
                                    "with connection.cursor() as c:\n"
                                    " c.execute('SELECT body,local_word,source FROM update_memory_local ORDER BY id')\n"
                                    " assert c.fetchall()==[('memory one','local one',None),('memory two','local two',None)]\n"})
    if purpose == "Stack release 5":
        return json.dumps({"reason": "Improved the naming note while preserving the local title.",
                           "edits": {"README.md": [{"before": context["local_files"]["README.md"].splitlines()[0],
                                                   "after": context["local_files"]["README.md"].splitlines()[0] + "\n\nMaster improved naming again."}]},
                           "proof": "from pathlib import Path\ns=Path('README.md').read_text()\n"
                                    "assert s.startswith('# Rouh (this Rouh own words)')\n"
                                    "assert 'Master improved naming again.' in s\n"})
    return json.dumps({"waiting": "No deterministic adaptation plan for this fictional purpose."})
