# Elon Predict AI — MVP

A free-first dashboard for tracking Elon Musk tweet-count markets on Polymarket.

## What works in this first version

- Streamlit website dashboard.
- Daily count entry for Tuesday-to-Tuesday and Friday-to-Friday windows.
- Local SQLite storage.
- CSV import/export for historical counts.
- Public Polymarket active-event scan using Gamma API.
- Public CLOB order-book lookup for YES best ask where token IDs are available.
- A basic probability calculator for a user-entered bracket.

## Important limitations

1. X's official API is not included as a free data source. The first version uses manual daily count entry and CSV import. We can add official X API access when you decide to fund it.
2. Market discovery currently scans the active event list and filters for Elon + tweet/post wording. A market may be missed because of API pagination or naming differences. The next iteration will add direct event URL/slug support and more complete discovery.
3. The probability calculator is a transparent normal-distribution baseline. It is not trained or calibrated on your historical records yet. Do not treat it as a trading signal.
4. Telegram notifications and always-on scheduled jobs are not in this first local MVP.

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Open the local URL Streamlit prints, usually http://localhost:8501.

## First setup

1. Open the **Tweet counts** tab.
2. Choose market type and start date in the sidebar.
3. Enter daily counts using the agreed market-day cutoff.
4. Save.
5. Open **Market scanner** and refresh.
6. Import historical daily counts using the CSV template.

## Data and privacy

The SQLite database is stored in `data/elon_predict.db`. It is local to the machine where the app runs. Do not upload API secrets into the app or commit them to GitHub.

## Next milestone

- Telegram bot alerts.
- Official X API integration (optional, paid usage).
- Automated daily collection and market snapshots.
- Historical pattern model using separate weekday/weekend and D1–D7 behaviour.
- Backtesting and probability calibration.
