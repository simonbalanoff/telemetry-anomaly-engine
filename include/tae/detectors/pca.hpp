#pragma once

#include "tae/math/symmetric.hpp"

namespace tae::detectors {
struct Reconstruction {
    double error = 0;
    math::Vector channel_errors{};
};

// Fit on the covariance of training-normalized observations only.
class PcaDetector {
  public:
    PcaDetector(const math::Matrix &covariance, std::size_t retained_components);
    Reconstruction score(const math::Vector &normalized) const;
    const math::EigenSystem &eigensystem() const noexcept {
        return eigensystem_;
    }
    std::size_t components() const noexcept {
        return components_;
    }

  private:
    math::EigenSystem eigensystem_;
    std::size_t components_;
};
} // namespace tae::detectors
