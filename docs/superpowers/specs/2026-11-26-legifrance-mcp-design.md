# Legifrance MCP Server — Design

## Intent

A fun/learning project: an MCP server that lets an MCP client (Claude
Desktop, Claude Code) query French law — code articles, consolidated
texts, and jurisprudence (case law) — by talking to DILA's official
Légifrance and Judilibre APIs.

## Goals

- Expose MCP tools for looking up law articles, full-text search across
  codes/texts, tracking how a text changed over time, and searching/
  fetching case law.
- Use the official, sanctioned data channel (PISTE-hosted APIs), not the
  public website.
- Keep the v1 surface small and useful rather than wrapping the whole
  API catalog.

## Non-goals

- Not a general legal-research platform: no citation-checking, drafting
  assistance, or RAG over downloaded documents in v1.
- Not covering other PISTE APIs unrelated to law/case-law lookup (JORF
  bulletins, DUME, procurement APIs, etc.).
- No persistent database or document cache in v1 — calls pass through
  to the APIs live (aside from caching the OAuth access token itself).
- No UI. This is a backend MCP server for tool-calling clients only.

## Anti-goals

- Scraping legifrance.gouv.fr's website/internal endpoints instead of
  using the official API. Considered and rejected — see Approaches.

## Constraints

- Requires a PISTE account with OAuth2 client-credentials for both the
  Légifrance API and the Judilibre API, each accepted separately via
  PISTE's "Consentement CGU API" step, and separately again for sandbox
  vs. production environments. Confirmed done for both APIs, sandbox
  environment, as of this design (production CGU/credentials not yet
  obtained — out of scope until v1 is validated, see Decided below).
- Sandbox and production are fully separate: different base URLs, token
  endpoints, and client_id/secret pairs. The server config needs to
  support switching between them without code changes.
- Data is published under Licence Ouverte 2.0; commercial/other reuse is
  allowed "at the user's own risk" and DILA can revoke API access for a
  breach of the API's terms of use without notice.
- Exact request/response shapes come from the Légifrance/Judilibre
  Swagger docs on the PISTE portal — the implementation needs to match
  those, not be guessed.
- Licence Ouverte 2.0 carries a real attribution obligation, not just a
  risk disclaimer: reuse must mention the source (at minimum, the name
  of the producer, DILA) and the date of last update of the information
  reused, satisfiable by including a URL back to the source. Tool
  responses need to carry this (e.g. a source URL/date field), not treat
  it as optional formatting.

## Approaches considered

1. **Scrape legifrance.gouv.fr's UI/internal endpoints.** Rejected. No
   data advantage (same underlying DILA data as the API), the site has
   had anti-scraping protections since a 2020 redesign (which broke the
   prior community scraper, `legipy`), and legally it's on much shakier
   ground (database-producer rights, a ToS built around the API as the
   intended reuse channel, no guarantee against being cut off) than a
   free, documented, sanctioned API built for exactly this purpose.
2. **Build fully from scratch against the official PISTE APIs.** Most
   control, but duplicates work already done well elsewhere.
3. **Use existing open-source prior art instead of building fresh.**
   Several Légifrance/Judilibre MCP servers already exist. The most
   relevant: `pylegifrance/pylegifrance` (actively maintained Python
   library wrapping Légifrance's codes/LODA/JURI search with direct
   PISTE OAuth2 auth) and `pylegifrance/mcp-server-legifrance` (an MCP
   server with near-matching tools, but stale — last touched mid-2025 —
   and its `server.py` routes every call through a third-party proxy
   (`lab.dassignies.law`) requiring an API key obtained informally from
   its maintainer, rather than using the `pylegifrance` library it
   claims to be built on, or the PISTE credentials already in hand for
   this project.

**Chosen: a hybrid of 2 and 3.** Fork both repos (`jfenal/pylegifrance`,
`jfenal/mcp-server-legifrance`, both with `upstream` remotes pointing at
`pylegifrance/*`) rather than depending on them unmodified or rebuilding
from zero:

- **Server fork**: keep its existing tool shape (`rechercher_code`,
  `rechercher_dans_texte_legal`, `rechercher_jurisprudence_judiciaire`,
  plus the `agent_juridique_expert` prompt) but replace its proxy-backed
  `make_api_request` with direct calls into the `pylegifrance` library
  (`fonds.code`, `fonds.loda`, `fonds.juri`), authenticated via the
  project's own PISTE sandbox credentials instead of a third-party key.
- **Library fork**: add a new `fonds/judilibre.py` (mirroring the
  existing `fonds/juri.py` pattern) for Judilibre's richer jurisprudence
  API, since `pylegifrance` only covers Légifrance's own JURI fond today.
- This keeps real reuse (auth, request/response modeling, existing tool
  surface) while fixing the one thing that didn't fit (the proxy
  dependency) and adding the one thing that was missing (Judilibre).

