// @ts-ignore-file
import "dotenv/config";
import fetch from "node-fetch";
import { DColors, MarketData, TF, TF_MAP } from "./core/types";
import { logger } from "./core/utils/logger";
import { TIMEFRAME_MS } from "./core/utils/helpers";

const API_BASE_URL = process.env.KLINE_DATA_URL;
const SECRET_TOKEN = process.env.SECRET_TOKEN;

if (!API_BASE_URL) {
  logger.error("[API Test] KLINE_DATA_URL не установлен");
  process.exit(1);
}

if (!SECRET_TOKEN) {
  logger.error("[API Test] SECRET_TOKEN не установлен");
  process.exit(1);
}

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  cached?: boolean;
  age?: string;
}

// --- НОВАЯ ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ---
/**
 * Форматирует UTC timestamp в удобочитаемое время (МСК)
 */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  // Добавляем +3 часа, чтобы получить МСК
  const mskTime = new Date(date.getTime() + 3 * 60 * 60 * 1000);
  // Форматируем в "YYYY-MM-DD HH:mm (МСК)"
  return mskTime.toISOString().replace("T", " ").substring(0, 16) + " (МСК)";
}
// --- КОНЕЦ ФУНКЦИИ ---

async function runApiTest() {
  logger.info(`[API Test] Тестирование кэша: ${API_BASE_URL}`, DColors.cyan);
  console.log("=================================================");

  const timeframes: TF[] = Object.values(TF_MAP);
  let passed = 0;
  let failed = 0;
  const now = Date.now();

  for (const tf of timeframes) {
    const url = `${API_BASE_URL}/api/cache/${tf}`;
    logger.info(`[API TEST] ${tf}`, DColors.yellow);

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

      // --- ИЗМЕНЕНИЕ ЗДЕСЬ (Проверка 3: Свежесть) ---
      const lastCandle = coin.candles[coin.candles.length - 1];
      const timeframeMs = TIMEFRAME_MS[tf];

      // Ожидаемое время открытия ПРЕДЫДУЩЕЙ свечи (в UTC)
      const expectedMinOpenTime =
        Math.floor(now / timeframeMs) * timeframeMs - timeframeMs;

      // Ожидаемое время открытия ТЕКУЩЕЙ свечи (в UTC)
      const expectedCurrentOpenTime = autoCorrectTime(
        lastCandle.openTime,
        timeframeMs
      );

      const isFresh = lastCandle.openTime >= expectedMinOpenTime;

      if (isFresh) {
        logger.info(
          `  ✓ Свежесть: OK. Найдена актуальная свеча.`,
          DColors.green
        );
        logger.info(
          `     -> Ожидалось (текущая): ${formatTime(expectedCurrentOpenTime)}`,
          DColors.cyan
        );
        logger.info(
          `     -> Найдено в кэше:   ${formatTime(lastCandle.openTime)}`,
          DColors.cyan
        );
      } else {
        logger.error(`  ✗ Устарело: Найдена старая свеча!`);
        logger.error(
          `     -> Ожидалось (минимум): ${formatTime(expectedMinOpenTime)}`
        );
        logger.error(
          `     -> Найдено в кэше:      ${formatTime(lastCandle.openTime)}`
        );
        failed++;
        console.log("-------------------------------------------------");
        continue;
      }
      // --- КОНЕЦ ИЗМЕНЕНИЯ ---

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
      logger.error(`  ✗ ОШИБКА: ${e.message}`, e);
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

/**
 * Округляет время до начала свечи
 */
function autoCorrectTime(timestamp: number, timeframeMs: number): number {
  return Math.floor(timestamp / timeframeMs) * timeframeMs;
}

runApiTest();
