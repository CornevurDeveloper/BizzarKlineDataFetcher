import { Candle, CoinMarketData, FetcherResult, TF, DColors } from "../types";
import { logger } from "../utils/logger";

/**
 * Обогащает свечу данными OI
 * Правило: берём ПЕРВУЮ 1h OI свечу, где oi1h.openTime >= candle.openTime
 */
function enrichCandleWithOI(candle: Candle, oi1hCandles: Candle[]): void {
  const match = oi1hCandles.find((oi) => oi.openTime >= candle.openTime);
  candle.openInterest = match?.openInterest ?? null;
}

/**
 * Обогащает свечу данными FR
 * Правило: точное совпадение fr.openTime === candle.openTime
 *
 * ### ИЗМЕНЕНИЕ №3.1: Сигнатура изменена
 */
function enrichCandleWithFR(
  _symbol: string,
  candle: Candle,
  frCandles: Candle[]
): void {
  // ИСПРАВЛЕННАЯ ЛОГИКА (которую вы уже пробовали)
  const TIME_FUZZ_MS = 5000; // Допуск в 5 секунд для "шума"

  // --- ИСПРАВЛЕНИЕ ОШИБКИ TS (ES2023) ---
  // .findLast() - это слишком новая функция (ES2023).
  // Заменяем ее на более совместимый аналог:
  const match = [...frCandles] // 1. Создаем копию (чтобы .reverse() не изменил оригинал)
    .reverse() // 2. Переворачиваем массив
    .find(
      // 3. Находим ПЕРВЫЙ элемент, который подходит
      (fr: Candle) => fr.openTime <= candle.openTime + TIME_FUZZ_MS
    );
  // --- КОНЕЦ ИСПРАВЛЕНИЯ ---

  candle.fundingRate = match?.fundingRate ?? null;
}

/**
 * Обогащает массив свечей одной монеты
 */
function enrichCoinCandles(
  symbol: string,
  candles: Candle[],
  oi1hData: Map<string, Candle[]>,
  frData?: Map<string, Candle[]>,
  includeFR: boolean = false
): void {
  const oi1hCandles = oi1hData.get(symbol) || [];
  const frCandles = frData?.get(symbol) || [];

  for (const candle of candles) {
    // OI обогащение (всегда)
    enrichCandleWithOI(candle, oi1hCandles);
    // FR обогащение (только для 4h и 8h)
    if (includeFR && frData) {
      enrichCandleWithFR(symbol, candle, frCandles);
    }
  }
}

/**
 * Основная функция обогащения
 * Обогащает данные klines данными OI и (опционально) FR
 */
export function enrichKlines(
  klineResults: CoinMarketData[],
  oi1hResult: FetcherResult,
  timeframe: TF,
  frResult?: FetcherResult
): CoinMarketData[] {
  const includeFR = timeframe === "4h" || timeframe === "8h";

  logger.info(
    `[Enricher] Starting enrichment for ${
      klineResults.length
    } coins [${timeframe}] | OI: ✓ | FR: ${includeFR ? "✓" : "✗"}`,
    DColors.cyan
  );
  // Создаём Map для быстрого доступа к данным по symbol
  const oi1hMap = new Map<string, Candle[]>();
  for (const coin of oi1hResult.successful) {
    oi1hMap.set(coin.symbol, coin.candles);
  }

  const frMap = frResult
    ? new Map<string, Candle[]>(
        frResult.successful.map((coin) => [coin.symbol, coin.candles])
      )
    : undefined;

  // Обогащаем каждую монету
  const enriched = klineResults.map((coinResult) => {
    const candles = [...coinResult.candles]; // Копируем массив
    enrichCoinCandles(coinResult.symbol, candles, oi1hMap, frMap, includeFR);

    return {
      symbol: coinResult.symbol,
      exchanges: coinResult.exchanges,
      category: coinResult.category,
      candles,
    };
  });
  logger.info(`[Enricher] ✓ Enriched ${enriched.length} coins`, DColors.green);

  return enriched;
}

/**
 * Вспомогательная функция: обрезает свечи до нужного количества
 */
export function trimCandles(
  results: CoinMarketData[],
  limit: number
): CoinMarketData[] {
  return results.map((coinResult) => ({
    symbol: coinResult.symbol,
    exchanges: coinResult.exchanges,
    category: coinResult.category,
    candles: coinResult.candles.slice(-limit), // Берём последние limit свечей
  }));
}
