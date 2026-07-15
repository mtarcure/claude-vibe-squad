import { validateNamed } from "../schema/validate.mjs";
import { emitInvariant } from "./emit-invariant.mjs";
import { generateIndex } from "./invariant-index.mjs";
import { runOracle } from "./oracle.mjs";

function evidenceVerdict(oracle, ledgerResult) {
  const pass = oracle.calibrated && ledgerResult.status === "net_new";
  return {
    schema_version: "1.0.0",
    evidence_level: { level: pass ? "L3" : "L2", evidence_ref: "evidence:synthetic-oracle-log" },
    terminus: { class: pass ? "code_exec" : "none", evidence_ref: "evidence:synthetic-canary" },
    privilege_required: { level: "none", path_evidence_ref: "evidence:synthetic-request-path" },
    determinism: { mode: "deterministic", replay_ref: "replay:synthetic-fixed-seed" },
    documented_by_vendor: { value: false, source_ref: "ledger:synthetic-public-record" },
    net_new: { value: ledgerResult.status === "net_new", ledger_ref: "ledger:synthetic-dedup" },
    criteria: {
      general_bounty_gate: { decision: pass ? "PASS" : "KILL", evidence_ref: "evidence:synthetic-general-gate" },
      wave_criterion: { decision: pass ? "PASS" : "KILL", evidence_ref: "evidence:synthetic-wave-gate" },
    },
    gate: pass ? "PASS" : "KILL",
    rationale: pass
      ? "Synthetic reviewed slice reaches its calibrated oracle and is net-new in the supplied ledger."
      : "Synthetic reviewed slice did not satisfy every evidence gate.",
  };
}

export async function runManualSlice({ guard, fixRef, externalInput, ledgerResult }) {
  const guardErrors = await validateNamed("GuardAnnotation", guard);
  if (guardErrors.length) throw new Error("guard annotation is invalid");

  const invariant = emitInvariant(guard, { fixRef });
  const invariantErrors = await validateNamed("InvariantDescriptor", invariant);
  if (invariantErrors.length) throw new Error("emitted invariant is invalid");

  const [positiveFixture, negativeFixture] = await Promise.all([
    externalInput.loadJson(guard.positive_fixture_ref),
    externalInput.loadJson(guard.negative_fixture_ref),
  ]);
  const oracle = runOracle(positiveFixture, negativeFixture);
  const verdict = evidenceVerdict(oracle, ledgerResult);
  const verdictErrors = await validateNamed("Verdict", verdict);
  if (verdictErrors.length) throw new Error("evidence verdict is invalid");

  return {
    invariant,
    index: generateIndex([invariant]),
    oracle,
    verdict,
    validation: {
      guard: guardErrors,
      invariant: invariantErrors,
      verdict: verdictErrors,
    },
  };
}
