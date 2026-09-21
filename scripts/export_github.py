"""Export a reviewable GitHub ZIP while preserving private local generated files.

This does not commit, push, delete working files or rewrite Git history.
Run --check --verify-tracked in CI to reject accidentally tracked raw data.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import zipfile

DIRECTORIES = {'.git', '.venv', '.pbi', '__pycache__', '.pytest_cache', 'build', 'dist', 'node_modules'}
LOCAL_FILES = {'reports/generalization_scores.csv', 'reports/operations_visits.csv',
               '_readme_preview.html',
               'artifacts/azure-local-smoke/predictions.csv', 'reports/powerbi-local-setup-check.json',
               'artifacts/batch-predictions.csv',
               'docs/github-about.md',
               'reports/publication-review.json', 'reports/powerbi-validation.md',
               'reports/powerbi-generator-check.json', 'reports/powerbi-layout-proof.html',
               'reports/figures/assistant_demo.png', 'reports/figures/reviewer_tour.png',
               'powerbi/energy_theme.json', 'powerbi/queries/qa_synonyms.json',
               'GITHUB_MANIFEST.json'}
PORTABLE_DATA_FOLDER = 'C:/Energy-Predictive-Equipment-Failure/data/processed/dashboard'
DATA_FOLDER_FILES = {
    'powerbi/EnergyPredictiveMaintenance.SemanticModel/definition/expressions.tmdl',
    'powerbi/queries/DataFolder.pq',
    'powerbi/model_contract.json',
}
MODEL_PREFIX = 'powerbi/EnergyPredictiveMaintenance.SemanticModel/'

def excluded(name):
    path = Path(name)
    parts = path.parts
    if any(part in DIRECTORIES or part.endswith('.egg-info') for part in parts):
        return True
    if 'tools' in parts and any(part in {'bin', 'obj'} for part in parts):
        return True
    if name.startswith('data/raw/'):
        return True
    # Keep the canonical TMDL/PBIR source; these are generated local mirrors.
    if name.startswith('powerbi/publication/'):
        return True
    if name.startswith('powerbi/queries/') and path.suffix == '.pq' and path.name != 'DataFolder.pq':
        return True
    if name.endswith('.zip.manifest.json'):
        return True
    if len(parts) == 3 and parts[:2] == ('data', 'processed') and (path.suffix in {'.csv', '.sqlite', '.db', '.parquet'} or '.sqlite-' in path.name):
        return True
    if name in LOCAL_FILES or name.startswith('reports/local-setup'):
        return True
    if path.name == '.env' or path.name.startswith('.env.') or path.name in {'localSettings.json', 'desktop.ini', 'Thumbs.db'}:
        return True
    return path.suffix.lower() in {'.zip', '.pending', '.sha256', '.pyc', '.pyo', '.log', '.xml'}

def publishable(root):
    kept, skipped = {}, []
    for folder, directories, names in os.walk(root):
        relative = Path(folder).relative_to(root)
        directories[:] = [name for name in directories if not excluded((relative / name / '_').as_posix())]
        for name in names:
            path = Path(folder) / name
            rel = path.relative_to(root).as_posix()
            if excluded(rel):
                skipped.append(rel)
            else:
                assert not path.is_symlink(), 'Symlink is not an exportable artifact: ' + rel
                kept[rel] = path
    return dict(sorted(kept.items())), skipped

def digest(data):
    return hashlib.sha256(data).hexdigest()

def publication_bytes(name, path):
    """Use a documented data-folder placeholder in the archive only.

    The installed project remains pointed at its local data. Normalization is
    deliberately limited to the three authoritative parameter representations;
    historical validation evidence is never silently relabelled as a new parse.
    """
    content = path.read_bytes()
    if name not in DATA_FOLDER_FILES:
        return content
    text = content.decode('utf-8-sig')
    if name.endswith('model_contract.json'):
        contract = json.loads(text)
        if not isinstance(contract.get('data_folder'), str):
            raise ValueError('Expected one data_folder string in ' + name)
        contract['data_folder'] = PORTABLE_DATA_FOLDER
        return (json.dumps(contract, indent=2) + '\n').encode('utf-8')
    prefix = r'(expression DataFolder\s*=\s*)' if name.endswith('.tmdl') else r'()'
    pattern = r'(?m)^' + prefix + r'"(?:[^"\r\n]|"")*"(?=\s+meta\b)'
    text, count = re.subn(pattern, lambda match: match.group(1) + '"' + PORTABLE_DATA_FOLDER + '"', text)
    if count != 1:
        raise ValueError('Expected exactly one DataFolder parameter in ' + name)
    return text.encode('utf-8')

def archive_tmdl_hash(contents):
    """Match validate_project.source_hash against the actual archived TMDL."""
    digest = hashlib.sha256()
    names = sorted(name for name in contents
                   if name.startswith(MODEL_PREFIX + 'definition/') and name.endswith('.tmdl'))
    if not names:
        raise ValueError('Publication is missing TMDL definitions.')
    for name in names:
        digest.update(name.removeprefix(MODEL_PREFIX).encode('utf-8'))
        digest.update(contents[name].decode('utf-8-sig').replace('\r\n', '\n').encode('utf-8'))
    return digest.hexdigest()

def prepare_publication(root, kept):
    """Normalize paths and retain genuine parser evidence for those bytes.

    The portable parser cache is created by an actual Microsoft TOM parse of a
    separate portable project copy. Its hash must still match all model source.
    It cannot authorize an unparsed model edit or manufacture parser evidence.
    """
    contents = {name: publication_bytes(name, path) for name, path in kept.items()}
    expected = archive_tmdl_hash(contents)
    for folder, label in [(root / 'powerbi', 'current model'),
                          (root / 'powerbi/publication', 'verified portable cache')]:
        evidence_path = folder / 'model_validation.json'
        snapshot_path = folder / 'model_snapshot.json'
        if not evidence_path.is_file() or not snapshot_path.is_file():
            continue
        evidence = json.loads(evidence_path.read_text(encoding='utf-8-sig'))
        if evidence.get('tmdlParsed') is True and evidence.get('tmdl_sha256') == expected:
            contents['powerbi/model_validation.json'] = evidence_path.read_bytes()
            contents['powerbi/model_snapshot.json'] = snapshot_path.read_bytes()
            return contents, {'status': 'pass', 'evidence_source': label,
                              'normalized_tmdl_sha256': expected,
                              'data_folder': PORTABLE_DATA_FOLDER}
    raise ValueError(
        'Portable Power BI parser evidence is missing or stale. No ZIP was created. '
        'Refresh powerbi/publication/model_validation.json and model_snapshot.json '
        'from a genuine TOM parse of a separate project copy using the documented '
        'portable DataFolder. Local files were not changed.'
    )

def validate(root, kept, verify_tracked):
    manifest = json.loads((root / 'screenshots/capture-manifest.json').read_text(encoding='utf-8'))
    images = manifest['entries']
    assert len(images) == len({entry['file'] for entry in images}) == 49
    assert all('screenshots/' + entry['file'] in kept for entry in images)
    for entry in images:
        if entry.get('sha256'):
            assert digest((root / 'screenshots' / entry['file']).read_bytes()) == entry['sha256']
    for required in ['README.md', 'START_HERE.md', 'data/README.md', 'artifacts/model.joblib',
                     '.github/workflows/ci.yml', 'powerbi/EnergyPredictiveMaintenance.pbip',
                     'data/processed/dashboard/scored_readings.csv', 'data/processed/dashboard/service_visits.csv',
                     'data/processed/dashboard/event_outcomes.csv', *sorted(DATA_FOLDER_FILES)]:
        assert required in kept, required
    tracked_status = 'not requested'
    if verify_tracked:
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
        bad = [name for name in tracked if name and name != 'GITHUB_MANIFEST.json' and excluded(name)]
        assert not bad, 'Generated/private files still tracked: ' + ', '.join(bad)
        tracked_status = 'pass'
    for name, path in kept.items():
        assert chr(0x2014) not in name, name
        assert path.stat().st_size < 25 * 1024 ** 2, 'File exceeds browser upload limit: ' + name
    return {'status': 'pass', 'payload_files': len(kept), 'screenshots': 49,
            'native_powerbi_screenshots': 8, 'raw_data_files_exported': 0,
            'training_intermediate_files_exported': 0, 'git_tracked_hygiene': tracked_status}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--verify-tracked', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    kept, skipped = publishable(root)
    result = validate(root, kept, args.verify_tracked)
    if args.check:
        try:
            _, proof = prepare_publication(root, kept)
        except ValueError as error:
            proof = {'status': 'requires_refresh', 'reason': str(error)}
        result['powerbi_publication_parser'] = proof
        print(json.dumps(result, indent=2))
        return
    output = (args.output or root.parent / 'Energy-Predictive-Equipment-Failure-GitHub-Ready.zip').resolve()
    manifest_output = output.with_suffix('.zip.manifest.json')
    checksum_output = output.with_suffix('.zip.sha256')
    assert not any(path.exists() for path in [output, manifest_output, checksum_output]), 'Preserve the existing archive and sidecars; choose another --output path.'
    output.parent.mkdir(parents=True, exist_ok=True)
    top = 'Energy-Predictive-Equipment-Failure'
    try:
        contents, parser_proof = prepare_publication(root, kept)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    result['powerbi_publication_parser'] = parser_proof
    payload = {name: {'sha256': digest(content), 'bytes': len(content)} for name, content in contents.items()}
    receipt = {'edition': 'GitHub publication without raw telemetry or training intermediates',
               'built_at_utc': datetime.now(timezone.utc).isoformat(),
               'scope': 'Archive payload integrity. This manifest is a sidecar, not part of the GitHub repository.',
               'data_policy': 'Curated processed synthetic dashboard inputs retained for runnable demos. Generate raw and training files locally.',
               'powerbi_data_setup': 'Archive parameters use the documented portable placeholder. Run python powerbi/configure_local.py after extraction. Source files are not modified; changing TMDL paths requires fresh TOM parsing before claiming current parser validation.',
               'validation': result, 'files': payload}
    manifest_content = (json.dumps(receipt, indent=2) + '\n').encode('utf-8')
    pending = output.with_suffix('.zip.pending')
    with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in contents.items():
            archive.writestr(top + '/' + name, content)
    with zipfile.ZipFile(pending) as archive:
        assert archive.testzip() is None
        assert len(archive.infolist()) == len(payload)
        for name, item in payload.items():
            assert digest(archive.read(top + '/' + name)) == item['sha256'], name
    pending.replace(output)
    manifest_output.write_bytes(manifest_content)
    fingerprint = digest(output.read_bytes())
    checksum_output.write_text(f'{fingerprint}  {output.name}\n', encoding='ascii')
    print(json.dumps({**result, 'archive': str(output), 'manifest_sidecar': str(manifest_output), 'archive_files': len(payload),
                      'bytes': output.stat().st_size, 'sha256': fingerprint,
                      'archive_crc_and_all_hashes': 'pass'}, indent=2))

if __name__ == '__main__':
    main()
