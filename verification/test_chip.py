"""Cocotb contract checks. Images are reconstructed from actual DUT outputs."""
import json
import os
import random
from pathlib import Path
import cocotb
from cocotb.triggers import Timer
from verification.oracle import pixel, gray_image, windows, write_gray


@cocotb.test()
async def contract_and_image(dut):
    spec = json.loads(Path(os.environ["CHIP_SPEC"]).read_text())
    output = Path(os.environ["CHIP_RESULTS"])
    seed = int(os.environ.get("CHIP_SEED", "20261003"))
    rng = random.Random(seed)
    latency = spec["latency_after_last_sample"]
    multi = spec["design_id"] == "image_multi"
    cycles = 0
    latencies, starts = [], []
    checks = 0

    async def cycle(value=0, bits=0, reset=1, enable=1):
        nonlocal cycles
        dut.clk.value = 0
        dut.ui_in.value = value
        dut.uio_in.value = bits
        dut.rst_n.value = reset
        dut.ena.value = enable
        await Timer(5, unit="ns")
        # A synchronous-reset DUT has no defined state before its first reset edge.
        ready = (int(dut.uio_out.value) >> 4 & 1) if reset else 0
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
        return ready, valid, value_out, flags >> 6 & 1

    async def reset():
        await cycle(reset=0)
        _, valid, _, busy = await cycle()
        assert not valid and not busy

    async def transact(values, mode=0, gaps=False, change_mode=False, restart=False):
        nonlocal checks
        if restart:
            for j in range(3):
                ready, valid, _, _ = await cycle(255, 1 | (2 if j == 0 else 0))
                assert ready and not valid
        start_cycle = cycles + 1
        for j, value in enumerate(values):
            if gaps and j in (2, 5):
                for _ in range(2):
                    _, valid, _, _ = await cycle()
                    assert not valid, "Output during partial transaction"
            later_mode = (mode+1) % 4 if change_mode and j else mode
            ready, valid, _, busy = await cycle(value, 1 | (2 if j == 0 else 0) | (later_mode << 2))
            assert ready, "Unexpected input backpressure during collection"
            assert not valid, "Early output"
            assert busy, "busy must cover collection and compute"
        last_sample = cycles
        expected = pixel(values, mode if multi else 0)
        for k in range(1, latency+1):
            ready, valid, actual, _ = await cycle(255, 0x0F)
            assert not ready, "Accepted input while compute is busy"
            assert bool(valid) == (k == latency), f"Wrong latency at {k}/{latency}"
            if valid:
                assert actual == expected, f"Arithmetic mismatch seed={seed} window={values} mode={mode}: {actual}!={expected}"
                latencies.append(cycles-last_sample)
                checks += 1
        starts.append(start_cycle)
        return actual

    await reset()
    # Data without a start marker must not create a transaction.
    for _ in range(12):
        _, valid, _, busy = await cycle(128, 1)
        assert not valid and not busy
    for mode in range(4):
        directed = [[0]*9, [128]*9, [255]*9,
                    *[[0, v, 0, 0, 0, 0, 0, 0, 0] for v in (79, 80, 81)],
                    [0, 0, 0, 0, 255, 0, 0, 0, 0], [0, 255, 0, 255, 0, 255, 0, 255, 0]]
        for values in directed:
            await transact(values, mode, gaps=True, change_mode=True, restart=True)
        for _ in range(2000 if multi or mode == 0 else 10):
            await transact([rng.randrange(256) for _ in range(9)], mode)
    # Abort partially collected and computing transactions, using both reset and ena.
    for during_compute in (False, True):
        for use_reset in (False, True):
            count = 9 if during_compute else 4
            for j in range(count):
                await cycle(255, 1 | (2 if j == 0 else 0))
            await cycle(reset=0 if use_reset else 1, enable=1 if use_reset else 0)
            for _ in range(latency+2):
                _, valid, _, busy = await cycle()
                assert not valid and not busy, "Aborted transaction leaked output"
            await transact([128]*9)
    # A sustained sequence gives actual initiation intervals, not spec constants.
    measured_starts = []
    for _ in range(1000):
        await transact([rng.randrange(256) for _ in range(9)])
        measured_starts.append(starts[-1])
    intervals = [b-a for a, b in zip(measured_starts, measured_starts[1:])]
    assert set(intervals) == {spec["minimum_window_initiation_interval"]}
    # Small deterministic generated image is always tested; user photos are optional extras.
    images = [("geometry", [[255 if (x//8+y//8)%2 else 0 for x in range(32)] for y in range(32)])]
    for p in sorted(Path(os.environ["CHIP_INPUTS"]).glob("*.png")):
        images.append((p.stem, gray_image(p, (128, 128))))
    image_files = []
    for name, image in images:
        for mode in range(3 if multi else 1):
            values = [await transact(w, mode) for w in windows(image)]
            target = output/f"{name}_mode{mode}_rtl.png"
            write_gray(target, values, len(image[0]), len(image))
            image_files.append(str(target))
    output.mkdir(parents=True, exist_ok=True)
    (output/"protocol_metrics.json").write_text(json.dumps({
        "seed":seed,"transactions_checked":checks,"cycles":cycles,
        "latencies_observed":sorted(set(latencies)),"initiation_intervals_observed":sorted(set(intervals)),
        "image_outputs":image_files,"kind":"actual_rtl_simulation"},indent=2)+"\n")
