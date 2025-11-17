# alert_tests/test_2_api_management.py
import httpx
import uuid
import logging
import json # 🚀 Добавлен json для дампа тела DELETE
from redis.asyncio import Redis as AsyncRedis
from . import helpers

async def run_test_2_management(client: httpx.AsyncClient, redis_conn: AsyncRedis, log: logging.Logger):
    """
    Сценарий 2: API Management (Add Many -> Move Many -> Delete Many)
    """
    log.info("--- 🔬 [Сценарий 2] API Management: Начинаю ---")
    
    # --- 🚀 ИЗМЕНЕНИЕ: Используем 'BTCUSDT' ---
    # Мы знаем из Сценария 1, что 'BTCUSDT' проходит фильтр 'add/one'.
    # 'SOLUSDT' (в предыдущей версии) был отфильтрован 'add/many', что вызвало ошибку 0 алертов.
    alerts_to_add = [
        {"symbol": "BTCUSDT", "price": 100, "alertName": "Mgmt Test 1 (BTC)", "action": "cross"},
        {"symbol": "BTCUSDT", "price": 200, "alertName": "Mgmt Test 2 (BTC)", "action": "cross"},
        {"symbol": "BTCUSDT", "price": 300, "alertName": "Mgmt Test 3 (BTC)", "action": "cross"}
    ]
    # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

    try:
        # --- Шаг 1: Add Many ---
        log.info("[Тест 2] Шаг 1: Добавление 3 алертов через /alerts/add/many...")
        response = await client.post(
            "/alerts/add/many",
            params={"collectionName": "working"},
            json={"alerts": alerts_to_add} 
        )
        
        # Если монеты BTC (по какой-то причине) нет, здесь теперь упадет ошибка 400
        response.raise_for_status()
        
        # Проверка
        working_count = await redis_conn.scard("index:line:working")
        if working_count != 3:
            raise AssertionError(f"Ожидалось 3 алерта в 'working', найдено {working_count}")
        log.info("       ✅ [OK] 3 алерта успешно добавлены в 'working'.")

        # --- Шаг 2: Move Many ---
        log.info(f"[Тест 2] Шаг 2: Чтение 'working' для получения сгенерированных ID...")
        working_alert_ids_bytes = await redis_conn.smembers("index:line:working")
        working_alert_ids = [id_b.decode('utf-8') for id_b in working_alert_ids_bytes]
        
        if len(working_alert_ids) != 3:
             raise AssertionError(f"Ошибка чтения ID из Redis: ожидалось 3, найдено {len(working_alert_ids)}")

        working_alerts_json = await redis_conn.json().mget(
            [f"alert:line:{id_str}" for id_str in working_alert_ids], 
            "$"
        )
        working_alerts = [res[0] for res in working_alerts_json if res]
        
        ids_to_move = [a['id'] for a in working_alerts[:2]] # Берем первые два
        
        log.info(f"[Тест 2] Шаг 2: Перемещение 2 алертов ({ids_to_move}) в 'archived'...")
        response = await client.post(
            "/alerts/move/many", 
            params={"sourceCollection": "working", "targetCollection": "archived"},
            json={"ids": ids_to_move}
        )
        response.raise_for_status()
        
        # (Проверки 'Move' без изменений)
        working_count = await redis_conn.scard("index:line:working")
        archived_count = await redis_conn.scard("index:line:archived")
        
        if working_count != 1:
            raise AssertionError(f"Ожидался 1 алерт в 'working' после перемещения, найдено {working_count}")
        if archived_count != 2:
            raise AssertionError(f"Ожидалось 2 алерта в 'archived' после перемещения, найдено {archived_count}")
        
        log.info("       ✅ [OK] 2 алерта перемещены в 'archived', 1 остался в 'working'.")

        # --- Шаг 3: Delete Many ---
        ids_to_delete = ids_to_move # Те же 2 ID
        log.info(f"[Тест 2] Шаг 3: Удаление 2 алертов ({ids_to_delete}) из 'archived'...")
        
        # --- 🚀 ИСПРАВЛЕНИЕ (TypeError): httpx.delete не принимает 'json=' ---
        # Используем 'content=' и 'json.dumps'
        delete_payload = json.dumps({"ids": ids_to_delete})
        response = await client.request(
            "DELETE", # Явный метод
            "/alerts/delete/many", 
            params={"collectionName": "archived"},
            content=delete_payload,
            headers={"Content-Type": "application/json"} # 🚀
        )
        # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---
        
        response.raise_for_status()
        
        # (Проверки 'Delete' без изменений)
        archived_count = await redis_conn.scard("index:line:archived")
        if archived_count != 0:
            raise AssertionError(f"Ожидалось 0 алертов в 'archived' после удаления, найдено {archived_count}")
        
        data_key_exists = await redis_conn.exists(f"alert:line:{ids_to_delete[0]}")
        if data_key_exists:
             raise AssertionError(f"JSON-данные {ids_to_delete[0]} не были удалены.")

        log.info("       ✅ [OK] 2 алерта успешно удалены из 'archived' (и их JSON-данные).")
        
        log.info("--- ✅ [Сценарий 2] API Management: УСПЕХ ---")
        return True

    except Exception as e:
        log.error(f"💥 [FAIL] [Сценарий 2] Тест провален: {e}", exc_info=True)
        return False