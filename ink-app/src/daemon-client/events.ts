import WebSocket from 'ws';
import { DaemonEvent } from '../types/protocol.js';

const WS_URL = process.env.VIBESQUAD_DAEMON_WS ?? 'ws://127.0.0.1:9876/events';

export function subscribeEvents(onEvent: (event: DaemonEvent) => void): () => void {
  const ws = new WebSocket(WS_URL);
  ws.on('message', (data) => {
    try {
      const event = JSON.parse(data.toString());
      onEvent(event);
    } catch (e) {
      console.error('failed to parse WS event', e);
    }
  });
  return () => ws.close();
}
