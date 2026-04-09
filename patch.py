#!/usr/bin/env python3
"""
Patch: GameHub Lite 5.1.4 — launch bug fix for unrecognized hardware
Ref: LAUNCH_BUG_REPORT.md

Target: LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1.smali
        in smali_classes5/

Fix: Remove the NetUnknownHostException instance-of check from the :goto_9
     exception handler so that ANY API error (404, ConvertException, etc.)
     returns true and proceeds with launch, instead of silently blocking it.

Lines removed:
    instance-of v0, v0, Lcom/drake/net/exception/NetUnknownHostException;
    if-eqz v0, :cond_14
"""

import os
import sys
import glob

TARGET_CLASS = "LauncherHelper$fetchStartTypeInfoAndSwitchModeInternal$2$1.smali"
SMALI_DIR = "smali_classes5"

LINE_A = "    instance-of v0, v0, Lcom/drake/net/exception/NetUnknownHostException;"
LINE_B = "    if-eqz v0, :cond_14"


def find_smali(decompile_dir):
    pattern = os.path.join(decompile_dir, "**", TARGET_CLASS)
    matches = glob.glob(pattern, recursive=True)
    # Prefer smali_classes5 if multiple hits
    for m in matches:
        if SMALI_DIR in m:
            return m
    return matches[0] if matches else None


def apply_patch(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    original = list(lines)
    out = []
    i = 0
    removed = 0
    while i < len(lines):
        line = lines[i]
        # Remove LINE_A immediately followed by LINE_B
        if line.rstrip() == LINE_A and i + 1 < len(lines) and lines[i + 1].rstrip() == LINE_B:
            print(f"  Removing line {i+1}: {line.rstrip()}")
            print(f"  Removing line {i+2}: {lines[i+1].rstrip()}")
            removed += 2
            i += 2
            continue
        out.append(line)
        i += 1

    if removed == 0:
        print("ERROR: Target lines not found — patch not applied.")
        print("The smali may have already been patched, or the class structure differs.")
        sys.exit(1)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)

    print(f"Patch applied: {removed} lines removed from {path}")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <apktool_decompile_dir>")
        sys.exit(1)

    decompile_dir = sys.argv[1]
    smali_path = find_smali(decompile_dir)

    if not smali_path:
        print(f"ERROR: Could not find {TARGET_CLASS} in {decompile_dir}")
        sys.exit(1)

    print(f"Found target: {smali_path}")
    apply_patch(smali_path)


if __name__ == "__main__":
    main()
