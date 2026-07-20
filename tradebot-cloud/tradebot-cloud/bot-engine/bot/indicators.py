"""
Technical Indicators Module
Calculates Exponential Moving Averages (EMA) for the strategy.
"""
import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA) for a given period.

    Args:
        series: Pandas Series of closing prices.
        period: EMA period (number of candles).

    Returns:
        Pandas Series containing EMA values.
    """
    if len(series) < period:
        return pd.Series([np.nan] * len(series), index=series.index)
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average (SMA)."""
    return series.rolling(window=period, min_periods=period).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) - bonus indicator."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR) - bonus indicator for volatility."""
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


class IndicatorSet:
    """Container holding all indicators required by the strategy."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all indicators on a DataFrame containing 'close' (and optionally 'high','low').

        Args:
            df: DataFrame with columns ['open','high','low','close','volume'] indexed by datetime.

        Returns:
            DataFrame with extra EMA columns appended.
        """
        df = df.copy()
        df["ema_8"] = calculate_ema(df["close"], self.ema_short)
        df["ema_13"] = calculate_ema(df["close"], self.ema_mid1)
        df["ema_21"] = calculate_ema(df["close"], self.ema_mid2)
        df["ema_55"] = calculate_ema(df["close"], self.ema_long)
        if {"high", "low"}.issubset(df.columns):
            df["atr"] = calculate_atr(df["high"], df["low"], df["close"])
        return df
