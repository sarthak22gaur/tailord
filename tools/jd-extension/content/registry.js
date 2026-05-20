// Lightweight adapter registry. Each adapter is:
//   { name, match(url): boolean, extract(): { jd, title?, company?, url? } }
// Adapter files (loaded after this one) call window.__jdRegister(adapter).
(() => {
  if (!window.__jdRegistry) window.__jdRegistry = [];
  window.__jdRegister = (a) => {
    const idx = window.__jdRegistry.findIndex((existing) => existing.name === a.name);
    if (idx >= 0) window.__jdRegistry[idx] = a;
    else window.__jdRegistry.push(a);
  };
  window.__jdResolve  = (url) => window.__jdRegistry.find((a) => a.match(url));
})();
