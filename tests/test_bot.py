"""Tests for parsing, storage and command handling. No Telegram token needed."""

import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from reportbot.bot import handle_command
from reportbot.parsing import ParseError, format_money, parse_expense, period_bounds
from reportbot.reports import render_csv, render_summary
from reportbot.store import ExpenseStore

TODAY = date(2026, 8, 6)  # a Thursday


class ParsingTests(unittest.TestCase):
    def test_simple_amount_and_category(self):
        parsed = parse_expense("12.50 lunch with client")
        self.assertEqual(parsed.amount_cents, 1250)
        self.assertEqual(parsed.category, "lunch")
        self.assertEqual(parsed.note, "with client")
        self.assertEqual(parsed.currency, "EUR")

    def test_comma_decimal_separator(self):
        self.assertEqual(parse_expense("12,5 taxi").amount_cents, 1250)

    def test_thousands_separator_is_not_a_decimal(self):
        self.assertEqual(parse_expense("1,500 rent").amount_cents, 150000)

    def test_space_as_thousands_separator(self):
        self.assertEqual(parse_expense("1 200 rent").amount_cents, 120000)

    def test_currency_symbol(self):
        parsed = parse_expense("€40 taxi")
        self.assertEqual(parsed.currency, "EUR")
        self.assertEqual(parsed.amount_cents, 4000)

    def test_currency_code(self):
        parsed = parse_expense("40 USD hotel")
        self.assertEqual(parsed.currency, "USD")
        self.assertEqual(parsed.category, "hotel")

    def test_short_word_is_not_mistaken_for_currency(self):
        parsed = parse_expense("15 gas station")
        self.assertEqual(parsed.currency, "EUR")
        self.assertEqual(parsed.category, "gas")
        self.assertEqual(parsed.note, "station")

    def test_rejects_message_without_amount(self):
        with self.assertRaises(ParseError):
            parse_expense("bought some coffee")

    def test_rejects_amount_without_category(self):
        with self.assertRaises(ParseError):
            parse_expense("12.50")

    def test_rejects_zero(self):
        with self.assertRaises(ParseError):
            parse_expense("0 lunch")

    def test_money_formatting(self):
        self.assertEqual(format_money(150000), "€1,500.00")
        self.assertEqual(format_money(4000, "USD"), "$40.00")


