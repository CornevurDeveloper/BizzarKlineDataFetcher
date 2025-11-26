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
import { DataStore } from "../store/store";
import { CONFIG } from "../core/config";

/**
 * Cron Job для 1D таймфрейма
 *
 * Алгоритм (Упрощенный, на основе реального кода):
 * 1. Fetch 1h OI data (CONFIG.OI.h1_GLOBAL)
 * 2. Wait
 * 3. Fetch 1h Kline data (CONFIG.KLINE.h1)
 * 4. Enrich and save 1h + OI
 * 5. Wait
 * 6. Fetch 12h Kline data (CONFIG.KLINE.h12_BASE) → BASE SET for 12h/1D
 * 7. Process:
 * - 12h (last 400 from 12h BASE) + OI → save to 12h (no FR!)
 * - 1D (combined from 12h BASE 800) + OI → save to 1D (no FR!)
 */
export async function run1dJob(): Promise<JobResult> {
  const startTime = Date.now();
  const timeframe: TF = "D" as TF;
  const errors: string[] = [];

  const coins = await fetchCoins();
  logger.info(`[JOB 1D] Starting job for ${coins.length} coins`, DColors.cyan);

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

    // Wait
    await new Promise((resolve) =>
      setTimeout(resolve, CONFIG.DELAYS.DELAY_BTW_TASKS)
    );
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

    // 5. Save ONLY 1h to DataStore
    await DataStore.save("1h" as TF, {
      timeframe: "1h" as TF,
      openTime: getCurrentCandleTime(TIMEFRAME_MS["1h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched1h.length,
      data: enriched1h,
    });

    logger.info(
      `[JOB 1d] ✓Saved 1h: ${enriched1h.length} coins`,
      DColors.green
    );

    // Wait
    await new Promise((resolve) =>
      setTimeout(resolve, CONFIG.DELAYS.DELAY_BTW_TASKS)
    );
    // 6. Fetch Klines 12h (801 candles) → BASE SET for 12h/1D
    const kline12hBaseResult = await fetchKlineData(
      coinGroups,
      "12h" as TF,
      CONFIG.KLINE.h12_BASE,
      {
        batchSize: 50,
        delayMs: 100,
      }
    );
    if (kline12hBaseResult.failed.length > 0) {
      errors.push(
        `12h Kline fetch failed for ${kline12hBaseResult.failed.length} coins`
      );
    }

    // 11. 12h (last 400 from 12h BASE) + OI → save (NO FR!)
    const kline12hTrimmed = trimCandles(
      kline12hBaseResult.successful,
      CONFIG.SAVE_LIMIT
    );
    const enriched12h = enrichKlines(kline12hTrimmed, oi1hResult, "12h" as TF);

    await DataStore.save("12h" as TF, {
      timeframe: "12h" as TF,
      openTime: getCurrentCandleTime(TIMEFRAME_MS["12h"]),
      updatedAt: Date.now(),
      coinsNumber: enriched12h.length,
      data: enriched12h,
    });

    logger.info(
      `[JOB 1d] ✓Saved 12h: ${enriched12h.length} coins`,
      DColors.green
    );
    // 12. 1D (combined from 12h BASE 800) + OI → save (NO FR!)
    const kline1dCombined = combineCoinResults(kline12hBaseResult.successful);
    const enriched1d = enrichKlines(kline1dCombined, oi1hResult, "D" as TF);

    await DataStore.save("D" as TF, {
      timeframe: "D" as TF,
      openTime: getCurrentCandleTime(TIMEFRAME_MS["D"]),
      updatedAt: Date.now(),
      coinsNumber: enriched1d.length,
      data: enriched1d,
    });

    logger.info(
      `[JOB 1d] ✓Saved 1d: ${enriched1d.length} coins`,
      DColors.green
    );
    const executionTime = Date.now() - startTime;

    logger.info(
      `[JOB 1D] ✓ Completed in ${executionTime}ms | Saved 1h: ${enriched1h.length} coins, 12h: ${enriched12h.length} coins, 1D: ${enriched1d.length} coins`,
      DColors.green
    );

    return {
      success: true,
      timeframe,
      totalCoins: coins.length,
      successfulCoins: enriched1d.length,
      failedCoins: kline12hBaseResult.failed.length,
      errors,
      executionTime,
    };
  } catch (error: any) {
    const executionTime = Date.now() - startTime;
    logger.error(`[JOB 1D] Failed: ${error.message}`, DColors.red);
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
