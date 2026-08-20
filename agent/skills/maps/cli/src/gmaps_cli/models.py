"""Typed models for places and directions.

Fields not yet mapped out of Google's positional response arrays are typed Optional and emitted
as null rather than guessed, so a consumer never reads a fabricated value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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


@dataclass
class PlaceDetail:
    name: str
    cid: int
    place_id: str | None
    address: str | None
    lat: float | None
    lng: float | None
    rating: float | None
    category: str | None
    phone: str | None
    website: str | None
    hours_today: str | None
    photos: list[str] = field(default_factory=list)
    links: Links | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Step:
    instruction: str
    line: str | None = None
    departure: str | None = None
    arrival: str | None = None


@dataclass
class DirectionsLeg:
    mode: str
    duration_text: str | None
    distance_text: str | None
    steps: list[Step] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ItineraryStop:
    place: PlaceDetail
    arrive: str
    leave: str
    open_at_slot: bool | None

    def to_json(self) -> dict[str, object]:
        return {
            "place": self.place.to_json(),
            "arrive": self.arrive,
            "leave": self.leave,
            "open_at_slot": self.open_at_slot,
        }
