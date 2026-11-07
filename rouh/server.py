"""The process's front door: the ASGI application uvicorn serves.

    python -m uvicorn rouh.server:app --host 127.0.0.1 --port 8021

This name is what systemd starts (`deploy/run-server.sh`, installed outside
the checkout so a rollback cannot take it away) and what the deploy imports
to check that new code loads before it restarts anything (`deploy/rouh.sh`),
so it stays, whatever is behind it.

Behind it, since 23 September 2026, is Django: `rouh/project/asgi.py` builds
the application, `rouh/project/urls.py` says which view answers each address,
and `rouh/runtime.py` is the process itself - the stores, the voice, the tabs
and the turns - which this file used to be, beside a FastAPI app.
"""
from rouh.project.asgi import application as app

__all__ = ["app"]
