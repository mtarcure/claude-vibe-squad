import { TaskPacket, Task } from '../types/protocol.js';

const BASE = process.env.VIBESQUAD_DAEMON_URL ?? 'http://127.0.0.1:9876';
const TOKEN = process.env.VIBESQUAD_DAEMON_TOKEN;

function authHeaders(): Record<string, string> {
  if (!TOKEN) return {};
  return { Authorization: `Bearer ${TOKEN}` };
}

export async function dispatchTask(packet: TaskPacket): Promise<{task_id: string; path: string}> {
  const resp = await fetch(`${BASE}/task`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ...authHeaders()},
    body: JSON.stringify(packet),
  });
  if (!resp.ok) throw new Error(`dispatch failed: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

export async function getTasks(): Promise<Task[]> {
  const resp = await fetch(`${BASE}/tasks`, { headers: authHeaders() });
  return (await resp.json()).tasks;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}
