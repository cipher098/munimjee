# V1 execution status

Updated: 17 October 2026. Coordinator branch: `codex/v1-integration`. Source baseline: `035b5da`; preserved application baseline: `e7694ff`.

## Active ownership

| Worker | Host | Branch | Current scope | State |
| --- | --- | --- | --- | --- |
| identity-onboarding | This Mac | codex/v1-identity | Additive tenant/user/membership bridge and versioned read APIs | Implementing |
| catalogue-commerce | This Mac | codex/v1-catalogue | SKU foundation, review rules, catalogue contracts | Implementing |
| social-automation | This Mac | codex/v1-social | Durable Instagram ingress and recovery | Implementing |
| qa-isolation | Mac mini dev | codex/v1-test-isolation | Fail-closed DB fixtures, isolated runner, CI | Implementing |
| imports | Mac mini dev | assigned by remote coordinator | Draft import/review logic and contract tests | Dispatch requested |
| storefront | Mac mini dev | assigned by remote coordinator | Three-theme preview scaffold and component contracts | Dispatch requested |

All new workers use GPT-6.1 Sol with high reasoning as requested. This does not change the current coordinating chat model. No implementation is yet release-ready.

## Preparation evidence

- P00: runtime and source checkout changes preserved privately, and relevant app changes copied into an isolated integration worktree. Existing running checkout, main/v0.1 branches and demos are untouched. Runtime-only model reports, local OS files and nested worktrees are excluded from the integration commit.
- P01: local disposable PostgreSQL 15 and Redis 7 containers created on a dedicated Docker network, loopback ports 55441/56441, separate credentials and temporary storage. Existing sellerbot containers are unchanged. Safe test harness work is pending. PostgreSQL 16 CI parity remains required.
- P02: initial decisions recorded in v1-contract-decisions.md; each lane owns separate files, integrator owns startup registration/migration order.
- P03: current provider permission status and courier selection remain unverified. No production credentials copied or live provider actions taken.
- Mac mini: empty project verified, GitHub access verified, Python/Node available. Docker queries time out; approximately 11 GiB disk free. Parallel pure-code and frontend work is allowed; local Docker supplies database verification until remote resources improve.

## Evidence and release state

Record exact commit and commands for each result. Skips and provider-dependent checks remain pending. The next gate is isolated baseline tests and reviewed foundation migrations. Browser checks of preview scaffolding do not count as complete checkout or seller onboarding. No production deployment is authorized or performed.
