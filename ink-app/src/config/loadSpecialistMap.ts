import { readFile } from 'fs/promises';

export interface SpecialistEntry {
  name: string;
  best_model_lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  review_model: string;
  source_namespace: string;
  required_tools_mcp_api: string;
  safety_level: string;
  preferred_tools: string;
  notes: string;
  keywords: string[];
}

export interface SpecialistMapConfig {
  specialists: Record<string, SpecialistEntry>;
  lanes: Record<string, { default: string; [key: string]: string }>;
}

const SPECIALIST_MAP_PATH = '/Users/user/Obsidian-Claude-Vibe-Squad/shared/specialist-runtime-map.tsv';

const LANE_CONFIG: Record<string, { default: string; [key: string]: string }> = {
  claude: { default: 'claude-sonnet-5', hard: 'claude-opus-4-8' },
  codex: { default: 'gpt-5' },
  gemini: { default: 'gemini-3.5-flash', deep: 'gemini-3.1-pro-preview', image: 'gemini-3-pro-image' },
  kimi: { default: 'kimi-k2.7-code' },
};

export async function loadSpecialistMap(): Promise<SpecialistMapConfig> {
  const content = await readFile(SPECIALIST_MAP_PATH, 'utf-8');
  const lines = content.trim().split('\n');

  if (lines.length < 2) {
    throw new Error('Invalid specialist map: missing header or data');
  }

  // Parse header (skip comment line if present)
  let headerLine = lines[0];
  let dataStartIdx = 1;
  if (headerLine.startsWith('#')) {
    headerLine = lines[1];
    dataStartIdx = 2;
  }

  const headers = headerLine.split('\t');
  const specialists: Record<string, SpecialistEntry> = {};

  // Parse data rows
  for (let i = dataStartIdx; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    const cols = line.split('\t');
    const rowObj: Record<string, string> = {};
    for (let j = 0; j < headers.length && j < cols.length; j++) {
      rowObj[headers[j]] = cols[j];
    }

    // Map TSV columns to our interface
    const name = rowObj['specialist'] || '';
    if (!name) continue;

    // Infer keywords from name and tags
    const nameParts = name.split('-').filter(p => p.length > 0);
    const tags = rowObj['preferred_tools']?.split(',').map(t => t.trim()) || [];
    const keywords = [...nameParts, ...tags.slice(0, 2)];

    const entry: SpecialistEntry = {
      name,
      best_model_lane: (rowObj['best_model_lane'] || 'claude') as 'claude' | 'codex' | 'gemini' | 'kimi',
      review_model: rowObj['review_model'] || '',
      source_namespace: rowObj['source_namespace'] || '',
      required_tools_mcp_api: rowObj['required_tools_mcp_api'] || '',
      safety_level: rowObj['safety_level'] || 'medium',
      preferred_tools: rowObj['preferred_tools'] || '',
      notes: rowObj['notes'] || '',
      keywords,
    };

    specialists[name] = entry;
  }

  return {
    specialists,
    lanes: LANE_CONFIG,
  };
}
