import { Candle, DColors, CoinMarketData } from "../types";
import { logger } from "../utils/logger";
import { TIMEFRAME_MS } from "../utils/helpers";

/**
 * Комбинирует свечи в соотношении 2:1
 * Используется для:
 * - 4h → 8h (2 свечи = 1 свеча)
 * - 12h → 1D (2 свечи = 1 свеча)
 *
 * FR для 8h свечи берётся из первой 4h свечи
 */
export function combineCandles(_symbol: string, candles: Candle[]): Candle[] {
  if (candles.length < 2) {
    logger.error("[Combiner] Not enough candles to combine", DColors.red);
    return [];
  }

  // Определяем интервал источника и целевой интервал
  const sourceIntervalMs = candles[1].openTime - candles[0].openTime;
  let targetIntervalMs: number;

  if (sourceIntervalMs === TIMEFRAME_MS["4h"]) {
    targetIntervalMs = TIMEFRAME_MS["8h"]; // 4h -> 8h
  } else if (sourceIntervalMs === TIMEFRAME_MS["12h"]) {
    targetIntervalMs = TIMEFRAME_MS["D"]; // 12h -> 1D
  } else {
    logger.warn(
      `[Combiner] Unexpected source interval: ${sourceIntervalMs}ms`,
      DColors.yellow
    );
    return [];
  }

  const result: Candle[] = [];
  let i = 0;

  while (i < candles.length - 1) {
    const first = candles[i];

    // Проверяем, выровнена ли текущая свеча по целевой сетке
    if (first.openTime % targetIntervalMs !== 0) {
      i++;
      continue;
    }

    const second = candles[i + 1];

    // Проверяем целостность данных обеих свечей
    if (
      first.openPrice == null ||
      first.highPrice == null ||
      first.lowPrice == null ||
      first.closePrice == null ||
      first.volume == null ||
      second.openPrice == null ||
      second.highPrice == null ||
      second.lowPrice == null ||
      second.closePrice == null ||
      second.volume == null
    ) {
      logger.warn(
        `[Combiner] Skipping pair at indices ${i}:${i + 1} - incomplete data`,
        DColors.yellow
      );
      i += 2;
      continue;
    }

    // Проверяем, что вторая свеча идет сразу после первой
    const expectedSecondOpenTime = first.openTime + sourceIntervalMs;
    if (second.openTime !== expectedSecondOpenTime) {
      logger.warn(
        `[Combiner] Gap detected at index ${i}: expected ${expectedSecondOpenTime}, got ${second.openTime}`,
        DColors.yellow
      );
      i += 2;
      continue;
    }

    result.push({
      openTime: first.openTime,
      openPrice: first.openPrice,
      highPrice: Math.max(first.highPrice, second.highPrice),
      lowPrice: Math.min(first.lowPrice, second.lowPrice),
      closePrice: second.closePrice,
      volume: first.volume + second.volume,
      volumeDelta: (first.volumeDelta || 0) + (second.volumeDelta || 0),
      openInterest: first.openInterest ?? null,
      fundingRate: first.fundingRate ?? second.fundingRate ?? null,
    });

    i += 2;
  }

  logger.info(
    `[Combiner] Combined: ${candles.length} → ${result.length} candles`,
    DColors.cyan
  );

  return result;
}

/**
 * Комбинирует данные для всех монет
 */
export function combineCoinResults(
  results: CoinMarketData[]
): CoinMarketData[] {
  return results.map((coinResult) => ({
    symbol: coinResult.symbol,
    exchanges: coinResult.exchanges,
    category: coinResult.category,
    candles: combineCandles(coinResult.symbol, coinResult.candles),
  }));
}
