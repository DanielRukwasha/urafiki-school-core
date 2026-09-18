"""Import every model so Alembic autogenerate and db.metadata see them all."""

from app.models.academic import (  # noqa: F401,E501
    AcademicYear,
    EvaluationPeriod,
    SchoolClass,
    Section,
)
from app.models.course import Course  # noqa: F401
from app.models.deliberation import DeliberationPolicy  # noqa: F401
from app.models.deliberation_workflow import (  # noqa: F401
    DeliberationAction,
    DeliberationAuditLog,
    DeliberationOverride,
    ManualDecision,
    PeriodPublication,
    PublicationStatus,
)
from app.models.grading import Grade, GradeAuditAction, GradeAuditLog, GradeStatut  # noqa: F401
from app.models.grille import (  # noqa: F401
    GrilleCours,
    GrilleCoursLigne,
    GrilleCoursLigneMaximum,
    GroupeCours,
    Niveau,
)
from app.models.institution import Institution  # noqa: F401
from app.models.platform import (  # noqa: F401
    CalculationStrategy,
    SuperAdmin,
    TenantAccessAuditLog,
    TenantAccessEventType,
)
from app.models.student import Enrollment, Student  # noqa: F401
from app.models.teaching import TeacherAssignment  # noqa: F401
from app.models.tenant_config import TenantConfig  # noqa: F401
from app.models.titulariat import (  # noqa: F401
    DelegationTitulariat,
    DemandeCorrection,
    StatutDelegation,
    StatutDemandeCorrection,
    TitulaireHistorique,
)
from app.models.user import User  # noqa: F401

__all__ = [
    "AcademicYear",
    "EvaluationPeriod",
    "Section",
    "SchoolClass",
    "Course",
    "DeliberationPolicy",
    "DeliberationAction",
    "DeliberationAuditLog",
    "DeliberationOverride",
    "ManualDecision",
    "PeriodPublication",
    "PublicationStatus",
    "Grade",
    "GradeAuditLog",
    "GradeAuditAction",
    "GradeStatut",
    "Niveau",
    "GroupeCours",
    "GrilleCours",
    "GrilleCoursLigne",
    "GrilleCoursLigneMaximum",
    "Institution",
    "CalculationStrategy",
    "SuperAdmin",
    "TenantAccessAuditLog",
    "TenantAccessEventType",
    "Enrollment",
    "Student",
    "TeacherAssignment",
    "TenantConfig",
    "TitulaireHistorique",
    "DelegationTitulariat",
    "DemandeCorrection",
    "StatutDelegation",
    "StatutDemandeCorrection",
    "User",
]
