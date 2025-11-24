// deno-lint-ignore-file no-explicit-any
import { fetchBinanceOI } from "../getters/get-binance-oi";
import { fetchBybitOI } from "../getters/get-bybit-oi";
import { CoinGroups, TF, FetchOptions, FetcherResult, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Универсальный fetcher для Open Interest
 * Автоматически разделяет монеты по биржам и делает параллельные запросы
 */
export async function fetchOI(
  coinGroups: CoinGroups,
  timeframe: TF,
  limit: number,
  options?: FetchOptions
): Promise<FetcherResult> {
  const { binanceCoins, bybitCoins } = coinGroups;
  logger.info(
    `[OI Fetcher] Starting: ${binanceCoins.length} Binance + ${bybitCoins.length} Bybit coins [${timeframe}]`,
    DColors.cyan
  );
  const tasks: Promise<any>[] = [];

  // Binance OI
  if (binanceCoins.length > 0) {
    tasks.push(fetchBinanceOI(binanceCoins, timeframe, limit, options));
  }

  // Bybit OI
  if (bybitCoins.length > 0) {
    tasks.push(fetchBybitOI(bybitCoins, timeframe, limit, options));
  }

  const results = await Promise.all(tasks);

  // Объединяем результаты
  const allSuccessful: any[] = [];
  const allFailed: any[] = [];

  for (const res of results) {
    allSuccessful.push(...res.successful);
    allFailed.push(...res.failed);
  }

  // --- ИСПРАВЛЕНИЕ РЕФАКТОРИНГА ---
  // allSuccessful.map(...) больше не нужен,
  // так как allSuccessful уже содержит CoinMarketData[]
  const failed = allFailed.map((item) => ({
    symbol: item.symbol,
    error: item.error,
  }));
  // --- КОНЕЦ ИСПРАВЛЕНИЯ ---

  logger.info(
    `[OI Fetcher] ✓ Success: ${allSuccessful.length} | ✗ Failed: ${failed.length}`,
    allSuccessful.length > 0 ? DColors.green : DColors.yellow
  );
  return { successful: allSuccessful, failed }; // <- ИСПРАВЛЕНО
}
