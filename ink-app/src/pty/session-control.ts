import { LaneProcess } from './lane-process.js';

// Each CLI has its own way to start a fresh session
export function startFreshSession(lane: LaneProcess): void {
  switch (lane.name) {
    case 'claude':
      lane.write('/newsession\r');
      break;
    case 'codex':
      // Codex CLI: send interrupt then re-invoke
      lane.write('\x03\r');
      break;
    case 'gemini':
      lane.write('/clear\r');
      break;
    case 'kimi':
      lane.write('/new\r');
      break;
  }
}
