# alert_manager/checker.py
import logging
import uuid
from typing import List, Dict, Optional, Any
from datetime import datetime
import pytz 

from alert_manager.model import (
    Alert, VwapAlert, KlineData, AlertsCollection,
)
# --- ИЗМЕНЕНИЕ: Замена относительного импорта на абсолютный ---
from alert_manager.storage import AlertStorage

# Импортируем (асинхронный) модуль отправки
# --- ИЗМЕНЕНИЕ: Замена относительного импорта на абсолютный ---
from alert_manager import telegram_sender 
# ---------------------------------------------------------

logger = logging.getLogger(__name__)

# --- Вспомогательные функции (без изменений) ---

def _unix_to_time_str(unix_ms: int) -> str:
    dt_utc = datetime.fromtimestamp(unix_ms / 1000, tz=pytz.utc)
    dt_target_tz = dt_utc.astimezone(pytz.FixedOffset(180)) # UTC+3
    return dt_target_tz.strftime('%H:%M:%S')

# --- 🚀 ИЗМЕНЕНИЕ: Добавляем приведение типов ---
def _check_line_alerts(
    klines_map: Dict[str, List[KlineData]],
    alerts: List[Alert]
) -> List[Alert]:
    matched_alerts: List[Alert] = []
    for alert in alerts:
        symbol = alert.get("symbol")
        alert_price_raw = alert.get("price") # 🚀
        if not symbol or alert_price_raw is None or symbol not in klines_map: # 🚀 (проверка на None)
            continue
        kline_list = klines_map[symbol]
        if not kline_list:
            continue
        last_kline = kline_list[-1] 
        kline_low_raw = last_kline.get("lowPrice") # 🚀
        kline_high_raw = last_kline.get("highPrice") # 🚀
        if kline_low_raw is None or kline_high_raw is None: # 🚀 (Проверка на None)
            continue
            
        try:
            # 🚀 Принудительное приведение к float
            alert_price = float(alert_price_raw)
            kline_low = float(kline_low_raw)
            kline_high = float(kline_high_raw)
        except (ValueError, TypeError):
            continue # Не можем сравнить, если не числа
        
        if kline_low <= alert_price <= kline_high:
            # --- (Логика создания НОВОГО ID - без изменений, она верная) ---
            activation_time = int(datetime.now(pytz.utc).timestamp() * 1000)
            matched_alert: Alert = {
                **alert, 
                "_id": None, 
                "id": str(uuid.uuid4()), 
                "activationTime": activation_time,
                "activationTimeStr": _unix_to_time_str(activation_time),
                "high": kline_high,
                "low": kline_low,
                "status": "triggered" 
            }
            matched_alerts.append(matched_alert)
    return matched_alerts
# --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---


def _calculate_vwap(klines: List[KlineData]) -> float:
    # (Код без изменений)
    cumulative_price_volume = 0
    cumulative_volume = 0
    for kline in klines:
        try:
            typical_price = (kline["highPrice"] + kline["lowPrice"] + kline["closePrice"]) / 3
            price_volume = typical_price * kline["volume"]
            cumulative_price_volume += price_volume
            cumulative_volume += kline["volume"]
        except (TypeError, KeyError):
            continue
    if cumulative_volume == 0:
        return 0.0
    return cumulative_price_volume / cumulative_volume

