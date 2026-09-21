"""Publication keeps local data intact and packages matching portable evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/export_github.py'
spec = importlib.util.spec_from_file_location('export_publication', SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    values = {
        'README.md': '# Reviewable portfolio\n',
        'data/raw/readings.csv': 'private local telemetry\n',
        'data/processed/modeling_frame.csv': 'private local features\n',
        'data/processed/dashboard/scored_readings.csv': 'asset_id,risk_score\nAB-001,0.2\n',
        'powerbi/model_contract.json': json.dumps({'data_folder': 'D:/Local Project/data', 'tables': {}}),
        'powerbi/queries/DataFolder.pq': '"D:/Local Project/data" meta [IsParameterQuery=true]\r\n',
        'powerbi/queries/Dim_Asset.pq': 'local generated query mirror\n',
        'powerbi/energy_theme.json': '{}',
        'reports/powerbi-layout-proof.html': '<h1>Local geometry preview</h1>',
        'reports/publication-review.json': '{}',
        'docs/github-about.md': '# Author setup notes\n',
        'GITHUB_MANIFEST.json': '{}',
        export.MODEL_PREFIX + 'definition/expressions.tmdl': 'expression DataFolder = "D:/Local Project/data" meta [IsParameterQuery=true]\r\n',
        export.MODEL_PREFIX + 'definition/model.tmdl': 'model Model\r\n\tculture: en-US\r\n',
    }
    for name, value in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode('utf-8'))
    return root


def add_proof(root, *, folder='publication', stale=False):
    kept, _ = export.publishable(root)
    contents = {name: export.publication_bytes(name, path) for name, path in kept.items()}
    fingerprint = export.archive_tmdl_hash(contents)
    target = root / 'powerbi' / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / 'model_validation.json').write_text(json.dumps({
        'tmdlParsed': True, 'tmdl_sha256': 'outdated' if stale else fingerprint,
    }), encoding='utf-8')
    (target / 'model_snapshot.json').write_text(json.dumps({
        'model': {'expressions': [{'name': 'DataFolder', 'expression': export.PORTABLE_DATA_FOLDER}]},
    }), encoding='utf-8')


def test_publication_excludes_raw_and_features_but_preserves_all_local_bytes(project):
    add_proof(project)
    before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    kept, _ = export.publishable(project)
    contents, proof = export.prepare_publication(project, kept)
    assert 'data/raw/readings.csv' not in contents
    assert 'data/processed/modeling_frame.csv' not in contents
    assert 'data/processed/dashboard/scored_readings.csv' in contents
    for local_only in ['powerbi/queries/Dim_Asset.pq', 'powerbi/energy_theme.json',
                       'reports/powerbi-layout-proof.html', 'reports/publication-review.json',
                       'docs/github-about.md', 'GITHUB_MANIFEST.json',
                       'powerbi/publication/model_validation.json', 'powerbi/publication/model_snapshot.json']:
        assert local_only not in contents
    for name in export.DATA_FOLDER_FILES:
        assert export.PORTABLE_DATA_FOLDER.encode() in contents[name]
        assert b'D:/Local Project/data' not in contents[name]
    assert proof['evidence_source'] == 'verified portable cache'
    after = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('state', ['missing', 'stale', 'changed_model'])
def test_missing_or_stale_parser_cache_blocks_export(project, state):
    if state != 'missing':
        add_proof(project, stale=state == 'stale')
    if state == 'changed_model':
        (project / (export.MODEL_PREFIX + 'definition/model.tmdl')).write_text('model Changed\n', encoding='utf-8')
    kept, _ = export.publishable(project)
    with pytest.raises(ValueError, match='parser evidence is missing or stale'):
        export.prepare_publication(project, kept)


def test_current_portable_parser_proof_does_not_require_a_cache(project):
    add_proof(project, folder='')
    kept, _ = export.publishable(project)
    _, proof = export.prepare_publication(project, kept)
    assert proof['evidence_source'] == 'current model'


@pytest.mark.parametrize('copies', [0, 2])
def test_parameter_normalization_requires_exactly_one_match(project, copies):
    name = export.MODEL_PREFIX + 'definition/expressions.tmdl'
    path = project / name
    path.write_text('expression DataFolder = "D:/data" meta [IsParameterQuery=true]\n' * copies, encoding='utf-8')
    with pytest.raises(ValueError, match='exactly one DataFolder'):
        export.publication_bytes(name, path)


def test_archive_manifest_hashes_normalized_bytes_and_matched_parser_proof(project, monkeypatch):
    add_proof(project)
    output = project.parent / 'publication.zip'
    # This fixture isolates export integrity from the repository's separate
    # screenshot-count/business-content validation.
    monkeypatch.setattr(export, 'validate', lambda *args: {'status': 'pass'})
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--root', str(project), '--output', str(output)])
    export.main()
    prefix = 'Energy-Predictive-Equipment-Failure/'
    with zipfile.ZipFile(output) as archive:
        receipt = json.loads(output.with_suffix('.zip.manifest.json').read_text(encoding='utf-8'))
        assert set(archive.namelist()) == {prefix + name for name in receipt['files']}
        assert prefix + 'GITHUB_MANIFEST.json' not in archive.namelist()
        for name, metadata in receipt['files'].items():
            content = archive.read(prefix + name)
            assert len(content) == metadata['bytes']
            assert hashlib.sha256(content).hexdigest() == metadata['sha256']
        for name in export.DATA_FOLDER_FILES:
            assert export.PORTABLE_DATA_FOLDER.encode() in archive.read(prefix + name)
        proof = json.loads(archive.read(prefix + 'powerbi/model_validation.json'))
        assert proof['tmdl_sha256'] == receipt['validation']['powerbi_publication_parser']['normalized_tmdl_sha256']
        assert not any('/data/raw/' in name for name in archive.namelist())
    assert (project / 'data/raw/readings.csv').is_file()


def test_actual_export_fails_before_creating_a_zip_with_stale_proof(project, monkeypatch):
    add_proof(project, stale=True)
    output = project.parent / 'blocked.zip'
    monkeypatch.setattr(export, 'validate', lambda *args: {'status': 'pass'})
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--root', str(project), '--output', str(output)])
    with pytest.raises(SystemExit, match='1'):
        export.main()
    assert not output.exists()
    assert not output.with_suffix('.zip.pending').exists()
