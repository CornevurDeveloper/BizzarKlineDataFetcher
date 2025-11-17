# alert_manager/model.py
"""
Этот модуль воссоздает модели данных (интерфейсы) из Deno-проекта,
используя Python TypedDict для строгой типизации.
"""
from typing import List, Optional, Literal
from typing_extensions import TypedDict

# --- Общие ---

class Coin(TypedDict, total=False):
    """
    (Код без изменений)
    """
    symbol: str
    category: str
    exchanges: List[str]
    imageUrl: str
    isAtWork: Optional[bool]

class KlineData(TypedDict, total=False):
    """
    (Код без изменений)
    """
    symbol: str
    category: str
    exchanges: List[str]
    imageUrl: str
    openTime: int
    closeTime: int
    openPrice: float
    highPrice: float
    closePrice: float
    lowPrice: float
    volume: float # Deno: baseVolume
    

# --- Line Alerts ---

class AlertBase(TypedDict, total=False):
    """
    (Код без изменений)
    """
    symbol: str
    alertName: str
    action: str
    price: float
    description: Optional[str]
    tvScreensUrls: Optional[List[str]]

class Alert(AlertBase, total=False):
    """
    (Код без изменений)
    """
    _id: Optional[str] # Mongo ID
    id: str # UUID
    creationTime: Optional[int]
    activationTime: Optional[int]
    activationTimeStr: Optional[str]
    high: Optional[float] # Deno: high
    low: Optional[float] # Deno: low
    isActive: bool
    status: str
    tvLink: Optional[str]
    cgLink: Optional[str]

# --- VWAP Alerts ---

class VwapAlert(TypedDict, total=False):
    """
    Полная модель VWAP Alert, основанная на vwap-alert.ts
    """
    _id: Optional[str] # Mongo ID
    id: str # UUID
    creationTime: Optional[int]
    activationTime: Optional[int]
    activationTimeStr: Optional[str]
    price: Optional[float] # Цена срабатывания (VWAP)
    high: Optional[float] # Deno: high
    low: Optional[float] # Deno: low
    tvScreensUrls: Optional[List[str]]
    isActive: bool
    symbol: str
    
    # --- 🚀 НАЧАЛО ИЗМЕНЕНИЯ ---
    alertName: Optional[str] # <-- Добавлено по аналогии с Alert
    # --- 🚀 КОНЕЦ ИЗМЕНЕНИЯ ---
    
    category: Optional[str]
    tvLink: Optional[str]
    cgLink: Optional[str]
    exchanges: Optional[List[str]]
    imageUrl: Optional[str]
    anchorTime: Optional[int] # Время "якоря"
    anchorPrice: Optional[float] # Рассчитанный VWAP
    anchorTimeStr: Optional[str]


# --- Коллекции ---
# (Код без изменений)
AlertsCollection = Literal["triggered", "archived", "working"]

# --- Ключи Redis ---
# (Код без изменений)
ALERTS_WORKING_KEY = "alerts:working"
ALERTS_TRIGGERED_KEY = "alerts:triggered"
ALERTS_ARCHIVED_KEY = "alerts:archived"
VWAP_ALERTS_WORKING_KEY = "vwap_alerts:working"
VWAP_ALERTS_TRIGGERED_KEY = "vwap_alerts:triggered"
VWAP_ALERTS_ARCHIVED_KEY = "vwap_alerts:archived"