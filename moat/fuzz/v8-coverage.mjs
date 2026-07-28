import inspector from "node:inspector";

const post = (session, method, params = {}) => new Promise((resolve, reject) => {
  session.post(method, params, (error, result) => {
    if (error) reject(error);
    else resolve(result);
  });
});

const percent = (covered, total) => total === 0 ? 0 : Math.round((covered / total) * 100);

export async function collectV8Coverage(run, {
  include = ["/moat/twinlab/", "/moat/oracle/"],
} = {}) {
  const session = new inspector.Session();
  session.connect();
  await post(session, "Profiler.enable");
  await post(session, "Profiler.startPreciseCoverage", { callCount: true, detailed: true });

  try {
    const value = await run();
    const snapshot = await post(session, "Profiler.takePreciseCoverage");
    const scripts = snapshot.result.filter((script) =>
      include.some((fragment) => script.url.includes(fragment)));
    let totalFunctions = 0;
    let coveredFunctions = 0;
    let totalRanges = 0;
    let coveredRanges = 0;

    for (const script of scripts) {
      for (const entry of script.functions) {
        totalFunctions += 1;
        if (entry.ranges.some((range) => range.count > 0)) coveredFunctions += 1;
        totalRanges += entry.ranges.length;
        coveredRanges += entry.ranges.filter((range) => range.count > 0).length;
      }
    }

    return {
      value,
      coverage: {
        engine: "v8",
        scripts: scripts.length,
        totalFunctions,
        coveredFunctions,
        functionPercent: percent(coveredFunctions, totalFunctions),
        totalRanges,
        coveredRanges,
        rangePercent: percent(coveredRanges, totalRanges),
      },
    };
  } finally {
    await post(session, "Profiler.stopPreciseCoverage");
    await post(session, "Profiler.disable");
    session.disconnect();
  }
}
