import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_existing_doppler_case_orbit_distinct_relabeling as relabel


def test_freshness_bins_preserve_frozen_boundaries():
    assert relabel.freshness_bin(0.0) is None
    assert relabel.freshness_bin(0.0001) == "0-6 h"
    assert relabel.freshness_bin(6.0) == "0-6 h"
    assert relabel.freshness_bin(6.0001) == "6-9 h"
    assert relabel.freshness_bin(36.0) == "24-36 h"
    assert relabel.freshness_bin(36.0001) is None


def test_score_and_decision_are_frozen_geometry_operations():
    model = {"center": np.array([1.0, 2.0, 3.0]), "precision": np.eye(3), "c95": 4.0, "c99": 9.0}
    assert relabel.score_vector(np.array([1.0, 2.0, 3.0]), model) == 0.0
    assert relabel.orbit_decision(4.0, 4.0, 9.0) == "NOT_ORBIT_DISTINCT"
    assert relabel.orbit_decision(4.1, 4.0, 9.0) == "AMBIGUOUS"
    assert relabel.orbit_decision(9.1, 4.0, 9.0) == "ORBIT_DISTINCT"
    assert math.isclose(math.sqrt(9.0 / model["c99"]), 1.0)


def test_midpoint_is_deterministic_for_even_and_odd_windows():
    assert relabel.midpoint("2026-03-10T00:00:00Z", "2026-03-10T00:00:59Z") == datetime(2026, 3, 10, 0, 0, 29, 500000, tzinfo=timezone.utc)
    assert relabel.midpoint("2026-03-10T00:00:00Z", "2026-03-10T00:01:00Z") == datetime(2026, 3, 10, 0, 0, 30, tzinfo=timezone.utc)


def test_sign_mapping_and_security_state():
    displacement_rtn = np.array([2.0, -3.0, 4.0])
    z = -displacement_rtn
    assert np.array_equal(z, np.array([-2.0, 3.0, -4.0]))
    assert relabel.security_state("ORBIT_DISTINCT", "ACCEPT", "READY_FOR_ORBIT_RELABEL") == "ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED"
    assert relabel.security_state("ORBIT_DISTINCT", "ACCEPT", "NOT_READY_FOR_RELABEL") == "BLOCKED_A_OR_B_SEMANTICS"
