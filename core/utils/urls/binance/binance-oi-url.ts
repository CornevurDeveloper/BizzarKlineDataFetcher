export function binanceOiUrl(symbol: string, interval: string, limit: number) {
  const base = "https://fapi.binance.com/futures/data/openInterestHist";

  return `${base}?symbol=${symbol}&period=${interval}&limit=${limit}`;
}
