import { spawnSync } from "node:child_process";

export function scanSecretsWithGitleaks(text) {
  const result = spawnSync(
    "gitleaks",
    [
      "stdin",
      "--no-banner",
      "--no-color",
      "--redact=100",
      "--report-format",
      "json",
      "--report-path",
      "-",
      "--log-level",
      "error",
    ],
    { input: text, encoding: "utf8", maxBuffer: 1024 * 1024 },
  );

  if (result.error?.code === "ENOENT") return { available: false, findings: [] };
  if (result.error) throw result.error;
  if (![0, 1].includes(result.status)) {
    throw new Error(`gitleaks failed with status ${result.status}`);
  }

  const findings = result.stdout.trim() ? JSON.parse(result.stdout) : [];
  return {
    available: true,
    findings: findings.map((item) => ({
      line: item.StartLine ?? 1,
      ruleId: item.RuleID ?? "unknown",
    })),
  };
}
