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

# ---- DATA FETCHING ----
@st.cache_data
def get_data():
    df = yf.download(TICKER, period="1y", interval="1d")
    st.write("DEBUG: Raw downloaded data:", df.head())

    if df.empty:
        raise ValueError("Downloaded data is empty. Please check ticker symbol or data source.")

    if df['Close'].isnull().values.all():
        raise ValueError("All Close values are NaN. Check if the data was downloaded correctly.")

    df.dropna(inplace=True)

    # Indicators
    try:
        df['Close'] = df['Close'].astype(float)  # Ensure 1D
        df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi()
        bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
        df['BBL'] = bb.bollinger_lband()
        df['BBM'] = bb.bollinger_mavg()
        df['BBU'] = bb.bollinger_hband()
    except Exception as e:
        st.write("DEBUG: RSI or BB inputs:", df['Close'].shape, type(df['Close']))
        raise ValueError(f"Indicator calculation failed: {e}")

    # Drawdown
    df['ATH'] = df['Close'].cummax()
    df['Drawdown'] = (df['Close'] - df['ATH']) / df['ATH'] * 100

    # Signal
    try:
        signal = (df['RSI'] < 30) & (df['Close'] < df['BBL']) & (df['Drawdown'] < -20)
        df['Buy Signal'] = signal.fillna(False).astype(bool)
    except Exception as e:
        st.write("DEBUG: Signal Generation Error", e)
        raise
    return df

# ---- ALERTING ----
def send_email(signal_date, price):
    msg = EmailMessage()
    msg.set_content(f"Buy signal for {TICKER} on {signal_date} at price {price:.2f}")
    msg['Subject'] = f"Buy Signal Alert: {TICKER}"
    msg['From'] = ALERT_EMAIL
    msg['To'] = RECIPIENT_EMAIL

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

try:
    df = get_data()
    latest = df.iloc[-1]

    st.write("DEBUG: latest row:", latest.to_dict())
    st.write("DEBUG: Buy Signal raw type:", type(latest['Buy Signal']))

    try:
        signal_value = latest['Buy Signal']
        if isinstance(signal_value, (pd.Series, pd.DataFrame)):
            signal_value = signal_value.values[0]
        if bool(signal_value):
            send_email(df.index[-1].date(), latest['Close'])
            st.success(f"✅ Buy Signal Triggered on {df.index[-1].date()}!")
    except Exception as signal_error:
        st.write("DEBUG: Signal comparison error", signal_error)
        raise

    # Plot chart
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(df.index, df['Close'], label='Close')
    ax.plot(df.index, df['BBL'], label='Lower BB', linestyle='--')
    ax.plot(df.index, df['BBM'], label='Middle BB', linestyle='--')
    ax.plot(df.index, df['BBU'], label='Upper BB', linestyle='--')
    ax.scatter(df[df['Buy Signal']].index, df[df['Buy Signal']]['Close'], label='Buy Signal', color='green', marker='^', s=100)
    ax.set_title(f"{TICKER} Price Chart with Indicators")
    ax.legend()
    st.pyplot(fig)

    # Show DataFrame
    st.subheader("Buy Signal Data")
    st.dataframe(df[df['Buy Signal']][['Close', 'RSI', 'BBL', 'Drawdown']])

except Exception as e:
    import traceback
    st.error(f"🚨 Error: {e}")
    st.text(traceback.format_exc())
