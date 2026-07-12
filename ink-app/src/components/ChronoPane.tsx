import React, { useState, useRef, useEffect } from 'react';
import { Box, Text } from 'ink';
import TextInput from 'ink-text-input';
import { StatusBadge } from './StatusBadge.js';

interface Props {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  transcript: {role: 'you' | 'chrono' | 'route'; text: string}[];
  onSubmit?: (text: string) => void;
  pending?: boolean;
}

export const ChronoPane: React.FC<Props> = ({status, transcript, onSubmit, pending = false}) => {
  const [input, setInput] = useState('');
  const lastTranscriptRef = useRef(0);

  // Auto-scroll display to show last entries
  const displayLimit = 3;
  const visibleTranscript = transcript.slice(Math.max(0, transcript.length - displayLimit));

  const handleSubmit = (text: string) => {
    if (text.trim() && onSubmit && !pending) {
      onSubmit(text);
      setInput('');
    }
  };

  return (
    <Box flexDirection="column" borderStyle="round" width="100%">
      <StatusBadge status={status} label="Chrono" />
      <Box flexDirection="column" marginTop={1}>
        {visibleTranscript.map((entry, i) => (
          <Box key={i} marginTop={1}>
            <Text bold color={entry.role === 'you' ? 'green' : entry.role === 'chrono' ? 'cyan' : 'yellow'}>
              {entry.role.padEnd(6)}
            </Text>
            <Text>{entry.text.slice(0, 80)}</Text>
          </Box>
        ))}
      </Box>
      {!pending && (
        <Box marginTop={1}>
          <Text>{'you> '}</Text>
          <TextInput value={input} onChange={setInput} onSubmit={handleSubmit} />
        </Box>
      )}
      {pending && (
        <Box marginTop={1}>
          <Text dimColor>waiting for response...</Text>
        </Box>
      )}
    </Box>
  );
};
