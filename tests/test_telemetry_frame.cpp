#include <gtest/gtest.h>

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <limits>

#include "tae/io/telemetry_frame.hpp"

namespace {

using tae::io::FrameBytes;
using tae::io::FrameValidator;
using tae::io::TelemetryFormatError;
using tae::io::TelemetryFrame;

constexpr std::uint8_t ALL = 0x3F;

void write_u32(
    FrameBytes& bytes,
    std::size_t offset,
    std::uint32_t value
) {
    for (std::size_t i = 0; i < 4; ++i) {
        bytes[offset + i] = static_cast<std::byte>(
            (value >> (8 * i)) & 0xFFU
        );
    }
}

void write_u16(
    FrameBytes& bytes,
    std::size_t offset,
    std::uint16_t value
) {
    bytes[offset] = static_cast<std::byte>(value & 0xFFU);
    bytes[offset + 1] = static_cast<std::byte>(
        (value >> 8) & 0xFFU
    );
}

FrameBytes make_bytes(
    const std::array<float, 6>& values,
    std::uint8_t observed,
    std::uint8_t usable,
    std::uint16_t staleness
) {
    FrameBytes bytes{};

    for (std::size_t i = 0; i < values.size(); ++i) {
        write_u32(
            bytes,
            i * 4,
            std::bit_cast<std::uint32_t>(values[i])
        );
    }

    bytes[24] = static_cast<std::byte>(observed);
    bytes[25] = static_cast<std::byte>(usable);
    write_u16(bytes, 26, staleness);

    return bytes;
}

TelemetryFrame make_frame(
    const std::array<float, 6>& values,
    std::uint8_t observed,
    std::uint8_t usable,
    std::uint16_t staleness
) {
    return tae::io::decode_frame(
        make_bytes(values, observed, usable, staleness)
    );
}

const std::array<float, 6> VALUES{
    0.5f, 0.25f, 0.0f, -0.5f, 1.0f, 0.75f
};

const std::array<float, 6> ZERO{};

}

TEST(TelemetryFrame, DecodesObservedFrame) {
    const auto frame = make_frame(VALUES, ALL, ALL, 0);

    EXPECT_EQ(frame.observed_mask, ALL);
    EXPECT_EQ(frame.usable_mask, ALL);
    EXPECT_EQ(frame.staleness, 0);

    for (std::size_t i = 0; i < VALUES.size(); ++i) {
        EXPECT_EQ(frame.values[i], VALUES[i]);
    }
}

TEST(TelemetryFrame, DecodesForwardFilledFrame) {
    const auto frame = make_frame(VALUES, 0, ALL, 3);

    EXPECT_EQ(frame.observed_mask, 0);
    EXPECT_EQ(frame.usable_mask, ALL);
    EXPECT_EQ(frame.staleness, 3);
}

TEST(TelemetryFrame, DecodesUnavailableFrame) {
    const auto frame = make_frame(ZERO, 0, 0, 6);

    EXPECT_EQ(frame.observed_mask, 0);
    EXPECT_EQ(frame.usable_mask, 0);
    EXPECT_EQ(frame.staleness, 6);
}

