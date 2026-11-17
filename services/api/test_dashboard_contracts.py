from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from services.api.dashboard import (
    AssignmentCreate,
    IncidentPatch,
    RoadReportBody,
    _decode_cursor,
    _encode_cursor,
)
from services.api.models import Incident


def test_urgency_override_requires_explanation():
    with pytest.raises(ValidationError):
        IncidentPatch(urgency_override=90)
    assert IncidentPatch(urgency_override=90, reason="New medical information").urgency_override == 90


def test_assignment_requires_one_incident_or_cluster():
    with pytest.raises(ValidationError):
        AssignmentCreate(incident_id="A" * 26, cluster_id="B" * 26)
    with pytest.raises(ValidationError):
        AssignmentCreate()


def test_road_report_requires_a_geojson_linestring():
    with pytest.raises(ValidationError):
        RoadReportBody(geometry={"type": "Point", "coordinates": [0, 0]}, status="blocked")
    report = RoadReportBody(geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, status="blocked")
    assert report.status == "blocked"


def test_incident_cursor_round_trips():
    incident = Incident(incident_id="A" * 26, canonical_request_id="B" * 26, updated_at=datetime.now(UTC))
    assert _decode_cursor(_encode_cursor(incident)) == (incident.updated_at, incident.incident_id)
