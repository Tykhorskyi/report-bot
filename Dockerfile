FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY reportbot ./reportbot
RUN pip install --no-cache-dir ".[xlsx]"

RUN useradd --create-home --uid 1000 bot && mkdir -p /data && chown bot /data
USER bot

ENV DATABASE_PATH=/data/expenses.db
VOLUME ["/data"]

CMD ["python", "-m", "reportbot"]
