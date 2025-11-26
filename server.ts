// ВАЖНО: Загружает .env переменные в process.env
import "dotenv/config";

import express, { Request, Response, NextFunction } from "express";
import { run1hJob } from "./jobs/job-1h";
import { run4hJob } from "./jobs/job-4h";
import { run8hJob } from "./jobs/job-8h";
import { run12hJob } from "./jobs/job-12h";
import { run1dJob } from "./jobs/job-1d";
import { DataStore } from "./store/store"; // <--- ИЗМЕНЕНИЕ: импорт DataStore
import { TF, JobResult, DColors, TF_MAP, MarketData } from "./core/types";
import { logger } from "./core/utils/logger";

// —————————————————————————————————————————————
// 1. КОНФИГУРАЦИЯ
// —————————————————————————————————————————————

const app = express();
// Render.com предоставляет порт через process.env.PORT
const PORT = process.env.PORT || 8000;
const SECRET_TOKEN = process.env.SECRET_TOKEN;

if (!SECRET_TOKEN) {
  logger.error("ОШИБКА: SECRET_TOKEN не установлен. Сервер не запущен.");
  process.exit(1);
}

// Инициализируем выбранное хранилище при старте
DataStore.init(); // <--- ИЗМЕНЕНИЕ: RedisStore -> DataStore

// Карта для запуска работ по API
const jobs: Record<string, () => Promise<JobResult>> = {
  "1h": run1hJob,
  "4h": run4hJob,
  "8h": run8hJob,
  "12h": run12hJob,
  "1d": run1dJob,
};

// —————————————————————————————————————————————
// 2. MIDDLEWARE (Авторизация)
// —————————————————————————————————————————————

const checkAuth = (req: Request, res: Response, next: NextFunction) => {
  const authHeader = req.headers.authorization; // 'authorization' в Node
  if (authHeader !== `Bearer ${SECRET_TOKEN}`) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
};

// —————————————————————————————————————————————
// 3. HTTP-сервер (API эндпоинты)
// —————————————————————————————————————————————

// --- ЭНДПОИНТ 0: Health Check (БЕЗ АВТОРИЗАЦИИ) ---
app.get("/health", (req: Request, res: Response) => {
  res.status(200).json({ status: "ok" });
});

// --- ЭНДПОИНТ 1: Получение данных из кэша (С LAZY LOADING) ---
app.get("/api/cache/:tf", checkAuth, async (req: Request, res: Response) => {
  try {
    const { tf } = req.params;

    // 1. Обработка "all" (Happy Path 1)
    if (tf === "all") {
      const allData = await DataStore.getAll(); // <--- ИЗМЕНЕНИЕ: RedisStore -> DataStore
      return res.status(200).json({ success: true, data: allData });
    }

    // 2. Проверка валидности таймфрейма
    if (!TF_MAP[tf]) {
      return res.status(400).json({ error: `Invalid timeframe: ${tf}` });
    }

    const timeframe = tf as TF;

    // 3. Получаем кэш (Happy Path 2)
    const cachedData = await DataStore.get(timeframe); // <--- ИЗМЕНЕНИЕ: RedisStore -> DataStore

    if (cachedData) {
      // Данные есть - отдаём, не проверяя возраст.
      return res.status(200).json({
        success: true,
        data: cachedData,
        cached: true,
      });
    }

    // 4. Кэша нет (Empty Data Path)
    // (Весь "медленный путь" с регенерацией удален)
    return res.status(404).json({
      error: `No cache found for timeframe: ${timeframe}`,
    });
  } catch (e: any) {
    const errorMsg = e instanceof Error ? e.message : String(e);
    logger.error(`[API] Error in cache endpoint: ${errorMsg}`, e);
    return res.status(500).json({ error: errorMsg });
  }
});

// --- ЭНДПОИНТ 2: Запуск работы (Этот ты будешь дергать из Deno Cron) ---
app.post("/api/jobs/run/:jobName", checkAuth, (req: Request, res: Response) => {
  try {
    const { jobName } = req.params;
    if (jobName && jobName in jobs) {
      const jobToRun = jobs[jobName];
      jobToRun(); // Запускаем АСИНХРОННО

      return res.status(202).json({
        success: true,
        message: `Job '${jobName}' started successfully.`,
      });
    } else {
      return res
        .status(404)
        .json({ error: `Job '${jobName || "undefined"}' not found.` });
    }
  } catch (e: any) {
    const errorMsg = e instanceof Error ? e.message : String(e);
    logger.error(`[API] Error running job: ${errorMsg}`, e);
    return res.status(500).json({ error: errorMsg });
  }
});

// --- ЭНДПОИНТ 3: Получение 1ч свечи BTC из кэша ---
app.get(
  "/api/1h-btc-candle",
  checkAuth,
  async (req: Request, res: Response) => {
    try {
      const tf = "1h" as TF;
      const symbolToFind = "BTCUSDT";

      const cache1h = await DataStore.get(tf); // <--- ИЗМЕНЕНИЕ: RedisStore -> DataStore

      if (!cache1h || !cache1h.data) {
        return res.status(404).json({
          error: `Cache for timeframe '${tf}' is empty or invalid.`,
        });
      }

      const symbolData = cache1h.data.find(
        (coin) => coin.symbol === symbolToFind
      );

      if (!symbolData) {
        return res.status(404).json({
          error: `Data for '${symbolToFind}' not found in '${tf}' cache.`,
        });
      }

      if (!symbolData.candles || symbolData.candles.length === 0) {
        return res.status(404).json({
          error: `Field 'candles' is empty for '${symbolToFind}' in '${tf}' cache.`,
        });
      }

      const candle = symbolData.candles[symbolData.candles.length - 1];

      return res.status(200).json({ success: true, data: candle });
    } catch (e: any) {
      const errorMsg = e instanceof Error ? e.message : String(e);
      logger.error(`[API] Error in btc-candle endpoint: ${errorMsg}`, e);
      return res.status(500).json({ success: false, error: errorMsg });
    }
  }
);

// --- 404 ---
// ИСПРАВЛЕНО: Добавлены типы Request и Response
app.use((req: Request, res: Response) => {
  res.status(404).json({ error: "Not Found" });
});

// —————————————————————————————————————————————
// 4. ЗАПУСК СЕРВЕРА
// —————————————————————————————————————————————

const startServer = async () => {
  // 3. Запускаем Express-сервер в любом случае
  app.listen(PORT, () => {
    logger.info(
      `🚀 [SERVER] Успешно запущен...`, // <-- Используем реальный хост
      DColors.green
    );
    logger.info(
      `[SERVER] Health check: GET /health (без авторизации)`,
      DColors.cyan
    );
    logger.info(
      `[SERVER] API требует: Authorization: Bearer <TOKEN>`,
      DColors.cyan
    );
  });
};

// Запускаем!
startServer();

// —————————————————————————————————————————————
// 5. Cron: ЗАПУСК ЗАДАЧ (УДАЛЕНО)
// —————————————————————————————————————————————
// (Cron-блок удален)
