export function bybitFrUrl(symbol: string, limit: number) {
  const baseUrl = "https://api.bybit.com/v5/market/funding/history";
  return `${baseUrl}?category=linear&symbol=${symbol}&limit=${limit}`;
}
