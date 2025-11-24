export function bingXOiUrl(symbol: string) {
  return `https://open-api.bingx.com/openApi/swap/v2/quote/openInterest?symbol=${symbol.replace(
    /(USDT)$/,
    "-$1"
  )}`;
}
