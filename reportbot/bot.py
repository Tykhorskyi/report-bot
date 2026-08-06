"""Telegram command handling.

The command layer is deliberately transport-agnostic: `handle_command`
takes plain arguments and returns a `Reply`, so every rule can be tested
without a Telegram token, a network call or a running bot.

`TelegramClient` is the only part that talks to the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import requests

from .parsing import ParseError, format_money, parse_expense, period_bounds
from .reports import render_csv, render_summary, render_xlsx, report_filename
from .store import ExpenseStore

log = logging.getLogger(__name__)

HELP = """I track expenses and turn them into reports.

Add an expense - just send it:
  12.50 lunch with client
  €40 taxi to airport
  1 200 rent

Commands:
  /report [today|week|month|YYYY-MM] - summary
  /csv    [period] - export as CSV
  /xlsx   [period] - export as Excel with a chart
  /undo - remove your last entry
  /help - this message
"""


@dataclass
class Reply:
    """What the bot wants to send back."""

    text: str
    document: bytes | None = None
    filename: str | None = None
    meta: dict = field(default_factory=dict)


class TelegramClient:
    """Minimal Telegram Bot API client (long polling)."""

    def __init__(self, token: str, session: requests.Session | None = None,
                 timeout: int = 30) -> None:
        if not token:
            raise ValueError("a bot token is required")
        self.base = f"https://api.telegram.org/bot{token}"
        self.session = session or requests.Session()
        self.timeout = timeout

    def get_updates(self, offset: int | None = None) -> list[dict]:
        response = self.session.get(
            f"{self.base}/getUpdates",
            params={"timeout": self.timeout, "offset": offset},
            timeout=self.timeout + 10,
        )
        response.raise_for_status()
        return response.json().get("result", [])

    def send_message(self, chat_id: int, text: str) -> None:
        self.session.post(
            f"{self.base}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=self.timeout,
        ).raise_for_status()

    def send_document(self, chat_id: int, content: bytes, filename: str,
                      caption: str = "") -> None:
        self.session.post(
            f"{self.base}/sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"document": (filename, content)},
            timeout=self.timeout + 30,
        ).raise_for_status()


def handle_command(store: ExpenseStore, user_id: int, text: str,
                   today: date | None = None) -> Reply:
    """Turn one incoming message into a reply. Pure, apart from the store."""
    text = (text or "").strip()
    if not text:
        return Reply("Send me an amount and what it was for, e.g. `12.50 lunch`.")

    if text.startswith("/"):
        command, _, argument = text.partition(" ")
        command = command.split("@")[0].lower()  # /report@MyBot in group chats
        argument = argument.strip()

        if command in {"/start", "/help"}:
            return Reply(HELP)

        if command in {"/report", "/csv", "/xlsx"}:
            try:
                start, end = period_bounds(argument or "month", today)
            except ParseError as exc:
                return Reply(f"⚠️ {exc}")

            totals = store.totals_by_category(user_id, start, end)

            if command == "/report":
                return Reply(render_summary(totals, start, end),
                             meta={"start": start, "end": end})

            expenses = store.list_between(user_id, start, end)
            if not expenses:
                return Reply(f"Nothing recorded between {start} and {end}.")

            if command == "/csv":
                return Reply(
                    f"{len(expenses)} expense(s), {start} to {end}",
                    document=render_csv(expenses),
                    filename=report_filename("expenses", start, end, "csv"),
                )

            return Reply(
                f"{len(expenses)} expense(s), {start} to {end}",
                document=render_xlsx(expenses, totals, start, end),
                filename=report_filename("expenses", start, end, "xlsx"),
            )

        if command == "/undo":
            start, end = "0000-01-01", "9999-12-31"
            expenses = store.list_between(user_id, start, end)
            if not expenses:
                return Reply("There is nothing to undo.")
            last = expenses[-1]
            store.delete(user_id, last.id)
            return Reply(
                f"Removed: {format_money(last.amount_cents, last.currency)} "
                f"on {last.category}"
            )

        return Reply(f"I don't know the command {command}. Try /help")

    try:
        parsed = parse_expense(text)
    except ParseError as exc:
        return Reply(f"⚠️ {exc}\n\nExample: `12.50 lunch with client`")

    store.add(
        user_id=user_id,
        amount_cents=parsed.amount_cents,
        category=parsed.category,
        note=parsed.note,
        currency=parsed.currency,
        spent_on=(today or date.today()).isoformat(),
    )

    start, end = period_bounds("month", today)
    running = store.total(user_id, start, end)

    return Reply(
        f"✅ {format_money(parsed.amount_cents, parsed.currency)} - {parsed.category}\n"
        f"This month: {format_money(running, parsed.currency)}"
    )


def run(token: str, database: str = "expenses.db") -> None:  # pragma: no cover - I/O loop
    """Long-polling loop. Kept dumb on purpose: all logic lives above."""
    store = ExpenseStore(database)
    client = TelegramClient(token)
    offset: int | None = None

    log.info("bot started")

    while True:
        try:
            updates = client.get_updates(offset)
        except requests.RequestException as exc:
            log.warning("getUpdates failed: %s", exc)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("edited_message")
            if not message or "text" not in message:
                continue

            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]

            try:
                reply = handle_command(store, user_id, message["text"])
                if reply.document and reply.filename:
                    client.send_document(chat_id, reply.document, reply.filename, reply.text)
                else:
                    client.send_message(chat_id, reply.text)
            except Exception:  # noqa: BLE001 - one bad message must not kill the bot
                log.exception("failed to handle update %s", update["update_id"])
                try:
                    client.send_message(chat_id, "Something went wrong on my side. Try again.")
                except requests.RequestException:
                    pass
