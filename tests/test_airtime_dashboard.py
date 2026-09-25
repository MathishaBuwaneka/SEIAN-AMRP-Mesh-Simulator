"""Exercise applying the radio settings through the real Streamlit dashboard."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_exact_radio_settings_apply_on_reset_and_invalid_ldro_is_reported():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not app.exception
    next(item for item in app.selectbox if item.label == "Timing model").select("LoRa time-on-air")
    next(item for item in app.selectbox if item.label == "Packet encoding").select("Binary v1")
    next(item for item in app.selectbox if item.label == "Routing engine").select("NetworkX oracle baseline")
    next(item for item in app.selectbox if item.label == "Spreading factor").select(12)
    app.run()
    next(item for item in app.button if item.label == "Create / Reset Network").click()
    app.run()
    assert not app.exception
    assert app.session_state["sim"].config.lora.airtime_mode == "lora"
    assert app.session_state["sim"].config.packet_encoding == "binary"
    assert app.session_state["sim"].config.lora.spreading_factor == 12
    next(item for item in app.selectbox if item.label == "Low-data-rate optimization").select("Disabled")
    app.run()
    assert not app.exception
    assert any("required" in error.value for error in app.error)


def test_event_radio_controls_apply_and_batch_timeline_is_exported():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    next(item for item in app.selectbox if item.label == "Timing model").select("LoRa time-on-air")
    next(item for item in app.selectbox if item.label == "Packet encoding").select("Binary v1")
    next(item for item in app.selectbox if item.label == "Radio scheduling").select("Event-based shared channel")
    next(item for item in app.selectbox if item.label == "Routing engine").select("NetworkX oracle baseline")
    app.run()
    next(item for item in app.button if item.label == "Create / Reset Network").click()
    app.run()
    assert not app.exception
    assert app.session_state["sim"].config.radio.mode == "event"
    next(item for item in app.button if item.label == "Advance One Step").click()
    app.run()
    assert not app.exception
    assert app.session_state["sim"].event_radio.records
    assert app.session_state["sim"].export_tables_json()["radio_metrics"]["physical_transmissions"] > 0
