"""Table layout specs produced by VLM and applied deterministically to raw cell grids."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class TableRegionSpec:
    sheet: str
    title: str | None = None
    header_rows: list[int] = field(default_factory=list)
    data_start_row: int = 0
    columns: list[str] = field(default_factory=list)
    col_indices: list[int] = field(default_factory=list)
    data_end_row: int | None = None
    region: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TableRegionSpec:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TableLayoutSheet:
    sheet: str
    regions: list[TableRegionSpec] = field(default_factory=list)
    confidence: float = 0.0
    needs_review: bool = False

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet,
            "regions": [r.to_dict() for r in self.regions],
            "confidence": self.confidence,
            "needs_review": self.needs_review,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TableLayoutSheet:
        return cls(
            sheet=data["sheet"],
            regions=[TableRegionSpec.from_dict(r) for r in data.get("regions", [])],
            confidence=float(data.get("confidence", 0)),
            needs_review=bool(data.get("needs_review", False)),
        )


@dataclass
class PageRecord:
  """Per-slide (pptx) or per-page (pdf) unit for viewer pairing."""
  index: int
  ref: str
  text: str = ""
  image_path: str | None = None

  def to_dict(self) -> dict:
    return asdict(self)

  @classmethod
  def from_dict(cls, data: dict) -> PageRecord:
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class RawSheet:
    sheet: str
    rows: list[list[str]]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RawSheet:
        return cls(sheet=data["sheet"], rows=data.get("rows", []))
