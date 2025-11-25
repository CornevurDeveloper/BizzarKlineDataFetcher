// @ts-ignore-file
import { fetchCoins } from "../core/fetchers/coin-fetcher";
import { fetchFR } from "../core/fetchers/fr-fetchers";
import { fetchKlineData } from "../core/fetchers/kline-fetchers";
import { fetchOI } from "../core/fetchers/oi-fetchers";
import { combineCoinResults } from "../core/processors/combiner";
import { enrichKlines, trimCandles } from "../core/processors/enricher";
import { JobResult, TF, DColors } from "../core/types";
import {
  splitCoinsByExchange,
  getCurrentCandleTime,
  TIMEFRAME_MS,
} from "../core/utils/helpers";
import { logger } from "../core/utils/logger";
import { RedisStore } from "../redis-store";
import { CONFIG } from "../core/config";

/**
 * Cron Job для 8h таймфрейма
 *
 * Алгоритм:
 * 1. Fetch 1h OI data (CONFIG.OI.h1_GLOBAL)
 * 2. Fetch FR data (CONFIG.FR.h4_RECENT)
 * 3. Fetch 4h Kline data (CONFIG.KLINE.h4_BASE) → BASE SET
 * 4. Process:
 *    - 4h (last 400 from BASE) + OI + FR → save to 4h
 *    - 8h (combined from BASE 800) + OI + FR → save to 8h
 */
export async function run8hJob(): Promise<JobResult> {
  const startTime = Date.now();
  const timeframe: TF = "8h";
  const errors: string[] = [];

  try {
    const coins = await fetchCoins();
    logger.info(
      `[JOB 8h] Starting job for ${coins.length} coins`,
      DColors.cyan
    );

    // Split coins by exchange
    const coinGroups = splitCoinsByExchange(coins);

    // Fetch OI 1h (720 candles)
    const oi1hResult = await fetchOI(coinGroups, "1h", CONFIG.OI.h1_GLOBAL, {
      batchSize: 50,
      delayMs: 100,
    });

    if (oi1hResult.failed.length > 0) {
      errors.push(`OI fetch failed for ${oi1hResult.failed.length} coins`);
    }

    // Fetch FR data (401 candles)
    const frResult = await fetchFR(coinGroups, CONFIG.FR.h4_RECENT, {
      batchSize: 50,
      delayMs: 100,
    });

    if (frResult.failed.length > 0) {
      errors.push(`FR fetch failed for ${frResult.failed.length} coins`);
    }

    // Fetch Klines 4h (801 candles) → BASE SET
    const kline4hBaseResult = await fetchKlineData(
      coinGroups,
      "4h",
      CONFIG.KLINE.h4_BASE,
      {
        batchSize: 50,
        delayMs: 100,
      }
    );

    if (kline4hBaseResult.failed.length > 0) {
      errors.push(
        `4h Kline fetch failed for ${kline4hBaseResult.failed.length} coins`
      );
    }

    // Process 4h: trim to 400 candles + OI + FR
    const kline4hTrimmed = trimCandles(
      kline4hBaseResult.successful,
      CONFIG.SAVE_LIMIT
    );

    const enriched4h = enrichKlines(kline4hTrimmed, oi1hResult, "4h", frResult);

    await RedisStore.save("4h", {
      timeframe: "4h",
      openTime: getCurrentCandleTime(TIMEFRAME_MS["4h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched4h.length,
      data: enriched4h,
    });

    logger.info(
      `[JOB 8h] ✓ Saved 4h: ${enriched4h.length} coins`,
      DColors.green
    );

    // Process 8h: combine BASE SET (800) → 8h + OI + FR
    const kline8hCombined = combineCoinResults(kline4hBaseResult.successful);

    const enriched8h = enrichKlines(
      kline8hCombined,
      oi1hResult,
      "8h",
      frResult
    );

    await RedisStore.save("8h", {
      timeframe: "8h",
      openTime: getCurrentCandleTime(TIMEFRAME_MS["8h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched8h.length,
      data: enriched8h,
    });

    const executionTime = Date.now() - startTime;

    logger.info(
      `[JOB 8h] ✓ Completed in ${executionTime}ms | Saved 8h: ${enriched8h.length} coins`,
      DColors.green
    );

    return {
      success: true,
      timeframe,
      totalCoins: coins.length,
      successfulCoins: enriched8h.length,
      failedCoins: kline4hBaseResult.failed.length,
      errors,
      executionTime,
    };
  } catch (error: any) {
    const executionTime = Date.now() - startTime;
    logger.error(`[JOB 8h] Failed: ${error.message}`, DColors.red);

    return {
      success: false,
      timeframe,
      totalCoins: 0,
      successfulCoins: 0,
      failedCoins: 0,
      errors: [error.message, ...errors],
      executionTime,
    };
  }
}
