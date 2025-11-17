# tests_e2e.py

import asyncio
import httpx # <-- ВОССТАНОВЛЕНО
import sys
import os
import time
from pathlib import Path 
import redis.asyncio as redis # <-- ВОССТАНОВЛЕНО

# --- ФИНАЛЬНАЯ КОРРЕКЦИЯ ПУТИ ---
# ИСПРАВЛЕНИЕ: Убран лишний os.path.dirname(). Теперь путь указывает на корень проекта.
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
# -------------------------------

# --- 1. Импорт наших тестовых модулей ---
try:
    from tests_e2e import helpers
    
    from tests_e2e.test_3_deep_integration import run_deep_integration_check
    from tests_e2e import test_main_orchestrator 
    
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модули из 'tests_e2e/'.", file=sys.stderr)
    print(f"Ошибка: {e}", file=sys.stderr)
    print("Убедитесь, что папка 'tests_e2e' существует и содержит '__init__.py'", file=sys.stderr)
    sys.exit(1)

# --- 2. Импорт хелпера Redis из основного кода ---
try:
    from cache_manager import get_redis_connection
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать 'get_redis_connection' из 'cache_manager'.", file=sys.stderr)
    sys.exit(1)


async def main():
    """
    Главный оркестратор E2E тестов.
    """
    log = helpers.setup_colored_logger()
    log.info("=" * 60)
    log.info(f"--- 🚀 НАЧИНАЮ E2E ТЕСТ ---")
    log.info(f"Цель: {helpers.BASE_URL}")
    log.info("=" * 60)
    
    total_start_time = time.time()
    redis_conn: redis.Redis = None
    http_client: httpx.AsyncClient = None
    all_passed = True
    
    try:
        # --- 1. Подключение к Redis ---
        log.info("Подключение к Redis...")
        redis_conn = await get_redis_connection()
        if not redis_conn:
             log.critical("💥 [FAIL] Не удалось подключиться к Redis. Тестирование отменено.")
             return False
        log.info("✅ [OK] Redis подключен.")

        # --- 2. Очистка перед тестом ---
        await helpers.cleanup_redis_keys(redis_conn, log)

        # --- 3. Запуск тестов через HTTPX ---
        async with httpx.AsyncClient(base_url=helpers.BASE_URL, timeout=300.0) as client:
            http_client = client
            
            # --- Проверка /health ---
            try:
                resp = await client.get("/health")
                resp.raise_for_status()
                log.info("✅ [OK] Сервер доступен (/health).")
            except Exception as e:
                log.critical(f"💥 [FAIL] Сервер НЕ ДОСТУПЕН по адресу {helpers.BASE_URL}/health.\n{e}")
                log.critical("Убедитесь, что сервер FastAPI запущен.")
                return False

            # --- Сценарий 3: Deep Integration Check (Проверка сырых данных) ---
            try:
                if not await run_deep_integration_check(client, log):
                    all_passed = False
            except Exception as e:
                log.error(f"💥 [FAIL] [Сценарий 3] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
                all_passed = False

            # --- Сценарий A/B: Запуск Активного Сценария ---
            if all_passed:
                all_passed = await test_main_orchestrator.run_active_scenario(client, redis_conn, log)
            else:
                log.warning("⚠️  Пропущено тестирование сценария из-за провала Сценария 3.")

    except Exception as e:
        log.critical(f"💥 [FAIL] Непредвиденная ошибка в главном runner: {e}", exc_info=True)
        all_passed = False
        
    finally:
        if redis_conn:
            await redis_conn.aclose()
            log.info("... Соединение с Redis закрыто.")
        
        total_end_time = time.time()
        total_duration = total_end_time - total_start_time
        
        log.info("=" * 60)
        if all_passed:
            log.info(f"--- 🏆🏆🏆 E2E ТЕСТ УСПЕШНО ЗАВЕРШЕН!")
        else:
            log.error(f"--- 💥 E2E ТЕСТ ПРОВАЛЕН. ---")
            
        log.info(f"--- ⏱️  Общее время выполнения: {total_duration:.2f} сек. ---")
        log.info("=" * 60)
        
        return all_passed


if __name__ == "__main__":
    try:
        os.makedirs("tests_e2e", exist_ok=True)
        Path("tests_e2e/__init__.py").touch()
        
        # Убедитесь, что созданы все необходимые файлы
        Path("tests_e2e/test_main_orchestrator.py").touch() 
        Path("tests_e2e/test_1_e2e_flow.py").touch()
        
        if not asyncio.run(main()):
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n❌ E2E Тест прерван пользователем (Ctrl+C).")
        sys.exit(2)
    except Exception as e:
        print(f"\n\n💥 КРИТИЧЕСКАЯ ОШИБКА ЗАПУСКА: {e}")
        sys.exit(1)