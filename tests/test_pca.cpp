#include <gtest/gtest.h>

#include <cmath>
#include <limits>
#include <random>

#include "tae/detectors/pca.hpp"
#include "tae/math/symmetric.hpp"

using tae::math::Matrix;
using tae::math::Vector;

TEST(Covariance, CenteredReferenceAtLargeOffset) {
    tae::math::Covariance covariance;
    for (int index = 1; index <= 4; ++index) {
        Vector observation{};
        for (std::size_t channel = 0; channel < 6; ++channel) {
            observation[channel] =
                1e9 + static_cast<double>(index) * static_cast<double>(channel + 1);
        }
        covariance.add(observation);
    }
    const auto actual = covariance.sample_covariance();
    for (std::size_t row = 0; row < 6; ++row) {
        for (std::size_t column = 0; column < 6; ++column) {
            EXPECT_NEAR(actual[row][column],
                        5.0 / 3 * static_cast<double>((row + 1) * (column + 1)), 1e-7);
        }
    }
}

TEST(SymmetricEigen, ReconstructsRandomMatricesAndOrthonormalBasis) {
    std::mt19937 generator(2026);
    std::normal_distribution<double> random;
    for (int trial = 0; trial < 40; ++trial) {
        Matrix matrix{};
        for (std::size_t row = 0; row < 6; ++row) {
            for (std::size_t column = row; column < 6; ++column) {
                matrix[row][column] = matrix[column][row] = random(generator);
            }
        }
        const auto eigen = tae::math::symmetric_eigen(matrix);
        for (std::size_t row = 0; row < 6; ++row) {
            if (row)
                EXPECT_LE(eigen.values[row], eigen.values[row - 1]);
            for (std::size_t column = 0; column < 6; ++column) {
                double reconstructed = 0, identity = 0;
                for (std::size_t index = 0; index < 6; ++index) {
                    reconstructed += eigen.vectors[row][index] * eigen.values[index] *
                                     eigen.vectors[column][index];
                    identity += eigen.vectors[index][row] * eigen.vectors[index][column];
                }
                EXPECT_NEAR(reconstructed, matrix[row][column], 1e-10);
                EXPECT_NEAR(identity, row == column ? 1 : 0, 1e-12);
            }
        }
    }
}

TEST(SymmetricEigen, HandlesZeroRepeatedEigenvaluesAndRejectsMalformedInput) {
    const auto zero = tae::math::symmetric_eigen(Matrix{});
    for (double eigenvalue : zero.values)
        EXPECT_EQ(eigenvalue, 0);
    Matrix identity{};
    for (std::size_t index = 0; index < 6; ++index)
        identity[index][index] = 1;
    const auto repeated = tae::math::symmetric_eigen(identity);
    for (double eigenvalue : repeated.values)
        EXPECT_EQ(eigenvalue, 1);
    identity[0][1] = .1;
    EXPECT_THROW(tae::math::symmetric_eigen(identity), std::invalid_argument);
    identity[0][1] = std::numeric_limits<double>::quiet_NaN();
    EXPECT_THROW(tae::math::symmetric_eigen(identity), std::invalid_argument);
}

TEST(Pca, DetectsBrokenRelationshipWithUnchangedIndividualMagnitudes) {
    // Channels 41 and 42 normally move together. Their difference is low variance.
    Matrix covariance{};
    covariance[0][0] = covariance[1][1] = 1;
    covariance[0][1] = covariance[1][0] = .99;
    for (std::size_t index = 2; index < 6; ++index)
        covariance[index][index] = .01;
    const tae::detectors::PcaDetector detector(covariance, 1);
    const auto normal = detector.score(Vector{1, 1, 0, 0, 0, 0});
    const auto broken = detector.score(Vector{1, -1, 0, 0, 0, 0});
    EXPECT_NEAR(normal.error, 0, 1e-20);
    EXPECT_NEAR(broken.error, 1.0 / 3, 1e-12);
    EXPECT_NEAR(broken.channel_errors[0] + broken.channel_errors[1], broken.error, 1e-12);
    EXPECT_THROW(tae::detectors::PcaDetector(covariance, 0), std::invalid_argument);
    EXPECT_THROW(tae::detectors::PcaDetector(covariance, 6), std::invalid_argument);
    covariance[5][5] = -1;
    EXPECT_THROW(tae::detectors::PcaDetector(covariance, 1), std::invalid_argument);
}
