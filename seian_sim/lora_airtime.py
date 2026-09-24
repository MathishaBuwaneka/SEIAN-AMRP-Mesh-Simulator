"""SX1276 LoRa time-on-air, datasheet section 4.1.1.7.

PHY payload length includes the application protocol header but excludes the
LoRa PHY header and CRC, which the formula accounts for separately.
"""

from dataclasses import dataclass
import math

from seian_sim.config import LoraConfig


@dataclass(frozen=True, slots=True)
class LoraAirtime:
    symbol_duration_s: float
    payload_symbols: int
    preamble_duration_s: float
    payload_duration_s: float
    low_data_rate_optimization: bool

    @property
    def total_s(self) -> float:
        return self.preamble_duration_s + self.payload_duration_s


def calculate_airtime(payload_bytes: int, config: LoraConfig) -> LoraAirtime:
    """Calculate one frame; reject lengths outside the SX1276 frame limit."""
    config.validate()
    if type(payload_bytes) is not int or not 1 <= payload_bytes <= 255:
        raise ValueError("LoRa PHY payload must contain 1..255 bytes.")
    sf = config.spreading_factor
    symbol_s = 2 ** sf / config.bandwidth_hz
    de = (symbol_s > 0.016 if config.low_data_rate_optimization is None
          else config.low_data_rate_optimization)
    numerator = 8 * payload_bytes - 4 * sf + 28 + 16 * int(config.crc_enabled) - 20 * int(config.implicit_header)
    payload_symbols = 8 + max(
        math.ceil(numerator / (4 * (sf - 2 * int(de)))) * config.coding_rate_denominator,
        0,
    )
    return LoraAirtime(
        symbol_s, payload_symbols, (config.preamble_symbols + 4.25) * symbol_s,
        payload_symbols * symbol_s, de,
    )


def receiver_sensitivity_dbm(config: LoraConfig) -> float:
    """Engineering estimate from thermal noise, noise figure, and SF SNR limit.

    This is not a measured chip/module sensitivity or a calibrated link budget.
    """
    config.validate()
    if config.sensitivity_dbm is not None:
        return config.sensitivity_dbm
    if config.airtime_mode == "approximate":
        return -118.0
    snr_limit_db = -5.0 - 2.5 * (config.spreading_factor - 6)
    return -174.0 + 10 * math.log10(config.bandwidth_hz) + config.receiver_noise_figure_db + snr_limit_db
