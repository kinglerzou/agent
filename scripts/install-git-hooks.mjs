// 把 .githooks 下的钩子安装到 .git/hooks，用于提交前自动执行 eslint --fix
import { chmodSync, copyFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const sourceDir = join(root, '.githooks');
const targetDir = join(root, '.git', 'hooks');

if (!existsSync(join(root, '.git'))) {
  console.log('[hooks] 当前目录不是 git 仓库，跳过安装');
  process.exit(0);
}

if (!existsSync(sourceDir)) {
  console.log('[hooks] 未找到 .githooks 目录，跳过安装');
  process.exit(0);
}

mkdirSync(targetDir, { recursive: true });

for (const file of readdirSync(sourceDir)) {
  const from = join(sourceDir, file);
  const to = join(targetDir, file);

  copyFileSync(from, to);
  chmodSync(to, 0o755);
  console.log(`[hooks] 已安装 ${file}`);
}
