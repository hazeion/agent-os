"""Small entry point used by native bundles and installer shortcuts."""

import os
from pathlib import Path
import runpy
import subprocess
import sys

from mentat.cli import main
from mentat.web_runtime import application_root, require_node_24


def console_gateway_companion() -> Path | None:
    """Return the fixed macOS console sibling used to supervise the Node gateway."""

    if not (bool(getattr(sys, "frozen", False)) and sys.platform == "darwin"):
        return None
    companion = application_root().parent / "MacOS" / "mentat-bridge"
    if not companion.is_file() or companion.is_symlink():
        return None
    return companion


def native_main() -> int:
    if os.environ.pop("MENTAT_NATIVE_SERVER", "") == "1":
        runpy.run_module("server", run_name="__main__")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--mentat-private-bridge":
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        runpy.run_module("mentat.local_bridge", run_name="__main__")
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "--mentat-node-gateway":
        node_path = Path(sys.argv[2])
        entrypoint = Path(sys.argv[3])
        expected_entrypoint = application_root() / "web" / "server.js"
        if (
            not (bool(getattr(sys, "frozen", False)) and sys.platform == "darwin")
            or not node_path.is_file()
            or entrypoint.resolve() != expected_entrypoint.resolve()
        ):
            return 2
        require_node_24(str(node_path))
        os.execv(str(node_path), [str(node_path), str(entrypoint)])
        return 2
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "--mentat-console-gateway":
        return main(arguments[1:])
    launch_arguments = arguments if arguments else ["start", "--open-browser"]
    companion = console_gateway_companion()
    if companion is not None and launch_arguments[0] == "start":
        return subprocess.call([str(companion), "--mentat-console-gateway", *launch_arguments])
    return main(launch_arguments)


if __name__ == "__main__":
    raise SystemExit(native_main())
