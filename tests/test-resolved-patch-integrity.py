#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "validate_resolved_patches", root / "scripts/validate-resolved-patches.py"
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    lock_root = Path(tmp) / ".resolved-patches"
    files = lock_root / "files"
    files.mkdir(parents=True)
    data = b"From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
    output = files / "01-test.patch"
    output.write_bytes(data)
    lock = {
        "schema": 1,
        "kernel": {"version": "7.1.5", "series": "7.1"},
        "components": {
            "test": {
                "kind": "git_patch",
                "output": "files/01-test.patch",
                "repo": "https://github.com/example/project.git",
                "ref": "main",
                "commit": "a" * 40,
                "selected_path": "patches/test.patch",
                "path": "patches/test.patch",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        },
    }
    lock_path = lock_root / "patch-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert module.validate_lock(lock_path) == 1

    output.write_bytes(data + b"mutated")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("mutated patch was accepted")

    output.write_bytes(data)
    lock["components"]["test"]["output"] = "../outside.patch"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("escaping output path was accepted")

print("Resolved patch integrity regression tests passed")
