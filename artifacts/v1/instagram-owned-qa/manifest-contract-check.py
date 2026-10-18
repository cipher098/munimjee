"""Bounded source/ORM-metadata check; no database, provider or shared writes."""
from pathlib import Path
import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[3]
CSV = "32a2d11fb51293402dd814eb3c4216327e5eec5a"
sys.path.insert(0, str(ROOT / "backend"))
from tests.safety import install_test_safety
install_test_safety()
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from app.models.imports_v1 import ImportAsset, ImportAudit
from app.services.imports_v1 import digest


def read(name):
    return (ROOT / name).read_text()


def csv_read(name):
    return subprocess.check_output(["git", "show", CSV + ":" + name], cwd=ROOT, text=True)


checks = []


def check(name, condition):
    checks.append({"name": name, "passed": bool(condition)})
    assert condition, name


def required(model):
    return sorted(column.name for column in model.__table__.columns
        if not column.nullable and column.default is None and column.server_default is None)


business = UUID("10000000-0000-0000-0000-000000000071")
actor = UUID("20000000-0000-0000-0000-000000000071")
job_id = UUID("30000000-0000-0000-0000-000000000071")
candidate_id = UUID("40000000-0000-0000-0000-000000000071")
asset_id = UUID("50000000-0000-0000-0000-000000000071")
media_id = "180000000000071"
content = b"\x89PNG\r\n\x1a\nsynthetic-original"
sha = hashlib.sha256(content).hexdigest()
asset_key = uuid5(job_id, "instagram-original:" + media_id + ":" + sha)
manifest_key = uuid5(job_id, "instagram-manifest:" + str(candidate_id) + ":" + media_id + ":" + sha)
asset_values = dict(id=asset_id, business_id=business, creator_id=actor,
    idempotency_key=asset_key, content_type="image/png", sha256=sha,
    size_bytes=len(content), content=content, authorized_at=datetime(2026, 10, 18, tzinfo=timezone.utc))
details = dict(contract_version="instagram-owned-manifest.v1", parent_media_id=media_id,
    asset_media_id=media_id, asset_id=str(asset_id), sha256=sha, size_bytes=len(content),
    content_type="image/png", connection_version=7)
audit_values = dict(id=uuid4(), business_id=business, job_id=job_id,
    candidate_id=candidate_id, actor_id=actor, idempotency_key=manifest_key,
    request_hash=digest(details), action="instagram_assets_retained", details=details)
asset_ddl = str(CreateTable(ImportAsset.__table__).compile(dialect=postgresql.dialect()))
audit_ddl = str(CreateTable(ImportAudit.__table__).compile(dialect=postgresql.dialect()))
check("asset insertion supplies every required field", set(required(ImportAsset)) <= asset_values.keys())
check("audit insertion supplies every required field", set(required(ImportAudit)) <= audit_values.keys())
check("asset unique key is tenant plus idempotency", any(isinstance(item, UniqueConstraint) and
    tuple(item.columns.keys()) == ("business_id", "idempotency_key") for item in ImportAsset.__table__.constraints))
check("audit unique key is tenant plus idempotency", any(isinstance(item, UniqueConstraint) and
    tuple(item.columns.keys()) == ("business_id", "idempotency_key") for item in ImportAudit.__table__.constraints))
audit_fks = [tuple(item.columns.keys()) for item in ImportAudit.__table__.constraints if isinstance(item, ForeignKeyConstraint)]
check("audit job and candidate have actual composite tenant FKs",
    ("business_id", "job_id") in audit_fks and ("business_id", "candidate_id") in audit_fks)
