#include "tae/math/symmetric.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace tae::math {
void Covariance::add(const Vector &value) {
    for (double element : value) {
        if (!std::isfinite(element)) {
            throw std::invalid_argument("Covariance observations must be finite");
        }
    }
    ++count_;
    Vector delta{};
    for (std::size_t row = 0; row < dimensions; ++row) {
        delta[row] = value[row] - mean_[row];
        mean_[row] += delta[row] / static_cast<double>(count_);
    }
    const double weight = static_cast<double>(count_ - 1) / static_cast<double>(count_);
    for (std::size_t row = 0; row < dimensions; ++row) {
        for (std::size_t column = row; column < dimensions; ++column) {
            scatter_[row][column] += weight * delta[row] * delta[column];
            scatter_[column][row] = scatter_[row][column];
        }
    }
}

Matrix Covariance::sample_covariance() const {
    if (count_ < 2) {
        throw std::runtime_error("Covariance requires at least two observations");
    }
    Matrix result = scatter_;
    for (auto &row : result) {
        for (auto &element : row) {
            element /= static_cast<double>(count_ - 1);
        }
    }
    return result;
}

EigenSystem symmetric_eigen(const Matrix &input) {
    double scale = 0;
    for (const auto &row : input) {
        for (double element : row) {
            if (!std::isfinite(element)) {
                throw std::invalid_argument("Eigenproblem must be finite");
            }
            scale = std::max(scale, std::abs(element));
        }
    }
    const double tolerance = std::max(1e-300, scale * 1e-13);
    Matrix matrix = input;
    Matrix vectors{};
    for (std::size_t row = 0; row < dimensions; ++row) {
        vectors[row][row] = 1;
        for (std::size_t column = row + 1; column < dimensions; ++column) {
            if (std::abs(input[row][column] - input[column][row]) > tolerance) {
                throw std::invalid_argument("Eigenproblem must be symmetric");
            }
        }
    }

    bool converged = false;
    for (std::size_t iteration = 0; iteration < 1024; ++iteration) {
        std::size_t pivot_row = 0, pivot_column = 1;
        double largest = 0;
        for (std::size_t row = 0; row < dimensions; ++row) {
            for (std::size_t column = row + 1; column < dimensions; ++column) {
                if (std::abs(matrix[row][column]) > largest) {
                    largest = std::abs(matrix[row][column]);
                    pivot_row = row;
                    pivot_column = column;
                }
            }
        }
        if (largest <= tolerance) {
            converged = true;
            break;
        }

        const auto p = pivot_row, q = pivot_column;
        const double angle = .5 * std::atan2(2 * matrix[p][q], matrix[q][q] - matrix[p][p]);
        const double cosine = std::cos(angle), sine = std::sin(angle);
        const double pp = matrix[p][p], qq = matrix[q][q], pq = matrix[p][q];
        matrix[p][p] = cosine * cosine * pp - 2 * sine * cosine * pq + sine * sine * qq;
        matrix[q][q] = sine * sine * pp + 2 * sine * cosine * pq + cosine * cosine * qq;
        matrix[p][q] = matrix[q][p] = 0;
        for (std::size_t index = 0; index < dimensions; ++index) {
            if (index != p && index != q) {
                const double ip = matrix[index][p], iq = matrix[index][q];
                matrix[index][p] = matrix[p][index] = cosine * ip - sine * iq;
                matrix[index][q] = matrix[q][index] = sine * ip + cosine * iq;
            }
            const double vp = vectors[index][p], vq = vectors[index][q];
            vectors[index][p] = cosine * vp - sine * vq;
            vectors[index][q] = sine * vp + cosine * vq;
        }
    }
    if (!converged) {
        throw std::runtime_error("Symmetric eigensolver did not converge");
    }

    std::array<std::size_t, dimensions> order{};
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](auto first, auto second) {
        return matrix[first][first] > matrix[second][second];
    });
    EigenSystem result;
    for (std::size_t column = 0; column < dimensions; ++column) {
        result.values[column] = matrix[order[column]][order[column]];
        // Fix the arbitrary eigenvector sign for reproducible model artifacts.
        std::size_t dominant = 0;
        for (std::size_t row = 1; row < dimensions; ++row) {
            if (std::abs(vectors[row][order[column]]) >
                std::abs(vectors[dominant][order[column]])) {
                dominant = row;
            }
        }
        const double sign = vectors[dominant][order[column]] < 0 ? -1 : 1;
        for (std::size_t row = 0; row < dimensions; ++row) {
            result.vectors[row][column] = sign * vectors[row][order[column]];
        }
    }
    return result;
}
} // namespace tae::math
