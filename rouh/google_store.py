"""Where an organisation's Google client and a person's Google connection live.

Two tables and one rule.

``google_clients`` holds one row per **organisation**: the OAuth client id and
the encrypted client secret its administrator registered in their own Google
Cloud project. Google will not approve one public Rouh app for the scopes
this needs, so there is no shared client and there is deliberately no fallback
to one: an organisation that has not entered a pair cannot connect anything,
and says so.

``google_connections`` holds one row per **user**: their own Google account,
their own access and refresh tokens, and which capabilities they granted. A
user consents through their organisation's client, and what comes back is
theirs alone.

Every method here takes the ids it is asking about and puts them in the WHERE
clause. `connection` takes both `user_id` and `org_id` even though `user_id`
alone is unique, because a route that has the wrong organisation in hand is
exactly the bug this is guarding against, and an extra column in the WHERE
turns it into "not found" rather than into a leak.

Neither the client secret nor a token is ever returned by anything that builds
an API response. `client_summary` is what Settings is shown; `client_for` is
what the OAuth exchange uses, and only the exchange calls it.

The tables are Django's since 23 September 2026 (`rouh.models.GoogleClient`,
`GoogleConnection`, `GoogleOAuthState`), in PostgreSQL. What goes into them is
exactly what went into the SQLite tables they were before: every secret and
every token sealed by `encryption.SecretBox` first, so a row read by anybody
without this instance's key is ciphertext and nothing else.

A consent state carries a ``purpose`` since the same day. Connecting a
signed-in person's Google account is ``connect``, which is every state this
file's own callers make; signing somebody in with Google is the other one, and
it has nobody to name yet (`rouh/web/sso.py`). Each round trip only ever spends
a state of its own kind, so a state minted to sign somebody in can never be
finished as a connection, or the other way round.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from .encryption import CannotOpen, SecretBox

#: The purpose of every consent state this file's own callers make: a signed-in
#: person connecting their Google account.
CONNECT = "connect"

#: How long a consent may sit unfinished. Long enough to read a Google consent
#: screen carefully, short enough that a state left in a browser history is
#: worthless by the time anyone finds it.
STATE_SECONDS = 15 * 60

#: What a Google OAuth client id looks like. Checked on save so a typo is
#: caught while the person is still looking at the form, rather than as an
#: unreadable error on the consent screen ten minutes later.
CLIENT_ID_SHAPE = re.compile(r"^[A-Za-z0-9\-_.]{6,120}\.apps\.googleusercontent\.com$")

#: The shortest thing Google has ever issued as a client secret is well over
#: this. It only has to catch an empty box and a pasted space.
MIN_SECRET_CHARS = 8


class NotSetUp(RuntimeError):
    """This organisation has not registered a Google OAuth client."""


@dataclass(frozen=True)
class OrgClient:
    """An organisation's OAuth client, opened. Never leaves this process."""

    org_id: str
    client_id: str
    client_secret: str = field(repr=False)
    updated_at: float = 0.0

    def __str__(self) -> str:            # so an f-string cannot print the secret
        return f"<OrgClient {self.org_id} {self.client_id}>"


@dataclass(frozen=True)
class Connection:
    """One person's Google connection, opened."""

    user_id: str
    org_id: str
    google_email: str
    google_account: str
    access_token: str = field(repr=False, default="")
    refresh_token: str = field(repr=False, default="")
    expires_at: float = 0.0
    scopes: tuple[str, ...] = ()
    connected_at: float = 0.0
    needs_reconnect: bool = False
    trouble: str = ""

    def __str__(self) -> str:
        return f"<Connection {self.user_id} {self.google_email}>"


def check_client_id(client_id: str) -> str:
    """The client id, tidied, or a sentence saying what is wrong with it."""
    value = (client_id or "").strip()
    if not value:
        return ""
    if not CLIENT_ID_SHAPE.match(value):
        raise ValueError(
            "That does not look like a Google OAuth client id. It ends in "
            "\".apps.googleusercontent.com\" and Google shows it on the "
            "credential's page in the Cloud console."
        )
    return value


def check_secret(secret: str) -> str:
    value = (secret or "").strip()
    if len(value) < MIN_SECRET_CHARS:
        raise ValueError(
            "The client secret is missing. Copy it from the same credential in "
            "the Google Cloud console; it usually starts with \"GOCSPX-\"."
        )
    return value