def _check_vwap_alerts(
    klines_map: Dict[str, List[KlineData]],
    alerts: List[VwapAlert]
) -> List[VwapAlert]:
    # (Код без изменений)
    triggered_alerts: List[VwapAlert] = []
    for vwap_alert in alerts:
        # ... (логика vwap)
        symbol = vwap_alert.get("symbol")
        anchor_time = vwap_alert.get("anchorTime")
        if not symbol or not anchor_time or symbol not in klines_map:
            continue
        kline_data = klines_map[symbol]
        if not kline_data:
            continue
        last_kline = kline_data[-1]
        last_kline_open_time = last_kline.get("openTime")
        if not last_kline_open_time:
            continue
        filtered_klines = [
            kline for kline in kline_data 
            if kline.get("openTime", 0) >= anchor_time and kline.get("openTime", 0) <= last_kline_open_time
        ]
        if not filtered_klines:
            continue
        vwap = _calculate_vwap(filtered_klines)
        if vwap == 0.0:
            continue
        kline_low_raw = last_kline.get("lowPrice") # 🚀
        kline_high_raw = last_kline.get("highPrice") # 🚀
        
        if not kline_low_raw or not kline_high_raw: # 🚀 (Проверка на None или пустую строку)
            continue
        try:
            # 🚀 Принудительное приведение к float
            kline_low = float(kline_low_raw)
            kline_high = float(kline_high_raw)
        except (ValueError, TypeError):
            continue # Не можем сравнить, если не числа
        if kline_low < vwap < kline_high: # 🚀 (Теперь тут числа)
            activation_time = int(datetime.now(pytz.utc).timestamp() * 1000)
            triggered_vwap: VwapAlert = {
                **vwap_alert,
                "_id": None,
                "id": str(uuid.uuid4()),
                "activationTime": activation_time,
                "activationTimeStr": _unix_to_time_str(activation_time),
                "high": kline_high, # 🚀 (Сохраняем как число)
                "low": kline_low, # 🚀 (Сохраняем как число)
                "anchorPrice": vwap, 
                "price": vwap, 
                "status": "triggered"
            }
            triggered_alerts.append(triggered_vwap)
    return triggered_alerts


async def run_alert_checks(
    cache_data: Dict[str, Any], 
    storage: AlertStorage
):
    """
    (Код без изменений)
    """
    logger.info("[ALERT_CHECKER] Запуск проверки алертов для 1h...")
    
    klines_map: Dict[str, List[KlineData]] = {
        coin.get("symbol"): coin.get("data", [])
        for coin in cache_data.get("data", [])
        if coin.get("symbol")
    }
    
    if not klines_map:
        logger.warning("[ALERT_CHECKER] Данные 1h Klines пусты. Проверка алертов пропущена.")
        return

    # 2. Проверка Line Alerts
    try:
        working_line_alerts = await storage.get_alerts("working")
        active_line_alerts = [a for a in working_line_alerts if a.get("isActive", False)]
        
        if active_line_alerts:
            matched_line_alerts = _check_line_alerts(klines_map, active_line_alerts)
            if matched_line_alerts:
                logger.info(f"[ALERT_CHECKER] Сработало {len(matched_line_alerts)} Line Alert(s).")
                for alert in matched_line_alerts:
                    await storage.add_alert("triggered", alert)
                
                await telegram_sender.send_triggered_alerts_report(matched_line_alerts)
            else:
                logger.info("[ALERT_CHECKER] Совпадений по Line Alerts не найдено.")
    except Exception as e:
        logger.error(f"[ALERT_CHECKER] Ошибка при проверке Line Alerts: {e}", exc_info=True)

    # 3. Проверка VWAP Alerts
    try:
        working_vwap_alerts = await storage.get_vwap_alerts("working")
        active_vwap_alerts = [a for a in working_vwap_alerts if a.get("isActive", False)]
        
        if active_vwap_alerts:
            matched_vwap_alerts = _check_vwap_alerts(klines_map, active_vwap_alerts)
            if matched_vwap_alerts:
                logger.info(f"[ALERT_CHECKER] Сработало {len(matched_vwap_alerts)} VWAP Alert(s).")
                for alert in matched_vwap_alerts:
                    await storage.add_vwap_alert("triggered", alert)
                
                await telegram_sender.send_triggered_vwap_alerts_report(matched_vwap_alerts)
            else:
                logger.info("[ALERT_CHECKER] Совпадений по VWAP Alerts не найдено.")
    except Exception as e:
        logger.error(f"[ALERT_CHECKER] Ошибка при проверке VWAP Alerts: {e}", exc_info=True)