import React, { useEffect, useRef } from 'react';
import {
  BrowserRouter as Router,
  Route,
  Routes,
  Navigate,
  useLocation,
} from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Login, { LoginLoadingCard } from './pages/Login';
import Channels from './pages/Channels';
import ContentSources from './pages/ContentSources';
import Guide from './pages/Guide';
import Stats from './pages/Stats';
import DVR from './pages/DVR';
import Settings from './pages/Settings';
import PluginsPage from './pages/Plugins';
import PluginBrowsePage from './pages/PluginBrowse';
import ConnectPage from './pages/Connect';
import Users from './pages/Users';
import LogosPage from './pages/Logos';
import VODsPage from './pages/VODs';
import useAuthStore from './store/auth';
import useBrowserStorage from './hooks/useBrowserStorage';
import FloatingVideo from './components/FloatingVideo';
import { WebsocketProvider } from './WebSocket';
import { Box, AppShell, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css'; // Ensure Mantine global styles load
import '@mantine/notifications/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/dates/styles.css';
import './index.css';
import mantineTheme from './mantineTheme';
import API from './api';
import { Notifications } from '@mantine/notifications';
import M3URefreshNotification from './components/M3URefreshNotification';
import { defaultRoute, getSafeNextPath } from './utils/loginRedirect';
import 'allotment/dist/style.css';

const drawerWidth = 240;
const miniDrawerWidth = 60;

const LoginRedirect = () => {
  const location = useLocation();
  const target = getSafeNextPath(location.pathname + location.search);
  const next = target ? `?next=${encodeURIComponent(target)}` : '';
  return <Navigate to={`/login${next}`} replace />;
};

const App = () => {
  const [open, setOpen] = useBrowserStorage('dispatcharr_sidebar_open', true);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isInitialized = useAuthStore((s) => s.isInitialized);
  const authReady = isAuthenticated && isInitialized;
  const isCheckingAuth = useAuthStore((s) => s.isCheckingAuth);
  const logout = useAuthStore((s) => s.logout);
  const initData = useAuthStore((s) => s.initData);
  const initializeAuth = useAuthStore((s) => s.initializeAuth);
  const setSuperuserStatus = useAuthStore((s) => s.setSuperuserStatus);

  const authCheckStarted = useRef(false);
  const superuserCheckStarted = useRef(false);

  const toggleDrawer = () => {
    setOpen((prev) => !prev);
  };

  // Check if a superuser exists on first load.
  useEffect(() => {
    if (superuserCheckStarted.current) return;
    superuserCheckStarted.current = true;

    async function checkSuperuser() {
      try {
        const response = await API.fetchSuperUser();
        setSuperuserStatus(response);
      } catch (error) {
        console.error('Error checking superuser status:', error);
        // Preserve the existing fail-open UI behavior if the status check fails.
        setSuperuserStatus({ superuser_exists: true });
        // If authentication error, redirect to login
        if (error.status === 401) {
          localStorage.removeItem('accessToken');
          localStorage.removeItem('refreshToken');
          localStorage.removeItem('tokenExpiration');
          window.location.href = '/login';
        }
      }
    }
    checkSuperuser();
  }, [setSuperuserStatus]);

  // Authentication check
  useEffect(() => {
    if (authCheckStarted.current) return;
    authCheckStarted.current = true;

    const checkAuth = async () => {
      try {
        const loggedIn = await initializeAuth();
        if (loggedIn) {
          await initData();
          // Logos are now loaded at the end of initData, no need for background loading
        } else {
          await logout();
        }
      } catch (error) {
        console.error('Auth check failed:', error);
        await logout();
      }
    };

    checkAuth();
  }, [initializeAuth, initData, logout]);

  return (
    <MantineProvider
      defaultColorScheme="dark"
      theme={mantineTheme}
      withGlobalStyles
      withNormalizeCSS
    >
      <WebsocketProvider>
        <Router>
          <AppShell
            header={{
              height: 0,
            }}
            navbar={{
              width: authReady ? (open ? drawerWidth : miniDrawerWidth) : 0,
            }}
          >
            {authReady && (
              <Sidebar
                drawerWidth={drawerWidth}
                miniDrawerWidth={miniDrawerWidth}
                collapsed={!open}
                toggleDrawer={toggleDrawer}
              />
            )}

            <AppShell.Main>
              <Box
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  // transition: 'margin-left 0.3s',
                  backgroundColor: '#18181b',
                  height: '100vh',
                  color: 'white',
                }}
              >
                <Box sx={{ p: 2, flex: 1, overflow: 'auto' }}>
                  {isCheckingAuth ? (
                    <LoginLoadingCard />
                  ) : (
                    <Routes>
                      {authReady ? (
                        <>
                          <Route path="/channels" element={<Channels />} />
                          <Route
                            path="/sources"
                            element={<ContentSources />}
                          />
                          <Route path="/guide" element={<Guide />} />
                          <Route path="/dvr" element={<DVR />} />
                          <Route path="/stats" element={<Stats />} />
                          <Route
                            path="/plugins/browse"
                            element={<PluginBrowsePage />}
                          />
                          <Route path="/plugins" element={<PluginsPage />} />
                          <Route path="/connect" element={<ConnectPage />} />
                          <Route path="/users" element={<Users />} />
                          <Route path="/settings" element={<Settings />} />
                          <Route path="/logos" element={<LogosPage />} />
                          <Route path="/vods" element={<VODsPage />} />
                        </>
                      ) : (
                        <Route path="/login" element={<Login />} />
                      )}
                      <Route
                        path="*"
                        element={
                          authReady ? (
                            <Navigate to={defaultRoute} replace />
                          ) : (
                            <LoginRedirect />
                          )
                        }
                      />
                    </Routes>
                  )}
                </Box>
              </Box>
            </AppShell.Main>
          </AppShell>
          <M3URefreshNotification />
          <Notifications containerWidth={350} />
        </Router>
      </WebsocketProvider>

      <FloatingVideo />
    </MantineProvider>
  );
};

export default App;
