# alert_tests/test_5_e2e_1h_alerts.py
import httpx
import asyncio
import uuid
import logging
import time
from redis.asyncio import Redis as AsyncRedis
from . import helpers # Импортируем наши хелперы
from typing import Dict, Any, List

# --- НОВЫЙ ИМПОРТ: Цветное логирование ---
GREEN = "\033[92m"
RESET = "\033[0m"
# ------------------------------------------

# Импортируем AlertStorage, чтобы создать "ловушку"
try:
    from alert_manager.storage import AlertStorage
    # Импорт run_alert_checks для симуляции (ИЗМЕНЕНИЕ №9)
    from alert_manager.checker import run_alert_checks
except ImportError:
    logging.critical("НЕ УДАЛОСЬ ИМПОРТИРОВАТЬ ALERT_MANAGER (test_5)")
    # Заглушка, чтобы тест мог упасть с ошибкой
    class AlertStorage:
        def __init__(self, r): pass
        async def add_alert(self, c, a): return False
    # Заглушка run_alert_checks
    async def run_alert_checks(data, storage):
        logging.error("run_alert_checks (ЗАГЛУШКА) вызвана")


TEST_SYMBOL = "BTCUSDT" 

# --- ИЗМЕНЕНИЕ №8: Мокинг-данные (Скопировано из test_1_e2e_lifecycle.py) ---
mock_cache_data = {
    "data": [
        {
            "symbol": TEST_SYMBOL,
            "data": [
                # Одна свеча, которая гарантированно вызовет срабатывание (Low 0.5 < Price 1.0 < High 2.0)
                {
                    "openTime": int(time.time() * 1000),
                    "closeTime": int(time.time() * 1000) + 1000,
                    "openPrice": 1.5,
                    "highPrice": 2.0, 
                    "lowPrice": 0.5,  
                    "closePrice": 1.8,
                    "volume": 1000.0, 
                    "baseVolume": 1000.0,
                    "quoteVolume": 1800.0
                }
            ]
        }
    ]
}
# --- КОНЕЦ ИЗМЕНЕНИЯ №8 ---

# --- ИЗМЕНЕНИЕ №11: Новая функция проверки структуры ---
def _verify_mock_data_structure(log: logging.Logger, data: Dict[str, Any], symbol: str) -> bool:
    """
    Проверяет, что мокинг-данные содержат минимальную структуру для Line Alerts.
    """
    log.info(f"  [ДИАГНОСТИКА] Проверка структуры мокинг-данных...")

    # 1. Проверка корневой структуры
    if 'data' not in data or not isinstance(data['data'], list):
        log.error("  ❌ Ошибка структуры: Отсутствует корневой ключ 'data' или он не является списком.")
        return False
        
    # 2. Проверка наличия символа
    coin_data = next((c for c in data['data'] if c.get('symbol') == symbol), None)
    # --- ИЗМЕНЕНИЕ №10: Диагностика наличия ---
    if not coin_data:
        log.error(f"  ❌ Ошибка структуры: Символ '{symbol}' не найден в списке 'data'.")
        return False

    # 3. Проверка наличия Klines
    klines = coin_data.get('data', [])
    if not klines or not isinstance(klines, list) or len(klines) == 0:
        log.error(f"  ❌ Ошибка структуры: В 'data' для '{symbol}' нет списка Klines.")
        return False

    # 4. Проверка полей Low/High в последней свече (критично для checker.py)
    last_kline = klines[-1]
    required_keys = ["highPrice", "lowPrice"]
    
    missing_keys = [k for k in required_keys if last_kline.get(k) is None]
    
    if missing_keys:
        log.error(f"  ❌ Ошибка структуры: В последней свече '{symbol}' отсутствуют критические поля: {missing_keys}")
        return False

    log.info(f"  [ДИАГНОСТИКА] {GREEN}✅ Структура мокинг-данных корректна.{RESET}")
    return True
# --- КОНЕЦ ИЗМЕНЕНИЯ №11 ---


# --- ИЗМЕНЕНО: Теперь возвращает int (creationTime) (ИЗМЕНЕНИЕ №1, №4, №6, №7) ---
async def _setup_test_alert(redis_conn: AsyncRedis, log: logging.Logger) -> int:
    """
    Вручную создает Alert (ловушку) в Redis (в 'working'),
    который должен 100% сработать.
    """
    
    current_time_ms = int(time.time() * 1000)
    test_alert_id = str(uuid.uuid4())
    
    # --- ИЗМЕНЕНИЕ №7: Добавлено цветное логирование ---
    log.info(f"[Тест 1h] Шаг 1: Создание алерта-ловушки {test_alert_id} ({GREEN}BTC > 1.0${RESET}) в Redis...")
    
    storage = AlertStorage(redis_conn)
    
    test_alert = {
        "id": test_alert_id,
        "symbol": TEST_SYMBOL,
        "alertName": f"E2E 1h Test Alert",
        "action": "cross",
        # --- ИЗМЕНЕНИЕ №6: Возвращение к цене 1.0 (Гарантированное срабатывание в моке) ---
        "price": 1.0, 
        "isActive": True,
        "status": "new",
        "creationTime": current_time_ms
    }
    
    try:
        success = await storage.add_alert("working", test_alert)
        if not success:
            log.error(f"  ❌ Ошибка: AlertStorage.add_alert() вернул False")
            raise RuntimeError("AlertStorage.add_alert() вернул False")
        
        # Прямая проверка
        is_in_working = await redis_conn.sismember("index:line:working", test_alert_id)
        if not is_in_working:
            log.error(f"  ❌ Ошибка: Тестовый алерт {test_alert_id} не найден в 'index:line:working'")
            raise AssertionError("Тестовый алерт не появился в 'index:line:working'")
        
        log.info(f"       ✅ [OK] Redis: Алерт-ловушка создан в 'working'. (ID: {test_alert_id})")
        return current_time_ms
        
    except Exception as e:
        log.error(f"💥 [FAIL] Не удалось создать алерт-ловушку: {e}", exc_info=True)
        return 0 

