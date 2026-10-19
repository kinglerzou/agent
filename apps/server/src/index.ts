import 'dotenv/config';
import { createApp } from './app.js';

const port = Number(process.env.PORT || 3001);

createApp().listen(port, '127.0.0.1', () =>
  // eslint-disable-next-line no-console -- Report the local API address at startup.
  console.log(`Agent API: http://127.0.0.1:${port} (${process.env.AGENT_PROVIDER || 'mock'})`),
);
