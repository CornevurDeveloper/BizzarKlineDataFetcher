export function bingxSpotUrl(symbol: string, interval: string, limit: number) {
  return `https://open-api.bingx.com/openApi/spot/v1/market/kline?symbol=${symbol.replace(
    /(USDT)$/,
    "-$1"
  )}&interval=${interval}&limit=${limit}`;
}
