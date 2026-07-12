import { readFile } from 'fs/promises';
import path from 'path';

const REPO_ROOT = '/Users/user/Obsidian-Claude-Vibe-Squad';

export async function loadChronoPrompt(): Promise<string> {
  const paths = [
    path.join(REPO_ROOT, 'shared', 'CHRONO-SOUL.md'),
    path.join(REPO_ROOT, 'shared', 'chrono-soul.md'),
  ];
  for (const p of paths) {
    try {
      return await readFile(p, 'utf-8');
    } catch {
      // Continue to next path
    }
  }
  return `You are Chrono, the orchestrator of Vibe Squad. You coordinate 4 model lanes (Claude, Codex, Gemini, Kimi) to work on tasks. You do not do the tasks yourself — you route them to specialists via the daemon at http://127.0.0.1:9876. Route questions from models to the operator in your own voice. Be concise.`;
}
