// The frame of every Insights page: the fixed header (title, the facts it stands on, the four Insights pages) and the page under it.
import type { ReactNode } from "react";
import { PageHeader } from "../../ds";
import { InsightsNav } from "./ui";

export function Frame({ back, title, meta, actions, children }: { back?: { to: string; label: string }; title: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="ins">
      <PageHeader back={back} title={title} actions={actions}
        meta={<div className="ins-meta">{!back && <InsightsNav />}{meta && <div className="ins-meta-l">{meta}</div>}</div>} />
      {!back && <div className="ins-nav-ph"><InsightsNav /></div>}
      {children}
    </div>
  );
}
