#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace tae::io {

inline constexpr std::size_t HEADER_SIZE = 64;
inline constexpr std::uint16_t FORMAT_VERSION = 1;
inline constexpr std::uint32_t CHANNEL_COUNT = 6;
inline constexpr std::uint32_t SAMPLE_PERIOD_MS = 30000;
inline constexpr std::uint32_t FRAME_SIZE = 28;

class TelemetryFormatError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct TelemetryHeader {
    std::int64_t start_us;
    std::uint64_t frame_count;
    std::int64_t validation_start_us;
    std::int64_t test_start_us;
};

TelemetryHeader decode_header(
    const std::array<std::byte, HEADER_SIZE>& bytes
);

}
