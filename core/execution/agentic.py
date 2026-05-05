#!/usr/bin/env python3
"""
================================================================================
AGENTIC AI EXECUTOR – Multi-step LLM with tool support
================================================================================

Purpose: Implements agentic AI workflows to measure orchestration tax.
    - Plans tasks, uses tools, synthesizes results
    - Phase-level timing for scientific analysis

SCIENTIFIC NOTES:
    - Uses SAME base prompt as linear for fair comparison
    - Planning phase uses temperature=0 for reproducibility
    - Phase timing separates planning/execution/synthesis
    - Complexity score weights multiple factors with proper normalization
    - Both cloud (Groq) and local (Ollama) providers supported

Requirements:
    Req 3.1: Dual-Harness Support – local/cloud via config
    Req 3.2: Complexity-Level Logic – based on tool calls
    Req 3.6: Device Handoff Latency – phase-level timing

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
import math
import os
import socket
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from core.execution.tools.real_tools import (  # real instrumented tools
    CalculatorTool,
    DatabaseQueryTool,
    FileProcessorTool,
    WebSearchTool,
    CodeExecutorTool,
    APIQueryTool,
    ToolResult,
)
import psutil
import requests

from core.utils.debug import dprint
from core.execution.model_factory import ModelFactory

logger = logging.getLogger(__name__)


# ============================================================================
# STANDARDIZED BASE PROMPT – Same as linear for fair comparison
# ============================================================================
BASE_TASK_PROMPT = """
Task: {task}

