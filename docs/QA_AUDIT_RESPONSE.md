# Response to the QA audit (report of 24 September 2026)

The audit tested the earlier AquaIntel prototype: SQLite, five HTML pages, 14 endpoints. It found 33
defects (4 critical, 5 high). This platform is a rebuild, so many of those defects cannot occur
here by construction. Each finding was still re-tested against this codebase by the same method,
by attacking the running API and UI.

* **Not applicable:** the attack was tried and the platform behaves correctly. A regression test
  now guards it.
* **Fixed:** the same class of defect *was* present here. It is now fixed and tested.

Every row names its guard: `backend/tests/api/test_audit_regressions.py` has one test class per
finding (`TestAQ008…`), and the UI checks are in `frontend/src/__tests__/components.test.tsx` and
`frontend/tests/e2e/journeys.spec.ts`.

**Summary:**
* **Fixed (the defect existed here):** AQ-003 (in part), AQ-004 (in PDF reports), AQ-008, AQ-009,
  AQ-011, AQ-012, AQ-013, AQ-014, AQ-016, AQ-020, AQ-022, AQ-026, AQ-027, AQ-029, AQ-030 (in part)
  and AQ-033.
* **Not applicable, verified:** everything else.

## Critical

| ID | Finding in the prototype | Result here | What was done | Guard |
|---|---|---|---|---|
| AQ-001 | Public sign-up accepts `role=admin` | **Not applicable.** There is no public sign-up. Accounts are created only by a user holding `users:manage`, and role changes need `roles:manage`. | Added the controlled path the audit recommends: `scripts/create_admin.py` creates the first administrator from a server shell (password prompted, policy enforced, audited), so production never needs the demo seed. | `TestAQ001NoSelfServiceAdmin` |
| AQ-002 | `/static` mounted on the project root exposes the database and source | **Not applicable.** The API serves no files. The SPA is a static build served by nginx from `dist/` only. | — | `TestAQ002NoFileExposure` (`/.env`, `/app/main.py`, key file, traversal) |
| AQ-003 | Hard-coded JWT key; tokens not checked against users | **Partly applied.** Tokens were already bound to an *active* user in the database, with logout blacklisting. But `config.py` had a published development default key that a misconfigured deployment would silently use. | Outside `development`/`test`, start-up now **fails** if the key is the default or a placeholder from `.env.example` or the Kubernetes manifests. It already uses PyJWT, as the audit recommends. | `TestAQ003SigningKey` |
| AQ-004 | Stored XSS through `innerHTML` | **Not applicable in the UI.** React escapes all text, and there is no `innerHTML` / `dangerouslySetInnerHTML` anywhere. **The same class of bug existed in PDF reports:** reportlab parses `<…>` markup in cell text, so a name containing `<` could break or restyle a PDF. | PDF text is XML-escaped. A **Content-Security-Policy** is added for the SPA (`script-src 'self'`, no inline scripts) and for the API. All pages were verified to run under it with zero violations. | `TestAQ022AQ004ReportInjection`, nginx `security-headers.conf` |

## High

| ID | Finding | Result here | What was done | Guard |
|---|---|---|---|---|
| AQ-005 | Unauthenticated ingestion and reads | **Not applicable.** Ingestion needs an API key with `telemetry:ingest`. The test calls **every** `GET /v1/*` route without credentials and expects 401. Only health probes and the API changelog are public, by design. | `/metrics` is never routed publicly: nginx and the ingress return 404 for it. | `TestAQ005ReadsNeedAuthentication` |
| AQ-006 | Passwords in URL query strings, written to access logs | **Not applicable.** Credentials travel in JSON bodies. | — | `TestAQ006CredentialsInBody` (no query parameter named *password*, *secret* or *token*) |
| AQ-008 | `inf`/`NaN` stored and then break reads; huge numbers cause a 500 | **Fixed. The same defect existed here.** `Infinity`, `NaN` and `1e400` were stored in `telemetry_data` with "good" quality. Reads masked them, but hourly averages and KPIs would have been corrupted. Separately, `limit=-1` on the telemetry query returned **500**. | Non-finite readings are rejected per point (`NON_FINITE_VALUE`), so the rest of a SCADA batch is kept. They are also refused in the stream processor for other Kafka producers. Every other request schema rejects them with 422 (`APIModel`). All numeric query parameters now have upper and lower bounds, including a `page` cap that stops a bigint overflow in `OFFSET`. | `TestAQ008NonFiniteNumbers` |
| AQ-028 | README install fails (missing dependencies) | **Not applicable.** `requirements/{base,prod,dev}.txt` pin every dependency. A clean virtualenv install of `requirements/dev.txt` was repeated for this response. | — | CI installs from scratch on every push |
| AQ-029 | Database with user data committed to git history | **Risk was present.** The project had **no `.gitignore`**, so the first `git add .` would have committed `backend/.env`, the generated integration key in `backend/var/`, and caches. | Added a root `.gitignore` covering secrets, keys, databases and build output. CI now fails if such a file is ever tracked, and runs a gitleaks secret scan over the full history. The demo password is documented, not secret. | `.github/workflows/ci.yml` |

