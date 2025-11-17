# tests_e2e/test_4_cache_consistency.py
import logging
import asyncio
from typing import Dict, Any, Optional
import httpx
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import ACTIVE_TIMEFRAME_PAIR

# Константы теста
SYMBOL_TO_TEST = 'BTCUSDT'
BINANCE_BASE_URL = "https://fapi.binance.com"

# Допустимые отклонения
TOLERANCE_PRICE = 0.01
TOLERANCE_OI = 1.0


async def _fetch_binance_klines(symbol: str, interval: str, limit: int = 2) -> Optional[list]:
    """Получает Klines с Binance API"""
    url = f"{BINANCE_BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Binance Klines HTTP {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logging.error(f"Ошибка получения Klines: {e}")
            return None


async def _fetch_binance_oi(symbol: str, period: str, limit: int = 2) -> Optional[list]:
    """Получает Open Interest с Binance API"""
    url = f"{BINANCE_BASE_URL}/futures/data/openInterestHist?symbol={symbol}&period={period}&limit={limit}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Binance OI HTTP {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logging.error(f"Ошибка получения OI: {e}")
            return None


def _parse_binance_klines(raw_klines: list, interval: str) -> list:
    """Парсит Klines из Binance в наш формат"""
    parsed = []
    interval_ms = {
        '4h': 4 * 60 * 60 * 1000,
        '8h': 8 * 60 * 60 * 1000, 
        '12h': 12 * 60 * 60 * 1000,
        '1d': 24 * 60 * 60 * 1000
    }.get(interval.lower(), 0)
    
    for kline in raw_klines:
        parsed.append({
            'openTime': kline[0],
            'closeTime': kline[0] + interval_ms - 1,
            'openPrice': float(kline[1]),
            'highPrice': float(kline[2]),
            'lowPrice': float(kline[3]),
            'closePrice': float(kline[4]),
            'volume': float(kline[5]),
            'quoteVolume': float(kline[7]),
            'trades': kline[8],
            'takerBuyBaseVolume': float(kline[9]),
            'takerBuyQuoteVolume': float(kline[10])
        })
    return parsed


def _parse_binance_oi(raw_oi: list) -> list:
    """Парсит Open Interest из Binance в наш формат"""
    parsed = []
    for oi_entry in raw_oi:
        parsed.append({
            'openTime': oi_entry['timestamp'],
            'openInterest': float(oi_entry['sumOpenInterest']),
            'openInterestValue': float(oi_entry['sumOpenInterestValue'])
        })
    return parsed


async def _get_source_data(timeframe: str) -> Optional[Dict[str, Any]]:
    """
    Собирает исходные данные с Binance
    Возвращает последнюю полную свечу (режем неполную)
    """
    oi_period_map = {
        '4h': '4h',
        '8h': '4h',
        '12h': '12h',
        '1d': '1d'
    }
    oi_period = oi_period_map.get(timeframe, '1h')
    
    raw_klines = await _fetch_binance_klines(SYMBOL_TO_TEST, timeframe, 2)
    raw_oi = await _fetch_binance_oi(SYMBOL_TO_TEST, oi_period, 2)
    
    if not raw_klines:
        logging.error(f"Не удалось получить Klines для {timeframe}")
        return None
        
    klines = _parse_binance_klines(raw_klines, timeframe)
    oi_data = _parse_binance_oi(raw_oi) if raw_oi else []
    
    # Режем последнюю свечу с биржи (неполная)
    if len(klines) > 1:
        klines = klines[:-1]
    
    if not klines:
        logging.error(f"Нет данных после обрезки для {timeframe}")
        return None
        
    latest_candle = klines[-1]
    target_ot = latest_candle['openTime']
    target_ct = latest_candle['closeTime']
    
    # Ищем OI внутри временного окна свечи, берем самый ранний
    best_oi = None
    for oi_entry in sorted(oi_data, key=lambda x: x['openTime']):
        oi_time = oi_entry['openTime']
        if target_ot <= oi_time <= target_ct:
            best_oi = oi_entry['openInterest']
            break
    
    # Если не нашли внутри, берем последний перед началом свечи
    if best_oi is None:
        for oi_entry in sorted(oi_data, key=lambda x: x['openTime'], reverse=True):
            if oi_entry['openTime'] < target_ot:
                best_oi = oi_entry['openInterest']
                break
    
    latest_candle['openInterest'] = best_oi
    
    logging.info(f"Для {timeframe}: свеча {target_ot}-{target_ct}, OI={best_oi}")
    
    return latest_candle


