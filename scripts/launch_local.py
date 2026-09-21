"""Open the installed local portfolio. Running without arguments shows a menu."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
VIEWS = {
    'tour': ROOT / 'reports/portfolio.html',
    'dashboard': ROOT / 'reports/dashboard.html',
    'screenshots': ROOT / 'screenshots/index.html',
    'powerbi': ROOT / 'powerbi/EnergyPredictiveMaintenance.pbip',
}

def check():
    import energy_failure
    from energy_failure.assistant_server import make_server
    required = [*VIEWS.values(), ROOT / 'artifacts/model.joblib', ROOT / 'notebooks/01_explore.ipynb']
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError('Missing project files: ' + ', '.join(missing))
    module_path = Path(energy_failure.__file__).resolve()
    if not module_path.is_relative_to(ROOT / 'src'):
        raise RuntimeError('Python resolved another project copy: ' + str(module_path))
    server = make_server(ROOT, 'peace.manager@portfolio.example', 0, 'rules', None)
    server.server_close()
    print(json.dumps({'project_root': str(ROOT), 'python': sys.executable,
                      'imported_package': str(module_path), 'required_files': 'pass',
                      'assistant_server_creation': 'pass',
                      'screenshots': len(json.loads((ROOT / 'screenshots/capture-manifest.json').read_text(encoding='utf-8'))['entries'])}, indent=2))

def assistant(no_browser):
    from energy_failure.assistant_server import make_server
    try:
        server = make_server(ROOT, 'peace.manager@portfolio.example', 8790, 'rules', None)
    except OSError as error:
        if error.errno not in {48, 98, 10048} and getattr(error, 'winerror', None) != 10048:
            raise
        server = make_server(ROOT, 'peace.manager@portfolio.example', 0, 'rules', None)
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'Assistant: {url}', flush=True)
    print('Synthetic Peace River scope. Rules-based mode; no paid API. Ctrl+C stops this server.', flush=True)
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('view', nargs='?', choices=[*VIEWS, 'assistant', 'notebook', 'check', 'tests'])
    parser.add_argument('--no-browser', action='store_true', help='Start the assistant or notebook server without opening a browser.')
    args = parser.parse_args()
    os.chdir(ROOT)
    view = args.view
    if view is None:
        print('Energy - Predictive Equipment Failure\n')
        print('1. Portfolio tour\n2. Interactive dashboard companion\n3. Evidence assistant\n4. Screenshot gallery\n5. EDA notebook in JupyterLab\n6. Power BI project\n7. Run automated tests\nQ. Exit\n')
        choice = input('Choose a view: ').strip().lower()
        if choice == 'q':
            return
        view = {'1': 'tour', '2': 'dashboard', '3': 'assistant', '4': 'screenshots', '5': 'notebook', '6': 'powerbi', '7': 'tests'}.get(choice)
        if view is None:
            parser.error('Choose 1 to 7 or Q.')
    if view == 'check':
        check()
    elif view == 'assistant':
        assistant(args.no_browser)
    elif view == 'notebook':
        if not (ROOT / 'data/processed/modeling_frame.csv').is_file():
            raise SystemExit('Generate the local analysis data first: python -m energy_failure.pipeline --output-root .\nThen refresh the README: python scripts/build_readme.py\nSee START_HERE.md for the full reproduction steps.')
        notebook_env = os.environ.copy()
        for variable, folder in [('JUPYTER_RUNTIME_DIR', 'jupyter-runtime'), ('JUPYTER_CONFIG_DIR', 'jupyter-config'), ('IPYTHONDIR', 'ipython')]:
            location = ROOT / 'build' / folder
            location.mkdir(parents=True, exist_ok=True)
            notebook_env[variable] = str(location)
        command = [sys.executable, '-m', 'jupyterlab', str(ROOT / 'notebooks/01_explore.ipynb')]
        if args.no_browser:
            command.append('--no-browser')
        raise SystemExit(subprocess.call(command, cwd=ROOT, env=notebook_env))
    elif view == 'tests':
        temporary = (ROOT / 'build/test-runs' / uuid.uuid4().hex).resolve()
        if not temporary.is_relative_to(ROOT) or temporary.exists():
            raise RuntimeError('Test temporary path is unsafe or already exists.')
        temporary.parent.mkdir(parents=True, exist_ok=True)
        raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q', '--basetemp', str(temporary), '--junitxml', str(ROOT / 'reports/local-setup-tests.xml')], cwd=ROOT))
    elif view == 'powerbi':
        subprocess.run([sys.executable, str(ROOT / 'powerbi/configure_local.py')], cwd=ROOT, check=True)
        try:
            os.startfile(VIEWS[view])
        except OSError as error:
            raise SystemExit('Install/open Power BI Desktop, then open ' + str(VIEWS[view]) + '\n' + str(error))
    else:
        webbrowser.open(VIEWS[view].as_uri())

if __name__ == '__main__':
    main()
