#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m py_compile \
  "$ROOT/scripts/resolve-latest-stable.py" \
  "$ROOT/scripts/resolve-patch-sources.py" \
  "$ROOT/scripts/resolve-infinity-v46-cpu-series.py" \
  "$ROOT/scripts/apply-dynamic-patch-sources.py" \
  "$ROOT/scripts/apply-validation-modules.py" \
  "$ROOT/scripts/patch-infinity-v46-build.py" \
  "$ROOT/scripts/apply-zarpon-generic-name.py" \
  "$ROOT/scripts/apply-latest-stable-series.py"
python3 -m json.tool "$ROOT/config/patch-sources.json" >/dev/null
python3 -m json.tool "$ROOT/config/infinity-source.json" >/dev/null
python3 -m unittest -v \
  "$ROOT/tests/test_latest_stable_identity.py" \
  "$ROOT/tests/test_virtualbox_host_compat.py" \
  "$ROOT/tests/test_dynamic_patch_resolver.py" \
  "$ROOT/tests/test_dynamic_patch_symlinks.py" \
  "$ROOT/tests/test_dynamic_patch_indirections.py" \
  "$ROOT/tests/test_infinity_v46_cpu_series.py" \
  "$ROOT/tests/test_validation_modules.py"

grep -Fq '"infinity"' "$ROOT/config/patch-sources.json"
grep -Fq '"v4.6-gpu"' "$ROOT/config/infinity-source.json"
grep -Fq '0001-v4.5-core-Infinity' "$ROOT/config/infinity-source.json"
grep -Fq '0003-v4.5-Infinity-RT' "$ROOT/config/infinity-source.json"
grep -Fq 'Subject: [PATCH 4/6]' "$ROOT/config/infinity-source.json"
grep -Fq 'resolve-infinity-v46-cpu-series.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-infinity-v46-build.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'apply-validation-modules.py' "$ROOT/scripts/patch-infinity-v46-build.py"
grep -Fq 'drivers/gpu/drm/amd/amdgpu/amdgpu.ko' "$ROOT/scripts/apply-validation-modules.py"
grep -Fq '"vram"' "$ROOT/config/patch-sources.json"
grep -Fq 'fallback_refs' "$ROOT/config/patch-sources.json"
grep -Fq 'patch-lock.json' "$ROOT/scripts/apply-dynamic-patch-sources.py"
grep -Fq 'KERNEL_VERSION' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-source-resolution.log' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'turbodecky-snapshot' "$ROOT/scripts/resolve-patch-sources.py"
grep -Fq 'kvm.enable_virt_at_load=0' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_INTEL=m' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_AMD=m' "$ROOT/config/kernelnote.config"

echo "Dynamic patch source validation passed"
