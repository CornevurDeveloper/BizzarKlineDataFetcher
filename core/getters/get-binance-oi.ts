// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file
import fetch from "node-fetch";
import {
  TF,
  DColors,
  Coin,
  FetcherResult,
  CoinMarketData,
  FailedCoinResult,
} from "../types";
import { logger } from "../utils/logger";
import { binanceOiUrl } from "../utils/urls/binance/binance-oi-url";
import { sleep } from "../utils/helpers";
import { CONFIG } from "../config"; // <--- Глобальный конфиг
import { binanceQueue } from "../utils/smart-queue";

const INTERVALS: Record<TF, number> = {
  "1h": 60 * 60 * 1000,
  "4h": 4 * 60 * 60 * 1000,
  "8h": 8 * 60 * 60 * 1000,
  "12h": 12 * 60 * 60 * 1000,
  D: 24 * 60 * 60 * 1000,
};

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
];

function normalizeTime(timestamp: number, timeframe: TF): number {
  const intervalMs = INTERVALS[timeframe];
  return Math.floor(timestamp / intervalMs) * intervalMs;
}

async function fetchCoinOI(
  symbol: string,
  timeframe: TF,
  limit: number
): Promise<any> {
  try {
    const randomUserAgent =
      USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    const url = binanceOiUrl(symbol, timeframe, limit);

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
      throw new Error(`Invalid response for ${symbol}`);
    }

    const sortedData = [...rawData].sort((a, b) => a.timestamp - b.timestamp);
    let processedData = sortedData.map((entry) => ({
      openTime: normalizeTime(Number(entry.timestamp), timeframe),
      openInterest: Number(entry.sumOpenInterestValue),
    }));

    if (processedData.length > 2) {
      processedData = processedData.slice(0, -1);
    }

    return { success: true, symbol, processedData };
  } catch (error: any) {
    return { success: false, symbol, error: error.message };
  }
}



export async function fetchBinanceOI(
  coins: Coin[],
  timeframe: TF,
  limit: number,
  _options?: any
): Promise<FetcherResult> {
  logger.info(
    `[BINANCE OI] Добавление ${coins.length} задач в глобальную очередь...`,
    DColors.yellow
  );

  const tasks = coins.map((coin) =>
    binanceQueue.add(() => fetchCoinOI(coin.symbol, timeframe, limit))
  );

  const results = await Promise.all(tasks);

  const successfulRaw = results.filter((r) => r.success);
  const failedRaw = results.filter((r) => !r.success);

  const successful: CoinMarketData[] = successfulRaw.map((item) => {
    const originalCoin = coins.find((c) => c.symbol === item.symbol);
    return {
      symbol: item.symbol,
      exchanges: originalCoin?.exchanges || [],
      category: originalCoin?.category || 0,
      candles: item.processedData.map((d: any) => ({
        openTime: d.openTime,
        openInterest: d.openInterest,
      })),
    };
  });

  const failed: FailedCoinResult[] = failedRaw.map((item) => ({
    symbol: item.symbol,
    error: item.error,
  }));

  logger.info(
    `[BINANCE OI] ✓ Успешно: ${successful.length} | ✗ Ошибок: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );

  return { successful, failed };
}
