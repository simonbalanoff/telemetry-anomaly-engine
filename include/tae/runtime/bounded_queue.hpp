#pragma once
#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace tae::runtime {
// Fixed storage, blocking MPMC queue. close() wakes all waiters; consumers drain.
template <class T> class BoundedQueue {
  public:
    explicit BoundedQueue(std::size_t capacity) : slots_(capacity) {
        if (capacity == 0)
            throw std::invalid_argument("Queue capacity must be positive");
    }
    bool push(T value) {
        std::unique_lock lock(mutex_);
        writable_.wait(lock, [&] { return closed_ || count_ < slots_.size(); });
        if (closed_)
            return false;
        slots_[tail_].emplace(std::move(value));
        tail_ = (tail_ + 1) % slots_.size();
        ++count_;
        readable_.notify_one();
        return true;
    }
    std::optional<T> pop() {
        std::unique_lock lock(mutex_);
        readable_.wait(lock, [&] { return closed_ || count_ != 0; });
        if (count_ == 0)
            return std::nullopt;
        auto value = std::move(slots_[head_]);
        slots_[head_].reset();
        head_ = (head_ + 1) % slots_.size();
        --count_;
        writable_.notify_one();
        return value;
    }
    void close() {
        std::lock_guard lock(mutex_);
        closed_ = true;
        readable_.notify_all();
        writable_.notify_all();
    }

  private:
    std::vector<std::optional<T>> slots_;
    std::size_t head_ = 0, tail_ = 0, count_ = 0;
    bool closed_ = false;
    std::mutex mutex_;
    std::condition_variable readable_, writable_;
};
} // namespace tae::runtime
