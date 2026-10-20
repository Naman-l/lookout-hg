import { Check, CircleDashed, CircleHelp, Hand, ShieldAlert } from "lucide-react";

export type StageKey = "found" | "worked" | "decision_ready" | "drafted" | "approved" | "sent" | "answered" | "held" | "asking";

/** Where a piece of work stands, as one pill. Needs-you is amber, done is green, held is red, the early stages are grey; each has an icon and its words. */
export function Stage({ stage, waitingOn }: { stage: StageKey; waitingOn?: string | null }) {
  const yours = stage === "drafted" && waitingOn === "you";
  const [word, tone, Icon] =
    stage === "held" ? ["Held", "red", ShieldAlert] as const
    : yours ? ["Needs your OK", "amber", Hand] as const
    : stage === "asking" ? ["Asking", "amber", CircleHelp] as const
    : stage === "approved" ? ["Approved", "green", Check] as const
    : stage === "sent" ? ["Sent", "green", Check] as const
    : stage === "answered" ? ["Answered", "green", Check] as const
    : stage === "decision_ready" ? ["Ready to decide", undefined, CircleDashed] as const
    : stage === "drafted" ? ["Drafted", undefined, CircleDashed] as const
    : stage === "worked" ? ["Worked", undefined, CircleDashed] as const
    : ["Found", undefined, CircleDashed] as const;
  return <span className="dm-pill" data-tone={tone}><Icon size={12} strokeWidth={2} aria-hidden />{word}</span>;
}
