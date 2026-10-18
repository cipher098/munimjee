"""Own P01 reset lease, actual shared app.main and ephemeral synthetic loopback TLS."""
from tests.safety import install_test_safety
install_test_safety()
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
import sys
import tempfile
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from tests.isolated_database import migrated_database


async def main():
    root = Path(__file__).resolve().parents[2]
    async with migrated_database():
        with tempfile.TemporaryDirectory(prefix='v1-comment-operator-tls-') as directory:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-loopback-only')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256()))
            keyfile, certfile = Path(directory) / 'key.pem', Path(directory) / 'cert.pem'
            keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            keyfile.chmod(0o600)
            certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            server = await asyncio.create_subprocess_exec(sys.executable, '-m', 'tests.comment_operator_browser_server',
                str(certfile), str(keyfile), cwd=root / 'backend', env=dict(os.environ))
            try:
                browser = await asyncio.create_subprocess_exec('node', str(root / 'backend/tests/browser/comment-operator.mjs'), cwd=root)
                code = await browser.wait()
                if code:
                    raise SystemExit(code)
            finally:
                if server.returncode is None:
                    server.terminate()
                await server.wait()
    # TemporaryDirectory removes both key/cert even after a failed browser run.


if __name__ == '__main__':
    asyncio.run(main())
