const $ = (id) => document.getElementById(id);
const { DEFAULT_BRIDGE_URL, fetchWithTimeout, normalizeBridgeUrl, storageGet, storageSet } = jdBrowser;

function setStatus(text, kind) {
  const el = $('status');
  el.textContent = text;
  el.className = kind || '';
}

async function load() {
  const { config } = await storageGet('config');
  $('bridgeUrl').value = config?.bridgeUrl || DEFAULT_BRIDGE_URL;
  $('bridgeToken').value = config?.bridgeToken || '';
}

$('save').addEventListener('click', async () => {
  let bridgeUrl;
  try {
    bridgeUrl = normalizeBridgeUrl($('bridgeUrl').value);
  } catch (e) {
    setStatus(e.message, 'err');
    return;
  }
  await storageSet({
    config: {
      bridgeUrl,
      bridgeToken: $('bridgeToken').value.trim(),
    },
  });
  setStatus('saved.', 'ok');
});

$('test').addEventListener('click', async () => {
  let base;
  try {
    base = normalizeBridgeUrl($('bridgeUrl').value);
  } catch (e) {
    setStatus(e.message, 'err');
    return;
  }
  setStatus('testing…');
  try {
    const res = await fetchWithTimeout(base + '/health', {
      headers: { 'X-Bridge-Token': $('bridgeToken').value.trim() },
    });
    if (!res.ok) return setStatus(`failed: HTTP ${res.status}`, 'err');
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      return setStatus(`failed: non-JSON response (${text.slice(0, 80)})`, 'err');
    }
    const authRes = await fetchWithTimeout(base + '/jobs', {
      headers: { 'X-Bridge-Token': $('bridgeToken').value.trim() },
    });
    if (authRes.status === 401) return setStatus('reachable, but bridge token was rejected', 'err');
    if (!authRes.ok) return setStatus(`reachable, but /jobs failed: HTTP ${authRes.status}`, 'err');
    setStatus(`OK — concurrency=${data.concurrency}, running=${data.running}, pending=${data.pendingDepth}`, 'ok');
  } catch (e) {
    setStatus(`unreachable: ${e.message}`, 'err');
  }
});

load();
