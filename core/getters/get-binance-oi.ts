// deno-lint-ignore-file no-explicit-any
// @ts-ignore-file
import fetch from "node-fetch"; // <--- ДОБАВЛЕНО
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
import { sleep } from "../utils/helpers"; // <--- ДОБАВЛЕНО
import { CONFIG } from "../config"; // <--- ДОБАВЛЕНО

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
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
];
function normalizeTime(timestamp: number, timeframe: TF): number {
  const intervalMs = INTERVALS[timeframe];
  return Math.floor(timestamp / intervalMs) * intervalMs;
}

// УДАЛЕНА ЛОКАЛЬНАЯ ФУНКЦИЯ delay
function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchCoinOI(
  symbol: string,
  timeframe: TF,
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
    const url = binanceOiUrl(symbol, timeframe, limit);

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

    return {
      success: true,
      symbol,
      processedData,
    };
  } catch (error: any) {
    logger.error(`${symbol} ошибка: ${error.message}`, DColors.red);
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

export async function fetchBinanceOI(
  coins: Coin[],
  timeframe: TF,
  limit: number,
  options?: {
    batchSize?: number;
    delayMs?: number;
  }
): Promise<FetcherResult> {
  const batchSize = options?.batchSize || CONFIG.THROTTLING.BATCH_SIZE; // <--- ИСПОЛЬЗУЕМ CONFIG

  logger.info(
    `Начало загрузки Binance OI для ${coins.length} монет [${timeframe}] | БАТЧ: ${CONFIG.THROTTLING.BATCH_SIZE} | ЗАДЕРЖКА: ${CONFIG.THROTTLING.DELAY_MS}ms между батчами`,
    DColors.yellow
  );
  // Передаем 0 в fetchCoinOI, чтобы он не делал двойную задержку
  const results = await fetchInBatches(coins, batchSize, (coin) =>
    fetchCoinOI(coin.symbol, timeframe, limit, 0)
  );
  const successfulRaw = results.filter((r) => r.success);
  const failedRaw = results.filter((r) => !r.success);

  const successful: CoinMarketData[] = successfulRaw.map((item) => {
    const originalCoin = coins.find((c) => c.symbol === item.symbol);
    return {
      symbol: item.symbol,
      exchanges: originalCoin?.exchanges || [],
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
    `✓ Успешно: ${successful.length} | ✗ Ошибок: ${failed.length}`,
    successful.length > 0 ? DColors.green : DColors.yellow
  );
  return { successful, failed };
}
