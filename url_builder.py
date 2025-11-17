# url_builder.py

from typing import Optional
import os
from config import KLINES_LIMIT_BASE_TF # <--- ИМПОРТ ИЗМЕНЕН

# --- Базовые URL ---
BINANCE_BASE_URL = os.environ.get(
    "BINANCE_BASE_URL", "https://fapi.binance.com"
)
BYBIT_BASE_URL = os.environ.get(
    "BYBIT_BASE_URL", "https://api.bybit.com"
)

# --- Binance URL Builders ---

def get_binance_server_time_url() -> str:
    """
    Формирует URL для получения времени сервера Binance Futures.
    """
    return f"{BINANCE_BASE_URL}/fapi/v1/time"


def get_binance_exchange_info_url() -> str:
    """
    Формирует URL для получения Exchange Information Binance Futures.
    """
    return f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo"


def get_binance_klines_url(
    symbol_api: str, interval: str, limit: int = KLINES_LIMIT_BASE_TF
) -> str:
    """
    Формирует URL для получения Klines (свечей) с Binance Futures.
    
    ВАЖНО: limit=400 заменен на KLINES_LIMIT_BASE_TF.
    """
    return f"{BINANCE_BASE_URL}/fapi/v1/klines?symbol={symbol_api}&interval={interval}&limit={limit}"


def get_binance_open_interest_url(symbol_api: str, period: str, limit: int = KLINES_LIMIT_BASE_TF) -> str:
    """
    ВОССТАНОВЛЕНО: Формирует URL для получения Open Interest (OI) с Binance Futures.
    """
    # Убедимся, что лимит не превышает 500 (макс. для Binance OI/FR)
    limit = min(limit, 500)
    return f"{BINANCE_BASE_URL}/futures/data/openInterestHist?symbol={symbol_api}&period={period}&limit={limit}"


def get_binance_funding_rate_url(symbol_api: str, limit: int = 1) -> str:
    """
    Формирует URL для получения последних данных по Funding Rate с Binance Futures.
    """
    # Убедимся, что лимит не превышает 500
    limit = min(limit, 500)
    return f"{BINANCE_BASE_URL}/fapi/v1/fundingRate?symbol={symbol_api}&limit={limit}"


# --- Bybit URLs ---

def get_bybit_server_time_url() -> str:
    """
    Формирует URL для получения времени сервера Bybit V5.
    """
    return f"{BYBIT_BASE_URL}/v3/public/time"


def get_bybit_exchange_info_url() -> str:
    """
    Формирует URL для получения Exchange Information Bybit V5.
    """
    return f"{BYBIT_BASE_URL}/v5/market/tickers?category=linear"


def get_bybit_klines_url(
    symbol_api: str, interval: str, limit: int = KLINES_LIMIT_BASE_TF
) -> str:
    """
    Формирует базовый URL для получения Klines (свечей) с Bybit V5.
    
    ВАЖНО: limit=400 заменен на KLINES_LIMIT_BASE_TF.
    """
    # Bybit V5 Klines: limit (макс 200) устанавливается в fetch_strategies,
    # так как мы используем пагинацию.
    # Мы запрашиваем 800 свечей 4h (для 8h),
    # fetch_bybit_paginated сделает 4 запроса по 200.
    return f"{BYBIT_BASE_URL}/v5/market/klines?category=linear&symbol={symbol_api}&interval={interval}"


def get_bybit_open_interest_url(symbol_api: str, period: str, limit: int = 400) -> str:
    """
    Формирует URL для получения Open Interest (OI) с Bybit V5 (Linear).
    """
    # Bybit V5 OI: limit (макс 200).
    limit = min(limit, 200)
    return f"{BYBIT_BASE_URL}/v5/market/open-interest?category=linear&symbol={symbol_api}&intervalTime={period}&limit={limit}"


def get_bybit_funding_rate_url(symbol_api: str, limit: int = 400) -> str:
    """
    Формирует URL для получения Funding Rate (FR) с Bybit V5 (Linear).
    """
    # Bybit V5 FR: limit (макс 100).
    limit = min(limit, 100)
    return f"{BYBIT_BASE_URL}/v5/market/funding/history?category=linear&symbol={symbol_api}&limit={limit}"