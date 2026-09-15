"""Canonical entry point for the legitimate-A orbit-error Doppler Stage-A study.

The implementation is kept in the independently named experiment module so the
frozen protocol and intermediate exploratory/confirmatory manifests remain
stable.  This wrapper exposes the output-script name specified by the study.
"""

from __future__ import annotations

import sys

from run_orbit_error_to_doppler_legitimate_experiment import main


if __name__ == "__main__":
    sys.exit(main())
