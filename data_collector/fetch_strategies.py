# data_collector/fetch_strategies.py

import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional, Tuple, List
import time

try:
    from data_collector.logging_setup import logger
except ImportError:
    import logging
    
logger = logging.getLogger(__name__)

# --- ИЗМЕНЕНИЕ: Заголовки для маскировки под браузер (из JS эталона) ---
BINANCE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.binance.com",
    "Referer": "https://www.binance.com/"
}
# -----------------------------------------------------------------------


# --- 1. Binance / Простой GET ---

async def fetch_simple(
    session: aiohttp.ClientSession, 
    task_info: Dict[str, Any], 
    semaphore: asyncio.Semaphore
) -> Optional[Tuple[Dict[str, Any], Any]]:
    """
    Универсальная функция для простых GET-запросов (Binance и большинство API).
    """
    url = task_info['url']
    symbol = task_info['symbol']
    data_type = task_info['data_type']
    timeframe = task_info.get('timeframe', 'N/A')
    exchange = task_info.get('exchange', 'binance')
    
    log_prefix = f"[{timeframe.upper()}] FETCH_SIMPLE ({exchange.upper()})"
    
    # --- ИЗМЕНЕНИЕ: Выбор заголовков ---
    request_headers = BINANCE_HEADERS if exchange == 'binance' else {}
    # -----------------------------------

    async with semaphore:
        # Оставляем небольшую задержку для безопасности
        await asyncio.sleep(0.2)
        
        start_time = time.time()
        try:
            # --- ИЗМЕНЕНИЕ: Передаем headers ---
            async with session.get(url, headers=request_headers, timeout=30) as response:
            # -----------------------------------
                
                log_status = "✅" if response.status == 200 else "❌"
                
                if response.status == 200:
                    raw_data = await response.json()
                    data_size = len(raw_data) if isinstance(raw_data, (list, dict)) else 0

                    logger.debug(
                        f"{log_prefix} {log_status} {symbol}/{data_type.upper()}: HTTP {response.status} | Размер: {data_size} записей | Время: {time.time() - start_time:.2f} с"
                    )
                    
                    return (task_info, raw_data)
                else:
                    text_response = await response.text()
                    logger.error(
                        f"{log_prefix} {log_status} {symbol}/{data_type.upper()}: HTTP {response.status} | Ошибка: {text_response[:100]} | URL: {url}"
                    )

        except asyncio.TimeoutError:
            logger.warning(f"{log_prefix}: Таймаут запроса {data_type} для {symbol} ({exchange}). URL: {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"{log_prefix}: Ошибка клиента {data_type} для {symbol} ({exchange}): {e}. URL: {url}")
            return None
        except Exception as e:
            logger.error(f"{log_prefix}: Неожиданная ошибка {data_type} для {symbol} ({exchange}): {e}. URL: {url}")
            return None


# --- 2. Bybit / Пагинация ---

async def fetch_bybit_paginated(
    session: aiohttp.ClientSession, 
    task_info: Dict[str, Any], 
    semaphore: asyncio.Semaphore
) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """
    Сбор данных Bybit с поддержкой пагинации, если limit > 1000.
    """
    url = task_info['url']
    symbol = task_info['symbol']
    data_type = task_info['data_type']
    timeframe = task_info.get('timeframe', 'N/A')
    exchange = task_info.get('exchange', 'bybit')
    limit = task_info.get('params', {}).get('limit', 1000)

    log_prefix = f"[{timeframe.upper()}] FETCH_PAGINATED ({exchange.upper()})"
    
    # Bybit: Максимальный лимит в одном запросе - 1000.
    MAX_PAGE_SIZE = 1000
    
    if limit <= MAX_PAGE_SIZE:
        # Если лимит не превышен, используем fetch_simple (который обрабатывает ошибки)
        return await fetch_simple(session, task_info, semaphore) 

    # --- Логика пагинации ---
    
    start_time = time.time()
    all_data = []
    current_limit = limit
    
    # 1. Формируем базовый URL и параметры
    base_url = url.split('?')[0]
    
    # 2. Пагинация
    async with semaphore:
        for offset in range(0, limit, MAX_PAGE_SIZE):
            page_size = min(MAX_PAGE_SIZE, current_limit)
            
            await asyncio.sleep(0.2)

            # Обновляем параметры URL
            current_url = f"{base_url}?symbol={symbol}&interval={timeframe}&limit={page_size}"
            if all_data:
                last_time = all_data[-1].get('openTime') 
                if last_time:
                    current_url += f"&endTime={last_time}"
                else:
                    logger.warning(f"{log_prefix}: Не удалось найти 'openTime' для пагинации {symbol}. Останов.")
                    break

            try:
                # Для Bybit пока не используем спец. заголовки, если не будет проблем
                async with session.get(current_url, timeout=30) as response:
                    
                    log_status = "✅" if response.status == 200 else "❌"
                    
                    if response.status == 200:
                        raw_data = await response.json()
                        data_payload = raw_data.get('result', {}).get('list', []) if isinstance(raw_data, dict) else []
                        data_size = len(data_payload)
                        
                        logger.debug(
                            f"{log_prefix} {log_status} {symbol}/{data_type.upper()} | Стр. {offset//MAX_PAGE_SIZE + 1}: "
                            f"HTTP {response.status} | Получено: {data_size} записей | Время: {time.time() - start_time:.2f} с"
                        )

                        if not data_payload:
                            break 

                        all_data.extend(data_payload)
                        current_limit -= page_size
                        
                        if data_size < page_size or current_limit <= 0:
                            break
                    else:
                        text_response = await response.text()
                        logger.error(
                            f"{log_prefix} {log_status} {symbol}/{data_type.upper()} | Стр. {offset//MAX_PAGE_SIZE + 1}: "
                            f"HTTP {response.status} | Ошибка: {text_response[:100]} | URL: {current_url}"
                        )
                        break

            except asyncio.TimeoutError:
                logger.warning(f"{log_prefix}: Таймаут запроса {data_type} для {symbol}. URL: {current_url}")
                break
            except aiohttp.ClientError as e:
                logger.error(f"{log_prefix}: Ошибка клиента {data_type} для {symbol}: {e}. URL: {current_url}")
                break
            except Exception as e:
                logger.error(f"{log_prefix}: Неожиданная ошибка {data_type} для {symbol}: {e}. URL: {current_url}")
                break

    
    final_raw_data = all_data # Возвращаем объединенный список
    
    if final_raw_data:
        return (task_info, final_raw_data)
        
    return None