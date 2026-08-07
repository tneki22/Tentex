import { Navigate, Route, Routes } from "react-router";
import { AppLayout } from "./app/AppLayout";
import { screenById } from "./app/screens";
import { SCREEN_VIEWS } from "./app/views";

/** Первый экран, который видит пользователь. */
const HOME = screenById("projects").path;

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to={HOME} replace />} />
        {Object.entries(SCREEN_VIEWS).map(([id, View]) => (
          <Route key={id} path={screenById(id).path} element={<View />} />
        ))}
        <Route path="*" element={<Navigate to={HOME} replace />} />
      </Route>
    </Routes>
  );
}
