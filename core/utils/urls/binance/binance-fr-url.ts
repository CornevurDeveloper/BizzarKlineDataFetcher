export function binanceFrUrl(symbol: string, limit: number) {
  const baseUrl = "https://fapi.binance.com/fapi/v1/fundingRate";
  return `${baseUrl}?symbol=${symbol}&limit=${limit}`;
}
