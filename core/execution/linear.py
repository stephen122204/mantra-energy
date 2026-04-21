#!/usr/bin/env python3
"""
================================================================================
LINEAR AI EXECUTOR – Single LLM call, no tools
================================================================================

Purpose: Implements linear AI workflows as the baseline for measuring 
         orchestration tax. Single LLM call with no tool usage.

Why this exists:
    Linear AI is the CONTROL case for experiments. By comparing its energy
    consumption against agentic AI, we can quantify the "orchestration tax" –
    the additional energy overhead of planning, tool use, and synthesis.

SCIENTIFIC NOTES:
    - This executor uses a STANDARDIZED prompt format identical to agentic's
      base prompt to ensure fair comparison.
    - All timestamps are recorded for precise energy alignment.
    - Both cloud (Groq) and local (Ollama) providers are supported.

Requirements:
    Req 3.1: Dual-Harness Support – local/cloud via config
    Req 3.6: Device Handoff Latency – exact start/end timestamps

Author: Deepak Panigrahy
================================================================================
"""

import os
import time
import uuid
import psutil
import socket
import logging
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import json

from core.utils.debug import dprint
from core.execution.model_factory import ModelFactory

logger = logging.getLogger(__name__)


# ============================================================================
# STANDARDIZED PROMPT for fair comparison with agentic
# Same base prompt used by both executors
# ============================================================================
BASE_TASK_PROMPT = """
Task: {task}

Please provide a complete and thorough answer.
"""


