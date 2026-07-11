import { IPty, spawn } from 'node-pty';

type LaneName = 'claude' | 'codex' | 'gemini' | 'kimi';

const COMMANDS: Record<LaneName, string> = {
  claude: '/Users/user/.local/bin/claude',
  codex: '/opt/homebrew/bin/codex',
  gemini: '/opt/homebrew/bin/gemini',
  kimi: '/Users/user/.local/bin/kimi',
};

const UNSET_ENV_KEYS = ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'];

export class LaneProcess {
  private pty: IPty | null = null;
  private dataHandlers: ((chunk: string) => void)[] = [];
  private exitHandlers: ((code: number) => void)[] = [];
  private crashCount = 0;
  private lastCrashTs = 0;
  private crashHandlers: ((info: {crashCount: number}) => void)[] = [];

  constructor(public readonly name: LaneName, private readonly args: string[] = []) {}

  async start(): Promise<void> {
    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined && !UNSET_ENV_KEYS.includes(k)) env[k] = v;
    }
    this.pty = spawn(COMMANDS[this.name], this.args, {
      name: 'xterm-color',
      cols: 120,
      rows: 30,
      cwd: process.env.HOME,
      env,
    });
    this.pty.onData((chunk: string) => {
      for (const h of this.dataHandlers) h(chunk);
    });
    this.pty.onExit(({exitCode}) => {
      for (const h of this.exitHandlers) h(exitCode);
      this.handleExit();
    });
  }

  private handleExit() {
    const now = Date.now();
    if (now - this.lastCrashTs > 5 * 60_000) this.crashCount = 0;
    this.crashCount += 1;
    this.lastCrashTs = now;
    for (const h of this.crashHandlers) h({crashCount: this.crashCount});
  }

  write(input: string): void {
    this.pty?.write(input);
  }

  onData(cb: (chunk: string) => void): void {
    this.dataHandlers.push(cb);
  }

  onExit(cb: (code: number) => void): void {
    this.exitHandlers.push(cb);
  }

  onCrash(cb: (info: {crashCount: number}) => void): void {
    this.crashHandlers.push(cb);
  }

  kill(): void {
    this.pty?.kill();
    this.pty = null;
  }
}
