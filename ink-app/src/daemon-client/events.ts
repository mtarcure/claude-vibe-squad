import WebSocket from 'ws';
import { DaemonEvent } from '../types/protocol.js';

const WS_URL = process.env.VIBESQUAD_DAEMON_WS ?? 'ws://127.0.0.1:9876/events';
const TOKEN = process.env.VIBESQUAD_DAEMON_TOKEN;

export function subscribeEvents(onEvent: (event: DaemonEvent) => void): () => void {
  const headers: Record<string, string> = {};
  if (TOKEN) headers['Authorization'] = `Bearer ${TOKEN}`;
  const ws = new WebSocket(WS_URL, { headers });

  ws.on('message', (data) => {
    try {
      const event = JSON.parse(data.toString());
      onEvent(event);
    } catch (e) {
      console.error('failed to parse WS event', e);
    }
  });

  ws.on('error', (err) => {
    // Silently ignore errors (daemon may not be running)
  });

  ws.on('close', () => {
    // Connection closed, cleanup happens in unsubscribe
  });

  return () => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  };
}
