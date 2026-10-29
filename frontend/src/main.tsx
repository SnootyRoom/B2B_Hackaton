import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

// Заглушка роли 1: проверяет связку фронт → nginx → API. Экраны делает роль 4.
function App() {
  const [status, setStatus] = useState("Проверяем связь с сервером…");
  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((r) => setStatus(r.status === 401 ? "Сервер доступен, войдите в систему" : `Ответ сервера: ${r.status}`))
      .catch(() => setStatus("Сервер недоступен"));
  }, []);
  return (
    <main style={{ fontFamily: "system-ui", padding: 16 }}>
      <h1>Скоринг закупок</h1>
      <p>{status}</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
