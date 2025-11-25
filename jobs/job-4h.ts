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
 * 1. Fetch 1h OI data (CONFIG.OI.h1_GLOBAL)
 * 2. Fetch FR data (CONFIG.FR.h4_RECENT)
 * 3. Fetch 1h Kline data (CONFIG.KLINE.h1)
 * 4. Fetch 4h Kline data (CONFIG.KLINE.h4_DIRECT)
 * 5. Enrich and save:
 * - 1h + OI → save to 1h
 * - 4h + OI + FR → save to 4h
 */
export async function run4hJob(): Promise<JobResult> {
  const startTime = Date.now();
  const timeframe: TF = "4h" as TF;
  const errors: string[] = [];

  const coins = await fetchCoins();
  logger.info(`[JOB 4h] Starting job for ${coins.length} coins`, DColors.cyan);

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

    // 3. Fetch FR (400 candles для 4h свечей)
    const frResult = await fetchFR(coinGroups, CONFIG.FR.h4_RECENT, {
      batchSize: 50,
      delayMs: 100,
    });
    if (frResult.failed.length > 0) {
      errors.push(`FR fetch failed for ${frResult.failed.length} coins`);
    }

    // // 4. Fetch Klines 1h (400 candles)
    // const kline1hResult = await fetchKlineData(
    //   coinGroups,
    //   "1h" as TF,
    //   CONFIG.KLINE.h1,
    //   {
    //     batchSize: 50,
    //     delayMs: 100,
    //   }
    // );
    // if (kline1hResult.failed.length > 0) {
    //   errors.push(
    //     `1h Kline fetch failed for ${kline1hResult.failed.length} coins`
    //   );
    // }

    // 5. Fetch Klines 4h (400 candles)
    const kline4hResult = await fetchKlineData(
      coinGroups,
      "4h" as TF,
      CONFIG.KLINE.h4_DIRECT,
      {
        batchSize: 50,
        delayMs: 100,
      }
    );
    if (kline4hResult.failed.length > 0) {
      errors.push(
        `4h Kline fetch failed for ${kline4hResult.failed.length} coins`
      );
    }

    // // 6. Enrich 1h Klines with OI (no FR)
    // const enriched1h = enrichKlines(
    //   kline1hResult.successful,
    //   oi1hResult,
    //   "1h" as TF
    // );

    // 7. Enrich 4h Klines with OI + FR
    const enriched4h = enrichKlines(
      kline4hResult.successful,
      oi1hResult,
      "4h" as TF,
      frResult
    );

    // // 8. Save 1h to Redis
    // const marketData1h: MarketData = {
    //   timeframe: "1h" as TF,
    //   openTime: getCurrentCandleTime(TIMEFRAME_MS["1h"]),
    //   updatedAt: Date.now(),
    //   coinsNumber: enriched1h.length,
    //   data: enriched1h,
    // };
    // await RedisStore.save("1h" as TF, marketData1h);

    // 9. Save 4h to Redis
    const marketData4h: MarketData = {
      timeframe: "4h" as TF,
      openTime: getCurrentCandleTime(TIMEFRAME_MS["4h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched4h.length,
      data: enriched4h,
    };
    await RedisStore.save("4h" as TF, marketData4h);

    const executionTime = Date.now() - startTime;

    logger.info(
      `[JOB 4h] ✓ Completed in ${executionTime}ms | 4h: ${enriched4h.length} coins`,
      DColors.green
    );

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
      totalCoins: coins.length,
      successfulCoins: 0,
      failedCoins: coins.length,
      errors: [error.message, ...errors],
      executionTime,
    };
  }
}
