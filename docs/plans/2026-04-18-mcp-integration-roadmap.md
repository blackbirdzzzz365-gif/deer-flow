# DeerFlow MCP Integration Roadmap

## Purpose

This document is the single rollout order for all MCP integrations we have discussed for DeerFlow.

It answers three things:

- what is already installed
- what should be integrated next, in what order, and why
- what information the user must provide once so Codex can finish the remaining rollout end-to-end

This is a planning and execution guide. It does not itself apply the changes.

## Approved Scope For This Rollout

The rollout approved on `2026-04-18` is:

- keep `GitHub MCP` unchanged
- keep `Playwright MCP` as baseline
- keep `x-search MCP` as baseline
- add `Context7 MCP`
- add `Tavily MCP`
- add `Firecrawl MCP`
- add `Cloudflare API MCP` with shared credentials and write-capable token scope
- do not add `Sentry MCP` in this rollout
- seed both `coding-pro` and `research-pro`

The required inputs for this approved scope were already provided, so no further credential questions are needed before execution.

## Current Truth

### Already live in production

DeerFlow production currently has these MCP servers working:

- `github`
- `playwright`
- `x-search`

Current production health is good and `x-search` has already been tested successfully against the xAI endpoint.

### Already discussed but not yet installed

Research-oriented MCPs:

- `Tavily MCP`
- `Firecrawl MCP`

Coding-oriented MCPs:

- `Context7 MCP`

Ops / debugging MCPs:

- `Cloudflare API MCP`

## Target MCP Portfolio

This is the MCP portfolio DeerFlow should ultimately have after the rollout is complete.

### Foundational baseline MCPs

These are not optional for the production profile we are building:

- `GitHub MCP`
- `Playwright MCP`
- `x-search MCP`

### Coding and research MCPs to add next

- `Context7 MCP`
- `Tavily MCP`
- `Firecrawl MCP`

### Ops and debugging MCPs to add later

- `Cloudflare API MCP`
- `Sentry MCP` (deferred, not part of the approved scope)

## Playwright MCP Position

`Playwright MCP` should be treated as a first-class baseline MCP, not just an implementation detail that happens to be live already.

Why it belongs in the target setup list:

- it is the browser automation layer for real UI validation
- it complements `Tavily` and `Firecrawl` instead of replacing them
- it is already proven stable in DeerFlow production
- it requires no additional vendor secret in the current setup pattern

Functional role in the stack:

- `Tavily` finds sources
- `Firecrawl` extracts and crawls pages
- `Playwright` validates real browser behavior, login flows, DOM state, and final UI outcomes

Because of that, any future "full MCP setup" for DeerFlow should explicitly include `Playwright MCP` in the baseline install set.

## Design Principles

These decisions drive the rollout order.

### 1. Prefer highest-value, lowest-risk integrations first

We should add the MCPs that immediately improve coding and research quality without exposing infrastructure or incident-response write paths too early.

### 2. Avoid tool overload

Every MCP adds tool schemas and routing complexity.

So the rollout should:

- start with compact, high-signal MCPs
- delay overlapping or heavier toolsets
- avoid enabling multiple MCPs that solve the same problem at once without routing rules

### 3. Keep secrets out of DeerFlow MCP config

DeerFlow currently exposes MCP config through the Gateway API. Because of that:

- never place long-lived tokens directly in `extensions_config.json`
- store secrets in `.deploy/*` or dedicated env files
- launch MCPs through wrapper scripts that read token files at runtime

### 4. Prefer `stdio` wrappers in DeerFlow production

Even when a vendor offers remote HTTP/OAuth MCPs, DeerFlow production is a server-side runtime, not an interactive IDE. The safest pattern for this stack is:

- wrapper script
- file-backed secret
- `stdio` transport

## Recommended Rollout Order

## Phase 0. Keep the current baseline stable

Do not change the current working MCP baseline until the next integrations are introduced one at a time.

Baseline to preserve:

- GitHub MCP
- Playwright MCP
- x-search MCP

Required checks before every new phase:

- DeerFlow local health
- DeerFlow public health
- MCP tool loader still initializes correctly
- `~/bin/prod-audit` stays clean after rollout

## Phase 1. Harden the existing coding baseline

### Step 1.1. Keep GitHub MCP but review its access model

GitHub MCP is already live. It should not be treated as a new install item.

What we should do instead:

