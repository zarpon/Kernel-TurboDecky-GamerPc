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
                "selection": "exact",
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
    port_data = data + b"# generated Linux compatibility port\n"
    port = files / "01-test-linux7.1.5-port.patch"
    port.write_bytes(port_data)
    lock["components"]["test"]["compatibility_port"] = {
        "adapter": "test-compatible-port",
        "kernel_target": "7.1.5",
        "output": "files/01-test-linux7.1.5-port.patch",
        "sha256": hashlib.sha256(port_data).hexdigest(),
        "size": len(port_data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert module.validate_lock(lock_path) == 2

    port.write_bytes(port_data + b"mutated")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("mutated compatibility port was accepted")

    port.write_bytes(port_data)
    lock["components"]["test"]["compatibility_port"]["source_sha256"] = "0" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("compatibility port with the wrong source was accepted")

    lock["components"]["test"]["compatibility_port"]["source_sha256"] = hashlib.sha256(data).hexdigest()
    lock["components"]["test"]["selection"] = "fallback"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("compatibility port from a fallback source was accepted")

    lock["components"]["test"]["selection"] = "exact"
    lock["components"]["test"]["output"] = "../outside.patch"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("escaping output path was accepted")

    # Positive, narrowly pinned fallback contract: no generic cross-series bypass.
    source_record = lock["components"].pop("test")
    lock["components"]["bore"] = source_record
    source_record["output"] = "files/01-test.patch"
    source_record["selection"] = "fallback"
    source_record["kernel_target"] = "7.3-rc2"
    source_record["project_version"] = "7.0.0"
    source_record["selected_path"] = "patches/stable/0001-linux7.3-rc2-bore-7.0.0.patch"
    lock["kernel"]["version"] = "7.4-rc1"
    source_record["compatibility_port"]["adapter"] = "linux7.4-rc1-bore7.0.0-futex-context"
    source_record["compatibility_port"]["kernel_target"] = "7.4-rc1"
    source_record["compatibility_port"]["source_kernel_target"] = "7.3-rc2"
    module.REVIEWED_BORE_74_SOURCE_SHA = hashlib.sha256(data).hexdigest()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert module.validate_lock(lock_path) == 2

    source_record["compatibility_port"]["adapter"] = "unreviewed-cross-series"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    try:
        module.validate_lock(lock_path)
    except module.IntegrityError:
        pass
    else:
        raise AssertionError("unreviewed cross-series adapter was accepted")


print("Resolved patch integrity regression tests passed")
