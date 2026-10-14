"""Fase 0: prova de BTC (ISMIR19, vocabulari gran de 170 acords).

Ús: python proves/acords_btc.py <dir_btc> <àudio.wav> <sortida.lab>
Basat en test.py del repo original, sense la part de MIDI i amb confiança per segment.
"""

import sys
import time
from pathlib import Path

dir_btc, entrada, sortida = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sys.path.insert(0, str(dir_btc))

import numpy as np  # noqa: E402

# El codi de BTC (2019) usa àlies de numpy eliminats a numpy >= 1.24
np.float = float
np.int = int
import torch  # noqa: E402
import yaml  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from btc_model import BTC_model  # noqa: E402
from utils.hparams import HParams  # noqa: E402
from utils.mir_eval_modules import audio_file_to_features, idx2voca_chord  # noqa: E402

t0 = time.perf_counter()
# El repo usa yaml.load() sense Loader, incompatible amb PyYAML >= 6
config = HParams(**yaml.safe_load((dir_btc / "run_config.yaml").read_text()))
config.feature["large_voca"] = True
config.model["num_chords"] = 170
idx_a_acord = idx2voca_chord()
model = BTC_model(config=config.model)
# El checkpoint conté arrays de numpy (mean/std): cal weights_only=False amb torch >= 2.6
punt = torch.load(dir_btc / "test" / "btc_model_large_voca.pt", map_location="cpu", weights_only=False)
model.load_state_dict(punt["model"])
model.eval()
t_carrega = time.perf_counter() - t0

t1 = time.perf_counter()
caract, per_segon, _ = audio_file_to_features(entrada, config)
t_caract = time.perf_counter() - t1

t2 = time.perf_counter()
caract = (caract.T - punt["mean"]) / punt["std"]
n = config.model["timestep"]
farciment = n - (caract.shape[0] % n)
n_reals = caract.shape[0]
caract = np.pad(caract, ((0, farciment), (0, 0)))
x = torch.tensor(caract, dtype=torch.float32).unsqueeze(0)
idx, conf = [], []
with torch.no_grad():
    for t in range(caract.shape[0] // n):
        h, _ = model.self_attn_layers(x[:, n * t : n * (t + 1), :])
        p = F.softmax(model.output_layer.output_projection(h), -1).squeeze(0)
        c, i = p.max(-1)
        idx.extend(i.tolist())
        conf.extend(c.tolist())
idx, conf = idx[:n_reals], conf[:n_reals]
t_inferencia = time.perf_counter() - t2

# Agrupar trames consecutives amb el mateix acord
linies = []
inici = 0
for k in range(1, len(idx) + 1):
    if k == len(idx) or idx[k] != idx[inici]:
        c = float(np.mean(conf[inici:k]))
        linies.append(f"{inici * per_segon:.3f} {k * per_segon:.3f} {idx_a_acord[idx[inici]]} {c:.2f}\n")
        inici = k
Path(sortida).write_text("".join(linies), encoding="utf-8")
print(f"carrega={t_carrega:.1f}s caracteristiques={t_caract:.1f}s inferencia={t_inferencia:.1f}s segments={len(linies)}")
