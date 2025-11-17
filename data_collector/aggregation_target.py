# data_collector/aggregation_target.py

import asyncio
import os
import sys
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
import math
from datetime import datetime
from redis.asyncio import Redis as AsyncRedis 
import json 

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from cache_manager import (
    get_redis_connection,
    save_to_cache, 
    load_from_cache 
)

from data_collector.data_processing import merge_data, format_final_structure, get_interval_duration_ms 

try:
    from data_collector.logging_setup import logger
except ImportError:
    logger = logging.getLogger(__name__)

# --- НОВАЯ ФУНКЦИЯ: UTC-выравнивание ---
def _align_to_utc_boundary(timestamp: int, target_interval_ms: int) -> int:
    """
    Выравнивает timestamp к ближайшей UTC-границе интервала.
    
    Для 8h: выравнивание на 00:00, 08:00, 16:00 UTC
    Для 1d: выравнивание на 00:00 UTC
    """
    ONE_DAY_MS = 86400000  # 24h
    
    if target_interval_ms == ONE_DAY_MS:  # 1d
        # Выравнивание на начало UTC-дня (00:00)
        return (timestamp // ONE_DAY_MS) * ONE_DAY_MS
    
    elif target_interval_ms == 28800000:  # 8h
        # Выравнивание на 00:00, 08:00, 16:00 UTC
        # 8h * 3 = 24h, поэтому сначала находим начало дня
        utc_day_start = (timestamp // ONE_DAY_MS) * ONE_DAY_MS
        # Затем находим ближайшую 8h границу внутри дня
        offset_in_day = timestamp - utc_day_start
        slot_in_day = (offset_in_day // target_interval_ms) * target_interval_ms
        return utc_day_start + slot_in_day
    
    else:
        # Для остальных интервалов (4h, 12h) - стандартное выравнивание
        return (timestamp // target_interval_ms) * target_interval_ms


def _aggregate_klines_to_target(
    base_klines: List[Dict[str, Any]], 
    target_interval_ms: int,
    base_interval_ms: int,
    symbol: str
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """Агрегирует Klines с UTC-выравниванием и проверкой полноты."""
    if not base_klines:
        return [], {}

    target_klines = []
    current_target_open_time = None
    accumulated_data = None
    
    aggregation_audit = defaultdict(lambda: defaultdict(list)) 
    current_base_klines = []
    
    base_klines.sort(key=lambda x: x['openTime'])

    for kline in base_klines:
        base_open_time = kline['openTime']
        
        # --- ИЗМЕНЕНИЕ: UTC-выравнивание ---
        expected_target_open_time = _align_to_utc_boundary(base_open_time, target_interval_ms)

        if current_target_open_time is None or expected_target_open_time != current_target_open_time:
            
            if accumulated_data is not None:
                # Проверка полноты свечи
                expected_duration = target_interval_ms
                actual_duration = accumulated_data["last_closeTime"] - accumulated_data["openTime"] + 1
                
                is_complete = actual_duration >= (expected_duration * 0.99)
                
                if is_complete:
                    final_kline = {
                        "openTime": accumulated_data["openTime"],
                        "closeTime": accumulated_data["last_closeTime"],
                        "openPrice": accumulated_data["openPrice"],
                        "highPrice": accumulated_data["highPrice"],
                        "lowPrice": accumulated_data["lowPrice"],
                        "closePrice": accumulated_data["last_closePrice"], 
                        "volume": accumulated_data["volume"],
                        "volumeDelta": accumulated_data["volumeDelta"],
                        "openInterest": None,
                        "fundingRate": None,
                    }
                    target_klines.append(final_kline)
                    
                    aggregation_audit[final_kline['openTime']]['target'] = final_kline
                    aggregation_audit[final_kline['openTime']]['base_klines'] = current_base_klines
                else:
                    logger.debug(f"Пропускаю неполную свечу {symbol}: {accumulated_data['openTime']} (длительность {actual_duration}/{expected_duration} мс)")
                
                current_base_klines = []
            
            current_target_open_time = expected_target_open_time
            accumulated_data = {
                "openTime": current_target_open_time,
                "openPrice": kline['openPrice'],
                "highPrice": kline['highPrice'],
                "lowPrice": kline['lowPrice'],
                "volume": kline['volume'],
                "volumeDelta": kline.get('volumeDelta', 0), 
                "last_closeTime": kline['closeTime'],
                "last_closePrice": kline['closePrice']
            }
            current_base_klines.append(kline)

        else:
            accumulated_data["highPrice"] = max(accumulated_data["highPrice"], kline['highPrice'])
            accumulated_data["lowPrice"] = min(accumulated_data["lowPrice"], kline['lowPrice'])
            accumulated_data["volume"] += kline['volume']
            accumulated_data["volumeDelta"] += kline.get('volumeDelta', 0) 
            accumulated_data["last_closeTime"] = kline['closeTime']
            accumulated_data["last_closePrice"] = kline['closePrice']
            current_base_klines.append(kline)
    
    # Проверка последней свечи
    if accumulated_data is not None:
        expected_duration = target_interval_ms
        actual_duration = accumulated_data["last_closeTime"] - accumulated_data["openTime"] + 1
        
        is_complete = actual_duration >= (expected_duration * 0.99)
        
        if is_complete:
            final_kline = {
                "openTime": accumulated_data["openTime"],
                "closeTime": accumulated_data["last_closeTime"],
                "openPrice": accumulated_data["openPrice"],
                "highPrice": accumulated_data["highPrice"],
                "lowPrice": accumulated_data["lowPrice"],
                "closePrice": accumulated_data["last_closePrice"], 
                "volume": accumulated_data["volume"],
                "volumeDelta": accumulated_data["volumeDelta"],
                "openInterest": None,
                "fundingRate": None,
            }
            target_klines.append(final_kline)
            
            aggregation_audit[final_kline['openTime']]['target'] = final_kline
            aggregation_audit[final_kline['openTime']]['base_klines'] = current_base_klines
        else:
            logger.debug(f"Пропускаю неполную последнюю свечу {symbol}: {accumulated_data['openTime']} (длительность {actual_duration}/{expected_duration} мс)")

    return target_klines, dict(aggregation_audit)


async def generate_and_save_target_cache(
    target_tf: str, 
    base_tf: str,
    all_coins: List[Dict],
    redis_conn: AsyncRedis
) -> bool:
    """
    Генерирует Target-Cache (например, 1d) из Base-Cache (например, 12h).
    """
    logger.info(f"[{target_tf.upper()}] Запуск генерации {target_tf} из {base_tf}...")
    
    base_cache_key = base_tf
    target_cache_key = target_tf

    base_cache_data = await load_from_cache(base_cache_key, redis_conn=redis_conn)
    
    if not base_cache_data or not base_cache_data.get('data'):
        logger.error(f"[{target_tf.upper()}] Не удалось загрузить или Base-Cache {base_tf} пуст.")
        return False

    base_data_list = base_cache_data['data']
    
    base_interval_ms = get_interval_duration_ms(base_tf)
    target_interval_ms = get_interval_duration_ms(target_tf)
    
    if base_interval_ms == 0 or target_interval_ms == 0:
        logger.error(f"[{target_tf.upper()}] Неизвестный интервал Base-TF ({base_tf}) или Target-TF ({target_tf}).")
        return False
        
    if target_interval_ms <= base_interval_ms:
        logger.error(f"[{target_tf.upper()}] Target-TF ({target_tf}) должен быть больше Base-TF ({base_tf}).")
        return False

    logger.info(f"[{target_tf.upper()}_GEN] Начинаю генерацию данных {target_tf} из {base_tf}...")
    
    all_merged_results = []
    successful_aggregation = 0
    total_base_coins = len(base_data_list) 

    for coin_data in base_data_list: 
        symbol = coin_data['symbol']
        base_klines = coin_data['data']
        
        if base_klines:
            
            target_klines, audit_report = _aggregate_klines_to_target(
                base_klines, target_interval_ms, base_interval_ms, symbol
            )
            
            oi_map = defaultdict(lambda: {'openTime': 0, 'openInterest': None, 'timestamp': float('inf')})
            fr_map = defaultdict(lambda: {'openTime': 0, 'fundingRate': None, 'timestamp': 0})
            
            for candle in base_klines:
                # --- ИЗМЕНЕНИЕ: UTC-выравнивание для OI/FR ---
                target_open_time = _align_to_utc_boundary(candle['openTime'], target_interval_ms)
                candle_time = candle.get('openTime')
                
                oi_value = candle.get('openInterest')
                if oi_value is not None:
                     current_best_oi = oi_map[target_open_time]
                     if candle_time < current_best_oi['timestamp']:
                         current_best_oi['timestamp'] = candle_time
                         current_best_oi['openTime'] = target_open_time
                         current_best_oi['openInterest'] = oi_value    
                
                fr_value = candle.get('fundingRate')
                if fr_value is not None:
                    current_best_fr = fr_map[target_open_time]
                    if candle_time > current_best_fr['timestamp']:
                         current_best_fr['timestamp'] = candle_time
                         current_best_fr['openTime'] = target_open_time
                         current_best_fr['fundingRate'] = fr_value
            
            oi_entries = [v for v in oi_map.values() if v['openInterest'] is not None]
            fr_entries = [v for v in fr_map.values() if v['fundingRate'] is not None]
            
            data_by_type = {
                'klines': target_klines,
                'oi': oi_entries,
                'fr': fr_entries
            }
            
            merged_result = merge_data(data_by_type, target_tf)
            
            if merged_result:
                all_merged_results.append({
                    'symbol': symbol,
                    'data': merged_result,
                    'exchanges': coin_data.get('exchanges', [])
                })
                successful_aggregation += 1

    logger.info(f"[{target_tf.upper()}_GEN] Агрегация {base_tf}->{target_tf} завершена.")
    logger.info(f"[{target_tf.upper()}_GEN] Всего монет с {base_tf}-данными: {total_base_coins}. Успешно обработано: {successful_aggregation}. Пропущено: {total_base_coins - successful_aggregation}.")
    
    logger.info(f"[{target_tf.upper()}_GEN] Начинаю слияние данных {target_tf}...")
    
    final_cache_structure = format_final_structure(
        all_merged_results, all_coins, target_tf
    )
    
    success = await save_to_cache(redis_conn, target_cache_key, final_cache_structure)
    
    if success:
        logger.info(f"[{target_tf.upper()}] ✅ Задача {target_tf} успешно завершена и сохранена.")
    
    return success


async def run_target_generation_process(
    target_tf: str, 
    base_tf: str,
    all_coins: List[Dict]
) -> bool:
    """
    Главная точка входа для генерации Target-Cache.
    """
    redis_conn = None
    
    try:
        redis_conn = await get_redis_connection()
        if not redis_conn:
            logger.critical("Не удалось подключиться к Redis.")
            return False

        success = await generate_and_save_target_cache(target_tf, base_tf, all_coins, redis_conn)
        return success

    except Exception as e:
        logger.critical(f"[{target_tf.upper()}] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        return False
    
    finally:
        if redis_conn:
            pass