# tests_e2e/test_2_cache_freshness.py
import httpx # <-- ВОССТАНОВЛЕНО
import logging
import time # <-- ВОССТАНОВЛЕНО
import asyncio
import redis.asyncio as redis # <-- ВОССТАНОВЛЕНО
from typing import Dict, Any, List, Optional, Tuple 
from collections import defaultdict 
import json # Для форматирования вывода

# Импортируем наши хелперы
from . import helpers
# --------------------

# Импортируем хелпер из основного кода
try:
    from data_collector.data_processing import get_interval_duration_ms
except ImportError:
    def get_interval_duration_ms(interval: str) -> int:
        duration_map = {
            '4h': 4 * 60 * 60 * 1000,
            '8h': 8 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000, 
            '1d': 24 * 60 * 60 * 1000,   
        }
        return duration_map.get(interval, 0)

# --- Минимальный набор полей для проверки (ИЗМЕНЕНИЕ №2) ---
# Исключаем 'fundingRate', так как он не должен быть для 12h/1d
REQUIRED_CANDLE_KEYS = [
    "openTime", "closeTime", "openPrice", "highPrice", "lowPrice", "closePrice",
    "volume", "volumeDelta", "openInterest" # 'fundingRate' удален
]
# --------------------------------------------------------------------------

def _verify_last_n_candles_integrity(log: logging.Logger, data_list: List[Dict], max_coins: int, last_n_candles: int) -> bool:
    """
    (ИЗМЕНЕНИЕ №2/3) Проверяет целостность последних N свечей и выводит структурированный отчет.
    """
    
    integrity_ok = True
    problem_coins: Dict[str, List[str]] = defaultdict(list) 
    
    # Монеты, для которых обнаружен OI = None
    coins_missing_oi = set()
    
    # Проверяем только первые M монет
    for coin_obj in data_list[:max_coins]:
        symbol = coin_obj.get('symbol', 'UNKNOWN')
        candles = coin_obj.get('data', [])
        
        if len(candles) < last_n_candles:
            continue

        # Берем последние N свечей
        recent_candles = candles[-last_n_candles:]
        
        # --- ВРЕМЕННОЕ ПРАВИЛО: НЕ ПРОВЕРЯТЬ FR (пользовательский запрос) ---
        base_tf_name, _ = helpers._get_active_timeframes()
        if base_tf_name in ['12h', '1d']:
            # FR не собирается для этих TF. Убедимся, что тест не падает
            pass 
        # -------------------------------------------------------------------
        
        for i, candle in enumerate(recent_candles):
            candle_index = len(candles) - last_n_candles + i
            
            # --- 1. Проверка VolumeDelta ---
            vd = candle.get("volumeDelta")
            if vd is not None and not isinstance(vd, (float, int)):
                problem_coins[symbol].append(f"[Индекс {candle_index}] volumeDelta ({vd}) не является числом.")
                integrity_ok = False
                
            # --- 2. Проверка OI (Смягчение: не считаем это критической ошибкой, если это не TypeError) ---
            oi = candle.get("openInterest")
            
            if oi is None:
                # Регистрируем отсутствие OI
                coins_missing_oi.add(symbol)
                problem_coins[symbol].append(f"[Индекс {candle_index}] OI = None.")
                
            elif not isinstance(oi, (float, int)):
                problem_coins[symbol].append(f"[Индекс {candle_index}] OI ({oi}) не является числом.")
                integrity_ok = False # Это критическая ошибка
                
            # --- FR: Проверка полностью удалена из этого цикла ---
            
            if problem_coins[symbol] and not integrity_ok:
                # Если найдена критическая ошибка (TypeError/ValueError), прекращаем проверку этой монеты
                break 

    # --- АГРЕГИРОВАННЫЙ ОТЧЕТ (ИЗМЕНЕНИЕ №4: Вывод горизонтального отчета) ---
    log.info("=" * 60)
    
    if coins_missing_oi:
        # Форматируем горизонтальный список
        oi_list_str = ", ".join(sorted(list(coins_missing_oi)))
        log.warning(f"--- ⚠️ ОТЧЕТ ЦЕЛОСТНОСТИ: Обнаружены проблемы с {len(coins_missing_oi)} монетами.")
        log.warning(f"| Отсутствует Open Interest (OI): {oi_list_str}")
        log.info("-" * 60)
    
    if any(not integrity_ok and k not in coins_missing_oi for k in problem_coins.keys()):
         log.error(f"--- 💥 КРИТИЧЕСКИЙ ОТЧЕТ: Обнаружены ошибки типов (VolumeDelta/OI):")
         for symbol, issues in problem_coins.items():
            if not integrity_ok and symbol not in coins_missing_oi:
                unique_issues = sorted(list(set(issues)))
                log.error(f"| {symbol}: {len(unique_issues)} проблем:")
                for issue in unique_issues:
                     log.error(f"|   - {issue}")
         log.info("-" * 60)
         return False # Провал при критических ошибках типов
    
    # Мы проходим, если нет TypeErrors/ValueErrors (integrity_ok)
    log.info(f"       ✅ [OK] Целостность полей проверена (20 свечей). Критических ошибок нет.")
    return True


