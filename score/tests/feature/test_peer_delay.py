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

"""Peer delay measurement and its use."""

import statistics
import time

import pytest
from gptp_grandmaster import (
    GrandMaster,
)
from helpers import (
    GM_IFACE,
    GM_OFFSET_NS,
    PDELAY_INTERVAL_S,
    PEER_DELAY_NEEDS_TX_TIMESTAMP,
    SYNC_INTERVAL_S,
    assert_following_grandmaster,
    output_of,
    probing,
    remove_shm_files,
    running_time_stack,
    start_time_slave,
    vehicle_time_jumps_ns,
    wait_for,
    wait_for_stream_in_sync,
    wait_for_stream_reliable,
    wait_for_vehicle_time_jump,
    write_json_file,
)

# --- peer delay (feat_req__time__veh_pdelay_comp / _discard / veh_sync_no_pdelay / veh_ascapable_thresh) ---------

# Far above the delay of the virtual link, and large against the noise of a jump of the vehicle time.
LINK_DELAY_NS = 2_000_000_000


JUMP_TOLERANCE_NS = 400_000_000


@PEER_DELAY_NEEDS_TX_TIMESTAMP
def test_link_delay_is_compensated(time_stack, probe_stream, grandmaster):
    """The peer delay that the time slave measures is added to the grandmaster time, and follows changes of it."""
    wait_for_stream_reliable(probe_stream)

    mark = len(probe_stream.samples())
    grandmaster.pdelay_extra_delay_ns = LINK_DELAY_NS
    wait_for_vehicle_time_jump(probe_stream, mark, LINK_DELAY_NS, "the link delay", JUMP_TOLERANCE_NS)

    mark = len(probe_stream.samples())
    grandmaster.pdelay_extra_delay_ns = 0
    wait_for_vehicle_time_jump(probe_stream, mark, -LINK_DELAY_NS, "the link delay being gone", JUMP_TOLERANCE_NS)


@pytest.mark.xfail(
    strict=True,
    reason="no peer delay is measured on a NIC without TX timestamps (see PEER_DELAY_NEEDS_TX_TIMESTAMP), and "
    "time_slave has no discard threshold: any positive peer delay would be applied to the vehicle time (https://github.com/eclipse-score/time/issues/257)",
)
def test_peer_delay_above_discard_threshold_is_not_applied(time_stack, probe_stream, grandmaster):
    """A peer delay of 5 s is far above any discard threshold of a project, so it must not shift the vehicle time."""
    wait_for_stream_reliable(probe_stream)
    # Without this, the test would pass whenever no peer delay is applied at all.
    mark = len(probe_stream.samples())
    grandmaster.pdelay_extra_delay_ns = LINK_DELAY_NS
    wait_for_vehicle_time_jump(probe_stream, mark, LINK_DELAY_NS, "the link delay", JUMP_TOLERANCE_NS)

    mark = len(probe_stream.samples())
    grandmaster.pdelay_extra_delay_ns = 5_000_000_000
    # The delay is measured with the next Pdelay_Req and used by the next Sync.
    time.sleep(3 * PDELAY_INTERVAL_S)

    jumps = vehicle_time_jumps_ns(probe_stream.samples()[mark:])
    assert jumps and all(abs(jump) < JUMP_TOLERANCE_NS for jump in jumps), (
        f"vehicle time jumped by {max(jumps, key=abs)} ns"
    )


def test_synchronizes_when_peer_delay_is_not_answered(time_stack, probe_stream):
    """Without a Pdelay_Resp the time slave still synchronizes and keeps requesting."""
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS, answer_pdelay=False) as master:
        wait_for_stream_reliable(probe_stream)
        mark = len(probe_stream.samples())
        requests = len(master.pdelay_request_times)
        time.sleep(4 * PDELAY_INTERVAL_S)
        samples = probe_stream.samples()[mark:]

        assert master.pdelay_count == 0
        assert len(master.pdelay_request_times) - requests >= 3, "Pdelay_Req messages stopped"
    assert_following_grandmaster(samples)


