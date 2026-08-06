"""Entry point: python -m reportbot"""

import logging
import os
import sys

from .bot import run


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN is not set", file=sys.stderr)
        return 2

    run(token, database=os.environ.get("DATABASE_PATH", "expenses.db"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
