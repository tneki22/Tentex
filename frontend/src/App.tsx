import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router";
import { AppLayout } from "./app/AppLayout";
import { screenById } from "./app/screens";
import { SCREEN_VIEWS } from "./app/views";
import { LoadingState } from "./components/ui/LoadingState";

const DetachedWorkspace = lazy(() =>
  import("./screens/ProjectWorkspace").then((module) => ({ default: module.ProjectWorkspace })),
);

/** Первый экран, который видит пользователь. */
const HOME = screenById("projects").path;

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to={HOME} replace />} />
        <Route path="/projects/:projectId/detached/:detachedId" element={
          <Suspense fallback={<LoadingState placement="page" label="Открываем рабочую область" />}>
            <DetachedWorkspace detached />
          </Suspense>
        } />
        {Object.entries(SCREEN_VIEWS).map(([id, View]) => (
          <Route key={id} path={screenById(id).path} element={
            <Suspense fallback={<LoadingState placement="page" label="Открываем экран" />}>
              <View />
            </Suspense>
          } />
        ))}
        <Route path="*" element={<Navigate to={HOME} replace />} />
      </Route>
    </Routes>
  );
}
