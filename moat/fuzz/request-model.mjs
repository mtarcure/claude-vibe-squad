import fc from "fast-check";

export const DECLARED_TRANSITIONS = Object.freeze([
  "normal",
  "prefetch",
  "rsc",
  "action",
  "rewrite",
  "redirect",
  "header",
  "path",
]);

const REQUESTS = new Map([
  ["normal", Object.freeze({ kind: "normal", method: "GET", path: "/public", headers: {} })],
  ["prefetch", Object.freeze({ kind: "prefetch", method: "GET", path: "/public", headers: { "x-prefetch": "1" } })],
  ["rsc", Object.freeze({ kind: "rsc", method: "GET", path: "/public", headers: { "x-rsc": "1" } })],
  ["action", Object.freeze({ kind: "action", method: "POST", path: "/action", headers: {} })],
  ["rewrite", Object.freeze({ kind: "rewrite", method: "GET", path: "/rewrite", headers: {} })],
  ["redirect", Object.freeze({ kind: "redirect", method: "GET", path: "/redirect", headers: {} })],
  ["header", Object.freeze({ kind: "header", method: "GET", path: "/protected", headers: { "x-synthetic": "1" } })],
  ["path", Object.freeze({ kind: "path", method: "GET", path: "/protected", headers: {} })],
]);

function sequencesFor({ seed, numRuns, transitions }) {
  const permutation = fc.shuffledSubarray(transitions, {
    minLength: transitions.length,
    maxLength: transitions.length,
  });
  return fc.sample(permutation, { seed, numRuns });
}

export function shrinkViolationSequence({ seed }) {
  const transition = fc.constantFrom(...DECLARED_TRANSITIONS);
  const sequence = fc.array(transition, { minLength: 1, maxLength: DECLARED_TRANSITIONS.length });
  const result = fc.check(
    fc.property(sequence, (steps) => !steps.some((step) =>
      step === "action" || step === "rewrite" || step === "header" || step === "path")),
    { seed, numRuns: 100 },
  );
  if (!result.failed) throw new Error("synthetic calibration model did not expose a counterexample");
  return result.counterexample[0];
}

export async function exerciseRequestModel({ dispatch, seed, numRuns, transitions = DECLARED_TRANSITIONS }) {
  if (typeof dispatch !== "function") throw new TypeError("dispatch must be a function");
  if (!Number.isInteger(numRuns) || numRuns < 1) throw new TypeError("numRuns must be positive");
  const sequences = sequencesFor({ seed, numRuns, transitions });
  const counts = Object.fromEntries(DECLARED_TRANSITIONS.map((name) => [name, 0]));
  const edges = {};
  let successes = 0;

  for (const sequence of sequences) {
    let prior = "initial";
    let detected = false;
    for (const transition of sequence) {
      counts[transition] += 1;
      const edge = `${prior}->${transition}`;
      edges[edge] = (edges[edge] ?? 0) + 1;
      prior = transition;
      const response = await dispatch(structuredClone(REQUESTS.get(transition)));
      detected ||= response.violation === true;
    }
    if (detected) successes += 1;
  }

  return { counts, edges, sequences, successes, attempts: numRuns };
}