class LinearExecutor:
    """
    Executes a single LLM call (linear workflow) with no tools.
    
    This is the baseline case for orchestration tax experiments:
    - One system prompt
    - One user message
    - One synchronous API call
    - Direct answer – no tool calls, no loops, no agent reasoning
    
    Its energy profile is the reference against which agentic overhead is measured.
    All configuration comes from Module 0 – no hardcoding.
    Debug output controlled by A_LEMS_DEBUG environment variable.
    """

    def __init__(self, model_config: Dict[str, Any]):
        """
        Initialize linear executor with model configuration from Module 0.
        
        Purpose:
            Load all settings from config files so the executor can work with
            different models (local/cloud) without code changes.
            
        Why this exists:
            Req 3.1 requires supporting both local and cloud models.
            All configuration comes from Module 0's models.json.
            
        Args:
            model_config: Dictionary containing:
                - provider: "groq", "anthropic", "openai", "ollama", etc.
                - api_endpoint: URL for API calls
                - api_key_env: Environment variable name for API key (cloud only)
                - model_id: Model identifier for the provider
                - max_tokens: Maximum tokens in response
                - temperature: Sampling temperature (0.0-1.0)
        """
        self.config = model_config
        self.api_key = os.getenv(self.config.get('api_key_env')) if self.config.get('api_key_env') else None
        self.max_tokens = self.config.get('max_tokens', 1024)
        self.temperature = self.config.get('temperature', 0.7)
        self.provider = self.config.get('provider', 'unknown')
        self.model_path = self.config.get('model_path')
        
        # ====================================================================
        # Performance optimization: Cache for local model
        # ====================================================================
        self._llm = None
        self._effective_kbps_list = []
        # inject resolved api_key into config so adapter finds it
        _cfg = dict(self.config)
        _cfg['_resolved_api_key'] = self.api_key
        self._adapter = ModelFactory.get_adapter(self.provider, _cfg)
        
        
        if not self.config.get("is_local", False) and self.config.get("api_key_env") and not self.api_key:
            error = "API key not found"
            logger.error(f"No API key available for {self.provider}")

    # =========================================================================
    # MAIN EXECUTION ENTRY POINT
    # =========================================================================
    def execute(self, prompt: str, temperature: Optional[float] = None) -> Dict[str, Any]:
        """
        Execute a single LLM call with precise timing and comprehensive metrics.
        
        Architecture:
            1. Validate request and capture pre-execution state
            2. Execute provider-specific API call
            3. Capture post-execution metrics (network, timing)
            4. Build interaction record (always, even on failure)
            5. Construct unified result dictionary
        
        Args:
            prompt: User query or task description
            temperature: Optional temperature override
            
        Returns:
            Dictionary with complete execution metrics
        """
        experiment_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # ====================================================================
        # Step 1: Validate request and get effective temperature
        # ====================================================================
        error, effective_temp = self._validate_request(temperature)
        
        # ====================================================================
        # Step 2: Capture pre-request network state (always)
        # ====================================================================
        net_before = {}
        
        dprint(f"\n{'='*60}")
        dprint(f"🚀 LINEAR EXECUTION [{experiment_id}]: {prompt[:100]}...")
        dprint(f"{'='*60}")
        
        # ====================================================================
        # Step 3: Execute provider-specific API call
        # ====================================================================
        content, tokens, api_latency_ms, prompt_bytes, response_bytes, effective_kbps, error = \
            self._execute_provider(prompt, effective_temp, error)
        # Get phase metrics for accurate local CPU time
     

        # ====================================================================
        # Step 4: Calculate post-execution metrics (always, even on failure)
        # ====================================================================
        end_time = time.time()
        execution_time_ms = (end_time - start_time) * 1000
        
        # Network metrics - always calculate
        # network metrics now captured inside adapter and stored in _current_llm_metrics
        _r = getattr(self, '_last_adapter_result', {})
        net_metrics = {
            'bytes_sent':      _r.get('bytes_sent', 0),
            'bytes_recv':      _r.get('bytes_recv', 0),
            'tcp_retransmits': _r.get('tcp_retransmits', 0),
        }
        
        # Safe compute time (never negative due to clock jitter)
        phase_metrics = getattr(self, '_current_llm_metrics', {})
        preprocess_ms = phase_metrics.get('preprocess_ms', 0)
        postprocess_ms = phase_metrics.get('postprocess_ms', 0)
        compute_time_ms = preprocess_ms + postprocess_ms   
        
        # Update throughput rolling average
        avg_effective_kbps = self._update_throughput(effective_kbps)
        
        # Safe content handling
        response_content = content if content is not None else ""
        status = "success" if error is None else "failure"
        
        # ====================================================================
        # Step 5: Build interaction record (ALWAYS, even on failure)
        # ====================================================================
        interaction = self._build_interaction(
            prompt=prompt,
            response=response_content,
            tokens=tokens,
            api_latency_ms=api_latency_ms,
            effective_kbps=effective_kbps,
            compute_time_ms=compute_time_ms,
            net_metrics=net_metrics,
            error=error,
            status=status
        )
        
        # Store in pending interactions list
        if not hasattr(self, 'pending_interactions'):
            self.pending_interactions = []
        self.pending_interactions.append(interaction)
        
        # ====================================================================
        # Step 6: Build unified result dictionary (ONE schema for all cases)
        # ====================================================================
        result = self._build_result(
            experiment_id=experiment_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            response=response_content,
            tokens=tokens,
            error=error,
            execution_time_ms=execution_time_ms,
            api_latency_ms=api_latency_ms,
            compute_time_ms=compute_time_ms,
            effective_kbps=effective_kbps,
            avg_effective_kbps=avg_effective_kbps,
            interaction=interaction,
            net_metrics=net_metrics,
            prompt=prompt,
            prompt_bytes=prompt_bytes,
            response_bytes=response_bytes
        )
        
        # Clear for next run
        self.pending_interactions = []
        
        dprint(f"✅ Linear complete: {execution_time_ms:.0f}ms, {tokens.get('total', 0)} tokens")
        return result

    def execute_comparison(self, task: str) -> Dict[str, Any]:
        """
        Execute with standardized prompt for fair comparison with agentic.
        
        This ensures linear and agentic see semantically equivalent tasks,
        removing bias from prompt engineering.
        
        Args:
            task: The task to solve
            
        Returns:
            Same as execute() but with standardized prompt
        """
        prompt = BASE_TASK_PROMPT.format(task=task)
        return self.execute(prompt)

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _validate_request(self, temperature: Optional[float]) -> Tuple[Optional[str], float]:
        """
        Validate the request and return effective temperature.
        
        Returns:
            Tuple of (error, effective_temperature)
        """
        error = None
        if not self.config.get("is_local", False) and self.config.get("api_key_env") and not self.api_key:
            error = "API key not found"
            logger.error(f"No API key available for {self.provider}")
        
        effective_temp = temperature if temperature is not None else self.temperature
        return error, effective_temp

    def _execute_provider(self, prompt: str, temp: float, current_error: Optional[str]) -> Tuple:
        """
        Execute provider-specific API call.
        
        Returns:
            Tuple of (content, tokens, api_latency_ms, prompt_bytes, 
                     response_bytes, effective_kbps, error)
        """
        # Chunk 7: delegate to adapter — no provider if/else here
        prompt_bytes = len(prompt.encode('utf-8'))
        if current_error is not None:
            return None, {}, 0, prompt_bytes, 0, 0, current_error
 
        dprint(f"📨 Calling {self.provider} adapter (temp={temp})...")
        error = None
        try:
            result          = self._adapter.call(prompt, temp)
            content         = result["content"]
            tokens          = result["tokens"]
            api_latency_ms  = result["total_time_ms"]
            response_bytes  = len(content.encode("utf-8"))
            effective_kbps  = result["phase_metrics"]["app_throughput_kbps"]
            # preserve _current_llm_metrics shape — harness reads at line 165
            self._current_llm_metrics = result["phase_metrics"]
            self._last_adapter_result = result
        except Exception as e:
            error = str(e)
            logger.error("Adapter call failed: %s", e)
            content, tokens, api_latency_ms = None, {}, 0
            response_bytes, effective_kbps  = 0, 0
            self._current_llm_metrics       = {}
 
        return content, tokens, api_latency_ms, prompt_bytes, response_bytes, effective_kbps, error


    def _compute_throughput(self, prompt_bytes: int, response_bytes: int, latency_ms: float) -> float:
        """
        Compute effective throughput in kbps.
        
        Formula: (total_bytes * 8) / (latency_seconds) / 1000
        
        Args:
            prompt_bytes: Size of prompt in bytes
            response_bytes: Size of response in bytes
            latency_ms: API latency in milliseconds
            
        Returns:
            Throughput in kbps (0 if latency_ms <= 0)
        """
        if latency_ms <= 0:
            return 0
        
        total_bytes = prompt_bytes + response_bytes
        latency_seconds = latency_ms / 1000
        return (total_bytes * 8) / latency_seconds / 1000

    def _update_throughput(self, kbps: float) -> float:
        """
        Update rolling average of throughput.
        
        Maintains a bounded list of the last 100 throughput values
        to compute a rolling average without memory leaks.
        
        Args:
            kbps: Current throughput value
            
        Returns:
            Current rolling average (or 0 if no values)
        """
        if kbps <= 0:
            return 0
        
        # ====================================================================
        # Append to bounded list (keep last 100)
        # ====================================================================
        self._effective_kbps_list.append(kbps)
        self._effective_kbps_list = self._effective_kbps_list[-100:]
        
        return sum(self._effective_kbps_list) / len(self._effective_kbps_list)

    def _build_interaction(self, prompt: str, response: str, tokens: Dict,
                          api_latency_ms: float, effective_kbps: float,
                          compute_time_ms: float, net_metrics: Dict,
                          error: Optional[str], status: str) -> Dict:
        """
        Build interaction record for LLM interaction table.
        
        This record is ALWAYS created, even on failure, to avoid dataset bias.
        """
        # Get phase metrics from the latest call
        phase_metrics = getattr(self, '_current_llm_metrics', {})
        
        return {
            'step_index': 1,
            'workflow_type': 'linear',
            'status': status,
            'prompt': prompt,
            'response': response if error is None else f"Error: {error}",
            'model_name': self.config.get('model_id'),
            'provider': self.provider,
            'prompt_tokens': tokens.get('prompt', 0) if error is None else 0,
            'completion_tokens': tokens.get('completion', 0) if error is None else 0,
            'total_tokens': tokens.get('total', 0) if error is None else 0,
            'api_latency_ms': api_latency_ms,
            'app_throughput_kbps': effective_kbps,
            'bytes_sent_approx': net_metrics['bytes_sent'],
            'bytes_recv_approx': net_metrics['bytes_recv'],
            'tcp_retransmits': net_metrics['tcp_retransmits'],
            "total_bytes_sent": net_metrics['bytes_sent'],
            "total_bytes_recv": net_metrics['bytes_recv'],
            "total_tcp_retransmits": net_metrics['tcp_retransmits'],
            'error': error,
            'compute_time_ms': compute_time_ms,
            'local_compute_ms': phase_metrics.get('local_compute_ms', 0),
            # New phase metrics
            'total_time_ms': phase_metrics.get('total_time_ms', 0),
            'preprocess_ms': phase_metrics.get('preprocess_ms', 0),
            'non_local_ms': phase_metrics.get('non_local_ms', 0),
            'postprocess_ms': phase_metrics.get('postprocess_ms', 0),
            'cpu_percent_during_wait': phase_metrics.get('cpu_percent_during_wait', 0),
            # Chunk 4: streaming latency — None for non-streaming adapters
            'ttft_ms':             phase_metrics.get('ttft_ms'),
            'tpot_ms':             phase_metrics.get('tpot_ms'),
            'token_throughput':    phase_metrics.get('token_throughput'),
            'streaming_enabled':   phase_metrics.get('streaming_enabled', 0),
            'first_token_time_ns': phase_metrics.get('first_token_time_ns'),
            'last_token_time_ns':  phase_metrics.get('last_token_time_ns'),            
        }

    def _build_result(self, experiment_id: str, start_time: float, end_time: float,
                     status: str, response: str, tokens: Dict, error: Optional[str],
                     execution_time_ms: float, api_latency_ms: float, compute_time_ms: float,
                     effective_kbps: float, avg_effective_kbps: float,
                     interaction: Dict, net_metrics: Dict, prompt: str,
                     prompt_bytes: int, response_bytes: int) -> Dict:
        """
        Build unified result dictionary with ONE schema for all cases.
        
        This ensures consistent data structure regardless of success/failure.
        """
        return {
            "experiment_id": experiment_id,
            "start_time": start_time,
            "end_time": end_time,
            "status": status,
            "response": response if error is None else f"Error: {error}",
            "tokens": tokens if error is None else {},
            "error": error,
            "execution_time_ms": execution_time_ms,
            "api_latency_ms": api_latency_ms,
            "compute_time_ms": compute_time_ms,
            "effective_kbps": effective_kbps,
            "avg_effective_kbps": avg_effective_kbps,
            "pending_interactions": [interaction],
            "bytes_sent": net_metrics['bytes_sent'],
            "bytes_recv": net_metrics['bytes_recv'],
            "tcp_retransmits": net_metrics['tcp_retransmits'],
            "total_bytes_sent": net_metrics['bytes_sent'],
            "total_bytes_recv": net_metrics['bytes_recv'],
            "total_tcp_retransmits": net_metrics['tcp_retransmits'],
            "prompt_chars": len(prompt),
            "response_chars": len(response),
            "prompt_bytes": prompt_bytes,
            "response_bytes": response_bytes,
            "timestamp": datetime.now().isoformat(),
            "model": self.config.get('model_id'),
            "provider": self.provider
        }