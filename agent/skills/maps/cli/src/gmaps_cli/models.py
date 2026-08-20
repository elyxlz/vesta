"""Typed models for places.

Fields not yet mapped out of Google's positional response arrays are typed Optional and emitted
as null rather than guessed, so a consumer never reads a fabricated value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Links:
    place_url: str
    directions_url: str


@dataclass
class Place:
    name: str
    lat: float
    lng: float
    ftid: str
    cid: int
    place_id: str | None
    address: str | None
    rating: float | None = None
    review_count: int | None = None
    category: str | None = None
    phone: str | None = None
    website: str | None = None
    open_now: bool | None = None
    links: Links | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)
