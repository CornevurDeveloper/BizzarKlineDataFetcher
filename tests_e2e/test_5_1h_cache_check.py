import httpx
import logging
import time
import redis.asyncio as redis

from . import helpers
from .test_2_cache_freshness import _verify_data_structure, get_interval_duration_ms

# Импорт конфигурации
try:
    from config import KLINES_LIMIT_1H
except ImportError:
    logging.warning("Не удалось импортировать KLINES_LIMIT_1H, используется значение по умолчанию 800")
    KLINES_LIMIT_1H = 800

TEST_TF = '1h'


async def _check_single_1h_cache(
    client: httpx.AsyncClient,
    log: logging.Logger
) -> bool:
    """
    Проверяет кэш 1h на корректность структуры, свежесть данных и глубину истории.
    
    Returns:
        True если все проверки пройдены успешно
    """
    log.info(f"--- 🔬 (Проверка) 'cache:{TEST_TF}' ---")
    is_valid = True
    
    try:
        # 1. Загружаем кэш
        response = await client.get(f"/get-cache/{TEST_TF}")
        
        if response.status_code == 404:
            log.error(f"💥 [FAIL] 'cache:{TEST_TF}' не найден (404).")
            return False
        
        response.raise_for_status()
        data = response.json()

        # 2. Проверка обязательных параметров в корне
        required_root_keys = ['openTime', 'closeTime', 'timeframe']
        
        for key in required_root_keys:
            if key not in data:
                log.error(
                    f"💥 [FAIL] 'cache:{TEST_TF}' не содержит обязательный ключ '{key}' в корне."
                )
                is_valid = False

        if data.get('timeframe') != TEST_TF:
            log.error(
                f"💥 [FAIL] 'cache:{TEST_TF}' имеет неверный timeframe "
                f"('{data.get('timeframe')}', ожидался '{TEST_TF}')."
            )
            is_valid = False

        if not is_valid:
            return False
        
        # 3. Проверка "свежести" данных по closeTime
        last_close_time_ms = data.get("closeTime")
        
        interval_ms = get_interval_duration_ms(TEST_TF)
        allowed_staleness_ms = interval_ms + helpers.GRACE_PERIOD_MS
        
        current_utc_time_ms = int(time.time() * 1000)
        time_diff_ms = current_utc_time_ms - last_close_time_ms
        
        if time_diff_ms < 0:
            log.warning(
                f"⚠️ [WARN] 'cache:{TEST_TF}' из будущего? "
                f"(Разница: {time_diff_ms} мс). Продолжаем проверку."
            )
        elif time_diff_ms > allowed_staleness_ms:
            log.error(
                f"💥 [FAIL] 'cache:{TEST_TF}' ПРОТУХ! "
                f"(Данные {time_diff_ms / 3600000:.1f} ч. назад)"
            )
            log.error(f"       Допустимо: {allowed_staleness_ms / 3600000:.1f} ч.")
            is_valid = False
        else:
            log.info(
                f"       ✅ [OK] 'cache:{TEST_TF}' актуален "
                f"(Данные {time_diff_ms / 3600000:.1f} ч. назад)."
            )

        # 4. Проверка структуры и целостности данных
        data_list = data.get("data", [])
        if not data_list:
            log.error(f"💥 [FAIL] 'cache:{TEST_TF}' не содержит 'data' (список монет пуст).")
            return False
        
        if not _verify_data_structure(log, data_list):
            return False
            
        # 5. Проверка глубины истории (количества свечей)
        first_coin_candles = data_list[0].get("data", [])
        candle_count = len(first_coin_candles)
        
        # Ожидаемое количество: KLINES_LIMIT_1H - 1 (последняя незакрытая свеча обрезается)
        expected_count = KLINES_LIMIT_1H - 1
        
        if candle_count == expected_count:
            log.info(
                f"       ✅ [OK] 'cache:{TEST_TF}' содержит {candle_count} свечей "
                f"(Ожидалось: {expected_count})."
            )
        else:
            log.error(
                f"💥 [FAIL] 'cache:{TEST_TF}' содержит {candle_count} свечей "
                f"(Ожидалось: {expected_count})."
            )
            is_valid = False
        
    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при проверке 'cache:{TEST_TF}': {e}", exc_info=True)
        is_valid = False
        
    return is_valid


async def run_1h_cache_check(
    client: httpx.AsyncClient,
    redis_conn: redis.Redis,
    log: logging.Logger
) -> bool:
    """
    Сценарий 5: Запускает сбор данных 1h через API и проверяет корректность кэша.
    
    Args:
        client: HTTP клиент для запросов к API
        redis_conn: Соединение с Redis
        log: Логгер для вывода информации
    
    Returns:
        True если все проверки пройдены успешно
    """
    log.info("\n" + "=" * 60)
    log.info("--- 🔬 [Сценарий 5] 1H Cache Check: Начинаю ---")
    start_time = time.time()
    
    try:
        # 1. Запуск сбора данных 1h (включает проверку алертов)
        log.info(
            f"--- 🔥 Запускаю сбор данных '{TEST_TF.upper()}' "
            f"(POST /internal/update-1h-and-check-alerts)..."
        )
        await helpers.post_task_1h(client, log, redis_conn)
        
        # 2. Проверка кэша 1h
        log.info(f"--- 🔎 Проверка кэша 'cache:{TEST_TF}'...")
        all_valid = await _check_single_1h_cache(client, log)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        if all_valid:
            log.info(
                f"--- ✅ [Сценарий 5] 1H Cache Check: УСПЕХ "
                f"(Заняло: {elapsed:.2f} сек) ---"
            )
        else:
            log.error(
                f"--- 💥 [Сценарий 5] 1H Cache Check: ПРОВАЛ "
                f"(Заняло: {elapsed:.2f} сек) ---"
            )
        
        return all_valid

    except Exception as e:
        log.error(
            f"💥 [FAIL] [Сценарий 5] Тест провален (Критическая ошибка): {e}",
            exc_info=True
        )
        end_time = time.time()
        elapsed = end_time - start_time
        log.error(
            f"--- 💥 [Сценарий 5] 1H Cache Check: ПРОВАЛ "
            f"(Время: {elapsed:.2f} сек) ---"
        )
        return False