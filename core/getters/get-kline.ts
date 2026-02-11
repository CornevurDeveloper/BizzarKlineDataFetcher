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
import { sleep, TIMEFRAME_MS } from "../utils/helpers";
import { CONFIG } from "../config"; // <--- Глобальный конфиг
import { binanceQueue, bybitQueue } from "../utils/smart-queue";

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
  limit: number
): Promise<any> {
  const interval = BINANCE_INTERVALS[timeframe];
  const url = binancePerpsUrl(symbol, interval, limit);
  const randomUserAgent =
    USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];

  const response = await fetch(url, {
    headers: {
      "User-Agent": randomUserAgent,
      Accept: "application/json",
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
  limit: number
): Promise<any> {
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

  if (timeframe === "8h") klines = resampleKlines(klines, "4h", "8h");
  else if (timeframe === "D") klines = resampleKlines(klines, "12h", "D");

  if (klines.length === 0) throw new Error(`No aligned candles for ${symbol}`);

  // Get timeframe in ms for closeTime calculation
  const timeframeMs = TIMEFRAME_MS[timeframe];

  let processedData = klines.map((entry: any) => ({
    openTime: parseInt(entry[0]),
    openPrice: parseFloat(entry[1]),
    highPrice: parseFloat(entry[2]),
    lowPrice: parseFloat(entry[3]),
    closePrice: parseFloat(entry[4]),
    volume: parseFloat(entry[6]), // Index 6 is Turnover (Quote Volume/USDT)
    volumeDelta: 0,
    // Calculate closeTime: start + interval - 1ms
    closeTime: parseInt(entry[0]) + timeframeMs - 1,
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
  limit: number
): Promise<any> {
  try {
    let data: any[] = [];
    if (exchange === "binance") {
      data = await fetchBinanceKlineData(symbol, timeframe, limit);
    } else {
      data = await fetchBybitKlineData(symbol, timeframe, limit);
    }

    return { success: true, symbol, data };
  } catch (error: any) {
    logger.error(
      `${symbol} [${exchange.toUpperCase()} KLINE] error: ${error.message}`,
      error
    );
    return { success: false, symbol, error: error.message };
  }
}

/**
 * Внутренняя функция батчей теперь СТРОГО использует CONFIG
 * + принимает label для логов
 */


export async function fetchKlines(
  coins: Coin[],
  exchange: "binance" | "bybit",
  timeframe: TF,
  limit: number,
  _options?: any // Игнорируем опции
): Promise<FetcherResult> {
  const label = `${exchange.toUpperCase()} KLINE`;

  logger.info(
    `[${label}] Adding ${coins.length} tasks to global queues...`,
    DColors.cyan
  );

  const tasks = coins.map((coin) => {
    if (exchange === "binance") {
      return binanceQueue.add(() => fetchKlineData(coin.symbol, exchange, timeframe, limit));
    } else {
      return bybitQueue.add(() => fetchKlineData(coin.symbol, exchange, timeframe, limit));
    }
  });

  const results = await Promise.all(tasks);

  const successfulRaw = results.filter((r) => r.success);
  const failedRaw = results.filter((r) => !r.success);

  const successful: CoinMarketData[] = successfulRaw.map((item) => {
    const originalCoin = coins.find((c) => c.symbol === item.symbol);

    return {
      symbol: item.symbol,
      exchanges: originalCoin?.exchanges || [],
      category: originalCoin?.category || 0,
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
    `[${label}] ✓ Success: ${successful.length} | ✗ Failed: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );

  return { successful, failed };
}
