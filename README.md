# report-bot

A Telegram bot that turns messages like `12.50 lunch with client` into a
tracked expense, and turns tracked expenses into a summary, a CSV, or an Excel
workbook with a chart.

Built as a realistic example of the two things clients ask for most in bot
work: **understanding what a human actually typed**, and **producing a file
their accountant will accept**.

```
You:  12.50 lunch with client
Bot:  ✅ €12.50 - lunch
      This month: €12.50

You:  /report month
Bot:  Expenses 2026-08-01 to 2026-08-06

      rent       €1,200.00  ███████████ 89.7%
      software      €60.00  █  4.5%
      taxi          €40.00  █  3.0%
      lunch         €37.50  █  2.8%

      total      €1,337.50

You:  /xlsx month
Bot:  [expenses_2026-08-01_2026-08-06.xlsx]
```

## The interesting part: input parsing

People don't type consistently. All of these work:

| Message | Parsed as |
|---|---|
| `12.50 lunch with client` | €12.50, lunch, "with client" |
| `12,5 coffee` | €12.50, coffee |
| `1 200 rent august` | €1,200.00, rent, "august" |
| `1,200.75 laptop` | €1,200.75, laptop |
| `€40 taxi to airport` | €40.00, taxi, "to airport" |
| `80 usd hotel` | $80.00, hotel |
| `15 gas station` | €15.00, **gas**, "station" |

That last row is the one that bites people: a naive parser reads `gas` as a
three-letter currency code and files the expense under `station`. Only real
currency codes are matched.

`1,500` is one thousand five hundred; `12,5` is twelve fifty. The rule is that
a separator is a decimal point only when it appears once and is followed by one
or two digits.

Amounts are stored as integer cents, so no float rounding error can appear in a
total.

## Commands

```
<any message with an amount>   record an expense
/report [today|week|month|YYYY-MM]   text summary with a bar breakdown
/csv    [period]               CSV export (UTF-8 BOM, opens cleanly in Excel)
/xlsx   [period]               Excel workbook: line items + summary + pie chart
/undo                          remove your last entry
/help                          usage
```

`week` starts on Monday. `2026-02` correctly ends on the 29th in a leap year.

## Running it

```bash
git clone https://github.com/Tykhorskyi/report-bot.git
cd report-bot
pip install -e ".[xlsx]"

export TELEGRAM_TOKEN="123456:ABC..."   # from @BotFather
python -m reportbot
```

Docker:

```bash
docker build -t report-bot .
docker run -d --restart unless-stopped \
  -e TELEGRAM_TOKEN \
  -v "$PWD/data:/data" \
  report-bot
```

The token is read from the environment and never stored in the repository.

## Design

```
reportbot/
├── parsing.py   # message -> amount, currency, category, note; period ranges
├── store.py     # SQLite: one table, parameterised SQL, cents as integers
├── reports.py   # text summary, CSV, XLSX (chart via openpyxl)
├── bot.py       # command handling (pure) + Telegram client (I/O)
└── __main__.py  # entry point
```

`handle_command()` takes plain arguments and returns a `Reply` object, so the
whole command surface is testable without a token, a network call, or a running
bot. The Telegram client is the only piece that talks to the outside world.

Every query is scoped by `user_id` — in a group chat, one person cannot read or
delete another's records, and there is a test for exactly that.

## Tests

```bash
python -m unittest discover -s tests -t .
```

39 tests: number formats and currencies, malformed input, period boundaries
(including leap years), per-user data isolation, running totals, CSV contents
and the Excel BOM, undo, unknown commands, and group-chat command suffixes
(`/report@MyBot`).

## Requirements

Python 3.10+, `requests`. `openpyxl` only if you want XLSX export.

## License

MIT
