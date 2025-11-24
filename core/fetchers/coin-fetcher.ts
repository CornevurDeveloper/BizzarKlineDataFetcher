import fetch from "node-fetch";
// @ts-ignore
import { Response } from "node-fetch";

// В Node.js мы не используем Deno.load().
// Вместо этого, 'dotenv' (указанный в вашем package.json)
// должен быть загружен ОДИН РАЗ в вашем главном файле (server.ts)
// командой: import 'dotenv/config';
// После этого все переменные будут доступны в 'process.env'.

export async function fetchCoins() {
  try {
    const url = process.env.COIN_SIFTER_URL + "/coins/formatted-symbols";
    const token = process.env.SECRET_TOKEN;

    // Важно: в Node.js нужно проверять, что переменные загрузились
    if (!process.env.COIN_SIFTER_URL || !process.env.SECRET_TOKEN) {
      console.error(
        "Error: COIN_SIFTER_URL or SECRET_TOKEN is not set in .env file."
      );
      // В server.ts вы должны были загрузить dotenv
      throw new Error("Missing server configuration");
    }

    const response = await fetch(url, {
      headers: {
        "X-Auth-Token": token!, // '!' означает "non-null assertion", т.к. мы проверили выше
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    // Типизируем ответ от 'node-fetch@2'
    const data: any = await response.json();
    const coins = data.symbols;

    return coins;
  } catch (error) {
    console.error("Failed to fetch or parse coins data:", error);
    throw error;
  }
}
