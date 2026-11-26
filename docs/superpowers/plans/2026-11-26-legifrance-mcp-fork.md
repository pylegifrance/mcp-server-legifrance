# Legifrance MCP Server (fork-and-extend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the forked `mcp-server-legifrance` into an MCP server that talks directly to PISTE (Légifrance + Judilibre) using the forked `pylegifrance` library, instead of the third-party `dassignies.law` proxy it ships with today.

**Architecture:** Two sibling git repos, both forks with `upstream` remotes already configured:
- `/home/jfenal/dev/gh/pylegifrance` (library) — extended with sandbox/prod config switching and a new Judilibre fond.
- `/home/jfenal/dev/gh/legifrance-mcp` (server, fork of `mcp-server-legifrance`) — depends on the local `pylegifrance` fork via a `uv` path source; its five MCP tools call into `pylegifrance` directly instead of the proxy.

**Tech Stack:** Python 3.12, `pylegifrance` (requests, pydantic v2, tenacity), `mcp[cli]`, `pytest` (+ `unittest.mock` for unit tests, existing `pytest-bdd` integration suite in `pylegifrance`), `uv` for dependency management.

**Spec:** `docs/superpowers/specs/2026-11-26-legifrance-mcp-design.md`

## Global Constraints

- Sandbox-only is sufficient for "v1 done" — production PISTE credentials are a later step, not a blocker for any task here.
- Every tool response must carry a Licence Ouverte 2.0 attribution: a source URL and, where the underlying model exposes one, a last-update date. No tool ships without this.
- `pylegifrance` has no Judilibre support today — it must be added (new fond), not assumed to exist.
- Judilibre lives on a different PISTE host than Légifrance's own API (`.../cassation/judilibre/v1.0` vs `.../dila/legifrance/lf-engine-app/`) and authenticates with an additional `KeyId` header on top of the normal PISTE bearer token — it cannot reuse `LegifranceClient.call_api` (POST-only, single base URL) unmodified.
- Keep the existing server's tool names/shapes (`rechercher_code`, `rechercher_dans_texte_legal`, `rechercher_jurisprudence_judiciaire`) rather than renaming them — only their backing implementation changes.
- `pylegifrance`'s `NomCode` enum already covers the ~78 official code names; do not build a second name-resolution layer.

## Review Focus

- An unrecognized code name passed to `rechercher_code` (not a valid `NomCode`) — the tool should return a clear error to the LLM caller, not an unhandled `ValueError`/stack trace.
- A search that matches nothing (any of the five tools) — should return an explicit "no results" message, not an empty/ambiguous payload the caller might mistake for an error.
- Missing or malformed Judilibre configuration (`KeyId`/credentials not set) — should fail fast and clearly when the server starts or on first Judilibre call, not surface as a generic 401 deep in a stack trace.
- The PISTE access token expiring during a long-running server process — `AuthenticationManager.ensure_valid_token()` already refreshes on expiry; a test should pin that a second call after expiry re-fetches rather than reusing a stale token.
- A broad jurisprudence search with many/full-text results — response size must stay bounded enough for an LLM caller's context budget rather than dumping every full decision text inline.

---

## Part A — `pylegifrance` fork (`/home/jfenal/dev/gh/pylegifrance`)

### Task 1: Sandbox/production URL switching in `ApiConfig`

**Files:**
- Modify: `pylegifrance/config.py`
- Test: `tests/test_config.py` (new)

