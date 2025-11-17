import asyncio
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
import time

# --- ИСПРАВЛЕНИЕ: Используем абсолютные импорты ---
import config
import api_parser
from cache_manager import get_redis_connection, save_to_cache
from data_collector import fetch_strategies
from data_collector.task_builder import prepare_tasks
from data_collector.data_processing import merge_data, format_final_structure
from data_collector.logging_setup import logger
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---
from config import TIMEFRAMES_TO_TRIM

 

FETCH_STRATEGY_MAP = {
    'binance': fetch_strategies.fetch_simple,
    'bybit': fetch_strategies.fetch_bybit_paginated,
}


def _sort_and_trim_klines(parsed_list: List[Dict], timeframe: str) -> List[Dict]:
    """Сортирует и обрезает последнюю незакрытую свечу для определенных таймфреймов."""
    if not parsed_list:
        return parsed_list
    
    # Гарантируем сортировку по возрастанию
    parsed_list.sort(key=lambda x: x.get('openTime', 0))
    
    # Обрезаем последнюю незакрытую свечу
    if timeframe in TIMEFRAMES_TO_TRIM:
        return parsed_list[:-1]
    
    return parsed_list


async def _fetch_and_process_data(
    all_coins: List[Dict], 
    timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Основная логика: готовит задачи, выполняет асинхронный сбор данных с бирж 
    и группирует их по типу данных (klines, oi, fr).
    """
    
    logger.info(f"[{timeframe.upper()}] 1/6: Подготовка задач...")

    # 1. Подготовка задач
    tasks_prepared = prepare_tasks(all_coins, timeframe)
    
    if not tasks_prepared:
        logger.warning(f"[{timeframe.upper()}] Нет задач для выполнения.")
        return None
    
    logger.info(f"[{timeframe.upper()}] 1/6: Готово. Всего {len(tasks_prepared)} задач.")

    # 2. Асинхронный сбор данных
    logger.info(f"[{timeframe.upper()}] 2/6: Запуск асинхронного сбора данных (Лимит: {config.CONCURRENCY_LIMIT}).")
    
    start_time = time.perf_counter()  # perf_counter точнее для измерения времени выполнения
    
    # Группировка задач по биржам
    tasks_by_exchange = defaultdict(list)
    for task in tasks_prepared:
        tasks_by_exchange[task['exchange']].append(task)
    
    # Создаем задачи для asyncio.gather
    async_tasks = []
    async with fetch_strategies.aiohttp.ClientSession() as aio_session:
        for exchange, task_list in tasks_by_exchange.items():
            fetch_func = FETCH_STRATEGY_MAP.get(exchange, fetch_strategies.fetch_simple)
            exchange_semaphore = asyncio.Semaphore(config.CONCURRENCY_LIMIT)
            
            for task_info in task_list:
                async_tasks.append(fetch_func(aio_session, task_info, exchange_semaphore))
        
        # Выполняем все задачи параллельно
        results = await asyncio.gather(*async_tasks, return_exceptions=True)
    
    elapsed = time.perf_counter() - start_time
    logger.info(f"[{timeframe.upper()}] 2/6: Сбор данных завершен за {elapsed:.2f} сек.")

    # 3. Парсинг и группировка
    logger.info(f"[{timeframe.upper()}] 3/6: Парсинг и группировка...")
    
    processed_data: Dict[str, Dict[str, List]] = {}
    successful_tasks = 0
    failed_tasks = 0
    
    for task, result in zip(tasks_prepared, results):
        symbol = task['symbol']
        data_type = task['data_type']
        
        # Обработка ошибок
        if isinstance(result, Exception):
            logger.warning(f"  -> {symbol}/{data_type.upper()}: Ошибка: {result}")
            failed_tasks += 1
            continue
        
        if result is None:
            logger.warning(f"  -> {symbol}/{data_type.upper()}: Пустой ответ")
            failed_tasks += 1
            continue
        
        _, raw_data = result
        parser_func = task['parser']
        
        try:
            parsed_list = parser_func(raw_data, timeframe)
            
            # Сортировка и обрезка для klines
            if data_type == 'klines':
                parsed_list = _sort_and_trim_klines(parsed_list, timeframe)
            
            if parsed_list:
                # Инициализируем структуру при первом использовании
                if symbol not in processed_data:
                    processed_data[symbol] = {}
                if data_type not in processed_data[symbol]:
                    processed_data[symbol][data_type] = []
                
                processed_data[symbol][data_type].extend(parsed_list)
                successful_tasks += 1
        
        except Exception as e:
            logger.error(f"  -> {symbol}/{data_type.upper()}: Ошибка парсинга: {e}", exc_info=True)
            failed_tasks += 1
    
    logger.info(
        f"[{timeframe.upper()}] 3/6: Обработано: {len(tasks_prepared)}, "
        f"Успешно: {successful_tasks}, Ошибки: {failed_tasks}"
    )

    # 4. Слияние и форматирование
    logger.info(f"[{timeframe.upper()}] 4/6: Слияние Klines/OI/FR...")
    
    # Создаем индекс монет для быстрого поиска O(1) вместо O(n)
    coins_by_symbol = {c['symbol']: c for c in all_coins}
    
    all_merged_results = []
    
    for symbol, data_types in processed_data.items():
        coin_full_info = coins_by_symbol.get(symbol)
        
        if not coin_full_info:
            logger.warning(f"  -> {symbol}: Информация о монете не найдена в all_coins")
            continue
        
        merged_result = merge_data(data_types, timeframe)
        
        if merged_result:
            all_merged_results.append({
                'symbol': symbol,
                'data': merged_result,
                'exchanges': coin_full_info.get('exchanges', [])
            })
    
    logger.info(f"[{timeframe.upper()}] 5/6: Слияние завершено.")
    
    # Формирование финальной структуры
    final_cache_structure = format_final_structure(all_merged_results, all_coins, timeframe)
    
    logger.info(f"[{timeframe.upper()}] 6/6: Финальная структура готова.")
    
    return final_cache_structure


async def fetch_market_data_and_save(
    all_coins: List[Dict], 
    timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Основная точка входа для сбора данных и сохранения в Redis.
    
    Args:
        all_coins: Список монет с их конфигурацией
        timeframe: Таймфрейм для сбора данных (например, '1h', '4h')
    
    Returns:
        Финальная структура данных или None в случае ошибки
    """
    redis_conn = None
    
    try:
        redis_conn = await get_redis_connection()
        if not redis_conn:
            logger.critical("Не удалось подключиться к Redis.")
            return None

        # 1. Получение и обработка данных
        final_data = await _fetch_and_process_data(all_coins, timeframe)

        if not final_data:
            logger.warning(f"[{timeframe.upper()}] Сбор данных завершен, но финальная структура пуста.")
            return None

        # 2. Сохранение в кэш
        cache_key = timeframe
        success = await save_to_cache(redis_conn, cache_key, final_data)
        
        if success:
            logger.info(f"[{timeframe.upper()}] ✅ Данные успешно сохранены в кэше.")
            return final_data
        else:
            logger.error(f"[{timeframe.upper()}] ❌ Ошибка сохранения данных в кэше.")
            return None

    except Exception as e:
        logger.critical(
            f"[{timeframe.upper()}] КРИТИЧЕСКАЯ ОШИБКА в fetch_market_data_and_save: {e}", 
            exc_info=True
        )
        return None
    
    finally:
        # Redis соединение управляется глобально, не закрываем здесь
        pass