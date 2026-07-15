import { readJsonWithin, toSystemPath } from "./filesystem.mjs";
import { runJsonCommand } from "./process.mjs";

const referencePattern = /^(fixture|manifest|descriptor):([A-Za-z0-9._/-]+)$/u;
const directoryByKind = {
  descriptor: "descriptors",
  fixture: "fixtures",
  manifest: "manifests",
};

function resolveReference(reference) {
  const match = referencePattern.exec(reference);
  if (!match || match[2].split("/").some((part) => part === ".." || !part)) {
    throw new Error("invalid external reference");
  }
  return `${directoryByKind[match[1]]}/${match[2]}.json`;
}

function defaultRecallRunner(request, environment) {
  const bridge = toSystemPath(new URL("./vault_recall_bridge.py", import.meta.url));
  return runJsonCommand("python3", [bridge], request, {
    environment: { ...process.env, ...environment },
  });
}

export function createExternalInput({
  environment = process.env,
  jsonLoader = readJsonWithin,
  recallRunner = defaultRecallRunner,
} = {}) {
  return Object.freeze({
    async loadJson(reference) {
      const root = environment.CHRONO_BOUNTY_ROOT;
      if (!root) throw new Error("CHRONO_BOUNTY_ROOT is required for Layer-2 reads");
      return jsonLoader(root, resolveReference(reference));
    },

    async recall(query, filters = undefined, limit = 8) {
      if (!environment.CHRONO_VAULT_ROOT) {
        return { status: "recall_unavailable", reason: "vault_root_unset" };
      }
      if (environment.CHRONO_VAULT_CLEARANCE !== "restricted") {
        return {
          status: "insufficient_clearance",
          reason: "restricted_clearance_required",
        };
      }
      try {
        const result = await recallRunner({ query, filters, limit }, environment);
        if (result.status === "ok" && result.clearance_effective !== "restricted") {
          return {
            status: "insufficient_clearance",
            reason: "effective_clearance_not_restricted",
          };
        }
        return result;
      } catch (error) {
        return {
          status: "recall_unavailable",
          reason: "bridge_error",
          error_type: error?.name ?? "Error",
        };
      }
    },
  });
}

export const externalInput = createExternalInput();
