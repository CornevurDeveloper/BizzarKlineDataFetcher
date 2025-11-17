# tests_e2e/test_3_deep_integration.py
import httpx # <-- ВОССТАНОВЛЕНО
import logging
import asyncio
import sys
import json 
from typing import Dict, Any, List

# Импортируем из tests_e2e
from . import helpers
# from .helpers import _get_active_timeframes # <-- УДАЛЕНО (Изменение №64)

# Импортируем из рабочей кодовой базы
try:
    import url_builder
    import api_parser
    import data_collector.fetch_strategies as fetch_strategies
    from data_collector.task_builder import prepare_tasks
except ImportError as e:
    logging.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось импортировать модули для интеграционного теста: {e}", exc_info=True)
    sys.exit(1)


# --- 1. Вспомогательная функция для запуска прямого сбора ---
async def _fetch_and_parse_direct(session: httpx.AsyncClient, task_info: Dict[str, Any], log: logging.Logger) -> bool:
    """
    Выполняет прямой запрос, используя соответствующую стратегию (fetch_strategies).
    Возвращает True, если данные получены, спарсены, и их количество > 0.
    """
    symbol = task_info['symbol']
    exchange = task_info['exchange']
    data_type = task_info['data_type']
    timeframe = task_info['original_timeframe']
    
    # 1. Создаем Semaphore (нужен для fetch_strategies)
    semaphore = asyncio.Semaphore(1) 
    
    # 2. Выбираем стратегию сбора
    fetch_func = getattr(fetch_strategies, f"fetch_{exchange}_paginated", fetch_strategies.fetch_simple)

    if exchange == 'binance':
        fetch_func = fetch_strategies.fetch_simple
    elif exchange == 'bybit':
        fetch_func = fetch_strategies.fetch_bybit_paginated
    else:
        log.error(f"Неизвестная биржа {exchange}")
        return False
        
    try:
        # Для этого теста создаем временную AIOHTTP сессию
        async with fetch_strategies.aiohttp.ClientSession() as aio_session:
            
            # Запуск сбора
            task_info_result, raw_data = await fetch_func(aio_session, task_info, semaphore)
        
    except Exception as e:
        log.error(f"💥 [FAIL] {symbol} ({exchange}, {data_type}): Ошибка сбора данных: {e}", exc_info=True)
        return False

    if not raw_data:
        log.error(f"💥 [FAIL] {symbol} ({exchange}, {data_type}): Сбор вернул пустые данные.")
        return False
        
    # 3. Парсинг
    try:
        parser_func = task_info['parser']
        parsed_data = parser_func(raw_data, timeframe)
        
        if not parsed_data:
             log.error(f"💥 [FAIL] {symbol} ({exchange}, {data_type}): Парсинг вернул пустой список.")
             return False

        # 4. Проверка количества и целостности
        log.info(f"   |-> {data_type.upper()} ({exchange}): Собрано {len(parsed_data)} записей.")
        
        # Klines должны быть > 700 (801 - последняя свеча + возможные пропуски)
        if data_type == 'klines' and len(parsed_data) < 700:
             log.error(f"💥 [FAIL] {symbol}: Klines ({len(parsed_data)}) слишком мало (< 700).")
             return False

        # --- ДЕТАЛЬНЫЙ ВЫВОД СЫРЫХ ДАННЫХ ДЛЯ ОТЧЕТА ---
        if data_type in ['oi', 'fr', 'klines']:
            log.info("-" * 40)
            log.info(f"   |-> {data_type.upper()} СТРУКТУРА ДАННЫХ (ТОП 5) для {symbol}:")
            
            raw_list = raw_data
            if exchange == 'bybit' and isinstance(raw_data, dict):
                 raw_list = raw_data.get('result', {}).get('list', [])

            
            # Klines (список словарей)
            if data_type == 'klines':
                for i, candle in enumerate(parsed_data[-5:]):
                    # Выводим ключевые поля Klines + VolumeDelta
                    log.info(f"   |-> KLINE: {i+1}. openTime={candle['openTime']}, closeTime={candle['closeTime']}, VD={candle.get('volumeDelta')}")
            
            # OI/FR (словарь)
            else:
                 # Выводим сырые данные (только 5 последних)
                 if isinstance(raw_list, list):
                     for i, raw_entry in enumerate(raw_list[-5:]):
                         # Используем json.dumps для чистого форматирования словаря
                         log.info(f"   |-> СЫРОЙ {data_type.upper()}: {i+1}. {json.dumps(raw_entry)}")
                 
                 # Выводим спарсенные данные (только 5 последних)
                 for i, entry in enumerate(parsed_data[-5:]):
                     if data_type == 'oi':
                         log.info(f"   |-> СПАРСЕННЫЙ OI: {i+1}. openTime={entry['openTime']}, OI={entry['openInterest']}")
                     elif data_type == 'fr':
                         log.info(f"   |-> СПАРСЕННЫЙ FR: {i+1}. openTime={entry['openTime']}, FR={entry['fundingRate']}")
            log.info("-" * 40)
        # -------------------------------------------------------------
        
        return True

    except Exception as e:
        log.error(f"💥 [FAIL] {symbol} ({exchange}, {data_type}): Ошибка парсинга: {e}", exc_info=True)
        return False


