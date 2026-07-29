"""Small entry point used by native bundles and installer shortcuts."""

import os
import runpy
import sys

from mentat.cli import main


def native_main() -> int:
    if os.environ.pop("MENTAT_NATIVE_SERVER", "") == "1":
        runpy.run_module("server", run_name="__main__")
        return 0
    arguments = sys.argv[1:]
    return main(arguments if arguments else ["start", "--open-browser"])


if __name__ == "__main__":
    raise SystemExit(native_main())
