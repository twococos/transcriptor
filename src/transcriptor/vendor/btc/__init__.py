"""BTC (Bi-directional Transformer for Chord recognition, ISMIR 2019).

Codi incorporat de https://github.com/jayg996/BTC-ISMIR19 (llicència MIT, vegeu LICENSE),
reduït a la inferència i modernitzat (numpy >= 2, torch >= 2.6). Els noms dels mòduls es
mantenen idèntics perquè el checkpoint original (`btc_model_large_voca.pt`) carregui tal qual.
"""

from .model import BTC_model, CONFIG_MODEL, CONFIG_AUDIO, idx_a_acord

__all__ = ["BTC_model", "CONFIG_MODEL", "CONFIG_AUDIO", "idx_a_acord"]