class GoogleStore:
    """The two tables, plus the short-lived consent states.

    It used to open the SQLite file it was handed and make its tables. The
    rows are Django's now and the schema is the migrations'; the path is still
    accepted, and not used, so a caller written before the move needs no
    change. `box` is what it always was: the only thing that seals and opens.
    """

    def __init__(self, db_path: str | None, box: SecretBox) -> None:
        self._box = box
        self._lock = threading.Lock()

    # --- the organisation's OAuth client ------------------------------------

    def save_client(self, org_id: str, client_id: str, client_secret: str,
                    *, by_user_id: str = "") -> None:
        """Register or replace one organisation's pair.

        Raises ValueError with a sentence a person can act on when either half
        is not the shape Google issues.
        """
        from .models import GoogleClient

        if not org_id:
            raise ValueError("an OAuth client belongs to an organisation")
        client_id = check_client_id(client_id)
        if not client_id:
            raise ValueError(
                "The client id is missing. Copy it from the credential's page "
                "in the Google Cloud console."
            )
        sealed = self._box.seal(check_secret(client_secret))
        with self._lock:
            GoogleClient.objects.bulk_create(
                [GoogleClient(org_id=org_id, client_id=client_id, secret_sealed=sealed,
                              updated_at=time.time(), updated_by=by_user_id)],
                update_conflicts=True, unique_fields=["org_id"],
                update_fields=["client_id", "secret_sealed", "updated_at", "updated_by"])

    def client_for(self, org_id: str) -> OrgClient:
        """The pair, opened, for the OAuth exchange. Nothing else calls this.

        Raises `NotSetUp` when the organisation has not registered one. There
        is no global client to fall back to, on purpose.
        """
        from .models import GoogleClient

        if not org_id:
            raise NotSetUp("no organisation was named")
        with self._lock:
            row = GoogleClient.objects.filter(org_id=org_id).first()
        if row is None:
            raise NotSetUp("this organisation has not registered a Google OAuth client")
        try:
            secret = self._box.open_(row.secret_sealed)
        except CannotOpen as exc:
            raise NotSetUp(
                "the stored client secret cannot be opened with this instance's "
                "encryption key, so it has to be entered again"
            ) from exc
        return OrgClient(org_id=org_id, client_id=row.client_id,
                         client_secret=secret, updated_at=row.updated_at)

    def client_summary(self, org_id: str) -> dict:
        """What Settings is allowed to show: everything except the secret."""
        from .models import GoogleClient

        if not org_id:
            return {"configured": False, "client_id": "", "secret_set": False,
                    "secret_changed_at": 0}
        with self._lock:
            row = (GoogleClient.objects.filter(org_id=org_id)
                   .values("client_id", "updated_at").first())
        if row is None:
            return {"configured": False, "client_id": "", "secret_set": False,
                    "secret_changed_at": 0}
        return {
            "configured": True,
            "client_id": row["client_id"],
            "secret_set": True,
            "secret_changed_at": row["updated_at"],
        }

    def remove_client(self, org_id: str) -> bool:
        from .models import GoogleClient

        if not org_id:
            return False
        with self._lock:
            gone, _ = GoogleClient.objects.filter(org_id=org_id).delete()
        return gone > 0

    # --- one person's connection --------------------------------------------

    def save_connection(self, user_id: str, org_id: str, *, google_email: str,
                        google_account: str, access_token: str, refresh_token: str,
                        expires_at: float, scopes) -> None:
        from django.db import transaction

        from .models import GoogleConnection

        if not user_id or not org_id:
            raise ValueError("a Google connection belongs to a user in an organisation")
        # A refresh token is only issued on the first consent. Re-consenting
        # without one must not wipe the one already held, or the connection
        # silently stops working the next time the access token expires. The
        # read and the write are one critical section and one transaction: two
        # consents finishing together must not let the second one see the state
        # before the first.
        sealed_refresh = self._box.seal(refresh_token) if refresh_token else ""
        sealed_access = self._box.seal(access_token) if access_token else ""
        with self._lock, transaction.atomic():
            kept = (GoogleConnection.objects.select_for_update()
                    .filter(user_id=user_id, org_id=org_id)
                    .values_list("refresh_sealed", flat=True).first()) or ""
            GoogleConnection.objects.bulk_create(
                [GoogleConnection(
                    user_id=user_id, org_id=org_id, google_email=google_email,
                    google_account=google_account, access_sealed=sealed_access,
                    refresh_sealed=sealed_refresh or kept, expires_at=float(expires_at),
                    scopes=" ".join(scopes or ()), connected_at=time.time(),
                    needs_reconnect=False, trouble="")],
                update_conflicts=True, unique_fields=["user_id"],
                update_fields=["org_id", "google_email", "google_account", "access_sealed",
                               "refresh_sealed", "expires_at", "scopes", "connected_at",
                               "needs_reconnect", "trouble"])

    def connection(self, user_id: str, org_id: str) -> Connection | None:
        """One person's connection, opened. Both ids are required."""
        from .models import GoogleConnection

        if not user_id or not org_id:
            return None
        with self._lock:
            row = GoogleConnection.objects.filter(user_id=user_id, org_id=org_id).first()
        if row is None:
            return None

        def opened(sealed: str) -> str:
            if not sealed:
                return ""
            try:
                return self._box.open_(sealed)
            except CannotOpen:
                return ""
        return Connection(
            user_id=row.user_id, org_id=row.org_id,
            google_email=row.google_email or "",
            google_account=row.google_account or "",
            access_token=opened(row.access_sealed),
            refresh_token=opened(row.refresh_sealed),
            expires_at=row.expires_at or 0.0,
            scopes=tuple((row.scopes or "").split()),
            connected_at=row.connected_at or 0.0,
            needs_reconnect=bool(row.needs_reconnect),
            trouble=row.trouble or "",
        )

    def store_access_token(self, user_id: str, org_id: str, access_token: str,
                           expires_at: float) -> None:
        from .models import GoogleConnection

        with self._lock:
            GoogleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
                access_sealed=self._box.seal(access_token), expires_at=float(expires_at),
                needs_reconnect=False, trouble="")

    def needs_reconnect(self, user_id: str, org_id: str, why: str) -> None:
        """Google has withdrawn the grant. Say so rather than failing later."""
        from .models import GoogleConnection

        with self._lock:
            GoogleConnection.objects.filter(user_id=user_id, org_id=org_id).update(
                needs_reconnect=True, trouble=why[:300], access_sealed="", expires_at=0)

    def forget_connection(self, user_id: str, org_id: str) -> bool:
        from .ghosts import CONNECTION
        from .models import GhostMark, GoogleConnection

        if not user_id or not org_id:
            return False
        with self._lock:
            gone, _ = GoogleConnection.objects.filter(user_id=user_id, org_id=org_id).delete()
            # What the ghost list's snoozes and dismissals were about went with it.
            GhostMark.objects.filter(user_id=user_id, org_id=org_id,
                                     mailbox_id=CONNECTION).delete()
        return gone > 0

    # --- the consent state ---------------------------------------------------

    def remember_state(self, nonce: str, user_id: str, org_id: str,
                       session: str = "", *, purpose: str = CONNECT,
                       next_path: str = "") -> None:
        """Keep one consent state until its callback comes back, or it expires.

        States older than `STATE_SECONDS` are cleared on the way in, so the
        table never holds more than a quarter of an hour of them.
        """
        from django.db import transaction

        from .models import GoogleOAuthState

        with self._lock, transaction.atomic():
            GoogleOAuthState.objects.filter(created_at__lt=time.time() - STATE_SECONDS).delete()
            GoogleOAuthState.objects.bulk_create(
                [GoogleOAuthState(nonce=nonce, user_id=user_id or "", org_id=org_id,
                                  session=session or "", purpose=purpose or CONNECT,
                                  next_path=next_path or "", created_at=time.time())],
                update_conflicts=True, unique_fields=["nonce"],
                update_fields=["user_id", "org_id", "session", "purpose", "next_path",
                               "created_at"])

    def state_purpose(self, nonce: str) -> str | None:
        """Which round trip a state belongs to, without spending it, or None.

        For the one callback address both round trips come back to, so it can
        hand the state to the flow that minted it (`rouh/web/sso.py`).
        """
        from .models import GoogleOAuthState

        if not nonce:
            return None
        with self._lock:
            return (GoogleOAuthState.objects.filter(nonce=nonce)
                    .values_list("purpose", flat=True).first())

    def take_state(self, nonce: str, purpose: str = CONNECT) -> dict | None:
        """Read a state and delete it in the same breath: single use.

        One ``DELETE ... RETURNING``, so the row that is handed back is the
        row that was deleted, and two callbacks arriving at once - which is
        what a double-click on the consent screen produces - cannot both have
        it, even from two processes.

        Only a state of the `purpose` asked for is spent. One of the other kind
        is left exactly where it is and this answers None, so a sign-in state
        brought to the connect flow is refused without being used up.
        """
        from django.db import connection

        if not nonce:
            return None
        with self._lock, connection.cursor() as cur:
            cur.execute(
                "DELETE FROM google_oauth_states WHERE nonce=%s AND purpose=%s"
                " RETURNING user_id, org_id, session, created_at, next_path",
                (nonce, purpose or CONNECT))
            row = cur.fetchone()
        if row is None:
            return None
        user_id, org_id, session, created_at, next_path = row
        if time.time() - created_at > STATE_SECONDS:
            return None
        found = {"user_id": user_id, "org_id": org_id, "session": session}
        if (purpose or CONNECT) != CONNECT:
            found["purpose"] = purpose
            found["next_path"] = next_path or ""
        return found

    def close(self) -> None:
        """Nothing to close: the connection is Django's, one per thread."""