TEST(TelemetryFrame, RejectsInvalidObservedMask) {
    EXPECT_THROW(
        make_frame(VALUES, 0x01, ALL, 0),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsInvalidUsableMask) {
    EXPECT_THROW(
        make_frame(VALUES, ALL, 0x01, 0),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsObservedWithStaleness) {
    EXPECT_THROW(
        make_frame(VALUES, ALL, ALL, 2),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsObservedButUnusable) {
    EXPECT_THROW(
        make_frame(VALUES, ALL, 0, 0),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsFillWithZeroStaleness) {
    EXPECT_THROW(
        make_frame(VALUES, 0, ALL, 0),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsFillBeyondLimit) {
    EXPECT_THROW(
        make_frame(VALUES, 0, ALL, 6),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsUnavailableTooEarly) {
    EXPECT_THROW(
        make_frame(ZERO, 0, 0, 5),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsNonzeroUnavailableValues) {
    EXPECT_THROW(
        make_frame(VALUES, 0, 0, 6),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsNegativeZeroWhenUnavailable) {
    auto values = ZERO;
    values[0] = -0.0f;

    EXPECT_THROW(
        make_frame(values, 0, 0, 6),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsNaN) {
    auto values = VALUES;
    values[0] = std::numeric_limits<float>::quiet_NaN();

    EXPECT_THROW(
        make_frame(values, ALL, ALL, 0),
        TelemetryFormatError
    );
}

TEST(TelemetryFrame, RejectsInfinity) {
    auto values = VALUES;
    values[0] = std::numeric_limits<float>::infinity();

    EXPECT_THROW(
        make_frame(values, ALL, ALL, 0),
        TelemetryFormatError
    );
}

TEST(FrameValidator, RequiresObservedFirstFrame) {
    FrameValidator validator;

    const auto frame = make_frame(VALUES, 0, ALL, 1);

    EXPECT_THROW(
        validator.validate(frame),
        TelemetryFormatError
    );
}

TEST(FrameValidator, AcceptsObservedFirstFrame) {
    FrameValidator validator;

    const auto frame = make_frame(VALUES, ALL, ALL, 0);

    EXPECT_NO_THROW(validator.validate(frame));
}

TEST(FrameValidator, AcceptsFiveConsecutiveFills) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    for (std::uint16_t i = 1; i <= 5; ++i) {
        EXPECT_NO_THROW(
            validator.validate(make_frame(VALUES, 0, ALL, i))
        );
    }
}

TEST(FrameValidator, RejectsIncorrectFillValues) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    auto changed = VALUES;
    changed[2] = 0.1f;

    EXPECT_THROW(
        validator.validate(make_frame(changed, 0, ALL, 1)),
        TelemetryFormatError
    );
}

TEST(FrameValidator, RejectsSkippedStaleness) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    EXPECT_THROW(
        validator.validate(make_frame(VALUES, 0, ALL, 3)),
        TelemetryFormatError
    );
}

TEST(FrameValidator, AcceptsExtendedOutage) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    for (std::uint16_t i = 1; i <= 5; ++i) {
        validator.validate(make_frame(VALUES, 0, ALL, i));
    }

    validator.validate(make_frame(ZERO, 0, 0, 6));
    validator.validate(make_frame(ZERO, 0, 0, 7));

    EXPECT_NO_THROW(
        validator.validate(make_frame(VALUES, ALL, ALL, 0))
    );
}

TEST(FrameValidator, RejectsIncorrectUnavailableTransition) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    for (std::uint16_t i = 1; i <= 5; ++i) {
        validator.validate(make_frame(VALUES, 0, ALL, i));
    }

    EXPECT_THROW(
        validator.validate(make_frame(ZERO, 0, 0, 8)),
        TelemetryFormatError
    );
}

TEST(FrameValidator, ResetsOnNewObservation) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));
    validator.validate(make_frame(VALUES, 0, ALL, 1));

    auto next = VALUES;
    next[0] = 0.9f;

    validator.validate(make_frame(next, ALL, ALL, 0));

    EXPECT_NO_THROW(
        validator.validate(make_frame(next, 0, ALL, 1))
    );
}

TEST(FrameValidator, ResetAllowsNewStream) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));
    validator.reset();

    EXPECT_THROW(
        validator.validate(make_frame(VALUES, 0, ALL, 1)),
        TelemetryFormatError
    );

    EXPECT_NO_THROW(
        validator.validate(make_frame(VALUES, ALL, ALL, 0))
    );
}

TEST(FrameValidator, CanRecoverAfterRejectedFrame) {
    FrameValidator validator;

    validator.validate(make_frame(VALUES, ALL, ALL, 0));

    auto changed = VALUES;
    changed[0] = 0.9f;

    EXPECT_THROW(
        validator.validate(make_frame(changed, 0, ALL, 1)),
        TelemetryFormatError
    );

    EXPECT_NO_THROW(
        validator.validate(make_frame(VALUES, 0, ALL, 1))
    );
}
