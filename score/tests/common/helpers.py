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

"""Constants and helpers shared by the end-to-end tests."""

import json
import shlex
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from gptp_grandmaster import (
    MSG_PDELAY_RESP,
    MSG_PDELAY_RESP_FOLLOW_UP,
)

BIN = "/opt/bin"


ENV = "MW_LOG_CONFIG_FILE=/opt/etc/logging.json"


GM_IFACE = "tap0"


# Offset of the grandmaster against the host clock: far enough from the target's
# own clock that a result which merely echoes the local time cannot pass.
GM_OFFSET_NS = 3600 * 1_000_000_000


SYNC_TOLERANCE_NS = 50_000_000


SYNC_TIMEOUT_S = 30


# Defaults of the time daemon (see comp_req__time_daemon__*): the jump limit is 500 us, jumps are not reported
# for 5 s after the initial synchronization, the timeout is 3.3 s and a jump is cleared by 2 valid frames.
JUMP_THRESHOLD_NS = 500_000


JUMP_DEBOUNCE_S = 5


TIMEOUT_S = 3.3


# Time slave defaults that are configured in config/time_slave_config.json.
PDELAY_WARMUP_S = 2.0


PDELAY_INTERVAL_S = 1.0


# Domain number of the grandmaster in tests that configure the time slave for a domain other than the default 0.
OTHER_DOMAIN = 5


@dataclass(frozen=True)
class Platform:
    # Command that prints the name of the network interface connected to the grandmaster.
    gptp_iface_command: str
    # Shared memory files of the time stack, which are removed before and after each test.
    shm_files: str
    # Reason why vehicle time is known to be offset from the grandmaster time, if it is. The time
    # slave and the application have to use the same local clock for it to be correct.
    vehicle_time_offset_issue: str = ""


# Keyed by the output of `uname -s` on the target.
PLATFORMS = {
    "Linux": Platform(
        gptp_iface_command="ls /sys/class/net | grep -v '^lo$' | head -n 1",
        shm_files="/dev/shm/gptp_* /dev/shm/svt_*",
        vehicle_time_offset_issue="time_slave stamps local_time with CLOCK_MONOTONIC, but HighResSteadyClock on "
        "Linux is based on std::chrono::high_resolution_clock (CLOCK_REALTIME), so VehicleClock::Now() is off "
        "by the epoch offset (https://github.com/eclipse-score/time/issues/310)",
    ),
    "QNX": Platform(
        gptp_iface_command="echo vtnet0",
        shm_files="/dev/shmem/gptp_* /dev/shmem/svt_*",
        vehicle_time_offset_issue="time_slave stamps local_time with CLOCK_MONOTONIC, but HighResSteadyClock on "
        "QNX is based on ClockCycles(), which is about 0.4 s ahead of CLOCK_MONOTONIC, so VehicleClock::Now() "
        "is off by that difference (https://github.com/eclipse-score/time/issues/310)",
    ),
}


