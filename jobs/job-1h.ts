// @ts-ignore-file
import { fetchCoins } from "../core/fetchers/coin-fetcher";
import { fetchKlineData } from "../core/fetchers/kline-fetchers";
import { fetchOI } from "../core/fetchers/oi-fetchers";
import { enrichKlines } from "../core/processors/enricher";
import { DColors, JobResult, TF } from "../core/types";
import {
  splitCoinsByExchange,
  getCurrentCandleTime,
  TIMEFRAME_MS,
} from "../core/utils/helpers";
import { logger } from "../core/utils/logger";
import { RedisStore } from "../redis-store";
import { CONFIG } from "../core/config";

/**
 * Cron Job для 1h таймфрейма
 * Запускается каждый час (кроме 0, 4, 8, 12, 20)
 *
 * Алгоритм:
 * 1. Fetch 1h OI data (CONFIG.OI.h1_GLOBAL)
 * 2. Fetch 1h Kline data (CONFIG.KLINE.h1)
 * 3. Enrich and save:
 * - 1h + OI → save to 1h
 */
export async function run1hJob(): Promise<JobResult> {
  const startTime = Date.now();
  const timeframe: TF = "1h" as TF;
  const errors: string[] = [];

  const coins = await fetchCoins();
  logger.info(`[JOB 1h] Starting job for ${coins.length} coins`, DColors.cyan);

  try {
    // 1. Split coins by exchange
    const coinGroups = splitCoinsByExchange(coins);

    // 2. Fetch OI 1h (720 candles)
    const oi1hResult = await fetchOI(
      coinGroups,
      "1h" as TF,
      CONFIG.OI.h1_GLOBAL,
      {
        batchSize: 50,
        delayMs: 100,
      }
    );
    if (oi1hResult.failed.length > 0) {
      errors.push(`OI fetch failed for ${oi1hResult.failed.length} coins`);
    }

    // 3. Fetch Klines 1h (400 candles)
    const kline1hResult = await fetchKlineData(
      coinGroups,
      "1h" as TF,
      CONFIG.KLINE.h1,
      {
        batchSize: 50,
        delayMs: 100,
      }
    );
    if (kline1hResult.failed.length > 0) {
      errors.push(
        `1h Kline fetch failed for ${kline1hResult.failed.length} coins`
      );
    }

    // 4. Enrich 1h + OI → save (no FR for 1h job)
    const enriched1h = enrichKlines(
      kline1hResult.successful,
      oi1hResult,
      "1h" as TF
    );

    // 5. Save ONLY 1h to Redis
    await RedisStore.save("1h" as TF, {
      timeframe: "1h" as TF,
      openTime: getCurrentCandleTime(TIMEFRAME_MS["1h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched1h.length,
      data: enriched1h,
    });

    const executionTime = Date.now() - startTime;

    logger.info(
      `[JOB 1h] ✓ Completed in ${executionTime}ms | Saved 1h: ${enriched1h.length} coins`,
      DColors.green
    );

    return {
      success: true,
      timeframe,
      totalCoins: coins.length,
      successfulCoins: enriched1h.length,
      failedCoins: kline1hResult.failed.length,
      errors,
      executionTime,
    };
  } catch (error: any) {
    const executionTime = Date.now() - startTime;
    logger.error(`[JOB 1h] Failed: ${error.message}`, DColors.red);
    return {
      success: false,
      timeframe,
      totalCoins: coins.length,
      successfulCoins: 0,
      failedCoins: coins.length,
      errors: [error.message, ...errors],
      executionTime,
    };
  }
}