// frontend/src/App.js
import React, { useEffect, useState } from 'react';
import {
  BrowserRouter as Router,
  Route,
  Routes,
  Navigate,
} from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Login from './pages/Login';
import Channels from './pages/Channels';
import M3U from './pages/M3U';
import EPG from './pages/EPG';
import Guide from './pages/Guide';
import Stats from './pages/Stats';
import Settings from './pages/Settings';
import StreamProfiles from './pages/StreamProfiles';
import useAuthStore from './store/auth';
import FloatingVideo from './components/FloatingVideo';
import { WebsocketProvider } from './WebSocket';
import { Box, AppShell, MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css'; // Ensure Mantine global styles load
import '@mantine/notifications/styles.css';
import 'mantine-react-table/styles.css';
import '@mantine/dropzone/styles.css';
import './index.css';
import mantineTheme from './mantineTheme';
import API from './api';
import { Notifications } from '@mantine/notifications';
import M3URefreshNotification from './components/M3URefreshNotification';
import 'allotment/dist/style.css';

const drawerWidth = 240;
const miniDrawerWidth = 60;
const defaultRoute = '/channels';

const App = () => {
  const [open, setOpen] = useState(true);
  const {
    isAuthenticated,
    setIsAuthenticated,
    logout,
    initData,
    initializeAuth,
    setSuperuserExists,
  } = useAuthStore();

  const toggleDrawer = () => {
    setOpen(!open);
  };

  // Check if a superuser exists on first load.
  useEffect(() => {
    async function checkSuperuser() {
      try {
        const response = await API.fetchSuperUser();
        if (!response.superuser_exists) {
          setSuperuserExists(false);
        }
      } catch (error) {
        console.error('Error checking superuser status:', error);
      }
    }
    checkSuperuser();
  }, []);

  // Authentication check
  useEffect(() => {
    const checkAuth = async () => {
      const loggedIn = await initializeAuth();
      if (loggedIn) {
        await initData();
        setIsAuthenticated(true);
      } else {
        await logout();
      }
    };
    checkAuth();
  }, [initializeAuth, initData, setIsAuthenticated, logout]);

  return (
    <MantineProvider
      defaultColorScheme="dark"
      theme={mantineTheme}
      withGlobalStyles
      withNormalizeCSS
    >
      <WebsocketProvider>
        <Notifications containerWidth={350} />
        <Router>
          <AppShell
            header={{
              height: 0,
            }}
            navbar={{
              width: open ? drawerWidth : miniDrawerWidth,
            }}
          >
            <Sidebar
              drawerWidth
              miniDrawerWidth
              collapsed={!open}
              toggleDrawer={toggleDrawer}
            />

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
                  <Routes>
                    {isAuthenticated ? (
                      <>
                        <Route path="/channels" element={<Channels />} />
                        <Route path="/m3u" element={<M3U />} />
                        <Route path="/epg" element={<EPG />} />
                        <Route
                          path="/stream-profiles"
                          element={<StreamProfiles />}
                        />
                        <Route path="/guide" element={<Guide />} />
                        <Route path="/stats" element={<Stats />} />
                        <Route path="/settings" element={<Settings />} />
                      </>
                    ) : (
                      <Route path="/login" element={<Login needsSuperuser />} />
                    )}
                    <Route
                      path="*"
                      element={
                        <Navigate
                          to={isAuthenticated ? defaultRoute : '/login'}
                          replace
                        />
                      }
                    />
                  </Routes>
                </Box>
              </Box>
            </AppShell.Main>
          </AppShell>
          <M3URefreshNotification />
        </Router>

        <FloatingVideo />
      </WebsocketProvider>
    </MantineProvider>
  );
};

export default App;