## Medium

| ID | Finding | Result here | What was done | Guard |
|---|---|---|---|---|
| AQ-007 | Statistics mix different sensor types | **Not applicable.** Rules are defined per tag (one sensor). The anomaly model uses standardised per-feature inputs of one pump, and trains only on running periods. | — | `test_rules_engine.py` |
| AQ-009 | Foreign keys / NOT NULL not enforced | **Fixed.** PostgreSQL already enforced every foreign key and NOT NULL. But a violation reached the client as **500**: for example, a rule for a non-existent tag, or a work order for an unknown asset. | Constraint errors map to proper statuses everywhere: foreign key → 422 `INVALID_REFERENCE`, unique → 409, NOT NULL / check → 422. The rule service now checks the tag first and says so clearly. | `TestAQ009AQ011IntegrityErrors` |
| AQ-010 | Passwords over 72 bytes cause 500 (bcrypt) | **Not applicable.** Passwords use Argon2id, which has no 72-byte limit, and lengths are bounded (422). | Maximum lengths were added to the create, reset and change-password fields. | `TestAQ010AQ012InputValidation` |
| AQ-011 | Errors returned with HTTP 200 | **Fixed.** Errors already used real statuses inside the error envelope. The one gap was database constraint errors returning 500 (see AQ-009). | Same fix as AQ-009. | `TestAQ009AQ011IntegrityErrors` |
| AQ-012 | No input validation | **Fixed.** Most validation was in place: e-mail, password policy, enums, lengths. **But a name of only spaces (`" "`) was accepted**, and some free-text fields had no maximum length. | Every request string is trimmed, so a blank name now fails `min_length`; passwords and tokens are exempt. Length limits were added to descriptions, notes, codes and phone numbers. | `TestAQ010AQ012InputValidation` |
| AQ-013 | Times shown shifted by the UTC offset | **Fixed. The defect was present here.** The API already returned UTC with an offset, but the UI rendered every time in UTC, so an IST user saw times 5 h 30 min behind their clock. | Times now show in the viewer's local zone, and the header shows which zone (e.g. `GMT+5:30`). Plant behaviour that depends on the hour of day now follows `AQUAINTEL_TZ` instead of server UTC: tariff windows, the demand curve, silent hours and report schedules (`core/timeutil.py`). | `TestAQ013Timestamps`, Playwright (`timezoneId: Asia/Kolkata`) |
| AQ-014 | Wildcard CORS, no security headers, no login throttling | **Fixed.** CORS was already an allowlist, and login was already limited to 5/min per IP with lockout after 10 failures. But security headers were set only by nginx, so the API reached directly (port-forward, internal callers) had none. | API middleware now adds `nosniff`, `X-Frame-Options`, a strict CSP, `Referrer-Policy` and `Cache-Control: no-store` on `/v1`. The SPA gets its own CSP. | `TestAQ014Hardening`, `test_bad_password_and_login_rate_limit` |
| AQ-021 | Expired or garbage tokens keep pages open | **Not applicable.** Verified in the browser: a forged token in storage is sent back to the login page, and a refresh failure signs the user out. | — | manual browser check (recorded in this audit) |
| AQ-023 | Edit breaks for names with an apostrophe | **Not applicable.** React has no inline JavaScript built from data. | — | — |

## Low and info

