import { copyFile, mkdir, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const EXTENSION_ROOT = join(__dirname, '..');
const REPO_ROOT = join(EXTENSION_ROOT, '..', '..');
const DEFAULT_DIST_ROOT = join(REPO_ROOT, 'dist', 'jd-extension');

const VERSION = '0.1.0';
const EXTENSION_NAME = 'Tailord';
const DESCRIPTION =
  'Queue LinkedIn JDs to your local Tailord bridge for evidence-backed resume tailoring.';
const HOMEPAGE_URL = 'https://github.com/sarthak22gaur/tailord';

const RUNTIME_DIRS = [
  'background',
  'content',
  'icons',
  'options',
  'popup',
  'shared',
];

const SHARED_MANIFEST = {
  manifest_version: 3,
  name: EXTENSION_NAME,
  version: VERSION,
  description: DESCRIPTION,
  homepage_url: HOMEPAGE_URL,
  permissions: ['activeTab', 'storage', 'notifications', 'alarms', 'scripting'],
  host_permissions: [
    'http://127.0.0.1/*',
    'http://localhost/*',
    'https://www.linkedin.com/*',
  ],
  action: {
    default_popup: 'popup/popup.html',
    default_icon: {
      16: 'icons/icon16.png',
      48: 'icons/icon48.png',
      128: 'icons/icon128.png',
    },
  },
  content_scripts: [
    {
      matches: ['https://www.linkedin.com/jobs/*'],
      js: [
        'content/registry.js',
        'content/adapters/linkedin.js',
        'content/extract.js',
      ],
      run_at: 'document_idle',
    },
  ],
  options_page: 'options/options.html',
  icons: {
    16: 'icons/icon16.png',
    48: 'icons/icon48.png',
    128: 'icons/icon128.png',
  },
};

function sortedJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function manifestFor(target) {
  if (target === 'chrome') {
    return {
      ...SHARED_MANIFEST,
      background: {
        service_worker: 'background/service_worker.js',
      },
    };
  }

  if (target === 'firefox') {
    return {
      ...SHARED_MANIFEST,
      background: {
        scripts: ['shared/browser-api.js', 'background/service_worker.js'],
      },
      browser_specific_settings: {
        gecko: {
          id: 'jd-bridge@local',
          strict_min_version: '121.0',
        },
      },
    };
  }

  throw new Error(`unknown extension target: ${target}`);
}

async function copyTree(src, dest) {
  const entries = await readdir(src, { withFileTypes: true });
  await mkdir(dest, { recursive: true });
  for (const entry of entries) {
    const srcPath = join(src, entry.name);
    const destPath = join(dest, entry.name);
    if (entry.isDirectory()) {
      await copyTree(srcPath, destPath);
    } else if (entry.isFile()) {
      await copyFile(srcPath, destPath);
    }
  }
}

async function collectFiles(root, dir = root) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await collectFiles(root, path));
    } else if (entry.isFile()) {
      files.push({
        absPath: path,
        relPath: relative(root, path).split(sep).join('/'),
      });
    }
  }
  return files;
}

let crcTable;
function crc32(buf) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = (crcTable[(crc ^ b) & 0xff] ^ (crc >>> 8)) >>> 0;
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(value) {
  const buf = Buffer.alloc(2);
  buf.writeUInt16LE(value, 0);
  return buf;
}

function u32(value) {
  const buf = Buffer.alloc(4);
  buf.writeUInt32LE(value >>> 0, 0);
  return buf;
}

async function writeZip(sourceDir, outPath) {
  const files = await collectFiles(sourceDir);
  const localParts = [];
  const centralParts = [];
  let offset = 0;

  for (const file of files) {
    const data = await readFile(file.absPath);
    const name = Buffer.from(file.relPath, 'utf8');
    const crc = crc32(data);
    const localHeader = Buffer.concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(data.length),
      u32(data.length),
      u16(name.length),
      u16(0),
      name,
    ]);
    localParts.push(localHeader, data);

    centralParts.push(Buffer.concat([
      u32(0x02014b50),
      u16(20),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(data.length),
      u32(data.length),
      u16(name.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      name,
    ]));

    offset += localHeader.length + data.length;
  }

  const central = Buffer.concat(centralParts);
  const local = Buffer.concat(localParts);
  const eocd = Buffer.concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(central.length),
    u32(local.length),
    u16(0),
  ]);

  await writeFile(outPath, Buffer.concat([local, central, eocd]));
}

export async function packageExtension({ distRoot = DEFAULT_DIST_ROOT } = {}) {
  await mkdir(distRoot, { recursive: true });
  const outputs = [];

  for (const target of ['chrome', 'firefox']) {
    const packageDir = join(distRoot, target);
    await rm(packageDir, { recursive: true, force: true });
    await mkdir(packageDir, { recursive: true });

    for (const dir of RUNTIME_DIRS) {
      await copyTree(join(EXTENSION_ROOT, dir), join(packageDir, dir));
    }

    await writeFile(join(packageDir, 'manifest.json'), sortedJson(manifestFor(target)), 'utf8');

    const zipPath = join(distRoot, `tailord-extension-${target}-${VERSION}.zip`);
    await rm(zipPath, { force: true });
    await writeZip(packageDir, zipPath);
    const zipStat = await stat(zipPath);
    outputs.push({ target, packageDir, zipPath, zipBytes: zipStat.size });
  }

  return outputs;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const outputs = await packageExtension();
  for (const output of outputs) {
    console.log(`${output.target}: ${output.packageDir}`);
    console.log(`${output.target}: ${output.zipPath} (${output.zipBytes} bytes)`);
  }
}
