#!/usr/bin/env bash
# Fase 0: segona part del lot (alineació, WhisperX, Roformer i, finalment, large-v3).
export TORCH_HOME=$PWD/work/models/torch HF_HOME=$PWD/work/models/hf HF_HUB_DISABLE_SYMLINKS_WARNING=1
export PYTHONIOENCODING=utf-8 PATH="$PWD/work/bin:$PATH"
C="estaca bondia gent"

for model in fw:large-v3-turbo; do
  for c in $C; do
    proves/cronometra.sh "alinea_${model#fw:}_$c" work/envs/lletra/Scripts/python -I proves/lletra_alinea.py "$model" \
      "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/${c}_cantada.txt" "work/lletra/alinea_${model#fw:}_$c.json"
  done
done

# L'estaca no té cap LRC de LRCLIB que quadri amb la gravació: el derivem de l'alineació
work/envs/btc/Scripts/python -I proves/lrc_des_d_alineacio.py work/lletres/estaca_cantada.txt \
  work/lletra/alinea_large-v3-turbo_estaca.json work/lletres/estaca.lrc

for c in $C; do
  proves/cronometra.sh "whisperx_$c" work/envs/whisperx/Scripts/python -I proves/lletra_whisperx.py \
    "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/$c.lrc" "work/lletra/whisperx_$c.json"
done

proves/lot_roformer.sh

# large-v3 només quan el model ja sigui a disc (es descarrega a part)
until [ -f work/proves/large-v3.descarregat ]; do sleep 30; done
for c in $C; do
  proves/cronometra.sh "asr_large-v3_$c" work/envs/lletra/Scripts/python -I proves/lletra_asr.py large-v3 \
    "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/$c.txt" "work/lletra/asr_large-v3_$c.json"
done
echo FET_LLETRA