**Interfaces:**
- Produces: `ApiConfig.from_env()` continues to return an `ApiConfig`, but now sandbox-aware; new constants `SANDBOX_TOKEN_URL`, `SANDBOX_API_URL`, `PROD_TOKEN_URL`, `PROD_API_URL` in `pylegifrance/config.py` for later tasks/consumers to reference.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_from_env_defaults_to_sandbox(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("PISTE_ENV", raising=False)
    config = ApiConfig.from_env()
    assert config.token_url == SANDBOX_TOKEN_URL
    assert config.api_url == SANDBOX_API_URL

def test_from_env_production_opt_in(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PISTE_ENV", "production")
    config = ApiConfig.from_env()
    assert config.token_url == PROD_TOKEN_URL
    assert config.api_url == PROD_API_URL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`SANDBOX_TOKEN_URL` etc. not defined / `from_env` ignores `PISTE_ENV`)

- [ ] **Step 3: Implement sandbox/prod switching in `pylegifrance/config.py`**

Add the four URL constants (sandbox host is `sandbox-oauth.piste.gouv.fr` / `sandbox-api.piste.gouv.fr`; keep the existing prod values as `PROD_*`). In `ApiConfig.from_env()`, read `PISTE_ENV` (default `"sandbox"`, case-insensitive), pick the matching pair, and pass them as `token_url`/`api_url` to the constructed `ApiConfig`. Reject any value other than `"sandbox"`/`"production"` with a `ValueError` naming the offending value.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pylegifrance/config.py tests/test_config.py
git commit -m "feat(config): switch PISTE sandbox/production via PISTE_ENV"
```

---

### Task 2: Judilibre client and auth

**Files:**
- Create: `pylegifrance/fonds/judilibre.py` (client + config only, no search/fetch logic yet)
- Create: `pylegifrance/models/judilibre/__init__.py`
- Create: `pylegifrance/models/judilibre/models.py`
- Test: `tests/unit/fonds/test_judilibre_client.py` (new)

**Interfaces:**
- Consumes: `pylegifrance.auth.AuthenticationManager`, `pylegifrance.config.ApiConfig` (Task 1).
- Produces:
  - `JUDILIBRE_SANDBOX_URL = "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0"`, `JUDILIBRE_PROD_URL = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"` constants in `fonds/judilibre.py`.
  - `class JudilibreClient: def __init__(self, config: ApiConfig, key_id: str, api_url: str | None = None)` — `api_url` defaults to `JUDILIBRE_SANDBOX_URL`.
  - `JudilibreClient.get(self, route: str, params: dict[str, Any] | None = None) -> requests.Response` — sends `Authorization: Bearer <token>` (via `self._auth_manager.ensure_valid_token()`) **and** `KeyId: <key_id>` headers.
  - `pydantic` models `DecisionShort` and `DecisionFull` in `models/judilibre/models.py` with fields: `id: str`, `jurisdiction: str | None`, `chamber: str | None`, `number: str | None`, `numbers: list[str] | None`, `ecli: str | None`, `formation: str | None`, `publication: list[str] | None`, `decision_date: str | None`, `type: str | None`, `solution: str | None`, `summary: str | None`, `themes: list[str] | None`, `files: list[dict] | None` on `DecisionShort`; `DecisionFull` extends it with `text: str | None`, `update_date: str | None`, `visa: list[dict] | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fonds/test_judilibre_client.py
from unittest.mock import MagicMock, patch
from pylegifrance.config import ApiConfig
from pylegifrance.fonds.judilibre import JudilibreClient, JUDILIBRE_SANDBOX_URL

def test_get_sends_bearer_and_keyid_headers():
    config = ApiConfig(client_id="id", client_secret="secret")
    client = JudilibreClient(config=config, key_id="my-key-id")
    client._auth_manager.ensure_valid_token = MagicMock(return_value="tok123")

    with patch.object(client._session, "get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        client.get("search", params={"query": "brevet"})

    called_url = mock_get.call_args.args[0]
    called_headers = mock_get.call_args.kwargs["headers"]
    assert called_url == f"{JUDILIBRE_SANDBOX_URL}/search"
    assert called_headers["Authorization"] == "Bearer tok123"
    assert called_headers["KeyId"] == "my-key-id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fonds/test_judilibre_client.py -v`
Expected: FAIL (module/class does not exist)

- [ ] **Step 3: Implement `JudilibreClient` in `pylegifrance/fonds/judilibre.py`**

Construct an internal `AuthenticationManager(config)` (same PISTE OAuth2 token the Légifrance API uses) and a `requests.Session()`. `get()` builds `f"{self._api_url}/{route}"`, sets both headers, forwards `params`, and raises on 4xx/5xx the same way `LegifranceClient.call_api` does (`raise Exception(f"API client error {status} - {body}")`) so callers get one consistent error shape across fonds. Judilibre's public OpenAPI spec only documents the `KeyId` header explicitly; PISTE's gateway is assumed to still require the standard bearer token on top of it (true of every other PISTE-hosted API seen so far). If sandbox calls 401 with both headers set, try dropping the `Authorization` header before assuming something else is wrong.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fonds/test_judilibre_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pylegifrance/fonds/judilibre.py pylegifrance/models/judilibre/ tests/unit/fonds/test_judilibre_client.py
git commit -m "feat(judilibre): add client with PISTE bearer + KeyId auth"
```

---

### Task 3: `JudilibreAPI` search/fetch + `JudilibreDecision` wrapper

**Files:**
- Modify: `pylegifrance/fonds/judilibre.py` (add `JudilibreAPI`, `JudilibreDecision`)
- Test: `tests/unit/fonds/test_judilibre_decision.py` (new)

**Interfaces:**
- Consumes: `JudilibreClient` (Task 2), `DecisionShort`/`DecisionFull` (Task 2).
- Produces:
  - `class JudilibreDecision` wrapping a `DecisionFull` (or `DecisionShort` for search hits), exposing properties `.id`, `.jurisdiction`, `.chamber`, `.ecli`, `.decision_date`, `.summary`, `.solution`, `.text` (`None` for search-result-only instances), `.update_date`, and `.url` (first `files[].url` if present, else `None`), plus `.to_markdown() -> str` (mirrors `JuriDecision.to_markdown()`'s structure: heading with jurisdiction/chamber/date, solution, ECLI, URL, summary, then text if present).
  - `class JudilibreAPI: def __init__(self, client: JudilibreClient)`.
  - `JudilibreAPI.search(self, query: str, **filters: Any) -> list[JudilibreDecision]` — GETs `search` with `query` plus any of the documented filter kwargs (`jurisdiction`, `chamber`, `date_start`, `date_end`, `page_size`) passed straight through as query params; wraps each `results[]` entry as a `JudilibreDecision`.
  - `JudilibreAPI.fetch(self, decision_id: str) -> JudilibreDecision | None` — GETs `decision?id=...`; returns `None` on a 404-shaped response, re-raises other errors.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/fonds/test_judilibre_decision.py
from unittest.mock import MagicMock
from pylegifrance.fonds.judilibre import JudilibreAPI, JudilibreDecision

def test_search_wraps_results_as_decisions():
    client = MagicMock()
    client.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"results": [{"id": "abc123", "jurisdiction": "Cour de cassation",
                                    "chamber": "Chambre sociale", "decision_date": "2020-03-04",
                                    "summary": "Résumé", "files": [{"url": "https://judilibre.fr/abc123"}]}]}
    )
    api = JudilibreAPI(client)

    results = api.search("licenciement")

    assert len(results) == 1
    assert isinstance(results[0], JudilibreDecision)
    assert results[0].id == "abc123"
    assert results[0].url == "https://judilibre.fr/abc123"

def test_fetch_returns_none_for_unknown_id():
    client = MagicMock()
    client.get.return_value = MagicMock(status_code=404, json=lambda: {"error": "not found"})
    api = JudilibreAPI(client)

    assert api.fetch("does-not-exist") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/fonds/test_judilibre_decision.py -v`
Expected: FAIL (`JudilibreAPI`/`JudilibreDecision` not defined)

- [ ] **Step 3: Implement `JudilibreDecision` and `JudilibreAPI`**

Base `to_markdown()` closely on `JuriDecision.to_markdown()` (same section order: heading, solution, ECLI/reference, URL, summary, then full text when present). `search()` drops `None`-valued filter kwargs before building `params` (mirror `clean_dict` from the old proxy server rather than reinventing it).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/fonds/test_judilibre_decision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pylegifrance/fonds/judilibre.py tests/unit/fonds/test_judilibre_decision.py
git commit -m "feat(judilibre): add search/fetch API and markdown-formatted decisions"
```

---

## Part B — `mcp-server-legifrance` fork (`/home/jfenal/dev/gh/legifrance-mcp`)

### Task 4: Depend on the local `pylegifrance` fork; drop the proxy config

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/server.py:21-54` (env loading / `API_KEY`/`API_URL` block)
- Modify: `README.md` (Prérequis/Installation sections — replace `DASSIGNIES_API_KEY`/`DASSIGNIES_API_URL` with `LEGIFRANCE_CLIENT_ID`/`LEGIFRANCE_CLIENT_SECRET`/`PISTE_ENV`)
- Test: `tests/test_config.py` (new)

**Interfaces:**
- Consumes: `pylegifrance.ApiConfig`, `pylegifrance.LegifranceClient` (Task 1).
- Produces: a module-level `get_legifrance_client() -> LegifranceClient` in `src/server.py` that later tasks (5–9) call instead of `make_api_request`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from unittest.mock import patch
import server

def test_get_legifrance_client_builds_from_env(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    client = server.get_legifrance_client()
    assert client.api_url  # built successfully, no proxy env vars needed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`get_legifrance_client` not defined / `DASSIGNIES_API_KEY` still required)

- [ ] **Step 3: Rewire `src/server.py`'s config block**

Run `uv add --editable ../pylegifrance` to register the local fork as a path dependency (adds a `[tool.uv.sources]` entry; keeps the dependency name `pylegifrance`). Delete the `API_KEY`/`API_URL`/`ValueError` block (lines ~41–46) and `HEADERS` (line 48), replacing with `from pylegifrance import ApiConfig, LegifranceClient` and `def get_legifrance_client() -> LegifranceClient: return LegifranceClient(ApiConfig.from_env())`. Remove the now-unused `requests` import if nothing else in the file still needs it directly (Tasks 5–8 will confirm). Update `README.md`'s Prérequis/Installation/`.env` example accordingly.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/server.py tests/test_config.py README.md
git commit -m "feat(config): authenticate directly against PISTE via pylegifrance"
```

---

### Task 5: Rewire `rechercher_code`

**Files:**
- Modify: `src/server.py` (`call_tool`'s `rechercher_code` branch, `make_api_request` removal for this path)
- Test: `tests/test_tools_code.py` (new)

**Interfaces:**
- Consumes: `get_legifrance_client()` (Task 4), `pylegifrance.fonds.code.Code`, `pylegifrance.models.code.enum.NomCode`.
- Produces: `async def call_rechercher_code(arguments: dict) -> list[TextContent]`, called from `call_tool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_code.py
from unittest.mock import MagicMock, patch
import pytest
from server import call_rechercher_code

@pytest.mark.asyncio
async def test_unknown_code_name_returns_clear_error():
    result = await call_rechercher_code({"search": "contrat", "code_name": "Pas un code"})
    assert "code" in result[0].text.lower()
    assert "Pas un code" in result[0].text

@pytest.mark.asyncio
async def test_no_results_returns_explicit_message():
    with patch("server.Code") as mock_code_cls:
        mock_code_cls.return_value.search.return_value.in_code.return_value \
            .text.return_value.execute.return_value = []
        result = await call_rechercher_code({"search": "zzzzz", "code_name": "Code civil"})
    assert "aucun résultat" in result[0].text.lower()
```

(Adjust the builder-chain mock to match `CodeSearchBuilder`'s actual fluent methods once Step 3 is written — the test's job is to pin "unknown code name" and "empty results" behavior, not the exact mock chain shape.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_code.py -v`
Expected: FAIL (`call_rechercher_code` not defined)

- [ ] **Step 3: Implement `call_rechercher_code`**

Resolve `arguments["code_name"]` against `NomCode` (case/accent-tolerant match against the enum's values); on no match, return a `TextContent` naming the invalid value and are a short list of valid examples rather than raising. On a match, build `Code(get_legifrance_client()).search().in_code(resolved).text(arguments["search"])...execute()` using whichever of `champ`/`sort`/`page_size`/`fetch_all` were supplied, matching the existing tool's documented parameters. Format each `Article` result as markdown including its source URL (Article already auto-generates one per the design doc's recon) and an empty-results case returning an explicit "Aucun résultat" message. Wire `call_tool`'s `rechercher_code` branch to call this function instead of `make_api_request`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_code.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_tools_code.py
git commit -m "feat(tools): back rechercher_code with pylegifrance.fonds.code"
```

---

### Task 6: Rewire `rechercher_dans_texte_legal`

**Files:**
- Modify: `src/server.py` (`call_tool`'s `rechercher_dans_texte_legal` branch)
- Test: `tests/test_tools_loda.py` (new)

**Interfaces:**
- Consumes: `get_legifrance_client()` (Task 4), `pylegifrance.fonds.loda.Loda`.
- Produces: `async def call_rechercher_texte_legal(arguments: dict) -> list[TextContent]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_loda.py
from unittest.mock import patch
import pytest
from server import call_rechercher_texte_legal

@pytest.mark.asyncio
async def test_no_results_returns_explicit_message():
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.search.return_value = []
        result = await call_rechercher_texte_legal({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_loda.py -v`
Expected: FAIL (`call_rechercher_texte_legal` not defined)

- [ ] **Step 3: Implement `call_rechercher_texte_legal`**

Mirror Task 5's shape: build the appropriate `Loda(get_legifrance_client())` call from `text_id`/`search`/`champ`/`type_recherche`/`page_size`, format each `TexteLoda` result as markdown with its URL/last-update date (Licence Ouverte attribution), explicit empty-results message. Wire into `call_tool`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_loda.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_tools_loda.py
git commit -m "feat(tools): back rechercher_dans_texte_legal with pylegifrance.fonds.loda"
```

---

### Task 7: Rewire `rechercher_jurisprudence_judiciaire`

**Files:**
- Modify: `src/server.py` (`call_tool`'s `rechercher_jurisprudence_judiciaire` branch)
- Test: `tests/test_tools_juri.py` (new)

**Interfaces:**
- Consumes: `get_legifrance_client()` (Task 4), `pylegifrance.fonds.juri.JuriAPI`.
- Produces: `async def call_rechercher_jurisprudence(arguments: dict) -> list[TextContent]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_juri.py
from unittest.mock import patch
import pytest
from server import call_rechercher_jurisprudence

@pytest.mark.asyncio
async def test_no_results_returns_explicit_message():
    with patch("server.JuriAPI") as mock_juri_cls:
        mock_juri_cls.return_value.search.return_value = []
        result = await call_rechercher_jurisprudence({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_juri.py -v`
Expected: FAIL (`call_rechercher_jurisprudence` not defined)

- [ ] **Step 3: Implement `call_rechercher_jurisprudence`**

Build a `pylegifrance.models.juri.search.SearchRequest` from the tool's existing arguments (`search`, `publication_bulletin`, `sort`, `champ`, `juridiction_judiciaire`, `page_size`, `fetch_all`) and call `JuriAPI(get_legifrance_client()).search(...)`. Format each `JuriDecision` via its existing `.to_markdown()` (already includes URL/date/attribution — no new formatting needed here), explicit empty-results message. Wire into `call_tool`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_juri.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_tools_juri.py
git commit -m "feat(tools): back rechercher_jurisprudence_judiciaire with pylegifrance.fonds.juri"
```

---

### Task 8: Add `rechercher_jurisprudence_judilibre` tool

**Files:**
- Modify: `src/server.py` (`list_tools`, `call_tool`)
- Test: `tests/test_tools_judilibre.py` (new)

**Interfaces:**
- Consumes: `get_legifrance_client()` and a new `get_judilibre_client() -> JudilibreClient` (same task, reads `JUDILIBRE_KEY_ID` from env, reuses the `ApiConfig` from `get_legifrance_client()`'s config for credentials), `pylegifrance.fonds.judilibre.JudilibreAPI` (Task 3).
- Produces: `async def call_rechercher_judilibre(arguments: dict) -> list[TextContent]`, a new `Tool(name="rechercher_jurisprudence_judilibre", ...)` entry in `list_tools()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_judilibre.py
from unittest.mock import patch
import pytest
from server import call_rechercher_judilibre

@pytest.mark.asyncio
async def test_no_results_returns_explicit_message():
    with patch("server.JudilibreAPI") as mock_api_cls:
        mock_api_cls.return_value.search.return_value = []
        result = await call_rechercher_judilibre({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()

@pytest.mark.asyncio
async def test_missing_key_id_fails_clearly(monkeypatch):
    monkeypatch.delenv("JUDILIBRE_KEY_ID", raising=False)
    result = await call_rechercher_judilibre({"search": "licenciement"})
    assert "judilibre_key_id" in result[0].text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_judilibre.py -v`
Expected: FAIL (`call_rechercher_judilibre` not defined)

- [ ] **Step 3: Implement `get_judilibre_client` and `call_rechercher_judilibre`**

`get_judilibre_client()` raises a clear `ValueError` naming `JUDILIBRE_KEY_ID` if the env var is unset, rather than constructing a client that will fail on first use. `call_rechercher_judilibre` maps the tool's arguments (`search`, `jurisdiction`, `chamber`, `date_start`, `date_end`, `page_size`) onto `JudilibreAPI.search(...)` keyword arguments and formats results via `JudilibreDecision.to_markdown()`. Add the new `Tool` definition to `list_tools()` (same `inputSchema` shape convention as the other three tools) and a branch in `call_tool()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_judilibre.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_tools_judilibre.py
git commit -m "feat(tools): add rechercher_jurisprudence_judilibre"
```

---

### Task 9: Add `get_text_history` tool

**Files:**
- Modify: `src/server.py` (`list_tools`, `call_tool`)
- Test: `tests/test_tools_history.py` (new)

**Interfaces:**
- Consumes: `get_legifrance_client()` (Task 4), `pylegifrance.fonds.loda.Loda`/`TexteLoda` (`.versions()`, `.format_modifications_report()`/`.to_markdown()`, already implemented upstream).
- Produces: `async def call_get_text_history(arguments: dict) -> list[TextContent]`, a new `Tool(name="get_text_history", ...)` entry.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_history.py
from unittest.mock import MagicMock, patch
import pytest
from server import call_get_text_history

@pytest.mark.asyncio
async def test_unknown_text_id_returns_explicit_message():
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = None
        result = await call_get_text_history({"text_id": "99-999"})
    assert "aucun résultat" in result[0].text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_history.py -v`
Expected: FAIL (`call_get_text_history` not defined)

- [ ] **Step 3: Implement `call_get_text_history`**

Fetch the `TexteLoda` by `text_id`, and if found call its `.format_modifications_report()` (falls back to `.to_markdown()` if the report is empty — e.g. a text with no recorded modifications) as the tool's output. On `None`, return the explicit "Aucun résultat" message. Add the `Tool`/`call_tool` wiring (input: `text_id`, required).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_history.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server.py tests/test_tools_history.py
git commit -m "feat(tools): add get_text_history"
```

---

### Task 10: Drop the rate limiter's hardcoded proxy assumption and update docs/config for Claude Desktop

**Files:**
- Modify: `src/server.py` (confirm `rate_limit` decorator still makes sense against PISTE's own limits — Légifrance/Judilibre documented limits differ from the old proxy's 10/s)
- Modify: `README.md` (full rewrite of "Outils disponibles" section to include the two new tools; `.env` example with `LEGIFRANCE_CLIENT_ID`/`LEGIFRANCE_CLIENT_SECRET`/`PISTE_ENV`/`JUDILIBRE_KEY_ID`; Claude Desktop config example unchanged in shape)
- Test: none (docs-only; existing test suite from Tasks 4–9 already covers behavior)

- [ ] **Step 1: Update the `rate_limit(calls=5, period=1.0)` decorator's value**

Check PISTE's published rate limits for Légifrance/Judilibre (PISTE portal, per-API documentation) and adjust the decorator's arguments if they differ from the proxy's old, unrelated 5/s figure — that number described the `dassignies.law` proxy, not PISTE itself.

- [ ] **Step 2: Rewrite README's Prérequis/Installation/.env/Outils disponibles sections**

Document all five tools, the new env vars, and that PISTE sandbox credentials (not a `dassignies.law` key) are required, per Task 4's config change.

- [ ] **Step 3: Commit**

```bash
git add src/server.py README.md
git commit -m "docs: document direct-PISTE setup and the full tool set"
```

---

---

### Task 11: Exponential backoff retry on transient API errors

Added after the original plan was executed: neither `LegifranceClient.call_api`
nor `JudilibreClient.get` retried anything — a transient 429/5xx from PISTE
raised immediately, and nothing backed off under load. Only OAuth token
fetch (`AuthenticationManager._fetch_new_token`) had retry, and that's a
fixed 5s wait, not exponential, and unrelated to the data-call path.

**Files:**
- Modify: `pylegifrance/client.py` (`LegifranceClient.call_api`)
- Modify: `pylegifrance/fonds/judilibre.py` (`JudilibreClient.get`)
- Test: `tests/unit/test_client_retry.py` (new), `tests/unit/fonds/test_judilibre_client_retry.py` (new)

**Interfaces:**
- No new public interface. `call_api`/`get`'s signatures and exception
  contract (`Exception(f"API client error {status} - {body}")` on a
  non-retryable or exhausted-retry failure) stay the same — this is
  internal retry/backoff behavior only.
- Retryable: HTTP 429 and 5xx. Not retryable: other 4xx (400/401/403/404 —
  these won't resolve by retrying) and `JudilibreClient.get`'s existing
  404-is-not-found handling (Task 3) stays a single attempt, unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_client_retry.py
from unittest.mock import MagicMock, patch
import pytest
from pylegifrance.client import LegifranceClient
from pylegifrance.config import ApiConfig

def _client() -> LegifranceClient:
    client = LegifranceClient(ApiConfig(client_id="id", client_secret="secret"))
    client._auth_manager.ensure_valid_token = MagicMock(return_value="tok")
    return client

def test_call_api_retries_on_429_then_succeeds():
    client = _client()
    responses = [MagicMock(status_code=429, text="rate limited"), MagicMock(status_code=200, text="ok")]
    with patch.object(client.session, "post", side_effect=responses) as mock_post:
        result = client.call_api("search", {"x": 1})
    assert result.status_code == 200
    assert mock_post.call_count == 2

def test_call_api_does_not_retry_on_400():
    client = _client()
    with patch.object(client.session, "post", return_value=MagicMock(status_code=400, text="bad request")) as mock_post:
        with pytest.raises(Exception, match="400"):
            client.call_api("search", {"x": 1})
    assert mock_post.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_client_retry.py -v`
Expected: FAIL (`test_call_api_retries_on_429_then_succeeds` — `mock_post.call_count == 1`, no retry happens yet)

- [ ] **Step 3: Implement retry with exponential backoff in `call_api`**

Use `tenacity` (already a dependency): wrap the `session.post(...)` call so
that a response with `status_code == 429` or `500 <= status_code < 600`
raises an internal `_TransientAPIError(status_code, body)`, retried with
`wait_exponential(multiplier=1, min=1, max=10)` and `stop_after_attempt(3)`,
`reraise=True`. After retries are exhausted (or immediately for a
non-retryable status), convert back to the existing
`Exception(f"API client error {status} - {body}")` so callers and existing
tests see no change in the error contract — only in whether a transient
failure got retried first.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_client_retry.py -v`
Expected: PASS (first test takes ~1s for the one backoff wait; second is immediate)

- [ ] **Step 5: Commit**

```bash
git add pylegifrance/client.py tests/unit/test_client_retry.py
git commit -m "feat(client): retry 429/5xx with exponential backoff"
```

- [ ] **Step 6: Write the failing test for `JudilibreClient.get`**

```python
# tests/unit/fonds/test_judilibre_client_retry.py
from unittest.mock import MagicMock, patch
from pylegifrance.config import ApiConfig
from pylegifrance.fonds.judilibre import JudilibreClient

def test_get_retries_on_503_then_succeeds():
    client = JudilibreClient(config=ApiConfig(client_id="id", client_secret="secret"), key_id="k")
    client._auth_manager.ensure_valid_token = MagicMock(return_value="tok")
    responses = [MagicMock(status_code=503, text="unavailable"), MagicMock(status_code=200, text="ok")]
    with patch.object(client._session, "get", side_effect=responses) as mock_get:
        result = client.get("search", params={"query": "x"})
    assert result.status_code == 200
    assert mock_get.call_count == 2
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/unit/fonds/test_judilibre_client_retry.py -v`
Expected: FAIL (`mock_get.call_count == 1`, no retry yet)

- [ ] **Step 8: Apply the same retry wrapper to `JudilibreClient.get`**

Same `_TransientAPIError`/backoff approach as Step 3, applied around
`self._session.get(...)`. 404 must stay untouched by this — it is handled
by the existing status-code branch (Task 3's ruling) after the retry
wrapper returns, not treated as retryable.

- [ ] **Step 9: Run test to verify it passes, then run the full suite**

Run: `uv run pytest tests/unit/fonds/test_judilibre_client_retry.py -v`
Expected: PASS

Run: `uv run pytest tests/unit tests/test_config.py tests/test_client.py -q`
Expected: all pass (no regression in Tasks 1-3's existing tests)

- [ ] **Step 10: Commit**

```bash
git add pylegifrance/fonds/judilibre.py tests/unit/fonds/test_judilibre_client_retry.py
git commit -m "feat(judilibre): retry 429/5xx with exponential backoff"
```

---

## Self-Review Notes

- **Spec coverage:** All 5 MVP tools from the design doc are covered (Tasks 5–9), direct-PISTE auth is covered (Task 4), sandbox/prod switching is covered (Task 1), Judilibre support is covered (Tasks 2–3), attribution is folded into each tool task's formatting step rather than a separate task.
- **Review Focus coverage:** unknown code name → Task 5; empty results → Tasks 5–9 each; token expiry → already covered by `AuthenticationManager`'s existing tested behavior upstream, not re-tested here since no code in this plan changes it; missing Judilibre config → Task 8; oversized responses → addressed qualitatively in Tasks 5–9's "format as markdown" steps rather than a hard limit, since no tool here uses `fetch_all=True` by default.
- **Proportion check:** kept task bodies to signatures + one test each; no full function bodies transcribed except where the exact assertion shape matters.
