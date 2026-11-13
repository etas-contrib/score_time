/********************************************************************************
 * Copyright (c) 2026 Contributors to the Eclipse Foundation
 *
 * See the NOTICE file(s) distributed with this work for additional
 * information regarding copyright ownership.
 *
 * This program and the accompanying materials are made available under the
 * terms of the Apache License Version 2.0 which is available at
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * SPDX-License-Identifier: Apache-2.0
 ********************************************************************************/
#ifndef SCORE_TIME_SLAVE_CONFIGURATION_CONFIG_LIMITS_H
#define SCORE_TIME_SLAVE_CONFIGURATION_CONFIG_LIMITS_H

#include <array>
#include <cstdint>
#include <limits>
#include <string_view>

namespace score
{
namespace ts
{
namespace config_schema
{

/// Hand-written mirror of time_slave_config_schema.json (keys, ranges, defaults).
///
/// The parser enforces exactly these values. config_schema_consistency_test compares this
/// table with the schema file in both directions, so any drift fails the build's tests.

struct IntProperty
{
    std::string_view key;
    std::int64_t min;
    std::int64_t max;
    std::int64_t default_value;
};

struct BoolProperty
{
    std::string_view key;
    bool default_value;
};

struct StringProperty
{
    std::string_view key;
    std::string_view default_value;
};

inline constexpr std::int64_t kNoMax = std::numeric_limits<std::int64_t>::max();

// ---- root ----
inline constexpr StringProperty kIfaceName{"iface_name", "emac0"};
inline constexpr IntProperty kDomainNumber{"domain_number", 0, 127, 0};
inline constexpr IntProperty kPdelayReqIntervalMs{"pdelay_req_interval_ms", 10, 60000, 1000};
inline constexpr IntProperty kPdelayWarmupMs{"pdelay_warmup_ms", 0, 60000, 2000};
inline constexpr IntProperty kSyncTimeoutMs{"sync_timeout_ms", 10, 60000, 3300};
inline constexpr IntProperty kJumpFutureThresholdNs{"jump_future_threshold_ns", 0, kNoMax, 500'000'000};
inline constexpr StringProperty kShmPath{"shm_path", "/gptp_shmem"};
inline constexpr std::string_view kPhcKey{"phc"};
inline constexpr std::string_view kQnxKey{"qnx"};
inline constexpr std::array kRootKeys{kIfaceName.key,
                                      kDomainNumber.key,
                                      kPdelayReqIntervalMs.key,
                                      kPdelayWarmupMs.key,
                                      kSyncTimeoutMs.key,
                                      kJumpFutureThresholdNs.key,
                                      kShmPath.key,
                                      kPhcKey,
                                      kQnxKey};

// ---- phc ----
inline constexpr BoolProperty kPhcEnabled{"enabled", false};
inline constexpr StringProperty kPhcDevice{"device", ""};
inline constexpr IntProperty kPhcStepThresholdNs{"step_threshold_ns", 0, kNoMax, 100'000'000};
inline constexpr std::array kPhcKeys{kPhcEnabled.key, kPhcDevice.key, kPhcStepThresholdNs.key};

// ---- qnx ----
inline constexpr StringProperty kQnxBpfDevicePath{"bpf_device_path", "/dev/bpf"};
inline constexpr BoolProperty kQnxSeeSent{"see_sent", false};
inline constexpr std::array kQnxKeys{kQnxBpfDevicePath.key, kQnxSeeSent.key};

}  // namespace config_schema
}  // namespace ts
}  // namespace score

#endif  // SCORE_TIME_SLAVE_CONFIGURATION_CONFIG_LIMITS_H
