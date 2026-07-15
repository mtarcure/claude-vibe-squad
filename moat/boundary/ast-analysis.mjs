import ts from "typescript";

const unknown = Object.freeze({ known: false, value: undefined, encoded: false });
const known = (value, encoded = false) => ({ known: true, value, encoded });

function scriptKind(fileName) {
  if (fileName.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (fileName.endsWith(".ts")) return ts.ScriptKind.TS;
  if (fileName.endsWith(".jsx")) return ts.ScriptKind.JSX;
  if (fileName.endsWith(".json")) return ts.ScriptKind.JSON;
  return ts.ScriptKind.JS;
}

function propertyName(node) {
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) return node.text;
  if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return node.text;
  return undefined;
}

function evaluate(node, constants, depth = 0) {
  if (!node || depth > 24) return unknown;
  if (ts.isStringLiteralLike(node)) return known(node.text);
  if (ts.isNumericLiteral(node)) return known(Number(node.text));
  if (node.kind === ts.SyntaxKind.TrueKeyword) return known(true);
  if (node.kind === ts.SyntaxKind.FalseKeyword) return known(false);
  if (node.kind === ts.SyntaxKind.NullKeyword) return known(null);
  if (ts.isIdentifier(node)) return constants.get(node.text) ?? unknown;
  if (
    ts.isParenthesizedExpression(node)
    || ts.isAsExpression(node)
    || ts.isTypeAssertionExpression(node)
    || ts.isNonNullExpression(node)
    || ts.isSatisfiesExpression(node)
  ) {
    return evaluate(node.expression, constants, depth + 1);
  }
  if (ts.isPrefixUnaryExpression(node)) {
    const operand = evaluate(node.operand, constants, depth + 1);
    if (!operand.known || typeof operand.value !== "number") return unknown;
    if (node.operator === ts.SyntaxKind.MinusToken) return known(-operand.value);
    if (node.operator === ts.SyntaxKind.PlusToken) return known(operand.value);
    return unknown;
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const left = evaluate(node.left, constants, depth + 1);
    const right = evaluate(node.right, constants, depth + 1);
    if (!left.known || !right.known) return unknown;
    if (!["string", "number"].includes(typeof left.value)) return unknown;
    if (!["string", "number"].includes(typeof right.value)) return unknown;
    return known(left.value + right.value, left.encoded || right.encoded);
  }
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text;
    let encoded = false;
    for (const span of node.templateSpans) {
      const expression = evaluate(span.expression, constants, depth + 1);
      if (!expression.known) return unknown;
      value += String(expression.value) + span.literal.text;
      encoded ||= expression.encoded;
    }
    return known(value, encoded);
  }
  if (ts.isArrayLiteralExpression(node)) {
    const values = node.elements.map((element) => evaluate(element, constants, depth + 1));
    if (values.some((value) => !value.known)) return unknown;
    return known(values.map(({ value }) => value), values.some(({ encoded }) => encoded));
  }
  if (!ts.isCallExpression(node)) return unknown;

  if (
    ts.isPropertyAccessExpression(node.expression)
    && ts.isIdentifier(node.expression.expression)
    && node.expression.expression.text === "String"
    && node.expression.name.text === "fromCharCode"
  ) {
    const values = node.arguments.map((argument) => evaluate(argument, constants, depth + 1));
    if (values.some((value) => !value.known || typeof value.value !== "number")) return unknown;
    return known(String.fromCharCode(...values.map(({ value }) => value)));
  }

  if (
    ts.isPropertyAccessExpression(node.expression)
    && ts.isIdentifier(node.expression.expression)
    && node.expression.expression.text === "Buffer"
    && node.expression.name.text === "from"
  ) {
    const input = evaluate(node.arguments[0], constants, depth + 1);
    const encoding = evaluate(node.arguments[1], constants, depth + 1);
    if (!input.known || typeof input.value !== "string") return unknown;
    if (!encoding.known || !["base64", "base64url"].includes(encoding.value)) return unknown;
    try {
      return known(Buffer.from(input.value, encoding.value), true);
    } catch {
      return unknown;
    }
  }

  if (ts.isPropertyAccessExpression(node.expression)) {
    const receiver = evaluate(node.expression.expression, constants, depth + 1);
    if (!receiver.known) return unknown;
    const method = node.expression.name.text;
    const args = node.arguments.map((argument) => evaluate(argument, constants, depth + 1));
    if (args.some((argument) => !argument.known)) return unknown;
    const values = args.map(({ value }) => value);
    if (method === "join" && Array.isArray(receiver.value)) {
      return known(receiver.value.join(values[0] ?? ","), receiver.encoded || args.some(({ encoded }) => encoded));
    }
    if (method === "toString" && Buffer.isBuffer(receiver.value)) {
      return known(receiver.value.toString(values[0] ?? "utf8"), receiver.encoded);
    }
    if (method === "slice" && typeof receiver.value === "string") {
      return known(receiver.value.slice(...values), receiver.encoded);
    }
  }
  return unknown;
}

