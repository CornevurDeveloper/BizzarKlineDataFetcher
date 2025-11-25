import { Redis } from "@upstash/redis"; // <--- ИЗМЕНЕНО: импорт из npm
import { compress, decompress } from "lz-string"; // <--- ИЗМЕНЕНО: импорт из npm
import { MarketData, TF, DColors } from "./core/types"; // <--- ИЗМЕНЕНО: убраны .ts
import { logger } from "./core/utils/logger"; // <--- ИЗМЕНЕНО: убраны .ts

/**
 * RedisStore - замена MemoryStore с персистентностью в Upstash Redis + компрессия
 */
export class RedisStore {
  private static redis: Redis | null = null;
  private static readonly KEY_PREFIX = "market-vibe:cache:";
  private static readonly TTL_SECONDS = 7 * 24 * 60 * 60; // 7 дней

  /**
   * Инициализация Redis клиента (вызывать при старте сервера)
   */
  static init() {
    if (this.redis) return;

    // --- ИЗМЕНЕНО: Deno.env.get -> process.env ---
    const url =
      process.env.BIZZAR_UPSTASH_REDIS_REST_URL ||
      process.env.BIZZAR_UPSTASH_REDIS_URL;
    const token =
      process.env.BIZZAR_UPSTASH_REDIS_REST_TOKEN ||
      process.env.BIZZAR_UPSTASH_REDIS_TOKEN;
    // ---

    if (!url || !token) {
      // Важно: убедитесь, что 'dotenv/config' импортирован в server.ts
      throw new Error(
        "BIZZAR_UPSTASH_REDIS_REST_URL и BIZZAR_UPSTASH_REDIS_REST_TOKEN должны быть установлены в .env"
      );
    }

    if (!url.startsWith("https://")) {
      throw new Error(
        `UPSTASH_REDIS_REST_URL должен начинаться с https://, получен: ${url}`
      );
    }

    this.redis = new Redis({
      url,
      token,
      automaticDeserialization: true,
    });

    logger.info("✅ [REDIS] Успешно подключен к Upstash Redis", DColors.green);
  }

  /**
   * Получить клиент Redis
   */
  private static getClient(): Redis {
    if (!this.redis) {
      this.init();
    }
    return this.redis!;
  }

  /**
   * Сохранить данные для таймфрейма (с компрессией)
   */
  static async save(timeframe: TF, snapshot: MarketData): Promise<void> {
    try {
      const redis = this.getClient();
      const key = `${this.KEY_PREFIX}${timeframe}`;

      const dataWithMeta = {
        ...snapshot,
        timestamp: Date.now(),
      };

      // Сжимаем JSON
      const jsonStr = JSON.stringify(dataWithMeta);

      // --- ИЗМЕНЕНО: TextEncoder -> Buffer (более идиоматично для Node.js) ---
      const originalSize = Buffer.from(jsonStr, "utf-8").length;
      const compressed = compress(jsonStr);
      // ---

      if (!compressed) {
        throw new Error(`Compression failed for ${timeframe}`);
      }

      // --- ИЗМЕНЕНО: TextEncoder -> Buffer ---
      const compressedSize = Buffer.from(compressed, "utf-8").length;
      const ratio = ((1 - compressedSize / originalSize) * 100).toFixed(1);

      logger.info(
        `📊 [REDIS] ${timeframe}: ${(originalSize / 1024 / 1024).toFixed(
          2
        )}MB → ${(compressedSize / 1024 / 1024).toFixed(
          2
        )}MB (сжато на ${ratio}%)`,
        DColors.yellow
      );

      // Сохраняем сжатую строку как JSON (Upstash требует JSON)
      await redis.set(key, JSON.stringify({ compressed }), {
        ex: this.TTL_SECONDS,
      });

      logger.info(
        `✅ [REDIS] Saved ${timeframe} (${snapshot.coinsNumber} coins)`,
        DColors.green
      );
    } catch (error) {
      logger.error(
        `❌ [REDIS] Error saving ${timeframe}: ${error}`,
        DColors.red
      );
      throw error;
    }
  }

  /**
   * Получить данные для таймфрейма (с распаковкой)
   */
  static async get(timeframe: TF): Promise<MarketData | null> {
    try {
      const redis = this.getClient();
      const key = `${this.KEY_PREFIX}${timeframe}`;

      // Получаем JSON объект с сжатой строкой
      const stored = await redis.get<{ compressed: string }>(key);

      if (!stored || !stored.compressed) {
        logger.info(
          `ℹ️ [REDIS] No cache found for ${timeframe}`,
          DColors.yellow
        );
        return null;
      }

      // Распаковываем
      const jsonStr = decompress(stored.compressed);

      if (!jsonStr) {
        logger.error(
          `❌ [REDIS] Failed to decompress ${timeframe}`,
          DColors.red
        );
        return null;
      }

      const data = JSON.parse(jsonStr) as MarketData & { timestamp: number };

      const ageMinutes = Math.round((Date.now() - data.timestamp) / 60000);
      logger.info(
        `✅ [REDIS] Retrieved ${timeframe}: ${data.coinsNumber} coins, age: ${ageMinutes}m`,
        DColors.cyan
      );

      return data;
    } catch (error) {
      logger.error(
        `❌ [REDIS] Error getting ${timeframe}: ${error}`,
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
      const redis = this.getClient();
      const pattern = `${this.KEY_PREFIX}*`;

      const keys = await redis.keys(pattern);

      if (keys.length === 0) {
        logger.info("ℹ️ [REDIS] No cached data found", DColors.yellow);
        return [];
      }

      const allData: MarketData[] = [];

      for (const key of keys) {
        try {
          const stored = await redis.get<{ compressed: string }>(key);
          if (stored && stored.compressed) {
            const jsonStr = decompress(stored.compressed);
            if (jsonStr) {
              const data = JSON.parse(jsonStr) as MarketData;
              allData.push(data);
            }
          }
        } catch (e) {
          logger.error(
            `❌ [REDIS] Error parsing key ${key}: ${e}`,
            DColors.red
          );
        }
      }

      logger.info(
        `✅ [REDIS] Retrieved ${allData.length} cached timeframes`,
        DColors.cyan
      );
      return allData;
    } catch (error) {
      logger.error(`❌ [REDIS] Error getting all data: ${error}`, DColors.red);
      return [];
    }
  }

  /**
   * Очистить все данные кэша
   */
  static async clear(): Promise<void> {
    try {
      const redis = this.getClient();
      const pattern = `${this.KEY_PREFIX}*`;

      const keys = await redis.keys(pattern);

      if (keys.length === 0) {
        logger.info("ℹ️ [REDIS] No keys to clear", DColors.yellow);
        return;
      }

      await redis.del(...keys);

      logger.info(
        `✅ [REDIS] Cleared ${keys.length} cached timeframes`,
        DColors.green
      );
    } catch (error) {
      logger.error(`❌ [REDIS] Error clearing cache: ${error}`, DColors.red);
      throw error;
    }
  }

  /**
   * Проверить возраст кэша (в миллисекундах)
   */
  static async getCacheAge(timeframe: TF): Promise<number | null> {
    const data = await this.get(timeframe);
    if (!data || !("timestamp" in data)) {
      return null;
    }
    return Date.now() - (data as any).timestamp;
  }

  /**
   * Проверить, устарел ли кэш
   */
  static async isStale(
    timeframe: TF,
    maxAge: number = 2 * 60 * 60 * 1000
  ): Promise<boolean> {
    const age = await this.getCacheAge(timeframe);
    return age === null || age > maxAge;
  }
}

export type { MarketData };
