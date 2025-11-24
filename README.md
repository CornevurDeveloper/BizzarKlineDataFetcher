# Cron System - Market Data Aggregation

Единая система для автоматического сбора, обработки и кэширования рыночных данных с Binance и Bybit.

---

## 📁 Структура проекта

```
cron-system/
├── core/
│   ├── types.ts                 # Общие типы и интерфейсы
│   ├── config.ts                # Конфигурация лимитов
│   ├── fetchers/
│   │   ├── oi-fetcher.ts       # OI данные (Open Interest)
│   │   ├── fr-fetcher.ts       # FR данные (Funding Rate)
│   │   └── kline-fetcher.ts    # Kline данные (OHLCV)
│   ├── processors/
│   │   ├── combiner.ts         # Комбинирование 4h→8h, 12h→1D
│   │   └── enricher.ts         # Обогащение OI + FR
│   └── utils/
│       └── helpers.ts          # Вспомогательные функции
├── jobs/
│   ├── job-1h.ts               # Cron job для 1h
│   ├── job-4h.ts               # Cron job для 4h
│   ├── job-8h.ts               # Cron job для 8h
│   ├── job-12h.ts              # Cron job для 12h
│   └── job-1d.ts               # Cron job для 1D
├── scheduler.ts                # Запуск cron jobs
└── memory-store.ts             # In-memory кэш
```

---

## 🎯 Архитектура

### Fetchers (Сборщики данных)

Все fetchers возвращают унифицированный формат:

```typescript
interface FetcherResult {
  successful: CoinMarketData[];
  failed: FailedCoinResult[];
}
```

---

### Processors (Обработчики)

- **Combiner**: Комбинирует свечи 2:1 (4h→8h, 12h→1D)  
- **Enricher**: Обогащает klines данными OI и FR

---

### Jobs (Задачи)

Каждый job выполняет определённую последовательность операций:

| Job | Timeframes | OI | FR | Combine |
|-----|------------|----|----|---------|
| 1h  | 1h         | ✓  | ✗  | ✗       |
| 4h  | 1h, 4h     | ✓  | ✓  | ✗       |
| 8h  | 1h, 4h, 8h | ✓  | ✓  | 4h→8h   |
| 12h | 1h–12h     | ✓  | ✗  | 4h→8h   |
| 1D  | 1h–1D      | ✓  | ✗  | 4h→8h, 12h→1D |

---

## 📊 Логика обработки данных

### Pre-fetch (выполняется один раз в начале job)

```typescript
import { CONFIG } from "./core/config.ts";

// Используется для всех TF
const oi1h = fetchOI(coins, "1h", CONFIG.OI.h1_GLOBAL);

// 8h normalized, только для 4h/8h
const fr = fetchFR(coins, CONFIG.FR.h4_RECENT);
```

---

### Enrichment Rules

#### OI Enrichment (все таймфреймы)

```typescript
const match = oi1hData.find(oi => oi.openTime >= candle.openTime);
candle.openInterest = match?.openInterest ?? null;
```

Пример для 4h candle:  
- openTime = 0:00  
- берём OI от 0:00

#### FR Enrichment (только 4h и 8h)

```typescript
const match = frData.findLast(fr => fr.openTime <= candle.openTime + 5000); // 5s допуск
candle.fundingRate = match?.fundingRate ?? null;
```

> FR нормализован к 4h/8h intervals внутри fetcher

---

### Combining Logic

#### 8h Timeframe

```typescript
const base4h = fetchKlines(coins, "4h", CONFIG.KLINE.h4_BASE);
const klines4h = base4h.slice(-CONFIG.SAVE_LIMIT);
enrich(klines4h, oi, fr);
save("4h", klines4h);

const klines8h = combine(base4h);  // 800 / 2 = 400
enrich(klines8h, oi, fr);
save("8h", klines8h);
```

#### 1D Timeframe

```typescript
const base12h = fetchKlines(coins, "12h", CONFIG.KLINE.h12_BASE);
const klines12h = base12h.slice(-CONFIG.SAVE_LIMIT);
enrich(klines12h, oi); // NO FR!
save("12h", klines12h);

const klines1d = combine(base12h);  // 800 / 2 = 400
enrich(klines1d, oi); // NO FR!
save("1D", klines1d);
```

---

## 🚀 Запуск

```bash
deno run --allow-net --allow-env --allow-read scheduler.ts
```

---

## ⏰ Расписание

- **1h Job**: каждый час, кроме 4h/8h/12h/1D  
- **4h Job**: 4, 20 часов  
- **8h Job**: 8, 16 часов  
- **12h Job**: 12 часов  
- **1D Job**: 0:00 UTC каждый день

---

## 📦 Результат

Все данные сохраняются в `MemoryStore` в формате:

```typescript
interface MarketData {
  timeframe: TF;
  openTime: number;
  updatedAt: number;
  coinsNumber: number;
  data: CoinMarketData[];
}
```

---

## 🔧 Конфигурация

Все лимиты (720, 801, 401) настраиваются в `core/config.ts`.

Batch размер и задержки:

```typescript
// jobs/job-1h.ts
const oi1hResult = await fetchOI(coinGroups, "1h" as TF, CONFIG.OI.h1_GLOBAL, {
  batchSize: 50,
  delayMs: 100
});
```

---

## ⚠️ Важные правила

- Не изменять логику без разрешения  
- OI: всегда 1h, `CONFIG.OI.h1_GLOBAL`  
- FR: 8h normalized, только для 4h и 8h  
- Combining: всегда 2:1 ratio  
- BASE SET: fetch BASE_LIMIT (801) → обработка → 800 → использование

---

## 📝 Модели данных

```typescript
interface Candle {
  openTime: number;
  highPrice?: number;
  lowPrice?: number;
  closePrice?: number;
  volume?: number;
  volumeDelta?: number;
  openInterest?: number | null;
  fundingRate?: number | null;
}
```

---

## 🛠️ Мониторинг

Все jobs логируют:

- Количество успешных/неудачных монет  
- Время выполнения  
- Ошибки

Доступ к данным:

```typescript
import { MemoryStore } from "./memory-store.ts";

const data1h = MemoryStore.get("1h");
const allData = MemoryStore.getAll();
```
