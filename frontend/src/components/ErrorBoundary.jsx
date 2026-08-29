import React from 'react';
import { X } from 'lucide-react';

const redactDiagnosticText = (value) => {
  if (!value) return '';
  return String(value)
    .replaceAll(window.location.origin, '')
    .replace(
      /([?&](?:token|access_token|refresh_token|authorization)=)[^\s&)]+/gi,
      '$1[redacted]'
    )
    .replace(/(Bearer\s+)[^\s]+/gi, '$1[redacted]');
};

class ErrorBoundary extends React.Component {
  state = {
    hasError: false,
    error: null,
    errorInfo: null,
    copyStatus: '',
    dismissed: false,
  };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error('ErrorBoundary caught:', {
      boundary: this.props.name || 'application',
      error,
      componentStack: errorInfo.componentStack,
      route: window.location.pathname,
    });

    this.symbolication = this.symbolicate(error, errorInfo);
  }

  symbolicate = async (error, errorInfo) => {
    try {
      const { symbolicateText } = await import('../utils/symbolicate');
      const [decodedStack, decodedComponentStack] = await Promise.all([
        symbolicateText(error?.stack),
        symbolicateText(errorInfo.componentStack),
      ]);
      this.setState({ decodedStack, decodedComponentStack });
    } catch {
      // fall back to the raw stack
    }
  };

  buildDiagnosticReport = () => {
    const { error, errorInfo, decodedStack, decodedComponentStack } =
      this.state;
    return [
      'Dispatcharr frontend error report',
      `Boundary: ${this.props.name || 'application'}`,
      `Time: ${new Date().toISOString()}`,
      `Route: ${window.location.pathname}`,
      `Build mode: ${import.meta.env.MODE}`,
      `Browser: ${navigator.userAgent}`,
      '',
      `Message: ${redactDiagnosticText(error?.message || 'Unknown error')}`,
      '',
      'Error stack:',
      redactDiagnosticText(decodedStack || error?.stack || 'Unavailable'),
      '',
      'React component stack:',
      redactDiagnosticText(
        decodedComponentStack || errorInfo?.componentStack || 'Unavailable'
      ),
    ].join('\n');
  };

  copyDiagnosticReport = async () => {
    if (this.symbolication) {
      await this.symbolication;
    }
    const report = this.buildDiagnosticReport();
    let copied = false;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(report);
        copied = true;
      }
    } catch (error) {
      console.warn('Failed to copy error report with Clipboard API:', error);
    }

    if (!copied) {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = report;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        copied = document.execCommand('copy');
        textarea.remove();
      } catch (error) {
        console.warn('Failed to copy error report:', error);
      }
    }

    this.setState({ copyStatus: copied ? 'Copied!' : 'Copy failed' });
    clearTimeout(this.copyStatusTimer);
    this.copyStatusTimer = setTimeout(
      () => this.setState({ copyStatus: '' }),
      2000
    );
  };

  hide = () => {
    this.setState({ dismissed: true });
  };

  componentWillUnmount() {
    clearTimeout(this.copyStatusTimer);
  }

  render() {
    if (this.state.hasError) {
      if (this.state.dismissed) return null;

      const { inline } = this.props;
      const Heading = inline ? 'h2' : 'h1';
      const panel = (
        <section
          style={{
            background: '#27272a',
            border: '1px solid #52525b',
            borderRadius: 8,
            maxWidth: 640,
            padding: 24,
            pointerEvents: 'auto',
            position: 'relative',
            width: '100%',
          }}
        >
          <button
            type="button"
            onClick={this.hide}
            aria-label="Hide"
            style={{
              background: 'none',
              border: 'none',
              color: '#a1a1aa',
              cursor: 'pointer',
              padding: 4,
              position: 'absolute',
              right: 16,
              top: 16,
            }}
          >
            <X size={18} />
          </button>
          <Heading style={{ marginTop: 0 }}>Something went wrong</Heading>
          <p>{this.state.error?.message || 'An unexpected error occurred.'}</p>
          <p style={{ color: '#a1a1aa', fontSize: 14 }}>
            Copy the diagnostic report when asking for support. It contains
            the error and React component stacks, route, build mode, and
            browser.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <button
              type="button"
              onClick={this.copyDiagnosticReport}
              aria-live="polite"
              style={{ minWidth: 190 }}
            >
              {this.state.copyStatus || 'Copy diagnostic report'}
            </button>
          </div>
        </section>
      );

      // Inline boundaries wrap a page section, not the whole app. Floating
      // (position: fixed) centers the panel over the viewport like a modal
      // without taking the section's layout space or adding a second <main>
      // landmark or <h1> the way the full-page fallback below does. The
      // wrapper ignores pointer events so the rest of the page stays
      // clickable; only the panel itself (pointerEvents: 'auto' above)
      // re-enables them.
      if (inline) {
        return (
          <div
            role="alert"
            style={{
              alignItems: 'center',
              color: '#f4f4f5',
              display: 'flex',
              inset: 0,
              justifyContent: 'center',
              padding: 24,
              pointerEvents: 'none',
              position: 'fixed',
              zIndex: 1000,
            }}
          >
            {panel}
          </div>
        );
      }

      return (
        <main
          role="alert"
          style={{
            alignItems: 'center',
            background: '#18181b',
            color: '#f4f4f5',
            display: 'flex',
            justifyContent: 'center',
            minHeight: '100vh',
            padding: 24,
          }}
        >
          {panel}
        </main>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
