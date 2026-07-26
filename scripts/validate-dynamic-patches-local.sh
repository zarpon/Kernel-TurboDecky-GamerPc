#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/logs"
exec > >(tee "$ROOT/logs/local-validation.log") 2>&1

python3 -m py_compile \
  "$ROOT/scripts/resolve-latest-stable.py" \
  "$ROOT/scripts/resolve-patch-sources.py" \
  "$ROOT/scripts/resolve-zen-interactive.py" \
  "$ROOT/scripts/update-marie-fallback.py" \
  "$ROOT/scripts/validate-marie-fallback.py" \
  "$ROOT/scripts/apply-dynamic-patch-sources.py" \
  "$ROOT/scripts/apply-validation-modules.py" \
  "$ROOT/scripts/patch-external-module-toolchain.py" \
  "$ROOT/scripts/apply-zarpon-generic-name.py" \
  "$ROOT/scripts/apply-latest-stable-series.py" \
  "$ROOT/scripts/finalize-bore-stable-port.py" \
  "$ROOT/scripts/apply-zen-interactive.py"
python3 -m json.tool "$ROOT/config/patch-sources.json" >/dev/null
python3 -m unittest -v \
  "$ROOT/tests/test_latest_stable_identity.py" \
  "$ROOT/tests/test_virtualbox_host_compat.py" \
  "$ROOT/tests/test_external_module_toolchain.py" \
  "$ROOT/tests/test_dynamic_patch_resolver.py" \
  "$ROOT/tests/test_dynamic_patch_symlinks.py" \
  "$ROOT/tests/test_dynamic_patch_indirections.py" \
  "$ROOT/tests/test_marie_version_reporting.py" \
  "$ROOT/tests/test_marie_local_fallback.py" \
  "$ROOT/tests/test_marie_fallback_updater.py" \
  "$ROOT/tests/test_bore_liquorix_port.py" \
  "$ROOT/tests/test_bore_stable_port.py" \
  "$ROOT/tests/test_bore_stable_finalizer.py" \
  "$ROOT/tests/test_validation_modules.py" \
  "$ROOT/tests/test_manual_workflow_contract.py" \
  "$ROOT/tests/test_zen_interactive_rewriter.py"
bash "$ROOT/tests/test_runtime_tuning.sh"

grep -Fq '"bore"' "$ROOT/config/patch-sources.json"
grep -Fq '"bore_sched_ext_coexistence"' "$ROOT/config/patch-sources.json"
grep -Fq 'firelzrd/bore-scheduler' "$ROOT/config/patch-sources.json"
grep -Fq '7.1.4-bore-6.8.0-rc1.patch' "$ROOT/scripts/build-kernelnote-core.sh"
grep -Fq '7.1.4-sched-ext-coexistence-fix.patch' "$ROOT/scripts/build-kernelnote-core.sh"
grep -Fq 'approved_sha256' "$ROOT/config/patch-sources.json"
grep -Fq 'CONFIG_SCHED_BORE=y' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_ZEN_INTERACTIVE=y' "$ROOT/config/kernelnote.config"
grep -Fq 'KERNEL_SERIES' "$ROOT/scripts/resolve-zen-interactive.py"
grep -Fq 'compatibility_sources' "$ROOT/scripts/resolve-zen-interactive.py"
grep -Fq 'intel_pstate=passive' "$ROOT/scripts/build-kernelnote-core.sh"
grep -Fq 'amd_pstate=passive' "$ROOT/scripts/build-kernelnote-core.sh"
grep -Fq 'CONFIG_X86_INTEL_PSTATE=y' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_X86_AMD_PSTATE=y' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2' "$ROOT/config/kernelnote.config"
grep -Fq 'intel_pstate=passive' "$ROOT/config/kernelnote.config"
grep -Fq 'amd_pstate=passive' "$ROOT/config/kernelnote.config"
grep -Fq 'resolve-patch-sources.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-external-module-toolchain.py' "$ROOT/scripts/apply-zarpon-generic-name.py"
if grep -Fq 'patch-external-module-toolchain.py' "$ROOT/scripts/apply-latest-stable-series.py"; then
  echo "external module helper must not be owned by apply-latest-stable-series.py" >&2
  exit 1