- confirm whether write actions should remain enabled
- optionally move to a more conservative token scope if the app remains broadly accessible
- keep the current wrapper/token-file pattern

Why first:

- it is already in production
- it has the highest blast radius among current MCPs
- this is a stabilization step, not a feature step

### Step 1.2. Add Context7 MCP

This is the best next MCP for coding quality.

Why it should come before research MCPs:

- high value for coding and docs lookup
- narrow scope
- low operational risk
- low overlap with existing tools

Target outcome:

- DeerFlow can resolve library IDs and fetch up-to-date library docs during coding tasks

Preferred transport:

- `stdio` via `npx -y @upstash/context7-mcp`
- wrapper script reading `.deploy/context7_api_key`

### Step 1.3. Keep Playwright MCP as mandatory baseline

`Playwright MCP` is already live, so this is not a new install step in the current production environment.

But it **is** part of the official setup list for DeerFlow and should remain mandatory in:

- any fresh production bootstrap
- any environment clone
- any future production rebuild

Why it stays in the baseline:

- it provides deterministic browser automation
- it is useful for coding, QA, and research verification
- it gives DeerFlow a direct way to validate what `Tavily` or `Firecrawl` found
- it does not introduce a new secret source in the current production model

## Phase 2. Add lightweight research discovery

### Step 2.1. Add Tavily MCP

Tavily should be the first new research MCP.

Why before Firecrawl:

- better starting point for discovery and citation-oriented search
- lower overlap with current stack
- less expensive / less heavy than deep crawl workflows

Target outcome:

- DeerFlow can quickly discover sources, links, and research leads before deciding to crawl deeply

Preferred transport:

- `stdio` wrapper using Tavily MCP package
- secret in `.deploy/tavily_api_key`

Important note:

- Tavily also supports remote MCP and OAuth-friendly setups
- for DeerFlow production, stick to the local wrapper pattern unless we deliberately redesign auth handling

## Phase 3. Add heavy extraction only after Tavily works

### Step 3.1. Add Firecrawl MCP

Firecrawl should come after Tavily, not before.

Why:

- Tavily handles source discovery better as a first-pass search layer
- Firecrawl is better for extraction, crawl, map, and structured site processing
- if both are added together too early, tool routing gets noisier

Target outcome:

- DeerFlow uses Tavily to discover sources
- DeerFlow uses Firecrawl only when deeper extraction or crawling is needed

Preferred transport:

- `stdio` wrapper using `npx -y firecrawl-mcp`
- secret in `.deploy/firecrawl_api_key`
- optional `.deploy/firecrawl_api_url` if self-hosted Firecrawl is used

## Phase 4. Add infrastructure control after coding/research are stable

### Step 4.1. Add Cloudflare API MCP

Cloudflare should come after Context7, Tavily, and Firecrawl.

Why:

- infrastructure tooling has a higher blast radius than coding/research tooling
- Cloudflare API MCP can perform real account actions
- it belongs after the low-risk, high-value developer MCPs are stable

Use only:

- `cloudflare-api`

Do not start with:

- the whole Cloudflare product-specific catalog

Why:

- the Cloudflare API MCP already covers broad needs
- it uses Codemode and keeps tool surface compact
- product-specific MCPs can be added later if there is a concrete recurring use case

Preferred transport:

- `stdio` wrapper running `mcp-remote` to `https://mcp.cloudflare.com/mcp`
- token stored in `.deploy/cloudflare_mcp_token`

## Phase 5. Add optional expansions only after the approved scope is stable

Only after Phases 1-4 are done and verified should we consider:

- Cloudflare product-specific MCPs such as observability or AI Gateway
- Sentry MCP in core mode
- Sentry embedded AI search
- custom routing rules / agent prompts that deliberately prefer one MCP over another
- splitting GitHub into read-only vs write-enabled profiles if needed

## Final Ordered List

This is the practical order to implement:

1. Keep `GitHub MCP` unchanged and verified
2. Keep `Playwright MCP` in the mandatory baseline
3. Keep `x-search MCP` in the mandatory baseline
4. Add `Context7 MCP`
5. Add `Tavily MCP`
6. Add `Firecrawl MCP`
7. Add `Cloudflare API MCP`
8. Seed `coding-pro` and `research-pro`
9. Add optional expansions only after the approved scope above is stable

## Fresh Bootstrap Order

If DeerFlow had to be set up from zero on a new environment, the bootstrap order should be:

