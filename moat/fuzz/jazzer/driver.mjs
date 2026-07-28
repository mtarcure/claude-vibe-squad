function summarizeIstanbulCoverage(coverageData, targetFragment) {
  let total = 0;
  let covered = 0;
  for (const [file, entry] of Object.entries(coverageData ?? {})) {
    if (!file.includes(targetFragment)) continue;
    for (const count of Object.values(entry.s ?? {})) {
      total += 1;
      if (count > 0) covered += 1;
    }
  }
  return {
    engine: "jazzer.js-istanbul",
    total,
    covered,
    percent: total === 0 ? 0 : Math.round((covered / total) * 100),
  };
}

export async function runJazzerEscalation({ seed, maxRuns }) {
  if (!Number.isInteger(maxRuns) || maxRuns < 1) throw new TypeError("Jazzer maxRuns must be positive");
  const core = await import("@jazzer.js/core");
  const targetUrl = new URL("./synthetic-target.mjs", import.meta.url);
  const options = new core.OptionsManager(core.OptionSource.DefaultCLIOptions);
  options.merge({
    coverage: true,
    coverageReporters: [],
    disableBugDetectors: [".*"],
    excludes: ["node_modules"],
    includes: ["/moat/fuzz/jazzer/"],
    fuzzTarget: targetUrl.pathname,
    fuzzerOptions: [`-runs=${maxRuns}`, `-seed=${seed}`],
    sync: true,
    timeout: 2_000,
  }, core.OptionSource.CommandLineArguments);
  options.merge({
    dictionaryEntries: Array.from({ length: 8 }, (_, value) => Uint8Array.of(value)),
  }, core.OptionSource.JestFuzzTestOptions);

  const result = await core.startFuzzing(options);
  if (result.returnCode !== core.FuzzingExitCode.Ok) {
    throw new Error(`Jazzer escalation failed with return code ${result.returnCode}`);
  }
  const target = await import("./synthetic-target.mjs");
  return {
    driver: "jazzer.js",
    invoked: true,
    seed,
    maxRuns,
    transitions: target.transitionCoverage(),
    coverage: summarizeIstanbulCoverage(globalThis.__coverage__, "/moat/fuzz/jazzer/synthetic-target.mjs"),
  };
}
