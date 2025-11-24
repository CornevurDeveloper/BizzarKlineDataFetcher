// @ts-ignore-file
import { DColors, JobResult } from "../types"; // <- ИЗМЕНЕНИЕ: убрано .ts
import { logger } from "./logger"; // <- ИЗМЕНЕНИЕ: убрано .ts

/**
 * Вспомогательная функция (wrapper) для логирования и безопасного запуска
 * Используется в /cron/*.ts файлах
 */
export async function runJob(
  jobName: string,
  jobFn: () => Promise<JobResult> // <- Убедимся, что job-функция возвращает JobResult
) {
  // --- ВЕРНУЛИ DCOLORS ---
  logger.info(`\n${"=".repeat(60)}`, DColors.cyan);
  logger.info(`Starting ${jobName} Job`, DColors.cyan);
  logger.info(`${"=".repeat(60)}\n`, DColors.cyan);
  // -------------------------

  try {
    // Запускаем сам job и ждем его результат
    const result = await jobFn();

    if (result.success) {
      // --- ВЕРНУЛИ DCOLORS ---
      logger.success(`\n✓ ${jobName} Job completed successfully`, DColors.green);
      logger.info(`  - Total coins: ${result.totalCoins}`, DColors.green);
      logger.info(`  - Successful: ${result.successfulCoins}`, DColors.green);
      logger.info(`  - Failed: ${result.failedCoins}`, DColors.green);
      logger.info(
        `  - Execution time: ${result.executionTime}ms\n`,
        DColors.green
      );
      // -------------------------
    } else {
      // --- ОСТАВИЛИ БЕЗ DCOLORS (ЭТО ПРАВИЛЬНО) ---
      logger.error(`\n✗ ${jobName} Job failed`);
      logger.error(`  - Errors: ${result.errors.join(", ")}\n`);
      // ---------------------------------------------
    }
  } catch (error: any) {
    // --- ОСТАВИЛИ ИСПРАВЛЕННЫЙ ВЫЗОВ (ЭТО ПРАВИЛЬНО) ---
    logger.error(`\n✗ ${jobName} Job crashed: ${error.message}\n`, error);
    // ----------------------------------------------------
    // Пробрасываем ошибку, чтобы Deno Deploy Cron мог ее поймать, если нужно
    throw error;
  }
}