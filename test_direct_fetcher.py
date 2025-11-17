# test_direct_fetcher.py
# (Этот файл должен находиться в корневой папке проекта "Эталон")

import httpx
import asyncio
import os
import sys
import gzip
import json
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# --- 1. Настройка ---
load_dotenv()
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
CLIENT_TIMEOUT_SECONDS = 600.0

# Константы для таймфреймов
TIMEFRAMES_WITH_FR = ['4h', '8h']
TIMEFRAMES_WITHOUT_FR = ['1h', '12h', '1d']
ALL_TIMEFRAMES = TIMEFRAMES_WITH_FR + TIMEFRAMES_WITHOUT_FR

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - (TEST_DIRECT_FETCHER) - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("TEST_DIRECT_FETCHER")

# --- 2. Хелпер Валидации ---

def validate_direct_response(response: httpx.Response, timeframe: str) -> bool:
    """
    Проверяет ответ от /get-market-data/direct.
    Проверяет статус, GZIP, структуру JSON и кастомные правила FR.
    Возвращает True при успехе, False при ошибке.
    """
    log.info(f"--- Валидация ответа для {timeframe} ---")

    # 1. Проверка Статуса
    if response.status_code != 200:
        log.error(f"💥 [FAIL] Ожидался статус 200, получен {response.status_code}. Тело: {response.text}")
        return False
        
    log.info("✅ Статус 200 OK.")

    # 2. Распаковка (умная проверка GZIP)
    try:
        # Проверяем GZIP по магическим байтам (первые 2 байта: 0x1f 0x8b)
        if response.content[:2] == b'\x1f\x8b':
            data = json.loads(gzip.decompress(response.content))
            log.info("✅ Данные были сжаты GZIP и успешно распакованы.")
        else:
            # Это обычный JSON (не сжатый)
            data = json.loads(response.content)
            # Проверяем, врёт ли сервер о GZIP
            if response.headers.get('content-encoding') == 'gzip':
                log.warning("⚠️  ВНИМАНИЕ: Заголовок 'content-encoding: gzip' присутствует, но данные НЕ сжаты!")
            else:
                log.info("✅ Данные получены в виде обычного JSON (без сжатия).")
                
    except json.JSONDecodeError as e:
        log.error(f"💥 [FAIL] Не удалось распарсить JSON: {e}")
        return False
    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при обработке ответа: {e}")
        return False

    # 3. Проверка Корневой Структуры
    required_root_keys = ['openTime', 'closeTime', 'timeframe', 'audit', 'data']
    missing_keys = [k for k in required_root_keys if k not in data]
    
    if missing_keys:
        log.error(f"💥 [FAIL] Отсутствуют ключи в корне JSON: {missing_keys}")
        return False
        
    if data['timeframe'] != timeframe:
        log.error(f"💥 [FAIL] Timeframe в ответе ('{data['timeframe']}') != запрошенному ('{timeframe}').")
        return False
        
    log.info("✅ Корневая структура JSON подтверждена.")

    # 4. Проверка Структуры Монеты
    data_list = data.get('data')
    if not isinstance(data_list, list):
        log.error(f"💥 [FAIL] 'data' не является списком.")
        return False
        
    if not data_list:
        log.error("💥 [FAIL] Список 'data' (монеты) пуст.")
        return False
    
    coin_obj = data_list[0]
    required_coin_keys = ['symbol', 'exchanges', 'data']
    missing_coin_keys = [k for k in required_coin_keys if k not in coin_obj]
    
    if missing_coin_keys:
        log.error(f"💥 [FAIL] Объект монеты не содержит ключи: {missing_coin_keys}")
        return False
        
    log.info("✅ Структура объекта монеты подтверждена.")

    # 5. Проверка Структуры Свечи
    candle_list = coin_obj.get('data')
    if not isinstance(candle_list, list):
        log.error("💥 [FAIL] 'data' внутри монеты не является списком.")
        return False
        
    if not candle_list:
        log.error("💥 [FAIL] Список свечей пуст.")
        return False
    
    # Проверяем последнюю свечу (самая актуальная)
    candle = candle_list[-1]
    required_candle_keys = [
        'openTime', 'closeTime', 'openPrice', 'highPrice', 
        'lowPrice', 'closePrice', 'volume', 'volumeDelta', 'openInterest'
    ]
    missing_candle_keys = [k for k in required_candle_keys if k not in candle]
    
    if missing_candle_keys:
        log.error(f"💥 [FAIL] Свеча не содержит ключи: {missing_candle_keys}")
        return False
        
    log.info("✅ Ключи свечи (Klines + OI + VolumeDelta) подтверждены.")

    # 6. Кастомная Проверка Бизнес-Логики (Funding Rate)
    if timeframe in TIMEFRAMES_WITH_FR:
        if 'fundingRate' not in candle:
            log.error(f"💥 [FAIL] 'fundingRate' ДОЛЖЕН БЫТЬ для {timeframe}, но отсутствует.")
            return False
        log.info(f"✅ 'fundingRate' корректно ПРИСУТСТВУЕТ для {timeframe}.")
    
    elif timeframe in TIMEFRAMES_WITHOUT_FR:
        if 'fundingRate' in candle:
            log.error(f"💥 [FAIL] 'fundingRate' НЕ ДОЛЖЕН БЫТЬ для {timeframe}, но присутствует.")
            return False
        log.info(f"✅ 'fundingRate' корректно ОТСУТСТВУЕТ для {timeframe}.")
        
    log.info(f"--- ✅ Валидация {timeframe} УСПЕШНА ---")
    return True


