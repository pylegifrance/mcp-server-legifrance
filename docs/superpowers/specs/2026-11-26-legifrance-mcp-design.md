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
2. **Use the official PISTE APIs (Légifrance + Judilibre) directly.**
   Chosen. Free, stable, documented, same data, officially sanctioned
   for programmatic reuse.

Only one approach survives real consideration; recorded here for the
record rather than as a live tradeoff.

## Decided

- **Data source:** official PISTE APIs — Légifrance (codes, consolidated
  texts, legislative history) and Judilibre (jurisprudence).
- **Language/runtime:** Python. Chosen not for raw performance (the
  bottleneck here is network I/O to the APIs, where Python/Node are a
  wash) but because `pylegifrance` already exists as a working reference
  for this API's auth flow, pagination, and quirks.
- **MVP tool scope** (approved by project owner):
  1. `get_article` — fetch a specific article by code name + article
     number, current consolidated version.
  2. `search_texts` — full-text search across codes/laws for a keyword
     or phrase, returning matching articles/texts with references.
  3. `get_text_history` — show how an article/text changed over time
     (versions, effective dates), using Légifrance's native versioning.
  4. `search_jurisprudence` — keyword/date/jurisdiction search over case
     law via Judilibre, returning decision summaries + references.
  5. `get_decision` — fetch the full text of a specific court decision
     by its Judilibre ID.
- **Code identification (`get_article`/`search_texts`):** callers pass
  the human-readable code name (e.g. "Code civil"), not Légifrance's
  internal code ID (CID). The server resolves name → CID via a static
  mapping of the ~80 official codes, built once from Légifrance's code
  list rather than hardcoded by hand. This is more natural for an LLM
  caller than requiring an opaque internal ID.
- **`search_texts` scope:** limited to Légifrance's LEGI corpus — codes
  plus other consolidated legislative/regulatory texts — not JORF
  announcement texts or other fonds (CNIL, DOLE, etc.). This matches
  the doc's "codes/laws" framing and keeps the tool's result shape
  predictable for v1.
- **Definition of done for v1:** a working server validated against the
  **sandbox** environment is sufficient. Production credentials/CGU are
  a later step once the sandbox version is stable, not a v1 blocker —
  consistent with this being a fun/learning project and the "keep v1
  small" goal above.

## Left to the builder

- MCP SDK choice (official Python MCP SDK) and project scaffolding
  (packaging, entrypoint, dependency management).
- OAuth2 client-credentials token handling: fetching, caching, and
  refreshing the access token against PISTE's token endpoint, with
  sandbox vs. prod endpoints/credentials selected via configuration
  (e.g. environment variables), not hardcoded.
- Exact endpoint mapping for each tool against the Légifrance/Judilibre
  Swagger docs (and optionally cross-checked against `pylegifrance`'s
  implementation).
- Error handling for upstream API errors (401/403/404/500, empty
  results) surfaced as clear MCP tool errors rather than raw exceptions
  or stack traces.
- Response shaping: how much of the raw API payload to pass through
  vs. trim/reformat per tool, balancing completeness against the
  calling LLM's context budget.
- Test strategy: mocking the HTTP layer rather than hitting the sandbox
  API in CI.
- Instructions/config for running the server from Claude Desktop/Claude
  Code (MCP server registration, required env vars).
