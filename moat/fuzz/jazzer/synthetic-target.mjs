const TRANSITIONS = Object.freeze([
  "normal",
  "prefetch",
  "rsc",
  "action",
  "rewrite",
  "redirect",
  "header",
  "path",
]);

const counts = Object.fromEntries(TRANSITIONS.map((name) => [name, 0]));

export function normalizeAndDispatch(data) {
  const first = data[0] ?? 0;
  const transition = TRANSITIONS[first % TRANSITIONS.length];
  counts[transition] += 1;

  if (transition === "normal") return { transition, normalized: "public" };
  if (transition === "prefetch") return { transition, normalized: "prefetch" };
  if (transition === "rsc") return { transition, normalized: "component" };
  if (transition === "action") return { transition, normalized: "action" };
  if (transition === "rewrite") return { transition, normalized: "rewrite" };
  if (transition === "redirect") return { transition, normalized: "redirect" };
  if (transition === "header") return { transition, normalized: "header" };
  return { transition, normalized: "path" };
}

export function fuzz(data) {
  normalizeAndDispatch(data);
}

export function transitionCoverage() {
  return structuredClone(counts);
}
