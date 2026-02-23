import React, { Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LanguageProvider } from './contexts/LanguageContext';
import { AuthProvider } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import Layout from './components/layout/Layout';
import TutorialOverlay from './components/TutorialOverlay';
import LoginPage from './pages/LoginPage';
import './styles/global.css';

/* Lazy-loaded page components for code splitting */
const Dashboard = React.lazy(() => import('./pages/Dashboard'));
const DecisionQueue = React.lazy(() => import('./pages/DecisionQueue'));
const ControlPanel = React.lazy(() => import('./pages/ControlPanel'));
const Creatives = React.lazy(() => import('./pages/Creatives'));
const Saturation = React.lazy(() => import('./pages/Saturation'));
const Opportunities = React.lazy(() => import('./pages/Opportunities'));
const Policies = React.lazy(() => import('./pages/Policies'));
const AuditLog = React.lazy(() => import('./pages/AuditLog'));
const Brain = React.lazy(() => import('./pages/Brain'));
const Help = React.lazy(() => import('./pages/Help'));
const OpsConsole = React.lazy(() => import('./pages/OpsConsole'));
const Onboarding = React.lazy(() => import('./pages/Onboarding'));
const Analytics = React.lazy(() => import('./pages/Analytics'));
const AlertCenter = React.lazy(() => import('./pages/AlertCenter'));
const Settings = React.lazy(() => import('./pages/Settings'));
const ContentStudio = React.lazy(() => import('./pages/ContentStudio'));
const BrandProfile = React.lazy(() => import('./pages/BrandProfile'));
const Radar = React.lazy(() => import('./pages/Radar'));
const Flywheel = React.lazy(() => import('./pages/Flywheel'));
const DataRoom = React.lazy(() => import('./pages/DataRoom'));

function App() {
  return (
    <LanguageProvider>
      <BrowserRouter>
        <AuthProvider>
          <TutorialOverlay />
          <Suspense fallback={<div style={{display:'flex',justifyContent:'center',alignItems:'center',height:'100vh'}}>Loading...</div>}>
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
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </LanguageProvider>
  );
}

export default App;
