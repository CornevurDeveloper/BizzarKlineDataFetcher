// deno-lint-ignore-file no-explicit-any
import { fetchKlines } from "../getters/get-kline";
import { CoinGroups, TF, FetchOptions, FetcherResult, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Универсальный fetcher для Klines
 * Автоматически разделяет монеты по биржам и делает параллельные запросы
 */
export async function fetchKlineData(
  coinGroups: CoinGroups,
  timeframe: TF,
  limit: number,
  options?: FetchOptions
): Promise<FetcherResult> {
  const { binanceCoins, bybitCoins } = coinGroups;
  logger.info(
    `[Kline Fetcher] Starting: ${binanceCoins.length} Binance + ${bybitCoins.length} Bybit coins [${timeframe}]`,
    DColors.cyan
  );
  const tasks: Promise<any>[] = [];

  // Binance Klines
  if (binanceCoins.length > 0) {
    tasks.push(fetchKlines(binanceCoins, "binance", timeframe, limit, options));
  }

  // Bybit Klines
  if (bybitCoins.length > 0) {
    tasks.push(fetchKlines(bybitCoins, "bybit", timeframe, limit, options));
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
    `[Kline Fetcher] ✓ Success: ${allSuccessful.length} | ✗ Failed: ${failed.length}`,
    allSuccessful.length > 0 ? DColors.green : DColors.yellow
  );
  return { successful: allSuccessful, failed }; // <- ИСПРАВЛЕНО
}
