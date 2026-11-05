#include <gtest/gtest.h>

#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "tae/io/telemetry_reader.hpp"

namespace {

using tae::io::TelemetryFormatError;
using tae::io::TelemetryReader;

using Bytes = std::vector<std::byte>;

void write_le(
    Bytes& bytes,
    std::size_t offset,
    std::uint64_t value,
    std::size_t count
) {
    for (std::size_t i = 0; i < count; ++i) {
        bytes[offset + i] = static_cast<std::byte>(
            (value >> (8 * i)) & 0xFFU
        );
    }
}

Bytes make_header(std::uint64_t count) {
    Bytes bytes(64);

    bytes[0] = std::byte{'T'};
    bytes[1] = std::byte{'A'};
    bytes[2] = std::byte{'E'};
    bytes[3] = std::byte{'1'};

    write_le(bytes, 4, 1, 2);
    write_le(bytes, 6, 64, 2);
    write_le(bytes, 8, 6, 4);
    write_le(bytes, 12, 30000, 4);
    write_le(bytes, 16, 0, 8);
    write_le(bytes, 24, count, 8);
    write_le(bytes, 32, 30000000, 8);
    write_le(bytes, 40, 60000000, 8);
    write_le(bytes, 48, 28, 4);

    return bytes;
}

Bytes make_frame(
    float value,
    std::uint8_t observed,
    std::uint8_t usable,
    std::uint16_t staleness
) {
    Bytes bytes(28);

    for (std::size_t i = 0; i < 6; ++i) {
        write_le(
            bytes,
            i * 4,
            std::bit_cast<std::uint32_t>(value),
            4
        );
    }

    bytes[24] = static_cast<std::byte>(observed);
    bytes[25] = static_cast<std::byte>(usable);
    write_le(bytes, 26, staleness, 2);

    return bytes;
}

Bytes make_valid_file() {
    Bytes bytes = make_header(4);

    const std::array<Bytes, 4> frames{
        make_frame(1.0f, 0x3F, 0x3F, 0),
        make_frame(1.0f, 0x00, 0x3F, 1),
        make_frame(1.0f, 0x00, 0x3F, 2),
        make_frame(2.0f, 0x3F, 0x3F, 0)
    };

    for (const auto& frame : frames) {
        bytes.insert(bytes.end(), frame.begin(), frame.end());
    }

    return bytes;
}

class TemporaryBinaryFile {
public:
    explicit TemporaryBinaryFile(const Bytes& bytes) {
        static std::atomic<std::uint64_t> counter{0};

        const auto tick =
            std::chrono::steady_clock::now()
                .time_since_epoch().count();

        path_ = std::filesystem::temp_directory_path() /
            ("tae_reader_" + std::to_string(tick) + "_" +
             std::to_string(counter.fetch_add(1)) + ".bin");

        std::ofstream stream(path_, std::ios::binary | std::ios::trunc);

        if (!stream) {
            throw std::runtime_error("Cannot create test file");
        }

        stream.write(
            reinterpret_cast<const char*>(bytes.data()),
            static_cast<std::streamsize>(bytes.size())
        );

        if (!stream) {
            throw std::runtime_error("Cannot write test file");
        }
    }

    ~TemporaryBinaryFile() {
        std::error_code ec;
        std::filesystem::remove(path_, ec);
    }

    const std::filesystem::path& path() const {
        return path_;
    }

private:
    std::filesystem::path path_;
};

}

TEST(TelemetryReader, ReadsValidFile) {
    TemporaryBinaryFile file(make_valid_file());
    TelemetryReader reader(file.path());

    EXPECT_EQ(reader.header().frame_count, 4U);
    EXPECT_EQ(reader.frames_read(), 0U);
    EXPECT_EQ(reader.remaining(), 4U);

    for (std::uint64_t i = 0; i < 4; ++i) {
        const auto frame = reader.next();

        ASSERT_TRUE(frame.has_value());
        EXPECT_EQ(reader.frames_read(), i + 1);
        EXPECT_EQ(reader.remaining(), 3U - i);
    }
}

