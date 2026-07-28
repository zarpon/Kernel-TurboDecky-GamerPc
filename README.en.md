# Kernel TurboDecky GamerPc

Portuguese version: [README.md](README.md)

Linux kernel optimized for enthusiasts seeking high performance in multimedia
and gaming on Debian, Ubuntu, and derivative distributions. The
`Kernel-TurboDecky-GamerPc` repository tracks the latest stable version
published by kernel.org.

## Hardware compatibility

The published package is intended for:

- Debian, Ubuntu, and derivatives that use `.deb`, `dpkg`, and `apt`;
- x86-64/amd64 desktops, laptops, and workstations;
- Intel, AMD, and other x86-64 CPU families enabled by the upstream
  configuration;
- systems with any number of cores and threads supported by the upstream kernel
  and the resources available on the machine.

The configuration retains upstream drivers for Intel and AMD graphics,
SATA/NVMe storage, USB, Ethernet, Wi-Fi, Bluetooth, HDA/USB audio, UVC/V4L2
cameras, and filesystems used by Debian and Ubuntu. Specific hardware still
depends on the corresponding upstream driver being available in the stable
version selected by the workflow.

ARM/ARM64 and 32-bit architectures, as well as systems that cannot run Debian
`amd64` packages, are not targets of this release. The proprietary NVIDIA
driver is not included; its DKMS module must be rebuilt for the new `uname -r`.
With Secure Boot enabled, the custom image and modules must be signed or
verification must be disabled.

## Expected benefits

- **Responsiveness and gaming:** BORE and POC Selector favor interactive tasks:
  BORE adjusts CFS/EEVDF priority according to burst time, while POC selects
  idle CPUs with cache topology in mind. This may improve perceived latency and
  frame-time consistency under load.
- **RT tasks and waiting:** BORE operates in the CFS/EEVDF path and preserves
  futex waiting when recalculating the task deadline. It does not turn the
  kernel into PREEMPT_RT and does not alter the SCHED_FIFO/SCHED_RR classes.
- **Frequency response:** REFLEX accelerates the transition from idle to busy,
  while NAP selects idle states adaptively. To keep REFLEX in control of the
  frequency policy, `intel_pstate=passive` and `amd_pstate=passive` are added to
  the kernel command line; the default `amd-pstate` mode is also set through
  `CONFIG_X86_AMD_PSTATE_DEFAULT_MODE=2`.
- **I/O and loading:** ADIOS adjusts deadlines and batches according to device
  latency, favoring synchronous operations during heavy disk access.
- **Memory:** Marie LRU reduces aggressive reclaim and thrashing; ZRAM-IR uses
  LZ4 and ZSTD to retain more useful pages under memory pressure.
- **VRAM management:** the `dmem` controller and the TTM port prioritize the
  eviction of unprotected buffers and honor `dmem.low` and `dmem.min`. On AMD
  GPUs under VRAM pressure, this may reduce unwanted migrations to GTT, short
  stalls, and frame-time variance.
- **Multimedia:** upstream video, audio, camera, storage, and networking drivers
  remain available without the pruning previously used by the single-machine
  profile.
- **Build optimization:** Clang/LLVM, ThinLTO, Polly, and O3 reduce part of the
  cost of kernel calls and loops without using the runner's `-march=native`.

`mitigations=off` and `nowatchdog` may reduce latency, but they also reduce
protection against CPU vulnerabilities and disable watchdogs. Evaluate this
trade-off before using the kernel on an exposed or production machine.

## Version and identity policy

Source: [Linux stable](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git).
The build clones the `v<version>` tag and verifies the version through the
Makefile before applying any patch.

## Performance patchset

