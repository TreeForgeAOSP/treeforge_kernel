#!/usr/bin/env python3
"""Repository-local TreeForge release workflow. No shared manager/runtime dependency.

This identical source is *vendored independently* by each component repository.
`./release prepare` stays owned by the component's existing release lifecycle.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.name
SLUGS = {
    'treeforge_rootd': 'TreeForgeDEV/treeforge_rootd',
    'treeforge_managerd': 'TreeForgeDEV/treeforge_managerd',
    'treeforge_transactiond': 'TreeForgeDEV/treeforge_transactiond',
    'treeforge_sepolicy': 'TreeForgeDEV/treeforge_sepolicy',
    'treeforge_manager': 'TreeForgeDEV/treeforge_manager',
    'treeforge_bootstrap': 'TreeForgeAOSP/treeforge_bootstrap',
    'pixel_partitioner': 'TreeForgeDEV/pixel_partitioner',
    'treeforge_kernel': 'TreeForgeAOSP/treeforge_kernel',
    'treeforge_bootstrap_framebuffer': 'TreeForgeAOSP/treeforge_bootstrap_framebuffer',
    'treeforge_bootstrap_menu': 'TreeForgeAOSP/treeforge_bootstrap_menu',
    'treeforge_toolchain': 'TreeForgeAOSP/treeforge_toolchain',
}
TITLES = {
    'treeforge_rootd': 'TreeForge Root Daemon',
    'treeforge_managerd': 'TreeForge Manager Daemon',
    'treeforge_transactiond': 'TreeForge Transaction Daemon',
    'treeforge_sepolicy': 'TreeForge SELinux',
    'treeforge_manager': 'TreeForge Manager',
    'treeforge_bootstrap': 'TreeForge Bootstrap',
    'pixel_partitioner': 'Pixel Partitioner',
    'treeforge_kernel': 'TreeForge Kernel',
    'treeforge_bootstrap_framebuffer': 'TreeForge Bootstrap Framebuffer',
    'treeforge_bootstrap_menu': 'TreeForge Boot Menu',
    'treeforge_toolchain': 'TreeForge Toolchain',
}
VERSION_RE = re.compile(r'v\d+\.\d+(?:\.\d+)?(?:b\d+)?\Z')
KERNEL_PREFIX_RE = re.compile(r'(?P<prefix>r[0-9.]+-)v(?P<body>\d+\.\d+(?:\.\d+)?(?:b\d+)?)\Z')
OWNER = 'skelitonlord'


class Refusal(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refusal(message)


def cmd(args: list[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd or ROOT, text=True, capture_output=True, check=check)


def git(*args: str) -> str:
    return cmd(['git', *args]).stdout.strip()


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return cmd(['gh', *args], check=check)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def version_file() -> Path:
    return ROOT / 'VERSION'


def version_info() -> tuple[str, str]:
    """Return (complete component version, editable version body)."""
    raw = version_file().read_text().strip()
    if REPO == 'treeforge_bootstrap':
        match = re.search(r'^TREEFORGE_BOOTSTRAP_VERSION=(\S+)\s*$', raw, re.M)
        require(match is not None, 'Bootstrap VERSION missing')
        v = match.group(1)
    elif REPO == 'treeforge_bootstrap_menu':
        menu = re.search(r'^TREEFORGE_BOOT_MENU_VERSION=(\S+)$', raw, re.M)
        manager = re.search(r'^TREEFORGE_BOOT_MANAGER_VERSION=(\S+)$', raw, re.M)
        require(menu is not None and manager is not None and menu.group(1) == manager.group(1),
                'Boot Menu/Boot Manager versions must agree')
        v = menu.group(1)
    else:
        v = raw
    if REPO == 'treeforge_kernel':
        match = KERNEL_PREFIX_RE.fullmatch(v)
        require(match is not None, 'invalid Kernel version prefix')
        return v, 'v' + match.group('body')
    require(VERSION_RE.fullmatch(v) is not None, f'invalid component VERSION: {v!r}')
    return v, v


def normalize(text: str) -> str:
    value = text.strip()
    if not value.startswith('v'):
        value = 'v' + value
    require(VERSION_RE.fullmatch(value) is not None, f'invalid version {text!r}')
    return value


def component_version(normal: str) -> str:
    if REPO == 'treeforge_kernel':
        current, _ = version_info()
        return current.split('-v', 1)[0] + '-' + normal
    return normal


def suggest_next(v: str) -> str:
    match = re.fullmatch(r'v(\d+)\.(\d+)(?:\.(\d+))?(?:b(\d+))?', v)
    require(match is not None, 'unsupported version for suggestion')
    major, minor, patch, beta = match.groups()
    if beta is not None:
        return f'v{major}.{minor}' + (f'.{patch}' if patch is not None else '') + f'b{int(beta)+1}'
    if patch is not None:
        return f'v{major}.{minor}.{int(patch)+1}'
    return f'v{major}.{minor}.1'


def version_order(version: str) -> tuple[int, int, int, int, int]:
    normal = normalize(version)
    match = re.fullmatch(r'v(\d+)\.(\d+)(?:\.(\d+))?(?:b(\d+))?', normal)
    require(match is not None, f'invalid semantic version: {version}')
    major, minor, patch, beta = match.groups()
    # A beta of an equivalent version sorts *before* the stable release.
    return int(major), int(minor), int(patch or 0), int(beta is None), int(beta or 0)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')


def expected_release_branch() -> str:
    # Pixel Partitioner is developed/released from its authoritative development branch.
    # Every other currently normalized TreeForge repository uses main.
    return 'development' if REPO == 'pixel_partitioner' else 'main'


def verify_clean_main_and_remote() -> str:
    branch = expected_release_branch()
    require(git('branch', '--show-current') == branch, f'release requires {branch} branch')
    require(not git('status', '--porcelain=v1', '--untracked-files=all'), 'worktree must be clean')
    slug = SLUGS[REPO]
    require(git('remote', 'get-url', 'origin') == f'git@github.com:{slug}.git', 'origin SSH slug mismatch')
    require(not cmd(['git', 'config', '--get', 'core.sshCommand'], check=False).stdout.strip(),
            'git core.sshCommand override not allowed')
    cmd(['git', 'fetch', 'origin', branch])
    head = git('rev-parse', 'HEAD')
    require(head == git('rev-parse', f'origin/{branch}'), f'HEAD does not equal origin/{branch}')
    return head


def check_owner() -> None:
    forbidden = ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_HOST', 'GH_ENTERPRISE_TOKEN',
                 'GITHUB_ACTIONS', 'GIT_SSH', 'GIT_SSH_COMMAND')
    require(not any(os.environ.get(k) for k in forbidden), 'ambient GitHub/SSH auth override forbidden')
    require(os.geteuid() != 0, 'do not publish as root')
    require(sys.stdin.isatty() and sys.stdout.isatty(), 'publishing requires real interactive TTY')
    who = gh('api', 'user', '--jq', '.login').stdout.strip()
    require(who == OWNER, f'GitHub CLI login is {who}, expected {OWNER}')
    proc = cmd(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-T', 'git@github.com'], check=False)
    require(proc.returncode == 1 and f'Hi {OWNER}! You\'ve successfully authenticated' in (proc.stdout + proc.stderr),
            'GitHub SSH identity is not the expected owner')
    full_name = gh('api', f'repos/{SLUGS[REPO]}', '--jq', '.full_name').stdout.strip()
    require(full_name == SLUGS[REPO], 'GitHub repository identity mismatch')
    print('OWNER_GITHUB_IDENTITY=PASS')


def remote_http(path: str) -> int:
    response = gh('api', '-i', path, check=False)
    combined = response.stdout + '\n' + response.stderr
    matches = re.findall(r'(?im)^HTTP/(?:1\.1|2(?:\.0)?|3)\s+(\d{3})\b', combined)
    require(bool(matches), f'GitHub HTTP status unverified for {path}: {combined[:400]!r}')
    status = int(matches[-1])
    require(status in (200, 404), f'GitHub API unexpectedly returned {status} for {path}')
    return status


def ensure_tag_available(tag: str) -> None:
    require(cmd(['git', 'show-ref', '--verify', '--quiet', f'refs/tags/{tag}'], check=False).returncode != 0,
            f'local tag already exists: {tag}')
    tags = cmd(['git', 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}'])
    require(not tags.stdout.strip(), f'Git remote tag already exists: {tag}')
    slug = SLUGS[REPO]
    require(remote_http(f'repos/{slug}/git/ref/tags/{tag}') == 404, f'remote tag exists: {tag}')
    require(remote_http(f'repos/{slug}/releases/tags/{tag}') == 404, f'GitHub release exists: {tag}')
    print(f'REMOTE_TAG_AND_RELEASE=AVAILABLE:{tag}')


def read_provider_identity() -> dict:
    # Kernel uses a generation lifecycle rather than current development-provider.
    if REPO == 'treeforge_kernel':
        return {}
    base = ROOT / 'out' / ('development-artifact' if REPO == 'treeforge_manager' else 'development-provider') / 'current'
    metadata = base / ('development-artifact.json' if REPO == 'treeforge_manager' else 'development-provider.json')
    if not metadata.is_file():
        # Check known alternate Manager development-artifact names without pretending they are trusted.
        raise Refusal(f'accepted development provenance missing at {metadata}')
    doc = json.loads(metadata.read_text())
    head = git('rev-parse', 'HEAD')
    require(doc.get('source_commit') == head, f'development artifact source commit mismatch: {doc.get("source_commit")} != {head}')
    require(doc.get('source_dirty') is False, 'development artifact was built dirty')
    require(doc.get('channel') == 'development' and doc.get('release_eligible') is False,
            'development provenance channel invalid')
    built, _ = version_info()
    require(doc.get('version') == built, f'provider VERSION mismatch: {doc.get("version")} != {built}')
    return doc


def staged_assets(tag: str) -> list[Path]:
    assets = ROOT / 'out' / 'releases' / tag / 'assets'
    require(assets.is_dir(), f'no prepared release assets: {assets}; run ./release prepare')
    files = sorted(p for p in assets.iterdir() if p.is_file())
    require(bool(files), 'empty prepared release')
    sums = assets / 'SHA256SUMS'
    require(sums.is_file(), f'{REPO}: staged SHA256SUMS missing')
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'([a-f0-9]{64})\s+\*?(.+)', line)
        require(match is not None, 'malformed SHA256SUMS line')
        rel = Path(match.group(2))
        require(not rel.is_absolute() and '..' not in rel.parts, 'unsafe checksum path')
        path = assets / rel
        require(path.is_file() and sha(path) == match.group(1), f'checksum mismatch: {rel}')
    print(f'STAGED_ASSETS=PASS COUNT={len(files)}')
    return files


def notes_text(tag: str, channel: str) -> str:
    text = (f'# {TITLES[REPO]} {tag}\n\n'
            f'Release channel: {channel}\n\n'
            'Clean, source-traced TreeForge release. Artifacts are promoted without rebuilding.\n')
    if REPO in ('treeforge_rootd', 'treeforge_managerd', 'treeforge_manager'):
        text += ('\n## Known bugs:\n\n- Structured rootd operation results are currently limited to 8 KiB. '
                 'Large future installed-family inventory results may be unavailable in Manager. '
                 'Deferred to runtime/update-engine work.\n')
    if REPO == 'treeforge_bootstrap':
        text += ('\n## Known bugs:\n\n- Touchscreen bring-up is broken through the fastbootd '
                 'transport path. Deferred to future Bootstrap development.\n')
    return text


def prepare_no_rebuild(tag: str) -> list[Path]:
    # Fail before invoking legacy prepare if the selected version does not match the build.
    built, _ = version_info()
    require(tag == built, f'chosen release {tag} differs from built VERSION {built}; no relabel/rebuild allowed')
    if REPO != 'treeforge_kernel':
        read_provider_identity()
    command = ['bash', str(ROOT / 'release'), 'prepare']
    if (ROOT / 'out' / 'releases' / tag / 'assets').exists():
        # Never implicitly delete a previously prepared release.
        return staged_assets(tag)
    proc = subprocess.run(command, cwd=ROOT, text=True)
    require(proc.returncode == 0, f'legacy release preparation refused, RC={proc.returncode}')
    return staged_assets(tag)


def update_next_version(published_tag: str) -> None:
    _, current_body = version_info()
    suggest = suggest_next(current_body)
    answer = input(f'Next development version [{suggest}] (blank accepts; skip to defer): ').strip()
    if answer.lower() == 'skip':
        print('NEXT_VERSION=DEFERRED; published release remains valid')
        return
    next_body = normalize(answer or suggest)
    require(version_order(next_body) > version_order(current_body),
            f'next development version {next_body} must be newer than published {current_body}')
    next_version = component_version(next_body)
    raw = version_file().read_text()
    if REPO == 'treeforge_bootstrap':
        changed = re.sub(r'(?m)^TREEFORGE_BOOTSTRAP_VERSION=\S+$',
                         f'TREEFORGE_BOOTSTRAP_VERSION={next_version}', raw, count=1)
    elif REPO == 'treeforge_bootstrap_menu':
        changed = re.sub(r'(?m)^TREEFORGE_BOOT_MENU_VERSION=\S+$',
                         f'TREEFORGE_BOOT_MENU_VERSION={next_version}', raw)
        changed = re.sub(r'(?m)^TREEFORGE_BOOT_MANAGER_VERSION=\S+$',
                         f'TREEFORGE_BOOT_MANAGER_VERSION={next_version}', changed)
    else:
        changed = next_version + '\n'
    require(changed != raw, 'VERSION not changed')
    require(not git('status', '--porcelain=v1', '--untracked-files=all'),
            'post-publish worktree is not clean')
    originals: dict[Path, str] = {version_file(): raw}
    files = ['VERSION']
    if REPO == 'treeforge_manager':
        code = ROOT / 'ANDROID_VERSION_CODE'
        code_raw = code.read_text()
        require(code_raw.strip().isdigit(), 'invalid Android VERSION_CODE')
        originals[code] = code_raw
        files.append('ANDROID_VERSION_CODE')
    try:
        version_file().write_text(changed)
        if REPO == 'treeforge_manager':
            code.write_text(f'{int(originals[code].strip()) + 1}\n')
        git('add', '--', *files)
        # Do not permit repository-local hooks to rebuild during a release.
        cmd(['git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m',
             f'Start {next_version} development after {published_tag}'])
    except Exception as exc:
        # No remote rollback or tag deletion; restore only the local pending files.
        for path, contents in originals.items():
            path.write_text(contents)
        cmd(['git', 'reset', '--quiet', 'HEAD', '--', *files], check=False)
        raise Refusal(f'release published but VERSION commit failed (local files restored): {exc}') from exc
    print(f'NEXT_DEVELOPMENT_VERSION={next_version}')
    print('NEXT_VERSION_COMMIT=LOCAL_ONLY (not pushed)')


def publication_receipt_path(tag: str) -> Path:
    return ROOT / 'out' / 'releases' / tag / 'publication.json'


def verify_published(tag: str, files: list[Path], channel: str) -> None:
    slug = SLUGS[REPO]
    expected_prerelease = channel == 'prerelease'
    view = json.loads(gh('release', 'view', tag, '--repo', slug, '--json', 'tagName,isDraft,isPrerelease').stdout)
    require(view.get('tagName') == tag and view.get('isDraft') is False
            and view.get('isPrerelease') is expected_prerelease, 'published GitHub release state mismatch')
    remote_tag = cmd(['git', 'ls-remote', 'origin', f'refs/tags/{tag}^{{}}']).stdout.strip().split()
    require(remote_tag and remote_tag[0] == git('rev-parse', 'HEAD'), 'published tag commit mismatch')
    dest = ROOT / 'out' / 'release-redownload' / f'{tag}-{stamp()}'
    dest.mkdir(parents=True, exist_ok=False)
    gh('release', 'download', tag, '--repo', slug, '--dir', str(dest))
    expected = {p.name for p in files}
    actual = {p.name for p in dest.iterdir() if p.is_file()}
    require(expected == actual, f'published asset names mismatch: expected={expected}, actual={actual}')
    for p in files:
        require(sha(p) == sha(dest / p.name), f'published byte mismatch: {p.name}')
    print(f'GITHUB_PUBLISHED_BYTES=PASS COUNT={len(files)}')


def publish() -> None:
    require(REPO in SLUGS, f'unrecognized release repository: {REPO}')
    built, body = version_info()
    require(sys.stdin.isatty() and sys.stdout.isatty(), 'release publishing requires interactive TTY')
    print(f'REPOSITORY={SLUGS[REPO]}')
    print(f'BUILT_VERSION={built}')
    raw = input(f'Enter release version [{body}]: ').strip()
    version = normalize(raw or body)
    tag = component_version(version)
    require(tag == built, f'requested {tag}, built {built}; cannot change release version without rebuilding')
    print('Release channel: 1) Stable  2) Beta  3) Pre-release')
    selected = input('Select release channel [2]: ').strip() or '2'
    require(selected in ('1', '2', '3'), 'invalid channel selection')
    channel = {'1': 'stable', '2': 'beta', '3': 'prerelease'}[selected]
    if channel == 'beta' and 'b' not in version:
        print('NOTE: Beta channel selected for a non-beta version; channel is explicit.')
    if channel == 'stable' and 'b' in version:
        print('NOTE: Stable channel selected for beta-numbered version; channel is explicit.')
    head = verify_clean_main_and_remote()
    check_owner()
    ensure_tag_available(tag)
    files = prepare_no_rebuild(tag)
    # Create standalone metadata *outside* provider payload, preserving exact development bytes.
    note_dir = ROOT / 'out' / 'releases' / tag
    note_dir.mkdir(parents=True, exist_ok=True)
    notes = note_dir / 'RELEASE_NOTES.md'
    if not notes.exists():
        notes.write_text(notes_text(tag, channel))
    else:
        require(f'Release channel: {channel}' in notes.read_text(), 'existing notes channel conflicts with selected channel')
    manifest = note_dir / 'treeforge-release-channel.json'
    new_channel_metadata = json.dumps({'schema': 'treeforge.release-channel.v1', 'version': tag,
                                       'channel': channel, 'source_commit': head,
                                       'component': REPO}, indent=2, sort_keys=True) + '\n'
    if manifest.exists():
        require(manifest.read_text() == new_channel_metadata, 'release-channel metadata conflicts with candidate')
    else:
        manifest.write_text(new_channel_metadata)
    uploaded = files + [manifest]
    print(f'RELEASE_CHANNEL={channel}; GITHUB_PRERELEASE={str(channel=="prerelease").lower()}')
    print(f'RELEASE_NOTES={notes}')
    # Extra authorization at the last possible point.
    expected = f'PUBLISH {SLUGS[REPO]} {tag}'
    answer = input(f'Type exactly "{expected}" to publish: ')
    require(answer == expected, 'publication cancelled; no GitHub mutations')
    # Revalidate source and remote state after the interactive authorization.
    require(git('rev-parse', 'HEAD') == head and not git('status', '--porcelain=v1', '--untracked-files=all'),
            'source changed before publication')
    ensure_tag_available(tag)
    print('=== PUBLICATION BEGINS: no automatic remote rollback ===')
    git('tag', '-a', tag, '-m', f'{TITLES[REPO]} {tag}', head)
    cmd(['git', 'push', 'origin', f'refs/tags/{tag}'])
    # Ensure tag immutable target before attempting release create.
    remote_tag = cmd(['git', 'ls-remote', 'origin', f'refs/tags/{tag}^{{}}']).stdout.strip().split()
    require(remote_tag and remote_tag[0] == head, 'remote tag commit mismatch; manual recovery required')
    args = ['release', 'create', tag, *[str(p) for p in uploaded], '--repo', SLUGS[REPO],
            '--verify-tag', '--title', f'{TITLES[REPO]} {tag}', '--notes-file', str(notes)]
    if channel == 'prerelease':
        args.extend(['--prerelease', '--latest=false'])
    elif channel == 'beta':
        args.append('--latest=false')
    else:
        args.append('--latest')
    gh(*args)
    verify_published(tag, uploaded, channel)
    receipt = publication_receipt_path(tag)
    receipt.write_text(json.dumps({'schema': 'treeforge.release-publication.v1',
                                   'repository': SLUGS[REPO], 'tag': tag, 'channel': channel,
                                   'head': head, 'verified_at': stamp()}, sort_keys=True, indent=2)+'\n')
    print('PUBLISH=PASS')
    print('NOTE: only now may the next development version be changed.')
    update_next_version(tag)


def resume(tag: str) -> None:
    # Recover only *verified* completed publication; never repeat remote create.
    receipt = publication_receipt_path(tag)
    require(receipt.is_file(), f'no verified publication receipt for {tag}')
    data = json.loads(receipt.read_text())
    require(data.get('repository') == SLUGS[REPO] and data.get('tag') == tag, 'receipt mismatch')
    current, _ = version_info()
    require(current == tag, 'local VERSION already advanced or no longer matches release')
    require(git('rev-parse', 'HEAD') == data.get('head'), 'HEAD mismatch for recovery')
    files = staged_assets(tag) + [ROOT / 'out' / 'releases' / tag / 'treeforge-release-channel.json']
    verify_published(tag, files, data['channel'])
    print('VERIFIED_PUBLICATION_RECOVERY=PASS')
    update_next_version(tag)


def contract_readonly() -> None:
    built, _ = version_info()
    head = git('rev-parse', 'HEAD')
    branch = git('branch', '--show-current')
    clean = not git('status', '--porcelain=v1', '--untracked-files=all')
    print(f'REPOSITORY={SLUGS[REPO]}')
    print(f'SOURCE_BRANCH={branch}')
    print(f'EXPECTED_RELEASE_BRANCH={expected_release_branch()}')
    print(f'SOURCE_COMMIT={head}')
    print(f'SOURCE_CLEAN={str(clean).upper()}')
    print(f'COMPONENT_VERSION={built}')
    if REPO == 'treeforge_kernel':
        print('ACCEPTED_PROVIDER_CONTRACT=KERNEL_GENERATION_LIFECYCLE; no current development-provider record')
        return
    base = ROOT / 'out' / ('development-artifact' if REPO == 'treeforge_manager' else 'development-provider') / 'current'
    metadata = base / ('development-artifact.json' if REPO == 'treeforge_manager' else 'development-provider.json')
    if not metadata.is_file():
        print('ACCEPTED_PROVIDER_CONTRACT=NO_CURRENT_METADATA')
        return
    try:
        doc = json.loads(metadata.read_text())
    except (ValueError, OSError) as exc:
        print(f'ACCEPTED_PROVIDER_CONTRACT=INVALID_METADATA:{exc}')
        return
    provider_commit = doc.get('source_commit')
    provider_version = doc.get('version')
    print(f'ACCEPTED_PROVIDER_SOURCE_COMMIT={provider_commit}')
    print(f'ACCEPTED_PROVIDER_VERSION={provider_version}')
    print(f'ACCEPTED_PROVIDER_SOURCE_CLEAN={doc.get("source_dirty") is False}')
    print('ACCEPTED_PROVIDER_MATCHES_CURRENT_HEAD=' + str(provider_commit == head).upper())
    print('ACCEPTED_PROVIDER_MATCHES_CURRENT_VERSION=' + str(provider_version == built).upper())
    if provider_commit != head:
        print('RELEASE_CONTRACT=HISTORICAL_ACCEPTED_PROVIDER; no provenance bypass authorized')
    else:
        print('RELEASE_CONTRACT=SOURCE_COMMIT_ALIGNED; downstream validation still required')


def main(argv: list[str]) -> int:
    require(REPO in SLUGS, f'unrecognized repository: {REPO}')
    subcommand = argv[0] if argv else 'publish'
    if subcommand == 'status':
        built, _ = version_info()
        print(f'REPOSITORY={SLUGS[REPO]}')
        print(f'CURRENT_BUILT_VERSION={built}')
        print(f'SOURCE_COMMIT={git("rev-parse", "HEAD")}')
        print('SOURCE_CLEAN=' + ('YES' if not git('status', '--porcelain=v1','--untracked-files=all') else 'NO'))
        print('PUBLISHED=NO')
        return 0
    if subcommand in ('publish', 'interactive'):
        require(len(argv) <= 1, 'usage: ./release [publish]')
        publish()
        return 0
    if subcommand == 'contract':
        require(len(argv) == 1, 'usage: ./release contract')
        contract_readonly()
        return 0
    if subcommand == 'verify':
        built, _ = version_info()
        require(len(argv) <= 1, 'usage: ./release verify')
        staged_assets(built)
        print('RELEASE_VERIFY=PASS')
        return 0
    if subcommand == 'resume':
        require(len(argv) == 2, 'usage: ./release resume VERSION')
        resume(component_version(normalize(argv[1])))
        return 0
    raise Refusal('usage: ./release [prepare [--force] | verify | publish | status | contract | resume VERSION]')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (Refusal, subprocess.CalledProcessError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f'TREEFORGE_RELEASE=BLOCKED: {error}', file=sys.stderr)
        sys.exit(1)
