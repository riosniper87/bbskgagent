#!/usr/bin/env bash
# Run on the DGX Spark. int8 weights for the 26B-A4B MoE fit comfortably in the 128GB
# unified pool, leaving room for KV cache. Keep concurrency low (Spark is a small-batch box).
set -euo pipefail
vllm serve google/gemma-4-26B-A4B-it \
  --quantization int8_per_channel_weight_only \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 4 \
  --port 8000
