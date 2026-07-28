function assertContract(appTemplate, oracleKit, isolationProfile) {
  if (!appTemplate || typeof appTemplate.create !== "function") {
    throw new TypeError("appTemplate must expose create()");
  }
  if (!oracleKit || typeof oracleKit.observe !== "function") {
    throw new TypeError("oracleKit must expose observe()");
  }
  if (isolationProfile?.kind !== "in-process" || isolationProfile.network !== "disabled") {
    throw new TypeError("Phase 4a requires the in-process, network-disabled isolation profile");
  }
}

export function provision(appTemplate, oracleKit, isolationProfile) {
  assertContract(appTemplate, oracleKit, isolationProfile);
  let lifecycle = "idle";
  let app;

  return Object.freeze({
    async start() {
      if (lifecycle !== "idle") throw new Error(`lab cannot start from ${lifecycle}`);
      app = appTemplate.create({ oracle: oracleKit, isolationProfile });
      if (!app || typeof app.dispatch !== "function") {
        throw new TypeError("created app must expose dispatch()");
      }
      lifecycle = "started";
      return Object.freeze({
        dispatch: async (request) => {
          if (lifecycle !== "started") throw new Error("lab is not running");
          return app.dispatch(request);
        },
      });
    },
    async stop() {
      if (lifecycle === "stopped") return;
      if (app && typeof app.stop === "function") await app.stop();
      lifecycle = "stopped";
    },
    observe() {
      return {
        lifecycle,
        templateId: appTemplate.id,
        oracle: oracleKit.observe(),
        app: app?.observe?.() ?? null,
      };
    },
  });
}
