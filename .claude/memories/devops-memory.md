# DevOps — Memory

Read at session start. Apply silently.

## Safety and scope
<!-- 2026-05-13 -->
- Never act on repositories outside the current project scope; treat other repos as off-limits unless explicitly assigned.
- Always verify no checks are failing in a PR or merge before proceeding.

## Docker
<!-- 2026-05-14 -->
- Docker named volumes isolate container DB from local dev DB — bind-mount or copy on first deploy.
- When Docker Desktop Linux engine pipe disappears mid-operation: kill all Docker processes, restart Desktop, wait for pipe before retrying.

## Deployment automation
<!-- 2026-05-14 -->
- When triggered after PR merge, execute deployment pipeline immediately — no user confirmation needed unless explicitly gated.

## PR self-assessment
<!-- 2026-05-14 -->
- When a PR opens, self-assess: does it touch infra, pipelines, Dockerfiles, or deployment config? If yes → review and sign off. If no → explicitly state "No DevOps review needed" to Reviewer.

## Budget-bot project
<!-- 2026-06-16 -->
- Hosting: Oracle Cloud Free Tier VM (Ampere A1 ARM) + systemd service + Cloudflare R2 (S3-compatible, STORAGE_BACKEND=s3).
- GitHub Actions runs scheduled_report.py only — not the interactive bot (long-polling incompatible with Actions).
- Deploy flow: git pull on VM → systemctl restart budget-bot. No CI/CD pipeline needed.
- Excel file lives in Cloudflare R2; both VM and GitHub Actions share the same bucket via S3 env vars.
