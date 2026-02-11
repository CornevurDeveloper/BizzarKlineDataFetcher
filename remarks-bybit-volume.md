# Fixing Bybit Volume Data: A Guide for Future Bots
This document details the exact changes made to resolve the "Missing Volume Data" issue for coins sourced from Bybit (or dual sourced from Binance/Bybit). Use this as a reference if encountering similar issues in bazzar-kline-data-fetcher.

## Problem
Coins sourced from Bybit (e.g., APEUSDT) were returning null for volume data.

### Root Cause
The `get-kline.ts` file was parsing the Bybit API response using incorrect array indices.

- It was reading volume from index 7.
- It was reading closeTime from index 6.

### Bybit API V5 Response Format (Linear):
```json
[
  "startTime", // Index 0
  "open",      // Index 1
  "high",      // Index 2
  "low",       // Index 3
  "close",     // Index 4
  "volume",    // Index 5 (Contract/Base Volume)
  "turnover"   // Index 6 (Quote Volume / USDT)
]
```

## Solution
1. Correct Array Indices in `get-kline.ts`
File: `core/getters/get-kline.ts`
Function: `fetchBybitKlineData`

**Changes Made:**

- **Volume Source**: Changed from index 7 (invalid) to index 6 (Turnover/Quote Volume).
  - *Why Index 6?* The user requested "Quote Volume (USDT)". Index 5 is Base Volume (e.g., in APE). Index 6 is Turnover (e.g., in USDT).
- **Close Time Calculation**: Changed from reading index 6 to calculating `openTime` + `interval`.
  - *Why?* Index 6 is turnover, not a timestamp. Bybit candles are defined by start time and interval.

**Code Diff:**
```typescript
// BEFORE
volume: parseFloat(entry[7]),
closeTime: parseInt(entry[6]),

// AFTER
import { sleep, TIMEFRAME_MS } from "../utils/helpers";
// ...
// Get timeframe in ms
const timeframeMs = TIMEFRAME_MS[timeframe];
// ...
volume: parseFloat(entry[6]), // Index 6 is Turnover (Quote Volume/USDT)
closeTime: parseInt(entry[0]) + timeframeMs - 1, // End of candle
```

2. Ensure `TIMEFRAME_MS` is Imported
Since we use `TIMEFRAME_MS` for the closeTime calculation, we added it to the imports.

## Verification
1. Local Verification Script
Create a script to run the job locally and inspect the data.

2. Build Fix
Issue: Debug scripts (`verify-*.ts`, `debug-*.ts`) often import internal modules but are not part of the main `tsc` build process, leading to build failures on deployment.
**Fix**: Always delete debug scripts before deploying.

```bash
del debug-bybit-volume.ts debug-fetch-coins.ts verify-1h-volume-all.ts verify-volume-fix.ts
```

## Summary for Replication
If this happens again:

1. Check the API documentation for the exchange (e.g., Bybit V5).
2. Verify the array indices returned by the API.
3. Update the parser in `core/getters/get-kline.ts`.
4. Verify locally with a script.
5. **Delete the script before pushing.**
