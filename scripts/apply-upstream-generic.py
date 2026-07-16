#!/usr/bin/env python3
"""Switch the generated build from Liquorix to kernel.org latest stable Linux."""

from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-upstream-generic.py <build-kernelnote-core.sh>")

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        'KERNEL_TAG="v7.1.3-lqx1"\n',
        ''': "${KERNEL_VERSION:?latest stable version was not resolved}"
: "${KERNEL_SERIES:?latest stable series was not resolved}"
: "${KERNEL_TAG:?latest stable tag was not resolved}"
: "${KERNEL_DEB_VERSION:?Debian package version was not resolved}"
''',
        "dynamic upstream tag",
    )
    source = replace_once(
        source,
        'KERNEL_REPO="https://github.com/zen-kernel/zen-kernel.git"\n',
        'KERNEL_REPO="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"\n',
        "upstream repository",
    )
    source = replace_once(
        source,
        'echo "==> Cloning official Liquorix source tag $KERNEL_TAG"\n',
        'echo "==> Cloning kernel.org latest stable source tag $KERNEL_TAG"\n',
        "clone description",
    )
    source = replace_once(
        source,
        '''git clone --no-checkout --depth 1 --single-branch --no-tags --branch \
"$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"
git -C "$KERNELDIR" checkout --force --detach "$KERNEL_TAG"
''',
        '''git clone --depth 1 --single-branch --no-tags --branch "$KERNEL_TAG" "$KERNEL_REPO" "$KERNELDIR"
actual_kernel_version="$(make -s -C "$KERNELDIR" kernelversion)"
if [[ "$actual_kernel_version" != "$KERNEL_VERSION" ]]; then
  echo "Cloned kernel version mismatch: $actual_kernel_version != $KERNEL_VERSION" >&2
  exit 1
fi
{
  echo "Policy: kernel.org latest_stable"
  echo "Resolved version: $KERNEL_VERSION"
  echo "Resolved series: $KERNEL_SERIES"
  echo "Source tag: $KERNEL_TAG"
  echo "Repository: $KERNEL_REPO"
  echo "Source URL: ${KERNEL_SOURCE_URL:-unknown}"
  echo "Release date: ${KERNEL_RELEASE_DATE:-unknown}"
} | tee "$LOGDIR/kernel-source-policy.txt"
''',
        "source version verification",
    )

    whitespace_anchor = '''    path.write_text("".join(output), encoding="utf-8")
PY
}
'''
    whitespace_block = '''    # Preserve exactly one final newline while removing extra blank lines at EOF.
    normalized = "".join(output).rstrip("\\n") + "\\n"
    path.write_text(normalized, encoding="utf-8")
PY
}
'''
    source = replace_once(
        source,
        whitespace_anchor,
        whitespace_block,
        "patched-file whitespace normalization",
    )

    config_anchor = 'cp "$WORKDIR/liquorix-amd64.config" .config\n'
    config_block = config_anchor + r'''
# Generic amd64 profile: keep the upstream platform, topology and driver
# choices instead of pruning the build for one computer model.
scripts/config --enable 64BIT
scripts/config --enable X86_64
scripts/config --enable SMP
scripts/config --enable EXPERT
scripts/config --enable PROCESSOR_SELECT
for symbol in CPU_SUP_INTEL CPU_SUP_AMD CPU_SUP_HYGON CPU_SUP_CENTAUR CPU_SUP_ZHAOXIN; do
  scripts/config --enable "$symbol"
done
scripts/config --enable MICROCODE
scripts/config --enable X86_MCE
scripts/config --disable X86_NATIVE_CPU
'''
    source = replace_once(source, config_anchor, config_block, "generic amd64 profile")

    assertion_anchor = 'assert_config "CONFIG_CPU_MITIGATIONS=y"\n'
    assertion_block = r'''assert_config "CONFIG_64BIT=y"
assert_config "CONFIG_X86_64=y"
assert_config "CONFIG_SMP=y"
assert_config "CONFIG_EXPERT=y"
assert_config "CONFIG_PROCESSOR_SELECT=y"
assert_config "CONFIG_CPU_SUP_INTEL=y"
assert_config "CONFIG_CPU_SUP_AMD=y"
assert_config "CONFIG_MICROCODE=y"
assert_config "CONFIG_X86_MCE=y"
assert_disabled_or_absent X86_NATIVE_CPU
assert_config "CONFIG_CPU_MITIGATIONS=y"
'''
    source = replace_once(source, assertion_anchor, assertion_block, "generic amd64 assertions")

    source = replace_once(
        source,
        'cp .config "$LOGDIR/final.config"\n',
        '''{
  echo "Target: generic amd64 desktop, laptop and workstation hardware"
  echo "CPU support: Intel and AMD x86-64 families retained from the upstream configuration"
  echo "Media support: upstream multimedia, graphics, audio, camera and wireless selections retained"
  echo "Policy: no model-specific CPU, topology or device pruning"
} | tee "$LOGDIR/media-profile.txt"

cp .config "$LOGDIR/final.config"
''',
        "media profile provenance",
    )

    source = source.replace(
        'KDEB_PKGVERSION="7.1.3-1turbodecky1"',
        'KDEB_PKGVERSION="$KERNEL_DEB_VERSION"',
    )
    source = source.replace(
        'echo "==> Kernelnote ThinLTO build completed successfully"',
        'echo "==> Latest-stable TurboDecky ThinLTO build completed successfully"',
    )

    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
