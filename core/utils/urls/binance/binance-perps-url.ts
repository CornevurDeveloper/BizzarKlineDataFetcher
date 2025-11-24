export function binancePerpsUrl(
  symbol: string,
  interval: string,
  limit: number
) {
  const baseUrl = "https://fapi.binance.com/fapi/v1/klines";
  return `${baseUrl}?symbol=${symbol}&interval=${interval}&limit=${limit}`;
}
