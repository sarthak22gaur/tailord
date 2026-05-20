# Chrome Web Store Submission Notes

Use this page as the copy/paste source for the first unlisted Chrome Web Store
submission.

## Listing Copy

Short description:

> Queue LinkedIn job descriptions to your local Tailord bridge for evidence-backed resume tailoring.

Detailed description:

> Tailord is a local companion extension for evidence-backed resume tailoring.
> From a LinkedIn job page, click the extension to send the visible job
> description to the Tailord bridge running on your own machine.
>
> Tailord evaluates the role against your local resume vault, then lets you
> generate a tailored resume and optional cover letter from reviewed evidence
> instead of starting from a generic prompt.
>
> The extension talks to `http://127.0.0.1` or `http://localhost`. Job
> descriptions are sent to your local bridge, and the bridge uses the LLM
> provider configured on your machine to perform evaluation and generation.
>
> Tailord is open source: https://github.com/sarthak22gaur/tailord

Privacy policy URL:

> https://github.com/sarthak22gaur/tailord/blob/main/docs/privacy.md

If GitHub Pages is enabled for the repository later, prefer the rendered Pages
URL for the privacy policy.

Homepage URL:

> https://github.com/sarthak22gaur/tailord

## Assets

- 128x128 icon: `tools/jd-extension/icons/icon128.png`
- Screenshot: `docs/assets/chrome-web-store/screenshot-popup-evaluation.png`
- Screenshot source: `docs/assets/chrome-web-store/screenshot-popup-evaluation.svg`
- Optional 440x280 small tile: skipped for the first unlisted submission.

The screenshot uses sample job data and shows the expected popup workflow after
the local bridge is running.

## Notes To Reviewer

Tailord is a local companion extension. It requires the user to run a local
Tailord bridge on `127.0.0.1` before job evaluation and generation can work.

Expected reviewer behavior without the bridge:

- The extension popup may show "Bridge unreachable".
- The Settings page "Test connection" may fail until a local bridge is running.
- This is the expected unauthenticated/offline state, not a hosted-service
  outage.

To test the full workflow:

1. Install the extension.
2. Install Tailord from the GitHub repository.
3. Run `tailord init <vault>`, then `tailord setup-bridge`.
4. Start the bridge with `tailord serve`.
5. Open extension Settings, paste the local bridge token, and click
   "Test connection".
6. Open a LinkedIn job page and click "Queue job".

## Permission Justifications

`activeTab`: read the job description from the LinkedIn tab the user is viewing
when they click "Queue job".

`storage`: persist the local bridge URL and per-install bridge token between
popup sessions.

`notifications`: notify the user when a queued job finishes evaluating or
generating.

`alarms`: poll the local bridge for job status about every 30 seconds. The
bridge runs on the user's machine, so the extension cannot use hosted push
events.

`scripting`: inject the job-description extraction adapter into LinkedIn tabs
that were opened before the extension was installed or reloaded.

`https://www.linkedin.com/*`: read the visible job description text the user is
already viewing.

`http://127.0.0.1/*` and `http://localhost/*`: send the job description to the
user's locally running Tailord bridge. The extension makes no calls to a hosted
Tailord backend.

## Pre-Submission Checklist

1. Run `node tools/jd-extension/scripts/make-icons.mjs`.
2. Run `node --test tools/jd-extension/test/package-extension.test.mjs`.
3. Run `node tools/jd-extension/scripts/package-extension.mjs`.
4. Load `dist/jd-extension/chrome/` unpacked in Chrome and confirm there are no
   manifest warnings.
5. Confirm popup and Settings behave gracefully when the bridge is not running.
6. Confirm Settings "Test connection" succeeds when the bridge is running with a
   valid token.
7. Upload `dist/jd-extension/tailord-extension-chrome-0.1.0.zip`.
8. Submit as unlisted first.
