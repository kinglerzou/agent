import { spawnSync } from 'node:child_process';

const executable = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const result = spawnSync(executable, [process.argv[2] || 'scripts/migrate-game-storage.py', ...process.argv.slice(3)], { stdio: 'inherit', env: process.env });

process.exit(result.status ?? 1);
