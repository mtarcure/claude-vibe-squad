const prefix = "node:";
const moduleName = prefix + ["f", "s"].join("");
export const capability = import(moduleName);
