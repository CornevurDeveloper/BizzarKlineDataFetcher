# alert_tests/helpers.py
import logging
import sys
import os
import time
import asyncio
import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis as AsyncRedis

# --- 🚀 УДАЛЕНО: Хак sys.path (больше не нужен, т.к. runner в корне) ---

# --- 1. Импорт из cache_manager (для get_redis_connection) ---
# (Теперь будет работать, т.к. test_alerts.py запускается из корня)
try:
    from cache_manager import get_redis_connection
except ImportError as e:
    logging.critical(f"КРИТИЧЕСКИЙ СБОЙ ИМПОРТА 'cache_manager': {e}")
    sys.exit(1)

# --- 2. Загрузка конфигурации из config.py и .env ---
load_dotenv()

try:
    from config import (
        REDIS_TASK_QUEUE_KEY,
        WORKER_LOCK_KEY,
        WORKER_LOCK_TIMEOUT_SECONDS,
        WORKER_LOCK_VALUE,
        SECRET_TOKEN
    )
except ImportError as e:
    logging.critical(f"КРИТИЕСКИЙ СБОЙ ИМПОРТА 'config': {e}")
    # Фоллбэки (из config.py и worker.py)
    REDIS_TASK_QUEUE_KEY = "data_collector_task_queue"
    WORKER_LOCK_KEY = "data_collector_lock"
    WORKER_LOCK_TIMEOUT_SECONDS = 1800
    WORKER_LOCK_VALUE = "processing"
    SECRET_TOKEN = os.environ.get("SECRET_TOKEN")


# Загружаем URL из .env, как в test_redis_warmup.py
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000") 

# --- 3. Настройки Ожидания (из test_redis_warmup.py) ---
POLL_INTERVAL_SEC = 5
MAX_WAIT_MINUTES_PER_TASK = 15

# --- 4. Настройка Логгера ---
def setup_logger(name: str) -> logging.Logger:
    """
    (Код не изменен)
    """
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    
    # Предотвращаем двойное логгирование, если обработчик уже есть
    if log.hasHandlers():
        return log

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s - [%(levelname)s] - (%(name)s) - %(message)s',
        datefmt='%Y-%m-%d %H:M:%S'
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)
    return log

# --- 5. Хелперы Redis ---
async def cleanup_alert_keys(redis_conn: AsyncRedis, log: logging.Logger):
    """
    (Код не изменен)
    """
    log.info("--- 🧹 Очистка ключей Alert Manager (index:*, alert:*) ---")
    
    try:
        index_keys = await redis_conn.keys("index:*")
        data_keys = await redis_conn.keys("alert:*")
        
        keys_to_delete = index_keys + data_keys
        
        if not keys_to_delete:
            log.info("... Ключи Alert Manager уже очищены.")
            return

        # Декодируем для логгирования (опционально, но полезно)
        keys_str = [k.decode('utf-8') if isinstance(k, bytes) else k for k in keys_to_delete]
        log.info(f"... Найдено {len(keys_str)} ключей для удаления: {keys_str}")
        
        deleted_count = await redis_conn.delete(*keys_to_delete)
        log.info(f"--- ✅ [OK] Очищено {deleted_count} ключей. ---")

    except Exception as e:
        log.error(f"💥 [FAIL] Критическая ошибка при очистке Redis: {e}", exc_info=True)
        raise

