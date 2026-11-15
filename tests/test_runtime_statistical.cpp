#include "tae/detectors/statistical.hpp"
#include "tae/runtime/bounded_queue.hpp"
#include "tae/runtime/frame_pool.hpp"
#include <array>
#include <atomic>
#include <cmath>
#include <future>
#include <gtest/gtest.h>
#include <thread>

namespace {
tae::io::TelemetryFrame observed(float x) {
    return {{x, x, x, x, x, x}, 0x3f, 0x3f, 0};
}
} // namespace
TEST(Moments, StableAtLargeOffsetAndRemovable) {
    tae::detectors::Moments m;
    for (double x : {1e9 + 1, 1e9 + 2, 1e9 + 3, 1e9 + 4})
        m.add(x);
    EXPECT_NEAR(m.mean, 1e9 + 2.5, 1e-6);
    EXPECT_NEAR(m.variance(), 5.0 / 3, 1e-8);
    m.remove(1e9 + 1);
    EXPECT_NEAR(m.mean, 1e9 + 3, 1e-6);
    EXPECT_NEAR(m.variance(), 1, 1e-8);
}
TEST(Normalizer, IgnoresFillsAndUnavailable) {
    tae::detectors::Normalizer n;
    n.fit(observed(0));
    n.fit(observed(2));
    auto frame = observed(100);
    frame.observed_mask = 0;
    n.fit(frame);
    EXPECT_EQ(n.count(), 2);
    EXPECT_NEAR(n.transform(observed(1))[0], 0, 1e-12);
    EXPECT_NEAR(n.transform(observed(3))[0], std::sqrt(2.0), 1e-12);
}
TEST(Statistical, IndependentRollingAndEwmaReference) {
    tae::detectors::Normalizer n;
    n.fit(observed(-1));
    n.fit(observed(1));
    tae::detectors::StatisticalDetector detector(4, .2);
    std::array<double, 4> history{};
    double ewma = 0;
    for (int i = 0; i < 200; ++i) {
        const auto frame = observed(static_cast<float>(std::sin(i * .3)));
        const double x = n.transform(frame)[0];
        auto result = detector.update(frame, n);
        if (i >= 4) {
            double mean = 0, variance = 0;
            for (auto value : history)
                mean += value / 4;
            for (auto value : history)
                variance += (value - mean) * (value - mean) / 3;
            ASSERT_TRUE(result);
            EXPECT_NEAR(result->zscore, std::abs(x - mean) / std::max(.05, std::sqrt(variance)),
                        1e-9);
            EXPECT_NEAR(result->ewma, std::abs(.2 * x + .8 * ewma) / std::sqrt(.2 / 1.8), 1e-9);
        } else
            EXPECT_FALSE(result);
        ewma = i == 0 ? x : .2 * x + .8 * ewma;
        history[static_cast<std::size_t>(i) % 4] = x;
    }
}
TEST(Statistical, OutageAndSplitResetRequireFullWarmup) {
    tae::detectors::Normalizer n;
    n.fit(observed(0));
    n.fit(observed(1));
    tae::detectors::StatisticalDetector d(2);
    EXPECT_FALSE(d.update(observed(0), n));
    EXPECT_FALSE(d.update(observed(1), n));
    EXPECT_TRUE(d.update(observed(10), n));
    auto frame = observed(0);
    frame.usable_mask = 0;
    frame.observed_mask = 0;
    EXPECT_FALSE(d.update(frame, n));
    EXPECT_FALSE(d.update(observed(1), n));
    EXPECT_FALSE(d.update(observed(1), n));
    EXPECT_TRUE(d.update(observed(1), n));
    d.reset();
    EXPECT_FALSE(d.update(observed(1), n));
}
TEST(Statistical, RejectsInvalidConfiguration) {
    EXPECT_THROW(tae::detectors::StatisticalDetector(1), std::invalid_argument);
    EXPECT_THROW(tae::detectors::StatisticalDetector(2, 0), std::invalid_argument);
}
TEST(FramePool, ExhaustionMoveAndAutomaticReturn) {
    tae::runtime::FramePool pool(1);
    auto lease = pool.acquire();
    ASSERT_TRUE(lease);
    (*lease)->staleness = 42;
    EXPECT_FALSE(pool.acquire());
    auto moved = std::move(*lease);
    lease.reset();
    EXPECT_FALSE(pool.acquire());
    EXPECT_EQ(moved->staleness, 42);
    {
        auto other = std::move(moved);
        EXPECT_EQ(other->staleness, 42);
    }
    EXPECT_TRUE(pool.acquire());
    EXPECT_THROW(tae::runtime::FramePool(0), std::invalid_argument);
}
TEST(BoundedQueue, WraparoundAndDrainAfterClose) {
    tae::runtime::BoundedQueue<int> q(2);
    EXPECT_TRUE(q.push(1));
    EXPECT_TRUE(q.push(2));
    EXPECT_EQ(q.pop(), 1);
    EXPECT_TRUE(q.push(3));
    q.close();
    EXPECT_FALSE(q.push(4));
    EXPECT_EQ(q.pop(), 2);
    EXPECT_EQ(q.pop(), 3);
    EXPECT_FALSE(q.pop());
}
TEST(BoundedQueue, CloseWakesBlockedProducerAndConsumer) {
    tae::runtime::BoundedQueue<int> full(1), empty(1);
    full.push(1);
    auto producer = std::async(std::launch::async, [&] { return full.push(2); });
    auto consumer = std::async(std::launch::async, [&] { return empty.pop(); });
    full.close();
    empty.close();
    EXPECT_FALSE(producer.get());
    EXPECT_FALSE(consumer.get());
}
TEST(Runtime, LeasesTransferAcrossThreadsWithoutLostFrames) {
    tae::runtime::FramePool pool(8);
    tae::runtime::BoundedQueue<tae::runtime::FramePool::Lease> queue(4);
    std::uint64_t total = 0;
    std::jthread consumer([&] {
        while (auto lease = queue.pop())
            total += (*lease)->staleness;
    });
    for (int i = 0; i < 10000; ++i) {
        auto lease = pool.acquire();
        while (!lease) {
            std::this_thread::yield();
            lease = pool.acquire();
        }
        (*lease)->staleness = 1;
        ASSERT_TRUE(queue.push(std::move(*lease)));
    }
    queue.close();
    consumer.join();
    EXPECT_EQ(total, 10000);
    for (int i = 0; i < 100; ++i)
        EXPECT_TRUE(pool.acquire());
}

TEST(BoundedQueue, MultipleProducersAndConsumersPreserveEveryItem) {
    tae::runtime::BoundedQueue<int> queue(7);
    std::atomic<std::uint64_t> total{0};
    std::atomic<std::uint64_t> count{0};
    std::vector<std::jthread> consumers;
    for (int worker = 0; worker < 2; ++worker) {
        consumers.emplace_back([&] {
            while (auto value = queue.pop()) {
                total.fetch_add(static_cast<std::uint64_t>(*value));
                count.fetch_add(1);
            }
        });
    }
    std::vector<std::jthread> producers;
    for (int worker = 0; worker < 4; ++worker) {
        producers.emplace_back([&, worker] {
            for (int index = 1; index <= 1000; ++index) {
                queue.push(worker * 1000 + index);
            }
        });
    }
    producers.clear(); // jthread joins before the queue is closed.
    queue.close();
    consumers.clear();
    EXPECT_EQ(count.load(), 4000);
    EXPECT_EQ(total.load(), 4000ULL * 4001 / 2);
}
