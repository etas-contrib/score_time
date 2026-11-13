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
#include "score/time_slave/src/application/configuration/config_parser.h"

#include <gtest/gtest.h>

#include <fstream>
#include <string>

namespace score
{
namespace ts
{
namespace
{

using ::testing::TestWithParam;
using ::testing::ValuesIn;

/// Write @p content to a temp file and return its path.
std::string WriteTempFile(const std::string& name, const std::string& content)
{
    const std::string path = testing::TempDir() + name;
    std::ofstream ofs(path);
    ofs << content;
    return path;
}

TEST(ConfigParserTest, EmptyObjectReturnsDefaults)
{
    const auto path = WriteTempFile("empty_config.json", "{}");
    const auto cfg = ParseConfig(path);

    EXPECT_EQ(cfg.engine_opts.iface_name, "emac0");
    EXPECT_EQ(cfg.engine_opts.domain_number, 0);
    EXPECT_EQ(cfg.engine_opts.pdelay_req_interval_ms, 1000);
    EXPECT_EQ(cfg.engine_opts.pdelay_warmup_ms, 2000);
    EXPECT_EQ(cfg.engine_opts.sync_timeout_ms, 3300);
    EXPECT_EQ(cfg.engine_opts.jump_future_threshold_ns, 500'000'000LL);
    EXPECT_EQ(cfg.shm_path, "/gptp_shmem");
    EXPECT_FALSE(cfg.engine_opts.phc_config.enabled);
    EXPECT_EQ(cfg.qnx.bpf_device_path, score::ts::env::qnx::kBpfDevicePathDefault);
    EXPECT_FALSE(cfg.qnx.see_sent);
}

TEST(ConfigParserTest, ParseAllTopLevelFields)
{
    const std::string json = R"({
        "iface_name": "eth1",
        "domain_number": 5,
        "pdelay_req_interval_ms": 500,
        "pdelay_warmup_ms": 1000,
        "sync_timeout_ms": 2000,
        "jump_future_threshold_ns": 100000000,
        "shm_path": "/custom_shm"
    })";
    const auto path = WriteTempFile("full_config.json", json);
    const auto cfg = ParseConfig(path);

    EXPECT_EQ(cfg.engine_opts.iface_name, "eth1");
    EXPECT_EQ(cfg.engine_opts.domain_number, 5);
    EXPECT_EQ(cfg.engine_opts.pdelay_req_interval_ms, 500);
    EXPECT_EQ(cfg.engine_opts.pdelay_warmup_ms, 1000);
    EXPECT_EQ(cfg.engine_opts.sync_timeout_ms, 2000);
    EXPECT_EQ(cfg.engine_opts.jump_future_threshold_ns, 100'000'000LL);
    EXPECT_EQ(cfg.shm_path, "/custom_shm");
}

TEST(ConfigParserTest, ParsePhcConfig)
{
    const std::string json = R"({
        "phc": {
            "enabled": true,
            "device": "ptp0",
            "step_threshold_ns": 50000000
        }
    })";
    const auto path = WriteTempFile("phc_config.json", json);
    const auto cfg = ParseConfig(path);

    EXPECT_TRUE(cfg.engine_opts.phc_config.enabled);
    EXPECT_EQ(cfg.engine_opts.phc_config.device, "ptp0");
    EXPECT_EQ(cfg.engine_opts.phc_config.step_threshold_ns, 50'000'000);
}

TEST(ConfigParserTest, ParseQnxConfig)
{
    const std::string json = R"({
        "qnx": {
            "bpf_device_path": "/dev/bpf_test",
            "see_sent": true
        }
    })";
    const auto path = WriteTempFile("qnx_config.json", json);
    const auto cfg = ParseConfig(path);

    EXPECT_EQ(cfg.qnx.bpf_device_path, "/dev/bpf_test");
    EXPECT_TRUE(cfg.qnx.see_sent);
}

TEST(ConfigParserTest, ParsePartialFields)
{
    const std::string json = R"({
        "iface_name": "eth2"
    })";
    const auto path = WriteTempFile("partial_config.json", json);
    const auto cfg = ParseConfig(path);

    // Only iface_name changed; everything else keeps default.
    EXPECT_EQ(cfg.engine_opts.iface_name, "eth2");
    EXPECT_EQ(cfg.engine_opts.domain_number, 0);
    EXPECT_EQ(cfg.engine_opts.pdelay_req_interval_ms, 1000);
    EXPECT_EQ(cfg.shm_path, "/gptp_shmem");
    EXPECT_FALSE(cfg.engine_opts.phc_config.enabled);
    EXPECT_FALSE(cfg.qnx.see_sent);
}

