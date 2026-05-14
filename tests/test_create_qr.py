"""Tests validation API création QR (/api/create_qr)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def auth_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = "owner-1"
        sess["role"] = "user"
        sess["username"] = "admin"
        sess["gym_name"] = "Salle"
        sess["phone"] = "+221771234567"
        sess["address"] = "X"


@patch("app._current_user")
def test_create_qr_requires_phone(mock_user, client, auth_session):
    mock_user.return_value = {
        "id": "owner-1",
        "role": "user",
        "gym_name": "Salle",
        "phone": "+221771234567",
        "address": "X",
        "is_active": True,
    }
    rv = client.post(
        "/api/create_qr",
        json={
            "client_name": "Test",
            "client_phone": "",
            "subscription_type": "Séance",
            "payment_mode": "especes",
            "amount_total": "100",
            "amount_paid": "100",
            "expiration": "24h",
        },
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 400
    assert "téléphone" in (rv.get_json().get("error") or "").lower()


@patch("app._current_user")
def test_create_qr_requires_subscription(mock_user, client, auth_session):
    mock_user.return_value = {
        "id": "owner-1",
        "role": "user",
        "gym_name": "Salle",
        "phone": "+221771234567",
        "address": "X",
        "is_active": True,
    }
    rv = client.post(
        "/api/create_qr",
        json={
            "client_name": "Test",
            "client_phone": "+221771234567",
            "subscription_type": "",
            "payment_mode": "especes",
            "amount_total": "100",
            "amount_paid": "100",
            "expiration": "24h",
        },
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 400


@patch("app.store.allocate_ticket_number", return_value="000042")
@patch("app.store.qr_hash_exists", return_value=False)
@patch("app.store.create_qr")
@patch("app.generate_qr_code_image")
@patch("app._invalidate_list_qr_cache_for_owner")
@patch("app._current_user")
def test_create_qr_success_minimal(
    mock_user,
    _inv,
    mock_img,
    mock_create,
    mock_hash,
    mock_ticket,
    client,
    auth_session,
):
    mock_user.return_value = {
        "id": "owner-1",
        "role": "user",
        "gym_name": "Salle",
        "phone": "+221771234567",
        "address": "X",
        "is_active": True,
    }
    mock_img.return_value = MagicMock()
    mock_create.return_value = "uuid-qr-1"

    rv = client.post(
        "/api/create_qr",
        json={
            "client_name": "Test Client",
            "client_phone": "+221771234567",
            "subscription_type": "Séance",
            "payment_mode": "especes",
            "amount_total": "100",
            "amount_paid": "50",
            "expiration": "24h",
        },
        headers={"Content-Type": "application/json"},
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body.get("success") is True
    assert body.get("qr_id") == "uuid-qr-1"
    mock_create.assert_called_once()
    call_kw = mock_create.call_args[0][0]
    assert call_kw.get("created_by_user_id") == "owner-1"
    assert call_kw.get("created_by_display") == "Salle"


@patch("app._current_user")
def test_operator_blocked_from_list_qr(mock_user, client):
    mock_user.return_value = {
        "id": "op-1",
        "role": "operator",
        "gym_name": "Caisse",
        "phone": "+221771234567",
        "address": "-",
        "is_active": True,
    }
    with client.session_transaction() as sess:
        sess["user_id"] = "op-1"
        sess["role"] = "operator"
        sess["username"] = "operator"
        sess["gym_name"] = "Caisse"
        sess["phone"] = "+221771234567"
        sess["address"] = "-"

    rv = client.get("/api/list_qr")
    assert rv.status_code == 403
    assert "gestion" in (rv.get_json().get("error") or "").lower()
