import { useState, useCallback, useRef } from 'react';
import { ChronoClient } from '../chrono/sdk-client.js';

export interface TranscriptEntry {
  role: 'you' | 'chrono';
  text: string;
}

export interface UseChronoReturn {
  transcript: TranscriptEntry[];
  pending: boolean;
  send: (userMessage: string) => Promise<string>;
}

export function useChrono(systemPrompt: string, mcpConfigPath?: string): UseChronoReturn {
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [pending, setPending] = useState(false);
  const clientRef = useRef<ChronoClient | null>(null);

  // Initialize client on first use
  if (!clientRef.current) {
    clientRef.current = new ChronoClient(systemPrompt, mcpConfigPath);
  }

  const send = useCallback(async (userMessage: string): Promise<string> => {
    if (!clientRef.current) throw new Error('Chrono client not initialized');

    setPending(true);
    setTranscript(prev => [...prev, { role: 'you', text: userMessage }]);

    let fullResponse = '';
    try {
      for await (const event of clientRef.current.send(userMessage)) {
        if (event.type === 'text') {
          fullResponse = event.content;
        } else if (event.type === 'error') {
          fullResponse = `[ERROR] ${event.content}`;
          break;
        }
      }
      if (!fullResponse) {
        fullResponse = '[waiting for response...]';
      }
    } catch (err) {
      fullResponse = `[ERROR] ${err instanceof Error ? err.message : 'Unknown error'}`;
    } finally {
      setPending(false);
    }

    setTranscript(prev => [...prev, { role: 'chrono', text: fullResponse }]);

    return fullResponse;
  }, []);

  return { transcript, pending, send };
}
