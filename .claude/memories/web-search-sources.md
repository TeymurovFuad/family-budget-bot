# Web Search Sources

Role-specific search guidance. Read this when you need to search the internet — it tells you what to search for and where.

---

## Universal search triggers (all roles)

Search the internet when:
- A library, framework, or tool version is needed and not in context
- An error message or exception needs diagnosis
- A technology standard, spec, or RFC is being cited — verify it is current
- A best practice is being recommended — verify it is still considered best practice
- "I'm not sure about this" — search rather than guess
- The user asks about something released after your knowledge cutoff

**Query formulation:**
- Be specific: include the technology name, version if known, and the exact problem
- Prefer official docs over blog posts
- If a result is older than 2 years, look for a more recent source

---

## Developer

**Search when:**
- Unfamiliar API, method signature, or return type
- Compiler/runtime error message — include exact error text in query
- Library version compatibility check
- "Is X the right way to do Y in [framework]?"

**Preferred sources (in order):**
1. Official documentation (e.g. docs.microsoft.com, learn.microsoft.com, kotlinlang.org)
2. GitHub repository README / releases
3. NuGet / npm / PyPI package page
4. Stack Overflow — filter to accepted answers on questions with high votes
5. MDN Web Docs (for web/JS)

**Query patterns:**
- `[technology] [method/class] [version] documentation`
- `[error message] [framework] [language] fix`
- `[concept] best practice [framework] [year]`

---

## Reviewer

**Search when:**
- Citing a technology standard (e.g. "this violates REST", "SOLID principle X") — verify the definition
- Checking whether a security pattern is still recommended
- Verifying a language or framework convention

**Required:** Verify technology-specific standards against official docs before citing — never rely on memory alone.

**Preferred sources:**
1. Official language/framework documentation
2. OWASP (security)
3. RFC index (rfc-editor.org) for protocol standards
4. NIST (security standards)

---

## Tester

**Search when:**
- OWASP vulnerability class definition needed
- WCAG accessibility criterion needs clarification
- Framework-specific test API reference needed
- Security test pattern for a specific vulnerability type

**Preferred sources:**
1. owasp.org — security testing guide, top 10
2. w3.org/WAI — WCAG guidelines
3. Official test framework docs (e.g. NUnit, xUnit, pytest)
4. MDN — browser/web standards

---

## Architect

**Search when:**
- Design pattern definition needed (Gang of Four, CQRS, Event Sourcing, etc.)
- Cloud provider service capability comparison
- RFC or protocol specification needed
- "Is this architectural approach still considered best practice?"

**Preferred sources:**
1. martinfowler.com — patterns, architecture articles
2. Official cloud provider docs (AWS, Azure, GCP)
3. RFC editor (rfc-editor.org)
4. CNCF landscape (cloud-native patterns)
5. Microsoft Architecture Center (learn.microsoft.com/azure/architecture)

---

## DevOps

**Search when:**
- Provider-specific YAML syntax or config option
- Version compatibility between tools (e.g. GitHub Actions runner, Docker, Kubernetes)
- Pipeline best practice for a specific provider
- Security hardening for infrastructure components

**Preferred sources:**
1. Official provider docs (docs.github.com, docs.aws.amazon.com, azure.microsoft.com)
2. Docker Hub official image docs
3. Kubernetes documentation (kubernetes.io)
4. HashiCorp docs (for Terraform/Vault)

---

## Designer

**Search when:**
- UX pattern for a specific interaction type
- Accessibility colour contrast requirements
- Platform-specific design conventions (iOS HIG, Material Design)
- Component specification from a design system

**Preferred sources:**
1. Nielsen Norman Group (nngroup.com) — UX research and patterns
2. Material Design guidelines (m3.material.io)
3. Apple Human Interface Guidelines (developer.apple.com/design)
4. W3C WAI — accessibility guidelines
5. Smashing Magazine — practical UX articles

---

## Technical Writer

**Search when:**
- Mermaid diagram syntax for a specific chart type
- OpenAPI/Swagger specification syntax
- Markdown extension support in a specific platform
- Documentation tool configuration

**Preferred sources:**
1. mermaid.js.org — diagram syntax reference
2. swagger.io/specification — OpenAPI spec
3. docs.github.com — GitHub Flavored Markdown
4. mkdocs.org / docusaurus.io — docs tool references

---

## Engineering Manager

**Search when:**
- DORA metrics definition or benchmark data
- Agile/Scrum ceremony format
- Team health framework or model
- Industry benchmark for delivery cadence

**Preferred sources:**
1. dora.dev — DORA metrics and research
2. Agile Alliance (agilealliance.org)
3. Scrum.org — Scrum guide
4. SPACE framework (GitHub research)

---

## Product Owner

**Search when:**
- Competitor feature comparison needed
- Industry standard for a product category
- User research methodology
- Acceptance criteria pattern for a specific domain

**Preferred sources:**
1. ProductPlan / Productboard blogs — product management practices
2. Nielsen Norman Group — user research
3. Competitor product pages / changelogs
4. Industry analyst reports (Gartner, Forrester — summaries only)
