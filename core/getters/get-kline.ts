// @ts-ignore-file
import fetch from "node-fetch";

import { bybitPerpUrl } from "../utils/urls/bybit/bybit-perps-url";
import { binancePerpsUrl } from "../utils/urls/binance/binance-perps-url";
import {
  TF,
  DColors,
  Coin,
  FetcherResult,
  CoinMarketData,
  FailedCoinResult,
} from "../types";
import { logger } from "../utils/logger";
import { sleep } from "../utils/helpers"; // <--- ДОБАВЛЕНО
import { CONFIG } from "../config"; // <--- ДОБАВЛЕНО

const BYBIT_INTERVALS: Record<TF, string> = {
  "1h": "60",
  "4h": "240",
  "8h": "240",
  "12h": "720",
  D: "720",
};
const BINANCE_INTERVALS: Record<TF, string> = {
  "1h": "1h",
  "4h": "4h",
  "8h": "8h",
  "12h": "12h",
  D: "1d",
};
const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
];
// УДАЛЕНА ЛОКАЛЬНАЯ ФУНКЦИЯ delay
function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isAlignedToTimeframe(timestamp: number, targetInterval: TF): boolean {
  const date = new Date(timestamp);
  const hours = date.getUTCHours();
  if (targetInterval === "8h") return hours % 8 === 0;
  if (targetInterval === "D") return hours === 0;
  return true;
}

function findFirstAlignedIndex(data: any[], targetInterval: TF): number {
  for (let i = 0; i < data.length; i++) {
    const timestamp = parseInt(data[i][0]);
    if (isAlignedToTimeframe(timestamp, targetInterval)) return i;
  }
  return -1;
}

function resampleKlines(
  data: any[],
  sourceInterval: TF,
  targetInterval: TF
): any[] {
  const ratios: Record<string, number> = { "4h->8h": 2, "12h->D": 2 };
  const key = `${sourceInterval}->${targetInterval}`;
  const ratio = ratios[key];

  if (!ratio || ratio <= 1) return data;
  const startIndex = findFirstAlignedIndex(data, targetInterval);
  if (startIndex === -1) return [];

  const resampled: any[] = [];
  for (let i = startIndex; i < data.length; i += ratio) {
    const chunk = data.slice(i, i + ratio);
    if (chunk.length !== ratio) continue;

    const chunkStartTime = parseInt(chunk[0][0]);
    if (!isAlignedToTimeframe(chunkStartTime, targetInterval)) continue;

    const open = parseFloat(chunk[0][1]);
    const high = Math.max(...chunk.map((c: any) => parseFloat(c[2])));
    const low = Math.min(...chunk.map((c: any) => parseFloat(c[3])));
    const close = parseFloat(chunk[chunk.length - 1][4]);
    const volume = chunk.reduce(
      (sum: number, c: any) => sum + parseFloat(c[5]),
      0
    );
    const openTime = parseInt(chunk[0][0]);
    const closeTime = parseInt(chunk[chunk.length - 1][6]);

    resampled.push([openTime, open, high, low, close, volume, closeTime]);
  }
  return resampled;
}

async function fetchBinanceKlineData(
  symbol: string,
  timeframe: TF,
  limit: number,
  delayMs: number
): Promise<any> {
  // delayMs больше не используется
  // if (delayMs > 0) await delay(delayMs);
  const interval = BINANCE_INTERVALS[timeframe];
  const url = binancePerpsUrl(symbol, interval, limit);
  const randomUserAgent =
    USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
  const response = await fetch(url, {
    headers: {
      "User-Agent": randomUserAgent,
      Accept: "application/json",
      "Accept-Language": "en-US,en;q=0.9",
      Referer: "https://www.binance.com",
      Origin: "https://www.binance.com",
    },
  });
  if (!response.ok)
    throw new Error(`HTTP ${response.status}: ${await response.text()}`);

  const rawData: any = await response.json();
  if (!Array.isArray(rawData))
    throw new Error(`Invalid Binance response for ${symbol}`);
  const klines = rawData.sort(
    (a: any, b: any) => parseInt(a[0]) - parseInt(b[0])
  );
  let processedData = klines.map((entry: any) => {
    const totalQuoteVolume = parseFloat(entry[7]);
    const takerBuyQuote = parseFloat(entry[10]);
    const sellerQuoteVolume = totalQuoteVolume - takerBuyQuote;
    const volumeDelta = takerBuyQuote - sellerQuoteVolume;

    return {
      openTime: parseInt(entry[0]),
      openPrice: parseFloat(entry[1]),
      highPrice: parseFloat(entry[2]),
      lowPrice: parseFloat(entry[3]),
      closePrice: parseFloat(entry[4]),
      volume: totalQuoteVolume,
      volumeDelta: parseFloat(volumeDelta.toFixed(2)),
      closeTime: parseInt(entry[6]),
    };
  });
  if (processedData.length > 2) {
    processedData = processedData.slice(0, -1);
  }

  return processedData;
}

