import { spawn as childSpawn, ChildProcess } from 'child_process';

type LaneName = 'claude' | 'codex' | 'gemini' | 'kimi';

const COMMANDS: Record<LaneName, string> = {
  claude: '/Users/user/.local/bin/claude',
  codex: '/opt/homebrew/bin/codex',
  gemini: '/opt/homebrew/bin/gemini',
  kimi: '/Users/user/.local/bin/kimi',
};

const UNSET_ENV_KEYS = ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'];

export class LaneProcess {
  private process: ChildProcess | null = null;
  private dataHandlers: ((chunk: string) => void)[] = [];
  private exitHandlers: ((code: number) => void)[] = [];

  constructor(public readonly name: LaneName, private readonly args: string[] = []) {}

  async start(): Promise<void> {
    const env: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined && !UNSET_ENV_KEYS.includes(k)) env[k] = v;
    }
    // Ensure critical paths are available
    if (!env.PATH) env.PATH = process.env.PATH || '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin';
    if (!env.HOME) env.HOME = process.env.HOME || '/Users/user';
    if (!env.TERM) env.TERM = 'xterm-color';

    const cmd = COMMANDS[this.name];

    try {
      this.process = childSpawn(cmd, this.args, {
        cwd: env.HOME,
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      if (this.process.stdout) {
        this.process.stdout.on('data', (chunk: Buffer) => {
          const str = chunk.toString('utf8');
          for (const h of this.dataHandlers) h(str);
        });
      }

      if (this.process.stderr) {
        this.process.stderr.on('data', (chunk: Buffer) => {
          const str = chunk.toString('utf8');
          for (const h of this.dataHandlers) h(str);
        });
      }

      this.process.on('exit', (code: number | null) => {
        for (const h of this.exitHandlers) h(code ?? 1);
      });
    } catch (err) {
      throw new Error(`Failed to spawn process: ${err}`);
    }
  }

  write(input: string): void {
    this.process?.stdin?.write(input);
  }

  onData(cb: (chunk: string) => void): void {
    this.dataHandlers.push(cb);
  }

  onExit(cb: (code: number) => void): void {
    this.exitHandlers.push(cb);
  }

  kill(): void {
    if (this.process) {
      try {
        this.process.kill();
      } catch (e) {
        // Already dead
      }
      this.process = null;
    }
  }
}
