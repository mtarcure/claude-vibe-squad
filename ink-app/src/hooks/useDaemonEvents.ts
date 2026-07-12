import { useState, useEffect, useRef } from 'react';
import { subscribeEvents } from '../daemon-client/events.js';
import { DaemonEvent } from '../types/protocol.js';

export interface UseDaemonEventsReturn {
  events: DaemonEvent[];
  lastEvent: DaemonEvent | null;
}

export function useDaemonEvents(): UseDaemonEventsReturn {
  const [events, setEvents] = useState<DaemonEvent[]>([]);
  const [lastEvent, setLastEvent] = useState<DaemonEvent | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    // Subscribe to daemon events
    const unsubscribe = subscribeEvents((event) => {
      setEvents(prev => [...prev, event]);
      setLastEvent(event);
    });

    unsubscribeRef.current = unsubscribe;

    return () => {
      if (unsubscribeRef.current) {
        unsubscribeRef.current();
      }
    };
  }, []);

  return { events, lastEvent };
}
