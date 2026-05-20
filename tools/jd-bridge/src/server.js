import Fastify from 'fastify';
import cors from '@fastify/cors';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { registerRoutes } from './routes.js';
import { bootstrap, shutdownQueue } from './queue.js';
import { corsOrigin, requireBridgeTokenConfigured } from './security.js';
import { loadConfig } from './config.js';

requireBridgeTokenConfigured();
const cfg = loadConfig();

function checkVault(cfg) {
  const issues = [];
  if (!existsSync(cfg.vault)) {
    issues.push(`vault directory missing: ${cfg.vault}`);
  }
  if (!existsSync(resolve(cfg.vault, 'data/master.yaml'))) {
    issues.push(`vault is missing data/master.yaml (resolved vault: ${cfg.vault})`);
  }
  // Bridge spawns `claude -p` with cwd=frameworkRoot; the Claude CLI
  // auto-discovers skills from .claude/skills/<name>/SKILL.md, which
  // `tailord sync-skills` generates from src/tailord/skills/.
  if (!existsSync(resolve(cfg.frameworkRoot, '.claude/skills/resume-tailoring/SKILL.md'))) {
    issues.push(
      `framework dir is missing .claude/skills/ (resolved framework: ${cfg.frameworkRoot}). ` +
      `Run \`tailord sync-skills\` from the framework root, or git pull to a commit that includes the generated dirs.`,
    );
  }
  return issues;
}

const vaultIssues = checkVault(cfg);
if (vaultIssues.length) {
  console.error('Bridge cannot start — vault/framework misconfigured:');
  for (const msg of vaultIssues) console.error(`  • ${msg}`);
  console.error(`Config source: ${cfg.source}`);
  console.error(
    'Set RESUME_VAULT in your bridge .env, or create a .resumerc.yaml. ' +
    'Run `tailord setup-bridge` to regenerate bridge config.',
  );
  process.exit(1);
}

const app = Fastify({
  logger: { level: process.env.LOG_LEVEL || 'info' },
  bodyLimit: 5 * 1024 * 1024,
});

await app.register(cors, {
  origin: corsOrigin,
  methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'X-Bridge-Token'],
});

await registerRoutes(app);

const port = cfg.bridge.port;
const host = '127.0.0.1';

const { resumedPending, failedOrphans } = bootstrap();
app.log.info(
  { resumedPending, failedOrphans, vault: cfg.vault, source: cfg.source },
  'queue bootstrapped',
);

try {
  await app.listen({ port, host });
  app.log.info(`jd-bridge listening on http://${host}:${port}`);
} catch (err) {
  app.log.error(err);
  process.exit(1);
}

let shuttingDown = false;
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    if (shuttingDown) process.exit(1);
    shuttingDown = true;
    app.log.info(`received ${sig}, shutting down`);
    await shutdownQueue();
    await app.close();
    process.exit(0);
  });
}
