#include <gtest/gtest.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

#include "tae/io/telemetry_header.hpp"

namespace {

using tae::io::TelemetryFormatError;
using tae::io::TelemetryHeader;

constexpr std::int64_t START_US = 946684800000000LL;
constexpr std::int64_t VAL_US = 1199145600000000LL;
constexpr std::int64_t TEST_US = 1293840000000000LL;
constexpr std::uint64_t FRAME_COUNT = 14728320ULL;

using HeaderBytes = std::array<std::byte, tae::io::HEADER_SIZE>;

void write_le(
    HeaderBytes& bytes,
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

HeaderBytes valid_header() {
    HeaderBytes bytes{};

    bytes[0] = std::byte{'T'};
    bytes[1] = std::byte{'A'};
    bytes[2] = std::byte{'E'};
    bytes[3] = std::byte{'1'};

    write_le(bytes, 4, 1, 2);
    write_le(bytes, 6, 64, 2);
    write_le(bytes, 8, 6, 4);
    write_le(bytes, 12, 30000, 4);
    write_le(bytes, 16, static_cast<std::uint64_t>(START_US), 8);
    write_le(bytes, 24, FRAME_COUNT, 8);
    write_le(bytes, 32, static_cast<std::uint64_t>(VAL_US), 8);
    write_le(bytes, 40, static_cast<std::uint64_t>(TEST_US), 8);
    write_le(bytes, 48, 28, 4);

    return bytes;
}

}

TEST(TelemetryHeader, DecodesValidHeader) {
    const auto bytes = valid_header();

    const TelemetryHeader header = tae::io::decode_header(bytes);

    EXPECT_EQ(header.start_us, START_US);
    EXPECT_EQ(header.frame_count, FRAME_COUNT);
    EXPECT_EQ(header.validation_start_us, VAL_US);
    EXPECT_EQ(header.test_start_us, TEST_US);
}

TEST(TelemetryHeader, RejectsInvalidMagic) {
    auto bytes = valid_header();
    bytes[0] = std::byte{'X'};

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsUnsupportedVersion) {
    auto bytes = valid_header();
    write_le(bytes, 4, 2, 2);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsWrongHeaderSize) {
    auto bytes = valid_header();
    write_le(bytes, 6, 32, 2);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsWrongChannelCount) {
    auto bytes = valid_header();
    write_le(bytes, 8, 5, 4);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsWrongSamplePeriod) {
    auto bytes = valid_header();
    write_le(bytes, 12, 1000, 4);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsWrongFrameSize) {
    auto bytes = valid_header();
    write_le(bytes, 48, 32, 4);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsNonzeroReserved32) {
    auto bytes = valid_header();
    write_le(bytes, 52, 1, 4);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsNonzeroReserved64) {
    auto bytes = valid_header();
    write_le(bytes, 56, 1, 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsZeroFrames) {
    auto bytes = valid_header();
    write_le(bytes, 24, 0, 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsMisalignedStart) {
    auto bytes = valid_header();
    write_le(bytes, 16, static_cast<std::uint64_t>(START_US + 1), 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsMisalignedValidationBoundary) {
    auto bytes = valid_header();
    write_le(bytes, 32, static_cast<std::uint64_t>(VAL_US + 1), 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsMisalignedTestBoundary) {
    auto bytes = valid_header();
    write_le(bytes, 40, static_cast<std::uint64_t>(TEST_US + 1), 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsReversedSplitBoundaries) {
    auto bytes = valid_header();
    write_le(bytes, 32, static_cast<std::uint64_t>(TEST_US), 8);
    write_le(bytes, 40, static_cast<std::uint64_t>(VAL_US), 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsEqualSplitBoundaries) {
    auto bytes = valid_header();
    write_le(bytes, 40, static_cast<std::uint64_t>(VAL_US), 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsPayloadSizeOverflow) {
    auto bytes = valid_header();

    write_le(
        bytes,
        24,
        std::numeric_limits<std::uint64_t>::max(),
        8
    );

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsTimestampRangeOverflow) {
    auto bytes = valid_header();

    const std::uint64_t count =
        static_cast<std::uint64_t>(
            std::numeric_limits<std::int64_t>::max() / 30000000
        ) + 1;

    write_le(bytes, 24, count, 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}

TEST(TelemetryHeader, RejectsTestBoundaryOutsideTimeline) {
    auto bytes = valid_header();
    write_le(bytes, 24, 1, 8);

    EXPECT_THROW(tae::io::decode_header(bytes), TelemetryFormatError);
}
