// deno-lint-ignore-file no-explicit-any
import { fetchBinanceOI } from "../getters/get-binance-oi";
import { fetchBybitOI } from "../getters/get-bybit-oi";
import { CoinGroups, TF, FetcherResult, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Универсальный fetcher для Open Interest
 * Автоматически разделяет монеты по биржам и делает параллельные запросы
 */
export async function fetchOI(
  coinGroups: CoinGroups,
  timeframe: TF,
  limit: number
): Promise<FetcherResult> {
  const { binanceCoins, bybitCoins } = coinGroups;
  logger.info(
    `[OI Fetcher] Starting: ${binanceCoins.length} Binance + ${bybitCoins.length} Bybit coins [${timeframe}]`,
    DColors.cyan
  );
  const tasks: Promise<any>[] = [];

  // Binance OI
  if (binanceCoins.length > 0) {
    tasks.push(fetchBinanceOI(binanceCoins, timeframe, limit));
  }

  // Bybit OI
  if (bybitCoins.length > 0) {
    tasks.push(fetchBybitOI(bybitCoins, timeframe, limit));
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
    `[OI Fetcher] ✓ Success: ${allSuccessful.length} | ✗ Failed: ${failed.length}`,
    allSuccessful.length > 0 ? DColors.green : DColors.yellow
  );
  return { successful: allSuccessful, failed };
}
