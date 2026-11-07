"""Every outside service a Rouh talks to, stood in for, in one container of the stack test.

The stack test (tests/stack/run.sh, CONTAINERS.md) brings up the real stack, built from the
change, and nothing in it may reach a real company with a real account. So this runs the same
stand-ins the test worlds use (`rouh/testing/fake_*.py`), each on a fixed port of its own and on
every address of this container, so the core and the key proxy reach them by the name
`standins` and the browser on the test machine reaches the few it has to (Google's and Hue's
sign-in pages) on the ports the test publishes. Nothing here is shipped: it runs from /code
only in the stack test, and FastAPI, which only the stand-ins need, is installed for it there.

    python tests/stack/standins.py --record /standins
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

#: name -> port. The settings file of the stack test (tests/stack/settings.env) points Rouh at
#: these, and the smoke test (tests/stack/smoke.py) reads what each one saw.
PORTS = {
    "model": 9001, "openai": 9002, "compat": 9003, "carddav": 9004, "brevo": 9005,
    "apify": 9006, "voyage": 9007, "stripe": 9008, "cloudflare": 9009, "slack": 9010,
    "hue": 9011, "dreame": 9012, "voice": 9013, "telegram": 9014, "google": 9015,
    "meetings": 9016, "shop": 9017, "youtube": 9018, "s3": 9019,
}

#: The address the browser on the test machine comes back to after Google's consent page.
PUBLIC = os.environ.get("STANDINS_ROUH_URL", "http://127.0.0.1:8420")


def apps(record: str) -> dict:
    from rouh.testing import (fake_apify, fake_brevo, fake_carddav, fake_cloudflare, fake_compat,
                              fake_dreame, fake_google, fake_hue, fake_meeting_library,
                              fake_model, fake_openai, fake_s3, fake_shop, fake_slack, fake_stripe,
                              fake_telegram, fake_voice, fake_voyage, fake_youtube)

    # Slack's Socket Mode address, as the core reaches this container.
    # iCloud names a person's home on a partition host beside the one asked: here a name of this
    # container's under `standins`, which compose.test.yml gives it.
    fake_carddav.PARTITION["host"] = os.environ.get("STANDINS_CARDDAV_PARTITION", "p52.standins")
    fake_slack.PORT.update(n=PORTS["slack"], host=os.environ.get("STANDINS_HOST", "standins"))
    return {
        "model": fake_model.build_app(record),
        "openai": fake_openai.build_app(record),
        "compat": fake_compat.build_app(record),
        "carddav": fake_carddav.build(),
        "brevo": fake_brevo.build_app(os.path.join(record, "mail")),
        "apify": fake_apify.build_app(),
        "voyage": fake_voyage.build_app(record),
        "stripe": fake_stripe.build_app(),
        "cloudflare": fake_cloudflare.app,
        "slack": fake_slack.app,
        "hue": fake_hue.app,
        "dreame": fake_dreame.app,
        "voice": fake_voice.build_app(os.path.join(record, "spoken")),
        "telegram": fake_telegram.build_app(os.path.join(record, "telegram")),
        "google": fake_google.build(f"{PUBLIC}/auth/google/callback", "stack-test-client.apps.googleusercontent.com",
                                    "stack-test-client-secret"),
        "meetings": fake_meeting_library.build_app(fake_meeting_library.KEY),
        "shop": fake_shop.build_app(),
        "youtube": fake_youtube.build_app(),
        "s3": fake_s3.build_app(),
    }


async def serve(record: str) -> None:
    import uvicorn

    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORTS[name], log_level="warning"))
               for name, app in apps(record).items()]
    print("standins: " + ", ".join(f"{n} {p}" for n, p in PORTS.items()) + ", ssh 2222 and 2224, github 9020", flush=True)

    async def echo(reader, writer):
        # The owner's own server, as far as the narrow way to it is concerned: what reaches it
        # comes back, upper case (runs.ssh in tests/stack/checks_runs.py).
        while data := await reader.read(4096):
            writer.write(data.upper())
            await writer.drain()
        writer.close()

    async def github(reader, writer):
        # GitHub, as far as the key proxy's grant is concerned (runs.github in checks_runs.py):
        # every request's Host and Authorization, said back as JSON, and nothing kept.
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        said = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:] if line)}
        body = json.dumps({"request": lines[0], "host": said.get("host", ""),
                           "authorization": said.get("authorization", ""), "cookie": said.get("cookie", "")}).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                     % (len(body), body))
        await writer.drain()
        writer.close()

    async def upsd(reader, writer):
        # NUT's upsd, for a UPS on battery and half full (machine.ups in tests/stack/checks_runs.py).
        while line := await reader.readline():
            if line.startswith(b"LIST VAR"):
                writer.write(b'BEGIN LIST VAR ups\nVAR ups battery.charge "57"\n'
                             b'VAR ups ups.status "OB DISCHRG"\nEND LIST VAR ups\n')
                await writer.drain()
            elif line.startswith(b"LOGOUT"):
                break
        writer.close()

    ssh = await asyncio.start_server(echo, "0.0.0.0", 2222)
    # The owner's server a timed grant opens (runs.proxy-grant): the same echo, on a port no
    # setting lists.
    timed = await asyncio.start_server(echo, "0.0.0.0", 2224)
    hub = await asyncio.start_server(github, "0.0.0.0", 9020)
    ups = await asyncio.start_server(upsd, "0.0.0.0", 3493)
    await asyncio.gather(ssh.serve_forever(), timed.serve_forever(), hub.serve_forever(), ups.serve_forever(),
                         *(s.serve() for s in servers))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", default="/standins")
    a = ap.parse_args()
    for sub in ("", "mail", "spoken", "telegram"):
        os.makedirs(os.path.join(a.record, sub), exist_ok=True)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    asyncio.run(serve(a.record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
