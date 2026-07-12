export interface SpecialistChoice {
  specialist: string;
  lane: 'claude' | 'codex' | 'gemini' | 'kimi';
  model: string;
  model_key: string;
}

export interface SpecialistMap {
  specialists: Record<string, {
    lane: string;
    model_key: string;
    tags: string[];
    keywords: string[];
  }>;
  lanes: Record<string, {default: string; [key: string]: string}>;
}

export function pickSpecialist(request: string, map: SpecialistMap): SpecialistChoice[] {
  const req = request.toLowerCase();
  const matches: SpecialistChoice[] = [];
  for (const [name, spec] of Object.entries(map.specialists)) {
    for (const kw of spec.keywords ?? []) {
      if (req.includes(kw.toLowerCase())) {
        const lane = spec.lane as 'claude' | 'codex' | 'gemini' | 'kimi';
        matches.push({
          specialist: name,
          lane,
          model: map.lanes[lane][spec.model_key] ?? map.lanes[lane].default,
          model_key: spec.model_key,
        });
        break;
      }
    }
  }
  return matches.length ? matches : [];
}
