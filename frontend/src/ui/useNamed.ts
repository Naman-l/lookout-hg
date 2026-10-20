import { usePartNames } from "../api/usePartNames";
import { humanize } from "./format";
import { poLineText } from "../domain-ui/Records";

/** A sentence from the backend with its numbers turned into names: a part number becomes the part's name, and an order line keeps its real number. A number with no known name stays as it is. */
export function useNamed() {
  const partName = usePartNames();
  return (text: string): string =>
    humanize(text)
      // a number the sentence already put in brackets after the name is dropped, not repeated
      .replace(/\s*\((?:HR-\d{5})\)/g, "")
      .replace(/\bHPO-\d{2}-\d{5}\s*\/\s*\d+/g, (m) => poLineText(m))
      .replace(/\bHR-\d{5}\b/g, (m) => partName(m) ?? m);
}