Please provide a complete and thorough answer.
"""
# Execution status constants — used by agentic result dict and classifier
EXECUTION_STATUS_SUCCESS         = "success"
EXECUTION_STATUS_FAILURE         = "failure"
EXECUTION_STATUS_PARTIAL_FAILURE = "partial_failure"  # some steps failed, synthesis succeeded
 
 
def _detect_error_type(msg: str) -> str:
    """
    Classify a provider error message into a canonical failure type.
    Used by agentic.execute() to populate execution.error_type.
    Order matters — more specific patterns checked first.
    """
    m = msg.lower()
    if "429" in m or "too many requests" in m or "rate_limit" in m or "rate limit" in m:
        return "rate_limit"
    if "context window" in m or "exceed context" in m or "context_length" in m or "context window" in m:
        return "context_overflow"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "connection" in m or "connection refused" in m or "network" in m:
        return "api_error"
    return "api_error"

class AgenticExecutor:
    """
    Executes agentic AI workflows with tool support.

    Workflow:
        1. Planning Phase: LLM creates step-by-step execution plan
        2. Execution Phase: Each step runs (tool or LLM)
        3. Synthesis Phase: Combine all results into final answer

    Number of LLM calls = 1 (plan) + N (steps) + 1 (synthesis)
    where N is the number of steps that require LLM reasoning.

    All configuration comes from Module 0 – no hardcoding.
    Debug output controlled by A_LEMS_DEBUG environment variable.
    """

    def __init__(self, model_config: Dict[str, Any]):
        """
        Initialize executor with model configuration from Module 0.

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
                - api_key_env: Environment variable name for API key
                - model_id: Model identifier for the provider
                - max_tokens: Maximum tokens in response
                - temperature: Sampling temperature (0.0-1.0)
                - tools: List of supported tool names
        """
        self.config = model_config
        self.api_key = (
            os.getenv(self.config.get("api_key_env"))
            if self.config.get("api_key_env")
            else None
        )
        self.supported_tools = self.config.get("tools", [])
        self.max_tokens = self.config.get("max_tokens", 2048)
        self.temperature = self.config.get("temperature", 0.7)
        self.provider = self.config.get("provider", "unknown")
        self.model_path = self.config.get("model_path")
        self.call_counter = 0
        self.pending_interactions = []

        if not self.config.get("is_local", False) and self.config.get("api_key_env") and not self.api_key:
            logger.warning(f"API key missing: {self.config.get('api_key_env')}")
        # Chunk 7: resolve adapter once — factory owns all provider dispatch
        # inject resolved api_key into config so adapter finds it
        _cfg = dict(self.config)
        _cfg['_resolved_api_key'] = self.api_key
        self._adapter = ModelFactory.get_adapter(self.provider, _cfg)
        logger.info(
            f"AgenticExecutor initialized: {self.config.get('model_id')} ({self.provider}) via {self._adapter.get_name()}"
        )

    def _calculate_complexity_score(
        self, llm_calls: int, tool_calls: int, total_tokens: int
    ) -> Dict[str, float]:
        """
        Calculate weighted complexity score for orchestration tax analysis.

        LITERATURE BASIS:
        -----------------
        This metric is informed by established research in Green AI and
        computer systems:

        1. LLM calls (α factor):
            Justification: Each model invocation incurs compute and energy cost
            proportional to inference workload. Supported by:
            - Schwartz et al., "Green AI" (2020) – energy ∝ computation
            - Patterson et al., "Carbon Emissions..." (2021) – energy ∝ model runs

        2. Tool calls (β factor):
            Justification: External tool execution consumes CPU, memory, I/O.
            Supported by:
            - Hennessy & Patterson, "Computer Architecture" – energy in systems

        3. Token volume (γ factor):
            Justification: Inference compute scales with token count.
            Supported by:
            - Kaplan et al., "Scaling Laws for Neural Language Models" (2020)

        WEIGHT VALUES:
        -------------
        The weights (α=0.4, β=0.3, γ=0.3) are HEURISTIC coefficients
        inspired by literature but represent our novel contribution –
        the "Orchestration Complexity Metric" defined in this work.

        NORMALIZATION:
        -------------
        All components are normalized to [0,1] range to ensure fair contribution
        regardless of absolute scales. This follows best practices in
        composite metric design (OECD, 2008).

        Returns:
            Dictionary with:
                - raw_score: Weighted sum (0-1 range)
                - normalized_score: Scaled to 1-10 for interpretation
                - components: Individual normalized factors with citations
                - weights: The heuristic weight values used
        """
        # Maximum expected values for normalization (based on pilot experiments)
        MAX_LLM_CALLS = 10  # Upper bound: planning + up to 8 steps + synthesis
        MAX_TOOL_CALLS = 10  # Upper bound: maximum tools in complex tasks
        TOKEN_THRESHOLD = 1000  # Based on scaling laws (Kaplan et al. 2020)

        # Normalize each component to [0, 1] range (OECD composite indicator guidelines)
        normalized_llm = min(llm_calls / MAX_LLM_CALLS, 1.0)
        normalized_tools = min(tool_calls / MAX_TOOL_CALLS, 1.0)
        normalized_tokens = min(total_tokens / TOKEN_THRESHOLD, 1.0)

        # Heuristic weights (our novel contribution – not from literature)
        ALPHA = 0.4  # LLM calls weight – importance of model invocations
        BETA = 0.3  # Tool calls weight – importance of external operations
        GAMMA = 0.3  # Token volume weight – importance of computation scale

        # Calculate weighted score
        raw_score = (
            ALPHA * normalized_llm + BETA * normalized_tools + GAMMA * normalized_tokens
        )

        # Scale to 1-10 for human interpretation
        normalized_score = 1 + raw_score * 9

        return {
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "components": {
                "llm_calls": {
                    "raw": llm_calls,
                    "normalized": normalized_llm,
                    "weight": ALPHA,
                    "citation": "Schwartz et al. 2020; Patterson et al. 2021",
                },
                "tool_calls": {
                    "raw": tool_calls,
                    "normalized": normalized_tools,
                    "weight": BETA,
                    "citation": "Hennessy & Patterson, Computer Architecture",
                },
                "token_volume": {
                    "raw": total_tokens,
                    "normalized": normalized_tokens,
                    "weight": GAMMA,
                    "citation": "Kaplan et al. 2020",
                },
            },
            "weights": {"alpha": ALPHA, "beta": BETA, "gamma": GAMMA},
            "note": "Heuristic weights – novel contribution of this work",
            "literature": {
                "green_ai": "Schwartz, R., Dodge, J., Smith, N. A., & Etzioni, O. (2020). Green AI.",
                "carbon_emissions": "Patterson, D., et al. (2021). Carbon Emissions and Large Neural Network Training.",
                "scaling_laws": "Kaplan, J., et al. (2020). Scaling Laws for Neural Language Models.",
                "computer_architecture": "Hennessy, J. L., & Patterson, D. A. (2017). Computer Architecture: A Quantitative Approach.",
                "composite_indicators": "OECD (2008). Handbook on Constructing Composite Indicators.",
            },
        }

    def execute(self, task: str, planning_temperature: float = 0.0, tool_graph: list = None) -> Dict[str, Any]:
        """
        Execute agentic workflow with phase-level timing.

        Purpose:
            This is the main entry point that runs the complete agentic pipeline:
            1. Planning: LLM creates step-by-step plan (temperature=0 for reproducibility)
            2. Execution: Each step runs (tool or LLM)
            3. Synthesis: Combine all results into final answer

        Why this exists:
            - Measures energy consumption of agentic workflows (Req 3.6)
            - Determines complexity based on tool count (Req 3.2)
            - Phase timing reveals where orchestration tax is spent
            - Results used to calculate overhead vs linear AI

        Args:
            task: User query (e.g., "What is 2+2?")
            planning_temperature: Temperature for planning phase (default 0.0 for reproducibility)

        Returns:
            Dictionary with all metrics needed for energy analysis
        """
        experiment_id = str(uuid.uuid4())[:8]
        overall_start = time.time()
        total_prompt_chars = 0
        total_response_chars = 0
        call_counter = 0
        step_counter = 0

        dprint(f"\n{'#'*70}")
        dprint(f"🚀 AGENTIC EXECUTION [{experiment_id}]: {task[:100]}")
        dprint(f"{'#'*70}")

        # ====================================================================
        # Phase 1: Planning – LLM creates step-by-step plan (1 call)
        # Temperature=0 for reproducibility – same task = same plan
        # This is CRITICAL for experimental reproducibility
        # ====================================================================
        orchestration_start = time.time()
        plan_start = time.time()
        call_counter += 1
        if tool_graph:
            self._current_task_prompt = task  # store for planner resolution
            # Tier 2 task — use pre-defined graph, skip LLM planning
            # Keep args_template unresolved — execute_tool_graph resolves at step time
            steps = [
                {
                    "tool": s["tool"],
                    "args_template": s.get("args_template", {}),
                    "depends_on": s.get("depends_on", []),
                    "step": s["step"],
                }
                for s in sorted(tool_graph, key=lambda x: x["step"])
            ]
            # Ensure all graph tools are in supported_tools
            for s in tool_graph:
                if s["tool"] not in self.supported_tools:
                    self.supported_tools.append(s["tool"])
            plan = {"steps": steps}
        else:
            plan = self._create_plan(
                task, temperature=planning_temperature, call_counter=call_counter
            )
            steps = plan.get("steps", [])
        plan_end = time.time()
        planning_time_ms = (plan_end - plan_start) * 1000

        # Emit planning phase event
        self._emit_event(
            phase="planning",
            event_type="planning",
            start_time=plan_start,
            end_time=plan_end,
            metadata={
                "steps": len(steps),
                "task_preview": task[:100],
                "planning_temperature": planning_temperature,
            },
        )

        dprint(f"📋 Planning: {len(steps)} steps, {planning_time_ms:.1f}ms")

        # ====================================================================
        # Phase 2: Execution – Run each step (tool or LLM)
        # ====================================================================
        exec_start = time.time()
        step_results, tools_used = [], []
        tokens = {"prompt": 0, "completion": 0, "total": 0}
        total_llm_calls = 0
        step_counter = 0

        for i, step in enumerate(steps):
            step_counter += 1
            logger.warning("STEP %d: keys=%s tool=%s supported=%s", i, list(step.keys()), step.get("tool"), self.supported_tools)
            if step.get("tool") in self.supported_tools:
                # Tool execution – external computation, no LLM call
                # Resolve args at execution time — handles {planner.*} and {step_N_result}
                step_results_dict = {sr["step"]: sr["result"] for sr in step_results}
                args = self._resolve_step_args(
                    step.get("args_template", step.get("args", {})),
                    step_results_dict,
                    task_prompt=getattr(self, "_current_task_prompt", None),
                )
                tool_start = time.time()
                logger.warning("_execute_tool CALLED: tool=%s step=%s", step.get("tool"), step_counter)
                result = self._execute_tool(
                    step["tool"], args, step_counter
                )
                tool_end = time.time()
                step_results.append(
                    {
                        "step": i + 1,
                        "type": "tool",
                        "tool": step["tool"],
                        "result": result,
                        "time_ms": (tool_end - tool_start) * 1000,
                    }
                )
                if step["tool"] not in tools_used:
                    tools_used.append(step["tool"])
                dprint(f"  🔧 Tool {step['tool']} → {result}")
            else:
                # LLM execution – another call to the model
                call_counter += 1
                prompt = step.get("prompt", task)
                llm_start = time.time()
                llm_result = self._call_llm(
                    prompt, temperature=self.temperature, call_counter=call_counter
                )
                llm_end = time.time()
                llm_content = llm_result.get("content", "")
                step_results.append(
                    {
                        "step": i + 1,
                        "type": "llm",
                        "result": llm_content,
                        "time_ms": (llm_end - llm_start) * 1000,
                    }
                )
                if llm_content.startswith("Error:"):
                    logger.warning(
                        "LLM step %d returned provider error: %s",
                        i + 1, llm_content[:120],
                    )

                # ====================================================================
                # FIXED: Handle token counting from API response (12 spaces indentation)
                # ====================================================================
                if "usage" in llm_result:
                    usage = llm_result["usage"]
                    tokens["prompt"] += usage.get("prompt_tokens", 0)
                    tokens["completion"] += usage.get("completion_tokens", 0)
                    tokens["total"] += usage.get("total_tokens", 0)
                    print(
                        f"🔍 DEBUG - added prompt:{usage.get('prompt_tokens',0)}, completion:{usage.get('completion_tokens',0)}, total:{usage.get('total_tokens',0)}"
                    )
                    print(f"🔍 DEBUG - now tokens: {tokens}")
                elif "tokens" in llm_result:
                    # Fallback for any providers that use 'tokens' format
                    for k, v in llm_result["tokens"].items():
                        tokens[k] += v
                        print(
                            f"🔍 DEBUG - added {k}: {v}, now tokens[{k}] = {tokens[k]}"
                        )
                else:
                    logger.debug(
                        f"No token data in llm_result. Keys: {llm_result.keys()}"
                    )

                total_llm_calls += 1
                total_prompt_chars += len(prompt)
                total_response_chars += len(llm_result.get("content", ""))
                dprint(f"  🤖 LLM step {i+1} complete")

        exec_end = time.time()
        execution_time_ms = (exec_end - exec_start) * 1000
        self._emit_event(
            phase="execution",
            event_type="execution",
            start_time=exec_start,
            end_time=exec_end,
            metadata={"steps": len(steps), "tools_used": len(tools_used)},
        )        

        print(f"🔍 DEBUG - accumulated tokens: {tokens}")
        print(f"🔍 DEBUG - tokens keys: {tokens.keys()}")
        # print("🔍 DEBUG - llm_result keys:", llm_result.keys())
        # print("🔍 DEBUG - llm_result full:", llm_result)
        # ====================================================================
        # Phase 3: Synthesis – Combine all results (1 call)
        # ====================================================================
        syn_start = time.time()
        call_counter += 1
        synthesis = self._synthesize(
            task, steps, step_results, call_counter=call_counter
        )
        syn_end = time.time()
        synthesis_time_ms = (syn_end - syn_start) * 1000

        # Emit synthesis phase event
        self._emit_event(
            phase="synthesis",
            event_type="synthesis",
            start_time=syn_start,
            end_time=syn_end,
            metadata={"tokens": tokens, "has_content": bool(synthesis.get("content"))},
        )
        if "tokens" in synthesis:
            for k, v in synthesis["tokens"].items():
                tokens[k] += v
        total_llm_calls += 1  # Count synthesis call
        total_prompt_chars += len(synthesis.get("prompt", ""))
        total_response_chars += len(synthesis.get("content", ""))

        # ====================================================================
        # Req 3.2: Determine complexity based on actual tool usage
        # More tools = more complex = higher energy consumption
        # ====================================================================
        tool_count = len(tools_used)
        if tool_count <= 1:
            complexity_level = 1  # Simple: 0-1 tools (low orchestration tax)
        elif tool_count <= 3:
            complexity_level = 2  # Moderate: 2-3 tools (medium tax)
        else:
            complexity_level = 3  # Complex: 4+ tools (high tax)

        total_time_ms = (time.time() - overall_start) * 1000

        # Calculate final LLM calls: planning (1) + execution (N) + synthesis (1)
        final_llm_calls = total_llm_calls + 1  # +1 for planning call
        # ====================================================================
        # Calculate total effective throughput across all LLM calls
        # ====================================================================
        total_effective_kbps = 0
        if hasattr(self, "_effective_kbps_list") and self._effective_kbps_list:
            total_effective_kbps = sum(self._effective_kbps_list) / len(
                self._effective_kbps_list
            )
            # Sum all effective_kbps values (you'd need to track them)
            # For now, let's calculate average
            dprint(
                f"📊 Average throughput: {total_effective_kbps:.1f} kbps across {len(self._effective_kbps_list)} calls"
            )

        # Calculate orchestration CPU overhead and aggregate network metrics
        total_llm_compute_ms = 0  # This is local_compute_ms from all interactions
        total_llm_compute_ms = 0
        total_non_local_ms = 0
        total_pre_ms = 0
        total_post_ms = 0
        total_bytes_sent = 0
        total_bytes_recv = 0
        total_workflow_non_local_ms = 0
        total_tcp_retransmits = 0
        
        for interaction in self.pending_interactions:
            total_llm_compute_ms += interaction.get("local_compute_ms", 0)
            total_non_local_ms += interaction.get("non_local_ms", 0)
            total_pre_ms += interaction.get("preprocess_ms", 0)
            total_post_ms += interaction.get("postprocess_ms", 0)
            total_bytes_sent += interaction.get("bytes_sent_approx", 0)
            total_bytes_recv += interaction.get("bytes_recv_approx", 0)
            total_workflow_non_local_ms += interaction.get("non_local_ms", 0)
            total_tcp_retransmits += interaction.get("tcp_retransmits", 0)
        
        
        # Calculate effective throughput for the entire workflow
        if total_workflow_non_local_ms > 0:
            total_bytes = total_bytes_sent + total_bytes_recv
            effective_throughput_kbps = (total_bytes * 8) / (total_workflow_non_local_ms / 1000) / 1000
        else:
            effective_throughput_kbps = 0
        
        orchestration_end = time.time()
        total_orchestration_ms = (orchestration_end - orchestration_start) * 1000
        orchestration_cpu_ms = max(0,
            total_orchestration_ms
            - total_llm_compute_ms
            - total_non_local_ms
        )
 
        # Scan step results for provider errors — structured failure detection.
        # Harness always completes so energy is captured regardless of LLM errors.
        # Sets execution.status and error_type so goal_execution_manager and
        # classifier can route correctly without relying on exception path.
        step_errors = [
            sr.get("result", "")
            for sr in step_results
            if isinstance(sr.get("result", ""), str)
            and sr.get("result", "").startswith("Error:")
        ]
        failed_steps  = len(step_errors)
        total_steps   = len(step_results)
 
        if failed_steps == 0:
            execution_status = EXECUTION_STATUS_SUCCESS
            execution_error_type = None
        elif failed_steps < total_steps:
            # Some steps failed but harness continued — partial failure
            execution_status = EXECUTION_STATUS_PARTIAL_FAILURE
            # Guard against empty step_errors — _detect_error_type requires a string
            execution_error_type = _detect_error_type(step_errors[0]) if step_errors else "api_error"
        else:
            # All steps failed — classify from first error if available
            execution_status = EXECUTION_STATUS_FAILURE
            execution_error_type = _detect_error_type(step_errors[0]) if step_errors else "api_error"



        result = {
            "experiment_id": experiment_id,
            "response": synthesis.get("content", ""),
            "execution": {                                        # structured failure metadata
                "status":        execution_status,               # success|failure|partial_failure
                "error_type":    execution_error_type,           # rate_limit|timeout|api_error|context_overflow|None
                "completed":     True,                           # harness always completes — energy always captured
                "error_message": step_errors[0] if step_errors else None,
                "failed_steps":  failed_steps,
                "total_steps":   total_steps,
            },            
            "tokens": tokens,
            "llm_calls": final_llm_calls,  # CORRECT: planning + execution + synthesis
            "steps": len(steps),
            "tools_used": tools_used,
            "tool_count": tool_count,
            "tool_calls": tool_count,  # Alias for database column
            "pending_interactions": getattr(self, "pending_interactions", []),
            "complexity_level": complexity_level,  # Req 3.2
            "complexity_score": self._calculate_complexity_score(
                final_llm_calls, tool_count, tokens.get("total", 0)
            ),
            "orchestration_cpu_ms": 0, # Will be calculated after pending_interactions
             "total_bytes_sent": 0,
             "total_bytes_recv": 0,
             "total_workflow_non_local_ms": 0,
             "effective_throughput_kbps": 0,
            "phase_times": {
                "planning_ms": planning_time_ms,
                "execution_ms": execution_time_ms,
                "synthesis_ms": synthesis_time_ms,
                "total_ms": total_time_ms,
            },
            "phase_percentages": {
                "planning_pct": (
                    (planning_time_ms / total_time_ms) * 100 if total_time_ms > 0 else 0
                ),
                "execution_pct": (
                    (execution_time_ms / total_time_ms) * 100
                    if total_time_ms > 0
                    else 0
                ),
                "synthesis_pct": (
                    (synthesis_time_ms / total_time_ms) * 100
                    if total_time_ms > 0
                    else 0
                ),
            },
            "phase_ratios": {
                "planning_ratio": (
                    planning_time_ms / total_time_ms if total_time_ms > 0 else 0
                ),
                "execution_ratio": (
                    execution_time_ms / total_time_ms if total_time_ms > 0 else 0
                ),
                "synthesis_ratio": (
                    synthesis_time_ms / total_time_ms if total_time_ms > 0 else 0
                ),
            },

            "timestamps": {
                "plan_start": plan_start,
                "plan_end": plan_end,
                "exec_start": exec_start,
                "exec_end": exec_end,
                "syn_start": syn_start,
                "syn_end": syn_end,
            },
            "total_time_ms": total_time_ms,  # Req 3.6
            "prompt_chars": total_prompt_chars,
            "response_chars": total_response_chars,
            "timestamp": datetime.now().isoformat(),
            "model": self.config.get("model_id"),
            "provider": self.provider,
            "avg_effective_kbps": total_effective_kbps,
        }

        dprint(f"\n📊 Phase breakdown:")
        dprint(
            f"   Planning:  {planning_time_ms:6.1f}ms ({result['phase_percentages']['planning_pct']:.0f}%)"
        )
        dprint(
            f"   Execution: {execution_time_ms:6.1f}ms ({result['phase_percentages']['execution_pct']:.0f}%)"
        )
        dprint(
            f"   Synthesis: {synthesis_time_ms:6.1f}ms ({result['phase_percentages']['synthesis_pct']:.0f}%)"
        )
        dprint(f"   TOTAL:     {total_time_ms:6.1f}ms")
        dprint(
            f"✅ Agentic complete: {total_time_ms:.0f}ms, {tokens.get('total', 0)} tokens"
        )
        # ====================================================================
        # Calculate API latency (total time spent waiting for network)
        # ====================================================================
        total_api_latency_ms = 0
        if hasattr(self, "_api_latencies"):
            total_api_latency_ms = sum(self._api_latencies)

        # Calculate phase ratios (normalized to 0-1 for ML)
        phase_ratios = {
            "planning_ratio": (
                planning_time_ms / total_time_ms if total_time_ms > 0 else 0
            ),
            "execution_ratio": (
                execution_time_ms / total_time_ms if total_time_ms > 0 else 0
            ),
            "synthesis_ratio": (
                synthesis_time_ms / total_time_ms if total_time_ms > 0 else 0
            ),
        }

        # ====================================================================
        # Calculate waiting time (time between LLM calls)
        # ====================================================================
        waiting_time_ms = 0
        if hasattr(self, "_api_latencies") and len(self._api_latencies) > 1:
            # Waiting time = total time - sum of active phases
            # Active phases = planning + execution + synthesis + tool time
            total_active = planning_time_ms + execution_time_ms + synthesis_time_ms
            if hasattr(self, "_tool_latencies"):
                total_active += sum(self._tool_latencies)
            waiting_time_ms = max(0, total_time_ms - total_active)


        # Add to result
        result["orchestration_cpu_ms"] = orchestration_cpu_ms
        result["total_bytes_sent"] = total_bytes_sent
        result["total_bytes_recv"] = total_bytes_recv
        result["total_workflow_non_local_ms"] = total_workflow_non_local_ms
        result["effective_throughput_kbps"] = effective_throughput_kbps
        result["total_tcp_retransmits"] = total_tcp_retransmits  
        # Add to result
        result.update(
            {
                "api_latency_ms": total_api_latency_ms,
                "compute_time_ms": total_pre_ms + total_post_ms + orchestration_cpu_ms,
                "waiting_time_ms": waiting_time_ms,  # M3-9
                "avg_step_time_ms": execution_time_ms / len(steps) if steps else 0,
                "events": getattr(self, "_events", []),  # M3-10
                "tool_latencies": getattr(self, "_tool_latencies", []),  # M3-11
                "avg_tool_latency_ms": (
                    sum(self._tool_latencies) / len(self._tool_latencies)
                    if hasattr(self, "_tool_latencies") and self._tool_latencies
                    else 0
                ),
            }
        )

    

        self.pending_interactions = []
        dprint(
            f"✅ Agentic complete: {execution_time_ms:.0f}ms, {tokens.get('total', 0)} tokens"
        )
        return result

    def execute_comparison(self, task: str, tool_graph: list = None) -> Dict[str, Any]:
        """
        Execute with standardized prompt for fair comparison with linear.

        This ensures linear and agentic see semantically equivalent tasks,
        removing bias from prompt engineering.

        Args:
            task: The task to solve

        Returns:
            Same as execute() but with standardized base prompt
        """
        # Same base prompt as linear
        base = BASE_TASK_PROMPT.format(task=task)

        # Additional instruction for agentic (planning)
        planning_prompt = f"""
{base}

