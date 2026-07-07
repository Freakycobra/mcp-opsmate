import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from '@/context/AuthContext';
import { ModeProvider } from '@/context/ModeContext';
import { ToastContainer } from '@/components/Toast';
import { Header } from '@/components/Header';
import { Sidebar } from '@/components/Sidebar';
import { ChatPage } from '@/pages/ChatPage';
import { HistoryPage } from '@/pages/HistoryPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { AdminPage } from '@/pages/AdminPage';

/**
 * App Layout with Header + Sidebar + Content
 */
function AppLayout(): JSX.Element {
  return (
    <div className="h-screen w-screen flex flex-col bg-opsmate-50 overflow-hidden">
      {/* Toast notifications */}
      <ToastContainer />

      {/* Top Header */}
      <Header />

      {/* Main content area */}
      <div className="flex-1 flex min-h-0">
        {/* Left Sidebar */}
        <Sidebar />

        {/* Content */}
        <main className="flex-1 min-w-0 overflow-hidden">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

/**
 * Root App Component
 * Wraps the entire application with all context providers.
 */
function App(): JSX.Element {
  return (
    <AuthProvider>
      <ModeProvider>
        <AppLayout />
      </ModeProvider>
    </AuthProvider>
  );
}

export default App;