check("JSON asset reference has no asset FK", "v1_import_assets" not in audit_ddl and "asset_id" not in ImportAudit.__table__.columns)
check("asset hash CHECK validates shape rather than content hash", "sha256 ~ '^[a-f0-9]{64}$'" in asset_ddl and "digest(" not in asset_ddl)
check("asset byte size CHECK remains five MB", "size_bytes <= 5000000" in asset_ddl and "octet_length(content) = size_bytes" in asset_ddl)
check("new action fits existing column", len(audit_values["action"]) <= ImportAudit.action.type.length)
check("canonical details are JSON primitives with reproducible digest", json.loads(json.dumps(details)) == details and
    digest(details) == hashlib.sha256(json.dumps(details, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest())
check("same job media hash deterministically replays asset and manifest keys",
    asset_key == uuid5(job_id, "instagram-original:" + media_id + ":" + sha) and
    manifest_key == uuid5(job_id, "instagram-manifest:" + str(candidate_id) + ":" + media_id + ":" + sha))
check("new job preserves a separate original version",
    asset_key != uuid5(UUID("30000000-0000-0000-0000-000000000072"), "instagram-original:" + media_id + ":" + sha))
migration = read("backend/alembic/versions/0046_v1_import_jobs.py")
check("0046 has no append-only trigger or manifest JSON FK", "CREATE TRIGGER" not in migration and "details->" not in migration)
api_tree = ast.parse(read("backend/app/api/v1/imports.py"))
get_paths = [node.args[0].value for node in ast.walk(api_tree) if isinstance(node, ast.Call) and
    isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args and
    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and node.args[0].value.startswith("/")]
check("current API has no asset or manifest GET", all("asset" not in path and "upload" not in path and "manifest" not in path for path in get_paths))
csv_model = csv_read("backend/app/models/imports_v1.py")
csv_migration = csv_read("backend/alembic/versions/0053_v1_csv_import.py")
check("CSV only widens asset MIME CHECK in the existing model", csv_model == read("backend/app/models/imports_v1.py").replace(
    "'image/jpeg','image/png','video/mp4'", "'image/jpeg','image/png','video/mp4','text/csv'"))
check("CSV0053 does not add FK trigger or schema relationship", "0052_v1_customer_links" in csv_migration and
    "create_check_constraint" in csv_migration and "ForeignKey" not in csv_migration and "CREATE TRIGGER" not in csv_migration)
unchanged_paths = ["backend/alembic/versions/0046_v1_import_jobs.py", "backend/app/services/import_catalogue.py",
    "backend/app/models/import_catalogue.py", "backend/app/api/v1/import_catalogue.py",
    "backend/app/services/channel_connections.py", "backend/app/services/channel_operator.py",
    "backend/app/workers/refresh_tokens.py", "backend/app/api/routes/auth.py"]
check("manifest readers and credential writer contracts unchanged by CSV32",
    all(read(path) == csv_read(path) for path in unchanged_paths))
csv_service = csv_read("backend/app/services/imports_v1.py")
check("CSV immutable capture and stale guard remain required", "captured_at = job.created_at if job.source[\"kind\"] == \"csv\" else timestamp" in csv_service and
    'action="stale_capture_ignored"' in csv_service)

paths = ["backend/app/models/imports_v1.py", "backend/app/services/imports_v1.py", "backend/app/api/v1/imports.py", *unchanged_paths]
result = dict(qa_commit_before_followup=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    csv_commit=CSV, assertion_count=len(checks), checks=checks,
    asset_required_without_defaults=required(ImportAsset), audit_required_without_defaults=required(ImportAudit),
    audit_fk_column_sets=audit_fks, import_GET_paths=get_paths,
    source_sha256={path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
    csv_sha256={path: hashlib.sha256(csv_read(path).encode()).hexdigest() for path in [
        "backend/app/models/imports_v1.py", "backend/app/services/imports_v1.py", "backend/alembic/versions/0053_v1_csv_import.py"]},
    synthetic_manifest_details=details, synthetic_asset_key=str(asset_key), synthetic_manifest_key=str(manifest_key),
    limitations=["Static source and ORM metadata only; no database constraint execution", "No shared hook or reader implemented",
        "Manifest JSON asset_id has no database FK", "Append-only behavior is an application proposal, not enforced DDL",
        "All credential writers still require coordinated lock/version fencing"],
    database_connections=0, provider_calls=0)
print(json.dumps(result, indent=2))