async def _get_cached_candle(client: httpx.AsyncClient, timeframe: str) -> Optional[Dict[str, Any]]:
    """Получает последнюю свечу из кэша (ничего не режем)"""
    try:
        response = await client.get(f"/get-cache/{timeframe}")
        if response.status_code == 200:
            data = response.json()
            
            for coin_data in data.get('data', []):
                if coin_data.get('symbol') == SYMBOL_TO_TEST:
                    candles = coin_data.get('data', [])
                    if candles:
                        return candles[-1]
                        
            logging.warning(f"BTCUSDT не найден в кэше {timeframe}")
            return None
        else:
            logging.error(f"Ошибка получения кэша {timeframe}: HTTP {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Ошибка загрузки кэша {timeframe}: {e}")
        return None


def _compare_candles(source: Dict, cached: Dict, timeframe: str) -> bool:
    """Сравнивает свечу из источника и из кэша"""
    is_consistent = True
    
    logging.info(f"Сравнение {timeframe}:")
    logging.info(f"  Source: OT={source.get('openTime')}, CT={source.get('closeTime')}, Close={source.get('closePrice')}, OI={source.get('openInterest')}")
    logging.info(f"  Cached: OT={cached.get('openTime')}, CT={cached.get('closeTime')}, Close={cached.get('closePrice')}, OI={cached.get('openInterest')}")
    
    if source.get('openTime') != cached.get('openTime'):
        logging.error(f"❌ Несоответствие openTime: source={source.get('openTime')}, cache={cached.get('openTime')}")
        is_consistent = False
    else:
        logging.info(f"✅ openTime совпадает: {source.get('openTime')}")
    
    if source.get('closeTime') != cached.get('closeTime'):
        logging.error(f"❌ Несоответствие closeTime: source={source.get('closeTime')}, cache={cached.get('closeTime')}")
        is_consistent = False
    else:
        logging.info(f"✅ closeTime совпадает: {source.get('closeTime')}")
    
    source_close = source.get('closePrice')
    cached_close = cached.get('closePrice')
    if source_close and cached_close:
        price_diff = abs(source_close - cached_close)
        if price_diff > TOLERANCE_PRICE:
            logging.error(f"❌ Расхождение closePrice: {price_diff:.4f} > {TOLERANCE_PRICE}")
            is_consistent = False
        else:
            logging.info(f"✅ closePrice в допуске: diff={price_diff:.4f}")
    else:
        logging.warning("⚠️ Отсутствует closePrice для сравнения")
    
    source_oi = source.get('openInterest')
    cached_oi = cached.get('openInterest')
    if source_oi is not None and cached_oi is not None:
        oi_diff = abs(source_oi - cached_oi)
        if oi_diff > TOLERANCE_OI:
            logging.error(f"❌ Расхождение OI: {oi_diff:.1f} > {TOLERANCE_OI}")
            is_consistent = False
        else:
            logging.info(f"✅ OI в допуске: diff={oi_diff:.1f}")
    elif source_oi is not None and cached_oi is None:
        logging.warning(f"⚠️ OI в source есть ({source_oi}), но в cache отсутствует")
    elif source_oi is None and cached_oi is not None:
        logging.warning(f"⚠️ OI в cache есть ({cached_oi}), но в source отсутствует")
    else:
        logging.info("ℹ️ OI отсутствует в обоих источниках")
    
    return is_consistent


async def run_cache_consistency_check(client: httpx.AsyncClient, log: logging.Logger) -> bool:
    """
    Сценарий 4: Проверка консистентности кэша с данными биржи
    """
    log.info("=" * 60)
    log.info("--- 🔎 [Сценарий 4] Консистентность кэша (Cache vs Binance) ---")
    
    base_tf, target_tf = ACTIVE_TIMEFRAME_PAIR.lower().split('_')
    
    log.info(f"Проверяем пару таймфреймов: {base_tf.upper()} -> {target_tf.upper()}")
    
    all_passed = True
    
    for timeframe in [base_tf, target_tf]:
        log.info(f"\n--- Проверка {timeframe.upper()} ---")
        
        log.info("Получаем данные с Binance...")
        source_candle = await _get_source_data(timeframe)
        if not source_candle:
            log.error(f"💥 Не удалось получить исходные данные для {timeframe}")
            all_passed = False
            continue
            
        log.info("Получаем данные из кэша...")
        cached_candle = await _get_cached_candle(client, timeframe)
        if not cached_candle:
            log.error(f"💥 Не удалось получить данные кэша для {timeframe}")
            all_passed = False
            continue
        
        log.info("Сравниваем данные...")
        timeframe_passed = _compare_candles(source_candle, cached_candle, timeframe)
        
        if timeframe_passed:
            log.info(f"✅ {timeframe.upper()} - КОНСИСТЕНТНО")
        else:
            log.error(f"💥 {timeframe.upper()} - НЕКОНСИСТЕНТНО")
            all_passed = False
    
    status = "УСПЕХ! ОИ И КЛЯЙН В ПОРЯДКЕ!!!" if all_passed else "ПРОВАЛ"
    emoji = "✅" if all_passed else "💥"
    
    log.info(f"\n--- {emoji} [Сценарий 4] Консистентность: {status} ---")
    return all_passed