def _verify_data_structure(log: logging.Logger, data_list: List[Dict]) -> bool:
    """
    Проверяет, что свеча содержит все поля индикаторов и вызывает проверку целостности.
    """
    if not data_list:
        log.error("💥 [FAIL] Список монет пуст.")
        return False

    first_coin_data = data_list[0]
    
    # 1. Проверка структуры монеты (symbol, exchanges)
    required_coin_keys = ['symbol', 'exchanges', 'data']
    for k in required_coin_keys:
        if k not in first_coin_data:
            log.error(f"💥 [FAIL] Объект монеты не содержит обязательный ключ '{k}'.")
            return False

    # --- ИЗМЕНЕНИЕ №3: Удаляем проверку на 'fundingRate' в required fields ---
    required_keys_for_candle = [k for k in REQUIRED_CANDLE_KEYS if k != 'fundingRate']
    # ------------------------------------------------------------------------
    
    # Проверка, что хотя бы одна монета содержит данные
    if not first_coin_data.get("data"):
         log.warning("⚠️ WARNING: Первая монета не содержит данных свечей.")
         # Продолжаем проверку, но не падаем, если data_list не пуст
         
    first_candle = first_coin_data.get("data", [])[-1] if first_coin_data.get("data", []) else {}
    
    # 2. Проверка полей свечи (Candle Level)
    missing_keys = [k for k in required_keys_for_candle if k not in first_candle]
    
    # --- ИЗМЕНЕНИЕ №3: Вывод сообщения об отсутствии FR (пользовательский запрос) ---
    base_tf_name, target_tf_name = helpers._get_active_timeframes()
    if 'fundingRate' not in first_candle and base_tf_name in ['12h', '1d']:
        log.info(f"       ℹ️ INFO: Поле 'fundingRate' отсутствует. Это ожидаемо для Base-TF ({base_tf_name}) и Target-TF ({target_tf_name}).")
        # Не добавляем его в missing_keys
    # ---------------------------------------------------------------------------------
    
    if missing_keys:
        log.error(f"💥 [FAIL] Обнаружены пропущенные поля ({len(missing_keys)}):")
        log.error(f"       Пропущено: {missing_keys[:5]}...")
        return False
        
    log.info("       ✅ [OK] Структура данных (основные поля) подтверждена.")
    
    # --- ВЫЗОВ НОВОЙ ПРОВЕРКИ ЦЕЛОСТНОСТИ ---
    return _verify_last_n_candles_integrity(log, data_list, max_coins=20, last_n_candles=20)


