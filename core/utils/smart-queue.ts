import { logger } from "./logger";
import { DColors } from "../types";
import { CONFIG } from "../config";

/**
 * Умная очередь для управления лимитами запросов к API.
 * Гарантирует, что запросы выполняются с заданной задержкой и размером батча,
 * независимо от того, сколько джобов пытаются их выполнить одновременно.
 */
class SmartQueue {
    private queue: Array<() => Promise<any>> = [];
    private isProcessing = false;
    private batchSize: number;
    private delayMs: number;
    private label: string;

    constructor(label: string, batchSize: number = 2, delayMs: number = 600) {
        this.label = label;
        this.batchSize = batchSize;
        this.delayMs = delayMs;
    }

    /**
     * Добавляет задачу в очередь и возвращает Promise, который разрешится,
     * когда задача будет выполнена.
     */
    add<T>(task: () => Promise<T>): Promise<T> {
        return new Promise((resolve, reject) => {
            const wrappedTask = async () => {
                try {
                    const result = await task();
                    resolve(result);
                } catch (error) {
                    reject(error);
                }
            };

            this.queue.push(wrappedTask);
            this.processQueue();
        });
    }

    private async processQueue() {
        if (this.isProcessing) return;
        this.isProcessing = true;

        while (this.queue.length > 0) {
            const batch = this.queue.splice(0, this.batchSize);

            const startTime = Date.now();

            // Выполняем батч параллельно
            await Promise.all(batch.map((task) => task()));

            const elapsed = Date.now() - startTime;
            const remainingDelay = this.delayMs - elapsed;

            if (this.queue.length > 0 && remainingDelay > 0) {
                await new Promise((resolve) => setTimeout(resolve, remainingDelay));
            }
        }

        this.isProcessing = false;
        logger.info(`[${this.label}] Очередь пуста.`, DColors.green);
    }
}

// Экземпляры очередей для разных бирж
const BATCH_SIZE = CONFIG.THROTTLING.BATCH_SIZE || 2;

export const binanceQueue = new SmartQueue(
    "BINANCE_QUEUE",
    BATCH_SIZE,
    CONFIG.THROTTLING.DELAY.BINANCE
);

export const bybitQueue = new SmartQueue(
    "BYBIT_QUEUE",
    BATCH_SIZE,
    CONFIG.THROTTLING.DELAY.BYBIT
);
