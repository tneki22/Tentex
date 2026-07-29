import { Navigate, Route, Routes } from "react-router";
import { AppLayout } from "./app/AppLayout";
import { screenById } from "./app/screens";
import { Cards } from "./screens/Cards";
import { Coverage } from "./screens/Coverage";
import { CoverageMap } from "./screens/CoverageMap";
import { InboxScreen } from "./screens/InboxScreen";
import { Materials } from "./screens/Materials";
import { Plan } from "./screens/Plan";
import { Program } from "./screens/Program";
import { ProjectWizard } from "./screens/ProjectWizard";
import { Projects } from "./screens/Projects";
import { Session } from "./screens/Session";
import { SettingsScreen } from "./screens/SettingsScreen";
import { SourceViewer } from "./screens/SourceViewer";
import { Suggestions } from "./screens/Suggestions";
import { Topic } from "./screens/Topic";
import { UiKit } from "./screens/UiKit";

/** Пути берутся из реестра экранов, чтобы список был в одном месте. */
const path = (id: string) => screenById(id).path;

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to={path("projects")} replace />} />
        <Route path={path("projects")} element={<Projects />} />
        <Route path={path("project-new")} element={<ProjectWizard />} />
        <Route path={path("coverage-map")} element={<CoverageMap />} />
        <Route path={path("coverage")} element={<Coverage />} />
        <Route path={path("program")} element={<Program />} />
        <Route path={path("materials")} element={<Materials />} />
        <Route path={path("source-viewer")} element={<SourceViewer />} />
        <Route path={path("suggestions")} element={<Suggestions />} />
        <Route path={path("topic")} element={<Topic />} />
        <Route path={path("session")} element={<Session />} />
        <Route path={path("cards")} element={<Cards />} />
        <Route path={path("plan")} element={<Plan />} />
        <Route path={path("inbox")} element={<InboxScreen />} />
        <Route path={path("settings")} element={<SettingsScreen />} />
        <Route path={path("ui-kit")} element={<UiKit />} />
        <Route path="*" element={<Navigate to={path("projects")} replace />} />
      </Route>
    </Routes>
  );
}
