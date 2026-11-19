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

"""Start-up behavior and latency of the time stack."""

import time

import pytest
from gptp_grandmaster import (
    GrandMaster,
)
from helpers import (
    FIRST_SEQUENCE_ID,
    GM_IFACE,
    GM_OFFSET_NS,
    NEEDS_SOFTWARE_TIMESTAMP_FIX,
    SYNC_INTERVAL_S,
    SYNC_TIMEOUT_S,
    TIMEOUT_S,
    probing,
    running_time_stack,
    status_key,
    sync_events_after_first_sync,
    wait_for,
    wait_for_stream,
    wait_for_stream_in_sync,
)

# --- start-up (feat_req__time__veh_status_init / veh_startup_timeout) --------------------------------------------


def test_status_after_start_indicates_nothing(target, platform, gptp_iface):
    """Right after the start the status is neither synchronized, nor timeout, nor a time leap."""
    with running_time_stack(target, platform, gptp_iface):
        started = time.monotonic()
        with probing(target) as stream:
            wait_for(lambda: stream.latest() is not None, 10, "the vehicle time probe to report")
            if time.monotonic() - started > TIMEOUT_S - 1:
                pytest.skip("the probe took too long to start for the status to be checked before the timeout")
            first = stream.samples()[0]

    assert status_key(first) == (False, False, False, False), first


@pytest.mark.xfail(
    strict=False,
    raises=TimeoutError,
    reason="no timeout is indicated in the 15 s after the start of the feature when no Sync ever arrives, "
    "although the default timeout is 3.3 s (https://github.com/eclipse-score/time/issues/267)",
)
def test_timeout_is_indicated_when_no_sync_arrives_after_start(time_stack, probe_stream):
    """Without any Sync after the start of the feature the timeout is indicated, without synchronized."""
    wait_for_stream(probe_stream, lambda s: s["timeout"], 15, "the start-up timeout to be reported")
    latest = probe_stream.latest()
    assert latest["timeout"] and not latest["synchronized"], latest


def test_first_sync_after_start_is_processed(time_stack, event_probe_stream):
    """The time stack is ready before the network communicates: the very first Sync/Follow_Up pair is used."""
    # The first notification is for the update that never happened (see test_no_sync_update_is_notified_before...).
    time.sleep(1)
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS, first_sequence_id=FIRST_SEQUENCE_ID) as master:
        wait_for(
            lambda: sync_events_after_first_sync(event_probe_stream),
            SYNC_TIMEOUT_S,
            "the first update to be notified",
            lambda: f"events: {event_probe_stream.events()[:3]}",
        )
        first_sent = master.sync_log[0]["sequence_id"]
        first_notified = sync_events_after_first_sync(event_probe_stream)[0]["sequence_id"]

    assert first_notified == first_sent, (
        f"the update of Sync {first_sent} was not used, the first one is {first_notified}"
    )


@NEEDS_SOFTWARE_TIMESTAMP_FIX
def test_synchronized_within_one_sync_interval_of_the_first_update(time_stack, event_probe_stream):
    """The synchronized indication is delivered less than one Sync interval after the Sync of the first update.

    Both timestamps are CLOCK_MONOTONIC: the ingress timestamp of the Sync and the SteadyClock of the sample.
    """
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS, first_sequence_id=FIRST_SEQUENCE_ID):
        wait_for_stream_in_sync(event_probe_stream)
        time.sleep(1)
        first_update = sync_events_after_first_sync(event_probe_stream)[0]
        first_synchronized = next(s for s in event_probe_stream.samples() if s["synchronized"])

    latency_ns = first_synchronized["monotonic_time_ns"] - first_update["sync_ingress_ns"]
    assert 0 <= latency_ns < SYNC_INTERVAL_S * 1e9, f"synchronized {latency_ns / 1e6:.1f} ms after the Sync"
