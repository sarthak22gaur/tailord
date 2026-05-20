(() => {
  const DETAIL_ROOT_SELECTORS = [
    '.jobs-search__job-details--container',
    '.jobs-search__job-details',
    '.jobs-details__main-content',
    '.scaffold-layout__detail',
    '.job-view-layout',
  ];

  const JD_SELECTORS = [
    '.jobs-description__content .jobs-box__html-content',
    '.jobs-description__content .jobs-description-content__text',
    '.jobs-description__content',
    '.jobs-description-content__text',
    '.jobs-box__html-content',
    'article.jobs-description__container',
    '.jobs-description',
    '#job-details',
  ];

  const TITLE_SELECTORS = [
    '.job-details-jobs-unified-top-card__job-title',
    '.jobs-unified-top-card__job-title',
    '[class*="top-card"] h1',
    '[class*="top-card"] h2',
    'h1.t-24',
    'h1',
    'h2',
  ];

  const COMPANY_SELECTORS = [
    '.job-details-jobs-unified-top-card__company-name a',
    '.job-details-jobs-unified-top-card__company-name',
    '.jobs-unified-top-card__company-name a',
    '.jobs-unified-top-card__company-name',
    '[class*="top-card"] [class*="company-name"] a',
    '[class*="top-card"] [class*="company-name"]',
    '[class*="company-name"] a',
    '[class*="company-name"]',
  ];

  const BLOCK_SELECTORS =
    'article, section, div, p, [class*="jobs-description"], [class*="job-details"], [class*="description"]';

  function textOf(el) {
    if (!el) return '';
    if (el.nodeType === Node.TEXT_NODE) {
      return isVisibleElement(el.parentElement) ? (el.textContent || '').trim() : '';
    }
    if (el.nodeType === Node.ELEMENT_NODE && !isVisibleElement(el)) return '';
    if ('innerText' in el) return (el.innerText || '').trim();
    return isVisibleElement(el) ? (el.textContent || '').trim() : '';
  }

  function pushUnique(list, el) {
    if (el && !list.includes(el)) list.push(el);
  }

  function isVisibleElement(el) {
    if (!el || el === document) return true;
    if (el.nodeType !== Node.ELEMENT_NODE) return isVisibleElement(el.parentElement);

    for (let cur = el; cur && cur !== document.documentElement; cur = cur.parentElement) {
      if (cur.hidden || cur.getAttribute('aria-hidden') === 'true') return false;
      const style = window.getComputedStyle(cur);
      if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') {
        return false;
      }
    }

    return [...el.getClientRects()].some((rect) => rect.width > 1 && rect.height > 1);
  }

  function visibleDetailScore(el) {
    if (!isVisibleElement(el)) return -Infinity;
    const text = textOf(el);
    if (text.length < 100 || looksLikeJobList(el)) return -Infinity;

    const rect = el.getBoundingClientRect();
    const isRightPane = rect.left > window.innerWidth * 0.25 && rect.width > window.innerWidth * 0.25;
    const hasActions = /\bApply\b/i.test(text) || /\bSave\b/i.test(text);
    const jd = extractJd(el);

    return (
      (jd.length >= 500 ? 20 : 0) +
      (hasJdAnchor(text) ? 12 : 0) +
      (extractTitle(el) ? 8 : 0) +
      (extractCompany(el) ? 3 : 0) +
      (hasActions ? 3 : 0) +
      (isRightPane ? 5 : 0) -
      listingLinkCount(el) * 5 -
      text.length / 10_000
    );
  }

  // Detect the right-pane container in LinkedIn's split-view layouts
  // (/jobs/search-results, /jobs/collections). On dedicated job pages
  // (/jobs/view/<id>) the whole document IS the detail. Newer LinkedIn
  // variants ship hashed CSS-module class names, so when the known selectors
  // miss we derive a semantic detail root from the description section instead
  // of letting the left-hand collection list bleed into the JD.
  function detailRoot() {
    const candidates = [];
    for (const sel of DETAIL_ROOT_SELECTORS) {
      for (const el of document.querySelectorAll(sel)) pushUnique(candidates, el);
    }
    const bestKnown = candidates
      .map((el) => ({ el, score: visibleDetailScore(el) }))
      .sort((a, b) => b.score - a.score)[0];
    if (bestKnown && bestKnown.score > -Infinity) {
      return bestKnown.el;
    }

    const main = document.querySelector('main') || document;
    return findDetailRootByContent(main) || main;
  }

  function firstSubstantial(root, selectors, minLen = 1, reject = null) {
    for (const sel of selectors) {
      const matches = [
        ...(root.matches?.(sel) ? [root] : []),
        ...root.querySelectorAll(sel),
      ];
      for (const el of matches) {
        const t = textOf(el);
        if (t && reject?.(t, el)) continue;
        if (t && t.length >= minLen) return t;
      }
    }
    return '';
  }

  // Anchor-walk fallback: LinkedIn's hashed-class variants strip every helpful
  // class, but the JD body still carries an "About the job" / "Job description"
  // heading. Find the text node, walk up to the smallest substantial ancestor.
  const JD_ANCHORS = [
    'About the job',
    'About this role',
    'About the role',
    'About the position',
    'Job description',
    'Job Description',
  ];

  function hasJdAnchor(text) {
    return JD_ANCHORS.some((a) => text.includes(a));
  }

  function isNonJobTitle(text) {
    const t = text.replace(/\s+/g, ' ').trim();
    if (!t) return true;
    const lower = t.toLowerCase();
    if (JD_ANCHORS.some((a) => lower === a.toLowerCase())) return true;
    return (
      /^top job picks\b/i.test(t) ||
      /^recommended jobs\b/i.test(t) ||
      /^search results\b/i.test(t) ||
      /^job search\b/i.test(t) ||
      /^jobs based on\b/i.test(t) ||
      /^how your profile\b/i.test(t) ||
      /^\d+\s+results$/i.test(t)
    );
  }

  function listingLinkCount(el) {
    return el?.querySelectorAll?.(
      'a[href*="/jobs/view/"], a[href*="/jobs/collections/"], [data-job-id], [data-occludable-job-id]'
    ).length || 0;
  }

  function looksLikeJobList(el) {
    const text = textOf(el);
    const links = listingLinkCount(el);
    if (links >= 3) return true;
    return (
      /\b\d+\s+results\b/i.test(text) &&
      /\b(Promoted|Viewed|Top job picks|Recommended jobs)\b/i.test(text)
    );
  }

  function anchorElements(root) {
    const found = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (hasJdAnchor(textOf(node))) pushUnique(found, node.parentElement);
    }
    return found;
  }

  function jdSeedElements(root) {
    const seeds = [];
    for (const sel of JD_SELECTORS) {
      if (root.matches?.(sel)) pushUnique(seeds, root);
      for (const el of root.querySelectorAll(sel)) pushUnique(seeds, el);
    }
    for (const el of anchorElements(root)) pushUnique(seeds, el);
    return seeds;
  }

  function findDetailRootByContent(root) {
    let best = null;
    let bestScore = -Infinity;

    for (const seed of jdSeedElements(root)) {
      for (let el = seed; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
        const text = textOf(el);
        if (text.length < 500 || text.length > 30_000) continue;
        if (looksLikeJobList(el)) continue;

        const title = extractTitle(el);
        const company = extractCompany(el);
        const links = listingLinkCount(el);
        const hasActions = /\bApply\b/i.test(text) || /\bSave\b/i.test(text);
        const score =
          (hasJdAnchor(text) ? 12 : 0) +
          (title ? 8 : 0) +
          (company ? 3 : 0) +
          (hasActions ? 2 : 0) -
          links * 5 -
          text.length / 10_000;

        if (score > bestScore) {
          best = el;
          bestScore = score;
        }

        // Walking up from the description seed means the first ancestor with
        // both JD and top-card context is the smallest useful detail pane.
        if (title && hasJdAnchor(text)) return el;
      }
    }

    return best;
  }

  function findJdByAnchor(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = textOf(node);
      if (!hasJdAnchor(text)) continue;
      let el = node.parentElement;
      while (el && el !== root && el !== document.body) {
        const t = textOf(el);
        if (t.length >= 1000 && t.length <= 30_000 && !looksLikeJobList(el)) return t;
        el = el.parentElement;
      }
    }
    return '';
  }

  // Fallback: largest text-rich block under the detail root. Includes plain
  // <div>/<section>/<article>/<p> since the hashed-class variants put the JD
  // in anonymous divs. Skips child elements that occupy ~all of the root (i.e.,
  // sole wrappers) and list-like blocks so search panes don't bleed in.
  function largestBlock(root) {
    const rootBytes = textOf(root).length;
    const ceiling = rootBytes > 0 ? rootBytes * 0.9 : Infinity;
    const candidates = [
      ...(root.matches?.(BLOCK_SELECTORS) ? [root] : []),
      ...root.querySelectorAll(BLOCK_SELECTORS),
    ];
    let best = '';
    for (const c of candidates) {
      const t = textOf(c);
      if (t.length < 500 || t.length > 30_000) continue;
      if (c !== root && root !== document && t.length > ceiling) continue;
      if (looksLikeJobList(c)) continue;
      if (t.length > best.length) best = t;
    }
    return best.length >= 500 ? best : '';
  }

  function extractJd(root) {
    return (
      firstSubstantial(root, JD_SELECTORS, 100) ||
      findJdByAnchor(root) ||
      largestBlock(root)
    );
  }

  function extractTitle(root) {
    return firstSubstantial(root, TITLE_SELECTORS, 1, isNonJobTitle);
  }

  function extractCompany(root) {
    return firstSubstantial(root, COMPANY_SELECTORS);
  }

  // Last-resort fallback for the hashed-class variant: LinkedIn always sets
  // <title> to something like "(99+) Company hiring Title in Location | LinkedIn"
  // or "(99+) Title | Company | LinkedIn". Parse both shapes.
  function fromDocumentTitle() {
    const raw = (document.title || '').trim();
    if (!raw) return null;
    const stripped = raw
      .replace(/^\(\d+\+?\)\s*/, '')      // drop "(99+) " inbox counter
      .replace(/\s*\|\s*LinkedIn\s*$/, '') // drop trailing " | LinkedIn"
      .trim();
    if (!stripped) return null;
    if (isNonJobTitle(stripped)) return null;

    const hiring = stripped.match(/^(.+?)\s+hiring\s+(.+?)(?:\s+in\s+[^|]+)?$/i);
    if (hiring) {
      return { company: hiring[1].trim(), title: hiring[2].trim() };
    }

    const parts = stripped.split(/\s*\|\s*/);
    if (parts.length >= 2) {
      const title = parts[0].trim();
      if (isNonJobTitle(title)) return null;
      return { title, company: parts[1].trim() };
    }

    return { title: stripped, company: '' };
  }

  function describe(el) {
    if (!el || el === document) return el === document ? 'document' : null;
    const cls = (el.className || '').toString().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    return cls ? `${el.tagName.toLowerCase()}.${cls}` : el.tagName.toLowerCase();
  }

  // Built on failure so the popup error and the page console can both surface
  // what the adapter tried, what matched, and which candidates were available.
  function collectDiagnostics() {
    const root = detailRoot();
    const jdProbe = JD_SELECTORS.map((sel) => {
      const el = root.querySelector(sel);
      return { sel, bytes: el ? textOf(el).length : null };
    });
    const blocks = [...root.querySelectorAll(BLOCK_SELECTORS)]
      .map((el) => ({
        sel: describe(el),
        bytes: textOf(el).length,
        listingLinks: listingLinkCount(el),
      }))
      .filter((x) => x.bytes >= 500 && x.bytes <= 30_000)
      .sort((a, b) => b.bytes - a.bytes)
      .slice(0, 8);
    const anchorHits = JD_ANCHORS.filter((a) => textOf(root).includes(a));
    const titleProbe = TITLE_SELECTORS.map((sel) => {
      const el = root.querySelector(sel);
      return { sel, text: el ? textOf(el).slice(0, 80) : null };
    });

    return {
      url: location.href,
      documentTitle: document.title,
      detailRoot: describe(root),
      listingLinksInRoot: listingLinkCount(root),
      anchorHits,
      jdSelectors: jdProbe,
      largestBlocks: blocks,
      titleSelectors: titleProbe,
      fromDocumentTitle: fromDocumentTitle(),
    };
  }

  const adapter = {
    name: 'linkedin',
    match: (url) => /^https:\/\/www\.linkedin\.com\/jobs\//.test(url),
    diagnostics: collectDiagnostics,
    extract: () => {
      const root = detailRoot();
      // On /jobs/collections pages, document.title can describe the collection
      // rather than the selected job, so prefer the visible detail-pane DOM
      // once a precise root has been found.
      const docTitle = fromDocumentTitle();
      const title = extractTitle(root) || docTitle?.title;
      const company = extractCompany(root) || docTitle?.company;
      return {
        jd: extractJd(root),
        title,
        company,
        url: location.href,
      };
    },
  };

  window.__jdRegister(adapter);
})();
