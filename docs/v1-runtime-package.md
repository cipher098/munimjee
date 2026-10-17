# Isolated V1 API and storefront image

This is a local packaging proof, not a deployment. It adds a dedicated `deploy/v1/Dockerfile` and two build/smoke commands. Existing `backend/Dockerfile`, compose services, deployed processes, databases, images and volumes are unchanged.

From the repository root:

```sh
python3 scripts/v1_runtime_package.py build --tag munimjee-v1-runtime:your-unique-local-tag
python3 scripts/smoke_v1_runtime.py --image munimjee-v1-runtime:your-unique-local-tag
```

The builder refuses an existing image tag. It creates and removes its own temporary context; it never sends the repository root to Docker and does not depend on a shared `.dockerignore`. Build constraints are one CPU and 1,536 MiB using the legacy Docker builder, with a 15-minute timeout. The legacy builder is currently available on the verified Docker 29.7.2 host but deprecated; a host that removes it needs an explicitly resource-limited BuildKit builder before this command can claim the same limit. No daemon configuration is changed.

The context contains tracked production Python modules (excluding app/scripts and backups), the two application YAML configuration files, Alembic migrations/configuration, 39 explicitly named static pages/modules/styles/scanner assets and exactly 12 operational storefront modules. New storefront or seller static dependencies must be explicitly added to these lists and to the shared bootstrap contract when needed. Fixture entrypoints, fixtures, tests, node_modules, artifacts, design files, uploads, environment files and key files do not enter the context. Symlinks, including a symlinked requirements file, fail closed. Dependency lines must be pinned index package requirements; URLs, options, nested files and local packages are rejected. Existing direct versions are retained while pytest, pytest-asyncio and vcrpy are omitted from this API runtime image. Test/smoke code is supplied only on stdin and is not packaged.

The image uses Python 3.11 slim, binary wheels, no compiler/system-package installation, and UID/GID 10001. It contains API code, migrations, static web files and storefront modules at `/opt/munimjee/storefront-src`; `V1_STOREFRONT_ASSETS_DIR` points there. Credentials and DATABASE_URL are not build arguments or image environment settings. The existing application creates empty upload directories at startup; no source uploads or customer files are copied. Operational upload persistence remains a separate runtime decision.

The default storefront flag stays off. Explicit enabling still requires a configured canonical `PUBLIC_BASE_URL` and a complete runtime module directory. Origin never derives from Host. Existing DB migration execution, credentials, worker/queue configuration and upload persistence are not run or supplied by this packaging command. The image has a normal uvicorn CMD, but the verified smoke uses actual app.main through TestClient and never starts an external service.

Smoke creates a uniquely named container with `--network none`, one CPU, 768 MiB, PID limit 256, read-only filesystem, dropped capabilities and no-new-privileges. Only /tmp and empty uploads use bounded ephemeral tmpfs. Synthetic credentials and unusable loopback DB/Redis URLs are passed at runtime. Python additionally rejects/counts DNS and IP connection attempts before importing the app. Three fresh processes prove:

- Default-off startup works with no canonical origin and a deliberately missing asset path; health is available and storefront paths are absent.
- Explicit canonical enabling serves actual JS/CSS and the private no-store/noindex order shell. Test, fixture, package, node_modules, environment and key paths return 404. No public product page or authenticated DB endpoint is called.
- An enabled missing runtime refuses startup.

The smoke compares the image's manifest to the current allowlisted source files, verifies their SHA256 hashes inside the runtime, verifies no customer upload files exist and removes only the container ID written by Docker into its fresh CID file in a finally block, then verifies removal; a failed create/name collision cannot target an existing named container. A failed or interrupted Docker daemon may still need inspection of that uniquely named container; the script does not prune or delete any existing resource. Registry/package downloads occur during build only; the verified smoke has no network, database or provider calls. Source/path exclusion and synthetic sentinels establish which files were packaged; they are not a claim that every application source literal is independently secret-scanned.

