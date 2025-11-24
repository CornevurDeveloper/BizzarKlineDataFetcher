export function binanceSpotUrl(
  symbol: string,
  interval: string,
  limit: number
) {
  const baseUrl = "https://api.binance.com/api/v3/klines";
  return `${baseUrl}?symbol=${symbol}&interval=${interval}&limit=${limit}`;
}
