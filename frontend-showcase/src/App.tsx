import { Spin } from 'antd';
import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/AppShell';
import AgentChatPage from './pages/AgentChatPage';
import LoginPage from './pages/LoginPage';
import HubPage from './pages/HubPage';
import DocsPage from './pages/DocsPage';
import HubsPage from './pages/HubsPage';
import { useSession } from './session';

export default function App() {
  const { loading, session } = useSession();

  if (loading) {
    return (
      <div className="center-screen">
        <Spin size="large" />
      </div>
    );
  }

  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HubsPage />} />
        <Route path="/hubs/:hubId" element={<HubPage />} />
        <Route
          path="/hubs/:hubId/agents/:agentId"
          element={<AgentChatPage />}
        />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/docs/:slug" element={<DocsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
