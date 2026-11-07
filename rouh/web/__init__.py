"""Rouh's web layer, in Django: the sign-in gate, the views, the websocket.

Every address Rouh answers is in `rouh/project/urls.py` and every view is in
this package. What the views do is ask the rest of Rouh - the stores, the
model loop, the one program - and hand back what it said: the work itself is
never written here.
"""