TEST(TelemetryReader, ReturnsCleanEndOfStream) {
    TemporaryBinaryFile file(make_valid_file());
    TelemetryReader reader(file.path());

    for (int i = 0; i < 4; ++i) {
        ASSERT_TRUE(reader.next().has_value());
    }

    EXPECT_FALSE(reader.next().has_value());
    EXPECT_FALSE(reader.next().has_value());
    EXPECT_EQ(reader.remaining(), 0U);
}

TEST(TelemetryReader, PreservesFrameValues) {
    TemporaryBinaryFile file(make_valid_file());
    TelemetryReader reader(file.path());

    auto first = reader.next();
    ASSERT_TRUE(first.has_value());
    EXPECT_FLOAT_EQ(first->values[0], 1.0f);
    EXPECT_EQ(first->observed_mask, 0x3F);

    reader.next();
    reader.next();

    auto last = reader.next();
    ASSERT_TRUE(last.has_value());
    EXPECT_FLOAT_EQ(last->values[0], 2.0f);
    EXPECT_EQ(last->staleness, 0);
}

TEST(TelemetryReader, RejectsTruncatedHeader) {
    TemporaryBinaryFile file(Bytes(32));

    EXPECT_THROW(
        TelemetryReader reader(file.path()),
        TelemetryFormatError
    );
}

TEST(TelemetryReader, RejectsTruncatedPayload) {
    auto bytes = make_valid_file();
    bytes.resize(bytes.size() - 1);

    TemporaryBinaryFile file(bytes);

    EXPECT_THROW(
        TelemetryReader reader(file.path()),
        TelemetryFormatError
    );
}

TEST(TelemetryReader, RejectsTrailingPayload) {
    auto bytes = make_valid_file();
    bytes.push_back(std::byte{0});

    TemporaryBinaryFile file(bytes);

    EXPECT_THROW(
        TelemetryReader reader(file.path()),
        TelemetryFormatError
    );
}

TEST(TelemetryReader, RejectsInvalidHeader) {
    auto bytes = make_valid_file();
    bytes[0] = std::byte{'X'};

    TemporaryBinaryFile file(bytes);

    EXPECT_THROW(
        TelemetryReader reader(file.path()),
        TelemetryFormatError
    );
}

TEST(TelemetryReader, RejectsCorruptFrame) {
    auto bytes = make_valid_file();
    bytes[64 + 24] = std::byte{0x01};

    TemporaryBinaryFile file(bytes);
    TelemetryReader reader(file.path());

    EXPECT_THROW(reader.next(), TelemetryFormatError);
    EXPECT_EQ(reader.frames_read(), 0U);
}

TEST(TelemetryReader, RejectsInvalidTransition) {
    auto bytes = make_valid_file();
    bytes[64 + 28 + 26] = std::byte{0x03};

    TemporaryBinaryFile file(bytes);
    TelemetryReader reader(file.path());

    ASSERT_TRUE(reader.next().has_value());

    EXPECT_THROW(reader.next(), TelemetryFormatError);
    EXPECT_EQ(reader.frames_read(), 1U);
}

TEST(TelemetryReader, CannotContinueAfterFailure) {
    auto bytes = make_valid_file();
    bytes[64 + 28 + 26] = std::byte{0x03};

    TemporaryBinaryFile file(bytes);
    TelemetryReader reader(file.path());

    ASSERT_TRUE(reader.next().has_value());
    EXPECT_THROW(reader.next(), TelemetryFormatError);
    EXPECT_THROW(reader.next(), TelemetryFormatError);
}

TEST(TelemetryReader, RejectsMissingFile) {
    const auto path =
        std::filesystem::temp_directory_path() /
        "tae_nonexistent_reader_test_file.bin";

    std::error_code ec;
    std::filesystem::remove(path, ec);

    EXPECT_THROW(
        TelemetryReader reader(path),
        std::runtime_error
    );
}