class PeriodTests(unittest.TestCase):
    def test_today(self):
        self.assertEqual(period_bounds("today", TODAY), ("2026-08-06", "2026-08-06"))

    def test_week_starts_on_monday(self):
        self.assertEqual(period_bounds("week", TODAY), ("2026-08-03", "2026-08-06"))

    def test_month_to_date(self):
        self.assertEqual(period_bounds("month", TODAY), ("2026-08-01", "2026-08-06"))

    def test_explicit_month_uses_real_last_day(self):
        self.assertEqual(period_bounds("2026-02", TODAY), ("2026-02-01", "2026-02-28"))
        self.assertEqual(period_bounds("2028-02", TODAY), ("2028-02-01", "2028-02-29"))

    def test_rejects_nonsense_period(self):
        with self.assertRaises(ParseError):
            period_bounds("last-tuesday", TODAY)

    def test_rejects_month_13(self):
        with self.assertRaises(ParseError):
            period_bounds("2026-13", TODAY)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExpenseStore(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_total(self):
        self.store.add(1, 1250, "lunch", spent_on="2026-08-01")
        self.store.add(1, 4000, "taxi", spent_on="2026-08-02")
        self.assertEqual(self.store.total(1, "2026-08-01", "2026-08-31"), 5250)

    def test_totals_sorted_by_amount(self):
        self.store.add(1, 1000, "lunch", spent_on="2026-08-01")
        self.store.add(1, 5000, "rent", spent_on="2026-08-01")
        self.store.add(1, 2000, "lunch", spent_on="2026-08-02")
        self.assertEqual(
            self.store.totals_by_category(1, "2026-08-01", "2026-08-31"),
            [("rent", 5000), ("lunch", 3000)],
        )

    def test_users_cannot_see_each_others_data(self):
        self.store.add(1, 1000, "lunch", spent_on="2026-08-01")
        self.store.add(2, 9999, "yacht", spent_on="2026-08-01")
        self.assertEqual(self.store.total(1, "2026-08-01", "2026-08-31"), 1000)

    def test_users_cannot_delete_each_others_data(self):
        expense_id = self.store.add(1, 1000, "lunch", spent_on="2026-08-01")
        self.assertFalse(self.store.delete(2, expense_id))
        self.assertTrue(self.store.delete(1, expense_id))

    def test_date_range_is_respected(self):
        self.store.add(1, 1000, "lunch", spent_on="2026-07-31")
        self.store.add(1, 2000, "lunch", spent_on="2026-08-01")
        self.assertEqual(self.store.total(1, "2026-08-01", "2026-08-31"), 2000)

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            self.store.add(1, 0, "lunch")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ExpenseStore(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def reply(self, text, user_id=1):
        return handle_command(self.store, user_id, text, today=TODAY)

    def test_plain_message_records_expense(self):
        reply = self.reply("12.50 lunch with client")
        self.assertIn("€12.50", reply.text)
        self.assertEqual(self.store.total(1, "2026-08-01", "2026-08-31"), 1250)

    def test_running_total_accumulates(self):
        self.reply("10 lunch")
        reply = self.reply("15 taxi")
        self.assertIn("This month: €25.00", reply.text)

    def test_bad_input_explains_itself(self):
        reply = self.reply("just some text")
        self.assertIn("⚠️", reply.text)
        self.assertIn("Example", reply.text)

    def test_report_shows_breakdown(self):
        self.reply("30 rent")
        self.reply("10 lunch")
        reply = self.reply("/report month")
        self.assertIn("rent", reply.text)
        self.assertIn("€40.00", reply.text)

    def test_report_on_empty_period(self):
        self.assertIn("No expenses", self.reply("/report 2020-01").text)

    def test_group_chat_command_suffix_is_handled(self):
        self.reply("10 lunch")
        self.assertIn("lunch", self.reply("/report@ExpenseBot month").text)

    def test_invalid_period_is_reported(self):
        self.assertIn("⚠️", self.reply("/report last-tuesday").text)

    def test_csv_export_returns_document(self):
        self.reply("12.50 lunch with client")
        reply = self.reply("/csv month")
        self.assertIsNotNone(reply.document)
        self.assertTrue(reply.filename.endswith(".csv"))

        rows = list(csv.DictReader(io.StringIO(reply.document.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["category"], "lunch")
        self.assertEqual(rows[0]["amount"], "12.50")

    def test_csv_export_when_nothing_recorded(self):
        reply = self.reply("/csv month")
        self.assertIsNone(reply.document)
        self.assertIn("Nothing recorded", reply.text)

    def test_undo_removes_last_entry(self):
        self.reply("10 lunch")
        self.reply("20 taxi")
        reply = self.reply("/undo")
        self.assertIn("taxi", reply.text)
        self.assertEqual(self.store.total(1, "2026-08-01", "2026-08-31"), 1000)

    def test_undo_with_nothing_to_undo(self):
        self.assertIn("nothing to undo", self.reply("/undo").text)

    def test_unknown_command(self):
        self.assertIn("don't know", self.reply("/teleport").text)

    def test_help(self):
        self.assertIn("/report", self.reply("/help").text)


class ReportTests(unittest.TestCase):
    def test_summary_has_bars_and_total(self):
        summary = render_summary([("rent", 50000), ("lunch", 10000)],
                                 "2026-08-01", "2026-08-06")
        self.assertIn("█", summary)
        self.assertIn("83.3%", summary)
        self.assertIn("€600.00", summary)

    def test_summary_when_empty(self):
        self.assertIn("No expenses", render_summary([], "2026-08-01", "2026-08-06"))

    def test_csv_has_bom_for_excel(self):
        from reportbot.store import Expense
        payload = render_csv([Expense(1, 1, 1250, "EUR", "lunch", "note", "2026-08-01")])
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
