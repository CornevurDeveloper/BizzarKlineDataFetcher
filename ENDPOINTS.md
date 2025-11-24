# MarketVibeHub API

Документация по API для сервера `server.ts`.

---

## 🔐 Аутентификация

Все эндпоинты требуют аутентификации. Запросы должны содержать заголовок `Authorization` с вашим `SECRET_TOKEN`.

**Формат:**

```
Authorization: Bearer <YOUR_SECRET_TOKEN>
```

---

## 📈 1. Получение данных из кэша

### `GET /api/cache/:tf`

Получает снэпшот данных из `MemoryStore` для указанного таймфрейма.

**URL-Параметры:**

- `:tf` (string, **required**) — таймфрейм для запроса  
  - **Допустимые значения:** `1h`, `4h`, `8h`, `12h`, `D`  
  - **Специальное значение:** `all` — вернет *весь* кэш, сгруппированный по таймфреймам

**Примеры (cURL):**

```bash
# Получить кэш для 1h
curl -X GET http://localhost:8000/api/cache/1h \
  -H "Authorization: Bearer <YOUR_SECRET_TOKEN>"

# Получить весь кэш
curl -X GET http://localhost:8000/api/cache/all \
  -H "Authorization: Bearer <YOUR_SECRET_TOKEN>"
```

**Ответ (Success 200 OK):**

```json
{
  "success": true,
  "data": {
    "tf": "1h",
    "updatedAt": 1732288019685,
    "data": [
      {
        "symbol": "MANTAUSDT",
        "data": [
          {
            "openTime": 1732204800000,
            "openPrice": 0.1157,
            "highPrice": 0.1185,
            "lowPrice": 0.1061,
            "closePrice": 0.1095,
            "volume": 13221402.3,
            "volumeDelta": -578255.95,
            "openInterest": 3348157.87,
            "fundingRate": null
          }
          // ... more candles
        ]
      }
      // ... more coins
    ]
  }
}
```

---

## 🚀 2. Ручной запуск Job

### `POST /api/jobs/run/:jobName`

Асинхронно запускает указанный job на сервере. Не ждет его выполнения.

**URL-Параметры:**

- `:jobName` (string, **required**) — имя задачи для запуска  
  - **Допустимые значения:** `1h`, `4h`, `8h`, `12h`, `1d`

**Пример (cURL):**

```bash
# Запустить 1d Job
curl -X POST http://localhost:8000/api/jobs/run/1d \
  -H "Authorization: Bearer <YOUR_SECRET_TOKEN>"
```

**Ответ (Success 202 Accepted):**

```json
{
  "success": true,
  "message": "Job '1d' started successfully."
}
```

---

## 🕯️ 3. Получение 15м свечи (Binance)

### `GET /api/latest-candle/:symbol`

Получает одну последнюю 15-минутную (15m) свечу с Binance Futures для указанного символа.

**URL-Параметры:**

- `:symbol` (string, **required**) — символ (например, `BTCUSDT`)

**Пример (cURL):**

```bash
# Получить последнюю 15м свечу для BTCUSDT
curl -X GET http://localhost:8000/api/latest-candle/BTCUSDT \
  -H "Authorization: Bearer <YOUR_SECRET_TOKEN>"
```

**Ответ (Success 200 OK):**

```json
{
  "success": true,
  "data": {
    "openTime": 1763920800000,
    "openPrice": 45000.1,
    "highPrice": 45010.5,
    "lowPrice": 44990,
    "closePrice": 45005.2,
    "volume": 15000000.5,
    "volumeDelta": 500000.1,
    "closeTime": 1763921699999
  }
}
```
