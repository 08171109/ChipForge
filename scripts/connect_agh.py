"""Connect separately installed AGH dependencies to this project's local runtime.

--check only validates paths; it does not start AGH or contact a model.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = {'script': 'scripts/connect_agh.py', 'runtime': 'runtime/agh', 'node': 'tools/node/bin/node', 'sdk': 'runtime/sdk-bundle.mjs', 'templates': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.environ.get("AGH_SOURCE_DIR"))
    parser.add_argument("--runtime", default=os.environ.get("AGH_RUNTIME_DIR"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.source:
        parser.error("set AGH_SOURCE_DIR to a separately installed AGH workspace")
    source = Path(args.source).expanduser().resolve()
    if source.is_relative_to(ROOT):
        parser.error("AGH_SOURCE_DIR must be outside this project")
    runtime = Path(args.runtime).expanduser().resolve() if args.runtime else source / "packages/cli/dist/local"
    if runtime.is_relative_to(ROOT):
        parser.error("AGH_RUNTIME_DIR must be outside this project")
    node = shutil.which("node")
    required = [runtime / "agnes.mjs", source / "packages/sdk/src/index.node.ts"]
    links = {SETTINGS["runtime"]: runtime}
    if SETTINGS.get("node"):
        if not node:
            parser.error("Node.js 24 is required on PATH")
        links[SETTINGS["node"]] = Path(node).resolve()
    if SETTINGS.get("mhs"):
        plugin = source / "packages/mhs/plugin"
        required += [plugin / "dist/hub.mjs", source / "packages/mhs/python/pyproject.toml"]
        links[SETTINGS["mhs"]] = plugin
    if SETTINGS.get("templates"):
        for key, folder in [("CHIPFORGE_TT_TEMPLATE_DIR", "ttsky-template"), ("CHIPFORGE_TT_TOOLS_DIR", "tt-support-tools")]:
            if not os.environ.get(key):
                parser.error("set " + key + " to the separately installed Tiny Tapeout dependency")
            dependency = Path(os.environ[key]).expanduser().resolve()
            if not dependency.is_dir() or dependency.is_relative_to(ROOT):
                parser.error(key + " must be an existing external directory")
            links["upstream/" + folder] = dependency
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        parser.error("prepare the external AGH runtime/SDK/MHS build first: " + ", ".join(missing))
    esbuild = next((p for p in [source / "packages/sdk/node_modules/esbuild/bin/esbuild", source / "node_modules/esbuild/bin/esbuild"] if p.is_file()), None)
    if not node or not esbuild:
        parser.error("install the external workspace dependencies with pnpm; SDK esbuild and Node.js are required")
    print(json.dumps({"source": str(source), "runtime": str(runtime), "links": {k: str(v) for k, v in links.items()}, "check_only": args.check}, indent=2))
    if args.check:
        return
    for rel, external in links.items():
        path = ROOT / rel
        if path.exists() or path.is_symlink():
            if path.is_symlink() and path.resolve() == external:
                continue
            raise RuntimeError("local path already exists; inspect before reconnecting: " + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(external, target_is_directory=external.is_dir())
    bundles = {SETTINGS["sdk"]: source / "packages/sdk/src/index.node.ts"}
    if SETTINGS.get("runtime_target"):
        bundles[SETTINGS["runtime_target"]] = source / "packages/plugin-runtime/src/runtime-target.ts"
    banner = 'import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'
    for target, entry in bundles.items():
        output = ROOT / target
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([node, str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm", "--banner:js=" + banner, "--outfile=" + str(output)], check=True)
    if SETTINGS.get("python"):
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "-e", str(source / "packages/mhs/python")], check=True)
    record = ROOT / "runtime/agent-dependencies.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"source": str(source), "runtime": str(runtime)}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
