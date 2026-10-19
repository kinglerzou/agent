export type Message = { role: 'user' | 'assistant'; content: string };
export type Source = { id: string; title: string; content: string; score: number };
export type AgentEvent =
  | { type: 'status'; message: string }
  | { type: 'tool_start'; name: string; input: unknown }
  | { type: 'tool_end'; name: string; output: string }
  | { type: 'sources'; sources: Source[] }
  | { type: 'token'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string };
