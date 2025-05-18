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
import matplotlib.dates as mdates
import os
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
import plotly.graph_objects as go
import plotly.express as px

# ---- CONFIG ----
TICKER = "VWRL.AS"

# Support both Streamlit secrets and environment variables
ALERT_EMAIL = st.secrets["ALERT_EMAIL"] if "ALERT_EMAIL" in st.secrets else os.getenv("ALERT_EMAIL")
EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"] if "EMAIL_PASSWORD" in st.secrets else os.getenv("EMAIL_PASSWORD")
RECIPIENT_EMAILS = (
    st.secrets["RECIPIENT_EMAILS"].split(",") if "RECIPIENT_EMAILS" in st.secrets 
    else os.getenv("RECIPIENT_EMAILS", "").split(",")
)
RECIPIENT_EMAILS = [email.strip() for email in RECIPIENT_EMAILS if email.strip()]

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ---- DATA FETCHING ----
@st.cache_data
def get_data():
    df = yf.download(TICKER, period="max", interval="1d")

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
    subject_prefix = "[TEST] " if test_mode else ""
    msg.set_content(f"Buy signal for {TICKER} on {signal_date} at price {price:.2f}")
    msg['Subject'] = f"{subject_prefix}Buy Signal Alert: {TICKER}"
    msg['From'] = ALERT_EMAIL
    msg['To'] = ', '.join(RECIPIENT_EMAILS)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(ALERT_EMAIL, EMAIL_PASSWORD)
            smtp.send_message(msg)
        st.success(f"✅ Email{' (test)' if test_mode else ''} sent to: {', '.join(RECIPIENT_EMAILS)}")
    except Exception as e:
        st.error(f"Failed to send email: {e}")

# ---- STREAMLIT UI ----
st.set_page_config(page_title="VWRL Strategy Dashboard", layout="wide")
st.title("📈 VWRL Buy Signal Strategy")
st.markdown("RSI < 30, Price < Lower Bollinger Band, and >20% Drawdown from All-Time High")

try:
    df = get_data()
    latest = df.iloc[-1]

    try:
        signal_value = latest['Buy Signal']
        if isinstance(signal_value, (pd.Series, pd.DataFrame)):
            signal_value = signal_value.values[0]
        if bool(signal_value):
            send_email(df.index[-1].date(), latest['Close'], test_mode=False)
            st.success(f"✅ Buy Signal Triggered on {df.index[-1].date()}!")

    except Exception as signal_error:
        raise

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='Close'))
    fig.add_trace(go.Scatter(x=df.index, y=df['BBL'], mode='lines', name='Lower BB', line=dict(dash='dot')))
    fig.add_trace(go.Scatter(x=df.index, y=df['BBM'], mode='lines', name='Middle BB', line=dict(dash='dot')))
    fig.add_trace(go.Scatter(x=df.index, y=df['BBU'], mode='lines', name='Upper BB', line=dict(dash='dot')))
    fig.add_trace(go.Scatter(x=df[df['Buy Signal']].index, y=df[df['Buy Signal']]['Close'], mode='markers', name='Buy Signal', marker=dict(color='green', size=10, symbol='triangle-up')))

    # Add date range selector and range slider to the x-axis
    fig.update_layout(
        title=f"{TICKER} Price Chart with Indicators (Interactive)",
        xaxis_title="Date",
        yaxis_title="Price",
        hovermode="x unified",
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(step="all")
                ])
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )

    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Buy Signal Data")
    st.dataframe(df[df['Buy Signal']][['Close', 'RSI', 'BBL', 'Drawdown']])

except Exception as e:
    import traceback
    st.error(f"🚨 Error: {e}")
    st.text(traceback.format_exc())
