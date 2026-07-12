import React, { useEffect, useState } from 'react';
import { Box } from 'ink';
import { Header } from './components/Header.js';
import { ChronoPane } from './components/ChronoPane.js';
import { LanePane } from './components/LanePane.js';
import { LaneProcess } from './pty/lane-process.js';
import { parseOutput } from './pty/output-parser.js';

type LaneName = 'claude' | 'codex' | 'gemini' | 'kimi';

interface LaneState {
  status: 'idle' | 'thinking' | 'tool' | 'waiting' | 'done' | 'error' | 'stuck' | 'starting';
  detail: string;
}

export const App: React.FC = () => {
  const [lanes, setLanes] = useState<Record<LaneName, LaneState>>({
    claude: {status: 'starting', detail: 'booting'},
    codex: {status: 'starting', detail: 'booting'},
    gemini: {status: 'starting', detail: 'booting'},
    kimi: {status: 'starting', detail: 'booting'},
  });

  useEffect(() => {
    const processes: Record<LaneName, LaneProcess> = {} as any;
    (['claude', 'codex', 'gemini', 'kimi'] as LaneName[]).forEach(name => {
      const proc = new LaneProcess(name);
      proc.start().then(() => {
        setLanes(prev => ({...prev, [name]: {status: 'idle', detail: 'ready'}}));
      }).catch(err => {
        console.error(`Failed to start ${name}:`, err);
        setLanes(prev => ({...prev, [name]: {status: 'error', detail: 'launch failed'}}));
      });
      proc.onData(chunk => {
        const hint = parseOutput(chunk);
        if (hint) setLanes(prev => ({...prev, [name]: {status: hint.status, detail: hint.detail ?? ''}}));
      });
      proc.onExit(code => {
        setLanes(prev => ({...prev, [name]: {status: 'error', detail: `exited (${code})`}}));
      });
      proc.onCrash(({crashCount}) => {
        if (crashCount === 1) {
          // Crash recovery level 1: silent auto-restart + retry
          proc.start().catch(err => {
            console.error(`Failed to restart ${name}:`, err);
          });
          setLanes(prev => ({...prev, [name]: {status: 'starting', detail: 'restarting'}}));
        } else if (crashCount === 2) {
          // Crash recovery level 2: escalate to Chrono (pause + alert)
          setLanes(prev => ({...prev, [name]: {status: 'error', detail: 'crashed twice — pausing'}}));
          // TODO: send Chrono a narration event
        } else if (crashCount >= 3) {
          // Crash recovery level 3: circuit open at daemon level
          setLanes(prev => ({...prev, [name]: {status: 'stuck', detail: 'circuit open'}}));
        }
      });
      processes[name] = proc;
    });
    return () => {
      Object.values(processes).forEach(p => p.kill());
    };
  }, []);

  const readyCount = Object.values(lanes).filter(l => l.status !== 'starting').length;

  return (
    <Box flexDirection="column">
      <Header project="none" readyCount={readyCount} totalLanes={4}
        timestamp={new Date().toLocaleTimeString()}
        usage={{claude: 0, codex: 0, gemini: 0, kimi: 0}} />
      <ChronoPane status="idle" transcript={[{role: 'chrono', text: 'ready'}]} />
      <Box flexDirection="row" width="100%">
        {(['claude', 'codex', 'gemini', 'kimi'] as LaneName[]).map(name => (
          <LanePane key={name} name={name} status={lanes[name].status} detail={lanes[name].detail} />
        ))}
      </Box>
    </Box>
  );
};