@pytest.mark.parametrize("delay_ns", [100_000_000, 2_000_000_000], ids=["100ms", "2s"])
def test_synchronizes_when_peer_delay_is_very_large(time_stack, probe_stream, delay_ns):
    """A peer delay far above neighborPropDelayThresh neither stops the synchronization nor the Pdelay_Req.

    The time slave does not measure the delay on every NIC (see PEER_DELAY_NEEDS_TX_TIMESTAMP): the test only shows
    that this does not matter, which is also what the requirement asks for when there is no valid measurement.
    """
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS, pdelay_extra_delay_ns=delay_ns) as master:
        wait_for_stream_reliable(probe_stream)
        requests = len(master.pdelay_request_times)
        time.sleep(4 * PDELAY_INTERVAL_S)
        latest = probe_stream.latest()

        assert master.pdelay_count > 0
        assert len(master.pdelay_request_times) - requests >= 3, "Pdelay_Req messages stopped"
    assert latest["synchronized"] and not latest["timeout"]


# --- first Pdelay_Req after start-up (feat_req__time__veh_startup_pdelay) ----------------------------------------


def wait_for_log_line(handle, text, timeout_s):
    """Wait for `text` in the output of `handle` and return time.monotonic() of the poll that saw it."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if text in output_of(handle):
            return time.monotonic()
        time.sleep(0.005)
    raise TimeoutError(f"{text!r} not logged within {timeout_s} s\n{output_of(handle)}")


@pytest.mark.parametrize(
    "warmup_ms",
    [
        pytest.param(0, id="without_warmup"),
        pytest.param(
            None,
            id="default_warmup",
            marks=pytest.mark.xfail(
                strict=True,
                reason="the Pdelay_Req warm-up of the project configuration is 2 s, which is far above the "
                "synchronization interval of 125 ms that the first Pdelay_Req is required to follow the start by",
            ),
        ),
    ],
)
def test_first_pdelay_request_follows_the_start_within_one_sync_interval(target, platform, gptp_iface, warmup_ms):
    """With the feature started and the link up, the first Pdelay_Req comes within one synchronization interval."""
    config = "/opt/etc/time_slave_config.json"
    if warmup_ms is not None:
        config = "/tmp/no_warmup_config.json"
        write_json_file(target, config, {"pdelay_warmup_ms": warmup_ms})
    remove_shm_files(target, platform)
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS) as master:
        slave = start_time_slave(target, gptp_iface, config)
        try:
            started = wait_for_log_line(slave, "TimeSlave initialized", 10)
            wait_for(lambda: master.pdelay_request_times, 10, "the first Pdelay_Req")
            first = master.pdelay_request_times[0]
        finally:
            slave.stop()
            remove_shm_files(target, platform)

    assert first - started < SYNC_INTERVAL_S, f"the first Pdelay_Req came {first - started:.3f} s after the start"


# --- peer delay is kept over a restart (feat_req__time__veh_pdelay_persist) --------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=TimeoutError,
    reason="no peer delay is measured on a NIC without TX timestamps (see PEER_DELAY_NEEDS_TX_TIMESTAMP), and "
    "nothing in time_slave stores a peer delay, so a restarted time slave would not have one either (https://github.com/eclipse-score/time/issues/257)",
)
def test_peer_delay_is_used_after_a_restart_until_a_new_one_is_measured(target, platform, gptp_iface):
    """A restarted time stack applies the last peer delay, while no Pdelay_Resp is received to measure a new one."""

    def offset_to_local_ns(stream):
        recent = stream.samples()[-10:]
        return statistics.mean(s["vehicle_time_ns"] - s["steady_time_ns"] for s in recent)

    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS) as master:
        with running_time_stack(target, platform, gptp_iface), probing(target) as stream:
            wait_for_stream_in_sync(stream)
            mark = len(stream.samples())
            master.pdelay_extra_delay_ns = LINK_DELAY_NS
            wait_for_vehicle_time_jump(stream, mark, LINK_DELAY_NS, "the link delay", JUMP_TOLERANCE_NS)
            time.sleep(1)
            with_delay = offset_to_local_ns(stream)

        master.answer_pdelay = False
        with running_time_stack(target, platform, gptp_iface), probing(target) as stream:
            wait_for_stream_in_sync(stream)
            time.sleep(1)
            restarted = offset_to_local_ns(stream)

    # Not within the delay of the one that is lost: that is the offset without a peer delay. The local clock may run
    # fast, which accumulates in the offset over the restart, but far less than the half of the delay.
    assert abs(restarted - with_delay) < LINK_DELAY_NS / 2, f"{(restarted - with_delay) / 1e9:.2f} s off"
