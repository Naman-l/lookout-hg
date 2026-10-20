import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { More } from "./shell/MobilePages";
import { Shelf } from "./sections/Shelf";
import { Shell } from "./shell/Shell";
import { Today } from "./sections/Today";
import { Placeholder } from "./sections/Placeholder";
import { Item } from "./sections/Item";
import { ApprovalsPage as Approvals } from "./sections/ApprovalsPage";
import { InboxPage as Inbox } from "./sections/InboxPage";
import { DataPage as Data } from "./sections/data/DataPage";
import { Import } from "./sections/Import";
import { SupplierPage } from "./sections/records/SupplierPage";
import { Bom } from "./sections/Bom";
import { PartPage } from "./sections/records/PartPage";
import { AgentActivity as Activity } from "./sections/agents/AgentActivity";
import { LandedStory } from "./sections/agents/LandedStory";
import { UnderTheHood as Hood } from "./sections/agents/UnderTheHood";
import { RunTrace as RunPage } from "./sections/agents/RunTrace";
import { Forecast, Orders, Parts, Suppliers } from "./sections/records/lists";
import { AskTestPage } from "./sections/AskTestPage";

const RECORD_TABS: Record<string, string> = { suppliers: "/suppliers", parts: "/parts", orders: "/orders", forecast: "/forecast", data: "/data", import: "/data/import" };
/** /records/<tab> opens that Records tab; an unknown one opens the first. */
function RecordsRedirect() {
  const { tab = "" } = useParams();
  return <Navigate to={RECORD_TABS[tab] ?? "/suppliers"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Today />} />
        <Route path="records" element={<Navigate to="/suppliers" replace />} />
        <Route path="records/import" element={<Navigate to="/data/import" replace />} />
        <Route path="records/:tab" element={<RecordsRedirect />} />
        <Route path="hood" element={<Hood />} />
        <Route path="inbox" element={<Inbox />} />
        <Route path="inbox/:id" element={<Inbox />} />
        <Route path="suppliers" element={<Suppliers />} />
        <Route path="suppliers/:id" element={<SupplierPage />} />
        <Route path="parts" element={<Parts />} />
        <Route path="parts/bom" element={<Bom />} />
        <Route path="parts/bom/:id" element={<Bom />} />
        <Route path="parts/:id" element={<PartPage />} />
        <Route path="orders" element={<Orders />} />
        <Route path="forecast" element={<Forecast />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="approvals/tab/:tab" element={<Approvals />} />
        <Route path="approvals/:id" element={<Approvals />} />
        <Route path="activity/:id" element={<RunPage />} />
        <Route path="activity" element={<Activity />} />
        <Route path="dev/landed-cost" element={<LandedStory />} />
        <Route path="data" element={<Data />} />
        <Route path="data/import" element={<Import />} />
        <Route path="items/:id" element={<Item />} />
        <Route path="dev/ask/:id" element={<AskTestPage />} />
        <Route path="builds/*" element={<Navigate to="/" replace />} />      {/* the build pages are out of the demo (Khalid): Today instead */}
        <Route path="shelf" element={<Shelf />} />
        <Route path="more" element={<More />} />
        <Route path="*" element={<Placeholder title="Page not found" line="Nothing lives at this address." />} />
      </Route>
    </Routes>
  );
}
