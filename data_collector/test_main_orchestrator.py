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
from . import helpers # Оставляем относительный, т.к. helpers.py в той же папке

# Импорт сценариев (ИЗМЕНЕНИЕ №48: Смена на абсолютный импорт)
from tests_e2e.test_1_e2e_flow import run_e2e_flow
from tests_e2e.test_2_cache_freshness import run_cache_freshness_check

# Импорт config
try:
    # Должен быть в sys.path благодаря tests_e2e.py и helpers.py
    import config 
except ImportError as e:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать 'config': {e}")
    sys.exit(1)


async def _run_full_test_scenario(
    client: httpx.AsyncClient, 
    redis_conn: redis.Redis, 
    log: logging.Logger, 
    config_pair: Literal["4H_8H", "12H_1D"]
) -> bool:
    """Запускает полный E2E-тест для заданной пары TF."""
    
    # --- 0. Настройка конфигурации ---
    log.info(f"\n{'='*60}\n--- ⚙️ СЦЕНАРИЙ TF: Настройка {config_pair} ---")
    config.ACTIVE_TIMEFRAME_PAIR = config_pair
    # Очистка кэша перед сменой TF (чтобы не путать 4h и 12h данные)
    await helpers.cleanup_redis_keys(redis_conn, log)
    
    base_tf, target_tf = helpers._get_active_timeframes()
    
    scenario_passed = True
    
    # 1. E2E Flow (Сбор Base-TF и Генерация Target-TF)
    log.info(f"--- 🔬 [Сценарий 1] E2E Flow: Начинаю ({base_tf} -> {target_tf}) ---")
    try:
        # NOTE: run_e2e_flow теперь использует TF из config
        if not await run_e2e_flow(client, redis_conn, log):
            scenario_passed = False
    except Exception as e:
        log.error(f"💥 [СЦЕНАРИЙ {config_pair}] ЭТАП 1 (E2E Flow) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
        scenario_passed = False
    
    # 2. Cache Freshness & Integrity Check
    if scenario_passed:
        log.info(f"--- 🔬 [Сценарий 2] Cache Freshness: Начинаю ({base_tf} -> {target_tf}) ---")
        try:
            if not await run_cache_freshness_check(client, redis_conn, log):
                scenario_passed = False
        except Exception as e:
            log.error(f"💥 [СЦЕНАРИЙ {config_pair}] ЭТАП 2 (Freshness) КРИТИЧЕСКИЙ ПРОВАЛ: {e}", exc_info=True)
            scenario_passed = False

    log.info(f"--- ✅/💥 СЦЕНАРИЙ {config_pair} ЗАВЕРШЕН. УСПЕХ: {scenario_passed} ---")
    return scenario_passed


async def run_all_scenarios(client: httpx.AsyncClient, redis_conn: redis.Redis, log: logging.Logger) -> bool:
    """Запускает оба сценария: 4H_8H и 12H_1D."""
    
    # Сохраняем исходное значение, чтобы восстановить его после тестов
    original_config_pair = config.ACTIVE_TIMEFRAME_PAIR
    
    # Сценарий A: Проверка 4H -> 8H (FR/OI должны быть в свечах)
    log.info("\n" * 2 + "=" * 60 + "\n--- ЗАПУСК: СЦЕНАРИЙ A (4H -> 8H) ---\n" + "=" * 60)
    scenario_a_passed = await _run_full_test_scenario(client, redis_conn, log, "4H_8H")
    
    # Сценарий B: Проверка 12H -> 1D (Только OI должен быть в свечах)
    log.info("\n" * 2 + "=" * 60 + "\n--- ЗАПУСК: СЦЕНАРИЙ B (12H -> 1D) ---\n" + "=" * 60)
    scenario_b_passed = await _run_full_test_scenario(client, redis_conn, log, "12H_1D")
    
    # Восстановление исходного конфига
    config.ACTIVE_TIMEFRAME_PAIR = original_config_pair
    
    return scenario_a_passed and scenario_b_passed