"""Tests API impression thermique (/api/print_qr)."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import sign_qr_data


def _future_iso():
    return (datetime.now() + timedelta(days=1)).isoformat()


def _past_iso():
    return (datetime.now() - timedelta(days=1)).isoformat()


def _dummy_signed_qr_data():
    payload = json.dumps({"uuid": "test-uuid-print"}, sort_keys=True)
    return sign_qr_data(payload)


def _complete_user():
    return {
        "id": "user-test-1",
        "role": "user",
        "gym_name": "Salle test",
        "phone": "+221771234567",
        "address": "Dakar",
        "is_active": True,
    }


@pytest.fixture
def auth_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "user-test-1"
        sess["role"] = "user"
        sess["username"] = "tester"
        sess["gym_name"] = "Salle test"
        sess["phone"] = "+221771234567"
        sess["address"] = "Dakar"


@patch("app.store.get_qr")
@patch("app._current_user")
def test_print_qr_rejects_inactive_qr(mock_current_user, mock_get_qr, client, auth_session):
    mock_current_user.return_value = _complete_user()
    mock_get_qr.return_value = {
        "id": "qr-inactive",
        "qr_data": _dummy_signed_qr_data(),
        "expiration_date": _future_iso(),
        "is_active": False,
    }

    rv = client.post("/api/print_qr/qr-inactive")

    assert rv.status_code == 400
    body = rv.get_json()
    assert body["success"] is False
    assert "désactivé" in (body.get("error") or "").lower()


@patch("app.store.get_qr")
@patch("app._current_user")
def test_print_qr_rejects_expired_qr(mock_current_user, mock_get_qr, client, auth_session):
    mock_current_user.return_value = _complete_user()
    mock_get_qr.return_value = {
        "id": "qr-expired",
        "qr_data": _dummy_signed_qr_data(),
        "expiration_date": _past_iso(),
        "is_active": True,
    }

    rv = client.post("/api/print_qr/qr-expired")

    assert rv.status_code == 400
    body = rv.get_json()
    assert body["success"] is False
    assert "expiré" in (body.get("error") or "").lower()


@patch("app.store.get_qr")
@patch("app._current_user")
def test_print_qr_404_when_not_found(mock_current_user, mock_get_qr, client, auth_session):
    mock_current_user.return_value = _complete_user()
    mock_get_qr.return_value = None

    rv = client.post("/api/print_qr/missing-id")

    assert rv.status_code == 404
    assert rv.get_json()["success"] is False
