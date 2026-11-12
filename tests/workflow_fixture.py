"""Read production workflow inputs for the materialized distribution."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / '.github/workflows/W1700K.yaml'
WORKFLOW = ROOT / '.github/workflows/build-firmware.yaml'


def distribution_inputs():
    entry = yaml.safe_load(ENTRY.read_text())
    return [job['with'] for job in entry['jobs'].values()]


def selected_inputs():
    system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
    return next(row for row in distribution_inputs() if row['system'] == system)