function collectConstants(sourceFile) {
  const declarations = [];
  const constants = new Map();
  const visit = (node) => {
    if (
      ts.isVariableDeclarationList(node)
      && (node.flags & ts.NodeFlags.Const) !== 0
    ) {
      for (const declaration of node.declarations) {
        if (ts.isIdentifier(declaration.name) && declaration.initializer) declarations.push(declaration);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);

  for (let pass = 0; pass < Math.min(32, declarations.length + 1); pass += 1) {
    let changed = false;
    for (const declaration of declarations) {
      if (constants.has(declaration.name.text)) continue;
      const value = evaluate(declaration.initializer, constants);
      if (value.known) {
        constants.set(declaration.name.text, value);
        changed = true;
      }
    }
    if (!changed) break;
  }
  return { constants, declarations };
}

function memberPath(node) {
  if (ts.isIdentifier(node)) return [node.text];
  if (ts.isPropertyAccessExpression(node)) {
    const parent = memberPath(node.expression);
    return parent ? [...parent, node.name.text] : null;
  }
  if (ts.isElementAccessExpression(node)) {
    const parent = memberPath(node.expression);
    const argument = node.argumentExpression;
    if (!parent || !ts.isStringLiteralLike(argument)) return null;
    return [...parent, argument.text];
  }
  return null;
}

function callBinding(expression) {
  if (ts.isIdentifier(expression)) return { binding: expression.text, name: expression.text };
  if (ts.isPropertyAccessExpression(expression)) {
    let receiver = expression.expression;
    while (ts.isPropertyAccessExpression(receiver)) receiver = receiver.expression;
    return {
      binding: ts.isIdentifier(receiver) ? receiver.text : undefined,
      name: expression.name.text,
    };
  }
  return {};
}

const sinkProperties = new Set([
  "endpoint",
  "fixture_path",
  "host",
  "hostname",
  "path",
  "target",
  "target_host",
  "target_url",
  "url",
]);

export function analyzeSource(text, fileName, { restrictedModules = [] } = {}) {
  const sourceFile = ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    scriptKind(fileName),
  );
  const { constants, declarations } = collectConstants(sourceFile);
  const imports = [];
  const unresolvedImports = [];
  const directPrivateReads = [];
  const evaluatedStrings = [];
  const flows = [];
  const createRequireNames = new Set(["createRequire"]);
  const requireNames = new Set(["require"]);
  const capabilityBindings = new Set();
  const restricted = new Set(restrictedModules);

  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement)) continue;
    const specifier = evaluate(statement.moduleSpecifier, constants);
    if (specifier.known) imports.push({ value: String(specifier.value), offset: statement.getStart(sourceFile) });
    if (restricted.has(specifier.value)) {
      if (statement.importClause?.name) capabilityBindings.add(statement.importClause.name.text);
      const bindings = statement.importClause?.namedBindings;
      if (bindings && ts.isNamespaceImport(bindings)) capabilityBindings.add(bindings.name.text);
      if (bindings && ts.isNamedImports(bindings)) {
        for (const element of bindings.elements) capabilityBindings.add(element.name.text);
      }
    }
    if (specifier.value !== "node:module" && specifier.value !== "module") continue;
    for (const element of statement.importClause?.namedBindings?.elements ?? []) {
      if ((element.propertyName?.text ?? element.name.text) === "createRequire") {
        createRequireNames.add(element.name.text);
      }
    }
  }

  const aliasVisit = (node) => {
    if (
      ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.initializer
      && ts.isCallExpression(node.initializer)
      && ts.isIdentifier(node.initializer.expression)
      && createRequireNames.has(node.initializer.expression.text)
    ) {
      requireNames.add(node.name.text);
    }
    ts.forEachChild(node, aliasVisit);
  };
  aliasVisit(sourceFile);

  const requireBindingVisit = (node) => {
    if (
      ts.isVariableDeclaration(node)
      && node.initializer
      && ts.isCallExpression(node.initializer)
      && ts.isIdentifier(node.initializer.expression)
      && requireNames.has(node.initializer.expression.text)
    ) {
      const specifier = evaluate(node.initializer.arguments[0], constants);
      if (specifier.known && restricted.has(specifier.value)) {
        if (ts.isIdentifier(node.name)) capabilityBindings.add(node.name.text);
        if (ts.isObjectBindingPattern(node.name)) {
          for (const element of node.name.elements) capabilityBindings.add(element.name.getText(sourceFile));
        }
      }
    }
    ts.forEachChild(node, requireBindingVisit);
  };
  requireBindingVisit(sourceFile);

  const visit = (node) => {
    if (
      ts.isStringLiteralLike(node)
      || ts.isTemplateExpression(node)
      || ts.isBinaryExpression(node)
      || ts.isCallExpression(node)
      || ts.isIdentifier(node)
    ) {
      const evaluated = evaluate(node, constants);
      if (evaluated.known && typeof evaluated.value === "string") {
        evaluatedStrings.push({ ...evaluated, offset: node.getStart(sourceFile) });
      }
    }
    if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      const value = evaluate(node.moduleSpecifier, constants);
      if (value.known) imports.push({ value: String(value.value), offset: node.getStart(sourceFile) });
    }
    if (ts.isCallExpression(node)) {
      const dynamicImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
      const directRequire = ts.isIdentifier(node.expression) && requireNames.has(node.expression.text);
      if (dynamicImport || directRequire) {
        const value = evaluate(node.arguments[0], constants);
        if (value.known) imports.push({ value: String(value.value), offset: node.getStart(sourceFile) });
        else unresolvedImports.push({ offset: node.getStart(sourceFile) });
      }
      const called = callBinding(node.expression);
      if (called.name === "fetch" || capabilityBindings.has(called.binding)) {
        const value = evaluate(node.arguments[0], constants);
        if (value.known && typeof value.value === "string") {
          flows.push({ ...value, offset: node.arguments[0].getStart(sourceFile), sink: called.name });
        }
      }
    }
    const path = memberPath(node);
    if (path?.join(".") === "process.env.CHRONO_BOUNTY_ROOT") {
      directPrivateReads.push(node.getStart(sourceFile));
    }
    if (ts.isPropertyAssignment(node) && sinkProperties.has(propertyName(node.name))) {
      const value = evaluate(node.initializer, constants);
      if (value.known && typeof value.value === "string") {
        flows.push({ ...value, offset: node.initializer.getStart(sourceFile), sink: propertyName(node.name) });
      }
    }
    if (
      ts.isBinaryExpression(node)
      && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isPropertyAccessExpression(node.left)
      && sinkProperties.has(node.left.name.text)
    ) {
      const value = evaluate(node.right, constants);
      if (value.known && typeof value.value === "string") {
        flows.push({ ...value, offset: node.right.getStart(sourceFile), sink: node.left.name.text });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);

  return {
    constantValues: declarations
      .map((declaration) => ({
        ...evaluate(declaration.initializer, constants),
        offset: declaration.initializer.getStart(sourceFile),
      }))
      .filter(({ known: isKnown, value }) => isKnown && typeof value === "string"),
    directPrivateReads: [...new Set(directPrivateReads)],
    evaluatedStrings: [...new Map(evaluatedStrings.map((item) => [
      `${item.offset}:${item.encoded}:${item.value}`,
      item,
    ])).values()],
    flows,
    imports,
    parseErrors: (sourceFile.parseDiagnostics ?? []).map((diagnostic) => ({
      offset: diagnostic.start ?? 0,
      message: ts.flattenDiagnosticMessageText(diagnostic.messageText, " "),
    })),
    unresolvedImports,
  };
}
