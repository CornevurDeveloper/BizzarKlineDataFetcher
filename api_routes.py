# api_routes.py
import logging
import os
import json
import gzip 
import asyncio
# --- УДАЛЕНО: time, aiohttp, defaultdict ---
from fastapi import APIRouter, HTTPException, Depends, Security, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel 
from typing import List, Dict, Any, Optional

# --- Импорты Redis ---
from redis.asyncio import Redis as AsyncRedis
# ---------------------

# --- Импорты модулей исполнения ---
from cache_manager import (
    get_redis_connection,
    load_raw_bytes_from_cache,
    load_from_cache,
    save_to_cache,
)
# --- ИЗМЕНЕНИЕ: Проблемные импорты УДАЛЕНЫ с верхнего уровня ---
# (Они будут импортированы внутри функций, чтобы избежать Cyclic Import)
# from data_collector import fetch_market_data
# from data_collector.aggregation_target import run_target_generation_process as run_target_generation_process_func
from data_collector.coin_source import get_coins as get_all_symbols
# from data_collector.direct_fetcher import run_direct_data_collection
# -----------------------------------------------------------------------


# --- Импорты из config ---
from config import (
    ALLOWED_CACHE_KEYS,
    SECRET_TOKEN,
    ACTIVE_TIMEFRAME_PAIR,
    # --- УДАЛЕНО: CONCURRENCY_LIMIT ---
)


# Создаем объект Router
router = APIRouter()
security = HTTPBearer()

# --- КОД ИЗ "ПРОЕКТА А" (ДЛЯ .../direct) ---
class MarketDataRequest(BaseModel):
    timeframes: List[str]
    symbols: Optional[List[str]] = None

# Глобальный semaphore для защиты /direct
DIRECT_ENDPOINT_SEMAPHORE = asyncio.Semaphore(1)
# ----------------------------------------


def _get_active_timeframes() -> tuple[str, str]:
    """
    Парсит ACTIVE_TIMEFRAME_PAIR из конфига.
    """
    try:
        base_tf, target_tf = ACTIVE_TIMEFRAME_PAIR.split('_')
        return base_tf.lower(), target_tf.lower()
    except ValueError:
        logging.critical(f"Неверный формат ACTIVE_TIMEFRAME_PAIR: {ACTIVE_TIMEFRAME_PAIR}. Ожидается 'BASE_TARGET'.")
        raise HTTPException(status_code=500, detail="Ошибка конфигурации таймфреймов.")


async def verify_cron_secret(credentials: HTTPBearer = Security(security)):
    """Проверяет секретный токен для Cron-Job."""
    if not SECRET_TOKEN:
        logging.error("[CRON_JOB_API] Запрос отклонен: SECRET_TOKEN не установлен на сервере (503).")
        raise HTTPException(
            status_code=503,
            detail="Сервис недоступен: Секрет для Cron-Job не настроен."
        )
    
    if credentials.credentials != SECRET_TOKEN:
        logging.warning("[CRON_JOB_API] Запрос отклонен: Неверный токен (403).")
        raise HTTPException(
            status_code=403,
            detail="Доступ запрещен: Неверный токен."
        )
    return True


async def _run_data_collection_task(timeframe: str, log_prefix: str):
    """
    Общая функция для синхронного сбора Klines/OI/FR (для Base-TF).
    (Блокировка удалена)
    """
    # --- ИЗМЕНЕНИЕ: "Ленивый" импорт ---
    from data_collector import fetch_market_data
    # ---------------------------------
    
    redis_conn = await get_redis_connection()
    if not redis_conn:
        raise HTTPException(status_code=503, detail="Сервис недоступен: Redis не подключен.")

    try:
        # 1. Сбор монет
        all_coins = await get_all_symbols()
        if not all_coins:
            raise HTTPException(status_code=503, detail="Не удалось получить список монет.")
         
        # 2. Выполнение задачи 
        logging.info(f"{log_prefix} Запуск fetch_market_data ({timeframe}, {len(all_coins)} монет)...")
        # (Вызываем стандартный fetch_market_data, который соберет Klines, OI и FR)
        klines_data = await fetch_market_data(all_coins, timeframe, prefetched_fr_data=None)
        
        if not klines_data or not klines_data.get('data'):
            raise HTTPException(status_code=404, detail=f"Данные {timeframe} не найдены.")

        # 3. Сохранение
        # (Используем f"cache:{timeframe}", а не key из load_raw_bytes)
        await save_to_cache(redis_conn, f"cache:{timeframe}", klines_data)
        
        logging.info(f"{log_prefix} ✅ Задача {timeframe} успешно завершена и сохранена.")
        return {"status": "ok", "message": f"Сбор данных {timeframe} успешно завершен и кэширован."}

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"{log_prefix} КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")
    finally:
        if redis_conn:
            pass


# === НОВЫЙ ЭНДПОИНТ: СБОР БАЗОВОГО ТАЙМФРЕЙМА (4H или 12H) ===
@router.post("/internal/update-base-data", status_code=200)
async def update_base_data(
    is_authenticated: bool = Depends(verify_cron_secret)
):
    """
    (СИНХРОННЫЙ) Запускает сбор базового TF (4h или 12h) согласно конфигу.
    """
    base_tf, _ = _get_active_timeframes()
    log_prefix = f"[API_BASE_SYNC:{base_tf.upper()}]"
    
    return await _run_data_collection_task(base_tf, log_prefix)


