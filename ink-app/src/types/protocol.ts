export interface TaskPacket {
  task_id?: string;
  project?: string;
  specialist: string;
  specialist_file: string;
  version?: string;
  lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  model: string;
  model_key: string;
  required_tools?: string[];
  preferred_tools?: string[];
  requires_approval?: string[];
  prompt: string;
  context?: Record<string, any>;
}

export interface Task {
  task_id: string;
  lane: string;
  state: 'queued' | 'running' | 'done' | 'error';
}

export interface DaemonEvent {
  type: 'task_complete' | 'task_error';
  task_id: string;
  path?: string;
}
