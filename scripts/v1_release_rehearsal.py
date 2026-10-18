#!/usr/bin/env python3
"""Fail-closed synthetic PostgreSQL 16 backup/restore and compatibility rehearsal.

The default plan reads repository migration metadata only. Execution never creates
or drops a database and accepts only two explicitly allocated, initially empty DBs.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from contextlib import AsyncExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Reviewed additive support/customer-link schema. Keep this explicit: a later
# migration needs its own compatibility review rather than accepting any head.
SUPPORTED_HEAD = "0052_v1_customer_links"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1000
MAX_TABLES = 200
TIMEOUT = 180


class RehearsalError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RehearsalError(message)


def repo_head(root=ROOT):
    revisions, parents = set(), set()
    for path in (root / "backend/alembic/versions").glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("revision", "down_revision"):
                        values[target.id] = ast.literal_eval(node.value)
        if "revision" in values:
            revisions.add(values["revision"])
            parent = values.get("down_revision")
            parents.update(parent if isinstance(parent, (tuple, list)) else [parent])
    heads = revisions - parents
    require(heads == {SUPPORTED_HEAD}, "Unsupported migration head; review compatibility contract first")
    return SUPPORTED_HEAD


def plan():
    return {
        "format": "munimjee.release-rehearsal.v1", "mode": "plan",
        "database_effects": False, "container_effects": False,
        "alembic_head": repo_head(), "required_postgresql_major": 16,
        "execute_contract": "two allocated initially empty P01 lanes; private ownership attestation; new private archive directory",
        "stages": ["validate inputs without connecting", "hold both P01 leases", "verify PG16 and empty source/target",
                   "migrate source using P01 and seed fixed synthetic fixture", "export read-only consistent snapshot",
                   "private bounded pg_dump", "recheck empty target and pg_restore single transaction",
                   "reconcile all table row/identity hashes, schema and monetary/reservation/pending totals",
                   "append newer target-only order; generic read-only persisted-data probe preserves all facts"],
        "application_switch": "pending: requires actual reviewed old/current application packages and mounted journey",
        "routine_rollback": "preserve post-cutover writes; compatibility preflight/forward fix; no snapshot overwrite or downgrade",
    }


def p01():
    # Import existing guards, never app.config or a dotenv source.
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from tests.safety import validate_test_database
    from tests.isolated_database import acquire_lease
    return validate_test_database, acquire_lease


def targets(source_lane, target_lane, env):
    validate, _ = p01()
    def one(lane, key):
        return validate({"TEST_LANE": lane, "TEST_DB_RESET": "1", "TEST_DATABASE_URL": env.get(key, ""),
                         "PYTEST_XDIST_WORKER": env.get("PYTEST_XDIST_WORKER", "master")})
    source = one(source_lane, "REHEARSAL_SOURCE_URL")
    target = one(target_lane, "REHEARSAL_TARGET_URL")
    require(source.database != target.database, "Source and target must be different allocated lanes")
    return source, target


def no_symlinks(path):
    require(path.is_absolute(), "Private paths must be absolute")
    require(".." not in path.parts, "Private paths cannot traverse parents")
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), "Symlinked private paths are forbidden")


def ownership(path, source, target):
    no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600,
                "Ownership attestation must be an owned 0600 regular file")
        require(info.st_size <= 4096, "Ownership attestation is too large")
        payload = os.read(fd, 4097)
        require(len(payload) <= 4096, "Ownership attestation grew beyond its bound")
        value = json.loads(payload)
    finally:
        os.close(fd)
    expected = {"format", "source_lane", "target_lane", "synthetic_only", "allocated", "owner"}
    require(isinstance(value, dict) and set(value) == expected, "Ownership attestation fields do not match the contract")
    require(value["format"] == "munimjee.release-ownership.v1" and value["source_lane"] == source.lane
            and value["target_lane"] == target.lane and value["synthetic_only"] is True and value["allocated"] is True
            and isinstance(value["owner"], str) and 0 < len(value["owner"]) <= 100,
            "Explicit allocated synthetic ownership attestation does not match both lanes")


def archive_location(path):
    no_symlinks(path)
    require(not any((parent / ".git").exists() for parent in (path, *path.parents)),
            "Private archives must remain outside every Git repository")
    require(not path.exists() and path.parent.is_dir(), "Archive directory must be new with an existing parent")
    require(path.parent.stat().st_uid == os.getuid() or bool(path.parent.stat().st_mode & stat.S_ISVTX),
            "Archive parent must be owned or sticky")


def private_file(directory, name):
    # Names are constants owned by this tool, never supplied by an archive.
    require(re.fullmatch(r"[a-z][a-z0-9_.-]{0,60}", name), "Invalid private output name")
    return os.fdopen(os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb")


def private_read(path):
    no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= MAX_ARCHIVE_BYTES,
                "Private archive must remain an owned bounded 0600 regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def private_sha256(path):
    digest = hashlib.sha256()
    with private_read(path) as stream:
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            require(total <= MAX_ARCHIVE_BYTES, "Private archive grew beyond its bound")
            digest.update(chunk)
    return digest.hexdigest()


def private_json(directory, name, value):
    with private_file(directory, name) as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def child_env(target, original):
    parsed = urlsplit(target.url)
    return {"PATH": original.get("PATH", os.defpath), "LANG": "C", "LC_ALL": "C",
            "PGHOST": target.host, "PGPORT": str(target.port), "PGDATABASE": target.database,
            "PGUSER": parsed.username, "PGPASSWORD": parsed.password,
            "PGCONNECT_TIMEOUT": "5", "PGSSLMODE": "disable", "PGPASSFILE": os.devnull,
            "PGSERVICEFILE": os.devnull, "PGSYSCONFDIR": os.devnull,
            "PGOPTIONS": "-c statement_timeout=120000 -c lock_timeout=5000"}


def command(argv, env, *, stdout=subprocess.PIPE, stdin=None):
    try:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/v1_release_exec.py"), str(MAX_ARCHIVE_BYTES), *argv],
                                env=env, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE,
                                timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RehearsalError("Bounded rehearsal subprocess failed or timed out; output withheld") from None
    require(result.returncode == 0, "Rehearsal subprocess failed; output withheld")
    return result.stdout



async def owned_call(function, *args, **kwargs):
    """Do not release either DB lease while a cancelled worker child still runs.

    subprocess.run itself kills/waits on timeout. Shielding plus draining the
    worker ensures cooperative cancellation cannot outlive the held DB leases.
    """
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancellation = None
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError as error:
            cancellation = error
        except Exception:
            break
    if cancellation is not None:
        # Retrieve a possible worker error to avoid an unhandled-task warning;
        # cancellation retains precedence while leases are still held.
        if not worker.cancelled():
            worker.exception()
        raise cancellation
    return worker.result()


def pg_tools(directory, env):
    no_symlinks(directory)
    tools = {}
    for name in ("pg_dump", "pg_restore"):
        executable = directory / name
        require(executable.is_file() and os.access(executable, os.X_OK), "Explicit PostgreSQL tools are unavailable")
        # Tool symlinks within an explicit trusted PG16 installation are allowed;
        # private archive/attestation paths remain strictly no-follow.
        output = command([str(executable), "--version"], env)
        require(re.fullmatch(name.encode() + rb" \(PostgreSQL\) 16\.[0-9]+[^\n]*\n?", output or b""),
                "Both archive tools must be PostgreSQL 16")
        tools[name] = str(executable)
    return tools


async def query(connection, sql, params=None):
    from sqlalchemy import text
    return await connection.execute(text(sql), params or {})


async def empty_database(connection):
    # All non-system relation/function/type objects, not merely application rows.
    count = (await query(connection, """SELECT
      (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
       WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') +
      (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
       WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') +
      (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
       WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema') +
      (SELECT count(*) FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema'))
    """)).scalar_one()
    require(count == 0, "Allocated source/restore target must be an empty database")


async def pg16(connection):
    version = int((await query(connection, "SHOW server_version_num")).scalar_one())
    require(160000 <= version < 170000, "Both allocated database servers must be PostgreSQL 16")


def canonical_constraint(definition):
    """Recognize only PG16's equivalent literal varchar-array text coercion.

    pg_dump/reparse may distribute a varchar[] -> text[] cast onto each literal.
    Preserve every literal, its order and all surrounding SQL. No other cast,
    expression, operator or writer protection is discarded.
    """
    literal = r"'(?:[^']|'')*'::character varying"
    pattern = re.compile(r"\(\(ARRAY\[(" + literal + r"(?:, " + literal + r")*)\]\)::text\[\]\)")
    def distribute(match):
        values = re.findall(literal, match.group(1))
        return "(ARRAY[" + ", ".join("(" + value + ")::text" for value in values) + "])"
    output, index = [], 0
    while index < len(definition):
        start = index
        if definition.startswith("--", index):
            end = definition.find("\n", index + 2)
            index = len(definition) if end < 0 else end + 1
        elif definition.startswith("/*", index):
            index, depth = index + 2, 1
            while index < len(definition) and depth:
                if definition.startswith("/*", index):
                    depth += 1
                    index += 2
                elif definition.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
        elif definition[index] in ("'", '"'):
            quote = definition[index]
            escaped = quote == "'" and index > 0 and definition[index-1] in "Ee" and (
                index == 1 or not (definition[index-2].isalnum() or definition[index-2] in "_$"))
            index += 1
            while index < len(definition):
                # Only E strings have backslash-escaped quote delimiters.
                # Standard/U& strings and quoted identifiers double quotes.
                if escaped and definition[index] == "\\":
                    index += 2
                elif definition[index] == quote:
                    index += 1
                    if index < len(definition) and definition[index] == quote:
                        index += 1
                    else:
                        break
                else:
                    index += 1
        elif definition[index] == "$" and (tag := re.match(r"\$(?:[A-Za-z_\x80-\U0010ffff][A-Za-z0-9_\x80-\U0010ffff]*)?\$", definition[index:])):
            delimiter = tag.group()
            end = definition.find(delimiter, index + len(delimiter))
            index = len(definition) if end < 0 else end + len(delimiter)
        elif match := pattern.match(definition, index):
            output.append(distribute(match))
            index = match.end()
            continue
        else:
            index += 1
        output.append(definition[start:index])
    return "".join(output)


async def schema_fingerprint(connection):
    """Fingerprint restored public writer protections as well as columns/FKs.

    Definitions are private inputs to a digest. Internal FK triggers are covered
    by validated FK definitions rather than unstable generated object OIDs/names.
    """
    await query(connection, "SET LOCAL standard_conforming_strings = on")
    catalog = {
        "columns": """SELECT table_name,column_name,data_type,udt_name,is_nullable,column_default
          FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position""",
        "constraints": """SELECT c.relname,k.conname,pg_get_constraintdef(k.oid),k.convalidated
          FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' ORDER BY c.relname,k.conname""",
        "functions": """SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY 1,2""",
        "triggers": """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled
          FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1,2""",
        "indexes": """SELECT tablename,indexname,indexdef FROM pg_indexes
          WHERE schemaname='public' ORDER BY tablename,indexname""",
        "table_security": """SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,c.relreplident,c.relpersistence
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY 1""",
        "policies": """SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
          FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname""",
        "views": """SELECT c.relname,c.relkind,pg_get_viewdef(c.oid)
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND c.relkind IN ('v','m') ORDER BY 1""",
        "enums": """SELECT t.typname,e.enumlabel,e.enumsortorder FROM pg_type t
          JOIN pg_namespace n ON n.oid=t.typnamespace JOIN pg_enum e ON e.enumtypid=t.oid
          WHERE n.nspname='public' ORDER BY t.typname,e.enumsortorder""",
        "sequence_definitions": """SELECT sequencename,data_type,start_value,min_value,max_value,increment_by,cycle,cache_size
          FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename""",
    }
    inventory = {name: list(map(list, (await query(connection, sql)).all())) for name, sql in catalog.items()}
    require(all(row[3] for row in inventory["constraints"]), "Unvalidated restored constraints are forbidden")
    for row in inventory["constraints"]:
        row[2] = canonical_constraint(row[2])
    inventory["sequence_state"] = []
    for row in inventory["sequence_definitions"]:
        name = row[0]
        require(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name), "Unexpected sequence identifier")
        state = (await query(connection, f'SELECT last_value,is_called FROM public."{name}"')).one()
        inventory["sequence_state"].append([name, *state])
    return hashlib.sha256(json.dumps(inventory, sort_keys=True, default=str).encode()).hexdigest()


async def snapshot(connection):
    await query(connection, "SET LOCAL TIME ZONE 'UTC'")
    versions = list((await query(connection, "SELECT version_num FROM public.alembic_version")).scalars())
    require(versions == [repo_head()], "Database must match the exact current repository Alembic head")
    tables = list((await query(connection, """SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename""")).scalars())
    require(0 < len(tables) <= MAX_TABLES, "Synthetic table inventory exceeds bounds")
    result = {}
    for name in tables:
        require(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name), "Unexpected table identifier")
        # to_jsonb canonicalizes column order; sort canonical full rows so duplicate
        # rows, every ID, values and multiplicity all contribute to the digest.
        size = (await query(connection, f'SELECT count(*),coalesce(sum(octet_length(to_jsonb(t)::text)),0) FROM public."{name}" t')).one()
        require(size[0] <= MAX_ROWS and size[1] <= 4 * 1024 * 1024, "Synthetic table data bound exceeded")
        rows = list((await query(connection, f'SELECT to_jsonb(t)::text FROM public."{name}" t LIMIT {MAX_ROWS + 1}')).scalars())
        require(len(rows) <= MAX_ROWS, "Synthetic row bound exceeded")
        digest = hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode()).hexdigest()
        result[name] = {"count": len(rows), "row_sha256": digest}
    schema_digest = await schema_fingerprint(connection)
    totals = (await query(connection, """SELECT count(*),coalesce(sum(total),0),
      coalesce(sum(total) FILTER (WHERE payment_status='paid'),0),
      coalesce(sum(total) FILTER (WHERE payment_status='collected'),0),
      (SELECT count(*) FROM sku_reservations),
      (SELECT coalesce(sum(quantity),0) FROM sku_reservations WHERE NOT released),
      (SELECT count(*) FROM sku_payment_attempts WHERE state='unknown'),
      (SELECT count(*) FROM manual_actions WHERE status='open'),
      (SELECT coalesce(sum(stock_available),0) FROM catalogue_skus) FROM commerce_orders""")).one()
    integrity = (await query(connection, """SELECT
      (SELECT count(*) FROM commerce_orders WHERE total<>subtotal+shipping_fee OR total<0) +
      (SELECT count(*) FROM sku_reservations r LEFT JOIN commerce_orders o ON o.id=r.order_id AND o.seller_id=r.business_id
         LEFT JOIN catalogue_skus s ON s.id=r.sku_id AND s.business_id=r.business_id AND s.product_id=r.product_id
         WHERE o.id IS NULL OR s.id IS NULL OR r.quantity<1)
    """)).scalar_one()
    require(integrity == 0, "Monetary/reservation integrity reconciliation failed")
    return {"head": versions[0], "tables": result, "schema_sha256": schema_digest,
            "totals": dict(zip(("orders", "placed_total_minor", "paid_total_minor", "cod_collected_minor",
                                "reservations", "reserved_quantity", "unknown_payments", "open_actions", "available_stock"), map(int, totals)))}


