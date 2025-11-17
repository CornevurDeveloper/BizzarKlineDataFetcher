# tests_e2e/helpers.py
import logging
import sys
import os
import time
import asyncio
import httpx
from dotenv import load_dotenv
from typing import Literal
import redis.asyncio as redis

# --- 1. Импорт из рабочей кодовой базы ---
try:
    from cache_manager import get_redis_connection
    from config import (
        WORKER_LOCK_KEY,
        SECRET_TOKEN,
        KLINES_LIMIT_4H, # Импортируем для валидации
        # --- НОВЫЙ ИМПОРТ ---
        ACTIVE_TIMEFRAME_PAIR
    )
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать 'cache_manager' или 'config'.", file=sys.stderr)
    print("Убедитесь, что вы запускаете test_e2e.py из корневой папки проекта.", file=sys.stderr)
    sys.exit(1)

# --- 2. Загрузка .env (на всякий случай, если он не загружен) ---
load_dotenv()
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")

# --- 3. Настройки Теста ---
POLL_INTERVAL_SEC = 15  # Пауза опроса воркера
MAX_WAIT_MINUTES_PER_TASK = 15 # Макс. время ожидания 1 задачи
GRACE_PERIOD_MS = 15 * 60 * 1000 # 15 минут для "свежести"

# --- 4. Настройка Цветного Логгера ---
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
CYAN = "\033[96m"

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        color = ""
        if record.levelno == logging.INFO:
            color = GREEN
        elif record.levelno == logging.WARNING:
            color = YELLOW
        elif record.levelno == logging.ERROR or record.levelno == logging.CRITICAL:
            color = RED
        
        timestamp = f"{CYAN}[{time.strftime('%H:%M:%S')}] (E2E) - {color}"
        message = super().format(record)
        return f"{timestamp}{message}{RESET}"

def setup_colored_logger() -> logging.Logger:
    log = logging.getLogger("E2E_TESTER")
    log.setLevel(logging.INFO)
    
    if log.hasHandlers():
        log.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = ColoredFormatter('%(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    return log

# --- 5. Хелперы Redis ---

async def cleanup_redis_keys(redis_conn: redis.Redis, log: logging.Logger):
    """
    Очищает КЛЮЧИ ЭТОГО ПРОЕКТА (4h/8h/12h/1d) перед запуском.
    """
    log.info(f"--- 🧹 Очистка Redis ---\r\nБлокировка: {WORKER_LOCK_KEY}")
    
    try:
        keys_to_delete = [
            "cache:4h",
            "cache:8h",
            "cache:12h", # --- ДОБАВЛЕНО ---
            "cache:1d"   # --- ДОБАВЛЕНО ---
        ]
        # Используем общие ключи для удаления, т.к. изолированные ключи не нужны для удаления
        keys_to_delete_full = [key.decode('utf-8') for key in await redis_conn.keys("*lock*")] 
        keys_to_delete_full += [key.decode('utf-8') for key in await redis_conn.keys("*queue*")]
        keys_to_delete_full += keys_to_delete
        
        deleted_count = await redis_conn.delete(*keys_to_delete_full)
        
        log.info(f"Удалено {deleted_count} старых ключей.")
        
    except Exception as e:
        log.error(f"Критическая ошибка при очистке Redis: {e}", exc_info=True)
        raise

# --- 6. Хелперы HTTP ---
# --- НОВЫЙ ХЕЛПЕР ДЛЯ ПАРСИНГА КОНФИГА ---
def _get_active_timeframes() -> tuple[str, str]:
    """
    Парсит ACTIVE_TIMEFRAME_PAIR из конфига.
    """
    try:
        base_tf, target_tf = ACTIVE_TIMEFRAME_PAIR.split('_')
        return base_tf.lower(), target_tf.lower()
    except ValueError:
        logging.critical(f"Неверный формат ACTIVE_TIMEFRAME_PAIR: {ACTIVE_TIMEFRAME_PAIR}. Ожидается 'BASE_TARGET'.")
        # В тестах мы не можем вызвать HTTPException, поэтому просто падаем
        sys.exit(1)


async def post_task(client: httpx.AsyncClient, log: logging.Logger, task_type: Literal["base", "target", "12h", "1d"]):
    """
    Отправляет HTTP-запрос для запуска задачи в API и ожидает 200 OK (синхронное исполнение).
    """
    if not SECRET_TOKEN: 
        log.error("💥 SECRET_TOKEN не найден в .env. Не могу запустить задачу.")
        raise ValueError("SECRET_TOKEN not set")
    
    headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
    
    # --- ЛОГИКА ОПРЕДЕЛЕНИЯ ЭНДПОИНТА И ИМЕНИ ЗАДАЧИ ---
    if task_type == "base":
        timeframe, _ = _get_active_timeframes()
        url = "/internal/update-base-data"
    elif task_type == "target":
        _, timeframe = _get_active_timeframes()
        url = "/internal/generate-target"
    # --- ДОБАВЛЕНА ПОДДЕРЖКА ДЛЯ СЛУЧАЙНОГО ЗАПУСКА ВСЕХ СТАБИЛЬНЫХ TF ---
    elif task_type in ["4h", "12h", "1d"]:
        timeframe = task_type
        url = f"/internal/update-{task_type}" # Это не используется, но оставлю как заглушку
        log.warning(f"⚠️ [WARN] Вызов {task_type} не предусмотрен в динамической модели. Используйте 'base' или 'target'.")
        sys.exit(1) # Принудительно падаем, чтобы пользователь использовал base/target
    else:
        raise ValueError(f"Неизвестный тип задачи: {task_type}")
    # ----------------------------------------------------

    log.info(f"--- 🔥 Запускаю задачу '{timeframe.upper()}' (POST {url})...")
    
    response = await client.post(url, headers=headers, timeout=MAX_WAIT_MINUTES_PER_TASK * 60 + 10)

    if response.status_code == 200:
        log.info(f"✅ [OK] Задача '{timeframe.upper()}' успешно выполнена (200 OK).")
        return True
    elif response.status_code == 409:
        log.error(f"💥 [FAIL] Блокировка занята (409 Conflict).")
        raise httpx.HTTPStatusError("Lock occupied", request=response.request, response=response)
    else:
        log.error(f"💥 [FAIL] Не удалось запустить задачу '{timeframe.upper()}'. Статус: {response.status_code}")
        log.error(f"Тело ответа: {response.text}")
        response.raise_for_status()