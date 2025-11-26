// @ts-ignore-file
import "dotenv/config";
import fetch from "node-fetch";
import { DColors, MarketData, TF, TF_MAP } from "./core/types";
import { logger } from "./core/utils/logger";
import { TIMEFRAME_MS } from "./core/utils/helpers";

const BAZZAR = process.env.BAZZAR_KLINE_FETCHER_URL;
const BIZZAR = process.env.BIZZAR_KLINE_FETCHER_URL;
const SECRET_TOKEN = process.env.SECRET_TOKEN;

if (!SECRET_TOKEN) {
  logger.error("[API Test] SECRET_TOKEN не установлен");
  process.exit(1);
}

const allTimeframes: TF[] = Object.values(TF_MAP);
const needsBazzar = allTimeframes.some((tf) => ["1h", "12h", "D"].includes(tf));
const needsBizzar = allTimeframes.some((tf) => ["4h", "8h"].includes(tf));

if (needsBazzar && !BAZZAR) {
  logger.error(
    "[API Test] Переменная BAZZAR_KLINE_FETCHER_URL обязательна для таймфреймов 1h/12h/D"
  );
  process.exit(1);
}

if (needsBizzar && !BIZZAR) {
  logger.error(
    "[API Test] Переменная BIZZAR_KLINE_FETCHER_URL обязательна для таймфреймов 4h/8h"
  );
  process.exit(1);
}

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  cached?: boolean;
  age?: string;
}

/**
 * Форматирует timestamp (ms) как UTC без часовых поясов
 */
function formatAsUTC(timestamp: number): string {
  return (
    new Date(timestamp).toISOString().replace("T", " ").substring(0, 19) +
    " UTC"
  );
}

/**
 * Возвращает правильный endpoint в зависимости от таймфрейма
 */
function getApiEndpoint(tf: TF): string {
  if (["1h", "12h", "D"].includes(tf)) {
    return `${BAZZAR}/api/cache/${tf}`;
  } else if (["4h", "8h"].includes(tf)) {
    return `${BIZZAR}/api/cache/${tf}`;
  }
  throw new Error(`Неизвестный таймфрейм: ${tf}`);
}

/**
 * Определяет источник данных по таймфрейму
 */
function getSource(tf: TF): "BAZZAR" | "BIZZAR" {
  if (["1h", "12h", "D"].includes(tf)) return "BAZZAR";
  if (["4h", "8h"].includes(tf)) return "BIZZAR";
  throw new Error(`Неизвестный таймфрейм: ${tf}`);
}

async function runApiTest() {
  logger.info(`[API Test] Тестирование кэша`, DColors.cyan);
  console.log("=================================================");

  const timeframes: TF[] = Object.values(TF_MAP);
  let passed = 0;
  let failed = 0;
  const now = Date.now();

  for (const tf of timeframes) {
    const url = getApiEndpoint(tf);
    const source = getSource(tf);

    logger.info(`[API TEST] ${tf} (${source})`, DColors.yellow);

    try {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${SECRET_TOKEN}` },
      });

      if (!response.ok) {
        logger.error(`  ✗ HTTP ${response.status}`);
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      const result = (await response.json()) as ApiResponse<MarketData>;

      if (!result.success || !result.data) {
        logger.error(`  ✗ ${result.error}`);
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      const data = result.data;

      // ✅ Проверка 1: Структура данных
      if (!data.data || data.data.length === 0) {
        logger.error(`  ✗ Нет данных`);
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      logger.info(`  ✓ Структура: ${data.coinsNumber} coins`, DColors.green);

      // ✅ Проверка 2: Свечи есть
      const coin = data.data[0];
      if (!coin.candles || coin.candles.length === 0) {
        logger.error(`  ✗ Нет свечей для ${coin.symbol}`);
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      logger.info(
        `  ✓ Свечи: ${coin.candles.length} candles для ${coin.symbol}`,
        DColors.green
      );

      // ✅ Проверка 3: Свежесть
      const lastCandle = coin.candles[coin.candles.length - 1];
      const timeframeMs = TIMEFRAME_MS[tf];

      // Проверка сетки: openTime должен быть кратен timeframeMs (в UTC)
      if (lastCandle.openTime % timeframeMs !== 0) {
        logger.error(
          `  ✗ Свеча не по сетке! openTime=${
            lastCandle.openTime
          } (${formatAsUTC(lastCandle.openTime)}), tf=${tf}`
        );
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      const currentCandleStart = Math.floor(now / timeframeMs) * timeframeMs;
      const expectedMinOpenTime = currentCandleStart - timeframeMs;
      const isFresh = lastCandle.openTime >= expectedMinOpenTime;

      if (isFresh) {
        logger.info(`  ✓ Свежесть: OK. Актуальная свеча.`, DColors.green);
        logger.info(
          `     -> Ожидалось (минимум): ${formatAsUTC(expectedMinOpenTime)}`,
          DColors.cyan
        );
        logger.info(
          `     -> Найдено в кэше:     ${formatAsUTC(lastCandle.openTime)}`,
          DColors.cyan
        );
      } else {
        logger.error(`  ✗ Устарело: старая свеча!`);
        logger.error(
          `     -> Ожидалось (минимум): ${formatAsUTC(expectedMinOpenTime)}`
        );
        logger.error(
          `     -> Найдено в кэше:     ${formatAsUTC(lastCandle.openTime)}`
        );
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      // ✅ Проверка 4: OI/FR целостность
      const candlesToCheck = coin.candles.slice(-10);
      let oiErrors = 0;
      let frErrors = 0;

      for (const candle of candlesToCheck) {
        if (candle.openInterest == null) {
          oiErrors++;
        }
        const shouldHaveFR = tf === "4h" || tf === "8h";
        const hasFR = candle.fundingRate != null;
        if (shouldHaveFR !== hasFR) {
          frErrors++;
        }
      }

      if (oiErrors > 0) {
        logger.error(
          `  ✗ OI: ${oiErrors}/${candlesToCheck.length} свечей без OI`
        );
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      const frLabel =
        tf === "4h" || tf === "8h" ? "должен быть" : "НЕ должен быть";
      if (frErrors > 0) {
        logger.error(`  ✗ FR: ${frErrors} ошибок (${frLabel})`);
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }

      logger.info(
        `  ✓ OI/FR: OK (${candlesToCheck.length} свечей, FR ${frLabel})`,
        DColors.green
      );

      // ✅ Проверка 5: Кэш статус
      logger.info(
        `  ✓ Кэш: ${result.cached ? "CACHED" : "GENERATED"} | Age: ${
          result.age || "N/A"
        }`,
        DColors.cyan
      );

      passed++;
    } catch (e: any) {
      logger.error(`  ✗ ОШИБКА: ${e.message}`);
      failed++;
    }

    console.log("-------------------------------------------------");
  }

  console.log("");
  if (failed === 0) {
    logger.info(
      `[API Test] ✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ: ${passed}/${timeframes.length}`,
      DColors.green
    );
  } else {
    logger.error(`[API Test] ❌ РЕЗУЛЬТАТЫ: ${passed} ✓ | ${failed} ✗`);
    process.exit(1);
  }
}

runApiTest();
