# Architecture Overview

---

## 🏗️ Система состоит из 4 слоёв

```
┌─────────────────────────────────────────┐
│ SCHEDULER LAYER │ ← Запуск jobs по расписанию
├─────────────────────────────────────────┤
│ JOBS LAYER      │ ← Оркестрация операций
├─────────────────────────────────────────┤
│ PROCESSORS LAYER│ ← Обработка данных
│ ├── Fetchers (OI, FR, Kline)
│ ├── Combiner (4h→8h, 12h→1D)
│ └── Enricher (OI + FR injection)
├─────────────────────────────────────────┤
│ DATA LAYER      │ ← Хранение данных (MemoryStore)
└─────────────────────────────────────────┘
```

---

## 📊 Data Flow

(Ссылки на `CONFIG` добавлены для ясности)

### 1h Job Flow

```
Coins → Split by Exchange
↓
┌────┴────┐
│ Binance │ Bybit
└────┬────┘
↓
[Fetch OI 1h (CONFIG.OI.h1_GLOBAL)]
[Fetch Kline 1h (CONFIG.KLINE.h1)]
↓
Enrich (OI only)
↓
Save to Cache (1h)
```

---

### 4h Job Flow

```
Coins → Split by Exchange
↓
┌────┴────┐
│ Binance │ Bybit
└────┬────┘
↓
[Fetch OI 1h (CONFIG.OI.h1_GLOBAL)]
[Fetch FR (CONFIG.FR.h4_RECENT)]
[Fetch Kline 1h (CONFIG.KLINE.h1)]
[Fetch Kline 4h (CONFIG.KLINE.h4_DIRECT)]
↓
┌────┴────┐
│ 1h+OI   │ 4h+OI+FR
└────┬────┘
↓
Save to Cache (1h, 4h)
```

---

### 8h Job Flow

```
Coins → Split by Exchange
↓
[Pre-fetch]
  OI 1h (CONFIG.OI.h1_GLOBAL)
  FR (CONFIG.FR.h4_RECENT)
↓
[Fetch Klines]
  1h (CONFIG.KLINE.h1)
  4h (CONFIG.KLINE.h4_BASE) ← BASE SET
↓
┌────┴────────────┐
│ 1h+OI │ 4h BASE (800)
┌───┴───┐
│ Last 400 → Combine 2:1 (SAVE_LIMIT)
│ 4h+OI+FR → 8h (400)
└─────────┴───────┘
↓
Save to Cache (1h, 4h, 8h)
```

---

### 12h Job Flow

```
Coins → Split by Exchange
↓
[Pre-fetch]
  OI 1h (CONFIG.OI.h1_GLOBAL)
  FR (CONFIG.FR.h4_RECENT)
↓
[Fetch Klines]
  1h (CONFIG.KLINE.h1)
  4h (CONFIG.KLINE.h4_BASE) ← BASE SET for 4h/8h
  12h (CONFIG.KLINE.h12_DIRECT) ← ОПТИМИЗИРОВАНО
↓
┌────┴─────────────────────┐
│ 1h+OI │ 4h BASE (800)
┌────┴────┐
│ Last 400 → Combine (SAVE_LIMIT)
│ 4h+OI+FR → 8h+OI+FR
│ 12h (400) → 12h+OI
└─────────┴─────────┘
↓
Save to Cache (1h, 4h, 8h, 12h)
```

> Примечание: `job-1d` обрабатывает 1D отдельно

---

## 🔄 Combining Algorithm

### Правила комбинирования 2:1

```typescript
function combineCandles(candles: Candle[]): Candle[] {
  const result: Candle[] = [];
  
  for (let i = 0; i < candles.length - 1; i += 2) {
    const first = candles[i];
    const second = candles[i + 1];
    
    result.push({
      openTime: first.openTime,      // От первой
      highPrice: max(first, second), // Макс из двух
      lowPrice: min(first, second),  // Мин из двух
      closePrice: second.closePrice, // От второй
      volume: first + second,        // Сумма
      volumeDelta: first + second    // Сумма
    });
  }
  
  return result;
}
```

