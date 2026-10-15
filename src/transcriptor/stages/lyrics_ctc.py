"""Afinament opcional dels temps de paraula amb alineació forçada CTC (wav2vec2 català).

La transferència des de l'ASR (lyrics_align.py) dona una finestra fiable per a cada línia; aquí,
dins d'aquesta finestra, s'alinea el text de la línia caràcter a caràcter amb el model
`softcatala/wav2vec2-large-xlsr-catala` i un Viterbi CTC propi en numpy (sense WhisperX ni
torchaudio.forced_align, que està en desús). Necessita l'extra `ctc` (transformers).
"""

from __future__ import annotations

import gc
import logging
import unicodedata
from pathlib import Path

import numpy as np

from ..audio import llegeix
from ..device import Perfil

log = logging.getLogger(__name__)

MODEL = "softcatala/wav2vec2-large-xlsr-catala"
MARGE_S = 0.6
MAX_FINESTRA_S = 30.0
MAX_CANVI_S = 1.5  # si el CTC mou una paraula més que això, es considera un error i no es toca


def _viterbi_ctc(logp: np.ndarray, tokens: list[int], blank: int) -> list[int] | None:
    """Alineació forçada CTC. Retorna, per a cada token, la primera trama on comença (o None)."""
    t_total = logp.shape[0]
    estats = [blank]
    for tk in tokens:
        estats += [tk, blank]
    s = len(estats)
    if t_total < len(tokens):
        return None
    em = logp[:, estats]  # [T, S]
    puntua = np.full(s, -np.inf)
    puntua[0], puntua[1] = em[0, 0], em[0, 1]
    previ = np.zeros((t_total, s), dtype=np.int32)
    idx = np.arange(s)
    # Salt de 2 estats permès cap a un no-blank diferent de l'anterior no-blank
    salt2 = np.zeros(s, dtype=bool)
    for k in range(3, s, 2):
        salt2[k] = estats[k] != estats[k - 2]
    for t in range(1, t_total):
        queda = puntua
        u1 = np.concatenate([[-np.inf], puntua[:-1]])
        u2 = np.where(salt2, np.concatenate([[-np.inf, -np.inf], puntua[:-2]]), -np.inf)
        millor = np.maximum(np.maximum(queda, u1), u2)
        previ[t] = np.where(millor == queda, idx, np.where(millor == u1, idx - 1, idx - 2))
        puntua = millor + em[t]
    final = s - 1 if puntua[s - 1] >= puntua[s - 2] else s - 2
    if not np.isfinite(puntua[final]):
        return None
    cami = np.zeros(t_total, dtype=np.int32)
    cami[-1] = final
    for t in range(t_total - 1, 0, -1):
        cami[t - 1] = previ[t, cami[t]]
    inicis: list[int | None] = [None] * len(tokens)
    for t, e in enumerate(cami):
        if e % 2 == 1 and inicis[(e - 1) // 2] is None:
            inicis[(e - 1) // 2] = t
    return inicis  # type: ignore[return-value]


def _tokens(paraula: str, vocab: dict[str, int]) -> list[int]:
    text = unicodedata.normalize("NFC", paraula.lower()).replace("’", "'")
    return [vocab[c] for c in text if c in vocab and c not in ("|", "-")]


def afina(veu: Path, paraules: list[dict], rangs: list[list[int]], perfil: Perfil) -> tuple[list[dict], float]:
    """Retorna (paraules amb temps afinats, fracció de paraules afinades)."""
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

    processador = Wav2Vec2Processor.from_pretrained(MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL).to(perfil.device).eval()
    vocab = processador.tokenizer.get_vocab()
    blank = processador.tokenizer.pad_token_id
    separador = vocab["|"]
    senyal, sr = llegeix(veu, sr=16000, mono=True)

    sortida = [dict(p) for p in paraules]
    afinades = 0
    try:
        for a, b in rangs:
            t0 = max(0.0, paraules[a]["start"] - MARGE_S)
            t1 = min(len(senyal) / sr, paraules[b - 1]["end"] + MARGE_S)
            if t1 - t0 > MAX_FINESTRA_S or t1 <= t0:
                continue
            tros = senyal[int(t0 * sr): int(t1 * sr)]
            tros = (tros - tros.mean()) / (tros.std() + 1e-7)
            with torch.no_grad():
                logits = model(torch.from_numpy(tros).float()[None].to(perfil.device)).logits[0]
            logp = torch.log_softmax(logits, -1).cpu().numpy()
            per_trama = (t1 - t0) / logp.shape[0]
            tokens, propietari = [], []
            for k in range(a, b):
                tk = _tokens(paraules[k]["text"], vocab)
                if not tk:
                    continue
                if tokens:
                    tokens.append(separador)
                    propietari.append(None)
                tokens += tk
                propietari += [k] * len(tk)
            if not tokens:
                continue
            inicis = _viterbi_ctc(logp, tokens, blank)
            if inicis is None:
                continue
            for k in range(a, b):
                trames = [inicis[i] for i, p in enumerate(propietari) if p == k and inicis[i] is not None]
                if not trames:
                    continue
                nou_inici = t0 + min(trames) * per_trama
                nou_fi = t0 + (max(trames) + 1) * per_trama
                if abs(nou_inici - paraules[k]["start"]) <= MAX_CANVI_S:
                    sortida[k]["start"], sortida[k]["end"] = round(nou_inici, 2), round(max(nou_fi, nou_inici), 2)
                    afinades += 1
    finally:
        del model
        gc.collect()
    return sortida, round(afinades / max(len(paraules), 1), 3)
