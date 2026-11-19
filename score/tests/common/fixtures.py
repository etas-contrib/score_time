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

"""Fixtures of the end-to-end tests, made available by the conftest.py of the test directories."""

import time

import pytest
from gptp_grandmaster import (
    GrandMaster,
)
from helpers import (
    GM_IFACE,
    GM_OFFSET_NS,
    JUMP_DEBOUNCE_S,
    PLATFORMS,
    probing,
    running_time_stack,
    wait_for_stream_reliable,
)


@pytest.fixture
def platform(target):
    exit_code, output = target.execute("uname -s")
    assert exit_code == 0, output
    return PLATFORMS[output.decode().strip()]


@pytest.fixture
def gptp_iface(target, platform):
    """Name of the network interface of the target that is connected to the grandmaster."""
    exit_code, output = target.execute(platform.gptp_iface_command)
    assert exit_code == 0 and output.strip(), output
    return output.decode().strip()


@pytest.fixture
def time_stack(target, platform, gptp_iface):
    with running_time_stack(target, platform, gptp_iface) as stack:
        yield stack


@pytest.fixture
def probe_stream(target, time_stack):
    # Depends on time_stack so that the probe never starts before the time stack's shared memory exists.
    with probing(target) as stream:
        yield stream


@pytest.fixture
def event_probe_stream(target, time_stack):
    """Probe stream whose probe subscribed to the notifications of the vehicle clock."""
    with probing(target, events=True) as stream:
        yield stream


@pytest.fixture
def grandmaster():
    """gPTP grandmaster on GM_IFACE, offset by GM_OFFSET_NS from the host clock."""
    with GrandMaster(GM_IFACE, offset_ns=GM_OFFSET_NS) as master:
        yield master


@pytest.fixture
def jump_detection_armed(time_stack, probe_stream, grandmaster):
    """Synchronized time stack in which the start-up suppression of time jumps (5 s) is over."""
    wait_for_stream_reliable(probe_stream)
    time.sleep(JUMP_DEBOUNCE_S + 2)
    assert probe_stream.latest()["reliable"]
    return probe_stream
