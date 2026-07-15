import { readJson } from "../adapters/filesystem.mjs";
import { commandLineArguments, reportCommandError } from "../adapters/process.mjs";
import { assertIndexCurrent } from "./invariant-index.mjs";

export async function checkInvariantIndex(args) {
  const indexFlag = args.indexOf("--index");
  if (indexFlag < 0 || !args[indexFlag + 1]) {
    throw new Error("usage: check-invariant-index --index INDEX DESCRIPTOR...");
  }
  const descriptorPaths = args.filter((_, index) => index !== indexFlag && index !== indexFlag + 1);
  if (!descriptorPaths.length) throw new Error("at least one descriptor is required");
  const [index, ...descriptors] = await Promise.all([
    readJson(args[indexFlag + 1]),
    ...descriptorPaths.map((file) => readJson(file)),
  ]);
  assertIndexCurrent(descriptors, index);
}

try {
  await checkInvariantIndex(commandLineArguments());
} catch (error) {
  reportCommandError(error?.message ?? "index check failed");
}
