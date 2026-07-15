import { joinSystemPath } from "../adapters/filesystem.mjs";
import { runCommand } from "../adapters/process.mjs";

const commitPattern = /^[0-9a-f]{40,64}$/u;
const logicalFixPattern = /^fix:[A-Za-z0-9._/-]+$/u;
const sourceFilePattern = /\.(?:c|cc|cpp|go|java|js|jsx|mjs|py|rs|ts|tsx)$/u;

const runGit = (mirrorPath, args, options = {}) => runCommand(
  "git",
  ["-C", mirrorPath, ...args],
  options,
);

function toolStatus(command, args = ["--version"]) {
  const result = runCommand(command, args, { allowMissing: true });
  return {
    available: result.available,
    version: result.available
      ? `${result.stdout}${result.stderr}`.trim().split("\n")[0]
      : null,
  };
}

export function inspectFullHistoryMirror(mirrorPath) {
  const gitDirectory = runGit(mirrorPath, ["rev-parse", "--git-dir"]);
  const shallow = runGit(mirrorPath, ["rev-parse", "--is-shallow-repository"])
    .stdout.trim();
  if (shallow !== "false") throw new Error("patch graph requires a full-history mirror");
  return {
    path: mirrorPath,
    git_directory: gitDirectory.stdout.trim(),
    full_history: true,
  };
}

function parseChangedFiles(mirrorPath, parent, commit) {
  return runGit(mirrorPath, ["diff", "--name-only", parent, commit, "--"])
    .stdout.split("\n")
    .filter((file) => sourceFilePattern.test(file));
}

function collectTooling(mirrorPath, parent, commit, changedFiles) {
  const treeSitter = toolStatus("tree-sitter");
  const difftastic = toolStatus("difft");

  if (treeSitter.available) {
    const parses = changedFiles.map((file) => runCommand(
      "tree-sitter",
      ["parse", "--quiet", joinSystemPath(mirrorPath, file)],
      { allowExitCodes: [0, 1] },
    ));
    treeSitter.generated = parses.some(({ status }) => status === 0);
  } else {
    treeSitter.generated = false;
  }

  if (difftastic.available) {
    const structural = runGit(mirrorPath, [
      "-c",
      "diff.external=difft",
      "diff",
      "--ext-diff",
      "--no-textconv",
      parent,
      commit,
      "--",
      ...changedFiles,
    ], { allowExitCodes: [0, 1] });
    difftastic.generated = structural.stdout.length > 0;
  } else {
    difftastic.generated = false;
  }

  return { tree_sitter: treeSitter, difftastic };
}

export function ingestFix(mirrorPath, manualFix) {
  inspectFullHistoryMirror(mirrorPath);
  if (
    !logicalFixPattern.test(manualFix?.ref ?? "")
    || !commitPattern.test(manualFix?.commit ?? "")
  ) {
    throw new Error("a logical fix ref and full commit id are required");
  }
  runGit(mirrorPath, ["cat-file", "-e", `${manualFix.commit}^{commit}`]);
  const parent = runGit(mirrorPath, ["rev-parse", `${manualFix.commit}^`]).stdout.trim();
  const changedFiles = parseChangedFiles(mirrorPath, parent, manualFix.commit);
  const diff = runGit(mirrorPath, [
    "diff",
    "--no-ext-diff",
    "--unified=3",
    parent,
    manualFix.commit,
    "--",
    ...changedFiles,
  ]).stdout;
  return {
    ref: manualFix.ref,
    commit: manualFix.commit,
    parent,
    mirror_path: mirrorPath,
    changed_files: changedFiles,
    diff,
    tooling: collectTooling(mirrorPath, parent, manualFix.commit, changedFiles),
  };
}

function candidateLines(diff) {
  const candidates = [];
  let file = null;
  let lineNumber = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++ b/")) {
      file = line.slice(6);
      continue;
    }
    const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/u.exec(line);
    if (hunk) {
      lineNumber = Number(hunk[1]);
      continue;
    }
    if (line.startsWith("+") && !line.startsWith("+++")) {
      const guard = /^\+\s*if\s*\((.+)\)\s*(?:return|throw|\{)/u.exec(line);
      if (guard && file) candidates.push({ file, line: lineNumber, predicate: guard[1] });
      lineNumber += 1;
    } else if (!line.startsWith("-")) {
      lineNumber += 1;
    }
  }
  return candidates;
}

export function extractGuardCandidates(fix) {
  if (!logicalFixPattern.test(fix?.ref ?? "") || typeof fix?.diff !== "string") {
    throw new Error("an ingested fix is required");
  }
  return candidateLines(fix.diff).map((candidate, index) => {
    const structuralSignals = Number(fix.tooling?.tree_sitter?.generated === true)
      + Number(fix.tooling?.difftastic?.generated === true);
    return {
      id: `candidate:${fix.ref.slice(4)}-${index + 1}`,
      schema_version: "1.0.0",
      source_fix_ref: fix.ref,
      review_state: "candidate",
      confidence: Math.min(0.9, 0.7 + (structuralSignals * 0.08)),
      predicate: candidate.predicate,
      location: { path: candidate.file, line: candidate.line },
      generators: ["unified-diff", "tree-sitter", "difftastic"],
      tooling: fix.tooling,
    };
  });
}

function callName(value) {
  const match = /^call:([A-Za-z_$][\w$]*)$/u.exec(value ?? "");
  if (!match) throw new Error("reviewed annotation requires call-shaped barrier and sink refs");
  return match[1];
}

function functionsInSource(source) {
  const lines = source.split("\n");
  const functions = [];
  for (let start = 0; start < lines.length; start += 1) {
    const declaration = /(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/u
      .exec(lines[start]);
    if (!declaration) continue;
    let depth = 0;
    let opened = false;
    let end = start;
    for (; end < lines.length; end += 1) {
      for (const character of lines[end]) {
        if (character === "{") {
          depth += 1;
          opened = true;
        } else if (character === "}") {
          depth -= 1;
        }
      }
      if (opened && depth === 0) break;
    }
    functions.push({ name: declaration[1], start, lines: lines.slice(start, end + 1) });
    start = end;
  }
  return functions;
}

export function findSyntacticSiblings(mirrorPath, revision, annotation) {
  inspectFullHistoryMirror(mirrorPath);
  if (!commitPattern.test(revision ?? "") || annotation?.review?.state !== "reviewed") {
    throw new Error("reviewed annotation and full revision are required");
  }
  const barrier = callName(annotation.barriers?.[0]);
  const sink = callName(annotation.sinks?.[0]);
  const files = runGit(mirrorPath, ["ls-tree", "-r", "--name-only", revision])
    .stdout.split("\n")
    .filter((file) => sourceFilePattern.test(file));
  const matches = [];

  for (const file of files) {
    const source = runGit(mirrorPath, ["show", `${revision}:${file}`]).stdout;
    for (const found of functionsInSource(source)) {
      const sinkIndex = found.lines.findIndex((line) => line.includes(`${sink}(`));
      if (sinkIndex < 0) continue;
      const beforeSink = found.lines.slice(0, sinkIndex + 1).join("\n");
      if (beforeSink.includes(`${barrier}(`)) continue;
      matches.push({
        path: file,
        line: found.start + sinkIndex + 1,
        function_name: found.name,
        sink: `call:${sink}`,
      });
    }
  }
  return matches.sort((left, right) => left.path.localeCompare(right.path) || left.line - right.line);
}
