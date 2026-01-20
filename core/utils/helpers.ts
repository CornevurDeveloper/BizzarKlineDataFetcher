import { Coin, CoinGroups } from "../types";

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
/**
 * Разделяет монеты по биржам
 */
export function splitCoinsByExchange(coins: Coin[]): CoinGroups {
  const binanceCoins = coins.filter(
    (coin) =>
      coin.exchanges?.some((ex) => ex.toLowerCase() === "binance") &&
      !coin.exchanges?.some((ex) => ex.toLowerCase() === "bybit"),
  );

  const bybitCoins = coins.filter((coin) =>
    coin.exchanges?.some((ex) => ex.toLowerCase() === "bybit"),
  );

  return { binanceCoins, bybitCoins };
}

/**
 * Получает текущее время для самой свежей свечи
 */
export function getCurrentCandleTime(timeframeMs: number): number {
  const now = Date.now();
  return Math.floor(now / timeframeMs) * timeframeMs;
}

/**
 * Интервалы таймфреймов в миллисекундах
 */
export const TIMEFRAME_MS = {
  "1h": 60 * 60 * 1000,
  "4h": 4 * 60 * 60 * 1000,
  "8h": 8 * 60 * 60 * 1000,
  "12h": 12 * 60 * 60 * 1000,
  D: 24 * 60 * 60 * 1000,
} as const;