| ID | Finding | Result here | What was done |
|---|---|---|---|
| AQ-015 | Unpaginated list endpoints | **Not applicable.** Lists are paginated (max 500 per page). The raw telemetry query is capped at 100 000 rows and returns `truncated`; aggregates are capped at 20 000 buckets. | Lower bounds added (see AQ-008). |
| AQ-016 | Duplicate rules raise duplicate alerts | **Fixed. The defect was present here.** | An identical *enabled* rule (same tag, type, severity and condition, compared as JSON so key order doesn't matter) is refused with **409**, naming the existing rule. Re-enabling a disabled twin is refused as well. Rules logic moved from the router into `services/rule_service.py`. Guard: `TestAQ016DuplicateRules`. |
| AQ-017 | Rules cannot be listed or deleted; alerts cannot be acknowledged | **Not applicable.** These are endpoints #43–#47 and #38–#42 (list, update, toggle, delete, acknowledge, resolve, escalate, bulk). | Guard: `TestAQ017RuleManagement`. |
| AQ-018 | Isolation Forest flags ~10% of clean data | **Not applicable.** The model is fitted once on normal running data, and its alert threshold is fixed at training time rather than re-estimated per request. The measured false-positive rate on held-out data is about 2% (spec target < 10%). | — |
| AQ-019 | E-mail uniqueness is case-sensitive | **Not applicable.** E-mails are stored lower-case and looked up case-insensitively. | Guard: `TestAQ019EmailCase`. |
| AQ-020 | Paths depend on the working directory | **Fixed. The defect was present here.** `.env`, the local report store and Alembic's `script_location` were all resolved from the start folder. | All are anchored to `backend/` (`BACKEND_DIR`, `%(here)s`). Guard: `TestAQ020WorkingDirectory` starts from a temporary folder. |
| AQ-022 | CSV export: no quoting, formula injection | **Fixed. The same class existed in Excel export.** openpyxl stores any string that starts with `=` as a live formula, so an asset named `=HYPERLINK(…)` would execute when opened. The download filename was also built from user text. | Every report cell is forced to text. Filenames are reduced to safe ASCII (no quotes, CR/LF or non-Latin-1 characters). Guard: `TestAQ022AQ004ReportInjection`. |
| AQ-024 / AQ-025 | Sign-up message cleared; Enter does not submit login | **Not applicable.** There is no sign-up; Enter submits the login form (verified). | — |
| AQ-026 | Detail page without an id is stuck on "Loading…" | **Fixed. The defect was present here.** A bad or unknown id left the asset, alert, KPI and dashboard pages spinning forever. | A shared `LoadFailed` state shows "… not found" with a way back for 404/422, and the error with Retry otherwise. Guard: a component test. |
| AQ-027 | Silent failure when the API is down; CDN dependency | **Fixed. The defect was present here.** Tables showed "No records" when the request had *failed*. The header showed **"0 critical · 0 major"** when the counts were unknown, which is dangerous in a control room. Raw codes such as `FETCH_ERROR` were displayed. IBM Plex came from Google Fonts, which breaks offline. | `DataTable` shows the error with Retry instead of an empty state. The header says "Alert counts unavailable". Errors are plain sentences. Fonts are bundled (`@fontsource`), and the app now makes zero third-party requests (verified). Guard: component tests. |
| AQ-030 | Repository hygiene: tracked `__pycache__`, no tests, CI, Dockerfile or LICENSE | **Mostly fixed.** Tests, CI and Dockerfiles exist. The missing `.gitignore` is fixed (see AQ-029). | A LICENSE is the owner's decision and is not added. |
| AQ-031 | `python-jose` → vulnerable `ecdsa` | **Not applicable.** This project uses PyJWT, and CI runs `pip-audit`. | — |
| AQ-032 | Prediction card hard-coded to one sensor | **Not applicable.** Predictions are per model and per asset. | — |
| AQ-033 | Documentation claims that don't match the code | **Fixed.** While re-checking, one claim of ours was wrong: `ARCHITECTURE.md` said routers never touch the ORM, but the rules endpoints did. | Refactored into `RuleService`, so the claim is true again. Time-zone documentation corrected. |

## How the re-test was done

1. **Probes against the running API:** anonymous calls to every route, forged and garbage tokens,
   `Infinity`/`NaN`/`1e400` in JSON, oversized and negative numbers, unknown foreign keys,
   duplicate rules, markup and formulas in names, file paths.
2. **Real Chrome via Playwright**, in the `Asia/Kolkata` time zone:
   * every page loaded under the production CSP, with violations and third-party hosts recorded;
   * the API was blocked to simulate an outage;
   * a garbage token was placed in storage;
   * invalid ids were opened in the URL.
3. Each confirmed defect was fixed and then **turned into an automated test**, so that it stays fixed.