Verification on 18 October 2026: ten pure package tests passed, and all three image smoke modes passed with zero DNS/network attempts. Image `munimjee-v1-runtime:local-20261018-c20-530f7e3` has ID `sha256:31fb58e1b9d5fb3825fe7dc6bd3ee2aec8d3b5ac72006c44d498316000d8c597`, Docker-reported size 129,634,098 bytes (123.6 MiB), Linux arm64, runtime UID/GID 10001. Docker received a 1.767 MB context with 233 files. The base resolved to `python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`. The source revision was integration `530f7e3`; per-file hashes identify the exact runtime independently of later packaging-script commits. The base tag and existing transitive dependency ranges are not a reproducible dependency lock.

Evidence: `artifacts/v1/runtime-package/image-verification.json` and `runtime-manifest.json`. The first smoke exposed an incorrect test assumption that uploads contained no subdirectories; existing route imports create empty directories. The corrected assertion rejects files and passes. No existing image/container/volume was removed or pruned. Temporary contexts and smoke containers were removed; the uniquely tagged image is retained for review. Build failure/resource exhaustion must be reported rather than triggering cleanup of unrelated resources.

Production deployment, live provider/customer sends, migrations against a real database, CI publication and multi-architecture certification remain outside this proof. The image closes the local runtime asset packaging gap only.

## Independent integrated artifact

The integrator reviewed the allowlist, symlink checks, pinned-index dependency guard, runtime mount, network restrictions and CID-only cleanup, with no substantive blocker. All **10 pure package tests** passed independently. A second uniquely tagged image was built from integration source `d2b73a9` (application code tested through `7675f36`): `munimjee-v1-runtime:local-20261018-integration-7675f36`, ID `sha256:040c2625ed60a24f2dce2cabd1229da85fbe58afedeed59f00c98245b81f5b02`, Docker-reported **129636999 bytes**, arm64, UID/GID **10001:10001**. It contains the final native draft-recovery assets. The final CID cleanup script reran all three offline smoke modes successfully against it; file/manifest hashes match, no DNS/network/DB attempt occurred and the created container was verified absent. Runtime files did not change in the later cleanup/test/documentation commits, so the image was not rebuilt for those changes.

Integration evidence is recorded separately in `artifacts/v1/runtime-package/integration-image-verification.json`, `integration-runtime-manifest.json` and `integration-smoke.txt`. The earlier author image/source proof remains intact. Both uniquely tagged local images are retained; no existing image/container/volume was pruned. This closes local packaging only, with deployment, real data migrations, provider acceptance and other release gates still pending.

## Wave3 integrated package

The new image `munimjee-v1-runtime:local-20261018-wave3-dd44d89` is built from
committed source `dd44d89f0b447423508682f995f1fc68af8c109b`. Its ID is
`sha256:5b3e18ee109cf4228464857c9bf715f1c6e5517ba37100e9832828d4edc4f01b`,
Docker-reported size **130113314 bytes**, arm64, UID/GID **10001:10001**. The
allowlist now includes **258 files**, including **39 explicit static files**
(parcel scanner JS/WASM/license included) and **12 storefront runtime modules**
(payment handoff included). Context files total 2,752,422 bytes; Docker reported
a 2.959 MB transfer. The earlier 233-file image remains a wave2 snapshot.

Ten pure package checks passed. All three offline modes passed on this image,
including exact current-context/image manifest equality and every runtime file's
SHA256. The enabled mode verifies the payment module and parcel scanner/WASM/
license are served, while fixture/test/key paths stay absent. No DNS, network,
DB or provider attempt occurred. The created CID was removed and verified absent;
no smoke container remains. Evidence is `artifacts/v1/runtime-package/wave3-final-*`.
No image push/deployment, worker/provider canary, persistent upload provisioning,
restore rehearsal or multi-architecture/CI certification is implied.

The earlier wave3 `af6c3e4` image/manifest is retained separately as an interim
checkpoint. It predates the final import-session transaction guard and is not
the current source artifact. No existing image was overwritten or pruned.
