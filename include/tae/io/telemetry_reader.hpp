#pragma once

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>

#include "tae/io/telemetry_frame.hpp"
#include "tae/io/telemetry_header.hpp"

namespace tae::io {

class TelemetryReader {
public:
    explicit TelemetryReader(const std::filesystem::path& path);

    TelemetryReader(const TelemetryReader&) = delete;
    TelemetryReader& operator=(const TelemetryReader&) = delete;

    std::optional<TelemetryFrame> next();

    const TelemetryHeader& header() const noexcept;
    std::uint64_t frames_read() const noexcept;
    std::uint64_t remaining() const noexcept;

private:
    std::ifstream stream_;
    TelemetryHeader header_{};
    FrameValidator validator_;
    std::uint64_t frames_read_ = 0;
    bool failed_ = false;
};

}
