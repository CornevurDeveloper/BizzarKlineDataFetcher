import { red, green, yellow, cyan, white, gray, bold } from "colorette";
import { DColors } from "../types"; // Убедись, что путь к types.ts верный
import { CONFIG } from "../config";
// Маппинг твоих DColors (которые "color: #...") на функции colorette
// Мы используем ключи enum (строки), а не их значения
const colorMap: Record<string, (text: string | number) => string> = {
  [DColors.red]: red,
  [DColors.green]: green,
  [DColors.yellow]: yellow,
  [DColors.cyan]: cyan,
  [DColors.white]: white,
  [DColors.gray]: gray,
};

class Logger {
  private projectName = bold(CONFIG.PROJECT_NAME); // Используем bold

  private log(
    message: string,
    colorEnum: DColors,
    logFn: (msg: string) => void = console.log
  ) {
    // Находим функцию цвета по значению enum (т.е. по строке "color: #...")
    const colorFunc = colorMap[colorEnum] || white;
    logFn(colorFunc(`[${this.projectName}] ${message}`));
  }

  public info(message: string, color: DColors): void {
    this.log(message, color, console.info);
  }

  public warn(message: string, color: DColors): void {
    this.log(message, color, console.warn);
  }

  /**
   * ИСПРАВЛЕННЫЙ метод error.
   * Он больше не принимает DColors в качестве второго аргумента.
   * Вместо этого он принимает настоящий объект ошибки (error?: unknown).
   */
  public error(message: string, error?: unknown): void {
    const colorFunc = colorMap[DColors.red]; // Всегда красный для ошибок
    console.error(colorFunc(bold(`[${this.projectName}] ✗ ERROR: ${message}`)));

    if (error) {
      // Если передан объект ошибки, выводим его
      if (error instanceof Error) {
        console.error(
          colorFunc(`[${this.projectName}]   Details: ${error.message}`)
        );
        // Раскомментируй, если нужен полный stack trace
        // if (error.stack) {
        //   console.error(gray(error.stack));
        // }
      } else {
        // Если передано что-то другое (например, строка)
        console.error(
          colorFunc(`[${this.projectName}]   Details: ${String(error)}`)
        );
      }
    }
  }

  public success(message: string, color: DColors): void {
    this.log(message, color, console.log);
  }
}

// Экспортируем один экземпляр
export const logger = new Logger();
