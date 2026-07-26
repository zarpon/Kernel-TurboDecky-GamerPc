#!/usr/bin/env python3
"""Inject the pinned REFLEX CPUFreq patch into the CI build pipeline."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def insert_after_marie_variables(text: str, block: str) -> str:
    preferred = re.compile(r"^PATCH_MARIE_VERSION=.*$", re.MULTILINE)
    fallback = re.compile(r"^MARIE_PATCH=.*$", re.MULTILINE)
    matches = list(preferred.finditer(text))
    if not matches:
        matches = list(fallback.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"REFLEX variables: expected one Marie variables anchor, found {len(matches)}"
        )
    match = matches[0]
    return text[: match.end()] + "\n" + block + text[match.end() :]


def patch_core(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if 'REFLEX_COMMIT="a7a7774b059a1f913521ffbfc52eeda72bdbb14c"' in source:
        return

    source = insert_after_marie_variables(
        source,
        '''
# REFLEX CPUFreq: native Linux 7.1 patch, pinned to an exact upstream commit.
REFLEX_REPO="https://github.com/firelzrd/reflex.git"
REFLEX_COMMIT="a7a7774b059a1f913521ffbfc52eeda72bdbb14c"
REFLEX_PATCH_PATH="patches/0001-linux7.1-reflex-v0.3.1.patch"
REFLEXDIR="$WORKDIR/reflex"
REFLEX_PATCH="$PATCHDIR/0007-reflex-v0.3.1-linux7.1.patch"
''',
    )

    source = replace_once(
        source,
        'normalize_changed_whitespace() {\n',
        r'''fetch_reflex_patch() {
  echo "==> Fetching pinned REFLEX CPUFreq 0.3.1 source locally"
  rm -rf "$REFLEXDIR"
  git init --quiet "$REFLEXDIR"
  git -C "$REFLEXDIR" remote add origin "$REFLEX_REPO"
  git -C "$REFLEXDIR" config remote.origin.promisor true
  git -C "$REFLEXDIR" config remote.origin.partialclonefilter blob:none
  git -C "$REFLEXDIR" fetch --no-tags --depth=1 --filter=blob:none origin "$REFLEX_COMMIT" \
    2>&1 | tee "$LOGDIR/07-reflex-fetch.log"

  git -C "$REFLEXDIR" show "FETCH_HEAD:$REFLEX_PATCH_PATH" > "$REFLEX_PATCH"
  test -s "$REFLEX_PATCH"
  grep -Fq 'Subject: [PATCH] linux7.1-reflex-v0.3.1' "$REFLEX_PATCH"

  {
    echo "Component: REFLEX CPUFreq Governor 0.3.1"
    echo "Repository: firelzrd/reflex"
    echo "Commit: $REFLEX_COMMIT"
    echo "Path: $REFLEX_PATCH_PATH"
    echo "SHA256: $(sha256sum "$REFLEX_PATCH" | awk '{print $1}')"
    echo "Acquisition: pinned local partial Git checkout"
  } | tee "$LOGDIR/07-reflex-provenance.txt"
}

normalize_changed_whitespace() {
''',
        "REFLEX fetch function",
    )

    source = replace_once(
        source,
        'apply_bore_patch() {\n',
        r'''apply_reflex_patch() {
  local file="$1" status=0

  echo "==> Applying native Linux 7.1 REFLEX CPUFreq 0.3.1 patch"
  if patch --batch --forward --strip=1 --dry-run < "$file" \
      > "$LOGDIR/07-reflex.dry-run.log" 2>&1; then
    patch --batch --forward --strip=1 < "$file" \
      | tee "$LOGDIR/07-reflex.apply.log"
  else
    cat "$LOGDIR/07-reflex.dry-run.log"
    echo "==> Porting REFLEX across Liquorix offsets with fuzz <= 3"
    set +e
    patch --batch --forward --fuzz=3 --strip=1 < "$file" \
      > "$LOGDIR/07-reflex.fuzz-apply.log" 2>&1
    status=$?
    set -e
    cat "$LOGDIR/07-reflex.fuzz-apply.log"

    if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
      {
        echo "==> Unresolved REFLEX port rejects"
        find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
        echo
        while IFS= read -r reject; do
          echo "### ${reject#$KERNELDIR/}"
          cat "$reject"
        done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
      } | tee "$LOGDIR/07-reflex-port-rejects.log"
      return 1
    fi
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete

  # Upstream's README documents CPU_FREQ_DEFAULT_GOV_REFLEX, and the governor
  # source implements cpufreq_default_governor() behind that symbol. The 0.3.1
  # patch does not add the symbol to the default-governor choice, so complete
  # that integration here before olddefconfig.
  python3 - <<'PY'
from pathlib import Path

path = Path("drivers/cpufreq/Kconfig")
text = path.read_text(encoding="utf-8")
if "config CPU_FREQ_DEFAULT_GOV_REFLEX" not in text:
    block = """
