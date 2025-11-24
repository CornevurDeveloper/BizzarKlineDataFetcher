// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file

import { fetchFundingRate } from "../getters/get-fr";
import { CoinGroups, FetchOptions, FetcherResult, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Универсальный fetcher для Funding Rate
 * Автоматически разделяет монеты по биржам и делает параллельные запросы
 * FR уже нормализован к 8h intervals внутри get-funding-rate.ts
 */
export async function fetchFR(
  coinGroups: CoinGroups,
  limit: number,
  options?: FetchOptions
): Promise<FetcherResult> {
  const { binanceCoins, bybitCoins } = coinGroups;
  logger.info(
    `[FR Fetcher] Starting: ${binanceCoins.length} Binance + ${bybitCoins.length} Bybit coins`,
    DColors.yellow
  );
  const tasks: Promise<any>[] = [];

  // Binance FR
  if (binanceCoins.length > 0) {
    tasks.push(fetchFundingRate(binanceCoins, "binance", limit, options));
  }

  // Bybit FR (будет нормализован к 8h)
  if (bybitCoins.length > 0) {
    tasks.push(fetchFundingRate(bybitCoins, "bybit", limit, options));
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
    `[FR Fetcher] ✓ Success: ${allSuccessful.length} | ✗ Failed: ${failed.length}`,
    allSuccessful.length > 0 ? DColors.green : DColors.yellow
  );

  return { successful: allSuccessful, failed } as FetcherResult; // <- ИСПРАВЛЕНО
}
