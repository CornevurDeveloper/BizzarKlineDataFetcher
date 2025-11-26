// deno-lint-ignore-file no-explicit-any
import { DColors, MarketData, TF } from "../core/types"; // <--- ИЗМЕНЕНО: путь ../core/
import { logger } from "../core/utils/logger"; // <--- ИЗМЕHЕНО: путь ../core/
import NodeCache from "node-cache";

// Тип для данных, хранящихся в кэше, с добавлением timestamp
type CachedMarketData = MarketData & { timestamp: number };

/**
 * MemoryStore - замена RedisStore с хранением в памяти (NodeCache).
 * API совместимо с RedisStore (кроме isStale/getCacheAge по запросу).
 * НЕ ИСПОЛЬЗУЕТ СЖАТИЕ.
 */
export class MemoryStore {
  private static kv: NodeCache | null = null;
  private static readonly KEY_PREFIX = "market-vibe:cache:";

  /**
   * Инициализация NodeCache клиента
   */
  static init() {
    if (this.kv) return;

    // stdTTL: 0 - нет TTL по умолчанию, мы управляем им вручную (как в RedisStore)
    this.kv = new NodeCache({ stdTTL: 0, checkperiod: 120 });
    logger.info("✅ [MEMORY] Успешно инициализирован NodeCache", DColors.green);
  }

  /**
   * Получить клиент NodeCache
   */
  private static getClient(): NodeCache {
    if (!this.kv) {
      this.init();
    }
    return this.kv!;
  }

  /**
   * Сохранить данные для таймфрейма (БЕЗ компрессии)
   */
  static async save(timeframe: TF, snapshot: MarketData): Promise<void> {
    try {
      const kv = this.getClient();
      const key = `${this.KEY_PREFIX}${timeframe}`;

      // Добавляем timestamp для совместимости с getCacheAge/isStale
      const dataWithMeta: CachedMarketData = {
        ...snapshot,
        timestamp: Date.now(),
      };

      // Сохраняем чистый JSON, БЕЗ СЖАТИЯ
      const success = kv.set(key, dataWithMeta);

      if (!success) {
        throw new Error("node-cache set operation failed");
      }

      logger.info(
        `✅ [MEMORY] Saved ${timeframe} (${snapshot.coinsNumber} coins)`,
        DColors.green
      );
    } catch (error) {
      logger.error(
        `❌ [MEMORY] Error saving ${timeframe}: ${error}`,
        DColors.red
      );
      throw error;
    }
  }

  /**
   * Получить данные для таймфрейма (БЕЗ распаковки)
   */
  static async get(timeframe: TF): Promise<MarketData | null> {
    try {
      const kv = this.getClient();
      const key = `${this.KEY_PREFIX}${timeframe}`;

      // Получаем чистый JSON
      const data = kv.get<CachedMarketData>(key);

      if (!data) {
        logger.info(
          `ℹ️ [MEMORY] No cache found for ${timeframe}`,
          DColors.yellow
        );
        return null;
      }

      const ageMinutes = Math.round((Date.now() - data.timestamp) / 60000);
      logger.info(
        `✅ [MEMORY] Retrieved ${timeframe}: ${data.coinsNumber} coins, age: ${ageMinutes}m`,
        DColors.cyan
      );

      return data;
    } catch (error) {
      logger.error(
        `❌ [MEMORY] Error getting ${timeframe}: ${error}`,
        DColors.red
      );
      return null;
    }
  }

  /**
   * Получить все закэшированные таймфреймы
   */
  static async getAll(): Promise<MarketData[]> {
    try {
      const kv = this.getClient();
      const keys = kv.keys();

      const allData: MarketData[] = [];

      for (const key of keys) {
        if (key.startsWith(this.KEY_PREFIX)) {
          try {
            const data = kv.get<MarketData>(key);
            if (data) {
              allData.push(data);
            }
          } catch (e) {
            logger.error(
              `❌ [MEMORY] Error parsing key ${key}: ${e}`,
              DColors.red
            );
          }
        }
      }

      logger.info(
        `✅ [MEMORY] Retrieved ${allData.length} cached timeframes`,
        DColors.cyan
      );
      return allData;
    } catch (error) {
      logger.error(`❌ [MEMORY] Error getting all data: ${error}`, DColors.red);
      return [];
    }
  }

  /**
   * Очистить все данные кэша
   */
  static async clear(): Promise<void> {
    try {
      const kv = this.getClient();
      const keys = kv.keys();

      const keysToDelete = keys.filter((k) => k.startsWith(this.KEY_PREFIX));

      if (keysToDelete.length === 0) {
        logger.info("ℹ️ [MEMORY] No keys to clear", DColors.yellow);
        return;
      }

      kv.del(keysToDelete);

      logger.info(
        `✅ [MEMORY] Cleared ${keysToDelete.length} cached timeframes`,
        DColors.green
      );
    } catch (error) {
      logger.error(`❌ [MEMORY] Error clearing cache: ${error}`, DColors.red);
      throw error;
    }
  }

  //
  // --- МЕТОДЫ getCacheAge и isStale УДАЛЕНЫ ПО ЗАПРОСУ ---
  //
}

export type { MarketData };