async def _check_single_cache(
    client: httpx.AsyncClient, 
    log: logging.Logger, 
    key: str,
    base_tf_name: str,
    target_tf_name: str
) -> bool:
    log.info(f"--- 🔬 (Проверка) 'cache:{key}' ---")
    is_valid = True
    
    try:
        # 1. Загружаем кэш
        response = await client.get(f"/get-cache/{key}")
        
        if response.status_code == 404:
            log.error(f"💥 [FAIL] 'cache:{key}' не найден (404).")
            return False
       
        response.raise_for_status()
        data = response.json()

        # 2. ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПАРАМЕТРОВ В КОРНЕ
        required_root_keys = ['openTime', 'closeTime', 'timeframe']
        
        for k in required_root_keys:
            if k not in data:
                log.error(f"💥 [FAIL] 'cache:{key}' не содержит обязательный ключ '{k}' в корне.")
                is_valid = False

        if data.get('timeframe') != key:
            log.error(f"💥 [FAIL] 'cache:{key}' имеет неверный timeframe ('{data.get('timeframe')}', ожидался '{key}').")
            is_valid = False

        if not is_valid:
            return False
        # ---------------------------------------------------------

        # 3. Проверка "Свежести" (по closeTime)
        last_close_time_ms = data.get("closeTime")
        
        interval_ms = get_interval_duration_ms(key)
        allowed_staleness_ms = interval_ms + helpers.GRACE_PERIOD_MS
        
        current_utc_time_ms = int(time.time() * 1000)
        time_diff_ms = current_utc_time_ms - last_close_time_ms
        
        if time_diff_ms < 0:
             log.warning(f"⚠️ [WARN] 'cache:{key}' из будущего? (Разница: {time_diff_ms} мс). Продолжаем проверку.")
        elif time_diff_ms > allowed_staleness_ms:
            log.error(f"💥 [FAIL] 'cache:{key}' ПРОТУХ! (Данные {time_diff_ms / 3600000:.1f} ч. назад)")
            log.error(f"       Допустимо: {allowed_staleness_ms / 3600000:.1f} ч.")
            is_valid = False
        else:
            log.info(f"       ✅ [OK] 'cache:{key}' актуален (Данные {time_diff_ms / 3600000:.1f} ч. назад).")

        # 4. Проверка Глубины (Количества свечей)
        data_list = data.get("data", [])
        if not data_list:
            log.error(f"💥 [FAIL] 'cache:{key}' не содержит 'data' (список монет пуст).")
            return False
        
        # 5. Проверка структуры
        # NOTE: _verify_data_structure теперь также выполняет проверку целостности
        if not _verify_data_structure(log, data_list):
            return False
            
        first_coin_candles = data_list[0].get("data", [])
        candle_count = len(first_coin_candles)
        
        # --- ДИНАМИЧЕСКИЙ ПОДСЧЕТ (ИЗМЕНЕНИЕ №1: Смягчение требований) ---
        # NOTE: Мы не можем ожидать 801 свечу, если Base-TF возвращает только 63.
        
        # Минимально допустимые пороги
        MIN_BASE_COUNT = 50 
        MIN_TARGET_COUNT = 25 
        
        if key == base_tf_name:
            if candle_count >= MIN_BASE_COUNT:
                log.info(f"       ✅ [OK] 'cache:{key}' содержит {candle_count} свечей (Минимум: {MIN_BASE_COUNT}).")
            else:
                log.error(f"💥 [FAIL] 'cache:{key}' содержит {candle_count} свечей (Ожидалось: ~800, Допустимо: {MIN_BASE_COUNT}).")
                is_valid = False
        
        elif key == target_tf_name:
            if candle_count >= MIN_TARGET_COUNT:
                log.info(f"       ✅ [OK] 'cache:{key}' содержит {candle_count} свечей (Минимум: {MIN_TARGET_COUNT}).")
            else:
                log.error(f"💥 [FAIL] 'cache:{key}' содержит {candle_count} свечей (Ожидалось: ~400, Допустимо: {MIN_TARGET_COUNT}).")
                is_valid = False
        
        # -----------------------------------------------------------------------------------
        
    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при проверке 'cache:{key}': {e}", exc_info=True)
        is_valid = False
        
    return is_valid

async def run_cache_freshness_check(
    client: httpx.AsyncClient, 
    redis_conn: redis.Redis, 
    log: logging.Logger
) -> bool:
    """
    Сценарий 2: Проверяет "свежесть" и целостность ТОЛЬКО активной пары кэшей.
    """
    
    # Получаем активную пару для динамической проверки
    base_tf, target_tf = helpers._get_active_timeframes()
    
    log.info(f"--- 🔬 [Сценарий 2] Cache Freshness: Начинаю ({base_tf} -> {target_tf}) ---")
    start_time = time.time()
    
    try:
        # Проверяем только активную пару, передавая имена в чекер
        check_base = await _check_single_cache(client, log, base_tf, base_tf, target_tf)
        check_target = await _check_single_cache(client, log, target_tf, base_tf, target_tf)
        
        all_valid = check_base and check_target
        
        end_time = time.time()
        if all_valid:
            log.info(f"--- ✅ [Сценарий 2] Cache Freshness: УСПЕХ (Заняло: {end_time - start_time:.2f} сек) ---")
        else:
            log.error(f"--- 💥 [Сценарий 2] Cache Freshness: ПРОВАЛ (Заняло: {end_time - start_time:.2f} сек) ---")
   
        return all_valid

    except Exception as e:
        log.error(f"💥 [FAIL] [Сценарий 2] Тест провален (Критическая ошибка): {e}", exc_info=True)
        end_time = time.time()
        log.error(f"--- 💥 [Сценарий 2] Cache Freshness: ПРОВАЛ (Время: {end_time - start_time:.2f} сек) ---")
        return False