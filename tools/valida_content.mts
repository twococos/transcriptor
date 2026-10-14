/**
 * Valida contents generats pel transcriptor amb el codi real del canconer (només lectura).
 *
 * Ús: node --experimental-strip-types tools/valida_content.mts <fitxer.txt>...
 * Variable CANCONER_DIR: arrel del repo del canconer (per defecte ../guitarreopuntcat).
 *
 * Comprova: round-trip serialize(parse(x)) === x, noms de secció vàlids (SECTION_TYPES) i
 * acords amb format conegut. Surt amb codi 1 si algun fitxer falla.
 */
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { pathToFileURL } from "node:url"

const arrel = resolve(process.env.CANCONER_DIR ?? "../guitarreopuntcat")
const model = await import(pathToFileURL(resolve(arrel, "src/lib/editor/model.ts")).href)
const seccions = await import(pathToFileURL(resolve(arrel, "src/lib/editor/sections.ts")).href)

const RE_ACORD = /^[A-G][#b]?(m|maj7|7|m7|sus2|sus4|add9|6|m6|dim|m7b5|mmaj7|9|13|aug)?(\/[A-G][#b]?)?$/

let errors = 0
for (const fitxer of process.argv.slice(2)) {
  const content = readFileSync(fitxer, "utf8")
  const problemes: string[] = []
  const doc = model.parse(content)
  if (model.serialize(doc) !== content) problemes.push("el round-trip parse/serialize no és idèntic")
  for (const b of doc.blocks) {
    if (b.kind === "section" && seccions.getSectionType(b.name) === null)
      problemes.push(`secció desconeguda: "${b.name}"`)
    if (b.kind === "lyric")
      for (const s of b.spans)
        if (s.kind === "chord" && !RE_ACORD.test(s.chord)) problemes.push(`acord estrany: "${s.chord}"`)
    if (b.kind === "empty") problemes.push("hi ha línies buides")
  }
  if (problemes.length) {
    errors++
    console.log(`✗ ${fitxer}\n  - ${[...new Set(problemes)].join("\n  - ")}`)
  } else {
    console.log(`✓ ${fitxer} (${doc.blocks.length} blocs)`)
  }
}
process.exit(errors ? 1 : 0)
