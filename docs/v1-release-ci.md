# Bounded V1 CI and package release checks

**Hosted execution blocked:** fixed workflow run
<https://github.com/cipher098/munimjee/actions/runs/39105879610> created four jobs,
but none executed any step. GitHub's exact check annotation says:
“The job was not started because your account is locked due to a billing issue.”
No retry, account setting change or payment was attempted. Workflow/image/PG16
acceptance remains pending.

18 October 2026. Application baseline `dd36b0d`, release lane base `3082f1a`.
This lane changes release tooling only. Product/schema/auth/recovery source and
`backend/requirements.txt` remain unchanged. Flags remain default off.

## Immutable inputs and their sources

`deploy/v1/Dockerfile` pins Python 3.11 slim **Bookworm** by its registry index
digest. The PostgreSQL 16 CI service is pinned the same way. The index records
include Linux amd64 and arm64 children; this establishes availability, not a
successful build. Exact registry responses are in
`artifacts/v1/release-ci/registry-pins.json`. These were obtained directly from
Docker's public registry manifest endpoint after a public pull-token request.
No registry credentials or tokens are saved. Docker documents digest pinning at
<https://docs.docker.com/reference/cli/docker/image/pull/>.

Every `uses:` action is pinned to an upstream Git commit, verified with
`git ls-remote https://github.com/actions/<action>.git refs/tags/<version>`:
checkout v4.2.2 `11bd71901bbe5b1630ceea73d27597364c9af683`, setup-python v5.6.0
`a26af69be951a213d495a4c3e4e4022e16d87065`, setup-node v4.4.0
`49933ea5288caeca8642d1e84afbd3f7d6820020`, upload-artifact v4.6.2
`ea165f8d65b6e75b540449e92b4886f43607fa02`. These are deliberately verified
stable versions, not a claim to be the latest releases. Node 22.23.3 was verified
against <https://nodejs.org/dist/index.json>. Local Python 3.11.16 came from uv's
managed CPython distribution. Hosted runner OS images and downloaded browser/OS
packages are not immutable; record the runner image version in actual CI evidence.

Runtime direct pins are mirrored exactly in `deploy/v1/runtime.in`, excluding only
pytest, pytest-asyncio and vcrpy. `runtime.lock` pins the complete Python 3.11/Linux
closure with distribution SHA256 hashes. `test.lock` adds the unchanged backend test
dependencies under runtime constraints. The Docker recipe requires binary wheels,
hash checking and `pip check`. See pip's primary guidance:
<https://pip.pypa.io/en/stable/topics/secure-installs/>.

Resolution used uv 0.12.9, public PyPI, no source builds, cutoff
`2026-10-18T00:00:00Z`, Python 3.11 and `x86_64-unknown-linux-gnu`:

```sh
uv pip compile deploy/v1/runtime.in --python-version 3.11 --python-platform x86_64-unknown-linux-gnu --generate-hashes --only-binary=:all: --default-index https://pypi.org/simple --exclude-newer 2026-10-18T00:00:00Z --no-header --no-annotate -o deploy/v1/runtime.lock
uv pip compile backend/requirements.txt -c deploy/v1/runtime.lock --python-version 3.11 --python-platform x86_64-unknown-linux-gnu --generate-hashes --only-binary=:all: --default-index https://pypi.org/simple --exclude-newer 2026-10-18T00:00:00Z --no-header --no-annotate -o deploy/v1/test.lock
```

The lock is intentionally scoped to Python 3.11/Linux, not every Python/platform.
The initially attempted universal test resolution failed on an unrelated PyPy
urllib3 constraint and was replaced by this explicit runtime scope. Saved public
PyPI version JSON metadata validates every runtime distribution hash; this is
registry provenance, not a vulnerability audit. Hashes prevent artifact substitution,
not vulnerabilities in incumbent direct pins. Changing those pins requires a
separate dependency/product compatibility review.

## Package and smoke guarantees

Only tracked allowlisted application/migration/static files, fixed storefront
modules, the immutable Docker recipe and validated runtime inputs enter the context.
Every enumerated static asset is now required, including scanner WASM/license.
An independent review found that staged deletions disappeared from the current
index allowlist used by the clean guard. The guard now diffs all HEAD names with
rename detection disabled before filtering runtime paths. Three regressions cover
a staged optional-module deletion, a rename inside runtime and a rename out of
runtime; release archives/builds refuse each.
Symlinks, development dependencies, URL/options/local requirement entries, dotenv,
uploads, tests and keys fail or remain excluded. The builder checks runtime direct
pins against the unchanged backend input before creating the destination.

