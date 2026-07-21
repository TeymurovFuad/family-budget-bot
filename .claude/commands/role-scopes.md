# Role Scopes

Single source of truth for what each role handles.
Read this file to verify routing (Orchestrator) or scope (role direct invocation).

| Role | In scope | Route |
|---|---|---|
| Architect | System design, ADRs, patterns, NFRs, service boundaries, technology selection, cross-cutting concerns | `/architect` |
| Designer | UX research, user flows, wireframes, component specs, design tokens, accessibility specs | `/designer` |
| Developer | Production features, bug fixes, unit tests (TDD for own code), service classes, APIs, domain logic | `/developer` |
| Tester | E2E test automation, page objects, step definitions, BDD/Reqnroll scenarios, performance/accessibility/visual tests, test verification | `/tester` |
| Reviewer | PR diff review, code quality, architecture compliance within a PR | `/reviewer` |
| DevOps | CI/CD pipelines, deployment scripts, infrastructure as code, monitoring, release management | `/devops` |
| Technical Writer | Feature docs, API docs, workflow docs, domain docs, infra docs, ADR writeups | `/technical-writer` |
| Product Owner | AC definition, story writing, backlog priority by value, accept/reject delivered features | `/product-owner` |
| Engineering Manager | Delivery tracking, ticket lifecycle, capacity, retros, blockers, backlog mechanics, memory governance | `/engineering-manager` |
