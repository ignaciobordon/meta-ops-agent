import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LanguageProvider } from './contexts/LanguageContext';
import { AuthProvider } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import Layout from './components/layout/Layout';
import TutorialOverlay from './components/TutorialOverlay';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import DecisionQueue from './pages/DecisionQueue';
import ControlPanel from './pages/ControlPanel';
import Creatives from './pages/Creatives';
import Saturation from './pages/Saturation';
import Opportunities from './pages/Opportunities';
import Policies from './pages/Policies';
import AuditLog from './pages/AuditLog';
import Brain from './pages/Brain';
import Help from './pages/Help';
import OpsConsole from './pages/OpsConsole';
import Onboarding from './pages/Onboarding';
import Analytics from './pages/Analytics';
import AlertCenter from './pages/AlertCenter';
import Settings from './pages/Settings';
import ContentStudio from './pages/ContentStudio';
import BrandProfile from './pages/BrandProfile';
import Radar from './pages/Radar';
import Flywheel from './pages/Flywheel';
import DataRoom from './pages/DataRoom';
import './styles/global.css';

function App() {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <AuthProvider>
          <TutorialOverlay />
          <Routes>
            {/* Public route */}
            <Route path="/login" element={<LoginPage />} />

            {/* Onboarding (outside Layout — no sidebar) */}
            <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />

            {/* Protected routes */}
            <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="decisions" element={<DecisionQueue />} />
              <Route path="control-panel" element={<ControlPanel />} />
              <Route path="brand-profile" element={<BrandProfile />} />
              <Route path="creatives" element={<Creatives />} />
              <Route path="content-studio" element={<ContentStudio />} />
              <Route path="saturation" element={<Saturation />} />
              <Route path="opportunities" element={<Opportunities />} />
              <Route path="radar" element={<Radar />} />
              <Route path="policies" element={<Policies />} />
              <Route path="audit" element={<AuditLog />} />
              <Route path="brain" element={<Brain />} />
              <Route path="ops" element={<OpsConsole />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="alerts" element={<AlertCenter />} />
              <Route path="help" element={<Help />} />
              <Route path="settings" element={<Settings />} />
              <Route path="flywheel" element={<Flywheel />} />
              <Route path="data-room" element={<DataRoom />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </LanguageProvider>
  );
}

export default App;
