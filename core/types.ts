/**
 * =================================================================================
 * Глобальные типы данных
 * =================================================================================
 */

// Таймфреймы
export type TF = "1h" | "4h" | "8h" | "12h" | "D";
export const TF_MAP: Record<string, TF> = {
  "1h": "1h",
  "4h": "4h",
  "8h": "8h",
  "12h": "12h",
  D: "D",
};

// Биржи
export type Exchange = "binance" | "bybit";

// Цвета для логгера (ANSI-коды)
export enum DColors {
  red = "color: #ff4d4d",
  green = "color: #5bff8b",
  yellow = "color: #ffff8b",
  cyan = "color: #00ffff",
  white = "color: #ffffff",
  gray = "color: #9e9e9e",
}

/**
 * =================================================================================
 * Типы для Fetchers
 * =================================================================================
 */

// Опции для батчей (параллельных запросов)
export type FetchOptions = {
  batchSize?: number;
  delayMs?: number;
};

// Монета (из Coin Sifter API)
export type Coin = {
  symbol: string;
  exchanges: string[];
};

// Группы монет по биржам
export type CoinGroups = {
  binanceCoins: Coin[];
  bybitCoins: Coin[];
};

// Результат одного неудачного запроса
export type FailedCoinResult = {
  symbol: string;
  error: string;
};

// Результат работы fetcher'а (до обогащения)
export type FetcherResult = {
  successful: CoinMarketData[]; // <- ИСПРАВЛЕНО: CoinRawData[] -> CoinMarketData[]
  failed: FailedCoinResult[];
};

/**
 * =================================================================================
 * Типы для Market Data (свечи и снэпшоты)
 * =================================================================================
 */

/**
 * Свеча (обогащенная)
 * Все поля, кроме openTime, могут быть null,
 * так как данные могут приходить из разных источников (Klines, OI, FR)
 */
export interface Candle {
  openTime: number; // Обязательное поле (timestamp)
  openPrice?: number | null;
  highPrice?: number | null;
  lowPrice?: number | null;
  closePrice?: number | null;
  volume?: number | null;
  volumeDelta?: number | null;
  openInterest?: number | null;
  fundingRate?: number | null;
  closeTime?: number; // Временно для Klines (Binance)
}

/**
 * Данные по одной монете (обогащенные)
 * Содержит массив свечей
 */
export interface CoinMarketData {
  symbol: string;
  exchanges: string[]; // Список бирж, где торгуется (из Coin Sifter)
  candles: Candle[];
}

/**
 * Снэпшот MarketData
 * Основной объект, который хранится в Redis/Cache
 * Содержит данные по ВСЕМ монетам для ОДНОГО таймфрейма
 */
export interface MarketData {
  timeframe: TF;
  openTime: number; // Время открытия последней (текущей) свечи
  updatedAt: number; // Timestamp последнего обновления
  coinsNumber: number; // Количество монет в 'data'
  data: CoinMarketData[]; // Массив данных по всем монетам
}

/**
 * =================================================================================
 * Типы для Cron Jobs
 * =================================================================================
 */

// Результат выполнения Cron Job
export interface JobResult {
  success: boolean;
  timeframe: TF | "N/A";
  totalCoins: number;
  successfulCoins: number;
  failedCoins: number;
  errors: string[];
  executionTime: number; // в миллисекундах
}
