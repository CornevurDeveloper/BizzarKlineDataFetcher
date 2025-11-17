#!/usr/bin/env python
# test_alerts.py (НАХОДИТСЯ В КОРНЕ ПРОЕКТА)
import asyncio
import httpx
import sys
import os

# --- Импортируем хелперы и модули ---
try:
    from alert_tests import helpers
    from alert_tests.test_1_e2e_lifecycle import run_test_1_lifecycle
    from alert_tests.test_2_api_management import run_test_2_management
    from alert_tests.test_3_api_cleanup import run_test_3_cleanup
    from alert_tests.test_4_api_uniqueness import run_test_4_uniqueness
    # --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ (E2E 1h) ---
    from alert_tests.test_5_e2e_1h_alerts import run_1h_alert_scenario
    # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---
    from cache_manager import get_redis_connection
except ImportError as e:
    print(f"Ошибка: Не удалось импортировать модули: {e}", file=sys.stderr)
    print("PYTHONPATH:", sys.path, file=sys.stderr)
    print("Убедитесь, что папка 'alert_tests' существует и содержит '__init__.py'", file=sys.stderr)
    sys.exit(1)

async def main():
    """
    Главный оркестратор E2E тестов для Alert Manager.
    """
    log = helpers.setup_logger("E2E_ALERT_RUNNER")
    log.info("="*60)
    log.info("--- 🚀 НАЧИНАЮ E2E ТЕСТ ALERT MANAGER ---")
    log.info(f"Цель: {helpers.BASE_URL}")
    log.info("="*60)
    
    redis_conn = None
    all_passed = True
    
    try:
        # --- 1. Подключение к Redis ---
        log.info("Подключение к Redis...")
        redis_conn = await get_redis_connection()
        if not redis_conn:
            log.critical("💥 [FAIL] Не удалось подключиться к Redis. Тестирование отменено.")
            return

        # --- 2. Очистка перед тестом ---
        await helpers.cleanup_alert_keys(redis_conn, log)

        # --- 3. Запуск тестов через HTTPX Client ---
        async with httpx.AsyncClient(base_url=helpers.BASE_URL, timeout=120.0) as client:
            
            # --- Тест 1: E2E LifeCycle ---
            try:
                if not await run_test_1_lifecycle(client, redis_conn, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 1] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False

            # --- Тест 2: API Management ---
            # (Очищаем ключи снова для чистого теста №2)
            await helpers.cleanup_alert_keys(redis_conn, log)
            try:
                if not await run_test_2_management(client, redis_conn, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 2] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False

            # --- Тест 3: API Cleanup ---
            # (Очищаем ключи снова для чистого теста №3)
            await helpers.cleanup_alert_keys(redis_conn, log)
            try:
                if not await run_test_3_cleanup(client, redis_conn, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 3] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False
            
            # --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ (E2E 1h) ---
            # --- Тест 4: API Uniqueness ---
            # (Очищаем ключи снова для чистого теста №4)
            await helpers.cleanup_alert_keys(redis_conn, log)
            try:
                if not await run_test_4_uniqueness(client, redis_conn, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 4] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False
            
            # --- Тест 5: E2E 1h Alert Flow (Наш новый) ---
            # (Очищаем ключи снова для чистого теста №5)
            await helpers.cleanup_alert_keys(redis_conn, log)
            try:
                if not await run_1h_alert_scenario(client, redis_conn, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 5] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False
            # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---
                
    except Exception as e:
        log.critical(f"💥 [FAIL] Непредвиденная ошибка в главном runner: {e}", exc_info=True)
        all_passed = False
        
    finally:
        if redis_conn:
            # --- (Исправление DeprecationWarning - без изменений) ---
            await redis_conn.aclose()
        log.info("="*60)
        if all_passed:
            log.info("--- 🏆🏆🏆 E2E ТЕСТ ALERT MANAGER УСПЕШНО ЗАВЕРШЕН! ---")
        else:
            log.error("--- 💥 E2E ТЕСТ ALERT MANAGER ПРОВАЛЕН. ---")
            sys.exit(1) # Выход с ошибкой


if __name__ == "__main__":
    asyncio.run(main())