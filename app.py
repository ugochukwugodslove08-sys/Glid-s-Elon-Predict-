import json, math, re, sqlite3, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from supabase import create_client
APP_DIR = Path(__file__).parent
DB_PATH = Path("/tmp/elon_predict.db")
WAT = ZoneInfo("Africa/Lagos")
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
st.set_page_config(page_title="Elon Predict AI", page_icon="📈", layout="wide")

def save_count(market_type, market_start, day_no, count):
    supabase.table("daily_counts").upsert({
        "market_type": market_type,
        "market_start": str(market_start),
        "day_no": int(day_no),
        "count": int(count),
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }, on_conflict="market_type,market_start,day_no").execute()

def history_frame():
    response = supabase.table("daily_counts").select("*").order("market_start").order("day_no").execute()
    return pd.DataFrame(response.data or [])

def fetch_events():
    # Public Gamma endpoint; no trading credentials required.
    r = requests.get(f"{GAMMA}/events", params={"active":"true","closed":"false","limit":500}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    matches = []
    for ev in data:
        title = str(ev.get("title") or ev.get("name") or "")
        markets = ev.get("markets") or []
        text = title + " " + " ".join(str(m.get("question","")) for m in markets)
        if "elon" in text.lower() and ("tweet" in text.lower() or "post" in text.lower()):
            matches.append(ev)
    return matches

def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else []
        except Exception:
            return []
    return []

def parse_range(text):
    s = str(text).replace(",", "")
    patterns = [
        r'(\d{2,4})\s*(?:-|–|—|to)\s*(\d{2,4})',
        r'(\d{2,4})\s*\+\s*(?:tweets|posts)?'
    ]
    m = re.search(patterns[0], s, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(patterns[1], s, re.I)
    if m:
        return int(m.group(1)), 9999
    return None

def get_yes_price_and_book(market):
    outcomes = as_list(market.get("outcomes"))
    token_ids = as_list(market.get("clobTokenIds"))
    prices = as_list(market.get("outcomePrices"))
    yes_idx = next((i for i, x in enumerate(outcomes) if str(x).lower() == "yes"), 0)
    token = str(token_ids[yes_idx]) if yes_idx < len(token_ids) else ""
    gamma_price = None
    if yes_idx < len(prices):
        try: gamma_price = float(prices[yes_idx])
        except Exception: pass
    best_ask = None
    if token:
        try:
            r = requests.get(f"{CLOB}/book", params={"token_id": token}, timeout=10)
            if r.ok:
                book = r.json()
                asks = book.get("asks") or []
                if asks:
                    best_ask = min(float(a["price"]) for a in asks if a.get("price") is not None)
        except Exception:
            pass
    return token, gamma_price, best_ask

def normal_cdf(x, mu, sigma):
    return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

def range_probability(lo, hi, mu, sigma):
    upper = 1.0 if hi >= 9999 else normal_cdf(hi + 0.5, mu, sigma)
    lower = 0.0 if lo <= 0 else normal_cdf(lo - 0.5, mu, sigma)
    return max(0.0, min(1.0, upper - lower))

st.title("📈 Elon Predict AI")
st.caption("Tweet-count intelligence for Polymarket · MVP · WAT (Africa/Lagos)")

with st.sidebar:
    st.header("Market setup")
    market_type = st.selectbox("Market window", ["Tuesday-to-Tuesday", "Friday-to-Friday"])
    market_start = st.date_input("Market start date")
    cutoff_hour = st.selectbox("Daily cutoff (WAT)", [17, 18], index=1)
    st.caption(f"Daily count boundary: {cutoff_hour}:00 WAT")
    st.divider()
    st.header("Signal settings")
    min_edge = st.slider("Minimum model edge", 0.01, 0.30, 0.08, 0.01)
    min_liquidity = st.number_input("Minimum market liquidity ($)", min_value=0, value=100, step=50)
    st.caption("Signals are informational, not financial advice.")

tab1, tab2, tab3, tab4 = st.tabs(["Live dashboard", "Tweet counts", "Market scanner", "History & import"])

with tab1:
    st.subheader("Current market overview")
    df = history_frame()
    start_key = market_start.isoformat()
    cur = df[(df.market_type == market_type) & (df.market_start == start_key)] if not df.empty else pd.DataFrame()
    counts = {int(r.day_no): int(r.count) for r in cur.itertuples()} if not cur.empty else {}
    total = sum(counts.values())
    c1, c2, c3 = st.columns(3)
    c1.metric("Tweets recorded", total)
    c2.metric("Days recorded", len(counts), "of 7")
    c3.metric("Market window", market_type)
    if counts:
        chart = pd.DataFrame({"Day":[f"D{i}" for i in range(1,8)],"Tweets":[counts.get(i,0) for i in range(1,8)]})
        st.bar_chart(chart.set_index("Day"))
    else:
        st.info("No counts recorded for this market yet. Open Tweet counts to enter today's observations.")
    if len(counts) >= 1:
        st.markdown("#### Pace snapshot")
        elapsed_days = len(counts)
        avg = total / elapsed_days
        projected = avg * 7
        st.metric("Simple weekly projection", f"{projected:.0f}", help="Average of recorded full-day bins multiplied by seven. Not yet adjusted for partial days or weekday effects.")
        st.caption("The first MVP deliberately labels this as a simple baseline. We will add the calibrated weekday/weekend model after importing your historical weekly records.")

with tab2:
    st.subheader("Record daily tweet counts")
    st.write("Enter the number of eligible posts in each completed market-day bin. Use the same counting convention as the market's resolution rules.")
        entered = {}
    for i in range(1, 8):
        entered[i] = st.number_input(
            f"Day {i}",
            min_value=0,
            max_value=2000,
            value=counts.get(i, 0),
            step=1,
            key=f"count_{i}_{market_type}_{start_key}"
        )
        if st.button("Save daily counts", type="primary"):
            for day, count in entered.items():
                if count > 0 or day in counts:
                    save_count(market_type, start_key, day, count)
            st.success("Counts saved to the local database.")
            st.rerun()
    st.caption("Zero is treated as a valid count if you save an existing day. Blank future days should remain zero until observed.")

with tab3:
    st.subheader("Polymarket market scanner")
    st.write("Scans currently active Polymarket events for Elon Musk tweet/post-count markets. Public market data only.")
    if st.button("Refresh Polymarket markets", type="primary"):
        with st.spinner("Searching active Polymarket events..."):
            try:
                st.session_state["events"] = fetch_events()
                st.session_state["scan_error"] = None
            except Exception as e:
                st.session_state["scan_error"] = str(e)
    if st.session_state.get("scan_error"):
        st.error(f"Market scan failed: {st.session_state['scan_error']}")
    events = st.session_state.get("events", [])
    if events:
        rows = []
        for ev in events:
            for m in ev.get("markets") or []:
                q = str(m.get("question") or "")
                parsed = parse_range(q)
                token, gp, ask = get_yes_price_and_book(m)
                price = ask if ask is not None else gp
                rows.append({
                    "Event": ev.get("title") or ev.get("name") or "",
                    "Market": q,
                    "Range": f"{parsed[0]}–{parsed[1]}" if parsed else "Unparsed",
                    "Best YES ask": price,
                    "Gamma YES price": gp,
                    "Liquidity ($)": m.get("liquidityNum") or m.get("liquidity") or 0,
                    "Token ID": token
                })
        mdf = pd.DataFrame(rows)
        st.dataframe(mdf.drop(columns=["Token ID"]), use_container_width=True, hide_index=True)
        st.caption("Best YES ask is fetched from the public order book when available. Gamma outcome price is shown as a fallback reference, not a guaranteed executable price.")
        st.download_button("Download market scan CSV", mdf.to_csv(index=False), "polymarket_scan.csv", "text/csv")
    else:
        st.info("Press Refresh Polymarket markets to scan. If no markets appear, the active event listing may not include the market; later versions will support direct event URL/slug lookup.")

    st.divider()
    st.subheader("Bracket probability comparison")
    st.write("Enter a projected final count and uncertainty to estimate probability for a bracket. This is a baseline normal-distribution model, not yet calibrated.")
    a, b, c = st.columns(3)
    mu = a.number_input("Projected final count", min_value=0, value=300, step=5)
    sigma = b.number_input("Uncertainty (standard deviation)", min_value=5, value=35, step=5)
    bracket = c.text_input("Bracket range", value="280-299")
    rr = parse_range(bracket)
    if rr:
        p = range_probability(rr[0], rr[1], float(mu), float(sigma))
        st.metric("Estimated bracket probability", f"{p:.1%}")
        st.caption("Compare this estimate with the best executable YES ask, not merely the last traded price. A positive difference alone is not a buy signal; liquidity, fees and model reliability matter.")
    else:
        st.warning("Enter a bracket like 280-299 or 400+.")

with tab4:
    st.subheader("Historical records")
    hist = history_frame()
    if not hist.empty:
        st.dataframe(hist, use_container_width=True, hide_index=True)
        st.download_button("Download history CSV", hist.to_csv(index=False), "elon_predict_history.csv", "text/csv")
    else:
        st.info("No saved history yet.")
    st.divider()
    st.subheader("Import historical daily counts")
    st.write("CSV columns required: market_type, market_start, day_no, count. market_type must be Tuesday-to-Tuesday or Friday-to-Friday.")
    template = pd.DataFrame([
        {"market_type":"Friday-to-Friday","market_start":"2026-11-20","day_no":1,"count":65},
        {"market_type":"Friday-to-Friday","market_start":"2026-11-20","day_no":2,"count":55}
    ])
    st.download_button("Download CSV template", template.to_csv(index=False), "historical_counts_template.csv", "text/csv")
    upload = st.file_uploader("Upload historical counts CSV", type=["csv"])
    if upload is not None:
        try:
            incoming = pd.read_csv(upload)
            required = {"market_type","market_start","day_no","count"}
            if not required.issubset(incoming.columns):
                st.error(f"Missing columns: {', '.join(sorted(required - set(incoming.columns)))}")
            else:
                st.dataframe(incoming.head(20), use_container_width=True)
                if st.button("Import records"):
                    for row in incoming.to_dict("records"):
                        if row["market_type"] not in ["Tuesday-to-Tuesday","Friday-to-Friday"]:
                            continue
                        save_count(row["market_type"], str(row["market_start"]), int(row["day_no"]), int(row["count"]))
                    st.success(f"Imported {len(incoming)} rows.")
                    st.rerun()
        except Exception as e:
            st.error(f"Could not read CSV: {e}")

st.divider()
st.caption("Elon Predict AI MVP · Data is stored locally in SQLite. Keep this app running for live dashboard access. Telegram and scheduled background collection are the next build milestone.")
