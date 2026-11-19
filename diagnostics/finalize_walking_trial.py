"""Apply the user's route clarification and check the completed trial artifacts."""
import hashlib
import json
from pathlib import Path
import serial

FOLDER=Path(__file__).resolve().parent/'trials/walking_001_20261119_233028_983555'
note=json.loads((FOLDER/'route_note.json').read_text(encoding='utf-8'))
assert '?' not in note['interpretation']
manifest=json.loads((FOLDER/'manifest.json').read_text(encoding='utf-8'))
manifest.update(actual_route_note=note['interpretation'],actual_route_user_original=note['user_original'],
                actual_route_label=note['trial_label'])
(FOLDER/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
root=Path(__file__).resolve().parents[1]
for relative,expected in [
 ('esp-csi/examples/get-started/tools/csi_data_read_parse.py','9456a557c499b47787cf6b2078fd3e7437cab568c9b031c2c3efd32bebe20b69'),
 ('esp-csi/examples/get-started/csi_send/main/app_main.c','7355e54fce0577ccd033755eb02e6b262af1db3f5e11c6d1e89b48364a2dcf0f')]:
    assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==expected,relative
with serial.Serial('COM7',921600,timeout=.1) as port:
    assert port.is_open
assert not port.is_open
(FOLDER/'final_verification.json').write_text(json.dumps(dict(source_unchanged=True,tx_unchanged=True,
    port_reopened_and_released=True,actual_route_recorded=True,firmware_flashing=False,
    threshold_tuning=False,github_push=False),indent=2),encoding='utf-8')
print('ROUTE_SOURCE_AND_PORT_VERIFIED')
