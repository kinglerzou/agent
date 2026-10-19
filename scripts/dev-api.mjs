import { spawnSync } from 'node:child_process';

const executable = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';

const result = spawnSync(executable, [
  '-m', 'uvicorn', 'studio.main:create_app', '--factory',
  '--app-dir', 'apps/api', '--host', '127.0.0.1', '--port', '3001',
], { stdio: 'inherit', env: process.env });

if (result.error) console.error('API 启动失败，请先执行 npm run setup:api');
process.exit(result.status ?? 1);
