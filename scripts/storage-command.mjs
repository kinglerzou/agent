import { spawnSync } from 'node:child_process';

const executable = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const result = spawnSync(executable, ['scripts/migrate-game-storage.py'], { stdio: 'inherit', env: process.env });

process.exit(result.status ?? 1);
