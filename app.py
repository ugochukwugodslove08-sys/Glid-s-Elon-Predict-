
import json
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from supabase import create_client

# ==================================================
# APP SETTINGS
# ==================================================

APP_NAME = "Glid's Elon Predict"

WAT = ZoneInfo("Africa/Lagos")
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

st.set_page_config(
    page_title=APP_NAME,
    page_icon="📈",
    layout="wide"
)

st.title("📈 Glid's Elon Predict")
st.caption(
    "Tweet-count intelligence for Polymarket · WAT (Africa/Lagos)"
)

# ==================================================
# SUPABASE CONNECTION
# ==================================================

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )

except Exception:
    st.error(
        "Supabase connection settings are missing or incorrect. "
        "Check SUPABASE_URL and SUPABASE_KEY in Streamlit Secrets."
    )
    st.stop()


# ==================================================
# DATABASE FUNCTIONS
# ==================================================

def save_count(market_type, market_start, day_no, count):
    record = {
        "market_type": market_type,
        "market_start": str(market_start),
        "day_no": int(day_no),
        "count": int(count),
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }

    supabase.table("daily_counts").upsert(
        record,
        on_conflict="market_type,market_start,day_no"
    ).execute()


def history_frame():
    response = (
        supabase.table("daily_counts")
        .select("*")
        .order("market_start")
        .order("day_no")
        .execute()
    )

    return pd.DataFrame(response.data or [])


# ==================================================
# POLYMARKET FUNCTIONS
# ==================================================

def fetch_events():
    response = requests.get(
        f"{GAMMA}/events",
        params={
            "active": "true",
            "closed": "false",
            "limit": 500
        },
        timeout=20
    )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list):
        return []

    matches = []

    for event in data:
        title = str(
            event.get("title") or event.get("name") or ""
        )

        markets = event.get("markets") or []

        market_text = " ".join(
            str(market.get("question", ""))
            for market in markets
        )

        combined_text = title + " " + market_text

        if (
            "elon" in combined_text.lower()
            and (
                "tweet" in combined_text.lower()
                or "post" in combined_text.lower()
            )
        ):
            matches.append(event)

    return matches


def as_list(value):
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    return []


def parse_range(text):
    value = str(text).replace(",", "")

    patterns = [
        r"(\d{2,4})\s*(?:-|–|—|to)\s*(\d{2,4})",
        r"(\d{2,4})\s*\+\s*(?:tweets|posts)?"
    ]

    match = re.search(patterns[0], value, re.I)

    if match:
        return (
            int(match.group(1)),
            int(match.group(2))
        )

    match = re.search(patterns[1], value, re.I)

    if match:
        return (
            int(match.group(1)),
            9999
        )

    return None


def get_yes_price_and_book(market):
    outcomes = as_list(market.get("outcomes"))
    token_ids = as_list(market.get("clobTokenIds"))
    prices = as_list(market.get("outcomePrices"))

    yes_index = next(
        (
            index
            for index, outcome in enumerate(outcomes)
            if str(outcome).lower() == "yes"
        ),
        0
    )

    token = (
        str(token_ids[yes_index])
        if yes_index < len(token_ids)
        else ""
    )

    gamma_price = None

    if yes_index < len(prices):
        try:
            gamma_price = float(prices[yes_index])
        except Exception:
            pass

    best_ask = None

    if token:
        try:
            response = requests.get(
                f"{CLOB}/book",
                params={"token_id": token},
                timeout=10
            )

            if response.ok:
                book = response.json()
                asks = book.get("asks") or []

                valid_asks = [
                    float(ask["price"])
                    for ask in asks
                    if ask.get("price") is not None
                ]

                if valid_asks:
                    best_ask = min(valid_asks)

        except Exception:
            pass

    return token, gamma_price, best_ask


# ==================================================
# PROBABILITY FUNCTIONS
# ==================================================

def normal_cdf(x, mu, sigma):
    return 0.5 * (
        1 + math.erf(
            (x - mu) / (sigma * math.sqrt(2))
        )
    )


def range_probability(lo, hi, mu, sigma):
    upper = (
        1.0
        if hi >= 9999
        else normal_cdf(hi + 0.5, mu, sigma)
    )

    lower = (
        0.0
        if lo <= 0
        else normal_cdf(lo - 0.5, mu, sigma)
    )

    return max(
        0.0,
        min(1.0, upper - lower)
    )


# ==================================================
# SIDEBAR SETTINGS
# ==================================================

