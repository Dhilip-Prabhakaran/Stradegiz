"""Store today's Upstox access token.

    docker compose run --rm backend python -m app.set_token PASTE_TOKEN_HERE

Deliberately a CLI, not an HTTP endpoint: writing a token is a privileged
action and the API has no auth yet, so this keeps the write local to the host
rather than exposing it on the network. An authenticated UI form can replace
this once auth lands.
"""

from __future__ import annotations

import argparse

from . import auth


def main() -> None:
    parser = argparse.ArgumentParser(description="Store today's Upstox access token")
    parser.add_argument("token", help="the access_token from your Upstox login")
    args = parser.parse_args()

    st = auth.save_token(args.token)
    print("token stored.")
    print(f"  issued  : {st.issued_at}")
    print(f"  expires : {st.expires_at}  (Upstox fixed 03:30 IST)")
    print(f"  valid   : {st.valid}")


if __name__ == "__main__":
    main()
