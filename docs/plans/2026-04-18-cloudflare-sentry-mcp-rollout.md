# Cloudflare MCP + Sentry MCP Rollout Plan

## Goal

Add two more MCP integrations to DeerFlow production:

- `Cloudflare MCP` for infrastructure, DNS, Workers, R2, Zero Trust, and Cloudflare operations
- `Sentry MCP` for coding/debugging workflows around errors, traces, issues, and performance

This document is a rollout plan only. It does **not** apply the integrations yet.

## Current DeerFlow Constraints

DeerFlow in this repo currently supports:

- `stdio` MCP servers
- `http` MCP servers
- `sse` MCP servers
- environment-variable expansion inside `extensions_config.json`

Production-specific constraints that matter here:

- DeerFlow currently exposes MCP config through the Gateway API.
- Secrets placed directly in MCP `headers` or inline `args` are more likely to leak through config inspection.
- The production containers already have `node`, `npm`, and `npx`, so local `stdio` wrappers are viable.
- The current production pattern already uses file-backed secrets in `.deploy/` for sensitive MCP credentials.

Because of that, the default rule for these two integrations should be:

- prefer `stdio` wrappers
- keep secrets in `.deploy/*`
- do not place long-lived tokens inline in `extensions_config.json`

## Recommended Architecture

### 1. Cloudflare MCP

Use the official Cloudflare **Cloudflare API MCP server** as the primary integration target.

Why:

- It gives broad coverage across the Cloudflare API.
- It uses `Codemode`, so it exposes a very small tool surface instead of thousands of endpoint-specific tools.
- This keeps DeerFlow's total MCP tool count under control.

Do **not** start with all product-specific Cloudflare MCP servers.

Reason:

- They dramatically increase tool count and overlap.
- DeerFlow already has other tools for browser work and web inspection.
- Adding too many Cloudflare MCPs at once will degrade tool routing quality.

Recommended initial scope:

- `cloudflare-api` only

Optional later expansions:

- `cloudflare-observability`
- `cloudflare-ai-gateway`
- `cloudflare-browser`

Recommended transport:

- `stdio` wrapper running `mcp-remote` against `https://mcp.cloudflare.com/mcp`

Why not direct `http` in DeerFlow first:

- Cloudflare's remote server is ideal with OAuth in interactive clients.
- DeerFlow production is a server-side runtime, not a human IDE session.
- Using bearer tokens in HTTP headers directly inside DeerFlow config is less safe than a wrapper script reading a file-backed token.

### 2. Sentry MCP

Use the official `@sentry/mcp-server` package in `stdio` mode.

Why:

- Official docs explicitly support `stdio`.
- It is the cleanest fit for DeerFlow's current production pattern.
- It avoids remote OAuth/browser complexity.

Recommended initial scope:

- enable core Sentry read/debug workflows first
- keep AI-powered Sentry search out of phase 1 unless we validate provider support

Important limitation:

- Official Sentry MCP docs state that AI-powered search tools need a supported LLM provider such as OpenAI or Anthropic.
- DeerFlow itself is routed through `9router`, but Sentry MCP's official docs do **not** clearly document custom OpenAI-compatible base URL support as the standard setup path.

Therefore the safe phase-1 plan is:

- install Sentry MCP without embedded AI search as a required dependency
- treat `search_events` / `search_issues` as optional phase-2 capability

## Final Recommendation

### Phase 1

Install:

- `cloudflare-api` via `mcp-remote` + bearer token file
- `sentry` via `npx @sentry/mcp-server@latest` + access token file

Do **not** add:

- Cloudflare product-specific MCP servers yet
- Sentry embedded AI search yet

### Phase 2

After phase-1 works in production:

- decide if Cloudflare needs one product-specific MCP for observability or AI Gateway
- decide if Sentry embedded AI search is worth enabling

## Security Decisions

### Cloudflare

Use a dedicated MCP token file:

- `.deploy/cloudflare_mcp_token`

Do not:

- hardcode bearer tokens in `extensions_config.json`
- put the token in the remote MCP URL

Preferred permission strategy:

- start with least-privilege Cloudflare API token
- if available, prefer read-oriented scopes for the first rollout
- add write scopes only when a real use case exists

### Sentry

Use a dedicated MCP token file:

- `.deploy/sentry_access_token`

Required scopes from official docs:

- `org:read`
- `project:read`
- `project:write`
- `team:read`
- `team:write`
- `event:write`

For phase 1, still treat the integration as operationally read-focused even if the official minimum scope set includes write scopes.

### Config Exposure Rule

For both integrations:

- secrets should only live in `.deploy/*` or `.env`
- wrappers should load the secret at runtime
- DeerFlow config should contain only command, args, env placeholders, and descriptions

## Tool Surface Strategy

### Why Cloudflare API MCP is preferred

Cloudflare's official API MCP uses a compact `search()` / `execute()` codemode pattern instead of exposing a massive endpoint catalog as MCP tools. That is a strong fit for DeerFlow because:

- it reduces context bloat
- it avoids flooding the agent with low-value tool schemas
- it preserves room for GitHub, Playwright, x-search, Tavily, Firecrawl, and Context7

### Why Sentry MCP is useful

Sentry MCP is naturally aligned with coding and debugging workflows:

- inspect issues
- inspect events
- inspect traces/performance
- understand regressions while coding

It is complementary to:

- GitHub MCP
- Context7
- Playwright

## Ordered Action Plan

### Step 1. Lock the exact scope

