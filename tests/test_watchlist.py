"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service and endpoints.
Follows the same patterns as tests/test_collection.py.
"""

import pytest
from datetime import datetime, timezone, timedelta
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.collection_service import FilmNotFoundError
from services.watchlist_service import (
    add_to_watchlist,
    get_watchlist,
    AlreadyOnWatchlistError,
)


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """
    Adding a valid film should create a WatchlistEntry in the database.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        # Verify it persisted
        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


def test_add_to_watchlist_defaults_to_public(app, sample_user, sample_film):
    """
    New watchlist entries should be public unless the user changes them
    (see the visibility decision in pr-response.md, Comment 4).
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry.public is True


# ── Deduplication ────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyOnWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyOnWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        # Confirm only one entry exists
        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film ─────────────────────────────────────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)

        assert WatchlistEntry.query.count() == 0


# ── get_watchlist sort order ─────────────────────────────────────────────────

def test_get_watchlist_returns_newest_first(app, sample_user):
    """
    get_watchlist() should return films sorted by date_added descending
    (most recently added first), not alphabetically.
    """
    with app.app_context():
        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        entry_a = WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier)
        entry_b = WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later)
        db.session.add_all([entry_a, entry_b])
        db.session.commit()

        watchlist = get_watchlist(sample_user)
        titles = [f["title"] for f in watchlist]

        # Blade Runner was added later, so it should come first
        assert titles == ["Blade Runner", "Alien"]


# ── Endpoint error codes ─────────────────────────────────────────────────────

def test_add_endpoint_returns_404_for_nonexistent_film(app, sample_user):
    """POST /watchlist/<user_id>/add with an unknown film_id should return 404."""
    client = app.test_client()
    response = client.post(
        f"/watchlist/{sample_user}/add",
        json={"film_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404


def test_add_endpoint_returns_409_for_duplicate(app, sample_user, sample_film):
    """Adding the same film twice through the endpoint should return 409."""
    client = app.test_client()
    url = f"/watchlist/{sample_user}/add"

    first = client.post(url, json={"film_id": sample_film})
    second = client.post(url, json={"film_id": sample_film})

    assert first.status_code == 201
    assert second.status_code == 409
