# M12 Security Review — Web UI & Live Dashboard

**Date:** 2026-07-20 · **Scope:** the React/TypeScript SPA — auth/token handling, the SSE transport,
rendering of agent-produced content, CSP, and the frontend supply chain · **Verdict: PASS**

> A web UI adds a new browser-side attack surface (XSS, token theft, CSRF, and hostile *agent output*
> reaching the DOM). The SPA is built so agent/run content is always data, the token never leaves the
> header, and inline script/style is impossible.

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Agent output is text/code, never markup | All run/agent content (timeline detail, diffs, plan titles, memory content) is rendered through React text nodes; no `dangerouslySetInnerHTML` anywhere | `DiffViewer` / `Timeline` render text nodes; grep: no `dangerouslySetInnerHTML` in `src/` |
| No inline script or style | Strict CSP `script-src 'self'; style-src 'self'` with no `unsafe-inline`; Vite bundles all JS/CSS from `'self'` | `index.html` CSP meta; production build emits external assets only |
| JWT never in the URL | The token rides the `Authorization` header on every request, including SSE — which is consumed via a **fetch stream** (not `EventSource`, which cannot set headers) | `client.ts` `streamRunEvents`; no token in any query string |
| Token at rest is scoped and revocable | Held in `localStorage` under one key; `logout` clears it; a 401 surfaces as an error, not a silent retry loop | `AuthContext` / `client.ts` |
| SSE authorizes per run | The stream endpoint is owner-checked server-side (M6); a non-owner sees the run as not found | backend `/runs/{id}/events` owner guard (carried) |
| Same-origin API, no CORS surface | The dev server proxies `/api` to the backend; in production the SPA is served behind the same gateway, so no cross-origin credentials flow | `vite.config.ts` proxy; `connect-src 'self'` |
| Frontend supply chain is gated | CI runs `npm ci` (lockfile-pinned), typecheck, lint, unit tests, build, and `npm audit` (high+) | `.github/workflows/frontend.yml` |
| One tested projection of run state | The dashboard and replay both fold events through one pure reducer; a divergence would fail its unit tests | `tests/events.test.ts` (purity + fold) |

## 2. Design decisions with security weight

- **The reducer is pure and the only interpreter of run events.** Live and replayed views cannot
  diverge, and the reducer never executes or evaluates event content — it only classifies it into
  typed, escaped timeline entries.
- **SSE over fetch, not EventSource.** `EventSource` cannot carry an `Authorization` header, which
  tempts putting the token in the URL (where it lands in logs and history). The fetch-stream reader
  keeps the token in the header and the URL clean.
- **CSP is strict by construction.** Because Vite emits external bundles and the app uses no inline
  handlers, `script-src 'self'` with no `unsafe-inline` holds without workarounds; the production
  gateway adds a per-response nonce on top.
- **Strict TypeScript is a safety net.** `strict`, `noUncheckedIndexedAccess`, and
  `exactOptionalPropertyTypes` catch a class of undefined-access bugs before they reach the browser.

## 3. Accepted findings / deliberate scoping

- **Playwright e2e + demo GIFs run where the stack is live.** The unit gate (typecheck/lint/vitest/
  build) is green locally and in CI; the full-flow e2e specs and screen recordings require the running
  backend (Docker) and are executed in CI / on a live environment, not in this build environment. The
  e2e job is present but gated (`if: false`) until the fixture-LLM API service is wired into CI.
- **Token storage is `localStorage`.** Acceptable for a self-hosted, single-origin SPA with
  short-lived access tokens + rotating refresh (M1); moving to an httpOnly cookie + CSRF token is a
  hardening option if the deployment model changes.
- **Diff rendering is a lightweight colorizer, not Monaco.** It renders diffs as escaped text with
  add/remove coloring; a Monaco-based editor view is a UX enhancement, not a security requirement.

## 4. Attack-shaped / robustness checks

The event reducer is unit-tested for purity (no input mutation) and correct folding of a full run
(status, plan, commits, tests, tokens/cost, PR); agent content flows only through escaped React text
nodes; the token is asserted (by construction) to travel in the header, not the URL; and CI fails on a
high-severity dependency advisory.

## 5. Carry-forward

M13+ can wire the fixture-LLM backend service into CI to un-gate the Playwright e2e job, record the
demo GIFs from a live run, and optionally add a Monaco diff/editor surface behind the same
text-only-output guarantee.
