// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file
import fetch from "node-fetch";
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
import { sleep } from "../utils/helpers";
import { CONFIG } from "../config"; // <--- Глобальный конфиг

// Константы таймфреймов в миллисекундах
const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
const FOUR_HOURS_MS = 4 * 60 * 60 * 1000;
const EIGHT_HOURS_MS = 8 * 60 * 60 * 1000;

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
];

function normalizeTime(timestamp: number, intervalMs: number): number {
  return Math.floor(timestamp / intervalMs) * intervalMs;
}

function distributeBinanceFR(
  fundingTime: number,
  fundingRate: number
): Array<{ openTime: number; fundingRate: number }> {
  const frTimestamp = normalizeTime(fundingTime, EIGHT_HOURS_MS);
  const result: Array<{ openTime: number; fundingRate: number }> = [];
  result.push({ openTime: frTimestamp, fundingRate });
  result.push({ openTime: frTimestamp + FOUR_HOURS_MS, fundingRate });
  return result;
}

function distributeBybitFR(
  sortedData: Array<{ fundingTime: number; fundingRate: number }>
): Array<{ openTime: number; fundingRate: number }> {
  if (sortedData.length < 2) return [];

  const detectedIntervalMs =
    sortedData[1].fundingTime - sortedData[0].fundingTime;

  let frIntervalMs: number;
  if (detectedIntervalMs <= TWO_HOURS_MS * 1.5) {
    frIntervalMs = TWO_HOURS_MS;
  } else if (detectedIntervalMs <= FOUR_HOURS_MS * 1.5) {
    frIntervalMs = FOUR_HOURS_MS;
  } else {
    frIntervalMs = EIGHT_HOURS_MS;
  }

  const result: Array<{ openTime: number; fundingRate: number }> = [];
  const aggregationMap = new Map<number, number[]>();

  for (const item of sortedData) {
    const frTimestamp = normalizeTime(item.fundingTime, frIntervalMs);

    if (frIntervalMs === FOUR_HOURS_MS) {
      result.push({ openTime: frTimestamp, fundingRate: item.fundingRate });
    } else if (frIntervalMs === EIGHT_HOURS_MS) {
      result.push({ openTime: frTimestamp, fundingRate: item.fundingRate });
      result.push({
        openTime: frTimestamp + FOUR_HOURS_MS,
        fundingRate: item.fundingRate,
      });
    } else if (frIntervalMs === TWO_HOURS_MS) {
      const normalizedCandleTime = normalizeTime(frTimestamp, FOUR_HOURS_MS);
      if (!aggregationMap.has(normalizedCandleTime)) {
        aggregationMap.set(normalizedCandleTime, []);
      }
      aggregationMap.get(normalizedCandleTime)!.push(item.fundingRate);
    }
  }

  for (const [candleTime, rates] of aggregationMap.entries()) {
    const avgRate = rates.reduce((a, b) => a + b, 0) / rates.length;
    result.push({ openTime: candleTime, fundingRate: avgRate });
  }

  return result.sort((a, b) => a.openTime - b.openTime);
}

async function fetchBinanceFundingRate(
  coin: Coin,
  limit: number
): Promise<any> {
  try {
    const randomUserAgent =
      USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    const url = binanceFrUrl(coin.symbol, limit);
    const response = await fetch(url, {
      headers: {
        "User-Agent": randomUserAgent,
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const rawData: any = await response.json();

    if (!Array.isArray(rawData)) {
      throw new Error(`Invalid response for ${coin.symbol}`);
    }

    const sortedData = [...rawData]
      .sort((a: any, b: any) => Number(a.fundingTime) - Number(b.fundingTime))
      .map((entry: any) => ({
        fundingTime: Number(entry.fundingTime),
        fundingRate: Number(entry.fundingRate),
      }));

    let processedData: Array<{ openTime: number; fundingRate: number }> = [];
    for (const item of sortedData) {
      const distributed = distributeBinanceFR(
        item.fundingTime,
        item.fundingRate
      );
      processedData.push(...distributed);
    }

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
      `${coin.symbol} [BINANCE FR] ошибка: ${error.message}`,
      DColors.red
    );
    return { success: false, symbol: coin.symbol, error: error.message };
  }
}

async function fetchBybitFundingRate(coin: Coin, limit: number): Promise<any> {
  try {
    const randomUserAgent =
      USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    const url = bybitFrUrl(coin.symbol, limit);

    const response = await fetch(url, {
      headers: {
        "User-Agent": randomUserAgent,
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const rawData: any = await response.json();

    if (!rawData?.result?.list || !Array.isArray(rawData.result.list)) {
      throw new Error(`Invalid response for ${coin.symbol}`);
    }

    const list = rawData.result.list;
    if (list.length === 0) {
      throw new Error(`No data for ${coin.symbol}`);
    }

    const sortedData = [...list]
      .sort(
        (a: any, b: any) =>
          Number(a.fundingRateTimestamp) - Number(b.fundingRateTimestamp)
      )
      .map((entry: any) => ({
        fundingTime: Number(entry.fundingRateTimestamp),
        fundingRate: Number(entry.fundingRate),
      }));

    const processedData = distributeBybitFR(sortedData);

    return {
      success: true,
      symbol: coin.symbol,
      exchanges: coin.exchanges || [],
      processedData,
    };
  } catch (error: any) {
    logger.error(
      `${coin.symbol} [BYBIT FR] ошибка: ${error.message}`,
      DColors.red
    );
    return { success: false, symbol: coin.symbol, error: error.message };
  }
}

/**
 * Внутренняя функция батчей теперь СТРОГО использует CONFIG
 * + принимает label для логов
 */
async function fetchInBatches<T>(
  items: T[],
  label: string,
  processor: (item: T) => Promise<any>
): Promise<any[]> {
  const results: any[] = [];

  // Приоритет CONFIG
  const batchSize = CONFIG.THROTTLING.BATCH_SIZE;
  const delayMs = CONFIG.THROTTLING.DELAY_MS;

  for (let i = 0; i < items.length; i += batchSize) {
    const batch = items.slice(i, i + batchSize);

    const batchResults = await Promise.all(batch.map(processor));
    results.push(...batchResults);

    logger.info(
      `[${label}] Прогресс: ${Math.min(i + batchSize, items.length)}/${
        items.length
      } (Batch: ${batchSize})`,
      DColors.cyan
    );

    if (i + batchSize < items.length) {
      await sleep(delayMs);
    }
  }

  return results;
}

function fetchFundingRateData(
  coin: Coin,
  exchange: "binance" | "bybit",
  limit: number
): Promise<any> {
  if (exchange === "binance") {
    return fetchBinanceFundingRate(coin, limit);
  } else {
    return fetchBybitFundingRate(coin, limit);
  }
}

export async function fetchFundingRate(
  coins: Coin[],
  exchange: "binance" | "bybit",
  limit: number,
  _options?: any // Игнорируем опции
): Promise<FetcherResult> {
  const label = `${exchange.toUpperCase()} FR`;

  logger.info(
    `[${label}] Запуск по CONFIG: Батч ${CONFIG.THROTTLING.BATCH_SIZE}, Задержка ${CONFIG.THROTTLING.DELAY_MS}ms`,
    DColors.cyan
  );

  const results = await fetchInBatches(coins, label, (coin) =>
    fetchFundingRateData(coin, exchange, limit)
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
    `[${label}] ✓ Успешно: ${successful.length} | ✗ Ошибок: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );

  return { successful, failed };
}
