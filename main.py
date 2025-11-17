# main.py
import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import asyncio
import os 
import importlib 
import sys # <-- ДОБАВЛЕН ДЛЯ sys.path

# --- ДОБАВЛЕНО: Исправление пути для поиска модулей в корне (url_builder, api_parser) ---
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
# ---------------------------------------------------------------------------------------

# --- 1. Настройка логгирования ---
try:
    from data_collector.logging_setup import setup_logging
    setup_logging()
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logger = logging.getLogger(__name__)
    # --- ИСПРАВЛЕНО ---
    logger.warning("Не удалось импортировать logging_setup. Используется базовый конфиг.")
    # -------------------

logger = logging.getLogger(__name__)

# --- 2. Импорт Воркера и Роутера ---
import api_routes
import api_routes_alerts # <-- 🚀 ИЗМЕНЕНИЕ (Миграция Алертов)
# -----------------------------------

# --- ИСПРАВЛЕНИЕ: ПРИНУДИТЕЛЬНАЯ ПЕРЕЗАГРУЗКА ---
importlib.reload(api_routes)
importlib.reload(api_routes_alerts) # <-- 🚀 ИЗМЕНЕНИЕ (Миграция Алертов)
api_router = api_routes.router
alerts_router = api_routes_alerts.router # <-- 🚀 ИЗМЕНЕНИЕ (Миграция Алертов)
# -----------------------------------------------

# --- 3. Обработчик Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan обработчик для событий startup и shutdown.
    """
    
    logger.info("=======================================================")
    logger.info("🚀 [STARTUP] FastAPI запущен.")
    
    try:
        # --- Startup Logic ---
        logger.info("[STARTUP 1/2] Воркер отключен. Задачи будут обрабатываться синхронно через API.")
        logger.info("[STARTUP 1/2] ✅ Фоновый воркер отключен.")

        # Проверка SECRET_TOKEN
        if not os.environ.get("SECRET_TOKEN"):
            logger.warning("[STARTUP 2/2] ⚠️ SECRET_TOKEN не установлен. Защищенные эндпоинты НЕ БУДУТ РАБОТАТЬ.")
        else:
            logger.info("[STARTUP 2/2] ✅ SECRET_TOKEN загружен. Эндпоинты /internal/... активны.")

        logger.info("=======================================================")

    except Exception as e:
        logger.critical(f"--- 💥 КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e} ---", exc_info=True)
    
    yield 
    
    # --- Shutdown Logic ---
    logger.info("--- 🛑 FastAPI завершает работу. ---")


app = FastAPI(lifespan=lifespan)

app.include_router(api_router) 
app.include_router(alerts_router) # <-- 🚀 ИЗМЕНЕНИЕ (Миграция Алертов)



if __name__ == "__main__":
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000, 
        reload=False,
        log_config=None
    )