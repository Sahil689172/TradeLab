"""Room lifecycle, chat, trade ideas, and shared paper portfolio."""

from __future__ import annotations

PREFIX = "/api/v1/collab"


def _create_room(client, name: str = "Nifty Desk", user: str = "sahil") -> str:
    response = client.post(
        f"{PREFIX}/rooms",
        json={"name": name, "created_by": user, "initial_capital": 500_000.0, "capacity": 2},
    )
    assert response.status_code == 201
    return response.json()["data"]["room_id"]


class TestRoomLifecycle:
    def test_create_room_registers_creator_as_member(self, seeded_client) -> None:
        response = seeded_client.post(
            f"{PREFIX}/rooms",
            json={"name": "Desk", "created_by": "sahil"},
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["members"] == ["sahil"]
        assert data["capacity"] == 2

    def test_second_user_can_join(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(f"{PREFIX}/rooms/{room_id}/join", params={"user": "arjun"})
        assert response.status_code == 200
        assert set(response.json()["data"]["members"]) == {"sahil", "arjun"}

    def test_join_beyond_capacity_is_rejected(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(f"{PREFIX}/rooms/{room_id}/join", params={"user": "arjun"})
        response = seeded_client.post(f"{PREFIX}/rooms/{room_id}/join", params={"user": "third"})
        assert response.status_code == 409

    def test_rejoin_existing_member_is_idempotent(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(f"{PREFIX}/rooms/{room_id}/join", params={"user": "sahil"})
        response = seeded_client.get(f"{PREFIX}/rooms/{room_id}")
        assert response.json()["data"]["members"] == ["sahil"]

    def test_unknown_room_returns_404(self, seeded_client) -> None:
        assert seeded_client.get(f"{PREFIX}/rooms/nope").status_code == 404

    def test_delete_room(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        assert seeded_client.delete(f"{PREFIX}/rooms/{room_id}").status_code == 200
        assert seeded_client.get(f"{PREFIX}/rooms/{room_id}").status_code == 404


class TestMessages:
    def test_post_and_read_chat(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        posted = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/messages",
            json={"author": "sahil", "text": "RELIANCE looks extended here"},
        )
        assert posted.status_code == 200
        assert posted.json()["data"]["kind"] == "CHAT"

        history = seeded_client.get(f"{PREFIX}/rooms/{room_id}/messages")
        messages = history.json()["data"]["messages"]
        assert [m["text"] for m in messages] == ["RELIANCE looks extended here"]

    def test_non_member_cannot_post(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/messages",
            json={"author": "stranger", "text": "hello"},
        )
        assert response.status_code == 403

    def test_history_is_chronological(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        for index in range(5):
            seeded_client.post(
                f"{PREFIX}/rooms/{room_id}/messages",
                json={"author": "sahil", "text": f"msg-{index}"},
            )
        messages = seeded_client.get(f"{PREFIX}/rooms/{room_id}/messages").json()["data"]["messages"]
        assert [m["text"] for m in messages] == [f"msg-{i}" for i in range(5)]


class TestTradeIdeas:
    def test_trade_idea_is_stamped_with_current_price(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/trade-ideas",
            json={
                "author": "sahil",
                "idea": {
                    "symbol": "RELIANCE",
                    "direction": "LONG",
                    "thesis": "breakout above range",
                    "target": 200.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["kind"] == "TRADE_IDEA"
        # Seeded history ends at close 129.0, so the call is scoreable later.
        assert data["trade_idea"]["price_at_post"] == 129.0

    def test_trade_idea_appears_in_history(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/trade-ideas",
            json={"author": "sahil", "idea": {"symbol": "RELIANCE", "direction": "SHORT"}},
        )
        messages = seeded_client.get(f"{PREFIX}/rooms/{room_id}/messages").json()["data"]["messages"]
        assert messages[0]["trade_idea"]["direction"] == "SHORT"


class TestSharedPortfolio:
    def test_order_fills_against_shared_book(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/orders",
            json={"author": "sahil", "side": "BUY", "symbol": "RELIANCE", "quantity": 10},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["accepted"] is True
        assert body["status"] == "FILLED"

    def test_both_members_see_the_same_portfolio(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(f"{PREFIX}/rooms/{room_id}/join", params={"user": "arjun"})
        seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/orders",
            json={"author": "sahil", "side": "BUY", "symbol": "RELIANCE", "quantity": 10},
        )
        # arjun did not place the order but shares the book.
        portfolio = seeded_client.get(f"{PREFIX}/rooms/{room_id}/portfolio").json()["data"]
        symbols = [p["symbol"] for p in portfolio["positions"]]
        assert "RELIANCE" in symbols
        assert portfolio["positions"][0]["quantity"] == 10

    def test_order_writes_an_event_into_chat(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/orders",
            json={"author": "sahil", "side": "BUY", "symbol": "RELIANCE", "quantity": 5},
        )
        messages = seeded_client.get(f"{PREFIX}/rooms/{room_id}/messages").json()["data"]["messages"]
        events = [m for m in messages if m["kind"] == "ORDER_EVENT"]
        assert len(events) == 1
        assert "bought" in events[0]["text"]
        assert events[0]["metadata"]["accepted"] is True

    def test_rejected_order_is_also_logged(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/orders",
            json={"author": "sahil", "side": "SELL", "symbol": "RELIANCE", "quantity": 5},
        )
        assert response.json()["data"]["accepted"] is False
        messages = seeded_client.get(f"{PREFIX}/rooms/{room_id}/messages").json()["data"]["messages"]
        events = [m for m in messages if m["kind"] == "ORDER_EVENT"]
        assert events[0]["metadata"]["accepted"] is False

    def test_rooms_have_isolated_books(self, seeded_client) -> None:
        first = _create_room(seeded_client, name="Room A")
        second = _create_room(seeded_client, name="Room B")
        seeded_client.post(
            f"{PREFIX}/rooms/{first}/orders",
            json={"author": "sahil", "side": "BUY", "symbol": "RELIANCE", "quantity": 10},
        )
        other = seeded_client.get(f"{PREFIX}/rooms/{second}/portfolio").json()["data"]
        assert other["positions"] == []

    def test_unknown_symbol_is_rejected_without_price(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        response = seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/orders",
            json={"author": "sahil", "side": "BUY", "symbol": "NOSUCHSYM", "quantity": 1},
        )
        assert response.json()["data"]["accepted"] is False
