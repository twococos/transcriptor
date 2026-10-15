"""Mètriques del benchmark: predicció del transcriptor contra el `content` de la BD.

Les referències de la BD també tenen errors: és una mesura de concordança, no la veritat absoluta.
"""

from __future__ import annotations

import re

import numpy as np

from ..notation import NOTES, arrel_i_sufix, majmin, nota
from ..structure import SECTION_TYPES
from ..text import normalitza, wer

_RE_CH = re.compile(r"<ch>([^<]*)</ch>")
_RE_SEC = re.compile(r"^\s*<sec>([^<]*)</sec>\s*$")


def llegeix_content(content: str) -> list[dict]:
    """Línies del content: {"tipus": "sec"|"lletra"|"acords", "text", "acords": [(pos, acord)], "seccio"}."""
    sortida, seccio = [], None
    for linia in content.split("\n"):
        m = _RE_SEC.match(linia)
        if m:
            seccio = m.group(1).strip()
            sortida.append({"tipus": "sec", "text": seccio, "acords": [], "seccio": seccio})
            continue
        text, acords, cursor = "", [], 0
        for tros in re.split(r"(<ch>[^<]*</ch>)", linia):
            mc = _RE_CH.fullmatch(tros)
            if mc:
                acords.append((len(text), mc.group(1).strip()))
            else:
                text += tros
        if not text.strip() and not acords:
            continue
        tipus = "lletra" if re.search(r"\w", text) else "acords"
        sortida.append({"tipus": tipus, "text": text, "acords": acords, "seccio": seccio})
    return sortida


def tipus_seccio(nom: str | None) -> str | None:
    if not nom:
        return None
    for t in SECTION_TYPES:
        if nom.strip().lower().startswith(t.lower()):
            return t
    return None


def septimes(acord: str) -> tuple[int, str] | None:
    """Acord → (arrel, qualitat) amb qualitat a maj | min | 7 | maj7 | m7 | dim (nivell sevenths)."""
    r = arrel_i_sufix(acord)
    if r is None:
        return None
    arrel, sufix = r
    for q in ("maj7", "m7b5", "m7", "mmaj7", "7", "dim", "m"):
        if sufix.startswith(q):
            return arrel, {"m7b5": "dim", "mmaj7": "min", "m": "min"}.get(q, q)
    return arrel, "maj"


def seq_acords(content: str, nivell=None) -> list[tuple[int, str]]:
    seq = [(nivell or majmin)(a) for a in _RE_CH.findall(content)]
    seq = [a for a in seq if a is not None]
    return [a for i, a in enumerate(seq) if i == 0 or a != seq[i - 1]]


def _nw_encerts(ref: list, pred: list) -> int:
    """Encerts de l'alineament òptim (encert +1, error -1, forat -1)."""
    n, m = len(ref), len(pred)
    if not n or not m:
        return 0
    punts = np.zeros((n + 1, m + 1), dtype=np.int32)
    encerts = np.zeros((n + 1, m + 1), dtype=np.int32)
    punts[:, 0] = -np.arange(n + 1)
    punts[0, :] = -np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            igual = ref[i - 1] == pred[j - 1]
            d = punts[i - 1, j - 1] + (1 if igual else -1)
            u = punts[i - 1, j] - 1
            e = punts[i, j - 1] - 1
            if d >= u and d >= e:
                punts[i, j], encerts[i, j] = d, encerts[i - 1, j - 1] + igual
            elif u >= e:
                punts[i, j], encerts[i, j] = u, encerts[i - 1, j]
            else:
                punts[i, j], encerts[i, j] = e, encerts[i, j - 1]
    return int(encerts[n, m])


def acords(ref_content: str, pred_content: str) -> dict:
    """Concordança de seqüències d'acords (majmin), provant els 12 transports; i a nivell sevenths
    amb el mateix transport."""
    ref, pred = seq_acords(ref_content), seq_acords(pred_content)
    millor = (-1, 0)
    for despl in range(12):
        ref_t = [((r + despl) % 12, t) for r, t in ref]
        millor = max(millor, (_nw_encerts(ref_t, pred), despl))
    encerts, despl = millor
    ref7 = [((r + despl) % 12, t) for r, t in seq_acords(ref_content, septimes)]
    pred7 = seq_acords(pred_content, septimes)
    encerts7 = _nw_encerts(ref7, pred7)
    return {
        "septimes_recall": round(encerts7 / max(len(ref7), 1), 3),
        "septimes_precisio": round(encerts7 / max(len(pred7), 1), 3),
        "n_ref": len(ref), "n_pred": len(pred),
        "acords_recall": round(encerts / max(len(ref), 1), 3),
        "acords_precisio": round(encerts / max(len(pred), 1), 3),
        "transport": despl if despl <= 6 else despl - 12,
    }


def _to_sonant(clau: str, capo: int) -> tuple[int, str] | None:
    r = arrel_i_sufix(clau)
    if r is None:
        return None
    arrel, sufix = r
    return (arrel + capo) % 12, "min" if sufix.startswith("m") else "maj"


