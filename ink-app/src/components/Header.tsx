import React from 'react';
import { Box, Text } from 'ink';

interface Props {
  project?: string;
  readyCount: number;
  totalLanes: number;
  timestamp: string;
  usage: {claude: number; codex: number; gemini: number; kimi: number};
}

export const Header: React.FC<Props> = ({project, readyCount, totalLanes, timestamp, usage}) => (
  <Box flexDirection="column" borderStyle="double">
    <Box>
      <Text bold>vibe-squad</Text>
      <Text> │ project: {project ?? 'none'} │ {readyCount}/{totalLanes} ready │ {timestamp}</Text>
    </Box>
    <Text dimColor>
      claude {usage.claude}% │ codex {usage.codex}% │ gemini {usage.gemini}% │ kimi {usage.kimi}%
    </Text>
  </Box>
);
