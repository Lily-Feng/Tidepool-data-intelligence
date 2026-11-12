/**
 * Stop the Bolt app cleanly when the process manager asks it to exit.
 * @param {{ stop: () => Promise<unknown>, logger: { info: (msg: string) => void } }} app
 * @returns {void}
 */
export function stopOnSignals(app) {
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, async () => {
      app.logger.info(`Received ${signal}, shutting down`);
      await app.stop();
      process.exit(0);
    });
  }
}
