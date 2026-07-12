export interface SpecialistChoice {
  specialist: string;
  lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  model: string;
  model_key: string;
}

export interface SpecialistMap {
  specialists: Record<string, {
    best_model_lane?: string;
    lane?: string;
    model_key?: string;
    tags?: string[];
    keywords?: string[];
  }>;
  lanes: Record<string, {default: string; [key: string]: string}>;
}

export function pickSpecialist(request: string, map: SpecialistMap): SpecialistChoice[] {
  const req = request.toLowerCase();
  const matches: SpecialistChoice[] = [];
  for (const [name, spec] of Object.entries(map.specialists)) {
    for (const kw of spec.keywords ?? []) {
      if (req.includes(kw.toLowerCase())) {
        const lane = (spec.best_model_lane || spec.lane || 'claude') as 'claude' | 'codex' | 'gemini' | 'kimi';
        const modelKey = spec.model_key || 'default';
        matches.push({
          specialist: name,
          lane,
          model: map.lanes[lane]?.[modelKey] ?? map.lanes[lane]?.default ?? 'unknown',
          model_key: modelKey,
        });
        break;
      }
    }
  }
  return matches.length ? matches : [];
}
