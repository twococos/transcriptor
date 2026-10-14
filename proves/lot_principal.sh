#!/usr/bin/env bash
# Fase 0: lot seqüencial de proves (ritme, acords, separació alternativa, lletra).
# Seqüencial perquè els temps de CPU no es contaminin entre proves.
export TORCH_HOME=$PWD/work/models/torch HF_HOME=$PWD/work/models/hf HF_HUB_DISABLE_SYMLINKS_WARNING=1
export PYTHONIOENCODING=utf-8
C="estaca bondia gent"
mkdir -p work/ritme work/acords work/lletra work/sep/roformer

for c in $C; do
  proves/cronometra.sh "beatthis_$c" work/envs/beatthis/Scripts/python -I proves/ritme_beatthis.py \
    "work/audio/$c.wav" "work/ritme/$c.json"
  proves/cronometra.sh "btc_$c" work/envs/btc/Scripts/python -I proves/acords_btc.py work/vendor/btc \
    "work/audio/$c.wav" "work/acords/btc_$c.lab"
  # Variant: acords sobre l'acompanyament sense veu
  proves/cronometra.sh "btc_noveu_$c" work/envs/btc/Scripts/python -I proves/acords_btc.py work/vendor/btc \
    "work/sep/demucs/htdemucs/$c/no_vocals.wav" "work/acords/btc_noveu_$c.lab"
done

for c in $C; do
  proves/cronometra.sh "roformer_$c" work/envs/audiosep/Scripts/audio-separator "work/audio/$c.wav" \
    -m vocals_mel_band_roformer.ckpt --model_file_dir work/models/audiosep \
    --output_dir "work/sep/roformer/$c" --output_format WAV
done

for model in large-v3-turbo large-v3; do
  for c in $C; do
    proves/cronometra.sh "asr_${model}_$c" work/envs/lletra/Scripts/python -I proves/lletra_asr.py "$model" \
      "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/$c.txt" "work/lletra/asr_${model}_$c.json"
  done
done

for model in medium large-v3-turbo; do
  for c in $C; do
    proves/cronometra.sh "alinea_${model}_$c" work/envs/lletra/Scripts/python -I proves/lletra_alinea.py "$model" \
      "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/$c.txt" "work/lletra/alinea_${model}_$c.json"
  done
done
for c in $C; do
  proves/cronometra.sh "whisperx_$c" work/envs/whisperx/Scripts/python -I proves/lletra_whisperx.py \
    "work/sep/demucs/htdemucs/$c/vocals.wav" "work/lletres/$c.lrc" "work/lletra/whisperx_$c.json"
done
echo FET_TOT
