import pytest

from seian_sim.route_messages import RouteAdvertisement, RouteErrorMessage


def valid_advertisement_payload() -> dict:
    return {
        "destination_id": "N01",
        "destination_sequence": 8,
        "hop_count": 2,
        "route_cost": 4.25,
        "lifetime_s": 120.0,
        "advertised_next_hop": "N02",
        "gateway_path": True,
        "electrical_risk": 0.35,
        "communication_health": 0.9,
        "communication_congestion": 0.2,
        "communication_fault_status": "normal",
    }


def test_route_advertisement_round_trip():
    advertisement = RouteAdvertisement.from_payload(
        valid_advertisement_payload(),
        max_hops=10,
    )

    assert RouteAdvertisement.from_payload(
        advertisement.to_payload(),
        max_hops=10,
    ) == advertisement


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("destination_id", ""),
        ("destination_sequence", -1),
        ("hop_count", 11),
        ("route_cost", float("inf")),
        ("lifetime_s", 0.0),
        ("gateway_path", 1),
        ("electrical_risk", 1.1),
        ("communication_health", -0.1),
        ("communication_congestion", 1.1),
        ("communication_fault_status", "broken"),
    ],
)
def test_route_advertisement_rejects_invalid_fields(field, value):
    payload = valid_advertisement_payload()
    payload[field] = value

    with pytest.raises(ValueError):
        RouteAdvertisement.from_payload(payload, max_hops=10)


def test_route_error_round_trip():
    message = RouteErrorMessage.from_payload(
        {
            "destination_id": "N01",
            "destination_sequence": 9,
            "failed_next_hop": "N02",
            "reason": "neighbor_timeout",
        }
    )

    assert RouteErrorMessage.from_payload(message.to_payload()) == message


def test_route_error_rejects_missing_failed_next_hop():
    with pytest.raises(ValueError):
        RouteErrorMessage.from_payload(
            {
                "destination_id": "N01",
                "destination_sequence": 9,
                "reason": "neighbor_timeout",
            }
        )
