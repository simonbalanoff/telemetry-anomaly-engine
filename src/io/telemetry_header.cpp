#include "tae/io/telemetry_header.hpp"

#include <bit>
#include <cstdint>
#include <limits>

namespace tae::io {

namespace {

std::uint64_t read_le(
    const std::array<std::byte, HEADER_SIZE>& bytes,
    std::size_t offset,
    std::size_t count
) {
    std::uint64_t result = 0;

    for (std::size_t i = 0; i < count; ++i) {
        result |= std::uint64_t{
            std::to_integer<std::uint8_t>(bytes[offset + i])
        } << (8 * i);
    }

    return result;
}

void require(bool condition, const char* message) {
    if (!condition) {
        throw TelemetryFormatError(message);
    }
}

}

TelemetryHeader decode_header(
    const std::array<std::byte, HEADER_SIZE>& bytes
) {
    require(
        bytes[0] == std::byte{'T'} &&
        bytes[1] == std::byte{'A'} &&
        bytes[2] == std::byte{'E'} &&
        bytes[3] == std::byte{'1'},
        "Invalid telemetry magic"
    );

    require(read_le(bytes, 4, 2) == FORMAT_VERSION,
            "Unsupported format version");

    require(read_le(bytes, 6, 2) == HEADER_SIZE,
            "Invalid header size");

    require(read_le(bytes, 8, 4) == CHANNEL_COUNT,
            "Unsupported channel count");

    require(read_le(bytes, 12, 4) == SAMPLE_PERIOD_MS,
            "Unsupported sample period");

    require(read_le(bytes, 48, 4) == FRAME_SIZE,
            "Invalid frame size");

    require(read_le(bytes, 52, 4) == 0 &&
            read_le(bytes, 56, 8) == 0,
            "Reserved fields must be zero");

    TelemetryHeader header{
        .start_us = std::bit_cast<std::int64_t>(
            read_le(bytes, 16, 8)
        ),
        .frame_count = read_le(bytes, 24, 8),
        .validation_start_us = std::bit_cast<std::int64_t>(
            read_le(bytes, 32, 8)
        ),
        .test_start_us = std::bit_cast<std::int64_t>(
            read_le(bytes, 40, 8)
        )
    };

    constexpr std::int64_t PERIOD_US = 30'000'000;

    require(header.frame_count > 0,
            "Frame count must be positive");

    require(header.start_us % PERIOD_US == 0,
            "Start timestamp is not grid-aligned");

    require(header.validation_start_us % PERIOD_US == 0 &&
            header.test_start_us % PERIOD_US == 0,
            "Split boundaries must be grid-aligned");

    require(
        header.start_us < header.validation_start_us &&
        header.validation_start_us < header.test_start_us,
        "Invalid split boundary ordering"
    );

    constexpr auto MAX_I64 =
        std::numeric_limits<std::int64_t>::max();

    constexpr auto MAX_U64 =
        std::numeric_limits<std::uint64_t>::max();

    require(
        header.frame_count <=
            (MAX_U64 - HEADER_SIZE) / FRAME_SIZE,
        "Declared payload size overflows"
    );

    require(
        header.frame_count <=
            static_cast<std::uint64_t>(MAX_I64 / PERIOD_US),
        "Frame count exceeds timestamp range"
    );

    const auto duration = static_cast<std::int64_t>(
        header.frame_count * PERIOD_US
    );

    require(
        header.start_us <= MAX_I64 - duration,
        "Final timestamp overflows"
    );

    const auto end_us = header.start_us + duration;

    require(
        header.test_start_us <= end_us,
        "Test boundary falls outside telemetry"
    );

    return header;
}

}
