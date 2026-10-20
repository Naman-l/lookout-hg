import { api } from "./client";
import { useResource } from "./useResource";

/** "Motor, BLDC, 48 V 400 W, 86 mm frame, hall sensors, wheel drive" -> "Motor, BLDC": the name a buyer says. */
export const shortName = (description: string) => {
  const name = description.split(", ").slice(0, 2).join(", ");
  // the export shouts some names ("GEARBOX, PLANETARY"): say them in sentence case
  if (name !== name.toUpperCase()) return name;
  // sentence case, but a short all-caps token is an acronym the records mean (BLDC, DC, PCB) and stays as written
  return name.split(/(\s+|,\s*)/).map((w, n) => (/^[A-Z0-9]{1,4}$/.test(w) && n > 0 ? w : n === 0 ? w[0] + w.slice(1).toLowerCase() : w.toLowerCase())).join("");
};

/** part number -> the name a buyer says, for records whose reference arrives without a label. */
export function usePartNames() {
  const r = useResource(api.parts);
  const map = new Map((r.data ?? []).map((p) => [p.ref.id ?? "", shortName(p.description)]));
  return (id: string) => map.get(id) || undefined;
}
