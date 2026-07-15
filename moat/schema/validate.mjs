import { readJson } from "../adapters/filesystem.mjs";

const SCHEMAS = {
  GuardAnnotation: "GuardAnnotation.schema.json",
  InvariantDescriptor: "InvariantDescriptor.schema.json",
  Verdict: "Verdict.schema.json",
  WaveResult: "WaveResult.schema.json",
};

const kindOf = (value) => {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (Number.isInteger(value)) return "integer";
  return typeof value;
};

const deepEqual = (left, right) => JSON.stringify(left) === JSON.stringify(right);

function typeMatches(expected, value) {
  const actual = kindOf(value);
  if (expected === "number") return actual === "number" || actual === "integer";
  if (expected === "object") return actual === "object";
  return actual === expected;
}

function validateNode(schema, value, path, errors) {
  if (typeof schema === "boolean") {
    if (!schema) errors.push({ instancePath: path, keyword: "falseSchema", message: "is disallowed" });
    return;
  }

  if (schema.const !== undefined && !deepEqual(schema.const, value)) {
    errors.push({ instancePath: path, keyword: "const", message: `must equal ${JSON.stringify(schema.const)}` });
  }

  if (schema.enum && !schema.enum.some((entry) => deepEqual(entry, value))) {
    errors.push({ instancePath: path, keyword: "enum", message: "must equal an allowed value" });
  }

  if (schema.type) {
    const expectedTypes = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!expectedTypes.some((expected) => typeMatches(expected, value))) {
      errors.push({ instancePath: path, keyword: "type", message: `must be ${expectedTypes.join(" or ")}` });
      return;
    }
  }

  if (schema.allOf) {
    for (const child of schema.allOf) validateNode(child, value, path, errors);
  }

  if (schema.anyOf) {
    const matches = schema.anyOf.some((child) => {
      const candidateErrors = [];
      validateNode(child, value, path, candidateErrors);
      return candidateErrors.length === 0;
    });
    if (!matches) errors.push({ instancePath: path, keyword: "anyOf", message: "must match at least one alternative" });
  }

  if (schema.oneOf) {
    const matches = schema.oneOf.filter((child) => {
      const candidateErrors = [];
      validateNode(child, value, path, candidateErrors);
      return candidateErrors.length === 0;
    }).length;
    if (matches !== 1) errors.push({ instancePath: path, keyword: "oneOf", message: "must match exactly one alternative" });
  }

  if (schema.if) {
    const conditionErrors = [];
    validateNode(schema.if, value, path, conditionErrors);
    if (conditionErrors.length === 0 && schema.then) validateNode(schema.then, value, path, errors);
    if (conditionErrors.length > 0 && schema.else) validateNode(schema.else, value, path, errors);
  }

  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) {
      errors.push({ instancePath: path, keyword: "minLength", message: `must contain at least ${schema.minLength} characters` });
    }
    if (schema.maxLength !== undefined && value.length > schema.maxLength) {
      errors.push({ instancePath: path, keyword: "maxLength", message: `must contain at most ${schema.maxLength} characters` });
    }
    if (schema.pattern && !new RegExp(schema.pattern, "u").test(value)) {
      errors.push({ instancePath: path, keyword: "pattern", message: `must match ${schema.pattern}` });
    }
  }

  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) {
      errors.push({ instancePath: path, keyword: "minimum", message: `must be >= ${schema.minimum}` });
    }
    if (schema.maximum !== undefined && value > schema.maximum) {
      errors.push({ instancePath: path, keyword: "maximum", message: `must be <= ${schema.maximum}` });
    }
  }

  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      errors.push({ instancePath: path, keyword: "minItems", message: `must contain at least ${schema.minItems} items` });
    }
    if (schema.maxItems !== undefined && value.length > schema.maxItems) {
      errors.push({ instancePath: path, keyword: "maxItems", message: `must contain at most ${schema.maxItems} items` });
    }
    if (schema.uniqueItems && new Set(value.map((entry) => JSON.stringify(entry))).size !== value.length) {
      errors.push({ instancePath: path, keyword: "uniqueItems", message: "must not contain duplicate items" });
    }
    if (schema.items) value.forEach((entry, index) => validateNode(schema.items, entry, `${path}/${index}`, errors));
  }

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    for (const required of schema.required ?? []) {
      if (!Object.hasOwn(value, required)) {
        errors.push({ instancePath: path, keyword: "required", message: `must include ${required}` });
      }
    }

    for (const [key, child] of Object.entries(schema.properties ?? {})) {
      if (Object.hasOwn(value, key)) validateNode(child, value[key], `${path}/${key}`, errors);
    }

    if (schema.additionalProperties === false) {
      const allowed = new Set(Object.keys(schema.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!allowed.has(key)) {
          errors.push({ instancePath: `${path}/${key}`, keyword: "additionalProperties", message: "is not allowed" });
        }
      }
    }
  }
}

export function validateInstance(schema, value) {
  const errors = [];
  validateNode(schema, value, "", errors);
  return errors;
}

export async function loadSchema(name) {
  const fileName = SCHEMAS[name];
  if (!fileName) throw new Error(`Unknown moat schema: ${name}`);
  return readJson(new URL(`../schemas/${fileName}`, import.meta.url));
}

export async function validateNamed(name, value) {
  return validateInstance(await loadSchema(name), value);
}

async function main() {
  const [name, instancePath] = process.argv.slice(2);
  if (!name || !instancePath) {
    console.error("usage: node schema/validate.mjs <schema-name> <instance.json>");
    process.exitCode = 2;
    return;
  }
  const errors = await validateNamed(name, await readJson(instancePath));
  if (errors.length) {
    console.error(JSON.stringify(errors, null, 2));
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
