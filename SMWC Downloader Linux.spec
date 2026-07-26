# -*- mode: python ; coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from build_support.manifest import auto_target
from build_support.pyinstaller_common import build_application

target = os.environ.get("SMWC_BUILD_TARGET") or 'linux-x86_64'
build_application(globals(), target)
