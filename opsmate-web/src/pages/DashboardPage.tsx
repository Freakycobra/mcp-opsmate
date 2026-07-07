import React from 'react';
import { Dashboard } from '@/components/Dashboard';
import { BarChart3, RefreshCw } from 'lucide-react';

export function DashboardPage(): JSX.Element {
  return (
    <div className="h-full overflow-y-auto scrollbar-thin p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-bold text-opsmate-900 flex items-center gap-2">
            <BarChart3 size={20} className="text-opsmate-500" />
            Dashboard
          </h1>
          <p className="text-sm text-opsmate-500">
            Real-time metrics and system health overview
          </p>
        </div>
        <div className="flex items-center gap-2 text-2xs text-opsmate-400">
          <RefreshCw size={12} className="animate-spin-slow" />
          <span>Auto-refreshes every 60s</span>
        </div>
      </div>
      <Dashboard />
    </div>
  );
}

export default DashboardPage;
