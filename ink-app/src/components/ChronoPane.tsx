import React from 'react';
import { Box, Text } from 'ink';
import { StatusBadge } from './StatusBadge.js';

interface Props {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  transcript: {role: 'you' | 'chrono' | 'route'; text: string}[];
}

export const ChronoPane: React.FC<Props> = ({status, transcript}) => (
  <Box flexDirection="column" borderStyle="round" width="100%">
    <StatusBadge status={status} label="Chrono" />
    <Box flexDirection="column" marginTop={1}>
      {transcript.map((entry, i) => (
        <Box key={i} marginTop={1}>
          <Text bold color={entry.role === 'you' ? 'green' : entry.role === 'chrono' ? 'cyan' : 'yellow'}>
            {entry.role}
          </Text>
          <Text>{'  '}{entry.text}</Text>
        </Box>
      ))}
    </Box>
  </Box>
);
