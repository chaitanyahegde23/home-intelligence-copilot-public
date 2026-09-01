from __future__ import annotations

import argparse
import getpass

from app.db.session import SessionLocal
from app.services.authentication import (
    BootstrapError,
    create_bootstrap_owner,
    reset_owner_password,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Home Intelligence Copilot operator commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-owner", help="create the initial household owner")
    create.add_argument("--login", required=True)
    create.add_argument("--household-name", default="Home household")
    reset = subparsers.add_parser("reset-owner-password", help="reset an owner password")
    reset.add_argument("--login", required=True)
    args = parser.parse_args()

    password = _prompt_password()
    with SessionLocal() as session:
        try:
            if args.command == "create-owner":
                create_bootstrap_owner(
                    session,
                    login=args.login,
                    password=password,
                    household_name=args.household_name,
                )
            else:
                reset_owner_password(session, login=args.login, new_password=password)
        except BootstrapError as exc:
            parser.error(str(exc))


def _prompt_password() -> str:
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("passwords do not match")
    return password


if __name__ == "__main__":
    main()
