# Tooling — Universal Technical Rules

Applied to every role, every session.
Read this file on every activation alongside `writing-style.md` and `conduct.md`.

---

## Web search

All roles have access to WebSearch and WebFetch. Use them — do not guess when you can verify.

**Search when:**
- A library version, API signature, or method behaviour is needed and not in context
- An error message needs diagnosis — include the exact error text in the query
- Citing a technology standard, spec, or best practice — verify it is current before stating it
- Something was likely released or changed after the knowledge cutoff
- "I'm not sure about this" — search rather than produce a plausible-sounding answer

**How to search:**
- Include the technology name, version if known, and the specific question
- Prefer official documentation over blog posts
- If a result is more than 2 years old, look for a more recent source
- For role-specific sources and query patterns, read `.claude/memories/web-search-sources.md`

**Never state a technology standard, library API, or external spec from memory alone without verifying.** Memory can be outdated or wrong. Search first, then state.

## Implementation — read before write

Before writing any new file (code, script, pipeline, config, test), read the existing equivalent in the codebase first. Do not generate from scratch.

- If adding a pipeline: read the canonical equivalent pipeline in the same project
- If adding a script: read an adjacent existing script for naming, invocation, and style patterns
- If adding a class, component, or step definition: read the nearest equivalent implementation

Generating without reading produces improvised code that diverges from established patterns and requires multiple correction rounds.

## API pagination

- When querying any paginated API (GitHub GraphQL or REST), always check `pageInfo.hasNextPage` / `endCursor` (GraphQL) or `Link: rel="next"` (REST) and fetch every subsequent page before concluding a result is absent or a list is complete. Never report "nothing found" after a capped first page.
