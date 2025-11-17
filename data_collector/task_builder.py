# data_collector/task_builder.py

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict
import os 
import re 
from config import KLINES_LIMIT_1H # <-- ДОБАВЬТЕ ЭТОТ ИМПОРТ
# === Импорты заменены на абсолютные ===
import url_builder
import api_parser 
# ============================================

try:
    from data_collector.logging_setup import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# --- Определение таймфреймов для API (если требуется) ---
def _get_api_timeframe(timeframe: str, data_type: str, exchange: str) -> str:
    """
    Возвращает фактический таймфрейм, который нужно передать в API биржи.
    """
    if exchange == 'binance':
        # --- ИЗМЕНЕНИЕ (Задача 1): Обновление логики OI ---
        # 1. Сбор OI
        if data_type == 'oi':
            # Для Klines '1h' используем OI '1h'
            if timeframe == '1h':
                return '1h'
            # Для Klines '4h', '8h', '12h', '1d' используем OI '4h'
            return '4h'
        # --------------------------------------------------
            
        # --- ИЗМЕНЕНИЕ (Задача 2): Удален неиспользуемый elif data_type == 'fr' ---
            
    # Для Bybit и всех остальных случаев используем исходный таймфрейм
    return timeframe

# --- ГЛАВНАЯ ФУНКЦИЯ ---
def prepare_tasks(coins: List[Dict], timeframe: str) -> List[Dict[str, Any]]:
    """
    Генерирует список задач для асинхронного сбора данных.
    """
    log_prefix = f"[{timeframe.upper()}_TASK_BUILDER]"
    tasks = []
    
    # Klines: Используем KLINES_LIMIT_BASE_TF из config.py (801)
    if timeframe == '1h':
        klines_limit = KLINES_LIMIT_1H
    else:
        klines_limit = url_builder.KLINES_LIMIT_BASE_TF 
    
    # --- ИЗМЕНЕНИЕ №26 (Revised): ЖЕСТКО ЗАДАННЫЕ ЛИМИТЫ OI/FR ---
    # OI: Берем все доступные данные (максимум API ~500, используем 500).
    oi_limit = 500 
    
    # FR: Установлен жесткий лимит 400, как запрошено.
    fr_limit = 400
    # -------------------------------------------------------------
    
    # ИЗМЕНЕНИЕ №39: Список поддерживаемых FR интервалов Binance (4ч и 8ч)
    BINANCE_SUPPORTED_FR_PERIODS = ['4h', '8h'] 
   
    for coin in coins:
        symbol = coin.get('symbol') 
        exchanges = coin.get('exchanges', [])
        
        if not symbol or not exchanges:
            logger.warning(f"{log_prefix} Пропускаю монету без символа или бирж: {coin.get('symbol')}")
            continue 

        # --- ИЗМЕНЕНИЕ №23: Реализация приоритетной логики выбора биржи ---
        target_exchange = None
        
        # 1. Приоритет Binance (если бинанс есть)
        if 'binance' in exchanges:
            target_exchange = 'binance'
        
        # 2. Fallback на Bybit (только если Binance не был выбран)
        elif 'bybit' in exchanges:
            # --- Правило: BTCUSDT не должен быть на Bybit ---
            if symbol == 'BTCUSDT':
                logger.warning(f"{log_prefix} Пропускаю BTCUSDT: Запрещено брать с Bybit (Binance не доступен).")
                continue 
            target_exchange = 'bybit'
            
        if not target_exchange:
            continue # Монета не соответствует правилам выбора биржи

        exchange = target_exchange # Выбираем ОДНУ биржу для создания задач
        # -------------------------------------------------------------------
        
        # --- 1. Klines ---
        url_func_klines = getattr(url_builder, f"get_{exchange}_klines_url", None)
        parser_func_klines = getattr(api_parser, f"parse_{exchange}_klines", None)
        
        if url_func_klines and parser_func_klines:
            tasks.append({
                "symbol": symbol, 
                "symbol_api": symbol, 
                "exchange": exchange,
                "data_type": "klines",
                "url": url_func_klines(symbol, timeframe, klines_limit),
                "parser": parser_func_klines,
                "original_timeframe": timeframe
            })
        else:
            logger.error(f"{log_prefix} Не найден get_{exchange}_klines_url или parse_{exchange}_klines для {symbol}")


        # --- 2. OI и FR ---
        for data_type, suffix in [('oi', 'open_interest'), ('fr', 'funding_rate')]:
            
            api_timeframe = _get_api_timeframe(timeframe, data_type, exchange) 
            
            # --- ИЗМЕНЕНИЕ №39: УСЛОВНАЯ ФИЛЬТРАЦИЯ FR ---
            # --- (Задача 2) Эта логика НЕ меняется, она отвечает за фильтрацию ---
            if data_type == 'fr' and exchange == 'binance':
                 # Собираем FR только если Base-TF соответствует интервалам FR Binance
                 if timeframe not in BINANCE_SUPPORTED_FR_PERIODS:
                     logger.debug(f"{log_prefix} Пропускаю FR для {symbol}: Base-TF {timeframe} не совпадает с интервалами Binance FR ({BINANCE_SUPPORTED_FR_PERIODS}).")
                     continue
            # -----------------------------------------------
            
            url_func_name = f"get_{exchange}_{suffix}_url"
            parser_func_name = f"parse_{exchange}_{data_type}"
            
            url_func = getattr(url_builder, url_func_name, None)
            parser_func = getattr(api_parser, parser_func_name, None)
            
            if not url_func or not parser_func:
                msg = f"{log_prefix} Не найден {url_func_name} или {parser_func_name} для {symbol}"
                logger.error(msg)
                continue

            # --- ИСПОЛЬЗУЕМ НОВЫЕ ЛИМИТЫ ---
            limit = oi_limit if data_type == 'oi' else fr_limit
            
            if data_type == 'oi':
                # Передаем символ и api_timeframe (e.g., '1h' или '4h')
                url = url_func(symbol, api_timeframe, limit) 
            elif data_type == 'fr':
                # Funding Rate
                url = url_func(symbol, limit)
                
            tasks.append({
                "symbol": symbol,
                "symbol_api": symbol, 
                "exchange": exchange,
                "data_type": data_type,
                "url": url,
                "parser": parser_func,
                "original_timeframe": timeframe
            })

    logger.info(f"[{timeframe.upper()}] DATA_COLLECTOR: 1/6: Готово. Всего {len(tasks)} задач.")
    return tasks