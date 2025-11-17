import asyncio
import logging
import httpx # Явный импорт для type hinting и вызовов
import redis.asyncio as redis # Явный импорт для type hinting
import time # Явный импорт
from typing import List, Dict, Any

# Импортируем наши хелперы из того же пакета
from . import helpers

# Импорт моделей
try:
    import config
except ImportError:
    import sys
    sys.exit(1)


async def run_e2e_flow(
    client: httpx.AsyncClient, 
    redis_conn: redis.Redis, 
    log: logging.Logger
) -> bool:
    """
    Сценарий 1: Выполняет полный цикл "Сбор Base" -> "Генерация Target" (синхронно).
    """
    start_time = time.time()
    all_passed = True

    try:
        # ИСПОЛЬЗУЕМ helpers._get_active_timeframes()
        base_tf, target_tf = helpers._get_active_timeframes()
    except Exception as e:
        log.error(f"Критическая ошибка при чтении ACTIVE_TIMEFRAME_PAIR: {e}", exc_info=True)
        return False

    log.info(f"--- 🔬 [Сценарий 1] E2E Flow: Начинаю ({base_tf} -> {target_tf}) ---")

    # --- ЭТАП 1: Сбор BASE-TF ---
    log.info(f"--- 🔥 Запускаю задачу '{base_tf.upper()}' (POST /internal/update-base-data)...")
    try:
        await helpers.post_task(client, log, "base") 
        log.info(f"✅ [Сценарий 1] ЭТАП 1 (Сбор {base_tf.upper()}) УСПЕШНО ЗАВЕРШЕН.")
    except httpx.HTTPStatusError as e:
        log.error(f"💥 [FAIL] ЭТАП 1 (Сбор {base_tf.upper()}) провален.")
        log.error(f"Тело ответа: {e.response.text}")
        all_passed = False

    # --- ЭТАП 2: Генерация TARGET-TF ---
    if all_passed:
        log.info(f"--- 🔥 Запускаю задачу '{target_tf.upper()}' (POST /internal/generate-target)...")
        try:
            # Генерация Target-TF
            await helpers.post_task(client, log, "target")
            log.info(f"✅ [Сценарий 1] ЭТАП 2 (Генерация {target_tf.upper()}) УСПЕШНО ЗАВЕРШЕН.")
        except httpx.HTTPStatusError as e:
            log.error(f"💥 [FAIL] ЭТАП 2 (Генерация {target_tf.upper()}) провален.")
            log.error(f"Тело ответа: {e.response.text}")
            all_passed = False

    duration = time.time() - start_time
    log.info(f"--- {'✅' if all_passed else '💥'} [Сценарий 1] E2E Flow: {'УСПЕХ' if all_passed else 'ПРОВАЛ'} (Время: {duration:.2f} сек) ---")

    return all_passed