# --- ИЗМЕНЕНО: Новая сигнатура и логика поиска (ИЗМЕНЕНИЕ №3) ---
async def _check_alert_triggered(redis_conn: AsyncRedis, log: logging.Logger, alert_creation_time: int) -> bool:
    """
    Проверяет, что алерт был перемещен (или скопирован) в 'triggered'
    идентифицируя его по уникальному creationTime.
    """
    log.info(f"[Тест 1h] Шаг 3: Проверка, что алерт (creationTime: {alert_creation_time}) появился в 'index:line:triggered'...")
    
    try:
        storage = AlertStorage(redis_conn)
        triggered_alerts = await storage.get_alerts("triggered")
        
        if not triggered_alerts:
             raise AssertionError("Алерт НЕ сработал. 'index:line:triggered' пуст.")
        
        # Ищем наш алерт по уникальному creationTime
        found = False
        for alert in triggered_alerts:
            if alert.get("creationTime") == alert_creation_time: 
                found = True
                break
        
        if not found:
            log.warning(f"  ⚠️ Найденные creationTime: {[a.get('creationTime') for a in triggered_alerts]}")
            raise AssertionError(f"Алерт сработал, но алерт с creationTime {alert_creation_time} не найден в 'triggered'.")
       
        log.info(f"       ✅ [OK] Redis: Алерт-ловушка успешно найден в 'triggered'. (CreationTime: {alert_creation_time})")
        return True
        
    except Exception as e:
        log.error(f"💥 [FAIL] Ошибка при проверке 'triggered': {e}", exc_info=True)
        return False


async def run_1h_alert_scenario(client: httpx.AsyncClient, redis_conn: AsyncRedis, log: logging.Logger):
    """
    Сценарий 5: E2E 1h Alert Flow (СИМУЛЯЦИЯ)
    """
    log.info("="*60)
    log.info("--- 🔬 [Сценарий 5] E2E 1h Alert Flow (СИМУЛЯЦИЯ): Начинаю ---")
    
    try:
        # --- Шаг 1: Создание Алерта-ловушки (в Redis) ---
        creation_time = await _setup_test_alert(redis_conn, log) 
        if creation_time == 0:
            return False 

        # --- ИЗМЕНЕНИЕ №11: Проверка структуры мокинг-данных ---
        if not _verify_mock_data_structure(log, mock_cache_data, TEST_SYMBOL):
            log.error(f"💥 [FAIL] Структура мокинг-данных не прошла валидацию.")
            return False
        # ---------------------------------------------------

        # --- ИЗМЕНЕНИЕ №10: Диагностика наличия BTCUSDT ---
        is_symbol_present = any(coin.get('symbol') == TEST_SYMBOL for coin in mock_cache_data.get('data', []))
        if is_symbol_present:
            log.info(f"  [ДИАГНОСТИКА] {GREEN}✅ {TEST_SYMBOL} найден{RESET} в мокинг-данных. Переход к проверке алертов.")
        else:
            log.error(f"  [ДИАГНОСТИКА] 💥 {TEST_SYMBOL} НЕ найден в мокинг-данных. СИМУЛЯЦИЯ ПРОВАЛЕНА.")
            return False
        # ---------------------------------------------------
        
        # --- Шаг 2: Симуляция (ИЗМЕНЕНИЕ №9) ---
        storage_instance = AlertStorage(redis_conn)
        
        log.info(f"[Тест 1h] Шаг 2: СИМУЛЯЦИЯ. Напрямую вызываю run_alert_checks с поддельными Klines...")
        await run_alert_checks(mock_cache_data, storage_instance) 
        log.info("       ✅ [OK] Симуляция run_alert_checks завершена.")
        # --- КОНЕЦ ИЗМЕНЕНИЯ №9 ---

        # --- Шаг 3: Проверка Redis (Прямое чтение) ---
        if not await _check_alert_triggered(redis_conn, log, creation_time): 
            return False 
            
        # --- Шаг 4: Проверка Telegram (Визуальная) ---
        log.info("="*50)
        log.info("--- 🔔 [Тест 1h] ПОЖАЛУЙСТА, ПРОВЕРЬТЕ TELEGRAM! 🔔 ---")
        log.info(f"Вы должны были получить сообщение о срабатывании 'E2E 1h Test Alert'.")
        log.info("="*50)

        log.info("--- ✅ [Сценарий 5] E2E 1h Alert Flow (СИМУЛЯЦИЯ): УСПЕХ ---")
        log.info("="*60)
        return True

    except Exception as e:
        log.error(f"💥 [FAIL] [Сценарий 5] Тест провален (Критическая ошибка): {e}", exc_info=True)
        log.info("="*60)
        return False