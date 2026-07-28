import { spawnSync } from "node:child_process";

export function runCommand(command, args, {
  allowExitCodes = [0],
  allowMissing = false,
  environment = process.env,
  input,
  workingDirectory,
} = {}) {
  const result = spawnSync(command, args, {
    cwd: workingDirectory,
    encoding: "utf8",
    env: environment,
    input,
    maxBuffer: 4 * 1024 * 1024,
  });

  if (result.error?.code === "ENOENT" && allowMissing) {
    return { available: false, status: null, stdout: "", stderr: "" };
  }
  if (result.error) throw result.error;
  if (!allowExitCodes.includes(result.status)) {
    throw new Error(`${command} failed with status ${result.status}`);
  }
  return {
    available: true,
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export function runJsonCommand(command, args, payload, { environment = process.env } = {}) {
  const result = runCommand(command, args, {
    environment,
    input: JSON.stringify(payload),
  });
  return JSON.parse(result.stdout);
}

export function commandLineArguments() {
  return process.argv.slice(2);
}

export function reportCommandError(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

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
