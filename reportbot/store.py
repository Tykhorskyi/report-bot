"""SQLite persistence for expenses.

Kept deliberately small: one table, plain SQL, no ORM. Every query is
parameterised, and money is stored in integer cents so no float rounding
error can creep into a total.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'EUR',
    category    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    spent_on    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_user_date
    ON expenses (user_id, spent_on);
"""


@dataclass(frozen=True)
class Expense:
    id: int
    user_id: int
    amount_cents: int
    currency: str
    category: str
    note: str
    spent_on: str

    @property
    def amount(self) -> float:
        return self.amount_cents / 100


class ExpenseStore:
    """Thin data-access layer over SQLite."""

    def __init__(self, path: str | Path = "expenses.db") -> None:
        self.path = str(path)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self,
        user_id: int,
        amount_cents: int,
        category: str,
        note: str = "",
        currency: str = "EUR",
        spent_on: str | None = None,
    ) -> int:
        if amount_cents <= 0:
            raise ValueError("amount must be positive")

        spent_on = spent_on or date.today().isoformat()

        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount_cents, currency, category, note, spent_on)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, amount_cents, currency, category.lower().strip(), note.strip(), spent_on),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def delete(self, user_id: int, expense_id: int) -> bool:
        """Delete one row. Scoped by user_id so nobody can delete someone else's."""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_between(self, user_id: int, start: str, end: str) -> list[Expense]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE user_id = ? AND spent_on BETWEEN ? AND ?"
                " ORDER BY spent_on, id",
                (user_id, start, end),
            ).fetchall()
        return [
            Expense(
                id=row["id"],
                user_id=row["user_id"],
                amount_cents=row["amount_cents"],
                currency=row["currency"],
                category=row["category"],
                note=row["note"],
                spent_on=row["spent_on"],
            )
            for row in rows
        ]

    def totals_by_category(self, user_id: int, start: str, end: str) -> list[tuple[str, int]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT category, SUM(amount_cents) AS total FROM expenses"
                " WHERE user_id = ? AND spent_on BETWEEN ? AND ?"
                " GROUP BY category ORDER BY total DESC",
                (user_id, start, end),
            ).fetchall()
        return [(row["category"], int(row["total"])) for row in rows]

    def total(self, user_id: int, start: str, end: str) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM expenses"
                " WHERE user_id = ? AND spent_on BETWEEN ? AND ?",
                (user_id, start, end),
            ).fetchone()
        return int(row["total"])
