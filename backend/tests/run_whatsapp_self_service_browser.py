"""P01 lease spanning actual migrations/main, loopback TLS and Chromium."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import text
from tests.isolated_database import current_migration_head, migrated_database

def source_manifest(root):
    paths = sorted([*root.joinpath('backend/app').rglob('*.py'),
                    *root.joinpath('backend/static').glob('*'),
                    *root.joinpath('backend/alembic').rglob('*.py'),
                    *root.joinpath('backend/tests').glob('*whatsapp*self*.*'),
                    root/'backend/tests/browser/whatsapp-self-service.mjs'])
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}

async def journey(root):
    nonce = secrets.token_hex(24)
    async with migrated_database() as engine:
        async with engine.connect() as db:
            actual = await db.scalar(text('SELECT version_num FROM alembic_version'))
            assert actual == current_migration_head()
            print('Actual Alembic head:', actual, flush=True)
            print('Actual PostgreSQL:', await db.scalar(text('SHOW server_version')), flush=True)
        with tempfile.TemporaryDirectory(prefix='v1-wa-setup-loopback-tls-') as directory:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-loopback-only')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
                .not_valid_after(now+timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                .sign(key, hashes.SHA256()))
            keyfile, certfile = Path(directory)/'key.pem', Path(directory)/'cert.pem'
            keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
            keyfile.chmod(0o600)
            certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            server = await asyncio.create_subprocess_exec(sys.executable, '-m', 'tests.whatsapp_self_service_server',
                str(certfile), str(keyfile), nonce, cwd=root/'backend', env=dict(os.environ))
            try:
                browser = await asyncio.create_subprocess_exec('node', str(root/'backend/tests/browser/whatsapp-self-service.mjs'),
                    cwd=root, env={**os.environ, 'WA_SETUP_FIXTURE_NONCE': nonce})
                try:
                    code = await asyncio.wait_for(browser.wait(), 240)
                except BaseException:
                    if browser.returncode is None:
                        browser.terminate()
                        await browser.wait()
                    raise
                if code:
                    raise SystemExit(code)
            finally:
                if server.returncode is None:
                    server.terminate()
                await server.wait()

async def main():
    root = Path(__file__).resolve().parents[2]
    output = root/'artifacts/v1/whatsapp-self-service/mounted'
    output.mkdir(parents=True, exist_ok=True)
    before = source_manifest(root)
    (output/'source-before.json').write_text(json.dumps(before, indent=2)+'\n')
    try:
        await journey(root)
    finally:
        # Preserve hashes even when the first browser run fails; never replace
        # a failed result with a success or leave a live server/TLS directory.
        after = source_manifest(root)
        (output/'source-manifest.json').write_text(json.dumps({'before': before, 'after': after}, indent=2)+'\n')
        assert before == after, 'Application/harness source changed during mounted proof'
        print(f'Stable application/harness hashes: {len(before)}', flush=True)

if __name__ == '__main__':
    asyncio.run(main())