with st.sidebar:
    st.header("Market setup")

    market_type = st.selectbox(
        "Market window",
        [
            "Tuesday-to-Tuesday",
            "Friday-to-Friday"
        ]
    )

    market_start = st.date_input(
        "Market start date"
    )

    cutoff_hour = st.selectbox(
        "Daily cutoff (WAT)",
        [17, 18],
        index=1
    )

    st.caption(
        f"Daily count boundary: {cutoff_hour}:00 WAT"
    )

    st.divider()

    st.header("Signal settings")

    min_edge = st.slider(
        "Minimum model edge",
        0.01,
        0.30,
        0.08,
        0.01
    )

    min_liquidity = st.number_input(
        "Minimum market liquidity ($)",
        min_value=0,
        value=100,
        step=50
    )

    st.caption(
        "Signals are informational, not financial advice."
    )


# ==================================================
# LOAD CURRENT MARKET COUNTS
# ==================================================

try:
    df = history_frame()

except Exception:
    st.error(
        "Could not load records from Supabase. "
        "Check your database tables and permissions."
    )
    st.stop()


start_key = market_start.isoformat()

if not df.empty:
    cur = df[
        (df["market_type"] == market_type)
        & (
            df["market_start"].astype(str)
            == start_key
        )
    ]
else:
    cur = pd.DataFrame()


counts = (
    {
        int(row.day_no): int(row.count)
        for row in cur.itertuples()
    }
    if not cur.empty
    else {}
)

total = sum(counts.values())


# ==================================================
# MAIN TABS
# ==================================================

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Live dashboard",
        "Tweet counts",
        "Market scanner",
        "History & import"
    ]
)


# ==================================================
# TAB 1: LIVE DASHBOARD
# ==================================================

with tab1:
    st.subheader("Current market overview")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Tweets recorded",
        total
    )

    col2.metric(
        "Days recorded",
        len(counts),
        "of 7"
    )

    col3.metric(
        "Market window",
        market_type
    )

    if counts:
        chart = pd.DataFrame({
            "Day": [
                f"Day {i}"
                for i in range(1, 8)
            ],
            "Tweets": [
                counts.get(i, 0)
                for i in range(1, 8)
            ]
        })

        st.bar_chart(
            chart.set_index("Day")
        )

    else:
        st.info(
            "No counts recorded for this market yet. "
            "Open Tweet counts to enter your observations."
        )

    if len(counts) >= 1:
        st.markdown("#### Pace snapshot")

        elapsed_days = len(counts)
        average = total / elapsed_days
        projected = average * 7

        st.metric(
            "Simple weekly projection",
            f"{projected:.0f}"
        )

        st.caption(
            "This is a basic average projection. "
            "It does not yet account for weekday patterns, "
            "weekends or partial days."
        )


# ==================================================
# TAB 2: TWEET COUNTS
# ==================================================

with tab2:
    st.subheader("Record daily tweet counts")

    st.write(
        "Enter the number of eligible posts in each "
        "completed market-day bin."
    )

    entered = {}

    # Days appear in order: Day 1 to Day 7
    for i in range(1, 8):
        entered[i] = st.number_input(
            f"Day {i}",
            min_value=0,
            max_value=2000,
            value=counts.get(i, 0),
            step=1,
            key=f"count_{i}_{market_type}_{start_key}"
        )

    if st.button(
        "Save daily counts",
        type="primary"
    ):
        try:
            for day, count in entered.items():
                if count > 0 or day in counts:
                    save_count(
                        market_type,
                        start_key,
                        day,
                        count
                    )

            st.success(
                "Daily counts saved successfully."
            )

            st.rerun()

        except Exception:
            st.error(
                "Could not save the counts. "
                "Check your Supabase connection and permissions."
            )

    st.caption(
        "A zero is saved for a day that already has a record. "
        "Leave future days at zero until you have observed them."
    )


# ==================================================
# TAB 3: MARKET SCANNER
# ==================================================

