// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file

import { fetchFundingRate } from "../getters/get-fr";
import { CoinGroups, FetcherResult, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Универсальный fetcher для Funding Rate
 * Автоматически разделяет монеты по биржам и делает параллельные запросы
 */
export async function fetchFR(
  coinGroups: CoinGroups,
  limit: number
): Promise<FetcherResult> {
  const { binanceCoins, bybitCoins } = coinGroups;
  logger.info(
    `[FR Fetcher] Starting: ${binanceCoins.length} Binance + ${bybitCoins.length} Bybit coins`,
    DColors.yellow
  );
  const tasks: Promise<any>[] = [];

  // Binance FR
  if (binanceCoins.length > 0) {
    tasks.push(fetchFundingRate(binanceCoins, "binance", limit));
  }

  // Bybit FR
  if (bybitCoins.length > 0) {
    tasks.push(fetchFundingRate(bybitCoins, "bybit", limit));
  }

  const results = await Promise.all(tasks);

  // Объединяем результаты
  const allSuccessful: any[] = [];
  const allFailed: any[] = [];

  for (const res of results) {
    allSuccessful.push(...res.successful);
    allFailed.push(...res.failed);
  }

  const failed = allFailed.map((item) => ({
    symbol: item.symbol,
    error: item.error,
  }));

  logger.info(
    `[FR Fetcher] ✓ Success: ${allSuccessful.length} | ✗ Failed: ${failed.length}`,
    allSuccessful.length > 0 ? DColors.green : DColors.yellow
  );

  return { successful: allSuccessful, failed } as FetcherResult;
}
