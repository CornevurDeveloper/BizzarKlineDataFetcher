# Quick Start Guide

---

## 📁 Система Файлов

```
MarketVibeHub/
├── core/
│   ├── types.ts
│   ├── config.ts                # <- ДОБАВЛЕНО
│   ├── fetchers/
│   │   ├── coin-fetcher.ts
│   │   ├── fr-fetchers.ts
│   │   ├── kline-fetchers.ts
│   │   └── oi-fetchers.ts
│   ├── getters/
│   │   ├── get-binance-oi.ts
│   │   ├── get-bybit-oi.ts
│   │   ├── get-fr.ts
│   │   └── get-kline.ts
│   ├── processors/
│   │   ├── combiner.ts
│   │   └── enricher.ts
│   └── utils/
│       ├── helpers.ts
│       ├── logger.ts
│       └── urls/
│           ├── binance/
│           │   ├── binance-fr-url.ts
│           │   ├── binance-oi-url.ts
│           │   ├── binance-perps-url.ts
│           │   └── binance-spot-url.ts
│           ├── bingx/
│           │   ├── bingx-fr-url.ts
│           │   ├── bingx-oi-url.ts
│           │   ├── bingx-perps-url.ts
│           │   └── bingx-spot-url.ts
│           └── bybit/
│               ├── bybit-fr-url.ts
│               ├── bybit-oi-url.ts
│               ├── bybit-perps-url.ts
│               └── bybit-spot-url.ts
├── jobs/
│   ├── job-12h.ts
│   ├── job-1d.ts
│   ├── job-1h.ts
│   ├── job-4h.ts
│   └── job-8h.ts
├── architecture.md
├── memory-store.ts
├── QUICK-START-CODE.md
├── README.md
├── remarks.txt
├── scheduler.ts
└── test.ts
```

---

## 🚀 Запуск системы

### 1. Установка зависимостей

```bash
# Система работает на Deno, установка не требуется
# Убедитесь что .env файл настроен с SECRET_TOKEN и COIN_SIFTER_URL
```

---

### 2. Запуск scheduler

```bash
deno run --allow-net --allow-env --allow-read scheduler.ts
```

---

### 3. Ручной запуск jobs (для тестирования)

```ts
import { fetchCoins } from "./fetch-coins.ts";
import { run1hJob } from "./jobs/job-1h.ts";

const { binanceCoins, bybitCoins } = await fetchCoins();
const allCoins = [...binanceCoins, ...bybitCoins];

const result = await run1hJob(allCoins);
console.log(result);
```

---

## 📊 Доступ к данным

### Получение данных из кэша

```ts
import { MemoryStore } from "./memory-store.ts";

// Данные для конкретного таймфрейма
const data1h = MemoryStore.get("1h");
const data4h = MemoryStore.get("4h");

// Все данные
const allData = MemoryStore.getAll();

// Структура данных
console.log(data1h.timeframe);    // "1h"
console.log(data1h.updatedAt);    // timestamp
console.log(data1h.data.length);  // количество монет
console.log(data1h.data[0].data.length); // 400 свечей
```

### Пример использования

```ts
// Получить последнюю свечу для BTC
const btcData = data1h.data.find(coin => coin.symbol === "BTCUSDT");
const lastCandle = btcData.data[btcData.data.length - 1];

console.log({
  symbol: btcData.symbol,
  openTime: lastCandle.openTime,
  closePrice: lastCandle.closePrice,
  volume: lastCandle.volume,
  openInterest: lastCandle.openInterest,
  fundingRate: lastCandle.fundingRate // null для 1h
});
```

---

## 🔧 Настройка jobs

### Изменение лимитов, batch size и delay

```ts
// core/config.ts
export const CONFIG = {
  SAVE_LIMIT: 400,

  KLINE: {
    h1: 401,
    h4_BASE: 801,
    // ...
  },

  OI: {
    h1_GLOBAL: 720, // <-- Изменить здесь
  },
  // ...
};
```

```ts
// jobs/job-1h.ts
const oi1hResult = await fetchOI(coinGroups, "1h" as TF, CONFIG.OI.h1_GLOBAL, {
  batchSize: 50,   // ← Количество монет в батче
  delayMs: 100,    // ← Задержка между запросами (ms)
});
```

---

### Изменение расписания

```ts
// scheduler.ts

// Текущее: проверка каждую минуту, запуск на :05
if (minute !== 5) return;

// Изменить на запуск на :00
if (minute !== 0) return;
```

---

## 📈 Мониторинг

### Логи

Все операции логируются с цветовой индикацией:

- 🔵 Cyan: Информация о начале операций  
- 🟢 Green: Успешные операции  
- 🟡 Yellow: Предупреждения  
- 🔴 Red: Ошибки  

---

### Результат job

```ts
interface JobResult {
  success: boolean;
  timeframe: TF;
  totalCoins: number;
  successfulCoins: number;
  failedCoins: number;
  errors: string[];
  executionTime: number; // ms
}
```

---

## 🧪 Тестирование

### Тест отдельного fetcher

```ts
import { CONFIG } from "./core/config.ts";
import { fetchOI } from "./core/fetchers/oi-fetcher.ts";
import { splitCoinsByExchange } from "./core/utils/helpers.ts";
import { fetchCoins } from "./fetch-coins.ts";

const { binanceCoins, bybitCoins } = await fetchCoins();
const coinGroups = { binanceCoins, bybitCoins };

const result = await fetchOI(coinGroups, "1h" as TF, CONFIG.OI.h1_GLOBAL);
console.log(`Success: ${result.successful.length}, Failed: ${result.failed.length}`);
```

---

### Тест combiner

```ts
import { combineCandles } from "./core/processors/combiner.ts";

const candles4h = [...]; // 800 свечей 4h
const candles8h = combineCandles(candles4h);
console.log(`Combined ${candles4h.length} → ${candles8h.length} candles`);
```

---

### Тест enricher

```ts
import { enrichKlines } from "./core/processors/enricher.ts";

const enriched = enrichKlines(
  klineResults,
  oi1hResult,
  "4h",
  frResult
);

// Проверяем что OI и FR добавлены
const sample = enriched[0].candles[0];
console.log({
  openInterest: sample.openInterest,  // должен быть number или null
  fundingRate: sample.fundingRate     // должен быть number или null для 4h
});
```

---

## 🐛 Troubleshooting

### Job не запускается

- Проверьте что scheduler работает  
- Проверьте текущее время (UTC)  
- Проверьте логи на наличие ошибок  

### Нет данных в кэше

- Дождитесь выполнения первого job  
- Проверьте `MemoryStore.getAll()` — должен вернуть данные  
- Проверьте логи job — должен быть `success: true`  

### Ошибки API

- Проверьте rate limits (`batchSize` и `delayMs`)  
- Проверьте доступность Binance/Bybit API  
- Увеличьте `delayMs`, если много ошибок  

### Неполные данные

- Проверьте `failed` в результатах job  
- Проверьте логи fetchers — могут быть ошибки для конкретных монет  
- Некоторые монеты могут отсутствовать на одной из бирж  

---

## 📚 Дальнейшее чтение

- `README.md` — Полная документация  
- `core/types.ts` — Все интерфейсы  
- `jobs/` — Исходный код jobs  
