# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Synchronization of the vehicle time with the grandmaster, and recovery from its absence."""

import time

import pytest
from gptp_grandmaster import (
    GrandMaster,
)
from helpers import (
    BIN,
    GM_IFACE,
    GM_OFFSET_NS,
    NEEDS_FLAG_PROPAGATION_FIX,
    SYNC_TIMEOUT_S,
    SYNC_TOLERANCE_NS,
    assert_no_jump_reported,
    drifts_from_grandmaster_pace_ns,
    probing,
    running_time_stack,
    sample_vehicle_time,
    start_time_slave,
    wait_for_stream,
    wait_for_stream_in_sync,
    wait_for_stream_reliable,
    wait_until_synchronized,
)


def test_binaries_are_deployed(target):
    """The time stack binaries exist and are executable on the target."""
    for binary in ("time_slave", "time_daemon", "vehicle_time_probe"):
        exit_code, output = target.execute(f"test -x {BIN}/{binary}")
        assert exit_code == 0, f"{binary} missing or not executable"


def test_not_synchronized_without_grandmaster(target, time_stack):
    """Without a grandmaster, vehicle time is neither synchronized nor reliable."""
    (sample,) = sample_vehicle_time(target)
    assert not sample["synchronized"]
    assert not sample["reliable"]


def test_synchronizes_to_grandmaster(target, time_stack, grandmaster):
    """With a grandmaster, vehicle time becomes synchronized, reliable and consistent."""
    wait_until_synchronized(target)

    (sample,) = sample_vehicle_time(target)
    assert sample["synchronized"] and sample["reliable"] and sample["consistent"]
    assert not sample["timeout"]


def test_vehicle_time_matches_grandmaster(request, target, platform, time_stack, grandmaster):
    """Vehicle time lies within SYNC_TOLERANCE_NS of the grandmaster time."""
    if platform.vehicle_time_offset_issue:
        request.applymarker(pytest.mark.xfail(strict=True, reason=platform.vehicle_time_offset_issue))
    wait_until_synchronized(target)

    before = grandmaster.time_ns()
    (sample,) = sample_vehicle_time(target)
    after = grandmaster.time_ns()

    assert before - SYNC_TOLERANCE_NS <= sample["vehicle_time_ns"] <= after + SYNC_TOLERANCE_NS


def test_vehicle_time_advances_with_grandmaster(target, time_stack, grandmaster):
    """Vehicle time is monotonic and advances at the pace of the grandmaster."""
    wait_until_synchronized(target)

    samples = sample_vehicle_time(target, samples=10, interval_ms=200)

    vehicle = [s["vehicle_time_ns"] for s in samples]
    assert vehicle == sorted(vehicle)
    assert all(abs(drift) < SYNC_TOLERANCE_NS for drift in drifts_from_grandmaster_pace_ns(samples))


@NEEDS_FLAG_PROPAGATION_FIX
def test_not_reliable_when_grandmaster_stops_and_recovery(target, time_stack, grandmaster):
    """Vehicle time becomes unreliable when sync stops and is synchronized again when it resumes."""
    with probing(target) as stream:
        wait_for_stream_reliable(stream)

        grandmaster.pause_sync()
        wait_for_stream(stream, lambda s: s["timeout"], SYNC_TIMEOUT_S, "timeout to be reported")
        assert not stream.latest()["reliable"]

        grandmaster.resume_sync()
        wait_for_stream_in_sync(stream)


def test_vehicle_time_follows_grandmaster_step(target, time_stack, grandmaster):
    """A step of the grandmaster time shows up in vehicle time.

    Vehicle time is compared to the local steady time rather than to the grandmaster
    time, so that the check is independent of the absolute value (see test_vehicle_time_matches_grandmaster).
    """
    step_ns = 2 * 1_000_000_000

    with probing(target) as stream:
        wait_for_stream_reliable(stream)
        baseline = stream.latest()

        grandmaster.step(step_ns)

        def stepped(sample):
            drift = drifts_from_grandmaster_pace_ns([baseline, sample])[1]
            return abs(drift - step_ns) < SYNC_TOLERANCE_NS

        wait_for_stream(stream, stepped, SYNC_TIMEOUT_S, f"vehicle time to follow the step (baseline {baseline})")


# --- grandmaster and time slave that come and go ---------------------------------------------------------------


@NEEDS_FLAG_PROPAGATION_FIX
def test_recovers_when_grandmaster_restarts(time_stack, probe_stream):
    """A new grandmaster, which starts its sequence ids from 0 again, is followed after the timeout of the old one."""
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS):
        wait_for_stream_reliable(probe_stream)
    wait_for_stream(probe_stream, lambda s: s["timeout"], 10, "timeout to be reported")

    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS):
        wait_for_stream_in_sync(probe_stream)


def test_sequence_id_wrap_around_is_neither_timeout_nor_jump(time_stack, probe_stream):
    """Sync/Follow_Up pairs keep being used when the sequence id wraps from 0xFFFF to 0."""
    # At 8 Syncs per second the id wraps after 2 s; stay within the start-up period of the jump detection (5 s).
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS, first_sequence_id=0x10000 - 16):
        wait_for_stream_reliable(probe_stream)
        mark = len(probe_stream.samples())
        time.sleep(3)
        samples = probe_stream.samples()[mark:]

    assert len(samples) > 10
    assert not [s for s in samples if s["timeout"]], "timeout reported"
    assert_no_jump_reported(samples)
    assert probe_stream.latest()["reliable"]


@pytest.mark.xfail(
    strict=True,
    reason="time_daemon connects to the shared memory of the time slave once and does not follow a restarted one (https://github.com/eclipse-score/time/issues/315)",
)
@pytest.mark.parametrize("how", ["stopped", "killed"])
def test_recovers_when_time_slave_is_restarted(target, platform, gptp_iface, grandmaster, how):
    """A time slave that is stopped or crashes, and then started again, is picked up by the running time daemon."""
    with running_time_stack(target, platform, gptp_iface) as (slave, _), probing(target) as stream:
        wait_for_stream_reliable(stream)

        if how == "killed":
            target.execute(f"kill -9 {slave.pid()}")
        else:
            slave.stop()
        wait_for_stream(stream, lambda s: s["timeout"], 10, "timeout to be reported")

        restarted = start_time_slave(target, gptp_iface)
        try:
            wait_for_stream_in_sync(stream, timeout_s=10)
        finally:
            restarted.stop()
