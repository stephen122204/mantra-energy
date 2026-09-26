"""HF transformers eager, batch 1, greedy, forced length. Writes per-generation token timestamps
(CLOCK_MONOTONIC ns, the same clock as sampler.py). No measurement code runs inside the decode loop beyond
recording a timestamp when generate() hands each token to the streamer.

    python hf_decode.py MODEL_DIR PROMPT_FILE OUT.json [--n 512] [--warm 64] [--reps 3]
"""
import hashlib
import json
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.generation.streamers import BaseStreamer

model_dir, prompt_file, out = sys.argv[1:4]
arg = lambda k, d: int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
N, WARM, REPS = arg("--n", 512), arg("--warm", 64), arg("--reps", 3)


class Stamps(BaseStreamer):
    def __init__(self):
        self.t, self.first = [], True

    def put(self, value):
        if self.first:  # the prompt
            self.first = False
            return
        self.t.append(time.monotonic_ns())

    def end(self):
        pass


tok = AutoTokenizer.from_pretrained(model_dir)
model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=torch.bfloat16, attn_implementation="eager").cuda().eval()
ids = tok(open(prompt_file).read(), return_tensors="pt").input_ids.cuda()


def gen(n):
    s = Stamps()
    with torch.inference_mode():
        o = model.generate(ids, do_sample=False, max_new_tokens=n, min_new_tokens=n, streamer=s,
                           pad_token_id=tok.eos_token_id, temperature=None, top_p=None, top_k=None)
    torch.cuda.synchronize()
    return dict(tokens=int(o.shape[1] - ids.shape[1]), stamps=s.t, text_sha=hashlib.sha256(str(o[0].tolist()).encode()).hexdigest())


result = dict(stack="hf-eager", model=model_dir, prompt_tokens=int(ids.shape[1]), n=N,
              torch=torch.__version__, transformers=__import__("transformers").__version__)
result["warmup"] = {k: v for k, v in gen(WARM).items() if k != "stamps"}
result["gens"] = []
for _ in range(REPS):
    g = gen(N)
    g["output_ids_sha"] = g.pop("text_sha")
    result["gens"].append(g)
json.dump(result, open(out, "w"))
print("HF_DONE", [g["tokens"] for g in result["gens"]])
