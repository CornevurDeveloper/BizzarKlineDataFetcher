# alert_tests/test_4_api_uniqueness.py
import httpx
import uuid
import logging
import time
from redis.asyncio import Redis as AsyncRedis
from . import helpers

async def run_test_4_uniqueness(client: httpx.AsyncClient, redis_conn: AsyncRedis, log: logging.Logger):
    """
    Сценарий 4: Проверка API уникальности имени
    (/alerts/check-name и /vwap-alerts/check-name)
    """
    log.info("--- 🔬 [Сценарий 4] API Uniqueness: Начинаю ---")
    
    unique_line_name = f"UniqueLineName-{uuid.uuid4()}"
    duplicate_line_name = f"DuplicateLineName-{uuid.uuid4()}"
    
    unique_vwap_name = f"UniqueVwapName-{uuid.uuid4()}"
    duplicate_vwap_name = f"DuplicateVwapName-{uuid.uuid4()}"

    try:
        # === ЧАСТЬ 1: LINE ALERTS ===
        log.info(f"[Тест 4.1] Шаг 1 (Line): Проверка '{unique_line_name}' (ожидаем True)...")
        response = await client.get(
            "/alerts/check-name",
            params={"name": unique_line_name}
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("isUnique"): # Ожидаем True
            raise AssertionError(f"Ожидалось isUnique=True, получено {data.get('isUnique')}")
        log.info("       ✅ [OK] Line: Имя корректно определено как уникальное.")

        # --- Создание Line алерта ---
        log.info(f"[Тест 4.1] Шаг 2 (Line): Создание алерта с именем '{duplicate_line_name}'...")
        line_alert = {
            "id": str(uuid.uuid4()),
            "symbol": "BTCUSDT",
            "alertName": duplicate_line_name,
            "action": "cross", "price": 1.0, "isActive": True, "status": "new"
        }
        response = await client.post(
            "/alerts/add/one", 
            params={"collectionName": "working"},
            json={"alert": line_alert}
        )
        response.raise_for_status()
        log.info("       ✅ [OK] Line: Алерт-дубликат создан.")

        # --- Проверка дубликата Line ---
        log.info(f"[Тест 4.1] Шаг 3 (Line): Повторная проверка '{duplicate_line_name}' (ожидаем False)...")
        response = await client.get(
            "/alerts/check-name",
            params={"name": duplicate_line_name}
        )
        response.raise_for_status()
        data = response.json()
        if data.get("isUnique"): # Ожидаем False
            raise AssertionError(f"Ожидалось isUnique=False, получено {data.get('isUnique')}")
        log.info("       ✅ [OK] Line: Имя корректно определено как дубликат.")

        # === ЧАСТЬ 2: VWAP ALERTS ===
        log.info(f"[Тест 4.2] Шаг 1 (VWAP): Проверка '{unique_vwap_name}' (ожидаем True)...")
        response = await client.get(
            "/vwap-alerts/check-name",
            params={"name": unique_vwap_name}
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("isUnique"): # Ожидаем True
            raise AssertionError(f"Ожидалось isUnique=True, получено {data.get('isUnique')}")
        log.info("       ✅ [OK] VWAP: Имя корректно определено как уникальное.")
        
        # --- Создание VWAP алерта ---
        log.info(f"[Тест 4.2] Шаг 2 (VWAP): Создание алерта с именем '{duplicate_vwap_name}'...")
        vwap_alert = {
            "id": str(uuid.uuid4()),
            "symbol": "BTCUSDT",
            "alertName": duplicate_vwap_name, # <-- Новое поле
            "anchorTime": int(time.time() * 1000),
            "isActive": True
        }
        response = await client.post(
            "/vwap-alerts/add/one", 
            params={"collectionName": "working"},
            json={"alert": vwap_alert}
        )
        response.raise_for_status()
        log.info("       ✅ [OK] VWAP: Алерт-дубликат создан.")

        # --- Проверка дубликата VWAP ---
        log.info(f"[Тест 4.2] Шаг 3 (VWAP): Повторная проверка '{duplicate_vwap_name}' (ожидаем False)...")
        response = await client.get(
            "/vwap-alerts/check-name",
            params={"name": duplicate_vwap_name}
        )
        response.raise_for_status()
        data = response.json()
        if data.get("isUnique"): # Ожидаем False
            raise AssertionError(f"Ожидалось isUnique=False, получено {data.get('isUnique')}")
        log.info("       ✅ [OK] VWAP: Имя корректно определено как дубликат.")
        
        log.info("--- ✅ [Сценарий 4] API Uniqueness: УСПЕХ ---")
        return True

    except Exception as e:
        log.error(f"💥 [FAIL] [Сценарий 4] Тест провален: {e}", exc_info=True)
        return False