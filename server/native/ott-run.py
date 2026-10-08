#!/usr/bin/python3
"""Manual replacement for the unpublished OTT workflow. Check by default; execute only explicitly."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def inside(path, parent):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(parent.resolve()) or not path.is_file():
        raise ValueError("Media file must be inside the expected storage folder")
    return path


def tool(name, path):
    result = subprocess.run(["/usr/local/bin/" + name, str(path)], capture_output=True, text=True, check=False)
    data = json.loads(result.stdout)
    if result.returncode:
        raise ValueError(data.get("error") or name + " failed")
    return data


def publish(source, destination):
    # Hard-link then unlink provides no-overwrite publication on this single storage filesystem.
    os.link(source, destination)
    source.unlink()


def main():
    parser = argparse.ArgumentParser(description="Check incoming media; optionally process and publish approved movies")
    parser.add_argument("file")
    parser.add_argument("--execute", action="store_true", help="Process if needed and move approved media into Movies")
    args = parser.parse_args()
    storage = Path("/mnt/storage")
    if not os.path.ismount(storage):
        raise ValueError("Media volume is not mounted")
    source = inside(args.file, storage / "_incoming")
    analysis = tool("ott-check", source)
    if not args.execute:
        print(json.dumps(analysis, indent=2))
        return
    target = analysis.get("target")
    approved = source
    if target == "PROCESS":
        processed = tool("ott-process", source)
        if not processed.get("success") or processed.get("final_analysis", {}).get("target") != "MEDIA":
            raise ValueError("Processed media was not approved; output retained for review")
        approved = inside(processed["output"], storage / "_processing")
    elif target != "MEDIA":
        print(json.dumps({"published": False, "reviewRequired": True, "analysis": analysis}, indent=2))
        return
    destination = storage / "media/movies" / approved.name
    if destination.exists():
        raise ValueError("Destination already exists; no files overwritten")
    publish(approved, destination)
    print(json.dumps({"published": True, "destination": str(destination), "original": str(source)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        raise SystemExit(1)
