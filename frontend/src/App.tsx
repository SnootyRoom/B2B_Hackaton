import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { setUnauthorizedHandler } from './api/client';
import { qk, useMe } from './lib/hooks';
import Layout from './components/Layout';
import { Loading } from './components/ui';
import LoginPage from './pages/LoginPage';
import ProfilePage from './pages/ProfilePage';
import UploadPage from './pages/UploadPage';
import ResultsPage from './pages/ResultsPage';
import ProcurementPage from './pages/ProcurementPage';
import HistoryPage from './pages/HistoryPage';
import WelcomePage from './pages/WelcomePage';


export default function App() {
  const qc = useQueryClient();
  const me = useMe();

  // Сессия истекла (сервер ответил 401) → забываем пользователя, покажется экран входа
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(qk.me, null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' });
    });
  }, [qc]);

  if (me.isPending) return <Loading />;

  if (!me.data) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<Layout user={me.data} />}>
        {/* После входа — стартовая страница: что делает сервис, три шага и кнопка «Начать» / «Далее» */}
        <Route index element={<WelcomePage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="procurements/:id" element={<ProcurementPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
