# data_collector/direct_fetcher.py

import logging
import asyncio
import gzip 
import json
import time
import aiohttp
from collections import defaultdict
import os 
import sys 
from typing import List, Dict, Any, Optional

# --- Зависимости FastAPI ---
from fastapi import HTTPException, Response

logger = logging.getLogger(__name__)


async def run_direct_data_collection(timeframe: str, symbols: Optional[List[str]]) -> Response:
    """
    Выполняет полный независимый цикл сбора данных "вживую"
    с кастомной фильтрацией FR.
    """
    
    # --- "Ленивые" импорты (абсолютные пути) ---
    try:
        import data_collector.task_builder as task_builder
        import data_collector.fetch_strategies as fetch_strategies
        import data_collector.data_processing as data_processing
        from data_collector.coin_source import get_coins as get_all_symbols
        import config
        import api_parser
    except ImportError as e:
        logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА в direct_fetcher: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка импорта на сервере: {e}")
    
    log_prefix = f"[API_DIRECT:{timeframe.upper()}]"
    start_total_time = time.time()
        
    try:
        # 1. Получаем список монет
        logging.info(f"{log_prefix} 1/6: Запрос списка монет...")
        all_coins = await get_all_symbols()
        if not all_coins:
            logging.error(f"{log_prefix} 1/6: Список монет пуст.")
            raise HTTPException(status_code=503, detail="Не удалось получить список монет.")
        
        # Фильтрация по 'symbols' (если предоставлены)
        if symbols:
            logging.info(f"{log_prefix} Применяю фильтр: {len(symbols)} монет.")
            all_coins = [c for c in all_coins if c.get('symbol') in symbols]

        # 2. Готовим задачи
        logging.info(f"{log_prefix} 2/6: Подготовка задач...")
        tasks_prepared = task_builder.prepare_tasks(all_coins, timeframe)
        
        # 3. *** КАСТОМНАЯ ЛОГИКА: Фильтр FR ***
        final_tasks_to_run = []
        for task in tasks_prepared:
            data_type = task['data_type']
            
            # ПРАВИЛО: Пропускаем FR, если TF не 4h или 8h
            if data_type == 'fr' and timeframe not in ['4h', '8h']:
                logging.debug(f"{log_prefix} Пропускаю FR-задачу для {timeframe}.")
                continue
                
            final_tasks_to_run.append(task)
        
        logging.info(f"{log_prefix} 2/6: Готово. Всего {len(final_tasks_to_run)} задач.")

        # 4. Выполняем задачи
        logging.info(f"{log_prefix} 3/6: Запуск асинхронного сбора данных (Лимит: {config.CONCURRENCY_LIMIT})...")
        start_fetch_time = time.time()
        
        semaphore = asyncio.Semaphore(config.CONCURRENCY_LIMIT)
        results = []
        
        async with aiohttp.ClientSession() as aio_session:
            tasks_by_exchange = defaultdict(list)
            for task in final_tasks_to_run:
                tasks_by_exchange[task['exchange']].append(task)

            async_tasks = []
            for exchange, task_list in tasks_by_exchange.items():
                fetch_func = fetch_strategies.fetch_simple if exchange == 'binance' else fetch_strategies.fetch_bybit_paginated
                exchange_semaphore = asyncio.Semaphore(config.CONCURRENCY_LIMIT) 
                
                for task_info in task_list:
                    async_tasks.append(fetch_func(aio_session, task_info, exchange_semaphore))
            
            results = await asyncio.gather(*async_tasks, return_exceptions=True)
        
        logging.info(f"{log_prefix} 3/6: Сбор данных завершен за {time.time() - start_fetch_time:.2f} сек.")

        # 5. Парсинг и Обработка
        logging.info(f"{log_prefix} 4/6: Парсинг Klines/OI/FR...")
        processed_data = defaultdict(lambda: defaultdict(list))
        
        for i, res in enumerate(results):
            task = final_tasks_to_run[i]
            symbol = task['symbol']
            data_type = task['data_type']
            
            if isinstance(res, Exception) or res is None:
                logging.warning(f"  -> {symbol}/{data_type.upper()}: Ошибка сбора или пустой ответ: {res}")
                continue
            
            task_info_result, raw_data = res
            parser_func = task['parser']
            
            try:
                parsed_list = parser_func(raw_data, timeframe) 
                if parsed_list:
                    processed_data[symbol][data_type].extend(parsed_list)
            except Exception as e:
                logging.error(f"  -> {symbol}/{data_type.upper()}: Ошибка парсинга: {e}", exc_info=True)

        # 6. Слияние
        logging.info(f"{log_prefix} 5/6: Слияние Klines/OI/FR...")
        all_merged_results = []
        for symbol, data_types in processed_data.items():
            coin_full_info = next((c for c in all_coins if c['symbol'] == symbol), None)
            if coin_full_info:
                merged_result = data_processing.merge_data(data_types, timeframe)
                if merged_result:
                    all_merged_results.append({
                        'symbol': symbol,
                        'data': merged_result,
                        'exchanges': coin_full_info.get('exchanges', [])
                    })
        
        # 7. Финальное форматирование
        logging.info(f"{log_prefix} 6/6: Финальное форматирование...")
        final_structured_data = data_processing.format_final_structure(
            all_merged_results, all_coins, timeframe
        )

        if not final_structured_data or not final_structured_data.get('data'):
            logging.warning(f"{log_prefix} 6/6: Сбор данных вернул пустой результат.")
            raise HTTPException(status_code=404, detail="Данные не найдены.")

        # 8. Сжатие и возврат
        logging.info(f"{log_prefix} Сжатие {len(final_structured_data['data'])} записей...")
        
        json_data = json.dumps(final_structured_data) 
        compressed_data = gzip.compress(json_data.encode('utf-8'))
        
        logging.info(f"{log_prefix} Отправка ответа ({len(compressed_data)} байт, GZIP)...")
        
        # Возвращаем сжатые данные БЕЗ Content-Encoding (чтобы браузер не распаковывал)
        return Response(
            content=compressed_data,
            media_type="application/octet-stream",  # Бинарные данные
            headers={
                "Content-Type": "application/json",  # Внутри JSON
                "X-Content-Encoding": "gzip",  # Информативный заголовок
                "Cache-Control": "no-transform, no-cache, max-age=0"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"{log_prefix} КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")