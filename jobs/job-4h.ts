// @ts-ignore-file
import { fetchCoins } from "../core/fetchers/coin-fetcher";
import { fetchFR } from "../core/fetchers/fr-fetchers";
import { fetchKlineData } from "../core/fetchers/kline-fetchers";
import { fetchOI } from "../core/fetchers/oi-fetchers";
import { enrichKlines } from "../core/processors/enricher";
import { DColors, JobResult, MarketData, TF } from "../core/types";
import {
  splitCoinsByExchange,
  getCurrentCandleTime,
  TIMEFRAME_MS,
} from "../core/utils/helpers";
import { logger } from "../core/utils/logger";
import { RedisStore } from "../redis-store";
import { CONFIG } from "../core/config";

/**
 * Cron Job для 4h таймфрейма
 *
 * Алгоритм:
 * 1. Fetch 1h OI data
 * 2. Wait 3s
 * 3. Fetch FR data
 * 4. Wait 3s
 * 5. Fetch 4h Kline data
 * 6. Enrich and save 4h + OI + FR
 */
export async function run4hJob(): Promise<JobResult> {
  const startTime = Date.now();
  const timeframe: TF = "4h";
  const errors: string[] = [];

  try {
    const coins = await fetchCoins();
    logger.info(
      `[JOB 4h] Starting job for ${coins.length} coins`,
      DColors.cyan
    );

    const coinGroups = splitCoinsByExchange(coins);
    let stepTime = Date.now();

    // Fetch OI 1h
    const oi1hResult = await fetchOI(coinGroups, "1h", CONFIG.OI.h1_GLOBAL, {
      batchSize: 10,
      delayMs: 200,
    });

    if (oi1hResult.failed.length > 0) {
      errors.push(`OI fetch failed for ${oi1hResult.failed.length} coins`);
    }

    logger.info(
      `[JOB 4h] ✓ Fetched OI in ${Date.now() - stepTime}ms`,
      DColors.green
    );

    // Wait
    await new Promise((resolve) =>
      setTimeout(resolve, CONFIG.DELAYS.DELAY_BTW_TASKS)
    );

    stepTime = Date.now();

    // Fetch FR data
    const frResult = await fetchFR(coinGroups, CONFIG.FR.h4_RECENT, {
      batchSize: 10,
      delayMs: 200,
    });

    if (frResult.failed.length > 0) {
      errors.push(`FR fetch failed for ${frResult.failed.length} coins`);
    }

    logger.info(
      `[JOB 4h] ✓ Fetched FR in ${Date.now() - stepTime}ms`,
      DColors.green
    );

    // Wait
    await new Promise((resolve) =>
      setTimeout(resolve, CONFIG.DELAYS.DELAY_BTW_TASKS)
    );

    stepTime = Date.now();

    // Fetch Klines 4h
    const kline4hResult = await fetchKlineData(
      coinGroups,
      "4h",
      CONFIG.KLINE.h4_DIRECT,
      {
        batchSize: 10,
        delayMs: 200,
      }
    );

    if (kline4hResult.failed.length > 0) {
      errors.push(
        `4h Kline fetch failed for ${kline4hResult.failed.length} coins`
      );
    }

    logger.info(
      `[JOB 4h] ✓ Fetched Klines in ${Date.now() - stepTime}ms`,
      DColors.green
    );

    // Enrich + Save
    stepTime = Date.now();

    const enriched4h = enrichKlines(
      kline4hResult.successful,
      oi1hResult,
      "4h",
      frResult
    );

    const marketData4h: MarketData = {
      timeframe: "4h",
      openTime: getCurrentCandleTime(TIMEFRAME_MS["4h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched4h.length,
      data: enriched4h,
    };

    await RedisStore.save("4h", marketData4h);

    logger.info(
      `[JOB 4h] ✓ Saved 4h: ${enriched4h.length} coins in ${
        Date.now() - stepTime
      }ms`,
      DColors.green
    );

    const executionTime = Date.now() - startTime;

    logger.info(`[JOB 4h] ✓ Completed in ${executionTime}ms`, DColors.green);

    return {
      success: true,
      timeframe,
      totalCoins: coins.length,
      successfulCoins: enriched4h.length,
      failedCoins: kline4hResult.failed.length,
      errors,
      executionTime,
    };
  } catch (error: any) {
    const executionTime = Date.now() - startTime;
    logger.error(`[JOB 4h] Failed: ${error.message}`, DColors.red);

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
