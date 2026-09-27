"""Measure how many paragraphs this machine should translate at once, and how fast.

One llama-server is started with the maximum number of slots, then the calibration
paragraphs are sent 1, 2, 4… at a time. The smallest setting within 5% of the best
throughput wins: more slots cost memory for little gain.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from .engine import Engine, EngineConfig, make_translator

GPU_LEVELS = [1, 2, 4, 6, 8]
CPU_LEVELS = [1, 2]
GOOD_ENOUGH = 0.95

# Written for Ratica (public domain), so no copyrighted text is ever needed for the test.
CALIBRATION = [
    "A hash table stores values under keys. When a program asks for a key, the table runs a hash function on "
    "it and jumps straight to the bucket where the value should be, so a lookup takes about the same time no "
    "matter how many items the table holds.",
    "Two different keys can end up in the same bucket. This is called a collision. Most tables handle it by "
    "keeping a short list in each bucket, or by probing the next free slot until an empty one is found.",
    "As a table fills up, collisions become more common and lookups slow down. To avoid this, the table grows "
    "when it reaches a certain load factor: it allocates a larger array and moves every item to its new place. "
    "This is slow once, but rare.",
    "Version control systems record every change made to a set of files. Developers can compare versions, "
    "find out who changed a line and why, and return to an earlier state when a new change breaks something "
    "that used to work.",
    "A compiler reads source code and turns it into instructions that a processor can run. Before it produces "
    "any output, it checks the program for errors, such as a missing bracket or a variable that was never "
    "declared, and reports them to the programmer.",
    "Unit tests check small pieces of a program in isolation. Each test prepares some input, calls one "
    "function and compares the result with the expected value. A good test suite runs in seconds and is "
    "executed after every change, before the code is shared.",
    "Networks split data into small packets. Each packet travels on its own and may take a different route. "
    "The receiving computer puts the packets back in order and asks the sender to repeat any that were lost "
    "on the way.",
    "Memory that a program no longer uses must be given back, or the program slowly consumes all available "
    "memory. Some languages ask the programmer to free memory by hand, while others use a garbage collector "
    "that finds and frees unused objects automatically.",
]
CALIBRATION_WORDS = sum(len(p.split()) for p in CALIBRATION)
SHORT = ["Learning objectives", "Chapter summary", "Exercises", "Key terms", "Check your understanding",
         "Further reading", "True or false?", "Try it yourself"]


def pick_slots(throughput: dict[int, float]) -> int:
    best = max(throughput.values())
    return min(k for k, v in throughput.items() if v >= GOOD_ENOUGH * best)


def measure(cfg: EngineConfig, target: str = "tr", levels=None, log_path=None, on_step=None) -> dict:
    """Return {"slots": best, "words_per_second": ..., "throughput": {slots: words/s}}."""
    levels = levels or (GPU_LEVELS if cfg.gpu else CPU_LEVELS)
    cfg = EngineConfig(**{**cfg.__dict__, "slots": max(levels)})
    throughput = {}
    with Engine(cfg, log_path=log_path) as engine:
        translate = make_translator(engine.url, "en", target)
        with ThreadPoolExecutor(max(levels)) as pool:
            list(pool.map(translate, CALIBRATION[:max(levels)]))  # warm-up: compiles GPU kernels once
            for k in levels:
                # The whole calibration set (and at least two rounds of k) per level: short runs are too noisy.
                texts = (CALIBRATION * 2)[: max(len(CALIBRATION), 2 * k)]
                t0 = time.perf_counter()
                with ThreadPoolExecutor(k) as level_pool:
                    list(level_pool.map(translate, texts))
                words = sum(len(p.split()) for p in texts)
                throughput[k] = words / (time.perf_counter() - t0)
                if on_step:
                    on_step(k, throughput[k])
            slots = pick_slots(throughput)
            # Fixed cost per request: books are full of headings, list items and captions.
            shorts = SHORT * 2
            t0 = time.perf_counter()
            with ThreadPoolExecutor(slots) as level_pool:
                list(level_pool.map(translate, shorts))
            per_block = (time.perf_counter() - t0) / len(shorts)
    return {"slots": slots, "words_per_second": throughput[slots], "throughput": throughput,
            "seconds_per_block": per_block}
