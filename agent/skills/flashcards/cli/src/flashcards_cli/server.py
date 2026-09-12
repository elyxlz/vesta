"""The private HTTP API vestad proxies: the same operations as the CLI, for a dashboard widget or
any other client holding a service key."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from . import commands
from .config import Config
from .db import get_db, utc_now
from .settings import SETTING_NAMES, Settings, load_settings, set_setting


class CardItem(BaseModel):
    front: str
    back: str
    notes: str = ""


class CardsBody(BaseModel):
    deck: str
    cards: list[CardItem]


class CardPatch(BaseModel):
    front: str | None = None
    back: str | None = None
    notes: str | None = None
    deck: str | None = None


class DeckPatch(BaseModel):
    name: str | None = None
    description: str | None = None


class ReviewBody(BaseModel):
    rating: str
    seconds: int | None = None


class SettingBody(BaseModel):
    name: str
    value: str


def _connection(config: Config):
    def conn() -> Iterator[sqlite3.Connection]:
        with closing(get_db(config.data_dir)) as connection:
            yield connection

    return Depends(conn)


def _deck_routes(app: FastAPI, connection) -> None:
    @app.get("/stats")
    def stats(db: sqlite3.Connection = connection) -> commands.Stats:
        return commands.stats(db, load_settings(db), now=utc_now())

    @app.get("/decks")
    def decks(db: sqlite3.Connection = connection) -> list[commands.Deck]:
        return commands.deck_list(db, now=utc_now())

    @app.patch("/decks/{name}")
    def update_deck(name: str, body: DeckPatch, db: sqlite3.Connection = connection) -> commands.Deck:
        return commands.deck_update(db, name, new_name=body.name, description=body.description, now=utc_now())

    @app.delete("/decks/{name}")
    def delete_deck(name: str, db: sqlite3.Connection = connection) -> dict[str, str | int | bool]:
        return commands.deck_delete(db, name, now=utc_now())

    @app.get("/config")
    def config_get(db: sqlite3.Connection = connection) -> Settings:
        return load_settings(db)

    @app.patch("/config")
    def config_set(body: SettingBody, db: sqlite3.Connection = connection) -> Settings:
        if body.name not in SETTING_NAMES:
            raise HTTPException(status_code=400, detail=f"unknown setting {body.name!r}")
        return set_setting(db, body.name, body.value)


def _card_routes(app: FastAPI, connection) -> None:
    @app.get("/cards")
    def cards(deck: str | None = None, db: sqlite3.Connection = connection) -> list[commands.Card]:
        return commands.card_list(db, deck=deck)

    @app.post("/cards", status_code=201)
    def add_cards(body: CardsBody, db: sqlite3.Connection = connection) -> commands.AddResult:
        return commands.cards_add(db, body.deck, [(item.front, item.back, item.notes) for item in body.cards], now=utc_now())

    @app.get("/cards/{card_id}")
    def card(card_id: int, db: sqlite3.Connection = connection) -> commands.Card:
        return commands.card_get(db, card_id)

    @app.patch("/cards/{card_id}")
    def update_card(card_id: int, body: CardPatch, db: sqlite3.Connection = connection) -> commands.Card:
        return commands.card_update(db, card_id, front=body.front, back=body.back, notes=body.notes, deck=body.deck, now=utc_now())

    @app.delete("/cards/{card_id}")
    def delete_card(card_id: int, db: sqlite3.Connection = connection) -> commands.Card:
        return commands.card_delete(db, card_id, now=utc_now())

    @app.post("/cards/{card_id}/suspend")
    def suspend_card(card_id: int, db: sqlite3.Connection = connection) -> commands.Card:
        return commands.card_suspend(db, card_id, suspended=True, now=utc_now())

    @app.post("/cards/{card_id}/resume")
    def resume_card(card_id: int, db: sqlite3.Connection = connection) -> commands.Card:
        return commands.card_suspend(db, card_id, suspended=False, now=utc_now())


def _study_routes(app: FastAPI, connection) -> None:
    @app.post("/cards/{card_id}/review")
    def review_card(card_id: int, body: ReviewBody, db: sqlite3.Connection = connection) -> commands.ReviewResult:
        return commands.review(db, load_settings(db), card_id, body.rating, now=utc_now(), seconds=body.seconds)

    @app.get("/due")
    def due(deck: str | None = None, limit: int | None = None, db: sqlite3.Connection = connection) -> list[commands.Card]:
        return commands.due_cards(db, load_settings(db), now=utc_now(), deck=deck, limit=limit)

    @app.get("/next")
    def next_card(deck: str | None = None, db: sqlite3.Connection = connection) -> commands.NextCard | None:
        return commands.next_card(db, load_settings(db), now=utc_now(), deck=deck)


def _create_app(config: Config) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc):
        raise HTTPException(status_code=400, detail=str(exc))

    connection = _connection(config)
    _deck_routes(app, connection)
    _card_routes(app, connection)
    _study_routes(app, connection)
    return app


def start_server(config: Config, port: int) -> uvicorn.Server:
    app = _create_app(config)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info"))
    threading.Thread(target=server.run, daemon=True).start()
    return server
