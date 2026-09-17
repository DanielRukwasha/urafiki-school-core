"""Optional native PDF checks; required by the PDF/browser CI job."""

import datetime
import io
import os
from pathlib import Path

import pytest

from app.models.student import Enrollment, Student
from app.models.user import RoleEnum
from app.security.tenant import resolve_tenant


@pytest.fixture(autouse=True)
def _tenant_request_context(app, tenant_a):
    """Ambient `db.session.add(...)` calls below construct rows directly,
    outside any HTTP request — push a resolved request context so their
    `ecole_id` column default sees tenant_a, same as every `client.*()`
    call already gets via before_request."""
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        yield


@pytest.fixture()
def pdf_runtime():
    try:
        import pypdf
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as error:
        if os.environ.get("REQUIRE_PDF"):
            pytest.fail(str(error))
        pytest.skip("Install requirements-pdf.txt, pypdf and native Pango libraries")
    return pypdf


@pytest.mark.parametrize("kind,count", [("bulletins", 2), ("palmares", 65)])
def test_a4_reports_paginate(
    client, db, make_user, course, enrollment, evaluation_period, pdf_runtime, kind, count
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    for index in range(1, count):
        pupil = Student(
            matricule=f"PDF-{index:04}",
            first_name="Eleve",
            last_name=f"Nom de famille compose {index:03}",
        )
        db.session.add(pupil)
        db.session.flush()
        db.session.add(
            Enrollment(
                student_id=pupil.id,
                school_class_id=course.school_class_id,
                academic_year_id=enrollment.academic_year_id,
                enrollment_date=datetime.date(2025, 9, 1),
            )
        )
    db.session.commit()
    response = client.get(
        f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}/print/{kind}?format=pdf"
    )
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    reader = pdf_runtime.PdfReader(io.BytesIO(response.data))
    assert len(reader.pages) >= 2
    if kind == "bulletins":
        assert len(reader.pages) == count
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.28) < 1
        assert abs(float(page.mediabox.height) - 841.89) < 1
        assert "Page " in page.extract_text()
    text = "".join(page.extract_text() for page in reader.pages)
    assert "IMC-0001" in text
    assert f"PDF-{count - 1:04}" in text
    assert "Télécharger" not in text
    output = Path("tmp/portal-review")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{kind}.pdf").write_bytes(response.data)
