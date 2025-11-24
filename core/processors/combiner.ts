import { Candle, DColors, CoinMarketData } from "../types";
import { logger } from "../utils/logger";

/**
 * Комбинирует свечи в соотношении 2:1
 * Используется для:
 * - 4h → 8h
 * - 12h → 1D
 *
 * FR для 8h свечи берётся из первой 4h свечи
 *
 * ### ИЗМЕНЕНИЕ №5.1: Сигнатура изменена
 */
export function combineCandles(_symbol: string, candles: Candle[]): Candle[] {
  if (candles.length < 2) {
    logger.error("[Combiner] Not enough candles to combine", DColors.red);
    return [];
  }

  if (candles.length % 2 !== 0) {
    logger.warn(
      `[Combiner] Odd number of candles (${candles.length}), last one will be skipped`,
      DColors.yellow
    );
  }

  const result: Candle[] = [];

  for (let i = 0; i < candles.length - 1; i += 2) {
    const first = candles[i];
    const second = candles[i + 1];

    // ### ИЗМЕНЕНИЕ №5.2: ДОБАВЛЕН ЛОГ ###
    // if (symbol === "BTCUSDT") {
    //   logger.warn(
    //     `[DEBUG: combiner.ts] Комбинация 8h свечи для BTCUSDT...`,
    //     DColors.yellow
    //   );
    //   console.log(
    //     `  -> 1я СВЕЧА (4h): openTime: ${first.openTime} | FR: ${first.fundingRate}`
    //   );
    //   console.log(
    //     `  -> 2я СВЕЧА (4h): openTime: ${second.openTime} | FR: ${second.fundingRate}`
    //   );
    //   console.log(
    //     `  -> РЕЗУЛЬТАТ (8h): openTime: ${first.openTime} | Итоговый FR: ${
    //       first.fundingRate ?? second.fundingRate ?? null
    //     }`
    //   );
    //   console.log(`-------------------------------------------------`);
    // }
    // ### КОНЕЦ ИЗМЕНЕНИЯ ###

    // Проверка целостности данных (== null проверяет на null и undefined, но не на 0)
    if (
      first.openPrice == null ||
      first.highPrice == null ||
      first.lowPrice == null ||
      first.closePrice == null ||
      first.volume == null
    ) {
      logger.warn(
        `[Combiner] Skipping incomplete candle at index ${i}`,
        DColors.yellow
      );
      continue;
    }

    if (
      second.openPrice == null ||
      second.highPrice == null ||
      second.lowPrice == null ||
      second.closePrice == null ||
      second.volume == null
    ) {
      logger.warn(
        `[Combiner] Skipping incomplete candle at index ${i + 1}`,
        DColors.yellow
      );
      continue;
    }

    result.push({
      openTime: first.openTime, // Время от первой свечи
      openPrice: first.openPrice,
      highPrice: Math.max(first.highPrice, second.highPrice),
      lowPrice: Math.min(first.lowPrice, second.lowPrice),
      closePrice: second.closePrice, // Close от второй свечи
      volume: first.volume + second.volume,
      volumeDelta: (first.volumeDelta || 0) + (second.volumeDelta || 0),
      // OI берём из первой свечи (или можно взять среднее)
      openInterest: first.openInterest ?? null,
      // FR берём из первой 4h свечи (обе 4h свечи имеют одинаковый FR из одного 8h периода)
      // ИСПРАВЛЕНО: Берем FR из первой, если нет - из второй
      fundingRate: first.fundingRate ?? second.fundingRate ?? null,
    });
  }

  // logger.info(
  //   `[Combiner] Combined ${candles.length} → ${result.length} candles`,
  //   DColors.green
  // );

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
    // ### ИЗМЕНЕНИЕ №4: Проброс symbol
    candles: combineCandles(coinResult.symbol, coinResult.candles),
  }));
}
