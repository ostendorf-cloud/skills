#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Load scripts/install.py and scripts/validate.py by path for the test suite."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def load_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
