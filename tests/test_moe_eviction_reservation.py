"""Force both interleavings at demand acquisition versus eviction selection."""
from pathlib import Path
import shutil
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('legacy',[False,True])
def test_selected_idle_expert_cannot_be_evicted_after_demand_claim(tmp_path,legacy):
    header=ROOT/'studies/energy_diagnosis/moe/native/transfer_lifecycle.h'
    code=r'''
#include "transfer_lifecycle.h"
#include <atomic>
#include <thread>
int main() {
 enum State { IDLE, FETCHING, EVICTING };
 std::atomic<State> state{IDLE}; std::atomic<int> phase{0};
 bool evicted=false;
 std::thread eviction([&] {
   bool selected=state.load()==IDLE;
   phase.store(1);
   while(phase.load()!=2) std::this_thread::yield();
   evicted=LEGACY ? selected : alems::reserve_idle(state,IDLE,EVICTING);
 });
 while(phase.load()!=1) std::this_thread::yield();
 if(!alems::reserve_idle(state,IDLE,FETCHING)) return 2;
 phase.store(2);eviction.join();
 if(evicted)return 3;
 state.store(IDLE);
 if(!alems::reserve_idle(state,IDLE,EVICTING))return 4;
 if(alems::reserve_idle(state,IDLE,FETCHING))return 5;
 state.store(IDLE);
 if(!alems::reserve_idle(state,IDLE,FETCHING))return 6;
}
'''.replace('LEGACY','true' if legacy else 'false')
    src=tmp_path/'test.cpp';src.write_text(code);binary=tmp_path/'test'
    subprocess.run([shutil.which('c++'),'-std=c++17','-pthread','-I',str(header.parent),str(src),'-o',str(binary)],check=True,timeout=60)
    assert subprocess.run([str(binary)],timeout=5).returncode==(3 if legacy else 0)
def test_real_patch_keeps_selected_reservation_and_rechecks_prefetch_claim():
    patch=(ROOT/'studies/energy_diagnosis/moe/patches/moe-infinity-transfer-lifecycle.patch').read_text()
    assert '+  EVICTING = 4,' in patch
    assert '+                       (evict_expert_node = FindExpertEvict(gpu_id)) != nullptr;' in patch
    assert '+        if (!acquired) break;' in patch
    assert '+          } reservation{evict_node};' in patch
