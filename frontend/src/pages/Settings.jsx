import React, { Suspense, useState } from 'react';
import {
  Accordion,
  AccordionControl,
  AccordionItem,
  AccordionPanel,
  Box,
  Center,
  Text,
  Loader
} from '@mantine/core';
const UserAgentsTable = React.lazy(() =>
  import('../components/tables/UserAgentsTable.jsx'));
const StreamProfilesTable = React.lazy(() =>
  import('../components/tables/StreamProfilesTable.jsx'));
const BackupManager = React.lazy(() =>
  import('../components/backups/BackupManager.jsx'));
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import UiSettingsForm from '../components/forms/settings/UiSettingsForm.jsx';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
const NetworkAccessForm = React.lazy(() =>
  import('../components/forms/settings/NetworkAccessForm.jsx'));
const ProxySettingsForm = React.lazy(() =>
  import('../components/forms/settings/ProxySettingsForm.jsx'));
const StreamSettingsForm = React.lazy(() =>
  import('../components/forms/settings/StreamSettingsForm.jsx'));
const DvrSettingsForm = React.lazy(() =>
  import('../components/forms/settings/DvrSettingsForm.jsx'));
const SystemSettingsForm = React.lazy(() =>
  import('../components/forms/settings/SystemSettingsForm.jsx'));

const SettingsPage = () => {
  const authUser = useAuthStore((s) => s.user);

  const [accordianValue, setAccordianValue] = useState(null);

  return (
    <Center p={10}>
      <Box w={'100%'} maw={800}>
        <Accordion
          variant="separated"
          defaultValue="ui-settings"
          onChange={setAccordianValue}
          miw={400}
        >
          <AccordionItem value="ui-settings">
            <AccordionControl>UI Settings</AccordionControl>
            <AccordionPanel>
              <UiSettingsForm
                  active={accordianValue === 'ui-settings'} />
            </AccordionPanel>
          </AccordionItem>

          {authUser.user_level == USER_LEVELS.ADMIN && (
            <>
              <AccordionItem value="dvr-settings">
                <AccordionControl>DVR</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <DvrSettingsForm
                        active={accordianValue === 'dvr-settings'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="stream-settings">
                <AccordionControl>Stream Settings</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <StreamSettingsForm
                        active={accordianValue === 'stream-settings'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="system-settings">
                <AccordionControl>System Settings</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <SystemSettingsForm
                        active={accordianValue === 'system-settings'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="user-agents">
                <AccordionControl>User-Agents</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <UserAgentsTable
                          active={accordianValue === 'user-agents'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="stream-profiles">
                <AccordionControl>Stream Profiles</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <StreamProfilesTable
                          active={accordianValue === 'stream-profiles'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="network-access">
                <AccordionControl>
                  <Box>Network Access</Box>
                  {accordianValue === 'network-access' && (
                    <Box>
                      <Text size="sm">Comma-Delimited CIDR ranges</Text>
                    </Box>
                  )}
                </AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <NetworkAccessForm
                          active={accordianValue === 'network-access'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="proxy-settings">
                <AccordionControl>
                  <Box>Proxy Settings</Box>
                </AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <ProxySettingsForm
                          active={accordianValue === 'proxy-settings'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>

              <AccordionItem value="backups">
                <AccordionControl>Backup & Restore</AccordionControl>
                <AccordionPanel>
                  <ErrorBoundary>
                    <Suspense fallback={<Loader />}>
                      <BackupManager active={accordianValue === 'backups'} />
                    </Suspense>
                  </ErrorBoundary>
                </AccordionPanel>
              </AccordionItem>
            </>
          )}
        </Accordion>
      </Box>
    </Center>
  );
};

export default SettingsPage;
