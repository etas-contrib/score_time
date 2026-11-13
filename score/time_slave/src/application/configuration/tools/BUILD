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
# *******************************************************************************

# Build-time tool deriving keys/ranges/defaults from the schema (single source of truth).
cc_binary(
    name = "gen_config_limits",
    srcs = ["gen_config_limits.cpp"],
    tags = ["QM"],
    visibility = ["//score/time_slave/src/application/configuration:__pkg__"],
    deps = [
        "@score_baselibs//score/json",
        "@score_baselibs//score/json:json_parser",
    ],
)
