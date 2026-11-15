#include "tae/detectors/pca.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace tae::detectors {
PcaDetector::PcaDetector(const math::Matrix &covariance, std::size_t retained_components)
    : eigensystem_(math::symmetric_eigen(covariance)), components_(retained_components) {
    if (components_ == 0 || components_ >= math::dimensions) {
        throw std::invalid_argument("PCA requires between one and five retained components");
    }
    const double tolerance = std::max(1e-12, std::abs(eigensystem_.values[0]) * 1e-10);
    for (double eigenvalue : eigensystem_.values) {
        if (eigenvalue < -tolerance) {
            throw std::invalid_argument("PCA covariance must be positive semidefinite");
        }
    }
}

Reconstruction PcaDetector::score(const math::Vector &normalized) const {
    math::Vector reconstructed{};
    for (double value : normalized) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("PCA observations must be finite");
        }
    }
    for (std::size_t component = 0; component < components_; ++component) {
        double projection = 0;
        for (std::size_t channel = 0; channel < math::dimensions; ++channel) {
            projection += normalized[channel] * eigensystem_.vectors[channel][component];
        }
        for (std::size_t channel = 0; channel < math::dimensions; ++channel) {
            reconstructed[channel] += projection * eigensystem_.vectors[channel][component];
        }
    }
    Reconstruction result;
    for (std::size_t channel = 0; channel < math::dimensions; ++channel) {
        const double residual = normalized[channel] - reconstructed[channel];
        result.channel_errors[channel] =
            residual * residual / static_cast<double>(math::dimensions);
        result.error += result.channel_errors[channel];
    }
    return result;
}
} // namespace tae::detectors
