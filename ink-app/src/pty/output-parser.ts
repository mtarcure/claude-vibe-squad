// Extract status hints from raw CLI output
export interface StatusHint {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error';
  detail?: string;
  toolName?: string;
}

const TOOL_PATTERN = /(?:tool_use|calling tool|using):?\s*([a-zA-Z_-]+)/i;
const THINKING_PATTERN = /thinking|reasoning|analyzing/i;
const DONE_PATTERN = /completed|done|finished|success/i;
const ERROR_PATTERN = /error|failed|cannot/i;

export function parseOutput(chunk: string): StatusHint | null {
  if (chunk.trim().length === 0) return null;
  const toolMatch = chunk.match(TOOL_PATTERN);
  if (toolMatch) return {status: 'tool', toolName: toolMatch[1], detail: chunk.slice(0, 60)};
  if (DONE_PATTERN.test(chunk)) return {status: 'done', detail: chunk.slice(0, 60)};
  if (ERROR_PATTERN.test(chunk)) return {status: 'error', detail: chunk.slice(0, 60)};
  if (THINKING_PATTERN.test(chunk)) return {status: 'thinking'};
  return null;
}