1. `GitHub MCP`
2. `Playwright MCP`
3. `x-search MCP`
4. `Context7 MCP`
5. `Tavily MCP`
6. `Firecrawl MCP`
7. `Cloudflare API MCP`
8. `coding-pro` and `research-pro`
9. `Sentry MCP` if explicitly requested later

## Why This Order Is Correct

### Context7 before Tavily / Firecrawl

Because coding quality gains come faster and safer from documentation retrieval than from adding more research surface area.

### Playwright stays before the rest of the new rollout

Because Playwright is already the stable browser automation baseline and should be preserved as part of every future MCP setup for DeerFlow.

It is not "next to be installed" on the current production stack, but it is absolutely part of the intended target setup.

### Tavily before Firecrawl

Because discovery should come before deep extraction.

Tavily:

- source finding
- citation-oriented search
- fast lead generation

Firecrawl:

- extraction
- crawl
- map
- structured processing

### Cloudflare after coding + research MCPs

Because Cloudflare introduces infrastructure write potential and should only be added after the developer-assistance MCPs are stable.

### Sentry is deferred

Because it was explicitly taken out of the approved scope for this rollout. It stays as a later optional expansion.

## Concrete Implementation Pattern

Every new MCP from now on should follow the same production pattern.

### File layout

Wrapper scripts go under:

- `deploy/production/mcp/`

Secrets go under:

- `/home/blackbird/services/deerflow/.deploy/`

Template wiring goes in:

- `deploy/production/extensions_config.template.json`
- `scripts/deploy_production.sh`
- `docs/production-deployment.md`

### Wrapper pattern

Each MCP gets:

- one wrapper shell script
- one token file or env-backed secret source

Wrapper responsibilities:

- load secret
- validate secret exists
- launch MCP cleanly
- fail with a short explicit error if the secret is missing

### Verification pattern

Each MCP phase should finish with:

1. `GET /api/mcp/config` shows the new server
2. runtime MCP tool loader sees the expected tool names
3. one real tool invocation succeeds
4. DeerFlow health stays green
5. `~/bin/prod-audit` returns clean

## Approved Inputs Already Received

The approved scope now has all required inputs:

- `GitHub MCP`: keep current policy unchanged
- `Playwright MCP`: keep current official server
- `x-search MCP`: already live
- `Context7 API key`: provided
- `Tavily API key`: provided
- `Firecrawl API key`: provided
- `Cloudflare`: reuse shared production credentials
- `Cloudflare mode`: `allow writes`
- `Sentry`: explicitly excluded from this rollout
- `coding-pro`: approved
- `research-pro`: approved

No further user input is required before execution for the approved scope above.
4. For Firecrawl, are we using Firecrawl Cloud or a self-hosted instance?
5. Do you want me to create new production agents such as:
   - `coding-pro`
   - `research-pro`

## Minimal Input Package

If you want the shortest possible handoff, send me this bundle:

1. `Context7 API key`
2. `Tavily API key`
3. `Firecrawl API key`
4. `Cloudflare token strategy`
   - either: "reuse shared Cloudflare credentials"
   - or: dedicated token value
5. `Cloudflare mode`
   - `read-mostly` or `allow writes`
6. `Sentry user auth token`
7. optional `SENTRY_HOST` if self-hosted
8. `one Sentry issue URL` or `org/project` for verification
9. `GitHub policy`
   - keep write-enabled
   - or harden to safer scope
10. whether to keep the current official `Playwright MCP` as the standard browser baseline
11. whether to create `coding-pro` and `research-pro` agents

After that, I can do the rest.

## Definition of Done

This rollout is complete only when:

- all chosen MCPs are present in DeerFlow config
- each MCP has a file-backed secret strategy
- each MCP has a wrapper script in `deploy/production/mcp/`
- each MCP can be invoked successfully in production
- DeerFlow public health remains clean
- `~/bin/prod-audit` returns `0 failure(s), 0 warning(s)`
- docs are updated to reflect the new production truth

## Related Docs

- [docs/production-deployment.md](/Users/nguyenquocthong/project/2-deer-flow/docs/production-deployment.md)
- [docs/plans/2026-04-18-cloudflare-sentry-mcp-rollout.md](/Users/nguyenquocthong/project/2-deer-flow/docs/plans/2026-04-18-cloudflare-sentry-mcp-rollout.md)
