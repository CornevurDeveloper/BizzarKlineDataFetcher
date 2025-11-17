# tests_e2e/test_main_orchestrator.py
# tests_e2e/test_main_orchestrator.py

import logging
import httpx 
import time 
import asyncio
import sys
import os
import redis.asyncio as redis 
from typing import Literal, Optional

# Импорт хелперов
from . import helpers

# Импорт сценариев
from tests_e2e.test_1_e2e_flow import run_e2e_flow
from tests_e2e.test_2_cache_freshness import run_cache_freshness_check
from tests_e2e.test_4_cache_consistency import run_cache_consistency_check
# --- НОВЫЙ ИМПОРТ (ИЗМЕНЕНИЕ №3) ---
from tests_e2e.test_5_1h_cache_check import run_1h_cache_check
# ------------------------------------

# Импорт config
try:
    import config 
except ImportError as e:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать 'config': {e}")
    sys.exit(1)


async def _run_full_test_scenario(
    client: httpx.AsyncClient, 
    redis_conn: redis.Redis, 
    log: logging.Logger, 
    config_pair: str 
) -> bool:
    """Запускает полный E2E-тест для заданной пары TF."""
    
    start_time = time.time()
    
    # --- 
# 0. Настройка конфигурации ---
    log.info(f"\n{'='*60}\n--- ⚙️ СЦЕНАРИЙ TF: Настройка {config_pair} ---")
    
    # Установка текущей пары в конфиге для корректного чтения сервером
    config.ACTIVE_TIMEFRAME_PAIR = config_pair 
    
    # Очистка кэша перед началом
    await helpers.cleanup_redis_keys(redis_conn, log)
    
    # ИСПОЛЬЗУЕМ helpers._get_active_timeframes()
    base_tf, target_tf = helpers._get_active_timeframes()
    
    scenario_passed = True
    
    # 1. E2E Flow (Сбор Base-TF и Генерация Target-TF)
  
#   log.info(f"--- 🔬 [Сценарий 1] E2E Flow: Начинаю ({base_tf} -> {target_tf}) ---")
    try:
        if not await run_e2e_flow(client, redis_conn, log):
            scenario_passed = False
    except Exception as e:
        log.error(f"💥 [СЦЕНАРИЙ {config_pair}] ЭТАП 1 (E2E Flow) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
        scenario_passed = False
    
    # 2. Cache Freshness & Integrity Check
    if scenario_passed:
   
#      log.info(f"--- 🔬 [Сценарий 2] Cache Freshness: Начинаю ({base_tf} -> {target_tf}) ---")
        try:
            if not await run_cache_freshness_check(client, redis_conn, log):
                scenario_passed = False
        except Exception as e:
            log.error(f"💥 [СЦЕНАРИЙ {config_pair}] ЭТАП 2 (Freshness) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
          
#   scenario_passed = False

    # --- НОВЫЙ ЭТАП 3: Проверка Консистентности Кэша (vs.
# Биржа) ---
    if scenario_passed:
        log.info(f"--- 🔬 [Сценарий 3] Cache Consistency: Начинаю ({base_tf} vs. Биржа) ---")
        try:
            if not await run_cache_consistency_check(client, log):
                scenario_passed = False
        except Exception as e:
            log.error(f"💥 [СЦЕНАРИЙ {config_pair}] ЭТАП 3 (Consistency) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
  
#           scenario_passed = False
    # -------------------------------------------------------------
    
    duration = time.time() - start_time
    log.info(f"--- ✅/💥 СЦЕНАРИЙ {config_pair} ЗАВЕРШЕН. УСПЕХ: {scenario_passed} (Время: {duration:.2f} сек) ---")
    
    return scenario_passed


async def run_active_scenario(client: httpx.AsyncClient, redis_conn: redis.Redis, log: logging.Logger) -> bool:
    """Запускает только один сценарий, определенный в config.ACTIVE_TIMEFRAME_PAIR, 
    плюс проверку 1h."""
    
    # Сохраняем исходное значение для восстановления
    original_config_pair = config.ACTIVE_TIMEFRAME_PAIR
    current_pair = original_config_pair # Берем текущую 
# пару из config.py
    
    log.info("\n" * 2 + "=" * 60 + "\n--- ЗАПУСК: АКТИВНЫЙ СЦЕНАРИЙ ИЗ КОНФИГА ({}) ---\n".format(current_pair) + "=" * 60)
    
    # Вызываем основной сценарий с текущей парой
    scenario_passed = await _run_full_test_scenario(client, redis_conn, log, current_pair)
    
    # --- НОВЫЙ ЭТАП: Проверка 1H Cache (ИЗМЕНЕНИЕ №3) ---
    final_pass = scenario_passed
    log.info("\n" * 2 + "=" * 60 + "\n--- ЗАПУСК: СЦЕНАРИЙ 5 (ПРОВЕРКА 1H КЭША) ---\n" + "=" * 60)
    
    try:
        if not await run_1h_cache_check(client, redis_conn, log):
            final_pass = False
    except Exception as e:
        log.error(f"💥 [СЦЕНАРИЙ 5] (1H Check) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
        final_pass = False
    # -----------------------------------------------------------------
    
    # Восстановление исходного конфига
    config.ACTIVE_TIMEFRAME_PAIR = original_config_pair
    
    return final_pass