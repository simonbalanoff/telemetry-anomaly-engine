#include "tae/detectors/statistical.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace tae::detectors {
void Moments::add(double x) {
    ++count;
    const double delta = x - mean;
    mean += delta / static_cast<double>(count);
    m2 += delta * (x - mean);
}
void Moments::remove(double x) {
    if (count <= 1) {
        *this = {};
        return;
    }
    const double old = mean;
    --count;
    mean -= (x - mean) / static_cast<double>(count);
    m2 = std::max(0.0, m2 - (x - old) * (x - mean));
}
double Moments::variance() const {
    return count > 1 ? m2 / static_cast<double>(count - 1) : 0;
}
void Normalizer::fit(const io::TelemetryFrame &frame) {
    if (frame.observed_mask != 0x3f)
        return;
    for (std::size_t c = 0; c < 6; ++c)
        moments_[c].add(frame.values[c]);
}
std::array<double, 6> Normalizer::transform(const io::TelemetryFrame &frame) const {
    if (count() < 2)
        throw std::runtime_error("Insufficient eligible training observations");
    std::array<double, 6> result{};
    for (std::size_t c = 0; c < 6; ++c)
        result[c] = (frame.values[c] - moments_[c].mean) /
                    std::max(1e-12, std::sqrt(moments_[c].variance()));
    return result;
}
StatisticalDetector::StatisticalDetector(std::size_t window, double alpha, double sigma_floor)
    : history_(window), alpha_(alpha), sigma_floor_(sigma_floor) {
    if (window < 2 || !std::isfinite(alpha) || alpha <= 0 || alpha > 1 ||
        !std::isfinite(sigma_floor) || sigma_floor <= 0)
        throw std::invalid_argument("Invalid statistical detector configuration");
}
void StatisticalDetector::reset() {
    rolling_ = {};
    ewma_ = {};
    size_ = 0;
    cursor_ = 0;
}
std::optional<Scores> StatisticalDetector::update(const io::TelemetryFrame &frame,
                                                  const Normalizer &normalizer) {
    if (frame.usable_mask != 0x3f) {
        reset();
        return std::nullopt;
    }
    const auto values = normalizer.transform(frame);
    std::optional<Scores> result;
    if (size_ == history_.size()) {
        Scores scores{};
        for (std::size_t c = 0; c < 6; ++c) {
            const double sigma = std::max(sigma_floor_, std::sqrt(rolling_[c].variance()));
            scores.zscore = std::max(scores.zscore, std::abs(values[c] - rolling_[c].mean) / sigma);
            const double next = alpha_ * values[c] + (1 - alpha_) * ewma_[c];
            scores.ewma = std::max(scores.ewma, std::abs(next) / std::sqrt(alpha_ / (2 - alpha_)));
        }
        result = scores;
    }
    for (std::size_t c = 0; c < 6; ++c) {
        if (size_ == history_.size())
            rolling_[c].remove(history_[cursor_][c]);
        rolling_[c].add(values[c]);
        ewma_[c] = size_ == 0 ? values[c] : alpha_ * values[c] + (1 - alpha_) * ewma_[c];
    }
    history_[cursor_] = values;
    cursor_ = (cursor_ + 1) % history_.size();
    size_ = std::min(size_ + 1, history_.size());
    return result;
}
} // namespace tae::detectors
