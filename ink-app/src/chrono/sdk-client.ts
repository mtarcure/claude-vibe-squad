import { spawn } from 'child_process';

export interface ChronoEvent {
  type: 'text' | 'error' | 'done';
  content: string;
}

const CLAUDE_PATH = '/Users/user/.local/bin/claude';
const UNSET_ENV_KEYS = ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'];

// Chrono runs as a subprocess of the operator's `claude` CLI so it uses the
// Max subscription (OAuth), not direct API credits. Each send() invocation
// spawns `claude -p -c` in non-interactive mode; -c preserves session state
// across turns via filesystem-backed session persistence in ~/.claude/.
// child_process.spawn is the right tool for this because -p mode is batch,
// not interactive — node-pty is only needed for the interactive model lanes.
export class ChronoClient {
  private systemPrompt: string;
  private mcpConfigPath?: string;

  constructor(systemPrompt: string, mcpConfigPath?: string) {
    this.systemPrompt = systemPrompt;
    this.mcpConfigPath = mcpConfigPath;
  }

  async *send(userMessage: string): AsyncGenerator<ChronoEvent> {
    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined && !UNSET_ENV_KEYS.includes(k)) env[k] = v as string;
    }

    const args = [
      '-p',
      '-c',
      '--append-system-prompt', this.systemPrompt,
    ];
    if (this.mcpConfigPath) {
      args.push('--mcp-config', this.mcpConfigPath);
    }
    args.push(userMessage);

    const child = spawn(CLAUDE_PATH, args, {
      cwd: env.HOME || '/Users/user',
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (d) => { stdout += d.toString(); });
    child.stderr?.on('data', (d) => { stderr += d.toString(); });

    const exitCode = await new Promise<number>((resolve) => {
      child.on('exit', (code) => resolve(code ?? 1));
    });

    if (exitCode !== 0) {
      yield { type: 'error', content: `claude exited with code ${exitCode}: ${(stderr || stdout).slice(0, 500)}` };
      return;
    }

    yield { type: 'text', content: stdout.trim() };
    yield { type: 'done', content: '' };
  }
}
