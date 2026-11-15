#pragma once
#include "tae/io/telemetry_frame.hpp"
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace tae::detectors {
struct Moments {
    std::uint64_t count = 0;
    double mean = 0, m2 = 0;
    void add(double x);
    void remove(double x);
    double variance() const;
};
class Normalizer {
  public:
    void fit(const io::TelemetryFrame &frame);
    std::array<double, 6> transform(const io::TelemetryFrame &frame) const;
    std::uint64_t count() const {
        return moments_[0].count;
    }
    const std::array<Moments, 6> &moments() const {
        return moments_;
    }

  private:
    std::array<Moments, 6> moments_{};
};
struct Scores {
    double zscore, ewma;
};
// Scores compare against PRIOR history. Exactly window usable cells warm up each reset.
class StatisticalDetector {
  public:
    StatisticalDetector(std::size_t window = 120, double alpha = 0.05, double sigma_floor = 0.05);
    void reset();
    std::optional<Scores> update(const io::TelemetryFrame &frame, const Normalizer &normalizer);

  private:
    std::vector<std::array<double, 6>> history_;
    std::array<Moments, 6> rolling_{};
    std::array<double, 6> ewma_{};
    std::size_t size_ = 0, cursor_ = 0;
    double alpha_, sigma_floor_;
};
} // namespace tae::detectors
