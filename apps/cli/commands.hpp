#pragma once

#include "tae/io/telemetry_reader.hpp"
#include <filesystem>
#include <string>

namespace tae::cli {
void verify(const std::filesystem::path &telemetry);
void score(const std::filesystem::path &telemetry, const std::filesystem::path &training_mask,
           const std::filesystem::path &scores, const std::filesystem::path &metadata,
           const std::string &window, const std::string &alpha,
           io::HeaderPolicy policy = io::HeaderPolicy::Production, bool include_pca = false);
} // namespace tae::cli
