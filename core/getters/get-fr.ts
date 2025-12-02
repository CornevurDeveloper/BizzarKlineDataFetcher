// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file
import fetch from "node-fetch"; // <--- ДОБАВЛЕНО
import {
  Coin,
  DColors,
  FetcherResult,
  CoinMarketData,
  FailedCoinResult,
} from "../types";
import { logger } from "../utils/logger";
import { binanceFrUrl } from "../utils/urls/binance/binance-fr-url";
import { bybitFrUrl } from "../utils/urls/bybit/bybit-fr-url";
import { sleep } from "../utils/helpers"; // <--- ДОБАВЛЕНО
import { CONFIG } from "../config"; // <--- ДОБАВЛЕНО

// Константы таймфреймов в миллисекундах
const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
const FOUR_HOURS_MS = 4 * 60 * 60 * 1000;
const EIGHT_HOURS_MS = 8 * 60 * 60 * 1000;

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
];

// Нормализация времени к началу интервала
function normalizeTime(timestamp: number, intervalMs: number): number {
  return Math.floor(timestamp / intervalMs) * intervalMs;
}

/**
 * Распределение Binance FR (8h) на 4h свечи
 * 1 FR (8h) → 2 свечи (4h)
 * ИСПРАВЛЕНО: Убрана фильтрация по времени.
 */
function distributeBinanceFR(
  fundingTime: number,
  fundingRate: number
): Array<{ openTime: number; fundingRate: number }> {
  // Нормализуем fundingTime к началу 8-часового периода
  const frTimestamp = normalizeTime(fundingTime, EIGHT_HOURS_MS);

  // В 8 часах помещается 2 свечи по 4 часа
  const result: Array<{ openTime: number; fundingRate: number }> = [];

  // Первая 4h свеча (00:00-04:00)
  result.push({ openTime: frTimestamp, fundingRate });

  // Вторая 4h свеча (04:00-08:00)
  result.push({ openTime: frTimestamp + FOUR_HOURS_MS, fundingRate });

  return result;
}

/**
 * Распределение Bybit FR (2h/4h/8h) на 4h свечи
 * Автоопределение интервала и умная подгонка
 * ИСПРАВЛЕНО: Убрана фильтрация по времени.
 */
function distributeBybitFR(
  sortedData: Array<{ fundingTime: number; fundingRate: number }>
): Array<{ openTime: number; fundingRate: number }> {
  if (sortedData.length < 2) {
    return [];
  }

  // Определяем интервал FR из разницы между первыми двумя записями
  const detectedIntervalMs =
    sortedData[1].fundingTime - sortedData[0].fundingTime;

  let frIntervalMs: number;
  if (detectedIntervalMs <= TWO_HOURS_MS * 1.5) {
    frIntervalMs = TWO_HOURS_MS; // 2h
  } else if (detectedIntervalMs <= FOUR_HOURS_MS * 1.5) {
    frIntervalMs = FOUR_HOURS_MS; // 4h
  } else {
    frIntervalMs = EIGHT_HOURS_MS; // 8h
  }

  const result: Array<{ openTime: number; fundingRate: number }> = [];
  const aggregationMap = new Map<number, number[]>();

  for (const item of sortedData) {
    const frTimestamp = normalizeTime(item.fundingTime, frIntervalMs);

    if (frIntervalMs === FOUR_HOURS_MS) {
      // 4h FR → 4h свечи (1:1)
      result.push({ openTime: frTimestamp, fundingRate: item.fundingRate });
    } else if (frIntervalMs === EIGHT_HOURS_MS) {
      // 8h FR → 2 свечи по 4h
      result.push({
        openTime: frTimestamp,
        fundingRate: item.fundingRate,
      });
      result.push({
        openTime: frTimestamp + FOUR_HOURS_MS,
        fundingRate: item.fundingRate,
      });
    } else if (frIntervalMs === TWO_HOURS_MS) {
      // 2h FR → агрегируем в 4h свечи
      const normalizedCandleTime = normalizeTime(frTimestamp, FOUR_HOURS_MS);
      if (!aggregationMap.has(normalizedCandleTime)) {
        aggregationMap.set(normalizedCandleTime, []);
      }
      aggregationMap.get(normalizedCandleTime)!.push(item.fundingRate);
    }
  }

  // Усредняем агрегированные 2h FR в 4h свечи
  for (const [candleTime, rates] of aggregationMap.entries()) {
    const avgRate = rates.reduce((a, b) => a + b, 0) / rates.length;
    result.push({ openTime: candleTime, fundingRate: avgRate });
  }

  return result.sort((a, b) => a.openTime - b.openTime);
}

