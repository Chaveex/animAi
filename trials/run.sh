#!/bin/sh
# usage: run.sh <sprite dir name> ; runs animate/validate/export for the three presets
s=$1
for p in idle walk attack; do
  python -m animai.cli.main animate trials/$s/rig.json --preset $p > trials/$s/animate_$p.json
  python -m animai.cli.main validate trials/$s/frames/$p > trials/$s/validate_$p.json
  python -m animai.cli.main export trials/$s/frames/$p --format spritesheet > trials/$s/export_$p.json
  python - "$s" "$p" <<'PY'
import json,sys
s,p=sys.argv[1:]
a=json.load(open(f'trials/{s}/animate_{p}.json')); v=json.load(open(f'trials/{s}/validate_{p}.json')); e=json.load(open(f'trials/{s}/export_{p}.json'))
o=a['outputs']
print(f"[{s}/{p}] animate ok={a['ok']} frames={o.get('frame_count')} dur={o.get('durations_ms')} canvas={o.get('canvas')} pivot={o.get('pivot')} warn={a['warnings']} err={a['error']}")
print(f"   validate ok={v['ok']} failed={v['outputs'].get('failed')} warn={v['warnings']}")
if not v['ok']:
    r=json.load(open(v['outputs']['report']))
    for c in r['checks']:
        if not c['pass']: print('     ',c)
print(f"   export ok={e['ok']} warn={e['warnings']} err={e['error']}")
PY
done
