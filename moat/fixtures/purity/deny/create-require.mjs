import { createRequire } from "node:module";

const load = createRequire(import.meta.url);
const moduleName = ["node:", "tls"].join("");
export const capability = load(moduleName);
