"""Etapa lyrics_asr: transcripció de la veu separada amb faster-whisper.

Es fa sempre, també quan tenim el text: serveix per transferir-ne els temps (lyrics_align.py).
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path

from ..audio import llegeix
from ..device import Perfil

log = logging.getLogger(__name__)


def _model(nom: str, perfil: Perfil, compute_type: str):
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(nom, device=perfil.device, compute_type=compute_type, cpu_threads=perfil.fils)
    except ImportError as e:
        # Smart App Control pot bloquejar la DLL de CTranslate2 la primera vegada (Fase 0)
        raise RuntimeError(
            "No s'ha pogut carregar CTranslate2. Si Windows mostra 'Una directiva de Control "
            "d'aplicacions ha bloquejat aquest fitxer', torna-ho a provar d'aquí a uns minuts."
        ) from e


def transcriu(veu: Path, perfil: Perfil, model: str, compute_type: str, idioma: str | None = None,
              prompt: str | None = None, vad_llindar: float = 0.5) -> dict:
    """Retorna {"idioma", "segments": [{start, end, text}], "paraules": [{start, end, text, conf}]}.

    `idioma` None = detecció automàtica (l'idioma de la BD no sempre és fiable).
    """
    wm = _model(model, perfil, compute_type)
    senyal, _ = llegeix(veu, sr=16000, mono=True)
    try:
        segments, info = wm.transcribe(
            senyal, language=idioma, word_timestamps=True, beam_size=5,
            vad_filter=True, vad_parameters={"threshold": vad_llindar},
            condition_on_previous_text=False, initial_prompt=prompt,
            # Detecció sobre diversos trossos: els primers 30 s sovint són instrumentals
            language_detection_segments=6,
        )
        segments = list(segments)
    finally:
        del wm
        gc.collect()
    return {
        "idioma": info.language,
        "segments": [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                     for s in segments],
        "paraules": [
            {"start": round(w.start, 2), "end": round(w.end, 2), "text": w.word.strip(),
             "conf": round(w.probability, 3)}
            for s in segments for w in (s.words or []) if w.word.strip()
        ],
    }
