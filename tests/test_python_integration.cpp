#include <gtest/gtest.h>

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <vector>

#include "tae/io/telemetry_reader.hpp"

namespace {

constexpr std::uint8_t ALL = 0x3F;

constexpr std::array<float, 6> INITIAL{
    0.5f, 0.25f, 0.0f, -0.5f, 1.0f, 0.75f
};

constexpr std::array<float, 6> RESUMED{
    1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f
};

constexpr std::array<float, 6> ZERO{};

struct ExpectedFrame {
    std::array<float, 6> values;
    std::uint8_t observed;
    std::uint8_t usable;
    std::uint16_t staleness;
};

const std::array<ExpectedFrame, 12> EXPECTED{{
    {INITIAL, ALL, ALL, 0},
    {INITIAL, ALL, ALL, 0},
    {INITIAL, 0, ALL, 1},
    {INITIAL, 0, ALL, 2},
    {INITIAL, 0, ALL, 3},
    {INITIAL, 0, ALL, 4},
    {INITIAL, 0, ALL, 5},
    {ZERO, 0, 0, 6},
    {ZERO, 0, 0, 7},
    {RESUMED, ALL, ALL, 0},
    {RESUMED, ALL, ALL, 0},
    {RESUMED, ALL, ALL, 0}
}};

std::filesystem::path fixture_path() {
    return std::filesystem::path(TAE_FIXTURE_PATH);
}

std::vector<char> read_bytes(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);

    if (!stream) {
        throw std::runtime_error("Cannot open test fixture");
    }

    return {
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()
    };
}

class TemporaryCorruptFile {
public:
    TemporaryCorruptFile(
        const std::filesystem::path& source,
        const std::filesystem::path& destination,
        std::size_t offset
    ) : path_(destination) {
        auto bytes = read_bytes(source);

        if (offset >= bytes.size()) {
            throw std::runtime_error("Invalid corruption offset");
        }

        bytes[offset] = static_cast<char>(
            static_cast<unsigned char>(bytes[offset]) ^ 0xFFU
        );

        std::ofstream stream(
            path_,
            std::ios::binary | std::ios::trunc
        );

        if (!stream) {
            throw std::runtime_error("Cannot create corrupted fixture");
        }

        stream.write(
            bytes.data(),
            static_cast<std::streamsize>(bytes.size())
        );

        if (!stream) {
            throw std::runtime_error("Cannot write corrupted fixture");
        }
    }

    ~TemporaryCorruptFile() {
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

TEST(PythonIntegration, HeaderMatchesExpectedValues) {
    tae::io::TelemetryReader reader(fixture_path());

    EXPECT_EQ(reader.header().start_us, 0);
    EXPECT_EQ(reader.header().frame_count, 12U);
    EXPECT_EQ(reader.header().validation_start_us, 30'000'000);
    EXPECT_EQ(reader.header().test_start_us, 60'000'000);
    EXPECT_EQ(reader.frames_read(), 0U);
    EXPECT_EQ(reader.remaining(), 12U);

    EXPECT_EQ(std::filesystem::file_size(fixture_path()), 400U);
}

TEST(PythonIntegration, AllFramesMatchExactly) {
    tae::io::TelemetryReader reader(fixture_path());

    for (std::size_t i = 0; i < EXPECTED.size(); ++i) {
        SCOPED_TRACE(i);

        const auto frame = reader.next();
        ASSERT_TRUE(frame.has_value());

        const auto& expected = EXPECTED[i];

        EXPECT_EQ(frame->observed_mask, expected.observed);
        EXPECT_EQ(frame->usable_mask, expected.usable);
        EXPECT_EQ(frame->staleness, expected.staleness);

        for (std::size_t ch = 0; ch < expected.values.size(); ++ch) {
            EXPECT_EQ(
                std::bit_cast<std::uint32_t>(frame->values[ch]),
                std::bit_cast<std::uint32_t>(expected.values[ch])
            );
        }

        EXPECT_EQ(reader.frames_read(), i + 1);
        EXPECT_EQ(reader.remaining(), EXPECTED.size() - i - 1);
    }

    EXPECT_FALSE(reader.next().has_value());
    EXPECT_FALSE(reader.next().has_value());
}

TEST(PythonIntegration, ReconstructedTimestampsAreCorrect) {
    tae::io::TelemetryReader reader(fixture_path());

    constexpr std::int64_t PERIOD_US = 30'000'000;

    for (std::int64_t i = 0; i < 12; ++i) {
        const auto cell_start =
            reader.header().start_us + i * PERIOD_US;

        const auto available = cell_start + PERIOD_US;

        EXPECT_EQ(cell_start, i * PERIOD_US);
        EXPECT_EQ(available, (i + 1) * PERIOD_US);

        ASSERT_TRUE(reader.next().has_value());
    }
}

TEST(PythonIntegration, RejectsCorruptHeader) {
    const auto source = fixture_path();
    TemporaryCorruptFile file(
        source,
        source.string() + ".bad_header",
        0
    );

    EXPECT_THROW(
        tae::io::TelemetryReader reader(file.path()),
        tae::io::TelemetryFormatError
    );
}

TEST(PythonIntegration, RejectsCorruptFrame) {
    const auto source = fixture_path();

    TemporaryCorruptFile file(
        source,
        source.string() + ".bad_frame",
        64 + 24
    );

    tae::io::TelemetryReader reader(file.path());

    EXPECT_THROW(
        reader.next(),
        tae::io::TelemetryFormatError
    );
}

TEST(PythonIntegration, RejectsCorruptStaleness) {
    const auto source = fixture_path();

    TemporaryCorruptFile file(
        source,
        source.string() + ".bad_staleness",
        64 + 2 * 28 + 26
    );

    tae::io::TelemetryReader reader(file.path());

    ASSERT_TRUE(reader.next().has_value());
    ASSERT_TRUE(reader.next().has_value());

    EXPECT_THROW(
        reader.next(),
        tae::io::TelemetryFormatError
    );
}