config CPU_FREQ_DEFAULT_GOV_REFLEX
\tbool "reflex"
\tdepends on SMP
\tselect CPU_FREQ_GOV_REFLEX
\tselect CPU_FREQ_GOV_PERFORMANCE
\thelp
\t  Use the 'reflex' CPUFreq governor by default. REFLEX combines
\t  immediate idle-to-busy frequency jumps with schedutil/PELT-based
\t  proportional scaling. The fallback governor is 'performance'.

"""
    marker = "endchoice\n"
    if text.count(marker) < 1:
        raise SystemExit("default CPUFreq governor choice end marker not found")
    text = text.replace(marker, block + marker, 1)
    path.write_text(text, encoding="utf-8")
PY

  git diff --check -- \
    arch/x86/kernel/cpu/aperfmperf.c \
    drivers/cpufreq \
    include/linux/sched/cpufreq.h \
    kernel/kthread.c kernel/sched/cpufreq.c \
    kernel/sched/cpufreq_schedutil.c kernel/time/tick-sched.c \
    | tee "$LOGDIR/07-reflex-diff-check.log"

  test -s drivers/cpufreq/cpufreq_reflex.c
  grep -Fq '#define CPUFREQ_REFLEX_VERSION  "0.3.1"' drivers/cpufreq/cpufreq_reflex.c
  grep -Fq 'config CPU_FREQ_GOV_REFLEX' drivers/cpufreq/Kconfig
  grep -Fq 'config CPU_FREQ_DEFAULT_GOV_REFLEX' drivers/cpufreq/Kconfig
  grep -Fq 'cpufreq_default_governor(void)' drivers/cpufreq/cpufreq_reflex.c
  echo "==> REFLEX 0.3.1 patch and default-governor integration applied successfully"
}

apply_bore_patch() {
''',
        "REFLEX apply function",
    )

    source = replace_once(
        source,
        'fetch_marie_testing_patch\n',
        'fetch_marie_testing_patch\nfetch_reflex_patch\n',
        "REFLEX fetch call",
    )

    source = replace_once(
        source,
        'cp "$WORKDIR/liquorix-amd64.config" .config\n',
        '''apply_reflex_patch "$REFLEX_PATCH"

cp "$WORKDIR/liquorix-amd64.config" .config
''',
        "REFLEX apply call",
    )

    source = replace_once(
        source,
        '''# ThinLTO is mandatory for the final kernel. These symbols only survive
''',
        '''# REFLEX must be built in to provide the kernel's default governor. Keep
# schedutil enabled because REFLEX reuses its PELT/update-util infrastructure.
scripts/config --enable CPU_FREQ
scripts/config --enable CPU_FREQ_GOV_SCHEDUTIL
scripts/config --enable CPU_FREQ_GOV_REFLEX
scripts/config --enable CPU_FREQ_DEFAULT_GOV_REFLEX
scripts/config --disable CPU_FREQ_DEFAULT_GOV_PERFORMANCE
scripts/config --disable CPU_FREQ_DEFAULT_GOV_POWERSAVE
scripts/config --disable CPU_FREQ_DEFAULT_GOV_USERSPACE
scripts/config --disable CPU_FREQ_DEFAULT_GOV_ONDEMAND
scripts/config --disable CPU_FREQ_DEFAULT_GOV_CONSERVATIVE
scripts/config --disable CPU_FREQ_DEFAULT_GOV_SCHEDUTIL

# ThinLTO is mandatory for the final kernel. These symbols only survive
''',
        "REFLEX configuration",
    )

    source = replace_once(
        source,
        'assert_config "CONFIG_CPU_MITIGATIONS=y"\n',
        '''assert_config "CONFIG_CPU_FREQ=y"
assert_config "CONFIG_CPU_FREQ_GOV_SCHEDUTIL=y"
assert_config "CONFIG_CPU_FREQ_GOV_REFLEX=y"
assert_config "CONFIG_CPU_FREQ_DEFAULT_GOV_REFLEX=y"
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_PERFORMANCE
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_POWERSAVE
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_USERSPACE
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_ONDEMAND
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_CONSERVATIVE
assert_disabled_or_absent CPU_FREQ_DEFAULT_GOV_SCHEDUTIL
assert_config "CONFIG_CPU_MITIGATIONS=y"
''',
        "REFLEX assertions",
    )

    path.write_text(source, encoding="utf-8")


def patch_wrapper(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    expected = '-kn-marie-bore-poc-nap-rfx-adios-zir-lto'
    if expected not in source:
        raise SystemExit("REFLEX local version anchor is missing from build wrapper")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: apply-reflex-core.py <build-kernelnote-core.sh> <build-kernelnote.sh>"
        )
    patch_core(Path(sys.argv[1]))
    patch_wrapper(Path(sys.argv[2]))


if __name__ == "__main__":
    main()
