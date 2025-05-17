# VWRL Strategy Dashboard (Streamlit + Alerts)

"""
This script builds a Streamlit dashboard to track a long-entry strategy for the VWRL ETF based on:
- RSI (14) < 30
- Price below Lower Bollinger Band (20, 2 std)
- Drawdown > 20% from all-time high

It also sends email alerts when all three conditions are met.
"""

import yfinance as yf
import pandas as pd
import streamlit as st
import smtplib
from email.message import EmailMessage
import matplotlib.pyplot as plt
import os
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands

# ---- CONFIG ----
TICKER = "VWRL.AS"

# Support both Streamlit secrets and environment variables
ALERT_EMAIL = st.secrets["ALERT_EMAIL"] if "ALERT_EMAIL" in st.secrets else os.getenv("ALERT_EMAIL")
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"] if "EMAIL_PASSWORD" in st.secrets else os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL = st.secrets["RECIPIENT_EMAIL"] if "RECIPIENT_EMAIL" in st.secrets else os.getenv("RECIPIENT_EMAIL")

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ---- DATA FETCHING ----
@st.cache_data
def get_data():
    df = yf.download(TICKER, period="1y", interval="1d")

    if df.empty:
        raise ValueError("Downloaded data is empty. Please check ticker symbol or data source.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ['_'.join(col).strip() if isinstance(col, tuple) else col for col in df.columns]

    column_map = {
        f'Close_{TICKER}': 'Close',
        f'Open_{TICKER}': 'Open',
        f'High_{TICKER}': 'High',
        f'Low_{TICKER}': 'Low',
        f'Volume_{TICKER}': 'Volume'
    }
    df.rename(columns=column_map, inplace=True)

    if 'Close' not in df.columns:
        raise ValueError("'Close' column is missing after flattening. Columns: " + str(df.columns))

    if df['Close'].isnull().values.all():
        raise ValueError("All Close values are NaN. Check if the data was downloaded correctly.")

    df.dropna(inplace=True)

    close_data = df[['Close']].copy()
    close_series = close_data.squeeze() if isinstance(close_data, pd.DataFrame) else close_data

    if close_series.ndim != 1:
        raise ValueError(f"Expected 1D Series, got shape {close_series.shape}")

    df['Close'] = close_series

    try:
        df['RSI'] = RSIIndicator(close=close_series, window=14).rsi()
        bb = BollingerBands(close=close_series, window=20, window_dev=2)
        df['BBL'] = bb.bollinger_lband()
        df['BBM'] = bb.bollinger_mavg()
        df['BBU'] = bb.bollinger_hband()

        df['ATH'] = close_series.cummax()
        df['Drawdown'] = (close_series - df['ATH']) / df['ATH'] * 100

    except Exception as e:
        raise ValueError(f"Indicator calculation failed: {e}")

    indicators = ['RSI', 'BBL', 'Drawdown']
    missing = [col for col in indicators if col not in df.columns]
    if missing:
        raise KeyError(f"Missing expected indicator columns: {missing}")

    df = df.dropna(subset=[col for col in indicators if col in df.columns])

    try:
        conditions = [
            df['RSI'] < 30,
            df['Close'] < df['BBL'],
            df['Drawdown'] < -20
        ]
        signal = pd.concat(conditions, axis=1).all(axis=1)
        df['Buy Signal'] = signal.fillna(False).astype(bool)
    except Exception as e:
        raise

    return df

# ---- ALERTING ----
def send_email(signal_date, price, test_mode=False):
    msg = EmailMessage()
    msg.set_content(f"Buy signal for {TICKER} on {signal_date} at price {price:.2f}")
    msg['Subject'] = f"Buy Signal Alert: {TICKER}"
    msg['From'] = ALERT_EMAIL
    msg['To'] = RECIPIENT_EMAIL

    if test_mode:
        st.info(f"[TEST MODE] Would send email: {msg['Subject']} - {msg.get_content()}")
        return

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(ALERT_EMAIL, EMAIL_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        st.error(f"Failed to send email: {e}")

# ---- STREAMLIT UI ----
st.set_page_config(page_title="VWRL Strategy Dashboard", layout="wide")
st.title("📈 VWRL Buy Signal Strategy")
st.markdown("RSI < 30, Price < Lower Bollinger Band, and >20% Drawdown from All-Time High")

test_mode = False
force_email = False
if DEBUG_MODE:
    test_mode = st.sidebar.checkbox("🔍 Test Alert Mode", value=False)
    force_email = st.sidebar.button("📧 Force Send Test Email")

try:
    df = get_data()
    latest = df.iloc[-1]

    try:
        if test_mode:
            send_email(df.index[-1].date(), latest['Close'], test_mode=True)
        else:
            signal_value = latest['Buy Signal']
            if isinstance(signal_value, (pd.Series, pd.DataFrame)):
                signal_value = signal_value.values[0]
            if bool(signal_value):
                send_email(df.index[-1].date(), latest['Close'], test_mode=False)
                st.success(f"✅ Buy Signal Triggered on {df.index[-1].date()}!")

        if force_email:
            send_email(df.index[-1].date(), latest['Close'], test_mode=False)
            st.success("✅ Test email sent.")

    except Exception as signal_error:
        raise

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df.index, df['Close'], label='Close')
    ax.plot(df.index, df['BBL'], label='Lower BB', linestyle='--')
    ax.plot(df.index, df['BBM'], label='Middle BB', linestyle='--')
    ax.plot(df.index, df['BBU'], label='Upper BB', linestyle='--')
    ax.scatter(df[df['Buy Signal']].index, df[df['Buy Signal']]['Close'], label='Buy Signal', color='green', marker='^', s=100)
    ax.set_title(f"{TICKER} Price Chart with Indicators")
    ax.legend()
    st.pyplot(fig)

    st.subheader("Buy Signal Data")
    st.dataframe(df[df['Buy Signal']][['Close', 'RSI', 'BBL', 'Drawdown']])

except Exception as e:
    import traceback
    st.error(f"🚨 Error: {e}")
    st.text(traceback.format_exc())
