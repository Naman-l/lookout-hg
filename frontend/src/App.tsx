import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { More } from "./shell/MobilePages";
import { Shell } from "./shell/Shell";
import { Today } from "./sections/Today";
import { Placeholder } from "./sections/Placeholder";
import { Item } from "./sections/Item";
import { ApprovalsPage as Approvals } from "./sections/ApprovalsPage";
import { InboxPage as Inbox } from "./sections/InboxPage";
import { DataPage as Data } from "./sections/data/DataPage";
import { Import } from "./sections/Import";
import { AgentActivity as Activity } from "./sections/agents/AgentActivity";
import { DesignPage } from "./ds/DesignPage";
import { UnderTheHood as Hood } from "./sections/agents/UnderTheHood";
import { RunTrace as RunPage } from "./sections/agents/RunTrace";
import { Lookup, MaterialPage, Materials, PoPage, Pos, PrPage, Prs, Requirements, VendorPage, Vendors, WorkFronts } from "./sections/records";
import { Brief, Estimates, Pricing, PricingMaterial, ProjectPage, Projects, Team, TeamPerson } from "./sections/insights";
import { OrgPage } from "./sections/org/OrgPage";

const RECORD_TABS: Record<string, string> = { vendors: "/vendors", materials: "/materials", prs: "/prs", pos: "/pos", requirements: "/requirements", workfronts: "/workfronts",
  data: "/data", import: "/data/import" };
/** /records/<tab> opens that Records tab; an unknown one opens the first. */
function RecordsRedirect() {
  const { tab = "" } = useParams();
  return <Navigate to={RECORD_TABS[tab] ?? "/vendors"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Today />} />
        <Route path="items/:id" element={<Item />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="approvals/tab/:tab" element={<Approvals />} />
        <Route path="approvals/:id" element={<Approvals />} />
        <Route path="inbox" element={<Inbox />} />
        <Route path="inbox/:id" element={<Inbox />} />
        <Route path="records" element={<Navigate to="/vendors" replace />} />
        <Route path="records/:tab" element={<RecordsRedirect />} />
        <Route path="vendors" element={<Vendors />} />
        <Route path="vendors/:id" element={<VendorPage />} />
        <Route path="materials" element={<Materials />} />
        <Route path="materials/:code" element={<MaterialPage />} />
        <Route path="prs" element={<Prs />} />
        <Route path="prs/:no" element={<PrPage />} />
        <Route path="pos" element={<Pos />} />
        <Route path="pos/:no" element={<PoPage />} />
        <Route path="requirements" element={<Requirements />} />
        <Route path="workfronts" element={<WorkFronts />} />
        <Route path="lookup" element={<Lookup />} />
        <Route path="insights" element={<Navigate to="/insights/team" replace />} />
        <Route path="insights/team" element={<Team />} />
        <Route path="insights/team/:person" element={<TeamPerson />} />
        <Route path="org" element={<OrgPage />} />
        <Route path="insights/projects" element={<Projects />} />
        <Route path="insights/projects/:id" element={<ProjectPage />} />
        <Route path="insights/pricing" element={<Pricing />} />
        <Route path="insights/pricing/:material" element={<PricingMaterial />} />
        <Route path="insights/estimates" element={<Estimates />} />
        <Route path="brief/:person" element={<Brief />} />
        <Route path="hood" element={<Hood />} />
        <Route path="activity/:id" element={<RunPage />} />
        <Route path="activity" element={<Activity />} />
        <Route path="data" element={<Data />} />
        <Route path="data/import" element={<Import />} />
        <Route path="design" element={<DesignPage />} />
        <Route path="more" element={<More />} />
        <Route path="*" element={<Placeholder title="Page not found" line="Nothing lives at this address." />} />
      </Route>
    </Routes>
  );
}
