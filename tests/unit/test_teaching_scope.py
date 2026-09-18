from flask import g

from app.blueprints.portal.routes import _teaching_scope


def test_teaching_scope_is_class_contextual(app):
    with app.test_request_context():
        g.teaching_scope = {
            "titular_class_ids": [12, "13"],
            "editable_course_ids": [31, 32, "33"],
            "submit_class_ids": [12],
        }
        assert _teaching_scope() == {
            "titular_class_ids": {12},
            "editable_course_ids": {31, 32},
            "submit_class_ids": {12},
            "source": "server",
        }


def test_missing_scope_keeps_legacy_assignment_fallback(app):
    with app.test_request_context():
        assert _teaching_scope() == {
            "titular_class_ids": set(),
            "editable_course_ids": None,
            "submit_class_ids": set(),
            "source": "legacy-assignment",
        }