async def run_test_for_timeframe(timeframe: str) -> bool:
    """
    Выполняет один тестовый запуск для указанного таймфрейма.
    """
    fr_rule = "Klines + OI + FR" if timeframe in TIMEFRAMES_WITH_FR else "Klines + OI"
        
    log.info(f"\n{'='*60}")
    log.info(f"🔥 [ТЕСТ] Запуск {timeframe} (Ожидаю: {fr_rule})")
    log.info(f"{'='*60}")
    log.warning(f"⏳ Ожидайте, запрос может занять 60-90+ секунд...")
    
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=CLIENT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "/get-market-data/direct", 
                json={"timeframes": [timeframe]}
            )
        
        is_valid = validate_direct_response(response, timeframe)
        
        if is_valid:
            log.info(f"🎉 [УСПЕХ] Тест {timeframe} пройден.\n")
            return True
        else:
            log.error(f"❌ [ПРОВАЛ] Тест {timeframe} не пройден.\n")
            return False
            
    except httpx.ConnectError as e:
        log.critical(f"💥 [ПРОВАЛ] Не удалось подключиться к {BASE_URL}. Сервер запущен?")
        log.error(str(e))
        return False
    except httpx.TimeoutException:
        log.critical(f"💥 [ПРОВАЛ] Превышен таймаут {CLIENT_TIMEOUT_SECONDS}с для {timeframe}")
        return False
    except Exception as e:
        log.critical(f"💥 [ПРОВАЛ] Критическая ошибка во время теста {timeframe}: {e}", exc_info=True)
        return False

# --- 3. Главная функция ---

async def main():
    """
    Главный E2E тест.
    """
    log.info("\n" + "="*60)
    log.info("🚀 ЗАПУСК E2E ТЕСТА ДЛЯ ЭНДПОИНТА /get-market-data/direct")
    log.info("="*60)
    log.info(f"BASE_URL: {BASE_URL}")
    log.info(f"Таймфреймы с FR: {TIMEFRAMES_WITH_FR}")
    log.info(f"Таймфреймы без FR: {TIMEFRAMES_WITHOUT_FR}")
    log.info("="*60 + "\n")
    
    results = {}
    
    # Последовательно запускаем все тесты
    for timeframe in ALL_TIMEFRAMES:
        results[timeframe] = await run_test_for_timeframe(timeframe)
    
    # Итоговый отчёт
    log.info("\n" + "="*60)
    log.info("📊 ИТОГОВЫЙ ОТЧЁТ")
    log.info("="*60)
    
    for timeframe, passed in results.items():
        status = "✅ УСПЕХ" if passed else "❌ ПРОВАЛ"
        log.info(f"{timeframe:>4} : {status}")
    
    log.info("="*60)
    
    all_passed = all(results.values())
    passed_count = sum(results.values())
    total_count = len(results)
    
    if all_passed:
        log.info(f"🏆 ВСЕ ТЕСТЫ ПРОЙДЕНЫ ({passed_count}/{total_count})")
        log.info("="*60 + "\n")
    else:
        log.error(f"💥 ПРОВАЛЕНО ТЕСТОВ: {total_count - passed_count}/{total_count}")
        log.info("="*60 + "\n")
        sys.exit(1)


if __name__ == "__main__":
    print("🚀 СКРИПТ СТАРТОВАЛ")
    print(f"Python: {sys.version}")
    print(f"BASE_URL: {BASE_URL}\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("\n⚠️  Тест прерван вручную (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        log.critical(f"💥 КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)