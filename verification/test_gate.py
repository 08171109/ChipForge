"""Gate-level (post-PnR mapped netlist) functional re-verification.

Drives the actual mapped netlist (CHIP_NETLIST) with the SKY130 cell models
(CHIP_PDK_MODELS) under zero-delay simulation, sampling after the rising edge
exactly like verification/test_chip.py. Expected outputs come from
verification.oracle; this module must not reimplement the arithmetic.

Scope: zero-delay logic and cycle-protocol verification only. There is no SDF
annotation and no dynamic timing claim here; timing is covered by STA separately.
The netlist must be compiled with the FUNCTIONAL SKY130 models (run_gate.py adds
-DFUNCTIONAL); the timing cell models leave CLK/D undelayed under iverilog.
"""
import hashlib
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from verification.oracle import pixel, windows, write_gray, gray_image

OPERATOR_MODES = {"sobel_binary": 0, "gaussian_blur": 1, "sharpen": 2}
RANDOM_WINDOWS = 256


def file_sha256(paths):
    """Digest of the listed files in order (single file -> its own sha256)."""
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


@cocotb.test()
async def gate_level_contract_and_image(dut):
    spec = json.loads(Path(os.environ["CHIP_SPEC"]).read_text())
    output = Path(os.environ["CHIP_RESULTS"])
    output.mkdir(parents=True, exist_ok=True)
    seed = int(os.environ.get("CHIP_SEED", "20261003"))
    rng = random.Random(seed)
    latency = spec["latency_after_last_sample"]
    minimum_ii = spec["minimum_window_initiation_interval"]
    multi = spec["design_id"] == "image_multi"
    operators = list(spec["operations"])
    assert spec.get("protocol_version") == "window9_v1", "Gate harness targets window9_v1 only"
    for name in operators:
        assert name in OPERATOR_MODES, f"Operator {name!r} has no oracle mapping"

    netlists = [p for p in os.environ.get("CHIP_NETLIST", "").split(os.pathsep) if p]
    models = [p for p in os.environ.get("CHIP_PDK_MODELS", "").split(os.pathsep) if p]
    assert netlists, "CHIP_NETLIST must name the mapped netlist file(s)"
    for path in netlists + models:
        assert Path(path).is_file(), f"Missing source file {path}"
    netlist_sha256 = file_sha256(netlists)

    cycles = 0
    checks = 0
    latencies = []
    starts = []
    image_outputs = []
    scenarios = []

    async def cycle(value=0, bits=0, reset=1, enable=1):
        nonlocal cycles
        dut.clk.value = 0
        dut.ui_in.value = value
        dut.uio_in.value = bits
        dut.rst_n.value = reset
        dut.ena.value = enable
        await Timer(5, unit="ns")
        # in_ready applies to the upcoming rising edge; undefined while aborting.
        ready = (int(dut.uio_out.value) >> 4 & 1) if (reset and enable) else 0
        dut.clk.value = 1
        await Timer(5, unit="ns")
        cycles += 1
        flags = int(dut.uio_out.value)
        assert int(dut.uio_oe.value) == 0xF0, "Wrong pin directions"
        assert flags & 0x8F == 0, "Unused outputs not zero"
        valid = flags >> 5 & 1
        value_out = int(dut.uo_out.value)
        if not valid:
            assert value_out == 0, "Output must be zero without out_valid"
        if not (reset and enable):
            assert (flags >> 4 & 1) == 0, "in_ready must be zero while rst_n/ena is low"
        return ready, valid, value_out, flags >> 6 & 1

    async def reset_dut():
        await cycle(reset=0)
        _, valid, _, busy = await cycle()
        assert not valid and not busy, "Reset did not return to idle"
        scenarios.append("reset_to_idle")

    async def restart_prefix():
        # A partial window (3 samples) that a following start_window must replace.
        for j in range(3):
            ready, valid, _, _ = await cycle(255, 1 | (2 if j == 0 else 0))
            assert ready and not valid, "Partial window prefix stalled or produced output"

    async def transact(values, mode=0, gaps=False, change_mode=False, restart=False):
        nonlocal checks
        if restart:
            await restart_prefix()
        start_cycle = cycles + 1
        for j, value in enumerate(values):
            if gaps and j in (2, 5):
                for _ in range(2):
                    _, valid, _, busy = await cycle()
                    assert not valid, "Output during partial transaction"
                    assert busy, "busy must remain high across valid gaps"
            later_mode = (mode + 1) % 4 if change_mode and j else mode
            ready, valid, _, busy = await cycle(value, 1 | (2 if j == 0 else 0) | (later_mode << 2))
            assert ready, f"Unexpected input backpressure during collection (sample {j} of {values})"
            assert not valid, "Early output"
            assert busy, "busy must cover collection and compute"
        last_sample = cycles
        expected = pixel(values, mode if multi else 0)
        actual = None
        for k in range(1, latency + 1):
            ready, valid, actual, _ = await cycle(255, 0x0F)
            assert not ready, "Accepted input while compute is busy"
            assert bool(valid) == (k == latency), f"Wrong latency at {k}/{latency}"
            if valid:
                assert actual == expected, (
                    f"Arithmetic mismatch seed={seed} mode={mode} window={values}: {actual}!={expected}")
                latencies.append(cycles - last_sample)
                checks += 1
        starts.append(start_cycle)
        return actual

    def random_windows(count):
        # Deterministic coverage of pixel values 128..255, remainder from the seeded RNG.
        high = list(range(128, 256))
        rng.shuffle(high)
        generated = []
        k = 0
        while k < len(high):
            window = [rng.randrange(128) for _ in range(9)]
            for pos in range(9):
                if k < len(high):
                    window[pos] = high[k]
                    k += 1
            generated.append(window)
        while len(generated) < count:
            generated.append([rng.randrange(256) for _ in range(9)])
        seen = {v for w in generated for v in w}
        missing = sorted(set(range(128, 256)) - seen)
        assert not missing, f"Seeded random windows failed to cover pixel values 128..255: {missing}"
        return generated

    # ---------------- directed windows ----------------
    directed = [[0] * 9, [255] * 9, [128] * 9,
                [0, 0, 0, 255, 255, 255, 0, 0, 0],
                [0, 255, 0, 0, 255, 0, 0, 255, 0],
                [255, 255, 255, 0, 0, 0, 255, 255, 255],
                [0, 255, 0, 255, 0, 255, 0, 255, 0],
                [0, 0, 0, 0, 255, 0, 0, 0, 0]]
    # Threshold strictness: M=158/160/162 around `>160`, one non-zero pixel at each position.
    for pos in range(9):
        for value in (79, 80, 81):
            window = [0] * 9
            window[pos] = value
            directed.append(window)

    await reset_dut()

    # Samples without the start marker must not open a window.
    for _ in range(12):
        _, valid, _, busy = await cycle(128, 1)
        assert not valid and not busy, "Sample without start_window began a window"
    scenarios.append("data_without_start_marker_ignored")

    # Restart: a new start_window during partial collection replaces the window.
    for j, value in enumerate([11, 22, 33, 44, 55]):
        ready, valid, _, busy = await cycle(value, 1 | (2 if j == 0 else 0))
        assert ready and not valid and busy, "Partial collection protocol"
    restart_window = [0, 255, 0, 255, 0, 255, 0, 255, 0]
    for j, value in enumerate(restart_window):
        ready, valid, _, busy = await cycle(value, 1 | (2 if j == 0 else 0))
        assert ready, f"restart must not stall the input handshake (sample {j})"
        assert not valid, "restart must not output early"
    restart_expected = pixel(restart_window, 0)
    last_sample = cycles
    for k in range(1, latency + 1):
        ready, valid, actual, _ = await cycle(255, 0x0F)
        assert not ready, "Accepted input while compute is busy"
        assert bool(valid) == (k == latency), f"Restart wrong latency at {k}/{latency}"
        if valid:
            assert actual == restart_expected, (
                f"Restart window not honoured seed={seed}: {actual}!={restart_expected}")
            latencies.append(cycles - last_sample)
            checks += 1
    scenarios.append("restart_during_partial_collection")

    # Aborts: reset or ena mid-collection and mid-compute must drop the transaction.
    for during_compute in (False, True):
        for use_reset in (False, True):
            count = 9 if during_compute else 4
            for j in range(count):
                await cycle(255, 1 | (2 if j == 0 else 0))
            if use_reset:
                await cycle(reset=0)
                scenarios.append("reset_mid_compute" if during_compute else "reset_mid_collection")
            else:
                await cycle(enable=0)
                scenarios.append("ena0_mid_compute" if during_compute else "ena0_mid_collection")
            for _ in range(latency + 2):
                _, valid, _, busy = await cycle()
                assert not valid and not busy, "Aborted transaction leaked output"
            await transact([128] * 9)

    # ---------------- directed + random sweeps per operator ----------------
    for op in operators:
        mode = OPERATOR_MODES[op] if multi else 0
        for values in directed:
            await transact(values, mode, gaps=True, change_mode=True, restart=True)
        for values in random_windows(RANDOM_WINDOWS):
            await transact(values, mode)
        scenarios.append(f"directed_and_random_windows:{op}")

    # Reserved mode value 3: single-function designs ignore it; image_multi outputs zero.
    await restart_prefix()
    await transact([0, 255, 0, 255, 0, 255, 0, 255, 0], 3, gaps=True, change_mode=True)
    scenarios.append("mode3_reserved_behavior")

    # ---------------- measured latency and initiation interval ----------------
    assert set(latencies) == {latency}, (
        f"Observed latencies {sorted(set(latencies))} != spec latency {latency}")
    scenarios.append("latency_after_last_sample_measured")

    measured_starts = []
    interval_windows = random_windows(RANDOM_WINDOWS)
    for index, values in enumerate(interval_windows):
        mode = OPERATOR_MODES[operators[index % len(operators)]] if multi else 0
        await transact(values, mode)
        measured_starts.append(starts[-1])
    intervals = [b - a for a, b in zip(measured_starts, measured_starts[1:])]
    assert set(intervals) == {minimum_ii}, (
        f"Observed initiation intervals {sorted(set(intervals))} != spec minimum {minimum_ii}")
    scenarios.append("minimum_initiation_interval_measured")

    # ---------------- fixed 32x32 geometry image, all operators ----------------
    image = [[255 if (x // 8 + y // 8) % 2 else 0 for x in range(32)] for y in range(32)]
    for op in operators:
        mode = OPERATOR_MODES[op] if multi else 0
        values = [await transact(window, mode) for window in windows(image)]
        target = output / f"geometry_gate_{op}_32x32.png"
        write_gray(target, values, len(image[0]), len(image))
        image_outputs.append(str(target))
        scenarios.append(f"image_32x32:{op}")

    # ---------------- optional extra photo inputs (if CHIP_INPUTS is set) ----------------
    chip_inputs_dir = os.environ.get("CHIP_INPUTS")
    if chip_inputs_dir and Path(chip_inputs_dir).is_dir():
        for p in sorted(Path(chip_inputs_dir).glob("*.png")):
            input_img = gray_image(p, (128, 128))
            for op in operators:
                mode = OPERATOR_MODES[op] if multi else 0
                values = [await transact(window, mode) for window in windows(input_img)]
                target = output / f"{p.stem}_gate_{op}_128x128.png"
                write_gray(target, values, len(input_img[0]), len(input_img))
                image_outputs.append(str(target))
                scenarios.append(f"image_photo_{p.stem}:{op}")

    metrics = {
        "kind": "gate_level_simulation",
        "design_id": spec["design_id"],
        "top_module": spec["top_module"],
        "protocol_version": spec["protocol_version"],
        "netlist_sha256": netlist_sha256,
        "netlist_files": netlists,
        "pdk_models": models,
        "seed": seed,
        "transactions_checked": checks,
        "cycles": cycles,
        "latencies_observed": sorted(set(latencies)),
        "initiation_intervals_observed": sorted(set(intervals)),
        "initiation_interval_samples": len(intervals),
        "image_outputs": image_outputs,
        "operators": operators,
        "protocol_scenarios": scenarios,
        "timing_scope": "zero_delay_functional_no_sdf_not_dynamic_timing",
        "note": ("Zero-delay logic/cycle verification against the mapped netlist; no SDF annotation, "
                 "dynamic timing not verified here (STA covers timing separately)."),
    }
    (output / "protocol_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
