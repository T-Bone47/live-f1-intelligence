# PHASE K — CODE QUALITY

## Frontend: ESLint added (there was none)

`frontend/eslint.config.js`, flat config. `npm run lint`: **0 errors,
126 warnings** (all `@typescript-eslint/no-explicit-any`).

Deliberately did NOT adopt `eslint-plugin-react-hooks`'s full
`recommended` config — that version bundles the full React Compiler
rule suite (29 rules), and several (`set-state-in-effect`,
`preserve-manual-memoization`) flagged this codebase's existing,
working fetch-in-effect pattern as hard errors across most of
`state/store.ts`. Adopting React Compiler conventions repo-wide is a
real refactor, not a lint-cleanly task. Kept just `rules-of-hooks`
(error) and `exhaustive-deps` (warn).

`no-explicit-any` is `warn`, not `off`, on purpose: every bug found in
Phase C/F this session was hidden by an `any` type masking a real
contract mismatch from `tsc`. The 126 warnings are that same signal,
surfaced going forward — reported, not cleared, matching this phase's
brief for pre-existing debt.

The only 2 real errors found (`prefer-const`, from base ESLint, not
react-hooks) were fixed — both were `let`-declared then assigned
exactly once.

## Backend: ruff findings, categorized

**290 findings** (was ~293 at the start of this phase — 3 were real
bugs, not style, and got fixed separately: see below). Full suite still
316 passed / 4 skipped / 0 failed after every fix in this phase.

| Code | Count | What it is |
|---|---|---|
| F841 | 18 | unused-variable |
| FURB167 | 18 | regex-flag-alias (style) |
| UP035 | 14 | deprecated-import (`typing.X` → builtin) |
| RUF059 | 12 | unused-unpacked-variable |
| UP006 | 11 | non-pep585-annotation (`List[X]` → `list[X]`) |
| ISC004 | 7 | implicit string concat in a collection literal |
| FURB162 | 6 | `.replace("Z", ...)` → `fromisoformat` handles `Z` natively |
| UP037 | 5 | quoted-annotation (no longer needed) |
| RUF012 | 4 | mutable class default |
| RUF022 | 4 | unsorted `__all__` |
| DTZ005 | 3 | `datetime.now()` without `tzinfo` |
| UP041 | 3 | `asyncio.TimeoutError` → `TimeoutError` alias |
| B010 / F811 | 2 each | `setattr` with a constant name / redefined-while-unused |
| 14 other rules | 1 each | assorted style (see `ruff check --statistics` for the full list) |

223 of the 290 are auto-fixable with `--fix` (mechanical, low-risk —
not run this phase, since a 223-line mixed-file diff of purely
cosmetic changes is exactly the "giant cleanup" this phase's brief
says not to attempt). None are the exhaustive kind of error-class that
would mask a runtime crash — that check was done separately.

**3 findings that were NOT style — fixed on sight, not left in this
table:** `F821` (undefined-name) appeared 3 times while categorizing
this list. Both root causes were genuine, currently-latent
`NameError`s: `app/ingest/normalize.py` raised `NormalizationError`
twice without importing it, and `app/storage/db.py`'s `insert_event` —
the core event-persistence path — called bare `json.loads(...)` inside
a method that locally imports `json as _json`. See the commit for
detail. `F821` no longer appears in the table above because both were
fixed, not because they were miscounted.
