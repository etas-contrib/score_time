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

"""Fixtures of the end-to-end tests of the features."""

from fixtures import (  # noqa: F401  (fixtures, found by pytest in this module)
    event_probe_stream,
    gptp_iface,
    grandmaster,
    jump_detection_armed,
    platform,
    probe_stream,
    time_stack,
)
