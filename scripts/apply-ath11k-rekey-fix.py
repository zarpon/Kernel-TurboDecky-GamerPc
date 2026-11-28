#!/usr/bin/env python3
"""Preserve the upstream ath11k rekey fix that superseded the 2022 revert."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_COMMIT = "97acb0259cc9cbfbd7ab689e25684f3d8ce10e26"
FLAGS_COMMIT = "9c78e747dd4fee6c36fcc926212e20032055cf9d"
SUPERSEDED_COMMIT = "52393e2ae12f18fb1a60578c24c46ebab292ddb6"
DRIVER = Path("drivers/net/wireless/ath/ath11k")


class RekeyError(RuntimeError):
    pass


def compact(text: str) -> str:
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
    return re.sub(r"\s+", "", text)


def block(text: str, start: int) -> str:
    depth = 0
    for index in range(start, len(text)):
        depth += (text[index] == "{") - (text[index] == "}")
        if depth == 0:
            return text[start:index + 1]
    raise RekeyError("ath11k integration has an incomplete code block")


def function(text: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}\([^;{{}}]*\)\s*\{{", text)
    if match is None:
        raise RekeyError(f"ath11k integration is missing {name}")
    return block(text, match.end() - 1)


def verify_integration(tree: Path, *, allow_legacy_flags: bool = False) -> dict[str, str]:
    files = {name: (tree / DRIVER / name).read_bytes() for name in ("core.h", "mac.c", "wmi.c")}
    texts = {name: compact(data.decode("utf-8")) for name, data in files.items()}
    core, mac, wmi = texts["core.h"], texts["mac.c"], texts["wmi.c"]
    requirements = {
        "per-vif station/key state": (core, ("u32num_stations;", "boolreinstall_group_keys;")),
        "group key reinstall": (function(mac, "ath11k_set_group_keys"), (
            "if(!key||(key->flags&IEEE80211_KEY_FLAG_PAIRWISE))continue;",
            "ath11k_install_key(arvif,key,SET_KEY,addr,WMI_KEY_GROUP)",
        )),
        "station counter increment": (function(mac, "ath11k_mac_inc_num_stations"), ("arvif->num_stations++;",)),
        "station counter decrement": (function(mac, "ath11k_mac_dec_num_stations"), ("arvif->num_stations--;",)),
        "reinstall on first station": (function(mac, "ath11k_mac_station_add"), (
            "if(arvif->num_stations==1&&arvif->reinstall_group_keys){",
            "ath11k_set_group_keys(arvif)", "arvif->reinstall_group_keys=false;",
        )),
        "clear-key cipher semantics": (function(mac, "ath11k_install_key"), (
            "if(cmd==DISABLE_KEY){arg.key_cipher=WMI_CIPHER_NONE;arg.key_data=NULL;gotoinstall;}",
        )),
        "null key buffer protection": (function(wmi, "ath11k_wmi_vdev_install_key"), (
            "if(arg->key_data)memcpy(tlv->value,(u8*)arg->key_data,key_len_aligned);",
        )),
    }
    for label, (text, markers) in requirements.items():
        if not all(marker in text for marker in markers):
            raise RekeyError(f"ath11k integration failed: {label}")
    set_key = function(mac, "ath11k_mac_op_set_key")
    if "is_ap_with_no_sta=(vif->type==NL80211_IFTYPE_AP&&!arvif->num_stations);" not in set_key:
        raise RekeyError("ath11k integration is missing the AP-without-stations exception")
    # WMI_KEY_PAIRWISE is zero: the initial rekey fix alone is incomplete.
    # The temporary legacy check only decides whether its follow-up is needed.
    pairwise = r"(?:\(flags&WMI_KEY_PAIRWISE\)|flags==WMI_KEY_PAIRWISE)" if allow_legacy_flags else r"flags==WMI_KEY_PAIRWISE"
    group = r"(?:\(flags&WMI_KEY_GROUP\)|flags==WMI_KEY_GROUP)" if allow_legacy_flags else r"flags==WMI_KEY_GROUP"
    if not allow_legacy_flags and not all(marker in set_key for marker in (
        "flags=WMI_KEY_PAIRWISE;", "flags=WMI_KEY_GROUP;",
    )):
        raise RekeyError("ath11k key-type assignment correction is missing")
    guard = re.search(rf"if\({pairwise}\|\|cmd==SET_KEY\|\|is_ap_with_no_sta\)\{{", set_key)
    if guard is None:
        raise RekeyError("ath11k integration is missing the rekey clearing guard")
    guarded = block(set_key, guard.end() - 1)
    if not all(call in guarded for call in (
        "ath11k_install_key(arvif,key,cmd,peer_addr,flags)",
        "ath11k_dp_peer_rx_pn_replay_config(arvif,peer_addr,cmd,key)",
    )):
        raise RekeyError("ath11k rekey guard does not protect key installation and replay configuration")
    if not re.search(rf"if\({group}&&cmd==SET_KEY&&is_ap_with_no_sta\)arvif->reinstall_group_keys=true;", guarded):
        raise RekeyError("ath11k integration is missing the reinstall state update")
    return {str(DRIVER / name): hashlib.sha256(data).hexdigest() for name, data in files.items()}


def authenticate_patch(patch: Path, commit: str, expected: set[str]) -> str:
    data = patch.read_bytes()
    text = data.decode("utf-8")
    if not text.startswith(f"From {commit} "):
        raise RekeyError("ath11k source is not the upstream rekey fix; obsolete DISABLE_KEY revert is forbidden")
    paths = re.findall(r"^diff --git a/(\S+) b/\S+$", text, re.MULTILINE)
    if set(paths) != expected or len(paths) != len(expected):
        raise RekeyError("ath11k upstream fix has unexpected changed files")
    return hashlib.sha256(data).hexdigest()


def apply_fix(tree: Path, patch: Path, flags_patch: Path) -> dict:
    digests = {
        UPSTREAM_COMMIT: authenticate_patch(patch, UPSTREAM_COMMIT, {str(DRIVER / "core.h"), str(DRIVER / "mac.c")}),
        FLAGS_COMMIT: authenticate_patch(flags_patch, FLAGS_COMMIT, {str(DRIVER / "mac.c")}),
    }
    applied: list[Path] = []
    command = ["git", "-C", str(tree), "apply"]

    def apply_clean(source: Path) -> None:
        check = subprocess.run([*command, "--check", str(source.resolve())], text=True, capture_output=True)
        if check.returncode:
            raise RekeyError("upstream ath11k rekey fix is not fully integrated and needs a reviewed port: " + check.stderr.strip())
        subprocess.run([*command, str(source.resolve())], check=True)
        applied.append(source)

    try:
        hashes = verify_integration(tree)
        status = "already-integrated"
    except RekeyError:
        try:
            try:
                verify_integration(tree, allow_legacy_flags=True)
            except RekeyError:
                apply_clean(patch)
            apply_clean(flags_patch)
            hashes = verify_integration(tree)
        except (RekeyError, subprocess.CalledProcessError):
            for source in reversed(applied):
                subprocess.run([*command, "--reverse", str(source.resolve())], check=True)
            raise
        status = "applied"
    kernel_commit = subprocess.check_output(["git", "-C", str(tree), "rev-parse", "HEAD"], text=True).strip()
    return {
        "component": "ath11k_disable_key", "status": status,
        "upstream_commits": [UPSTREAM_COMMIT, FLAGS_COMMIT], "supersedes": SUPERSEDED_COMMIT,
        "kernel_commit": kernel_commit,
        "patch_sha256": digests, "verified_files": hashes,
    }


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: apply-ath11k-rekey-fix.py <kernel-tree> <rekey-patch> <flags-patch> <report.json>")
    try:
        report = apply_fix(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    except (OSError, RekeyError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ath11k rekey validation failed: {exc}") from exc
    output = Path(sys.argv[4])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ath11k rekey fix {UPSTREAM_COMMIT} + {FLAGS_COMMIT}: {report['status']}; obsolete revert superseded")


if __name__ == "__main__":
    main()
