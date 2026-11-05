#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "tae/io/telemetry_header.hpp"

namespace tae::io {

using FrameBytes = std::array<std::byte, FRAME_SIZE>;

struct TelemetryFrame {
    std::array<float, CHANNEL_COUNT> values;
    std::uint8_t observed_mask;
    std::uint8_t usable_mask;
    std::uint16_t staleness;
};

TelemetryFrame decode_frame(const FrameBytes& bytes);

class FrameValidator {
public:
    void validate(const TelemetryFrame& frame);
    void reset() noexcept;

private:
    std::array<float, CHANNEL_COUNT> last_observed_{};
    std::uint16_t previous_staleness_ = 0;
    bool has_observation_ = false;
};

}
