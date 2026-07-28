const clone = (value) => structuredClone(value);

export function createLoopbackOracleKit() {
  const records = {
    http: [],
    redirects: [],
    protectedAccesses: [],
    actions: [],
    egress: [],
    guards: [],
    violations: [],
  };

  return Object.freeze({
    recordHttp(request) {
      records.http.push(clone(request));
    },
    recordRedirect(redirect) {
      records.redirects.push(clone(redirect));
    },
    recordProtectedAccess(access) {
      const entry = clone(access);
      records.protectedAccesses.push(entry);
      if (entry.trustedMarker !== true) {
        records.violations.push({ class: "protected-access", observation: entry });
      }
    },
    recordAction(action) {
      const entry = clone(action);
      records.actions.push(entry);
      if (entry.authorized !== true) {
        records.violations.push({ class: "unauthorized-action", observation: entry });
      }
    },
    recordEgress(attempt) {
      records.egress.push(clone(attempt));
    },
    recordGuard(decision) {
      records.guards.push(clone(decision));
    },
    observe() {
      return clone(records);
    },
  });
}
