import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { manifestFor, packageExtension } from '../scripts/package-extension.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const EXTENSION_ROOT = resolve(__dirname, '..');

function requiredSurface(manifest) {
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.name, 'Tailord');
  assert.ok(manifest.description.length <= 132);
  assert.equal(manifest.homepage_url, 'https://github.com/sarthak22gaur/tailord');
  assert.deepEqual(manifest.permissions, ['activeTab', 'storage', 'notifications', 'alarms', 'scripting']);
  assert.deepEqual(manifest.host_permissions, [
    'http://127.0.0.1/*',
    'http://localhost/*',
    'https://www.linkedin.com/*',
  ]);
  assert.equal(manifest.action.default_popup, 'popup/popup.html');
  assert.equal(manifest.options_page, 'options/options.html');
  assert.equal(manifest.icons['128'], 'icons/icon128.png');
  assert.equal(manifest.content_scripts[0].matches[0], 'https://www.linkedin.com/jobs/*');
  assert.deepEqual(manifest.content_scripts[0].js, [
    'content/registry.js',
    'content/adapters/linkedin.js',
    'content/extract.js',
  ]);
}

test('target manifests keep Chrome and Firefox background shapes separate', () => {
  const chrome = manifestFor('chrome');
  requiredSurface(chrome);
  assert.equal(chrome.background.service_worker, 'background/service_worker.js');
  assert.equal(Object.hasOwn(chrome.background, 'scripts'), false);
  assert.equal(Object.hasOwn(chrome, 'browser_specific_settings'), false);

  const firefox = manifestFor('firefox');
  requiredSurface(firefox);
  assert.deepEqual(firefox.background.scripts, [
    'shared/browser-api.js',
    'background/service_worker.js',
  ]);
  assert.equal(Object.hasOwn(firefox.background, 'service_worker'), false);
  assert.equal(firefox.browser_specific_settings.gecko.id, 'jd-bridge@local');
});

test('source manifest is the Chrome development manifest', async () => {
  const manifest = JSON.parse(await readFile(resolve(EXTENSION_ROOT, 'manifest.json'), 'utf8'));
  assert.deepEqual(manifest, manifestFor('chrome'));
});

test('icon128 is not the old flat placeholder tile', async () => {
  const icon = await readFile(resolve(EXTENSION_ROOT, 'icons/icon128.png'));
  assert.ok(icon.length > 1000, `icon128.png is suspiciously small (${icon.length} bytes)`);
});

test('packageExtension writes generated manifests and zip artifacts', async () => {
  const distRoot = await mkdtemp(resolve(tmpdir(), 'tailord-extension-dist-'));
  const outputs = await packageExtension({ distRoot });
  assert.deepEqual(outputs.map((o) => o.target), ['chrome', 'firefox']);

  for (const target of ['chrome', 'firefox']) {
    const rootEntries = await readdir(resolve(distRoot, target));
    assert.deepEqual(rootEntries.sort(), [
      'background',
      'content',
      'icons',
      'manifest.json',
      'options',
      'popup',
      'shared',
    ]);

    const manifest = JSON.parse(
      await readFile(resolve(distRoot, target, 'manifest.json'), 'utf8'),
    );
    assert.deepEqual(manifest, manifestFor(target));

    const zip = await readFile(resolve(distRoot, `tailord-extension-${target}-0.1.0.zip`));
    assert.equal(zip.subarray(0, 4).toString('hex'), '504b0304');
    assert.ok(zip.length > 1000);
  }
});
