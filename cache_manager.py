# cache_manager.py
# --- ВЕРСИЯ GZIP 100% (Render, пожалуйста, обновись) ---
import logging
import json
import gzip
from datetime import datetime
from typing import Dict, Any, Optional
from redis.asyncio import Redis as AsyncRedis
from urllib.parse import urlparse

# Импортируем ВСЁ из config.py
from config import (
  
    UPSTASH_REDIS_URL,
    UPSTASH_REDIS_TOKEN,
    # --- УДАЛЕНО: REDIS_TASK_QUEUE_KEY ---
    WORKER_LOCK_KEY,
    WORKER_LOCK_VALUE
)

logger = logging.getLogger(__name__)
_redis_pool: Optional[AsyncRedis] = None


async def get_redis_connection() -> Optional[AsyncRedis]:
    """(Код не изменен) Подключение к Redis - используем URL + TOKEN отдельно"""
    global _redis_pool
    
    if _redis_pool is None:
        try:
            # Парсим URL чтобы достать хост и порт
           
            parsed = urlparse(UPSTASH_REDIS_URL)
  
            _redis_pool = AsyncRedis(
                host=parsed.hostname,
                port=parsed.port or 6379,
                password=UPSTASH_REDIS_TOKEN,  # <-- Токен отдельно!
                ssl=True,  # Upstash всегда требует SSL
                decode_responses=False,
                # --- ИЗМЕНЕНИЕ №9: Увеличение таймаутов до 120 сек ---
                socket_connect_timeout=120, 
                socket_timeout=120,                 
                # --------------------------------------------------
                socket_keepalive=True
            )
 
            await _redis_pool.ping()
            logger.info("✅ Подключено к Redis")
            return _redis_pool
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis: {e}")
            _redis_pool = None
            return None
    
 
    return _redis_pool


async def check_redis_health() -> bool:
    """(Код не изменен) Проверяет доступность Redis."""
    conn = await get_redis_connection()
    if conn:
        try:
            return await conn.ping()
        except Exception:
            return False
    return False


async def load_from_cache(key: str, redis_conn: AsyncRedis) -> Optional[Dict[str, Any]]:
    """(Код не изменен) Загружает данные из Redis по ключу. Декодирует JSON."""
    cache_key = f"cache:{key}"
    data_bytes = await redis_conn.get(cache_key)
    
    if data_bytes:
        try:
            # --- Сначала распаковываем ---
            data_bytes = gzip.decompress(data_bytes)
            # ----------------------------------------
            data_str = data_bytes.decode('utf-8')
           
            return json.loads(data_str)
      
        except (IOError, gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as e:
            # --- Обработка, если данные не сжаты (старый кэш) ---
            logger.warning(f"[CACHE] Не удалось распаковать gzip для {cache_key} (возможно, старый кэш? Ошибка: {e}). Попытка прочитать как обычный JSON...")
            try:
                # Попытка прочитать как обычный (не сжатый) JSON
                data_str = data_bytes.decode('utf-8')
                return json.loads(data_str)
            except Exception as e_inner:
         
                logger.error(f"[CACHE] Ошибка десериализации ключа {cache_key} (даже как fallback): {e_inner}")
                return None
            # -----------------------------------------------------------------
    return None


async def load_raw_bytes_from_cache(key: str, redis_conn: AsyncRedis) -> Optional[bytes]:
    """
    (Код не изменен) Загружает сырые байты из Redis (без декомпрессии).
    """
    cache_key = f"cache:{key}"
    # Просто возвращаем байты (это GZIP), которые лежат в Redis
    return await redis_conn.get(cache_key)


async def save_to_cache(redis_conn: AsyncRedis, key: str, data: Dict[str, Any], expiry_seconds: Optional[int] = None) -> bool:
    """Сохраняет данные в Redis."""
    cache_key = f"cache:{key}"
    
    if 'audit' not in data:
        data_content = data.get('data')
        count = 0
        if isinstance(data_content, (list, dict)):
     
             count = len(data_content)
            
        data['audit'] = {
            "timestamp": int(datetime.now().timestamp() * 1000),
            "source": "data_collector",
            "count": count
        }
        
    try:
  
        data_json = json.dumps(data)
        data_bytes = data_json.encode('utf-8')
        
        
        # --- Сжимаем данные перед отправкой ---
        compressed_data = gzip.compress(data_bytes)
        # -------------------------------------------------
        
        if expiry_seconds:
        
            result = await redis_conn.set(cache_key, compressed_data, ex=expiry_seconds)
     
        else:
            result = await redis_conn.set(cache_key, compressed_data)
        
        # --- ИСПРАВЛЕНИЕ: Используем существующий ключ audit.symbols_in_final_list ---
        final_count = data.get('audit', {}).get('symbols_in_final_list', 'N/A')
        
        logger.info(f"[CACHE] Успешно сохранено {final_count} записей в {cache_key} (Сжато: {len(data_bytes)} -> {len(compressed_data)} байт).")
        # --------------------------------------------------------------------------
        return result
    except Exception as e:
        logger.error(f"[CACHE] Ошибка при сохранении ключа {cache_key} в Redis: {e}", exc_info=True)
        return False


# --- УДАЛЕНО: async def clear_queue(...) ---
    
# --- УДАЛЕНО: async def add_task_to_queue(...) ---


async def get_worker_status(redis_conn: AsyncRedis) -> Optional[bytes]:
    """(Код не изменен) Возвращает статус блокировки воркера (bytes или None)."""
    return await redis_conn.get(WORKER_LOCK_KEY)


async def check_if_task_is_running(timeframe: str, redis_conn: AsyncRedis) -> bool:
  
    """(Код не изменен) Проверяет, выполняется ли задача для данного timeframe."""
    lock_status = await get_worker_status(redis_conn)
    return lock_status and lock_status.decode('utf-8') == WORKER_LOCK_VALUE