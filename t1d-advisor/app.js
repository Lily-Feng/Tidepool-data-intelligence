import 'dotenv/config';

import { App } from '@slack/bolt';

import { resolveLogLevel } from './config/log-level.js';
import { stopOnSignals } from './config/shutdown.js';
import { registerListeners } from './listeners/index.js';

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  socketMode: true,
  logLevel: resolveLogLevel(process.env.LOG_LEVEL),
  ignoreSelf: false,
});

registerListeners(app);
stopOnSignals(app);

(async () => {
  await app.start();
  app.logger.info('Starter Agent is running!');
})();