def wait_for(condition, timeout_s, what, details=lambda: ""):
    """Poll `condition` until it is true; raise TimeoutError with `details()` appended otherwise."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise TimeoutError(f"timed out after {timeout_s}s waiting for {what}\n{details()}")


def output_of(handle):
    """Output of an asynchronously executed process as text."""
    output = handle.get_output()
    return output.decode(errors="replace") if isinstance(output, bytes) else output


def log_of(handle):
    """Output of a process with whitespace collapsed, as the log pads streamed values with spaces."""
    return " ".join(output_of(handle).split())


def sample_vehicle_time(target, samples=1, interval_ms=100):
    """Run the vehicle time probe on the target and return its parsed samples."""
    exit_code, output = target.execute(f"{BIN}/vehicle_time_probe --samples {samples} --interval-ms {interval_ms}")
    assert exit_code == 0, output
    return [json.loads(line) for line in output.decode().splitlines() if line.startswith("{")]


def start_time_slave(target, gptp_iface, config="/opt/etc/time_slave_config.json", env=""):
    config_arg = f" --config {config}" if config else ""
    return target.execute_async(
        f"exec env {ENV} {env} GPTP_IFACE={gptp_iface} {BIN}/time_slave{config_arg}", cwd="/opt"
    )


def start_time_daemon(target):
    return target.execute_async(f"exec env {ENV} {BIN}/time_daemon", cwd="/opt")


def remove_shm_files(target, platform):
    target.execute(f"rm -f {platform.shm_files}")


def present_shm_files(target, platform):
    _, output = target.execute(f"ls -1 {platform.shm_files} 2>/dev/null")
    return output.decode().split()


def write_text_file(target, path, text):
    # echo, as QNX has no printf; it adds a newline, which no test depends on.
    exit_code, output = target.execute(f"echo {shlex.quote(text)} > {path}")
    assert exit_code == 0, output


def write_json_file(target, path, content):
    write_text_file(target, path, json.dumps(content))


@contextmanager
def running_time_stack(target, platform, gptp_iface, config="/opt/etc/time_slave_config.json", slave_env=""):
    """Time slave and time daemon running on the target, in this start-up order.

    `config` is passed as --config, unless it is None. `slave_env` holds additional VAR=value settings.
    """
    remove_shm_files(target, platform)
    slave = start_time_slave(target, gptp_iface, config, slave_env)
    try:
        wait_for(
            lambda: "TimeSlave initialized" in output_of(slave),
            10,
            "time_slave to initialize",
            lambda: output_of(slave),
        )
        daemon = start_time_daemon(target)
        try:
            yield slave, daemon
        finally:
            daemon.stop()
    finally:
        slave.stop()
        remove_shm_files(target, platform)


class ProbeStream:
    """Vehicle time probe sampling continuously on the target.

    Polling the probe with one execute() per sample is too slow to see short-lived status changes
    such as a time jump, which is cleared again after two sync frames.

    With `events`, the probe also prints the notifications that it receives, see events().
    """

    def __init__(self, target, interval_ms=20, events=False):
        self._process = target.execute_async(
            f"exec {BIN}/vehicle_time_probe --samples 0 --interval-ms {interval_ms}{' --events' if events else ''}",
            cwd="/opt",
        )
        self._samples = []
        self._events = []
        self._consumed = 0  # characters of the output that are already parsed

    def _parse_new_output(self):
        output = output_of(self._process)
        complete = output.rfind("\n") + 1  # a trailing partial line is parsed once it is complete
        for line in output[self._consumed : complete].splitlines():
            if line.startswith("{") and line.endswith("}"):
                self._samples.append(json.loads(line))
            elif line.startswith("EVENT {") and line.endswith("}"):
                self._events.append(json.loads(line[len("EVENT ") :]))
        self._consumed = complete

    def samples(self):
        """All samples so far. Only the output that is new since the last call is parsed."""
        self._parse_new_output()
        return list(self._samples)

    def events(self, kind=None):
        """All notifications so far (of one `kind`: "status", "sync" or "pdelay"), in the order they were delivered."""
        self._parse_new_output()
        return [e for e in self._events if kind is None or e["event"] == kind]

    def latest(self):
        samples = self.samples()
        return samples[-1] if samples else None

    def stop(self):
        self._process.stop()


@contextmanager
def probing(target, events=False, interval_ms=20):
    stream = ProbeStream(target, interval_ms=interval_ms, events=events)
    try:
        yield stream
    finally:
        stream.stop()


def wait_until_synchronized(target):
    """Block until the vehicle time probe reports reliable time."""
    with probing(target) as stream:
        wait_for_stream_reliable(stream)


def drifts_from_grandmaster_pace_ns(samples):
    """Deviation of each sample's vehicle time from the time elapsed since the first sample, in nanoseconds.

    Vehicle time follows the grandmaster, but the local steady clock may run at another rate (the clock of a QEMU
    guest runs 1 - 2 % fast). The elapsed steady time is therefore divided by the mean rate_deviation, which is the
    local time per grandmaster time.
    """
    rate = statistics.mean(s["rate_deviation"] for s in samples)
    assert rate > 0, "no rate deviation reported"
    first = samples[0]
    return [
        (s["vehicle_time_ns"] - first["vehicle_time_ns"]) - (s["steady_time_ns"] - first["steady_time_ns"]) / rate
        for s in samples
    ]


# Fixes that are not part of this change, which the tests marked with these need. Not strict: they are expected
# to fail without the fix and to pass once it is in, so the marker can be removed then.
NEEDS_FLAG_PROPAGATION_FIX = pytest.mark.xfail(
    strict=False,
    reason="needs the fix that propagates the timeout and time jump flags (the time slave cleared is_correct on "
    "timeouts and jumps, so ConvertPtpStatus dropped all flags): b810c4e on mattday-etas-itests (https://github.com/eclipse-score/time/issues/324)",
)


NEEDS_SOFTWARE_TIMESTAMP_FIX = pytest.mark.xfail(
    strict=False,
    reason="needs the fix for NICs without hardware timestamping (the ingress timestamp of a Sync is 0, so neither "
    "the sync ingress time nor the rate deviation are usable): 1111cbc on mattday-etas-itests (https://github.com/eclipse-score/time/issues/257)",
)
NEEDS_JUMP_DETECTION_FIXES = pytest.mark.xfail(
    strict=False,
    reason="needs the fixes for the time jump detection: propagation of the jump flags (b810c4e), the software "
    "timestamp fallback of NICs without hardware timestamps (1111cbc), and ignoring repeated frames in "
    "TimeJumpsValidator (2bc1bad), all on mattday-etas-itests (https://github.com/eclipse-score/time/issues/324, https://github.com/eclipse-score/time/issues/325, https://github.com/eclipse-score/time/issues/257)",
)


LEAP_FLAGS = ("leap_future", "leap_past")


# The time daemon's jump limit is a fixed 500 us, and its jump detection compares the local time between two Syncs
# with the grandmaster time between them. The clock of the QEMU guest runs 1 - 2 % fast (nested KVM), which is
# 1 - 2.5 ms per Sync interval, so once the start-up period (5 s) is over, almost every Sync is reported as a
# time jump to the past. Not strict, as they may pass when the guest clock happens to be accurate. The exact limit is
# covered by the unit tests of the time jump validator.
JUMP_LIMIT_BELOW_LINK_NOISE = pytest.mark.xfail(
    strict=False,
    reason="500 us jump limit of the time daemon is below the clock rate error of the QEMU guest (https://github.com/eclipse-score/time/issues/264)",
)


def wait_for_stream(stream, condition, timeout_s, what):
    """Wait until `condition(latest_sample)` holds for the latest sample of the probe stream."""
    wait_for(
        lambda: (stream.latest() is not None) and condition(stream.latest()),
        timeout_s,
        what,
        lambda: f"latest sample: {stream.latest()}",
    )


def wait_for_stream_reliable(stream):
    wait_for_stream(stream, lambda s: s["reliable"], SYNC_TIMEOUT_S, "vehicle time to become reliable")


def wait_for_stream_in_sync(stream, timeout_s=SYNC_TIMEOUT_S):
    """Wait for synchronized time without timeout, whatever the time jump flags are.

    Unlike reliable time, this does not depend on the time jump detection, which flags nearly every Sync once its
    start-up period is over when the local clock runs at another rate than the grandmaster (see the note at
    JUMP_LIMIT_BELOW_LINK_NOISE).
    """
    wait_for_stream(
        stream, lambda s: s["synchronized"] and not s["timeout"], timeout_s, "vehicle time to be synchronized"
    )


def assert_no_jump_reported(samples):
    assert not [s for s in samples if s["leap_future"] or s["leap_past"]], "unexpected time jump flag"


UNUSABLE_SYNC_DWELL_S = 2.0


# --- peer delay responder (comp_req__time_slave__pdelay_req_response / ethernet_address / domain_filtering) ---------


def request_peer_delay(master, domain=None):
    """Send a Pdelay_Req as a peer and return the Pdelay_Resp and Pdelay_Resp_Follow_Up that answer it."""
    sequence_id = master.send_pdelay_request(domain)

    def replies():
        return [r for r in list(master.pdelay_replies) if r["sequence_id"] == sequence_id]

    wait_for(lambda: len(replies()) >= 2, 3, "the answers to the Pdelay_Req", lambda: str(master.pdelay_replies))
    by_type = {r["type"]: r for r in replies()}
    return by_type[MSG_PDELAY_RESP], by_type[MSG_PDELAY_RESP_FOLLOW_UP]


def vehicle_time_jumps_ns(samples):
    """Change of the vehicle time from one sample to the next, beyond the time that the steady clock advanced.

    An update of the vehicle time is applied at once, so it is a single jump between two samples. This does not depend
    on the pace of the vehicle time, which cannot be derived from the steady clock: the HighResSteadyClock of Linux is
    based on CLOCK_REALTIME, which the guest slews and steps.
    """
    return [
        (b["vehicle_time_ns"] - a["vehicle_time_ns"]) - (b["steady_time_ns"] - a["steady_time_ns"])
        for a, b in zip(samples, samples[1:])
    ]


def wait_for_vehicle_time_jump(stream, mark, expected_ns, what, tolerance_ns=SYNC_TOLERANCE_NS):
    """Wait until the vehicle time jumped by `expected_ns` since the `mark`-th sample, because of `what`."""
    wait_for(
        lambda: any(abs(jump - expected_ns) < tolerance_ns for jump in vehicle_time_jumps_ns(stream.samples()[mark:])),
        SYNC_TIMEOUT_S,
        f"vehicle time to jump by {expected_ns} ns because of {what}",
        lambda: f"jumps: {[j for j in vehicle_time_jumps_ns(stream.samples()[mark:]) if abs(j) > 10_000_000]}",
    )


def assert_following_grandmaster(samples):
    """The samples are synchronized, without timeout, and advance at the pace of the grandmaster."""
    assert len(samples) > 10
    assert all(s["synchronized"] and not s["timeout"] for s in samples)
    assert all(abs(drift) < SYNC_TOLERANCE_NS for drift in drifts_from_grandmaster_pace_ns(samples))


# On a NIC without TX timestamps (such as the virtual NIC of the QEMU target) a peer delay is never measured:
# PeerDelayMeasurer::SendRequest() keeps t1 as "pending" while RawSocketImpl::Send() waits up to 50 ms for a TX
# timestamp that does not come, the Pdelay_Resp arrives within that time, and the measurement that is dropped because
# of the pending t1 is not computed again. t1 would be 0 afterwards, i.e. the software TX timestamp is no fallback.
PEER_DELAY_NEEDS_TX_TIMESTAMP = pytest.mark.xfail(
    strict=True,
    raises=TimeoutError,
    reason="time_slave never completes a peer delay measurement on a NIC without TX timestamps: the response "
    "arrives while t1 is still pending, and the measurement is not recomputed (https://github.com/eclipse-score/time/issues/257)",
)


def status_key(status):
    return (status["synchronized"], status["timeout"], status["leap_future"], status["leap_past"])


# --- notification of time synchronization updates (feat_req__time__veh_data_notify / veh_sync_data) ---------------


FIRST_SEQUENCE_ID = 1000  # not 0, which the sequenceId of an update that never happened is


def sync_events_after_first_sync(stream):
    """The sync notifications that are for an update of the grandmaster (see the test of the very first one)."""
    return [e for e in stream.events("sync") if e["precise_origin_ns"] != 0]


LEAP_STEP_NS = 100_000_000


# --- latency (feat_req__time__veh_sync_latency / veh_startup_ready) -----------------------------------------------

SYNC_INTERVAL_S = 0.125  # the synchronization interval that the grandmaster is specified to use, see GrandMaster
