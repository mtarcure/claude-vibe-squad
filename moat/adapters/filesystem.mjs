import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readdir, readFile, realpath, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
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

export async function resolvePathWithin(root, relativePath, {
  realpathImpl = realpath,
} = {}) {
  const rootPath = asPath(root);
  const target = path.resolve(rootPath, relativePath);
  if (target === rootPath || !target.startsWith(`${rootPath}${path.sep}`)) {
    throw new Error("external path escapes its configured root");
  }
  const [realRoot, realTarget] = await Promise.all([
    realpathImpl(rootPath),
    realpathImpl(target),
  ]);
  if (realTarget === realRoot || !realTarget.startsWith(`${realRoot}${path.sep}`)) {
    throw new Error("external real path escapes its configured root");
  }
  return realTarget;
}

export async function readJsonWithin(root, relativePath, {
  realpathImpl = realpath,
  readJsonImpl = readJson,
} = {}) {
  const realTarget = await resolvePathWithin(root, relativePath, { realpathImpl });
  return readJsonImpl(realTarget);
}

export function toSystemPath(value) {
  return asPath(value);
}

export function joinSystemPath(...parts) {
  return path.join(...parts.map(String));
}

export async function createTemporaryDirectory(prefix) {
  return mkdtemp(path.join(tmpdir(), prefix));
}

export async function ensureDirectory(directory) {
  await mkdir(asPath(directory), { recursive: true });
}

export async function writeText(file, content) {
  await writeFile(asPath(file), content, "utf8");
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
