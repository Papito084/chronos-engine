import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[ChronosEngine UI Error]', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center p-6 bg-terminal-surface border border-trade-sell/30 rounded-lg text-center m-2">
          <AlertTriangle className="w-10 h-10 text-trade-sell mb-3" />
          <h3 className="text-lg font-semibold text-terminal-text mb-1">
            {this.props.fallbackTitle || 'Component Render Error'}
          </h3>
          <p className="text-sm text-terminal-muted max-w-md font-mono mb-4">
            {this.state.error?.message || 'An unexpected exception occurred while rendering.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="flex items-center gap-2 px-4 py-2 bg-terminal-card hover:bg-terminal-hover border border-terminal-border rounded text-sm text-terminal-text transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Reset Component
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
