import { Check, X } from "lucide-react";

/** Every reason the backend gives for distrusting a message, said as a sentence. A code never reaches the screen. */
export const REASONS: Record<string, string> = {
  sender_domain_lookalike: "The sender's domain looks like the supplier's but is not the one on file",
  sender_domain_near_match: "The sender's domain is a near match to the supplier's, not the same",
  sender_not_in_master: "The sender's company is not in our supplier list",
  sender_not_contact_on_file: "The sender is not a contact we have on file",
  new_sender: "This is the first message from this sender",
  reply_to_freemail: "Replies would go to a free personal mailbox, not the company's",
  reply_to_other_domain: "Replies would go to a different domain than the sender's",
  bank_detail_change: "It asks to change bank details",
  instruction_in_message: "It contains an instruction aimed at software or at us",
  urgency: "It pushes for action today",
  advance_payment_demand: "It demands payment in advance",
  supplier_on_hold: "The supplier is on hold with us",
  price_far_above_history: "The price is far above what we have paid before",
};
export const GOOD: Record<string, string> = {
  contact_on_file: "The sender is a contact on file",
  no_bank_change: "No bank or payment change",
  no_instruction: "No instruction aimed at software",
};

const words = (code: string) => { const s = code.replace(/_/g, " ").trim(); return s ? s[0].toUpperCase() + s.slice(1) : code; };

/** One reason, one sentence: a red cross when it is a concern, a green check when it was verified. */
export function TrustBadge({ reason, ok = false }: { reason: string; ok?: boolean }) {
  const text = (ok ? GOOD[reason] : REASONS[reason]) ?? words(reason);
  return (
    <span className="dm-trust" data-tone={ok ? "green" : "red"}>
      {ok ? <Check size={14} strokeWidth={2} aria-hidden /> : <X size={14} strokeWidth={2} aria-hidden />}
      <span><span className="dm-sr">{ok ? "Passed: " : "Concern: "}</span>{text}</span>
    </span>
  );
}

/** The rail's trust block for a message: the concerns when there are any, else what was verified. */
export function TrustBadges({ flags, onFile }: { flags: string[]; onFile?: boolean }) {
  if (flags.length) return <div className="dm-stack">{flags.map((f) => <TrustBadge key={f} reason={f} />)}</div>;
  return (
    <div className="dm-stack">
      {onFile && <TrustBadge reason="contact_on_file" ok />}
      <TrustBadge reason="no_bank_change" ok />
      <TrustBadge reason="no_instruction" ok />
    </div>
  );
}
