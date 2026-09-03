"""Typed models for places and directions.

Fields Google's positional response arrays may not carry are typed Optional and emitted as null
rather than guessed, so a consumer never reads a fabricated value.
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
    ftid: str | None
    address: str | None
    lat: float | None
    lng: float | None
    rating: float | None
    category: str | None
    phone: str | None
    website: str | None
    hours_today: str | None
    open_intervals: list[tuple[int, int]] = field(default_factory=list)  # today, minutes since midnight
    photos: list[str] = field(default_factory=list)
    links: Links | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class MapList:
    id: str
    name: str
    kind: int
    item_count: int | None
    share_url: str | None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class MapListItem:
    name: str
    cid: int
    note: str | None

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Step:
    instruction: str
    line: str | None = None


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
        return asdict(self)


@dataclass
class ItineraryLeg:
    origin: str
    dest: str
    mode: str
    duration: str | None


@dataclass
class Itinerary:
    stops: list[ItineraryStop]
    legs: list[ItineraryLeg]
    route_url: str
    total_minutes: int

    def to_json(self) -> dict[str, object]:
        return {
            "stops": [stop.to_json() for stop in self.stops],
            "legs": [{"from": leg.origin, "to": leg.dest, "mode": leg.mode, "duration": leg.duration} for leg in self.legs],
            "route_url": self.route_url,
            "total_minutes": self.total_minutes,
        }
