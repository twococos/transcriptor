import json
from pathlib import Path

from transcriptor.postprocess import temps_asr

DADES = Path(__file__).parent / "dades" / "asr"  # lyrics_asr.json crus de l'app (large-v3-turbo, int8)


def _p(text: str, start: float, end: float) -> dict:
    return {"start": start, "end": end, "text": text, "conf": 0.9}


def _seg(paraules: list[dict]) -> dict:
    return {"start": paraules[0]["start"], "end": paraules[-1]["end"], "text": " ".join(p["text"] for p in paraules)}


def _temps(r: dict, text: str) -> list[float]:
    return next([p["start"], p["end"]] for p in r["paraules"] if p["text"] == text)


def test_primera_paraula_desplacada_es_mou_davant_la_seguent():
    a = [_p("when", 10.0, 10.3), _p("you", 10.3, 10.6), _p("were", 10.6, 10.9), _p("here", 10.9, 11.2)]
    b = [_p("Couldn't", 11.2, 12.4), _p("look", 15.0, 15.3), _p("you", 15.3, 15.6), _p("in", 15.6, 15.9)]
    r = temps_asr.corregeix(a + b, [_seg(a), _seg(b)])
    assert _temps(r, "Couldn't") == [14.4, 15.0]  # durada: 2 × mediana (0.3)
    assert r["segments"][1]["start"] == 14.4
    assert r["paraules"][:4] == a
    assert len(r["correccions"]) == 1


def test_final_de_frase_amb_puntuacio_no_es_toca():
    a = [_p("bon", 10.0, 10.3), _p("dia,", 10.3, 11.0), _p("adeu", 13.0, 13.3), _p("amic", 13.3, 13.6)]
    r = temps_asr.corregeix(a, [_seg(a)])
    assert r["correccions"] == []


def test_dins_el_segment_sense_puntuacio_es_mou():
    a = [_p("balla", 30.0, 30.3), _p("com", 30.3, 31.4), _p("una", 37.0, 37.3), _p("baldufa", 37.3, 37.6)]
    r = temps_asr.corregeix(a, [_seg(a)])
    assert _temps(r, "com") == [36.4, 37.0]


def test_buit_entre_segments_no_es_toca():
    a = [_p("cry", 35.0, 35.6)]
    b = [_p("you", 40.0, 40.3), _p("float", 40.3, 40.6)]
    r = temps_asr.corregeix(a + b, [_seg(a), _seg(b)])
    assert r["correccions"] == []


def test_creep_primeres_paraules_de_vers():
    asr = json.loads((DADES / "creep.json").read_text(encoding="utf-8"))
    r = temps_asr.corregeix(asr["paraules"], asr["segments"])
    mogudes = {c["text"]: c for c in r["correccions"]}
    # "Couldn't [20.26-21.50] … look [24.03]": just abans de "look"
    assert "Couldn't" in mogudes and mogudes["Couldn't"]["despres"][1] == 24.03
    assert mogudes["Your"]["despres"][1] == 34.21
    # Cap primera paraula de segment separada de la següent del mateix segment per més d'1 s
    seg = temps_asr._segment_de(r["paraules"], r["segments"])
    for k in range(len(r["paraules"]) - 1):
        if seg[k] is not None and seg[k] == seg[k + 1] and (k == 0 or seg[k - 1] != seg[k]):
            assert r["paraules"][k + 1]["start"] - r["paraules"][k]["end"] <= temps_asr.MIN_BUIT_S
    # La primera frase no es toca
    assert r["paraules"][:5] == asr["paraules"][:5]
    # L'ordre es manté
    inicis = [p["start"] for p in r["paraules"]]
    assert inicis == sorted(inicis)


def test_fauna_primera_paraula_abans_de_l_instrumental():
    asr = json.loads((DADES / "fauna.json").read_text(encoding="utf-8"))
    r = temps_asr.corregeix(asr["paraules"], asr["segments"])
    # "Vino [0.02-1.18]" amb 15 s d'instrumental fins a "por [16.22]"
    assert r["paraules"][0]["text"] == "Vino" and r["paraules"][0]["end"] == r["paraules"][1]["start"]
    assert r["paraules"][0]["start"] > 15.0
    inicis = [p["start"] for p in r["paraules"]]
    assert inicis == sorted(inicis)
