import { Tip } from "./Tip";

/** Jargon appears only with its meaning on hover. A word not listed here is shown as it is, never guessed. */
export const GLOSSARY: Record<string, { word: string; meaning: string }> = {
  bom: { word: "BOM", meaning: "Bill of materials: the list of parts that make one robot." },
  po: { word: "PO", meaning: "Purchase order: what we ordered from a supplier, line by line." },
  fm: { word: "FM", meaning: "Force majeure: a supplier's notice that an event outside its control excuses late delivery." },
  hts: { word: "HTS", meaning: "Harmonized Tariff Schedule code: it decides which import duty applies to a part." },
  incoterm: { word: "Incoterm", meaning: "The shipping term that says who pays and who carries the risk at each leg." },
  coo: { word: "COO", meaning: "Country of origin: where a part is made, which decides its duty." },
  moq: { word: "MOQ", meaning: "Minimum order quantity: the least a supplier will sell at one price." },
};

export function Term({ k }: { k: keyof typeof GLOSSARY | string }) {
  const t = GLOSSARY[k.toLowerCase()];
  if (!t) return <>{k}</>;
  return <Tip tip={t.meaning} inline><abbr className="dm-term">{t.word}</abbr></Tip>;
}
