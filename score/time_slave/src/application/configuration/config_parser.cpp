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

#include "score/time_slave/src/application/configuration/config_limits.h"

#include "score/json/json_parser.h"
#include "score/mw/log/logging.h"
#include "score/time_slave/src/common/logging_contexts.h"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace score
{
namespace ts
{

namespace
{

using score::json::Error;
using score::json::GetAttribute;
using score::json::MakeError;
using score::json::Object;

/// Log a fatal configuration error and terminate the process.
///
/// LogFatal() alone only logs; an invalid configuration must never be applied,
/// so terminate explicitly.
[[noreturn]] void FatalConfigError(std::string_view key, std::string_view reason)
{
    score::mw::log::LogFatal(kTimeSlaveAppContext) << "Config field '" << key << "' " << reason;
    std::abort();
}

/// Fatal out if @p result is a type/parse error (as opposed to the caller having
/// already detected "key not present" via Object::find()).
template <typename ResultT>
void FatalOnTypeError(const ResultT& result, std::string_view key)
{
    if (!result.has_value() && result.error() != MakeError(Error::kKeyNotFound))
    {
        FatalConfigError(key, std::string{"has wrong type: "} + std::string{result.error().Message()});
    }
}

/// Reads the properties of one JSON object, driven by the schema-generated key table.
///
/// Every property is parsed through the generated constants (key, range, default), and
/// Finish() enforces the schema both ways: keys in the file that the schema does not
/// declare are rejected ("additionalProperties": false), and schema properties this
/// parser never read are reported, so a schema change cannot be silently ignored.
class ObjectReader
{
  public:
    template <std::size_t N>
    ObjectReader(const Object& obj, std::string_view scope, const std::string_view (&schema_keys)[N])
        : obj_{obj}, scope_{scope}, schema_keys_{schema_keys}, schema_key_count_{N}
    {
    }

    /// Read a string property; leaves @p out unchanged if key is missing.
    void String(const config_schema::StringProperty& prop, std::string& out)
    {
        Mark(prop.key);
        const auto result = GetAttribute<std::string_view>(std::cref(obj_), prop.key);
        FatalOnTypeError(result, prop.key);
        if (result.has_value())
        {
            out = std::string{result.value()};
        }
    }

    /// Read an integer property and validate it against the schema range; leaves @p out
    /// unchanged if key is missing. Terminates on wrong type (including JSON booleans) or
    /// out-of-range values.
    template <typename T>
    void Int(const config_schema::IntProperty& prop, T& out)
    {
        Mark(prop.key);
        // Any::As<arithmetic>() silently converts JSON booleans; the schema demands "integer",
        // so require the stored value to be a genuine JSON number first.
        const auto it = obj_.find(prop.key);
        if (it != obj_.end() && !it->second.As<score::json::Number>().has_value())
        {
            FatalConfigError(prop.key, "has wrong type: expected integer");
        }
        const auto result = GetAttribute<std::int64_t>(std::cref(obj_), prop.key);
        FatalOnTypeError(result, prop.key);
        if (result.has_value())
        {
            const std::int64_t value = result.value();
            if (value < prop.min || value > prop.max)
            {
                FatalConfigError(prop.key,
                                 "is out of range: " + std::to_string(value) + " not in [" +
                                     std::to_string(prop.min) + ", " + std::to_string(prop.max) + "]");
            }
            out = static_cast<T>(value);
        }
    }

    /// Read a bool property; leaves @p out unchanged if key is missing.
    void Bool(const config_schema::BoolProperty& prop, bool& out)
    {
        Mark(prop.key);
        // Any::As<bool>() silently converts JSON numbers; require a genuine JSON boolean.
        const auto it = obj_.find(prop.key);
        if (it != obj_.end() && it->second.As<score::json::Number>().has_value())
        {
            FatalConfigError(prop.key, "has wrong type: expected boolean");
        }
        const auto result = GetAttribute<bool>(std::cref(obj_), prop.key);
        FatalOnTypeError(result, prop.key);
        if (result.has_value())
        {
            out = result.value();
        }
    }

    /// Read a nested object property. Returns nullptr if the key is missing.
    const Object* NestedObject(std::string_view key)
    {
        Mark(key);
        const auto result = GetAttribute<Object>(std::cref(obj_), key);
        if (!result.has_value())
        {
            if (result.error() != MakeError(Error::kKeyNotFound))
            {
                FatalConfigError(key, std::string{"is not an object: "} + std::string{result.error().Message()});
            }
            return nullptr;
        }
        return &result.value().get();
    }

    /// Must be called after all properties were read.
    void Finish() const
    {
        for (const auto& entry : obj_)
        {
            const auto key = entry.first.GetAsStringView();
            if (std::find(schema_keys_, schema_keys_ + schema_key_count_, key) == schema_keys_ + schema_key_count_)
            {
                FatalConfigError(Qualified(key), "is not defined by the configuration schema");
            }
        }
        for (const auto* it = schema_keys_; it != schema_keys_ + schema_key_count_; ++it)
        {
            const auto key = *it;
            if (std::find(read_.begin(), read_.end(), key) == read_.end())
            {
                FatalConfigError(Qualified(key), "is defined by the schema but not handled by the parser");
            }
        }
    }

  private:
    void Mark(std::string_view key)
    {
        read_.push_back(key);
    }

    std::string Qualified(std::string_view key) const
    {
        return scope_.empty() ? std::string{key} : std::string{scope_} + "." + std::string{key};
    }

    const Object& obj_;
    std::string_view scope_;
    const std::string_view* schema_keys_;
    std::size_t schema_key_count_;
    std::vector<std::string_view> read_;
};

/// Parse the optional "phc" nested object. If absent, @p cfg keeps defaults.
void ParsePhcConfig(ObjectReader& root, details::PhcConfig& cfg)
{
    const Object* phc_obj = root.NestedObject("phc");
    if (phc_obj == nullptr)
    {
        return;
    }
    ObjectReader reader{*phc_obj, "phc", config_schema::kPhcKeys};
    reader.Bool(config_schema::kPhcEnabled, cfg.enabled);
    reader.String(config_schema::kPhcDevice, cfg.device);
    reader.Int(config_schema::kPhcStepThresholdNs, cfg.step_threshold_ns);
    reader.Finish();
}

/// Parse the optional "qnx" nested object. If absent, @p qnx keeps defaults.
void ParseQnxConfig(ObjectReader& root, TimeSlaveConfig::QnxSettings& qnx)
{
    const Object* qnx_obj = root.NestedObject("qnx");
    if (qnx_obj == nullptr)
    {
        return;
    }
    ObjectReader reader{*qnx_obj, "qnx", config_schema::kQnxKeys};
    reader.String(config_schema::kQnxBpfDevicePath, qnx.bpf_device_path);
    reader.Bool(config_schema::kQnxSeeSent, qnx.see_sent);
    reader.Finish();
}

}  // namespace

TimeSlaveConfig ParseConfig(const std::string& path)
{
    const score::json::JsonParser parser;
    auto root_result = parser.FromFile(path);
    if (!root_result.has_value())
    {
        score::mw::log::LogFatal(kTimeSlaveAppContext)
            << "Failed to parse config file '" << path << "': " << root_result.error().Message();
        std::abort();
    }

    auto obj_result = root_result.value().As<Object>();
    if (!obj_result.has_value())
    {
        score::mw::log::LogFatal(kTimeSlaveAppContext) << "Config file '" << path << "' root is not a JSON object";
        std::abort();
    }
    const auto& obj = obj_result.value().get();

    TimeSlaveConfig cfg;
    auto& opts = cfg.engine_opts;

    ObjectReader reader{obj, "", config_schema::kRootKeys};
    reader.String(config_schema::kIfaceName, opts.iface_name);
    reader.Int(config_schema::kDomainNumber, opts.domain_number);
    reader.Int(config_schema::kPdelayReqIntervalMs, opts.pdelay_req_interval_ms);
    reader.Int(config_schema::kPdelayWarmupMs, opts.pdelay_warmup_ms);
    reader.Int(config_schema::kSyncTimeoutMs, opts.sync_timeout_ms);
    reader.Int(config_schema::kJumpFutureThresholdNs, opts.jump_future_threshold_ns);
    reader.String(config_schema::kShmPath, cfg.shm_path);

    ParsePhcConfig(reader, opts.phc_config);
    ParseQnxConfig(reader, cfg.qnx);
    reader.Finish();

    return cfg;
}

}  // namespace ts
}  // namespace score
