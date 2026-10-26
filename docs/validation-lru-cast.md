# CAST migration validation — 2026-10-26

The build resolves `firelzrd/lru_cast` again on every run. Release ordering
compares the complete upstream version (including RC/rN), then chooses the
native kernel variant of that release or the nearest foreign variant to port.
An older native release cannot displace newer upstream code.

Live resolution selected upstream commit
`71c94c9fd7270c8c260ef7a861cb043bfb375321`, CAST `0.2.5`,
`patches/0001-7.3-rc7-lru_cast-v0.2.5.patch` for Linux 7.3.
These values are validation evidence, not build pins.

The complete patch passed `git apply --check` against all 26 existing source
files it modifies, downloaded from `torvalds/linux@v7.3`; new files are supplied
by the patch. The original upstream bytes were sufficient, with SHA-256
`288386b09f673d0d8d713d2398bb6c064145c063805946047a4d85bf53093ce3`.

The combined targeted validation across both repositories passed 85 tests:
82 existing/new resolver, audit, lock, application, configuration and integration
tests, plus three Charcoal CAST policy tests. Windows shell tests used the
bundled Git Bash with POSIX mode disabled. Python compilation, shell syntax,
TurboDecky's integrated script generation and modified PKGBUILD source hashes
were also checked.

New tests cover a newer foreign release/revision beating an older native patch,
native selection within the newest release, preservation of locked bytes,
the reviewed folio include-context port and failure without partial application.
`CONFIG_LRU_CAST=y` is enforced. Upstream CAST defaults to enabled; no separate
`LRU_CAST_DEFAULT_ON` option is invented. The package no longer sets swappiness.

This is patch/application and targeted regression validation, not a complete
kernel compilation or boot test. The broad Windows discovery run encountered
Linux-specific tooling/symlink requirements and an unrelated existing REFLEX
assertion; it is not reported as passing. Full Linux CI/build and boot validation
remain necessary. Unknown future kernel API changes stop for a reviewed port;
they never select an older CAST release.