async function fetchBybitKlineData(
  symbol: string,
  timeframe: TF,
  limit: number,
  delayMs: number
): Promise<any> {
  // delayMs больше не используется
  // if (delayMs > 0) await delay(delayMs);
  const bybitInterval = BYBIT_INTERVALS[timeframe];
  const fetchLimit =
    timeframe === "8h" || timeframe === "D" ? Math.ceil(limit * 2.2) : limit;
  const url = bybitPerpUrl(symbol, bybitInterval, fetchLimit);
  const randomUserAgent =
    USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
  const response = await fetch(url, {
    headers: {
      "User-Agent": randomUserAgent,
      Accept: "application/json",
      "Accept-Language": "en-US,en;q=0.9",
      Referer: "https://www.bybit.com",
      Origin: "https://www.bybit.com",
    },
  });
  if (!response.ok)
    throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  const rawData: any = await response.json();
  if (!rawData?.result?.list)
    throw new Error(`Invalid Bybit response for ${symbol}`);

  let klines = rawData.result.list;
  if (klines.length === 0) throw new Error(`No data for ${symbol}`);
  klines = [...klines].sort(
    (a: any, b: any) => parseInt(a[0]) - parseInt(b[0])
  );

  // --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
  if (timeframe === "8h") klines = resampleKlines(klines, "4h", "8h");
  else if (timeframe === "D") klines = resampleKlines(klines, "12h", "D");
  // --- КОНЕЦ ИСПРАВЛЕНИЯ ---

  if (klines.length === 0) throw new Error(`No aligned candles for ${symbol}`);
  let processedData = klines.map((entry: any) => ({
    openTime: parseInt(entry[0]),
    openPrice: parseFloat(entry[1]),
    highPrice: parseFloat(entry[2]),
    lowPrice: parseFloat(entry[3]),
    closePrice: parseFloat(entry[4]),
    volume: parseFloat(entry[7]),
    volumeDelta: 0,
    closeTime: parseInt(entry[6]),
  }));
  if (processedData.length > 2) {
    processedData = processedData.slice(0, -1);
  }

  return processedData;
}

async function fetchKlineData(
  symbol: string,
  exchange: "binance" | "bybit",
  timeframe: TF,
  limit: number,
  delayMs: number
): Promise<any> {
  try {
    let data: any[] = [];
    if (exchange === "binance") {
      // delayMs не передаем, т.к. задержка управляется в fetchInBatches
      data = await fetchBinanceKlineData(symbol, timeframe, limit, 0);
    } else {
      data = await fetchBybitKlineData(symbol, timeframe, limit, 0);
    }

    if (data.length > 0) {
      const last = data[data.length - 1];
      const date =
        new Date(last.openTime + 3 * 3600 * 1000)
          .toISOString()
          .replace("T", " ")
          .substring(0, 19) + " MSK";
      // logger.info(
      //   `${symbol} [${exchange.toUpperCase()} ${timeframe}] → ${
      //     data.length
      //   } candles | Last: ${date} | Close: ${last.closePrice}`,
      //   DColors.green
      // );
    }

    return {
      success: true,
      symbol,
      data,
    };
  } catch (error: any) {
    // --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    logger.error(
      `${symbol} [${exchange}] error: ${error.message}`,
      error // Передаем сам объект 'error'
    );
    // --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    return {
      success: false,
      symbol,
      error: error.message.replace(/[<>'"]/g, ""),
    };
  }
}

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
      `Progress: ${Math.min(i + effectiveBatchSize, items.length)}/${
        items.length
      } (Batch: ${effectiveBatchSize})`,
      DColors.cyan
    );

    // 3. 🛑 ГЛАВНОЕ ИСПРАВЛЕНИЕ: Ждем 400ms между батчами
    if (i + effectiveBatchSize < items.length) {
      await sleep(DELAY_BETWEEN_BATCHES);
    }
  }

  return results;
}

export async function fetchKlines(
  coins: Coin[],
  exchange: "binance" | "bybit",
  timeframe: TF,
  limit: number,
  options?: {
    batchSize?: number;
    delayMs?: number;
  }
): Promise<FetcherResult> {
  const batchSize = options?.batchSize || CONFIG.THROTTLING.BATCH_SIZE; // <--- ИСПОЛЬЗУЕМ CONFIG

  logger.info(
    `Fetching ${exchange.toUpperCase()} Klines for ${
      coins.length
    } coins [${timeframe}] | БАТЧ: ${
      CONFIG.THROTTLING.BATCH_SIZE
    } | ЗАДЕРЖКА: ${CONFIG.THROTTLING.DELAY_MS}ms между батчами`,
    DColors.cyan
  );
  const results = await fetchInBatches(
    coins,
    batchSize,
    (coin) => fetchKlineData(coin.symbol, exchange, timeframe, limit, 0) // Передаем 0 в fetchKlineData
  );
  const successfulRaw = results.filter((r) => r.success);
  const failedRaw = results.filter((r) => !r.success);

  const successful: CoinMarketData[] = successfulRaw.map((item) => {
    const originalCoin = coins.find((c) => c.symbol === item.symbol);

    return {
      symbol: item.symbol,
      exchanges: originalCoin?.exchanges || [],
      candles: item.data.map((d: any) => ({
        openTime: d.openTime,
        openPrice: d.openPrice,
        highPrice: d.highPrice,
        lowPrice: d.lowPrice,
        closePrice: d.closePrice,
        volume: d.volume,
        volumeDelta: d.volumeDelta,
      })),
    };
  });

  const failed: FailedCoinResult[] = failedRaw.map((item) => ({
    symbol: item.symbol,
    error: item.error,
  }));
  logger.info(
    `✓ Success: ${successful.length} | ✗ Failed: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );
  return { successful, failed };
}