To solve this effectively, break it down into steps.
You can use tools like calculator or web search if needed.
"""
        return self.execute(planning_prompt, tool_graph=tool_graph)

    def _create_plan(
        self, task: str, temperature: float = 0.0, call_counter: int = None
    ) -> Dict[str, Any]:
        """
        Ask LLM to create execution plan with deterministic temperature.

        Purpose:
            This is where agentic intelligence happens – the LLM analyzes
            the task and decides what steps are needed. Linear AI skips this.

        Why this exists:
            - Planning consumes energy (Req 3.6)
            - Determines how many tools will be used (Req 3.2)
            - Temperature=0 ensures same task = same plan (reproducibility)

        Args:
            task: Original user query
            temperature: 0.0 for reproducible planning

        Returns:
            Dictionary with 'steps' array containing the execution plan
        """
        prompt = f"""
        Break this task into steps. Return JSON with "steps" array.
        Each step: {{"description": str, "type": "tool/llm", 
                   "tool": name if tool, "args": {{}} if tool,
                   "prompt": str if llm}}
        Task: {task}
        Tools: {', '.join(self.supported_tools)}
        Example: {{"steps": [{{"description": "Calculate", "type": "tool", 
                             "tool": "calculator", "args": {{"expression": "2+2"}}}}]}}
        """

        response = self._call_llm(
            prompt, temperature=temperature, call_counter=call_counter
        )
        content = response.get("content", "{}")

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            return json.loads(content.strip())
        except:
            # Fallback for when LLM fails – still return something usable
            return {"steps": [{"description": "Answer", "type": "llm", "prompt": task}]}

    def _synthesize(
        self, task: str, steps: List, results: List, call_counter: int = None
    ) -> Dict[str, Any]:
        """
        Combine step results into final answer.

        Purpose:
            Takes all the pieces from planning and execution and weaves them
            into a coherent answer that addresses the original query.

        Why this exists:
            Without synthesis, agentic AI would just return raw tool outputs.
            This step consumes energy and is part of the orchestration tax.

        Args:
            task: Original user query
            steps: The plan steps
            results: Results from executing each step

        Returns:
            Dictionary with synthesis results (content and tokens)
        """
        prompt = f"Task: {task}\nResults: {json.dumps(list(zip(steps, results)))}\nFinal answer:"
        return self._call_llm(
            prompt, temperature=self.temperature, call_counter=call_counter
        )

    def _execute_tool(self, name: str, args: Dict, step_index: int = None) -> Any:
        """
        Execute a specific tool.

        Purpose:
            Tools give agentic AI access to external capabilities that the
            model alone doesn't have (real data, computation, etc.).

        Why this exists:
            Tool execution consumes energy (Req 3.6) and contributes to the
            orchestration tax we want to measure. This function centralizes
            all tool logic so it can be easily extended.

        Args:
            name: Tool name ("calculator", "web_search", etc.)
            args: Tool-specific arguments (expression, query, etc.)

        Returns:
            Tool execution result (varies by tool)
        """
        tool_start = time.time()
 
        # Emit start event before execution — existing pipeline pattern
        self._emit_event(
            phase="execution",
            event_type="tool_call",
            start_time=tool_start,
            end_time=tool_start,
            metadata={"tool": name, "args_keys": list(args.keys()),
                      "step": step_index},
        )
 
        result = self._dispatch_tool(name, args)  # never raises
 
        tool_end = time.time()
 
        # Backfill instrumentation metadata into the event just emitted
        # _events is the in-flight list before DB flush — last entry is ours
        if hasattr(self, "_events") and self._events:
            last = self._events[-1]
            last["end_time_ns"] = int(tool_end * 1e9)
            last["duration_ns"] = int((tool_end - tool_start) * 1e9)
            last["metadata"].update({
                "tool_name":            name,
                "success":              result.success,
                "io_bytes_read":        result.io_bytes_read,
                "io_bytes_written":     result.io_bytes_written,
                "input_payload_hash":   result.input_payload_hash,
                "output_payload_hash":  result.output_payload_hash,
                "cpu_time_ns":          result.cpu_time_ns,
                "memory_delta_kb":      result.memory_delta_kb,
                "result_rows":          result.row_count,
                "result_preview":       str(result.result)[:200],
                "error":                result.error,
            })
 
        # Return raw result on success, None on failure so caller can handle
        return result.result if result.success else None
 
    def _dispatch_tool(self, name: str, args: Dict) -> ToolResult:
        """
        Route tool name to real implementation.
        Instantiated per-call — tools are stateless execution primitives.
        Never raises — returns ToolResult(success=False) on unknown tool.
        db_path passed to DatabaseQueryTool so it queries live experiments DB.
        """
        db_path = getattr(self, "db_path", "data/experiments.db")
        tool_map = {
            "calculator":     CalculatorTool(),
            "database_query": DatabaseQueryTool(db_path),
            "file_processor": FileProcessorTool(),
            "web_search":     WebSearchTool(),
            "code_executor":  CodeExecutorTool(),
            "api_query":      APIQueryTool(),
        }
        tool = tool_map.get(name)
        if not tool:
            logger.warning("Unknown tool requested: %s", name)
            return ToolResult(
                success=False, result=None,
                tool_name=name, duration_ns=0,
                error=f"Unknown tool: {name}",
            )
 
        # Tool failure injection — fires after harness starts so energy is captured.
        # failure_injector is passed into AgenticExecutor at construction time
        # when experiment_type is failure_injection or retry_study.
        # maybe_inject_tool_failure() requires tool_name for deterministic seeding.
        _injector = getattr(self, "failure_injector", None)
        if _injector and _injector.is_active():
            if _injector.maybe_inject_tool_failure(
                tool_name=name,
                rep_num=getattr(self, "_current_run_id", 1),
                attempt_num=getattr(self, "_current_attempt", 1),
            ):
                logger.info("FailureInjector: tool failure injected for %s", name)
                return ToolResult(
                    success=False, result=None,
                    tool_name=name, duration_ns=0,
                    error=f"INJECTED: simulated tool failure for {name}",
                )
 
        try:
            return tool.execute(**args)
        except Exception as exc:
            logger.warning("Tool %s raised unexpectedly: %s", name, exc)
            return ToolResult(
                success=False, result=None,
                tool_name=name, duration_ns=0,
                error=str(exc),
            )
 
    def execute_tool_graph(
        self,
        graph: list,
        step_results: dict,
        failure_injector=None,
    ) -> dict:
        """
        Execute tool graph respecting dependency order.
 
        PAPER JUSTIFICATION: Steps declared as parallel (depends_on=[])
        execute sequentially in our instrumentation environment. This design
        ensures precise per-tool energy attribution without interference
        between concurrent processes. We model and report this as sequential
        orchestration overhead — conservative, because real parallel execution
        would show lower wall-clock time but identical per-tool energy.
 
        Args:
            graph: list of step dicts from task tool_graph config
            step_results: dict to accumulate {step_N: result} — modified in place
            failure_injector: optional FailureInjector instance for tg_error_recovery
 
        Returns:
            step_results dict with all completed step outputs.
        """
        # Sort by step number so dependency order is always respected
        sorted_steps = sorted(graph, key=lambda s: s["step"])
 
        for step in sorted_steps:
            step_num = step["step"]
            tool_name = step["tool"]
            deps = step.get("depends_on", [])
 
            # All dependencies must be completed before this step runs
            for dep in deps:
                if dep not in step_results:
                    logger.warning(
                        "Step %d dependency step_%d not in results — skipping",
                        step_num, dep,
                    )
                    step_results[step_num] = None
                    continue
 
            # Resolve args — substitute step results into template placeholders
            args = self._resolve_step_args(
                step.get("args_template", {}), step_results,
                task_prompt=getattr(self, "_current_task_prompt", None)
            )
 
            # Optional failure injection for tg_error_recovery task
            if failure_injector is not None:
                inj = step.get("failure_injection", {})
                if inj.get("step") == step_num:
                    import random
                    if random.random() < inj.get("rate", 0.0):
                        logger.info(
                            "Failure injected at step %d per task config", step_num
                        )
                        step_results[step_num] = None
                        continue
 
            result = self._execute_tool(tool_name, args, step_index=step_num)
            step_results[step_num] = result
 
        return step_results
 
    def _resolve_step_args(self, template: dict, step_results: dict,
                           task_prompt: str = None) -> dict:
        """
        Substitute placeholders in args template.
        Three placeholder types:
          {step_N_result}           — prior tool output (pipeline chaining)
          {planner.generate_*}      — LLM generates value from task prompt
          static values             — used as-is (deterministic benchmark mode)
        """
        resolved = {}
        for key, val in template.items():
            if isinstance(val, str):
                # Step result chaining
                for step_num, step_result in step_results.items():
                    placeholder = f"{{step_{step_num}_result}}"
                    if placeholder in val and step_result is not None:
                        val = val.replace(placeholder, str(step_result))
                # Planner placeholder — call LLM to generate value
                if "{planner." in val and task_prompt:
                    planner_prompt = (
                        f"Generate ONLY a raw {key} value for this task:\n"
                        f"{task_prompt}\n\n"
                        f"Rules:\n"
                        f"- No explanation, no markdown, no code fences\n"
                        f"- Raw value only — one line\n"
                        f"- For SQL: use only these tables: runs, experiments, goal_execution, goal_attempt\n"
                        f"- For SQL: energy column is pkg_energy_uj, workflow type is workflow_type\n"
                    )
                    llm_result = self._call_llm(planner_prompt, temperature=0.0)
                    raw = llm_result.get("content", "").strip()
                    import re as _re
                    generated = _re.sub(r"```[a-z]*\n?", "", raw).replace("```", "").strip()
                    generated = generated.split("\n")[0].strip()
                    logger.debug("Planner resolved %s=%r for key=%s", val, generated, key)
                    val = generated
            resolved[key] = val
        return resolved

    def _call_llm(
        self, prompt: str, temperature: Optional[float] = None, call_counter: int = None
    ) -> Dict[str, Any]:
        """
        Make actual API call to the LLM provider.

        Purpose:
            This is the core communication layer with the LLM API.
            Handles both cloud (Groq) and local (Ollama) providers.

        Why this exists:
            - Counts LLM calls for energy analysis (Req 3.6)
            - Tracks token usage for cost and energy estimation
            - Centralizes error handling
            - Supports different temperatures for planning vs execution

        Args:
            prompt: The prompt text to send to the LLM
            temperature: 0.0 for planning (reproducible), 0.7 for execution

        Returns:
            Dictionary with:
                - 'content': The model's response text
                - 'tokens': Dict with prompt/completion/total token counts
        """
        # Track calls for this execution
        # Initialize call tracking
        if not hasattr(self, "_call_count"):
            self._call_count = 0
            self._api_latencies = []
            self._cpu_samples = []
            self._effective_kbps_list = []
 
        self._call_count += 1
        temp = temperature if temperature is not None else self.temperature
 
        dprint(f"\n{'='*50}")
        dprint(f"📨 LLM #{self._call_count} (temp={temp}, {len(prompt)} chars)")
        dprint(f"{'='*50}")
 
        if not self.config.get("is_local", False) and self.config.get("api_key_env") and not self.api_key:
            logger.error("No API key available")
            return {"content": "Error: No API key", "tokens": {}}
 
        try:
            result              = self._adapter.call(prompt, temp)
            content             = result["content"]
            tokens              = result["tokens"]
            total_time_ms       = result["total_time_ms"]
            phase_metrics       = result["phase_metrics"]
            preprocess_ms       = phase_metrics["preprocess_ms"]
            non_local_ms        = phase_metrics["non_local_ms"]
            local_compute_ms    = phase_metrics["local_compute_ms"]
            postprocess_ms      = phase_metrics["postprocess_ms"]
            app_throughput_kbps = phase_metrics["app_throughput_kbps"]
            cpu_percent_during_wait = phase_metrics["cpu_percent_during_wait"]
            bytes_sent          = result.get("bytes_sent", 0)
            bytes_recv          = result.get("bytes_recv", 0)
            tcp_retransmits     = result.get("tcp_retransmits", 0)
 
            self._api_latencies.append(total_time_ms)
            self._effective_kbps_list.append(app_throughput_kbps)
 
            interaction = {
                "step_index":               call_counter if call_counter is not None else self._call_count,
                "workflow_type":            "agentic",
                "prompt":                   prompt,
                "response":                 content,
                "model_name":               self.config.get("model_id", "unknown"),
                "provider":                 self.provider,
                "prompt_tokens":            tokens.get("prompt", 0),
                "completion_tokens":        tokens.get("completion", 0),
                "total_tokens":             tokens.get("total", 0),
                "total_time_ms":            total_time_ms,
                "preprocess_ms":            preprocess_ms,
                "non_local_ms":             non_local_ms,
                "local_compute_ms":         local_compute_ms,
                "postprocess_ms":           postprocess_ms,
                "app_throughput_kbps":      app_throughput_kbps,
                "bytes_sent_approx":        bytes_sent,
                "bytes_recv_approx":        bytes_recv,
                "tcp_retransmits":          tcp_retransmits,
                "cpu_percent_during_wait":  cpu_percent_during_wait,
                # Chunk 4: streaming latency — None for non-streaming adapters
                "ttft_ms":             phase_metrics.get("ttft_ms"),
                "tpot_ms":             phase_metrics.get("tpot_ms"),
                "token_throughput":    phase_metrics.get("token_throughput"),
                "streaming_enabled":   phase_metrics.get("streaming_enabled", 0),
                "first_token_time_ns": phase_metrics.get("first_token_time_ns"),
                "last_token_time_ns":  phase_metrics.get("last_token_time_ns"), 
                "request_start_ns":    phase_metrics.get("request_start_ns"),               
                "status":                   "success",
            }
 
            if not hasattr(self, "pending_interactions"):
                self.pending_interactions = []
            self.pending_interactions.append(interaction)
 
            return {
                "content":                  content,
                "tokens":                   tokens,
                "total_time_ms":            total_time_ms,
                "preprocess_ms":            preprocess_ms,
                "non_local_ms":             non_local_ms,
                "local_compute_ms":         local_compute_ms,
                "postprocess_ms":           postprocess_ms,
                "app_throughput_kbps":      app_throughput_kbps,
                "bytes_sent_approx":        bytes_sent,
                "bytes_recv_approx":        bytes_recv,
                "tcp_retransmits":          tcp_retransmits,
                "cpu_percent_during_wait":  cpu_percent_during_wait,
                "pending_interactions":     self.pending_interactions.copy(),
            }
 
        except Exception as e:
            logger.error("Adapter call failed in agentic: %s", e)
            if not hasattr(self, "pending_interactions"):
                self.pending_interactions = []
            interaction = {
                "step_index":           call_counter if call_counter is not None else self._call_count,
                "workflow_type":        "agentic",
                "prompt":               prompt,
                "response":             f"ERROR: {e}",
                "model_name":           self.config.get("model_id", "unknown"),
                "provider":             self.provider,
                "prompt_tokens":        0,
                "completion_tokens":    0,
                "total_tokens":         0,
                "total_time_ms":        0,
                "preprocess_ms":        0,
                "non_local_ms":         0,
                "local_compute_ms":     0,
                "postprocess_ms":       0,
                "app_throughput_kbps":  0,
                "bytes_sent_approx":    0,
                "bytes_recv_approx":    0,
                "tcp_retransmits":      0,
                "cpu_percent_during_wait": 0,
                # Chunk 4: no streaming data on error path
                "ttft_ms":             None,
                "tpot_ms":             None,
                "token_throughput":    None,
                "streaming_enabled":   0,
                "first_token_time_ns": None,
                "last_token_time_ns":  None,
                "request_start_ns":    None,
                "error_message":        str(e),
                "error_type":           _detect_error_type(str(e)),
                "status":               "failure",
            }
            self.pending_interactions.append(interaction)
            return {
                "content":              f"Error: {e}",
                "tokens":               {},
                "total_time_ms":        0,
                "preprocess_ms":        0,
                "non_local_ms":         0,
                "local_compute_ms":     0,
                "postprocess_ms":       0,
                "app_throughput_kbps":  0,
                "bytes_sent_approx":    0,
                "bytes_recv_approx":    0,
                "tcp_retransmits":      0,
                "cpu_percent_during_wait": 0,
                "pending_interactions": self.pending_interactions.copy(),
            }


    def _emit_event(
        self,
        phase: str,
        event_type: str,
        start_time: float,
        end_time: float,
        metadata: Dict = None,
    ) -> None:
        """
        Emit an orchestration event for tax attribution.

        Args:
            phase: 'planning', 'execution', 'synthesis'
            event_type: 'llm_call', 'tool_call', 'waiting', etc.
            start_time: Start timestamp
            end_time: End timestamp
            metadata: Additional event data
        """
        if not hasattr(self, "_events"):
            self._events = []

        event = {
            "phase": phase,
            "event_type": event_type,
            "start_time_ns": int(start_time * 1e9),
            "end_time_ns": int(end_time * 1e9),
            "duration_ns": int((end_time - start_time) * 1e9),
            "metadata": metadata or {},
        }
        self._events.append(event)
        dprint(f"📝 Event: {phase}.{event_type} ({event['duration_ns']/1e6:.2f}ms)")
        print(f"🔔 EVENT CREATED: {phase}.{event_type}")
