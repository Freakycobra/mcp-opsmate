import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ModeIndicator } from './ModeIndicator';
import {
  Terminal,
  MessageSquare,
  History,
  BarChart3,
  Settings,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { useMode } from '@/context/ModeContext';

interface NavLinkProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
}

function NavLink({ to, icon, label, isActive }: NavLinkProps): JSX.Element {
  return (
    <Link
      to={to}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        isActive
          ? 'bg-opsmate-200 text-opsmate-900'
          : 'text-opsmate-600 hover:bg-opsmate-100 hover:text-opsmate-800'
      }`}
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </Link>
  );
}

export function Header(): JSX.Element {
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const { error: modeError } = useMode();
  const isConnected = isAuthenticated && !modeError;

  const navItems = [
    { to: '/', icon: <MessageSquare size={16} />, label: 'Chat' },
    { to: '/history', icon: <History size={16} />, label: 'History' },
    { to: '/dashboard', icon: <BarChart3 size={16} />, label: 'Dashboard' },
    { to: '/admin', icon: <Settings size={16} />, label: 'Admin' },
  ];

  return (
    <header className="h-14 bg-white border-b border-opsmate-200 flex items-center px-4 lg:px-6 shrink-0">
      {/* Logo */}
      <Link to="/" className="flex items-center gap-2.5 mr-6 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-opsmate-800 flex items-center justify-center">
          <Terminal size={16} className="text-opsmate-100" />
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-base font-bold text-opsmate-900 tracking-tight">OpsMate</span>
          <span className="text-2xs font-medium text-opsmate-400 uppercase tracking-wider">MCP</span>
        </div>
      </Link>

      {/* Navigation */}
      <nav className="flex items-center gap-1 mr-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            icon={item.icon}
            label={item.label}
            isActive={
              item.to === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(item.to)
            }
          />
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-3">
        {/* Connection status */}
        <div
          className="flex items-center gap-1.5 text-xs text-opsmate-500"
          title={isConnected ? 'Connected to OpsMate server' : 'Disconnected or not authenticated'}
        >
          {isConnected ? (
            <>
              <Wifi size={12} className="text-green-500" />
              <span className="hidden sm:inline">Connected</span>
            </>
          ) : (
            <>
              <WifiOff size={12} className="text-opsmate-400" />
              <span className="hidden sm:inline">Offline</span>
            </>
          )}
        </div>

        {/* Mode indicator */}
        <ModeIndicator />

        {/* Quick-action icon */}
        <Link
          to="/"
          className="w-7 h-7 rounded-lg bg-opsmate-800 flex items-center justify-center hover:bg-opsmate-700 transition-colors"
          title="New Command"
        >
          <Zap size={14} className="text-opsmate-100" />
        </Link>
      </div>
    </header>
  );
}

export default Header;
