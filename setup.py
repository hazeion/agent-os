"""Setuptools entry point for the verified public Mentat distribution."""

from pathlib import Path
import sys

from setuptools import setup

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.package_data import package_data_files


setup(data_files=package_data_files(ROOT))
