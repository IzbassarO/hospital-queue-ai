"""Display-ready values of explanation factors.

Raw factor values in pred_referral.explanation are strings ("1.0", "0.0248…", "08IV"). The rules below turn them
into what a user reads: rates as percentages with 1 decimal, counts as integers, days with 1 decimal, codes with
their dictionary names. The per-feature format comes from ml/configs/explain_templates.yaml, copied by
`make marts` into mart_build_info.config["explain_display"], so the API and the model's own sentences agree.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DimOrganization, DimProfile, DimRegion
from app.services.common import BuildInfo

_NAME_FORMATS = ("region", "org", "profile")


def _num(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")


@dataclass
class ValueFormatter:
    rules: dict
    icd3_names: dict[str, str]
    names: dict[str, dict[str, str]] = field(default_factory=lambda: {f: {} for f in _NAME_FORMATS})

    @classmethod
    def for_build(cls, info: BuildInfo) -> "ValueFormatter":
        return cls(
            rules=info.config.get("explain_display") or {"features": {}},
            icd3_names=info.config["derived"].get("icd3_names") or {},
        )

    def short_label(self, feature: str, fallback: str | None = None) -> str:
        spec = self.rules["features"].get(feature, {})
        return spec.get("short_label") or spec.get("label") or fallback or feature

    def fmt_of(self, feature: str) -> dict:
        return self.rules["features"].get(feature, {"format": "text"})

    def load_names(self, session: Session, pairs: Iterable[tuple[str, str | None]]) -> "ValueFormatter":
        """Fetch dictionary names for the (feature, value) pairs about to be formatted, one query per dictionary."""
        wanted: dict[str, set[str]] = {f: set() for f in _NAME_FORMATS}
        for feature, value in pairs:
            fmt = self.fmt_of(feature)["format"]
            if fmt in wanted and value is not None:
                wanted[fmt].add(str(value))
        sources = {
            "region": (DimRegion.region_code, DimRegion.region_name),
            "org": (DimOrganization.org_code, DimOrganization.org_name),
            "profile": (DimProfile.profile_code, DimProfile.profile_name),
        }
        for fmt, codes in wanted.items():
            codes -= self.names[fmt].keys()
            if codes:
                code_col, name_col = sources[fmt]
                self.names[fmt].update(session.execute(select(code_col, name_col).where(code_col.in_(codes))).all())
        return self

    def _icd_chapter(self, code: str) -> str | None:
        for first, last, chapter in self.rules.get("icd_chapter_ranges", []):
            if first <= code[:3] <= last:
                return chapter
        return None

    def format(self, feature: str, value: str | float | None) -> str:
        spec = self.fmt_of(feature)
        value = None if value is None else str(value)
        if value is None or value == "" or value.lower() == "nan":
            return self.rules.get("missing_value", "нет данных")
        fmt, unit = spec["format"], spec.get("unit")
        try:
            if fmt in _NAME_FORMATS:
                name = self.names[fmt].get(value)
                return f"{name} ({value})" if name else value
            if fmt == "icd_chapter":
                name = self.rules.get("icd_chapters", {}).get(value)
                return f"{value} — {name}" if name else value
            if fmt == "icd_code":
                if value in self.icd3_names:
                    return f"{value} — {self.icd3_names[value]}"
                chapter = self._icd_chapter(value)
                name = self.rules.get("icd_chapters", {}).get(chapter)
                return f"{value} (класс {chapter} — {name})" if name else value
            if fmt == "weekday":
                return self.rules["weekdays"][int(float(value)) - 1]
            if fmt == "int":
                text = _num(float(value), 0)
            elif fmt == "float1":
                text = _num(float(value), 1)
            elif fmt == "percent":
                return f"{_num(100 * float(value), 1)}%"
            else:
                return value
        except (ValueError, IndexError, KeyError):
            return value
        return f"{text} {unit}" if unit else text


# effect of a factor on the model output: days for the wait-time model, probability share for the refusal model
EFFECT_UNITS = {"wait_time": ("дн.", 1.0), "refusal_risk": ("п.п.", 100.0)}


def with_display(explanation: dict | None, formatter: ValueFormatter) -> dict:
    """Copy of a referral explanation with display fields next to each factor's raw `value` and `effect`:
    `value_display`, `short_label`, `unit` and `effect_in_unit` (days, or percentage points for refusal risk)."""
    out = {}
    for model, factors in (explanation or {}).items():
        unit, scale = EFFECT_UNITS.get(model, ("", 1.0))
        out[model] = [
            {
                **f,
                "value_display": formatter.format(f["feature"], f.get("value")),
                "short_label": formatter.short_label(f["feature"]),
                "unit": unit,
                "effect_in_unit": round(float(f.get("effect", 0.0)) * scale, 2),
            }
            for f in factors
        ]
    return out


def explanation_pairs(explanations: Iterable[dict | None]) -> Iterable[tuple[str, str | None]]:
    for explanation in explanations:
        for factors in (explanation or {}).values():
            for f in factors:
                yield f["feature"], f.get("value")
