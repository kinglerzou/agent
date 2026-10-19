import express from 'express';
import { z } from 'zod';
import { runAgent } from './agent.js';
import { documents } from './knowledge.js';

const requestSchema = z
  .object({
    messages: z
      .array(
        z.object({
          role: z.enum(['user', 'assistant']),
          content: z.string().trim().min(1).max(8000),
        }),
      )
      .min(1)
      .max(20),
  })
  .refine((v) => v.messages.at(-1)?.role === 'user');

export function createApp(provider = process.env.AGENT_PROVIDER || 'mock') {
  if (!['mock', 'openai'].includes(provider))
    throw new Error('AGENT_PROVIDER 必须是 mock 或 openai');
  if (provider === 'openai' && !process.env.OPENAI_API_KEY)
    throw new Error('OpenAI 模式需要配置 OPENAI_API_KEY');
  const app = express();

  app.use(express.json({ limit: '200kb' }));
  app.get('/api/health', (_req, res) =>
    res.json({
      status: 'ok',
      provider,
      model: provider === 'mock' ? 'Mock / 本地模拟' : process.env.OPENAI_MODEL || 'gpt-4.1-mini',
    }),
  );
  app.get('/api/knowledge', (_req, res) => res.json(documents));
  let active = 0;
  app.post('/api/chat', async (req, res) => {
    const parsed = requestSchema.safeParse(req.body);

    if (!parsed.success) {
      res
        .status(400)
        .json({ error: '消息格式错误：最多 20 条，每条 1–8000 字符，末条必须为用户消息' });

      return;
    }
    if (active >= 8) {
      res.status(429).json({ error: '服务繁忙，请稍后重试' });

      return;
    }
    active++;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error('请求超时')), 90000);

    res.on('close', () => controller.abort());
    res.set({
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.flushHeaders();

    const emit = (event: Parameters<Parameters<typeof runAgent>[1]>[0]) => {
      if (!res.destroyed) res.write(`data: ${JSON.stringify(event)}\n\n`);
    };

    try {
      await runAgent(parsed.data.messages, emit, controller.signal, provider);
    } catch {
      emit({
        type: 'error',
        message: controller.signal.aborted
          ? '请求已停止或超时'
          : 'Agent 执行失败，请检查后端模型配置后重试',
      });
    } finally {
      clearTimeout(timer);
      active--;
      res.end();
    }
  });
  app.use(((error: { status?: number }, _req, res, _next) => {
    res.status(error.status === 413 ? 413 : 400).json({ error: '请求体无效或过大' });
  }) as express.ErrorRequestHandler);

  return app;
}
