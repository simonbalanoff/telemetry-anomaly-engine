#include "commands.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

#include "tae/detectors/statistical.hpp"
#include "tae/io/telemetry_reader.hpp"

namespace tae::cli {
namespace {
constexpr std::int64_t period_us = 30'000'000;

struct ScoringSummary {
    std::uint64_t scored_frames = 0;
    std::vector<double> latency_ns;
};

// Fixed little-endian binary64 records avoid a large text file for 14M frames.
void write_double(std::ostream &output, double value) {
    const auto bits = std::bit_cast<std::uint64_t>(value);
    std::array<char, 8> bytes{};
    for (unsigned index = 0; index < 8; ++index) {
        bytes[index] = static_cast<char>((bits >> (index * 8)) & 255);
    }
    output.write(bytes.data(), 8);
}

void require_distinct_paths(const std::array<std::filesystem::path, 4> &paths) {
    for (std::size_t first = 0; first < paths.size(); ++first) {
        for (std::size_t second = first + 1; second < paths.size(); ++second) {
            if (std::filesystem::weakly_canonical(paths[first]) ==
                    std::filesystem::weakly_canonical(paths[second]) ||
                (std::filesystem::exists(paths[first]) && std::filesystem::exists(paths[second]) &&
                 std::filesystem::equivalent(paths[first], paths[second]))) {
                throw std::invalid_argument("Input and output paths must be distinct");
            }
        }
    }
}

tae::detectors::Normalizer fit_normalizer(const std::filesystem::path &telemetry,
                                          const std::filesystem::path &training_mask,
                                          io::HeaderPolicy policy) {
    io::TelemetryReader reader(telemetry, policy);
    const auto header = reader.header();
    if (std::filesystem::file_size(training_mask) != header.frame_count) {
        throw std::runtime_error("Training mask length mismatch");
    }
    std::ifstream mask(training_mask, std::ios::binary);
    if (!mask)
        throw std::runtime_error("Cannot open training mask");

    detectors::Normalizer normalizer;
    while (auto frame = reader.next()) {
        char eligible = 0;
        if (!mask.get(eligible) || (eligible != 0 && eligible != 1)) {
            throw std::runtime_error("Invalid training mask");
        }
        const auto index = static_cast<std::int64_t>(reader.frames_read() - 1);
        const auto timestamp = header.start_us + index * period_us;
        if (eligible && timestamp >= header.validation_start_us) {
            throw std::runtime_error("Training mask leaks across split");
        }
        if (eligible)
            normalizer.fit(*frame);
    }
    if (normalizer.count() < 2) {
        throw std::runtime_error("Insufficient eligible training data");
    }
    return normalizer;
}

ScoringSummary write_scores(io::TelemetryReader &reader, const detectors::Normalizer &normalizer,
                            detectors::StatisticalDetector &detector,
                            const std::filesystem::path &scores_path) {
    std::ofstream output(scores_path, std::ios::binary);
    if (!output)
        throw std::runtime_error("Cannot open score output");

    const auto header = reader.header();
    const double missing = std::numeric_limits<double>::quiet_NaN();
    ScoringSummary summary;
    summary.latency_ns.reserve(static_cast<std::size_t>(header.frame_count / 1024 + 1));
    while (auto frame = reader.next()) {
        const auto index = reader.frames_read() - 1;
        const auto timestamp = header.start_us + static_cast<std::int64_t>(index) * period_us;
        if (timestamp == header.validation_start_us || timestamp == header.test_start_us) {
            detector.reset();
        }

        // Sample one in 1024 updates, excluding I/O and integrity checks from timing.
        const bool sample_latency = index % 1024 == 0;
        const auto start = sample_latency ? std::chrono::steady_clock::now()
                                          : std::chrono::steady_clock::time_point{};
        const auto scores = detector.update(*frame, normalizer);
        if (sample_latency) {
            const auto duration = std::chrono::steady_clock::now() - start;
            summary.latency_ns.push_back(
                std::chrono::duration<double, std::nano>(duration).count());
        }
        write_double(output, scores ? scores->zscore : missing);
        write_double(output, scores ? scores->ewma : missing);
        if (scores)
            ++summary.scored_frames;
    }
    output.close();
    if (!output)
        throw std::runtime_error("Failed to write scores");
    return summary;
}

void write_metadata(const std::filesystem::path &path, const io::TelemetryHeader &header,
                    const detectors::Normalizer &normalizer, ScoringSummary &summary,
                    std::size_t window, double alpha) {
    std::ofstream output(path);
    if (!output)
        throw std::runtime_error("Cannot open metadata output");

    std::sort(summary.latency_ns.begin(), summary.latency_ns.end());
    const auto quantile = [&](double fraction) {
        const auto index =
            static_cast<std::size_t>(fraction * static_cast<double>(summary.latency_ns.size() - 1));
        return summary.latency_ns[index];
    };
    output << std::setprecision(17) << "{\n  \"training_observations\": " << normalizer.count()
           << ",\n  \"frames\": " << header.frame_count
           << ",\n  \"scored\": " << summary.scored_frames << ",\n  \"window\": " << window
           << ",\n  \"alpha\": " << alpha
           << ",\n  \"sigma_floor\": 0.05,\n  \"latency_samples\": " << summary.latency_ns.size()
           << ",\n  \"latency_ns\": {\"p50\": " << quantile(.5) << ", \"p95\": " << quantile(.95)
           << ", \"p99\": " << quantile(.99) << "},\n  \"normalization\": [";
    bool first = true;
    for (const auto &moment : normalizer.moments()) {
        if (!first)
            output << ',';
        first = false;
        output << "\n    {\"mean\": " << moment.mean << ", \"variance\": " << moment.variance()
               << '}';
    }
    output << "\n  ]\n}\n";
    output.close();
    if (!output)
        throw std::runtime_error("Failed to write metadata");
}
} // namespace

void verify(const std::filesystem::path &telemetry) {
    io::TelemetryReader reader(telemetry);
    std::uint64_t observed = 0, filled = 0, unavailable = 0;
    while (auto frame = reader.next()) {
        if (frame->observed_mask)
            ++observed;
        else if (frame->usable_mask)
            ++filled;
        else
            ++unavailable;
    }
    std::cout << "{\"frames\":" << reader.frames_read() << ",\"observed\":" << observed
              << ",\"filled\":" << filled << ",\"unavailable\":" << unavailable << "}\n";
}

void score(const std::filesystem::path &telemetry, const std::filesystem::path &training_mask,
           const std::filesystem::path &scores, const std::filesystem::path &metadata,
           const std::string &window_text, const std::string &alpha_text, io::HeaderPolicy policy) {
    require_distinct_paths({telemetry, training_mask, scores, metadata});
    std::size_t parsed = 0;
    const auto window = std::stoull(window_text, &parsed);
    if (parsed != window_text.size() || window < 2 || window > 1'000'000 || window_text[0] == '-') {
        throw std::invalid_argument("Window must be 2..1000000");
    }
    const double alpha = std::stod(alpha_text, &parsed);
    if (parsed != alpha_text.size())
        throw std::invalid_argument("Invalid alpha");
    detectors::StatisticalDetector detector(static_cast<std::size_t>(window), alpha);
    const auto normalizer = fit_normalizer(telemetry, training_mask, policy);
    io::TelemetryReader reader(telemetry, policy);
    auto summary = write_scores(reader, normalizer, detector, scores);
    write_metadata(metadata, reader.header(), normalizer, summary, static_cast<std::size_t>(window),
                   alpha);
    std::cout << "Scored " << summary.scored_frames << " / " << reader.header().frame_count
              << " frames\n";
}
} // namespace tae::cli
