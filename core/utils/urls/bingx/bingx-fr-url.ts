export function bingXFrUrl(symbol: string, limit: number) {
  return `https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate?symbol=${symbol.replace(
    /(USDT)$/,
    "-$1"
  )}&limit=${limit}`;
}
