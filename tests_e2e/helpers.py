import logging
import sys
import os
import time
from typing import Literal, Optional
from dotenv import load_dotenv
import httpx
import redis.asyncio as redis

# Импорт из рабочей кодовой базы
try:
    from cache_manager import get_redis_connection
    from config import (
        SECRET_TOKEN,
        KLINES_LIMIT_BASE_TF,
        ACTIVE_TIMEFRAME_PAIR,
        # --- ИСПРАВЛЕНИЕ (Шаг 3 из 3): Импортируем TIMEFRAMES_TO_TRIM ---
        TIMEFRAMES_TO_TRIM 
    )
except ImportError as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модули: {e}", file=sys.stderr)
    print("Убедитесь, что вы запускаете тесты из корневой папки проекта.", file=sys.stderr)
    sys.exit(1)

load_dotenv()

# Константы
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
POLL_INTERVAL_SEC = 15
MAX_WAIT_MINUTES_PER_TASK = 15
GRACE_PERIOD_MS = 15 * 60 * 1000

# ANSI цвета
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """Форматтер для цветного вывода логов в терминал."""
    
    LEVEL_COLORS = {
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED,
    }
    
    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        timestamp = f"{CYAN}[{time.strftime('%H:%M:%S')}] (E2E) - {color}"
        message = super().format(record)
        return f"{timestamp}{message}{RESET}"


