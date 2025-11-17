# data_collector/data_processing.py

import logging
from typing import List, Dict, Any, Optional, Tuple, Set, Union
from collections import defaultdict
import math
import zlib
import json
import time # ДОБАВЛЕН ИМПОРТ

logger = logging.getLogger(__name__)

# --- ВРЕМЕННЫЕ КОНСТАНТЫ ---
# Сопоставление интервалов с их длительностью в миллисекундах
INTERVAL_MAP_MS = {
    '1m': 60 * 1000,
    '3m': 3 * 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '2h': 2 * 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
    '6h': 6 * 60 * 60 * 1000,
    '8h': 8 * 60 * 60 * 1000,
    '12h': 12 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '3d': 3 * 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
}
# -----------------------------

def get_interval_duration_ms(interval: str) -> int:
    """Возвращает длительность интервала в миллисекундах."""
    return INTERVAL_MAP_MS.get(interval.lower(), 0)

def normalize_to_open_time(timestamp: Optional[int], interval_ms: int) -> Optional[int]:
    """Нормализует временную метку к ближайшему началу интервала."""
    if timestamp is None or interval_ms <= 0:
        return None
    return (timestamp // interval_ms) * interval_ms

def calculate_volume_delta(klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Рассчитывает 'volumeDelta' для списка Klines.
    Volume Delta = Volume (Buy) - Volume (Sell)
    """
    
    for kline in klines:
        if 'volumeDelta' not in kline:
            try:
                # ... (логика расчета volumeDelta)
                if 'buyVolume' in kline and 'sellVolume' in kline:
                    buy_volume = float(kline['buyVolume'])
                    sell_volume = float(kline['sellVolume'])
                    kline['volumeDelta'] = buy_volume - sell_volume
                else:
                    kline['volumeDelta'] = 0.0
                   
            except (TypeError, ValueError) as e:
                logger.warning(f"Ошибка расчета volumeDelta: {e}")
                kline['volumeDelta'] = None
                
    return klines


def _align_and_merge_by_time(data_by_type: Dict[str, List[Dict[str, Any]]], base_timeframe: str) -> List[Dict[str, Any]]:
    """
    Нормализует временные метки всех типов данных (Klines, OI, FR) к интервалу Base-TF
    и объединяет их в единый массив Klines, выбирая наиболее релевантное
    значение (OI/FR) для каждого интервала.
    Returns: List[Dict[str, Any]] - список Klines, дополненных OI и FR.
    """
    base_interval_ms = get_interval_duration_ms(base_timeframe)
    if base_interval_ms == 0:
        logger.error(f"Неизвестный базовый таймфрейм: {base_timeframe}")
        return []

    merged_map: Dict[int, Dict[str, Any]] = defaultdict(lambda: {'timestamp': 0})

    for data_type, entries in data_by_type.items():
        
        if data_type == 'klines':
            pass 
        elif data_type == 'oi':
            # ИЗМЕНЕНИЕ: Инициализируем timestamp как float('inf') для выбора САМОГО РАННЕГО снимка (Min Timestamp)
            oi_snapshot_map = defaultdict(lambda: {'openInterest': None, 'timestamp': float('inf')})
        elif data_type == 'fr':
            # Для FR: Выбираем САМЫЙ СВЕЖИЙ снимок (Max Timestamp)
            fr_snapshot_map = defaultdict(lambda: {'fundingRate': None, 'timestamp': 0})

        for entry in entries:
            entry_timestamp = entry.get('openTime') 
            
            if entry_timestamp is None:
                continue

            time_key = normalize_to_open_time(entry_timestamp, base_interval_ms)

            if time_key is None:
                continue

            if data_type == 'klines':
                merged_map[time_key]['klines'] = entry 

            elif data_type == 'oi':
                current_best = oi_snapshot_map[time_key]
                
                # ИЗМЕНЕНИЕ: Выбираем САМЫЙ РАННИЙ снимок OI (для соответствия эталону Binance)
                if entry_timestamp < current_best['timestamp']: 
                    current_best['timestamp'] = entry_timestamp
                    current_best['openInterest'] = entry.get('openInterest')

            elif data_type == 'fr':
                current_best = fr_snapshot_map[time_key]

                # Для FR: Выбираем САМЫЙ СВЕЖИЙ снимок 
                if entry_timestamp > current_best['timestamp']:
                    current_best['timestamp'] = entry_timestamp
                    current_best['fundingRate'] = entry.get('fundingRate')

    # Шаг 2: Слияние Klines с лучшими снимками OI и FR
    klines_only = [item.get('klines', {}) for time_key, item in merged_map.items() if 'klines' in item]
    klines_only.sort(key=lambda k: k.get('openTime', 0))
    klines_map = {kline['openTime']: kline for kline in klines_only if 'openTime' in kline}
    
    # Добавляем OI
    if 'oi_snapshot_map' in locals():
        for time_key, data in oi_snapshot_map.items():
            if time_key in klines_map and data['openInterest'] is not None:
                klines_map[time_key]['openInterest'] = data['openInterest']
            
    # Добавляем FR
    if 'fr_snapshot_map' in locals():
         for time_key, data in fr_snapshot_map.items():
            if time_key in klines_map and data['fundingRate'] is not None:
                klines_map[time_key]['fundingRate'] = data['fundingRate']

    return list(klines_map.values())


def merge_data(data_by_type: Dict[str, List[Dict[str, Any]]], base_timeframe: str) -> List[Dict[str, Any]]:
    """
    Основная функция объединения данных.
    1. Объединяет Klines, OI, FR по времени (используя Base-TF).
    2. Рассчитывает volumeDelta, если он отсутствует.
    """
    
    merged_klines = _align_and_merge_by_time(data_by_type, base_timeframe)
    
    if not merged_klines:
        logger.warning(f"Не удалось слить данные для Base-TF {base_timeframe}.")
        return []
        
    final_klines = calculate_volume_delta(merged_klines)
    
    final_klines = [k for k in final_klines if 'openTime' in k]
    
    return final_klines

# --- ИСПРАВЛЕНИЕ: ЭТА ФУНКЦИЯ ПОЛНОСТЬЮ ПЕРЕПИСАНА ---
def format_final_structure(
    coin_data_list: List[Dict[str, Any]], 
    all_coins: List[Dict], # (all_coins больше не используется, но оставлен для совместимости сигнатуры)
    timeframe: str
) -> Dict[str, Any]:
    """
    (ВОССТАНОВЛЕННАЯ ЛОГИКА)
    Форматирует окончательную структуру для сохранения в кэше Redis.
    - Вычисляет 'openTime' и 'closeTime' для корня кэша.
    - Использует ключ 'data' (список), а не 'coins' (словарь).
    - Восстанавливает блок 'audit' для корректного логгирования.
    """
    
    max_open_time = 0
    max_close_time = 0
    
    # Мы ожидаем 'coin_data_list' в формате:
    # [{'symbol': 'BTC', 'data': [...], 'exchanges': [...]}, ...]
    
    for coin_obj in coin_data_list:
        klines = coin_obj.get('data', [])
        
        if klines:
            # Находим самую последнюю свечу в списке
            last_kline = klines[-1]
            
            current_open = last_kline.get('openTime', 0)
            current_close = last_kline.get('closeTime', 0)
            
            if current_open > max_open_time:
                max_open_time = current_open
            
            if current_close > max_close_time:
                max_close_time = current_close

    # Восстанавливаем блок 'audit' (исправляет лог N/A)
    final_count = len(coin_data_list)
    audit_block = {
        "timestamp": int(time.time() * 1000),
        "source": "data_collector",
        "symbols_in_final_list": final_count
    }

    # Собираем правильную структуру
    final_structure = {
        "timeframe": timeframe,
        "openTime": max_open_time,   # (Исправляет test_2_cache_freshness)
        "closeTime": max_close_time, # (Исправляет test_2_cache_freshness)
        "data": coin_data_list,      # (Исправляет 404 в api_routes и test_4)
        "audit": audit_block         # (Исправляет 'N/A' в cache_manager)
    }
            
    return final_structure
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

def serialize_data(data: List[Dict[str, Any]]) -> bytes:
    """Сериализует список Klines в JSON, затем сжимает с помощью zlib."""
    try:
        json_data = json.dumps(data, separators=(',', ':')).encode('utf-8')
        return zlib.compress(json_data, 9)
    except Exception as e:
        logger.error(f"Ошибка сериализации данных: {e}", exc_info=True)
        return b''


def deserialize_data(data: bytes) -> Optional[List[Dict[str, Any]]]:
    """Разжимает данные с помощью zlib и десериализует JSON."""
    if not data:
        return None
    try:
        decompressed_data = zlib.decompress(data)
        return json.loads(decompressed_data.decode('utf-8'))
    except zlib.error as e:
        logger.error(f"Ошибка декомпрессии данных (zlib): {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка десериализации данных (JSON): {e}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка десериализации: {e}")
        return None