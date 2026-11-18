import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api.dashboard import my_assignments
from services.api.models import Assignment, Base, Incident, User


@pytest.fixture
def field_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'field.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Incident(incident_id="I" * 26, canonical_request_id="R" * 26,
                     latitude=10.1, longitude=76.2, urgency_score=84,
                     people_count_max=3, categories=["medical"], special_needs=["elderly"]),
            Assignment(assignment_id="A" * 26, incident_id="I" * 26,
                      team_id="T" * 26, status="assigned", eta_s=600, created_by="C" * 26),
            Assignment(assignment_id="B" * 26, incident_id="I" * 26,
                      team_id="X" * 26, status="assigned", eta_s=900, created_by="C" * 26),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_volunteer_sees_only_their_team_assignments(field_session):
    result = my_assignments(field_session, User(user_id="U" * 26, role="volunteer", team_id="T" * 26))
    assert len(result) == 1
    assert result[0]["assignment_id"] == "A" * 26
    assert result[0]["location"] == [76.2, 10.1]
    assert result[0]["special_needs"] == ["elderly"]


def test_volunteer_without_team_cannot_list_assignments(field_session):
    with pytest.raises(HTTPException) as error:
        my_assignments(field_session, User(user_id="U" * 26, role="volunteer"))
    assert error.value.status_code == 403
