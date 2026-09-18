"""Presentation states only; authentication and rate limiting remain backend decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessNotice:
    code: str
    title: str
    message: str
    allow_login: bool
    retry_after: int | None = None


def access_notice(code, retry_after=None):
    states = {
        "invalid_credentials": ("Connexion refusée", "Email ou mot de passe invalide.", True),
        "account_suspended": (
            "Compte suspendu",
            "Votre compte ne permet plus la connexion. Contactez la direction.",
            False,
        ),
        "tenant_unknown": (
            "Portail introuvable",
            "Vérifiez l’adresse fournie par votre établissement.",
            False,
        ),
        "tenant_suspended": (
            "Portail temporairement indisponible",
            "L’accès à ce portail est suspendu. Contactez votre établissement.",
            False,
        ),
        "rate_limited": (
            "Veuillez patienter",
            "Trop de tentatives. Réessayez après le délai indiqué.",
            False,
        ),
    }
    if code not in states:
        raise ValueError("Unknown access state")
    title, message, allow_login = states[code]
    retry_after = min(max(int(retry_after), 1), 86400) if retry_after is not None else None
    return AccessNotice(code, title, message, allow_login, retry_after)