## Decided

- **Data source:** official PISTE APIs — Légifrance (codes, consolidated
  texts, legislative history) and Judilibre (jurisprudence).
- **Language/runtime:** Python. Chosen not for raw performance (the
  bottleneck here is network I/O to the APIs, where Python/Node are a
  wash) but because `pylegifrance` already exists as a working reference
  for this API's auth flow, pagination, and quirks.
- **MVP tool scope** (revised after inspecting the forked code — the
  library already does more of this than assumed):
  1. `rechercher_code` (existing) — search/fetch articles within a
     French code by name + keyword/article number, backed by
     `fonds.code.Code.search()` / `.fetch_article()`. `pylegifrance`'s
     `NomCode` enum already covers the ~78 official code names, so
     callers pass human-readable names ("Code civil") directly — no
     separate name→ID mapping needs to be built.
  2. `rechercher_dans_texte_legal` (existing) — search within LODA texts
     (lois, ordonnances, décrets, arrêtés) by text ID or keyword, backed
     by `fonds.loda`.
  3. `get_text_history` (new, but thin) — how a text/article changed
     over time. `fonds.loda.TexteLoda` already implements `.versions()`,
     `.at(date)`, `get_modified_articles()`/`get_created_articles()`,
     and `format_modifications_report()`/`to_markdown()` — this tool is
     mostly exposing existing library methods, not building new logic.
  4. `rechercher_jurisprudence_judiciaire` (existing) — keyword/date/
     jurisdiction search over Légifrance's own JURI case-law fond.
  5. `rechercher_jurisprudence_judilibre` (new) — equivalent search over
     Judilibre, via the new `fonds/judilibre.py` added to the library
     fork (richer jurisprudence API Légifrance's own JURI fond doesn't
     cover — see Approaches).
  Tool 1–2 and 4 keep their existing French names/shapes from the
  forked server rather than being renamed, since they already fit.
- **`search_texts`/LODA scope:** limited to Légifrance's LEGI corpus —
  codes plus other consolidated legislative/regulatory texts — not JORF
  announcement texts or other fonds (CNIL, DOLE, etc.), matching what
  `fonds.code`/`fonds.loda` already cover.
- **Definition of done for v1:** a working server validated against the
  **sandbox** environment is sufficient. Production credentials/CGU are
  a later step once the sandbox version is stable, not a v1 blocker —
  consistent with this being a fun/learning project and the "keep v1
  small" goal above.

## Left to the builder

- Replacing `server.py`'s proxy-backed `make_api_request`/`API_KEY`/
  `API_URL` plumbing with direct use of `pylegifrance`'s
  `LegifranceClient`/`AuthenticationManager`/`ApiConfig`, wired to this
  project's own PISTE sandbox `client_id`/`client_secret`.
- `ApiConfig.from_env()` currently hardcodes production PISTE URLs
  (`api.piste.gouv.fr`, `oauth.piste.gouv.fr`); it needs sandbox URL
  support (PISTE's sandbox host) selectable via configuration, not
  hardcoded, consistent with "sandbox-only is enough for v1 done."
- Designing and implementing `fonds/judilibre.py` in the library fork:
  auth reuse (same `AuthenticationManager` pattern, Judilibre's own
  base URL/token scope), request/response modeling mirroring
  `fonds/juri.py`'s shape where sensible, and whatever Judilibre-specific
  filters (jurisdiction, date range, publication status) its API exposes.
- The new `rechercher_jurisprudence_judilibre` and `get_text_history`
  tools in the server: input schema, and how much of the library's
  return value (e.g. `TexteLoda.to_markdown()`'s full report vs. a
  trimmed summary) to pass back to the calling LLM.
- Attribution: adding the Licence Ouverte 2.0 source/date mention (a
  source URL is likely available on the models already) to every tool's
  output, across both existing and new tools.
- Error handling for upstream API errors (401/403/404/500, empty
  results) surfaced as clear MCP tool errors rather than raw exceptions
  or stack traces — the existing server's generic `try`/`except` is a
  reasonable base but may need tightening once the proxy is gone.
- Test strategy: mocking the HTTP layer rather than hitting the sandbox
  API in CI (the forked repos currently have no visible test coverage
  for `server.py`'s tool-calling layer; `pylegifrance` itself should
  already have tests worth keeping green).
- Instructions/config for running the server from Claude Desktop/Claude
  Code (MCP server registration, required env vars).
- Whether/how to track upstream: keeping the `upstream` remotes useful
  for pulling in `pylegifrance`'s future fixes (e.g. for `fonds/code`,
  `fonds/loda`) without losing the Judilibre/auth changes made here.
