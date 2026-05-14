"""Tests API prolongation ticket (/api/extend_qr)."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import sign_qr_data


def _past_iso():
    return (datetime.now() - timedelta(days=2)).isoformat()


def _future_iso():
    return (datetime.now() + timedelta(days=2)).isoformat()


def _complete_user():
    return {
        "id": "user-test-1",
        "role": "user",
        "gym_name": "Salle test",
        "phone": "+221771234567",
        "address": "Dakar",
        "is_active": True,
    }


def _expired_qr_record():
    inner = {
        "uuid": "qr-ext-1",
        "name": "Dupont",
        "firstname": "",
        "phone": "+221771234567",
        "email": "",
        "address": "",
        "ticket": "000042",
        "expires": int(datetime.now().timestamp()),
        "subscription_type": "Séance",
        "service": "",
        "amount_total": 100.0,
        "amount_paid": 100.0,
        "payment_mode": "especes",
    }
    signed = sign_qr_data(json.dumps(inner, sort_keys=True))
    return {
        "id": "qr-ext-1",
        "owner_id": "user-test-1",
        "qr_data": signed,
        "expiration_date": _past_iso(),
        "expiration_ts": int(datetime.now().timestamp()) - 86400,
        "is_active": False,
        "client_name": "Dupont",
        "client_firstname": "",
        "client_phone": "+221771234567",
        "client_email": "",
        "client_address": "",
        "ticket_number": "000042",
        "subscription_type": "Séance",
        "service": "",
        "amount_total": 100,
        "amount_paid": 100,
        "payment_mode": "especes",
    }


@pytest.fixture
def auth_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "user-test-1"
        sess["owner_id"] = "user-test-1"
        sess["role"] = "user"
        sess["username"] = "tester"
        sess["gym_name"] = "Salle test"
        sess["phone"] = "+221771234567"
        sess["address"] = "Dakar"


@patch("app._current_user")
@patch("app.store.get_qr")
def test_extend_qr_rejects_when_still_valid(mock_get_qr, mock_user, client, auth_session):
    mock_user.return_value = _complete_user()
    r = _expired_qr_record()
    r["expiration_date"] = _future_iso()
    mock_get_qr.return_value = r

    rv = client.post(
        "/api/extend_qr/qr-ext-1",
        json={"expiration": "24h"},
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 400
    body = rv.get_json()
    assert body.get("success") is False
    assert "pas expir" in (body.get("error") or "").lower()


@patch("app._invalidate_list_qr_cache_for_owner")
@patch("app.store.update_qr_fields", return_value=True)
@patch("app.store.qr_hash_exists", return_value=False)
@patch("app.store.get_qr")
@patch("app._current_user")
def test_extend_qr_success_updates_fields(
    mock_user,
    mock_get_qr,
    mock_hash_exists,
    mock_update,
    _inv,
    client,
    auth_session,
):
    mock_user.return_value = _complete_user()
    mock_get_qr.return_value = _expired_qr_record()

    rv = client.post(
        "/api/extend_qr/qr-ext-1",
        json={"expiration": "24h"},
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body.get("success") is True
    assert "expiration_date" in body
    mock_update.assert_called_once()
    call_kw = mock_update.call_args[0][1]
    assert "qr_data" in call_kw
    assert "qr_hash" in call_kw
    assert "expiration_date" in call_kw
    assert "expiration_ts" in call_kw
    assert call_kw.get("is_active") is True
    assert call_kw.get("printed_at") is None
    assert call_kw.get("amount_total") == 100
    assert call_kw.get("amount_paid") == 100


@patch("app._invalidate_list_qr_cache_for_owner")
@patch("app.store.update_qr_fields", return_value=True)
@patch("app.store.qr_hash_exists", return_value=False)
@patch("app.store.get_qr")
@patch("app._current_user")
def test_extend_qr_accepts_new_amounts(
    mock_user,
    mock_get_qr,
    mock_hash_exists,
    mock_update,
    _inv,
    client,
    auth_session,
):
    mock_user.return_value = _complete_user()
    mock_get_qr.return_value = _expired_qr_record()

    rv = client.post(
        "/api/extend_qr/qr-ext-1",
        json={"expiration": "24h", "amount_total": 15000, "amount_paid": 12000},
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 200
    call_kw = mock_update.call_args[0][1]
    assert call_kw.get("amount_total") == 15000
    assert call_kw.get("amount_paid") == 12000


@patch("app.store.get_qr")
@patch("app._current_user")
def test_extend_qr_rejects_paid_over_total(mock_user, mock_get_qr, client, auth_session):
    mock_user.return_value = _complete_user()
    mock_get_qr.return_value = _expired_qr_record()

    rv = client.post(
        "/api/extend_qr/qr-ext-1",
        json={"expiration": "24h", "amount_total": 100, "amount_paid": 200},
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 400
    assert "dépasse" in (rv.get_json().get("error") or "").lower()
