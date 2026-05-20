// Config discovery for the bridge — mirrors src/tailord/config.py.
//
// Resolution order: RESUME_VAULT env var → .resumerc.yaml in CWD or any
// ancestor → $XDG_CONFIG_HOME/tailord/config.yaml → CWD as the vault.
// Env always wins over file so a one-off override doesn't require an edit.

import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, isAbsolute, resolve } from 'node:path';
import YAML from 'yaml';

const CONFIG_FILENAME = '.resumerc.yaml';

function xdgConfigHome() {
  return process.env.XDG_CONFIG_HOME || resolve(homedir(), '.config');
}

function ancestors(start) {
  const out = [start];
  let cur = start;
  while (dirname(cur) !== cur) {
    cur = dirname(cur);
    out.push(cur);
  }
  return out;
}

function readYaml(path) {
  try {
    return YAML.parse(readFileSync(path, 'utf8')) || {};
  } catch (_) {
    return {};
  }
}

function discoverConfigFile() {
  for (const parent of ancestors(resolve(process.cwd()))) {
    const candidate = resolve(parent, CONFIG_FILENAME);
    if (existsSync(candidate)) return { path: candidate, data: readYaml(candidate) };
  }
  const userCfg = resolve(xdgConfigHome(), 'tailord', 'config.yaml');
  if (existsSync(userCfg)) return { path: userCfg, data: readYaml(userCfg) };
  return null;
}

function expand(p) {
  if (!p) return null;
  if (p.startsWith('~')) return resolve(homedir(), p.slice(1).replace(/^[\/\\]/, ''));
  return isAbsolute(p) ? p : resolve(process.cwd(), p);
}

let cached = null;

export function loadConfig() {
  if (cached) return cached;

  const fileFound = discoverConfigFile();
  const fileData = fileFound?.data ?? {};

  const envVault = process.env.RESUME_VAULT;
  const vault = expand(envVault) || expand(fileData.vault) || process.cwd();

  // RESUME_FRAMEWORK lets the user point at a separate framework dir when
  // their vault is split off. Defaults to vault for the single-repo case.
  const frameworkRoot = expand(process.env.RESUME_FRAMEWORK) || vault;

  const port = Number(
    process.env.BRIDGE_PORT ?? fileData?.bridge?.port ?? 8787,
  );

  const modelRunner = process.env.MODEL_RUNNER || fileData.model_runner || 'claude_cli';

  // Bridge state lives in the vault, not the framework checkout. No env-var
  // override on purpose — putting state outside the vault was the bug that
  // motivated the move.
  const dbPath = resolve(vault, '.tailord/jobs.db');

  cached = {
    vault,
    frameworkRoot,
    dbPath,
    bridge: { port },
    modelRunner,
    configFile: fileFound?.path ?? null,
    source: envVault
      ? 'env:RESUME_VAULT'
      : fileFound
        ? fileFound.path
        : 'defaults',
  };
  return cached;
}
