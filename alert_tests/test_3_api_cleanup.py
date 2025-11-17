# alert_tests/test_3_api_cleanup.py
import httpx
import uuid
import logging
import time
from datetime import datetime, timedelta
from redis.asyncio import Redis as AsyncRedis
from . import helpers

async def run_test_3_cleanup(client: httpx.AsyncClient, redis_conn: AsyncRedis, log: logging.Logger):
    """
    Сценарий 3: API Cleanup (/alerts/internal/cleanup-triggered)
    """
    log.info("--- 🔬 [Сценарий 3] API Cleanup: Начинаю ---")

    if not helpers.SECRET_TOKEN:
        log.error("💥 [FAIL] [Сценарий 3] SECRET_TOKEN не найден в .env или config.py. Тест пропускается.")
        return False

    # --- Шаг 1: Ручное создание "старого" алерта в Redis ---
    log.info("[Тест 3] Шаг 1: Ручное создание 'старого' алерта (3 дня) в 'triggered'...")
    
    old_alert_id = str(uuid.uuid4())
    cutoff_dt = datetime.now() - timedelta(days=3)
    old_activation_time = int(cutoff_dt.timestamp() * 1000)
    
    old_alert_data = {
        "id": old_alert_id,
        "symbol": "OLD",
        "activationTime": old_activation_time 
    }
    
    data_key = f"alert:line:{old_alert_id}"
    index_key = "index:line:triggered" 
    
    try:
        # Используем пайплайн для атомарности
        async with redis_conn.pipeline(transaction=True) as pipe:
            pipe.json().set(data_key, "$", old_alert_data)
            pipe.sadd(index_key, old_alert_id)
            await pipe.execute()
        
        log.info(f"       ✅ [OK] Фейковый 'старый' алерт {old_alert_id} создан.")
        
    except Exception as e:
        log.error(f"💥 [FAIL] Не удалось создать фейковый алерт в Redis: {e}", exc_info=True)
        return False

    # --- Шаг 2: Вызов эндпоинта очистки ---
    log.info("[Тест 3] Шаг 2: Вызов /alerts/internal/cleanup-triggered (hours=24)...")
    
    headers = {"Authorization": f"Bearer {helpers.SECRET_TOKEN}"}
    payload = {"hours": 24} 
    
    try:
        response = await client.post(
            "/alerts/internal/cleanup-triggered", 
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        
        response_data = response.json()
        log.info(f"       ✅ [OK] API ответил: {response_data.get('message')}")
        
        if response_data.get('deleted_line_count', 0) != 1:
            log.warning(f"       ⚠️  API отчитался об удалении {response_data.get('deleted_line_count')} алертов (ожидался 1).")

    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при вызове эндпоинта очистки: {e}", exc_info=True)
        return False

    # --- Шаг 3: Проверка в Redis ---
    log.info(f"[Тест 3] Шаг 3: Проверка, что 'старый' алерт {old_alert_id} удален из Redis...")
    
    data_exists = await redis_conn.exists(data_key)
    index_exists = await redis_conn.sismember(index_key, old_alert_id)
    
    if data_exists or index_exists:
        raise AssertionError(f"Алерт НЕ был удален! Data exists: {data_exists}, Index exists: {index_exists}")
    
    log.info("       ✅ [OK] 'Старый' алерт успешно удален (JSON и Индекс).")
    
    log.info("--- ✅ [Сценарий 3] API Cleanup: УСПЕХ ---")
    return True