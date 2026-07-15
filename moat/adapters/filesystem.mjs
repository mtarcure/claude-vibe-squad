import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const asPath = (value) =>
  path.resolve(value instanceof URL ? fileURLToPath(value) : String(value));

export async function readText(file) {
  return readFile(asPath(file), "utf8");
}

export async function readJson(file) {
  return JSON.parse(await readText(file));
}

export async function sha256(file) {
  const content = await readFile(asPath(file));
  return createHash("sha256").update(content).digest("hex");
}

export async function listFiles(root) {
  const rootPath = asPath(root);
  const entries = await readdir(rootPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    const entryPath = path.join(rootPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(entryPath)));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }

  return files;
}

export function pathDetails(file, root) {
  const absolute = asPath(file);
  const rootPath = asPath(root);
  return {
    absolute,
    basename: path.basename(absolute),
    extension: path.extname(absolute).toLowerCase(),
    relative: path.relative(rootPath, absolute).split(path.sep).join("/"),
    withinRoot: absolute === rootPath || absolute.startsWith(`${rootPath}${path.sep}`),
  };
}
