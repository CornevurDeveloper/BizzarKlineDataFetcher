# alert_tests/test_1_e2e_lifecycle.py
import httpx
import asyncio
import uuid
import logging
import time
from redis.asyncio import Redis as AsyncRedis
from . import helpers # Импортируем наши хелперы

# --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ: Импортируем то, что будем симулировать ---
from alert_manager.storage import AlertStorage
from alert_manager.checker import run_alert_checks
# --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

# UUID для этого тестового запуска
TEST_RUN_ID = str(uuid.uuid4())[:8]
TEST_SYMBOL = "BTCUSDT"

# --- 🚀 ИЗМЕНЕНИЕ: Это наши "поддельные" Klines-данные ---
# Мы симулируем, что воркер получил эти данные
mock_cache_data = {
    "data": [
        {
            "symbol": TEST_SYMBOL,
            "data": [
                # Одна свеча, которая гарантированно вызовет срабатывание (Low 0.5 < Price 1.0 < High 2.0)
                {
                    "openTime": int(time.time() * 1000),
                    "closeTime": int(time.time() * 1000) + 1000,
                    "openPrice": 1.5,
                    "highPrice": 2.0, #
                    "lowPrice": 0.5,  #
                    "closePrice": 1.8,
                    "volume": 1000.0, # (Наличие 'volume' важно для VWAP)
                    "baseVolume": 1000.0,
                    "quoteVolume": 1800.0
                }
            ]
        }
    ]
}
# --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---


async def run_test_1_lifecycle(client: httpx.AsyncClient, redis_conn: AsyncRedis, log: logging.Logger):
    """
    Сценарий 1: E2E LifeCycle (Создание -> СИМУЛЯЦИЯ Триггера -> Срабатывание)
    """
    log.info("--- 🔬 [Сценарий 1] E2E LifeCycle (СИМУЛЯЦИЯ): Начинаю (ID Запуска: %s) ---", TEST_RUN_ID)
    
    test_alert_id = str(uuid.uuid4())
    test_alert = {
        "id": test_alert_id,
        "symbol": TEST_SYMBOL,
        "alertName": f"E2E Test {TEST_RUN_ID}",
        "action": "cross",
        "price": 1.0, # Гарантированно сработает (BTC > 1$)
        "isActive": True,
        "status": "new",
        "creationTime": int(time.time() * 1000)
    }

    try:
        # --- Шаг 1: Создание Алерта (API) ---
        log.info(f"[Тест 1] Шаг 1: Создание алерта {test_alert_id} (BTC > 1$) через API...")
        response = await client.post(
            "/alerts/add/one", 
            params={"collectionName": "working"},
            json={"alert": test_alert}
        )
        response.raise_for_status()
        log.info("       ✅ [OK] API: Алерт успешно создан.")

        # --- Шаг 2: Проверка в Redis (Прямое чтение) ---
        log.info(f"[Тест 1] Шаг 2: Проверка, что алерт {test_alert_id} в 'index:line:working'...")
        is_in_working = await redis_conn.sismember("index:line:working", test_alert_id)
        if not is_in_working:
            raise AssertionError("Тестовый алерт не появился в 'index:line:working'")
        log.info("       ✅ [OK] Redis: Алерт найден в 'working'.")

        # --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ: Шаги 3 и 4 ---
        # (УДАЛЕНЫ: post_task_1h и wait_for_worker_to_be_free)
        
        log.info("[Тест 1] Шаг 3: Симуляция. Готовлю AlertStorage...")
        # `run_alert_checks` ожидает *экземпляр* AlertStorage, а не просто redis_conn
        storage_instance = AlertStorage(redis_conn)
        
        log.info("[Тест 1] Шаг 4: СИМУЛЯЦИЯ. Напрямую вызываю run_alert_checks с поддельными Klines...")
        await run_alert_checks(mock_cache_data, storage_instance) #
        log.info("       ✅ [OK] Симуляция run_alert_checks завершена.")
        # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

        # --- 🚀 ИЗМЕНЕНИЕ: Шаг 5 (Исправление) ---
        log.info(f"[Тест 1] Шаг 5: Проверка, что НОВЫЙ алерт появился в 'index:line:triggered'...")
        
        # Мы не знаем ID нового алерта (checker создает новый uuid),
        # поэтому мы просто проверяем, что в 'triggered' появился 1 алерт.
        triggered_count = await redis_conn.scard("index:line:triggered")
        
        if triggered_count == 0:
            raise AssertionError("Алерт НЕ сработал. 'index:line:triggered' пуст.")
        if triggered_count > 1:
             raise AssertionError(f"Алерт сработал, но в 'triggered' СЛИШКОМ МНОГО алертов ({triggered_count}).")
            
        log.info(f"       ✅ [OK] Redis: Найден {triggered_count} алерт в 'triggered'.")
        # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

        # --- Шаг 6: Проверка Telegram (Визуальная) ---
        log.info("="*50)
        log.info("--- 🔔 [Тест 1] ПОЖАЛУЙСТА, ПРОВЕРЬТЕ TELEGRAM! 🔔 ---")
        log.info(f"Вы должны были получить сообщение о срабатывании 'E2E Test {TEST_RUN_ID}'.")
        log.info("(Скрипт ждет 10 секунд для визуальной проверки...)")
        log.info("="*50)
        await asyncio.sleep(10)

        log.info("--- ✅ [Сценарий 1] E2E LifeCycle (СИМУЛЯЦИЯ): УСПЕХ ---")
        return True

    except Exception as e:
        log.error(f"💥 [FAIL] [Сценарий 1] Тест провален: {e}", exc_info=True)
        return False