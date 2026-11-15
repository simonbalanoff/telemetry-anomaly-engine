#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace tae::math {
inline constexpr std::size_t dimensions = 6;
using Vector = std::array<double, dimensions>;
using Matrix = std::array<Vector, dimensions>;

// Online, centered covariance: memory use is independent of observation count.
class Covariance {
  public:
    void add(const Vector &value);
    Matrix sample_covariance() const;
    std::uint64_t count() const noexcept {
        return count_;
    }

  private:
    std::uint64_t count_ = 0;
    Vector mean_{};
    Matrix scatter_{};
};

struct EigenSystem {
    Vector values{};  // Descending order.
    Matrix vectors{}; // Eigenvectors are columns, matching NumPy's convention.
};

// Jacobi rotations for a finite symmetric 6x6 matrix. Throws on non-convergence.
EigenSystem symmetric_eigen(const Matrix &input);
} // namespace tae::math
