#pragma once
#include "tae/io/telemetry_frame.hpp"
#include <cstddef>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace tae::runtime {
// Pool must outlive its leases. Nonblocking acquire; a lease returns its slot on destruction.
class FramePool {
  public:
    class Lease {
      public:
        Lease(const Lease &) = delete;
        Lease &operator=(const Lease &) = delete;
        Lease(Lease &&other) noexcept
            : pool_(std::exchange(other.pool_, nullptr)), index_(other.index_) {}
        Lease &operator=(Lease &&other) noexcept {
            if (this != &other) {
                release();
                pool_ = std::exchange(other.pool_, nullptr);
                index_ = other.index_;
            }
            return *this;
        }
        ~Lease() {
            release();
        }
        io::TelemetryFrame &operator*() const {
            return pool_->frames_[index_];
        }
        io::TelemetryFrame *operator->() const {
            return &**this;
        }

      private:
        friend class FramePool;
        Lease(FramePool *pool, std::size_t index) : pool_(pool), index_(index) {}
        void release() {
            if (pool_) {
                std::lock_guard lock(pool_->mutex_);
                pool_->free_.push_back(index_);
                pool_ = nullptr;
            }
        }
        FramePool *pool_;
        std::size_t index_;
    };
    explicit FramePool(std::size_t capacity) : frames_(capacity) {
        if (!capacity)
            throw std::invalid_argument("Pool capacity must be positive");
        free_.reserve(capacity);
        for (std::size_t i = capacity; i > 0; --i)
            free_.push_back(i - 1);
    }
    std::optional<Lease> acquire() {
        std::lock_guard lock(mutex_);
        if (free_.empty())
            return std::nullopt;
        auto index = free_.back();
        free_.pop_back();
        return Lease(this, index);
    }

  private:
    std::vector<io::TelemetryFrame> frames_;
    std::vector<std::size_t> free_;
    std::mutex mutex_;
};
} // namespace tae::runtime
