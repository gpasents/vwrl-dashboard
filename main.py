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
ALERT_EMAIL = os.getenv("ALERT_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# ---- DATA FETCHING ----
@st.cache_data
def get_data():
    df = yf.download(TICKER, period="1y", interval="1d")
    if df.empty or df['Close'].isnull().all():
        raise ValueError("Downloaded data is empty or invalid. Please check ticker symbol or data source.")

    df.dropna(inplace=True)

    # Indicators
    try:
        df['RSI'] = RSIIndicator(close=df['Close'], window=14).rsi().squeeze()
        bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
        df['BBL'] = bb.bollinger_lband().squeeze()
        df['BBM'] = bb.bollinger_mavg().squeeze()
        df['BBU'] = bb.bollinger_hband().squeeze()
    except Exception as e:
        raise ValueError(f"Indicator calculation failed: {e}")

    # Drawdown
    df['ATH'] = df['Close'].cummax()
    df['Drawdown'] = (df['Close'] - df['ATH']) / df['ATH'] * 100

    # Signal
    df['Buy Signal'] = ((df['RSI'] < 30) & (df['Close'] < df['BBL']) & (df['Drawdown'] < -20)).fillna(False).astype(bool)
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

    # Check and send alert if signal triggered today
    if bool(latest['Buy Signal']):
        send_email(df.index[-1].date(), latest['Close'])
        st.success(f"✅ Buy Signal Triggered on {df.index[-1].date()}!")

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
    st.error(f"🚨 Error: {e}")