"""A required GPU compiler must not silently fall back or be swapped by dependencies."""
import os
from pathlib import Path
import subprocess


ENV = Path(__file__).resolve().parents[1] / 'slurm/env.sh'


def load(module):
    return subprocess.run(['bash', '-c', 'set -eu; source "$1"; ' + module + '; load_modules; echo READY', 'test', str(ENV)],
                          env={**os.environ, 'SCRATCH': '/tmp', 'CUDA_MODULE': 'cuda/12.9'},
                          capture_output=True, text=True)


def test_requested_cuda_module_is_loaded_and_retained():
    r = load('module() { printf "%s\\n" "$*"; return 0; }')
    assert r.returncode == 0 and 'load StdEnv/2023 python/3.11 gcc cuda/12.9' in r.stdout
    assert 'is-loaded cuda/12.9' in r.stdout and 'READY' in r.stdout


def test_missing_requested_cuda_does_not_fall_back():
    r = load('module() { printf "%s\\n" "$*"; if [[ "$*" == *cuda/12.9* ]]; then return 7; fi; }')
    assert r.returncode != 0 and 'READY' not in r.stdout
    assert 'load python/3.11\n' not in r.stdout


def test_dependency_cannot_silently_replace_cuda():
    r = load('module() { if [[ "$1" == is-loaded ]]; then return 1; fi; return 0; }')
    assert r.returncode != 0 and 'Required CUDA module was replaced' in r.stderr


def parsers(model):
    r = subprocess.run(['bash', '-c', 'source "$1"; echo "$TOOL_PARSER|$REASONING_PARSER|$NATIVE_LEN|$WS_THINKING"',
                        'test', str(ENV)],
                       env={k: v for k, v in os.environ.items()
                            if k not in ('TOOL_PARSER', 'REASONING_PARSER', 'NATIVE_LEN', 'WS_THINKING')}
                       | {'SCRATCH': '/tmp', 'MODEL_ID': model}, capture_output=True, text=True)
    return r.stdout.strip()


def test_parsers_follow_the_model_family():
    assert parsers('Qwen/Qwen3-30B-A3B-FP8') == 'hermes|qwen3|32768|1'
    # no thinking at all, trained on 256k: no reasoning parser, so tool_choice=required is structured output
    assert parsers('Qwen/Qwen3-30B-A3B-Instruct-2507-FP8') == 'hermes||262144|0'
    # Harmony, and its own YaRN up to 128k (start_vllm.sh must not add another)
    assert parsers('openai/gpt-oss-120b') == 'openai|openai_gptoss|131072|1'
