#include "tae/io/telemetry_reader.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <ios>
#include <stdexcept>

namespace tae::io {

namespace {

template <std::size_t N>
void read_exact(
    std::ifstream& stream,
    std::array<std::byte, N>& buffer
) {
    stream.read(
        reinterpret_cast<char*>(buffer.data()),
        static_cast<std::streamsize>(buffer.size())
    );

    if (!stream) {
        throw TelemetryFormatError(
            "Unexpected end of telemetry file or read failure"
        );
    }
}

}

TelemetryReader::TelemetryReader(
    const std::filesystem::path& path
) {
    std::error_code ec;
    const auto physical_size = std::filesystem::file_size(path, ec);

    if (ec) {
        throw std::runtime_error(
            "Cannot determine telemetry file size: " + ec.message()
        );
    }

    if (physical_size < HEADER_SIZE) {
        throw TelemetryFormatError("Truncated telemetry header");
    }

    stream_.open(path, std::ios::binary);

    if (!stream_) {
        throw std::runtime_error("Cannot open telemetry file");
    }

    std::array<std::byte, HEADER_SIZE> header_bytes{};
    read_exact(stream_, header_bytes);

    header_ = decode_header(header_bytes);

    const std::uint64_t expected_size =
        static_cast<std::uint64_t>(HEADER_SIZE) +
        header_.frame_count *
            static_cast<std::uint64_t>(FRAME_SIZE);

    if (physical_size != expected_size) {
        throw TelemetryFormatError(
            "Telemetry file size does not match declared frame count"
        );
    }
}

std::optional<TelemetryFrame> TelemetryReader::next() {
    if (failed_) {
        throw TelemetryFormatError(
            "Reader is unusable after a previous read failure"
        );
    }

    if (frames_read_ == header_.frame_count) {
        return std::nullopt;
    }

    try {
        FrameBytes bytes{};
        read_exact(stream_, bytes);

        TelemetryFrame frame = decode_frame(bytes);
        validator_.validate(frame);

        ++frames_read_;
        return frame;
    } catch (...) {
        failed_ = true;
        throw;
    }
}

const TelemetryHeader& TelemetryReader::header() const noexcept {
    return header_;
}

std::uint64_t TelemetryReader::frames_read() const noexcept {
    return frames_read_;
}

std::uint64_t TelemetryReader::remaining() const noexcept {
    return header_.frame_count - frames_read_;
}

}
