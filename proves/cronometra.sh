#!/usr/bin/env bash
# Executa una comanda i n'afegeix el temps de paret (s) a work/proves/temps.tsv
# Ús: proves/cronometra.sh <etiqueta> <comanda...>
mkdir -p work/proves
etiqueta=$1; shift
inici=$(date +%s%N)
"$@" > "work/proves/${etiqueta}.log" 2>&1
codi=$?
fi=$(date +%s%N)
printf "%s\t%d\t%s\n" "$etiqueta" $(( (fi - inici) / 1000000000 )) "$codi" >> work/proves/temps.tsv
