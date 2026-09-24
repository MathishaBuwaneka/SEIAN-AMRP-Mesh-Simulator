# LoRa airtime model

**Binary branch update:** select **Packet encoding → Binary v1** to use the full
encoded frame length without the assumed header budget described below. Compact
route advertisements now fit and decentralized exact-mode regression tests pass.
See [the shared binary contract](BINARY_PACKET_FORMAT.md). The JSON limitations
below still apply when JSON encoding is selected.

The simulator offers `approximate` (default) and `lora` timing modes. Select
**LoRa airtime settings → Timing model → LoRa time-on-air**, set the radio
parameters, and press **Create / Reset Network**. For a multi-hop airtime
experiment with today's JSON packets, select **NetworkX oracle baseline**:
verbose route advertisements can exceed the exact mode's frame limit.

In Python, set `config.lora.airtime_mode = "lora"` before constructing the
simulator. Both manual Forward and batch delivery use the selected model.
Topology exports include `lora_config`; old files without it remain readable.
Exported radio settings override the corresponding settings supplied by callers.

## Formula and supported profile

The calculation follows Semtech's [SX1276/77/78/79 datasheet, section 4.1.1.7,
page 31](https://cdn-shop.adafruit.com/product-files/3179/sx1276_77_78_79.pdf).

```text
Tsym = 2^SF / BW
Npayload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH)
                       / (4*(SF - 2*DE))) * (CR + 4), 0)
Tpreamble = (programmed_preamble + 4.25) * Tsym
ToA = Tpreamble + Npayload * Tsym
```

`PL` is the PHY payload byte count, `IH=1` selects implicit header mode,
`CRC=1` includes the PHY payload CRC, and `CR=1..4` means coding rate 4/5..4/8.
The configuration stores the denominator (5..8), not the register value.
Supported bandwidths are 125, 250, and 500 kHz; SF6..SF12 are supported, with
implicit headers required at SF6. Preamble length is 6..65535 symbols.
Automatic low-data-rate optimization enables `DE` when `Tsym > 16 ms`.
It can be enabled explicitly; disabling it when required is rejected.

Reference values below use 20 PHY payload bytes, explicit header, CRC enabled,
eight preamble symbols, and coding rate 4/5. These are independently
hand-evaluated formula values, not hardware measurements.

| SF | Bandwidth | Airtime |
| --- | --- | --- |
| 7 | 125 kHz | 56.576 ms |
| 7 | 250 kHz | 28.288 ms |
| 7 | 500 kHz | 14.144 ms |
| 10 | 125 kHz | 370.688 ms |
| 11 | 125 kHz | 741.376 ms |
| 12 | 125 kHz | 1318.912 ms |

## Byte representation and frame limit

Application payloads are encoded as sorted, compact JSON in UTF-8. The byte
length is recalculated before transmission so mutable payloads cannot bypass
the limit. Exact mode adds `protocol_header_bytes` (default **24**, an explicit
budget assumption rather than a defined SEIAN binary header) to this length.
Simulator-only paths, timestamps, and Python object metadata are not sent.
The formula accounts for the PHY header/CRC separately; do not include those
again in the protocol-header budget.

The resulting PHY payload must be 1..255 bytes. Larger packets are recorded as
`frame_too_large` before any radio attempt or simulated time advance. There is
no automatic fragmentation, compression, or silent truncation. In particular,
current verbose JSON advertisements may fail in exact mode; compact binary
route-control packets must be implemented before using it for complete
decentralized convergence studies. Implicit mode assumes both ends already
know each frame's payload length; negotiation is not simulated.

Approximate mode retains the existing base-plus-length timing formula without
the 255-byte limit, but now also uses compact UTF-8 payload byte counts. Old
JSON-length-based latency numbers therefore should not be reused as baselines.

## Delay and sensitivity

Link delay is airtime plus `transmission_delay_s` (default 0.25 s, a separate
processing/scheduling assumption). Set this to zero to study airtime alone.
Failed radio attempts consume that same delay. Oversize preflight rejections
consume none. Discovery probes do not simulate a transmitted HELLO frame and
have no airtime. Broadcast delivery remains serialized per receiver.

Exact mode estimates sensitivity using thermal noise, receiver noise figure
(default 6 dB), and an SF-dependent SNR threshold (-5 dB at SF6, decreasing
2.5 dB per SF). This follows the link-budget structure described in Semtech's
[Long Range with LoRa](https://blog.semtech.com/long-range-with-lora).
It is an engineering estimate, not measured module performance. A finite
`sensitivity_dbm` overrides it. Approximate mode defaults to the previous
-118 dBm threshold. Exact-mode reported SNR uses the matching thermal-noise
estimate. Existing path-loss, maximum-range, and random-loss assumptions remain.

Carrier frequency is recorded and validated against the SX1276 tuning range;
it does not yet change path loss or enforce any regional band rules. Event-based
collisions, duty cycle, dwell time, hardware calibration, a shared binary packet
format, real CRC/MIC calculation, and retransmission remain separate work.

## Validation

`tests/test_lora_airtime.py` covers formula vectors, LDRO boundaries, parameter
validation, byte-size limits, Unicode encoding, sensitivity, manual/batch
two-hop timing, failed attempts, mutable payloads, and topology round trips.
Run the complete mesh and power-plane suites with:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```
