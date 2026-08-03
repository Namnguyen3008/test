import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const localPython = resolve(repo, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const python = existsSync(localPython) ? localPython : "python";
const child = spawn(python, ["-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "8000"], {
  stdio: "inherit",
  cwd: repo,
  env: { ...process.env, APP_ENV: "test", APP_DATA_MODE: "development" },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 0));
