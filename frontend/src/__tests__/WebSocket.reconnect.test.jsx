import { useSyncExternalStore } from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { authState, setAuth, authListeners } = vi.hoisted(() => {
  const authState = {
    accessToken: 'token-1',
    isAuthenticated: true,
  };
  const authListeners = new Set();
  const setAuth = (partial) => {
    Object.assign(authState, partial);
    authListeners.forEach((listener) => listener());
  };
  return { authState, setAuth, authListeners };
});

vi.mock('../store/auth', () => ({
  default: (selector) =>
    useSyncExternalStore(
      (listener) => {
        authListeners.add(listener);
        return () => authListeners.delete(listener);
      },
      () => selector(authState),
      () => selector(authState)
    ),
}));

vi.mock('../store/settings', () => ({
  default: (selector) =>
    selector({
      environment: { env_mode: 'aio' },
    }),
}));

vi.mock('../store/channels', () => ({
  default: Object.assign((selector) => selector(channelsState), {
    getState: () => channelsState,
  }),
}));

vi.mock('../store/playlists', () => ({
  default: Object.assign((selector) => selector(playlistsState), {
    getState: () => playlistsState,
  }),
}));

vi.mock('../store/epgs', () => ({
  default: Object.assign((selector) => selector(epgsState), {
    getState: () => epgsState,
  }),
}));

vi.mock('../store/logos', () => ({
  default: Object.assign((selector) => selector(logosState), {
    getState: () => logosState,
  }),
}));

vi.mock('../store/users', () => ({
  default: Object.assign((selector) => selector({ users: [] }), {
    getState: () => ({ users: [] }),
  }),
}));

vi.mock('../store/plugins.jsx', () => ({
  usePluginStore: Object.assign((selector) => selector(pluginState), {
    getState: () => pluginState,
  }),
}));

vi.mock('../api', () => ({
  default: {
    getNotifications: vi.fn(),
  },
}));

vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
    update: vi.fn(),
  },
}));

