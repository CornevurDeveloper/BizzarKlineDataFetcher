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
import { binanceQueue, bybitQueue } from "../utils/smart-queue";

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

    let allRawData: any[] = [];
    let currentEndTime: number | undefined;
    const BATCH_LIMIT = 200; // Bybit max limit per request

    // Loop to fetch data until we have enough or no more data
    while (allRawData.length < limit) {
      // Calculate how many we still need
      const remaining = limit - allRawData.length;
      // Request slightly more than needed to cover overlaps or safe margins, but capped at 200
      const currentLimit = Math.min(remaining, BATCH_LIMIT);

      // Construct URL manually to support pagination
      // Note: bybitFrUrl currently only handles symbol and limit. 
      // We need to add endTime for pagination if it's not the first request.
      let url = bybitFrUrl(coin.symbol, BATCH_LIMIT); // Always request max batch size to minimize requests
      if (currentEndTime) {
        url += `&endTime=${currentEndTime}`;
      }

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
        // If it's the first request and it fails, throw error.
        // If partial data collected, maybe break? But consistency is better.
        if (allRawData.length === 0) {
          throw new Error(`Invalid response for ${coin.symbol}`);
        }
        break; // Stop fetching if response is invalid but we have some data
      }

      const list = rawData.result.list;
      if (list.length === 0) {
        if (allRawData.length === 0) {
          throw new Error(`No data for ${coin.symbol}`);
        }
        break; // No more data
      }

      // Add to collection
      allRawData = allRawData.concat(list);

      // Prepare for next iteration
      // Bybit returns data sorted by time? 
      // Actually typically it returns latest first.
      // We need the oldest timestamp in this batch to be the endTime for the next batch.
      // Let's find the minimum timestamp.
      let minTime = Infinity;
      for (const item of list) {
        const t = Number(item.fundingRateTimestamp);
        if (t < minTime) minTime = t;
      }

      if (minTime === Infinity) break; // Should not happen if list not empty

      // Set endTime for next request to minTime.
      // API documentation says endTime is exclusive? Or inclusive?
      // Usually it returns records <= endTime. 
      // To avoid duplicates, we might want minTime - 1. 
      // But verifying: "endTime: The end timestamp (ms)"
      currentEndTime = minTime; // We will dedup later anyway.

      // Safety break to prevent infinite loops if data doesn't change
      if (list.length < BATCH_LIMIT) break; // Less than limit means we reached the end
    }

    // Deduplicate based on fundingRateTimestamp and Sort
    const uniqueMap = new Map<number, any>();
    for (const item of allRawData) {
      const time = Number(item.fundingRateTimestamp);
      // If we have duplicates, it doesn't matter much which one we keep
      uniqueMap.set(time, item);
    }

    // Sort ascending
    const sortedData = Array.from(uniqueMap.values())
      .map((entry: any) => ({
        fundingTime: Number(entry.fundingRateTimestamp),
        fundingRate: Number(entry.fundingRate),
      }))
      .sort((a, b) => a.fundingTime - b.fundingTime);

    // Trim to requested limit (take latest N)
    // Since we fetched backwards, we might have more than needed.
    // We want the LATEST 'limit' items.
    const slicedData = sortedData.slice(-limit);

    const processedData = distributeBybitFR(slicedData);

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
    `[${label}] Добавление ${coins.length} задач в глобальные очереди...`,
    DColors.cyan
  );

  const tasks = coins.map((coin) => {
    if (exchange === "binance") {
      return binanceQueue.add(() => fetchFundingRateData(coin, exchange, limit));
    } else {
      return bybitQueue.add(() => fetchFundingRateData(coin, exchange, limit));
    }
  });

  const results = await Promise.all(tasks);

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