// Получение данных для одной монеты с Binance
async function fetchBinanceFundingRate(
  coin: Coin,
  limit: number,
  delayMs: number = 0
): Promise<any> {
  try {
    // Задержка теперь управляется в fetchInBatches
    // if (delayMs > 0) {
    //   await delay(delayMs);
    // }

    const randomUserAgent =
      USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    const url = binanceFrUrl(coin.symbol, limit);
    const response = await fetch(url, {
      headers: {
        "User-Agent": randomUserAgent,
        Accept: "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        Referer: "https://www.binance.com",
        Origin: "https://www.binance.com",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    const rawData: any = await response.json(); // <--- Типизация для node-fetch

    if (!Array.isArray(rawData)) {
      throw new Error(`Invalid response for ${coin.symbol}`);
    }

    // Сортируем по времени
    const sortedData = [...rawData]
      .sort((a: any, b: any) => Number(a.fundingTime) - Number(b.fundingTime))
      .map((entry: any) => ({
        fundingTime: Number(entry.fundingTime),
        fundingRate: Number(entry.fundingRate),
      }));

    // Распределяем 8h FR на 4h свечи (БЕЗ ФИЛЬТРАЦИИ ПО ВРЕМЕНИ)
    let processedData: Array<{ openTime: number; fundingRate: number }> = [];
    for (const item of sortedData) {
      const distributed = distributeBinanceFR(
        item.fundingTime,
        item.fundingRate
      );

      processedData.push(...distributed);
    }

    // Удаляем дубликаты по openTime
    const uniqueMap = new Map<number, number>();
    for (const item of processedData) {
      uniqueMap.set(item.openTime, item.fundingRate);
    }
    processedData = Array.from(uniqueMap.entries())
      .map(([openTime, fundingRate]) => ({ openTime, fundingRate }))
      .sort((a, b) => a.openTime - b.openTime);

    return {
      success: true,
      symbol: coin.symbol,
      exchanges: coin.exchanges || [],
      processedData,
    };
  } catch (error: any) {
    logger.error(
      `${coin.symbol} [BINANCE] ошибка: ${error.message}`,
      DColors.red
    );
    return {
      success: false,
      symbol: coin.symbol,
      error: error.message.replace(/[<>'"]/g, ""),
    };
  }
}

// Получение данных для одной монеты с Bybit
async function fetchBybitFundingRate(
  coin: Coin,
  limit: number,
  delayMs: number = 0
): Promise<any> {
  try {
    // Задержка теперь управляется в fetchInBatches
    // if (delayMs > 0) {
    //   await delay(delayMs);
    // }

    const randomUserAgent =
      USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    const url = bybitFrUrl(coin.symbol, limit);

    const response = await fetch(url, {
      headers: {
        "User-Agent": randomUserAgent,
        Accept: "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        Referer: "https://www.bybit.com",
        Origin: "https://www.bybit.com",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    const rawData: any = await response.json(); // <--- Типизация для node-fetch

    if (!rawData?.result?.list || !Array.isArray(rawData.result.list)) {
      throw new Error(`Invalid response for ${coin.symbol}`);
    }

    const list = rawData.result.list;
    if (list.length === 0) {
      throw new Error(`No data for ${coin.symbol}`);
    }

    // Сортируем по времени
    const sortedData = [...list]
      .sort(
        (a: any, b: any) =>
          Number(a.fundingRateTimestamp) - Number(b.fundingRateTimestamp)
      )
      .map((entry: any) => ({
        fundingTime: Number(entry.fundingRateTimestamp),
        fundingRate: Number(entry.fundingRate),
      }));

    // Распределяем FR (БЕЗ ФИЛЬТРАЦИИ ПО ВРЕМЕНИ)
    const processedData = distributeBybitFR(sortedData);

    if (coin.symbol === "BTCUSDT") {
      logger.warn(
        `[DEBUG: get-fr.ts | BYBIT] 5 последних ЧИСТЫХ 4h openTime для BTCUSDT:`,
        DColors.yellow
      );
    }

    return {
      success: true,
      symbol: coin.symbol,
      exchanges: coin.exchanges || [],
      processedData,
    };
  } catch (error: any) {
    logger.error(
      `${coin.symbol} [BYBIT] ошибка: ${error.message}`,
      DColors.red
    );
    return {
      success: false,
      symbol: coin.symbol,
      error: error.message.replace(/[<>'"]/g, ""),
    };
  }
}

// Обработка батчами для контроля нагрузки
async function fetchInBatches<T>(
  items: T[],
  batchSize: number,
  processor: (item: T) => Promise<any>
): Promise<any[]> {
  const results: any[] = [];
  const DELAY_BETWEEN_BATCHES = CONFIG.THROTTLING.DELAY_MS; // <--- ИСПОЛЬЗУЕМ CONFIG
  const effectiveBatchSize = CONFIG.THROTTLING.BATCH_SIZE; // <--- ИСПОЛЬЗУЕМ CONFIG

  for (let i = 0; i < items.length; i += effectiveBatchSize) {
    const batch = items.slice(i, i + effectiveBatchSize);

    // 1. Выполняем запросы в батче ПАРАЛЛЕЛЬНО (Promise.all)
    const batchResults = await Promise.all(batch.map(processor));
    results.push(...batchResults);

    // 2. Логируем прогресс
    logger.info(
      `Прогресс: ${Math.min(i + effectiveBatchSize, items.length)}/${
        items.length
      } (Батч: ${effectiveBatchSize})`,
      DColors.cyan
    );

    // 3. 🛑 ГЛАВНОЕ ИСПРАВЛЕНИЕ: Ждем 400ms между батчами
    if (i + effectiveBatchSize < items.length) {
      await sleep(DELAY_BETWEEN_BATCHES);
    }
  }

  return results;
}

// Получение данных для одной монеты с выбранной биржи
function fetchFundingRateData(
  coin: Coin,
  exchange: "binance" | "bybit",
  limit: number,
  delayMs: number = 0
): Promise<any> {
  if (exchange === "binance") {
    // Передаем 0, т.к. задержка управляется в fetchInBatches
    return fetchBinanceFundingRate(coin, limit, 0);
  } else {
    return fetchBybitFundingRate(coin, limit, 0);
  }
}

// Основная функция - получение данных для всех монет
export async function fetchFundingRate(
  coins: Coin[],
  exchange: "binance" | "bybit",
  limit: number,
  options?: {
    batchSize?: number;
    delayMs?: number;
  }
): Promise<FetcherResult> {
  const batchSize = options?.batchSize || CONFIG.THROTTLING.BATCH_SIZE; // <--- ИСПОЛЬЗУЕМ CONFIG
  // const delayMs = options?.delayMs || 0;
  logger.info(
    `Начало загрузки ${exchange.toUpperCase()} FR для ${
      coins.length
    } монет | БАТЧ: ${CONFIG.THROTTLING.BATCH_SIZE} | ЗАДЕРЖКА: ${
      CONFIG.THROTTLING.DELAY_MS
    }ms между батчами`, // <--- ИСПОЛЬЗУЕМ CONFIG
    DColors.cyan
  );

  const results = await fetchInBatches(
    coins,
    batchSize,
    (coin) => fetchFundingRateData(coin, exchange, limit, 0) // Передаем 0 в fetchFundingRateData
  );

  const successfulRaw = results.filter((r) => r.success);
  const failedRaw = results.filter((r) => !r.success);

  const successful: CoinMarketData[] = successfulRaw.map((item) => ({
    symbol: item.symbol,
    exchanges: item.exchanges || [],
    category: item.category || 0,
    candles: item.processedData.map((d: any) => ({
      openTime: d.openTime,
      fundingRate: d.fundingRate,
    })),
  }));

  const failed: FailedCoinResult[] = failedRaw.map((item) => ({
    symbol: item.symbol,
    error: item.error,
  }));

  logger.info(
    `✓ Успешно: ${successful.length} | ✗ Ошибок: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );

  return {
    successful,
    failed,
  };
}
