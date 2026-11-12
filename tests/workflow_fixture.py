"""Read the native production workflow for the materialized distribution."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTRY = WORKFLOW = ROOT / '.github/workflows/W1700K.yaml'
INPUT_ENV = {'system': 'SYSTEM', 'title': 'DISTRO_TITLE', 'tc': 'TC_PREFIX',
             'cc': 'CC_PREFIX', 'dl': 'DL_PREFIX', 'tb': 'TB_PREFIX'}


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def distribution_inputs():
    return [{key: job['env'][name] for key, name in INPUT_ENV.items()}
            for job in workflow()['jobs'].values()]


def build_job(document=None):
    system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
    return (workflow() if document is None else document)['jobs'][system]


def selected_inputs():
    env = build_job()['env']
    return {key: env[name] for key, name in INPUT_ENV.items()}
