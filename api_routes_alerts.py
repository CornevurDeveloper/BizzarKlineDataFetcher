# api_routes_alerts.py
"""
(Описание модуля без изменений)
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security

from redis.asyncio import Redis as AsyncRedis

from alert_manager.storage import AlertStorage
from alert_manager.model import (
    Alert, VwapAlert, AlertBase, AlertsCollection,
)
from cache_manager import get_redis_connection
# --- 🚀 ИЗМЕНЕНИЕ: 'get_coins' больше не нужен ---
# from data_collector.coin_source import get_coins 
# --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

# (Импорт verify_cron_secret без изменений)
try:
    from api_routes import verify_cron_secret
except ImportError:
    try:
        from api_routes import verify_cron_secret
    except ImportError:
        def verify_cron_secret():
            return True

logger = logging.getLogger(__name__)
router = APIRouter()

# (get_alert_storage без изменений)
async def get_alert_storage(redis: AsyncRedis = Depends(get_redis_connection)) -> AlertStorage:
    if not redis:
        raise HTTPException(status_code=503, detail="Не удалось подключиться к Redis для AlertStorage")
    return AlertStorage(redis)

# (GET эндпоинты без изменений)
@router.get("/alerts", response_model=List[Alert])
async def get_alerts_controller(
    collectionName: AlertsCollection = Query(..., description="Имя коллекции"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    return await storage.get_alerts(collectionName)

@router.get("/alerts/symbol", response_model=List[Alert])
async def get_alerts_by_symbol_controller(
    symbol: str = Query(..., description="Символ"),
    collectionName: AlertsCollection = Query(..., description="Имя коллекции"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    all_alerts = await storage.get_alerts(collectionName)
    return [alert for alert in all_alerts if alert.get("symbol") == symbol]

@router.post("/alerts/add/one", status_code=201)
async def add_alert_controller(
    payload: Request,
    collectionName: AlertsCollection = Query(..., description="Имя коллекции"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    try:
        body = await payload.json()
        alert_data = body.get("alert")
        if not alert_data:
            raise HTTPException(status_code=400, detail="Нет ключа 'alert'")
        
        if 'id' not in alert_data: alert_data['id'] = str(uuid.uuid4())
        
        alert: Alert = alert_data
        success = await storage.add_alert(collectionName, alert)
        if success: return {"message": "Alert added successfully!"}
        else: raise HTTPException(status_code=500, detail="Failed to add alert.")
    except Exception as e:
        logger.error(f"Ошибка add_alert_controller: {e}", exc_info=True)
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/alerts/add/many", status_code=201)
async def add_alerts_batch_controller(
    payload: Request, 
    collectionName: AlertsCollection = Query(..., description="Имя коллекции"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    """
    (ИЗМЕНЕНО) Пакетное добавление. Логика 'get_coins()' удалена
    для соответствия 'add/one' и Deno.
    """
    try:
        body = await payload.json()
        alertBases: List[AlertBase] = body.get("alerts") 
        if not alertBases:
             raise HTTPException(status_code=400, detail="Нет ключа 'alerts' или список пуст.")

        # --- 🚀 ИЗМЕНЕНИЕ: Логика 'get_coins' и фильтрации УДАЛЕНА ---
        
        new_alerts: List[Alert] = []
        
        for base in alertBases:
            # Создаем полный объект Alert из AlertBase
            new_alert: Alert = {
                **base,
                "isActive": True,
                "status": "new",
                "id": str(uuid.uuid4()),
                "creationTime": int(datetime.now().timestamp() * 1000),
                "description": base.get("description", "Yet nothing to say")
            }
            new_alerts.append(new_alert)
        # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---

        if not new_alerts:
             raise HTTPException(status_code=400, detail="Не получено алертов для добавления.")

        for alert in new_alerts:
            await storage.add_alert(collectionName, alert)

        return {
            "success": True,
            "message": f"Alerts added: {len(new_alerts)}. Rejected: 0",
            "alerts": new_alerts,
            "rejected_symbols": []
        }

    except Exception as e:
        logger.error(f"Ошибка в add_alerts_batch_controller: {e}", exc_info=True)
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=500, detail="Internal server error")

# (Остальные эндпоинты: update, delete, move, vwap - без изменений)
@router.put("/alerts/update/one")
async def update_alert_controller(payload: Request, collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        filter_data = body.get("filter")
        update_data = body.get("updatedData")
        if not filter_data or not update_data: raise HTTPException(status_code=400, detail="Нужны 'filter' и 'updatedData'")
        all_alerts = await storage.get_alerts(collectionName)
        found_alert = next((a for a in all_alerts if all(a.get(k) == v for k,v in filter_data.items())), None)
        if not found_alert: raise HTTPException(status_code=404, detail="Alert not found")
        await storage.update_alert_by_id(found_alert['id'], {**found_alert, **update_data})
        return {"message": "Alert updated successfully!"}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Update error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@router.delete("/alerts/delete/many")
async def delete_many_controller(payload: Request, collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        ids = body.get("ids")
        if not ids: raise HTTPException(status_code=400, detail="Нужен 'ids'")
        await storage.delete_alerts_by_id(collectionName, ids)
        return {"message": "Alerts deleted"}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@router.post("/alerts/move/many")
async def move_many_controller(payload: Request, sourceCollection: AlertsCollection = Query(...), targetCollection: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        ids = body.get("ids")
        if not ids: raise HTTPException(status_code=400, detail="Нужен 'ids'")
        await storage.move_alerts_by_id(sourceCollection, targetCollection, ids)
        return {"message": f"Moved {len(ids)} alerts", "count": len(ids)}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Move error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

# --- VWAP Alerts (Кратко, без изменений логики) ---
@router.get("/vwap-alerts", response_model=List[VwapAlert])
async def get_vwap_alerts_controller(collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    return await storage.get_vwap_alerts(collectionName)

@router.get("/vwap-alerts/symbol", response_model=List[VwapAlert])
async def get_vwap_alerts_by_symbol_controller(symbol: str = Query(...), collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    all_alerts = await storage.get_vwap_alerts(collectionName)
    return [a for a in all_alerts if a.get("symbol") == symbol]

@router.post("/vwap-alerts/add/one", status_code=201)
async def add_vwap_alert_controller(payload: Request, collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        alert_data = body.get("alert")
        if not alert_data: raise HTTPException(status_code=400, detail="Нет 'alert'")
        if 'id' not in alert_data: alert_data['id'] = str(uuid.uuid4())
        if 'creationTime' not in alert_data: alert_data['creationTime'] = int(datetime.now().timestamp()*1000)
        await storage.add_vwap_alert(collectionName, alert_data)
        return {"message": "VwapAlert added"}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Add VWAP error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@router.put("/vwap-alerts/update/one")
async def update_vwap_alert_controller(payload: Request, collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        filter_data = body.get("filter")
        update_data = body.get("updatedData")
        if not filter_data or not update_data: raise HTTPException(status_code=400, detail="Missing filter/data")
        all_alerts = await storage.get_vwap_alerts(collectionName)
        found = next((a for a in all_alerts if all(a.get(k) == v for k,v in filter_data.items())), None)
        if not found: raise HTTPException(status_code=404, detail="Not found")
        await storage.update_vwap_alert_by_id(found['id'], {**found, **update_data})
        return {"message": "Updated"}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Update VWAP error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@router.delete("/vwap-alerts/delete/many")
async def delete_many_vwap_controller(payload: Request, collectionName: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        ids = body.get("ids")
        if not ids: raise HTTPException(status_code=400, detail="Missing ids")
        await storage.delete_vwap_alerts_by_id(collectionName, ids)
        return {"message": "Deleted"}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Delete VWAP error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

@router.post("/vwap-alerts/move/many")
async def move_many_vwap_controller(payload: Request, sourceCollection: AlertsCollection = Query(...), targetCollection: AlertsCollection = Query(...), storage: AlertStorage = Depends(get_alert_storage)):
    try:
        body = await payload.json()
        ids = body.get("ids")
        if not ids: raise HTTPException(status_code=400, detail="Missing ids")
        await storage.move_vwap_alerts_by_id(sourceCollection, targetCollection, ids)
        return {"message": f"Moved {len(ids)} alerts", "count": len(ids)}
    except Exception as e:
        if isinstance(e, HTTPException): raise
        logger.error(f"Move VWAP error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

# (Cleanup - без изменений)
@router.post("/alerts/internal/cleanup-triggered", status_code=200)
async def cleanup_triggered_alerts(payload: Request, storage: AlertStorage = Depends(get_alert_storage), is_authenticated: bool = Depends(verify_cron_secret)):
    try:
        body = await payload.json()
        hours = body.get("hours")
        if not hours or not isinstance(hours, int) or hours <= 0:
            raise HTTPException(status_code=400, detail="Invalid 'hours'")
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        logger.info(f"[CLEANUP] Cleaning older than {hours}h ({cutoff})...")
        del_line = await storage.cleanup_line_alerts_older_than("triggered", cutoff_ms)
        del_vwap = await storage.cleanup_vwap_alerts_older_than("triggered", cutoff_ms)
        total = del_line + del_vwap
        msg = f"Deleted Line: {del_line}. Deleted VWAP: {del_vwap}. Total: {total}."
        logger.info(f"[CLEANUP] {msg}")
        return {"message": msg, "deleted_line_count": del_line, "deleted_vwap_count": del_vwap, "total_deleted": total}
    except Exception as e:
        logger.error(f"Cleanup error: {e}", exc_info=True)
        if isinstance(e, HTTPException): raise
        raise HTTPException(status_code=500, detail="Internal error")

# --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ: Новый эндпоинт ---
@router.get("/alerts/check-name", response_model=Dict[str, bool])
async def check_alert_name_uniqueness(
    name: str = Query(..., description="Имя алерта для проверки"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    """
    Проверяет, существует ли Line Alert с таким 'alertName'
    в 'working' коллекции.
    """
    try:
        working_alerts = await storage.get_alerts("working")
        
        # Ищем совпадение (без учета регистра для надежности)
        name_lower = name.lower()
        is_duplicate = any(
            alert.get("alertName", "").lower() == name_lower
            for alert in working_alerts
        )
        
        return {"isUnique": not is_duplicate}
        
    except Exception as e:
        logger.error(f"Ошибка в check_alert_name_uniqueness: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
        
@router.get("/vwap-alerts/check-name", response_model=Dict[str, bool])
async def check_vwap_alert_name_uniqueness(
    name: str = Query(..., description="Имя VWAP алерта для проверки"),
    storage: AlertStorage = Depends(get_alert_storage)
):
    """
    (НОВЫЙ) Проверяет, существует ли VWAP Alert с таким 'alertName'
    в 'working' коллекции.
    """
    try:
        working_alerts = await storage.get_vwap_alerts("working")
        
        # Ищем совпадение (без учета регистра для надежности)
        name_lower = name.lower()
        is_duplicate = any(
            alert.get("alertName", "").lower() == name_lower
            for alert in working_alerts
        )
        
        return {"isUnique": not is_duplicate}
        
    except Exception as e:
        logger.error(f"Ошибка в check_vwap_alert_name_uniqueness: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
# --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---