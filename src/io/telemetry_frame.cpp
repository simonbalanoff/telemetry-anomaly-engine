#include "tae/io/telemetry_frame.hpp"

#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace tae::io {

namespace {

constexpr std::uint8_t ALL_CHANNELS = 0x3F;
constexpr std::uint16_t MAX_FILL = 5;

std::uint32_t read_u32(
    const FrameBytes& bytes,
    std::size_t offset
) {
    std::uint32_t result = 0;

    for (std::size_t i = 0; i < 4; ++i) {
        result |= static_cast<std::uint32_t>(
            std::to_integer<std::uint8_t>(bytes[offset + i])
        ) << (8 * i);
    }

    return result;
}

std::uint16_t read_u16(
    const FrameBytes& bytes,
    std::size_t offset
) {
    return static_cast<std::uint16_t>(
        std::to_integer<std::uint8_t>(bytes[offset])
        | (static_cast<std::uint16_t>(
            std::to_integer<std::uint8_t>(bytes[offset + 1])
        ) << 8)
    );
}

void require(bool condition, const char* message) {
    if (!condition) {
        throw TelemetryFormatError(message);
    }
}

void validate_values(const TelemetryFrame& frame) {
    if (frame.usable_mask == 0) {
        for (float value : frame.values) {
            require(
                std::bit_cast<std::uint32_t>(value) == 0,
                "Unavailable frame contains nonzero values"
            );
        }

        return;
    }

    for (float value : frame.values) {
        require(
            std::isfinite(value),
            "Usable frame contains nonfinite values"
        );
    }
}

void validate_state(const TelemetryFrame& frame) {
    require(
        frame.observed_mask == 0 ||
        frame.observed_mask == ALL_CHANNELS,
        "Invalid observed mask"
    );

    require(
        frame.usable_mask == 0 ||
        frame.usable_mask == ALL_CHANNELS,
        "Invalid usable mask"
    );

    if (frame.observed_mask == ALL_CHANNELS) {
        require(
            frame.usable_mask == ALL_CHANNELS &&
            frame.staleness == 0,
            "Invalid observed frame state"
        );
    } else if (frame.usable_mask == ALL_CHANNELS) {
        require(
            frame.staleness >= 1 &&
            frame.staleness <= MAX_FILL,
            "Invalid forward-filled frame state"
        );
    } else {
        require(
            frame.staleness > MAX_FILL,
            "Invalid unavailable frame state"
        );
    }
}

bool equal_bits(
    const std::array<float, CHANNEL_COUNT>& left,
    const std::array<float, CHANNEL_COUNT>& right
) {
    for (std::size_t i = 0; i < CHANNEL_COUNT; ++i) {
        if (std::bit_cast<std::uint32_t>(left[i]) !=
            std::bit_cast<std::uint32_t>(right[i])) {
            return false;
        }
    }

    return true;
}

}

TelemetryFrame decode_frame(const FrameBytes& bytes) {
    TelemetryFrame frame{};

    for (std::size_t i = 0; i < CHANNEL_COUNT; ++i) {
        const std::uint32_t bits = read_u32(bytes, i * 4);
        frame.values[i] = std::bit_cast<float>(bits);
    }

    frame.observed_mask =
        std::to_integer<std::uint8_t>(bytes[24]);

    frame.usable_mask =
        std::to_integer<std::uint8_t>(bytes[25]);

    frame.staleness = read_u16(bytes, 26);

    validate_state(frame);
    validate_values(frame);

    return frame;
}

void FrameValidator::validate(const TelemetryFrame& frame) {
    validate_state(frame);
    validate_values(frame);

    if (!has_observation_) {
        require(
            frame.observed_mask == ALL_CHANNELS,
            "First frame must be observed"
        );

        last_observed_ = frame.values;
        previous_staleness_ = 0;
        has_observation_ = true;
        return;
    }

    if (frame.observed_mask == ALL_CHANNELS) {
        last_observed_ = frame.values;
        previous_staleness_ = 0;
        return;
    }

    const std::uint16_t expected =
        previous_staleness_ ==
            std::numeric_limits<std::uint16_t>::max()
        ? previous_staleness_
        : static_cast<std::uint16_t>(
            previous_staleness_ + 1
        );

    require(
        frame.staleness == expected,
        "Invalid staleness transition"
    );

    if (frame.usable_mask == ALL_CHANNELS) {
        require(
            equal_bits(frame.values, last_observed_),
            "Forward-filled values differ from last observation"
        );
    }

    previous_staleness_ = frame.staleness;
}

void FrameValidator::reset() noexcept {
    last_observed_.fill(0.0f);
    previous_staleness_ = 0;
    has_observation_ = false;
}

}