**Почему 801 → 800?**

- Fetch: 801 candles (BASE_LIMIT)  
- Processing: slice first and last in `get-kline.ts`  
- Result: 800 candles (BASE SET)  
- Usage:  
  - Last 400 (SAVE_LIMIT) → direct timeframe  
  - All 800 → combine to 400 higher TF  

---

## 💉 Enrichment Algorithm

### OI Enrichment (все таймфреймы)

```typescript
for (const candle of klines) {
  const oi = oi1hData.find(oi => oi.openTime >= candle.openTime);
  candle.openInterest = oi?.openInterest ?? null;
}
```

Пример:

- 4h[0:00] → 1h[0:00] ✓  
- 4h[4:00] → 1h[4:00] ✓  
- 4h[8:00] → 1h[8:00] ✓  

---

### FR Enrichment (только 4h и 8h)

```typescript
for (const candle of klines) {
  const fr = frData.findLast(fr => fr.openTime <= candle.openTime + 5000);
  candle.fundingRate = fr?.fundingRate ?? null;
}
```

Пример:

- 4h[0:00]  → FR[0:00] ✓  
- 4h[4:00]  → FR[0:00] ✓ (findLast)  
- 4h[8:00]  → FR[8:00] ✓  
- 4h[12:00] → FR[8:00] ✓ (findLast)  
- 4h[16:00] → FR[16:00] ✓  

---

## 🗄️ Storage Model

### Memory Store Structure

```typescript
Map<TF, MarketData> {
  "1h" => {
    timeframe: "1h",
    openTime: 1234567890000,
    updatedAt: 1234567890500,
    data: [
      {
        symbol: "BTCUSDT",
        exchanges: ["binance"],
        data: [ /* 400 candles */ ]
      },
      // ... other coins
    ]
  },
  "4h" => { /* ... */ },
  // ...
}
```

### Candle Structure

```typescript
{
  openTime: 1234567890000,    // Primary key
  highPrice: 50000,
  lowPrice: 49000,
  closePrice: 49500,
  volume: 1000000,
  volumeDelta: 5000,
  openInterest: 1234567890,   // From OI 1h
  fundingRate: 0.0001         // From FR (4h/8h only)
}
```

---

## ⚡ Performance Optimization

### Batch Processing

```typescript
// Sequential
for (const coin of coins) {
  await fetchData(coin);
}

// Parallel with batching
const batches = chunk(coins, 50);
for (const batch of batches) {
  await Promise.all(batch.map(fetchData));
  await delay(100);  // Rate limiting
}
```

---

### Pre-fetching Strategy

```typescript
import { CONFIG } from "./core/config.ts";

const oi1h = await fetchOI(coins, "1h", CONFIG.OI.h1_GLOBAL);
const fr = await fetchFR(coins, CONFIG.FR.h4_RECENT);

enrich1h(klines1h, oi1h);
enrich4h(klines4h, oi1h, fr);
enrich8h(klines8h, oi1h, fr);
enrich12h(klines12h, oi1h); // No FR
enrich1d(klines1d, oi1h);   // No FR
```

---

### Map-based Lookup

```typescript
// O(n²)
for (const candle of candles) {
  const oi = oiArray.find(oi => oi.openTime >= candle.openTime);
}

// O(n) with Map
const oiMap = new Map(oiArray.map(oi => [oi.symbol, oi.candles]));
for (const candle of candles) {
  const oi = oiMap.get(candle.symbol);
}
```

---

## 🔒 Immutability

```typescript
// ❌ Wrong
function enrich(candles: Candle[]) {
  for (const candle of candles) {
    candle.openInterest = 123;
  }
}

// ✅ Correct
function enrich(candles: Candle[]) {
  const copy = [...candles];