async def run(args, env):
    source, target = targets(args.source_lane, args.target_lane, env)
    ownership(args.attestation, source, target)
    archive_location(args.archive_dir)
    tools = await owned_call(pg_tools, args.pg_bin, {"PATH": env.get("PATH", os.defpath), "LANG": "C"})
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from v1_release_synthetic import seed, newer_order, validate_fixture
    _, acquire_lease = p01()
    engines = [create_async_engine(t.url, poolclass=NullPool, connect_args={"timeout": 5, "command_timeout": 120})
               for t in (source, target)]
    try:
        async with AsyncExitStack() as stack:
            connections = [await stack.enter_async_context(engine.connect()) for engine in engines]
            for connection, database in zip(connections, (source, target)):
                await acquire_lease(connection, database)
                await connection.commit()  # session-level lease survives transactions
                await pg16(connection)
                await empty_database(connection)
                await connection.commit()
            require(targets(args.source_lane, args.target_lane, env) == (source, target), "Lane configuration changed")
            src, dst = connections
            # Owned source only; existing P01 migrator never creates/drops a DB.
            migration_env = {key: env[key] for key in ("PATH", "HOME", "TMPDIR") if key in env}
            migration_env.update(TEST_DATABASE_URL=source.url, TEST_LANE=source.lane, TEST_DB_RESET="1",
                                 PYTHONPATH=str(ROOT / "backend"))
            await owned_call(command, [sys.executable, "-m", "tests.migrate_test_database"], migration_env)
            await seed(src)
            await src.commit()
            async with src.begin():
                await query(src, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                await query(src, "SET LOCAL TIME ZONE 'UTC'")
                baseline = await snapshot(src)
                await validate_fixture(src, baseline)
                export = (await query(src, "SELECT pg_export_snapshot()")).scalar_one()
                require(re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+", export), "Invalid exported snapshot token")
                archive_location(args.archive_dir)  # revalidate immediately before filesystem mutation
                os.mkdir(args.archive_dir, 0o700)
                with private_file(args.archive_dir, "synthetic.dump") as archive:
                    await owned_call(command,
                        [tools["pg_dump"], "--format=custom", "--no-owner", "--no-privileges", "--no-comments",
                         "--no-security-labels", "--snapshot", export], child_env(source, env), stdout=archive)
                    archive.flush()
                    os.fsync(archive.fileno())
                archive_path = args.archive_dir / "synthetic.dump"
                require(0 < archive_path.stat().st_size <= MAX_ARCHIVE_BYTES, "Archive size bound failed")
                await empty_database(dst)  # both leases still held; refuse any preexisting target objects
                await dst.commit()
                with private_read(archive_path) as archive:
                    await owned_call(command,
                        [tools["pg_restore"], "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error",
                         "--dbname", target.database], child_env(target, env), stdin=archive)
                await query(dst, "SET LOCAL TIME ZONE 'UTC'")
                restored = await snapshot(dst)
                require(restored == baseline, "Restored target reconciliation mismatch")
                await dst.commit()
                # Never mutate source or restore an older backup over newer writes.
                await newer_order(dst)
                await dst.commit()
                before = await snapshot(dst)
                await dst.commit()
                async with dst.begin():
                    await query(dst, "SET TRANSACTION READ ONLY")
                    result = (await query(dst, "SELECT id,total,payment_status FROM commerce_orders ORDER BY id")).all()
                    require(len(result) == 3, "Persisted-data reader lost a post-cutover synthetic order")
                    require(await snapshot(dst) == before, "Persisted read-contract probe changed facts")
                require(await snapshot(src) == baseline, "Source changed during read-only backup")
                evidence = {"format": "munimjee.release-rehearsal.v1", "mode": "execute", "synthetic_only": True,
                            "head": repo_head(), "restore": "passed", "reconciliation": restored,
                            "post_cutover_reconciliation": before,
                            "persisted_read_contract": "passed; generic SQL probe retains newer target-only order",
                            "application_switch": "pending_actual_old_current_application_journey",
                            "schema_downgrade": "not_executed", "archive_sha256": private_sha256(archive_path)}
                private_json(args.archive_dir, "evidence.json", evidence)
                return evidence
    finally:
        for engine in engines:
            await engine.dispose()


class RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise RehearsalError("Invalid invocation; arguments withheld")


def main(argv=None):
    parser = RedactedArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "execute"), default="plan")
    parser.add_argument("--source-lane")
    parser.add_argument("--target-lane")
    parser.add_argument("--attestation", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--pg-bin", type=Path)
    try:
        args = parser.parse_args(argv)
        if args.action == "plan":
            result = plan()
        else:
            require(all((args.source_lane, args.target_lane, args.attestation, args.archive_dir, args.pg_bin)),
                    "Execute requires both lane names, private ownership attestation, new archive directory and explicit PG16 tools")
            repo_head()
            result = asyncio.run(run(args, dict(os.environ)))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        # Exceptions from drivers/libpq can include URLs or SQL row values.
        # Only a fixed redacted message reaches public output.
        print(json.dumps({"format": "munimjee.release-rehearsal.v1", "status": "failed",
                          "reason": "Rehearsal refused or failed; private inputs and subprocess output withheld"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
