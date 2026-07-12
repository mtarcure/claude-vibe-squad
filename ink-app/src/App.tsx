import React, { useEffect, useState } from 'react';
import { Box } from 'ink';
import { Header } from './components/Header.js';
import { ChronoPane } from './components/ChronoPane.js';
import { LanePane } from './components/LanePane.js';
import { LaneProcess } from './pty/lane-process.js';
import { parseOutput } from './pty/output-parser.js';
import { loadChronoPrompt } from './chrono/prompt-loader.js';
import { loadSpecialistMap, SpecialistMapConfig } from './config/loadSpecialistMap.js';
import { useChrono } from './hooks/useChrono.js';
import { useDaemonEvents } from './hooks/useDaemonEvents.js';
import { dispatchTask } from './daemon-client/http.js';
import { pickSpecialist } from './chrono/router.js';

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

  const [chronoPrompt, setChronoPrompt] = useState('');
  const [specialistMap, setSpecialistMap] = useState<SpecialistMapConfig | null>(null);
  const [taskStates, setTaskStates] = useState<Record<string, string>>({});

  // Load Chrono prompt and specialist map at startup
  useEffect(() => {
    loadChronoPrompt().then(setChronoPrompt);
    loadSpecialistMap().then(setSpecialistMap).catch(err => {
      console.error('Failed to load specialist map:', err);
    });
  }, []);

  // Initialize Chrono client and daemon event subscriber
  const { transcript, pending, send: sendChrono } = useChrono(chronoPrompt);
  const { lastEvent } = useDaemonEvents();

  // Initialize lane processes
  useEffect(() => {
    if (!specialistMap) return;

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
          proc.start().catch(err => {
            console.error(`Failed to restart ${name}:`, err);
          });
          setLanes(prev => ({...prev, [name]: {status: 'starting', detail: 'restarting'}}));
        } else if (crashCount === 2) {
          setLanes(prev => ({...prev, [name]: {status: 'error', detail: 'crashed twice — pausing'}}));
        } else if (crashCount >= 3) {
          setLanes(prev => ({...prev, [name]: {status: 'stuck', detail: 'circuit open'}}));
        }
      });
      processes[name] = proc;
    });
    return () => {
      Object.values(processes).forEach(p => p.kill());
    };
  }, [specialistMap]);

  // When Chrono responds, route and dispatch to specialists
  useEffect(() => {
    if (!specialistMap || transcript.length === 0 || pending) return;

    const last = transcript[transcript.length - 1];
    if (last.role !== 'chrono') return;

    // Pick specialists based on Chrono's response
    const choices = pickSpecialist(last.text, specialistMap as any);
    for (const choice of choices) {
      const dept = specialistMap.specialists[choice.specialist]?.source_namespace || 'shared';
      const packet = {
        specialist: choice.specialist,
        specialist_file: `departments/${dept}/specialists/${choice.specialist}.md`,
        lane: choice.lane,
        model: choice.model,
        model_key: choice.model_key,
        prompt: last.text,
      };

      dispatchTask(packet)
        .then(({task_id}) => {
          setLanes(prev => ({
            ...prev,
            [choice.lane]: {
              status: 'thinking' as const,
              detail: `task ${task_id.slice(0, 8)}...`,
            },
          }));
          setTaskStates(prev => ({...prev, [task_id]: 'dispatched'}));
        })
        .catch(err => {
          console.error(`Failed to dispatch to ${choice.specialist}:`, err);
          setLanes(prev => ({
            ...prev,
            [choice.lane]: { status: 'error' as const, detail: 'dispatch failed' },
          }));
        });
    }
  }, [transcript, specialistMap, pending]);

  // Update lane state when daemon reports task completion
  useEffect(() => {
    if (!lastEvent) return;

    if (lastEvent.type === 'task_complete') {
      setTaskStates(prev => ({...prev, [lastEvent.task_id]: 'done'}));
      const laneNames = (['claude', 'codex', 'gemini', 'kimi'] as LaneName[]);
      laneNames.forEach(name => {
        setLanes(prev => ({
          ...prev,
          [name]: prev[name].status === 'thinking' ? {...prev[name], status: 'done' as const} : prev[name],
        }));
      });
    } else if (lastEvent.type === 'task_error') {
      setTaskStates(prev => ({...prev, [lastEvent.task_id]: 'error'}));
      const laneNames = (['claude', 'codex', 'gemini', 'kimi'] as LaneName[]);
      laneNames.forEach(name => {
        setLanes(prev => ({
          ...prev,
          [name]: prev[name].status === 'thinking' ? {...prev[name], status: 'error' as const, detail: 'task failed'} : prev[name],
        }));
      });
    }
  }, [lastEvent]);

  const readyCount = Object.values(lanes).filter(l => l.status !== 'starting').length;
  const chronoStatus = pending ? 'thinking' as const : 'idle' as const;

  return (
    <Box flexDirection="column">
      <Header
        project="none"
        readyCount={readyCount}
        totalLanes={4}
        timestamp={new Date().toLocaleTimeString()}
        usage={{claude: 0, codex: 0, gemini: 0, kimi: 0}}
      />
      <ChronoPane
        status={chronoStatus}
        transcript={transcript}
        onSubmit={sendChrono}
        pending={pending}
      />
      <Box flexDirection="row" width="100%">
        {(['claude', 'codex', 'gemini', 'kimi'] as LaneName[]).map(name => (
          <LanePane
            key={name}
            name={name}
            status={lanes[name].status}
            detail={lanes[name].detail}
          />
        ))}
      </Box>
    </Box>
  );
};
