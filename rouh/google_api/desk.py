"""What the assistant's own tools reach for: `GoogleDesk`, which knows whose
Google account to open.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..google_oauth import NotConnected, missing_for_every_call
from ..tenancy import Identity

if TYPE_CHECKING:
    from .clients import GoogleClients, Services


class GoogleDesk:
    """One object the tools use, which knows whose Google account to open.

    A tool runs inside a spoken turn, where there is no HTTP request to read a
    session off. So the person comes from the `ContextVar` the websocket sets
    for the life of the connection (`tenancy.speaking`), which every task the
    turn starts inherits. Failing that - a background job, a command - the one
    account this install has is meant; with more than one account and nobody
    named, the answer is "I do not know whose", because the next step would
    read somebody's mail.
    """

    def __init__(self, tenancy, store, clients: GoogleClients, audit=None) -> None:
        self._tenancy = tenancy
        self._store = store
        self._clients = clients
        #: Where every write is written down. See `google_audit.py`.
        self.audit = audit

    def person(self) -> Identity | None:
        from ..tenancy import speaker

        return speaker() or self._tenancy.only_person()

    def state(self) -> str:
        """Which of the six states this is in, in one word.

        "ready", "nobody", "not-set-up", "not-connected", "needs-more-access"
        or "needs-reconnect". The fifth is the one worth telling apart: nothing
        is broken, the person granted a narrower set of permissions than Rouh
        now asks for, and one press of Connect fixes it.
        """
        who = self.person()
        if who is None:
            return "nobody"
        if not self._store.client_summary(who.org_id)["configured"]:
            return "not-set-up"
        held = self._store.connection(who.user_id, who.org_id)
        if held is None:
            return "not-connected"
        # Only what stops every call. A grant without Calendar is still ready
        # for mail, Drive and Docs, and every calendar call says for itself
        # that Calendar is missing (`google_oauth.CHECKED_PER_CALL`).
        if missing_for_every_call(held.scopes):
            return "needs-more-access"
        if held.needs_reconnect:
            return "needs-reconnect"
        return "ready"

    def not_ready_because(self) -> str:
        """The sentence to say instead of an answer, or empty when it is ready.

        Marked as Rouh's own words (`rouh/untrusted.py`): mail and Drive
        results are boxed as somebody else's, and this is not one of those. It
        is this machine saying it cannot reach Google yet, and boxing it as a
        quoted email would be a lie about who said it.
        """
        from ..untrusted import ours

        state = self.state()
        if state == "needs-more-access":
            from ..google_oauth import why_reconnect

            who = self.person()
            held = self._store.connection(who.user_id, who.org_id) if who else None
            return ours(why_reconnect(missing_for_every_call(held.scopes if held else ())))
        return ours({
            "nobody": (
                "I cannot tell whose Google account to use from here. Ask me from a "
                "conversation you are signed in to."),
            "not-set-up": (
                "Google is not set up for this organisation yet. An administrator has "
                "to register a Google Cloud OAuth client in Settings first."),
            "not-connected": (
                "No Google account is connected yet. Open Settings and press "
                "Connect Google."),
            "needs-reconnect": (
                "Google has withdrawn this connection. Open Settings and connect the "
                "account again."),
        }.get(state, ""))

    def services(self) -> Services:
        who = self.person()
        if who is None:
            raise NotConnected("There is nobody here whose Google account this could be.")
        return self._clients.for_user(who)

    def address(self) -> str:
        """The address of the Google account the person here connected, or "".

        The account mail is sent from, and so one place the person's own address
        is known (`outbox.recipient`). Never raises.
        """
        try:
            who = self.person()
            held = self._store.connection(who.user_id, who.org_id) if who else None
        except Exception:
            return ""
        return str(held.google_email or "") if held else ""

    def wrote(self, tool: str, target: str, summary: str, *, account: str = "") -> None:
        """Record one write, against the person whose account it happened in.

        Called by every tool that changes anything, straight after Google says
        it worked. Never raises: a message that has been sent has been sent,
        whatever this machine's disk is doing. `account` is the Google account
        it happened in when that is not the connection's: a forward from one
        of the person's own inboxes (`inboxes.open_to_forward`).
        """
        if self.audit is None:
            return
        who = self.person()
        held = (self._store.connection(who.user_id, who.org_id) if who and not account
                else None)
        self.audit.wrote(
            tool, target, summary,
            user_id=who.user_id if who else "", org_id=who.org_id if who else "",
            account=account or (held.google_email if held else ""))
