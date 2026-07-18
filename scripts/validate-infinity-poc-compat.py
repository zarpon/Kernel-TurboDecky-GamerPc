#!/usr/bin/env python3
"""Fail closed on harmful overlap between Infinity full series and POC Selector."""
from __future__ import annotations
import argparse,re
from pathlib import Path

def paths(text:str)->set[str]:
    return set(re.findall(r'^diff --git a/(\S+) b/\S+$',text,re.M))

def gpu_tail(text:str)->str:
    marker='Subject: [PATCH 4/6]'
    if marker not in text: raise SystemExit('Infinity GPU patch 4/6 marker missing')
    return text[text.index(marker):]

def main():
    p=argparse.ArgumentParser();p.add_argument('infinity',type=Path);p.add_argument('poc',type=Path);p.add_argument('--report',type=Path);a=p.parse_args()
    inf=a.infinity.read_text(errors='replace');poc=a.poc.read_text(errors='replace');gpu=gpu_tail(inf)
    inf_paths=paths(inf);gpu_paths=paths(gpu);poc_paths=paths(poc)
    bad_gpu={x for x in gpu_paths if not (x.startswith('drivers/gpu/drm/') or x.startswith('include/drm/'))}
    if bad_gpu: raise SystemExit(f'Infinity GPU series unexpectedly touches non-DRM paths: {sorted(bad_gpu)}')
    overlap=gpu_paths&poc_paths
    if overlap: raise SystemExit(f'Infinity GPU and POC touch the same files: {sorted(overlap)}')
    if any(x.startswith(('drivers/gpu/drm/','include/drm/')) for x in poc_paths): raise SystemExit('POC unexpectedly touches DRM/GPU paths')
    required_poc=['select_idle_cpu_poc','!sched_asym_cpucap_active()','poc_selector_active']
    for marker in required_poc:
        if marker not in poc: raise SystemExit(f'POC compatibility guard missing: {marker}')
    for marker in ['READ_ONCE(inf_p->infinity.futex_waiting)','READ_ONCE(inf_p->infinity.ema)']:
        if marker not in gpu: raise SystemExit(f'Infinity cross-scheduler marker missing: {marker}')
    if re.search(r'\bpoc_[A-Za-z0-9_]*\s*=',gpu): raise SystemExit('Infinity GPU series writes POC state')
    known_cpu_overlap={'kernel/sched/fair.c','kernel/sched/sched.h'}
    cpu_overlap=(inf_paths&poc_paths)-gpu_paths
    unexpected=cpu_overlap-known_cpu_overlap
    if unexpected: raise SystemExit(f'unexpected CPU-side Infinity/POC overlap: {sorted(unexpected)}')
    lines=[
      'Infinity/POC compatibility: PASS',
      f'Infinity files: {len(inf_paths)}',f'Infinity GPU files: {len(gpu_paths)}',f'POC files: {len(poc_paths)}',
      f'GPU/POC direct overlap: {sorted(overlap)}',f'Known CPU overlap: {sorted(cpu_overlap)}',
      'POC is bypassed on asymmetric-capacity topologies.',
      'Infinity GPU reads Infinity task EMA/futex state and does not read or write POC state.',
    ]
    report='\n'.join(lines)+'\n';print(report,end='')
    if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(report)
if __name__=='__main__':main()
