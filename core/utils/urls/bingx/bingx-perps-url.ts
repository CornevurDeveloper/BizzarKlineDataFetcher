export function bingxPerpUrl(symbol: string, interval: string, limit: number) {
  return `https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol=${symbol.replace(
    /(USDT)$/,
    "-$1"
  )}&interval=${interval}&limit=${limit}`;
}
