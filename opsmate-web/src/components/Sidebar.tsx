import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import {
  MessageSquare,
  History,
  BarChart3,
  Settings,
  KeyRound,
  LogOut,
  Terminal,
  Shield,
} from 'lucide-react';

interface SidebarItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  badge?: string;
}

function SidebarItem({ to, icon, label, isActive, badge }: SidebarItemProps): JSX.Element {
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all group ${
        isActive
          ? 'bg-opsmate-800 text-white shadow-soft'
          : 'text-opsmate-600 hover:bg-opsmate-100 hover:text-opsmate-900'
      }`}
    >
      <span className={isActive ? 'text-opsmate-200' : 'text-opsmate-400 group-hover:text-opsmate-600'}>
        {icon}
      </span>
      <span className="font-medium">{label}</span>
      {badge && (
        <span className="ml-auto text-2xs font-semibold px-1.5 py-0.5 rounded-full bg-opsmate-200 text-opsmate-700">
          {badge}
        </span>
      )}
    </Link>
  );
}

export function Sidebar(): JSX.Element {
  const location = useLocation();
  const { isAuthenticated, isAdmin, logout, apiKey } = useAuth();

  const mainItems = [
    {
      to: '/',
      icon: <MessageSquare size={18} />,
      label: 'Chat',
      isActive: location.pathname === '/',
    },
    {
      to: '/history',
      icon: <History size={18} />,
      label: 'History',
      isActive: location.pathname === '/history',
    },
    {
      to: '/dashboard',
      icon: <BarChart3 size={18} />,
      label: 'Dashboard',
      isActive: location.pathname === '/dashboard',
    },
    {
      to: '/admin',
      icon: <Settings size={18} />,
      label: 'Admin',
      isActive: location.pathname === '/admin',
      badge: isAdmin ? 'Admin' : undefined,
    },
  ];

  return (
    <aside className="w-60 bg-white border-r border-opsmate-200 flex flex-col h-full shrink-0">
      {/* Logo area */}
      <div className="h-14 flex items-center px-4 border-b border-opsmate-200">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-opsmate-800 flex items-center justify-center">
            <Terminal size={14} className="text-opsmate-100" />
          </div>
          <span className="text-sm font-bold text-opsmate-900">OpsMate</span>
        </Link>
      </div>

      {/* Main navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {mainItems.map((item) => (
          <SidebarItem key={item.to} {...item} />
        ))}
      </nav>

      {/* Bottom section - Auth status */}
      <div className="px-3 py-3 border-t border-opsmate-200 space-y-2">
        {isAuthenticated ? (
          <>
            <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-opsmate-50">
              <KeyRound size={14} className="text-opsmate-400 shrink-0" />
              <div className="min-w-0">
                <p className="text-xs font-medium text-opsmate-700 truncate">
                  {apiKey?.slice(0, 8)}...{apiKey?.slice(-4)}
                </p>
                <p className="text-2xs text-opsmate-400">API Key</p>
              </div>
            </div>
            {isAdmin && (
              <div className="flex items-center gap-2 px-3 py-1">
                <Shield size={12} className="text-green-500 shrink-0" />
                <span className="text-2xs font-medium text-green-600">Admin Access</span>
              </div>
            )}
            <button
              onClick={logout}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-opsmate-500 hover:bg-red-50 hover:text-red-600 transition-colors w-full"
            >
              <LogOut size={16} />
              <span>Sign Out</span>
            </button>
          </>
        ) : (
          <Link
            to="/"
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-opsmate-500 hover:bg-opsmate-100 hover:text-opsmate-700 transition-colors"
          >
            <KeyRound size={16} />
            <span>Enter API Key</span>
          </Link>
        )}
      </div>
    </aside>
  );
}

export default Sidebar;
