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

// Build-time tool: reads time_slave_config_schema.json and emits a C++ header with the
// keys, ranges and defaults of every property, so that the parser cannot drift from the
// schema. Usage: gen_config_limits <schema.json>   (header is written to stdout)

#include "score/json/json_parser.h"

#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace
{

using score::json::GetAttribute;
using score::json::Object;

[[noreturn]] void Die(const std::string& msg)
{
    std::cerr << "gen_config_limits: " << msg << std::endl;
    std::exit(1);
}

std::string Escape(std::string_view in)
{
    std::string out;
    for (const char c : in)
    {
        if (c == '\\' || c == '"')
        {
            out += '\\';
        }
        out += c;
    }
    return out;
}

/// "phc.step_threshold_ns" -> "PhcStepThresholdNs"
std::string ToCamel(const std::string& path)
{
    std::string out;
    bool upper = true;
    for (const char c : path)
    {
        if (c == '_' || c == '.')
        {
            upper = true;
        }
        else
        {
            out += upper ? static_cast<char>(std::toupper(static_cast<unsigned char>(c))) : c;
            upper = false;
        }
    }
    return out;
}

std::string_view Str(const Object& o, std::string_view key)
{
    const auto r = GetAttribute<std::string_view>(std::cref(o), key);
    return r.has_value() ? r.value() : std::string_view{};
}

bool Has(const Object& o, std::string_view key)
{
    return o.find(key) != o.end();
}

std::int64_t Int(const Object& o, std::string_view key)
{
    const auto r = GetAttribute<std::int64_t>(std::cref(o), key);
    if (!r.has_value())
    {
        Die("property attribute '" + std::string{key} + "' is not an integer");
    }
    return r.value();
}

/// Emit constants for all properties of @p schema_obj (an object schema); returns the
/// declarations for nested objects through @p nested.
void Emit(const Object& schema_obj,
          const std::string& scope,  // "" for root, else e.g. "phc"
          std::ostringstream& out,
          std::vector<std::pair<std::string, const Object*>>& nested_out,
          std::string& keys_out)
{
    const auto props = GetAttribute<Object>(std::cref(schema_obj), "properties");
    if (!props.has_value())
    {
        Die("object schema '" + scope + "' has no 'properties'");
    }
    for (const auto& [key_sv, any] : props.value().get())
    {
        const std::string key{key_sv.GetAsStringView()};
        const std::string path = scope.empty() ? key : scope + "." + key;
        const auto prop_result = any.As<Object>();
        if (!prop_result.has_value())
        {
            Die("property '" + path + "' is not an object");
        }
        const Object& prop = prop_result.value().get();
        const std::string type{Str(prop, "type")};
        const std::string name = "k" + ToCamel(path);
        keys_out += "    \"" + Escape(key) + "\",\n";

        if (type == "integer")
        {
            if (!Has(prop, "default"))
            {
                Die("integer property '" + path + "' has no 'default'");
            }
            const std::string min = Has(prop, "minimum") ? std::to_string(Int(prop, "minimum"))
                                                          : "std::numeric_limits<std::int64_t>::min()";
            const std::string max = Has(prop, "maximum") ? std::to_string(Int(prop, "maximum"))
                                                          : "std::numeric_limits<std::int64_t>::max()";
            out << "inline constexpr IntProperty " << name << "{\"" << Escape(key) << "\", " << min << ", " << max
                << ", " << Int(prop, "default") << "};\n";
        }
        else if (type == "boolean")
        {
            const auto d = GetAttribute<bool>(std::cref(prop), "default");
            if (!d.has_value())
            {
                Die("boolean property '" + path + "' has no 'default'");
            }
            out << "inline constexpr BoolProperty " << name << "{\"" << Escape(key) << "\", "
                << (d.value() ? "true" : "false") << "};\n";
        }
        else if (type == "string")
        {
            if (!Has(prop, "default"))
            {
                Die("string property '" + path + "' has no 'default'");
            }
            out << "inline constexpr StringProperty " << name << "{\"" << Escape(key) << "\", \""
                << Escape(Str(prop, "default")) << "\"};\n";
        }
        else if (type == "object")
        {
            nested_out.emplace_back(path, &prop);
        }
        else
        {
            Die("property '" + path + "' has unsupported type '" + type + "'");
        }
    }
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 2)
    {
        Die("usage: gen_config_limits <schema.json>");
    }
    const score::json::JsonParser parser;
    auto root = parser.FromFile(argv[1]);
    if (!root.has_value())
    {
        Die(std::string{"cannot parse schema: "} + std::string{root.error().Message()});
    }
    const auto root_obj = root.value().As<Object>();
    if (!root_obj.has_value())
    {
        Die("schema root is not an object");
    }

    std::ostringstream out;
    out << "// GENERATED from " << std::filesystem::path{argv[1]}.filename().string()
        << " by gen_config_limits. DO NOT EDIT.\n"
           "#ifndef SCORE_TIME_SLAVE_CONFIGURATION_CONFIG_LIMITS_H\n"
           "#define SCORE_TIME_SLAVE_CONFIGURATION_CONFIG_LIMITS_H\n\n"
           "#include <cstddef>\n#include <cstdint>\n#include <limits>\n#include <string_view>\n\n"
           "namespace score\n{\nnamespace ts\n{\nnamespace config_schema\n{\n\n"
           "struct IntProperty\n{\n    std::string_view key;\n    std::int64_t min;\n    std::int64_t max;\n"
           "    std::int64_t default_value;\n};\n"
           "struct BoolProperty\n{\n    std::string_view key;\n    bool default_value;\n};\n"
           "struct StringProperty\n{\n    std::string_view key;\n    std::string_view default_value;\n};\n\n";

    // Breadth-first over object schemas: root, then nested objects.
    std::vector<std::pair<std::string, const Object*>> queue{{"", &root_obj.value().get()}};
    for (std::size_t i = 0; i < queue.size(); ++i)
    {
        const std::string scope = queue[i].first;
        std::vector<std::pair<std::string, const Object*>> nested;
        std::string keys;
        Emit(*queue[i].second, scope, out, nested, keys);
        const std::string prefix = scope.empty() ? "Root" : ToCamel(scope);
        out << "inline constexpr std::string_view k" << prefix << "Keys[] = {\n" << keys << "};\n";
        out << "\n";
        queue.insert(queue.end(), nested.begin(), nested.end());
    }
    out << "}  // namespace config_schema\n}  // namespace ts\n}  // namespace score\n\n#endif\n";
    std::cout << out.str();
    return 0;
}