def tonalitat(ref_clau: str, transport: int, pred_tonic: str | None, pred_mode: str | None) -> str:
    """exacte | relatiu | quinta | paral·lel | altre.

    Compara en "formes": el to de la BD (tal com està escrit) desplaçat pel transport detectat a
    la seqüència d'acords, contra el to predit menys la cejilla suggerida. Així una gravació en un to
    diferent del de la BD no compta com a error de tonalitat.
    """
    ref = _to_sonant(ref_clau, transport)
    if ref is None or pred_tonic is None:
        return "sense"
    pred = (NOTES.index(nota(pred_tonic)), "min" if pred_mode == "minor" else "maj")
    if ref == pred:
        return "exacte"
    (ra, rm), (pa, pm) = ref, pred
    if rm != pm and ((rm == "maj" and pa == (ra + 9) % 12) or (rm == "min" and pa == (ra + 3) % 12)):
        return "relatiu"
    if rm == pm and (pa - ra) % 12 in (5, 7):
        return "quinta"
    if ra == pa:
        return "paral·lel"
    return "altre"


def tonalitat_acords_bd(ref_content: str, transport: int, pred_tonic: str | None,
                        pred_mode: str | None) -> str:
    """Com `tonalitat`, però la referència és el to estimat dels acords de la BD (durada uniforme)."""
    from ..postprocess.key import clau, estima

    acords = [{"start": i, "end": i + 1, "label": a} for i, a in enumerate(_RE_CH.findall(ref_content))
              if majmin(a)]
    to_ref = estima(acords)
    if to_ref is None:
        return "sense"
    return tonalitat(clau(to_ref), transport, pred_tonic, pred_mode)


def wer_lletra(ref_content: str, text_asr: str) -> float:
    ref = " ".join(l["text"] for l in llegeix_content(ref_content) if l["tipus"] == "lletra")
    return round(wer(normalitza(ref), normalitza(text_asr)), 3)


def _index_paraula(text: str, pos: int) -> int:
    """Índex de la paraula on cau la posició de caràcter `pos`."""
    return max(len(text[: pos + 1].split()) - 1, 0) if text[: pos + 1].strip() else 0


def collocacio(ref_content: str, pred_content: str, transport: int) -> dict:
    """Part dels acords de les línies de lletra de la referència que cauen a la mateixa paraula.

    Les línies es parellen pel text normalitzat (en ordre). Acords comparats a nivell majmin,
    aplicant el transport detectat.
    """
    ref = [l for l in llegeix_content(ref_content) if l["tipus"] == "lletra"]
    pred = [l for l in llegeix_content(pred_content) if l["tipus"] == "lletra"]
    claus_pred = [" ".join(normalitza(l["text"])) for l in pred]
    total = encerts = 0
    j = 0
    for l in ref:
        clau = " ".join(normalitza(l["text"]))
        total += len(l["acords"])
        try:
            k = claus_pred.index(clau, j)
        except ValueError:
            continue
        j = k + 1
        acords_pred = {}
        for pos, a in pred[k]["acords"]:
            acords_pred.setdefault(_index_paraula(pred[k]["text"], pos), set()).add(majmin(a))
        for pos, a in l["acords"]:
            mm = majmin(a)
            if mm is None:
                continue
            esperat = ((mm[0] + transport) % 12, mm[1])
            if esperat in acords_pred.get(_index_paraula(l["text"], pos), set()):
                encerts += 1
    return {"collocacio": round(encerts / max(total, 1), 3), "acords_en_lletra": total}


def estructura(ref_content: str, pred_content: str) -> dict:
    """Coincidència del tipus de secció per línia de lletra, i nombre de seccions."""
    ref = [l for l in llegeix_content(ref_content) if l["tipus"] == "lletra"]
    pred = [l for l in llegeix_content(pred_content) if l["tipus"] == "lletra"]
    claus_pred = [" ".join(normalitza(l["text"])) for l in pred]
    total = encerts = 0
    j = 0
    for l in ref:
        clau = " ".join(normalitza(l["text"]))
        try:
            k = claus_pred.index(clau, j)
        except ValueError:
            continue
        j = k + 1
        total += 1
        encerts += tipus_seccio(l["seccio"]) == tipus_seccio(pred[k]["seccio"])
    n_ref = sum(1 for l in llegeix_content(ref_content) if l["tipus"] == "sec")
    n_pred = sum(1 for l in llegeix_content(pred_content) if l["tipus"] == "sec")
    return {"estructura": round(encerts / max(total, 1), 3), "seccions_ref": n_ref, "seccions_pred": n_pred}


def qualitat_referencia(content: str) -> dict:
    """Indicadors per detectar referències pobres (esborranys mal importats)."""
    linies = llegeix_content(content)
    lletra = [l for l in linies if l["tipus"] == "lletra"]
    amb_acords = sum(1 for l in lletra if l["acords"])
    seccions = sum(1 for l in linies if l["tipus"] == "sec")
    acords_rars = sum(1 for a in _RE_CH.findall(content) if majmin(a) is None)
    problemes = []
    if len(lletra) < 6:
        problemes.append("poca lletra")
    if lletra and amb_acords / len(lletra) < 0.4:
        problemes.append("poques línies amb acords")
    if seccions == 0:
        problemes.append("sense seccions")
    if acords_rars:
        problemes.append(f"{acords_rars} acords il·legibles")
    return {"linies_lletra": len(lletra), "linies_amb_acords": amb_acords, "n_seccions": seccions,
            "ref_problemes": "; ".join(problemes)}