Decide that the first install will include only:

- `cloudflare-api`
- `sentry`

Explicitly defer:

- extra Cloudflare domain-specific MCPs
- Sentry AI-powered search mode

### Step 2. Prepare credentials

Create or confirm:

- a Cloudflare API token for MCP usage
- a Sentry user auth token with the required scopes

Store them as:

- `/home/blackbird/services/deerflow/.deploy/cloudflare_mcp_token`
- `/home/blackbird/services/deerflow/.deploy/sentry_access_token`

If we want to reuse existing machine credentials:

- Cloudflare may be sourced from the shared Cloudflare production runtime already configured on this machine
- Sentry should still get a dedicated token file for clarity and revocation

### Step 3. Add wrapper scripts

Add under `deploy/production/mcp/`:

- `run_cloudflare_mcp.sh`
- `run_sentry_mcp.sh`

Responsibilities:

- read token files
- fail fast with a clear error if missing
- launch the upstream MCP server without leaking secrets into DeerFlow config

Expected commands:

- Cloudflare:
  - `npx -y mcp-remote https://mcp.cloudflare.com/mcp --header "Authorization: Bearer ${TOKEN}"`
- Sentry:
  - `npx -y @sentry/mcp-server@latest`
  - pass `SENTRY_ACCESS_TOKEN` via environment

### Step 4. Update `extensions_config` template

Add two MCP entries to:

- `deploy/production/extensions_config.template.json`

Proposed names:

- `cloudflare-api`
- `sentry`

Use `stdio` entries only.

Do not inline raw tokens.

### Step 5. Update deploy script

Extend:

- `scripts/deploy_production.sh`

So that deploy:

- syncs the new wrapper scripts into `.deploy/`
- copies or hydrates secret files if needed
- sets executable permissions

### Step 6. Decide Sentry AI search policy

Choose one of two modes:

- `Mode A: Core only`
  - no embedded AI provider
  - simpler and safer first rollout
- `Mode B: Embedded AI search`
  - only after validating whether Sentry MCP supports our chosen provider setup cleanly in production

Recommendation:

- start with `Mode A`

### Step 7. Add agent guidance

Update or add custom DeerFlow agents so tool routing stays predictable.

Suggested usage rules:

- `cloudflare-api` only when the task is about DNS, Workers, R2, Zero Trust, AI Gateway, or Cloudflare configuration
- `sentry` only when the task is about production errors, incidents, regressions, traces, or debugging

This is important because DeerFlow already has:

- GitHub MCP
- Playwright MCP
- x-search MCP

### Step 8. Roll out on linux VM

Sync to:

- `/home/blackbird/services/deerflow/deploy/production/mcp/`
- `/home/blackbird/services/deerflow/config/extensions_config.json`

Then restart:

- `deerflow-gateway`
- `deerflow-langgraph`

### Step 9. Verify MCP load

Verify:

- DeerFlow config API shows both MCP servers enabled
- runtime MCP tool loader sees the new toolsets
- each wrapper launches cleanly

Minimum checks:

- list MCP config from Gateway
- list runtime MCP tools from `deerflow-langgraph`
- invoke one low-risk tool from Cloudflare MCP
- invoke one low-risk tool from Sentry MCP

### Step 10. Production smoke test

Run:

- `~/bin/prod-audit`

Then run one real-use workflow per MCP:

- Cloudflare:
  - read-only query first, such as searching API surface or reading a known config
- Sentry:
  - inspect a known issue/event in the target org/project

## Proposed File Changes When We Execute

Expected files to touch in the implementation phase:

- `deploy/production/extensions_config.template.json`
- `deploy/production/mcp/run_cloudflare_mcp.sh`
- `deploy/production/mcp/run_sentry_mcp.sh`
- `scripts/deploy_production.sh`
- `docs/production-deployment.md`

Optional:

- `deploy/production/app.env.example`
- custom agent config under `deploy/production/agents/`

## Risks

### 1. Secret leakage through config inspection

Mitigation:

- wrapper scripts
- file-backed secrets
- no inline headers/tokens in JSON

### 2. Too many tools

Mitigation:

- use only `cloudflare-api` first
- skip extra Cloudflare product MCPs in phase 1

### 3. Sentry embedded AI provider mismatch

Mitigation:

- do not require embedded AI search in phase 1
- validate separately before enabling

### 4. Write-capable infrastructure actions

Mitigation:

- least-privilege Cloudflare token
- staged rollout
- start with read-oriented validation tasks

## Execution Decision

If we execute this plan, the safest order is:

1. `Cloudflare API MCP`
2. `Sentry MCP core mode`
3. production verification
4. optional Sentry AI-search enablement
5. optional Cloudflare product-specific MCPs

## References

- Cloudflare managed MCP servers: `https://developers.cloudflare.com/agents/model-context-protocol/mcp-servers-for-cloudflare/`
- Cloudflare MCP repository: `https://github.com/cloudflare/mcp-server-cloudflare`
- Sentry MCP repository: `https://github.com/getsentry/sentry-mcp`
- Firecrawl MCP docs: `https://docs.firecrawl.dev/mcp-server`
- Tavily MCP docs: `https://docs.tavily.com/documentation/mcp`
- Context7 API keys: `https://context7.com/docs/howto/api-keys`
- DeerFlow MCP support in this repo:
  - `backend/packages/harness/deerflow/config/extensions_config.py`
  - `backend/packages/harness/deerflow/mcp/client.py`
  - `backend/docs/MCP_SERVER.md`
