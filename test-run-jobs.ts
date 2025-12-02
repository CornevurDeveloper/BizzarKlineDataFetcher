// @ts-ignore-file
import "dotenv/config";
import fetch from "node-fetch";
// @ts-ignore
import { Response } from "node-fetch";
import { DColors } from "./core/types";
import { logger } from "./core/utils/logger";

// 1. ЗАГРУЗКА КОНФИГУРАЦИИ
const BAZZAR_URL = process.env.BAZZAR_KLINE_FETCHER_URL;
const SECRET_TOKEN = process.env.SECRET_TOKEN;

if (!BAZZAR_URL || !SECRET_TOKEN) {
  logger.error(
    "[Job Runner] Ошибка: BAZZAR_KLINE_FETCHER_URL или SECRET_TOKEN не установлены в .env"
  );
  process.exit(1);
}

// 2. JOBS ДЛЯ ЗАПУСКА (только BAZZAR)
const jobsToRun: string[] = ["8h"];

/**
 * Отправляет POST запрос для запуска job
 */
async function triggerJob(jobName: string): Promise<boolean> {
  const url = `${BAZZAR_URL}/api/jobs/run/${jobName}`;
  logger.info(
    `[Job Runner] 🚀 Запуск ${jobName}... (POST ${url})`,
    DColors.cyan
  );

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${SECRET_TOKEN}`,
      },
    });

    // В файле ENDPOINTS.md указано "202 Accepted"
    if (response.status === 202) {
      const result = (await response.json()) as any;
      logger.info(
        `[Job Runner] ✅ Успешно запущен ${jobName}. Сообщение: ${result.message}`,
        DColors.green
      );
      return true;
    } else {
      logger.error(
        `[Job Runner] ✗ Ошибка запуска ${jobName} (HTTP ${response.status})`
      );
      try {
        const errorResult = (await response.json()) as any;
        logger.error(`  -> Ответ сервера: ${errorResult.error || "N/A"}`);
      } catch (e) {
        logger.error(`  -> Не удалось прочитать ответ сервера.`);
      }
      return false;
    }
  } catch (e: any) {
    logger.error(`[Job Runner] ✗ КРИТИЧЕСКАЯ ОШИБКА при запуске ${jobName}`);
    logger.error(e.message);
    return false;
  }
}

/**
 * Главная функция запуска
 */
async function runTest() {
  logger.info(`[Job Runner] Запуск тестового прогона...`, DColors.yellow);
  console.log("=================================================");

  let successCount = 0;

  // Запускаем jobs ПОСЛЕДОВАТЕЛЬНО, чтобы не перегружать сервер
  for (const jobName of jobsToRun) {
    const success = await triggerJob(jobName);
    if (success) {
      successCount++;
    }
    console.log("-------------------------------------------------");
    // Пауза между запусками
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  console.log("");
  if (successCount === jobsToRun.length) {
    logger.info(
      `[Job Runner] ✅ ВСЕ ${successCount} JOBS УСПЕШНО ЗАПУЩЕНЫ`,
      DColors.green
    );
  } else {
    logger.error(
      `[Job Runner] ❌ РЕЗУЛЬТАТ: ${successCount} ✓ | ${
        jobsToRun.length - successCount
      } ✗`
    );
    process.exit(1);
  }
}

runTest();