def setup_colored_logger() -> logging.Logger:
    """Настраивает и возвращает цветной логгер для E2E тестов."""
    log = logging.getLogger("E2E_TESTER")
    log.setLevel(logging.INFO)
    
    if log.hasHandlers():
        log.handlers.clear()
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = ColoredFormatter('%(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)
    
    return log


# --- ИСПРАВЛЕНИЕ: Функция переименована обратно ---
def _get_active_timeframes() -> tuple[str, str]:
    """
    Парсит ACTIVE_TIMEFRAME_PAIR из конфига.
    
    Returns:
        Кортеж (base_timeframe, target_timeframe)
    
    Raises:
        ValueError: Если формат конфига неверный
    """
    try:
        base_tf, target_tf = ACTIVE_TIMEFRAME_PAIR.split('_')
        return base_tf.lower(), target_tf.lower()
    except ValueError as e:
        raise ValueError(
            f"Неверный формат ACTIVE_TIMEFRAME_PAIR: {ACTIVE_TIMEFRAME_PAIR}. "
            f"Ожидается 'BASE_TARGET' (например, '4h_1d')"
        ) from e
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---


# --- ИСПРАВЛЕНИЕ: Логика полностью переписана ---
async def cleanup_redis_keys(redis_conn: redis.Redis, log: logging.Logger) -> None:
    """
    Очищает ключи проекта (cache:*, *lock*, *queue*) перед запуском тестов.
    
    Args:
        redis_conn: Соединение с Redis
        log: Логгер для вывода информации
    """
    log.info("--- 🧹 Очистка Redis (поиск по маскам cache:*, *lock*, *queue*) ---")
    
    try:
        # 1. Собираем все ключи для удаления
        keys_to_delete = set()
        
        # 2. Ищем все ключи кэша (включая cache:cache:1h)
        cache_keys = await redis_conn.keys("cache:*")
        keys_to_delete.update(cache_keys)
        
        # 3. Ищем все ключи блокировок
        lock_keys = await redis_conn.keys("*lock*")
        keys_to_delete.update(lock_keys)
        
        # 4. Ищем все ключи очередей
        queue_keys = await redis_conn.keys("*queue*")
        keys_to_delete.update(queue_keys)
        
        # 5. Выводим отчет и удаляем
        if keys_to_delete:
            # Конвертируем байты в строки для красивого лога
            keys_str_list = [k.decode('utf-8') for k in keys_to_delete]
            
            log.info(f"Найдено {len(keys_str_list)} ключей для удаления.")
            
            # Выводим до 10 ключей для примера
            if len(keys_str_list) > 10:
                log.info(f"  -> (Пример): {keys_str_list[:10]}...")
            else:
                log.info(f"  -> Ключи: {keys_str_list}")

            deleted_count = await redis_conn.delete(*keys_to_delete)
            log.info(f"Удалено {deleted_count} ключей.")
        else:
            log.info("Не найдено ключей (cache:*, *lock*, *queue*) для удаления.")
    
    except Exception as e:
        log.error(f"Ошибка при очистке Redis: {e}", exc_info=True)
        raise
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---


async def execute_task(
    client: httpx.AsyncClient,
    log: logging.Logger,
    timeframe: str,
    url: str,
    redis_conn: Optional[redis.Redis] = None,
    clear_cache: bool = False
) -> bool:
    """
    Универсальный исполнитель задач через HTTP API.
    
    Args:
        client: HTTP клиент
        log: Логгер
        timeframe: Таймфрейм задачи
        url: Endpoint для запроса
        redis_conn: Соединение Redis (опционально, для очистки кэша)
        clear_cache: Очистить кэш перед запуском
    
    Returns:
        True если задача выполнена успешно
    
    Raises:
        ValueError: Если SECRET_TOKEN не установлен
        httpx.HTTPStatusError: При ошибках HTTP
    """
    if not SECRET_TOKEN:
        raise ValueError("SECRET_TOKEN не установлен в .env")
    
    # Очистка кэша при необходимости
    if clear_cache and redis_conn:
        # --- ИСПРАВЛЕНИЕ: Передаем ключ БЕЗ префикса ---
        # (execute_task используется только в post_task_1h, где timeframe='1h')
        cache_key = timeframe 
        log.info(f"Очищаю 'cache:{cache_key}' для инициализации обновления...")
        await redis_conn.delete(f"cache:{cache_key}") # cache_manager сам префикс не ставит при удалении
        # ---------------------------------------------
    
    headers = {"Authorization": f"Bearer {SECRET_TOKEN}"}
    timeout = MAX_WAIT_MINUTES_PER_TASK * 60 + 10
    
    log.info(f"--- 🔥 Запускаю задачу '{timeframe.upper()}' (POST {url})...")
    
    try:
        response = await client.post(url, headers=headers, timeout=timeout)
        
        if response.status_code == 200:
            log.info(f"✅ [OK] Задача '{timeframe.upper()}' успешно выполнена.")
            return True
        elif response.status_code == 409:
            log.error(f"💥 [FAIL] Блокировка занята (409 Conflict).")
            raise httpx.HTTPStatusError(
                "Lock occupied",
                request=response.request,
                response=response
            )
        else:
            log.error(f"💥 [FAIL] Ошибка выполнения задачи '{timeframe.upper()}'.")
            log.error(f"Статус: {response.status_code}")
            log.error(f"Тело ответа: {response.text}")
            response.raise_for_status()
            
    except httpx.HTTPError as e:
        log.error(f"💥 [FAIL] Ошибка HTTP при запросе к {url}: {e}")
        raise
    
    return False


async def post_task(
    client: httpx.AsyncClient,
    log: logging.Logger,
    task_type: Literal["base", "target"]
) -> bool:
    """
    Запускает задачу base или target через API.
    
    Args:
        client: HTTP клиент
        log: Логгер
        task_type: Тип задачи ('base' или 'target')
    
    Returns:
        True если задача выполнена успешно
    """
    # --- ИСПРАВЛЕНИЕ: Вызов переименованной функции ---
    base_tf, target_tf = _get_active_timeframes()
    # ---------------------------------------------
    
    if task_type == "base":
        timeframe = base_tf
        url = "/internal/update-base-data"
    elif task_type == "target":
        timeframe = target_tf
        url = "/internal/generate-target"
    else:
        raise ValueError(f"Неизвестный тип задачи: {task_type}. Используйте 'base' или 'target'.")
    
    return await execute_task(client, log, timeframe, url)


async def post_task_1h(
    client: httpx.AsyncClient,
    log: logging.Logger,
    redis_conn: redis.Redis
) -> bool:
    """
    Запускает задачу обновления данных 1h и проверки алертов.
    
    Args:
        client: HTTP клиент
        log: Логгер
        redis_conn: Соединение Redis (для очистки кэша)
    
    Returns:
        True если задача выполнена успешно
    """
    return await execute_task(
        client=client,
        log=log,
        timeframe="1h",
        url="/internal/update-1h-and-check-alerts",
        redis_conn=redis_conn,
        clear_cache=True
    )


async def get_coins_from_api_test():
    """
    Получает список монет из рабочей кодовой базы для тестирования.
    
    Returns:
        Список монет или пустой список при ошибке
    """
    try:
        from data_collector.coin_source import get_coins
        return await get_coins()
    except ImportError:
        logging.error("Не удалось импортировать get_coins для тестового сбора.")
        return []