- **BORE scheduler** — [firelzrd/bore-scheduler](https://github.com/firelzrd/bore-scheduler/tree/main/patches/testing): burst-time-oriented CFS/EEVDF priority adjustment. On every build, the resolver selects and locks the newest exact Linux-series version by commit, path, SHA-256, and size. The patch is applied only after `patch --dry-run`, without fuzz. The `sched_ext` fix is locked too; its Linux 7.1 port is materialized from the current upstream `reweight_task()` body and reviewed context, with its hash, size, and parent-source SHA recorded in the lock. An incompatible structural change fails before compilation or publication.
- **POC Selector** — [firelzrd/poc-selector](https://github.com/firelzrd/poc-selector): efficient idle CPU selection with LLC and topology awareness.
- **NAP CPUIdle** — [firelzrd/nap](https://github.com/firelzrd/nap): adaptive idle-state prediction.
- **REFLEX CPUFreq** — [firelzrd/reflex](https://github.com/firelzrd/reflex): fast idle-to-busy response combined with PELT.
- **Interactive Zen** — the `zen-sauce` branch from the newest compatible Linux
  series is resolved automatically; the current `evdev` and P-State commits
  that complete the profile are also recorded in `patch-lock.json`.
- **Marie LRU** — [firelzrd/lru_marie](https://github.com/firelzrd/lru_marie): adaptive reclaim for desktop systems.
- **ADIOS** — [firelzrd/adios](https://github.com/firelzrd/adios): adaptive, built-in, default I/O scheduler.
- **ZRAM-IR** — [firelzrd/zram-ir](https://github.com/firelzrd/zram-ir): LZ4 as
  the primary compressor and ZSTD as priority `1` recompressor. The
  `turbodecky-tuning` package installs a `zram-generator` drop-in that replaces
  the distribution compressor policy before `zram0` receives `disksize`, while
  preserving the swap size and priority configured by the system. A
  `systemd-zram-setup@` `ExecStartPre` reinforces the configuration before
  initialization; the UDEV helper remains only as a safe fallback and never
  reconfigures active swap.
- **VRAM through cgroup / TTM** — policy derived from pixelcluster patches,
  aggregated and pinned to commit
  [`ea739d734ec179864b21446856315bc49f7c52fa`](https://github.com/CachyOS/kernel-patches/tree/ea739d734ec179864b21446856315bc49f7c52fa/7.0/misc).
  The port enables `CONFIG_CGROUP_DMEM=y`, separates cgroup accounting from TTM
  allocation, considers `low/min` protection during eviction, and selects
  unprotected buffers before game buffers.

The workflow also resolves and records C23 libbpf, Clear Linux, fsync through
`FUTEX_WAIT_MULTIPLE`, O3, Bluetooth SSP, the libbpf workaround, universal CPU
optimizations without targeting a specific model, DKMS-Clang compatibility,
Polly, firmware diagnostics, three minstrel_ht fixes, and ath11k fixes. The four
OpenWrt sources from commit
[`0ff1553b`](https://github.com/openwrt/openwrt/tree/0ff1553bd731c0db28043fc9caab90bdc32587f3)
are versioned under `patches/openwrt-0ff1553/`; the downgrade rework has a port
with Linux 7.1 context. Every patch has a source, commit or URL, SHA-256,
application attempt, prior-integration detection, and reject reporting.

## VRAM management through cgroup

The VRAM integration does not increase the physical capacity of the GPU and
does not reserve a fixed amount of memory for every game. It provides TTM and
the `dmem` controller with per-cgroup priority information so they can make
better decisions when VRAM approaches its limit.

### What changes

- device-memory accounting is associated with the application's cgroup;
- `dmem.low` provides best-effort protection;
- `dmem.min` provides stronger protection;
- unprotected buffers are considered first for eviction;
- a protected allocation may attempt to reclaim VRAM before falling back to a
  slower domain such as GTT;
- protection between sibling cgroups takes the common ancestor into account;
- the Linux 7.1 port is applied through semantic anchors and does not use
  `patch --fuzz`.

The `turbodecky-vram` package is included in the release and installs:

- `dmemcg-booster` 0.1.2;
- `dmemcg-booster-system.service`;
- `dmemcg-booster-user.service`;
- cgroup delegation with `Delegate=yes`;
- the `turbodecky-vram-run` launcher.

The system and user services are enabled by default during installation. A
reboot after installing the release is recommended to ensure that the new
kernel, user-service delegation, and cgroup controllers are active.

### Automatic and manual activation

After installing all `.deb` packages from the release, check the services:

```bash
systemctl status dmemcg-booster-system.service
systemctl --user status dmemcg-booster-user.service
```

If they are disabled, enable them manually:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dmemcg-booster-system.service

systemctl --user daemon-reload
systemctl --user enable --now dmemcg-booster-user.service
```

Confirm that the kernel exposes the device-memory controller:

```bash
cat /sys/fs/cgroup/cgroup.controllers
```

The output must contain `dmem`. A direct check can be performed with:

```bash
tr ' ' '\n' < /sys/fs/cgroup/cgroup.controllers | grep '^dmem$'
```

If `dmem` does not appear, confirm that the system booted with the TurboDecky
kernel:

```bash
uname -r
```

The result must follow the format
`linux.<version>.turbodecky`.

### Steam

To place a Steam game in its own systemd scope, use this in the launch options:

```text
turbodecky-vram-run %command%
```

With gamescope:

```text
turbodecky-vram-run gamescope -f -- %command%
```

Add the resolution, refresh-rate, and upscaling options appropriate for the
computer to gamescope. Recent gamescope versions may identify the foreground
game and complement cgroup protection.

### Non-Steam games

Run the game or launcher through the wrapper:

```bash
turbodecky-vram-run /path/to/the/game
```

A launcher can also be wrapped:

```bash
turbodecky-vram-run heroic
turbodecky-vram-run lutris
```

The wrapper creates a separate systemd scope. To adjust protection dynamically
according to the foreground window, use a compatible compositor or launcher
integration.

### KDE Plasma

On Plasma, `plasma-foreground-booster-dmemcg` can complement
`dmemcg-booster` and update protection according to the active window. It is
optional and is not installed by the generic package because that would add
Plasma and Qt dependencies to Cinnamon, GNOME, and other desktop environments.

### Compatibility and limitations

The main benefit is expected on AMD GPUs that use AMDGPU and TTM, especially
models with 4 to 8 GiB of VRAM and games that exceed or approach the available
limit.

- on an Intel GPU without TTM/AMDGPU, there is no direct benefit from the VRAM
  eviction policy;
- the proprietary NVIDIA driver does not use this integration;
- when free VRAM is available, the difference may be zero;
- the optimization is intended to reduce stutter and poor eviction decisions,
  not to guarantee higher average FPS;
- launching the game in a separate scope does not replace actual foreground
  application detection integration.

Technical details, patch provenance, and validation information are available
in [VRAM.md](VRAM.md).

## Automatic installation of the latest release

The latest release can be installed with the versioned script at
[`scripts/install-latest-release.sh`](scripts/install-latest-release.sh):

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  | sh
```

The script queries `/releases/latest` and prefers the
`turbodecky-linux-*.zip` asset. If the release does not contain a ZIP file, it
downloads all `.deb` assets, including `turbodecky-vram`. In both modes, it
validates the packages and architecture, normalizes permissions, calculates
the installation order from declared dependencies, uses `dpkg`, repairs
external dependencies with `apt-get -f install`, and updates GRUB.

After installation, reboot the computer and confirm the kernel with `uname -r`.
Full instructions are available in [INSTALL.md](INSTALL.md).
