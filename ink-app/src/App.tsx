import React, { useState } from 'react';
import { Box } from 'ink';
import { Header } from './components/Header.js';
import { ChronoPane } from './components/ChronoPane.js';
import { LanePane } from './components/LanePane.js';

export const App: React.FC = () => {
  const [now] = useState(new Date().toLocaleTimeString());
  return (
    <Box flexDirection="column">
      <Header project="none" readyCount={0} totalLanes={4} timestamp={now}
        usage={{claude: 0, codex: 0, gemini: 0, kimi: 0}} />
      <ChronoPane status="starting" transcript={[{role: 'chrono', text: 'starting up...'}]} />
      <Box flexDirection="row" width="100%">
        <LanePane name="Claude" status="starting" />
        <LanePane name="Codex" status="starting" />
        <LanePane name="Gemini" status="starting" />
        <LanePane name="Kimi" status="starting" />
      </Box>
    </Box>
  );
};