TEST(ConfigParserTest, FullExampleConfigRoundTrip)
{
    const auto path = WriteTempFile("example.json",
                                    "{\n"
                                    "    \"iface_name\": \"emac0\",\n"
                                    "    \"domain_number\": 0,\n"
                                    "    \"pdelay_req_interval_ms\": 1000,\n"
                                    "    \"pdelay_warmup_ms\": 2000,\n"
                                    "    \"sync_timeout_ms\": 3300,\n"
                                    "    \"jump_future_threshold_ns\": 500000000,\n"
                                    "    \"shm_path\": \"/gptp_shmem\",\n"
                                    "    \"phc\": {\n"
                                    "        \"enabled\": true,\n"
                                    "        \"device\": \"emac0\",\n"
                                    "        \"step_threshold_ns\": 100000000\n"
                                    "    },\n"
                                    "    \"qnx\": {\n"
                                    "        \"bpf_device_path\": \"/dev/bpf\",\n"
                                    "        \"see_sent\": true\n"
                                    "    }\n"
                                    "}\n");

    const auto cfg = ParseConfig(path);

    EXPECT_EQ(cfg.engine_opts.iface_name, "emac0");
    EXPECT_EQ(cfg.engine_opts.domain_number, 0);
    EXPECT_EQ(cfg.engine_opts.pdelay_req_interval_ms, 1000);
    EXPECT_EQ(cfg.engine_opts.pdelay_warmup_ms, 2000);
    EXPECT_EQ(cfg.engine_opts.sync_timeout_ms, 3300);
    EXPECT_EQ(cfg.engine_opts.jump_future_threshold_ns, 500'000'000LL);
    EXPECT_EQ(cfg.shm_path, "/gptp_shmem");
    EXPECT_TRUE(cfg.engine_opts.phc_config.enabled);
    EXPECT_EQ(cfg.engine_opts.phc_config.device, "emac0");
    EXPECT_EQ(cfg.engine_opts.phc_config.step_threshold_ns, 100'000'000);
    EXPECT_EQ(cfg.qnx.bpf_device_path, "/dev/bpf");
    EXPECT_TRUE(cfg.qnx.see_sent);
}

// ---- Schema validation (issue #314) ----------------------------------------

struct RangeCase
{
    const char* name;
    const char* json;
};

class ConfigParserInvalidTest : public TestWithParam<RangeCase>
{
};

TEST_P(ConfigParserInvalidTest, RejectsValueViolatingSchema)
{
    const auto path = WriteTempFile(std::string{"invalid_"} + GetParam().name + ".json", GetParam().json);
    EXPECT_DEATH(ParseConfig(path), "");
}

const RangeCase kInvalidCases[] = {
    {"domain_above_max", R"({"domain_number": 128})"},
    {"domain_negative", R"({"domain_number": -1})"},
    {"domain_wraps_uint8", R"({"domain_number": 256})"},
    {"pdelay_interval_below_min", R"({"pdelay_req_interval_ms": 9})"},
    {"pdelay_interval_above_max", R"({"pdelay_req_interval_ms": 60001})"},
    {"pdelay_warmup_negative", R"({"pdelay_warmup_ms": -1})"},
    {"pdelay_warmup_above_max", R"({"pdelay_warmup_ms": 60001})"},
    {"sync_timeout_below_min", R"({"sync_timeout_ms": 9})"},
    {"sync_timeout_above_max", R"({"sync_timeout_ms": 60001})"},
    {"jump_threshold_negative", R"({"jump_future_threshold_ns": -1})"},
    {"step_threshold_negative", R"({"phc": {"step_threshold_ns": -1}})"},
    {"bool_for_integer", R"({"domain_number": true})"},
    {"bool_false_for_integer", R"({"sync_timeout_ms": false})"},
    {"bool_for_nested_integer", R"({"phc": {"step_threshold_ns": true}})"},
    {"string_for_integer", R"({"domain_number": "5"})"},
    {"fractional_for_integer", R"({"domain_number": 1.5})"},
    {"integer_for_string", R"({"iface_name": 5})"},
    {"integer_for_bool", R"({"phc": {"enabled": 1}})"},
    {"string_for_bool", R"({"qnx": {"see_sent": "true"}})"},
    {"phc_not_object", R"({"phc": 1})"},
    {"qnx_not_object", R"({"qnx": 1})"},
    {"root_not_object", R"([])"},
};

INSTANTIATE_TEST_SUITE_P(Schema, ConfigParserInvalidTest, ValuesIn(kInvalidCases), [](const auto& info) {
    return std::string{info.param.name};
});

TEST(ConfigParserTest, AcceptsBoundaryValues)
{
    const auto lo = ParseConfig(WriteTempFile("bounds_lo.json",
                                              R"({"domain_number": 0, "pdelay_req_interval_ms": 10,
                                                  "pdelay_warmup_ms": 0, "sync_timeout_ms": 10,
                                                  "jump_future_threshold_ns": 0,
                                                  "phc": {"step_threshold_ns": 0}})"));
    EXPECT_EQ(lo.engine_opts.domain_number, 0);
    EXPECT_EQ(lo.engine_opts.pdelay_req_interval_ms, 10);
    EXPECT_EQ(lo.engine_opts.pdelay_warmup_ms, 0);
    EXPECT_EQ(lo.engine_opts.sync_timeout_ms, 10);
    EXPECT_EQ(lo.engine_opts.jump_future_threshold_ns, 0);

    const auto hi = ParseConfig(WriteTempFile("bounds_hi.json",
                                              R"({"domain_number": 127, "pdelay_req_interval_ms": 60000,
                                                  "pdelay_warmup_ms": 60000, "sync_timeout_ms": 60000})"));
    EXPECT_EQ(hi.engine_opts.domain_number, 127);
    EXPECT_EQ(hi.engine_opts.pdelay_req_interval_ms, 60000);
    EXPECT_EQ(hi.engine_opts.pdelay_warmup_ms, 60000);
    EXPECT_EQ(hi.engine_opts.sync_timeout_ms, 60000);
}

TEST(ConfigParserTest, MissingFileTerminates)
{
    EXPECT_DEATH(ParseConfig(testing::TempDir() + "does_not_exist.json"), "");
}

}  // namespace
}  // namespace ts
}  // namespace score