`runtime-manifest.json` records the actual source file SHA256 values, generated
context file hashes, source Git revision and a canonical content-map hash. The
revision describes ancestry; **the content hash identifies packaged bytes**, including
modified tracked files. Untracked files remain excluded. The context manifest explicitly records `source_dirty`. Release `archive` and
`build` refuse staged or unstaged modified tracked runtime inputs; `context` still
permits an explicitly marked development snapshot. File modes and timestamps are
normalized. `archive --output <new-file.tar>` emits a sorted tar with uid/gid/mtime
zero and empty owner/group names; existing outputs are never replaced. Identical
HEAD/input bytes yield identical archives regardless of mtime and umask.
This does not establish byte-for-byte OCI image reproducibility.

Smoke uses one disposable container, network none, read-only root, nonroot
10001:10001, dropped capabilities, bounded tmpfs/resources, synthetic configuration
and three isolated off/enabled/missing-asset processes. It checks Python 3.11,
UID/GID, exact complete manifest match, file digests, required private/static assets,
startup refusal and zero recorded network/DNS attempts. Cleanup is only by the
Docker-written 64-character CID and is verified; names never authorize removal.
Docker inspect/cleanup calls are now bounded as well.

## CI boundary and current evidence

The workflow uses ephemeral GitHub-hosted Ubuntu 24.04 runners, `contents: read`,
no persisted checkout credentials, no secrets, no deployment/push and job timeouts.
It validates workflow syntax/contexts using upstream-checksummed actionlint 1.7.12,
installs the hashed test closure, runs safety/package/Node contracts and maintained
Playwright fixture journeys. Those fixture journeys remain fixture evidence.
The PostgreSQL job checks out full history for the independent historical evidence
verifier. The PostgreSQL 16 job uses a random published port, literal 127.0.0.1 and exact
`munimjee_test_ci` P01 lane. Existing guards block provider sockets and hold the
advisory lease across reset, actual migrations and each complete DB fixture.
A required dedicated migration/lease test writes JUnit and a second command rejects
missing, duplicate, failed, errored or skipped proof before the full backend suite. The same job then runs the maintained actual
`tests.run_wave4_native_browser` journey sequentially inside its own held P01 lease:
native signup/review, all three persisted themes and synthetic COD orders, with
external browser requests aborted and no provider transports.
Native amd64 and arm64 jobs build and run the network-disabled image smoke; no
multiarch registry manifest is published.

Local Python 3.11.16: **119 passed, 2 skipped** in the pure package/CI/P01-safety
selection; the two actual DB cases skipped explicitly because no lane was allocated.
The hashed test closure installed successfully on local macOS arm64 and passed
`uv pip check`; Python 3.11 compile checks passed. A separate source startup/route/model/revision
chain selection passed **5/5**; it did not connect to a database. Raw sanitized output is under
`artifacts/v1/release-ci/`. The first YAML validation found an unquoted colon in a command; it was corrected.
The early actual hosted run at checkpoint `dafc175` then failed before any job
started: <https://github.com/cipher098/munimjee/actions/runs/39105746311>.
Dynamic service-port context was moved to step environment and object indexing
uses a string key. Verified actionlint subsequently passed; this does not turn the
initial failed run into a pass. Node contracts passed **77/77** and the maintained
syntax check passed locally. Python Actions distribution metadata confirms 3.11.16
on Linux x64 and arm64, saved in `python-action-version.json`.

The single permitted read-only Docker info probe timed out at six seconds. No
Docker restart, local build, actual new image smoke, actual PostgreSQL execution,
successful remote CI run or multiarch result is claimed. Earlier wave4 image/database evidence
belongs to its recorded source/inputs and does not certify this changed base/lock.
Real CPython 3.11 hash-required wheel downloads succeeded for **90/90 packages
on each Linux amd64 and arm64 target** using Python 3.11.16/pip 24.0; all downloaded
wheel digests were independently rechecked against the runtime lock. The target
wheel manifests are `linux-wheel-downloads.json`. This proves availability and
hash matching, not installation/execution on those architectures. Initial downloads
using macOS system Python 3.9/pip 21 were rejected on its Python-marker resolution;
the successful downloads used the actual Python 3.11 interpreter.

Two clean-source CLI archives at fixed source `01b0ce4` matched byte-for-byte:
3,399,680 bytes, SHA256
`49a4c17a0c63c929ff10c428bcf9f42ff08939374a02adc181470ab362c11a57`.
The canonical packaged content-map hash is
`ae4eaadeb905bca50bdf03b58be966858d3dc8de45d59ac5fdbc9b7b2362272b`.
Archive evidence includes the exact full source revision; a new commit changes the
embedded revision and therefore the archive hash even when content-map bytes match.

Successful hosted workflow runs, new image smoke and any OCI reproducibility claim remain pending. Rehearsal CLI
execution composition remains deferred until its independent safety review and
coordinator integration. Its standalone plan/pure checks are reported by that lane. Live provider,
physical phone, migration/restore, business readiness and all other G0-G6 gates
remain separate release requirements; this CI work does not make V1 released.
