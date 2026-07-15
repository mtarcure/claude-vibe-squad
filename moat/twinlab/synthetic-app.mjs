const TRUSTED_MARKER = "present";

function isTrusted(request) {
  return request.headers?.["x-trusted-middleware"] === TRUSTED_MARKER;
}

export function createSyntheticAppTemplate({ id, enforceTrustedMarker }) {
  if (typeof id !== "string" || !id) throw new TypeError("synthetic app id is required");
  if (typeof enforceTrustedMarker !== "boolean") {
    throw new TypeError("enforceTrustedMarker must be boolean");
  }

  return Object.freeze({
    id,
    create({ oracle }) {
      let actionExecutions = 0;
      let stopped = false;

      const guarded = (request, kind) => {
        const trustedMarker = isTrusted(request);
        const allowed = trustedMarker || !enforceTrustedMarker;
        oracle.recordGuard({ kind, allowed, trustedMarker });
        return { allowed, trustedMarker };
      };

      const protectedRoute = (request) => {
        const decision = guarded(request, "protected-route");
        if (!decision.allowed) return { status: 403, blocked: true, violation: false };
        oracle.recordProtectedAccess({
          route: "synthetic-protected",
          trustedMarker: decision.trustedMarker,
        });
        return { status: 200, protected: true, violation: !decision.trustedMarker };
      };

      const harmlessAction = (request) => {
        const decision = guarded(request, "harmless-action");
        if (!decision.allowed) return { status: 403, blocked: true, violation: false };
        actionExecutions += 1;
        oracle.recordAction({
          action: "synthetic-harmless-action",
          authorized: decision.trustedMarker,
          execution: actionExecutions,
        });
        return { status: 200, actionExecutions, violation: !decision.trustedMarker };
      };

      return Object.freeze({
        async dispatch(request) {
          if (stopped) throw new Error("synthetic app is stopped");
          oracle.recordHttp({
            method: request.method ?? "GET",
            route: request.path ?? "/",
            kind: request.kind ?? "normal",
          });

          if (request.kind === "redirect") {
            oracle.recordRedirect({ from: "/redirect", to: "/public", status: 302 });
            return { status: 302, location: "/public", violation: false };
          }
          if (request.kind === "action") return harmlessAction(request);
          if (request.kind === "rewrite") return protectedRoute(request);
          if (request.path === "/protected") return protectedRoute(request);
          return { status: 200, public: true, violation: false };
        },
        async stop() {
          stopped = true;
        },
        observe() {
          return { actionExecutions, stopped, enforceTrustedMarker };
        },
      });
    },
  });
}
