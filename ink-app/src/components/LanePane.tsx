import React from 'react';
import { Box, Text } from 'ink';
import { StatusBadge } from './StatusBadge.js';

interface Props {
  name: string;
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  detail?: string;
  metric?: string;
  duration?: string;
}

export const LanePane: React.FC<Props> = ({name, status, detail, metric, duration}) => (
  <Box flexDirection="column" borderStyle="single" width="25%">
    <StatusBadge status={status} label={name} />
    {detail && <Text dimColor>{detail}</Text>}
    {metric && <Text dimColor>↳ {metric}</Text>}
    {duration && <Text dimColor>{duration}</Text>}
  </Box>
);
