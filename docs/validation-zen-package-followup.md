# Zen package follow-up validation

This temporary validation marker exists only to trigger the full `package` workflow from a `validation/**` pull request after PR #22 was merged before its package run completed.

The workflow must produce all Debian packages while preserving the existing THP policy and `CONFIG_ZEN_INTERACTIVE=y`.
