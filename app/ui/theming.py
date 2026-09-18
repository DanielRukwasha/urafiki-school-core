"""Safe tenant presentation values and WCAG 2.2 contrast-checked palettes."""

import colorsys
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
FALLBACK_PRIMARY = "#334155"
FALLBACK_NEUTRAL = "#64748b"
WHITE = "#ffffff"
BLACK = "#000000"


def color(value, fallback):
    return value.lower() if isinstance(value, str) and HEX.fullmatch(value) else fallback


def rgb(value):
    return tuple(int(value[index : index + 2], 16) / 255 for index in (1, 3, 5))


def hex_rgb(channels):
    return "#" + "".join(f"{round(max(0, min(1, channel)) * 255):02x}" for channel in channels)


def mix(source, target, amount):
    return hex_rgb(
        a * (1 - amount) + b * amount for a, b in zip(rgb(source), rgb(target), strict=True)
    )


def luminance(value):
    channels = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb(value)]
    return sum(v * weight for v, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(first, second):
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def darken_for(seed, backgrounds, ratio=4.5):
    """Keep the hue where possible; verify actual quantized RGB, without rounding ratios."""
    for step in range(101):
        candidate = mix(seed, BLACK, step / 100)
        if all(contrast(candidate, background) >= ratio for background in backgrounds):
            return candidate
    return BLACK


def safe_asset_url(value):
    """Only same-origin assets; no protocols, credentials, traversal or inline content."""
    if not isinstance(value, str) or len(value) > 512:
        return None
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    try:
        parts = urlsplit(decoded)
    except ValueError:
        return None
    if (
        parts.scheme
        or parts.netloc
        or not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) < 32 for char in decoded)
        or ".." in parts.path.split("/")
        or parts.query
        or parts.fragment
    ):
        return None
    return decoded


def text(value, fallback="", limit=200):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else fallback


@dataclass(frozen=True)
class Theme:
    name: str
    initials: str
    logo_url: str | None
    favicon_url: str | None
    locale: str
    tokens: dict[str, str]
    adjustments: tuple[str, ...]


def build_theme(configuration=None):
    configuration = configuration if isinstance(configuration, dict) else {}
    primary = color(configuration.get("primary_color"), FALLBACK_PRIMARY)
    accent = color(configuration.get("accent_color"), primary)
    neutral = color(configuration.get("neutral_color"), FALLBACK_NEUTRAL)
    hue, light, saturation = colorsys.rgb_to_hls(*rgb(neutral))
    neutral = hex_rgb(colorsys.hls_to_rgb(hue, light, min(saturation, 0.12)))
    background = mix(neutral, WHITE, 0.96)
    subtle = mix(primary, WHITE, 0.94)
    hover = mix(primary, WHITE, 0.98)
    surfaces = (WHITE, background, subtle, hover)
    primary_accessible = darken_for(primary, surfaces, 4.8)
    accent_accessible = darken_for(accent, surfaces, 4.8)
    tokens = {
        "primary": primary_accessible,
        "on-primary": WHITE,
        "accent": accent_accessible,
        "on-accent": WHITE,
        "neutral": neutral,
        "background": background,
        "surface": WHITE,
        "surface-subtle": subtle,
        "surface-hover": hover,
        "text": darken_for(neutral, surfaces, 7),
        "muted": darken_for(neutral, surfaces, 4.8),
        "line": mix(neutral, WHITE, 0.75),
        "control-border": darken_for(neutral, surfaces, 3.1),
        "focus": primary_accessible,
    }
    for name, seed in {
        "error": "#b42336",
        "success": "#24604b",
        "warning": "#805500",
        "info": "#235ba5",
    }.items():
        status_background = mix(seed, WHITE, 0.96)
        tokens[name + "-surface"] = status_background
        tokens[name] = darken_for(seed, (*surfaces, status_background), 4.8)
    name = text(configuration.get("display_name"), "Portail scolaire")
    locale = configuration.get("locale") if configuration.get("locale") in {"fr", "en"} else "fr"
    adjustments = tuple(
        key
        for key, before, after in (
            ("primary_color", primary, primary_accessible),
            ("accent_color", accent, accent_accessible),
        )
        if before != after
    )
    return Theme(
        name=name,
        initials="".join(word[0].upper() for word in name.split()[:2]),
        logo_url=safe_asset_url(configuration.get("logo_url")),
        favicon_url=safe_asset_url(configuration.get("favicon_url")),
        locale=locale,
        tokens=tokens,
        adjustments=adjustments,
    )


def contrast_pairs(theme):
    """Pairs used by the UI, exposed for tests and configuration feedback."""
    tokens = theme.tokens
    pairs = [
        (tokens["on-primary"], tokens["primary"], 4.5),
        (tokens["on-accent"], tokens["accent"], 4.5),
    ]
    for surface in ("surface", "background", "surface-subtle", "surface-hover"):
        for foreground in (
            "text",
            "muted",
            "primary",
            "accent",
            "error",
            "success",
            "warning",
            "info",
        ):
            pairs.append((tokens[foreground], tokens[surface], 4.5))
        for foreground in ("focus", "control-border"):
            pairs.append((tokens[foreground], tokens[surface], 3))
    for status in ("error", "success", "warning", "info"):
        pairs.append((tokens[status], tokens[status + "-surface"], 4.5))
    return pairs