fi
grep -Fq 'drivers/gpu/drm/amd/amdgpu/amdgpu.ko' "$ROOT/scripts/apply-validation-modules.py"
grep -Fq '"vram"' "$ROOT/config/patch-sources.json"
grep -Fq 'fallback_refs' "$ROOT/config/patch-sources.json"
grep -Fq 'local_fallback_patch' "$ROOT/config/patch-sources.json"
test -s "$ROOT/patches/fallback/lru_marie.patch"
python3 "$ROOT/scripts/validate-marie-fallback.py" \
  --patch "$ROOT/patches/fallback/lru_marie.patch" \
  --metadata "$ROOT/patches/fallback/lru_marie.json"
grep -Fq 'patch-lock.json' "$ROOT/scripts/apply-dynamic-patch-sources.py"
grep -Fq 'KERNEL_VERSION' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'patch-source-resolution.log' "$ROOT/scripts/apply-zarpon-generic-name.py"
grep -Fq 'turbodecky-snapshot' "$ROOT/scripts/resolve-patch-sources.py"
grep -Fq 'kvm.enable_virt_at_load=0' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_INTEL=m' "$ROOT/config/kernelnote.config"
grep -Fq 'CONFIG_KVM_AMD=m' "$ROOT/config/kernelnote.config"
grep -Fq 'TUNING_VERSION="1.3.2"' "$ROOT/scripts/build-tuning-package.sh"
grep -Fq 'Version: ${TUNING_VERSION}' "$ROOT/scripts/build-tuning-package.sh"
grep -Fq 'Depends: clang, llvm, lld, make' "$ROOT/scripts/build-tuning-package.sh"
if grep -RIn --binary-files=without-match \
  --exclude-dir=.git \
  --exclude-dir=work \
  --exclude-dir=logs \
  --exclude-dir=__pycache__ \
  -e 'infin'"ity" "$ROOT"; then
  echo "Legacy scheduler references remain in the TurboDecky tree" >&2
  exit 1
fi

# Exercise the exact CI pre-build rewrite chain on disposable script copies.
# This catches stale cross-transformer anchors before any source checkout or
# kernel compilation and leaves a named step in local-validation.log.
if [[ -n "${KERNEL_VERSION:-}" && -n "${KERNEL_SERIES:-}" ]]; then
  preflight_dir="$(mktemp -d)"
  trap 'rm -rf "$preflight_dir"' EXIT
  cp "$ROOT/scripts/build-kernelnote-core.sh" "$preflight_dir/core.sh"
  cp "$ROOT/scripts/build-kernelnote.sh" "$preflight_dir/wrapper.sh"

  run_rewriter() {
    local label="$1"
    shift
    echo "==> Preflight rewriter: $label"
    "$@"
  }

  run_rewriter reflex \
    python3 "$ROOT/scripts/apply-reflex-core.py" \
      "$preflight_dir/core.sh" "$preflight_dir/wrapper.sh"
  run_rewriter upstream-generic \
    python3 "$ROOT/scripts/apply-upstream-generic.py" "$preflight_dir/core.sh"
  run_rewriter requested-series \
    python3 "$ROOT/scripts/apply-requested-patch-series.py" "$preflight_dir/core.sh"
  run_rewriter latest-stable \
    python3 "$ROOT/scripts/apply-latest-stable-series.py" "$preflight_dir/core.sh"
  run_rewriter zen-interactive \
    python3 "$ROOT/scripts/apply-zen-interactive.py" "$preflight_dir/core.sh"
  run_rewriter generic-name-and-dynamic-sources \
    python3 "$ROOT/scripts/apply-zarpon-generic-name.py" \
      "$preflight_dir/core.sh" "$preflight_dir/wrapper.sh"
  run_rewriter final-bore-port \
    python3 "$ROOT/scripts/finalize-bore-stable-port.py" "$preflight_dir/core.sh"
  bash -n "$preflight_dir/core.sh" "$preflight_dir/wrapper.sh"
  rm -rf "$preflight_dir"
  trap - EXIT
fi

echo "Dynamic patch source validation passed"
