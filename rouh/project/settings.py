"""Django's settings for Rouh.

Every value that differs between the server, a laptop and the browser
environment is read through `rouh/config.py`, which is where every setting
Rouh has always read lives, with its reasoning. This file only turns those
into the shape Django asks for, and says why each Django default was kept or
changed.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from rouh.config import config

#: The repository root: `manage.py` is here.
BASE_DIR = Path(__file__).resolve().parents[2]


def _secret_key() -> str:
    """The key sessions and CSRF tokens are signed with.

    From the environment when it is set there, and otherwise made once and
    kept beside the data with mode 0600, the way the credential key already is
    (`rouh/encryption.py`). A key that changed on every restart would sign
    every browser out on every deploy.
    """
    said = os.environ.get("ROUH_SECRET_KEY") or os.environ.get("DJANGO_SECRET_KEY")
    if said:
        return said
    path = os.path.join(config.data_dir, "django-secret.key")
    try:
        with open(path, encoding="utf-8") as fh:
            kept = fh.read().strip()
        if kept:
            return kept
    except OSError:
        pass
    made = secrets.token_urlsafe(50)
    try:
        os.makedirs(config.data_dir, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        # Somebody who may not write the data directory - a command run as
        # another user, a script that only wanted a constant from a module -
        # gets a key for this process alone. Nothing it signs outlives it,
        # which for anything but the server itself is exactly right.
        return made
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(made + "\n")
    return made


SECRET_KEY = _secret_key()

#: Never on the server. A traceback page is a map of the machine.
DEBUG = os.environ.get("ROUH_DEBUG", "").lower() in {"1", "true", "yes", "on"}

#: The public names (`ROUH_PUBLIC_HOSTS` and the public URL's own, the
#: installation's, blank on a fresh one until its installer sets them), and
#: this machine itself (the old jarvis and rou
#: names are retired: "use rouh and forget about jarvis and rou", Petar,
#: 23 September 2026): the crew's hooks and the deploy's health check come
#: straight to 127.0.0.1:8021, and the browser environment serves on 127.0.0.1
#: too. The socket's origin check (`asgi.py`) reads this same list.
ALLOWED_HOSTS = sorted({
    host for host in (
        *config.public_host_list(),
        "127.0.0.1", "localhost", "[::1]", "::1",
        *[h.strip() for h in os.environ.get("ROUH_ALLOWED_HOSTS", "").split(",")],
    ) if host
})

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "channels",
    "rouh.apps.RouhConfig",
]

MIDDLEWARE = [
    # Email addresses show as themselves through Cloudflare, which would otherwise turn
    # them into "[email protected]" (`rouh/web/addresses.py`). First, so it marks the
    # page every other one has finished with.
    "rouh.web.addresses.AddressesAsThemselves",
    "django.middleware.security.SecurityMiddleware",
    # Secure on the cookies of a request that came in over https, and only
    # then (`rouh/web/gate.py`). Before the session middleware in this list so
    # it sees the cookie that one sets.
    "rouh.web.gate.SecureCookiesWhenHttps",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "rouh.web.owner_marks.OwnerMarks",
    # Demo mode (`rouh/web/demo.py`): codes in an address put back to real names on the way in,
    # and every answer blurred on the way out while the person is in demo mode. After the sign-in,
    # which says whose demo mode it is. Inside OwnerMarks, so an interface sentence with the
    # owner's mark in it is recognised as the interface's before the mark is filled in.
    "rouh.web.demo.DemoLens",
    "django.contrib.messages.middleware.MessageMiddleware",
    # The gate: every address answers only to a signed-in person, except the
    # handful `rouh/web/gate.py` names. After authentication, because that is
    # what says who the person is.
    "rouh.web.gate.SignInRequired",
]

ROOT_URLCONF = "rouh.project.urls"
ASGI_APPLICATION = "rouh.project.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- the database -------------------------------------------------------------

DATABASES = {
    "default": {
        # PostgreSQL, with one thing added: a connection that broke - the
        # database restarted underneath a long-lived process - is noticed and
        # opened again on the next query instead of failing every query after
        # it (`rouh/project/db/base.py`).
        "ENGINE": "rouh.project.db",
        "NAME": config.db_name,
        "USER": config.db_user,
        "PASSWORD": config.db_password_now(),
        "HOST": config.db_host,
        "PORT": config.db_port,
        # Lent, not kept: every connection comes from one bounded pool and goes
        # back after each request, each call handed to a thread and each beat,
        # and when a thread ends (`rouh/project/db/base.py`, `rouh/dbwork.py`).
        # Until 21 October 2026 each thread kept its own for ever, and a web
        # request's throwaway thread left one behind every time, which filled
        # PostgreSQL several times an hour (task 137). Django's pool needs 0.
        "CONN_MAX_AGE": 0,
        # Checked as it is lent, so a database restart costs no failed query.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "application_name": "rouh",
            "connect_timeout": 5,
            "pool": {
                "name": "rouh",
                # Kept open when nothing asks; it grows at once when something
                # does. Small, because every manage.py command has a pool too.
                "min_size": int(os.environ.get("ROUH_DB_POOL_MIN") or 2),
                # The most this process ever holds of PostgreSQL. Measured on
                # 21 October 2026: one or two at work at a time; bursts of
                # imports, backfills and dreaming can ask for up to about 40,
                # and background never has more than this less 12.
                "max_size": int(os.environ.get("ROUH_DB_POOL_MAX") or 50),
                # Waiting borrowers beyond this are told at once that it is busy.
                "max_waiting": 200,
                # How long a borrower waits is decided per thread in
                # `rouh/project/db/base.py`; this is only the pool's default.
                "timeout": 10,
                "max_idle": 600,
                "max_lifetime": 3600,
            },
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

#: Only for a check of your own that needs a model changed before the real
#: migration is written: point Django at a copy of `rouh/migrations/` in your
#: scratch folder instead of the committed one. Never set on the server.
if os.environ.get("ROUH_MIGRATIONS_MODULE"):
    MIGRATION_MODULES = {"rouh": os.environ["ROUH_MIGRATIONS_MODULE"]}

# --- accounts and signing in --------------------------------------------------

AUTH_USER_MODEL = "rouh.User"

AUTHENTICATION_BACKENDS = [
    # Django's own, with the username matched regardless of case, which is how
    # the accounts table always matched it (`rouh/accounts.py`).
    "rouh.accounts.CaseInsensitiveBackend",
]

PASSWORD_HASHERS = [
    # scrypt: what Rouh has always used, now through Django. 16 MB of memory
    # per guess is what makes a stolen database expensive to attack.
    "django.contrib.auth.hashers.ScryptPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    # The hashes the old accounts table held, so a password that worked the
    # day before the move still works the day after. Django rewrites each one
    # into the first hasher above the first time it is used.
    "rouh.accounts.LegacyScryptHasher",
]

#: Every form that sets a password lists these, in this order, and ticks each
#: off as the password is typed (`rouh/password_rules.py`), so a change here is
#: a change there too. Ten characters, not twelve: Petar, 24 September 2026
#: (fr_a5aa0123f5d1).
AUTH_PASSWORD_VALIDATORS = [
    # Letters, numbers, symbols and length, in that order on every form that sets a password
    # (Petar, 8 November 2026, task 176; `rouh/password_rules.py`).
    {"NAME": "rouh.password_rules.HasLetterValidator"},
    {"NAME": "rouh.password_rules.HasNumberValidator"},
    {"NAME": "rouh.password_rules.HasSymbolValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"

#: How long the link a forgotten password is answered with keeps working
#: (`rouh/password_reset.py`). An hour: long enough to find the email, short
#: enough that an old one found in a mailbox later is no good to anybody.
PASSWORD_RESET_TIMEOUT = 60 * 60

#: The sign-in cookie. Named as it was, so the name in a browser's cookie jar
#: still says what it is; the value is Django's session key now, so everybody
#: signs in once after the move, which is expected.
SESSION_COOKIE_NAME = "rouh_session"
#: How long a sign-in lasts, counted from the last time it was used: long,
#: because the person signs in on their phone and their laptop; finite,
#: because a browser left in a hotel should stop working on its own. The gate
#: pushes the end back once a day rather than on every request.
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_SAVE_EVERY_REQUEST = False

#: The CSRF token travels in a cookie the page's own script reads and sends
#: back as a header on every write (`rouh/static/csrf.js`). Named for Rouh so
#: it cannot collide with another app on the same parent domain.
CSRF_COOKIE_NAME = "rouh_csrftoken"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
CSRF_TRUSTED_ORIGINS = sorted({
    origin for origin in (
        config.public_url.rstrip("/"),
        *[f"https://{host}" for host in config.public_host_list()],
        *[o.strip() for o in os.environ.get("ROUH_CSRF_TRUSTED_ORIGINS", "").split(",")],
    ) if origin
})
CSRF_FAILURE_VIEW = "rouh.web.gate.csrf_failure"

# --- behind nginx ---------------------------------------------------------------

#: nginx is the only way in from outside and it says whether the browser came
#: over https. A request straight to 127.0.0.1 has no such header and is http.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
#: Not redirected here: nginx only listens on 443, and the hooks and the
#: health check on 127.0.0.1 are http on purpose.
SECURE_SSL_REDIRECT = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
#: X-Frame-Options is set per response, not everywhere: a workspace page is
#: framed by Rouh's own page on purpose (`rouh/pages.py`).
X_FRAME_OPTIONS = "SAMEORIGIN"

#: A request body big enough for what nginx lets through. Files have their own
#: ceiling (`rouh/attachments.py`) and are spooled to disk past a few megabytes.
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- the page's own files ---------------------------------------------------------

#: Rouh's front end is `rouh/static/`, served by Rouh itself at `/a/<stamp>/`
#: with a fingerprint in the address (`rouh/web/assets.py`), and at `/static/`
#: for an old bookmark and for the Django admin's own files.
STATIC_URL = "/static/"

# --- the websocket ------------------------------------------------------------------

#: One process, and nothing sends to a socket from anywhere but inside it, so
#: there is no channel layer: the tabs are held in memory (`Hub` in
#: `rouh/runtime.py`), as they always were.
CHANNEL_LAYERS: dict = {}

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

#: Rouh configures its own logging (`rouh/runtime.py`) and Django's lines go
#: to the same place through the root logger.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "django": {"level": "INFO", "propagate": True},
        "django.request": {"level": "WARNING", "propagate": True},
    },
}