# --- 6. Хелперы Воркера (Скопировано из test_redis_warmup.py) ---
async def wait_for_worker_to_be_free(redis_conn: AsyncRedis, log: logging.Logger, task_name: str):
    """
    (Код не изменен)
    """
    log.info(f"--- ⏳ Ожидаю завершения задачи '{task_name}' (опрос Redis {WORKER_LOCK_KEY} каждые {POLL_INTERVAL_SEC} сек)...")
    max_wait_time_sec = MAX_WAIT_MINUTES_PER_TASK * 60
    
    if not redis_conn:
        log.error("💥 [FAIL] Не удалось подключиться к Redis. Проверка блокировки невозможна.")
        raise ConnectionError("Redis недоступен в wait_for_worker_to_be_free")
        
    # --- Фаза 1: Ждем, пока НАШ воркер (processing) ЗАХВАТИТ задачу ---
    log.info(f"... Фаза 1: Ожидаю, пока '{WORKER_LOCK_VALUE}' не появится в {WORKER_LOCK_KEY} (Макс {max_wait_time_sec} сек)...")
    phase1_start_time = time.time()
    task_taken = False
    
    while time.time() - phase1_start_time < max_wait_time_sec:
        try:
            lock_status_bytes = await redis_conn.get(WORKER_LOCK_KEY)
            lock_status = lock_status_bytes.decode('utf-8') if lock_status_bytes else None
            
            if lock_status == WORKER_LOCK_VALUE:
                log.info(f"✅ [Фаза 1] НАШ воркер захватил задачу (Lock='{lock_status}'). Перехожу к Фазе 2.")
                task_taken = True
                break
            elif lock_status is not None:
                log.warning(f"... [Фаза 1] 'Фантомный' воркер занят (Lock='{lock_status}'). Жду, пока он освободит...")
                await asyncio.sleep(POLL_INTERVAL_SEC)
            else:
                log.info(f"... [Фаза 1] Воркер свободен (Lock=None). Ожидаю захвата задачи '{task_name}'... Жду {POLL_INTERVAL_SEC} сек...")
                await asyncio.sleep(POLL_INTERVAL_SEC)

        except Exception as e:
            log.error(f"[Фаза 1] Ошибка при опросе Redis (lock): {e}", exc_info=False)
            await asyncio.sleep(POLL_INTERVAL_SEC)
            
    if not task_taken:
         raise TimeoutError(f"Таймаут Фазы 1! НАШ воркер (lock='{WORKER_LOCK_VALUE}') не захватил задачу '{task_name}' за {max_wait_time_sec} сек.")

    # --- Фаза 2: Ждем, пока НАШ воркер (processing) ОСВОБОДИТ задачу ---
    log.info(f"... Фаза 2: Ожидаю, пока '{WORKER_LOCK_VALUE}' не исчезнет (воркер завершит работу)...")
    phase2_start_time = time.time()
    
    while time.time() - phase2_start_time < max_wait_time_sec:
        try:
            lock_status_bytes = await redis_conn.get(WORKER_LOCK_KEY)
            lock_status = lock_status_bytes.decode('utf-8') if lock_status_bytes else None
            
            if lock_status == WORKER_LOCK_VALUE:
                log.info(f"... [Фаза 2] НАШ воркер все еще занят (Lock='{lock_status}'). Жду {POLL_INTERVAL_SEC} сек...")
                await asyncio.sleep(POLL_INTERVAL_SEC)
            else:
                log.info(f"✅ [Фаза 2] НАШ воркер освободился (Lock='{lock_status}'). Задача '{task_name}' выполнена.")
                return # УСПЕХ

        except Exception as e:
            log.error(f"[Фаза 2] Ошибка при опросе Redis (lock): {e}", exc_info=False)
            await asyncio.sleep(POLL_INTERVAL_SEC)

    raise TimeoutError(f"Таймаут Фазы 2! НАШ воркер (lock='{WORKER_LOCK_VALUE}') не освободил задачу '{task_name}' за {max_wait_time_sec} сек.")

async def post_task_1h(client: httpx.AsyncClient, log: logging.Logger, redis_conn: AsyncRedis):
    """
    (Код не изменен)
    """
    
    # Очищаем кэш '1h', чтобы API инициировал обновление
    cache_key_to_clear = "cache:1h"
    log.info(f"Очищаю '{cache_key_to_clear}', чтобы API инициировал обновление...")
    await redis_conn.delete(cache_key_to_clear)
        
    log.info("Запускаю задачу '1h' (POST /get-market-data)...")
    response = await client.post("/get-market-data", json={"timeframes": ["1h"]})

    if response.status_code == 202:
        log.info(f"✅ [OK] Задача '1h' принята в очередь.")
    elif response.status_code == 409:
        log.warning(f"Воркер уже был занят (409). Ожидаю его завершения...")
    else:
        log.error(f"💥 [FAIL] Не удалось поставить задачу '1h'. Статус: {response.status_code}, Тело: {response.text}")
        response.raise_for_status()