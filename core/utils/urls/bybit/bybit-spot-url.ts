export function bybitSpotUrl(symbol: string, interval: string, limit: number) {
  const baseUrl = "https://api.bybit.com/v5/market/kline";
  return `${baseUrl}?category=spot&symbol=${symbol}&interval=${interval}&limit=${limit}`;
}