vi.mock('@mantine/core', () => ({
  Alert: ({ children, title }) => (
    <div data-testid="ws-alert">
      <span data-testid="ws-alert-title">{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
}));

const channelsState = {
  setChannelStats: vi.fn(),
  setVodStats: vi.fn(),
  setTimeshiftStats: vi.fn(),
  fetchChannelProfiles: vi.fn(),
  fetchChannelIds: vi.fn(),
  fetchRecordings: vi.fn(),
  updateChannel: vi.fn(),
  removeRecording: vi.fn(),
  channels: {},
};

const playlistsState = {
  fetchPlaylists: vi.fn(),
  setRefreshProgress: vi.fn(),
  setProfilePreview: vi.fn(),
  updatePlaylist: vi.fn(),
  playlists: {},
};

const epgsState = {
  epgs: {},
  fetchEPGs: vi.fn(),
  fetchEPGData: vi.fn(),
  updateEPG: vi.fn(),
  updateEPGProgress: vi.fn(),
};

const logosState = {
  fetchAllLogos: vi.fn(),
  fetchLogosByIds: vi.fn(),
};

const pluginState = {
  updatePluginTaskProgress: vi.fn(),
  completePluginTask: vi.fn(),
};

class MockWebSocket {
  static instances = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    // Match browsers: close notifies onclose unless the caller cleared it.
    const handler = this.onclose;
    this.onclose = null;
    handler?.({});
  }

  send() {}
}

let useWebSocketHook = () => [false, null, null];
let latestSend = null;

function ReadyProbe() {
  const [ready, send] = useWebSocketHook();
  latestSend = send;
  return (
    <div data-testid="ws-probe" data-ready={ready ? 'yes' : 'no'} />
  );
}

describe('WebsocketProvider reconnect backoff', () => {
  let WebsocketProvider;

  beforeEach(async () => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    authState.accessToken = 'token-1';
    authState.isAuthenticated = true;
    authListeners.clear();
    vi.stubGlobal('WebSocket', MockWebSocket);
    latestSend = null;
    WebsocketProvider = (await import('../WebSocket')).WebsocketProvider;
    useWebSocketHook = (await import('../WebSocketContext')).useWebSocket;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('does not reconnect immediately after a failed connection', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    const first = MockWebSocket.instances[0];

    await act(async () => {
      first.onerror?.(new Event('error'));
      first.onclose?.(new CloseEvent('close'));
    });

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(screen.getByTestId('ws-alert-title')).toHaveTextContent(
      'WebSocket Reconnecting'
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(499);
    });
    expect(MockWebSocket.instances).toHaveLength(1);

    await act(async () => {
      // Half-jitter floor for attempt 0 is 500ms when random is unlucky;
      // advance to the full initial window so a retry is guaranteed.
      await vi.advanceTimersByTimeAsync(501);
    });
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });

  it('keeps retrying after many failures instead of giving up', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    for (let i = 0; i < 8; i++) {
      const socket = MockWebSocket.instances.at(-1);
      await act(async () => {
        socket.onclose?.(new CloseEvent('close'));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
    }

    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(9);
    expect(screen.getByTestId('ws-alert-title')).toHaveTextContent(
      'WebSocket Reconnecting'
    );
    expect(
      screen.queryByText(/WebSocket Connection Failed/i)
    ).not.toBeInTheDocument();
  });

  it('does not open a new socket when isReady flips after a successful connect', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.readyState = MockWebSocket.OPEN;
      first.onopen?.(new Event('open'));
    });

    expect(MockWebSocket.instances).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('does not stack a second retry when close fires twice', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.onclose?.(new CloseEvent('close'));
      first.onclose?.(new CloseEvent('close'));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('rebinds send after the access token changes', async () => {
    render(
      <WebsocketProvider>
        <ReadyProbe />
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.readyState = MockWebSocket.OPEN;
      first.onopen?.(new Event('open'));
    });
    expect(screen.getByTestId('ws-probe')).toHaveAttribute('data-ready', 'yes');
    const sendOnFirstSocket = latestSend;

    await act(async () => {
      setAuth({ accessToken: 'token-2' });
    });

    expect(MockWebSocket.instances).toHaveLength(2);
    expect(screen.getByTestId('ws-probe')).toHaveAttribute('data-ready', 'no');

    const second = MockWebSocket.instances[1];
    const sendSpy = vi.spyOn(second, 'send');
    await act(async () => {
      second.readyState = MockWebSocket.OPEN;
      second.onopen?.(new Event('open'));
    });

    expect(screen.getByTestId('ws-probe')).toHaveAttribute('data-ready', 'yes');
    expect(latestSend).not.toBe(sendOnFirstSocket);
    latestSend('ping');
    expect(sendSpy).toHaveBeenCalledWith('ping');
  });

  it('does not reconnect after logout', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      setAuth({ isAuthenticated: false, accessToken: null });
      // A close event arriving after logout must not schedule another attempt.
      first.onclose?.(new CloseEvent('close'));
    });

    const openSockets = MockWebSocket.instances.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(MockWebSocket.instances).toHaveLength(openSockets);
    expect(screen.queryByTestId('ws-alert')).not.toBeInTheDocument();
  });

  it('cancels a pending backoff timer on logout', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.onclose?.(new CloseEvent('close'));
    });
    expect(screen.getByTestId('ws-alert-title')).toHaveTextContent(
      'WebSocket Reconnecting'
    );

    const socketsWhileWaiting = MockWebSocket.instances.length;
    await act(async () => {
      setAuth({ isAuthenticated: false, accessToken: null });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(MockWebSocket.instances).toHaveLength(socketsWhileWaiting);
    expect(screen.queryByTestId('ws-alert')).not.toBeInTheDocument();
  });

  it('keeps the reconnect banner visible during Reconnect Now', async () => {
    render(
      <WebsocketProvider>
        <div>child</div>
      </WebsocketProvider>
    );

    const first = MockWebSocket.instances[0];
    await act(async () => {
      first.onclose?.(new CloseEvent('close'));
    });

    await act(async () => {
      screen.getByRole('button', { name: /reconnect now/i }).click();
    });

    expect(screen.getByTestId('ws-alert-title')).toHaveTextContent(
      'WebSocket Reconnecting'
    );
    expect(MockWebSocket.instances.length).toBeGreaterThan(1);
  });
});