with tab3:
    st.subheader("Polymarket market scanner")

    st.write(
        "Scans currently active Polymarket events "
        "for Elon Musk tweet/post-count markets."
    )

    if st.button(
        "Refresh Polymarket markets",
        type="primary"
    ):
        with st.spinner(
            "Searching active Polymarket events..."
        ):
            try:
                st.session_state["events"] = fetch_events()
                st.session_state["scan_error"] = None

            except Exception as error:
                st.session_state["scan_error"] = str(error)

    if st.session_state.get("scan_error"):
        st.error(
            f"Market scan failed: "
            f"{st.session_state['scan_error']}"
        )

    events = st.session_state.get("events", [])

    if events:
        rows = []

        for event in events:
            for market in event.get("markets") or []:
                question = str(
                    market.get("question") or ""
                )

                parsed = parse_range(question)

                token, gamma_price, best_ask = (
                    get_yes_price_and_book(market)
                )

                price = (
                    best_ask
                    if best_ask is not None
                    else gamma_price
                )

                rows.append({
                    "Event": (
                        event.get("title")
                        or event.get("name")
                        or ""
                    ),
                    "Market": question,
                    "Range": (
                        f"{parsed[0]}–{parsed[1]}"
                        if parsed
                        else "Unparsed"
                    ),
                    "Best YES ask": price,
                    "Gamma YES price": gamma_price,
                    "Liquidity ($)": (
                        market.get("liquidityNum")
                        or market.get("liquidity")
                        or 0
                    ),
                    "Token ID": token
                })

        market_df = pd.DataFrame(rows)

        st.dataframe(
            market_df.drop(columns=["Token ID"]),
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Best YES ask comes from the public order book "
            "when available. Gamma price is a reference, "
            "not a guaranteed executable price."
        )

        st.download_button(
            "Download market scan CSV",
            market_df.to_csv(index=False),
            "polymarket_scan.csv",
            "text/csv"
        )

    else:
        st.info(
            "Press Refresh Polymarket markets to scan. "
            "If no markets appear, the active event listing "
            "may not include the market."
        )

    st.divider()

    st.subheader("Bracket probability comparison")

    st.write(
        "Enter a projected final count and uncertainty "
        "to estimate the probability of a bracket."
    )

    col_a, col_b, col_c = st.columns(3)

    mu = col_a.number_input(
        "Projected final count",
        min_value=0,
        value=300,
        step=5
    )

    sigma = col_b.number_input(
        "Uncertainty (standard deviation)",
        min_value=5,
        value=35,
        step=5
    )

    bracket = col_c.text_input(
        "Bracket range",
        value="280-299"
    )

    bracket_range = parse_range(bracket)

    if bracket_range:
        probability = range_probability(
            bracket_range[0],
            bracket_range[1],
            float(mu),
            float(sigma)
        )

        st.metric(
            "Estimated bracket probability",
            f"{probability:.1%}"
        )

        st.caption(
            "Compare this estimate with the best executable "
            "YES ask. This baseline model is not yet calibrated."
        )

    else:
        st.warning(
            "Enter a bracket like 280-299 or 400+."
        )


# ==================================================
# TAB 4: HISTORY AND IMPORT
# ==================================================

with tab4:
    st.subheader("Historical records")

    try:
        history = history_frame()

        if not history.empty:
            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True
            )

            st.download_button(
                "Download history CSV",
                history.to_csv(index=False),
                "elon_predict_history.csv",
                "text/csv"
            )

        else:
            st.info(
                "No saved history yet."
            )

    except Exception:
        st.error(
            "Could not retrieve historical records."
        )

    st.divider()

    st.subheader("Import historical daily counts")

    st.write(
        "CSV columns required: market_type, market_start, "
        "day_no, count. Market type must be "
        "Tuesday-to-Tuesday or Friday-to-Friday."
    )

    template = pd.DataFrame([
        {
            "market_type": "Friday-to-Friday",
            "market_start": "2026-11-20",
            "day_no": 1,
            "count": 65
        },
        {
            "market_type": "Friday-to-Friday",
            "market_start": "2026-11-20",
            "day_no": 2,
            "count": 55
        }
    ])

    st.download_button(
        "Download CSV template",
        template.to_csv(index=False),
        "historical_counts_template.csv",
        "text/csv"
    )

    upload = st.file_uploader(
        "Upload historical counts CSV",
        type=["csv"]
    )

    if upload is not None:
        try:
            incoming = pd.read_csv(upload)

            required = {
                "market_type",
                "market_start",
                "day_no",
                "count"
            }

            if not required.issubset(incoming.columns):
                missing = required - set(incoming.columns)

                st.error(
                    "Missing columns: "
                    + ", ".join(sorted(missing))
                )

            else:
                st.dataframe(
                    incoming.head(20),
                    use_container_width=True
                )

                if st.button("Import records"):
                    imported = 0

                    for row in incoming.to_dict("records"):
                        if row["market_type"] not in [
                            "Tuesday-to-Tuesday",
                            "Friday-to-Friday"
                        ]:
                            continue

                        save_count(
                            row["market_type"],
                            str(row["market_start"]),
                            int(row["day_no"]),
                            int(row["count"])
                        )

                        imported += 1

                    st.success(
                        f"Imported {imported} records."
                    )

                    st.rerun()

        except Exception:
            st.error(
                "Could not read or import the CSV file. "
                "Check its columns and values."
            )


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "Glid's Elon Predict · Tweet-count intelligence · "
    "Data stored in Supabase · WAT (Africa/Lagos)"
    )
