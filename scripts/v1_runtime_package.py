#!/usr/bin/env python3
"""Create a small allowlisted V1 build context; never send the checkout to Docker."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STOREFRONT = (
    'styles.css', 'live.css', 'live-entry.js', 'live-app.js', 'live-api.js',
    'canonical-contract.js', 'checkout-attempt.js', 'order-status.js',
    'components.js', 'commerce.js', 'theme-config.js',
)
STATIC = frozenset((
    'admin.html', 'catalogue_workspace.css', 'catalogue_workspace.html', 'catalogue_workspace.js',
    'categories.html', 'channel_operator.css', 'channel_operator.html', 'channel_operator.js',
    'commerce.css', 'commerce.html', 'commerce.js', 'dashboard.html', 'dashboard_login.html',
    'data_deletion.html', 'llm_costs.html', 'manual_actions.html', 'onboarding.html', 'products.html',
    'settings.html', 'social.css', 'social.html', 'social.js', 'storefront.css', 'storefront.html',
    'storefront.js', 'training.html', 'v1_app.css', 'v1_app.html', 'v1_app.js', 'v1_client.js',
))
DEV_REQUIREMENTS = {'pytest', 'pytest-asyncio', 'vcrpy'}
FORBIDDEN = {'.env', '.git', 'uploads', 'tests', 'node_modules', 'artifacts',
             'design', 'keys', '__pycache__', '.venv'}


def allowed_source(name: str) -> bool:
    path = Path(name)
    if any(part.lower() in FORBIDDEN or part.lower().startswith('.env') for part in path.parts):
        return False
    if name in {'backend/requirements.txt', 'backend/alembic.ini', 'deploy/v1/Dockerfile'}:
        return True
    if path.parts[:2] == ('backend', 'app'):
        return ('scripts' not in path.parts and path.suffix == '.py') or name in {
            'backend/app/agents.yaml', 'backend/app/intervention_rules.yaml'}
    if path.parts[:2] == ('backend', 'alembic'):
        return path.suffix in {'.py', '.mako'}
    if path.parts[:2] == ('backend', 'static'):
        return len(path.parts) == 3 and path.name in STATIC
    return name.startswith('frontend/storefront/src/') and path.name in STOREFRONT and len(path.parts) == 4


def tracked_sources(root: Path) -> list[str]:
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], check=True, capture_output=True)
    return sorted(name for name in result.stdout.decode().split('\0') if name and allowed_source(name))


def checked_source(root: Path, name: str) -> Path:
    source = root / name
    # Git symlinks or symlinked directories must never read outside the checkout.
    if source.is_symlink() or any(parent.is_symlink() for parent in source.parents if parent != root.parent):
        raise ValueError('Runtime source symlinks are forbidden')
    if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
        raise ValueError('Missing or foreign runtime source')
    return source


def copy_source(root: Path, name: str, destination: Path) -> None:
    source = checked_source(root, name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)


def create_context(root: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError('Build context destination must not already exist')
    root = root.resolve()
    names = tracked_sources(root)
    required = {'backend/requirements.txt', 'backend/alembic.ini', 'backend/app/main.py',
                'backend/alembic/env.py', 'backend/static/v1_client.js', 'deploy/v1/Dockerfile'}
    required.update('frontend/storefront/src/' + name for name in STOREFRONT)
    if not required.issubset(names):
        raise ValueError('Required tracked runtime files are missing')
    output.mkdir(parents=True)
    for name in names:
        if name == 'backend/requirements.txt':
            continue
        target = ('Dockerfile' if name == 'deploy/v1/Dockerfile' else
                  'storefront-src/' + Path(name).name if name.startswith('frontend/storefront/src/') else name)
        copy_source(root, name, output / target)
    lines = checked_source(root, 'backend/requirements.txt').read_text().splitlines()
    requirements = []
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_-]+)(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+-]+', line)
        if not match:
            raise ValueError('Only pinned index requirements are accepted; URLs/options/local paths are forbidden')
        if match[1].lower() not in DEV_REQUIREMENTS:
            requirements.append(line)
    (output / 'requirements.txt').write_text('\n'.join(requirements) + '\n')
    files = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(output.rglob('*')) if path.is_file()}
    manifest = {'format': 'munimjee.v1.runtime-package.v1', 'files': files,
                'source_revision': subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                    check=True, capture_output=True, text=True).stdout.strip(),
                'excluded_dev_requirements': sorted(DEV_REQUIREMENTS)}
    (output / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    context = sub.add_parser('context'); context.add_argument('--output', type=Path, required=True)
    build = sub.add_parser('build'); build.add_argument('--tag', required=True)
    args = parser.parse_args()
    if args.action == 'context':
        manifest = create_context(ROOT, args.output)
        print(json.dumps({'files': len(manifest['files']), 'context': str(args.output)}))
        return
    if not re.fullmatch(r'munimjee-v1-runtime:[a-z0-9][a-z0-9_.-]{0,100}', args.tag):
        parser.error('Use a unique local munimjee-v1-runtime:<tag> name')
    if subprocess.run(['docker', 'image', 'inspect', args.tag], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        parser.error('Refusing to replace an existing image tag')
    with tempfile.TemporaryDirectory(prefix='munimjee-v1-context-') as temporary:
        manifest = create_context(ROOT, Path(temporary) / 'context')
        print(json.dumps({'files':len(manifest['files']), 'tag':args.tag}), flush=True)
        # Legacy builder honors CPU/memory constraints; do not mutate daemon settings.
        subprocess.run(['docker', 'build', '--memory', '1536m', '--cpu-period', '100000',
            '--cpu-quota', '100000', '--tag', args.tag, str(Path(temporary) / 'context')],
            check=True, env={**os.environ, 'DOCKER_BUILDKIT':'0'}, timeout=900)

if __name__ == '__main__':
    main()