# --- 2. ГЛАВНАЯ ФУНКЦИЯ ТЕСТА ---
async def run_deep_integration_check(client: httpx.AsyncClient, log: logging.Logger) -> bool:
    """
    Сценарий 3: Глубокая интеграционная проверка (сбор Klines/OI/FR напрямую).
    """
    log.info("=" * 60)
    log.info("--- 🔎 [Сценарий 3] Глубокая Интеграция: Начинаю (Binance/Bybit) ---")
    
    # ИСПОЛЬЗУЕМ helpers._get_active_timeframes()
    base_tf, _ = helpers._get_active_timeframes() # Проверяем только Base-TF
    all_passed = True
    
    # 1. Получаем список монет (для выбора)
    try:
        all_coins = await helpers.get_coins_from_api_test()
        if not all_coins:
            log.error("💥 [FAIL] Не удалось получить список монет для проверки.")
            return False
            
        # 2. Выбираем монеты для теста: BTC (Binance) и TONUSDT (Binance - проблемная монета)
        binance_btc = next((c for c in all_coins if c['symbol'] == 'BTCUSDT' and 'binance' in c['exchanges']), None)
        binance_ton = next((c for c in all_coins if c['symbol'] == 'TONUSDT' and 'binance' in c['exchanges']), None)
        
        if not binance_btc or not binance_ton:
            log.warning("⚠️ [WARN] Не найдены подходящие монеты BTCUSDT или TONUSDT (Binance). Пропускаю интеграционный тест.")
            return True 
            
    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при подготовке монет: {e}", exc_info=True)
        return False
        
    coins_to_test = [
        {"coin": binance_btc, "exchange": "binance"},
        {"coin": binance_ton, "exchange": "binance"}
    ]
    
    # 3. Создаем задачи и запускаем прямой сбор
    for item in coins_to_test:
        coin = item['coin']
        exchange = item['exchange']
        
        log.info(f"--- Тестирование {coin['symbol']} на {exchange.upper()} ({base_tf}) ---")
    
        # Создаем задачи для Klines, OI, FR
        tasks_prepared = prepare_tasks([coin], base_tf)
        
        tasks_filtered = [t for t in tasks_prepared if t['exchange'] == exchange]
        
        for task in tasks_filtered:
            if not await _fetch_and_parse_direct(client, task, log):
                all_passed = False

    log.info("=" * 60)
    if all_passed:
        log.info("--- ✅ [Сценарий 3] Интеграционный тест пройден.")
    else:
        log.error("--- 💥 [Сценарий 3] Интеграционный тест провален. ---")
        
    return all_passed