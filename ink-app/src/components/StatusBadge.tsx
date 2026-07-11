import React from 'react';
import { Text } from 'ink';

type Status = 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';

const BADGES: Record<Status, {char: string; color: string}> = {
  idle: {char: '⚪', color: 'gray'},
  thinking: {char: '⣾', color: 'cyan'},
  tool: {char: '🔧', color: 'yellow'},
  waiting: {char: '⏸', color: 'blue'},
  done: {char: '🟢', color: 'green'},
  error: {char: '⚠️', color: 'yellow'},
  stuck: {char: '🔴', color: 'red'},
  starting: {char: '🔵', color: 'blue'},
};

export const StatusBadge: React.FC<{status: Status; label?: string}> = ({status, label}) => {
  const badge = BADGES[status];
  return (
    <Text color={badge.color}>
      {badge.char} {label ?? status}
    </Text>
  );
};
