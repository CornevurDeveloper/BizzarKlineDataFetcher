// ВАЖНО: Загружает .env переменные в process.env
import "dotenv/config";

import express, { Request, Response, NextFunction } from "express";
import { run1hJob } from "./jobs/job-1h";
import { run4hJob } from "./jobs/job-4h";
import { run8hJob } from "./jobs/job-8h";
import { run12hJob } from "./jobs/job-12h";
import { run1dJob } from "./jobs/job-1d";
import { RedisStore } from "./redis-store";
import { TF, JobResult, DColors, TF_MAP, MarketData } from "./core/types";
import { logger } from "./core/utils/logger";
import { AddressInfo } from "net";
import { CONFIG } from "./core/config";

// —————————————————————————————————————————————
// 1. КОНФИГУРАЦИЯ
// —————————————————————————————————————————————

const app = express();
// Render.com предоставляет порт через process.env.PORT
const PORT = parseInt(process.env.PORT || "8000", 10);
const SECRET_TOKEN = process.env.SECRET_TOKEN;

if (!SECRET_TOKEN) {
  logger.error("ОШИБКА: SECRET_TOKEN не установлен. Сервер не запущен.");
  process.exit(1);
}

// Инициализируем Redis при старте
RedisStore.init();

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

    // Обработка "all"
    if (tf === "all") {
      const allData = await RedisStore.getAll();
      return res.status(200).json({ success: true, data: allData });
    }

    // Проверка валидности таймфрейма
    if (!TF_MAP[tf]) {
      return res.status(400).json({ error: `Invalid timeframe: ${tf}` });
    }

    const timeframe = tf as TF;
    const cachedData = await RedisStore.get(timeframe);

    if (cachedData) {
      // Проверяем свежесть данных (макс 2 часа)
      // Убедимся, что timestamp существует, прежде чем его читать
      const timestamp = (cachedData as any)?.timestamp;
      if (timestamp) {
        const age = Date.now() - timestamp;
        const maxAge = 2 * 60 * 60 * 1000; // 2 часа

        if (age < maxAge) {
          // Данные свежие - отдаём
          return res.status(200).json({
            success: true,
            data: cachedData,
            cached: true,
            age: Math.round(age / 60000) + " minutes",
          });
        }
        logger.info(
          `[API] Cache for ${timeframe} is stale (age: ${Math.round(
            age / 60000
          )} min), regenerating...`,
          DColors.yellow
        );
      } else {
        logger.warn(
          `[API] Cache for ${timeframe} found, but missing 'timestamp'. Regenerating...`,
          DColors.yellow
        );
      }
    }

    // Кэша нет или устарел - генерируем ПРЯМО СЕЙЧАС
    logger.info(
      `[API] Cache miss for ${timeframe}, running job synchronously...`,
      DColors.cyan
    );

    const jobFn = jobs[timeframe];
    if (!jobFn) {
      return res.status(500).json({
        error: `Job for timeframe ${timeframe} not found`,
      });
    }

    await jobFn(); // Блокирующий вызов job
    const freshData = await RedisStore.get(timeframe);

    if (!freshData) {
      return res.status(500).json({
        error: `Failed to generate cache for ${timeframe}`,
      });
    }

    return res.status(200).json({
      success: true,
      data: freshData,
      cached: false,
      generated: true,
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

      const cache1h = await RedisStore.get(tf);

      if (!cache1h || !cache1h.data) {
        return res.status(404).json({
          error: `Cache for timeframe '${tf}' is empty or invalid.`,
        });
      }

      const symbolData = cache1h.data.find(
        (coin) => coin.symbol === symbolToFind
      );

      if (!symbolData) {
        return res.status(4404).json({
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
app.use((req: Request, res: Response) => {
  res.status(404).json({ error: "Not Found" });
});

// —————————————————————————————————————————————
// 4. ЗАПУСК СЕРВЕРА
// —————————————————————————————————————————————

const startServer = async () => {
  try {
    //const initialLimit = CONFIG.INIT.STARTUP_CANDLES; // <--- ИСПОЛЬЗУЕМ CONFIG

    // 1. Всегда запускаем run1dJob() при старте
    // logger.info(
    //   `[SERVER] Запускаю run1dJob() для ИНИЦИАЛИЗАЦИИ кэша. Лимит: ${initialLimit} свечей (для экономии RAM)...`,
    //   DColors.yellow
    // );

    // ВРЕМЕННОЕ ИСПРАВЛЕНИЕ: Мы передаем очень низкий лимит, чтобы избежать OOM ошибки при запуске.
    // Фактическую работу Cron должен будет запустить позже, используя полный лимит.
    //await run1dJob(); // <--- Ждем завершения с маленьким лимитом

    logger.info(
      "[SERVER] ✓ Инициализация кэша завершена. Полная загрузка будет выполнена Cron-задачей.",
      DColors.green
    );
  } catch (error: any) {
    // 2. Логируем ошибку, но НЕ ПАДАЕМ
    logger.error(
      `[SERVER] ❌ Ошибка при инициализации: ${error.message}`,
      error
    );
    logger.info(
      "[SERVER] Сервер продолжит работу. API будет использовать lazy loading.",
      DColors.yellow
    );
  }

  // 3. Запускаем Express-сервер в любом случае

  const server = app.listen(PORT, "0.0.0.0", () => {
    const address = server.address();
    let host = "0.0.0.0";
    let port: string | number = PORT;

    if (
      address &&
      typeof address === "object" &&
      (address as AddressInfo).port
    ) {
      const addrInfo = address as AddressInfo;
      host = addrInfo.address;
      port = addrInfo.port;
    }

    logger.info(
      `🚀 [SERVER] Успешно запущен, слушает на http://${host}:${port}`,
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