# === НОВЫЙ ЭНДПОИНТ: ГЕНЕРАЦИЯ ЦЕЛЕВОГО ТАЙМФРЕЙМА (8H или 1D) ===
@router.post("/internal/generate-target", status_code=200)
async def generate_target_data(
    is_authenticated: bool = Depends(verify_cron_secret)
):
    """
    (СИНХРОННЫЙ) Запускает агрегацию целевого TF (8h или 1d) согласно конфигу.
    (Внешняя блокировка удалена)
    """
    # --- ИЗМЕНЕНИЕ: "Ленивый" импорт ---
    from data_collector.aggregation_target import run_target_generation_process as run_target_generation_process_func
    # ---------------------------------
    
    base_tf, target_tf = _get_active_timeframes()
    log_prefix = f"[API_TARGET_SYNC:{target_tf.upper()}]"
    
    try:
        # 1. Сбор монет
        all_coins = await get_all_symbols()
        if not all_coins:
            raise HTTPException(status_code=503, detail="Не удалось получить список монет.")
        
        # 3. Агрегация
        logging.info(f"{log_prefix} Запуск генерации {target_tf} из {base_tf}...")
        
        success = await run_target_generation_process_func(
            target_tf,  
            base_tf,    
            all_coins   
        )
        
        if not success:
             raise HTTPException(status_code=500, detail=f"Агрегация {target_tf} завершилась с ошибкой.")
        
        logging.info(f"{log_prefix} ✅ Задача {target_tf} успешно завершена и сохранена.")
        return {"status": "ok", "message": f"Агрегация данных {target_tf} успешно завершена и кэширована."}
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"{log_prefix} КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")
    


@router.get("/get-cache/{key}")
async def get_raw_cache(key: str):
    """Возвращает сырые сжатые GZIP данные из кэша Redis."""
    if key not in ALLOWED_CACHE_KEYS:
         raise HTTPException(status_code=400, detail=f"Ключ '{key}' не разрешен.")

    redis_conn = await get_redis_connection()
    if not redis_conn:
        raise HTTPException(status_code=503, detail="Сервис недоступен: Redis не подключен.")

    # (Используем f"cache:{key}", а не key из load_raw_bytes)
    data_bytes = await load_raw_bytes_from_cache(f"cache:{key}", redis_conn=redis_conn)
    
    if data_bytes:
        return Response(
            content=data_bytes,
            media_type="application/json",
            headers={
                 "Content-Encoding": "gzip",
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-transform"
            }
        )
    else:
        raise HTTPException(status_code=404, detail=f"Ключ '{key}' пуст.")


@router.get("/health")
@router.head("/health")
async def health_check():
    """Простой эндпоинт для проверки, что сервер жив."""
    return {"status": "ok"}


# === 🚀 ИЗМЕНЕНИЕ: НЕЗАВИСИМЫЙ ЭНДПОИНТ (ЛОГИКА ВЫНЕСЕНА) ===
@router.post("/get-market-data/direct")
async def get_market_data_direct(request: MarketDataRequest):
    """
    (НЕЗАВИСИМЫЙ) Запускает сбор Klines/OI/FR "вживую", минуя кэш.
    Реализует кастомную логику сбора (1/12/1d = K+OI, 4/8h = K+OI+FR).
    ВНИМАНИЕ: Запрос может занимать 60-90+ секунд.
    Защищен от DDoS: максимум 1 одновременный запрос.
    """
    # --- ИЗМЕНЕНИЕ: "Ленивый" импорт ---
    from data_collector.direct_fetcher import run_direct_data_collection
    # ---------------------------------
    
    if not request.timeframes:
        raise HTTPException(status_code=400, detail="Необходимо указать timeframe.")
    
    if len(request.timeframes) > 1:
        raise HTTPException(status_code=400, detail="Только один timeframe за запрос.")
    
    timeframe = request.timeframes[0]
    
    if timeframe not in ALLOWED_CACHE_KEYS:
        raise HTTPException(status_code=400, detail=f"Timeframe '{timeframe}' не поддерживается.")

    # ✅ Защита от DDoS
    async with DIRECT_ENDPOINT_SEMAPHORE:
        log_prefix = f"[API_DIRECT:{timeframe.upper()}]"
        logging.info(f"{log_prefix} Получен запрос. Семафор захвачен.")
        
        try:
            # 1. Вызываем новую независимую функцию
            # Она сама обработает сбор, фильтрацию, парсинг, слияние и GZIP
            return await run_direct_data_collection(timeframe, request.symbols)

        except HTTPException as e:
            # Пробрасываем HTTP ошибки (404, 503, 500) из direct_fetcher
            raise e
        # --- ИСПРАВЛЕНИЕ: IndentationError ---
        # (Этот блок сдвинут влево, чтобы соответствовать `try`)
        except Exception as e:
             # Ловим любые другие (не-HTTP) ошибки
             logging.error(f"{log_prefix} КРИТИЧЕСКАЯ ОШИБКА (API_ROUTES): {e}", exc_info=True)
             raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")
# === 🚀 КОНЕЦ ИЗМЕНЕНИЯ ===