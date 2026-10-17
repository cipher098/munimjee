# Isolated V1 API and storefront image

This is a local packaging proof, not a deployment. It adds a dedicated `deploy/v1/Dockerfile` and two build/smoke commands. Existing `backend/Dockerfile`, compose services, deployed processes, databases, images and volumes are unchanged.

From the repository root:

```sh
python3 scripts/v1_runtime_package.py build --tag munimjee-v1-runtime:your-unique-local-tag
python3 scripts/smoke_v1_runtime.py --image munimjee-v1-runtime:your-unique-local-tag
```

The builder refuses an existing image tag. It creates and removes its own temporary context; it never sends the repository root to Docker and does not depend on a shared `.dockerignore`. Build constraints are one CPU and 1,536 MiB using the legacy Docker builder, with a 15-minute timeout. The legacy builder is currently available on the verified Docker 29.7.2 host but deprecated; a host that removes it needs an explicitly resource-limited BuildKit builder before this command can claim the same limit. No daemon configuration is changed.

The context contains tracked production Python modules (excluding app/scripts and backups), the two application YAML configuration files, Alembic migrations/configuration, 30 explicitly named existing static pages/modules/styles and exactly 11 operational storefront modules. New storefront or seller static dependencies must be explicitly added to these lists and to the shared bootstrap contract when needed. Fixture entrypoints, fixtures, tests, node_modules, artifacts, design files, uploads, environment files and key files do not enter the context. Symlinks, including a symlinked requirements file, fail closed. Dependency lines must be pinned index package requirements; URLs, options, nested files and local packages are rejected. Existing direct versions are retained while pytest, pytest-asyncio and vcrpy are omitted from this API runtime image. Test/smoke code is supplied only on stdin and is not packaged.

The image uses Python 3.11 slim, binary wheels, no compiler/system-package installation, and UID/GID 10001. It contains API code, migrations, static web files and storefront modules at `/opt/munimjee/storefront-src`; `V1_STOREFRONT_ASSETS_DIR` points there. Credentials and DATABASE_URL are not build arguments or image environment settings. The existing application creates empty upload directories at startup; no source uploads or customer files are copied. Operational upload persistence remains a separate runtime decision.

The default storefront flag stays off. Explicit enabling still requires a configured canonical `PUBLIC_BASE_URL` and a complete runtime module directory. Origin never derives from Host. Existing DB migration execution, credentials, worker/queue configuration and upload persistence are not run or supplied by this packaging command. The image has a normal uvicorn CMD, but the verified smoke uses actual app.main through TestClient and never starts an external service.

Smoke creates a uniquely named container with `--network none`, one CPU, 768 MiB, PID limit 256, read-only filesystem, dropped capabilities and no-new-privileges. Only /tmp and empty uploads use bounded ephemeral tmpfs. Synthetic credentials and unusable loopback DB/Redis URLs are passed at runtime. Python additionally rejects/counts DNS and IP connection attempts before importing the app. Three fresh processes prove:

- Default-off startup works with no canonical origin and a deliberately missing asset path; health is available and storefront paths are absent.
- Explicit canonical enabling serves actual JS/CSS and the private no-store/noindex order shell. Test, fixture, package, node_modules, environment and key paths return 404. No public product page or authenticated DB endpoint is called.
- An enabled missing runtime refuses startup.

The smoke compares the image's manifest to the current allowlisted source files, verifies their SHA256 hashes inside the runtime, verifies no customer upload files exist and removes only its own container in a finally block. A failed or interrupted Docker daemon may still need inspection of that uniquely named container; the script does not prune or delete any existing resource. Registry/package downloads occur during build only; the verified smoke has no network, database or provider calls. Source/path exclusion and synthetic sentinels establish which files were packaged; they are not a claim that every application source literal is independently secret-scanned.

Verification on 18 October 2026: seven pure package tests passed, and all three image smoke modes passed with zero DNS/network attempts. Image `munimjee-v1-runtime:local-20261018-c20-530f7e3` has ID `sha256:31fb58e1b9d5fb3825fe7dc6bd3ee2aec8d3b5ac72006c44d498316000d8c597`, Docker-reported size 129,634,098 bytes (123.6 MiB), Linux arm64, runtime UID/GID 10001. Docker received a 1.767 MB context with 233 files. The base resolved to `python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`. The source revision was integration `530f7e3`; per-file hashes identify the exact runtime independently of later packaging-script commits. The base tag and existing transitive dependency ranges are not a reproducible dependency lock.

Evidence: `artifacts/v1/runtime-package/image-verification.json` and `runtime-manifest.json`. The first smoke exposed an incorrect test assumption that uploads contained no subdirectories; existing route imports create empty directories. The corrected assertion rejects files and passes. No existing image/container/volume was removed or pruned. Temporary contexts and smoke containers were removed; the uniquely tagged image is retained for review. Build failure/resource exhaustion must be reported rather than triggering cleanup of unrelated resources.

Production deployment, live provider/customer sends, migrations against a real database, CI publication and multi-architecture certification remain outside this proof. The image closes the local runtime asset packaging gap only.
