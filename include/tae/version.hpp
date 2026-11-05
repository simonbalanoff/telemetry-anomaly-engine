#pragma once

#include <string_view>

namespace tae {

// Returns the project version, e.g. "0.1.0".
std::string_view version() noexcept;

} // namespace tae
