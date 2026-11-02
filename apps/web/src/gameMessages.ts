export type Source = { id: string; title: string; content: string; score?: number };
export type Message = {
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  toolTrace?: string[];
  error?: string;
  complete?: boolean;
  status?: string;
  // API wire field names mirror the Python response schema.
  // eslint-disable-next-line @typescript-eslint/naming-convention
  turn_id?: string;
  draft?: string;
  // eslint-disable-next-line @typescript-eslint/naming-convention
  review?: { reviewer: string; reviewed_at: string; decision: { action: string; comment: string } };
};

function applyToolEvent(event: { type: string; name?: string; query?: string; count?: number }, answer: Message) {
  if (event.type === 'tool_call') {
    (answer.toolTrace ??= []).push(`${event.name}(${JSON.stringify({ query: event.query })})`);
  }
  if (event.type === 'subagent_start') {
    (answer.toolTrace ??= []).push(`委派 ${event.name}：${event.query}`);
  }
  if (event.type === 'subagent_end') answer.toolTrace?.push(`${event.name} 已完成，主助手正在汇总`);
  if (event.type === 'tool_result') answer.toolTrace?.push(`检索完成：命中 ${event.count ?? 0} 个知识片段`);
}

export function applyMessageEvent(data: string, answer: Message, onStatus: (message: string) => void) {
  const event = JSON.parse(data) as {
    type: string;
    text?: string;
    message?: string;
    sources?: Source[];
    name?: string;
    query?: string;
    count?: number;
    // API wire field names mirror the Python response schema.
    // eslint-disable-next-line @typescript-eslint/naming-convention
    turn_id?: string;
  };

  applyToolEvent(event, answer);
  if (event.type === 'token') answer.content += event.text ?? '';
  if (event.type === 'sources') answer.sources = event.sources ?? [];
  if (event.type === 'status') onStatus(event.message ?? '');
  if (event.type === 'error') throw new Error(event.message ?? '生成失败');
  if (event.type === 'done') { answer.complete = true; answer.status = 'completed'; }
  if (['pending_review', 'rejected'].includes(event.type)) {
    answer.status = event.type;
    answer.turn_id = event.turn_id;
  }
}

export function isSettled(answer: Message) {
  return answer.complete || ['pending_review', 'rejected'].includes(answer.status ?? '');
}
