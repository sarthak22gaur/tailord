// Bridge between the popup/service-worker and the page-side adapters.
if (!window.__jdExtractListenerInstalled) {
  window.__jdExtractListenerInstalled = true;
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'extract-jd') return;
    try {
      const adapter = window.__jdResolve(location.href);
      if (!adapter) {
        sendResponse({ error: `No adapter registered for ${location.host}${location.pathname}` });
        return;
      }
      const data = adapter.extract();
      if (!data.jd || data.jd.length < 50) {
        const diag = typeof adapter.diagnostics === 'function' ? adapter.diagnostics() : null;
        if (diag) console.warn('[jd-bridge] extraction failed', diag);
        const diagText = diag ? `\n\nDebug:\n${JSON.stringify(diag, null, 2)}` : '';
        sendResponse({
          error: `LinkedIn job description not found (got ${data.jd?.length ?? 0} chars). Open the job detail pane or /jobs/view page, wait for the description to load, then retry. If it still fails, LinkedIn likely changed the job-detail DOM selectors.${diagText}`,
        });
        return;
      }
      sendResponse({ ok: true, data: { ...data, source: adapter.name } });
    } catch (e) {
      sendResponse({ error: e?.message ?? String(e) });
    }
  });
}
