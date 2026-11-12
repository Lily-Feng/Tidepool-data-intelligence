import { LogLevel } from '@slack/bolt';

const LOG_LEVELS = {
  debug: LogLevel.DEBUG,
  info: LogLevel.INFO,
  warn: LogLevel.WARN,
  error: LogLevel.ERROR,
};

/**
 * Resolve a Bolt log level from a string such as process.env.LOG_LEVEL, defaulting to info.
 * @param {string | undefined} value
 * @returns {LogLevel}
 */
export function resolveLogLevel(value) {
  const key = /** @type {keyof typeof LOG_LEVELS} */ ((value || 'info').trim().toLowerCase());
  return LOG_LEVELS[key] ?? LogLevel.INFO;
}
