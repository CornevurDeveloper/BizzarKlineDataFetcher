// deno-lint-ignore-file no-explicit-any
import { DColors, MarketData } from "./core/types"; // <- ИЗМЕНЕНИЕ: импорт DColors
import { logger } from "./core/utils/logger";
import NodeCache from "node-cache";

/**
 * Хранилище в памяти для кэширования данных MarketData.
 */
const kv = new NodeCache({ stdTTL: 0, checkperiod: 120 });

export const memoryStore = {
  /**
   * Сохраняет MarketData в кэш.
   */
  async set(key: string, data: MarketData): Promise<void> {
    try {
      const success = kv.set(key, data);

      if (success) {
        logger.info(
          `[MemoryStore] ✓ Data saved for key: ${key} (TF: ${data.timeframe}, Coins: ${data.coinsNumber})`,
          DColors.green // <--- ИСПРАВЛЕНО: Добавлен DColors.green
        );
      } else {
        throw new Error("node-cache set operation failed");
      }
    } catch (error: any) {
      logger.error(
        `[MemoryStore] ✗ Error saving data for key ${key}: ${error.message}`,
        error // <--- ИСПРАВЛЕНО: Передаем сам объект error
      );
    }
  },

  /**
   * Получает MarketData из кэша по ключу.
   */
  async get(key: string): Promise<MarketData | null> {
    try {
      const data = kv.get(key);

      if (data) {
        logger.info(
          `[MemoryStore] ✓ Data retrieved for key: ${key}`,
          DColors.cyan // <--- ИСПРАВЛЕНО: Добавлен DColors.cyan
        );
        return data as MarketData;
      } else {
        logger.warn(
          `[MemoryStore] ✗ No data found for key: ${key}`,
          DColors.yellow // <--- ИСПРАВЛЕНО: Добавлен DColors.yellow
        );
        return null;
      }
    } catch (error: any) {
      logger.error(
        `[MemoryStore] ✗ Error retrieving data for key ${key}: ${error.message}`,
        error // <--- ИСПРАВЛЕНО: Передаем сам объект error
      );
      return null;
    }
  },

  /**
   * Удаляет MarketData из кэша по ключу.
   */
  async delete(key: string): Promise<void> {
    try {
      kv.del(key);
      logger.info(
        `[MemoryStore] ✓ Data deleted for key: ${key}`,
        DColors.green // <--- ИСПРАВЛЕНО: Добавлен DColors.green
      );
    } catch (error: any) {
      logger.error(
        `[MemoryStore] ✗ Error deleting data for key ${key}: ${error.message}`,
        error // <--- ИСПРАВЛЕНО: Передаем сам объект error
      );
    }
  },
};
