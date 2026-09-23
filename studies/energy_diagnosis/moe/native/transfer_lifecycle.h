// SPDX-License-Identifier: MIT
// Standalone lifecycle used by the actual backend queue and portable tests.
#pragma once
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace alems {
// Predicate updates must hold the same mutex used by condition_variable::wait.
// An atomic predicate alone cannot prevent a notification before the waiter sleeps.
template <class Update>
inline void update_and_notify(std::mutex& mutex, std::condition_variable& cv,
                              Update update) {
  {
    std::lock_guard<std::mutex> lock(mutex);
    update();
  }
  cv.notify_all();
}

inline std::int64_t now_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct TransferRecord {
  std::uint64_t generation = 0;
  std::int64_t layer_id = -1;
  std::uint32_t tensor_id = 0;  // Backend node ID; Python resolves via topology.
  std::int64_t bytes = 0, transferred_bytes = 0;
  std::int64_t enqueue_ns = 0, start_ns = 0, end_ns = 0;
  std::int64_t queue_wait_ns = 0, transfer_ns = 0;
  std::string source_device, outcome;
};
struct TransferState {
  std::mutex mutex;
  std::unordered_map<std::uint32_t, std::int64_t> active;
  std::vector<TransferRecord> records;
  std::int64_t inflight = 0;
  std::uint64_t dropped = 0;
  std::size_t record_limit = 65536;
};
class TransferTicket {
  std::shared_ptr<TransferState> state_;
  TransferRecord record_;
  bool terminal_ = false;
 public:
  TransferTicket(std::shared_ptr<TransferState> state, TransferRecord record)
      : state_(std::move(state)), record_(std::move(record)) {}
  TransferTicket(const TransferTicket&) = delete;
  ~TransferTicket() noexcept { finish("cancelled", 0); }
  void start() {
    std::lock_guard<std::mutex> lock(state_->mutex);
    if (terminal_) throw std::logic_error("starting terminal transfer");
    if (record_.start_ns) throw std::logic_error("duplicate transfer start");
    record_.start_ns = now_ns();
  }
  void finish(const std::string& outcome, std::int64_t transferred) noexcept {
    std::lock_guard<std::mutex> lock(state_->mutex);
    if (terminal_) return;
    terminal_ = true;
    record_.end_ns = now_ns();
    record_.transferred_bytes = transferred;
    record_.queue_wait_ns = (record_.start_ns ? record_.start_ns : record_.end_ns) - record_.enqueue_ns;
    record_.transfer_ns = record_.start_ns ? record_.end_ns - record_.start_ns : 0;
    state_->inflight -= record_.bytes;
    state_->active.erase(record_.tensor_id);
    try {
      record_.outcome = outcome;
      if (state_->records.size() < state_->record_limit) state_->records.push_back(record_);
      else ++state_->dropped;
    } catch (...) { ++state_->dropped; }
  }
};
class TransferLedger {
  std::shared_ptr<TransferState> state_ = std::make_shared<TransferState>();
 public:
  std::shared_ptr<TransferTicket> admit(std::uint32_t node, std::int64_t bytes,
      std::int64_t limit, std::uint64_t generation, std::int64_t layer,
      const std::string& source) {
    std::lock_guard<std::mutex> lock(state_->mutex);
    if (bytes <= 0 || limit < 0 || bytes > limit || state_->inflight > limit - bytes
        || state_->active.count(node)) return {};
    TransferRecord record;
    record.tensor_id = node; record.bytes = bytes; record.generation = generation;
    record.layer_id = layer; record.source_device = source; record.enqueue_ns = now_ns();
    state_->active.emplace(node, bytes);
    state_->inflight += bytes;
    try { return std::make_shared<TransferTicket>(state_, record); }
    catch (...) { state_->active.erase(node); state_->inflight -= bytes; throw; }
  }
  std::int64_t inflight() const {
    std::lock_guard<std::mutex> lock(state_->mutex); return state_->inflight;
  }
  std::uint64_t dropped() const {
    std::lock_guard<std::mutex> lock(state_->mutex); return state_->dropped;
  }
  std::vector<TransferRecord> drain() {
    std::lock_guard<std::mutex> lock(state_->mutex);
    std::vector<TransferRecord> result; result.swap(state_->records); return result;
  }
};
struct PlacementRecord {
  std::uint64_t node = 0;
  std::int64_t bytes = 0, start_ns = 0, return_ns = 0;
  std::string source, destination;
  bool on_demand = false, completed_at_return = false;
};
class PlacementLog {
  std::mutex mutex_;
  std::vector<PlacementRecord> records_;
  std::uint64_t dropped_ = 0;
 public:
  void append(PlacementRecord r) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    try {
      if (records_.size() < 524288) records_.push_back(std::move(r));
      else ++dropped_;
    } catch (...) { ++dropped_; }
  }
  std::vector<PlacementRecord> drain() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<PlacementRecord> rows; rows.swap(records_); return rows;
  }
  std::uint64_t dropped() {
    std::lock_guard<std::mutex> lock(mutex_); return dropped_;
  }
};
inline PlacementLog placement_log;
}  // namespace alems
