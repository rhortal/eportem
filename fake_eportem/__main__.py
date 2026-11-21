"""Run the fake ePortem on its own, for trying the service locally.

    python -m fake_eportem --port 8081 --account ALICE:secret --account BOB:pw:7,8,9

An account is USER:PASSWORD, optionally followed by :OFFICE,HOME,LUNCH activity
IDs. Control endpoints: GET /_fake/events, POST /_fake/reset,
POST /_fake/faults (a JSON Fault), POST /_fake/expire ({"username": ...}).
Never expose it beyond your machine: it accepts the passwords given here.
"""
import argparse
import time

from checkin.core.activities import ActivityIds
from fake_eportem.server import Account, FakeEportem


def parse_account(text):
    parts = text.split(":")
    if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError("expected USER:PASSWORD or USER:PASSWORD:OFFICE,HOME,LUNCH")
    if len(parts) == 2:
        return Account(parts[0], parts[1])
    ids = parts[2].split(",")
    if len(ids) != 3 or not all(ids):
        raise argparse.ArgumentTypeError("activity IDs must be OFFICE,HOME,LUNCH")
    return Account(parts[0], parts[1], ActivityIds(*ids))


def main(argv=None):
    parser = argparse.ArgumentParser(description="A fake ePortem for development.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--account", type=parse_account, action="append", required=True)
    parser.add_argument("--recaptcha", action="store_true", help="serve a stub reCAPTCHA script")
    parser.add_argument("--session-ttl", type=float, default=None, help="seconds a login lasts")
    args = parser.parse_args(argv)
    fake = FakeEportem(args.account, recaptcha=args.recaptcha, session_ttl=args.session_ttl,
                       host=args.host, port=args.port).start()
    print(f"Fake ePortem on {fake.base_url} with {len(args.account)} account(s); Ctrl-C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        fake.stop()


if __name__ == "__main__":
    main()
