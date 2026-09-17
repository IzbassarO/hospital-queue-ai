import { spawnSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";

const committed = join(process.cwd(), "src/api/generated");
const temporary = mkdtempSync(join(tmpdir(), "hqai-openapi-"));
const binary = (name) =>
  join(
    process.cwd(),
    "node_modules",
    ".bin",
    `${name}${process.platform === "win32" ? ".cmd" : ""}`,
  );

function run(label, command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.error || result.status !== 0) {
    if (result.stdout) process.stderr.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    const reason = result.error?.message ?? `exit code ${result.status}`;
    throw new Error(`${label} command failed: ${reason}`);
  }
}

function files(root, directory = root) {
  return readdirSync(directory)
    .flatMap((name) => {
      const path = join(directory, name);
      return statSync(path).isDirectory()
        ? files(root, path)
        : [relative(root, path)];
    })
    .sort();
}

try {
  run("openapi-ts generator", binary("openapi-ts"), [
    "-i",
    "../backend/openapi.json",
    "-o",
    temporary,
    "-p",
    "@hey-api/typescript",
    "--silent",
    "--no-log-file",
  ]);
  run("Prettier formatter", binary("prettier"), [
    "--config",
    ".prettierrc.json",
    "--no-editorconfig",
    "--write",
    temporary,
    "--log-level",
    "silent",
  ]);

  const expectedFiles = files(committed);
  const generatedFiles = files(temporary);
  const mismatch =
    expectedFiles.join("\n") !== generatedFiles.join("\n") ||
    generatedFiles.some(
      (name) =>
        !readFileSync(join(committed, name)).equals(
          readFileSync(join(temporary, name)),
        ),
    );
  if (mismatch) {
    console.error(
      "Generated API contract is stale. Review backend/openapi.json, then run `npm run api:generate`.",
    );
    process.exitCode = 1;
  } else {
    console.log(
      `Generated API contract: PASS (${generatedFiles.length} files current)`,
    );
  }
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Generated API contract check failed: ${message}`);
  process.exitCode = 1;
} finally {
  rmSync(temporary, { force: true, recursive: true });
}
